// What the Ecolego importer takes from the rest of Kompartment, and the rules of JavaScript (and
// of Python) it leans on: a port of the Julia package's importers/eco_maps.jl (itself a port of
// the Python package's `_eco_maps.py`).
//
// Two kinds of thing: the small mappers the application's src/io/eco.js imports from other
// modules -- how Ecolego spells an interpolation rule, a reduction, an extreme and an event
// direction, the solvers' names, the length of a year, what each kind of block is called -- and
// the language rules the importer's output depends on: `Number('')` is 0, `trim()` knows its
// own set of spaces, a string's length counts UTF-16 code units, an object lists its
// integer-like keys first, `localeCompare` sorts by the Unicode collation, a plain object
// answers `constructor`, `toPrecision` rounds a tie away from zero -- and Python's own
// `str.lower()` and `str.upper()`, since the reference is the Python port.
//
// Text is UTF-8 bytes; positions are 0-based byte offsets and ranges half-open.

#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "util/json.hpp"

namespace kompartment::eco {

// --- what the importer refuses with ----------------------------------------------------------

/// A file the importer cannot read: not an Ecolego model, an Ecolego 4/5 `<sheet>`, an archive
/// with no model in it, XML that does not parse, or a name no model can hold. `message` holds the
/// words whole (`what()` stops at a NUL byte, which a file's own text may put in them).
struct EcoImportError : std::runtime_error {
    std::string message;
    explicit EcoImportError(const std::string& m) : std::runtime_error(m), message(m) {}
};

/// The Julia package's `ArgumentError` (Python's `ValueError`): a modification date past what a
/// JavaScript `Date` holds.
struct EcoArgumentError : std::invalid_argument {
    std::string message;
    explicit EcoArgumentError(const std::string& m) : std::invalid_argument(m), message(m) {}
};

/// The Julia package's `ErrorException` (Python's `NotImplementedError`): an archive entry that
/// asks for a ZIP version past what `zipfile` reads.
struct EcoUnsupportedError : std::runtime_error {
    std::string message;
    explicit EcoUnsupportedError(const std::string& m) : std::runtime_error(m), message(m) {}
};

// --- strings ---------------------------------------------------------------------------------

/// How many bytes the JavaScript white space starting at byte `i` of `s[0, n)` takes (0: none).
std::size_t js_space_bytes(std::string_view s, std::size_t i, std::size_t n);
inline std::size_t js_space_bytes(std::string_view s, std::size_t i) { return js_space_bytes(s, i, s.size()); }

/// The bytes [a, b) of `s` less JavaScript's white space at either end.
std::pair<std::size_t, std::size_t> js_trim_range(std::string_view s, std::size_t a, std::size_t b);

/// `text.trim()`, with JavaScript's idea of white space.
std::string js_trim(std::string_view s);

/// `text.length`: UTF-16 code units.
std::size_t js_len(std::string_view s);

/// How many UTF-16 code units the characters before byte `i` take.
std::size_t utf16_pos(std::string_view s, std::size_t i);

/// `text.replace(/[^A-Za-z0-9_]/g, '_')`, on UTF-16 code units.
std::string js_identifier(std::string_view s);

inline bool is_ascii_digit(unsigned char b) { return b >= '0' && b <= '9'; }
inline bool is_alpha(unsigned char b) { return (b >= 'A' && b <= 'Z') || (b >= 'a' && b <= 'z'); }
inline bool is_hex(unsigned char b) { return is_ascii_digit(b) || (b >= 'A' && b <= 'F') || (b >= 'a' && b <= 'f'); }
inline bool is_ident_char(unsigned char b) { return is_alpha(b) || is_ascii_digit(b) || b == '_'; }
inline bool is_name_part(unsigned char b) { return is_ident_char(b) || b == '.'; }

/// Whether `s` is the ASCII word `w`, ASCII letters compared regardless of case.
bool ascii_ieq(std::string_view s, std::string_view w);

/// ASCII letters lowered, everything else as it is.
std::string ascii_lower(std::string_view s);

/// Whether a capital sigma's neighbour `c` is skipped in deciding whether the sigma ends a word
/// (`_eco_is_case_ignorable`).
bool is_case_ignorable(char32_t c);

/// `s.upper()` and `s.lower()` as Python maps them.
std::string py_upper(std::string_view s);
std::string py_lower(std::string_view s);

/// Julia's `strip(s)`: its white space (`isspace`) off both ends.
std::string julia_strip(std::string_view s);

/// The code point of the UTF-8 character at byte `i` of valid text, and its length.
char32_t char_at(std::string_view s, std::size_t i, std::size_t& len);
/// A code point as UTF-8.
void put_char(std::string& out, char32_t c);

// --- numbers ---------------------------------------------------------------------------------

/// A decimal literal as JavaScript reads one: `[+-]?(Infinity|digits[.digits]|.digits)(e[+-]digits)?`.
bool is_js_decimal(std::string_view s);
/// `float(s)` for a decimal literal: the nearest double, infinity past the range.
double parse_decimal(std::string_view s);
/// A whole number written in base 2, 8 or 16 (digits checked by the caller), as the double
/// nearest it (`Float64(::BigInt)`).
double radix_to_double(std::string_view digits, int base);

/// JavaScript's `Number(v)` as the importer's Python port reads it.
double to_number(std::string_view s);
double to_number(const Json& v);
inline double to_number(const std::optional<std::string>& s) { return s ? to_number(std::string_view(*s)) : 0.0; }

/// `Number.isFinite(v)`.
bool is_finite_number(const Json& v);

/// `Math.round(x)` and `Math.floor(x)`.
double js_round(double x);
double js_floor(double x);

/// `String(x)` for what the importer writes into its messages.
std::string js_string(const Json& v);
std::string js_string(double x);

/// `Number(x.toPrecision(digits))`: the double's exact value rounded, a tie away from zero.
double round_significant(double x, int digits);

/// `x.toExponential()`.
std::string to_exponential(double x);

// --- dates -----------------------------------------------------------------------------------

/// `new Date(ms).toISOString().slice(0, 10)`; EcoArgumentError("Invalid time value") past what
/// a `Date` holds.
std::string iso_date(double ms);

// --- objects ---------------------------------------------------------------------------------

/// `d` with its keys in the order a JavaScript object lists them.
Json js_object_order(const Json& d);

/// What a plain JavaScript object answers for a key: its own value, what every object inherits
/// from `Object.prototype` (`constructor`, `toString`, ... and `__proto__`), or nothing.
struct PlainValue {
    enum class Kind { None, Own, Inherited } kind = Kind::None;
    std::string value;          // the own value, or the inherited key
    bool is_function = false;   // inherited: a function (all but `__proto__`)
};

// --- localeCompare ---------------------------------------------------------------------------

/// `a.localeCompare(b) < 0` in Node, for what an index list can be called (`_eco_collation_key`).
bool collation_less(std::string_view a, std::string_view b);

// --- the mappers eco.js imports --------------------------------------------------------------

/// Seconds per year: this tool's (365.25 days) for a model in days or less, Ecolego's otherwise.
double seconds_per_year(std::string_view unit);

PlainValue interpolation_from_eco(const std::optional<std::string>& name);
std::optional<std::string> operation_from_eco(const std::optional<std::string>& name);
/// The recorder kind for Ecolego's block type, or nothing.
std::optional<std::string> kind_from_eco(std::string_view type);
const std::vector<std::string>& event_fields(std::string_view kind);
const std::vector<std::string>& equation_fields(std::string_view kind);
std::optional<std::string> extreme_from_eco(const std::optional<std::string>& name);
PlainValue direction_from_eco(const std::optional<std::string>& name);
/// Both of a solver's names, `stiff, NDF (ndf)`.
std::string solver_name(const Json& solver_id);
/// What each kind of block is called, in the plural ("" for none).
std::string kind_label(std::string_view kind);
/// Each collection's kind of block ("" for none).
std::string singular(std::string_view collection);

}  // namespace kompartment::eco
