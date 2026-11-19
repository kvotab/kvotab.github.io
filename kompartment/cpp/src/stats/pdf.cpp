#include "stats/pdf.hpp"

#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <limits>

#include "lang/jsmath.hpp"
#include "stats/normal.hpp"
#include "util/errors.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
constexpr double Inf = std::numeric_limits<double>::infinity();

const Json& empty_object() {
    static const Json e = Json::object();
    return e;
}

/// One character of UTF-8 at `i`: its code point and length, or none for bytes that are not one
/// (an overlong form, a surrogate, a sequence cut short) -- which Julia's `Char` holds as a
/// malformed character, never equal to a real one.
bool decode_at(std::string_view s, std::size_t i, std::uint32_t& cp, std::size_t& len) {
    auto byte = [&](std::size_t k) { return static_cast<unsigned char>(s[k]); };
    unsigned char c = byte(i);
    if (c < 0x80) {
        cp = c;
        len = 1;
        return true;
    }
    std::size_t n;
    std::uint32_t v, least;
    if ((c & 0xe0) == 0xc0) {
        n = 2, v = c & 0x1f, least = 0x80;
    } else if ((c & 0xf0) == 0xe0) {
        n = 3, v = c & 0x0f, least = 0x800;
    } else if ((c & 0xf8) == 0xf0) {
        n = 4, v = c & 0x07, least = 0x10000;
    } else {
        return false;
    }
    if (i + n > s.size()) return false;
    for (std::size_t k = 1; k < n; k++) {
        unsigned char d = byte(i + k);
        if ((d & 0xc0) != 0x80) return false;
        v = (v << 6) | (d & 0x3f);
    }
    if (v < least || v > 0x10ffff || (v >= 0xd800 && v <= 0xdfff)) return false;
    cp = v;
    len = n;
    return true;
}

/// `strip(pred, s)` over characters: what `pred` holds of taken from both ends.
template <class Pred>
std::string_view strip_by(std::string_view s, Pred pred) {
    std::size_t a = 0;
    while (a < s.size()) {
        std::uint32_t cp;
        std::size_t len;
        if (!decode_at(s, a, cp, len) || !pred(cp)) break;
        a += len;
    }
    std::size_t b = s.size();
    while (b > a) {
        std::size_t start = b - 1;
        while (start > a && b - start < 4 && (static_cast<unsigned char>(s[start]) & 0xc0) == 0x80) start--;
        std::uint32_t cp;
        std::size_t len;
        if (!decode_at(s, start, cp, len) || start + len != b || !pred(cp)) break;
        b = start;
    }
    return s.substr(a, b - a);
}

/// The white space and line ends JavaScript's `trim()` takes away (`_PD_JS_SPACE`).
bool js_space(std::uint32_t c) {
    return c == '\t' || c == '\n' || c == '\v' || c == '\f' || c == '\r' || c == ' ' || c == 0xa0 || c == 0x1680 ||
           (c >= 0x2000 && c <= 0x200a) || c == 0x2028 || c == 0x2029 || c == 0x202f || c == 0x205f || c == 0x3000 ||
           c == 0xfeff;
}

/// Julia's `isspace`: the ASCII white space, U+0085, and the Unicode space separators.
bool jl_space(std::uint32_t c) {
    return c == ' ' || (c >= '\t' && c <= '\r') || c == 0x85 || c == 0xa0 || c == 0x1680 || (c >= 0x2000 && c <= 0x200a) ||
           c == 0x202f || c == 0x205f || c == 0x3000;
}

bool c_space(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\v' || c == '\f' || c == '\r'; }

/// Julia's `tryparse(Float64, s)` (`jl_try_substrtod`): the C library's strtod, which must read
/// something and leave nothing but white space, and neither overflow nor underflow to zero.
std::optional<double> jl_tryparse_float(const std::string& s) {
    const char* begin = s.c_str();
    char* end = nullptr;
    errno = 0;
    double out = std::strtod(begin, &end);
    if (errno == ERANGE && (out == 0 || out == HUGE_VAL || out == -HUGE_VAL)) return std::nullopt;
    if (end == begin) return std::nullopt;
    for (std::size_t k = static_cast<std::size_t>(end - begin); k < s.size(); k++)
        if (!c_space(s[k])) return std::nullopt;
    return out;
}

/// `Float64(parse(BigInt, digits; base))` for a base that is a power of two: the whole number
/// rounded to the nearest double, a tie to the even one, Infinity past the largest.
double big_to_double(std::string_view digits, int bits_per_digit) {
    std::string bits;
    bits.reserve(digits.size() * static_cast<std::size_t>(bits_per_digit));
    for (char ch : digits) {
        int v = (ch >= '0' && ch <= '9') ? ch - '0' : (ch >= 'a' && ch <= 'f') ? ch - 'a' + 10 : ch - 'A' + 10;
        for (int k = bits_per_digit - 1; k >= 0; k--) bits.push_back(((v >> k) & 1) ? '1' : '0');
    }
    std::size_t first = bits.find('1');
    if (first == std::string::npos) return 0.0;
    std::string_view b = std::string_view(bits).substr(first);
    std::size_t len = b.size();
    if (len <= 53) {
        std::uint64_t m = 0;
        for (char ch : b) m = (m << 1) | static_cast<std::uint64_t>(ch == '1');
        return static_cast<double>(m);
    }
    std::uint64_t m = 0;
    for (std::size_t k = 0; k < 53; k++) m = (m << 1) | static_cast<std::uint64_t>(b[k] == '1');
    bool round = b[53] == '1';
    bool sticky = b.find('1', 54) != std::string_view::npos;
    long long exponent = static_cast<long long>(len) - 53;
    if (round && (sticky || (m & 1))) {
        m += 1;
        if (m == (std::uint64_t{1} << 53)) {
            m >>= 1;
            exponent += 1;
        }
    }
    if (exponent > 2000) return Inf;
    return std::ldexp(static_cast<double>(m), static_cast<int>(exponent));
}

bool is_digit(char c) { return c >= '0' && c <= '9'; }

/// `^[+-]?(?:Infinity|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\z`
bool decimal_text(std::string_view t) {
    std::size_t k = 0, n = t.size();
    if (k < n && (t[k] == '+' || t[k] == '-')) k++;
    if (t.substr(k) == "Infinity") return true;
    std::size_t whole = 0;
    while (k < n && is_digit(t[k])) k++, whole++;
    if (whole > 0) {
        if (k < n && t[k] == '.') {
            k++;
            while (k < n && is_digit(t[k])) k++;
        }
    } else {
        if (!(k < n && t[k] == '.')) return false;
        k++;
        std::size_t frac = 0;
        while (k < n && is_digit(t[k])) k++, frac++;
        if (frac == 0) return false;
    }
    if (k < n && (t[k] == 'e' || t[k] == 'E')) {
        std::size_t e = k + 1;
        if (e < n && (t[e] == '+' || t[e] == '-')) e++;
        std::size_t ex = 0;
        while (e < n && is_digit(t[e])) e++, ex++;
        if (ex > 0) k = e;
    }
    return k == n;
}

/// `^0(?:[xX]([0-9a-fA-F]+)|[oO]([0-7]+)|[bB]([01]+))\z`: the digits and bits a digit, or none.
std::optional<std::pair<std::string_view, int>> other_base(std::string_view t) {
    if (t.size() < 3 || t[0] != '0') return std::nullopt;
    char x = t[1];
    std::string_view digits = t.substr(2);
    auto all = [&](auto ok) {
        for (char c : digits)
            if (!ok(c)) return false;
        return true;
    };
    if (x == 'x' || x == 'X') {
        if (all([](char c) { return is_digit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'); })) return std::make_pair(digits, 4);
    } else if (x == 'o' || x == 'O') {
        if (all([](char c) { return c >= '0' && c <= '7'; })) return std::make_pair(digits, 3);
    } else if (x == 'b' || x == 'B') {
        if (all([](char c) { return c == '0' || c == '1'; })) return std::make_pair(digits, 1);
    }
    return std::nullopt;
}

/// Julia's `lowercase` as far as it can make the words `inf`, `infinity` and `nan`: the ASCII
/// capitals, and the dotted capital I, which it lowers to a plain `i`.
std::string jl_lower_ascii(std::string_view s) {
    std::string out;
    out.reserve(s.size());
    for (std::size_t i = 0; i < s.size(); i++) {
        char c = s[i];
        if (c >= 'A' && c <= 'Z') {
            out.push_back(static_cast<char>(c - 'A' + 'a'));
        } else if (static_cast<unsigned char>(c) == 0xc4 && i + 1 < s.size() && static_cast<unsigned char>(s[i + 1]) == 0xb0) {
            out.push_back('i');   // U+0130
            i++;
        } else {
            out.push_back(c);
        }
    }
    return out;
}

const Json* params_of(const Json& spec) {
    if (spec.is_null())
        throw ArgumentError("no distribution: the application cannot read the parameters of null either");
    const Json* p = pd_prop(spec, "params");
    return pd_nullish(p) ? &empty_object() : p;
}

bool kind_is(const Json* kind, const char* name) { return kind != nullptr && *kind == name; }

/// Logn.muprim / sigmaprim: an arithmetic mean and sd carried into log space.
std::pair<double, double> logn_log_space(double mean, double sd) {
    return {js_log((mean * mean) / std::sqrt((sd * sd) + (mean * mean))), pd_sqrt(js_log(1 + ((sd * sd) / (mean * mean))))};
}

/// `probit(u)` where JavaScript multiplies by it: its `null` outside (0, 1) counts as 0.
double probit_or_zero(double u) {
    std::optional<double> z = normal_probit(u);
    return z ? *z : 0.0;
}

}  // namespace

// --- JavaScript's rules ------------------------------------------------------------------------------

const Json* pd_prop(const Json* obj, std::string_view key) {
    if (obj == nullptr || !obj->is_object()) return nullptr;
    return obj->obj().find(key);
}

bool pd_truthy(const Json* v) {
    if (pd_nullish(v)) return false;
    switch (v->type()) {
        case Json::Type::Bool: return v->as_bool();
        case Json::Type::Int: return v->as_int() != 0;
        case Json::Type::Float: {
            double x = v->as_double();
            return !(x == 0 || std::isnan(x));
        }
        case Json::Type::String: return !v->as_string().empty();
        default: return true;
    }
}

std::string_view pd_js_trim(std::string_view s) { return strip_by(s, js_space); }

std::string_view jl_strip(std::string_view s) { return strip_by(s, jl_space); }

double pd_string_to_number(std::string_view s) {
    std::string_view t = pd_js_trim(s);
    if (t.empty()) return 0.0;
    if (auto other = other_base(t)) return big_to_double(other->first, other->second);
    if (decimal_text(t)) {
        std::string_view body = t;
        while (!body.empty() && (body[0] == '+' || body[0] == '-')) body.remove_prefix(1);
        if (body == "Infinity") return t[0] == '-' ? -Inf : Inf;
        std::string text(t);
        std::optional<double> v = jl_tryparse_float(text);
        if (v) return *v;
        // Out of a double's range, where Julia's `tryparse` refuses what JavaScript rounds: to
        // the infinities, or to zero -- the C library's strtod, correctly rounded, as the Julia
        // package's BigFloat is.
        return std::strtod(text.c_str(), nullptr);
    }
    return NaN;
}

std::string pd_js_number_str(double x) { return js_text(x); }

std::string pd_js_str(const Json* v) {
    if (v == nullptr) return "undefined";
    switch (v->type()) {
        case Json::Type::Null: return "null";
        case Json::Type::Bool: return v->as_bool() ? "true" : "false";
        case Json::Type::String: return v->as_string();
        case Json::Type::Int:
        case Json::Type::Float: return pd_js_number_str(v->as_double());
        case Json::Type::Array: {
            std::string out;
            bool first = true;
            for (const Json& e : v->arr()) {
                if (!first) out.push_back(',');
                first = false;
                if (!pd_nullish(&e)) out += pd_js_str(&e);
            }
            return out;
        }
        case Json::Type::Object: return "[object Object]";
    }
    return "";
}

double pd_to_number(const Json* v) {
    if (v == nullptr) return NaN;
    switch (v->type()) {
        case Json::Type::Null: return 0.0;
        case Json::Type::Bool: return v->as_bool() ? 1.0 : 0.0;
        case Json::Type::Int:
        case Json::Type::Float: return v->as_double();
        case Json::Type::String: return pd_string_to_number(v->as_string());
        case Json::Type::Array: return pd_string_to_number(pd_js_str(v));
        default: return NaN;
    }
}

double pd_jmax(double a, double b) {
    if (std::isnan(a) || std::isnan(b)) return NaN;
    if (a == b) return std::signbit(a) ? b : a;
    return a > b ? a : b;
}

double pd_jmin(double a, double b) {
    if (std::isnan(a) || std::isnan(b)) return NaN;
    if (a == b) return std::signbit(a) ? a : b;
    return a < b ? a : b;
}

double pd_sqrt(double x) { return x >= 0 ? std::sqrt(x) : NaN; }

double jl_py_float(const Json& v) {
    if (v.is_bool()) return v.as_bool() ? 1.0 : 0.0;
    if (v.is_number()) return v.as_double();
    if (!v.is_string()) return NaN;
    std::string_view s = jl_strip(v.as_string());
    if (s.empty()) return NaN;
    std::string low = jl_lower_ascii(s);
    if (low == "inf" || low == "+inf" || low == "infinity" || low == "+infinity") return Inf;
    if (low == "-inf" || low == "-infinity") return -Inf;
    if (low == "nan" || low == "+nan" || low == "-nan") return NaN;
    std::string clean;
    clean.reserve(s.size());
    for (char c : s)
        if (c != '_') clean.push_back(c);
    // A decimal and nothing else (`_PY_DECIMAL`): what strtod reads besides -- hexadecimal, the
    // words -- Python's float() refuses.
    std::size_t k = 0, n = clean.size(), digits = 0;
    if (k < n && (clean[k] == '+' || clean[k] == '-')) k++;
    while (k < n && clean[k] >= '0' && clean[k] <= '9') k++, digits++;
    if (k < n && clean[k] == '.') {
        k++;
        while (k < n && clean[k] >= '0' && clean[k] <= '9') k++, digits++;
    }
    if (digits == 0) return NaN;
    if (k < n && (clean[k] == 'e' || clean[k] == 'E')) {
        k++;
        if (k < n && (clean[k] == '+' || clean[k] == '-')) k++;
        std::size_t ex = 0;
        while (k < n && clean[k] >= '0' && clean[k] <= '9') k++, ex++;
        if (ex == 0) return NaN;
    }
    if (k != n) return NaN;
    std::optional<double> x = jl_tryparse_float(clean);
    // Out of a double's range, where Julia's `tryparse` refuses what Python rounds: to the
    // infinities, or to zero.
    return x ? *x : std::strtod(clean.c_str(), nullptr);
}

// --- the kinds -------------------------------------------------------------------------------------

const std::vector<std::pair<std::string, std::vector<std::string>>>& pdf_kind_params() {
    static const std::vector<std::pair<std::string, std::vector<std::string>>> kinds = {
        {"unif", {"min", "max"}},
        {"triang", {"min", "max", "mode"}},
        {"dtriang", {"min", "max", "mode"}},
        {"norm", {"mean", "sd"}},
        {"logu", {"min", "max"}},
        {"logt", {"min", "max", "mode"}},
        {"logdt", {"min", "max", "mode"}},
        {"Logn4", {"gm", "gsd"}},
        {"logn", {"mean", "sd"}},
        {"logn5", {"p1", "x1", "p2", "x2"}},
        {"pg", {}},
    };
    return kinds;
}

const std::vector<std::string>* pd_meta(const Json* kind) {
    if (kind == nullptr || !kind->is_string()) return nullptr;
    for (const auto& [id, params] : pdf_kind_params())
        if (kind->as_string() == id) return &params;
    return nullptr;
}

bool pdf_complete(const Json& spec) {
    if (!pd_truthy(&spec)) return false;
    const Json* kind = pd_prop(spec, "kind");
    const std::vector<std::string>* params = pd_meta(kind);
    if (params == nullptr) return false;
    if (*kind == "pg") {
        const Json* values = pd_prop(spec, "values");
        if (pd_nullish(values) || values->is_object() || values->is_number() || values->is_bool()) return false;
        if (values->is_array()) return values->size() > 0;
        if (values->is_string()) return !values->as_string().empty();
        return false;
    }
    const Json* p = pd_prop(spec, "params");
    for (const auto& k : *params)
        if (pd_nullish(pd_prop(p, k))) return false;
    return true;
}

// --- the forward and inverse CDF ---------------------------------------------------------------------

std::optional<std::pair<double, double>> pd_log_space(const Json& spec) {
    const Json* kind = pd_prop(spec, "kind");
    const Json* p = pd_prop(spec, "params");
    if (pd_nullish(p)) p = &empty_object();
    if (kind_is(kind, "Logn4")) return std::make_pair(js_log(pd_param(p, "gm")), js_log(pd_param(p, "gsd")));
    if (kind_is(kind, "logn")) return logn_log_space(pd_param(p, "mean"), pd_param(p, "sd"));
    if (kind_is(kind, "logn5")) {
        // `probit` reads its argument as Python's float() reads it; a missing one is NaN.
        auto probit_of = [&](const char* key) {
            const Json* v = pd_prop(p, key);
            return v == nullptr ? normal_probit(NaN) : normal_probit(*v);
        };
        std::optional<double> z1 = probit_of("p1");
        std::optional<double> z2 = probit_of("p2");
        if (!z1 || !z2 || *z1 == *z2) return std::nullopt;
        double sigma = (js_log(pd_param(p, "x2")) - js_log(pd_param(p, "x1"))) / (*z2 - *z1);
        if (!(sigma > 0)) return std::nullopt;
        return std::make_pair(js_log(pd_param(p, "x1")) - sigma * *z1, sigma);
    }
    return std::nullopt;
}

double pdf_cdf(const Json& spec, const Json* x0) {
    const Json* p = params_of(spec);
    const Json* kind = pd_prop(spec, "kind");
    double x = pd_to_number(x0);
    if (kind_is(kind, "unif")) {
        double a = pd_param(p, "min");
        double b = pd_param(p, "max");
        if (x <= a) return 0.0;
        if (x >= b) return 1.0;
        return (x - a) / (b - a);
    } else if (kind_is(kind, "triang")) {
        double a = pd_param(p, "min");
        double b = pd_param(p, "max");
        double c = pd_param(p, "mode");
        if (x <= a) return 0.0;
        if (x >= b) return 1.0;
        if (x <= c) return ((x - a) * (x - a)) / ((b - a) * (c - a));
        return 1 - ((b - x) * (b - x)) / ((b - a) * (b - c));
    } else if (kind_is(kind, "dtriang")) {
        double a = pd_param(p, "min");
        double b = pd_param(p, "max");
        double c = pd_param(p, "mode");
        if (x <= a) return 0.0;
        if (x >= b) return 1.0;
        if (x <= c) return ((x - a) * (x - a)) / (2 * ((c - a) * (c - a)));
        return 1 - ((b - x) * (b - x)) / (2 * ((b - c) * (b - c)));
    } else if (kind_is(kind, "logu")) {
        double a = pd_param(p, "min");
        double b = pd_param(p, "max");
        if (x <= a) return 0.0;
        if (x >= b) return 1.0;
        return (js_log(x) - js_log(a)) / (js_log(b) - js_log(a));
    } else if (kind_is(kind, "logt")) {
        double la = js_log(pd_param(p, "min"));
        double lb = js_log(pd_param(p, "max"));
        double lc = js_log(pd_param(p, "mode"));
        if (x <= pd_param(p, "min")) return 0.0;
        if (x >= pd_param(p, "max")) return 1.0;
        double lx = js_log(x);
        if (lx <= lc) return ((lx - la) * (lx - la)) / ((lc - la) * (lb - la));
        return 1 - ((lb - lx) * (lb - lx)) / ((lb - la) * (lb - lc));
    } else if (kind_is(kind, "logdt")) {
        if (x <= pd_param(p, "min")) return 0.0;
        if (x >= pd_param(p, "max")) return 1.0;
        double la = js_log(pd_param(p, "min"));
        double lb = js_log(pd_param(p, "max"));
        double lc = js_log(pd_param(p, "mode"));
        double lx = js_log(x);
        if (lx <= lc) return ((lx - la) * (lx - la)) / (2 * ((lc - la) * (lc - la)));
        return 1 - ((lb - lx) * (lb - lx)) / (2 * ((lb - lc) * (lb - lc)));
    } else if (kind_is(kind, "norm")) {
        return normal_phi((x - pd_param(p, "mean")) / pd_param(p, "sd"));
    } else if (kind_is(kind, "Logn4") || kind_is(kind, "logn") || kind_is(kind, "logn5")) {
        if (x <= 0) return 0.0;
        auto ls = pd_log_space(spec);
        return ls ? normal_phi((js_log(x) - ls->first) / ls->second) : 0.0;
    }
    return 0.0;
}

double pdf_cdf(const Json& spec, double x) {
    Json v(x);
    return pdf_cdf(spec, &v);
}

double pdf_quantile(const Json& spec, const Json* u0) {
    const Json* p = params_of(spec);
    const Json* kind = pd_prop(spec, "kind");
    double u = pd_to_number(u0);
    if (kind_is(kind, "unif")) {
        double a = pd_param(p, "min");
        return a + u * (pd_param(p, "max") - a);
    } else if (kind_is(kind, "triang")) {
        double a = pd_param(p, "min");
        double b = pd_param(p, "max");
        double c = pd_param(p, "mode");
        double split = (c - a) / (b - a);
        if (u <= split) return a + pd_sqrt((u * (b - a)) * (c - a));
        return b - pd_sqrt(((1 - u) * (b - a)) * (b - c));
    } else if (kind_is(kind, "dtriang")) {
        double a = pd_param(p, "min");
        double b = pd_param(p, "max");
        double c = pd_param(p, "mode");
        if (u <= 0.5) return a + pd_sqrt(2 * u) * (c - a);
        return b - (b - c) * pd_sqrt(2 * (1 - u));
    } else if (kind_is(kind, "logu")) {
        double la = js_log(pd_param(p, "min"));
        return js_exp(la + u * (js_log(pd_param(p, "max")) - la));
    } else if (kind_is(kind, "logt")) {
        double la = js_log(pd_param(p, "min"));
        double lb = js_log(pd_param(p, "max"));
        double lc = js_log(pd_param(p, "mode"));
        double split = (lc - la) / (lb - la);
        double lx = u <= split ? la + pd_sqrt((u * (lb - la)) * (lc - la)) : lb - pd_sqrt(((1 - u) * (lb - la)) * (lb - lc));
        return js_exp(lx);
    } else if (kind_is(kind, "logdt")) {
        double la = js_log(pd_param(p, "min"));
        double lb = js_log(pd_param(p, "max"));
        double lc = js_log(pd_param(p, "mode"));
        double lx = u <= 0.5 ? la + pd_sqrt(2 * u) * (lc - la) : lb - (lb - lc) * pd_sqrt(2 * (1 - u));
        return js_exp(lx);
    } else if (kind_is(kind, "norm")) {
        return pd_param(p, "mean") + pd_param(p, "sd") * probit_or_zero(u);
    } else if (kind_is(kind, "Logn4") || kind_is(kind, "logn") || kind_is(kind, "logn5")) {
        auto ls = pd_log_space(spec);
        return ls ? js_exp(ls->first + ls->second * probit_or_zero(u)) : NaN;
    }
    return NaN;
}

double pdf_quantile(const Json& spec, double u) {
    Json v(u);
    return pdf_quantile(spec, &v);
}

ProbabilityCuts probability_cuts(const Json& spec) {
    double lo = 0.0, hi = 1.0;
    const Json* trmin = pd_prop(spec, "trmin");
    const Json* trmax = pd_prop(spec, "trmax");
    const Json* pmin = pd_prop(spec, "pmin");
    const Json* pmax = pd_prop(spec, "pmax");
    if (!pd_nullish(trmin)) lo = pd_jmax(lo, pdf_cdf(spec, trmin));
    if (!pd_nullish(trmax)) hi = pd_jmin(hi, pdf_cdf(spec, trmax));
    if (!pd_nullish(pmin)) lo = pd_jmax(lo, pd_to_number(pmin));
    if (!pd_nullish(pmax)) hi = pd_jmin(hi, pd_to_number(pmax));
    if (!(hi > lo)) return {0.0, 1.0, false, true};
    return {lo, hi, lo > 0 || hi < 1, false};
}

}  // namespace kompartment
