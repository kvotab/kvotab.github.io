// A built model, ready to run: the derivative, the algebraic values and the hooks
// (what `buildSystem` returns in the application).
//
// The equations are compiled into passes -- the slots that never change (worked
// out once), those that change with the clock alone (once per instant), those
// that read the state (on every call) -- and the derivative is assembled as
//
//     dy/dt = A(X) [y; 1]
//
// one product of a sparse matrix with the state and a one: the linear terms'
// coefficients in the columns of the states they read, every other term in the
// last column. A has one entry per term, in the order the application adds the
// terms to each state, duplicates kept, and the product sums each row's terms
// in that order -- each product rounded on its own, never fused -- so the
// derivative is the application's to the last bit. With parity off the terms
// are merged first, one entry per state and column read, and the product is
// taken over those with fused multiply-adds: a third of the terms on a large
// assessment.

#pragma once

#include <cstdint>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "engine/builder.hpp"
#include "engine/project.hpp"
#include "engine/vm.hpp"

namespace kompartment {

/// The derivative's matrix with its terms merged (parity off): one entry per state and
/// column read, `vals`, worked out from its sources -- the slots it reads, with their
/// signs; the constant terms' sum, `konst`; the products of two slots and the far-field
/// paths' values, added from the terms' own values -- and the constant column per row,
/// `b`, from the affine terms.
struct MergedMatrix {
    std::vector<std::int32_t> rowptr, cols;
    std::vector<double> vals;
    std::vector<std::int32_t> src_ptr, src_slot;
    std::vector<double> src_sign;
    std::vector<double> konst;
    std::vector<std::int32_t> extra_pos, extra_dest;   // a product or far-field term: its place among the terms, and its entry
    std::vector<std::int32_t> fast;                    // the entries with a source that moves with the state
    std::vector<std::int32_t> extra_fast;              // the extra terms of those
    std::vector<std::int32_t> aff_rows, aff_ptr, aff_pos;
    std::vector<std::int32_t> aff_src;                 // linear sources that land in the constant column
    std::vector<double> b;
};

/// Where the derivative's terms come from, and how each row is summed.
struct Assembler {
    int n = 0;
    std::vector<std::int32_t> rowptr;   // over n rows
    std::vector<std::int32_t> cols;     // n is the column of the constant one
    std::vector<double> data;
    // The linear coefficients' sources: those that read a slot moving with the state from
    // `lin_fast_from` on, the others before it.
    std::vector<std::int32_t> lin_xsign_pos, lin_xsign_slot;
    std::vector<double> lin_xsign_sign;
    std::size_t lin_fast_from = 0;
    std::vector<std::int32_t> lin_xx_pos, lin_xx_a, lin_xx_b;
    std::vector<double> lin_xx_sign;
    std::vector<std::int32_t> lin_const_pos;
    std::vector<double> lin_const_val;
    bool consts_written = false;
    std::vector<std::pair<int, std::vector<std::int32_t>>> lin_farf;   // (path, positions)
    // The affine terms, written on every call.
    std::vector<std::int32_t> aff_xsign_pos, aff_xsign_slot;
    std::vector<double> aff_xsign_sign;
    std::vector<std::int32_t> aff_x_pos, aff_x_slot;
    std::vector<std::int32_t> aff_fail_pos, aff_fail_h, aff_fail_p, aff_fail_r;
    std::vector<std::int32_t> aff_mean_pos, aff_mean_slot, aff_mean_mem;
    int moves = 0;   // 0 constant, 1 with the clock, 2 with the state
    long key_version = -1;
    double key_clock = std::numeric_limits<double>::quiet_NaN();
    bool keyed = false;
    bool empty = true;
    std::shared_ptr<MergedMatrix> merged;

    Assembler() = default;
    explicit Assembler(const Builder& b);
};

/// A model's passes, compiled once and shared by every copy of its system.
struct Passes {
    Program invariant, at_instant, moving, moving_derivative, initial;
    bool has_derivative = false;
};

struct JacobianInfo;

class System {
public:
    /// A project built into equations and compiled.
    explicit System(std::shared_ptr<const Project> project, bool jacobian = true);

    std::shared_ptr<const Project> project;
    std::shared_ptr<Builder> builder;
    int nstate = 0, nalg = 0, nparam = 0;
    std::vector<double> P;
    std::vector<double> X;
    ModelData data;
    double start_time = 0, end_time = 0;
    std::shared_ptr<const Passes> passes;
    Assembler assembler;
    long invariant_version = 0;
    std::vector<int> clock_idx;
    std::vector<double> lo_x, hi_x;
    double min_change = 0.0;
    double origin = 0.0;
    double lo_t, hi_t, clock_at;
    std::vector<EntryPtr> remembering;
    std::vector<int> event_slots;
    std::shared_ptr<JacobianInfo> jacobian;
    double compile_ms = 0, build_ms = 0;
    std::vector<std::vector<double>> sampled_times;   // per event: the occurrences drawn for this run

    bool has_events() const { return !event_slots.empty(); }
    bool has_store_step() const { return !remembering.empty(); }

    /// The distributed points of the lookup tables back into their tables.
    void refresh_tables();
    /// Works out the slots that never move (after a parameter has changed).
    void evaluate_invariant();
    /// Works the clock-only slots out every `interval` and interpolates between; 0 is off.
    void use_clock_interpolation(double interval, std::optional<double> from = std::nullopt);
    /// Brings the clock-only slots up to `t`, if they are not there already.
    void at_instant(double t, const double* y);
    /// Every algebraic slot at `(t, y)`, in `X`.
    const std::vector<double>& evaluate_algebraic(double t, const double* y);
    /// The algebraic slots the derivative reads at `(t, y)`; the others are left as they were.
    void evaluate_for_derivative(double t, const double* y);
    /// The derivative at `(t, y)`.
    void rhs(double* dy, double t, const double* y);
    std::vector<double> dydt(double t, const std::vector<double>& y);
    std::vector<double> initial_state();

    /// Puts every history back to the start of a run.
    void prime_recorders(double t0, const std::vector<double>& y0);
    /// Records a step the solver accepted.
    void store_step(double t, const double* y);
    /// The discrete events' functions at `(t, y)`, into `out`.
    void event_values(double* out, double t, const double* y);
    /// Fires the events `which` (from 0) at `(t, y)`.
    void fire_events(const std::vector<int>& which, double t, const double* y);
    /// What the events the triggers `which` set off do to the state: applied to a copy of
    /// `y`, in the order the model lists them, each once however many of its trigger's
    /// indices fired together -- the state and how many acted, or none when none did.
    std::optional<std::pair<std::vector<double>, int>> jumps_at_crossing(const std::vector<int>& which, const std::vector<double>& y);
    /// Whether an event's occurrences are drawn for this run, and which.
    void set_disruption(int index, bool sampled, std::vector<double> times = {});
    /// Applies a jump's operations to `y`, in place.
    void apply_jump(std::vector<double>& y, const JumpSpec& spec) const;
    /// The times the tables read at the clock turn at, strictly inside (from, to), in order;
    /// none for a model with more than `limit` of them.
    std::optional<std::vector<double>> table_corners(double from, double to, double limit = std::numeric_limits<double>::infinity()) const;
    /// The tables read at the clock that do not repeat, each once.
    std::vector<std::shared_ptr<LookupTable>> clock_tables() const;

    /// A copy another thread can run beside this one: the passes, the build and every
    /// index vector shared; the parameters, the slots, the recorders' histories, the
    /// tables' values and the derivative's coefficients its own.
    System clone() const;

private:
    void run(const Program& pass, double t, const double* y);
    void clock_into(double t, const double* y, std::vector<double>& into);
    void assemble(double* dy, const double* y);
    void set_linear();
    void set_fast();
    void set_affine(const double* y);
    void set_extras();
    void set_farfield();
    void refresh_linear();
    void refresh_merged(MergedMatrix& M);

    std::vector<double> work_;
    std::vector<double> scratch_y_;
};

}  // namespace kompartment
