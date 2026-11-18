// df/dy for the implicit solvers: its structure, a colouring, and its values
// (src/sim/jacobian.js).
//
// The pattern is read off the statements the derivative is made of -- which
// states each contribution reads, directly or through the algebraic slots that
// read the state -- never probed, so a coefficient that happens to be zero at
// the start is not taken for a structural zero. The values are assembled
// analytically where the model allows: most of the Jacobian is direct (a
// transfer's rate, decay), and the rest comes through the slots that read the
// state by the chain rule, each slot's gradient a sparse row worked out in
// dependency order by forward-mode tangents of its statements.
//
// The budgets of the mass-balance audit follow the solver: at their diagonal
// for the solvers that take it so, whole for the others.

#pragma once

#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "engine/system.hpp"
#include "solvers/solvers.hpp"

namespace kompartment {

struct Analytic;

struct JacobianInfo {
    bool available = false;
    std::optional<std::string> reason;
    std::optional<Pattern> pattern;
    std::optional<ColumnGroups> groups;
    bool constant = false;
    std::shared_ptr<Analytic> analytic;
    long nnz = 0;
    int colours = 0;
    double density = 0;
    std::optional<std::string> budget_rows;
};

/// The Jacobian the solvers are handed: its pattern and colouring, and where the model
/// allows, its values.
std::shared_ptr<JacobianInfo> build_jacobian(System& sys);

/// The `JacobianSpec` a solver takes: the analytic values when there are any, unless the
/// settings ask for differences; none when the system has no pattern.
std::optional<JacobianSpec> jacobian_spec(System& sys, bool numeric = false);

/// The Jacobian of a cloned system: the plans shared, the work space and the system its own.
std::shared_ptr<JacobianInfo> clone_jacobian(const std::shared_ptr<JacobianInfo>& j, System& sys);

// --- the structure (engine/jacobian.cpp) -------------------------------------------------------------

/// Whether the audit's budget rows are taken whole (false: at their diagonal).
bool full_budget(const System& sys);
/// The colouring with the audit's budgets in one group of their own (when their rows are at the diagonal).
ColumnGroups budgets_apart(const ColumnGroups& groups, const Builder& b, bool full);
/// For every algebraic slot that reads the state: the states it depends on (sorted),
/// directly or through other such slots.
std::unordered_map<int, std::vector<int>> state_dependencies(const System& sys);
/// Which entries of df/dy can be non-zero.
Pattern jacobian_structure(const System& sys, bool full = false);

// --- the values (engine/jacobian_analytic.cpp) ---------------------------------------------------------

/// A model whose derivative has no rule to differentiate by; `what` names what has none.
struct NoDerivative : std::runtime_error {
    explicit NoDerivative(const std::string& what) : std::runtime_error(what) {}
};

/// The plan of a system's exact Jacobian on `pattern`; throws `NoDerivative` where the
/// model has something without a rule. Null: this engine has no exact Jacobian yet.
std::shared_ptr<Analytic> make_analytic(System& sys, const Pattern& pattern, bool full);
/// Writes the Jacobian's values (in the pattern's order) at `(t, y)`; false when one is not finite.
bool analytic_evaluate(Vec& J, Analytic& an, double t, const Vec& y);
/// Whether the Jacobian never changes, and whether it moves with the clock alone.
bool analytic_constant(const Analytic& an);
bool analytic_state_free(const Analytic& an);
/// A plan for a cloned system: the plan shared, the work space its own.
std::shared_ptr<Analytic> clone_analytic(const std::shared_ptr<Analytic>& an, System& sys);

}  // namespace kompartment
