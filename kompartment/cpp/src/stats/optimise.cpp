// The optimisers (see optimise.hpp): a port of the Julia package's stats/optimise.jl,
// operation for operation.

#include "stats/optimise.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <string_view>
#include <unordered_map>
#include <utility>

#include "engine/probabilistic.hpp"
#include "lang/jsmath.hpp"
#include "stats/pdf.hpp"
#include "stats/sample.hpp"
#include "util/errors.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
constexpr double Inf = std::numeric_limits<double>::infinity();

/// `Float64Array.from(values)`, read to length `n` (`_op_numbers`): past the end is NaN.
std::vector<double> op_numbers(const std::vector<Json>& values, std::size_t n) {
    std::vector<double> out;
    out.reserve(n);
    for (std::size_t i = 0; i < values.size() && i < n; i++) out.push_back(pd_to_number(values[i]));
    while (out.size() < n) out.push_back(NaN);
    return out;
}

/// The bounds, read to length `n` (`_op_bounds`): refused where either is not given.
std::pair<std::vector<double>, std::vector<double>> op_bounds(const Json& lower, const Json& upper, std::size_t n) {
    if (lower.is_null() || upper.is_null()) throw ArgumentError("lower and upper bounds are required");
    return {op_numbers(optimise_items(lower, "iterate"), n), op_numbers(optimise_items(upper, "iterate"), n)};
}

double op_clamp(double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }

std::vector<double> op_clamp_all(const std::vector<double>& x, const std::vector<double>& lower, const std::vector<double>& upper) {
    std::vector<double> out(x.size());
    for (std::size_t i = 0; i < x.size(); i++) out[i] = op_clamp(x[i], lower[i], upper[i]);
    return out;
}

/// Julia's `x == v` for a double and a number a caller wrote: exact, whatever its type.
bool equals_number(double x, const Json& v) {
    if (v.is_float()) return x == v.as_double();
    // An integer against a double: equal only where the double is that whole number.
    const long long i = v.as_int();
    if (!(x == std::trunc(x)) || !(x >= -9223372036854775808.0 && x < 9223372036854775808.0)) return false;
    return static_cast<long long>(x) == i;
}

/// `floor(Int, x)`, refused as Julia refuses a value no 64-bit integer holds.
long long floor_int(double x) {
    const double f = std::floor(x);
    if (!(f >= -9223372036854775808.0 && f < 9223372036854775808.0))
        throw JuliaError("InexactError", "InexactError: Int64(" + julia_float(f) + ")");
    return static_cast<long long>(f);
}

/// `values[i]`, NaN past the end (`_op_index`).
double op_index(const std::vector<double>& values, std::size_t i) { return i < values.size() ? values[i] : NaN; }

/// `values[i]`, refused past the end as Julia's indexing refuses it.
double checked(const std::vector<double>& values, std::size_t i) {
    if (i >= values.size())
        throw JuliaError("BoundsError", "BoundsError: attempt to access " + std::to_string(values.size()) + "-element Vector{Float64} at index [" +
                                            std::to_string(i + 1) + "]");
    return values[i];
}

/// An objective counted, stoppable and never asked twice for the same point (`_OpBudget`).
/// `keep`, where given, is asked after each evaluation for whatever else of it the caller
/// needs -- the residual vector Levenberg-Marquardt differences -- which is stored with the
/// point and handed back as `kept`.
class EvalBudget {
public:
    EvalBudget(OptimiseFunction f, double max_evals, const std::function<void(const OptimiseStep&)>& on_step, const std::function<bool()>& signal,
           std::function<std::optional<std::vector<double>>()> keep = nullptr)
        : f_(std::move(f)), max_evals_(max_evals), on_step_(on_step), signal_(signal), keep_(std::move(keep)) {}

    long long evals = 0;
    double best = Inf;
    std::optional<std::vector<double>> best_x;
    std::optional<std::vector<double>> kept;

    /// `_op_call!`.
    double call(const std::vector<double>& x) {
        if (signal_ && signal_()) throw OptimiseError("stopped");
        if (static_cast<double>(evals) >= max_evals_) throw OptimiseError("budget");
        // A simplex revisits a vertex it already knows; so does a population that converged.
        // Each of those is a whole integration.
        std::string key;
        for (std::size_t i = 0; i < x.size(); i++) {
            if (i) key.push_back(',');
            key += js_to_precision(x[i], 12);
        }
        // A point answered from memory is not counted against the budget. So a Nelder-Mead
        // simplex whose every new point is the same key -- no number in any coordinate, which
        // a start that is no number or infinite bounds come to -- and whose values hold an
        // Infinity, so that they never agree, goes on until its signal stops it: the Julia
        // package's fault, and the application's, kept (tools/calibrate_fixtures.jl has such
        // searches, stopped).
        auto had = seen_.find(key);
        if (had != seen_.end()) {
            kept = had->second.second;
            return had->second.first;
        }
        evals += 1;
        const double fx = f_(x);
        const double use = std::isfinite(fx) ? fx : Inf;
        kept = keep_ ? keep_() : std::nullopt;
        seen_.emplace(std::move(key), std::make_pair(use, kept));
        if (use < best) {
            best = use;
            best_x = x;
        }
        if (on_step_) {
            OptimiseStep step;
            step.evals = evals;
            step.fx = use;
            step.best = best;
            step.x = &x;
            step.best_x = best_x ? &*best_x : nullptr;
            on_step_(step);
        }
        return use;
    }

    /// `_op_done`.
    OptimiseResult done(const std::string& reason) const {
        OptimiseResult out;
        out.x = best_x;
        out.fx = best;
        out.evals = evals;
        out.reason = reason;
        return out;
    }

private:
    OptimiseFunction f_;
    double max_evals_;
    const std::function<void(const OptimiseStep&)>& on_step_;
    const std::function<bool()>& signal_;
    std::function<std::optional<std::vector<double>>()> keep_;
    std::unordered_map<std::string, std::pair<double, std::optional<std::vector<double>>>> seen_;
};

/// `something(v, fallback)` of a budget: the value, or the method's own where none is given.
double budget_of(const Json& v, double fallback) { return v.is_null() ? fallback : pd_to_number(v); }

}  // namespace

std::vector<Json> optimise_items(const Json& v, const char* what) {
    std::vector<Json> out;
    switch (v.type()) {
        case Json::Type::Null:
            throw JuliaError("MethodError", std::string("MethodError: no method matching ") + what + "(::Nothing)");
        case Json::Type::Array: return v.arr();
        case Json::Type::Object:
            out.assign(v.size(), Json::object());
            return out;
        case Json::Type::String: {
            // One per character as Julia counts them: a code point of well-formed UTF-8, or a
            // byte that is not.
            const std::string& s = v.as_string();
            for (std::size_t i = 0; i < s.size();) {
                const unsigned char c = static_cast<unsigned char>(s[i]);
                std::size_t len = c < 0x80 ? 1 : (c & 0xe0) == 0xc0 ? 2 : (c & 0xf0) == 0xe0 ? 3 : (c & 0xf8) == 0xf0 ? 4 : 1;
                bool ok = i + len <= s.size();
                for (std::size_t k = 1; ok && k < len; k++) ok = (static_cast<unsigned char>(s[i + k]) & 0xc0) == 0x80;
                i += ok ? len : 1;
                out.push_back(Json::object());
            }
            return out;
        }
        default: out.push_back(v); return out;
    }
}

// --- how a residual is measured, and how a variable moves ------------------------------------------

std::optional<OptimiseScale> optimise_scale(const Json* key) {
    const std::string k = pd_js_str(key);
    if (k == "absolute") return OptimiseScale::Absolute;
    if (k == "relative") return OptimiseScale::Relative;
    if (k == "log") return OptimiseScale::Log;
    return std::nullopt;
}

double optimise_residual(OptimiseScale scale, double got, double want) {
    switch (scale) {
        case OptimiseScale::Absolute: return got - want;
        case OptimiseScale::Relative: return want == 0 ? got : (got - want) / std::fabs(want);
        case OptimiseScale::Log: return (got > 0 && want > 0) ? js_log(got) - js_log(want) : NaN;
    }
    return NaN;
}

std::optional<OptimiseSpace> optimise_space(const Json* key) {
    const std::string k = pd_js_str(key);
    if (k == "linear") return OptimiseSpace::Linear;
    if (k == "log") return OptimiseSpace::Log;
    return std::nullopt;
}

double space_to(OptimiseSpace space, double v) { return space == OptimiseSpace::Log ? js_log(v) : v; }
double space_from(OptimiseSpace space, double u) { return space == OptimiseSpace::Log ? js_exp(u) : u; }
bool space_ok(OptimiseSpace space, double lo, double hi) { return space == OptimiseSpace::Linear || (lo > 0 && hi > 0); }

std::vector<double> optimise_readings(const Json& readings) {
    std::vector<double> out;
    if (!readings.is_array()) return out;
    for (const Json& v : readings.arr()) out.push_back(v.is_number() ? v.as_double() : pd_to_number(v));
    return out;
}

Objective objective_of(const std::vector<double>& readings, const std::vector<Json>& targets) {
    Objective out;
    out.residuals.reserve(targets.size());
    for (std::size_t i = 0; i < targets.size(); i++) {
        const Json& t = targets[i];
        const OptimiseScale scale = optimise_scale(pd_prop(t, "scale")).value_or(OptimiseScale::Relative);
        const Json* w = pd_prop(t, "weight");
        const double weight = (w && w->is_number() && std::isfinite(w->as_double()) && w->as_double() > 0) ? w->as_double() : 1.0;
        const double r = optimise_residual(scale, i < readings.size() ? readings[i] : NaN, pd_to_number(pd_prop(t, "value")));
        const double use = std::isfinite(r) ? std::sqrt(weight) * r : 1e6;
        out.residuals.push_back(use);
        out.objective += use * use;
    }
    return out;
}

// --- Nelder-Mead ------------------------------------------------------------------------------------

OptimiseResult nelder_mead(const OptimiseFunction& f, const Json& start, const OptimiseOptions& o) {
    const std::vector<Json> raw_start = optimise_items(start, "length");
    const std::size_t n = raw_start.size();
    if (n == 0) throw OptimiseError("Nothing to vary.");
    const double max_evals = budget_of(o.max_evals, 400);
    const double tol = o.tol ? *o.tol : 1e-8;
    const auto [lower, upper] = op_bounds(o.lower, o.upper, n);
    EvalBudget budget(f, max_evals, o.on_step, o.signal);
    auto at = [&](const std::vector<double>& x) { return budget.call(op_clamp_all(x, lower, upper)); };
    const std::vector<double> s0 = op_numbers(raw_start, n);
    const double dn = static_cast<double>(n);
    try {
        // The simplex: the start, then one step along each axis.
        std::vector<std::vector<double>> simplex{s0};
        for (std::size_t i = 0; i < n; i++) {
            std::vector<double> x = s0;
            const double span = upper[i] - lower[i];
            const double step = span > 0 ? span * 0.05 : std::fabs(x[i]) * 0.05 + 1e-6;
            x[i] = op_clamp(x[i] + step, lower[i], upper[i]);
            // A vertex that landed on top of another is no vertex: step the other way rather
            // than starting with a degenerate simplex.
            if (raw_start[i].is_number() && equals_number(x[i], raw_start[i])) x[i] = op_clamp(raw_start[i].as_double() - step, lower[i], upper[i]);
            simplex.push_back(std::move(x));
        }
        std::vector<double> fs;
        fs.reserve(n + 1);
        for (const auto& x : simplex) fs.push_back(at(x));
        std::vector<std::size_t> order(n + 1);
        for (;;) {
            // Sorted by value: the best first, the worst last, a stable sort.
            std::iota(order.begin(), order.end(), std::size_t{0});
            std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) { return fs[a] < fs[b]; });
            {
                std::vector<std::vector<double>> sorted;
                std::vector<double> fsorted;
                sorted.reserve(n + 1);
                fsorted.reserve(n + 1);
                for (std::size_t k : order) {
                    sorted.push_back(std::move(simplex[k]));
                    fsorted.push_back(fs[k]);
                }
                simplex = std::move(sorted);
                fs = std::move(fsorted);
            }
            // Converged when the simplex has collapsed onto one value.
            const double spread = std::fabs(fs[n] - fs[0]) / (std::fabs(fs[0]) + std::fabs(fs[n]) + 1e-300);
            if (spread < tol) return budget.done("converged");
            // The centroid of all but the worst.
            std::vector<double> mid(n, 0.0);
            for (std::size_t i = 0; i < n; i++)
                for (std::size_t k = 0; k < n; k++) mid[k] += simplex[i][k] / dn;
            auto along = [&](double t) {
                std::vector<double> x(n);
                for (std::size_t k = 0; k < n; k++) x[k] = mid[k] + t * (mid[k] - simplex[n][k]);
                return x;
            };
            std::vector<double> xr = along(1.0);
            const double fr = at(xr);
            if (fr < fs[0]) {
                std::vector<double> xe = along(2.0);
                const double fe = at(xe);
                if (fe < fr) {
                    simplex[n] = std::move(xe);
                    fs[n] = fe;
                } else {
                    simplex[n] = std::move(xr);
                    fs[n] = fr;
                }
                continue;
            }
            if (fr < fs[n - 1]) {
                simplex[n] = std::move(xr);
                fs[n] = fr;
                continue;
            }
            // Contract, on whichever side is better.
            std::vector<double> xc = fr < fs[n] ? along(0.5) : along(-0.5);
            const double fc = at(xc);
            if (fc < (fs[n] < fr ? fs[n] : fr)) {
                simplex[n] = std::move(xc);
                fs[n] = fc;
                continue;
            }
            // Nothing helped: pull everything halfway towards the best.
            for (std::size_t i = 1; i <= n; i++) {
                std::vector<double> x(n);
                for (std::size_t k = 0; k < n; k++) x[k] = simplex[0][k] + 0.5 * (simplex[i][k] - simplex[0][k]);
                simplex[i] = op_clamp_all(x, lower, upper);
                fs[i] = at(simplex[i]);
            }
        }
    } catch (const OptimiseError& e) {
        return budget.done(e.what());
    }
}

// --- Levenberg-Marquardt ----------------------------------------------------------------------------

std::optional<std::vector<double>> optimise_solve(const std::vector<std::vector<double>>& A, const std::vector<double>& b) {
    const std::size_t n = b.size();
    std::vector<std::vector<double>> M(n);
    for (std::size_t i = 0; i < n; i++) {
        M[i].assign(A[i].begin(), A[i].begin() + static_cast<std::ptrdiff_t>(n));
        M[i].push_back(b[i]);
    }
    for (std::size_t c = 0; c < n; c++) {
        std::size_t p = c;
        for (std::size_t i = c + 1; i < n; i++)
            if (std::fabs(M[i][c]) > std::fabs(M[p][c])) p = i;
        if (!(std::fabs(M[p][c]) > 1e-300)) return std::nullopt;
        std::swap(M[c], M[p]);
        for (std::size_t i = c + 1; i < n; i++) {
            const double k = M[i][c] / M[c][c];
            if (k == 0) continue;
            std::vector<double>& row = M[i];
            const std::vector<double>& pivot = M[c];
            for (std::size_t j = c; j <= n; j++) row[j] -= k * pivot[j];
        }
    }
    std::vector<double> x(n, 0.0);
    for (std::size_t i = n; i-- > 0;) {
        double s = M[i][n];
        for (std::size_t j = i + 1; j < n; j++) s -= M[i][j] * x[j];
        x[i] = s / M[i][i];
    }
    return x;
}

OptimiseResult levenberg_marquardt(const ResidualFunction& residuals, const Json& start, const OptimiseOptions& o) {
    const std::vector<Json> raw_start = optimise_items(start, "length");
    const std::size_t n = raw_start.size();
    if (n == 0) throw OptimiseError("Nothing to vary.");
    const double max_evals = budget_of(o.max_evals, 400);
    const double tol = o.tol ? *o.tol : 1e-10;
    const auto [lower, upper] = op_bounds(o.lower, o.upper, n);
    std::optional<std::vector<double>> last;
    auto f = [&](const std::vector<double>& x) {
        last = residuals(x);
        double s = 0.0;
        for (double r : *last) s += r * r;
        return std::isfinite(s) ? s : Inf;
    };
    // The residuals are kept with the point they belong to, so a point the budget answers
    // from memory comes back with its own.
    EvalBudget budget(f, max_evals, o.on_step, o.signal, [&]() { return last; });
    auto eval_at = [&](const std::vector<double>& x) {
        const double fx = budget.call(op_clamp_all(x, lower, upper));
        return std::make_pair(fx, budget.kept);
    };
    try {
        std::vector<double> x = op_clamp_all(op_numbers(raw_start, n), lower, upper);
        auto [fx, r0] = eval_at(x);
        // (Never so: the residuals come back with every point. The Julia package's own words.)
        if (!r0) return budget.done("no residuals");
        std::vector<double> r = std::move(*r0);
        const std::size_t m = r.size();
        double lam = 1e-3;
        for (;;) {
            // The Jacobian, column by column: one extra evaluation each.
            std::vector<std::vector<double>> J;
            J.reserve(n);
            for (std::size_t k = 0; k < n; k++) {
                const double span = upper[k] - lower[k];
                const double a = (span > 0 ? span : std::fabs(x[k]) + 1) * 1e-6, b = std::fabs(x[k]) * 1e-9;
                const double h = b > a ? b : a;
                std::vector<double> xp = x;
                xp[k] = op_clamp(x[k] + h, lower[k], upper[k]);
                if (xp[k] == x[k]) xp[k] = op_clamp(x[k] - h, lower[k], upper[k]);
                const double step = xp[k] - x[k];
                if (step == 0) {
                    J.emplace_back(m, 0.0);
                    continue;
                }
                const std::vector<double> got_r = *eval_at(xp).second;
                std::vector<double> col(m);
                for (std::size_t i = 0; i < m; i++) col[i] = (op_index(got_r, i) - checked(r, i)) / step;
                J.push_back(std::move(col));
            }
            // JᵀJ and Jᵀr, which are n x n and n however long the residual vector is.
            std::vector<std::vector<double>> A(n, std::vector<double>(n, 0.0));
            std::vector<double> g(n, 0.0);
            for (std::size_t a = 0; a < n; a++) {
                for (std::size_t b = a; b < n; b++) {
                    double s = 0.0;
                    const std::vector<double>& Ja = J[a];
                    const std::vector<double>& Jb = J[b];
                    for (std::size_t i = 0; i < m; i++) s += Ja[i] * Jb[i];
                    A[a][b] = s;
                    A[b][a] = s;
                }
                double s = 0.0;
                const std::vector<double>& Ja = J[a];
                for (std::size_t i = 0; i < m; i++) s += Ja[i] * checked(r, i);
                g[a] = s;
            }
            bool stepped = false;
            for (int tries = 0; tries < 12; tries++) {
                std::vector<std::vector<double>> M;
                M.reserve(n);
                for (std::size_t a = 0; a < n; a++) {
                    std::vector<double> row = A[a];
                    // Marquardt's own scaling: the damping follows the curvature rather than
                    // being the same in every direction.
                    row[a] += lam * (A[a][a] > 0 ? A[a][a] : 1.0);
                    M.push_back(std::move(row));
                }
                std::optional<std::vector<double>> dx = optimise_solve(M, g);
                if (!dx) {
                    lam *= 10;
                    continue;
                }
                std::vector<double> trial(n);
                for (std::size_t k = 0; k < n; k++) trial[k] = x[k] - (*dx)[k];
                auto [got_fx, got_r] = eval_at(trial);
                if (got_fx < fx) {
                    const double gain = (fx - got_fx) / (std::fabs(fx) + 1e-300);
                    x = op_clamp_all(trial, lower, upper);
                    fx = got_fx;
                    r = std::move(*got_r);
                    lam = 1e-12 > lam / 10 ? 1e-12 : lam / 10;
                    stepped = true;
                    if (gain < tol) return budget.done("converged");
                    break;
                }
                lam *= 10;
                if (lam > 1e12) return budget.done("converged");
            }
            if (!stepped) return budget.done("converged");
        }
    } catch (const OptimiseError& e) {
        return budget.done(e.what());
    }
}

// --- differential evolution -------------------------------------------------------------------------

OptimiseResult differential_evolution(const OptimiseFunction& f, const OptimiseOptions& o) {
    if (o.lower.is_null()) throw ArgumentError("lower and upper bounds are required");
    const std::size_t n = optimise_items(o.lower, "length").size();
    if (n == 0) throw OptimiseError("Nothing to vary.");
    const auto [lower, upper] = op_bounds(o.lower, o.upper, n);
    const double max_evals = budget_of(o.max_evals, 2000);
    const double F = o.F ? *o.F : 0.7;
    const double CR = o.CR ? *o.CR : 0.9;
    // Ten per variable is the usual advice, floored so a one-variable problem still has a
    // population and capped so a ten-variable one still finishes.
    const double size_ = pd_to_number(o.pop_size);
    const double N = size_ > 3 ? size_ : static_cast<double>(std::min<long long>(60, std::max<long long>(8, 10 * static_cast<long long>(n))));
    Mulberry32 nxt(sm_to_uint32(o.seed));
    EvalBudget budget(f, max_evals, o.on_step, o.signal);
    const double dn = static_cast<double>(n);
    try {
        std::vector<std::vector<double>> pop;
        std::vector<double> fit;
        std::optional<std::vector<double>> first;
        if (pd_truthy(o.start)) first = op_numbers(optimise_items(o.start, "iterate"), n);
        long long i = 0;
        while (static_cast<double>(i) < N) {
            std::vector<double> x(n);
            if (i == 0 && first) {
                for (std::size_t k = 0; k < n; k++) x[k] = op_clamp((*first)[k], lower[k], upper[k]);
            } else {
                for (std::size_t k = 0; k < n; k++) x[k] = lower[k] + nxt.next() * (upper[k] - lower[k]);
            }
            pop.push_back(x);
            fit.push_back(budget.call(x));
            i += 1;
        }
        for (;;) {
            i = 0;
            while (static_cast<double>(i) < N) {
                long long a = i, b = i, c = i;
                while (a == i) a = floor_int(nxt.next() * N);
                while (b == i || b == a) b = floor_int(nxt.next() * N);
                while (c == i || c == a || c == b) c = floor_int(nxt.next() * N);
                // At least one coordinate always comes from the mutant, or a trial could be its
                // own parent and the population stall.
                const long long must = floor_int(nxt.next() * dn);
                const std::vector<double>& pa = pop[static_cast<std::size_t>(a)];
                const std::vector<double>& pb = pop[static_cast<std::size_t>(b)];
                const std::vector<double>& pc = pop[static_cast<std::size_t>(c)];
                const std::vector<double>& pi_ = pop[static_cast<std::size_t>(i)];
                std::vector<double> trial(n, 0.0);
                for (std::size_t k = 0; k < n; k++) {
                    if (static_cast<long long>(k) == must || nxt.next() < CR) {
                        trial[k] = op_clamp(pa[k] + F * (pb[k] - pc[k]), lower[k], upper[k]);
                    } else {
                        trial[k] = pi_[k];
                    }
                }
                const double ft = budget.call(trial);
                if (ft <= fit[static_cast<std::size_t>(i)]) {
                    pop[static_cast<std::size_t>(i)] = std::move(trial);
                    fit[static_cast<std::size_t>(i)] = ft;
                }
                i += 1;
            }
            // Converged when the whole population agrees. (Every value is a number: a point's
            // value is finite or Infinity.)
            const double lo = *std::min_element(fit.begin(), fit.end());
            const double hi = *std::max_element(fit.begin(), fit.end());
            if (hi - lo <= std::fabs(lo) * 1e-10) return budget.done("converged");
        }
    } catch (const OptimiseError& e) {
        return budget.done(e.what());
    }
}

// --- the table ----------------------------------------------------------------------------------------

std::optional<OptimiseMethod> optimise_method(const Json* key) {
    const std::string k = pd_js_str(key);
    if (k == "nelder") return OptimiseMethod::Nelder;
    if (k == "lm") return OptimiseMethod::Lm;
    if (k == "de") return OptimiseMethod::De;
    return std::nullopt;
}

OptimiseResult run_optimise_method(OptimiseMethod method, const OptimiseContext& ctx, const OptimiseOptions& o) {
    const Json start = Json::array(ctx.start);
    OptimiseOptions opts;
    opts.lower = o.lower;
    opts.upper = o.upper;
    opts.max_evals = o.max_evals;
    opts.on_step = o.on_step;
    opts.signal = o.signal;
    switch (method) {
        case OptimiseMethod::Nelder: return nelder_mead(ctx.objective, start, opts);
        case OptimiseMethod::Lm: return levenberg_marquardt(ctx.residuals, start, opts);
        case OptimiseMethod::De:
            opts.start = start;
            opts.seed = o.seed;
            return differential_evolution(ctx.objective, opts);
    }
    return nelder_mead(ctx.objective, start, opts);
}

}  // namespace kompartment
