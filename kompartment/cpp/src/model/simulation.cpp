#include "model/simulation.hpp"

#include <cmath>
#include <cstdlib>
#include <limits>

#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

const std::vector<std::string>& solver_ids() {
    static const std::vector<std::string> ids = {
        "ndf", "ros23", "dp45", "auto", "auto_julia", "rodas5p", "radau5", "fbdf", "fbdf_krylov", "qndf",
        "kencarp4", "trbdf2", "rosenbrock23", "tsit5", "vern7", "scipy_bdf", "scipy_radau", "scipy_lsoda"};
    return ids;
}
const std::vector<std::string>& spacings() {
    static const std::vector<std::string> v = {"log", "linear", "series", "solver", "both"};
    return v;
}
const std::vector<std::string>& series_kinds() {
    static const std::vector<std::string> v = {"log", "linear", "times"};
    return v;
}
const std::vector<std::string>& samplings() {
    static const std::vector<std::string> v = {"latin", "random"};
    return v;
}
const std::vector<std::string>& split_modes() {
    static const std::vector<std::string> v = {"auto", "on", "off"};
    return v;
}

double time_unit_years(std::string_view unit) {
    if (unit == "second") return 1.0 / 31557600;
    if (unit == "minute") return 60.0 / 31557600;
    if (unit == "hour") return 3600.0 / 31557600;
    if (unit == "day") return 1 / 365.25;
    if (unit == "year") return 1.0;
    return 0.0;
}

Json simulation_defaults() {
    return Json::object({
        {"start_time", Json(0)},
        {"end_time", Json(1e5)},
        {"output_points", Json(250)},
        {"spacing", Json("log")},
        {"solver", Json(DEFAULT_SOLVER)},
        {"rtol", Json(1e-3)},
        {"abstol", Json(1e-6)},
        {"time_unit", Json("year")},
        {"non_negative", Json(true)},
        {"iterations", Json(1000)},
        {"seed", Json(1)},
        {"sampling", Json("latin")},
    });
}

int shorthand_points(const Json& count) {
    // As the application's comparisons read the count: with `Number()` ("0x10" is 16).
    const double v = js_number_of(count);
    if (2 <= v && v <= MAX_OUTPUT_POINTS) return static_cast<int>(std::floor(v + 0.5));
    return 250;
}

std::string solver_label(std::string_view id) {
    static const std::pair<const char*, const char*> labels[] = {
        {"ndf", "stiff, NDF"}, {"ros23", "stiff, low order, Rosenbrock 2-3"}, {"dp45", "non-stiff, Dormand-Prince 4-5"},
        {"auto", "stiff or non-stiff, switching as it runs"},
        {"auto_julia", "stiff or non-stiff, as DifferentialEquations.jl chooses"},
        {"rodas5p", "stiff, Rosenbrock 5"}, {"radau5", "stiff, Radau IIA 5"},
        {"fbdf", "stiff, fixed-leading-coefficient BDF"}, {"fbdf_krylov", "stiff, FBDF by GMRES, no matrix"},
        {"qndf", "stiff, quasi-constant-step NDF"}, {"kencarp4", "stiff, ESDIRK 4"},
        {"trbdf2", "stiff, ESDIRK 2 (loose tolerances)"},
        {"rosenbrock23", "stiff, low order, Rosenbrock 2-3 as in Julia"}, {"tsit5", "non-stiff, Tsitouras 5"},
        {"vern7", "non-stiff, Verner 7"}, {"scipy_bdf", "SciPy BDF, stiff"},
        {"scipy_radau", "SciPy Radau IIA, stiff"}, {"scipy_lsoda", "SciPy LSODA, auto-switching"},
    };
    for (const auto& [key, label] : labels)
        if (id == key) return label;
    return "";
}

}  // namespace kompartment
