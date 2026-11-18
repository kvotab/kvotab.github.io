// What the builder's parts share with each other and with nothing else.

#pragma once

#include <optional>
#include <set>
#include <string>
#include <vector>

#include "engine/builder.hpp"

namespace kompartment::detail {

/// The index of `dim` standing for an index of its root list: none when `dim` is a root
/// or the name is not its root's, absent when the root index has no counterpart in `dim`.
struct DerivedIndex {
    enum class Kind { None, Absent, Found };
    Kind kind;
    std::string name;
};
DerivedIndex derived_index(const IndexSpace& space, const std::string& dim, const std::string& index_name);

/// Which dimension of `target` each written index pins -- by name, not by position.
Tup pin_indices(const IndexSpace& space, const Entry& target, const std::vector<std::optional<std::string>>& indices,
                const std::string& name, const std::optional<std::string>& owner_name, const Entry::Context* context);

/// The index positions a block occupies by being what it is: a transfer is one of the
/// transfers and knows its two ends; a compartment is one of the compartments.
const Entry::Context* implicit_indices(Entry& owner);

/// The dimensions along which an entry's equation never changes.
std::vector<std::string> flat_dimensions(const IndexSpace& space, const Entry& entry);

/// An entry's trees, each distinct equation's once and in the order they first appear.
std::vector<ENodePtr> distinct_asts(const Entry& a);

/// `from`, `from + 1`, ... `count` of them.
std::vector<int> iota(int from, int count);

std::shared_ptr<Stmt> make_stmt(const EntryPtr& a, std::vector<int> outs, TNodePtr tree, int width, int sub = 0, bool multiply = false);
std::shared_ptr<Stmt> make_stmt(const EntryPtr& a, int out, TNodePtr tree, int width, int sub = 0, bool multiply = false);

/// The Python engine's `_js_number`: `Number(v)` with Python's reading of text.
double builder_number(const Json& v);

}  // namespace kompartment::detail
