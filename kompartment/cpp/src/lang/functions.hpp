// The built-in functions of the equation language (src/parser/functions.js).
//
// The same names, aliases and arities, and the same answers: JavaScript's
// where C++ would differ (`sqrt(-1)` is NaN, `1/0` Infinity) and numpy's
// where the Python engine's numbers are the reference (`min` and `max` keep
// the first of two equal zeros, `sign(-0)` is 0). Every function here takes
// and returns doubles one at a time; the evaluator calls them element by
// element. The transcendental functions are the C library's, as numpy's and
// the Julia engine's are.

#pragma once

#include <cmath>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace kompartment {

inline constexpr double AVOGADRO = 6.02214179e23;
inline constexpr double EPS = 2.220446049250313e-16;          // 2^-52
inline constexpr double SECONDS_PER_YEAR = 365.25 * 24 * 3600;
inline const double LN2 = std::log(2.0);

/// What the parser needs to know of a function: its canonical key and arity.
struct FunctionSpec {
    std::string key;
    int arity;
    std::optional<int> max_arity;   // none: as many as given
    bool needs_context;             // time(), start_time(), end_time()
};

/// The function a name calls (an alias resolved), or none.
std::optional<FunctionSpec> lookup_function(std::string_view name);

/// Whether a name is one the language keeps to itself: its functions and kept words.
bool is_reserved_name(std::string_view name);
const std::vector<std::string>& reserved_names();

// --- the arithmetic, one number at a time -------------------------------------------------------

inline bool js_truth(double x) { return x != 0.0; }   // NaN is true, as in JavaScript
inline double b2f(bool b) { return b ? 1.0 : 0.0; }

/// `Math.round`: the nearest integer, halves towards positive infinity; -0 for a negative
/// that rounds to zero.
inline double kf_round(double a) {
    double f = std::floor(a);
    double r = f + b2f(a - f >= 0.5);
    return r == 0 ? std::copysign(0.0, a) : r;
}

inline double kf_abs(double x) { return std::fabs(x); }
inline double kf_sqrt(double x) { return x < 0 ? std::numeric_limits<double>::quiet_NaN() : std::sqrt(x); }
inline double kf_exp(double x) { return std::exp(x); }
inline double kf_log(double x) { return std::log(x); }
inline double kf_log10(double x) { return std::log10(x); }
inline double kf_log2(double x) { return std::log2(x); }
inline double cpow(double a, double b) { return std::pow(a, b); }

/// numpy's `power` with one exponent for every element: the exponents 2, 0.5 and -1 are
/// worked out as a square, a square root and a reciprocal, every other one by the C
/// library's pow. (numpy takes that short cut only when the exponent is one number; an
/// exponent per element always goes to pow, which differs from the short cut in the last
/// bit for about one argument in a thousand.)
inline double np_pow(double a, double b) {
    if (b == 2.0) return a * a;
    if (b == 0.5) return kf_sqrt(a);
    if (b == -1.0) return 1.0 / a;
    return cpow(a, b);
}
/// `Math.pow` (the Python engine's `js_pow`): numpy's power, except that 1 and -1 to an
/// infinite or NaN power are NaN. `kf_jspow` with an exponent per element, `kf_jspow1`
/// with one exponent for every element.
inline double kf_jspow(double a, double b) {
    return (std::fabs(a) == 1.0 && !std::isfinite(b)) ? std::numeric_limits<double>::quiet_NaN() : cpow(a, b);
}
inline double kf_jspow1(double a, double b) {
    return (std::fabs(a) == 1.0 && !std::isfinite(b)) ? std::numeric_limits<double>::quiet_NaN() : np_pow(a, b);
}
inline double kf_hypot(double a, double b) { return std::hypot(a, b); }
inline double kf_ceil(double x) { return std::ceil(x); }
inline double kf_floor(double x) { return std::floor(x); }
inline double kf_fix(double x) { return std::trunc(x); }
inline double kf_sign(double x) { return x > 0 ? 1.0 : x < 0 ? -1.0 : x == 0 ? 0.0 : x; }
inline double kf_ulp(double x) { return std::fabs(x) * EPS; }
inline double kf_mod(double a, double b) { return b == 0 ? a : a - b * std::floor(a / b); }
inline double kf_rem(double a, double b) { return b == 0 ? std::numeric_limits<double>::quiet_NaN() : a - b * std::trunc(a / b); }
inline double kf_sin(double x) { return std::sin(x); }
inline double kf_cos(double x) { return std::cos(x); }
inline double kf_tan(double x) { return std::tan(x); }
inline double kf_asin(double x) { return std::asin(x); }
inline double kf_acos(double x) { return std::acos(x); }
inline double kf_atan(double x) { return std::atan(x); }
inline double kf_atan2(double a, double b) { return std::atan2(a, b); }
inline double kf_sinh(double x) { return std::sinh(x); }
inline double kf_cosh(double x) { return std::cosh(x); }
inline double kf_tanh(double x) { return std::tanh(x); }
inline double kf_asinh(double x) { return std::asinh(x); }
inline double kf_acosh(double x) { return std::acosh(x); }
inline double kf_atanh(double x) { return std::atanh(x); }

/// numpy's `minimum`/`maximum`: the first NaN where either is one; of two equal values the
/// first, but for -0 below +0 (as JavaScript's `Math.min`).
inline double kf_min(double a, double b) {
    if (std::isnan(a)) return a;
    if (std::isnan(b)) return b;
    if (a < b) return a;
    if (b < a) return b;
    return (a == 0.0 && std::signbit(b)) ? b : a;
}
inline double kf_max(double a, double b) {
    if (std::isnan(a)) return a;
    if (std::isnan(b)) return b;
    if (a > b) return a;
    if (b > a) return b;
    return (a == 0.0 && std::signbit(a)) ? b : a;
}
inline double kf_not(double a) { return b2f(a == 0.0); }

inline constexpr int FACTORIAL_MAX = 170;
double kf_factorial(double n);
inline double kf_binomial(double n, double k) { return kf_factorial(n) / (kf_factorial(k) * kf_factorial(n - k)); }

inline double kf_ramp_down(double x, double s, double e) {
    double lo = kf_min(s, e);
    double hi = kf_max(s, e);
    if (!(x > lo)) return 1.0;
    if (x >= hi) return 0.0;
    return (hi - x) / (hi - lo);
}
inline double kf_ramp_up(double x, double s, double e) { return 1.0 - kf_ramp_down(x, s, e); }

/// `smoothDown`; `one_s`: the steepness is one number for every element (numpy's short cut applies).
inline double kf_smooth_down(double x, double X, double s, bool one_s = true) {
    if (!(x > 0)) return 1.0;
    if (!(X > 0)) return 0.0;
    double r = one_s ? np_pow(x / X, 2 * s) : cpow(x / X, 2 * s);
    return std::isfinite(r) ? 1.0 / (1.0 + r) : 0.0;
}
inline double kf_smooth_up(double x, double X, double s, bool one_s = true) { return 1.0 - kf_smooth_down(x, X, s, one_s); }

inline double kf_bq2mole(double bq, double half_life_years) { return (bq * half_life_years * SECONDS_PER_YEAR) / (LN2 * AVOGADRO); }
inline double kf_mole2bq(double mole, double half_life_years) { return (LN2 * mole * AVOGADRO) / (half_life_years * SECONDS_PER_YEAR); }

/// erf and erfc, exactly as the application computes them: Cody's rational form near zero,
/// Numerical Recipes' Chebyshev fit beyond.
double kf_erf(double x);
double kf_erfc(double x);

// --- the functions of many arguments ---------------------------------------------------------------

/// `[...values].sort((a, b) => a - b)` as V8 does it, NaN included.
std::vector<double> js_sort_numbers(const double* values, std::size_t n);

/// The percentile of a sample: sorted values at the midpoints (i - 0.5)/n, the extremes
/// pinned to 0 and 1, straight lines between.
double kf_percentile(double phi, const double* xs, std::size_t n);

/// A transport operation read outside its path.
struct TransportRangeError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// `args`: the cells' values, then the position (0..1).
double kf_transport_point(const double* args, std::size_t count);
/// `args`: the cells' values, then the range's two ends.
double kf_transport_range(const double* args, std::size_t count, bool mean);

}  // namespace kompartment
