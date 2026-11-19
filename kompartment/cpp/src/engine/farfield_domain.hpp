// The far-field pathway's settings: what a path block holds, its defaults, and
// the checks a project makes of it before anything is built
// (src/domain/farfield.js). The cells, the rates and the release are in
// engine/farfield.

#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

/// How the downstream end is closed (0..4); 4 is the rock going on past the release point.
inline constexpr int CONTINUES = 4;
const std::vector<std::string>& farf_methods();          // discretized, semi-analytical
const std::vector<std::string>& farf_surfaces();         // f, aw, aperture
const std::vector<std::string>& farf_grids();            // matched, reference
const std::vector<std::string>& farf_nuclide_keys();     // kd_f, eps_m, kd_m, de_m
const std::vector<std::string>& farf_single_keys();
const std::vector<std::string>& farf_equation_keys();
const std::vector<std::string>& farf_structure_keys();   // n_f, n_m, o_b, n_b

/// What a new path starts with (`FARF_DEFAULTS` in src/domain/farfield.js); a dictionary of its own.
Json farf_defaults();
/// What a saved path that does not mention these meant: the reference implementation's numerics.
const Json& farf_legacy();
/// A surface setting's equation when the path gives none.
std::string farf_surface_default(std::string_view key);

/// `Number(v)`, as the application reads a value it is given: null and blank text 0, text by
/// JavaScript's grammar (`0x10` is 16; `1_000` and `inf` NaN), a list what its text reads as.
double value_number(const Json& v);

/// Whether a path is worked out on cells, which is what gives it states.
bool uses_cells(const Json& block);
/// Whether a path is worked out semi-analytically.
bool is_semi_analytic(const Json& block);
/// How a path gives its flow-wetted surface: F unless it says otherwise.
std::string surface_of(const Json& block);
/// Every equation but the two ways of giving the surface the path does not use.
std::vector<std::string> active_equation_keys(const Json& block);
/// How many cells of rock past the release point the semi-infinite outlet needs.
int auto_extra_cells(const Json& nf, const Json& pe);
/// The extra cells past the release point.
int extra_cells(const Json& block);

/// The structure the cells are built on: the semi-infinite outlet as extra cells closed by
/// linear extrapolation (`effectiveStructure`).
struct FarfStructure {
    int n_f, n_m, o_b, n_b;
    bool downstream;
};
FarfStructure effective_structure(const Json& block);

inline int cell_index(int k, int j, int nm) { return k * (nm + 1) + j; }
/// How many cells one nuclide's path has; one for a semi-analytical path.
int cell_count(const Json& g);
/// The cells whose inventory is the path's.
int held_cells(const Json& block);
/// What each cell is called: `F3` the third fracture cell, `M3_1` the first matrix layer behind it.
std::vector<std::string> cell_names(const Json& g);

/// What is wrong with a path's cell counts and outflow condition, with its depths, or with
/// its rock's settings; nothing when all is well.
std::optional<std::string> structure_problem(const Json& g);
std::optional<std::string> geometry_problem(const Json& block);
std::optional<std::string> rock_problem(const Json& block);

}  // namespace kompartment
