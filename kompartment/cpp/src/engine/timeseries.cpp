#include "engine/timeseries.hpp"

#include <algorithm>
#include <cmath>

#include "engine/farfield_domain.hpp"
#include "lang/jsmath.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {
// Text by JavaScript's grammar (blank is 0, `1_000` NaN); anything else as Python's `float`.
double ts_number(const Json& v) { return v.is_null() ? 0.0 : v.is_string() ? js_number_of(v) : value_number(v); }
}  // namespace

std::string series_kind(const Json& spec) {
    if (spec.get("times").is_array()) return "times";
    const Json& k = spec.get("kind");
    std::string named = js_str(!k.is_null() ? k : (!spec.get("spacing").is_null() ? spec.get("spacing") : Json("log")));
    return (named == "log" || named == "linear" || named == "times") ? named : "log";
}

std::vector<double> series_times(const Json& spec, double t0, double t1) {
    std::string kind = series_kind(spec);
    std::vector<double> out;
    if (kind == "times") {
        if (spec.get("times").is_array())
            for (const Json& v : spec.get("times").arr()) {
                double x = ts_number(v);
                if (std::isfinite(x) && t0 <= x && x <= t1) out.push_back(x);
            }
        std::sort(out.begin(), out.end());
        return out;
    }
    double nn = spec.has("points") ? ts_number(spec.get("points")) : 0.0;
    nn = std::isfinite(nn) ? std::floor(nn + 0.5) : nn;
    if (!(nn >= 2)) return out;
    long n = static_cast<long>(nn);
    double frm = spec.get("from").is_null() ? t0 : ts_number(spec.get("from"));
    double to = spec.get("to").is_null() ? t1 : ts_number(spec.get("to"));
    if (!(std::isfinite(frm) && std::isfinite(to))) return out;
    double last = std::min(t1, to);
    if (kind == "log") {
        if (frm <= 0) frm = 1.0;
        if (!(to > frm)) return out;
        double step = (js_log10(to) - js_log10(frm)) / static_cast<double>(n - 1);
        if (!(step > 0)) return out;
        double log_from = js_log10(frm);
        for (long c = 0; c <= n * 4 + 7; c++) {
            double v = js_pow(10.0, log_from + step * static_cast<double>(c));
            if (v > last * (1 + SAME_TIME)) break;
            if (v >= t0) out.push_back(v);
        }
        return out;
    }
    double step = (to - frm) / static_cast<double>(n - 1);
    if (!(step > 0)) return out;
    for (long c = 0; c <= n * 4 + 7; c++) {
        double v = frm + step * static_cast<double>(c);
        if (v > last + std::fabs(step) * SAME_TIME) break;
        if (v >= t0) out.push_back(v);
    }
    return out;
}

std::vector<double> combine_series(const Json& series, double t0, double t1) {
    std::vector<double> every = {t0, t1};
    if (series.is_array())
        for (const Json& spec : series.arr()) {
            std::vector<double> t = series_times(spec, t0, t1);
            every.insert(every.end(), t.begin(), t.end());
        }
    std::sort(every.begin(), every.end());
    std::vector<double> out;
    for (double v : every) {
        if (!std::isfinite(v)) continue;
        if (!out.empty()) {
            double last = out.back();
            if (std::fabs(v - last) <= std::fabs(last == 0 ? v : last) * SAME_TIME) continue;
        }
        out.push_back(v);
    }
    return out;
}

}  // namespace kompartment
