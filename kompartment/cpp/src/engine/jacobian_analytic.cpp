// df/dy's values, assembled analytically (engine/jacobian.jl from its tangents on;
// engine/analytic.py).
//
// Most of the Jacobian is direct (a transfer's rate, decay), and the rest comes
// through the slots that read the state by the chain rule, each slot's gradient
// a sparse row worked out in dependency order by forward-mode tangents of its
// statements -- the application's rules (`TANGENT_RULES` in
// src/parser/compile.js), term for term in the Python engine's order, so the
// values are its to the last bit. The order of every sum and product below is
// therefore part of the result: nothing here is rearranged, and nothing fused.

#include "engine/jacobian_analytic.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_set>
#include <utility>

#include "engine/farfield.hpp"
#include "engine/farfield_domain.hpp"
#include "engine/farfield_semi.hpp"
#include "engine/lookup.hpp"
#include "engine/tree.hpp"
#include "lang/functions.hpp"
#include "model/names.hpp"

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
constexpr double LN10 = 0x1.26bb1bbb55516p+1;   // log(10)
constexpr double TWO_OVER_SQRT_PI = 1.1283791670955126;

using Tables = std::vector<std::shared_ptr<LookupTable>>;

// --- tangents ------------------------------------------------------------------------------------------

/// A tangent, or none: an expression the seeded leaf does not reach has none, which is not
/// the same as a tangent of zero (a NaN times none is still none).
struct MaybeF {
    double v;
    bool some;
};
constexpr MaybeF NONE{0.0, false};
inline MaybeF some(double v) { return MaybeF{v, true}; }

inline MaybeF tmul(double a, MaybeF d) { return d.some ? some(a * d.v) : NONE; }
inline MaybeF tadd(MaybeF a, MaybeF b) {
    if (!a.some) return b;
    if (!b.some) return a;
    return some(a.v + b.v);
}
inline double z(MaybeF d) { return d.some ? d.v : 0.0; }

/// Zero where every live argument tangent is zero: a column the expression does not reach gets 0.
inline MaybeF zero_seed_guard(const MaybeF* dA, std::size_t n, MaybeF tangent) {
    if (!tangent.some) return NONE;
    bool any = false, all_zero = true;
    for (std::size_t i = 0; i < n; i++) {
        if (!dA[i].some) continue;
        any = true;
        if (!(dA[i].v == 0)) all_zero = false;
    }
    if (!any) return tangent;
    if (all_zero) return some(0.0);
    return tangent;
}

/// What is known of a power before any number is: a constant exponent, and whether the
/// exponent is one number for every element (numpy's short cut in its pow).
struct PowerShape {
    bool has_exponent = false;
    double exponent = 0;
    bool b_one = true;
};

PowerShape power_shape(const TNode& exponent) {
    PowerShape s;
    std::optional<double> k = fold_value(exponent);
    s.has_exponent = k.has_value();
    s.exponent = k.value_or(0.0);
    s.b_one = scalar_subtree(exponent);
    return s;
}

/// The power rule.
inline MaybeF power_rule(double a, double b, MaybeF da, MaybeF db, double V, const PowerShape& shape) {
    if (!db.some && shape.has_exponent) {
        double exponent = shape.exponent;
        if (exponent == 0) return NONE;
        if (exponent == 1) return da;
        if (exponent == 2) return some(2 * a * da.v);
        if (exponent == 0.5) return some(da.v / (2 * V));
        return some(exponent * kf_jspow1(a, exponent - 1) * da.v);
    }
    auto pw = [&](double x, double y) { return shape.b_one ? kf_jspow1(x, y) : kf_jspow(x, y); };
    if (!db.some) return some(b * pw(a, b - 1) * da.v);
    if (!da.some) return some(a > 0 ? V * kf_log(a) * db.v : 0.0);
    if (a > 0) return some(V * ((b / a) * da.v + kf_log(a) * db.v));
    return some(b * pw(a, b - 1) * da.v);
}

// The functions by what their derivative is: a rule of their own, a staircase (no tangent
// anywhere), or one of the few the walk handles itself.
bool is_stairs(Fn fn) {
    switch (fn) {
        case Fn::Ceil: case Fn::Floor: case Fn::Round: case Fn::Fix: case Fn::Sign: case Fn::Not: case Fn::And:
        case Fn::Or: case Fn::Nand: case Fn::Nor: case Fn::Xor: case Fn::Eps: case Fn::Pi:
            return true;
        default: return false;
    }
}
bool is_live_or_refuse(Fn fn) { return fn == Fn::InterpolationUseEndValues || fn == Fn::InterpolationExtrapolation; }
bool is_handled(Fn fn) {
    return fn == Fn::Power || fn == Fn::Min || fn == Fn::Max || fn == Fn::Sum || fn == Fn::Mean || fn == Fn::Prod;
}
bool is_rule_key(Fn fn) {
    switch (fn) {
        case Fn::Abs: case Fn::Sqrt: case Fn::Exp: case Fn::Log: case Fn::Log10: case Fn::Log2: case Fn::Hypot:
        case Fn::Sin: case Fn::Cos: case Fn::Tan: case Fn::Asin: case Fn::Acos: case Fn::Atan: case Fn::Sinh:
        case Fn::Cosh: case Fn::Tanh: case Fn::Asinh: case Fn::Acosh: case Fn::Atanh: case Fn::Erf: case Fn::Erfc:
        case Fn::Atan2: case Fn::Mod: case Fn::Rem: case Fn::Ulp: case Fn::RampDown: case Fn::RampUp:
        case Fn::SmoothDown: case Fn::SmoothUp: case Fn::InterpolationUseEndValues:
        case Fn::InterpolationExtrapolation: case Fn::Bq2Mole: case Fn::Mole2Bq:
            return true;
        default: return false;
    }
}
bool is_ramp_or_smooth(Fn fn) {
    return fn == Fn::RampDown || fn == Fn::RampUp || fn == Fn::SmoothDown || fn == Fn::SmoothUp;
}

/// A function's own rule: the tangent of its value `V` from its arguments' values and tangents.
MaybeF rule(const TCall& t, const double* A, const MaybeF* dA, std::size_t n, double V) {
    double a = A[0];
    MaybeF da = dA[0];
    switch (t.fn) {
        case Fn::Abs: return some(kf_sign(a) * da.v);
        case Fn::Sqrt: return some(da.v / (2 * V));
        case Fn::Exp: return some(V * da.v);
        case Fn::Log: return some(da.v / a);
        case Fn::Log10: return some(da.v / (a * LN10));
        case Fn::Log2: return some(da.v / (a * LN2));
        case Fn::Hypot: {
            MaybeF s = tadd(tmul(A[0], dA[0]), tmul(A[1], dA[1]));
            return s.some ? some(s.v / V) : NONE;
        }
        case Fn::Sin: return some(kf_cos(a) * da.v);
        case Fn::Cos: return some((-kf_sin(a)) * da.v);
        case Fn::Tan: return some((1 + V * V) * da.v);
        case Fn::Asin: return some(da.v / kf_sqrt(1 - a * a));
        case Fn::Acos: return some((-da.v) / kf_sqrt(1 - a * a));
        case Fn::Atan: return some(da.v / (1 + a * a));
        case Fn::Sinh: return some(kf_cosh(a) * da.v);
        case Fn::Cosh: return some(kf_sinh(a) * da.v);
        case Fn::Tanh: return some((1 - V * V) * da.v);
        case Fn::Asinh: return some(da.v / kf_sqrt(a * a + 1));
        case Fn::Acosh: return some(da.v / kf_sqrt(a * a - 1));
        case Fn::Atanh: return some(da.v / (1 - a * a));
        case Fn::Erf: return some(TWO_OVER_SQRT_PI * kf_exp(-a * a) * da.v);
        case Fn::Erfc: return some(-TWO_OVER_SQRT_PI * kf_exp(-a * a) * da.v);
        case Fn::Atan2: {
            MaybeF s = tadd(tmul(A[1], dA[0]), dA[1].some ? some(-(A[0] * dA[1].v)) : NONE);
            return s.some ? some(s.v / (A[0] * A[0] + A[1] * A[1])) : NONE;
        }
        case Fn::Mod:
            if (!dA[1].some) return da;
            if (A[1] == 0) return some(z(da));
            return some(z(da) - std::floor(A[0] / A[1]) * dA[1].v);
        case Fn::Rem:
            if (!dA[1].some) return da;
            if (A[1] == 0) return some(NaN);
            return some(z(da) - std::trunc(A[0] / A[1]) * dA[1].v);
        case Fn::Ulp: return some(kf_sign(a) * 2.220446049250313e-16 * da.v);
        case Fn::RampDown:
        case Fn::RampUp: {
            if (!dA[0].some || dA[1].some || dA[2].some) return NONE;
            double sign = t.fn == Fn::RampUp ? 1.0 : -1.0;
            double lo = kf_min(A[1], A[2]);
            double hi = kf_max(A[1], A[2]);
            bool inside = (A[0] > lo) & (A[0] < hi);
            return some(inside ? sign * dA[0].v / (hi - lo) : 0.0);
        }
        case Fn::SmoothDown:
        case Fn::SmoothUp: {
            if (!dA[0].some || dA[1].some || dA[2].some) return NONE;
            double sign = t.fn == Fn::SmoothUp ? 1.0 : -1.0;
            bool pos = A[0] > 0;
            return some(pos ? (sign * 2 * A[2] / A[0]) * V * (1 - V) * dA[0].v : 0.0);
        }
        case Fn::InterpolationUseEndValues:
        case Fn::InterpolationExtrapolation: {
            for (std::size_t i = 1; i < n; i++)
                if (dA[i].some) return NONE;
            return some(interpolate_slope(A, n, t.fn == Fn::InterpolationExtrapolation) * dA[0].v);
        }
        case Fn::Bq2Mole:
            return tadd(dA[0].some ? some(kf_bq2mole(dA[0].v, A[1])) : NONE, dA[1].some ? some(kf_bq2mole(A[0], dA[1].v)) : NONE);
        case Fn::Mole2Bq:
            return tadd(dA[0].some ? some(kf_mole2bq(dA[0].v, A[1])) : NONE, dA[1].some ? some(-V * dA[1].v / A[1]) : NONE);
        default: break;
    }
    throw NoDerivative(t.key + "()");
}

/// A function's tangent: `shape` is what is known of its exponent when it is a power.
MaybeF call_tangent(const TCall& t, const double* A, const MaybeF* dA, std::size_t n, double V, const PowerShape& shape) {
    switch (t.fn) {
        case Fn::Power: return zero_seed_guard(dA, n, power_rule(A[0], A[1], dA[0], dA[1], V, shape));
        case Fn::Min:
        case Fn::Max: {
            double out = NaN;
            for (std::size_t i = n; i-- > 0;) {
                double d = dA[i].some ? dA[i].v : 0.0;
                if (A[i] == V) out = d;
            }
            return some(out);
        }
        case Fn::Sum: {
            MaybeF out = NONE;
            for (std::size_t i = 0; i < n; i++) out = tadd(out, dA[i]);
            return out;
        }
        case Fn::Mean: {
            MaybeF out = NONE;
            for (std::size_t i = 0; i < n; i++) out = tadd(out, dA[i]);
            return out.some ? some(out.v / static_cast<double>(n)) : NONE;
        }
        case Fn::Prod: {
            double p = A[0];
            MaybeF dp = dA[0];
            for (std::size_t i = 1; i < n; i++) {
                double nxt = p * A[i];
                dp = tadd(dp.some ? some(A[i] * dp.v) : NONE, tmul(p, dA[i]));
                p = nxt;
            }
            return dp;
        }
        default: break;
    }
    if (!is_rule_key(t.fn)) {
        if (is_stairs(t.fn)) return NONE;
        throw NoDerivative(t.key + "()");
    }
    MaybeF tangent = rule(t, A, dA, n, V);
    if (!tangent.some && is_live_or_refuse(t.fn)) {
        for (std::size_t i = 0; i < n; i++)
            if (dA[i].some) throw NoDerivative(t.key + "() with a table that depends on the state");
    }
    return zero_seed_guard(dA, n, tangent);
}

std::vector<bool> scalar_arguments(const TCall& t) {
    std::vector<bool> ones;
    for (const auto& x : t.args) ones.push_back(scalar_subtree(*x));
    return ones;
}
bool reads_ones(Fn fn) { return fn == Fn::Power || fn == Fn::SmoothDown || fn == Fn::SmoothUp; }

/// Forward-mode tangent of one statement along one leaf, one element at a time: `values`
/// the element's leaves in `tree_leaves` order, `seed` the leaf the tangent is taken along
/// (-1: none, for the value alone).
struct Tangent {
    const Tables* tables;
    const double* values;
    int seed;
    int pos;
};

std::pair<double, MaybeF> twalk(Tangent& tg, const TNode& t) {
    switch (t.kind) {
        case TNode::Kind::Leaf: {
            int k = tg.pos++;
            return {tg.values[k], k == tg.seed ? some(1.0) : NONE};
        }
        case TNode::Kind::Neg: {
            auto [v, d] = twalk(tg, *as_neg(t).a);
            return {-v, d.some ? some(-d.v) : NONE};
        }
        case TNode::Kind::Bin: {
            const TBin& n = as_bin(t);
            BinOp op = n.op;
            auto [a, da] = twalk(tg, *n.a);
            auto [b, db] = twalk(tg, *n.b);
            bool b_one = op == BinOp::Pow ? scalar_subtree(*n.b) : true;
            double value = apply_binary(op, a, b, b_one);
            if (op == BinOp::Add) return {value, tadd(da, db)};
            if (op == BinOp::Sub) {
                if (!db.some) return {value, da};
                return {value, da.some ? some(da.v - db.v) : some(-db.v)};
            }
            if (op == BinOp::Mul) {
                if (!da.some && !db.some) return {value, NONE};
                return {value, tadd(tmul(b, da), tmul(a, db))};
            }
            if (op == BinOp::Div) {
                if (!da.some && !db.some) return {value, NONE};
                if (!db.some) return {value, some(da.v / b)};
                if (!da.some) return {value, some((-(value * db.v)) / b)};
                return {value, some((da.v - value * db.v) / b)};
            }
            if (op == BinOp::Pow) {
                if (!da.some && !db.some) return {value, NONE};
                MaybeF both[2] = {da, db};
                return {value, zero_seed_guard(both, 2, power_rule(a, b, da, db, value, power_shape(*n.b)))};
            }
            return {value, NONE};
        }
        case TNode::Kind::Cond: {
            const TCond& n = as_tcond(t);
            double test = twalk(tg, *n.test).first;
            auto [a, da] = twalk(tg, *n.a);
            auto [b, db] = twalk(tg, *n.b);
            bool chosen = test != 0;
            double value = chosen ? a : b;
            if (!da.some && !db.some) return {value, NONE};
            return {value, some(chosen ? z(da) : z(db))};
        }
        case TNode::Kind::Tab: {
            const TTab& n = as_tab(t);
            int index = static_cast<int>(tg.values[tg.pos++]);   // the table's index is never live
            auto [arg, darg] = twalk(tg, *n.arg);
            const LookupTable& table = *(*tg.tables)[static_cast<std::size_t>(index)];
            double value = table_at(table, arg);
            if (!darg.some) return {value, NONE};
            return {value, some(table_slope(table, arg) * darg.v)};
        }
        case TNode::Kind::Call: {
            const TCall& n = as_tcall(t);
            std::size_t count = n.args.size();
            std::vector<double> A(count);
            std::vector<MaybeF> dA(count, NONE);
            for (std::size_t i = 0; i < count; i++) {
                auto [v, d] = twalk(tg, *n.args[i]);
                A[i] = v;
                dA[i] = d;
            }
            std::vector<bool> ones;
            if (reads_ones(n.fn)) ones = scalar_arguments(n);
            double value = call_value(n.fn, A.data(), count, reads_ones(n.fn) ? &ones : nullptr);
            bool live = false;
            for (const MaybeF& d : dA) live = live || d.some;
            if (!live) return {value, NONE};
            PowerShape shape = n.fn == Fn::Power ? power_shape(*n.args[1]) : PowerShape{};
            return {value, call_tangent(n, A.data(), dA.data(), count, value, shape)};
        }
    }
    throw std::logic_error("tangent: a node of no kind");
}

std::pair<double, MaybeF> tangent_run(Tangent& tg, const TNode& tree, const double* values, int seed) {
    tg.values = values;
    tg.seed = seed;
    tg.pos = 0;
    return twalk(tg, tree);
}

// --- the tangent, laid out flat ---------------------------------------------------------------------
//
// The walk above computes every node's value again for every leaf it seeds,
// and asks each node what it is as it goes. A statement's tree is laid out
// once instead, its nodes in the order the walk finishes them (children
// first): the values of every element are worked out in a single pass, node by
// node, and a leaf's tangent is then carried up the one path from it to the
// root -- every node off that path has no tangent, as the walk finds (a node
// whose arguments all have none has none). Each step does the walk's
// arithmetic, in its order, so the numbers are the walk's to the bit. Both
// passes run over all of a statement's elements at each node: the arithmetic
// of one element never meets another's, so the order they are taken in changes
// no number.

enum : std::uint8_t { TP_LEAF = 1, TP_NEG, TP_BIN, TP_COND, TP_TAB, TP_CALL };

/// A statement's tree as the tangent reads it: nodes children first, each leaf at its
/// position in `tree_leaves`.
struct TangentTape {
    std::vector<std::uint8_t> kind;
    std::vector<std::uint8_t> op;         // a binary operation's `BinOp`
    std::vector<const TNode*> node;       // (kept alive by the plan's tree)
    std::vector<const TLeaf*> leaf;       // a leaf's own, a table's index
    std::vector<I32> arg_ptr, arg_count;  // a node's children, in order, in `arg_idx`
    std::vector<I32> arg_idx;
    std::vector<I32> pos;                 // a leaf's position (a table's: its index's)
    std::vector<PowerShape> shape;        // ^ and power(): the exponent
    std::vector<I32> ones;                // power, smoothDown, smoothUp: which arguments are one number (-1: none)
    std::vector<std::vector<bool>> ones_store;
    std::vector<I32> parent;              // -1: the root
    std::vector<I32> slot;                // which of its parent's children a node is
    std::vector<I32> leaf_node;           // the node at each leaf position (-1: a table's index)
    I32 most_args = 0;

    std::size_t size() const { return kind.size(); }
};

I32 tape_push(TangentTape& tp, std::uint8_t kind, const TNode& t, const std::vector<I32>& args, I32 pos) {
    tp.kind.push_back(kind);
    tp.op.push_back(0);
    tp.node.push_back(&t);
    tp.leaf.push_back(nullptr);
    tp.arg_ptr.push_back(static_cast<I32>(tp.arg_idx.size()));
    tp.arg_count.push_back(static_cast<I32>(args.size()));
    tp.arg_idx.insert(tp.arg_idx.end(), args.begin(), args.end());
    tp.pos.push_back(pos);
    tp.shape.emplace_back();
    tp.ones.push_back(-1);
    tp.most_args = std::max(tp.most_args, static_cast<I32>(args.size()));
    return static_cast<I32>(tp.kind.size()) - 1;
}

I32 tape_node(TangentTape& tp, const TNode& t) {
    switch (t.kind) {
        case TNode::Kind::Leaf: {
            tp.leaf_node.push_back(-1);
            I32 p = static_cast<I32>(tp.leaf_node.size()) - 1;
            I32 k = tape_push(tp, TP_LEAF, t, {}, p);
            tp.leaf[static_cast<std::size_t>(k)] = &as_leaf(t);
            tp.leaf_node[static_cast<std::size_t>(p)] = k;
            return k;
        }
        case TNode::Kind::Neg: {
            I32 c = tape_node(tp, *as_neg(t).a);
            return tape_push(tp, TP_NEG, t, {c}, -1);
        }
        case TNode::Kind::Bin: {
            const TBin& n = as_bin(t);
            I32 a = tape_node(tp, *n.a);
            I32 b = tape_node(tp, *n.b);
            I32 k = tape_push(tp, TP_BIN, t, {a, b}, -1);
            tp.op[static_cast<std::size_t>(k)] = static_cast<std::uint8_t>(n.op);
            if (n.op == BinOp::Pow) tp.shape[static_cast<std::size_t>(k)] = power_shape(*n.b);
            return k;
        }
        case TNode::Kind::Cond: {
            const TCond& n = as_tcond(t);
            I32 c1 = tape_node(tp, *n.test);
            I32 c2 = tape_node(tp, *n.a);
            I32 c3 = tape_node(tp, *n.b);
            return tape_push(tp, TP_COND, t, {c1, c2, c3}, -1);
        }
        case TNode::Kind::Tab: {
            const TTab& n = as_tab(t);
            tp.leaf_node.push_back(-1);                       // the table's index: never live
            I32 p = static_cast<I32>(tp.leaf_node.size()) - 1;
            I32 c = tape_node(tp, *n.arg);
            I32 k = tape_push(tp, TP_TAB, t, {c}, p);
            tp.leaf[static_cast<std::size_t>(k)] = n.leaf.get();
            return k;
        }
        case TNode::Kind::Call: {
            const TCall& n = as_tcall(t);
            std::vector<I32> cs;
            for (const auto& x : n.args) cs.push_back(tape_node(tp, *x));
            I32 k = tape_push(tp, TP_CALL, t, cs, -1);
            if (reads_ones(n.fn)) {
                tp.ones[static_cast<std::size_t>(k)] = static_cast<I32>(tp.ones_store.size());
                tp.ones_store.push_back(scalar_arguments(n));
            }
            if (n.fn == Fn::Power) tp.shape[static_cast<std::size_t>(k)] = power_shape(*n.args[1]);
            return k;
        }
    }
    throw std::logic_error("tangent: a node of no kind");
}

TangentTape make_tape(const TNode& tree) {
    TangentTape tp;
    tape_node(tp, tree);
    std::size_t m = tp.size();
    tp.parent.assign(m, -1);
    tp.slot.assign(m, 0);
    for (std::size_t k = 0; k < m; k++) {
        const I32* c = tp.arg_idx.data() + tp.arg_ptr[k];
        for (I32 s = 0; s < tp.arg_count[k]; s++) {
            tp.parent[static_cast<std::size_t>(c[s])] = static_cast<I32>(k);
            tp.slot[static_cast<std::size_t>(c[s])] = s;
        }
    }
    return tp;
}

/// Where a statement's leaves are read at `(t, y)`.
struct Reads {
    const double* y;
    const double* X;
    const double* P;
    double t;
    const System* sys;
    const Tables* tables;
};

/// One leaf's value for one element.
inline double leaf_value(const TLeaf& l, std::size_t i, const Reads& rd) {
    switch (l.leaf) {
        case LeafKind::Y: return rd.y[l.index_at(i)];
        case LeafKind::X: return rd.X[l.index_at(i)];
        case LeafKind::P: return rd.P[l.index_at(i)];
        case LeafKind::K: return l.value_at(i);
        case LeafKind::T: return rd.t;
        case LeafKind::T0: return rd.sys->start_time;
        case LeafKind::T1: return rd.sys->end_time;
        case LeafKind::DIS: return rd.sys->data.DIS[static_cast<std::size_t>(l.index_at(i))];
        case LeafKind::TAB: return static_cast<double>(l.index_at(i));   // read by the tangent as the table's index
    }
    return 0.0;
}

/// One leaf's value for every element.
void leaf_values(double* out, const TLeaf& l, std::size_t W, const Reads& rd) {
    const double* from = nullptr;
    switch (l.leaf) {
        case LeafKind::Y: from = rd.y; break;
        case LeafKind::X: from = rd.X; break;
        case LeafKind::P: from = rd.P; break;
        case LeafKind::DIS: from = rd.sys->data.DIS.data(); break;
        case LeafKind::K:
            if (l.values) std::copy_n(l.values->data(), W, out);
            else std::fill_n(out, W, l.value);
            return;
        case LeafKind::T: std::fill_n(out, W, rd.t); return;
        case LeafKind::T0: std::fill_n(out, W, rd.sys->start_time); return;
        case LeafKind::T1: std::fill_n(out, W, rd.sys->end_time); return;
        case LeafKind::TAB:
            for (std::size_t i = 0; i < W; i++) out[i] = static_cast<double>(l.index_at(i));
            return;
    }
    if (l.indices) {
        const int* idx = l.indices->data();
        for (std::size_t i = 0; i < W; i++) out[i] = from[idx[i]];
    } else {
        std::fill_n(out, W, from[l.index]);
    }
}

/// Every node's value for every element, into `nv`: node `k`'s values at `nv[k * W ...]`.
/// `A` is room for one call's arguments.
void tape_values(double* nv, const TangentTape& tp, std::size_t W, const Reads& rd, double* A) {
    // NOTE(speed): a subtree that is one number for every element (`scalar_subtree`) is worked
    // out W times over here; it could be worked out once and spread.
    std::size_t m = tp.size();
    for (std::size_t k = 0; k < m; k++) {
        double* out = nv + k * W;
        const I32* c = tp.arg_idx.data() + tp.arg_ptr[k];
        switch (tp.kind[k]) {
            case TP_LEAF: leaf_values(out, *tp.leaf[k], W, rd); break;
            case TP_BIN: {
                const double* a = nv + static_cast<std::size_t>(c[0]) * W;
                const double* b = nv + static_cast<std::size_t>(c[1]) * W;
                BinOp op = static_cast<BinOp>(tp.op[k]);
                switch (op) {
                    case BinOp::Add:
                        for (std::size_t i = 0; i < W; i++) out[i] = a[i] + b[i];
                        break;
                    case BinOp::Sub:
                        for (std::size_t i = 0; i < W; i++) out[i] = a[i] - b[i];
                        break;
                    case BinOp::Mul:
                        for (std::size_t i = 0; i < W; i++) out[i] = a[i] * b[i];
                        break;
                    case BinOp::Div:
                        for (std::size_t i = 0; i < W; i++) out[i] = a[i] / b[i];
                        break;
                    default: {
                        bool b_one = tp.shape[k].b_one;
                        for (std::size_t i = 0; i < W; i++) out[i] = apply_binary(op, a[i], b[i], b_one);
                    }
                }
                break;
            }
            case TP_NEG: {
                const double* a = nv + static_cast<std::size_t>(c[0]) * W;
                for (std::size_t i = 0; i < W; i++) out[i] = -a[i];
                break;
            }
            case TP_COND: {
                const double* test = nv + static_cast<std::size_t>(c[0]) * W;
                const double* a = nv + static_cast<std::size_t>(c[1]) * W;
                const double* b = nv + static_cast<std::size_t>(c[2]) * W;
                for (std::size_t i = 0; i < W; i++) out[i] = test[i] != 0 ? a[i] : b[i];
                break;
            }
            case TP_TAB: {
                const TLeaf& index = *tp.leaf[k];
                const double* arg = nv + static_cast<std::size_t>(c[0]) * W;
                for (std::size_t i = 0; i < W; i++) out[i] = table_at(*(*rd.tables)[static_cast<std::size_t>(index.index_at(i))], arg[i]);
                break;
            }
            default: {
                const TCall& call = as_tcall(*tp.node[k]);
                std::size_t n = static_cast<std::size_t>(tp.arg_count[k]);
                const std::vector<bool>* ones = tp.ones[k] < 0 ? nullptr : &tp.ones_store[static_cast<std::size_t>(tp.ones[k])];
                for (std::size_t i = 0; i < W; i++) {
                    for (std::size_t j = 0; j < n; j++) A[j] = nv[static_cast<std::size_t>(c[j]) * W + i];
                    out[i] = call_value(call.fn, A, n, ones);
                }
            }
        }
    }
}

/// The tangent of the root along the leaf at position `p`, for every element, from the
/// nodes' values `nv`, into `d`: false where the walk finds none for some element (the
/// statement's term along that leaf is then left out whole, as the walk leaves it).
bool tape_tangent(double* d, const TangentTape& tp, I32 p, std::size_t W, const double* nv, const Tables& tables, double* A,
                  MaybeF* dA) {
    I32 k = tp.leaf_node[static_cast<std::size_t>(p)];
    std::fill_n(d, W, 1.0);
    for (;;) {
        I32 par_ = tp.parent[static_cast<std::size_t>(k)];
        if (par_ < 0) return true;
        std::size_t par = static_cast<std::size_t>(par_);
        I32 s = tp.slot[static_cast<std::size_t>(k)];
        const I32* c = tp.arg_idx.data() + tp.arg_ptr[par];
        switch (tp.kind[par]) {
            case TP_BIN: {
                const double* a = nv + static_cast<std::size_t>(c[0]) * W;
                const double* b = nv + static_cast<std::size_t>(c[1]) * W;
                const double* value = nv + par * W;
                switch (static_cast<BinOp>(tp.op[par])) {
                    case BinOp::Add: break;
                    case BinOp::Sub:
                        if (s != 0)
                            for (std::size_t i = 0; i < W; i++) d[i] = -d[i];
                        break;
                    case BinOp::Mul: {
                        const double* other = s == 0 ? b : a;
                        for (std::size_t i = 0; i < W; i++) d[i] = other[i] * d[i];
                        break;
                    }
                    case BinOp::Div:
                        if (s == 0) {
                            for (std::size_t i = 0; i < W; i++) d[i] = d[i] / b[i];
                        } else {
                            for (std::size_t i = 0; i < W; i++) d[i] = (-(value[i] * d[i])) / b[i];
                        }
                        break;
                    case BinOp::Pow: {
                        const PowerShape& shape = tp.shape[par];
                        for (std::size_t i = 0; i < W; i++) {
                            MaybeF both[2] = {s == 0 ? some(d[i]) : NONE, s == 1 ? some(d[i]) : NONE};
                            MaybeF r = zero_seed_guard(both, 2, power_rule(a[i], b[i], both[0], both[1], value[i], shape));
                            if (!r.some) return false;
                            d[i] = r.v;
                        }
                        break;
                    }
                    default: return false;   // a comparison, a logical operation: no tangent
                }
                break;
            }
            case TP_NEG:
                for (std::size_t i = 0; i < W; i++) d[i] = -d[i];
                break;
            case TP_COND: {
                if (s == 0) return false;   // the test's tangent is nobody's
                const double* test = nv + static_cast<std::size_t>(c[0]) * W;
                if (s == 1) {
                    for (std::size_t i = 0; i < W; i++) d[i] = test[i] != 0 ? d[i] : 0.0;
                } else {
                    for (std::size_t i = 0; i < W; i++) d[i] = test[i] != 0 ? 0.0 : d[i];
                }
                break;
            }
            case TP_TAB: {
                const TLeaf& index = *tp.leaf[par];
                const double* arg = nv + static_cast<std::size_t>(c[0]) * W;
                for (std::size_t i = 0; i < W; i++)
                    d[i] = table_slope(*tables[static_cast<std::size_t>(index.index_at(i))], arg[i]) * d[i];
                break;
            }
            default: {
                const TCall& call = as_tcall(*tp.node[par]);
                std::size_t n = static_cast<std::size_t>(tp.arg_count[par]);
                const double* value = nv + par * W;
                const PowerShape& shape = tp.shape[par];
                for (std::size_t j = 0; j < n; j++) dA[j] = NONE;
                for (std::size_t i = 0; i < W; i++) {
                    for (std::size_t j = 0; j < n; j++) A[j] = nv[static_cast<std::size_t>(c[j]) * W + i];
                    dA[s] = some(d[i]);
                    MaybeF r = call_tangent(call, A, dA, n, value[i], shape);
                    if (!r.some) return false;
                    d[i] = r.v;
                }
            }
        }
        k = par_;
    }
}

/// Refuses, before any evaluation, a statement whose derivative along a live leaf would need
/// a rule nobody wrote. `live`: by leaf position.
bool check_differentiable(const TNode& t, const std::vector<char>& live, std::size_t& pos) {
    switch (t.kind) {
        case TNode::Kind::Leaf: return live[pos++] != 0;
        case TNode::Kind::Neg: return check_differentiable(*as_neg(t).a, live, pos);
        case TNode::Kind::Bin: {
            bool a = check_differentiable(*as_bin(t).a, live, pos);
            bool b = check_differentiable(*as_bin(t).b, live, pos);
            return a || b;
        }
        case TNode::Kind::Cond: {
            bool a = check_differentiable(*as_tcond(t).test, live, pos);
            bool b = check_differentiable(*as_tcond(t).a, live, pos);
            bool c = check_differentiable(*as_tcond(t).b, live, pos);
            return b || c || a;
        }
        case TNode::Kind::Tab:
            pos++;
            return check_differentiable(*as_tab(t).arg, live, pos);
        case TNode::Kind::Call: {
            const TCall& n = as_tcall(t);
            bool any = false, any_after_first = false;
            for (std::size_t i = 0; i < n.args.size(); i++) {
                bool flag = check_differentiable(*n.args[i], live, pos);
                any = any || flag;
                if (i > 0) any_after_first = any_after_first || flag;
            }
            if (!any) return false;
            if (is_handled(n.fn) || is_stairs(n.fn)) return true;
            if (is_live_or_refuse(n.fn) && any_after_first) throw NoDerivative(n.key + "() with a table that depends on the state");
            if (is_ramp_or_smooth(n.fn) && any_after_first) throw NoDerivative(n.key + "() whose ends depend on the state");
            if (!is_rule_key(n.fn)) throw NoDerivative(n.key + "()");
            return true;
        }
    }
    return false;
}

// --- the analytic Jacobian ------------------------------------------------------------------------------

/// One statement's part in the gradients of the slots that read the state.
struct StatementPlan {
    struct YTerm {
        I32 leaf;
        std::vector<I32> dst;                // a place among the gradients per element
    };
    struct XTerm {
        I32 leaf;
        std::vector<I32> elem, src, dst;     // the element, the gradient entry read, the one added to
    };
    struct Own {
        I32 elem, lo, hi;                    // the slot's own gradient: [lo, hi) among the gradients
    };
    TNodePtr tree;
    TangentTape tape;
    std::vector<TLeafPtr> leaves;
    std::size_t width = 1;
    std::vector<I32> outs;
    std::vector<YTerm> y_terms;
    std::vector<XTerm> x_terms;
    bool multiply = false;
    std::vector<Own> own;
};

/// What a statement of special code contributes.
struct SpecialPlan {
    enum class Kind : unsigned char { Farfield, Laplace, Zero, MinMax, RunningMean };
    /// A remembering block at one of its indices, when its slot has a gradient.
    struct Item {
        I32 out = 0;             // its slot
        I32 tgt = 0;             // its target's
        bool follows = false;    // the target has a gradient to take
        I32 src = 0;             // the target's gradient, and
        I32 pos = 0, count = 0;  // where each of its entries goes in the slot's own (in `pos`)
        I32 own = 0;             // a running mean: its summed state's place in the slot's gradient
        I32 mem = 0;             // its recorder
    };
    /// A far-field setting that follows the state, as the release's gradient reads it: the
    /// setting's slot and, for every slot of the path reading it, the release's gradient
    /// positions over the setting's columns and the setting's own gradient there.
    struct SettingPart {
        I32 slot = 0;
        std::vector<I32> pos, src;
    };
    struct SettingTerm {
        I32 x = 0;
        std::vector<SettingPart> parts;
    };
    Kind kind = Kind::Zero;
    std::vector<Item> items;
    std::vector<I32> pos;
    I32 path = -1;             // a far-field path's release: which path (`pos` is where its weights go)
    std::vector<SettingTerm> terms;   // ... and the settings of it that follow the state
};

/// A direct term group: J[pos] += value, value from `kind`.
struct DirectTerm {
    enum class Kind : unsigned char { XSign, NegXH, XH, NegXX, XX, Const, Farf };
    Kind kind;
    std::vector<I32> pos;
    std::vector<I32> a;        // slots
    std::vector<double> f;     // signs or coefficients
    I32 s1 = 0, s2 = 0;
};

/// A chain term group: J[dst] += coefficient * G[src], the coefficient its element's
/// (`sign` and `idx` are spread out here over the entries of each element's gradient).
struct ChainTerm {
    enum class Kind : unsigned char { SignDonor, Ones, NegY, Y, NegOne, NegXY, XY, Recording, FarfSettings };
    Kind kind;
    std::vector<I32> src, dst;
    std::vector<double> sign;
    std::vector<I32> idx;      // states (or recorders); -1: none. FarfSettings: the element
    I32 s1 = 0;                // a slot. FarfSettings: the path
    std::vector<I32> parts;    // FarfSettings: the (setting, slot) pairs, flat
};

/// Everything worked out once for a model: shared by every copy of its system.
struct AnalyticPlan {
    std::vector<I32> g_row_of;             // by slot: its row among the gradients, -1 for none
    std::vector<I32> g_ptr;                // each row's start, and the end
    std::vector<I32> g_col;                // each row's states, sorted
    std::size_t g_nnz = 0;
    std::vector<std::pair<bool, I32>> order;   // the plans in dependency order: (special?, which)
    std::vector<StatementPlan> statements;
    std::vector<SpecialPlan> specials;
    std::vector<DirectTerm> direct;
    std::vector<ChainTerm> chain;
    bool constant = false;
    bool state_free = false;               // df/dy moves with the clock at most: the model is linear
    // what an evaluation needs room for
    std::size_t most_nodes = 0, most_width = 1, most_products = 0, most_args = 1;

    std::size_t row_size(I32 r) const { return static_cast<std::size_t>(g_ptr[static_cast<std::size_t>(r) + 1] - g_ptr[static_cast<std::size_t>(r)]); }
    const I32* row_cols(I32 r) const { return g_col.data() + g_ptr[static_cast<std::size_t>(r)]; }
    /// The row of a slot that has a gradient, -1 otherwise.
    I32 row_of(int slot) const { return g_row_of[static_cast<std::size_t>(slot)]; }
    /// Where the state `c` sits in the gradient of `slot`.
    I32 g_pos(int slot, int c) const {
        I32 r = row_of(slot);
        if (r < 0) throw std::logic_error("a slot without a gradient");
        const I32* cols = row_cols(r);
        std::size_t count = row_size(r);
        std::size_t at = static_cast<std::size_t>(std::lower_bound(cols, cols + count, static_cast<I32>(c)) - cols);
        if (at >= count) throw std::logic_error("a state outside a slot's gradient");
        return g_ptr[static_cast<std::size_t>(r)] + static_cast<I32>(at);
    }
};

/// Where the entry (row, col) sits among the pattern's values.
I32 pat_pos(const Pattern& p, int row, int col) {
    const I32* first = p.rowval.data() + p.colptr[static_cast<std::size_t>(col)];
    const I32* last = p.rowval.data() + p.colptr[static_cast<std::size_t>(col) + 1];
    const I32* at = std::lower_bound(first, last, static_cast<I32>(row));
    if (at == last || *at != row) throw NoDerivative("an entry outside the Jacobian pattern");
    return static_cast<I32>(at - p.rowval.data());
}

/// A path's setting slots that follow the state and have a gradient, each once, in order.
std::vector<int> settings_moving(const AnalyticPlan& an, const FarfieldPath& F, const std::vector<unsigned char>& moving) {
    std::vector<int> all = F.setting_slots();
    std::sort(all.begin(), all.end());
    all.erase(std::unique(all.begin(), all.end()), all.end());
    std::vector<int> out;
    for (int x : all) {
        if (moving[static_cast<std::size_t>(x)] != 2) continue;
        I32 g = an.row_of(x);
        if (g < 0 || an.row_size(g) == 0) continue;
        out.push_back(x);
    }
    return out;
}

/// The tangents of a path's rates and release weights along its setting slot `x`:
/// `farfield_tangent` along that slot alone, into `T` (Python's `_setting_partials`).
void setting_partials(FarfTangent& T, FarfPath& F, const double* X, std::size_t nalg, int x) {
    std::vector<double> dX(nalg, 0.0);
    dX[static_cast<std::size_t>(x)] = 1.0;
    if (!farfield_tangent(T, F, X, dX.data())) {
        std::fill(T.dvals.begin(), T.dvals.end(), 0.0);
        std::fill(T.drel.begin(), T.drel.end(), 0.0);
    }
}

/// For each (setting, slot) pair of `parts`, each cell's rate along the setting: the tangent
/// of the slot's matrix entries times the state, added up entry by entry.
std::vector<double> settings_rates(FarfPath& F, const std::vector<I32>& parts, const double* y, const double* X,
                                   std::size_t nalg) {
    const std::size_t nc = static_cast<std::size_t>(F.ncells), nnz = static_cast<std::size_t>(F.nnz);
    std::vector<double> out(parts.size() / 2 * nc, 0.0);
    std::unordered_map<int, std::vector<double>> partials;
    for (std::size_t i = 0; i < parts.size() / 2; i++) {
        const int x = parts[2 * i], slot = parts[2 * i + 1];
        auto it = partials.find(x);
        if (it == partials.end()) {
            FarfTangent T(F);
            setting_partials(T, F, X, nalg, x);
            it = partials.emplace(x, std::move(T.dvals)).first;
        }
        const std::vector<double>& dvals = it->second;
        const std::size_t base = i * nc, off = static_cast<std::size_t>(slot) * nnz;
        for (std::size_t e = 0; e < nnz; e++)
            out[base + static_cast<std::size_t>(F.rows[e])] += dvals[off + e] * y[F.col_flat_[off + e]];
    }
    return out;
}

SpecialPlan special_plan(const AnalyticPlan& an, const Builder& b, const EntryPtr& a) {
    const auto& moving = b.slot_class;
    SpecialPlan plan;
    if (a->kind == "farfield") {
        // A path's release: its weights on the cells it is released from; a semi-analytical
        // path's, the weight of each source's current inflow times that inflow's gradient.
        const FarfieldPath& F = *b.FARF[static_cast<std::size_t>(a->farf_index)];
        if (F.laplace) {
            plan.kind = SpecialPlan::Kind::Laplace;
            plan.path = a->farf_index;
            return plan;
        }
        plan.kind = SpecialPlan::Kind::Farfield;
        plan.path = a->farf_index;
        const std::vector<int>& release = F.release_slots();
        for (int slot = 0; slot < F.slots(); slot++)
            for (int c : F.rel_idx(slot)) plan.pos.push_back(an.g_pos(release[static_cast<std::size_t>(slot)], c));
        // A setting that follows the state moves the release's weights (see `special_gradient`).
        for (int x : settings_moving(an, F, moving)) {
            I32 g = an.row_of(x);
            std::size_t ncols = an.row_size(g);
            const I32* cols = an.row_cols(g);
            SpecialPlan::SettingTerm term;
            term.x = x;
            for (int slot = 0; slot < F.slots(); slot++) {
                std::vector<int> mine = F.setting_slots_of(slot);
                if (std::find(mine.begin(), mine.end(), x) == mine.end()) continue;
                SpecialPlan::SettingPart part;
                part.slot = slot;
                for (std::size_t q = 0; q < ncols; q++) {
                    part.pos.push_back(an.g_pos(release[static_cast<std::size_t>(slot)], cols[q]));
                    part.src.push_back(an.g_ptr[static_cast<std::size_t>(g)] + static_cast<I32>(q));
                }
                term.parts.push_back(std::move(part));
            }
            plan.terms.push_back(std::move(term));
        }
        return plan;
    }
    const EntryPtr& rec = a->recorder;
    if (!rec) throw NoDerivative(a->kind);
    if (rec->kind == "delay") {
        for (int off = 0; off < a->width; off++) {
            if (moving[static_cast<std::size_t>(rec->aux_at("delay")->base + off)] == 2) {
                throw NoDerivative("a delay whose lag depends on the state: its value slides along the recorded history "
                                   "as the state changes, and that derivative is not one to guess at");
            }
        }
        plan.kind = SpecialPlan::Kind::Zero;
        return plan;
    }
    if (rec->kind == "snapshot") {
        plan.kind = SpecialPlan::Kind::Zero;
        return plan;
    }
    // A minimum or maximum follows its target while it is at it; a running mean is its
    // summed state over the time recorded, and its target before any has been. Where each
    // of those lands among the gradients is the same at every evaluation: found once here.
    bool mean = rec->kind == "running_mean";
    plan.kind = mean ? SpecialPlan::Kind::RunningMean : rec->kind == "min_max" ? SpecialPlan::Kind::MinMax : SpecialPlan::Kind::Zero;
    if (plan.kind == SpecialPlan::Kind::Zero) return plan;
    for (int off = 0; off < a->width; off++) {
        int out = a->base + off;
        if (an.row_of(out) < 0) continue;
        SpecialPlan::Item item;
        item.out = out;
        item.tgt = rec->aux_at("target")->base + off;
        item.mem = rec->mem + off;
        if (mean) item.own = an.g_pos(out, rec->state->base + off);
        I32 r = an.row_of(item.tgt);
        if (r >= 0 && moving[static_cast<std::size_t>(item.tgt)] == 2) {
            item.follows = true;
            item.src = an.g_ptr[static_cast<std::size_t>(r)];
            item.pos = static_cast<I32>(plan.pos.size());
            item.count = static_cast<I32>(an.row_size(r));
            const I32* cols = an.row_cols(r);
            for (I32 q = 0; q < item.count; q++) plan.pos.push_back(an.g_pos(out, cols[q]));
        }
        plan.items.push_back(item);
    }
    return plan;
}

void plan_statements(AnalyticPlan& an, const Builder& b) {
    const auto& moving = b.slot_class;
    for (const auto& a : b.algebraic) {
        if (a->cls != 2 || (b.has_derivative_stmts && b.derivative_blocks.count(a->name) == 0)) continue;
        for (const auto& s : b.alg_stmts.at(a->name)) {
            if (s->special) {
                an.order.emplace_back(true, static_cast<I32>(an.specials.size()));
                an.specials.push_back(special_plan(an, b, a));
                continue;
            }
            StatementPlan plan;
            std::size_t W = static_cast<std::size_t>(std::max(1, s->width));
            std::vector<int> outs = s->out_indices();
            if (outs.size() < W) outs.assign(W, outs[0]);
            plan.tree = s->tree;
            plan.leaves = tree_leaves(s->tree);
            plan.width = W;
            plan.outs.assign(outs.begin(), outs.end());
            plan.multiply = s->multiply;
            std::vector<char> live(plan.leaves.size(), 0);
            bool any_live = false;
            for (std::size_t p = 0; p < plan.leaves.size(); p++) {
                const TLeaf& leaf = *plan.leaves[p];
                if (leaf.leaf == LeafKind::Y) {
                    StatementPlan::YTerm term;
                    term.leaf = static_cast<I32>(p);
                    for (std::size_t i = 0; i < W; i++) term.dst.push_back(an.g_pos(outs[i], leaf.index_at(i)));
                    plan.y_terms.push_back(std::move(term));
                    live[p] = 1;
                    any_live = true;
                } else if (leaf.leaf == LeafKind::X) {
                    bool moves = false;
                    for (std::size_t i = 0; i < W; i++) moves = moves || moving[static_cast<std::size_t>(leaf.index_at(i))] == 2;
                    if (!moves) continue;
                    StatementPlan::XTerm term;
                    term.leaf = static_cast<I32>(p);
                    for (std::size_t i = 0; i < W; i++) {
                        int x = leaf.index_at(i);
                        if (moving[static_cast<std::size_t>(x)] != 2 || an.row_of(x) < 0) continue;
                        I32 r = an.row_of(x);
                        std::size_t count = an.row_size(r);
                        const I32* cols = an.row_cols(r);
                        for (std::size_t q = 0; q < count; q++) {
                            term.elem.push_back(static_cast<I32>(i));
                            term.src.push_back(an.g_ptr[static_cast<std::size_t>(r)] + static_cast<I32>(q));
                            term.dst.push_back(an.g_pos(outs[i], cols[q]));
                        }
                    }
                    if (term.elem.empty()) continue;
                    an.most_products = std::max(an.most_products, term.elem.size());
                    plan.x_terms.push_back(std::move(term));
                    live[p] = 1;
                    any_live = true;
                }
            }
            if (any_live) {
                std::size_t pos = 0;
                check_differentiable(*s->tree, live, pos);
            }
            if (s->multiply) {
                for (std::size_t i = 0; i < outs.size(); i++) {
                    I32 r = an.row_of(outs[i]);
                    if (r < 0) continue;
                    plan.own.push_back({static_cast<I32>(i), an.g_ptr[static_cast<std::size_t>(r)], an.g_ptr[static_cast<std::size_t>(r) + 1]});
                }
            }
            plan.tape = make_tape(*s->tree);
            an.most_nodes = std::max(an.most_nodes, plan.tape.size() * W);
            an.most_width = std::max(an.most_width, W);
            an.most_args = std::max(an.most_args, static_cast<std::size_t>(plan.tape.most_args));
            an.order.emplace_back(false, static_cast<I32>(an.statements.size()));
            an.statements.push_back(std::move(plan));
        }
    }
}

void plan_assembly(AnalyticPlan& an, const Builder& b, const Pattern& pattern, const std::vector<char>& br) {
    const auto& moving = b.slot_class;
    // Every row's slot is read through its gradient: one entry of the Jacobian per state the
    // slot depends on. `sign` and `idx` are per row, or empty.
    auto add_chain = [&](const std::vector<int>& rows, const std::vector<int>& slots, ChainTerm::Kind kind,
                         const std::vector<double>* sign, const std::vector<I32>* idx, I32 s1) {
        ChainTerm c;
        c.kind = kind;
        c.s1 = s1;
        std::size_t count = std::min(rows.size(), slots.size());
        for (std::size_t i = 0; i < count; i++) {
            int r = rows[i], x = slots[i];
            if (br[static_cast<std::size_t>(r)] || moving[static_cast<std::size_t>(x)] != 2 || an.row_of(x) < 0) continue;
            I32 g = an.row_of(x);
            std::size_t ncols = an.row_size(g);
            const I32* cols = an.row_cols(g);
            for (std::size_t q = 0; q < ncols; q++) {
                c.src.push_back(an.g_ptr[static_cast<std::size_t>(g)] + static_cast<I32>(q));
                c.dst.push_back(pat_pos(pattern, r, cols[q]));
                if (sign) c.sign.push_back((*sign)[i]);
                if (idx) c.idx.push_back((*idx)[i]);
            }
        }
        if (!c.src.empty()) an.chain.push_back(std::move(c));
    };
    auto as_i32 = [](const std::vector<int>& v) { return std::vector<I32>(v.begin(), v.end()); };
    for (const Phase& ph : b.phases) {
        switch (ph.kind) {
            case Phase::Kind::Transfers: {
                const std::vector<int>& tgt = ph.tgt;
                const std::vector<int>& flux = ph.a;
                std::vector<int> src_of(static_cast<std::size_t>(b.nflux), -1);
                for (std::size_t i = 0; i < b.flux_mbd.size(); i++) src_of[static_cast<std::size_t>(b.flux_mbd[i])] = b.flux_mbd_src[i];
                std::vector<int> rate(flux.size());
                std::vector<I32> src(flux.size());
                DirectTerm d{DirectTerm::Kind::XSign, {}, {}, {}, 0, 0};
                for (std::size_t i = 0; i < flux.size(); i++) {
                    src[i] = src_of[static_cast<std::size_t>(flux[i])];
                    rate[i] = b.flux_rate[static_cast<std::size_t>(flux[i])];
                    if (src[i] >= 0 && !br[static_cast<std::size_t>(tgt[i])]) {
                        d.pos.push_back(pat_pos(pattern, tgt[i], src[i]));
                        d.a.push_back(rate[i]);
                        d.f.push_back(ph.f[i]);
                    }
                }
                if (!d.pos.empty()) an.direct.push_back(std::move(d));
                // d/dX[rate] = sign * (y[src] if multiplying by the donor else 1)
                add_chain(tgt, rate, ChainTerm::Kind::SignDonor, &ph.f, &src, 0);
                break;
            }
            case Phase::Kind::X: add_chain(ph.tgt, ph.a, ChainTerm::Kind::Ones, nullptr, nullptr, 0); break;
            case Phase::Kind::Waste: {
                const std::vector<int>& p_idx = ph.tgt;
                const std::vector<int>& m_idx = ph.a;
                const std::vector<int>& r_idx = ph.b;
                const std::vector<int>& budget = ph.c;
                int h = ph.s1;
                DirectTerm lost{DirectTerm::Kind::NegXH, {}, {}, {}, h, 0};
                DirectTerm gained{DirectTerm::Kind::XH, {}, {}, {}, h, 0};
                for (int p : p_idx) lost.pos.push_back(pat_pos(pattern, p, p));
                for (std::size_t i = 0; i < std::min(m_idx.size(), p_idx.size()); i++) gained.pos.push_back(pat_pos(pattern, m_idx[i], p_idx[i]));
                an.direct.push_back(std::move(lost));
                an.direct.push_back(std::move(gained));
                std::vector<int> hs(p_idx.size(), h);
                std::vector<I32> of = as_i32(p_idx);
                add_chain(p_idx, hs, ChainTerm::Kind::NegY, nullptr, &of, 0);
                add_chain(m_idx, hs, ChainTerm::Kind::Y, nullptr, &of, 0);
                add_chain(m_idx, r_idx, ChainTerm::Kind::NegOne, nullptr, nullptr, 0);
                if (!budget.empty()) add_chain(budget, r_idx, ChainTerm::Kind::Ones, nullptr, nullptr, 0);
                break;
            }
            case Phase::Kind::Move: {
                const std::vector<int>& a_idx = ph.tgt;
                const std::vector<int>& second = ph.a;
                int lam_slot = ph.s1, share_slot = ph.s2;
                DirectTerm out{DirectTerm::Kind::NegXX, {}, {}, {}, lam_slot, share_slot};
                for (int r : a_idx) out.pos.push_back(pat_pos(pattern, r, r));
                an.direct.push_back(std::move(out));
                if (!second.empty()) {
                    DirectTerm in{DirectTerm::Kind::XX, {}, {}, {}, lam_slot, share_slot};
                    bool all_budget = true;
                    for (int r : second) all_budget = all_budget && br[static_cast<std::size_t>(r)];
                    if (!all_budget) {
                        for (std::size_t i = 0; i < second.size(); i++)
                            if (!br[static_cast<std::size_t>(second[i])]) in.pos.push_back(pat_pos(pattern, second[i], a_idx[i]));
                        an.direct.push_back(std::move(in));
                    }
                }
                std::vector<int> ls(a_idx.size(), lam_slot), ss(a_idx.size(), share_slot);
                std::vector<I32> of = as_i32(a_idx);
                add_chain(a_idx, ls, ChainTerm::Kind::NegXY, nullptr, &of, share_slot);
                add_chain(a_idx, ss, ChainTerm::Kind::NegXY, nullptr, &of, lam_slot);
                if (!second.empty()) {
                    add_chain(second, ls, ChainTerm::Kind::XY, nullptr, &of, share_slot);
                    add_chain(second, ss, ChainTerm::Kind::XY, nullptr, &of, lam_slot);
                }
                break;
            }
            case Phase::Kind::Mean: {
                std::vector<I32> recorders(ph.tgt.size());
                for (std::size_t i = 0; i < recorders.size(); i++) recorders[i] = ph.s1 + static_cast<I32>(i);
                add_chain(ph.tgt, ph.a, ChainTerm::Kind::Recording, nullptr, &recorders, 0);
                break;
            }
            case Phase::Kind::Coef: {
                DirectTerm d{DirectTerm::Kind::Const, {}, {}, {}, 0, 0};
                for (std::size_t i = 0; i < ph.tgt.size(); i++) {
                    if (br[static_cast<std::size_t>(ph.tgt[i])]) continue;
                    d.pos.push_back(pat_pos(pattern, ph.tgt[i], ph.a[i]));
                    d.f.push_back(ph.f[i]);
                }
                if (!d.pos.empty()) an.direct.push_back(std::move(d));
                break;
            }
            case Phase::Kind::Farf: {
                // A path's own terms, at its rows and columns: its values the path's own.
                const FarfieldPath& F = *b.FARF[static_cast<std::size_t>(ph.s1)];
                const std::vector<int>& rf = F.row_flat();
                const std::vector<int>& cf = F.col_flat();
                DirectTerm d{DirectTerm::Kind::Farf, {}, {}, {}, ph.s1, 0};
                d.pos.reserve(rf.size());
                for (std::size_t i = 0; i < rf.size(); i++) d.pos.push_back(pat_pos(pattern, rf[i], cf[i]));
                an.direct.push_back(std::move(d));
                // A setting that follows the state moves the matrix: each cell's rate through it --
                // the matrix's tangent along it times the state, as `jvp` has it in
                // src/sim/farfield.js -- chained along the setting's gradient.
                if (!F.laplace) {
                    const FarfPath& path = static_cast<const FarfPath&>(F);
                    std::vector<int> rows, slots;
                    std::vector<I32> parts, element;
                    for (int x : settings_moving(an, F, moving)) {
                        for (int slot = 0; slot < path.slots(); slot++) {
                            std::vector<int> mine = path.setting_slots_of(slot);
                            if (std::find(mine.begin(), mine.end(), x) == mine.end()) continue;
                            const I32 i = static_cast<I32>(parts.size() / 2);
                            parts.push_back(x);
                            parts.push_back(slot);
                            const int o = slot / path.nnuc, m = slot % path.nnuc;
                            for (int cell = 0; cell < path.ncells; cell++) {
                                rows.push_back(path.base + o * path.ncells * path.nnuc + cell * path.nnuc + m);
                                slots.push_back(x);
                                element.push_back(i * path.ncells + cell);
                            }
                        }
                    }
                    if (!parts.empty()) {
                        const std::size_t before = an.chain.size();
                        add_chain(rows, slots, ChainTerm::Kind::FarfSettings, nullptr, &element, ph.s1);
                        if (an.chain.size() > before) an.chain.back().parts = parts;
                    }
                }
                break;
            }
        }
    }
}

/// True when df/dy moves with neither the clock nor the state (`isConstant`); with `clock`
/// false, when it does not move with the state (the model is linear, its coefficients
/// perhaps moving in time).
bool is_constant(const Builder& b, bool clock) {
    for (const auto& r : b.recorders)
        if (r->mem >= 0) return false;
    for (const auto& p : b.farf_layout)
        if (p->farf && p->farf->laplace) return false;
    auto moves = [&](const EntryPtr& a) { return b.on_state.count(a->name) != 0 || (clock && b.on_clock.count(a->name) != 0); };
    std::unordered_set<std::string> paths;
    for (const auto& p : b.farf_layout)
        if (!(p->farf && p->farf->laplace)) paths.insert(p->name);
    for (const auto& W : b.waste_layout)
        if (b.on_clock.count(W->release_slot->name) == 0) paths.insert(W->q);
    // A transfer that only passes a path's (or the packages') release on reads nothing of its own.
    auto bare_release = [&](const EntryPtr& a) {
        if (paths.empty() || a->asts.empty()) return false;
        const Json& by_donor = a->block.is_object() ? a->block.get("multiply_by_donor") : a->block;
        if (!(by_donor.is_bool() && !by_donor.as_bool())) return false;
        for (const auto& ast : a->asts) {
            if (!ast || ast->kind != ENode::Kind::Ref) return false;
            const ERef& ref = as_ref(*ast);
            if (!(ref.by_list ? ref.named.empty() : ref.indices.empty())) return false;
            auto q = resolve_reference(ref.name, a->system, [&](const std::string& n) { return paths.count(n) != 0; });
            if (!q || paths.count(*q) == 0) return false;
        }
        return true;
    };
    std::vector<EntryPtr> rates;
    for (const char* collection : {"transfers", "inflows"}) {
        for (const Json& blk : b.project->blocks_of(collection)) {
            const Json& qname = blk.get("qname");
            const Json& name = qname.is_null() ? blk.get("name") : qname;
            if (!name.is_string()) continue;
            auto it = b.alg_by_name.find(name.as_string());
            if (it != b.alg_by_name.end() && !bare_release(it->second)) rates.push_back(it->second);
        }
    }
    rates.insert(rates.end(), b.dydt_slots.begin(), b.dydt_slots.end());
    for (const auto& p : b.farf_layout) {
        for (const auto& key : farf_equation_keys()) {
            auto it = b.alg_by_name.find(p->name + "#" + key);
            if (it != b.alg_by_name.end()) rates.push_back(it->second);
        }
    }
    for (const auto& W : b.waste_layout) {
        rates.push_back(W->hazard_slot);
        for (const char* key : {"irf", "degradation_rate"}) {
            const EntryPtr* slot = W->setting_at(key);
            if (!slot) throw std::logic_error("packages without a setting");
            rates.push_back(*slot);
        }
    }
    for (const auto& D : b.disruption_layout) {
        rates.push_back(D->lambda_slot);
        rates.insert(rates.end(), D->shares.begin(), D->shares.end());
    }
    for (const auto& a : rates)
        if (a && moves(a)) return false;
    return true;
}

std::shared_ptr<const AnalyticPlan> make_plan(System& sys, const Pattern& pattern, bool full) {
    const Builder& b = *sys.builder;
    auto plan = std::make_shared<AnalyticPlan>();
    AnalyticPlan& an = *plan;
    int n = sys.nstate;
    std::unordered_map<int, std::vector<int>> deps = state_dependencies(sys);
    if (b.has_derivative_stmts) {
        // Only the slots the derivative reads have a gradient worth working out.
        std::vector<char> kept(static_cast<std::size_t>(std::max(1, b.nalg)), 0);
        for (const auto& a : b.algebraic) {
            if (b.derivative_blocks.count(a->name) == 0 || a->width <= 0) continue;
            for (int k = a->base; k < a->base + a->width; k++) kept[static_cast<std::size_t>(k)] = 1;
        }
        for (auto it = deps.begin(); it != deps.end();) it = kept[static_cast<std::size_t>(it->first)] ? std::next(it) : deps.erase(it);
    }
    std::vector<int> g_rows;
    for (const auto& [slot, cols] : deps) g_rows.push_back(slot);
    std::sort(g_rows.begin(), g_rows.end());
    an.g_row_of.assign(static_cast<std::size_t>(std::max(1, b.nalg)), -1);
    an.g_ptr.assign(g_rows.size() + 1, 0);
    for (std::size_t k = 0; k < g_rows.size(); k++) {
        const std::vector<int>& cols = deps[g_rows[k]];
        an.g_row_of[static_cast<std::size_t>(g_rows[k])] = static_cast<I32>(k);
        an.g_col.insert(an.g_col.end(), cols.begin(), cols.end());
        an.g_ptr[k + 1] = static_cast<I32>(an.g_col.size());
    }
    an.g_nnz = an.g_col.size();
    std::vector<char> budget_rows(static_cast<std::size_t>(n), 0);
    if (b.budget && !full) {
        int from = b.budget->base, to = b.budget->base + static_cast<int>(b.budget->terms.size()) * b.budget->nfam;
        for (int r = from; r < to; r++) budget_rows[static_cast<std::size_t>(r)] = 1;
    }
    plan_statements(an, b);
    plan_assembly(an, b, pattern, budget_rows);
    an.constant = is_constant(b, true);
    an.state_free = an.constant || is_constant(b, false);
    return plan;
}

}  // namespace

/// A system's exact Jacobian: its plan, shared with every copy of the system, and the room
/// one evaluation works in, its own.
struct Analytic {
    System* sys = nullptr;
    std::shared_ptr<const AnalyticPlan> plan;
    Vec G;                       // the gradients of the slots that read the state
    Vec work;                    // the tape's values: every node at every element
    Vec factor;                  // an availability's own factor per element, then
    Vec d;                       // one leaf's tangent per element
    Vec products;
    Vec args;                    // one call's arguments
    std::vector<MaybeF> dargs;   // and their tangents
    Vec leafwork;                // (the walk's: one element's leaves)

    Analytic(System& system, std::shared_ptr<const AnalyticPlan> p) : sys(&system), plan(std::move(p)) {
        G.assign(plan->g_nnz, 0.0);
        work.assign(plan->most_nodes, 0.0);
        factor.assign(plan->most_width, 0.0);
        d.assign(plan->most_width, 0.0);
        products.assign(plan->most_products, 0.0);
        args.assign(plan->most_args, 0.0);
        dargs.assign(plan->most_args, NONE);
    }
};

namespace {

/// One statement's part of the gradients.
void statement_gradient(Analytic& an, const StatementPlan& plan, const Reads& rd) {
    double* G = an.G.data();
    std::size_t W = plan.width;
    const TangentTape& tp = plan.tape;
    std::size_t m = tp.size();
    double* nv = an.work.data();
    tape_values(nv, tp, W, rd, an.args.data());
    double* d = an.d.data();
    const double* base = nullptr;
    if (plan.multiply) {
        const double* factor = nv + (m - 1) * W;   // the root's values
        for (const auto& own : plan.own) {
            double f_i = factor[own.elem];
            for (I32 q = own.lo; q < own.hi; q++) G[q] *= f_i;
        }
        // The rate as it stood before the availability multiplied it in.
        double* was = an.factor.data();
        for (std::size_t i = 0; i < W; i++) was[i] = factor[i] != 0 ? rd.X[plan.outs[i]] / factor[i] : 0.0;
        base = was;
    }
    for (const auto& term : plan.y_terms) {
        if (!tape_tangent(d, tp, term.leaf, W, nv, *rd.tables, an.args.data(), an.dargs.data())) continue;
        if (base)
            for (std::size_t i = 0; i < W; i++) d[i] = d[i] * base[i];
        const I32* dst = term.dst.data();
        for (std::size_t i = 0; i < W; i++) G[dst[i]] += d[i];
    }
    for (const auto& term : plan.x_terms) {
        if (!tape_tangent(d, tp, term.leaf, W, nv, *rd.tables, an.args.data(), an.dargs.data())) continue;
        if (base)
            for (std::size_t i = 0; i < W; i++) d[i] = d[i] * base[i];
        // np.add.at(G, dst, d[elem] * G[src]): every product formed first, then added in order.
        // NOTE(speed): a statement that does not read its own slots (all but an availability's)
        // never reads an entry it adds to, and the two loops could be one.
        std::size_t count = term.elem.size();
        const I32* elem = term.elem.data();
        const I32* src = term.src.data();
        const I32* dst = term.dst.data();
        double* products = an.products.data();
        for (std::size_t q = 0; q < count; q++) products[q] = d[elem[q]] * G[src[q]];
        for (std::size_t q = 0; q < count; q++) G[dst[q]] += products[q];
    }
}

/// The same by the walk over the tree, an element and a leaf at a time (the check on the tape).
void statement_gradient_walked(Analytic& an, const StatementPlan& plan, const Reads& rd) {
    double* G = an.G.data();
    std::size_t W = plan.width;
    std::size_t nl = plan.leaves.size();
    if (an.leafwork.size() < nl * W) an.leafwork.resize(nl * W);
    double* vals = an.leafwork.data();
    for (std::size_t i = 0; i < W; i++)
        for (std::size_t p = 0; p < nl; p++) vals[i * nl + p] = leaf_value(*plan.leaves[p], i, rd);
    Tangent tg{rd.tables, nullptr, -1, 0};
    Vec base;
    if (plan.multiply) {
        Vec factor(W);
        for (std::size_t i = 0; i < W; i++) factor[i] = tangent_run(tg, *plan.tree, vals + i * nl, -1).first;
        for (const auto& own : plan.own)
            for (I32 q = own.lo; q < own.hi; q++) G[q] *= factor[static_cast<std::size_t>(own.elem)];
        base.resize(W);
        for (std::size_t i = 0; i < W; i++) base[i] = factor[i] != 0 ? rd.X[plan.outs[i]] / factor[i] : 0.0;
    }
    Vec d(W);
    auto tangents = [&](I32 leaf) {
        for (std::size_t i = 0; i < W; i++) {
            MaybeF di = tangent_run(tg, *plan.tree, vals + i * nl, leaf).second;
            if (!di.some) return false;
            d[i] = di.v;
        }
        if (!base.empty())
            for (std::size_t i = 0; i < W; i++) d[i] = d[i] * base[i];
        return true;
    };
    for (const auto& term : plan.y_terms) {
        if (!tangents(term.leaf)) continue;
        for (std::size_t i = 0; i < W; i++) G[term.dst[i]] += d[i];
    }
    for (const auto& term : plan.x_terms) {
        if (!tangents(term.leaf)) continue;
        Vec products(term.elem.size());
        for (std::size_t q = 0; q < products.size(); q++) products[q] = d[static_cast<std::size_t>(term.elem[q])] * G[term.src[q]];
        for (std::size_t q = 0; q < products.size(); q++) G[term.dst[q]] += products[q];
    }
}

/// The release of a semi-analytical path along the state (`releaseTangent`): the weight of each
/// source's current inflow times that inflow's gradient.
void laplace_gradient(Analytic& an, LaplaceFarfPath& F, const Reads& rd) {
    const std::vector<double>& cur = F.current_weights(rd.t);
    if (std::all_of(cur.begin(), cur.end(), [](double w) { return w == 0.0; })) return;
    const AnalyticPlan& P = *an.plan;
    double* G = an.G.data();
    const double* y = rd.y;
    const double* X = rd.X;
    int n = F.nnuc;
    const auto& moving = an.sys->builder->slot_class;
    for (int slot = 0; slot < F.nslots; slot++) {
        int out = F.release_slots_[static_cast<std::size_t>(slot)];
        I32 r_out = P.row_of(out);
        if (r_out < 0) continue;
        const I32* row_cols = P.row_cols(r_out);
        std::size_t width = P.row_size(r_out);
        if (width == 0) continue;
        auto place = [&](I32 c) { return static_cast<std::size_t>(std::lower_bound(row_cols, row_cols + width, c) - row_cols); };
        std::vector<double> acc(width, 0.0);
        int o = slot / n;
        for (int j = 0; j < n; j++) {
            double w = cur[static_cast<std::size_t>(slot * n + j)];
            if (w == 0) continue;
            for (const auto& [x, d] : F.terms_into[static_cast<std::size_t>(o * n + j)]) {
                double scale = w;
                if (d >= 0) {
                    acc[place(d)] += w * X[x];
                    scale = w * y[d];
                }
                I32 r = P.row_of(x);
                if (r >= 0 && moving[static_cast<std::size_t>(x)] == 2) {
                    const I32* cols = P.row_cols(r);
                    std::size_t count = P.row_size(r);
                    if (count > 0) {
                        I32 lo = P.g_ptr[static_cast<std::size_t>(r)];
                        for (std::size_t q = 0; q < count; q++) acc[place(cols[q])] += scale * G[lo + static_cast<I32>(q)];
                    }
                }
            }
        }
        I32 lo = P.g_ptr[static_cast<std::size_t>(r_out)];
        for (std::size_t q = 0; q < width; q++) G[lo + static_cast<I32>(q)] += acc[q];
    }
}

void special_gradient(Analytic& an, const SpecialPlan& plan, const Reads& rd) {
    double* G = an.G.data();
    switch (plan.kind) {
        case SpecialPlan::Kind::Laplace:
            laplace_gradient(an, static_cast<LaplaceFarfPath&>(*rd.sys->data.FARF[static_cast<std::size_t>(plan.path)]), rd);
            return;
        case SpecialPlan::Kind::Farfield: {
            // The path refreshed, its release weights added: the system's own path, so that a
            // copy of the system reads its own.
            FarfieldPath& F = *rd.sys->data.FARF[static_cast<std::size_t>(plan.path)];
            F.refresh(rd.X);
            const double* w = F.release_weights().data();
            const I32* pos = plan.pos.data();
            for (std::size_t q = 0; q < plan.pos.size(); q++) G[pos[q]] += w[q];
            // A setting that follows the state: the release's own tangent along it -- its
            // weights' tangent times the cells, as `releaseTangent` has it -- chained along the
            // setting's gradient.
            if (!plan.terms.empty()) {
                FarfPath& path = static_cast<FarfPath&>(F);
                for (const SpecialPlan::SettingTerm& term : plan.terms) {
                    FarfTangent T(path);
                    setting_partials(T, path, rd.X, rd.sys->X.size(), term.x);
                    for (const SpecialPlan::SettingPart& part : term.parts) {
                        const std::size_t off = static_cast<std::size_t>(part.slot) * static_cast<std::size_t>(path.nrel);
                        double dq = 0.0;
                        for (int r = 0; r < path.nrel; r++)
                            dq += T.drel[off + static_cast<std::size_t>(r)] * rd.y[path.rel_at[off + static_cast<std::size_t>(r)]];
                        for (std::size_t q = 0; q < part.pos.size(); q++) G[part.pos[q]] += dq * G[part.src[q]];
                    }
                }
            }
            return;
        }
        case SpecialPlan::Kind::Zero: return;
        case SpecialPlan::Kind::MinMax:
        case SpecialPlan::Kind::RunningMean: break;
    }
    const std::vector<Recorder>& mem = rd.sys->data.MEM;
    // (The slot's row and its target's are two rows: nothing added here is read here.)
    auto follow = [&](const SpecialPlan::Item& item) {
        const I32* pos = plan.pos.data() + item.pos;
        const double* from = G + item.src;
        for (I32 q = 0; q < item.count; q++) G[pos[q]] += from[q];
    };
    for (const auto& item : plan.items) {
        if (plan.kind == SpecialPlan::Kind::MinMax) {
            if (rd.X[item.out] == rd.X[item.tgt] && item.follows) follow(item);
        } else {
            double el = mem[static_cast<std::size_t>(item.mem)].elapsed_at(rd.t);
            if (el > 0) {
                G[item.own] += 1.0 / el;
            } else if (item.follows) {
                follow(item);
            }
        }
    }
}

void gradients(Analytic& an, const Reads& rd, bool walked) {
    std::fill(an.G.begin(), an.G.end(), 0.0);
    const AnalyticPlan& plan = *an.plan;
    for (const auto& [special, which] : plan.order) {
        if (special) special_gradient(an, plan.specials[static_cast<std::size_t>(which)], rd);
        else if (walked) statement_gradient_walked(an, plan.statements[static_cast<std::size_t>(which)], rd);
        else statement_gradient(an, plan.statements[static_cast<std::size_t>(which)], rd);
    }
}

/// A chain term into `J`: each element's coefficient times the gradient it scales.
void chain_add(double* J, const ChainTerm& c, const double* G, const System& sys, const double* y, const double* X) {
    std::size_t count = c.dst.size();
    const I32* dst = c.dst.data();
    const I32* src = c.src.data();
    const I32* idx = c.idx.data();
    switch (c.kind) {
        case ChainTerm::Kind::FarfSettings: {
            // Each cell's rate along the setting, worked out once for every element.
            FarfPath& path = static_cast<FarfPath&>(*sys.data.FARF[static_cast<std::size_t>(c.s1)]);
            std::vector<double> rate = settings_rates(path, c.parts, y, X, sys.X.size());
            for (std::size_t q = 0; q < count; q++) J[dst[q]] += rate[static_cast<std::size_t>(idx[q])] * G[src[q]];
            break;
        }
        case ChainTerm::Kind::SignDonor: {
            const double* sign = c.sign.data();
            for (std::size_t q = 0; q < count; q++) J[dst[q]] += (idx[q] >= 0 ? sign[q] * y[idx[q]] : sign[q]) * G[src[q]];
            break;
        }
        case ChainTerm::Kind::Ones:
            for (std::size_t q = 0; q < count; q++) J[dst[q]] += G[src[q]];
            break;
        case ChainTerm::Kind::NegOne:
            for (std::size_t q = 0; q < count; q++) J[dst[q]] += -G[src[q]];
            break;
        case ChainTerm::Kind::NegY:
            for (std::size_t q = 0; q < count; q++) J[dst[q]] += -y[idx[q]] * G[src[q]];
            break;
        case ChainTerm::Kind::Y:
            for (std::size_t q = 0; q < count; q++) J[dst[q]] += y[idx[q]] * G[src[q]];
            break;
        case ChainTerm::Kind::NegXY: {
            double x = X[c.s1];
            for (std::size_t q = 0; q < count; q++) J[dst[q]] += -(x * y[idx[q]]) * G[src[q]];
            break;
        }
        case ChainTerm::Kind::XY: {
            double x = X[c.s1];
            for (std::size_t q = 0; q < count; q++) J[dst[q]] += x * y[idx[q]] * G[src[q]];
            break;
        }
        case ChainTerm::Kind::Recording: {
            const std::vector<Recorder>& mem = sys.data.MEM;
            for (std::size_t q = 0; q < count; q++) J[dst[q]] += (mem[static_cast<std::size_t>(idx[q])].recording ? 1.0 : 0.0) * G[src[q]];
            break;
        }
    }
}

bool evaluate(Vec& Jv, Analytic& an, double t, const Vec& yv, bool walked) {
    System& sys = *an.sys;
    const AnalyticPlan& plan = *an.plan;
    const double* y = yv.data();
    sys.evaluate_for_derivative(t, y);
    const double* X = sys.X.data();
    if (plan.g_nnz > 0) {
        Reads rd{y, X, sys.P.data(), t, &sys, &sys.data.TAB};
        gradients(an, rd, walked);
    }
    const double* G = an.G.data();
    std::fill(Jv.begin(), Jv.end(), 0.0);
    double* J = Jv.data();
    for (const DirectTerm& d : plan.direct) {
        const I32* pos = d.pos.data();
        std::size_t count = d.pos.size();
        switch (d.kind) {
            case DirectTerm::Kind::XSign: {
                const I32* a = d.a.data();
                const double* f = d.f.data();
                for (std::size_t q = 0; q < count; q++) J[pos[q]] += f[q] * X[a[q]];
                break;
            }
            case DirectTerm::Kind::NegXH: {
                double v = -X[d.s1];
                for (std::size_t q = 0; q < count; q++) J[pos[q]] += v;
                break;
            }
            case DirectTerm::Kind::XH: {
                double v = X[d.s1];
                for (std::size_t q = 0; q < count; q++) J[pos[q]] += v;
                break;
            }
            case DirectTerm::Kind::NegXX: {
                double v = -(X[d.s1] * X[d.s2]);
                for (std::size_t q = 0; q < count; q++) J[pos[q]] += v;
                break;
            }
            case DirectTerm::Kind::XX: {
                double v = X[d.s1] * X[d.s2];
                for (std::size_t q = 0; q < count; q++) J[pos[q]] += v;
                break;
            }
            case DirectTerm::Kind::Const: {
                const double* f = d.f.data();
                for (std::size_t q = 0; q < count; q++) J[pos[q]] += f[q];
                break;
            }
            case DirectTerm::Kind::Farf: {
                // The path refreshed at X, its own values added at its entries.
                FarfieldPath& F = *sys.data.FARF[static_cast<std::size_t>(d.s1)];
                F.refresh(X);
                const double* vals = F.values().data();
                for (std::size_t q = 0; q < count; q++) J[pos[q]] += vals[q];
                break;
            }
        }
    }
    for (const ChainTerm& c : plan.chain) chain_add(J, c, G, sys, y, X);
    for (double v : Jv)
        if (!std::isfinite(v)) return false;
    return true;
}

}  // namespace

std::shared_ptr<Analytic> make_analytic(System& sys, const Pattern& pattern, bool full) {
    return std::make_shared<Analytic>(sys, make_plan(sys, pattern, full));
}

bool analytic_evaluate(Vec& J, Analytic& an, double t, const Vec& y) { return evaluate(J, an, t, y, false); }
bool analytic_evaluate_walked(Vec& J, Analytic& an, double t, const Vec& y) { return evaluate(J, an, t, y, true); }

bool analytic_constant(const Analytic& an) { return an.plan->constant; }
bool analytic_state_free(const Analytic& an) { return an.plan->state_free; }

std::shared_ptr<Analytic> clone_analytic(const std::shared_ptr<Analytic>& an, System& sys) {
    if (!an) return an;
    return std::make_shared<Analytic>(sys, an->plan);
}

const System* analytic_system(const Analytic& an) { return an.sys; }
std::size_t analytic_gradient_rows(const Analytic& an) { return an.plan->g_ptr.size() - 1; }
std::size_t analytic_gradient_entries(const Analytic& an) { return an.plan->g_nnz; }
const Vec& analytic_gradients(const Analytic& an) { return an.G; }

TreeTangent tree_tangent(const TNode& tree, const std::vector<std::shared_ptr<LookupTable>>& tables, const double* values, int seed) {
    Tangent tg{&tables, values, seed, 0};
    auto [value, d] = tangent_run(tg, tree, values, seed);
    return TreeTangent{value, d.some, d.v};
}

void check_tree_differentiable(const TNode& tree, const std::vector<char>& live) {
    std::size_t pos = 0;
    check_differentiable(tree, live, pos);
}

}  // namespace kompartment
