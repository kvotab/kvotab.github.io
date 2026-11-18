// The builder: what its messages say, the helpers over the index space, statements
// merged, and the layout of states, parameters, tables and algebraic slots.

#include <algorithm>
#include <cmath>
#include <regex>

#include "engine/transport.hpp"
#include "engine/builder.hpp"
#include "engine/builder_internal.hpp"
#include "engine/farfield.hpp"
#include "model/indexlists.hpp"
#include "model/names.hpp"
#include "model/simulation.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

const std::vector<std::string>& budget_terms() {
    static const std::vector<std::string> v = {"in", "out", "decay", "ingrowth", "explicit", "between"};
    return v;
}

namespace {

std::optional<std::string> slot_words(const std::string& key) {
    static const std::unordered_map<std::string, std::string> words = {
        {"inventory", "inventory"}, {"irf", "instant release fraction"}, {"degradation_rate", "matrix degradation rate"},
        {"fail_at", "fail at"}, {"fail_from", "failures from"}, {"fail_to", "failures until"},
        {"fail_start", "failures start"}, {"fail_rate", "failure rate"}, {"fail_scale", "weibull scale"},
        {"fail_shape", "weibull shape"},
        {"at", "at setting"}, {"rate", "rate setting"}, {"from", "from setting"}, {"until", "until setting"},
        {"dydt", "dy/dt term"}, {"limit", "availability limit"}, {"top", "availability numerator"},
        {"bottom", "availability denominator"}, {"hazard", "failure hazard"}, {"lambda", "rate"}, {"share", "share"}};
    auto it = words.find(key);
    return it == words.end() ? std::nullopt : std::optional<std::string>(it->second);
}

}  // namespace

std::string in_words(const std::string& message) {
    static const std::regex add_to("add '([^']+)' to '([^'#]+)#[^']*'");
    static const std::regex setting("'([^'#\\s]+)#([A-Za-z_]+\\d*)'");
    std::string text = std::regex_replace(message, add_to, "add '$1' to the lists $2 is indexed by");
    std::string out;
    auto begin = std::sregex_iterator(text.begin(), text.end(), setting);
    std::size_t last = 0;
    for (auto it = begin; it != std::sregex_iterator(); ++it) {
        const std::smatch& m = *it;
        out.append(text, last, static_cast<std::size_t>(m.position()) - last);
        std::string block = m[1], key = m[2];
        std::optional<std::string> words = slot_words(key);
        if (!words) {
            std::string bare = key;
            while (!bare.empty() && bare.back() >= '0' && bare.back() <= '9') bare.pop_back();
            words = slot_words(bare);
        }
        out += block + "\xe2\x80\x99s " + (words ? *words : "setting " + key);
        last = static_cast<std::size_t>(m.position() + m.length());
    }
    out.append(text, last, std::string::npos);
    return out;
}

namespace {
struct ErrorParts {
    std::string full;
    std::optional<std::string> owner, setting;
};
ErrorParts error_parts(const std::string& message, const std::optional<std::string>& block) {
    ErrorParts p;
    std::size_t cut = block ? block->find('#') : std::string::npos;
    bool split = block && cut != std::string::npos && cut > 0;
    p.owner = split ? std::optional<std::string>(block->substr(0, cut)) : block;
    std::string said = in_words(message);
    p.full = (p.owner && !p.owner->empty()) ? *p.owner + ": " + said : said;
    if (split) p.setting = block->substr(cut + 1);
    return p;
}
}  // namespace

BuildError::BuildError(const std::string& message, const std::optional<std::string>& block)
    : std::runtime_error(error_parts(message, block).full),
      block_name(error_parts(message, block).owner),
      setting(error_parts(message, block).setting) {}

// --- helpers over the index space ----------------------------------------------------------------------

Tup tuple_by_list(const IndexSpace& space, const std::vector<std::string>& dims, int offset) {
    std::vector<std::string> names = space.tuple_at(dims, offset);
    Tup out;
    for (std::size_t i = 0; i < dims.size(); i++) out.set(dims[i], names[i]);
    return out;
}

std::optional<int> position_in(const IndexSpace& space, const std::string& dim, const Tup& tup) {
    if (const std::string* name = tup.find(dim)) {
        auto pos = space.get_list(dim).position(*name);
        if (pos) return pos;
    }
    for (const auto& [list_name, index_name] : tup) {
        if (list_name == dim) continue;
        std::optional<Relation> rel = space.has_list(list_name) ? space.relate(dim, list_name) : std::nullopt;
        if (!rel) continue;
        if (rel->kind == Relation::Kind::Same) {
            auto pos = space.get_list(dim).position(index_name);
            if (pos) return pos;
        } else {
            auto k = space.get_list(list_name).position(index_name);
            if (!k) continue;
            int pos = (*rel->table)[static_cast<std::size_t>(*k)];
            if (pos >= 0) return pos;
        }
    }
    return std::nullopt;
}

std::string describe_tuple(const Tup& tup) {
    std::string s;
    for (const auto& [k, v] : tup) {
        if (!s.empty()) s += ", ";
        s += k + "=" + v;
    }
    return s.empty() ? "scalar" : s;
}

namespace detail {

DerivedIndex derived_index(const IndexSpace& space, const std::string& dim, const std::string& index_name) {
    const IndexList& lst = space.get_list(dim);
    if (lst.root_name == dim) return {DerivedIndex::Kind::None, ""};
    const IndexList& root = space.get_list(*lst.root_name);
    auto k = root.position(index_name);
    if (!k) return {DerivedIndex::Kind::None, ""};
    auto rel = space.relate(dim, *lst.root_name);
    int pos = (rel && rel->kind == Relation::Kind::Map) ? (*rel->table)[static_cast<std::size_t>(*k)] : *k;
    if (pos < 0) return {DerivedIndex::Kind::Absent, ""};
    if (pos < static_cast<int>(lst.enabled.size())) return {DerivedIndex::Kind::Found, lst.enabled[static_cast<std::size_t>(pos)].name};
    return {DerivedIndex::Kind::Absent, ""};
}

Tup pin_indices(const IndexSpace& space, const Entry& target, const std::vector<std::optional<std::string>>& indices,
                const std::string& name, const std::optional<std::string>& owner_name, const Entry::Context* context) {
    Tup fixed;
    std::vector<std::string> given;
    for (const auto& w : indices) {
        if (!w || w->empty()) continue;
        const std::string& i = *w;
        if (i != SOURCE_INDEX && i != TARGET_INDEX) {
            given.push_back(i);
            continue;
        }
        std::optional<std::string> end = context ? context->at(i) : std::nullopt;
        if (end && !end->empty()) {
            given.push_back(*end);
            continue;
        }
        std::string which = i == SOURCE_INDEX ? "flows out of" : "flows into";
        if (context && context->at(TRANSFER_LIST)) {
            std::string goes = i == SOURCE_INDEX ? "comes from" : "goes";
            throw BuildError("'" + name + "[" + i + "]' asks for the compartment this transfer " + which + ", and it has none: it " + goes +
                             " outside the model.", owner_name);
        }
        throw BuildError("'" + i + "' means the compartment a transfer " + which + ", so it can only be written in a transfer's own equation.",
                         owner_name);
    }
    if (given.empty()) return fixed;
    auto as_written = [&]() {
        std::string s = name;
        for (const auto& i : indices) s += "[" + (i ? *i : std::string()) + "]";
        return s;
    };
    const std::vector<std::string>& dims = target.dims;
    if (given.size() > dims.size()) {
        std::string noun = given.size() == 1 ? "index" : "indices";
        std::string what = dims.empty() ? "nothing, so it holds a single value"
                                        : "only " + std::to_string(dims.size()) + " list" + (dims.size() == 1 ? "" : "s") + " (" + join(dims, ", ") + ")";
        throw BuildError("'" + as_written() + "' pins " + std::to_string(given.size()) + " " + noun + ", but '" + name + "' is indexed by " + what + ".",
                         owner_name);
    }
    auto accepted = [&](const std::string& dim, const std::string& index_name) -> std::optional<std::string> {
        if (space.get_list(dim).position_of.count(index_name)) return index_name;
        DerivedIndex d = derived_index(space, dim, index_name);
        return d.kind == DerivedIndex::Kind::Found ? std::optional<std::string>(d.name) : std::nullopt;
    };
    std::set<std::size_t> claimed;
    for (const auto& dim : dims) {
        std::optional<std::size_t> pick;
        for (std::size_t k = 0; k < given.size() && !pick; k++)
            if (!claimed.count(k) && accepted(dim, given[k])) pick = k;
        for (std::size_t k = 0; k < given.size() && !pick; k++)
            if (accepted(dim, given[k])) pick = k;
        if (!pick) continue;
        fixed.set(dim, *accepted(dim, given[*pick]));
        claimed.insert(*pick);
    }
    for (std::size_t k = 0; k < given.size(); k++) {
        if (claimed.count(k)) continue;
        const std::string& g = given[k];
        for (const auto& d : dims)
            for (const auto& i : space.get_list(d).indices)
                if (i.name == g && !i.enabled)
                    throw BuildError("'" + g + "' is disabled in '" + d + "', so '" + as_written() + "' has no value. Re-enable it, or change this equation.",
                                     owner_name);
        std::vector<std::string> owns;
        for (const auto& d : dims)
            if (accepted(d, g)) owns.push_back(d);
        if (!owns.empty())
            throw BuildError("'" + as_written() + "' pins '" + join(owns, "' and '") + "' twice: '" + g + "' belongs to " + (owns.size() == 1 ? "it" : "them") +
                             ", and so does another index in the same reference.", owner_name);
        throw BuildError("'" + g + "' is not an index of any list that '" + name + "' is indexed by (" + (dims.empty() ? "none" : join(dims, ", ")) + ")",
                         owner_name);
    }
    return fixed;
}

const Entry::Context* implicit_indices(Entry& owner) {
    if (owner.context_made) return owner.context ? &*owner.context : nullptr;
    owner.context_made = true;
    const Json& block = owner.block;
    const Json& alias = block.get("alias");
    auto text = [](const Json& v) -> std::optional<std::string> { return v.is_null() ? std::nullopt : std::optional<std::string>(js_str(v)); };
    const std::string& kind = owner.kind;
    if (kind == "transfer" || starts_with(kind, "availability:")) {
        Entry::Context c;
        std::optional<std::string> tname = text(alias.get("transfer"));
        if (!tname) tname = owner.transfer;
        if (!tname) tname = owner.name;
        c.items.emplace_back(TRANSFER_LIST, tname);
        c.items.emplace_back(SOURCE_INDEX, !alias.get("from").is_null() ? text(alias.get("from")) : text(block.get("from")));
        c.items.emplace_back(TARGET_INDEX, !alias.get("to").is_null() ? text(alias.get("to")) : text(block.get("to")));
        owner.context = std::move(c);
    } else if (kind == "compartment" || kind == "compartment:dydt") {
        Entry::Context c;
        std::optional<std::string> cname = text(alias.get("compartment"));
        if (!cname) cname = owner.state_name;
        if (!cname) cname = owner.name;
        c.items.emplace_back(COMPARTMENT_LIST, cname);
        owner.context = std::move(c);
    }
    return owner.context ? &*owner.context : nullptr;
}

std::vector<std::string> flat_dimensions(const IndexSpace& space, const Entry& entry) {
    const std::vector<std::string>& dims = entry.dims;
    std::vector<std::string> out;
    if (dims.size() < 2) return out;
    const std::vector<std::string>& equations = entry.equations;
    if (static_cast<int>(equations.size()) != entry.width) return out;
    const std::vector<int>& st = space.strides(dims);
    for (std::size_t i = 0; i < dims.size(); i++) {
        int size = space.list_size(dims[i]);
        bool flat = true;
        for (int off = 0; off < entry.width; off++) {
            int pos = (off / st[i]) % size;
            if (pos != 0 && equations[static_cast<std::size_t>(off)] != equations[static_cast<std::size_t>(off - pos * st[i])]) {
                flat = false;
                break;
            }
        }
        if (flat) out.push_back(dims[i]);
    }
    return out;
}

std::vector<ENodePtr> distinct_asts(const Entry& a) {
    if (a.asts.size() <= 1) return a.asts;
    if (a.uniform) return {a.asts[0]};
    std::unordered_set<std::string> seen;
    std::vector<ENodePtr> out;
    for (std::size_t k = 0; k < a.asts.size(); k++)
        if (seen.insert(a.equations[k]).second) out.push_back(a.asts[k]);
    return out;
}

std::vector<int> iota(int from, int count) {
    std::vector<int> v(static_cast<std::size_t>(count > 0 ? count : 0));
    for (int i = 0; i < count; i++) v[static_cast<std::size_t>(i)] = from + i;
    return v;
}

std::shared_ptr<Stmt> make_stmt(const EntryPtr& a, std::vector<int> outs, TNodePtr tree, int width, int sub, bool multiply) {
    auto s = std::make_shared<Stmt>();
    if (outs.size() == 1 && width <= 1) {
        s->out = outs[0];
    } else {
        s->outs = std::make_shared<const std::vector<int>>(std::move(outs));
    }
    s->tree = std::move(tree);
    s->width = width;
    s->block = a;
    s->level = {a ? a->level : 0, sub};
    s->multiply = multiply;
    return s;
}

std::shared_ptr<Stmt> make_stmt(const EntryPtr& a, int out, TNodePtr tree, int width, int sub, bool multiply) {
    auto s = std::make_shared<Stmt>();
    s->out = out;
    s->tree = std::move(tree);
    s->width = width;
    s->block = a;
    s->level = {a ? a->level : 0, sub};
    s->multiply = multiply;
    return s;
}

double builder_number(const Json& v) {
    if (v.is_null()) return 0.0;
    if (v.is_bool()) return v.as_bool() ? 1.0 : 0.0;
    if (v.is_number()) return v.as_double();
    std::string s(js_trim(js_str(v)));
    if (s.empty()) return 0.0;
    double f = py_float_nan(Json(s));
    if (std::isnan(f)) {
        std::string low = lowercase(s);
        if (low == "nan" || low == "+nan" || low == "-nan") return f;
        if (low == "infinity" || low == "+infinity") return std::numeric_limits<double>::infinity();
        if (low == "-infinity") return -std::numeric_limits<double>::infinity();
        return std::numeric_limits<double>::quiet_NaN();
    }
    return f;
}

}  // namespace detail

using namespace detail;

DecayTables decay_tables(const DecayModel& model, int size) {
    int n = std::max(1, size);
    DecayTables t;
    t.ioff.assign(static_cast<std::size_t>(n), 0);
    t.icnt.assign(static_cast<std::size_t>(n), 0);
    for (int k = 0; k < n; k++) {
        t.ioff[static_cast<std::size_t>(k)] = static_cast<int>(t.ipar.size());
        if (static_cast<std::size_t>(k) < model.parents.size()) {
            for (const auto& p : model.parents[static_cast<std::size_t>(k)]) {
                t.ipar.push_back(p.index);
                t.icoef.push_back(p.lambda * p.ratio);
            }
            t.icnt[static_cast<std::size_t>(k)] = static_cast<int>(model.parents[static_cast<std::size_t>(k)].size());
        }
    }
    t.lam = model.lambdas.empty() ? std::vector<double>(static_cast<std::size_t>(n), 0.0) : model.lambdas;
    return t;
}

// --- statements ----------------------------------------------------------------------------------------

std::vector<std::shared_ptr<Stmt>> split_stmt(const std::shared_ptr<Stmt>& s) {
    if (s->width <= 1 || !s->tree) return {s};
    std::vector<TLeafPtr> ls = tree_leaves(s->tree);
    std::vector<int> outs = s->out_indices();
    std::vector<std::shared_ptr<Stmt>> out;
    for (int i = 0; i < s->width; i++) {
        std::vector<TLeafPtr> fresh;
        fresh.reserve(ls.size());
        for (const auto& l : ls) {
            if (l->leaf == LeafKind::K) fresh.push_back(k_leaf(l->value_at(static_cast<std::size_t>(i))));
            else if (l->leaf == LeafKind::T || l->leaf == LeafKind::T0 || l->leaf == LeafKind::T1) fresh.push_back(l);
            else fresh.push_back(make_leaf(l->leaf, l->index_at(static_cast<std::size_t>(i))));
        }
        auto one = std::make_shared<Stmt>();
        one->out = outs[static_cast<std::size_t>(i)];
        one->tree = rebuild(s->tree, fresh);
        one->width = 1;
        one->block = s->block;
        one->level = s->level;
        one->mergeable = false;
        one->array = s->array;
        one->multiply = s->multiply;
        out.push_back(one);
    }
    return out;
}

std::vector<std::shared_ptr<Stmt>> merge_statements(const std::vector<std::shared_ptr<Stmt>>& stmts) {
    std::map<std::pair<int, int>, std::vector<std::shared_ptr<Stmt>>> by_level;
    for (const auto& s : stmts) by_level[s->level].push_back(s);
    std::vector<std::shared_ptr<Stmt>> out;
    for (const auto& [level, at_level] : by_level) {
        // A statement on its own, or a group of the same shape, each where its first stood.
        struct Item {
            std::shared_ptr<Stmt> one;
            std::vector<std::shared_ptr<Stmt>> group;
        };
        std::vector<Item> order;
        std::unordered_map<std::string, std::size_t> group_of;
        for (const auto& s : at_level) {
            if (!s->mergeable || !s->tree) {
                order.push_back({s, {}});
                continue;
            }
            std::string key = std::string(1, static_cast<char>('0' + static_cast<int>(s->array))) + (s->multiply ? "*" : "=") + signature(*s->tree);
            auto g = group_of.find(key);
            if (g == group_of.end()) {
                g = group_of.emplace(key, order.size()).first;
                order.push_back({nullptr, {}});
            }
            order[g->second].group.push_back(s);
        }
        for (const Item& item : order) {
            if (item.one) {
                out.push_back(item.one);
                continue;
            }
            if (item.group.size() == 1) {
                out.push_back(item.group[0]);
                continue;
            }
            std::vector<std::pair<std::vector<TLeafPtr>, int>> leaf_groups;
            std::vector<int> outs;
            for (const auto& s : item.group) {
                leaf_groups.emplace_back(tree_leaves(s->tree), s->width);
                if (s->outs) outs.insert(outs.end(), s->outs->begin(), s->outs->end());
                else outs.insert(outs.end(), static_cast<std::size_t>(s->width), s->out);
            }
            const auto& first = item.group[0];
            auto merged = std::make_shared<Stmt>();
            merged->width = static_cast<int>(outs.size());
            merged->outs = std::make_shared<const std::vector<int>>(std::move(outs));
            merged->tree = rebuild(first->tree, merge_leaves(leaf_groups));
            merged->block = first->block;
            merged->level = level;
            merged->array = first->array;
            merged->multiply = first->multiply;
            out.push_back(merged);
        }
    }
    return out;
}

// --- the builder ---------------------------------------------------------------------------------------

std::vector<std::string> Builder::dims_of(const Json& block) const { return space->without_scenarios(strings_of(block.get("index_lists"))); }

bool Builder::is_nuclide_dim(const std::string& d) const {
    if (!material_list) return false;
    const IndexList& l = space->get_list(d);
    return l.mapping.is_null() && l.root_name == material_root;
}

Tup Builder::entry_tuple(const Json& block, const std::vector<std::string>& dims, int off) const {
    return space->pin_scenario(strings_of(block.get("index_lists")), tuple_by_list(*space, dims, off));
}

Builder::Builder(std::shared_ptr<const Project> project_) : project(std::move(project_)) {
    if (!project->transports.empty()) project = expand_transports(*project);
    space = &project->index_space;
    material_list = project->material_list_name;
    decay = project->decay_model();
    if (material_list) material_root = space->get_list(*material_list).root_name;
    layout_states();
    layout_parameters();
    layout_tables();
    layout_algebraic();
    prepare_parsing();
    parse_all();
    order_algebraic();
    levels();
    events();
    generate_algebraic();
    classes();
    assembly();
    jumps();
    for (const auto& l : decay_lists) DEC.push_back(DEC_tables.at(l));
    derivative_reads();
    initial_state();
}

// --- layout --------------------------------------------------------------------------------------------

namespace {
EntryPtr new_entry(const std::string& name, const Json& block, const std::string& kind) {
    auto e = std::make_shared<Entry>();
    e->name = name;
    e->block = block;
    e->kind = kind;
    return e;
}
std::optional<std::string> local_of(const Json& block) {
    const Json& n = block.get("name");
    return n.is_null() ? std::nullopt : std::optional<std::string>(js_str(n));
}
std::string system_text(const Json& block) {
    const Json& s = block.get("system");
    return s.is_null() ? std::string() : js_str(s);
}
}  // namespace

void Builder::layout_states() {
    int n = 0;
    auto state = [&](const Json& c, const std::string& kind, const std::vector<std::string>& dims, int w, bool hidden) {
        EntryPtr e = new_entry(c.get("qname").as_string(), c, kind);
        e->local_name = local_of(c);
        e->system = system_text(c);
        e->base = n;
        e->width = w;
        e->dims = dims;
        e->hidden = hidden;
        return e;
    };
    for (const Json& c : project->blocks_of("compartments")) {
        std::vector<std::string> dims = dims_of(c);
        int w = space->width(dims);
        states.push_back(state(c, "compartment", dims, w, js_truthy(c.get("hidden"))));
        n += w;
    }
    for (const Json& m : project->blocks_of("running_means")) {
        std::vector<std::string> dims = dims_of(m);
        int w = space->width(dims);
        EntryPtr e = state(m, "running_mean", dims, w, true);
        states.push_back(e);
        mean_states.push_back(e);
        n += w;
    }
    for (const Json& f : project->blocks_of("farfields")) {
        const std::string& q = f.get("qname").as_string();
        std::optional<std::string> problem = structure_problem(f);
        if (!problem) problem = geometry_problem(f);
        if (!problem) problem = rock_problem(f);
        if (problem) throw BuildError(*problem, q);
        bool laplace = is_semi_analytic(f);
        if (!uses_cells(f) && !laplace)
            throw BuildError("'" + js_text(f.get("method")) + "' is not a way this tool can work a path out (" + join(farf_methods(), ", ") + ")", q);
        std::vector<std::string> dims = dims_of(f);
        std::vector<std::string> nuc_dims;
        for (const auto& d : dims)
            if (is_nuclide_dim(d)) nuc_dims.push_back(d);
        if (nuc_dims.size() > 1)
            throw BuildError("A far-field path runs one decay chain, and it is indexed by two radionuclide dimensions (" + join(nuc_dims, " and ") + ").", q);
        auto farf = std::make_shared<FarfLayout>();
        for (std::size_t i = 0; i < dims.size() && farf->m_idx < 0; i++)
            if (is_nuclide_dim(dims[i])) farf->m_idx = static_cast<int>(i);
        int m_idx = farf->m_idx;
        if (m_idx >= 0) farf->list_name = dims[static_cast<std::size_t>(m_idx)];
        int nnuc = farf->list_name ? space->list_size(*farf->list_name) : 1;
        std::vector<int> other_idx;
        for (int i = 0; i < static_cast<int>(dims.size()); i++)
            if (i != m_idx) {
                other_idx.push_back(i);
                farf->other_dims.push_back(dims[static_cast<std::size_t>(i)]);
            }
        int other_width = space->width(farf->other_dims);
        int ncells = cell_count(f);
        const std::vector<int> st = space->strides(dims);
        const std::vector<int> other_st = space->strides(farf->other_dims);
        farf->dim_off.assign(static_cast<std::size_t>(other_width * nnuc), 0);
        for (int o = 0; o < other_width; o++) {
            int at = 0;
            for (std::size_t k = 0; k < farf->other_dims.size(); k++) {
                int pos = (o / other_st[k]) % space->list_size(farf->other_dims[k]);
                at += pos * st[static_cast<std::size_t>(other_idx[k])];
            }
            for (int m = 0; m < nnuc; m++)
                farf->dim_off[static_cast<std::size_t>(o * nnuc + m)] = at + (m_idx >= 0 ? m * st[static_cast<std::size_t>(m_idx)] : 0);
        }
        if (!laplace) farf->structure = effective_structure(f);
        farf->laplace = laplace;
        farf->nnuc = nnuc;
        farf->other_width = other_width;
        farf->ncells = ncells;
        farf->single_off = iota(0, other_width);
        EntryPtr e = state(f, "farfield", dims, other_width * ncells * nnuc, true);
        e->farf = farf;
        states.push_back(e);
        farf_layout.push_back(e);
        n += e->width;
    }
    for (const Json& w : project->blocks_of("waste_packages")) {
        const std::string& q = w.get("qname").as_string();
        std::vector<std::string> dims = dims_of(w);
        int wd = space->width(dims);
        auto half = [&](const char* role, int base) {
            EntryPtr e = new_entry(q + " " + role, w, "waste_package");
            e->local_name = local_of(w);
            e->system = system_text(w);
            e->width = wd;
            e->dims = dims;
            e->hidden = true;
            e->base = base;
            e->qname = q;
            e->unit = project->decay_unit;
            e->role = role;
            return e;
        };
        EntryPtr intact = half("intact", n), exposed = half("exposed", n + wd);
        states.push_back(intact);
        states.push_back(exposed);
        EntryPtr W = new_entry(q, w, "waste_layout");
        W->dims = dims;
        W->width = wd;
        W->q = q;
        W->intact = intact;
        W->exposed = exposed;
        const Json& failure = w.get("failure");
        W->failure = (failure.is_string() && (failure == "never" || !failure_keys(failure.as_string()).empty())) ? failure.as_string() : "never";
        waste_layout.push_back(W);
        n += 2 * wd;
    }
    for (const auto& W : waste_layout) waste_by_name[W->q] = W;
    for (const Json& d : project->blocks_of("events")) {
        const std::string& q = d.get("qname").as_string();
        EntryPtr e = new_entry(q, d, "event");
        e->local_name = local_of(d);
        e->system = system_text(d);
        e->base = n;
        e->width = 1;
        e->qname = q;
        states.push_back(e);
        EntryPtr D = new_entry(q, d, "disruption");
        D->q = q;
        D->entry = e;
        const Json& timing = d.get("timing");
        D->timing = (timing == "at" || timing == "poisson" || timing == "trigger") ? timing.as_string() : "at";
        D->actions = normalise_actions(d.get("actions"));
        D->number = static_cast<int>(disruption_layout.size());
        disruption_layout.push_back(D);
        n += 1;
    }
    if (project->simulation.get("mass_balance") == Json(true)) {
        const IndexList* mat = material_list ? &space->get_list(*material_list) : nullptr;
        auto bud = std::make_shared<Budget>();
        if (mat)
            for (const auto& i : mat->enabled) bud->families.push_back(i.name);
        bud->families.push_back(UNINDEXED);
        int nfam = static_cast<int>(bud->families.size());
        for (const auto& s : states) {
            if (s->kind != "compartment" && s->kind != "waste_package") continue;
            std::vector<int> fam_of(static_cast<std::size_t>(s->width), nfam - 1);
            std::optional<std::size_t> m;
            for (std::size_t i = 0; i < s->dims.size() && !m; i++)
                if (is_nuclide_dim(s->dims[i])) m = i;
            if (m && mat)
                for (int off = 0; off < s->width; off++) {
                    std::string nm = space->tuple_at(s->dims, off)[*m];
                    auto pos = mat->position(nm);
                    fam_of[static_cast<std::size_t>(off)] = pos ? *pos : nfam - 1;
                }
            bud->members.push_back({s->name, s->base, s->width, std::move(fam_of)});
        }
        bud->base = n;
        bud->nfam = nfam;
        bud->terms = budget_terms();
        budget = bud;
        EntryPtr e = new_entry("#mass-balance", Json(), "budget");
        e->local_name = "#mass-balance";
        e->base = n;
        e->width = static_cast<int>(budget_terms().size()) * nfam;
        e->hidden = true;
        e->budget = bud;
        states.push_back(e);
        n += e->width;
    }
    nstate = n;
    for (const auto& s : states)
        if (s->kind == "compartment") state_by_name[s->name] = s;
    for (const auto& f : farf_layout) path_by_name[f->name] = f;
}

void Builder::layout_parameters() {
    int n = 0;
    for (const Json& p : project->blocks_of("parameters")) {
        std::vector<std::string> dims = dims_of(p);
        int w = space->width(dims);
        EntryPtr e = new_entry(p.get("qname").as_string(), p, "parameter");
        e->local_name = local_of(p);
        e->system = system_text(p);
        e->base = n;
        e->width = w;
        e->dims = dims;
        param_layout.push_back(e);
        n += w;
    }
    for (const auto& p : param_layout) param_by_name[p->name] = p;
    for (const Json& lk : project->blocks_of("lookups")) {
        std::vector<std::string> dims = dims_of(lk);
        int w = space->width(dims);
        auto points_at = entry_lookup(lk, "points");
        for (int off = 0; off < w; off++) {
            Tup tup = entry_tuple(lk, dims, off);
            Json points = points_at(tup);
            if (!points.is_array()) continue;
            for (std::size_t i = 0; i < points.size(); i++) {
                const Json& pt = points[i];
                Json spec = (pt.is_array() && pt.size() > 2) ? pt[2] : Json();
                if (!js_truthy(spec)) continue;
                EntryPtr e = new_entry(lk.get("qname").as_string(), lk, "point");
                e->dims = dims;
                e->index = tup;
                e->off = off;
                e->point = static_cast<int>(i);
                e->at = pt[0].as_double();
                e->value = pt[1].as_double();
                e->spec = spec;
                e->slot = n;
                point_layout.push_back(e);
                n += 1;
            }
        }
    }
    for (const auto& pt : point_layout) points_by_entry[{pt->name, pt->off}].push_back(pt);
    nparam = n;
    P.assign(static_cast<std::size_t>(std::max(1, n)), 0.0);
    for (const auto& pt : point_layout) P[static_cast<std::size_t>(pt->slot)] = pt->value;
    for (const auto& e : param_layout) {
        auto value_of = entry_lookup(e->block, "value");
        for (int off = 0; off < e->width; off++) {
            Tup tup = entry_tuple(e->block, e->dims, off);
            Json v = value_of(tup);
            double num = builder_number(v);
            if (!std::isfinite(num)) throw BuildError("Value '" + js_text(v) + "' is not a number", e->name);
            P[static_cast<std::size_t>(e->base + off)] = num;
        }
    }
}

void Builder::layout_tables() {
    for (const Json& lk : project->blocks_of("lookups")) {
        const std::string& q = lk.get("qname").as_string();
        std::vector<std::string> dims = dims_of(lk);
        int w = space->width(dims);
        // The elements that share one list of points share its table.
        std::vector<std::pair<Json, int>> cache;
        int base = static_cast<int>(TAB.size());
        auto points_at = entry_lookup(lk, "points");
        for (int off = 0; off < w; off++) {
            Tup tup = entry_tuple(lk, dims, off);
            Json points = points_at(tup);
            if (points.is_null()) points = Json::array();
            auto mine = points_by_entry.find({q, off});
            bool has_points = mine != points_by_entry.end();
            int cached = -1;
            if (!has_points)
                for (const auto& [seen, at] : cache)
                    if (seen.same(points)) cached = at;
            if (cached >= 0) {
                TAB.push_back(TAB[static_cast<std::size_t>(cached)]);
            } else {
                try {
                    const Json& rule = lk.get("interpolation");
                    TAB.push_back(std::make_shared<LookupTable>(points.empty() ? Json::array({Json::array({Json(0), Json(0)})}) : points,
                                                                rule.is_null() ? std::string("linear") : js_str(rule),
                                                                js_truthy(lk.get("cyclic"))));
                } catch (const LookupError& e) {
                    std::string at = dims.empty() ? "" : " at " + describe_tuple(tup);
                    throw BuildError(std::string(e.what()) + at, q);
                }
                if (!has_points) cache.emplace_back(points, static_cast<int>(TAB.size()) - 1);
            }
            if (has_points) {
                std::vector<int> order = iota(0, static_cast<int>(points.size()));
                std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
                    double x = builder_number(points[static_cast<std::size_t>(a)][0]), y = builder_number(points[static_cast<std::size_t>(b)][0]);
                    return x < y;
                });
                std::unordered_map<int, int> rank;
                for (std::size_t to = 0; to < order.size(); to++) rank[order[to]] = static_cast<int>(to);
                for (const auto& pt : mine->second) {
                    pt->tab = static_cast<int>(TAB.size()) - 1;
                    auto r = rank.find(pt->point);
                    pt->row = r == rank.end() ? pt->point : r->second;
                }
            }
        }
        EntryPtr e = new_entry(q, lk, "lookup_table");
        e->local_name = local_of(lk);
        e->system = system_text(lk);
        e->width = w;
        e->dims = dims;
        e->tab = base;
        const Json& arg = lk.get("argument");
        if (js_truthy(arg)) e->argument = js_str(arg);
        lookup_layout.push_back(e);
    }
    for (const auto& lk : lookup_layout)
        if (lk->argument) table_by_name[lk->name] = lk;
}

EntryPtr Builder::add_algebraic(const std::string& name, const std::string& kind, const Json& block,
                                const std::optional<std::string>& value_key, const std::vector<std::string>* over) {
    EntryPtr e = new_entry(name, block, kind);
    e->dims = over ? *over : dims_of(block);
    e->width = space->width(e->dims);
    e->local_name = local_of(block);
    e->system = system_text(block);
    e->value_key = value_key;
    e->base = nalg;
    e->hidden = js_truthy(block.get("hidden"));
    algebraic.push_back(e);
    nalg += e->width;
    return e;
}

void Builder::layout_algebraic() {
    static const std::vector<std::string> none;
    for (const Json& e : project->blocks_of("expressions")) add_algebraic(e.get("qname").as_string(), "expression", e, "equation");
    for (const Json& t : project->blocks_of("transfers")) {
        EntryPtr slot = add_algebraic(t.get("qname").as_string(), "transfer", t, "rate");
        const Json& scheme = t.get("availability");
        const Json& which = scheme.get("scheme");
        if (!(scheme.is_object() && (which == "limit" || which == "shared_limit" || which == "langmuir" || which == "shared_langmuir"))) continue;
        slot->availability = std::make_shared<Availability>();
        slot->availability->scheme = scheme;
        std::vector<std::string> keys = (which == "limit" || which == "shared_limit") ? std::vector<std::string>{"limit"}
                                                                                      : std::vector<std::string>{"top", "bottom"};
        for (const auto& key : keys) {
            Json holder = t.shallow();
            holder.set("entries", Json::array());
            holder.set(key, scheme.get(key));
            EntryPtr op = add_algebraic(slot->name + "#" + key, "availability:" + key, holder, key, &slot->dims);
            op->hidden = true;
            op->transfer = slot->name;
            slot->availability->operands.emplace_back(key, op);
        }
        slot->needs.clear();
        for (const auto& [key, op] : slot->availability->operands) slot->needs.push_back(op->name);
    }
    for (const Json& s : project->blocks_of("inflows")) add_algebraic(s.get("qname").as_string(), "inflow", s, "rate");
    for (const Json& c : project->blocks_of("compartments")) {
        if (!has_dydt(c)) continue;
        EntryPtr slot = add_algebraic(c.get("qname").as_string() + "#dydt", "compartment:dydt", c, "dydt");
        slot->hidden = true;
        slot->state_name = c.get("qname").as_string();
        dydt_slots.push_back(slot);
    }
    for (const auto& lk : lookup_layout) {
        if (lk->argument) continue;
        add_algebraic(lk->name, "lookup", lk->block, "points")->tab = lk->tab;
    }
    for (const Json& o : project->blocks_of("index_reductions")) add_algebraic(o.get("qname").as_string(), "index_reduction", o, "target");
    for (const Json& g : project->blocks_of("block_reductions")) add_algebraic(g.get("qname").as_string(), "block_reduction", g, "targets");
    for (const auto& W : waste_layout) {
        std::vector<std::string> failing = failure_keys(W->failure);
        for (const auto& key : waste_equation_keys()) {
            if (starts_with(key, "fail_") && std::find(failing.begin(), failing.end(), key) == failing.end()) continue;
            const auto& per_nuclide = waste_nuclide_keys();
            bool single = std::find(per_nuclide.begin(), per_nuclide.end(), key) == per_nuclide.end();
            EntryPtr slot = add_algebraic(W->q + "#" + key, "waste_package:" + key, W->block, key, single ? &none : nullptr);
            slot->hidden = true;
            if (single) slot->single = true;
            W->setting.emplace_back(key, slot);
        }
        EntryPtr hazard = add_algebraic(W->q + "#hazard", "waste_package:hazard", W->block, std::nullopt, &none);
        hazard->hidden = true;
        for (const auto& k : failing) hazard->needs.push_back((*W->setting_at(k))->name);
        hazard->waste = W;
        W->hazard_slot = hazard;
        EntryPtr release = add_algebraic(W->q, "waste_package", W->block, std::nullopt);
        release->needs = {hazard->name, (*W->setting_at("irf"))->name, (*W->setting_at("degradation_rate"))->name};
        release->waste = W;
        W->release_slot = release;
    }
    for (const auto& D : disruption_layout) {
        for (const auto& key : timing_keys(D->timing)) {
            const Json& v = D->block.get(key);
            if (v.is_null() || js_trim(js_str(v)).empty()) continue;
            EntryPtr slot = add_algebraic(D->q + "#" + key, "event:" + key, D->block, key, &none);
            slot->hidden = true;
            slot->single = true;
            D->setting.emplace_back(key, slot);
        }
        for (std::size_t k = 0; k < D->actions.size(); k++) {
            const Json& a = D->actions[k];
            Json holder = Json::object({{"name", D->block.get("name")}, {"system", D->block.get("system")}, {"index_lists", Json::array()},
                                        {"entries", Json::array()}, {"fraction", a.get("fraction")}});
            EntryPtr slot = add_algebraic(D->q + "#share" + std::to_string(k), "event:share", holder, "fraction", &none);
            slot->hidden = true;
            slot->single = true;
            D->shares.push_back(slot);
        }
        EntryPtr lam_slot = add_algebraic(D->q + "#lambda", "event:lambda", D->block, std::nullopt, &none);
        lam_slot->hidden = true;
        for (const auto& [key, s] : D->setting) lam_slot->needs.push_back(s->name);
        lam_slot->event = D;
        D->lambda_slot = lam_slot;
        for (std::size_t k = 0; k < D->actions.size(); k++) {
            const Json& a = D->actions[k];
            if (!(a.get("kind") == "fail")) continue;
            auto W = a.get("block").is_string() ? waste_by_name.find(a.get("block").as_string()) : waste_by_name.end();
            if (W == waste_by_name.end())
                throw BuildError("'" + js_text(a.get("block")) + "' is not a set of waste packages, so it has no packages to fail.", D->q);
            W->second->hazard_slot->needs.push_back(lam_slot->name);
            W->second->hazard_slot->needs.push_back(D->shares[k]->name);
            W->second->disrupted.push_back({D, D->shares[k]});
        }
    }
    for (const auto& p : farf_layout) {
        std::unordered_map<std::string, int> setting_base;
        std::vector<std::string> keys = active_equation_keys(p->block);
        for (const auto& key : keys) {
            const auto& per = farf_nuclide_keys();
            bool per_nuclide = std::find(per.begin(), per.end(), key) != per.end();
            EntryPtr slot = add_algebraic(p->name + "#" + key, "farfield:" + key, p->block, key, per_nuclide ? nullptr : &p->farf->other_dims);
            slot->hidden = true;
            setting_base[key] = slot->base;
            if (!per_nuclide) slot->single = true;
        }
        EntryPtr rel = add_algebraic(p->name, "farfield", p->block, std::nullopt);
        for (const auto& key : keys) rel->needs.push_back(p->name + "#" + key);
        rel->path = p;
        rel->farf_index = static_cast<int>(FARF.size());
        p->alg_release = rel;
        p->farf_index = static_cast<int>(FARF.size());
        FARF.push_back(make_farfield_path(*this, p, rel, setting_base, keys));
    }
    std::unordered_map<std::string, EntryPtr> mean_state_by_name;
    for (const auto& m : mean_states) mean_state_by_name[m->name] = m;
    for (const auto& kind : recorder_kinds()) {
        for (const Json& blk : project->blocks_of(recorder_collection(kind))) {
            const std::string& name = blk.get("qname").as_string();
            std::vector<std::pair<std::string, EntryPtr>> aux;
            for (const auto& key : equation_fields(kind)) {
                EntryPtr slot = add_algebraic(name + "#" + key, kind + ":" + key, blk, key);
                slot->hidden = true;
                aux.emplace_back(key, slot);
            }
            EntryPtr entry = add_algebraic(name, kind, blk, std::nullopt);
            entry->aux = aux;
            for (const auto& [key, a] : aux) entry->needs.push_back(a->name);
            EntryPtr rec = new_entry(name, blk, kind);
            rec->dims = entry->dims;
            rec->width = entry->width;
            rec->entry = entry;
            rec->aux = aux;
            rec->mem = is_remembering_kind(kind) ? static_cast<int>(MEM.size()) : -1;
            auto st = mean_state_by_name.find(name);
            if (st != mean_state_by_name.end()) rec->state = st->second;
            if (rec->mem >= 0) {
                for (int off = 0; off < entry->width; off++) {
                    Tup tup = entry_tuple(blk, entry->dims, off);
                    Json start = value_at(blk, "start_trigger", tup);
                    const Json& op = blk.get("operation");
                    bool waits = !start.is_null() && !js_trim(js_str(start)).empty();
                    MEM.emplace_back(kind, js_truthy(op) ? js_str(op) : std::string("max"), !waits);
                }
            }
            recorders.push_back(rec);
            entry->recorder = rec;
        }
    }
    for (const auto& a : algebraic) alg_by_name[a->name] = a;
}

}  // namespace kompartment
