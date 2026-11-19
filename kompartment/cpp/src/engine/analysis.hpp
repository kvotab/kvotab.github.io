// What a probabilistic run says, the part the engine's service answers the page
// with: the bands of every series -- quantiles, mean, standard deviation, the
// median's two intervals -- over the realisations a screen keeps. The Julia
// package's engine/analysis.jl (the Python package's `kompartment/engine/analysis.py`,
// the application's `bandsOf`), in the same order of operations, so the numbers
// are the page's to the last bit. (Not here: summaries, a tornado's table, what
// drove the spread -- the page works those out.)
//
// A varied parameter is a series here too, one value per realisation, after the
// kept ones (the application's `withInputs`). As in the Julia package, a series
// is numbered from 1 (the kept ones, then the varied parameters), and so is a
// realisation. A `mask` (one entry per realisation, true or non-zero to use it;
// null for every one) screens realisations out, exactly as if they had failed.

#pragma once

#include <string>
#include <utility>
#include <vector>

#include "engine/probabilistic.hpp"
#include "util/json.hpp"

namespace kompartment {

/// The percentiles a band shows unless others are asked for.
inline constexpr double PROB_QUANTILES[] = {0.05, 0.25, 0.5, 0.75, 0.95};
/// What a regression is read on: the values, their ranks, their logarithms (the page's).
inline constexpr const char* PROB_TRANSLATIONS[] = {"none", "rank", "log"};
/// The percentiles a summary of one output at one time lists (the page's).
inline constexpr double SUMMARY_PERCENTILES[] = {0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99};

/// A series as the analysis reads it: realisations x times as doubles (x 1 for a varied
/// parameter, NaN where it did not run), a time's realisations together as Julia lays a
/// matrix out: realisation i at time j (from 0) is `data[j * rows + i]`.
struct SeriesMatrix {
    long long rows = 0;
    std::size_t cols = 0;
    std::vector<double> data;

    double operator()(long long i, std::size_t j) const { return data[j * static_cast<std::size_t>(rows) + static_cast<std::size_t>(i)]; }
};

/// How many series a result reads: the kept ones, then each varied parameter as its draws (`_an_count`).
std::size_t an_count(const ProbabilisticResults& r);
/// Series `k`'s descriptor (from 1).
const Json& an_output(const ProbabilisticResults& r, std::size_t k);
/// Whether series `k` is one value per realisation (a varied parameter), and which input it is
/// (its row of `samples`, from 1; 0 for a kept series).
bool an_flat(const ProbabilisticResults& r, std::size_t k);
long long an_drawn_from(const ProbabilisticResults& r, std::size_t k);
/// Series `k` as a matrix of doubles (`_an_matrix`).
SeriesMatrix an_matrix(const ProbabilisticResults& r, std::size_t k);
/// Which series a label names (from 1), among the kept series and the varied parameters;
/// Julia's `KeyError` where none does.
std::size_t an_index(const ProbabilisticResults& r, const std::string& label);

/// How many entries a mask has, as Julia's `length` counts them: a list's, a dictionary's, a
/// text's characters; one for a number or a Boolean.
long long mask_length(const Json& mask);
/// Whether realisation `i` (from 1) is used: always without a mask; `mask[i]` true or non-zero
/// (and not NaN) with one -- anything but a number, a Boolean or null counting as true.
bool an_keep(const Json* mask, long long i);

/// The finite values of time `j` (from 0) of `M` over the realisations kept, ascending (-0 before 0).
std::vector<double> an_finite_sorted(const SeriesMatrix& M, std::size_t j, const Json* mask);
/// The band at each time: order statistics across the realisations that ran, `x[round(q (n - 1))]`.
std::vector<std::vector<double>> an_quantiles(const SeriesMatrix& M, const std::vector<double>& qs, const Json* mask);
/// The mean at each time of the finite values of the realisations kept, summed in order.
std::vector<double> an_mean(const SeriesMatrix& M, const Json* mask);

/// The median's 95% interval (`errLo`, `errHi`) and the body's 68% (`bodyLo`, `bodyHi`) at each time.
struct MedianSpread {
    std::vector<double> err_lo, err_hi, body_lo, body_hi;
};
MedianSpread an_median_spread(const SeriesMatrix& M, double z, const Json* mask);

/// The standard deviation at each time over the finite values kept (n - 1), NaN below two;
/// and how many there were.
struct SpreadOf {
    std::vector<double> sd;
    std::vector<long long> n;
};
SpreadOf an_sd(const SeriesMatrix& M, const std::vector<double>& mean, const Json* mask);

/// The percentiles asked for (probabilities strictly between 0 and 1), with the median,
/// ascending; `PROB_QUANTILES` where `list` is not a list.
std::vector<double> percentiles_for(const Json& list);

/// The band of one series (by label) at each time: each `qs` quantile in turn, a quantile
/// given twice once.
std::vector<std::pair<double, std::vector<double>>> quantiles(const ProbabilisticResults& r, const std::string& label,
                                                              const std::vector<double>& qs = {0.05, 0.5, 0.95}, const Json* mask = nullptr);
/// The mean of one series at each time over the realisations that ran.
std::vector<double> realisations_mean(const ProbabilisticResults& r, const std::string& label, const Json* mask = nullptr);
/// The median's 95% interval and the body's 68% at each time.
MedianSpread median_spread(const ProbabilisticResults& r, const std::string& label, double z = 1.959964, const Json* mask = nullptr);

/// One series' band (`bands`): the quantiles at `quantiles` (the median always among them),
/// the mean, the standard deviation with its counts and the median's intervals; `flat` for a
/// varied parameter, whose numbers are single values.
struct Band {
    std::vector<std::vector<double>> q;
    std::vector<double> quantiles;
    std::vector<double> mean;
    SpreadOf sd;
    MedianSpread med;
    bool flat = false;
};
/// Per series -- every kept one, then every varied parameter as its draws -- its band.
std::vector<Band> bands(const ProbabilisticResults& r, const Json& percentiles = Json(), const Json* mask = nullptr);

}  // namespace kompartment
