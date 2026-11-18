// The solvers a run can be given, by the id the model file stores
// (engine/solverset.py: the NDF, the Rosenbrock 2-3 and the Dormand-Prince
// 4-5). Each takes `(f, tspan, y0, options)` with `f(dy, t, y)` the derivative
// and `options` the Python engine's settings, and returns a `Solution`: a row
// per requested time reached, and where an event stopped the run.

#pragma once

#include <functional>
#include <string>

#include "solvers/ndf.hpp"
#include "solvers/onestep.hpp"
#include "solvers/types.hpp"

namespace kompartment {

/// What a model's kind of trouble most often is ("singular", "noPattern").
const Hints& solver_hints();

/// What `variableOrder` says when the NDF fails with `e`, keeping where the
/// solver was when it gave up (`last_t`, `last_y`): the runner looks at the
/// equations there. An aborted run's failure, or an empty span's, is `e` itself.
SolverError variable_order_failure(const SolverError& e, double t0);

/// The NDF (BDF with `options.bdf`): `variableOrder` in the application, the
/// Python engine's `solverset.variable_order`. `on_step` is called
/// `(fraction, n, t)` every 64 derivative evaluations; false aborts.
Solution variable_order(const RhsFunction& f, const Vec& tspan, const Vec& y0,
                        const SolverOptions& options = SolverOptions());

/// A solver: `(f, tspan, y0, options) -> Solution`.
using SolverFunction = Solution (*)(const RhsFunction&, const Vec&, const Vec&, const SolverOptions&);

/// The solver of an id ("ndf", "ros23", "dp45"), or null.
SolverFunction solver_by_id(const std::string& id);

/// Runs the solver of an id; `std::invalid_argument` where there is none.
Solution solve(const std::string& id, const RhsFunction& f, const Vec& tspan, const Vec& y0,
               const SolverOptions& options = SolverOptions());

}  // namespace kompartment
