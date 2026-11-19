// Fitting a model to numbers somebody already knows: the optimisers. The Julia
// package's stats/optimise.jl (the Python package's `kompartment/stats/optimise.py`,
// the application's `src/domain/optimise.js`); engine/calibrate is the other half,
// what one evaluation of the model is.
//
// What is minimised is the sum of weighted squared residuals (`objective_of`), each
// measured on its target's own scale -- `absolute` (got - want), `relative` (divided by
// the target; the default) or `log` (the log of the ratio). The algorithms, all
// derivative-free in the model, bound-constrained, deterministic given a seed, and
// reporting after every evaluation: Nelder-Mead (a simplex of n + 1 points; local, few
// evaluations), Levenberg-Marquardt (least squares on a finite-difference Jacobian of the
// residuals; fastest near a solution), differential evolution (`rand/1/bin`; slow, and the
// only global one).
//
// **The same steps as the Julia package.** Every step is its arithmetic in its order, the
// random stream is mulberry32, a point is recognised as seen before by the same
// `toPrecision(12)` text, and the logarithmic space and scale use V8's `Math.log` and
// `Math.exp` (`js_log`, `js_exp`): run on the same function, the three methods here visit
// the same points in the same order and stop at the same evaluation as the Julia
// package's -- and the application's. Faithful to a fault, too: Nelder-Mead keeps the
// unclamped points in its simplex (only the evaluation is clamped), so its centroid can
// lie outside the box.
//
// What the Julia functions take as any value -- a start, the bounds, a budget, a seed, a
// population -- is taken here as the JSON value a caller holds and read as Julia reads it:
// a list item by item (`Number()` of each, NaN past the end), a number once, a text a
// character at a time and a dictionary a pair at a time (neither of them a number).
//
// References: Nelder & Mead 1965; Marquardt 1963; Storn & Price 1997.

#pragma once

#include <functional>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

/// An optimisation that cannot start ("Nothing to vary."), or -- inside the optimisers,
/// where it is caught -- one being stopped ("stopped", "budget"). An objective that raises
/// one ends the search the same way, its message the reason.
struct OptimiseError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// What Julia's iteration finds in a value a caller passes: a list's items; a number or a
/// Boolean once; a text's characters and a dictionary's pairs, neither of them a number nor
/// `nothing` (each stands here as an empty dictionary, which reads alike: `Number()` of it
/// NaN, truthy, no number). Null is no collection: refused as Julia's `MethodError` of `what`
/// (`length`, `iterate`).
std::vector<Json> optimise_items(const Json& v, const char* what = "iterate");

// --- how a residual is measured, and how a variable moves ------------------------------------------

/// How a residual is measured (`OPTIMISE_SCALES`).
enum class OptimiseScale { Absolute, Relative, Log };
/// The scale a target's `scale` names, as `_op_lookup` finds it (`String()` of the value
/// looked up); none where it names none. A key not there is `undefined`.
std::optional<OptimiseScale> optimise_scale(const Json* key);
/// `got - want`; `(got - want) / |want|` (`got` where `want` is 0); `ln got - ln want`
/// (NaN unless both are above zero).
double optimise_residual(OptimiseScale scale, double got, double want);

/// How a variable moves between its bounds (`OPTIMISE_SPACES`): as it is, or in its logarithm.
enum class OptimiseSpace { Linear, Log };
std::optional<OptimiseSpace> optimise_space(const Json* key);
/// Into the space searched (`to`), back out of it (`from`), and whether the bounds can be
/// searched in it (`ok`).
double space_to(OptimiseSpace space, double v);
double space_from(OptimiseSpace space, double u);
bool space_ok(OptimiseSpace space, double lo, double hi);

/// The objective from one set of endpoint readings (`objective_of`): the sum of squares,
/// and the residuals.
struct Objective {
    double objective = 0.0;
    std::vector<double> residuals;
};
/// Each target is `{"value", "scale", "weight"}`: `scale` a key of the scales (relative when
/// it names none), `weight` a positive number (1 otherwise) that multiplies the square. A
/// residual that is not a number counts as a miss of 1e6. A reading past the end is NaN.
Objective objective_of(const std::vector<double>& readings, const std::vector<Json>& targets);
/// `readings[i]` as arithmetic reads a value: a number as it is, anything else `Number()` of
/// it (null 0, text read as JavaScript reads it).
std::vector<double> optimise_readings(const Json& readings);

// --- the methods ------------------------------------------------------------------------------------

/// What every method reports after every evaluation it makes (a point it has seen is not
/// evaluated again, and not reported): how many so far, this one's value (Infinity for what
/// is not a finite number), the best so far, the point, and the best point (none until one
/// is better than Infinity).
struct OptimiseStep {
    long long evals = 0;
    double fx = 0.0;
    double best = 0.0;
    const std::vector<double>* x = nullptr;
    const std::vector<double>* best_x = nullptr;
};

/// What a method gives: the best point seen (none if none was better than Infinity), its
/// value, how many evaluations, and why it stopped -- "converged", "budget" or "stopped".
struct OptimiseResult {
    std::optional<std::vector<double>> x;
    double fx = 0.0;
    long long evals = 0;
    std::string reason;
};

using OptimiseFunction = std::function<double(const std::vector<double>&)>;
using ResidualFunction = std::function<std::vector<double>(const std::vector<double>&)>;

/// What a method is told besides its function and its start; null where the Julia
/// package's caller passes nothing.
struct OptimiseOptions {
    /// The bounds, one per variable: refused where either is null.
    Json lower, upper;
    /// The most evaluations, read as `Number()` reads it (NaN: no limit); null the method's own
    /// (400 for Nelder-Mead and Levenberg-Marquardt, 2000 for differential evolution).
    Json max_evals;
    /// When to stop: the method's own where none (1e-8, 1e-10).
    std::optional<double> tol;
    /// Differential evolution's first member, where it is truthy; its population (more than 3,
    /// or ten per variable between 8 and 60), its seed, `F` and `CR` (0.7 and 0.9 where none).
    Json start;
    Json pop_size = Json(0);
    Json seed = Json(1);
    std::optional<double> F, CR;
    /// Hears every evaluation; `signal` answering true stops the search before the next one.
    std::function<void(const OptimiseStep&)> on_step;
    std::function<bool()> signal;
};

/// Nelder-Mead, the bounds applied by clamping (`nelder_mead`): reflect 1, expand 2, contract
/// 0.5, shrink 0.5, an initial simplex stepping each coordinate by 5% of its range, converged
/// when the simplex's values agree to `tol`, relatively.
OptimiseResult nelder_mead(const OptimiseFunction& f, const Json& start, const OptimiseOptions& options);

/// Levenberg-Marquardt on a forward-difference Jacobian of `residuals` (`levenberg_marquardt`):
/// the damped normal equations `(JᵀJ + λ·diag(JᵀJ)) dx = Jᵀr` solved by Gauss elimination, λ
/// down by ten when a step helps and up by ten when it does not.
OptimiseResult levenberg_marquardt(const ResidualFunction& residuals, const Json& start, const OptimiseOptions& options);

/// Differential evolution, `rand/1/bin` (`differential_evolution`): the population over the
/// whole box, the start (where there is one) its first member, mulberry32 seeded with `seed`;
/// converged when the whole population agrees to 1e-10, relatively.
OptimiseResult differential_evolution(const OptimiseFunction& f, const OptimiseOptions& options);

/// Gauss elimination with partial pivoting (`_op_solve`); none where a pivot is not above
/// 1e-300 (or is no number). `A` is n x n, by rows.
std::optional<std::vector<double>> optimise_solve(const std::vector<std::vector<double>>& A, const std::vector<double>& b);

/// The three methods, by the key a file stores (`OPTIMISE_METHODS`): none for a key it does
/// not know.
enum class OptimiseMethod { Nelder, Lm, De };
std::optional<OptimiseMethod> optimise_method(const Json* key);

/// What a method runs on: the start, and the objective and the residuals of a point.
struct OptimiseContext {
    std::vector<double> start;
    OptimiseFunction objective;
    ResidualFunction residuals;
};
/// One method run as the table runs it: Nelder-Mead and Levenberg-Marquardt from the start
/// with the bounds, the budget, `on_step` and `signal`; differential evolution with those, the
/// start as its first member and the seed. What a method does not read it ignores.
OptimiseResult run_optimise_method(OptimiseMethod method, const OptimiseContext& ctx, const OptimiseOptions& options);

}  // namespace kompartment
