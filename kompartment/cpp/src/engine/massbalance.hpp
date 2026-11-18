// The mass-balance audit (src/domain/massbalance.js). With `mass_balance` on,
// the run carries one budget state per family (each radionuclide, and one for
// what is not indexed by any) per kind of movement; the audit checks that
// what each family holds equals what it started with plus what came in, less
// what went out and decayed, plus what grew in.

#pragma once

#include <vector>

#include "engine/builder.hpp"
#include "util/json.hpp"

namespace kompartment {

/// The closure, family by family and in total, with the names the page reads it by.
/// `abstol`: per state, or one number (`abstol_all`) when empty.
Json audit(const Budget& budget, const std::vector<double>& t, const std::vector<std::vector<double>>& y, const Json& rtol,
           const std::vector<double>& abstol, double abstol_all);

}  // namespace kompartment
