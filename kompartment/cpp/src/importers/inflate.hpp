// Raw deflate data inflated as the Ecolego importer's archive reader inflates it (the Julia
// package's `_eco_raw_inflate`, which is CPython's `zlib.decompressobj(-15).decompress(raw,
// max_length)` on zlib): the output, at most `max_length` bytes and grown the way the Julia
// package grows it, whether the stream ended, and zlib's message for damage.
//
// It is an inflater of this engine's own that inflates, written to zlib's inflate.c (1.3.1, which
// the Julia package inflates with): the same states in the same order, so that it reads as far,
// stops at the same byte and gives up with the same words on every stream -- whatever zlib the
// build found, if any: a system's zlib may word its errors otherwise (Apple's says "invalid
// literal/length/distance code" where zlib says "invalid literal/length code" or "invalid
// distance code"). The build's zlib inflates only when asked, for the tests to check one against
// the other.

#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <string_view>

namespace kompartment::eco {

struct InflateResult {
    std::string out;
    bool eof = false;                     // the stream's last block ended
    std::optional<std::string> damage;    // zlib's message, as it says it
};

/// Whether this build inflates with zlib.
bool have_zlib();

/// `src` inflated, at most `max_length` bytes (the buffer sized from `size_hint` and grown as
/// the Julia package grows it); by the build's zlib instead when `with_zlib` and the build has it.
InflateResult raw_inflate(std::string_view src, std::size_t max_length, std::size_t size_hint, bool with_zlib = false);

}  // namespace kompartment::eco
