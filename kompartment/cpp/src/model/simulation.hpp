// The simulation settings: their defaults, the solvers and the time units.

#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

/// In the order the application offers them (`SOLVER_IDS` in src/ode/solvers.js).
const std::vector<std::string>& solver_ids();
inline constexpr const char* DEFAULT_SOLVER = "ndf";
const std::vector<std::string>& spacings();        // log, linear, series, solver, both
const std::vector<std::string>& series_kinds();    // log, linear, times
const std::vector<std::string>& samplings();       // latin, random
const std::vector<std::string>& split_modes();     // auto, on, off
inline constexpr int MAX_OUTPUT_POINTS = 100000;

/// A time unit as a fraction of a year, or 0 for a word that is not one.
double time_unit_years(std::string_view unit);

/// What the application uses when a file leaves a setting out (a dictionary of its own
/// each time).
Json simulation_defaults();

/// How many points the shorthand grid is spread over (`shorthandPoints` in the
/// application): the count in `output_points` where a grid can be spread over it
/// (2..MAX_OUTPUT_POINTS, halves rounded up), and the default otherwise.
int shorthand_points(const Json& count);

/// The label the application gives a solver, or "" for an id it does not have.
std::string solver_label(std::string_view id);


}  // namespace kompartment
