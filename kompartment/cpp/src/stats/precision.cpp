// How well a calibration's values are known (see precision.hpp): a port of the Julia
// package's stats/precision.jl, operation for operation.

#include "stats/precision.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

#include "stats/normal.hpp"

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
// Julia's `Float64(pi)`.
constexpr double PI = 3.141592653589793;
constexpr double LANCZOS[9] = {0.99999999999980993, 676.5203681218851, -1259.1392167224028,
                               771.32342877765313, -176.61502916214059, 12.507343278686905,
                               -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7};

/// `sqrt`, NaN below nought (`_pr_sqrt`).
double pr_sqrt(double x) { return x >= 0 ? std::sqrt(x) : NaN; }

/// The continued fraction of the incomplete beta function, by Lentz's method.
double beta_fraction(double a, double b, double x) {
    const double tiny = 1e-300;
    const double qab = a + b;
    const double qap = a + 1;
    const double qam = a - 1;
    double c = 1.0;
    double d = 1 - (qab * x) / qap;
    if (std::fabs(d) < tiny) d = tiny;
    d = 1 / d;
    double h = d;
    for (int m = 1; m <= 500; m++) {
        const int m2 = 2 * m;
        double aa = (m * (b - m) * x) / ((qam + m2) * (a + m2));
        d = 1 + aa * d;
        if (std::fabs(d) < tiny) d = tiny;
        c = 1 + aa / c;
        if (std::fabs(c) < tiny) c = tiny;
        d = 1 / d;
        h *= d * c;
        aa = (-(a + m) * (qab + m) * x) / ((a + m2) * (qap + m2));
        d = 1 + aa * d;
        if (std::fabs(d) < tiny) d = tiny;
        c = 1 + aa / c;
        if (std::fabs(c) < tiny) c = tiny;
        d = 1 / d;
        const double step = d * c;
        h *= step;
        if (std::fabs(step - 1) < 1e-15) break;
    }
    return h;
}

/// Inverts a symmetric positive matrix scaled to unit diagonal, by Gauss-Jordan with partial
/// pivoting; none when a pivot falls under `tiny`, which on a matrix of correlations means two
/// columns of J nearly in line.
std::optional<std::vector<std::vector<double>>> invert_scaled(const std::vector<std::vector<double>>& S, double tiny = 1e-12) {
    const std::size_t n = S.size();
    std::vector<std::vector<double>> M;
    for (std::size_t i = 0; i < n; i++) {
        std::vector<double> r(2 * n, 0.0);
        std::copy(S[i].begin(), S[i].end(), r.begin());
        r[n + i] = 1.0;
        M.push_back(std::move(r));
    }
    for (std::size_t c = 0; c < n; c++) {
        std::size_t p = c;
        for (std::size_t r = c + 1; r < n; r++)
            if (std::fabs(M[r][c]) > std::fabs(M[p][c])) p = r;
        if (!(std::fabs(M[p][c]) > tiny)) return std::nullopt;
        std::swap(M[c], M[p]);
        const double piv = M[c][c];
        for (std::size_t k = 0; k < 2 * n; k++) M[c][k] /= piv;
        for (std::size_t r = 0; r < n; r++) {
            if (r == c) continue;
            const double f = M[r][c];
            if (f == 0) continue;
            for (std::size_t k = 0; k < 2 * n; k++) M[r][k] -= f * M[c][k];
        }
    }
    std::vector<std::vector<double>> out;
    for (std::size_t i = 0; i < n; i++) out.emplace_back(M[i].begin() + static_cast<std::ptrdiff_t>(n), M[i].end());
    return out;
}

Json text_or_null(const std::optional<std::string>& s) { return s ? Json(*s) : Json(); }

}  // namespace

double ln_gamma(double x) {
    if (x < 0.5) return std::log(PI / std::fabs(std::sin(PI * x))) - ln_gamma(1 - x);
    const double z = x - 1;
    double a = LANCZOS[0];
    const double t = z + 7.5;
    for (int i = 1; i < 9; i++) a += LANCZOS[i] / (z + i);
    return 0.5 * std::log(2 * PI) + (z + 0.5) * std::log(t) - t + std::log(a);
}

double incomplete_beta(double x, double a, double b) {
    if (!(x > 0)) return 0.0;
    if (!(x < 1)) return 1.0;
    const double front = std::exp(ln_gamma(a + b) - ln_gamma(a) - ln_gamma(b) + a * std::log(x) + b * std::log1p(-x));
    if (x < (a + 1) / (a + b + 2)) return (front * beta_fraction(a, b, x)) / a;
    return 1 - (front * beta_fraction(b, a, 1 - x)) / b;
}

double student_cdf(double t, double dof) {
    const double tail = 0.5 * incomplete_beta(dof / (dof + t * t), dof / 2, 0.5);
    return t >= 0 ? 1 - tail : tail;
}

double student_quantile(double p, double dof) {
    if (!((p > 0 && p < 1) && dof > 0)) return NaN;
    if (p == 0.5) return 0.0;
    if (dof == 1) return std::tan(PI * (p - 0.5));
    if (dof == 2) return (2 * p - 1) / std::sqrt(2 * p * (1 - p));
    if (dof > 1e7) return normal_quantile(p);
    const double q = p > 0.5 ? p : 1 - p;
    double lo = 0.0;
    double hi = 2 * normal_quantile(q);
    if (!(hi > 2)) hi = 2.0;   // Math.max(2, ...)
    while (student_cdf(hi, dof) < q) hi *= 2;
    for (int i = 0; i < 300 && hi - lo > 1e-15 * hi; i++) {
        const double mid = 0.5 * (lo + hi);
        if (student_cdf(mid, dof) < q)
            lo = mid;
        else
            hi = mid;
    }
    const double t = 0.5 * (lo + hi);
    return p > 0.5 ? t : -t;
}

Json precision_of(const PrecisionInput& in) {
    const std::size_t m = in.residuals.size();
    const std::size_t n = in.keys.size();
    std::vector<std::optional<std::string>> held;
    for (std::size_t k = 0; k < n; k++) {
        std::optional<std::string> h = k < in.pinned.size() ? in.pinned[k] : std::nullopt;
        if (!h) h = k < in.failed.size() ? in.failed[k] : std::nullopt;
        if (!h && !in.columns[k]) h = "held";
        held.push_back(h);
    }
    // A value no endpoint moves: its column is nothing, so the matrix would be singular for a
    // reason the reader can be told plainly.
    for (std::size_t k = 0; k < n; k++) {
        if (held[k] || !in.columns[k]) continue;
        const std::vector<double>& col = *in.columns[k];
        bool any = false;
        for (std::size_t i = 0; i < m && !any; i++)
            if (col[i] != 0) any = true;
        if (!any) held[k] = "no effect";
    }
    std::vector<std::size_t> free;
    for (std::size_t k = 0; k < n; k++)
        if (!held[k]) free.push_back(k);
    const std::size_t nf = free.size();
    double ssr = 0.0;
    for (std::size_t i = 0; i < m; i++) ssr += in.residuals[i] * in.residuals[i];
    const long long dof = static_cast<long long>(m) - static_cast<long long>(nf);
    const double t = dof > 0 ? student_quantile(0.5 + in.level / 2, static_cast<double>(dof)) : NaN;
    Json values = Json::array();
    for (std::size_t k = 0; k < n; k++)
        values.push(Json::object({{"key", Json(in.keys[k])},
                                  {"se", Json()},
                                  {"low", Json()},
                                  {"high", Json()},
                                  {"factor", Json()},
                                  {"held", text_or_null(held[k])}}));
    Json out = Json::object({{"targets", Json(static_cast<long long>(m))},
                             {"free", Json(static_cast<long long>(nf))},
                             {"dof", Json(dof)},
                             {"spread", dof > 0 ? Json(pr_sqrt(ssr / static_cast<double>(dof))) : Json()},
                             {"t", dof > 0 ? Json(t) : Json()},
                             {"level", Json(in.level)},
                             {"reason", Json()},
                             {"values", values},
                             {"correlations", Json()}});
    if (nf == 0) {
        out.set("reason", Json("nothing free"));
        return out;
    }

    // J^T J over the values left free, scaled to unit diagonal so that the pivots say how
    // nearly in line two columns are, whatever their units.
    std::vector<std::vector<double>> A;
    for (std::size_t a : free) {
        std::vector<double> row;
        for (std::size_t b : free) {
            double s = 0.0;
            for (std::size_t i = 0; i < m; i++) s += (*in.columns[a])[i] * (*in.columns[b])[i];
            row.push_back(s);
        }
        A.push_back(std::move(row));
    }
    std::vector<double> d;
    for (std::size_t i = 0; i < nf; i++) d.push_back(pr_sqrt(A[i][i]));
    std::vector<std::vector<double>> S(nf, std::vector<double>(nf));
    for (std::size_t i = 0; i < nf; i++)
        for (std::size_t j = 0; j < nf; j++) S[i][j] = A[i][j] / (d[i] * d[j]);
    const auto inverse = invert_scaled(S);
    if (!inverse) {
        out.set("reason", Json("cannot tell apart"));
        return out;
    }
    const std::vector<std::vector<double>>& Sinv = *inverse;
    // The inverse of a symmetric matrix, symmetric to the last bit: the two halves
    // Gauss-Jordan gives differ in it, and a correlation is one number.
    Json matrix = Json::array();
    for (std::size_t a = 0; a < nf; a++) {
        std::vector<double> row;
        for (std::size_t b = 0; b < nf; b++)
            row.push_back(a == b ? 1.0 : (0.5 * (Sinv[a][b] + Sinv[b][a])) / pr_sqrt(Sinv[a][a] * Sinv[b][b]));
        matrix.push(Json::array(row));
    }
    std::vector<std::string> free_keys;
    for (std::size_t k : free) free_keys.push_back(in.keys[k]);
    out.set("correlations", Json::object({{"keys", Json::array(free_keys)}, {"matrix", matrix}}));
    if (!(dof > 0)) {
        out.set("reason", Json("no spare targets"));
        return out;
    }

    const double s2 = ssr / static_cast<double>(dof);
    for (std::size_t a = 0; a < nf; a++) {
        const std::size_t k = free[a];
        // (J^T J)^-1 = D^-1 S^-1 D^-1, so the variance is s^2 S^-1[a][a] / d[a]^2.
        const double se_u = pr_sqrt((s2 * Sinv[a][a]) / (d[a] * d[a]));
        const double v = in.values[k];
        Json& row = values[k];
        if (in.log[k]) {
            const double factor = std::exp(t * se_u);
            row.set("factor", Json(factor));
            row.set("low", Json(v / factor));
            row.set("high", Json(v * factor));
            row.set("se", Json(std::fabs(v) * se_u));
        } else {
            row.set("se", Json(se_u));
            row.set("low", Json(v - t * se_u));
            row.set("high", Json(v + t * se_u));
        }
    }
    return out;
}

}  // namespace kompartment
