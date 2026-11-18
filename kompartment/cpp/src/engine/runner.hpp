// Runs a project and collects its results (src/sim/runner.js): the solver is
// driven over the output grid -- restarted at every switch time, every jump and
// every discrete event -- and only the states are kept. Every other series (an
// expression, a rate, a table read at the clock, what a recorder holds) is
// worked out from (t, y) when it is asked for, as the application does.

#pragma once

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "engine/farfield.hpp"
#include "engine/farfield_semi.hpp"
#include "engine/project.hpp"
#include "engine/system.hpp"
#include "solvers/solvers.hpp"

namespace kompartment {

inline constexpr int MAX_SOLVER_POINTS = 4000;
inline constexpr int MAX_EVENTS = 10000;
inline constexpr const char* POINT_LIST = "Time point";

/// What a run leaves on the system that reading its results depends on.
struct RunState {
    std::vector<Recorder> mem;
    std::vector<double> dis;
    std::vector<std::vector<double>> sampled;
    double min_change = 0, origin = 0;
    std::vector<LaplaceRunState> laplace;   // the semi-analytical paths' histories
};
RunState run_state(const System& sys);
void restore_run_state(System& sys, const RunState& state);

/// What a run produced: the states at every output time, and every other series worked
/// out from them on demand.
class Results {
public:
    std::shared_ptr<const Project> project;
    std::shared_ptr<System> system;
    std::vector<double> t;
    std::vector<Vec> y;
    Json stats;    // the solver's counts
    Json timing;   // build_ms, solve_ms, total_ms
    RunState kept;

    /// Every series the run can report, as descriptors (label, block, kind, index, unit,
    /// source, offset...), in the application's order.
    const std::vector<Json>& outputs();
    std::vector<std::string> labels();
    bool has(const std::string& label);
    const Json& find_output(const std::string& label);
    std::vector<double> series(const std::string& label);
    std::vector<double> series(const Json& output);
    /// Several series at once: one pass over the run.
    std::vector<std::vector<double>> series_many(const std::vector<Json>& outputs);
    /// The algebraic slots `need` at every output time: a row per time.
    std::vector<std::vector<double>> algebraic_rows(const std::vector<int>& need);
    /// The states held at zero by the non-negative constraint, and for how many steps:
    /// `{label, steps, fraction}`, the most held first.
    std::vector<Json> held_at_zero();
    /// The mass-balance audit, when `simulation.mass_balance` is on; null otherwise.
    Json mass_balance();
    /// One line on how the run went: solver, steps, time taken.
    std::string summary();
    /// The run as the application's CSV export: a time column, then one column per series.
    std::string to_csv(const std::vector<Json>* outputs = nullptr, double time_origin = 0.0);

private:
    std::vector<Json> outputs_;
    bool described_ = false;
    std::unordered_map<std::string, std::size_t> by_label_;
};

/// `on_progress(fraction, t)` is called as the run goes; returning false stops the run.
using ProgressFunction = std::function<bool(double fraction, double t)>;

struct RunOptions {
    ProgressFunction on_progress;
    bool on_grid = false;
    std::optional<std::string> solver;   // run with this one, whatever the policy says
    RowPool* rows = nullptr;
    /// Far-field layers to hold instead of laying them out, as a split run's parts are given
    /// the whole model's (`whole_layers`); none: every path lays out its own.
    const FarfLayerMap* layers = nullptr;
};

/// Runs a project, on the system given or one built here.
Results run_project(std::shared_ptr<const Project> project, std::shared_ptr<System> system = nullptr, const RunOptions& options = {});

/// Every series a run of this system can report.
std::vector<Json> outputs_of(System& sys, const Project& project);

/// The absolute tolerance per state (empty when nothing asked for more than the model's
/// own), and the states that cannot go negative.
std::vector<double> absolute_tolerance(const Project& project, const System& sys);
std::vector<std::uint8_t> non_negative_states(const Project& project, const System& sys);

}  // namespace kompartment
