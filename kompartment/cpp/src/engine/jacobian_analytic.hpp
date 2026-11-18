// The exact Jacobian's values: what the tests ask of it beside the solvers' interface
// (engine/jacobian.hpp declares that).

#pragma once

#include "engine/jacobian.hpp"

namespace kompartment {

/// `analytic_evaluate` with every tangent worked out by the walk over the statement's tree
/// instead of the tree laid out flat: the same values to the bit, slower -- a check on the
/// flat form.
bool analytic_evaluate_walked(Vec& J, Analytic& an, double t, const Vec& y);

/// The system a plan reads. A plan holds its system by address: a system that is copied or
/// moved after its Jacobian was made has to be given a plan of its own (`clone_analytic`).
const System* analytic_system(const Analytic& an);

/// How many slots have a gradient of their own, and how many entries those gradients have.
std::size_t analytic_gradient_rows(const Analytic& an);
std::size_t analytic_gradient_entries(const Analytic& an);
/// The gradients the last evaluation worked out: slot by slot in the slots' order, each
/// slot's along the states it depends on, in their order (Julia's `an.G`).
const Vec& analytic_gradients(const Analytic& an);

}  // namespace kompartment
