// The iteration matrix Mass - a*J: formed, factorised, solved with
// (engine/solvers/matrix.py).
//
// A sparse matrix is factorised by the application's own sparse LUs
// (sparselu.hpp), chosen as it chooses them -- the application's choice, fill
// and factors, to the bit, as the Python engine has them. A dense one is
// factorised by the application's dense LU (kernels.hpp) up to APP_LU_MAX
// states -- its arithmetic, bit for bit, or with parity off the engine's own
// -- and by the engine's own beyond (where the Python and Julia engines go to
// LAPACK, whose builds round differently from one another anyway). Which one
// follows the application's rule: dense for small systems or where the sparse
// factor fills in past a share of n^2, sparse otherwise -- decided on real
// factorisations of the first matrix, never on the clock.

#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "solvers/pattern.hpp"
#include "solvers/sparselu.hpp"
#include "solvers/types.hpp"
#include "util/json.hpp"

namespace kompartment {

/// What the matrix refuses to be made or factorised with (Python's RuntimeError).
struct MatrixError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// The matrix Newton iterates with: `IterationMatrix`, or one a caller makes for
/// a system of a known block form (the `iteration_matrix` option of `ndf`).
class AbstractIterationMatrix {
public:
    virtual ~AbstractIterationMatrix() = default;
    /// Mass - a*J factorised, the rows `held` marks (where not null) as rows of
    /// the identity; nothing, or the message of why not.
    virtual std::optional<std::string> form(double a, const Vec& J, const std::vector<std::uint8_t>* held) = 0;
    /// `x = W \ x` for the latest factorisation.
    virtual void solve_inplace(Vec& x) = 0;
    /// What a run gives back when it ends, however it ends.
    virtual void release() {}
    /// Which LU, and how full its factor is: a dictionary with `sparse`, `fill`, `lu`.
    virtual const Json& info() = 0;
};

/// `form(a, J, held)` factorises Mass - a*J with the rows `held` marks as rows
/// of the identity; `solve(x, b)` answers for the latest one.
///
/// `J` is the pattern's values when there is a pattern, and the dense Jacobian
/// by columns (`J[i + j*n]`) otherwise. The pattern is the caller's, and must
/// outlive the matrix.
class IterationMatrix : public AbstractIterationMatrix {
public:
    static constexpr double DENSE_MAX_BYTES = 2.0 * 1024 * 1024 * 1024;
    static constexpr int APP_LU_MAX = 200;
    static constexpr int DENSE_BELOW = 24;
    static constexpr double DENSE_FILL = 0.15;

    IterationMatrix(int n, const Pattern* pattern, const Vec& J0, const std::string& mode = "auto",
                    const Vec* mass = nullptr, const Hints* hints = nullptr, int dense_below = DENSE_BELOW,
                    double dense_fill = DENSE_FILL);

    std::optional<std::string> form(double a, const Vec& J, const std::vector<std::uint8_t>* held = nullptr) override;
    /// `x = W \ b` for the latest factorisation (`x`, `b` distinct).
    void solve(Vec& x, const Vec& b);
    void solve_inplace(Vec& x) override;
    const Json& info() override;
    /// The dictionary as it stands, without the sparse LU's latest counts read into it.
    const Json& info_as_made() const noexcept { return info_; }

    int n;
    /// Whether the matrix is factorised by a sparse LU.
    bool sparse = false;
    /// The application's sparse LUs, where `sparse`.
    std::unique_ptr<SparseLUMatrix> sw;

private:
    const Pattern* pattern_;
    bool has_mass_;
    Hints hints_;
    Json info_;
    bool kernels_;
    int lu_;
    // the application's LU (by rows), or the engine's own (by columns)
    Vec lut_;
    std::vector<I32> piv_;
    double fail_[2] = {0.0, 0.0};
    std::vector<std::uint8_t> no_held_;
    Vec mass_diag_;
    Vec work_;
    // a matrix of more than APP_LU_MAX states (by columns)
    Vec wd_;
    std::vector<I32> ipiv_;
    Vec masked_;

    std::string singular_message(int column) const;
    std::string non_finite_message(int column, double value) const;
};

/// Makes the matrix Newton iterates with, in place of `IterationMatrix`:
/// `(n, pattern, J, matrix, mass, hints)`, the pattern, mass and hints null where there are none.
using IterationMatrixFactory = std::function<std::unique_ptr<AbstractIterationMatrix>(
    int n, const Pattern* pattern, const Vec& J, const std::string& matrix, const Vec* mass, const Hints* hints)>;

}  // namespace kompartment
