#include "engine/localsens.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <functional>
#include <limits>
#include <unordered_map>
#include <unordered_set>
#include <utility>

#include "engine/builder.hpp"
#include "engine/farfield.hpp"
#include "engine/farfield_domain.hpp"
#include "engine/jacobian.hpp"
#include "engine/recorders.hpp"
#include "engine/switchtimes.hpp"
#include "stats/pdf.hpp"
#include "util/errors.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
/// sqrt(2^-52), the forward step's scale and the size of a difference of J·v.
constexpr double LS_EPS = 0x1p-26;
constexpr double JAC_SQRT_EPS = 0x1p-26;

double now_s() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

// --- the parameter slots ----------------------------------------------------------------------------

/// A key JavaScript takes for an array index: `0` or digits without a leading zero, below 2^32 - 1.
bool is_array_index(const std::string& k) {
    if (k.empty() || k.size() > 10) return false;
    if (k.size() > 1 && k[0] == '0') return false;
    for (char c : k)
        if (c < '0' || c > '9') return false;
    return std::stoull(k) < 4294967295ULL;
}

/// Keys in the order JavaScript enumerates an object's: the integer-like ones first, ascending,
/// then the rest as they were inserted (`_ls_js_ordered`).
template <class Items>
Json js_ordered_items(const Items& items) {
    std::vector<std::pair<unsigned long long, Json>> ints;
    std::vector<std::pair<std::string, Json>> keys;
    for (const auto& [k, v] : items) {
        std::string key(k);
        if (is_array_index(key)) ints.emplace_back(std::stoull(key), Json(v));
        keys.emplace_back(std::move(key), Json(v));
    }
    std::stable_sort(ints.begin(), ints.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
    Json out = Json::object();
    for (const auto& [k, v] : ints) out.set(std::to_string(k), v);
    for (const auto& [k, v] : keys)
        if (!is_array_index(k)) out.set(k, v);
    return out;
}

Json js_ordered(const Json& d) { return d.is_object() ? js_ordered_items(d.obj()) : Json::object(); }
Json js_ordered(const Tup& tup) { return js_ordered_items(tup); }

/// `effectiveValue`: the most specific entry that sets `key` and matches `index`, else the
/// block's own; none (`undefined`) where neither says anything.
const Json* effective_value(const Json& block, std::string_view key, const Json& index) {
    const Json* best = nullptr;
    int best_score = -1;
    const Json& entries = block.is_object() ? block.get("entries") : Json::null_value;
    if (entries.is_array()) {
        for (const Json& entry : entries.arr()) {
            if (!(entry.is_object() && entry.has(key))) continue;
            int score = 0;
            bool ok = true;
            const Json& idx = entry.get("index");
            if (idx.is_object()) {
                for (const auto& [lst, name] : idx.obj()) {
                    const Json& have = index.get(lst);
                    // (JavaScript's `!==`: text against text, and a list the index does not name is undefined.)
                    if (!(index.has(lst) && have.is_string() && name.is_string() && have.as_string() == name.as_string())) {
                        ok = false;
                        break;
                    }
                    score += 1;
                }
            }
            if (ok && score > best_score) {
                best_score = score;
                best = &entry.get(key);
            }
        }
    }
    if (best_score >= 0) return best;
    return block.is_object() && block.has(key) ? &block.get(key) : nullptr;
}

// --- what the forward equations cannot carry -----------------------------------------------------------

/// Something given: not null, and not text that is all white space.
bool said(const Json& v) { return !v.is_null() && !(v.is_string() && js_trim(v.as_string()).empty()); }

/// The algebraic blocks the derivative reads, directly or through others (`readByDerivative`).
std::vector<EntryPtr> read_by_derivative(const System& sys) {
    const auto& algebraic = sys.builder->algebraic;
    std::unordered_map<std::string, EntryPtr> by_name;
    for (const auto& a : algebraic) by_name[a->name] = a;
    auto starts = [](const std::string& s, const char* p) { return s.rfind(p, 0) == 0; };
    auto direct = [&](const Entry& a) {
        const std::string& k = a.kind;
        return k == "transfer" || k == "inflow" || k == "compartment:dydt" || k == "waste_package" || k == "farfield" || k == "running_mean:target" ||
               starts(k, "waste_package:") || starts(k, "event:") || starts(k, "farfield:");
    };
    std::unordered_set<std::string> reached;
    std::vector<std::string> stack;
    for (const auto& a : algebraic)
        if (direct(*a)) stack.push_back(a->name);
    while (!stack.empty()) {
        std::string name = stack.back();
        stack.pop_back();
        if (reached.count(name)) continue;
        reached.insert(name);
        auto it = by_name.find(name);
        if (it != by_name.end()) stack.insert(stack.end(), it->second->reads_alg.begin(), it->second->reads_alg.end());
    }
    std::vector<EntryPtr> out;
    for (const auto& a : algebraic)
        if (reached.count(a->name)) out.push_back(a);
    return out;
}

bool switched_by_event(const System& sys, const Entry& rec) {
    const IndexSpace& space = *sys.builder->space;
    for (int off = 0; off < rec.width; off++) {
        Tup tup = rec.dims.empty() ? Tup() : tuple_by_list(space, rec.dims, off);
        // At the scenario that runs, as the builder reads the event fields.
        tup = space.pin_scenario(strings_of(rec.block.get("index_lists")), tup);
        for (const std::string& field : event_fields(rec.kind))
            if (said(value_at(rec.block, field, tup))) return true;
    }
    return false;
}

/// `fn()` with every value of a parameter block moved a little, then put back
/// (`_ls_with_block_moved`). The block is the builder's own dictionary, which the project
/// shares when it is the project built from.
std::vector<double> with_block_moved(const std::function<std::vector<double>()>& fn, const Json& shared) {
    Json block = shared;   // the same dictionary
    auto move = [](const Json& v) -> Json {
        const double x = pd_to_number(v);
        return std::isfinite(x) && said(v) ? Json(x * (1 + 1e-6) + 1e-9) : v;
    };
    std::optional<Json> had_value;
    if (block.is_object() && block.has("value")) had_value = block.get("value");
    std::vector<Json> entries;
    std::vector<std::optional<Json>> had_entries;
    if (block.is_object() && block.get("entries").is_array()) {
        for (const Json& e : block.get("entries").arr()) {
            entries.push_back(e);
            had_entries.push_back(e.is_object() && e.has("value") ? std::optional<Json>(e.get("value")) : std::nullopt);
        }
    }
    auto restore = [&]() {
        if (had_value) block.set("value", *had_value);
        for (std::size_t k = 0; k < entries.size(); k++)
            if (had_entries[k]) entries[k].set("value", *had_entries[k]);
    };
    std::vector<double> out;
    try {
        if (had_value) block.set("value", move(*had_value));
        for (Json& e : entries)
            if (e.is_object() && e.has("value")) {
                Json moved = move(e.get("value"));
                e.set("value", moved);
            }
        out = fn();
    } catch (...) {
        restore();
        throw;
    }
    restore();
    return out;
}

// --- the closures' state ------------------------------------------------------------------------------

/// What the right-hand side, the big Jacobian and the iteration matrix share.
struct Work {
    std::shared_ptr<System> system;
    System* sys = nullptr;
    int n = 0, mm = 0;
    std::vector<int> slots;
    std::shared_ptr<ParamTangentPlan> plan;
    std::size_t nparam = 1;
    std::shared_ptr<Analytic> an;
    const Pattern* pattern = nullptr;
    std::size_t nnz = 0;
    bool budgeted = false;
    std::vector<char> budget_rows;
    // the clock's interpolation, anchored where each stretch of the run starts
    double clock_interval = 0.0, clock_from = 0.0;
    Vec J, f0, fp, jv, yv, sv, seed, moved, yd;
    Vec J0, Jm, coupling, yc, ys;
    std::shared_ptr<const std::vector<std::vector<I32>>> state_at;

    /// The two ends the clock's interpolation holds were worked out from the parameter as it
    /// was: dropped around each difference.
    void forget_clock() {
        if (clock_interval > 0) sys->use_clock_interpolation(clock_interval, clock_from);
    }

    /// J·v off the Jacobian's values at (t, y) -- or, at a point where the analytic Jacobian
    /// declines (an entry that is not finite), differenced along v, as the solvers difference
    /// the matrix there.
    const Vec& jvp(double t, bool have) {
        std::fill(jv.begin(), jv.end(), 0.0);
        const std::size_t N = static_cast<std::size_t>(n);
        if (have) {
            const I32* rows = pattern->rowval.data();
            const I32* cols = pattern->col_of.data();
            for (std::size_t q = 0; q < nnz; q++) jv[rows[q]] = jv[rows[q]] + J[q] * sv[cols[q]];
            return jv;
        }
        // Julia's `maximum(abs, v)`: NaN where any is.
        auto max_abs = [N](const Vec& v) {
            double m = 0.0;
            for (std::size_t i = 0; i < N; i++) {
                const double a = std::fabs(v[i]);
                if (std::isnan(a) || std::isnan(m)) m = NaN;
                else if (i == 0 || a > m) m = a;
            }
            return m;
        };
        const double size = n == 0 ? 0.0 : max_abs(sv);
        if (!(size > 0)) return jv;
        const double biggest = n == 0 ? 0.0 : max_abs(yv);
        const double delta = JAC_SQRT_EPS * (biggest > 1.0 ? biggest : 1.0) / size;
        std::fill(moved.begin(), moved.end(), 0.0);
        for (std::size_t i = 0; i < N; i++) yd[i] = yv[i] + delta * sv[i];
        sys->rhs(moved.data(), t, yd.data());
        for (std::size_t i = 0; i < N; i++) jv[i] = (moved[i] - f0[i]) / delta;
        return jv;
    }

    void dydt(Vec& out, double t, const Vec& Y) {
        const std::size_t N = static_cast<std::size_t>(n);
        std::copy_n(Y.begin(), N, yv.begin());
        sys->rhs(f0.data(), t, yv.data());
        std::copy_n(f0.begin(), N, out.begin());
        const bool have = analytic_evaluate(J, *an, t, yv);
        std::vector<double>& P = sys->P;
        for (int j = 1; j <= mm; j++) {
            const std::size_t base = N * static_cast<std::size_t>(j);
            std::copy_n(Y.begin() + static_cast<std::ptrdiff_t>(base), N, sv.begin());
            jvp(t, have);
            const std::size_t slot = static_cast<std::size_t>(slots[static_cast<std::size_t>(j - 1)]);
            if (plan) {
                std::fill(seed.begin(), seed.end(), 0.0);
                seed[slot] = 1.0;
                const std::vector<double> pv = param_pvp(*plan, t, yv, seed);
                for (std::size_t i = 0; i < N; i++) out[base + i] = jv[i] + pv[i];
                continue;
            }
            // df/dp by one forward difference. The invariant pass carries the new parameter
            // into the algebra worked out from the old one.
            const double p0 = P[slot];
            const double h = step_for(p0);
            P[slot] = p0 + h;
            sys->evaluate_invariant();
            forget_clock();
            sys->rhs(fp.data(), t, yv.data());
            P[slot] = p0;
            sys->evaluate_invariant();
            forget_clock();
            for (std::size_t i = 0; i < N; i++) out[base + i] = jv[i] + (fp[i] - f0[i]) / h;
        }
    }

    /// d(S_j')/dy into `coupling`, on J's pattern, from J's values `J0` at (t, y): J's own
    /// derivative along (S_j, e_j) -- J at the state moved by e·S_j and the parameter by e,
    /// less J, over e -- and nothing on the budget rows, where df/dp writes nothing.
    const Vec& coupling_of(double t, const Vec& Y, int j) {
        const std::size_t N = static_cast<std::size_t>(n);
        std::vector<double>& P = sys->P;
        const std::size_t slot = static_cast<std::size_t>(slots[static_cast<std::size_t>(j - 1)]);
        const double p0 = P[slot];
        const double a = std::fabs(p0);
        const double e = LS_EPS * ((a == a && a != 0) ? a : 1.0);
        const std::size_t off = N * static_cast<std::size_t>(j);
        for (std::size_t i = 0; i < N; i++) yc[i] = Y[i] + e * Y[off + i];
        P[slot] = p0 + e;
        sys->evaluate_invariant();
        forget_clock();
        bool ok;
        try {
            ok = analytic_evaluate(Jm, *an, t, yc);
        } catch (...) {
            P[slot] = p0;
            sys->evaluate_invariant();
            forget_clock();
            throw;
        }
        P[slot] = p0;
        sys->evaluate_invariant();
        forget_clock();
        if (!ok) {
            std::fill(coupling.begin(), coupling.end(), 0.0);
            return coupling;
        }
        for (std::size_t q = 0; q < nnz; q++) coupling[q] = (Jm[q] - J0[q]) / e;
        for (std::size_t q = 0; q < nnz; q++)
            if (budget_rows[q]) coupling[q] = 0.0;
        // A coupling that is not a number is no coupling: the block is left out.
        bool finite = true;
        for (double c : coupling) finite = finite && std::isfinite(c);
        if (!finite) std::fill(coupling.begin(), coupling.end(), 0.0);
        return coupling;
    }

    /// The big Jacobian's values: J's entries and each coupling's in the states' columns, J's
    /// again down the diagonal.
    bool big_evaluate(Vec& vals, double t, const Vec& Y) {
        std::copy_n(Y.begin(), static_cast<std::size_t>(n), ys.begin());
        if (!analytic_evaluate(J0, *an, t, ys)) return false;
        const std::vector<std::vector<I32>>& at = *state_at;
        for (std::size_t q = 0; q < nnz; q++) vals[static_cast<std::size_t>(at[0][q])] = J0[q];
        for (int j = 1; j <= mm; j++) {
            const Vec& c = coupling_of(t, Y, j);
            const std::vector<I32>& sa = at[static_cast<std::size_t>(j)];
            for (std::size_t q = 0; q < nnz; q++) vals[static_cast<std::size_t>(sa[q])] = c[q];
        }
        const std::size_t blocks = static_cast<std::size_t>(1 + mm);
        for (std::size_t b = 1; b <= static_cast<std::size_t>(mm); b++) std::copy(J0.begin(), J0.end(), vals.begin() + static_cast<std::ptrdiff_t>((blocks + b - 1) * nnz));
        return true;
    }
};

/// The matrix Newton iterates with for [y, S_1, ..., S_m], a block at a time (`blockMatrix` in
/// the application). It is block lower triangular -- A = I - a·J on the diagonal, -a·C_j under
/// the states' block, C_j = d(S_j')/dy -- so the states' block is solved first and each
/// sensitivity's after it, the coupling carried to its right-hand side: one factorisation of
/// A, and never a pivot taken across blocks. An LU of the whole matrix pivots a state's
/// column on a sensitivity's row wherever the coupling is the larger entry, and mixes that
/// row's rounding into the state's correction, which for a state near zero is all of it.
///
/// A state the floor holds is a row of the identity in the states' block, and the
/// sensitivities are held with their states (`held_with`): the same row is the identity in
/// every sensitivity's block, with nothing of the coupling under it, so the one factorisation
/// serves them all. The rows held are read off the states' (`held` up to `n`): the solver marks
/// a sensitivity's with its state's.
class BlockMatrix final : public AbstractIterationMatrix {
public:
    BlockMatrix(const Pattern* base, int n, int m, std::shared_ptr<const std::vector<std::vector<I32>>> state_at, const Vec& values, std::string mode,
                const Hints* hints)
        : n_(n), m_(m), base_(base), state_at_(std::move(state_at)), mode_(std::move(mode)), hints_(hints) {
        const std::size_t nnz = base->nnz();
        J_.assign(nnz, 0.0);
        C_.assign(static_cast<std::size_t>(m), Vec(nnz, 0.0));
        extract(values);
        states_ = std::make_unique<IterationMatrix>(n, base, J_, mode_, nullptr, hints_);
        held_y_.assign(static_cast<std::size_t>(n), 0);
        xy_.assign(static_cast<std::size_t>(n), 0.0);
        rs_.assign(static_cast<std::size_t>(n), 0.0);
        cd_.assign(static_cast<std::size_t>(n), 0.0);
    }

    std::optional<std::string> form(double a, const Vec& J, const std::vector<std::uint8_t>* held) override {
        extract(J);
        a_ = a;
        bool any = false;
        if (held != nullptr) {
            for (int i = 0; i < n_; i++) {
                held_y_[static_cast<std::size_t>(i)] = (*held)[static_cast<std::size_t>(i)];
                if ((*held)[static_cast<std::size_t>(i)] != 0) any = true;
            }
        }
        any_held_ = any;
        return states_->form(a, J_, any ? &held_y_ : nullptr);
    }

    void solve_inplace(Vec& x) override {
        const std::size_t n = static_cast<std::size_t>(n_);
        for (std::size_t i = 0; i < n; i++) xy_[i] = x[i];
        states_->solve_inplace(xy_);
        for (std::size_t i = 0; i < n; i++) x[i] = xy_[i];
        const I32* rows = base_->rowval.data();
        const I32* cols = base_->col_of.data();
        const std::size_t nnz = base_->nnz();
        for (int j = 0; j < m_; j++) {
            // The coupling's part: C_j times the states' correction, column by column.
            std::fill(cd_.begin(), cd_.end(), 0.0);
            const Vec& c = C_[static_cast<std::size_t>(j)];
            for (std::size_t q = 0; q < nnz; q++) cd_[rows[q]] = cd_[rows[q]] + c[q] * xy_[cols[q]];
            const std::size_t off = n * static_cast<std::size_t>(j + 1);
            for (std::size_t i = 0; i < n; i++) rs_[i] = x[off + i] + a_ * cd_[i];
            // ...and none of it on a held row.
            if (any_held_)
                for (std::size_t i = 0; i < n; i++)
                    if (held_y_[i] != 0) rs_[i] = x[off + i];
            states_->solve_inplace(rs_);
            for (std::size_t i = 0; i < n; i++) x[off + i] = rs_[i];
        }
    }

    void release() override { states_->release(); }

    const Json& info() override { return states_->info(); }

private:
    /// J's entries and each coupling's, out of the big values.
    void extract(const Vec& values) {
        const std::vector<std::vector<I32>>& at = *state_at_;
        for (std::size_t q = 0; q < J_.size(); q++) J_[q] = values[static_cast<std::size_t>(at[0][q])];
        for (std::size_t j = 0; j < C_.size(); j++) {
            const std::vector<I32>& sa = at[j + 1];
            Vec& c = C_[j];
            for (std::size_t q = 0; q < c.size(); q++) c[q] = values[static_cast<std::size_t>(sa[q])];
        }
    }

    int n_, m_;
    const Pattern* base_;
    std::shared_ptr<const std::vector<std::vector<I32>>> state_at_;
    std::string mode_;
    const Hints* hints_;
    Vec J_;
    std::vector<Vec> C_;
    std::unique_ptr<IterationMatrix> states_;
    double a_ = 0.0;
    bool any_held_ = false;   // a row held as the matrix was last formed
    std::vector<std::uint8_t> held_y_;
    Vec xy_, rs_, cd_;
};

/// The ways a solve gives up that a noisy driving term brings about.
bool noisy(const std::string& kind) { return kind == "tolerance" || kind == "stalled" || kind == "steps"; }

}  // namespace

double step_for(double p) { return LS_EPS * pd_jmax(std::fabs(p), 1.0); }

std::vector<Json> parameter_slots(const System& sys) {
    std::vector<Json> out;
    const std::unordered_map<std::string, std::string> units = material_units(sys);
    const IndexSpace& space = *sys.builder->space;
    for (const auto& entry : sys.builder->param_layout) {
        const std::vector<std::string>& dims = entry->dims;
        std::vector<Json> described;
        describe_entry(described, sys, *entry, "parameter", "P", units);
        for (int off = 0; off < entry->width; off++) {
            const Tup at_tuple = dims.empty() ? Tup() : tuple_by_list(space, dims, off);
            Json tup = dims.empty() ? Json::object() : js_ordered(at_tuple);
            Json unit = static_cast<std::size_t>(off) < described.size() ? described[static_cast<std::size_t>(off)].get("unit", Json("")) : Json("");
            // Read as the builder reads it: at the scenario that runs.
            const Json at = js_ordered(space.pin_scenario(strings_of(entry->block.get("index_lists")), at_tuple));
            const Json* value = effective_value(entry->block, "value", at);
            out.push_back(Json::object({{"slot", Json(entry->base + off)},
                                        {"name", Json(entry->name)},
                                        {"index", tup},
                                        {"value", Json(pd_to_number(value))},
                                        {"unit", unit.is_null() ? Json("") : unit}}));
        }
    }
    return out;
}

std::string slot_label(const Json& e) {
    const Json& index = e.get("index");
    std::vector<Json> idx;
    if (index.is_object()) {
        const Json ordered = js_ordered(index);
        for (const auto& [k, v] : ordered.obj()) idx.push_back(v);
    }
    const Json& name = e.get("name");
    if (idx.empty()) return name.is_string() ? name.as_string() : pd_js_str(name);
    std::string out = pd_js_str(name) + "[";
    for (std::size_t i = 0; i < idx.size(); i++) {
        if (i) out += "][";
        if (!idx[i].is_null()) out += pd_js_str(idx[i]);
    }
    return out + "]";
}

std::vector<Json> state_series(const System& sys) {
    const std::unordered_map<std::string, std::string> units = material_units(sys);
    std::vector<Json> out;
    for (const auto& s : sys.builder->states) {
        const char* kind = s->kind == "compartment" && !s->hidden ? "compartment"
                           : s->kind == "waste_package"           ? "waste_inventory"
                           : s->kind == "event"                   ? "event"
                                                                  : nullptr;
        if (kind) {
            std::vector<Json> described;
            describe_entry(described, sys, *s, kind, "y", units);
            for (const Json& d : described)
                out.push_back(Json::object({{"offset", d.get("offset")},
                                            {"label", d.get("label")},
                                            {"block", Json(s->name)},
                                            {"kind", Json(kind)},
                                            {"unit", d.get("unit")},
                                            {"hidden", Json(false)}}));
            continue;
        }
        for (int off = 0; off < s->width; off++)
            out.push_back(Json::object({{"offset", Json(s->base + off)},
                                        {"label", Json(s->width > 1 ? s->name + " #" + std::to_string(off) : s->name)},
                                        {"block", Json(s->name)},
                                        {"kind", Json(s->kind)},
                                        {"unit", Json("")},
                                        {"hidden", Json(true)}}));
    }
    return out;
}

std::optional<std::string> uncarried(const Project& project, System& sys, const std::vector<Json>& wanted) {
    const Builder& b = *sys.builder;
    const std::vector<double> grid = project.time_grid();
    auto inside = [&](double at) { return grid.front() < at && at < grid.back(); };
    auto jump = [](const std::string& name, double at) {
        return "'" + name + "' makes the state jump at t=" + pd_js_number_str(at) +
               ", and dy/dp is not carried across a jump: after it, it depends on how the jump moves with the parameters, which the "
               "sensitivity equations do not have.";
    };
    for (const JumpSpec& j : b.jump_specs) {
        if (j.slot) {
            const double at = sys.X[static_cast<std::size_t>(*j.slot)];
            if (inside(at)) return jump(j.name, at);
        } else {
            for (double at : sys.sampled_times[static_cast<std::size_t>(j.index)])
                if (inside(at)) return jump(j.name, at);
        }
    }
    // ...and so does an event a trigger sets off, at a time nobody knows until the crossing is
    // found -- which moves with the parameters too.
    for (const auto& D : b.disruption_layout) {
        if (D->timing != "trigger") continue;
        return "'" + D->q +
               "' makes the state jump whenever its trigger fires, and dy/dp is not carried across a jump: after it, it depends on how the "
               "jump and the crossing move with the parameters, which the sensitivity equations do not have.";
    }
    // A semi-analytical path's release is read by its own held state, always, and it is a
    // convolution over the whole run's inflow.
    for (const auto& p : b.farf_layout) {
        if (!(p->farf && p->farf->laplace)) continue;
        return "'" + (p->local_name ? *p->local_name : p->name) +
               "' is worked out semi-analytically: its release is a convolution over what flowed into it during the run, and dy/dp through a "
               "history is not carried by the sensitivity equations, which see only the present. Work the path out on cells to run a local "
               "sensitivity analysis.";
    }
    for (const auto& a : read_by_derivative(sys)) {
        const EntryPtr& rec = a->recorder;
        if (!rec) continue;
        const bool path_kind = rec->kind == "min_max" || rec->kind == "snapshot" || rec->kind == "delay";
        if (path_kind || (rec->kind == "running_mean" && switched_by_event(sys, *rec)))
            return "'" + (a->local_name ? *a->local_name : a->name) +
                   "' remembers the path of the run, and the model's rates read it: dy/dp through a history is not carried by the sensitivity "
                   "equations, which see only the present.";
    }
    // A parameter that places a corner, found by moving its block's values and asking for the
    // switch times again -- of the project the system was laid out from, whose block is the one
    // moved: in a model with transports that is the builder's own copy, the transports written
    // out, and moving its block left the switch times of the project handed in where they were,
    // so the corner was never seen and dy/dp was integrated across it.
    const Project& built = *b.project;
    const std::vector<double> corners = switch_times(built);
    for (const Json& e : wanted) {
        const long long slot = e.get("slot").as_int();
        const Entry* entry = nullptr;
        for (const auto& p : b.param_layout)
            if (p->base <= slot && slot < p->base + p->width) {
                entry = p.get();
                break;
            }
        if (!entry || entry->block.is_null()) continue;
        const std::vector<double> moved = with_block_moved([&]() { return switch_times(built); }, entry->block);
        if (moved != corners)
            return "'" + slot_label(e) +
                   "' places a corner of the run (a switch time, or when something starts or stops): moving it moves a discontinuity, and "
                   "dy/dp with respect to it is an impulse the sensitivity equations do not have.";
    }
    return std::nullopt;
}

std::unique_ptr<SensitivityProblem> sensitivity_problem(std::shared_ptr<const Project> project, const Json& parameters, const SensitivityOptions& options) {
    auto pr = std::make_unique<SensitivityProblem>();
    pr->project = project;
    auto system = std::make_shared<System>(project);
    pr->system = system;
    System& sys = *system;
    const auto& jac = sys.jacobian;
    if (!(jac && jac->available)) {
        std::optional<std::string> reason;
        if (sys.nstate == 0) reason = "the model has no compartments to differentiate";
        else if (jac) reason = jac->reason;
        throw SensitivityError("This model has no analytic Jacobian, and the sensitivity equations are driven by it. " + (reason ? *reason : std::string()));
    }
    std::unordered_map<std::string, Json> by_label;
    for (const Json& e : parameter_slots(sys)) by_label[slot_label(e)] = e;
    if (parameters.is_string()) throw ArgumentError("parameters is a list of slot labels, not one label");
    std::vector<Json> wanted;
    if (parameters.is_array())
        for (const Json& p : parameters.arr()) {
            if (!p.is_string()) continue;
            auto it = by_label.find(p.as_string());
            if (it != by_label.end()) wanted.push_back(it->second);
        }
    if (wanted.empty()) throw SensitivityError("Name at least one parameter to take the sensitivity to.");
    const Json most = options.most.is_null() ? Json(12) : options.most;
    if (static_cast<double>(wanted.size()) > pd_to_number(most))
        throw SensitivityError(std::to_string(wanted.size()) +
                               " parameters at once: each one adds a copy of the whole state vector to the solve and an evaluation of the derivative "
                               "to every step. Choose at most " +
                               pd_js_str(most) + ".");
    if (std::optional<std::string> refusal = uncarried(*project, sys, wanted)) throw SensitivityError(*refusal);

    const int n = sys.nstate;
    const int mm = static_cast<int>(wanted.size());
    const std::size_t N = static_cast<std::size_t>(n) * static_cast<std::size_t>(1 + mm);
    const std::size_t nn = static_cast<std::size_t>(n);
    std::vector<int> slots;
    for (const Json& e : wanted) slots.push_back(static_cast<int>(e.get("slot").as_int()));
    if (options.differenced) {
        pr->why.available = false;
        pr->why.reason = "asked for the differenced df/dp";
    } else {
        pr->why = param_tangent(sys);
    }
    auto work = std::make_shared<Work>();
    Work& w = *work;
    w.system = system;
    w.sys = &sys;
    w.n = n;
    w.mm = mm;
    w.slots = slots;
    w.plan = pr->why.available ? pr->why.plan : nullptr;
    w.nparam = static_cast<std::size_t>(std::max(1, sys.nparam));
    w.an = jac->analytic;
    w.pattern = &*jac->pattern;
    const Pattern& pattern = *w.pattern;
    const std::size_t nnz = pattern.nnz();
    w.nnz = nnz;
    w.clock_from = py_float_nan(project->simulation.get("start_time"));
    w.J.assign(nnz, 0.0);
    w.f0.assign(nn, 0.0);
    w.fp.assign(nn, 0.0);
    w.jv.assign(nn, 0.0);
    w.yv.assign(nn, 0.0);
    w.sv.assign(nn, 0.0);
    w.moved.assign(nn, 0.0);
    w.yd.assign(nn, 0.0);
    w.seed.assign(w.nparam, 0.0);

    // The iteration matrix: J down the diagonal, (1 + m) times, and under it how each
    // sensitivity's equations move with the state (`bigJacobian` in the application). A
    // state's column holds J's entries and then each sensitivity's under them; the
    // sensitivities' columns follow, J's entries in their own block.
    const std::size_t blocks = static_cast<std::size_t>(1 + mm);
    const std::vector<I32>& rows = pattern.rowval;
    const std::vector<I32>& cols = pattern.col_of;
    const std::vector<I32>& colptr = pattern.colptr;
    auto state_at = std::make_shared<std::vector<std::vector<I32>>>(blocks, std::vector<I32>(nnz, 0));
    for (std::size_t q = 0; q < nnz; q++) {
        const std::size_t c = static_cast<std::size_t>(cols[q]);
        const I32 within = static_cast<I32>(q) - colptr[c];
        const I32 len = colptr[c + 1] - colptr[c];
        for (std::size_t b = 0; b < blocks; b++) (*state_at)[b][q] = static_cast<I32>(blocks) * colptr[c] + static_cast<I32>(b) * len + within;
    }
    std::vector<I32> brows((blocks + static_cast<std::size_t>(mm)) * nnz), bcols((blocks + static_cast<std::size_t>(mm)) * nnz);
    for (std::size_t b = 0; b < blocks; b++)
        for (std::size_t q = 0; q < nnz; q++) {
            const std::size_t at = static_cast<std::size_t>((*state_at)[b][q]);
            brows[at] = rows[q] + static_cast<I32>(b) * n;
            bcols[at] = cols[q];
        }
    for (std::size_t b = 1; b < blocks; b++)
        for (std::size_t q = 0; q < nnz; q++) {
            const std::size_t at = (blocks + b - 1) * nnz + q;
            brows[at] = rows[q] + static_cast<I32>(b) * n;
            bcols[at] = cols[q] + static_cast<I32>(b) * n;
        }
    Pattern big(static_cast<int>(N), brows, bcols);
    if (!(big.rowval == brows && big.col_of == bcols)) throw std::runtime_error("the repeated Jacobian pattern did not keep the order of its blocks");
    // The colouring twice: a state's column reaches the sensitivities' rows as well, so it
    // shares no group with theirs -- the states' groups, then the sensitivities', each across
    // every block.
    std::optional<ColumnGroups> big_groups;
    if (jac->groups && !jac->groups->empty()) {
        ColumnGroups g(jac->groups->begin(), jac->groups->end());
        for (const auto& group : *jac->groups) {
            std::vector<I32> across;
            for (std::size_t b = 1; b < blocks; b++)
                for (I32 c : group) across.push_back(c + static_cast<I32>(b) * n);
            g.push_back(std::move(across));
        }
        big_groups = std::move(g);
    }
    w.budget_rows.assign(nnz, 0);
    if (sys.builder->budget) {
        const int frm = sys.builder->budget->base;
        const int to = sys.builder->budget->base + static_cast<int>(sys.builder->budget->terms.size()) * sys.builder->budget->nfam;
        for (std::size_t q = 0; q < nnz; q++) w.budget_rows[q] = frm <= rows[q] && rows[q] < to;
    }
    // Asked to difference its Jacobian, the model gets that here too: the pattern and its
    // colouring, and no values.
    const bool numeric = project->simulation.get("jacobian") == "numeric";
    w.J0.assign(nnz, 0.0);
    w.Jm.assign(nnz, 0.0);
    w.coupling.assign(nnz, 0.0);
    w.yc.assign(nn, 0.0);
    w.ys.assign(nn, 0.0);
    w.state_at = state_at;
    JacobianEvaluate evaluate;
    if (!numeric) evaluate = [work](Vec& vals, double t, const Vec& Y) { return work->big_evaluate(vals, t, Y); };
    pr->jacobian = JacobianSpec(std::move(big), std::move(big_groups), std::move(evaluate), false, false);

    // Initial conditions, the sensitivities included. dy0/dp: an initial inventory may be an
    // equation over parameters, and where it is not this is exactly zero.
    std::vector<double>& P = sys.P;
    const std::vector<double> y0 = sys.initial_state();
    Vec Y0(N, 0.0);
    std::copy(y0.begin(), y0.end(), Y0.begin());
    for (int j = 1; j <= mm; j++) {
        const std::size_t slot = static_cast<std::size_t>(slots[static_cast<std::size_t>(j - 1)]);
        const double p0 = P[slot];
        const double h = step_for(p0);
        P[slot] = p0 + h;
        sys.evaluate_invariant();
        const std::vector<double> yh = sys.initial_state();
        P[slot] = p0;
        sys.evaluate_invariant();
        for (std::size_t i = 0; i < nn; i++) Y0[nn * static_cast<std::size_t>(j) + i] = (yh[i] - y0[i]) / h;
    }

    // Tolerances: the run's own for the states, over |p| for dy/dp.
    const std::vector<double> base_atol = absolute_tolerance(*project, sys);
    const std::vector<double> per_state = base_atol.empty() ? std::vector<double>(nn, project->simulation.get("abstol").as_double())
                                                            : std::vector<double>(base_atol.begin(), base_atol.begin() + static_cast<std::ptrdiff_t>(nn));
    Vec atol(N, 0.0);
    std::copy(per_state.begin(), per_state.end(), atol.begin());
    // ...and what each sensitivity is weighed against: itself, and its state over |p| as well
    // (`weight_floor` of the NDF), so that it is held to what it means for y -- an elasticity
    // right to rtol -- and one negligible beside its state is not asked for rtol of itself,
    // which the rounding of the terms its equation cancels down to can deny it.
    pr->weight_floor.from.assign(N, -1.0);
    pr->weight_floor.factor.assign(N, 0.0);
    for (int j = 1; j <= mm; j++) {
        const double a = std::fabs(P[static_cast<std::size_t>(slots[static_cast<std::size_t>(j - 1)])]);
        const double scale = (a == a && a != 0) ? a : 1.0;
        for (std::size_t i = 0; i < nn; i++) {
            const std::size_t at = nn * static_cast<std::size_t>(j) + i;
            atol[at] = per_state[i] / scale;
            pr->weight_floor.from[at] = static_cast<double>(i);
            pr->weight_floor.factor[at] = 1 / scale;
        }
    }

    Json chosen = Json::array();
    for (const Json& e : wanted)
        chosen.push(Json::object({{"label", Json(slot_label(e))}, {"name", e.get("name")}, {"index", e.get("index")}, {"value", e.get("value")}}));

    pr->n = n;
    pr->m = mm;
    pr->wanted = std::move(wanted);
    pr->slots = std::move(slots);
    pr->chosen = std::move(chosen);
    pr->tangent = w.plan != nullptr;
    pr->rtol = project->simulation.get("rtol").as_double();
    pr->work = work;
    // The floor the run applies -- each compartment's own -- is on the states and nothing after
    // them: a sensitivity may perfectly well be negative. But each is held with its state
    // (`held_with` of the NDF): while the floor holds a compartment at zero it is zero for every
    // value of the parameter near this one, so its dy/dp is zero -- put there the moment the hold
    // begins, a moment that moves with the parameter, and kept there while it lasts -- and what
    // the compartment feeds takes nothing of it.
    pr->held_with.assign(N, -1.0);
    for (int j = 1; j <= mm; j++)
        for (std::size_t i = 0; i < nn; i++) pr->held_with[nn * static_cast<std::size_t>(j) + i] = static_cast<double>(i);
    Equations& eq = pr->equations;
    eq.dydt = [work](Vec& out, double t, const Vec& Y) { work->dydt(out, t, Y); };
    eq.y0 = std::move(Y0);
    eq.abstol = std::move(atol);
    eq.jacobian = &pr->jacobian;
    eq.solver = "ndf";
    // The clock-only algebra may be interpolated (`min_change_time`), anchored where each
    // stretch of the run starts: the runner says where.
    eq.on_segment = [work](double from, double interval) {
        work->clock_from = from;
        work->clock_interval = interval;
    };
    eq.weight_floor = &pr->weight_floor;
    eq.held_with = &pr->held_with;
    // The matrix Newton iterates with, a block at a time.
    eq.iteration_matrix = [work](int, const Pattern*, const Vec& values, const std::string& mode, const Vec*, const Hints* hints) {
        return std::unique_ptr<AbstractIterationMatrix>(new BlockMatrix(work->pattern, work->n, work->mm, work->state_at, values, mode, hints));
    };
    return pr;
}

SensitivityRun run_sensitivity(std::shared_ptr<const Project> project, const Json& parameters, const SensitivityOptions& options) {
    const double started = now_s();
    std::unique_ptr<SensitivityProblem> pr = sensitivity_problem(project, parameters, options);
    const std::size_t n = static_cast<std::size_t>(pr->n);
    const std::size_t mm = static_cast<std::size_t>(pr->m);
    const std::size_t N = n * (1 + mm);
    RunOptions run;
    run.on_grid = true;
    run.on_progress = options.on_progress;
    run.equations = &pr->equations;
    Results res;
    try {
        res = run_project(pr->project, pr->system, run);
    } catch (const SolverError& e) {
        std::optional<SolverError> said = ls_differenced_failure(e, *pr, options.differenced);
        if (!said) throw;
        throw *said;
    }
    SensitivityRun out;
    out.t = res.t;
    out.y.assign(n, std::vector<double>(res.y.size()));
    out.sens.assign(mm, std::vector<std::vector<double>>(n, std::vector<double>(res.y.size())));
    for (std::size_t r = 0; r < res.y.size(); r++) {
        const Vec& row = res.y[r];
        for (std::size_t i = 0; i < n; i++) out.y[i][r] = row[i];
        for (std::size_t k = 0; k < mm; k++)
            for (std::size_t i = 0; i < n; i++) out.sens[k][i][r] = row[n * (k + 1) + i];
    }
    const Json& nsteps = res.stats.get("nsteps");
    const Json& restarts = res.stats.get("restarts");
    out.stats = Json::object({{"ms", Json(static_cast<long long>(std::nearbyint(1000 * (now_s() - started))))},
                              {"nsteps", nsteps.is_null() ? Json(0) : nsteps},
                              {"states", Json(static_cast<long long>(N))},
                              {"restarts", restarts.is_null() ? Json(0) : restarts},
                              {"compiled", Json(true)}});
    out.chosen = pr->chosen;
    out.series = state_series(*pr->system);
    out.tangent = pr->tangent;
    out.system = pr->system;
    return out;
}

std::optional<SolverError> ls_differenced_failure(const SolverError& e, const SensitivityProblem& pr, bool asked) {
    if (pr.tangent || !noisy(e.kind)) return std::nullopt;
    std::vector<std::string> names;
    for (const Json& c : pr.wanted) names.push_back(slot_label(c));
    std::string listed = names[0];
    if (names.size() > 1) {
        listed.clear();
        for (std::size_t i = 0; i + 1 < names.size(); i++) listed += (i ? ", " : "") + names[i];
        listed += " and " + names.back();
    }
    const std::string why = asked ? "as asked" : "since " + (pr.why.reason ? *pr.why.reason : std::string("null"));
    const double a = std::fabs(pr.system->P[static_cast<std::size_t>(pr.wanted[0].get("slot").as_int())]);
    const Json& abstol = pr.project->simulation.get("abstol");
    const double tol = (pr.project->simulation.has("abstol") ? pd_to_number(abstol) : NaN) / ((a == a && a != 0) ? a : 1.0);
    const std::string where = std::isfinite(e.t) ? " past t=" + pd_js_number_str(e.t) : "";
    SolverError out(e.kind,
                    "The sensitivity equations could not be integrated" + where + ": df/dp along " + listed +
                        " is worked out by a difference, " + why +
                        ", which is right to about eight figures, and what it loses to rounding may be more than dy/dp is held to: the run's "
                        "relative tolerance of the larger of dy/dp and the state over the parameter's value, and no less than the absolute "
                        "tolerance over it, " +
                        js_to_precision(tol, 2) + " for " + names[0] + ". Looser tolerances are the first thing to try.",
                    e.t);
    out.hint = ls_solver_words(e.message);
    return out;
}

std::string ls_solver_words(const std::string& message) {
    std::string m = message;
    const std::size_t held = m.find(" Something is holding a state where it cannot go");
    if (held != std::string::npos) m = m.substr(0, held);
    const std::string prefix = "variableOrder failed: ";
    const std::size_t advice = m.find(". If the model is not stiff, dormandPrince may do better");
    if (m.rfind(prefix, 0) == 0 && advice != std::string::npos) m = m.substr(prefix.size(), advice - prefix.size());
    return m;
}

std::vector<double> elasticity(const std::vector<double>& y, const std::vector<double>& s, const Json& p) {
    const double pv = pd_to_number(p);
    std::vector<double> out(y.size(), NaN);
    for (std::size_t i = 0; i < y.size(); i++) {
        const double yi = y[i];
        const double si = i < s.size() ? s[i] : NaN;
        out[i] = yi == 0 ? NaN : (pv / yi) * si;
    }
    return out;
}

}  // namespace kompartment
