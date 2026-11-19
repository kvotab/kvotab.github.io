#include "util/json.hpp"

#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cstring>

#include "util/jsnum.hpp"

namespace kompartment {

const Json Json::null_value{};

JsonError::JsonError(const std::string& what, std::size_t at)
    : std::runtime_error(what + " (at byte " + std::to_string(at) + ")"), position(at) {}

// --- Json ------------------------------------------------------------------------------------------

Json::Json(const char* s) : type_(Type::String), s_(std::make_shared<std::string>(s)) { v_.i = 0; }
Json::Json(std::string s) : type_(Type::String), s_(std::make_shared<std::string>(std::move(s))) { v_.i = 0; }
Json::Json(std::string_view s) : type_(Type::String), s_(std::make_shared<std::string>(s)) { v_.i = 0; }
Json::Json(JArray a) : type_(Type::Array), a_(std::make_shared<JArray>(std::move(a))) { v_.i = 0; }
Json::Json(JObject o) : type_(Type::Object), o_(std::make_shared<JObject>(std::move(o))) { v_.i = 0; }

Json Json::array() { return Json(JArray{}); }
Json Json::array(std::initializer_list<Json> items) { return Json(JArray(items)); }
Json Json::array(const std::vector<std::string>& items) {
    JArray a;
    a.reserve(items.size());
    for (const auto& s : items) a.emplace_back(s);
    return Json(std::move(a));
}
Json Json::array(const std::vector<double>& items) {
    JArray a;
    a.reserve(items.size());
    for (double x : items) a.emplace_back(x);
    return Json(std::move(a));
}
Json Json::object() { return Json(JObject{}); }
Json Json::object(std::initializer_list<std::pair<std::string, Json>> items) { return Json(JObject(items)); }

static const char* type_name(Json::Type t) {
    switch (t) {
        case Json::Type::Null: return "null";
        case Json::Type::Bool: return "a boolean";
        case Json::Type::Int:
        case Json::Type::Float: return "a number";
        case Json::Type::String: return "text";
        case Json::Type::Array: return "a list";
        case Json::Type::Object: return "a dictionary";
    }
    return "?";
}

[[noreturn]] static void wrong(const char* wanted, Json::Type got) {
    throw JsonTypeError(std::string("Expected ") + wanted + ", found " + type_name(got));
}

bool Json::as_bool() const {
    if (type_ != Type::Bool) wrong("a boolean", type_);
    return v_.b;
}
std::int64_t Json::as_int() const {
    if (type_ == Type::Int) return v_.i;
    if (type_ == Type::Float && v_.d == std::floor(v_.d) && std::fabs(v_.d) < 9.2e18) return static_cast<std::int64_t>(v_.d);
    wrong("a whole number", type_);
}
double Json::as_double() const {
    if (type_ == Type::Float) return v_.d;
    if (type_ == Type::Int) return static_cast<double>(v_.i);
    wrong("a number", type_);
}
const std::string& Json::as_string() const {
    if (type_ != Type::String) wrong("text", type_);
    return *s_;
}
JArray& Json::arr() {
    if (type_ != Type::Array) wrong("a list", type_);
    return *a_;
}
const JArray& Json::arr() const {
    if (type_ != Type::Array) wrong("a list", type_);
    return *a_;
}
JObject& Json::obj() {
    if (type_ != Type::Object) wrong("a dictionary", type_);
    return *o_;
}
const JObject& Json::obj() const {
    if (type_ != Type::Object) wrong("a dictionary", type_);
    return *o_;
}

const Json& Json::get(std::string_view key) const noexcept {
    if (type_ != Type::Object) return null_value;
    const Json* v = o_->find(key);
    return v ? *v : null_value;
}
Json Json::get(std::string_view key, const Json& fallback) const {
    if (type_ != Type::Object) return fallback;
    const Json* v = o_->find(key);
    return v ? *v : fallback;
}
bool Json::has(std::string_view key) const noexcept { return type_ == Type::Object && o_->find(key) != nullptr; }
void Json::set(std::string_view key, Json value) { obj().set(key, std::move(value)); }
bool Json::erase(std::string_view key) { return obj().erase(key); }
Json& Json::operator[](std::string_view key) { return obj()[key]; }

std::size_t Json::size() const noexcept {
    switch (type_) {
        case Type::Array: return a_->size();
        case Type::Object: return o_->size();
        case Type::String: return s_->size();
        default: return 0;
    }
}
Json& Json::operator[](std::size_t i) { return arr().at(i); }
const Json& Json::operator[](std::size_t i) const { return arr().at(i); }
void Json::push(Json value) { arr().push_back(std::move(value)); }

Json Json::copy() const {
    if (type_ == Type::Array) {
        JArray out;
        out.reserve(a_->size());
        for (const Json& x : *a_) out.push_back(x.copy());
        return Json(std::move(out));
    }
    if (type_ == Type::Object) {
        JObject out;
        out.reserve(o_->size());
        for (const auto& [k, x] : *o_) out.set(k, x.copy());
        return Json(std::move(out));
    }
    return *this;   // leaves cannot change: shared
}

Json Json::shallow() const {
    if (type_ == Type::Array) return Json(JArray(*a_));
    if (type_ == Type::Object) {
        JObject out;
        out.reserve(o_->size());
        for (const auto& [k, x] : *o_) out.set(k, x);
        return Json(std::move(out));
    }
    return *this;
}

bool Json::same(const Json& other) const noexcept {
    if (type_ != other.type_) return false;
    switch (type_) {
        case Type::Array: return a_ == other.a_;
        case Type::Object: return o_ == other.o_;
        default: return *this == other;
    }
}

bool operator==(const Json& a, const Json& b) {
    using T = Json::Type;
    if (a.is_number() && b.is_number()) {
        if (a.type_ == T::Int && b.type_ == T::Int) return a.v_.i == b.v_.i;
        return a.as_double() == b.as_double();
    }
    if (a.type_ != b.type_) return false;
    switch (a.type_) {
        case T::Null: return true;
        case T::Bool: return a.v_.b == b.v_.b;
        case T::String: return *a.s_ == *b.s_;
        case T::Array: {
            if (a.a_ == b.a_) return true;
            if (a.a_->size() != b.a_->size()) return false;
            for (std::size_t i = 0; i < a.a_->size(); i++)
                if (!((*a.a_)[i] == (*b.a_)[i])) return false;
            return true;
        }
        case T::Object: {
            if (a.o_ == b.o_) return true;
            if (a.o_->size() != b.o_->size()) return false;
            for (const auto& [k, x] : *a.o_) {
                const Json* y = b.o_->find(k);
                if (!y || !(x == *y)) return false;
            }
            return true;
        }
        default: return false;
    }
}

// --- JObject ---------------------------------------------------------------------------------------

namespace {
constexpr std::size_t kScanBelow = 12;   // fewer keys than this are found by looking through them
}

JObject::JObject(std::initializer_list<Item> items) {
    items_.reserve(items.size());
    for (const auto& it : items) set(it.first, it.second);
}

void JObject::index_all() {
    index_.clear();
    index_.reserve(items_.size() * 2);
    for (std::size_t i = 0; i < items_.size(); i++) index_.emplace(items_[i].first, i);
    indexed_ = true;
}

std::ptrdiff_t JObject::position(std::string_view key) const noexcept {
    if (!indexed_) {
        for (std::size_t i = 0; i < items_.size(); i++)
            if (items_[i].first == key) return static_cast<std::ptrdiff_t>(i);
        return -1;
    }
    auto it = index_.find(std::string(key));
    return it == index_.end() ? -1 : static_cast<std::ptrdiff_t>(it->second);
}

Json* JObject::find(std::string_view key) noexcept {
    auto p = position(key);
    return p < 0 ? nullptr : &items_[static_cast<std::size_t>(p)].second;
}
const Json* JObject::find(std::string_view key) const noexcept {
    auto p = position(key);
    return p < 0 ? nullptr : &items_[static_cast<std::size_t>(p)].second;
}
const Json& JObject::at(std::string_view key) const {
    const Json* v = find(key);
    if (!v) throw std::out_of_range("No key '" + std::string(key) + "'");
    return *v;
}
Json& JObject::at(std::string_view key) {
    Json* v = find(key);
    if (!v) throw std::out_of_range("No key '" + std::string(key) + "'");
    return *v;
}
Json& JObject::operator[](std::string_view key) {
    if (Json* v = find(key)) return *v;
    items_.emplace_back(std::string(key), Json());
    if (indexed_) index_.emplace(items_.back().first, items_.size() - 1);
    else if (items_.size() >= kScanBelow) index_all();
    return items_.back().second;
}
void JObject::set(std::string_view key, Json value) { (*this)[key] = std::move(value); }
bool JObject::erase(std::string_view key) {
    auto p = position(key);
    if (p < 0) return false;
    items_.erase(items_.begin() + p);
    indexed_ = false;
    index_.clear();
    if (items_.size() >= kScanBelow) index_all();
    return true;
}
void JObject::clear() {
    items_.clear();
    index_.clear();
    indexed_ = false;
}
std::vector<std::string> JObject::keys() const {
    std::vector<std::string> out;
    out.reserve(items_.size());
    for (const auto& it : items_) out.push_back(it.first);
    return out;
}

// --- reading ---------------------------------------------------------------------------------------

namespace {

struct Reader {
    const unsigned char* s;
    std::size_t i;   // from 0
    std::size_t n;

    [[noreturn]] void fail(const std::string& what) const { throw JsonError(what, i + 1); }

    void skip_ws() {
        while (i < n) {
            unsigned char c = s[i];
            if (!(c == 0x20 || c == 0x0a || c == 0x0d || c == 0x09)) break;
            i++;
        }
    }

    void expect_word(const char* w) {
        std::size_t m = std::strlen(w);
        if (i + m > n || std::memcmp(s + i, w, m) != 0) fail("Unexpected text in JSON");
        i += m;
    }

    unsigned hex4(std::size_t at) {
        if (at + 4 > n) fail("A \\u escape is cut short");
        unsigned v = 0;
        for (int k = 0; k < 4; k++) {
            unsigned char c = s[at + k];
            unsigned d;
            if (c >= '0' && c <= '9') d = c - '0';
            else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') d = c - 'A' + 10;
            else fail("A \\u escape needs four hex digits");
            v = v * 16 + d;
        }
        return v;
    }

    static void put_utf8(std::string& out, unsigned u) {
        if (u < 0x80) out.push_back(static_cast<char>(u));
        else if (u < 0x800) {
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

    std::string read_string() {
        std::size_t start = ++i;
        // The common case: no escapes, copied in one go.
        while (i < n) {
            unsigned char c = s[i];
            if (c == '"') {
                std::string out(reinterpret_cast<const char*>(s + start), i - start);
                i++;
                return out;
            }
            if (c == '\\') break;
            if (c < 0x20) fail("A control character inside a JSON string");
            i++;
        }
        std::string out(reinterpret_cast<const char*>(s + start), i - start);
        while (i < n) {
            unsigned char c = s[i];
            if (c == '"') {
                i++;
                return out;
            }
            if (c == '\\') {
                if (i + 1 >= n) break;
                unsigned char e = s[i + 1];
                switch (e) {
                    case '"': case '\\': case '/': out.push_back(static_cast<char>(e)); i += 2; break;
                    case 'b': out.push_back('\b'); i += 2; break;
                    case 'f': out.push_back('\f'); i += 2; break;
                    case 'n': out.push_back('\n'); i += 2; break;
                    case 'r': out.push_back('\r'); i += 2; break;
                    case 't': out.push_back('\t'); i += 2; break;
                    case 'u': {
                        unsigned u = hex4(i + 2);
                        i += 6;
                        if (u >= 0xd800 && u <= 0xdbff && i + 6 <= n && s[i] == '\\' && s[i + 1] == 'u') {
                            unsigned lo = hex4(i + 2);
                            if (lo >= 0xdc00 && lo <= 0xdfff) {
                                u = 0x10000 + ((u - 0xd800) << 10) + (lo - 0xdc00);
                                i += 6;
                            }
                        }
                        // A lone surrogate is kept as the replacement character.
                        put_utf8(out, (u >= 0xd800 && u <= 0xdfff) ? 0xfffd : u);
                        break;
                    }
                    default: fail("An unknown escape in a JSON string");
                }
            } else {
                if (c < 0x20) fail("A control character inside a JSON string");
                out.push_back(static_cast<char>(c));
                i++;
            }
        }
        fail("A JSON string is not closed");
    }

    Json read_number() {
        std::size_t start = i;
        if (i < n && s[i] == '-') i++;
        bool integer = true;
        while (i < n) {
            unsigned char c = s[i];
            if (c >= '0' && c <= '9') i++;
            else if (c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-') {
                integer = false;
                i++;
            } else break;
        }
        std::string text(reinterpret_cast<const char*>(s + start), i - start);
        if (integer && !text.empty() && text != "-") {
            errno = 0;
            char* end = nullptr;
            long long v = std::strtoll(text.c_str(), &end, 10);
            if (errno == 0 && end == text.c_str() + text.size()) return Json(static_cast<long long>(v));
        }
        // The grammar of a JSON number, then the double nearest to it; past the range of
        // a double JavaScript reads Infinity (or 0), as strtod does.
        std::size_t k = 0, m = text.size();
        auto digits = [&]() {
            std::size_t from = k;
            while (k < m && text[k] >= '0' && text[k] <= '9') k++;
            return k - from;
        };
        bool ok = true;
        if (k < m && text[k] == '-') k++;
        if (k < m && text[k] == '0') k++;
        else if (digits() == 0) ok = false;
        if (ok && k < m && text[k] == '.') {
            k++;
            if (digits() == 0) ok = false;
        }
        if (ok && k < m && (text[k] == 'e' || text[k] == 'E')) {
            k++;
            if (k < m && (text[k] == '+' || text[k] == '-')) k++;
            if (digits() == 0) ok = false;
        }
        if (!ok || k != m) {
            i = start;
            fail("'" + text + "' is not a JSON number");
        }
        return Json(std::strtod(text.c_str(), nullptr));
    }

    Json read_value(int depth) {
        if (depth > 10000) fail("JSON nested too deeply");
        skip_ws();
        if (i >= n) fail("Unexpected end of JSON");
        unsigned char c = s[i];
        if (c == '{') return read_object(depth);
        if (c == '[') return read_array(depth);
        if (c == '"') return Json(read_string());
        if (c == 't') { expect_word("true"); return Json(true); }
        if (c == 'f') { expect_word("false"); return Json(false); }
        if (c == 'n') { expect_word("null"); return Json(); }
        if (c == '-' || (c >= '0' && c <= '9')) return read_number();
        fail(std::string("Unexpected character '") + static_cast<char>(c) + "' in JSON");
    }

    Json read_object(int depth) {
        i++;
        JObject out;
        skip_ws();
        if (i < n && s[i] == '}') {
            i++;
            return Json(std::move(out));
        }
        for (;;) {
            skip_ws();
            if (!(i < n && s[i] == '"')) fail("Expected a key in a JSON object");
            std::string key = read_string();
            skip_ws();
            if (!(i < n && s[i] == ':')) fail("Expected ':' in a JSON object");
            i++;
            out.set(key, read_value(depth + 1));
            skip_ws();
            if (i >= n) fail("Unexpected end of JSON in an object");
            unsigned char c = s[i++];
            if (c == '}') return Json(std::move(out));
            if (c != ',') { i--; fail("Expected ',' or '}' in a JSON object"); }
        }
    }

    Json read_array(int depth) {
        i++;
        JArray out;
        skip_ws();
        if (i < n && s[i] == ']') {
            i++;
            return Json(std::move(out));
        }
        for (;;) {
            out.push_back(read_value(depth + 1));
            skip_ws();
            if (i >= n) fail("Unexpected end of JSON in an array");
            unsigned char c = s[i++];
            if (c == ']') return Json(std::move(out));
            if (c != ',') { i--; fail("Expected ',' or ']' in a JSON array"); }
        }
    }
};

}  // namespace

Json parse_json(std::string_view text) {
    Reader r{reinterpret_cast<const unsigned char*>(text.data()), 0, text.size()};
    if (r.n >= 3 && r.s[0] == 0xef && r.s[1] == 0xbb && r.s[2] == 0xbf) r.i = 3;
    Json v = r.read_value(0);
    r.skip_ws();
    if (r.i < r.n) r.fail("Unexpected text after the JSON value");
    return v;
}

// --- writing ---------------------------------------------------------------------------------------

namespace {

void write_string(std::string& out, const std::string& s) {
    out.push_back('"');
    for (unsigned char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            default:
                if (c < 0x20) {
                    static const char* hex = "0123456789abcdef";
                    out += "\\u00";
                    out.push_back(hex[c >> 4]);
                    out.push_back(hex[c & 15]);
                } else {
                    out.push_back(static_cast<char>(c));
                }
        }
    }
    out.push_back('"');
}

void write_value(std::string& out, const Json& v, int depth, int indent) {
    switch (v.type()) {
        case Json::Type::Null: out += "null"; return;
        case Json::Type::Bool: out += v.as_bool() ? "true" : "false"; return;
        case Json::Type::Int: out += std::to_string(v.as_int()); return;
        case Json::Type::Float: out += js_number(v.as_double()); return;
        case Json::Type::String: write_string(out, v.as_string()); return;
        case Json::Type::Object: {
            const JObject& o = v.obj();
            if (o.empty()) { out += "{}"; return; }
            out.push_back('{');
            bool first = true;
            for (const auto& [k, x] : o) {
                if (!first) out.push_back(',');
                first = false;
                if (indent > 0) {
                    out.push_back('\n');
                    out.append(static_cast<std::size_t>(indent * (depth + 1)), ' ');
                }
                write_string(out, k);
                out += indent > 0 ? ": " : ":";
                write_value(out, x, depth + 1, indent);
            }
            if (indent > 0) {
                out.push_back('\n');
                out.append(static_cast<std::size_t>(indent * depth), ' ');
            }
            out.push_back('}');
            return;
        }
        case Json::Type::Array: {
            const JArray& a = v.arr();
            if (a.empty()) { out += "[]"; return; }
            out.push_back('[');
            bool first = true;
            for (const Json& x : a) {
                if (!first) out.push_back(',');
                first = false;
                if (indent > 0) {
                    out.push_back('\n');
                    out.append(static_cast<std::size_t>(indent * (depth + 1)), ' ');
                }
                write_value(out, x, depth + 1, indent);
            }
            if (indent > 0) {
                out.push_back('\n');
                out.append(static_cast<std::size_t>(indent * depth), ' ');
            }
            out.push_back(']');
            return;
        }
    }
}

}  // namespace

std::string json_text(const Json& value, int indent) {
    std::string out;
    write_value(out, value, 0, indent);
    return out;
}

bool js_truthy(const Json& v) noexcept {
    switch (v.type()) {
        case Json::Type::Null: return false;
        case Json::Type::Bool: return v.as_bool();
        case Json::Type::Int: return v.as_int() != 0;
        case Json::Type::Float: { double d = v.as_double(); return !(d == 0 || std::isnan(d)); }
        case Json::Type::String: return !v.as_string().empty();
        default: return true;
    }
}

}  // namespace kompartment
