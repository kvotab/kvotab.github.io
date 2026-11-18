// The integrators' shared types, and how they fail.
//
// Ports of the Python engine's own solvers (kompartment/engine/solvers), as the
// Julia engine has them (julia/src/solvers): the variable-order NDF that is the
// default, the Rosenbrock 2-3 and the Dormand-Prince 4-5, the iteration matrix
// they factorise, the event location they share, and `variable_order` -- how a
// run's settings become the NDF's arguments. With parity on, the per-state
// arithmetic is the Python engine's element for element and in its order (no
// fused multiply-adds, sums kept sequential), the powers in the step-size
// formulas are the C library's, a dense matrix of up to 200 states is
// factorised by the application's own LU and a sparse one by its sparse LUs --
// so a run takes the Python engine's steps and gives its numbers to the last
// bit.
//
// Messages are the Python engine's, word for word -- the indices they quote (a
// state, a column) are counted from zero as there, and so is every index this
// interface takes or gives.

#pragma once

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

using Vec = std::vector<double>;
using I32 = std::int32_t;
using I64 = std::int64_t;

/// What a model's kind of trouble most often is, by the failure it explains
/// ("singular", "noPattern").
using Hints = std::map<std::string, std::string>;

/// A run the solver could not finish. `kind` says how, `t` where.
///
/// Kinds: 'span', 'tolerance', 'nonfinite', 'singular', 'stalled', 'steps',
/// 'jacobian', 'aborted', 'output', 'weightFloor'. `t`, `last_t` are NaN where
/// Python's are None; `trace` (a list), `last_y` and `stats` (a dictionary) are
/// empty until the solver fills them. `block_name` is the block a value that is
/// not a number starts in, and `solver_message` what the solver said before the
/// message was said again with it in.
class SolverError : public std::exception {
public:
    std::string kind;
    std::string message;
    double t;
    Json trace;
    double last_t;
    Vec last_y;
    Json stats;
    std::optional<std::string> hint;
    std::optional<std::string> block_name;
    std::optional<std::string> solver_message;

    SolverError(std::string kind, std::string message, double t = std::numeric_limits<double>::quiet_NaN());
    const char* what() const noexcept override { return message.c_str(); }
};

/// The derivative: `f(dy, t, y)` writes every element of `dy`.
using RhsFunction = std::function<void(Vec& dy, double t, const Vec& y)>;
/// A Jacobian's values: `evaluate(vals, t, y)` writes them and returns true, or returns false to decline.
using JacobianEvaluate = std::function<bool(Vec& vals, double t, const Vec& y)>;
/// Event functions: `fun(out, t, y)` writes the `n` values.
using EventFunction = std::function<void(Vec& out, double t, const Vec& y)>;
/// `on_accepted(t, y)` / `on_output(t, y)`.
using StepCallback = std::function<void(double t, const Vec& y)>;
/// The NDF's own `on_step(t, nsteps)`: false aborts.
using StepProgress = std::function<bool(double t, long nsteps)>;
/// A runner's `on_step(fraction, n, t)`: false aborts.
using RunProgress = std::function<bool(double fraction, long n, double t)>;
/// `landing(t, t_next)`: where a step from t to t_next is to end instead, or NaN.
using StepLanding = std::function<double(double t, double t_next)>;

/// Rows for a solver's output (an option's `rows`), handed out in turn and used
/// again from the first by the next run (`reset_rows`): a thread of a
/// probabilistic run keeps one, its realisations' series read out before the
/// next starts, so that a large model's rows -- hundreds of megabytes a
/// realisation -- are not made anew each time. A `Solution` made with a pool
/// reads the pool's rows: it is good until the pool hands them out again.
struct RowPool {
    std::vector<std::unique_ptr<Vec>> rows;
    std::size_t next = 0;
};

inline void reset_rows(RowPool& pool) noexcept { pool.next = 0; }

/// The next row of `pool`, holding a copy of `y`.
Vec& take_row(RowPool& pool, const Vec& y);

/// A solution's rows, read as a list of vectors: each its own copy, or a row of
/// the `RowPool` the run was given.
class Rows {
public:
    Rows() = default;
    Rows(const Rows& other);
    Rows& operator=(const Rows& other);
    Rows(Rows&&) noexcept = default;
    Rows& operator=(Rows&&) noexcept = default;

    std::size_t size() const noexcept { return rows_.size(); }
    bool empty() const noexcept { return rows_.empty(); }
    const Vec& operator[](std::size_t i) const { return *rows_[i]; }
    Vec& operator[](std::size_t i) { return *rows_[i]; }
    const Vec& front() const { return *rows_.front(); }
    const Vec& back() const { return *rows_.back(); }

    /// A row of its own, holding a copy of `y`.
    void push_copy(const Vec& y);
    /// A row kept elsewhere (a pool's), which must outlive the reading of it.
    void push_borrowed(Vec* row) { rows_.push_back(row); }
    void reserve(std::size_t n) { rows_.reserve(n); }

    class const_iterator {
    public:
        using inner = std::vector<Vec*>::const_iterator;
        explicit const_iterator(inner it) : it_(it) {}
        const Vec& operator*() const { return **it_; }
        const_iterator& operator++() { ++it_; return *this; }
        bool operator!=(const const_iterator& o) const { return it_ != o.it_; }
        bool operator==(const const_iterator& o) const { return it_ == o.it_; }
    private:
        inner it_;
    };
    const_iterator begin() const { return const_iterator(rows_.begin()); }
    const_iterator end() const { return const_iterator(rows_.end()); }

private:
    std::vector<Vec*> rows_;
    std::vector<std::unique_ptr<Vec>> own_;
};

namespace sv {

/// Python's builtin `max(a, b)`: `b` only when `b > a` (NaN never wins from the right).
inline double py_max(double a, double b) noexcept { return b > a ? b : a; }
/// Python's builtin `min(a, b)`.
inline double py_min(double a, double b) noexcept { return b < a ? b : a; }

/// Julia's `max` of two floats, which the weights are taken with: NaN when either
/// is, and +0 over -0.
inline double jl_max(double x, double y) noexcept {
    const double d = x - y;
    const double larger = std::signbit(d) ? y : x;
    return ((x != x) | (y != y)) ? d : larger;
}

constexpr double INF = std::numeric_limits<double>::infinity();
constexpr double NOT_A_NUMBER = std::numeric_limits<double>::quiet_NaN();

}  // namespace sv

}  // namespace kompartment
