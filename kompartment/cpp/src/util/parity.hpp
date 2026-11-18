// Speed first, or the Python package's arithmetic to the bit.
//
// By default the engine takes the quickest way to an answer within a run's
// tolerance: fused multiply-adds and vector instructions in its linear
// algebra, the derivative's terms merged into one matrix, one Newton
// iteration where a model is linear, the quickest of its solvers where a
// model asks for a slower one. With parity on it does exactly what the
// Python and Julia packages do with theirs on -- every term summed in the
// application's order, each product rounded on its own, the model's own
// solver -- so a run gives their numbers to the last bit. That is how the
// engine is checked against them.
//
// A system takes the setting when it is built and a run when it starts:
// build again after changing it.

#pragma once

#include <string>

namespace kompartment {

/// Whether the engine reproduces the Python package's arithmetic to the bit.
/// Set with `set_parity` or `KOMPARTMENT_PARITY=1`.
bool parity() noexcept;
void set_parity(bool on) noexcept;

/// "fastest" (the default): a model that asks for the Rosenbrock 2-3 is run with the NDF,
/// falling back on the model's own solver if the NDF cannot finish. "model": always the
/// model's own solver (parity implies it). `KOMPARTMENT_SOLVERS=model`.
enum class SolverPolicy { Fastest, Model };
SolverPolicy solver_policy() noexcept;
void set_solver_policy(SolverPolicy policy) noexcept;

/// The solver a run takes for the one its model asks for, under the policy.
std::string quicker_solver(const std::string& asked);

}  // namespace kompartment
