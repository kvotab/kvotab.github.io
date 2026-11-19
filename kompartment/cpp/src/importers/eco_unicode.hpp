// The case tables the Ecolego importer's Python `str.lower()` and `str.upper()` stand on, as
// the Julia package has them (utf8proc's simple mappings and categories), written by
// tools/eco_unicode.jl into eco_unicode.cpp.

#pragma once

#include <cstddef>
#include <cstdint>

namespace kompartment::eco_unicode {

/// The code points first, first + stride, ... last, each mapped by adding delta.
struct CaseRun {
    std::uint32_t first, last;
    std::int32_t delta;
    std::uint32_t stride;
};

/// The code points first to last.
struct Range {
    std::uint32_t first, last;
};

extern const CaseRun LOWER[];
extern const std::size_t LOWER_COUNT;
extern const CaseRun UPPER[];
extern const std::size_t UPPER_COUNT;
/// `isuppercase(c) || islowercase(c)` or category Lt.
extern const Range CASED[];
extern const std::size_t CASED_COUNT;
/// Categories Mn, Me, Cf, Lm and Sk.
extern const Range IGNORABLE[];
extern const std::size_t IGNORABLE_COUNT;

/// Julia's `lowercase(c)` and `uppercase(c)`.
char32_t lower(char32_t c);
char32_t upper(char32_t c);
/// Whether `c` is cased (`_eco_is_cased`), and whether its category is one a capital sigma's
/// neighbour may be skipped for (the categories of `_eco_is_case_ignorable`).
bool is_cased(char32_t c);
bool is_ignorable_category(char32_t c);

}  // namespace kompartment::eco_unicode
