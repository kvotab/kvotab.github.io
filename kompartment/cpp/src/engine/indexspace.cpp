#include "engine/indexspace.hpp"

#include <algorithm>

#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

std::vector<int> identity_table(int n) {
    std::vector<int> t(static_cast<std::size_t>(n));
    for (int i = 0; i < n; i++) t[static_cast<std::size_t>(i)] = i;
    return t;
}

std::vector<int> compose(const std::vector<int>& inner, const std::vector<int>& outer) {
    std::vector<int> out(inner.size(), -1);
    for (std::size_t k = 0; k < inner.size(); k++)
        if (inner[k] >= 0) out[k] = outer[static_cast<std::size_t>(inner[k])];
    return out;
}

std::vector<int> by_name(const IndexList& a, const IndexList& b) {
    std::vector<int> table(static_cast<std::size_t>(a.size), -1);
    for (std::size_t k = 0; k < a.enabled.size(); k++) {
        auto it = b.position_of.find(a.enabled[k].name);
        table[k] = it == b.position_of.end() ? -1 : it->second;
    }
    return table;
}

const JArray& pairs_of(const IndexList& lst) {
    static const JArray none;
    const Json& p = lst.mapping.get("pairs");
    return p.is_array() ? p.arr() : none;
}

std::optional<int> position_of(const IndexList& lst, const Json& name) {
    if (!name.is_string()) return std::nullopt;
    return lst.position(name.as_string());
}

std::vector<int> mapped_up(const IndexList& lst, const IndexList& parent) {
    std::vector<int> table(static_cast<std::size_t>(lst.size), -1);
    for (const Json& pair : pairs_of(lst)) {
        auto k = position_of(lst, pair.get("from"));
        auto pos = position_of(parent, pair.get("to"));
        if (!k || !pos || table[static_cast<std::size_t>(*k)] >= 0) continue;
        table[static_cast<std::size_t>(*k)] = *pos;
    }
    return table;
}

std::vector<int> mapped_down(const IndexList& lst, const IndexList& parent) {
    std::vector<int> table(static_cast<std::size_t>(parent.size), -1);
    for (const Json& pair : pairs_of(lst)) {
        auto k = position_of(parent, pair.get("to"));
        auto pos = position_of(lst, pair.get("from"));
        if (!k || !pos) continue;
        table[static_cast<std::size_t>(*k)] = *pos;
    }
    return table;
}

void index_enabled(IndexList& lst) {
    lst.size = static_cast<int>(lst.enabled.size());
    lst.position_of.clear();
    for (std::size_t k = 0; k < lst.enabled.size(); k++) lst.position_of[lst.enabled[k].name] = static_cast<int>(k);
}

}  // namespace

IndexSpace::IndexSpace(const Json& raw_lists) {
    for (const Json& raw : raw_lists.arr()) {
        if (!(raw.is_object() && js_truthy(raw.get("name")))) throw IndexSpaceError("An index list needs a name");
        std::string name = js_str(raw.get("name"));
        if (lists_.count(name)) throw IndexSpaceError("Duplicate index list '" + name + "'");
        IndexList lst;
        lst.name = name;
        if (raw.get("indices").is_array())
            for (const Json& i : raw.get("indices").arr()) {
                if (i.is_string()) {
                    lst.indices.push_back({i.as_string(), true});
                } else {
                    const Json& n = i.get("name");
                    const Json& e = i.get("enabled");
                    lst.indices.push_back({n.is_null() ? std::string() : js_str(n), !(e.is_bool() && !e.as_bool())});
                }
            }
        lst.for_contaminants = js_truthy(raw.get("for_contaminants"));
        lst.for_nuclides = js_truthy(raw.get("for_nuclides"));
        lst.for_scenarios = js_truthy(raw.get("for_scenarios"));
        if (js_truthy(raw.get("sub_set_of"))) lst.sub_set_of = js_str(raw.get("sub_set_of"));
        if (js_truthy(raw.get("mapping"))) lst.mapping = raw.get("mapping").shallow();
        lists_.emplace(name, std::move(lst));
        order_.push_back(name);
    }
    resolve();
}

void IndexSpace::resolve() {
    for (auto& [name, lst] : lists_) {
        lst.enabled.clear();
        for (const auto& i : lst.indices)
            if (i.enabled) lst.enabled.push_back(i);
        index_enabled(lst);
        lst.names.clear();
        for (const auto& i : lst.indices) lst.names.insert(i.name);
    }
    for (const auto& name : order_) {
        IndexList& lst = lists_.at(name);
        if (lst.sub_set_of) {
            auto it = lists_.find(*lst.sub_set_of);
            if (it == lists_.end())
                throw IndexSpaceError("Index list '" + lst.name + "' is a sub-set of '" + *lst.sub_set_of + "', which does not exist", lst.name);
            const IndexList& root = it->second;
            if (root.sub_set_of)
                throw IndexSpaceError("'" + lst.name + "' is a sub-set of '" + root.name +
                                      "', which is itself a sub-set. Sub-sets must be taken from a root list.", lst.name);
            for (const auto& idx : lst.enabled)
                if (!root.names.count(idx.name))
                    throw IndexSpaceError("'" + idx.name + "' is in the sub-set '" + lst.name + "' but not in its root list '" + root.name + "'", lst.name);
            bool dormant = false;
            for (const auto& i : lst.enabled)
                if (!root.position_of.count(i.name)) dormant = true;
            if (dormant) {
                std::vector<ListIndex> kept;
                for (const auto& i : lst.enabled)
                    if (root.position_of.count(i.name)) kept.push_back(i);
                lst.enabled = std::move(kept);
                index_enabled(lst);
            }
        }
        if (!lst.mapping.is_null()) {
            const Json& to = lst.mapping.get("to");
            if (!(to.is_string() && lists_.count(to.as_string())))
                throw IndexSpaceError("Index list '" + lst.name + "' maps to '" + (to.is_null() ? std::string("nothing") : js_str(to)) +
                                      "', which does not exist", lst.name);
        }
    }
    for (const auto& name : order_) {
        std::unordered_set<std::string> seen;
        place(lists_.at(name), seen);
    }
    place_scenarios();
}

IndexList& IndexSpace::place(IndexList& lst, std::unordered_set<std::string>& seen) {
    if (lst.root_name) return lst;
    if (seen.count(lst.name)) throw IndexSpaceError("Index list '" + lst.name + "' is defined in terms of itself", lst.name);
    seen.insert(lst.name);
    std::optional<std::string> parent_name = lst.sub_set_of;
    if (!parent_name && !lst.mapping.is_null() && js_truthy(lst.mapping.get("to"))) parent_name = js_str(lst.mapping.get("to"));
    if (!parent_name || parent_name->empty()) {
        lst.root_name = lst.name;
        lst.up = identity_table(lst.size);
        lst.down = identity_table(lst.size);
        return lst;
    }
    auto it = lists_.find(*parent_name);
    if (it == lists_.end()) throw IndexSpaceError("No index list named '" + *parent_name + "'");
    IndexList& parent = place(it->second, seen);
    std::vector<int> step_up = lst.sub_set_of ? by_name(lst, parent) : mapped_up(lst, parent);
    std::vector<int> step_down = lst.sub_set_of ? by_name(parent, lst) : mapped_down(lst, parent);
    lst.root_name = parent.root_name;
    lst.up = compose(step_up, parent.up);
    lst.down = compose(parent.down, step_down);
    return lst;
}

void IndexSpace::place_scenarios() {
    scenario_root_.reset();
    for (const auto& name : order_) {
        const IndexList& lst = lists_.at(name);
        if (lst.for_scenarios && lst.root_name == lst.name) {
            scenario_root_ = lst.name;
            break;
        }
    }
    if (!scenario_root_) {
        for (const auto& name : order_) {
            const IndexList& lst = lists_.at(name);
            if (lst.for_scenarios) {
                scenario_root_ = lst.root_name;
                break;
            }
        }
    }
    for (auto& [name, lst] : lists_) lst.is_scenario = scenario_root_ && lst.root_name == scenario_root_;
    std::vector<std::string> found = scenarios();
    scenario_ = found.empty() ? std::nullopt : std::optional<std::string>(found[0]);
}

std::vector<std::string> IndexSpace::scenarios() const {
    return scenario_root_ ? index_names(*scenario_root_) : std::vector<std::string>{};
}

bool IndexSpace::is_scenario_dim(std::string_view name) const {
    const IndexList* lst = find_list(name);
    return lst && lst->is_scenario;
}

std::optional<std::string> IndexSpace::set_scenario(const std::optional<std::string>& name) {
    std::vector<std::string> available = scenarios();
    scenario_ = (name && std::find(available.begin(), available.end(), *name) != available.end()) ? name : std::nullopt;
    return scenario_;
}

std::optional<std::string> IndexSpace::scenario_index_in(std::string_view dim) const {
    const IndexList* lst = find_list(dim);
    if (!lst || !lst->is_scenario || !scenario_) return std::nullopt;
    const IndexList& root = lists_.at(*scenario_root_);
    auto root_pos = root.position(*scenario_);
    if (!root_pos) return std::nullopt;
    int pos = lst == &root ? *root_pos : lst->down[static_cast<std::size_t>(*root_pos)];
    return pos >= 0 ? std::optional<std::string>(lst->enabled[static_cast<std::size_t>(pos)].name) : std::nullopt;
}

std::vector<std::string> IndexSpace::without_scenarios(const std::vector<std::string>& dims) const {
    if (!scenario_root_) return dims;
    std::vector<std::string> out;
    for (const auto& d : dims)
        if (!is_scenario_dim(d)) out.push_back(d);
    return out;
}

Tup IndexSpace::pin_scenario(const std::vector<std::string>& dims, const Tup& tuple) const {
    if (!scenario_root_ || !scenario_) return tuple;
    Tup out = tuple;
    for (const auto& d : dims) {
        if (!is_scenario_dim(d)) continue;
        auto name = scenario_index_in(d);
        if (!name) continue;
        out.set(d, *name);
    }
    return out;
}

const IndexList* IndexSpace::find_list(std::string_view name) const {
    auto it = lists_.find(std::string(name));
    return it == lists_.end() ? nullptr : &it->second;
}

const IndexList& IndexSpace::get_list(std::string_view name) const {
    const IndexList* lst = find_list(name);
    if (!lst) throw IndexSpaceError("No index list named '" + std::string(name) + "'");
    return *lst;
}

std::vector<std::string> IndexSpace::index_names(std::string_view name) const {
    const IndexList& lst = get_list(name);
    std::vector<std::string> out;
    out.reserve(lst.enabled.size());
    for (const auto& i : lst.enabled) out.push_back(i.name);
    return out;
}

const IndexList* IndexSpace::material_list() const {
    for (const auto& name : order_)
        if (lists_.at(name).for_contaminants) return &lists_.at(name);
    return nullptr;
}

const IndexList* IndexSpace::nuclide_list() const {
    for (const auto& name : order_)
        if (lists_.at(name).for_nuclides) return &lists_.at(name);
    return nullptr;
}

const std::vector<int>& IndexSpace::strides(const std::vector<std::string>& dims) const {
    auto hit = stride_cache_.find(dims);
    if (hit != stride_cache_.end()) return hit->second;
    std::vector<int> st(dims.size(), 1);
    for (std::size_t i = dims.size(); i-- > 1;) st[i - 1] = st[i] * list_size(dims[i]);
    for (const auto& d : dims) get_list(d);   // an unknown list is refused even when its size is not read
    return stride_cache_.emplace(dims, std::move(st)).first->second;
}

int IndexSpace::width(const std::vector<std::string>& dims) const {
    int n = 1;
    for (const auto& d : dims) n *= list_size(d);
    return n;
}

int IndexSpace::offset_of(const std::vector<std::string>& dims, const std::vector<std::string>& tuple) const {
    const std::vector<int>& st = strides(dims);
    int off = 0;
    for (std::size_t i = 0; i < dims.size(); i++) {
        auto pos = get_list(dims[i]).position(tuple[i]);
        if (!pos) throw IndexSpaceError("'" + tuple[i] + "' is not an enabled index of '" + dims[i] + "'");
        off += *pos * st[i];
    }
    return off;
}

std::vector<std::string> IndexSpace::tuple_at(const std::vector<std::string>& dims, int offset) const {
    const std::vector<int>& st = strides(dims);
    std::vector<std::string> out;
    int rest = offset;
    for (std::size_t i = 0; i < dims.size(); i++) {
        int k = rest / st[i];
        rest -= k * st[i];
        out.push_back(get_list(dims[i]).enabled[static_cast<std::size_t>(k)].name);
    }
    return out;
}

std::vector<std::vector<int>> IndexSpace::positions(const std::vector<std::string>& dims) const {
    std::vector<std::vector<int>> out;
    if (dims.empty()) return out;
    int w = width(dims);
    out.assign(dims.size(), std::vector<int>(static_cast<std::size_t>(w)));
    if (w == 0) return out;
    const std::vector<int>& st = strides(dims);
    for (int off = 0; off < w; off++) {
        int rest = off;
        for (std::size_t i = 0; i < dims.size(); i++) {
            int k = rest / st[i];
            rest -= k * st[i];
            out[i][static_cast<std::size_t>(off)] = k;
        }
    }
    return out;
}

std::optional<Relation> IndexSpace::relate(const std::string& from_list, const std::string& to_list) const {
    if (from_list == to_list) return Relation{Relation::Kind::Same, nullptr, false};
    auto key = std::make_pair(from_list, to_list);
    auto found = relate_cache_.find(key);
    if (found != relate_cache_.end()) return found->second;
    std::optional<Relation> rel = relate_uncached(from_list, to_list);
    relate_cache_.emplace(key, rel);
    return rel;
}

std::optional<Relation> IndexSpace::relate_uncached(const std::string& from_list, const std::string& to_list) const {
    const IndexList& a = get_list(from_list);
    const IndexList& b = get_list(to_list);
    if (a.root_name != b.root_name) return std::nullopt;
    auto table = std::make_shared<std::vector<int>>(static_cast<std::size_t>(b.size), -1);
    bool partial = false;
    for (int k = 0; k < b.size; k++) {
        int r = b.up[static_cast<std::size_t>(k)];
        if (r >= 0) (*table)[static_cast<std::size_t>(k)] = a.down[static_cast<std::size_t>(r)];
        if ((*table)[static_cast<std::size_t>(k)] < 0) partial = true;
    }
    return Relation{Relation::Kind::Map, table, partial};
}

std::vector<std::string> IndexSpace::missing_from(const std::string& dim, const std::string& frm) const {
    auto rel = relate(dim, frm);
    if (!rel || rel->kind == Relation::Kind::Same) return {};
    std::vector<std::string> names = index_names(frm);
    std::vector<std::string> out;
    for (std::size_t k = 0; k < rel->table->size(); k++)
        if ((*rel->table)[k] < 0 && k < names.size()) out.push_back(names[k]);
    if (out.empty()) out.push_back("missing indices");
    return out;
}

std::vector<ProjTerm> IndexSpace::projection(const std::vector<std::string>& source_dims, const std::vector<std::string>& target_dims,
                                             const Tup* fixed_indices, const ProjContext* context) const {
    const std::vector<int> st = strides(target_dims);
    std::vector<ProjTerm> terms;
    for (std::size_t i = 0; i < target_dims.size(); i++) {
        const std::string& dim = target_dims[i];
        int stride = st[i];
        if (const std::string* fixed = fixed_indices ? fixed_indices->find(dim) : nullptr) {
            auto pos = get_list(dim).position(*fixed);
            if (!pos) throw IndexSpaceError("'" + *fixed + "' is not an enabled index of '" + dim + "'");
            terms.push_back({stride, dim, *pos, -1, nullptr, false});
            continue;
        }
        std::optional<ProjTerm> best;
        for (std::size_t s = 0; s < source_dims.size(); s++) {
            auto rel = relate(dim, source_dims[s]);
            if (!rel) continue;
            if (rel->kind == Relation::Kind::Same) {
                best = ProjTerm{stride, dim, -1, static_cast<int>(s), nullptr, false};
                break;
            }
            ProjTerm here{stride, dim, -1, static_cast<int>(s), rel->table, rel->partial};
            if (!best || (best->partial && !here.partial)) best = here;
        }
        if (!best || best->partial) {
            std::string what = context && context->target ? "'" + *context->target + "'" : "that block";
            std::string where = context && context->owner ? "'" + *context->owner + "'" : "this block";
            std::vector<std::string> names = index_names(dim);
            std::string first_name = names.empty() ? "index" : names[0];
            std::string block = context && context->target ? *context->target : "block";
            if (best) {
                const std::string& frm = source_dims[static_cast<std::size_t>(best->from)];
                throw IndexSpaceError(what + " is indexed by '" + dim + "', which does not cover every index of '" + frm +
                                      "' -- so for some of them " + where + " has no value to read. Give '" + dim + "' the missing " +
                                      join(missing_from(dim, frm), ", ") + ", or write an explicit index, as in " + block + "[" +
                                      first_name + "].", dim);
            }
            throw IndexSpaceError(what + " is indexed by '" + dim + "', which " + where +
                                  " is not indexed by and cannot reach. Give an explicit index, as in " + block + "[" + first_name +
                                  "], or add '" + dim + "' to " + where + ".", dim);
        }
        terms.push_back(*best);
    }
    return terms;
}

std::vector<std::string> normalise_dims(const Json& dims) {
    std::unordered_set<std::string> seen;
    std::vector<std::string> out;
    if (!dims.is_array()) return out;
    for (const Json& d : dims.arr()) {
        std::string ds = js_str(d);
        if (!seen.insert(ds).second) throw IndexSpaceError("Index list '" + ds + "' is used twice on the same block");
        out.push_back(ds);
    }
    return out;
}

}  // namespace kompartment
