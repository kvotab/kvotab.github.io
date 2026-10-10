# The driver the one-step methods share (engine/solvers/onestep.py), and the
# two methods: the Rosenbrock (2,3) of Shampine and Reichelt (rosenbrock23.py)
# and the Dormand-Prince (4,5) (dormand_prince.py).
#
# Step-size control, the non-negativity constraint (held derivatives and the
# projection onto zero), the stall guard, events and output are the same for
# both; each method supplies only how a step is attempted and how the
# solution is read inside one.

const _OS_EPS = 2.0^-52
const _OS_STALL_WINDOW_STEPS = 2000
const _OS_STALL_SPAN_FRACTION = 1e-9
const _OS_MAX_AT_FLOOR = 20
const _OS_SAFETY = 0.9
const _OS_SHRINK_LEAST = 0.1
const _OS_GROW_MOST = 5.0

_os_non_finite_error(t::Float64, index::Union{Nothing,Int}) =
    SolverError("nonfinite", "The state or its derivative became non-finite at t=$(_pyrepr(t))" *
                             (index === nothing ? "" : " (state $index)") * ". Check for division by zero, a " *
                             "negative base raised to a fractional power, or an initial value that is not a number.", t)

@inline _os_step_floor(t::Float64) = (16 * _OS_EPS) * abs(t)

"""The derivative with a constrained state at zero held there
(`HeldDerivative`), or the derivative as it is (`hold` false)."""
struct _OSRhs
    f::RHSFunction
    hold::Bool
    idx::Vector{Int}
    push::Vector{Float64}
end

@inline function _os_rhs!(r::_OSRhs, out::Vector{Float64}, t::Float64, y::Vector{Float64})
    r.f(out, t, y)
    r.hold || return out
    idx = r.idx
    isempty(idx) && return out
    _all_above_zero(y, idx) && return out
    push = r.push
    @inbounds for i in idx
        if (y[i] <= 0) & (out[i] < 0)
            push[i] = max(push[i], -out[i])
            out[i] = 0.0
        end
    end
    return out
end

# --- Rosenbrock (2,3) --------------------------------------------------------------------

const _ROS_SINGULAR_HINT = "A compartment with no way in and no way out will do this."
const _ROS_D = 1 / (2 + sqrt(2.0))
const _ROS_E32 = 6 + sqrt(2.0)
const _ROS_SQRT_EPS = sqrt(2.0^-52)

mutable struct _Ros23
    neq::Int
    rhs::_OSRhs
    threshold::Vector{Float64}
    pattern::Union{Nothing,Pattern}
    groups::Vector{Vector{Int}}
    evaluate::Union{Nothing,JacobianEvaluate}
    constant::Bool
    dwork::DifferenceWork
    J::Vector{Float64}
    W::IterationMatrix
    f0::Vector{Float64}
    ft::Vector{Float64}
    npds::Int
    ndecomps::Int
    spent::Int
    need_jacobian::Bool
    dfdt_at::Float64
    k1::Vector{Float64}
    k2::Vector{Float64}
    k3::Vector{Float64}
    f1::Vector{Float64}
    f2::Vector{Float64}
    tmp::Vector{Float64}
    ymid::Vector{Float64}
    t_from::Float64
    h_from::Float64
    y_from::Vector{Float64}
end

function _Ros23(neq::Int, rhs::_OSRhs, threshold::Vector{Float64}, jac::Union{Nothing,JacobianSpec})
    pattern = jac === nothing ? nothing : jac.pattern
    groups = jac === nothing ? nothing : jac.groups
    if pattern !== nothing && groups === nothing
        groups = colour_columns(pattern)
    end
    z() = zeros(neq)
    return _Ros23(neq, rhs, threshold, pattern, groups === nothing ? Vector{Int}[] : groups,
                  jac === nothing ? nothing : jac.evaluate, jac === nothing ? false : jac.constant,
                  DifferenceWork(pattern, groups, neq), zeros(pattern !== nothing ? pattern_nnz(pattern) : neq * neq),
                  IterationMatrix(0, nothing, Float64[]), z(), z(), 0, 0, 0, true, NaN,
                  z(), z(), z(), z(), z(), z(), z(), 0.0, 0.0, z())
end

_os_id(::_Ros23) = "ros23"
_os_order(::_Ros23) = 2
_os_default_max_steps(::_Ros23) = 1e6
_os_snaps_to_constraint(::_Ros23) = true

_os_step_budget_message(::_Ros23, max_steps::Float64, t::Float64) =
    "Exceeded $(trunc(Int, max_steps)) steps at t=$(_pyrepr(t))."

_os_floor_message(::_Ros23, t::Float64, hmin::Float64, worst::Int) =
    "Unable to meet integration tolerances at t=$(_pyrepr(t)) without reducing the step below the smallest " *
    "allowed ($(_pyrepr(hmin)))."

_os_stall_message(::_Ros23, t::Float64, window::Int, covered::Float64, floor::Bool) =
    "The solver stopped making progress at t=$(_pyrepr(t)): $window steps advanced the clock by less than " *
    "$(_pyrepr(covered)), and the step size is no longer growing. " *
    (floor ?
     "A state is reaching zero while its equations push it below, and a constraint that binds is not one a " *
     "one-step method can carry: use the stiff NDF solver, or turn \"cannot go negative\" off on the compartment " *
     "to see what the model really does." :
     "A rate is changing faster than the step size can follow -- a switch the model does not declare, or a " *
     "tolerance tighter than this low-order method can keep up with: declare its switch times, loosen the " *
     "tolerance, or use the stiff NDF solver.")

function _ros_jacobian!(st::_Ros23, t::Float64, y::Vector{Float64})
    if st.evaluate !== nothing && st.evaluate(st.J, t, y)
        return nothing
    end
    rhs = st.rhs
    if st.pattern !== nothing
        st.spent += length(st.groups)
        difference_jacobian!(st.J, (o, tt, yy) -> _os_rhs!(rhs, o, tt, yy), t, y, st.f0, st.pattern, st.groups,
                             st.threshold, st.dwork)
        return nothing
    end
    n = st.neq
    dl = difference_increment!(st.dwork.dl, y, st.threshold)
    ytry = st.dwork.ytry
    fg = st.dwork.fg
    J = st.J
    f0 = st.f0
    copyto!(ytry, y)
    @inbounds for j in 1:n
        ytry[j] = y[j] + dl[j]
        _os_rhs!(rhs, fg, t, ytry)
        off = (j - 1) * n
        for i in 1:n
            J[off+i] = (fg[i] - f0[i]) / dl[j]
        end
        ytry[j] = y[j]
    end
    st.spent += n
    return nothing
end

function _os_start!(st::_Ros23, t::Float64, y::Vector{Float64})::Int
    _os_rhs!(st.rhs, st.f0, t, y)
    _ros_jacobian!(st, t, y)
    st.npds += 1
    st.need_jacobian = false
    try
        st.W = IterationMatrix(st.neq, st.pattern, st.J, "auto", nothing,
                               Dict{String,String}("singular" => _ROS_SINGULAR_HINT))
    catch e
        e isa MatrixError ? error(e.msg) : rethrow()
    end
    return 1
end

_os_derivative_at_start(st::_Ros23) = st.f0

function _os_attempt!(st::_Ros23, t::Float64, y::Vector{Float64}, h::Float64, tnew::Float64,
                      ynew::Vector{Float64}, err::Vector{Float64})::Tuple{Int,Float64}
    before = st.spent
    if st.need_jacobian && !(st.constant && st.npds > 0)
        _ros_jacobian!(st, t, y)
        st.npds += 1
    end
    st.need_jacobian = false
    n = st.neq
    f0, ft, f1, f2 = st.f0, st.ft, st.f1, st.f2
    k1, k2, k3, tmp, ymid = st.k1, st.k2, st.k3, st.tmp, st.ymid
    if st.dfdt_at != t
        dt = copysign(_pymin(_ROS_SQRT_EPS * _pymax(abs(t), abs(t + h)), abs(h)), h)
        _os_rhs!(st.rhs, f1, t + dt, y)
        st.spent += 1
        @inbounds for i in 1:n
            ft[i] = (f1[i] - f0[i]) / dt
        end
        st.dfdt_at = t
    end
    msg = _mat_form!(st.W, h * _ROS_D, st.J)
    if msg !== nothing
        throw(SolverError("singular", "$msg (at t=$(_pyrepr(t)))", t))
    end
    st.ndecomps += 1
    W = st.W
    hD = h * _ROS_D
    half_h = 0.5 * h
    @inbounds for i in 1:n
        tmp[i] = f0[i] + hD * ft[i]
    end
    _mat_solve!(W, k1, tmp)
    @inbounds for i in 1:n
        ymid[i] = y[i] + half_h * k1[i]
    end
    _os_rhs!(st.rhs, f1, t + 0.5 * h, ymid)
    @inbounds for i in 1:n
        tmp[i] = f1[i] - k1[i]
    end
    _mat_solve!(W, k2, tmp)
    @inbounds for i in 1:n
        k2[i] += k1[i]
    end
    @inbounds for i in 1:n
        ynew[i] = y[i] + h * k2[i]
    end
    _os_rhs!(st.rhs, f2, tnew, ynew)
    @inbounds for i in 1:n
        tmp[i] = f2[i] - _ROS_E32 * (k2[i] - f1[i]) - 2 * (k1[i] - f0[i]) + hD * ft[i]
    end
    _mat_solve!(W, k3, tmp)
    st.spent += 2
    @inbounds for i in 1:n
        err[i] = k1[i] - 2 * k2[i] + k3[i]
    end
    st.t_from = t
    st.h_from = h
    copyto!(st.y_from, y)
    return (st.spent - before, 1 / 6)
end

function _os_dense_at!(out::Vector{Float64}, st::_Ros23, tq::Float64)
    s = (tq - st.t_from) / st.h_from
    a1 = s * st.h_from
    a2 = (s * s) * st.h_from
    y_from, f0, k2 = st.y_from, st.f0, st.k2
    @inbounds for i in eachindex(out)
        out[i] = (y_from[i] + a1 * f0[i]) + a2 * (k2[i] - f0[i])
    end
    return out
end

function _os_accept!(st::_Ros23, tnew::Float64, ynew::Vector{Float64}, reprojected::Bool)::Int
    used = 0
    if reprojected
        _os_rhs!(st.rhs, st.f2, tnew, ynew)
        used = 1
    end
    copyto!(st.f0, st.f2)
    st.need_jacobian = true
    st.dfdt_at = NaN
    return used
end

function _os_restart!(st::_Ros23, t::Float64, y::Vector{Float64})::Int
    _os_rhs!(st.rhs, st.f0, t, y)
    st.need_jacobian = true
    st.dfdt_at = NaN
    return 1
end

function _os_stats!(stats::Dict{String,Any}, st::_Ros23)
    stats["npds"] = st.npds
    stats["ndecomps"] = st.ndecomps
    stats["sparse"] = st.W.sparse
    stats["fill"] = st.W.info["fill"]
    _mat_release!(st.W)
    return stats
end

# --- Dormand-Prince (4,5) ----------------------------------------------------------------

const _DP_NODES = (1 / 5, 3 / 10, 4 / 5, 8 / 9, 1.0, 1.0)
const _DP_STAGE = (
    (1 / 5,),
    (3 / 40, 9 / 40),
    (44 / 45, -56 / 15, 32 / 9),
    (19372 / 6561, -25360 / 2187, 64448 / 6561, -212 / 729),
    (9017 / 3168, -355 / 33, 46732 / 5247, 49 / 176, -5103 / 18656),
    (35 / 384, 0.0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84),
)
const _DP_ERROR = (71 / 57600, 0.0, -71 / 16695, 71 / 1920, -17253 / 339200, 22 / 525, -1 / 40)
const _DP_DENSE = (
    (1.0, -183 / 64, 37 / 12, -145 / 128),
    (0.0, 0.0, 0.0, 0.0),
    (0.0, 1500 / 371, -1000 / 159, 1000 / 371),
    (0.0, -125 / 32, 125 / 12, -375 / 64),
    (0.0, 9477 / 3392, -729 / 106, 25515 / 6784),
    (0.0, -11 / 7, 11 / 3, -55 / 28),
    (0.0, 3 / 2, -4.0, 5 / 2),
)

mutable struct _DP45
    neq::Int
    rhs::_OSRhs
    k::Vector{Vector{Float64}}
    acc::Vector{Float64}
    ystage::Vector{Float64}
    t_from::Float64
    h_from::Float64
    y_from::Vector{Float64}
end

_DP45(neq::Int, rhs::_OSRhs) = _DP45(neq, rhs, [zeros(neq) for _ in 1:7], zeros(neq), zeros(neq), 0.0, 0.0, zeros(neq))

_os_id(::_DP45) = "dp45"
_os_order(::_DP45) = 4
_os_default_max_steps(::_DP45) = 1e7
_os_snaps_to_constraint(::_DP45) = false

_os_step_budget_message(::_DP45, max_steps::Float64, t::Float64) =
    "Exceeded $(trunc(Int, max_steps)) steps at t=$(_pyrepr(t)); the system may be stiff -- try a stiff solver " *
    "(NDF, or Rosenbrock 2-3)."

_os_floor_message(::_DP45, t::Float64, hmin::Float64, worst::Int) =
    "Unable to meet integration tolerances at t=$(_pyrepr(t)) without reducing the step below the smallest " *
    "allowed ($(_pyrepr(hmin))). State $worst is the worst offender; the system is probably stiff -- try a stiff " *
    "solver (NDF, or Rosenbrock 2-3)."

_os_stall_message(::_DP45, t::Float64, window::Int, covered::Float64, floor::Bool) =
    "The solver stopped making progress at t=$(_pyrepr(t)): $window steps advanced the clock by less than " *
    "$(_pyrepr(covered)), and the step size is no longer growing. " *
    (floor ?
     "A state is being held against zero, which this explicit method cannot carry: use the stiff NDF solver, or " *
     "turn \"cannot go negative\" off on the compartment to see what the model really does." :
     "The system is stiff -- try a stiff solver (NDF, or Rosenbrock 2-3).")

"""`y + h * sum(c_j k_j)` over the non-zero coefficients (`_combine`)."""
function _dp_combine!(out::Vector{Float64}, st::_DP45, y::Vector{Float64}, h::Float64, row::NTuple{N,Float64}) where {N}
    acc = st.acc
    fill!(acc, 0.0)
    for j in 1:N
        c = row[j]
        c != 0 || continue
        kj = st.k[j]
        @inbounds for i in eachindex(acc)
            acc[i] = acc[i] + c * kj[i]
        end
    end
    @inbounds for i in eachindex(out)
        out[i] = y[i] + h * acc[i]
    end
    return out
end

function _os_start!(st::_DP45, t::Float64, y::Vector{Float64})::Int
    _os_rhs!(st.rhs, st.k[1], t, y)
    return 1
end

_os_derivative_at_start(st::_DP45) = st.k[1]

function _os_attempt!(st::_DP45, t::Float64, y::Vector{Float64}, h::Float64, tnew::Float64,
                      ynew::Vector{Float64}, err::Vector{Float64})::Tuple{Int,Float64}
    # The stages one by one: each row of coefficients is a tuple of its own length.
    k, ys = st.k, st.ystage
    _dp_combine!(ys, st, y, h, _DP_STAGE[1])
    _os_rhs!(st.rhs, k[2], t + h * _DP_NODES[1], ys)
    _dp_combine!(ys, st, y, h, _DP_STAGE[2])
    _os_rhs!(st.rhs, k[3], t + h * _DP_NODES[2], ys)
    _dp_combine!(ys, st, y, h, _DP_STAGE[3])
    _os_rhs!(st.rhs, k[4], t + h * _DP_NODES[3], ys)
    _dp_combine!(ys, st, y, h, _DP_STAGE[4])
    _os_rhs!(st.rhs, k[5], t + h * _DP_NODES[4], ys)
    _dp_combine!(ys, st, y, h, _DP_STAGE[5])
    _os_rhs!(st.rhs, k[6], t + h * _DP_NODES[5], ys)
    _dp_combine!(ynew, st, y, h, _DP_STAGE[6])
    _os_rhs!(st.rhs, st.k[7], tnew, ynew)
    fill!(err, 0.0)
    for j in 1:7
        c = _DP_ERROR[j]
        c != 0 || continue
        kj = st.k[j]
        @inbounds for i in eachindex(err)
            err[i] = err[i] + c * kj[i]
        end
    end
    st.t_from = t
    st.h_from = h
    copyto!(st.y_from, y)
    return (6, 1.0)
end

function _os_dense_at!(out::Vector{Float64}, st::_DP45, tq::Float64)
    s = (tq - st.t_from) / st.h_from
    s2 = s * s
    s3 = s2 * s
    s4 = s3 * s
    acc = st.acc
    fill!(acc, 0.0)
    for j in 1:7
        c = _DP_DENSE[j]
        w = c[1] * s + c[2] * s2 + c[3] * s3 + c[4] * s4
        w != 0 || continue
        kj = st.k[j]
        @inbounds for i in eachindex(acc)
            acc[i] = acc[i] + w * kj[i]
        end
    end
    h = st.h_from
    y_from = st.y_from
    @inbounds for i in eachindex(out)
        out[i] = y_from[i] + h * acc[i]
    end
    return out
end

function _os_accept!(st::_DP45, tnew::Float64, ynew::Vector{Float64}, reprojected::Bool)::Int
    spent = 0
    if reprojected
        _os_rhs!(st.rhs, st.k[7], tnew, ynew)
        spent = 1
    end
    copyto!(st.k[1], st.k[7])
    return spent
end

_os_restart!(st::_DP45, t::Float64, y::Vector{Float64}) = 0
_os_stats!(stats::Dict{String,Any}, st::_DP45) = stats

# --- the driver ------------------------------------------------------------------------

_truthy(x) = x === nothing ? false : x isa Bool ? x : x isa Number ? x != 0 :
             (x isa AbstractString || x isa AbstractArray || x isa AbstractDict) ? !isempty(x) : true

_opt(opts::AbstractDict, key::String) = get(opts, key, nothing)

"""Python's `opts.get(key) or default`."""
_opt_or(opts::AbstractDict, key::String, default) = (v = _opt(opts, key); _truthy(v) ? v : default)

_step_callback(x) = x === nothing ? nothing : x isa StepCallback ? x : StepCallback((t, y) -> (x(t, y); nothing))
_run_progress(x) = x === nothing ? nothing : x isa RunProgress ? x : RunProgress((a, n, t) -> x(a, n, t) !== false)

function _jacobian_spec(x)::Union{Nothing,JacobianSpec}
    x === nothing && return nothing
    x isa JacobianSpec && return x
    if x isa AbstractDict
        _truthy(x) || return nothing
        return JacobianSpec(; pattern=get(x, "pattern", nothing), groups=get(x, "groups", nothing),
                            evaluate=get(x, "evaluate", nothing), constant=_truthy(get(x, "constant", false)))
    end
    throw(ArgumentError("a jacobian is a JacobianSpec or nothing"))
end

"""The tolerance vector a one-step solve uses (`atol`)."""
_atol_vector(ab, neq::Int) = ab isa Real ? fill(Float64(ab), neq) : Vector{Float64}(ab)

function _os_integrate(method::Symbol, f::RHSFunction, tspan_in::AbstractVector{<:Real},
                       y0_in::AbstractVector{<:Real}, opts::AbstractDict)::Solution
    tspan = Vector{Float64}(tspan_in)
    y0 = Vector{Float64}(y0_in)
    neq = length(y0)
    t0 = tspan[1]
    t_end = tspan[end]
    if t_end == t0
        throw(SolverError("span", "Simulation start and end time are equal", t0))
    end
    span = abs(t_end - t0)
    rtol = Float64(_opt_or(opts, "rtol", 1e-3))
    atol = _atol_vector(get(opts, "abstol", 1e-6), neq)
    threshold = Vector{Float64}(undef, neq)
    @inbounds for i in 1:neq
        threshold[i] = atol[i] / rtol
    end
    nn = _opt(opts, "non_negative")
    mask = nn !== nothing && any(_truthy, nn) ? Bool[_truthy(v) for v in nn] : nothing
    holds = method === :ros23
    rhs = _OSRhs(f, mask !== nothing && holds, mask === nothing ? Int[] : findall(mask), zeros(neq))
    st = method === :ros23 ? _Ros23(neq, rhs, threshold, _jacobian_spec(_opt(opts, "jacobian"))) : _DP45(neq, rhs)
    max_steps = Float64(_opt_or(opts, "max_steps", _os_default_max_steps(st)))
    hmax_opt = _opt(opts, "hmax")
    hmax = _truthy(hmax_opt) && hmax_opt > 0 ? _pymin(Float64(hmax_opt), span) : 0.1 * span
    hmin_v = _opt(opts, "hmin")
    hmin_opt = _truthy(hmin_v) && hmin_v > 0 ? Float64(hmin_v) : 0.0
    stall_window = Int(_opt_or(opts, "stall_window", _OS_STALL_WINDOW_STEPS))
    h0v = _opt(opts, "h0")
    h0 = _truthy(h0v) && h0v > 0 ? Float64(h0v) : 0.0
    events = _opt(opts, "events")
    return _os_run(st, rhs, tspan, y0, rtol, atol, threshold, mask, max_steps, hmax, hmin_opt, stall_window, h0,
                   events === nothing ? nothing : events::EventFunctions,
                   _step_callback(_opt(opts, "on_output")), _step_callback(_opt(opts, "on_accepted")),
                   _run_progress(_opt(opts, "on_step")))
end

function _os_run(st::S, rhs::_OSRhs, tspan::Vector{Float64}, y0::Vector{Float64}, rtol::Float64,
                 atol::Vector{Float64}, threshold::Vector{Float64}, mask::Union{Nothing,Vector{Bool}},
                 max_steps::Float64, hmax::Float64, hmin_opt::Float64, stall_window::Int, h0::Float64,
                 events::Union{Nothing,EventFunctions}, on_output::Union{Nothing,StepCallback},
                 on_accepted::Union{Nothing,StepCallback}, on_step::Union{Nothing,RunProgress})::Solution where {S}
    neq = length(y0)
    npts = length(tspan)
    t0 = tspan[1]
    t_end = tspan[end]
    direction = t_end > t0 ? 1.0 : -1.0
    span = abs(t_end - t0)
    stall_span = _OS_STALL_SPAN_FRACTION * span
    exponent = 1 / (_os_order(st) + 1)
    nn_idx = mask === nothing ? Int[] : findall(mask)
    has_nn = mask !== nothing
    tout = Float64[]
    yout = Vector{Vector{Float64}}()

    t = t0
    y = copy(y0)
    push!(tout, t0)
    push!(yout, copy(y))
    next_out = 2
    nsteps = 0
    nfailed = 0
    nbelowtol = 0
    negative = 0
    nfevals = 0
    held = rhs.hold ? zeros(Int, neq) : nothing
    vl = Float64[]
    vr = Float64[]
    if events !== nothing
        vl = zeros(events.n)
        events.fun(vl, t0, y)
        vr = zeros(events.n)
    end
    stopped = nothing
    nfevals += _os_start!(st, t, y)

    ynew = zeros(neq)
    err_vec = zeros(neq)
    dense = zeros(neq)
    evbuf = zeros(neq)
    local step_size::Float64
    if h0 > 0
        step_size = h0
    else
        f0 = _os_derivative_at_start(st)
        d0 = _weighted_norm(y, y, y, threshold)[1] / rtol
        d1 = _weighted_norm(f0, y, y, threshold)[1] / rtol
        guess = (d0 < 1e-5 || d1 < 1e-5) ? 1e-6 : 0.01 * (d0 / d1)
        guess = _pymin(guess, hmax)
        trial = zeros(neq)
        dg = direction * guess
        @inbounds for i in 1:neq
            trial[i] = y[i] + dg * f0[i]
        end
        ftry = _os_rhs!(rhs, zeros(neq), t0 + direction * guess, trial)
        nfevals += 1
        @inbounds for i in 1:neq
            ftry[i] = ftry[i] - f0[i]
        end
        d2 = _weighted_norm(ftry, y, y, threshold)[1] / rtol / guess
        if !isfinite(d2)
            d2 = 100 * d1
        end
        m = _pymax(d1, d2)
        h1 = m <= 1e-15 ? _pymax(1e-6, guess * 1e-3) : cpow(0.01 / m, exponent)
        step_size = _pymin(100 * guess, h1)
    end
    step_size = _pymin(hmax, _pymax(_pymax(_os_step_floor(t0), hmin_opt), step_size))
    at_floor = 0
    stall_step = 0
    stall_t = t0
    stall_h = 0.0
    floor_in_window = 0
    tnew = t
    dense_at! = (out::Vector{Float64}, tq::Float64) -> begin
        _os_dense_at!(out, st, tq)
        if has_nn
            @inbounds for i in nn_idx
                v = out[i]
                out[i] = v < 0 ? 0.0 : v
            end
        end
        nothing
    end
    while true
        if nsteps > max_steps
            throw(SolverError("steps", _os_step_budget_message(st, max_steps, t), t))
        end
        hmin = _pymax(_os_step_floor(t), hmin_opt)
        step_size = _pymin(hmax, _pymax(hmin, step_size))
        h = direction * step_size
        last = false
        if 1.1 * step_size >= abs(t_end - t)
            h = t_end - t
            step_size = abs(h)
            last = true
        end
        err = 0.0
        worst_at = 1
        failed_once = false
        restart = false
        tnew = t
        while true
            tnew = last ? t_end : t + h
            h = tnew - t
            fevals, scale = _os_attempt!(st, t, y, h, tnew, ynew, err_vec)
            nfevals += fevals
            worst, worst_at = _weighted_norm(err_vec, y, ynew, threshold)
            err = (worst * step_size) * scale
            if !isfinite(err)
                nfailed += 1
                if step_size <= hmin
                    throw(_os_non_finite_error(t, worst_at - 1))
                end
                failed_once = true
                step_size = _pymax(hmin, 0.1 * step_size)
                h = direction * step_size
                last = false
                continue
            end
            for_constraint = false
            if has_nn && err <= rtol && _any_below_zero(ynew, nn_idx)
                best = 0.0
                at = 1
                @inbounds for i in 1:neq
                    v = (mask[i] & (ynew[i] < 0)) ? -ynew[i] / threshold[i] : 0.0
                    if i == 1
                        best = v
                        at = 1
                    elseif !isnan(best) && (isnan(v) || v > best)
                        best = v
                        at = i
                    end
                end
                if best > 0 && best > rtol
                    err = best
                    worst_at = at
                    for_constraint = true
                end
            end
            if err <= rtol
                at_floor = 0
                break
            end
            nfailed += 1
            if for_constraint
                floor_in_window += 1
            end
            if for_constraint && _os_snaps_to_constraint(st)
                any_snap = false
                @inbounds for i in nn_idx
                    if (ynew[i] < 0) & (y[i] > 0) & (y[i] <= atol[i])
                        y[i] = 0.0
                        any_snap = true
                    end
                end
                if any_snap
                    nfevals += _os_restart!(st, t, y)
                    restart = true
                    break
                end
            end
            before = step_size
            if for_constraint || failed_once
                step_size = _pymax(hmin, 0.5 * step_size)
            else
                step_size = _pymax(hmin, step_size * _pymax(_OS_SHRINK_LEAST,
                                                            _OS_SAFETY * cpow(rtol / err, exponent)))
            end
            failed_once = true
            if step_size <= hmin
                at_floor += 1
                if at_floor >= _OS_MAX_AT_FLOOR
                    throw(SolverError("tolerance", _os_floor_message(st, t, hmin, worst_at - 1), t))
                end
                step_size = before
                nbelowtol += 1
                break
            end
            h = direction * step_size
            last = false
        end
        restart && continue
        nsteps += 1
        reprojected = false
        if has_nn
            if _any_below_zero(ynew, nn_idx)
                cnt = 0
                @inbounds for i in nn_idx
                    if ynew[i] < 0
                        ynew[i] = 0.0
                        cnt += 1
                    end
                end
                reprojected = true
                negative += cnt
                floor_in_window += cnt
            end
            if held !== nothing
                push = rhs.push
                cnt = 0
                @inbounds for i in 1:neq
                    if push[i] * step_size > atol[i]
                        held[i] += 1
                        cnt += 1
                    end
                end
                floor_in_window += cnt
                fill!(push, 0.0)
            end
        end
        if nsteps - stall_step >= stall_window
            crawling = abs(tnew - stall_t) < stall_span
            not_growing = abs(h) <= stall_h
            if crawling && not_growing
                throw(SolverError("stalled", _os_stall_message(st, tnew, stall_window, stall_span,
                                                               floor_in_window > 0), tnew))
            end
            stall_step = nsteps
            stall_t = tnew
            stall_h = abs(h)
            floor_in_window = 0
        end

        if events !== nothing
            hit = _ev_locate_crossing(events, t, vl, tnew, ynew, vr, dense_at!, evbuf, t0)
            if hit !== nothing
                t_e, values, which = hit
                tnew = t_e
                dense_at!(dense, tnew)
                copyto!(ynew, dense)
                vr === values || copyto!(vr, values)
                stopped = (t=tnew, y=copy(ynew), which=which)
                last = true
            end
            copyto!(vl, vr)
        end
        while next_out <= npts
            tq = tspan[next_out]
            if direction * (tnew - tq) < 0
                break
            end
            at_v = if tq == tnew
                ynew
            else
                dense_at!(dense, tq)
                dense
            end
            push!(tout, tq)
            push!(yout, copy(at_v))
            on_output !== nothing && on_output(tq, at_v)
            next_out += 1
        end
        on_accepted !== nothing && on_accepted(tnew, ynew)
        if on_step !== nothing && (nsteps & 31) == 0
            if !on_step(abs(tnew - t0) / span, nsteps, tnew)
                throw(SolverError("aborted", "Simulation aborted", tnew))
            end
        end
        last && break
        nfevals += _os_accept!(st, tnew, ynew, reprojected)
        if !failed_once
            grow = err > 0 ? _OS_SAFETY * cpow(rtol / err, exponent) : _OS_GROW_MOST
            step_size *= _pymin(_OS_GROW_MOST, _pymax(_OS_SHRINK_LEAST, grow))
        end
        t = tnew
        copyto!(y, ynew)
    end
    stats = Dict{String,Any}("nsteps" => nsteps, "nfailed" => nfailed, "nfevals" => nfevals,
                             "nbelowtol" => nbelowtol, "negative" => negative, "held" => held,
                             "solver" => _os_id(st), "points" => length(tout))
    _os_stats!(stats, st)
    return Solution(tout, yout, tnew, copy(ynew), stopped, stats)
end

"""The Rosenbrock (2,3) solver (`rosenbrock23`): `opts` as Python's."""
rosenbrock23(f::RHSFunction, tspan::AbstractVector{<:Real}, y0::AbstractVector{<:Real}, opts::AbstractDict) =
    _os_integrate(:ros23, f, tspan, y0, opts)

"""The Dormand-Prince (4,5) solver (`dormand_prince`): `opts` as Python's."""
dormand_prince(f::RHSFunction, tspan::AbstractVector{<:Real}, y0::AbstractVector{<:Real}, opts::AbstractDict) =
    _os_integrate(:dp45, f, tspan, y0, opts)
