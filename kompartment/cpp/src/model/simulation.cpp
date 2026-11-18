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

std::optional<double> py_float(const Json& v) {
    if (v.is_bool()) return v.as_bool() ? 1.0 : 0.0;
    if (v.is_number()) return v.as_double();
    if (!v.is_string()) return std::nullopt;
    std::string s(js_trim(v.as_string()));
    {
        std::string low = lowercase(s);
        std::string_view body = low;
        bool negative = false;
        if (!body.empty() && (body[0] == '+' || body[0] == '-')) {
            negative = body[0] == '-';
            body.remove_prefix(1);
        }
        if (body == "nan") return std::numeric_limits<double>::quiet_NaN();
        if (body == "inf" || body == "infinity")
            return negative ? -std::numeric_limits<double>::infinity() : std::numeric_limits<double>::infinity();
    }
    // [+-] digits[.digits] | .digits, an optional exponent; an underscore may stand
    // between two digits.
    std::string clean;
    std::size_t k = 0, n = s.size();
    auto digits = [&]() {
        std::size_t count = 0;
        while (k < n) {
            if (s[k] >= '0' && s[k] <= '9') {
                clean.push_back(s[k++]);
                count++;
            } else if (s[k] == '_' && count > 0 && k + 1 < n && s[k + 1] >= '0' && s[k + 1] <= '9') {
                k++;
            } else {
                break;
            }
        }
        return count;
    };
    if (k < n && (s[k] == '+' || s[k] == '-')) clean.push_back(s[k++]);
    std::size_t whole = digits(), frac = 0;
    if (k < n && s[k] == '.') {
        clean.push_back(s[k++]);
        frac = digits();
    }
    if (whole == 0 && frac == 0) return std::nullopt;
    if (k < n && (s[k] == 'e' || s[k] == 'E')) {
        clean.push_back(s[k++]);
        if (k < n && (s[k] == '+' || s[k] == '-')) clean.push_back(s[k++]);
        if (digits() == 0) return std::nullopt;
    }
    if (k != n) return std::nullopt;
    return std::strtod(clean.c_str(), nullptr);
}

int shorthand_points(const Json& count) {
    std::optional<double> v = py_float(count);
    if (v && 2 <= *v && *v <= MAX_OUTPUT_POINTS) return static_cast<int>(std::floor(*v + 0.5));
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
