# How well the values a calibration found are known: the Python package's
# `kompartment/stats/precision.py` (the application's `src/domain/precision.js`).
#
# Least squares answers *how sure is it* from two things it already has at the
# answer: how much misfit is left, and how the endpoints move when each value
# moves. Near the answer the residuals are close to straight in the values,
# `r(u) ~ r0 + J (u - u*)`, and then
#
#     cov(u) = s^2 (J^T J)^-1,   s^2 = |r0|^2 / (m - n)
#
# for `m` residuals and `n` values found. Each value's standard error is the
# root of its diagonal entry, its range about 95 % that times Student's t on
# `m - n` degrees of freedom, and the off-diagonal entries, scaled to the
# diagonal, are the correlations. A value searched in its logarithm has its
# standard error in the logarithm, so its range is a factor either way.
#
# With no more targets than values there is no misfit left to judge by: the
# correlations still follow from `J`, the standard errors do not. A value on a
# bound is held and given no range; one no endpoint moves has "no effect"; two
# the endpoints cannot tell apart are named as that.
#
# Every exp, log, sin and tan here is the C library's (`cexp`, `clog`,
# `clog1p`, `csin`, `ctan`), as Python's `math` calls it, and a square root
# below nought is NaN as Python's port makes it, so each value is Python's to
# the last bit.

const _PR_LANCZOS = (0.99999999999980993, 676.5203681218851, -1259.1392167224028,
                     771.32342877765313, -176.61502916214059, 12.507343278686905,
                     -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7)
const _PR_PI = Float64(pi)

"""`sqrt`, NaN below nought (Julia's own throws)."""
_pr_sqrt(x::Float64) = x >= 0 ? sqrt(x) : NaN

"""
    ln_gamma(x) -> Float64

The logarithm of the gamma function, by Lanczos's approximation (g = 7, n = 9).
"""
function ln_gamma(x::Float64)
    x < 0.5 && return clog(_PR_PI / abs(csin(_PR_PI * x))) - ln_gamma(1 - x)
    z = x - 1
    a = _PR_LANCZOS[1]
    t = z + 7.5
    for i in 1:8
        a += _PR_LANCZOS[i+1] / (z + i)
    end
    return 0.5 * clog(2 * _PR_PI) + (z + 0.5) * clog(t) - t + clog(a)
end

"""The continued fraction of the incomplete beta function, by Lentz's method."""
function _pr_beta_fraction(a::Float64, b::Float64, x::Float64)
    tiny = 1e-300
    qab = a + b
    qap = a + 1
    qam = a - 1
    c = 1.0
    d = 1 - (qab * x) / qap
    abs(d) < tiny && (d = tiny)
    d = 1 / d
    h = d
    for m in 1:500
        m2 = 2 * m
        aa = (m * (b - m) * x) / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        abs(d) < tiny && (d = tiny)
        c = 1 + aa / c
        abs(c) < tiny && (c = tiny)
        d = 1 / d
        h *= d * c
        aa = (-(a + m) * (qab + m) * x) / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        abs(d) < tiny && (d = tiny)
        c = 1 + aa / c
        abs(c) < tiny && (c = tiny)
        d = 1 / d
        step = d * c
        h *= step
        abs(step - 1) < 1e-15 && break
    end
    return h
end

"""
    incomplete_beta(x, a, b) -> Float64

The regularised incomplete beta function, `I_x(a, b)`.
"""
function incomplete_beta(x::Float64, a::Float64, b::Float64)
    x > 0 || return 0.0
    x < 1 || return 1.0
    front = cexp(ln_gamma(a + b) - ln_gamma(a) - ln_gamma(b) + a * clog(x) + b * clog1p(-x))
    x < (a + 1) / (a + b + 2) && return (front * _pr_beta_fraction(a, b, x)) / a
    return 1 - (front * _pr_beta_fraction(b, a, 1 - x)) / b
end

"""
    student_cdf(t, dof) -> Float64

Student's t distribution with `dof` degrees of freedom: P(T <= t).
"""
function student_cdf(t::Float64, dof::Real)
    tail = 0.5 * incomplete_beta(dof / (dof + t * t), dof / 2, 0.5)
    return t >= 0 ? 1 - tail : tail
end

"""
    student_quantile(p, dof) -> Float64

Student's t quantile: the t below which a share `p` lies. Closed forms for one
and two degrees of freedom, the normal's beyond ten million, and between them
the distribution function inverted by bisection to the last bit. NaN outside
(0, 1) or for no degrees of freedom.
"""
function student_quantile(p::Float64, dof::Real)
    ((p > 0 && p < 1) && dof > 0) || return NaN
    p == 0.5 && return 0.0
    dof == 1 && return ctan(_PR_PI * (p - 0.5))
    dof == 2 && return (2 * p - 1) / sqrt(2 * p * (1 - p))
    dof > 1e7 && return normal_quantile(p)
    q = p > 0.5 ? p : 1 - p
    lo = 0.0
    hi = 2 * normal_quantile(q)
    hi > 2 || (hi = 2.0)   # Math.max(2, ...)
    while student_cdf(hi, dof) < q
        hi *= 2
    end
    i = 0
    while i < 300 && hi - lo > 1e-15 * hi
        mid = 0.5 * (lo + hi)
        if student_cdf(mid, dof) < q
            lo = mid
        else
            hi = mid
        end
        i += 1
    end
    t = 0.5 * (lo + hi)
    return p > 0.5 ? t : -t
end

"""
Inverts a symmetric positive matrix scaled to unit diagonal, by Gauss-Jordan
with partial pivoting; `nothing` when a pivot falls under `tiny`, which on a
matrix of correlations means two columns of J nearly in line.
"""
function _pr_invert_scaled(S::Vector{Vector{Float64}}, tiny::Float64=1e-12)
    n = length(S)
    M = Vector{Float64}[]
    for i in 1:n
        r = zeros(2n)
        r[1:n] .= S[i]
        r[n+i] = 1.0
        push!(M, r)
    end
    for c in 1:n
        p = c
        for r in c+1:n
            abs(M[r][c]) > abs(M[p][c]) && (p = r)
        end
        abs(M[p][c]) > tiny || return nothing
        M[c], M[p] = M[p], M[c]
        piv = M[c][c]
        for k in 1:2n
            M[c][k] /= piv
        end
        for r in 1:n
            r == c && continue
            f = M[r][c]
            f == 0 && continue
            for k in 1:2n
                M[r][k] -= f * M[c][k]
            end
        end
    end
    return Vector{Float64}[M[i][n+1:2n] for i in 1:n]
end

"""
    precision_of(; residuals, columns, keys, spaces, values, pinned=nothing, failed=nothing, level=0.95) -> JDict

The precision of a least-squares answer, from its residuals and their
derivatives there (`precisionOf`). `residuals` are the search's own at the
answer; `columns[k]` is dr/du for value `k` in the space the search moved in,
`nothing` for one held (on a bound) or one the model would not run around;
`spaces` `"linear"` or `"log"`; `values` the values found, as the model holds
them; `pinned` `"lower"`, `"upper"` or `nothing` per value; `failed` why a value
has no column, where the model did not run around it; `level` the share the
ranges hold.

Returns `{"targets", "free", "dof", "spread", "t", "level", "reason", "values",
"correlations"}`: per value `{"key", "se", "low", "high", "factor", "held"}` --
`se` in the value's own units (for a logarithmic one, the value times its
standard error in the logarithm), `factor` the range's either way for a
logarithmic one, `held` why it has none (`"lower"`, `"upper"`, `"no effect"`,
or the reason it could not be differenced). `reason` says why there are no
ranges: `"nothing free"`, `"cannot tell apart"` or `"no spare targets"`.
"""
function precision_of(; residuals, columns, keys, spaces, values, pinned=nothing, failed=nothing, level::Float64=0.95)
    pin = pinned === nothing ? Any[] : pinned
    fail = failed === nothing ? Any[] : failed
    m = length(residuals)
    n = length(keys)
    held = Union{Nothing,String}[]
    for k in 1:n
        h = k <= length(pin) ? pin[k] : nothing
        h === nothing && (h = k <= length(fail) ? fail[k] : nothing)
        h === nothing && (h = columns[k] !== nothing ? nothing : "held")
        push!(held, h)
    end
    # A value no endpoint moves: its column is nothing, so the matrix would be
    # singular for a reason the reader can be told plainly.
    for k in 1:n
        col = columns[k]
        (held[k] !== nothing || col === nothing) && continue
        any(col[i] != 0 for i in 1:m) || (held[k] = "no effect")
    end
    free = Int[k for k in 1:n if held[k] === nothing]
    nf = length(free)
    ssr = 0.0
    for i in 1:m
        ssr += residuals[i] * residuals[i]
    end
    dof = m - nf
    out = JDict(
        "targets" => m,
        "free" => nf,
        "dof" => dof,
        "spread" => dof > 0 ? _pr_sqrt(ssr / dof) : nothing,
        "t" => dof > 0 ? student_quantile(0.5 + level / 2, dof) : nothing,
        "level" => level,
        "reason" => nothing,
        "values" => JDict[JDict("key" => keys[k], "se" => nothing, "low" => nothing, "high" => nothing,
                                "factor" => nothing, "held" => held[k]) for k in 1:n],
        "correlations" => nothing,
    )
    if nf == 0
        out["reason"] = "nothing free"
        return out
    end

    # J^T J over the values left free, scaled to unit diagonal so that the
    # pivots say how nearly in line two columns are, whatever their units.
    A = Vector{Float64}[]
    for a in free
        row = Float64[]
        for b in free
            s = 0.0
            for i in 1:m
                s += columns[a][i] * columns[b][i]
            end
            push!(row, s)
        end
        push!(A, row)
    end
    d = Float64[_pr_sqrt(A[i][i]) for i in 1:nf]
    S = Vector{Float64}[Float64[A[i][j] / (d[i] * d[j]) for j in 1:nf] for i in 1:nf]
    Sinv = _pr_invert_scaled(S)
    if Sinv === nothing
        out["reason"] = "cannot tell apart"
        return out
    end
    # The inverse of a symmetric matrix, symmetric to the last bit: the two
    # halves Gauss-Jordan gives differ in it, and a correlation is one number.
    matrix = Vector{Float64}[Float64[a == b ? 1.0 : (0.5 * (Sinv[a][b] + Sinv[b][a])) / _pr_sqrt(Sinv[a][a] * Sinv[b][b])
                                     for b in 1:nf] for a in 1:nf]
    out["correlations"] = JDict("keys" => Any[keys[k] for k in free], "matrix" => matrix)
    if !(dof > 0)
        out["reason"] = "no spare targets"
        return out
    end

    s2 = ssr / dof
    t = out["t"]::Float64
    for (a, k) in enumerate(free)
        # (J^T J)^-1 = D^-1 S^-1 D^-1, so the variance is s^2 S^-1[a][a] / d[a]^2.
        se_u = _pr_sqrt((s2 * Sinv[a][a]) / (d[a] * d[a]))
        v = Float64(values[k])
        row = out["values"][k]
        if spaces[k] == "log"
            factor = cexp(t * se_u)
            row["factor"] = factor
            row["low"] = v / factor
            row["high"] = v * factor
            row["se"] = abs(v) * se_u
        else
            row["se"] = se_u
            row["low"] = v - t * se_u
            row["high"] = v + t * se_u
        end
    end
    return out
end
