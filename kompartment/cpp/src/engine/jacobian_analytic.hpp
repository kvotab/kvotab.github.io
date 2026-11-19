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

/// One element of a statement's tree and its forward-mode tangent along one leaf, by the walk
/// (`tangent_run!`): `values` the element's leaves in `tree_leaves` order (a table's leaf: the
/// table's index), `seed` the leaf the tangent is taken along, counted from 0 (-1: none, for
/// the value alone). `has` is false where the walk finds no tangent.
struct TreeTangent {
    double value = 0.0;
    bool has = false;
    double tangent = 0.0;
};
TreeTangent tree_tangent(const TNode& tree, const std::vector<std::shared_ptr<LookupTable>>& tables, const double* values, int seed);

/// Refuses (`NoDerivative`), before anything is worked out, a tree whose derivative along a live
/// leaf would need a rule nobody wrote (`_check_differentiable`): `live` by leaf position.
void check_tree_differentiable(const TNode& tree, const std::vector<char>& live);

}  // namespace kompartment
