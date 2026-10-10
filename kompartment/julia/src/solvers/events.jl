# Where an event function crosses zero inside a step (engine/solvers/events.py).

"""The discrete events a solve stops at: `n` functions, `fun(out, t, y)`
writing their values, and the direction each counts (1 rising, -1 falling,
0 either)."""
struct EventFunctions
    n::Int
    fun::EventFunction
    direction::Vector{Int8}
end

EventFunctions(n::Integer, fun, direction::AbstractVector{<:Real}) =
    EventFunctions(Int(n), fun isa EventFunction ? fun : EventFunction(fun), Int8[Int8(sign(d)) for d in direction])

const _EV_EPS = 2.0^-52

"""`Math.sign`: NaN for NaN, the zero itself for a zero (so -0 and +0 stay
apart as values but compare equal)."""
@inline _ev_sign(v::Float64) = v != v ? NaN : (v != 0 ? (v > 0 ? 1.0 : -1.0) : v)

@inline function _ev_crosses(vl::Vector{Float64}, vr::Vector{Float64}, direction::Vector{Int8}, i::Int)::Bool
    @inbounds a, b = vl[i], vr[i]
    sa, sb = _ev_sign(a), _ev_sign(b)
    sa == sb && return false
    return Float64(@inbounds direction[i]) * (b - a) >= 0
end

function _ev_any_crossing(vl::Vector{Float64}, vr::Vector{Float64}, direction::Vector{Int8})::Bool
    for i in eachindex(vl)
        _ev_crosses(vl, vr, direction, i) && return true
    end
    return false
end

function _ev_crossing_tolerance(tl::Float64, tr::Float64)::Float64
    scale = _pymax(_pymax(abs(tl), abs(tr)), 1.0)
    return _pymin(abs(tr - tl), (64 * _EV_EPS) * scale)
end

function _ev_earliest_secant(vlo::Vector{Float64}, vhi::Vector{Float64}, direction::Vector{Int8})::Float64
    frac = 1.0
    for i in eachindex(vlo)
        _ev_crosses(vlo, vhi, direction, i) || continue
        a, b = vlo[i], vhi[i]
        f = a == b ? 0.5 : -a / (b - a)
        if !(0 < f < 1)
            f = 0.5
        end
        if f < frac
            frac = f
        end
    end
    return frac
end

"""The first crossing in (tl, tr]: `(t, values, which)` with `which` the
1-based events that cross there, or nothing. `values_at!(out, t)` writes the
event functions' values at `t` (read from the step's interpolant)."""
function _ev_first_crossing(values_at!::F, tl::Float64, vl::Vector{Float64}, tr::Float64, vr::Vector{Float64},
                            direction::Vector{Int8},
                            t_start::Float64) where {F}
    n = length(vl)
    tol = _ev_crossing_tolerance(tl, tr)
    tdir = tr != tl ? copysign(1.0, tr - tl) : 0.0
    lo = tl
    vlo = vl
    if tl == t_start
        resting = false
        for i in 1:n
            if vl[i] == 0 && vr[i] != 0
                resting = true
                break
            end
        end
        if resting
            lo = tl + (tdir * 0.5) * tol
            if tdir * (tr - lo) <= 0
                return nothing
            end
            vlo = zeros(n)
            values_at!(vlo, lo)
            for i in 1:n
                if vlo[i] == 0 && vl[i] == 0
                    vlo[i] = vr[i]
                end
            end
        end
    end
    _ev_any_crossing(vlo, vr, direction) || return nothing
    hi = tr
    vhi = vr
    kept = 0
    same_end = 0
    for _ in 1:80
        if !(abs(hi - lo) > tol)
            break
        end
        if same_end >= 2
            mid = 0.5 * (lo + hi)
        else
            mid = lo + _ev_earliest_secant(vlo, vhi, direction) * (hi - lo)
            inner = 0.5 * tol
            if tdir * (mid - lo) < inner
                mid = lo + tdir * inner
            end
            if tdir * (hi - mid) < inner
                mid = hi - tdir * inner
            end
            if !(tdir * (mid - lo) > 0 && tdir * (hi - mid) > 0)
                mid = 0.5 * (lo + hi)
            end
        end
        vmid = zeros(n)
        values_at!(vmid, mid)
        if _ev_any_crossing(vlo, vmid, direction)
            hi = mid
            vhi = vmid
            same_end = kept == 1 ? same_end + 1 : 1
            kept = 1
        else
            lo = mid
            vlo = vmid
            same_end = kept == -1 ? same_end + 1 : 1
            kept = -1
        end
    end
    which = Int[i for i in 1:n if _ev_crosses(vlo, vhi, direction, i)]
    return (hi, vhi, which)
end

"""Reads the event functions at the end of a step (into `vr`) and, if any
crossed, finds the first crossing inside it (`locate_crossing`).
`dense_at!(out, t)` writes the state at `t` inside the step; `ybuf` is
room for it."""
function _ev_locate_crossing(ev::EventFunctions, t::Float64, vl::Vector{Float64}, tnew::Float64,
                             ynew::Vector{Float64}, vr::Vector{Float64}, dense_at!::F, ybuf::Vector{Float64},
                             t_start::Float64) where {F}
    ev.fun(vr, tnew, ynew)
    _ev_any_crossing(vl, vr, ev.direction) || return nothing
    at! = (out, tq) -> begin
        dense_at!(ybuf, tq)
        ev.fun(out, tq, ybuf)
        nothing
    end
    return _ev_first_crossing(at!, t, vl, tnew, vr, ev.direction, t_start)
end
