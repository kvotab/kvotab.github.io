// The far-field path solved in the Laplace domain: the semi-analytical
// alternative to the cells, what the semi-analytical runtime
// (farfield_semi.*) tabulates its unit responses with. A port of the Julia
// package's farfield_laplace.jl, operation for operation.
//
// The path is advection and dispersion along a fracture (TW, Pe) with sorption
// on its coating, diffusion into the rock matrix beside it, and decay and
// ingrowth along the model's decay network; its transfer matrix is a function
// of lower-triangular matrices (Parlett's recurrence, or sums over decay paths
// of divided differences from Taylor series where the diagonal clusters), and
// a response is inverted along a parabola through the saddle point on the real
// axis -- shared parabolas for nearby times, de Hoog's method where those
// fail -- and tabulated on an adaptive grid with its first two derivatives.
//
// The complex arithmetic is Python's complex type as the Python engine uses it
// (CPython's product and its mixed float/complex rules), with the application's
// square root, tanh and Smith's division, and the C library's exp, log and
// trigonometric functions -- each written out here, never std::complex: every
// operation in the Julia package's order, so that the responses are its to
// the last bit. Only what the engine uses is here: the release responses.

#pragma once

#include <array>
#include <cmath>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

namespace kompartment::lp {

/// A path this method cannot solve, and why.
struct LaplacePathError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// Python's `math.log` of zero or below (Julia's `DomainError(x, "math domain error")`).
struct PyLogDomainError : std::domain_error {
    double x;
    explicit PyLogDomainError(double v) : std::domain_error("math domain error"), x(v) {}
};

/// Julia's `floor(Int, x)` or `ceil(Int, x)` of a number with no Int64 to it (an InexactError).
struct JlInexactError : std::runtime_error {
    JlInexactError() : std::runtime_error("InexactError: no Int64 for a whole number this far out") {}
};

inline constexpr int LP_MAX_BLOCK = 16;
inline constexpr int LP_RELEASE = 0;
inline constexpr int LP_INVENTORY = 1;
inline constexpr int LP_DECAYED = 2;
inline constexpr double LP_PI = 3.141592653589793;
inline constexpr double LP_EPS = 2.220446049250313e-16;

/// A complex number as the Julia code holds it (a ComplexF64): no operators but those Julia's
/// own ComplexF64 has where the Julia code uses them (componentwise sums and the negation).
struct Cx {
    double re = 0.0;
    double im = 0.0;
};
inline Cx operator+(Cx a, Cx b) { return {a.re + b.re, a.im + b.im}; }
inline Cx operator-(Cx a, Cx b) { return {a.re - b.re, a.im - b.im}; }
inline Cx operator-(Cx a) { return {-a.re, -a.im}; }
inline const Cx LP_CNAN{std::numeric_limits<double>::quiet_NaN(), std::numeric_limits<double>::quiet_NaN()};

// --- the C library's functions, as Julia's ccalls have them ----------------------------------------
//
// Called through pointers the compiler cannot see through: on Darwin it would make a sin and a cos of
// the same number one call of __sincos_stret, whose bits are not always theirs.
double lm_sin(double x);
double lm_cos(double x);
double lm_exp(double x);
double lm_log(double x);
double lm_log10(double x);
double lm_sinh(double x);
double lm_cosh(double x);
double lm_tanh(double x);
double lm_tan(double x);
double lm_asinh(double x);

// --- complex arithmetic as the Python engine has it ------------------------------------------------

/// CPython's `float * complex`: the float as complex(x, 0.0), then the full product.
inline Cx r_mul(double x, Cx z) { return {x * z.re - 0.0 * z.im, x * z.im + 0.0 * z.re}; }
/// CPython's complex product.
inline Cx c_mul(Cx a, Cx b) { return {a.re * b.re - a.im * b.im, a.re * b.im + a.im * b.re}; }
/// CPython's `x + complex`: the float as complex(x, 0.0).
inline Cx r_add(double x, Cx z) { return {x + z.re, 0.0 + z.im}; }
/// Python's `z == 0` of a complex.
inline bool c_iszero(Cx z) { return z.re == 0 && z.im == 0; }
/// Smith's division, as the application does it; NaN for 0/0.
Cx c_div(Cx a, Cx b);
/// The principal square root; the cut is the negative real axis.
Cx c_sqrt(Cx z);
Cx c_exp(Cx z);
/// tanh, accurate for small arguments and safe for large ones.
Cx c_tanh(Cx z);
/// sech^2 = 1 - tanh^2, without the cancellation near tanh = 1.
Cx c_sech2(Cx z);
/// Python's `math.log`: a domain error at zero and below.
double py_log(double x);
/// `Math.log`: -Infinity at zero and NaN below it.
inline double lp_ln(double x) { return x > 0 ? lm_log(x) : (x == 0 ? -INFINITY : std::numeric_limits<double>::quiet_NaN()); }

// --- the path ---------------------------------------------------------------------------------------

/// Divided differences over subsets of points, and their scratch.
struct LPDD {
    int n = 0;
    int kind = 0;
    double E = 0.0;
    double t = 0.0;
    std::vector<Cx> z, f;
    std::vector<double> sc;
    std::vector<int> cl;
    std::vector<double> dist;
    // The memo of a subset's divided difference, by its mask: a value and the generation it is of.
    std::vector<Cx> memo_val;
    std::vector<std::uint32_t> memo_gen;
    std::uint32_t gen = 1;
    int ncl = 0;
    std::vector<int> cl_mask;
    std::vector<Cx> cl_c;
    std::vector<char> cl_ok;
    std::vector<int> cl_k;
    std::vector<std::vector<Cx>> cl_coef;
    explicit LPDD(int nmax);
};

struct LPWorkspace {
    std::vector<Cx> a, mz, tz, g, v;
    std::vector<double> col;
    std::vector<Cx> L, T, F;
    double E = 0.0;
    LPDD dd;
    long long clustered = 0;
    long long evaluations = 0;
    explicit LPWorkspace(int nmax);
};

/// The block of a pair (i, j): the nuclides on some decay path from j to i, parents first; local
/// index 0 is j and the last is i.
struct LPBlock {
    int i = 0;
    int j = 0;
    std::vector<int> S;
    int m = 0;
    std::vector<double> A;
    std::vector<double> lam, Rf, Rm, De;
    double Rmin = 0.0;
    bool matrix = false;
    double s0 = std::numeric_limits<double>::quiet_NaN();
};

/// The real axis of one pair: the singularity, the scan's points (s, psi), the midpoints and the
/// tilted means between them.
struct LPAxis {
    LPBlock* blk = nullptr;
    int kind = 0;
    double shift = 0.0;
    double s0 = 0.0;
    std::vector<double> s, psi, sm, D;
    double tLo = std::numeric_limits<double>::quiet_NaN();
};

/// A path, ready to be solved (`prepare_path`).
struct LaplacePath {
    int n = 0;
    std::vector<std::string> names;
    double tw = 0, f = 0, Pe = 0;
    bool inf_pe = false;
    double aw = 0, x0 = 0;
    bool inf_x0 = false;
    double rho = 0;
    std::vector<double> lam, Rf, Rm, De;
    std::vector<int> matrix;
    std::vector<std::vector<std::pair<int, double>>> parents;
    std::vector<int> order, pos;
    std::vector<int> reach;   // reach[j*n + i]: j decays (eventually) into i, or is it
    int max_block = 1;
    std::unordered_map<int, std::unique_ptr<LPBlock>> blocks;   // a null block: j never becomes i
    std::map<std::tuple<int, int, int>, std::unique_ptr<LPAxis>> axes;
    std::unique_ptr<LPWorkspace> ws;
    bool reaches(int j, int i) const { return reach[static_cast<std::size_t>(j) * n + i] != 0; }
};

/// A decay table in the builder's layout, as the path reads it.
struct LPDecay {
    std::vector<double> lam;
    std::vector<int> ioff, icnt, ipar;
    std::vector<double> icoef;
};

/// The settings of one combination as numbers: `tw`, `rho_m`, `pe`, `pen_dep` and the surface once,
/// `kd_f`, `eps_m`, `kd_m`, `de_m` one per nuclide.
struct LPSettings {
    std::string surface;
    std::map<std::string, double> single;
    std::map<std::string, std::vector<double>> each;
};

/// A path, ready to be solved; `LaplacePathError` with the reason for what the method cannot solve.
std::unique_ptr<LaplacePath> prepare_path(const LPSettings& settings, const LPDecay* decay, int n,
                                          const std::vector<std::string>* names);

// --- the two scalar functions, their Taylor series and length scales (here for the tests) ---------

Cx tau_at(const LaplacePath& path, Cx z);
double tau_scale(const LaplacePath& path, Cx z);
Cx phi_at(const LaplacePath& path, Cx g);
double h_scale(const LaplacePath& path, Cx g);
std::vector<Cx> sqrt_series(Cx A, Cx B, int K);
std::vector<Cx> tau_series(const LaplacePath& path, Cx c, int K);
std::vector<Cx> h_series(const LaplacePath& path, Cx c, double E, int K);
std::vector<Cx> exp_series(double t, Cx c, int K);

/// The block of a pair, or null when j never becomes i.
LPBlock* block_of(LaplacePath& path, int i, int j);
/// The pair's transform at s, scaled: the value is the result times e^(-ws.E).
Cx eval_block(LaplacePath& path, LPWorkspace& ws, LPBlock& blk, Cx s, int kind);
/// T_ij(s); 0 when j never becomes i.
Cx lp_transfer(LaplacePath& path, double sr, double si, int i, int j);
/// T(0) for every pair, row-major n x n.
std::vector<double> transfer_at_zero(LaplacePath& path);

double singularity(LaplacePath& path, LPBlock& blk, int kind = LP_RELEASE);
LPAxis* axis_of(LaplacePath& path, LPBlock& blk, int kind, double shift);

/// The saddle for time t from the axis's table.
struct LPSaddle {
    double s = 0, psi2 = 0, w = 0;
    bool edge = false, beyond = false;
};
std::optional<LPSaddle> saddle_at(const LPAxis& ax, double t);

/// What an inversion at one time gives: h, h', h'', the error estimate and the condition.
struct LPInv {
    double h = 0, dh = 0, d2 = 0, err = 0, cond = 1;
    bool regrow = false, bad = false;
};
LPInv invert_parabola(LaplacePath& path, LPWorkspace& ws, LPAxis& ax, double t, double atol);
double invert_de_hoog(LaplacePath& path, LPWorkspace& ws, LPBlock& blk, int kind, double shift, double t, int M, int deriv = 0);
int de_hoog_terms(const LaplacePath& path, const LPAxis* ax = nullptr, double t = 0.0);

/// What `_response_support` gives.
struct LPSupport {
    double tLo, tHi, tPeak, logPeak, tTail;
};
std::optional<LPSupport> response_support(const LPAxis& ax, double t_min, double t_max);
double log_estimate(const LPAxis& ax, double t);

double hermite5(double ta, double ya, double da, double ea, double tb, double yb, double db, double eb, double t);

// --- shared contours: one parabola for the times of a cell -----------------------------------------

/// A cell's parabola, built and summed at its probe times, and its nodes (`buildCell`).
struct LPCell {
    bool ok = false;
    double k = 0, tLo = 0, tA = 0, tHi = 0;
    std::string why;
    double v = 0, step = 0;
    int levels = 0;
    double strip = 0, c = 0;
    int n = 0;
    std::vector<double> sr, si, gr, gi, ag, la, mE;
    std::vector<int> lev;
};

/// The cells of one axis, built as times ask for them (`makeCells`).
struct LPCells {
    LPAxis* ax = nullptr;
    std::vector<double> tb, U, sig;
    // By the cell's number, as Julia's Dict{Float64} keys it (isequal: every NaN one key).
    std::unordered_map<std::uint64_t, LPCell> map;
    double peak = 0;
    bool infPe = false;
    double rtol = 1e-11, atol = 0;
    int maxEval = 0;
    // shared, fallback, negligible, cells, failed, dehoog
    long long st_shared = 0, st_fallback = 0, st_negligible = 0, st_cells = 0, st_failed = 0, st_dehoog = 0;
    std::vector<double> pt;
};
LPCells make_cells(LaplacePath& path, LPAxis& ax, double atol, double peak);
double cell_u(const LPCells& C, double tt);
double cell_t(const LPCells& C, double u);
/// The response at t from the shared parabola of t's cell, or nothing when the cell cannot serve t.
std::optional<LPInv> invert_shared(LaplacePath& path, LPWorkspace& ws, LPCells& C, double t);

// --- unit responses on adaptive grids ---------------------------------------------------------------

inline constexpr int LP_RESP_PER_DECADE = 10;
inline constexpr double LP_RESP_RTOL = 2e-8;
inline constexpr double LP_RESP_ATOL = 1e-13;
inline constexpr int LP_RESP_MAXPTS = 6000;
inline constexpr double LP_T_CAP = 1e12;

/// The share of an axis's samples that fell back to de Hoog's method so far.
struct LPHint {
    long long tries = 0;
    long long fails = 0;
};

/// One sample: (h, h', h'', cond, err).
struct LPSample {
    double h, dh, d2, cond, err;
};
LPSample lp_sample(LaplacePath& path, LPWorkspace& ws, LPAxis& ax, double t, double atol, LPHint* hint, LPCells* cells);

/// A response tabulated with its first two derivatives (`computeResponse`), and its integral.
struct LPResponse {
    std::vector<double> t, h, dh, d2h;
    double peak = 0.0;
    double tPeak = std::numeric_limits<double>::quiet_NaN();
    double integral = 0.0;
    double maxCond = 1.0;
    double maxErr = 0.0;
    double m0 = 0.0;
    double T0 = 0.0;
    double expected = 0.0;
    bool balanced = true;
    double rel = 0.0;
    bool checked = false;
};

using LPSampler = std::function<LPSample(double t, double atol, LPHint& hint)>;
LPResponse compute_response(const LPSampler& sampler, double t_a, double t_b, int per, int max_pts, double delay,
                            double peak_estimate);

/// The release of i in response to a unit pulse of j at t = 0, tabulated on an adaptive grid over
/// [0, t_max], its integral held to what leaves the path by its last time and worked out again from
/// far earlier on a finer grid when it misses (`unitResponse`, the default inversion on shared
/// parabolas).
LPResponse unit_response(LaplacePath& path, int i, int j, double t_max);

}  // namespace kompartment::lp
