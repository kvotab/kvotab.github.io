// Making sampled inputs move together, as Kompartment does it: Iman and Conover
// (1982). The Julia package's stats/correlate.jl (the Python package's
// `kompartment/stats/correlate.py`, the application's `src/domain/correlate.js`).
//
// A probabilistic run draws every distributed input on a stream of its own, so two
// inputs are independent unless the model says otherwise, in its simulation
// settings:
//
//     "correlations": [
//       {"a": "Kd[Tc-99]", "b": "Kd[I-129]", "r": 0.8},
//       {"group": "Kd", "r": 0.9}
//     ]
//
// -- a *pair* names two sampled inputs as the sampling plan spells them, a *group*
// correlates every sampled index of one parameter with every other.
//
// Iman-Conover *permutes* each correlated column so that the columns' ranks
// correlate as the target matrix says; nothing about any one column changes, only
// which realisation gets which value. The arithmetic is the Julia package's, in the
// same order, so the same seed gives the same permutation.

#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

class Project;

/// Two sampled inputs to correlate: their places among the names, from 0, `a < b`.
struct CorrelationPair {
    int a = 0, b = 0;
    double r = 0.0;
};

struct CorrelationPairs {
    std::vector<CorrelationPair> pairs;
    /// What was ignored and why, in the Julia package's words.
    std::vector<std::string> problems;
};

/// The pairs a model asks for, read off `simulation.correlations`; `names` are every sampled
/// input, as the sampling plan spells them (`Kd[Tc-99]`). What is ignored, and why: a
/// coefficient outside [-1, 1], a name that is not sampled, an input paired with itself, a
/// group with fewer than two members, a pair given twice (the first coefficient is kept).
/// `simulation` is the settings (none: not there).
CorrelationPairs correlation_pairs(const Json* simulation, const std::vector<std::string>& names);
/// The same for a project: its settings.
CorrelationPairs correlation_pairs(const Project& project, const std::vector<std::string>& names);
/// The same for a model as its file holds it (the settings under `simulation`).
CorrelationPairs correlation_pairs_of_model(const Json& model, const std::vector<std::string>& names);

struct ImanConover {
    /// Which columns moved, from 0, ascending.
    std::vector<int> columns;
    /// The largest change the target matrix needed to become a correlation matrix (0 when it
    /// already was one).
    double adjusted = 0.0;
};

/// Reorders the correlated columns in place so their ranks correlate as asked. `columns` are
/// one per sampled input, `n` long each; `pairs` from `correlation_pairs`; `names` what each
/// column is called, which names its score stream; `seed_bits` the run's seed (`sm_to_uint32`).
/// Nothing moves with no pairs, or with fewer than three realisations.
ImanConover iman_conover(std::vector<std::vector<double>>& columns, const std::vector<CorrelationPair>& pairs,
                         const std::vector<std::string>& names, std::uint32_t seed_bits);

/// numpy's `argsort(v, kind='stable')`: NaN after everything, -0 equal to +0; from 0.
std::vector<std::size_t> np_argsort(const std::vector<double>& v);

}  // namespace kompartment
