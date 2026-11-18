#include "engine/derived.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_map>
#include <unordered_set>

#include "engine/farfield_domain.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {
const double NaN = std::numeric_limits<double>::quiet_NaN();
bool is_period_kind(const std::string& k) { return k == "period_mean" || k == "period_sum" || k == "period_change" || k == "period_rate"; }
std::string text_of(const Json& v) { return v.is_null() ? std::string() : std::string(js_trim(js_str(v))); }
double number_or_nan(const Json& v) { return v.is_null() ? NaN : py_float_nan(v); }

std::vector<double> by_period(const std::string& kind, const std::vector<double>& t, const std::vector<double>& values, std::size_t n, double period) {
    std::vector<double> out(n, NaN);
    if (n == 0 || !(period > 0)) return out;
    double t0 = t[0], t_end = t[n - 1];
    std::vector<double> running = derived_integral(t, values, n);
    auto integral_to = [&](double x) {
        if (x <= t0) return 0.0;
        if (x >= t_end) return running[n - 1];
        std::size_t lo = 0, hi = n - 1;
        while (hi - lo > 1) {
            std::size_t mid = (lo + hi) >> 1;
            if (t[mid] <= x) lo = mid;
            else hi = mid;
        }
        double a = values[lo];
        double b = derived_value_at(t, values, n, x);
        if (!std::isfinite(a) || !std::isfinite(b)) return running[lo];
        return running[lo] + 0.5 * (a + b) * (x - t[lo]);
    };
    std::size_t j = 0;
    for (long k = 0;; k++) {
        double frm = t0 + static_cast<double>(k) * period;
        if (frm > t_end) break;
        double to = std::min(t_end, frm + period);
        double span = to - frm;
        double v;
        if (kind == "period_mean") {
            v = span > 0 ? (integral_to(to) - integral_to(frm)) / span : derived_value_at(t, values, n, frm);
        } else if (kind == "period_sum") {
            v = integral_to(to) - integral_to(frm);
        } else {
            double change = derived_value_at(t, values, n, to) - derived_value_at(t, values, n, frm);
            v = kind == "period_change" ? change : (span > 0 ? change / span : NaN);
        }
        while (j < n && (t[j] < to || (to == t_end && t[j] <= t_end))) out[j++] = v;
        if (to == t_end) break;
    }
    return out;
}
}  // namespace

bool is_derived_kind(const std::string& k) {
    return k == "max" || k == "min" || k == "time_of_max" || k == "at_time" || k == "integral" || is_period_kind(k);
}
bool is_series_kind(const std::string& kind) { return kind == "integral" || is_period_kind(kind); }

std::string derived_unit(const std::string& kind, const Json& source_unit, const Json& time_unit) {
    std::string u = text_of(source_unit), tu = text_of(time_unit);
    if (kind == "time_of_max") return tu;
    if (kind == "integral" || kind == "period_sum") return u.empty() ? "" : u + " " + tu;
    if (kind == "period_rate") return u.empty() ? "" : u + "/" + tu;
    return u;
}

double derived_value_at(const std::vector<double>& t, const std::vector<double>& values, std::size_t n, double at) {
    if (n == 0 || !std::isfinite(at)) return NaN;
    if (at <= t[0]) return values[0];
    if (at >= t[n - 1]) return values[n - 1];
    std::size_t lo = 0, hi = n - 1;
    while (hi - lo > 1) {
        std::size_t mid = (lo + hi) >> 1;
        if (t[mid] <= at) lo = mid;
        else hi = mid;
    }
    double span = t[hi] - t[lo];
    if (!(span > 0)) return values[lo];
    double a = values[lo], b = values[hi];
    if (!std::isfinite(a)) return b;
    if (!std::isfinite(b)) return a;
    return a + ((at - t[lo]) / span) * (b - a);
}

std::vector<double> derived_integral(const std::vector<double>& t, const std::vector<double>& values, std::size_t n) {
    std::vector<double> out(n, 0.0);
    double total = 0.0;
    for (std::size_t i = 1; i < n; i++) {
        double dt = t[i] - t[i - 1];
        double a = values[i - 1], b = values[i];
        if (dt > 0 && std::isfinite(a) && std::isfinite(b)) total += 0.5 * (a + b) * dt;
        out[i] = total;
    }
    return out;
}

std::vector<double> derived_reduce(const std::string& kind, const std::vector<double>& t, const std::vector<double>& values, double at, double period) {
    std::size_t n = std::min(t.size(), values.size());
    if (kind == "integral") return derived_integral(t, values, n);
    if (is_period_kind(kind)) return by_period(kind, t, values, n, period);
    double v = NaN;
    if (n > 0) {
        if (kind == "at_time") {
            v = derived_value_at(t, values, n, at);
        } else {
            double best = NaN, best_at = NaN;
            for (std::size_t i = 0; i < n; i++) {
                double x = values[i];
                if (!std::isfinite(x)) continue;
                if (best != best || (kind == "min" ? x < best : x > best)) {
                    best = x;
                    best_at = t[i];
                }
            }
            v = kind == "time_of_max" ? best_at : best;
        }
    }
    return std::vector<double>(t.size(), v);
}

std::vector<Json> derived_outputs(const Project& project, const std::vector<Json>& known_outputs) {
    std::vector<Json> out;
    std::vector<Json> pending;
    for (const Json& b : project.derived.arr()) {
        if (!b.is_object()) continue;
        if (text_of(b.get("name")).empty()) continue;
        if (!(b.get("kind").is_string() && is_derived_kind(b.get("kind").as_string()))) continue;
        if (text_of(b.get("of")).empty()) continue;
        pending.push_back(b);
    }
    if (pending.empty()) return out;
    std::unordered_set<std::string> known;
    std::unordered_map<std::string, Json> by_label;
    for (const Json& o : known_outputs) {
        const std::string& label = o.get("label").as_string();
        known.insert(label);
        by_label[label] = o;
    }
    Json time_unit = project.simulation.get("time_unit").is_null() ? Json("year") : project.simulation.get("time_unit");
    std::size_t passes = 0;
    while (!pending.empty() && passes <= pending.size()) {
        std::vector<Json> later;
        for (const Json& d : pending) {
            std::string name = js_str(d.get("name"));
            std::string of = d.get("of").is_string() ? d.get("of").as_string() : js_str(d.get("of"));
            if (!(d.get("of").is_string() && known.count(of)) || known.count(name)) {
                later.push_back(d);
                continue;
            }
            auto src = by_label.find(of);
            const std::string& kind = d.get("kind").as_string();
            Json o = Json::object({
                {"kind", Json("derived")}, {"source", Json("D")}, {"block", Json(name)}, {"label", Json(name)},
                {"unit", Json(derived_unit(kind, src == by_label.end() ? Json() : src->second.get("unit"), time_unit))},
                {"derived", Json::object({{"kind", Json(kind)}, {"of", d.get("of")}, {"at", Json(number_or_nan(d.get("at")))},
                                          {"period", Json(number_or_nan(d.get("period")))}})},
                {"dims", Json::array()}, {"index", Json()}});
            if (!is_series_kind(kind)) o.set("timeDependent", Json(false));
            out.push_back(o);
            by_label[name] = o;
            known.insert(name);
        }
        if (later.size() == pending.size()) break;
        pending = std::move(later);
        passes++;
    }
    return out;
}

}  // namespace kompartment
