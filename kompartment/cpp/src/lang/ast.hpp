// An equation as a tree, and its tokens.

#pragma once

#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace kompartment {

/// One token: its kind, its text and where it starts (in characters, from 0, as the
/// application counts).
struct Token {
    enum class Type { Number, Ident, Op, LParen, RParen, Comma, LBracket, RBracket, Index, Eof };
    Type type;
    std::string text;
    int pos;
};

/// A character the language does not use.
struct EquationSyntaxError : std::runtime_error {
    int position;
    std::string source;
    EquationSyntaxError(const std::string& message, int position_, std::string source_)
        : std::runtime_error(message), position(position_), source(std::move(source_)) {}
};

/// An equation that cannot be read.
struct EquationParseError : std::runtime_error {
    int position;
    std::string source;
    EquationParseError(const std::string& message, int position_, std::string source_)
        : std::runtime_error(message), position(position_), source(std::move(source_)) {}
};

struct UnitDim;   // what a unit measures (engine/unitcheck)

struct ENode;
using ENodePtr = std::shared_ptr<ENode>;

/// A node of an equation's tree.
struct ENode {
    enum class Kind : unsigned char { Num, Ref, Call, Unary, Binary, Cond };
    Kind kind;
    explicit ENode(Kind k) : kind(k) {}
    virtual ~ENode() = default;
};

/// A number, and the unit written against it (`0.01[m]`), if any.
struct ENum : ENode {
    double value;
    std::optional<std::string> unit;
    std::shared_ptr<const UnitDim> dim;
    explicit ENum(double v) : ENode(Kind::Num), value(v) {}
    ENum(double v, std::optional<std::string> u) : ENode(Kind::Num), value(v), unit(std::move(u)) {}
};

/// A reference to a block: one entry per bracket (none for `[]`), or lists named outright
/// with the index taken on each (the reducing blocks build those). `scope` is the
/// sub-system a reference moved in by the function inliner was written in.
struct ERef : ENode {
    std::string name;
    std::vector<std::optional<std::string>> indices;
    bool by_list = false;
    std::vector<std::pair<std::string, std::string>> named;   // (list, index) when by_list
    std::optional<std::string> scope;
    explicit ERef(std::string n) : ENode(Kind::Ref), name(std::move(n)) {}
    ERef(std::string n, std::vector<std::optional<std::string>> idx, std::optional<std::string> sc = std::nullopt)
        : ENode(Kind::Ref), name(std::move(n)), indices(std::move(idx)), scope(std::move(sc)) {}
};

struct ECall : ENode {
    std::string name;
    std::vector<ENodePtr> args;
    std::optional<std::string> scope;
    ECall(std::string n, std::vector<ENodePtr> a, std::optional<std::string> sc = std::nullopt)
        : ENode(Kind::Call), name(std::move(n)), args(std::move(a)), scope(std::move(sc)) {}
};

struct EUnary : ENode {
    std::string op;
    ENodePtr operand;
    EUnary(std::string o, ENodePtr x) : ENode(Kind::Unary), op(std::move(o)), operand(std::move(x)) {}
};

struct EBinary : ENode {
    std::string op;
    ENodePtr left, right;
    EBinary(std::string o, ENodePtr l, ENodePtr r) : ENode(Kind::Binary), op(std::move(o)), left(std::move(l)), right(std::move(r)) {}
};

struct ECond : ENode {
    ENodePtr test, then, otherwise;
    ECond(ENodePtr t, ENodePtr a, ENodePtr b) : ENode(Kind::Cond), test(std::move(t)), then(std::move(a)), otherwise(std::move(b)) {}
};

inline const ENum& as_num(const ENode& n) { return static_cast<const ENum&>(n); }
inline const ERef& as_ref(const ENode& n) { return static_cast<const ERef&>(n); }
inline const ECall& as_call(const ENode& n) { return static_cast<const ECall&>(n); }
inline const EUnary& as_unary(const ENode& n) { return static_cast<const EUnary&>(n); }
inline const EBinary& as_binary(const ENode& n) { return static_cast<const EBinary&>(n); }
inline const ECond& as_cond(const ENode& n) { return static_cast<const ECond&>(n); }

}  // namespace kompartment
