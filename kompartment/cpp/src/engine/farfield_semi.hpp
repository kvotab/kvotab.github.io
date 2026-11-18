// The runtime of a far-field path worked out semi-analytically, beside `FarfPath`
// for the paths on cells: a port of the Julia package's farfield_semi.jl,
// operation for operation.
//
// * no cells: one state per nuclide (per combination of the block's other
//   dimensions) for what the path holds, d(held)/dt = in - out - Lambda held;
// * `out`, the release, is the inflow's recorded history convolved with the
//   path's unit responses (farfield_laplace.*), worked out once per run from
//   the settings at its first instant;
// * the history is recorded at every accepted step, output time and segment
//   start, a cubic through the last four records between them; two records at
//   one instant are a step, a jump of what is held between them an amount
//   delivered at once;
// * each recorded piece is kept as six moments about its centre, and pieces
//   merge while they are narrow beside every response spacing they will still
//   meet;
// * the step being taken (from the last record to the time asked about) is
//   integrated exactly against the response, the current inflow's weight
//   being the release's derivative along it (the Jacobian's).
//
// The arithmetic is the Python engine's, numpy's pairwise sum over the history
// included, so that a run is its run to the last bit.

#pragma once

#include <array>
#include <functional>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "engine/farfield.hpp"
#include "engine/farfield_laplace.hpp"

namespace kompartment {

// --- one response, ready to convolve -----------------------------------------------------------

/// A unit response as quintic pieces in the power basis of each piece, with their running moments
/// and the narrowest spacing ahead of every lag.
struct SemiKernel {
    std::vector<double> t;
    int n = 0, np = 0;
    std::vector<double> a;       // 6 per piece: piece k's coefficients at a[6k..6k+5]
    std::vector<double> d;
    std::vector<double> ahead;
    double t0 = 0, t_end = 0, m0 = 0, tm0 = 0;
    std::vector<double> P;       // 4 per point: the integral of h u^q up to t[k], at P[4k+q]
    explicit SemiKernel(const lp::LPResponse& r);
};

int piece_at(const SemiKernel& kern, double u);
double kernel_at(const SemiKernel& kern, double u);
std::array<double, 4> piece_moments(const SemiKernel& kern, int k, double ua, double ub);
std::array<double, 4> running_moments(const SemiKernel& kern, double D);
std::vector<std::array<double, 5>> lag_basis(const std::vector<double>& s, int count, double D);
std::array<double, 6> semi_shift(const std::array<double, 6>& mu, double c, double w, double nc, double nw);
double semi_direct(const SemiKernel& kern, double t, double c, double w, const std::array<double, 4>& e);

// --- the recorded inflow of one source -----------------------------------------------------------

/// The inflow of one source, recorded, and what it has put into the path: blocks oldest first --
/// centre, half-width, six moments scaled by the half-width, and for a block still one recorded
/// piece its cubic in s = (tau - c)/w.
struct Convolver {
    std::vector<int> ti;                                  // the targets' slots (from 0)
    std::vector<std::shared_ptr<const SemiKernel>> tk;    // and their responses
    std::vector<double> bc, bw;
    std::vector<std::array<double, 6>> bm;
    std::vector<std::optional<std::array<double, 4>>> bp;
    std::vector<double> rt, rv;
    double last_t = -std::numeric_limits<double>::infinity();
    std::vector<double> imp_t, imp_a;
    std::size_t compact_at = 64;
    long long count = 0;
};

void impulse(Convolver& cv, double t, double amount);
void push_record(Convolver& cv, double t, double v);

/// Scratch for the history sums.
struct SemiScratch {
    std::vector<double> v;
    std::vector<int> wide;
};

/// What the recorded history releases at t, added into `out[i]` for each target.
void history(const Convolver& cv, double t, double* out, SemiScratch& scr);

/// The step from a source's last record to t (or a point mass inside it), for one target: the
/// weights of the cubic's nodes.
struct SemiPart {
    int i = 0;
    std::array<double, 4> w{};
    int count = 0;
    int nr = 0;
    int slot = 0;
};

void step_weights(std::vector<SemiPart>& out, const Convolver& cv, double t, int slot);
void point_parts(std::vector<SemiPart>& out, const Convolver& cv, double t, int slot);
double step_sum(const Convolver& cv, const SemiPart& part, double v);

// --- the path ------------------------------------------------------------------------------------

/// The unit responses of one combination: a kernel per pair (i, j) that has one, row-major.
struct SemiCombo {
    struct Miss {
        int i, j;
        double integral, expected, T0, rel, until;
    };
    std::vector<std::shared_ptr<const SemiKernel>> kernels;
    int pairs = 0;
    std::vector<Miss> misses;
};

/// Forgets every response kept (`clearResponses`).
void clear_semi_responses();

/// What a run leaves on the path that reading its results depends on.
struct LaplaceRunState {
    std::vector<double> rec_t;
    std::vector<std::vector<double>> rec_v, imp_t, imp_v;
    std::unordered_map<std::uint64_t, std::vector<double>> releases;
};

/// One far-field block worked out semi-analytically (`LaplaceFarfPath`).
struct LaplaceFarfPath final : FarfieldPath {
    int base, nnuc, other_width;
    std::vector<int> dim_off, single_off;
    std::unordered_map<std::string, int> setting_base;
    std::vector<std::string> keys;
    std::set<std::string> is_single;
    std::string surface;
    int release_base;
    double span;
    std::optional<std::vector<std::string>> names;
    std::string block_name;
    int nslots;
    std::vector<int> release_slots_;     // slots of X
    std::vector<int> held_idx_;          // states
    std::vector<int> cell_starts_;
    std::optional<lp::LPDecay> D;
    std::vector<int> in_tgt, in_rate, in_donor;
    std::vector<std::vector<std::pair<int, int>>> terms_into;
    // what a run changes
    std::vector<double> IN, held, last_held;
    std::vector<double> rec_t;                       // the records' times, every slot's alike
    std::vector<std::vector<double>> rec_v, imp_t, imp_v;
    std::vector<std::shared_ptr<const SemiCombo>> combos;
    std::optional<std::vector<Convolver>> live, sweep;
    double sweep_at;
    int sweep_next = 0;
    std::vector<int> sweep_imp;
    std::unordered_map<std::uint64_t, std::vector<double>> releases;   // by the time's bits, -0 as 0
    double last_t, hist_t;
    std::vector<double> hist_vals;
    double weight_t;
    std::vector<double> cur;
    std::vector<SemiPart> parts;
    bool weighed = false;
    bool ready = false;
    SemiScratch scratch;
    std::vector<double> res;
    std::vector<int> none_;
    std::vector<double> nothing_;

    LaplaceFarfPath(int base, int nnuc, int other_width, std::vector<int> dim_off, std::vector<int> single_off,
                    const std::unordered_map<std::string, int>& setting_base, std::vector<std::string> keys,
                    const std::vector<std::string>& single, const std::string& surface, int release_base, double span,
                    std::optional<std::vector<std::string>> names, std::string block_name);

    int slots() const override { return nslots; }
    const std::vector<int>& release_slots() const override { return release_slots_; }
    const std::vector<int>& held_idx() const override { return held_idx_; }
    void set_inflow(std::vector<int> where, std::vector<int> rate, std::vector<int> donor) override;
    void set_decay(const DecayTables* decay) override;
    const std::vector<int>& cell_starts() const override { return cell_starts_; }
    std::vector<int> setting_slots() const override;
    std::vector<int> setting_slots_of(int slot) const override;
    const std::vector<int>& row_flat() const override { return none_; }
    const std::vector<int>& col_flat() const override { return none_; }
    void refresh(const double*) override {}
    const std::vector<double>& values() const override { return nothing_; }
    void release(const double* y, double* X, double t) override;
    void restart() override;
    std::vector<int> rel_idx(int) const override { return {}; }
    const std::vector<double>& release_weights() const override { return nothing_; }
    std::shared_ptr<FarfieldPath> clone() const override;

    /// The unit responses of every combination, from the settings in X; `FarfError` with the
    /// reason for what the method cannot solve.
    void prepare(const double* X);
    /// Puts the history back to the start of a run and records its first instant.
    void prime(double t0, const double* y0, const double* X);
    /// Records an instant the solver has told the model about.
    void store(double t, const double* y, const double* X);
    LaplaceRunState run_state() const;
    void restore_run_state(const LaplaceRunState& state);
    /// For each release slot, the states it depends on: what the inflow into the same
    /// combination reads, since the step being taken carries it with a weight.
    std::vector<std::vector<int>> release_dependencies(const std::function<const std::vector<int>&(int)>& of_x) const;
    /// The weight of each source's current inflow in each target's release at t: `cur[slot * n + j]`.
    const std::vector<double>& current_weights(double t);
    /// Every unit response that missed its mass balance: never a quiet shortfall.
    std::vector<Json> balance_warnings() const;

    // (the pieces, for the tests)
    lp::LPSettings settings_of(const double* X, int o) const;
    int setting_at(const std::string& key, int o, int off) const;
    std::vector<Convolver> convolvers() const;
    const std::vector<double>& inflow(const double* y, const double* X);
    void weights(double t);
    void behind(const double* y, double* X, double t);
    void points_behind(const Convolver& cv, int slot, double t, double* out) const;
    double recorded_inflow(int slot, double tau) const;
    void truncate(double t);
};

/// `Number(x).toPrecision(4)` as the Python engine writes it for the balance warnings.
std::string js_precision4(double x);

/// A response key: the settings, the decay table, the span and the nuclides as one text.
std::string semi_response_key(const lp::LPSettings& s, const lp::LPDecay* D, double span, int nnuc);

}  // namespace kompartment
