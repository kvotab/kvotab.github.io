#include "engine/paramtangent.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

#include "engine/farfield.hpp"
#include "engine/jacobian.hpp"
#include "engine/jacobian_analytic.hpp"
#include "engine/tree.hpp"

namespace kompartment {

struct ParamTangentPlan {
    /// One statement's part in df/dp: where its parameter leaves and its moving slots' leaves are.
    struct Statement {
        TNodePtr tree;
        std::vector<TLeafPtr> leaves;
        std::vector<int> outs;                                   // the slots it writes
        std::size_t width = 1;
        std::vector<std::pair<int, std::vector<int>>> p_terms;   // (leaf, from 0; the parameter slot of each element)
        std::vector<std::pair<int, std::vector<int>>> x_terms;   // (leaf; the algebraic slot of each element)
        bool multiply = false;
    };
    /// A statement, a remembering block's part (its slot's entry and its recorder), or a far-field
    /// path's (which path, and room for its rates' tangents).
    struct Item {
        enum class Kind : unsigned char { Statement, Recorder, Path };
        Kind kind = Kind::Statement;
        Statement statement;
        EntryPtr entry, rec;
        int index = -1;
        std::shared_ptr<FarfTangent> tangent;
    };
    /// A running mean's integrals: the summed states, the targets' slots, the first recorder.
    struct Mean {
        std::vector<int> s_idx, t_idx;
        int first = 0;
    };

    System* sys = nullptr;
    int n = 0;
    int nalg = 0;
    std::vector<Item> items;
    // The transfers' terms: target, flux and sign each, then every flux's rate slot and donor (-1: none).
    bool has_transfers = false;
    std::vector<int> tr_tgt, tr_flux, tr_rate, tr_src;
    std::vector<double> tr_sign;
    std::vector<std::pair<std::vector<int>, std::vector<int>>> xs;
    std::vector<Mean> means;
};

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();

/// A leaf's index for each of `w` elements (`_leaf_indices`).
std::vector<int> leaf_indices(const TLeaf& l, std::size_t w) {
    if (l.indices) return *l.indices;
    return std::vector<int>(w, l.index);
}

ParamTangentPlan::Item special_item(const Builder& b, const EntryPtr& a, std::vector<char>& moves) {
    ParamTangentPlan::Item item;
    if (a->kind == "farfield") {
        // A path on cells: its release moves along a parameter only if a setting does (the
        // cells are states, held), with the weights' own tangent: see `param_pvp`.
        FarfieldPath& F = *b.FARF[static_cast<std::size_t>(a->farf_index)];
        if (F.laplace) throw ParamTangentRefused("a far-field path, whose derivative along a parameter is not generated");
        const std::vector<int>& release = farfield_release_slots(F);
        for (std::size_t slot = 0; slot < release.size(); slot++) {
            bool any = false;
            for (int s : F.setting_slots_of(static_cast<int>(slot))) any = any || moves[static_cast<std::size_t>(s)] != 0;
            moves[static_cast<std::size_t>(release[slot])] = any;
        }
        item.kind = ParamTangentPlan::Item::Kind::Path;
        item.index = a->farf_index;
        item.tangent = std::make_shared<FarfTangent>(static_cast<const FarfPath&>(F));
        return item;
    }
    const EntryPtr& rec = a->recorder;
    if (!rec) throw ParamTangentRefused("a far-field path, whose derivative along a parameter is not generated");
    for (int off = 0; off < a->width; off++) {
        const std::size_t i = static_cast<std::size_t>(a->base + off);
        if (rec->kind == "min_max" || rec->kind == "running_mean") {
            moves[i] = moves[static_cast<std::size_t>(rec->aux_at("target")->base + off)];
        } else if (rec->kind == "delay") {
            if (moves[static_cast<std::size_t>(rec->aux_at("delay")->base + off)])
                throw ParamTangentRefused("a delay whose lag depends on a parameter: its value slides along the recorded history, and that "
                                          "derivative is not one to guess at");
            moves[i] = 0;
        } else {
            moves[i] = 0;
        }
    }
    item.kind = ParamTangentPlan::Item::Kind::Recorder;
    item.entry = a;
    item.rec = rec;
    return item;
}

/// Element `i`'s leaf values, as the tangent reads them (a table's leaf: its index).
void leaf_values(std::vector<double>& vals, const System& sys, const std::vector<TLeafPtr>& leaves, std::size_t i, const double* y,
                 const double* X, double t) {
    for (std::size_t p = 0; p < leaves.size(); p++) {
        const TLeaf& l = *leaves[p];
        double v = 0.0;
        switch (l.leaf) {
            case LeafKind::Y: v = y[l.index_at(i)]; break;
            case LeafKind::X: v = X[l.index_at(i)]; break;
            case LeafKind::P: v = sys.P[static_cast<std::size_t>(l.index_at(i))]; break;
            case LeafKind::K: v = l.value_at(i); break;
            case LeafKind::T: v = t; break;
            case LeafKind::T0: v = sys.start_time; break;
            case LeafKind::T1: v = sys.end_time; break;
            case LeafKind::DIS: v = sys.data.DIS[static_cast<std::size_t>(l.index_at(i))]; break;
            case LeafKind::TAB: v = static_cast<double>(l.index_at(i)); break;
        }
        vals[p] = v;
    }
}

/// A remembering block's slots along `w` (`_pt_recorder!`).
void recorder_tangent(const ParamTangentPlan& pt, const ParamTangentPlan::Item& item, const std::vector<double>& X, std::vector<double>& dX, double t) {
    const Entry& a = *item.entry;
    const Entry& rec = *item.rec;
    for (int off = 0; off < a.width; off++) {
        const std::size_t i = static_cast<std::size_t>(a.base + off);
        if (rec.kind == "min_max") {
            const std::size_t tgt = static_cast<std::size_t>(rec.aux_at("target")->base + off);
            dX[i] = X[i] == X[tgt] ? dX[tgt] : 0.0;
        } else if (rec.kind == "running_mean") {
            const std::size_t tgt = static_cast<std::size_t>(rec.aux_at("target")->base + off);
            const double el = pt.sys->data.MEM[static_cast<std::size_t>(rec.mem + off)].elapsed_at(t);
            dX[i] = el > 0 ? 0.0 : dX[tgt];
        } else {
            dX[i] = 0.0;
        }
    }
}

}  // namespace

std::shared_ptr<ParamTangentPlan> make_param_tangent_plan(System& sys) {
    const Builder& b = *sys.builder;
    auto pt = std::make_shared<ParamTangentPlan>();
    pt->sys = &sys;
    pt->n = sys.nstate;
    pt->nalg = sys.nalg;
    // Which slots a parameter reaches, structurally.
    std::vector<char> moves(static_cast<std::size_t>(std::max(1, sys.nalg)), 0);
    for (const auto& a : b.algebraic) {
        for (const auto& s : b.alg_stmts.at(a->name)) {
            if (s->special) {
                pt->items.push_back(special_item(b, a, moves));
                continue;
            }
            ParamTangentPlan::Statement st;
            const std::size_t W = static_cast<std::size_t>(std::max(1, s->width));
            std::vector<int> outs = s->out_indices();
            if (outs.size() < W) outs.assign(W, outs[0]);
            st.tree = s->tree;
            st.leaves = tree_leaves(s->tree);
            st.outs = outs;
            st.width = W;
            st.multiply = s->multiply;
            for (std::size_t pos = 0; pos < st.leaves.size(); pos++) {
                const TLeaf& leaf = *st.leaves[pos];
                if (leaf.leaf == LeafKind::P) {
                    st.p_terms.emplace_back(static_cast<int>(pos), leaf_indices(leaf, W));
                } else if (leaf.leaf == LeafKind::X) {
                    std::vector<int> idx = leaf_indices(leaf, W);
                    bool any = false;
                    for (int x : idx) any = any || moves[static_cast<std::size_t>(x)] != 0;
                    if (any) st.x_terms.emplace_back(static_cast<int>(pos), std::move(idx));
                }
            }
            if (!st.p_terms.empty() || !st.x_terms.empty()) {
                std::vector<char> live(st.leaves.size(), 0);
                for (const auto& term : st.p_terms) live[static_cast<std::size_t>(term.first)] = 1;
                for (const auto& term : st.x_terms) live[static_cast<std::size_t>(term.first)] = 1;
                check_tree_differentiable(*s->tree, live);
            }
            std::vector<char> reached(W, st.p_terms.empty() ? 0 : 1);
            for (const auto& term : st.x_terms)
                for (std::size_t i = 0; i < W; i++)
                    if (moves[static_cast<std::size_t>(term.second[i])]) reached[i] = 1;
            if (s->multiply)
                for (std::size_t i = 0; i < W; i++)
                    if (moves[static_cast<std::size_t>(outs[i])]) reached[i] = 1;
            for (std::size_t i = 0; i < W; i++) moves[static_cast<std::size_t>(outs[i])] = reached[i];
            ParamTangentPlan::Item item;
            item.kind = ParamTangentPlan::Item::Kind::Statement;
            item.statement = std::move(st);
            pt->items.push_back(std::move(item));
        }
    }
    // The assembly: the same phases the derivative is made of.
    const int n = sys.nstate;
    std::vector<char> budget(static_cast<std::size_t>(std::max(0, n)), 0);
    if (b.budget) {
        const int frm = b.budget->base;
        const int to = b.budget->base + static_cast<int>(b.budget->terms.size()) * b.budget->nfam;
        for (int k = frm; k < to; k++) budget[static_cast<std::size_t>(k)] = 1;
    }
    for (const Phase& ph : b.phases) {
        switch (ph.kind) {
            case Phase::Kind::Transfers: {
                std::vector<int> src_of(static_cast<std::size_t>(b.nflux), -1);
                for (std::size_t i = 0; i < b.flux_mbd.size(); i++) src_of[static_cast<std::size_t>(b.flux_mbd[i])] = b.flux_mbd_src[i];
                pt->has_transfers = true;
                pt->tr_tgt.clear();
                pt->tr_flux.clear();
                pt->tr_sign.clear();
                for (std::size_t q = 0; q < ph.tgt.size(); q++) {
                    if (budget[static_cast<std::size_t>(ph.tgt[q])]) continue;
                    pt->tr_tgt.push_back(ph.tgt[q]);
                    pt->tr_flux.push_back(ph.a[q]);
                    pt->tr_sign.push_back(ph.f[q]);
                }
                pt->tr_rate = b.flux_rate;
                pt->tr_src = std::move(src_of);
                break;
            }
            case Phase::Kind::X: {
                std::pair<std::vector<int>, std::vector<int>> x;
                for (std::size_t q = 0; q < ph.tgt.size(); q++) {
                    if (budget[static_cast<std::size_t>(ph.tgt[q])]) continue;
                    x.first.push_back(ph.tgt[q]);
                    x.second.push_back(ph.a[q]);
                }
                pt->xs.push_back(std::move(x));
                break;
            }
            case Phase::Kind::Mean: pt->means.push_back({ph.tgt, ph.a, ph.s1}); break;
            case Phase::Kind::Waste:
            case Phase::Kind::Move: throw ParamTangentRefused("a block whose derivative along a parameter is not generated");
            default:
                // Coef -- decay and ingrowth, whose coefficients are not parameters; Farf -- a path's
                // cells, held, under rates that move only with its settings -- taken with its
                // release (see `param_pvp`).
                break;
        }
    }
    return pt;
}

std::vector<double> param_pvp(ParamTangentPlan& pt, double t, const std::vector<double>& y, const std::vector<double>& w) {
    System& sys = *pt.sys;
    const std::vector<double>& X = sys.evaluate_algebraic(t, y.data());
    std::vector<double> dX(static_cast<std::size_t>(std::max(1, pt.nalg)), 0.0);
    std::vector<double> vals;
    // The far-field paths whose rates move along `w`, for the cells' part below.
    std::vector<const ParamTangentPlan::Item*> moved;
    for (const ParamTangentPlan::Item& item : pt.items) {
        if (item.kind == ParamTangentPlan::Item::Kind::Recorder) {
            recorder_tangent(pt, item, X, dX, t);
            continue;
        }
        if (item.kind == ParamTangentPlan::Item::Kind::Path) {
            // The release: the weights' tangent applied to the cells, one cell at a time from
            // zero, as the release is added up.
            FarfPath& F = static_cast<FarfPath&>(*sys.data.FARF[static_cast<std::size_t>(item.index)]);
            FarfTangent& T = *item.tangent;
            const bool moving = farfield_tangent(T, F, X.data(), dX.data());
            for (int slot = 0; slot < F.nslots; slot++) {
                double q = 0.0;
                if (moving) {
                    for (int r = 0; r < F.nrel; r++) {
                        const std::size_t at = static_cast<std::size_t>(slot * F.nrel + r);
                        q += T.drel[at] * y[static_cast<std::size_t>(F.rel_at[at])];
                    }
                }
                dX[static_cast<std::size_t>(F.release_slots()[static_cast<std::size_t>(slot)])] = q;
            }
            if (moving) moved.push_back(&item);
            continue;
        }
        const ParamTangentPlan::Statement& s = item.statement;
        const std::size_t W = s.width;
        std::vector<std::pair<int, std::vector<double>>> terms;
        for (const auto& [pos, idx] : s.p_terms) {
            std::vector<double> weight(idx.size());
            bool any = false;
            for (std::size_t k = 0; k < idx.size(); k++) {
                weight[k] = w[static_cast<std::size_t>(idx[k])];
                any = any || weight[k] != 0;
            }
            if (any) terms.emplace_back(pos, std::move(weight));
        }
        for (const auto& [pos, idx] : s.x_terms) {
            std::vector<double> weight(idx.size());
            bool any = false;
            for (std::size_t k = 0; k < idx.size(); k++) {
                weight[k] = dX[static_cast<std::size_t>(idx[k])];
                any = any || weight[k] != 0;
            }
            if (any) terms.emplace_back(pos, std::move(weight));
        }
        std::vector<double> before;
        bool any_before = false;
        if (s.multiply) {
            for (int o : s.outs) {
                before.push_back(dX[static_cast<std::size_t>(o)]);
                any_before = any_before || before.back() != 0;
            }
        }
        if (terms.empty() && (!s.multiply || !any_before)) {
            if (s.multiply)
                for (int o : s.outs) dX[static_cast<std::size_t>(o)] = 0.0;
            continue;
        }
        if (vals.size() < s.leaves.size()) vals.resize(s.leaves.size());
        std::vector<double> d(W, 0.0);
        std::vector<double> tangent(W);
        for (const auto& [pos, weight] : terms) {
            bool live = true;
            for (std::size_t i = 0; i < W; i++) {
                leaf_values(vals, sys, s.leaves, i, y.data(), X.data(), t);
                TreeTangent r = tree_tangent(*s.tree, sys.data.TAB, vals.data(), pos);
                if (!r.has) {
                    live = false;
                    break;
                }
                tangent[i] = r.tangent;
            }
            if (!live) continue;
            for (std::size_t i = 0; i < W; i++) d[i] = d[i] + tangent[i] * weight[i];
        }
        if (s.multiply) {
            // X[out] *= factor: the rate's own tangent scaled by the factor, plus the rate times
            // the factor's tangent. The slot holds rate * factor, so the rate is read back out.
            std::vector<double> next(W);
            for (std::size_t i = 0; i < W; i++) {
                leaf_values(vals, sys, s.leaves, i, y.data(), X.data(), t);
                const double f = tree_tangent(*s.tree, sys.data.TAB, vals.data(), -1).value;
                const double rate = f != 0 ? X[static_cast<std::size_t>(s.outs[i])] / f : 0.0;
                next[i] = before[i] * f + rate * d[i];
            }
            for (std::size_t i = 0; i < W; i++) dX[static_cast<std::size_t>(s.outs[i])] = next[i];
        } else {
            for (std::size_t i = 0; i < W; i++) dX[static_cast<std::size_t>(s.outs[i])] = d[i];
        }
    }
    const std::size_t n = static_cast<std::size_t>(pt.n);
    std::vector<double> out(n, 0.0);
    std::vector<double> add(n);
    auto add_into_out = [&]() {
        for (std::size_t i = 0; i < n; i++) out[i] = out[i] + add[i];
    };
    if (pt.has_transfers) {
        std::vector<double> dflux(pt.tr_rate.size());
        for (std::size_t q = 0; q < pt.tr_rate.size(); q++)
            dflux[q] = dX[static_cast<std::size_t>(pt.tr_rate[q])] * (pt.tr_src[q] >= 0 ? y[static_cast<std::size_t>(pt.tr_src[q])] : 1.0);
        std::fill(add.begin(), add.end(), 0.0);
        for (std::size_t q = 0; q < pt.tr_tgt.size(); q++) {
            const std::size_t at = static_cast<std::size_t>(pt.tr_tgt[q]);
            add[at] = add[at] + pt.tr_sign[q] * dflux[static_cast<std::size_t>(pt.tr_flux[q])];
        }
        add_into_out();
    }
    for (const auto& [tgt, xs] : pt.xs) {
        std::fill(add.begin(), add.end(), 0.0);
        for (std::size_t q = 0; q < tgt.size(); q++) {
            const std::size_t at = static_cast<std::size_t>(tgt[q]);
            add[at] = add[at] + dX[static_cast<std::size_t>(xs[q])];
        }
        add_into_out();
    }
    // A path's cells: the matrix's own tangent applied to them.
    for (const ParamTangentPlan::Item* item : moved) {
        const FarfPath& F = static_cast<const FarfPath&>(*sys.data.FARF[static_cast<std::size_t>(item->index)]);
        const std::vector<double>& dvals = item->tangent->dvals;
        const std::vector<int>& rows = F.row_flat();
        const std::vector<int>& cols = F.col_flat();
        std::fill(add.begin(), add.end(), 0.0);
        for (std::size_t i = 0; i < rows.size(); i++) {
            const std::size_t at = static_cast<std::size_t>(rows[i]);
            add[at] = add[at] + dvals[i] * y[static_cast<std::size_t>(cols[i])];
        }
        add_into_out();
    }
    const std::vector<Recorder>& mem = sys.data.MEM;
    for (const ParamTangentPlan::Mean& m : pt.means) {
        for (std::size_t q = 0; q < m.s_idx.size(); q++) {
            const double recording = mem[static_cast<std::size_t>(m.first) + q].recording ? 1.0 : 0.0;
            const std::size_t at = static_cast<std::size_t>(m.s_idx[q]);
            out[at] = out[at] + recording * dX[static_cast<std::size_t>(m.t_idx[q])];
        }
    }
    return out;
}

ParamTangent param_tangent(System& sys) {
    auto refused = [](std::string reason) {
        ParamTangent t;
        t.reason = std::move(reason);
        return t;
    };
    const auto& jac = sys.jacobian;
    if (!(jac && jac->available)) return refused("there is no analytic Jacobian: " + (jac && jac->reason ? *jac->reason : std::string("None")));
    if (!(sys.nparam > 0)) return refused("the model holds no parameters");
    const Builder& b = *sys.builder;
    bool semi = false;
    for (const auto& p : b.farf_layout) semi = semi || (p->farf && p->farf->laplace);
    if (semi) return refused("the model has a semi-analytical far-field path, whose derivative along a parameter is not generated");
    if (!b.waste_layout.empty()) return refused("the model has a waste package, whose derivative along a parameter is not generated");
    if (!b.disruption_layout.empty()) return refused("the model has a disruptive event, whose derivative along a parameter is not generated");
    std::shared_ptr<ParamTangentPlan> plan;
    try {
        plan = make_param_tangent_plan(sys);
    } catch (const NoDerivative& e) {
        return refused(std::string("no derivative rule for ") + e.what());
    } catch (const ParamTangentRefused& e) {
        return refused(e.what());
    }
    // The same question the Jacobian's own tangent answers at build: whether what it gives at
    // the start of the run is a number. A seed of ones exercises every parameter at once.
    std::optional<std::vector<double>> probe;
    try {
        std::vector<double> seed(static_cast<std::size_t>(sys.nparam), 1.0);
        probe = param_pvp(*plan, sys.start_time, sys.initial_state(), seed);
    } catch (const std::exception&) {
        probe.reset();
    }
    sys.clock_at = NaN;
    if (probe) {
        for (double v : *probe)
            if (!std::isfinite(v))
                return refused("df/dp has a non-finite entry at the starting state, and a driving term that is not a number is not one to "
                               "integrate");
    }
    ParamTangent t;
    t.available = true;
    t.plan = std::move(plan);
    return t;
}

}  // namespace kompartment
