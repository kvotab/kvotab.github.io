#include "stats/correlate.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <set>
#include <unordered_map>
#include <utility>

#include "engine/project.hpp"
#include "stats/normal.hpp"
#include "stats/pdf.hpp"
#include "stats/sample.hpp"
#include "util/errors.hpp"

namespace kompartment {

namespace {

/// A value in a message, or `?` for none (`v ?? '?'`).
std::string or_q(const Json* v) { return pd_nullish(v) ? "?" : pd_js_str(v); }

/// How many characters Julia's iteration finds in a text: one per code point of well-formed
/// UTF-8 (a byte that is not, one each).
std::size_t chars_in(std::string_view s) {
    std::size_t n = 0;
    for (std::size_t i = 0; i < s.size();) {
        unsigned char c = static_cast<unsigned char>(s[i]);
        std::size_t len = c < 0x80 ? 1 : (c & 0xe0) == 0xc0 ? 2 : (c & 0xf0) == 0xe0 ? 3 : (c & 0xf8) == 0xf0 ? 4 : 1;
        bool ok = i + len <= s.size();
        for (std::size_t k = 1; ok && k < len; k++) ok = (static_cast<unsigned char>(s[i + k]) & 0xc0) == 0x80;
        i += ok ? len : 1;
        n++;
    }
    return n;
}

/// `s = 0; for (v of values) s += v`: a sum in order.
double seq_sum(const double* v, std::size_t n) {
    double s = 0.0;
    for (std::size_t i = 0; i < n; i++) s += v[i];
    return s;
}

/// `a < b` as numpy's sort compares: NaN after everything, -0 equal to +0.
bool np_less(double a, double b) { return a < b || (std::isnan(b) && !std::isnan(a)); }

/// `Float64Array.from(values).sort()`: ascending, -0 before +0, NaN last.
std::vector<double> typed_sort(const std::vector<double>& values) {
    std::vector<double> s = values;
    std::stable_sort(s.begin(), s.end(), np_less);
    std::vector<std::size_t> zeros;
    for (std::size_t i = 0; i < s.size(); i++)
        if (s[i] == 0.0) zeros.push_back(i);
    if (!zeros.empty()) {
        std::size_t negative = 0;
        for (std::size_t i : zeros)
            if (std::signbit(s[i])) negative++;
        for (std::size_t k = 0; k < zeros.size(); k++) s[zeros[k]] = k < negative ? -0.0 : 0.0;
    }
    return s;
}

/// The `j` of each Fisher-Yates step, `i` from `n - 1` down to 1: `floor(next() * (i + 1))`.
std::vector<std::size_t> fisher_yates_picks(Mulberry32& nxt, std::size_t n) {
    std::vector<std::size_t> out;
    if (n < 2) return out;
    out.reserve(n - 1);
    for (std::size_t i = n - 1; i >= 1; i--) out.push_back(static_cast<std::size_t>(std::floor(nxt.next() * static_cast<double>(i + 1))));
    return out;
}

/// The identity of order `size`, flat, row-major.
std::vector<double> identity(std::size_t size) {
    std::vector<double> out(size * size, 0.0);
    for (std::size_t i = 0; i < size; i++) out[i * size + i] = 1.0;
    return out;
}

/// The sample correlation matrix of the columns of `scores` (n x size, a column after another), flat.
std::vector<double> correlation_of(const std::vector<double>& scores, std::size_t n, std::size_t size) {
    std::vector<double> mean(size);
    for (std::size_t j = 0; j < size; j++) mean[j] = seq_sum(scores.data() + j * n, n) / static_cast<double>(n);
    std::vector<double> cov(size * size, 0.0);
    std::vector<double> d(n), di(n);
    for (std::size_t i = 0; i < size; i++) {
        for (std::size_t r = 0; r < n; r++) di[r] = scores[i * n + r] - mean[i];
        for (std::size_t j = i; j < size; j++) {
            double mj = mean[j];
            for (std::size_t r = 0; r < n; r++) d[r] = di[r] * (scores[j * n + r] - mj);
            cov[i * size + j] = seq_sum(d.data(), n);
        }
    }
    std::vector<double> out(size * size, 0.0);
    for (std::size_t i = 0; i < size; i++)
        for (std::size_t j = i; j < size; j++) {
            double c = cov[i * size + j] / std::sqrt(cov[i * size + i] * cov[j * size + j]);
            out[i * size + j] = c;
            out[j * size + i] = c;
        }
    return out;
}

/// Cholesky, lower triangular, flat; a pivot below 1e-12 is floored there (rounding, not repair).
std::vector<double> cholesky(const std::vector<double>& a, std::size_t size) {
    std::vector<double> low(size * size, 0.0);
    for (std::size_t i = 0; i < size; i++)
        for (std::size_t j = 0; j <= i; j++) {
            double s = a[i * size + j];
            for (std::size_t l = 0; l < j; l++) s -= low[i * size + l] * low[j * size + l];
            if (i == j) low[i * size + i] = pd_sqrt(pd_jmax(s, 1e-12));
            else low[i * size + j] = s / low[j * size + j];
        }
    return low;
}

/// The inverse of a lower-triangular matrix, by forward substitution; flat.
std::vector<double> invert_lower(const std::vector<double>& low, std::size_t size) {
    std::vector<double> out(size * size, 0.0);
    for (std::size_t col = 0; col < size; col++)
        for (std::size_t i = 0; i < size; i++) {
            double s = i == col ? 1.0 : 0.0;
            for (std::size_t l = 0; l < i; l++) s -= low[i * size + l] * out[l * size + col];
            out[i * size + col] = s / low[i * size + i];
        }
    return out;
}

/// Eigenvalues and eigenvectors of a symmetric matrix by cyclic Jacobi; vectors are columns.
std::pair<std::vector<double>, std::vector<double>> jacobi_eigen(const std::vector<double>& a0, std::size_t size) {
    std::vector<double> a = a0;
    std::vector<double> v = identity(size);
    for (int sweep = 1; sweep <= 100; sweep++) {
        double off = 0.0;
        for (std::size_t i = 0; i < size; i++)
            for (std::size_t j = i + 1; j < size; j++) off += a[i * size + j] * a[i * size + j];
        if (off < 1e-22) break;
        for (std::size_t p = 0; p < size; p++)
            for (std::size_t q = p + 1; q < size; q++) {
                double apq = a[p * size + q];
                if (std::fabs(apq) < 1e-300) continue;
                double theta = (a[q * size + q] - a[p * size + p]) / (2 * apq);
                double sign = (theta == 0 || std::isnan(theta)) ? 1.0 : std::copysign(1.0, theta);
                double t = sign / (std::fabs(theta) + std::sqrt(theta * theta + 1));
                double c = 1 / std::sqrt(t * t + 1);
                double s = t * c;
                for (std::size_t k = 0; k < size; k++) {
                    double akp = a[k * size + p], akq = a[k * size + q];
                    a[k * size + p] = c * akp - s * akq;
                    a[k * size + q] = s * akp + c * akq;
                }
                for (std::size_t k = 0; k < size; k++) {
                    double apk = a[p * size + k], aqk = a[q * size + k];
                    a[p * size + k] = c * apk - s * aqk;
                    a[q * size + k] = s * apk + c * aqk;
                }
                for (std::size_t k = 0; k < size; k++) {
                    double vkp = v[k * size + p], vkq = v[k * size + q];
                    v[k * size + p] = c * vkp - s * vkq;
                    v[k * size + q] = s * vkp + c * vkq;
                }
            }
    }
    std::vector<double> values(size);
    for (std::size_t i = 0; i < size; i++) values[i] = a[i * size + i];
    return {values, v};
}

/// Moves a symmetric unit-diagonal matrix, in place, to a correlation matrix near it:
/// eigenvalues below 1e-6 lifted to it and the matrix rebuilt, then the diagonal scaled back
/// to one. Returns the largest change to any coefficient.
double nearest_correlation(std::vector<double>& c, std::size_t size) {
    auto [values, vectors] = jacobi_eigen(c, size);
    const double floor_ = 1e-6;
    bool all = true;
    for (double v : values)
        if (!(v >= floor_)) all = false;
    if (all) return 0.0;
    std::vector<double> before = c;
    for (std::size_t i = 0; i < size; i++)
        for (std::size_t j = 0; j < size; j++) {
            double s = 0.0;
            for (std::size_t l = 0; l < size; l++) s += vectors[i * size + l] * pd_jmax(values[l], floor_) * vectors[j * size + l];
            c[i * size + j] = s;
        }
    std::vector<double> d(size);
    for (std::size_t i = 0; i < size; i++) d[i] = pd_sqrt(c[i * size + i]);
    for (std::size_t i = 0; i < size; i++)
        for (std::size_t j = 0; j < size; j++) c[i * size + j] = c[i * size + j] / (d[i] * d[j]);
    double worst = 0.0;
    for (std::size_t i = 0; i < c.size(); i++) worst = pd_jmax(worst, std::fabs(c[i] - before[i]));
    return worst;
}

}  // namespace

std::vector<std::size_t> np_argsort(const std::vector<double>& v) {
    std::vector<std::size_t> order(v.size());
    for (std::size_t i = 0; i < v.size(); i++) order[i] = i;
    std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) { return np_less(v[a], v[b]); });
    return order;
}

CorrelationPairs correlation_pairs(const Json* simulation, const std::vector<std::string>& names) {
    std::unordered_map<std::string, int> at;
    for (std::size_t k = 0; k < names.size(); k++) at[names[k]] = static_cast<int>(k);
    CorrelationPairs out;
    std::set<std::pair<int, int>> seen;
    auto add = [&](int i, int j, double r, const std::string& where) {
        if (i == j) {
            out.problems.push_back(where + ": an input cannot be correlated with itself.");
            return;
        }
        std::pair<int, int> key = i < j ? std::make_pair(i, j) : std::make_pair(j, i);
        if (seen.count(key)) {
            out.problems.push_back(where + ": " + names[static_cast<std::size_t>(i)] + " and " + names[static_cast<std::size_t>(j)] +
                                   " are correlated twice; the first coefficient is kept.");
            return;
        }
        seen.insert(key);
        out.pairs.push_back(CorrelationPair{std::min(i, j), std::max(i, j), r});
    };
    // What is gone through: a list's items, a dictionary's keys, a text's characters, a number
    // or a Boolean once -- as Julia's `for c in list` goes through them. Only a list's items
    // can be dictionaries; everything else reads as one without a key.
    static const Json nothing_here;
    const Json* correlations = pd_prop(simulation, "correlations");
    std::vector<const Json*> list;
    if (!pd_nullish(correlations)) {
        if (correlations->is_array()) {
            for (const Json& c : correlations->arr()) list.push_back(&c);
        } else if (correlations->is_object()) {
            list.assign(correlations->obj().size(), &nothing_here);
        } else if (correlations->is_string()) {
            list.assign(chars_in(correlations->as_string()), &nothing_here);
        } else {
            list.push_back(&nothing_here);
        }
    }
    for (const Json* c : list) {
        const Json* r_raw = pd_prop(c, "r");
        double r = pd_to_number(r_raw);
        const Json* group = pd_prop(c, "group");
        std::string where = pd_truthy(group) ? "group " + pd_js_str(group)
                                             : or_q(pd_prop(c, "a")) + " \xe2\x80\x93 " + or_q(pd_prop(c, "b"));
        if (!std::isfinite(r) || r < -1 || r > 1) {
            out.problems.push_back(where + ": a correlation is a number between -1 and 1, not " + pd_js_str(r_raw) + ".");
            continue;
        }
        if (!pd_nullish(group)) {
            // Every sampled index of the parameter: `Kd[...]`, and the bare name for a
            // parameter with no index -- which has one slot, and is said.
            std::string prefix = pd_js_str(group) + "[";
            std::vector<int> members;
            for (std::size_t k = 0; k < names.size(); k++) {
                const std::string& n = names[k];
                if ((group->is_string() && n == group->as_string()) || n.compare(0, prefix.size(), prefix) == 0)
                    members.push_back(static_cast<int>(k));
            }
            if (members.size() < 2) {
                out.problems.push_back(where + ": " + (members.size() == 1 ? "only one" : "no") +
                                       " sampled index carries that name, so there is nothing to correlate it with.");
                continue;
            }
            for (std::size_t x = 0; x < members.size(); x++)
                for (std::size_t y = x + 1; y < members.size(); y++) add(members[x], members[y], r, where);
            continue;
        }
        const Json* a = pd_prop(c, "a");
        const Json* b = pd_prop(c, "b");
        auto i = at.find(pd_js_str(a));
        auto j = at.find(pd_js_str(b));
        if (i == at.end() || j == at.end()) {
            std::vector<const Json*> missing;
            if (i == at.end() && pd_truthy(a)) missing.push_back(a);
            if (j == at.end() && pd_truthy(b)) missing.push_back(b);
            std::string said;
            for (std::size_t k = 0; k < missing.size(); k++) said += (k ? " and " : "") + pd_js_str(missing[k]);
            out.problems.push_back(where + ": " + said + " " + (missing.size() == 1 ? "is" : "are") +
                                   " not a sampled input of this model (spelled as in the sampling plan, e.g. Kd[Tc-99]).");
            continue;
        }
        add(i->second, j->second, r, where);
    }
    return out;
}

CorrelationPairs correlation_pairs(const Project& project, const std::vector<std::string>& names) {
    return correlation_pairs(&project.simulation, names);
}

CorrelationPairs correlation_pairs_of_model(const Json& model, const std::vector<std::string>& names) {
    return correlation_pairs(pd_prop(model, "simulation"), names);
}

ImanConover iman_conover(std::vector<std::vector<double>>& columns, const std::vector<CorrelationPair>& pairs,
                         const std::vector<std::string>& names, std::uint32_t seed_bits) {
    ImanConover out;
    if (pairs.empty()) return out;
    std::size_t n = columns.empty() ? 0 : columns[0].size();
    // Two realisations cannot carry a correlation, and one cannot be ranked.
    if (n < 3) return out;

    std::set<int> taking;
    for (const auto& p : pairs) {
        taking.insert(p.a);
        taking.insert(p.b);
    }
    std::vector<int> involved(taking.begin(), taking.end());
    std::size_t size = involved.size();
    std::map<int, std::size_t> pos;
    for (std::size_t i = 0; i < size; i++) pos[involved[i]] = i;

    // The target, and the nearest correlation matrix to it when it is not one.
    std::vector<double> target = identity(size);
    for (const auto& p : pairs) {
        std::size_t i = pos[p.a], j = pos[p.b];
        target[i * size + j] = p.r;
        target[j * size + i] = p.r;
    }
    out.adjusted = nearest_correlation(target, size);
    std::vector<double> chol_target = cholesky(target, size);

    // Scores: normal quantiles of evenly spaced probabilities, shuffled on a stream named for
    // the input.
    std::vector<double> base(n);
    for (std::size_t i = 1; i <= n; i++) base[i - 1] = *normal_probit(static_cast<double>(i) / static_cast<double>(n + 1));
    std::vector<double> scores(n * size);   // a column after another
    for (std::size_t j = 0; j < size; j++) {
        std::size_t k = static_cast<std::size_t>(involved[j]);
        std::string name = k < names.size() ? names[k] : "undefined";
        Mulberry32 nxt = stream_for(seed_bits, "correlation:" + name);
        std::vector<double> col = base;
        std::vector<std::size_t> picks = fisher_yates_picks(nxt, n);
        for (std::size_t step = 0; step + 1 < n; step++) {
            std::size_t i = n - 1 - step;
            std::swap(col[i], col[picks[step]]);
        }
        std::copy(col.begin(), col.end(), scores.begin() + static_cast<std::ptrdiff_t>(j * n));
    }

    // What the scores correlate to by accident, taken out; what is wanted, put in:
    // T = S (P F^-1)^T.
    std::vector<double> chol_scores = cholesky(correlation_of(scores, n, size), size);
    std::vector<double> inv = invert_lower(chol_scores, size);
    std::vector<double> m(size * size, 0.0);   // P F^-1
    for (std::size_t i = 0; i < size; i++)
        for (std::size_t j = 0; j < size; j++) {
            double s = 0.0;
            for (std::size_t l = 0; l < size; l++) s += chol_target[i * size + l] * inv[l * size + j];
            m[i * size + j] = s;
        }
    std::vector<double> t_mat(n * size);
    for (std::size_t i = 0; i < size; i++) {
        std::vector<double> s(n, 0.0);
        for (std::size_t j = 0; j < size; j++) {
            double mij = m[i * size + j];
            for (std::size_t r = 0; r < n; r++) s[r] = s[r] + scores[j * n + r] * mij;
        }
        std::copy(s.begin(), s.end(), t_mat.begin() + static_cast<std::ptrdiff_t>(i * n));
    }

    // Each input takes the rank pattern of its column of T: the realisation holding the largest
    // score gets the input's largest value, and so on.
    for (std::size_t j = 0; j < size; j++) {
        std::vector<double>& col = columns.at(static_cast<std::size_t>(involved[j]));
        // (A column shorter than the first is Julia's BoundsError.)
        if (col.size() < n) throw JuliaError("BoundsError", "BoundsError: a column shorter than the first");
        std::vector<double> ordered = typed_sort(col);
        std::vector<double> tj(t_mat.begin() + static_cast<std::ptrdiff_t>(j * n), t_mat.begin() + static_cast<std::ptrdiff_t>((j + 1) * n));
        std::vector<std::size_t> order = np_argsort(tj);
        for (std::size_t rank = 0; rank < order.size(); rank++) col[order[rank]] = ordered[rank];
    }
    out.columns = involved;
    return out;
}

}  // namespace kompartment
