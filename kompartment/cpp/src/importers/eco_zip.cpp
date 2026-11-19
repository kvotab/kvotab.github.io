#include "importers/eco_zip.hpp"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string_view>

#include "importers/eco_maps.hpp"
#include "importers/eco_text.hpp"
#include "importers/inflate.hpp"
#include "io/zip.hpp"
#include "util/json.hpp"

namespace kompartment::eco {

namespace {

// Python's integers, as far as an archive's offsets need them: a ZIP64 field holds up to
// 2^64 - 1, and an offset less what lies before the archive can be negative.
struct I128 {
    std::uint64_t hi = 0, lo = 0;   // two's complement

    I128() = default;
    I128(std::int64_t v) : hi(v < 0 ? ~std::uint64_t{0} : 0), lo(static_cast<std::uint64_t>(v)) {}
    static I128 u64(std::uint64_t v) {
        I128 r;
        r.lo = v;
        return r;
    }
    bool negative() const { return (hi >> 63) != 0; }
    friend I128 operator+(I128 a, I128 b) {
        I128 r;
        r.lo = a.lo + b.lo;
        r.hi = a.hi + b.hi + (r.lo < a.lo ? 1 : 0);
        return r;
    }
    friend I128 operator-(I128 a, I128 b) {
        I128 r;
        r.lo = a.lo - b.lo;
        r.hi = a.hi - b.hi - (a.lo < b.lo ? 1 : 0);
        return r;
    }
    friend bool operator==(I128 a, I128 b) { return a.hi == b.hi && a.lo == b.lo; }
    friend bool operator<(I128 a, I128 b) {
        if (a.hi != b.hi) return static_cast<std::int64_t>(a.hi) < static_cast<std::int64_t>(b.hi);
        return a.lo < b.lo;
    }
    friend bool operator>(I128 a, I128 b) { return b < a; }
    // The value, which the caller knows to lie in [0, 2^63).
    std::size_t index() const { return static_cast<std::size_t>(lo); }
    std::string str() const {
        I128 v = *this;
        const bool neg = v.negative();
        if (neg) v = I128(0) - v;
        // Divide the 128-bit magnitude by 10 repeatedly.
        std::string digits;
        std::uint64_t h = v.hi, l = v.lo;
        do {
            // (h:l) / 10, a 32-bit limb at a time.
            std::uint64_t rem = 0;
            std::uint32_t limbs[4] = {static_cast<std::uint32_t>(h >> 32), static_cast<std::uint32_t>(h), static_cast<std::uint32_t>(l >> 32),
                                      static_cast<std::uint32_t>(l)};
            for (std::uint32_t& limb : limbs) {
                const std::uint64_t cur = (rem << 32) | limb;
                limb = static_cast<std::uint32_t>(cur / 10);
                rem = cur % 10;
            }
            h = (static_cast<std::uint64_t>(limbs[0]) << 32) | limbs[1];
            l = (static_cast<std::uint64_t>(limbs[2]) << 32) | limbs[3];
            digits.push_back(static_cast<char>('0' + rem));
        } while (h != 0 || l != 0);
        if (neg) digits.push_back('-');
        std::reverse(digits.begin(), digits.end());
        return digits;
    }
};

// What zipfile raises, before the importer says it in its own words.
struct BadZip : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// One entry of the central directory, as zipfile's ZipInfo has it.
struct ZipInfo {
    std::string orig_name;
    bool utf8 = false;
    std::uint16_t flag_bits = 0;
    std::uint16_t compress_type = 0;
    I128 compress_size, file_size, header_offset;
};

inline unsigned byte(std::string_view d, std::size_t i) { return static_cast<unsigned char>(d[i]); }
inline std::uint32_t le16(std::string_view d, std::size_t i) { return byte(d, i) | (byte(d, i + 1) << 8); }
inline std::uint32_t le32(std::string_view d, std::size_t i) {
    return le16(d, i) | (static_cast<std::uint32_t>(le16(d, i + 2)) << 16);
}
inline std::uint64_t le64(std::string_view d, std::size_t i) {
    return static_cast<std::uint64_t>(le32(d, i)) | (static_cast<std::uint64_t>(le32(d, i + 4)) << 32);
}
inline bool sig(std::string_view d, std::size_t i, const char* s) { return std::memcmp(d.data() + i, s, 4) == 0; }

// `BytesIO.seek(offset, 2)` followed by `read(count)`: a position before the start is the start.
std::pair<std::size_t, std::size_t> read_from_end(std::string_view data, std::int64_t offset, std::int64_t count) {
    const std::int64_t n = static_cast<std::int64_t>(data.size());
    const std::int64_t pos = std::max<std::int64_t>(n + offset, 0);
    return {static_cast<std::size_t>(pos), static_cast<std::size_t>(std::min(pos + count, n))};
}

struct EndRecord {
    bool sig64 = false;
    I128 size, offset, location;
};

EndRecord end_record64(std::string_view data, std::int64_t offset, const EndRecord& endrec) {
    auto [a, b] = read_from_end(data, offset - 20, 20);
    if (b - a != 20) return endrec;
    if (!sig(data, a, "PK\x06\x07")) return endrec;
    const std::uint32_t diskno = le32(data, a + 4);
    const std::uint32_t disks = le32(data, a + 16);
    if (diskno != 0 || disks > 1) throw BadZip("zipfiles that span multiple disks are not supported");
    auto [c, d] = read_from_end(data, offset - 20 - 56, 56);
    if (d - c != 56) return endrec;
    if (!sig(data, c, "PK\x06\x06")) return endrec;
    EndRecord r;
    r.sig64 = true;
    r.size = I128::u64(le64(data, c + 40));
    r.offset = I128::u64(le64(data, c + 48));
    r.location = endrec.location;
    return r;
}

// The end of central directory record as zipfile's `_EndRecData` finds it, or none for no ZIP
// archive.
std::optional<EndRecord> end_record(std::string_view data) {
    const std::int64_t filesize = static_cast<std::int64_t>(data.size());
    {
        auto [a, b] = read_from_end(data, -22, std::int64_t{1} << 62);
        if (b - a == 22 && sig(data, a, "PK\x05\x06") && byte(data, a + 20) == 0 && byte(data, a + 21) == 0) {
            EndRecord e;
            e.size = I128::u64(le32(data, a + 12));
            e.offset = I128::u64(le32(data, a + 16));
            e.location = I128(filesize - 22);
            return end_record64(data, -22, e);
        }
    }
    const std::int64_t max_comment_start = std::max<std::int64_t>(filesize - (1 << 16) - 22, 0);
    // The last whole signature in the tail.
    for (std::int64_t i = filesize - 4; i >= max_comment_start; i--) {
        if (!sig(data, static_cast<std::size_t>(i), "PK\x05\x06")) continue;
        if (filesize - i < 22) return std::nullopt;
        const std::size_t r = static_cast<std::size_t>(i);
        EndRecord e;
        e.size = I128::u64(le32(data, r + 12));
        e.offset = I128::u64(le32(data, r + 16));
        e.location = I128(i);
        return end_record64(data, i - filesize, e);
    }
    return std::nullopt;
}

// ZipInfo._decodeExtra: the ZIP64 sizes and offset, and the checks on the unicode path field
// (whose name zipfile uses for nothing the importer reads).
void decode_extra(std::string_view extra, const std::string& name, ZipInfo& info) {
    std::size_t k = 0;
    while (extra.size() - k >= 4 && k <= extra.size()) {
        const std::uint32_t tp = le16(extra, k);
        const std::uint32_t ln = le16(extra, k + 2);
        if (ln + 4 > extra.size() - k) {
            char buf[80];
            std::snprintf(buf, sizeof buf, "Corrupt extra field %04x (size=%u)", tp, ln);
            throw BadZip(buf);
        }
        const std::string_view body = extra.substr(k + 4, ln);
        if (tp == 0x0001) {
            std::size_t q = 0;
            std::string field;
            auto next8 = [&]() {
                if (!(q + 8 <= body.size())) throw BadZip("Corrupt zip64 extra field. " + field + " not found.");
                const I128 v = I128::u64(le64(body, q));
                q += 8;
                return v;
            };
            // Only a field of 0xFFFFFFFF is read again, as the Julia package reads it: Python
            // 3.12's zipfile reads one already set to 0xFFFFFFFFFFFFFFFF (by an earlier ZIP64
            // field) again too, and so imports an archive the Julia package refuses as one that
            // "expands to 17592186044416 MB".
            const I128 all32 = I128::u64(0xffffffffu);
            if (info.file_size == all32) {
                field = "File size";
                info.file_size = next8();
            }
            if (info.compress_size == all32) {
                field = "Compress size";
                info.compress_size = next8();
            }
            if (info.header_offset == all32) {
                field = "Header offset";
                info.header_offset = next8();
            }
        } else if (tp == 0x7075) {
            if (body.size() < 5) throw BadZip("Corrupt unicode path extra field (0x7075)");
            const unsigned up_version = byte(body, 0);
            const std::uint32_t up_crc = le32(body, 1);
            if (up_version == 1 && up_crc == crc32(name)) {
                try {
                    utf8_strict(body.substr(5));
                } catch (const EcoDecodeError&) {
                    throw BadZip("Corrupt unicode path extra field (0x7075): invalid utf-8 bytes");
                }
            }
        }
        k += ln + 4;
    }
}

// zipfile's `_RealGetContents`: the entries of the central directory.
std::vector<ZipInfo> central_directory(std::string_view data) {
    std::optional<EndRecord> endrec = end_record(data);
    if (!endrec) throw BadZip("File is not a zip file");
    const I128 size_cd = endrec->size;
    const I128 offset_cd = endrec->offset;
    I128 concat = endrec->location - size_cd - offset_cd;
    if (endrec->sig64) concat = concat - I128(56 + 20);
    const I128 start_dir = offset_cd + concat;
    if (start_dir.negative()) throw BadZip("Bad offset for central directory");
    const I128 n = I128(static_cast<std::int64_t>(data.size()));
    const I128 from = start_dir < n ? start_dir : n;
    const I128 end_ = (start_dir + size_cd) < n ? start_dir + size_cd : n;
    const std::string_view cd = data.substr(from.index(), end_.index() - from.index());
    std::size_t p = 0;   // the read position in `cd`
    auto take = [&](std::size_t k) {
        const std::size_t a = p;
        p = std::min(p + k, cd.size());
        return cd.substr(a, p - a);
    };
    std::vector<ZipInfo> infos;
    I128 total(0);
    while (total < size_cd) {
        const std::string_view centdir = take(46);
        if (centdir.size() != 46) throw BadZip("Truncated central directory");
        if (!sig(centdir, 0, "PK\x01\x02")) throw BadZip("Bad magic number for central directory");
        const unsigned extract_version = byte(centdir, 6);
        ZipInfo info;
        info.flag_bits = static_cast<std::uint16_t>(le16(centdir, 8));
        info.compress_type = static_cast<std::uint16_t>(le16(centdir, 10));
        info.compress_size = I128::u64(le32(centdir, 20));
        info.file_size = I128::u64(le32(centdir, 24));
        const std::uint32_t name_len = le16(centdir, 28);
        const std::uint32_t extra_len = le16(centdir, 30);
        const std::uint32_t comment_len = le16(centdir, 32);
        info.header_offset = I128::u64(le32(centdir, 42));
        info.orig_name = std::string(take(name_len));
        info.utf8 = (info.flag_bits & 0x0800) != 0;
        // zipfile decodes a flagged name strictly, and fails on one that is not UTF-8.
        if (info.utf8) utf8_strict(info.orig_name);
        const std::string extra(take(extra_len));
        take(comment_len);
        if (extract_version > 63) {
            char buf[64];
            std::snprintf(buf, sizeof buf, "zip file version %.1f", extract_version / 10.0);
            throw EcoUnsupportedError(buf);
        }
        decode_extra(extra, info.orig_name, info);
        info.header_offset = info.header_offset + concat;
        infos.push_back(std::move(info));
        total = total + I128(static_cast<std::int64_t>(46 + name_len + extra_len + comment_len));
    }
    return infos;
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
    std::vector<ZipInfo> infos;
    try {
        infos = central_directory(data);
    } catch (const BadZip& e) {
        const std::string msg = e.what();
        if (msg == "File is not a zip file")
            throw EcoImportError("This does not look like a ZIP archive. An Ecolego project (.eco) is a zipped project folder; a bare "
                                 "model.xml should be opened directly instead.");
        if (msg == "Bad magic number for central directory" || msg == "Truncated central directory")
            throw EcoImportError("The central directory is damaged");
        throw EcoImportError("The archive is damaged: " + msg);
    } catch (const EcoDecodeError& e) {
        throw EcoImportError("The archive is damaged: " + e.message);
    }

    EcoArchive archive;
    archive.bytes_ = std::move(data);
    archive.with_zlib_ = with_zlib;
    const std::string_view bytes(archive.bytes_);
    const std::size_t size = bytes.size();
    const I128 size128(static_cast<std::int64_t>(size));
    for (const ZipInfo& info : infos) {
        const std::string name = without_bom(utf8_replace(info.orig_name));
        if ((info.flag_bits & 0x1) != 0)
            throw EcoImportError("'" + name + "' is encrypted. Ecolego can obfuscate a project on save; re-save it without that "
                                 "option, or export the model, before importing.");
        if (!name.empty() && name.back() == '/') continue;   // a directory
        const I128 offset = info.header_offset;
        if (offset.negative() || offset + I128(30) > size128)
            throw EcoImportError("'" + name + "' says its data begins at byte " + offset.str() + ", which is outside this " +
                                 std::to_string(size) + "-byte archive.");
        const std::size_t o = offset.index();
        if (!sig(bytes, o, "PK\x03\x04")) throw EcoImportError("The local header for '" + name + "' is damaged");
        const std::uint32_t name_len = le16(bytes, o + 26);
        const std::uint32_t extra_len = le16(bytes, o + 28);
        const I128 start = offset + I128(static_cast<std::int64_t>(30 + name_len + extra_len));
        const I128 compressed = info.compress_size;
        if (start > size128 || start + compressed > size128)
            throw EcoImportError("'" + name + "' claims " + compressed.str() + " bytes from " + start.str() + ", which runs past the end of this " +
                                 std::to_string(size) + "-byte archive.");
        EcoArchive::Entry entry;
        entry.start = start.index();
        entry.stop = (start + compressed).index();
        entry.expected = info.file_size.lo;   // a size is never more than 2^64 - 1
        const unsigned method = info.compress_type;
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
