#include "engine/system.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <numeric>

#include "engine/farfield.hpp"
#include "engine/farfield_semi.hpp"
#include "engine/jacobian.hpp"
#include "util/fastmath.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

namespace kompartment {

namespace {

const double NaN = std::numeric_limits<double>::quiet_NaN();

double now_ms() {
    using namespace std::chrono;
    return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
}

bool same_bits(double a, double b) { return std::memcmp(&a, &b, sizeof a) == 0; }

/// Julia's `isequal`: a NaN equals a NaN, and -0 is not 0.
bool is_equal(double a, double b) { return (std::isnan(a) && std::isnan(b)) || same_bits(a, b); }

template <class T>
void append(std::vector<std::int32_t>& to, const std::vector<T>& from) {
    for (auto x : from) to.push_back(static_cast<std::int32_t>(x));
}

}  // namespace

// --- the assembly ------------------------------------------------------------------------------------------

Assembler::Assembler(const Builder& b) {
    n = b.nstate;
    std::vector<int> rows, columns;
    std::vector<double> seq;
    auto entries = [&](const std::vector<int>& r, const std::vector<int>* c, const std::vector<double>& order) {
        std::vector<int> ids(r.size());
        for (std::size_t i = 0; i < r.size(); i++) {
            ids[i] = static_cast<int>(rows.size());
            rows.push_back(r[i]);
            columns.push_back(c ? (*c)[i] : n);
            seq.push_back(order[i]);
        }
        return ids;
    };
    enum class Kind { XSign, XX, Const, Farf, X, Fail, Mean };
    struct Term {
        Kind kind;
        std::vector<int> ids;
        std::vector<int> a, b2, c;   // slots, as each kind reads them
        std::vector<double> f;
        int s = -1;
    };
    std::vector<Term> lin, aff;
    std::vector<int> coef_slots;
    auto ramp = [](double base, std::size_t count, int step = 1, int shift = 0) {
        std::vector<double> o(count);
        for (std::size_t i = 0; i < count; i++) o[i] = base + static_cast<double>(static_cast<long>(i) * step + shift);
        return o;
    };
    double base = 0.0;
    for (const Phase& ph : b.phases) {
        switch (ph.kind) {
            case Phase::Kind::Transfers: {
                std::vector<int> src_of(static_cast<std::size_t>(b.nflux), -1);
                for (std::size_t i = 0; i < b.flux_mbd.size(); i++) src_of[static_cast<std::size_t>(b.flux_mbd[i])] = b.flux_mbd_src[i];
                Term l{Kind::XSign, {}, {}, {}, {}, {}, -1}, a{Kind::XSign, {}, {}, {}, {}, {}, -1};
                std::vector<int> lr, lc, ar;
                std::vector<double> lo, ao;
                for (std::size_t i = 0; i < ph.tgt.size(); i++) {
                    int flux = ph.a[i];
                    int src = src_of[static_cast<std::size_t>(flux)];
                    int rate = b.flux_rate[static_cast<std::size_t>(flux)];
                    double order = base + static_cast<double>(i);
                    if (src >= 0) {
                        lr.push_back(ph.tgt[i]);
                        lc.push_back(src);
                        lo.push_back(order);
                        l.a.push_back(rate);
                        l.f.push_back(ph.f[i]);
                        coef_slots.push_back(rate);
                    } else {
                        ar.push_back(ph.tgt[i]);
                        ao.push_back(order);
                        a.a.push_back(rate);
                        a.f.push_back(ph.f[i]);
                    }
                }
                if (!lr.empty()) {
                    l.ids = entries(lr, &lc, lo);
                    lin.push_back(std::move(l));
                }
                if (!ar.empty()) {
                    a.ids = entries(ar, nullptr, ao);
                    aff.push_back(std::move(a));
                }
                base += static_cast<double>(ph.tgt.size());
                break;
            }
            case Phase::Kind::X: {
                if (!ph.tgt.empty()) {
                    Term a{Kind::X, entries(ph.tgt, nullptr, ramp(base, ph.tgt.size())), ph.a, {}, {}, {}, -1};
                    aff.push_back(std::move(a));
                }
                base += static_cast<double>(ph.tgt.size());
                break;
            }
            case Phase::Kind::Waste: {
                std::size_t kk = ph.tgt.size();
                int wd = ph.c.empty() ? 2 : 3;
                if (kk > 0) {
                    Term l{Kind::XSign, entries(ph.tgt, &ph.tgt, ramp(base, kk, wd)), std::vector<int>(kk, ph.s1), {}, {}, std::vector<double>(kk, -1.0), -1};
                    coef_slots.insert(coef_slots.end(), kk, ph.s1);
                    lin.push_back(std::move(l));
                    Term f{Kind::Fail, entries(ph.a, nullptr, ramp(base, kk, wd, 1)), ph.tgt, ph.b, {}, {}, ph.s1};
                    aff.push_back(std::move(f));
                    if (!ph.c.empty()) {
                        Term x{Kind::X, entries(ph.c, nullptr, ramp(base, kk, wd, 2)), ph.b, {}, {}, {}, -1};
                        aff.push_back(std::move(x));
                    }
                }
                base += static_cast<double>(kk * static_cast<std::size_t>(wd));
                break;
            }
            case Phase::Kind::Move: {
                std::size_t kk = ph.tgt.size();
                int wd = ph.a.empty() ? 1 : 2;
                if (kk > 0) {
                    std::vector<int> ls(kk, ph.s1), ss(kk, ph.s2);
                    Term out{Kind::XX, entries(ph.tgt, &ph.tgt, ramp(base, kk, wd)), ls, ss, {}, std::vector<double>(kk, -1.0), -1};
                    lin.push_back(std::move(out));
                    coef_slots.insert(coef_slots.end(), ls.begin(), ls.end());
                    coef_slots.insert(coef_slots.end(), ss.begin(), ss.end());
                    if (!ph.a.empty()) {
                        Term in{Kind::XX, entries(ph.a, &ph.tgt, ramp(base, kk, wd, 1)), ls, ss, {}, std::vector<double>(kk, 1.0), -1};
                        lin.push_back(std::move(in));
                        coef_slots.insert(coef_slots.end(), ls.begin(), ls.end());
                        coef_slots.insert(coef_slots.end(), ss.begin(), ss.end());
                    }
                }
                base += static_cast<double>(kk * static_cast<std::size_t>(wd));
                break;
            }
            case Phase::Kind::Mean: {
                if (!ph.tgt.empty()) {
                    Term m{Kind::Mean, entries(ph.tgt, nullptr, ramp(base, ph.tgt.size())), ph.a, {}, {}, {}, ph.s1};
                    aff.push_back(std::move(m));
                }
                base += static_cast<double>(ph.tgt.size());
                break;
            }
            case Phase::Kind::Coef: {
                if (!ph.tgt.empty()) {
                    Term c{Kind::Const, entries(ph.tgt, &ph.a, ramp(base, ph.tgt.size())), {}, {}, {}, ph.f, -1};
                    lin.push_back(std::move(c));
                }
                base += static_cast<double>(ph.tgt.size());
                break;
            }
            case Phase::Kind::Farf: {
                const FarfieldPath& F = *b.FARF[static_cast<std::size_t>(ph.s1)];
                auto [rf, cf] = farfield_row_col(F);
                if (!rf.empty()) {
                    Term f{Kind::Farf, entries(rf, &cf, ramp(base, rf.size())), {}, {}, {}, {}, ph.s1};
                    lin.push_back(std::move(f));
                    std::vector<int> slots = farfield_setting_slots(F);
                    coef_slots.insert(coef_slots.end(), slots.begin(), slots.end());
                }
                base += static_cast<double>(rf.size());
                break;
            }
        }
    }
    std::size_t m = rows.size();
    // Rows in order, and within a row the terms in the order they are added.
    std::vector<std::int32_t> order(m);
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](std::int32_t x, std::int32_t y) {
        if (rows[static_cast<std::size_t>(x)] != rows[static_cast<std::size_t>(y)]) return rows[static_cast<std::size_t>(x)] < rows[static_cast<std::size_t>(y)];
        return seq[static_cast<std::size_t>(x)] < seq[static_cast<std::size_t>(y)];
    });
    std::vector<std::int32_t> pos(m);
    for (std::size_t k = 0; k < m; k++) pos[static_cast<std::size_t>(order[k])] = static_cast<std::int32_t>(k);
    rowptr.assign(static_cast<std::size_t>(n) + 1, 0);
    for (int r : rows) rowptr[static_cast<std::size_t>(r) + 1]++;
    for (int i = 0; i < n; i++) rowptr[static_cast<std::size_t>(i) + 1] += rowptr[static_cast<std::size_t>(i)];
    if (m >= static_cast<std::size_t>(std::numeric_limits<std::int32_t>::max()))
        throw BuildError("The derivative has " + std::to_string(m) + " terms, more than this engine can index.");
    cols.resize(m);
    for (std::size_t k = 0; k < m; k++) cols[k] = static_cast<std::int32_t>(columns[static_cast<std::size_t>(order[k])]);
    data.assign(m, 0.0);
    empty = m == 0;
    auto places = [&](const std::vector<int>& ids) {
        std::vector<std::int32_t> p(ids.size());
        for (std::size_t i = 0; i < ids.size(); i++) p[i] = pos[static_cast<std::size_t>(ids[i])];
        return p;
    };
    for (const Term& t : lin) {
        std::vector<std::int32_t> p = places(t.ids);
        switch (t.kind) {
            case Kind::XSign:
                append(lin_xsign_pos, p);
                append(lin_xsign_slot, t.a);
                lin_xsign_sign.insert(lin_xsign_sign.end(), t.f.begin(), t.f.end());
                break;
            case Kind::XX:
                append(lin_xx_pos, p);
                append(lin_xx_a, t.a);
                append(lin_xx_b, t.b2);
                lin_xx_sign.insert(lin_xx_sign.end(), t.f.begin(), t.f.end());
                break;
            case Kind::Const:
                append(lin_const_pos, p);
                lin_const_val.insert(lin_const_val.end(), t.f.begin(), t.f.end());
                break;
            case Kind::Farf: lin_farf.emplace_back(t.s, p); break;
            default: break;
        }
    }
    for (const Term& t : aff) {
        std::vector<std::int32_t> p = places(t.ids);
        switch (t.kind) {
            case Kind::XSign:
                append(aff_xsign_pos, p);
                append(aff_xsign_slot, t.a);
                aff_xsign_sign.insert(aff_xsign_sign.end(), t.f.begin(), t.f.end());
                break;
            case Kind::X:
                append(aff_x_pos, p);
                append(aff_x_slot, t.a);
                break;
            case Kind::Fail:
                append(aff_fail_pos, p);
                aff_fail_h.insert(aff_fail_h.end(), p.size(), t.s);
                append(aff_fail_p, t.a);
                append(aff_fail_r, t.b2);
                break;
            case Kind::Mean:
                append(aff_mean_pos, p);
                append(aff_mean_slot, t.a);
                for (std::size_t i = 0; i < t.a.size(); i++) aff_mean_mem.push_back(t.s + static_cast<std::int32_t>(i));
                break;
            default: break;
        }
    }
    moves = 0;
    for (int s : coef_slots) moves = std::max(moves, static_cast<int>(b.slot_class[static_cast<std::size_t>(s)]));
    // The coefficients read from a slot that moves with the state last, in their order: only
    // they are written again on a call that finds the clock where it was.
    std::vector<std::size_t> slow, fast;
    for (std::size_t i = 0; i < lin_xsign_slot.size(); i++)
        (b.slot_class[static_cast<std::size_t>(lin_xsign_slot[i])] == 2 ? fast : slow).push_back(i);
    if (!fast.empty()) {
        std::vector<std::size_t> o = slow;
        o.insert(o.end(), fast.begin(), fast.end());
        std::vector<std::int32_t> np(o.size()), ns(o.size());
        std::vector<double> ng(o.size());
        for (std::size_t i = 0; i < o.size(); i++) {
            np[i] = lin_xsign_pos[o[i]];
            ns[i] = lin_xsign_slot[o[i]];
            ng[i] = lin_xsign_sign[o[i]];
        }
        lin_xsign_pos = std::move(np);
        lin_xsign_slot = std::move(ns);
        lin_xsign_sign = std::move(ng);
    }
    lin_fast_from = slow.size();
    if (parity()) return;

    // The terms merged into one entry per state and column, with where each entry's value
    // comes from.
    auto M = std::make_shared<MergedMatrix>();
    const auto& cls = b.slot_class;
    // The entry each linear term adds into: terms are in row order, so a row's entries are
    // found together, each column's first term in the row making its entry. -1: the constant column.
    std::vector<std::int32_t> term_entry(m, -1);
    M->rowptr.assign(static_cast<std::size_t>(n) + 1, 0);
    std::vector<std::int32_t> seen_row(static_cast<std::size_t>(n), -1), seen_entry(static_cast<std::size_t>(n), 0);
    M->aff_ptr.push_back(0);
    for (int i = 0; i < n; i++) {
        bool affine = false;
        for (std::int32_t k = rowptr[static_cast<std::size_t>(i)]; k < rowptr[static_cast<std::size_t>(i) + 1]; k++) {
            std::int32_t c = cols[static_cast<std::size_t>(k)];
            if (c >= n) {
                M->aff_pos.push_back(k);
                affine = true;
                continue;
            }
            if (seen_row[static_cast<std::size_t>(c)] == i) {
                term_entry[static_cast<std::size_t>(k)] = seen_entry[static_cast<std::size_t>(c)];
            } else {
                M->cols.push_back(c);
                std::int32_t j = static_cast<std::int32_t>(M->cols.size()) - 1;
                seen_row[static_cast<std::size_t>(c)] = i;
                seen_entry[static_cast<std::size_t>(c)] = j;
                term_entry[static_cast<std::size_t>(k)] = j;
            }
        }
        M->rowptr[static_cast<std::size_t>(i) + 1] = static_cast<std::int32_t>(M->cols.size());
        if (affine) {
            M->aff_rows.push_back(i);
            M->aff_ptr.push_back(static_cast<std::int32_t>(M->aff_pos.size()));
        }
    }
    std::size_t nm = M->cols.size();
    // Each entry's sources, grouped by entry. A linear source whose term lands in the constant
    // column is the constant column's: its value goes into the terms, and from them into b.
    std::vector<std::int32_t> count_src(nm, 0);
    for (std::size_t q = 0; q < lin_xsign_pos.size(); q++) {
        std::int32_t j = term_entry[static_cast<std::size_t>(lin_xsign_pos[q])];
        if (j < 0) M->aff_src.push_back(static_cast<std::int32_t>(q));
        else count_src[static_cast<std::size_t>(j)]++;
    }
    M->src_ptr.assign(nm + 1, 0);
    for (std::size_t j = 0; j < nm; j++) M->src_ptr[j + 1] = M->src_ptr[j] + count_src[j];
    std::vector<std::int32_t> next(M->src_ptr.begin(), M->src_ptr.end() - 1);
    M->src_slot.resize(static_cast<std::size_t>(M->src_ptr[nm]));
    M->src_sign.resize(static_cast<std::size_t>(M->src_ptr[nm]));
    std::vector<char> fast_entry(nm, 0);
    for (std::size_t q = 0; q < lin_xsign_pos.size(); q++) {
        std::int32_t j = term_entry[static_cast<std::size_t>(lin_xsign_pos[q])];
        if (j < 0) continue;
        std::size_t at = static_cast<std::size_t>(next[static_cast<std::size_t>(j)]++);
        M->src_slot[at] = lin_xsign_slot[q];
        M->src_sign[at] = lin_xsign_sign[q];
        if (cls[static_cast<std::size_t>(lin_xsign_slot[q])] == 2) fast_entry[static_cast<std::size_t>(j)] = 1;
    }
    M->konst.assign(nm, 0.0);
    for (std::size_t q = 0; q < lin_const_pos.size(); q++) {
        std::int32_t k = lin_const_pos[q];
        std::int32_t j = term_entry[static_cast<std::size_t>(k)];
        // A constant in the constant column is a term written once.
        if (j < 0) data[static_cast<std::size_t>(k)] = lin_const_val[q];
        else M->konst[static_cast<std::size_t>(j)] += lin_const_val[q];
    }
    std::vector<char> extra_moves;
    for (std::size_t q = 0; q < lin_xx_pos.size(); q++) {
        std::int32_t k = lin_xx_pos[q];
        if (term_entry[static_cast<std::size_t>(k)] < 0) continue;   // written into the terms, summed into b
        M->extra_pos.push_back(k);
        M->extra_dest.push_back(term_entry[static_cast<std::size_t>(k)]);
        extra_moves.push_back(std::max(cls[static_cast<std::size_t>(lin_xx_a[q])], cls[static_cast<std::size_t>(lin_xx_b[q])]) == 2);
    }
    for (const auto& [path, positions] : lin_farf)
        for (std::int32_t k : positions) {
            if (term_entry[static_cast<std::size_t>(k)] < 0) continue;
            M->extra_pos.push_back(k);
            M->extra_dest.push_back(term_entry[static_cast<std::size_t>(k)]);
            extra_moves.push_back(moves == 2);
        }
    for (std::size_t e = 0; e < extra_moves.size(); e++)
        if (extra_moves[e]) fast_entry[static_cast<std::size_t>(M->extra_dest[e])] = 1;
    for (std::size_t j = 0; j < nm; j++)
        if (fast_entry[j]) M->fast.push_back(static_cast<std::int32_t>(j));
    for (std::size_t e = 0; e < M->extra_dest.size(); e++)
        if (fast_entry[static_cast<std::size_t>(M->extra_dest[e])]) M->extra_fast.push_back(static_cast<std::int32_t>(e));
    M->vals.assign(nm, 0.0);
    M->b.assign(static_cast<std::size_t>(n), 0.0);
    merged = M;
}

// --- the system --------------------------------------------------------------------------------------------

System::System(std::shared_ptr<const Project> project_, bool with_jacobian) : project(std::move(project_)) {
    double t0 = now_ms();
    builder = std::make_shared<Builder>(project);
    double built = now_ms();
    const Builder& b = *builder;
    nstate = b.nstate;
    nalg = b.nalg;
    nparam = b.nparam;
    P = b.P;
    X.assign(static_cast<std::size_t>(std::max(1, nalg)), 0.0);
    data.TAB = b.TAB;
    data.MEM = b.MEM;
    data.DIS.assign(std::max<std::size_t>(1, b.disruption_layout.size()), 1.0);
    data.T0 = project->simulation.get("start_time").as_double();
    data.T1 = project->simulation.get("end_time").as_double();
    data.FARF = b.FARF;
    start_time = data.T0;
    end_time = data.T1;
    auto ps = std::make_shared<Passes>();
    ps->invariant = Program(merge_statements(b.pass_stmts[0]));
    ps->at_instant = Program(merge_statements(b.pass_stmts[1]));
    ps->moving = Program(merge_statements(b.pass_stmts[2]));
    {
        std::vector<std::shared_ptr<Stmt>> initial = merge_statements(b.initial_before);
        for (auto& s : merge_statements(b.initial_stmts)) initial.push_back(s);
        ps->initial = Program(initial);
    }
    ps->has_derivative = b.has_derivative_stmts;
    if (b.has_derivative_stmts) ps->moving_derivative = Program(merge_statements(b.derivative_stmts));
    passes = ps;
    double compiled = now_ms();
    assembler = Assembler(b);
    for (int i = 0; i < nalg; i++)
        if (b.slot_class[static_cast<std::size_t>(i)] == 1) clock_idx.push_back(i);
    lo_x.assign(clock_idx.size(), 0.0);
    hi_x.assign(clock_idx.size(), 0.0);
    origin = data.T0;
    lo_t = hi_t = clock_at = NaN;
    for (const auto& r : b.recorders)
        if (r->mem >= 0) remembering.push_back(r);
    for (std::size_t k = 0; k < data.FARF.size(); k++)
        if (data.FARF[k]->laplace) laplace.push_back(static_cast<int>(k));
    for (const auto& e : b.event_slots) event_slots.push_back(e.slot);
    sampled_times.assign(b.disruption_layout.size(), {});
    compile_ms = compiled - built;
    build_ms = built - t0;
    evaluate_invariant();
    if (!laplace.empty()) semi_refusals(b, X);
    if (!with_jacobian) {
        jacobian = std::make_shared<JacobianInfo>();
        jacobian->reason = "not asked for";
    } else if (nstate == 0) {
        jacobian = std::make_shared<JacobianInfo>();
        jacobian->reason = "the model has no compartments to differentiate";
    } else {
        jacobian = build_jacobian(*this);
    }
}

void System::run(const Program& pass, double t, const double* y) {
    EvalContext ctx{t, const_cast<double*>(y), X.data(), P.data(), &data};
    pass.run(ctx, work_);
}

void System::refresh_tables() {
    for (const auto& pt : builder->point_layout) {
        if (pt->tab < 0 || pt->row < 0) continue;
        LookupTable& table = *data.TAB[static_cast<std::size_t>(pt->tab)];
        if (pt->row < table.n) table.set_y(pt->row, P[static_cast<std::size_t>(pt->slot)]);
    }
}

void System::evaluate_invariant() {
    refresh_tables();
    scratch_y_.assign(static_cast<std::size_t>(std::max(1, nstate)), 0.0);
    run(passes->invariant, start_time, scratch_y_.data());
    clock_at = NaN;
    invariant_version++;
}

void System::use_clock_interpolation(double interval, std::optional<double> from) {
    min_change = std::isfinite(interval) && interval > 0 ? interval : 0.0;
    origin = (from && std::isfinite(*from)) ? *from : start_time;
    lo_t = hi_t = clock_at = NaN;
    // A segment's start reads the clock afresh: the coefficients are worked out again.
    assembler.keyed = false;
}

void System::clock_into(double t, const double* y, std::vector<double>& into) {
    run(passes->at_instant, t, y);
    for (std::size_t k = 0; k < clock_idx.size(); k++) into[k] = X[static_cast<std::size_t>(clock_idx[k])];
}

void System::at_instant(double t, const double* y) {
    if (same_bits(t, clock_at) || t == clock_at) return;
    if (min_change > 0 && !clock_idx.empty()) {
        double k = std::floor((t - origin) / min_change);
        double a = origin + k * min_change;
        double b = a + min_change;
        if (a != lo_t) {
            if (a == hi_t) lo_x = hi_x;
            else clock_into(a, y, lo_x);
            lo_t = a;
        }
        if (b != hi_t) {
            clock_into(b, y, hi_x);
            hi_t = b;
        }
        double wgt = (t - a) / min_change;
        for (std::size_t j = 0; j < clock_idx.size(); j++)
            X[static_cast<std::size_t>(clock_idx[j])] = lo_x[j] + wgt * (hi_x[j] - lo_x[j]);
        clock_at = t;
        return;
    }
    run(passes->at_instant, t, y);
    clock_at = t;
}

const std::vector<double>& System::evaluate_algebraic(double t, const double* y) {
    at_instant(t, y);
    run(passes->moving, t, y);
    return X;
}

void System::evaluate_for_derivative(double t, const double* y) {
    at_instant(t, y);
    run(passes->has_derivative ? passes->moving_derivative : passes->moving, t, y);
}

void System::rhs(double* dy, double t, const double* y) {
    at_instant(t, y);
    run(passes->has_derivative ? passes->moving_derivative : passes->moving, t, y);
    assemble(dy, y);
}

std::vector<double> System::dydt(double t, const std::vector<double>& y) {
    std::vector<double> dy(static_cast<std::size_t>(nstate), 0.0);
    rhs(dy.data(), t, y.data());
    return dy;
}

std::vector<double> System::initial_state() {
    std::vector<double> y0(static_cast<std::size_t>(std::max(nstate, 1)), 0.0);
    run(passes->initial, start_time, y0.data());
    y0.resize(static_cast<std::size_t>(nstate));
    return y0;
}

// --- the derivative's coefficients and rows ----------------------------------------------------------------

void System::set_fast() {
    Assembler& A = assembler;
    double* d = A.data.data();
    const double* x = X.data();
    for (std::size_t i = A.lin_fast_from; i < A.lin_xsign_pos.size(); i++) d[A.lin_xsign_pos[i]] = x[A.lin_xsign_slot[i]] * A.lin_xsign_sign[i];
    for (std::size_t i = 0; i < A.lin_xx_pos.size(); i++) d[A.lin_xx_pos[i]] = x[A.lin_xx_a[i]] * x[A.lin_xx_b[i]] * A.lin_xx_sign[i];
    set_farfield();
}

// The far-field paths' own terms: each path's rates, worked out again where its settings moved.
void System::set_farfield() {
    Assembler& A = assembler;
    double* d = A.data.data();
    for (const auto& [k, p] : A.lin_farf) {
        FarfieldPath& F = *data.FARF[static_cast<std::size_t>(k)];
        F.refresh(X.data());
        const double* vals = F.values().data();
        for (std::size_t i = 0; i < p.size(); i++) d[p[i]] = vals[i];
    }
}

void System::set_linear() {
    Assembler& A = assembler;
    double* d = A.data.data();
    const double* x = X.data();
    if (!A.consts_written) {
        for (std::size_t i = 0; i < A.lin_const_pos.size(); i++) d[A.lin_const_pos[i]] = A.lin_const_val[i];
        A.consts_written = true;
    }
    for (std::size_t i = 0; i < A.lin_fast_from; i++) d[A.lin_xsign_pos[i]] = x[A.lin_xsign_slot[i]] * A.lin_xsign_sign[i];
    set_fast();
}

void System::set_affine(const double* y) {
    Assembler& A = assembler;
    double* d = A.data.data();
    const double* x = X.data();
    for (std::size_t i = 0; i < A.aff_xsign_pos.size(); i++) d[A.aff_xsign_pos[i]] = x[A.aff_xsign_slot[i]] * A.aff_xsign_sign[i];
    for (std::size_t i = 0; i < A.aff_x_pos.size(); i++) d[A.aff_x_pos[i]] = x[A.aff_x_slot[i]];
    for (std::size_t i = 0; i < A.aff_fail_pos.size(); i++) d[A.aff_fail_pos[i]] = x[A.aff_fail_h[i]] * y[A.aff_fail_p[i]] - x[A.aff_fail_r[i]];
    for (std::size_t i = 0; i < A.aff_mean_pos.size(); i++)
        d[A.aff_mean_pos[i]] = data.MEM[static_cast<std::size_t>(A.aff_mean_mem[i])].recording ? x[A.aff_mean_slot[i]] : 0.0;
}

void System::set_extras() {
    Assembler& A = assembler;
    double* d = A.data.data();
    const double* x = X.data();
    for (std::size_t i = 0; i < A.lin_xx_pos.size(); i++) d[A.lin_xx_pos[i]] = x[A.lin_xx_a[i]] * x[A.lin_xx_b[i]] * A.lin_xx_sign[i];
    set_farfield();
}

void System::refresh_linear() {
    Assembler& A = assembler;
    if (A.keyed && A.key_version == invariant_version && (A.moves == 0 || same_bits(A.key_clock, clock_at))) {
        if (A.moves == 2) set_fast();
        return;
    }
    set_linear();
    A.key_version = invariant_version;
    A.key_clock = clock_at;
    A.keyed = true;
}

namespace {
// The merged entries from their sources: the constant part, then each slot read.
inline void gather(MergedMatrix& M, const double* x, std::size_t j) {
    double acc = M.konst[j];
    for (std::int32_t q = M.src_ptr[j]; q < M.src_ptr[j + 1]; q++) acc = muladd(x[M.src_slot[static_cast<std::size_t>(q)]], M.src_sign[static_cast<std::size_t>(q)], acc);
    M.vals[j] = acc;
}
}  // namespace

void System::refresh_merged(MergedMatrix& M) {
    Assembler& A = assembler;
    const double* x = X.data();
    const double* d = A.data.data();
    bool extras = !(A.lin_xx_pos.empty() && A.lin_farf.empty());
    if (A.keyed && A.key_version == invariant_version && (A.moves == 0 || same_bits(A.key_clock, clock_at))) {
        if (A.moves != 2) return;
        // (the product and far-field terms written whole: some may be in the constant column)
        if (extras) set_extras();
        for (std::int32_t j : M.fast) gather(M, x, static_cast<std::size_t>(j));
        for (std::int32_t e : M.extra_fast) M.vals[static_cast<std::size_t>(M.extra_dest[static_cast<std::size_t>(e)])] += d[M.extra_pos[static_cast<std::size_t>(e)]];
        return;
    }
    if (extras) set_extras();
    for (std::size_t j = 0; j < M.vals.size(); j++) gather(M, x, j);
    for (std::size_t e = 0; e < M.extra_pos.size(); e++) M.vals[static_cast<std::size_t>(M.extra_dest[e])] += d[M.extra_pos[e]];
    A.key_version = invariant_version;
    A.key_clock = clock_at;
    A.keyed = true;
}

void System::assemble(double* dy, const double* y) {
    Assembler& A = assembler;
    int n = A.n;
    if (A.empty) {
        std::fill(dy, dy + n, 0.0);
        return;
    }
    if (A.merged) {
        MergedMatrix& M = *A.merged;
        refresh_merged(M);
        set_affine(y);
        double* d = A.data.data();
        const double* x = X.data();
        for (std::int32_t q : M.aff_src) d[A.lin_xsign_pos[static_cast<std::size_t>(q)]] = x[A.lin_xsign_slot[static_cast<std::size_t>(q)]] * A.lin_xsign_sign[static_cast<std::size_t>(q)];
        // The constant column, row by row, from the affine terms' values.
        for (std::size_t q = 0; q < M.aff_rows.size(); q++) {
            double acc = 0.0;
            for (std::int32_t p = M.aff_ptr[q]; p < M.aff_ptr[q + 1]; p++) acc += d[M.aff_pos[static_cast<std::size_t>(p)]];
            M.b[static_cast<std::size_t>(M.aff_rows[q])] = acc;
        }
        const std::int32_t* rp = M.rowptr.data();
        const std::int32_t* cl = M.cols.data();
        const double* vals = M.vals.data();
        const double* bb = M.b.data();
        for (int i = 0; i < n; i++) {
            double acc = bb[i];
            for (std::int32_t jj = rp[i]; jj < rp[i + 1]; jj++) acc = muladd(vals[jj], y[cl[jj]], acc);
            dy[i] = acc;
        }
        return;
    }
    refresh_linear();
    set_affine(y);
    // The derivative's rows summed: each product rounded, then added in order.
    const std::int32_t* rp = A.rowptr.data();
    const std::int32_t* cl = A.cols.data();
    const double* d = A.data.data();
    for (int i = 0; i < n; i++) {
        double acc = 0.0;
        for (std::int32_t jj = rp[i]; jj < rp[i + 1]; jj++) {
            std::int32_t c = cl[jj];
            acc += d[jj] * (c < n ? y[c] : 1.0);
        }
        dy[i] = acc;
    }
}

// --- recorders, events and jumps ---------------------------------------------------------------------------

void System::prime_recorders(double t0, const std::vector<double>& y0) {
    if (remembering.empty() && laplace.empty()) return;
    for (Recorder& r : data.MEM) r.prime(t0, 0.0);
    // A seed may read another block that remembers -- the peak of a dose worked out from a
    // delayed volume -- and the pass that works it out reads that block's history before it
    // has one: the seeds are worked out again with the histories primed, until none of them
    // moves (the application's `primeRecorders`).
    evaluate_algebraic(t0, y0.data());
    std::vector<double> seeds;
    for (std::size_t sweep = 0; sweep <= remembering.size(); sweep++) {
        bool moved = false;
        std::size_t i = 0;
        for (const auto& rec : remembering) {
            const EntryPtr& seed = rec->kind == "snapshot" ? rec->aux_at("initial") : rec->aux_at("target");
            for (int off = 0; off < rec->width; off++, i++) {
                double v = X[static_cast<std::size_t>(seed->base + off)];
                if (sweep > 0 && is_equal(seeds[i], v)) continue;
                if (sweep == 0) seeds.push_back(v);
                else seeds[i] = v;
                data.MEM[static_cast<std::size_t>(rec->mem + off)].prime(t0, v);
                moved = true;
            }
        }
        if (!moved) break;
        evaluate_algebraic(t0, y0.data());
    }
    for (int k : laplace) static_cast<LaplaceFarfPath&>(*data.FARF[static_cast<std::size_t>(k)]).prime(t0, y0.data(), X.data());
}

void System::store_step(double t, const double* y) {
    if (remembering.empty() && laplace.empty()) return;
    evaluate_algebraic(t, y);
    for (const auto& rec : remembering) {
        const EntryPtr& from = rec->kind == "delay" ? rec->aux_at("target") : rec->entry;
        for (int off = 0; off < rec->width; off++)
            data.MEM[static_cast<std::size_t>(rec->mem + off)].store(t, X[static_cast<std::size_t>(from->base + off)]);
    }
    for (int k : laplace) static_cast<LaplaceFarfPath&>(*data.FARF[static_cast<std::size_t>(k)]).store(t, y, X.data());
}

void System::start_segment(double t, const double* y) {
    if (laplace.empty()) return;
    evaluate_algebraic(t, y);
    for (int k : laplace) static_cast<LaplaceFarfPath&>(*data.FARF[static_cast<std::size_t>(k)]).store(t, y, X.data());
}

void System::event_values(double* out, double t, const double* y) {
    evaluate_algebraic(t, y);
    for (std::size_t k = 0; k < event_slots.size(); k++) out[k] = X[static_cast<std::size_t>(event_slots[k])];
}

void System::fire_events(const std::vector<int>& which, double t, const double* y) {
    evaluate_algebraic(t, y);
    for (int i : which) {
        auto hs = builder->event_handlers.find(i);
        if (hs == builder->event_handlers.end()) continue;
        for (const EventHandler& h : hs->second) {
            const EntryPtr& rec = h.rec;
            double summed = rec->state ? y[rec->state->base + h.off] : 0.0;
            data.MEM[static_cast<std::size_t>(rec->mem + h.off)].fire(h.action, t, X[static_cast<std::size_t>(rec->aux_at("target")->base + h.off)], summed);
        }
    }
}

std::optional<std::pair<std::vector<double>, int>> System::jumps_at_crossing(const std::vector<int>& which, const std::vector<double>& y) {
    std::optional<std::pair<std::vector<double>, int>> out;
    for (const JumpSpec& j : builder->jump_specs) {
        if (j.fired_by.empty()) continue;
        bool any = false;
        for (int i : which)
            if (std::find(j.fired_by.begin(), j.fired_by.end(), i) != j.fired_by.end()) any = true;
        if (!any) continue;
        if (!out) out.emplace(y, 0);
        apply_jump(out->first, j);
        out->second++;
    }
    return out;
}

void System::set_disruption(int index, bool sampled, std::vector<double> times) {
    if (index < 0 || static_cast<std::size_t>(index) >= builder->disruption_layout.size()) return;
    data.DIS[static_cast<std::size_t>(index)] = sampled ? 0.0 : 1.0;
    if (sampled) std::sort(times.begin(), times.end());
    else times.clear();
    sampled_times[static_cast<std::size_t>(index)] = std::move(times);
    clock_at = NaN;
}

void System::apply_jump(std::vector<double>& y, const JumpSpec& spec) const {
    const double* x = X.data();
    for (const JumpOp& op : spec.ops) {
        if (op.kind == JumpOp::Kind::Count) {
            y[static_cast<std::size_t>(op.slot)] += 1;
        } else if (op.kind == JumpOp::Kind::Fail) {
            double share = op.share_slot < 0 ? 1.0 : x[op.share_slot];
            std::size_t n = op.intact.size();
            std::vector<double> fail(n), irf(n);
            for (std::size_t i = 0; i < n; i++) {
                fail[i] = share * y[static_cast<std::size_t>(op.intact[i])];
                irf[i] = x[op.irf[i]];
            }
            for (std::size_t i = 0; i < n; i++) y[static_cast<std::size_t>(op.intact[i])] -= fail[i];
            for (std::size_t i = 0; i < n; i++) y[static_cast<std::size_t>(op.exposed[i])] += fail[i] * (1 - irf[i]);
            for (std::size_t i = 0; i < op.to.size(); i++) y[static_cast<std::size_t>(op.to[i])] += fail[i] * irf[i];
            for (std::size_t i = 0; i < op.budget.size(); i++) y[static_cast<std::size_t>(op.budget[i])] += fail[i] * irf[i];
        } else {
            double share = x[op.share_slot];
            std::size_t n = op.from.size();
            std::vector<double> m(n);
            for (std::size_t i = 0; i < n; i++) m[i] = share * y[static_cast<std::size_t>(op.from[i])];
            for (std::size_t i = 0; i < n; i++) y[static_cast<std::size_t>(op.from[i])] -= m[i];
            if (!op.to.empty()) {
                for (std::size_t i = 0; i < n; i++) y[static_cast<std::size_t>(op.to[i])] += m[i];
            } else {
                for (std::size_t i = 0; i < op.budget.size(); i++) y[static_cast<std::size_t>(op.budget[i])] += m[i];
            }
        }
    }
}

std::optional<std::vector<double>> System::table_corners(double from, double to, double limit) const {
    double lo = std::min(from, to), hi = std::max(from, to);
    std::vector<double> found;
    for (const auto& lk : builder->lookup_layout) {
        if (lk->argument) continue;
        const Json& rule = lk->block.get("interpolation");
        for (int k = lk->tab; k < lk->tab + lk->width; k++) {
            if (static_cast<std::size_t>(k) >= data.TAB.size()) continue;
            const LookupTable& table = *data.TAB[static_cast<std::size_t>(k)];
            const std::vector<double>& x = table.x;
            if (x.size() < 2) continue;
            std::vector<double> at;
            if (rule == "nearest") {
                for (std::size_t i = 0; i + 1 < x.size(); i++) at.push_back((x[i] + x[i + 1]) / 2);
            } else {
                at = x;
            }
            if (!table.cyclic) {
                for (double c : at)
                    if (lo < c && c < hi) found.push_back(c);
                continue;
            }
            double period = x.back() - x.front();
            if (!(period > 0)) continue;
            double first = std::floor((lo - x.front()) / period);
            double last = std::ceil((hi - x.front()) / period);
            if ((last - first) * static_cast<double>(at.size() - 1) > limit) return std::nullopt;
            for (double p = first; p <= last; p += 1.0)
                for (double c : at) {
                    double t = c + p * period;
                    if (lo < t && t < hi) found.push_back(t);
                }
        }
    }
    std::sort(found.begin(), found.end());
    std::vector<double> out;
    for (double t : found) {
        double prev = out.empty() ? -std::numeric_limits<double>::infinity() : out.back();
        if (t - prev <= 1e-9 * std::max(1.0, std::fabs(t))) continue;
        out.push_back(t);
        if (static_cast<double>(out.size()) > limit) return std::nullopt;
    }
    return out;
}

std::vector<std::shared_ptr<LookupTable>> System::clock_tables() const {
    std::vector<std::shared_ptr<LookupTable>> tables;
    for (const auto& lk : builder->lookup_layout) {
        if (lk->argument) continue;
        for (int k = lk->tab; k < lk->tab + lk->width; k++) {
            if (static_cast<std::size_t>(k) >= data.TAB.size()) continue;
            const auto& table = data.TAB[static_cast<std::size_t>(k)];
            if (table->cyclic || std::find(tables.begin(), tables.end(), table) != tables.end()) continue;
            tables.push_back(table);
        }
    }
    return tables;
}

System System::clone() const {
    System c = *this;
    // The tables with points drawn again are this copy's own; what they share stays shared.
    std::vector<std::pair<const LookupTable*, std::shared_ptr<LookupTable>>> copied;
    for (auto& t : c.data.TAB) {
        std::shared_ptr<LookupTable> mine;
        for (const auto& [was, now] : copied)
            if (was == t.get()) mine = now;
        if (!mine) {
            mine = std::make_shared<LookupTable>(*t);
            copied.emplace_back(t.get(), mine);
        }
        t = mine;
    }
    // The far-field paths: what a run changes of each is this copy's own.
    for (auto& F : c.data.FARF) F = F->clone();
    if (assembler.merged) c.assembler.merged = std::make_shared<MergedMatrix>(*assembler.merged);
    c.assembler.keyed = false;
    c.lo_t = c.hi_t = c.clock_at = NaN;
    c.jacobian = clone_jacobian(jacobian, c);
    return c;
}

}  // namespace kompartment
