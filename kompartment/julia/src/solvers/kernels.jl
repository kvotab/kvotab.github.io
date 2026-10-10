# The solvers' inner loops (engine/solvers/kernels.py).
#
# * The application's own dense LU (`formAndFactor`, `factorizeInPlace`,
#   `solve`): the same row-major elimination with partial pivoting, the same
#   pivot choice, one rounding per operation, so a dense factorisation is the
#   Python engine's to the last bit. It is held transposed -- `A[j, i]` is the
#   application's `lu[i, j]` -- so that the application's rows are Julia's
#   columns and every inner loop runs down contiguous memory.
# * The weighted norms and the checks for a constrained state at zero.

const _LU_OK = 0
const _LU_SINGULAR = 1
const _LU_NONFINITE = 2

"""Python's builtin `max(a, b)`: `b` only when `b > a` (NaN never wins
from the right)."""
@inline _pymax(a::Float64, b::Float64) = b > a ? b : a
"""Python's builtin `min(a, b)`."""
@inline _pymin(a::Float64, b::Float64) = b < a ? b : a

"""`factorizeInPlace` on the transposed matrix `A` (`A[j, i]` = lu[i, j]).
On failure `fail` holds the column (counted from zero) and |pivot|."""
function _app_factor!(A::Matrix{Float64}, piv::Vector{Int}, fail::Vector{Float64})::Int
    n = size(A, 1)
    @inbounds for i in 1:n
        piv[i] = i
    end
    @inbounds for k in 1:n
        p = k
        max_abs = abs(A[k, k])
        for i in k+1:n
            v = abs(A[k, i])
            if v > max_abs
                max_abs = v
                p = i
            end
        end
        if !(max_abs > 0) || !isfinite(max_abs)
            fail[1] = k - 1
            fail[2] = max_abs
            return max_abs != 0 ? _LU_NONFINITE : _LU_SINGULAR
        end
        if p != k
            for j in 1:n
                tmp = A[j, p]
                A[j, p] = A[j, k]
                A[j, k] = tmp
            end
            t = piv[p]
            piv[p] = piv[k]
            piv[k] = t
        end
        pivot = A[k, k]
        for i in k+1:n
            f = A[k, i] / pivot
            f == 0 && continue
            A[k, i] = f
            for j in k+1:n
                A[j, i] -= f * A[j, k]
            end
        end
    end
    return _LU_OK
end

"""Mass - a*J from a pattern's values, factorised (`_form_factor_pattern`).
A row `held` marks (non-zero) is a row of the identity."""
function _app_form_factor_pattern!(a::Float64, colptr::Vector{Int}, rowval::Vector{Int}, values::Vector{Float64},
                                   held::Vector{UInt8}, mass::Vector{Float64}, A::Matrix{Float64},
                                   piv::Vector{Int}, fail::Vector{Float64})::Int
    n = size(A, 1)
    fill!(A, 0.0)
    bad = -1
    bad_value = 0.0
    @inbounds for j in 1:n
        for p in colptr[j]:colptr[j+1]-1
            i = rowval[p]
            held[i] != 0 && continue
            v = -a * values[p]
            if bad < 0 && !isfinite(v)
                bad = j - 1
                bad_value = v
            end
            A[j, i] = v
        end
    end
    if bad >= 0
        fail[1] = bad
        fail[2] = bad_value
        return -_LU_NONFINITE
    end
    @inbounds for i in 1:n
        A[i, i] += mass[i]
    end
    return _app_factor!(A, piv, fail)
end

"""Mass - a*J from a dense Jacobian held by columns (`J[i + (j-1)*n]`),
factorised (`_form_factor_dense`)."""
function _app_form_factor_dense!(a::Float64, J::Vector{Float64}, held::Vector{UInt8}, mass::Vector{Float64},
                                 A::Matrix{Float64}, piv::Vector{Int}, fail::Vector{Float64})::Int
    n = size(A, 1)
    bad = -1
    bad_value = 0.0
    @inbounds for j in 1:n
        off = (j - 1) * n
        for i in 1:n
            v = held[i] != 0 ? 0.0 : -a * J[off+i]
            if bad < 0 && !isfinite(v)
                bad = j - 1
                bad_value = v
            end
            A[j, i] = v
        end
    end
    if bad >= 0
        fail[1] = bad
        fail[2] = bad_value
        return -_LU_NONFINITE
    end
    @inbounds for i in 1:n
        A[i, i] += mass[i]
    end
    return _app_factor!(A, piv, fail)
end

"""The application's `solve` with the transposed factors: `x = W \\ b`
(`x` and `b` distinct).

Every row's sum is taken as the application takes it -- one term after
another, the columns in order -- but the forward substitution runs four
rows' sums side by side: their terms over the columns already solved for
are independent, and each row then takes the block's own columns, still in
order. The backward substitution's rows each start from the row just
solved, and stay one after another."""
function _app_solve!(x::Vector{Float64}, A::Matrix{Float64}, piv::Vector{Int}, b::Vector{Float64})
    n = size(A, 1)
    @inbounds for i in 1:n
        x[i] = b[piv[i]]
    end
    i = 2
    @inbounds while i + 3 <= n
        s0 = x[i]
        s1 = x[i+1]
        s2 = x[i+2]
        s3 = x[i+3]
        for j in 1:i-1
            xj = x[j]
            s0 -= A[j, i] * xj
            s1 -= A[j, i+1] * xj
            s2 -= A[j, i+2] * xj
            s3 -= A[j, i+3] * xj
        end
        x[i] = s0
        s1 -= A[i, i+1] * s0
        x[i+1] = s1
        s2 -= A[i, i+2] * s0
        s2 -= A[i+1, i+2] * s1
        x[i+2] = s2
        s3 -= A[i, i+3] * s0
        s3 -= A[i+1, i+3] * s1
        s3 -= A[i+2, i+3] * s2
        x[i+3] = s3
        i += 4
    end
    @inbounds while i <= n
        s = x[i]
        for j in 1:i-1
            s -= A[j, i] * x[j]
        end
        x[i] = s
        i += 1
    end
    @inbounds for i in n:-1:1
        s = x[i]
        for j in i+1:n
            s -= A[j, i] * x[j]
        end
        x[i] = s / A[i, i]
    end
    return x
end

"""The largest |v| / max(|ya|, |yb|, threshold) and where (`_weighted`):
NaN and the first index where it is not a number."""
function _weighted_norm(v::Vector{Float64}, ya::Vector{Float64}, yb::Vector{Float64},
                        threshold::Vector{Float64})::Tuple{Float64,Int}
    worst = 0.0
    at = 1
    @inbounds for i in eachindex(v)
        s = _pymax(_pymax(abs(ya[i]), abs(yb[i])), threshold[i])
        e = abs(v[i]) / s
        if !(e >= 0) || !isfinite(yb[i])
            return (NaN, i)
        end
        if i == 1 || e > worst
            worst = e
            at = i
        end
    end
    return worst > 0 ? (worst, at) : (0.0, 1)
end

"""Whether every `y[idx]` is above zero (NaN is not)."""
@inline function _all_above_zero(y::Vector{Float64}, idx::Vector{Int})::Bool
    @inbounds for i in idx
        if !(y[i] > 0)
            return false
        end
    end
    return true
end

"""Whether any `y[idx]` is below zero."""
@inline function _any_below_zero(y::Vector{Float64}, idx::Vector{Int})::Bool
    @inbounds for i in idx
        if y[i] < 0
            return true
        end
    end
    return false
end

"""max(0, max |v| * inv), NaN when any product is not a number (`_scaled_max`).

Every product is +0 or above, or NaN (flagged apart), so their largest is the
same whatever order they are compared in: eight running maxima side by side
give the one sequential loop's answer, bit for bit, four times faster."""
function _scaled_max(v::Vector{Float64}, inv::Vector{Float64})::Float64
    n = length(v)
    m1 = m2 = m3 = m4 = m5 = m6 = m7 = m8 = 0.0
    bad = false
    i = 1
    @inbounds while i + 7 <= n
        a1 = abs(v[i]) * inv[i]
        a2 = abs(v[i+1]) * inv[i+1]
        a3 = abs(v[i+2]) * inv[i+2]
        a4 = abs(v[i+3]) * inv[i+3]
        a5 = abs(v[i+4]) * inv[i+4]
        a6 = abs(v[i+5]) * inv[i+5]
        a7 = abs(v[i+6]) * inv[i+6]
        a8 = abs(v[i+7]) * inv[i+7]
        bad |= (a1 != a1) | (a2 != a2) | (a3 != a3) | (a4 != a4) | (a5 != a5) | (a6 != a6) | (a7 != a7) | (a8 != a8)
        m1 = ifelse(a1 > m1, a1, m1)
        m2 = ifelse(a2 > m2, a2, m2)
        m3 = ifelse(a3 > m3, a3, m3)
        m4 = ifelse(a4 > m4, a4, m4)
        m5 = ifelse(a5 > m5, a5, m5)
        m6 = ifelse(a6 > m6, a6, m6)
        m7 = ifelse(a7 > m7, a7, m7)
        m8 = ifelse(a8 > m8, a8, m8)
        i += 8
    end
    @inbounds while i <= n
        a = abs(v[i]) * inv[i]
        bad |= a != a
        m1 = ifelse(a > m1, a, m1)
        i += 1
    end
    bad && return NaN
    m1 = ifelse(m2 > m1, m2, m1)
    m1 = ifelse(m3 > m1, m3, m1)
    m1 = ifelse(m4 > m1, m4, m1)
    m1 = ifelse(m5 > m1, m5, m1)
    m1 = ifelse(m6 > m1, m6, m1)
    m1 = ifelse(m7 > m1, m7, m1)
    m1 = ifelse(m8 > m1, m8, m1)
    return m1
end

"""`float(np.cumsum(v * v)[-1])`: the squares summed strictly in order."""
function _seq_sum_squares(v::Vector{Float64})::Float64
    s = 0.0
    @inbounds for i in eachindex(v)
        s += v[i] * v[i]
    end
    return s
end
