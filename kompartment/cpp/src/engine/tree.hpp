// From equation trees to resolved expression trees.
//
// `resolve_tree` turns a parsed equation into a tree whose leaves are
// resolved: a slot of the state (`y`), of the parameters (`P`), of the
// algebraic values (`X`), a number (`K`), the clock (`T`, `T0`, `T1`), a
// lookup table (`TAB`) or an event's expected-value switch (`DIS`) -- each
// leaf holding one index, or a vector of them, one per element the statement
// computes. Subtrees of numbers alone are folded here, with the arithmetic
// the evaluator uses. Statements whose trees have the same shape and that do
// not read one another are merged: their leaves' index vectors concatenated,
// so one loop computes them all.
//
// Indices are the application's: counted from 0.

#pragma once

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "lang/ast.hpp"

namespace kompartment {

enum class LeafKind : unsigned char { K, T, T0, T1, Y, P, X, TAB, DIS };
const char* leaf_kind_name(LeafKind k);

enum class BinOp : unsigned char { Add, Sub, Mul, Div, Pow, Lt, Le, Gt, Ge, Eq, Ne, And, Or };
const char* bin_op_name(BinOp op);

/// The built-in functions, by number (their canonical names in lang/functions).
enum class Fn : unsigned char {
    Abs, Sqrt, Exp, Log, Log10, Log2, Power, Hypot, Ceil, Floor, Round, Fix, Sign, Eps, Ulp, Pi, Mod, Rem, Factorial,
    Binomial, Erf, Erfc, Sin, Cos, Tan, Asin, Acos, Atan, Atan2, Sinh, Cosh, Tanh, Asinh, Acosh, Atanh, Min, Max, Sum,
    Prod, Mean, If, Not, And, Or, Nand, Nor, Xor, Percentile, InterpolationUseEndValues, InterpolationExtrapolation,
    Bq2Mole, Mole2Bq, TransportPoint, TransportSum, TransportMean, RampDown, RampUp, SmoothDown, SmoothUp, Time,
    StartTime, EndTime, Unknown
};
Fn fn_of(const std::string& key);

struct TNode;
using TNodePtr = std::shared_ptr<const TNode>;
using IntVec = std::shared_ptr<const std::vector<int>>;
using NumVec = std::shared_ptr<const std::vector<double>>;

struct TNode {
    enum class Kind : unsigned char { Leaf, Neg, Bin, Cond, Call, Tab };
    Kind kind;
    explicit TNode(Kind k) : kind(k) {}
    virtual ~TNode() = default;
};

/// A leaf: one index (or number) for every element, or one shared by all.
struct TLeaf : TNode {
    LeafKind leaf;
    int index = 0;      // the shared index (y, P, X, TAB, DIS)
    IntVec indices;     // one per element, when they differ
    double value = 0;   // the shared number (K)
    NumVec values;

    explicit TLeaf(LeafKind k) : TNode(Kind::Leaf), leaf(k) {}
    TLeaf(LeafKind k, int i) : TNode(Kind::Leaf), leaf(k), index(i) {}
    TLeaf(LeafKind k, int i, IntVec is, double v, NumVec vs)
        : TNode(Kind::Leaf), leaf(k), index(i), indices(std::move(is)), value(v), values(std::move(vs)) {}

    bool is_vector() const { return indices != nullptr || values != nullptr; }
    int width() const { return indices ? static_cast<int>(indices->size()) : values ? static_cast<int>(values->size()) : 1; }
    /// The index, or the number, for element `i` (from 0).
    int index_at(std::size_t i) const { return indices ? (*indices)[i] : index; }
    double value_at(std::size_t i) const { return values ? (*values)[i] : value; }
};
using TLeafPtr = std::shared_ptr<const TLeaf>;

/// A leaf of one index, or of one per element (a vector of one is the one).
TLeafPtr make_leaf(LeafKind k);
TLeafPtr make_leaf(LeafKind k, int index);
TLeafPtr make_leaf(LeafKind k, std::vector<int> indices);
TLeafPtr k_leaf(double v);
TLeafPtr k_leaf(std::vector<double> v);

struct TNeg : TNode {
    TNodePtr a;
    explicit TNeg(TNodePtr x) : TNode(Kind::Neg), a(std::move(x)) {}
};
struct TBin : TNode {
    BinOp op;
    TNodePtr a, b;
    TBin(BinOp o, TNodePtr x, TNodePtr y) : TNode(Kind::Bin), op(o), a(std::move(x)), b(std::move(y)) {}
};
struct TCond : TNode {
    TNodePtr test, a, b;
    TCond(TNodePtr t, TNodePtr x, TNodePtr y) : TNode(Kind::Cond), test(std::move(t)), a(std::move(x)), b(std::move(y)) {}
};
/// A built-in function, by its canonical name.
struct TCall : TNode {
    std::string key;
    Fn fn;
    std::vector<TNodePtr> args;
    TCall(std::string k, std::vector<TNodePtr> a) : TNode(Kind::Call), key(std::move(k)), fn(fn_of(key)), args(std::move(a)) {}
};
/// A lookup table read at an argument.
struct TTab : TNode {
    TLeafPtr leaf;
    TNodePtr arg;
    TTab(TLeafPtr l, TNodePtr a) : TNode(Kind::Tab), leaf(std::move(l)), arg(std::move(a)) {}
};

inline const TLeaf& as_leaf(const TNode& n) { return static_cast<const TLeaf&>(n); }
inline const TNeg& as_neg(const TNode& n) { return static_cast<const TNeg&>(n); }
inline const TBin& as_bin(const TNode& n) { return static_cast<const TBin&>(n); }
inline const TCond& as_tcond(const TNode& n) { return static_cast<const TCond&>(n); }
inline const TCall& as_tcall(const TNode& n) { return static_cast<const TCall&>(n); }
inline const TTab& as_tab(const TNode& n) { return static_cast<const TTab&>(n); }

/// The number a tree is, when it is one number for every element; none otherwise.
std::optional<double> fold_value(const TNode& t);

/// A binary operation on two numbers, as the evaluator does it; `b_one`: the exponent of a
/// power is one number for every element of its statement.
double apply_binary(BinOp op, double a, double b, bool b_one = true);

/// A built-in function applied to numbers, as the evaluator applies it. `ones[i]`:
/// argument i is one number for every element of its statement (all of them when null),
/// which decides numpy's short cut in a power.
double call_value(Fn fn, const double* args, std::size_t n, const std::vector<bool>* ones = nullptr);

/// Gives the leaf a reference reads.
using RefResolver = std::function<TNodePtr(const ERef& node)>;
/// Gives the tree of a call the model defines (a table read at an argument), or null.
using CallResolver = std::function<TNodePtr(const std::string& name, const std::vector<TNodePtr>& args)>;

/// The expression tree of a parsed equation, every reference resolved.
TNodePtr resolve_tree(const ENode& ast, const RefResolver& ref, const CallResolver& call = nullptr);

/// The shape of a tree: its operations and the kinds of its leaves.
std::string signature(const TNode& tree);

/// Whether a subtree is one value for every element of its statement.
bool scalar_subtree(const TNode& t);

/// Every leaf of a tree, in a fixed order (the order `rebuild` takes).
std::vector<TLeafPtr> tree_leaves(const TNodePtr& tree);
void tree_leaves(std::vector<TLeafPtr>& out, const TNodePtr& tree);

/// The same tree with its leaves replaced, in `tree_leaves` order.
TNodePtr rebuild(const TNodePtr& tree, const std::vector<TLeafPtr>& leaves);

/// Leaves of several same-shaped statements, concatenated position by position: each
/// group is a statement's leaves and its width. A leaf that is the same scalar in every
/// statement stays a scalar; otherwise it becomes one vector covering every element of
/// every statement, in order.
std::vector<TLeafPtr> merge_leaves(const std::vector<std::pair<std::vector<TLeafPtr>, int>>& groups);

}  // namespace kompartment
