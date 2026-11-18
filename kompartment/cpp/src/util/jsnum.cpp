#include "util/jsnum.hpp"

#include <charconv>
#include <cmath>
#include <cstdlib>
#include <limits>

namespace kompartment {

std::pair<std::string, int> shortest_digits(double x) {
    // The shortest digits that read back as x, in scientific form: d[.ddd]e±XX.
    char buf[40];
    auto res = std::to_chars(buf, buf + sizeof buf, x, std::chars_format::scientific);
    std::string_view s(buf, static_cast<std::size_t>(res.ptr - buf));
    std::size_t epos = s.find('e');
    int e = std::atoi(std::string(s.substr(epos + 1)).c_str());
    std::string digits;
    for (char c : s.substr(0, epos))
        if (c != '.') digits.push_back(c);
    // value = d.ddd × 10^e = 0.dddd × 10^(e + 1)
    int n = e + 1;
    std::size_t stop = digits.size();
    while (stop > 1 && digits[stop - 1] == '0') stop--;
    digits.resize(stop);
    return {digits, n};
}

std::string js_number(long long x) { return std::to_string(x); }

std::string js_number(double f) {
    if (std::isnan(f) || std::isinf(f)) return "null";
    if (f == 0) return "0";
    std::string sign = f < 0 ? "-" : "";
    auto [digits, n] = shortest_digits(std::fabs(f));
    int k = static_cast<int>(digits.size());
    if (k <= n && n <= 21) return sign + digits + std::string(static_cast<std::size_t>(n - k), '0');
    if (0 < n && n <= 21) return sign + digits.substr(0, static_cast<std::size_t>(n)) + "." + digits.substr(static_cast<std::size_t>(n));
    if (-6 < n && n <= 0) return sign + "0." + std::string(static_cast<std::size_t>(-n), '0') + digits;
    int e = n - 1;
    std::string mant = k == 1 ? digits : digits.substr(0, 1) + "." + digits.substr(1);
    return sign + mant + "e" + (e >= 0 ? "+" : "-") + std::to_string(std::abs(e));
}

std::string js_text(double f) {
    if (std::isnan(f)) return "NaN";
    if (std::isinf(f)) return f > 0 ? "Infinity" : "-Infinity";
    return js_number(f);
}

std::string js_text(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return "null";
        case Json::Type::Bool: return v.as_bool() ? "true" : "false";
        case Json::Type::Int: return std::to_string(v.as_int());
        case Json::Type::Float: return js_text(v.as_double());
        case Json::Type::String: return v.as_string();
        case Json::Type::Array: {
            std::string out;
            bool first = true;
            for (const Json& x : v.arr()) {
                if (!first) out.push_back(',');
                first = false;
                if (!x.is_null()) out += js_text(x);
            }
            return out;
        }
        case Json::Type::Object: return "[object Object]";
    }
    return "";
}

std::string js_str(const Json& v) {
    switch (v.type()) {
        case Json::Type::String: return v.as_string();
        case Json::Type::Bool: return v.as_bool() ? "true" : "false";
        case Json::Type::Int: return std::to_string(v.as_int());
        case Json::Type::Float: return js_number(v.as_double());
        case Json::Type::Null: return "null";
        default: return js_text(v);
    }
}

namespace {

// The white space `trim()` strips: the ASCII ones, the no-break space, the byte-order mark,
// the line and paragraph separators and the Unicode space separators.
std::size_t space_at(std::string_view s, std::size_t i) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    if (c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' || c == '\f') return 1;
    if (c == 0xc2 && i + 1 < s.size() && static_cast<unsigned char>(s[i + 1]) == 0xa0) return 2;   // U+00A0
    if (i + 2 < s.size()) {
        unsigned char d = static_cast<unsigned char>(s[i + 1]), e = static_cast<unsigned char>(s[i + 2]);
        if (c == 0xef && d == 0xbb && e == 0xbf) return 3;                         // U+FEFF
        if (c == 0xe2 && d == 0x80 && (e >= 0x80 && e <= 0x8a)) return 3;          // U+2000..U+200A
        if (c == 0xe2 && d == 0x80 && (e == 0xa8 || e == 0xa9 || e == 0xaf)) return 3;   // U+2028, U+2029, U+202F
        if (c == 0xe2 && d == 0x81 && e == 0x9f) return 3;                         // U+205F
        if (c == 0xe3 && d == 0x80 && e == 0x80) return 3;                         // U+3000
        if (c == 0xe1 && d == 0x9a && e == 0x80) return 3;                         // U+1680
    }
    return 0;
}

bool all_of(std::string_view s, bool (*ok)(char)) {
    if (s.empty()) return false;
    for (char c : s)
        if (!ok(c)) return false;
    return true;
}

double from_radix(std::string_view digits, int base) {
    double v = 0;
    for (char c : digits) {
        int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c - 'A' + 10;
        v = v * base + d;
    }
    return v;
}

}  // namespace

std::string_view js_trim(std::string_view s) {
    std::size_t a = 0;
    while (a < s.size()) {
        std::size_t k = space_at(s, a);
        if (!k) break;
        a += k;
    }
    std::size_t b = s.size();
    while (b > a) {
        // Step back over one character: a continuation byte belongs to the one before it.
        std::size_t start = b - 1;
        while (start > a && (static_cast<unsigned char>(s[start]) & 0xc0) == 0x80) start--;
        std::size_t k = space_at(s, start);
        if (!k || start + k != b) break;
        b = start;
    }
    return s.substr(a, b - a);
}

double js_number_of(std::string_view text) {
    std::string_view s = js_trim(text);
    if (s.empty()) return 0.0;
    {
        // (The other engines read the word whatever its case.)
        std::string low(s);
        for (char& c : low)
            if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
        if (low == "infinity" || low == "+infinity") return std::numeric_limits<double>::infinity();
        if (low == "-infinity") return -std::numeric_limits<double>::infinity();
    }
    // A decimal literal: [+-] (digits [. digits*] | . digits) [e [+-] digits]
    {
        std::size_t k = 0, m = s.size();
        if (k < m && (s[k] == '+' || s[k] == '-')) k++;
        std::size_t whole = 0, frac = 0;
        while (k < m && s[k] >= '0' && s[k] <= '9') { k++; whole++; }
        bool ok = true;
        if (k < m && s[k] == '.') {
            k++;
            while (k < m && s[k] >= '0' && s[k] <= '9') { k++; frac++; }
        }
        if (whole == 0 && frac == 0) ok = false;
        if (ok && k < m && (s[k] == 'e' || s[k] == 'E')) {
            k++;
            if (k < m && (s[k] == '+' || s[k] == '-')) k++;
            std::size_t ex = 0;
            while (k < m && s[k] >= '0' && s[k] <= '9') { k++; ex++; }
            if (ex == 0) ok = false;
        }
        if (ok && k == m) return std::strtod(std::string(s).c_str(), nullptr);
    }
    if (s.size() > 2 && s[0] == '0') {
        std::string_view rest = s.substr(2);
        if ((s[1] == 'x' || s[1] == 'X') && all_of(rest, [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'); }))
            return from_radix(rest, 16);
        if ((s[1] == 'o' || s[1] == 'O') && all_of(rest, [](char c) { return c >= '0' && c <= '7'; })) return from_radix(rest, 8);
        if ((s[1] == 'b' || s[1] == 'B') && all_of(rest, [](char c) { return c == '0' || c == '1'; })) return from_radix(rest, 2);
    }
    return std::numeric_limits<double>::quiet_NaN();
}

double js_number_of(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return 0.0;
        case Json::Type::Bool: return v.as_bool() ? 1.0 : 0.0;
        case Json::Type::Int:
        case Json::Type::Float: return v.as_double();
        case Json::Type::String: return js_number_of(std::string_view(v.as_string()));
        case Json::Type::Array:
            if (v.size() == 0) return 0.0;
            if (v.size() == 1) return js_number_of(v[std::size_t{0}]);
            return std::numeric_limits<double>::quiet_NaN();
        default: return std::numeric_limits<double>::quiet_NaN();
    }
}

bool js_truthy_switch(const Json& v, bool fallback) {
    if (fallback) return !((v.is_bool() && !v.as_bool()) || v == "false" || (v.is_number() && v.as_double() == 0));
    return (v.is_bool() && v.as_bool()) || v == "true" || (v.is_number() && v.as_double() == 1);
}

double round_half_up(double x) { return std::floor(x + 0.5); }

std::string py_repr(double x) {
    if (std::isnan(x)) return "nan";
    if (std::isinf(x)) return x > 0 ? "inf" : "-inf";
    if (x == 0) return std::signbit(x) ? "-0.0" : "0.0";
    auto [digits, decpt] = shortest_digits(std::fabs(x));
    int nd = static_cast<int>(digits.size());
    std::string body;
    if (decpt <= -4 || decpt > 16) {
        int e = decpt - 1;
        body = nd == 1 ? digits : digits.substr(0, 1) + "." + digits.substr(1);
        std::string ex = std::to_string(std::abs(e));
        if (ex.size() < 2) ex = "0" + ex;
        body += std::string("e") + (e < 0 ? "-" : "+") + ex;
    } else if (decpt <= 0) {
        body = "0." + std::string(static_cast<std::size_t>(-decpt), '0') + digits;
    } else if (decpt >= nd) {
        body = digits + std::string(static_cast<std::size_t>(decpt - nd), '0') + ".0";
    } else {
        body = digits.substr(0, static_cast<std::size_t>(decpt)) + "." + digits.substr(static_cast<std::size_t>(decpt));
    }
    return x < 0 ? "-" + body : body;
}

}  // namespace kompartment
