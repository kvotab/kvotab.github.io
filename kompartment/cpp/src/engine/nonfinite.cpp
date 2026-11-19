#include "engine/nonfinite.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <stdexcept>
#include <unordered_map>

#include "engine/builder.hpp"
#include "engine/lookup.hpp"
#include "engine/tree.hpp"
#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

using Vec = std::vector<double>;

constexpr int MOST_STEPS = 500;
constexpr int MOST_FOLLOWED = 2000;
constexpr std::size_t MOST_NAMED = 3;
constexpr std::size_t MOST_READS = 6;
constexpr std::size_t LONGEST_PART = 240;
const std::string ELLIPSIS = "\xe2\x80\xa6";

// One at a time: copies of a system share the builder and the index space, whose look-ups
// fill caches as they go.
std::mutex& nf_lock() {
    static std::mutex m;
    return m;
}

bool read_by_assembly(const Entry& a) {
    const std::string& k = a.kind;
    return k == "transfer" || k == "inflow" || k == "compartment:dydt" || k == "waste_package" || k == "farfield" || k == "running_mean:target" ||
           starts_with(k, "waste_package:") || starts_with(k, "event:") || starts_with(k, "farfield:");
}

/// A slot of a block's own -- `T#limit`, `M#target` -- answers as the block.
std::string block_of(const std::string& name) { return name.substr(0, name.find('#')); }

// A value of a vector, as Julia reads one: past either end is an error.
double element(const Vec& v, long i) {
    if (i < 0 || static_cast<std::size_t>(i) >= v.size()) throw std::out_of_range("an index past the end of a vector");
    return v[static_cast<std::size_t>(i)];
}

// --- one element of an equation, taken apart -----------------------------------------------

struct Equation {
    System* sys = nullptr;
    EntryPtr a;
    const ENode* ast = nullptr;
    std::vector<std::string> dims;
    Tup tup;
    RefResolver ref;
    CallResolver call;
    std::unordered_map<const ENode*, std::optional<double>> values;
};
using EquationPtr = std::shared_ptr<Equation>;

EquationPtr equation_at(System& sys, int k, int off) {
    Builder& b = *sys.builder;
    const EntryPtr& a = b.algebraic.at(static_cast<std::size_t>(k - 1));
    if (a->asts.empty()) return nullptr;
    const std::size_t which = a->uniform ? 0 : static_cast<std::size_t>(off);
    if (which >= a->asts.size() || !a->asts[which]) throw std::out_of_range("no equation at that element");
    auto eq = std::make_shared<Equation>();
    eq->sys = &sys;
    eq->a = a;
    eq->ast = a->asts[which].get();
    eq->dims = a->dims;
    eq->tup = a->dims.empty() ? Tup() : tuple_by_list(*b.space, a->dims, off);
    Equation* e = eq.get();
    // The builder's resolver, without its note of a block reading itself: the builder is
    // shared by every copy of a system, and written only while it builds.
    eq->ref = [&b, e](const ERef& r) -> TNodePtr {
        Located at = b.locate(e->a, "", e->dims, nullptr, &e->tup, r);
        if (at.kind == RefKind::Table) throw std::runtime_error("'" + r.name + "' is a lookup table with an argument");
        LeafKind array = at.kind == RefKind::State ? LeafKind::Y : at.kind == RefKind::Param ? LeafKind::P : LeafKind::X;
        if (at.indices) return std::make_shared<TLeaf>(array, 0, at.indices, 0.0, nullptr);
        return make_leaf(array, at.index);
    };
    eq->call = b.make_call_resolver(a, eq->dims, nullptr, &eq->tup);
    return eq;
}

/// What a reference reads: `y`, `P` or `X` (0 for a table), and where.
struct Read {
    char array = 0;
    int offset = 0;
};

Read read_of(Equation& eq, const ERef& node) {
    Located at = eq.sys->builder->locate(eq.a, "", eq.dims, nullptr, &eq.tup, node);
    if (at.indices) throw std::runtime_error("a reference to many values");
    return {at.kind == RefKind::State ? 'y' : at.kind == RefKind::Param ? 'P' : at.kind == RefKind::Alg ? 'X' : '\0', at.index};
}

/// A resolved tree's value for one element, with the evaluator's arithmetic.
double tree_value(const TNode& t, double time, const Vec& y, const System& sys) {
    switch (t.kind) {
        case TNode::Kind::Leaf: {
            const TLeaf& l = as_leaf(t);
            if (l.is_vector()) throw std::runtime_error("A leaf of many values is not a value");
            switch (l.leaf) {
                case LeafKind::K: return l.value;
                case LeafKind::T: return time;
                case LeafKind::T0: return sys.data.T0;
                case LeafKind::T1: return sys.data.T1;
                case LeafKind::Y: return element(y, l.index);
                case LeafKind::P: return element(sys.P, l.index);
                case LeafKind::X: return element(sys.X, l.index);
                case LeafKind::DIS: return element(sys.data.DIS, l.index);
                default: throw std::runtime_error("A table leaf is not a value");
            }
        }
        case TNode::Kind::Neg: return -tree_value(*as_neg(t).a, time, y, sys);
        case TNode::Kind::Bin: {
            const TBin& b = as_bin(t);
            double x = tree_value(*b.a, time, y, sys);
            double z = tree_value(*b.b, time, y, sys);
            return apply_binary(b.op, x, z);
        }
        case TNode::Kind::Cond: {
            const TCond& c = as_tcond(t);
            return tree_value(tree_value(*c.test, time, y, sys) != 0.0 ? *c.a : *c.b, time, y, sys);
        }
        case TNode::Kind::Call: {
            const TCall& c = as_tcall(t);
            Vec args;
            args.reserve(c.args.size());
            for (const auto& a : c.args) args.push_back(tree_value(*a, time, y, sys));
            if (c.fn == Fn::Unknown) throw std::runtime_error("Cannot evaluate '" + c.key + "'");
            return call_value(c.fn, args.data(), args.size(), nullptr);
        }
        case TNode::Kind::Tab: {
            const TTab& tab = as_tab(t);
            const auto& table = sys.data.TAB.at(static_cast<std::size_t>(tab.leaf->index));
            return table_at(*table, tree_value(*tab.arg, time, y, sys));
        }
    }
    throw std::logic_error("Cannot evaluate this node");
}

std::optional<double> value_of(Equation& eq, const ENode* node, double t, const Vec& y) {
    auto it = eq.values.find(node);
    if (it != eq.values.end()) return it->second;
    std::optional<double> v;
    try {
        TNodePtr tree = resolve_tree(*node, eq.ref, eq.call);
        if (!tree) throw std::runtime_error("nothing to evaluate");
        v = tree_value(*tree, t, y, *eq.sys);
    } catch (...) {
        v = std::nullopt;   // a part that will not evaluate is one not followed
    }
    eq.values[node] = v;
    return v;
}

// --- following a value back ---------------------------------------------------------------------

struct Operand {
    const ENode* node;
    std::optional<double> value;
};

/// The operation that made a value that is not a number: the node, its value, and the
/// operands it was worked out from.
struct Part {
    const ENode* node;
    double value;
    std::vector<Operand> operands;
};

struct Root {
    int k = 0, off = 0;       // the algebraic block (from 1) and the element
    EquationPtr eq;
    std::optional<Part> part;
    std::optional<Read> read;
};
using RootPtr = std::shared_ptr<Root>;

RootPtr bare_root(int k, int off) {
    auto r = std::make_shared<Root>();
    r->k = k;
    r->off = off;
    return r;
}

struct At {
    System* sys = nullptr;
    double t = 0;
    Vec state, d;
    std::vector<int> owner;   // the algebraic block (from 1) of each slot; 0 for none
    std::map<std::pair<int, int>, RootPtr> memo;   // null while being followed
};

std::optional<std::pair<int, int>> slot_at(const At& at, long offset) {
    if (offset < 0 || offset >= static_cast<long>(at.owner.size())) return std::nullopt;
    int k = at.owner[static_cast<std::size_t>(offset)];
    if (k == 0) return std::nullopt;
    return std::make_pair(k, static_cast<int>(offset) - at.sys->builder->algebraic[static_cast<std::size_t>(k - 1)]->base);
}

RootPtr follow(At& at, int k, int off, int depth);

RootPtr root_of(At& at, int k, int off, int depth = 0) {
    const auto key = std::make_pair(k, off);
    auto it = at.memo.find(key);
    if (it != at.memo.end()) return it->second ? it->second : bare_root(k, off);
    at.memo[key] = nullptr;
    RootPtr found = follow(at, k, off, depth);
    at.memo[key] = found;
    return found;
}

/// The operands a node was worked out from, with their values: only the branch a conditional took.
template <class Value>
std::vector<Operand> operands_of(const ENode& node, Value value) {
    auto of = [&](const ENodePtr& n) { return Operand{n.get(), value(n.get())}; };
    switch (node.kind) {
        case ENode::Kind::Unary: return {of(as_unary(node).operand)};
        case ENode::Kind::Binary: {
            const EBinary& b = as_binary(node);
            Operand left = of(b.left);
            Operand right = of(b.right);
            return {left, right};
        }
        case ENode::Kind::Cond: {
            const ECond& c = as_cond(node);
            Operand test = of(c.test);
            if (!test.value) return {test};
            Operand taken = of(*test.value != 0 ? c.then : c.otherwise);
            return {test, taken};
        }
        case ENode::Kind::Call: {
            const ECall& c = as_call(node);
            if (c.name == "if" && c.args.size() >= 2) {
                Operand test = of(c.args[0]);
                if (!test.value) return {test};
                const ENodePtr* taken = *test.value != 0 ? &c.args[1] : (c.args.size() > 2 ? &c.args[2] : nullptr);
                if (!taken) return {test};
                Operand chosen = of(*taken);
                return {test, chosen};
            }
            std::vector<Operand> out;
            for (const auto& a : c.args) out.push_back(of(a));
            return out;
        }
        default: return {};
    }
}

/// The node of an equation that is not a number while every operand it was worked out
/// from is one -- the operation that made it -- and its operands.
std::optional<Part> innermost(Equation& eq, double t, const Vec& y) {
    auto value = [&](const ENode* n) { return value_of(eq, n, t, y); };
    const ENode* node = eq.ast;
    std::optional<double> v = value(node);
    if (!v || std::isfinite(*v)) return std::nullopt;
    for (;;) {
        std::vector<Operand> parts = operands_of(*node, value);
        auto bad = std::find_if(parts.begin(), parts.end(), [](const Operand& p) { return p.value && !std::isfinite(*p.value); });
        if (bad == parts.end()) return Part{node, *v, std::move(parts)};
        node = bad->node;
        v = bad->value;
    }
}

RootPtr follow(At& at, int k, int off, int depth) {
    RootPtr here = bare_root(k, off);
    if (depth > MOST_STEPS) return here;
    const Entry& a = *at.sys->builder->algebraic[static_cast<std::size_t>(k - 1)];
    const Vec& X = at.sys->X;
    // A block that remembers has no equation; what it is not a number of, if anything
    // now, is its target.
    if (a.recorder && a.recorder->kind != "trigger") {
        const EntryPtr* target = nullptr;
        for (const auto& item : a.recorder->aux)
            if (item.first == "target") target = &item.second;
        if (target) {
            const long i = static_cast<long>((*target)->base) + off;
            auto nxt = std::isfinite(element(X, i)) ? std::nullopt : slot_at(at, i);
            return !nxt ? here : root_of(at, nxt->first, nxt->second, depth + 1);
        }
    }
    EquationPtr eq;
    try {
        eq = equation_at(*at.sys, k, off);
    } catch (...) {
        eq = nullptr;
    }
    if (!eq) return here;
    std::optional<Part> part = innermost(*eq, at.t, at.state);
    if (!part) {
        // The equation comes to a number and the slot does not: the slot is the rate times
        // an availability, and it is that.
        if (a.availability)
            for (const auto& [key, op] : a.availability->operands) {
                const long i = static_cast<long>(op->base) + off;
                auto nxt = std::isfinite(element(X, i)) ? std::nullopt : slot_at(at, i);
                if (nxt) return root_of(at, nxt->first, nxt->second, depth + 1);
            }
        return here;
    }
    if (part->node->kind == ENode::Kind::Ref) {
        std::optional<Read> read;
        try {
            read = read_of(*eq, as_ref(*part->node));
        } catch (...) {
            read = std::nullopt;
        }
        auto nxt = (read && read->array == 'X') ? slot_at(at, read->offset) : std::nullopt;
        if (nxt) return root_of(at, nxt->first, nxt->second, depth + 1);
        here->eq = eq;
        here->part = std::move(part);
        here->read = read;
        return here;
    }
    here->eq = eq;
    here->part = std::move(part);
    return here;
}

std::unique_ptr<At> evaluated(System& sys, double t, const Vec& y) {
    const int n = sys.nstate;
    if (static_cast<long>(y.size()) < n) return nullptr;
    auto at = std::make_unique<At>();
    at->sys = &sys;
    at->t = t;
    at->state.assign(y.begin(), y.begin() + n);
    at->d.assign(static_cast<std::size_t>(n), 0.0);
    try {
        sys.rhs(at->d.data(), t, at->state.data());
        // Every slot, not only those the derivative runs: a block the derivative reads is in
        // both, and its value is the same in either.
        sys.evaluate_algebraic(t, at->state.data());
    } catch (...) {
        return nullptr;
    }
    at->owner.assign(static_cast<std::size_t>(std::max(1, sys.nalg)), 0);
    int k = 0;
    for (const auto& a : sys.builder->algebraic) {
        k++;
        if (a->width <= 0) continue;
        if (a->base < 0 || static_cast<std::size_t>(a->base + a->width) > at->owner.size()) throw std::out_of_range("a block past the slots");
        std::fill(at->owner.begin() + a->base, at->owner.begin() + a->base + a->width, k);
    }
    return at;
}

/// One root per block, at its first element, with which elements it has, in the order of the blocks.
struct RootBlock {
    RootPtr first;
    std::set<int> offs;
};

std::vector<RootBlock> by_root_block(const std::vector<RootPtr>& roots) {
    std::map<int, RootBlock> by_block;
    for (const RootPtr& r : roots) {
        auto it = by_block.find(r->k);
        if (it == by_block.end()) {
            by_block.emplace(r->k, RootBlock{r, {r->off}});
        } else {
            it->second.offs.insert(r->off);
            if (r->off < it->second.first->off) it->second.first = r;
        }
    }
    std::vector<RootBlock> out;
    for (auto& [k, b] : by_block) out.push_back(std::move(b));
    return out;
}

struct Flow {
    std::string name, kind;
    int count = 0;
};

struct FromAssembly {
    std::vector<Flow> flows;
    std::vector<RootBlock> blocks;
    std::map<int, std::vector<std::string>> flows_of;
};

/// The blocks behind the values that are not numbers which the assembly of the derivative
/// reads, the flows that carry them, and which flows each reach.
FromAssembly from_assembly(At& at) {
    FromAssembly out;
    std::unordered_map<std::string, std::size_t> seen;
    std::vector<RootPtr> roots;
    int followed = 0;
    int k = 0;
    for (const auto& ap : at.sys->builder->algebraic) {
        k++;
        const Entry& a = *ap;
        if (!read_by_assembly(a)) continue;
        const bool is_flow = a.kind == "transfer" || a.kind == "inflow";
        const std::string flow = is_flow ? block_of(a.name) : std::string();
        for (int off = 0; off < a.width; off++) {
            if (std::isfinite(element(at.sys->X, static_cast<long>(a.base) + off))) continue;
            if (is_flow) {
                auto it = seen.find(flow);
                if (it == seen.end()) {
                    it = seen.emplace(flow, out.flows.size()).first;
                    out.flows.push_back(Flow{flow, a.kind, 0});
                }
                out.flows[it->second].count += 1;
            }
            followed += 1;
            if (followed > MOST_FOLLOWED) continue;
            RootPtr r = root_of(at, k, off);
            roots.push_back(r);
            if (is_flow && a.kind == "transfer") {
                auto& via = out.flows_of[r->k];
                if (std::find(via.begin(), via.end(), flow) == via.end()) via.push_back(flow);
            }
        }
    }
    out.blocks = by_root_block(roots);
    return out;
}

/// The blocks behind the values that are not numbers which only results read.
std::vector<RootBlock> from_the_rest(At& at, const std::set<int>& stopping) {
    std::vector<RootPtr> roots;
    int followed = 0;
    int k = 0;
    for (const auto& ap : at.sys->builder->algebraic) {
        k++;
        const Entry& a = *ap;
        // The slots behind a block -- a recorder's target, an availability -- answer for it:
        // the block's own slot is the one to follow.
        if (a.hidden || read_by_assembly(a)) continue;
        for (int off = 0; off < a.width; off++) {
            if (std::isfinite(element(at.sys->X, static_cast<long>(a.base) + off))) continue;
            followed += 1;
            if (followed > MOST_FOLLOWED) return by_root_block(roots);
            RootPtr r = root_of(at, k, off);
            if (!stopping.count(r->k)) roots.push_back(r);
        }
    }
    return by_root_block(roots);
}

/// A run's state block with values that are not numbers.
struct StateGroup {
    std::string name, kind;
    int count = 0, first = -1, at = 0;
    std::vector<std::string> dims;
};

/// The run's states that are not numbers, a block at a time, in the order of the state vector.
template <class Bad>
std::vector<StateGroup> group_by(const std::vector<EntryPtr>& entries, int n, Bad bad) {
    std::vector<StateGroup> out;
    for (const auto& s : entries) {
        int count = 0, first = -1;
        for (int i = 0; i < s->width; i++) {
            const int at = s->base + i;
            if (at >= n || !bad(at)) continue;
            if (first < 0) first = i;
            count++;
        }
        if (count == 0) continue;
        out.push_back(StateGroup{block_of(s->name), s->kind.empty() ? "compartment" : s->kind, count, first, s->base + first, s->dims});
    }
    return out;
}

const Entry* entry_at(const std::vector<EntryPtr>& entries, int offset) {
    for (const auto& e : entries)
        if (e->base <= offset && offset < e->base + e->width) return e.get();
    return nullptr;
}

struct Reading {
    std::string text;
    std::optional<double> value;
};

struct RootInfo {
    std::string name, kind;
    std::optional<Tup> index;
    int count = 0;
    double value = 0;
    struct Source {
        std::string name, kind;
        std::optional<Tup> index;
        double value = 0;
    };
    std::optional<Source> source;
    struct Text {
        std::string text, worked;
        std::vector<Reading> reads;
    };
    std::optional<Text> part;
};

std::string worked_text(const ENode& node, const std::vector<Operand>& parts, double value);

/// The references inside a part, each once, with the value it read.
std::vector<Reading> reads_of(const ENode& node, Equation& eq, double t, const Vec& y) {
    std::vector<Reading> out;
    std::function<void(const ENode&)> walk = [&](const ENode& n) {
        switch (n.kind) {
            case ENode::Kind::Ref: {
                std::string text = equation_text(n);
                for (const Reading& r : out)
                    if (r.text == text) return;
                out.push_back(Reading{text, value_of(eq, &n, t, y)});
                return;
            }
            case ENode::Kind::Unary: walk(*as_unary(n).operand); return;
            case ENode::Kind::Binary:
                walk(*as_binary(n).left);
                walk(*as_binary(n).right);
                return;
            case ENode::Kind::Cond:
                walk(*as_cond(n).test);
                walk(*as_cond(n).then);
                walk(*as_cond(n).otherwise);
                return;
            case ENode::Kind::Call:
                for (const auto& a : as_call(n).args) walk(*a);
                return;
            default: return;
        }
    };
    walk(node);
    return out;
}

RootInfo describe_root(const RootBlock& block, At& at) {
    const Root& first = *block.first;
    const Builder& b = *at.sys->builder;
    const Entry& a = *b.algebraic[static_cast<std::size_t>(first.k - 1)];
    RootInfo root;
    root.name = block_of(a.name);
    root.kind = a.kind;
    if (!a.dims.empty()) root.index = tuple_by_list(*b.space, a.dims, first.off);
    root.count = static_cast<int>(block.offs.size());
    root.value = element(at.sys->X, static_cast<long>(a.base) + first.off);
    if (!first.part) return root;
    const Part& part = *first.part;
    if (part.node->kind == ENode::Kind::Ref && first.read) {
        // A state or a parameter that is not a number: what the equation read.
        const Read& read = *first.read;
        const Entry* holder = read.array == 'y' ? entry_at(b.states, read.offset) : read.array == 'P' ? entry_at(b.param_layout, read.offset) : nullptr;
        if (holder) {
            RootInfo::Source source;
            source.name = block_of(holder->name);
            source.kind = read.array == 'y' ? (holder->kind.empty() ? "compartment" : holder->kind) : "parameter";
            if (!holder->dims.empty()) source.index = tuple_by_list(*b.space, holder->dims, read.offset - holder->base);
            source.value = part.value;
            root.source = std::move(source);
            return root;
        }
    }
    root.part = RootInfo::Text{equation_text(*part.node), worked_text(*part.node, part.operands, part.value), reads_of(*part.node, *first.eq, at.t, at.state)};
    return root;
}

// --- what is found ----------------------------------------------------------------------------

struct NonFinite {
    double t = 0;
    std::vector<StateGroup> states;
    int state_count = 0;
    std::vector<Flow> flows;
    std::optional<RootInfo> root;
    std::vector<std::string> others;
};

/// Where the derivative at `(t, y)` stops being a number, and why (`nonFiniteAt`).
std::optional<NonFinite> non_finite_at(System& sys, double t, const Vec& y) {
    std::unique_ptr<At> at = evaluated(sys, t, y);
    if (!at) return std::nullopt;
    std::vector<StateGroup> states =
        group_by(sys.builder->states, sys.nstate, [&](int i) { return !std::isfinite(at->d[static_cast<std::size_t>(i)]) || !std::isfinite(at->state[static_cast<std::size_t>(i)]); });
    if (states.empty()) return std::nullopt;
    FromAssembly found = from_assembly(*at);
    std::vector<RootInfo> roots;
    for (const RootBlock& b : found.blocks) roots.push_back(describe_root(b, *at));
    NonFinite out;
    out.t = t;
    for (const StateGroup& g : states) out.state_count += g.count;
    out.states = std::move(states);
    out.flows = std::move(found.flows);
    if (!roots.empty()) out.root = roots[0];
    for (std::size_t i = 1; i < roots.size(); i++) {
        const std::string& name = roots[i].name;
        if (std::find(out.others.begin(), out.others.end(), name) != out.others.end() || (out.root && name == out.root->name)) continue;
        out.others.push_back(name);
    }
    return out;
}

// --- the words --------------------------------------------------------------------------------

/// A value as it is shown: four figures, written as JavaScript writes a number.
std::string nf_number(double f) {
    if (!std::isfinite(f)) return js_text(f);
    if (f == 0) return "0";
    return js_text(std::strtod(js_to_exponential(f, 3).c_str(), nullptr));
}

std::string index_text(const std::optional<Tup>& index) { return (!index || index->empty()) ? "" : " [" + describe_tuple(*index) + "]"; }

/// Up to three names, then how many more.
std::string list_text(const std::vector<std::string>& names) {
    const std::size_t n = names.size();
    if (n <= MOST_NAMED) {
        if (n < 2) return n == 1 ? names[0] : "";
        return join(std::vector<std::string>(names.begin(), names.end() - 1), ", ") + " and " + names.back();
    }
    return join(std::vector<std::string>(names.begin(), names.begin() + MOST_NAMED), ", ") + " and " + std::to_string(n - MOST_NAMED) + " more";
}

/// What an operation read, the values most likely to be the cause first.
std::string reads_text(const std::vector<Reading>& reads) {
    if (reads.empty()) return "";
    auto telling = [](const std::optional<double>& v) { return !v || !std::isfinite(*v) || *v <= 0; };
    std::set<std::size_t> keep;
    if (reads.size() <= MOST_READS) {
        for (std::size_t i = 0; i < reads.size(); i++) keep.insert(i);
    } else {
        std::vector<std::size_t> order;
        for (std::size_t i = 0; i < reads.size(); i++)
            if (telling(reads[i].value)) order.push_back(i);
        for (std::size_t i = 0; i < reads.size(); i++)
            if (!telling(reads[i].value)) order.push_back(i);
        keep.insert(order.begin(), order.begin() + MOST_READS);
    }
    std::vector<std::string> items;
    for (std::size_t i = 0; i < reads.size(); i++)
        if (keep.count(i)) items.push_back(reads[i].text + " = " + (reads[i].value ? nf_number(*reads[i].value) : std::string("?")));
    const std::size_t more = reads.size() - items.size();
    if (more > 0) return ", with " + join(items, ", ") + " and " + std::to_string(more) + " more";
    if (items.size() < 2) return ", with " + join(items, "");
    return ", with " + join(std::vector<std::string>(items.begin(), items.end() - 1), ", ") + " and " + items.back();
}

std::string root_sentence(const RootInfo& r, bool at_start) {
    const int more = r.count - 1;
    const std::string others = more > 0 ? " (and " + std::to_string(more) + " more of its indices)" : "";
    const std::string lead = at_start ? "Comes to " + nf_number(r.value) + " at the start" + (r.index ? " at " + describe_tuple(*r.index) : std::string()) + others
                                      : "It starts in " + r.name + index_text(r.index) + others;
    if (r.source) {
        const auto& s = *r.source;
        const std::string what = s.kind == "parameter"     ? "the parameter " + s.name + index_text(s.index) + ", which is"
                                 : s.kind == "compartment" ? "the compartment " + s.name + index_text(s.index) + ", which holds"
                                                           : "the state " + s.name + index_text(s.index) + ", which is";
        if (at_start) return lead + ": it reads " + what + " " + nf_number(s.value) + ".";
        return "It starts in " + what + " " + nf_number(s.value) + ", read by " + r.name + index_text(r.index) + others + ".";
    }
    if (r.part) return lead + ": " + r.part->text + " comes to " + r.part->worked + reads_text(r.part->reads) + ".";
    return at_start ? lead + "." : lead + ", which comes to " + nf_number(r.value) + ".";
}

std::string reach_text(const NonFinite& found, const System& sys) {
    const auto& states = found.states;
    std::vector<std::string> named;
    for (const StateGroup& s : states) {
        std::string index = (states.size() == 1 && s.count == 1 && !s.dims.empty()) ? index_text(tuple_by_list(*sys.builder->space, s.dims, s.first)) : "";
        named.push_back(s.name + index);
    }
    const bool compartments = std::all_of(states.begin(), states.end(), [](const StateGroup& s) { return s.kind == "compartment"; });
    const std::string noun = compartments ? "compartment" : "block";
    std::string text = states.size() == 1
                           ? "It reaches the " + noun + " " + named[0] + (found.state_count > 1 ? " (" + std::to_string(found.state_count) + " states)" : "")
                           : "It reaches " + std::to_string(states.size()) + " " + noun + "s, " + std::to_string(found.state_count) +
                                 " states in all: " + list_text(named);
    if (!found.flows.empty()) {
        std::vector<std::string> transfers, inflows, parts;
        for (const Flow& f : found.flows) {
            if (f.kind == "transfer") transfers.push_back(f.name);
            if (f.kind == "inflow") inflows.push_back(f.name);
        }
        if (!transfers.empty()) parts.push_back(std::string(transfers.size() == 1 ? "the transfer" : "the transfers") + " " + list_text(transfers));
        if (!inflows.empty()) parts.push_back(std::string(inflows.size() == 1 ? "the inflow" : "the inflows") + " " + list_text(inflows));
        text += ", through " + join(parts, " and ");
    }
    return text + ".";
}

/// The message for a run that stopped on a value that is not a number.
std::string message_of(const NonFinite& found, const System& sys, const std::optional<std::pair<double, double>>& step) {
    std::vector<std::string> lines;
    if (!step) {
        lines.push_back("The simulation produced a value that is not a number at t=" + js_text(found.t) + ".");
    } else {
        lines.push_back("The simulation produced a value that is not a number at t=" + js_text(step->first) + ".");
        lines.push_back("The state it held there gives numbers; a step of " + nf_number(step->second) + " past it does not.");
    }
    if (found.root) lines.push_back(root_sentence(*found.root, false));
    lines.push_back(reach_text(found, sys));
    const auto& others = found.others;
    if (!others.empty()) {
        const std::size_t rest = others.size() - 1;
        lines.push_back(rest == 0 ? others[0] + " starts one of its own as well."
                                  : others[0] + " and " + std::to_string(rest) + " more " + (rest == 1 ? "block" : "blocks") + " start one of their own as well.");
    }
    return join(lines, " ");
}

/// Whether numbers went in and an infinity came out: an overflow rather than a domain error.
bool overflows(const std::vector<Operand>& parts, double value) {
    if (!std::isinf(value)) return false;
    for (const Operand& p : parts)
        if (!p.value || !std::isfinite(*p.value)) return false;
    for (const Operand& p : parts)
        if (p.value && *p.value == 0) return false;
    return true;
}

std::string op_text(const std::string& op) { return (op == "*" || op == "/" || op == "^") ? op : " " + op + " "; }

/// An operation with its operands' values in place of their equations: `0/0`, `log(0)`.
std::string worked_text(const ENode& node, const std::vector<Operand>& parts, double value) {
    auto v = [&](std::size_t i) -> std::string {
        if (i > parts.size()) return "?";
        const auto& x = parts[i - 1].value;
        if (!x) return "?";
        std::string s = nf_number(*x);
        return *x < 0 ? "(" + s + ")" : s;
    };
    const std::string big = overflows(parts, value) ? ", too large for a number" : "";
    if (node.kind == ENode::Kind::Binary) return v(1) + op_text(as_binary(node).op) + v(2) + big;
    if (node.kind == ENode::Kind::Unary) return "-" + v(1);
    if (node.kind == ENode::Kind::Call) {
        if (parts.empty()) return nf_number(value);
        std::vector<std::string> args;
        for (const Operand& p : parts) args.push_back(nf_number(p.value ? *p.value : std::nan("")));
        return as_call(node).name + "(" + join(args, ", ") + ")" + big;
    }
    return nf_number(value);
}

// --- equations back to text -------------------------------------------------------------------

constexpr int UNARY = 7, POWER = 8, ATOM = 10;

int binary_precedence(const std::string& op) {
    if (op == "||") return 1;
    if (op == "&&") return 2;
    if (op == "==" || op == "~=") return 3;
    if (op == "<" || op == "<=" || op == ">" || op == ">=") return 4;
    if (op == "+" || op == "-") return 5;
    if (op == "*" || op == "/") return 6;
    return 0;
}

int precedence(const ENode& node) {
    switch (node.kind) {
        case ENode::Kind::Binary: return as_binary(node).op == "^" ? POWER : binary_precedence(as_binary(node).op);
        case ENode::Kind::Unary: return UNARY;
        case ENode::Kind::Cond: return 0;
        case ENode::Kind::Num: return as_num(node).value < 0 ? UNARY : ATOM;
        default: return ATOM;
    }
}

std::string text_of(const ENode& node);

std::string wrapped(const ENode& child, int tighter) { return precedence(child) < tighter ? "(" + text_of(child) + ")" : text_of(child); }

std::string text_of(const ENode& node) {
    switch (node.kind) {
        case ENode::Kind::Num: {
            const ENum& n = as_num(node);
            return js_text(n.value) + (n.unit ? "[" + *n.unit + "]" : std::string());
        }
        case ENode::Kind::Ref: {
            const ERef& r = as_ref(node);
            std::string out = r.name;
            if (r.by_list) {
                for (const auto& [list, index] : r.named) out += "[" + index + "]";
            } else {
                for (const auto& i : r.indices) out += "[" + (i ? *i : std::string()) + "]";
            }
            return out;
        }
        case ENode::Kind::Unary: return "-" + wrapped(*as_unary(node).operand, POWER);
        case ENode::Kind::Binary: {
            const EBinary& b = as_binary(node);
            if (b.op == "^") {
                const ENode& r = *b.right;
                std::string exponent = (r.kind == ENode::Kind::Unary && precedence(*as_unary(r).operand) >= ATOM) ? text_of(r) : wrapped(r, ATOM);
                return wrapped(*b.left, POWER) + "^" + exponent;
            }
            const int p = binary_precedence(b.op);
            return wrapped(*b.left, p) + op_text(b.op) + wrapped(*b.right, p + 1);
        }
        case ENode::Kind::Cond: {
            const ECond& c = as_cond(node);
            return wrapped(*c.test, 1) + " ? " + wrapped(*c.then, 1) + " : " + wrapped(*c.otherwise, 1);
        }
        case ENode::Kind::Call: {
            const ECall& c = as_call(node);
            std::vector<std::string> args;
            for (const auto& a : c.args) args.push_back(text_of(*a));
            return c.name + "(" + join(args, ", ") + ")";
        }
    }
    return "?";
}

// --- the run's side ---------------------------------------------------------------------------

// Whether a character goes on with a word, as JavaScript's `\w` reads one: an ASCII letter, digit
// or underscore, and nothing else.
bool word_character(char32_t c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_'; }

// `/not a number|non-finite|not-a-number|infinite|\bNaN\b/i`
bool about_non_numbers(const SolverError& e) {
    if (e.kind == "nonfinite") return true;
    std::string m = e.message;
    for (char& c : m)
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    for (const char* w : {"not a number", "non-finite", "not-a-number", "infinite"})
        if (m.find(w) != std::string::npos) return true;
    for (std::size_t at = m.find("nan"); at != std::string::npos; at = m.find("nan", at + 1)) {
        bool before = false, after = false;
        if (at > 0) {
            std::size_t start = at - 1, len;
            while (start > 0 && (static_cast<unsigned char>(m[start]) & 0xc0) == 0x80) start--;
            before = word_character(utf8_at(m, start, len));
        }
        if (at + 3 < m.size()) {
            std::size_t len;
            after = word_character(utf8_at(m, at + 3, len));
        }
        if (!before && !after) return true;
    }
    return false;
}

/// Explicit steps past the last state the solver held, from the shortest the clock tells
/// apart and four times longer each time, up to `up_to` or the first that shows a value
/// that is not a number (`stepPast`).
std::optional<std::pair<NonFinite, double>> step_past(System& sys, double t, const Vec& from, double up_to) {
    const std::size_t n = static_cast<std::size_t>(sys.nstate);
    if (from.size() < n) throw std::out_of_range("a state shorter than the system's");
    Vec y(from.begin(), from.begin() + static_cast<std::ptrdiff_t>(n));
    Vec f(n, 0.0);
    sys.rhs(f.data(), t, y.data());
    for (double v : f)
        if (!std::isfinite(v)) return std::nullopt;
    const double shortest = 4 * std::numeric_limits<double>::epsilon() * std::max(1.0, std::fabs(t));
    const double longest = std::max(up_to, 1024 * shortest);
    Vec z(n);
    for (double h = shortest; h <= longest; h *= 4) {
        for (std::size_t i = 0; i < n; i++) z[i] = y[i] + h * f[i];
        if (auto found = non_finite_at(sys, t + h, z)) return std::make_pair(std::move(*found), h);
    }
    return std::nullopt;
}

std::string where_text(const StateGroup& g, const System& sys) {
    if (g.dims.empty()) return "";
    const int more = g.count - 1;
    const std::string tail = more > 0 ? " (and " + std::to_string(more) + " more of its indices)" : "";
    return " at " + describe_tuple(tuple_by_list(*sys.builder->space, g.dims, g.first)) + tail;
}

}  // namespace

std::string equation_text(const ENode& node) {
    std::string text = text_of(node);
    std::vector<std::size_t> starts;   // where each character starts
    for (std::size_t i = 0; i < text.size(); i++)
        if ((static_cast<unsigned char>(text[i]) & 0xc0) != 0x80) starts.push_back(i);
    if (starts.size() <= LONGEST_PART) return text;
    const std::size_t keep = (LONGEST_PART - 1) / 2;
    return text.substr(0, starts[keep]) + ELLIPSIS + text.substr(starts[starts.size() - keep]);
}

bool explain_non_finite(SolverError& e, System& sys, const std::optional<StretchStart>& start, const HeldStep* held, double end) {
    if (e.kind == "aborted" || e.kind == "span") return false;
    std::lock_guard<std::mutex> one_at_a_time(nf_lock());
    std::optional<std::pair<double, Vec>> from;
    if (!e.last_y.empty() && std::isfinite(e.last_t)) from.emplace(e.last_t, e.last_y);
    else if (held && std::isfinite(held->t) && (!start || !(held->t < start->first))) from.emplace(held->t, held->y);
    std::vector<std::pair<double, const Vec*>> tries;
    if (from) {
        tries.emplace_back(from->first, &from->second);
        if (std::isfinite(e.t) && e.t != from->first) tries.emplace_back(e.t, &from->second);
    } else if (start && std::isfinite(start->first) && (!std::isfinite(e.t) || e.t == start->first)) {
        tries.emplace_back(start->first, &start->second);
    }
    auto said = [&](const NonFinite& found, const std::optional<std::pair<double, double>>& step) {
        e.solver_message = e.message;
        e.message = message_of(found, sys, step);
        std::optional<std::string> block;
        if (found.root) block = found.root->source ? found.root->source->name : found.root->name;
        if (!block && !found.states.empty()) block = found.states[0].name;
        if (block) e.block_name = block;
        return true;
    };
    for (const auto& [t, y] : tries) {
        std::optional<NonFinite> found;
        try {
            found = non_finite_at(sys, t, *y);
        } catch (...) {
            found = std::nullopt;
        }
        if (found) return said(*found, std::nullopt);
    }
    if (from && about_non_numbers(e)) {
        const double up_to = std::max(std::isfinite(e.t) ? 2 * std::fabs(e.t - from->first) : 0.0, std::isfinite(end) ? 1e-3 * std::fabs(end - from->first) : 0.0);
        std::optional<std::pair<NonFinite, double>> past;
        try {
            past = step_past(sys, from->first, from->second, up_to);
        } catch (...) {
            past = std::nullopt;
        }
        if (past) return said(past->first, std::make_pair(from->first, past->second));
    }
    return false;
}

std::vector<Json> start_warnings(System& sys, double t0, const Vec& y0) {
    std::lock_guard<std::mutex> one_at_a_time(nf_lock());
    std::vector<Json> out;
    for (const StateGroup& g : group_by(sys.builder->states, sys.nstate, [&](int i) { return !std::isfinite(element(y0, i)); })) {
        if (g.kind != "compartment") continue;
        out.push_back(Json::object({{"block", Json(g.name)},
                                    {"message", Json("Its initial value comes to " + nf_number(element(y0, g.at)) + where_text(g, sys) + ", so a run cannot start.")},
                                    {"stops", Json(true)}}));
    }
    if (!out.empty()) return out;
    std::unique_ptr<At> at = evaluated(sys, t0, y0);
    if (!at) return out;
    FromAssembly found = from_assembly(*at);
    std::set<int> stopping;
    for (const RootBlock& b : found.blocks) stopping.insert(b.first->k);
    for (const RootBlock& b : found.blocks) {
        RootInfo r = describe_root(b, *at);
        auto via = found.flows_of.find(b.first->k);
        std::string through;
        if (via != found.flows_of.end() && !via->second.empty())
            through = ", through " + std::string(via->second.size() == 1 ? "the transfer" : "the transfers") + " " + list_text(via->second) + ",";
        out.push_back(Json::object({{"block", Json(r.name)},
                                    {"message", Json(root_sentence(r, true) + " The run reads it" + through + " so it will stop at its first step.")},
                                    {"stops", Json(true)}}));
    }
    for (const RootBlock& b : from_the_rest(*at, stopping)) {
        RootInfo r = describe_root(b, *at);
        const std::string what = r.count > 1 ? "these values" : "this value";
        out.push_back(Json::object({{"block", Json(r.name)},
                                    {"message", Json(root_sentence(r, true) + " Only results read it, so a run goes on, with " + what + " at its first point.")},
                                    {"stops", Json(false)}}));
    }
    return out;
}

}  // namespace kompartment
