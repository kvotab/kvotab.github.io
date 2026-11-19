// Running a model many times over its distributions: the Julia package's
// engine/probabilistic.jl (the Python package's `kompartment/engine/probabilistic.py`,
// the application's `src/sim/probabilistic.js`), with the realisations shared out
// between threads.
//
// A probabilistic run draws a value for every distributed parameter (and every
// lookup point that carries a spread) per realisation, integrates the model again,
// and keeps the series asked for -- every realisation of them, because a band is
// read off all of them.
//
// **Built once, integrated many times.** The model is built and compiled once;
// each thread runs its share of the realisations on a copy of the built system of
// its own (`System::clone`, which shares the compiled passes), setting the
// parameters and working the invariant algebra out again for each. **The design is
// drawn whole** before any realisation runs: Latin hypercube is a statement about a
// whole column, and each input draws from a stream named after it, so any number of
// threads gives the same answer, to the last bit, as one; each realisation's
// numbers are those it has in a serial run, and in the other engines.
//
// Besides a sample, a *tornado* (every input swung alone to a low and a high
// probability) and a global sensitivity design (`gsa`, the points of one of the
// methods in stats/gsa_design.hpp) run the same way.
//
//     ProbabilisticOptions options;                  // seed, iterations, keep, threads...
//     options.iterations = 1000;
//     ProbabilisticResults prob = run_probabilistic(project, options);
//     Replay one = run_realisation(project, 17, options);   // realisation 17 as a run
//
// The parts, as a run uses them:
//
//     auto sys = std::make_shared<System>(project);
//     SampleDesign design = design_for(*project, *sys, options);   // seed, iterations, tornado, gsa...
//     ValueTable eff = effective_values(design, frm, to);          // realisations frm..to-1, from 0
//     for each realisation i in [frm, to), on a system of its own (System::clone):
//         apply_realisation(s, design, eff, i - frm, i);           // parameters, invariant slots, dice
//         run it (RunOptions::on_grid, a RowPool per thread)
//
// `design.stats` is what the run's statistics start from; a run adds "failed",
// "trouble", "ms" before it and "threads" after it (Julia's `merge!`).

#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "engine/runner.hpp"
#include "stats/gsa_design.hpp"
#include "stats/sample.hpp"
#include "util/json.hpp"

namespace kompartment {

class Project;
class System;

inline constexpr long long PROB_MOST_BYTES = 1073741824;
inline constexpr long long PROB_MOST_BYTES_ASKED = 4LL * 1073741824;

/// Anything but an input: not a parameter, not a lookup table.
bool can_be_endpoint(const Json& kind);

/// Whether a design's option asks for something (`_pb_truthy_opt`): as the application asks, by
/// any value JavaScript takes for true -- an empty dictionary too, and not 0, NaN or "" -- how
/// `design_for` tells a tornado or a sensitivity design asked for.
bool pb_truthy_opt(const Json& x);

/// Python's `str(v)`, for a name or a group a model file gives (`_pb_py_str`): text as it is,
/// `True`/`False`, `None`, a float as Python's `repr`; a list or a dictionary as Julia's
/// `string()` writes it.
std::string pb_py_str(const Json& v);

/// Julia's `show` (`repr`) of a value a model file holds, as it shows one inside a list:
/// `nothing`, `true`, `5`, `1.0` and `1.0e-5`, text in quotes and escaped, `Any[1, 2]`,
/// `OrderedCollections.OrderedDict{String, Any}("a" => 1)`.
std::string julia_show(const Json& v);
/// Julia's `string(v)`: text as it is, any other value as `julia_show` writes it.
std::string julia_string(const Json& v);
/// Julia's `show` of a Float64: Ryu's shortest digits laid out as Julia lays them out.
std::string julia_float(double x);
/// Julia's `show` of a String: in quotes, escaped as Julia escapes it.
std::string julia_quote(const std::string& s);

/// The correlation group a plan entry's distribution belongs to, or none.
std::optional<std::string> sample_group(const PlanEntry& entry);

/// A sampled input's name, as the application spells it: `Kd[I-129]`, `Q@500`, `k`.
std::string sample_slot_name(const PlanEntry& entry);

/// The bytes a run of this shape holds (`double` while running, `float32` in a file), and in words.
struct ShapeEstimate {
    long long bytes = 0;
    std::string text;
};
ShapeEstimate estimate(long long series, long long times, long long iterations, std::string_view precision = "double");

/// `"float32"` when a run of this shape would hold more than `most` bytes as doubles (a
/// gigabyte, what a tab may hold), else `"double"`.
std::string hold_precision(long long series, long long times, long long iterations, long long most = PROB_MOST_BYTES);

/// A Poisson process's occurrence times between two times, drawn from `stream`.
std::vector<double> sample_occurrences(double rate, double frm, double until, Mulberry32& stream, long long most = 10000);

/// The distributions a model would sample (`distributed_slots`), narrowed to the inputs
/// `simulation.varied` names when it names any that are there.
std::vector<PlanEntry> sampling_plan(const Project& project, const System& sys);
/// The same, the system built for it (without its Jacobian), as Julia's default argument does.
std::vector<PlanEntry> sampling_plan(const std::shared_ptr<const Project>& project);

/// Inputs x realisations, a realisation after another as Julia lays a matrix out: input k's
/// value in realisation i (both from 0) is `(k, i)`.
struct ValueTable {
    std::size_t inputs = 0;
    long long realisations = 0;
    std::vector<double> data;

    ValueTable() = default;
    /// Refused as Julia refuses `Matrix{Float64}(undef, inputs, realisations)`.
    ValueTable(std::size_t inputs, long long realisations);
    double& operator()(std::size_t k, long long i) { return data[static_cast<std::size_t>(i) * inputs + k]; }
    double operator()(std::size_t k, long long i) const { return data[static_cast<std::size_t>(i) * inputs + k]; }
    /// Realisation i's values, one per input.
    const double* realisation(long long i) const { return data.data() + static_cast<std::size_t>(i) * inputs; }
};

/// What every realisation of a run sets (`designFor`), the values of every one drawn at the start.
struct SampleDesign {
    std::vector<PlanEntry> plan;
    std::vector<std::string> names;
    std::vector<double> best;            // the model's own value of each input
    std::vector<bool> varies;
    long long iterations = 0;
    ValueTable values;                   // inputs x iterations: what realisation i draws for input k
    Json seed;
    /// `"seed"`, `"latin"`, `"sampled"`; a sample's `"correlated"`, `"correlationAdjusted"`,
    /// `"correlationProblems"`, `"groups"`; a tornado's `"tornado"` (`"low"`, `"high"`, `"swung"`
    /// from 1); a sensitivity design's `"gsa"` (`"method"`, `"options"`, `"factors"` -- each
    /// factor's `"members"` from 1 -- `"correlated"`, `"correlationsUsed"`,
    /// `"correlationShrunk"`, `"correlationProblems"`). Inputs are counted from 1 there, as the
    /// Julia package counts them (a sample archive writes them from 0).
    Json stats;
    /// A sensitivity design's own (`build_design`), or none.
    std::shared_ptr<const GsaDesign> gsa_design;

    bool is_tornado() const { return stats.has("tornado"); }
    bool is_gsa() const { return stats.has("gsa"); }
    /// Whether the points are designed -- a tornado's or a sensitivity design's -- rather than a sample.
    bool is_designed() const { return is_tornado() || is_gsa(); }
    /// The plan as the Julia package writes it: `[{"slot", "name", "index", "spec"}]`.
    Json plan_json() const;
};

/// What a design is asked for, as a probabilistic job's options give it.
struct DesignOptions {
    /// The run's seed: any value, read as JavaScript's `Number()` reads it, and recorded as given.
    Json seed = Json(1);
    /// How many realisations a sample has (rounded, at least one); 100 when none.
    std::optional<double> iterations;
    /// Latin hypercube, or independent draws.
    bool latin = true;
    /// The inputs a sample varies, by name (`Kd[I-129]`); every other is held at its own value.
    /// (A service reading them from a job's JSON makes each a string as Julia's `string()` does.)
    std::optional<std::vector<std::string>> varied;
    /// A tornado: `true`, or `{"low": 0.05, "high": 0.95}`; null, `false` or `{}` for none.
    Json tornado;
    /// A sensitivity design: `{"method": "sobol", "options": {"samples": 500}}`; null, `false` or
    /// `{}` for none.
    Json gsa;
};

/// Every realisation's values, drawn whole: one column of uniforms per sampled input on a
/// stream named after it (or after its correlation group), Latin hypercube or random, the
/// correlations the model asks for put in by Iman-Conover, each uniform read through its
/// input's distribution. `sys` is the project's system as built (its `P` gives each input's
/// own value). Refusals are the Julia package's `ArgumentError`s, word for word.
SampleDesign design_for(const Project& project, const System& sys, const DesignOptions& options = {});

/// The value each input takes in realisations `frm` to `to - 1` (from 0), which is what is set
/// into the run and what it records (`_pb_effective`): the value drawn where it is a number; the
/// model's own for an input that is held; and, for a varied input whose draw is not a number,
/// the last value drawn before it that was -- the model's own where none was. Read off the
/// design alone, so that a realisation is the same run on whichever thread and in whichever
/// range it runs, and replayed on its own.
ValueTable effective_values(const SampleDesign& design, long long frm, long long to);

/// Sets realisation `i` (from 0, column `column` of `eff`) into `sys`, ready to run: the
/// parameters, the invariant algebra, the events' dice (`_pb_apply!`). Once the design is
/// drawn, several threads may each set realisations into a system of their own
/// (`System::clone`): nothing shared is written. (`design_for` has looked every event block's
/// settings up once, which builds the key index a large JSON dictionary makes on its first
/// lookup; a lookup that builds one is no read two threads may share.)
void apply_realisation(System& sys, const SampleDesign& design, const ValueTable& eff, long long column, long long i);

/// This realisation's occurrences (`i` from 0) of every random event that draws them; with
/// `sample` false (a designed run) every event keeps its deterministic form.
void draw_disruptions(System& sys, const Json& seed, long long i, bool sample = true);

// --- what a run keeps ------------------------------------------------------------------------

/// What a probabilistic run kept (`ProbabilisticResults`): every realisation of each kept
/// series, the value each input took in each, and the statistics read off them. The
/// realisations held are those numbered `first` to `last` (from 1): all of them unless a
/// range was asked for. Realisation `i` here (from 0) is realisation `first + i` of the
/// design.
struct ProbabilisticResults {
    /// The output times every realisation was reported on.
    std::vector<double> t;
    /// The kept series' descriptors (`"label"`, `"block"`, `"kind"`, ...).
    std::vector<Json> outputs;
    /// `"double"`, or `"float32"` when a run of this shape would hold more than `most_bytes`
    /// as doubles (`hold_precision`): which of `values` and `values32` holds the series.
    std::string precision = "double";
    /// One per kept series: realisation i's value at time j (both from 0) at `i * t.size() + j`
    /// -- a realisation's times together, as the sample archive lays them out. A failed
    /// realisation's row is NaN.
    std::vector<std::vector<double>> values;
    std::vector<std::vector<float>> values32;
    /// Inputs x realisations held: the value each sampled input took -- the value drawn, or
    /// where that was no number, the one held over from a realisation before (`effective_values`).
    ValueTable samples;
    /// The sampled inputs and their names as the application spells them (`Kd[I-129]`).
    std::vector<PlanEntry> plan;
    std::vector<std::string> names;
    /// The varied parameters as series: `{"output": descriptor, "k": its row of `samples`, from 1}`.
    std::vector<Json> inputs;
    /// 1 per realisation held that ran, 0 where it failed.
    std::vector<std::uint8_t> ran;
    long long iterations = 0;
    long long first = 1, last = 0;
    /// `"failed"`, `"trouble"`, `"ms"`, the design's (`"seed"`, `"latin"`, `"sampled"`, ...: see
    /// `SampleDesign::stats`), `"threads"`; inputs counted from 1, as the Julia package counts them.
    Json stats;
    /// The project the run was made from.
    std::shared_ptr<const Project> project;
    /// A sensitivity design's own (`build_design`), or none.
    std::shared_ptr<const GsaDesign> gsa_design;

    bool single() const { return precision == "float32"; }
    /// How many realisations are held.
    long long held() const { return last - first + 1; }
    std::size_t times() const { return t.size(); }
    /// Series `w`'s value (from 0) in realisation `i` at time `j`.
    double value(std::size_t w, long long i, std::size_t j) const {
        std::size_t at = static_cast<std::size_t>(i) * t.size() + j;
        return single() ? static_cast<double>(values32[w][at]) : values[w][at];
    }
    /// Every realisation of series `w` (from 0), or of the series a label names, as doubles, a
    /// realisation's times together.
    std::vector<double> realisations(std::size_t w) const;
    std::vector<double> realisations(const std::string& label) const { return realisations(index_of(label)); }
    /// The kept series' labels.
    std::vector<std::string> labels() const;
    /// Which kept series a label names (from 0); Julia's `KeyError` where none does.
    std::size_t index_of(const std::string& label) const;
    /// The values one sampled input took, by its name (`Kd[Cs-137]`); a `KeyError` for a name
    /// that is not sampled.
    std::vector<double> sample(const std::string& name) const;
};

/// `(name, descriptor) -> keep it?`: which series a run keeps, by a test of its own.
using KeepFunction = std::function<bool(const std::string& name, const Json& descriptor)>;
/// `on_progress(done, total)`: called after every realisation, one call at a time, `done`
/// rising. What it throws stops the run (every thread finishes the realisation it is on) and
/// comes out of `run_probabilistic` once every thread has stopped.
using RealisationProgress = std::function<void(long long done, long long total)>;

/// What a probabilistic run is asked for: the design's settings (seed, iterations, Latin
/// hypercube or not, the inputs varied, a tornado or a sensitivity design), and these.
struct ProbabilisticOptions : DesignOptions {
    /// The series kept, by block name or label: none for every endpoint (anything but an
    /// input). `keep_by`, where given, decides instead.
    std::optional<std::vector<std::string>> keep;
    KeepFunction keep_by;
    /// How many threads share the realisations (at most the machine's cores, at least one);
    /// 0 for every core.
    int threads = 0;
    RealisationProgress on_progress;
    /// A run that would hold more than `most_bytes` even as float32 is refused, unless `large`
    /// asks for up to `asked_bytes` -- a tab's limits by default (a gigabyte, four), the
    /// application's own, drawn from this machine's memory, for a sample the engine holds.
    bool large = false;
    long long most_bytes = PROB_MOST_BYTES;
    long long asked_bytes = PROB_MOST_BYTES_ASKED;
    /// Only these realisations of the whole design, by their numbers from 1 (first, last).
    std::optional<std::pair<double, double>> range;
};

/// Runs `options.iterations` realisations of a model over its distributions (100 when none
/// is given; a tornado's or a sensitivity design's own count) and keeps the series asked
/// for (`run_probabilistic`).
///
/// The model is built once. `threads` threads share the realisations, each on a copy of
/// the built system of its own; the design is drawn whole first, so the answer does not
/// depend on how many. A failure in the first realisation fails the run (the others stop);
/// any other that fails is recorded -- its row NaN, `ran` 0, `stats["failed"]` counted and
/// the first five in `stats["trouble"]`, in the Julia package's words -- and the run goes
/// on. A run that would hold more than `most_bytes` of doubles keeps float32; past that even
/// so it is refused (a Julia `ErrorException`), unless `large` lets it come to `asked_bytes`.
ProbabilisticResults run_probabilistic(std::shared_ptr<const Project> project, const ProbabilisticOptions& options = {});

/// The realisations a run holds, `frm` to `to - 1` counted from 0: all of them, or those
/// `range` numbers (from 1, rounded as Julia rounds, a tie to the even one) (`_pb_slice`).
std::pair<long long, long long> realisation_slice(const std::optional<std::pair<double, double>>& range, long long iterations);

/// One realisation's kept series, as a probabilistic run takes them out of its run
/// (`_pb_take!`): the states read once per time for every series that reads them, the
/// algebraic slots worked out once per time with the run's histories, a parameter's value,
/// a derived series from its curve; for a run reported at times besides the grid's, every
/// series over every row, read at the first row at or after each grid time
/// (`_pb_take_rows!`). Each as doubles, over `grid`. (A run takes them into the matrices it
/// holds; this is for looking at one.)
std::vector<std::vector<double>> take_realisation(Results& res, const std::vector<Json>& kept, const std::vector<double>& grid);

/// One realisation of a probabilistic run as an ordinary run (`run_realisation`).
struct Replay {
    Results results;
    /// Which realisation, from 1, and of how many.
    long long number = 0;
    long long iterations = 0;
    /// Each input's name, the value it was run with, and whether it was held: not varied, at
    /// the model's value in a tornado's point, or held over from a realisation before, the
    /// draw being no number.
    struct Value {
        std::string name;
        double value = 0;
        bool held = false;
    };
    std::vector<Value> values;
};

/// Realisation `number` (from 1, brought into the design's range) of a probabilistic run,
/// as an ordinary run on a system built for it, set as the whole run sets it (an input whose
/// draw is not a number holding the value drawn before it, `effective_values`).
Replay run_realisation(std::shared_ptr<const Project> project, long long number, const DesignOptions& options = {});

}  // namespace kompartment
