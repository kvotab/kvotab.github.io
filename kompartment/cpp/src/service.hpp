// The C++ engine behind the application's local server.
//
// `serve.py` in the application's folder serves the page and can hand its runs
// to an engine on the same machine instead of solving them in the browser; this
// is the C++ one. The server starts it once and keeps it:
//
//     kompartment-cpp --serve
//
// The protocol is the Python and Julia engines' (kompartment/julia/src/service.jl),
// word for word: a line of JSON per message, jobs and cancels in on standard
// input, `ready`, `stage`, `progress`, `done`, `error` and `cancelled` out on
// standard output, which carries nothing else. A `run` job writes the model and
// its run as *Save with results* writes them; a `probabilistic` one the model and
// the sample (`sample_archive`), or a tornado's or a sensitivity design's runs,
// saying how many realisations are done as it goes; a `replay` one realisation of
// a probabilistic run, as a run; a `local-sensitivity` one integrates dy/dp for the
// parameters its options name (`run_sensitivity`) and writes the times, the
// parameters, the run's counts and every state the page shows with its
// derivatives, as JSON. A run asked to be kept (`"keep": true`) is held
// here, its archive without the states, and `series`, `archive` and `forget` ask
// about it; a sample asked to be kept is held the same way, its archive without
// the kept series, and `bands`, `realisations`, `column`, `realisation`,
// `archive` and `forget` ask about it -- answered on a thread of their own beside
// the jobs. Each job is a thread of its own, as many at once as the machine has
// cores (`concurrent` in `ready`). Errors are named as the Julia engine names
// them. What this engine does not do -- a calibration, a solver it does not have,
// a model it cannot build yet -- it refuses before anything runs
// (`NotOnThisEngine`), and the page does it itself.

#pragma once

#include <iosfwd>
#include <stdexcept>
#include <string>

#include "util/json.hpp"

namespace kompartment {

struct ProbabilisticResults;

/// What this engine does not do, said before anything runs: the page does it itself, in
/// the browser, when it hears this.
struct NotOnThisEngine : std::runtime_error {
    using std::runtime_error::runtime_error;
};

inline constexpr const char* ENGINE_VERSION = "0.1.0";

/// Reads jobs until `input` closes.
void serve_stdio(std::istream& input, std::ostream& output);

/// The answer to a question `op` (`bands`, `realisations`, `column`, `realisation`) about a
/// sample, as little-endian doubles, laid out as the Julia engine's service lays them out
/// (`_service_sample_answer`): per series, a run per percentile then the mean, the standard
/// deviation, its count and the median's two intervals; or each series asked for (by its
/// number from 0, the kept ones then the varied parameters) -- every realisation of it, one
/// time across the realisations, or one realisation across the times. Refusals as the Julia
/// engine's (`ArgumentError`).
std::string sample_answer_bytes(const Json& op, const ProbabilisticResults& prob, const Json& q);

}  // namespace kompartment
