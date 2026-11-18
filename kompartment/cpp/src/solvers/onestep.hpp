// The driver the one-step methods share (engine/solvers/onestep.py), and the
// two methods: the Rosenbrock (2,3) of Shampine and Reichelt (rosenbrock23.py)
// and the Dormand-Prince (4,5) (dormand_prince.py).
//
// Step-size control, the non-negativity constraint (held derivatives and the
// projection onto zero), the stall guard, events and output are the same for
// both; each method supplies only how a step is attempted and how the
// solution is read inside one.

#pragma once

#include "solvers/ndf.hpp"
#include "solvers/types.hpp"

namespace kompartment {

/// The Rosenbrock (2,3) solver (`rosenbrock23`): `options` as Python's.
Solution rosenbrock23(const RhsFunction& f, const Vec& tspan, const Vec& y0,
                      const SolverOptions& options = SolverOptions());

/// The Dormand-Prince (4,5) solver (`dormand_prince`): `options` as Python's.
Solution dormand_prince(const RhsFunction& f, const Vec& tspan, const Vec& y0,
                        const SolverOptions& options = SolverOptions());

}  // namespace kompartment
