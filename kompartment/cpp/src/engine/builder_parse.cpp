// The builder: the equations parsed, the algebraic blocks put in order, what a reference
// reads, and which triggers set what off.

#include <algorithm>
#include <regex>

#include "engine/unitcheck.hpp"
#include "engine/builder.hpp"
#include "engine/builder_internal.hpp"
#include "lang/parse.hpp"
#include "model/indexlists.hpp"
#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

using namespace detail;

namespace {

std::string operation_function(const Json& op) {
    if (op == "sum") return "sum";
    if (op == "product") return "prod";
    if (op == "min") return "min";
    if (op == "max") return "max";
    if (op == "mean") return "mean";
    if (op == "percentile") return "percentile";
    throw std::out_of_range("no such operation");
}

bool self_refs(const ENode& node, const Entry& a, const std::function<bool(const std::string&)>& is_alg) {
    switch (node.kind) {
        case ENode::Kind::Ref: {
            const ERef& r = as_ref(node);
            if (r.indices.empty() && !r.by_list) {
                auto q = resolve_reference(r.name, a.system, is_alg);
                if (q && *q == a.name) return true;
            }
            return false;
        }
        case ENode::Kind::Unary: return self_refs(*as_unary(node).operand, a, is_alg);
        case ENode::Kind::Binary: return self_refs(*as_binary(node).left, a, is_alg) || self_refs(*as_binary(node).right, a, is_alg);
        case ENode::Kind::Cond:
            return self_refs(*as_cond(node).test, a, is_alg) || self_refs(*as_cond(node).then, a, is_alg) ||
                   self_refs(*as_cond(node).otherwise, a, is_alg);
        case ENode::Kind::Call:
            for (const auto& x : as_call(node).args)
                if (self_refs(*x, a, is_alg)) return true;
            return false;
        default: return false;
    }
}

}  // namespace

// --- parsing -------------------------------------------------------------------------------------------

bool Builder::known(const std::string& n) const {
    return state_by_name.count(n) || param_by_name.count(n) || alg_by_name.count(n) || table_by_name.count(n);
}

EntryPtr Builder::call_target(const std::string& name, const std::string& system) const {
    if (table_by_name.empty()) return nullptr;
    auto q = resolve_reference(name, system, [&](const std::string& n) { return known(n); });
    if (!q) return nullptr;
    auto it = table_by_name.find(*q);
    return it == table_by_name.end() ? nullptr : it->second;
}

void Builder::prepare_parsing() {
    try {
        functions = UserFunctions(project->blocks_of("functions"), [&](const std::string& n, const std::string& s) { return call_target(n, s) != nullptr; });
    } catch (const FunctionError& e) {
        throw BuildError(e.what(), e.block_name);
    }
    for (const Json& x : project->all_blocks()) unit_blocks[x.get("qname").as_string()] = x;
}

ENodePtr Builder::parse_model_equation(const std::string& text, const std::string& system, const std::string& owner) const {
    ENodePtr ast;
    try {
        ast = parse_equation(std::string_view(text), [&](const std::string& n) {
            return call_target(n, system) != nullptr || (functions.size() > 0 && functions.resolve(n, system).has_value());
        });
        scale_model_literals(ast, unit_blocks, project->simulation, system);
    } catch (const EquationParseError& e) {
        static const std::regex unknown("^Unknown function '([^']+)'");
        std::smatch m;
        std::string message = e.what();
        if (std::regex_search(message, m, unknown))
            throw BuildError(message + " in \"" + text + "\". If '" + m[1].str() + "' is meant to be one of this model\xe2\x80\x99s own, add a function of "
                             "that name under Functions and write what it works out to; Ecolego keeps some functions in a library beside the "
                             "project, and those do not travel with the file.", owner);
        throw;
    }
    if (functions.size() == 0) return ast;
    try {
        return functions.inline_functions(ast, owner, system);
    } catch (const FunctionError& e) {
        throw BuildError(e.what(), e.block_name ? e.block_name : std::optional<std::string>(owner));
    }
}

EntryPtr Builder::target_entry(const std::string& name, const std::string& system) const {
    auto q = resolve_reference(name, system, [&](const std::string& n) { return known(n); });
    if (!q) return nullptr;
    for (const auto* map : {&state_by_name, &param_by_name, &alg_by_name, &table_by_name}) {
        auto it = map->find(*q);
        if (it != map->end()) return it->second;
    }
    return nullptr;
}

Builder::IndexOperation Builder::index_operation_ast(const EntryPtr& a, const std::string& target) const {
    EntryPtr entry = target_entry(target, a->system);
    if (!entry) {
        std::string where = !a->system.empty() ? " or in '" + a->system + "'" : "";
        throw BuildError("'" + target + "' is not a block in this model" + where + ".", a->name);
    }
    const std::vector<std::string>& dims = entry->dims;
    if (dims.empty())
        throw BuildError("'" + target + "' holds a single value, so there is no index to reduce over. An index operation needs a target with one "
                         "more dimension than it has itself.", a->name);
    // The reduced list: the target's first list the block itself is not indexed by.
    std::optional<std::string> over;
    {
        std::vector<std::string> tdims;
        for (const auto& d : dims)
            if (!space->get_list(d).for_scenarios) tdims.push_back(d);
        if (!tdims.empty()) {
            if (a->dims.empty()) {
                over = tdims[0];
            } else {
                for (const auto& d : tdims)
                    if (std::find(a->dims.begin(), a->dims.end(), d) == a->dims.end()) {
                        over = d;
                        break;
                    }
            }
        }
    }
    if (!over)
        throw BuildError("'" + a->local_name.value_or("nothing") + "' is indexed by every list '" + target + "' is (" + join(dims, ", ") +
                         "), so there is nothing left to reduce over.", a->name);
    std::vector<std::string> names = space->index_names(*over);
    if (names.empty()) return {std::make_shared<ENum>(0.0), "0", over, {}};
    const Json& op = a->block.get("operation");
    std::string fn = operation_function(op);
    std::vector<ENodePtr> args;
    std::vector<std::string> shown;
    if (op == "percentile") {
        args.push_back(std::make_shared<ENum>(a->block.get("percentile").as_double()));
        shown.push_back(js_str(a->block.get("percentile")));
    }
    for (const auto& idx : names) {
        auto ref = std::make_shared<ERef>(target);
        ref->by_list = true;
        ref->named.emplace_back(*over, idx);
        args.push_back(ref);
        shown.push_back(target + "[" + idx + "]");
    }
    return {std::make_shared<ECall>(fn, std::move(args)), fn + "(" + join(shown, ", ") + ")", over, {}};
}

Builder::IndexOperation Builder::aggregate_ast(const EntryPtr& a, const std::vector<std::string>& targets) const {
    std::vector<std::string> kept, dropped;
    for (const auto& t : targets) {
        EntryPtr entry = target_entry(t, a->system);
        if (!entry) {
            std::string where = !a->system.empty() ? " or in '" + a->system + "'" : "";
            throw BuildError("'" + t + "' is not a block in this model" + where + ".", a->name);
        }
        try {
            ProjContext ctx{a->name, t};
            space->projection(a->dims, entry->dims, nullptr, &ctx);
            kept.push_back(t);
        } catch (const IndexSpaceError&) {
            dropped.push_back(t);
        }
    }
    if (!dropped.empty() && kept.empty()) {
        std::string frm = a->dims.empty() ? "a single value" : "'" + join(a->dims, ", ") + "'";
        throw BuildError("none of its targets (" + join(dropped, ", ") + ") can be reached from " + frm + ".", a->name);
    }
    if (kept.empty()) return {std::make_shared<ENum>(0.0), "0", std::nullopt, dropped};
    if (kept.size() == 1) return {std::make_shared<ERef>(kept[0]), kept[0], std::nullopt, dropped};
    std::string fn = operation_function(a->block.get("operation"));
    std::vector<ENodePtr> args;
    for (const auto& t : kept) args.push_back(std::make_shared<ERef>(t));
    return {std::make_shared<ECall>(fn, std::move(args)), fn + "(" + join(kept, ", ") + ")", std::nullopt, dropped};
}

void Builder::parse_all() {
    for (const auto& a : algebraic) {
        a->equations.clear();
        a->asts.clear();
        a->uniform = true;
        const std::string& kind = a->kind;
        if (kind == "lookup" || a->recorder || kind == "farfield" || kind == "waste_package" || kind == "waste_package:hazard" || kind == "event:lambda")
            continue;
        auto all_same = [&]() {
            for (const auto& e : a->equations)
                if (e != a->equations[0]) return false;
            return true;
        };
        if (kind == "index_reduction" || kind == "block_reduction") {
            for (int off = 0; off < a->width; off++) {
                Tup tup = entry_tuple(a->block, a->dims, off);
                IndexOperation spec;
                if (kind == "index_reduction") {
                    Json t = value_at(a->block, "target", tup);
                    spec = index_operation_ast(a, t.is_null() ? std::string() : js_str(t));
                } else {
                    spec = aggregate_ast(a, strings_of(value_at(a->block, "targets", tup)));
                }
                a->equations.push_back(spec.text);
                a->asts.push_back(spec.ast);
                if (spec.over) a->over = spec.over;
                if (!spec.dropped.empty()) a->dropped = spec.dropped;
            }
            a->uniform = all_same();
            continue;
        }
        std::unordered_map<std::string, ENodePtr> parsed;
        auto value_of = entry_lookup(a->block, *a->value_key);
        // Without per-index entries every element has the block's own value, and no
        // element's indices need to be worked out to find it.
        bool varies = false;
        if (a->block.get("entries").is_array())
            for (const Json& e : a->block.get("entries").arr())
                if (e.is_object() && e.has(*a->value_key)) varies = true;
        static const Tup nowhere;
        for (int off = 0; off < a->width; off++) {
            Json v = varies ? value_of(entry_tuple(a->block, a->dims, off)) : value_of(nowhere);
            std::string eq = v.is_null() ? std::string("0") : js_str(v);
            a->equations.push_back(eq);
            auto hit = parsed.find(eq);
            if (hit == parsed.end()) {
                ENodePtr ast;
                try {
                    ast = parse_model_equation(eq, a->system, a->name);
                } catch (const EquationParseError& e) {
                    throw BuildError(std::string(e.what()) + " in \"" + eq + "\" (at character " + std::to_string(e.position + 1) + ")", a->name);
                }
                hit = parsed.emplace(eq, ast).first;
            }
            a->asts.push_back(hit->second);
        }
        a->uniform = all_same();
    }
}

void Builder::order_algebraic() {
    auto is_alg = [&](const std::string& n) { return alg_by_name.count(n) != 0; };
    std::unordered_map<std::string, std::vector<std::string>> deps;
    for (const auto& a : algebraic) {
        // The references in the order a JavaScript Set of them iterates: first seen first.
        std::vector<std::string> order;
        std::vector<ENodePtr> distinct = distinct_asts(*a);
        for (const auto& ast : distinct) collect_in_order(order, *ast);
        std::vector<std::string> resolved;
        std::unordered_set<std::string> have;
        for (const auto& r : order) {
            auto q = resolve_reference(r, a->system, is_alg);
            if (q && *q != a->name && have.insert(*q).second) resolved.push_back(*q);
        }
        for (const auto& ast : distinct) {
            if (self_refs(*ast, *a, is_alg)) {
                std::string local = a->local_name.value_or(a->name);
                std::string hint = a->dims.empty() ? "" : " To read this block at another index, name that index -- '" + local + "[<index>]'.";
                throw BuildError("'" + local + "' refers to itself. An equation cannot read its own value: there is nothing to read until it has "
                                 "been worked out." + hint, a->name);
            }
        }
        for (const auto& n : a->needs)
            if (have.insert(n).second) resolved.push_back(n);
        deps[a->name] = resolved;
        a->reads_alg = resolved;
    }
    std::unordered_map<std::string, int> state;
    std::vector<EntryPtr> ordered;
    std::vector<std::string> stack;
    auto circular = [&](const std::string& name) -> BuildError {
        auto k = std::find(stack.begin(), stack.end(), name);
        std::vector<std::string> names(k, stack.end());
        names.push_back(name);
        std::string cycle = join(names, " -> ");
        BuildError e("Circular reference: " + cycle + ". Expressions and transfer rates may not depend on themselves, directly or indirectly.");
        // A path worked out semi-analytically whose inflow reads its own release says so.
        for (const auto& p : farf_layout) {
            if (!(p->farf->laplace && std::find(names.begin(), names.end(), p->name) != names.end())) continue;
            return BuildError("'" + p->local_name.value_or(p->name) + "' is worked out semi-analytically, and what flows into it reads its own "
                              "release at the same instant (" + cycle + "). Its release depends on what flows in, so the two cannot be worked out "
                              "one after the other: put a compartment between them, or work the path out on cells.", p->name);
        }
        return e;
    };
    // Depth first, iteratively: a model can chain tens of thousands of expressions.
    for (const auto& a0 : algebraic) {
        if (state[a0->name] == 2) continue;
        std::vector<std::pair<std::string, std::size_t>> work = {{a0->name, 0}};
        while (!work.empty()) {
            std::string name = work.back().first;
            std::size_t i = work.back().second;
            if (i == 0) {
                int s = state[name];
                if (s == 2) {
                    work.pop_back();
                    continue;
                }
                if (s == 1) throw circular(name);
                state[name] = 1;
                stack.push_back(name);
            }
            const std::vector<std::string>& ds = deps[name];
            if (i < ds.size()) {
                work.back().second = i + 1;
                const std::string& d = ds[i];
                int sd = state[d];
                if (sd == 1) throw circular(d);
                if (sd == 0) work.emplace_back(d, 0);
                continue;
            }
            work.pop_back();
            stack.pop_back();
            state[name] = 2;
            ordered.push_back(alg_by_name.at(name));
        }
    }
    algebraic = ordered;
}

void Builder::levels() {
    std::unordered_map<std::string, int> level;
    for (const auto& a : algebraic) {
        int lv = 0;
        for (const auto& d : a->reads_alg) {
            auto it = level.find(d);
            if (it != level.end()) lv = std::max(lv, it->second + 1);
        }
        level[a->name] = lv;
        a->level = lv;
    }
}

// --- resolution ----------------------------------------------------------------------------------------

Located Builder::locate(const EntryPtr& owner, const std::string& owner_name_in, const std::vector<std::string>& source_dims,
                        const Positions* pos, const Tup* fixed_tuple, const ERef& ref) {
    const std::string& name = ref.name;
    std::optional<std::string> owner_name = owner ? std::optional<std::string>(owner->name)
                                            : (owner_name_in.empty() ? std::nullopt : std::optional<std::string>(owner_name_in));
    std::string owner_system = ref.scope ? *ref.scope : (owner ? owner->system : std::string());
    auto qname = resolve_reference(name, owner_system, [&](const std::string& n) { return known(n); });
    EntryPtr target;
    RefKind kind = RefKind::Alg;
    if (qname) {
        if (auto it = state_by_name.find(*qname); it != state_by_name.end()) {
            target = it->second;
            kind = RefKind::State;
        } else if (auto it2 = param_by_name.find(*qname); it2 != param_by_name.end()) {
            target = it2->second;
            kind = RefKind::Param;
        } else if (auto it3 = alg_by_name.find(*qname); it3 != alg_by_name.end()) {
            target = it3->second;
            // A table with an argument has no slots of its own, and its name is a table's first.
            kind = table_by_name.count(*qname) ? RefKind::Table : RefKind::Alg;
        } else if (auto it4 = table_by_name.find(*qname); it4 != table_by_name.end()) {
            target = it4->second;
            kind = RefKind::Table;
        }
    }
    if (!target) {
        auto off = resolve_reference(name, owner_system, [&](const std::string& n) { return project->disabled.count(n) != 0; });
        if (off)
            throw BuildError("'" + name + "' is disabled, so it has no value for this equation to read. Enable '" + *off +
                             "', or disable this block as well.", owner_name);
        std::string tail = !owner_system.empty()
                               ? "in sub-system '" + owner_system + "' or at the top level of this model. To reach a block in another sub-system, give "
                                 "its full path, as in '" + owner_system + "." + name + "'."
                               : "in this model.";
        throw BuildError("Unknown name '" + name + "'. It is not a parameter, compartment, expression or transfer " + tail, owner_name);
    }
    const Entry::Context* context = owner ? implicit_indices(*owner) : nullptr;
    Tup fixed;
    if (ref.by_list) {
        for (const auto& [k, v] : ref.named) fixed.set(k, v);
    } else {
        fixed = pin_indices(*space, *target, ref.indices, name, owner_name, context);
    }
    for (const auto& dim : target->dims) {
        if (fixed.has(dim)) continue;
        bool reached = false;
        for (const auto& sd : source_dims)
            if (space->relate(dim, sd)) reached = true;
        if (reached) continue;
        std::optional<std::string> implied = context ? context->at(dim) : std::nullopt;
        if (!implied && context) {
            const std::string& root = *space->get_list(dim).root_name;
            std::optional<std::string> at_root = context->at(root);
            if (root != dim && at_root) {
                DerivedIndex own = derived_index(*space, dim, *at_root);
                if (own.kind == DerivedIndex::Kind::Absent) {
                    std::string what = root == TRANSFER_LIST ? "transfers" : "compartments";
                    throw BuildError("'" + name + "' has a value per index of '" + dim + "', which is made of " + what + ", and '" +
                                     owner_name.value_or("nothing") + "' is not one of them. Add it to '" + dim + "', or name one, as '" + name +
                                     "[<index>]'.", owner_name);
                }
                if (own.kind == DerivedIndex::Kind::Found) implied = own.name;
            }
        }
        if (implied) {
            fixed.set(dim, *implied);
            continue;
        }
        if (dim == COMPARTMENT_LIST) {
            std::string who = owner_name ? "'" + *owner_name + "'" : "this equation";
            std::string how = (owner && owner->kind == "transfer")
                                  ? "Write '" + name + "[" + SOURCE_INDEX + "]' for the compartment it flows out of, or '" + name + "[" + TARGET_INDEX +
                                    "]' for the one it flows into."
                                  : "Name one, as '" + name + "[<compartment>]'.";
            throw BuildError("'" + name + "' has a value per compartment, and " + who + " does not say which. " + how, owner_name);
        }
        if (dim == TRANSFER_LIST) {
            std::string who = owner_name ? "'" + *owner_name + "'" : "this equation";
            throw BuildError("'" + name + "' has a value per transfer, and " + who + " is not a transfer, so there is no transfer to take it from. "
                             "Name one, as '" + name + "[<transfer>]'.", owner_name);
        }
    }
    int base = kind == RefKind::Table ? target->tab : target->base;
    Located out{kind, target, base, nullptr};
    if (target->width == 1 && target->dims.empty()) return out;
    ProjContext ctx{owner_name, name};
    if (fixed_tuple) {
        Tup tup = fixed_tuple->merged(fixed);
        int off = 0;
        const std::vector<int>& st = space->strides(target->dims);
        for (std::size_t i = 0; i < target->dims.size(); i++) {
            const std::string& dim = target->dims[i];
            auto p = position_in(*space, dim, tup);
            if (!p) {
                try {
                    space->projection(source_dims, {dim}, &fixed, &ctx);
                } catch (const IndexSpaceError& e) {
                    throw BuildError(e.what(), owner_name);
                }
                throw BuildError("Cannot resolve index '" + dim + "' of '" + name + "'", owner_name);
            }
            off += *p * st[i];
        }
        out.index = base + off;
        return out;
    }
    std::vector<ProjTerm> terms;
    try {
        terms = space->projection(source_dims, target->dims, &fixed, &ctx);
    } catch (const IndexSpaceError& e) {
        throw BuildError(e.what(), owner_name);
    }
    int constant = base;
    std::vector<int> index;
    bool any = false;
    for (const auto& term : terms) {
        if (term.fixed >= 0) {
            constant += term.fixed * term.stride;
            continue;
        }
        const std::vector<int>& v = (*pos)[static_cast<std::size_t>(term.from)];
        if (!any) {
            index.assign(v.size(), 0);
            any = true;
        }
        if (term.table) {
            const std::vector<int>& table = *term.table;
            for (std::size_t e = 0; e < v.size(); e++) index[e] += table[static_cast<std::size_t>(v[e])] * term.stride;
        } else {
            for (std::size_t e = 0; e < v.size(); e++) index[e] += v[e] * term.stride;
        }
    }
    if (!any) {
        out.index = constant;
        return out;
    }
    for (int& x : index) x += constant;
    if (index.size() == 1) {
        out.index = index[0];
        return out;
    }
    out.indices = std::make_shared<const std::vector<int>>(std::move(index));
    return out;
}

RefResolver Builder::make_resolver(const EntryPtr& owner, const std::vector<std::string>& source_dims, const Positions* pos,
                                   const Tup* fixed_tuple) {
    return [this, owner, &source_dims, pos, fixed_tuple](const ERef& ref) -> TNodePtr {
        Located at = locate(owner, "", source_dims, pos, fixed_tuple, ref);
        if (at.kind == RefKind::Table)
            throw BuildError("'" + ref.name + "' is a lookup table with an argument, so it has no value of its own; call it, as '" + ref.name +
                             "(...)'.", owner ? std::optional<std::string>(owner->name) : std::nullopt);
        if (at.kind == RefKind::Alg && owner && at.target == owner) self_reading.insert(owner->name);
        LeafKind array = at.kind == RefKind::State ? LeafKind::Y : at.kind == RefKind::Param ? LeafKind::P : LeafKind::X;
        if (at.indices) return std::make_shared<TLeaf>(array, 0, at.indices, 0.0, nullptr);
        return make_leaf(array, at.index);
    };
}

CallResolver Builder::make_call_resolver(const EntryPtr& owner, const std::vector<std::string>& source_dims, const Positions* pos,
                                         const Tup* fixed_tuple) {
    return [this, owner, &source_dims, pos, fixed_tuple](const std::string& name, const std::vector<TNodePtr>& args) -> TNodePtr {
        if (!call_target(name, owner ? owner->system : std::string())) return nullptr;
        if (args.size() != 1)
            throw BuildError("'" + name + "' is a lookup table and takes exactly one argument; " + std::to_string(args.size()) + " were given.",
                             owner ? std::optional<std::string>(owner->name) : std::nullopt);
        Located at = locate(owner, "", source_dims, pos, fixed_tuple, ERef(name));
        TLeafPtr leaf = at.indices ? std::make_shared<TLeaf>(LeafKind::TAB, 0, at.indices, 0.0, nullptr) : make_leaf(LeafKind::TAB, at.index);
        return std::make_shared<TTab>(leaf, args[0]);
    };
}

// --- events --------------------------------------------------------------------------------------------

void Builder::events() {
    for (const auto& rec : recorders) {
        if (rec->kind != "trigger") continue;
        rec->event_base = static_cast<int>(event_slots.size());
        for (int off = 0; off < rec->width; off++) {
            Tup tup = entry_tuple(rec->block, rec->dims, off);
            Json written = value_at(rec->block, "direction", tup);
            if (!js_truthy(written)) written = rec->block.get("direction");
            int direction = written.is_string() ? direction_sign(written.as_string()) : 0;
            event_slots.push_back({rec->entry->base + off, direction, rec->name,
                                   rec->dims.empty() ? std::nullopt : std::optional<Tup>(tuple_by_list(*space, rec->dims, off))});
        }
    }
    for (const auto& e : event_slots) event_direction.push_back(static_cast<signed char>(e.direction));
    for (const auto& rec : recorders) {
        if (rec->mem < 0) continue;
        for (const auto& field : event_fields(rec->kind)) {
            for (int off = 0; off < rec->width; off++) {
                Tup tup = entry_tuple(rec->block, rec->dims, off);
                Json written = value_at(rec->block, field, tup);
                std::string text = written.is_null() ? std::string() : std::string(js_trim(js_str(written)));
                if (text.empty()) continue;
                ENodePtr ast;
                try {
                    ast = parse_equation(std::string_view(text));
                } catch (const EquationParseError&) {
                    throw BuildError("'" + text + "' is not the name of a discrete event.", rec->name);
                }
                std::string spaced = field;
                std::replace(spaced.begin(), spaced.end(), '_', ' ');
                if (ast->kind != ENode::Kind::Ref)
                    throw BuildError("'" + spaced + "' must name a discrete event, not an expression; '" + text + "' is one.", rec->name);
                const ERef& ref = as_ref(*ast);
                Located at = locate(rec->entry, "", rec->dims, nullptr, &tup, ref);
                const EntryPtr& owner = at.target->recorder;
                if (!owner || owner->kind != "trigger") {
                    std::string what = field == "trigger" ? "take a snapshot" : spaced;
                    throw BuildError("'" + ref.name + "' is not a discrete event, so it cannot " + what + ".", rec->name);
                }
                int which = owner->event_base + (at.index - at.target->base);
                event_handlers[which].push_back({rec, off, event_action(field)});
            }
        }
    }
    // ...and set off an event: which of the slots above each event set off by a trigger
    // watches. Its trigger is a name, read from where the event is; an indexed trigger named
    // whole sets it off when any of its indices fires, one index named, `T[Cs-137]`, when
    // that one does.
    for (const auto& D : disruption_layout) {
        if (D->timing != "trigger") continue;
        std::string local = js_str(D->block.get("name"));
        const Json& written = D->block.get("trigger");
        std::string text = written.is_null() ? std::string() : std::string(js_trim(js_str(written)));
        if (text.empty()) throw BuildError("'" + local + "' is set off by a trigger, and names none.", D->q);
        ENodePtr ast;
        try {
            ast = parse_equation(std::string_view(text));
        } catch (const EquationParseError&) {
            throw BuildError("'" + text + "' is not the name of a trigger.", D->q);
        }
        if (ast->kind != ENode::Kind::Ref)
            throw BuildError("What sets '" + local + "' off must name a trigger, not an expression; '" + text + "' is one.", D->q);
        const ERef& ref = as_ref(*ast);
        // A block that is there and is not a trigger is said to be one first; a name that
        // is nobody's, or is switched off, the locator says.
        const Json& sys = D->block.get("system");
        auto qname = resolve_reference(ref.name, sys.is_null() ? std::string() : js_str(sys), [&](const std::string& n) { return known(n); });
        EntryPtr whole = qname && alg_by_name.count(*qname) ? alg_by_name.at(*qname) : nullptr;
        EntryPtr owner = whole ? whole->recorder : nullptr;
        if (qname && (!owner || owner->kind != "trigger"))
            throw BuildError("'" + ref.name + "' is not a trigger, so it cannot set off '" + local + "'.", D->q);
        std::vector<int> slots;
        if (owner && !owner->dims.empty() && ref.indices.empty()) {
            for (int k = 0; k < owner->width; k++) slots.push_back(owner->event_base + k);
        } else {
            static const std::vector<std::string> no_dims;
            Tup nowhere;
            Located at = locate(D->entry, "", no_dims, nullptr, &nowhere, ref);
            owner = at.target->recorder;
            if (!owner || owner->kind != "trigger")
                throw BuildError("'" + ref.name + "' is not a trigger, so it cannot set off '" + local + "'.", D->q);
            slots.push_back(owner->event_base + (at.index - at.target->base));
        }
        D->fired_by = slots;
    }
}

}  // namespace kompartment
