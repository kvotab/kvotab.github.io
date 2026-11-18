// The builder: a statement for every algebraic block, which slots move with what, and
// which of the moving blocks the derivative reads.

#include <algorithm>
#include <cmath>

#include "engine/builder.hpp"
#include "engine/builder_internal.hpp"
#include "engine/farfield.hpp"
#include "lang/functions.hpp"
#include "model/names.hpp"
#include "model/simulation.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

using namespace detail;

namespace {

TNodePtr K(double v) { return k_leaf(v); }
TNodePtr xleaf(int i) { return make_leaf(LeafKind::X, i); }
TNodePtr bin(BinOp op, TNodePtr a, TNodePtr b) { return std::make_shared<TBin>(op, std::move(a), std::move(b)); }
TNodePtr cond(TNodePtr t, TNodePtr a, TNodePtr b) { return std::make_shared<TCond>(std::move(t), std::move(a), std::move(b)); }
TNodePtr call(const char* key, std::vector<TNodePtr> args) { return std::make_shared<TCall>(key, std::move(args)); }
std::vector<int> plus(int base, const std::vector<int>& idx) {
    std::vector<int> out(idx.size());
    for (std::size_t i = 0; i < idx.size(); i++) out[i] = base + idx[i];
    return out;
}

std::shared_ptr<Stmt> special_stmt(const EntryPtr& a, Special sp, bool state, bool clock) {
    auto s = std::make_shared<Stmt>();
    s->block = a;
    s->level = {a->level, 0};
    s->mergeable = false;
    s->special = std::make_shared<const Special>(std::move(sp));
    s->array = state ? Stmt::Array::State : (clock ? Stmt::Array::Clock : Stmt::Array::X);
    return s;
}

TNodePtr hazard_tree(const std::string& failure, const TNodePtr& t, const TNodePtr& frm, const TNodePtr& to, const TNodePtr& start,
                     const TNodePtr& rate, const TNodePtr& scale, const TNodePtr& shape) {
    if (failure == "uniform") {
        TNodePtr width = call("max", {bin(BinOp::Sub, to, t), bin(BinOp::Mul, K(WINDOW_TAIL), call("abs", {bin(BinOp::Sub, to, frm)}))});
        return cond(bin(BinOp::Lt, t, frm), K(0.0), bin(BinOp::Div, K(1.0), width));
    }
    if (failure == "exponential") return cond(bin(BinOp::Lt, t, start), K(0.0), rate);
    if (failure == "weibull") {
        TNodePtr age = call("max", {bin(BinOp::Sub, t, start), bin(BinOp::Mul, K(1e-12), call("abs", {scale}))});
        TNodePtr powr = call("power", {bin(BinOp::Div, age, scale), bin(BinOp::Sub, shape, K(1.0))});
        return cond(bin(BinOp::Lt, t, start), K(0.0), bin(BinOp::Mul, bin(BinOp::Div, shape, scale), powr));
    }
    return K(0.0);
}

double moles_per_unit(const std::string& decay_unit, double lam_per_time_unit, double seconds_per_time_unit) {
    if (decay_unit == "mol") return 1.0;
    double per_second = lam_per_time_unit / seconds_per_time_unit;
    if (!(per_second > 0)) return 0.0;
    return 1 / (per_second * AVOGADRO_AVAILABILITY);
}

// One term of an availability's amount: the states read, their factor, and the group they
// count in (a group per element, and the one this term is of), if any.
struct AvailabilityTerm {
    std::vector<int> off;
    double factor;
    bool grouped;
    std::vector<int> group_at;
    int group;
};

TNodePtr availability_sum(const std::vector<AvailabilityTerm>& terms) {
    if (terms.empty()) return K(0.0);
    std::vector<TNodePtr> parts;
    for (const auto& term : terms) {
        TNodePtr read = make_leaf(LeafKind::Y, term.off);
        if (term.factor != 1) read = bin(BinOp::Mul, K(term.factor), read);
        if (term.grouped) {
            std::vector<double> at(term.group_at.begin(), term.group_at.end());
            read = cond(bin(BinOp::Eq, k_leaf(std::move(at)), K(static_cast<double>(term.group))), read, K(0.0));
        }
        parts.push_back(read);
    }
    TNodePtr out = parts[0];
    for (std::size_t i = 1; i < parts.size(); i++) out = bin(BinOp::Add, out, parts[i]);
    return out;
}

TNodePtr availability_expression(const Json& scheme, const TNodePtr& amount, const std::vector<std::pair<std::string, TNodePtr>>& ops) {
    auto op = [&](const char* key) -> const TNodePtr& {
        for (const auto& [k, v] : ops)
            if (k == key) return v;
        throw std::logic_error("no such operand");
    };
    TNodePtr body;
    if (scheme.get("scheme") == "limit" || scheme.get("scheme") == "shared_limit") {
        body = cond(bin(BinOp::Gt, amount, K(0.0)), call("min", {bin(BinOp::Div, op("limit"), amount), K(1.0)}), K(1.0));
    } else {
        const TNodePtr& a = op("top");
        const TNodePtr& bb = op("bottom");
        body = cond(bin(BinOp::Ne, bin(BinOp::Add, amount, bb), K(0.0)), bin(BinOp::Div, bin(BinOp::Add, amount, a), bin(BinOp::Add, amount, bb)), K(1.0));
    }
    if (js_truthy(scheme.get("unavailable"))) return bin(BinOp::Sub, K(1.0), body);
    return body;
}

}  // namespace

// --- statements for the algebraic blocks ---------------------------------------------------------------

void Builder::generate_algebraic() {
    for (const auto& a : algebraic) {
        std::vector<std::shared_ptr<Stmt>> stmts = statements_for(a);
        if (self_reading.count(a->name)) {
            std::vector<std::shared_ptr<Stmt>> split;
            for (const auto& s : stmts) {
                if (s->tree && s->width > 1) {
                    for (auto& one : split_stmt(s)) split.push_back(one);
                } else {
                    split.push_back(s);
                }
            }
            for (const auto& s : split) s->mergeable = false;
            stmts = std::move(split);
        }
        alg_stmts[a->name] = std::move(stmts);
    }
}

TNodePtr Builder::resolve_stmt_tree(const EntryPtr& a, const ENode& ast, const std::vector<std::string>& dims, const Positions* pos,
                                    const Tup* tup) {
    try {
        return resolve_tree(ast, make_resolver(a, dims, pos, tup), make_call_resolver(a, dims, pos, tup));
    } catch (const BuildError&) {
        throw;
    } catch (const IndexSpaceError&) {
        throw;
    } catch (const NotSupported&) {
        throw;
    } catch (const std::invalid_argument& e) {
        throw BuildError(e.what(), a->name);
    } catch (const std::runtime_error& e) {
        throw BuildError(e.what(), a->name);
    }
}

std::vector<std::shared_ptr<Stmt>> Builder::statements_for(const EntryPtr& a) {
    std::vector<std::shared_ptr<Stmt>> out;
    static const std::vector<std::string> no_dims;
    TNodePtr t = make_leaf(LeafKind::T);
    const std::string& kind = a->kind;
    if (kind == "lookup") {
        if (a->width == 1 && a->dims.empty()) {
            out.push_back(make_stmt(a, a->base, std::make_shared<TTab>(make_leaf(LeafKind::TAB, a->tab), t), 1));
        } else if (a->width > 0) {
            std::vector<int> idx = iota(0, a->width);
            out.push_back(make_stmt(a, plus(a->base, idx), std::make_shared<TTab>(make_leaf(LeafKind::TAB, plus(a->tab, idx)), t), a->width));
        }
        return out;
    }
    if (kind == "farfield") {
        Special sp{Special::Kind::FarfieldRelease, a->farf_index, a->path->farf->laplace, {}, {}, {}, {}};
        out.push_back(special_stmt(a, std::move(sp), true, false));
        return out;
    }
    if (kind == "waste_package:hazard") {
        const EntryPtr& W = a->waste;
        auto at = [&](const char* key) -> TNodePtr {
            const EntryPtr* slot = W->setting_at(key);
            return slot ? xleaf((*slot)->base) : K(0.0);
        };
        TNodePtr tree = hazard_tree(W->failure, t, at("fail_from"), at("fail_to"), at("fail_start"), at("fail_rate"), at("fail_scale"), at("fail_shape"));
        for (const auto& dis : W->disrupted)
            tree = bin(BinOp::Add, tree, bin(BinOp::Mul, xleaf(dis.D->lambda_slot->base), xleaf(dis.share->base)));
        out.push_back(make_stmt(a, a->base, tree, 1));
        return out;
    }
    if (kind == "event:lambda") {
        const EntryPtr& D = a->event;
        if (D->timing != "poisson") {
            out.push_back(make_stmt(a, a->base, K(0.0), 1));
            return out;
        }
        const EntryPtr* from_slot = D->setting_at("from");
        const EntryPtr* until_slot = D->setting_at("until");
        TNodePtr frm = from_slot ? xleaf((*from_slot)->base) : TNodePtr(make_leaf(LeafKind::T0));
        TNodePtr until = until_slot ? xleaf((*until_slot)->base) : TNodePtr(make_leaf(LeafKind::T1));
        TNodePtr inside = bin(BinOp::And, bin(BinOp::Ge, t, frm), bin(BinOp::Lt, t, until));
        TNodePtr rate = xleaf((*D->setting_at("rate"))->base);
        out.push_back(make_stmt(a, a->base, bin(BinOp::Mul, make_leaf(LeafKind::DIS, D->number), cond(inside, rate, K(0.0))), 1));
        return out;
    }
    if (kind == "waste_package") {
        const EntryPtr& W = a->waste;
        if (a->width == 0) return out;
        std::vector<int> idx = iota(0, a->width);
        auto leaf = [&](LeafKind k, int base) -> TNodePtr { return make_leaf(k, plus(base, idx)); };
        TNodePtr tree = bin(BinOp::Add,
                            bin(BinOp::Mul, bin(BinOp::Mul, xleaf(W->hazard_slot->base), leaf(LeafKind::Y, W->intact->base)),
                                leaf(LeafKind::X, (*W->setting_at("irf"))->base)),
                            bin(BinOp::Mul, leaf(LeafKind::X, (*W->setting_at("degradation_rate"))->base), leaf(LeafKind::Y, W->exposed->base)));
        out.push_back(make_stmt(a, plus(a->base, idx), tree, a->width));
        return out;
    }
    if (const EntryPtr& rec = a->recorder) {
        if (a->width == 0) return out;
        std::vector<int> offs = iota(0, a->width);
        if (rec->kind == "trigger") {
            TNodePtr tree = bin(BinOp::Sub, make_leaf(LeafKind::X, plus(rec->aux_at("first")->base, offs)),
                                make_leaf(LeafKind::X, plus(rec->aux_at("second")->base, offs)));
            out.push_back(make_stmt(a, plus(a->base, offs), tree, a->width));
            return out;
        }
        Special sp;
        sp.out = plus(a->base, offs);
        sp.mem = plus(rec->mem, offs);
        if (rec->kind == "min_max") {
            sp.kind = Special::Kind::MinMax;
            sp.arg = plus(rec->aux_at("target")->base, offs);
        } else if (rec->kind == "running_mean") {
            sp.kind = Special::Kind::RunningMean;
            sp.arg = plus(rec->aux_at("target")->base, offs);
            sp.state = plus(rec->state->base, offs);
        } else if (rec->kind == "snapshot") {
            sp.kind = Special::Kind::Snapshot;
        } else {
            sp.kind = Special::Kind::Delay;
            sp.arg = plus(rec->aux_at("delay")->base, offs);
        }
        out.push_back(special_stmt(a, std::move(sp), true, false));
        return out;
    }
    if (a->width == 0) return out;
    if (a->width == 1 && a->dims.empty()) {
        Tup nowhere;
        out.push_back(make_stmt(a, a->base, resolve_stmt_tree(a, *a->asts[0], no_dims, nullptr, &nowhere), 1));
    } else if (a->uniform) {
        Positions pos = space->positions(a->dims);
        TNodePtr tree = resolve_stmt_tree(a, *a->asts[0], a->dims, &pos, nullptr);
        out.push_back(make_stmt(a, iota(a->base, a->width), tree, a->width));
    } else {
        for (auto& s : by_equation(a)) out.push_back(s);
    }
    if (a->availability)
        for (auto& s : availability_stmts(a)) out.push_back(s);
    return out;
}

std::vector<std::shared_ptr<Stmt>> Builder::by_equation(const EntryPtr& a) {
    const std::vector<std::string>& dims = a->dims;
    std::vector<std::string> flat = flat_dimensions(*space, *a);
    if (!flat.empty()) {
        try {
            return groups(a, std::set<std::string>(flat.begin(), flat.end()));
        } catch (const BuildError&) {
        } catch (const IndexSpaceError&) {
        }
    }
    std::vector<std::shared_ptr<Stmt>> out;
    for (int off = 0; off < a->width; off++) {
        Tup tup = tuple_by_list(*space, dims, off);
        TNodePtr tree = resolve_stmt_tree(a, *a->asts[static_cast<std::size_t>(off)], dims, nullptr, &tup);
        out.push_back(make_stmt(a, a->base + off, tree, 1));
    }
    return out;
}

std::vector<std::shared_ptr<Stmt>> Builder::groups(const EntryPtr& a, const std::set<std::string>& flat_set) {
    const std::vector<std::string>& dims = a->dims;
    const std::vector<int> st = space->strides(dims);
    std::vector<int> sizes;
    for (const auto& d : dims) sizes.push_back(space->list_size(d));
    std::vector<std::size_t> varying, looped;
    for (std::size_t i = 0; i < dims.size(); i++) (flat_set.count(dims[i]) ? looped : varying).push_back(i);
    int ngroups = 1;
    for (std::size_t i : varying) ngroups *= sizes[i];
    // The looped dimensions' positions, in loop order (outer first: the last fastest).
    int count = 1;
    for (std::size_t i : looped) count *= sizes[i];
    std::vector<std::vector<int>> grids(looped.size(), std::vector<int>(static_cast<std::size_t>(count), 0));
    if (!looped.empty()) {
        std::vector<int> lst(looped.size(), 1);
        for (std::size_t i = looped.size(); i-- > 1;) lst[i - 1] = lst[i] * sizes[looped[i]];
        for (int c = 0; c < count; c++) {
            int rest = c;
            for (std::size_t j = 0; j < looped.size(); j++) {
                int q = rest / lst[j];
                rest -= q * lst[j];
                grids[j][static_cast<std::size_t>(c)] = q;
            }
        }
    }
    std::vector<std::shared_ptr<Stmt>> out;
    for (int g = 0; g < ngroups; g++) {
        std::vector<int> at(dims.size(), 0);
        int rest = g;
        for (std::size_t k = varying.size(); k-- > 0;) {
            std::size_t i = varying[k];
            at[i] = rest % sizes[i];
            rest /= sizes[i];
        }
        int base = a->base;
        for (std::size_t i = 0; i < dims.size(); i++) base += at[i] * st[i];
        const ENodePtr& ast = a->asts[static_cast<std::size_t>(base - a->base)];
        Positions pos;
        std::vector<int> offs(static_cast<std::size_t>(count), base);
        for (std::size_t i = 0; i < dims.size(); i++) {
            if (flat_set.count(dims[i])) {
                std::size_t j = static_cast<std::size_t>(std::find(looped.begin(), looped.end(), i) - looped.begin());
                const std::vector<int>& p = grids[j];
                for (std::size_t c = 0; c < offs.size(); c++) offs[c] += p[c] * st[i];
                pos.push_back(p);
            } else {
                pos.emplace_back(static_cast<std::size_t>(count), at[i]);
            }
        }
        TNodePtr tree = resolve_stmt_tree(a, *ast, dims, &pos, nullptr);
        out.push_back(make_stmt(a, std::move(offs), tree, count));
    }
    return out;
}

std::vector<std::shared_ptr<Stmt>> Builder::availability_stmts(const EntryPtr& a) {
    const Json& t = a->block;
    std::string tname = js_str(t.get("name"));
    EntryPtr src;
    if (js_truthy(t.get("from"))) {
        auto it = state_by_name.find(js_str(t.get("from")));
        if (it != state_by_name.end()) src = it->second;
    }
    if (!src)
        throw BuildError("'" + tname + "' has an availability, which is a fraction of what is in the compartment it flows out of, and it does "
                         "not flow out of one.", tname);
    const Json& scheme = a->availability->scheme;
    if (a->width == 0) return {};
    Positions pos = space->positions(a->dims);
    std::vector<int> idx = iota(0, a->width);

    // The amount: the donor's own cell, or every member of the group it shares a limit with.
    std::vector<int> base = state_offsets(a->dims, pos, src, tname, a->width);
    std::vector<AvailabilityTerm> terms;
    auto own = [&]() { terms.assign(1, AvailabilityTerm{base, 1.0, false, {}, 0}); };
    const Json& which_scheme = scheme.get("scheme");
    bool shared = which_scheme == "shared_limit" || which_scheme == "shared_langmuir";
    if (!shared) {
        own();
    } else {
        std::string over(js_trim(scheme.get("over").is_null() ? std::string() : js_str(scheme.get("over"))));
        const std::vector<std::string>& dims = src->dims;
        int which = -1;
        for (std::size_t k = 0; k < dims.size() && which < 0; k++)
            if (dims[k] == over) which = static_cast<int>(k);
        std::shared_ptr<const std::vector<int>> group_table;
        if (which < 0 && !over.empty() && space->has_list(over)) {
            const IndexList& grouping = space->get_list(over);
            for (std::size_t k = 0; k < dims.size() && which < 0; k++) {
                if (grouping.mapping.is_null() || grouping.root_name != space->get_list(dims[k]).root_name) continue;
                auto rel = space->relate(over, dims[k]);
                if (!rel || rel->kind != Relation::Kind::Map) continue;
                which = static_cast<int>(k);
                group_table = rel->table;
            }
        }
        int size = which < 0 ? 0 : space->list_size(dims[static_cast<std::size_t>(which)]);
        if (which < 0 || !(size > 1)) {
            own();
        } else {
            const std::string& along = dims[static_cast<std::size_t>(which)];
            int stride = space->strides(dims)[static_cast<std::size_t>(which)];
            std::vector<int> peer;
            bool found = false;
            for (std::size_t k = 0; k < a->dims.size() && !found; k++)
                if (a->dims[k] == along) {
                    peer = pos[k];
                    found = true;
                }
            for (std::size_t k = 0; k < a->dims.size() && !found; k++) {
                auto rel = space->relate(along, a->dims[k]);
                if (rel && rel->kind == Relation::Kind::Map) {
                    for (int x : pos[k]) peer.push_back((*rel->table)[static_cast<std::size_t>(x)]);
                    found = true;
                }
            }
            if (!found)
                throw BuildError("'" + tname + "' shares its amount along '" + along + "', which the transfer is not indexed by, so there is no "
                                 "telling which member of the group each flux belongs to.", tname);
            std::vector<int> first(peer.size());
            for (std::size_t e = 0; e < peer.size(); e++) first[e] = base[base.size() == 1 ? 0 : e] - stride * peer[e];
            bool moles = scheme.get("basis") == "moles";
            const std::vector<ListIndex>& names = space->get_list(along).enabled;
            std::string unit = js_truthy(project->simulation.get("time_unit")) ? js_str(project->simulation.get("time_unit")) : "year";
            double seconds_per = time_unit_years(unit) * SECONDS_PER_YEAR;
            std::vector<int> group_at;
            if (group_table)
                for (int x : peer) group_at.push_back((*group_table)[static_cast<std::size_t>(x)]);
            for (int i = 0; i < size; i++) {
                if (group_table && (*group_table)[static_cast<std::size_t>(i)] < 0) continue;
                double factor = 1.0;
                if (moles) {
                    double lam_i = static_cast<std::size_t>(i) < names.size() ? project->lam(names[static_cast<std::size_t>(i)].name, unit) : 0.0;
                    factor = moles_per_unit(project->decay_unit, lam_i, seconds_per);
                }
                if (factor == 0) continue;
                std::vector<int> off(first.size());
                for (std::size_t e = 0; e < first.size(); e++) off[e] = first[e] + i * stride;
                terms.push_back({std::move(off), factor, group_table != nullptr, group_at, group_table ? (*group_table)[static_cast<std::size_t>(i)] : 0});
            }
        }
    }
    TNodePtr amount = availability_sum(terms);
    std::vector<std::pair<std::string, TNodePtr>> ops;
    for (const auto& [key, op] : a->availability->operands) ops.emplace_back(key, make_leaf(LeafKind::X, plus(op->base, idx)));
    TNodePtr tree = availability_expression(scheme, amount, ops);
    return {make_stmt(a, plus(a->base, idx), tree, a->width, 1, true)};
}

std::vector<int> Builder::state_offsets(const std::vector<std::string>& source_dims, const Positions& pos, const EntryPtr& entry,
                                        const std::string& owner, int width) {
    std::size_t n = static_cast<std::size_t>(std::max(width, 1));
    std::vector<int> idx(n, entry->base);
    if (entry->dims.empty()) return idx;
    std::vector<ProjTerm> terms;
    try {
        ProjContext ctx{owner, entry->name};
        terms = space->projection(source_dims, entry->dims, nullptr, &ctx);
    } catch (const IndexSpaceError& e) {
        throw BuildError(e.what(), owner);
    }
    for (const auto& term : terms) {
        if (term.fixed >= 0) {
            for (int& x : idx) x += term.fixed * term.stride;
            continue;
        }
        const std::vector<int>& v = pos[static_cast<std::size_t>(term.from)];
        for (std::size_t e = 0; e < n; e++) {
            int at = v[e];
            idx[e] += (term.table ? (*term.table)[static_cast<std::size_t>(at)] : at) * term.stride;
        }
    }
    return idx;
}

std::vector<int> Builder::farf_inlet(const std::vector<std::string>& source_dims, const Positions& pos, const EntryPtr& entry,
                                     const std::string& owner, int width) {
    const FarfLayout& farf = *entry->farf;
    std::vector<ProjTerm> terms;
    try {
        ProjContext ctx{owner, entry->name};
        terms = space->projection(source_dims, entry->dims, nullptr, &ctx);
    } catch (const IndexSpaceError& e) {
        throw BuildError(e.what(), owner);
    }
    std::unordered_map<std::string, int> stride;
    if (farf.list_name) stride[*farf.list_name] = 1;
    const std::vector<int>& other_st = space->strides(farf.other_dims);
    for (std::size_t i = 0; i < farf.other_dims.size(); i++) stride[farf.other_dims[i]] = other_st[i] * farf.ncells * farf.nnuc;
    std::size_t n = static_cast<std::size_t>(std::max(width, 1));
    std::vector<int> idx(n, entry->base);
    for (const auto& term : terms) {
        int st = stride.at(term.dim);
        if (term.fixed >= 0) {
            for (int& x : idx) x += term.fixed * st;
            continue;
        }
        const std::vector<int>& v = pos[static_cast<std::size_t>(term.from)];
        for (std::size_t e = 0; e < n; e++) {
            int at = v[e];
            idx[e] += (term.table ? (*term.table)[static_cast<std::size_t>(at)] : at) * st;
        }
    }
    return idx;
}

// --- which slots move ----------------------------------------------------------------------------------

void Builder::classes() {
    for (const auto& a : algebraic) {
        bool state = false, clock = false;
        for (const auto& s : alg_stmts[a->name]) {
            if (s->special) {
                state = state || s->array == Stmt::Array::State;
                clock = clock || s->array == Stmt::Array::Clock;
                continue;
            }
            for (const auto& leaf : tree_leaves(s->tree)) {
                if (leaf->leaf == LeafKind::Y) state = true;
                else if (leaf->leaf == LeafKind::T || leaf->leaf == LeafKind::T0 || leaf->leaf == LeafKind::T1 || leaf->leaf == LeafKind::TAB ||
                         leaf->leaf == LeafKind::DIS)
                    clock = true;
            }
        }
        for (const auto& d : a->reads_alg) {
            if (on_state.count(d)) state = true;
            if (on_clock.count(d)) clock = true;
        }
        if (state) on_state.insert(a->name);
        if (clock) on_clock.insert(a->name);
    }
    slot_class.assign(static_cast<std::size_t>(std::max(1, nalg)), 0);
    for (const auto& a : algebraic) {
        int cls = on_state.count(a->name) ? 2 : (on_clock.count(a->name) ? 1 : 0);
        a->cls = cls;
        for (int k = 0; k < a->width; k++) slot_class[static_cast<std::size_t>(a->base + k)] = static_cast<unsigned char>(cls);
        for (const auto& s : alg_stmts[a->name]) {
            if (s->special) s->array = Stmt::Array::X;
            pass_stmts[cls].push_back(s);
        }
    }
}

// --- which of the moving blocks the derivative reads ---------------------------------------------------

// The moving blocks the derivative's phases read, and whatever those read in turn: the
// derivative and its Jacobian leave the others out (a dose, a concentration: only
// results, recorders and events read them). `derivative_stmts` is the moving pass without
// them, in the same order, and `derivative_blocks` their names: neither is made when
// nothing is left out.
void Builder::derivative_reads() {
    has_derivative_stmts = false;
    std::vector<int> slots;
    for (const auto& ph : phases) {
        switch (ph.kind) {
            case Phase::Kind::Transfers:
                for (int f : ph.a) slots.push_back(flux_rate[static_cast<std::size_t>(f)]);
                break;
            case Phase::Kind::X:
            case Phase::Kind::Mean: slots.insert(slots.end(), ph.a.begin(), ph.a.end()); break;
            case Phase::Kind::Waste:
                slots.push_back(ph.s1);
                slots.insert(slots.end(), ph.b.begin(), ph.b.end());
                break;
            case Phase::Kind::Move:
                slots.push_back(ph.s1);
                slots.push_back(ph.s2);
                break;
            case Phase::Kind::Farf: {
                std::vector<int> s = farfield_setting_slots(*FARF[static_cast<std::size_t>(ph.s1)]);
                slots.insert(slots.end(), s.begin(), s.end());
                break;
            }
            case Phase::Kind::Coef: break;
        }
    }
    for (const auto& W : waste_layout)
        for (int k = 0; k < W->width; k++) slots.push_back((*W->setting_at("irf"))->base + k);
    for (const auto& D : disruption_layout)
        for (const auto& s : D->shares) slots.push_back(s->base);
    std::vector<int> owner(static_cast<std::size_t>(std::max(1, nalg)), -1);
    std::unordered_map<std::string, int> index;
    for (std::size_t k = 0; k < algebraic.size(); k++) {
        const auto& a = algebraic[k];
        for (int i = 0; i < a->width; i++) owner[static_cast<std::size_t>(a->base + i)] = static_cast<int>(k);
        index[a->name] = static_cast<int>(k);
    }
    std::vector<char> need(algebraic.size(), 0);
    std::vector<int> stack;
    auto want = [&](int k) {
        if (k >= 0 && !need[static_cast<std::size_t>(k)]) {
            need[static_cast<std::size_t>(k)] = 1;
            stack.push_back(k);
        }
    };
    for (int s : slots) want(owner[static_cast<std::size_t>(s)]);
    while (!stack.empty()) {
        const auto& a = algebraic[static_cast<std::size_t>(stack.back())];
        stack.pop_back();
        for (const auto& n : a->reads_alg) {
            auto it = index.find(n);
            if (it != index.end()) want(it->second);
        }
        for (const auto& s : alg_stmts[a->name]) {
            if (!s->tree) continue;
            for (const auto& leaf : tree_leaves(s->tree)) {
                if (leaf->leaf != LeafKind::X) continue;
                if (!leaf->indices) want(owner[static_cast<std::size_t>(leaf->index)]);
                else
                    for (int i : *leaf->indices) want(owner[static_cast<std::size_t>(i)]);
            }
        }
    }
    bool every = true;
    for (std::size_t k = 0; k < algebraic.size(); k++)
        if (algebraic[k]->cls == 2 && !need[k]) every = false;
    if (every) return;
    has_derivative_stmts = true;
    for (std::size_t k = 0; k < algebraic.size(); k++) {
        if (!need[k]) continue;
        derivative_blocks.insert(algebraic[k]->name);
        if (algebraic[k]->cls != 2) continue;
        for (const auto& s : alg_stmts[algebraic[k]->name]) derivative_stmts.push_back(s);
    }
}

}  // namespace kompartment
