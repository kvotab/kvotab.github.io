// How the answer moves when one parameter moves: forward sensitivities (the Julia
// package's engine/localsens.jl; the Python package's `kompartment/engine/localsens.py`,
// the application's `src/sim/localsens.js`). At the values the model holds, what is
// dy/dp?
//
// **The forward sensitivity equations.** Differentiate `y' = f(t, y, p)` with respect
// to a parameter and `S = dy/dp` satisfies
//
//     S' = J·S + df/dp,      S(0) = dy0/dp
//
// -- a linear system driven by df/dp, integrated alongside the states: the augmented
// vector is `[y, S_1, ..., S_m]` and one solve gives the states and every sensitivity
// at once.
//
// **J·S** is the model's analytic Jacobian applied to each sensitivity block, its
// values formed once per derivative call. **df/dp is differentiated where the model
// allows it** (engine/paramtangent) and differenced otherwise -- one forward step of
// `sqrt(eps)·max(|p|, 1)`, with the invariant pass run on either side so the
// perturbation reaches the algebra worked out from the parameter. `differenced`
// forces the difference. A solve that gives up with a difference in it says so: what
// a difference loses to rounding can be more than the absolute tolerance dy/dp is
// held to.
//
// **The iteration matrix** is the original Jacobian repeated down the diagonal, and
// under it how each sensitivity's equations move with the state (`C_j = d(S_j')/dy`,
// J's own derivative along `(S_j, e_j)`), solved a block at a time: the states' block
// factorised once -- twice while the zero floor holds a state -- and each
// sensitivity's solved after it, never a pivot taken across blocks. The solve is the
// NDF whatever solver the model names: a Rosenbrock method uses the whole Jacobian
// inside its formula.
//
// **It is a run of the model**: the augmented system is integrated by the runner's own
// machinery (`Equations` in engine/runner), restarted at every switch time, through the
// discrete events, with the blocks that remember primed and fed, each compartment's
// own floor and the clock's interpolation. What the forward equations cannot carry is
// refused, by name (`uncarried`): a jump in the state, a block that remembers the path
// of the run where the derivative reads it, a semi-analytical far-field path, and a
// parameter that places a corner of the run.
//
// **Tolerances.** The states take the run's own absolute tolerances; the block of dy/dp
// takes them divided by |p| (CVODES's rule; a parameter at zero takes the state's
// unchanged), and each sensitivity is weighed against its state over |p| as well.

#pragma once

#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "engine/paramtangent.hpp"
#include "engine/project.hpp"
#include "engine/runner.hpp"
#include "engine/system.hpp"
#include "solvers/solvers.hpp"
#include "util/json.hpp"

namespace kompartment {

/// A sensitivity run that cannot be set up: no analytic Jacobian, no parameter named, too
/// many, or something in the model the sensitivity equations cannot carry.
struct SensitivityError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// `sqrt(eps)·max(|p|, 1)`: the forward step for `p`.
double step_for(double p);

/// Every parameter slot a built model has (`parameterSlots`): `{"slot" (from 0), "name",
/// "index", "value", "unit"}`, one per index tuple. `value` is the value the model file gives
/// the slot, read the way the editor reads it; `unit` is the slot's as the chart labels its
/// series.
std::vector<Json> parameter_slots(const System& sys);

/// `name` or `name[i][j]`: how a parameter slot is asked for (`slotLabel`).
std::string slot_label(const Json& slot);

/// A name for every state the solve carries, as the chart names the same series
/// (`stateSeries`): `{"offset", "label", "block", "kind", "unit", "hidden"}`, in the order of
/// the state vector. Machinery -- a far-field path's cells, a running mean's integral, the
/// mass balance -- is `hidden`.
std::vector<Json> state_series(const System& sys);

/// What stands between the forward equations and the right answer, in words, or nothing
/// (`uncarried`): a jump in the state inside the run; an event a trigger sets off; a
/// semi-analytical far-field path; a min/max, snapshot or delay -- or a running mean a
/// discrete event switches -- that the derivative reads; or a chosen parameter (an entry of
/// `parameter_slots`) that places a corner of the run. A corner is found by moving the chosen
/// parameter's values in the model's own dictionaries and putting them back, as the Julia
/// package does: no other thread is to read the project meanwhile.
std::optional<std::string> uncarried(const Project& project, System& sys, const std::vector<Json>& wanted);

struct SensitivityOptions {
    /// The most parameters taken at once: 12 where null.
    Json most;
    /// Differences df/dp even where it could be generated.
    bool differenced = false;
    /// `on_progress(fraction, t)` hears the run's progress; returning false stops the run.
    ProgressFunction on_progress;
};

/// The augmented system `run_sensitivity` integrates, set up and not solved
/// (`sensitivity_problem`). It holds pointers into itself: made once, never moved.
struct SensitivityProblem {
    std::shared_ptr<const Project> project;
    std::shared_ptr<System> system;
    int n = 0;                       // the model's states
    int m = 0;                       // the parameters
    std::vector<Json> wanted;        // the parameter slots chosen, as `parameter_slots` gives them
    std::vector<int> slots;
    Json chosen;                     // [{"label", "name", "index", "value"}]
    bool tangent = false;            // df/dp differentiated (true) or differenced
    ParamTangent why;                // what `param_tangent` said, or why it was not asked
    double rtol = 0.0;
    /// What `run_sensitivity` hands the runner: `dydt(out, t, Y)` the right-hand side of
    /// `Y = [y, S_1, ..., S_m]`, `Y0`, the absolute tolerances, the Jacobian below, the NDF, the
    /// clock's anchors, the weight floor and the block iteration matrix.
    Equations equations;
    /// The model's Jacobian repeated down the diagonal, the coupling under the states' block.
    JacobianSpec jacobian;
    /// Each sensitivity weighed against its state over |p| as well.
    WeightFloor weight_floor;
    /// What the closures share.
    std::shared_ptr<void> work;

    SensitivityProblem() = default;
    SensitivityProblem(const SensitivityProblem&) = delete;
    SensitivityProblem& operator=(const SensitivityProblem&) = delete;
};

/// Sets the problem up, refusing as it refuses: `parameters` a list of slot labels
/// (`"Kd[I-129]"`), anything else taken as naming none and a single label refused.
std::unique_ptr<SensitivityProblem> sensitivity_problem(std::shared_ptr<const Project> project, const Json& parameters,
                                                        const SensitivityOptions& options = {});

/// What `run_sensitivity` gives: the output times; `y[i]` the series of state `i`;
/// `sens[k][i]` that of `d y_i / d p_k`; the parameters chosen; a name for every state
/// (`state_series`); `{"ms", "nsteps", "states", "restarts", "compiled"}`; and whether
/// df/dp was differentiated (true) or differenced.
struct SensitivityRun {
    std::vector<double> t;
    std::vector<std::vector<double>> y;
    std::vector<std::vector<std::vector<double>>> sens;
    Json chosen;
    std::vector<Json> series;
    Json stats;
    bool tangent = false;
    std::shared_ptr<System> system;
};

/// Integrates the model and dy/dp for the parameters named (`runSensitivity`). A solve that
/// gives up where df/dp is differenced says so (`SolverError`), the solver's own words its
/// hint.
SensitivityRun run_sensitivity(std::shared_ptr<const Project> project, const Json& parameters, const SensitivityOptions& options = {});

/// A solve of the sensitivity equations that gave up, said for what it most likely is when
/// df/dp is worked out by a difference (`differencedFailure`), or nothing.
std::optional<SolverError> ls_differenced_failure(const SolverError& e, const SensitivityProblem& problem, bool asked);

/// What the solver said, without the advice the run adds for a model's own equations.
std::string ls_solver_words(const std::string& message);

/// `(p / y)·(dy/dp)`: a relative change for a relative change, comparable across parameters
/// as dy/dp is not. NaN where `y` is zero.
std::vector<double> elasticity(const std::vector<double>& y, const std::vector<double>& s, const Json& p);

}  // namespace kompartment
