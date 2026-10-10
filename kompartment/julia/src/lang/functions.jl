# The built-in functions of the equation language (src/parser/functions.js).
#
# The same names, aliases and arities, and the same answers: JavaScript's
# where Julia would throw (`log(-1)` is NaN, `sqrt(-1)` NaN, `1/0` Inf) and
# numpy's where the Python engine's numbers are the reference (`min` and
# `max` keep the first of two equal zeros, `sign(-0)` is 0). Every function
# here takes and returns Float64 scalars; the generated code calls them
# element by element.

const AVOGADRO = 6.02214179e23
const EPS = 2.0^-52

"""What the parser needs to know of a function: its canonical key and arity."""
struct FunctionSpec
    key::String
    arity::Int
    max_arity::Union{Nothing,Int}     # nothing: as many as given (varargs)
    needs_context::Bool               # time(), start_time(), end_time()
end

const FUNCTION_ARITIES = Dict{String,Tuple{Int,Union{Nothing,Int},Bool}}(
    "abs" => (1, 1, false), "sqrt" => (1, 1, false), "exp" => (1, 1, false), "log" => (1, 1, false),
    "log10" => (1, 1, false), "log2" => (1, 1, false), "power" => (2, 2, false), "hypot" => (2, 2, false),
    "ceil" => (1, 1, false), "floor" => (1, 1, false), "round" => (1, 1, false), "fix" => (1, 1, false),
    "sign" => (1, 1, false), "eps" => (0, 0, false), "ulp" => (1, 1, false), "pi" => (0, 0, false),
    "mod" => (2, 2, false), "rem" => (2, 2, false), "factorial" => (1, 1, false), "binomial" => (2, 2, false),
    "erf" => (1, 1, false), "erfc" => (1, 1, false), "sin" => (1, 1, false), "cos" => (1, 1, false),
    "tan" => (1, 1, false), "asin" => (1, 1, false), "acos" => (1, 1, false), "atan" => (1, 1, false),
    "atan2" => (2, 2, false), "sinh" => (1, 1, false), "cosh" => (1, 1, false), "tanh" => (1, 1, false),
    "asinh" => (1, 1, false), "acosh" => (1, 1, false), "atanh" => (1, 1, false),
    "min" => (1, nothing, false), "max" => (1, nothing, false), "sum" => (1, nothing, false),
    "prod" => (1, nothing, false), "mean" => (1, nothing, false), "if" => (2, 3, false), "not" => (1, 1, false),
    "and" => (2, nothing, false), "or" => (2, nothing, false), "nand" => (2, nothing, false),
    "nor" => (2, nothing, false), "xor" => (2, nothing, false), "percentile" => (2, nothing, false),
    "interpolationUseEndValues" => (3, nothing, false), "interpolationExtrapolation" => (3, nothing, false),
    "bq2mole" => (2, 2, false), "mole2bq" => (2, 2, false), "transport_point" => (2, nothing, false),
    "transport_sum" => (3, nothing, false), "transport_mean" => (3, nothing, false),
    "rampDown" => (3, 3, false), "rampUp" => (3, 3, false), "smoothDown" => (3, 3, false),
    "smoothUp" => (3, 3, false), "time" => (0, 0, true), "start_time" => (0, 0, true), "end_time" => (0, 0, true),
)

"""Aliases the language accepts."""
const FUNCTION_ALIASES = Dict("fabs" => "abs", "ln" => "log", "pow" => "power", "sgn" => "sign", "product" => "prod")

"""The function a name calls, or `nothing`."""
function lookup_function(name::AbstractString)
    key = get(FUNCTION_ALIASES, name, String(name))
    a = get(FUNCTION_ARITIES, key, nothing)
    a === nothing && return nothing
    return FunctionSpec(key, a[1], a[2], a[3])
end

# --- the arithmetic, one number at a time --------------------------------------------

@inline js_truth(x::Float64) = x != 0.0          # NaN is true, as in JavaScript
@inline b2f(b::Bool) = b ? 1.0 : 0.0

"""`Math.round`: the nearest integer, halves towards positive infinity; -0 for a negative that rounds to zero."""
@inline function kf_round(a::Float64)
    f = floor(a)
    r = f + b2f(a - f >= 0.5)
    return r == 0 ? copysign(0.0, a) : r
end

@inline kf_abs(x::Float64) = abs(x)
@inline kf_sqrt(x::Float64) = x < 0 ? NaN : sqrt(x)
@inline kf_exp(x::Float64) = cexp(x)
@inline kf_log(x::Float64) = clog(x)
@inline kf_log10(x::Float64) = clog10(x)
@inline kf_log2(x::Float64) = clog2(x)
"""
numpy's `power` with one exponent for every element: the exponents 2, 0.5 and
-1 are worked out as a square, a square root and a reciprocal, every other
one by the C library's pow. (numpy takes that short cut only when the
exponent is one number; an exponent per element always goes to pow, which
differs from the short cut in the last bit for about one argument in a
thousand.)
"""
@inline function np_pow(a::Float64, b::Float64)
    b == 2.0 && return a * a
    b == 0.5 && return kf_sqrt(a)
    b == -1.0 && return 1.0 / a
    return cpow(a, b)
end
"""`Math.pow` (the Python engine's `js_pow`): numpy's power, except that 1 and -1
to an infinite or NaN power are NaN. `kf_jspow` with an exponent per element,
`kf_jspow1` with one exponent for every element."""
@inline kf_jspow(a::Float64, b::Float64) = (abs(a) == 1.0 && !isfinite(b)) ? NaN : cpow(a, b)
@inline kf_jspow1(a::Float64, b::Float64) = (abs(a) == 1.0 && !isfinite(b)) ? NaN : np_pow(a, b)
@inline kf_hypot(a::Float64, b::Float64) = chypot(a, b)
@inline kf_ceil(x::Float64) = ceil(x)
@inline kf_floor(x::Float64) = floor(x)
@inline kf_fix(x::Float64) = trunc(x)
@inline kf_sign(x::Float64) = x > 0 ? 1.0 : x < 0 ? -1.0 : x == 0 ? 0.0 : x
@inline kf_ulp(x::Float64) = abs(x) * EPS
@inline kf_mod(a::Float64, b::Float64) = b == 0 ? a : a - b * floor(a / b)
@inline kf_rem(a::Float64, b::Float64) = b == 0 ? NaN : a - b * trunc(a / b)
@inline kf_sin(x::Float64) = csin(x)
@inline kf_cos(x::Float64) = ccos(x)
@inline kf_tan(x::Float64) = ctan(x)
@inline kf_asin(x::Float64) = casin(x)
@inline kf_acos(x::Float64) = cacos(x)
@inline kf_atan(x::Float64) = catan(x)
@inline kf_atan2(a::Float64, b::Float64) = catan2(a, b)
@inline kf_sinh(x::Float64) = csinh(x)
@inline kf_cosh(x::Float64) = ccosh(x)
@inline kf_tanh(x::Float64) = ctanh(x)
@inline kf_asinh(x::Float64) = casinh(x)
@inline kf_acosh(x::Float64) = cacosh(x)
@inline kf_atanh(x::Float64) = catanh(x)
"""numpy's `minimum`/`maximum`: NaN in, NaN out; of two equal values, the first."""
@inline kf_min(a::Float64, b::Float64) = (a <= b || isnan(a)) ? a : b
@inline kf_max(a::Float64, b::Float64) = (a >= b || isnan(a)) ? a : b
@inline kf_not(a::Float64) = b2f(a == 0.0)

const FACTORIAL_MAX = 170

function kf_factorial(n::Float64)
    k = isfinite(n) ? floor(n + 0.5) : n
    k >= 0 || return NaN
    k > FACTORIAL_MAX && return Inf
    r = 1.0
    for i in 2:Int(k)
        r *= i
    end
    return r
end

kf_binomial(n::Float64, k::Float64) = kf_factorial(n) / (kf_factorial(k) * kf_factorial(n - k))

function kf_ramp_down(x::Float64, s::Float64, e::Float64)
    lo = kf_min(s, e)
    hi = kf_max(s, e)
    !(x > lo) && return 1.0
    x >= hi && return 0.0
    return (hi - x) / (hi - lo)
end
kf_ramp_up(x::Float64, s::Float64, e::Float64) = 1.0 - kf_ramp_down(x, s, e)

"""`smoothDown`; `one_s`: the steepness is one number for every element (numpy's short cut applies)."""
function kf_smooth_down(x::Float64, X::Float64, s::Float64, one_s::Bool=true)
    !(x > 0) && return 1.0
    !(X > 0) && return 0.0
    r = one_s ? np_pow(x / X, 2 * s) : cpow(x / X, 2 * s)
    return isfinite(r) ? 1.0 / (1.0 + r) : 0.0
end
kf_smooth_up(x::Float64, X::Float64, s::Float64, one_s::Bool=true) = 1.0 - kf_smooth_down(x, X, s, one_s)

kf_bq2mole(bq::Float64, half_life_years::Float64) = (bq * half_life_years * SECONDS_PER_YEAR) / (LN2 * AVOGADRO)
kf_mole2bq(mole::Float64, half_life_years::Float64) = (LN2 * mole * AVOGADRO) / (half_life_years * SECONDS_PER_YEAR)

# --- erf and erfc, exactly as the application computes them --------------------------

const _ERFC_COF = (
    -1.3026537197817094, 6.4196979235649026e-1, 1.9476473204185836e-2,
    -9.561514786808631e-3, -9.46595344482036e-4, 3.66839497852761e-4,
    4.2523324806907e-5, -2.0278578112534e-5, -1.624290004647e-6,
    1.303655835580e-6, 1.5626441722e-8, -8.5238095915e-8,
    6.529054439e-9, 5.059343495e-9, -9.91364156e-10,
    -2.27365122e-10, 9.6467911e-11, 2.394038e-12,
    -6.886027e-12, 8.94487e-13, 3.13092e-13,
    -1.12708e-13, 3.81e-16, 7.106e-15,
)
const ERF_NEAR = 0.46875
const _ERF_A = (3.16112374387056560e0, 1.13864154151050156e2, 3.77485237685302021e2,
                3.20937758913846947e3, 1.85777706184603153e-1)
const _ERF_B = (2.36012909523441209e1, 2.44024637934444173e2, 1.28261652607737228e3,
                2.84423683343917062e3)

"""erf for |x| <= ERF_NEAR: W. J. Cody's x P(x²)/Q(x²) (CALERF's first interval)."""
function _erf_near(x::Float64)
    y = abs(x)
    ysq = y > 1.11e-16 ? y * y : 0.0
    num = _ERF_A[5] * ysq
    den = ysq
    for i in 1:3
        num = (num + _ERF_A[i]) * ysq
        den = (den + _ERF_B[i]) * ysq
    end
    return x * (num + _ERF_A[4]) / (den + _ERF_B[4])
end

"""The complementary error function: 1 - erf near zero, Numerical Recipes' Chebyshev fit beyond."""
function kf_erfc(x::Float64)
    isnan(x) && return NaN
    abs(x) <= ERF_NEAR && return 1 - _erf_near(x)
    z = abs(x)
    t = 2 / (2 + z)
    ty = 4 * t - 2
    d = 0.0
    dd = 0.0
    for j in length(_ERFC_COF):-1:2
        tmp = d
        d = ty * d - dd + _ERFC_COF[j]
        dd = tmp
    end
    ans = t * cexp(-z * z + 0.5 * (_ERFC_COF[1] + ty * d) - dd)
    return x >= 0 ? ans : 2 - ans
end

"""The error function: Cody's near zero, 1 - erfc(|x|) with x's sign beyond."""
function kf_erf(x::Float64)
    abs(x) <= ERF_NEAR && return _erf_near(x)
    v = 1 - kf_erfc(abs(x))
    return x < 0 ? -v : v
end

# --- the functions of many arguments ------------------------------------------------

_cmp_numbers(a::Float64, b::Float64) = (v = a - b; v != v ? 0.0 : v)

"""`[...values].sort((a, b) => a - b)` as V8 does it, NaN included (see reduce.py)."""
function js_sort_numbers(values::AbstractVector{Float64})
    a = collect(Float64, values)
    n = length(a)
    n < 2 && return a
    if !any(isnan, a)
        return sort!(a)
    end
    if n >= 64
        return sort!(a; by=v -> isnan(v) ? (1, 0.0) : (0, v))
    end
    run = 2
    descending = _cmp_numbers(a[2], a[1]) < 0
    previous = a[2]
    for i in 3:n
        order = _cmp_numbers(a[i], previous)
        ((descending && order >= 0) || (!descending && order < 0)) && break
        previous = a[i]
        run += 1
    end
    descending && reverse!(a, 1, run)
    for start in run:n-1          # 0-based start, as V8's BinaryInsertionSort
        pivot = a[start+1]
        left, right = 0, start
        while left < right
            mid = left + ((right - left) >> 1)
            if _cmp_numbers(pivot, a[mid+1]) < 0
                right = mid
            else
                left = mid + 1
            end
        end
        for k in start:-1:left+1
            a[k+1] = a[k]
        end
        a[left+1] = pivot
    end
    return a
end

"""The percentile of a sample: sorted values at the midpoints (i - 0.5)/n, the
extremes pinned to 0 and 1, straight lines between."""
function kf_percentile(phi::Float64, xs::AbstractVector{Float64})
    n = length(xs)
    (n == 0 || !(phi >= 0) || !(phi <= 100)) && return NaN
    p = phi / 100
    s = js_sort_numbers(xs)
    if p == 0.5
        return n % 2 == 1 ? s[div(n + 1, 2)] : (s[div(n, 2)] + s[div(n, 2)+1]) / 2
    end
    xx = [s[1]; s; s[n]]
    pp = [0.0; [(i - 0.5) / n for i in 1:n]; 1.0]
    j = 1
    while j < n + 2 && p > pp[j+1]
        j += 1
    end
    j >= n + 2 && return xx[n+2]
    span = pp[j+1] - pp[j]
    span == 0 && return xx[j+1]
    return ((p - pp[j]) / span) * (xx[j+1] - xx[j]) + xx[j]
end

struct TransportRangeError <: Exception
    message::String
end
Base.showerror(io::IO, e::TransportRangeError) = print(io, e.message)

function kf_transport_point(args::AbstractVector{Float64})
    x = args[end]
    n = length(args) - 1
    isnan(x) && return NaN
    x < 0 && throw(TransportRangeError("transport operation: the position $(py_repr(x)) is lower than zero"))
    x > 1 && throw(TransportRangeError("transport operation: the position $(py_repr(x)) is higher than one"))
    return args[(x == 1 ? n - 1 : trunc(Int, x * n))+1]
end

function kf_transport_range(args::AbstractVector{Float64}, mean::Bool)
    n = length(args) - 2
    a, b = args[n+1], args[n+2]
    (isnan(a) || isnan(b)) && return NaN
    a > b && ((a, b) = (b, a))
    a < 0 && throw(TransportRangeError("transport operation: the range starts at $(py_repr(a)), which is lower than zero"))
    b > 1 && throw(TransportRangeError("transport operation: the range ends at $(py_repr(b)), which is higher than one"))
    total = 0.0
    if a == 0 && b == 1
        for e in 1:n
            total += args[e]
        end
        return mean ? total / n : total
    end
    f = trunc(Int, a * n) + 1
    t = trunc(Int, b * n)
    cells = 0.0
    if t > f
        for e in f:t-1
            total += args[e+1]
        end
        cells += t - f
    end
    dx = f - a * n
    cells += dx
    total += args[f] * dx
    if b < 1
        dy = b * n - t
        cells += dy
        total += args[t+1] * dy
    end
    return mean ? total / cells : total
end
