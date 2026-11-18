// Numbers as JavaScript reads and writes them, and as Python writes them.
//
// A model file is JSON written by JavaScript, and much of what a run reports
// (labels, the CSV export, messages) quotes numbers the way JavaScript's
// `String(x)` prints them: the shortest digits that read back as the same
// number, laid out by JavaScript's rule -- plain from 1e-6 up to 1e21 and
// exponential beyond (`0.000015`, `1e-7`, `1.5e+21`). Reading follows
// `Number(v)`: an empty string is 0, anything that is not a number is NaN.
// The solvers' messages are the Python engine's, which quote a float as its
// `repr` (`py_repr`).

#pragma once

#include <string>
#include <string_view>
#include <utility>

#include "util/json.hpp"

namespace kompartment {

/// The shortest decimal digits that round-trip to the positive finite `x`, and
/// the exponent `n` with `x = 0.digits × 10^n`.
std::pair<std::string, int> shortest_digits(double x);

/// `x` as JavaScript's `String(x)` writes it; NaN and the infinities as `null`,
/// which is what `JSON.stringify` makes of them.
std::string js_number(double x);
std::string js_number(long long x);

/// What JavaScript's `String(v)` makes of a value a model's JSON can hold, for messages
/// that quote what was written: `NaN`, `Infinity`, `null`, lists joined by commas.
std::string js_text(const Json& v);
std::string js_text(double x);

/// `String(v)` for what a model file holds where an equation is expected: strings as they
/// are, numbers as JavaScript prints them.
std::string js_str(const Json& v);

/// JavaScript's `Number(v)` for what a model file can hold: null and `""` are 0, booleans
/// 1 and 0, text that is not a number NaN.
double js_number_of(const Json& v);
double js_number_of(std::string_view text);

/// A switch as the application reads one from a file: on unless it says `false`,
/// `"false"` or 0 when the default is on; off unless it says `true`, `"true"` or 1 when
/// the default is off.
bool js_truthy_switch(const Json& v, bool fallback);

/// `Math.floor(x + 0.5)`.
double round_half_up(double x);

/// `x.toPrecision(p)`: the exact binary value rounded to p digits, a tie going up.
std::string js_to_precision(double x, int p);

/// `x.toFixed(digits)`: the exact value rounded half up; `String(x)` from 1e21.
std::string js_to_fixed(double x, int digits);

/// `x.toExponential(f)`: the exact value rounded to f + 1 digits, a tie going up.
std::string js_to_exponential(double x, int f);

/// A float as Python's `repr` writes it: fixed between 1e-4 and 1e16 (`0.0001`, `1.0`),
/// `1e-05` / `1.5e+16` outside, `nan`, `inf`.
std::string py_repr(double x);

/// Text without the white space JavaScript's `trim()` takes from its ends.
std::string_view js_trim(std::string_view s);

}  // namespace kompartment
