#include "model/keys.hpp"

#include <unordered_map>

#include "engine/farfield_domain.hpp"
#include "model/indexlists.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

using Mapping = std::unordered_map<std::string, std::string>;

const Mapping KEYS_PROJECT = {{"halfLives", "half_lives"}, {"indexLists", "index_lists"}};
const Mapping KEYS_COLLECTION = {{"sources", "inflows"}, {"discrete_events", "triggers"}, {"disruptions", "events"},
                                 {"index_operations", "index_reductions"}, {"aggregates", "block_reductions"}};
const Mapping KEYS_INDEX_LIST = {{"forMaterials", "for_contaminants"}, {"for_materials", "for_contaminants"},
                                 {"forNuclides", "for_nuclides"}, {"subSetOf", "sub_set_of"}};
const Mapping KEYS_SIMULATION = {{"startTime", "start_time"}, {"endTime", "end_time"}, {"outputPoints", "output_points"},
                                 {"timeUnit", "time_unit"}};
const Mapping OLD_SOLVER_IDS = {{"ode15s", "ndf"}, {"ode15s_bdf", "bdf"}, {"ode23s", "ros23"}, {"ode45", "dp45"}};
const Mapping KEYS_VIEW = {
    {"showExpressions", "show_expressions"}, {"showParameters", "show_parameters"}, {"showLookups", "show_lookups"},
    {"showReductions", "show_reductions"}, {"showInfluences", "show_influences"}, {"showSinks", "show_sinks"},
    {"connectionLabel", "connection_label"}};
const Mapping KEYS_BLOCK = {
    {"indexLists", "index_lists"}, {"handleDecay", "handle_decay"}, {"multiplyByDonor", "multiply_by_donor"},
    {"reset_event", "reset_trigger"}, {"start_event", "start_trigger"}, {"stop_event", "stop_trigger"},
    {"event", "trigger"}, {"resetEvent", "reset_trigger"}, {"startEvent", "start_trigger"},
    {"stopEvent", "stop_trigger"}, {"perNuclide", "per_nuclide"}, {"valuesByNuclide", "values_by_nuclide"}};
const Mapping KEYS_ENTRY = {{"multiplyByDonor", "multiply_by_donor"}, {"reset_event", "reset_trigger"},
                            {"start_event", "start_trigger"}, {"stop_event", "stop_trigger"}, {"event", "trigger"}};

// `obj` with its keys renamed, each where the old one stood; the new spelling wins.
Json rename_keys(const Json& obj, const Mapping& mapping) {
    if (!obj.is_object()) return obj;
    JObject out;
    out.reserve(obj.size());
    for (const auto& [k, v] : obj.obj()) {
        auto to = mapping.find(k);
        if (to == mapping.end()) {
            out.set(k, v);
            continue;
        }
        if (obj.has(to->second)) continue;
        out.set(to->second, v);
    }
    return Json(std::move(out));
}

Json migrate_farfield_targets(const Json& raw) {
    const Json& farfields = raw.get("farfields");
    if (!farfields.is_array()) return raw;
    Json moved = Json::array(), kept = Json::array();
    for (const Json& f : farfields.arr()) {
        const Json& to = f.get("to");
        if (!f.is_object() || to.is_null() || to == "") {
            kept.push(f);
            continue;
        }
        Json g = Json::object();
        for (const auto& [k, v] : f.obj())
            if (k != "to") g.set(k, v);
        kept.push(g);
        const Json& name = f.get("name");
        Json t = Json::object();
        if (js_truthy(f.get("system"))) t.set("system", f.get("system"));
        t.set("name", Json(js_truthy(name) ? js_text(name) + "_release" : std::string("release")));
        t.set("from", name);
        t.set("to", Json(js_str(to)));
        t.set("rate", js_truthy(name) ? name : Json("0"));
        t.set("multiply_by_donor", Json(false));
        moved.push(t);
    }
    if (moved.empty()) return raw;
    Json out = raw.shallow();
    out.set("farfields", kept);
    Json transfers = Json::array();
    if (raw.get("transfers").is_array())
        for (const Json& t : raw.get("transfers").arr()) transfers.push(t);
    for (const Json& t : moved.arr()) transfers.push(t);
    out.set("transfers", transfers);
    return out;
}

Json migrate_farfield_defaults(const Json& raw) {
    const Json& farfields = raw.get("farfields");
    if (!farfields.is_array()) return raw;
    bool changed = false;
    Json out_f = Json::array();
    for (const Json& f : farfields.arr()) {
        if (!f.is_object()) {
            out_f.push(f);
            continue;
        }
        Json g;
        for (const auto& [k, v] : farf_legacy().obj()) {
            if (f.has(k)) continue;
            if (g.is_null()) g = f.shallow();
            g.set(k, v);
        }
        if (g.is_null()) {
            out_f.push(f);
            continue;
        }
        changed = true;
        out_f.push(g);
    }
    if (!changed) return raw;
    Json out = raw.shallow();
    out.set("farfields", out_f);
    return out;
}

}  // namespace

const std::vector<std::string>& collections() {
    static const std::vector<std::string> v = {
        "compartments", "expressions", "parameters", "lookups", "index_reductions", "block_reductions", "min_maxes",
        "running_means", "snapshots", "delays", "triggers", "farfields", "waste_packages", "events", "functions",
        "transfers", "inflows"};
    return v;
}

Json migrate_keys(const Json& raw) {
    if (!raw.is_object()) return raw;
    Json out = rename_keys(rename_keys(raw.copy(), KEYS_PROJECT), KEYS_COLLECTION);
    if (out.get("index_lists").is_array()) {
        Json lists = Json::array();
        for (const Json& l : out.get("index_lists").arr()) lists.push(rename_keys(l, KEYS_INDEX_LIST));
        out.set("index_lists", lists);
    }
    out = split_material_roles(rename_built_in_lists(migrate_farfield_defaults(migrate_farfield_targets(out))));
    if (out.get("simulation").is_object()) {
        Json sim = rename_keys(out.get("simulation"), KEYS_SIMULATION);
        const Json& solver = sim.get("solver");
        if (solver.is_string()) {
            auto it = OLD_SOLVER_IDS.find(solver.as_string());
            if (it != OLD_SOLVER_IDS.end()) sim.set("solver", Json(it->second));
        }
        if (sim.get("solver") == "bdf") {
            // The plain BDFs are the NDF with its switch on.
            sim.set("solver", Json("ndf"));
            sim.set("bdf", Json(true));
        }
        out.set("simulation", sim);
    }
    if (out.get("view").is_object()) out.set("view", rename_keys(out.get("view"), KEYS_VIEW));
    for (const auto& key : collections()) {
        const Json& blocks = out.get(key);
        if (!blocks.is_array()) continue;
        Json renamed = Json::array();
        for (const Json& b : blocks.arr()) {
            if (!b.is_object()) {
                renamed.push(b);
                continue;
            }
            Json nb = rename_keys(b, KEYS_BLOCK);
            if (nb.get("entries").is_array()) {
                Json entries = Json::array();
                for (const Json& e : nb.get("entries").arr()) entries.push(rename_keys(e, KEYS_ENTRY));
                nb.set("entries", entries);
            }
            renamed.push(nb);
        }
        out.set(key, renamed);
    }
    return out;
}

}  // namespace kompartment
