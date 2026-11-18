// The far-field path solved in the Laplace domain (see farfield_laplace.hpp): a port of the Julia
// package's farfield_laplace.jl, operation for operation and in its order.

#include "engine/farfield_laplace.hpp"

#include <algorithm>
#include <bit>
#include <cstring>
#include <limits>

#include "engine/farfield.hpp"
#include "util/jsnum.hpp"

namespace kompartment::lp {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
constexpr double Inf = std::numeric_limits<double>::infinity();

/// Julia's `sqrt` of a Float64: a DomainError below zero (never the NaN the C library gives).
struct JlSqrtDomainError : std::domain_error {
    JlSqrtDomainError() : std::domain_error("sqrt was called with a negative real argument") {}
};
inline double jl_sqrt(double x) {
    if (x < 0) throw JlSqrtDomainError();
    return std::sqrt(x);
}
inline long long jl_int(double f) {
    if (!(f >= -9.223372036854775808e18 && f < 9.223372036854775808e18)) throw JlInexactError();
    return static_cast<long long>(f);
}
inline long long jl_floor_int(double x) { return jl_int(std::floor(x)); }
inline long long jl_ceil_int(double x) { return jl_int(std::ceil(x)); }

inline int low_bit(int mask) { return std::countr_zero(static_cast<unsigned>(mask)); }
inline int high_bit(int mask) { return 31 - std::countl_zero(static_cast<unsigned>(mask)); }

const double* binom_half() {
    static const auto b = [] {
        std::array<double, 260> v{};
        v[0] = 1.0;
        for (int n = 1; n <= 259; n++) v[n] = v[n - 1] * (0.5 - (n - 1)) / n;
        return v;
    }();
    return b.data();
}

constexpr double LP_LINK_FRAC = 0.3;
constexpr double LP_TAYLOR_FRAC = 0.5;
constexpr int LP_NEED_ALL = 0;
constexpr int LP_NEED_COLUMN = 1;
constexpr int LP_NEED_CORNER = 2;
constexpr double LP_VERTEX_BETA = 1.5;
constexpr double LP_SINH_RATIO = 0.1;
constexpr double LP_SINH_STEP = 0.3;
constexpr int LP_CELL_C = 2;
constexpr int LP_CELL_F = 2;
constexpr double LP_CELL_PROBES[5] = {-0.5, -0.25, 0.0, 0.25, 0.5};
constexpr double LP_CELL_COND = 1e6;
constexpr double LP_CELL_PRUNE = 1e-20;
constexpr double LP_CELL_NEGLIGIBLE = 1e-20;
constexpr int LP_CELL_MAX_EVAL = 24000;
const double LP_LN_F = lm_log(static_cast<double>(LP_CELL_F));
const double LP_CELL_SLOPE = 1 / (2 * LP_LN_F);
const double LP_LN_PRUNE = lm_log(LP_CELL_PRUNE);
const double LP_LN2 = lm_log(2.0);

}  // namespace

// --- the C library's functions ----------------------------------------------------------------------

double lm_exp(double x) { return std::exp(x); }
double lm_log(double x) { return std::log(x); }
double lm_log10(double x) { return std::log10(x); }
double lm_sinh(double x) { return std::sinh(x); }
double lm_cosh(double x) { return std::cosh(x); }
double lm_tanh(double x) { return std::tanh(x); }
double lm_tan(double x) { return std::tan(x); }
double lm_asinh(double x) { return std::asinh(x); }

// --- complex arithmetic as the Python engine has it ------------------------------------------------

Cx c_div(Cx a, Cx b) {
    double ar = a.re, ai = a.im, br = b.re, bi = b.im;
    if (std::fabs(br) >= std::fabs(bi)) {
        if (br == 0.0) return LP_CNAN;
        double r = bi / br;
        double d = br + bi * r;
        return {(ar + ai * r) / d, (ai - ar * r) / d};
    }
    double r = br / bi;
    double d = bi + br * r;
    return {(ar * r + ai) / d, (ai * r - ar) / d};
}

Cx c_sqrt(Cx z) {
    double ar = z.re, ai = z.im;
    if (ai == 0) {
        if (ar >= 0) return {jl_sqrt(ar), 0.0};
        if (ar != ar) return LP_CNAN;
        return {0.0, jl_sqrt(-ar)};
    }
    double m = py_hypot(ar, ai);
    if (ar >= 0) {
        double t = jl_sqrt(0.5 * (m + ar));
        return {t, ai / (2 * t)};
    }
    if (m != m) return LP_CNAN;
    double t = jl_sqrt(0.5 * (m - ar));
    return {std::fabs(ai) / (2 * t), ai >= 0 ? t : -t};
}

Cx c_exp(Cx z) {
    double e = lm_exp(z.re);
    double y = z.im;
    if (y - y != 0) return LP_CNAN;
    return {e * lm_cos(y), e * lm_sin(y)};
}

Cx c_tanh(Cx z) {
    double ar = z.re, ai = z.im, sg = 1.0;
    if (ar < 0) {
        ar = -ar;
        ai = -ai;
        sg = -1.0;
    }
    if (ar > 18) {
        double e = 2 * lm_exp(-2 * ar);
        return {sg * (1 - e * lm_cos(2 * ai)), sg * (e * lm_sin(2 * ai))};
    }
    double d = lm_cosh(2 * ar) + lm_cos(2 * ai);
    return {sg * lm_sinh(2 * ar) / d, sg * lm_sin(2 * ai) / d};
}

Cx c_sech2(Cx z) {
    double ar = z.re, ai = z.im;
    if (ar < 0) {
        ar = -ar;
        ai = -ai;
    }
    double e1 = lm_exp(-ar);
    double e2 = e1 * e1;
    Cx w{e2 * lm_cos(2 * ai), -e2 * lm_sin(2 * ai)};
    Cx num{2 * e1 * lm_cos(ai), -2 * e1 * lm_sin(ai)};
    Cx s = c_div(num, r_add(1.0, w));
    return {s.re * s.re - s.im * s.im, 2 * s.re * s.im};
}

double py_log(double x) {
    if (!(x > 0 || std::isnan(x))) throw PyLogDomainError(x);
    return lm_log(x);
}

// --- the path ---------------------------------------------------------------------------------------

LPDD::LPDD(int nmax)
    : z(nmax), f(nmax), sc(nmax, 0.0), cl(nmax, 0), dist(static_cast<std::size_t>(nmax) * nmax, 0.0),
      memo_val(std::size_t{1} << nmax), memo_gen(std::size_t{1} << nmax, 0), cl_mask(nmax, 0), cl_c(nmax),
      cl_ok(nmax, 0), cl_k(nmax, -1), cl_coef(nmax) {}

LPWorkspace::LPWorkspace(int nmax)
    : a(nmax), mz(nmax), tz(nmax), g(nmax), v(nmax), col(nmax, 0.0), L(static_cast<std::size_t>(nmax) * nmax),
      T(static_cast<std::size_t>(nmax) * nmax), F(static_cast<std::size_t>(nmax) * nmax), dd(nmax) {}

std::unique_ptr<LaplacePath> prepare_path(const LPSettings& settings, const LPDecay* decay, int n,
                                          const std::vector<std::string>* names) {
    if (!(n >= 1)) throw LaplacePathError("A path needs at least one species to carry.");
    std::vector<std::string> nm;
    if (names) {
        nm = *names;
    } else {
        for (int k = 1; k <= n; k++) nm.push_back("#" + std::to_string(k));
    }
    auto one = [&](const std::string& key) {
        auto it = settings.single.find(key);
        if (it == settings.single.end()) throw LaplacePathError(key + " must be a number (got None)");
        double v = it->second;
        if (v != v) throw LaplacePathError(key + " must be a number (got " + py_repr(v) + ")");
        return v;
    };
    auto each = [&](const std::string& key) {
        auto it = settings.each.find(key);
        std::vector<double> out(n, 0.0);
        for (int k = 0; k < n; k++) {
            double x;
            if (it == settings.each.end()) {
                auto s = settings.single.find(key);
                x = s == settings.single.end() ? NaN : s->second;
            } else {
                x = it->second[k];
            }
            if (!std::isfinite(x) || x < 0)
                throw LaplacePathError(key + " of " + nm[k] + " must be zero or a positive number (got " + py_repr(x) + ")");
            out[k] = x;
        }
        return out;
    };
    double tw = one("tw");
    double rho = one("rho_m");
    double Pe = one("pe");
    double x0 = one("pen_dep");
    if (!(tw > 0 && std::isfinite(tw)))
        throw LaplacePathError("The travel time TW must be a positive number (got " + py_repr(tw) + ")");
    std::string surface = settings.surface.empty() ? "f" : settings.surface;
    double aw;
    if (surface == "aw") {
        aw = one("aw");
        if (!(aw >= 0 && std::isfinite(aw)))
            throw LaplacePathError("The flow-wetted surface a_w must be zero or positive (got " + py_repr(aw) + ")");
    } else if (surface == "aperture") {
        double delta = one("aperture");
        if (!(delta > 0)) throw LaplacePathError("The fracture aperture must be a positive length (got " + py_repr(delta) + ")");
        aw = 2 / delta;
    } else if (surface == "f") {
        double f0 = one("f");
        if (!(f0 >= 0 && std::isfinite(f0)))
            throw LaplacePathError("The flow-related transport resistance F must be zero or positive (got " + py_repr(f0) + ")");
        aw = f0 / tw;
    } else {
        throw LaplacePathError("Unknown way of giving the wetted surface '" + surface + "'");
    }
    double f = aw * tw;
    if (!(Pe > 0)) throw LaplacePathError("The Peclet number must be greater than zero (got " + py_repr(Pe) + ")");
    if (!(x0 > 0))
        throw LaplacePathError("The depth into the matrix must be a positive length, or Infinity (got " + py_repr(x0) + ")");
    if (!(rho >= 0 && std::isfinite(rho)))
        throw LaplacePathError("The rock density must be zero or positive (got " + py_repr(rho) + ")");
    std::vector<double> kd_f = each("kd_f");
    std::vector<double> eps = each("eps_m");
    std::vector<double> kd_m = each("kd_m");
    std::vector<double> De = each("de_m");
    std::vector<double> Rf(n, 0.0), Rm(n, 0.0);
    std::vector<int> matrix(n, 0);
    for (int k = 0; k < n; k++) {
        Rf[k] = 1 + kd_f[k] * aw;
        Rm[k] = eps[k] + rho * kd_m[k];
        if (aw > 0 && De[k] > 0 && !(Rm[k] > 0))
            throw LaplacePathError("The matrix capacity eps + rho*Kd of " + nm[k] +
                                   " must be greater than zero: a rock with no porosity and no sorption has nothing for it to diffuse into.");
        matrix[k] = (aw > 0 && De[k] > 0) ? 1 : 0;
    }
    std::vector<double> lam(n, 0.0);
    std::vector<std::vector<std::pair<int, double>>> parents(n);
    if (decay) {
        if (static_cast<int>(decay->lam.size()) < n) throw LaplacePathError("The decay table is shorter than the nuclide list.");
        for (int i = 0; i < n; i++) {
            lam[i] = decay->lam[i];
            if (!std::isfinite(lam[i]) || lam[i] < 0)
                throw LaplacePathError("The decay constant of " + nm[i] + " must be zero or positive (got " + py_repr(lam[i]) + ")");
            int o = decay->ioff[i];
            for (int q = 0; q < decay->icnt[i]; q++) {
                int p = decay->ipar[o + q];
                double c = decay->icoef[o + q];
                if (!std::isfinite(c) || c < 0)
                    throw LaplacePathError("The ingrowth of " + nm[i] + " from " + nm[p] + " must be zero or positive (got " + py_repr(c) + ")");
                if (c == 0) continue;
                if (p == i) throw LaplacePathError(nm[i] + " is its own parent.");
                auto had = std::find_if(parents[i].begin(), parents[i].end(), [&](const auto& e) { return e.first == p; });
                if (had != parents[i].end())
                    had->second = had->second + c;
                else
                    parents[i].push_back({p, c});
            }
        }
    }
    std::vector<int> indeg(n, 0);
    std::vector<std::vector<int>> children(n);
    for (int i = 0; i < n; i++)
        for (const auto& [p, c] : parents[i]) {
            children[p].push_back(i);
            indeg[i]++;
        }
    std::vector<int> order;
    std::vector<char> taken(n, 0);
    for (int it = 0; it < n; it++) {
        int pick = -1;
        for (int k = 0; k < n; k++)
            if (!taken[k] && indeg[k] == 0) {
                pick = k;
                break;
            }
        if (pick < 0) break;
        taken[pick] = 1;
        order.push_back(pick);
        for (int c : children[pick]) indeg[c]--;
    }
    if (static_cast<int>(order.size()) < n)
        throw LaplacePathError("The decay network closes on itself, so it has no order to solve it in.");
    std::vector<int> pos(n, 0);
    for (int p = 0; p < n; p++) pos[order[p]] = p;
    std::vector<int> reach(static_cast<std::size_t>(n) * n, 0);
    for (int p = n - 1; p >= 0; p--) {
        int k = order[p];
        reach[static_cast<std::size_t>(k) * n + k] = 1;
        for (int c : children[k])
            for (int l = 0; l < n; l++)
                if (reach[static_cast<std::size_t>(c) * n + l] != 0) reach[static_cast<std::size_t>(k) * n + l] = 1;
    }
    for (int i = 0; i < n; i++)
        for (const auto& [p, c] : parents[i])
            if (matrix[p] != matrix[i]) {
                const std::string& inside = matrix[p] != 0 ? nm[p] : nm[i];
                const std::string& outside = matrix[p] != 0 ? nm[i] : nm[p];
                throw LaplacePathError(outside + " does not diffuse into the matrix (De = 0) while " + inside + ", which it decays " +
                                       (matrix[p] != 0 ? "from" : "into") + ", does: give it a small De, or use the discretised path.");
            }
    bool inf_pe = !std::isfinite(Pe);
    if (inf_pe)
        for (int k = 0; k < n; k++)
            if (matrix[k] == 0)
                throw LaplacePathError("Plug flow (Pe = Infinity) needs matrix diffusion for every nuclide: without it " + nm[k] +
                                       " leaves as a pulse with no width at all.");
    int max_block = 1;
    for (int j = 0; j < n; j++)
        for (int i = 0; i < n; i++) {
            if (i == j || reach[static_cast<std::size_t>(j) * n + i] == 0) continue;
            int m = 0;
            for (int k = 0; k < n; k++)
                if (reach[static_cast<std::size_t>(j) * n + k] != 0 && reach[static_cast<std::size_t>(k) * n + i] != 0) m++;
            if (m > LP_MAX_BLOCK)
                throw LaplacePathError(std::to_string(m) + " nuclides lie on the decay paths from " + nm[j] + " to " + nm[i] + "; at most " +
                                       std::to_string(LP_MAX_BLOCK) + " can be solved together.");
            max_block = std::max(max_block, m);
        }
    auto path = std::make_unique<LaplacePath>();
    path->n = n;
    path->names = nm;
    path->tw = tw;
    path->f = f;
    path->Pe = Pe;
    path->inf_pe = inf_pe;
    path->aw = aw;
    path->x0 = x0;
    path->inf_x0 = !std::isfinite(x0);
    path->rho = rho;
    path->lam = lam;
    path->Rf = Rf;
    path->Rm = Rm;
    path->De = De;
    path->matrix = matrix;
    path->parents = parents;
    path->order = order;
    path->pos = pos;
    path->reach = reach;
    path->max_block = max_block;
    path->ws = std::make_unique<LPWorkspace>(max_block);
    return path;
}

// --- the two scalar functions, their Taylor series and length scales ---------------------------------

Cx tau_at(const LaplacePath& path, Cx z) {
    Cx u = c_sqrt(z);
    if (path.inf_x0) return u;
    return c_mul(u, c_tanh(r_mul(path.x0, u)));
}

double tau_scale(const LaplacePath& path, Cx z) {
    double zr = z.re, zi = z.im;
    double sc = py_hypot(zr, zi);
    if (!path.inf_x0) {
        double a = LP_PI / path.x0;
        long long n0 = 0;
        if (zr < 0) n0 = std::max(0LL, jl_floor_int(jl_sqrt(-zr) / a - 0.5));
        for (long long n = std::max(0LL, n0 - 1); n <= n0 + 1; n++) {
            double zp = -((n + 0.5) * a) * ((n + 0.5) * a);
            double d = py_hypot(zr - zp, zi);
            if (d < sc) sc = d;
        }
    }
    return sc;
}

Cx phi_at(const LaplacePath& path, Cx g) {
    double tw = path.tw;
    if (path.inf_pe) return {-tw * g.re, -tw * g.im};
    double B = 4 * tw / path.Pe;
    Cx S = c_sqrt({1 + B * g.re, B * g.im});
    return c_div({-2 * tw * g.re, -2 * tw * g.im}, {1 + S.re, S.im});
}

namespace {

/// The fracture's part of member p's g at s, less d s when the pair's transform has its delay taken out.
inline Cx g_fracture(const LPBlock& blk, int p, double sr, double si, double d) {
    double rf = blk.Rf[p];
    if (d > 0) {
        double e = rf - d;
        return {rf * blk.lam[p] + e * sr, e * si};
    }
    return {(sr + blk.lam[p]) * rf, si * rf};
}

}  // namespace

double h_scale(const LaplacePath& path, Cx g) {
    double tw = path.tw;
    if (path.inf_pe) return 1 / tw;
    double B = 4 * tw / path.Pe;
    double S = jl_sqrt(py_hypot(1 + B * g.re, B * g.im));
    return ff_min(S / tw, S * S / B);
}

std::vector<Cx> sqrt_series(Cx A, Cx B, int K) {
    const double* binom = binom_half();
    Cx s0 = c_sqrt(A);
    Cx q = c_div(B, A);
    double qr = q.re, qi = q.im, pr = s0.re, pi_ = s0.im;
    std::vector<Cx> out(K + 1);
    for (int n = 0; n <= K; n++) {
        out[n] = {binom[n] * pr, binom[n] * pi_};
        double t = pr * qr - pi_ * qi;
        pi_ = pr * qi + pi_ * qr;
        pr = t;
    }
    return out;
}

std::vector<Cx> tau_series(const LaplacePath& path, Cx c, int K) {
    std::vector<Cx> s1 = sqrt_series(c, {1.0, 0.0}, K);
    if (path.inf_x0) return s1;
    double x0 = path.x0;
    std::vector<Cx> s2(K + 1), s3(K + 1);
    s2[0] = c_tanh({x0 * s1[0].re, x0 * s1[0].im});
    s3[0] = c_sech2({x0 * s1[0].re, x0 * s1[0].im});
    for (int n = 1; n <= K; n++) {
        double ar = 0.0, ai = 0.0;
        for (int k = 1; k <= n; k++) {
            double vr = k * x0 * s1[k].re;
            double vi = k * x0 * s1[k].im;
            Cx q = s3[n - k];
            ar += vr * q.re - vi * q.im;
            ai += vr * q.im + vi * q.re;
        }
        s2[n] = {ar / n, ai / n};
        double br = 0.0, bi = 0.0;
        for (int k = 0; k <= n; k++) {
            Cx a = s2[k], b = s2[n - k];
            br += a.re * b.re - a.im * b.im;
            bi += a.re * b.im + a.im * b.re;
        }
        s3[n] = {-br, -bi};
    }
    std::vector<Cx> out(K + 1);
    for (int n = 0; n <= K; n++) {
        double ar = 0.0, ai = 0.0;
        for (int k = 0; k <= n; k++) {
            Cx a = s1[k], b = s2[n - k];
            ar += a.re * b.re - a.im * b.im;
            ai += a.re * b.im + a.im * b.re;
        }
        out[n] = {ar, ai};
    }
    return out;
}

std::vector<Cx> h_series(const LaplacePath& path, Cx c, double E, int K) {
    double tw = path.tw;
    std::vector<Cx> s1;
    if (path.inf_pe) {
        s1.assign(K + 1, Cx{});
        s1[0] = {-tw * c.re, -tw * c.im};
        if (K >= 1) s1[1] = {-tw, 0.0};
    } else {
        double B = 4 * tw / path.Pe;
        double half = path.Pe / 2;
        s1 = sqrt_series({1 + B * c.re, B * c.im}, {B, 0.0}, K);
        for (int n = 1; n <= K; n++) s1[n] = {s1[n].re * -half, s1[n].im * -half};
        s1[0] = phi_at(path, c);
    }
    std::vector<Cx> out(K + 1);
    out[0] = c_exp({s1[0].re + E, s1[0].im});
    for (int n = 1; n <= K; n++) {
        double ar = 0.0, ai = 0.0;
        for (int k = 1; k <= n; k++) {
            double pr = k * s1[k].re;
            double pi_ = k * s1[k].im;
            Cx h = out[n - k];
            ar += pr * h.re - pi_ * h.im;
            ai += pr * h.im + pi_ * h.re;
        }
        out[n] = {ar / n, ai / n};
    }
    return out;
}

std::vector<Cx> exp_series(double t, Cx c, int K) {
    std::vector<Cx> out(K + 1);
    Cx e = c_exp({-t * c.re, -t * c.im});
    double r = e.re, i = e.im;
    out[0] = e;
    for (int n = 1; n <= K; n++) {
        r = r * (-t / n);
        i = i * (-t / n);
        out[n] = {r, i};
    }
    return out;
}

// --- divided differences over subsets of points, robust for clusters -----------------------------

namespace {

double dd_scale(const LaplacePath& path, const LPDD& dd, Cx z) {
    if (dd.kind == 0) return tau_scale(path, z);
    if (dd.kind == 1) return h_scale(path, z);
    return 1 / dd.t;
}

std::vector<Cx> dd_series(const LaplacePath& path, const LPDD& dd, Cx c, int K) {
    if (dd.kind == 0) return tau_series(path, c, K);
    if (dd.kind == 1) return h_series(path, c, dd.E, K);
    return exp_series(dd.t, c, K);
}

bool dd_setup(const LaplacePath& path, LPDD& dd, int n) {
    dd.n = n;
    if (++dd.gen == 0) {
        std::fill(dd.memo_gen.begin(), dd.memo_gen.end(), 0u);
        dd.gen = 1;
    }
    const std::vector<Cx>& z = dd.z;
    for (int k = 0; k < n; k++) {
        dd.sc[k] = dd_scale(path, dd, z[k]);
        dd.cl[k] = k;
    }
    bool anyc = false;
    for (int a = 0; a < n; a++)
        for (int b = a + 1; b < n; b++) {
            double dx = z[a].re - z[b].re;
            double dy = z[a].im - z[b].im;
            double d = jl_sqrt(dx * dx + dy * dy);
            dd.dist[a * n + b] = d;
            dd.dist[b * n + a] = d;
            if (d <= LP_LINK_FRAC * ff_min(dd.sc[a], dd.sc[b])) {
                anyc = true;
                int ca = dd.cl[a], cb = dd.cl[b];
                if (ca != cb)
                    for (int k = 0; k < n; k++)
                        if (dd.cl[k] == cb) dd.cl[k] = ca;
            }
        }
    dd.ncl = 0;
    if (!anyc) return false;
    std::vector<int> seen(n, -1);
    for (int k = 0; k < n; k++) {
        int root = dd.cl[k];
        if (seen[root] < 0) {
            seen[root] = dd.ncl;
            dd.cl_mask[dd.ncl] = 0;
            dd.ncl++;
        }
        int c = seen[root];
        dd.cl[k] = c;
        dd.cl_mask[c] |= 1 << k;
    }
    for (int c = 0; c < dd.ncl; c++) {
        dd.cl_ok[c] = 0;
        dd.cl_k[c] = -1;
    }
    return true;
}

std::optional<Cx> dd_taylor(const LaplacePath& path, LPDD& dd, int mask, int cnt, int c) {
    int m = cnt - 1;
    if (dd.cl_k[c] < 0) {
        int cm = dd.cl_mask[c];
        double cr = 0.0, ci = 0.0;
        int k0 = 0;
        for (int k = 0; k < dd.n; k++)
            if (cm & (1 << k)) {
                cr += dd.z[k].re;
                ci += dd.z[k].im;
                k0++;
            }
        cr /= k0;
        ci /= k0;
        double rad = 0.0;
        for (int k = 0; k < dd.n; k++)
            if (cm & (1 << k)) rad = ff_max(rad, py_hypot(dd.z[k].re - cr, dd.z[k].im - ci));
        double sc = dd_scale(path, dd, {cr, ci});
        double q = rad / sc;
        dd.cl_c[c] = {cr, ci};
        if (!(q <= LP_TAYLOR_FRAC)) {
            dd.cl_ok[c] = 0;
            dd.cl_k[c] = 0;
            return std::nullopt;
        }
        dd.cl_ok[c] = 1;
        int mmax = k0 - 1;
        int extra = 2;
        if (q > 0) {
            double term = 1.0;
            extra = 1;
            while (extra < 240) {
                term *= q * (extra + mmax) / extra;
                if (term < 1e-17 && extra > 2) break;
                extra++;
            }
        }
        int K = std::min(255, mmax + extra + 2);
        dd.cl_k[c] = K;
        dd.cl_coef[c] = dd_series(path, dd, {cr, ci}, K);
    }
    if (!dd.cl_ok[c]) return std::nullopt;
    int K = dd.cl_k[c];
    Cx cc = dd.cl_c[c];
    int L = K - m;
    std::vector<Cx> h(L + 1);
    h[0] = {1.0, 0.0};
    int mm = mask;
    while (mm != 0) {
        int k = low_bit(mm);
        Cx w = dd.z[k] - cc;
        double wr = w.re, wi = w.im;
        for (int j = 1; j <= L; j++) {
            Cx p = h[j - 1];
            h[j] = {h[j].re + (wr * p.re - wi * p.im), h[j].im + (wr * p.im + wi * p.re)};
        }
        mm &= mm - 1;
    }
    const std::vector<Cx>& f = dd.cl_coef[c];
    double sr = 0.0, si = 0.0;
    for (int j = L; j >= 0; j--) {
        Cx a = f[m + j], b = h[j];
        sr += a.re * b.re - a.im * b.im;
        si += a.re * b.im + a.im * b.re;
    }
    return Cx{sr, si};
}

Cx dd_get(const LaplacePath& path, LPDD& dd, int mask) {
    if (dd.memo_gen[mask] == dd.gen) return dd.memo_val[mask];
    int n = dd.n;
    int lo = low_bit(mask);
    int hi = high_bit(mask);
    Cx val;
    if (lo == hi) {
        val = dd.f[lo];
    } else {
        int c0 = dd.ncl != 0 ? dd.cl[lo] : -1;
        int cnt = 0;
        int m = mask;
        while (m != 0) {
            cnt++;
            if (c0 >= 0 && dd.cl[low_bit(m)] != c0) c0 = -1;
            m &= m - 1;
        }
        std::optional<Cx> t = c0 >= 0 ? dd_taylor(path, dd, mask, cnt, c0) : std::nullopt;
        if (t) {
            val = *t;
        } else {
            int a = lo, b = hi;
            if (dd.ncl != 0 && dd.cl[a] == dd.cl[b]) {
                double bd = -1.0;
                int bb = -1;
                m = mask;
                while (m != 0) {
                    int k = low_bit(m);
                    if (dd.cl[k] != dd.cl[a] && dd.dist[a * n + k] > bd) {
                        bd = dd.dist[a * n + k];
                        bb = k;
                    }
                    m &= m - 1;
                }
                if (bb < 0) {
                    m = mask;
                    while (m != 0) {
                        int p = low_bit(m);
                        int m2 = m & (m - 1);
                        while (m2 != 0) {
                            int q = low_bit(m2);
                            if (dd.dist[p * n + q] > bd) {
                                bd = dd.dist[p * n + q];
                                a = p;
                                bb = q;
                            }
                            m2 &= m2 - 1;
                        }
                        m &= m - 1;
                    }
                }
                b = bb;
            }
            Cx x = dd_get(path, dd, mask & ~(1 << a));
            Cx y = dd_get(path, dd, mask & ~(1 << b));
            val = c_div(x - y, dd.z[b] - dd.z[a]);
        }
    }
    dd.memo_val[mask] = val;
    dd.memo_gen[mask] = dd.gen;
    return val;
}

// --- functions of lower-triangular matrices ------------------------------------------------------

void path_visit(const LaplacePath& path, LPWorkspace& ws, int m, const std::vector<Cx>& L, std::vector<Cx>& F, int q, int k, int mask,
                Cx prod, bool corner_only) {
    if (k != q && (!corner_only || k == m - 1)) {
        Cx v = dd_get(path, ws.dd, mask);
        F[k * m + q] = F[k * m + q] + Cx{prod.re * v.re - prod.im * v.im, prod.re * v.im + prod.im * v.re};
    }
    for (int l = k + 1; l < m; l++) {
        Cx e = L[l * m + k];
        if (c_iszero(e)) continue;
        path_visit(path, ws, m, L, F, q, l, mask | (1 << l), {prod.re * e.re - prod.im * e.im, prod.re * e.im + prod.im * e.re}, corner_only);
    }
}

void tri_fun(const LaplacePath& path, LPWorkspace& ws, int m, const std::vector<Cx>& L, std::vector<Cx>& F, int need) {
    LPDD& dd = ws.dd;
    for (int p = 0; p < m; p++) F[p * m + p] = dd.f[p];
    if (m == 1) return;
    if (!dd_setup(path, dd, m)) {
        const std::vector<Cx>& z = dd.z;
        for (int d = 1; d < m; d++)
            for (int q = 0; q <= m - d - 1; q++) {
                int p = q + d;
                Cx l = L[p * m + q];
                Cx e = F[p * m + p] - F[q * m + q];
                double ar = l.re * e.re - l.im * e.im;
                double ai = l.re * e.im + l.im * e.re;
                for (int k = q + 1; k <= p - 1; k++) {
                    Cx g1 = L[p * m + k], f1 = F[k * m + q], f2 = F[p * m + k], g2 = L[k * m + q];
                    ar += f2.re * g2.re - f2.im * g2.im - (g1.re * f1.re - g1.im * f1.im);
                    ai += f2.re * g2.im + f2.im * g2.re - (g1.re * f1.im + g1.im * f1.re);
                }
                F[p * m + q] = c_div({ar, ai}, z[p] - z[q]);
            }
        return;
    }
    ws.clustered++;
    if (need == LP_NEED_ALL) {
        for (int p = 1; p < m; p++)
            for (int q = 0; q < p; q++) F[p * m + q] = {0.0, 0.0};
        for (int q = 0; q <= m - 2; q++) path_visit(path, ws, m, L, F, q, q, 1 << q, {1.0, 0.0}, false);
    } else {
        for (int p = 1; p < m; p++) F[p * m] = {0.0, 0.0};
        path_visit(path, ws, m, L, F, 0, 0, 1, {1.0, 0.0}, need == LP_NEED_CORNER);
    }
}

}  // namespace

// --- one pair's transform ----------------------------------------------------------------------

LPBlock* block_of(LaplacePath& path, int i, int j) {
    int key = i * path.n + j;
    auto it = path.blocks.find(key);
    if (it != path.blocks.end()) return it->second.get();
    std::unique_ptr<LPBlock> blk;
    if (path.reaches(j, i)) {
        std::vector<int> S;
        for (int k : path.order)
            if (path.reaches(j, k) && path.reaches(k, i)) S.push_back(k);
        int m = static_cast<int>(S.size());
        std::unordered_map<int, int> loc;
        for (int p = 0; p < m; p++) loc[S[p]] = p;
        std::vector<double> A(static_cast<std::size_t>(m) * m, 0.0);
        for (int p = 0; p < m; p++)
            for (const auto& [par, c] : path.parents[S[p]]) {
                auto q = loc.find(par);
                if (q == loc.end()) continue;
                A[p * m + q->second] -= c;
            }
        blk = std::make_unique<LPBlock>();
        blk->i = i;
        blk->j = j;
        blk->S = S;
        blk->m = m;
        blk->A = A;
        for (int k : S) {
            blk->lam.push_back(path.lam[k]);
            blk->Rf.push_back(path.Rf[k]);
            blk->Rm.push_back(path.Rm[k]);
            blk->De.push_back(path.De[k]);
        }
        double rmin = blk->Rf[0];
        for (int p = 1; p < m; p++)
            if (blk->Rf[p] < rmin) rmin = blk->Rf[p];
        blk->Rmin = rmin;
        blk->matrix = path.matrix[S[0]] == 1;
        blk->s0 = NaN;
    }
    LPBlock* raw = blk.get();
    path.blocks[key] = std::move(blk);
    return raw;
}

Cx eval_block(LaplacePath& path, LPWorkspace& ws, LPBlock& blk, Cx s, int kind) {
    int m = blk.m;
    double aw = path.aw;
    ws.evaluations++;
    double delay = (kind != LP_INVENTORY && path.inf_pe) ? blk.Rmin : 0.0;
    double phi_max = -Inf;
    const std::vector<double>& lam = blk.lam;
    const std::vector<double>& Rf = blk.Rf;
    const std::vector<double>& De = blk.De;
    for (int p = 0; p < m; p++) {
        Cx a{s.re + lam[p], s.im};
        ws.a[p] = a;
        Cx g0 = g_fracture(blk, p, s.re, s.im, delay);
        double gr = g0.re, gi = g0.im;
        if (blk.matrix) {
            double fm = blk.Rm[p] / De[p];
            Cx mz{fm * a.re, fm * a.im};
            ws.mz[p] = mz;
            Cx tz = tau_at(path, mz);
            ws.tz[p] = tz;
            gr += aw * De[p] * tz.re;
            gi += aw * De[p] * tz.im;
        }
        Cx g{gr, gi};
        ws.g[p] = g;
        Cx ph = phi_at(path, g);
        if (ph.re > phi_max) phi_max = ph.re;
    }
    double E = std::isfinite(phi_max) ? -phi_max : 0.0;
    std::vector<Cx>& L = ws.L;
    LPDD& dd = ws.dd;
    const std::vector<double>& A = blk.A;
    if (m > 1) {
        if (blk.matrix) {
            dd.kind = 0;
            for (int p = 0; p < m; p++) {
                dd.z[p] = ws.mz[p];
                dd.f[p] = ws.tz[p];
                for (int q = 0; q < p; q++) L[p * m + q] = {A[p * m + q] * blk.Rm[q] / De[p], 0.0};
            }
            tri_fun(path, ws, m, L, ws.T, LP_NEED_ALL);
            const std::vector<Cx>& T = ws.T;
            for (int p = 1; p < m; p++) {
                double c = aw * De[p];
                for (int q = 0; q < p; q++) {
                    Cx t = T[p * m + q];
                    L[p * m + q] = {A[p * m + q] * Rf[q] + c * t.re, c * t.im};
                }
            }
        } else {
            for (int p = 1; p < m; p++)
                for (int q = 0; q < p; q++) L[p * m + q] = {A[p * m + q] * Rf[q], 0.0};
        }
    }
    dd.kind = 1;
    dd.E = E;
    for (int p = 0; p < m; p++) {
        dd.z[p] = ws.g[p];
        Cx ph = phi_at(path, ws.g[p]);
        dd.f[p] = c_exp({ph.re + E, ph.im});
    }
    std::vector<Cx>& F = ws.F;
    tri_fun(path, ws, m, L, F, kind == LP_RELEASE ? LP_NEED_CORNER : LP_NEED_COLUMN);
    if (kind == LP_RELEASE) {
        ws.E = E;
        return F[(m - 1) * m];
    }
    double EK, c0, c1;
    if (kind == LP_DECAYED) {
        EK = E;
        c0 = 0.0;
        c1 = -1.0;
    } else {
        EK = E < 0 ? E : 0.0;
        c0 = lm_exp(EK);
        c1 = lm_exp(EK - E);
    }
    std::vector<Cx>& v = ws.v;
    for (int p = 0; p < m; p++) {
        Cx fp = F[p * m];
        double wr = (p == 0 ? c0 : 0.0) - c1 * fp.re;
        double wi = -c1 * fp.im;
        for (int q = 0; q < p; q++) {
            double a = A[p * m + q];
            if (a != 0) {
                wr -= a * v[q].re;
                wi -= a * v[q].im;
            }
        }
        v[p] = c_div({wr, wi}, ws.a[p]);
    }
    ws.E = EK;
    return v[m - 1];
}

Cx lp_transfer(LaplacePath& path, double sr, double si, int i, int j) {
    LPBlock* blk = block_of(path, i, j);
    if (!blk) return {0.0, 0.0};
    Cx v = eval_block(path, *path.ws, *blk, {sr, si}, LP_RELEASE);
    double lr = -path.ws->E - (path.inf_pe ? path.tw * blk->Rmin * sr : 0.0);
    double li = path.inf_pe ? -path.tw * blk->Rmin * si : 0.0;
    Cx e = c_exp({lr, li});
    return {v.re * e.re - v.im * e.im, v.re * e.im + v.im * e.re};
}

std::vector<double> transfer_at_zero(LaplacePath& path) {
    int n = path.n;
    std::vector<double> out(static_cast<std::size_t>(n) * n, 0.0);
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++) {
            if (!block_of(path, i, j)) continue;
            double v = lp_transfer(path, 0.0, 0.0, i, j).re;
            if (!std::isfinite(v)) v = lp_transfer(path, 1e-300, 0.0, i, j).re;
            out[i * n + j] = v;
        }
    return out;
}

// --- numerical inversion -------------------------------------------------------------------------

namespace {

double tau_real(const LaplacePath& path, double z) {
    if (z >= 0) {
        double u = jl_sqrt(z);
        return path.inf_x0 ? u : u * lm_tanh(path.x0 * u);
    }
    double u = jl_sqrt(-z);
    return path.inf_x0 ? NaN : -u * lm_tan(path.x0 * u);
}

double off_lambda(const LPBlock& blk, double s, double gap) {
    for (int it = 0; it <= blk.m; it++) {
        bool moved = false;
        for (int p = 0; p < blk.m; p++)
            if (std::fabs(s + blk.lam[p]) < gap) {
                s = -blk.lam[p] + gap;
                moved = true;
            }
        if (!moved) break;
    }
    return s;
}

using Pt = std::pair<double, double>;
inline double d_of(const Pt& a, const Pt& b) { return -(b.second - a.second) / (b.first - a.first); }

LPAxis real_axis(LaplacePath& path, LPWorkspace& ws, LPBlock& blk, int kind, double shift, double t_lo, double t_hi) {
    double s0 = singularity(path, blk, kind);
    double fac = py_pow(10.0, 1.0 / 8);
    auto psi_at = [&](double s) {
        double at = kind == LP_INVENTORY ? off_lambda(blk, s, 1e-7 * (s - s0)) : s;
        Cx v = eval_block(path, ws, blk, {at, 0.0}, kind);
        double F = v.re;
        return (F > 0 && std::isfinite(F)) ? py_log(F) - ws.E : -Inf;
    };
    double x0 = ff_max(std::fabs(s0), 0.0) + 1 / t_hi;
    std::vector<Pt> up, dn;
    double wmax = -Inf;
    double x = x0;
    for (int it = 0; it < 800; it++) {
        double p = psi_at(s0 + x);
        up.push_back({s0 + x, p});
        if (!std::isfinite(p) || x > 1e12 / t_lo) break;
        std::size_t m = up.size();
        if (m >= 2) {
            const Pt& a = up[m - 2];
            const Pt& b = up[m - 1];
            double w = 0.5 * (a.first + b.first) * d_of(a, b) + 0.5 * (a.second + b.second);
            if (w > wmax) wmax = w;
            if (w < wmax - 120) break;
        }
        x *= fac;
    }
    Pt prev = up[0];
    double d_prev = up.size() > 1 ? d_of(up[0], up[1]) : 0.0;
    x = x0 / fac;
    for (int it = 0; it < 800; it++) {
        double s = s0 + x;
        if (!(s > s0)) break;
        double p = psi_at(s);
        if (!std::isfinite(p)) break;
        double D = d_of({s, p}, prev);
        if (!(D > d_prev)) break;
        dn.push_back({s, p});
        double w = 0.5 * (s + prev.first) * D + 0.5 * (p + prev.second);
        if (w > wmax) wmax = w;
        prev = {s, p};
        d_prev = D;
        if (D > 10 * t_hi || x < 1e-13 * ff_max(std::fabs(s0), 1 / t_hi) || w < wmax - 120) break;
        x /= fac;
    }
    std::vector<Pt> pts(dn.rbegin(), dn.rend());
    pts.insert(pts.end(), up.begin(), up.end());
    std::vector<double> extra;
    double e_hi = ff_max(pts.back().first, 0.0);
    double e_left = 0.5 * std::fabs(s0);
    double e = 1 / t_hi;
    while (e < ff_max(e_hi, e_left)) {
        if (e < e_hi) extra.push_back(e);
        if (e < e_left) extra.push_back(-e);
        e *= fac;
    }
    if (!extra.empty()) {
        std::vector<double> have;
        for (const Pt& q : pts) have.push_back(q.first);
        double lo0 = have[0];
        auto near = [&](double a, double b) { return std::fabs(a - b) < 1e-6 * ff_max(ff_max(std::fabs(a), std::fabs(b)), 1 / t_hi); };
        for (double ex : extra) {
            if (!(ex > lo0) || std::any_of(have.begin(), have.end(), [&](double h) { return near(h, ex); })) continue;
            double pv = psi_at(ex);
            if (std::isfinite(pv)) pts.push_back({ex, pv});
        }
        std::stable_sort(pts.begin(), pts.end(), [](const Pt& a, const Pt& b) { return a.first < b.first; });
        std::vector<Pt> kept{pts[0]};
        for (std::size_t k = 1; k < pts.size(); k++) {
            double Dn = d_of(kept.back(), pts[k]);
            if (!(Dn > 0) || (kept.size() >= 2 && !(Dn < d_of(kept[kept.size() - 2], kept.back())))) continue;
            kept.push_back(pts[k]);
        }
        pts = std::move(kept);
    }
    for (int it = 0; it < 14; it++) {
        if (pts.size() >= 4000) break;
        std::vector<Pt> out{pts[0]};
        bool added = false;
        std::size_t np_ = pts.size();
        for (std::size_t k = 0; k + 1 < np_; k++) {
            const Pt a = pts[k];
            const Pt b = pts[k + 1];
            double Dk = d_of(a, b);
            double Dl = k > 0 ? d_of(pts[k - 1], a) : NaN;
            double Dr = k + 2 < np_ ? d_of(b, pts[k + 2]) : NaN;
            double drop = ff_max(std::isfinite(Dl) ? Dl - Dk : 0.0, std::isfinite(Dr) ? Dk - Dr : 0.0);
            double w = 0.5 * (a.first + b.first) * Dk + 0.5 * (a.second + b.second);
            if (drop * (b.first - a.first) > 1 && w > wmax - 80) {
                double s_mid = s0 + jl_sqrt((a.first - s0) * (b.first - s0));
                if (a.first < s_mid && s_mid < b.first) {
                    double p = psi_at(s_mid);
                    if (std::isfinite(p)) {
                        out.push_back({s_mid, p});
                        added = true;
                    }
                }
            }
            out.push_back(b);
        }
        pts = std::move(out);
        if (!added) break;
    }
    std::size_t K = pts.size();
    LPAxis ax;
    ax.blk = &blk;
    ax.kind = kind;
    ax.shift = shift;
    ax.s0 = s0;
    for (const Pt& q : pts) {
        ax.s.push_back(q.first);
        ax.psi.push_back(q.second);
    }
    std::size_t K1 = K > 0 ? K - 1 : 0;
    ax.sm.assign(K1, 0.0);
    ax.D.assign(K1, 0.0);
    for (std::size_t k = 0; k + 1 < K; k++) {
        ax.sm[k] = s0 + jl_sqrt((ax.s[k] - s0) * (ax.s[k + 1] - s0));
        ax.D[k] = (std::isfinite(ax.psi[k + 1]) && std::isfinite(ax.psi[k])) ? -(ax.psi[k + 1] - ax.psi[k]) / (ax.s[k + 1] - ax.s[k]) : NaN;
    }
    ax.tLo = NaN;
    return ax;
}

}  // namespace

double singularity(LaplacePath& path, LPBlock& blk, int kind) {
    if (kind == LP_DECAYED) {
        double s0 = singularity(path, blk);
        for (int p = 0; p < blk.m; p++)
            if (-blk.lam[p] > s0) s0 = -blk.lam[p];
        return s0;
    }
    if (blk.s0 == blk.s0) return blk.s0;
    double s0 = -Inf;
    for (int p = 0; p < blk.m; p++) {
        double lam = blk.lam[p];
        double Rf = blk.Rf[p];
        double sk;
        if (!blk.matrix) {
            sk = path.inf_pe ? -Inf : -lam - path.Pe / (4 * path.tw * Rf);
        } else if (path.inf_x0) {
            sk = -lam;
        } else {
            double f = blk.Rm[p] / blk.De[p];
            double pole = -lam - (LP_PI / (2 * path.x0)) * (LP_PI / (2 * path.x0)) / f;
            if (path.inf_pe) {
                sk = pole;
            } else {
                double gs = -path.Pe / (4 * path.tw);
                double a = pole, b = -lam;
                int it = 0;
                while (it < 200 && b - a > 1e-15 * ff_max(std::fabs(a), std::fabs(b))) {
                    double c = 0.5 * (a + b);
                    double g = (c + lam) * Rf + path.aw * blk.De[p] * tau_real(path, f * (c + lam));
                    if (g > gs)
                        b = c;
                    else
                        a = c;
                    it++;
                }
                sk = b;
            }
        }
        if (sk > s0) s0 = sk;
    }
    blk.s0 = s0;
    return s0;
}

std::optional<LPSaddle> saddle_at(const LPAxis& ax, double t) {
    const std::vector<double>& D = ax.D;
    const std::vector<double>& sm = ax.sm;
    int K = static_cast<int>(D.size());
    double s0 = ax.s0;
    if (K < 2) return std::nullopt;
    int k = 0;
    while (k < K && !(D[k] <= t)) {
        if (!std::isfinite(D[k]) && k > 0) break;
        k++;
    }
    if (k == 0) {
        double psi2 = (D[0] - D[1]) / (sm[1] - sm[0]);
        return LPSaddle{sm[0], psi2, sm[0] * t + ax.psi[0], true, false};
    }
    if (k >= K || !std::isfinite(D[k])) return LPSaddle{sm[std::min(k, K) - 1], NaN, -Inf, false, true};
    int a = k - 1, b = k;
    double la = py_log(D[a]);
    double lb = py_log(D[b]);
    double f = (la - py_log(t)) / (la - lb);
    double xa = sm[a] - s0;
    double xb = sm[b] - s0;
    double ss = s0 + xa * py_pow(xb / xa, f);
    double psi2 = (D[a] - D[b]) / (sm[b] - sm[a]);
    double psi = ax.psi[b] + (ax.s[b] - ss) * 0.5 * (t + D[b]);
    return LPSaddle{ss, psi2, ss * t + psi, false, false};
}

namespace {

/// An inversion's sums: the response and its first two derivatives, with what they say of themselves.
struct LPAcc {
    double h = 0, dh = 0, d2 = 0, abs = 0;
    bool bad = false, regrow = false, cut = false;
    double stop = Inf;
    explicit LPAcc(double s = Inf) : stop(s) {}
};

const LPInv LP_ZERO{0.0, 0.0, 0.0, 0.0, 1.0, false, false};
const LPInv LP_FAILED{NaN, NaN, NaN, Inf, Inf, false, false};

double parabola_term(LaplacePath& path, LPWorkspace& ws, LPAxis& ax, double t, double ss, double kappa, double Y, double jac, double wgt,
                     LPAcc& acc) {
    double sr = ss - kappa * Y * Y;
    double si = Y;
    Cx F = eval_block(path, ws, *ax.blk, {sr, si}, ax.kind);
    double ex = t * sr - ws.E;
    if (ex > 700) {
        acc.bad = true;
        return Inf;
    }
    if (ex < -740 || c_iszero(F)) return 0.0;
    Cx e = c_exp({ex, t * si});
    double ar = e.re * F.re - e.im * F.im;
    double ai = e.re * F.im + e.im * F.re;
    double q = 2 * kappa * Y;
    double zr = ar - ai * q;
    double zi = ai + ar * q;
    double w = wgt * jac;
    acc.h += w * zr;
    double yr = sr * zr - si * zi;
    double yi = sr * zi + si * zr;
    acc.dh += w * yr;
    acc.d2 += w * (sr * yr - si * yi);
    double mod = py_hypot(zr, zi);
    acc.abs += w * mod;
    return jac * mod;
}

void parabola_sweep(LaplacePath& path, LPWorkspace& ws, LPAxis& ax, double t, double ss, double kappa, double step, double off, LPAcc& acc,
                    double c = 0.0) {
    double max_mod = 0.0;
    double min_env = Inf;
    int small = 0;
    double last[7] = {0, 0, 0, 0, 0, 0, 0};
    for (int k = 0; k <= 19999; k++) {
        double u = off + k * (off != 0 ? 2 * step : step);
        double Y = c > 0 ? c * lm_sinh(u) : u;
        double jac = c > 0 ? c * lm_cosh(u) : 1.0;
        if (u == 0) {
            double m0 = parabola_term(path, ws, ax, t, ss, kappa, 0.0, jac, 0.5, acc);
            max_mod = ff_max(max_mod, m0);
            continue;
        }
        double m = parabola_term(path, ws, ax, t, ss, kappa, Y, jac, 1.0, acc);
        if (k > 3 && (m > 100 * max_mod || (min_env < 1e-6 * max_mod && m > 1e-3 * max_mod))) {
            acc.regrow = true;
            break;
        }
        if (m > max_mod) max_mod = m;
        last[k % 7] = m;
        if (k >= 7) {
            double mx = last[0];
            for (int r = 1; r < 7; r++)
                if (last[r] > mx) mx = last[r];
            min_env = ff_min(min_env, mx);
        }
        if (m <= 1e-18 * max_mod) {
            small++;
            if (small >= 3 && k > 3) return;
        } else {
            small = 0;
        }
        if (acc.bad) return;
        if (ws.evaluations > acc.stop) break;
    }
    acc.cut = true;
}

double psi_real(LaplacePath& path, LPWorkspace& ws, LPAxis& ax, double s) {
    Cx v = eval_block(path, ws, *ax.blk, {s, 0.0}, ax.kind);
    double F = v.re;
    return (F > 0 && std::isfinite(F)) ? py_log(F) - ws.E : NaN;
}

struct LPLocal {
    double psi, D, psi2;
};

/// psi, the tilted mean D = -psi' and psi'' at s, by central differences.
LPLocal local_axis(LaplacePath& path, LPWorkspace& ws, LPAxis& ax, double s, double scale) {
    double dl = ff_min(1e-3 * (s - ax.s0), scale > 0 ? 0.1 * scale : Inf);
    double pm = psi_real(path, ws, ax, s - dl);
    double p0 = psi_real(path, ws, ax, s);
    double pp = psi_real(path, ws, ax, s + dl);
    return {p0, (pm - pp) / (2 * dl), (pp - 2 * p0 + pm) / (dl * dl)};
}

/// ln |H(g_p(s))|, the size of member p's own transform at s.
double ln_hk(const LaplacePath& path, const LPBlock& blk, int p, double sr, double si, double rfc) {
    double lam = blk.lam[p];
    Cx g0 = g_fracture(blk, p, sr, si, rfc);
    double gr = g0.re, gi = g0.im;
    if (blk.matrix) {
        double fm = blk.Rm[p] / blk.De[p];
        Cx tz = tau_at(path, {fm * (sr + lam), fm * si});
        gr += path.aw * blk.De[p] * tz.re;
        gi += path.aw * blk.De[p] * tz.im;
    }
    return phi_at(path, {gr, gi}).re;
}

bool clears_ridge(const LaplacePath& path, const LPBlock& blk, double v, double t, double kappa, const std::vector<double>& lev, double lev_min,
                  double rfc) {
    double ymax;
    if (path.inf_pe) {
        ymax = jl_sqrt(80 / (t * kappa));
    } else {
        if (t * v + path.Pe / 2 <= lev_min) return true;
        ymax = jl_sqrt((t * v + path.Pe / 2 - lev_min + 40) / (t * kappa));
    }
    for (int q = 1; q <= 96; q++) {
        double Y = ymax * q / 96;
        double sr = v - kappa * Y * Y;
        for (int p = 0; p < blk.m; p++)
            if (t * sr + ln_hk(path, blk, p, sr, Y, rfc) > lev[p]) return false;
    }
    return true;
}

/// How fast, at most, the phase of any member's own transform times e^(st) turns along the parabola.
std::pair<double, double> path_frequency(const LaplacePath& path, const LPBlock& blk, double v, double t, double kappa, double floor_,
                                         double rfc, const double* t2, double c) {
    double ymax = jl_sqrt(ff_max(0.0, (t * v - floor_ + (path.inf_pe ? 40.0 : path.Pe / 2 + 40)) / (t * kappa)));
    double wmax = 0.0;
    double wmax_u = 0.0;
    for (int q = 0; q <= 96; q++) {
        double Y = ymax * q / 96;
        double sr = v - kappa * Y * Y;
        double si = Y;
        for (int p = 0; p < blk.m; p++) {
            double zr0 = sr + blk.lam[p];
            Cx g0 = g_fracture(blk, p, sr, si, rfc);
            double gr = g0.re, gi = g0.im;
            double dgr = path.inf_pe ? blk.Rf[p] - rfc : blk.Rf[p];
            double dgi = 0.0;
            if (blk.matrix) {
                double f = blk.Rm[p] / blk.De[p];
                double aw_de = path.aw * blk.De[p];
                Cx u = c_sqrt({f * zr0, f * si});
                double tr = u.re, ti = u.im;
                Cx hh = c_div({0.5, 0.0}, u);
                double dr, di;
                if (path.inf_x0) {
                    dr = hh.re;
                    di = hh.im;
                } else {
                    Cx th = c_tanh({path.x0 * u.re, path.x0 * u.im});
                    tr = u.re * th.re - u.im * th.im;
                    ti = u.re * th.im + u.im * th.re;
                    Cx se = c_sech2({path.x0 * u.re, path.x0 * u.im});
                    dr = th.re * hh.re - th.im * hh.im + 0.5 * path.x0 * se.re;
                    di = th.re * hh.im + th.im * hh.re + 0.5 * path.x0 * se.im;
                }
                gr += aw_de * tr;
                gi += aw_de * ti;
                dgr += aw_de * f * dr;
                dgi += aw_de * f * di;
            }
            Cx ph = phi_at(path, {gr, gi});
            if (t * sr + ph.re < floor_) continue;
            double pr_, pi_;
            if (path.inf_pe) {
                pr_ = -path.tw * dgr;
                pi_ = -path.tw * dgi;
            } else {
                double B = 4 * path.tw / path.Pe;
                Cx sq = c_sqrt({1 + B * gr, B * gi});
                Cx q_ = c_div({-path.tw, 0.0}, sq);
                pr_ = q_.re * dgr - q_.im * dgi;
                pi_ = q_.re * dgi + q_.im * dgr;
            }
            double w = std::fabs((t + pr_) - 2 * kappa * Y * pi_);
            if (t2) w = ff_max(w, std::fabs((*t2 + pr_) - 2 * kappa * Y * pi_));
            if (w > wmax) wmax = w;
            if (c > 0) {
                double wu = w * jl_sqrt(c * c + Y * Y);
                if (wu > wmax_u) wmax_u = wu;
            }
        }
    }
    return {wmax, wmax_u};
}

struct LPVertex {
    double v;
    std::optional<LPLocal> loc;
    double psi2;
};

/// The vertex of the parabola for time tt: (v, the local axis at v or nothing, psi'').
LPVertex parabola_vertex(LaplacePath& path, LPWorkspace& ws, LPAxis& ax, double tt, const LPSaddle& sad) {
    double v_min = ax.s0 + LP_VERTEX_BETA / tt;
    double v = ff_max(sad.s, v_min);
    std::optional<LPLocal> loc;
    double psi2 = NaN;
    if (ax.kind != LP_INVENTORY) {
        double scale = ff_min(1 / tt, (std::isfinite(sad.psi2) && sad.psi2 > 0) ? 1 / jl_sqrt(sad.psi2) : Inf);
        loc = local_axis(path, ws, ax, v, scale);
        for (int it = 0; it < 3; it++) {
            if (!(v > v_min && loc->psi2 > 0 && std::fabs(loc->D - tt) > 0.5 * jl_sqrt(loc->psi2))) break;
            double vn = ff_max(v + (loc->D - tt) / loc->psi2, v_min);
            LPLocal ln = local_axis(path, ws, ax, vn, scale);
            if (!(std::fabs(ln.D - tt) < std::fabs(loc->D - tt)) || !(ln.psi2 > 0)) break;
            v = vn;
            loc = ln;
        }
        psi2 = loc->psi2;
    }
    if (!(psi2 > 0) || !std::isfinite(psi2)) psi2 = (std::isfinite(sad.psi2) && sad.psi2 > 0) ? sad.psi2 : tt * tt;
    return {v, loc, psi2};
}

double flatten_for_ridge(const LaplacePath& path, const LPBlock& blk, double v, double t, double wv, double kappa, double rfc) {
    int m = blk.m;
    std::vector<double> lev(m, 0.0);
    double lev_min = Inf;
    for (int p = 0; p < m; p++) {
        lev[p] = ff_max(t * v + ln_hk(path, blk, p, v, 0.0, rfc), wv) + 2;
        lev_min = ff_min(lev_min, lev[p]);
    }
    for (int it = 0; it < 16; it++) {
        if (clears_ridge(path, blk, v, t, kappa, lev, lev_min, rfc)) break;
        kappa /= 4;
    }
    return kappa;
}

double parabola_strip(const LPAxis& ax, double v, double kappa) {
    double dist = v - ax.s0;
    double strip = Inf;
    if (dist > 0 && std::isfinite(dist)) {
        if (kappa * dist < 1e-12)
            strip = dist;
        else if (4 * kappa * dist >= 1)
            strip = 1 / (2 * kappa);
        else
            strip = (1 - jl_sqrt(1 - 4 * kappa * dist)) / (2 * kappa);
    }
    if (!(strip > 0)) strip = dist > 0 ? dist : Inf;
    return strip;
}

inline double path_curvature(double psi2, double t, double dv, double kappa) {
    return psi2 + 2 * ff_max(0.0, std::isfinite(dv) ? t - dv : 0.0) * kappa;
}

inline double sinh_step(double c, double gauss_step, double w_u) {
    return ff_min(ff_min(LP_SINH_STEP, w_u > 0 ? 0.5 * LP_PI / w_u : Inf), gauss_step / c);
}

double node_scale(double strip, double psi2e, double gauss_step, double w_y, double w_u) {
    if (!(psi2e > 0) || !(strip * jl_sqrt(psi2e) < LP_SINH_RATIO)) return 0.0;
    double step_y = ff_min(gauss_step, w_y > 0 ? 0.5 * LP_PI / w_y : Inf);
    if (!(0.5 * strip < step_y)) return 0.0;
    double reach = jl_sqrt(83 / psi2e);
    double n_y = reach / (0.5 * strip);
    double n_u = lm_asinh(reach / strip) / sinh_step(strip, gauss_step, w_u);
    return n_u < n_y ? strip : 0.0;
}

LPInv parabola_sums(LaplacePath& path, LPWorkspace& ws, LPAxis& ax, double tt, double v, double kappa, double psi2, double omega, double rtol,
                    double atol, double stop, double strip, double c = 0.0) {
    double strip_u, step;
    if (c > 0) {
        strip_u = LP_PI / 4;
        step = sinh_step(c, 1.5 * LP_PI / jl_sqrt(18.5 * psi2), omega);
    } else {
        step = 1.5 * LP_PI / jl_sqrt(18.5 * psi2);
        if (omega > 0) step = ff_min(step, 0.5 * LP_PI / omega);
        strip_u = strip;
        step = ff_min(step, 0.5 * strip);
    }
    double ss = ax.kind == LP_INVENTORY ? off_lambda(*ax.blk, v, 0.25 * (c > 0 ? c * step : step)) : v;
    LPAcc acc(stop);
    parabola_sweep(path, ws, ax, tt, ss, kappa, step, 0.0, acc, c);
    if (acc.regrow) return LPInv{NaN, NaN, NaN, Inf, Inf, true, false};
    double h = acc.h * step / LP_PI;
    double dh = acc.dh * step / LP_PI;
    double d2 = acc.d2 * step / LP_PI;
    double err = Inf;
    int agreed = 0;
    for (int level = 0; level <= 11; level++) {
        if (acc.bad || ws.evaluations > stop) break;
        double half = step / 2;
        LPAcc a2(stop);
        parabola_sweep(path, ws, ax, tt, ss, kappa, half, half, a2, c);
        if (a2.regrow) return LPInv{NaN, NaN, NaN, Inf, Inf, true, false};
        if (a2.bad) {
            acc.bad = true;
            break;
        }
        if (a2.cut) acc.cut = true;
        acc.h += a2.h;
        acc.dh += a2.dh;
        acc.d2 += a2.d2;
        acc.abs += a2.abs;
        step = half;
        double h2 = acc.h * step / LP_PI;
        err = std::fabs(h2 - h);
        h = h2;
        dh = acc.dh * step / LP_PI;
        d2 = acc.d2 * step / LP_PI;
        double floor_ = 1e-15 * acc.abs * step / LP_PI + atol;
        double rel = err / ff_max(std::fabs(h), 1e-300);
        double edge = std::isfinite(strip_u) ? 2 * lm_exp(-2 * LP_PI * strip_u / step) : 0.0;
        double nxt = ff_max(rel * rel, edge);
        bool ok = err <= floor_ || (level >= 1 && err <= rtol * std::fabs(h) && nxt <= rtol) ||
                  (!(c > 0) && step <= 0.3 * strip_u && nxt <= rtol * 1e-2);
        agreed = ok ? agreed + 1 : 0;
        if (ok && (agreed >= 2 || !path.inf_pe)) {
            err = ff_min(err, nxt * std::fabs(h) + floor_);
            break;
        }
    }
    if (acc.bad) return LPInv{NaN, NaN, NaN, Inf, Inf, false, true};
    double cond = acc.abs * step / LP_PI / ff_max(std::fabs(h), 1e-300);
    if (acc.cut) err = Inf;
    return LPInv{h, dh, d2, err, cond, false, false};
}

}  // namespace

LPInv invert_parabola(LaplacePath& path, LPWorkspace& ws, LPAxis& ax, double t, double atol) {
    double tt = t - ax.shift;
    if (!(tt > 0)) return LP_ZERO;
    double rtol = 1e-11;
    int max_eval = 6000;
    std::optional<LPSaddle> sad = saddle_at(ax, tt);
    if (!sad || sad->beyond || sad->w < -720) return LP_ZERO;
    long long n0 = ws.evaluations;
    LPVertex vx = parabola_vertex(path, ws, ax, tt, *sad);
    double v = vx.v;
    double psi2 = vx.psi2;
    const std::optional<LPLocal>& loc = vx.loc;
    double wv = (loc && std::isfinite(loc->psi)) ? tt * v + loc->psi : sad->w;
    double omega = (loc && std::isfinite(loc->D)) ? std::fabs(tt - loc->D) : 0.0;
    double kappa = ff_max(psi2 / (2 * tt), 0.25 / (v - ax.s0));
    double rfc = ax.shift > 0 ? ax.blk->Rmin : 0.0;
    if (!path.inf_pe || !path.inf_x0) kappa = flatten_for_ridge(path, *ax.blk, v, tt, wv, kappa, rfc);
    LPInv res = LP_ZERO;
    for (int it = 0; it < 4; it++) {
        double strip = parabola_strip(ax, v, kappa);
        double psi2e = path_curvature(psi2, tt, loc ? loc->D : NaN, kappa);
        auto [w_y0, rate_u] = path_frequency(path, *ax.blk, v, tt, kappa, wv - 25, rfc, nullptr, strip);
        double w_y = ff_max(omega, w_y0);
        double w_u = ff_max(omega * jl_sqrt(strip * strip + 50 / psi2e), rate_u);
        double c = node_scale(strip, psi2e, 1.5 * LP_PI / jl_sqrt(18.5 * psi2), w_y, w_u);
        res = parabola_sums(path, ws, ax, tt, v, kappa, psi2, c > 0 ? w_u : w_y, rtol, atol, static_cast<double>(n0 + max_eval), strip, c);
        if (!res.regrow) break;
        kappa /= 8;
    }
    if (res.regrow || res.bad) return LP_FAILED;
    return res;
}

// --- shared contours: one parabola for the times of a cell ------------------------------------------

namespace {

double cell_span(double t1, double t2, double sig) {
    if (!(sig > 0) || !std::isfinite(sig)) return LP_CELL_SLOPE * py_log(t2 / t1);
    double tk = LP_CELL_C * sig / LP_LN_F;
    if (t2 <= tk) return LP_CELL_SLOPE * py_log(t2 / t1);
    if (t1 >= tk) return (t2 - t1) / (2 * LP_CELL_C * sig);
    return LP_CELL_SLOPE * py_log(tk / t1) + (t2 - tk) / (2 * LP_CELL_C * sig);
}

LPCell failed_cell(double k, double t_lo, double t_a, double t_hi, const std::string& why) {
    LPCell c;
    c.ok = false;
    c.k = k;
    c.tLo = t_lo;
    c.tA = t_a;
    c.tHi = t_hi;
    c.why = why;
    c.v = NaN;
    c.step = NaN;
    c.levels = 0;
    c.strip = NaN;
    c.c = 0.0;
    c.n = 0;
    return c;
}

/// The nodes a cell's sweeps leave: s, the weighted factor of its term, its scale and its level.
struct LPNodes {
    std::vector<double> sr, si, gr, gi, E;
    std::vector<int> lev;
};

struct LPCellAcc {
    std::vector<double> h, abs;
    bool bad = false, regrow = false, cut = false;
    double stop = Inf;
};

void cell_sweep(LaplacePath& path, LPWorkspace& ws, LPCells& C, double ss, double kappa, double step, double off, int level, LPCellAcc& acc,
                LPNodes& nodes, double c = 0.0) {
    LPAxis& ax = *C.ax;
    LPBlock& blk = *ax.blk;
    int kind = ax.kind;
    const std::vector<double>& P = C.pt;
    int npr = static_cast<int>(P.size());
    std::vector<double>& ah = acc.h;
    std::vector<double>& aa = acc.abs;
    std::vector<double> mods(npr, 0.0), max_mod(npr, 0.0), min_env(npr, Inf), last(7 * npr, 0.0);
    std::vector<int> small(npr, 0);
    for (int k = 0; k <= 19999; k++) {
        double u = off + k * (off != 0 ? 2 * step : step);
        double Y = c > 0 ? c * lm_sinh(u) : u;
        double jac = c > 0 ? c * lm_cosh(u) : 1.0;
        double wgt = u == 0 ? 0.5 : 1.0;
        double w = wgt * jac;
        double sr = ss - kappa * Y * Y;
        double si = Y;
        Cx F = eval_block(path, ws, blk, {sr, si}, kind);
        double Fr = F.re, Fi = F.im;
        double E = ws.E;
        double q = 2 * kappa * Y;
        double gr = w * (Fr - Fi * q);
        double gi = w * (Fi + Fr * q);
        nodes.sr.push_back(sr);
        nodes.si.push_back(si);
        nodes.gr.push_back(gr);
        nodes.gi.push_back(gi);
        nodes.E.push_back(E);
        nodes.lev.push_back(level);
        for (int p = 0; p < npr; p++) {
            double t = P[p];
            double ex = t * sr - E;
            double m = 0.0;
            if (ex > 700) {
                acc.bad = true;
                m = Inf;
            } else if (!(ex < -740 || (Fr == 0 && Fi == 0))) {
                Cx e = c_exp({ex, t * si});
                double zr = e.re * gr - e.im * gi;
                double zi = e.re * gi + e.im * gr;
                ah[p] += zr;
                m = py_hypot(zr, zi);
                aa[p] += m;
                m /= wgt;
            }
            mods[p] = m;
        }
        if (u == 0) {
            for (int p = 0; p < npr; p++) max_mod[p] = ff_max(max_mod[p], mods[p]);
            continue;
        }
        bool dead = k > 3;
        for (int p = 0; p < npr; p++) {
            double m = mods[p];
            if (k > 3 && (m > 100 * max_mod[p] || (min_env[p] < 1e-6 * max_mod[p] && m > 1e-3 * max_mod[p]))) {
                acc.regrow = true;
                return;
            }
            if (m > max_mod[p]) max_mod[p] = m;
            last[7 * p + k % 7] = m;
            if (k >= 7) {
                double env = 0.0;
                for (int r = 7 * p; r < 7 * p + 7; r++)
                    if (last[r] > env) env = last[r];
                if (env < min_env[p]) min_env[p] = env;
            }
            if (m <= 1e-18 * max_mod[p])
                small[p]++;
            else
                small[p] = 0;
            if (small[p] < 3) dead = false;
        }
        if (dead) return;
        if (acc.bad) return;
        if (ws.evaluations > acc.stop) break;
    }
    acc.cut = true;
}

struct LPCellSums {
    bool ok = false;
    std::string why;
    bool regrow = false;
    double step = NaN;
    int levels = 0;
    double strip = NaN;
    double c = 0.0;
    double ss = 0.0;
    LPNodes nodes;
};

/// The sums of a cell's parabola at every probe time (`cellSums`).
LPCellSums cell_sums(LaplacePath& path, LPWorkspace& ws, LPCells& C, double v, double kappa, double psi2, double omega, double stop,
                     double strip, double c = 0.0) {
    LPAxis& ax = *C.ax;
    int npr = static_cast<int>(C.pt.size());
    double rtol = C.rtol;
    double strip_u, step;
    if (c > 0) {
        strip_u = LP_PI / 4;
        step = sinh_step(c, 1.5 * LP_PI / jl_sqrt(18.5 * psi2), omega);
    } else {
        step = 1.5 * LP_PI / jl_sqrt(18.5 * psi2);
        if (omega > 0) step = ff_min(step, 0.5 * LP_PI / omega);
        strip_u = strip;
        step = ff_min(step, 0.5 * strip);
    }
    double ss = ax.kind == LP_INVENTORY ? off_lambda(*ax.blk, v, 0.25 * (c > 0 ? c * step : step)) : v;
    LPCellAcc acc{std::vector<double>(npr, 0.0), std::vector<double>(npr, 0.0), false, false, false, stop};
    LPCellSums r;
    r.c = c;
    r.ss = ss;
    auto fail = [&](const char* why) {
        r.ok = false;
        r.why = why;
        r.regrow = false;
        r.step = NaN;
        r.levels = 0;
        r.strip = NaN;
        return std::move(r);
    };
    auto regrown = [&]() {
        r.ok = false;
        r.why = "";
        r.regrow = true;
        r.step = NaN;
        r.levels = 0;
        r.strip = NaN;
        return std::move(r);
    };
    cell_sweep(path, ws, C, ss, kappa, step, 0.0, 0, acc, r.nodes, c);
    if (acc.regrow) return regrown();
    if (acc.bad || acc.cut) return fail(acc.bad ? "overflow" : "cut short");
    std::vector<double> h(npr);
    for (int p = 0; p < npr; p++) h[p] = acc.h[p] * step / LP_PI;
    int agreed = 0;
    for (int level = 0; level <= 11; level++) {
        if (ws.evaluations > stop) break;
        double half = step / 2;
        cell_sweep(path, ws, C, ss, kappa, half, half, level + 1, acc, r.nodes, c);
        if (acc.regrow) return regrown();
        if (acc.bad || acc.cut) return fail(acc.bad ? "overflow" : "cut short");
        step = half;
        double edge = std::isfinite(strip_u) ? 2 * lm_exp(-2 * LP_PI * strip_u / step) : 0.0;
        bool every = true;
        for (int p = 0; p < npr; p++) {
            double h2 = acc.h[p] * step / LP_PI;
            double err = std::fabs(h2 - h[p]);
            h[p] = h2;
            double floor_ = 1e-15 * acc.abs[p] * step / LP_PI + C.atol;
            double rel = err / ff_max(std::fabs(h2), 1e-300);
            double nxt = ff_max(rel * rel, edge);
            if (!(err <= floor_ || (level >= 1 && err <= rtol * std::fabs(h2) && nxt <= rtol) ||
                  (!(c > 0) && step <= 0.3 * strip_u && nxt <= rtol * 1e-2)))
                every = false;
        }
        agreed = every ? agreed + 1 : 0;
        if (every && (agreed >= 2 || !path.inf_pe)) {
            r.ok = true;
            r.why = "";
            r.regrow = false;
            r.step = step;
            r.levels = level + 1;
            r.strip = strip_u;
            return r;
        }
    }
    return fail(ws.evaluations > stop ? "budget" : "no agreement");
}

LPCell build_cell(LaplacePath& path, LPWorkspace& ws, LPCells& C, double k) {
    LPAxis& ax = *C.ax;
    double t_a = cell_t(C, k);
    double t_lo = cell_t(C, k - 0.5);
    double t_hi = cell_t(C, k + 0.5);
    auto fail = [&](const std::string& why) { return failed_cell(k, t_lo, t_a, t_hi, why); };
    if (!(t_lo > 0) || !(t_a > t_lo) || !(t_hi > t_a) || !std::isfinite(t_hi)) return fail("lattice");
    std::optional<LPSaddle> sad = saddle_at(ax, t_a);
    if (!sad || sad->beyond || sad->w < -720) return fail("negligible");
    long long n0 = ws.evaluations;
    LPVertex vx = parabola_vertex(path, ws, ax, t_a, *sad);
    double v = vx.v;
    double psi2 = vx.psi2;
    double psi_v = sad->w - t_a * v;
    double d_v = t_a;
    if (vx.loc) {
        if (!std::isfinite(vx.loc->psi) || !std::isfinite(vx.loc->D)) return fail("axis");
        psi_v = vx.loc->psi;
        d_v = vx.loc->D;
    }
    double omega = ff_max(std::fabs(t_lo - d_v), std::fabs(t_hi - d_v));
    double kappa = ff_max(psi2 / (2 * t_a), 0.25 / (v - ax.s0));
    LPBlock& blk = *ax.blk;
    double rfc = ax.shift > 0 ? blk.Rmin : 0.0;
    if (!path.inf_pe || !path.inf_x0) kappa = flatten_for_ridge(path, blk, v, t_lo, t_lo * v + psi_v, kappa, rfc);
    C.pt.clear();
    for (double p : LP_CELL_PROBES) C.pt.push_back(cell_t(C, k + p));
    LPCellSums res;
    for (int it = 0; it < 4; it++) {
        double strip = parabola_strip(ax, v, kappa);
        double psi2lo = ff_max(psi2 * t_lo / t_a, psi2 + 2 * (t_lo - d_v) * kappa);
        double psi2hi = psi2 * t_hi / t_a;
        auto [w_y0, rate_u] = path_frequency(path, blk, v, t_lo, kappa, t_lo * v + psi_v - 25, rfc, &t_hi, strip);
        double w_y = ff_max(omega, w_y0);
        double w_u = ff_max(omega * jl_sqrt(strip * strip + 50 / psi2lo), rate_u);
        double c = node_scale(strip, psi2lo, 1.5 * LP_PI / jl_sqrt(18.5 * psi2hi), w_y, w_u);
        res = cell_sums(path, ws, C, v, kappa, psi2hi, c > 0 ? w_u : w_y, static_cast<double>(n0 + C.maxEval), strip, c);
        if (!res.regrow) break;
        kappa /= 8;
    }
    if (!res.ok) return fail(res.regrow ? "regrowth" : res.why);
    const LPNodes& nd = res.nodes;
    double ss = res.ss;
    std::size_t nn = nd.sr.size();
    std::vector<double> lg(nn);
    for (std::size_t q = 0; q < nn; q++) lg[q] = lp_ln(py_hypot(nd.gr[q], nd.gi[q])) - nd.E[q];
    double top = lg[0] + LP_LN2 + LP_LN_PRUNE;
    LPCell cell;
    cell.ok = true;
    cell.k = k;
    cell.tLo = t_lo;
    cell.tA = t_a;
    cell.tHi = t_hi;
    cell.why = "";
    cell.v = v;
    cell.step = res.step;
    cell.levels = res.levels;
    cell.strip = res.strip;
    cell.c = res.c;
    for (std::size_t q = 0; q < nn; q++) {
        if (!(q == 0 || !(t_lo * (nd.sr[q] - ss) + lg[q] < top && t_hi * (nd.sr[q] - ss) + lg[q] < top))) continue;
        cell.sr.push_back(nd.sr[q]);
        cell.si.push_back(nd.si[q]);
        cell.gr.push_back(nd.gr[q]);
        cell.gi.push_back(nd.gi[q]);
        cell.mE.push_back(-nd.E[q]);
        cell.lev.push_back(nd.lev[q]);
        cell.ag.push_back(py_hypot(nd.gr[q], nd.gi[q]));
    }
    cell.n = static_cast<int>(cell.sr.size());
    for (double x : cell.ag) cell.la.push_back(lp_ln(x));
    return cell;
}

/// The response, h' and h'' at tt from a cell's nodes, or nothing when the result does not pass.
std::optional<LPInv> cell_sample(const LPCells& C, const LPCell& cell, double tt) {
    int n = cell.n;
    const std::vector<double>& sr = cell.sr;
    const std::vector<double>& si = cell.si;
    const std::vector<double>& gr = cell.gr;
    const std::vector<double>& gi = cell.gi;
    const std::vector<double>& ag = cell.ag;
    const std::vector<double>& la = cell.la;
    const std::vector<double>& mE = cell.mE;
    const std::vector<int>& lev = cell.lev;
    int L = cell.levels;
    double low = tt * sr[0] + mE[0] + la[0] + LP_LN_PRUNE;
    double h = 0.0, d1 = 0.0, d2 = 0.0, a = 0.0, h1 = 0.0, a1 = 0.0, h2 = 0.0;
    for (int q = 0; q < n; q++) {
        double ex = tt * sr[q] + mE[q];
        if (ex > 700) return std::nullopt;
        if (ex < -740 || ex + la[q] < low) continue;
        double e = lm_exp(ex);
        double ph = tt * si[q];
        double er = e * lm_cos(ph);
        double ei = e * lm_sin(ph);
        double g_r = gr[q], g_i = gi[q];
        double zr = er * g_r - ei * g_i;
        double zi = er * g_i + ei * g_r;
        double s_r = sr[q], s_i = si[q];
        double yr = s_r * zr - s_i * zi;
        double yi = s_r * zi + s_i * zr;
        double m = e * ag[q];
        h += zr;
        d1 += yr;
        d2 += s_r * yr - s_i * yi;
        a += m;
        if (lev[q] < L) {
            h1 += zr;
            a1 += m;
            if (lev[q] < L - 1) h2 += zr;
        }
    }
    double rtol = C.rtol;
    double atol = C.atol;
    double strip = cell.strip;
    // Julia's `passes` is a closure assigning `err`, a local of the function around it too, so it
    // writes that one: a second call (under plug flow) leaves its own difference in `err`, which
    // the test below and the result then read. Kept as Julia has it.
    double err = 0.0;
    auto passes = [&](double hn, double hp, double an, double st, int level) {
        err = std::fabs(hn - hp);
        double floor_ = 1e-15 * an + atol;
        double rel = err / ff_max(std::fabs(hn), 1e-300);
        double nxt = ff_max(rel * rel, std::isfinite(strip) ? 2 * lm_exp(-2 * LP_PI * strip / st) : 0.0);
        bool ok = err <= floor_ || (level >= 1 && err <= rtol * std::fabs(hn) && nxt <= rtol) ||
                  (!(cell.c > 0) && st <= 0.3 * strip && nxt <= rtol * 1e-2);
        return ok ? ff_min(err, nxt * std::fabs(hn) + floor_) : -1.0;
    };
    double st = cell.step;
    double c = st / LP_PI;
    double H = h * c;
    double H1 = h1 * 2 * c;
    double A = a * c;
    err = passes(H, H1, A, st, L - 1);
    if (!(err >= 0)) return std::nullopt;
    if (C.infPe && !(passes(H1, h2 * 4 * c, a1 * 2 * c, 2 * st, L - 2) >= 0)) return std::nullopt;
    double cond = A / ff_max(std::fabs(H), 1e-300);
    if (!std::isfinite(H) || !(cond <= LP_CELL_COND || A <= LP_CELL_NEGLIGIBLE * C.peak)) return std::nullopt;
    if (err > 1e-6 * std::fabs(H) + atol) return std::nullopt;
    return LPInv{H, d1 * c, d2 * c, err, cond, false, false};
}

std::uint64_t cell_key(double k) {
    if (k != k) return 0x7ff8000000000000ULL;
    std::uint64_t u;
    std::memcpy(&u, &k, 8);
    return u;
}

}  // namespace

double cell_u(const LPCells& C, double tt) {
    const std::vector<double>& tb = C.tb;
    int nb = static_cast<int>(tb.size());
    if (nb == 0) return LP_CELL_SLOPE * py_log(tt);
    if (tt <= tb[0]) return LP_CELL_SLOPE * py_log(tt / tb[0]);
    if (tt >= tb[nb - 1]) return C.U[nb - 1] + LP_CELL_SLOPE * py_log(tt / tb[nb - 1]);
    int lo = 0, hi = nb - 1;
    while (hi - lo > 1) {
        int c = (lo + hi) >> 1;
        if (tb[c] <= tt)
            lo = c;
        else
            hi = c;
    }
    return C.U[lo] + cell_span(tb[lo], tt, C.sig[lo]);
}

double cell_t(const LPCells& C, double u) {
    const std::vector<double>& tb = C.tb;
    int nb = static_cast<int>(tb.size());
    const std::vector<double>& U = C.U;
    if (nb == 0) return lm_exp(u / LP_CELL_SLOPE);
    if (u <= 0) return tb[0] * lm_exp(u / LP_CELL_SLOPE);
    if (u >= U[nb - 1]) return tb[nb - 1] * lm_exp((u - U[nb - 1]) / LP_CELL_SLOPE);
    int lo = 0, hi = nb - 1;
    while (hi - lo > 1) {
        int c = (lo + hi) >> 1;
        if (U[c] <= u)
            lo = c;
        else
            hi = c;
    }
    double t1 = tb[lo];
    double sig = C.sig[lo];
    double du = u - U[lo];
    if (!(sig > 0) || !std::isfinite(sig)) return t1 * lm_exp(du / LP_CELL_SLOPE);
    double tk = LP_CELL_C * sig / LP_LN_F;
    if (t1 >= tk) return t1 + du * 2 * LP_CELL_C * sig;
    double uk = LP_CELL_SLOPE * py_log(tk / t1);
    return du <= uk ? t1 * lm_exp(du / LP_CELL_SLOPE) : tk + (du - uk) * 2 * LP_CELL_C * sig;
}

LPCells make_cells(LaplacePath& path, LPAxis& ax, double atol, double peak) {
    const std::vector<double>& D = ax.D;
    const std::vector<double>& sm = ax.sm;
    std::vector<double> tb, sb;
    double last = Inf;
    for (std::size_t k = 0; k < D.size(); k++) {
        double d = D[k];
        if (!std::isfinite(d)) {
            if (!tb.empty()) break;
            continue;
        }
        if (!(d > 0) || !(d < last)) continue;
        tb.push_back(d);
        sb.push_back(sm[k]);
        last = d;
    }
    std::reverse(tb.begin(), tb.end());
    std::reverse(sb.begin(), sb.end());
    std::size_t nb = tb.size();
    std::vector<double> U(nb, 0.0);
    std::vector<double> sig(nb > 0 ? nb - 1 : 0, 0.0);
    for (std::size_t m = 0; m + 1 < nb; m++) {
        double den = sb[m] - sb[m + 1];
        double psi2 = den != 0 ? (tb[m + 1] - tb[m]) / den : NaN;
        sig[m] = (psi2 > 0 && std::isfinite(psi2)) ? jl_sqrt(psi2) : NaN;
        U[m + 1] = U[m] + cell_span(tb[m], tb[m + 1], sig[m]);
    }
    if (!(peak > 0)) {
        double lp = -Inf;
        for (double t : tb) lp = ff_max(lp, log_estimate(ax, t + ax.shift));
        peak = std::isfinite(lp) ? lm_exp(lp) : 0.0;
    }
    LPCells C;
    C.ax = &ax;
    C.tb = std::move(tb);
    C.U = std::move(U);
    C.sig = std::move(sig);
    C.peak = peak;
    C.infPe = path.inf_pe;
    C.rtol = 1e-11;
    C.atol = atol;
    C.maxEval = LP_CELL_MAX_EVAL;
    C.pt.assign(std::size(LP_CELL_PROBES), 0.0);
    return C;
}

std::optional<LPInv> invert_shared(LaplacePath& path, LPWorkspace& ws, LPCells& C, double t) {
    LPAxis& ax = *C.ax;
    double tt = t - ax.shift;
    if (!(tt > 0)) {
        C.st_negligible++;
        return LP_ZERO;
    }
    std::optional<LPSaddle> sad = saddle_at(ax, tt);
    if (!sad || sad->beyond || sad->w < -720) {
        C.st_negligible++;
        return LP_ZERO;
    }
    double u = cell_u(C, tt) + 0.5;
    double k = std::isfinite(u) ? std::floor(u) : (u == u ? u : NaN);
    std::uint64_t key = cell_key(k);
    auto it = C.map.find(key);
    if (it == C.map.end()) {
        LPCell cell = build_cell(path, ws, C, k);
        bool ok = cell.ok;
        it = C.map.emplace(key, std::move(cell)).first;
        C.st_cells++;
        if (!ok) C.st_failed++;
    }
    const LPCell& cell = it->second;
    std::optional<LPInv> r = (cell.ok && std::isfinite(k)) ? cell_sample(C, cell, tt) : std::nullopt;
    if (r)
        C.st_shared++;
    else
        C.st_fallback++;
    return r;
}

int de_hoog_terms(const LaplacePath& path, const LPAxis* ax, double t) {
    long long m = path.inf_pe ? 24 : std::max(24LL, jl_ceil_int(1.2 * jl_sqrt(path.Pe)));
    if (ax) {
        double tt = t - ax->shift;
        std::optional<LPSaddle> sad = tt > 0 ? saddle_at(*ax, tt) : std::nullopt;
        if (sad && !sad->beyond && sad->psi2 > 0) m = std::max(m, jl_ceil_int(1.7 * tt / jl_sqrt(sad->psi2)));
    }
    return static_cast<int>(std::min(160LL, m));
}

double invert_de_hoog(LaplacePath& path, LPWorkspace& ws, LPBlock& blk, int kind, double shift, double t, int M, int deriv) {
    double tt = t - shift;
    if (!(tt > 0)) return 0.0;
    double tol = 1e-12;
    double T = 2 * tt;
    double gamma = -py_log(tol) / (2 * T);
    int K = 2 * M;
    std::vector<Cx> a(K + 1);
    double E0 = 0.0;
    int k_use = K;
    for (int k = 0; k <= K; k++) {
        Cx F = eval_block(path, ws, blk, {gamma, k * LP_PI / T}, kind);
        if (k == 0) E0 = ws.E;
        double sc = lm_exp(E0 - ws.E);
        Cx v{F.re * sc, F.im * sc};
        for (int r = 0; r < deriv; r++) {
            double sr = gamma;
            double si = k * LP_PI / T;
            v = {sr * v.re - si * v.im, sr * v.im + si * v.re};
        }
        for (int r = 0; r < (deriv < 0 ? -deriv : 0); r++) v = c_div(v, {gamma, k * LP_PI / T});
        a[k] = v;
        if (!(v.re != 0 || v.im != 0) || !std::isfinite(v.re) || !std::isfinite(v.im)) {
            k_use = k - 1;
            break;
        }
    }
    if (((k_use % 2) + 2) % 2 == 1) k_use -= 1;
    if (k_use < 2) return NaN;
    int Mu = k_use / 2;
    a[0] = {a[0].re * 0.5, a[0].im * 0.5};
    std::vector<Cx> q(k_use), e(k_use + 1), d(k_use + 1);
    for (int k = 0; k < k_use; k++) q[k] = c_div(a[k + 1], a[k]);
    d[0] = a[0];
    for (int r = 1; r <= Mu; r++) {
        for (int k = 0; k <= k_use - 2 * r; k++) e[k] = q[k + 1] - q[k] + e[k + 1];
        d[2 * r - 1] = -q[0];
        d[2 * r] = -e[0];
        if (r < Mu)
            for (int k = 0; k <= k_use - 2 * r - 1; k++) {
                Cx x = q[k + 1], y = e[k + 1];
                q[k] = c_div({x.re * y.re - x.im * y.im, x.re * y.im + x.im * y.re}, e[k]);
            }
    }
    double zr = lm_cos(LP_PI * tt / T);
    double zi = lm_sin(LP_PI * tt / T);
    Cx A2{0.0, 0.0}, A1 = d[0], B2{1.0, 0.0}, B1{1.0, 0.0};
    for (int k = 1; k <= k_use; k++) {
        Cx c{d[k].re * zr - d[k].im * zi, d[k].re * zi + d[k].im * zr};
        Cx An, Bn;
        if (k < k_use) {
            An = A1 + Cx{c.re * A2.re - c.im * A2.im, c.re * A2.im + c.im * A2.re};
            Bn = B1 + Cx{c.re * B2.re - c.im * B2.im, c.re * B2.im + c.im * B2.re};
        } else {
            Cx d1 = d[k_use - 1] - d[k_use];
            double hr = 0.5 * (1 + d1.re * zr - d1.im * zi);
            double hi = 0.5 * (d1.re * zi + d1.im * zr);
            Cx h2{hr * hr - hi * hi, 2 * hr * hi};
            Cx u = c_div(c, h2);
            Cx w = c_sqrt({1 + u.re, u.im});
            double Rr = -(hr * (1 - w.re) - hi * (-w.im));
            double Ri = -(hr * (-w.im) + hi * (1 - w.re));
            An = A1 + Cx{Rr * A2.re - Ri * A2.im, Rr * A2.im + Ri * A2.re};
            Bn = B1 + Cx{Rr * B2.re - Ri * B2.im, Rr * B2.im + Ri * B2.re};
        }
        A2 = A1;
        A1 = An;
        B2 = B1;
        B1 = Bn;
    }
    Cx res = c_div(A1, B1);
    return lm_exp(gamma * tt - E0) / T * res.re;
}

// --- unit responses on adaptive grids ---------------------------------------------------------------

double log_estimate(const LPAxis& ax, double t) {
    double tt = t - ax.shift;
    if (!(tt > 0)) return -Inf;
    std::optional<LPSaddle> sad = saddle_at(ax, tt);
    if (!sad || sad->beyond || !std::isfinite(sad->w)) return -Inf;
    double c = (std::isfinite(sad->psi2) && sad->psi2 > 0) ? -0.5 * py_log(2 * LP_PI * sad->psi2) : 0.0;
    return sad->w + c;
}

std::optional<LPSupport> response_support(const LPAxis& ax, double t_min, double t_max) {
    double d = ax.shift;
    double u_min = t_min - d;
    double u_max = t_max - d;
    int per = 16;
    long long n = std::max(2LL, jl_ceil_int(lm_log10(u_max / u_min) * per) + 1);
    std::vector<double> ts(n, 0.0), est(n, 0.0);
    double wmax = -Inf;
    long long kmax = -1;
    for (long long k = 0; k < n; k++) {
        ts[k] = d + u_min * py_pow(u_max / u_min, static_cast<double>(k) / static_cast<double>(n - 1));
        est[k] = log_estimate(ax, ts[k]);
        if (est[k] > wmax) {
            wmax = est[k];
            kmax = k;
        }
    }
    if (!std::isfinite(wmax)) return std::nullopt;
    long long k_lo = 0;
    while (k_lo < n && !(est[k_lo] > wmax - 62)) k_lo++;
    long long k_hi = n - 1;
    while (k_hi > kmax && !(est[k_hi] > wmax - 72)) k_hi--;
    long long k_tail = n - 1;
    while (k_tail > kmax && !(est[k_tail] > wmax - 20.7)) k_tail--;
    return LPSupport{ts[std::max(0LL, k_lo - 1)], k_hi >= n - 1 ? t_max : ts[std::min(n - 1, k_hi + 1)], ts[kmax], wmax,
                     k_tail >= n - 1 ? t_max : ts[std::min(n - 1, k_tail + 1)]};
}

namespace {
inline double cond_or_one(double c) { return c == 0.0 ? 1.0 : c; }
}  // namespace

LPSample lp_sample(LaplacePath& path, LPWorkspace& ws, LPAxis& ax, double t, double atol, LPHint* hint, LPCells* cells) {
    if (hint) hint->tries++;
    if (cells) {
        std::optional<LPInv> s = invert_shared(path, ws, *cells, t);
        if (s) return {s->h, s->dh, s->d2, cond_or_one(s->cond), s->err};
    }
    bool direct = hint && hint->tries > 16 && static_cast<double>(hint->fails) > 0.75 * static_cast<double>(hint->tries);
    LPInv r = direct ? LPInv{NaN, NaN, NaN, Inf, NaN, false, false} : invert_parabola(path, ws, ax, t, atol);
    if (std::isfinite(r.h) && !(r.err > 1e-6 * std::fabs(r.h) + atol)) return {r.h, r.dh, r.d2, cond_or_one(r.cond), r.err};
    if (hint) hint->fails++;
    if (cells) cells->st_dehoog++;
    int m1 = de_hoog_terms(path, &ax, t);
    int m2 = std::min(2 * m1, 320);
    LPBlock& blk = *ax.blk;
    int kind = ax.kind;
    double shift = ax.shift;
    double a_ = invert_de_hoog(path, ws, blk, kind, shift, t, m1);
    double b_ = invert_de_hoog(path, ws, blk, kind, shift, t, m2);
    double e_h = std::fabs(a_ - b_);
    if (std::isfinite(b_) && (!std::isfinite(r.h) || !std::isfinite(r.err) || e_h < r.err)) {
        double d1 = invert_de_hoog(path, ws, blk, kind, shift, t, m2, 1);
        double d2 = invert_de_hoog(path, ws, blk, kind, shift, t, m2, 2);
        if (std::isfinite(d1) && std::isfinite(d2)) return {b_, d1, d2, 1.0, e_h + atol};
    }
    if (std::isfinite(r.h)) return {r.h, r.dh, r.d2, cond_or_one(r.cond), r.err};
    if (direct) {
        LPInv s2 = invert_parabola(path, ws, ax, t, atol);
        if (std::isfinite(s2.h)) return {s2.h, s2.dh, s2.d2, cond_or_one(s2.cond), s2.err};
    }
    return {0.0, 0.0, 0.0, Inf, Inf};
}

double hermite5(double ta, double ya, double da, double ea, double tb, double yb, double db, double eb, double t) {
    double d = tb - ta;
    double x = (t - ta) / d;
    double x2 = x * x;
    double x3 = x2 * x;
    double x4 = x3 * x;
    double x5 = x4 * x;
    double h0 = 1 - 10 * x3 + 15 * x4 - 6 * x5;
    double h1 = x - 6 * x3 + 8 * x4 - 3 * x5;
    double h2 = 0.5 * (x2 - 3 * x3 + 3 * x4 - x5);
    double h4 = -4 * x3 + 7 * x4 - 3 * x5;
    double h5 = 0.5 * (x3 - 2 * x4 + x5);
    return h0 * ya + d * h1 * da + d * d * h2 * ea + (1 - h0) * yb + d * h4 * db + d * d * h5 * eb;
}

LPResponse compute_response(const LPSampler& sampler, double t_a, double t_b, int per, int max_pts, double delay, double peak_estimate) {
    double rtol = LP_RESP_RTOL;
    double atol_rel = LP_RESP_ATOL;
    double dl = delay;
    long long n0 = std::max(16LL, jl_ceil_int(lm_log10((t_b - dl) / (t_a - dl)) * per) + 1);
    std::vector<double> T, H, D, D2;
    double peak = 0.0;
    double max_cond = 1.0;
    double max_err = 0.0;
    double pe = peak_estimate;
    double atol = pe > 0 ? 1e-3 * LP_RESP_ATOL * pe : 0.0;
    LPHint hint;
    for (long long k = 0; k < n0; k++) {
        double t = dl + (t_a - dl) * py_pow((t_b - dl) / (t_a - dl), static_cast<double>(k) / static_cast<double>(n0 - 1));
        LPSample s = sampler(t, atol, hint);
        if (s.err > max_err) max_err = s.err;
        T.push_back(t);
        H.push_back(s.h);
        D.push_back(s.dh);
        D2.push_back(s.d2);
        if (std::fabs(s.h) > peak) peak = std::fabs(s.h);
        if (s.cond > max_cond) max_cond = s.cond;
    }
    std::vector<char> flag(T.size() - 1, 1);
    for (int it = 0; it < 30; it++) {
        std::vector<double> nT{T[0]}, nH{H[0]}, nD{D[0]}, nD2{D2[0]};
        std::vector<char> nF;
        bool inserted = false;
        for (std::size_t k = 0; k + 1 < T.size(); k++) {
            if (flag[k] && static_cast<long long>(T.size() + nT.size()) < 2LL * max_pts &&
                (T[k] == dl || (T[k + 1] - dl) / (T[k] - dl) > 1 + 1e-9)) {
                double tm = T[k] == dl ? dl + 0.5 * (T[k + 1] - dl) : dl + jl_sqrt((T[k] - dl) * (T[k + 1] - dl));
                LPSample s = sampler(tm, ff_max(atol, 1e-3 * LP_RESP_ATOL * peak), hint);
                if (s.err > max_err) max_err = s.err;
                if (std::fabs(s.h) > peak) peak = std::fabs(s.h);
                if (s.cond > max_cond) max_cond = s.cond;
                double p = hermite5(T[k], H[k], D[k], D2[k], T[k + 1], H[k + 1], D[k + 1], D2[k + 1], tm);
                bool dh0 = static_cast<double>(hint.fails) > 0.5 * static_cast<double>(hint.tries);
                bool ok = std::fabs(s.h - p) <= (dh0 ? ff_max(rtol, 1e-7) : rtol) * std::fabs(s.h) + (dh0 ? ff_max(atol_rel, 1e-10) : atol_rel) * peak;
                nT.push_back(tm);
                nH.push_back(s.h);
                nD.push_back(s.dh);
                nD2.push_back(s.d2);
                nF.push_back(!ok);
                nF.push_back(!ok);
                if (!ok) inserted = true;
            } else {
                nF.push_back(0);
            }
            nT.push_back(T[k + 1]);
            nH.push_back(H[k + 1]);
            nD.push_back(D[k + 1]);
            nD2.push_back(D2[k + 1]);
        }
        T = std::move(nT);
        H = std::move(nH);
        D = std::move(nD);
        D2 = std::move(nD2);
        flag = std::move(nF);
        if (!inserted || static_cast<long long>(T.size()) >= max_pts) break;
    }
    std::size_t n = T.size();
    double integral = 0.0;
    double t_peak = T[0];
    double pk = -Inf;
    for (std::size_t k = 0; k < n; k++)
        if (H[k] > pk) {
            pk = H[k];
            t_peak = T[k];
        }
    for (std::size_t k = 0; k + 1 < n; k++) {
        double d = T[k + 1] - T[k];
        integral += d * (0.5 * (H[k] + H[k + 1]) + d * (D[k] - D[k + 1]) / 10 + d * d * (D2[k] + D2[k + 1]) / 120);
    }
    LPResponse r;
    r.t = std::move(T);
    r.h = std::move(H);
    r.dh = std::move(D);
    r.d2h = std::move(D2);
    r.peak = ff_max(pk, 0.0);
    r.tPeak = t_peak;
    r.integral = integral;
    r.maxCond = max_cond;
    r.maxErr = max_err / ff_max(pk, 1e-300);
    return r;
}

LPAxis* axis_of(LaplacePath& path, LPBlock& blk, int kind, double shift) {
    auto key = std::make_tuple(blk.i, blk.j, kind);
    auto it = path.axes.find(key);
    if (it == path.axes.end()) {
        double t_lo = shift > 0 ? shift * (1 + 1e-9) : path.tw * 1e-6;
        auto ax = std::make_unique<LPAxis>(real_axis(path, *path.ws, blk, kind, shift, t_lo, LP_T_CAP));
        ax->tLo = t_lo;
        it = path.axes.emplace(key, std::move(ax)).first;
    }
    return it->second.get();
}

namespace {

/// Under plug flow, what arrives before a response's first time, kept as a point mass there.
void add_early_mass(LaplacePath& path, LPAxis& ax, LPResponse& resp) {
    resp.m0 = 0.0;
    if (!path.inf_pe || ax.kind == LP_INVENTORY || resp.t.size() < 2) return;
    double S = invert_de_hoog(path, *path.ws, *ax.blk, ax.kind, ax.shift, resp.t[0], de_hoog_terms(path), -1);
    if (S > 0 && std::isfinite(S)) {
        resp.m0 = S;
        resp.integral += S;
    }
}

struct LPBalance {
    bool ok, checked;
    double expected, rel;
};

/// A release response's integral against what leaves the path by its last time.
LPBalance mass_balance(LaplacePath& path, LPAxis& ax, const LPResponse& resp, double tol) {
    double T0 = resp.T0;
    if (!(std::fabs(T0) > 1e-30)) return {true, false, T0, 0.0};
    double expected = T0;
    std::size_t n = resp.t.size();
    if (n > 0) {
        double tl = resp.t[n - 1];
        double tt = tl - ax.shift;
        std::optional<LPSaddle> sad = tt > 0 ? saddle_at(ax, tt) : std::nullopt;
        double rest = (sad && !sad->beyond && sad->s <= 0) ? lm_exp(sad->w) : Inf;
        if (!(rest <= 1e-10 * std::fabs(T0))) {
            double S = invert_de_hoog(path, *path.ws, *ax.blk, ax.kind, ax.shift, tl, de_hoog_terms(path), -1);
            if (std::isfinite(S)) expected = S;
        }
    }
    double rel = std::fabs(resp.integral - expected) / ff_max(std::fabs(T0), 1e-10);
    return {rel <= tol, true, expected, rel};
}

}  // namespace

LPResponse unit_response(LaplacePath& path, int i, int j, double t_max) {
    LPBlock* blk = block_of(path, i, j);
    if (!blk) return LPResponse{};
    LPWorkspace& ws = *path.ws;
    int kind = LP_RELEASE;
    double shift = path.inf_pe ? path.tw * blk->Rmin : 0.0;
    double tm = ff_min(t_max, LP_T_CAP);
    double T0 = lp_transfer(path, 0.0, 0.0, i, j).re;
    if (!std::isfinite(T0)) T0 = lp_transfer(path, 1e-300, 0.0, i, j).re;
    LPAxis& ax = *axis_of(path, *blk, kind, shift);
    std::optional<LPSupport> sup = response_support(ax, ax.tLo, LP_T_CAP);
    double t_a = sup ? sup->tLo : NaN;
    double t_b = sup ? ff_min(sup->tHi, tm) : NaN;
    double peak_estimate = sup ? lm_exp(sup->logPeak) : 0.0;
    LPCells cells = make_cells(path, ax, peak_estimate > 0 ? 1e-3 * LP_RESP_ATOL * peak_estimate : 0.0, peak_estimate);
    LPSampler sampler = [&](double t, double atol, LPHint& hint) { return lp_sample(path, ws, ax, t, atol, &hint, &cells); };
    LPResponse resp = (sup && t_b > t_a * (1 + 1e-9))
                          ? compute_response(sampler, t_a, t_b, LP_RESP_PER_DECADE, LP_RESP_MAXPTS, shift, peak_estimate)
                          : LPResponse{};
    add_early_mass(path, ax, resp);
    resp.T0 = T0;
    double tol = ff_max(1e-5, 50 * LP_RESP_RTOL);
    LPBalance bal = mass_balance(path, ax, resp, tol);
    if (!bal.ok) {
        double t_a2 = ff_max(ax.tLo, (sup ? sup->tLo : ax.tLo) / 1e3);
        double t_b2 = sup ? t_b : ff_min(LP_T_CAP, tm);
        if (t_b2 > t_a2 * (1 + 1e-9)) {
            LPResponse r2 = compute_response(sampler, t_a2, t_b2, 2 * LP_RESP_PER_DECADE, 2 * LP_RESP_MAXPTS, shift, peak_estimate);
            add_early_mass(path, ax, r2);
            r2.T0 = T0;
            LPBalance b2 = mass_balance(path, ax, r2, tol);
            if (b2.rel < bal.rel) {
                resp = std::move(r2);
                bal = b2;
            }
        }
    }
    resp.expected = bal.expected;
    resp.balanced = bal.ok;
    resp.rel = bal.rel;
    resp.checked = bal.checked;
    return resp;
}

}  // namespace kompartment::lp
