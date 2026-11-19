#include "importers/eco.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <deque>
#include <fstream>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <unordered_map>
#include <unordered_set>

#include "importers/eco_pdf.hpp"
#include "importers/eco_text.hpp"
#include "importers/eco_zip.hpp"
#include "importers/xml.hpp"
#include "lang/functions.hpp"
#include "model/decay.hpp"
#include "model/indexlists.hpp"
#include "model/keys.hpp"
#include "model/names.hpp"
#include "model/simulation.hpp"
#include "util/jsnum.hpp"

namespace kompartment::eco {

namespace {

using OptStr = std::optional<std::string>;

// --- small helpers ---------------------------------------------------------------------------

// A dictionary that keeps the order its keys were first set in (Julia's OrderedDict).
template <class V>
struct OrderedMap {
    std::vector<std::pair<std::string, V>> items;
    std::unordered_map<std::string, std::size_t> at;

    V& operator[](const std::string& k) {
        auto it = at.find(k);
        if (it != at.end()) return items[it->second].second;
        at.emplace(k, items.size());
        items.emplace_back(k, V{});
        return items.back().second;
    }
    const V* find(const std::string& k) const {
        auto it = at.find(k);
        return it == at.end() ? nullptr : &items[it->second].second;
    }
    bool has(const std::string& k) const { return at.count(k) != 0; }
    bool empty() const { return items.empty(); }
    std::size_t size() const { return items.size(); }
};

const JArray& empty_list() {
    static const JArray none;
    return none;
}

// `project.get(key) or []`.
const JArray& list_of(const Json& d, std::string_view key) {
    const Json& v = d.get(key);
    return v.is_array() ? v.arr() : empty_list();
}

// Python's truthiness, for what the importer tests that way.
bool truthy(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return false;
        case Json::Type::Bool: return v.as_bool();
        case Json::Type::Int: return v.as_int() != 0;
        case Json::Type::Float: return v.as_double() != 0;   // NaN is true
        case Json::Type::String: return !v.as_string().empty();
        case Json::Type::Array: return !v.arr().empty();
        case Json::Type::Object: return !v.obj().empty();
    }
    return true;
}
bool truthy(const OptStr& s) { return s && !s->empty(); }

// What `"$(x)"` makes of a value the importer interpolates: text as it is.
std::string str(const Json& v) { return v.is_string() ? v.as_string() : js_string(v); }

Json J(const OptStr& s) { return s ? Json(*s) : Json(); }

bool is_false(const Json& v) { return v.is_bool() && !v.as_bool(); }

std::string join(const std::vector<std::string>& parts, std::string_view sep) {
    std::string out;
    for (std::size_t k = 0; k < parts.size(); k++) {
        if (k) out += sep;
        out += parts[k];
    }
    return out;
}

std::vector<std::string> first_n(const std::vector<std::string>& v, std::size_t n) {
    return std::vector<std::string>(v.begin(), v.begin() + static_cast<std::ptrdiff_t>(std::min(n, v.size())));
}

std::vector<std::string> split_on(std::string_view s, char sep) {
    std::vector<std::string> out;
    std::size_t a = 0;
    while (true) {
        const std::size_t b = s.find(sep, a);
        if (b == std::string_view::npos) {
            out.emplace_back(s.substr(a));
            return out;
        }
        out.emplace_back(s.substr(a, b - a));
        a = b + 1;
    }
}

bool contains(const std::vector<std::string>& v, const std::string& x) { return std::find(v.begin(), v.end(), x) != v.end(); }

std::string itos(long long n) { return std::to_string(n); }

// `_PATH_SEPARATOR.split(name)[-1]`: the part after the last `/` or `\`.
std::string last_part(std::string_view name) {
    const std::size_t k = name.find_last_of("/\\");
    return std::string(k == std::string_view::npos ? name : name.substr(k + 1));
}

// `re.search('<tag[<JS space>>]', text)`: the tag's name followed by white space or `>`.
bool has_tag(const std::string& text, std::string_view tag) {
    const std::size_t n = text.size();
    std::size_t from = 0;
    while (true) {
        const std::size_t r = text.find(tag, from);
        if (r == std::string::npos) return false;
        const std::size_t after = r + tag.size();
        if (after < n && (text[after] == '>' || js_space_bytes(text, after, n) > 0)) return true;
        from = r + 1;
    }
}

// `{system}.{name}` when the block has a sub-system, its name otherwise.
std::string qualified(const Json& block) {
    const Json& system = block.get("system");
    const Json& name = block.get("name");
    return truthy(system) ? str(system) + "." + str(name) : str(name);
}

// `obj` without its empty strings, missing values and empty lists.
using Pairs = std::vector<std::pair<std::string, Json>>;
Json trim_empty(const Pairs& pairs) {
    Json out = Json::object();
    for (const auto& [k, v] : pairs) {
        if (v.is_null() || (v.is_string() && v.as_string().empty()) || (v.is_array() && v.arr().empty())) continue;
        out.set(k, v);
    }
    return out;
}

// `a, b and c`.
std::string list_words(const std::vector<std::string>& parts) {
    if (parts.size() <= 1) return join(parts, "");
    return join(std::vector<std::string>(parts.begin(), parts.end() - 1), ", ") + " and " + parts.back();
}

bool looks_like_zip(std::string_view data) {
    return data.size() >= 4 && data[0] == 0x50 && data[1] == 0x4b && (data[2] == 0x03 || data[2] == 0x05 || data[2] == 0x07);
}

bool has_ident_char(std::string_view s) {
    for (char c : s)
        if (is_ident_char(static_cast<unsigned char>(c))) return true;
    return false;
}

bool has_operator_char(std::string_view s) {
    for (char c : s)
        if (std::string_view("+-*/^()[],").find(c) != std::string_view::npos) return true;
    return false;
}

// The runs of `[A-Za-z0-9_]` (or, with `dots`, of `[A-Za-z0-9_.]`) in a text.
std::vector<std::string> runs_of(std::string_view s, bool dots) {
    std::vector<std::string> out;
    const std::size_t n = s.size();
    auto in_run = [&](unsigned char b) { return is_ident_char(b) || (dots && b == '.'); };
    std::size_t i = 0;
    while (i < n) {
        if (in_run(static_cast<unsigned char>(s[i]))) {
            std::size_t j = i + 1;
            while (j < n && in_run(static_cast<unsigned char>(s[j]))) j++;
            out.emplace_back(s.substr(i, j - i));
            i = j;
        } else {
            i++;
        }
    }
    return out;
}

// A reference and nothing else: a name, or a path of names.
bool is_reference(std::string_view text) {
    const std::size_t n = text.size();
    if (n == 0) return false;
    std::size_t i = 0;
    while (true) {
        if (!(i < n && (is_alpha(static_cast<unsigned char>(text[i])) || text[i] == '_'))) return false;
        i++;
        while (i < n && is_ident_char(static_cast<unsigned char>(text[i]))) i++;
        if (i >= n) return true;
        if (text[i] != '.') return false;
        i++;
    }
}

// The discrete event a transfer names: `^([A-Za-z_][A-Za-z0-9_.]*)((?:\[[^\[\]]+\])*)$`, with
// PCRE's `$` (the very end, or before a newline that ends the text).
bool match_event(const std::string& s, std::string& name, std::string& index) {
    const std::size_t n = s.size();
    if (n == 0 || !(is_alpha(static_cast<unsigned char>(s[0])) || s[0] == '_')) return false;
    std::size_t i = 1;
    while (i < n && (is_ident_char(static_cast<unsigned char>(s[i])) || s[i] == '.')) i++;
    std::size_t k = i;
    while (k < n && s[k] == '[') {
        std::size_t m = k + 1;
        while (m < n && s[m] != '[' && s[m] != ']') m++;
        if (m == k + 1 || m >= n || s[m] != ']') break;
        k = m + 1;
    }
    if (!(k == n || (k + 1 == n && s[k] == '\n'))) return false;
    name = s.substr(0, i);
    index = s.substr(i, k - i);
    return true;
}

// `compartments` -> `compartment`, for the one-of case.
std::string singularise(const std::string& label) {
    auto ends = [&](std::string_view w) { return label.size() >= w.size() && label.compare(label.size() - w.size(), w.size(), w) == 0; };
    if (ends("ies")) return label.substr(0, label.size() - 3) + "y";
    if (ends("es") && !ends("ses")) return label.substr(0, label.size() - 2);
    return ends("s") ? label.substr(0, label.size() - 1) : label;
}

// A number short enough for a sentence: 1e5 rather than 100000.
std::string fmt_count(const Json& v) {
    const double n = to_number(v);
    if (!std::isfinite(n)) return js_string(v);
    if (n != 0 && (std::fabs(n) >= 1e6 || std::fabs(n) < 1e-3)) {
        std::string s = to_exponential(round_significant(n, 4));
        const std::size_t at = s.find("e+");
        if (at != std::string::npos) s.replace(at, 2, "e");
        return s;
    }
    return js_string(round_significant(n, 6));
}

// `Created at[S]+(JS_DOT+)` as a full match, ASCII case ignored: the date.
OptStr created_at(const std::string& text) {
    const std::size_t n = text.size();
    if (!(n >= 10 && ascii_ieq(std::string_view(text).substr(0, 10), "Created at"))) return std::nullopt;
    std::size_t i = 10, spaces = 0;
    while (i < n) {
        const std::size_t sp = js_space_bytes(text, i, n);
        if (sp == 0) break;
        i += sp;
        spaces++;
    }
    if (spaces == 0 || i >= n) return std::nullopt;
    const std::string rest = text.substr(i);
    if (rest.find('\n') != std::string::npos || rest.find('\r') != std::string::npos || rest.find("\xe2\x80\xa8") != std::string::npos ||
        rest.find("\xe2\x80\xa9") != std::string::npos)
        return std::nullopt;
    return rest;
}

// `\u2026/model C.eco` -> `model C`.
OptStr base_name_of(const OptStr& path) {
    if (!truthy(path)) return std::nullopt;
    std::string last = last_part(*path);
    const std::size_t n = last.size();
    for (const char* ext : {"eco", "eas", "xml"}) {
        if (n >= 4 && last[n - 4] == '.' && ascii_ieq(std::string_view(last).substr(n - 3), ext)) {
            last = last.substr(0, n - 4);
            break;
        }
    }
    std::string t = js_trim(last);
    if (t.empty()) return std::nullopt;
    return t;
}

// The text of a `<property name="...">`, trimmed, or none.
OptStr property_text(const XmlNode& el, std::string_view name) {
    for (const XmlNode* p : el.children) {
        if (*p->name != "property") continue;
        const OptStr a = attr(*p, "name");
        if (a && *a == name) return js_trim(text(*p));
    }
    return std::nullopt;
}

// The colours Ecolego gives a new block of each type, as `#rrggbb`: a block still in one was never
// given a colour, and takes this tool's for its kind. A transfer has two, since Ecolego 6 keeps the
// old transfer coefficients' green on the transfers it reads them as. `DEFAULT_COLOURS` in
// src/io/eco.js.
const std::vector<std::string>& default_colours(const std::string& type) {
    static const std::unordered_map<std::string, std::vector<std::string>> colours = {
        {"compartment", {"#c0ffc0"}},
        {"transport-begin", {"#c0ffc0"}},
        {"transport-end", {"#c0ffc0"}},
        {"expression", {"#c0c0ff"}},
        {"post-processing", {"#c0c0ff"}},
        {"constant", {"#c0c0ff"}},
        {"transport-number", {"#c0c0ff"}},
        {"transport-element-counter", {"#d0e0a0"}},
        {"transport-operation", {"#e0e0c0"}},
        {"parameter", {"#a0ffa0"}},
        {"lookup-table", {"#c0ff80"}},
        {"index-operation", {"#c0e0c0"}},
        {"aggregate", {"#80e0c0"}},
        {"min-max", {"#c0a280"}},
        {"running-mean", {"#c0a280"}},
        {"snapshot", {"#c0a280"}},
        {"delay", {"#80c0c0"}},
        {"discrete-event", {"#c08080"}},
        {"general-variable", {"#c0e0ff"}},
        {"select", {"#c0e0ff"}},
        {"transfer", {"#c0ffc0", "#80ff80"}},
        {"transfer-coefficient", {"#c0ffc0", "#80ff80"}},
    };
    static const std::vector<std::string> none;
    auto it = colours.find(type);
    return it == colours.end() ? none : it->second;
}

// The colour a block was given in Ecolego, as `#rrggbb`, or none when it was given none: its colour
// switched off, not a number Java's `Integer.valueOf` reads -- a sign, ASCII digits, an int's
// range -- or its type's own. `blockColour` in src/io/eco.js.
OptStr block_colour(const XmlNode* el, const std::string& type) {
    OptStr shown = property_text(*el, "color-visible");
    if (!truthy(shown)) shown = child_text(el, "color-visible");
    if (truthy(shown) && py_lower(*shown) != "true") return std::nullopt;
    OptStr text = property_text(*el, "color");
    if (!truthy(text)) text = child_text(el, "color");
    if (!truthy(text)) return std::nullopt;
    const std::string& t = *text;
    const std::size_t sign = (t[0] == '+' || t[0] == '-') ? 1 : 0;
    if (sign == t.size()) return std::nullopt;
    for (std::size_t k = sign; k < t.size(); k++)
        if (t[k] < '0' || t[k] > '9') return std::nullopt;
    // The digits past any leading zeros: more than ten of them is past an int, and no overflow here.
    std::size_t first = sign;
    while (first + 1 < t.size() && t[first] == '0') first++;
    if (t.size() - first > 10) return std::nullopt;
    long long value = std::stoll(t.substr(first));
    if (t[0] == '-') value = -value;
    if (value < -2147483648LL || value > 2147483647LL) return std::nullopt;
    static const char* digits = "0123456789abcdef";
    const long long rgb = value & 0xffffff;
    std::string colour = "#";
    for (int shift = 20; shift >= 0; shift -= 4) colour += digits[(rgb >> shift) & 0xf];
    if (contains(default_colours(type), colour)) return std::nullopt;
    return colour;
}

// The predefined-type an index list declares, upper-cased.
OptStr predefined_type(const XmlNode& el) {
    const OptStr t = property_text(el, "predefined-type");
    if (!truthy(t)) return std::nullopt;
    return py_upper(js_trim(*t));
}

std::string or_str(const OptStr& s) { return truthy(s) ? *s : std::string(); }

// A nuclide's `<unit>` as one of the two an inventory can be held in, or none.
OptStr normalise_decay_unit(const OptStr& raw) {
    const std::string given = js_trim(raw ? *raw : "");
    for (const char* w : {"mol", "mole", "moles"})
        if (ascii_ieq(given, w)) return std::string("mol");
    for (const char* w : {"bq", "becquerel", "bequerel"})
        if (ascii_ieq(given, w)) return std::string("Bq");
    return std::nullopt;
}

// An array as the format writes it, `[1.0, 2.5, 3.0]`; what is not a number is dropped, and an
// empty element reads as 0, as `Number('')` does.
std::vector<double> number_list(const OptStr& text) {
    std::vector<double> out;
    if (!text) return out;
    std::string inner = js_trim(*text);
    if (!inner.empty() && inner[0] == '[') inner.erase(0, 1);
    if (!inner.empty() && inner.back() == ']') inner.pop_back();
    if (js_trim(inner).empty()) return out;
    for (const std::string& part : split_on(inner, ',')) {
        const double n = to_number(std::string_view(js_trim(part)));
        if (std::isfinite(n)) out.push_back(n);
    }
    return out;
}

// An aggregate's targets, as the format joins them: `a+b`.
Json split_targets(const Json& text) {
    Json out = Json::array();
    for (const std::string& p : split_on(text.is_null() ? std::string() : js_string(text), '+')) {
        std::string t = js_trim(p);
        if (!t.empty()) out.push(Json(t));
    }
    return out;
}

// `re.split('[<JS space>,;]+', text)` without its empty pieces.
std::vector<std::string> split_times(const std::string& text) {
    std::vector<std::string> out;
    const std::size_t n = text.size();
    std::size_t i = 0, start = 0;
    while (i < n) {
        const char b = text[i];
        const std::size_t k = (b == ',' || b == ';') ? 1 : js_space_bytes(text, i, n);
        if (k > 0) {
            if (start < i) out.push_back(text.substr(start, i - start));
            i += k;
            start = i;
        } else {
            i++;
        }
    }
    if (start < n) out.push_back(text.substr(start));
    return out;
}

// A parameter name this tool's parser can read, kept clear of its siblings.
std::string safe_parameter(const std::string& raw, const std::vector<std::string>& taken) {
    const std::string s = js_trim(raw);
    std::string name;
    bool in_run = false;
    for (std::size_t i = 0; i < s.size();) {
        std::size_t k = 1;
        const char32_t c = char_at(s, i, k);
        i += k;
        if (c < 0x80 && is_ident_char(static_cast<unsigned char>(c))) {
            name.push_back(static_cast<char>(c));
            in_run = false;
        } else if (!in_run) {
            name.push_back('_');
            in_run = true;
        }
    }
    if (!name.empty() && is_ascii_digit(static_cast<unsigned char>(name[0]))) name = "p" + name;
    if (name.empty() || is_reserved_name(name)) name = "p" + itos(static_cast<long long>(taken.size()) + 1);
    while (contains(taken, name)) name += "_";
    return name;
}

// Ecolego's "not set": one magic double written wherever a number was left alone.
constexpr double D_AUTO = -792842341234.23404823434;

// One number from the file, with Ecolego's "not set" read as absent.
std::optional<double> auto_number(const XmlNode* el, std::string_view tag) {
    const std::optional<double> v = child_number(el, tag);
    if (!v || !std::isfinite(*v)) return std::nullopt;
    if (std::fabs(*v - D_AUTO) <= std::fabs(D_AUTO) * 1e-9) return std::nullopt;
    return v;
}

// The time units Ecolego writes, as this tool's.
OptStr time_unit_of(const std::string& said) {
    static const std::map<std::string, std::string> units = {
        {"second", "second"}, {"seconds", "second"}, {"s", "second"}, {"minute", "minute"}, {"minutes", "minute"},
        {"hour", "hour"}, {"hours", "hour"}, {"h", "hour"}, {"day", "day"}, {"days", "day"}, {"d", "day"},
        {"year", "year"}, {"years", "year"}, {"y", "year"}, {"a", "year"}};
    auto it = units.find(said);
    if (it == units.end()) return std::nullopt;
    return it->second;
}

// The solver each Ecolego solver name becomes: four are the same method, the rest the nearest.
OptStr solver_of(const std::string& key) {
    static const std::map<std::string, std::string> map = {
        {"ODE45", "dp45"}, {"ODE23", "dp45"}, {"ODE113", "dp45"}, {"ODE853", "dp45"},
        {"ODE1", "dp45"}, {"ODE2", "dp45"}, {"ODE3", "dp45"}, {"ODE4", "dp45"}, {"ODE5", "dp45"},
        {"ODE15S", "ndf"}, {"ODE15SBDF", "ndf"},
        {"ODE23S", "ros23"}, {"ODE23T", "ros23"}, {"ODE23TB", "ros23"},
        {"RADAU5", "ndf"}, {"KRYLOV", "ndf"}, {"PADE", "ndf"}, {"TAYLOR", "ndf"}};
    auto it = map.find(key);
    if (it == map.end()) return std::nullopt;
    return it->second;
}

bool solver_exact(const std::string& key) {
    return key == "ODE15S" || key == "ODE15SBDF" || key == "ODE23S" || key == "ODE45";
}

// The solver a file names, as a key of the solver map: case, punctuation and `java` dropped.
std::string solver_key(const std::string& text) {
    std::string word;
    for (char c : py_upper(text))
        if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) word.push_back(c);
    if (word.compare(0, 4, "JAVA") == 0) word = word.substr(4);
    static const std::map<std::string, std::string> alias = {
        {"EULERFORWARD", "ODE1"}, {"EULERBACKWARD", "ODE1"}, {"HEUN", "ODE2"}, {"MIDPOINT", "ODE3"},
        {"RK4", "ODE4"}, {"DORMANDPRINCE", "ODE45"}, {"IMEXSD", "ODE15S"}};
    auto it = alias.find(word);
    return it == alias.end() ? word : it->second;
}

OptStr output_mode(const std::string& written) {
    static const std::map<std::string, std::string> modes = {
        {"produce no additional output", "solver"}, {"produce additional output", "both"},
        {"produce specified output only", "series"}, {"0", "solver"}, {"1", "both"}, {"2", "series"}};
    auto it = modes.find(written);
    if (it == modes.end()) return std::nullopt;
    return it->second;
}

// --- what the file's block types become ------------------------------------------------------

bool is_supported(const std::string& t) {
    static const std::unordered_set<std::string> s = {
        "compartment", "expression", "parameter", "post-processing", "constant", "lookup-table", "index-operation",
        "aggregate", "min-max", "running-mean", "snapshot", "delay", "discrete-event", "transfer", "transfer-coefficient",
        "transport-begin", "transport-end", "transport-number", "transport-element-counter", "transport-operation",
        "general-variable", "select"};
    return s.count(t) != 0;
}
bool is_boundary(const OptStr& t) { return t && (*t == "source" || *t == "sink"); }
bool is_interface(const OptStr& t) { return t && (*t == "model-input" || *t == "model-output" || *t == "connector"); }

OptStr transport_role(const std::string& t) {
    if (t == "transport-begin") return std::string("begin");
    if (t == "transport-end") return std::string("end");
    if (t == "transport-number") return std::string("number");
    if (t == "transport-element-counter") return std::string("counter");
    if (t == "transport-operation") return std::string("operation");
    return std::nullopt;
}

// --- the importer's working state ------------------------------------------------------------

// One index list as the importer works on it before it is written out.
struct EcoList {
    std::string name;
    Json indices = Json::array();
    std::unordered_map<std::string, std::string> index_by_id;
    OptStr id;
    std::string original;
    bool for_scenarios = false, for_elements = false;
    OptStr predefined;
    OptStr sub_set_of_id, mapping_to_id;
    std::vector<std::pair<OptStr, OptStr>> mapping_pairs;
    OptStr sub_set_of;
    Json mapping;
    bool for_contaminants = false, for_nuclides = false;
};

struct Materials {
    OrderedMap<bool> by_name;
    std::unordered_set<std::string> nuclide_names;
    std::unordered_map<std::string, std::string> units;
};

struct IndexIds {
    std::unordered_map<std::string, EcoList*> list_by_id;
    std::unordered_map<std::string, std::pair<std::string, std::string>> index_by_id;
};

struct Hierarchy {
    std::unordered_map<std::string, std::string> path_by_id;
    std::vector<std::string> systems, disabled_paths, transports;
};

struct Link {
    std::string source, target, via;
};

struct Wiring {
    std::vector<Link> links;
    std::unordered_map<std::string, std::string> operations;
    OrderedMap<bool> exposed;
    std::unordered_map<std::string, std::string> id_by_guid;
};

struct General {
    Json block;
    bool picked = false;
    std::vector<std::string> offered;
};

struct Provenance {
    OptStr author, comment;
    std::optional<double> modified;
};

// Maps Ecolego's names onto identifiers, and remembers the mapping so the equations can follow
// it. Unique per sub-system; keyed by block id rather than by name.
struct NameMapper {
    EcoImportReport& report;
    std::unordered_map<std::string, std::string> by_key;
    OrderedMap<std::string> by_original;
    std::unordered_map<std::string, std::unordered_set<std::string>> used;
    OrderedMap<bool> ambiguous;

    explicit NameMapper(EcoImportReport& r) : report(r) {}

    // One name as an identifier this tool can parse. A reserved word is taken before the file
    // says anything, so `min` is numbered like a clash: `min_1`.
    std::string map(const OptStr& original, const std::string& key, const std::string& system, const std::string& fallback) {
        auto hit = by_key.find(key);
        if (hit != by_key.end()) return hit->second;
        const std::string given = js_trim(original ? *original : "");
        const bool absent = given.empty();
        std::string clean = js_identifier(absent ? fallback : given);
        if (!clean.empty() && is_ascii_digit(static_cast<unsigned char>(clean[0]))) clean = "_" + clean;
        if (clean.empty()) clean = "block";
        std::unordered_set<std::string>& taken = used[system];
        std::string candidate = clean;
        long long n = 1;
        while (taken.count(candidate) || is_reserved_name(candidate)) {
            candidate = clean + "_" + itos(n);
            n++;
        }
        // A bare reference is rewritten by name, so a name that maps two ways cannot be
        // rewritten safely. A block with no name has nothing an equation could refer to it by.
        if (!absent) {
            const std::string* seen = by_original.find(given);
            if (!seen) by_original[given] = candidate;
            else if (*seen != candidate) ambiguous[given] = true;
        }
        taken.insert(candidate);
        by_key[key] = candidate;
        if (candidate != given) {
            report.renamed.push(Json::object({{"from", Json(absent ? std::string("(unnamed)") : given)}, {"to", Json(candidate)}}));
        }
        return candidate;
    }

    // A name for a block the file does not have -- a second transfer this import makes of one --
    // free in its sub-system, and taken there. Not a rename.
    std::string claim(const std::string& base, const std::string& system) {
        std::unordered_set<std::string>& taken = used[system];
        std::string candidate = base;
        long long n = 1;
        while (taken.count(candidate) || is_reserved_name(candidate)) {
            candidate = base + "_" + itos(n);
            n++;
        }
        taken.insert(candidate);
        return candidate;
    }

    std::vector<std::string> duplicated() const {
        std::vector<std::string> out;
        for (const auto& [k, v] : ambiguous.items) out.push_back(k);
        return out;
    }
};

// Which of the rewrite's pairs can change a given text, found without searching the text for
// every one of them (`_EcoCandidates`).
struct Candidates {
    std::vector<std::set<std::string>> runs;
    std::unordered_map<std::string, std::vector<std::size_t>> index;
    std::set<std::size_t> always;

    explicit Candidates(const std::vector<std::pair<std::string, std::string>>& pairs) {
        for (const auto& p : pairs) {
            std::vector<std::string> r = runs_of(p.first, false);
            runs.emplace_back(r.begin(), r.end());
        }
        for (std::size_t j = 0; j < runs.size(); j++) {
            // the longest is the rarest
            std::vector<std::string> v(runs[j].begin(), runs[j].end());
            std::sort(v.begin(), v.end(), [](const std::string& a, const std::string& b) {
                if (a.size() != b.size()) return a.size() > b.size();
                return a < b;
            });
            index[v[0]].push_back(j);
        }
        std::set<std::string> put_in;
        for (std::size_t j = 0; j < pairs.size(); j++) {
            for (const std::string& r : runs_of(pairs[j].first, true))
                if (put_in.count(r)) {
                    always.insert(j);
                    break;
                }
            put_in.insert(pairs[j].second);
        }
    }

    std::vector<std::size_t> of(const std::string& text) const {
        std::vector<std::string> r = runs_of(text, false);
        const std::set<std::string> rs(r.begin(), r.end());
        std::set<std::size_t> found = always;
        for (const std::string& run : rs) {
            auto it = index.find(run);
            if (it == index.end()) continue;
            for (std::size_t j : it->second)
                if (std::includes(rs.begin(), rs.end(), runs[j].begin(), runs[j].end())) found.insert(j);
        }
        return std::vector<std::size_t>(found.begin(), found.end());
    }
};

// --- the importer ----------------------------------------------------------------------------

class Importer {
public:
    EcoImportReport report;
    NameMapper names{report};
    Json project = Json::object();

    // A model.xml read into a project.
    void run(const XmlNode* data_model, const OptStr& file_name, const OptStr& version) {
        project.set("name", Json("Imported project"));
        project.set("description", Json(""));
        project.set("simulation", Json::object());
        for (const char* k : {"index_lists", "parameters", "compartments", "expressions", "transfers", "inflows", "lookups",
                              "index_reductions", "block_reductions", "min_maxes", "running_means", "snapshots", "delays",
                              "triggers", "functions"})
            project.set(k, Json::array());

        const Provenance provenance = read_project_properties(data_model, file_name);
        read_functions(data_model);
        const Materials materials = read_materials(data_model);
        const IndexIds index_ids = read_index_lists(data_model, materials);
        read_decay_chains(data_model);
        Hierarchy hierarchy = read_hierarchy(data_model);
        read_blocks(data_model, index_ids, hierarchy);
        read_simulation_settings(data_model);

        // Two rewrites, both textual and both necessary: Ecolego names may hold spaces and
        // punctuation this tool's identifiers cannot, so those blocks were renamed above; and
        // equations may use sub-system-qualified references, which are the block ids.
        rewrite_renamed_references();
        drop_unreachable_targets();
        // What Ecolego's sub-system inputs and outputs connected, connected directly. Last, so
        // the references it writes are the names the model ended up with.
        connect_interfaces();
        // After the two above, so what a general variable reads is the name the model ended up with.
        settle_general_variables();
        rewrite_endpoint_ids();
        // Last of the rewrites, so the trigger a discrete transfer names, and the compartments it
        // moves between, are the names the model ended up with.
        settle_transfer_events();

        const std::vector<std::string> duplicated = names.duplicated();
        if (!duplicated.empty()) {
            const std::string more = duplicated.size() > 6 ? "\u2026" : "";
            warn(itos(static_cast<long long>(duplicated.size())) +
                 " name(s) had to be spelled differently in different sub-systems (" + join(first_n(duplicated, 6), ", ") + more +
                 "), because the original is not a valid identifier and the tidied form was already taken. A bare reference to one "
                 "of those was left as written -- check those equations.");
        }

        finish();
        // Last, so the counts are of the model as it ended up rather than as the file spelled it.
        project.set("description", Json(describe_model(provenance, file_name, version)));
        // Who wrote it, as the file says -- beside the name and the description, where a model of
        // this tool's own keeps it.
        if (truthy(provenance.author)) {
            Json head = Json::object();
            head.set("name", project.get("name"));
            head.set("description", project.get("description"));
            head.set("author", Json(*provenance.author));
            for (const auto& [k, v] : project.obj())
                if (!head.has(k)) head.set(k, v);
            project = head;
        }
        json_ready(project);
    }

private:
    std::deque<EcoList> lists_;
    std::unordered_set<const JObject*> markers_;
    // What read_blocks hands on.
    OrderedMap<std::string> block_name_by_id_;
    Wiring wiring_;
    OrderedMap<std::string> twins_;
    std::vector<General> generals_;

    // --- the report ----------------------------------------------------------------------------

    void skip(const std::string& type, const Json& name, const std::string& why) {
        report.skipped.push(Json::object({{"type", Json(type)}, {"name", name}, {"why", Json(why)}}));
    }
    void note(const std::string& type, const std::string& name) {
        report.notes.push(Json::object({{"type", Json(type)}, {"name", Json(name)}}));
    }
    void warn(const std::string& message) {
        if (report.said.count(message)) return;
        report.said.insert(message);
        report.warnings.push_back(message);
    }
    void in_disabled_system(const std::string& path) {
        if (!report.disabled_systems) report.disabled_systems.emplace();
        for (auto& [p, n] : *report.disabled_systems)
            if (p == path) {
                n++;
                return;
            }
        report.disabled_systems->emplace_back(path, 1);
    }

    void finish() {
        auto n = [&](const char* k) { return static_cast<long long>(list_of(project, k).size()); };
        report.counts = {{"index_lists", n("index_lists")},
                         {"compartments", n("compartments")},
                         {"transfers", n("transfers")},
                         {"parameters", n("parameters")},
                         {"expressions", n("expressions")},
                         {"inflows", n("inflows")},
                         {"lookups", n("lookups")},
                         {"index_reductions", n("index_reductions")},
                         {"block_reductions", n("block_reductions")},
                         {"min_maxes", n("min_maxes")},
                         {"running_means", n("running_means")},
                         {"snapshots", n("snapshots")},
                         {"delays", n("delays")},
                         {"triggers", n("triggers")},
                         {"events", n("events")},
                         {"nuclides", n("nuclides")}};
    }

    // --- values a plain JavaScript object inherits ---------------------------------------------

    // A name a plain object inherits (`constructor`, `toString`, `__proto__`): a value of its own
    // until the project is made ready for JSON, which leaves a function out of a dictionary
    // (`null` in a list) and writes the prototype as `{}`.
    Json value_of(const PlainValue& p) {
        if (p.kind == PlainValue::Kind::Own) return Json(p.value);
        if (p.kind == PlainValue::Kind::None) return Json();
        Json m = Json::object({{"inherited", Json(p.value)}, {"function", Json(p.is_function)}});
        markers_.insert(&m.obj());
        return m;
    }
    bool is_marker(const Json& v) const { return v.is_object() && markers_.count(&v.obj()) != 0; }
    bool is_function_marker(const Json& v) const { return is_marker(v) && v.get("function").as_bool(); }

    // `value` as `JSON.stringify` would see it, changed in place.
    Json json_ready(Json value) {
        if (is_marker(value)) return is_function_marker(value) ? Json() : Json::object();
        if (value.is_object()) {
            for (const std::string& k : value.obj().keys()) {
                const Json v = value.get(k);
                if (is_function_marker(v)) value.erase(k);
                else value.set(k, json_ready(v));
            }
            return value;
        }
        if (value.is_array()) {
            JArray& a = value.arr();
            for (Json& x : a) x = json_ready(x);
            return value;
        }
        return value;
    }

    // --- names ---------------------------------------------------------------------------------

    // A nuclide's, material's, index's or decay pair's name, as the file gives it, trimmed; none
    // (and a warning) for a blank one. A prototype key is refused outright.
    OptStr key_name(const OptStr& raw, const std::string& what) {
        const std::string name = js_trim(raw ? *raw : "");
        const std::string an = (!what.empty() && std::string("aeiouAEIOU").find(what[0]) != std::string::npos) ? "An" : "A";
        if (name.empty()) {
            warn(an + " " + what + " with no name was left out.");
            return std::nullopt;
        }
        if (name == "__proto__" || name == "constructor" || name == "prototype") {
            throw EcoImportError(an + " " + what + " in this file is called '" + name +
                                 "', which is not a name but a key into every object's prototype; this tool keys its tables by these "
                                 "names and cannot hold one. Ecolego never writes it -- rename the " +
                                 what + " in Ecolego, or check that the file has not been tampered with.");
        }
        return name;
    }

    // --- sections ------------------------------------------------------------------------------

    // <project-properties>: the model's name, and who wrote it, when.
    Provenance read_project_properties(const XmlNode* data_model, const OptStr& file_name) {
        const XmlNode* props = child(data_model, "project-properties");
        const OptStr from_file = base_name_of(file_name);
        if (!props) {
            project.set("name", Json(from_file ? *from_file : std::string("Imported project")));
            return {};
        }
        OptStr declared = attr(*props, "name");
        if (!declared) declared = child_text(props, "name");
        if (!declared) declared = child_text(props, "full-name");
        OptStr chosen = (!truthy(declared) || *declared == "model") ? from_file : std::nullopt;
        if (!chosen) chosen = declared ? *declared : std::string("Imported project");
        project.set("name", Json(*chosen));
        const double stamp = to_number(child_text(props, "modification-date"));
        const OptStr author = property_text(*props, "author");
        OptStr comment = property_text(*props, "comment");
        if (!truthy(comment)) comment = child_text(props, "comment");
        Provenance p;
        if (truthy(author)) p.author = author;
        if (truthy(comment)) p.comment = comment;
        if (std::isfinite(stamp) && stamp > 0) p.modified = stamp;
        return p;
    }

    // <function-model>: the project's compiled user-defined functions. Their names and parameters
    // come across; their bodies, compiled code in the archive, cannot.
    void read_functions(const XmlNode* data_model) {
        const XmlNode* model = find(*data_model, "function-model");
        if (!model) return;
        for (const XmlNode* el : children(model, "function")) {
            OptStr original = attr(*el, "name");
            if (!original) original = attr(*el, "source-file-name");
            if (!original) original = std::string("function");
            const std::string name = names.map(original, "fn:" + *original, "", *original);
            const XmlNode* meta = child(el, "function-metadata");
            std::vector<std::string> parameters;
            if (meta) {
                for (const XmlNode* p : children(meta, "parameter-metadata")) {
                    // The key is the identifier; the name is what the dialog showed.
                    OptStr raw = attr(*p, "key");
                    if (!raw) raw = attr(*p, "name");
                    if (!raw) raw = "p" + itos(static_cast<long long>(parameters.size()) + 1);
                    parameters.push_back(safe_parameter(*raw, parameters));
                }
            }
            project["functions"].push(trim_empty({{"name", Json(name)},
                                                  {"parameters", Json::array(parameters)},
                                                  {"equation", Json("")},
                                                  {"unit", Json("")},
                                                  {"comment", Json(or_str(child_text(meta ? meta : el, "function-description")))}}));
            const OptStr source = attr(*el, "source-file-name");
            warn("'" + *original + "' is a user-defined function, whose body is compiled code in the project archive (" +
                 (source ? *source : std::string("a compiled source file")) + "). This tool keeps its name and its " +
                 itos(static_cast<long long>(parameters.size())) +
                 " parameter(s); write what it works out to as an equation before the model will run.");
        }
    }

    // <material-model>: the nuclides with their half-lives (seconds in the file, years here; a
    // missing or infinite one is stable), the plain materials with their units, and the unit the
    // inventories are in.
    Materials read_materials(const XmlNode* data_model) {
        const XmlNode* model = child(data_model, "material-model");
        Materials out;
        if (!model) return out;
        // A half-life is in seconds, and how many make a year depends on the unit the model runs in.
        const OptStr said_text = child_text(child(data_model, "simulation-settings"), "time-unit");
        const std::string said = py_lower(said_text ? *said_text : "");
        const OptStr unit_said = time_unit_of(said);
        const double per_year = seconds_per_year(unit_said ? *unit_said : "year");
        Json half_lives = Json::object();
        OptStr decay_unit;
        for (const XmlNode* nuc : children(model, "nuclide")) {
            const OptStr name = key_name(attr(*nuc, "name"), "nuclide");
            if (!truthy(name)) continue;
            const OptStr unit = normalise_decay_unit(child_text(nuc, "unit"));
            if (truthy(unit)) {
                if (truthy(decay_unit) && *decay_unit != *unit)
                    warn("The nuclides disagree about their unit (" + *decay_unit + " and " + *unit + "); the model is read as " + *decay_unit + ".");
                else if (!truthy(decay_unit))
                    decay_unit = unit;
            }
            const OptStr raw_half_life = child_text(nuc, "half-life");
            const double seconds = to_number(raw_half_life);
            if (std::isfinite(seconds) && seconds > 0) {
                half_lives.set(*name, Json(seconds / per_year));
            } else {
                // Stable isotopes are written with an infinite (or absent) half-life. The word, not
                // infinity, which JSON cannot hold.
                half_lives.set(*name, Json(STABLE));
                if (truthy(raw_half_life) && ascii_lower(*raw_half_life).find("inf") == std::string::npos)
                    warn("'" + *name + "' has no usable half-life; it is treated as stable.");
            }
            out.by_name[*name] = true;
            out.nuclide_names.insert(*name);
        }
        // Plain materials carry no decay and a unit of their own.
        for (const XmlNode* mat : children(model, "material")) {
            const OptStr name = key_name(attr(*mat, "name"), "material");
            if (!truthy(name)) continue;
            out.by_name[*name] = true;
            const OptStr u = child_text(mat, "unit");
            const std::string unit = js_trim(u ? *u : "");
            if (!unit.empty()) out.units[*name] = unit;
        }
        if (!half_lives.empty()) project.set("half_lives", js_object_order(half_lives));
        // Written whichever it is, so a round trip cannot turn an amount model into an activity one.
        project.set("decay_unit", Json(decay_unit ? *decay_unit : std::string("Bq")));
        return out;
    }

    // <index-list-model>: the index lists, their sub-sets and mappings (resolved by id), and which
    // of them are the material catalogue, the radionuclides, the scenarios and the elements.
    IndexIds read_index_lists(const XmlNode* data_model, const Materials& materials) {
        const XmlNode* model = child(data_model, "index-list-model");
        IndexIds ids;
        if (!model) return ids;

        std::vector<EcoList*> raw;
        for (const XmlNode* list_el : children(model, "index-list")) {
            // This package's export writes a scenario list under Ecolego's name for it,
            // `Scenarios`, with its own name beside it: that name is the list's.
            const OptStr pre = predefined_type(*list_el);
            const OptStr own_name = (pre && *pre == "SCENARIOS") ? property_text(*list_el, "kompartment-name") : std::nullopt;
            const OptStr raw_name = truthy(own_name) ? own_name : attr(*list_el, "name");
            const OptStr list_id = child_text(list_el, "id");
            const std::string key = list_id ? *list_id : (raw_name ? *raw_name : std::string());
            const std::string name = names.map(raw_name, "indexlist:" + key, "", "IndexList");
            std::string original_name = js_trim(raw_name ? *raw_name : "");
            if (original_name.empty()) original_name = name;

            Json indices = Json::array();
            std::unordered_map<std::string, std::string> own_index_by_id;
            for (const XmlNode* idx_el : children(list_el, "index")) {
                const OptStr idx_name = key_name(attr(*idx_el, "name"), "index of '" + original_name + "'");
                if (!truthy(idx_name)) continue;
                const OptStr idx_id = child_text(idx_el, "id");
                const OptStr enabled_attr = attr(*idx_el, "enabled");
                const bool enabled = !enabled_attr ? true : py_lower(*enabled_attr) == "true";
                indices.push(Json::object({{"name", Json(*idx_name)}, {"enabled", Json(enabled)}}));
                if (truthy(idx_id)) {
                    own_index_by_id[*idx_id] = *idx_name;
                    if (!ids.index_by_id.count(*idx_id)) ids.index_by_id[*idx_id] = {*idx_name, name};
                }
            }

            const OptStr predefined = predefined_type(*list_el);
            EcoList& entry = lists_.emplace_back();
            entry.name = name;
            entry.indices = indices;
            entry.index_by_id = std::move(own_index_by_id);
            entry.id = list_id;
            entry.original = original_name;
            entry.for_scenarios = predefined && *predefined == "SCENARIOS";
            entry.for_elements = predefined && *predefined == "ELEMENTS";
            entry.predefined = predefined;
            const XmlNode* sub_set = child(list_el, "sub-set");
            if (sub_set && truthy(attr(*sub_set, "of"))) entry.sub_set_of_id = attr(*sub_set, "of");
            const XmlNode* mapping = child(list_el, "mapping");
            if (mapping && truthy(attr(*mapping, "to"))) {
                entry.mapping_to_id = attr(*mapping, "to");
                for (const XmlNode* m : children(mapping, "map")) entry.mapping_pairs.emplace_back(attr(*m, "from"), attr(*m, "to"));
            }
            raw.push_back(&entry);
            if (truthy(list_id)) ids.list_by_id[*list_id] = &entry;
        }

        // Resolve id references now that every list is known.
        auto global_index = [&](const OptStr& id) -> OptStr {
            if (!id) return std::nullopt;
            auto it = ids.index_by_id.find(*id);
            if (it == ids.index_by_id.end()) return std::nullopt;
            return it->second.first;
        };
        for (EcoList* entry : raw) {
            if (truthy(entry->sub_set_of_id)) {
                auto it = ids.list_by_id.find(*entry->sub_set_of_id);
                if (it != ids.list_by_id.end()) entry->sub_set_of = it->second->name;
                else warn("Index list '" + entry->original + "' is a sub-set of a list that is not in the file.");
            }
            if (truthy(entry->mapping_to_id)) {
                auto it = ids.list_by_id.find(*entry->mapping_to_id);
                if (it != ids.list_by_id.end()) {
                    EcoList* target = it->second;
                    Json pairs = Json::array();
                    for (const auto& [from_id, to_id] : entry->mapping_pairs) {
                        OptStr frm;
                        if (from_id) {
                            auto f = entry->index_by_id.find(*from_id);
                            if (f != entry->index_by_id.end()) frm = f->second;
                        }
                        if (!frm) frm = global_index(from_id);
                        OptStr to;
                        if (to_id) {
                            auto t = target->index_by_id.find(*to_id);
                            if (t != target->index_by_id.end()) to = t->second;
                        }
                        if (!to) to = global_index(to_id);
                        if (truthy(frm) && truthy(to)) pairs.push(Json::object({{"from", Json(*frm)}, {"to", Json(*to)}}));
                    }
                    entry->mapping = Json::object({{"to", Json(target->name)}, {"pairs", pairs}});
                } else {
                    warn("Index list '" + entry->original + "' maps to a list that is not in the file.");
                }
            }
        }

        // The material dimensions: by predefined type, then by name, then by shape.
        std::vector<EcoList*> candidates;
        for (EcoList* e : raw) {
            if (e->indices.empty()) continue;
            bool all = true;
            for (const Json& i : e->indices.arr())
                if (!materials.by_name.has(i.get("name").as_string())) {
                    all = false;
                    break;
                }
            if (all) candidates.push_back(e);
        }
        auto list_named = [&](const std::string& want) -> EcoList* {
            for (EcoList* e : raw)
                if (ascii_lower(js_trim(e->name)) == want) return e;
            return nullptr;
        };
        auto in_candidates = [&](EcoList* e) { return std::find(candidates.begin(), candidates.end(), e) != candidates.end(); };
        auto usable = [&](EcoList* e) { return e && (e->indices.empty() || in_candidates(e)); };
        auto first_of = [&](const std::vector<EcoList*>& v, const std::function<bool(EcoList*)>& pred) -> EcoList* {
            for (EcoList* e : v)
                if (pred(e)) return e;
            return nullptr;
        };

        EcoList* catalogue = first_of(raw, [](EcoList* e) { return e->predefined && *e->predefined == "MATERIALS"; });
        EcoList* nuclides = first_of(raw, [](EcoList* e) { return e->predefined && *e->predefined == "RADIONUCLIDES"; });
        if (!catalogue && usable(list_named("materials"))) catalogue = list_named("materials");
        if (!nuclides && usable(list_named("radionuclides"))) nuclides = list_named("radionuclides");
        // The shape: a sub-set of the materials is the radionuclides, and the list a radionuclide
        // sub-set is taken from is the materials.
        if (!catalogue && nuclides && truthy(nuclides->sub_set_of)) {
            const std::string of = *nuclides->sub_set_of;
            catalogue = first_of(raw, [&](EcoList* e) { return e->name == of; });
        }
        if (!catalogue) {
            catalogue = first_of(candidates, [](EcoList* e) { return !truthy(e->sub_set_of) && e->mapping.is_null(); });
            if (!catalogue && !candidates.empty()) {
                catalogue = candidates[0];
                for (EcoList* e : candidates)
                    if (e->indices.size() > catalogue->indices.size()) catalogue = e;
            }
        }
        if (!nuclides && catalogue) {
            nuclides = first_of(candidates, [&](EcoList* e) { return e != catalogue && e->sub_set_of && *e->sub_set_of == catalogue->name; });
        }

        if (catalogue) {
            catalogue->for_contaminants = true;
            // A material that is not a radionuclide is measured in its own unit.
            for (Json& i : catalogue->indices.arr()) {
                auto u = materials.units.find(i.get("name").as_string());
                if (u != materials.units.end() && !u->second.empty()) i.set("unit", Json(u->second));
            }
        }
        if (nuclides && nuclides != catalogue) {
            nuclides->for_nuclides = true;
            if (!truthy(nuclides->sub_set_of) && catalogue) nuclides->sub_set_of = catalogue->name;
            // A file may carry the list without its contents; Ecolego decays what the material
            // model says, so that is what goes here.
            std::unordered_set<std::string> have;
            for (const Json& i : nuclides->indices.arr()) have.insert(i.get("name").as_string());
            std::vector<std::string> added;
            if (catalogue) {
                const JArray cat = catalogue->indices.arr();
                for (const Json& i : cat) {
                    const std::string n = i.get("name").as_string();
                    if (have.count(n) || !materials.nuclide_names.count(n)) continue;
                    nuclides->indices.push(Json::object({{"name", Json(n)}, {"enabled", i.get("enabled")}}));
                    added.push_back(n);
                }
            }
            if (!added.empty() && have.empty()) {
                warn("'" + nuclides->name + "' is empty in this file; its " + itos(static_cast<long long>(added.size())) + " radionuclide" +
                     (added.size() == 1 ? "" : "s") + " were read from the material model, which is what Ecolego decays them from.");
            }
        }
        EcoList* decaying = nuclides ? nuclides : catalogue;
        if (decaying) {
            Json names_ = Json::array();
            for (const Json& i : decaying->indices.arr())
                if (i.get("enabled").as_bool()) names_.push(i.get("name"));
            project.set("nuclides", names_);
        }

        // A file that says nothing about its lists still names them: `Scenarios` and `Elements`
        // are Ecolego's own names for its own.
        if (!std::any_of(raw.begin(), raw.end(), [](EcoList* e) { return e->for_scenarios; })) {
            EcoList* found = list_named("scenarios");
            if (found) found->for_scenarios = true;
        }
        if (!std::any_of(raw.begin(), raw.end(), [](EcoList* e) { return e->for_elements; })) {
            EcoList* found = list_named("elements");
            if (found && !found->for_contaminants && !found->for_nuclides) found->for_elements = true;
        }

        std::vector<EcoList*> scenarios;
        for (EcoList* e : raw)
            if (e->for_scenarios) scenarios.push_back(e);
        std::vector<Json> named;
        for (EcoList* e : scenarios)
            for (const Json& i : e->indices.arr())
                if (i.get("enabled").as_bool()) named.push_back(i);
        if (named.size() > 1) {
            warn("This model has " + itos(static_cast<long long>(named.size())) + " scenarios (" + scenarios[0]->name +
                 "). Ecolego runs one simulation per scenario; this tool runs one at a time -- pick which under Simulation, and "
                 "every block indexed by that list is read at the one selected. It opened on '" +
                 named[0].get("name").as_string() + "'.");
        }

        Json lists = Json::array();
        for (EcoList* e : raw) {
            Json out = Json::object({{"name", Json(e->name)}, {"indices", e->indices}});
            if (e->for_contaminants) out.set("for_contaminants", Json(true));
            if (e->for_nuclides) out.set("for_nuclides", Json(true));
            if (e->for_scenarios) out.set("for_scenarios", Json(true));
            if (e->for_elements) out.set("for_elements", Json(true));
            if (truthy(e->sub_set_of)) out.set("sub_set_of", Json(*e->sub_set_of));
            if (!e->mapping.is_null()) out.set("mapping", e->mapping);
            lists.push(out);
        }
        project.set("index_lists", lists);
        return ids;
    }

    // <nuclide-decay-model>: the decay pairs, with their branching ratios (1 where the file's is
    // not a number).
    void read_decay_chains(const XmlNode* data_model) {
        const XmlNode* model = child(data_model, "nuclide-decay-model");
        if (!model) return;
        Json chains = Json::array();
        for (const XmlNode* pair : children(model, "decay-pair")) {
            const OptStr rate = attr(*pair, "rate");
            const OptStr parent = key_name(attr(*pair, "parent"), "decay pair parent");
            const OptStr daughter = key_name(attr(*pair, "daughter"), "decay pair daughter");
            if (!(truthy(parent) && truthy(daughter))) continue;
            // A missing attribute is `undefined`, which is NaN.
            const double ratio = !rate ? std::nan("") : to_number(std::string_view(*rate));
            chains.push(Json::array({Json(*parent), Json(*daughter), std::isfinite(ratio) ? Json(ratio) : Json(1)}));
        }
        if (!chains.empty()) project.set("chains", chains);
    }

    // <hierarchy-model>: every sub-system, parents before children. A sub-system is a namespace
    // and gives its blocks a path; a group is only a visual grouping and is flattened away; a
    // transport is marked; one the file switches off is carried as switched off.
    Hierarchy read_hierarchy(const XmlNode* data_model) {
        const XmlNode* model = child(data_model, "hierarchy-model");
        Hierarchy out;
        if (!model) return out;
        long long groups = 0;
        for (const XmlNode* el : children(model, "sub-system-block")) {
            const OptStr sid = child_text(el, "id");
            const OptStr original = attr(*el, "name");
            // The root carries neither, and is not a level of anything.
            if (!(truthy(sid) && truthy(original))) continue;
            const OptStr parent_id = child_text(el, "sub-system");
            std::string parent_path;
            if (truthy(parent_id)) {
                auto it = out.path_by_id.find(*parent_id);
                if (it != out.path_by_id.end()) parent_path = it->second;
            }
            const std::string kind = attr_or(*el, "type", "");
            if (kind == "group") {
                groups++;
                out.path_by_id[*sid] = parent_path;
                continue;
            }
            if (kind == "external") {
                warn("Sub-system '" + *original +
                     "' is an external sub-system; this tool reads it as an ordinary one, so its linked library is not applied.");
            }
            const std::string local = names.map(original, "subsystem:" + *sid, parent_path, "subsystem");
            const std::string path = parent_path.empty() ? local : parent_path + "." + local;
            out.path_by_id[*sid] = path;
            out.systems.push_back(path);
            if (kind == "transport") out.transports.push_back(path);
            const std::optional<bool> enabled = child_bool(el, "enabled");
            if (!(enabled ? *enabled : true)) out.disabled_paths.push_back(path);
        }
        if (groups != 0) {
            warn(itos(groups) + " group" + (groups == 1 ? " was" : "s were") +
                 " flattened: a group is a visual grouping in Ecolego and does not scope names, so its blocks belong to the sub-system "
                 "around it.");
        }
        if (!out.systems.empty()) project.set("systems", Json::array(out.systems));
        if (!out.transports.empty()) project.set("transports", Json::array(out.transports));
        if (!out.disabled_paths.empty()) project.set("disabled_systems", Json::array(out.disabled_paths));
        return out;
    }

    // --- blocks --------------------------------------------------------------------------------

    // The value of the entry with no index -- Ecolego's default -- or null.
    static Json pick_default(const std::vector<Json>& entries, const char* key) {
        for (const Json& e : entries)
            if (e.get("index").empty() && e.has(key)) return e.get(key);
        return Json();
    }

    // The entries that carry an index, with only `keys`.
    static Json keep_indexed(const std::vector<Json>& entries, const std::vector<std::string>& ks) {
        Json out = Json::array();
        for (const Json& e : entries) {
            if (e.get("index").empty()) continue;
            Json rec = Json::object({{"index", e.get("index")}});
            bool found = false;
            for (const std::string& k : ks)
                if (e.has(k)) {
                    rec.set(k, e.get(k));
                    found = true;
                }
            if (found) out.push(rec);
        }
        return out;
    }

    static Json or_json(const Json& v, const Json& fallback) { return v.is_null() ? fallback : v; }

    // Drops an absolute tolerance this tool cannot carry -- infinite, zero or negative -- and says so.
    void readable_tolerances(std::vector<Json>& entries, const std::string& block_label) {
        long long dropped = 0;
        for (Json& e : entries) {
            if (!e.has("abstol")) continue;
            if (is_finite_number(e.get("abstol")) && e.get("abstol").as_double() > 0) continue;
            e.erase("abstol");
            dropped++;
        }
        if (dropped != 0) {
            warn("'" + block_label + "' sets an absolute tolerance this tool cannot carry (" + itos(dropped) +
                 " of them -- infinite, zero or negative). The simulation's own absolute tolerance applies to those states.");
        }
    }

    // Ecolego's saturation band, read as the one constraint this tool keeps.
    bool read_non_negative(const std::vector<Json>& entries, const std::string& block_label) {
        bool bounded = false, negative_floor = false;
        for (const Json& e : entries) {
            const Json& lo = e.get("lower");
            const Json& hi = e.get("upper");
            if (!lo.is_null() && std::isfinite(to_number(lo))) {
                if (to_number(lo) < 0) negative_floor = true;
                else if (to_number(lo) > 0) bounded = true;
            }
            if (!hi.is_null() && std::isfinite(to_number(hi))) bounded = true;
        }
        if (bounded) {
            warn("'" + block_label +
                 "' has a saturation band. This tool keeps only the \"cannot go negative\" part of it, so the floor and ceiling were "
                 "dropped -- express a cap as a rate term instead, or the model will not be the one in the file.");
        }
        return !negative_floor;
    }

    static void assign_if(Json& rec, const char* key, const OptStr& value) {
        if (value && !value->empty()) rec.set(key, Json(*value));
    }

    static void assign_number_if(Json& rec, const char* key, const OptStr& value) {
        if (!value || value->empty()) return;
        const double n = to_number(std::string_view(*value));
        if (std::isfinite(n)) rec.set(key, Json(n));
        else if (py_lower(*value) == "infinity") rec.set(key, Json(std::numeric_limits<double>::infinity()));
    }

    // A block's <entry> elements, each as `{index: {list: index}, ...values}`. An entry whose
    // index cannot be resolved against the block's own lists is dropped rather than applied to
    // the wrong cells. A transfer's entries are read as a transfer's whatever their `type` says.
    std::vector<Json> read_entries(const XmlNode* el, const std::vector<EcoList*>& dim_lists, const std::string& block_label) {
        std::vector<Json> out;
        const OptStr el_type = attr(*el, "type");
        const bool transfer = el_type && (*el_type == "transfer" || *el_type == "transfer-coefficient");
        for (const XmlNode* entry_el : el->children) {
            if (*entry_el->name != "entry") continue;
            Json index = Json::object();
            std::vector<std::string> ids;
            for (const std::string& p : split_on(attr_or(*entry_el, "index", ""), ',')) {
                std::string s = js_trim(p);
                if (!s.empty()) ids.push_back(s);
            }
            for (std::size_t position = 0; position < ids.size(); position++) {
                const std::string& idx_id = ids[position];
                // The ids are written in the order the block declares its lists, so position i
                // belongs to dimension i; a search where it does not.
                EcoList* positional = position < dim_lists.size() ? dim_lists[position] : nullptr;
                if (positional) {
                    auto it = positional->index_by_id.find(idx_id);
                    if (it != positional->index_by_id.end()) {
                        index.set(positional->name, Json(it->second));
                        continue;
                    }
                }
                EcoList* owner = nullptr;
                for (EcoList* l : dim_lists)
                    if (l->index_by_id.count(idx_id)) {
                        owner = l;
                        break;
                    }
                if (owner) {
                    index.set(owner->name, Json(owner->index_by_id.at(idx_id)));
                    continue;
                }
                warn("An entry of '" + block_label + "' is keyed by an index ('" + idx_id +
                     "') that none of its index lists contains; that entry was dropped.");
            }

            Json rec = Json::object({{"index", index}});
            const OptStr type = transfer ? OptStr("transfer") : attr(*entry_el, "type");
            const std::string t = type ? *type : std::string();
            if (t == "compartment") {
                assign_if(rec, "initial", child_text(entry_el, "initial-condition"));
                assign_number_if(rec, "lower", child_text(entry_el, "lower-saturation"));
                assign_number_if(rec, "upper", child_text(entry_el, "upper-saturation"));
                // This compartment's own absolute tolerance, at this index.
                assign_number_if(rec, "abstol", child_text(entry_el, "abs-tol"));
                // The extra term in the compartment's rate of change.
                assign_if(rec, "dydt", child_text(entry_el, "differential-equation"));
            } else if (t == "transfer") {
                OptStr rate = child_text(entry_el, "transfer-equation");
                if (!rate) rate = child_text(entry_el, "equation");
                assign_if(rec, "rate", rate);
                const OptStr mult = child_text(entry_el, "multiply-with-donor");
                if (mult && !mult->empty()) rec.set("multiply_by_donor", Json(py_lower(*mult) == "true"));
                // The discrete event that makes this a discrete transfer: settled into an event of
                // this tool's by settle_transfer_events.
                const OptStr event = child_text(entry_el, "transfer-event");
                if (event) {
                    std::string stripped = js_trim(*event);
                    if (!stripped.empty()) rec.set("transfer_event", Json(stripped));
                }
            } else if (t == "expression") {
                assign_if(rec, "equation", child_text(entry_el, "equation"));
            } else if (t == "parameter") {
                assign_number_if(rec, "value", child_text(entry_el, "value"));
                // The distribution, kept: `function=` names the kind and the expression the
                // family, and the parser needs both.
                const XmlNode* pdf_el = child(entry_el, "pdf");
                if (pdf_el) {
                    const OptStr value = child_text(pdf_el, "pdf-value");
                    const OptStr fn = attr(*pdf_el, "function");
                    std::optional<Json> spec = parse_pdf(value ? *value : "", fn ? *fn : "");
                    if (spec && !spec->empty()) rec.set("pdf", *spec);
                    else rec.set("pdf_unread", Json(value ? *value : std::string()));
                }
            } else if (t == "min-max" || t == "running-mean") {
                assign_if(rec, "target", child_text(entry_el, "target-expression"));
                assign_if(rec, "reset_trigger", child_text(entry_el, "reset-event"));
                assign_if(rec, "start_trigger", child_text(entry_el, "start-recording-event"));
                assign_if(rec, "stop_trigger", child_text(entry_el, "stop-recording-event"));
            } else if (t == "snapshot") {
                assign_if(rec, "target", child_text(entry_el, "snapshot-target"));
                assign_if(rec, "trigger", child_text(entry_el, "snapshot-event"));
                assign_if(rec, "initial", child_text(entry_el, "snapshot-initial-value"));
            } else if (t == "delay") {
                assign_if(rec, "target", child_text(entry_el, "delay-target"));
                assign_if(rec, "delay", child_text(entry_el, "delay-time"));
            } else if (t == "discrete-event") {
                assign_if(rec, "first", child_text(entry_el, "first-expression"));
                assign_if(rec, "second", child_text(entry_el, "second-expression"));
                Json direction = value_of(direction_from_eco(child_text(entry_el, "direction")));
                if (truthy(direction)) rec.set("direction", direction);
            } else if (t == "lookup-table") {
                const std::vector<double> xs = number_list(child_text(entry_el, "lookup-table-time-points"));
                const std::vector<double> ys = number_list(child_text(entry_el, "lookup-table-values"));
                // Walked to the shorter of the two, so a truncated file loses the tail rather
                // than the whole table.
                const std::size_t n = std::min(xs.size(), ys.size());
                if (n < xs.size() || n < ys.size()) {
                    warn("'" + block_label + "' has " + itos(static_cast<long long>(xs.size())) + " time point(s) but " +
                         itos(static_cast<long long>(ys.size())) + " value(s); the extra ones were dropped.");
                }
                Json points = Json::array();
                for (std::size_t k = 0; k < n; k++) points.push(Json::array({Json(xs[k]), Json(ys[k])}));
                if (!points.empty()) rec.set("points", points);
                if (child(entry_el, "link")) {
                    warn("'" + block_label + "' takes its table from a linked result, which this tool cannot follow; the stored points were used.");
                }
            }

            const OptStr entry_unit = child_text(entry_el, "entry-unit");
            if (truthy(entry_unit)) rec.set("unit", Json(*entry_unit));

            if (index.size() != ids.size()) continue;
            out.push_back(rec);
        }
        return out;
    }

    // The list a transfer written over the intersection of its two ends stands on: Ecolego writes
    // that list as `index-lists=""` with `dimension="1"`.
    std::vector<EcoList*> intersection_dims(const XmlNode* el, const std::string& original,
                                            const std::unordered_map<std::string, std::vector<EcoList*>>& dims_by_id) {
        const OptStr dimension = attr(*el, "dimension");
        const double width = dimension ? to_number(std::string_view(*dimension)) : 0.0;
        if (!std::isfinite(width) || width < 1) return {};
        const OptStr src_id = attr(*el, "source");
        const OptStr dst_id = attr(*el, "target");
        auto dims_of = [&](const OptStr& id) -> std::vector<EcoList*> {
            if (!id) return {};
            auto it = dims_by_id.find(*id);
            return it == dims_by_id.end() ? std::vector<EcoList*>{} : it->second;
        };
        const std::vector<EcoList*> frm = dims_of(src_id), to = dims_of(dst_id);
        // One end outside the model has nothing to intersect with.
        if (frm.empty() || to.empty()) {
            const std::vector<EcoList*>& only = frm.empty() ? to : frm;
            return static_cast<double>(only.size()) == width ? only : std::vector<EcoList*>{};
        }
        std::vector<EcoList*> picks;
        for (EcoList* a : frm) {
            for (EcoList* b : to) {
                EcoList* narrower = nullptr;
                if (a->name == b->name) narrower = a;
                else if (a->sub_set_of && *a->sub_set_of == b->name) narrower = a;
                else if (b->sub_set_of && *b->sub_set_of == a->name) narrower = b;
                if (narrower && std::find(picks.begin(), picks.end(), narrower) == picks.end()) picks.push_back(narrower);
            }
        }
        if (static_cast<double>(picks.size()) == width) return picks;
        std::vector<std::string> an, bn;
        for (EcoList* l : frm) an.push_back(l->name);
        for (EcoList* l : to) bn.push_back(l->name);
        const std::string a_names = join(an, " \u00D7 "), b_names = join(bn, " \u00D7 ");
        warn("'" + original + "' is written over the indices its two ends have in common (" + (a_names.empty() ? "none" : a_names) +
             " and " + (b_names.empty() ? "none" : b_names) +
             "), which is a list Ecolego works out and does not write down. Neither end's dimension is a sub-set of the other's, so "
             "there is no list here that holds exactly those indices: '" +
             original + "' was read as the file spells it, and will need a dimension chosen by hand.");
        return {};
    }

    // <block-model>: every component and connection, as blocks of this tool's kinds or as entries
    // in the report.
    void read_blocks(const XmlNode* data_model, const IndexIds& index_ids, Hierarchy& hierarchy) {
        const XmlNode* model = child(data_model, "block-model");
        if (!model) {
            warn("The file has no <block-model>; nothing to import.");
            return;
        }
        std::vector<const XmlNode*> elements = children(model, "component");
        for (const XmlNode* c : children(model, "connection")) elements.push_back(c);

        std::unordered_set<std::string> declared(hierarchy.systems.begin(), hierarchy.systems.end());

        auto system_of_element = [&](const XmlNode* el) -> std::string {
            // A file that declares no hierarchy still says where its blocks live, so an
            // undeclared parent is taken at its word.
            const OptStr parent_id = child_text(el, "sub-system");
            if (!truthy(parent_id)) return "";
            auto hit = hierarchy.path_by_id.find(*parent_id);
            if (hit != hierarchy.path_by_id.end()) return hit->second;
            const std::vector<std::string> all_parts = split_on(*parent_id, '.');
            std::vector<std::string> mapped;
            for (std::size_t k = 0; k < all_parts.size(); k++) {
                const std::string key = join(std::vector<std::string>(all_parts.begin(), all_parts.begin() + static_cast<std::ptrdiff_t>(k + 1)), ".");
                const std::string system = join(std::vector<std::string>(all_parts.begin(), all_parts.begin() + static_cast<std::ptrdiff_t>(k)), ".");
                mapped.push_back(names.map(all_parts[k], "subsystem:" + key, system, "subsystem"));
            }
            const std::string path = join(mapped, ".");
            hierarchy.path_by_id[*parent_id] = path;
            if (!declared.count(path)) {
                declared.insert(path);
                if (!project.has("systems")) project.set("systems", Json::array());
                project["systems"].push(Json(path));
            }
            return path;
        };

        auto dim_lists_of = [&](const XmlNode* el) {
            std::vector<EcoList*> out;
            for (const std::string& p : split_on(attr_or(*el, "index-lists", ""), ',')) {
                const std::string s = js_trim(p);
                if (s.empty()) continue;
                auto it = index_ids.list_by_id.find(s);
                if (it != index_ids.list_by_id.end()) out.push_back(it->second);
            }
            return out;
        };

        std::unordered_map<std::string, std::vector<EcoList*>> dims_by_id;
        std::unordered_set<std::string> boundary_ids;
        std::unordered_map<std::string, std::string> system_by_id;
        OrderedMap<bool> disabled_ids;
        // The colour each block was given, by the qualified name it ends up with; put on the blocks
        // once they all exist. See `block_colour`.
        std::unordered_map<std::string, std::string> colours;

        // Pass one: block id -> qualified name, so connections can resolve their ends and
        // equations their qualified references.
        for (const XmlNode* el : elements) {
            const OptStr bid = child_text(el, "id");
            const OptStr type = attr(*el, "type");
            if (!truthy(bid)) continue;
            const OptStr guid = child_text(el, "guid");
            if (truthy(guid)) wiring_.id_by_guid[js_trim(*guid)] = *bid;
            const std::optional<bool> enabled = child_bool(el, "enabled");
            if (!(enabled ? *enabled : true)) disabled_ids[*bid] = true;
            if (is_boundary(type)) {
                boundary_ids.insert(*bid);
                continue;
            }
            if (!type || !is_supported(*type)) continue;
            dims_by_id[*bid] = dim_lists_of(el);
            const std::string system = system_of_element(el);
            system_by_id[*bid] = system;
            const std::string local = names.map(attr(*el, "name"), *bid, system, *bid);
            block_name_by_id_[*bid] = system.empty() ? local : system + "." + local;
        }

        const std::vector<std::string>& transports = hierarchy.transports;
        for (const XmlNode* el : elements) {
            const OptStr type = attr(*el, "type");
            const std::string original = attr_or(*el, "name", "(unnamed)");

            if (is_boundary(type)) continue;   // folded into the transfers that attach to it
            if (is_interface(type)) {
                // Read for its wiring, then dropped. A disabled one routes nothing.
                const OptStr cid = child_text(el, "id");
                if (cid && disabled_ids.has(*cid)) continue;
                if (*type == "connector") {
                    for (const XmlNode* link : children(el, "model-connection")) {
                        const std::string source = js_trim(attr_or(*link, "source", ""));
                        const std::string target = js_trim(attr_or(*link, "target", ""));
                        if (!(source.empty() || target.empty())) wiring_.links.push_back({source, target, original});
                    }
                } else {
                    for (const XmlNode* obj : children(el, "interface-object")) {
                        const std::string guid = js_trim(attr_or(*obj, "guid", ""));
                        if (guid.empty()) continue;
                        wiring_.exposed[guid] = true;
                        const std::string op = py_upper(js_trim(attr_or(*obj, "operation", "")));
                        if (!op.empty()) wiring_.operations[guid] = op;
                    }
                }
                continue;
            }
            if (type && *type == "influence") {
                note(*type, original);
                continue;
            }
            if (!type || !is_supported(*type)) {
                skip(type ? *type : std::string("unknown"), Json(original), "this tool has no equivalent block type");
                continue;
            }
            const std::string& type_ = *type;

            const OptStr bid = child_text(el, "id");
            std::string system;
            {
                auto it = bid ? system_by_id.find(*bid) : system_by_id.end();
                system = it != system_by_id.end() ? it->second : system_of_element(el);
            }
            std::string qualified_name;
            {
                const std::string* q = bid ? block_name_by_id_.find(*bid) : nullptr;
                qualified_name = q ? *q : names.map(original, bid ? *bid : original, system, "block");
            }
            // Blocks carry their own local name and the sub-system holding them.
            const std::string name = (!system.empty() && qualified_name.compare(0, system.size() + 1, system + ".") == 0)
                                         ? qualified_name.substr(system.size() + 1)
                                         : qualified_name;
            if (const OptStr colour = block_colour(el, type_)) colours[system.empty() ? name : system + "." + name] = *colour;
            // Dimension lists in declared order, for resolving entry ids -- and, where the file
            // names none but says there is one, the list that stands for the intersection of a
            // transfer's two ends.
            std::vector<EcoList*> dim_lists = dim_lists_of(el);
            if (dim_lists.empty()) dim_lists = intersection_dims(el, original, dims_by_id);
            Json dims = Json::array();
            for (EcoList* l : dim_lists)
                if (!l->name.empty()) dims.push(Json(l->name));
            // A block with no index lists is scalar and says so.
            const std::pair<std::string, Json> dim_spec = dims.empty() ? std::pair<std::string, Json>{"per_nuclide", Json(false)}
                                                                       : std::pair<std::string, Json>{"index_lists", dims};
            const std::string unit = or_str(child_text(el, "unit"));
            // A block's comment is its `comment` property, as Ecolego 6 writes it; a `<comment>`
            // element where there is none.
            OptStr comment_ = property_text(*el, "comment");
            const std::string comment = comment_ ? *comment_ : or_str(child_text(el, "comment"));
            std::vector<Json> entries = read_entries(el, dim_lists, original);

            if (type_ == "general-variable" || type_ == "select") {
                // The pick is the entry's equation; the oldest spelling gives it, and the list, by
                // GUID instead. A pick nobody made reads 0.
                auto by_guid = [&](const XmlNode* node) -> OptStr {
                    if (!node) return std::nullopt;
                    auto it = wiring_.id_by_guid.find(js_trim(attr_or(*node, "guid", "")));
                    if (it == wiring_.id_by_guid.end()) return std::nullopt;
                    return it->second;
                };
                const Json chosen = pick_default(entries, "equation");
                const OptStr from_guid = by_guid(find(*el, "selected-object-guid"));
                const OptStr picked = !chosen.is_null() ? OptStr(str(chosen)) : from_guid;
                std::vector<std::string> offered;
                walk(*el, [&](const XmlNode& node) {
                    OptStr oid;
                    if (*node.name == "available-object") {
                        if (has_attr(node, "id")) oid = js_trim(*attr(node, "id"));
                    } else if (*node.name == "available-object-guid") {
                        oid = by_guid(&node);
                    }
                    if (truthy(oid) && !contains(offered, *oid)) offered.push_back(*oid);
                    return false;
                });
                Json block = trim_empty({{"name", Json(name)},
                                         {"system", Json(system)},
                                         dim_spec,
                                         // Ecolego shows the chosen block's unit as this one's and
                                         // writes a copy of it, which stands until the block is found.
                                         {"unit", !unit.empty() ? Json(unit) : or_json(pick_default(entries, "unit"), Json(""))},
                                         {"comment", Json(comment)},
                                         {"equation", Json(picked ? *picked : std::string("0"))},
                                         {"entries", keep_indexed(entries, {"equation"})}});
                project["expressions"].push(block);
                generals_.push_back({block, picked.has_value(), offered});
                continue;
            }

            const bool is_expression = type_ == "expression" || type_ == "post-processing" || type_ == "constant" || type_ == "transport-number";
            const OptStr role = transport_role(type_);
            // A part of a transport outside a transport sub-system is a part of nothing: a file
            // edited by hand.
            if (role && !contains(transports, system)) {
                skip(type_, Json(original), "it is a part of a transport, and is not inside one");
                continue;
            }
            auto with_role = [&](Pairs p) {
                if (role) p.emplace_back("transport", Json(*role));
                return p;
            };

            if (type_ == "compartment" || (role && (*role == "begin" || *role == "end"))) {
                readable_tolerances(entries, original);
                Pairs pairs = with_role({{"name", Json(name)}, {"system", Json(system)}, dim_spec, {"unit", Json(unit)}, {"comment", Json(comment)}});
                const std::optional<bool> handle_decay = child_bool(el, "handle-decay");
                pairs.emplace_back("handle_decay", Json(handle_decay ? *handle_decay : true));
                pairs.emplace_back("initial", or_json(pick_default(entries, "initial"), Json("0")));
                pairs.emplace_back("abstol", pick_default(entries, "abstol"));
                pairs.emplace_back("dydt", pick_default(entries, "dydt"));
                pairs.emplace_back("non_negative", Json(read_non_negative(entries, original)));
                pairs.emplace_back("entries", keep_indexed(entries, {"initial", "abstol", "dydt"}));
                Json compartment = trim_empty(pairs);
                // An empty <unit> is a compartment that has none, as the export writes one; no
                // <unit> at all is the Bq an Ecolego file means.
                if (unit.empty() && child(el, "unit")) compartment.set("unit", Json(""));
                project["compartments"].push(compartment);
            } else if (role && *role == "counter") {
                project["expressions"].push(trim_empty({{"name", Json(name)},
                                                        {"system", Json(system)},
                                                        dim_spec,
                                                        {"unit", Json("")},
                                                        {"comment", Json(comment)},
                                                        {"transport", Json("counter")},
                                                        {"equation", Json("1")}}));
            } else if (role && *role == "operation") {
                // How it is read follows from how many arguments it declares.
                const std::size_t args = children(el, "argument").size();
                const OptStr operation = child_text(el, "operation");
                project["expressions"].push(trim_empty({{"name", Json(name)},
                                                        {"system", Json(system)},
                                                        dim_spec,
                                                        {"unit", Json(unit)},
                                                        {"comment", Json(comment)},
                                                        {"transport", Json("operation")},
                                                        {"operation", Json(operation ? *operation : std::string("MEAN"))},
                                                        {"argument", Json(args >= 2 ? "range" : args == 1 ? "point" : "all")}}));
            } else if (is_expression) {
                if (!(type_ == "expression" || type_ == "transport-number")) {
                    warn("'" + original + "' is a " + type_ +
                         " expression; this tool evaluates every expression at each step, which is equivalent unless it depended on "
                         "the evaluation order.");
                }
                // An expression with `<argument>` elements is a function: called with those values
                // rather than read.
                std::vector<std::string> arg_names;
                for (const XmlNode* x : children(el, "argument")) {
                    OptStr a = child_text(x, "argument-key");
                    if (!a) a = child_text(x, "argument-name");
                    if (truthy(a)) arg_names.push_back(*a);
                }
                if (!arg_names.empty() && !role) {
                    std::vector<std::string> parameters;
                    for (const std::string& a : arg_names) parameters.push_back(safe_parameter(a, parameters));
                    const Json per_index = keep_indexed(entries, {"equation"});
                    if (!per_index.empty()) {
                        warn("'" + original + "' is a function of " + join(parameters, ", ") + " with " + itos(static_cast<long long>(per_index.size())) +
                             " equation(s) set per index. A function is worked out where it is called, at the caller's index, so only its "
                             "default equation came across.");
                    }
                    project["functions"].push(trim_empty({{"name", Json(name)},
                                                          {"system", Json(system)},
                                                          {"unit", Json(unit)},
                                                          {"comment", Json(comment)},
                                                          {"parameters", Json::array(parameters)},
                                                          {"equation", or_json(pick_default(entries, "equation"), Json(""))}}));
                    continue;
                }
                Pairs pairs = with_role({{"name", Json(name)}, {"system", Json(system)}, dim_spec, {"unit", Json(unit)}, {"comment", Json(comment)}});
                pairs.emplace_back("equation", or_json(pick_default(entries, "equation"), Json("0")));
                pairs.emplace_back("entries", keep_indexed(entries, {"equation"}));
                project["expressions"].push(trim_empty(pairs));
            } else if (type_ == "lookup-table") {
                // An <argument> makes the table a function of what the caller passes, instead of a
                // series read at the clock.
                const XmlNode* arg_el = child(el, "argument");
                OptStr argument;
                if (arg_el) {
                    argument = child_text(arg_el, "argument-key");
                    if (!truthy(argument)) argument = child_text(arg_el, "argument-name");
                    if (!truthy(argument)) argument = std::string("X");
                }
                const OptStr option = child_text(el, "lookup-option");
                const Json interpolation = value_of(interpolation_from_eco(option));
                if (truthy(option) && !truthy(interpolation)) {
                    warn("'" + original + "' uses the interpolation rule '" + *option +
                         "', which this tool does not know; straight lines between the points were used.");
                }
                const std::optional<bool> cyclic = child_bool(el, "lookup-cyclic");
                Pairs pairs = {{"name", Json(name)},
                               {"system", Json(system)},
                               dim_spec,
                               {"unit", Json(unit)},
                               {"comment", Json(comment)},
                               {"interpolation", or_json(interpolation, Json("linear"))},
                               {"cyclic", Json(cyclic ? *cyclic : false)}};
                if (truthy(argument)) pairs.emplace_back("argument", Json(*argument));
                pairs.emplace_back("points", or_json(pick_default(entries, "points"), Json::array()));
                pairs.emplace_back("entries", keep_indexed(entries, {"points"}));
                project["lookups"].push(trim_empty(pairs));
            } else if (type_ == "index-operation" || type_ == "aggregate") {
                // The target is the block's own equation: one id for an index operation, ids
                // joined with `+` for an aggregate.
                const Json spec = or_json(pick_default(entries, "equation"), Json(""));
                const OptStr raw_op = child_text(el, "operation");
                const OptStr operation = operation_from_eco(raw_op);
                if (truthy(raw_op) && !truthy(operation)) {
                    warn("'" + original + "' reduces with '" + *raw_op + "', which this tool does not know; it was summed instead.");
                }
                Pairs common = {{"name", Json(name)},
                                {"system", Json(system)},
                                dim_spec,
                                {"unit", Json(unit)},
                                {"comment", Json(comment)},
                                {"operation", Json(operation ? *operation : std::string("sum"))}};
                if (type_ == "index-operation") {
                    // Only when it is actually there: Number(null) is 0, which would look like a
                    // stated percentile of zero.
                    const OptStr stated = property_text(*el, "percentile");
                    std::optional<double> pct = child_number(el, "percentile");
                    if (!pct) {
                        if (stated && !stated->empty()) pct = to_number(std::string_view(*stated));
                    }
                    const std::string trimmed = js_trim(str(spec));
                    common.emplace_back("target", trimmed.empty() ? Json() : Json(trimmed));
                    if (pct && std::isfinite(*pct)) common.emplace_back("percentile", Json(*pct));
                    Json per = Json::array();
                    const Json indexed = keep_indexed(entries, {"equation"});
                    for (const Json& e : indexed.arr())
                        per.push(Json::object({{"index", e.get("index")}, {"target", Json(js_trim(js_string(e.get("equation"))))}}));
                    common.emplace_back("entries", per);
                    project["index_reductions"].push(trim_empty(common));
                } else {
                    common.emplace_back("targets", split_targets(spec));
                    Json per = Json::array();
                    const Json indexed = keep_indexed(entries, {"equation"});
                    for (const Json& e : indexed.arr())
                        per.push(Json::object({{"index", e.get("index")}, {"targets", split_targets(e.get("equation"))}}));
                    common.emplace_back("entries", per);
                    project["block_reductions"].push(trim_empty(common));
                }
            } else if (kind_from_eco(type_)) {
                // The blocks that remember, and the events that drive them.
                const std::string kind = *kind_from_eco(type_);
                std::vector<std::string> ks = equation_fields(kind);
                for (const std::string& f : event_fields(kind)) ks.push_back(f);
                Pairs common = {{"name", Json(name)}, {"system", Json(system)}, dim_spec, {"unit", Json(unit)}, {"comment", Json(comment)}};
                auto pick = [&](const char* key, const Json& fallback) { return or_json(pick_default(entries, key), fallback); };
                const Json per_index = keep_indexed(entries, ks);
                if (kind == "min_max") {
                    const OptStr raw_op = child_text(el, "operation");
                    const OptStr op = extreme_from_eco(raw_op);
                    if (truthy(raw_op) && !truthy(op)) {
                        warn("'" + original + "' records '" + *raw_op + "', which this tool does not know; its maximum was recorded instead.");
                    }
                    common.emplace_back("operation", Json(op ? *op : std::string("max")));
                    common.emplace_back("target", pick("target", Json("0")));
                    common.emplace_back("reset_trigger", pick("reset_trigger", Json()));
                    common.emplace_back("start_trigger", pick("start_trigger", Json()));
                    common.emplace_back("stop_trigger", pick("stop_trigger", Json()));
                    common.emplace_back("entries", per_index);
                    project["min_maxes"].push(trim_empty(common));
                } else if (kind == "running_mean") {
                    common.emplace_back("target", pick("target", Json("0")));
                    common.emplace_back("reset_trigger", pick("reset_trigger", Json()));
                    common.emplace_back("start_trigger", pick("start_trigger", Json()));
                    common.emplace_back("stop_trigger", pick("stop_trigger", Json()));
                    common.emplace_back("entries", per_index);
                    project["running_means"].push(trim_empty(common));
                } else if (kind == "snapshot") {
                    common.emplace_back("target", pick("target", Json("0")));
                    common.emplace_back("trigger", pick("trigger", Json()));
                    common.emplace_back("initial", pick("initial", Json("0")));
                    common.emplace_back("entries", per_index);
                    project["snapshots"].push(trim_empty(common));
                } else if (kind == "delay") {
                    common.emplace_back("target", pick("target", Json("0")));
                    common.emplace_back("delay", pick("delay", Json("0")));
                    common.emplace_back("entries", per_index);
                    project["delays"].push(trim_empty(common));
                } else {
                    common.emplace_back("first", pick("first", Json("0")));
                    common.emplace_back("second", pick("second", Json("0")));
                    common.emplace_back("direction", pick("direction", Json("rising")));
                    common.emplace_back("entries", per_index);
                    project["triggers"].push(trim_empty(common));
                }
            } else if (type_ == "parameter") {
                // Only what could not be read is worth saying; a distribution that arrived intact
                // is on the parameter.
                long long unread = 0;
                for (const Json& e : entries)
                    if (truthy(e.get("pdf_unread"))) unread++;
                if (unread != 0) {
                    const std::string what = unread == 1 ? "a probability distribution" : itos(unread) + " probability distributions";
                    warn("'" + original + "' has " + what + " this tool could not read; the constant value is used for " +
                         (unread == 1 ? "it" : "them") + ".");
                }
                project["parameters"].push(trim_empty({{"name", Json(name)},
                                                       {"system", Json(system)},
                                                       dim_spec,
                                                       {"unit", Json(unit)},
                                                       {"comment", Json(comment)},
                                                       {"value", or_json(pick_default(entries, "value"), Json(0))},
                                                       {"pdf", pick_default(entries, "pdf")},
                                                       {"entries", keep_indexed(entries, {"value", "pdf"})}}));
            } else if (type_ == "transfer" || type_ == "transfer-coefficient") {
                auto resolve_end = [&](const OptStr& id_attr, const char* which) -> OptStr {
                    if (!truthy(id_attr)) return std::nullopt;
                    if (boundary_ids.count(*id_attr)) return std::nullopt;
                    const std::string* end_ = block_name_by_id_.find(*id_attr);
                    if (!end_ || end_->empty()) {
                        warn("Transfer '" + original + "' " + which + " a block that was not imported; that end was left open.");
                        return std::nullopt;
                    }
                    return *end_;
                };
                const OptStr frm = resolve_end(attr(*el, "source"), "starts at");
                const OptStr to = resolve_end(attr(*el, "target"), "ends at");
                if (!frm && !to) {
                    skip(type_, Json(original), "neither endpoint is a compartment in this model");
                    continue;
                }
                // Per the file format; the default row's own value still wins. A transfer with no
                // donor cannot be multiplied by one.
                bool donor = false;
                if (frm) {
                    const Json d = pick_default(entries, "multiply_by_donor");
                    donor = d.is_null() ? (type_ == "transfer-coefficient") : d.as_bool();
                }
                const Json rate = or_json(pick_default(entries, "rate"), Json("0"));

                // A discrete transfer is not a rate: it goes through the renames as a transfer that
                // carries its event, and becomes an event of this tool's at the end.
                const bool discrete = std::any_of(entries.begin(), entries.end(), [](const Json& e) { return !e.get("transfer_event").is_null(); });
                if (discrete) {
                    project["transfers"].push(trim_empty({{"name", Json(name)},
                                                          {"system", Json(system)},
                                                          dim_spec,
                                                          {"unit", Json(unit)},
                                                          {"comment", Json(comment)},
                                                          {"from", J(frm)},
                                                          {"to", J(to)},
                                                          {"rate", rate},
                                                          {"multiply_by_donor", Json(donor)},
                                                          {"transfer_event", pick_default(entries, "transfer_event")},
                                                          {"entries", keep_indexed(entries, {"rate", "multiply_by_donor", "transfer_event"})}}));
                    continue;
                }

                // Ecolego keeps the flag row by row, and here it is one setting of the transfer.
                // Rows that say otherwise become a second transfer between the same two ends, and
                // the first moves nothing there.
                std::vector<Json> other;
                if (frm) {
                    for (const Json& e : entries)
                        if (!e.get("index").empty() && e.has("multiply_by_donor") && e.get("multiply_by_donor") != Json(donor)) other.push_back(e);
                }
                std::vector<Json> rows;
                for (const Json& e : entries) {
                    const bool moved = std::any_of(other.begin(), other.end(), [&](const Json& o) { return o.same(e); });
                    if (moved) {
                        Json copy = e.shallow();
                        copy.set("rate", Json("0"));
                        rows.push_back(copy);
                    } else {
                        rows.push_back(e);
                    }
                }
                project["transfers"].push(trim_empty({{"name", Json(name)},
                                                      {"system", Json(system)},
                                                      dim_spec,
                                                      {"unit", Json(unit)},
                                                      {"comment", Json(comment)},
                                                      {"from", J(frm)},
                                                      {"to", J(to)},
                                                      {"rate", rate},
                                                      {"multiply_by_donor", Json(donor)},
                                                      {"entries", keep_indexed(rows, {"rate"})}}));
                if (!other.empty()) {
                    const std::string twin = names.claim(name + "_" + (donor ? "absolute" : "by_donor"), system);
                    twins_[system.empty() ? name : system + "." + name] = system.empty() ? twin : system + "." + twin;
                    Json per = Json::array();
                    for (const Json& e : other) per.push(Json::object({{"index", e.get("index")}, {"rate", or_json(e.get("rate"), rate)}}));
                    project["transfers"].push(trim_empty({{"name", Json(twin)},
                                                          {"system", Json(system)},
                                                          dim_spec,
                                                          {"from", J(frm)},
                                                          {"to", J(to)},
                                                          {"rate", Json("0")},
                                                          {"multiply_by_donor", Json(!donor)},
                                                          {"entries", per}}));
                    std::vector<std::string> where_parts;
                    for (std::size_t k = 0; k < std::min<std::size_t>(3, other.size()); k++) {
                        std::vector<std::string> vals;
                        for (const auto& [lk, lv] : other[k].get("index").obj()) vals.push_back(str(lv));
                        where_parts.push_back(join(vals, ", "));
                    }
                    const std::string where_ = join(where_parts, "; ");
                    const std::string more = other.size() > 3 ? "; " + itos(static_cast<long long>(other.size()) - 3) + " more" : "";
                    warn("'" + original + "' " + (donor ? "multiplies by its donor" : "is an absolute flux") + " at some indices and not at others (" +
                         where_ + more + "), which is one setting of a whole transfer here. Those indices are '" + twin + "', " +
                         (donor ? "an absolute flux" : "multiplied by the donor") + ", beside '" + name +
                         "', which moves nothing there; the two move what the file's transfer moves, and a block that reads '" + name +
                         "' reads zero at those indices.");
                }
            }
        }

        // The blocks the file switches off, now that they exist. A block inside a sub-system the
        // file switches off keeps its own switch; the report counts what each such sub-system holds.
        std::unordered_set<std::string> off_names;
        for (const auto& [i, _] : disabled_ids.items) {
            const std::string* q = block_name_by_id_.find(i);
            if (q && !q->empty()) off_names.insert(*q);
        }
        for (const auto& [whole, twin] : twins_.items)
            if (off_names.count(whole)) off_names.insert(twin);
        const std::vector<std::string>& off_paths = hierarchy.disabled_paths;
        auto in_off_system = [&](const std::string& system) -> OptStr {
            for (const std::string& p : off_paths)
                if (system == p || system.compare(0, p.size() + 1, p + ".") == 0) return p;
            return std::nullopt;
        };
        if (!off_names.empty() || !off_paths.empty()) {
            for (const char* collection : {"compartments", "expressions", "transfers", "parameters", "inflows", "lookups", "index_reductions",
                                           "block_reductions", "min_maxes", "running_means", "snapshots", "delays", "triggers"}) {
                for (Json block : list_of(project, collection)) {
                    const std::string qname = qualified(block);
                    const OptStr via = truthy(block.get("system")) ? in_off_system(str(block.get("system"))) : std::nullopt;
                    if (truthy(via)) in_disabled_system(*via);
                    if (!off_names.count(qname)) continue;
                    block.set("enabled", Json(false));
                    report.disabled.push_back(qname);
                }
            }
        }

        // The colours, by qualified name as the switches are. The second half of a transfer made in
        // two is the colour of the first.
        for (const auto& [whole, twin] : twins_.items) {
            auto it = colours.find(whole);
            if (it == colours.end()) continue;
            const std::string colour = it->second;
            colours[twin] = colour;
        }
        if (!colours.empty()) {
            for (const char* collection : {"compartments", "expressions", "transfers", "parameters", "functions", "lookups",
                                           "index_reductions", "block_reductions", "min_maxes", "running_means", "snapshots",
                                           "delays", "triggers"}) {
                for (Json block : list_of(project, collection)) {
                    auto it = colours.find(qualified(block));
                    if (it != colours.end()) block.set("color", Json(it->second));
                }
            }
        }
    }

    // --- simulation settings -------------------------------------------------------------------

    // The <time-series> children of one list, as this tool's own series.
    std::vector<Json> read_time_series(const XmlNode* host, Json& sim) {
        std::vector<Json> out;
        if (!host) return out;
        for (const XmlNode* el : children(host, "time-series")) {
            const std::string type = py_lower(attr_or(*el, "type", ""));
            if (type == "custom") {
                // `[1000.0, 2000.0]`; the empty tokens go before they are read as numbers, or `[]`
                // would be the single time zero.
                std::string text;
                for (char c : or_str(child_text(el, "values")))
                    if (c != '[' && c != ']') text.push_back(c);
                std::vector<double> times;
                for (const std::string& t : split_times(text)) {
                    const double v = to_number(std::string_view(t));
                    if (std::isfinite(v)) times.push_back(v);
                }
                if (!times.empty()) {
                    std::stable_sort(times.begin(), times.end(), [](double a, double b) { return a < b; });
                    Json ts = Json::array();
                    for (double t : times) ts.push(Json(t));
                    out.push_back(Json::object({{"kind", Json("times")}, {"times", ts}}));
                }
                continue;
            }
            // Either end may be Ecolego's AUTO, "follow the simulation", which is what this tool's
            // series mean by an empty end.
            const std::optional<double> frm = auto_number(el, "time-series-start-time");
            const std::optional<double> to = auto_number(el, "time-series-end-time");
            const std::string kind = type == "geometric" ? "log" : "linear";
            std::optional<double> points = child_number(el, "n");
            if (!points) {
                // An incrementing series says how far apart its points are.
                const std::optional<double> step = child_number(el, "increment");
                const double a = frm ? *frm : sim.get("start_time").as_double();
                const double b = to ? *to : sim.get("end_time").as_double();
                if (step && *step > 0 && b > a) {
                    points = js_floor((b - a) / *step) + 1;
                    if (std::fabs((b - a) / *step - js_round((b - a) / *step)) > 1e-9) {
                        warn("An output series steps by " + js_string(*step) + " from " + js_string(a) + " to " + js_string(b) +
                             ", which does not divide evenly; " + js_string(*points) + " points were used.");
                    }
                }
            }
            if (!points || !(*points >= 2)) {
                warn("An output series had no usable number of points and was dropped.");
                continue;
            }
            out.push_back(Json::object({{"kind", Json(kind)},
                                        {"points", Json(js_round(*points))},
                                        {"from", frm ? Json(*frm) : Json()},
                                        {"to", to ? Json(*to) : Json()}}));
        }
        return out;
    }

    // When Ecolego saves results and on what times: <output-options>, overridden by <batch-mode>,
    // and the series in <time-series-list> and <discrete-times>.
    void read_output_times(const XmlNode* s, Json& sim) {
        const std::string written = js_trim(or_str(child_text(s, "output-options")));
        OptStr mode = output_mode(py_lower(written));
        if (!mode) mode = output_mode(js_string(to_number(std::string_view(written))));

        std::vector<Json> series = read_time_series(child(s, "time-series-list"), sim);
        for (const Json& x : read_time_series(child(s, "discrete-times"), sim)) series.push_back(x);
        if (!series.empty()) {
            Json all = Json::array();
            for (const Json& x : series) all.push(x);
            sim.set("output_times", all);
        }

        // Batch mode reports on the specified times whatever the option says.
        const bool batch = py_lower(js_trim(or_str(child_text(s, "batch-mode")))) == "true";
        const OptStr wanted = batch ? OptStr("series") : mode;
        if (!truthy(wanted)) return;
        if (*wanted == "solver") {
            sim.set("spacing", Json("solver"));
            return;
        }
        if (series.empty()) {
            warn("The file asks for output on specified times but lists none; " + js_string(sim.get("output_points")) +
                 " logarithmic points were used instead.");
            return;
        }
        sim.set("spacing", Json(*wanted));
    }

    // Which blocks the model is set up to save: <outputs><output id>, as block ids until named.
    static void read_endpoints(const XmlNode* s, Json& sim) {
        const XmlNode* lst = child(s, "outputs");
        if (!lst) return;
        Json ids = Json::array();
        for (const XmlNode* o : children(lst, "output")) {
            const OptStr i = attr(*o, "id");
            if (i && !i->empty()) ids.push(Json(*i));
        }
        if (!ids.empty()) sim.set("endpoints", ids);
    }

    // <simulation-settings> and <probabilistic-settings>: the time span and unit, the solver and
    // tolerances, the saturation switch, the output times, the endpoints, and what a
    // probabilistic run would do. A file with none takes this tool's defaults.
    void read_simulation_settings(const XmlNode* data_model) {
        const XmlNode* s = child(data_model, "simulation-settings");
        Json sim = simulation_defaults();
        if (!s) {
            project.set("simulation", sim);
            warn("No simulation settings in the file; defaults were used.");
            return;
        }

        const std::optional<double> start = child_number(s, "start-time");
        const std::optional<double> end_ = child_number(s, "end-time");
        if (start) sim.set("start_time", Json(*start));
        if (end_) sim.set("end_time", Json(*end_));
        if (!(sim.get("end_time").as_double() > sim.get("start_time").as_double())) {
            sim.set("start_time", Json(0));
            sim.set("end_time", Json(std::max(1.0, end_ ? *end_ : 1e5)));
            warn("The stored time span was not usable; it was reset.");
        }

        // Ecolego's master switch over every compartment's bounds, mapped onto the floor, which is
        // the part of it there is.
        const OptStr saturation = child_text(s, "saturation-enabled");
        if (saturation && ascii_ieq(js_trim(*saturation), "false")) {
            sim.set("non_negative", Json(false));
            warn("Saturation is switched off in this model, so no compartment is held at zero -- which is how Ecolego runs it. Each "
                 "compartment keeps its own *cannot go negative* setting; none of them is consulted while the switch is off. Turn it "
                 "back on under Simulation if you want the floor.");
        }

        const XmlNode* prob = child(data_model, "probabilistic-settings");
        if (prob) {
            const double n = to_number(child_text(prob, "no-simulations"));
            if (std::isfinite(n) && n > 0) sim.set("iterations", Json(js_round(n)));
            // With no <seed>, `Number(null)` is 0, a seed.
            const double seed = to_number(child_text(prob, "seed"));
            if (std::isfinite(seed)) sim.set("seed", Json(js_round(seed)));
            const std::string how = py_lower(or_str(child_text(prob, "sampling")));
            if (!how.empty()) sim.set("sampling", Json(how.find("latin") != std::string::npos ? "latin" : "random"));
            Json chosen = Json::array();
            for (const XmlNode* n2 : children(child(prob, "probabilistic-parameters"), "selected-parameter")) {
                std::string t = js_trim(text(*n2));
                if (!t.empty()) chosen.push(Json(t));
            }
            if (!chosen.empty()) sim.set("varied", chosen);
            const std::size_t pairs = children(child(prob, "correlation-matrix"), "correlation-pair").size();
            const OptStr enabled = child_text(prob, "correlation-enabled");
            if (pairs != 0 && !(enabled && *enabled == "false")) {
                warn("The model correlates " + itos(static_cast<long long>(pairs)) +
                     " pair(s) of parameters when it samples them. This tool samples each one independently, so a probabilistic run "
                     "here spreads wider than Ecolego's would.");
            }
        }

        const std::string unit = py_lower(or_str(child_text(s, "time-unit")));
        const OptStr known_unit = time_unit_of(unit);
        if (truthy(known_unit)) sim.set("time_unit", Json(*known_unit));
        else if (!unit.empty()) warn("Unrecognised time unit '" + unit + "'; years were assumed.");

        const std::string said = js_trim(or_str(child_text(s, "java-solver")));
        const std::string solver = solver_key(said);
        const OptStr mapped = solver_of(solver);
        if (truthy(mapped)) {
            sim.set("solver", Json(*mapped));
            if (solver == "ODE15SBDF") sim.set("bdf", Json(true));
            if (!solver_exact(solver)) {
                warn("The model used the " + solver + " solver, which this tool does not have; " + solver_name(sim.get("solver")) +
                     " was chosen as the closest.");
            }
        } else if (!said.empty()) {
            warn("The model names a solver this tool does not know, '" + said + "'; " + solver_name(sim.get("solver")) + " was used.");
        }

        const std::optional<double> rtol = child_number(s, "rel-error-tolerance");
        const std::optional<double> atol = child_number(s, "abs-error-tolerance");
        if (rtol && *rtol > 0) sim.set("rtol", Json(*rtol));
        if (atol && *atol > 0) sim.set("abstol", Json(*atol));

        if (sim.get("start_time").as_double() < 0) {
            sim.set("spacing", Json("linear"));
            warn("The simulation starts before zero, so linear output spacing was used (logarithmic time needs a non-negative start).");
        }

        read_output_times(s, sim);
        read_endpoints(s, sim);

        const std::string type = py_upper(or_str(child_text(s, "simulation-type")));
        if (!type.empty() && type != "DETERMINISTIC") {
            warn("The model is set up for a " + py_lower(type) + " simulation; this tool runs the deterministic case only.");
        }

        project.set("simulation", sim);
    }

    // --- the textual rewrite -------------------------------------------------------------------

    // Substitutes renamed blocks throughout every equation. Textual rather than token-based,
    // because the original names are exactly the ones the tokenizer cannot handle -- `Deep soil`
    // is three tokens. Qualified ids first and longest names first, and a match only counts when
    // it is not butted up against another name character (`.` included).
    void rewrite_renamed_references() {
        std::vector<std::pair<std::string, std::string>> candidates_in;
        for (const auto& [bid, to] : block_name_by_id_.items)
            if (bid != to) candidates_in.emplace_back(bid, to);
        const std::vector<std::string> dup = names.duplicated();
        const std::set<std::string> ambiguous(dup.begin(), dup.end());
        for (const auto& [frm, to] : names.by_original.items)
            if (frm != to && !ambiguous.count(frm)) candidates_in.emplace_back(frm, to);

        std::set<std::pair<std::string, std::string>> seen;
        std::vector<std::pair<std::string, std::string>> pairs;
        for (const auto& p : candidates_in) {
            // An empty `from` is found at every position, and one with no name character in it is
            // not a name anything could have referred to.
            if (p.first.empty() || p.first == p.second || !has_ident_char(p.first)) continue;
            if (seen.count(p)) continue;
            seen.insert(p);
            pairs.push_back(p);
        }
        std::stable_sort(pairs.begin(), pairs.end(), [](const auto& a, const auto& b) { return js_len(a.first) > js_len(b.first); });
        if (pairs.empty()) return;

        long long touched = 0;
        OrderedMap<std::string> fired;
        const Candidates candidates(pairs);

        std::function<Json(const Json&)> rewrite = [&](const Json& text) -> Json {
            if (text.is_array()) {
                Json out = Json::array();
                for (const Json& t : text.arr()) out.push(rewrite(t));
                return out;
            }
            if (!text.is_string() || text.as_string().empty()) return text;
            const std::string& original = text.as_string();
            std::string out = original;
            for (std::size_t j : candidates.of(original)) {
                const std::string& frm = pairs[j].first;
                const std::string& to = pairs[j].second;
                std::size_t at = 0;
                while (true) {
                    const std::size_t i = at > out.size() ? std::string::npos : out.find(frm, at);
                    if (i == std::string::npos) break;
                    const std::size_t stop = i + frm.size();   // the byte after the match
                    const bool before_ok = i == 0 || !is_name_part(static_cast<unsigned char>(out[i - 1]));
                    const bool after_ok = stop >= out.size() || !is_name_part(static_cast<unsigned char>(out[stop]));
                    if (before_ok && after_ok) {
                        out = out.substr(0, i) + to + out.substr(stop);
                        at = i + to.size();
                        fired[frm] = to;
                    } else {
                        at = stop;
                    }
                }
            }
            if (out != original) touched++;
            return Json(out);
        };

        const std::vector<std::pair<const char*, std::vector<const char*>>> collections_ = {
            {"compartments", {"initial"}},
            {"transfers", {"rate"}},
            {"inflows", {"rate"}},
            {"expressions", {"equation"}},
            // A function's body is an equation, and a call of one is a reference.
            {"functions", {"equation"}},
            // A reducing block names its targets rather than writing an equation, but they are
            // references like any other.
            {"index_reductions", {"target"}},
            {"block_reductions", {"targets"}},
            // A block that remembers names its target, and its event fields name a discrete event.
            {"min_maxes", {"target", "reset_trigger", "start_trigger", "stop_trigger"}},
            {"running_means", {"target", "reset_trigger", "start_trigger", "stop_trigger"}},
            {"snapshots", {"target", "trigger", "initial"}},
            {"delays", {"target", "delay"}},
            {"triggers", {"first", "second"}},
        };
        for (const auto& [collection, ks] : collections_) {
            for (Json block : list_of(project, collection)) {
                for (const char* k : ks)
                    if (block.has(k)) block.set(k, rewrite(block.get(k)));
                for (Json entry : list_of(block, "entries"))
                    for (const char* k : ks)
                        if (entry.has(k)) entry.set(k, rewrite(entry.get(k)));
            }
        }
        // A discrete transfer's event is a reference too, until it is settled into an event.
        for (Json t : list_of(project, "transfers")) {
            if (!t.get("transfer_event").is_null()) t.set("transfer_event", rewrite(t.get("transfer_event")));
            for (Json entry : list_of(t, "entries"))
                if (!entry.get("transfer_event").is_null()) entry.set("transfer_event", rewrite(entry.get("transfer_event")));
        }

        if (touched != 0) {
            warn("Rewrote " + itos(touched) +
                 " equation(s) to use this tool's block names, including sub-system-qualified references. The substitution is textual, "
                 "because the original names are not valid identifiers -- check the results.");
            // A name with an operator in it is also an expression: `A-B` turned every `A - B` in
            // the model into a reference to `A_B`.
            std::vector<std::pair<std::string, std::string>> risky;
            for (const auto& [frm, to] : fired.items)
                if (has_operator_char(frm)) risky.emplace_back(frm, to);
            if (!risky.empty()) {
                std::vector<std::string> shown;
                for (std::size_t k = 0; k < std::min<std::size_t>(6, risky.size()); k++)
                    shown.push_back("'" + risky[k].first + "' \u2192 '" + risky[k].second + "'");
                warn(itos(static_cast<long long>(risky.size())) + " of those names contain" + (risky.size() == 1 ? "s" : "") +
                     " operator or bracket characters (" + join(shown, ", ") + (risky.size() > 6 ? ", \u2026" : "") +
                     "). Every occurrence of the text in an equation was read as the block -- including where it was written as "
                     "arithmetic between two other blocks. Check those equations by hand.");
            }
        }
    }

    // Drops a reduction whose target was never imported, and lists it in the report; an
    // aggregate that lost only some of its targets keeps the rest, with a warning.
    void drop_unreachable_targets() {
        std::unordered_set<std::string> known;
        for (const char* kind : {"parameters", "compartments", "expressions", "transfers", "inflows", "lookups", "index_reductions",
                                 "block_reductions", "functions", "min_maxes", "running_means", "snapshots", "delays", "triggers"})
            for (const Json& b : list_of(project, kind)) known.insert(qualified(b));
        auto resolve = [&](const std::string& ref, const std::string& system) {
            return resolve_reference(ref, system, [&](const std::string& q) { return known.count(q) != 0; });
        };
        auto or_empty = [](const Json& s) { return truthy(s) ? str(s) : std::string(); };

        Json kept_reductions = Json::array();
        for (const Json& o : list_of(project, "index_reductions")) {
            const Json& target = o.get("target");
            if (truthy(target) && resolve(str(target), or_empty(o.get("system")))) {
                kept_reductions.push(o);
                continue;
            }
            skip("index-operation", o.get("name"),
                 "it reduces '" + (target.is_null() ? std::string("(nothing)") : js_string(target)) + "', which is not in this model");
            known.erase(qualified(o));
        }
        project.set("index_reductions", kept_reductions);

        Json kept_aggregates = Json::array();
        for (Json g : list_of(project, "block_reductions")) {
            const JArray targets = list_of(g, "targets");
            const std::string system = or_empty(g.get("system"));
            Json kept = Json::array();
            std::vector<std::string> lost;
            for (const Json& t : targets) {
                if (resolve(str(t), system)) kept.push(t);
                else lost.push_back(str(t));
            }
            if (kept.size() == targets.size()) {
                kept_aggregates.push(g);
                continue;
            }
            if (kept.empty()) {
                skip("aggregate", g.get("name"), "none of the blocks it reduces (" + join(lost, ", ") + ") is in this model");
                known.erase(qualified(g));
                continue;
            }
            g.set("targets", kept);
            const std::string more = lost.size() > 4 ? "\u2026" : "";
            warn("'" + str(g.get("name")) + "' reduces " + itos(static_cast<long long>(lost.size())) + " block(s) this tool did not import (" +
                 join(first_n(lost, 4), ", ") + more + "); they were left out of the total.");
            kept_aggregates.push(g);
        }
        project.set("block_reductions", kept_aggregates);
    }

    // --- sub-system interfaces -----------------------------------------------------------------

    struct Holder {
        std::string collection, kind;
        Json block;
        std::string qname;
    };

    // Puts one equation where a block's own value was: "rewritten", "converted" for a parameter
    // that became an expression, or none for a kind that cannot be fed at all.
    OptStr wire_into(const Holder& target, const std::string& equation) {
        Json block = target.block;
        auto clear = [&](const char* key) {
            Json kept = Json::array();
            for (const Json& e : list_of(block, "entries")) {
                Json rest = Json::object();
                for (const auto& [k, v] : e.obj())
                    if (k != key) rest.set(k, v);
                bool any = false;
                for (const auto& [k, v] : rest.obj())
                    if (k != "index") any = true;
                if (any) kept.push(rest);
            }
            block.set("entries", kept);
            if (kept.empty()) block.erase("entries");
        };
        if (target.kind == "expression") {
            block.set("equation", Json(equation));
            clear("equation");
            return std::string("rewritten");
        }
        if (target.kind == "transfer") {
            block.set("rate", Json(equation));
            clear("rate");
            return std::string("rewritten");
        }
        if (target.kind == "parameter") {
            JArray& params = project["parameters"].arr();
            for (std::size_t k = 0; k < params.size(); k++)
                if (params[k].same(block)) {
                    params.erase(params.begin() + static_cast<std::ptrdiff_t>(k));
                    break;
                }
            block.erase("value");
            clear("value");
            block.erase("entries");
            block.set("equation", Json(equation));
            project["expressions"].push(block);
            return std::string("converted");
        }
        return std::nullopt;
    }

    // Wires up what a sub-system interface connected, and drops the interface.
    void connect_interfaces() {
        const Wiring& wiring = wiring_;
        if (wiring.links.empty()) {
            if (!wiring.exposed.empty()) {
                const bool one = wiring.exposed.size() == 1;
                warn(itos(static_cast<long long>(wiring.exposed.size())) + " sub-system input/output" + (one ? " was" : "s were") +
                     " declared but connected to nothing, so nothing was routed: the " +
                     (one ? "block behind it keeps the value" : "blocks behind them keep the values") + " the file gives " +
                     (one ? "it" : "them") + ".");
            }
            return;
        }

        std::unordered_map<std::string, Holder> by_name;
        const std::vector<std::pair<const char*, const char*>> holders = {
            {"parameters", "parameter"}, {"compartments", "compartment"}, {"expressions", "expression"}, {"transfers", "transfer"},
            {"inflows", "inflow"}, {"lookups", "lookup"}, {"index_reductions", "index_reduction"},
            {"block_reductions", "block_reduction"}, {"min_maxes", "min_max"}, {"running_means", "running_mean"},
            {"snapshots", "snapshot"}, {"delays", "delay"}, {"triggers", "trigger"}};
        for (const auto& [collection, kind] : holders)
            for (const Json& block : list_of(project, collection)) {
                const std::string qname = qualified(block);
                by_name[qname] = Holder{collection, kind, block, qname};
            }
        auto found = [&](const std::string& guid) -> const Holder* {
            auto b = wiring.id_by_guid.find(guid);
            if (b == wiring.id_by_guid.end()) return nullptr;
            const std::string* qname = block_name_by_id_.find(b->second);
            if (!qname) return nullptr;
            auto h = by_name.find(*qname);
            return h == by_name.end() ? nullptr : &h->second;
        };

        OrderedMap<std::vector<const Link*>> by_target;
        for (const Link& link : wiring.links) by_target[link.target].push_back(&link);

        long long joined = 0;
        std::vector<std::string> lost, converted;
        for (const auto& [target_guid, incoming] : by_target.items) {
            const Holder* target = found(target_guid);
            if (!target) {
                lost.push_back(incoming[0]->via);
                continue;
            }
            std::vector<const Holder*> sources;
            for (const Link* l : incoming) {
                const Holder* s = found(l->source);
                if (s) sources.push_back(s);
            }
            if (sources.size() != incoming.size()) lost.push_back(incoming[0]->via);
            if (sources.empty()) continue;

            std::vector<std::string> refs;
            for (const Holder* s : sources) refs.push_back(s->qname);
            auto op_it = wiring.operations.find(target_guid);
            const std::string op = op_it == wiring.operations.end() ? std::string("ADD") : op_it->second;
            static const std::map<std::string, std::string> fns = {{"ADD", "sum"}, {"MAX", "max"}, {"MIN", "min"}, {"MEAN", "mean"}, {"PRODUCT", "prod"}};
            auto fn_it = fns.find(op);
            const std::string fn = fn_it == fns.end() ? std::string("sum") : fn_it->second;
            const std::string equation = refs.size() == 1 ? refs[0] : fn + "(" + join(refs, ", ") + ")";

            const OptStr rewritten = wire_into(*target, equation);
            if (!rewritten) {
                std::string kind = target->kind;
                std::replace(kind.begin(), kind.end(), '_', ' ');
                warn("'" + target->qname + "' is fed by a sub-system interface, and a " + kind + " cannot be: its value was left as the file gives it.");
                continue;
            }
            if (*rewritten == "converted") converted.push_back(target->qname);
            joined++;
        }

        if (joined != 0) {
            std::string tail;
            if (!converted.empty()) {
                const std::string others = converted.size() > 4 ? " and others" : "";
                const bool one = converted.size() == 1;
                tail = " " + join(first_n(converted, 4), ", ") + others + " " + (one ? "was a parameter and is" : "were parameters and are") +
                       " now expressions, since what feeds " + (one ? "it" : "them") + " is not a number.";
            }
            warn(itos(joined) + " sub-system input" + (joined == 1 ? "" : "s") + " " + (joined == 1 ? "was" : "were") +
                 " connected straight to what feeds " + (joined == 1 ? "it" : "them") +
                 ". Ecolego routes those through model input and output blocks, which are a way to wire a ready-made sub-system into a "
                 "project; this tool has no such library, so the two ends are joined directly and the interface blocks are left out." +
                 tail);
        }
        if (!lost.empty()) {
            std::vector<std::string> unique_lost;
            for (const std::string& l : lost)
                if (!contains(unique_lost, l)) unique_lost.push_back(l);
            const std::string shown = join(first_n(unique_lost, 4), ", ");
            warn(itos(static_cast<long long>(lost.size())) + " sub-system connection" + (lost.size() == 1 ? "" : "s") + " (" + shown +
                 ") named a block this tool did not import, so " + (lost.size() == 1 ? "it" : "they") + " could not be joined up.");
        }
    }

    // Settles each general variable on the block it reads, and says what became of them: Ecolego
    // shows the chosen block's unit as the general variable's, and the copy the file carries stood
    // in until now.
    void settle_general_variables() {
        if (generals_.empty()) return;
        std::unordered_map<std::string, Json> blocks;
        for (const char* kind : {"parameters", "compartments", "expressions", "transfers", "inflows", "lookups", "index_reductions",
                                 "block_reductions", "min_maxes", "running_means", "snapshots", "delays", "triggers"})
            for (const Json& b : list_of(project, kind)) blocks[qualified(b)] = b;
        auto resolve = [&](const Json& equation, const std::string& system) {
            return resolve_reference(js_trim(js_string(equation.is_null() ? Json("") : equation)), system,
                                     [&](const std::string& q) { return blocks.count(q) != 0; });
        };

        std::vector<std::string> read, unchosen;
        bool passed_over = false;
        for (const General& g : generals_) {
            Json block = g.block;
            const std::string qname = qualified(block);
            const std::size_t own = list_of(block, "entries").size();
            if (!g.picked && own == 0) {
                unchosen.push_back("'" + qname + "'");
                continue;
            }
            const std::string system = truthy(block.get("system")) ? str(block.get("system")) : std::string();
            const std::string text = js_trim(js_string(block.get("equation").is_null() ? Json("") : block.get("equation")));
            const OptStr target = resolve(Json(text), system);
            if (target) {
                const Json unit = blocks[*target].get("unit");
                if (unit.is_string() && !unit.as_string().empty()) block.set("unit", unit);
            }

            std::string line = "'" + qname + "' reads '" + (target ? *target : text) + "'";
            if (!target && is_reference(text)) line += ", which is not in this model";
            if (own != 0) line += " (and makes its own choice at " + itos(static_cast<long long>(own)) + " " + (own == 1 ? "index" : "indices") + ")";
            std::set<OptStr> chosen{target};
            for (const Json& e : list_of(block, "entries")) chosen.insert(resolve(e.get("equation"), system));
            std::vector<std::string> others;
            for (const std::string& i : g.offered) {
                const std::string* named = block_name_by_id_.find(i);
                const std::string n = named ? *named : i;
                if (!chosen.count(OptStr(n))) others.push_back(n);
            }
            if (!others.empty()) {
                std::vector<std::string> shown;
                for (const std::string& n : first_n(others, 3)) shown.push_back("'" + n + "'");
                if (others.size() > 3) shown.push_back(itos(static_cast<long long>(others.size()) - 3) + " more");
                line += ", chosen over " + list_words(shown);
                passed_over = true;
            }
            read.push_back(line);
        }
        if (!read.empty()) {
            const bool one = read.size() == 1;
            const std::string more = read.size() > 6 ? "; and " + itos(static_cast<long long>(read.size()) - 6) + " more" : "";
            warn(itos(static_cast<long long>(read.size())) + " general variable" + (one ? "" : "s") + ", " + (one ? "a block" : "blocks") +
                 " that stand" + (one ? "s" : "") + " in for one of a list of others, arrived as " + (one ? "an expression" : "expressions") +
                 " reading the one chosen, which is what Ecolego works out for " + (one ? "it" : "them") + ": " + join(first_n(read, 6), "; ") +
                 more + ". " +
                 (passed_over ? "The blocks passed over are in the model as they were; to choose one, write its name in the equation."
                              : "To choose another block, write its name in the equation."));
        }
        if (!unchosen.empty()) {
            const bool one = unchosen.size() == 1;
            std::vector<std::string> shown = first_n(unchosen, 4);
            if (unchosen.size() > 4) shown.push_back(itos(static_cast<long long>(unchosen.size()) - 4) + " more");
            warn(list_words(shown) + " " + (one ? "is a general variable" : "are general variables") +
                 " with no block chosen, which Ecolego will not run; here " + (one ? "it reads" : "they read") + " 0.");
        }
    }

    // Whether a set of names holds every block a run has a result for.
    bool names_every_result(const std::set<std::string>& names_) const {
        bool any_block = false;
        for (const std::string& collection : collections()) {
            if (collection == "functions") continue;
            for (const Json& b : list_of(project, collection)) {
                if (!(b.is_object() && !is_false(b.get("enabled")))) continue;
                const Json& argument = b.get("argument");
                if (collection == "lookups" && !argument.is_null() && js_trim(str(argument)) != "") continue;
                if (collection == "expressions" && (b.get("transport") == "counter" || b.get("transport") == "operation")) continue;
                any_block = true;
                if (!names_.count(qualified(b))) return false;
            }
        }
        return any_block;
    }

    // The endpoints by the names the blocks ended up with; a repeat is not a fault, and an id
    // with no block behind it is left out, with one warning for all of them.
    void rewrite_endpoint_ids() {
        Json sim = project.get("simulation");
        const Json ids = sim.is_object() ? sim.get("endpoints") : Json();
        if (!(ids.is_array() && !ids.empty())) return;
        std::unordered_set<std::string> known;
        for (const std::string& collection : collections())
            for (const Json& b : list_of(project, collection)) known.insert(qualified(b));
        Json out = Json::array();
        std::set<std::string> seen;
        long long unresolved = 0;
        for (const Json& eid_json : ids.arr()) {
            const std::string eid = str(eid_json);
            // The id first: in these files an id *is* the qualified name.
            std::string name = eid;
            if (!known.count(eid)) {
                const std::string* named = block_name_by_id_.find(eid);
                if (named) name = *named;
            }
            if (seen.count(name)) continue;
            if (!known.count(name)) {
                unresolved++;
                continue;
            }
            seen.insert(name);
            out.push(Json(name));
            // Half a transfer is not what was asked for.
            const std::string* twin = twins_.find(name);
            if (twin && !twin->empty() && !seen.count(*twin)) {
                seen.insert(*twin);
                out.push(Json(*twin));
            }
        }
        // A list of every block a run has a result for is what keeping everything means here,
        // where a block added later is kept too.
        if (!out.empty() && !names_every_result(seen)) sim.set("endpoints", out);
        else sim.erase("endpoints");
        if (unresolved != 0) {
            warn(itos(unresolved) + " of the model's saved endpoints name blocks that are not in the imported model; they were left out of "
                                    "the endpoint list.");
        }
    }

    // Ecolego's discrete transfers, as the events they are here.
    void settle_transfer_events() {
        Json transfers = project.get("transfers");
        if (!transfers.is_array()) return;
        std::vector<Json> discrete;
        for (const Json& t : transfers.arr()) {
            bool any = !t.get("transfer_event").is_null();
            for (const Json& e : list_of(t, "entries"))
                if (!e.get("transfer_event").is_null()) any = true;
            if (any) discrete.push_back(t);
        }
        if (discrete.empty()) return;
        auto qualified2 = [](const Json& b) {
            return truthy(b.get("system")) ? str(b.get("system")) + "." + str(b.get("name")) : str(b.get("name"));
        };
        std::unordered_map<std::string, Json> triggers, compartments;
        for (const Json& b : list_of(project, "triggers")) triggers[qualified2(b)] = b;
        for (const Json& c : list_of(project, "compartments")) compartments[qualified2(c)] = c;
        auto lists = [](const Json* b) -> std::string {
            if (!b) return "";
            std::string out;
            bool first = true;
            for (const Json& l : list_of(*b, "index_lists")) {
                if (!first) out.push_back('\0');
                first = false;
                out += str(l);
            }
            return out;
        };
        struct Move {
            std::string name;
            Json from, to;
        };
        std::vector<std::string> made;
        // The events each discrete event sets off, by the event and the index it is named at, in
        // the order they will act.
        OrderedMap<std::vector<Move>> together;
        for (const Json& t : discrete) {
            const JArray& rows = list_of(t, "entries");
            const Json event = t.get("transfer_event");
            std::string fires;
            OptStr why;
            {
                const Json* frm = nullptr;
                if (truthy(t.get("from"))) {
                    auto it = compartments.find(str(t.get("from")));
                    if (it != compartments.end()) frm = &it->second;
                }
                const Json& to_name = t.get("to");
                const Json* to = nullptr;
                if (!to_name.is_null()) {
                    auto it = compartments.find(str(to_name));
                    if (it != compartments.end()) to = &it->second;
                }
                auto any_row = [&](const std::function<bool(const Json&)>& pred) { return std::any_of(rows.begin(), rows.end(), pred); };
                std::string name, index;
                if (!truthy(t.get("from"))) {
                    why = "it starts outside the model, so there is no inventory for an event to move a share of";
                } else if (is_false(t.get("multiply_by_donor")) || any_row([](const Json& e) { return is_false(e.get("multiply_by_donor")); })) {
                    why = "it moves an amount at each firing rather than a share of its donor, and an event here moves shares";
                } else if (event.is_null() || any_row([&](const Json& e) { return !e.get("transfer_event").is_null() && e.get("transfer_event") != event; })) {
                    why = "its discrete event is not the same one at every index, and an event here is set off by one trigger";
                } else if (any_row([&](const Json& e) { return !e.get("rate").is_null() && e.get("rate") != t.get("rate"); })) {
                    why = "the share it moves is not the same at every index, and an event here moves one share of every index";
                } else if (!frm || (!to_name.is_null() && !to)) {
                    why = "an end of it is not a compartment, and an event here moves between compartments";
                } else if (lists(&t) != lists(frm) || (to && lists(to) != lists(frm))) {
                    why = "its ends are not indexed as it is, and an event here moves its share between two compartments cell for cell";
                } else if (!match_event(str(event), name, index)) {
                    why = "'" + str(event) + "' does not name a discrete event";
                } else {
                    // The event's name, and an index for each of its lists or none.
                    const OptStr named = resolve_reference(name, truthy(t.get("system")) ? str(t.get("system")) : std::string(),
                                                           [&](const std::string& n) { return triggers.count(n) != 0; });
                    if (!named) {
                        why = "'" + str(event) + "' is not a discrete event of this model";
                    } else if (static_cast<std::size_t>(std::count(index.begin(), index.end(), '[')) != list_of(triggers[*named], "index_lists").size()) {
                        why = "'" + str(event) + "' is indexed, and Ecolego fires it index by index, setting the transfer off at each index on its own";
                    } else {
                        fires = *named + index;
                    }
                }
            }
            JArray& all = project["transfers"].arr();
            for (std::size_t k = 0; k < all.size(); k++)
                if (all[k].same(t)) {
                    all.erase(all.begin() + static_cast<std::ptrdiff_t>(k));
                    break;
                }
            if (why) {
                skip("transfer", Json(qualified2(t)), "it has a transfer event, which makes it a discrete transfer, and " + *why);
                continue;
            }
            Json block = Json::object({{"name", t.get("name")}});
            if (truthy(t.get("system"))) block.set("system", t.get("system"));
            if (truthy(t.get("comment"))) block.set("comment", t.get("comment"));
            if (is_false(t.get("enabled"))) block.set("enabled", Json(false));
            // The transfer's colour, on the block it became.
            if (truthy(t.get("color"))) block.set("color", t.get("color"));
            block.set("timing", Json("trigger"));
            block.set("trigger", event);
            Json move = Json::object({{"kind", Json("move")}, {"from", t.get("from")}, {"to", t.get("to")}, {"fraction", t.get("rate")}});
            block.set("actions", Json::array({move}));
            if (!project.has("events")) project.set("events", Json::array());
            project["events"].push(block);
            made.push_back(str(t.get("name")));
            together[fires].push_back(Move{str(t.get("name")), move.get("from"), move.get("to")});
        }
        // Several set off by one event act in turn here, each on what the one before left, where
        // Ecolego moves every share from what was there before any of them moved.
        for (const auto& [fires, moves] : together.items) {
            const Move* first_ = nullptr;
            const Move* second = nullptr;
            for (std::size_t j = 1; j < moves.size() && !first_; j++)
                for (std::size_t i = 0; i < j; i++)
                    if (moves[j].from == moves[i].from || moves[j].from == moves[i].to) {
                        first_ = &moves[i];
                        second = &moves[j];
                        break;
                    }
            if (!first_) continue;
            warn("'" + first_->name + "' and '" + second->name + "' are set off by the same discrete event, and '" + second->name +
                 "' takes its share of '" + str(second->from) + "' after '" + first_->name + "' has moved a share " +
                 (first_->from == second->from ? "out of" : "into") +
                 " it. Ecolego takes every share from what was there before any of them moved; here events at one instant act in the "
                 "order they are listed, so '" +
                 second->name + "' moves a share of something else.");
        }
        if (!made.empty()) {
            const bool one = made.size() == 1;
            std::vector<std::string> shown;
            for (const std::string& n : first_n(made, 6)) shown.push_back("'" + n + "'");
            if (made.size() > 6) shown.push_back(itos(static_cast<long long>(made.size()) - 6) + " more");
            warn(std::string(one ? "A transfer has" : itos(static_cast<long long>(made.size())) + " transfers have") +
                 " a transfer event, which makes " + (one ? "it" : "each") +
                 " a discrete transfer: it moves its share of the donor all at once whenever that discrete event fires, and nothing in "
                 "between. " +
                 (one ? "It" : "Each") +
                 " came in as an event set off by that trigger, moving the same share to the same place at the same instant: " +
                 list_words(shown) + ".");
        }
    }

    // --- the description -----------------------------------------------------------------------

    // How many state variables the solver will integrate, as the application counts them: one
    // per combination of each compartment's and running mean's enabled indices, and one per event.
    long long state_count() const {
        Json stored = Json::array();
        for (const Json& l : list_of(project, "index_lists"))
            if (l.is_object()) stored.push(l);
        Json lists = derive_elements(stored);
        const std::vector<std::pair<const char*, const char*>> derived = {{COMPARTMENT_LIST, "compartments"}, {TRANSFER_LIST, "transfers"}};
        for (const auto& [name, collection] : derived) {
            bool present = false;
            for (const Json& l : lists.arr())
                if (l.get("name") == name) present = true;
            if (present) continue;
            std::vector<std::string> names_;
            for (const Json& b : list_of(project, collection)) {
                if (!(b.is_object() && !truthy(b.get("hidden")))) continue;
                const Json& sys = b.get("system");
                const Json n = truthy(sys) ? Json(str(sys) + "." + str(b.get("name"))) : b.get("name");
                if (n.is_string() && !n.as_string().empty()) names_.push_back(n.as_string());
            }
            if (names_.empty()) continue;
            Json indices = Json::array();
            for (const std::string& n : names_) indices.push(Json::object({{"name", Json(n)}, {"enabled", Json(true)}}));
            lists.push(Json::object({{"name", Json(name)}, {"indices", indices}}));
        }
        auto material_dimension = [&]() -> Json {
            const Json* nuc = nullptr;
            for (const Json& l : stored.arr())
                if (truthy(l.get("for_nuclides"))) {
                    nuc = &l;
                    break;
                }
            const Json* explicit_ = nullptr;
            if (nuc && truthy(nuc->get("indices"))) explicit_ = nuc;
            else
                for (const Json& l : stored.arr())
                    if (truthy(l.get("for_contaminants"))) {
                        explicit_ = &l;
                        break;
                    }
            if (explicit_) return truthy(explicit_->get("indices")) ? explicit_->get("name") : Json();
            if (truthy(project.get("nuclides"))) return Json(NUCLIDE_LIST);
            return Json();
        };
        auto enabled_count = [&](const Json& dim) -> long long {
            const Json& lst = find_list(lists, dim);
            if (lst.is_null()) return dim == NUCLIDE_LIST ? static_cast<long long>(list_of(project, "nuclides").size()) : 0;
            long long c = 0;
            for (const Json& i : list_of(lst, "indices"))
                if (!(i.is_object() && is_false(i.get("enabled")))) c++;
            return c;
        };
        auto effective_dims = [&](const Json& b) -> JArray {
            const Json& dims = b.get("index_lists");
            if (dims.is_array()) return dims.arr();
            if (b.has("actions") || b.has("timing")) return {};
            const Json name = material_dimension();
            if (truthy(name) && !is_false(b.get("per_nuclide"))) return {name};
            return {};
        };
        long long n = 0;
        for (const char* collection : {"compartments", "running_means"}) {
            for (const Json& b : list_of(project, collection)) {
                long long c = 1;
                for (const Json& d : effective_dims(b)) c *= enabled_count(d);
                n += c;
            }
        }
        // A discrete transfer comes in as an event, which counts its occurrences in a state of its own.
        n += static_cast<long long>(list_of(project, "events").size());
        return n;
    }

    // What the model is, in up to five lines, for its description: where it came from, what is in
    // it, what it is indexed by and what a run of it does; the author's own comment leads when
    // there is one.
    std::string describe_model(const Provenance& facts, const OptStr& file_name, const OptStr& version) const {
        std::vector<std::string> lines;
        const OptStr created = created_at(js_trim(facts.comment ? *facts.comment : ""));
        if (truthy(facts.comment) && !created) lines.push_back(js_trim(*facts.comment));

        // Where it came from.
        std::vector<std::string> parts;
        const std::string file = last_part(file_name ? *file_name : "");
        parts.push_back(file.empty() ? std::string("Imported from Ecolego") : "Imported from " + file);
        if (truthy(version)) parts.push_back("written by Ecolego " + *version);
        if (truthy(facts.author)) parts.push_back("by " + *facts.author);
        if (created) parts.push_back("created " + js_trim(*created));
        else if (facts.modified) parts.push_back("last changed " + iso_date(*facts.modified));
        lines.push_back(join(parts, ", ") + ".");

        // What is in it, in the order the panels list the kinds.
        std::vector<std::string> counts;
        for (const std::string& collection : collections()) {
            const std::size_t n = list_of(project, collection).size();
            if (n == 0) continue;
            const std::string single = singular(collection);
            std::string label = single.empty() ? std::string() : kind_label(single);
            label = ascii_lower(label.empty() ? collection : label);
            counts.push_back(itos(static_cast<long long>(n)) + " " + (n == 1 ? singularise(label) : label));
        }
        if (!counts.empty()) {
            const std::size_t systems = list_of(project, "systems").size();
            const long long states = state_count();
            lines.push_back("Holds " + list_words(counts) +
                            (systems != 0 ? ", in " + itos(static_cast<long long>(systems)) + " sub-system" + (systems == 1 ? "" : "s") : std::string()) +
                            (states != 0 ? "; " + itos(states) + " state" + (states == 1 ? "" : "s") + " to integrate" : std::string()) + ".");
        }

        // What it is indexed by: the lists blocks actually carry, most used first.
        OrderedMap<long long> used;
        for (const std::string& collection : collections()) {
            for (const Json& block : list_of(project, collection)) {
                const Json dims = block.is_object() ? block.get("index_lists") : Json();
                if (!dims.is_array()) continue;
                for (const Json& dim : dims.arr()) used[str(dim)] += 1;
            }
        }
        std::vector<std::pair<std::string, long long>> ranked = used.items;
        std::stable_sort(ranked.begin(), ranked.end(), [](const auto& a, const auto& b) {
            if (a.second != b.second) return a.second > b.second;
            return collation_less(a.first, b.first);
        });
        std::vector<std::string> dims;
        for (const auto& [name, _] : ranked) {
            const Json* lst = nullptr;
            for (const Json& l : list_of(project, "index_lists"))
                if (l.get("name") == name) {
                    lst = &l;
                    break;
                }
            long long n = 0;
            if (lst)
                for (const Json& i : list_of(*lst, "indices"))
                    if (!is_false(i.get("enabled"))) n++;
            dims.push_back(n != 0 ? name + " (" + itos(n) + ")" : name);
        }
        if (!dims.empty()) {
            const std::size_t most = 6;
            std::vector<std::string> shown = first_n(dims, most);
            if (dims.size() > most) shown.push_back(itos(static_cast<long long>(dims.size() - most)) + " more");
            lines.push_back("Indexed by " + list_words(shown) + ".");
        }

        // What a run of it does.
        Json sim = project.get("simulation");
        if (!sim.is_object()) sim = Json::object();
        if (!sim.get("end_time").is_null()) {
            const Json unit = sim.get("time_unit").is_null() ? Json("year") : sim.get("time_unit");
            const Json start = sim.get("start_time");
            const Json solver = sim.get("solver");
            lines.push_back("Runs " + fmt_count(start.is_null() ? Json(0) : start) + " to " + fmt_count(sim.get("end_time")) + " " + str(unit) +
                            "s with " + (solver.is_null() ? std::string(DEFAULT_SOLVER) : str(solver)) + ".");
        }
        return join(lines, "\n");
    }
};

// Which Ecolego wrote the archive: `.version` at its root is a properties file.
OptStr ecolego_version(EcoArchive& entries) {
    for (const std::string& name : entries.names()) {
        if (last_part(name) != ".version") continue;
        std::string text;
        try {
            text = decode_xml_bytes(entries.get(name));
        } catch (const EcoImportError&) {
            return std::nullopt;
        }
        return version_in(text);
    }
    return std::nullopt;
}

}  // namespace

// --- the report ------------------------------------------------------------------------------

std::string EcoImportReport::summary() const {
    auto cn = [&](const char* k) -> long long {
        for (const auto& [name, n] : counts)
            if (name == k) return n;
        return 0;
    };
    std::vector<std::string> lines;
    lines.push_back("Imported " + itos(cn("compartments")) + " compartment(s), " + itos(cn("transfers")) + " transfer(s), " +
                    itos(cn("parameters")) + " parameter(s), " + itos(cn("expressions")) + " expression(s), " +
                    (cn("lookups") != 0 ? itos(cn("lookups")) + " lookup table(s), " : std::string()) +
                    (cn("index_reductions") != 0 ? itos(cn("index_reductions")) + " index operation(s), " : std::string()) +
                    (cn("block_reductions") != 0 ? itos(cn("block_reductions")) + " aggregate(s), " : std::string()) +
                    (cn("events") != 0 ? itos(cn("events")) + " event(s), " : std::string()) + itos(cn("index_lists")) + " index list(s), " +
                    itos(cn("nuclides")) + " nuclide(s).");
    auto by_type = [](const Json& list) {
        OrderedMap<long long> m;
        for (const Json& s : list.arr()) m[js_string(s.get("type"))] += 1;
        std::vector<std::string> parts;
        for (const auto& [t, n] : m.items) parts.push_back(itos(n) + " " + t);
        return join(parts, ", ");
    };
    if (!skipped.empty())
        lines.push_back("Skipped " + itos(static_cast<long long>(skipped.size())) + " block(s) this tool cannot represent: " + by_type(skipped) + ".");
    if (!notes.empty()) lines.push_back("Ignored " + by_type(notes) + ": these carry no mass, so the results are unaffected.");
    if (!renamed.empty()) lines.push_back("Renamed " + itos(static_cast<long long>(renamed.size())) + " block(s) to valid identifiers.");
    if (!disabled.empty())
        lines.push_back(itos(static_cast<long long>(disabled.size())) + " block(s) are disabled, as they were in Ecolego, and take no part in the run.");
    if (disabled_systems && !disabled_systems->empty()) {
        std::vector<std::string> said_;
        for (const auto& [p, n] : *disabled_systems)
            said_.push_back("Sub-system '" + p + "' is switched off as a whole, as it was in Ecolego, with " + itos(n) + " block" + (n == 1 ? "" : "s") +
                            " in it; they keep their own switches and come back with it.");
        lines.push_back(join(said_, " "));
    }
    for (const std::string& w : warnings) lines.push_back(w);
    return join(lines, "\n");
}

Json EcoImportReport::to_json() const {
    Json out = Json::object();
    auto copies = [](const Json& list) {
        Json a = Json::array();
        for (const Json& s : list.arr()) a.push(s.shallow());
        return a;
    };
    out.set("skipped", copies(skipped));
    out.set("notes", copies(notes));
    out.set("renamed", copies(renamed));
    out.set("disabled", Json::array(disabled));
    if (disabled_systems) {
        Json ds = Json::object();
        for (const auto& [p, n] : *disabled_systems) ds.set(p, Json(n));
        out.set("disabled_systems", ds);
    } else {
        out.set("disabled_systems", Json());
    }
    out.set("warnings", Json::array(warnings));
    Json c = Json::object();
    for (const auto& [k, n] : counts) c.set(k, Json(n));
    out.set("counts", c);
    out.set("ok", Json(ok()));
    out.set("summary", Json(summary()));
    return out;
}

// --- the entry points ------------------------------------------------------------------------

std::optional<std::string> version_in(std::string_view text) {
    const std::size_t n = text.size();
    std::size_t from = 0;
    while (true) {
        const std::size_t k = text.find("version", from);
        if (k == std::string_view::npos) return std::nullopt;
        from = k + 1;
        if (k > 0) {
            // The character before must be white space.
            std::size_t p = k - 1;
            while (p > 0 && (static_cast<unsigned char>(text[p]) & 0xc0) == 0x80) p--;
            if (js_space_bytes(text, p, n) != k - p) continue;
        }
        std::size_t i = k + 7;
        while (i < n) {
            const std::size_t sp = js_space_bytes(text, i, n);
            if (sp == 0) break;
            i += sp;
        }
        if (!(i < n && text[i] == '=')) continue;
        i++;
        while (i < n) {
            const std::size_t sp = js_space_bytes(text, i, n);
            if (sp == 0) break;
            i += sp;
        }
        std::size_t j = i;
        while (j < n && (is_ident_char(static_cast<unsigned char>(text[j])) || text[j] == '.' || text[j] == '-')) j++;
        if (j > i) return std::string(text.substr(i, j - i));
    }
}

EcoImport import_model_xml(std::string src, const std::optional<std::string>& file_name, const std::optional<std::string>& version) {
    if (!is_valid_utf8(src)) src = utf8_replace(src);
    std::unique_ptr<XmlDoc> doc;
    try {
        doc = parse_xml(std::move(src));
    } catch (const EcoXMLError& e) {
        throw EcoImportError("model.xml is not valid XML: " + e.full());
    }
    const XmlNode* root = doc->root;
    const XmlNode* data_model = *root->name == "data-model" ? root : find(*root, "data-model");
    if (!data_model) throw EcoImportError("The XML has no <data-model> element");
    Importer imp;
    imp.run(data_model, file_name, version);
    return EcoImport{imp.project, imp.report};
}

EcoImport import_eco_file(std::string raw, const std::optional<std::string>& file_name, const std::optional<std::string>& version,
                          bool with_zlib) {
    // Ecolego 4/5 wrote the model as a bare XML file, usually UTF-16 with a BOM; Ecolego 6 zips
    // the project folder. Both carry the .eco extension.
    if (!looks_like_zip(raw)) {
        std::string text = decode_xml_bytes(raw);
        if (has_tag(text, "<sheet"))
            throw EcoImportError(
                "This is an Ecolego 4/5 model: a <sheet> document with a different data model from Ecolego 6 (compartments live in "
                "spreadsheet cells rather than a block model). This importer reads the Ecolego 6 format. Open the file in Ecolego and "
                "save it again to convert it.");
        if (!has_tag(text, "<data-model"))
            throw EcoImportError(
                "This file is neither a ZIP archive nor an Ecolego model XML. If it is a project folder, zip it or open its model.xml "
                "directly.");
        return import_model_xml(std::move(text), file_name, version);
    }

    EcoArchive entries = unzip(std::move(raw), with_zlib);

    // model.xml sits at the archive root in practice, but it is looked for by name anywhere --
    // and these archives are written on Windows, so a name may use backslashes. By name first,
    // and the bytes only of the one wanted: an assessment's results are never decompressed.
    std::optional<std::string> model_xml;
    for (const std::string& name : entries.names()) {
        if (last_part(name) == "model.xml") {
            model_xml = decode_xml_bytes(entries.get(name));
            break;
        }
    }
    if (!model_xml) {
        for (const std::string& name : entries.names()) {
            const std::string low = py_lower(name);
            if (!(low.size() >= 4 && low.compare(low.size() - 4, 4, ".xml") == 0)) continue;
            std::string text = decode_xml_bytes(entries.get(name));
            if (has_tag(text, "<data-model")) {
                model_xml = std::move(text);
                break;
            }
        }
    }
    if (!model_xml) {
        std::string held = join(entries.names(), ", ");
        if (held.empty()) held = "nothing";
        throw EcoImportError("No model.xml in the archive (it holds: " + held +
                             "). This may be a library or workspace archive rather than a project.");
    }
    return import_model_xml(std::move(*model_xml), file_name, ecolego_version(entries));
}

EcoImport import_eco_path(const std::string& path, const std::optional<std::string>& version) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Cannot read " + path);
    std::ostringstream ss;
    ss << in.rdbuf();
    const std::size_t slash = path.find_last_of('/');
    const std::string file_name = slash == std::string::npos ? path : path.substr(slash + 1);
    return import_eco_file(ss.str(), file_name, version);
}

bool is_ecolego_path(std::string_view path) {
    const std::string low = ascii_lower(path);
    auto ends = [&](const char* w) {
        const std::size_t k = std::strlen(w);
        return low.size() >= k && low.compare(low.size() - k, k, w) == 0;
    };
    return ends(".eco") || ends(".eas") || ends(".xml");
}

}  // namespace kompartment::eco
