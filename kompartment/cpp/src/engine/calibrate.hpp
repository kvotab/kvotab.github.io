// Running an optimisation against the model: calibration. The Julia package's
// engine/calibrate.jl (the Python package's `kompartment/engine/calibrate.py`, the
// application's `src/sim/calibrate.js`). stats/optimise knows how to walk downhill and
// nothing about compartments; this is the other half -- what one evaluation *is*: set
// the parameters, work the invariants out again, solve, and read the endpoints at the
// times the targets name.
//
// **The system is built once.** Everything a candidate changes is read live -- `P` is
// the array the compiled statements read and the initial state a call rather than a
// value -- which is the same reason a probabilistic run can integrate a thousand times
// off one build.
//
// **A variable may be searched in its logarithm** (`space: "log"`): a rate constant
// known to within orders of magnitude is not usefully stepped by a fixed amount. Only
// `P` ever sees the value itself.
//
// **An evaluation that will not solve is not an error.** A corner of the box the solver
// cannot carry comes back as NaN readings -- a miss of 1e6 per target -- which every
// method reads as "not that way". A run is not stopped part way: the search stops
// between evaluations. What this engine cannot run at all -- a solver it does not have
// (`NotSupported`) -- is no fact about the model, and stops the calibration so that it is
// done where it can be.

#pragma once

#include <functional>
#include <memory>
#include <optional>
#include <vector>

#include "engine/project.hpp"
#include "engine/runner.hpp"
#include "util/json.hpp"

namespace kompartment {

/// One endpoint's value out of a finished run (`reading_of`): `target` is `{"output",
/// "when", "time"}`, the series labelled `output` read at its highest (`"peak"`), at the end
/// (`"end"`), or at the output time nearest `time` -- the nearest rather than an
/// interpolation, since a target is compared against what the model says. NaN when the run
/// has no such series.
double reading_of(Results& res, const Json& target);

/// The variables of a model, as an optimisation can offer them (`variables_of`): every
/// parameter slot, `{"key", "name", "index", "slot", "value", "unit"}`.
std::vector<Json> variables_of(std::shared_ptr<const Project> project);

/// What a calibration says after every evaluation of its search: how many so far, this
/// one's misfit, the best so far, and the values of the best point in the values a reader
/// knows (none until a point is better than Infinity).
struct CalibrateStep {
    long long evals = 0;
    double fx = 0.0;
    double best = 0.0;
    std::optional<std::vector<double>> values;
};

/// A calibration's settings, as a job's options give them; null where they say nothing.
struct CalibrateOptions {
    /// `{"output", "when", "time", "value", "scale", "weight"}` (see `reading_of` and
    /// `objective_of`); a target that is not truthy, or names no output, is passed over.
    Json targets;
    /// `{"key", "lower", "upper", "space", "start"}`: `key` a slot label (`slot_label`),
    /// `space` `"linear"` or `"log"`, `start` the model's own value when not a number.
    Json variables;
    /// A key of the methods (`"nelder"` when it names none).
    Json method;
    /// The budget (300, at least 10).
    Json max_evals;
    /// Differential evolution's seed (1).
    Json seed;
    std::function<void(const CalibrateStep&)> on_progress;
    /// Answering true stops the search before the next evaluation.
    std::function<bool()> signal;
};

/// Solves for the parameter values that put the endpoints where they are asked to be
/// (`calibrate`). Returns `{"ok", "matched", "method", "reason", "evals", "ms",
/// "objective", "values", "targets"}`: `values[i]` = `{"key", "was", "value", "lower",
/// "upper", "pinned"}` and `targets[i]` = `{"output", "want", "got", "scale"}`. `matched`
/// says whether every target is met to 1%, which `ok` -- numbers came back -- does not.
/// Refuses as the Julia package refuses (`OptimiseError`).
Json calibrate(std::shared_ptr<const Project> project, const CalibrateOptions& options);

}  // namespace kompartment
