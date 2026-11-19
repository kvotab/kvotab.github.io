#include "lang/functions.hpp"

#include <algorithm>
#include <unordered_map>
#include <unordered_set>

#include "util/jsnum.hpp"

namespace kompartment {

namespace {

struct Arity {
    int least;
    int most;   // -1: no limit
    bool context;
};

const std::unordered_map<std::string_view, Arity>& arities() {
    static const std::unordered_map<std::string_view, Arity> table = {
        {"abs", {1, 1, false}}, {"sqrt", {1, 1, false}}, {"exp", {1, 1, false}}, {"log", {1, 1, false}},
        {"log10", {1, 1, false}}, {"log2", {1, 1, false}}, {"power", {2, 2, false}}, {"hypot", {2, 2, false}},
        {"ceil", {1, 1, false}}, {"floor", {1, 1, false}}, {"round", {1, 1, false}}, {"fix", {1, 1, false}},
        {"sign", {1, 1, false}}, {"eps", {0, 0, false}}, {"ulp", {1, 1, false}}, {"pi", {0, 0, false}},
        {"mod", {2, 2, false}}, {"rem", {2, 2, false}}, {"factorial", {1, 1, false}}, {"binomial", {2, 2, false}},
        {"erf", {1, 1, false}}, {"erfc", {1, 1, false}}, {"sin", {1, 1, false}}, {"cos", {1, 1, false}},
        {"tan", {1, 1, false}}, {"asin", {1, 1, false}}, {"acos", {1, 1, false}}, {"atan", {1, 1, false}},
        {"atan2", {2, 2, false}}, {"sinh", {1, 1, false}}, {"cosh", {1, 1, false}}, {"tanh", {1, 1, false}},
        {"asinh", {1, 1, false}}, {"acosh", {1, 1, false}}, {"atanh", {1, 1, false}},
        {"min", {1, -1, false}}, {"max", {1, -1, false}}, {"sum", {1, -1, false}},
        {"prod", {1, -1, false}}, {"mean", {1, -1, false}}, {"if", {2, 3, false}}, {"not", {1, 1, false}},
        {"and", {2, -1, false}}, {"or", {2, -1, false}}, {"nand", {2, -1, false}},
        {"nor", {2, -1, false}}, {"xor", {2, -1, false}}, {"percentile", {2, -1, false}},
        {"interpolationUseEndValues", {3, -1, false}}, {"interpolationExtrapolation", {3, -1, false}},
        {"bq2mole", {2, 2, false}}, {"mole2bq", {2, 2, false}}, {"transport_point", {2, -1, false}},
        {"transport_sum", {3, -1, false}}, {"transport_mean", {3, -1, false}},
        {"rampDown", {3, 3, false}}, {"rampUp", {3, 3, false}}, {"smoothDown", {3, 3, false}},
        {"smoothUp", {3, 3, false}}, {"time", {0, 0, true}}, {"start_time", {0, 0, true}}, {"end_time", {0, 0, true}},
    };
    return table;
}

const std::unordered_map<std::string_view, std::string_view>& aliases() {
    static const std::unordered_map<std::string_view, std::string_view> table = {
        {"fabs", "abs"}, {"ln", "log"}, {"pow", "power"}, {"sgn", "sign"}, {"product", "prod"}};
    return table;
}

}  // namespace

std::optional<FunctionSpec> lookup_function(std::string_view name) {
    auto alias = aliases().find(name);
    std::string_view key = alias == aliases().end() ? name : alias->second;
    auto it = arities().find(key);
    if (it == arities().end()) return std::nullopt;
    FunctionSpec spec{std::string(it->first), it->second.least, std::nullopt, it->second.context};
    if (it->second.most >= 0) spec.max_arity = it->second.most;
    return spec;
}

const std::vector<std::string>& reserved_names() {
    // Kompartment's RESERVED set (src/domain/names.js).
    static const std::vector<std::string> names = {
        "__proto__", "abs", "acos", "acosh", "and", "asin", "asinh", "atan", "atan2", "atanh", "binomial", "bq2mole",
        "ceil", "constructor", "cos", "cosh", "end_time", "eps", "erf", "erfc", "exp", "fabs", "factorial", "fix",
        "floor", "hypot", "if", "interpolationExtrapolation", "interpolationUseEndValues", "ln", "log", "log10",
        "log2", "max", "mean", "min", "mod", "mole2bq", "nand", "nor", "not", "or", "percentile", "pi", "pow", "power",
        "prod", "product", "prototype", "rampDown", "rampUp", "rem", "round", "sgn", "sign", "sin", "sinh",
        "smoothDown", "smoothUp", "sqrt", "start_time", "sum", "tan", "tanh", "time", "transport_mean",
        "transport_point", "transport_sum", "ulp", "xor"};
    return names;
}

bool is_reserved_name(std::string_view name) {
    static const std::unordered_set<std::string_view> set = [] {
        std::unordered_set<std::string_view> s;
        for (const auto& n : reserved_names()) s.insert(n);
        return s;
    }();
    return set.count(name) != 0;
}

double kf_factorial(double n) {
    double k = std::isfinite(n) ? std::floor(n + 0.5) : n;
    if (!(k >= 0)) return std::numeric_limits<double>::quiet_NaN();
    if (k > FACTORIAL_MAX) return std::numeric_limits<double>::infinity();
    double r = 1.0;
    for (int i = 2; i <= static_cast<int>(k); i++) r *= i;
    return r;
}

namespace {

const double ERFC_COF[24] = {
    -1.3026537197817094, 6.4196979235649026e-1, 1.9476473204185836e-2,
    -9.561514786808631e-3, -9.46595344482036e-4, 3.66839497852761e-4,
    4.2523324806907e-5, -2.0278578112534e-5, -1.624290004647e-6,
    1.303655835580e-6, 1.5626441722e-8, -8.5238095915e-8,
    6.529054439e-9, 5.059343495e-9, -9.91364156e-10,
    -2.27365122e-10, 9.6467911e-11, 2.394038e-12,
    -6.886027e-12, 8.94487e-13, 3.13092e-13,
    -1.12708e-13, 3.81e-16, 7.106e-15,
};
const double ERF_NEAR = 0.46875;
const double ERF_A[5] = {3.16112374387056560e0, 1.13864154151050156e2, 3.77485237685302021e2, 3.20937758913846947e3,
                         1.85777706184603153e-1};
const double ERF_B[4] = {2.36012909523441209e1, 2.44024637934444173e2, 1.28261652607737228e3, 2.84423683343917062e3};

// erf for |x| <= ERF_NEAR: W. J. Cody's x P(x²)/Q(x²) (CALERF's first interval).
double erf_near(double x) {
    double y = std::fabs(x);
    double ysq = y > 1.11e-16 ? y * y : 0.0;
    double num = ERF_A[4] * ysq;
    double den = ysq;
    for (int i = 0; i < 3; i++) {
        num = (num + ERF_A[i]) * ysq;
        den = (den + ERF_B[i]) * ysq;
    }
    return x * (num + ERF_A[3]) / (den + ERF_B[3]);
}

double cmp_numbers(double a, double b) {
    double v = a - b;
    return v != v ? 0.0 : v;
}

}  // namespace

double kf_erfc(double x) {
    if (std::isnan(x)) return std::numeric_limits<double>::quiet_NaN();
    if (std::fabs(x) <= ERF_NEAR) return 1 - erf_near(x);
    double z = std::fabs(x);
    double t = 2 / (2 + z);
    double ty = 4 * t - 2;
    double d = 0.0, dd = 0.0;
    for (int j = 23; j >= 1; j--) {
        double tmp = d;
        d = ty * d - dd + ERFC_COF[j];
        dd = tmp;
    }
    double ans = t * std::exp(-z * z + 0.5 * (ERFC_COF[0] + ty * d) - dd);
    return x >= 0 ? ans : 2 - ans;
}

double kf_erf(double x) {
    if (std::fabs(x) <= ERF_NEAR) return erf_near(x);
    double v = 1 - kf_erfc(std::fabs(x));
    return x < 0 ? -v : v;
}

std::vector<double> js_sort_numbers(const double* values, std::size_t n) {
    std::vector<double> a(values, values + n);
    if (n < 2) return a;
    bool any_nan = false;
    for (double v : a)
        if (std::isnan(v)) { any_nan = true; break; }
    if (!any_nan) {
        // (-0 before 0, as a sort by value with the sign as a tie-break gives.)
        std::stable_sort(a.begin(), a.end(), [](double p, double q) {
            if (p < q) return true;
            if (q < p) return false;
            return std::signbit(p) && !std::signbit(q);
        });
        return a;
    }
    if (n >= 64) {
        std::stable_sort(a.begin(), a.end(), [](double p, double q) {
            bool pn = std::isnan(p), qn = std::isnan(q);
            if (pn != qn) return qn;
            if (pn) return false;
            if (p < q) return true;
            if (q < p) return false;
            return std::signbit(p) && !std::signbit(q);
        });
        return a;
    }
    // V8's insertion sort for short lists: a comparator that calls a NaN equal to
    // everything is not an ordering, and where the NaNs end up follows from the steps.
    std::size_t run = 2;
    bool descending = cmp_numbers(a[1], a[0]) < 0;
    double previous = a[1];
    for (std::size_t i = 2; i < n; i++) {
        double order = cmp_numbers(a[i], previous);
        if ((descending && order >= 0) || (!descending && order < 0)) break;
        previous = a[i];
        run++;
    }
    if (descending) std::reverse(a.begin(), a.begin() + static_cast<std::ptrdiff_t>(run));
    for (std::size_t start = run; start < n; start++) {
        double pivot = a[start];
        std::size_t left = 0, right = start;
        while (left < right) {
            std::size_t mid = left + ((right - left) >> 1);
            if (cmp_numbers(pivot, a[mid]) < 0) right = mid;
            else left = mid + 1;
        }
        for (std::size_t k = start; k > left; k--) a[k] = a[k - 1];
        a[left] = pivot;
    }
    return a;
}

double kf_percentile(double phi, const double* xs, std::size_t count) {
    const double nan = std::numeric_limits<double>::quiet_NaN();
    long n = static_cast<long>(count);
    if (n == 0 || !(phi >= 0) || !(phi <= 100)) return nan;
    double p = phi / 100;
    std::vector<double> s = js_sort_numbers(xs, count);
    if (p == 0.5) return n % 2 == 1 ? s[static_cast<std::size_t>((n + 1) / 2 - 1)] : (s[static_cast<std::size_t>(n / 2 - 1)] + s[static_cast<std::size_t>(n / 2)]) / 2;
    // xx = [s[0], s..., s[n-1]], pp = [0, (i - 0.5)/n for i in 1..n, 1], both of n + 2 (counted from 1 below).
    auto xx = [&](long j) { return j == 1 ? s[0] : j == n + 2 ? s[static_cast<std::size_t>(n - 1)] : s[static_cast<std::size_t>(j - 2)]; };
    auto pp = [&](long j) { return j == 1 ? 0.0 : j == n + 2 ? 1.0 : ((j - 1) - 0.5) / static_cast<double>(n); };
    long j = 1;
    while (j < n + 2 && p > pp(j + 1)) j++;
    if (j >= n + 2) return xx(n + 2);
    double span = pp(j + 1) - pp(j);
    if (span == 0) return xx(j + 1);
    return ((p - pp(j)) / span) * (xx(j + 1) - xx(j)) + xx(j);
}

double kf_transport_point(const double* args, std::size_t count) {
    double x = args[count - 1];
    long n = static_cast<long>(count) - 1;
    if (std::isnan(x)) return std::numeric_limits<double>::quiet_NaN();
    if (x < 0) throw TransportRangeError("transport operation: the position " + js_number(x) + " is lower than zero");
    if (x > 1) throw TransportRangeError("transport operation: the position " + js_number(x) + " is higher than one");
    long at = x == 1 ? n - 1 : static_cast<long>(std::trunc(x * static_cast<double>(n)));
    return args[at];
}

double kf_transport_range(const double* args, std::size_t count, bool mean) {
    long n = static_cast<long>(count) - 2;
    double a = args[n], b = args[n + 1];
    if (std::isnan(a) || std::isnan(b)) return std::numeric_limits<double>::quiet_NaN();
    if (a > b) std::swap(a, b);
    if (a < 0) throw TransportRangeError("transport operation: the range starts at " + js_number(a) + ", which is lower than zero");
    if (b > 1) throw TransportRangeError("transport operation: the range ends at " + js_number(b) + ", which is higher than one");
    double total = 0.0;
    if (a == 0 && b == 1) {
        for (long e = 0; e < n; e++) total += args[e];
        return mean ? total / static_cast<double>(n) : total;
    }
    // f and t as the Julia engine counts them: f from 1, t from 0.
    long f = static_cast<long>(std::trunc(a * static_cast<double>(n))) + 1;
    long t = static_cast<long>(std::trunc(b * static_cast<double>(n)));
    double cells = 0.0;
    if (t > f) {
        for (long e = f; e <= t - 1; e++) total += args[e];
        cells += static_cast<double>(t - f);
    }
    double dx = static_cast<double>(f) - a * static_cast<double>(n);
    cells += dx;
    total += args[f - 1] * dx;
    if (b < 1) {
        double dy = b * static_cast<double>(n) - static_cast<double>(t);
        cells += dy;
        total += args[t] * dy;
    }
    return mean ? total / cells : total;
}

}  // namespace kompartment
