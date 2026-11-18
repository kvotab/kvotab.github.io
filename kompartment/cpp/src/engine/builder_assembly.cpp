// The builder: the derivative's phases in the order the application adds its terms, the
// jumps in the state, and the initial state.

#include <algorithm>
#include <cmath>

#include "engine/builder.hpp"
#include "engine/builder_internal.hpp"
#include "engine/farfield.hpp"
#include "lang/parse.hpp"
#include "model/indexlists.hpp"
#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

using namespace detail;

namespace {

std::vector<int> plus(int base, const std::vector<int>& idx) {
    std::vector<int> out(idx.size());
    for (std::size_t i = 0; i < idx.size(); i++) out[i] = base + idx[i];
    return out;
}

template <class T>
std::vector<T> interleave(const std::vector<std::vector<T>>& cols) {
    std::size_t w = cols[0].size();
    std::vector<T> out;
    out.reserve(w * cols.size());
    for (std::size_t i = 0; i < w; i++)
        for (const auto& c : cols) out.push_back(c[i]);
    return out;
}

template <class T>
void append(std::vector<T>& to, const std::vector<T>& from) { to.insert(to.end(), from.begin(), from.end()); }

bool reads_time(const ENode& n) {
    switch (n.kind) {
        case ENode::Kind::Call:
            if (as_call(n).name == "time") return true;
            for (const auto& a : as_call(n).args)
                if (reads_time(*a)) return true;
            return false;
        case ENode::Kind::Unary: return reads_time(*as_unary(n).operand);
        case ENode::Kind::Binary: return reads_time(*as_binary(n).left) || reads_time(*as_binary(n).right);
        case ENode::Kind::Cond: return reads_time(*as_cond(n).test) || reads_time(*as_cond(n).then) || reads_time(*as_cond(n).otherwise);
        default: return false;
    }
}

}  // namespace

// --- the audit's families ------------------------------------------------------------------------------

std::vector<int> Builder::family_of(const std::vector<std::string>& dims, const Positions& pos, int width) const {
    int nfam = budget->nfam;
    std::optional<std::size_t> k;
    for (std::size_t i = 0; i < dims.size() && !k; i++)
        if (is_nuclide_dim(dims[i])) k = i;
    if (!k) return std::vector<int>(static_cast<std::size_t>(width), nfam - 1);
    if (dims[*k] == *material_list) return pos[*k];
    auto rel = space->relate(*material_list, dims[*k]);
    std::vector<int> out;
    out.reserve(pos[*k].size());
    for (int x : pos[*k]) {
        int f = (rel && rel->table) ? (*rel->table)[static_cast<std::size_t>(x)] : -1;
        out.push_back(f < 0 ? nfam - 1 : f);
    }
    return out;
}

std::vector<int> Builder::endpoint_family(const EntryPtr& entry, const std::vector<std::string>& dims, const Positions& pos, int width) const {
    for (const auto& d : entry->dims)
        if (is_nuclide_dim(d)) return family_of(dims, pos, width);
    return std::vector<int>(static_cast<std::size_t>(width), budget->nfam - 1);
}

std::string Builder::family_key(const EntryPtr& entry, const std::vector<std::string>& dims) const {
    bool a = false, b = false;
    for (const auto& d : entry->dims) a = a || is_nuclide_dim(d);
    for (const auto& d : dims) b = b || is_nuclide_dim(d);
    return (a && b) ? "loop" : "unindexed";
}

std::vector<int> Builder::budget_at(std::string_view term, const std::vector<int>& fam) const {
    const auto& terms = budget_terms();
    int at = static_cast<int>(std::find(terms.begin(), terms.end(), term) - terms.begin());
    std::vector<int> out(fam.size());
    for (std::size_t i = 0; i < fam.size(); i++) out[i] = budget->base + at * budget->nfam + fam[i];
    return out;
}

// --- the derivative ------------------------------------------------------------------------------------

void Builder::assembly() {
    auto state_of = [&](const Json& name) -> EntryPtr {
        if (!js_truthy(name)) return nullptr;
        auto it = state_by_name.find(js_str(name));
        return it == state_by_name.end() ? nullptr : it->second;
    };
    auto path_of = [&](const Json& name) -> EntryPtr {
        if (!js_truthy(name)) return nullptr;
        auto it = path_by_name.find(js_str(name));
        return it == path_by_name.end() ? nullptr : it->second;
    };
    auto empty_dim = [&](const EntryPtr& alg) {
        for (const auto& d : alg->dims)
            if (space->list_size(d) == 0) return true;
        return false;
    };
    std::vector<int> rate_idx, src_idx, contrib_flux, contrib_tgt;
    std::vector<char> mbd_mask;
    std::vector<double> contrib_sign;
    int n = 0;
    struct LaplaceIn {
        std::vector<int> where, rate, donor;
    };
    std::map<int, LaplaceIn> laplace_in;
    for (const Json& t : project->blocks_of("transfers")) {
        const EntryPtr& alg = alg_by_name.at(t.get("qname").as_string());
        std::string tname = js_str(t.get("name"));
        EntryPtr src = state_of(t.get("from"));
        EntryPtr tgt = state_of(t.get("to"));
        EntryPtr path = (js_truthy(t.get("to")) && !tgt) ? path_of(t.get("to")) : nullptr;
        const Json& by = t.get("multiply_by_donor");
        bool mbd = !(by.is_bool() && !by.as_bool());
        if (mbd && !src)
            throw BuildError("A transfer with no source compartment cannot be multiplied by its donor; set \"multiply_by_donor\": false to give "
                             "an absolute flux.", tname);
        int W = alg->width;
        if (W == 0 || empty_dim(alg)) continue;
        Positions pos = alg->dims.empty() ? Positions{} : space->positions(alg->dims);
        std::vector<int> k = iota(n, W);
        n += W;
        std::vector<int> rates = iota(alg->base, W);
        append(rate_idx, rates);
        std::vector<int> s_off, g_off, p_off;
        if (src) s_off = state_offsets(alg->dims, pos, src, tname, W);
        if (tgt) g_off = state_offsets(alg->dims, pos, tgt, tname, W);
        if (path) p_off = farf_inlet(alg->dims, pos, path, tname, W);
        std::vector<int> none(static_cast<std::size_t>(W), -1);
        if (path && path->farf->laplace) {
            LaplaceIn& in = laplace_in[path->farf_index];
            append(in.where, plus(-path->base, p_off));
            append(in.rate, rates);
            append(in.donor, (mbd && src) ? s_off : none);
        }
        mbd_mask.insert(mbd_mask.end(), static_cast<std::size_t>(W), mbd ? 1 : 0);
        append(src_idx, src ? s_off : none);
        std::vector<std::vector<int>> cols_t;
        std::vector<std::vector<double>> cols_s;
        auto col = [&](const std::vector<int>& target, double sign) {
            cols_t.push_back(target);
            cols_s.emplace_back(static_cast<std::size_t>(W), sign);
        };
        if (src) col(s_off, -1.0);
        if (tgt) col(g_off, 1.0);
        if (path) col(p_off, 1.0);
        if (budget) {
            std::vector<int> f_s, f_t;
            if (src) f_s = endpoint_family(src, alg->dims, pos, W);
            if (tgt) f_t = endpoint_family(tgt, alg->dims, pos, W);
            if (src && !tgt) col(budget_at("out", f_s), 1.0);
            const Json& from = t.get("from");
            if (!src && tgt && !(from.is_string() && waste_by_name.count(from.as_string()))) col(budget_at("in", f_t), 1.0);
            if (src && tgt && family_key(src, alg->dims) != family_key(tgt, alg->dims)) {
                col(budget_at("between", f_s), -1.0);
                col(budget_at("between", f_t), 1.0);
            }
        }
        if (cols_t.empty()) continue;
        std::vector<int> T = interleave(cols_t);
        std::vector<double> S = interleave(cols_s);
        std::vector<int> Fk = interleave(std::vector<std::vector<int>>(cols_t.size(), k));
        for (std::size_t i = 0; i < T.size(); i++) {
            if (T[i] < 0) continue;
            contrib_tgt.push_back(T[i]);
            contrib_sign.push_back(S[i]);
            contrib_flux.push_back(Fk[i]);
        }
    }
    for (const auto& p : farf_layout) {
        if (!p->farf->laplace) continue;
        const FarfieldPath& F = *FARF[static_cast<std::size_t>(p->farf_index)];
        int W = farfield_slots(F);
        if (W == 0) continue;
        std::vector<int> k = iota(n, W);
        n += W;
        append(rate_idx, farfield_release_slots(F));
        mbd_mask.insert(mbd_mask.end(), static_cast<std::size_t>(W), 0);
        src_idx.insert(src_idx.end(), static_cast<std::size_t>(W), -1);
        append(contrib_tgt, farfield_held_idx(F));
        contrib_sign.insert(contrib_sign.end(), static_cast<std::size_t>(W), -1.0);
        append(contrib_flux, k);
    }
    nflux = n;
    if (nflux > 0) {
        flux_rate = rate_idx;
        for (std::size_t i = 0; i < mbd_mask.size(); i++)
            if (mbd_mask[i]) {
                flux_mbd.push_back(static_cast<int>(i));
                flux_mbd_src.push_back(src_idx[i]);
            }
        Phase ph{Phase::Kind::Transfers, contrib_tgt, contrib_flux, {}, {}, contrib_sign, -1, -1};
        phases.push_back(std::move(ph));
    }

    // Inflows: + rate into the target (or a path's inlet), and 'in' to the budget.
    std::vector<int> tg, xs;
    for (const Json& s : project->blocks_of("inflows")) {
        const EntryPtr& alg = alg_by_name.at(s.get("qname").as_string());
        std::string sname = js_str(s.get("name"));
        EntryPtr tgt = state_of(s.get("to"));
        EntryPtr path = tgt ? nullptr : path_of(s.get("to"));
        int W = alg->width;
        if (W == 0 || empty_dim(alg)) continue;
        Positions pos = alg->dims.empty() ? Positions{} : space->positions(alg->dims);
        std::vector<int> target = tgt ? state_offsets(alg->dims, pos, tgt, sname, W) : farf_inlet(alg->dims, pos, path, sname, W);
        std::vector<int> rate = iota(alg->base, W);
        if (path && path->farf->laplace) {
            LaplaceIn& in = laplace_in[path->farf_index];
            append(in.where, plus(-path->base, target));
            append(in.rate, rate);
            in.donor.insert(in.donor.end(), static_cast<std::size_t>(W), -1);
        }
        std::vector<std::vector<int>> cols_t = {target}, cols_x = {rate};
        if (budget && tgt) {
            cols_t.push_back(budget_at("in", endpoint_family(tgt, alg->dims, pos, W)));
            cols_x.push_back(rate);
        }
        append(tg, interleave(cols_t));
        append(xs, interleave(cols_x));
    }
    if (!tg.empty()) phases.push_back(Phase{Phase::Kind::X, tg, xs, {}, {}, {}, -1, -1});
    for (const auto& p : farf_layout) {
        if (!p->farf->laplace) continue;
        LaplaceIn& in = laplace_in[p->farf_index];
        farfield_set_inflow(*FARF[static_cast<std::size_t>(p->farf_index)], in.where, in.rate, in.donor);
    }

    // Waste packages: fail out of the intact inventory, fail - release into the exposed.
    for (const auto& W : waste_layout) {
        if (W->width == 0) continue;
        const EntryPtr& Pd = W->intact;
        Positions pos = Pd->dims.empty() ? Positions{} : space->positions(Pd->dims);
        bool carried = false;
        for (const Json& t : project->blocks_of("transfers"))
            if (t.get("from") == W->q && !t.get("to").is_null() && state_by_name.count(js_str(t.get("to")))) carried = true;
        std::vector<int> idx = iota(0, W->width);
        std::vector<int> out_budget;
        if (budget && !carried) out_budget = budget_at("out", family_of(Pd->dims, pos, W->width));
        phases.push_back(Phase{Phase::Kind::Waste, plus(Pd->base, idx), plus(W->exposed->base, idx), plus(W->release_slot->base, idx), out_budget, {},
                               W->hazard_slot->base, -1});
    }

    // Disruptive events: the count, and moves at the expected-value rate.
    for (const auto& D : disruption_layout) {
        phases.push_back(Phase{Phase::Kind::X, {D->entry->base}, {D->lambda_slot->base}, {}, {}, {}, -1, -1});
        for (std::size_t k = 0; k < D->actions.size(); k++) {
            const Json& a = D->actions[k];
            if (!(a.get("kind") == "move")) continue;
            auto [A, B] = move_ends(D, a);
            if (A->width == 0) continue;
            Positions pos = A->dims.empty() ? Positions{} : space->positions(A->dims);
            std::vector<int> idx = iota(0, A->width);
            std::vector<int> second;
            if (B) second = plus(B->base, idx);
            else if (budget) second = budget_at("out", family_of(A->dims, pos, A->width));
            phases.push_back(Phase{Phase::Kind::Move, plus(A->base, idx), second, {}, {}, {}, D->lambda_slot->base, D->shares[k]->base});
        }
    }

    // Explicit dy/dt terms.
    tg.clear();
    xs.clear();
    for (const auto& slot : dydt_slots) {
        const EntryPtr& st = state_by_name.at(*slot->state_name);
        if (slot->width == 0) continue;
        Positions pos = slot->dims.empty() ? Positions{} : space->positions(slot->dims);
        std::vector<int> idx = iota(0, slot->width);
        std::vector<std::vector<int>> cols_t = {plus(st->base, idx)}, cols_x = {plus(slot->base, idx)};
        if (budget) {
            cols_t.push_back(budget_at("explicit", endpoint_family(st, slot->dims, pos, slot->width)));
            cols_x.push_back(plus(slot->base, idx));
        }
        append(tg, interleave(cols_t));
        append(xs, interleave(cols_x));
    }
    if (!tg.empty()) phases.push_back(Phase{Phase::Kind::X, tg, xs, {}, {}, {}, -1, -1});

    // Running means: dS/dt = target while recording.
    for (const auto& rec : recorders) {
        if (rec->kind != "running_mean" || rec->width == 0) continue;
        std::vector<int> idx = iota(0, rec->width);
        phases.push_back(Phase{Phase::Kind::Mean, plus(rec->state->base, idx), plus(rec->aux_at("target")->base, idx), {}, {}, {}, rec->mem, -1});
    }

    // Decay and ingrowth, per decaying state block, along its nuclide list.
    std::unordered_map<std::string, int> decay_index;
    auto decay_slot = [&](const std::string& list_name) {
        auto it = decay_index.find(list_name);
        if (it != decay_index.end()) return it->second;
        decay_lists.push_back(list_name);
        return decay_index[list_name] = static_cast<int>(decay_lists.size()) - 1;
    };
    auto table_for = [&](const std::string& lst) -> const DecayTables& {
        auto it = DEC_tables.find(lst);
        if (it != DEC_tables.end()) return it->second;
        DecayModel model = (material_list && lst == *material_list) ? decay : project->decay_model_for(lst);
        return DEC_tables.emplace(lst, decay_tables(model, space->list_size(lst))).first->second;
    };
    for (const auto& s : states) {
        if (s->kind != "compartment" && s->kind != "waste_package") continue;
        const Json& hd = s->block.get("handle_decay");
        if ((hd.is_bool() && !hd.as_bool()) || !material_list) continue;
        std::optional<int> m;
        for (std::size_t i = 0; i < s->dims.size() && !m; i++)
            if (is_nuclide_dim(s->dims[i])) m = static_cast<int>(i);
        if (!m) continue;
        decaying.push_back({s, *m, decay_slot(s->dims[static_cast<std::size_t>(*m)])});
    }
    for (const auto& lst : decay_lists) table_for(lst);
    std::vector<int> ctg, csr;
    std::vector<double> csc;
    for (const auto& d : decaying) {
        const EntryPtr& s = d.state;
        if (s->width == 0) continue;
        const DecayTables& D = table_for(s->dims[static_cast<std::size_t>(d.m)]);
        Positions pos = space->positions(s->dims);
        int stride_m = space->strides(s->dims)[static_cast<std::size_t>(d.m)];
        const std::vector<int>& nm = pos[static_cast<std::size_t>(d.m)];
        std::vector<int> fam, bdecay, bgrow;
        if (budget) {
            fam = family_of(s->dims, pos, s->width);
            bdecay = budget_at("decay", fam);
            bgrow = budget_at("ingrowth", fam);
        }
        for (int i = 0; i < s->width; i++) {
            std::size_t e = static_cast<std::size_t>(i);
            int si = s->base + i;
            int at = nm[e];
            double lam = D.lam[static_cast<std::size_t>(at)];
            ctg.push_back(si);
            csc.push_back(-lam);
            csr.push_back(si);
            if (budget) {
                ctg.push_back(bdecay[e]);
                csc.push_back(lam);
                csr.push_back(si);
            }
            int cnt = D.icnt[static_cast<std::size_t>(at)];
            for (int q = 0; q < cnt; q++) {
                std::size_t o = static_cast<std::size_t>(D.ioff[static_cast<std::size_t>(at)] + q);
                double coef = D.icoef[o];
                int src = si + (D.ipar[o] - at) * stride_m;
                ctg.push_back(si);
                csc.push_back(coef);
                csr.push_back(src);
                if (budget) {
                    ctg.push_back(bgrow[e]);
                    csc.push_back(coef);
                    csr.push_back(src);
                }
            }
        }
    }
    if (!ctg.empty()) phases.push_back(Phase{Phase::Kind::Coef, ctg, csr, {}, {}, csc, -1, -1});

    // Far-field paths: transport inside, then decay along their chain.
    for (const auto& p : farf_layout) {
        const DecayTables* dec = nullptr;
        const Json& hd = p->block.get("handle_decay");
        if (!(hd.is_bool() && !hd.as_bool()) && p->farf->list_name) {
            p->decay_slot = decay_slot(*p->farf->list_name);
            dec = &table_for(*p->farf->list_name);
        } else {
            p->decay_slot.reset();
        }
        FarfieldPath& F = *FARF[static_cast<std::size_t>(p->farf_index)];
        farfield_set_decay(F, dec);
        if (!p->farf->laplace) {
            Phase ph{Phase::Kind::Farf, {}, {}, {}, {}, {}, p->farf_index, -1};
            phases.push_back(std::move(ph));
        }
        if (!dec) continue;
        int nnuc = p->farf->nnuc;
        Phase ph{Phase::Kind::Coef, {}, {}, {}, {}, {}, -1, -1};
        for (int start : farfield_cell_starts(F)) {
            for (int m = 0; m < nnuc; m++) {
                int si = start + m;
                ph.tgt.push_back(si);
                ph.f.push_back(-dec->lam[static_cast<std::size_t>(m)]);
                ph.a.push_back(si);
                int cnt = dec->icnt[static_cast<std::size_t>(m)];
                for (int q = 0; q < cnt; q++) {
                    std::size_t o = static_cast<std::size_t>(dec->ioff[static_cast<std::size_t>(m)] + q);
                    ph.tgt.push_back(si);
                    ph.f.push_back(dec->icoef[o]);
                    ph.a.push_back(start + dec->ipar[o]);
                }
            }
        }
        phases.push_back(std::move(ph));
    }
}

std::pair<EntryPtr, EntryPtr> Builder::move_ends(const EntryPtr& D, const Json& a) const {
    const Json& from = a.get("from");
    auto A = from.is_string() ? state_by_name.find(from.as_string()) : state_by_name.end();
    if (A == state_by_name.end())
        throw BuildError("'" + js_text(from) + "' is not a compartment, so there is nothing to move out of it.", D->q);
    const Json& to = a.get("to");
    EntryPtr B;
    if (js_truthy(to)) {
        auto it = state_by_name.find(js_str(to));
        if (it == state_by_name.end()) throw BuildError("'" + js_str(to) + "' is not a compartment, so nothing can be moved into it.", D->q);
        B = it->second;
    }
    if (B && (B->width != A->second->width || join(B->dims, ",") != join(A->second->dims, ","))) {
        std::string fa = A->second->dims.empty() ? "by nothing" : join(A->second->dims, " \xc3\x97 ");
        std::string fb = B->dims.empty() ? "by nothing" : join(B->dims, " \xc3\x97 ");
        throw BuildError("'" + js_str(from) + "' and '" + js_str(to) + "' are indexed differently (" + fa + " against " + fb +
                         "). An event moves a share cell for cell, so the two have to match.", D->q);
    }
    return {A->second, B};
}

// --- jumps ---------------------------------------------------------------------------------------------

std::optional<JumpOp> Builder::fail_op(const EntryPtr& W, int share_slot) {
    const EntryPtr& Pd = W->intact;
    const Json* carrier = nullptr;
    for (const Json& t : project->blocks_of("transfers"))
        if (t.get("from") == W->q) {
            carrier = &t;
            break;
        }
    Json to = carrier ? carrier->get("to") : Json();
    EntryPtr tgt, path;
    if (js_truthy(to)) {
        auto it = state_by_name.find(js_str(to));
        if (it != state_by_name.end()) tgt = it->second;
        else if (auto pt = path_by_name.find(js_str(to)); pt != path_by_name.end()) path = pt->second;
    }
    if (W->width == 0) return std::nullopt;
    Positions pos = Pd->dims.empty() ? Positions{} : space->positions(Pd->dims);
    std::vector<int> idx = iota(0, W->width);
    JumpOp op;
    op.kind = JumpOp::Kind::Fail;
    op.share_slot = share_slot;
    op.intact = plus(Pd->base, idx);
    op.exposed = plus(W->exposed->base, idx);
    op.irf = plus((*W->setting_at("irf"))->base, idx);
    if (tgt) op.to = state_offsets(Pd->dims, pos, tgt, js_str(carrier->get("name")), W->width);
    else if (path) op.to = farf_inlet(Pd->dims, pos, path, js_str(carrier->get("name")), W->width);
    if (budget && !tgt) op.budget = budget_at("out", family_of(Pd->dims, pos, W->width));
    return op;
}

void Builder::jumps() {
    for (const auto& W : waste_layout) {
        if (W->failure != "at") continue;
        JumpSpec spec;
        spec.name = W->q;
        if (auto op = fail_op(W, -1)) spec.ops.push_back(*op);
        const Json& fa = W->block.get("fail_at");
        spec.slot = (*W->setting_at("fail_at"))->base;
        spec.text = fa.is_null() ? std::string() : js_str(fa);
        jump_specs.push_back(std::move(spec));
    }
    for (const auto& D : disruption_layout) {
        JumpSpec spec;
        spec.name = D->q;
        spec.index = D->number;
        JumpOp count;
        count.kind = JumpOp::Kind::Count;
        count.slot = D->entry->base;
        spec.ops.push_back(count);
        for (std::size_t k = 0; k < D->actions.size(); k++) {
            const Json& a = D->actions[k];
            int share = D->shares[k]->base;
            if (a.get("kind") == "fail") {
                if (auto op = fail_op(waste_by_name.at(a.get("block").as_string()), share)) spec.ops.push_back(*op);
                continue;
            }
            auto [A, B] = move_ends(D, a);
            if (A->width == 0) continue;
            Positions pos = A->dims.empty() ? Positions{} : space->positions(A->dims);
            std::vector<int> idx = iota(0, A->width);
            JumpOp op;
            op.kind = JumpOp::Kind::Move;
            op.share_slot = share;
            op.from = plus(A->base, idx);
            if (B) op.to = plus(B->base, idx);
            if (!B && budget) op.budget = budget_at("out", family_of(A->dims, pos, A->width));
            spec.ops.push_back(std::move(op));
        }
        if (D->timing == "at") {
            const Json& at = D->block.get("at");
            spec.slot = (*D->setting_at("at"))->base;
            spec.text = at.is_null() ? std::string() : js_str(at);
        } else if (D->timing == "trigger") {
            // Not a corner known before the run: applied where its trigger fires.
            spec.fired_by = D->fired_by;
        }
        jump_specs.push_back(std::move(spec));
    }
}

// --- the initial state ---------------------------------------------------------------------------------

void Builder::initial_state() {
    // The algebraic blocks that hold the same value for the whole run, which an initial
    // condition may read.
    std::unordered_set<std::string> invariant;
    auto known_block = [&](const std::string& n) { return alg_by_name.count(n) != 0 || state_by_name.count(n) != 0; };
    for (const auto& a : algebraic) {
        if (a->kind != "expression" && a->kind != "index_reduction" && a->kind != "block_reduction") continue;
        std::vector<ENodePtr> distinct = distinct_asts(*a);
        bool clock = false;
        for (const auto& ast : distinct) clock = clock || reads_time(*ast);
        if (clock) continue;
        std::set<std::string> refs;
        for (const auto& ast : distinct) collect_references(refs, *ast);
        for (const auto& n : a->needs) refs.insert(n);
        bool ok = true;
        for (const auto& r : refs) {
            auto q = resolve_reference(r, a->system, known_block);
            if (!q) continue;
            if (*q != a->name && !invariant.count(*q)) {
                ok = false;
                break;
            }
        }
        if (ok) invariant.insert(a->name);
    }
    auto why_not_initial = [&](const std::string& name, const Entry& s) -> std::string {
        std::string where = !s.system.empty() ? " in '" + s.system + "' or at the top level" : "";
        auto q = resolve_reference(name, s.system, known_block);
        if (q && state_by_name.count(*q))
            return "Initial condition cannot read '" + name + "': it is a compartment, and no compartment has a value until every initial "
                   "condition has been worked out. Use a parameter or an expression that does not read the state.";
        if (q && alg_by_name.count(*q)) {
            const std::string& kind = alg_by_name.at(*q)->kind;
            std::string why = kind == "lookup" ? ", being read from a table at the clock" : kind == "farfield" ? ", being the release out of a far-field path" : "";
            return "Initial condition cannot read '" + name + "': its value changes over the run" + why + ". Only a parameter, or an expression "
                   "made of parameters and numbers, holds the same value at every moment.";
        }
        return "Initial condition may only use parameters, numbers and expressions that do not change over the run; '" + name +
               "' is not one of those" + where + ".";
    };

    std::unordered_set<std::string> used;
    for (const auto& s : states) {
        if (s->kind == "farfield" || s->kind == "budget" || s->kind == "event") continue;
        if (s->kind == "waste_package" && s->role != "intact") continue;
        std::string key = s->kind == "waste_package" ? "inventory" : "initial";
        std::unordered_map<std::string, ENodePtr> parsed;
        auto value_of = entry_lookup(s->block, key);
        std::vector<std::string> block_dims = strings_of(s->block.get("index_lists"));
        std::string block_system = js_truthy(s->block.get("system")) ? js_str(s->block.get("system")) : "";
        for (int off = 0; off < s->width; off++) {
            Tup tup = space->pin_scenario(block_dims, tuple_by_list(*space, s->dims, off));
            Json v = value_of(tup);
            std::string eq = v.is_null() ? std::string("0") : js_str(v);
            RefResolver resolve = [&](const ERef& ref) -> TNodePtr {
                const std::string& name = ref.name;
                auto q = resolve_reference(name, s->system, [&](const std::string& n) { return param_by_name.count(n) != 0 || invariant.count(n) != 0; });
                EntryPtr pr;
                bool is_param = false;
                if (q) {
                    if (auto it = param_by_name.find(*q); it != param_by_name.end()) {
                        pr = it->second;
                        is_param = true;
                    } else if (auto it2 = alg_by_name.find(*q); it2 != alg_by_name.end()) {
                        pr = it2->second;
                    }
                }
                if (!pr) throw BuildError(why_not_initial(name, *s), s->name);
                LeafKind store = is_param ? LeafKind::P : LeafKind::X;
                if (!is_param) used.insert(*q);
                if (pr->dims.empty()) return make_leaf(store, pr->base);
                Entry::Context here;
                here.items.emplace_back(COMPARTMENT_LIST, s->name);
                Tup t{{COMPARTMENT_LIST, s->name}};
                t = t.merged(tup).merged(pin_indices(*space, *pr, ref.indices, name, s->name, &here));
                const std::vector<int>& st = space->strides(pr->dims);
                int o = 0;
                for (std::size_t i = 0; i < pr->dims.size(); i++) {
                    const std::string& dim = pr->dims[i];
                    auto p = position_in(*space, dim, t);
                    if (!p) {
                        std::string msg = dim == TRANSFER_LIST
                                              ? "'" + name + "' has a value per transfer, and a compartment is not a transfer. Name one, as '" + name + "[<transfer>]'."
                                              : "'" + name + "' is indexed by '" + dim + "', which the initial condition of '" + s->name +
                                                "' cannot resolve. Give an explicit index.";
                        throw BuildError(msg, s->name);
                    }
                    o += *p * st[i];
                }
                return make_leaf(store, pr->base + o);
            };
            TNodePtr tree;
            try {
                auto hit = parsed.find(eq);
                if (hit == parsed.end()) hit = parsed.emplace(eq, parse_model_equation(eq, block_system, s->name)).first;
                tree = resolve_tree(*hit->second, resolve);
            } catch (const EquationParseError& e) {
                throw BuildError(std::string(e.what()) + " in initial condition \"" + eq + "\"", s->name);
            } catch (const BuildError&) {
                throw;
            } catch (const IndexSpaceError&) {
                throw;
            } catch (const NotSupported&) {
                throw;
            } catch (const std::invalid_argument& e) {
                throw BuildError(e.what(), s->name);
            } catch (const std::runtime_error& e) {
                throw BuildError(e.what(), s->name);
            }
            auto stmt = std::make_shared<Stmt>();
            stmt->out = s->base + off;
            stmt->tree = tree;
            stmt->width = 1;
            stmt->array = Stmt::Array::Y0;
            initial_stmts.push_back(stmt);
        }
    }
    if (!used.empty()) {
        std::unordered_set<std::string> wanted = used;
        for (auto a = algebraic.rbegin(); a != algebraic.rend(); ++a)
            if (wanted.count((*a)->name))
                for (const auto& r : (*a)->reads_alg) wanted.insert(r);
        for (const auto& a : algebraic)
            if (wanted.count(a->name))
                for (const auto& st : alg_stmts[a->name]) initial_before.push_back(st);
    }
}

}  // namespace kompartment
