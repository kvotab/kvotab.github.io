#include "engine/farfield_domain.hpp"

#include <cmath>
#include <cstdlib>
#include <limits>

#include "model/names.hpp"
#include "stats/pdf.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {
const double NaN = std::numeric_limits<double>::quiet_NaN();

bool among(const std::vector<std::string>& v, const Json& x) {
    if (!x.is_string()) return false;
    for (const auto& s : v)
        if (s == x.as_string()) return true;
    return false;
}

bool farf_empty(const Json& v) { return v.is_null() || (v.is_string() && js_trim(v.as_string()).empty()); }
/// `Number.isInteger(v)`.
bool whole_number(double v) { return std::isfinite(v) && v == std::floor(v); }
/// `Number(block.key)`: null and blank text 0, a setting not there NaN, text by JavaScript's grammar.
double farf_number(const Json& block, const char* key) { return pd_to_number(pd_prop(block, key)); }
}  // namespace

const std::vector<std::string>& farf_methods() {
    static const std::vector<std::string> v = {"discretized", "semi-analytical"};
    return v;
}
const std::vector<std::string>& farf_surfaces() {
    static const std::vector<std::string> v = {"f", "aw", "aperture"};
    return v;
}
const std::vector<std::string>& farf_grids() {
    static const std::vector<std::string> v = {"matched", "reference"};
    return v;
}
const std::vector<std::string>& farf_nuclide_keys() {
    static const std::vector<std::string> v = {"kd_f", "eps_m", "kd_m", "de_m"};
    return v;
}
const std::vector<std::string>& farf_single_keys() {
    static const std::vector<std::string> v = {"tw", "f", "aw", "aperture", "rho_m", "pe", "pen_dep", "pen_dep_0"};
    return v;
}
const std::vector<std::string>& farf_equation_keys() {
    static const std::vector<std::string> v = {"tw", "f", "aw", "aperture", "kd_f", "kd_m", "de_m", "eps_m", "rho_m", "pe",
                                               "pen_dep", "pen_dep_0"};
    return v;
}
const std::vector<std::string>& farf_structure_keys() {
    static const std::vector<std::string> v = {"n_f", "n_m", "o_b", "n_b"};
    return v;
}

Json farf_defaults() {
    return Json::object({
        {"method", Json("discretized")},
        {"tw", Json("100")}, {"surface", Json("f")}, {"f", Json("1e5")}, {"kd_f", Json("0")}, {"kd_m", Json("0")},
        {"de_m", Json("1e-4")}, {"eps_m", Json("0.0018")}, {"rho_m", Json("2700")}, {"pe", Json("10")},
        {"pen_dep", Json("12.5")}, {"pen_dep_0", Json("")}, {"n_f", Json(20)}, {"n_m", Json(12)},
        {"o_b", Json(CONTINUES)}, {"n_b", Json("")}, {"grid", Json("matched")}, {"handle_decay", Json(true)},
        {"report_cells", Json(false)},
    });
}

const Json& farf_legacy() {
    static const Json legacy = Json::object({{"o_b", Json(1)}, {"n_b", Json(0)}, {"grid", Json("reference")},
                                             {"surface", Json("f")}, {"method", Json("discretized")}, {"n_m", Json(20)}});
    return legacy;
}

std::string farf_surface_default(std::string_view key) {
    if (key == "f") return "1e5";
    if (key == "aw") return "1000";
    return "0.002";
}

double value_number(const Json& v) { return pd_to_number(v); }

bool uses_cells(const Json& block) {
    const Json& m = block.get("method");
    return m.is_null() || m == "" || m == "discretized";
}

bool is_semi_analytic(const Json& block) { return block.is_object() && block.get("method") == "semi-analytical"; }

std::string surface_of(const Json& block) {
    const Json& s = block.get("surface");
    return among(farf_surfaces(), s) ? s.as_string() : "f";
}

std::vector<std::string> active_equation_keys(const Json& block) {
    std::string used = surface_of(block);
    std::vector<std::string> out;
    for (const auto& k : farf_equation_keys()) {
        bool other = (k == "f" || k == "aw" || k == "aperture") && k != used;
        if (!other) out.push_back(k);
    }
    return out;
}

int auto_extra_cells(const Json& nf, const Json& pe) {
    double n = pd_to_number(nf);
    double p = pd_to_number(pe);
    if (!(whole_number(n) && n >= 1)) return 0;
    if (!(p > 0 && std::isfinite(p))) p = 10.0;
    double rho = (2 * n - p) / (2 * n + p);
    if (!(rho > 0)) return 0;
    int k = 0;
    double left = 1.0;
    while (left > 0.1 && k < 10000) {
        left *= rho;
        k++;
    }
    return k;
}

int extra_cells(const Json& block) {
    const Json& nb = block.get("n_b");
    if (farf_empty(nb))
        return farf_number(block, "o_b") == CONTINUES ? auto_extra_cells(block.get("n_f"), block.get("pe")) : 0;
    return static_cast<int>(pd_to_number(nb));
}

FarfStructure effective_structure(const Json& block) {
    double ob = farf_number(block, "o_b");
    int nf = static_cast<int>(farf_number(block, "n_f"));
    int nm = static_cast<int>(farf_number(block, "n_m"));
    int nb = extra_cells(block);
    if (ob == CONTINUES) return {nf, nm, 2, nb, true};
    return {nf, nm, static_cast<int>(ob), nb, js_truthy(block.get("downstream"))};
}

int cell_count(const Json& g) {
    if (is_semi_analytic(g)) return 1;
    if (!uses_cells(g)) return 0;
    FarfStructure e = effective_structure(g);
    return (e.n_f + e.n_b) * (e.n_m + 1);
}

int held_cells(const Json& block) {
    if (is_semi_analytic(block)) return 1;
    if (!uses_cells(block)) return 0;
    FarfStructure e = effective_structure(block);
    return (e.downstream ? e.n_f : e.n_f + e.n_b) * (e.n_m + 1);
}

std::vector<std::string> cell_names(const Json& g) {
    FarfStructure e = effective_structure(g);
    std::vector<std::string> names(static_cast<std::size_t>((e.n_f + e.n_b) * (e.n_m + 1)));
    for (int k = 0; k < e.n_f + e.n_b; k++) {
        names[static_cast<std::size_t>(cell_index(k, 0, e.n_m))] = "F" + std::to_string(k + 1);
        for (int j = 1; j <= e.n_m; j++)
            names[static_cast<std::size_t>(cell_index(k, j, e.n_m))] = "M" + std::to_string(k + 1) + "_" + std::to_string(j);
    }
    return names;
}

std::optional<std::string> structure_problem(const Json& g) {
    if (is_semi_analytic(g)) {
        const Json& v = g.get("surface");
        if (v.is_null() || v == "" || among(farf_surfaces(), v)) return std::nullopt;
        return "surface must be one of " + join(farf_surfaces(), ", ");
    }
    auto whole = [&](const char* key, int least) -> std::optional<std::string> {
        const double v = farf_number(g, key);
        if (!whole_number(v)) return std::string(key) + " must be a whole number";
        if (v < least) return std::string(key) + " must be at least " + std::to_string(least);
        return std::nullopt;
    };
    if (auto p = whole("n_f", 1)) return p;
    if (auto p = whole("n_m", 2)) return p;
    if (!farf_empty(g.get("n_b")))
        if (auto p = whole("n_b", 0)) return p;
    double obv = farf_number(g, "o_b");
    if (!(obv == 0 || obv == 1 || obv == 2 || obv == 3 || obv == 4)) return "o_b must be one of 0, 1, 2, 3, 4";
    struct Choice {
        const char* key;
        const std::vector<std::string>* allowed;
    };
    for (const Choice& c : {Choice{"method", &farf_methods()}, Choice{"grid", &farf_grids()}, Choice{"surface", &farf_surfaces()}}) {
        const Json& v = g.get(c.key);
        if (!v.is_null() && !(v == "") && !among(*c.allowed, v)) return std::string(c.key) + " must be one of " + join(*c.allowed, ", ");
    }
    FarfStructure e = effective_structure(g);
    if (e.o_b == 2 && e.n_f + e.n_b < 2) return "a linearly extrapolated outflow needs at least two fracture cells";
    if (e.o_b == 3 && e.n_f + e.n_b < 3) return "a quadratically extrapolated outflow needs at least three fracture cells";
    if (e.n_b == 0 && e.o_b == 3 && e.n_f < 3) return "reading the release under a quadratic outflow needs three fracture cells";
    if (e.n_b == 0 && e.o_b == 2 && e.n_f < 2) return "reading the release under a linear outflow needs two fracture cells";
    return std::nullopt;
}

std::optional<std::string> geometry_problem(const Json& block) {
    double nm = farf_number(block, "n_m");
    double pen_dep = farf_number(block, "pen_dep");
    const Json& raw_first = block.get("pen_dep_0");   // absent or null alike: no first layer given
    bool has_first = !(raw_first == "" || raw_first.is_null());
    double first = has_first ? pd_to_number(raw_first) : NaN;
    if (is_semi_analytic(block)) {
        if (std::isfinite(pen_dep) && !(pen_dep > 0)) return "the penetration depth must be a positive length";
        return std::nullopt;
    }
    if (!std::isfinite(pen_dep) || !whole_number(nm)) return std::nullopt;
    if (!(pen_dep > 0)) return "the penetration depth must be a positive length";
    if (!has_first || !std::isfinite(first)) return std::nullopt;
    if (!(first > 0)) return "the first matrix layer must be a positive length";
    if (first * nm > pen_dep * (1 + 1e-12))
        return js_number(nm) + " matrix layers starting at " + js_number(first) + " m cannot add up to a penetration depth of " +
               js_number(pen_dep) + " m: the layers grow with depth, so the first must be smaller than " + js_number(pen_dep / nm) + " m";
    return std::nullopt;
}

std::optional<std::string> rock_problem(const Json& block) {
    struct Term {
        const char* key;
        const char* what;
    };
    static const Term terms[] = {
        {"kd_f", "the sorption on the fracture coating K_d,f"},
        {"kd_m", "the partition coefficient in the rock matrix K_d,m"},
        {"de_m", "the effective diffusivity in the rock matrix D_e,m"},
        {"eps_m", "the porosity of the rock matrix \xce\xb5_m"},
        {"rho_m", "the dry bulk density of the rock matrix \xcf\x81_m"},
    };
    std::vector<Json> holders = {block};
    if (block.get("entries").is_array())
        for (const Json& e : block.get("entries").arr()) holders.push_back(e);
    for (std::size_t h = 0; h < holders.size(); h++) {
        const Json& holder = holders[h];
        if (!holder.is_object()) continue;
        for (const Term& term : terms) {
            const Json& v = holder.get(term.key);
            if (v.is_null() || js_trim(pd_js_str(v)).empty()) continue;
            double n = pd_to_number(v);
            if (!std::isfinite(n) || n >= 0) continue;
            std::string at;
            if (h > 0) {
                std::vector<std::string> parts;
                if (holder.get("index").is_object())
                    for (const auto& [k, x] : holder.get("index").obj()) parts.push_back(js_text(x));
                at = " at " + join(parts, ", ");
            }
            return std::string(term.what) + " must be zero or positive (got " + js_text(v) + at + ")";
        }
    }
    return std::nullopt;
}

}  // namespace kompartment
