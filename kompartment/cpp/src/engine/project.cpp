#include "engine/project.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

#include "engine/farfield_domain.hpp"
#include "engine/timeseries.hpp"
#include "lang/functions.hpp"
#include "lang/jsmath.hpp"
#include "model/decay.hpp"
#include "model/indexlists.hpp"
#include "model/keys.hpp"
#include "model/names.hpp"
#include "model/simulation.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

const double INF = std::numeric_limits<double>::infinity();
const double NaN = std::numeric_limits<double>::quiet_NaN();
const JArray NO_ITEMS;

const JArray& items(const Json& v) { return v.is_array() ? v.arr() : NO_ITEMS; }
std::string trimmed(const Json& v) { return std::string(js_trim(js_str(v))); }
/// `strip(js_str(something(v, "")))`.
std::string text_of(const Json& v) { return v.is_null() ? std::string() : trimmed(v); }
bool is_false(const Json& v) { return v.is_bool() && !v.as_bool(); }
bool is_true(const Json& v) { return v.is_bool() && v.as_bool(); }
/// On unless it says false, "false" or 0.
bool unless_off(const Json& v) { return !(is_false(v) || v == "false" || (v.is_number() && v.as_double() == 0)); }
bool among(const std::vector<std::string>& v, const Json& x) {
    return x.is_string() && std::find(v.begin(), v.end(), x.as_string()) != v.end();
}
bool among(const std::vector<std::string>& v, const std::string& x) { return std::find(v.begin(), v.end(), x) != v.end(); }
bool is_whole(double x) { return std::isfinite(x) && x == std::floor(x); }
std::string spaced(std::string s) {
    std::replace(s.begin(), s.end(), '_', ' ');
    return s;
}
bool blank(std::string_view s) { return js_trim(s).empty(); }
/// An index name with what cannot be in one shown as `?`: a line break, angle brackets,
/// the line and paragraph separators.
bool bad_index_char(std::string_view s, std::size_t i, std::size_t& len) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    len = 1;
    if (c == '\r' || c == '\n' || c == '<' || c == '>') return true;
    if (c == 0xe2 && i + 2 < s.size() && static_cast<unsigned char>(s[i + 1]) == 0x80 &&
        (static_cast<unsigned char>(s[i + 2]) == 0xa8 || static_cast<unsigned char>(s[i + 2]) == 0xa9)) {
        len = 3;
        return true;
    }
    return false;
}
bool has_bad_index_char(std::string_view s) {
    std::size_t len;
    for (std::size_t i = 0; i < s.size(); i++)
        if (bad_index_char(s, i, len)) return true;
    return false;
}
std::string shown_index(std::string_view s) {
    std::string out;
    for (std::size_t i = 0; i < s.size();) {
        std::size_t len;
        if (bad_index_char(s, i, len)) {
            out.push_back('?');
            i += len;
        } else {
            out.push_back(s[i++]);
        }
    }
    return out;
}
std::string values_joined(const Json& index, const char* sep, bool as_text = false) {
    std::vector<std::string> parts;
    if (index.is_object())
        for (const auto& [k, x] : index.obj()) parts.push_back(as_text ? js_text(x) : js_str(x));
    return join(parts, sep);
}

const std::vector<std::string> DECAY_UNITS = {"Bq", "mol"};
const std::vector<std::string> INTERPOLATIONS = {"linear", "extrapolate", "below", "above", "nearest"};
const std::vector<std::string> OPERATIONS = {"sum", "product", "min", "max", "mean", "percentile"};
const std::vector<std::string> AGGREGATE_OPERATIONS = {"sum", "product", "min", "max", "mean"};
const std::vector<std::string> EXTREMES = {"max", "min"};
const std::vector<std::string> DIRECTIONS = {"rising", "falling", "both"};
const std::vector<std::string> FAILURES = {"never", "at", "uniform", "exponential", "weibull"};
const std::vector<std::string> TIMINGS = {"at", "poisson", "trigger"};
const std::vector<std::string> ACTIONS = {"fail", "move"};

std::string failure_label(std::string_view f) {
    if (f == "never") return "never";
    if (f == "at") return "all at one time";
    if (f == "uniform") return "evenly over a window";
    if (f == "exponential") return "at a constant rate";
    return "Weibull";
}

Json waste_defaults() {
    return Json::object({
        {"failure", Json("never")}, {"packages", Json(1)}, {"inventory", Json("0")}, {"irf", Json("0")},
        {"degradation_rate", Json("0")}, {"fail_at", Json("")}, {"fail_from", Json("")}, {"fail_to", Json("")},
        {"fail_start", Json("0")}, {"fail_rate", Json("")}, {"fail_scale", Json("")}, {"fail_shape", Json("1")},
        {"handle_decay", Json(true)}});
}
Json dis_defaults() {
    return Json::object({{"timing", Json("at")}, {"at", Json("")}, {"rate", Json("")}, {"from", Json("")}, {"until", Json("")},
                         {"trigger", Json("")}, {"sampled", Json(true)}, {"actions", Json::array()}});
}

std::optional<std::string> from_eco(const std::vector<std::pair<const char*, const char*>>& table, const std::string& word) {
    for (const auto& [from, to] : table)
        if (word == from) return std::string(to);
    return std::nullopt;
}
const std::vector<std::pair<const char*, const char*>> INTERPOLATION_FROM_ECO = {
    {"Interpolation-Use End Values", "linear"}, {"Interpolation-Extrapolation", "extrapolate"},
    {"Use Input Below", "below"}, {"Use Input Above", "above"}, {"Use Input Nearest", "nearest"}};
const std::vector<std::pair<const char*, const char*>> OPERATION_FROM_ECO = {
    {"SUM", "sum"}, {"PRODUCT", "product"}, {"MIN", "min"}, {"MAX", "max"}, {"MEAN", "mean"}, {"PERCENTILE", "percentile"},
    {"Sum", "sum"}, {"Product", "product"}, {"Minimum", "min"}, {"Maximum", "max"}, {"Mean", "mean"}, {"Percentile", "percentile"}};
const std::vector<std::pair<const char*, const char*>> DIRECTION_FROM_ECO = {{"RIGHT", "rising"}, {"LEFT", "falling"}, {"BOTH", "both"}};

/// What a kind of block starts with (`BLOCK_DEFAULTS`); a dictionary of its own.
Json block_defaults(const std::string& kind) {
    if (kind == "compartment")
        return Json::object({{"initial", Json("0")}, {"non_negative", Json(true)}, {"handle_decay", Json(true)}, {"color", Json()}, {"unit", Json("Bq")}});
    if (kind == "transfer")
        return Json::object({{"from", Json()}, {"to", Json()}, {"rate", Json("0")}, {"multiply_by_donor", Json(true)}, {"unit", Json("1/year")}});
    if (kind == "expression") return Json::object({{"equation", Json("0")}, {"unit", Json("")}});
    if (kind == "parameter") return Json::object({{"value", Json(0)}, {"unit", Json("")}});
    if (kind == "inflow") return Json::object({{"to", Json()}, {"rate", Json("0")}, {"unit", Json("Bq/year")}});
    if (kind == "lookup")
        return Json::object({{"points", Json::array()}, {"interpolation", Json("linear")}, {"cyclic", Json(false)}, {"argument", Json()}, {"unit", Json("")}});
    if (kind == "index_reduction")
        return Json::object({{"target", Json()}, {"operation", Json("sum")}, {"percentile", Json()}, {"unit", Json("")}});
    if (kind == "block_reduction") return Json::object({{"targets", Json::array()}, {"operation", Json("sum")}, {"unit", Json("")}});
    if (kind == "function") return Json::object({{"parameters", Json::array()}, {"equation", Json("")}, {"unit", Json("")}});
    if (kind == "min_max")
        return Json::object({{"target", Json("0")}, {"operation", Json("max")}, {"reset_trigger", Json()}, {"start_trigger", Json()},
                             {"stop_trigger", Json()}, {"unit", Json("")}});
    if (kind == "running_mean")
        return Json::object({{"target", Json("0")}, {"reset_trigger", Json()}, {"start_trigger", Json()}, {"stop_trigger", Json()}, {"unit", Json("")}});
    if (kind == "snapshot") return Json::object({{"target", Json("0")}, {"trigger", Json()}, {"initial", Json("0")}, {"unit", Json("")}});
    if (kind == "delay") return Json::object({{"target", Json("0")}, {"delay", Json("0")}, {"unit", Json("")}});
    if (kind == "trigger") return Json::object({{"first", Json("0")}, {"second", Json("0")}, {"direction", Json("rising")}, {"unit", Json("")}});
    Json d = kind == "farfield" ? farf_defaults() : kind == "waste_package" ? waste_defaults() : dis_defaults();
    d.set("unit", Json(""));
    return d;
}

std::optional<std::string> transport_operation(const Json& op) {
    std::string v = lowercase(text_of(op));
    if (v.empty()) return std::nullopt;
    if (v == "sum" || v == "mean") return v;
    if (v == "point") return std::string("sum");
    return std::nullopt;
}
std::optional<std::string> transport_argument(const Json& arg) {
    std::string v = lowercase(text_of(arg));
    if (v == "all" || v == "point" || v == "range") return v;
    return std::nullopt;
}
std::optional<std::string> extreme(const Json& name) {
    std::string s = uppercase(text_of(name));
    if (s == "MIN") return std::string("min");
    if (s == "MAX") return std::string("max");
    return std::nullopt;
}

bool is_jsnum_like(const Json& v) { return v.is_number() || v.is_string(); }

Json normalise_entry_index(const Json& index, const std::optional<std::string>& material_list_name,
                           const std::vector<std::string>& dims) {
    if (index.is_null()) return Json::object();
    if (index.is_string()) {
        std::optional<std::string> lst = dims.size() == 1 ? std::optional<std::string>(dims[0]) : material_list_name;
        if (!lst || lst->empty())
            throw ValidationError("Entry index '" + index.as_string() + "' is ambiguous: name the index list explicitly, as { \"ListName\": \"" +
                                  index.as_string() + "\" }");
        return Json::object({{*lst, index}});
    }
    if (index.is_array()) {
        if (index.size() != dims.size())
            throw ValidationError("Entry index has " + std::to_string(index.size()) + " component(s) but the block has " +
                                  std::to_string(dims.size()) + " dimension(s)");
        Json out = Json::object();
        for (std::size_t i = 0; i < dims.size(); i++)
            if (!index[i].is_null()) out.set(dims[i], index[i]);
        return out;
    }
    if (!index.is_object())
        throw ValidationError("Entry index '" + js_text(index) + "' is not an index: write it as a name, a list of names, or an object keyed by index list.");
    return index.shallow();
}

Json normalise_entries(const Json& raw, const std::string& kind, const std::optional<std::string>& material_list_name,
                       const std::vector<std::string>& dims) {
    Json out = Json::array();
    const std::vector<std::string>& keys = value_keys(kind);
    const Json& block_name = raw.has("name") ? raw.get("name") : Json::null_value;
    Json name_or_empty = raw.has("name") ? block_name : Json("");
    bool material = material_list_name && !material_list_name->empty();
    for (const Json& e : items(raw.get("entries"))) {
        if (!e.is_object()) continue;
        Json index = normalise_entry_index(e.get("index"), material_list_name, dims);
        Json values = Json::object();
        for (const auto& k : keys)
            if (e.has(k)) values.set(k, e.get(k));
        if (kind == "lookup" && values.has("points")) values.set("points", normalise_points(values.get("points"), name_or_empty));
        if (kind == "block_reduction" && values.has("targets")) values.set("targets", normalise_targets(values.get("targets"), name_or_empty));
        if (values.has("non_negative")) values.set("non_negative", Json(unless_off(values.get("non_negative"))));
        if ((kind == "farfield" || kind == "waste_package") && material && index.has(*material_list_name)) {
            const std::vector<std::string>& per_nuclide = kind == "farfield" ? farf_nuclide_keys() : waste_nuclide_keys();
            Json kept = Json::object();
            for (const auto& [k, v] : values.obj())
                if (among(per_nuclide, k)) kept.set(k, v);
            values = kept;
        }
        Json entry = Json::object({{"index", index}});
        for (const auto& [k, v] : values.obj()) entry.set(k, v);
        out.push(entry);
    }
    const Json& init = raw.get("initial");
    if (kind == "compartment" && init.is_object() && material)
        for (const auto& [nuc, v] : init.obj())
            out.push(Json::object({{"index", Json::object({{*material_list_name, Json(nuc)}})}, {"initial", Json(js_str(v))}}));
    const Json& vbn = raw.get("values_by_nuclide");
    if (kind == "parameter" && js_truthy(vbn) && material && vbn.is_object())
        for (const auto& [nuc, v] : vbn.obj())
            out.push(Json::object({{"index", Json::object({{*material_list_name, Json(nuc)}})}, {"value", Json(js_number_of(v))}}));
    return out;
}

std::string summed_dims_why(const std::string& flux, const std::string& end, const std::string& end_name,
                            const std::vector<std::string>& dims, const std::function<std::optional<int>(const std::string&)>& size_of) {
    std::vector<std::string> named;
    for (const auto& d : dims) named.push_back("'" + d + "'");
    std::string lst = named.size() > 1 ? join(std::vector<std::string>(named.begin(), named.end() - 1), ", ") + " and " + named.back() : named[0];
    bool counted = true;
    long count = 1;
    for (const auto& d : dims) {
        std::optional<int> s = size_of(d);
        if (!s || *s == 0) counted = false;
        else count *= *s;
    }
    std::string over = counted ? "all " + std::to_string(count) + " of them" : "all of them";
    std::string each = counted ? "each of the " + std::to_string(count) + " of them" : "each of them";
    std::string body = end == "to" ? ": the flux would be added up over " + over + " and delivered into the one '" + end_name + "' cell."
                                   : ": the flux would be taken out of the one '" + end_name + "' cell once for " + each + ".";
    return "'" + flux + "' is indexed by " + lst + ", which '" + end_name + "' is not" + body +
           " Give both ends the same dimensions, or tick \"sum extra indices\" on '" + flux + "' to ask for that total on purpose.";
}

std::string compact(const Json& v) { return json_text(v, 0); }

}  // namespace

ValidationError::ValidationError(const std::string& message, std::optional<std::string> block_)
    : std::runtime_error((block_ && !block_->empty()) ? *block_ + ": " + message : message), block(std::move(block_)) {}

const std::vector<std::string>& block_collections() {
    static const std::vector<std::string> v = {
        "parameters", "compartments", "expressions", "transfers", "inflows", "lookups", "index_reductions",
        "block_reductions", "functions", "min_maxes", "running_means", "snapshots", "delays", "triggers", "farfields",
        "waste_packages", "events"};
    return v;
}

std::string kind_of_collection(std::string_view c) {
    if (c == "parameters") return "parameter";
    if (c == "compartments") return "compartment";
    if (c == "expressions") return "expression";
    if (c == "transfers") return "transfer";
    if (c == "inflows") return "inflow";
    if (c == "lookups") return "lookup";
    if (c == "index_reductions") return "index_reduction";
    if (c == "block_reductions") return "block_reduction";
    if (c == "functions") return "function";
    if (c == "min_maxes") return "min_max";
    if (c == "running_means") return "running_mean";
    if (c == "snapshots") return "snapshot";
    if (c == "delays") return "delay";
    if (c == "triggers") return "trigger";
    if (c == "farfields") return "farfield";
    if (c == "waste_packages") return "waste_package";
    if (c == "events") return "event";
    return "";
}

const std::vector<std::string>& waste_nuclide_keys() {
    static const std::vector<std::string> v = {"inventory", "irf", "degradation_rate"};
    return v;
}
const std::vector<std::string>& waste_single_keys() {
    static const std::vector<std::string> v = {"fail_at", "fail_from", "fail_to", "fail_start", "fail_rate", "fail_scale", "fail_shape"};
    return v;
}
const std::vector<std::string>& waste_equation_keys() {
    static const std::vector<std::string> v = {"inventory", "irf", "degradation_rate", "fail_at", "fail_from", "fail_to",
                                               "fail_start", "fail_rate", "fail_scale", "fail_shape"};
    return v;
}
const std::vector<std::string>& dis_equation_keys() {
    // `trigger` is an equation in the sense a snapshot's is: its one token names the
    // trigger that sets the event off.
    static const std::vector<std::string> v = {"at", "rate", "from", "until", "trigger"};
    return v;
}
std::vector<std::string> timing_keys(std::string_view timing) {
    if (timing == "at") return {"at"};
    if (timing == "poisson") return {"rate", "from", "until"};
    return {};
}
std::vector<std::string> failure_keys(std::string_view f) {
    if (f == "at") return {"fail_at"};
    if (f == "uniform") return {"fail_from", "fail_to"};
    if (f == "exponential") return {"fail_start", "fail_rate"};
    if (f == "weibull") return {"fail_start", "fail_scale", "fail_shape"};
    return {};
}
std::string waste_label(std::string_view key) {
    static const std::pair<const char*, const char*> labels[] = {
        {"inventory", "Inventory"}, {"irf", "Instant release fraction"}, {"degradation_rate", "Matrix degradation rate"},
        {"fail_at", "Fail at"}, {"fail_from", "Failures from"}, {"fail_to", "Failures until"},
        {"fail_start", "Failures start"}, {"fail_rate", "Failure rate"}, {"fail_scale", "Weibull scale"},
        {"fail_shape", "Weibull shape"}};
    for (const auto& [k, label] : labels)
        if (key == k) return label;
    return "";
}

const std::vector<std::string>& value_keys(std::string_view kind) {
    static const std::vector<std::string> none;
    static const std::unordered_map<std::string_view, std::vector<std::string>> table = {
        {"compartment", {"initial", "abstol", "non_negative", "dydt"}},
        {"function", {"equation"}},
        // The rate alone: whether it is multiplied by the donor is one setting of the whole transfer.
        {"transfer", {"rate"}},
        {"expression", {"equation"}},
        {"parameter", {"value", "pdf"}},
        {"inflow", {"rate"}},
        {"lookup", {"points"}},
        {"index_reduction", {"target"}},
        {"block_reduction", {"targets"}},
        {"min_max", {"target", "reset_trigger", "start_trigger", "stop_trigger"}},
        {"running_mean", {"target", "reset_trigger", "start_trigger", "stop_trigger"}},
        {"snapshot", {"target", "trigger", "initial"}},
        {"delay", {"target", "delay"}},
        {"trigger", {"first", "second", "direction"}},
        {"farfield", farf_equation_keys()},
        {"waste_package", waste_equation_keys()},
        {"event", dis_equation_keys()},
    };
    auto it = table.find(kind);
    return it == table.end() ? none : it->second;
}

Json value_at(const Json& block, std::string_view key, const Tup& tup) {
    const Json* best = nullptr;
    int best_score = -1;
    for (const Json& entry : items(block.get("entries"))) {
        if (!entry.has(key)) continue;
        int score = 0;
        bool ok = true;
        const Json& index = entry.get("index");
        if (index.is_object())
            for (const auto& [list_name, index_name] : index.obj()) {
                const std::string* at = tup.find(list_name);
                if (!(at && index_name.is_string() && *at == index_name.as_string())) {
                    ok = false;
                    break;
                }
                score++;
            }
        if (ok && score > best_score) {
            best_score = score;
            best = &entry.get(key);
        }
    }
    if (best_score >= 0) return *best;
    return block.get(key);
}

std::function<Json(const Tup&)> entry_lookup(const Json& block, const std::string& key) {
    struct Group {
        std::vector<std::string> lists;
        std::unordered_map<std::string, std::pair<int, Json>> by_values;
    };
    auto groups = std::make_shared<std::vector<Group>>();
    int pos = 0;
    for (const Json& entry : items(block.get("entries"))) {
        pos++;
        if (!entry.has(key)) continue;
        std::vector<std::string> lists;
        std::string vals;
        const Json& index = entry.get("index");
        if (index.is_object())
            for (const auto& [k, v] : index.obj()) {
                lists.push_back(k);
                // An index that is not text matches nothing: a key no tuple makes.
                vals += v.is_string() ? v.as_string() : std::string("\x01") + compact(v);
                vals.push_back('\x1f');
            }
        Group* g = nullptr;
        for (auto& x : *groups)
            if (x.lists == lists) g = &x;
        if (!g) {
            groups->push_back({lists, {}});
            g = &groups->back();
        }
        g->by_values.emplace(vals, std::make_pair(pos, entry.get(key)));
    }
    Json own = block.get(key);
    if (groups->empty()) return [own](const Tup&) { return own; };
    std::stable_sort(groups->begin(), groups->end(), [](const Group& a, const Group& b) { return a.lists.size() > b.lists.size(); });
    return [groups, own](const Tup& tup) {
        int best_score = -1, best_pos = -1;
        const Json* best = nullptr;
        std::string vals;
        for (const Group& g : *groups) {
            int score = static_cast<int>(g.lists.size());
            if (score < best_score) break;
            vals.clear();
            bool has_all = true;
            for (const auto& name : g.lists) {
                const std::string* at = tup.find(name);
                if (!at) {
                    has_all = false;
                    break;
                }
                vals += *at;
                vals.push_back('\x1f');
            }
            if (!has_all) continue;
            auto hit = g.by_values.find(vals);
            if (hit != g.by_values.end() && (score > best_score || hit->second.first < best_pos)) {
                best_score = score;
                best_pos = hit->second.first;
                best = &hit->second.second;
            }
        }
        return best_score >= 0 ? *best : own;
    };
}

bool has_dydt(const Json& block) {
    auto is_set = [](const Json& v) { return v.is_string() && !blank(v.as_string()); };
    if (is_set(block.get("dydt"))) return true;
    for (const Json& e : items(block.get("entries")))
        if (is_set(e.get("dydt"))) return true;
    return false;
}

std::string py_text(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return "None";
        case Json::Type::Bool: return v.as_bool() ? "True" : "False";
        case Json::Type::Int: return std::to_string(v.as_int());
        case Json::Type::Float: return py_repr(v.as_double());
        default: return js_text(v);
    }
}

std::vector<std::string> strings_of(const Json& list) {
    std::vector<std::string> out;
    for (const Json& x : items(list)) out.push_back(js_str(x));
    return out;
}

Json normalise_index_lists(const Json& raw_lists) {
    for (const Json& l : items(raw_lists)) {
        if (!(l.is_object() && !js_truthy(l.get("derived")))) continue;
        const Json& lname = l.get("name");
        std::string name_text = lname.is_null() ? std::string() : js_str(lname);
        if (!is_name(std::string_view(name_text)))
            throw ValidationError("'" + shown_index(lname.is_null() ? "nothing" : name_text) +
                                  "' is not a valid index list name (letters, digits and underscore; must not start with a digit)",
                                  shown_index(lname.is_null() ? "nothing" : name_text));
        if (is_reserved_name(name_text)) throw ValidationError("'" + name_text + "' is a reserved name", name_text);
        std::unordered_set<std::string> seen;
        for (const Json& i : items(l.get("indices"))) {
            const Json& n = i.is_string() ? i : i.get("name");
            std::string text = n.is_null() ? std::string() : js_str(n);
            if (blank(text)) throw ValidationError("An index of '" + name_text + "' has no name", name_text);
            if (has_bad_index_char(text))
                throw ValidationError("'" + shown_index(text) + "' is not a usable index name: an index may not contain a line break or angle brackets", name_text);
            if (!seen.insert(text).second)
                throw ValidationError("'" + text + "' appears twice in index list '" + name_text +
                                      "'. Two indices of the same name are one address for two positions: everything indexed by the list would carry a slot nothing can reach.",
                                      name_text);
        }
    }
    auto names_of = [](const Json& l) {
        std::vector<Json> out;
        for (const Json& i : items(l.get("indices"))) out.push_back(i.is_string() ? i : i.get("name"));
        return out;
    };
    auto holds = [](const std::vector<Json>& names, const Json& x) {
        for (const Json& n : names)
            if (n == x) return true;
        return false;
    };
    for (const Json& l : items(raw_lists)) {
        if (!(l.is_object() && !js_truthy(l.get("derived")) && l.get("mapping").is_object())) continue;
        const Json& mapping = l.get("mapping");
        const Json* target = nullptr;
        for (const Json& x : items(raw_lists))
            if (x.is_object() && x.get("name") == mapping.get("to")) { target = &x; break; }
        if (!target) continue;
        std::vector<Json> own = names_of(l), theirs = names_of(*target);
        std::string lname = js_str(l.get("name"));
        for (const Json& pair : items(mapping.get("pairs"))) {
            const Json& from = pair.get("from");
            const Json& to = pair.get("to");
            if (!holds(own, from))
                throw ValidationError("Index list '" + lname + "' maps '" + shown_index(from.is_null() ? "nothing" : js_str(from)) +
                                      "', which is not one of its indices", lname);
            if (!holds(theirs, to))
                throw ValidationError("Index list '" + lname + "' maps '" + js_str(from) + "' onto '" + shown_index(to.is_null() ? "nothing" : js_str(to)) +
                                      "', which is not an index of '" + js_str(target->get("name")) + "'", lname);
        }
    }
    Json out = Json::array();
    for (const Json& l : items(raw_lists)) {
        Json d = Json::object({{"name", l.get("name")}, {"for_contaminants", Json(js_truthy(l.get("for_contaminants")))}});
        for (const char* key : {"for_nuclides", "for_scenarios", "for_elements"})
            if (js_truthy(l.get(key))) d.set(key, Json(true));
        if (js_truthy(l.get("sub_set_of"))) d.set("sub_set_of", l.get("sub_set_of"));
        if (js_truthy(l.get("mapping"))) d.set("mapping", l.get("mapping"));
        if (js_truthy(l.get("comment"))) d.set("comment", l.get("comment"));
        if (js_truthy(l.get("derived"))) d.set("derived", Json(true));
        if (js_truthy(l.get("auto"))) d.set("auto", l.get("auto"));
        if (js_truthy(l.get("note"))) d.set("note", l.get("note"));
        Json idx = Json::array();
        for (const Json& i : items(l.get("indices"))) {
            if (i.is_string()) {
                idx.push(Json::object({{"name", i}, {"enabled", Json(true)}}));
            } else {
                Json e = Json::object({{"name", i.get("name")}, {"enabled", Json(!is_false(i.get("enabled")))}});
                std::string u = text_of(i.get("unit"));
                if (!u.empty()) e.set("unit", Json(u));
                idx.push(e);
            }
        }
        d.set("indices", idx);
        out.push(d);
    }
    return out;
}

Json normalise_series(const Json& raw) {
    Json out = Json::array();
    if (!raw.is_array()) return out;
    for (const Json& spec : raw.arr()) {
        if (!spec.is_object()) continue;
        std::string kind;
        if (spec.get("times").is_array()) {
            kind = "times";
        } else {
            const Json& k = spec.get("kind");
            std::string named = js_str(!k.is_null() ? k : (js_truthy(spec.get("spacing")) ? spec.get("spacing") : Json("log")));
            kind = named == "linear" ? "linear" : (named == "times" ? "times" : "log");
        }
        if (kind == "times") {
            std::vector<double> times;
            for (const Json& x : items(spec.get("times"))) {
                double v = js_number_of(x);
                if (std::isfinite(v)) times.push_back(v);
            }
            std::sort(times.begin(), times.end());
            if (!times.empty()) out.push(Json::object({{"kind", Json("times")}, {"times", Json::array(times)}}));
            continue;
        }
        double pts = spec.has("points") ? js_number_of(spec.get("points")) : 0.0;
        long points = std::isfinite(pts) ? static_cast<long>(std::floor(pts + 0.5)) : 0;
        if (points < 2) continue;
        auto num = [](const Json& v) -> Json {
            if (v.is_null() || v == "") return Json();
            double n = js_number_of(v);
            return std::isfinite(n) ? Json(n) : Json();
        };
        out.push(Json::object({{"kind", Json(kind)}, {"points", Json(static_cast<long long>(points))}, {"from", num(spec.get("from"))},
                               {"to", num(spec.get("to"))}}));
    }
    return out;
}

Json normalise_points(const Json& points, const Json& block_name) {
    Json out = Json::array();
    if (points.is_null()) return out;
    std::optional<std::string> owner = block_name.is_null() ? std::nullopt : std::optional<std::string>(js_str(block_name));
    if (!points.is_array()) throw ValidationError("Lookup points must be a list of [x, y] pairs", owner);
    Json pairs = points;
    if (points.size() == 2 && points[0].is_array() && points[1].is_array() && points[0].size() == points[1].size() &&
        points[0].size() != 2) {
        bool all = true;
        for (const Json& x : points[0].arr())
            if (!is_jsnum_like(x)) all = false;
        if (all) {
            pairs = Json::array();
            for (std::size_t i = 0; i < points[0].size(); i++) pairs.push(Json::array({points[0][i], points[1][i]}));
        }
    }
    std::size_t i = 0;
    for (const Json& pt : pairs.arr()) {
        i++;
        Json x, y, pdf;
        if (pt.is_array()) {
            if (pt.size() > 0) x = pt[0];
            if (pt.size() > 1) y = pt[1];
            if (pt.size() > 2) pdf = pt[2];
        } else if (pt.is_object()) {
            x = pt.get("x");
            y = pt.get("y");
            pdf = pt.get("pdf");
        }
        double nx = x.is_null() ? NaN : js_number_of(x);
        double ny = y.is_null() ? NaN : js_number_of(y);
        if (!std::isfinite(nx) || !std::isfinite(ny))
            throw ValidationError("Lookup point " + std::to_string(i) + " is (" + js_text(x) + ", " + js_text(y) + "); both parts must be numbers", owner);
        out.push(js_truthy(pdf) ? Json::array({Json(nx), Json(ny), pdf}) : Json::array({Json(nx), Json(ny)}));
    }
    return out;
}

Json normalise_targets(const Json& targets, const Json& block_name) {
    Json out = Json::array();
    if (targets.is_null()) return out;
    std::vector<std::string> lst;
    if (targets.is_string()) {
        lst = split(targets.as_string(), '+');
    } else if (targets.is_array()) {
        for (const Json& t : targets.arr()) lst.push_back(js_str(t));
    } else {
        throw ValidationError("Aggregate targets must be a list of block names",
                              block_name.is_null() ? std::nullopt : std::optional<std::string>(js_str(block_name)));
    }
    for (const auto& t : lst) {
        std::string s(js_trim(t));
        if (!s.empty()) out.push(Json(s));
    }
    return out;
}

Json normalise_actions(const Json& raw) {
    Json out = Json::array();
    if (!raw.is_array()) return out;
    for (const Json& a : raw.arr()) {
        if (!a.is_object()) continue;
        const Json& k = a.get("kind");
        const Json& f = a.get("fraction");
        Json d = Json::object({{"kind", Json(js_str(!k.is_null() ? k : Json("move")))}, {"fraction", Json(js_str(!f.is_null() ? f : Json("1")))}});
        if (d.get("kind") == "fail") {
            const Json& b = a.get("block");
            d.set("block", b.is_null() ? Json() : Json(js_str(b)));
        } else {
            const Json& fr = a.get("from");
            const Json& to = a.get("to");
            d.set("from", fr.is_null() ? Json() : Json(js_str(fr)));
            d.set("to", (to.is_null() || to == "") ? Json() : Json(js_str(to)));
        }
        out.push(d);
    }
    return out;
}

// --- the project ---------------------------------------------------------------------------------------

Project::Project(const Json& raw0) {
    if (!raw0.is_object()) throw ValidationError("A model is one JSON object");
    raw = migrate_keys(raw0);   // a copy: the caller's is never changed
    name = !raw.get("name").is_null() ? raw.get("name") : Json("Untitled project");
    description = js_truthy(raw.get("description")) ? raw.get("description") : Json("");
    Json sim = simulation_defaults();
    if (raw.get("simulation").is_object())
        for (const auto& [k, v] : raw.get("simulation").obj()) sim.set(k, v);
    simulation = sim;
    for (const char* key : {"start_time", "end_time", "output_points", "rtol", "abstol"}) {
        const Json& v = sim.get(key);
        if (v.is_null() || v.is_number()) continue;
        double n = js_number_of(v);
        if (!std::isfinite(n)) throw ValidationError("'" + js_text(v) + "' is not a number, and " + spaced(key) + " has to be one");
        sim.set(key, Json(n));
    }
    struct Range {
        const char* key;
        double least, most;
        bool whole;
    };
    for (const Range& r : {Range{"max_step", 0, INF, false}, Range{"initial_step", 0, INF, false}, Range{"max_steps", 1, INF, true},
                           Range{"max_order", 1, 5, true}, Range{"min_order", 1, 5, true}, Range{"newton_kappa", 0, 1, false},
                           Range{"max_jac_age", 1, INF, true}, Range{"below_tol_run", 0, INF, true}, Range{"stagnation_tol", 0, 1, false}}) {
        Json v = sim.get(r.key);
        if (v.is_null() || v == "") {
            sim.erase(r.key);
            continue;
        }
        double n = js_number_of(v);
        if (!std::isfinite(n) || n < r.least || n > r.most || (r.whole && !is_whole(n))) {
            std::string rng = r.most == INF ? "of at least " + js_number(r.least) : "between " + js_number(r.least) + " and " + js_number(r.most);
            throw ValidationError("'" + js_text(v) + "' is not a " + spaced(r.key) + ": a " + (r.whole ? "whole number" : "number") + " " + rng);
        }
        sim.set(r.key, Json(n));
    }
    if (!sim.get("min_order").is_null() &&
        js_number_of(sim.get("min_order")) > js_number_of(sim.has("max_order") ? sim.get("max_order") : Json(5)))
        throw ValidationError("The lowest order (" + js_text(sim.get("min_order")) + ") is above the highest (" +
                              js_text(sim.has("max_order") ? sim.get("max_order") : Json(5)) + ")");
    struct Choice {
        const char* key;
        std::vector<std::string> allowed;
    };
    for (const Choice& c : {Choice{"error_norm", {"rms", "max"}}, Choice{"matrix", {"auto", "refactor", "sparse", "dense"}},
                            Choice{"jacobian", {"analytic", "numeric"}}}) {
        Json v = sim.get(c.key);
        if (v.is_null() || v == "") {
            sim.erase(c.key);
            continue;
        }
        if (!among(c.allowed, v)) throw ValidationError("'" + js_text(v) + "' is not a " + spaced(c.key) + " (" + join(c.allowed, ", ") + ")");
    }
    sim.set("norm_control", Json(js_truthy_switch(sim.get("norm_control"), false)));
    sim.set("bdf", Json(js_truthy_switch(sim.get("bdf"), false)));
    sim.set("non_negative", Json(js_truthy_switch(sim.has("non_negative") ? sim.get("non_negative") : Json(true), true)));
    sim.set("mass_balance", Json(js_truthy_switch(sim.get("mass_balance"), false)));
    sim.set("auto_abstol", Json(js_truthy_switch(sim.get("auto_abstol"), false)));
    {
        double n = js_number_of(sim.get("iterations"));
        n = std::isfinite(n) ? std::floor(n + 0.5) : n;
        sim.set("iterations", Json(std::isfinite(n) && n > 0 ? static_cast<long long>(n) : 1000LL));
        double s = js_number_of(sim.get("seed"));
        sim.set("seed", Json(std::isfinite(s) ? static_cast<long long>(std::floor(s + 0.5)) : 1LL));
    }
    if (!(sim.get("sampling") == "random")) sim.set("sampling", Json("latin"));
    if (!(sim.get("time_unit").is_string() && time_unit_years(sim.get("time_unit").as_string()) > 0))
        throw ValidationError("Unknown time unit '" + js_text(sim.get("time_unit")) + "'");
    if (!among(spacings(), sim.get("spacing")))
        throw ValidationError("'" + js_text(sim.get("spacing")) + "' is not a way of choosing output times (" + join(spacings(), ", ") + ")");
    output_times = normalise_series(sim.get("output_times"));
    sim.set("output_times", output_times);
    output_mode = sim.get("spacing") == "solver" ? "solver" : (sim.get("spacing") == "both" ? "both" : "grid");
    solver_points = output_mode != "grid";

    nuclides = raw.get("nuclides").is_array() ? raw.get("nuclides").shallow() : Json::array();
    {
        const Json& du = raw.get("decay_unit");
        decay_unit = trimmed(!du.is_null() ? du : Json("Bq"));
        double ceiling = !sim.get("decay_ceiling").is_null() ? js_number_of(sim.get("decay_ceiling")) : NaN;
        decay_ceiling = std::isfinite(ceiling) && ceiling > 0 ? ceiling : INF;
        if (!among(DECAY_UNITS, decay_unit)) throw ValidationError("Unknown decay unit '" + decay_unit + "' (" + join(DECAY_UNITS, " or ") + ")");
    }
    half_lives_override = raw.get("half_lives").is_object() ? raw.get("half_lives").shallow() : Json::object();
    for (const auto& [nuc, v] : half_lives_override.obj()) {
        if (v.is_null()) continue;
        std::string word = lowercase(trimmed(v));
        if (word == "stable" || word == "inf" || word == "infinity") {
            half_lives_[nuc] = INF;
            continue;
        }
        double years = js_number_of(v);
        if (!(std::isfinite(years) && years > 0))
            throw ValidationError("The half-life of '" + nuc + "' must be a number of years greater than zero, or 'stable' -- '" + js_text(v) +
                                  "' is neither.", nuc);
        half_lives_[nuc] = years;
    }
    // A list stated -- an empty one too, which means no decay chains -- replaces the default pairs.
    chains_stated = kompartment::chains_stated(raw.get("chains"));
    if (chains_stated) {
        chains_override = Json::array();
        for (const Json& c : items(raw.get("chains"))) chains_override.push(c.is_array() ? c.shallow() : Json::array());
        for (Json& pair : chains_override.arr()) {
            Json parent = pair.size() > 0 ? pair[0] : Json();
            Json daughter = pair.size() > 1 ? pair[1] : Json();
            std::vector<std::string> shown;
            for (const Json& x : pair.arr()) shown.push_back(compact(x));
            std::string named = "[" + join(shown, ", ") + "]";
            if (!parent.is_string() || blank(parent.as_string()) || !daughter.is_string() || blank(daughter.as_string()))
                throw ValidationError("A decay pair is [parent, daughter, branching]; " + named + " does not name two nuclides.");
            double r = pair.size() < 3 ? 1.0 : js_number_of(pair[2]);
            if (!std::isfinite(r) || r <= 0 || r > 1) {
                std::string gives = pair.size() < 3 ? "none" : compact(pair[2]);
                throw ValidationError("The branching from '" + parent.as_string() + "' to '" + daughter.as_string() +
                                      "' must be greater than zero and at most 1; " + named + " gives " + gives + ".");
            }
            if (pair.size() < 3) pair.push(Json(1));
        }
    }

    Json declared = desugar_nuclides(raw);
    Json lists = derive_block_lists(derive_elements(declared), raw);
    for (const Json& l : lists.arr())
        if (js_truthy(l.get("derived"))) derived_lists.insert(js_str(l.get("name")));
    index_lists = normalise_index_lists(lists);
    try {
        index_space = IndexSpace(index_lists);
    } catch (const IndexSpaceError& e) {
        throw ValidationError(e.what(), e.detail);
    }
    if (const IndexList* materials = index_space.material_list()) material_list_name = materials->name;
    const IndexList* nuc = index_space.nuclide_list();
    nuclide_list_name = nuc ? std::optional<std::string>(nuc->name) : material_list_name;
    if (chains_stated) {
        chains = chains_override;
    } else {
        chains = Json::array();
        for (const auto& [parent, daughter, branching] : default_chains(material_names()))
            chains.push(Json::array({Json(parent), Json(daughter), Json(branching)}));
    }
    if (!raw.get("scenario").is_null()) {
        const Json& wanted = raw.get("scenario");
        if (!index_space.set_scenario(wanted.is_string() ? std::optional<std::string>(wanted.as_string()) : std::nullopt)) {
            std::vector<std::string> sc = index_space.scenarios();
            index_space.set_scenario(sc.empty() ? std::nullopt : std::optional<std::string>(sc[0]));
        }
    }
    scenario = index_space.scenario();
    scenarios = index_space.scenarios();

    for (const auto& collection : block_collections()) blocks[collection] = {};
    for (const auto& collection : block_collections()) {
        std::string kind = kind_of_collection(collection);
        JArray out;
        for (const Json& b : items(raw.get(collection)))
            if (b.is_object()) out.push_back(normalise_block(b, kind));
        blocks[collection] = std::move(out);
    }

    {
        const Json& ds = raw.get("disabled_systems");
        for (const Json& x : items(ds))
            if (!x.is_null() && !trimmed(x).empty()) disabled_systems.push_back(trimmed(x));
    }
    auto off_by_system = [&](const Json& block) -> std::optional<std::string> {
        std::string home = js_truthy(block.get("system")) ? js_str(block.get("system")) : "";
        if (home.empty()) return std::nullopt;
        std::vector<std::string> hits;
        for (const auto& q : disabled_systems)
            if (is_within(home, q)) hits.push_back(q);
        if (hits.empty()) return std::nullopt;
        std::stable_sort(hits.begin(), hits.end(), [](const std::string& a, const std::string& b) { return a.size() < b.size(); });
        return hits[0];
    };
    for (const auto& collection : block_collections()) {
        JArray kept, off;
        for (const Json& b : blocks[collection]) {
            bool own = is_false(b.get("enabled"));
            std::optional<std::string> by = own ? std::nullopt : off_by_system(b);
            if (own || by) {
                std::string q = b.get("qname").as_string();
                disabled.insert(q);
                off.push_back(b);
                if (by) off_reasons[q] = "it is in '" + *by + "', which is disabled";
            } else {
                kept.push_back(b);
            }
        }
        blocks[collection] = std::move(kept);
        if (!off.empty()) switched_off[collection] = std::move(off);
    }
    std::vector<std::string> block_systems;
    for (const auto& c : collections())
        for (const Json& b : items(raw.get(c)))
            if (b.is_object()) block_systems.push_back(js_truthy(b.get("system")) ? js_str(b.get("system")) : "");
    systems = system_paths(raw.get("systems"), raw.get("transports"), block_systems);
    for (const Json& x : items(raw.get("transports"))) {
        std::string t = text_of(x);
        if (!t.empty() && !among(transports, t)) transports.push_back(t);
    }
    for (const auto& q : disabled_systems)
        if (!among(systems, q))
            throw ValidationError("'" + q + "' is listed as a disabled sub-system, but there is no sub-system of that name", q);
    resolve_endpoints();
    layout = raw.get("layout").is_object() ? raw.get("layout").shallow() : Json::object();
    shapes = raw.get("shapes").is_array() ? raw.get("shapes").copy() : Json::array();
    derived = raw.get("derived").is_array() ? raw.get("derived").copy() : Json::array();
    view = js_truthy(raw.get("view")) && raw.get("view").is_object() ? raw.get("view").shallow() : Json();
    validate();
}

const JArray& Project::blocks_of(std::string_view collection) const {
    auto it = blocks.find(std::string(collection));
    return it == blocks.end() ? NO_ITEMS : it->second;
}

std::vector<std::string> Project::material_names() const {
    return material_list_name ? index_space.index_names(*material_list_name) : std::vector<std::string>{};
}
std::vector<std::string> Project::nuclide_names() const {
    return nuclide_list_name ? index_space.index_names(*nuclide_list_name) : std::vector<std::string>{};
}

std::optional<double> Project::half_life_of(const std::string& nuclide) const {
    auto it = half_lives_.find(nuclide);
    if (it != half_lives_.end()) return it->second;
    return half_life(nuclide);
}

double Project::lam(const std::string& nuclide, const std::string& unit) const {
    std::optional<double> hl = half_life_of(nuclide);
    if (!hl || !std::isfinite(*hl)) return 0.0;
    return LN2 / (*hl / time_unit_years(unit));
}

DecayModel Project::decay_model() const { return decay_model_for(material_list_name); }

DecayModel Project::decay_model_for(const std::optional<std::string>& list_name) const {
    DecayModel m;
    if (list_name && index_space.has_list(*list_name)) m.names = index_space.index_names(*list_name);
    Json pairs = chains_override;
    if (!chains_stated) {
        pairs = Json::array();
        for (const auto& [parent, daughter, branching] : default_chains(m.names, decay_ceiling))
            pairs.push(Json::array({Json(parent), Json(daughter), Json(branching)}));
    }
    std::unordered_map<std::string, int> idx;
    for (std::size_t i = 0; i < m.names.size(); i++) idx[m.names[i]] = static_cast<int>(i);
    std::string unit = time_unit();
    for (const auto& n : m.names) m.lambdas.push_back(lam(n, unit));
    m.parents.resize(m.names.size());
    bool amounts = decay_unit == "mol";
    for (const Json& pair : pairs.arr()) {
        if (!(pair[0].is_string() && pair[1].is_string())) continue;
        auto pi = idx.find(pair[0].as_string());
        auto di = idx.find(pair[1].as_string());
        if (pi == idx.end() || di == idx.end()) continue;
        Json ratio = pair.size() > 2 ? pair[2] : Json(1);
        m.parents[static_cast<std::size_t>(di->second)].push_back(
            {pi->second, amounts ? m.lambdas[static_cast<std::size_t>(pi->second)] : m.lambdas[static_cast<std::size_t>(di->second)],
             js_number_of(ratio)});
    }
    return m;
}

Json Project::normalise_block(const Json& raw_block, const std::string& kind) {
    Json base = block_defaults(kind);
    for (const auto& [k, v] : raw_block.obj()) base.set(k, v);
    base.set("kind", Json(kind));
    std::optional<std::string> owner = raw_block.has("name") ? std::optional<std::string>(js_text(raw_block.get("name"))) : std::nullopt;
    Json name_or_empty = raw_block.has("name") ? raw_block.get("name") : Json("");
    std::string role;
    {
        const Json& t = raw_block.get("transport");
        std::vector<std::string> roles = kind == "compartment" ? std::vector<std::string>{"begin", "end"}
                                         : kind == "expression" ? std::vector<std::string>{"number", "counter", "operation"}
                                         : std::vector<std::string>{};
        if (among(roles, t)) role = t.as_string();
    }
    if (!role.empty()) base.set("transport", Json(role));
    else base.erase("transport");
    if (role == "counter") base.set("equation", Json("1"));
    if (role == "operation") {
        base.set("operation", Json(transport_operation(raw_block.get("operation")).value_or("mean")));
        base.set("argument", Json(transport_argument(raw_block.get("argument")).value_or("all")));
    }
    if (kind == "compartment") base.set("non_negative", Json(!is_false(base.get("non_negative"))));
    if (kind == "transfer") base.set("multiply_by_donor", Json(!is_false(base.get("multiply_by_donor"))));
    if (kind == "transfer" || kind == "inflow") {
        const Json& sei = base.get("sum_extra_indices");
        if (is_true(sei) || sei == "true") base.set("sum_extra_indices", Json(true));
        else base.erase("sum_extra_indices");
    }
    base.set("comment", !raw_block.get("comment").is_null() ? raw_block.get("comment") : Json(""));
    if (kind == "lookup") {
        const Json& interp = raw_block.get("interpolation");
        if (interp.is_null() || interp == "") {
            base.set("interpolation", Json("linear"));
        } else {
            auto known = from_eco(INTERPOLATION_FROM_ECO, trimmed(interp));
            base.set("interpolation", known ? Json(*known) : interp);
        }
        base.set("cyclic", Json(js_truthy(raw_block.get("cyclic"))));
        base.set("argument", js_truthy(raw_block.get("argument")) ? Json(js_str(raw_block.get("argument"))) : Json());
        base.set("points", normalise_points(raw_block.get("points"), name_or_empty));
    }
    if (kind == "index_reduction" || kind == "block_reduction") {
        const Json& op = raw_block.get("operation");
        if (op.is_null() || op == "") {
            base.set("operation", Json("sum"));
        } else {
            auto known = from_eco(OPERATION_FROM_ECO, trimmed(op));
            base.set("operation", known ? Json(*known) : op);
        }
    }
    if (kind == "index_reduction") {
        base.set("target", raw_block.get("target").is_null() ? Json() : Json(js_str(raw_block.get("target"))));
        base.set("percentile", raw_block.get("percentile").is_null() ? Json() : Json(js_number_of(raw_block.get("percentile"))));
    }
    if (kind == "block_reduction") base.set("targets", normalise_targets(raw_block.get("targets"), name_or_empty));
    if (kind == "function") {
        Json params = Json::array();
        for (const Json& x : items(raw_block.get("parameters")))
            if (!x.is_null() && !trimmed(x).empty()) params.push(Json(trimmed(x)));
        base.set("parameters", params);
        base.set("equation", raw_block.get("equation").is_null() ? Json("") : Json(js_str(raw_block.get("equation"))));
        base.set("system", js_truthy(raw_block.get("system")) ? raw_block.get("system") : Json(""));
        base.set("index_lists", Json::array());
        base.set("entries", Json::array());
        base.set("qname", Json(qualified_name(base)));
        return base;
    }
    if (kind == "min_max") {
        const Json& op = raw_block.get("operation");
        if (op.is_null() || op == "") {
            base.set("operation", Json("max"));
        } else {
            auto known = extreme(op);
            base.set("operation", known ? Json(*known) : op);
        }
    }
    if (kind == "farfield") {
        Json defaults = farf_defaults();
        for (const auto& key : farf_structure_keys()) {
            Json given = !raw_block.get(key).is_null() ? raw_block.get(key) : defaults.get(key);
            if (key == "n_b" && (given.is_null() || (given.is_string() && blank(given.as_string())))) {
                base.set(key, Json(""));
                continue;
            }
            double v = js_number_of(given);
            base.set(key, std::isfinite(v) ? Json(static_cast<long long>(std::floor(v + 0.5))) : raw_block.get(key));
        }
        const Json& s = raw_block.get("surface");
        base.set("surface", (s.is_null() || s == "") ? Json(surface_of(raw_block)) : s);
        std::string used = surface_of(base);
        if (base.get(used).is_null()) base.set(used, Json(farf_surface_default(used)));
        base.erase("to");
    }
    if (kind == "waste_package") {
        const Json& f = raw_block.get("failure");
        base.set("failure", (f.is_null() || f == "") ? Json("never") : f);
        const Json& np = raw_block.get("packages");
        double n = js_number_of(!np.is_null() ? np : Json(1));
        base.set("packages", std::isfinite(n) ? Json(static_cast<long long>(std::floor(n + 0.5))) : np);
        base.set("handle_decay", Json(unless_off(raw_block.get("handle_decay"))));
        base.erase("to");
    }
    if (kind == "event") {
        const Json& t = raw_block.get("timing");
        base.set("timing", (t.is_null() || t == "") ? Json("at") : t);
        base.set("sampled", Json(unless_off(raw_block.get("sampled"))));
        base.set("actions", normalise_actions(raw_block.get("actions")));
    }
    if (kind == "trigger") {
        const Json& d = raw_block.get("direction");
        if (d.is_null() || d == "") {
            base.set("direction", Json("rising"));
        } else {
            auto known = from_eco(DIRECTION_FROM_ECO, uppercase(trimmed(d)));
            base.set("direction", known ? Json(*known) : d);
        }
    }
    std::vector<std::string> dims = dimensions_for(raw_block, kind);
    if (kind == "event") dims.clear();
    base.set("index_lists", Json::array(dims));
    Json unit = raw_block.get("unit");
    if (unit.is_null() && (kind == "transfer" || kind == "inflow")) unit = Json(derived_unit(base, kind));
    if (unit.is_null() && kind == "compartment") unit = Json(inventory_unit(base));
    if (unit.is_null() && (kind == "farfield" || kind == "waste_package")) unit = Json(decay_unit + "/" + js_str(simulation.get("time_unit")));
    if (unit.is_null()) {
        Json u = block_defaults(kind).get("unit");
        unit = js_truthy(u) ? u : Json("");
    }
    base.set("unit", unit);
    if (base.get("transport") == "number" || base.get("transport") == "counter") base.set("unit", Json(""));
    base.set("system", js_truthy(raw_block.get("system")) ? raw_block.get("system") : Json(""));
    base.set("qname", Json(qualified_name(base)));
    try {
        base.set("entries", normalise_entries(raw_block, kind, nuclide_list_name, dims));
    } catch (const ValidationError& e) {
        throw;
    }
    if (kind == "transfer") {
        const JArray& raws = items(raw_block.get("entries"));
        bool by_donor = base.get("multiply_by_donor").as_bool();
        for (std::size_t at = 0; at < raws.size(); at++) {
            const Json& e = raws[at];
            if (!(e.is_object() && e.has("multiply_by_donor") && (!is_false(e.get("multiply_by_donor"))) != by_donor)) continue;
            const JArray& entries = base.get("entries").arr();
            std::string where = at < entries.size() ? values_joined(entries[at].get("index"), ", ") : "";
            if (where.empty()) where = "one of its entries";
            std::string said = by_donor ? "It multiplies its rate by the donor" : "Its rate is an absolute flux";
            throw ValidationError(said + ", and " + where + " says otherwise. That is one setting for the whole transfer -- it makes the rate a "
                                  "coefficient or a flux, and gives it its unit -- so a model that needs both has two transfers between the same "
                                  "compartments: one by the donor and one an absolute flux, each with a zero rate where the other applies.",
                                  base.get("name").is_null() ? std::nullopt : std::optional<std::string>(js_text(base.get("name"))));
        }
    }
    if (base.get("initial").is_object()) base.set("initial", Json("0"));
    if (kind == "compartment") {
        std::vector<Json> holders = {base};
        for (const Json& e : base.get("entries").arr()) holders.push_back(e);
        for (Json& holder : holders) {
            if (!holder.has("dydt")) continue;
            const Json& d = holder.get("dydt");
            if (d.is_null() || trimmed(d).empty()) holder.erase("dydt");
            else holder.set("dydt", Json(js_str(d)));
        }
    }
    const std::vector<std::string>& vk = value_keys(kind);
    if (!vk.empty() && raw_block.has("default") && !raw_block.has(vk[0])) base.set(vk[0], raw_block.get("default"));
    for (const char* key : {"values_by_nuclide", "default", "per_nuclide"}) base.erase(key);
    (void)owner;
    return base;
}

std::string Project::derived_unit(const Json& block, const std::string& kind) const {
    std::string t = js_truthy(simulation.get("time_unit")) ? js_str(simulation.get("time_unit")) : "year";
    auto unit_of = [&](const Json& end) -> std::string {
        if (end.is_null()) return "";
        const JArray& cs = blocks_of("compartments");
        const Json* c = nullptr;
        for (const Json& x : cs)
            if (x.get("qname") == end) { c = &x; break; }
        if (!c)
            for (const Json& x : cs)
                if (x.get("name") == end) { c = &x; break; }
        return c ? text_of(c->get("unit")) : "";
    };
    auto per = [&](const std::string& q) {
        bool compound = q.find('/') != std::string::npos;
        for (unsigned char ch : q)
            if (ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r' || ch == '\f' || ch == '\v') compound = true;
        return compound ? "(" + q + ")/" + t : q + "/" + t;
    };
    if (kind == "inflow") {
        std::string u = unit_of(block.get("to"));
        return u.empty() ? "" : per(u);
    }
    if (!is_false(block.get("multiply_by_donor"))) return "1/" + t;
    const Json& fr = block.get("from");
    std::string u = unit_of(!fr.is_null() ? fr : block.get("to"));
    return u.empty() ? "" : per(u);
}

std::string Project::inventory_unit(const Json& base) const {
    for (const Json& d : items(base.get("index_lists"))) {
        const Json* l = nullptr;
        for (const Json& x : index_lists.arr())
            if (x.get("name") == d) { l = &x; break; }
        if (!l) continue;
        bool is_material = js_truthy(l->get("for_contaminants")) || js_truthy(l->get("for_nuclides")) ||
                           (js_truthy(l->get("sub_set_of")) && material_list_name && l->get("sub_set_of") == *material_list_name);
        if (is_material) return dimension_unit(js_str(d));
    }
    return decay_unit;
}

std::string Project::material_unit(const std::string& name) const {
    const Json* catalogue = nullptr;
    for (const Json& l : index_lists.arr())
        if (js_truthy(l.get("for_contaminants"))) { catalogue = &l; break; }
    if (catalogue)
        for (const Json& i : catalogue->get("indices").arr())
            if (i.get("name") == name) {
                std::string stated = text_of(i.get("unit"));
                if (!stated.empty()) return stated;
                break;
            }
    const Json* nucs = nullptr;
    for (const Json& l : index_lists.arr())
        if (js_truthy(l.get("for_nuclides"))) { nucs = &l; break; }
    if (!nucs) nucs = catalogue;
    bool is_nuclide = false;
    if (nucs) {
        for (const Json& i : nucs->get("indices").arr())
            if (i.get("name") == name) is_nuclide = true;
    } else {
        for (const Json& n : nuclides.arr())
            if (n == name) is_nuclide = true;
    }
    return is_nuclide ? (decay_unit == "mol" ? "mol" : "Bq") : "";
}

std::string Project::dimension_unit(const std::string& list_name) const {
    const Json* lst = nullptr;
    for (const Json& l : index_lists.arr())
        if (l.get("name") == list_name) { lst = &l; break; }
    if (!lst) {
        for (const Json& l : index_lists.arr())
            if (js_truthy(l.get("for_contaminants")) || js_truthy(l.get("for_nuclides"))) return "";
        return decay_unit == "mol" ? "mol" : "Bq";
    }
    std::optional<std::string> one;
    for (const Json& i : lst->get("indices").arr()) {
        if (is_false(i.get("enabled"))) continue;
        std::string u = material_unit(i.get("name").is_null() ? std::string() : js_str(i.get("name")));
        if (u.empty()) return "";
        if (!one) one = u;
        else if (*one != u) return "";
    }
    return one.value_or("");
}

std::optional<std::vector<std::string>> Project::endpoint_dims(const Json& end_name) {
    if (end_name.is_null()) return std::nullopt;
    if (!ends_by_name_) {
        ends_by_name_.emplace();
        for (const char* key : {"compartments", "farfields", "waste_packages"})
            for (const Json& b : items(raw.get(key)))
                if (b.is_object() && js_truthy(b.get("name"))) (*ends_by_name_)[qualified_name(b)] = b;
    }
    const auto& ends = *ends_by_name_;
    std::string written = js_str(end_name);
    std::string q = resolve_reference(written, "", [&](const std::string& n) { return ends.count(n) != 0; }).value_or(written);
    auto it = ends.find(q);
    if (it == ends.end()) return std::nullopt;
    const Json& end = it->second;
    if (end.get("index_lists").is_array()) {
        try {
            return normalise_dims(end.get("index_lists"));
        } catch (const IndexSpaceError& e) {
            throw ValidationError(e.what(), end.get("name").is_null() ? std::nullopt : std::optional<std::string>(js_text(end.get("name"))));
        }
    }
    std::optional<std::string> implied = (nuclide_list_name && index_space.list_size(*nuclide_list_name) > 0) ? nuclide_list_name : material_list_name;
    if (implied && !implied->empty() && !is_false(end.get("per_nuclide"))) return std::vector<std::string>{*implied};
    return std::vector<std::string>{};
}

std::vector<std::string> Project::dimensions_for(const Json& raw_block, const std::string& kind) {
    if (kind == "function") return {};
    std::optional<std::string> owner = raw_block.get("name").is_null() ? std::nullopt : std::optional<std::string>(js_text(raw_block.get("name")));
    if (raw_block.get("index_lists").is_array()) {
        std::vector<std::string> dims;
        try {
            dims = normalise_dims(raw_block.get("index_lists"));
        } catch (const IndexSpaceError& e) {
            throw ValidationError(e.what(), owner);
        }
        for (const auto& d : dims) {
            if (!index_space.has_list(d)) throw ValidationError("Unknown index list '" + d + "'", owner);
            const Json& lst = find_list(index_lists, std::string_view(d));
            if (!list_applies(lst, kind)) throw ValidationError(list_applies_why(lst, kind), owner);
        }
        auto clash = clashing_dimensions(index_lists, dims);
        if (clash) throw ValidationError(clashing_dimensions_why(clash), owner);
        return dims;
    }
    if (kind == "transfer" || kind == "inflow") {
        auto a = endpoint_dims(raw_block.get("from"));
        auto b = endpoint_dims(raw_block.get("to"));
        auto shared = shared_dims(index_lists, a ? &*a : nullptr, b ? &*b : nullptr);
        if (shared) return shared->dims;
    }
    std::optional<std::string> implied = (nuclide_list_name && index_space.list_size(*nuclide_list_name) > 0) ? nuclide_list_name : material_list_name;
    if (implied && !implied->empty() && !is_false(raw_block.get("per_nuclide"))) return {*implied};
    return {};
}

std::vector<std::pair<std::string, Json>> Project::blocks_by_name() const {
    std::vector<std::pair<std::string, Json>> out;
    std::unordered_set<std::string> seen;
    for (const auto& collection : collections())
        for (const Json& b : blocks_of(collection)) {
            const std::string& q = b.get("qname").as_string();
            if (!seen.insert(q).second) throw ValidationError("Duplicate block name '" + q + "'", q);
            out.emplace_back(q, b);
        }
    return out;
}

std::vector<Json> Project::all_blocks() const {
    std::vector<Json> out;
    for (const auto& c : collections())
        for (const Json& b : blocks_of(c)) out.push_back(b);
    return out;
}

void Project::resolve_endpoints() {
    std::unordered_set<std::string> ends;
    for (const char* c : {"compartments", "farfields", "waste_packages"})
        for (const Json& b : blocks[c]) ends.insert(b.get("qname").as_string());
    auto known = [&](const std::string& n) { return ends.count(n) != 0; };
    for (const char* c : {"transfers", "inflows"})
        for (Json& conn : blocks[c])
            for (const char* end : {"from", "to"}) {
                const Json& ref = conn.get(end);
                if (ref.is_null()) continue;
                std::string r = js_str(ref);
                if (known(r)) {
                    conn.set(end, Json(r));
                } else {
                    auto q = resolve_reference(r, js_truthy(conn.get("system")) ? js_str(conn.get("system")) : "", known);
                    conn.set(end, Json(q.value_or(r)));
                }
            }
    follow_disabled_ends();
}

void Project::follow_disabled_ends() {
    implicitly_disabled = off_reasons;
    JArray kept;
    for (Json& t : blocks["transfers"]) {
        const std::string& q = t.get("qname").as_string();
        if (!t.get("from").is_null() && disabled.count(js_str(t.get("from")))) {
            implicitly_disabled[q] = "its donor '" + js_str(t.get("from")) + "' is disabled, so there is no inventory for it to move";
            disabled.insert(q);
            continue;
        }
        if (!t.get("to").is_null() && disabled.count(js_str(t.get("to")))) {
            implicitly_disabled[q + "#to"] = "it flows into '" + js_str(t.get("to")) + "', which is disabled, so what it moves leaves the model";
            t.set("to", Json());
        }
        kept.push_back(t);
    }
    blocks["transfers"] = std::move(kept);
    kept.clear();
    for (Json& s : blocks["inflows"]) {
        const std::string& q = s.get("qname").as_string();
        if (!s.get("to").is_null() && disabled.count(js_str(s.get("to")))) {
            implicitly_disabled[q] = "it flows into '" + js_str(s.get("to")) + "', which is disabled, so there is nothing for it to feed";
            disabled.insert(q);
            continue;
        }
        kept.push_back(s);
    }
    blocks["inflows"] = std::move(kept);
}

void Project::validate() {
    std::unordered_set<std::string> names;
    static const char* const order[] = {"parameters", "compartments", "expressions", "transfers", "inflows", "lookups",
                                        "index_reductions", "block_reductions", "min_maxes", "running_means", "snapshots",
                                        "delays", "triggers", "farfields", "waste_packages", "events", "functions"};
    std::vector<Json> everything;
    for (const char* c : order)
        for (const Json& b : blocks_of(c)) everything.push_back(b);
    for (const Json& b : everything) {
        const Json& bname = b.get("name");
        const std::string& q = b.get("qname").as_string();
        if (!(js_truthy(bname) && is_name(std::string_view(js_str(bname)))))
            throw ValidationError("'" + js_text(bname) + "' is not a valid name (letters, digits and underscore; must not start with a digit)",
                                  bname.is_null() ? std::nullopt : std::optional<std::string>(js_str(bname)));
        if (is_reserved_name(js_str(bname))) throw ValidationError("'" + js_str(bname) + "' is a reserved name", js_str(bname));
        if (!is_valid_path(b.get("system").is_null() ? std::string() : js_str(b.get("system"))))
            throw ValidationError("'" + js_text(b.get("system")) + "' is not a valid sub-system path", q);
        if (among(systems, q)) throw ValidationError("'" + q + "' is both a block and a sub-system, and the two cannot share a name", q);
        if (!names.insert(q).second) {
            const Json& sys = b.get("system");
            throw ValidationError("Duplicate block name '" + q + "'" + (js_truthy(sys) ? " in sub-system '" + js_str(sys) + "'" : ""), q);
        }
    }
    for (const Json& c : blocks_of("compartments")) {
        std::vector<Json> holders = {c};
        for (const Json& e : c.get("entries").arr()) holders.push_back(e);
        for (std::size_t h = 0; h < holders.size(); h++) {
            const Json& v0 = holders[h].get("abstol");
            if (v0.is_null() || v0 == "") continue;
            double v = js_number_of(v0);
            if (std::isfinite(v) && v > 0) continue;
            const Json& where = h > 0 ? holders[h].get("index") : Json::null_value;
            std::string at = (where.is_object() && !where.empty()) ? " for " + values_joined(where, ", ") : "";
            throw ValidationError("Absolute tolerance" + at + " must be a number greater than zero (got " + js_text(v0) + ")", c.get("qname").as_string());
        }
    }
    std::unordered_set<std::string> compartments, paths;
    for (const Json& c : blocks_of("compartments")) compartments.insert(c.get("qname").as_string());
    for (const char* c : {"farfields", "waste_packages"})
        for (const Json& b : blocks_of(c)) paths.insert(b.get("qname").as_string());
    auto in = [](const std::unordered_set<std::string>& set, const Json& v) { return v.is_string() && set.count(v.as_string()) != 0; };
    std::unordered_map<std::string, std::string> releasing;
    for (const Json& t : blocks_of("transfers")) {
        const Json& fr = t.get("from");
        if (!in(paths, fr)) continue;
        std::string tname = js_str(t.get("name"));
        auto held = releasing.find(fr.as_string());
        if (held != releasing.end())
            throw ValidationError("'" + fr.as_string() + "' has two releases, '" + held->second + "' and '" + tname +
                                  "'. A block has one -- for a path the flux out of the far end, for waste packages what leaves them -- and each "
                                  "of these would deliver the whole of it, so the model would release twice what the block let go.", tname);
        releasing[fr.as_string()] = tname;
    }
    for (const Json& t : blocks_of("transfers")) {
        const Json& fr = t.get("from");
        const Json& to = t.get("to");
        std::string tname = js_str(t.get("name"));
        if (!fr.is_null() && !in(compartments, fr) && !in(paths, fr)) throw ValidationError("Unknown source compartment '" + js_str(fr) + "'", tname);
        if (!to.is_null() && !in(compartments, to) && !in(paths, to)) throw ValidationError("Unknown target compartment '" + js_str(to) + "'", tname);
        if (in(paths, fr)) {
            if (!is_false(t.get("multiply_by_donor")))
                throw ValidationError("'" + js_str(fr) + "' is a far-field path, so there is no single donor inventory to multiply by: a release "
                                      "carries the flux out of the path itself.", tname);
            if (in(paths, to))
                throw ValidationError("A release from one far-field path cannot be delivered straight into another: give it a compartment in between.", tname);
        }
        if (fr.is_null() && to.is_null()) throw ValidationError("A transfer must have a source, a target, or both", tname);
        if (fr == to) throw ValidationError("Source and target are both '" + js_text(fr) + "'", tname);
    }
    for (const Json& s : blocks_of("inflows")) {
        const Json& to = s.get("to");
        if (!(in(compartments, to) || in(paths, to))) throw ValidationError("Unknown target compartment '" + js_text(to) + "'", js_str(s.get("name")));
    }
    std::unordered_map<std::string, Json> holds;
    for (const char* c : {"compartments", "farfields", "waste_packages"})
        for (const Json& b : blocks_of(c)) holds[b.get("qname").as_string()] = b;
    auto size_of = [&](const std::string& n) -> std::optional<int> {
        return index_space.has_list(n) ? std::optional<int>(index_space.list_size(n)) : std::nullopt;
    };
    for (const char* c : {"transfers", "inflows"})
        for (const Json& flux : blocks_of(c)) {
            if (js_truthy(flux.get("sum_extra_indices"))) continue;
            for (const char* end : {"from", "to"}) {
                const Json& e = flux.get(end);
                if (!e.is_string()) continue;
                auto at = holds.find(e.as_string());
                if (at == holds.end()) continue;
                std::vector<std::string> summed = summed_dims(index_lists, strings_of(flux.get("index_lists")), strings_of(at->second.get("index_lists")));
                if (summed.empty()) continue;
                const std::string& fq = flux.get("qname").as_string();
                throw ValidationError(summed_dims_why(fq, end, at->second.get("qname").as_string(), summed, size_of), fq);
            }
        }
    for (const Problem& prob : waste_problems()) throw ValidationError(prob.message, prob.name);
    for (const Problem& prob : disruption_problems()) throw ValidationError(prob.message, prob.name);
    std::optional<std::string> root;
    if (material_list_name) root = index_space.get_list(*material_list_name).root_name;
    for (const char* c : {"farfields", "waste_packages"})
        for (const Json& f : blocks_of(c)) {
            const std::string& q = f.get("qname").as_string();
            if (f.get("kind") == "farfield") {
                std::optional<std::string> problem = structure_problem(f);
                if (!problem) problem = geometry_problem(f);
                if (!problem) problem = rock_problem(f);
                if (problem) throw ValidationError(*problem, q);
            }
            std::vector<std::string> chains_along;
            for (const auto& d : strings_of(f.get("index_lists")))
                if (root && index_space.has_list(d) && index_space.get_list(d).mapping.is_null() && index_space.get_list(d).root_name == root)
                    chains_along.push_back(d);
            if (chains_along.size() > 1) {
                std::string what = f.get("kind") == "farfield" ? "A far-field path runs" : "Waste packages run";
                throw ValidationError(what + " one decay chain along one dimension, and '" + js_str(f.get("name")) + "' is indexed by " +
                                      std::to_string(chains_along.size()) + " of them (" + join(chains_along, " \xc3\x97 ") +
                                      "). A sub-set of the radionuclides is a second set of the same nuclides: pick the one the path carries.", q);
            }
        }
    for (const Json& l : blocks_of("lookups")) {
        const std::string& q = l.get("qname").as_string();
        if (!among(INTERPOLATIONS, l.get("interpolation")))
            throw ValidationError("'" + js_text(l.get("interpolation")) + "' is not an interpolation rule (" + join(INTERPOLATIONS, ", ") + ")", q);
        const Json& arg = l.get("argument");
        if (!arg.is_null() && !is_name(std::string_view(js_str(arg)))) throw ValidationError("'" + js_str(arg) + "' is not a valid argument name", q);
    }
    for (const Json& f : blocks_of("functions")) {
        const std::string& q = f.get("qname").as_string();
        std::unordered_set<std::string> seen;
        for (const auto& par : strings_of(f.get("parameters"))) {
            if (!is_name(std::string_view(par)))
                throw ValidationError("'" + par + "' is not a valid parameter name (letters, digits and underscore; must not start with a digit)", q);
            if (is_reserved_name(par)) throw ValidationError("'" + par + "' is a reserved name, so it cannot be a parameter", q);
            if (!seen.insert(par).second) throw ValidationError("'" + par + "' is named twice in the parameters of '" + js_str(f.get("name")) + "'", q);
        }
    }
    for (const Json& o : blocks_of("index_reductions")) {
        const std::string& q = o.get("qname").as_string();
        if (!among(OPERATIONS, o.get("operation")))
            throw ValidationError("'" + js_text(o.get("operation")) + "' is not a reduction (" + join(OPERATIONS, ", ") + ")", q);
        if (o.get("operation") == "percentile") {
            const Json& pc = o.get("percentile");
            if (!(pc.is_number() && 0 <= pc.as_double() && pc.as_double() <= 100))
                throw ValidationError("A percentile must be between 0 and 100; '" + py_text(pc) + "' is not", q);
        }
        if (!js_truthy(o.get("target"))) throw ValidationError("An index operation needs a block to reduce", q);
    }
    for (const Json& m : blocks_of("min_maxes"))
        if (!among(EXTREMES, m.get("operation")))
            throw ValidationError("'" + js_text(m.get("operation")) + "' is not a min/max operation (" + join(EXTREMES, ", ") + ")", m.get("qname").as_string());
    for (const Json& e : blocks_of("triggers"))
        if (!among(DIRECTIONS, e.get("direction")))
            throw ValidationError("'" + js_text(e.get("direction")) + "' is not a crossing direction (" + join(DIRECTIONS, ", ") + ")", e.get("qname").as_string());
    for (const Json& a : blocks_of("block_reductions")) {
        const std::string& q = a.get("qname").as_string();
        if (!among(AGGREGATE_OPERATIONS, a.get("operation")))
            throw ValidationError("'" + js_text(a.get("operation")) + "' is not a reduction an aggregate can do (" + join(AGGREGATE_OPERATIONS, ", ") + ")", q);
        bool any = !a.get("targets").empty();
        for (const Json& e : a.get("entries").arr())
            if (js_truthy(e.get("targets"))) any = true;
        if (!any) throw ValidationError("An aggregate needs at least one block to reduce", q);
    }
    {
        std::vector<std::string> unknown;
        for (const auto& n : nuclide_names())
            if (!half_life_of(n)) unknown.push_back(n);
        if (!unknown.empty())
            throw ValidationError("No half-life for " + join(unknown, ", ") + ". Set one on the Decay tab -- or type \"stable\" there for a nuclide "
                                  "that does not decay -- or give it under \"half_lives\" in the project file.");
    }
    for (const Json& b : everything) {
        std::string bname = js_str(b.get("name"));
        std::vector<std::string> dims = strings_of(b.get("index_lists"));
        for (const Json& entry : b.get("entries").arr()) {
            const Json& index = entry.get("index");
            if (!index.is_object()) continue;
            for (const auto& [list_name, index_name] : index.obj()) {
                if (!index_space.has_list(list_name)) throw ValidationError("Entry refers to unknown index list '" + list_name + "'", bname);
                if (!among(dims, list_name))
                    throw ValidationError("Entry is keyed by '" + list_name + "', which '" + bname + "' is not indexed by", bname);
                bool found = false;
                for (const auto& i : index_space.get_list(list_name).indices)
                    if (index_name.is_string() && i.name == index_name.as_string()) found = true;
                if (!found) throw ValidationError("'" + js_text(index_name) + "' is not an index of '" + list_name + "'", bname);
            }
        }
    }
    const Json& sim = simulation;
    double start = sim.get("start_time").as_double(), end = sim.get("end_time").as_double();
    if (!(end > start)) throw ValidationError("End time must be greater than start time");
    if (sim.get("spacing") == "log" && start < 0) throw ValidationError("Logarithmic output needs a non-negative start time");
    const Json& points = sim.get("output_points");
    // Only the two shorthands are spread from the count: a list of series carries its own, the
    // solver's own steps are however many it takes, and "both" is those two together.
    bool counted = sim.get("spacing") == "log" || sim.get("spacing") == "linear";
    if (counted && !(points.is_number() && points.as_double() >= 2)) throw ValidationError("At least 2 output points are required");
    if (counted && points.is_number() && points.as_double() > MAX_OUTPUT_POINTS)
        throw ValidationError(js_text(points) + " output points is more than this can report (" + std::to_string(MAX_OUTPUT_POINTS) + ").");
    for (const auto& [key, label] : {std::pair<const char*, const char*>{"rtol", "Relative"}, {"abstol", "Absolute"}}) {
        double v = js_number_of(sim.get(key));
        if (!(v > 0)) throw ValidationError(std::string(label) + " tolerance must be greater than zero (got " + py_text(sim.get(key)) + ")");
    }
}

std::vector<Problem> Project::waste_problems() const {
    std::vector<Problem> out;
    for (const Json& b : blocks_of("waste_packages")) {
        const std::string& name = b.get("qname").as_string();
        Json f = js_truthy(b.get("failure")) ? b.get("failure") : Json("never");
        if (!among(FAILURES, f)) {
            out.push_back({name, "failure", "'" + js_text(f) + "' is not a way for packages to fail (" + join(FAILURES, ", ") + ")."});
            continue;
        }
        const std::string& fail = f.as_string();
        for (const auto& key : failure_keys(fail))
            if (text_of(b.get(key)).empty())
                out.push_back({name, key, "Packages that fail " + failure_label(fail) + " need " + lowercase(waste_label(key)) + ": a number or an equation."});
        auto num = [&](const char* key) -> std::optional<double> {
            double v = js_number_of(std::string_view(text_of(b.get(key))));
            return std::isfinite(v) ? std::optional<double>(v) : std::nullopt;
        };
        if (fail == "uniform") {
            auto a = num("fail_from"), z = num("fail_to");
            if (a && z && !(*z > *a))
                out.push_back({name, "fail_to", "The failures end (" + js_number(*z) + ") before they begin (" + js_number(*a) + ")."});
        }
        if (fail == "weibull" && num("fail_shape") && !(*num("fail_shape") > 0)) out.push_back({name, "fail_shape", "A Weibull shape has to be above 0."});
        if (fail == "weibull" && num("fail_scale") && !(*num("fail_scale") > 0)) out.push_back({name, "fail_scale", "A Weibull scale has to be above 0."});
        if (fail == "exponential" && num("fail_rate") && *num("fail_rate") < 0) out.push_back({name, "fail_rate", "A failure rate cannot be negative."});
        const Json& np = b.get("packages");
        if (!np.is_null() && !(np == "")) {
            double n = js_number_of(np);
            if (!is_whole(n) || n < 1) out.push_back({name, "packages", "'" + js_text(np) + "' is not a number of packages: a whole number, at least 1."});
        }
        std::vector<std::pair<Json, Json>> holders = {{b, Json()}};
        for (const Json& e : items(b.get("entries"))) holders.emplace_back(e, e.get("index"));
        for (const auto& [values, where] : holders) {
            auto at = [&](const char* key) -> std::optional<double> {
                std::string text = text_of(values.get(key));
                double v = js_number_of(std::string_view(text));
                return (!text.empty() && std::isfinite(v)) ? std::optional<double>(v) : std::nullopt;
            };
            std::string cell = (where.is_object() && !where.empty()) ? " (at " + values_joined(where, " \xc2\xb7 ") + ")" : "";
            auto irf = at("irf");
            if (irf && (*irf < 0 || *irf > 1)) out.push_back({name, "irf", "The instant release fraction is between 0 and 1" + cell + "."});
            auto d = at("degradation_rate");
            if (d && *d < 0) out.push_back({name, "degradation_rate", "A degradation rate cannot be negative" + cell + "."});
        }
    }
    return out;
}

std::vector<Problem> Project::disruption_problems() const {
    std::vector<Problem> out;
    std::unordered_set<std::string> wastes, compartments;
    for (const Json& w : blocks_of("waste_packages")) wastes.insert(w.get("qname").as_string());
    for (const Json& c : blocks_of("compartments")) compartments.insert(c.get("qname").as_string());
    for (const Json& b : blocks_of("events")) {
        const std::string& name = b.get("qname").as_string();
        Json timing = js_truthy(b.get("timing")) ? b.get("timing") : Json("at");
        if (!among(TIMINGS, timing)) {
            out.push_back({name, "timing", "'" + js_text(timing) + "' is not a way for an event to happen (" + join(TIMINGS, ", ") + ")."});
            continue;
        }
        if (timing == "at" && text_of(b.get("at")).empty())
            out.push_back({name, "at", "An event at a time needs the time: a number or an equation."});
        if (timing == "poisson" && text_of(b.get("rate")).empty())
            out.push_back({name, "rate", "A random event needs its rate: occurrences per unit time."});
        // Whether the name is a trigger is the build's to say, as for a snapshot's.
        if (timing == "trigger" && text_of(b.get("trigger")).empty())
            out.push_back({name, "trigger", "An event set off by a trigger needs the trigger: name one."});
        auto num = [](const Json& text) -> std::optional<double> {
            std::string t = text_of(text);
            if (t.empty()) return std::nullopt;
            double v = js_number_of(std::string_view(t));
            return std::isfinite(v) ? std::optional<double>(v) : std::nullopt;
        };
        if (timing == "poisson" && num(b.get("rate")) && *num(b.get("rate")) < 0) out.push_back({name, "rate", "A rate cannot be negative."});
        auto fr = num(b.get("from")), un = num(b.get("until"));
        if (timing == "poisson" && fr && un && !(*un > *fr))
            out.push_back({name, "until", "The window ends (" + py_repr(*un) + ") before it opens (" + py_repr(*fr) + ")."});
        Json actions = normalise_actions(b.get("actions"));
        for (std::size_t k = 0; k < actions.size(); k++) {
            const Json& a = actions[k];
            std::string field = "actions[" + std::to_string(k) + "]";
            std::string kind = a.get("kind").as_string();
            if (!among(ACTIONS, kind)) {
                out.push_back({name, field, "'" + kind + "' is not something an event can do (" + join(ACTIONS, ", ") + ")."});
                continue;
            }
            if (kind == "fail") {
                if (!js_truthy(a.get("block"))) out.push_back({name, field, "Which packages fail? Name a waste-package block."});
                else if (!wastes.count(a.get("block").as_string()))
                    out.push_back({name, field, "'" + a.get("block").as_string() + "' is not a set of waste packages, so it has no packages to fail."});
            } else {
                if (!js_truthy(a.get("from"))) out.push_back({name, field, "Move what? Name a compartment."});
                else if (!compartments.count(a.get("from").as_string()))
                    out.push_back({name, field, "'" + a.get("from").as_string() + "' is not a compartment, so there is nothing to move out of it."});
                if (!a.get("to").is_null() && !compartments.count(a.get("to").as_string()))
                    out.push_back({name, field, "'" + a.get("to").as_string() + "' is not a compartment, so nothing can be moved into it."});
                if (!a.get("to").is_null() && a.get("to") == a.get("from"))
                    out.push_back({name, field, "Moving " + js_str(a.get("from")) + " into itself changes nothing."});
            }
            auto f = num(a.get("fraction"));
            if (f && (*f < 0 || *f > 1)) out.push_back({name, field, "A share is between 0 and 1; " + py_repr(*f) + " is not."});
        }
    }
    return out;
}

// --- the output grid ---------------------------------------------------------------------------------

std::vector<double> Project::time_grid() const {
    const Json& sim = simulation;
    std::string key = compact(sim.get("start_time")) + "|" + compact(sim.get("end_time")) + "|" + compact(sim.get("output_points")) + "|" +
                      js_str(sim.get("spacing")) + "|" + (output_times.empty() ? std::string() : compact(output_times));
    if (!grid_.empty() && grid_key_ == key) return grid_;
    double start = sim.get("start_time").as_double(), end = sim.get("end_time").as_double();
    const Json& spacing = sim.get("spacing");
    std::vector<double> t;
    if (spacing == "series" || (spacing == "both" && !output_times.empty())) {
        t = combine_series(output_times, start, end);
    } else {
        int n = shorthand_points(sim.get("output_points"));
        t.assign(static_cast<std::size_t>(n), 0.0);
        if (spacing == "log" || spacing == "solver" || spacing == "both") {
            double lo = start > 0 ? start : std::max(end, 1.0) * 1e-6;
            double a = js_log(lo), b = js_log(end);
            t[0] = start;
            for (int i = 1; i < n; i++) t[static_cast<std::size_t>(i)] = js_exp(a + ((b - a) * i) / (n - 1));
            t[static_cast<std::size_t>(n - 1)] = end;
        } else {
            for (int i = 0; i < n; i++) t[static_cast<std::size_t>(i)] = start + ((end - start) * i) / (n - 1);
        }
    }
    grid_key_ = key;
    grid_ = t;
    return t;
}

}  // namespace kompartment
