#include "engine/jacobian.hpp"

#include <algorithm>

#include "engine/farfield.hpp"
#include "model/simulation.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

bool diagonal_budget_solver(const std::string& id) {
    static const char* ids[] = {"ndf", "auto", "dp45", "tsit5", "vern7", "scipy_bdf", "scipy_radau", "scipy_lsoda"};
    for (const char* s : ids)
        if (id == s) return true;
    return false;
}

void sort_unique(std::vector<int>& v) {
    std::sort(v.begin(), v.end());
    v.erase(std::unique(v.begin(), v.end()), v.end());
}

const std::vector<int> NO_DEPS;

}  // namespace

bool full_budget(const System& sys) {
    if (!sys.builder->budget) return false;
    const Json& solver = sys.project->simulation.get("solver");
    return !diagonal_budget_solver(solver.is_null() ? std::string(DEFAULT_SOLVER) : js_str(solver));
}

ColumnGroups budgets_apart(const ColumnGroups& groups, const Builder& b, bool full) {
    if (!b.budget || full) return groups;
    I32 from = b.budget->base, to = b.budget->base + static_cast<I32>(b.budget->terms.size()) * b.budget->nfam;
    ColumnGroups rest;
    for (const auto& g : groups) {
        std::vector<I32> kept;
        for (I32 c : g)
            if (c < from || c >= to) kept.push_back(c);
        if (!kept.empty()) rest.push_back(std::move(kept));
    }
    std::vector<I32> budget;
    for (I32 c = from; c < to; c++) budget.push_back(c);
    rest.push_back(std::move(budget));
    return rest;
}

std::unordered_map<int, std::vector<int>> state_dependencies(const System& sys) {
    const Builder& b = *sys.builder;
    std::unordered_map<int, std::vector<int>> deps;
    const auto& moving = b.slot_class;
    auto of_x = [&](int idx) -> const std::vector<int>& {
        if (moving[static_cast<std::size_t>(idx)] != 2) return NO_DEPS;
        auto it = deps.find(idx);
        return it == deps.end() ? NO_DEPS : it->second;
    };
    for (const auto& a : b.algebraic) {
        if (a->cls != 2) continue;
        for (const auto& s : b.alg_stmts.at(a->name)) {
            if (s->special) {
                if (a->kind == "farfield") {
                    // A path's release reads the cells it is released from, and whatever its settings read.
                    const FarfieldPath& F = *b.FARF[static_cast<std::size_t>(a->farf_index)];
                    // (A semi-analytical path's release reads what flows into it: not worked out here yet.)
                    if (F.laplace) throw NotSupported("The C++ engine does not work out semi-analytical far-field paths yet.");
                    const std::vector<int>& release = F.release_slots();
                    for (int slot = 0; slot < F.slots(); slot++) {
                        std::vector<int> parts = F.rel_idx(slot);
                        for (int x : F.setting_slots_of(slot)) {
                            const std::vector<int>& more = of_x(x);
                            parts.insert(parts.end(), more.begin(), more.end());
                        }
                        sort_unique(parts);
                        deps[release[static_cast<std::size_t>(slot)]] = std::move(parts);
                    }
                    continue;
                }
                const EntryPtr& rec = a->recorder;
                if (!rec) continue;
                for (int off = 0; off < a->width; off++) {
                    std::vector<int> parts;
                    auto add = [&](const std::vector<int>& more) { parts.insert(parts.end(), more.begin(), more.end()); };
                    if (rec->kind == "min_max") {
                        add(of_x(rec->aux_at("target")->base + off));
                    } else if (rec->kind == "running_mean") {
                        parts.push_back(rec->state->base + off);
                        add(of_x(rec->aux_at("target")->base + off));
                    } else if (rec->kind == "delay") {
                        add(of_x(rec->aux_at("delay")->base + off));
                    }
                    sort_unique(parts);
                    deps[a->base + off] = std::move(parts);
                }
                continue;
            }
            std::size_t W = static_cast<std::size_t>(std::max(1, s->width));
            std::vector<int> outs = s->out_indices();
            if (outs.size() < W) outs.assign(W, outs[0]);
            std::vector<TLeafPtr> ys, xs;
            for (const auto& leaf : tree_leaves(s->tree)) {
                if (leaf->leaf == LeafKind::Y) ys.push_back(leaf);
                else if (leaf->leaf == LeafKind::X) xs.push_back(leaf);
            }
            for (std::size_t i = 0; i < W; i++) {
                std::vector<int> parts;
                for (const auto& l : ys) parts.push_back(l->index_at(i));
                for (const auto& l : xs) {
                    const std::vector<int>& more = of_x(l->index_at(i));
                    parts.insert(parts.end(), more.begin(), more.end());
                }
                if (s->multiply) {
                    // (its own slot read as well: what the statement multiplies)
                    auto own = deps.find(outs[i]);
                    if (own != deps.end()) {
                        std::vector<int> mine = own->second;
                        if (moving[static_cast<std::size_t>(outs[i])] == 2) parts.insert(parts.end(), mine.begin(), mine.end());
                        parts.insert(parts.end(), mine.begin(), mine.end());
                    }
                }
                sort_unique(parts);
                deps[outs[i]] = std::move(parts);
            }
        }
    }
    return deps;
}

Pattern jacobian_structure(const System& sys, bool full) {
    const Builder& b = *sys.builder;
    int n = sys.nstate;
    std::unordered_map<int, std::vector<int>> deps = state_dependencies(sys);
    const auto& moving = b.slot_class;
    std::vector<char> budget_rows(static_cast<std::size_t>(n), 0);
    if (b.budget && !full) {
        int from = b.budget->base, to = b.budget->base + static_cast<int>(b.budget->terms.size()) * b.budget->nfam;
        for (int r = from; r < to; r++) budget_rows[static_cast<std::size_t>(r)] = 1;
    }
    std::vector<I32> rows, cols;
    for (int i = 0; i < n; i++) {
        rows.push_back(i);
        cols.push_back(i);
    }
    auto x_deps = [&](int x) -> const std::vector<int>& {
        if (moving[static_cast<std::size_t>(x)] != 2) return NO_DEPS;
        auto it = deps.find(x);
        return it == deps.end() ? NO_DEPS : it->second;
    };
    auto add = [&](int row, const std::vector<int>& dep) {
        if (dep.empty() || budget_rows[static_cast<std::size_t>(row)]) return;
        for (int c : dep) {
            rows.push_back(row);
            cols.push_back(c);
        }
    };
    auto add_one = [&](int r, int c) {
        if (budget_rows[static_cast<std::size_t>(r)]) return;
        rows.push_back(r);
        cols.push_back(c);
    };
    for (const Phase& ph : b.phases) {
        switch (ph.kind) {
            case Phase::Kind::Transfers: {
                std::vector<int> src_of_flux(static_cast<std::size_t>(b.nflux), -1);
                for (std::size_t i = 0; i < b.flux_mbd.size(); i++) src_of_flux[static_cast<std::size_t>(b.flux_mbd[i])] = b.flux_mbd_src[i];
                for (std::size_t i = 0; i < ph.tgt.size(); i++) {
                    int src = src_of_flux[static_cast<std::size_t>(ph.a[i])];
                    if (src >= 0) add_one(ph.tgt[i], src);
                }
                for (std::size_t i = 0; i < ph.tgt.size(); i++) add(ph.tgt[i], x_deps(b.flux_rate[static_cast<std::size_t>(ph.a[i])]));
                break;
            }
            case Phase::Kind::X:
            case Phase::Kind::Mean:
                for (std::size_t i = 0; i < ph.tgt.size(); i++) add(ph.tgt[i], x_deps(ph.a[i]));
                break;
            case Phase::Kind::Waste: {
                for (std::size_t i = 0; i < ph.tgt.size(); i++) add_one(ph.tgt[i], ph.tgt[i]);
                for (std::size_t i = 0; i < ph.tgt.size(); i++) add_one(ph.a[i], ph.tgt[i]);
                for (std::size_t i = 0; i < ph.tgt.size(); i++) {
                    add(ph.tgt[i], x_deps(ph.s1));
                    add(ph.a[i], x_deps(ph.s1));
                    add(ph.a[i], x_deps(ph.b[i]));
                }
                for (std::size_t i = 0; i < ph.c.size(); i++) add(ph.c[i], x_deps(ph.b[i]));
                break;
            }
            case Phase::Kind::Move: {
                std::vector<int> extra = x_deps(ph.s1);
                const std::vector<int>& more = x_deps(ph.s2);
                extra.insert(extra.end(), more.begin(), more.end());
                sort_unique(extra);
                for (int r : ph.tgt) add_one(r, r);
                for (std::size_t i = 0; i < ph.a.size(); i++) add_one(ph.a[i], ph.tgt[i]);
                for (int r : ph.tgt) add(r, extra);
                for (int r : ph.a) add(r, extra);
                break;
            }
            case Phase::Kind::Coef:
                for (std::size_t i = 0; i < ph.tgt.size(); i++) add_one(ph.tgt[i], ph.a[i]);
                break;
            case Phase::Kind::Farf: {
                const FarfieldPath& F = *b.FARF[static_cast<std::size_t>(ph.s1)];
                const std::vector<int>& rf = F.row_flat();
                const std::vector<int>& cf = F.col_flat();
                for (std::size_t i = 0; i < rf.size(); i++) add_one(rf[i], cf[i]);
                // Settings that read the state: every row of the path reads what they read.
                std::vector<int> settings;
                for (int x : F.setting_slots()) {
                    const std::vector<int>& more = x_deps(x);
                    settings.insert(settings.end(), more.begin(), more.end());
                }
                sort_unique(settings);
                if (!settings.empty()) {
                    std::vector<int> path_rows = rf;
                    sort_unique(path_rows);
                    for (int r : path_rows) add(r, settings);
                }
                break;
            }
        }
    }
    return Pattern(n, rows, cols);
}

std::shared_ptr<JacobianInfo> build_jacobian(System& sys) {
    auto info = std::make_shared<JacobianInfo>();
    bool full = full_budget(sys);
    info->pattern = jacobian_structure(sys, full);
    info->groups = budgets_apart(colour_columns(*info->pattern), *sys.builder, full);
    int n = sys.nstate;
    info->nnz = static_cast<long>(info->pattern->nnz());
    info->colours = static_cast<int>(info->groups->size());
    info->density = static_cast<double>(info->nnz) / static_cast<double>(std::max(1L, static_cast<long>(n) * n));
    info->reason = "differenced through its pattern";
    try {
        std::shared_ptr<Analytic> an = make_analytic(sys, *info->pattern, full);
        if (an) {
            Vec J(static_cast<std::size_t>(info->nnz), 0.0);
            bool ok = true;
            try {
                ok = analytic_evaluate(J, *an, sys.start_time, sys.initial_state());
            } catch (const std::exception&) {
                ok = true;   // as the application: the model's arithmetic at the start says nothing here
            }
            sys.clock_at = std::numeric_limits<double>::quiet_NaN();
            if (ok) {
                info->available = true;
                info->reason.reset();
                info->constant = analytic_constant(*an);
                info->analytic = an;
            } else {
                info->reason = "the generated Jacobian has a non-finite entry at the starting state (an exact derivative may be infinite "
                               "where sqrt or log meets an empty compartment), and an infinite entry is not a matrix a solver can factorise";
            }
        }
    } catch (const NoDerivative& e) {
        info->reason = std::string("no derivative rule for ") + e.what();
    }
    if (sys.builder->budget && info->available) info->budget_rows = full ? "exact" : "diagonal";
    return info;
}

std::optional<JacobianSpec> jacobian_spec(System& sys, bool numeric) {
    const auto& j = sys.jacobian;
    if (!(j && j->pattern)) return std::nullopt;
    if (numeric || !j->analytic) return JacobianSpec(j->pattern, j->groups, nullptr, false);
    std::shared_ptr<Analytic> an = j->analytic;
    JacobianEvaluate ev = [an](Vec& vals, double t, const Vec& y) { return analytic_evaluate(vals, *an, t, y); };
    return JacobianSpec(j->pattern, j->groups, ev, j->constant, analytic_state_free(*an));
}

std::shared_ptr<JacobianInfo> clone_jacobian(const std::shared_ptr<JacobianInfo>& j, System& sys) {
    if (!j || !j->analytic) return j;
    auto out = std::make_shared<JacobianInfo>(*j);
    out->analytic = clone_analytic(j->analytic, sys);
    return out;
}

}  // namespace kompartment
