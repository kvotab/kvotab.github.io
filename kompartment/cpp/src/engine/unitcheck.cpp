#include "engine/unitcheck.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <unordered_set>

#include "engine/project.hpp"
#include "lang/functions.hpp"
#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

const char32_t MICRO = 0xb5;        // the micro sign
const char32_t MU = 0x3bc;          // the Greek letter
const char32_t MIDDLE_DOT = 0xb7;

// --- text, a character at a time ----------------------------------------------------------------

std::u32string chars_of(std::string_view s) {
    std::u32string out;
    out.reserve(s.size());
    const std::size_t n = s.size();
    for (std::size_t i = 0; i < n;) {
        unsigned char c = static_cast<unsigned char>(s[i]);
        std::size_t len = c < 0x80 ? 1 : (c >> 5) == 0x6 ? 2 : (c >> 4) == 0xe ? 3 : (c >> 3) == 0x1e ? 4 : 1;
        if (i + len > n) len = 1;
        char32_t u = c;
        if (len == 2) u = c & 0x1f;
        else if (len == 3) u = c & 0x0f;
        else if (len == 4) u = c & 0x07;
        for (std::size_t k = 1; k < len; k++) u = (u << 6) | (static_cast<unsigned char>(s[i + k]) & 0x3f);
        out.push_back(u);
        i += len;
    }
    return out;
}

void append_utf8(std::string& out, char32_t u) {
    if (u < 0x80) {
        out.push_back(static_cast<char>(u));
    } else if (u < 0x800) {
        out.push_back(static_cast<char>(0xc0 | (u >> 6)));
        out.push_back(static_cast<char>(0x80 | (u & 0x3f)));
    } else if (u < 0x10000) {
        out.push_back(static_cast<char>(0xe0 | (u >> 12)));
        out.push_back(static_cast<char>(0x80 | ((u >> 6) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | (u & 0x3f)));
    } else {
        out.push_back(static_cast<char>(0xf0 | (u >> 18)));
        out.push_back(static_cast<char>(0x80 | ((u >> 12) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | ((u >> 6) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | (u & 0x3f)));
    }
}

/// The characters `a .. b-1` of `s` as text.
std::string text_of(const std::u32string& s, std::size_t a, std::size_t b) {
    std::string out;
    for (std::size_t k = a; k < b; k++) append_utf8(out, s[k]);
    return out;
}

/// White space as Julia's `strip` takes it: the space, tab to carriage return, the next
/// line character and the spaces of Unicode's category Zs.
bool is_space(char32_t c) {
    return c == ' ' || (c >= '\t' && c <= '\r') || c == 0x85 || c == 0xa0 || c == 0x1680 || (c >= 0x2000 && c <= 0x200a) ||
           c == 0x202f || c == 0x205f || c == 0x3000;
}

std::u32string stripped(const std::u32string& s) {
    std::size_t a = 0, b = s.size();
    while (a < b && is_space(s[a])) a++;
    while (b > a && is_space(s[b - 1])) b--;
    return s.substr(a, b - a);
}

bool is_unit_letter(char32_t c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == MICRO || c == MU; }
bool is_ascii_digit(char32_t c) { return c >= '0' && c <= '9'; }
bool is_ident_start(char32_t c) { return is_unit_letter(c) || c == '_' || c == '%'; }
bool is_ident_part(char32_t c) { return is_ident_start(c) || is_ascii_digit(c) || c == '.'; }

// --- the units known ---------------------------------------------------------------------------------

bool unit_none(const std::string& lowered) {
    static const std::unordered_set<std::string> none = {"", "-", "[-]", "1", "unitless", "dimensionless", "none", "n/a", "[]"};
    return none.count(lowered) != 0;
}

/// The symbol a unit's other spellings stand for; the name itself when it has none.
std::string unit_alias(const std::string& name) {
    static const std::unordered_map<std::string, std::string> alias = {
        {"y", "year"}, {"yr", "year"}, {"years", "year"}, {"a", "year"},
        {"sec", "s"}, {"second", "s"}, {"seconds", "s"},
        {"hour", "h"}, {"hours", "h"},
        {"day", "d"}, {"days", "d"},
        {"litre", "L"}, {"liter", "L"}, {"l", "L"},
        {"Bequerel", "Bq"}, {"becquerel", "Bq"},
        {"Mole", "mol"}, {"mole", "mol"}, {"moles", "mol"},
        {"Sievert", "Sv"}, {"sievert", "Sv"},
        {"kilogram", "kg"}, {"kilograms", "kg"},
        {"metre", "m"}, {"meter", "m"}, {"metres", "m"}, {"meters", "m"},
    };
    auto it = alias.find(name);
    return it == alias.end() ? name : it->second;
}

struct Prefix {
    const char* text;
    double scale;
};
const Prefix UNIT_PREFIX[] = {{"T", 1e12}, {"G", 1e9}, {"M", 1e6}, {"k", 1e3}, {"d", 1e-1}, {"c", 1e-2}, {"m", 1e-3},
                              {"u", 1e-6}, {"\xc2\xb5", 1e-6}, {"\xce\xbc", 1e-6}, {"n", 1e-9}, {"p", 1e-12}};

bool prefixable(const std::string& name) {
    static const std::unordered_set<std::string> units = {"Bq", "Sv", "Gy", "g", "kg", "m", "mol", "L", "s", "J", "W", "Pa", "Ci"};
    return units.count(name) != 0;
}

UnitDim mass_dim(const std::string& base, double scale) {
    return base == "g" ? UnitDim({{"kg", 1}}, scale * 1e-3) : UnitDim({{base, 1}}, scale);
}

std::optional<UnitDim> prefixed(const std::string& name) {
    for (const Prefix& p : UNIT_PREFIX) {
        std::string_view pre(p.text);
        if (!starts_with(name, pre) || name.size() == pre.size()) continue;
        std::string base = unit_alias(name.substr(pre.size()));
        if (base == "kg") continue;
        if (prefixable(base)) return mass_dim(base, p.scale);
    }
    return std::nullopt;
}

UnitDim symbol_dim(const std::u32string& raw) {
    std::u32string chars = stripped(raw);
    if (chars.empty()) return UnitDim();
    std::string sym = text_of(chars, 0, chars.size());
    if (unit_none(lowercase(sym))) return UnitDim();
    // `m3`, `km2`: a length with a power written after it.
    if (chars.size() >= 2 && is_ascii_digit(chars.back()) && std::all_of(chars.begin(), chars.end() - 1, is_unit_letter)) {
        UnitDim base = symbol_dim(chars.substr(0, chars.size() - 1));
        if (base.powers.size() == 1 && base.power("m")) {
            // A whole power of a whole power: always a unit.
            return *dim_pow(base, static_cast<double>(chars.back() - U'0'));
        }
    }
    std::string name = unit_alias(sym);
    if (prefixable(name)) return mass_dim(name, 1.0);
    if (auto p = prefixed(name)) return *p;
    return UnitDim({{name, 1}}, 1.0);
}

// --- reading a unit ------------------------------------------------------------------------------------

struct UnitParser {
    const std::u32string& s;
    const std::size_t len;
    std::size_t at = 0;   // the next character to read
    int depth = 0;
    static constexpr int max_depth = 32;

    explicit UnitParser(const std::u32string& text) : s(text), len(text.size()) {}

    char32_t peek() const { return at < len ? s[at] : U'\0'; }
    void skip() {
        while (at < len && s[at] == ' ') at++;
    }
    double read_number(std::size_t a, std::size_t b) const { return std::strtod(text_of(s, a, b).c_str(), nullptr); }

    std::optional<double> number() {
        std::size_t k = at;
        if (k < len && (s[k] == '+' || s[k] == '-')) k++;
        if (!(k < len && is_ascii_digit(s[k]))) return std::nullopt;
        while (k < len && is_ascii_digit(s[k])) k++;
        if (k + 1 < len && s[k] == '.' && is_ascii_digit(s[k + 1])) {
            k++;
            while (k < len && is_ascii_digit(s[k])) k++;
        }
        double v = read_number(at, k);
        at = k;
        return v;
    }

    std::optional<UnitDim> factor() {
        skip();
        if (at < len && s[at] == '(') {
            if (depth >= max_depth) return std::nullopt;
            at++;
            depth++;
            std::optional<UnitDim> inner = expr();
            depth--;
            skip();
            if (at >= len || s[at] != ')') return std::nullopt;
            at++;
            return inner;
        }
        if (at < len && is_ident_start(s[at])) {
            std::size_t k = at + 1;
            while (k < len && is_ident_part(s[k])) k++;
            std::u32string word = s.substr(at, k - at);
            at = k;
            if (word == U"per") return std::nullopt;
            std::optional<UnitDim> dim = symbol_dim(word);
            // A bare negative power: `s-1`.
            if (at + 1 < len && s[at] == '-' && is_ascii_digit(s[at + 1])) {
                k = at + 1;
                while (k < len && is_ascii_digit(s[k])) k++;
                double p = read_number(at, k);
                at = k;
                dim = dim_pow(*dim, p);
            }
            return dim;
        }
        return number() ? std::optional<UnitDim>(UnitDim()) : std::nullopt;
    }

    std::optional<UnitDim> term() {
        std::optional<UnitDim> base = factor();
        if (!base) return std::nullopt;
        std::size_t before = at;
        skip();
        if (at >= len || s[at] != '^') at = before;
        if (at < len && s[at] == '^') {
            at++;
            skip();
            std::optional<double> n;
            if (at < len && s[at] == '(') {
                at++;
                n = number();
                skip();
                if (n && at < len && s[at] == '/') {
                    at++;
                    skip();
                    std::optional<double> d = number();
                    if (!d || *d == 0) return std::nullopt;
                    n = *n / *d;
                    skip();
                }
                if (!n || at >= len || s[at] != ')') return std::nullopt;
                at++;
            } else {
                n = number();
            }
            if (!n) return std::nullopt;
            base = dim_pow(*base, *n);
            if (!base) return std::nullopt;
        }
        return base;
    }

    /// Whether the word `per` stands here: the three letters with no more of a word after them.
    bool per_word() const {
        if (!(at + 2 < len && s[at] == 'p' && s[at + 1] == 'e' && s[at + 2] == 'r')) return false;
        if (at + 3 >= len) return true;
        char32_t c = s[at + 3];
        // A letter, a digit or an underscore goes on with the word. Of the characters past
        // ASCII only the two a unit is written with matter: after any other, the text is
        // not a unit whichever way this is answered.
        return !((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || is_ascii_digit(c) || c == '_' || c >= 0x80);
    }

    std::optional<UnitDim> expr() {
        std::optional<UnitDim> out = term();
        if (!out) return std::nullopt;
        while (true) {
            std::size_t save = at;
            skip();
            char32_t ch = peek();
            if (ch == '*' || ch == MIDDLE_DOT) {
                at++;
                std::optional<UnitDim> next = term();
                if (!next) return std::nullopt;
                out = dim_times(*out, *next);
            } else if (ch == '/') {
                at++;
                std::optional<UnitDim> next = term();
                if (!next) return std::nullopt;
                out = dim_over(*out, *next);
            } else if (per_word()) {
                at += 3;
                std::optional<UnitDim> rest = expr();
                if (!rest) return std::nullopt;
                return dim_over(*out, *rest);
            } else if (ch != U'\0' && (is_ident_start(ch) || ch == '(') && save != at) {
                std::optional<UnitDim> next = term();
                if (!next) return std::nullopt;
                out = dim_times(*out, *next);
            } else {
                at = save;
                break;
            }
        }
        return out;
    }
};

const DimPtr& one_dim() {
    static const DimPtr one = std::make_shared<const UnitDim>();
    return one;
}

DimPtr shared(UnitDim d) { return std::make_shared<const UnitDim>(std::move(d)); }
DimPtr shared(std::optional<UnitDim> d) { return d ? shared(std::move(*d)) : nullptr; }

bool among(const char* const* names, std::size_t n, const std::string& name) {
    for (std::size_t i = 0; i < n; i++)
        if (name == names[i]) return true;
    return false;
}
template <std::size_t N>
bool among(const char* const (&names)[N], const std::string& name) { return among(names, N, name); }

const char* const UNIT_PURE[] = {"exp", "log", "log10", "log2", "ln", "sin", "cos", "tan", "asin", "acos", "atan", "sinh",
                                 "cosh", "tanh", "asinh", "acosh", "atanh", "erf", "erfc", "factorial", "binomial"};
const char* const UNIT_SAME[] = {"abs", "fabs", "ceil", "floor", "round", "fix", "min", "max", "mean", "percentile"};
const char* const UNIT_CLOCK[] = {"time", "start_time", "end_time"};
const char* const UNIT_COMPARE[] = {"==", "!=", "<", ">", "<=", ">=", "~=", "&&", "||"};
const char* const AGREE_OPS[] = {"+", "-", "==", "!=", "<", ">", "<=", ">=", "~="};
const char* const AGREE_CALLS[] = {"min", "max", "if", "ifelse"};

std::string clash_note(const DimPtr& l, const DimPtr& r) {
    if (!l || !same_kind(*l, r.get())) return "";
    double f = dim_factor(*l, *r);
    return " \xe2\x80\x94 the same quantity, a factor of " + scale_text(f >= 1 ? f : 1 / f) +
           " apart; only a literal written directly against the other side is converted, so the factor is yours to write in here";
}

/// The one unit several pieces share: none when any is not known; a clash when two differ.
DimPtr agree(const std::vector<DimPtr>& dims, std::size_t from, std::size_t to, const std::string& what) {
    DimPtr out;
    for (std::size_t i = from; i < to && i < dims.size(); i++) {
        const DimPtr& d = dims[i];
        if (!d) return nullptr;
        if (!out || is_one(*out)) {
            out = d;
            continue;
        }
        if (is_one(*d) || dim_equals(*out, d.get())) continue;
        throw UnitClash(what + " do not agree: " + dim_text(*out) + " and " + dim_text(*d));
    }
    return out;
}
DimPtr agree(const std::vector<DimPtr>& dims, const std::string& what) { return agree(dims, 0, dims.size(), what); }

struct UnitWalker {
    const UnitOf& unit_of;
    const DimPtr& time_dim;

    DimPtr walk(const ENode& node) const {
        switch (node.kind) {
            case ENode::Kind::Num: {
                const ENum& n = as_num(node);
                if (n.dim) return n.dim;
                if (!n.unit) return one_dim();
                return parse_unit(std::string_view(*n.unit));
            }
            case ENode::Kind::Ref: return unit_of(as_ref(node).name);
            case ENode::Kind::Unary: return as_unary(node).op == "!" ? one_dim() : walk(*as_unary(node).operand);
            case ENode::Kind::Binary: return binary(as_binary(node));
            case ENode::Kind::Cond: {
                const ECond& c = as_cond(node);
                walk(*c.test);
                DimPtr then = walk(*c.then);
                return agree({then, walk(*c.otherwise)}, "the two results");
            }
            case ENode::Kind::Call: return call(as_call(node));
        }
        return nullptr;
    }

    DimPtr binary(const EBinary& node) const {
        const std::string& op = node.op;
        DimPtr l = walk(*node.left);
        DimPtr r = walk(*node.right);
        if (among(UNIT_COMPARE, op)) {
            if (l && r && !is_one(*l) && !is_one(*r) && !dim_equals(*l, r.get()))
                throw UnitClash(dim_text(*l) + " and " + dim_text(*r) + " cannot be compared" + clash_note(l, r));
            return one_dim();
        }
        if (op == "*" || op == ".*") return (l && r) ? shared(dim_times(*l, *r)) : nullptr;
        if (op == "/" || op == "./") return (l && r) ? shared(dim_over(*l, *r)) : nullptr;
        if (op == "^" || op == ".^") {
            if (!l) return nullptr;
            if (is_one(*l)) return one_dim();
            if (node.right->kind != ENode::Kind::Num) return nullptr;
            return shared(dim_pow(*l, as_num(*node.right).value));
        }
        if (!l || !r) return nullptr;
        if (is_one(*l)) return r;
        if (is_one(*r)) return l;
        if (!dim_equals(*l, r.get()))
            throw UnitClash(dim_text(*l) + " and " + dim_text(*r) + " cannot be " + (op == "-" ? "subtracted" : "added") +
                            clash_note(l, r));
        return l;
    }

    DimPtr call(const ECall& node) const {
        const std::string& name = node.name;
        std::vector<DimPtr> args;
        args.reserve(node.args.size());
        for (const ENodePtr& a : node.args) args.push_back(walk(*a));
        if (among(UNIT_CLOCK, name)) return time_dim;
        if (among(UNIT_PURE, name)) {
            if (!args.empty() && args[0] && !is_one(*args[0]))
                throw UnitClash(name + " needs a plain number, not " + dim_text(*args[0]));
            return one_dim();
        }
        if (name == "sqrt") return (!args.empty() && args[0]) ? shared(dim_pow(*args[0], 0.5)) : nullptr;
        if (name == "power" || name == "pow") {
            if (args.empty() || !args[0]) return nullptr;
            if (is_one(*args[0])) return one_dim();
            if (node.args.size() < 2 || node.args[1]->kind != ENode::Kind::Num) return nullptr;
            return shared(dim_pow(*args[0], as_num(*node.args[1]).value));
        }
        if (name == "if") return agree(args, 1, args.size(), "the two results of if");
        if (name == "rampUp" || name == "rampDown") {
            agree(args, "the argument and the two ends of " + name);
            return one_dim();
        }
        if (name == "smoothUp" || name == "smoothDown") {
            agree(args, 0, 2, "the argument and the half-way point of " + name);
            if (args.size() > 2 && args[2] && !is_one(*args[2]))
                throw UnitClash("the sharpness of " + name + " is a plain number, not " + dim_text(*args[2]));
            return one_dim();
        }
        if (name == "mod" || name == "rem") return args.empty() ? nullptr : args[0];
        if (name == "atan2" || name == "sign" || name == "sgn") return one_dim();
        if (name == "hypot") return agree(args, "the arguments of hypot");
        if (name == "sum") return agree(args, "the arguments of sum");
        if (name == "prod" || name == "product") return nullptr;
        if (among(UNIT_SAME, name)) return agree(args, "the arguments of " + name);
        return nullptr;
    }
};

/// Python's truthiness of what a model file holds: null, false, zero and what is empty are not.
bool py_truthy(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return false;
        case Json::Type::Bool: return v.as_bool();
        case Json::Type::Int: return v.as_int() != 0;
        case Json::Type::Float: return v.as_double() != 0;
        default: return !v.empty();
    }
}

}  // namespace

// --- the algebra ------------------------------------------------------------------------------------------

const long long* UnitDim::power(std::string_view symbol) const {
    for (const auto& p : powers)
        if (p.first == symbol) return &p.second;
    return nullptr;
}

bool is_one(const UnitDim& d) { return d.powers.empty() && d.scale == 1; }

UnitDim dim_times(const UnitDim& a, const UnitDim& b, int sign) {
    UnitDim out;
    out.powers = a.powers;
    for (const auto& [sym, n] : b.powers) {
        auto at = std::find_if(out.powers.begin(), out.powers.end(), [&](const auto& p) { return p.first == sym; });
        // Whole numbers that wrap around, as the other engines' do.
        unsigned long long have = at == out.powers.end() ? 0ULL : static_cast<unsigned long long>(at->second);
        long long next = static_cast<long long>(have + static_cast<unsigned long long>(n) * static_cast<unsigned long long>(static_cast<long long>(sign)));
        if (next == 0) {
            if (at != out.powers.end()) out.powers.erase(at);
        } else if (at != out.powers.end()) {
            at->second = next;
        } else {
            out.powers.emplace_back(sym, next);
        }
    }
    out.scale = sign > 0 ? a.scale * b.scale : a.scale / b.scale;
    return out;
}

UnitDim dim_over(const UnitDim& a, const UnitDim& b) { return dim_times(a, b, -1); }

std::optional<UnitDim> dim_pow(const UnitDim& d, double n) {
    if (n == 0) return UnitDim();
    UnitDim out;
    for (const auto& [sym, e] : d.powers) {
        double next = static_cast<double>(e) * n;
        if (!(std::isfinite(next) && next == std::floor(next))) return std::nullopt;
        if (!(next >= -9223372036854775808.0 && next < 9223372036854775808.0))
            throw UnitPowerError("The power " + js_text(next) + " of '" + sym + "' is past what a whole number holds");
        out.powers.emplace_back(sym, static_cast<long long>(next));
    }
    // Python's float `**`, which is the C library's pow.
    out.scale = cpow(d.scale, n);
    return out;
}

bool same_kind(const UnitDim& a, const UnitDim* b) {
    if (!b || a.powers.size() != b->powers.size()) return false;
    for (const auto& [sym, n] : a.powers) {
        const long long* other = b->power(sym);
        if (!other || *other != n) return false;
    }
    return true;
}

double dim_factor(const UnitDim& a, const UnitDim& b) { return a.scale / b.scale; }

bool dim_equals(const UnitDim& a, const UnitDim* b) { return same_kind(a, b) && std::fabs(dim_factor(a, *b) - 1) < 1e-9; }

std::string to_exponential(double v) {
    if (v == 0) return "0e+0";
    // What the other engines make of a scale that is no number: the letters of its name, laid out as digits.
    if (std::isnan(v)) return "N.aNe+2";
    if (std::isinf(v)) return v < 0 ? "-I.nfe+2" : "I.nfe+2";
    auto [digits, n] = shortest_digits(std::fabs(v));
    int e = n - 1;
    std::string body = digits.size() == 1 ? digits : digits.substr(0, 1) + "." + digits.substr(1);
    return (v < 0 ? "-" : "") + body + "e" + (e >= 0 ? "+" : "-") + std::to_string(std::abs(e));
}

std::string scale_text(double scale) {
    char buf[64];
    std::snprintf(buf, sizeof buf, "%.12g", scale);
    double s = std::strtod(buf, nullptr);
    if (1e-3 <= scale && scale < 1e6) return js_number(s);
    // Zeros at the end of the digits, and the point they leave bare, are dropped: `\.?0+e` becomes `e`.
    std::string text = to_exponential(s);
    std::string out;
    for (std::size_t i = 0; i < text.size();) {
        std::size_t k = i;
        if (text[k] == '.') k++;
        std::size_t zeros = k;
        while (zeros < text.size() && text[zeros] == '0') zeros++;
        if (zeros > k && zeros < text.size() && text[zeros] == 'e') {
            out.push_back('e');
            i = zeros + 1;
        } else {
            out.push_back(text[i++]);
        }
    }
    return out;
}

std::string dim_text(const UnitDim& d) {
    if (is_one(d)) return "unitless";
    std::vector<std::pair<std::string, long long>> up, down;
    for (const auto& p : d.powers) {
        if (p.second > 0) up.push_back(p);
        else if (p.second < 0) down.push_back(p);
    }
    std::sort(up.begin(), up.end());
    std::sort(down.begin(), down.end());
    auto parts = [](const std::vector<std::pair<std::string, long long>>& ps) {
        std::vector<std::string> out;
        for (const auto& [sym, n] : ps) {
            // The size of the power, which wraps around at the very end of the whole numbers as theirs does.
            unsigned long long size = n < 0 ? 0ULL - static_cast<unsigned long long>(n) : static_cast<unsigned long long>(n);
            out.push_back(size == 1 ? sym : sym + "^" + std::to_string(static_cast<long long>(size)));
        }
        return join(out, "*");
    };
    if (up.empty() && down.empty()) return "\xc3\x97" + scale_text(d.scale);
    std::string top = up.empty() ? "1" : parts(up);
    std::string lead = d.scale == 1 ? "" : scale_text(d.scale) + " ";
    if (down.empty()) return lead + top;
    std::string bottom = parts(down);
    return lead + top + "/" + (down.size() > 1 ? "(" + bottom + ")" : bottom);
}

// --- reading a unit ------------------------------------------------------------------------------------

DimPtr parse_unit(std::string_view text) {
    std::u32string src = stripped(chars_of(text));
    if (unit_none(lowercase(text_of(src, 0, src.size())))) return one_dim();
    if (src.size() >= 2 && src.front() == '[' && src.back() == ']') src = stripped(src.substr(1, src.size() - 2));
    if (unit_none(lowercase(text_of(src, 0, src.size())))) return one_dim();
    UnitParser p(src);
    std::optional<UnitDim> value = p.expr();
    p.skip();
    return (value && p.at >= p.len) ? shared(std::move(*value)) : nullptr;
}

DimPtr parse_unit(const Json& text) {
    if (text.is_null()) return parse_unit(std::string_view());
    if (text.is_string()) return parse_unit(std::string_view(text.as_string()));
    // A list or a dictionary is written out by the other engines as no unit reads.
    if (text.is_array() || text.is_object()) return nullptr;
    return parse_unit(std::string_view(py_text(text)));
}

bool same_unit(const Json& a, const Json& b) {
    DimPtr x = parse_unit(a), y = parse_unit(b);
    return x && y && dim_equals(*x, y.get());
}

// --- the unit of an equation ------------------------------------------------------------------------------

EquationUnit equation_unit(const ENode& ast, const UnitOf& unit_of, const DimPtr& time_dim) {
    try {
        return {UnitWalker{unit_of, time_dim}.walk(ast), std::nullopt};
    } catch (const UnitClash& e) {
        return {nullptr, std::string(e.what())};
    }
}

bool has_unit_literal(const ENode& node) {
    std::vector<const ENode*> stack = {&node};
    while (!stack.empty()) {
        const ENode* n = stack.back();
        stack.pop_back();
        switch (n->kind) {
            case ENode::Kind::Num:
                if (as_num(*n).unit) return true;
                break;
            case ENode::Kind::Call:
                for (const ENodePtr& a : as_call(*n).args) stack.push_back(a.get());
                break;
            case ENode::Kind::Unary: stack.push_back(as_unary(*n).operand.get()); break;
            case ENode::Kind::Binary:
                stack.push_back(as_binary(*n).left.get());
                stack.push_back(as_binary(*n).right.get());
                break;
            case ENode::Kind::Cond:
                stack.push_back(as_cond(*n).test.get());
                stack.push_back(as_cond(*n).then.get());
                stack.push_back(as_cond(*n).otherwise.get());
                break;
            default: break;
        }
    }
    return false;
}

// --- literals scaled ----------------------------------------------------------------------------------------

namespace {

struct LiteralScaler {
    const UnitOf& unit_of;
    const DimPtr& time_dim;
    ScaledLiterals done;

    DimPtr dim_of(const ENode& node) const {
        try {
            return equation_unit(node, unit_of, time_dim).dim;
        } catch (const std::exception&) {
            return nullptr;   // the unit of this piece is simply not known
        }
    }

    static bool literal(const ENode& n) { return n.kind == ENode::Kind::Num && as_num(n).unit && !as_num(n).dim; }

    void against(ENum& lit, const ENode* other) {
        DimPtr want = other ? dim_of(*other) : nullptr;
        DimPtr here = dim_of(lit);
        if (!here || is_one(*here)) return;
        if (!want) {
            done.unconverted.push_back({lit.value, *lit.unit});
            return;
        }
        if (!same_kind(*want, here.get()) || dim_equals(*want, here.get())) return;
        double f = dim_factor(*here, *want);
        done.converted.push_back({lit.value, dim_text(*here), dim_text(*want), lit.value * f});
        lit.value *= f;
        lit.dim = want;
    }

    void reconcile(const std::vector<ENode*>& nodes) {
        std::vector<ENode*> lits;
        for (ENode* n : nodes)
            if (literal(*n)) lits.push_back(n);
        if (lits.empty()) return;
        const ENode* anchor = nullptr;
        for (ENode* n : nodes) {
            if (!literal(*n) && dim_of(*n)) {
                anchor = n;
                break;
            }
        }
        if (!anchor) {
            for (ENode* n : nodes) {
                if (n != lits[0]) {
                    anchor = n;
                    break;
                }
            }
        }
        for (ENode* lit : lits) {
            if (lit == anchor) continue;
            against(static_cast<ENum&>(*lit), anchor);
        }
    }

    void walk(ENode& node) {
        switch (node.kind) {
            case ENode::Kind::Binary: {
                EBinary& b = static_cast<EBinary&>(node);
                walk(*b.left);
                walk(*b.right);
                if (among(AGREE_OPS, b.op)) reconcile({b.left.get(), b.right.get()});
                break;
            }
            case ENode::Kind::Unary: walk(*static_cast<EUnary&>(node).operand); break;
            case ENode::Kind::Cond: {
                ECond& c = static_cast<ECond&>(node);
                walk(*c.test);
                walk(*c.then);
                walk(*c.otherwise);
                reconcile({c.then.get(), c.otherwise.get()});
                break;
            }
            case ENode::Kind::Call: {
                ECall& c = static_cast<ECall&>(node);
                for (const ENodePtr& a : c.args) walk(*a);
                if (among(AGREE_CALLS, c.name)) {
                    std::vector<ENode*> args;
                    bool chosen = c.name == "if" || c.name == "ifelse";   // the first argument is the test
                    for (std::size_t i = chosen ? 1 : 0; i < c.args.size(); i++) args.push_back(c.args[i].get());
                    reconcile(args);
                }
                break;
            }
            default: break;
        }
    }
};

}  // namespace

ScaledLiterals scale_literals(const ENodePtr& ast, const UnitOf& unit_of, const DimPtr& time_dim) {
    if (!ast || !has_unit_literal(*ast)) return {};
    LiteralScaler scaler{unit_of, time_dim, {}};
    scaler.walk(*ast);
    return std::move(scaler.done);
}

void scale_model_literals(const ENodePtr& ast, const std::unordered_map<std::string, Json>& unit_blocks,
                          const Json& simulation, const std::string& system) {
    if (!ast || !has_unit_literal(*ast)) return;
    const Json& tu = simulation.get("time_unit");
    DimPtr time_dim = py_truthy(tu) ? parse_unit(tu) : parse_unit(std::string_view("year"));
    auto known = [&](const std::string& n) { return unit_blocks.count(n) != 0; };
    UnitOf unit_of = [&](const std::string& written) -> DimPtr {
        std::optional<std::string> q = resolve_reference(written, system, known);
        if (!q || q->empty()) return nullptr;
        const Json& text = unit_blocks.at(*q).get("unit");
        return py_truthy(text) ? parse_unit(text) : nullptr;
    };
    scale_literals(ast, unit_of, time_dim);
}

}  // namespace kompartment
