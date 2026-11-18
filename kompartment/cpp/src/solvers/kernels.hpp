// The solvers' inner loops (engine/solvers/kernels.py).
//
// * The application's own dense LU (`formAndFactor`, `factorizeInPlace`,
//   `solve`): the same row-major elimination with partial pivoting, the same
//   pivot choice, one rounding per operation, so a dense factorisation is the
//   Python engine's to the last bit. It is held by rows, `lu[i*n + j]`, as the
//   application holds it, so every inner loop runs down contiguous memory.
// * The engine's own dense LU, the default where parity is off: by columns,
//   with fused multiply-adds.
// * The weighted norms and the checks for a constrained state at zero.

#pragma once

#include <cstdint>
#include <utility>
#include <vector>

#include "solvers/pattern.hpp"
#include "solvers/types.hpp"

namespace kompartment::sv {

constexpr int LU_OK = 0;
constexpr int LU_SINGULAR = 1;
constexpr int LU_NONFINITE = 2;

/// `factorizeInPlace` on the matrix `lu` held by rows. On failure `fail` holds
/// the column (counted from zero) and |pivot|.
int app_factor(double* lu, int n, I32* piv, double* fail);

/// Mass - a*J from a pattern's values, factorised (`_form_factor_pattern`).
/// A row `held` marks (non-zero) is a row of the identity.
int app_form_factor_pattern(double a, const Pattern& p, const Vec& values, const std::uint8_t* held, const Vec& mass,
                            Vec& lu, std::vector<I32>& piv, double* fail);

/// Mass - a*J from a dense Jacobian held by columns (`J[i + j*n]`), factorised
/// (`_form_factor_dense`).
int app_form_factor_dense(double a, const Vec& J, const std::uint8_t* held, const Vec& mass, Vec& lu,
                          std::vector<I32>& piv, double* fail);

/// The application's `solve` with the factors: `x = W \ b` (`x` and `b` distinct).
void app_solve(Vec& x, const Vec& lu, const std::vector<I32>& piv, const Vec& b);

/// The largest |v| / max(|ya|, |yb|, threshold) and where (`_weighted`): NaN and
/// the first index where it is not a number. The index is counted from zero.
std::pair<double, int> weighted_norm(const Vec& v, const Vec& ya, const Vec& yb, const Vec& threshold);

/// Whether every `y[idx]` is above zero (NaN is not).
inline bool all_above_zero(const Vec& y, const std::vector<I32>& idx) noexcept {
    for (I32 i : idx)
        if (!(y[i] > 0)) return false;
    return true;
}

/// Whether any `y[idx]` is below zero.
inline bool any_below_zero(const Vec& y, const std::vector<I32>& idx) noexcept {
    for (I32 i : idx)
        if (y[i] < 0) return true;
    return false;
}

/// max(0, max |v| * inv), NaN when any product is not a number (`_scaled_max`).
double scaled_max(const Vec& v, const Vec& inv) noexcept;

/// The weights of the states `lo` up to `hi`: `inv[i] = 1 / max(max(|y[i]|, |ynew[i]|), threshold[i])`,
/// the maxima Julia's (NaN when either is). Two states at a time where the processor has
/// that maximum as one instruction -- the same operations, so the same bits.
void inverse_weights(double* inv, const double* y, const double* ynew, const double* threshold, int lo, int hi) noexcept;

/// Whether any of the states listed is below zero.
bool any_below_zero(const double* y, const std::vector<I32>& idx) noexcept;

/// `float(np.cumsum(v * v)[-1])`: the squares summed strictly in order.
double seq_sum_squares(const Vec& v) noexcept;

// --- the engine's own dense LU, the default -----------------------------------------------------------
//
// Where the engine need not reproduce the Python package's arithmetic (`parity()` off), a dense
// iteration matrix is held by columns and factorised and solved column by column: each inner loop
// is a contiguous update of one column by another, which the compiler turns into vector
// instructions with fused multiply-adds, where the application's row sums are a chain of
// dependent additions. The pivots are LAPACK's (the largest in the column).

/// Mass - a*J from a pattern's values, in `A` by columns (`A[i + j*n]` = W[i, j]); the rows `held`
/// marks are rows of the identity. 0, or `-LU_NONFINITE` with the first column and value that is
/// not a number.
int fast_form_pattern(Vec& A, double a, const Pattern& p, const Vec& values, const std::uint8_t* held,
                      const Vec& mass, double* fail);

/// Mass - a*J from a dense Jacobian held by columns, as `fast_form_pattern`.
int fast_form_dense(Vec& A, double a, const Vec& J, const std::uint8_t* held, const Vec& mass, double* fail);

/// LU with partial pivoting of `A` in place: L below the diagonal (unit), U on and above it, and
/// `piv[k]` the row swapped with row k at step k. On failure `fail` holds the column (from zero)
/// and |pivot|, as `app_factor` does.
int fast_factor(double* A, int n, I32* piv, double* fail);

/// `x = W \ x` for the factors `fast_factor` left in `A`.
void fast_solve(Vec& x, const Vec& A, const std::vector<I32>& piv);

}  // namespace kompartment::sv
