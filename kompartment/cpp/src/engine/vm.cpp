#include "engine/vm.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

#include "engine/farfield.hpp"
#include "lang/functions.hpp"

namespace kompartment {

namespace {

constexpr int BLOCK = 256;   // elements worked out at a time: a statement's registers stay in the first cache

enum Op : std::uint8_t {
    LOAD, NEG, ADD, SUB, MUL, DIV, LT, LE, GT, GE, EQ, NE, AND, OR,
    POW_SQ, POW_SQRT, POW_RECIP, POW_C, POW_JS, POW_JS1,
    SELECT, CALL1, CALL2, CALL3, CALLN, TAB
};

inline const double* array_of(const EvalContext& ctx, std::uint8_t which) {
    switch (which) {
        case 0: return ctx.y;
        case 1: return ctx.P;
        case 2: return ctx.X;
        default: return ctx.D->DIS.data();
    }
}

std::uint8_t array_code(LeafKind k) {
    switch (k) {
        case LeafKind::Y: return 0;
        case LeafKind::P: return 1;
        case LeafKind::X: return 2;
        case LeafKind::DIS: return 3;
        default: throw std::logic_error(std::string("A ") + leaf_kind_name(k) + " leaf is not a value");
    }
}

// Whether a subtree holds something that can refuse its arguments: where one stands in a
// conditional's branch, the branch not taken must not be worked out.
bool may_refuse(const TNode& t) {
    switch (t.kind) {
        case TNode::Kind::Leaf: return false;
        case TNode::Kind::Neg: return may_refuse(*as_neg(t).a);
        case TNode::Kind::Bin: return may_refuse(*as_bin(t).a) || may_refuse(*as_bin(t).b);
        case TNode::Kind::Cond: return may_refuse(*as_tcond(t).test) || may_refuse(*as_tcond(t).a) || may_refuse(*as_tcond(t).b);
        case TNode::Kind::Call: {
            Fn fn = as_tcall(t).fn;
            if (fn == Fn::TransportPoint || fn == Fn::TransportSum || fn == Fn::TransportMean || fn == Fn::InterpolationUseEndValues ||
                fn == Fn::InterpolationExtrapolation)
                return true;
            for (const auto& a : as_tcall(t).args)
                if (may_refuse(*a)) return true;
            return false;
        }
        case TNode::Kind::Tab: return may_refuse(*as_tab(t).arg);
    }
    return false;
}

bool guards_a_refusal(const TNode& t) {
    switch (t.kind) {
        case TNode::Kind::Leaf: return false;
        case TNode::Kind::Neg: return guards_a_refusal(*as_neg(t).a);
        case TNode::Kind::Bin: return guards_a_refusal(*as_bin(t).a) || guards_a_refusal(*as_bin(t).b);
        case TNode::Kind::Cond:
            return may_refuse(*as_tcond(t).a) || may_refuse(*as_tcond(t).b) || guards_a_refusal(*as_tcond(t).test);
        case TNode::Kind::Call:
            for (const auto& a : as_tcall(t).args)
                if (guards_a_refusal(*a)) return true;
            return false;
        case TNode::Kind::Tab: return guards_a_refusal(*as_tab(t).arg);
    }
    return false;
}

inline double unary(Fn fn, double a) {
    switch (fn) {
        case Fn::Abs: return kf_abs(a);
        case Fn::Sqrt: return kf_sqrt(a);
        case Fn::Exp: return kf_exp(a);
        case Fn::Log: return kf_log(a);
        case Fn::Log10: return kf_log10(a);
        case Fn::Log2: return kf_log2(a);
        case Fn::Ceil: return kf_ceil(a);
        case Fn::Floor: return kf_floor(a);
        case Fn::Round: return kf_round(a);
        case Fn::Fix: return kf_fix(a);
        case Fn::Sign: return kf_sign(a);
        case Fn::Ulp: return kf_ulp(a);
        case Fn::Factorial: return kf_factorial(a);
        case Fn::Erf: return kf_erf(a);
        case Fn::Erfc: return kf_erfc(a);
        case Fn::Sin: return kf_sin(a);
        case Fn::Cos: return kf_cos(a);
        case Fn::Tan: return kf_tan(a);
        case Fn::Asin: return kf_asin(a);
        case Fn::Acos: return kf_acos(a);
        case Fn::Atan: return kf_atan(a);
        case Fn::Sinh: return kf_sinh(a);
        case Fn::Cosh: return kf_cosh(a);
        case Fn::Tanh: return kf_tanh(a);
        case Fn::Asinh: return kf_asinh(a);
        case Fn::Acosh: return kf_acosh(a);
        case Fn::Atanh: return kf_atanh(a);
        case Fn::Not: return kf_not(a);
        default: throw std::logic_error("not a function of one argument");
    }
}

inline double binary(Fn fn, double a, double b) {
    switch (fn) {
        case Fn::Hypot: return kf_hypot(a, b);
        case Fn::Mod: return kf_mod(a, b);
        case Fn::Rem: return kf_rem(a, b);
        case Fn::Binomial: return kf_binomial(a, b);
        case Fn::Atan2: return kf_atan2(a, b);
        case Fn::Bq2Mole: return kf_bq2mole(a, b);
        case Fn::Mole2Bq: return kf_mole2bq(a, b);
        default: throw std::logic_error("not a function of two arguments");
    }
}

inline double ternary(Fn fn, double a, double b, double c, bool one) {
    switch (fn) {
        case Fn::RampDown: return kf_ramp_down(a, b, c);
        case Fn::RampUp: return kf_ramp_up(a, b, c);
        case Fn::SmoothDown: return kf_smooth_down(a, b, c, one);
        case Fn::SmoothUp: return kf_smooth_up(a, b, c, one);
        default: throw std::logic_error("not a function of three arguments");
    }
}

int arity_class(Fn fn) {
    switch (fn) {
        case Fn::Abs: case Fn::Sqrt: case Fn::Exp: case Fn::Log: case Fn::Log10: case Fn::Log2: case Fn::Ceil: case Fn::Floor:
        case Fn::Round: case Fn::Fix: case Fn::Sign: case Fn::Ulp: case Fn::Factorial: case Fn::Erf: case Fn::Erfc: case Fn::Sin:
        case Fn::Cos: case Fn::Tan: case Fn::Asin: case Fn::Acos: case Fn::Atan: case Fn::Sinh: case Fn::Cosh: case Fn::Tanh:
        case Fn::Asinh: case Fn::Acosh: case Fn::Atanh: case Fn::Not:
            return 1;
        case Fn::Hypot: case Fn::Mod: case Fn::Rem: case Fn::Binomial: case Fn::Atan2: case Fn::Bq2Mole: case Fn::Mole2Bq:
            return 2;
        case Fn::RampDown: case Fn::RampUp: case Fn::SmoothDown: case Fn::SmoothUp:
            return 3;
        default: return 0;   // as many as given
    }
}

}  // namespace

// --- one element, by walking the tree ------------------------------------------------------------------

double eval_tree(const TNode& tree, std::size_t k, const EvalContext& ctx) {
    switch (tree.kind) {
        case TNode::Kind::Leaf: {
            const TLeaf& l = as_leaf(tree);
            switch (l.leaf) {
                case LeafKind::K: return l.value_at(k);
                case LeafKind::T: return ctx.t;
                case LeafKind::T0: return ctx.D->T0;
                case LeafKind::T1: return ctx.D->T1;
                default: return array_of(ctx, array_code(l.leaf))[l.index_at(k)];
            }
        }
        case TNode::Kind::Neg: return -eval_tree(*as_neg(tree).a, k, ctx);
        case TNode::Kind::Bin: {
            const TBin& b = as_bin(tree);
            double x = eval_tree(*b.a, k, ctx);
            double y = eval_tree(*b.b, k, ctx);
            return apply_binary(b.op, x, y, b.op == BinOp::Pow ? scalar_subtree(*b.b) : true);
        }
        case TNode::Kind::Cond: {
            const TCond& c = as_tcond(tree);
            return eval_tree(*c.test, k, ctx) != 0.0 ? eval_tree(*c.a, k, ctx) : eval_tree(*c.b, k, ctx);
        }
        case TNode::Kind::Call: {
            const TCall& c = as_tcall(tree);
            double small[16];
            std::vector<double> big;
            double* args = small;
            if (c.args.size() > 16) {
                big.resize(c.args.size());
                args = big.data();
            }
            for (std::size_t i = 0; i < c.args.size(); i++) args[i] = eval_tree(*c.args[i], k, ctx);
            if (c.fn == Fn::Power) return scalar_subtree(*c.args[1]) ? kf_jspow1(args[0], args[1]) : kf_jspow(args[0], args[1]);
            if (c.fn == Fn::SmoothDown || c.fn == Fn::SmoothUp) return ternary(c.fn, args[0], args[1], args[2], scalar_subtree(*c.args[2]));
            return call_value(c.fn, args, c.args.size());
        }
        case TNode::Kind::Tab: {
            const TTab& tab = as_tab(tree);
            double arg = eval_tree(*tab.arg, k, ctx);
            return table_at(*ctx.D->TAB[static_cast<std::size_t>(tab.leaf->index_at(k))], arg);
        }
    }
    throw std::logic_error("Cannot evaluate this node");
}

// --- compiling ---------------------------------------------------------------------------------------------

struct ProgramCompiler {
    Program& p;
    std::int32_t used = 0, most = 0;
    std::vector<std::int32_t> free_list;

    using Operand = Program::Operand;
    using Instr = Program::Instr;

    std::int32_t take() {
        if (!free_list.empty()) {
            std::int32_t r = free_list.back();
            free_list.pop_back();
            return r;
        }
        most = std::max(most, used + 1);
        return used++;
    }
    void give(const Operand& o) {
        if (o.kind == Operand::Reg) free_list.push_back(o.index);
    }
    Operand reg(std::int32_t r) {
        Operand o;
        o.kind = Operand::Reg;
        o.index = r;
        return o;
    }
    Operand constant(double v) {
        Operand o;
        o.kind = Operand::Const;
        o.index = static_cast<std::int32_t>(p.consts_.size());
        p.consts_.push_back(v);
        return o;
    }
    std::int32_t ints(const std::vector<int>& v) {
        std::int32_t at = static_cast<std::int32_t>(p.ints_.size());
        p.ints_.insert(p.ints_.end(), v.begin(), v.end());
        return at;
    }
    static bool is_run(const std::vector<int>& v) {
        for (std::size_t i = 1; i < v.size(); i++)
            if (v[i] != v[0] + static_cast<int>(i)) return false;
        return !v.empty();
    }
    Operand emit(Instr in) {
        in.dst = take();
        p.code_.push_back(in);
        return reg(in.dst);
    }

    Operand leaf(const TLeaf& l) {
        Operand o;
        switch (l.leaf) {
            case LeafKind::K:
                if (!l.values) return constant(l.value);
                o.kind = Operand::Vec;
                o.index = static_cast<std::int32_t>(p.vecs_.size());
                p.vecs_.insert(p.vecs_.end(), l.values->begin(), l.values->end());
                return o;
            case LeafKind::T: o.kind = Operand::T; return o;
            case LeafKind::T0: o.kind = Operand::T0; return o;
            case LeafKind::T1: o.kind = Operand::T1; return o;
            default: break;
        }
        o.array = array_code(l.leaf);
        if (!l.indices) {
            o.kind = Operand::Scalar;
            o.index = l.index;
            return o;
        }
        if (is_run(*l.indices)) {
            o.kind = Operand::Run;
            o.index = (*l.indices)[0];
            return o;
        }
        Instr in;
        in.op = LOAD;
        in.a.array = o.array;
        in.ints = ints(*l.indices);
        return emit(in);
    }

    Operand power(const TNode& exponent, Operand a, Operand b) {
        bool one = scalar_subtree(exponent);
        Instr in;
        in.a = a;
        in.b = b;
        in.op = one ? POW_JS1 : POW_JS;
        if (exponent.kind == TNode::Kind::Leaf && as_leaf(exponent).leaf == LeafKind::K) {
            const TLeaf& l = as_leaf(exponent);
            bool finite = true;
            if (l.values) {
                for (double v : *l.values) finite = finite && std::isfinite(v);
            } else {
                finite = std::isfinite(l.value);
            }
            if (finite) {
                if (!one) in.op = POW_C;
                else if (l.value == 2.0) in.op = POW_SQ;
                else if (l.value == 0.5) in.op = POW_SQRT;
                else if (l.value == -1.0) in.op = POW_RECIP;
                else in.op = POW_C;
            }
        }
        give(a);
        give(b);
        return emit(in);
    }

    Operand compile(const TNode& t) {
        switch (t.kind) {
            case TNode::Kind::Leaf: return leaf(as_leaf(t));
            case TNode::Kind::Neg: {
                Instr in;
                in.op = NEG;
                in.a = compile(*as_neg(t).a);
                give(in.a);
                return emit(in);
            }
            case TNode::Kind::Bin: {
                const TBin& b = as_bin(t);
                Operand x = compile(*b.a);
                Operand y = compile(*b.b);
                if (b.op == BinOp::Pow) return power(*b.b, x, y);
                Instr in;
                static const Op ops[] = {ADD, SUB, MUL, DIV, POW_C, LT, LE, GT, GE, EQ, NE, AND, OR};
                in.op = ops[static_cast<int>(b.op)];
                in.a = x;
                in.b = y;
                give(x);
                give(y);
                return emit(in);
            }
            case TNode::Kind::Cond: {
                const TCond& c = as_tcond(t);
                Instr in;
                in.op = SELECT;
                in.a = compile(*c.test);
                in.b = compile(*c.a);
                in.c = compile(*c.b);
                give(in.a);
                give(in.b);
                give(in.c);
                return emit(in);
            }
            case TNode::Kind::Call: {
                const TCall& c = as_tcall(t);
                std::vector<Operand> args;
                for (const auto& a : c.args) args.push_back(compile(*a));
                if (c.fn == Fn::Power) return power(*c.args[1], args[0], args[1]);
                Instr in;
                in.fn = static_cast<std::uint8_t>(c.fn);
                int cls = arity_class(c.fn);
                if (cls == 1) {
                    in.op = CALL1;
                    in.a = args[0];
                } else if (cls == 2) {
                    in.op = CALL2;
                    in.a = args[0];
                    in.b = args[1];
                } else if (cls == 3) {
                    in.op = CALL3;
                    in.a = args[0];
                    in.b = args[1];
                    in.c = args[2];
                    in.flag = scalar_subtree(*c.args[2]) ? 1 : 0;
                } else {
                    // Folded an argument at a time: its register is none of its arguments'.
                    in.op = CALLN;
                    in.args = static_cast<std::int32_t>(p.args_.size());
                    in.nargs = static_cast<std::int32_t>(args.size());
                    p.args_.insert(p.args_.end(), args.begin(), args.end());
                    Operand out = emit(in);
                    for (const auto& a : args) give(a);
                    return out;
                }
                for (const auto& a : args) give(a);
                return emit(in);
            }
            case TNode::Kind::Tab: {
                const TTab& tab = as_tab(t);
                Instr in;
                in.op = TAB;
                in.a = compile(*tab.arg);
                if (tab.leaf->indices) {
                    in.flag = 1;
                    in.ints = ints(*tab.leaf->indices);
                } else {
                    in.ints = tab.leaf->index;
                }
                give(in.a);
                return emit(in);
            }
        }
        throw std::logic_error("Cannot compile this node");
    }

    void statement(const Stmt& s) {
        Program::Compiled c;
        c.special = s.special;
        if (s.special) {
            p.stmts_.push_back(std::move(c));
            return;
        }
        c.width = std::max(s.width, 1);
        c.array = s.array == Stmt::Array::Y0 ? 0 : 2;
        c.multiply = s.multiply;
        if (!s.outs) {
            c.out_kind = 0;
            c.out = s.out;
        } else if (is_run(*s.outs)) {
            c.out_kind = 1;
            c.out = (*s.outs)[0];
        } else {
            c.out_kind = 2;
            c.out = ints(*s.outs);
        }
        p.elements_ += static_cast<std::size_t>(c.width);
        if (guards_a_refusal(*s.tree)) {
            c.lazy = s.tree;
            p.stmts_.push_back(std::move(c));
            return;
        }
        used = 0;
        free_list.clear();
        c.first = static_cast<std::int32_t>(p.code_.size());
        c.result = compile(*s.tree);
        c.count = static_cast<std::int32_t>(p.code_.size()) - c.first;
        p.most_registers_ = std::max(p.most_registers_, most);
        p.stmts_.push_back(std::move(c));
    }
};

Program::Program(const std::vector<std::shared_ptr<Stmt>>& statements) {
    ProgramCompiler compiler{*this, 0, 0, {}};
    for (const auto& s : statements) compiler.statement(*s);
}

// --- running -----------------------------------------------------------------------------------------------

namespace {

struct Src {
    const double* p;
    int step;   // 0: one value for every element
};

template <class F>
inline void map1(double* d, Src a, int n, F f) {
    if (a.step) {
        for (int k = 0; k < n; k++) d[k] = f(a.p[k]);
    } else {
        double v = f(*a.p);
        for (int k = 0; k < n; k++) d[k] = v;
    }
}

template <class F>
inline void map2(double* d, Src a, Src b, int n, F f) {
    if (a.step && b.step) {
        for (int k = 0; k < n; k++) d[k] = f(a.p[k], b.p[k]);
    } else if (a.step) {
        double y = *b.p;
        for (int k = 0; k < n; k++) d[k] = f(a.p[k], y);
    } else if (b.step) {
        double x = *a.p;
        for (int k = 0; k < n; k++) d[k] = f(x, b.p[k]);
    } else {
        double v = f(*a.p, *b.p);
        for (int k = 0; k < n; k++) d[k] = v;
    }
}

void run_special(const Special& sp, EvalContext& ctx) {
    double* X = ctx.X;
    std::vector<Recorder>& mem = ctx.D->MEM;
    std::size_t n = sp.out.size();
    switch (sp.kind) {
        case Special::Kind::FarfieldRelease:
            ctx.D->FARF[static_cast<std::size_t>(sp.index)]->release(ctx.y, X, ctx.t);
            return;
        case Special::Kind::Snapshot:
            for (std::size_t k = 0; k < n; k++) X[sp.out[k]] = mem[static_cast<std::size_t>(sp.mem[k])].held(ctx.t);
            return;
        case Special::Kind::MinMax:
            for (std::size_t k = 0; k < n; k++) X[sp.out[k]] = mem[static_cast<std::size_t>(sp.mem[k])].extreme(ctx.t, X[sp.arg[k]]);
            return;
        case Special::Kind::Delay:
            for (std::size_t k = 0; k < n; k++) X[sp.out[k]] = mem[static_cast<std::size_t>(sp.mem[k])].delayed(ctx.t, X[sp.arg[k]]);
            return;
        case Special::Kind::RunningMean:
            for (std::size_t k = 0; k < n; k++)
                X[sp.out[k]] = mem[static_cast<std::size_t>(sp.mem[k])].mean_of(ctx.t, ctx.y[sp.state[k]], X[sp.arg[k]]);
            return;
    }
}

}  // namespace

void Program::run(EvalContext& ctx, std::vector<double>& work) const {
    if (work.size() < static_cast<std::size_t>(most_registers_) * BLOCK) work.resize(static_cast<std::size_t>(most_registers_) * BLOCK);
    double* regs = work.data();
    const double* consts = consts_.data();
    const double* vecs = vecs_.data();
    const std::int32_t* ints = ints_.data();
    const double t0 = ctx.D->T0, t1 = ctx.D->T1;
    int off = 0;
    auto src = [&](const Operand& o) -> Src {
        switch (o.kind) {
            case Operand::Const: return {consts + o.index, 0};
            case Operand::Vec: return {vecs + o.index + off, 1};
            case Operand::T: return {&ctx.t, 0};
            case Operand::T0: return {&t0, 0};
            case Operand::T1: return {&t1, 0};
            case Operand::Scalar: return {array_of(ctx, o.array) + o.index, 0};
            case Operand::Run: return {array_of(ctx, o.array) + o.index + off, 1};
            default: return {regs + static_cast<std::size_t>(o.index) * BLOCK, 1};
        }
    };
    for (const Compiled& s : stmts_) {
        if (s.special) {
            run_special(*s.special, ctx);
            continue;
        }
        double* out = s.array == 0 ? ctx.y : ctx.X;
        if (s.lazy) {
            for (int k = 0; k < s.width; k++) {
                double v = eval_tree(*s.lazy, static_cast<std::size_t>(k), ctx);
                int o = s.out_kind == 0 ? s.out : s.out_kind == 1 ? s.out + k : ints[s.out + k];
                out[o] = s.multiply ? out[o] * v : v;
            }
            continue;
        }
        const Instr* code = code_.data() + s.first;
        for (off = 0; off < s.width; off += BLOCK) {
            int n = std::min(BLOCK, s.width - off);
            for (int i = 0; i < s.count; i++) {
                const Instr& in = code[i];
                double* d = regs + static_cast<std::size_t>(in.dst) * BLOCK;
                switch (in.op) {
                    case LOAD: {
                        const double* a = array_of(ctx, in.a.array);
                        const std::int32_t* idx = ints + in.ints + off;
                        for (int k = 0; k < n; k++) d[k] = a[idx[k]];
                        break;
                    }
                    case NEG: map1(d, src(in.a), n, [](double x) { return -x; }); break;
                    case ADD: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return x + y; }); break;
                    case SUB: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return x - y; }); break;
                    case MUL: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return x * y; }); break;
                    case DIV: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return x / y; }); break;
                    case LT: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return x < y ? 1.0 : 0.0; }); break;
                    case LE: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return x <= y ? 1.0 : 0.0; }); break;
                    case GT: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return x > y ? 1.0 : 0.0; }); break;
                    case GE: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return x >= y ? 1.0 : 0.0; }); break;
                    case EQ: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return x == y ? 1.0 : 0.0; }); break;
                    case NE: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return x != y ? 1.0 : 0.0; }); break;
                    case AND: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return ((x != 0.0) & (y != 0.0)) ? 1.0 : 0.0; }); break;
                    case OR: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return ((x != 0.0) | (y != 0.0)) ? 1.0 : 0.0; }); break;
                    case POW_SQ: map1(d, src(in.a), n, [](double x) { return x * x; }); break;
                    case POW_SQRT: map1(d, src(in.a), n, [](double x) { return kf_sqrt(x); }); break;
                    case POW_RECIP: map1(d, src(in.a), n, [](double x) { return 1.0 / x; }); break;
                    case POW_C: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return cpow(x, y); }); break;
                    case POW_JS: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return kf_jspow(x, y); }); break;
                    case POW_JS1: map2(d, src(in.a), src(in.b), n, [](double x, double y) { return kf_jspow1(x, y); }); break;
                    case SELECT: {
                        Src c = src(in.a), a = src(in.b), b = src(in.c);
                        for (int k = 0; k < n; k++) d[k] = c.p[k * c.step] != 0.0 ? a.p[k * a.step] : b.p[k * b.step];
                        break;
                    }
                    case CALL1: {
                        Fn fn = static_cast<Fn>(in.fn);
                        switch (fn) {
                            case Fn::Exp: map1(d, src(in.a), n, [](double x) { return std::exp(x); }); break;
                            case Fn::Log: map1(d, src(in.a), n, [](double x) { return std::log(x); }); break;
                            case Fn::Sqrt: map1(d, src(in.a), n, [](double x) { return kf_sqrt(x); }); break;
                            case Fn::Abs: map1(d, src(in.a), n, [](double x) { return std::fabs(x); }); break;
                            default: map1(d, src(in.a), n, [fn](double x) { return unary(fn, x); });
                        }
                        break;
                    }
                    case CALL2: {
                        Fn fn = static_cast<Fn>(in.fn);
                        map2(d, src(in.a), src(in.b), n, [fn](double x, double y) { return binary(fn, x, y); });
                        break;
                    }
                    case CALL3: {
                        Fn fn = static_cast<Fn>(in.fn);
                        bool one = in.flag != 0;
                        Src a = src(in.a), b = src(in.b), c = src(in.c);
                        for (int k = 0; k < n; k++) d[k] = ternary(fn, a.p[k * a.step], b.p[k * b.step], c.p[k * c.step], one);
                        break;
                    }
                    case CALLN: {
                        Fn fn = static_cast<Fn>(in.fn);
                        const Operand* ops = args_.data() + in.args;
                        int m = in.nargs;
                        if (fn == Fn::Min || fn == Fn::Max || fn == Fn::Sum || fn == Fn::Prod || fn == Fn::Mean) {
                            // Folded from the left, an argument at a time over the block.
                            Src first = src(ops[0]);
                            for (int k = 0; k < n; k++) d[k] = first.p[k * first.step];
                            for (int j = 1; j < m; j++) {
                                Src a = src(ops[j]);
                                switch (fn) {
                                    case Fn::Min: for (int k = 0; k < n; k++) d[k] = kf_min(d[k], a.p[k * a.step]); break;
                                    case Fn::Max: for (int k = 0; k < n; k++) d[k] = kf_max(d[k], a.p[k * a.step]); break;
                                    case Fn::Prod: for (int k = 0; k < n; k++) d[k] = d[k] * a.p[k * a.step]; break;
                                    default: for (int k = 0; k < n; k++) d[k] = d[k] + a.p[k * a.step]; break;
                                }
                            }
                            if (fn == Fn::Mean) {
                                double count = static_cast<double>(m);
                                for (int k = 0; k < n; k++) d[k] = d[k] / count;
                            }
                            break;
                        }
                        double small[32];
                        std::vector<double> big;
                        double* buf = small;
                        if (m > 32) {
                            big.resize(static_cast<std::size_t>(m));
                            buf = big.data();
                        }
                        Src small_src[32];
                        std::vector<Src> big_src;
                        Src* srcs = small_src;
                        if (m > 32) {
                            big_src.resize(static_cast<std::size_t>(m));
                            srcs = big_src.data();
                        }
                        for (int j = 0; j < m; j++) srcs[j] = src(ops[j]);
                        // The destination may be one of the arguments' registers: an element's
                        // arguments are all read before its value is written.
                        for (int k = 0; k < n; k++) {
                            for (int j = 0; j < m; j++) buf[j] = srcs[j].p[k * srcs[j].step];
                            d[k] = call_value(fn, buf, static_cast<std::size_t>(m));
                        }
                        break;
                    }
                    case TAB: {
                        Src a = src(in.a);
                        const auto& tabs = ctx.D->TAB;
                        if (in.flag) {
                            const std::int32_t* idx = ints + in.ints + off;
                            for (int k = 0; k < n; k++) d[k] = table_at(*tabs[static_cast<std::size_t>(idx[k])], a.p[k * a.step]);
                        } else {
                            const LookupTable& table = *tabs[static_cast<std::size_t>(in.ints)];
                            for (int k = 0; k < n; k++) d[k] = table_at(table, a.p[k * a.step]);
                        }
                        break;
                    }
                }
            }
            Src r = src(s.result);
            if (s.out_kind == 1) {
                double* o = out + s.out + off;
                if (s.multiply) {
                    for (int k = 0; k < n; k++) o[k] = o[k] * r.p[k * r.step];
                } else {
                    for (int k = 0; k < n; k++) o[k] = r.p[k * r.step];
                }
            } else if (s.out_kind == 2) {
                const std::int32_t* idx = ints + s.out + off;
                if (s.multiply) {
                    for (int k = 0; k < n; k++) out[idx[k]] = out[idx[k]] * r.p[k * r.step];
                } else {
                    for (int k = 0; k < n; k++) out[idx[k]] = r.p[k * r.step];
                }
            } else {
                for (int k = 0; k < n; k++) out[s.out] = s.multiply ? out[s.out] * r.p[k * r.step] : r.p[k * r.step];
            }
        }
    }
}

}  // namespace kompartment
