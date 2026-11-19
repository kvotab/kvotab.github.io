#include "importers/eco_maps.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <map>
#include <unordered_map>

#include "importers/eco_unicode.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

// --- the case tables (eco_unicode.cpp) ----------------------------------------------------------

namespace eco_unicode {

namespace {

char32_t mapped(const CaseRun* runs, std::size_t n, char32_t c) {
    // The last run that starts at or before c.
    std::size_t lo = 0, hi = n;
    while (lo < hi) {
        std::size_t mid = (lo + hi) / 2;
        if (runs[mid].first <= c) lo = mid + 1;
        else hi = mid;
    }
    if (lo == 0) return c;
    const CaseRun& r = runs[lo - 1];
    if (c > r.last || (c - r.first) % r.stride != 0) return c;
    return static_cast<char32_t>(static_cast<std::int64_t>(c) + r.delta);
}

bool within(const Range* ranges, std::size_t n, char32_t c) {
    std::size_t lo = 0, hi = n;
    while (lo < hi) {
        std::size_t mid = (lo + hi) / 2;
        if (ranges[mid].first <= c) lo = mid + 1;
        else hi = mid;
    }
    return lo > 0 && c <= ranges[lo - 1].last;
}

}  // namespace

char32_t lower(char32_t c) { return mapped(LOWER, LOWER_COUNT, c); }
char32_t upper(char32_t c) { return mapped(UPPER, UPPER_COUNT, c); }
bool is_cased(char32_t c) { return within(CASED, CASED_COUNT, c); }
bool is_ignorable_category(char32_t c) { return within(IGNORABLE, IGNORABLE_COUNT, c); }

}  // namespace eco_unicode

namespace eco {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
constexpr double Inf = std::numeric_limits<double>::infinity();

inline unsigned char at(std::string_view s, std::size_t i) { return static_cast<unsigned char>(s[i]); }

}  // namespace

// --- strings ---------------------------------------------------------------------------------

std::size_t js_space_bytes(std::string_view s, std::size_t i, std::size_t n) {
    const unsigned char b = at(s, i);
    if (b < 0x80) return (b == 0x20 || (b >= 0x09 && b <= 0x0d)) ? 1 : 0;
    if (b == 0xc2) return (i + 1 < n && at(s, i + 1) == 0xa0) ? 2 : 0;
    if (b == 0xe1) return (i + 2 < n && at(s, i + 1) == 0x9a && at(s, i + 2) == 0x80) ? 3 : 0;
    if (b == 0xe2) {
        if (!(i + 2 < n)) return 0;
        const unsigned char b1 = at(s, i + 1), b2 = at(s, i + 2);
        if (b1 == 0x80) return ((b2 >= 0x80 && b2 <= 0x8a) || b2 == 0xa8 || b2 == 0xa9 || b2 == 0xaf) ? 3 : 0;
        if (b1 == 0x81) return b2 == 0x9f ? 3 : 0;
        return 0;
    }
    if (b == 0xe3) return (i + 2 < n && at(s, i + 1) == 0x80 && at(s, i + 2) == 0x80) ? 3 : 0;
    if (b == 0xef) return (i + 2 < n && at(s, i + 1) == 0xbb && at(s, i + 2) == 0xbf) ? 3 : 0;
    return 0;
}

std::pair<std::size_t, std::size_t> js_trim_range(std::string_view s, std::size_t a, std::size_t b) {
    while (a < b) {
        const std::size_t k = js_space_bytes(s, a, b);
        if (k == 0) break;
        a += k;
    }
    while (b > a) {
        // The start of the character ending at b.
        std::size_t s0 = b - 1;
        while (s0 > a && (at(s, s0) & 0xc0) == 0x80) s0--;
        if (js_space_bytes(s, s0, b) != b - s0) break;
        b = s0;
    }
    return {a, b};
}

std::string js_trim(std::string_view s) {
    auto [a, b] = js_trim_range(s, 0, s.size());
    return std::string(s.substr(a, b - a));
}

char32_t char_at(std::string_view s, std::size_t i, std::size_t& len) {
    const unsigned char c = at(s, i);
    auto cont = [&](std::size_t k) -> char32_t { return i + k < s.size() ? (at(s, i + k) & 0x3f) : 0; };
    if (c < 0x80) {
        len = 1;
        return c;
    }
    if (c < 0xe0) {
        len = std::min<std::size_t>(2, s.size() - i);
        return (static_cast<char32_t>(c & 0x1f) << 6) | cont(1);
    }
    if (c < 0xf0) {
        len = std::min<std::size_t>(3, s.size() - i);
        return (static_cast<char32_t>(c & 0x0f) << 12) | (cont(1) << 6) | cont(2);
    }
    len = std::min<std::size_t>(4, s.size() - i);
    return (static_cast<char32_t>(c & 0x07) << 18) | (cont(1) << 12) | (cont(2) << 6) | cont(3);
}

void put_char(std::string& out, char32_t c) {
    if (c < 0x80) {
        out.push_back(static_cast<char>(c));
    } else if (c < 0x800) {
        out.push_back(static_cast<char>(0xc0 | (c >> 6)));
        out.push_back(static_cast<char>(0x80 | (c & 0x3f)));
    } else if (c < 0x10000) {
        out.push_back(static_cast<char>(0xe0 | (c >> 12)));
        out.push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | (c & 0x3f)));
    } else {
        out.push_back(static_cast<char>(0xf0 | (c >> 18)));
        out.push_back(static_cast<char>(0x80 | ((c >> 12) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | (c & 0x3f)));
    }
}

std::size_t js_len(std::string_view s) {
    std::size_t n = 0;
    for (std::size_t i = 0; i < s.size();) {
        std::size_t k = 1;
        const char32_t c = char_at(s, i, k);
        n += c > 0xffff ? 2 : 1;
        i += k;
    }
    return n;
}

std::size_t utf16_pos(std::string_view s, std::size_t i) {
    std::size_t n = 0;
    const std::size_t stop = std::min(i, s.size());
    for (std::size_t k = 0; k < stop;) {
        std::size_t len = 1;
        const char32_t c = char_at(s, k, len);
        n += c > 0xffff ? 2 : 1;
        k += len;
    }
    return n;
}

std::string js_identifier(std::string_view s) {
    std::string out;
    out.reserve(s.size());
    for (std::size_t i = 0; i < s.size();) {
        std::size_t k = 1;
        const char32_t c = char_at(s, i, k);
        if (c < 0x80 && is_ident_char(static_cast<unsigned char>(c))) out.push_back(static_cast<char>(c));
        else out += c > 0xffff ? "__" : "_";
        i += k;
    }
    return out;
}

bool ascii_ieq(std::string_view s, std::string_view w) {
    if (s.size() != w.size()) return false;
    for (std::size_t k = 0; k < s.size(); k++) {
        unsigned char x = at(s, k), y = at(w, k);
        if (x >= 'A' && x <= 'Z') x += 0x20;
        if (y >= 'A' && y <= 'Z') y += 0x20;
        if (x != y) return false;
    }
    return true;
}

std::string ascii_lower(std::string_view s) {
    std::string out(s);
    for (char& c : out)
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c + 32);
    return out;
}

namespace {

bool is_ascii_text(std::string_view s) {
    for (char c : s)
        if (static_cast<unsigned char>(c) >= 0x80) return false;
    return true;
}

// Python's full upper-case mappings, where one character becomes several (`_ECO_UPPER_MULTI`).
const std::unordered_map<char32_t, std::u32string>& upper_multi() {
    static const std::unordered_map<char32_t, std::u32string> m = {
        {0x00DF, U"SS"}, {0x0149, U"\u02BCN"}, {0x01F0, U"J\u030C"},
        {0x0390, U"\u0399\u0308\u0301"}, {0x03B0, U"\u03A5\u0308\u0301"}, {0x0587, U"\u0535\u0552"},
        {0x1E96, U"H\u0331"}, {0x1E97, U"T\u0308"}, {0x1E98, U"W\u030A"}, {0x1E99, U"Y\u030A"},
        {0x1E9A, U"A\u02BE"}, {0x1F50, U"\u03A5\u0313"}, {0x1F52, U"\u03A5\u0313\u0300"},
        {0x1F54, U"\u03A5\u0313\u0301"}, {0x1F56, U"\u03A5\u0313\u0342"}, {0x1F80, U"\u1F08\u0399"},
        {0x1F81, U"\u1F09\u0399"}, {0x1F82, U"\u1F0A\u0399"}, {0x1F83, U"\u1F0B\u0399"},
        {0x1F84, U"\u1F0C\u0399"}, {0x1F85, U"\u1F0D\u0399"}, {0x1F86, U"\u1F0E\u0399"},
        {0x1F87, U"\u1F0F\u0399"}, {0x1F88, U"\u1F08\u0399"}, {0x1F89, U"\u1F09\u0399"},
        {0x1F8A, U"\u1F0A\u0399"}, {0x1F8B, U"\u1F0B\u0399"}, {0x1F8C, U"\u1F0C\u0399"},
        {0x1F8D, U"\u1F0D\u0399"}, {0x1F8E, U"\u1F0E\u0399"}, {0x1F8F, U"\u1F0F\u0399"},
        {0x1F90, U"\u1F28\u0399"}, {0x1F91, U"\u1F29\u0399"}, {0x1F92, U"\u1F2A\u0399"},
        {0x1F93, U"\u1F2B\u0399"}, {0x1F94, U"\u1F2C\u0399"}, {0x1F95, U"\u1F2D\u0399"},
        {0x1F96, U"\u1F2E\u0399"}, {0x1F97, U"\u1F2F\u0399"}, {0x1F98, U"\u1F28\u0399"},
        {0x1F99, U"\u1F29\u0399"}, {0x1F9A, U"\u1F2A\u0399"}, {0x1F9B, U"\u1F2B\u0399"},
        {0x1F9C, U"\u1F2C\u0399"}, {0x1F9D, U"\u1F2D\u0399"}, {0x1F9E, U"\u1F2E\u0399"},
        {0x1F9F, U"\u1F2F\u0399"}, {0x1FA0, U"\u1F68\u0399"}, {0x1FA1, U"\u1F69\u0399"},
        {0x1FA2, U"\u1F6A\u0399"}, {0x1FA3, U"\u1F6B\u0399"}, {0x1FA4, U"\u1F6C\u0399"},
        {0x1FA5, U"\u1F6D\u0399"}, {0x1FA6, U"\u1F6E\u0399"}, {0x1FA7, U"\u1F6F\u0399"},
        {0x1FA8, U"\u1F68\u0399"}, {0x1FA9, U"\u1F69\u0399"}, {0x1FAA, U"\u1F6A\u0399"},
        {0x1FAB, U"\u1F6B\u0399"}, {0x1FAC, U"\u1F6C\u0399"}, {0x1FAD, U"\u1F6D\u0399"},
        {0x1FAE, U"\u1F6E\u0399"}, {0x1FAF, U"\u1F6F\u0399"}, {0x1FB2, U"\u1FBA\u0399"},
        {0x1FB3, U"\u0391\u0399"}, {0x1FB4, U"\u0386\u0399"}, {0x1FB6, U"\u0391\u0342"},
        {0x1FB7, U"\u0391\u0342\u0399"}, {0x1FBC, U"\u0391\u0399"}, {0x1FC2, U"\u1FCA\u0399"},
        {0x1FC3, U"\u0397\u0399"}, {0x1FC4, U"\u0389\u0399"}, {0x1FC6, U"\u0397\u0342"},
        {0x1FC7, U"\u0397\u0342\u0399"}, {0x1FCC, U"\u0397\u0399"}, {0x1FD2, U"\u0399\u0308\u0300"},
        {0x1FD3, U"\u0399\u0308\u0301"}, {0x1FD6, U"\u0399\u0342"}, {0x1FD7, U"\u0399\u0308\u0342"},
        {0x1FE2, U"\u03A5\u0308\u0300"}, {0x1FE3, U"\u03A5\u0308\u0301"}, {0x1FE4, U"\u03A1\u0313"},
        {0x1FE6, U"\u03A5\u0342"}, {0x1FE7, U"\u03A5\u0308\u0342"}, {0x1FF2, U"\u1FFA\u0399"},
        {0x1FF3, U"\u03A9\u0399"}, {0x1FF4, U"\u038F\u0399"}, {0x1FF6, U"\u03A9\u0342"},
        {0x1FF7, U"\u03A9\u0342\u0399"}, {0x1FFC, U"\u03A9\u0399"}, {0xFB00, U"FF"},
        {0xFB01, U"FI"}, {0xFB02, U"FL"}, {0xFB03, U"FFI"},
        {0xFB04, U"FFL"}, {0xFB05, U"ST"}, {0xFB06, U"ST"}, {0xFB13, U"\u0544\u0546"},
        {0xFB14, U"\u0544\u0535"}, {0xFB15, U"\u0544\u053B"}, {0xFB16, U"\u054E\u0546"}, {0xFB17, U"\u0544\u053D"},
    };
    return m;
}


std::u32string decode_all(std::string_view s) {
    std::u32string out;
    for (std::size_t i = 0; i < s.size();) {
        std::size_t k = 1;
        out.push_back(char_at(s, i, k));
        i += k;
    }
    return out;
}

}  // namespace

bool is_case_ignorable(char32_t c) {
    switch (c) {
        case '\'': case '.': case ':': case '^': case '`': case 0xA8: case 0xAD: case 0xAF: case 0xB4: case 0xB7:
        case 0xB8: case 0x2018: case 0x2019: case 0x2024: case 0x2027:
            return true;
        default:
            return eco_unicode::is_ignorable_category(c);
    }
}

std::string py_upper(std::string_view s) {
    std::string out;
    out.reserve(s.size());
    if (is_ascii_text(s)) {
        for (char c : s) out.push_back(c >= 'a' && c <= 'z' ? static_cast<char>(c - 32) : c);
        return out;
    }
    const auto& multi = upper_multi();
    for (std::size_t i = 0; i < s.size();) {
        std::size_t k = 1;
        const char32_t c = char_at(s, i, k);
        auto it = multi.find(c);
        if (it != multi.end())
            for (char32_t m : it->second) put_char(out, m);
        else put_char(out, eco_unicode::upper(c));
        i += k;
    }
    return out;
}

std::string py_lower(std::string_view s) {
    std::string out;
    out.reserve(s.size());
    if (is_ascii_text(s)) {
        for (char c : s) out.push_back(c >= 'A' && c <= 'Z' ? static_cast<char>(c + 32) : c);
        return out;
    }
    const std::u32string chars = decode_all(s);
    const std::size_t n = chars.size();
    for (std::size_t k = 0; k < n; k++) {
        const char32_t c = chars[k];
        if (c == 0x130) {
            out += "i\xcc\x87";
        } else if (c == 0x3A3) {
            // Final_Sigma: a cased letter before (case-ignorables skipped), and none after.
            std::ptrdiff_t j = static_cast<std::ptrdiff_t>(k) - 1;
            while (j >= 0 && is_case_ignorable(chars[static_cast<std::size_t>(j)])) j--;
            bool final_ = j >= 0 && eco_unicode::is_cased(chars[static_cast<std::size_t>(j)]);
            if (final_ && k + 1 < n) {
                std::size_t m = k + 1;
                while (m < n && is_case_ignorable(chars[m])) m++;
                final_ = m >= n || !eco_unicode::is_cased(chars[m]);
            }
            put_char(out, final_ ? 0x3C2 : 0x3C3);
        } else {
            put_char(out, eco_unicode::lower(c));
        }
    }
    return out;
}

// --- numbers ---------------------------------------------------------------------------------

bool is_js_decimal(std::string_view cu) {
    const std::size_t n = cu.size();
    std::size_t i = 0;
    if (n == 0) return false;
    if (cu[i] == '+' || cu[i] == '-') i++;
    if (i >= n) return false;
    if (n - i == 8 && cu.substr(i) == "Infinity") return true;
    std::size_t d1 = 0, d2 = 0;
    while (i < n && is_ascii_digit(at(cu, i))) {
        i++;
        d1++;
    }
    if (i < n && cu[i] == '.') {
        i++;
        while (i < n && is_ascii_digit(at(cu, i))) {
            i++;
            d2++;
        }
    }
    if (d1 + d2 == 0) return false;
    if (i < n && (cu[i] == 'e' || cu[i] == 'E')) {
        i++;
        if (i < n && (cu[i] == '+' || cu[i] == '-')) i++;
        std::size_t d3 = 0;
        while (i < n && is_ascii_digit(at(cu, i))) {
            i++;
            d3++;
        }
        if (d3 == 0) return false;
    }
    return i >= n;
}

double parse_decimal(std::string_view s) {
    if (!s.empty() && s.back() == 'y') return s[0] == '-' ? -Inf : Inf;   // ...Infinity
    // What the C library makes of it, as Python's float does: the nearest double, infinity
    // past the range and zero (or a subnormal) below it.
    const std::string text(s);
    return std::strtod(text.c_str(), nullptr);
}

double radix_to_double(std::string_view digits, int base) {
    const int per = base == 16 ? 4 : base == 8 ? 3 : 1;
    // The number's bits, most significant first, without leading zeros.
    std::vector<unsigned char> bits;
    bits.reserve(digits.size() * static_cast<std::size_t>(per));
    for (char ch : digits) {
        const unsigned char c = static_cast<unsigned char>(ch);
        const int v = is_ascii_digit(c) ? c - '0' : (c >= 'a' && c <= 'z') ? c - 'a' + 10 : c - 'A' + 10;
        for (int k = per - 1; k >= 0; k--) {
            const unsigned char bit = static_cast<unsigned char>((v >> k) & 1);
            if (bits.empty() && bit == 0) continue;
            bits.push_back(bit);
        }
    }
    const std::size_t n = bits.size();
    if (n == 0) return 0.0;
    if (n <= 53) {
        std::uint64_t m = 0;
        for (unsigned char b : bits) m = (m << 1) | b;
        return static_cast<double>(m);
    }
    // The top 53 bits, rounded to nearest with ties to even on what follows.
    std::uint64_t m = 0;
    for (std::size_t k = 0; k < 53; k++) m = (m << 1) | bits[k];
    const bool half = bits[53] != 0;
    bool sticky = false;
    for (std::size_t k = 54; k < n && !sticky; k++) sticky = bits[k] != 0;
    if (half && (sticky || (m & 1))) m++;
    long exponent = static_cast<long>(n) - 53;
    if (m == (std::uint64_t{1} << 53)) {
        m >>= 1;
        exponent++;
    }
    if (exponent + 53 > 1024) return Inf;
    return std::ldexp(static_cast<double>(m), static_cast<int>(exponent));
}

namespace {

// `int(digits, base)` in Python: the base's prefix may lead, and every character must be a
// digit of the base. Nothing where Python raises.
std::optional<double> py_int(std::string_view s, int base) {
    if (s.size() >= 2 && s[0] == '0') {
        char p = s[1];
        if (p >= 'A' && p <= 'Z') p = static_cast<char>(p + 32);
        if ((base == 16 && p == 'x') || (base == 8 && p == 'o') || (base == 2 && p == 'b')) s.remove_prefix(2);
    }
    if (s.empty()) return std::nullopt;
    for (char ch : s) {
        const unsigned char c = static_cast<unsigned char>(ch);
        const int v = is_ascii_digit(c) ? c - '0' : (c >= 'a' && c <= 'z') ? c - 'a' + 10 : (c >= 'A' && c <= 'Z') ? c - 'A' + 10 : 99;
        if (v >= base) return std::nullopt;
    }
    return radix_to_double(s, base);
}

}  // namespace

double to_number(std::string_view v) {
    const std::string s = js_trim(v);
    if (s.empty()) return 0.0;
    if (is_js_decimal(s)) return parse_decimal(s);
    const std::size_t n = s.size();
    if (n >= 3 && s[0] == '0' && std::strchr("xXoObB", s[1]) != nullptr && s[1] != '\0') {
        bool ok = true;
        for (std::size_t k = 2; k < n && ok; k++) ok = is_ident_char(at(s, k)) && s[k] != '_';
        if (ok) {
            const int base = (s[1] == 'x' || s[1] == 'X') ? 16 : (s[1] == 'o' || s[1] == 'O') ? 8 : 2;
            std::optional<double> whole = py_int(std::string_view(s).substr(2), base);
            return whole ? *whole : NaN;
        }
    }
    return NaN;
}

double to_number(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return 0.0;
        case Json::Type::Bool: return v.as_bool() ? 1.0 : 0.0;
        case Json::Type::Int:
        case Json::Type::Float: return v.as_double();
        case Json::Type::String: return to_number(std::string_view(v.as_string()));
        default: return NaN;
    }
}

bool is_finite_number(const Json& v) { return v.is_number() && std::isfinite(v.as_double()); }

double js_round(double f) {
    if (!std::isfinite(f)) return f;
    double r = std::floor(f);
    if (f - r >= 0.5) r += 1;
    return r;
}

double js_floor(double f) { return std::isfinite(f) ? std::floor(f) : f; }

std::string js_string(double f) {
    if (std::isnan(f)) return "NaN";
    if (std::isinf(f)) return f > 0 ? "Infinity" : "-Infinity";
    return js_number(f);
}

std::string js_string(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return "null";
        case Json::Type::Bool: return v.as_bool() ? "true" : "false";
        case Json::Type::Int:
        case Json::Type::Float: return js_string(v.as_double());
        case Json::Type::String: return v.as_string();
        default: return js_text(v);
    }
}

namespace {

// Every significant digit of the positive finite x's binary value (a double has at most 767;
// what follows them is zeros), and the exponent of the first: x = d1.d2d3... \u00D7 10^adjusted.
std::pair<std::string, int> exact_decimal(double x) {
    char buf[840];
    std::snprintf(buf, sizeof buf, "%.800e", x);
    std::string digits;
    const char* c = buf;
    for (; *c && *c != 'e'; c++)
        if (*c >= '0' && *c <= '9') digits.push_back(*c);
    return {digits, std::atoi(c + 1)};
}

}  // namespace

double round_significant(double f, int digits) {
    if (f == 0 || !std::isfinite(f)) return f;
    auto [d, adjusted] = exact_decimal(std::fabs(f));
    const std::size_t keep_n = std::min<std::size_t>(static_cast<std::size_t>(digits), d.size());
    std::string kept = d.substr(0, keep_n);
    const bool up = d.size() > static_cast<std::size_t>(digits) && d[static_cast<std::size_t>(digits)] >= '5';
    const int exp10 = adjusted - static_cast<int>(kept.size()) + 1;
    if (up) {
        std::size_t k = kept.size();
        while (k > 0 && kept[k - 1] == '9') kept[--k] = '0';
        if (k > 0) kept[k - 1]++;
        else kept.insert(kept.begin(), '1');
    }
    // A leading zero is never kept: the first digit of an exact value is not 0.
    const double v = parse_decimal(kept + "e" + std::to_string(exp10));
    return f < 0 ? -v : v;
}

std::string to_exponential(double f) {
    if (!std::isfinite(f)) return js_string(f);
    if (f == 0) return "0e+0";
    const std::string sign = f < 0 ? "-" : "";
    auto [digits, n] = shortest_digits(std::fabs(f));
    const int e = n - 1;
    const std::string mant = digits.size() == 1 ? digits : digits.substr(0, 1) + "." + digits.substr(1);
    return sign + mant + "e" + (e >= 0 ? "+" : "-") + std::to_string(std::abs(e));
}

// --- dates -----------------------------------------------------------------------------------

namespace {

std::int64_t floor_div(std::int64_t a, std::int64_t b) {
    std::int64_t q = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))) q--;
    return q;
}

std::string lpad(std::string s, std::size_t width) {
    if (s.size() < width) s.insert(0, width - s.size(), '0');
    return s;
}

}  // namespace

std::string iso_date(double ms) {
    if (!std::isfinite(ms) || std::fabs(ms) > 8.64e15) throw EcoArgumentError("Invalid time value");
    const std::int64_t t = static_cast<std::int64_t>(std::trunc(ms));
    std::int64_t z = floor_div(t, 86400000) + 719468;
    const std::int64_t era = floor_div(z, 146097);
    const std::int64_t doe = z - era * 146097;
    const std::int64_t yoe = floor_div(doe - floor_div(doe, 1460) + floor_div(doe, 36524) - floor_div(doe, 146096), 365);
    std::int64_t y = yoe + era * 400;
    const std::int64_t doy = doe - (365 * yoe + floor_div(yoe, 4) - floor_div(yoe, 100));
    const std::int64_t mp = floor_div(5 * doy + 2, 153);
    const std::int64_t d = doy - floor_div(153 * mp + 2, 5) + 1;
    const std::int64_t m = mp < 10 ? mp + 3 : mp - 9;
    if (m <= 2) y += 1;
    const std::string year = (y >= 0 && y <= 9999) ? lpad(std::to_string(y), 4)
                                                   : std::string(y > 0 ? "+" : "-") + lpad(std::to_string(y < 0 ? -y : y), 6);
    const std::string s = year + "-" + lpad(std::to_string(m), 2) + "-" + lpad(std::to_string(d), 2);
    return s.substr(0, 10);
}

// --- objects ---------------------------------------------------------------------------------

namespace {

bool is_array_index(std::string_view k) {
    if (k.empty()) return false;
    if (k.size() > 1 && k[0] == '0') return false;
    for (char c : k)
        if (!is_ascii_digit(static_cast<unsigned char>(c))) return false;
    if (k.size() > 10) return false;
    return std::stoull(std::string(k)) <= 4294967294ULL;
}

}  // namespace

Json js_object_order(const Json& d) {
    std::vector<std::pair<unsigned long long, std::string>> ints;
    for (const auto& [k, v] : d.obj())
        if (is_array_index(k)) ints.emplace_back(std::stoull(k), k);
    if (ints.empty()) return d;
    std::stable_sort(ints.begin(), ints.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
    Json out = Json::object();
    for (const auto& [n, k] : ints) out.set(k, d.get(k));
    for (const auto& [k, v] : d.obj())
        if (!out.has(k)) out.set(k, v);
    return out;
}

// --- localeCompare ---------------------------------------------------------------------------

namespace {

void collation_key(std::string_view text, std::vector<long>& primary, std::vector<long>& tertiary) {
    for (std::size_t i = 0; i < text.size();) {
        std::size_t k = 1;
        const long o = static_cast<long>(char_at(text, i, k));
        i += k;
        if (o == '_') primary.push_back(1);
        else if (o >= 48 && o <= 57) primary.push_back(2 + o - 48);
        else if (o >= 97 && o <= 122) primary.push_back(12 + o - 97);
        else if (o >= 65 && o <= 90) primary.push_back(12 + o - 65);
        else primary.push_back(100 + o);
        tertiary.push_back((o >= 65 && o <= 90) ? 1 : 0);
    }
}

}  // namespace

bool collation_less(std::string_view a, std::string_view b) {
    std::vector<long> pa, ta, pb, tb;
    collation_key(a, pa, ta);
    collation_key(b, pb, tb);
    if (pa != pb) return std::lexicographical_compare(pa.begin(), pa.end(), pb.begin(), pb.end());
    return std::lexicographical_compare(ta.begin(), ta.end(), tb.begin(), tb.end());
}

// --- the mappers eco.js imports --------------------------------------------------------------

double seconds_per_year(std::string_view unit) {
    if (unit == "minute" || unit == "second" || unit == "hour" || unit == "day") return 365.25 * 24 * 3600;
    return 31556952.0;
}

namespace {

const std::vector<std::string>& prototype_members() {
    static const std::vector<std::string> v = {"constructor", "__defineGetter__", "__defineSetter__", "hasOwnProperty",
                                               "__lookupGetter__", "__lookupSetter__", "isPrototypeOf",
                                               "propertyIsEnumerable", "toString", "valueOf", "__proto__", "toLocaleString"};
    return v;
}

PlainValue plain_lookup(const std::vector<std::pair<std::string, std::string>>& table, const std::string& key) {
    PlainValue out;
    for (const auto& [k, v] : table)
        if (k == key) {
            out.kind = PlainValue::Kind::Own;
            out.value = v;
            return out;
        }
    for (const auto& m : prototype_members())
        if (m == key) {
            out.kind = PlainValue::Kind::Inherited;
            out.value = key;
            out.is_function = key != "__proto__";
            return out;
        }
    return out;
}

}  // namespace

PlainValue interpolation_from_eco(const std::optional<std::string>& name) {
    static const std::vector<std::pair<std::string, std::string>> table = {
        {"Interpolation-Use End Values", "linear"}, {"Interpolation-Extrapolation", "extrapolate"},
        {"Use Input Below", "below"}, {"Use Input Above", "above"}, {"Use Input Nearest", "nearest"}};
    return plain_lookup(table, js_trim(name ? *name : ""));
}

std::optional<std::string> operation_from_eco(const std::optional<std::string>& name) {
    static const std::map<std::string, std::string> table = {
        {"SUM", "sum"}, {"PRODUCT", "product"}, {"MIN", "min"}, {"MAX", "max"}, {"MEAN", "mean"},
        {"PERCENTILE", "percentile"}, {"Sum", "sum"}, {"Product", "product"}, {"Minimum", "min"},
        {"Maximum", "max"}, {"Mean", "mean"}, {"Percentile", "percentile"}};
    auto it = table.find(js_trim(name ? *name : ""));
    if (it == table.end()) return std::nullopt;
    return it->second;
}

std::optional<std::string> kind_from_eco(std::string_view type) {
    if (type == "min-max") return "min_max";
    if (type == "running-mean") return "running_mean";
    if (type == "snapshot") return "snapshot";
    if (type == "delay") return "delay";
    if (type == "discrete-event") return "trigger";
    return std::nullopt;
}

const std::vector<std::string>& event_fields(std::string_view kind) {
    static const std::vector<std::string> recorder = {"reset_trigger", "start_trigger", "stop_trigger"};
    static const std::vector<std::string> snapshot = {"trigger"};
    static const std::vector<std::string> none;
    if (kind == "min_max" || kind == "running_mean") return recorder;
    if (kind == "snapshot") return snapshot;
    return none;
}

const std::vector<std::string>& equation_fields(std::string_view kind) {
    static const std::vector<std::string> target = {"target"};
    static const std::vector<std::string> snapshot = {"target", "initial"};
    static const std::vector<std::string> delay = {"target", "delay"};
    static const std::vector<std::string> trigger = {"first", "second"};
    static const std::vector<std::string> none;
    if (kind == "min_max" || kind == "running_mean") return target;
    if (kind == "snapshot") return snapshot;
    if (kind == "delay") return delay;
    if (kind == "trigger") return trigger;
    return none;
}

std::optional<std::string> extreme_from_eco(const std::optional<std::string>& name) {
    const std::string s = py_upper(js_trim(name ? *name : ""));
    if (s == "MIN") return "min";
    if (s == "MAX") return "max";
    return std::nullopt;
}

PlainValue direction_from_eco(const std::optional<std::string>& name) {
    static const std::vector<std::pair<std::string, std::string>> table = {
        {"RIGHT", "rising"}, {"LEFT", "falling"}, {"BOTH", "both"}, {"->", "rising"}, {"<-", "falling"}, {">-<", "both"}};
    const std::string s = js_trim(name ? *name : "");
    PlainValue found = plain_lookup(table, py_upper(s));
    if (found.kind == PlainValue::Kind::None) found = plain_lookup(table, s);
    return found;
}

std::string solver_name(const Json& solver_id) {
    static const std::map<std::string, std::string> labels = {
        {"ndf", "stiff, NDF"},
        {"ros23", "stiff, low order, Rosenbrock 2-3"},
        {"dp45", "non-stiff, Dormand-Prince 4-5"},
        {"auto", "stiff or non-stiff, switching as it runs"},
        {"auto_julia", "stiff or non-stiff, as DifferentialEquations.jl chooses"},
        {"rodas5p", "stiff, Rosenbrock 5"},
        {"radau5", "stiff, Radau IIA 5"},
        {"fbdf", "stiff, fixed-leading-coefficient BDF"},
        {"fbdf_krylov", "stiff, FBDF by GMRES, no matrix"},
        {"qndf", "stiff, quasi-constant-step NDF"},
        {"kencarp4", "stiff, ESDIRK 4"},
        {"trbdf2", "stiff, ESDIRK 2 (loose tolerances)"},
        {"rosenbrock23", "stiff, low order, Rosenbrock 2-3 as in Julia"},
        {"tsit5", "non-stiff, Tsitouras 5"},
        {"vern7", "non-stiff, Verner 7"},
        {"scipy_bdf", "SciPy BDF, stiff"},
        {"scipy_radau", "SciPy Radau IIA, stiff"},
        {"scipy_lsoda", "SciPy LSODA, auto-switching"},
    };
    if (solver_id.is_string()) {
        auto it = labels.find(solver_id.as_string());
        if (it != labels.end() && !it->second.empty()) return it->second + " (" + solver_id.as_string() + ")";
    }
    return js_string(solver_id);
}

std::string kind_label(std::string_view kind) {
    static const std::map<std::string, std::string, std::less<>> labels = {
        {"compartment", "Compartments"}, {"transfer", "Transfers"}, {"inflow", "Inflows"},
        {"expression", "Expressions"}, {"parameter", "Parameters"}, {"lookup", "Lookup tables"},
        {"index_reduction", "Reduce over an index"}, {"block_reduction", "Combine blocks"},
        {"function", "Functions"}, {"min_max", "Min/max"}, {"running_mean", "Running means"},
        {"snapshot", "Snapshots"}, {"delay", "Delays"}, {"trigger", "Triggers"},
        {"farfield", "Far-field pathways"}, {"waste_package", "Waste packages"}, {"event", "Events"},
        {"farfield_inventory", "Path inventories"}, {"farfield_cell", "Path cells"},
        {"waste_inventory", "Package inventories"}};
    auto it = labels.find(kind);
    return it == labels.end() ? std::string() : it->second;
}

std::string singular(std::string_view collection) {
    static const std::map<std::string, std::string, std::less<>> names = {
        {"compartments", "compartment"}, {"transfers", "transfer"}, {"inflows", "inflow"},
        {"parameters", "parameter"}, {"expressions", "expression"}, {"lookups", "lookup"},
        {"index_reductions", "index_reduction"}, {"block_reductions", "block_reduction"},
        {"functions", "function"}, {"min_maxes", "min_max"}, {"running_means", "running_mean"},
        {"snapshots", "snapshot"}, {"delays", "delay"}, {"triggers", "trigger"}, {"farfields", "farfield"},
        {"waste_packages", "waste_package"}, {"events", "event"}};
    auto it = names.find(collection);
    return it == names.end() ? std::string() : it->second;
}

}  // namespace eco
}  // namespace kompartment
