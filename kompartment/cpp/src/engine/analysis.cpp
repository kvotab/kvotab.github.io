// The bands of a probabilistic run (see analysis.hpp): a port of the part of the Julia
// package's engine/analysis.jl the service reads, operation for operation.

#include "engine/analysis.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <set>

#include "stats/pdf.hpp"
#include "util/errors.hpp"

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();

/// Julia's `isless` for two finite doubles: -0 before 0.
bool jl_less(double a, double b) { return a < b || (a == b && std::signbit(a) && !std::signbit(b)); }

/// `s[min(n - 1, max(0, k)) + 1]`: an order statistic, the position clamped into the sample.
double order_stat(const std::vector<double>& s, long long k) {
    long long n = static_cast<long long>(s.size());
    return s[static_cast<std::size_t>(std::min(n - 1, std::max(0LL, k)))];
}

}  // namespace

std::size_t an_count(const ProbabilisticResults& r) { return r.outputs.size() + r.inputs.size(); }

const Json& an_output(const ProbabilisticResults& r, std::size_t k) {
    return k <= r.outputs.size() ? r.outputs.at(k - 1) : r.inputs.at(k - 1 - r.outputs.size()).get("output");
}

bool an_flat(const ProbabilisticResults& r, std::size_t k) { return k > r.outputs.size(); }

long long an_drawn_from(const ProbabilisticResults& r, std::size_t k) {
    return k <= r.outputs.size() ? 0 : r.inputs.at(k - 1 - r.outputs.size()).get("k").as_int();
}

SeriesMatrix an_matrix(const ProbabilisticResults& r, std::size_t k) {
    SeriesMatrix M;
    if (k <= r.outputs.size()) {
        const std::size_t w = k - 1;
        if (w >= (r.single() ? r.values32.size() : r.values.size()))
            throw JuliaError("BoundsError", "BoundsError: series " + std::to_string(k) + " of " + std::to_string(r.outputs.size()));
        M.rows = r.held();
        M.cols = r.times();
        M.data.assign(static_cast<std::size_t>(M.rows) * M.cols, 0.0);
        for (long long i = 0; i < M.rows; i++)
            for (std::size_t j = 0; j < M.cols; j++) M.data[j * static_cast<std::size_t>(M.rows) + static_cast<std::size_t>(i)] = r.value(w, i, j);
        return M;
    }
    // A varied parameter: its draws, NaN where the realisation did not run.
    const std::size_t from = static_cast<std::size_t>(an_drawn_from(r, k) - 1);
    M.rows = r.samples.realisations;
    M.cols = 1;
    M.data.resize(static_cast<std::size_t>(M.rows));
    for (long long i = 0; i < M.rows; i++) {
        double v = r.samples(from, i);
        if (r.ran.at(static_cast<std::size_t>(i)) == 0) v = NaN;
        M.data[static_cast<std::size_t>(i)] = v;
    }
    return M;
}

std::size_t an_index(const ProbabilisticResults& r, const std::string& label) {
    for (std::size_t k = 1; k <= an_count(r); k++)
        if (an_output(r, k).get("label") == label) return k;
    throw JuliaError("KeyError", "KeyError: key " + julia_quote("No series labelled '" + label + "'") + " not found");
}

long long mask_length(const Json& mask) {
    switch (mask.type()) {
        case Json::Type::Array:
        case Json::Type::Object: return static_cast<long long>(mask.size());
        case Json::Type::String: {
            long long n = 0;
            for (unsigned char c : mask.as_string())
                if ((c & 0xc0) != 0x80) n++;
            return n;
        }
        case Json::Type::Null:
            throw JuliaError("MethodError", "MethodError: no method matching length(::Nothing)");
        default: return 1;
    }
}

bool an_keep(const Json* mask, long long i) {
    if (mask == nullptr) return true;
    if (i > mask_length(*mask)) return false;
    const Json* m = mask;
    if (mask->is_array()) {
        m = &(*mask)[static_cast<std::size_t>(i - 1)];
    } else if (mask->is_object()) {
        // A dictionary has no entry at a number.
        throw JuliaError("KeyError", "KeyError: key " + std::to_string(i) + " not found");
    } else if (mask->is_string()) {
        return true;   // a character: neither a number nor nothing
    }
    if (m->is_bool()) return m->as_bool();
    if (!m->is_number()) return !m->is_null();
    double v = m->as_double();
    return v != 0 && !std::isnan(v);
}

std::vector<double> an_finite_sorted(const SeriesMatrix& M, std::size_t j, const Json* mask) {
    std::vector<double> col;
    for (long long i = 0; i < M.rows; i++) {
        if (!an_keep(mask, i + 1)) continue;
        double v = M(i, j);
        if (std::isfinite(v)) col.push_back(v);
    }
    std::sort(col.begin(), col.end(), jl_less);
    return col;
}

std::vector<std::vector<double>> an_quantiles(const SeriesMatrix& M, const std::vector<double>& qs, const Json* mask) {
    const std::size_t times = M.cols;
    std::vector<std::vector<double>> out(qs.size(), std::vector<double>(times, 0.0));
    for (std::size_t j = 0; j < times; j++) {
        std::vector<double> s = an_finite_sorted(M, j, mask);
        long long n = static_cast<long long>(s.size());
        for (std::size_t k = 0; k < qs.size(); k++) {
            if (n == 0) {
                out[k][j] = NaN;
                continue;
            }
            long long idx = jl_to_int(std::floor(qs[k] * static_cast<double>(n - 1) + 0.5));
            out[k][j] = order_stat(s, idx);
        }
    }
    return out;
}

std::vector<double> an_mean(const SeriesMatrix& M, const Json* mask) {
    const std::size_t times = M.cols;
    std::vector<double> out(times, 0.0);
    for (std::size_t j = 0; j < times; j++) {
        double total = 0.0;
        long long n = 0;
        for (long long i = 0; i < M.rows; i++) {
            if (!an_keep(mask, i + 1)) continue;
            double v = M(i, j);
            if (std::isfinite(v)) {
                total += v;
                n++;
            }
        }
        out[j] = n > 0 ? total / static_cast<double>(n) : NaN;
    }
    return out;
}

MedianSpread an_median_spread(const SeriesMatrix& M, double z, const Json* mask) {
    const std::size_t times = M.cols;
    MedianSpread out{std::vector<double>(times, 0.0), std::vector<double>(times, 0.0), std::vector<double>(times, 0.0),
                     std::vector<double>(times, 0.0)};
    for (std::size_t j = 0; j < times; j++) {
        std::vector<double> s = an_finite_sorted(M, j, mask);
        long long n = static_cast<long long>(s.size());
        if (n == 0) {
            out.err_lo[j] = out.err_hi[j] = out.body_lo[j] = out.body_hi[j] = NaN;
            continue;
        }
        double half = (z * std::sqrt(static_cast<double>(n))) / 2;
        double middle = static_cast<double>(n - 1) / 2;
        out.err_lo[j] = order_stat(s, jl_to_int(std::ceil(middle - half)));
        out.err_hi[j] = order_stat(s, jl_to_int(std::floor(middle + half)));
        out.body_lo[j] = order_stat(s, jl_to_int(std::floor(0.158655 * static_cast<double>(n - 1) + 0.5)));
        out.body_hi[j] = order_stat(s, jl_to_int(std::floor(0.841345 * static_cast<double>(n - 1) + 0.5)));
    }
    return out;
}

SpreadOf an_sd(const SeriesMatrix& M, const std::vector<double>& mean, const Json* mask) {
    const std::size_t times = M.cols;
    std::vector<double> out(times, 0.0);
    std::vector<long long> n(times, 0);
    for (long long i = 0; i < M.rows; i++) {
        if (!an_keep(mask, i + 1)) continue;
        for (std::size_t j = 0; j < times; j++) {
            double v = M(i, j);
            bool ok = std::isfinite(v);
            double d = ok ? v - mean[j] : 0.0;
            out[j] += d * d;
            n[j] += ok;
        }
    }
    SpreadOf s;
    s.n = n;
    s.sd.resize(times);
    for (std::size_t j = 0; j < times; j++)
        s.sd[j] = n[j] > 1 ? std::sqrt(out[j] / static_cast<double>(std::max(n[j] - 1, 1LL))) : NaN;
    return s;
}

std::vector<double> percentiles_for(const Json& list) {
    std::set<double> want = {0.5};
    auto take = [&](double v) {
        if (std::isfinite(v) && 0 < v && v < 1) want.insert(v);
    };
    if (list.is_array()) {
        for (const Json& p : list.arr()) take(pd_to_number(p));   // a number or a Boolean as it is, text as Python reads it
    } else {
        for (double p : PROB_QUANTILES) take(p);
    }
    return std::vector<double>(want.begin(), want.end());
}

std::vector<std::pair<double, std::vector<double>>> quantiles(const ProbabilisticResults& r, const std::string& label, const std::vector<double>& qs,
                                                              const Json* mask) {
    SeriesMatrix M = an_matrix(r, an_index(r, label));
    std::vector<std::vector<double>> ys = an_quantiles(M, qs, mask);
    std::vector<std::pair<double, std::vector<double>>> out;
    for (std::size_t k = 0; k < qs.size(); k++) {
        // An ordered dictionary by quantile (Julia's `isequal`: NaN is NaN, -0 is not 0): one
        // given again takes the place it had.
        auto same = [&](double a, double b) { return (std::isnan(a) && std::isnan(b)) || (a == b && std::signbit(a) == std::signbit(b)); };
        auto it = std::find_if(out.begin(), out.end(), [&](const auto& e) { return same(e.first, qs[k]); });
        if (it != out.end()) it->second = ys[k];
        else out.emplace_back(qs[k], ys[k]);
    }
    return out;
}

std::vector<double> realisations_mean(const ProbabilisticResults& r, const std::string& label, const Json* mask) {
    return an_mean(an_matrix(r, an_index(r, label)), mask);
}

MedianSpread median_spread(const ProbabilisticResults& r, const std::string& label, double z, const Json* mask) {
    return an_median_spread(an_matrix(r, an_index(r, label)), z, mask);
}

std::vector<Band> bands(const ProbabilisticResults& r, const Json& percentiles, const Json* mask) {
    std::vector<double> qs = percentiles_for(percentiles);
    std::vector<Band> out;
    for (std::size_t k = 1; k <= an_count(r); k++) {
        SeriesMatrix M = an_matrix(r, k);
        Band band;
        band.mean = an_mean(M, mask);
        band.q = an_quantiles(M, qs, mask);
        band.quantiles = qs;
        band.sd = an_sd(M, band.mean, mask);
        band.med = an_median_spread(M, 1.959964, mask);
        band.flat = an_flat(r, k);
        out.push_back(std::move(band));
    }
    return out;
}

}  // namespace kompartment
