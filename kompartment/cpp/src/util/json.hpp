// JSON values as a model file holds them.
//
// A model is JSON written by JavaScript, and the engine works on it as the
// other engines do: objects are dictionaries that keep the file's key order,
// lists and dictionaries are shared when a value is copied (as they are in
// JavaScript, Python and Julia -- `copy()` makes a tree of its own), and a
// number written without a fraction or an exponent is an integer where it
// fits, every other number the double JavaScript reads it as.

#pragma once

#include <cstdint>
#include <initializer_list>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace kompartment {

class Json;
class JObject;
using JArray = std::vector<Json>;

/// What the reader says when the text is not JSON; `position` is the byte, from 1.
struct JsonError : std::runtime_error {
    std::size_t position;
    JsonError(const std::string& what, std::size_t at);
};

/// A value read where another kind was expected.
struct JsonTypeError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

class Json {
public:
    enum class Type : std::uint8_t { Null, Bool, Int, Float, String, Array, Object };

    Json() noexcept : type_(Type::Null) { v_.i = 0; }
    Json(std::nullptr_t) noexcept : Json() {}
    Json(bool b) noexcept : type_(Type::Bool) { v_.b = b; }
    Json(int i) noexcept : type_(Type::Int) { v_.i = i; }
    Json(long i) noexcept : type_(Type::Int) { v_.i = i; }
    Json(long long i) noexcept : type_(Type::Int) { v_.i = i; }
    Json(unsigned long i) noexcept : type_(Type::Int) { v_.i = static_cast<std::int64_t>(i); }
    Json(double d) noexcept : type_(Type::Float) { v_.d = d; }
    Json(const char* s);
    Json(std::string s);
    Json(std::string_view s);
    Json(JArray a);
    Json(JObject o);
    Json(std::initializer_list<Json> list) = delete;   // say Json::array({...})

    static Json array();
    static Json array(std::initializer_list<Json> items);
    static Json array(const std::vector<std::string>& items);
    static Json array(const std::vector<double>& items);
    static Json object();
    static Json object(std::initializer_list<std::pair<std::string, Json>> items);

    Type type() const noexcept { return type_; }
    bool is_null() const noexcept { return type_ == Type::Null; }
    bool is_bool() const noexcept { return type_ == Type::Bool; }
    bool is_int() const noexcept { return type_ == Type::Int; }
    bool is_float() const noexcept { return type_ == Type::Float; }
    /// A number, as Julia's `v isa Real && !(v isa Bool)`.
    bool is_number() const noexcept { return type_ == Type::Int || type_ == Type::Float; }
    bool is_string() const noexcept { return type_ == Type::String; }
    bool is_array() const noexcept { return type_ == Type::Array; }
    bool is_object() const noexcept { return type_ == Type::Object; }

    bool as_bool() const;
    std::int64_t as_int() const;
    /// The number as a double (an integer converted).
    double as_double() const;
    const std::string& as_string() const;
    JArray& arr();
    const JArray& arr() const;
    JObject& obj();
    const JObject& obj() const;

    // --- a dictionary's values ---------------------------------------------------------------

    /// `d[key]`, or null when this is not a dictionary or has no such key (Julia's `jget`).
    const Json& get(std::string_view key) const noexcept;
    /// `d[key]`, or `fallback` when this is not a dictionary or has no such key.
    Json get(std::string_view key, const Json& fallback) const;
    bool has(std::string_view key) const noexcept;
    /// Sets `d[key]`; a new key goes last.
    void set(std::string_view key, Json value);
    /// Removes a key; whether it was there.
    bool erase(std::string_view key);
    /// `d[key]` for writing: made null, last, when absent. Throws when this is not a dictionary.
    Json& operator[](std::string_view key);
    Json& operator[](const char* key) { return (*this)[std::string_view(key)]; }
    Json& operator[](const std::string& key) { return (*this)[std::string_view(key)]; }

    // --- a list's values ----------------------------------------------------------------------

    /// The length of a list, the number of keys of a dictionary, the bytes of a string; 0 otherwise.
    std::size_t size() const noexcept;
    bool empty() const noexcept { return size() == 0; }
    Json& operator[](std::size_t i);
    const Json& operator[](std::size_t i) const;
    Json& operator[](int i) { return (*this)[static_cast<std::size_t>(i)]; }
    const Json& operator[](int i) const { return (*this)[static_cast<std::size_t>(i)]; }
    void push(Json value);

    /// A tree of its own: every dictionary and list copied (Julia's `jcopy`).
    Json copy() const;
    /// A list or dictionary of its own holding the same values (what they hold is shared).
    Json shallow() const;
    /// Whether two values are the same thing: the same list or dictionary, or equal leaves.
    bool same(const Json& other) const noexcept;

    /// Equal by content: numbers by value (1 == 1.0), dictionaries whatever their key order.
    friend bool operator==(const Json& a, const Json& b);
    friend bool operator!=(const Json& a, const Json& b) { return !(a == b); }
    bool operator==(const char* s) const { return type_ == Type::String && *s_ == s; }
    bool operator==(std::string_view s) const { return type_ == Type::String && *s_ == s; }
    bool operator==(const std::string& s) const { return type_ == Type::String && *s_ == s; }

    static const Json null_value;

private:
    Type type_;
    union {
        bool b;
        std::int64_t i;
        double d;
    } v_;
    std::shared_ptr<std::string> s_;
    std::shared_ptr<JArray> a_;
    std::shared_ptr<JObject> o_;
};

/// A dictionary that keeps the order its keys were set in.
class JObject {
public:
    using Item = std::pair<std::string, Json>;
    using iterator = std::vector<Item>::iterator;
    using const_iterator = std::vector<Item>::const_iterator;

    JObject() = default;
    JObject(std::initializer_list<Item> items);

    std::size_t size() const noexcept { return items_.size(); }
    bool empty() const noexcept { return items_.empty(); }
    iterator begin() noexcept { return items_.begin(); }
    iterator end() noexcept { return items_.end(); }
    const_iterator begin() const noexcept { return items_.begin(); }
    const_iterator end() const noexcept { return items_.end(); }
    const std::vector<Item>& items() const noexcept { return items_; }

    Json* find(std::string_view key) noexcept;
    const Json* find(std::string_view key) const noexcept;
    bool has(std::string_view key) const noexcept { return find(key) != nullptr; }
    /// The value at a key that is there; throws otherwise.
    const Json& at(std::string_view key) const;
    Json& at(std::string_view key);
    /// The value at a key, made null (last) when absent.
    Json& operator[](std::string_view key);
    void set(std::string_view key, Json value);
    bool erase(std::string_view key);
    void clear();
    void reserve(std::size_t n) { items_.reserve(n); }
    std::vector<std::string> keys() const;

private:
    std::ptrdiff_t position(std::string_view key) const noexcept;
    void index_all();

    std::vector<Item> items_;
    // Past a handful of keys a lookup goes through a table, kept up as keys are set and
    // erased: a lookup never writes, so threads may share a dictionary they only read.
    std::unordered_map<std::string, std::size_t> index_;
    bool indexed_ = false;
};

/// JSON text as values. A byte-order mark is not part of the text.
Json parse_json(std::string_view text);

/// A value as JSON, formatted as `JSON.stringify(value, null, indent)`: numbers as
/// JavaScript writes them (what is not finite as `null`), keys in the dictionary's order.
std::string json_text(const Json& value, int indent = 2);

/// Whether a raw value is truthy as JavaScript reads one (`!!v`).
bool js_truthy(const Json& v) noexcept;

}  // namespace kompartment
