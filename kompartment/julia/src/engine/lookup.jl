# Lookup tables: a value that changes with time (src/domain/lookup.js).
#
# A table is a list of (x, y) points and a rule for reading between and
# beyond them: `linear` (straight lines, held flat at the ends),
# `extrapolate` (the end segments continued), `below`, `above`, `nearest`.
# `cyclic` wraps x into the table's own span first. The point is found by
# bisection, so the answer does not depend on the order a solver asks in; two
# points at the same x are a step, and the later one wins.

struct LookupError <: Exception
    message::String
end
Base.showerror(io::IO, e::LookupError) = print(io, e.message)

_lk_number(v::Nothing) = 0.0
_lk_number(v::Bool) = v ? 1.0 : 0.0
_lk_number(v::Real) = Float64(v)
function _lk_number(v::AbstractString)
    f = py_float(v)
    !isnan(f) && return f
    isempty(strip(v)) && return 0.0
    return NaN
end
_lk_number(v) = NaN

"""`[[x, y], ...]` or `[xs, ys]` as two vectors sorted by x (a stable sort)."""
function to_table(points)
    flat(a) = a isa AbstractVector && all(v -> (v isa Real && !(v isa Bool)) || v isa AbstractString, a)
    if points isa AbstractVector && length(points) == 2 && flat(points[1]) && flat(points[2]) &&
       length(points[1]) == length(points[2]) && length(points[1]) != 2
        xs, ys = points[1], points[2]
    else
        pairs = something(points, Any[])
        xs = Any[p isa AbstractVector ? p[1] : jget(p, "x") for p in pairs]
        ys = Any[p isa AbstractVector ? (length(p) > 1 ? p[2] : nothing) : jget(p, "y") for p in pairs]
    end
    nx = Float64[v === nothing ? NaN : _lk_number(v) for v in xs]
    order = sortperm(collect(1:length(nx)); by=i -> isnan(nx[i]) ? (1, 0.0) : (0, nx[i]))
    return nx[order], Float64[ys[i] === nothing ? NaN : _lk_number(ys[i]) for i in order]
end

"""A table ready to be read (`makeTable`)."""
mutable struct LookupTable
    x::Vector{Float64}
    y::Vector{Float64}
    n::Int
    first::Float64
    last::Float64
    span::Float64
    interpolation::Symbol     # :linear :extrapolate :below :above :nearest
    cyclic::Bool
    wraps::Bool
end

function LookupTable(points, interpolation::AbstractString="linear", cyclic::Bool=false)
    interpolation in INTERPOLATIONS ||
        throw(LookupError("'$interpolation' is not an interpolation rule ($(join(INTERPOLATIONS, ", ")))"))
    x, y = to_table(points)
    n = length(x)
    n == 0 && throw(LookupError("A lookup table needs at least one point"))
    any(v -> !isfinite(v), x) && throw(LookupError("A lookup point has no x value"))
    span = x[end] - x[1]
    return LookupTable(x, y, n, x[1], x[end], span, Symbol(interpolation), cyclic, cyclic && span > 0)
end

Base.length(t::LookupTable) = t.n

"""Rewrites one point's value (a distributed point, drawn again); `row` from 0."""
set_y!(t::LookupTable, row::Int, value::Float64) = (t.y[row+1] = value)

@inline function _wrap(t::LookupTable, v::Float64)
    a = rem(v - t.first, t.span)          # C's fmod, as Python's math.fmod
    return a >= 0 ? a + t.first : a + t.span + t.first
end

"""The 0-based segment a point falls in: bisect_right(x, v) - 1, clamped to [0, n-2]."""
@inline function _segment(t::LookupTable, v::Float64)
    v != v && return 0
    lo, hi = 0, t.n
    x = t.x
    @inbounds while lo < hi
        mid = (lo + hi) >>> 1
        if v < x[mid+1]
            hi = mid
        else
            lo = mid + 1
        end
    end
    return min(max(lo - 1, 0), t.n - 2)
end

@inline function _between(t::LookupTable, v::Float64, i::Int)
    x, y = t.x, t.y
    @inbounds begin
        dx = x[i+2] - x[i+1]
        dx == 0 && return y[i+2]
        return y[i+1] + ((v - x[i+1]) / dx) * (y[i+2] - y[i+1])
    end
end

"""The table read at `raw`."""
function table_at(t::LookupTable, raw::Float64)
    v = t.wraps ? _wrap(t, raw) : raw
    n = t.n
    y = t.y
    n == 1 && return y[1]
    interp = t.interpolation
    if v <= t.first
        return interp === :extrapolate ? _between(t, v, 0) : y[1]
    end
    if v >= t.last
        return interp === :extrapolate ? _between(t, v, n - 2) : y[n]
    end
    i = _segment(t, v)
    @inbounds begin
        interp === :below && return y[i+1]
        interp === :above && return t.x[i+1] == v ? y[i+1] : y[i+2]
        if interp === :nearest
            dx = t.x[i+2] - t.x[i+1]
            return (dx == 0 || (v - t.x[i+1]) / dx < 0.5) ? y[i+1] : y[i+2]
        end
    end
    return _between(t, v, i)
end

"""dy/dx at `raw` (zero for the step rules and at a step)."""
function table_slope(t::LookupTable, raw::Float64)
    n = t.n
    (n == 1 || t.interpolation in (:below, :above, :nearest)) && return 0.0
    v = t.wraps ? _wrap(t, raw) : raw
    x, y = t.x, t.y
    if v < t.first || v > t.last
        t.interpolation === :extrapolate || return 0.0
        i = v < t.first ? 0 : n - 2
    else
        i = _segment(t, v)
    end
    dx = x[i+2] - x[i+1]
    return dx == 0 ? 0.0 : (y[i+2] - y[i+1]) / dx
end
