// How well the values a calibration found are known: the Julia package's stats/precision.jl
// (the Python package's `kompartment/stats/precision.py`, the application's
// `src/domain/precision.js`).
//
// Least squares answers *how sure is it* from two things it already has at the answer: how
// much misfit is left, and how the endpoints move when each value moves. Near the answer the
// residuals are close to straight in the values, `r(u) ~ r0 + J (u - u*)`, and then
//
//     cov(u) = s^2 (J^T J)^-1,   s^2 = |r0|^2 / (m - n)
//
// for `m` residuals and `n` values found. Each value's standard error is the root of its
// diagonal entry, its range about 95 % that times Student's t on `m - n` degrees of freedom,
// and the off-diagonal entries, scaled to the diagonal, are the correlations. A value searched
// in its logarithm has its standard error in the logarithm, so its range is a factor either
// way. With no more targets than values the correlations still follow from `J` and the
// standard errors do not; a value on a bound is held and given no range; one no endpoint
// moves has "no effect"; two the endpoints cannot tell apart are named as that.
//
// Every exp, log, sin and tan here is the C library's, as Julia's `cexp`, `clog`, `clog1p`,
// `csin` and `ctan` call it, and a square root below nought is NaN, so each value is the
// Julia package's to the last bit.

#pragma once

#include <optional>
#include <string>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

/// The logarithm of the gamma function, by Lanczos's approximation (g = 7, n = 9).
double ln_gamma(double x);
/// The regularised incomplete beta function, `I_x(a, b)`.
double incomplete_beta(double x, double a, double b);
/// Student's t distribution with `dof` degrees of freedom: P(T <= t).
double student_cdf(double t, double dof);
/// Student's t quantile: the t below which a share `p` lies. Closed forms for one and two
/// degrees of freedom, the normal's beyond ten million, and between them the distribution
/// function inverted by bisection to the last bit. NaN outside (0, 1) or for no degrees of
/// freedom.
double student_quantile(double p, double dof);

/// What `precision_of` works from.
struct PrecisionInput {
    /// The search's own residuals at the answer.
    std::vector<double> residuals;
    /// dr/du for each value, in the space the search moved in; none for one held (on a bound)
    /// or one the model would not run around.
    std::vector<std::optional<std::vector<double>>> columns;
    std::vector<std::string> keys;
    /// Whether each value was searched in its logarithm.
    std::vector<bool> log;
    /// The values found, as the model holds them.
    std::vector<double> values;
    /// "lower", "upper" or none, per value.
    std::vector<std::optional<std::string>> pinned;
    /// Why a value has no column, where the model did not run around it.
    std::vector<std::optional<std::string>> failed;
    /// The share the ranges hold.
    double level = 0.95;
};

/// The precision of a least-squares answer, from its residuals and their derivatives there
/// (`precision_of`): `{"targets", "free", "dof", "spread", "t", "level", "reason", "values",
/// "correlations"}`, per value `{"key", "se", "low", "high", "factor", "held"}` -- `se` in the
/// value's own units (for a logarithmic one, the value times its standard error in the
/// logarithm), `factor` the range's either way for a logarithmic one, `held` why it has none
/// ("lower", "upper", "no effect", or the reason it could not be differenced). `reason` says
/// why there are no ranges: "nothing free", "cannot tell apart" or "no spare targets".
Json precision_of(const PrecisionInput& in);

}  // namespace kompartment
