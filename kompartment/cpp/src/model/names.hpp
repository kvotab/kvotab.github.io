// Names, sub-systems and how a name written in an equation finds its block.
//
// A block has a local name (`Water`) and lives in a sub-system, a dotted path
// (`NearField.Geosphere`; the top level is ""). Its qualified name is the two
// joined, `NearField.Geosphere.Water`. An equation refers to a block by a
// name resolved from the sub-system it is written in: a dotted name is a full
// path from the top level; a bare name is looked up in the writer's own
// sub-system first, then at the top level -- never in between.

#pragma once

#include <functional>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

inline constexpr char SEPARATOR = '.';

/// What a block, an index list or a sub-system component may be called:
/// letters, digits and underscore, not starting with a digit.
bool is_name(std::string_view name);
bool is_name(const Json& name);

/// What is wrong with `name` as a block's local name, or nothing.
std::optional<std::string> name_problem(const Json& name);

/// The components of a sub-system path; "" has none.
std::vector<std::string> path_parts(std::string_view path);

/// `system` and `name` joined into a qualified name.
std::string qualify(std::string_view system, std::string_view name);

/// The sub-system a path is inside: `A.B.C` -> `A.B`, `A` -> "".
std::string parent_of(std::string_view path);

/// The last component of a path: `A.B.C` -> `C`.
std::string base_name(std::string_view path);

/// Whether `path` is `ancestor` or somewhere inside it; everything is within "".
bool is_within(std::string_view path, std::string_view ancestor);

/// Whether a sub-system path is well formed: every component a name.
bool is_valid_path(std::string_view path);

/// The sub-system a raw block lives in.
std::string system_of(const Json& block);

/// A raw block's qualified name.
std::string qualified_name(const Json& block);

/// The qualified name a reference written in `system` means, or nothing. `known(qname)`
/// says whether a block of that name exists.
std::optional<std::string> resolve_reference(std::string_view reference, std::string_view system,
                                             const std::function<bool(const std::string&)>& known);

/// How a reference to `target` is written from inside `system`.
std::string reference_from(std::string_view target, std::string_view system,
                           const std::function<bool(const std::string&)>& known);

/// JavaScript's `localeCompare` for identifier-like names: case folded first, lower case
/// before upper on a tie.
std::pair<std::string, std::string> locale_key(std::string_view s);
/// `a.localeCompare(b) < 0` by that key.
bool locale_less(std::string_view a, std::string_view b);

/// Every sub-system a model has, shallowest first: every prefix of every declared path,
/// transport path and block's sub-system.
std::vector<std::string> system_paths(const Json& declared, const Json& transports,
                                      const std::vector<std::string>& block_systems);

/// Text in lower case (ASCII letters and the Latin-1 and Latin Extended-A letters with
/// one lower-case form; the rest as they are).
std::string lowercase(std::string_view s);
std::string uppercase(std::string_view s);

/// The code point of the UTF-8 character starting at byte `i`; `len` says how many bytes it takes.
char32_t utf8_at(std::string_view s, std::size_t i, std::size_t& len);

/// Whether `s` starts or ends with `what`.
inline bool starts_with(std::string_view s, std::string_view what) { return s.substr(0, what.size()) == what; }
inline bool ends_with(std::string_view s, std::string_view what) {
    return s.size() >= what.size() && s.substr(s.size() - what.size()) == what;
}

/// `parts` joined with `sep`.
std::string join(const std::vector<std::string>& parts, std::string_view sep);
/// `s` split at every `sep` (empty pieces kept).
std::vector<std::string> split(std::string_view s, char sep);

}  // namespace kompartment
