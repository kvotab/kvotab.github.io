// The run log: what a run was, in words that survive it -- program, date, the
// settings, how the solve went, what was held at zero, whether the mass balance
// closed (the Julia package's engine/runlog.jl, a port of the application's
// src/domain/runlog.js). The page shows it under *Run log*, and a results
// archive keeps it; numbers are written as the page writes them.

#pragma once

#include <chrono>
#include <optional>
#include <string>
#include <vector>

#include "engine/runner.hpp"

namespace kompartment {

/// `date.toISOString()`: UTC, to the millisecond.
std::string iso_utc(std::chrono::system_clock::time_point at);

/// The mass-balance audit in words (`describeAudit`): whether it closes, then a line per
/// family. `time_unit` follows every time it writes, when there is one.
std::vector<std::string> describe_audit(const Json& audit, const std::string& time_unit = "");

/// A switching solver's account in words, `Tsit5 12 steps, Rosenbrock23 300; 3 switches`,
/// or none for any other solver (`describeMethodSteps`).
std::optional<std::string> describe_method_steps(const Json& stats);

struct RunLogOptions {
    /// The model as its file holds it; the run's own when null.
    const Json* project = nullptr;
    /// The program's build stamp, written after the title; none when empty.
    std::string build;
    /// When; the date line writes it.
    std::chrono::system_clock::time_point at = std::chrono::system_clock::now();
};

/// The log of a deterministic run, as lines (the application's `runLogLines`): the model,
/// its settings, how the run went -- steps, how df/dy was obtained, a split asked for,
/// output points, timings -- what was held at zero, the far-field paths' warnings and the
/// mass-balance audit.
std::vector<std::string> run_log_lines(Results& res, const RunLogOptions& options = {});

/// The log of a run as one text, its lines joined by newlines (`run_log`); a results
/// archive keeps it split at them again.
std::string run_log(Results& res, const RunLogOptions& options = {});

struct ProbabilisticResults;

/// The log of a probabilistic run or a tornado, as lines (`probabilisticLogLines`): how many
/// realisations (or design points), the seed and the sampling (or where a tornado swung its
/// inputs to), the inputs sampled and correlated, the correlations ignored, the threads, the
/// wall clock, the realisations that failed.
std::vector<std::string> probabilistic_log_lines(const ProbabilisticResults& prob);

/// That log as one text (`run_log(prob)`).
std::string run_log(const ProbabilisticResults& prob);

}  // namespace kompartment
