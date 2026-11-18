// The standard normal distribution, as Kompartment computes it: the Julia package's
// stats/normal.jl (the Python package's `kompartment/stats/_normal.py`, itself the
// application's `phi`, `probit` and `normalQuantile` in `src/domain/pdf.js`).
//
// `erfc` is the expression language's own (`kf_erfc`, lang/functions.hpp), and every
// exp and log here is the C library's, as Python's `math` calls it, so each value is
// the other engines' to the last bit.

#pragma once

#include <optional>

#include "util/json.hpp"

namespace kompartment {

/// The standard normal CDF: `0.5 erfc(-z/sqrt 2)`.
double normal_phi(double z);

/// Acklam's approximation to the standard normal quantile; none outside (0, 1).
std::optional<double> normal_probit(double p);
/// The same of a value as a model file holds it, read first as Python's `float()` reads it
/// (`jl_py_float`): none for anything that is not a number in (0, 1).
std::optional<double> normal_probit(const Json& p);

/// The standard normal's inverse CDF: `normal_probit` and two Newton steps; -Inf at or below
/// 0 (and for NaN), Inf at or above 1.
double normal_quantile(double p);

}  // namespace kompartment
