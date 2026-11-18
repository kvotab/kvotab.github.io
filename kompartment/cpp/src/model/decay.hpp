// Radionuclide data: half-lives, elements and the decay chains between them.
//
// ICRP Publication 107 as Kompartment carries it (compiled in, see
// tools/embed_data.py). Worked out from it, the way the application works
// them out: a nuclide's half-life in years (infinite for a stable one, none
// for a name the table does not know), its element, and the decay pairs among
// a set of nuclides when a model states none -- each modelled nuclide's
// daughters, with the branching that reaches them through the members that
// are not modelled (`collapse` in src/domain/decaydb.js).

#pragma once

#include <limits>
#include <optional>
#include <string>
#include <string_view>
#include <tuple>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

namespace icrp107_data {
struct Progeny {
    const char* name;
    double branching;
};
struct Row {
    const char* name;
    double half_life;   // years; negative: stable
    int first;          // its progeny, in PROGENY
    int count;
};
extern const Progeny PROGENY[];
extern const Row ROWS[];
extern const int ROW_COUNT;
}  // namespace icrp107_data

inline constexpr const char* STABLE = "stable";

/// The table's names, in its order.
const std::vector<std::string>& known_nuclides();
bool is_known_nuclide(std::string_view name);

/// Half-life in years; infinite when stable, none when unknown.
std::optional<double> half_life(std::string_view name);

/// Whether a half-life as a file may write it means "does not decay".
bool means_stable(const Json& v);

/// The element symbol of a nuclide's name (`Cs-137` -> `Cs`), or none.
std::optional<std::string> element_of(std::string_view nuclide);

/// The decay pairs a set of nuclides makes, `(parent, daughter, branching)`, the
/// branching being the total probability that one decay of the parent reaches the
/// daughter through nuclides that are not in the set. A daughter longer-lived than
/// `ceiling` years is a sink rather than passed through.
std::vector<std::tuple<std::string, std::string, double>> default_chains(
    const std::vector<std::string>& nuclides, double ceiling = std::numeric_limits<double>::infinity(),
    double min_branching = 1e-9);

/// Whether a model states its own decay pairs, as the application reads `chains`: any
/// list does, an empty one included, and nothing JavaScript reads as false.
inline bool chains_stated(const Json& chains) { return js_truthy(chains); }

}  // namespace kompartment
