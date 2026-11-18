// The times a model says it changes at, where the solver is restarted
// (src/domain/switchtimes.js, and `constantValue` in src/domain/transport.js):
// the declared switch times (a number, or the name of a parameter or an
// expression that comes to one before the run starts), plus the times waste
// packages fail at and events happen at.

#pragma once

#include <optional>
#include <set>
#include <string>
#include <vector>

#include "engine/project.hpp"
#include "engine/tree.hpp"

namespace kompartment {

/// Every such time strictly inside the run, in order.
std::vector<double> switch_times(const Project& project);
std::optional<double> resolve_switch_time(const Project& project, const Json& entry);

/// A block's value for the run when it has one: a parameter's number, or an expression
/// made of numbers and such blocks.
std::optional<double> constant_value(const Project& project, const Json& block, const std::string& kind,
                                     const std::set<std::string>& seen = {});

/// A tree of numbers and the clock, worked out with the evaluator's arithmetic.
double evaluate_tree(const TNode& tree, double t, double t0, double t1);

}  // namespace kompartment
