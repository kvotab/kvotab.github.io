// The index-list model of one project: enabled indices, strides, and the tables
// that carry a position from one list into another (`IndexSpace` in
// src/domain/indexlists.js).
//
// Positions are counted from 0, as the application counts them, and a
// translation table holds -1 where a position has no counterpart.

#pragma once

#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

struct IndexSpaceError : std::runtime_error {
    std::optional<std::string> detail;
    explicit IndexSpaceError(const std::string& message, std::optional<std::string> detail_ = std::nullopt)
        : std::runtime_error(message), detail(std::move(detail_)) {}
};

/// An index tuple by list: which index of each list, in the order they were set.
class Tup {
public:
    using Item = std::pair<std::string, std::string>;
    Tup() = default;
    Tup(std::initializer_list<Item> items) : items_(items) {}
    const std::string* find(std::string_view list) const noexcept {
        for (const auto& it : items_)
            if (it.first == list) return &it.second;
        return nullptr;
    }
    bool has(std::string_view list) const noexcept { return find(list) != nullptr; }
    void set(std::string_view list, std::string index) {
        for (auto& it : items_)
            if (it.first == list) {
                it.second = std::move(index);
                return;
            }
        items_.emplace_back(std::string(list), std::move(index));
    }
    /// This tuple with `other`'s entries set over it (Julia's `merge`).
    Tup merged(const Tup& other) const {
        Tup out = *this;
        for (const auto& it : other.items_) out.set(it.first, it.second);
        return out;
    }
    std::size_t size() const noexcept { return items_.size(); }
    bool empty() const noexcept { return items_.empty(); }
    const std::vector<Item>& items() const noexcept { return items_; }
    auto begin() const noexcept { return items_.begin(); }
    auto end() const noexcept { return items_.end(); }

private:
    std::vector<Item> items_;
};

/// One index of a list: its name and whether it is switched on.
struct ListIndex {
    std::string name;
    bool enabled;
};

struct IndexList {
    std::string name;
    bool for_contaminants = false;
    bool for_nuclides = false;
    bool for_scenarios = false;
    std::optional<std::string> sub_set_of;
    Json mapping;                                        // null: none
    std::vector<ListIndex> indices;
    std::vector<ListIndex> enabled;
    int size = 0;
    std::unordered_map<std::string, int> position_of;   // enabled name => position
    std::unordered_set<std::string> names;
    std::optional<std::string> root_name;
    std::vector<int> up;                                 // position here => position in the root (-1: none)
    std::vector<int> down;                               // position in the root => position here (-1: none)
    bool is_scenario = false;

    std::optional<int> position(std::string_view index) const {
        auto it = position_of.find(std::string(index));
        return it == position_of.end() ? std::nullopt : std::optional<int>(it->second);
    }
};

/// How a position in one list translates into another.
struct Relation {
    enum class Kind { Same, Map };
    Kind kind;
    std::shared_ptr<const std::vector<int>> table;   // for Map
    bool partial = false;
};

/// One target dimension's term of a projection.
struct ProjTerm {
    int stride;
    std::string dim;
    int fixed;   // -1 when the position comes from the source
    int from;    // which source dimension (from 0), -1 when fixed
    std::shared_ptr<const std::vector<int>> table;   // null: carried directly
    bool partial;
};

/// What a projection is being made for, for its messages.
struct ProjContext {
    std::optional<std::string> owner, target;
};

class IndexSpace {
public:
    IndexSpace() = default;
    /// From normalised lists (dictionaries with `name`, `indices`, ...).
    explicit IndexSpace(const Json& raw_lists);

    bool has_list(std::string_view name) const { return lists_.count(std::string(name)) != 0; }
    const IndexList& get_list(std::string_view name) const;
    const IndexList* find_list(std::string_view name) const;
    int list_size(std::string_view name) const { return get_list(name).size; }
    std::vector<std::string> index_names(std::string_view name) const;
    const std::vector<std::string>& order() const { return order_; }
    const IndexList* material_list() const;
    const IndexList* nuclide_list() const;

    const std::vector<int>& strides(const std::vector<std::string>& dims) const;
    int width(const std::vector<std::string>& dims) const;
    int offset_of(const std::vector<std::string>& dims, const std::vector<std::string>& tuple) const;
    /// The index names at an offset of a block of dimensions `dims`.
    std::vector<std::string> tuple_at(const std::vector<std::string>& dims, int offset) const;
    /// For every offset of a block of these dimensions, its position along each dimension:
    /// one vector per dimension, in offset order (the last dimension fastest).
    std::vector<std::vector<int>> positions(const std::vector<std::string>& dims) const;

    /// How a position in `to_list` translates into `from_list`; none for unrelated lists.
    std::optional<Relation> relate(const std::string& from_list, const std::string& to_list) const;
    std::vector<std::string> missing_from(const std::string& dim, const std::string& frm) const;

    /// How to read a block of `target_dims` from inside one of `source_dims`: one term per
    /// target dimension, carried directly, through a sub-set's or a mapping's table, or
    /// pinned to one index.
    std::vector<ProjTerm> projection(const std::vector<std::string>& source_dims, const std::vector<std::string>& target_dims,
                                     const Tup* fixed_indices = nullptr, const ProjContext* context = nullptr) const;

    // --- scenarios ---
    const std::optional<std::string>& scenario_root() const { return scenario_root_; }
    const std::optional<std::string>& scenario() const { return scenario_; }
    std::vector<std::string> scenarios() const;
    bool is_scenario_dim(std::string_view name) const;
    /// Chooses a scenario; none when it is not one of them.
    std::optional<std::string> set_scenario(const std::optional<std::string>& name);
    std::optional<std::string> scenario_index_in(std::string_view dim) const;
    std::vector<std::string> without_scenarios(const std::vector<std::string>& dims) const;
    /// `tuple` with the scenario's index set on each scenario dimension of `dims`.
    Tup pin_scenario(const std::vector<std::string>& dims, const Tup& tuple) const;

private:
    void resolve();
    IndexList& place(IndexList& lst, std::unordered_set<std::string>& seen);
    void place_scenarios();
    std::optional<Relation> relate_uncached(const std::string& from_list, const std::string& to_list) const;

    std::unordered_map<std::string, IndexList> lists_;
    std::vector<std::string> order_;
    mutable std::map<std::vector<std::string>, std::vector<int>> stride_cache_;
    std::optional<std::string> scenario_root_;
    std::optional<std::string> scenario_;
    mutable std::map<std::pair<std::string, std::string>, std::optional<Relation>> relate_cache_;
};

/// A block's dimensions as written, each used once.
std::vector<std::string> normalise_dims(const Json& dims);

}  // namespace kompartment
