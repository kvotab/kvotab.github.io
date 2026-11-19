#include "solvers/ndf.hpp"

#include <algorithm>
#include <cmath>
#include <memory>
#include <stdexcept>

#include "solvers/kernels.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace sv {

double ndf_ulp(double x) {
    const double a = std::fabs(x);
    if (!(a > 0)) return 5e-324;
    double e = std::floor(std::log2(a)) - 52.0;
    e = e > -1074.0 ? e : -1074.0;
    return std::pow(2.0, e);
}

}  // namespace sv

namespace {

using sv::jl_max;
using sv::py_max;
using sv::py_min;

constexpr double NDF_EPS = 0x1p-52;
constexpr int NDF_MAX_ORDER = 5;
constexpr double NDF_KAPPA[5] = {-0.185, -1.0 / 9, -0.0823, -0.0415, 0.0};
constexpr double NDF_GAMMA[5] = {1.0, 3.0 / 2, 11.0 / 6, 25.0 / 12, 137.0 / 60};
constexpr int NDF_NEWTON_MAX = 4;
constexpr double NDF_NEWTON_TOL = 0.3;
constexpr double NDF_RATE_LIMIT = 0.9;
constexpr double NDF_RATE_FLOOR = 0.02;
// The floor on the Newton rate where the Jacobian is exact and constant (a linear model: `constant`
// and `state_free`): one iteration then solves the step's equations to round-off, and the rate
// measured is round-off too, so a step stops after one iteration where ode15s's floor of 0.02 would
// ask for two. The other engines do the same, so parity keeps it.
constexpr double NDF_EXACT_RATE_FLOOR = 1e-6;
constexpr double NDF_CONVERGED_FLOOR = 1e-3;
constexpr double NDF_SAFETY = 0.8;
constexpr double NDF_SAFETY_LOWER = 0.75;
constexpr double NDF_SAFETY_HIGHER = 0.7;
constexpr double NDF_MAX_GROWTH = 10.0;
constexpr double NDF_NEWTON_CUT = 0.25;
constexpr double NDF_STALL_SPAN_FRACTION = 1e-10;
constexpr int NDF_MAX_BELOW_TOLERANCE = 20;
constexpr int NDF_TRACE_STEPS = 12;

// The operations on the difference table go over the states in tiles that stay in the
// first-level cache, and inside a tile one column at a time, so that every inner loop reads
// two or three arrays and vectorises -- each state's arithmetic the Python engine's, in its order.
constexpr int NDF_TILE = 512;

inline double step_floor(double t) { return 16 * sv::ndf_ulp(t); }

SolverError floor_failure(double t, bool nonfinite) {
    const double hmin = step_floor(t);
    if (nonfinite) {
        return SolverError("nonfinite",
                           "The state or its derivative became non-finite at t=" + py_repr(t) +
                               ", and no step size above the smallest allowed (" + py_repr(hmin) + ") gives a number.",
                           t);
    }
    return SolverError("tolerance",
                       "Failure at t=" + py_repr(t) +
                           ": unable to meet the integration tolerances without reducing the step size below the "
                           "smallest value allowed (" + py_repr(hmin) + ").",
                       t);
}

SolverError steps_failure(double max_steps, double t) {
    return SolverError("steps",
                       "Exceeded " + std::to_string(static_cast<long long>(max_steps)) + " steps at t=" + py_repr(t) +
                           ". Nothing this solver can do with the step size will finish this run.",
                       t);
}

SolverError stall_failure(double t, long window, double covered) {
    return SolverError("stalled",
                       "The solver stopped making progress at t=" + py_repr(t) + ": " + std::to_string(window) +
                           " accepted steps advanced the clock by less than " + py_repr(covered) +
                           ", and the step size is no longer growing.",
                       t);
}

SolverError error_nonfinite(double t) {
    return SolverError("nonfinite",
                       "The error estimate is not a number at t=" + py_repr(t) +
                           ": a tolerance or a state weight is NaN.",
                       t);
}

SolverError initial_nonfinite(double t0, int state) {
    return SolverError("nonfinite",
                       "The state or its derivative is not a number at t=" + py_repr(t0) + " (state " +
                           std::to_string(state) + ").",
                       t0);
}

void basis_at(Vec& out, double s, int k) {
    out[0] = 1.0;
    for (int j = 1; j <= k; j++) out[j] = out[j - 1] * (((s + j) - 1) / j);
}

double choose(int n, int r) {
    double v = 1.0;
    for (int i = 1; i <= r; i++) v = (v * (n - r + i)) / i;
    return v;
}

/// The regridding matrix (`regrid_matrix`): T[m, j] for 0 <= m <= j <= k, held by rows of `w`.
void regrid_matrix(Vec& T, Vec& vals, Vec& b, int w, int k, double s_end, double ratio) {
    for (int i = 0; i <= k; i++) {
        basis_at(b, s_end - i * ratio, k);
        for (int j = 0; j <= k; j++) vals[i * w + j] = b[j];
    }
    for (int m = 0; m <= k; m++) {
        for (int j = 0; j <= k; j++) T[m * w + j] = 0.0;
        for (int j = m; j <= k; j++) {
            double acc = 0.0;
            for (int i = 0; i <= m; i++) acc += ((i % 2 == 1 ? -1.0 : 1.0) * choose(m, i)) * vals[i * w + j];
            T[m * w + j] = acc;
        }
    }
}

/// The floored states: those weighed against another's size as well, the states they are
/// weighed against, and the factors (see `weight_floor` in `ndf`).
struct Floor {
    std::vector<I32> at;
    std::vector<I32> from;
    Vec factor;
};

/// The norm every test is measured in (`Weighting`).
struct Weighting {
    const Vec* threshold = nullptr;
    bool norm_control = false;
    bool rms = false;
    Vec inv;
    const Floor* floor = nullptr;

    void init(int neq, const Vec* threshold_, bool norm_control_, bool rms_, const Floor* floor_) {
        threshold = threshold_;
        norm_control = norm_control_;
        rms = (!norm_control_) && rms_;
        inv.assign(norm_control_ ? 1 : static_cast<std::size_t>(neq), 0.0);
        floor = floor_;
    }
};

/// The floored states' weights from `y` and `ynew`: the larger of their own and the floor, where the floor is larger
/// (a NaN floor leaves the weight as it was), as `Weighting.update` takes it.
inline void floor_weights(const Weighting& w, Vec& inv, const Vec& thr, const Vec& y, const Vec& ynew) {
    const Floor& fl = *w.floor;
    for (std::size_t q = 0; q < fl.at.size(); q++) {
        const I32 i = fl.at[q];
        const I32 k = fl.from[q];
        const double ww = jl_max(jl_max(std::fabs(y[i]), std::fabs(ynew[i])), thr[i]);
        const double v = fl.factor[q] * jl_max(std::fabs(y[k]), std::fabs(ynew[k]));
        inv[i] = 1 / (v > ww ? v : ww);
    }
}

void update_weights(Weighting& w, const Vec& y, const Vec& ynew) {
    const Vec& thr = *w.threshold;
    if (w.norm_control) {
        w.inv[0] = 1 / py_max(py_max(std::sqrt(sv::seq_sum_squares(y)), std::sqrt(sv::seq_sum_squares(ynew))), thr[0]);
        return;
    }
    Vec& inv = w.inv;
    const std::size_t n = inv.size();
    sv::inverse_weights(inv.data(), y.data(), ynew.data(), thr.data(), 0, static_cast<int>(n));
    if (!w.floor->at.empty()) floor_weights(w, inv, thr, y, ynew);
}

/// `weight_floor` checked (`weightFloorOf`): `(from, factor)`, one entry per state, `from` another state (counted
/// from zero) or -1 and `factor` a finite number of zero or more.
Floor weight_floor_of(const WeightFloor* option, int neq) {
    Floor fl;
    if (option == nullptr) return fl;
    if (static_cast<int>(option->from.size()) != neq || static_cast<int>(option->factor.size()) != neq) {
        throw SolverError("weightFloor", "weightFloor needs a from and a factor for each of the " +
                                             std::to_string(neq) + " equations");
    }
    for (int i = 0; i < neq; i++) {
        const double k = option->from[i];
        const double c = option->factor[i];
        const bool whole = std::isfinite(k) && k == std::floor(k);
        if (!(whole && -1 <= k && k < neq) || !(c >= 0 && std::isfinite(c))) {
            throw SolverError("weightFloor", "weightFloor's entry " + std::to_string(i) +
                                                 " is not a state and a factor: " + js_text(k) + ", " + js_text(c));
        }
        if (!(k >= 0)) continue;
        fl.at.push_back(i);
        fl.from.push_back(static_cast<I32>(k));
        fl.factor.push_back(c);
    }
    return fl;
}

/// `held_with` checked (`heldWithOf`): one entry per state, the state (counted from zero) it is held
/// with or -1; as the state each row is held with, -1 for none -- empty where the option is not given.
std::vector<I32> held_with_of(const Vec* option, int neq) {
    std::vector<I32> out;
    if (option == nullptr) return out;
    if (static_cast<int>(option->size()) != neq) {
        throw SolverError("heldWith", "heldWith needs an entry for each of the " + std::to_string(neq) + " equations");
    }
    out.assign(static_cast<std::size_t>(neq), -1);
    for (int r = 0; r < neq; r++) {
        const double i = (*option)[static_cast<std::size_t>(r)];
        const bool whole = std::isfinite(i) && i == std::floor(i);
        if (!(whole && -1 <= i && i < neq && i != r)) {
            throw SolverError("heldWith", "heldWith's entry " + std::to_string(r) + " is not another state: " + js_text(i));
        }
        out[static_cast<std::size_t>(r)] = static_cast<I32>(i);
    }
    return out;
}

double norm_of(const Weighting& w, const Vec& v) {
    const Vec& inv = w.inv;
    if (w.norm_control) return std::sqrt(sv::seq_sum_squares(v)) * inv[0];
    if (w.rms) {
        const std::size_t n = v.size();
        if (n == 0) return 0.0;
        double s = 0.0;
        for (std::size_t i = 0; i < n; i++) {
            const double a = v[i] * inv[i];
            s += a * a;
        }
        return std::sqrt(s / static_cast<double>(n));
    }
    return sv::scaled_max(v, inv);
}

// --- the solver's state -------------------------------------------------------------------------------

struct State {
    const RhsFunction* f = nullptr;
    int neq = 0;
    double rtol = 0.0;
    Vec* atol = nullptr;
    Vec threshold;
    Vec newton_threshold;
    Floor floor;
    Weighting error_weight;
    Weighting newton_weight_own;
    Weighting* newton_weight = nullptr;
    bool separate_newton = false;
    const Vec* mass = nullptr;
    std::vector<I32> algebraic;
    double leading[5] = {0, 0, 0, 0, 0};
    double error_const[5] = {0, 0, 0, 0, 0};
    int max_order = 5;
    double direction = 0.0;
    // the projected system
    std::vector<I32> constrained;
    bool projected = false;
    std::vector<std::uint8_t> held_rows;
    Vec push;
    /// Whether any push has been raised above zero since they were last cleared.
    bool pushed = false;
    /// Whether some absolute tolerance is below zero, which even a push of zero is above.
    bool atol_below_zero = false;
    bool any_held = false;
    std::vector<std::uint8_t> held_now;
    std::vector<std::uint8_t> held_in_w;
    bool w_held = false;                // a row held in the matrix as it was last formed
    // The rows held with each constrained state (`held_with`), by its place in `constrained`: those
    // of the q-th are fol_rows[fol_start[q]] up to fol_rows[fol_start[q + 1]]; none where
    // `followers` is false.
    bool followers = false;
    std::vector<I32> fol_start;
    std::vector<I32> fol_rows;
    // the Jacobian and the matrix
    const Pattern* pattern = nullptr;
    const ColumnGroups* groups = nullptr;
    ColumnGroups own_groups;
    const JacobianEvaluate* evaluate = nullptr;
    bool constant = false;
    bool state_free = false;
    Vec J;
    bool fresh = false;
    DifferenceWork dwork;
    std::unique_ptr<AbstractIterationMatrix> W;
    // the difference table: D[j] is the j-th backward difference
    std::vector<Vec> D;
    Vec tmp;
    Vec T;
    Vec Tvals;
    Vec basis;
    // where the step is
    double t = 0.0;
    double tnew = 0.0;
    double h = 0.0;
    int k = 1;
    double hW = 0.0;
    int kW = 0;
    double rate = -1.0;
    double hTable = 0.0;
    int consecutive = 0;
    int mask_reforms = 0;
    // counts
    long long nfevals = 0;
    long long nsteps = 0;
    long long nfailed = 0;
    long long npds = 0;
    long long ndecomps = 0;
    long long nsolves = 0;
    long long nbelowtol = 0;
    long long negative = 0;
    // the last steps, for a failure's trace
    double trace_t[NDF_TRACE_STEPS] = {};
    double trace_h[NDF_TRACE_STEPS] = {};
    int trace_k[NDF_TRACE_STEPS] = {};
    double trace_err[NDF_TRACE_STEPS] = {};
    int trace_newton[NDF_TRACE_STEPS] = {};
    int trace_failed[NDF_TRACE_STEPS] = {};
    int trace_len = 0;
    int trace_pos = 0;
    // work vectors
    Vec fv;
    Vec pred;
    Vec hist;
    Vec ynew;
    Vec d;
    Vec delta;
    Vec work;
    Vec dense;
};

// NOTE(speed): the derivative is called through a std::function (twice over from
// `variable_order`, which counts the calls in one of its own); a solver templated on the
// derivative would let a system's own code be called directly.
inline void raw(State& s, Vec& out, double t, const Vec& y) {
    s.nfevals += 1;
    (*s.f)(out, t, y);
}

/// The derivative of the projected system (`projectedDerivative`): a
/// constrained state at or below zero whose equation pushes it lower is held,
/// and the rows held with it (`held_with`) with it.
void rhs(State& s, Vec& out, double t, const Vec& y) {
    if (!s.projected) {
        raw(s, out, t, y);
        return;
    }
    const std::vector<I32>& c = s.constrained;
    if (sv::all_above_zero(y, c)) {
        raw(s, out, t, y);
        if (s.any_held) {
            for (I32 i : c) s.held_rows[i] = 0;
            if (s.followers)
                for (I32 r : s.fol_rows) s.held_rows[r] = 0;
            s.any_held = false;
        }
        return;
    }
    raw(s, out, t, y);
    Vec& push = s.push;
    bool anyh = false;
    for (std::size_t q = 0; q < c.size(); q++) {
        const I32 i = c[q];
        const bool hold = (y[i] <= 0) && (out[i] < 0);
        // A push is +0 or above, so its maximum with +0 is itself: only a held state's is taken.
        if (hold) {
            push[q] = jl_max(push[q], -out[i]);
            out[i] = 0.0;
            anyh = true;
        }
        s.held_rows[i] = hold ? 1 : 0;
    }
    if (s.followers) {
        for (std::size_t q = 0; q < c.size(); q++) {
            const std::uint8_t h = s.held_rows[c[q]];
            for (I32 p = s.fol_start[q]; p < s.fol_start[q + 1]; p++) {
                const I32 r = s.fol_rows[p];
                s.held_rows[r] = h;
                if (h == 1) out[r] = 0.0;
            }
        }
    }
    s.any_held = anyh;
    if (anyh) s.pushed = true;
}

Json stats_of(const State& s) {
    Json out = Json::object();
    out.set("nsteps", Json(s.nsteps));
    out.set("nfailed", Json(s.nfailed));
    out.set("npds", Json(s.npds));
    out.set("ndecomps", Json(s.ndecomps));
    out.set("nsolves", Json(s.nsolves));
    out.set("nbelowtol", Json(s.nbelowtol));
    out.set("negative", Json(s.negative));
    out.set("nfevals", Json(s.nfevals));
    return out;
}

Json trace_of(const State& s) {
    Json out = Json::array();
    const int n = s.trace_len;
    const int cap = NDF_TRACE_STEPS;
    const int first = n < cap ? 0 : s.trace_pos;
    for (int q = 0; q < n; q++) {
        const int i = (first + q) % cap;
        Json step = Json::object();
        step.set("t", Json(s.trace_t[i]));
        step.set("h", Json(s.trace_h[i]));
        step.set("k", Json(s.trace_k[i]));
        step.set("err", Json(s.trace_err[i]));
        step.set("newton", Json(s.trace_newton[i]));
        step.set("failed", Json(s.trace_failed[i]));
        out.push(step);
    }
    return out;
}

/// `fail(e)`: the failure with where the run was.
SolverError fail(const State& s, SolverError e) {
    e.trace = trace_of(s);
    e.last_t = s.t;
    e.last_y = s.D[0];
    e.stats = stats_of(s);
    return e;
}

// --- the difference table -----------------------------------------------------------------------------

/// The start of an attempt: the prediction and the history (`predict`,
/// `history`) into `pred` and `hist`, `ynew = pred`, `d = 0`, the weights
/// updated with (y, ynew) (`update`), and -- returned -- the norm of ynew in
/// the Newton weight.
double begin_attempt(State& s, int k) {
    const int n = s.neq;
    const double* y = s.D[0].data();
    double* pred = s.pred.data();
    double* hist = s.hist.data();
    double* ynew = s.ynew.data();
    double* d = s.d.data();
    Weighting& ew = s.error_weight;
    Weighting& nw = *s.newton_weight;
    const bool sep = s.separate_newton;
    double* einv = ew.inv.data();
    const double* ethr = ew.threshold->data();
    double* ninv = nw.inv.data();
    const double* nthr = nw.threshold->data();
    for (int lo = 0; lo < n; lo += NDF_TILE) {
        const int hi = std::min(lo + NDF_TILE, n);
        // pred = c0 + c1 + ... + ck, and hist = 0 + g1 c1 + ... + gk ck
        for (int i = lo; i < hi; i++) {
            pred[i] = y[i];
            hist[i] = 0.0;
        }
        for (int j = 1; j <= k; j++) {
            const double* cj = s.D[j].data();
            for (int i = lo; i < hi; i++) pred[i] += cj[i];
        }
        for (int j = 1; j <= k; j++) {
            const double* cj = s.D[j].data();
            const double g = NDF_GAMMA[j - 1];
            for (int i = lo; i < hi; i++) hist[i] += g * cj[i];
        }
        for (int i = lo; i < hi; i++) {
            ynew[i] = pred[i];
            d[i] = 0.0;
        }
        if (ew.norm_control) continue;
        sv::inverse_weights(einv, y, pred, ethr, lo, hi);
        if (sep) sv::inverse_weights(ninv, y, pred, nthr, lo, hi);
    }
    // The floored states, once the whole prediction is there to read.
    if (!ew.norm_control && !ew.floor->at.empty()) {
        floor_weights(ew, ew.inv, *ew.threshold, s.D[0], s.pred);
        if (sep) floor_weights(nw, nw.inv, *nw.threshold, s.D[0], s.pred);
    }
    if (ew.norm_control) {
        const double ry = std::sqrt(sv::seq_sum_squares(s.D[0]));
        const double rp = std::sqrt(sv::seq_sum_squares(s.ynew));
        ew.inv[0] = 1 / py_max(py_max(ry, rp), (*ew.threshold)[0]);
        if (sep) nw.inv[0] = 1 / py_max(py_max(ry, rp), (*nw.threshold)[0]);
        return rp * nw.inv[0];
    }
    return norm_of(nw, s.ynew);
}

/// A Newton correction taken: `d += delta`, `ynew = pred + d`, in one pass,
/// and -- returned -- the norm of the new `d` in the error weight (`of_error`).
double take_correction(State& s) {
    const int n = s.neq;
    double* d = s.d.data();
    double* ynew = s.ynew.data();
    const double* pred = s.pred.data();
    const double* delta = s.delta.data();
    const Weighting& ew = s.error_weight;
    if (ew.norm_control) {
        double acc = 0.0;
        for (int i = 0; i < n; i++) {
            const double di = d[i] + delta[i];
            d[i] = di;
            ynew[i] = pred[i] + di;
            acc += di * di;
        }
        return std::sqrt(acc) * ew.inv[0];
    }
    const double* inv = ew.inv.data();
    if (ew.rms) {
        double acc = 0.0;
        for (int i = 0; i < n; i++) {
            const double di = d[i] + delta[i];
            d[i] = di;
            ynew[i] = pred[i] + di;
            const double a = di * inv[i];
            acc += a * a;
        }
        return n == 0 ? 0.0 : std::sqrt(acc / n);
    }
    for (int i = 0; i < n; i++) {
        const double di = d[i] + delta[i];
        d[i] = di;
        ynew[i] = pred[i] + di;
    }
    return sv::scaled_max(s.d, ew.inv);
}

/// `advance(k, d)`: the step taken into the table.
void advance(std::vector<Vec>& D, int k, const Vec& d_) {
    const int n = static_cast<int>(d_.size());
    const double* d = d_.data();
    double* a = D[k + 2].data();
    double* b = D[k + 1].data();
    for (int lo = 0; lo < n; lo += NDF_TILE) {
        const int hi = std::min(lo + NDF_TILE, n);
        for (int i = lo; i < hi; i++) {
            a[i] = d[i] - b[i];
            b[i] = d[i];
        }
        for (int j = k; j >= 0; j--) {
            double* cj = D[j].data();
            const double* cj1 = D[j + 1].data();
            for (int i = lo; i < hi; i++) cj[i] += cj1[i];
        }
    }
}

/// `regrid(k, s_end, ratio)`: the table re-expressed on the grid of a new
/// step. Column m is made from the old columns m..k and then written, which
/// no later column reads.
void regrid(State& s, int k, double s_end, double ratio) {
    const int w = s.max_order + 1;
    regrid_matrix(s.T, s.Tvals, s.basis, w, k, s_end, ratio);
    const double* T = s.T.data();
    double* tmp = s.tmp.data();
    const int n = s.neq;
    for (int lo = 0; lo < n; lo += NDF_TILE) {
        const int hi = std::min(lo + NDF_TILE, n);
        for (int m = 0; m <= k; m++) {
            for (int i = lo; i < hi; i++) tmp[i] = 0.0;
            for (int j = m; j <= k; j++) {
                const double wt = T[m * w + j];
                if (wt == 0) continue;
                const double* c = s.D[j].data();
                for (int i = lo; i < hi; i++) tmp[i] += wt * c[i];
            }
            double* cm = s.D[m].data();
            for (int i = lo; i < hi; i++) cm[i] = tmp[i];
        }
    }
}

inline void rescale(State& s, int k, double ratio) { regrid(s, k, 0.0, ratio); }

void value_at(Vec& out_, State& s, int k, double sq, bool clamp) {
    basis_at(s.basis, sq, k);
    const int n = s.neq;
    double* out = out_.data();
    const double* c0 = s.D[0].data();
    for (int i = 0; i < n; i++) out[i] = c0[i];
    for (int j = 1; j <= k; j++) {
        const double bj = s.basis[j];
        const double* c = s.D[j].data();
        for (int i = 0; i < n; i++) out[i] += bj * c[i];
    }
    if (clamp) {
        for (std::size_t q = 0; q < s.constrained.size(); q++) {
            const I32 i = s.constrained[q];
            const double v = out[i];
            out[i] = v < 0 ? 0.0 : v;
            // ...and the rows held with a state put onto zero, put there with it.
            if (v < 0 && s.followers)
                for (I32 p = s.fol_start[q]; p < s.fol_start[q + 1]; p++) out[s.fol_rows[p]] = 0.0;
        }
    }
}

inline void forget(std::vector<Vec>& D, I32 i) {
    for (std::size_t j = 1; j < D.size(); j++) D[j][i] = 0.0;
}

/// The rows held with the q-th constrained state, put onto zero with it -- and, `forget_them`, their
/// history forgotten as its is.
void follow_onto_zero(State& s, std::size_t q, bool forget_them) {
    Vec& y = s.D[0];
    for (I32 p = s.fol_start[q]; p < s.fol_start[q + 1]; p++) {
        const I32 r = s.fol_rows[p];
        y[r] = 0.0;
        if (forget_them) forget(s.D, r);
    }
}

/// The rows held with each constrained state, by its place in `constrained` (`heldWithOf`): a row held
/// with a state the floor never holds is held never, and left out.
void build_followers(State& s, const std::vector<I32>& held_with) {
    s.followers = false;
    if (held_with.empty()) return;
    const std::vector<I32>& c = s.constrained;
    std::vector<I32> place(held_with.size(), -1);
    for (std::size_t q = 0; q < c.size(); q++) place[static_cast<std::size_t>(c[q])] = static_cast<I32>(q);
    s.fol_start.assign(c.size() + 1, 0);
    for (std::size_t r = 0; r < held_with.size(); r++) {
        const I32 l = held_with[r];
        if (l >= 0 && place[static_cast<std::size_t>(l)] >= 0) s.fol_start[static_cast<std::size_t>(place[static_cast<std::size_t>(l)]) + 1] += 1;
    }
    for (std::size_t q = 0; q < c.size(); q++) s.fol_start[q + 1] += s.fol_start[q];
    if (s.fol_start[c.size()] == 0) return;
    s.fol_rows.assign(static_cast<std::size_t>(s.fol_start[c.size()]), 0);
    std::vector<I32> next(s.fol_start.begin(), s.fol_start.end() - 1);
    for (std::size_t r = 0; r < held_with.size(); r++) {
        const I32 l = held_with[r];
        if (l >= 0 && place[static_cast<std::size_t>(l)] >= 0) {
            const std::size_t q = static_cast<std::size_t>(place[static_cast<std::size_t>(l)]);
            s.fol_rows[static_cast<std::size_t>(next[q]++)] = static_cast<I32>(r);
        }
    }
    s.followers = true;
}

// --- the Jacobian and the matrix ----------------------------------------------------------------------

/// df/dy differenced at the current point from `fy` (`differenced`).
void differenced(State& s, const Vec& fy) {
    const Vec& y = s.D[0];
    const double t = s.t;
    if (s.pattern != nullptr) {
        difference_jacobian(s.J, [&s](Vec& out, double tt, const Vec& yy) { raw(s, out, tt, yy); }, t, y, fy,
                            *s.pattern, *s.groups, s.threshold, s.dwork);
        return;
    }
    const int n = s.neq;
    difference_increment(s.dwork.dl, y, s.threshold);
    const Vec& dl = s.dwork.dl;
    Vec& ytry = s.dwork.ytry;
    Vec& fg = s.dwork.fg;
    Vec& J = s.J;
    ytry = y;
    for (int j = 0; j < n; j++) {
        ytry[j] = y[j] + dl[j];
        raw(s, fg, t, ytry);
        const std::size_t off = static_cast<std::size_t>(j) * n;
        for (int i = 0; i < n; i++) J[off + i] = (fg[i] - fy[i]) / dl[j];
        ytry[j] = y[j];
    }
}

/// `evaluate_jacobian(fy)`: the supplied Jacobian, or differenced (from `fy`,
/// or from a fresh evaluation when there is none).
void evaluate_jacobian(State& s, const Vec* fy) {
    s.npds += 1;
    const bool supplied = s.evaluate != nullptr && (*s.evaluate)(s.J, s.t, s.D[0]);
    if (!supplied) {
        if (fy == nullptr) {
            raw(s, s.work, s.t, s.D[0]);
            fy = &s.work;
        }
        differenced(s, *fy);
    }
    s.fresh = true;
}

inline void read_held(State& s) {
    if (s.projected) std::copy(s.held_rows.begin(), s.held_rows.end(), s.held_now.begin());
}

bool held_moved(const State& s) {
    if (!s.projected) return false;
    for (I32 i : s.constrained)
        if (s.held_now[i] != s.held_in_w[i]) return true;
    return false;
}

bool released_in_w(State& s) {
    if (!s.projected) return false;
    bool any = false;
    for (std::size_t q = 0; q < s.constrained.size(); q++) {
        const I32 i = s.constrained[q];
        if (s.held_in_w[i] == 1 && s.held_rows[i] == 0) {
            s.held_now[i] = 0;
            any = true;
            // ...and the rows held with it, released with it.
            if (s.followers)
                for (I32 p = s.fol_start[q]; p < s.fol_start[q + 1]; p++) s.held_now[s.fol_rows[p]] = 0;
        }
    }
    return any;
}

/// `form_w()`: the iteration matrix for the current step and order.
void form_w(State& s) {
    bool any_held = false;
    if (s.projected) {
        std::copy(s.held_now.begin(), s.held_now.end(), s.held_in_w.begin());
        for (I32 i : s.constrained) {
            if (s.held_in_w[i] != 0) {
                any_held = true;
                break;
            }
        }
    }
    std::optional<std::string> msg = s.W->form(s.h / s.leading[s.k - 1], s.J, any_held ? &s.held_in_w : nullptr);
    if (msg) throw fail(s, SolverError("singular", *msg + " (at t=" + py_repr(s.t) + ")", s.t));
    s.ndecomps += 1;
    s.hW = s.h;
    s.kW = s.k;
    s.w_held = any_held;
    // A new matrix converges at a rate of its own -- except an exact one (a constant Jacobian,
    // no rows held), whose rate is round-off whatever the step.
    if (!(s.constant && s.state_free && !any_held)) s.rate = -1.0;
}

void change_step(State& s, double factor) {
    const double h_new = s.direction * py_max(step_floor(s.t), std::fabs(s.h) * factor);
    if (h_new != s.hTable) {
        rescale(s, s.k, h_new / s.hTable);
        s.hTable = h_new;
    }
    s.h = h_new;
    s.consecutive = 0;
    s.mask_reforms = 0;
}

/// `snap_onto_bound`: constrained states within their absolute tolerance
/// above zero that `should` picks are put on zero; false when there are none.
/// `by_held`: those held; otherwise those below zero in `s.ynew`.
bool snap_onto_bound(State& s, bool by_held) {
    Vec& yv = s.D[0];
    const Vec& atol = *s.atol;
    bool any = false;
    for (I32 i : s.constrained) {
        const bool should = by_held ? s.held_rows[i] == 1 : s.ynew[i] < 0;
        if ((yv[i] > 0) && (yv[i] <= atol[i]) && should) {
            any = true;
            break;
        }
    }
    if (!any) return false;
    long long count = 0;
    for (std::size_t q = 0; q < s.constrained.size(); q++) {
        const I32 i = s.constrained[q];
        const bool should = by_held ? s.held_rows[i] == 1 : s.ynew[i] < 0;
        if ((yv[i] > 0) && (yv[i] <= atol[i]) && should) {
            yv[i] = 0.0;
            forget(s.D, i);
            if (s.followers) follow_onto_zero(s, q, true);
            count += 1;
        }
    }
    s.negative += count;
    rhs(s, s.work, s.t, yv);
    read_held(s);
    form_w(s);
    return true;
}

inline double allowed(double e, int q, double safety, double rtol) {
    return e > 0 ? py_min(NDF_MAX_GROWTH, safety * std::pow(rtol / e, 1.0 / (q + 1))) : NDF_MAX_GROWTH;
}

/// Gives the matrix back when the run ends, however it ends.
struct Release {
    AbstractIterationMatrix* W;
    ~Release() {
        if (W != nullptr) W->release();
    }
};

Solution ndf_solve(const RhsFunction& f, const Vec& tspan, const Vec& y0, double rtol, Vec& atol,
                   const std::vector<I32>& non_negative, int max_order, bool bdf, double hmax_in, double h0,
                   double max_steps, const std::string& error_norm, bool norm_control, const JacobianSpec* jacobian,
                   const std::string& matrix, long floor_run, long floor_newton_run, double stagnation_tol,
                   int min_newton, long stall_window, const EventFunctions* events, double t_start_in,
                   const Hints* hints, const StepCallback& on_accepted, const StepCallback& on_output,
                   const StepProgress& on_step, bool auto_abstol, bool ends_only, const Vec* mass, RowPool* rows,
                   const StepLanding& landing, Floor floor_in, const IterationMatrixFactory& iteration_matrix,
                   const std::vector<I32>& held_with) {
    const int neq = static_cast<int>(y0.size());
    const std::size_t N = y0.size();
    const std::size_t npts = tspan.size();
    const double t0 = tspan.front();
    const double t_end = tspan.back();
    const double direction = t_end != t0 ? std::copysign(1.0, t_end - t0) : 0.0;
    const double span = std::fabs(t_end - t0);
    if (!(span > 0)) throw SolverError("span", "The start and end times are equal", t0);

    State s;
    s.f = &f;
    s.neq = neq;
    s.rtol = rtol;
    s.atol = &atol;
    for (int k = 1; k <= 5; k++) {
        s.leading[k - 1] = (1 - (bdf ? 0.0 : NDF_KAPPA[k - 1])) * NDF_GAMMA[k - 1];
        s.error_const[k - 1] = (bdf ? 0.0 : NDF_KAPPA[k - 1]) * NDF_GAMMA[k - 1] + 1.0 / (k + 1);
    }
    Vec& threshold = s.threshold;
    threshold.resize(N);
    for (std::size_t i = 0; i < N; i++) threshold[i] = atol[i] / rtol;
    if (auto_abstol) s.newton_threshold = threshold;
    if (mass != nullptr) {
        for (int i = 0; i < neq; i++)
            if ((*mass)[i] == 0.0) s.algebraic.push_back(i);
    }
    const std::vector<I32>& algebraic = s.algebraic;
    const bool rms = error_norm == "rms";
    s.floor = std::move(floor_in);
    s.error_weight.init(neq, &s.threshold, norm_control, rms, &s.floor);
    if (auto_abstol) {
        s.newton_weight_own.init(neq, &s.newton_threshold, norm_control, rms, &s.floor);
        s.newton_weight = &s.newton_weight_own;
    } else {
        s.newton_weight = &s.error_weight;
    }
    s.separate_newton = auto_abstol;
    Weighting& error_weight = s.error_weight;
    Weighting& newton_weight = *s.newton_weight;
    const double hmax = hmax_in > 0 ? py_min(hmax_in, span) : 0.1 * span;

    s.mass = mass;
    s.max_order = max_order;
    s.direction = direction;
    for (I32 i : non_negative)
        if (!(mass != nullptr && (*mass)[i] == 0)) s.constrained.push_back(i);
    const std::vector<I32>& constrained = s.constrained;
    const bool projected = !constrained.empty();
    s.projected = projected;
    s.held_rows.assign(N, 0);
    s.push.assign(constrained.size(), 0.0);
    s.pushed = false;
    s.atol_below_zero = false;
    for (I32 i : constrained) s.atol_below_zero |= atol[i] < 0;
    s.held_now.assign(N, 0);
    s.held_in_w.assign(N, 0);
    // Rows held with a constrained state (`held_with`): held where it is held, put onto zero where
    // it is put there.
    build_followers(s, held_with);

    const Pattern* pattern = (jacobian != nullptr && jacobian->pattern) ? &*jacobian->pattern : nullptr;
    s.pattern = pattern;
    s.evaluate = (jacobian != nullptr && jacobian->evaluate) ? &jacobian->evaluate : nullptr;
    const bool constant = jacobian != nullptr && jacobian->constant;
    s.constant = constant;
    s.state_free = jacobian != nullptr && jacobian->state_free;
    if (jacobian != nullptr && jacobian->groups) {
        s.groups = &*jacobian->groups;
    } else if (pattern != nullptr) {
        s.own_groups = colour_columns(*pattern);
        s.groups = &s.own_groups;
    }
    s.J.assign(pattern != nullptr ? pattern->nnz() : N * N, 0.0);
    s.dwork = DifferenceWork(pattern, s.groups, neq);

    std::vector<Vec>& D = s.D;
    D.assign(static_cast<std::size_t>(max_order) + 3, Vec(N, 0.0));
    D[0] = y0;
    s.tmp.assign(N, 0.0);
    const std::size_t w = static_cast<std::size_t>(max_order) + 1;
    s.T.assign(w * w, 0.0);
    s.Tvals.assign(w * w, 0.0);
    s.basis.assign(w, 0.0);
    s.t = t0;
    s.tnew = t0;
    for (Vec* v : {&s.fv, &s.pred, &s.hist, &s.ynew, &s.d, &s.delta, &s.work, &s.dense}) v->assign(N, 0.0);
    std::vector<long long> held;
    if (projected) held.assign(N, 0);

    Solution sol;
    Vec& tout = sol.t;
    Rows& yout = sol.y;
    auto record = [&](double tv, const Vec& yv) {
        if (ends_only && tout.size() > 1) {
            tout[1] = tv;
            yout[1] = yv;
        } else {
            tout.push_back(tv);
            if (rows != nullptr) {
                yout.push_borrowed(&take_row(*rows, yv));
            } else {
                yout.push_copy(yv);
            }
        }
    };

    std::size_t next_out = 1;
    record(t0, D[0]);

    Vec f0(N, 0.0);
    rhs(s, f0, t0, D[0]);
    for (int i = 0; i < neq; i++) {
        if (!std::isfinite(D[0][i]) || !std::isfinite(f0[i])) throw initial_nonfinite(t0, i);
    }
    Vec vl;
    Vec vr;
    sv::EventWork event_work;
    if (events != nullptr) {
        vl.assign(static_cast<std::size_t>(events->n), 0.0);
        events->fun(vl, t0, D[0]);
        vr.assign(static_cast<std::size_t>(events->n), 0.0);
        event_work = sv::EventWork(events->n);
    }
    const double t_start = std::isnan(t_start_in) ? t0 : t_start_in;

    // --- the Jacobian and the matrix ------------------------------------------------------------------
    evaluate_jacobian(s, &f0);
    try {
        if (iteration_matrix) {
            s.W = iteration_matrix(neq, pattern, s.J, matrix, mass, hints);
        } else {
            s.W = std::make_unique<IterationMatrix>(neq, pattern, s.J, matrix, mass, hints);
        }
    } catch (const MatrixError& e) {
        throw SolverError("singular", e.what(), t0);
    }
    AbstractIterationMatrix& W = *s.W;
    {
        Release release{&W};
        // --- the first step ---------------------------------------------------------------------------
        Vec yp = f0;
        for (I32 i : algebraic) yp[i] = 0.0;
        double step_size;
        if (h0 > 0) {
            step_size = h0;
        } else {
            const Vec& y = D[0];
            update_weights(error_weight, y, y);
            Vec& dy = s.work;
            dy = y;
            for (I32 i : algebraic) dy[i] = 0.0;
            const double d0 = norm_of(error_weight, dy) / rtol;
            const double d1 = norm_of(error_weight, yp) / rtol;
            double guess = (d0 < 1e-5 || d1 < 1e-5) ? 1e-6 : 0.01 * (d0 / d1);
            guess = py_min(guess, hmax);
            Vec& trial = s.ynew;
            const double dg = direction * guess;
            for (int i = 0; i < neq; i++) trial[i] = y[i] + dg * yp[i];
            rhs(s, s.fv, t0 + direction * guess, trial);
            const Vec& f1 = s.fv;
            Vec& df = s.work;
            for (int i = 0; i < neq; i++) df[i] = f1[i] - f0[i];
            for (I32 i : algebraic) df[i] = 0.0;
            double d2 = norm_of(error_weight, df) / rtol / guess;
            if (!std::isfinite(d2)) d2 = 100 * d1;
            const double m = py_max(d1, d2);
            const double h1 = m <= 1e-15 ? py_max(1e-6, guess * 1e-3) : std::sqrt(0.01 / m);
            step_size = py_min(100 * guess, h1);
        }
        step_size = py_min(hmax, py_max(step_floor(t0), step_size));
        s.h = direction * step_size;
        // table.start(y, h * yp)
        {
            Vec& c1 = D[1];
            const double hh = s.h;
            for (int i = 0; i < neq; i++) c1[i] = hh * yp[i];
            for (std::size_t j = 2; j < D.size(); j++) std::fill(D[j].begin(), D[j].end(), 0.0);
        }
        s.hTable = s.h;
        read_held(s);
        form_w(s);

        long below_run = 0;
        long long stall_step = 0;
        double stall_t = t0;
        double stall_h = 0.0;
        int newton_its = 0;
        int step_fails = 0;
        double err = 0.0;
        bool last = false;
        const double* hist = s.hist.data();
        const double* d = s.d.data();
        double* delta = s.delta.data();
        const Vec& ynew = s.ynew;
        auto dense_at = [&s, projected](Vec& out, double tq) { value_at(out, s, s.k, (tq - s.tnew) / s.h, projected); };

        for (;;) {
            const double hmin = step_floor(s.t);
            step_size = py_min(hmax, py_max(hmin, std::fabs(s.h)));
            last = false;
            double h_try = direction * step_size;
            if (1.1 * step_size >= std::fabs(t_end - s.t)) {
                h_try = t_end - s.t;
                last = true;
            }
            // A step that would pass over a pulse in a table ends on it instead:
            // f is never looked at between two steps.
            if (landing) {
                const double at = landing(s.t, s.t + h_try);
                if (direction * (at - s.t) > 0 && direction * (s.t + h_try - at) > 0) {
                    h_try = at - s.t;
                    last = false;
                }
            }
            if (h_try != s.hTable) {
                rescale(s, s.k, h_try / s.hTable);
                s.hTable = h_try;
                s.consecutive = 0;
            }
            s.h = h_try;
            s.mask_reforms = 0;
            if (projected) {
                const Vec& y = D[0];
                bool anyle = false;
                for (I32 i : constrained) {
                    if (y[i] <= 0) {
                        anyle = true;
                        break;
                    }
                }
                if (anyle) rhs(s, s.work, s.t, y);
                read_held(s);
            }
            if (s.h != s.hW || s.k != s.kW || held_moved(s)) form_w(s);

            err = 0.0;
            bool first_failure = true;
            for (;;) {
                const int k = s.k;
                const double h = s.h;
                s.tnew = last ? t_end : s.t + h;
                const double tnew = s.tnew;
                const double ynorm = begin_attempt(s, k);
                if (projected && s.pushed) {
                    std::fill(s.push.begin(), s.push.end(), 0.0);
                    s.pushed = false;
                }
                const double roundoff = (100 * NDF_EPS) * ynorm;
                double dnorm = 0.0;
                int outcome = 0;            // 0 converged, 1 nonfinite, 2 slow
                double prev = 0.0;
                double rho = s.rate;
                const double scale = 1 / s.leading[k - 1];
                newton_its = 0;
                // Whether the system iterated on is the linear one the matrix was formed for: no
                // row held in the matrix, none in any evaluation of this attempt. Where one is, the
                // zero floor makes it linear only in pieces, and the rules of an exact matrix are
                // off: a rate under the floor is not believed, and none is recorded.
                bool linear = !s.w_held;
                for (int it = 1; it <= NDF_NEWTON_MAX; it++) {
                    rhs(s, s.fv, tnew, ynew);
                    if (s.any_held) linear = false;
                    const double* fv = s.fv.data();
                    // the residual, solved for in place: delta
                    if (mass != nullptr) {
                        const double* mv = mass->data();
                        for (int i = 0; i < neq; i++) delta[i] = (h * fv[i] - mv[i] * hist[i]) * scale - mv[i] * d[i];
                    } else {
                        for (int i = 0; i < neq; i++) delta[i] = (h * fv[i] - hist[i]) * scale - d[i];
                    }
                    W.solve_inplace(s.delta);
                    s.nsolves += 1;
                    newton_its = it;
                    const double size = norm_of(newton_weight, s.delta);
                    if (!std::isfinite(size)) {
                        outcome = 1;
                        break;
                    }
                    dnorm = take_correction(s);
                    if (size <= roundoff || size <= NDF_CONVERGED_FLOOR * rtol) {
                        // On a linear model a second correction down at round-off is the rate
                        // measured: ode15s keeps none, and so has every next step iterate twice where
                        // once solves it -- with a constant Jacobian, exact, at the floor of an exact
                        // one; with one that moves with the clock, at the usual floor. (Not on a
                        // nonlinear model, where the next step's rate can be larger: it drifted an
                        // oscillator from the reference.)
                        if (it >= 2 && s.state_free && linear) {
                            rho = py_max(size / prev, s.constant ? NDF_EXACT_RATE_FLOOR : NDF_RATE_FLOOR);
                        }
                        break;
                    }
                    if (it == 1) {
                        const double rate = (s.rate < NDF_RATE_FLOOR && !linear) ? -1.0 : s.rate;
                        if (min_newton <= 1 && rate >= 0 && (rate / (1 - rate)) * size <= NDF_NEWTON_TOL * rtol) break;
                        prev = size;
                        continue;
                    }
                    const double ratio = size / prev;
                    if (ratio >= NDF_RATE_LIMIT) {
                        if (stagnation_tol > 0 && s.fresh && size <= stagnation_tol * rtol) break;
                        outcome = 2;
                        break;
                    }
                    rho = py_max(ratio, (s.constant && s.state_free && linear) ? NDF_EXACT_RATE_FLOOR : NDF_RATE_FLOOR);
                    const double remaining = (rho / (1 - rho)) * size;
                    if (remaining <= NDF_NEWTON_TOL * rtol && it >= min_newton) break;
                    if (it == NDF_NEWTON_MAX ||
                        remaining * std::pow(rho, static_cast<double>(NDF_NEWTON_MAX - it)) > NDF_NEWTON_TOL * rtol) {
                        outcome = 2;
                        break;
                    }
                    prev = size;
                }

                if (outcome != 0) {
                    s.nfailed += 1;
                    if (projected && snap_onto_bound(s, true)) continue;
                    if (!s.fresh) {
                        evaluate_jacobian(s, nullptr);
                        read_held(s);
                        form_w(s);
                        continue;
                    }
                    if (std::fabs(h) <= hmin) {
                        if (outcome == 1 || below_run >= floor_newton_run) throw fail(s, floor_failure(s.t, outcome == 1));
                        below_run += 1;
                        s.nbelowtol += 1;
                        err = rtol;
                        break;
                    }
                    change_step(s, NDF_NEWTON_CUT);
                    last = false;
                    form_w(s);
                    continue;
                }
                if (s.mask_reforms < 1 && released_in_w(s)) {
                    s.mask_reforms += 1;
                    s.nfailed += 1;
                    form_w(s);
                    continue;
                }
                s.rate = rho;

                err = s.error_const[k - 1] * dnorm;
                if (!std::isfinite(err)) throw fail(s, error_nonfinite(s.t));
                bool for_constraint = false;
                // With no state below zero every term of the maximum is +0, and so is the maximum.
                if (projected && sv::any_below_zero(ynew.data(), constrained)) {
                    double worst = 0.0;
                    for (std::size_t q = 0; q < constrained.size(); q++) {
                        const I32 i = constrained[q];
                        const double v = ynew[i] < 0 ? -ynew[i] / threshold[i] : 0.0;
                        worst = q == 0 ? v : jl_max(worst, v);       // numpy's max: NaN wins
                    }
                    if (worst > rtol && worst > err) {
                        err = worst;
                        for_constraint = true;
                    }
                }
                if (err <= rtol) {
                    below_run = 0;
                    break;
                }
                s.nfailed += 1;
                step_fails += 1;
                if (for_constraint && snap_onto_bound(s, false)) continue;
                if (std::fabs(h) <= hmin) {
                    if (below_run >= floor_run) throw fail(s, floor_failure(s.t, false));
                    below_run += 1;
                    s.nbelowtol += 1;
                    break;
                }
                double factor;
                if (first_failure) {
                    first_failure = false;
                    factor = py_max(0.1, NDF_SAFETY * std::pow(rtol / err, 1.0 / (k + 1)));
                    if (k > 1) {
                        const double* ck = D[k].data();
                        double* sm = s.work.data();
                        for (int i = 0; i < neq; i++) sm[i] = ck[i] + d[i];
                        const double err_lower = s.error_const[k - 2] * norm_of(error_weight, s.work);
                        const double lower =
                            err_lower > 0 ? py_max(0.1, NDF_SAFETY_LOWER * std::pow(rtol / err_lower, 1.0 / k)) : sv::INF;
                        if (lower > factor) {
                            s.k = k - 1;
                            factor = py_min(1.0, lower);
                        }
                    }
                } else {
                    factor = 0.5;
                }
                change_step(s, factor);
                last = false;
                form_w(s);
            }

            // --- accepted ------------------------------------------------------------------------------
            s.nsteps += 1;
            {
                const int pos = s.trace_pos;
                s.trace_t[pos] = s.t;
                s.trace_h[pos] = s.h;
                s.trace_k[pos] = s.k;
                s.trace_err[pos] = err;
                s.trace_newton[pos] = newton_its;
                s.trace_failed[pos] = step_fails;
                s.trace_pos = pos == NDF_TRACE_STEPS - 1 ? 0 : pos + 1;
                s.trace_len = std::min(s.trace_len + 1, NDF_TRACE_STEPS);
            }
            step_fails = 0;
            if (static_cast<double>(s.nsteps) > max_steps) throw fail(s, steps_failure(max_steps, s.t));
            if (s.nsteps - stall_step >= stall_window) {
                const bool crawling = std::fabs(s.tnew - stall_t) < span * NDF_STALL_SPAN_FRACTION;
                const bool not_growing = std::fabs(s.h) <= 2 * stall_h;
                if (crawling && not_growing) {
                    throw fail(s, stall_failure(s.tnew, stall_window, span * NDF_STALL_SPAN_FRACTION));
                }
                stall_step = s.nsteps;
                stall_t = s.tnew;
                stall_h = std::fabs(s.h);
            }

            int k = s.k;
            advance(D, k, s.d);
            Vec& y = D[0];
            if (projected) {
                for (std::size_t q = 0; q < constrained.size(); q++) {
                    const I32 i = constrained[q];
                    if (y[i] < 0) {
                        y[i] = 0.0;
                        s.negative += 1;
                        forget(D, i);
                        if (s.followers) follow_onto_zero(s, q, true);
                    }
                }
                const double ah = std::fabs(s.h);
                // Pushes all at zero count nothing (unless a tolerance is below zero).
                if (s.pushed || s.atol_below_zero) {
                    for (std::size_t q = 0; q < constrained.size(); q++) {
                        const I32 i = constrained[q];
                        held[i] += (s.push[q] * ah > atol[i]) ? 1 : 0;
                    }
                }
            }

            if (events != nullptr) {
                const bool hit = sv::ev_locate_crossing(*events, event_work, s.t, vl, s.tnew, y, vr, dense_at, s.dense,
                                                        t_start);
                if (hit) {
                    const double t_e = event_work.t;
                    regrid(s, k, (t_e - s.tnew) / s.h, (t_e - s.t) / s.h);
                    s.h = t_e - s.t;
                    s.hTable = s.h;
                    s.tnew = t_e;
                    s.consecutive = 0;
                    if (projected) {
                        for (std::size_t q = 0; q < constrained.size(); q++) {
                            const I32 i = constrained[q];
                            const double v = y[i];
                            y[i] = v < 0 ? 0.0 : v;
                            if (v < 0 && s.followers) follow_onto_zero(s, q, false);
                        }
                    }
                    if (event_work.values != &vr) vr = *event_work.values;
                    sol.stopped = Stopped{t_e, y, event_work.which};
                    last = true;
                }
                vl = vr;
            }

            const double tnew = s.tnew;
            while (next_out < npts) {
                const double tq = tspan[next_out];
                if (direction * (tnew - tq) < 0) break;
                const Vec* at = &D[0];
                if (!(tq == tnew)) {
                    dense_at(s.dense, tq);
                    at = &s.dense;
                }
                record(tq, *at);
                if (on_output) on_output(tq, *at);
                next_out += 1;
            }
            if (on_accepted) on_accepted(tnew, D[0]);
            if (on_step && (s.nsteps & 15) == 0 && !on_step(tnew, static_cast<long>(s.nsteps))) {
                throw SolverError("aborted", "Aborted", tnew);
            }

            s.t = tnew;
            if (auto_abstol) {
                const Vec& yy = D[0];
                for (int i = 0; i < neq; i++) {
                    const double fl = rtol * std::fabs(yy[i]);
                    if (fl > atol[i]) {
                        atol[i] = fl;
                        threshold[i] = fl / rtol;
                    }
                }
            }
            if (last) break;

            s.consecutive += 1;
            k = s.k;
            if (s.consecutive >= k + 1) {
                int best_k = k;
                double best = allowed(err, k, NDF_SAFETY, rtol);
                if (k > 1) {
                    const double e_lower = s.error_const[k - 2] * norm_of(error_weight, D[k]);
                    const double g = allowed(e_lower, k - 1, NDF_SAFETY_LOWER, rtol);
                    if (g > best) {
                        best = g;
                        best_k = k - 1;
                    }
                }
                if (k < max_order) {
                    const double e_higher = s.error_const[k] * norm_of(error_weight, D[k + 2]);
                    const double g = allowed(e_higher, k + 1, NDF_SAFETY_HIGHER, rtol);
                    if (g > best) {
                        best = g;
                        best_k = k + 1;
                    }
                }
                if (best > 1) {
                    s.k = best_k;
                    s.h *= best;
                    s.consecutive = 0;
                }
            }
            if (!constant) s.fresh = false;
        }
    }

    Json stats = stats_of(s);
    if (projected) {
        Json list = Json::array();
        for (long long v : held) list.push(Json(v));
        stats.set("held", list);
    } else {
        stats.set("held", Json());
    }
    const Json& info = W.info();
    stats.set("sparse", info.get("sparse"));
    stats.set("fill", info.get("fill"));
    stats.set("lu", info.get("lu"));
    stats.set("solver", Json(bdf ? "BDF" : "NDF"));
    sol.end_t = s.t;
    sol.end_y = D[0];
    sol.stats = std::move(stats);
    return sol;
}

}  // namespace

Solution ndf(const RhsFunction& f, const Vec& tspan, const Vec& y0, const NdfOptions& o) {
    const int neq = static_cast<int>(y0.size());
    if (tspan.empty()) throw std::invalid_argument("ndf: the time span is empty");
    Vec own_atol;
    Vec* atol = &own_atol;
    if (o.abstol_vector != nullptr) {
        if (o.abstol_vector->size() != y0.size()) {
            throw std::invalid_argument("ndf: the absolute tolerances are not one per state");
        }
        if (o.auto_abstol) {
            atol = o.abstol_vector;         // raised in place, as the caller's array is in Python
        } else {
            own_atol = *o.abstol_vector;
        }
    } else {
        own_atol.assign(y0.size(), o.abstol);
    }
    const Vec* mass = (o.mass != nullptr && o.mass->size() == y0.size()) ? o.mass : nullptr;
    const int mo = std::max(1, std::min(NDF_MAX_ORDER, static_cast<int>(std::floor(o.max_order + 0.5))));
    const long floor_run = o.below_tol_run
                               ? std::max(0L, static_cast<long>(std::nearbyint(*o.below_tol_run)))
                               : NDF_MAX_BELOW_TOLERANCE;
    const long floor_newton_run = o.below_tol_run ? floor_run : 0;
    // Checked in the Julia package's order: the weight floor, then the rows held with a state.
    Floor floor = weight_floor_of(o.weight_floor, neq);
    const std::vector<I32> held_with = held_with_of(o.held_with, neq);
    return ndf_solve(f, tspan, y0, o.rtol, *atol, o.non_negative, mo, o.bdf, o.hmax, o.h0, o.max_steps,
                     o.error_norm.empty() ? std::string("max") : o.error_norm, o.norm_control, o.jacobian,
                     o.matrix.empty() ? std::string("auto") : o.matrix, floor_run, floor_newton_run,
                     o.stagnation_tol, o.min_newton, o.stall_window, o.events,
                     o.t_start ? *o.t_start : sv::NOT_A_NUMBER, o.hints, o.on_accepted, o.on_output, o.on_step,
                     o.auto_abstol, o.ends_only, mass, o.rows, o.landing, std::move(floor), o.iteration_matrix,
                     held_with);
}

}  // namespace kompartment
