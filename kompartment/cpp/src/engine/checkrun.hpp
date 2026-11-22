// Is the run resolved? The run set against itself solved more carefully: the Julia
// package's engine/checkrun.jl (the Python package's `kompartment/engine/checkrun.py`, the
// application's `src/sim/checkrun.js`, with the names `stateLabels` in `src/sim/jaccheck.js`
// gives the states). Done where the run is held, so that a page checking a run this engine
// holds need not fetch it.
//
// The careful run is the same model with both tolerances a hundred times tighter -- a
// compartment's own absolute tolerance too -- the relative one never below
// `CHECK_RTOL_FLOOR`, the step budget ten times larger where the model sets one, at the
// run's own output times. Each state's largest difference over the run is measured as a
// share of the most it reaches in either run, or of the run's absolute tolerance over its
// relative where that is more: a run holds below 0.1 %, nearly holds below 1 %, and
// otherwise does not. Nothing here rounds -- absolute values, maxima, one division -- so on
// the same two runs it gives the Julia package's report to the bit.

#pragma once

#include <functional>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "engine/project.hpp"
#include "engine/runner.hpp"
#include "engine/system.hpp"
#include "util/json.hpp"

namespace kompartment {

/// How much tighter the careful run's tolerances are.
constexpr double CHECK_CAREFUL = 100;
/// The careful run's relative tolerance goes no lower than this.
constexpr double CHECK_RTOL_FLOOR = 1e-12;
/// A run holds below the first, nearly holds below the second.
constexpr double CHECK_HOLDS = 1e-3;
constexpr double CHECK_NEARLY = 1e-2;

/// What `tighten_tolerances` set the careful run's tolerances to, and whether the relative
/// one could not be tightened all the way.
struct Tightened {
    double rtol = 0.0;
    double abstol = 0.0;
    bool floor = false;
};

/// Tightens a model's tolerances in place, as the careful run has them
/// (`tighten_tolerances!`): both a hundred times tighter, the relative one no lower than
/// `CHECK_RTOL_FLOOR`; a step budget the model sets ten times as large; a compartment's own
/// absolute tolerance, and an index's, a hundred times tighter.
Tightened tighten_tolerances(Json& model);

/// The careful run's model (`careful_model`): the run's own, copied, with the tolerances
/// tightened and the output times the run's.
std::pair<Json, Tightened> careful_model(const Json& model, const std::vector<double>& times);

/// What each state is called (`state_labels`): a block's name with its index, a far-field
/// path's with the cell, `state i` for one nothing names.
std::vector<std::string> state_labels(const System& sys);

/// The run set against the careful one, state by state (`compare_runs`): each run its times
/// and a row of states per time, over the run's project and system. Returns `{"verdict",
/// "worst", "moved", "states", "times", "sameTimes"}`, `moved` the states that moved most,
/// each `{"label", "state", "share", "at", "held", "careful"}` (`state` from 0).
Json compare_runs(const Project& project, const System& sys, const std::vector<double>& held_t, const std::vector<Vec>& held_y,
                  const std::vector<double>& careful_t, const std::vector<Vec>& careful_y);

/// Checks a run (`check_run`): solves the careful run -- `solve`, a run with whatever stop and
/// progress the caller has -- and sets the run against it. `model` is the model the run was
/// made of, as a project file (the project's own when null). Returns what `compare_runs`
/// gives, with `run` `{"rtol", "abstol", "steps"}` and `careful` `{"rtol", "abstol", "floor",
/// "ms", "steps", "maxSteps"}`.
Json check_run(const Results& held, const std::function<Results(std::shared_ptr<const Project>)>& solve, const Json* model = nullptr);

}  // namespace kompartment
