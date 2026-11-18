#include "model/indexlists.hpp"

#include <algorithm>
#include <set>
#include <unordered_map>

#include "model/decay.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

const Json EMPTY_LIST = Json::array();

// A raw value as a list, or an empty one.
const JArray& items(const Json& v) { return v.is_array() ? v.arr() : EMPTY_LIST.arr(); }

bool contains(const std::vector<std::string>& v, const std::string& s) { return std::find(v.begin(), v.end(), s) != v.end(); }

// A copy of a dictionary with keys set, each where it stood or last.
Json copy_with(const Json& d, std::initializer_list<std::pair<const char*, Json>> pairs) {
    Json out = d.shallow();
    for (const auto& [k, v] : pairs) out.set(k, v);
    return out;
}

std::string replace_all(std::string s, char from, char to) {
    std::replace(s.begin(), s.end(), from, to);
    return s;
}

}  // namespace

std::string was_called(std::string_view list) {
    if (list == NUCLIDE_LIST) return "Nuclide";
    if (list == ELEMENT_LIST) return "Element";
    if (list == MATERIAL_LIST) return "Materials";
    return "";
}

bool is_auto_dim_kind(std::string_view kind) {
    return kind == "expression" || kind == "parameter" || kind == "lookup" || kind == "block_reduction" || kind == "index_reduction";
}

Json index_name(const Json& index) { return index.is_string() ? index : index.get("name"); }

const Json& find_list(const Json& lists, const Json& name) {
    for (const Json& l : items(lists))
        if (l.is_object() && l.get("name") == name) return l;
    return Json::null_value;
}
const Json& find_list(const Json& lists, std::string_view name) {
    for (const Json& l : items(lists))
        if (l.is_object() && l.get("name") == name) return l;
    return Json::null_value;
}

Json parent_list_name(const Json& lst) {
    if (lst.is_null()) return Json();
    const Json& s = lst.get("sub_set_of");
    if (js_truthy(s)) return s;
    const Json& m = lst.get("mapping");
    if (!js_truthy(m)) return Json();
    return m.is_string() ? m : m.get("to");
}

Lineage lineage(const Json& lists, const Json& name) {
    Lineage out;
    Json at = name;
    std::vector<Json> seen;
    auto was_seen = [&](const Json& v) {
        for (const Json& s : seen)
            if (s == v) return true;
        return false;
    };
    while (js_truthy(at) && !was_seen(at)) {
        seen.push_back(at);
        const Json& lst = find_list(lists, at);
        const Json& m = lst.get("mapping");
        Json mto = js_truthy(m) ? (m.is_object() ? m.get("to") : m) : Json();
        Json nxt = js_truthy(mto) ? mto : lst.get("sub_set_of");
        if (!js_truthy(nxt)) break;
        if (js_truthy(mto)) out.mapped = true;
        out.above.emplace_back(js_str(nxt), js_truthy(mto));
        at = nxt;
    }
    out.root = js_truthy(at) ? at : name;
    return out;
}

Json root_of(const Json& lists, const Json& name) { return lineage(lists, name).root; }

bool list_applies(const Json& lst, std::string_view kind) {
    if (lst.is_null()) return false;
    if (!js_truthy(lst.get("auto"))) return true;
    return is_auto_dim_kind(kind);
}

std::string list_applies_why(const Json& lst, std::string_view kind) {
    if (list_applies(lst, kind)) return "";
    if (lst.is_null()) return "That index list is not in this model.";
    std::string one = lst.get("auto") == "compartments" ? "compartment" : "transfer";
    std::string name = js_str(lst.get("name"));
    std::string own = kind == one ? "A " + one + " is one of them already: that is what lets a value indexed by '" + name +
                                    "' be read inside a " + one + " with no index at all. " : "";
    return "'" + name + "' has one index per " + one + ", and a " + replace_all(std::string(kind), '_', ' ') +
           " cannot be indexed by them. " + own + "Only an expression, a parameter, a lookup table, an aggregate or an index operation can.";
}

std::optional<DimensionClash> clashing_dimensions(const Json& lists, const std::vector<std::string>& dims) {
    struct Seen {
        std::string name;
        Lineage line;
    };
    std::vector<Seen> seen;
    for (const auto& d : dims) seen.push_back({d, lineage(lists, Json(d))});
    auto auto_of = [&](const Json& n) -> Json {
        const Json& l = find_list(lists, n);
        return l.is_null() ? Json() : l.get("auto");
    };
    auto link_to = [](const Lineage& line, const std::string& name) -> const std::pair<std::string, bool>* {
        for (const auto& x : line.above)
            if (x.first == name) return &x;
        return nullptr;
    };
    for (std::size_t i = 0; i < seen.size(); i++) {
        for (std::size_t j = i + 1; j < seen.size(); j++) {
            const Seen& a = seen[i];
            const Seen& b = seen[j];
            if (a.name == b.name) continue;
            if (a.line.root == b.line.root) {
                const auto* b_above_a = link_to(a.line, b.name);
                const auto* a_above_b = link_to(b.line, a.name);
                const auto* link = b_above_a ? b_above_a : a_above_b;
                DimensionClash c;
                c.a = a.name;
                c.b = b.name;
                c.root = js_str(a.line.root);
                c.how = !link ? "siblings" : (link->second ? "grouping" : "sub_set");
                if (b_above_a) c.below = a.name;
                else if (a_above_b) c.below = b.name;
                if (c.below) c.above = *c.below == a.name ? b.name : a.name;
                return c;
            }
            Json ra = auto_of(a.line.root), rb = auto_of(b.line.root);
            if (js_truthy(ra) && js_truthy(rb) && ra != rb) {
                DimensionClash c;
                c.a = a.name;
                c.b = b.name;
                c.how = "blocks";
                return c;
            }
        }
    }
    return std::nullopt;
}

std::string clashing_dimensions_why(const std::optional<DimensionClash>& clash) {
    if (!clash) return "";
    const std::string& a = clash->a;
    const std::string& b = clash->b;
    if (clash->how == "blocks")
        return "'" + a + "' has one index per compartment and '" + b + "' one per transfer, and a block cannot be indexed by both. Pick one.";
    if (clash->how == "siblings")
        return "'" + a + "' and '" + b + "' are both taken from '" + clash->root.value_or("") +
               "', so a block indexed by both would be indexed by the same dimension twice. Pick one.";
    const std::string below = clash->below.value_or(""), above = clash->above.value_or("");
    if (clash->how == "grouping")
        return "'" + below + "' is a grouping of '" + above + "', so a block indexed by both would be indexed by the same dimension twice. Pick one.";
    return "'" + below + "' is a sub-set of '" + above + "', so a block indexed by both would be indexed by the same dimension twice. Pick one.";
}

namespace {

// The dimensions a flux varies along: the scenario list is not one.
std::vector<std::string> plain(const Json& lists, const std::vector<std::string>* dims) {
    std::vector<std::string> out;
    if (!dims) return out;
    for (const auto& d : *dims) {
        const Json& lst = find_list(lists, std::string_view(d));
        if (!lst.is_null() && js_truthy(lst.get("for_scenarios"))) continue;
        out.push_back(d);
    }
    return out;
}

}  // namespace

std::optional<SharedDims> shared_dims(const Json& lists, const std::vector<std::string>* source,
                                      const std::vector<std::string>* target) {
    if (!source && !target) return std::nullopt;
    if (!source || !target) return SharedDims{plain(lists, source ? source : target), {}};
    std::vector<std::string> a = plain(lists, source), b = plain(lists, target);
    if (a.size() != b.size()) return std::nullopt;
    if (a.empty()) return SharedDims{};
    std::vector<std::string> rest = b;
    std::vector<std::optional<std::string>> matched;
    for (const auto& s : a) {
        Json rs = root_of(lists, Json(s));
        std::size_t k = 0;
        for (; k < rest.size(); k++)
            if (root_of(lists, Json(rest[k])) == rs) break;
        if (k == rest.size()) {
            matched.emplace_back(std::nullopt);
        } else {
            matched.emplace_back(rest[k]);
            rest.erase(rest.begin() + static_cast<std::ptrdiff_t>(k));
        }
    }
    SharedDims out;
    for (std::size_t i = 0; i < a.size(); i++) {
        if (!matched[i]) return std::nullopt;
        const std::string& s = a[i];
        const std::string& t = *matched[i];
        if (s == t) {
            out.dims.push_back(s);
            continue;
        }
        const Json& ls = find_list(lists, std::string_view(s));
        const Json& lt = find_list(lists, std::string_view(t));
        std::optional<std::string> narrower;
        if (ls.get("sub_set_of") == t) narrower = s;
        else if (lt.get("sub_set_of") == s) narrower = t;
        if (!narrower) return std::nullopt;
        out.dims.push_back(*narrower);
        out.shared.push_back({s, t, *narrower});
    }
    return out;
}

std::vector<std::string> summed_dims(const Json& lists, const std::vector<std::string>& flux_dims,
                                     const std::vector<std::string>& end_dims) {
    std::vector<Json> roots;
    for (const auto& d : plain(lists, &end_dims)) roots.push_back(root_of(lists, Json(d)));
    std::vector<std::string> out;
    for (const auto& d : plain(lists, &flux_dims)) {
        Json r = root_of(lists, Json(d));
        bool found = false;
        for (const Json& x : roots)
            if (x == r) { found = true; break; }
        if (!found) out.push_back(d);
    }
    return out;
}

bool is_decay_dim(const Json& lists, const Json& name, const Json& material) {
    if (!(js_truthy(name) && js_truthy(material))) return false;
    const Json& lst = find_list(lists, name);
    if (lst.is_null() || js_truthy(lst.get("mapping"))) return false;
    return root_of(lists, name) == root_of(lists, material);
}

// --- reading a file ----------------------------------------------------------------------------------

Json rename_built_in_lists(const Json& raw) {
    if (!raw.is_object()) return raw;
    const JArray& lists = items(raw.get("index_lists"));
    std::vector<Json> taken;
    for (const Json& l : lists)
        if (l.is_object()) taken.push_back(l.get("name"));
    auto is_taken = [&](const char* name) {
        for (const Json& t : taken)
            if (t == name) return true;
        return false;
    };
    auto flagged = [](const Json& l) {
        if (!l.is_object()) return false;
        for (const char* k : {"for_contaminants", "for_materials", "forMaterials"})
            if (!l.get(k).is_null()) return js_truthy(l.get(k));
        return false;
    };
    const Json* material = nullptr;
    for (const Json& l : lists)
        if (flagged(l)) { material = &l; break; }
    std::unordered_map<std::string, std::string> mapping;
    auto rename = [&](const char* to) {
        std::string was = was_called(to);
        if (!(was.empty() || is_taken(to))) mapping[was] = to;
    };
    if (material ? material->get("name") == was_called(NUCLIDE_LIST) : js_truthy(raw.get("nuclides"))) rename(NUCLIDE_LIST);
    const Json* element = nullptr;
    for (const Json& l : lists) {
        if (!(l.is_object() && l.get("name") == was_called(ELEMENT_LIST))) continue;
        const Json& m = l.get("mapping");
        if (js_truthy(l.get("for_elements")) ||
            (m.is_object() && js_truthy(m.get("to")) && material && m.get("to") == material->get("name"))) {
            element = &l;
            break;
        }
    }
    if (element) rename(ELEMENT_LIST);
    if (material && material->get("name") == was_called(MATERIAL_LIST)) rename(MATERIAL_LIST);
    if (mapping.empty()) return raw;
    auto to = [&](const Json& name) -> Json {
        if (!name.is_string()) return name;
        auto it = mapping.find(name.as_string());
        return it == mapping.end() ? name : Json(it->second);
    };
    auto mapped = [&](const std::string& name) { return mapping.count(name) != 0; };
    Json out = raw.shallow();
    if (!lists.empty()) {
        Json new_lists = Json::array();
        for (const Json& l : lists) {
            if (!l.is_object()) {
                new_lists.push(l);
                continue;
            }
            Json n = copy_with(l, {{"name", to(l.get("name"))}});
            if (js_truthy(l.get("sub_set_of"))) n.set("sub_set_of", to(l.get("sub_set_of")));
            const Json& m = l.get("mapping");
            if (m.is_object() && js_truthy(m.get("to"))) n.set("mapping", copy_with(m, {{"to", to(m.get("to"))}}));
            new_lists.push(n);
        }
        out.set("index_lists", new_lists);
    }
    for (const auto& [key, value] : raw.obj()) {
        if (key == "index_lists" || !value.is_array()) continue;
        bool changed = false;
        Json blocks = Json::array();
        for (const Json& b : value.arr()) {
            if (!b.is_object()) {
                blocks.push(b);
                continue;
            }
            const Json& dims = b.get("index_lists");
            bool needs_dims = false;
            if (dims.is_array())
                for (const Json& d : dims.arr())
                    if (d.is_string() && mapped(d.as_string())) needs_dims = true;
            const Json& entries = b.get("entries");
            bool needs_entries = false;
            if (entries.is_array())
                for (const Json& e : entries.arr()) {
                    if (!(e.is_object() && e.get("index").is_object())) continue;
                    for (const auto& [d, i] : e.get("index").obj())
                        if (mapped(d)) needs_entries = true;
                }
            if (!needs_dims && !needs_entries) {
                blocks.push(b);
                continue;
            }
            changed = true;
            Json nb = b.shallow();
            if (needs_dims) {
                Json nd = Json::array();
                for (const Json& d : dims.arr()) nd.push(to(d));
                nb.set("index_lists", nd);
            }
            if (needs_entries) {
                Json ne = Json::array();
                for (const Json& e : entries.arr()) {
                    if (e.is_object() && e.get("index").is_object()) {
                        Json index = Json::object();
                        for (const auto& [d, i] : e.get("index").obj()) index.set(js_str(to(Json(d))), i);
                        ne.push(copy_with(e, {{"index", index}}));
                    } else {
                        ne.push(e);
                    }
                }
                nb.set("entries", ne);
            }
            blocks.push(nb);
        }
        if (changed) out.set(key, blocks);
    }
    return out;
}

std::string free_name(const std::vector<std::string>& taken, const std::string& want) {
    std::string name = want;
    int n = 2;
    while (contains(taken, name)) {
        name = want + std::to_string(n);
        n++;
    }
    return name;
}

namespace {
std::vector<std::string> names_of(const JArray& lists) {
    std::vector<std::string> out;
    for (const Json& l : lists)
        if (l.is_object() && l.get("name").is_string()) out.push_back(l.get("name").as_string());
    return out;
}
}  // namespace

Json split_material_roles(const Json& raw) {
    if (!raw.is_object()) return raw;
    const JArray& lists = items(raw.get("index_lists"));
    if (lists.empty()) return raw;
    for (const Json& l : lists)
        if (l.is_object() && js_truthy(l.get("for_nuclides"))) return raw;
    const Json* flagged = nullptr;
    for (const Json& l : lists)
        if (l.is_object() && js_truthy(l.get("for_contaminants"))) { flagged = &l; break; }
    if (!flagged) return raw;
    auto as_nuclides = [](const Json& l) {
        Json n = copy_with(l, {{"for_nuclides", Json(true)}});
        n.erase("for_contaminants");
        return n;
    };
    const Json* parent = nullptr;
    if (js_truthy(flagged->get("sub_set_of"))) {
        const Json& p = find_list(raw.get("index_lists"), flagged->get("sub_set_of"));
        if (!p.is_null()) parent = &p;
    }
    Json root;
    Json nxt = Json::array();
    if (parent) {
        root = parent->get("name");
        for (const Json& l : lists)
            nxt.push(l.same(*flagged) ? as_nuclides(l) : (l.same(*parent) ? copy_with(l, {{"for_contaminants", Json(true)}}) : l));
    } else {
        const Json* sub = nullptr;
        for (const Json& l : lists)
            if (l.is_object() && l.get("sub_set_of") == flagged->get("name") &&
                (l.get("name") == NUCLIDE_LIST || l.get("name") == was_called(NUCLIDE_LIST))) { sub = &l; break; }
        if (sub) {
            root = flagged->get("name");
            for (const Json& l : lists) nxt.push(l.same(*sub) ? copy_with(l, {{"for_nuclides", Json(true)}}) : l);
        } else {
            if (flagged->get("name") == MATERIAL_LIST) return raw;
            std::string root_name = free_name(names_of(lists), MATERIAL_LIST);
            root = Json(root_name);
            Json indices = Json::array();
            for (const Json& i : items(flagged->get("indices")))
                indices.push(i.is_string() ? Json::object({{"name", i}, {"enabled", Json(true)}}) : i.shallow());
            Json catalogue = Json::object({
                {"name", root},
                {"for_contaminants", Json(true)},
                {"comment", Json("Every material the model knows. The radionuclides among them are in " + js_text(flagged->get("name")) + ".")},
                {"indices", indices},
            });
            for (const Json& l : lists) {
                if (!l.same(*flagged)) {
                    nxt.push(l);
                    continue;
                }
                nxt.push(catalogue);
                nxt.push(copy_with(as_nuclides(l), {{"sub_set_of", root}}));
            }
        }
    }
    Json nuclides;
    for (const Json& l : nxt.arr())
        if (l.is_object() && js_truthy(l.get("for_nuclides"))) {
            nuclides = l.get("name");
            break;
        }
    if (!js_truthy(nuclides) || nuclides == root) return copy_with(raw, {{"index_lists", nxt}});
    Json fixed = Json::array();
    for (const Json& l : nxt.arr()) {
        if (!l.is_object() || js_truthy(l.get("for_nuclides"))) fixed.push(l);
        else if (l.has("sub_set_of") && l.get("sub_set_of") == nuclides) fixed.push(copy_with(l, {{"sub_set_of", root}}));
        else if (l.get("mapping").is_object() && l.get("mapping").has("to") && l.get("mapping").get("to") == nuclides)
            fixed.push(copy_with(l, {{"mapping", copy_with(l.get("mapping"), {{"to", root}})}}));
        else fixed.push(l);
    }
    return copy_with(raw, {{"index_lists", fixed}});
}

Json desugar_nuclides(const Json& raw) {
    const Json& nuclides = raw.get("nuclides");
    Json existing = raw.get("index_lists").is_null() ? Json::array() : raw.get("index_lists");
    if (!(nuclides.is_array() && !nuclides.empty())) return existing;
    for (const Json& l : items(existing))
        if (l.is_object() && (l.get("name") == NUCLIDE_LIST || l.get("name") == was_called(NUCLIDE_LIST) ||
                              js_truthy(l.get("for_contaminants")) || js_truthy(l.get("for_nuclides"))))
            return existing;
    std::string root = free_name(names_of(items(existing)), MATERIAL_LIST);
    Json indices = Json::array();
    Json copies = Json::array();
    for (const Json& n : nuclides.arr()) {
        indices.push(Json::object({{"name", n}, {"enabled", Json(true)}}));
        copies.push(Json::object({{"name", n}, {"enabled", Json(true)}}));
    }
    Json out = Json::array();
    out.push(Json::object({{"name", Json(root)}, {"for_contaminants", Json(true)}, {"indices", copies}}));
    out.push(Json::object({{"name", Json(NUCLIDE_LIST)}, {"for_nuclides", Json(true)}, {"sub_set_of", Json(root)}, {"indices", indices}}));
    for (const Json& l : items(existing)) out.push(l);
    return out;
}

Json derive_elements(const Json& lists) {
    const JArray& all = items(lists);
    const Json* material = nullptr;
    for (const Json& l : all)
        if (js_truthy(l.get("for_contaminants"))) { material = &l; break; }
    Json same = Json(JArray(all));
    if (!material) return same;
    for (const Json& l : all)
        if (js_truthy(l.get("for_elements")) || l.get("name") == ELEMENT_LIST || l.get("name") == was_called(ELEMENT_LIST)) return same;
    std::vector<std::string> names, dormant;
    Json pairs = Json::array();
    for (const Json& raw : items(material->get("indices"))) {
        Json nuclide = index_name(raw);
        std::optional<std::string> symbol = element_of(nuclide.is_null() ? std::string() : js_str(nuclide));
        Json el = symbol ? Json(*symbol) : nuclide;
        if (!js_truthy(el)) continue;
        std::string e = js_str(el);
        if (raw.is_object() && raw.get("enabled").is_bool() && !raw.get("enabled").as_bool()) {
            if (!contains(dormant, e)) dormant.push_back(e);
            continue;
        }
        if (!contains(names, e)) names.push_back(e);
        pairs.push(Json::object({{"from", el}, {"to", nuclide}}));
    }
    std::vector<std::string> off;
    for (const auto& e : dormant)
        if (!contains(names, e)) off.push_back(e);
    if (names.empty() && off.empty()) return same;
    Json indices = Json::array();
    for (const auto& n : names) indices.push(Json::object({{"name", Json(n)}, {"enabled", Json(true)}}));
    for (const auto& n : off) indices.push(Json::object({{"name", Json(n)}, {"enabled", Json(false)}}));
    same.push(Json::object({
        {"name", Json(ELEMENT_LIST)},
        {"for_elements", Json(true)},
        {"derived", Json(true)},
        {"comment", Json("One index per element of " + js_str(material->get("name")) + ", kept in step with it.")},
        {"mapping", Json::object({{"to", material->get("name")}, {"pairs", pairs}})},
        {"indices", indices},
    }));
    return same;
}

Json derive_block_lists(const Json& lists, const Json& model) {
    Json out = Json(JArray(items(lists)));
    struct Auto {
        const char* name;
        const char* collection;
        const char* what;
    };
    for (const Auto& a : {Auto{COMPARTMENT_LIST, "compartments", "compartment"}, Auto{TRANSFER_LIST, "transfers", "transfer"}}) {
        bool there = false;
        for (const Json& l : out.arr())
            if (l.get("name") == a.name) there = true;
        if (there) continue;
        std::vector<std::string> names;
        for (const Json& b : items(model.get(a.collection))) {
            if (!(b.is_object() && !js_truthy(b.get("hidden")))) continue;
            const Json& sys = b.get("system");
            const Json& name = b.get("name");
            if (js_truthy(sys)) {
                names.push_back(js_str(sys) + "." + js_text(name));
            } else if (name.is_string() && !name.as_string().empty()) {
                names.push_back(name.as_string());
            }
        }
        if (names.empty()) continue;
        Json indices = Json::array();
        for (const auto& n : names) indices.push(Json::object({{"name", Json(n)}, {"enabled", Json(true)}}));
        std::string what = a.what;
        out.push(Json::object({
            {"name", Json(a.name)},
            {"derived", Json(true)},
            {"auto", Json(a.collection)},
            {"note", Json("One index per " + what + " in the model \xe2\x80\x94 the " + what + "s are the indices, so there is nothing to edit here. Add a " +
                          what + " and this list gains an index; rename one and the index follows.")},
            {"indices", indices},
        }));
    }
    return out;
}

}  // namespace kompartment
