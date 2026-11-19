// Solving a model in its independent parts, side by side (src/sim/partition.js
// and src/sim/split.js, as the Julia package's engine/split.jl ports them).
//
// A large assessment is rarely one problem: its radionuclides fall into groups
// with no path between them -- each decay chain held together by its own
// ingrowth and nothing joining one chain to the next -- and solved as one
// system every state moves at the step size the worst of them needs. The
// partition finds those groups from the Jacobian's pattern; the plan decides
// whether solving them apart pays for the model in hand; the run packs the
// *jobs* -- sets of materials whose states reach no other job's -- into one bin
// per thread, builds each bin (the model with every other material switched
// off) and solves it on the model's output grid at its own steps, and files
// every state back into the whole model's vector by name. What comes out is an
// ordinary `Results` of the whole model whose states were integrated in
// pieces, worked out afterwards on the whole model's system.
//
// **Not bit for bit the whole model's.** Each bin takes the steps its own
// states need, which is the point, and so agrees with the whole to within the
// tolerance. The jobs of one bin share its steps, so how they are packed --
// which follows the number of threads -- changes the last digits; a bin is the
// same run on whichever thread takes it, and the Julia package's run of it to
// the bit.
//
// **Threads.** A bin is a thread of its own: it builds its own project and
// system, shares nothing with the others but the model it was cut from and the
// whole model's far-field layers, both only read. The numbers auto weighs a
// split by are this engine's own (`SPLIT_CONSTANTS`), measured here.
//
// **Refused, whatever the setting, where it would be wrong or cannot work:** a
// model the partition declines (a delay, a snapshot or an event reaches across
// parts without showing in the Jacobian; a far-field path worked out
// semi-analytically); output at the solver's own steps, which differ in every
// part; a model with no materials to divide by; one part holding everything;
// one thread; a run that is itself one of several side by side; and a min/max
// whose target reads states of more than one job, which no part can give back.
//
// **Carried back:** besides the states, each part's run leaves its recorders'
// histories; a min/max or running mean is taken from the job that owns the
// states its target reads, and put on the whole system, so their series are
// the run's. The far-field paths' matched layers are the whole model's: a part
// alone would size them by its own nuclides and solve another path.
//
// Parts, jobs, bins and states are numbered from 0, as the application numbers them.

#pragma once

#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "engine/project.hpp"
#include "engine/recorders.hpp"
#include "engine/runner.hpp"
#include "engine/system.hpp"
#include "solvers/pattern.hpp"
#include "util/json.hpp"

namespace kompartment {

// --- the partition ---------------------------------------------------------------------------------

/// The states of each part, from a sparsity pattern (`statePartition`): two states belong
/// together when one reads the other, in either direction. `of[i]` is the part state `i`
/// belongs to, numbered in the order the states first appear, so part 0 holds state 0 -- a
/// property of the model, not of how the components were found. No pattern: no parts.
struct StatePartition {
    int count = 0;
    std::vector<int> of;
    std::vector<int> sizes;
    int largest = 0;
};
StatePartition state_partition(const Pattern* pattern);

/// Why this system may not be split, or none when it may (`whyNotSplit`). It names the first
/// thing it cannot account for rather than guessing.
std::optional<std::string> why_not_split(const System& sys);

/// The partition, with the reason when there is not one (`partitionOf`). Refused: one part,
/// `of` and `sizes` none.
struct Partition {
    bool ok = false;
    std::optional<std::string> refusal;
    int count = 1;
    std::optional<std::vector<int>> of;
    std::optional<std::vector<int>> sizes;
    int largest = 0;
};
Partition partition_of(const System& sys);

// --- names and materials of the states -------------------------------------------------------------

/// A name for each state that is the same for the same state in any build of the model,
/// whichever materials that build has (`stateKeys`): the block, its index, and for a
/// far-field path the cell; a mass-balance budget by its term and family. None when two
/// states come out with one name.
std::optional<std::vector<std::string>> state_keys(const System& sys);

/// The material each state belongs to, or none for one that is not per material (`stateMaterials`).
std::vector<std::optional<std::string>> state_materials(const System& sys);

// --- the jobs --------------------------------------------------------------------------------------

/// Materials whose states reach no other job's, and how many states they own.
struct SplitJob {
    std::vector<std::string> materials;
    long long states = 0;
    bool operator==(const SplitJob& o) const { return materials == o.materials && states == o.states; }
};

/// An entry of a recorder that remembers (a min/max, a running mean): its name, the job whose
/// states its target reads, and its place in the whole system's histories.
struct SplitRecorder {
    std::string key;
    int job = 0;
    int slot = 0;
    bool operator==(const SplitRecorder& o) const { return key == o.key && job == o.job && slot == o.slot; }
};

/// The jobs a model's parts make (`splitJobs`): `why` is the refusal, none when there are jobs.
struct SplitJobs {
    std::optional<std::string> why;
    std::vector<SplitJob> jobs;
    std::vector<int> owner;   // per state: its job
    std::vector<std::string> keys;
    int parts = 0;
    std::vector<SplitRecorder> recorders;
};

/// The jobs: sets of materials, each with the states it owns. A job is built by switching
/// every other material off, so parts that share a material are merged. A part with no
/// material at all is in every job's build and is taken from whichever job is smallest.
SplitJobs split_jobs(const System& sys);

// --- the plan --------------------------------------------------------------------------------------

/// The numbers auto weighs a split by (the Julia package's `SplitConstants`): the
/// application's formulas, with what this engine measured (`SPLIT_CONSTANTS`). The defaults
/// are the Python package's, under which a plan is the Python package's plan.
///
/// - `shared_work`: the share of a whole derivative call every part pays whatever its size
///   -- the solver's own work per step.
/// - `auto_states`: auto splits a model it has not timed only from this many states up.
/// - `auto_solve_ms`: auto splits a model it has timed only when a whole solve took this long.
/// - `auto_gain`: how much faster auto wants the split to be expected, or measured, to be;
///   `auto_gain_untimed` the same for a model whose solve time is not known yet.
/// - `start_ms`: what a split costs once per run beyond its bins' builds and solves.
/// - `build_fixed`: the share of a whole build each bin pays whatever it holds, until a split
///   of the model has measured it; none takes a bin's build to shrink with its share of the
///   states, as the Python package does.
/// - `build_contention`: how much longer every bin's build takes for each other bin built at
///   the same time. Above zero, auto weighs every number of bins up to one per thread and
///   takes the quickest; at zero, one bin per thread.
/// - `untimed_bins`: the most bins auto packs a model into before a run of it has been timed
///   (0: one per thread).
struct SplitConstants {
    double shared_work = 0.1;
    long long auto_states = 10000;
    double auto_solve_ms = 1500.0;
    double auto_gain = 1.2;
    double auto_gain_untimed = 2.0;
    double start_ms = 650.0;
    std::optional<double> build_fixed;
    double build_contention = 0.0;
    long long untimed_bins = 0;
};

/// This engine's own (see split.cpp for how they were measured).
extern const SplitConstants SPLIT_CONSTANTS;

/// A job's share of a whole derivative call, from its share of the states.
double job_cost(double states, double total, const SplitConstants& c = SPLIT_CONSTANTS);

/// Jobs into `workers` bins, largest first into the least loaded: the longest-processing-time
/// rule (`packJobs`). Each bin lists its jobs, in order.
std::vector<std::vector<int>> pack_jobs(const std::vector<double>& costs, long long workers);

/// Whether to split a run, and how (`planSplit`); and, once one has run, what it did. `use`
/// says whether to; `why` says why, in the application's words.
struct SplitPlan {
    bool use = false;
    std::string mode;
    std::string why;
    std::optional<double> predicted;
    std::vector<SplitJob> jobs;
    std::vector<int> owner;                 // per state: its job
    std::vector<std::string> keys;
    std::vector<std::vector<int>> bins;     // per bin: its jobs
    int parts = 0;
    std::vector<SplitRecorder> recorders;
    // What a run of it did: a line per bin, its wall time and its gain.
    Json ran = Json::array();
    double wall_ms = 0.0;
    std::optional<double> gain;
};

/// What `plan_split` is asked under: the mode as the model gives it ("on", "off"; anything
/// else is auto), how many threads (`workers`), whether the run is one of several side by
/// side (`nest` false), the whole model's build, what earlier runs of this layout measured
/// here (`known`: "solve_ms", "gain", "build_fixed", "bins"; null for nothing), whether the
/// run is held to the output grid whatever the model says, and the constants.
struct PlanOptions {
    Json mode = Json("auto");
    double workers = 1;
    bool nest = true;
    double build_ms = 0.0;
    Json known;
    bool on_grid = false;
    SplitConstants constants = SPLIT_CONSTANTS;
};

/// Whether to split this run, and how (`planSplit`). The jobs are packed by their states into
/// bins, as the application packs them, and a bin is built once: one bin per thread when the
/// split is asked for, and as many as auto expects to be quickest otherwise (see
/// `SplitConstants`). The prediction is the application's cost model: each bin costs its
/// share of the whole model's build and of its solve, the bins run side by side, and a split
/// costs `start_ms` once. Without `known` the ratio is judged on the model's shape alone,
/// with a larger margin and only for a large model.
SplitPlan plan_split(const System& sys, const Project& project, const PlanOptions& options = {});

/// The plan's bins as the jobs the threads are given (`binJobs`): one per bin, its jobs'
/// materials together, built once however many of the model's parts it holds -- with which
/// of the whole model's states each files (`owner`, by bin) and which recorders' histories
/// each gives back (`recorders`, by bin).
struct BinnedJobs {
    std::vector<SplitJob> jobs;
    std::vector<int> owner;
    std::vector<SplitRecorder> recorders;
};
BinnedJobs bin_jobs(const SplitPlan& plan);

/// `n` with a comma between thousands, as Python's `f'{n:,}'` writes it.
std::string with_commas(long long n);

/// A plan that is not a split: its mode, why, and what was predicted (`_no_split`).
SplitPlan no_split(const std::string& mode, const std::string& why, std::optional<double> predicted = std::nullopt);

// --- one bin's model ---------------------------------------------------------------------------------

/// The model as one job builds it: every material switched off but its own (`partModel`).
Json part_model(const Json& model, const std::vector<std::string>& keep, bool copy_it = true);

/// A job's model, built, switching back on any material its equations name outright --
/// `k[C-14]` -- and trying again (`buildPart`).
struct BuiltPart {
    std::shared_ptr<const Project> project;
    std::shared_ptr<System> system;
    std::vector<std::string> pinned;
};
BuiltPart build_part(const Json& model);

/// Where a job's states go in the whole model's vector (`placeStates`): `(from, to)`, for the
/// states the job owns -- by their place in `keys` and in the whole model.
std::pair<std::vector<int>, std::vector<int>> place_states(const std::unordered_map<std::string, int>& whole, const std::vector<std::string>& keys,
                                                           const std::vector<int>& owner, int job);

// --- the parts, back into one run --------------------------------------------------------------------

/// What one bin's run sends back: its states by name, its counts, and its recorders' histories.
struct PartRun {
    std::vector<double> t;
    std::vector<Vec> y;
    std::vector<std::string> keys;
    Json stats = Json::object();
    Json held;                                   // the zero floor's tally per state, or null
    std::map<std::string, Recorder> mem;
    std::vector<double> dis;
    std::vector<std::vector<double>> sampled;
    std::pair<double, double> clock{0.0, 0.0};   // the clock's interpolation: interval, origin
    double build_ms = 0.0;
    double solve_ms = 0.0;
    std::vector<std::string> pinned;
};

/// The parts, back into one run of the whole model (`assembleParts`). Every state is filed
/// from the job that owns it, by name; every part must have come back on the same times, and
/// every state must have come from one -- else this throws and the caller solves the whole
/// model. The counts are summed; a held-at-zero tally is kept as a share of its own part's
/// steps.
struct Assembled {
    std::vector<double> t;
    std::vector<Vec> y;
    Json stats;
};
Assembled assemble_parts(const std::vector<std::string>& keys, const std::vector<int>& owner, const std::vector<PartRun>& outcomes);

/// What a split run gives back (`run_split`): the whole model's times and states, the summed
/// counts, the wall time, a line per bin (`jobs`: materials, states, nsteps, buildMs,
/// solveMs), and what one thread would have taken whole and what the split is expected to
/// take, for deciding the next run.
struct SplitRun {
    std::vector<double> t;
    std::vector<Vec> y;
    Json stats;
    double wall_ms = 0.0;
    Json jobs = Json::array();
    double whole_ms = 0.0;
    double expected_ms = 0.0;
};

struct SplitRunOptions {
    /// How many bins run side by side; none: every bin at once.
    std::optional<int> threads;
    /// The parts' mean fraction and the slowest one's clock, about ten times a second, from
    /// the calling thread; false stops every part, and the run throws `SolverError`
    /// `aborted`. What it throws stops the parts, and comes out once they have stopped.
    ProgressFunction on_progress;
    SplitConstants constants = SPLIT_CONSTANTS;
};

/// The whole model, solved in its parts at once, as one run (`runSplit`). Each bin of the
/// plan is one job (`bin_jobs`): the model with the bin's materials switched on, built once
/// and run on a thread of its own -- as many side by side as `threads` says, the largest bin
/// first to whichever is free. What each sends back is filed into the whole model's vector by
/// name, and its recorders' histories onto the whole system. Throws if anything does not add
/// up, and the caller solves the whole model instead.
SplitRun run_split(const std::shared_ptr<const Project>& project, System& sys, const SplitPlan& plan, const SplitRunOptions& options = {});

/// What one thread would have taken to solve the whole model, from a split's bins: each
/// one's "states" and "nsteps", and its solve (`solving`, in the same order). Two estimates,
/// each of which errs high in a way of its own; the smaller is taken: the slowest bin
/// stretched to the whole by its share of a derivative call (`job_cost`), as the application
/// estimates it; and every bin's cost per step summed, the work each repeats every step
/// counted once, over as many steps as the most any bin took.
double whole_solve_ms(const Json& jobs, const std::vector<double>& solving, long long states, const SplitConstants& c = SPLIT_CONSTANTS);

/// The share of a whole build each part pays whatever it holds, from the parts' builds (`f`
/// in `B * (f + (1 - f) * share)`): their mean, held to [0, 2] -- each bin's build first
/// taken back from what the others built beside it cost it (`contention`). None where
/// nothing says.
std::optional<double> build_fixed(const Json& jobs, long long states, double build_ms, double contention = 0.0);

// --- what auto learns -----------------------------------------------------------------------------------

/// The most entries the file keeps.
inline constexpr std::size_t SPLIT_MEMORY_KEEP = 1000;

/// A stamp of this engine's build: what was measured with another build is not taken to hold
/// for this one.
const std::string& split_engine_stamp();

/// Where what auto learns is kept: `split-memory-cpp.json` in `KOMPARTMENT_CACHE` when that
/// is set, else in `~/.kompartment/cpp/`; none when `KOMPARTMENT_SPLIT_MEMORY` is `0`.
std::optional<std::string> split_memory_path();

/// What a measurement is kept by: the model's layout and the engine's build.
std::string split_memory_key(const std::string& signature);

/// What auto has learned of a model (see `split_memory_key`): "solve_ms", "gain",
/// "build_fixed", "bins", "when"; null when nothing.
Json split_recall(const std::string& key);

/// Keeps what a run measured, here and in the file -- written whole under a name of this
/// process's own and moved into place, the oldest entries dropped past `SPLIT_MEMORY_KEEP`. A
/// measurement within a quarter of the one kept is not written again: a script that runs a
/// model a thousand times does not write the file a thousand times.
void split_remember(const std::string& key, const Json& entry);

/// Forgets what this process has learned and read, so that the next recall reads the file
/// again (the tests' `empty!(_SPLIT_MEMORY); _SPLIT_MEMORY_READ[] = false`).
void split_memory_forget();

/// Whether two measurements are within a quarter of each other (`_split_close`). One that is not
/// a number -- null, or written into the file by hand as anything else -- is unknown: two
/// unknowns are close, an unknown and a number are not.
bool split_close(const Json& a, const Json& b);

// --- the run ---------------------------------------------------------------------------------------------

/// A run of the whole model -- solved in its parts at once when `simulation.split` says so
/// and the plan agrees, whole otherwise -- with the plan's account in `stats["split"]`, as
/// the application gives it. What `run_project` does with a project it builds itself.
/// `options.threads` is how many bins the parts are packed into, one per thread (the
/// machine's cores by default); `options.nest` false is a run that is itself one of several
/// side by side. `on_progress` and `on_grid` are the run's.
Results run_whole_or_split(const std::shared_ptr<const Project>& project, const RunOptions& options = {});

}  // namespace kompartment
