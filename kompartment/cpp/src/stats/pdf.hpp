// Probability distributions on a parameter, as Kompartment reads and draws them:
// the Julia package's stats/pdf.jl (the Python package's `kompartment/stats/pdf.py`,
// the application's `src/domain/pdf.js`) -- which kinds there are, whether one is
// filled in, its forward and inverse CDF and the two probabilities a truncation
// leaves.
//
// A distribution is a dictionary, as a model file stores it:
//
//     {"kind": "logt", "params": {"min": 7e-12, "max": 5e-11, "mode": 1e-11},
//      "values": null, "trmin": null, "trmax": null, "pmin": null, "pmax": null,
//      "group": null, "inorder": true, "pos": 0}
//
// Every function is the Julia one step for step, down to the order of the
// operations, so that a value drawn here is the value the other engines draw:
// V8's `js_exp` and `js_log`, the C library's exp and log in the normal CDF and
// quantile (stats/normal.hpp), and JavaScript's rules where a value is not a plain
// number -- `null` counts as 0 in arithmetic and a missing key as NaN, `Math.max`
// of a NaN is NaN -- so a distribution that is only half filled in gives what it
// gives in the application rather than raising.
//
// JavaScript's `undefined` (a key that is not there, as distinct from `null`) is a
// null pointer here: `pd_prop` gives one for a missing key.

#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

// --- JavaScript's rules, where Julia's differ ----------------------------------------------------

/// `obj?.[key]`: the value, or none (`undefined`) for a key, or an object, that is not there.
const Json* pd_prop(const Json* obj, std::string_view key);
inline const Json* pd_prop(const Json& obj, std::string_view key) { return pd_prop(&obj, key); }

/// `v == null`: `null` or `undefined`.
inline bool pd_nullish(const Json* v) { return v == nullptr || v->is_null(); }

/// JavaScript's ToBoolean: an empty dictionary or list is true, 0, NaN and '' are not.
bool pd_truthy(const Json* v);
inline bool pd_truthy(const Json& v) { return pd_truthy(&v); }

/// `String.prototype.trim`.
std::string_view pd_js_trim(std::string_view s);

/// `Number(s)` for a string: JavaScript's StringToNumber. (A decimal Julia's `parse` cannot
/// read -- one that overflows, or underflows to zero -- raises its `ArgumentError`, as the
/// Julia package does: JavaScript reads `1e400` as Infinity.)
double pd_string_to_number(std::string_view s);

/// `String(x)` for a number: NaN and the infinities included.
std::string pd_js_number_str(double x);

/// `String(v)` for anything a model file can hold (`undefined` for none).
std::string pd_js_str(const Json* v);
inline std::string pd_js_str(const Json& v) { return pd_js_str(&v); }

/// `Number(v)`: `null` is 0, `undefined` NaN, a string read as JavaScript reads one.
double pd_to_number(const Json* v);
inline double pd_to_number(const Json& v) { return pd_to_number(&v); }

/// A distribution's parameter as JavaScript's arithmetic reads it: `null` is 0, missing NaN.
inline double pd_param(const Json* p, std::string_view key) { return pd_to_number(pd_prop(p, key)); }

/// `Math.max(a, b)` and `Math.min(a, b)`: NaN if either is, and +0 above -0.
double pd_jmax(double a, double b);
double pd_jmin(double a, double b);

/// `Math.sqrt`: NaN below zero.
double pd_sqrt(double x);

/// Julia's `strip`: the white space Julia's `isspace` knows taken from both ends.
std::string_view jl_strip(std::string_view s);

/// Julia's `py_float` (engine/farfield_domain.jl): Python's `float()` of a value, NaN for
/// what it cannot read -- text by Julia's `tryparse`, hexadecimal and `inf` included.
double jl_py_float(const Json& v);

// --- the kinds -----------------------------------------------------------------------------------

/// What each kind takes, in the application's order (`PDF_KINDS`).
const std::vector<std::pair<std::string, std::vector<std::string>>>& pdf_kind_params();

/// The kind's parameter names, or none for anything that is not a kind's own name.
const std::vector<std::string>* pd_meta(const Json* kind);

/// Whether every number the kind needs is filled in (for a list, whether it has values).
bool pdf_complete(const Json& spec);

// --- the forward and inverse CDF -----------------------------------------------------------------

/// The probability of being at or below `x`, before truncation (`cdf_at`): exact where the
/// shape is elementary, through the normal CDF for the three log-normals; 0 for a kind it does
/// not know. A distribution that is `null` raises the Julia package's `ArgumentError`.
double pdf_cdf(const Json& spec, const Json* x);
double pdf_cdf(const Json& spec, double x);

/// The value at probability `u`, before truncation (`quantile`); NaN for a kind it does not
/// know. As in the application, the normal kinds read `probit(u)`, which is 0 outside (0, 1).
double pdf_quantile(const Json& spec, const Json* u);
double pdf_quantile(const Json& spec, double u);

/// The two probabilities a truncated curve is read between (`probability_cuts`).
struct ProbabilityCuts {
    double lo = 0.0, hi = 1.0;
    bool cut = false;
    /// A cut the wrong way round -- Ecolego's `trmin=6.5,trmax=0.0` -- is no cut at all.
    bool reversed = false;
};
ProbabilityCuts probability_cuts(const Json& spec);

/// A log-normal's log-space mean and sd, whichever way it was written; none where there is none.
std::optional<std::pair<double, double>> pd_log_space(const Json& spec);

}  // namespace kompartment
