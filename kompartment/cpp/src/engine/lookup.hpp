// Lookup tables: a value that changes with time (src/domain/lookup.js).
//
// A table is a list of (x, y) points and a rule for reading between and
// beyond them: `linear` (straight lines, held flat at the ends),
// `extrapolate` (the end segments continued), `below`, `above`, `nearest`.
// `cyclic` wraps x into the table's own span first. The point is found by
// bisection, so the answer does not depend on the order a solver asks in; two
// points at the same x are a step, and the later one wins.

#pragma once

#include <cmath>
#include <stdexcept>
#include <string>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

struct LookupError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

enum class Interpolation : unsigned char { Linear, Extrapolate, Below, Above, Nearest };

/// A table ready to be read (`makeTable`).
struct LookupTable {
    std::vector<double> x, y;
    int n = 0;
    double first = 0, last = 0, span = 0;
    Interpolation interpolation = Interpolation::Linear;
    bool cyclic = false;
    bool wraps = false;

    LookupTable() = default;
    /// From `[[x, y], ...]` or `[xs, ys]` as a model holds them.
    LookupTable(const Json& points, const std::string& interpolation, bool cyclic = false);
    /// From points given as numbers, in any order.
    LookupTable(std::vector<double> xs, std::vector<double> ys, const std::string& interpolation, bool cyclic = false);

    /// Rewrites one point's value (a distributed point, drawn again); `row` from 0.
    void set_y(int row, double value) { y[static_cast<std::size_t>(row)] = value; }

private:
    void finish(std::vector<double> xs, std::vector<double> ys, const std::string& interpolation, bool cyclic);
};

/// The segment a point falls in: bisect_right(x, v) - 1, clamped to [0, n-2].
inline int table_segment(const LookupTable& t, double v) {
    if (v != v) return 0;
    int lo = 0, hi = t.n;
    const double* x = t.x.data();
    while (lo < hi) {
        int mid = static_cast<int>((static_cast<unsigned>(lo) + static_cast<unsigned>(hi)) >> 1);
        if (v < x[mid]) hi = mid;
        else lo = mid + 1;
    }
    int i = lo - 1;
    if (i < 0) i = 0;
    if (i > t.n - 2) i = t.n - 2;
    return i;
}

inline double table_between(const LookupTable& t, double v, int i) {
    const double* x = t.x.data();
    const double* y = t.y.data();
    double dx = x[i + 1] - x[i];
    if (dx == 0) return y[i + 1];
    return y[i] + ((v - x[i]) / dx) * (y[i + 1] - y[i]);
}

inline double table_wrap(const LookupTable& t, double v) {
    double a = std::fmod(v - t.first, t.span);
    return a >= 0 ? a + t.first : a + t.span + t.first;
}

/// The table read at `raw`.
inline double table_at(const LookupTable& t, double raw) {
    double v = t.wraps ? table_wrap(t, raw) : raw;
    int n = t.n;
    const double* y = t.y.data();
    if (n == 1) return y[0];
    Interpolation interp = t.interpolation;
    if (v <= t.first) return interp == Interpolation::Extrapolate ? table_between(t, v, 0) : y[0];
    if (v >= t.last) return interp == Interpolation::Extrapolate ? table_between(t, v, n - 2) : y[n - 1];
    int i = table_segment(t, v);
    if (interp == Interpolation::Below) return y[i];
    if (interp == Interpolation::Above) return t.x[static_cast<std::size_t>(i)] == v ? y[i] : y[i + 1];
    if (interp == Interpolation::Nearest) {
        double dx = t.x[static_cast<std::size_t>(i) + 1] - t.x[static_cast<std::size_t>(i)];
        return (dx == 0 || (v - t.x[static_cast<std::size_t>(i)]) / dx < 0.5) ? y[i] : y[i + 1];
    }
    return table_between(t, v, i);
}

/// dy/dx at `raw` (zero for the step rules and at a step).
double table_slope(const LookupTable& t, double raw);

/// `interpolationUseEndValues(XI, X1, Y1, X2, Y2, ...)` and its sibling: `args` the lookup
/// value and then x, y pairs.
double interpolate_args(const double* args, std::size_t count, bool extrapolate);
double interpolate_slope(const double* args, std::size_t count, bool extrapolate);

/// A value a table's point is read as: null is 0, text a number where it is one.
double lookup_number(const Json& v);

}  // namespace kompartment
