// The variable-order NDF/BDF integrator: Kompartment's default solver
// (engine/solvers/ndf.py, itself a port of src/ode/solvers/ndf.js).
//
// The numerical differentiation formulas of orders one to five (Shampine and
// Reichelt, "The MATLAB ODE Suite", 1997), with the backward differentiation
// formulas as the case of every kappa zero, in backward-difference form with
// a quasi-constant step; `non_negative` states integrated as the projected
// system, a Jacobian that declines a point differenced there instead, and a
// run that accepts steps but covers none of the interval stopped, saying so.
//
// Every per-state operation is the Python engine's, in its order; every work
// vector is made once per solve, so a step allocates nothing.

#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "solvers/events.hpp"
#include "solvers/matrix.hpp"
#include "solvers/pattern.hpp"
#include "solvers/types.hpp"
#include "util/json.hpp"

namespace kompartment {

/// What the solver is told about df/dy (Python's `jacobian` dict): its
/// pattern, the colouring to difference it with (none: `colour_columns`),
/// an `evaluate(vals, t, y)` that writes its values (the pattern's, in the
/// pattern's order; without a pattern the dense matrix by columns) or returns
/// false to have them differenced, and whether it is constant.
struct JacobianSpec {
    std::optional<Pattern> pattern;
    std::optional<ColumnGroups> groups;
    JacobianEvaluate evaluate;
    bool constant = false;
    /// The values are exact and do not move with the state (they may with the clock): the model
    /// is linear. Said only by the caller that knows it -- the model's analytic Jacobian -- so a
    /// matrix marked constant is not taken for one.
    bool state_free = false;

    JacobianSpec() = default;
    JacobianSpec(std::optional<Pattern> pattern_, std::optional<ColumnGroups> groups_, JacobianEvaluate evaluate_,
                 bool constant_)
        : pattern(std::move(pattern_)),
          groups(std::move(groups_)),
          evaluate(std::move(evaluate_)),
          constant(constant_),
          state_free(false) {}
    JacobianSpec(std::optional<Pattern> pattern_, std::optional<ColumnGroups> groups_, JacobianEvaluate evaluate_,
                 bool constant_, bool state_free_)
        : pattern(std::move(pattern_)),
          groups(std::move(groups_)),
          evaluate(std::move(evaluate_)),
          constant(constant_),
          state_free(state_free_) {}
};

/// Where an event stopped a solve: the time, the state there, and the events
/// that crossed (counted from zero).
struct Stopped {
    double t = 0.0;
    Vec y;
    std::vector<int> which;
};

/// What a solve produced: a row per output time reached, where it ended, where
/// an event stopped it, and its counts (a dictionary with the Python engine's
/// stats keys).
struct Solution {
    Vec t;
    Rows y;
    double end_t = 0.0;
    Vec end_y;
    std::optional<Stopped> stopped;
    Json stats;
};

/// States weighed against another's size as well: `factor[i] * |y[from[i]]|`,
/// one entry per state, `from` another state (counted from zero) or -1 for none.
struct WeightFloor {
    Vec from;
    Vec factor;
};

/// The NDF's arguments (the Python engine's `ndf` keywords).
struct NdfOptions {
    double rtol = 1e-3;
    /// The absolute tolerance of every state, unless `abstol_vector` gives each its own.
    double abstol = 1e-6;
    /// One per state (the caller's, good for the call); with `auto_abstol` it is
    /// raised in place, as the caller's array is in Python.
    Vec* abstol_vector = nullptr;
    /// The states held at zero or above, counted from zero.
    std::vector<I32> non_negative;
    double max_order = 5;
    bool bdf = false;
    double hmax = 0.0;
    double h0 = 0.0;
    double max_steps = 1e6;
    std::string error_norm = "max";
    bool norm_control = false;
    const JacobianSpec* jacobian = nullptr;
    std::string matrix = "auto";
    std::optional<double> below_tol_run;
    double stagnation_tol = 0.0;
    int min_newton = 1;
    long stall_window = 2000;
    const EventFunctions* events = nullptr;
    std::optional<double> t_start;
    const Hints* hints = nullptr;
    StepCallback on_accepted;
    StepCallback on_output;
    /// Asked every 16 steps; false aborts the run.
    StepProgress on_step;
    bool auto_abstol = false;
    bool ends_only = false;
    /// The diagonal of the mass matrix (a zero marks an algebraic equation), or null.
    const Vec* mass = nullptr;
    RowPool* rows = nullptr;
    /// Where a step about to be tried is to end instead (NaN for where it would).
    StepLanding landing;
    const WeightFloor* weight_floor = nullptr;
    /// Makes the matrix Newton iterates with, in place of `IterationMatrix`.
    IterationMatrixFactory iteration_matrix;
};

/// Integrates y' = f(t, y) over `tspan`, answering at every time in it (the
/// Python engine's `ndf`).
Solution ndf(const RhsFunction& f, const Vec& tspan, const Vec& y0, const NdfOptions& options = NdfOptions());

/// A run's settings as a model file's solver options give them (the Python
/// engine's `opts`): what is absent, or zero where Python reads `opts.get(key) or
/// default`, takes the solver's default.
struct SolverOptions {
    std::optional<double> rtol;
    double abstol = 1e-6;
    Vec* abstol_vector = nullptr;
    /// A flag per state: held at zero or above. Empty: none.
    std::vector<std::uint8_t> non_negative;
    std::optional<double> max_order;
    bool bdf = false;
    std::optional<double> hmax;
    std::optional<double> hmin;
    std::optional<double> h0;
    std::optional<double> max_steps;
    /// "" for the default ("max").
    std::string error_norm;
    bool norm_control = false;
    /// "" for the default ("auto").
    std::string matrix;
    std::optional<double> below_tol_run;
    std::optional<double> stagnation_tol;
    std::optional<long> stall_window;
    const JacobianSpec* jacobian = nullptr;
    const EventFunctions* events = nullptr;
    StepCallback on_accepted;
    StepCallback on_output;
    /// `(fraction, n, t)`; false aborts the run.
    RunProgress on_step;
    bool auto_abstol = false;
    bool ends_only = false;
    RowPool* rows = nullptr;
    StepLanding landing;
    const WeightFloor* weight_floor = nullptr;
    IterationMatrixFactory iteration_matrix;
};

namespace sv {

/// Python's `2.0 ** max(floor(log2(|x|)) - 52, -1074)`, with the C library's
/// log2 and pow as Python's are.
double ndf_ulp(double x);

/// Python's `opts.get(key) or fallback` for a number: the fallback where it is absent or zero.
inline double opt_or(const std::optional<double>& v, double fallback) { return (v && *v != 0) ? *v : fallback; }

}  // namespace sv

}  // namespace kompartment
