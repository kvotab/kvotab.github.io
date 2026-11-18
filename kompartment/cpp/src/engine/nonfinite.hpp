// Where a value that is not a number came from (the Julia package's
// engine/nonfinite.jl, a port of the application's src/sim/nonfinite.js).
//
// A run that stops on a NaN or an infinity would say when and nothing else. The
// state the solver held is known, so the equations are worked out once more
// there and a value that is not a number is followed back the way it came: from
// the compartments whose derivative it reached, through the transfers that
// carried it, and down through each equation a part at a time to the one
// operation that made it out of numbers -- zero divided by zero, the log of a
// negative, an overflow -- and the values that operation read. It is followed
// by value, not by name: a part of an equation is resolved by the builder's own
// resolvers at the element's tuple and worked out with the evaluator's own
// arithmetic. `start_warnings` says the same before a run.
//
// The words are the application's, letter for letter. Indices are the
// builder's, counted from 0.

#pragma once

#include <limits>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "engine/system.hpp"
#include "lang/ast.hpp"
#include "solvers/types.hpp"
#include "util/json.hpp"

namespace kompartment {

/// The last step a solver accepted, as the runner keeps it for a solver whose error does
/// not carry one (every solver but the NDF): NaN until there is one.
struct HeldStep {
    double t = std::numeric_limits<double>::quiet_NaN();
    std::vector<double> y;
};

/// Where the stretch a run was solving started, and from what: where a solver that fails
/// at its first instant failed.
using StretchStart = std::pair<double, std::vector<double>>;

/// Puts where a value that is not a number starts into a solver's error
/// (`explainNonFinite`): looked for at the state the solver last held -- its own, if its
/// error carries one, else `held` -- and at the instant it failed; else at the start of
/// the stretch it was solving, if that is where it failed; else, for a failure about a
/// value that is not a number, short steps past the state held. The message is said again
/// with the place in it (the solver's own kept as `solver_message`), and the block it
/// starts in becomes `block_name`. Nothing is changed when nothing is found; whether
/// something was. `end`: where the run was to end.
bool explain_non_finite(SolverError& e, System& sys, const std::optional<StretchStart>& start, const HeldStep* held, double end);

/// What a run would trip over, said before one is run (`startWarnings`): every block whose
/// value at the start is not a number of its own making, `{block, message, stops}` each,
/// in the order the equations are worked out.
std::vector<Json> start_warnings(System& sys, double t0, const std::vector<double>& y0);

/// A tree written back out as an equation (`equationText`), cut in the middle past 240
/// characters.
std::string equation_text(const ENode& node);

}  // namespace kompartment
