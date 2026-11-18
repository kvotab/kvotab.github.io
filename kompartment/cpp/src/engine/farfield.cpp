#include "engine/farfield.hpp"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <tuple>

#include "engine/farfield_semi.hpp"
#include "engine/system.hpp"
#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

const double NaN = std::numeric_limits<double>::quiet_NaN();
const double Inf = std::numeric_limits<double>::infinity();

double vector_norm2(double ax, double ay, double mx, bool found_nan) {
    if (std::isinf(mx)) return mx;
    if (found_nan) return NaN;
    if (mx == 0.0) return mx;
    int max_e = 0;
    std::frexp(mx, &max_e);
    if (max_e < -1023) {
        double dmin = std::numeric_limits<double>::min();
        return dmin * vector_norm2(ax / dmin, ay / dmin, mx / dmin, found_nan);
    }
    double scale = std::ldexp(1.0, -max_e);
    double csum = 1.0;
    double frac1 = 0.0;
    double frac2 = 0.0;
    double x = ax * scale;
    double hi = x * x;
    double lo = std::fma(x, x, -hi);
    double s = csum + hi;
    frac2 += (csum - s) + hi;
    csum = s;
    frac1 += lo;
    x = ay * scale;
    hi = x * x;
    lo = std::fma(x, x, -hi);
    s = csum + hi;
    frac2 += (csum - s) + hi;
    csum = s;
    frac1 += lo;
    double h = std::sqrt(csum - 1.0 + (frac1 + frac2));
    hi = -h * h;
    lo = std::fma(-h, h, -hi);
    s = csum + hi;
    frac2 += (csum - s) + hi;
    csum = s;
    frac1 += lo;
    x = csum - 1.0 + (frac1 + frac2);
    h += x / (2.0 * h);
    return h / scale;
}

/// A layer's thickness for a person, as the application writes it (`thicknessText`).
std::string thickness_text(double x) {
    if (x >= 1) return js_to_precision(x, 3) + " m";
    if (x >= 1e-3) return js_to_precision(x * 1e3, 3) + " mm";
    return js_to_precision(x * 1e6, 3) + " \xc2\xb5m";
}

std::optional<std::string> surface_problem(const std::string& surface, const FarfSetting& s, double aw) {
    if (aw > 0 && std::isfinite(aw)) return std::nullopt;
    if (surface == "aw")
        return "The flow-wetted surface a_w must be positive: it is the wetted surface per unit volume of water (got " + num_text(aw) + ")";
    if (surface == "aperture")
        return "The fracture aperture must be a positive length: the wetted surface is 2/\xce\xb4 per unit volume of water (got \xce\xb4 = " +
               num_text(s.aperture) + ")";
    return "F/TW must be positive: it is the flow-wetted surface per unit volume of water (got " + num_text(aw) + ")";
}

/// The tangent of `wetted_surface`, given the tangent of each setting.
double wetted_surface_tangent(const std::string& surface, const FarfSetting& s, const FarfSetting& ds) {
    if (surface == "aw") return ds.aw;
    if (surface == "aperture") return (-2 * ds.aperture) / (s.aperture * s.aperture);
    return (ds.f * s.tw - s.f * ds.tw) / (s.tw * s.tw);
}

// The equation keys, by their place among `farf_equation_keys()`.
enum : int { K_TW, K_F, K_AW, K_APERTURE, K_KD_F, K_KD_M, K_DE_M, K_EPS_M, K_RHO_M, K_PE, K_PEN_DEP, K_PEN_DEP_0 };

/// Python's `str()` of what a block holds for a setting, for a message.
std::string ff_text(const Json& v) {
    if (v.is_string()) return v.as_string();
    if (v.is_bool()) return v.as_bool() ? "True" : "False";
    if (v.is_int()) return std::to_string(v.as_int());
    if (v.is_float()) return py_repr(v.as_double());
    if (v.is_null()) return "";
    return json_text(v, 0);
}

}  // namespace

// --- arithmetic as Python and numpy have it ------------------------------------------------

double py_hypot(double x, double y) {
    double ax = std::fabs(x);
    double ay = std::fabs(y);
    bool found_nan = std::isnan(ax) || std::isnan(ay);
    double mx = 0.0;
    if (ax > mx) mx = ax;
    if (ay > mx) mx = ay;
    return vector_norm2(ax, ay, mx, found_nan);
}

double np_pairwise(const double* v, std::size_t n) {
    if (n < 8) {
        double res = 0.0;
        for (std::size_t i = 0; i < n; i++) res += v[i];
        return res;
    }
    if (n <= 128) {
        double r1 = v[0], r2 = v[1], r3 = v[2], r4 = v[3];
        double r5 = v[4], r6 = v[5], r7 = v[6], r8 = v[7];
        std::size_t i = 8;
        std::size_t stop = n - (n % 8);
        while (i < stop) {
            r1 += v[i];
            r2 += v[i + 1];
            r3 += v[i + 2];
            r4 += v[i + 3];
            r5 += v[i + 4];
            r6 += v[i + 5];
            r7 += v[i + 6];
            r8 += v[i + 7];
            i += 8;
        }
        double res = ((r1 + r2) + (r3 + r4)) + ((r5 + r6) + (r7 + r8));
        while (i < n) {
            res += v[i];
            i += 1;
        }
        return res;
    }
    std::size_t n2 = n / 2;
    n2 -= n2 % 8;
    return np_pairwise(v, n2) + np_pairwise(v + n2, n - n2);
}

double py_pow(double iv, double iw) {
    if (iw == 0.0) return 1.0;
    if (std::isnan(iv)) return iv;
    if (std::isnan(iw)) return iv == 1.0 ? 1.0 : iw;
    if (std::isinf(iw)) {
        iv = std::fabs(iv);
        if (iv == 1.0) return 1.0;
        return (iw > 0.0) == (iv > 1.0) ? std::fabs(iw) : 0.0;
    }
    bool odd = std::fmod(std::fabs(iw), 2.0) == 1.0;   // DOUBLE_IS_ODD_INTEGER
    if (std::isinf(iv)) {
        if (iw > 0.0) return odd ? iv : std::fabs(iv);
        return odd ? std::copysign(0.0, iv) : 0.0;
    }
    if (iv == 0.0) {
        if (iw < 0.0) throw std::domain_error("0.0 cannot be raised to a negative power");
        return odd ? iv : 0.0;
    }
    bool negate = false;
    if (iv < 0.0) {
        if (iw != std::floor(iw)) throw std::domain_error("a negative number raised to a fractional power");
        iv = -iv;
        negate = odd;
    }
    if (iv == 1.0) return negate ? -1.0 : 1.0;
    double ix = std::pow(iv, iw);
    return negate ? -ix : ix;
}

double ff_pow(double q, int j) {
    if (j == 0) return 1.0;
    bool odd = (j % 2) != 0;
    if (std::isnan(q)) return q;
    if (q == 0 || std::isinf(q)) return odd ? q : std::fabs(q);
    if (q == 1.0) return 1.0;
    double r = std::pow(std::fabs(q), static_cast<double>(j));
    if (std::isinf(r)) return Inf;
    return (odd && q < 0) ? -r : r;
}

std::string num_text(double f) {
    if (std::isnan(f)) return "NaN";
    if (std::isinf(f)) return f > 0 ? "Infinity" : "-Infinity";
    if (f == std::floor(f) && std::fabs(f) < 1e21) {
        if (f == 0) return "0";
        char buf[40];
        std::snprintf(buf, sizeof buf, "%.0f", f);
        return buf;
    }
    return py_repr(f);
}

// --- the geometry ------------------------------------------------------------------------------

void layer_depths(double* d, double pen_dep, int nm, double aw, double first) {
    if (!(pen_dep > 0 && std::isfinite(pen_dep))) throw FarfError("The penetration depth must be a positive length (got " + py_repr(pen_dep) + ")");
    if (!(aw > 0 && std::isfinite(aw)))
        throw FarfError("F/TW must be positive: it is the flow-wetted surface per unit volume of water (got " + py_repr(aw) + ")");
    double d0 = first;
    if (!std::isfinite(d0) || !(d0 > 0)) {
        const double E = 2.718281828459045;
        // The series of nm layers from a first layer x, less the depth.
        auto geo = [&](double x) {
            double s = 0.0;
            for (int k = 1; k <= nm; k++) s += x * std::exp(static_cast<double>(k));
            return s - pen_dep;
        };
        d0 = zeroin(geo, 1e-12 / E, 2 / aw / E) * E;
    }
    if (d0 * nm > pen_dep * (1 + 1e-12)) {
        throw FarfError(std::to_string(nm) + " matrix layers starting at " + py_repr(d0) + " m cannot add up to a penetration depth of " +
                        py_repr(pen_dep) + " m: the layers grow with depth, so the first must be smaller than " + py_repr(pen_dep / nm) +
                        " m. Use a thinner first layer, fewer layers, a greater depth, or leave the first layer empty to have it worked out.");
    }
    // d0 q^j added up, less the depth.
    auto total = [&](double q) {
        double s = 0.0;
        for (int j = 0; j < nm; j++) s += d0 * ff_pow(q, j);
        return s - pen_dep;
    };
    double hi = 100.0;
    while (total(hi) < 0 && hi < 1e300) hi *= 100;
    double q = zeroin(total, 1.0, hi);
    for (int j = 0; j < nm; j++) d[j] = d0 * ff_pow(q, j);
}

void layer_depths_tangent(double* dd, double pen_dep, int nm, double aw, double first, const double* d, double d_pen_dep, double d_aw,
                          double d_first) {
    double d0 = d[0];
    double q = nm > 1 ? d[1] / d[0] : 1.0;
    double dd0;
    if (!std::isfinite(first) || !(first > 0)) {
        double bracket = 2 / aw;
        if (d0 >= bracket * (1 - 1e-12)) {
            dd0 = (-2 / (aw * aw)) * d_aw;
        } else {
            double s = 0.0;
            for (int k = 1; k <= nm; k++) s += std::exp(static_cast<double>(k));
            dd0 = (2.718281828459045 / s) * d_pen_dep;
        }
    } else {
        dd0 = d_first;
    }
    double total = 0.0;
    double dsum = 0.0;
    for (int j = 0; j < nm; j++) {
        total += ff_pow(q, j);
        if (j > 0) dsum += j * ff_pow(q, j - 1);
    }
    double dq = dsum == 0 ? 0.0 : (d_pen_dep - total * dd0) / (d0 * dsum);
    for (int j = 0; j < nm; j++) dd[j] = dd0 * ff_pow(q, j) + (j > 0 ? d0 * j * ff_pow(q, j - 1) * dq : 0.0);
}

double penetration_scale(double de, double rm, double lam, double rf, double aw, double tw, double pe) {
    if (!((de > 0) && (rm > 0) && (aw > 0) && std::isfinite(aw))) return Inf;
    if (!((tw > 0) && (pe > 0))) return Inf;
    double G = (FARF_ATTENUATION * (1 + FARF_ATTENUATION / pe)) / tw;
    double A = aw * std::sqrt(de * rm);
    double u = (2 * G) / (A + std::sqrt(A * A + 4 * rf * G));
    double u2 = ff_max(u * u, (std::isfinite(lam) && lam > 0) ? lam : 0.0);
    if (!((u2 > 0) && std::isfinite(u2))) return Inf;
    return std::sqrt(de / rm / u2);
}

std::optional<std::string> coarse_layers_warning(const double* d, int n, double q, const std::string& where) {
    if (!(q > COARSE_GROWTH)) return std::nullopt;
    if (n <= 0) return std::nullopt;
    double depth = 0.0;
    for (int i = 0; i < n; i++) depth += d[i];
    int need = 1;
    double step = d[0];
    double reach = d[0];
    while (reach < depth * (1 - 1e-12) && need < 10000) {
        step *= 2;
        reach += step;
        need += 1;
    }
    return "the " + std::to_string(n) + " matrix layers" + where + " grow by " + js_to_precision(q, 3) + " from a first layer of " +
           thickness_text(d[0]) + ", which is coarse at depth: " + std::to_string(need) + " layers would keep the growth to 2";
}

// --- the cells ---------------------------------------------------------------------------------

std::pair<std::vector<int>, std::vector<int>> cell_structure(const FarfStructure& g) {
    int nf = g.n_f, nm = g.n_m, ob = g.o_b, nb = g.n_b;
    int NF = nf + nb;
    std::vector<int> rows, cols;
    auto cell = [&](int k, int j) { return cell_index(k, j, nm); };
    auto at = [&](int r, int c) {
        rows.push_back(r);
        cols.push_back(c);
    };
    for (int k = 0; k < NF; k++) at(cell(k, 0), cell(k, 0));
    for (int k = 0; k < NF; k++)
        for (int j = 1; j <= nm; j++) at(cell(k, j), cell(k, j));
    for (int k = 1; k < NF; k++) {
        at(cell(k, 0), cell(k - 1, 0));
        at(cell(k - 1, 0), cell(k, 0));
    }
    if (ob == 3) at(cell(NF - 1, 0), cell(NF - 3, 0));
    for (int k = 0; k < NF; k++) {
        at(cell(k, 1), cell(k, 0));
        at(cell(k, 0), cell(k, 1));
    }
    for (int j = 0; j <= nm - 2; j++)
        for (int k = 0; k < NF; k++) {
            at(cell(k, j + 2), cell(k, j + 1));
            at(cell(k, j + 1), cell(k, j + 2));
        }
    return {rows, cols};
}

std::vector<int> release_cells(const FarfStructure& g) {
    int nf = g.n_f, nm = g.n_m, nb = g.n_b, ob = g.o_b;
    auto cell = [&](int k) { return cell_index(k - 1, 0, nm); };
    if (nb > 0) return {cell(nf), cell(nf + 1)};
    if (ob == 2) return {cell(nf), cell(nf - 1)};
    if (ob == 3) return {cell(nf), cell(nf - 1), cell(nf - 2)};
    return {cell(nf)};
}

FarfSetting::FarfSetting()
    : tw(NaN), f(NaN), aw(NaN), aperture(NaN), kd_f(NaN), kd_m(NaN), de_m(NaN), eps_m(NaN), rho_m(NaN), pe(NaN), pen_dep(NaN), pen_dep_0(NaN), lam(0.0) {}

std::optional<std::string> rock_setting_problem(const FarfSetting& s) {
    struct Field {
        double v;
        const char* what;
    };
    const Field fields[] = {
        {s.kd_f, "The sorption on the fracture coating K_d,f"},
        {s.kd_m, "The partition coefficient in the rock matrix K_d,m"},
        {s.de_m, "The effective diffusivity in the rock matrix D_e,m"},
        {s.eps_m, "The porosity of the rock matrix \xce\xb5_m"},
        {s.rho_m, "The dry bulk density of the rock matrix \xcf\x81_m"},
    };
    for (const Field& f : fields) {
        if (f.v >= 0 && std::isfinite(f.v)) continue;
        return std::string(f.what) + " must be zero or positive (got " + js_text(f.v) + ")";
    }
    return std::nullopt;
}

double wetted_surface(const std::string& surface, const FarfSetting& s) {
    if (surface == "aw") return s.aw;
    if (surface == "aperture") return js_div(2.0, s.aperture);
    return js_div(s.f, s.tw);
}

FarfPath::FarfPath(const FarfStructure& g, int base_, int nnuc_, int other_width_, std::vector<int> dim_off_, std::vector<int> single_off_,
                   const std::unordered_map<std::string, int>& setting_base, const std::vector<std::string>& single, int release_base_,
                   std::vector<std::string> keys_, const std::string& grid, const std::string& surface_, std::string block_name_)
    : nf(g.n_f), nm(g.n_m), ob(g.o_b), nb(g.n_b), structure(g), block_name(std::move(block_name_)), base(base_), nnuc(nnuc_),
      other_width(other_width_), dim_off(std::move(dim_off_)), single_off(std::move(single_off_)), keys(std::move(keys_)),
      release_base(release_base_), matched(grid == "matched") {
    const auto& surfaces = farf_surfaces();
    surface = std::find(surfaces.begin(), surfaces.end(), surface_) != surfaces.end() ? surface_ : "f";
    ncells = (nf + nb) * (nm + 1);
    std::tie(rows, cols) = cell_structure(g);
    nnz = static_cast<int>(rows.size());
    std::vector<int> rel_cells = release_cells(g);
    nrel = static_cast<int>(rel_cells.size());
    nslots = other_width * nnuc;
    nkeys = static_cast<int>(keys.size());
    auto is_single = [&](const std::string& key) { return std::find(single.begin(), single.end(), key) != single.end(); };
    setting_at.assign(static_cast<std::size_t>(nslots * nkeys), 0);
    for (int o = 0; o < other_width; o++)
        for (int m = 0; m < nnuc; m++) {
            int slot = o * nnuc + m;
            int off = dim_off[static_cast<std::size_t>(slot)];
            for (int k = 0; k < nkeys; k++) {
                const std::string& key = keys[static_cast<std::size_t>(k)];
                int one = single_off.empty() ? 0 : single_off[static_cast<std::size_t>(o)];
                setting_at[static_cast<std::size_t>(slot * nkeys + k)] = setting_base.at(key) + (is_single(key) ? one : off);
            }
        }
    row_flat_.resize(static_cast<std::size_t>(nslots * nnz));
    col_flat_.resize(static_cast<std::size_t>(nslots * nnz));
    rel_at.resize(static_cast<std::size_t>(nslots * nrel));
    for (int o = 0; o < other_width; o++)
        for (int m = 0; m < nnuc; m++) {
            int s = o * nnuc + m;
            int obase = base + o * ncells * nnuc;
            for (int e = 0; e < nnz; e++) {
                row_flat_[static_cast<std::size_t>(s * nnz + e)] = obase + rows[static_cast<std::size_t>(e)] * nnuc + m;
                col_flat_[static_cast<std::size_t>(s * nnz + e)] = obase + cols[static_cast<std::size_t>(e)] * nnuc + m;
            }
            for (int r = 0; r < nrel; r++) rel_at[static_cast<std::size_t>(s * nrel + r)] = obase + rel_cells[static_cast<std::size_t>(r)] * nnuc + m;
        }
    for (int o = 0; o < other_width; o++)
        for (int c = 0; c < ncells; c++) cell_starts_.push_back(base + o * ncells * nnuc + c * nnuc);
    release_slots_.resize(dim_off.size());
    for (std::size_t i = 0; i < dim_off.size(); i++) release_slots_[i] = release_base + dim_off[i];
    for (const auto& k : farf_equation_keys()) {
        auto it = std::find(keys.begin(), keys.end(), k);
        key_pos.push_back(it == keys.end() ? -1 : static_cast<int>(it - keys.begin()));
    }
    vals.assign(static_cast<std::size_t>(nslots * nnz), 0.0);
    rel_w.assign(static_cast<std::size_t>(nslots * nrel), 0.0);
    seen.assign(static_cast<std::size_t>(nslots * nkeys), NaN);
    lam.assign(static_cast<std::size_t>(nnuc), 0.0);
    layers_d.assign(static_cast<std::size_t>(nm * other_width), 0.0);
    layers_h.assign(static_cast<std::size_t>(nm * other_width), 0.0);
    layers_q.assign(static_cast<std::size_t>(other_width), NaN);
    laid_out.assign(static_cast<std::size_t>(other_width), 0);
    changed.assign(static_cast<std::size_t>(nslots), 0);
    ref_d.assign(static_cast<std::size_t>(nm), 0.0);
    // (One more than the layer-to-layer rates there are, so that a single layer reads a zero.)
    mmf.assign(static_cast<std::size_t>(std::max(1, nm - 1)), 0.0);
    mmb.assign(static_cast<std::size_t>(std::max(1, nm - 1)), 0.0);
}

std::vector<int> FarfPath::setting_slots() const {
    std::vector<int> out;
    out.reserve(static_cast<std::size_t>(nslots * nkeys));
    for (int k = 0; k < nkeys; k++)
        for (int slot = 0; slot < nslots; slot++) out.push_back(setting_at[static_cast<std::size_t>(slot * nkeys + k)]);
    return out;
}

std::vector<int> FarfPath::setting_slots_of(int slot) const {
    auto first = setting_at.begin() + slot * nkeys;
    return std::vector<int>(first, first + nkeys);
}

std::vector<int> FarfPath::rel_idx(int slot) const {
    auto first = rel_at.begin() + slot * nrel;
    return std::vector<int>(first, first + nrel);
}

FarfSetting& FarfPath::read_setting(const double* X, int slot) {
    FarfSetting& s = setting;
    s.tw = xset(X, slot, K_TW);
    s.f = xset(X, slot, K_F);
    s.aw = xset(X, slot, K_AW);
    s.aperture = xset(X, slot, K_APERTURE);
    s.kd_f = xset(X, slot, K_KD_F);
    s.kd_m = xset(X, slot, K_KD_M);
    s.de_m = xset(X, slot, K_DE_M);
    s.eps_m = xset(X, slot, K_EPS_M);
    s.rho_m = xset(X, slot, K_RHO_M);
    s.pe = xset(X, slot, K_PE);
    s.pen_dep = xset(X, slot, K_PEN_DEP);
    double v = xset(X, slot, K_PEN_DEP_0);
    s.pen_dep_0 = v > 0 ? v : NaN;
    s.lam = lam[static_cast<std::size_t>(slot % nnuc)];
    return s;
}

void FarfPath::slot_rates(const FarfSetting& s, int slot, int o, bool ref_ready) {
    double pe = s.pe;
    if (!(pe > 0 && std::isfinite(pe)))
        throw FarfError("The Peclet number must be greater than zero: the dispersion is TW/Pe (got " + num_text(pe) + ")");
    double aw = wetted_surface(surface, s);
    if (auto bad = surface_problem(surface, s, aw)) throw FarfError(*bad);
    if (!(s.tw > 0 && std::isfinite(s.tw))) throw FarfError("The travel time T_w must be positive (got " + num_text(s.tw) + ")");
    if (auto rock = rock_setting_problem(s)) throw FarfError(*rock);
    double r_m = s.eps_m + s.rho_m * s.kd_m;
    if (!(r_m > 0 && std::isfinite(r_m))) {
        throw FarfError("The matrix capacity eps + rho*Kd must be greater than zero (got " + py_repr(s.eps_m) + " + " + py_repr(s.rho_m) + "*" +
                        py_repr(s.kd_m) + " = " + py_repr(r_m) + "). A rock with no porosity and no sorption has nothing for the nuclide to diffuse into.");
    }
    double f_df = 1 / (1 + s.kd_f * aw);
    double adv_f = (f_df * nf) / s.tw;
    double d_f = ff_max(0.0, adv_f * (nf / pe - 0.5));
    double de = s.de_m;
    double diff_fm1, diff_m1f;
    if (matched) {
        const double* d = layers_d.data() + static_cast<std::size_t>(o * nm);
        const double* h = layers_h.data() + static_cast<std::size_t>(o * nm);
        diff_fm1 = (f_df * aw * de) / h[0];
        diff_m1f = de / (r_m * d[0] * h[0]);
        for (int j = 0; j < nm - 1; j++) {
            mmf[static_cast<std::size_t>(j)] = de / (r_m * d[j] * h[j + 1]);
            mmb[static_cast<std::size_t>(j)] = de / (r_m * d[j + 1] * h[j + 1]);
        }
    } else {
        double* d = ref_d.data();
        if (!ref_ready) layer_depths(d, s.pen_dep, nm, aw, s.pen_dep_0);
        diff_fm1 = (f_df * 2 * aw * de) / d[0];
        diff_m1f = (2 * de) / (r_m * d[0] * d[0]);
        for (int j = 0; j < nm - 1; j++) {
            mmf[static_cast<std::size_t>(j)] = (2 * de) / (r_m * d[j] * (d[j] + d[j + 1]));
            mmb[static_cast<std::size_t>(j)] = (2 * de) / (r_m * d[j + 1] * (d[j + 1] + d[j]));
        }
    }
    cell_values(vals.data() + static_cast<std::size_t>(slot * nnz), adv_f, d_f, diff_fm1, diff_m1f, mmf.data(), mmb.data());
    release_weights_of(rel_w.data() + static_cast<std::size_t>(slot * nrel), adv_f, d_f);
}

void FarfPath::cell_values(double* out, double adv_f, double d_f, double diff_fm1, double diff_m1f, const double* f, const double* b) const {
    int NF = nf + nb;
    int i = 0;
    double frac_loss = -(adv_f + 2 * d_f + diff_fm1);
    for (int k = 0; k < NF; k++) out[i + k] = frac_loss;
    out[i] += d_f;
    if (ob == 1) out[i + NF - 1] += d_f;
    else if (ob == 2) out[i + NF - 1] += 2 * d_f;
    else if (ob == 3) out[i + NF - 1] += 3 * d_f;
    i += NF;
    for (int k = 0; k < NF; k++)
        for (int j = 1; j <= nm; j++) {
            if (j == 1) out[i] = -(diff_m1f + f[0]);
            else if (j == nm) out[i] = -b[nm - 2];
            else out[i] = -(f[j - 1] + b[j - 2]);
            i += 1;
        }
    for (int k = 1; k <= NF - 1; k++) {
        double v = d_f + adv_f;
        if (k == NF - 1) {
            if (ob == 2) v -= d_f;
            else if (ob == 3) v -= 3 * d_f;
        }
        out[i] = v;
        out[i + 1] = d_f;
        i += 2;
    }
    if (ob == 3) {
        out[i] = d_f;
        i += 1;
    }
    for (int k = 0; k < NF; k++) {
        out[i] = diff_fm1;
        out[i + 1] = diff_m1f;
        i += 2;
    }
    for (int j = 0; j < nm - 1; j++)
        for (int k = 0; k < NF; k++) {
            out[i] = f[j];
            out[i + 1] = b[j];
            i += 2;
        }
}

void FarfPath::release_weights_of(double* w, double adv_f, double d_f) const {
    if (nb > 0) {
        w[0] = adv_f + d_f;
        w[1] = -d_f;
    } else if (ob == 0) {
        w[0] = adv_f + d_f;
    } else if (ob == 1) {
        w[0] = adv_f;
    } else if (ob == 2) {
        w[0] = adv_f - d_f;
        w[1] = d_f;
    } else {
        w[0] = adv_f - 2 * d_f;
        w[1] = 3 * d_f;
        w[2] = -d_f;
    }
}

void FarfPath::lay_out(const double* X, int o) {
    int first_slot = o * nnuc;
    const FarfSetting& s = read_setting(X, first_slot);
    double aw = wetted_surface(surface, s);
    double pen_dep = s.pen_dep, first = s.pen_dep_0, tw = s.tw, pe = s.pe;
    for (int m = 0; m < nnuc; m++) {
        const FarfSetting& n = read_setting(X, first_slot + m);
        if (auto rock = rock_setting_problem(n)) throw FarfError(*rock);
    }
    auto scales = [&]() {
        double L = Inf;
        for (int m = 0; m < nnuc; m++) {
            const FarfSetting& n = read_setting(X, first_slot + m);
            double v = penetration_scale(n.de_m, n.eps_m + n.rho_m * n.kd_m, lam[static_cast<std::size_t>(m)], 1 + n.kd_f * aw, aw, tw, pe);
            if (v < L) L = v;
        }
        return L;
    };
    layers_q[static_cast<std::size_t>(o)] =
        matched_grid(layers_d.data() + static_cast<std::size_t>(o * nm), layers_h.data() + static_cast<std::size_t>(o * nm), pen_dep, nm, first, scales);
}

void FarfPath::refresh(const double* X) {
    bool any_changed = false;
    for (int slot = 0; slot < nslots; slot++) {
        bool ch = false;
        for (int k = 0; k < nkeys; k++) {
            std::size_t at = static_cast<std::size_t>(slot * nkeys + k);
            if (X[setting_at[at]] != seen[at]) {
                ch = true;
                break;
            }
        }
        changed[static_cast<std::size_t>(slot)] = ch;
        any_changed |= ch;
    }
    if (!any_changed) {
        if (!matched) return;
        if (std::all_of(laid_out.begin(), laid_out.end(), [](char c) { return c != 0; })) return;
    }
    for (int o = 0; o < other_width; o++) {
        int lo = o * nnuc;
        int hi = (o + 1) * nnuc;
        bool fresh = matched && !laid_out[static_cast<std::size_t>(o)];
        if (!fresh) {
            bool any_o = false;
            for (int slot = lo; slot < hi; slot++)
                if (changed[static_cast<std::size_t>(slot)]) {
                    any_o = true;
                    break;
                }
            if (!any_o) continue;
        }
        if (fresh) lay_out(X, o);
        bool ref_ready = false;
        try {
            for (int slot = lo; slot < hi; slot++) {
                if (!fresh && !changed[static_cast<std::size_t>(slot)]) continue;
                const FarfSetting& s = read_setting(X, slot);
                slot_rates(s, slot, o, ref_ready);
                ref_ready = true;
                for (int k = 0; k < nkeys; k++) {
                    std::size_t at = static_cast<std::size_t>(slot * nkeys + k);
                    seen[at] = X[setting_at[at]];
                }
            }
        } catch (...) {
            if (fresh) laid_out[static_cast<std::size_t>(o)] = 0;
            throw;
        }
        if (fresh) laid_out[static_cast<std::size_t>(o)] = 1;
    }
}

void FarfPath::release(const double* y, double* X, double) {
    refresh(X);
    const double* w = rel_w.data();
    for (int slot = 0; slot < nslots; slot++) {
        double q = 0.0;
        for (int r = 0; r < nrel; r++) {
            std::size_t at = static_cast<std::size_t>(slot * nrel + r);
            q += w[at] * y[rel_at[at]];
        }
        X[release_slots_[static_cast<std::size_t>(slot)]] = q;
    }
}

void FarfPath::restart() {
    std::fill(laid_out.begin(), laid_out.end(), 0);
    std::fill(seen.begin(), seen.end(), NaN);
    if (!pins || pins->empty()) return;
    for (int o = 0; o < other_width; o++) {
        if (static_cast<std::size_t>(o) >= pins->size()) continue;
        const std::optional<FarfLayers>& g = (*pins)[static_cast<std::size_t>(o)];
        if (!g) continue;
        if (g->d.size() != static_cast<std::size_t>(nm) || g->h.size() != static_cast<std::size_t>(nm)) continue;
        std::copy(g->d.begin(), g->d.end(), layers_d.begin() + o * nm);
        std::copy(g->h.begin(), g->h.end(), layers_h.begin() + o * nm);
        layers_q[static_cast<std::size_t>(o)] = g->q;
        laid_out[static_cast<std::size_t>(o)] = 1;
    }
}

void FarfPath::pin_layers(std::optional<std::vector<std::optional<FarfLayers>>> given) {
    if (matched && given && !given->empty()) pins = std::move(given);
    else pins.reset();
    restart();
}

void FarfPath::set_decay(const DecayTables* dec) {
    std::fill(lam.begin(), lam.end(), 0.0);
    if (dec) {
        std::size_t n = std::min(static_cast<std::size_t>(nnuc), dec->lam.size());
        std::copy(dec->lam.begin(), dec->lam.begin() + static_cast<std::ptrdiff_t>(n), lam.begin());
    }
    restart();
}

std::vector<Json> FarfPath::layer_warnings() const {
    std::vector<Json> out;
    if (!matched) return out;
    for (int o = 0; o < other_width; o++) {
        if (!laid_out[static_cast<std::size_t>(o)]) continue;
        std::string where = other_width > 1 ? " (index combination " + std::to_string(o + 1) + " of " + std::to_string(other_width) + ")" : "";
        auto msg = coarse_layers_warning(layers_d.data() + static_cast<std::size_t>(o * nm), nm, layers_q[static_cast<std::size_t>(o)], where);
        if (msg) out.push_back(Json::object({{"block", Json(block_name)}, {"message", Json(*msg)}}));
    }
    return out;
}

std::shared_ptr<FarfieldPath> FarfPath::clone() const {
    auto c = std::make_shared<FarfPath>(*this);
    c->setting = FarfSetting();
    return c;
}

// --- the tangents of a path's rates ----------------------------------------------------------------

FarfTangent::FarfTangent(const FarfPath& F)
    : dvals(static_cast<std::size_t>(F.nslots * F.nnz), 0.0), drel(static_cast<std::size_t>(F.nslots * F.nrel), 0.0),
      ref_d(static_cast<std::size_t>(F.nm), 0.0), dd(static_cast<std::size_t>(F.nm), 0.0), mmf(static_cast<std::size_t>(std::max(1, F.nm - 1)), 0.0),
      mmb(static_cast<std::size_t>(std::max(1, F.nm - 1)), 0.0), dmmf(static_cast<std::size_t>(std::max(1, F.nm - 1)), 0.0),
      dmmb(static_cast<std::size_t>(std::max(1, F.nm - 1)), 0.0) {}

namespace {

/// Slot `slot`'s settings' tangents into `ds` (NaN where the path has no such setting).
void read_tangent(FarfSetting& ds, const FarfPath& F, const double* dX, int slot) {
    ds.tw = F.xset(dX, slot, K_TW);
    ds.f = F.xset(dX, slot, K_F);
    ds.aw = F.xset(dX, slot, K_AW);
    ds.aperture = F.xset(dX, slot, K_APERTURE);
    ds.kd_f = F.xset(dX, slot, K_KD_F);
    ds.kd_m = F.xset(dX, slot, K_KD_M);
    ds.de_m = F.xset(dX, slot, K_DE_M);
    ds.eps_m = F.xset(dX, slot, K_EPS_M);
    ds.rho_m = F.xset(dX, slot, K_RHO_M);
    ds.pe = F.xset(dX, slot, K_PE);
    ds.pen_dep = F.xset(dX, slot, K_PEN_DEP);
    ds.pen_dep_0 = F.xset(dX, slot, K_PEN_DEP_0);
}

/// One slot's rates worked out again, as `slot_rates` has them (its settings were checked
/// there), and their tangents into `T.dvals` and `T.drel`. The reference layers are worked
/// out into `T.ref_d` unless `ref_ready`.
void slot_rates_tangent(FarfTangent& T, const FarfPath& F, const FarfSetting& s, const FarfSetting& ds, int slot, int o, bool ref_ready) {
    int nf = F.nf, nm = F.nm;
    double pe = s.pe;
    double aw = wetted_surface(F.surface, s);
    double r_m = s.eps_m + s.rho_m * s.kd_m;
    double f_df = 1 / (1 + s.kd_f * aw);
    double adv_f = (f_df * nf) / s.tw;
    double d_f = ff_max(0.0, adv_f * (nf / pe - 0.5));
    double d_aw = wetted_surface_tangent(F.surface, s, ds);
    double d_rm = ds.eps_m + ds.rho_m * s.kd_m + s.rho_m * ds.kd_m;
    double d_fdf = -(ds.kd_f * aw + s.kd_f * d_aw) * f_df * f_df;
    double d_adv_f = (nf * (d_fdf * s.tw - f_df * ds.tw)) / (s.tw * s.tw);
    double shape = nf / pe - 0.5;
    double d_df = d_f > 0 ? d_adv_f * shape + adv_f * (-(nf / (pe * pe)) * ds.pe) : 0.0;
    double de = s.de_m, dde = ds.de_m;
    double* mmf = T.mmf.data();
    double* mmb = T.mmb.data();
    double* dmmf = T.dmmf.data();
    double* dmmb = T.dmmb.data();
    double d_fm1, d_m1f;
    if (F.matched) {
        // The matched layers are held for the run: only the rates over them move.
        const double* d = F.layers_d.data() + static_cast<std::size_t>(o * nm);
        const double* h = F.layers_h.data() + static_cast<std::size_t>(o * nm);
        double diff_m1f = de / (r_m * d[0] * h[0]);
        for (int j = 0; j < nm - 1; j++) {
            mmf[j] = de / (r_m * d[j] * h[j + 1]);
            mmb[j] = de / (r_m * d[j + 1] * h[j + 1]);
        }
        d_fm1 = (d_fdf * aw * de + f_df * d_aw * de + f_df * aw * dde) / h[0];
        d_m1f = dde / (r_m * d[0] * h[0]) - diff_m1f * (d_rm / r_m);
        for (int j = 0; j < nm - 1; j++) {
            dmmf[j] = dde / (r_m * d[j] * h[j + 1]) - mmf[j] * (d_rm / r_m);
            dmmb[j] = dde / (r_m * d[j + 1] * h[j + 1]) - mmb[j] * (d_rm / r_m);
        }
    } else {
        // The reference layers follow the settings, and so does their tangent.
        double* d = T.ref_d.data();
        if (!ref_ready) layer_depths(d, s.pen_dep, nm, aw, s.pen_dep_0);
        double diff_fm1 = (f_df * 2 * aw * de) / d[0];
        double diff_m1f = (2 * de) / (r_m * d[0] * d[0]);
        for (int j = 0; j < nm - 1; j++) {
            mmf[j] = (2 * de) / (r_m * d[j] * (d[j] + d[j + 1]));
            mmb[j] = (2 * de) / (r_m * d[j + 1] * (d[j + 1] + d[j]));
        }
        double* dd = T.dd.data();
        layer_depths_tangent(dd, s.pen_dep, nm, aw, s.pen_dep_0, d, ds.pen_dep, d_aw, ds.pen_dep_0);
        d_fm1 = (2 / d[0]) * (d_fdf * aw * de + f_df * d_aw * de + f_df * aw * dde) - (diff_fm1 / d[0]) * dd[0];
        d_m1f = (2 * dde) / (r_m * d[0] * d[0]) - diff_m1f * (d_rm / r_m + (2 * dd[0]) / d[0]);
        for (int j = 0; j < nm - 1; j++) {
            double sumd = d[j] + d[j + 1];
            double dsumd = dd[j] + dd[j + 1];
            dmmf[j] = (2 * dde) / (r_m * d[j] * sumd) - mmf[j] * (d_rm / r_m + dd[j] / d[j] + dsumd / sumd);
            dmmb[j] = (2 * dde) / (r_m * d[j + 1] * sumd) - mmb[j] * (d_rm / r_m + dd[j + 1] / d[j + 1] + dsumd / sumd);
        }
    }
    F.cell_values(T.dvals.data() + static_cast<std::size_t>(slot * F.nnz), d_adv_f, d_df, d_fm1, d_m1f, dmmf, dmmb);
    F.release_weights_of(T.drel.data() + static_cast<std::size_t>(slot * F.nrel), d_adv_f, d_df);
}

}  // namespace

bool farfield_tangent(FarfTangent& T, FarfPath& F, const double* X, const double* dX) {
    F.refresh(X);
    bool moving = false;
    for (std::size_t at = 0; at < F.setting_at.size() && !moving; at++)
        if (dX[F.setting_at[at]] != 0) moving = true;
    if (!moving) return false;
    int nnuc = F.nnuc;
    for (int o = 0; o < F.other_width; o++) {
        // The reference layers from the first slot's settings, as the refresh has them.
        bool ref_ready = false;
        for (int slot = o * nnuc; slot < (o + 1) * nnuc; slot++) {
            const FarfSetting& s = F.read_setting(X, slot);
            read_tangent(T.ds, F, dX, slot);
            slot_rates_tangent(T, F, s, T.ds, slot, o, ref_ready);
            ref_ready = true;
        }
    }
    return true;
}

// --- what the builder, the system and the runner call ----------------------------------------------

std::shared_ptr<FarfieldPath> make_farfield_path(Builder& b, const EntryPtr& p, const EntryPtr& rel,
                                                 const std::unordered_map<std::string, int>& setting_base, const std::vector<std::string>& keys) {
    const FarfLayout& farf = *p->farf;
    std::vector<std::string> single;
    const auto& per_nuclide = farf_nuclide_keys();
    for (const auto& k : keys)
        if (std::find(per_nuclide.begin(), per_nuclide.end(), k) == per_nuclide.end()) single.push_back(k);
    if (farf.laplace) {
        // A semi-analytical path's release reads what flows in at the same instant, so it is
        // worked out after every rate that delivers into the path.
        auto path_of = [&](const Json& to) -> EntryPtr {
            if (!to.is_string()) return nullptr;
            auto it = b.path_by_name.find(to.as_string());
            return it == b.path_by_name.end() ? nullptr : it->second;
        };
        for (const Json& t : b.project->blocks_of("transfers")) {
            const Json& to = t.get("to");
            if (js_truthy(to) && !(to.is_string() && b.state_by_name.count(to.as_string())) && path_of(to) == p)
                rel->needs.push_back(t.get("qname").as_string());
        }
        for (const Json& src : b.project->blocks_of("inflows")) {
            const Json& to = src.get("to");
            if (!(to.is_string() && b.state_by_name.count(to.as_string())) && path_of(to) == p) rel->needs.push_back(src.get("qname").as_string());
        }
        const Json& sim = b.project->simulation;
        std::optional<std::vector<std::string>> names;
        if (farf.list_name) names = b.space->index_names(*farf.list_name);
        return std::make_shared<LaplaceFarfPath>(p->base, farf.nnuc, farf.other_width, farf.dim_off, farf.single_off, setting_base, keys, single,
                                                 surface_of(p->block), rel->base,
                                                 sim.get("end_time").as_double() - sim.get("start_time").as_double(), names, p->name);
    }
    std::string grid = p->block.get("grid") == "matched" ? "matched" : "reference";
    return std::make_shared<FarfPath>(*farf.structure, p->base, farf.nnuc, farf.other_width, farf.dim_off, farf.single_off, setting_base, single,
                                      rel->base, keys, grid, surface_of(p->block), p->name);
}

int farfield_slots(const FarfieldPath& F) { return F.slots(); }
const std::vector<int>& farfield_release_slots(const FarfieldPath& F) { return F.release_slots(); }
const std::vector<int>& farfield_held_idx(const FarfieldPath& F) { return F.held_idx(); }
void farfield_set_inflow(FarfieldPath& F, std::vector<int> where, std::vector<int> rate, std::vector<int> donor) {
    F.set_inflow(std::move(where), std::move(rate), std::move(donor));
}
void farfield_set_decay(FarfieldPath& F, const DecayTables* decay) { F.set_decay(decay); }
std::vector<int> farfield_cell_starts(const FarfieldPath& F) { return F.cell_starts(); }
std::vector<int> farfield_setting_slots(const FarfieldPath& F) { return F.setting_slots(); }
std::pair<std::vector<int>, std::vector<int>> farfield_row_col(const FarfieldPath& F) { return {F.row_flat(), F.col_flat()}; }

std::vector<Json> farfield_outputs(const System& sys, const Entry& entry) {
    const FarfLayout& farf = *entry.farf;
    const Json& block = entry.block;
    const IndexSpace& space = *sys.builder->space;
    int held = held_cells(block);
    std::string unit = ff_text(block.get("unit"));
    // (What it holds is the release's unit without its "per time".)
    std::size_t slash = unit.rfind('/');
    if (slash != std::string::npos) unit.erase(slash);
    if (unit.empty()) unit = "Bq";
    bool report_cells = js_truthy(block.get("report_cells"));
    std::vector<std::string> cells;
    if (report_cells) cells = cell_names(block);
    std::vector<std::string> names;
    if (farf.list_name) names = space.index_names(*farf.list_name);
    const auto& material = sys.builder->material_list;
    bool has_material = material && !material->empty();
    std::vector<Json> out;
    for (int o = 0; o < farf.other_width; o++) {
        std::vector<std::string> others;
        if (!farf.other_dims.empty()) others = space.tuple_at(farf.other_dims, o);
        int base = entry.base + o * farf.ncells * farf.nnuc;
        for (int m = 0; m < farf.nnuc; m++) {
            Json nuclide = farf.list_name ? Json(names[static_cast<std::size_t>(m)]) : Json();
            std::vector<std::string> index;
            std::size_t k = 0;
            for (const auto& dim : entry.dims) {
                if (farf.list_name && dim == *farf.list_name) index.push_back(names[static_cast<std::size_t>(m)]);
                else index.push_back(others[k++]);
            }
            std::string suffix = index.empty() ? "" : " [" + join(index, ", ") + "]";
            Json offsets = Json::array();
            for (int c = 0; c < held; c++) offsets.push(Json(base + c * farf.nnuc + m));
            out.push_back(Json::object({{"kind", Json("farfield_inventory")},
                                        {"block", Json(entry.name + " held")},
                                        {"nuclide", has_material ? nuclide : Json()},
                                        {"index", index.empty() ? Json() : Json::array(index)},
                                        {"dims", Json::array(entry.dims)},
                                        {"label", Json(entry.name + " held" + suffix)},
                                        {"unit", Json(unit)},
                                        {"source", Json("y")},
                                        {"offsets", offsets}}));
            if (!report_cells) continue;
            for (int cell = 0; cell < farf.ncells; cell++) {
                const std::string& name = cells[static_cast<std::size_t>(cell)];
                out.push_back(Json::object({{"kind", Json("farfield_cell")},
                                            {"block", Json(entry.name + "." + name)},
                                            {"nuclide", has_material ? nuclide : Json()},
                                            {"index", index.empty() ? Json() : Json::array(index)},
                                            {"dims", Json::array(entry.dims)},
                                            {"label", Json(entry.name + "." + name + suffix)},
                                            {"unit", Json(unit)},
                                            {"source", Json("y")},
                                            {"offset", Json(base + cell * farf.nnuc + m)}}));
            }
        }
    }
    return out;
}

FarfieldWarnings farfield_warnings(const System& sys) {
    FarfieldWarnings out;
    for (const auto& F : sys.data.FARF) {
        if (const auto* semi = dynamic_cast<const LaplaceFarfPath*>(F.get())) {
            for (Json& w : semi->balance_warnings()) out.farfield.push_back(std::move(w));
        } else if (const auto* cells = dynamic_cast<const FarfPath*>(F.get())) {
            for (Json& w : cells->layer_warnings()) out.layers.push_back(std::move(w));
        }
    }
    return out;
}

namespace {

/// What each setting is called in a message: the application's labels as text.
std::string farf_text(const std::string& key) {
    static const std::map<std::string, std::string> text = {{"tw", "Tw"},           {"f", "F"},         {"aw", "aw"},       {"aperture", "\u03b4"},
                                                            {"kd_f", "Kd,f"},       {"kd_m", "Kd,m"},   {"de_m", "De,m"},   {"eps_m", "\u03b5m"},
                                                            {"rho_m", "\u03c1m"},  {"pe", "Pe"},       {"pen_dep", "PENDEP"}, {"pen_dep_0", "PENDEP0"}};
    auto it = text.find(key);
    return it == text.end() ? key : it->second;
}

/// Julia's `strip`: the white space at either end gone.
std::string stripped(const std::string& s) {
    const char* ws = " \t\n\r\v\f";
    std::size_t a = s.find_first_not_of(ws);
    if (a == std::string::npos) return "";
    std::size_t b = s.find_last_not_of(ws);
    return s.substr(a, b - a + 1);
}

}  // namespace

void semi_refusals(const Builder& b, const std::vector<double>& X) {
    for (const auto& p : b.farf_layout) {
        if (!p->farf->laplace) continue;
        for (const auto& key : active_equation_keys(p->block)) {
            auto it = b.alg_by_name.find(p->name + "#" + key);
            if (it == b.alg_by_name.end() || key == "pen_dep_0") continue;
            const EntryPtr& slot = it->second;
            int cls = 0;
            if (slot->width > 0)
                for (int k = slot->base; k < slot->base + slot->width; k++) cls = std::max(cls, static_cast<int>(b.slot_class[static_cast<std::size_t>(k)]));
            if (cls == 0) continue;
            std::string said = stripped(ff_text(p->block.get(key)));
            throw BuildError("'" + p->local_name.value_or(p->name) +
                                 "' is worked out semi-analytically, which solves the path once for the whole run, so its settings have to be "
                                 "constants -- and " +
                                 farf_text(key) + " follows the " + (cls == 1 ? "clock" : "state of the model") +
                                 (said.empty() ? "" : " ('" + said + "')") +
                                 ". Give it a constant, or work the path out on cells, which reads its settings as they change.",
                             p->name);
        }
        try {
            auto* F = dynamic_cast<LaplaceFarfPath*>(b.FARF[static_cast<std::size_t>(p->farf_index)].get());
            if (F) F->prepare(X.data());
        } catch (const FarfError& e) {
            throw BuildError("'" + p->local_name.value_or(p->name) + "' cannot be worked out semi-analytically: " + e.what(), p->name);
        }
    }
}

std::string layer_key(const IndexSpace& space, const std::vector<std::string>& dims, int o) {
    if (dims.empty()) return "";
    return join(space.tuple_at(dims, o), std::string_view("\0", 1));
}

std::optional<FarfLayerMap> whole_layers(System& sys, const Project& project) {
    const Builder& b = *sys.builder;
    std::vector<std::pair<EntryPtr, FarfPath*>> paths;
    for (const auto& p : b.farf_layout) {
        auto* F = dynamic_cast<FarfPath*>(sys.data.FARF[static_cast<std::size_t>(p->farf_index)].get());
        if (F && F->matched) paths.emplace_back(p, F);
    }
    if (paths.empty()) return std::nullopt;
    double t0 = project.simulation.get("start_time").as_double();
    std::vector<double> y = sys.initial_state();
    sys.prime_recorders(t0, y);
    std::vector<double> scratch(1, 0.0);
    const std::vector<double>& X = sys.evaluate_algebraic(t0, y.empty() ? scratch.data() : y.data());
    FarfLayerMap out;
    for (const auto& [p, F] : paths) {
        const FarfLayout& farf = *p->farf;
        std::map<std::string, FarfLayers> combos;
        for (int o = 0; o < farf.other_width; o++) {
            try {
                F->lay_out(X.data(), o);
            } catch (const std::exception&) {
                continue;   // left to the part, which says why when it runs
            }
            FarfLayers g;
            g.d.assign(F->layers_d.begin() + o * F->nm, F->layers_d.begin() + (o + 1) * F->nm);
            g.h.assign(F->layers_h.begin() + o * F->nm, F->layers_h.begin() + (o + 1) * F->nm);
            g.q = F->layers_q[static_cast<std::size_t>(o)];
            combos[layer_key(*b.space, farf.other_dims, o)] = std::move(g);
        }
        out[p->name] = std::move(combos);
    }
    return out;
}

void pin_layers(System& sys, const FarfLayerMap* layers) {
    const IndexSpace& space = *sys.builder->space;
    for (const auto& p : sys.builder->farf_layout) {
        auto* F = dynamic_cast<FarfPath*>(sys.data.FARF[static_cast<std::size_t>(p->farf_index)].get());
        if (!F) continue;
        const std::map<std::string, FarfLayers>* mine = nullptr;
        if (layers) {
            auto it = layers->find(p->name);
            if (it != layers->end()) mine = &it->second;
        }
        if (!mine || mine->empty()) {
            F->pin_layers(std::nullopt);
            continue;
        }
        const FarfLayout& farf = *p->farf;
        std::vector<std::optional<FarfLayers>> pins;
        for (int o = 0; o < farf.other_width; o++) {
            auto it = mine->find(layer_key(space, farf.other_dims, o));
            pins.push_back(it == mine->end() ? std::nullopt : std::optional<FarfLayers>(it->second));
        }
        F->pin_layers(std::move(pins));
    }
}

}  // namespace kompartment
