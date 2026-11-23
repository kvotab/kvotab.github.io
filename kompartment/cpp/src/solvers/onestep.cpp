#include "solvers/onestep.hpp"

#include <algorithm>
#include <cmath>
#include <memory>
#include <stdexcept>
#include <utility>

#include "solvers/kernels.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

using sv::jl_max;
using sv::py_max;
using sv::py_min;

constexpr double OS_EPS = 0x1p-52;
constexpr long OS_STALL_WINDOW_STEPS = 2000;
constexpr double OS_STALL_SPAN_FRACTION = 1e-9;
constexpr int OS_MAX_AT_FLOOR = 20;
constexpr double OS_SAFETY = 0.9;
constexpr double OS_SHRINK_LEAST = 0.1;
constexpr double OS_GROW_MOST = 5.0;

SolverError non_finite_error(double t, int index) {
    return SolverError("nonfinite",
                       "The state or its derivative became non-finite at t=" + py_repr(t) + " (state " +
                           std::to_string(index) +
                           "). Check for division by zero, a negative base raised to a fractional power, or an "
                           "initial value that is not a number.",
                       t);
}

inline double os_step_floor(double t) { return (16 * OS_EPS) * std::fabs(t); }

/// The derivative with a constrained state at zero held there
/// (`HeldDerivative`), or the derivative as it is (`hold` false).
struct OsRhs {
    const RhsFunction* f;
    bool hold;
    std::vector<I32> idx;
    Vec push;
};

inline void os_rhs(OsRhs& r, Vec& out, double t, const Vec& y) {
    (*r.f)(out, t, y);
    if (!r.hold) return;
    const std::vector<I32>& idx = r.idx;
    if (idx.empty()) return;
    if (sv::all_above_zero(y, idx)) return;
    Vec& push = r.push;
    for (I32 i : idx) {
        if ((y[i] <= 0) && (out[i] < 0)) {
            push[i] = jl_max(push[i], -out[i]);
            out[i] = 0.0;
        }
    }
}

// --- Rosenbrock (2,3) ---------------------------------------------------------------------------------

const char* const ROS_SINGULAR_HINT = "A compartment with no way in and no way out will do this.";
const double ROS_D = 1 / (2 + std::sqrt(2.0));
const double ROS_E32 = 6 + std::sqrt(2.0);
constexpr double ROS_SQRT_EPS = 0x1p-26;       // sqrt(2^-52)

struct Ros23 {
    int neq;
    OsRhs* rhs;
    const Vec* threshold;
    const Pattern* pattern = nullptr;
    const ColumnGroups* groups = nullptr;
    ColumnGroups own_groups;
    const JacobianEvaluate* evaluate = nullptr;
    bool constant = false;
    DifferenceWork dwork;
    Vec J;
    std::unique_ptr<IterationMatrix> W;
    Vec f0, ft;
    long long npds = 0;
    long long ndecomps = 0;
    long long spent = 0;
    bool need_jacobian = true;
    double dfdt_at = sv::NOT_A_NUMBER;
    Vec k1, k2, k3, f1, f2, tmp, ymid;
    double t_from = 0.0;
    double h_from = 0.0;
    Vec y_from;

    Ros23(int neq_, OsRhs* rhs_, const Vec* threshold_, const JacobianSpec* jac)
        : neq(neq_), rhs(rhs_), threshold(threshold_) {
        const std::size_t N = static_cast<std::size_t>(neq);
        if (jac != nullptr) {
            if (jac->pattern) pattern = &*jac->pattern;
            if (jac->groups) groups = &*jac->groups;
            if (jac->evaluate) evaluate = &jac->evaluate;
            constant = jac->constant;
        }
        if (pattern != nullptr && groups == nullptr) {
            own_groups = colour_columns(*pattern);
            groups = &own_groups;
        }
        dwork = DifferenceWork(pattern, groups, neq);
        J.assign(pattern != nullptr ? pattern->nnz() : N * N, 0.0);
        for (Vec* v : {&f0, &ft, &k1, &k2, &k3, &f1, &f2, &tmp, &ymid, &y_from}) v->assign(N, 0.0);
    }

    static const char* id() { return "ros23"; }
    static int order() { return 2; }
    static double default_max_steps() { return 1e6; }
    static bool snaps_to_constraint() { return true; }

    static std::string step_budget_message(double max_steps, double t) {
        return "Exceeded " + std::to_string(static_cast<long long>(max_steps)) + " steps at t=" + py_repr(t) + ".";
    }

    static std::string floor_message(double t, double hmin, int /*worst*/) {
        return "Unable to meet integration tolerances at t=" + py_repr(t) +
               " without reducing the step below the smallest allowed (" + py_repr(hmin) + ").";
    }

    static std::string stall_message(double t, long window, double covered, bool floor) {
        return "The solver stopped making progress at t=" + py_repr(t) + ": " + std::to_string(window) +
               " steps advanced the clock by less than " + py_repr(covered) +
               ", and the step size is no longer growing. " +
               (floor ? "A state is reaching zero while its equations push it below, and a constraint that binds is "
                        "not one a one-step method can carry: use the stiff NDF solver, or turn \"cannot go "
                        "negative\" off on the compartment to see what the model really does."
                      : "A rate is changing faster than the step size can follow -- a switch the model does not "
                        "declare, or a tolerance tighter than this low-order method can keep up with: declare its "
                        "switch times, loosen the tolerance, or use the stiff NDF solver.");
    }

    void jacobian(double t, const Vec& y) {
        if (evaluate != nullptr && (*evaluate)(J, t, y)) return;
        OsRhs& r = *rhs;
        if (pattern != nullptr) {
            spent += static_cast<long long>(groups->size());
            difference_jacobian(J, [&r](Vec& o, double tt, const Vec& yy) { os_rhs(r, o, tt, yy); }, t, y, f0,
                                *pattern, *groups, *threshold, dwork);
            return;
        }
        const int n = neq;
        difference_increment(dwork.dl, y, *threshold);
        const Vec& dl = dwork.dl;
        Vec& ytry = dwork.ytry;
        Vec& fg = dwork.fg;
        ytry = y;
        for (int j = 0; j < n; j++) {
            ytry[j] = y[j] + dl[j];
            os_rhs(r, fg, t, ytry);
            const std::size_t off = static_cast<std::size_t>(j) * n;
            for (int i = 0; i < n; i++) J[off + i] = (fg[i] - f0[i]) / dl[j];
            ytry[j] = y[j];
        }
        spent += n;
    }

    long long start(double t, const Vec& y) {
        os_rhs(*rhs, f0, t, y);
        jacobian(t, y);
        npds += 1;
        need_jacobian = false;
        const Hints hints{{"singular", ROS_SINGULAR_HINT}};
        // A matrix that cannot be made (too large to hold without a pattern) is the caller's to hear of as it is.
        W = std::make_unique<IterationMatrix>(neq, pattern, J, "auto", nullptr, &hints);
        return 1;
    }

    const Vec& derivative_at_start() const { return f0; }

    std::pair<long long, double> attempt(double t, const Vec& y_, double h, double tnew, Vec& ynew_, Vec& err_) {
        const long long before = spent;
        if (need_jacobian && !(constant && npds > 0)) {
            jacobian(t, y_);
            npds += 1;
        }
        need_jacobian = false;
        const int n = neq;
        if (dfdt_at != t) {
            const double dt = std::copysign(py_min(ROS_SQRT_EPS * py_max(std::fabs(t), std::fabs(t + h)), std::fabs(h)), h);
            os_rhs(*rhs, f1, t + dt, y_);
            spent += 1;
            for (int i = 0; i < n; i++) ft[i] = (f1[i] - f0[i]) / dt;
            dfdt_at = t;
        }
        std::optional<std::string> msg = W->form(h * ROS_D, J);
        if (msg) throw SolverError("singular", *msg + " (at t=" + py_repr(t) + ")", t);
        ndecomps += 1;
        const double hD = h * ROS_D;
        const double half_h = 0.5 * h;
        const double* y = y_.data();
        double* ynew = ynew_.data();
        double* err = err_.data();
        {
            const double* pf0 = f0.data();
            const double* pft = ft.data();
            double* ptmp = tmp.data();
            for (int i = 0; i < n; i++) ptmp[i] = pf0[i] + hD * pft[i];
        }
        W->solve(k1, tmp);
        for (int i = 0; i < n; i++) ymid[i] = y[i] + half_h * k1[i];
        os_rhs(*rhs, f1, t + 0.5 * h, ymid);
        for (int i = 0; i < n; i++) tmp[i] = f1[i] - k1[i];
        W->solve(k2, tmp);
        for (int i = 0; i < n; i++) k2[i] += k1[i];
        for (int i = 0; i < n; i++) ynew[i] = y[i] + h * k2[i];
        os_rhs(*rhs, f2, tnew, ynew_);
        for (int i = 0; i < n; i++) tmp[i] = f2[i] - ROS_E32 * (k2[i] - f1[i]) - 2 * (k1[i] - f0[i]) + hD * ft[i];
        W->solve(k3, tmp);
        spent += 2;
        for (int i = 0; i < n; i++) err[i] = k1[i] - 2 * k2[i] + k3[i];
        t_from = t;
        h_from = h;
        y_from = y_;
        return {spent - before, 1.0 / 6};
    }

    void dense_at(Vec& out, double tq) const {
        const double s = (tq - t_from) / h_from;
        const double a1 = s * h_from;
        const double a2 = (s * s) * h_from;
        const std::size_t n = out.size();
        for (std::size_t i = 0; i < n; i++) out[i] = (y_from[i] + a1 * f0[i]) + a2 * (k2[i] - f0[i]);
    }

    long long accept(double tnew, const Vec& ynew, bool reprojected) {
        long long used = 0;
        if (reprojected) {
            os_rhs(*rhs, f2, tnew, ynew);
            used = 1;
        }
        f0 = f2;
        need_jacobian = true;
        dfdt_at = sv::NOT_A_NUMBER;
        return used;
    }

    long long restart(double t, const Vec& y) {
        os_rhs(*rhs, f0, t, y);
        need_jacobian = true;
        dfdt_at = sv::NOT_A_NUMBER;
        return 1;
    }

    void stats(Json& out) {
        out.set("npds", Json(npds));
        out.set("ndecomps", Json(ndecomps));
        out.set("sparse", Json(W->sparse));
        out.set("fill", W->info_as_made().get("fill"));
        W->release();
    }
};

// --- Dormand-Prince (4,5) -----------------------------------------------------------------------------

constexpr double DP_NODES[6] = {1.0 / 5, 3.0 / 10, 4.0 / 5, 8.0 / 9, 1.0, 1.0};
constexpr double DP_STAGE[6][6] = {
    {1.0 / 5, 0, 0, 0, 0, 0},
    {3.0 / 40, 9.0 / 40, 0, 0, 0, 0},
    {44.0 / 45, -56.0 / 15, 32.0 / 9, 0, 0, 0},
    {19372.0 / 6561, -25360.0 / 2187, 64448.0 / 6561, -212.0 / 729, 0, 0},
    {9017.0 / 3168, -355.0 / 33, 46732.0 / 5247, 49.0 / 176, -5103.0 / 18656, 0},
    {35.0 / 384, 0.0, 500.0 / 1113, 125.0 / 192, -2187.0 / 6784, 11.0 / 84},
};
constexpr double DP_ERROR[7] = {71.0 / 57600, 0.0, -71.0 / 16695, 71.0 / 1920, -17253.0 / 339200, 22.0 / 525, -1.0 / 40};
constexpr double DP_DENSE[7][4] = {
    {1.0, -183.0 / 64, 37.0 / 12, -145.0 / 128},
    {0.0, 0.0, 0.0, 0.0},
    {0.0, 1500.0 / 371, -1000.0 / 159, 1000.0 / 371},
    {0.0, -125.0 / 32, 125.0 / 12, -375.0 / 64},
    {0.0, 9477.0 / 3392, -729.0 / 106, 25515.0 / 6784},
    {0.0, -11.0 / 7, 11.0 / 3, -55.0 / 28},
    {0.0, 3.0 / 2, -4.0, 5.0 / 2},
};

struct DP45 {
    int neq;
    OsRhs* rhs;
    Vec k[7];
    Vec acc;
    Vec ystage;
    double t_from = 0.0;
    double h_from = 0.0;
    Vec y_from;

    DP45(int neq_, OsRhs* rhs_) : neq(neq_), rhs(rhs_) {
        const std::size_t N = static_cast<std::size_t>(neq);
        for (Vec& v : k) v.assign(N, 0.0);
        acc.assign(N, 0.0);
        ystage.assign(N, 0.0);
        y_from.assign(N, 0.0);
    }

    static const char* id() { return "dp45"; }
    static int order() { return 4; }
    static double default_max_steps() { return 1e7; }
    static bool snaps_to_constraint() { return false; }

    static std::string step_budget_message(double max_steps, double t) {
        return "Exceeded " + std::to_string(static_cast<long long>(max_steps)) + " steps at t=" + py_repr(t) +
               "; the system may be stiff -- try a stiff solver (NDF, or Rosenbrock 2-3).";
    }

    static std::string floor_message(double t, double hmin, int worst) {
        return "Unable to meet integration tolerances at t=" + py_repr(t) +
               " without reducing the step below the smallest allowed (" + py_repr(hmin) + "). State " +
               std::to_string(worst) +
               " is the worst offender; the system is probably stiff -- try a stiff solver (NDF, or Rosenbrock 2-3).";
    }

    static std::string stall_message(double t, long window, double covered, bool floor) {
        return "The solver stopped making progress at t=" + py_repr(t) + ": " + std::to_string(window) +
               " steps advanced the clock by less than " + py_repr(covered) +
               ", and the step size is no longer growing. " +
               (floor ? "A state is being held against zero, which this explicit method cannot carry: use the stiff "
                        "NDF solver, or turn \"cannot go negative\" off on the compartment to see what the model "
                        "really does."
                      : "The system is stiff -- try a stiff solver (NDF, or Rosenbrock 2-3).");
    }

    /// `y + h * sum(c_j k_j)` over the non-zero coefficients (`_combine`).
    void combine(Vec& out_, const Vec& y_, double h, const double* row, int count) {
        const int n = neq;
        double* a = acc.data();
        for (int i = 0; i < n; i++) a[i] = 0.0;
        for (int j = 0; j < count; j++) {
            const double c = row[j];
            if (!(c != 0)) continue;
            const double* kj = k[j].data();
            for (int i = 0; i < n; i++) a[i] = a[i] + c * kj[i];
        }
        double* out = out_.data();
        const double* y = y_.data();
        for (int i = 0; i < n; i++) out[i] = y[i] + h * a[i];
    }

    long long start(double t, const Vec& y) {
        os_rhs(*rhs, k[0], t, y);
        return 1;
    }

    const Vec& derivative_at_start() const { return k[0]; }

    std::pair<long long, double> attempt(double t, const Vec& y, double h, double tnew, Vec& ynew, Vec& err_) {
        // The stages one by one: each row of coefficients has its own length.
        Vec& ys = ystage;
        for (int stage = 0; stage < 5; stage++) {
            combine(ys, y, h, DP_STAGE[stage], stage + 1);
            os_rhs(*rhs, k[stage + 1], t + h * DP_NODES[stage], ys);
        }
        combine(ynew, y, h, DP_STAGE[5], 6);
        os_rhs(*rhs, k[6], tnew, ynew);
        const int n = neq;
        double* err = err_.data();
        for (int i = 0; i < n; i++) err[i] = 0.0;
        for (int j = 0; j < 7; j++) {
            const double c = DP_ERROR[j];
            if (!(c != 0)) continue;
            const double* kj = k[j].data();
            for (int i = 0; i < n; i++) err[i] = err[i] + c * kj[i];
        }
        t_from = t;
        h_from = h;
        y_from = y;
        return {6, 1.0};
    }

    void dense_at(Vec& out_, double tq) {
        const double s = (tq - t_from) / h_from;
        const double s2 = s * s;
        const double s3 = s2 * s;
        const double s4 = s3 * s;
        const int n = neq;
        double* a = acc.data();
        for (int i = 0; i < n; i++) a[i] = 0.0;
        for (int j = 0; j < 7; j++) {
            const double* c = DP_DENSE[j];
            const double w = c[0] * s + c[1] * s2 + c[2] * s3 + c[3] * s4;
            if (!(w != 0)) continue;
            const double* kj = k[j].data();
            for (int i = 0; i < n; i++) a[i] = a[i] + w * kj[i];
        }
        const double h = h_from;
        double* out = out_.data();
        const double* yf = y_from.data();
        for (int i = 0; i < n; i++) out[i] = yf[i] + h * a[i];
    }

    long long accept(double tnew, const Vec& ynew, bool reprojected) {
        long long used = 0;
        if (reprojected) {
            os_rhs(*rhs, k[6], tnew, ynew);
            used = 1;
        }
        k[0] = k[6];
        return used;
    }

    long long restart(double /*t*/, const Vec& /*y*/) { return 0; }
    void stats(Json& /*out*/) {}
};

// --- the driver ---------------------------------------------------------------------------------------

template <class S>
Solution os_run(S& st, OsRhs& rhs, const Vec& tspan, const Vec& y0, double rtol, const Vec& atol, const Vec& threshold,
                const std::vector<std::uint8_t>* mask, double max_steps, double hmax, double hmin_opt,
                long stall_window, double h0, const EventFunctions* events, const StepCallback& on_output,
                const StepCallback& on_accepted, const RunProgress& on_step, const StepLanding& landing) {
    const int neq = static_cast<int>(y0.size());
    const std::size_t N = y0.size();
    const std::size_t npts = tspan.size();
    const double t0 = tspan.front();
    const double t_end = tspan.back();
    const double direction = t_end > t0 ? 1.0 : -1.0;
    const double span = std::fabs(t_end - t0);
    const double stall_span = OS_STALL_SPAN_FRACTION * span;
    const double exponent = 1.0 / (S::order() + 1);
    std::vector<I32> nn_idx;
    if (mask != nullptr) {
        for (int i = 0; i < neq; i++)
            if ((*mask)[i] != 0) nn_idx.push_back(i);
    }
    const bool has_nn = mask != nullptr;
    Solution sol;
    Vec& tout = sol.t;
    Rows& yout = sol.y;

    double t = t0;
    Vec y = y0;
    tout.push_back(t0);
    yout.push_copy(y);
    std::size_t next_out = 1;
    long long nsteps = 0;
    long long nfailed = 0;
    long long nbelowtol = 0;
    long long negative = 0;
    long long nfevals = 0;
    std::vector<long long> held;
    if (rhs.hold) held.assign(N, 0);
    Vec vl;
    Vec vr;
    sv::EventWork event_work;
    if (events != nullptr) {
        vl.assign(static_cast<std::size_t>(events->n), 0.0);
        events->fun(vl, t0, y);
        vr.assign(static_cast<std::size_t>(events->n), 0.0);
        event_work = sv::EventWork(events->n);
    }
    nfevals += st.start(t, y);

    Vec ynew(N, 0.0);
    Vec err_vec(N, 0.0);
    Vec dense(N, 0.0);
    Vec evbuf(N, 0.0);
    double step_size;
    if (h0 > 0) {
        step_size = h0;
    } else {
        const Vec& f0 = st.derivative_at_start();
        const double d0 = sv::weighted_norm(y, y, y, threshold).first / rtol;
        const double d1 = sv::weighted_norm(f0, y, y, threshold).first / rtol;
        double guess = (d0 < 1e-5 || d1 < 1e-5) ? 1e-6 : 0.01 * (d0 / d1);
        guess = py_min(guess, hmax);
        Vec trial(N, 0.0);
        const double dg = direction * guess;
        for (int i = 0; i < neq; i++) trial[i] = y[i] + dg * f0[i];
        Vec ftry(N, 0.0);
        os_rhs(rhs, ftry, t0 + direction * guess, trial);
        nfevals += 1;
        for (int i = 0; i < neq; i++) ftry[i] = ftry[i] - f0[i];
        double d2 = sv::weighted_norm(ftry, y, y, threshold).first / rtol / guess;
        if (!std::isfinite(d2)) d2 = 100 * d1;
        const double m = py_max(d1, d2);
        const double h1 = m <= 1e-15 ? py_max(1e-6, guess * 1e-3) : std::pow(0.01 / m, exponent);
        step_size = py_min(100 * guess, h1);
    }
    step_size = py_min(hmax, py_max(py_max(os_step_floor(t0), hmin_opt), step_size));
    int at_floor = 0;
    long long stall_step = 0;
    double stall_t = t0;
    double stall_h = 0.0;
    long long floor_in_window = 0;
    double tnew = t;
    auto dense_at = [&st, &nn_idx, has_nn](Vec& out, double tq) {
        st.dense_at(out, tq);
        if (has_nn) {
            for (I32 i : nn_idx) {
                const double v = out[i];
                out[i] = v < 0 ? 0.0 : v;
            }
        }
    };
    for (;;) {
        if (static_cast<double>(nsteps) > max_steps) throw SolverError("steps", S::step_budget_message(max_steps, t), t);
        const double hmin = py_max(os_step_floor(t), hmin_opt);
        step_size = py_min(hmax, py_max(hmin, step_size));
        double h = direction * step_size;
        bool last = false;
        if (1.1 * step_size >= std::fabs(t_end - t)) {
            h = t_end - t;
            step_size = std::fabs(h);
            last = true;
        }
        // A step that would pass over a pulse in a table ends on it instead:
        // f is never looked at between two steps.
        if (landing) {
            const double at = landing(t, t + h);
            if (direction * (at - t) > 0 && direction * (t + h - at) > 0) {
                h = at - t;
                step_size = std::fabs(h);
                last = false;
            }
        }
        double err = 0.0;
        int worst_at = 0;
        bool failed_once = false;
        bool restart = false;
        tnew = t;
        for (;;) {
            tnew = last ? t_end : t + h;
            h = tnew - t;
            const std::pair<long long, double> spent = st.attempt(t, y, h, tnew, ynew, err_vec);
            nfevals += spent.first;
            const double scale = spent.second;
            const std::pair<double, int> worst = sv::weighted_norm(err_vec, y, ynew, threshold);
            worst_at = worst.second;
            err = (worst.first * step_size) * scale;
            if (!std::isfinite(err)) {
                nfailed += 1;
                if (step_size <= hmin) throw non_finite_error(t, worst_at);
                failed_once = true;
                step_size = py_max(hmin, 0.1 * step_size);
                h = direction * step_size;
                last = false;
                continue;
            }
            bool for_constraint = false;
            if (has_nn && err <= rtol && sv::any_below_zero(ynew, nn_idx)) {
                double best = 0.0;
                int at = 0;
                for (int i = 0; i < neq; i++) {
                    const double v = (((*mask)[i] != 0) && (ynew[i] < 0)) ? -ynew[i] / threshold[i] : 0.0;
                    if (i == 0) {
                        best = v;
                        at = 0;
                    } else if (!std::isnan(best) && (std::isnan(v) || v > best)) {
                        best = v;
                        at = i;
                    }
                }
                if (best > 0 && best > rtol) {
                    err = best;
                    worst_at = at;
                    for_constraint = true;
                }
            }
            if (err <= rtol) {
                at_floor = 0;
                break;
            }
            nfailed += 1;
            if (for_constraint) floor_in_window += 1;
            if (for_constraint && S::snaps_to_constraint()) {
                bool any_snap = false;
                for (I32 i : nn_idx) {
                    if ((ynew[i] < 0) && (y[i] > 0) && (y[i] <= atol[i])) {
                        y[i] = 0.0;
                        any_snap = true;
                    }
                }
                if (any_snap) {
                    nfevals += st.restart(t, y);
                    restart = true;
                    break;
                }
            }
            const double before = step_size;
            if (for_constraint || failed_once) {
                step_size = py_max(hmin, 0.5 * step_size);
            } else {
                step_size = py_max(hmin, step_size * py_max(OS_SHRINK_LEAST, OS_SAFETY * std::pow(rtol / err, exponent)));
            }
            failed_once = true;
            if (step_size <= hmin) {
                at_floor += 1;
                if (at_floor >= OS_MAX_AT_FLOOR) throw SolverError("tolerance", S::floor_message(t, hmin, worst_at), t);
                step_size = before;
                nbelowtol += 1;
                break;
            }
            h = direction * step_size;
            last = false;
        }
        if (restart) continue;
        nsteps += 1;
        bool reprojected = false;
        if (has_nn) {
            if (sv::any_below_zero(ynew, nn_idx)) {
                long long cnt = 0;
                for (I32 i : nn_idx) {
                    if (ynew[i] < 0) {
                        ynew[i] = 0.0;
                        cnt += 1;
                    }
                }
                reprojected = true;
                negative += cnt;
                floor_in_window += cnt;
            }
            if (rhs.hold) {
                Vec& push = rhs.push;
                long long cnt = 0;
                for (int i = 0; i < neq; i++) {
                    if (push[i] * step_size > atol[i]) {
                        held[i] += 1;
                        cnt += 1;
                    }
                }
                floor_in_window += cnt;
                std::fill(push.begin(), push.end(), 0.0);
            }
        }
        if (nsteps - stall_step >= stall_window) {
            const bool crawling = std::fabs(tnew - stall_t) < stall_span;
            const bool not_growing = std::fabs(h) <= stall_h;
            if (crawling && not_growing) {
                throw SolverError("stalled", S::stall_message(tnew, stall_window, stall_span, floor_in_window > 0), tnew);
            }
            stall_step = nsteps;
            stall_t = tnew;
            stall_h = std::fabs(h);
            floor_in_window = 0;
        }

        if (events != nullptr) {
            const bool hit = sv::ev_locate_crossing(*events, event_work, t, vl, tnew, ynew, vr, dense_at, evbuf, t0, &tspan,
                                                    next_out);
            if (hit) {
                tnew = event_work.t;
                dense_at(dense, tnew);
                ynew = dense;
                if (event_work.values != &vr) vr = *event_work.values;
                sol.stopped = Stopped{tnew, ynew, event_work.which};
                last = true;
            }
            vl = vr;
        }
        while (next_out < npts) {
            const double tq = tspan[next_out];
            if (direction * (tnew - tq) < 0) break;
            const Vec* at_v = &ynew;
            if (!(tq == tnew)) {
                dense_at(dense, tq);
                at_v = &dense;
            }
            tout.push_back(tq);
            yout.push_copy(*at_v);
            if (on_output) on_output(tq, *at_v);
            next_out += 1;
        }
        if (on_accepted) on_accepted(tnew, ynew);
        if (on_step && (nsteps & 31) == 0) {
            if (!on_step(std::fabs(tnew - t0) / span, static_cast<long>(nsteps), tnew)) {
                throw SolverError("aborted", "Simulation aborted", tnew);
            }
        }
        if (last) break;
        nfevals += st.accept(tnew, ynew, reprojected);
        if (!failed_once) {
            const double grow = err > 0 ? OS_SAFETY * std::pow(rtol / err, exponent) : OS_GROW_MOST;
            step_size *= py_min(OS_GROW_MOST, py_max(OS_SHRINK_LEAST, grow));
        }
        t = tnew;
        y = ynew;
    }
    Json stats = Json::object();
    stats.set("nsteps", Json(nsteps));
    stats.set("nfailed", Json(nfailed));
    stats.set("nfevals", Json(nfevals));
    stats.set("nbelowtol", Json(nbelowtol));
    stats.set("negative", Json(negative));
    if (rhs.hold) {
        Json list = Json::array();
        for (long long v : held) list.push(Json(v));
        stats.set("held", list);
    } else {
        stats.set("held", Json());
    }
    stats.set("solver", Json(S::id()));
    stats.set("points", Json(static_cast<long long>(tout.size())));
    st.stats(stats);
    sol.end_t = tnew;
    sol.end_y = ynew;
    sol.stats = std::move(stats);
    return sol;
}

Solution os_integrate(bool ros, const RhsFunction& f, const Vec& tspan, const Vec& y0, const SolverOptions& o) {
    if (tspan.empty()) throw std::invalid_argument("the time span is empty");
    const int neq = static_cast<int>(y0.size());
    const std::size_t N = y0.size();
    const double t0 = tspan.front();
    const double t_end = tspan.back();
    if (t_end == t0) throw SolverError("span", "Simulation start and end time are equal", t0);
    const double span = std::fabs(t_end - t0);
    const double rtol = sv::opt_or(o.rtol, 1e-3);
    Vec atol;
    if (o.abstol_vector != nullptr) {
        if (o.abstol_vector->size() != N) throw std::invalid_argument("the absolute tolerances are not one per state");
        atol = *o.abstol_vector;
    } else {
        atol.assign(N, o.abstol);
    }
    Vec threshold(N);
    for (std::size_t i = 0; i < N; i++) threshold[i] = atol[i] / rtol;
    bool any_nn = false;
    for (std::uint8_t v : o.non_negative) any_nn |= v != 0;
    std::vector<std::uint8_t> mask_store;
    const std::vector<std::uint8_t>* mask = nullptr;
    if (any_nn) {
        if (o.non_negative.size() != N) throw std::invalid_argument("non_negative is not one flag per state");
        mask_store = o.non_negative;
        mask = &mask_store;
    }
    OsRhs rhs{&f, mask != nullptr && ros, {}, Vec(N, 0.0)};
    if (mask != nullptr) {
        for (int i = 0; i < neq; i++)
            if ((*mask)[i] != 0) rhs.idx.push_back(i);
    }
    const double hmax = (o.hmax && *o.hmax != 0 && *o.hmax > 0) ? py_min(*o.hmax, span) : 0.1 * span;
    const double hmin_opt = (o.hmin && *o.hmin != 0 && *o.hmin > 0) ? *o.hmin : 0.0;
    const long stall_window = (o.stall_window && *o.stall_window != 0) ? *o.stall_window : OS_STALL_WINDOW_STEPS;
    const double h0 = (o.h0 && *o.h0 != 0 && *o.h0 > 0) ? *o.h0 : 0.0;
    if (ros) {
        Ros23 st(neq, &rhs, &threshold, o.jacobian);
        const double max_steps = sv::opt_or(o.max_steps, Ros23::default_max_steps());
        return os_run(st, rhs, tspan, y0, rtol, atol, threshold, mask, max_steps, hmax, hmin_opt, stall_window, h0,
                      o.events, o.on_output, o.on_accepted, o.on_step, o.landing);
    }
    DP45 st(neq, &rhs);
    const double max_steps = sv::opt_or(o.max_steps, DP45::default_max_steps());
    return os_run(st, rhs, tspan, y0, rtol, atol, threshold, mask, max_steps, hmax, hmin_opt, stall_window, h0,
                  o.events, o.on_output, o.on_accepted, o.on_step, o.landing);
}

}  // namespace

Solution rosenbrock23(const RhsFunction& f, const Vec& tspan, const Vec& y0, const SolverOptions& options) {
    return os_integrate(true, f, tspan, y0, options);
}

Solution dormand_prince(const RhsFunction& f, const Vec& tspan, const Vec& y0, const SolverOptions& options) {
    return os_integrate(false, f, tspan, y0, options);
}

}  // namespace kompartment
