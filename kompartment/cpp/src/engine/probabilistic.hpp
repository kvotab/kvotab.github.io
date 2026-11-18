// Running a model many times over its distributions: the Julia package's
// engine/probabilistic.jl (the Python package's `kompartment/engine/probabilistic.py`,
// the application's `src/sim/probabilistic.js`). Here, the part a run draws before
// any realisation runs: the sampling plan, the design and how a realisation is set
// into a system.
//
// **The design is drawn whole** before any realisation runs: Latin hypercube is a
// statement about a whole column, and each input draws from a stream named after
// it, so any number of threads gives the same answer, to the last bit, as one; each
// realisation's numbers are those it has in a serial run, and in the other engines.
//
// Besides a sample, a *tornado* (every input swung alone to a low and a high
// probability) and a global sensitivity design (`gsa`, the points of one of the
// methods in stats/gsa_design.hpp) run the same way.
//
// A run uses it so:
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
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

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

/// Python's `str(v)`, for a name or a group a model file gives (`_pb_py_str`): text as it is,
/// `True`/`False`, `None`, a float as Python's `repr`; a list or a dictionary as Julia's
/// `string()` writes it.
std::string pb_py_str(const Json& v);

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

}  // namespace kompartment
