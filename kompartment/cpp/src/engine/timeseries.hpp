// When results are saved: the output time grid (src/domain/timeseries.js).
//
// A list of series -- geometric, linear, or times written out -- combines into
// one sorted set of times, the run's own start and end always in it and
// duplicates removed with a relative tolerance.

#pragma once

#include <string>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

/// Two times are the same time when they are this close, relatively.
inline constexpr double SAME_TIME = 1e-9;

std::string series_kind(const Json& spec);
/// One series' own time points inside the run, in increasing order.
std::vector<double> series_times(const Json& spec, double t0, double t1);
/// Every series, sorted, without duplicates; the run's start and end always in.
std::vector<double> combine_series(const Json& series, double t0, double t1);

}  // namespace kompartment
