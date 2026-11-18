#include "engine/tree.hpp"

#include <cmath>
#include <stdexcept>
#include <unordered_map>

#include "engine/lookup.hpp"
#include "lang/functions.hpp"

namespace kompartment {

const char* leaf_kind_name(LeafKind k) {
    switch (k) {
        case LeafKind::K: return "K";
        case LeafKind::T: return "T";
        case LeafKind::T0: return "T0";
        case LeafKind::T1: return "T1";
        case LeafKind::Y: return "y";
        case LeafKind::P: return "P";
        case LeafKind::X: return "X";
        case LeafKind::TAB: return "TAB";
        case LeafKind::DIS: return "DIS";
    }
    return "?";
}

const char* bin_op_name(BinOp op) {
    switch (op) {
        case BinOp::Add: return "+";
        case BinOp::Sub: return "-";
        case BinOp::Mul: return "*";
        case BinOp::Div: return "/";
        case BinOp::Pow: return "^";
        case BinOp::Lt: return "<";
        case BinOp::Le: return "<=";
        case BinOp::Gt: return ">";
        case BinOp::Ge: return ">=";
        case BinOp::Eq: return "==";
        case BinOp::Ne: return "~=";
        case BinOp::And: return "&&";
        case BinOp::Or: return "||";
    }
    return "?";
}

Fn fn_of(const std::string& key) {
    static const std::unordered_map<std::string, Fn> table = {
        {"abs", Fn::Abs}, {"sqrt", Fn::Sqrt}, {"exp", Fn::Exp}, {"log", Fn::Log}, {"log10", Fn::Log10}, {"log2", Fn::Log2},
        {"power", Fn::Power}, {"hypot", Fn::Hypot}, {"ceil", Fn::Ceil}, {"floor", Fn::Floor}, {"round", Fn::Round},
        {"fix", Fn::Fix}, {"sign", Fn::Sign}, {"eps", Fn::Eps}, {"ulp", Fn::Ulp}, {"pi", Fn::Pi}, {"mod", Fn::Mod},
        {"rem", Fn::Rem}, {"factorial", Fn::Factorial}, {"binomial", Fn::Binomial}, {"erf", Fn::Erf}, {"erfc", Fn::Erfc},
        {"sin", Fn::Sin}, {"cos", Fn::Cos}, {"tan", Fn::Tan}, {"asin", Fn::Asin}, {"acos", Fn::Acos}, {"atan", Fn::Atan},
        {"atan2", Fn::Atan2}, {"sinh", Fn::Sinh}, {"cosh", Fn::Cosh}, {"tanh", Fn::Tanh}, {"asinh", Fn::Asinh},
        {"acosh", Fn::Acosh}, {"atanh", Fn::Atanh}, {"min", Fn::Min}, {"max", Fn::Max}, {"sum", Fn::Sum},
        {"prod", Fn::Prod}, {"mean", Fn::Mean}, {"if", Fn::If}, {"not", Fn::Not}, {"and", Fn::And}, {"or", Fn::Or},
        {"nand", Fn::Nand}, {"nor", Fn::Nor}, {"xor", Fn::Xor}, {"percentile", Fn::Percentile},
        {"interpolationUseEndValues", Fn::InterpolationUseEndValues},
        {"interpolationExtrapolation", Fn::InterpolationExtrapolation}, {"bq2mole", Fn::Bq2Mole},
        {"mole2bq", Fn::Mole2Bq}, {"transport_point", Fn::TransportPoint}, {"transport_sum", Fn::TransportSum},
        {"transport_mean", Fn::TransportMean}, {"rampDown", Fn::RampDown}, {"rampUp", Fn::RampUp},
        {"smoothDown", Fn::SmoothDown}, {"smoothUp", Fn::SmoothUp}, {"time", Fn::Time}, {"start_time", Fn::StartTime},
        {"end_time", Fn::EndTime}};
    auto it = table.find(key);
    return it == table.end() ? Fn::Unknown : it->second;
}

TLeafPtr make_leaf(LeafKind k) { return std::make_shared<TLeaf>(k); }
TLeafPtr make_leaf(LeafKind k, int index) { return std::make_shared<TLeaf>(k, index); }
TLeafPtr make_leaf(LeafKind k, std::vector<int> indices) {
    if (indices.size() == 1) return std::make_shared<TLeaf>(k, indices[0]);
    return std::make_shared<TLeaf>(k, 0, std::make_shared<const std::vector<int>>(std::move(indices)), 0.0, nullptr);
}
TLeafPtr k_leaf(double v) { return std::make_shared<TLeaf>(LeafKind::K, 0, nullptr, v, nullptr); }
TLeafPtr k_leaf(std::vector<double> v) {
    if (v.size() == 1) return k_leaf(v[0]);
    return std::make_shared<TLeaf>(LeafKind::K, 0, nullptr, 0.0, std::make_shared<const std::vector<double>>(std::move(v)));
}

std::optional<double> fold_value(const TNode& t) {
    if (t.kind != TNode::Kind::Leaf) return std::nullopt;
    const TLeaf& l = as_leaf(t);
    if (l.leaf == LeafKind::K && !l.values) return l.value;
    return std::nullopt;
}

double apply_binary(BinOp op, double a, double b, bool b_one) {
    switch (op) {
        case BinOp::Add: return a + b;
        case BinOp::Sub: return a - b;
        case BinOp::Mul: return a * b;
        case BinOp::Div: return a / b;
        case BinOp::Pow: return b_one ? kf_jspow1(a, b) : kf_jspow(a, b);
        case BinOp::Lt: return b2f(a < b);
        case BinOp::Le: return b2f(a <= b);
        case BinOp::Gt: return b2f(a > b);
        case BinOp::Ge: return b2f(a >= b);
        case BinOp::Eq: return b2f(a == b);
        case BinOp::Ne: return b2f(a != b);
        case BinOp::And: return b2f(a != 0 && b != 0);
        case BinOp::Or: return b2f(a != 0 || b != 0);
    }
    throw std::logic_error("Cannot evaluate operator");
}

double call_value(Fn fn, const double* a, std::size_t n, const std::vector<bool>* ones) {
    auto one = [&](std::size_t i) { return !ones || (*ones)[i]; };
    switch (fn) {
        case Fn::If: return a[0] != 0 ? a[1] : (n > 2 ? a[2] : 0.0);
        case Fn::Not: return kf_not(a[0]);
        case Fn::Min: {
            double out = a[0];
            for (std::size_t i = 1; i < n; i++) out = kf_min(out, a[i]);
            return out;
        }
        case Fn::Max: {
            double out = a[0];
            for (std::size_t i = 1; i < n; i++) out = kf_max(out, a[i]);
            return out;
        }
        case Fn::Sum: {
            double out = a[0];
            for (std::size_t i = 1; i < n; i++) out = out + a[i];
            return out;
        }
        case Fn::Prod: {
            double out = a[0];
            for (std::size_t i = 1; i < n; i++) out = out * a[i];
            return out;
        }
        case Fn::Mean: {
            double out = a[0];
            for (std::size_t i = 1; i < n; i++) out = out + a[i];
            return out / static_cast<double>(n);
        }
        case Fn::Power: return one(1) ? kf_jspow1(a[0], a[1]) : kf_jspow(a[0], a[1]);
        case Fn::SmoothDown: return kf_smooth_down(a[0], a[1], a[2], one(2));
        case Fn::SmoothUp: return kf_smooth_up(a[0], a[1], a[2], one(2));
        case Fn::Round: return kf_round(a[0]);
        case Fn::Pi: return 3.141592653589793;
        case Fn::Abs: return kf_abs(a[0]);
        case Fn::Sqrt: return kf_sqrt(a[0]);
        case Fn::Exp: return kf_exp(a[0]);
        case Fn::Log: return kf_log(a[0]);
        case Fn::Log10: return kf_log10(a[0]);
        case Fn::Log2: return kf_log2(a[0]);
        case Fn::Hypot: return kf_hypot(a[0], a[1]);
        case Fn::Ceil: return kf_ceil(a[0]);
        case Fn::Floor: return kf_floor(a[0]);
        case Fn::Fix: return kf_fix(a[0]);
        case Fn::Sign: return kf_sign(a[0]);
        case Fn::Eps: return EPS;
        case Fn::Ulp: return kf_ulp(a[0]);
        case Fn::Mod: return kf_mod(a[0], a[1]);
        case Fn::Rem: return kf_rem(a[0], a[1]);
        case Fn::Factorial: return kf_factorial(a[0]);
        case Fn::Binomial: return kf_binomial(a[0], a[1]);
        case Fn::Erf: return kf_erf(a[0]);
        case Fn::Erfc: return kf_erfc(a[0]);
        case Fn::Sin: return kf_sin(a[0]);
        case Fn::Cos: return kf_cos(a[0]);
        case Fn::Tan: return kf_tan(a[0]);
        case Fn::Asin: return kf_asin(a[0]);
        case Fn::Acos: return kf_acos(a[0]);
        case Fn::Atan: return kf_atan(a[0]);
        case Fn::Atan2: return kf_atan2(a[0], a[1]);
        case Fn::Sinh: return kf_sinh(a[0]);
        case Fn::Cosh: return kf_cosh(a[0]);
        case Fn::Tanh: return kf_tanh(a[0]);
        case Fn::Asinh: return kf_asinh(a[0]);
        case Fn::Acosh: return kf_acosh(a[0]);
        case Fn::Atanh: return kf_atanh(a[0]);
        case Fn::And: {
            bool all = true;
            for (std::size_t i = 0; i < n; i++) all = all && a[i] != 0;
            return b2f(all);
        }
        case Fn::Or: {
            bool any = false;
            for (std::size_t i = 0; i < n; i++) any = any || a[i] != 0;
            return b2f(any);
        }
        case Fn::Nand: {
            bool all = true;
            for (std::size_t i = 0; i < n; i++) all = all && a[i] != 0;
            return 1.0 - b2f(all);
        }
        case Fn::Nor: {
            bool any = false;
            for (std::size_t i = 0; i < n; i++) any = any || a[i] != 0;
            return 1.0 - b2f(any);
        }
        case Fn::Xor: {
            int count = 0;
            for (std::size_t i = 0; i < n; i++) count += a[i] != 0;
            return b2f(count % 2 == 1);
        }
        case Fn::Percentile: return kf_percentile(a[0], a + 1, n - 1);
        case Fn::InterpolationUseEndValues: return interpolate_args(a, n, false);
        case Fn::InterpolationExtrapolation: return interpolate_args(a, n, true);
        case Fn::Bq2Mole: return kf_bq2mole(a[0], a[1]);
        case Fn::Mole2Bq: return kf_mole2bq(a[0], a[1]);
        case Fn::TransportPoint: return kf_transport_point(a, n);
        case Fn::TransportSum: return kf_transport_range(a, n, false);
        case Fn::TransportMean: return kf_transport_range(a, n, true);
        case Fn::RampDown: return kf_ramp_down(a[0], a[1], a[2]);
        case Fn::RampUp: return kf_ramp_up(a[0], a[1], a[2]);
        default: break;
    }
    throw std::logic_error("Cannot evaluate a function that reads the clock as a number");
}

namespace {

BinOp bin_op_of(const std::string& op) {
    static const std::unordered_map<std::string, BinOp> table = {
        {"+", BinOp::Add}, {"-", BinOp::Sub}, {"*", BinOp::Mul}, {"/", BinOp::Div}, {"^", BinOp::Pow}, {"<", BinOp::Lt},
        {"<=", BinOp::Le}, {">", BinOp::Gt}, {">=", BinOp::Ge}, {"==", BinOp::Eq}, {"~=", BinOp::Ne}, {"&&", BinOp::And},
        {"||", BinOp::Or}};
    return table.at(op);
}

// Folds a node whose children are all numbers; none when it cannot.
std::optional<double> evaluate_constant(const TNode& t) {
    switch (t.kind) {
        case TNode::Kind::Neg: {
            auto v = fold_value(*as_neg(t).a);
            return v ? std::optional<double>(-*v) : std::nullopt;
        }
        case TNode::Kind::Bin: {
            auto a = fold_value(*as_bin(t).a), b = fold_value(*as_bin(t).b);
            if (!a || !b) return std::nullopt;
            return apply_binary(as_bin(t).op, *a, *b);
        }
        case TNode::Kind::Cond: {
            auto v = fold_value(*as_tcond(t).test);
            if (!v) return std::nullopt;
            return fold_value(*v != 0 ? *as_tcond(t).a : *as_tcond(t).b);
        }
        case TNode::Kind::Call: {
            const TCall& c = as_tcall(t);
            std::vector<double> vals;
            for (const auto& a : c.args) {
                auto v = fold_value(*a);
                if (!v) return std::nullopt;
                vals.push_back(*v);
            }
            if (c.fn == Fn::Time || c.fn == Fn::StartTime || c.fn == Fn::EndTime) return std::nullopt;
            try {
                return call_value(c.fn, vals.data(), vals.size());
            } catch (const std::exception&) {
                return std::nullopt;   // left for run time, where it raises in place
            }
        }
        default: return std::nullopt;
    }
}

struct Walker {
    const RefResolver& ref;
    const CallResolver& call;

    TNodePtr walk(const ENode& node, int depth) const {
        if (depth > 20000)
            throw std::runtime_error("This equation is too long or too deeply nested to compile. Split it into expression blocks.");
        TNodePtr out;
        switch (node.kind) {
            case ENode::Kind::Num: return k_leaf(as_num(node).value);
            case ENode::Kind::Ref: return ref(as_ref(node));
            case ENode::Kind::Unary: out = std::make_shared<TNeg>(walk(*as_unary(node).operand, depth + 1)); break;
            case ENode::Kind::Binary: {
                const EBinary& b = as_binary(node);
                TNodePtr left = walk(*b.left, depth + 1);
                out = std::make_shared<TBin>(bin_op_of(b.op), left, walk(*b.right, depth + 1));
                break;
            }
            case ENode::Kind::Cond: {
                const ECond& c = as_cond(node);
                TNodePtr test = walk(*c.test, depth + 1);
                TNodePtr then = walk(*c.then, depth + 1);
                out = std::make_shared<TCond>(test, then, walk(*c.otherwise, depth + 1));
                break;
            }
            case ENode::Kind::Call: {
                const ECall& c = as_call(node);
                std::string name = c.name;
                if (auto spec = lookup_function(name)) name = spec->key;
                std::vector<TNodePtr> args;
                for (const auto& a : c.args) args.push_back(walk(*a, depth + 1));
                if (call) {
                    TNodePtr own = call(c.name, args);
                    if (own) return own;
                }
                Fn fn = fn_of(name);
                if (fn == Fn::Unknown) throw std::invalid_argument("Unknown function '" + name + "'");
                if (fn == Fn::Time) return make_leaf(LeafKind::T);
                if (fn == Fn::StartTime) return make_leaf(LeafKind::T0);
                if (fn == Fn::EndTime) return make_leaf(LeafKind::T1);
                if (fn == Fn::Eps) return k_leaf(EPS);
                if (fn == Fn::Pi) return k_leaf(3.141592653589793);
                if (fn == Fn::If) out = std::make_shared<TCond>(args[0], args[1], args.size() > 2 ? args[2] : TNodePtr(k_leaf(0.0)));
                else out = std::make_shared<TCall>(name, std::move(args));
                break;
            }
        }
        auto v = evaluate_constant(*out);
        return v ? TNodePtr(k_leaf(*v)) : out;
    }
};

void sig(std::string& io, const TNode& t) {
    switch (t.kind) {
        case TNode::Kind::Leaf: io += leaf_kind_name(as_leaf(t).leaf); break;
        case TNode::Kind::Neg:
            io += "-(";
            sig(io, *as_neg(t).a);
            io += ')';
            break;
        case TNode::Kind::Bin:
            io += bin_op_name(as_bin(t).op);
            io += '(';
            sig(io, *as_bin(t).a);
            io += ',';
            sig(io, *as_bin(t).b);
            io += ')';
            break;
        case TNode::Kind::Cond:
            io += "?(";
            sig(io, *as_tcond(t).test);
            io += ',';
            sig(io, *as_tcond(t).a);
            io += ',';
            sig(io, *as_tcond(t).b);
            io += ')';
            break;
        case TNode::Kind::Call: {
            const TCall& c = as_tcall(t);
            io += c.key;
            io += '(';
            for (std::size_t i = 0; i < c.args.size(); i++) {
                if (i) io += ',';
                sig(io, *c.args[i]);
            }
            io += ')';
            break;
        }
        case TNode::Kind::Tab:
            io += "tab(";
            sig(io, *as_tab(t).arg);
            io += ')';
            break;
    }
}

TNodePtr rebuild_walk(const TNodePtr& t, const std::vector<TLeafPtr>& leaves, std::size_t& k) {
    switch (t->kind) {
        case TNode::Kind::Leaf: return leaves[k++];
        case TNode::Kind::Neg: return std::make_shared<TNeg>(rebuild_walk(as_neg(*t).a, leaves, k));
        case TNode::Kind::Bin: {
            TNodePtr a = rebuild_walk(as_bin(*t).a, leaves, k);
            return std::make_shared<TBin>(as_bin(*t).op, a, rebuild_walk(as_bin(*t).b, leaves, k));
        }
        case TNode::Kind::Cond: {
            TNodePtr a = rebuild_walk(as_tcond(*t).test, leaves, k);
            TNodePtr b = rebuild_walk(as_tcond(*t).a, leaves, k);
            return std::make_shared<TCond>(a, b, rebuild_walk(as_tcond(*t).b, leaves, k));
        }
        case TNode::Kind::Call: {
            std::vector<TNodePtr> args;
            for (const auto& a : as_tcall(*t).args) args.push_back(rebuild_walk(a, leaves, k));
            return std::make_shared<TCall>(as_tcall(*t).key, std::move(args));
        }
        case TNode::Kind::Tab: {
            TLeafPtr leaf = leaves[k++];
            return std::make_shared<TTab>(leaf, rebuild_walk(as_tab(*t).arg, leaves, k));
        }
    }
    throw std::logic_error("rebuild");
}

}  // namespace

TNodePtr resolve_tree(const ENode& ast, const RefResolver& ref, const CallResolver& call) { return Walker{ref, call}.walk(ast, 0); }

std::string signature(const TNode& tree) {
    std::string io;
    sig(io, tree);
    return io;
}

bool scalar_subtree(const TNode& t) {
    switch (t.kind) {
        case TNode::Kind::Leaf: return !as_leaf(t).is_vector();
        case TNode::Kind::Neg: return scalar_subtree(*as_neg(t).a);
        case TNode::Kind::Bin: return scalar_subtree(*as_bin(t).a) && scalar_subtree(*as_bin(t).b);
        case TNode::Kind::Cond: return scalar_subtree(*as_tcond(t).test) && scalar_subtree(*as_tcond(t).a) && scalar_subtree(*as_tcond(t).b);
        case TNode::Kind::Call:
            for (const auto& a : as_tcall(t).args)
                if (!scalar_subtree(*a)) return false;
            return true;
        case TNode::Kind::Tab: return !as_tab(t).leaf->is_vector() && scalar_subtree(*as_tab(t).arg);
    }
    return true;
}

void tree_leaves(std::vector<TLeafPtr>& out, const TNodePtr& t) {
    switch (t->kind) {
        case TNode::Kind::Leaf: out.push_back(std::static_pointer_cast<const TLeaf>(t)); break;
        case TNode::Kind::Neg: tree_leaves(out, as_neg(*t).a); break;
        case TNode::Kind::Bin:
            tree_leaves(out, as_bin(*t).a);
            tree_leaves(out, as_bin(*t).b);
            break;
        case TNode::Kind::Cond:
            tree_leaves(out, as_tcond(*t).test);
            tree_leaves(out, as_tcond(*t).a);
            tree_leaves(out, as_tcond(*t).b);
            break;
        case TNode::Kind::Call:
            for (const auto& a : as_tcall(*t).args) tree_leaves(out, a);
            break;
        case TNode::Kind::Tab:
            out.push_back(as_tab(*t).leaf);
            tree_leaves(out, as_tab(*t).arg);
            break;
    }
}

std::vector<TLeafPtr> tree_leaves(const TNodePtr& tree) {
    std::vector<TLeafPtr> out;
    tree_leaves(out, tree);
    return out;
}

TNodePtr rebuild(const TNodePtr& tree, const std::vector<TLeafPtr>& leaves) {
    std::size_t k = 0;
    return rebuild_walk(tree, leaves, k);
}

std::vector<TLeafPtr> merge_leaves(const std::vector<std::pair<std::vector<TLeafPtr>, int>>& groups) {
    const std::vector<TLeafPtr>& first = groups[0].first;
    std::vector<TLeafPtr> out;
    out.reserve(first.size());
    for (std::size_t i = 0; i < first.size(); i++) {
        const TLeafPtr& leaf = first[i];
        LeafKind kind = leaf->leaf;
        if (kind == LeafKind::T || kind == LeafKind::T0 || kind == LeafKind::T1) {
            out.push_back(leaf);
            continue;
        }
        if (kind == LeafKind::K) {
            bool same = true;
            for (const auto& g : groups) {
                const TLeaf& l = *g.first[i];
                if (l.values || !((l.value == leaf->value) || (std::isnan(l.value) && std::isnan(leaf->value)))) {
                    same = false;
                    break;
                }
            }
            // (A leaf of the first statement that is itself a vector is never "the same".)
            if (same && !leaf->values) {
                out.push_back(leaf);
                continue;
            }
            std::vector<double> vals;
            for (const auto& [ls, w] : groups) {
                const TLeaf& l = *ls[i];
                if (l.values) vals.insert(vals.end(), l.values->begin(), l.values->end());
                else vals.insert(vals.end(), static_cast<std::size_t>(w), l.value);
            }
            out.push_back(std::make_shared<TLeaf>(LeafKind::K, 0, nullptr, 0.0, std::make_shared<const std::vector<double>>(std::move(vals))));
            continue;
        }
        bool same = true;
        for (const auto& g : groups) {
            const TLeaf& l = *g.first[i];
            if (l.indices || l.index != leaf->index) {
                same = false;
                break;
            }
        }
        if (same) {
            out.push_back(leaf);
            continue;
        }
        std::vector<int> idx;
        for (const auto& [ls, w] : groups) {
            const TLeaf& l = *ls[i];
            if (l.indices) idx.insert(idx.end(), l.indices->begin(), l.indices->end());
            else idx.insert(idx.end(), static_cast<std::size_t>(w), l.index);
        }
        out.push_back(std::make_shared<TLeaf>(kind, 0, std::make_shared<const std::vector<int>>(std::move(idx)), 0.0, nullptr));
    }
    return out;
}

}  // namespace kompartment
