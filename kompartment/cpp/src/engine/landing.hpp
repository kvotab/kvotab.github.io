// Where a step has to end so as not to pass over a pulse in a table
// (`src/sim/landing.js` in the application, number for number).
//
// A solver looks at the derivative at the ends of its steps and at its stages
// inside them, and nowhere else. A table read at the clock that rises and falls
// back between two of those places is never seen, and what it would have put
// into the model is lost: a pulse after a time of none arrives as nothing, a
// spike on a steady release as the steady release alone.
//
// So each turn of each such table -- a point higher than both its neighbours, or
// lower -- is a place a step may not cover whole when the turn matters: when the
// area it adds to the straight line between its neighbours is more than rtol of
// what the table holds over that step. Such a step ends at the turn instead. A
// turn is judged over the stretch a step would have to cover to miss it, by the
// interpolation rule, and the step ends inside that stretch, never on a jump.
// Tables read at an expression, and cyclic ones, are left out.

#pragma once

#include <memory>
#include <optional>
#include <vector>

#include "engine/lookup.hpp"

namespace kompartment {

/// `landing(t, t_next)`: where a step from t to t_next is to end instead, or NaN.
class TableLanding {
public:
    double operator()(double t, double t_next) const;

    struct Tab {
        std::vector<double> x, ay, cum;
        std::vector<double> A;      // where the stretch of each turn starts
        std::vector<double> B;      // ... and ends
        std::vector<double> AT;     // the time inside it a step ends on
        std::vector<double> CRIT;   // the area the turn adds, over rtol
        std::vector<double> block_max;
    };
    std::vector<Tab> tabs;
};

/// The rule for `tables`, or none when none of them turns.
std::optional<TableLanding> table_landing(const std::vector<std::shared_ptr<LookupTable>>& tables, double rtol);

}  // namespace kompartment
