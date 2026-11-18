#include "engine/lookup.hpp"

#include <algorithm>
#include <limits>
#include <numeric>

#include "engine/farfield_domain.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {
const double NaN = std::numeric_limits<double>::quiet_NaN();

Interpolation rule_of(const std::string& name) {
    if (name == "linear") return Interpolation::Linear;
    if (name == "extrapolate") return Interpolation::Extrapolate;
    if (name == "below") return Interpolation::Below;
    if (name == "above") return Interpolation::Above;
    if (name == "nearest") return Interpolation::Nearest;
    throw LookupError("'" + name + "' is not an interpolation rule (linear, extrapolate, below, above, nearest)");
}

bool flat(const Json& a) {
    if (!a.is_array()) return false;
    for (const Json& v : a.arr())
        if (!(v.is_number() || v.is_string())) return false;
    return true;
}
}  // namespace

double lookup_number(const Json& v) {
    if (v.is_null()) return 0.0;
    if (v.is_bool()) return v.as_bool() ? 1.0 : 0.0;
    if (v.is_number()) return v.as_double();
    if (v.is_string()) return js_number_of(v);      // JavaScript's grammar: `1_000` is NaN
    return NaN;
}

void LookupTable::finish(std::vector<double> xs, std::vector<double> ys, const std::string& rule, bool cyc) {
    interpolation = rule_of(rule);
    // Sorted by x, points of one x in the order given; a point with no x last.
    std::vector<std::size_t> order(xs.size());
    std::iota(order.begin(), order.end(), std::size_t{0});
    std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        double p = xs[a], q = xs[b];
        bool pn = std::isnan(p), qn = std::isnan(q);
        if (pn != qn) return qn;
        if (pn) return false;
        if (p < q) return true;
        if (q < p) return false;
        return std::signbit(p) && !std::signbit(q);
    });
    x.resize(xs.size());
    y.resize(xs.size());
    for (std::size_t k = 0; k < order.size(); k++) {
        x[k] = xs[order[k]];
        y[k] = ys[order[k]];
    }
    n = static_cast<int>(x.size());
    if (n == 0) throw LookupError("A lookup table needs at least one point");
    for (double v : x)
        if (!std::isfinite(v)) throw LookupError("A lookup point has no x value");
    first = x.front();
    last = x.back();
    span = last - first;
    cyclic = cyc;
    wraps = cyc && span > 0;
}

LookupTable::LookupTable(const Json& points, const std::string& rule, bool cyc) {
    rule_of(rule);   // the rule is checked before the points are read
    std::vector<double> xs, ys;
    if (points.is_array() && points.size() == 2 && flat(points[0]) && flat(points[1]) && points[0].size() == points[1].size() &&
        points[0].size() != 2) {
        for (const Json& v : points[0].arr()) xs.push_back(lookup_number(v));
        for (const Json& v : points[1].arr()) ys.push_back(lookup_number(v));
    } else if (points.is_array()) {
        for (const Json& p : points.arr()) {
            Json px, py;
            if (p.is_array()) {
                if (p.size() > 0) px = p[0];
                if (p.size() > 1) py = p[1];
            } else {
                px = p.get("x");
                py = p.get("y");
            }
            xs.push_back(px.is_null() ? NaN : lookup_number(px));
            ys.push_back(py.is_null() ? NaN : lookup_number(py));
        }
    }
    finish(std::move(xs), std::move(ys), rule, cyc);
}

LookupTable::LookupTable(std::vector<double> xs, std::vector<double> ys, const std::string& rule, bool cyc) {
    finish(std::move(xs), std::move(ys), rule, cyc);
}

double table_slope(const LookupTable& t, double raw) {
    int n = t.n;
    if (n == 1 || t.interpolation == Interpolation::Below || t.interpolation == Interpolation::Above ||
        t.interpolation == Interpolation::Nearest)
        return 0.0;
    double v = t.wraps ? table_wrap(t, raw) : raw;
    int i;
    if (v < t.first || v > t.last) {
        if (t.interpolation != Interpolation::Extrapolate) return 0.0;
        i = v < t.first ? 0 : n - 2;
    } else {
        i = table_segment(t, v);
    }
    double dx = t.x[static_cast<std::size_t>(i) + 1] - t.x[static_cast<std::size_t>(i)];
    return dx == 0 ? 0.0 : (t.y[static_cast<std::size_t>(i) + 1] - t.y[static_cast<std::size_t>(i)]) / dx;
}

namespace {

LookupTable table_of(const double* args, std::size_t count, bool extrapolate) {
    std::vector<double> xs, ys;
    for (std::size_t i = 1; i + 1 < count; i += 2) {
        xs.push_back(args[i]);
        ys.push_back(args[i + 1]);
    }
    return LookupTable(std::move(xs), std::move(ys), extrapolate ? "extrapolate" : "linear");
}

// `table_between` on the points of an argument list: segment `i` from 0, point k at
// args[2k + 1], args[2k + 2].
inline double between_points(const double* args, double v, std::size_t i) {
    double x1 = args[2 * i + 1], y1 = args[2 * i + 2], x2 = args[2 * i + 3], y2 = args[2 * i + 4];
    double dx = x2 - x1;
    if (dx == 0) return y2;
    return y1 + ((v - x1) / dx) * (y2 - y1);
}

}  // namespace

double interpolate_args(const double* args, std::size_t count, bool extrapolate) {
    std::size_t rest = count - 1;
    if (rest < 2 || rest % 2 != 0)
        throw LookupError("interpolation needs a lookup value and then x, y pairs; got " + std::to_string(rest) + " value(s) after it");
    std::size_t n = rest / 2;   // the points
    // Points that come in order of x, every x finite, are read where they stand, by the
    // table's own arithmetic; any others are made into a table first.
    for (std::size_t k = 0; k < n; k++) {
        double x = args[2 * k + 1];
        if (!(std::isfinite(x) && (k == 0 || args[2 * k - 1] <= x))) return table_at(table_of(args, count, extrapolate), args[0]);
    }
    double v = args[0];
    if (n == 1) return args[2];
    if (v <= args[1]) return extrapolate ? between_points(args, v, 0) : args[2];
    if (v >= args[2 * n - 1]) return extrapolate ? between_points(args, v, n - 2) : args[2 * n];
    if (v != v) return between_points(args, v, 0);
    std::size_t lo = 0, hi = n;
    while (lo < hi) {
        std::size_t mid = (lo + hi) >> 1;
        if (v < args[2 * mid + 1]) hi = mid;
        else lo = mid + 1;
    }
    std::size_t i = lo == 0 ? 0 : lo - 1;
    if (i > n - 2) i = n - 2;
    return between_points(args, v, i);
}

double interpolate_slope(const double* args, std::size_t count, bool extrapolate) {
    std::size_t rest = count - 1;
    if (rest < 2 || rest % 2 != 0) return 0.0;
    return table_slope(table_of(args, count, extrapolate), args[0]);
}

}  // namespace kompartment
