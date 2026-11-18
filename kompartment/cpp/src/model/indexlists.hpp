// The rules of Kompartment's index lists (src/domain/indexlists.js).
//
// Every block is indexed by an ordered list of index lists -- its dimensions
// -- and holds one value per combination of their indices. A list is a root,
// a sub-set of another list (`sub_set_of`), or a mapping onto another
// (`mapping: {to, pairs}`). Two lists are built in: the material catalogue
// (`for_contaminants`, `Contaminants`) and the radionuclides (`for_nuclides`,
// `Radionuclides`), a sub-set of it. Three are derived from the model and
// never written to the file: `Elements`, `Compartments` and `Transfers`.
//
// The lists here are raw: a list of dictionaries as a model file holds them.

#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

inline constexpr const char* MATERIAL_LIST = "Contaminants";
inline constexpr const char* NUCLIDE_LIST = "Radionuclides";
inline constexpr const char* ELEMENT_LIST = "Elements";
inline constexpr const char* COMPARTMENT_LIST = "Compartments";
inline constexpr const char* TRANSFER_LIST = "Transfers";

/// What the built-in lists used to be called, for files written then ("" for the others).
std::string was_called(std::string_view list);

/// Whether a block of `kind` may be indexed by `Compartments` or `Transfers`.
bool is_auto_dim_kind(std::string_view kind);

/// The words that stand for a transfer's own two ends inside its equations.
inline constexpr const char* SOURCE_INDEX = "_source_";
inline constexpr const char* TARGET_INDEX = "_target_";

/// An index's name: the text itself, or a dictionary's `name` (null when it has none).
Json index_name(const Json& index);

/// The list of that name among raw lists, or null.
const Json& find_list(const Json& lists, const Json& name);
const Json& find_list(const Json& lists, std::string_view name);

/// The list a list is taken from (its `sub_set_of`, or what its mapping maps to), or null.
Json parent_list_name(const Json& lst);

/// How a list reaches its root; `above` is the chain of lists above it, nearest first,
/// each with whether the step to it is a mapping.
struct Lineage {
    Json root;
    bool mapped = false;
    std::vector<std::pair<std::string, bool>> above;
};
Lineage lineage(const Json& lists, const Json& name);
Json root_of(const Json& lists, const Json& name);

/// Whether a block of `kind` may be indexed by `lst`, and why not in words.
bool list_applies(const Json& lst, std::string_view kind);
std::string list_applies_why(const Json& lst, std::string_view kind);

/// The first pair of dimensions that are one dimension twice.
struct DimensionClash {
    std::string a, b;
    std::optional<std::string> root;
    std::string how;   // siblings, grouping, sub_set, blocks
    std::optional<std::string> below, above;
};
std::optional<DimensionClash> clashing_dimensions(const Json& lists, const std::vector<std::string>& dims);
std::string clashing_dimensions_why(const std::optional<DimensionClash>& clash);

/// What a transfer between two blocks is indexed by: the indices both ends have.
struct SharedDims {
    struct Shared {
        std::string from, to, dims;
    };
    std::vector<std::string> dims;
    std::vector<Shared> shared;
};
/// `source`/`target` are the two ends' dimensions, null pointers for the model boundary.
std::optional<SharedDims> shared_dims(const Json& lists, const std::vector<std::string>* source,
                                      const std::vector<std::string>* target);

/// The flux's dimensions one of its ends cannot follow.
std::vector<std::string> summed_dims(const Json& lists, const std::vector<std::string>& flux_dims,
                                     const std::vector<std::string>& end_dims);

/// Whether the nuclides decay along a dimension.
bool is_decay_dim(const Json& lists, const Json& name, const Json& material);

// --- reading a file ----------------------------------------------------------------------------------

/// Renames the built-in lists in a file written under their old names.
Json rename_built_in_lists(const Json& raw);
/// Tells the two material roles apart in a file that has them as one list.
Json split_material_roles(const Json& raw);
/// The `nuclides: [...]` shorthand as the two lists it stands for.
Json desugar_nuclides(const Json& raw);
/// The lists with the derived element list added, when the model has none.
Json derive_elements(const Json& lists);
/// The lists with `Compartments` and `Transfers` added.
Json derive_block_lists(const Json& lists, const Json& model);

/// A name not among `taken`: `want`, or `want2`, `want3`, ...
std::string free_name(const std::vector<std::string>& taken, const std::string& want);

}  // namespace kompartment
