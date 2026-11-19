#include "importers/eco_zip.hpp"

#include <algorithm>
#include <cstring>
#include <optional>
#include <string_view>
#include <utility>

#include "importers/eco_maps.hpp"
#include "importers/eco_text.hpp"
#include "importers/inflate.hpp"
#include "util/json.hpp"

namespace kompartment::eco {

namespace {

// A 64-bit count from the file is kept whole, where the application holds it as a double: no
// comparison here can tell the two apart -- one that large is past the end of any archive either
// way, and each is made so that it cannot overflow -- and a message writes it through
// `js_string`, rounded to a double as `Number()` rounds it.

inline unsigned byte(std::string_view d, std::uint64_t i) { return static_cast<unsigned char>(d[static_cast<std::size_t>(i)]); }
inline std::uint32_t le16(std::string_view d, std::uint64_t i) { return byte(d, i) | (byte(d, i + 1) << 8); }
inline std::uint32_t le32(std::string_view d, std::uint64_t i) {
    return le16(d, i) | (static_cast<std::uint32_t>(le16(d, i + 2)) << 16);
}
inline std::uint64_t le64(std::string_view d, std::uint64_t i) {
    return static_cast<std::uint64_t>(le32(d, i)) | (static_cast<std::uint64_t>(le32(d, i + 4)) << 32);
}
inline bool sig(std::string_view d, std::uint64_t i, const char* s) {
    return std::memcmp(d.data() + static_cast<std::size_t>(i), s, 4) == 0;
}
// Whether `count` bytes from `at` lie inside `size`.
inline bool inside(std::uint64_t at, std::uint64_t count, std::uint64_t size) { return at <= size && count <= size - at; }
std::string number(std::uint64_t v) { return js_string(static_cast<double>(v)); }

struct EndRecord {
    std::uint64_t at = 0, count = 0, offset = 0;
};

// `findEOCD`: the end of central directory record in the last 64 KB, the one nearest the end;
// none when there is none.
std::optional<EndRecord> end_record(std::string_view data) {
    const std::int64_t n = static_cast<std::int64_t>(data.size());
    const std::int64_t low = std::max<std::int64_t>(0, n - 0x10000 - 22);
    for (std::int64_t p = n - 22; p >= low; p--) {
        const std::uint64_t q = static_cast<std::uint64_t>(p);
        if (sig(data, q, "PK\x05\x06")) return EndRecord{q, le16(data, q + 10), le32(data, q + 16)};
    }
    return std::nullopt;
}

// `findZip64`: the ZIP64 end record the locator before the end record points at, as (count,
// offset); none when there is none.
std::optional<std::pair<std::uint64_t, std::uint64_t>> zip64_end(std::string_view data, std::uint64_t end_at) {
    const std::uint64_t n = data.size();
    if (end_at < 20) return std::nullopt;
    const std::uint64_t locator = end_at - 20;
    if (!inside(locator, 20, n)) return std::nullopt;
    if (!sig(data, locator, "PK\x06\x07")) return std::nullopt;
    const std::uint64_t at = le64(data, locator + 8);
    // 56 bytes: through the central directory offset, the last field wanted.
    if (at > (std::uint64_t{1} << 53) - 1 || !inside(at, 56, n))
        throw EcoImportError("This archive says its ZIP64 directory is at byte " + std::to_string(at) + ", which is outside its own " +
                             std::to_string(n) + " bytes.");
    if (!sig(data, at, "PK\x06\x06")) return std::nullopt;
    return std::make_pair(le64(data, at + 32), le64(data, at + 48));
}

struct Sizes {
    std::uint64_t expected, compressed, offset;
};

// `readZip64Extra`: the sizes and offset a central record left at 0xFFFFFFFF, from the first ZIP64
// record in its extra field -- the uncompressed size, the compressed size and the offset, those
// that are saturated, in that order. Any record after the first is not read.
Sizes zip64_sizes(std::string_view data, std::uint64_t start, std::uint64_t length, Sizes s, const std::string& name) {
    std::uint64_t p = start;
    // The walk is clamped to the archive, and each 64-bit read to its record.
    const std::uint64_t end = std::min<std::uint64_t>(start + length, data.size());
    while (p + 4 <= end) {
        const std::uint32_t kind = le16(data, p);
        const std::uint32_t size = le16(data, p + 2);
        if (kind == 0x0001) {
            std::uint64_t q = p + 4;
            const std::uint64_t stop = std::min<std::uint64_t>(p + 4 + size, end);
            auto take = [&]() {
                if (q + 8 > stop)
                    throw EcoImportError("The ZIP64 record for '" + name + "' says it is " + std::to_string(size) +
                                         " bytes long but does not hold the sizes it promises; the archive looks damaged.");
                const std::uint64_t v = le64(data, q);
                q += 8;
                return v;
            };
            if (s.expected == 0xffffffffu) s.expected = take();
            if (s.compressed == 0xffffffffu) s.compressed = take();
            if (s.offset == 0xffffffffu) s.offset = take();
            break;
        }
        p += 4 + size;
    }
    return s;
}

std::string mb(double x) { return js_string(js_round(x / 1048576)); }

}  // namespace

void EcoArchive::check_allowance(const std::string& name, std::uint64_t size) const {
    const std::uint64_t left = MAX_INFLATED - spent_;
    if (size <= left) return;
    throw EcoImportError("'" + name + "' takes this archive past the " + mb(static_cast<double>(MAX_INFLATED)) +
                         " MB this reader will decompress in total: " + mb(static_cast<double>(spent_)) +
                         " MB have come out already and this entry adds " + mb(static_cast<double>(size)) +
                         " more. No real project expands that far, so the archive is either damaged or built to exhaust memory.");
}

std::string EcoArchive::inflate(const std::string& name, std::size_t start, std::size_t stop, std::uint64_t expected) {
    if (expected > MAX_INFLATED)
        throw EcoImportError("'" + name + "' says it expands to " + mb(static_cast<double>(expected)) + " MB, past the " +
                             mb(static_cast<double>(MAX_INFLATED)) + " MB this reader will decompress. No real model is that large.");
    check_allowance(name, expected);
    const std::uint64_t limit = std::min(MAX_INFLATED, MAX_INFLATED - spent_);
    InflateResult r = raw_inflate(std::string_view(bytes_).substr(start, stop - start), static_cast<std::size_t>(limit + 1),
                                  static_cast<std::size_t>(expected), with_zlib_);
    if (r.damage) {
        std::string said = *r.damage;
        if (said == "invalid block type") said = "Invalid block type";
        else if (said == "invalid stored block lengths") said = "Stored block length check failed";
        else if (said == "invalid distance too far back") said = "Back-reference points before the output";
        throw EcoImportError("Could not decompress '" + name + "': " + said);
    }
    if (r.out.size() > limit)
        throw EcoImportError("Could not decompress '" + name + "': the entry expands to more than " + mb(static_cast<double>(limit)) +
                             " MB, which is far larger than any real model -- the archive is either damaged or built to exhaust memory");
    if (!r.eof) throw EcoImportError("Could not decompress '" + name + "': Compressed data ended unexpectedly");
    check_allowance(name, r.out.size());
    spent_ += r.out.size();
    if (expected != 0 && r.out.size() != expected)
        throw EcoImportError("'" + name + "' inflated to " + std::to_string(r.out.size()) + " bytes but the directory says " +
                             std::to_string(expected) + "; the archive looks damaged.");
    return std::move(r.out);
}

const std::string& EcoArchive::get(const std::string& name) {
    Entry& e = entries_.at(name);
    if (!e.data) {
        if (e.deflated) e.data = inflate(name, e.start, e.stop, e.expected);
        else e.data = bytes_.substr(e.start, e.stop - e.start);
    }
    return *e.data;
}

EcoArchive unzip(std::string data, bool with_zlib) {
    EcoArchive archive;
    archive.bytes_ = std::move(data);
    archive.with_zlib_ = with_zlib;
    const std::string_view bytes(archive.bytes_);
    const std::uint64_t size = bytes.size();

    const std::optional<EndRecord> found = end_record(bytes);
    if (!found)
        throw EcoImportError("This does not look like a ZIP archive. An Ecolego project (.eco) is a zipped project folder; a bare "
                             "model.xml should be opened directly instead.");
    std::uint64_t entry_count = found->count, p = found->offset;
    // ZIP64, for the rare enormous project.
    if (entry_count == 0xffff || p == 0xffffffffu) {
        if (auto z64 = zip64_end(bytes, found->at)) {
            entry_count = z64->first;
            p = z64->second;
        }
    }

    for (std::uint64_t i = 0; i < entry_count; i++) {
        if (!inside(p, 46, size) || !sig(bytes, p, "PK\x01\x02")) throw EcoImportError("The central directory is damaged");
        const std::uint32_t flags = le16(bytes, p + 8);
        const std::uint32_t method = le16(bytes, p + 10);
        Sizes s{le32(bytes, p + 24), le32(bytes, p + 20), le32(bytes, p + 42)};
        const std::uint32_t name_len = le16(bytes, p + 28);
        const std::uint32_t extra_len = le16(bytes, p + 30);
        const std::uint32_t comment_len = le16(bytes, p + 32);
        // The record's three variable parts have to fit too.
        if (p + 46 + name_len + extra_len + comment_len > size)
            throw EcoImportError("The central directory runs past the end of this " + std::to_string(size) + "-byte archive");
        const std::string name = without_bom(utf8_replace(bytes.substr(static_cast<std::size_t>(p + 46), name_len)));
        if ((flags & 0x1) != 0)
            throw EcoImportError("'" + name + "' is encrypted. Ecolego can obfuscate a project on save; re-save it without that "
                                 "option, or export the model, before importing.");
        // ZIP64 extended information, when the 32-bit fields are saturated.
        if (s.compressed == 0xffffffffu || s.expected == 0xffffffffu || s.offset == 0xffffffffu)
            s = zip64_sizes(bytes, p + 46 + name_len, extra_len, s, name);
        p += 46 + name_len + extra_len + comment_len;
        if (!name.empty() && name.back() == '/') continue;   // a directory
        if (!inside(s.offset, 30, size))
            throw EcoImportError("'" + name + "' says its data begins at byte " + number(s.offset) + ", which is outside this " +
                                 std::to_string(size) + "-byte archive.");
        // The local header repeats the name and extra field, and its extra field length can
        // differ from the central one.
        const std::uint64_t o = s.offset;
        if (!sig(bytes, o, "PK\x03\x04")) throw EcoImportError("The local header for '" + name + "' is damaged");
        const std::uint64_t start = o + 30 + le16(bytes, o + 26) + le16(bytes, o + 28);
        if (!inside(start, s.compressed, size))
            throw EcoImportError("'" + name + "' claims " + number(s.compressed) + " bytes from " + std::to_string(start) +
                                 ", which runs past the end of this " + std::to_string(size) + "-byte archive.");
        EcoArchive::Entry entry;
        entry.start = static_cast<std::size_t>(start);
        entry.stop = static_cast<std::size_t>(start + s.compressed);
        entry.expected = s.expected;
        if (method == 0) {
            entry.deflated = false;
        } else if (method == 8) {
            entry.deflated = true;
            const std::string low = py_lower(name);
            if (low.size() >= 4 && low.compare(low.size() - 4, 4, ".xml") == 0)
                entry.data = archive.inflate(name, entry.start, entry.stop, entry.expected);
        } else {
            throw EcoImportError("'" + name + "' uses compression method " + std::to_string(method) +
                                 ", which is not supported (only stored and deflate are).");
        }
        if (archive.entries_.find(name) == archive.entries_.end()) archive.names_.push_back(name);
        archive.entries_[name] = std::move(entry);
    }
    return archive;
}

}  // namespace kompartment::eco
