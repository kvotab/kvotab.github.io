#include "io/zip.hpp"

#include <array>
#include <ctime>
#include <stdexcept>

#ifdef KOMPARTMENT_HAVE_ZLIB
#include <zlib.h>
#endif

namespace kompartment {

namespace {

void put16(std::string& out, std::uint32_t v) {
    out.push_back(static_cast<char>(v & 0xff));
    out.push_back(static_cast<char>((v >> 8) & 0xff));
}
void put32(std::string& out, std::uint32_t v) {
    put16(out, v & 0xffff);
    put16(out, (v >> 16) & 0xffff);
}

}  // namespace

std::uint32_t crc32(const std::string& bytes) {
    static const std::array<std::uint32_t, 256> table = [] {
        std::array<std::uint32_t, 256> t{};
        for (std::uint32_t i = 0; i < 256; i++) {
            std::uint32_t c = i;
            for (int k = 0; k < 8; k++) c = (c & 1) ? 0xedb88320u ^ (c >> 1) : c >> 1;
            t[i] = c;
        }
        return t;
    }();
    std::uint32_t c = 0xffffffffu;
    for (unsigned char b : bytes) c = table[(c ^ b) & 0xff] ^ (c >> 8);
    return c ^ 0xffffffffu;
}

std::string deflate_bytes(const std::string& raw, int level) {
#ifdef KOMPARTMENT_HAVE_ZLIB
    z_stream s{};
    if (deflateInit2(&s, level, Z_DEFLATED, -15, 8, Z_DEFAULT_STRATEGY) != Z_OK) return "";
    std::string out;
    out.resize(deflateBound(&s, static_cast<uLong>(raw.size())));
    s.next_in = reinterpret_cast<Bytef*>(const_cast<char*>(raw.data()));
    s.avail_in = static_cast<uInt>(raw.size());
    s.next_out = reinterpret_cast<Bytef*>(out.data());
    s.avail_out = static_cast<uInt>(out.size());
    int rc = deflate(&s, Z_FINISH);
    std::size_t made = s.total_out;
    deflateEnd(&s);
    if (rc != Z_STREAM_END) return "";
    out.resize(made);
    return out;
#else
    (void)raw;
    (void)level;
    return "";
#endif
}

std::string zip_archive(const std::vector<std::pair<std::string, std::string>>& entries, bool compress, double modified,
                        std::uint64_t inflate_limit) {
    // A date and time as a ZIP entry carries them: MS-DOS, local time, no year before 1980.
    std::time_t when = static_cast<std::time_t>(modified);
    std::tm tm{};
#if defined(_WIN32)
    localtime_s(&tm, &when);
#else
    localtime_r(&when, &tm);
#endif
    int year = std::max(1980, tm.tm_year + 1900);
    std::uint32_t date = static_cast<std::uint32_t>(((year - 1980) << 9) | ((tm.tm_mon + 1) << 5) | std::max(1, tm.tm_mday)) & 0xffff;
    std::uint32_t time = static_cast<std::uint32_t>((tm.tm_hour << 11) | (tm.tm_min << 5) | (tm.tm_sec >> 1)) & 0xffff;
    std::string io, central;
    std::uint32_t count = 0;
    std::uint64_t inflated = 0;
    for (const auto& [name, raw] : entries) {
        if (raw.size() > 0xffffffffull) throw std::runtime_error("'" + name + "' is " + std::to_string(raw.size()) + " bytes, which needs ZIP64");
        bool fits = inflated + raw.size() <= inflate_limit;
        std::string packed = (compress && fits) ? deflate_bytes(raw) : std::string();
        bool use = !packed.empty() && packed.size() < raw.size();
        if (use) inflated += raw.size();
        const std::string& data = use ? packed : raw;
        std::uint32_t method = use ? 8 : 0;
        std::uint32_t crc = crc32(raw);
        std::uint32_t offset = static_cast<std::uint32_t>(io.size());
        put32(io, 0x04034b50);
        put16(io, 20);
        put16(io, 0x0800);
        put16(io, method);
        put16(io, time);
        put16(io, date);
        put32(io, crc);
        put32(io, static_cast<std::uint32_t>(data.size()));
        put32(io, static_cast<std::uint32_t>(raw.size()));
        put16(io, static_cast<std::uint32_t>(name.size()));
        put16(io, 0);
        io += name;
        io += data;
        put32(central, 0x02014b50);
        put16(central, 20);
        put16(central, 20);
        put16(central, 0x0800);
        put16(central, method);
        put16(central, time);
        put16(central, date);
        put32(central, crc);
        put32(central, static_cast<std::uint32_t>(data.size()));
        put32(central, static_cast<std::uint32_t>(raw.size()));
        put16(central, static_cast<std::uint32_t>(name.size()));
        put16(central, 0);
        put16(central, 0);
        put16(central, 0);
        put16(central, 0);
        put32(central, 0);
        put32(central, offset);
        central += name;
        count++;
    }
    std::uint32_t cd_offset = static_cast<std::uint32_t>(io.size());
    io += central;
    put32(io, 0x06054b50);
    put16(io, 0);
    put16(io, 0);
    put16(io, count);
    put16(io, count);
    put32(io, static_cast<std::uint32_t>(central.size()));
    put32(io, cd_offset);
    put16(io, 0);
    return io;
}

}  // namespace kompartment
