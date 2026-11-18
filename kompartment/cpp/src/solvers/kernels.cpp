#include "solvers/kernels.hpp"

#include <algorithm>
#include <cmath>

#if defined(__aarch64__)
#include <arm_neon.h>
#endif

namespace kompartment::sv {

int app_factor(double* lu, int n, I32* piv, double* fail) {
    for (int i = 0; i < n; i++) piv[i] = i;
    for (int k = 0; k < n; k++) {
        int p = k;
        double max_abs = std::fabs(lu[static_cast<std::size_t>(k) * n + k]);
        for (int i = k + 1; i < n; i++) {
            const double v = std::fabs(lu[static_cast<std::size_t>(i) * n + k]);
            if (v > max_abs) {
                max_abs = v;
                p = i;
            }
        }
        if (!(max_abs > 0) || !std::isfinite(max_abs)) {
            fail[0] = k;
            fail[1] = max_abs;
            return max_abs != 0 ? LU_NONFINITE : LU_SINGULAR;
        }
        double* rk = lu + static_cast<std::size_t>(k) * n;
        if (p != k) {
            double* rp = lu + static_cast<std::size_t>(p) * n;
            for (int j = 0; j < n; j++) {
                const double tmp = rp[j];
                rp[j] = rk[j];
                rk[j] = tmp;
            }
            const I32 t = piv[p];
            piv[p] = piv[k];
            piv[k] = t;
        }
        const double pivot = rk[k];
        for (int i = k + 1; i < n; i++) {
            double* ri = lu + static_cast<std::size_t>(i) * n;
            const double f = ri[k] / pivot;
            if (f == 0) continue;
            ri[k] = f;
            // One row less a multiple of another: independent elements, each rounded twice.
            for (int j = k + 1; j < n; j++) ri[j] -= f * rk[j];
        }
    }
    return LU_OK;
}

int app_form_factor_pattern(double a, const Pattern& p, const Vec& values, const std::uint8_t* held, const Vec& mass,
                            Vec& lu, std::vector<I32>& piv, double* fail) {
    const int n = p.n;
    std::fill(lu.begin(), lu.end(), 0.0);
    int bad = -1;
    double bad_value = 0.0;
    for (int j = 0; j < n; j++) {
        for (I32 q = p.colptr[j]; q < p.colptr[j + 1]; q++) {
            const I32 i = p.rowval[q];
            if (held[i] != 0) continue;
            const double v = -a * values[q];
            if (bad < 0 && !std::isfinite(v)) {
                bad = j;
                bad_value = v;
            }
            lu[static_cast<std::size_t>(i) * n + j] = v;
        }
    }
    if (bad >= 0) {
        fail[0] = bad;
        fail[1] = bad_value;
        return -LU_NONFINITE;
    }
    for (int i = 0; i < n; i++) lu[static_cast<std::size_t>(i) * n + i] += mass[i];
    return app_factor(lu.data(), n, piv.data(), fail);
}

int app_form_factor_dense(double a, const Vec& J, const std::uint8_t* held, const Vec& mass, Vec& lu,
                          std::vector<I32>& piv, double* fail) {
    const int n = static_cast<int>(mass.size());
    int bad = -1;
    double bad_value = 0.0;
    for (int j = 0; j < n; j++) {
        const std::size_t off = static_cast<std::size_t>(j) * n;
        for (int i = 0; i < n; i++) {
            const double v = held[i] != 0 ? 0.0 : -a * J[off + i];
            if (bad < 0 && !std::isfinite(v)) {
                bad = j;
                bad_value = v;
            }
            lu[static_cast<std::size_t>(i) * n + j] = v;
        }
    }
    if (bad >= 0) {
        fail[0] = bad;
        fail[1] = bad_value;
        return -LU_NONFINITE;
    }
    for (int i = 0; i < n; i++) lu[static_cast<std::size_t>(i) * n + i] += mass[i];
    return app_factor(lu.data(), n, piv.data(), fail);
}

// Every row's sum is taken as the application takes it -- one term after
// another, the columns in order -- but the forward substitution runs four
// rows' sums side by side: their terms over the columns already solved for
// are independent, and each row then takes the block's own columns, still in
// order. The backward substitution's rows each start from the row just
// solved, and stay one after another.
// NOTE(speed): with parity on a dense solve is these chains of dependent subtractions, which
// cannot use vector instructions without changing the sums; with parity off `fast_solve` runs.
void app_solve(Vec& x_, const Vec& lu_, const std::vector<I32>& piv, const Vec& b) {
    const int n = static_cast<int>(x_.size());
    double* x = x_.data();
    const double* lu = lu_.data();
    const std::size_t N = static_cast<std::size_t>(n);
    for (int i = 0; i < n; i++) x[i] = b[piv[i]];
    int i = 1;
    while (i + 3 < n) {
        const double* r0 = lu + static_cast<std::size_t>(i) * N;
        const double* r1 = r0 + N;
        const double* r2 = r1 + N;
        const double* r3 = r2 + N;
        double s0 = x[i];
        double s1 = x[i + 1];
        double s2 = x[i + 2];
        double s3 = x[i + 3];
        for (int j = 0; j < i; j++) {
            const double xj = x[j];
            s0 -= r0[j] * xj;
            s1 -= r1[j] * xj;
            s2 -= r2[j] * xj;
            s3 -= r3[j] * xj;
        }
        x[i] = s0;
        s1 -= r1[i] * s0;
        x[i + 1] = s1;
        s2 -= r2[i] * s0;
        s2 -= r2[i + 1] * s1;
        x[i + 2] = s2;
        s3 -= r3[i] * s0;
        s3 -= r3[i + 1] * s1;
        s3 -= r3[i + 2] * s2;
        x[i + 3] = s3;
        i += 4;
    }
    while (i < n) {
        const double* ri = lu + static_cast<std::size_t>(i) * N;
        double s = x[i];
        for (int j = 0; j < i; j++) s -= ri[j] * x[j];
        x[i] = s;
        i += 1;
    }
    for (int r = n - 1; r >= 0; r--) {
        const double* ri = lu + static_cast<std::size_t>(r) * N;
        double s = x[r];
        for (int j = r + 1; j < n; j++) s -= ri[j] * x[j];
        x[r] = s / ri[r];
    }
}

std::pair<double, int> weighted_norm(const Vec& v, const Vec& ya, const Vec& yb, const Vec& threshold) {
    double worst = 0.0;
    int at = 0;
    const int n = static_cast<int>(v.size());
    for (int i = 0; i < n; i++) {
        const double s = py_max(py_max(std::fabs(ya[i]), std::fabs(yb[i])), threshold[i]);
        const double e = std::fabs(v[i]) / s;
        if (!(e >= 0) || !std::isfinite(yb[i])) return {NOT_A_NUMBER, i};
        if (i == 0 || e > worst) {
            worst = e;
            at = i;
        }
    }
    return worst > 0 ? std::pair<double, int>{worst, at} : std::pair<double, int>{0.0, 0};
}

// FMAX is the maximum of IEEE 754-2008 -- NaN when either is, +0 over -0 -- which is
// `jl_max` on every pair of numbers; the absolute value and the division are the same
// operations a state at a time or two.
void inverse_weights(double* inv, const double* y, const double* ynew, const double* threshold, int lo, int hi) noexcept {
    int i = lo;
#if defined(__aarch64__)
    const float64x2_t one = vdupq_n_f64(1.0);
    for (; i + 1 < hi; i += 2) {
        const float64x2_t a = vabsq_f64(vld1q_f64(y + i));
        const float64x2_t b = vabsq_f64(vld1q_f64(ynew + i));
        const float64x2_t m = vmaxq_f64(vmaxq_f64(a, b), vld1q_f64(threshold + i));
        vst1q_f64(inv + i, vdivq_f64(one, m));
    }
#endif
    for (; i < hi; i++) inv[i] = 1 / jl_max(jl_max(std::fabs(y[i]), std::fabs(ynew[i])), threshold[i]);
}

bool any_below_zero(const double* y, const std::vector<I32>& idx) noexcept {
    const std::size_t n = idx.size();
    const I32* at = idx.data();
    std::size_t q = 0;
    // In stretches, so that the loop has no way out inside it and a run of states all at
    // or above zero -- the usual one -- is read as fast as it can be.
    while (q < n) {
        const std::size_t end = std::min(n, q + 256);
        int below = 0;
        for (; q < end; q++) below |= y[at[q]] < 0 ? 1 : 0;
        if (below) return true;
    }
    return false;
}

// Every product is +0 or above, or NaN (flagged apart), so their largest is the
// same whatever order they are compared in: eight running maxima side by side
// give the one sequential loop's answer, bit for bit, four times faster.
double scaled_max(const Vec& v_, const Vec& inv_) noexcept {
    const std::size_t n = v_.size();
    const double* v = v_.data();
    const double* inv = inv_.data();
    double m[8] = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
    bool bad = false;
    std::size_t i = 0;
    for (; i + 7 < n; i += 8) {
        for (int q = 0; q < 8; q++) {
            const double a = std::fabs(v[i + q]) * inv[i + q];
            bad |= a != a;
            m[q] = a > m[q] ? a : m[q];
        }
    }
    for (; i < n; i++) {
        const double a = std::fabs(v[i]) * inv[i];
        bad |= a != a;
        m[0] = a > m[0] ? a : m[0];
    }
    if (bad) return NOT_A_NUMBER;
    double m1 = m[0];
    for (int q = 1; q < 8; q++) m1 = m[q] > m1 ? m[q] : m1;
    return m1;
}

double seq_sum_squares(const Vec& v) noexcept {
    double s = 0.0;
    for (double x : v) s += x * x;
    return s;
}

// --- the engine's own dense LU ----------------------------------------------------------------------

int fast_form_pattern(Vec& A, double a, const Pattern& p, const Vec& values, const std::uint8_t* held,
                      const Vec& mass, double* fail) {
    const int n = p.n;
    std::fill(A.begin(), A.end(), 0.0);
    for (int j = 0; j < n; j++) {
        const std::size_t off = static_cast<std::size_t>(j) * n;
        for (I32 q = p.colptr[j]; q < p.colptr[j + 1]; q++) {
            const I32 i = p.rowval[q];
            if (held[i] != 0) continue;
            const double v = -a * values[q];
            if (!std::isfinite(v)) {
                fail[0] = j;
                fail[1] = v;
                return -LU_NONFINITE;
            }
            A[off + i] = v;
        }
    }
    for (int i = 0; i < n; i++) A[static_cast<std::size_t>(i) * n + i] += mass[i];
    return 0;
}

int fast_form_dense(Vec& A, double a, const Vec& J, const std::uint8_t* held, const Vec& mass, double* fail) {
    const int n = static_cast<int>(mass.size());
    for (int j = 0; j < n; j++) {
        const std::size_t off = static_cast<std::size_t>(j) * n;
        for (int i = 0; i < n; i++) {
            const double v = held[i] != 0 ? 0.0 : -a * J[off + i];
            if (!std::isfinite(v)) {
                fail[0] = j;
                fail[1] = v;
                return -LU_NONFINITE;
            }
            A[off + i] = v;
        }
    }
    for (int i = 0; i < n; i++) A[static_cast<std::size_t>(i) * n + i] += mass[i];
    return 0;
}

int fast_factor(double* A, int n, I32* piv, double* fail) {
    const std::size_t N = static_cast<std::size_t>(n);
    for (int k = 0; k < n; k++) {
        double* ck = A + static_cast<std::size_t>(k) * N;
        int p = k;
        double largest = std::fabs(ck[k]);
        for (int i = k + 1; i < n; i++) {
            const double v = std::fabs(ck[i]);
            if (v > largest) {
                largest = v;
                p = i;
            }
        }
        if (!(largest > 0) || !std::isfinite(largest)) {
            fail[0] = k;
            fail[1] = largest;
            return largest != 0 ? LU_NONFINITE : LU_SINGULAR;
        }
        piv[k] = p;
        if (p != k) {
            for (int j = 0; j < n; j++) std::swap(A[static_cast<std::size_t>(j) * N + k], A[static_cast<std::size_t>(j) * N + p]);
        }
        const double r = 1 / ck[k];
        for (int i = k + 1; i < n; i++) ck[i] *= r;
        // NOTE(speed): a blocked (or recursive) elimination would keep a large matrix in the
        // cache; the columns are taken one at a time here, as the Julia engine takes them.
        for (int j = k + 1; j < n; j++) {
            double* cj = A + static_cast<std::size_t>(j) * N;
            const double akj = cj[k];
            if (akj == 0) continue;
            for (int i = k + 1; i < n; i++) cj[i] = std::fma(-ck[i], akj, cj[i]);
        }
    }
    return LU_OK;
}

void fast_solve(Vec& x_, const Vec& A_, const std::vector<I32>& piv) {
    const int n = static_cast<int>(x_.size());
    const std::size_t N = static_cast<std::size_t>(n);
    double* x = x_.data();
    const double* A = A_.data();
    for (int k = 0; k < n; k++) {
        const I32 p = piv[k];
        if (p != k) std::swap(x[k], x[p]);
    }
    for (int j = 0; j + 1 < n; j++) {
        const double xj = x[j];
        if (xj == 0) continue;
        const double* cj = A + static_cast<std::size_t>(j) * N;
        for (int i = j + 1; i < n; i++) x[i] = std::fma(-cj[i], xj, x[i]);
    }
    for (int j = n - 1; j >= 0; j--) {
        const double* cj = A + static_cast<std::size_t>(j) * N;
        const double xj = x[j] / cj[j];
        x[j] = xj;
        if (xj == 0) continue;
        for (int i = 0; i < j; i++) x[i] = std::fma(-cj[i], xj, x[i]);
    }
}

}  // namespace kompartment::sv
