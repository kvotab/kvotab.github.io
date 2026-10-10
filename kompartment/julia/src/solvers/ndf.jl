# The variable-order NDF/BDF integrator: Kompartment's default solver
# (engine/solvers/ndf.py, itself a port of src/ode/solvers/ndf.js).
#
# The numerical differentiation formulas of orders one to five (Shampine and
# Reichelt, "The MATLAB ODE Suite", 1997), with the backward differentiation
# formulas as the case of every kappa zero, in backward-difference form with
# a quasi-constant step; `non_negative` states integrated as the projected
# system, a Jacobian that declines a point differenced there instead, and a
# run that accepts steps but covers none of the interval stopped, saying so.
#
# Every per-state operation is the Python engine's, in its order; every work
# vector is made once per solve, so a step allocates nothing.

const _NDF_EPS = 2.0^-52
const _NDF_MAX_ORDER = 5
const _NDF_KAPPA = (-0.185, -1 / 9, -0.0823, -0.0415, 0.0)
const _NDF_GAMMA = (1.0, 3 / 2, 11 / 6, 25 / 12, 137 / 60)
const _NDF_NEWTON_MAX = 4
const _NDF_NEWTON_TOL = 0.3
const _NDF_RATE_LIMIT = 0.9
const _NDF_RATE_FLOOR = 0.02
const _NDF_CONVERGED_FLOOR = 1e-3
const _NDF_SAFETY = 0.8
const _NDF_SAFETY_LOWER = 0.75
const _NDF_SAFETY_HIGHER = 0.7
const _NDF_MAX_GROWTH = 10.0
const _NDF_NEWTON_CUT = 0.25
const _NDF_STALL_WINDOW_STEPS = 2000
const _NDF_STALL_SPAN_FRACTION = 1e-10
const _NDF_MAX_BELOW_TOLERANCE = 20
const _NDF_TRACE_STEPS = 12

"""What the solver is told about df/dy (Python's `jacobian` dict): its
pattern, the colouring to difference it with (nothing: `colour_columns`),
an `evaluate(vals, t, y)` that writes its values (the pattern's, in the
pattern's order; without a pattern the dense matrix by columns) or returns
false to have them differenced, and whether it is constant."""
struct JacobianSpec
    pattern::Union{Nothing,Pattern}
    groups::Union{Nothing,Vector{Vector{Int}}}
    evaluate::Union{Nothing,JacobianEvaluate}
    constant::Bool
end

JacobianSpec(; pattern=nothing, groups=nothing, evaluate=nothing, constant::Bool=false) =
    JacobianSpec(pattern, groups, evaluate === nothing || evaluate isa JacobianEvaluate ? evaluate :
                                  JacobianEvaluate(evaluate), constant)

"""What a solve produced: a row per output time reached (copies), where it
ended, where an event stopped it (`which`: 1-based events), and its
counts (the Python engine's stats keys)."""
struct Solution
    t::Vector{Float64}
    y::Vector{Vector{Float64}}
    end_t::Float64
    end_y::Vector{Float64}
    stopped::Union{Nothing,NamedTuple{(:t, :y, :which),Tuple{Float64,Vector{Float64},Vector{Int}}}}
    stats::Dict{String,Any}
end

# --- small pieces ------------------------------------------------------------------------

"""Python's `2.0 ** max(floor(log2(|x|)) - 52, -1074)`, with the C library's
log2 and pow as Python's are."""
@inline function _ndf_ulp(x::Float64)::Float64
    a = abs(x)
    !(a > 0) && return 5e-324
    e = floor(clog2(a)) - 52.0
    e = e > -1074.0 ? e : -1074.0
    return cpow(2.0, e)
end

@inline _ndf_step_floor(t::Float64) = 16 * _ndf_ulp(t)

function _ndf_floor_failure(t::Float64, nonfinite::Bool)
    hmin = _ndf_step_floor(t)
    if nonfinite
        return SolverError("nonfinite", "The state or its derivative became non-finite at t=$(_pyrepr(t)), and no " *
                                        "step size above the smallest allowed ($(_pyrepr(hmin))) gives a number.", t)
    end
    return SolverError("tolerance", "Failure at t=$(_pyrepr(t)): unable to meet the integration tolerances without " *
                                    "reducing the step size below the smallest value allowed ($(_pyrepr(hmin))).", t)
end

_ndf_steps_failure(max_steps::Float64, t::Float64) =
    SolverError("steps", "Exceeded $(trunc(Int, max_steps)) steps at t=$(_pyrepr(t)). Nothing this solver can do " *
                         "with the step size will finish this run.", t)

_ndf_stall_failure(t::Float64, window::Int, covered::Float64) =
    SolverError("stalled", "The solver stopped making progress at t=$(_pyrepr(t)): $window accepted steps advanced " *
                           "the clock by less than $(_pyrepr(covered)), and the step size is no longer growing.", t)

_ndf_error_nonfinite(t::Float64) =
    SolverError("nonfinite", "The error estimate is not a number at t=$(_pyrepr(t)): a tolerance or a state weight " *
                             "is NaN.", t)

_ndf_initial_nonfinite(t0::Float64, state::Int) =
    SolverError("nonfinite", "The state or its derivative is not a number at t=$(_pyrepr(t0)) (state $state).", t0)

function _ndf_basis_at!(out::Vector{Float64}, s::Float64, k::Int)
    out[1] = 1.0
    @inbounds for j in 1:k
        out[j+1] = out[j] * (((s + j) - 1) / j)
    end
    return out
end

function _ndf_choose(n::Int, r::Int)::Float64
    v = 1.0
    for i in 1:r
        v = (v * (n - r + i)) / i
    end
    return v
end

"""The regridding matrix (`regrid_matrix`): T[m+1, j+1] for 0 <= m <= j <= k."""
function _ndf_regrid_matrix!(T::Matrix{Float64}, vals::Matrix{Float64}, b::Vector{Float64}, k::Int,
                             s_end::Float64, ratio::Float64)
    for i in 0:k
        _ndf_basis_at!(b, s_end - i * ratio, k)
        for j in 0:k
            vals[i+1, j+1] = b[j+1]
        end
    end
    for m in 0:k
        for j in 0:k
            T[m+1, j+1] = 0.0
        end
        for j in m:k
            acc = 0.0
            for i in 0:m
                acc += ((i % 2 == 1 ? -1.0 : 1.0) * _ndf_choose(m, i)) * vals[i+1, j+1]
            end
            T[m+1, j+1] = acc
        end
    end
    return T
end

"""The norm every test is measured in (`Weighting`)."""
struct _NDFWeighting
    threshold::Vector{Float64}
    norm_control::Bool
    rms::Bool
    inv::Vector{Float64}
end

_NDFWeighting(neq::Int, threshold::Vector{Float64}, norm_control::Bool, rms::Bool) =
    _NDFWeighting(threshold, norm_control, (!norm_control) && rms, zeros(norm_control ? 1 : neq))

function _ndf_update!(w::_NDFWeighting, y::Vector{Float64}, ynew::Vector{Float64})
    if w.norm_control
        w.inv[1] = 1 / _pymax(_pymax(sqrt(_seq_sum_squares(y)), sqrt(_seq_sum_squares(ynew))), w.threshold[1])
        return nothing
    end
    inv, thr = w.inv, w.threshold
    @inbounds for i in eachindex(inv)
        inv[i] = 1 / max(max(abs(y[i]), abs(ynew[i])), thr[i])
    end
    return nothing
end

function _ndf_norm(w::_NDFWeighting, v::Vector{Float64})::Float64
    inv = w.inv
    if w.norm_control
        return sqrt(_seq_sum_squares(v)) * inv[1]
    end
    if w.rms
        n = length(v)
        n == 0 && return 0.0
        s = 0.0
        @inbounds for i in 1:n
            a = v[i] * inv[i]
            s += a * a
        end
        return sqrt(s / n)
    end
    return _scaled_max(v, inv)
end

# --- the solver's state --------------------------------------------------------------

mutable struct _NDFState
    f::RHSFunction
    neq::Int
    rtol::Float64
    atol::Vector{Float64}
    threshold::Vector{Float64}
    newton_threshold::Vector{Float64}
    error_weight::_NDFWeighting
    newton_weight::_NDFWeighting
    separate_newton::Bool
    mass::Union{Nothing,Vector{Float64}}
    algebraic::Vector{Int}
    leading::NTuple{5,Float64}
    error_const::NTuple{5,Float64}
    max_order::Int
    direction::Float64
    # the projected system
    constrained::Vector{Int}
    projected::Bool
    held_rows::Vector{UInt8}
    push::Vector{Float64}
    any_held::Bool
    held_now::Vector{UInt8}
    held_in_w::Vector{UInt8}
    # the Jacobian and the matrix
    pattern::Union{Nothing,Pattern}
    groups::Vector{Vector{Int}}
    evaluate::Union{Nothing,JacobianEvaluate}
    constant::Bool
    J::Vector{Float64}
    fresh::Bool
    dwork::DifferenceWork
    W::IterationMatrix
    # the difference table: D[j+1] is the j-th backward difference
    D::Vector{Vector{Float64}}
    tmp::Vector{Float64}
    T::Matrix{Float64}
    Tvals::Matrix{Float64}
    basis::Vector{Float64}
    # where the step is
    t::Float64
    tnew::Float64
    h::Float64
    k::Int
    hW::Float64
    kW::Int
    rate::Float64
    hTable::Float64
    consecutive::Int
    mask_reforms::Int
    # counts
    nfevals::Int
    nsteps::Int
    nfailed::Int
    npds::Int
    ndecomps::Int
    nsolves::Int
    nbelowtol::Int
    negative::Int
    # the last steps, for a failure's trace
    trace_t::Vector{Float64}
    trace_h::Vector{Float64}
    trace_k::Vector{Int}
    trace_err::Vector{Float64}
    trace_newton::Vector{Int}
    trace_failed::Vector{Int}
    trace_len::Int
    trace_pos::Int
    # work vectors
    fv::Vector{Float64}
    pred::Vector{Float64}
    hist::Vector{Float64}
    ynew::Vector{Float64}
    d::Vector{Float64}
    delta::Vector{Float64}
    work::Vector{Float64}
    dense::Vector{Float64}
end

@inline function _ndf_raw!(s::_NDFState, out::Vector{Float64}, t::Float64, y::Vector{Float64})
    s.nfevals += 1
    s.f(out, t, y)
    return out
end

"""The derivative of the projected system (`projectedDerivative`): a
constrained state at or below zero whose equation pushes it lower is held."""
function _ndf_rhs!(s::_NDFState, out::Vector{Float64}, t::Float64, y::Vector{Float64})
    s.projected || return _ndf_raw!(s, out, t, y)
    c = s.constrained
    if _all_above_zero(y, c)
        _ndf_raw!(s, out, t, y)
        if s.any_held
            @inbounds for i in c
                s.held_rows[i] = 0x00
            end
            s.any_held = false
        end
        return out
    end
    _ndf_raw!(s, out, t, y)
    push = s.push
    held_rows = s.held_rows
    anyh = false
    @inbounds for q in eachindex(c)
        i = c[q]
        hold = (y[i] <= 0) & (out[i] < 0)
        push[q] = max(push[q], hold ? -out[i] : 0.0)
        if hold
            out[i] = 0.0
            anyh = true
        end
        held_rows[i] = hold ? 0x01 : 0x00
    end
    s.any_held = anyh
    return out
end

function _ndf_stats(s::_NDFState)::Dict{String,Any}
    return Dict{String,Any}("nsteps" => s.nsteps, "nfailed" => s.nfailed, "npds" => s.npds,
                            "ndecomps" => s.ndecomps, "nsolves" => s.nsolves, "nbelowtol" => s.nbelowtol,
                            "negative" => s.negative, "nfevals" => s.nfevals)
end

function _ndf_trace(s::_NDFState)::Vector{Any}
    out = Any[]
    n = s.trace_len
    cap = length(s.trace_t)
    first = n < cap ? 1 : s.trace_pos
    for q in 0:n-1
        i = mod1(first + q, cap)
        push!(out, Dict{String,Any}("t" => s.trace_t[i], "h" => s.trace_h[i], "k" => s.trace_k[i],
                                    "err" => s.trace_err[i], "newton" => s.trace_newton[i],
                                    "failed" => s.trace_failed[i]))
    end
    return out
end

"""`fail(e)`: the failure with where the run was."""
function _ndf_fail(s::_NDFState, e::SolverError)::SolverError
    e.trace = _ndf_trace(s)
    e.last_t = s.t
    e.last_y = copy(s.D[1])
    e.stats = _ndf_stats(s)
    return e
end

# --- the difference table ----------------------------------------------------------------
#
# The operations on the table go over the states in tiles that stay in the
# first-level cache, and inside a tile one column at a time, so that every
# inner loop reads two or three arrays and vectorises -- each state's
# arithmetic the Python engine's, in its order. The columns come as a tuple
# whose length is a constant of the call.

const _NDF_TILE = 512

@inline _ndf_cols(D::Vector{Vector{Float64}}, ::Val{K}) where {K} = ntuple(j -> @inbounds(D[j]), Val(K))

"""The start of an attempt: the prediction and the history (`predict`,
`history`) into `pred` and `hist`, `ynew = pred`, `d = 0`, the weights
updated with (y, ynew) (`update`), and -- returned -- the norm of ynew in
the Newton weight."""
function _ndf_begin_attempt!(s::_NDFState, k::Int)::Float64
    D = s.D
    k == 1 && return _ndf_begin!(s, _ndf_cols(D, Val(2)))
    k == 2 && return _ndf_begin!(s, _ndf_cols(D, Val(3)))
    k == 3 && return _ndf_begin!(s, _ndf_cols(D, Val(4)))
    k == 4 && return _ndf_begin!(s, _ndf_cols(D, Val(5)))
    return _ndf_begin!(s, _ndf_cols(D, Val(6)))
end

"""`pred` and `hist` over lo:hi: c0 + c1 + ... + ck, and 0 + g1 c1 + ... + gk ck."""
@inline function _ndf_pred_hist!(pred::Vector{Float64}, hist::Vector{Float64}, cols::NTuple{K,Vector{Float64}},
                                 lo::Int, hi::Int) where {K}
    c0 = cols[1]
    @inbounds for i in lo:hi
        pred[i] = c0[i]
        hist[i] = 0.0
    end
    @inbounds for j in 2:K
        cj = cols[j]
        for i in lo:hi
            pred[i] += cj[i]
        end
    end
    @inbounds for j in 2:K
        cj = cols[j]
        g = _NDF_GAMMA[j-1]
        for i in lo:hi
            hist[i] += g * cj[i]
        end
    end
    return nothing
end

function _ndf_begin!(s::_NDFState, cols::NTuple{K,Vector{Float64}})::Float64 where {K}
    y = cols[1]
    pred, hist, ynew, d = s.pred, s.hist, s.ynew, s.d
    ew = s.error_weight
    nw = s.newton_weight
    n = s.neq
    sep = s.separate_newton
    einv, ethr = ew.inv, ew.threshold
    ninv, nthr = nw.inv, nw.threshold
    for lo in 1:_NDF_TILE:n
        hi = min(lo + _NDF_TILE - 1, n)
        _ndf_pred_hist!(pred, hist, cols, lo, hi)
        @inbounds for i in lo:hi
            ynew[i] = pred[i]
            d[i] = 0.0
        end
        ew.norm_control && continue
        @inbounds for i in lo:hi
            einv[i] = 1 / max(max(abs(y[i]), abs(pred[i])), ethr[i])
        end
        if sep
            @inbounds for i in lo:hi
                ninv[i] = 1 / max(max(abs(y[i]), abs(pred[i])), nthr[i])
            end
        end
    end
    if ew.norm_control
        ry, rp = sqrt(_seq_sum_squares(y)), sqrt(_seq_sum_squares(ynew))
        ew.inv[1] = 1 / _pymax(_pymax(ry, rp), ew.threshold[1])
        if sep
            nw.inv[1] = 1 / _pymax(_pymax(ry, rp), nw.threshold[1])
        end
        return rp * nw.inv[1]
    end
    return _ndf_norm(nw, ynew)
end

"""A Newton correction taken: `d += delta`, `ynew = pred + d`, in one pass,
and -- returned -- the norm of the new `d` in the error weight (`of_error`)."""
function _ndf_take_correction!(s::_NDFState)::Float64
    d, ynew, pred, delta = s.d, s.ynew, s.pred, s.delta
    ew = s.error_weight
    n = s.neq
    if ew.norm_control
        acc = 0.0
        @inbounds for i in 1:n
            di = d[i] + delta[i]
            d[i] = di
            ynew[i] = pred[i] + di
            acc += di * di
        end
        return sqrt(acc) * ew.inv[1]
    end
    inv = ew.inv
    if ew.rms
        acc = 0.0
        @inbounds for i in 1:n
            di = d[i] + delta[i]
            d[i] = di
            ynew[i] = pred[i] + di
            a = di * inv[i]
            acc += a * a
        end
        return n == 0 ? 0.0 : sqrt(acc / n)
    end
    @inbounds for i in 1:n
        di = d[i] + delta[i]
        d[i] = di
        ynew[i] = pred[i] + di
    end
    return _scaled_max(d, inv)
end

"""`advance(k, d)`: the step taken into the table."""
function _ndf_advance!(D::Vector{Vector{Float64}}, k::Int, d::Vector{Float64})
    n = length(d)
    a, b = D[k+3], D[k+2]
    for lo in 1:_NDF_TILE:n
        hi = min(lo + _NDF_TILE - 1, n)
        @inbounds for i in lo:hi
            a[i] = d[i] - b[i]
            b[i] = d[i]
        end
        for j in k:-1:0
            cj, cj1 = D[j+1], D[j+2]
            @inbounds for i in lo:hi
                cj[i] += cj1[i]
            end
        end
    end
    return nothing
end

"""`regrid(k, s_end, ratio)`: the table re-expressed on the grid of a new
step. Column m is made from the old columns m..k and then written, which
no later column reads."""
function _ndf_regrid!(s::_NDFState, k::Int, s_end::Float64, ratio::Float64)
    T = _ndf_regrid_matrix!(s.T, s.Tvals, s.basis, k, s_end, ratio)
    D = s.D
    tmp = s.tmp
    n = length(tmp)
    for lo in 1:_NDF_TILE:n
        hi = min(lo + _NDF_TILE - 1, n)
        for m in 0:k
            @inbounds for i in lo:hi
                tmp[i] = 0.0
            end
            for j in m:k
                w = T[m+1, j+1]
                w == 0 && continue
                c = D[j+1]
                @inbounds for i in lo:hi
                    tmp[i] += w * c[i]
                end
            end
            cm = D[m+1]
            @inbounds for i in lo:hi
                cm[i] = tmp[i]
            end
        end
    end
    return nothing
end

_ndf_rescale!(s::_NDFState, k::Int, ratio::Float64) = _ndf_regrid!(s, k, 0.0, ratio)

function _ndf_value_at!(out::Vector{Float64}, s::_NDFState, k::Int, sq::Float64, clamp::Bool)
    b = _ndf_basis_at!(s.basis, sq, k)
    D = s.D
    copyto!(out, D[1])
    for j in 1:k
        bj = b[j+1]
        c = D[j+1]
        @inbounds for i in eachindex(out)
            out[i] += bj * c[i]
        end
    end
    if clamp
        @inbounds for i in s.constrained
            v = out[i]
            out[i] = v < 0 ? 0.0 : v
        end
    end
    return out
end

function _ndf_forget!(D::Vector{Vector{Float64}}, i::Int)
    for j in 2:length(D)
        @inbounds D[j][i] = 0.0
    end
end

# --- the Jacobian and the matrix -----------------------------------------------------

"""df/dy differenced at the current point from `fy` (`differenced`)."""
function _ndf_differenced!(s::_NDFState, fy::Vector{Float64})
    y = s.D[1]
    t = s.t
    raw! = (out, tt, yy) -> _ndf_raw!(s, out, tt, yy)
    if s.pattern !== nothing
        difference_jacobian!(s.J, raw!, t, y, fy, s.pattern, s.groups, s.threshold, s.dwork)
        return nothing
    end
    n = s.neq
    dl = difference_increment!(s.dwork.dl, y, s.threshold)
    ytry = s.dwork.ytry
    fg = s.dwork.fg
    J = s.J
    copyto!(ytry, y)
    @inbounds for j in 1:n
        ytry[j] = y[j] + dl[j]
        _ndf_raw!(s, fg, t, ytry)
        off = (j - 1) * n
        for i in 1:n
            J[off+i] = (fg[i] - fy[i]) / dl[j]
        end
        ytry[j] = y[j]
    end
    return nothing
end

"""`evaluate_jacobian(fy)`: the supplied Jacobian, or differenced (from `fy`,
or from a fresh evaluation when there is none)."""
function _ndf_evaluate_jacobian!(s::_NDFState, fy::Union{Nothing,Vector{Float64}})
    s.npds += 1
    supplied = s.evaluate !== nothing && s.evaluate(s.J, s.t, s.D[1])
    if !supplied
        if fy === nothing
            fy = _ndf_raw!(s, s.work, s.t, s.D[1])
        end
        _ndf_differenced!(s, fy)
    end
    s.fresh = true
    return nothing
end

function _ndf_read_held!(s::_NDFState)
    s.projected && copyto!(s.held_now, s.held_rows)
    return nothing
end

function _ndf_held_moved(s::_NDFState)::Bool
    s.projected || return false
    @inbounds for i in s.constrained
        s.held_now[i] != s.held_in_w[i] && return true
    end
    return false
end

function _ndf_released_in_w!(s::_NDFState)::Bool
    s.projected || return false
    any = false
    @inbounds for i in s.constrained
        if s.held_in_w[i] == 1 && s.held_rows[i] == 0
            s.held_now[i] = 0x00
            any = true
        end
    end
    return any
end

"""`form_w()`: the iteration matrix for the current step and order."""
function _ndf_form_w!(s::_NDFState)
    any_held = false
    if s.projected
        copyto!(s.held_in_w, s.held_now)
        @inbounds for i in s.constrained
            if s.held_in_w[i] != 0
                any_held = true
                break
            end
        end
    end
    msg = _mat_form!(s.W, s.h / s.leading[s.k], s.J, any_held ? s.held_in_w : nothing)
    if msg !== nothing
        throw(_ndf_fail(s, SolverError("singular", "$msg (at t=$(_pyrepr(s.t)))", s.t)))
    end
    s.ndecomps += 1
    s.hW = s.h
    s.kW = s.k
    s.rate = -1.0
    return nothing
end

function _ndf_change_step!(s::_NDFState, factor::Float64)
    h_new = s.direction * _pymax(_ndf_step_floor(s.t), abs(s.h) * factor)
    if h_new != s.hTable
        _ndf_rescale!(s, s.k, h_new / s.hTable)
        s.hTable = h_new
    end
    s.h = h_new
    s.consecutive = 0
    s.mask_reforms = 0
    return nothing
end

"""`snap_onto_bound`: constrained states within their absolute tolerance
above zero that `should` picks are put on zero; false when there are none.
`by_held`: those held; otherwise those below zero in `s.ynew`."""
function _ndf_snap_onto_bound!(s::_NDFState, by_held::Bool)::Bool
    yv = s.D[1]
    atol = s.atol
    any = false
    @inbounds for i in s.constrained
        should = by_held ? s.held_rows[i] == 1 : s.ynew[i] < 0
        if (yv[i] > 0) & (yv[i] <= atol[i]) & should
            any = true
            break
        end
    end
    any || return false
    count = 0
    @inbounds for i in s.constrained
        should = by_held ? s.held_rows[i] == 1 : s.ynew[i] < 0
        if (yv[i] > 0) & (yv[i] <= atol[i]) & should
            yv[i] = 0.0
            _ndf_forget!(s.D, i)
            count += 1
        end
    end
    s.negative += count
    _ndf_rhs!(s, s.work, s.t, yv)
    _ndf_read_held!(s)
    _ndf_form_w!(s)
    return true
end

# --- the solver ----------------------------------------------------------------------

"""
    ndf(f, tspan, y0; rtol=1e-3, abstol=1e-6, non_negative=Int[], max_order=5, bdf=false,
        hmax=0.0, h0=0.0, max_steps=1e6, error_norm="max", norm_control=false, jacobian=nothing,
        matrix="auto", below_tol_run=nothing, stagnation_tol=0.0, min_newton=1, stall_window=2000,
        events=nothing, t_start=nothing, hints=nothing, on_accepted=nothing, on_output=nothing,
        on_step=nothing, auto_abstol=false, ends_only=false, mass=nothing) -> Solution

Integrates y' = f(t, y) over `tspan`, answering at every time in it (the
Python engine's `ndf`). `non_negative` holds 1-based state indices; `abstol`
is a number or a vector (with `auto_abstol`, a vector of the right length
is raised in place, as Python's is); `on_step(t, nsteps)` is asked every 16
steps and aborts the run by returning false.
"""
function ndf(f::RHSFunction, tspan::AbstractVector{<:Real}, y0::AbstractVector{<:Real};
             rtol::Real=1e-3, abstol::Union{Real,AbstractVector{<:Real}}=1e-6,
             non_negative::AbstractVector{<:Integer}=Int[], max_order::Real=_NDF_MAX_ORDER, bdf::Bool=false,
             hmax::Union{Nothing,Real}=0.0, h0::Union{Nothing,Real}=0.0, max_steps::Real=1e6,
             error_norm::Union{Nothing,AbstractString}="max", norm_control::Bool=false,
             jacobian::Union{Nothing,JacobianSpec}=nothing, matrix::Union{Nothing,AbstractString}="auto",
             below_tol_run::Union{Nothing,Real}=nothing, stagnation_tol::Real=0.0, min_newton::Integer=1,
             stall_window::Integer=_NDF_STALL_WINDOW_STEPS, events::Union{Nothing,EventFunctions}=nothing,
             t_start::Union{Nothing,Real}=nothing, hints::Union{Nothing,Dict{String,String}}=nothing,
             on_accepted::Union{Nothing,StepCallback}=nothing, on_output::Union{Nothing,StepCallback}=nothing,
             on_step::Union{Nothing,StepProgress}=nothing, auto_abstol::Bool=false, ends_only::Bool=false,
             mass::Union{Nothing,AbstractVector{<:Real}}=nothing)::Solution
    neq = length(y0)
    atol_in = if auto_abstol && abstol isa Vector{Float64} && length(abstol) == neq
        abstol                      # raised in place, as the caller's array is in Python
    elseif abstol isa Real
        fill(Float64(abstol), neq)
    else
        Vector{Float64}(abstol)
    end
    mass_v = mass !== nothing && length(mass) == neq ? Vector{Float64}(mass) : nothing
    mo = max(1, min(_NDF_MAX_ORDER, trunc(Int, floor(Float64(max_order) + 0.5))))
    floor_run = below_tol_run === nothing ? _NDF_MAX_BELOW_TOLERANCE : max(0, round(Int, below_tol_run))
    floor_newton_run = below_tol_run === nothing ? 0 : floor_run
    hm = hmax === nothing ? 0.0 : Float64(hmax)
    return _ndf_solve(f, Vector{Float64}(tspan), Vector{Float64}(y0), Float64(rtol), atol_in,
                      Vector{Int}(non_negative), mo, bdf, hm, h0 === nothing ? 0.0 : Float64(h0),
                      Float64(max_steps), error_norm === nothing ? "max" : String(error_norm), norm_control,
                      jacobian, matrix === nothing || isempty(matrix) ? "auto" : String(matrix), floor_run,
                      floor_newton_run, Float64(stagnation_tol), Int(min_newton), Int(stall_window), events,
                      t_start === nothing ? NaN : Float64(t_start), hints, on_accepted, on_output, on_step,
                      auto_abstol, ends_only, mass_v)
end

function _ndf_solve(f::RHSFunction, tspan::Vector{Float64}, y0::Vector{Float64}, rtol::Float64,
                    atol::Vector{Float64}, non_negative::Vector{Int}, max_order::Int, bdf::Bool, hmax_in::Float64,
                    h0::Float64, max_steps::Float64, error_norm::String, norm_control::Bool,
                    jacobian::Union{Nothing,JacobianSpec}, matrix::String, floor_run::Int, floor_newton_run::Int,
                    stagnation_tol::Float64, min_newton::Int, stall_window::Int,
                    events::Union{Nothing,EventFunctions}, t_start_in::Float64,
                    hints::Union{Nothing,Dict{String,String}}, on_accepted::Union{Nothing,StepCallback},
                    on_output::Union{Nothing,StepCallback}, on_step::Union{Nothing,StepProgress},
                    auto_abstol::Bool, ends_only::Bool, mass::Union{Nothing,Vector{Float64}})::Solution
    neq = length(y0)
    npts = length(tspan)
    t0 = tspan[1]
    t_end = tspan[end]
    direction = t_end != t0 ? copysign(1.0, t_end - t0) : 0.0
    span = abs(t_end - t0)
    if !(span > 0)
        throw(SolverError("span", "The start and end times are equal", t0))
    end
    leading = ntuple(k -> (1 - (bdf ? 0.0 : _NDF_KAPPA[k])) * _NDF_GAMMA[k], 5)
    error_const = ntuple(k -> (bdf ? 0.0 : _NDF_KAPPA[k]) * _NDF_GAMMA[k] + 1 / (k + 1), 5)
    threshold = Vector{Float64}(undef, neq)
    @inbounds for i in 1:neq
        threshold[i] = atol[i] / rtol
    end
    newton_threshold = auto_abstol ? copy(threshold) : threshold
    algebraic = mass !== nothing ? findall(==(0.0), mass) : Int[]
    rms = error_norm == "rms"
    error_weight = _NDFWeighting(neq, threshold, norm_control, rms)
    newton_weight = auto_abstol ? _NDFWeighting(neq, newton_threshold, norm_control, rms) : error_weight
    hmax = hmax_in > 0 ? _pymin(hmax_in, span) : 0.1 * span

    constrained = Int[i for i in non_negative if !(mass !== nothing && mass[i] == 0)]
    projected = !isempty(constrained)

    pattern = jacobian === nothing ? nothing : jacobian.pattern
    evaluate = jacobian === nothing ? nothing : jacobian.evaluate
    constant = jacobian === nothing ? false : jacobian.constant
    groups = jacobian === nothing ? nothing : jacobian.groups
    if pattern !== nothing && groups === nothing
        groups = colour_columns(pattern)
    end
    groups_v = groups === nothing ? Vector{Int}[] : groups
    Jlen = pattern !== nothing ? pattern_nnz(pattern) : neq * neq

    D = [zeros(neq) for _ in 1:max_order+3]
    copyto!(D[1], y0)
    s = _NDFState(f, neq, rtol, atol, threshold, newton_threshold, error_weight, newton_weight, auto_abstol, mass,
                  algebraic, leading, error_const, max_order, direction,
                  constrained, projected, zeros(UInt8, neq), zeros(length(constrained)), false,
                  zeros(UInt8, neq), zeros(UInt8, neq),
                  pattern, groups_v, evaluate, constant, zeros(Jlen), false,
                  DifferenceWork(pattern, groups, neq), IterationMatrix(0, nothing, Float64[]),
                  D, zeros(neq), zeros(max_order + 1, max_order + 1), zeros(max_order + 1, max_order + 1),
                  zeros(max_order + 1),
                  t0, t0, 0.0, 1, 0.0, 0, -1.0, 0.0, 0, 0,
                  0, 0, 0, 0, 0, 0, 0, 0,
                  zeros(_NDF_TRACE_STEPS), zeros(_NDF_TRACE_STEPS), zeros(Int, _NDF_TRACE_STEPS),
                  zeros(_NDF_TRACE_STEPS), zeros(Int, _NDF_TRACE_STEPS), zeros(Int, _NDF_TRACE_STEPS), 0, 1,
                  zeros(neq), zeros(neq), zeros(neq), zeros(neq), zeros(neq), zeros(neq), zeros(neq), zeros(neq))
    held = projected ? zeros(Int, neq) : nothing

    tout = Float64[]
    yout = Vector{Vector{Float64}}()
    record = (tv::Float64, yv::Vector{Float64}) -> begin
        if ends_only && length(tout) > 1
            tout[2] = tv
            yout[2] = copy(yv)
        else
            push!(tout, tv)
            push!(yout, copy(yv))
        end
        nothing
    end

    next_out = 2
    record(t0, D[1])

    f0 = _ndf_rhs!(s, zeros(neq), t0, D[1])
    @inbounds for i in 1:neq
        if !isfinite(D[1][i]) || !isfinite(f0[i])
            throw(_ndf_initial_nonfinite(t0, i - 1))
        end
    end
    vl = Float64[]
    vr = Float64[]
    if events !== nothing
        vl = zeros(events.n)
        events.fun(vl, t0, D[1])
        vr = zeros(events.n)
    end
    t_start = isnan(t_start_in) ? t0 : t_start_in
    stopped = nothing

    # --- the Jacobian and the matrix ---------------------------------------------------
    _ndf_evaluate_jacobian!(s, f0)
    try
        s.W = IterationMatrix(neq, pattern, s.J, matrix, mass, hints)
    catch e
        e isa MatrixError || rethrow()
        throw(SolverError("singular", e.msg, t0))
    end
    W = s.W
    try
        # --- the first step ------------------------------------------------------------
        yp = copy(f0)
        for i in algebraic
            yp[i] = 0.0
        end
        y = D[1]
        local step_size::Float64
        if h0 > 0
            step_size = h0
        else
            _ndf_update!(error_weight, y, y)
            dy = s.work
            copyto!(dy, y)
            for i in algebraic
                dy[i] = 0.0
            end
            d0 = _ndf_norm(error_weight, dy) / rtol
            d1 = _ndf_norm(error_weight, yp) / rtol
            guess = (d0 < 1e-5 || d1 < 1e-5) ? 1e-6 : 0.01 * (d0 / d1)
            guess = _pymin(guess, hmax)
            trial = s.ynew
            dg = direction * guess
            @inbounds for i in 1:neq
                trial[i] = y[i] + dg * yp[i]
            end
            f1 = _ndf_rhs!(s, s.fv, t0 + direction * guess, trial)
            df = s.work
            @inbounds for i in 1:neq
                df[i] = f1[i] - f0[i]
            end
            for i in algebraic
                df[i] = 0.0
            end
            d2 = _ndf_norm(error_weight, df) / rtol / guess
            if !isfinite(d2)
                d2 = 100 * d1
            end
            m = _pymax(d1, d2)
            h1 = m <= 1e-15 ? _pymax(1e-6, guess * 1e-3) : sqrt(0.01 / m)
            step_size = _pymin(100 * guess, h1)
        end
        step_size = _pymin(hmax, _pymax(_ndf_step_floor(t0), step_size))
        s.h = direction * step_size
        # table.start(y, h * yp)
        c1 = D[2]
        hh = s.h
        @inbounds for i in 1:neq
            c1[i] = hh * yp[i]
        end
        for j in 3:length(D)
            fill!(D[j], 0.0)
        end
        s.hTable = s.h
        _ndf_read_held!(s)
        _ndf_form_w!(s)

        below_run = 0
        stall_step = 0
        stall_t = t0
        stall_h = 0.0
        newton_its = 0
        step_fails = 0
        err = 0.0
        last = false
        pred, hist, ynew, d, delta = s.pred, s.hist, s.ynew, s.d, s.delta
        dense_at! = (out::Vector{Float64}, tq::Float64) -> begin
            _ndf_value_at!(out, s, s.k, (tq - s.tnew) / s.h, projected)
            nothing
        end

        while true
            hmin = _ndf_step_floor(s.t)
            step_size = _pymin(hmax, _pymax(hmin, abs(s.h)))
            last = false
            h_try = direction * step_size
            if 1.1 * step_size >= abs(t_end - s.t)
                h_try = t_end - s.t
                last = true
            end
            if h_try != s.hTable
                _ndf_rescale!(s, s.k, h_try / s.hTable)
                s.hTable = h_try
                s.consecutive = 0
            end
            s.h = h_try
            s.mask_reforms = 0
            y = D[1]
            if projected
                anyle = false
                @inbounds for i in constrained
                    if y[i] <= 0
                        anyle = true
                        break
                    end
                end
                anyle && _ndf_rhs!(s, s.work, s.t, y)
                _ndf_read_held!(s)
            end
            if s.h != s.hW || s.k != s.kW || _ndf_held_moved(s)
                _ndf_form_w!(s)
            end

            err = 0.0
            first_failure = true
            while true
                k = s.k
                h = s.h
                s.tnew = last ? t_end : s.t + h
                tnew = s.tnew
                ynorm = _ndf_begin_attempt!(s, k)
                projected && fill!(s.push, 0.0)
                roundoff = (100 * _NDF_EPS) * ynorm
                dnorm = 0.0
                outcome = 0          # 0 converged, 1 nonfinite, 2 slow
                prev = 0.0
                rho = s.rate
                scale = 1 / s.leading[k]
                newton_its = 0
                for it in 1:_NDF_NEWTON_MAX
                    fv = _ndf_rhs!(s, s.fv, tnew, ynew)
                    # the residual, solved for in place: delta
                    if mass !== nothing
                        @inbounds for i in 1:neq
                            delta[i] = (h * fv[i] - mass[i] * hist[i]) * scale - mass[i] * d[i]
                        end
                    else
                        @inbounds for i in 1:neq
                            delta[i] = (h * fv[i] - hist[i]) * scale - d[i]
                        end
                    end
                    _mat_solve_inplace!(W, delta)
                    s.nsolves += 1
                    newton_its = it
                    size = _ndf_norm(newton_weight, delta)
                    if !isfinite(size)
                        outcome = 1
                        break
                    end
                    dnorm = _ndf_take_correction!(s)
                    if size <= roundoff || size <= _NDF_CONVERGED_FLOOR * rtol
                        break
                    end
                    if it == 1
                        rate = s.rate
                        if min_newton <= 1 && rate >= 0 && (rate / (1 - rate)) * size <= _NDF_NEWTON_TOL * rtol
                            break
                        end
                        prev = size
                        continue
                    end
                    ratio = size / prev
                    if ratio >= _NDF_RATE_LIMIT
                        if stagnation_tol > 0 && s.fresh && size <= stagnation_tol * rtol
                            break
                        end
                        outcome = 2
                        break
                    end
                    rho = _pymax(ratio, _NDF_RATE_FLOOR)
                    remaining = (rho / (1 - rho)) * size
                    if remaining <= _NDF_NEWTON_TOL * rtol && it >= min_newton
                        break
                    end
                    if it == _NDF_NEWTON_MAX ||
                       remaining * cpow(rho, Float64(_NDF_NEWTON_MAX - it)) > _NDF_NEWTON_TOL * rtol
                        outcome = 2
                        break
                    end
                    prev = size
                end

                if outcome != 0
                    s.nfailed += 1
                    if projected && _ndf_snap_onto_bound!(s, true)
                        continue
                    end
                    if !s.fresh
                        _ndf_evaluate_jacobian!(s, nothing)
                        _ndf_read_held!(s)
                        _ndf_form_w!(s)
                        continue
                    end
                    if abs(h) <= hmin
                        if outcome == 1 || below_run >= floor_newton_run
                            throw(_ndf_fail(s, _ndf_floor_failure(s.t, outcome == 1)))
                        end
                        below_run += 1
                        s.nbelowtol += 1
                        err = rtol
                        break
                    end
                    _ndf_change_step!(s, _NDF_NEWTON_CUT)
                    last = false
                    _ndf_form_w!(s)
                    continue
                end
                if s.mask_reforms < 1 && _ndf_released_in_w!(s)
                    s.mask_reforms += 1
                    s.nfailed += 1
                    _ndf_form_w!(s)
                    continue
                end
                s.rate = rho

                err = s.error_const[k] * dnorm
                if !isfinite(err)
                    throw(_ndf_fail(s, _ndf_error_nonfinite(s.t)))
                end
                for_constraint = false
                if projected
                    worst = 0.0
                    @inbounds for (q, i) in enumerate(constrained)
                        v = ynew[i] < 0 ? -ynew[i] / threshold[i] : 0.0
                        worst = q == 1 ? v : max(worst, v)       # numpy's max: NaN wins
                    end
                    if worst > rtol && worst > err
                        err = worst
                        for_constraint = true
                    end
                end
                if err <= rtol
                    below_run = 0
                    break
                end
                s.nfailed += 1
                step_fails += 1
                if for_constraint && _ndf_snap_onto_bound!(s, false)
                    continue
                end
                if abs(h) <= hmin
                    if below_run >= floor_run
                        throw(_ndf_fail(s, _ndf_floor_failure(s.t, false)))
                    end
                    below_run += 1
                    s.nbelowtol += 1
                    break
                end
                local factor::Float64
                if first_failure
                    first_failure = false
                    factor = _pymax(0.1, _NDF_SAFETY * cpow(rtol / err, 1 / (k + 1)))
                    if k > 1
                        ck = D[k+1]
                        sm = s.work
                        @inbounds for i in 1:neq
                            sm[i] = ck[i] + d[i]
                        end
                        err_lower = s.error_const[k-1] * _ndf_norm(error_weight, sm)
                        lower = err_lower > 0 ? _pymax(0.1, _NDF_SAFETY_LOWER * cpow(rtol / err_lower, 1 / k)) : Inf
                        if lower > factor
                            s.k = k - 1
                            factor = _pymin(1.0, lower)
                        end
                    end
                else
                    factor = 0.5
                end
                _ndf_change_step!(s, factor)
                last = false
                _ndf_form_w!(s)
            end

            # --- accepted ---------------------------------------------------------------
            s.nsteps += 1
            pos = s.trace_pos
            s.trace_t[pos] = s.t
            s.trace_h[pos] = s.h
            s.trace_k[pos] = s.k
            s.trace_err[pos] = err
            s.trace_newton[pos] = newton_its
            s.trace_failed[pos] = step_fails
            s.trace_pos = pos == _NDF_TRACE_STEPS ? 1 : pos + 1
            s.trace_len = min(s.trace_len + 1, _NDF_TRACE_STEPS)
            step_fails = 0
            if s.nsteps > max_steps
                throw(_ndf_fail(s, _ndf_steps_failure(max_steps, s.t)))
            end
            if s.nsteps - stall_step >= stall_window
                crawling = abs(s.tnew - stall_t) < span * _NDF_STALL_SPAN_FRACTION
                not_growing = abs(s.h) <= 2 * stall_h
                if crawling && not_growing
                    throw(_ndf_fail(s, _ndf_stall_failure(s.tnew, stall_window, span * _NDF_STALL_SPAN_FRACTION)))
                end
                stall_step = s.nsteps
                stall_t = s.tnew
                stall_h = abs(s.h)
            end

            k = s.k
            _ndf_advance!(D, k, d)
            y = D[1]
            if projected
                @inbounds for i in constrained
                    if y[i] < 0
                        y[i] = 0.0
                        s.negative += 1
                        _ndf_forget!(D, i)
                    end
                end
                ah = abs(s.h)
                @inbounds for q in eachindex(constrained)
                    i = constrained[q]
                    held[i] += (s.push[q] * ah > atol[i]) ? 1 : 0
                end
            end

            if events !== nothing
                hit = _ev_locate_crossing(events, s.t, vl, s.tnew, y, vr, dense_at!, s.dense, t_start)
                if hit !== nothing
                    t_e, values, which = hit
                    _ndf_regrid!(s, k, (t_e - s.tnew) / s.h, (t_e - s.t) / s.h)
                    s.h = t_e - s.t
                    s.hTable = s.h
                    s.tnew = t_e
                    s.consecutive = 0
                    y = D[1]
                    if projected
                        @inbounds for i in constrained
                            v = y[i]
                            y[i] = v < 0 ? 0.0 : v
                        end
                    end
                    vr === values || copyto!(vr, values)
                    stopped = (t=t_e, y=copy(y), which=which)
                    last = true
                end
                copyto!(vl, vr)
            end

            tnew = s.tnew
            while next_out <= npts
                tq = tspan[next_out]
                if direction * (tnew - tq) < 0
                    break
                end
                at = if tq == tnew
                    D[1]
                else
                    dense_at!(s.dense, tq)
                    s.dense
                end
                record(tq, at)
                on_output !== nothing && on_output(tq, at)
                next_out += 1
            end
            on_accepted !== nothing && on_accepted(tnew, D[1])
            if on_step !== nothing && (s.nsteps & 15) == 0 && !on_step(tnew, s.nsteps)
                throw(SolverError("aborted", "Aborted", tnew))
            end

            s.t = tnew
            if auto_abstol
                yy = D[1]
                @inbounds for i in 1:neq
                    fl = rtol * abs(yy[i])
                    if fl > atol[i]
                        atol[i] = fl
                        threshold[i] = fl / rtol
                    end
                end
            end
            last && break

            s.consecutive += 1
            k = s.k
            if s.consecutive >= k + 1
                best_k = k
                best = _ndf_allowed(err, k, _NDF_SAFETY, rtol)
                if k > 1
                    e_lower = s.error_const[k-1] * _ndf_norm(error_weight, D[k+1])
                    g = _ndf_allowed(e_lower, k - 1, _NDF_SAFETY_LOWER, rtol)
                    if g > best
                        best, best_k = g, k - 1
                    end
                end
                if k < max_order
                    e_higher = s.error_const[k+1] * _ndf_norm(error_weight, D[k+3])
                    g = _ndf_allowed(e_higher, k + 1, _NDF_SAFETY_HIGHER, rtol)
                    if g > best
                        best, best_k = g, k + 1
                    end
                end
                if best > 1
                    s.k = best_k
                    s.h *= best
                    s.consecutive = 0
                end
            end
            if !constant
                s.fresh = false
            end
        end
    finally
        _mat_release!(W)
    end

    stats = _ndf_stats(s)
    stats["held"] = held
    stats["sparse"] = W.info["sparse"]
    stats["fill"] = W.info["fill"]
    stats["lu"] = W.info["lu"]
    stats["solver"] = bdf ? "BDF" : "NDF"
    return Solution(tout, yout, s.t, copy(D[1]), stopped, stats)
end

@inline _ndf_allowed(e::Float64, q::Int, safety::Float64, rtol::Float64) =
    e > 0 ? _pymin(_NDF_MAX_GROWTH, safety * cpow(rtol / e, 1 / (q + 1))) : _NDF_MAX_GROWTH
