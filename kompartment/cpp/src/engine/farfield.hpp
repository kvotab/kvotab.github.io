// The far-field pathway (FARFCOMP) at run time: a dual-porosity transport
// model behind one block (`FarfPath` in src/sim/farfield.js, as the Python and
// Julia engines port it).
//
// A path on cells has, for every nuclide and every index of its other
// dimensions, a fracture of n_f (+ n_b) cells and n_m matrix layers behind
// each; its rates are worked out from its setting slots whenever they move
// (`refresh`), on matched layers laid out once per run or on the reference
// implementation's layers, and its release is read off its last cells. A path
// worked out semi-analytically has one state per nuclide, for what it holds;
// this engine does not work those out yet.
//
// The arithmetic is the Python engine's operation for operation -- numpy's
// and CPython's where those differ from the C library's (`math.hypot`,
// `np.sum`, `np.spacing`, builtin `min`/`max`, `float ** int`) -- so that a run
// is the other engines' to the last bit. Every index here is the
// application's, counted from 0.

#pragma once

#include <cmath>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "engine/builder.hpp"

namespace kompartment {

class System;

// --- arithmetic as Python and numpy have it ------------------------------------------------

/// Python's builtin `max(a, b)`: the first unless the second is greater (NaN and ties keep `a`).
inline double ff_max(double a, double b) { return b > a ? b : a; }
/// Python's builtin `min(a, b)`: the first unless the second is less.
inline double ff_min(double a, double b) { return b < a ? b : a; }

/// numpy's `spacing`: the distance to the next double away from zero, signed like x; either
/// zero gives the least positive double.
inline double np_spacing(double x) {
    if (x == 0.0) return 5.0e-324;
    if (std::isnan(x) || std::isinf(x)) return std::numeric_limits<double>::quiet_NaN();
    return (x > 0 ? std::nextafter(x, std::numeric_limits<double>::infinity()) : std::nextafter(x, -std::numeric_limits<double>::infinity())) - x;
}

/// numpy's `sign` of a float: 1, -1, 0 for either zero, NaN for NaN.
inline double np_sign(double x) { return x > 0 ? 1.0 : x < 0 ? -1.0 : x == 0 ? 0.0 : std::numeric_limits<double>::quiet_NaN(); }

/// CPython's `math.hypot(x, y)` (`vector_norm`: lossless scaling, error-free squares,
/// compensated sums and a differential correction of the root), not the C library's `hypot`.
double py_hypot(double x, double y);

/// numpy's pairwise summation of `n` values from `v` (`pairwise_sum_DOUBLE`: blocks of 8
/// accumulators up to 128 terms, halves above).
double np_pairwise(const double* v, std::size_t n);
/// `np.sum` of the first `n` values of a 1-D float array: the reduction's initial 0.0 plus
/// the pairwise sum.
inline double np_sum(const double* v, std::size_t n) { return 0.0 + np_pairwise(v, n); }
inline double np_sum(const std::vector<double>& v) { return np_sum(v.data(), v.size()); }

/// CPython's `float ** float` for finite results: its special cases, then libm's `pow` of
/// the magnitude with the sign put back; an overflow (Python's OverflowError) is infinite.
/// Throws `std::domain_error` where Python raises (zero to a negative power, a negative
/// number to a fractional one).
double py_pow(double v, double w);

/// Python's `q ** j` for a whole j >= 0, infinite where Python overflows.
double ff_pow(double q, int j);

/// a / b as JavaScript has it.
inline double js_div(double a, double b) {
    if (b != 0) return a / b;
    if (a == 0 || a != a) return std::numeric_limits<double>::quiet_NaN();
    return std::copysign(std::numeric_limits<double>::infinity(), a) * std::copysign(1.0, b);
}

/// A number as the Python engine's messages write it (JavaScript's integers, Python's repr).
std::string num_text(double x);

/// `x.toPrecision(p)`: the exact binary value rounded to p digits, a tie going up.
std::string js_to_precision(double x, int p);

// --- errors ----------------------------------------------------------------------------------

/// A far-field path whose settings cannot describe a path.
struct FarfError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// --- the geometry ------------------------------------------------------------------------------

/// How far down the transfer function may fall before a frequency stops mattering (e^-25),
/// and how many times thinner than the depth diffusion reaches there the first matched layer is.
inline constexpr double FARF_ATTENUATION = 25.0;
inline constexpr double FARF_RESOLVE = 10.0;
/// How much matched layers may grow from one to the next before they are said to be coarse at depth.
inline constexpr double COARSE_GROWTH = 2.5;

/// Dekker's zeroin (1969), as the reports write it, on `fn`.
template <class Fn>
double zeroin(Fn&& fn, double a, double b) {
    double fa = fn(a);
    double fc = fa;
    double c = a;
    double fb = 0.0;
    for (int it = 0; it < 1000; it++) {
        fb = fn(b);
        if (np_sign(fb) == np_sign(fc)) {
            c = a;
            fc = fa;
        }
        if (std::fabs(fc) < std::fabs(fb)) {
            double a1 = b, b1 = c, c1 = b;
            a = a1;
            b = b1;
            c = c1;
            double fa1 = fb, fb1 = fc, fc1 = fb;
            fa = fa1;
            fb = fb1;
            fc = fc1;
        }
        double m = (b + c) / 2;
        if (std::fabs(m - b) <= np_spacing(std::fabs(b))) return b;
        double p = (b - a) * fb;
        double q = fa - fb;
        if (p < 0) {
            q = -q;
            p = -p;
        }
        a = b;
        fa = fb;
        if (p <= np_spacing(q)) {
            b += np_sign(c - b) * np_spacing(b);
        } else if (p <= (m - b) * q) {
            b += p / q;
        } else {
            b = m;
        }
    }
    return b;
}

/// The rock matrix's layer thicknesses (the reference layers, `get_d`) into `d[0..nm)`: a
/// geometric series adding up to the penetration depth; `first` NaN where it is to be worked out.
void layer_depths(double* d, double pen_dep, int nm, double aw, double first);

/// The tangent of `layer_depths` with respect to its own inputs, into `dd[0..nm)`: both
/// thicknesses come out of a root-find, so the derivative comes out of the implicit function
/// theorem. `first` NaN where the first layer was worked out.
void layer_depths_tangent(double* dd, double pen_dep, int nm, double aw, double first, const double* d, double d_pen_dep, double d_aw,
                          double d_first);

/// The depth diffusion reaches into the rock at the fastest frequency the path lets through,
/// for one nuclide.
double penetration_scale(double de, double rm, double lam, double rf, double aw, double tw, double pe);

/// The matched layers (`matchedGrid`) into `d[0..nm)`, `h[0..nm)`; returns q, the ratio of the
/// series. `first` NaN where the first layer is to be worked out from `scales()`, the
/// shallowest penetration scale.
template <class Scales>
double matched_grid(double* d, double* h, double pen_dep, int nm, double first, Scales&& scales);

/// What to say about matched layers that grow by more than `COARSE_GROWTH`, or nothing.
std::optional<std::string> coarse_layers_warning(const double* d, int n, double q, const std::string& where = "");

// --- the cells ---------------------------------------------------------------------------------

/// The (row, column) pairs the transport matrix fills, in cell numbering (from 0).
std::pair<std::vector<int>, std::vector<int>> cell_structure(const FarfStructure& g);
/// The cells the release is read from; for the semi-infinite outlet, the plane at the release point.
std::vector<int> release_cells(const FarfStructure& g);

/// One slot's settings, as a path reads them (NaN where the path has no such setting;
/// `pen_dep_0` NaN where it is not positive).
struct FarfSetting {
    double tw, f, aw, aperture, kd_f, kd_m, de_m, eps_m, rho_m, pe, pen_dep, pen_dep_0, lam;
    FarfSetting();
};

/// Why one slot's rock settings cannot be used, or nothing.
std::optional<std::string> rock_setting_problem(const FarfSetting& s);

/// A combination's matched layers, held from outside (`pinLayers`).
struct FarfLayers {
    std::vector<double> d, h;
    double q = std::numeric_limits<double>::quiet_NaN();
};
/// By path name, then by combination of the path's other dimensions (`layer_key`).
using FarfLayerMap = std::map<std::string, std::map<std::string, FarfLayers>>;

/// One far-field path, laid out and ready to be worked out.
struct FarfieldPath {
    bool laplace = false;
    virtual ~FarfieldPath() = default;

    virtual int slots() const = 0;
    virtual const std::vector<int>& release_slots() const = 0;
    virtual const std::vector<int>& held_idx() const = 0;
    virtual void set_inflow(std::vector<int> where, std::vector<int> rate, std::vector<int> donor) = 0;
    virtual void set_decay(const DecayTables* decay) = 0;
    virtual const std::vector<int>& cell_starts() const = 0;
    /// Every slot the settings are read from: key after key, each over every slot of the path.
    virtual std::vector<int> setting_slots() const = 0;
    /// The slots one of the path's slots reads its settings from, key after key.
    virtual std::vector<int> setting_slots_of(int slot) const = 0;
    virtual const std::vector<int>& row_flat() const = 0;
    virtual const std::vector<int>& col_flat() const = 0;
    /// Works the rates out again for every slot whose settings moved.
    virtual void refresh(const double* X) = 0;
    /// The values of the path's own terms, in the order of `row_flat`.
    virtual const std::vector<double>& values() const = 0;
    /// The release out of the far end of every slot, into its slot of X.
    virtual void release(const double* y, double* X, double t) = 0;
    /// Starts a run.
    virtual void restart() = 0;
    /// The states slot `slot`'s release is read from, and every slot's weights on them (slot after slot).
    virtual std::vector<int> rel_idx(int slot) const = 0;
    virtual const std::vector<double>& release_weights() const = 0;
    /// A copy for another thread: the structure and the index vectors shared in content, what a run changes its own.
    virtual std::shared_ptr<FarfieldPath> clone() const = 0;
};

/// One far-field block on cells at run time: its cells for every nuclide and every index of
/// its other dimensions, the rates worked out from its setting slots, the release read off
/// its last cells.
struct FarfPath final : FarfieldPath {
    int nf, nm, ob, nb;
    FarfStructure structure;
    std::string block_name;
    int base, nnuc, other_width;
    std::vector<int> dim_off, single_off;
    std::vector<std::string> keys;
    std::vector<int> key_pos;            // where each of the equation keys is among `keys` (-1: not there)
    int release_base;
    bool matched;
    std::string surface;
    int ncells, nnz, nrel, nslots, nkeys;
    std::vector<int> rows, cols;         // cell numbering
    std::vector<int> setting_at;         // nkeys per slot, slot after slot: slots of X
    std::vector<int> row_flat_, col_flat_;   // states, slot by slot
    std::vector<int> rel_at;             // nrel per slot: states
    std::vector<int> release_slots_;     // slots of X
    std::vector<int> cell_starts_;
    std::vector<int> none_;
    // what a run changes
    std::vector<double> vals;            // nnz per slot, slot after slot
    std::vector<double> rel_w;           // nrel per slot
    std::vector<double> seen;            // nkeys per slot
    std::vector<double> lam;
    std::vector<double> layers_d, layers_h;   // nm per combination (matched)
    std::vector<double> layers_q;
    std::vector<char> laid_out;
    std::optional<std::vector<std::optional<FarfLayers>>> pins;
    // scratch
    std::vector<char> changed;
    FarfSetting setting;
    std::vector<double> ref_d, mmf, mmb;

    FarfPath(const FarfStructure& structure, int base, int nnuc, int other_width, std::vector<int> dim_off, std::vector<int> single_off,
             const std::unordered_map<std::string, int>& setting_base, const std::vector<std::string>& single, int release_base,
             std::vector<std::string> keys, const std::string& grid, const std::string& surface, std::string block_name);

    int slots() const override { return nslots; }
    const std::vector<int>& release_slots() const override { return release_slots_; }
    const std::vector<int>& held_idx() const override { return none_; }
    void set_inflow(std::vector<int>, std::vector<int>, std::vector<int>) override {}
    void set_decay(const DecayTables* decay) override;
    const std::vector<int>& cell_starts() const override { return cell_starts_; }
    std::vector<int> setting_slots() const override;
    std::vector<int> setting_slots_of(int slot) const override;
    const std::vector<int>& row_flat() const override { return row_flat_; }
    const std::vector<int>& col_flat() const override { return col_flat_; }
    void refresh(const double* X) override;
    const std::vector<double>& values() const override { return vals; }
    void release(const double* y, double* X, double t) override;
    void restart() override;
    std::vector<int> rel_idx(int slot) const override;
    const std::vector<double>& release_weights() const override { return rel_w; }
    std::shared_ptr<FarfieldPath> clone() const override;

    /// Slot `slot`'s settings into the path's scratch record.
    FarfSetting& read_setting(const double* X, int slot);
    /// The matched layers of combination `o`, from every nuclide on it, each one's rock settings checked first.
    void lay_out(const double* X, int o);
    /// Holds a combination's matched layers at those given -- one per combination, or none for
    /// one left to lay out its own -- or, given nothing, lets every combination lay out its own again.
    void pin_layers(std::optional<std::vector<std::optional<FarfLayers>>> pins);
    /// What the run has to say about this path's layers: `{block, message}` per combination
    /// whose matched layers grow by more than `COARSE_GROWTH`.
    std::vector<Json> layer_warnings() const;

    double xset(const double* X, int slot, int key) const {
        int p = key_pos[static_cast<std::size_t>(key)];
        return p < 0 ? std::numeric_limits<double>::quiet_NaN() : X[setting_at[static_cast<std::size_t>(slot * nkeys + p)]];
    }
    void slot_rates(const FarfSetting& s, int slot, int o, bool ref_ready);
    /// The transport matrix's values from the rates, in the order `cell_structure` lists them, into `out[at..]`.
    void cell_values(double* out, double adv_f, double d_f, double diff_fm1, double diff_m1f, const double* mmf, const double* mmb) const;
    /// The release weights of one slot from the rates, into `w[0..nrel)`.
    void release_weights_of(double* w, double adv_f, double d_f) const;
};

/// The flow-wetted surface per unit volume of water, however the path gives it.
double wetted_surface(const std::string& surface, const FarfSetting& s);

/// Scratch for the tangents of a path's rates (`farfield_tangent`): the matrix's, nnz per slot
/// slot after slot as `vals`, and the release weights', nrel per slot as `rel_w`, with what
/// working them out needs.
struct FarfTangent {
    std::vector<double> dvals, drel;
    FarfSetting ds;
    std::vector<double> ref_d, dd, mmf, mmb, dmmf, dmmb;
    explicit FarfTangent(const FarfPath& F);
};

/// The tangents of the path's rates along the direction `dX` is the tangent of, into
/// `T.dvals` and `T.drel`: whether any setting moves along it at all. The matched layers are
/// held for the run, so only the rates over them move.
bool farfield_tangent(FarfTangent& T, FarfPath& F, const double* X, const double* dX);

// --- what the builder, the system and the runner call ----------------------------------------------

/// Lays a path out on the builder's slots. `rel` is its release slot, `setting_base` where
/// each of its settings' slots start, `keys` the settings it reads.
std::shared_ptr<FarfieldPath> make_farfield_path(Builder& b, const EntryPtr& p, const EntryPtr& rel,
                                                 const std::unordered_map<std::string, int>& setting_base,
                                                 const std::vector<std::string>& keys);

/// How many release slots a path has, the slots themselves, and the states it holds.
int farfield_slots(const FarfieldPath& F);
const std::vector<int>& farfield_release_slots(const FarfieldPath& F);
const std::vector<int>& farfield_held_idx(const FarfieldPath& F);
/// What flows into a semi-analytical path: where (within the path), the rate slots and the donors.
void farfield_set_inflow(FarfieldPath& F, std::vector<int> where, std::vector<int> rate, std::vector<int> donor);
void farfield_set_decay(FarfieldPath& F, const DecayTables* decay);
/// Where each cell's nuclides start in the state.
std::vector<int> farfield_cell_starts(const FarfieldPath& F);
/// Every slot a path's settings are read from.
std::vector<int> farfield_setting_slots(const FarfieldPath& F);
/// The rows and columns of a path's own terms in the derivative's matrix.
std::pair<std::vector<int>, std::vector<int>> farfield_row_col(const FarfieldPath& F);

/// The series a far-field path reports: what it holds per nuclide (summed over its cells, the
/// extra cells of a semi-infinite outlet left out) and, with `report_cells`, every cell.
std::vector<Json> farfield_outputs(const System& sys, const Entry& entry);

/// Every far-field path's warnings of a run: semi-analytical responses that missed their mass
/// balance (`stats.farfield`) and matched layers coarse at depth (`stats.layers`).
struct FarfieldWarnings {
    std::vector<Json> farfield, layers;
};
FarfieldWarnings farfield_warnings(const System& sys);

/// A combination of a path's other dimensions as one name (`layerKey`): its index names joined by NUL.
std::string layer_key(const IndexSpace& space, const std::vector<std::string>& dims, int o);

/// The far-field paths' matched layers as a run of the whole model lays them out at its first
/// instant, for a split run's parts to hold (`wholeLayers`); nothing for a model with no
/// matched layers.
std::optional<FarfLayerMap> whole_layers(System& sys, const Project& project);

/// Holds the far-field paths' matched layers at those given, or lets every path lay out its
/// own again, given none (`pinLayers`).
void pin_layers(System& sys, const FarfLayerMap* layers);

// --- templates -------------------------------------------------------------------------------------

template <class Scales>
double matched_grid(double* d, double* h, double pen_dep, int nm, double first, Scales&& scales) {
    if (!(pen_dep > 0 && std::isfinite(pen_dep))) throw FarfError("The penetration depth must be a positive length (got " + num_text(pen_dep) + ")");
    double d0 = first;
    if (!std::isfinite(d0) || !(d0 > 0)) {
        double L = scales();
        double even = pen_dep / nm;
        if (!(L < std::numeric_limits<double>::infinity())) {
            d0 = even;
        } else {
            d0 = L / FARF_RESOLVE;
            if (!(d0 < even)) d0 = even;
        }
    }
    if (d0 * nm > pen_dep * (1 + 1e-12)) {
        throw FarfError(std::to_string(nm) + " matrix layers starting at " + num_text(d0) + " m cannot add up to a penetration depth of " +
                        num_text(pen_dep) + " m: the layers grow with depth, so the first must be smaller than " + num_text(pen_dep / nm) +
                        " m. Use a thinner first layer, fewer layers, a greater depth, or leave the first layer empty to have it worked out.");
    }
    double q = 1.0;
    if (nm == 1 || d0 * nm >= pen_dep * (1 - 1e-12)) {
        for (int j = 0; j < nm; j++) d[j] = pen_dep / nm;
    } else {
        // d0 multiplied by r layer after layer, added up, less the depth.
        auto total = [&](double r) {
            double acc = 0.0;
            double t = d0;
            for (int k = 0; k < nm; k++) {
                acc += t;
                t *= r;
            }
            return acc - pen_dep;
        };
        double hi = 2.0;
        while (total(hi) < 0 && hi < 1e300) hi *= 2;
        q = zeroin(total, 1.0, hi);
        d[0] = d0;
        for (int j = 1; j < nm; j++) d[j] = d[j - 1] * q;
    }
    h[0] = d[0] / (1 + std::sqrt(q));
    for (int j = 1; j < nm; j++) h[j] = std::sqrt(d[j - 1] * d[j]);
    return q;
}

}  // namespace kompartment
