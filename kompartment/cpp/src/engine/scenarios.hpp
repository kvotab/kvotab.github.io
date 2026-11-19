// A model run once per scenario (`run_scenarios`, the Julia package's api.jl): the
// scenario list's every index pinned in turn, each run a run of its own, side by side on
// threads where asked. Their results go into one file as io/resultfile's `scenarios_tree`
// writes them.
//
//     auto runs = run_scenarios(raw);                    // {"A", Results}, {"B", Results}, ...
//     save_scenarios(runs, "scenarios.h5");

#pragma once

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "engine/runner.hpp"
#include "util/json.hpp"

namespace kompartment {

/// Runs a model (its file's dictionary, which is not changed) once for each scenario --
/// those named, or every one its scenario list holds -- and gives the runs by scenario, in
/// that order. `settings` are set over the model's `simulation` first, key by key. With more
/// than one thread the scenarios run side by side, each on one thread (and then none is split
/// into parts). A model without a scenario list is refused with an `ArgumentError`, in the
/// Julia package's words; what a run throws comes out once every thread has stopped.
std::vector<std::pair<std::string, Results>> run_scenarios(const Json& raw, const std::optional<std::vector<std::string>>& names = std::nullopt,
                                                           int threads = 1, const Json& settings = Json());

}  // namespace kompartment
