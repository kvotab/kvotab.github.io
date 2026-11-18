// Numbers read off finished curves: the peak, when it peaked, the total
// (src/domain/derived.js). A derived value is an output like any other, worked
// out from (t, y) when asked for; the kinds that are curves (the running
// integral, per-period means and sums) give one value per output time, the
// rest one number.

#pragma once

#include <string>
#include <vector>

#include "engine/project.hpp"
#include "util/json.hpp"

namespace kompartment {

bool is_derived_kind(const std::string& kind);
/// Whether a kind is a curve (the running integral, per-period values) and not one number.
bool is_series_kind(const std::string& kind);
std::string derived_unit(const std::string& kind, const Json& source_unit, const Json& time_unit);

/// A derived value of the series `values` at times `t`: a curve (one value per time) for
/// the kinds that are curves, one number repeated otherwise.
std::vector<double> derived_reduce(const std::string& kind, const std::vector<double>& t, const std::vector<double>& values, double at, double period);

double derived_value_at(const std::vector<double>& t, const std::vector<double>& values, std::size_t n, double at);
std::vector<double> derived_integral(const std::vector<double>& t, const std::vector<double>& values, std::size_t n);

/// The derived values a run can report, admitted in passes so one may be of another.
std::vector<Json> derived_outputs(const Project& project, const std::vector<Json>& known_outputs);

}  // namespace kompartment
