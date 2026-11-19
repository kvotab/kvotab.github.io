#include "stats/gsa_design.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <new>
#include <stdexcept>
#include <utility>

#include "stats/correlate.hpp"
#include "stats/normal.hpp"
#include "stats/pdf.hpp"
#include "util/errors.hpp"
#include "util/libm.hpp"

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
constexpr double GD_PI = 3.141592653589793;

// --- Julia's numbers: an Int64 that wraps, or a Float64, and exact comparisons between them -------------

struct JNum {
    bool is_int = true;
    long long i = 0;
    double f = 0.0;
};
JNum jn(long long v) { return {true, v, 0.0}; }
JNum jn(double v) { return {false, 0, v}; }
JNum jn(const Json& v) {
    if (v.is_int()) return jn(static_cast<long long>(v.as_int()));
    if (v.is_bool()) return jn(static_cast<long long>(v.as_bool() ? 1 : 0));
    if (v.is_float()) return jn(v.as_double());
    throw JuliaError("MethodError", "MethodError: arithmetic on " + pd_js_str(v));
}
double dbl(JNum a) { return a.is_int ? static_cast<double>(a.i) : a.f; }
long long wrap_mul(long long a, long long b) {
    return static_cast<long long>(static_cast<unsigned long long>(a) * static_cast<unsigned long long>(b));
}
long long wrap_add(long long a, long long b) {
    return static_cast<long long>(static_cast<unsigned long long>(a) + static_cast<unsigned long long>(b));
}
JNum operator*(JNum a, JNum b) { return a.is_int && b.is_int ? jn(wrap_mul(a.i, b.i)) : jn(dbl(a) * dbl(b)); }
/// Julia's `/`: always a Float64.
double operator/(JNum a, JNum b) { return dbl(a) / dbl(b); }

/// An Int64 against a Float64, exactly, as Julia compares them: -1, 0, 1, or 2 where the double
/// is NaN.
int cmp_int_float(long long i, double f) {
    if (std::isnan(f)) return 2;
    if (f >= 9223372036854775808.0) return -1;
    if (f < -9223372036854775808.0) return 1;
    double tf = std::trunc(f);
    long long ti = static_cast<long long>(tf);
    if (i < ti) return -1;
    if (i > ti) return 1;
    double frac = f - tf;
    return frac > 0 ? -1 : frac < 0 ? 1 : 0;
}
int cmp(JNum a, JNum b) {
    if (a.is_int && b.is_int) return a.i < b.i ? -1 : a.i > b.i ? 1 : 0;
    if (a.is_int) return cmp_int_float(a.i, b.f);
    if (b.is_int) {
        int c = cmp_int_float(b.i, a.f);
        return c == 2 ? 2 : -c;
    }
    if (std::isnan(a.f) || std::isnan(b.f)) return 2;
    return a.f < b.f ? -1 : a.f > b.f ? 1 : 0;
}
bool lt(JNum a, JNum b) { return cmp(a, b) == -1; }
bool le(JNum a, JNum b) {
    int c = cmp(a, b);
    return c == -1 || c == 0;
}
bool gt(JNum a, JNum b) { return cmp(a, b) == 1; }
bool ge(JNum a, JNum b) {
    int c = cmp(a, b);
    return c == 1 || c == 0;
}

/// `Number.isInteger`.
bool is_integer(JNum v) { return v.is_int || (std::isfinite(v.f) && v.f == std::floor(v.f)); }

/// Why a design past `GSA_MOST` is refused.
constexpr const char* GD_TOO_MANY = "These settings ask for more than can be counted exactly, let alone run; give smaller numbers.";

/// A whole number as an Int where it is one, as Python's arithmetic keeps it.
Json gd_whole(double v) {
    if (std::isfinite(v) && v == std::floor(v) && std::fabs(v) < GSA_MOST) return Json(static_cast<long long>(v));
    return Json(v);
}

/// Julia's `fld` of two Int64s: division rounded down.
long long fld(long long a, long long b) {
    if (b == 0) throw JuliaError("DivideError", "DivideError: integer division error");
    if (b == -1) return static_cast<long long>(0ULL - static_cast<unsigned long long>(a));
    long long q = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))) q -= 1;
    return q;
}

/// Julia's `max` of two Float64s: NaN if either is, +0 above -0.
double jl_max(double a, double b) {
    if (std::isnan(a) || std::isnan(b)) return NaN;
    if (a == b) return std::signbit(a) ? b : a;
    return a > b ? a : b;
}

/// `n!` in floating point, multiplied as the application's recursion multiplies it.
double gd_factorial(long long n) {
    double f = 1.0;
    for (long long i = 2; i <= n; i++) f = static_cast<double>(i) * f;
    return f;
}

/// `zeros(rows, cols)`'s room, refused as Julia refuses it.
std::vector<double> zeros_of(long long rows, long long cols) { return jl_zeros(jl_array_count(rows, cols)); }

GsaDesign new_design(int K, long long runs) {
    GsaDesign d;
    d.K = K;
    d.runs = runs;
    d.u = zeros_of(K, runs);
    return d;
}

Json rows_json(const std::vector<std::vector<double>>& rows) {
    Json out = Json::array();
    for (const auto& r : rows) out.push(Json::array(r));
    return out;
}

// --- the methods' settings ------------------------------------------------------------------------

enum class SetKind { Choice, Int, Number, Switch };

struct Setting {
    std::string key;
    SetKind kind;
    std::function<Json(long long)> fallback;
    std::vector<std::string> choices;
};

Setting choice(std::string key, std::string d, std::vector<std::string> choices) {
    return {std::move(key), SetKind::Choice, [d](long long) { return Json(d); }, std::move(choices)};
}
Setting count(std::string key, long long d) { return {std::move(key), SetKind::Int, [d](long long) { return Json(d); }, {}}; }
Setting number(std::string key, double d) { return {std::move(key), SetKind::Number, [d](long long) { return Json(d); }, {}}; }
Setting toggle(std::string key, bool d) { return {std::move(key), SetKind::Switch, [d](long long) { return Json(d); }, {}}; }

const std::vector<std::pair<std::string, std::vector<Setting>>>& gsa_methods() {
    static const std::vector<std::pair<std::string, std::vector<Setting>>> methods = {
        {"morris",
         {choice("design", "walks", {"walks", "trajectories"}), count("trajectories", 10), count("points", 10), count("levels", 100),
          count("candidates", 0), toggle("relative", false), count("resamples", 100)}},
        {"sobol",
         {count("samples", 1000), toggle("second", false), count("blocks", 1),
          choice("estimator", "jansen1999", {"jansen1999", "sobol2007", "homma1996", "janon2014"}), count("resamples", 100)}},
        {"efast", {count("samples", 1000), count("harmonics", 4)}},
        {"rbdfast", {count("samples", 1000), count("harmonics", 6)}},
        {"ff", {number("low", 0.05), number("high", 0.95), toggle("pairs", false)}},
        {"dgsm", {count("samples", 100), number("step", 0.001), toggle("crossed", false), count("resamples", 100)}},
        {"radial", {count("samples", 100), count("resamples", 100)}},
        // Song, Nelson and Staum's advice: over random orders, one outer sample and three
        // inner ones; over all of them (K!, affordable to four), more outer samples.
        {"shapley",
         {Setting{"perms", SetKind::Int, [](long long K) { return Json(K <= 4 ? 0LL : 100LL); }, {}}, count("nVar", 1000),
          Setting{"nOuter", SetKind::Int, [](long long K) { return Json(K <= 4 ? 10LL : 1LL); }, {}}, count("nInner", 3)}},
    };
    return methods;
}

const std::vector<Setting>* find_method(const Json& method) {
    if (!method.is_string()) return nullptr;
    for (const auto& [name, settings] : gsa_methods())
        if (method.as_string() == name) return &settings;
    return nullptr;
}

/// A count a builder takes. `gsa_refusal` has turned away every setting that is not a whole
/// number below `GSA_MOST`, so each is an Int by the time a builder reads it.
long long count_arg(const Json& o, const char* key) {
    const Json& v = o.get(key);
    if (!v.is_int()) throw std::logic_error(std::string("a design's ") + key + " is not a whole number past its refusal");
    return v.as_int();
}

/// The Fisher-Yates pick `floor(next() * (i + 1))`.
long long pick(Mulberry32& g, long long i) { return static_cast<long long>(std::floor(g.next() * static_cast<double>(i + 1))); }

/// `n` evenly spaced from `a` to `b`, both included.
std::vector<double> linspace(double a, double b, long long n) {
    if (n <= 0) return {};
    if (n == 1) return {a};
    double step = (b - a) / static_cast<double>(n - 1);
    std::vector<double> out(static_cast<std::size_t>(n));
    for (long long i = 0; i < n; i++) out[static_cast<std::size_t>(i)] = a + static_cast<double>(i) * step;
    out[static_cast<std::size_t>(n - 1)] = b;
    return out;
}

/// SALib's `sum_distances` of a set of candidates: the root of the summed squared pair distances.
double spread(const std::vector<long long>& set, const std::vector<std::vector<double>>& D) {
    double s = 0.0;
    for (std::size_t x = 0; x < set.size(); x++)
        for (std::size_t y = x + 1; y < set.size(); y++) {
            double v = D[static_cast<std::size_t>(set[x])][static_cast<std::size_t>(set[y])];
            s += v * v;
        }
    return std::sqrt(s);
}

/// The position of the largest, the last of equals, as numpy's `argsort()[-1]` has it.
std::size_t last_max(const std::vector<double>& values) {
    std::size_t best = 0;
    for (std::size_t i = 1; i < values.size(); i++)
        if (values[i] >= values[best]) best = i;
    return best;
}

// --- Shapley's copula ------------------------------------------------------------------------------

/// A standard normal from two uniforms, Box-Muller; the stream decides both.
double gaussian(Mulberry32& g) {
    double u = g.next();
    while (!(u > 0)) u = g.next();
    double v = g.next();
    return std::sqrt(-2 * std::log(u)) * lm_cos((2 * GD_PI) * v);
}

/// The inputs' joint law in probability space: independent, or a Gaussian copula.
struct Copula {
    long long K;
    const std::vector<double>* corr;
    Mulberry32& next;
    std::map<std::vector<long long>, std::optional<std::vector<double>>> cache;
};

std::vector<double> sub(const Copula& law, const std::vector<long long>& idx) {
    std::vector<double> out;
    out.reserve(idx.size() * idx.size());
    for (long long a : idx)
        for (long long b : idx) out.push_back((*law.corr)[static_cast<std::size_t>(a * law.K + b)]);
    return out;
}

/// z ~ N(mu, L L').
std::vector<double> draw_z(Copula& law, std::size_t m, const std::vector<double>& L, const std::vector<double>* mu) {
    std::vector<double> e(m);
    for (std::size_t i = 0; i < m; i++) e[i] = gaussian(law.next);
    std::vector<double> z(m, 0.0);
    for (std::size_t a = 0; a < m; a++) {
        double s = mu == nullptr ? 0.0 : (*mu)[a];
        for (std::size_t b = 0; b <= a; b++) s += L[a * m + b] * e[b];
        z[a] = s;
    }
    return z;
}

std::vector<double> phi_of(std::vector<double> z) {
    for (double& x : z) x = normal_phi(x);
    return z;
}

/// `n` draws of the inputs `idx` (from 0) from their joint marginal, a row each.
std::vector<std::vector<double>> subset(Copula& law, const std::vector<long long>& idx, long long n) {
    std::vector<std::vector<double>> out;
    if (law.corr == nullptr) {
        for (long long r = 0; r < n; r++) {
            std::vector<double> row(idx.size());
            for (double& x : row) x = law.next.next();
            out.push_back(std::move(row));
        }
        return out;
    }
    auto it = law.cache.find(idx);
    if (it == law.cache.end()) it = law.cache.emplace(idx, gsa_cholesky(sub(law, idx), static_cast<long long>(idx.size()))).first;
    if (!it->second) throw ArgumentError("The correlations between these inputs are not a valid correlation matrix.");
    const std::vector<double>& L = *it->second;
    for (long long r = 0; r < n; r++) out.push_back(phi_of(draw_z(law, idx.size(), L, nullptr)));
    return out;
}

/// `n` draws of the inputs `plus` given `minus` (from 0) at the probabilities `u_minus`.
std::vector<std::vector<double>> given(Copula& law, const std::vector<long long>& plus, const std::vector<long long>& minus,
                                       const std::vector<double>& u_minus, long long n) {
    std::vector<std::vector<double>> out;
    if (law.corr == nullptr) {
        for (long long r = 0; r < n; r++) {
            std::vector<double> row(plus.size());
            for (double& x : row) x = law.next.next();
            out.push_back(std::move(row));
        }
        return out;
    }
    // GlobalSensitivity.jl's find_cond_mean_var: B - C'D^-1 C, and C'D^-1 times the
    // conditioning values as normal scores.
    const std::vector<double>& corr = *law.corr;
    long long K = law.K;
    std::size_t p = plus.size(), q = minus.size();
    std::vector<double> z_minus(u_minus.size());
    for (std::size_t r = 0; r < u_minus.size(); r++) z_minus[r] = normal_quantile(u_minus[r]);
    std::optional<std::vector<double>> Ld_ = gsa_cholesky(sub(law, minus), static_cast<long long>(q));
    if (!Ld_) throw ArgumentError("The correlations between these inputs are not a valid correlation matrix.");
    const std::vector<double>& Ld = *Ld_;
    // Solve D X = C for X = D^-1 C, one column per member of `plus`.
    std::vector<double> X(q * p, 0.0);
    for (std::size_t c = 0; c < p; c++) {
        std::vector<double> col(q);
        for (std::size_t r = 0; r < q; r++) col[r] = corr[static_cast<std::size_t>(minus[r] * K + plus[c])];
        std::vector<double> w(q, 0.0);
        for (std::size_t r = 0; r < q; r++) {
            double s = col[r];
            for (std::size_t l = 0; l < r; l++) s -= Ld[r * q + l] * w[l];
            w[r] = s / Ld[r * q + r];
        }
        for (std::size_t rr = q; rr-- > 0;) {
            double s = w[rr];
            for (std::size_t l = rr + 1; l < q; l++) s -= Ld[l * q + rr] * X[l * p + c];
            X[rr * p + c] = s / Ld[rr * q + rr];
        }
    }
    std::vector<double> mu(p, 0.0), cov(p * p, 0.0);
    for (std::size_t a = 0; a < p; a++) {
        double s = 0.0;
        for (std::size_t r = 0; r < q; r++) s += X[r * p + a] * z_minus[r];
        mu[a] = s;
        for (std::size_t b = 0; b < p; b++) {
            double c = corr[static_cast<std::size_t>(plus[a] * K + plus[b])];
            for (std::size_t r = 0; r < q; r++) c -= corr[static_cast<std::size_t>(minus[r] * K + plus[a])] * X[r * p + b];
            cov[a * p + b] = c;
        }
    }
    // Symmetrised, and a variance rounding made a hair negative is zero.
    for (std::size_t a = 0; a < p; a++)
        for (std::size_t b = a + 1; b < p; b++) {
            double v = (cov[a * p + b] + cov[b * p + a]) / 2;
            cov[a * p + b] = v;
            cov[b * p + a] = v;
        }
    std::optional<std::vector<double>> L_ = gsa_cholesky(cov, static_cast<long long>(p));
    std::vector<double> L = L_ ? *L_ : gsa_jitter_cholesky(cov, static_cast<long long>(p));
    for (long long r = 0; r < n; r++) out.push_back(phi_of(draw_z(law, p, L, &mu)));
    return out;
}

}  // namespace

// --- the pieces ------------------------------------------------------------------------------------

long long gsa_int32(double v) {
    if (!std::isfinite(v)) return 0;
    double r = std::fmod(std::trunc(v), 4294967296.0);
    if (r < 0) r += 4294967296.0;
    return r >= 2147483648.0 ? static_cast<long long>(r - 4294967296.0) : static_cast<long long>(r);
}

double gsa_round(double x) {
    if (!std::isfinite(x)) return x;
    double f = std::floor(x);
    return x - f >= 0.5 ? f + 1 : f;
}

double gsa_sinpi(double x) {
    if (!std::isfinite(x)) return NaN;
    double r = std::fmod(x, 2.0);
    if (r < 0) r += 2;
    if (r < 0.25) return lm_sin(GD_PI * r);
    if (r < 0.75) return lm_cos(GD_PI * (r - 0.5));
    if (r < 1.25) return -lm_sin(GD_PI * (r - 1));
    if (r < 1.75) return -lm_cos(GD_PI * (r - 1.5));
    return lm_sin(GD_PI * (r - 2));
}

std::vector<long long> gsa_random_permutation(long long n, Mulberry32& g) {
    std::vector<long long> p;
    for (long long i = 0; i < n; i++) p.push_back(i);
    for (long long i = static_cast<long long>(p.size()) - 1; i >= 1; i--) {
        long long j = pick(g, i);
        std::swap(p[static_cast<std::size_t>(i)], p[static_cast<std::size_t>(j)]);
    }
    return p;
}

std::vector<std::vector<long long>> gsa_permutations(long long n) {
    std::vector<std::vector<long long>> out;
    std::vector<long long> a;
    for (long long i = 0; i < n; i++) a.push_back(i);
    while (true) {
        out.push_back(a);
        long long i = n - 2;
        while (i >= 0 && a[static_cast<std::size_t>(i)] >= a[static_cast<std::size_t>(i + 1)]) i--;
        if (i < 0) return out;
        long long j = n - 1;
        while (a[static_cast<std::size_t>(j)] <= a[static_cast<std::size_t>(i)]) j--;
        std::swap(a[static_cast<std::size_t>(i)], a[static_cast<std::size_t>(j)]);
        std::reverse(a.begin() + (i + 1), a.end());
    }
}

std::vector<std::vector<int>> gsa_hadamard(long long k) {
    if (!(k >= 2 && (k & (k - 1)) == 0))
        throw ArgumentError("A Hadamard matrix of order " + std::to_string(k) + " is not a power of two from 2 up");
    std::size_t n = static_cast<std::size_t>(k);
    std::vector<std::vector<int>> h(n, std::vector<int>(n, 1));
    h[1][1] = -1;
    std::size_t bot = 2, right = 2;
    while (bot < n) {
        for (std::size_t r = 0; r < bot; r++)
            for (std::size_t c = 0; c < right; c++) {
                int v = h[r][c];
                h[r][right + c] = v;
                h[bot + r][c] = v;
                h[bot + r][right + c] = -v;
            }
        bot *= 2;
        right *= 2;
    }
    return h;
}

std::optional<std::vector<double>> gsa_cholesky(const std::vector<double>& A, long long n_) {
    std::size_t n = static_cast<std::size_t>(n_);
    std::vector<double> L(n * n, 0.0);
    for (std::size_t j = 0; j < n; j++)
        for (std::size_t i = j; i < n; i++) {
            double s = A[i * n + j];
            for (std::size_t l = 0; l < j; l++) s -= L[i * n + l] * L[j * n + l];
            if (i == j) {
                if (!(s > 1e-14)) return std::nullopt;
                L[j * n + j] = std::sqrt(s);
            } else {
                L[i * n + j] = s / L[j * n + j];
            }
        }
    return L;
}

std::vector<double> gsa_jitter_cholesky(const std::vector<double>& A, long long n) {
    double eps = 1e-12;
    while (eps < 1) {
        std::vector<double> B = A;
        for (long long i = 0; i < n; i++) B[static_cast<std::size_t>(i * n + i)] += eps;
        std::optional<std::vector<double>> L = gsa_cholesky(B, n);
        if (L) return *L;
        eps *= 10;
    }
    throw ArgumentError("A conditional covariance could not be factorised.");
}

// --- the settings ----------------------------------------------------------------------------------

std::vector<std::string> gsa_method_names() {
    std::vector<std::string> out;
    for (const auto& m : gsa_methods()) out.push_back(m.first);
    return out;
}

Json gsa_options(const Json& method, long long K, const Json* given) {
    Json out = Json::object();
    const std::vector<Setting>* spec = find_method(method);
    if (spec == nullptr) return out;
    for (const Setting& s : *spec) {
        const Json* want = nullptr;
        if (given != nullptr && given->is_object()) {
            want = given->obj().find(s.key);
            if (want != nullptr && want->is_null()) want = nullptr;   // `get(given, key, nothing)`
        }
        Json d = s.fallback(K);
        if (s.kind == SetKind::Switch) {
            out.set(s.key, want == nullptr ? d : Json(pd_truthy(want)));
        } else if (s.kind == SetKind::Choice) {
            bool ok = want != nullptr && want->is_string() &&
                      std::find(s.choices.begin(), s.choices.end(), want->as_string()) != s.choices.end();
            out.set(s.key, ok ? Json(want->as_string()) : d);
        } else {
            double v = (want == nullptr || (want->is_string() && want->as_string().empty())) ? NaN : pd_to_number(want);
            out.set(s.key, std::isfinite(v) ? (s.kind == SetKind::Int ? gd_whole(gsa_round(v)) : Json(v)) : d);
        }
    }
    return out;
}

Json gsa_runs(const Json& method, long long K, const Json* options) {
    Json o = gsa_options(method, K, options);
    // In doubles, in the application's order.
    auto f = [&](const char* key) { return dbl(jn(o.get(key))); };
    const double k = static_cast<double>(K);
    double runs;
    if (method == "morris") {
        runs = f("trajectories") * (o.get("design") == "trajectories" ? k + 1 : f("points"));
    } else if (method == "radial") {
        runs = f("samples") * (k + 1);
    } else if (method == "sobol") {
        runs = f("blocks") * (o.get("second").as_bool() ? 2 * k + 2 : k + 2) * f("samples");
    } else if (method == "efast") {
        runs = k * dbl(jn(efast_samples(o.get("samples"), o.get("harmonics"))));
    } else if (method == "rbdfast") {
        runs = f("samples");
    } else if (method == "ff") {
        long long k2 = 2;
        while (k2 < K) k2 *= 2;
        runs = static_cast<double>(2 * k2);
    } else if (method == "dgsm") {
        runs = f("samples") * (1 + k + (o.get("crossed").as_bool() ? (k * (k - 1)) / 2 : 0.0));
    } else if (method == "shapley") {
        const double orders = gt(jn(o.get("perms")), jn(0LL)) ? f("perms") : gd_factorial(K);
        runs = f("nVar") + orders * (k - 1) * f("nOuter") * f("nInner");
    } else {
        return Json(0);
    }
    return gd_whole(runs);
}

std::optional<std::string> gsa_refusal(const Json& method, long long K, const Json* options) {
    Json o = gsa_options(method, K, options);
    if (find_method(method) == nullptr) return "There is no method called " + pd_js_str(method) + ".";
    if (K < 1) return std::string("Nothing is sampled, so there is nothing to vary.");
    auto num = [&](const char* key) { return jn(o.get(key)); };
    auto positive = [](JNum v) { return is_integer(v) && ge(v, jn(1LL)); };
    const std::string& m = method.as_string();
    if (m == "morris") {
        if (!positive(num("trajectories")) || !ge(num("points"), jn(2LL)) || !ge(num("levels"), jn(2LL)))
            return std::string("Morris needs at least one trajectory of two points, over at least two levels.");
        if (o.get("design") == "trajectories" && lt(jn(0LL), num("candidates")) && lt(num("candidates"), num("trajectories")))
            return std::string("Fewer candidates than trajectories to keep; 0 keeps every one drawn.");
    } else if (m == "radial") {
        if (!ge(num("samples"), jn(2LL))) return std::string("The radial design needs at least two base points.");
    } else if (m == "sobol") {
        if (!(ge(num("samples"), jn(2LL)) && positive(num("blocks")))) return std::string("Sobol needs at least two samples and one block.");
        if (gt(num("blocks"), jn(1LL)) && gt(num("blocks"), num("samples"))) return std::string("More blocks than samples.");
    } else if (m == "efast" || m == "rbdfast") {
        if (!(ge(num("samples"), jn(8LL)) && positive(num("harmonics"))))
            return std::string("This needs at least a few samples and one harmonic.");
        if (m == "rbdfast" && ge(jn(2LL) * num("harmonics"), jn(num("samples") / jn(2LL))))
            return std::string("Too many harmonics for so few samples.");
    } else if (m == "ff") {
        if (!(gt(num("low"), jn(0LL)) && lt(num("high"), jn(1LL)) && lt(num("low"), num("high"))))
            return std::string("The two levels must be probabilities, the low one below the high.");
    } else if (m == "dgsm") {
        if (!ge(num("samples"), jn(2LL))) return std::string("DGSM needs at least two points.");
        if (!(gt(num("step"), jn(0LL)) && lt(num("step"), jn(0.5)))) return std::string("The step must be a small probability.");
    } else if (m == "shapley") {
        if (le(num("perms"), jn(0LL)) && K > 8) {
            std::string k = pd_js_number_str(static_cast<double>(K));
            return "All " + k + "! orders of " + k + " inputs is too many; give a number of random orders.";
        }
        if (!(ge(num("nVar"), jn(2LL)) && positive(num("nOuter")) && ge(num("nInner"), jn(2LL))))
            return std::string("Shapley needs at least two variance samples, one outer and two inner samples.");
    }
    // Past what a double counts one by one, a setting, or the runs it makes, would hang eFAST's
    // search for its points, or ask for more than any machine could lay out.
    for (const Setting& s : *find_method(method))
        if (s.kind == SetKind::Int && !(std::fabs(dbl(num(s.key.c_str()))) < GSA_MOST)) return std::string(GD_TOO_MANY);
    if (!(dbl(jn(gsa_runs(method, K, &o))) < GSA_MOST)) return std::string(GD_TOO_MANY);
    return std::nullopt;
}

// --- Morris: GlobalSensitivity.jl's random walks, and Morris's own trajectories ---------------------------

GsaDesign morris_design(int K, long long trajectories, long long points, long long levels, Mulberry32& next) {
    if (!(levels >= 2)) throw ArgumentError("Morris needs at least two levels.");
    if (!(points >= 2)) throw ArgumentError("A Morris trajectory needs at least two points.");
    long long runs = wrap_mul(trajectories, points);
    GsaDesign d = new_design(K, runs);
    std::vector<long long> at(static_cast<std::size_t>(K), 0);
    for (long long t = 0; t < trajectories; t++) {
        for (int k = 0; k < K; k++) at[static_cast<std::size_t>(k)] = gsa_int32(std::floor(next.next() * static_cast<double>(levels)));
        for (long long s = 0; s < points; s++) {
            long long j = static_cast<long long>(std::floor(next.next() * static_cast<double>(K)));
            long long step = next.next() < 0.5 ? -1 : 1;
            if (0 <= j && j < K) {
                long long& aj = at[static_cast<std::size_t>(j)];
                aj = gsa_int32(static_cast<double>(aj + step));
                if (aj > levels - 1) aj -= 2;
                else if (aj < 0) aj += 2;
            }
            for (int k = 0; k < K; k++)
                d.u[static_cast<std::size_t>((t * points + s) * K + k)] = (static_cast<double>(at[static_cast<std::size_t>(k)]) + 0.5) / static_cast<double>(levels);
        }
    }
    d.fields = Json::object({{"method", Json("morris")}, {"K", Json(K)}, {"trajectories", Json(trajectories)}, {"points", Json(points)},
                             {"levels", Json(levels)}, {"u", Json()}, {"runs", Json(runs)}});
    return d;
}

std::vector<std::vector<long long>> morris_trajectory(int K, long long p, Mulberry32& g) {
    long long half = p / 2;
    std::vector<int> order(static_cast<std::size_t>(K));
    for (int i = 0; i < K; i++) order[static_cast<std::size_t>(i)] = i;
    for (long long i = K - 1; i >= 1; i--) std::swap(order[static_cast<std::size_t>(i)], order[static_cast<std::size_t>(pick(g, i))]);
    std::vector<long long> direction(static_cast<std::size_t>(K));
    for (auto& dir : direction) dir = g.next() < 0.5 ? -1 : 1;
    std::vector<long long> at(static_cast<std::size_t>(K));
    for (auto& a : at) a = static_cast<long long>(std::floor(g.next() * static_cast<double>(half)));
    for (int k = 0; k < K; k++)
        if (direction[static_cast<std::size_t>(k)] < 0) at[static_cast<std::size_t>(k)] += half;
    std::vector<std::vector<long long>> rows;
    rows.reserve(static_cast<std::size_t>(K) + 1);
    rows.push_back(at);
    for (int k : order) {
        at[static_cast<std::size_t>(k)] += direction[static_cast<std::size_t>(k)] * half;
        rows.push_back(at);
    }
    return rows;
}

double trajectory_distance(const std::vector<std::vector<long long>>& a, const std::vector<std::vector<long long>>& b) {
    double s = 0.0;
    for (const auto& ra : a)
        for (const auto& rb : b) {
            double q = 0.0;
            for (std::size_t k = 0; k < ra.size(); k++) {
                double t = static_cast<double>(ra[k]) - static_cast<double>(rb.at(k));
                q += t * t;
            }
            s += std::sqrt(q);
        }
    return a == b ? 0.0 : static_cast<double>(static_cast<float>(s));
}

std::vector<long long> optimal_trajectories(const std::vector<std::vector<std::vector<long long>>>& candidates, long long k) {
    long long N = static_cast<long long>(candidates.size());
    std::vector<long long> all;
    if (k >= N) {
        for (long long i = 0; i < N; i++) all.push_back(i);
        return all;
    }
    std::size_t n = static_cast<std::size_t>(N);
    std::vector<std::vector<double>> D(n, std::vector<double>(n, 0.0));
    for (std::size_t j = 0; j < n; j++)
        for (std::size_t l = j + 1; l < n; l++) {
            double d = trajectory_distance(candidates[j], candidates[l]);
            D[j][l] = d;
            D[l][j] = d;
        }
    std::vector<std::vector<std::size_t>> by_row(n);
    for (std::size_t r = 0; r < n; r++) by_row[r] = np_argsort(D[r]);
    std::vector<std::vector<long long>> tried;
    std::vector<double> scores;
    for (long long i = 1; i <= k - 1; i++) {
        // Each row's i farthest, and the row itself.
        std::vector<std::vector<long long>> sets;
        for (std::size_t r = 0; r < n; r++) {
            std::vector<long long> s;
            for (long long t = N - 1; t >= N - i; t--) s.push_back(static_cast<long long>(by_row[r][static_cast<std::size_t>(t)]));
            s.push_back(static_cast<long long>(r));
            sets.push_back(std::move(s));
        }
        std::vector<double> spreads;
        for (const auto& s : sets) spreads.push_back(spread(s, D));
        std::vector<long long> best = sets[last_max(spreads)];
        for (long long g = 1; g <= k - i - 1; g++) {
            std::vector<std::vector<long long>> grown;
            for (long long c = 0; c < N; c++)
                if (std::find(best.begin(), best.end(), c) == best.end()) {
                    std::vector<long long> s = best;
                    s.push_back(c);
                    grown.push_back(std::move(s));
                }
            std::vector<double> sp;
            for (const auto& s : grown) sp.push_back(spread(s, D));
            best = grown.at(last_max(sp));
        }
        scores.push_back(spread(best, D));
        tried.push_back(std::move(best));
    }
    if (tried.empty()) throw ArgumentError("Fewer than two trajectories to keep among the candidates.");
    std::vector<long long> out = tried[last_max(scores)];
    std::sort(out.begin(), out.end());
    return out;
}

GsaDesign morris_trajectory_design(int K, long long trajectories, long long levels, long long candidates, Mulberry32& next) {
    long long p = std::max(2LL, wrap_mul(2, jl_to_int(gsa_round(static_cast<double>(levels) / 2))));
    long long drawn = std::max(trajectories, candidates);
    std::vector<std::vector<std::vector<long long>>> everyone;
    for (long long t = 0; t < drawn; t++) everyone.push_back(morris_trajectory(K, p, next));
    std::vector<long long> keep;
    if (drawn > trajectories) {
        keep = optimal_trajectories(everyone, trajectories);
    } else {
        for (long long t = 0; t < drawn; t++) keep.push_back(t);
    }
    long long points = K + 1;
    long long runs = wrap_mul(static_cast<long long>(keep.size()), points);
    GsaDesign d = new_design(K, runs);
    for (std::size_t t = 0; t < keep.size(); t++) {
        const auto& rows = everyone[static_cast<std::size_t>(keep[t])];
        for (long long r = 0; r < points; r++)
            for (int k = 0; k < K; k++)
                d.u[static_cast<std::size_t>((static_cast<long long>(t) * points + r) * K + k)] =
                    (static_cast<double>(rows[static_cast<std::size_t>(r)][static_cast<std::size_t>(k)]) + 0.5) / static_cast<double>(p);
    }
    d.fields = Json::object({{"method", Json("morris")}, {"design", Json("trajectories")}, {"K", Json(K)},
                             {"trajectories", Json(static_cast<long long>(keep.size()))}, {"points", Json(points)}, {"levels", Json(p)},
                             {"candidates", Json(drawn)}, {"u", Json()}, {"runs", Json(runs)}});
    return d;
}

// --- the radial design, Campolongo, Saltelli and Cariboni 2011 -------------------------------------------

GsaDesign radial_design(int K, const std::vector<std::vector<double>>& base, const std::vector<std::vector<double>>& step) {
    long long N = base.empty() ? 0 : static_cast<long long>(base[0].size());
    long long per = K + 1;
    GsaDesign d = new_design(K, wrap_mul(N, per));
    for (int k = 0; k < K; k++)
        for (long long i = 0; i < N; i++) {
            for (long long r = 0; r < per; r++)
                d.u[static_cast<std::size_t>((i * per + r) * K + k)] = base[static_cast<std::size_t>(k)][static_cast<std::size_t>(i)];
            d.u[static_cast<std::size_t>((i * per + 1 + k) * K + k)] = step[static_cast<std::size_t>(k)][static_cast<std::size_t>(i)];
        }
    d.fields = Json::object({{"method", Json("radial")}, {"K", Json(K)}, {"N", Json(N)}, {"per", Json(per)}, {"u", Json()},
                             {"runs", Json(d.runs)}});
    return d;
}

// --- Sobol: Saltelli's design ------------------------------------------------------------------------

GsaDesign sobol_design(int K, long long n, bool second, long long blocks,
                       const std::function<std::vector<double>(int, const std::string&, long long)>& draw) {
    long long per = wrap_mul(second ? 2LL * K + 2 : static_cast<long long>(K) + 2, n);
    GsaDesign d = new_design(K, wrap_mul(blocks, per));
    auto place = [&](int k, const std::vector<double>& src, long long offset) {
        for (long long r = 0; r < n; r++) d.u[static_cast<std::size_t>((offset + r) * K + k)] = src.at(static_cast<std::size_t>(r));
    };
    for (long long b = 0; b < blocks; b++) {
        long long base = b * per;
        for (int k = 0; k < K; k++) {
            std::vector<double> A = draw(k, "A", b);
            std::vector<double> B = draw(k, "B", b);
            place(k, A, base);
            place(k, B, base + n);
            // A with column j from B, for each j; then B with column j from A.
            for (int j = 1; j <= K; j++) place(k, k + 1 == j ? B : A, base + (1 + j) * n);
            if (second)
                for (int j = 1; j <= K; j++) place(k, k + 1 == j ? A : B, base + (1 + K + j) * n);
        }
    }
    d.fields = Json::object({{"method", Json("sobol")}, {"K", Json(K)}, {"n", Json(n)}, {"second", Json(second)}, {"blocks", Json(blocks)},
                             {"u", Json()}, {"runs", Json(d.runs)}});
    return d;
}

// --- eFAST and RBD-FAST --------------------------------------------------------------------------------

Json efast_samples(const Json& n, const Json& M_) {
    if (!M_.is_int()) throw JuliaError("MethodError", "MethodError: no method matching efast_samples with harmonics " + pd_js_str(M_));
    long long M = M_.as_int();
    // `4.0 * M * M + 1`, in doubles as the application works it out.
    const double m = static_cast<double>(M);
    double N = jl_max(gsa_round(dbl(jn(n))), 4.0 * m * m + 1);
    if (!(std::isfinite(N) && M >= 1)) throw ArgumentError("eFAST needs a number of points and at least one harmonic.");
    // A start that cannot be counted one by one is given back unsearched; its design is refused.
    if (!(N < GSA_MOST)) return Json(N);
    long long Ni = jl_to_int(N);
    long long twoM = 2 * M;
    while (true) {
        long long w = fld(Ni - 1, twoM);
        if (fld(w, twoM) >= 1 && M * w <= fld(Ni, 2) - 1) return Json(Ni);
        Ni += 1;
    }
}

std::vector<double> efast_frequencies(long long K, long long N, long long M) {
    if (K < 1) throw ArgumentError("eFAST needs an input.");
    double twoM = static_cast<double>(wrap_mul(2, M));
    std::vector<double> omega{std::floor(static_cast<double>(N - 1) / twoM)};
    double m = std::floor(omega[0] / twoM);
    if (m >= static_cast<double>(K - 1)) {
        // floor.(Int, range(1, m, length = K - 1))
        std::vector<double> r;
        if (K - 1 == 1) {
            r.push_back(1.0);
        } else {
            for (long long i = 0; i <= K - 2; i++) r.push_back(1 + (static_cast<double>(i) * (m - 1)) / static_cast<double>(K - 2));
        }
        for (double x : r) omega.push_back(std::floor(x));
    } else {
        for (long long i = 0; i <= K - 2; i++) omega.push_back(m != 0 ? std::fmod(static_cast<double>(i), m) + 1 : NaN);
    }
    return omega;
}

GsaDesign efast_design(int K, long long N, long long harmonics, const std::vector<double>& phases) {
    std::vector<double> omega = efast_frequencies(K, N, harmonics);
    GsaDesign d = new_design(K, wrap_mul(K, N));
    std::vector<double> temp(static_cast<std::size_t>(K), 0.0);
    std::vector<double> s(static_cast<std::size_t>(std::max(0LL, N)));
    for (long long r = 0; r < N; r++) s[static_cast<std::size_t>(r)] = (2 / static_cast<double>(N)) * static_cast<double>(r);
    for (int i = 0; i < K; i++) {
        temp[static_cast<std::size_t>(i)] = omega[0];
        for (int k = 0; k < i; k++) temp[static_cast<std::size_t>(k)] = omega[static_cast<std::size_t>(k + 1)];
        for (int k = i + 1; k < K; k++) temp[static_cast<std::size_t>(k)] = omega[static_cast<std::size_t>(k)];
        double phi0 = phases.at(static_cast<std::size_t>(i));
        for (int j = 0; j < K; j++)
            for (long long r = 0; r < N; r++)
                d.u[static_cast<std::size_t>((i * N + r) * K + j)] =
                    0.5 + (1 / GD_PI) * lm_asin(gsa_sinpi(temp[static_cast<std::size_t>(j)] * s[static_cast<std::size_t>(r)] + phi0));
    }
    d.fields = Json::object({{"method", Json("efast")}, {"K", Json(K)}, {"N", Json(N)}, {"harmonics", Json(harmonics)},
                             {"omega", Json::array(omega)}, {"u", Json()}, {"runs", Json(d.runs)}});
    return d;
}

GsaDesign rbd_fast_design(int K, long long N, const std::vector<std::vector<long long>>& perms) {
    std::vector<double> s0 = linspace(-GD_PI, GD_PI, N);
    std::vector<double> s = zeros_of(K, N);   // K x N, a column after another
    GsaDesign d = new_design(K, N);
    for (int k = 0; k < K; k++)
        for (long long i = 0; i < N; i++) {
            double sk = s0.at(static_cast<std::size_t>(perms[static_cast<std::size_t>(k)].at(static_cast<std::size_t>(i))));
            s[static_cast<std::size_t>(i * K + k)] = sk;
            d.u[static_cast<std::size_t>(i * K + k)] = 0.5 + lm_asin(lm_sin(sk)) / GD_PI;
        }
    std::vector<std::vector<double>> rows(static_cast<std::size_t>(K));
    for (int k = 0; k < K; k++)
        for (long long i = 0; i < N; i++) rows[static_cast<std::size_t>(k)].push_back(s[static_cast<std::size_t>(i * K + k)]);
    d.fields = Json::object({{"method", Json("rbdfast")}, {"K", Json(K)}, {"N", Json(N)}, {"s", rows_json(rows)}, {"u", Json()},
                             {"runs", Json(N)}});
    return d;
}

// --- a two-level fractional factorial of resolution IV (Saltelli 2008, eq. 2.31) --------------------

GsaDesign ff_design(int K, double low, double high) {
    long long k2 = 2;
    while (k2 < K) k2 *= 2;
    std::vector<std::vector<int>> H = gsa_hadamard(k2);
    long long rows = 2 * k2;
    std::vector<std::vector<int>> signs = H;
    for (const auto& row : H) {
        std::vector<int> neg(row.size());
        for (std::size_t c = 0; c < row.size(); c++) neg[c] = -row[c];
        signs.push_back(std::move(neg));
    }
    GsaDesign d = new_design(K, rows);
    for (int k = 0; k < K; k++)
        for (long long r = 0; r < rows; r++)
            d.u[static_cast<std::size_t>(r * K + k)] = signs[static_cast<std::size_t>(r)][static_cast<std::size_t>(k)] > 0 ? high : low;
    Json signs_json = Json::array();
    for (const auto& row : signs) {
        Json r = Json::array();
        for (int v : row) r.push(Json(v));
        signs_json.push(r);
    }
    d.fields = Json::object({{"method", Json("ff")}, {"K", Json(K)}, {"rows", Json(rows)}, {"signs", signs_json}, {"low", Json(low)},
                             {"high", Json(high)}, {"u", Json()}, {"runs", Json(rows)}});
    return d;
}

// --- DGSM: Sobol and Kucherenko's derivative-based measures ------------------------------------------

GsaDesign dgsm_design(int K, const std::vector<std::vector<double>>& base, double step, bool crossed) {
    long long N = base.empty() ? 0 : static_cast<long long>(base[0].size());
    long long per = 1 + K + (crossed ? (static_cast<long long>(K) * (K - 1)) / 2 : 0);
    // h[k][i]: the step input k takes at point i
    std::vector<std::vector<double>> h(static_cast<std::size_t>(K), std::vector<double>(static_cast<std::size_t>(N)));
    for (int k = 0; k < K; k++)
        for (long long i = 0; i < N; i++) {
            double b = base[static_cast<std::size_t>(k)][static_cast<std::size_t>(i)];
            h[static_cast<std::size_t>(k)][static_cast<std::size_t>(i)] = b + step < 1 ? step : -step;
        }
    GsaDesign d = new_design(K, wrap_mul(N, per));
    auto U = [&](int k, long long col) -> double& { return d.u[static_cast<std::size_t>(col * K + k)]; };
    for (int k = 0; k < K; k++)
        for (long long i = 0; i < N; i++)
            for (long long r = 0; r < per; r++) U(k, i * per + r) = base[static_cast<std::size_t>(k)][static_cast<std::size_t>(i)];
    for (int k = 0; k < K; k++)
        for (long long i = 0; i < N; i++) U(k, i * per + 1 + k) += h[static_cast<std::size_t>(k)][static_cast<std::size_t>(i)];
    if (crossed) {
        long long p = 1 + K;
        for (int a = 0; a < K; a++)
            for (int c = a + 1; c < K; c++) {
                for (long long i = 0; i < N; i++) {
                    U(a, i * per + p) += h[static_cast<std::size_t>(a)][static_cast<std::size_t>(i)];
                    U(c, i * per + p) += h[static_cast<std::size_t>(c)][static_cast<std::size_t>(i)];
                }
                p += 1;
            }
    }
    Json hv = Json::array();
    for (long long i = 0; i < N; i++)
        for (int k = 0; k < K; k++) hv.push(Json(h[static_cast<std::size_t>(k)][static_cast<std::size_t>(i)]));
    d.fields = Json::object({{"method", Json("dgsm")}, {"K", Json(K)}, {"N", Json(N)}, {"per", Json(per)}, {"step", Json(step)},
                             {"crossed", Json(crossed)}, {"h", hv}, {"u", Json()}, {"runs", Json(d.runs)}});
    return d;
}

// --- Shapley effects: Song, Nelson and Staum's algorithm ---------------------------------------------

GsaDesign shapley_design(int K, long long perms, long long n_var, long long n_outer, long long n_inner,
                         const std::vector<double>* corr, Mulberry32& next) {
    if (perms < -1) throw ArgumentError("Invalid array length");
    std::vector<std::vector<long long>> orders;
    if (perms == -1) {
        orders = gsa_permutations(K);
    } else {
        for (long long t = 0; t < perms; t++) orders.push_back(gsa_random_permutation(K, next));
    }
    // (A correlation matrix with fewer than K x K numbers is Julia's BoundsError, at the first draw.)
    if (corr != nullptr && corr->size() < static_cast<std::size_t>(K) * static_cast<std::size_t>(K))
        throw JuliaError("BoundsError", "BoundsError: a correlation matrix of " + std::to_string(corr->size()) + " numbers for " +
                                            std::to_string(K) + " inputs");
    Copula law{K, corr, next, {}};
    long long runs = wrap_add(n_var, wrap_mul(wrap_mul(wrap_mul(static_cast<long long>(orders.size()), K - 1), n_outer), n_inner));
    GsaDesign d = new_design(K, std::max(0LL, runs));
    d.runs = runs;
    long long at = 0;
    long long cols = std::max(0LL, runs);
    auto column = [&](long long c) {
        if (c >= cols) throw JuliaError("BoundsError", "BoundsError: a run past the design's");
        return d.u.data() + static_cast<std::size_t>(c * K);
    };
    std::vector<long long> everyone;
    for (long long k = 0; k < K; k++) everyone.push_back(k);
    for (const auto& row : subset(law, everyone, n_var)) {
        double* u = column(at);
        for (int k = 0; k < K; k++) u[k] = row[static_cast<std::size_t>(k)];
        at += 1;
    }
    for (const auto& perm : orders)
        for (int j = 1; j <= K - 1; j++) {
            std::vector<long long> plus(perm.begin(), perm.begin() + j);
            std::vector<long long> minus(perm.begin() + j, perm.end());
            for (const auto& fixed : subset(law, minus, n_outer))
                for (const auto& drawn : given(law, plus, minus, fixed, n_inner)) {
                    double* u = column(at);
                    for (std::size_t a = 0; a < plus.size(); a++) u[plus[a]] = drawn[a];
                    for (std::size_t b = 0; b < minus.size(); b++) u[minus[b]] = fixed[b];
                    at += 1;
                }
        }
    Json orders_json = Json::array();
    for (const auto& o : orders) {
        Json r = Json::array();
        for (long long v : o) r.push(Json(v));
        orders_json.push(r);
    }
    d.fields = Json::object({{"method", Json("shapley")}, {"K", Json(K)}, {"orders", orders_json}, {"nVar", Json(n_var)},
                             {"nOuter", Json(n_outer)}, {"nInner", Json(n_inner)}, {"correlated", Json(corr != nullptr)}, {"u", Json()},
                             {"runs", Json(runs)}});
    return d;
}

// --- a design from a run's seed --------------------------------------------------------------------

GsaDesign build_design(const Json& method, const std::vector<std::string>& keys, const Json* options, const Json& seed,
                       const std::vector<double>* corr) {
    int K = static_cast<int>(keys.size());
    Json o = gsa_options(method, K, options);
    std::optional<std::string> refused = gsa_refusal(method, K, &o);
    if (refused) throw ArgumentError(*refused);
    const std::vector<std::string>& names = keys;
    // The seed is read where Julia reads it: at the first stream drawn.
    auto stream = [&](const std::string& name) { return stream_for(seed, name); };
    auto col = [&](const std::string& name, long long n) {
        Mulberry32 g = stream(name);
        return uniforms(n, g, true);
    };
    const std::string& m = method.as_string();
    GsaDesign d;
    if (m == "morris") {
        Mulberry32 nxt = stream("#gsa#morris");
        if (o.get("design") == "trajectories") {
            d = morris_trajectory_design(K, count_arg(o, "trajectories"), count_arg(o, "levels"), count_arg(o, "candidates"), nxt);
        } else {
            d = morris_design(K, count_arg(o, "trajectories"), count_arg(o, "points"), count_arg(o, "levels"), nxt);
        }
    } else if (m == "radial") {
        const long long n = count_arg(o, "samples");
        std::vector<std::vector<double>> base, step;
        for (const auto& k : names) base.push_back(col(k + "#radial#base", n));
        for (const auto& k : names) step.push_back(col(k + "#radial#step", n));
        d = radial_design(K, base, step);
    } else if (m == "sobol") {
        const long long n = count_arg(o, "samples");
        d = sobol_design(K, n, o.get("second").as_bool(), count_arg(o, "blocks"), [&](int k, const std::string& which, long long b) {
            return col(names[static_cast<std::size_t>(k)] + "#sobol#" + which + "#" + std::to_string(b), n);
        });
    } else if (m == "efast") {
        const long long N = efast_samples(o.get("samples"), o.get("harmonics")).as_int();
        std::vector<double> phases;
        for (const auto& k : names) {
            Mulberry32 g = stream(k + "#efast");
            phases.push_back(2 * g.next());
        }
        d = efast_design(K, N, count_arg(o, "harmonics"), phases);
    } else if (m == "rbdfast") {
        const long long n = count_arg(o, "samples");
        std::vector<std::vector<long long>> perms;
        for (const auto& k : names) {
            Mulberry32 g = stream(k + "#rbdfast");
            perms.push_back(gsa_random_permutation(n, g));
        }
        d = rbd_fast_design(K, n, perms);
    } else if (m == "ff") {
        d = ff_design(K, o.get("low").as_double(), o.get("high").as_double());
    } else if (m == "dgsm") {
        const long long n = count_arg(o, "samples");
        std::vector<std::vector<double>> base;
        for (const auto& k : names) base.push_back(col(k + "#dgsm", n));
        d = dgsm_design(K, base, o.get("step").as_double(), o.get("crossed").as_bool());
    } else {   // shapley: gsa_refusal has turned away any other name
        const long long perms = count_arg(o, "perms");
        Mulberry32 nxt = stream("#gsa#shapley");
        d = shapley_design(K, perms > 0 ? perms : -1, count_arg(o, "nVar"), count_arg(o, "nOuter"), count_arg(o, "nInner"), corr, nxt);
    }
    d.fields.set("options", o);
    // What the intervals are drawn from, so that reading the table again gives the same one.
    d.fields.set("seed", seed);
    return d;
}

}  // namespace kompartment
