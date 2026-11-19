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

/// The series a run of a system can report, and where each label first comes among them.
struct OutputIndex {
    std::vector<Json> outputs;
    std::unordered_map<std::string, std::size_t> by_label;
};
/// `outputs` indexed by label (a label listed twice is found as the first).
std::shared_ptr<const OutputIndex> index_outputs(std::vector<Json> outputs);

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
    /// The series this run reports, described once for its build and handed to every run of
    /// it (a probabilistic run's realisations: Julia's `outputs_cache` and `label_index`),
    /// so that each does not describe them again.
    void share_outputs(std::shared_ptr<const OutputIndex> index) { described_ = std::move(index); }
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
    const OutputIndex& described();
    std::shared_ptr<const OutputIndex> described_;
};

/// `on_progress(fraction, t)` is called as the run goes; returning false stops the run.
using ProgressFunction = std::function<bool(double fraction, double t)>;

/// A system of equations standing over the model's own, integrated by a run's machinery in
/// its place -- restarted at every switch time, through the discrete events, with the
/// blocks that remember primed and fed, each compartment's own floor and the clock's
/// interpolation (the Julia package's `equations` in `run_project`; the local sensitivity's,
/// engine/localsens). `dydt(out, t, Y)` writes every element, `Y` the model's states first and
/// `y0` as long as it; `abstol` one per element; `jacobian` the solver's; `solver` the one
/// it is kept to whatever happens; `on_segment(from, interval)` told where each stretch
/// between restarts starts and the clock's interpolation interval. Nothing after the states
/// is floored at zero, but `held_with`, given, holds some with the states the floor holds.
struct Equations {
    RhsFunction dydt;
    Vec y0;
    Vec abstol;
    const JacobianSpec* jacobian = nullptr;
    std::string solver = "ndf";
    std::function<void(double from, double interval)> on_segment;
    /// Some entries weighed against others as well (`weight_floor` of the NDF).
    const WeightFloor* weight_floor = nullptr;
    /// The matrix Newton iterates with, made a block at a time (`iteration_matrix` of the NDF).
    IterationMatrixFactory iteration_matrix;
    /// Some entries held with the model's states the floor holds (`held_with` of the NDF).
    const Vec* held_with = nullptr;
};

struct RunOptions {
    ProgressFunction on_progress;
    bool on_grid = false;
    std::optional<std::string> solver;   // run with this one, whatever the policy says
    RowPool* rows = nullptr;
    /// Far-field layers to hold instead of laying them out, as a split run's parts are given
    /// the whole model's (`whole_layers`); none: every path lays out its own.
    const FarfLayerMap* layers = nullptr;
    /// Equations integrated in place of the model's own (see `Equations`), the caller's for
    /// the length of the run; none: the model's.
    const Equations* equations = nullptr;
    /// A run that builds its own system: how many bins a split packs the model's parts into,
    /// one per thread -- none: the machine's cores (engine/split, `run_whole_or_split`).
    std::optional<int> threads;
    /// False for a run that is itself one of several side by side, which is not split.
    bool nest = true;
};

/// Runs a project, on the system given or one built here. A run that builds its own system
/// is solved in its independent parts on several threads when `simulation.split` says so and
/// the plan agrees (`run_whole_or_split`, engine/split), and `stats["split"]` says what was
/// done; `solver`, `rows` and `layers` are then not asked for.
Results run_project(std::shared_ptr<const Project> project, std::shared_ptr<System> system = nullptr, const RunOptions& options = {});

/// The dimension of `dims` that is the model's material list, or a sub-set of it (never a
/// mapping onto it); none when there is none (`_material_dim`).
std::optional<std::string> material_dim(const System& sys, const std::vector<std::string>& dims);

/// A solver's steps per method (`steps_by`) and its switches between them, added to `into`
/// (`add_method_steps!`).
void add_method_steps(Json& into, const Json& from);

/// Every series a run of this system can report.
std::vector<Json> outputs_of(System& sys, const Project& project);

/// Every material's unit, by its name (`material_units`).
std::unordered_map<std::string, std::string> material_units(const System& sys);

/// The series one layout entry stands for (`describe_entry`), added to `out`: one per index
/// tuple, or one -- its kind, block, nuclide, index, label, unit, source and offset.
void describe_entry(std::vector<Json>& out, const System& sys, const Entry& entry, const std::string& kind, const char* source,
                    const std::unordered_map<std::string, std::string>& units);

/// The absolute tolerance per state (empty when nothing asked for more than the model's
/// own), and the states that cannot go negative.
std::vector<double> absolute_tolerance(const Project& project, const System& sys);
std::vector<std::uint8_t> non_negative_states(const Project& project, const System& sys);

}  // namespace kompartment
