// The entries of an Ecolego archive (.eco, .eas), read as the Python port of the importer reads
// them (the Julia package's importers/eco_zip.jl): the central directory as Python's `zipfile`
// reads it (end record found the same way, entries counted by the directory's size, ZIP64 sizes
// and offsets, an archive with something before it), with its refusals, and the data through
// each entry's local header -- stored and deflated entries only, no CRC check, a deflated `.xml`
// entry inflated up front and everything else when first asked for (an assessment's results
// never are), one decompression allowance for the whole archive, and the application's messages
// for what cannot be read.

#pragma once

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace kompartment::eco {

/// The most one entry, and the whole archive, may expand to.
inline constexpr std::uint64_t MAX_INFLATED = 256ull * 1024 * 1024;

/// The entries of a ZIP archive, by name, most of them decompressed only when asked for. A name
/// repeated in the directory keeps its first place and its last entry.
class EcoArchive {
public:
    const std::vector<std::string>& names() const { return names_; }
    /// An entry's bytes, inflated when first asked for; EcoImportError when they cannot be.
    const std::string& get(const std::string& name);
    /// How many bytes have been inflated so far.
    std::uint64_t spent() const { return spent_; }

private:
    friend EcoArchive unzip(std::string data, bool with_zlib);
    struct Entry {
        std::optional<std::string> data;
        std::size_t start = 0, stop = 0;   // where the stored or compressed bytes lie
        bool deflated = false;
        std::uint64_t expected = 0;        // the size the directory gives
    };
    std::string inflate(const std::string& name, std::size_t start, std::size_t stop, std::uint64_t expected);
    void check_allowance(const std::string& name, std::uint64_t size) const;

    std::string bytes_;
    std::vector<std::string> names_;
    std::map<std::string, Entry> entries_;
    std::uint64_t spent_ = 0;
    bool with_zlib_ = false;
};

/// The entries of a ZIP archive; EcoImportError for one that cannot be read, EcoUnsupportedError
/// for an entry that needs a later ZIP than `zipfile` reads. Inflated by the engine's own inflater
/// (importers/inflate.hpp); `with_zlib` by the build's zlib instead, where it has one (the tests').
EcoArchive unzip(std::string data, bool with_zlib = false);

}  // namespace kompartment::eco
