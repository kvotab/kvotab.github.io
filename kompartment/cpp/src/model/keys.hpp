// Renaming the keys an older project file uses (src/domain/keys.js).
//
// Keys are snake_case now; files written when they were camelCase, or before
// some collections were renamed, still open. The rename matters: an unknown
// key is ignored rather than reported, so a stale `multiplyByDonor: false`
// would quietly turn back into the default `true`.

#pragma once

#include <string>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

/// Every collection of blocks in a project file.
const std::vector<std::string>& collections();

/// A copy of `raw` with every older key renamed to the current one; also moves a
/// far-field path's old `to` into a release transfer, renames the built-in index lists
/// written under their old names, and splits a single material list into the catalogue
/// and the radionuclides it carries.
Json migrate_keys(const Json& raw);

}  // namespace kompartment
