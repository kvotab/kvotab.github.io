#include "solvers/matrix.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "solvers/kernels.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

namespace kompartment {

namespace {

constexpr int MAT_NONE = 0;
constexpr int MAT_KERNEL = 1;
constexpr int MAT_BIG = 2;             // more than APP_LU_MAX states: the engine's own LU, where Julia's is LAPACK's
constexpr int MAT_FAST = 4;            // the engine's own dense LU (kernels.hpp), where parity is off

/// The application's mode code for a sparse LU (sparselu.hpp): what is not
/// `auto` or `refactor` is the searching LU, as in the Python engine.
int slu_mode(const std::string& mode) {
    return mode == "auto" ? slu::AUTO : mode == "refactor" ? slu::REFACTOR : slu::SPARSE_MODE;
}

std::string hint_of(const Hints& hints, const char* key) {
    auto it = hints.find(key);
    return it == hints.end() ? std::string() : it->second;
}

}  // namespace

std::string IterationMatrix::singular_message(int column) const {
    if (has_mass_ && mass_diag_[static_cast<std::size_t>(column)] == 0) {
        return "The iteration matrix M - h*J is singular at the algebraic variable in column " +
               std::to_string(column) +
               ": its constraint does not determine it. Check that the constraint depends on its own variable, "
               "that no two constraints say the same thing, and that the system is index 1.";
    }
    std::string base = std::string("The iteration matrix ") + (has_mass_ ? "M - h*J" : "I - h*J") +
                       " is singular at column " + std::to_string(column);
    const std::string hint = hint_of(hints_, "singular");
    return hint.empty() ? base : base + ". " + hint;
}

std::string IterationMatrix::non_finite_message(int column, double value) const {
    return std::string("The iteration matrix ") + (has_mass_ ? "M - h*J" : "I - h*J") +
           " has an entry that is not a number (" + py_repr(value) + ") at column " + std::to_string(column) +
           ": the Jacobian has a non-finite entry there.";
}

IterationMatrix::IterationMatrix(int n_, const Pattern* pattern, const Vec& J0, const std::string& mode,
                                 const Vec* mass, const Hints* hints, int dense_below, double dense_fill)
    : n(n_), pattern_(pattern), has_mass_(mass != nullptr), kernels_(n_ <= APP_LU_MAX), lu_(MAT_NONE) {
    if (hints != nullptr) hints_ = *hints;
    const std::size_t N = static_cast<std::size_t>(n);
    info_ = Json::object();
    info_.set("sparse", Json(false));
    info_.set("lu", Json("dense"));
    info_.set("fill", Json());
    info_.set("ordering", Json("natural"));
    info_.set("nnz", Json(static_cast<long long>(pattern != nullptr ? pattern->nnz() : N * N)));
    info_.set("repivots", Json(0));
    info_.set("fallbacks", Json(0));
    const bool too_big = static_cast<double>(n) * n * 8 > DENSE_MAX_BYTES;
    if (kernels_) lut_.assign(N * N, 0.0);
    piv_.assign(N, 0);
    no_held_.assign(N, 0);
    if (mass != nullptr) {
        mass_diag_ = *mass;
    } else {
        mass_diag_.assign(N, 1.0);
    }
    work_.assign(N, 0.0);
    if (pattern == nullptr) {
        if (too_big) {
            char gb[64];
            std::snprintf(gb, sizeof gb, "%.1f", static_cast<double>(n) * n * 8 / 1073741824.0);
            throw MatrixError("This model has " + std::to_string(n) +
                              " states, and without a sparsity pattern the solver would have to hold the iteration "
                              "matrix as " + std::to_string(n) + " by " + std::to_string(n) + " numbers -- " + gb +
                              " GB. " + hint_of(hints_, "noPattern"));
        }
        return;
    }
    masked_.assign(pattern->nnz(), 0.0);
    if (mode == "dense" && !too_big) return;
    if (mode == "auto" && n < dense_below && !too_big) return;
    auto made = std::make_unique<SparseLUMatrix>(n, pattern->colptr, pattern->rowval, J0, mass_diag_,
                                                 mass != nullptr, slu_mode(mode), dense_fill, too_big, true);
    info_.set("fill", made->fill < 0 ? Json() : Json(static_cast<long long>(made->fill)));
    info_.set("ordering", Json(slu::ORDERINGS[made->ordering]));
    if (made->kind == slu::DENSE) return;
    info_.set("sparse", Json(true));
    info_.set("lu", Json(slu::lu_name(*made)));
    sw = std::move(made);
    sparse = true;
}

std::optional<std::string> IterationMatrix::form(double a, const Vec& J, const std::vector<std::uint8_t>* held) {
    const std::size_t N = static_cast<std::size_t>(n);
    if (sw) {
        const int st = slu::form(*sw, a, J, held != nullptr ? held->data() : nullptr);
        if (st == slu::OK) return std::nullopt;
        if (st == slu::NONFINITE) return non_finite_message(sw->fail_column, sw->fail_value);
        return singular_message(sw->fail_column);
    }
    if (kernels_) {
        const std::uint8_t* h = held != nullptr ? held->data() : no_held_.data();
        const bool exact = parity();
        int status;
        if (exact) {
            status = pattern_ == nullptr ? sv::app_form_factor_dense(a, J, h, mass_diag_, lut_, piv_, fail_)
                                         : sv::app_form_factor_pattern(a, *pattern_, J, h, mass_diag_, lut_, piv_, fail_);
        } else {
            const int formed = pattern_ == nullptr ? sv::fast_form_dense(lut_, a, J, h, mass_diag_, fail_)
                                                   : sv::fast_form_pattern(lut_, a, *pattern_, J, h, mass_diag_, fail_);
            status = formed != 0 ? formed : sv::fast_factor(lut_.data(), n, piv_.data(), fail_);
        }
        if (status != 0) {
            const int col = static_cast<int>(fail_[0]);
            const double value = fail_[1];
            if (status == -sv::LU_NONFINITE || status == sv::LU_NONFINITE) return non_finite_message(col, value);
            return singular_message(col);
        }
        lu_ = exact ? MAT_KERNEL : MAT_FAST;
        return std::nullopt;
    }
    // More than APP_LU_MAX states: held by columns, checked as the Python engine checks what it
    // hands LAPACK, and factorised by the engine's own LU.
    if (wd_.size() != N * N) {
        wd_.assign(N * N, 0.0);
        ipiv_.assign(N, 0);
    }
    double* Wd = wd_.data();
    if (pattern_ == nullptr) {
        for (std::size_t q = 0; q < N * N; q++) Wd[q] = -a * J[q];
        if (held != nullptr) {
            for (std::size_t i = 0; i < N; i++) {
                if ((*held)[i] == 0) continue;
                for (std::size_t j = 0; j < N; j++) Wd[i + j * N] = 0.0;
            }
        }
    } else {
        const Pattern& p = *pattern_;
        const I32* rows = p.rowval.data();
        const I32* cols = p.col_of.data();
        Vec& vals = masked_;
        const std::size_t nz = vals.size();
        for (std::size_t q = 0; q < nz; q++) vals[q] = (held != nullptr && (*held)[rows[q]] != 0) ? 0.0 : J[q];
        for (std::size_t q = 0; q < nz; q++) {
            if (!std::isfinite(vals[q])) return non_finite_message(cols[q], vals[q]);
        }
        std::fill(wd_.begin(), wd_.end(), 0.0);
        for (std::size_t q = 0; q < nz; q++)
            Wd[static_cast<std::size_t>(rows[q]) + static_cast<std::size_t>(cols[q]) * N] = -a * vals[q];
    }
    for (std::size_t i = 0; i < N; i++) Wd[i + i * N] += mass_diag_[i];
    bool finite = true;
    for (std::size_t q = 0; q < N * N; q++) finite &= std::isfinite(Wd[q]);
    if (!finite) {
        // The first entry that is not a number, in Python's (row-major) order.
        for (std::size_t i = 0; i < N; i++)
            for (std::size_t j = 0; j < N; j++)
                if (!std::isfinite(Wd[i + j * N])) return non_finite_message(static_cast<int>(j), Wd[i + j * N]);
    }
    const int status = sv::fast_factor(Wd, n, ipiv_.data(), fail_);
    if (status == sv::LU_NONFINITE) return non_finite_message(static_cast<int>(fail_[0]), fail_[1]);
    if (status != sv::LU_OK) return singular_message(static_cast<int>(fail_[0]));
    lu_ = MAT_BIG;
    return std::nullopt;
}

void IterationMatrix::solve(Vec& x, const Vec& b) {
    if (sw) {
        slu::solve(*sw, b, x);
    } else if (lu_ == MAT_FAST) {
        std::copy(b.begin(), b.end(), x.begin());
        sv::fast_solve(x, lut_, piv_);
    } else if (lu_ == MAT_KERNEL) {
        sv::app_solve(x, lut_, piv_, b);
    } else {
        std::copy(b.begin(), b.end(), x.begin());
        sv::fast_solve(x, wd_, ipiv_);
    }
}

void IterationMatrix::solve_inplace(Vec& x) {
    if (sw) {
        // NOTE(speed): the sparse solves permute the right-hand side into work of their own, so
        // they could read `x` and write it back without this copy.
        std::copy(x.begin(), x.end(), work_.begin());
        slu::solve(*sw, work_, x);
    } else if (lu_ == MAT_FAST) {
        sv::fast_solve(x, lut_, piv_);
    } else if (lu_ == MAT_KERNEL) {
        std::copy(x.begin(), x.end(), work_.begin());
        sv::app_solve(x, lut_, piv_, work_);
    } else {
        sv::fast_solve(x, wd_, ipiv_);
    }
}

const Json& IterationMatrix::info() {
    if (sw) {
        info_.set("fill", sw->fill < 0 ? Json() : Json(static_cast<long long>(sw->fill)));
        info_.set("repivots", Json(static_cast<long long>(sw->repivots)));
        info_.set("fallbacks", Json(static_cast<long long>(sw->fallbacks)));
    }
    return info_;
}

}  // namespace kompartment
