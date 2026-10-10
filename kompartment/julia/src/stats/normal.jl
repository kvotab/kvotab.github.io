# The standard normal distribution, as Kompartment computes it: the Python
# package's `kompartment/stats/_normal.py` (itself the application's `phi`,
# `probit` and `normalQuantile` in `src/domain/pdf.js`).
#
# `erf` and `erfc` are the expression language's own (`kf_erf`, `kf_erfc` in
# src/lang/functions.jl: W. J. Cody's interval near zero, Numerical Recipes'
# Chebyshev fit beyond), which are the same functions as `_normal.py`'s, step
# for step. Every exp and log here is the C library's (`cexp`, `clog`), as
# Python's `math` calls it, so each value is Python's to the last bit.

const _NQ_A = (-3.969683028665376e+1, 2.209460984245205e+2, -2.759285104469687e+2,
               1.383577518672690e+2, -3.066479806614716e+1, 2.506628277459239)
const _NQ_B = (-5.447609879822406e+1, 1.615858368580409e+2, -1.556989798598866e+2,
               6.680131188771972e+1, -1.328068155288572e+1)
const _NQ_C = (-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838,
               -2.549732539343734, 4.374664141464968, 2.938163982698783)
const _NQ_D = (7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996,
               3.754408661907416)
const _NQ_SQRT2 = sqrt(2.0)
const _NQ_LOW = 0.02425

"""
    normal_phi(z) -> Float64

The standard normal CDF: `0.5 erfc(-z/√2)`.
"""
normal_phi(z::Float64) = 0.5 * kf_erfc((-z) / _NQ_SQRT2)

"""
    normal_probit(p) -> Union{Float64,Nothing}

Acklam's approximation to the standard normal quantile; `nothing` outside
(0, 1), and for anything Python's `float()` cannot read as a number.
"""
function normal_probit(p)
    q = p isa Float64 ? p : py_float(p)
    (0 < q < 1) || return nothing
    a, b, c, d = _NQ_A, _NQ_B, _NQ_C, _NQ_D
    if q < _NQ_LOW
        t = sqrt(-2 * clog(q))
        return (((((c[1] * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5]) * t + c[6]) /
               ((((d[1] * t + d[2]) * t + d[3]) * t + d[4]) * t + 1)
    end
    if q <= 1 - _NQ_LOW
        t = q - 0.5
        r = t * t
        return ((((((a[1] * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * r + a[6]) * t) /
               (((((b[1] * r + b[2]) * r + b[3]) * r + b[4]) * r + b[5]) * r + 1)
    end
    t = sqrt(-2 * clog(1 - q))
    return (-(((((c[1] * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5]) * t + c[6])) /
           ((((d[1] * t + d[2]) * t + d[3]) * t + d[4]) * t + 1)
end

"""
    normal_quantile(p) -> Float64

The standard normal's inverse CDF: `normal_probit` and two Newton steps;
-Inf at or below 0, Inf at or above 1.
"""
function normal_quantile(p::Float64)
    p > 0 || return -Inf
    p < 1 || return Inf
    x = normal_probit(p)::Float64
    for _ in 1:2
        e = normal_phi(x) - p
        dens = cexp(-0.5 * x * x) / sqrt(2 * pi)
        dens > 0 || break
        x -= e / dens
    end
    return x
end
