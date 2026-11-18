// The C++ engine behind the application's local server.
//
// `serve.py` in the application's folder serves the page and can hand its runs
// to an engine on the same machine instead of solving them in the browser; this
// is the C++ one. The server starts it once and keeps it:
//
//     kompartment-cpp --serve
//
// The protocol is the Python engine's (kompartment/python/kompartment/service.py),
// word for word: a line of JSON per message, jobs and cancels in on standard
// input, `ready`, `stage`, `progress`, `done`, `error` and `cancelled` out on
// standard output, which carries nothing else. A `run` job writes the model and
// its run as *Save with results* writes them. A run asked to be kept (`"keep":
// true`) is held here, its archive without the states, and `series`, `archive`
// and `forget` ask about it, answered on a thread of their own beside the jobs.
// Each job is a thread of its own, as many at once as the machine has cores
// (`concurrent` in `ready`). What this engine does not do -- a probabilistic
// run, a calibration, a sensitivity -- it refuses before anything runs
// (`NotOnThisEngine`), and the page does it itself.

#pragma once

#include <iosfwd>
#include <stdexcept>

namespace kompartment {

/// What this engine does not do, said before anything runs: the page does it itself, in
/// the browser, when it hears this.
struct NotOnThisEngine : std::runtime_error {
    using std::runtime_error::runtime_error;
};

inline constexpr const char* ENGINE_VERSION = "0.1.0";

/// Reads jobs until `input` closes.
void serve_stdio(std::istream& input, std::ostream& output);

}  // namespace kompartment
