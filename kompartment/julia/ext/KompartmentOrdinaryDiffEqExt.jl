# DifferentialEquations.jl's own solvers behind Kompartment's solver ids.
#
# The application and the Python engine carry ports of OrdinaryDiffEq's
# methods (FBDF, QNDF, Rodas5P, RadauIIA5, KenCarp4, TRBDF2, Rosenbrock23,
# Tsit5, Vern7 and the default algorithm). In Julia there is no need to port
# them: with `using OrdinaryDiffEq` loaded, a model whose solver is one of
# those ids is solved by OrdinaryDiffEq itself, with the model's analytic
# Jacobian (sparse, on its structural pattern) handed over as `jac`.
#
# The contract is the runner's, as the application's adapter keeps it: a row
# at every requested time, the blocks that remember told of every accepted
# step and every requested time, every event terminal with its direction, a
# state that cannot go negative held at zero after each step, and a failure
# reported as a SolverError.

module KompartmentOrdinaryDiffEqExt

using Kompartment
using OrdinaryDiffEq
using SparseArrays
using LinearAlgebra

import Kompartment: Solution, SolverError, JacobianSpec, EventFunctions, RHSFunction


const SciMLBase = parentmodule(OrdinaryDiffEq.DiscreteCallback)

"""
A method by name, wherever OrdinaryDiffEq keeps it: since version 7 its
methods live in sub-packages (OrdinaryDiffEqBDF, OrdinaryDiffEqSDIRK, ...),
some loaded but not exported, and some (RadauIIA5, in OrdinaryDiffEqFIRK)
only when loaded by the user.
"""
function method_named(name::Symbol, package::String)
    isdefined(OrdinaryDiffEq, name) && return getfield(OrdinaryDiffEq, name)
    for m in values(Base.loaded_modules)
        startswith(string(nameof(m)), "OrdinaryDiffEq") && isdefined(m, name) && return getfield(m, name)
    end
    throw(SolverError("unavailable", "$name is in $package, which is not loaded: `using $package` first.", NaN))
end

"""Each id the model file may name, and the method it stands for."""
function algorithm(id::String)
    fd = OrdinaryDiffEq.AutoFiniteDiff()
    id == "fbdf" && return method_named(:FBDF, "OrdinaryDiffEqBDF")(autodiff=fd)
    id == "qndf" && return method_named(:QNDF, "OrdinaryDiffEqBDF")(autodiff=fd)
    id == "rodas5p" && return method_named(:Rodas5P, "OrdinaryDiffEqRosenbrock")(autodiff=fd)
    id == "kencarp4" && return method_named(:KenCarp4, "OrdinaryDiffEqSDIRK")(autodiff=fd)
    id == "trbdf2" && return method_named(:TRBDF2, "OrdinaryDiffEqSDIRK")(autodiff=fd)
    id == "rosenbrock23" && return method_named(:Rosenbrock23, "OrdinaryDiffEqRosenbrock")(autodiff=fd)
    id == "tsit5" && return method_named(:Tsit5, "OrdinaryDiffEqTsit5")()
    id == "vern7" && return method_named(:Vern7, "OrdinaryDiffEqVerner")()
    id == "radau5" && return method_named(:RadauIIA5, "OrdinaryDiffEqFIRK")(autodiff=fd)
    id == "auto_julia" && return method_named(:DefaultODEAlgorithm, "OrdinaryDiffEqDefault")(autodiff=fd)
    if id == "fbdf_krylov"
        LS = _linear_solve()
        LS === nothing && throw(SolverError("unavailable", "FBDF by GMRES needs LinearSolve's KrylovJL_GMRES: " *
                                                           "`using LinearSolve` first.", NaN))
        return FBDF(autodiff=fd, linsolve=LS.KrylovJL_GMRES())
    end
    throw(ArgumentError("'$id' is not a DifferentialEquations.jl method this knows"))
end

"""LinearSolve, where something has loaded it (OrdinaryDiffEq does, without exporting it)."""
function _linear_solve()
    for m in values(Base.loaded_modules)
        nameof(m) === :LinearSolve && isdefined(m, :KrylovJL_GMRES) && return m
    end
    return nothing
end

const IDS = Kompartment.DIFFEQ_SOLVER_IDS
const EXPLICIT = ("tsit5", "vern7")

_opt(opts, key) = (v = get(opts, key, nothing); v === false ? nothing : v)

"""What one solve keeps: the rows asked for, and how far it has told the recorders."""
mutable struct Record
    tspan::Vector{Float64}
    next::Int
    t::Vector{Float64}
    y::Vector{Vector{Float64}}
    last_accepted::Float64
    on_output::Any
    on_accepted::Any
    non_negative::Vector{Int}
    negative::Int
    stopped::Any
    events::Any
    ev_values::Vector{Float64}
end

"""The rows due up to `t` (read off the interpolant), then the step itself, told to the recorders."""
function record_step!(r::Record, integ, t::Float64)
    u = integ.u
    while r.next <= length(r.tspan) && r.tspan[r.next] <= t
        tq = r.tspan[r.next]
        row = tq == t ? copy(u) : integ(tq)
        for i in r.non_negative
            row[i] < 0 && (row[i] = 0.0)
        end
        push!(r.t, tq)
        push!(r.y, row)
        r.on_output !== nothing && r.on_output(tq, row)
        r.next += 1
    end
    if t > r.last_accepted
        r.last_accepted = t
        r.on_accepted !== nothing && r.on_accepted(t, u)
    end
end

function solve_with(id::String, f::RHSFunction, tspan_in::AbstractVector{<:Real}, y0_in::AbstractVector{<:Real},
                    opts::AbstractDict)
    tspan = Vector{Float64}(tspan_in)
    y0 = Vector{Float64}(y0_in)
    n = length(y0)
    t0, tf = tspan[1], tspan[end]
    abs(tf - t0) > 0 || throw(SolverError("span", "Simulation start and end time are equal", t0))
    nfe = Ref(0)
    ode_f! = function (du, u, p, t)
        nfe[] += 1
        f(du, Float64(t), u)
        return nothing
    end
    jac = _opt(opts, "jacobian")
    explicit = id in EXPLICIT
    fn = if !explicit && jac isa JacobianSpec && jac.pattern !== nothing
        P = jac.pattern
        vals = zeros(length(P.rowval))
        groups = jac.groups === nothing ? Kompartment.colour_columns(P) : jac.groups
        abstol = get(opts, "abstol", 1e-6)
        rtol = Float64(something(_opt(opts, "rtol"), 1e-3))
        threshold = abstol isa Real ? fill(Float64(abstol) / rtol, n) : Vector{Float64}(abstol) ./ rtol
        f0 = zeros(n)
        work = Kompartment.DifferenceWork(P, groups, n)
        dense = n < 64
        proto = dense ? zeros(n, n) : SparseMatrixCSC(n, n, copy(P.colptr), copy(P.rowval), zeros(length(P.rowval)))
        evaluate = jac.evaluate
        jac! = function (J, u, p, t)
            ok = evaluate !== nothing && evaluate(vals, Float64(t), u)
            if !ok
                f(f0, Float64(t), u)
                Kompartment.difference_jacobian!(vals, f, Float64(t), u, f0, P, groups, threshold, work)
            end
            if dense
                fill!(J, 0.0)
                for j in 1:n, q in P.colptr[j]:P.colptr[j+1]-1
                    J[P.rowval[q], j] = vals[q]
                end
            else
                copyto!(nonzeros(J), vals)
            end
            return nothing
        end
        ODEFunction(ode_f!; jac=jac!, jac_prototype=proto)
    else
        ODEFunction(ode_f!)
    end
    prob = ODEProblem(fn, y0, (t0, tf))
    nn = _opt(opts, "non_negative")
    non_negative = nn === nothing ? Int[] : Int[i for (i, v) in enumerate(nn) if v === true]
    events = _opt(opts, "events")
    rec = Record(tspan, 2, [t0], [copy(y0)], t0, _opt(opts, "on_output"), _opt(opts, "on_accepted"), non_negative, 0,
                 nothing, events, events === nothing ? Float64[] : zeros(events.n))
    if _opt(opts, "ends_only") !== nothing
        rec.tspan = [t0, tf]
    end
    callbacks = Any[]
    # Events are found as the engine's own solvers find them, after each
    # accepted step: a change of sign in the right direction (from exactly
    # zero counts), located inside the step on the method's interpolant.
    vl = events === nothing ? Float64[] : zeros(events.n)
    vr = similar(vl)
    ybuf = zeros(n)
    events === nothing || events.fun(vl, t0, y0)
    dense_at! = (out, tq) -> nothing
    # After every accepted step: hold what cannot go negative, then the events,
    # then the rows due and the recorders.
    step_cb = DiscreteCallback((u, t, integ) -> true, function (integ)
        moved = false
        for i in rec.non_negative
            if integ.u[i] < 0
                integ.u[i] = 0.0
                rec.negative += 1
                moved = true
            end
        end
        SciMLBase.u_modified!(integ, moved)
        t = Float64(integ.t)
        if events !== nothing
            hit = Kompartment._ev_locate_crossing(events, Float64(integ.tprev), vl, t, integ.u, vr,
                                                  (out, tq) -> (integ(out, tq); nothing), ybuf, t0)
            if hit !== nothing
                te, _, which = hit
                ye = te == t ? copy(integ.u) : integ(te)
                for i in rec.non_negative
                    ye[i] < 0 && (ye[i] = 0.0)
                end
                while rec.next <= length(rec.tspan) && rec.tspan[rec.next] <= te
                    tq = rec.tspan[rec.next]
                    row = tq == te ? copy(ye) : integ(tq)
                    for i in rec.non_negative
                        row[i] < 0 && (row[i] = 0.0)
                    end
                    push!(rec.t, tq)
                    push!(rec.y, row)
                    rec.on_output !== nothing && rec.on_output(tq, row)
                    rec.next += 1
                end
                rec.last_accepted = te
                rec.on_accepted !== nothing && rec.on_accepted(te, ye)
                rec.stopped = (t=te, y=ye, which=which)
                terminate!(integ)
                return
            end
            copyto!(vl, vr)
        end
        record_step!(rec, integ, t)
    end; save_positions=(false, false))
    push!(callbacks, step_cb)
    kw = Dict{Symbol,Any}(
        :reltol => Float64(something(_opt(opts, "rtol"), 1e-3)),
        :abstol => (a = get(opts, "abstol", 1e-6); a isa Real ? Float64(a) : Vector{Float64}(a)),
        :save_everystep => false, :save_start => false, :save_end => false, :dense => false,
        :callback => CallbackSet(callbacks...),
        :maxiters => Int(something(_opt(opts, "max_steps"), 1e6)),
    )
    hmax = _opt(opts, "hmax")
    hmax !== nothing && hmax > 0 && (kw[:dtmax] = Float64(hmax))
    h0 = _opt(opts, "h0")
    h0 !== nothing && h0 > 0 && (kw[:dt] = Float64(h0))
    alg = algorithm(id)
    integ = init(prob, alg; kw...)
    solve!(integ)
    rc = integ.sol.retcode
    ok = rc == ReturnCode.Success || (rc == ReturnCode.Terminated && rec.stopped !== nothing)
    if !ok
        t = Float64(integ.t)
        throw(SolverError(string(rc), "$(nameof(typeof(alg))) stopped at t=$t: $(rc). Tighter tolerances or another " *
                                      "method may get further.", t))
    end
    s = integ.stats
    stats = Dict{String,Any}("nsteps" => Int(s.naccept), "nfailed" => Int(s.nreject), "nfevals" => nfe[],
                             "npds" => Int(s.njacs), "ndecomps" => Int(s.nw), "nsolves" => Int(s.nsolve),
                             "negative" => rec.negative, "points" => length(rec.t),
                             "solver" => string(nameof(typeof(alg))))
    return Solution(rec.t, rec.y, Float64(integ.t), copy(integ.u),
                    rec.stopped === nothing ? nothing : (t=rec.stopped.t, y=rec.stopped.y, which=rec.stopped.which),
                    stats)
end

function __init__()
    for id in IDS
        Kompartment.SOLVERS[id] = (f, tspan, y0, opts) -> solve_with(id, f, tspan, y0, opts)
    end
end

end # module
