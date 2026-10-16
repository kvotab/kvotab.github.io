# How the answer moves when one parameter moves: forward sensitivities. The
# Python package's `kompartment/engine/localsens.py` (the application's
# `src/sim/localsens.js`). At the values the model holds, what is dy/dp?
#
# **The forward sensitivity equations.** Differentiate `y' = f(t, y, p)` with
# respect to a parameter and `S = dy/dp` satisfies
#
#     S' = J·S + df/dp,      S(0) = dy0/dp
#
# -- a linear system driven by df/dp, integrated alongside the states: the
# augmented vector is `[y, S_1, ..., S_m]` and one solve gives the states and
# every sensitivity at once.
#
# **J·S** is the model's analytic Jacobian applied to each sensitivity block,
# its values formed once per derivative call. **df/dp is differentiated where
# the model allows it** (engine/paramtangent.jl) and differenced otherwise --
# one forward step of `sqrt(eps)·max(|p|, 1)`, with the invariant pass run on
# either side so the perturbation reaches the algebra worked out from the
# parameter. `differenced=true` forces the difference.
#
# **The iteration matrix ignores the second derivatives**, as CVODES does: it is
# the original Jacobian repeated down the diagonal, with the original colouring
# repeated with it -- and why the solve is the NDF whatever solver the model
# names: a Rosenbrock method uses the whole Jacobian inside its formula.
#
# **It is a run of the model**: the augmented system is integrated by the
# runner's own machinery (`equations` in `run_project`), restarted at every
# switch time, through the discrete events, with the blocks that remember
# primed and fed, each compartment's own floor and the clock's interpolation.
# What the forward equations cannot carry is refused, by name (`uncarried`): a
# jump in the state, a block that remembers the path of the run where the
# derivative reads it, a semi-analytical far-field path, and a parameter that
# places a corner of the run.
#
# **Tolerances.** The states take the run's own absolute tolerances; the block
# of dy/dp takes them divided by |p| (CVODES's rule; a parameter at zero takes
# the state's unchanged).

"""A sensitivity run that cannot be set up: no analytic Jacobian, no parameter
named, too many, or something in the model the sensitivity equations cannot carry."""
struct SensitivityError <: Exception
    message::String
end
Base.showerror(io::IO, e::SensitivityError) = print(io, e.message)

const _LS_EPS = sqrt(2.0^-52)

"""`sqrt(eps)·max(|p|, 1)`: the forward step for `p`."""
step_for(p::Float64) = _LS_EPS * _pd_jmax(abs(p), 1.0)

# --- the parameter slots ----------------------------------------------------------------------

const _LS_ARRAY_INDEX = r"^(?:0|[1-9][0-9]*)$"
_ls_is_array_index(k) = k isa AbstractString && occursin(_LS_ARRAY_INDEX, k) && parse(BigInt, k) < big(2)^32 - 1

"""A dictionary in the order JavaScript enumerates an object's keys: the
integer-like ones first, ascending, then the rest as they were inserted."""
function _ls_js_ordered(d::AbstractDict)
    out = JDict()
    for k in sort!([k for k in keys(d) if _ls_is_array_index(k)]; by=k -> parse(BigInt, k))
        out[k] = d[k]
    end
    for (k, v) in d
        _ls_is_array_index(k) || (out[String(k)] = v)
    end
    return out
end

"""`effectiveValue`: the most specific entry that sets `key` and matches `index`,
else the block's own; `_PD_MISSING` where neither says anything."""
function _ls_effective_value(block, key::String, index::AbstractDict)
    best = _PD_MISSING
    best_score = -1
    entries = block isa AbstractDict ? get(block, "entries", nothing) : nothing
    for entry in (entries isa AbstractVector ? entries : Any[])
        (entry isa AbstractDict && haskey(entry, key)) || continue
        score = 0
        ok = true
        idx = get(entry, "index", nothing)
        for (lst, name) in (idx isa AbstractDict ? idx : JDict())
            if get(index, lst, _PD_MISSING) != name
                ok = false
                break
            end
            score += 1
        end
        if ok && score > best_score
            best_score = score
            best = entry[key]
        end
    end
    best_score >= 0 && return best
    return block isa AbstractDict ? get(block, key, _PD_MISSING) : _PD_MISSING
end

"""
    parameter_slots(sys) -> Vector{JDict}

Every parameter slot a built model has: `{"slot" (from 0), "name", "index",
"value", "unit"}`, one per index tuple (`parameterSlots`). `value` is the value
the model file gives the slot, read the way the editor reads it; `unit` is the
slot's as the chart labels its series.
"""
function parameter_slots(sys::System)
    out = JDict[]
    units = material_units(sys)
    space = sys.builder.space
    for entry in sys.builder.param_layout
        dims = entry.dims
        described = describe_entry(sys, entry, "parameter", "P", units)
        for off in 0:entry.width-1
            tup = isempty(dims) ? JDict() : _ls_js_ordered(tuple_by_list(space, dims, off))
            unit = off < length(described) ? get(described[off+1], "unit", "") : ""
            push!(out, JDict("slot" => entry.base + off, "name" => entry.name, "index" => tup,
                             "value" => _pd_to_number(_ls_effective_value(entry.block, "value", tup)),
                             "unit" => unit === nothing ? "" : unit))
        end
    end
    return out
end

"""`name` or `name[i][j]`: how a parameter slot is asked for (`slotLabel`)."""
function slot_label(e::AbstractDict)
    index = get(e, "index", nothing)
    idx = index isa AbstractDict ? collect(values(_ls_js_ordered(index))) : Any[]
    isempty(idx) && return get(e, "name", nothing)
    return "$(_pd_js_str(get(e, "name", nothing)))[$(join((v === nothing ? "" : _pd_js_str(v) for v in idx), "]["))]"
end

"""
    state_series(sys) -> Vector{JDict}

A name for every state the solve carries, as the chart names the same series
(`stateSeries`): `{"offset", "label", "block", "kind", "unit", "hidden"}`, in
the order of the state vector. Machinery -- a far-field path's cells, a running
mean's integral, the mass balance -- is `hidden`.
"""
function state_series(sys::System)
    units = material_units(sys)
    out = JDict[]
    for s in sys.builder.states
        kind = s.kind == "compartment" && !s.hidden ? "compartment" :
               s.kind == "waste_package" ? "waste_inventory" : s.kind == "event" ? "event" : nothing
        if kind !== nothing
            for d in describe_entry(sys, s, kind, "y", units)
                push!(out, JDict("offset" => d["offset"], "label" => d["label"], "block" => s.name, "kind" => kind,
                                 "unit" => d["unit"], "hidden" => false))
            end
            continue
        end
        for off in 0:s.width-1
            push!(out, JDict("offset" => s.base + off, "label" => s.width > 1 ? "$(s.name) #$off" : s.name,
                             "block" => s.name, "kind" => s.kind, "unit" => "", "hidden" => true))
        end
    end
    return out
end

# --- what the forward equations cannot carry --------------------------------------------------

const _LS_PATH_KINDS = ("min_max", "snapshot", "delay")

"""The algebraic blocks the derivative reads, directly or through others (`readByDerivative`)."""
function _ls_read_by_derivative(sys::System)
    algebraic = sys.builder.algebraic
    by_name = Dict(a.name => a for a in algebraic)
    direct(a) = a.kind in ("transfer", "inflow", "compartment:dydt", "waste_package", "farfield",
                           "running_mean:target") || occursin(r"^(waste_package|event|farfield):", a.kind)
    reached = Set{String}()
    stack = String[a.name for a in algebraic if direct(a)]
    while !isempty(stack)
        name = pop!(stack)
        name in reached && continue
        push!(reached, name)
        haskey(by_name, name) && append!(stack, by_name[name].reads_alg)
    end
    return [a for a in algebraic if a.name in reached]
end

"""Python's `str(v).strip() != ''`."""
_ls_said(v) = v !== nothing && v !== _PD_MISSING && !(v isa AbstractString && isempty(strip(v)))

function _ls_switched_by_event(sys::System, rec::Entry)
    for off in 0:rec.width-1
        tup = isempty(rec.dims) ? Tup() : tuple_by_list(sys.builder.space, rec.dims, off)
        for field in get(EVENT_FIELDS, rec.kind, ())
            _ls_said(value_at(rec.block, field, tup)) && return true
        end
    end
    return false
end

"""`fn()` with every value of a parameter block moved a little, then put back."""
function _ls_with_block_moved(fn, block)
    move(v) = (x = _pd_to_number(v); isfinite(x) && _ls_said(v) ? x * (1 + 1e-6) + 1e-9 : v)
    had_value = get(block, "value", _PD_MISSING)
    entries = get(block, "entries", nothing)
    entries isa AbstractVector || (entries = Any[])
    had_entries = Any[e isa AbstractDict ? get(e, "value", _PD_MISSING) : _PD_MISSING for e in entries]
    try
        had_value === _PD_MISSING || (block["value"] = move(had_value))
        for e in entries
            (e isa AbstractDict && haskey(e, "value")) && (e["value"] = move(e["value"]))
        end
        return fn()
    finally
        had_value === _PD_MISSING || (block["value"] = had_value)
        for (e, v) in zip(entries, had_entries)
            v === _PD_MISSING || (e["value"] = v)
        end
    end
end

"""
    uncarried(project, sys, wanted) -> Union{String,Nothing}

What stands between the forward equations and the right answer, in words, or
`nothing` (`uncarried`): a jump in the state inside the run; an event a trigger
sets off; a semi-analytical far-field path; a min/max, snapshot or delay -- or a
running mean a discrete event switches -- that the derivative reads; or a chosen
parameter that places a corner of the run.
"""
function uncarried(proj::Project, sys::System, wanted)
    grid = time_grid(proj)
    for (j, at) in jumps_of(sys)
        grid[1] < at < grid[end] || continue
        return "'$(j.name)' makes the state jump at t=$(_pd_js_str(Float64(at))), and dy/dp is not carried across a " *
               "jump: after it, it depends on how the jump moves with the parameters, which the sensitivity " *
               "equations do not have."
    end
    # ...and so does an event a trigger sets off, at a time nobody knows until
    # the crossing is found -- which moves with the parameters too.
    for D in sys.builder.disruption_layout
        D[:timing] == "trigger" || continue
        return "'$(D[:q])' makes the state jump whenever its trigger fires, and dy/dp is not carried across a jump: " *
               "after it, it depends on how the jump and the crossing move with the parameters, which the " *
               "sensitivity equations do not have."
    end
    # A semi-analytical path's release is read by its own held state, always,
    # and it is a convolution over the whole run's inflow.
    for p in sys.builder.farf_layout
        p[:farf].laplace || continue
        return "'$(something(p.local_name, p.name))' is worked out semi-analytically: its release is a convolution " *
               "over what flowed into it during the run, and dy/dp through a history is not carried by the " *
               "sensitivity equations, which see only the present. Work the path out on cells to run a local " *
               "sensitivity analysis."
    end
    for a in _ls_read_by_derivative(sys)
        rec = get(a, :recorder, nothing)
        rec === nothing && continue
        if rec.kind in _LS_PATH_KINDS || (rec.kind == "running_mean" && _ls_switched_by_event(sys, rec))
            return "'$(something(a.local_name, a.name))' remembers the path of the run, and the model's rates read " *
                   "it: dy/dp through a history is not carried by the sensitivity equations, which see only the " *
                   "present."
        end
    end
    corners = switch_times(proj)
    for e in wanted
        slot = e["slot"]
        i = findfirst(p -> p.base <= slot < p.base + p.width, sys.builder.param_layout)
        i === nothing && continue
        entry = sys.builder.param_layout[i]
        entry.block === nothing && continue
        moved = _ls_with_block_moved(() -> switch_times(proj), entry.block)
        if moved != corners
            return "'$(slot_label(e))' places a corner of the run (a switch time, or when something starts or " *
                   "stops): moving it moves a discontinuity, and dy/dp with respect to it is an impulse the " *
                   "sensitivity equations do not have."
        end
    end
    return nothing
end

# --- the run ----------------------------------------------------------------------------------

_ls_project(m) = m isa Project ? m : m isa Model ? project(m) : m isa AbstractDict ? Project(m) :
                 project(Kompartment.load(String(m)))

"""
    sensitivity_problem(m, parameters; most=12, differenced=false) -> NamedTuple

The augmented system `run_sensitivity` integrates, set up and not solved:
`(dydt!, jacobian, y0, rtol, abstol, n, m, chosen, system, project, equations,
tangent)` -- `dydt!(out, t, Y)` the right-hand side of `Y = [y, S_1, ..., S_m]`,
`jacobian` the model's own repeated down the diagonal (a `JacobianSpec`),
`equations` what `run_sensitivity` hands the runner, `tangent` whether df/dp
is differentiated (`true`) or differenced. Refuses as it refuses.
"""
function sensitivity_problem(m, parameters=nothing; most=nothing, differenced::Bool=false)
    proj = _ls_project(m)
    sys = build_system(proj)
    jac = sys.jacobian
    if !(jac isa JacobianInfo && jac.available)
        reason = sys.nstate == 0 ? "the model has no compartments to differentiate" :
                 jac isa JacobianInfo ? jac.reason : nothing
        throw(SensitivityError("This model has no analytic Jacobian, and the sensitivity equations are driven by it. " *
                               (reason === nothing ? "" : _pd_js_str(reason))))
    end
    by_label = Dict{Any,JDict}()
    for e in parameter_slots(sys)
        by_label[slot_label(e)] = e
    end
    parameters isa AbstractString && throw(ArgumentError("parameters is a list of slot labels, not one label"))
    wanted = JDict[by_label[p] for p in something(parameters, Any[]) if p isa AbstractString && haskey(by_label, p)]
    isempty(wanted) && throw(SensitivityError("Name at least one parameter to take the sensitivity to."))
    most_ = something(most, 12)
    if length(wanted) > _pd_to_number(most_)
        throw(SensitivityError("$(length(wanted)) parameters at once: each one adds a copy of the whole state vector " *
                               "to the solve and an evaluation of the derivative to every step. Choose at most " *
                               "$(_pd_js_str(most_))."))
    end
    refusal = uncarried(proj, sys, wanted)
    refusal === nothing || throw(SensitivityError(refusal))

    n = sys.nstate
    mm = length(wanted)
    N = n * (1 + mm)
    P = sys.P
    slots = Int[e["slot"] for e in wanted]
    tangent = differenced ? (available=false, reason="asked for the differenced df/dp", plan=nothing) :
              param_tangent(sys)
    plan = tangent.available ? tangent.plan : nothing
    nparam = max(1, sys.nparam)
    an = jac.analytic
    pattern = jac.pattern
    rows, cols = pattern.rowval, pattern.col_of
    nnz_ = pattern_nnz(pattern)

    # The clock-only algebra may be interpolated (`min_change_time`), anchored
    # where each stretch of the run starts: the runner says where. The two ends
    # it holds were worked out from the parameter as it was, so they are
    # dropped around each difference.
    clock_interval = Ref(0.0)
    clock_from = Ref(py_float(proj.simulation["start_time"]))
    on_segment = (frm, interval) -> (clock_from[] = Float64(frm); clock_interval[] = Float64(interval); nothing)
    forget_clock() = clock_interval[] > 0 && use_clock_interpolation!(sys, clock_interval[], clock_from[])

    J = zeros(nnz_)
    f0 = zeros(n)
    fp = zeros(n)
    jv = zeros(n)
    yv = zeros(n)
    sv = zeros(n)
    seed = zeros(nparam)
    # J·v off the Jacobian's values at (t, y) -- or, at a point where the
    # analytic Jacobian declines (an entry that is not finite), differenced along
    # v, as the solvers difference the matrix there.
    function jvp!(t::Float64, have::Bool)
        fill!(jv, 0.0)
        if have
            @inbounds for q in 1:nnz_
                jv[rows[q]] += J[q] * sv[cols[q]]
            end
            return jv
        end
        size_ = n == 0 ? 0.0 : maximum(abs, sv)
        size_ > 0 || return jv
        biggest = n == 0 ? 0.0 : maximum(abs, yv)
        delta = _JAC_SQRT_EPS * (biggest > 1.0 ? biggest : 1.0) / size_
        moved = zeros(n)
        rhs!(sys, moved, t, yv .+ delta .* sv)
        @inbounds for i in 1:n
            jv[i] = (moved[i] - f0[i]) / delta
        end
        return jv
    end
    function dydt!(out::Vector{Float64}, t::Float64, Y::Vector{Float64})
        copyto!(yv, 1, Y, 1, n)
        rhs!(sys, f0, t, yv)
        copyto!(out, 1, f0, 1, n)
        have = analytic_evaluate!(J, an, t, yv)
        for j in 1:mm
            base = n * j
            copyto!(sv, 1, Y, base + 1, n)
            jvp!(t, have)
            slot = slots[j]
            if plan !== nothing
                fill!(seed, 0.0)
                seed[slot+1] = 1.0
                pv = param_pvp(plan, t, yv, seed)
                @inbounds for i in 1:n
                    out[base+i] = jv[i] + pv[i]
                end
                continue
            end
            # df/dp by one forward difference. The invariant pass carries the
            # new parameter into the algebra worked out from the old one.
            p0 = P[slot+1]
            h = step_for(p0)
            P[slot+1] = p0 + h
            evaluate_invariant!(sys)
            forget_clock()
            rhs!(sys, fp, t, yv)
            P[slot+1] = p0
            evaluate_invariant!(sys)
            forget_clock()
            @inbounds for i in 1:n
                out[base+i] = jv[i] + (fp[i] - f0[i]) / h
            end
        end
        return nothing
    end

    # The iteration matrix: J down the diagonal, (1 + m) times, and the colouring
    # repeated with it.
    blocks = 1 + mm
    brows = reduce(vcat, [rows .+ b * n for b in 0:blocks-1])
    bcols = reduce(vcat, [cols .+ b * n for b in 0:blocks-1])
    big = Pattern(N, brows, bcols)
    (big.rowval == brows && big.col_of == bcols) ||
        error("the repeated Jacobian pattern did not keep the order of its blocks")
    base_groups = jac.groups === nothing ? Vector{Int}[] : jac.groups
    big_groups = isempty(base_groups) ? nothing :
                 [reduce(vcat, [g .+ b * n for b in 0:blocks-1]) for g in base_groups]
    # Asked to difference its Jacobian, the model gets that here too: the pattern
    # and its colouring, and no values.
    numeric = get(proj.simulation, "jacobian", nothing) == "numeric"
    Jb = zeros(nnz_)
    big_evaluate = numeric ? nothing : JacobianEvaluate((vals, t, Y) -> begin
        analytic_evaluate!(Jb, an, t, Y[1:n]) || return false
        for b in 0:blocks-1
            copyto!(vals, b * nnz_ + 1, Jb, 1, nnz_)
        end
        return true
    end)
    big_jacobian = JacobianSpec(big, big_groups, big_evaluate, false, false)

    # Initial conditions, the sensitivities included. dy0/dp: an initial
    # inventory may be an equation over parameters, and where it is not this is
    # exactly zero.
    y0 = initial_state(sys)
    Y0 = zeros(N)
    Y0[1:n] = y0
    for (j, slot) in enumerate(slots)
        p0 = P[slot+1]
        h = step_for(p0)
        P[slot+1] = p0 + h
        evaluate_invariant!(sys)
        yh = initial_state(sys)
        P[slot+1] = p0
        evaluate_invariant!(sys)
        Y0[n*j+1:n*(j+1)] = (yh .- y0) ./ h
    end

    # Tolerances: the run's own for the states, over |p| for dy/dp.
    base_atol = absolute_tolerance(proj, sys)
    per_state = base_atol isa Real ? fill(Float64(base_atol), n) : Float64.(base_atol[1:n])
    atol = zeros(N)
    atol[1:n] = per_state
    for (j, slot) in enumerate(slots)
        a = abs(P[slot+1])
        scale = (a == a && a != 0) ? a : 1.0
        atol[n*j+1:n*(j+1)] = per_state ./ scale
    end

    chosen = [JDict("label" => slot_label(e), "name" => e["name"], "index" => e["index"], "value" => e["value"])
              for e in wanted]
    equations = (dydt=dydt!, y0=Y0, abstol=atol, jacobian=big_jacobian, solver="ndf", on_segment=on_segment)
    return (dydt! = dydt!, jacobian=big_jacobian, y0=Y0, rtol=Float64(proj.simulation["rtol"]), abstol=atol, n=n,
            m=mm, chosen=chosen, system=sys, project=proj, equations=equations, tangent=plan !== nothing)
end

"""
    run_sensitivity(m, parameters; most=12, differenced=false, on_progress=nothing) -> NamedTuple

Integrates the model and dy/dp for the parameters named (`runSensitivity`):
`parameters` are slot labels, as `slot_label` spells them (`"Kd[I-129]"`);
`most` (12) refuses more, since each one adds a copy of the state vector to
the solve; `differenced` differences df/dp even where it could be generated.
`on_progress(fraction, t)` hears the run's progress, and returning `false`
from it stops the run.

Returns `(t, y, sens, chosen, states, series, stats, tangent)`: the output
times; `y[i]` the series of state `i`; `sens[k][i]` that of `d y_i / d p_k`;
`chosen[k]` = `{"label", "name", "index", "value"}`; the layout's states; a
name for every state (`state_series`); `{"ms", "nsteps", "states",
"restarts", "compiled"}`; and whether df/dp was differentiated (`true`) or
differenced.
"""
function run_sensitivity(m, parameters=nothing; most=nothing, differenced::Bool=false, on_progress=nothing)
    started = time()
    pr = sensitivity_problem(m, parameters; most, differenced)
    n, mm = pr.n, pr.m
    N = n * (1 + mm)
    res = run_project(pr.project; system=pr.system, on_grid=true, on_progress, equations=pr.equations)
    rows_ = res.y
    y = [Float64[r[i] for r in rows_] for i in 1:n]
    sens = [[Float64[r[n*k+i] for r in rows_] for i in 1:n] for k in 1:mm]
    nsteps = get(res.stats, "nsteps", nothing)
    stats = JDict("ms" => round(Int, 1000 * (time() - started)), "nsteps" => something(nsteps, 0), "states" => N,
                  "restarts" => something(get(res.stats, "restarts", nothing), 0), "compiled" => true)
    return (t=copy(res.t), y=y, sens=sens, chosen=pr.chosen, states=pr.system.builder.states,
            series=state_series(pr.system), stats=stats, tangent=pr.tangent)
end

"""`(p / y)·(dy/dp)`: a relative change for a relative change, comparable across
parameters as dy/dp is not. NaN where `y` is zero."""
function elasticity(y_row::AbstractVector, s_row::AbstractVector, p)
    pv = _pd_to_number(p)
    out = fill(NaN, length(y_row))
    for i in eachindex(y_row)
        yi = Float64(y_row[i])
        s = i <= length(s_row) ? Float64(s_row[i]) : NaN
        out[i] = yi == 0 ? NaN : (pv / yi) * s
    end
    return out
end
