// The C++ solvers against the Python engine's, case by case
// (julia/tools/solver_fixtures.py writes julia/test/solvers/fixtures.json; a port of
// julia/test/solvers/runtests.jl with problems.jl).
//
// A run must take the Python run's steps -- the same accepted times, the same
// counts -- and give its outputs bit for bit, on the sparse path too, where
// both factorise with the application's sparse LUs; a failure must say what
// Python's says, word for word. The made-up landscape's derivative is scipy's
// CSR product on the Python side, whose multiply-adds are fused: its runs
// agree to the tolerance. So do the runs of more than 200 states with a dense
// matrix, which Python hands to LAPACK.

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "check.hpp"
#include "solvers/solvers.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

using namespace kompartment;

namespace {

// --- decoding -----------------------------------------------------------------------------------------

/// A number of the fixtures: a C hex-float string, "inf", "-inf", "nan", or a plain number.
double num(const Json& v) {
    if (v.is_string()) {
        const std::string& s = v.as_string();
        if (s == "inf") return std::numeric_limits<double>::infinity();
        if (s == "-inf") return -std::numeric_limits<double>::infinity();
        if (s == "nan") return std::numeric_limits<double>::quiet_NaN();
        return std::strtod(s.c_str(), nullptr);
    }
    return v.as_double();
}

Vec fvec(const Json& list) {
    Vec out;
    out.reserve(list.size());
    for (const Json& v : list.arr()) out.push_back(num(v));
    return out;
}

std::vector<I32> ivec(const Json& list) {
    std::vector<I32> out;
    out.reserve(list.size());
    for (const Json& v : list.arr()) out.push_back(static_cast<I32>(v.as_int()));
    return out;
}

bool truthy(const Json& v) {
    if (v.is_bool()) return v.as_bool();
    if (v.is_number()) return v.as_double() != 0;
    return !v.is_null();
}

/// The larger of two errors, a NaN staying one.
double worse(double worst, double e) { return (worst != worst || e != e) ? std::nan("") : std::max(worst, e); }

bool bits_equal(const Vec& a, const Vec& b) {
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); i++)
        if (!check::same_bits(a[i], b[i])) return false;
    return true;
}

// --- the problems -------------------------------------------------------------------------------------
//
// The problems of tools/solver_fixtures.py, written again with the same arithmetic in the same
// order, so that a derivative here is the Python one to the last bit. Each gives the derivative,
// the Jacobian's parts (n, rows, cols, values or none, constant; counted from zero) and the events.

struct Parts {
    int n = 0;
    std::vector<I32> rows;
    std::vector<I32> cols;
    JacobianEvaluate values;
    bool constant = false;
};

struct Problem {
    RhsFunction f;
    std::optional<Parts> parts;
    std::optional<EventFunctions> events;
};

Problem prob_robertson(const Json&) {
    Problem p;
    p.f = [](Vec& dy, double, const Vec& y) {
        dy[0] = -0.04 * y[0] + 1e4 * y[1] * y[2];
        dy[1] = 0.04 * y[0] - 1e4 * y[1] * y[2] - 3e7 * y[1] * y[1];
        dy[2] = 3e7 * y[1] * y[1];
    };
    Parts parts;
    parts.n = 3;
    parts.rows = {0, 1, 0, 1, 2, 0, 1};
    parts.cols = {0, 0, 1, 1, 1, 2, 2};
    parts.values = [](Vec& v, double, const Vec& y) {
        v[0] = -0.04;
        v[1] = 0.04;
        v[2] = 1e4 * y[2];
        v[3] = -1e4 * y[2] - 6e7 * y[1];
        v[4] = 6e7 * y[1];
        v[5] = 1e4 * y[1];
        v[6] = -1e4 * y[1];
        return true;
    };
    p.parts = parts;
    return p;
}

Problem prob_vdp(const Json& params) {
    const double mu = num(params.get("mu"));
    Problem p;
    p.f = [mu](Vec& dy, double, const Vec& y) {
        dy[0] = y[1];
        dy[1] = mu * ((1.0 - y[0] * y[0]) * y[1]) - y[0];
    };
    Parts parts;
    parts.n = 2;
    parts.rows = {1, 0, 1};
    parts.cols = {0, 1, 1};
    parts.values = [mu](Vec& v, double, const Vec& y) {
        v[0] = -2.0 * mu * y[0] * y[1] - 1.0;
        v[1] = 1.0;
        v[2] = mu * (1.0 - y[0] * y[0]);
        return true;
    };
    p.parts = parts;
    return p;
}

Problem prob_decay3(const Json& params) {
    const Vec l = fvec(params.get("l"));
    const double l1 = l[0], l2 = l[1], l3 = l[2];
    Problem p;
    p.f = [l1, l2, l3](Vec& dy, double, const Vec& y) {
        dy[0] = -l1 * y[0];
        dy[1] = l1 * y[0] - l2 * y[1];
        dy[2] = l2 * y[1] - l3 * y[2];
    };
    Parts parts;
    parts.n = 3;
    parts.rows = {0, 1, 1, 2, 2};
    parts.cols = {0, 0, 1, 1, 2};
    const Vec vals = {-l1, l1, -l2, l2, -l3};
    parts.values = [vals](Vec& v, double, const Vec&) {
        std::copy(vals.begin(), vals.end(), v.begin());
        return true;
    };
    parts.constant = true;
    p.parts = parts;
    return p;
}

Problem prob_orego(const Json&) {
    const double s = 77.27, q = 8.375e-6, w = 0.161;
    Problem p;
    p.f = [s, q, w](Vec& dy, double, const Vec& y) {
        dy[0] = s * (y[1] - y[0] * y[1] + y[0] - q * y[0] * y[0]);
        dy[1] = (-y[1] - y[0] * y[1] + y[2]) / s;
        dy[2] = w * (y[0] - y[2]);
    };
    return p;
}

Problem prob_hires(const Json&) {
    Problem p;
    p.f = [](Vec& dy, double, const Vec& y) {
        const double f7 = 280.0 * y[5] * y[7] - 1.81 * y[6];
        dy[0] = -1.71 * y[0] + 0.43 * y[1] + 8.32 * y[2] + 0.0007;
        dy[1] = 1.71 * y[0] - 8.75 * y[1];
        dy[2] = -10.03 * y[2] + 0.43 * y[3] + 0.035 * y[4];
        dy[3] = 8.32 * y[1] + 1.71 * y[2] - 1.12 * y[3];
        dy[4] = -1.745 * y[4] + 0.43 * y[5] + 0.43 * y[6];
        dy[5] = -280.0 * y[5] * y[7] + 0.69 * y[3] + 1.71 * y[4] - 0.43 * y[5] + 0.69 * y[6];
        dy[6] = f7;
        dy[7] = -f7;
    };
    return p;
}

Problem prob_ball(const Json&) {
    const double g = 9.81;
    Problem p;
    p.f = [g](Vec& dy, double, const Vec& y) {
        dy[0] = y[1];
        dy[1] = -g;
    };
    p.events = EventFunctions(1, [](Vec& out, double, const Vec& y) { out[0] = y[0]; }, std::vector<int>{-1});
    return p;
}

Problem prob_nonneg(const Json&) {
    Problem p;
    p.f = [](Vec& dy, double, const Vec& y) {
        dy[0] = -0.5 - 0.1 * y[0] + 0.05 * y[1];
        dy[1] = 0.1 * y[0] - 0.05 * y[1];
    };
    Parts parts;
    parts.n = 2;
    parts.rows = {0, 1, 0, 1};
    parts.cols = {0, 0, 1, 1};
    p.parts = parts;
    return p;
}

Problem prob_chain(const Json& params) {
    const Vec k = fvec(params.get("k"));
    const int n = static_cast<int>(k.size());
    Problem p;
    p.f = [k, n](Vec& dy, double, const Vec& y) {
        for (int i = 0; i < n; i++) dy[i] = -k[i] * y[i];
        for (int i = 1; i < n; i++) dy[i] += k[i - 1] * y[i - 1];
    };
    Parts parts;
    parts.n = n;
    Vec vals;
    for (int i = 0; i < n; i++) {
        parts.rows.push_back(i);
        parts.cols.push_back(i);
        vals.push_back(-k[i]);
        if (i + 1 < n) {
            parts.rows.push_back(i + 1);
            parts.cols.push_back(i);
            vals.push_back(k[i]);
        }
    }
    parts.values = [vals](Vec& v, double, const Vec&) {
        std::copy(vals.begin(), vals.end(), v.begin());
        return true;
    };
    parts.constant = true;
    p.parts = parts;
    return p;
}

/// landscape_matrix of solver_fixtures.py: the entries (row, column, value), and the source.
struct Landscape {
    int n = 0;
    std::vector<I32> rows, cols;
    Vec vals;
    Vec src;
};

Landscape landscape_matrix(int nb, int B = 10) {
    Landscape m;
    const int n = nb * B;
    m.n = n;
    Vec out(static_cast<std::size_t>(n), 0.0);
    auto rate = [](long long i, long long a) {
        return std::ldexp(static_cast<double>(1 + (i * a) % 97), -static_cast<int>((i * a) % 13));
    };
    auto flow = [&](int src, int dst, double r) {
        m.rows.push_back(dst);
        m.cols.push_back(src);
        m.vals.push_back(r);
        out[src] += r;
    };
    for (int b = 0; b < nb; b++) {
        const int base = b * B;
        for (int j = 0; j < B; j++) {
            const int i = base + j;
            if (j + 1 < B) {
                flow(i, i + 1, rate(i, 7919));
                flow(i + 1, i, rate(i, 104729) * 0.25);
            }
            flow(i, base + (j + 4) % B, rate(i, 1299709) * 0.125);
        }
        const int last = base + B - 1;
        if (b + 1 < nb) flow(last, base + B, rate(b, 15485863));
        if (b + 5 < nb) flow(last, base + 5 * B + 1, rate(b, 32452843) * 0.5);
    }
    for (int i = 0; i < n; i++) {
        m.rows.push_back(i);
        m.cols.push_back(i);
        m.vals.push_back(-(out[i] + 1e-3 * (1 + i % 5)));
    }
    m.src.assign(static_cast<std::size_t>(n), 0.0);
    for (int i = 0; i < n; i += B) m.src[i] = 1.0;
    return m;
}

Problem prob_landscape(const Json& params) {
    const Landscape m = landscape_matrix(static_cast<int>(num(params.get("nb"))));
    const int n = m.n;
    const std::size_t nz = m.vals.size();
    // The matrix by columns (its entries are distinct), which is the pattern's order, and by rows.
    std::vector<std::size_t> by_col(nz), by_row(nz);
    for (std::size_t q = 0; q < nz; q++) by_col[q] = by_row[q] = q;
    std::sort(by_col.begin(), by_col.end(), [&](std::size_t a, std::size_t b) {
        return m.cols[a] != m.cols[b] ? m.cols[a] < m.cols[b] : m.rows[a] < m.rows[b];
    });
    std::sort(by_row.begin(), by_row.end(), [&](std::size_t a, std::size_t b) {
        return m.rows[a] != m.rows[b] ? m.rows[a] < m.rows[b] : m.cols[a] < m.cols[b];
    });
    bool distinct = true;
    for (std::size_t q = 1; q < nz; q++)
        distinct &= !(m.cols[by_col[q]] == m.cols[by_col[q - 1]] && m.rows[by_col[q]] == m.rows[by_col[q - 1]]);
    CHECK(distinct);
    // The derivative by rows, each row's entries in column order (scipy's CSR
    // product, without its fused multiply-adds: agreement here is to the
    // tolerance only).
    std::vector<I32> rp(static_cast<std::size_t>(n) + 1, 0), ci(nz);
    Vec rv(nz);
    for (std::size_t q = 0; q < nz; q++) {
        rp[m.rows[by_row[q]] + 1] += 1;
        ci[q] = m.cols[by_row[q]];
        rv[q] = m.vals[by_row[q]];
    }
    for (int i = 0; i < n; i++) rp[i + 1] += rp[i];
    const Vec src = m.src;
    Problem p;
    p.f = [n, rp, ci, rv, src](Vec& dy, double, const Vec& y) {
        for (int i = 0; i < n; i++) {
            double s = 0.0;
            for (I32 q = rp[i]; q < rp[i + 1]; q++) s += rv[q] * y[ci[q]];
            dy[i] = s + src[i];
        }
    };
    Parts parts;
    parts.n = n;
    Vec data(nz);
    for (std::size_t q = 0; q < nz; q++) {
        parts.rows.push_back(m.rows[by_col[q]]);
        parts.cols.push_back(m.cols[by_col[q]]);
        data[q] = m.vals[by_col[q]];
    }
    parts.values = [data](Vec& v, double, const Vec&) {
        std::copy(data.begin(), data.end(), v.begin());
        return true;
    };
    parts.constant = true;
    p.parts = parts;
    return p;
}

Problem prob_robertson_dae(const Json&) {
    Problem p;
    p.f = [](Vec& dy, double, const Vec& y) {
        dy[0] = -0.04 * y[0] + 1e4 * y[1] * y[2];
        dy[1] = 0.04 * y[0] - 1e4 * y[1] * y[2] - 3e7 * y[1] * y[1];
        dy[2] = y[0] + y[1] + y[2] - 1.0;
    };
    Parts parts;
    parts.n = 3;
    parts.rows = {0, 1, 2, 0, 1, 2, 0, 1, 2};
    parts.cols = {0, 0, 0, 1, 1, 1, 2, 2, 2};
    parts.values = [](Vec& v, double, const Vec& y) {
        v[0] = -0.04;
        v[1] = 0.04;
        v[2] = 1.0;
        v[3] = 1e4 * y[2];
        v[4] = -1e4 * y[2] - 6e7 * y[1];
        v[5] = 1.0;
        v[6] = 1e4 * y[1];
        v[7] = -1e4 * y[1];
        v[8] = 1.0;
        return true;
    };
    p.parts = parts;
    return p;
}

Problem prob_decay3_nan(const Json& params) {
    Problem p = prob_decay3(params);
    const RhsFunction f0 = p.f;
    p.f = [f0](Vec& dy, double t, const Vec& y) {
        f0(dy, t, y);
        if (t > 5.0) dy[1] = std::numeric_limits<double>::quiet_NaN();
    };
    return p;
}

Problem prob_blowup(const Json&) {
    Problem p;
    p.f = [](Vec& dy, double t, const Vec&) { dy[0] = 1.0 / ((1.0 - t) * (1.0 - t)); };
    return p;
}

Problem problem_of(const std::string& name, const Json& params) {
    static const std::map<std::string, Problem (*)(const Json&)> problems = {
        {"robertson", prob_robertson}, {"vdp", prob_vdp},         {"decay3", prob_decay3},
        {"orego", prob_orego},         {"hires", prob_hires},     {"ball", prob_ball},
        {"nonneg", prob_nonneg},       {"chain", prob_chain},     {"landscape", prob_landscape},
        {"robertson_dae", prob_robertson_dae},                    {"decay3_nan", prob_decay3_nan},
        {"blowup", prob_blowup},
    };
    auto it = problems.find(name);
    if (it == problems.end()) throw std::runtime_error("no problem " + name);
    return it->second(params);
}

/// The JacobianSpec of a case: "none", "pattern" (differenced through it) or "exact".
std::optional<JacobianSpec> jacobian_of(const std::optional<Parts>& parts, const std::string& how) {
    if (how == "none" || !parts) return std::nullopt;
    Pattern pattern(parts->n, parts->rows, parts->cols);
    ColumnGroups groups = colour_columns(pattern);
    if (how == "pattern" || !parts->values) return JacobianSpec(pattern, groups, JacobianEvaluate(), false);
    if (how == "exact_nan" || how == "exact_nan0") {
        // Not a number in the third entry after t = 1 (from the start with "exact_nan0").
        const bool always = how == "exact_nan0";
        const JacobianEvaluate values = parts->values;
        JacobianEvaluate spoiled = [values, always](Vec& v, double t, const Vec& y) {
            values(v, t, y);
            if (always || t > 1.0) v[2] = std::numeric_limits<double>::quiet_NaN();
            return true;
        };
        return JacobianSpec(pattern, groups, spoiled, false);
    }
    return JacobianSpec(pattern, groups, parts->values, parts->constant);
}

// --- running a case as the fixture did ----------------------------------------------------------------

struct Progress {
    double fraction;
    long n;
    double t;
};

struct Run {
    std::vector<Solution> segments;         // one, or the segments of a restarted run
    std::optional<SolverError> error;
    Vec steps;
    std::vector<Progress> progress;
    Vec abstol;                             // the tolerances after the run, where they were a list
};

Run run_case(const Json& c) {
    Run run;
    Problem problem = problem_of(c.get("problem").as_string(), c.get("params"));
    const std::optional<JacobianSpec> jac = jacobian_of(problem.parts, c.get("jac").as_string());
    const Vec tspan = fvec(c.get("tspan"));
    const Vec y0 = fvec(c.get("y0"));
    const std::string solver = c.get("solver").as_string();
    const Json& opts = c.get("opts");
    const bool has_abstol_list = opts.get("abstol").is_array();
    if (has_abstol_list) run.abstol = fvec(opts.get("abstol"));
    Vec mass;
    if (opts.has("mass")) mass = fvec(opts.get("mass"));
    StepCallback on_accepted = [&run](double t, const Vec&) { run.steps.push_back(t); };

    NdfOptions no;
    SolverOptions so;
    for (const auto& [key, v] : opts.obj()) {
        if (key == "rtol") {
            no.rtol = num(v);
            so.rtol = num(v);
        } else if (key == "abstol") {
            if (has_abstol_list) {
                no.abstol_vector = &run.abstol;
                so.abstol_vector = &run.abstol;
            } else {
                no.abstol = num(v);
                so.abstol = num(v);
            }
        } else if (key == "bdf") {
            no.bdf = so.bdf = truthy(v);
        } else if (key == "max_order") {
            no.max_order = num(v);
            so.max_order = num(v);
        } else if (key == "error_norm") {
            no.error_norm = so.error_norm = v.as_string();
        } else if (key == "norm_control") {
            no.norm_control = so.norm_control = truthy(v);
        } else if (key == "auto_abstol") {
            no.auto_abstol = so.auto_abstol = truthy(v);
        } else if (key == "h0") {
            no.h0 = num(v);
            so.h0 = num(v);
        } else if (key == "hmax") {
            no.hmax = num(v);
            so.hmax = num(v);
        } else if (key == "hmin") {
            so.hmin = num(v);
        } else if (key == "max_steps") {
            no.max_steps = num(v);
            so.max_steps = num(v);
        } else if (key == "matrix") {
            no.matrix = so.matrix = v.as_string();
        } else if (key == "non_negative") {
            if (solver == "ndf") {
                no.non_negative = ivec(v);          // the states, counted from zero
            } else {
                for (const Json& flag : v.arr()) so.non_negative.push_back(truthy(flag) ? 1 : 0);
            }
        } else if (key == "ends_only") {
            no.ends_only = so.ends_only = truthy(v);
        } else if (key == "below_tol_run") {
            no.below_tol_run = num(v);
            so.below_tol_run = num(v);
        } else if (key == "stagnation_tol") {
            no.stagnation_tol = num(v);
            so.stagnation_tol = num(v);
        } else if (key == "mass") {
            no.mass = &mass;
        } else if (key == "on_step") {
            if (v.is_bool() && v.as_bool()) {
                so.on_step = [&run](double a, long n, double t) {
                    run.progress.push_back(Progress{a, n, t});
                    return true;
                };
            }
        } else {
            CHECK_MSG(false, "an option the test does not know: " + key);
        }
    }
    const JacobianSpec* jacobian = jac ? &*jac : nullptr;
    const EventFunctions* events = problem.events ? &*problem.events : nullptr;
    no.jacobian = jacobian;
    no.events = events;
    no.on_accepted = on_accepted;
    so.jacobian = jacobian;
    so.events = events;
    so.on_accepted = on_accepted;
    auto solve_span = [&](const Vec& span, const Vec& y) {
        if (solver == "ndf") return ndf(problem.f, span, y, no);
        return solve(solver == "variable_order" ? "ndf" : solver, problem.f, span, y, so);
    };
    try {
        const Json& restart = c.get("restart");
        if (restart.is_bool() && !restart.as_bool()) {
            run.segments.push_back(solve_span(tspan, y0));
        } else {
            double t = tspan[0];
            Vec y = y0;
            std::size_t nxt = 0;
            for (int round = 0; round < 12; round++) {
                while (nxt < tspan.size() && tspan[nxt] <= t) nxt += 1;
                if (nxt >= tspan.size()) break;
                Vec span{t};
                span.insert(span.end(), tspan.begin() + static_cast<std::ptrdiff_t>(nxt), tspan.end());
                run.segments.push_back(solve_span(span, y));
                const Solution& r = run.segments.back();
                if (!r.stopped) break;
                t = r.stopped->t;
                y = r.stopped->y;
                y[1] = -0.8 * y[1];
                if (restart == "floor") y[0] = 0.0;
            }
        }
    } catch (const SolverError& e) {
        run.error = e;
    }
    return run;
}

// --- comparing ----------------------------------------------------------------------------------------

const char* const STAT_KEYS[] = {"nsteps", "nfailed", "nfevals", "npds", "ndecomps", "nsolves", "nbelowtol", "negative"};

void compare_solution(const std::string& name, const Solution& sol, const Json& ref, bool exact, double rtol,
                      double atol, int stride) {
    const Json& rs = ref.get("stats");
    const Vec ref_t = fvec(ref.get("t"));
    const JArray& ref_y = ref.get("y").arr();
    CHECK_MSG(ref_t == sol.t, name + ": the output times");
    CHECK_MSG(sol.y.size() == ref_y.size(), name + ": the number of output rows");
    if (exact) {
        for (std::size_t i = 0; i < ref_y.size() && i < sol.y.size(); i++) {
            CHECK_MSG(bits_equal(fvec(ref_y[i]), sol.y[i]), name + ": output row " + std::to_string(i) + " differs");
        }
        for (const char* k : STAT_KEYS) {
            if (!rs.has(k)) continue;
            CHECK_MSG(rs.get(k) == sol.stats.get(k),
                      name + ": stats[" + k + "] is " + js_text(sol.stats.get(k)) + ", Python's " + js_text(rs.get(k)));
        }
        if (rs.has("held")) {
            CHECK_MSG(rs.get("held") == sol.stats.get("held"), name + ": stats[held]");
        }
        if (ref.has("end")) {
            CHECK_MSG(check::same_bits(num(ref.get("end").get("t")), sol.end_t), name + ": the end time");
            CHECK_MSG(bits_equal(fvec(ref.get("end").get("y")), sol.end_y), name + ": the end state");
        }
    } else {
        double worst = 0.0;
        for (std::size_t i = 0; i < ref_y.size() && i < sol.y.size(); i++) {
            const Vec r = fvec(ref_y[i]);
            const Vec& yj = sol.y[i];
            for (std::size_t j = 0; j < r.size(); j++) {
                const double mine = yj[j * static_cast<std::size_t>(stride)];
                const double scale = 10 * (rtol * std::max(std::fabs(r[j]), std::fabs(mine)) + atol);
                worst = worse(worst, std::fabs(r[j] - mine) / scale);
            }
        }
        CHECK_MSG(worst <= 1, name + ": outputs differ beyond 10x the tolerance (" + std::to_string(worst) + ")");
        for (const char* k : {"nsteps", "ndecomps"}) {
            const double want = rs.get(k).as_double();
            const double got = sol.stats.get(k).as_double();
            CHECK_MSG(std::fabs(want - got) <= 0.25 * want + 5,
                      name + ": stats[" + k + "] is " + js_text(got) + ", Python's " + js_text(want));
        }
    }
    const Json& st = ref.get("stopped");
    if (st.is_null()) {
        CHECK_MSG(!sol.stopped, name + ": stopped where Python did not");
    } else {
        CHECK_MSG(sol.stopped.has_value(), name + ": did not stop where Python did");
        if (sol.stopped) {
            CHECK_MSG(check::same_bits(num(st.get("t")), sol.stopped->t), name + ": the time it stopped at");
            CHECK_MSG(bits_equal(fvec(st.get("y")), sol.stopped->y), name + ": the state it stopped at");
            std::vector<int> which;
            for (const Json& w : st.get("which").arr()) which.push_back(static_cast<int>(w.as_int()));
            CHECK_MSG(which == sol.stopped->which, name + ": the events that stopped it");
        }
    }
}

void check_case(const Json& c) {
    const std::string name = c.get("name").as_string();
    const bool exact = c.get("exact").as_bool();
    Run run = run_case(c);
    const Json& opts = c.get("opts");
    const double rtol = opts.has("rtol") ? num(opts.get("rtol")) : 1e-3;
    double atol = 1e-6;
    if (opts.get("abstol").is_array()) {
        const Vec ab = fvec(opts.get("abstol"));
        atol = *std::max_element(ab.begin(), ab.end());
    } else if (opts.has("abstol")) {
        atol = num(opts.get("abstol"));
    }
    const Vec ref_steps = fvec(c.get("steps"));
    if (exact) {
        std::size_t part = 0;
        while (part < ref_steps.size() && part < run.steps.size() && check::same_bits(ref_steps[part], run.steps[part])) {
            part += 1;
        }
        const bool same = part == ref_steps.size() && part == run.steps.size();
        CHECK_MSG(same, name + ": the accepted steps part at step " + std::to_string(part) + " (Python took " +
                            std::to_string(ref_steps.size()) + ", this " + std::to_string(run.steps.size()) + ")");
    }
    if (c.has("error")) {
        const Json& e = c.get("error");
        CHECK_MSG(run.error.has_value(), name + ": did not fail where Python did");
        if (!run.error) return;
        CHECK_MSG(run.error->kind == e.get("kind").as_string(), name + ": the kind of failure is " + run.error->kind);
        CHECK_MSG(run.error->message == e.get("message").as_string(),
                  name + ": the messages differ:\n  Python: " + e.get("message").as_string() + "\n  this:   " +
                      run.error->message);
        CHECK_MSG(check::same_bits(num(e.get("t")), run.error->t), name + ": where it failed");
        if (!e.get("stats").is_null()) {
            for (const auto& [key, v] : e.get("stats").obj()) {
                CHECK_MSG(v == run.error->stats.get(key), name + ": the failure's stats[" + key + "]");
            }
            CHECK_MSG(check::same_bits(num(e.get("last_t")), run.error->last_t), name + ": the failure's last_t");
            const JArray& want = e.get("trace").arr();
            CHECK_MSG(want.size() == run.error->trace.size(), name + ": the length of the failure's trace");
            for (std::size_t i = 0; i < want.size() && i < run.error->trace.size(); i++) {
                const Json& a = want[i];
                const Json& b = run.error->trace[i];
                CHECK_MSG(check::same_bits(num(a.get("t")), b.get("t").as_double()) &&
                              check::same_bits(num(a.get("h")), b.get("h").as_double()) && a.get("k") == b.get("k") &&
                              check::same_bits(num(a.get("err")), b.get("err").as_double()) &&
                              a.get("newton") == b.get("newton") && a.get("failed") == b.get("failed"),
                          name + ": the failure's trace, step " + std::to_string(i));
            }
        } else {
            CHECK_MSG(run.error->stats.empty(), name + ": a failure with stats where Python's has none");
        }
        return;
    }
    if (run.error) {
        CHECK_MSG(false, name + ": failed where Python did not (" + run.error->kind + "): " + run.error->message);
        return;
    }
    const int stride = static_cast<int>(c.get("stride").as_int());
    const Json& restart = c.get("restart");
    if (!(restart.is_bool() && !restart.as_bool())) {
        const JArray& segs = c.get("segments").arr();
        CHECK_MSG(segs.size() == run.segments.size(), name + ": the number of segments");
        for (std::size_t i = 0; i < segs.size() && i < run.segments.size(); i++) {
            compare_solution(name + " segment " + std::to_string(i + 1), run.segments[i], segs[i], exact, rtol, atol,
                             stride);
        }
    } else {
        compare_solution(name, run.segments[0], c.get("result"), exact, rtol, atol, stride);
    }
    const JArray& progress = c.get("progress").arr();
    if (!progress.empty() || !run.progress.empty()) {
        CHECK_MSG(progress.size() == run.progress.size(), name + ": the number of progress calls");
        for (std::size_t i = 0; i < progress.size() && i < run.progress.size(); i++) {
            const Json& a = progress[i];
            const Progress& b = run.progress[i];
            CHECK_MSG(check::same_bits(num(a[0]), b.fraction) && a[1].as_int() == b.n &&
                          check::same_bits(num(a[2]), b.t),
                      name + ": progress call " + std::to_string(i));
        }
    }
    if (c.has("abstol_after")) {
        CHECK_MSG(bits_equal(fvec(c.get("abstol_after")), run.abstol), name + ": the tolerances raised");
    }
}

// --- the pieces against Python's ----------------------------------------------------------------------

void check_units(const Json& U) {
    // numbers in messages (Python's float repr)
    int bad = 0;
    for (const Json& pair : U.get("repr").arr()) {
        if ("repr:" + py_repr(num(pair[0])) != pair[1].as_string()) bad += 1;
    }
    CHECK_EQ(bad, 0);
    // ulp (the C library's log2 and pow)
    bad = 0;
    for (const Json& pair : U.get("ulp").arr()) {
        if (!check::same_bits(sv::ndf_ulp(num(pair[0])), num(pair[1]))) bad += 1;
    }
    CHECK_EQ(bad, 0);
    // colour_columns
    for (const Json& c : U.get("colour").arr()) {
        const Pattern p(static_cast<int>(c.get("n").as_int()), ivec(c.get("rows")), ivec(c.get("cols")));
        ColumnGroups want;
        for (const Json& g : c.get("groups").arr()) want.push_back(ivec(g));
        CHECK(colour_columns(p) == want);
    }
    // dense or sparse (IterationMatrix)
    for (const Json& c : U.get("decisions").arr()) {
        const int n = static_cast<int>(c.get("n").as_int());
        const Pattern p(n, ivec(c.get("rows")), ivec(c.get("cols")));
        // The values travel in the Python pattern's order, which is this pattern's.
        IterationMatrix W(n, &p, fvec(c.get("values")), c.get("mode").as_string());
        CHECK_EQ(W.sparse, c.get("sparse").as_bool());
        W.release();
    }
}

// --- aborted runs -------------------------------------------------------------------------------------

void check_aborted() {
    Problem problem = prob_robertson(Json());
    const std::optional<JacobianSpec> jac = jacobian_of(problem.parts, "exact");
    const Vec y0 = {1.0, 0.0, 0.0};
    const Vec tspan = {0.0, 4e6};
    // variable_order: asked every 64 evaluations, (fraction, n, t); false stops the run
    {
        int calls = 0;
        SolverOptions o;
        o.rtol = 1e-6;
        o.abstol = 1e-10;
        o.jacobian = &*jac;
        o.on_step = [&calls](double, long, double) {
            calls += 1;
            return calls < 3;
        };
        std::optional<SolverError> e;
        try {
            variable_order(problem.f, tspan, y0, o);
        } catch (const SolverError& err) {
            e = err;
        }
        CHECK(e && e->kind == "aborted" && e->message == "Simulation aborted");
        CHECK_EQ(calls, 3);
    }
    // the NDF's own on_step(t, nsteps): every 16 steps
    {
        std::vector<long> seen;
        NdfOptions o;
        o.rtol = 1e-6;
        o.abstol = 1e-10;
        o.jacobian = &*jac;
        o.on_step = [&seen](double, long n) {
            seen.push_back(n);
            return n < 32;
        };
        std::optional<SolverError> e;
        try {
            ndf(problem.f, tspan, y0, o);
        } catch (const SolverError& err) {
            e = err;
        }
        CHECK(e && e->kind == "aborted" && e->message == "Aborted");
        CHECK(seen == (std::vector<long>{16, 32}));
    }
    // the one-step methods: every 32 steps, (fraction, nsteps, t)
    for (const char* solver : {"ros23", "dp45"}) {
        std::vector<long> seen;
        SolverOptions o;
        o.rtol = 1e-4;
        o.abstol = 1e-8;
        o.jacobian = &*jac;
        o.on_step = [&seen](double, long n, double) {
            seen.push_back(n);
            return false;
        };
        std::optional<SolverError> e;
        try {
            solve(solver, problem.f, tspan, y0, o);
        } catch (const SolverError& err) {
            e = err;
        }
        CHECK(e && e->kind == "aborted" && e->message == "Simulation aborted");
        CHECK(seen == (std::vector<long>{32}));
    }
}

// --- a sparse matrix is the application's sparse LUs' -------------------------------------------------

void check_sparse() {
    Problem problem = prob_landscape(parse_json("{\"nb\": 20}"));
    const std::optional<JacobianSpec> jac = jacobian_of(problem.parts, "exact");
    const char* const cases[3][2] = {{"sparse", "sparse"}, {"refactor", "refactor"}, {"auto", "refactor"}};
    for (const auto& pair : cases) {
        NdfOptions o;
        o.rtol = 1e-6;
        o.abstol = 1e-12;
        o.jacobian = &*jac;
        o.matrix = pair[0];
        const Solution sol = ndf(problem.f, {0.0, 1.0, 100.0}, Vec(200, 0.0), o);
        CHECK(sol.stats.get("sparse") == Json(true) && sol.stats.get("lu") == pair[1]);
        bool finite = true;
        for (double v : sol.y.back()) finite &= std::isfinite(v);
        CHECK(finite);
    }
}

// --- what the fixtures do not reach --------------------------------------------------------------------

void check_extras() {
    Problem problem = prob_robertson(Json());
    const std::optional<JacobianSpec> jac = jacobian_of(problem.parts, "exact");
    const Vec y0 = {1.0, 0.0, 0.0};
    const Vec tspan = {0.0, 0.4, 4.0, 40.0};
    NdfOptions base;
    base.rtol = 1e-6;
    base.abstol = 1e-10;
    base.jacobian = &*jac;
    const Solution plain = ndf(problem.f, tspan, y0, base);
    auto same_rows = [](const Solution& a, const Solution& b) {
        if (a.t != b.t || a.y.size() != b.y.size()) return false;
        for (std::size_t i = 0; i < a.y.size(); i++)
            if (!bits_equal(a.y[i], b.y[i])) return false;
        return bits_equal(a.end_y, b.end_y);
    };
    // Rows from a pool: the same numbers, in the pool's rows, which the next run uses again.
    {
        RowPool pool;
        NdfOptions o = base;
        o.rows = &pool;
        const Solution first = ndf(problem.f, tspan, y0, o);
        CHECK(same_rows(plain, first));
        CHECK_EQ(pool.rows.size(), tspan.size());
        CHECK(&first.y[0] == pool.rows[0].get());
        reset_rows(pool);
        const Solution second = ndf(problem.f, tspan, y0, o);
        CHECK(same_rows(plain, second));
        CHECK_EQ(pool.rows.size(), tspan.size());
        CHECK(&second.y[2] == pool.rows[2].get());
        const Solution copy = second;               // a copy's rows are its own
        CHECK(same_rows(plain, copy) && &copy.y[0] != pool.rows[0].get());
    }
    // A matrix of the caller's making: the solver's own, made by the caller, gives the same run.
    {
        NdfOptions o = base;
        int made = 0;
        o.iteration_matrix = [&made](int n, const Pattern* pattern, const Vec& J, const std::string& matrix,
                                     const Vec* mass, const Hints* hints) {
            made += 1;
            return std::unique_ptr<AbstractIterationMatrix>(new IterationMatrix(n, pattern, J, matrix, mass, hints));
        };
        CHECK(same_rows(plain, ndf(problem.f, tspan, y0, o)));
        CHECK_EQ(made, 1);
    }
    // A landing: a step that would pass over the time ends on it instead, in every solver.
    {
        const double at = 0.37;
        const StepLanding landing = [at](double t, double t_next) {
            return (t < at && t_next > at) ? at : std::numeric_limits<double>::quiet_NaN();
        };
        Vec steps;
        const StepCallback on_accepted = [&steps](double t, const Vec&) { steps.push_back(t); };
        NdfOptions o = base;
        o.landing = landing;
        o.on_accepted = on_accepted;
        ndf(problem.f, tspan, y0, o);
        CHECK(std::find(steps.begin(), steps.end(), at) != steps.end());
        for (const char* solver : {"ndf", "ros23", "dp45"}) {
            steps.clear();
            SolverOptions so;
            so.rtol = 1e-4;
            so.abstol = 1e-8;
            so.jacobian = &*jac;
            so.landing = landing;
            so.on_accepted = on_accepted;
            solve(solver, problem.f, {0.0, 0.2, 1.0}, y0, so);
            CHECK(std::find(steps.begin(), steps.end(), at) != steps.end());
            CHECK(std::is_sorted(steps.begin(), steps.end()));
        }
    }
    // States weighed against another's size: checked, and no state floored is the plain run.
    {
        WeightFloor none{{-1, -1, -1}, {0, 0, 0}};
        NdfOptions o = base;
        o.weight_floor = &none;
        CHECK(same_rows(plain, ndf(problem.f, tspan, y0, o)));
        WeightFloor some{{-1, 0, -1}, {0, 1e-3, 0}};
        o.weight_floor = &some;
        const Solution floored = ndf(problem.f, tspan, y0, o);
        CHECK(floored.t == plain.t && std::fabs(floored.end_y[0] - plain.end_y[0]) < 1e-3);
        CHECK(floored.stats.get("nsteps").as_int() <= plain.stats.get("nsteps").as_int());
        auto message_of = [&](const WeightFloor& wf) {
            NdfOptions bad = base;
            bad.weight_floor = &wf;
            try {
                ndf(problem.f, tspan, y0, bad);
            } catch (const SolverError& e) {
                return e.kind + ": " + e.message;
            }
            return std::string("no failure");
        };
        CHECK_EQ(message_of(WeightFloor{{-1, -1}, {0, 0}}),
                 "weightFloor: weightFloor needs a from and a factor for each of the 3 equations");
        CHECK_EQ(message_of(WeightFloor{{-1, 7, -1}, {0, 1, 0}}),
                 "weightFloor: weightFloor's entry 1 is not a state and a factor: 7, 1");
        CHECK_EQ(message_of(WeightFloor{{-1, 0.5, -1}, {0, 1, 0}}),
                 "weightFloor: weightFloor's entry 1 is not a state and a factor: 0.5, 1");
        CHECK_EQ(message_of(WeightFloor{{0, -1, -1}, {-2, 0, 0}}),
                 "weightFloor: weightFloor's entry 0 is not a state and a factor: 0, -2");
    }
    // What a matrix that cannot be factorised says, with parity on and off.
    for (bool exact : {true, false}) {
        const bool was = parity();
        set_parity(exact);
        const Hints hints{{"singular", "A compartment with no way in and no way out will do this."}};
        const Pattern p(2, {0, 1, 0, 1}, {0, 0, 1, 1});
        {
            IterationMatrix W(2, &p, {2.0, 0.0, 0.0, 1.0}, "auto", nullptr, &hints);
            const std::optional<std::string> msg = W.form(0.5, {2.0, 0.0, 0.0, 1.0});
            CHECK(msg && *msg == "The iteration matrix I - h*J is singular at column 0. A compartment with no way "
                                 "in and no way out will do this.");
            CHECK(!W.form(0.25, {2.0, 0.0, 0.0, 1.0}));
            Vec x(2), b = {1.0, 3.0};
            W.solve(x, b);
            CHECK(x[0] == 2.0 && x[1] == 4.0);
            W.solve_inplace(b);
            CHECK(b == x);
        }
        {
            const Vec mass = {1.0, 0.0};
            IterationMatrix W(2, &p, {1.0, 0.0, 0.0, 0.0}, "auto", &mass, &hints);
            const std::optional<std::string> msg = W.form(0.5, {1.0, 0.0, 0.0, 0.0});
            CHECK(msg && *msg == "The iteration matrix M - h*J is singular at the algebraic variable in column 1: "
                                 "its constraint does not determine it. Check that the constraint depends on its "
                                 "own variable, that no two constraints say the same thing, and that the system is "
                                 "index 1.");
            const std::optional<std::string> inf = W.form(0.5, {1.0, 0.0, std::numeric_limits<double>::infinity(), 1.0});
            CHECK(inf && *inf == "The iteration matrix M - h*J has an entry that is not a number (-inf) at column 1: "
                                 "the Jacobian has a non-finite entry there.");
        }
        {
            // Without a pattern the Jacobian is dense, by columns; a held row is a row of the identity.
            IterationMatrix W(2, nullptr, {0.0, 0.0, 0.0, 0.0});
            const std::vector<std::uint8_t> held = {0, 1};
            CHECK(!W.form(0.5, {-2.0, 8.0, 0.0, -4.0}, &held));
            Vec x = {4.0, 5.0};
            W.solve_inplace(x);
            CHECK(x[0] == 2.0 && x[1] == 5.0);
        }
        set_parity(was);
    }
}

// --- the quick way (parity off) -----------------------------------------------------------------------
//
// With parity off a run takes the same solver its quickest way: the engine's own dense LU with
// fused multiply-adds, one Newton iteration where the Jacobian is exact and constant. The numbers
// are then not Python's to the bit, but the same answer to the run's tolerance.

void check_fast(const Json& cases) {
    for (const Json& c : cases.arr()) {
        const std::string name = c.get("name").as_string();
        if (c.has("error") || c.has("segments") || !c.has("result")) continue;
        if (c.get("problem") == "vdp" || c.get("problem") == "orego") continue;    // relaxation oscillators: a
                                                                                   // late switch is not an error
        const Json& opts = c.get("opts");
        if (opts.has("on_step")) continue;
        Run run = run_case(c);
        CHECK_MSG(!run.error, name + " (parity off): failed");
        if (run.error) continue;
        const Solution& sol = run.segments[0];
        const Json& ref = c.get("result");
        const double rtol = opts.has("rtol") ? num(opts.get("rtol")) : 1e-3;
        double atol = 1e-6;
        if (opts.get("abstol").is_array()) {
            const Vec ab = fvec(opts.get("abstol"));
            atol = *std::max_element(ab.begin(), ab.end());
        } else if (opts.has("abstol")) {
            atol = num(opts.get("abstol"));
        }
        const std::size_t stride = static_cast<std::size_t>(c.get("stride").as_int());
        const JArray& ref_y = ref.get("y").arr();
        CHECK_MSG(fvec(ref.get("t")) == sol.t, name + " (parity off): the output times");
        double worst = 0.0;
        for (std::size_t i = 0; i < ref_y.size() && i < sol.y.size(); i++) {
            const Vec r = fvec(ref_y[i]);
            for (std::size_t j = 0; j < r.size(); j++) {
                const double mine = sol.y[i][j * stride];
                const double scale = 100 * (rtol * std::max(std::fabs(r[j]), std::fabs(mine)) + atol);
                worst = worse(worst, std::fabs(r[j] - mine) / scale);
            }
        }
        CHECK_MSG(worst <= 1, name + " (parity off): outputs differ beyond 100x the tolerance (" +
                                  std::to_string(worst) + ")");
    }
}

}  // namespace

int main() {
    // Checked against the Python package's solvers step by step: parity on.
    set_parity(true);
    const Json doc = parse_json(check::read_file(KOMPARTMENT_REPO "/julia/test/solvers/fixtures.json"));
    CHECK(doc.get("numba") == Json(true));          // the Python runs used the application's dense LU
    for (const Json& c : doc.get("cases").arr()) {
        try {
            check_case(c);
        } catch (const std::exception& e) {
            CHECK_MSG(false, c.get("name").as_string() + ": " + e.what());
        }
    }
    check_units(doc.get("units"));
    check_aborted();
    check_sparse();
    check_extras();
    set_parity(false);
    check_fast(doc.get("cases"));
    check_aborted();
    check_sparse();
    check_extras();
    return check::summary("test_solvers");
}
