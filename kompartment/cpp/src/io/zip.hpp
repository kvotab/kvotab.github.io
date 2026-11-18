// A ZIP archive, written as the application's `zip` lays one out: local headers,
// deflate or stored data, a central directory and an end record; names flagged
// as UTF-8, version 2.0, no extra fields, comments or ZIP64.

#pragma once

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace kompartment {

/// The check sum a ZIP entry carries.
std::uint32_t crc32(const std::string& bytes);

/// `raw` deflated (no header), or empty when this build has no zlib.
std::string deflate_bytes(const std::string& raw, int level = 6);

/// Entries (name, bytes) as an archive. An entry is stored when deflate does not make it
/// smaller, and when it would take the deflated total past `inflate_limit` (what the
/// application's reader inflates of one archive). `modified`: seconds since the epoch.
std::string zip_archive(const std::vector<std::pair<std::string, std::string>>& entries, bool compress = true,
                        double modified = 0, std::uint64_t inflate_limit = 256ull * 1024 * 1024);

}  // namespace kompartment
