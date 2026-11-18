#include "stats/normal.hpp"

#include <cmath>

#include "lang/functions.hpp"
#include "stats/pdf.hpp"

namespace kompartment {

namespace {

constexpr double NQ_A[6] = {-3.969683028665376e+1, 2.209460984245205e+2, -2.759285104469687e+2,
                            1.383577518672690e+2, -3.066479806614716e+1, 2.506628277459239};
constexpr double NQ_B[5] = {-5.447609879822406e+1, 1.615858368580409e+2, -1.556989798598866e+2,
                            6.680131188771972e+1, -1.328068155288572e+1};
constexpr double NQ_C[6] = {-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838,
                            -2.549732539343734, 4.374664141464968, 2.938163982698783};
constexpr double NQ_D[4] = {7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996,
                            3.754408661907416};
const double NQ_SQRT2 = std::sqrt(2.0);
constexpr double NQ_LOW = 0.02425;
// sqrt(2 pi), as Julia's `sqrt(2 * pi)` works it out.
const double NQ_SQRT_2PI = std::sqrt(2 * 3.141592653589793);

}  // namespace

double normal_phi(double z) { return 0.5 * kf_erfc((-z) / NQ_SQRT2); }

std::optional<double> normal_probit(double q) {
    if (!(0 < q && q < 1)) return std::nullopt;
    const double* a = NQ_A;
    const double* b = NQ_B;
    const double* c = NQ_C;
    const double* d = NQ_D;
    if (q < NQ_LOW) {
        double t = std::sqrt(-2 * std::log(q));
        return (((((c[0] * t + c[1]) * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5]) /
               ((((d[0] * t + d[1]) * t + d[2]) * t + d[3]) * t + 1);
    }
    if (q <= 1 - NQ_LOW) {
        double t = q - 0.5;
        double r = t * t;
        return ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * t) /
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
    }
    double t = std::sqrt(-2 * std::log(1 - q));
    return (-(((((c[0] * t + c[1]) * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5])) /
           ((((d[0] * t + d[1]) * t + d[2]) * t + d[3]) * t + 1);
}

std::optional<double> normal_probit(const Json& p) {
    return normal_probit(p.is_float() ? p.as_double() : jl_py_float(p));
}

double normal_quantile(double p) {
    if (!(p > 0)) return -INFINITY;
    if (!(p < 1)) return INFINITY;
    double x = *normal_probit(p);
    for (int k = 0; k < 2; k++) {
        double e = normal_phi(x) - p;
        double dens = std::exp(-0.5 * x * x) / NQ_SQRT_2PI;
        if (!(dens > 0)) break;
        x -= e / dens;
    }
    return x;
}

}  // namespace kompartment
