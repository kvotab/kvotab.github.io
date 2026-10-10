# Runs a project and collects its results (src/sim/runner.js, as the Python
# engine's runner.py ports it): the solver is driven over the output grid --
# restarted at every switch time, every jump and every discrete event -- and
# only the states are kept. Every other series (an expression, a rate, a
# table read at the clock, what a recorder holds) is worked out from (t, y)
# when it is asked for, as the application does.

const MAX_SOLVER_POINTS = 4000
const MAX_EVENTS = 10000
const POINT_LIST = "Time point"
const HISTORY_KINDS = Set(["min_max", "running_mean", "snapshot", "delay", "trigger", "event"])

"""What a run produced: the states at every output time, and every other series worked out from them on demand."""
mutable struct Results
    project::Project
    system::System
    t::Vector{Float64}
    y::Vector{Vector{Float64}}
    stats::Dict{String,Any}
    timing::Dict{String,Float64}
    outputs_cache::Union{Nothing,Vector{JDict}}
    label_index::Union{Nothing,Dict{Any,JDict}}
    run_state::Any
end

Results(project, system, t, y, stats, timing) =
    Results(project, system, t, y, stats, timing, nothing, nothing, run_state(system))

Base.show(io::IO, r::Results) = print(io, "<Results ", repr(r.project.name), ": ", summary(r), ">")

function check_initial_state(sys::System, y0::Vector{Float64})
    i = findfirst(v -> !isfinite(v), y0)
    i === nothing && return
    at = findfirst_value(s -> s.base <= i - 1 < s.base + s.width, sys.builder.states)
    where_ = ""
    if at !== nothing && !isempty(at.dims)
        tup = tuple_by_list(sys.builder.space, at.dims, i - 1 - at.base)
        where_ = " at " * join(("$k=$v" for (k, v) in tup), ", ")
    end
    name = at !== nothing ? at.name : "State $(i - 1)"
    v = js_number(y0[i])
    v == "null" && (v = js_text(y0[i]))
    throw(SolverError("nonfinite", "$name starts at $v$where_, which is not a number the simulation can start from. Its " *
                                   "initial inventory works out to $v -- most often a division by a parameter that is " *
                                   "zero, or a log or square root of one.", 0.0))
end

"""The absolute tolerance per state, or one number when nothing asked for more."""
function absolute_tolerance(project::Project, sys::System)
    fallback = Float64(project.simulation["abstol"])
    per_state = fill(fallback, sys.nstate)
    asked = false
    for s in sys.builder.states
        s.kind in ("compartment", "waste_package") || continue
        for off in 0:s.width-1
            v = value_at(s.block, "abstol", tuple_by_list(sys.builder.space, s.dims, off))
            (v === nothing || v == "") && continue
            n = py_float(v)
            (isfinite(n) && n > 0) || continue
            per_state[s.base+off+1] = n
            asked = true
        end
    end
    return asked ? per_state : fallback
end

function non_negative_states(project::Project, sys::System)
    out = falses(sys.nstate)
    project.simulation["non_negative"] === false && return out
    for s in sys.builder.states
        s.kind in ("compartment", "waste_package") || continue
        for i in 0:s.width-1
            v = value_at(s.block, "non_negative", tuple_by_list(sys.builder.space, s.dims, i))
            out[s.base+i+1] = v !== false
        end
    end
    return out
end

"""Every jump the state makes in a run: `(jump, at)`."""
function jumps_of(sys::System)
    out = Tuple{JumpSpec,Float64}[]
    for j in sys.jumps
        if j.slot !== nothing
            push!(out, (j, slot_value(sys, j.slot)))
        else
            for at in sys.sampled_times[j.index+1]
                push!(out, (j, at))
            end
        end
    end
    return out
end

mutable struct StepCollector
    t::Vector{Float64}
    y::Vector{Vector{Float64}}
    stride::Int
    seen::Int
    last::Float64
end

function collect_step!(c::StepCollector, t::Float64, y::Vector{Float64})
    t > c.last || return
    c.last = t
    seen = c.seen
    c.seen = seen + 1
    seen % c.stride == 0 || return
    push!(c.t, t)
    push!(c.y, copy(y))
    if length(c.t) >= MAX_SOLVER_POINTS * 2
        c.t = c.t[1:2:end]
        c.y = c.y[1:2:end]
        c.stride *= 2
    end
end

function add_method_steps!(into::Dict{String,Any}, frm::Dict{String,Any})
    by = get(frm, "steps_by", nothing)
    by === nothing && return into
    acc = get!(into, "steps_by", OrderedDict{String,Int}())
    for (name, n) in by
        acc[name] = get(acc, name, 0) + n
    end
    into["switches"] = get(into, "switches", 0) + get(frm, "switches", 0)
    return into
end

#: The ids solved by DifferentialEquations.jl here, once `using OrdinaryDiffEq` has loaded the extension.
const DIFFEQ_SOLVER_IDS = ("fbdf", "qndf", "rodas5p", "radau5", "kencarp4", "trbdf2", "rosenbrock23", "tsit5", "vern7",
                           "auto_julia", "fbdf_krylov")

"""Why a model's solver cannot run here, and what to do instead."""
function _unavailable_solver(id)
    here = join(sort(collect(keys(SOLVERS))), ", ")
    if id in DIFFEQ_SOLVER_IDS
        extra = id == "radau5" ? " (and `using OrdinaryDiffEqFIRK`, which holds RadauIIA5)" :
                id == "fbdf_krylov" ? " (and `using LinearSolve`)" : ""
        return "'$id' is solved by DifferentialEquations.jl here: `using OrdinaryDiffEq` first$extra. Or run it with " *
               "one of this package's own solvers: $here."
    end
    id == "auto" && return "'auto', the application's switching solver, is not in the Julia engine. It hands a stiff " *
                           "run to 'ndf': run(m; solver=\"ndf\"), or 'auto_julia' with `using OrdinaryDiffEq`."
    startswith(string(id), "scipy_") && return "'$id' is SciPy's, which only the Python package runs. Here: $here, " *
                                               "or DifferentialEquations.jl's methods with `using OrdinaryDiffEq`."
    return "Unknown solver '$id'. Available here: $here; with `using OrdinaryDiffEq`, also $(join(DIFFEQ_SOLVER_IDS, ", "))."
end

"""
    run_project(project; system=nothing, on_progress=nothing, on_grid=false) -> Results

Runs a project, built here unless `system` is given. `on_progress(fraction, t)`
is called as the run goes; returning `false` from it stops the run.
"""
function run_project(project::Project; system::Union{Nothing,System}=nothing, on_progress=nothing, on_grid::Bool=false)
    t0 = time()
    sys = system === nothing ? build_system(project) : system
    # A far-field path lays its matched layers out at the first instant of a
    # run and holds them to the end of it: this is that instant, every run.
    for F in sys.data.FARF
        farfield_restart!(F)
    end
    build_ms = 1000 * (time() - t0)
    grid = time_grid(project)
    y0 = initial_state(sys)
    check_initial_state(sys, y0)
    nstate = sys.nstate
    non_negative = non_negative_states(project, sys)
    abstol = absolute_tolerance(project, sys)
    steps = (project.solver_points && !on_grid) ? StepCollector(Float64[], Vector{Float64}[], 1, 0, -Inf) : nothing
    span = (steps !== nothing && project.output_mode == "solver") ? [grid[1], grid[end]] : grid
    solve_start = time()
    if nstate == 0
        sol_t = copy(grid)
        sol_y = [Float64[] for _ in grid]
        if has_store_step(sys)
            prime_recorders!(sys, grid[1], Float64[])
            for tt in grid
                store_step!(sys, tt, Float64[])
            end
        end
        on_progress !== nothing && on_progress(1.0, grid[end])
        return Results(project, sys, sol_t, sol_y,
                       Dict{String,Any}("solver" => nothing, "integrated" => false, "points" => length(grid)),
                       Dict("build_ms" => build_ms, "solve_ms" => 1000 * (time() - solve_start)))
    end
    sim = project.simulation
    solver_id = something(get(sim, "solver", nothing), "ndf")
    solver = get(SOLVERS, solver_id, nothing)
    solver === nothing && throw(ArgumentError(_unavailable_solver(solver_id)))
    prime_recorders!(sys, grid[1], y0)
    stored = (t, y) -> (store_step!(sys, t, y); nothing)
    on_accepted = if steps !== nothing && has_store_step(sys)
        (t, y) -> (store_step!(sys, t, y); collect_step!(steps, t, y); nothing)
    elseif steps !== nothing
        (t, y) -> (collect_step!(steps, t, y); nothing)
    elseif has_store_step(sys)
        stored
    else
        nothing
    end
    numeric = get(sim, "jacobian", nothing) == "numeric"
    opts = Dict{String,Any}(
        "rtol" => Float64(sim["rtol"]), "abstol" => abstol,
        "jacobian" => jacobian_spec(sys, numeric),
        "non_negative" => collect(non_negative),
        "auto_abstol" => get(sim, "auto_abstol", false) === true,
        "hmax" => (something(get(sim, "max_step", nothing), 0) > 0) ? Float64(sim["max_step"]) : nothing,
        "h0" => (something(get(sim, "initial_step", nothing), 0) > 0) ? Float64(sim["initial_step"]) : nothing,
        "max_steps" => get(sim, "max_steps", nothing), "max_order" => get(sim, "max_order", nothing),
        "min_order" => get(sim, "min_order", nothing),
        "bdf" => get(sim, "bdf", false) === true, "norm_control" => get(sim, "norm_control", false) === true,
        "error_norm" => get(sim, "error_norm", nothing), "newton_kappa" => get(sim, "newton_kappa", nothing),
        "stagnation_tol" => get(sim, "stagnation_tol", nothing), "max_jac_age" => get(sim, "max_jac_age", nothing),
        "below_tol_run" => get(sim, "below_tol_run", nothing), "matrix" => get(sim, "matrix", nothing),
        "on_accepted" => on_accepted,
        "on_output" => has_store_step(sys) ? stored : nothing,
        "ends_only" => steps !== nothing && project.output_mode == "solver",
        "events" => has_events(sys) ? EventFunctions(length(sys.event_slots),
                                                      EventFunction((out, t, y) -> (event_values!(out, sys, t, y); nothing)),
                                                      sys.event_direction) : nothing,
        "carry" => Dict{String,Any}(),
        "on_step" => on_progress === nothing ? nothing : (fraction, n, at) -> begin
            r = on_progress(fraction, at)
            r !== false
        end,
    )
    jumps = jumps_of(sys)
    for (j, at) in jumps
        j.slot === nothing && continue
        if !isfinite(at) || sys.slot_class[j.slot+1] != 0
            throw(BuildError("The time every package fails has to come to a number before the run; '$(j.name)' says " *
                             "'$(j.text)'.", j.name))
        end
    end
    inside(t) = span[1] < t < span[end]
    breaks = sort!(unique([b for b in [switch_times(project); [at for (_, at) in jumps]] if inside(b)]))
    jumped = Ref(0)
    function jump_at(t, y)
        due = [j for (j, at) in jumps if at == t]
        isempty(due) && return y
        nxt = copy(y)
        for j in due
            apply_jump!(nxt, sys.X, j)
        end
        jumped[] += length(due)
        return nxt
    end
    min_change = py_float(something(get(sim, "min_change_time", nothing), 0))
    isfinite(min_change) || (min_change = 0.0)
    f = RHSFunction((dy, t, y) -> (rhs!(sys, dy, t, y); nothing))
    function solve_span(grid2::Vector{Float64}, start::Vector{Float64})
        use_clock_interpolation!(sys, min_change, grid2[1])
        start_segment!(sys, grid2[1], start)
        if has_events(sys)
            return solve_with_events(sys, f, solver, grid2, start, opts)
        end
        return solver(f, grid2, start, opts)
    end
    local solution
    try
        solution = !isempty(breaks) ? solve_across_breaks(solve_span, span, y0, breaks, isempty(jumps) ? nothing : jump_at) :
                   _as_run(solve_span(span, y0))
        isempty(jumps) || (solution.stats["jumps"] = jumped[])
        if steps !== nothing
            solution = project.output_mode == "both" ? merge_steps(solution, steps) : from_steps(steps, solution)
        end
    catch e
        if e isa SolverError
            hints = String[]
            said = occursin("cannot go negative", e.message)
            stalled_one_step = solver_id in ("ros23", "dp45") && occursin("stopped making progress", e.message)
            if !said && solver_id in ("dp45", "tsit5", "vern7")
                push!(hints, "This model looks stiff; switch the solver to \"$(SOLVER_LABELS["ndf"])\" or " *
                             "\"$(SOLVER_LABELS["ros23"])\", or to \"$(SOLVER_LABELS["auto"])\", which finds that out for itself.")
            end
            if !said && !stalled_one_step && solver_id != "ndf" && any(non_negative)
                push!(hints, "If a compartment reaches zero at this time, its \"cannot go negative\" setting is the likely " *
                             "cause: \"$(SOLVER_LABELS["ndf"])\" carries a binding constraint, and turning the setting off on " *
                             "that compartment shows what the model is really doing.")
            end
            isempty(hints) || (e.hint = join(hints, " "))
        end
        rethrow()
    end
    solution.stats["compiled"] = true
    # What a far-field path has to say about the run (``stats.farfield``, ``stats.layers``).
    warned = farfield_warnings(sys)
    isempty(warned.farfield) || (solution.stats["farfield"] = warned.farfield)
    isempty(warned.layers) || (solution.stats["layers"] = warned.layers)
    # A model that asks to be solved in parts is solved whole here, and says so as the
    # Python package's account of a split does.
    if get(sim, "split", nothing) == "on"
        solution.stats["split"] = Dict{String,Any}("used" => false, "mode" => "on",
                                                   "why" => "the Julia engine solves the whole model as one system")
    end
    now = time()
    return Results(project, sys, solution.t, solution.y, solution.stats,
                   Dict("build_ms" => build_ms, "solve_ms" => 1000 * (now - solve_start), "total_ms" => 1000 * (now - t0)))
end

"""A run's solution, as the runner keeps it: times, rows and counts."""
mutable struct RunSolution
    t::Vector{Float64}
    y::Vector{Vector{Float64}}
    stats::Dict{String,Any}
end

_as_run(s) = s isa RunSolution ? s : RunSolution(s.t, s.y, s.stats)

function from_steps(steps::StepCollector, solution::RunSolution)
    t = [solution.t[1]]
    y = [solution.y[1]]
    for (tt, yy) in zip(steps.t, steps.y)
        tt > t[end] || continue
        push!(t, tt)
        push!(y, yy)
    end
    end_t = solution.t[end]
    if end_t > t[end]
        push!(t, end_t)
        push!(y, solution.y[end])
    end
    stats = copy(solution.stats)
    stats["points"] = length(t)
    stats["solver_points"] = steps.seen
    stats["thinned_by"] = steps.stride > 1 ? steps.stride : 0
    return RunSolution(t, y, stats)
end

function merge_steps(solution::RunSolution, steps::StepCollector)
    t = Float64[]
    y = Vector{Float64}[]
    function push(tv, yv)
        if !isempty(t) && abs(tv - t[end]) <= abs(t[end] == 0 ? tv : t[end]) * 1e-9
            return
        end
        push!(t, tv)
        push!(y, yv)
    end
    i = j = 1
    st, sy = solution.t, solution.y
    while i <= length(st) || j <= length(steps.t)
        a = i <= length(st) ? st[i] : Inf
        b = j <= length(steps.t) ? steps.t[j] : Inf
        if a <= b
            push(a, sy[i])
            i += 1
        else
            push(b, steps.y[j])
            j += 1
        end
    end
    stats = copy(solution.stats)
    stats["points"] = length(t)
    stats["solver_points"] = steps.seen
    stats["thinned_by"] = steps.stride > 1 ? steps.stride : 0
    return RunSolution(t, y, stats)
end

"""Integrates in segments, restarting at every declared corner."""
function solve_across_breaks(solve, grid::Vector{Float64}, y0::Vector{Float64}, breaks::Vector{Float64}, jump_at=nothing)
    times = Float64[]
    rows = Vector{Float64}[]
    stats = Dict{String,Any}("nsteps" => 0, "nfailed" => 0, "nfevals" => 0, "restarts" => 0, "breaks" => length(breaks))
    ends = [breaks; grid[end]]
    y = y0
    at = grid[1]
    nxt = 1
    for end_ in ends
        end_ > at || continue
        inside = [at]
        while nxt <= length(grid) && grid[nxt] <= at
            nxt += 1
        end
        while nxt <= length(grid) && grid[nxt] < end_
            push!(inside, grid[nxt])
            nxt += 1
        end
        push!(inside, end_)
        seg = _as_run(solve(inside, y))
        for (i, tt) in enumerate(seg.t)
            (i == 1 && !isempty(times) && tt == times[end]) && continue
            push!(times, tt)
            push!(rows, seg.y[i])
        end
        s = seg.stats
        for key in ("nsteps", "nfailed", "nfevals", "restarts")
            stats[key] += something(get(s, key, 0), 0)
        end
        if !isempty(s)
            (!js_truthy(get(stats, "solver", nothing)) && js_truthy(get(s, "solver", nothing))) && (stats["solver"] = s["solver"])
            get(s, "sparse", nothing) !== nothing && (stats["sparse"] = s["sparse"])
            get(s, "fill", nothing) !== nothing && (stats["fill"] = s["fill"])
            for key in ("npds", "ndecomps", "negative", "events")
                get(s, key, nothing) !== nothing && (stats[key] = get(stats, key, 0) + s[key])
            end
            if get(s, "held", nothing) !== nothing
                stats["held"] = get(stats, "held", nothing) === nothing ? copy(s["held"]) : stats["held"] .+ s["held"]
            end
            add_method_steps!(stats, s)
        end
        y = seg.y[end]
        at = seg.t[end]
        jump_at !== nothing && (y = jump_at(at, y))
    end
    stats["restarts"] += length(ends) - 1
    return RunSolution(times, rows, stats)
end

"""Integrates a model with discrete events, restarting at each crossing."""
function solve_with_events(sys::System, f, solver, grid::Vector{Float64}, y0::Vector{Float64}, opts)
    last = grid[end]
    times = Float64[]
    rows = Vector{Float64}[]
    stats = Dict{String,Any}("nsteps" => 0, "nfailed" => 0, "nfevals" => 0, "events" => 0, "restarts" => 0)
    t = grid[1]
    y = y0
    nxt = 1
    guard = 0
    while true
        if guard > MAX_EVENTS
            error("The simulation hit $MAX_EVENTS discrete events without reaching t=$(js_number(last)). An event whose " *
                  "two expressions stay equal fires again the moment the solver restarts; check the crossing direction.")
        end
        guard += 1
        while nxt <= length(grid) && grid[nxt] <= t
            nxt += 1
        end
        nxt > length(grid) && break
        span = [t; grid[nxt:end]]
        seg = solver(f, span, y, opts)
        for (i, tt) in enumerate(seg.t)
            (i == 1 && !isempty(times) && tt == times[end]) && continue
            push!(times, tt)
            push!(rows, seg.y[i])
        end
        s = seg.stats
        stats["nsteps"] += something(get(s, "nsteps", 0), 0)
        stats["nfailed"] += something(get(s, "nfailed", 0), 0)
        stats["nfevals"] += something(get(s, "nfevals", 0), 0)
        haskey(stats, "solver") || (stats["solver"] = get(s, "solver", nothing))
        stats["sparse"] = get(s, "sparse", get(stats, "sparse", nothing))
        stats["negative"] = get(stats, "negative", 0) + something(get(s, "negative", 0), 0)
        if get(s, "held", nothing) !== nothing
            stats["held"] = get(stats, "held", nothing) === nothing ? copy(s["held"]) : stats["held"] .+ s["held"]
        end
        add_method_steps!(stats, s)
        stopped = seg.stopped
        stopped === nothing && break
        t = stopped.t
        y = stopped.y
        fire_events!(sys, stopped.which, t, y)
        store_step!(sys, t, y)
        stats["events"] += length(stopped.which)
        stats["restarts"] += 1
    end
    return RunSolution(times, rows, stats)
end

# --- what a run reports --------------------------------------------------------------------

function _material_dim(sys::System, dims)
    space = sys.builder.space
    material = sys.builder.material_list
    root = material === nothing ? nothing : get_list(space, material).root_name
    for d in dims
        (root === nothing || !has_list(space, d)) && continue
        lst = get_list(space, d)
        (lst.mapping === nothing && lst.root_name == root) && return d
    end
    return nothing
end

function _time_dependent(sys::System, kind, source, offset)
    source == "P" && return false
    (source == "X" && !(kind in HISTORY_KINDS)) && return sys.slot_class[offset+1] != 0
    return true
end

material_units(sys::System) = Dict(n => material_unit(sys.project, n) for n in material_names(sys.project))

"""A series' descriptor, its keys in the application's order. Made with room
for all of them: a large model has hundreds of thousands, and a dictionary
grown key by key spends most of its making growing."""
function _descriptor(kind, block, nuclide, index, dims, label, unit, source, offset)
    d = JDict()
    sizehint!(d, 10)
    d["kind"] = kind
    d["block"] = block
    d["nuclide"] = nuclide
    d["index"] = index
    d["dims"] = dims
    d["label"] = label
    d["unit"] = unit
    d["source"] = source
    d["offset"] = offset
    return d
end

"""The series one layout entry stands for: one per index tuple, or one."""
function describe_entry(sys::System, entry::Entry, kind, source, units)
    space = sys.builder.space
    dims = entry.dims
    block = entry.block === nothing ? JDict() : entry.block
    unit = get(entry, :unit, nothing)
    unit === nothing && (unit = something(jget(block, "unit"), ""))
    function still!(d, offset)
        _time_dependent(sys, kind, source, offset) || (d["timeDependent"] = false)
        return d
    end
    if isempty(dims)
        return [still!(_descriptor(kind, entry.name, nothing, nothing, Any[], entry.name, unit, source, entry.base),
                       entry.base)]
    end
    md = _material_dim(sys, dims)
    mpos = md === nothing ? 0 : findfirst(==(md), dims)
    out = JDict[]
    sizehint!(out, entry.width)
    # Each offset's index names, as `tuple_at` gives them, without looking
    # the lists and strides up again for every one.
    nd = length(dims)
    members = [get_list(space, d).enabled for d in dims]
    st = strides(space, dims)
    io = IOBuffer()
    for off in 0:entry.width-1
        names = Vector{String}(undef, nd)
        rest = off
        for i in 1:nd
            k = div(rest, st[i])
            rest -= k * st[i]
            names[i] = members[i][k+1].name
        end
        material = md === nothing ? nothing : names[mpos]
        u = !isempty(unit) ? unit : ((material !== nothing && kind != "trigger") ? get(units, material, "") : "")
        print(io, entry.name, " [")
        for i in 1:nd
            i > 1 && print(io, ", ")
            print(io, names[i])
        end
        print(io, ']')
        push!(out, still!(_descriptor(kind, entry.name, material, names, collect(Any, dims), String(take!(io)), u,
                                      source, entry.base + off), entry.base + off))
    end
    return out
end

function lookup_point_outputs(sys::System, units)
    out = JDict[]
    for pt in sys.builder.point_layout
        dims = pt.dims
        names = [pt[:index][d] for d in dims]
        md = _material_dim(sys, dims)
        material = md === nothing ? nothing : pt[:index][md]
        at = "@$(js_number(pt[:at]))"
        unit = something(get(pt.block, "unit", nothing), "")
        isempty(unit) && material !== nothing && (unit = get(units, material, ""))
        push!(out, JDict("kind" => "lookup", "block" => pt.name, "nuclide" => material, "index" => Any[names...; at],
                         "dims" => Any[dims...; POINT_LIST], "label" => "$(pt.name) [$(join([names; at], ", "))]",
                         "unit" => unit, "source" => "P", "offset" => pt[:slot], "timeDependent" => false))
    end
    return out
end

"""Every series a run of this system can report."""
function outputs_of(sys::System, project::Project)
    units = material_units(sys)
    out = JDict[]
    for s in sys.builder.states
        if s.kind == "compartment"
            s.hidden || append!(out, describe_entry(sys, s, "compartment", "y", units))
            continue
        end
        s.kind == "farfield" && append!(out, farfield_outputs(sys, s))
        s.kind == "waste_package" && append!(out, describe_entry(sys, s, "waste_inventory", "y", units))
        s.kind == "event" && append!(out, describe_entry(sys, s, "event", "y", units))
    end
    for a in sys.builder.algebraic
        (a.kind == "inflow" || a.hidden) && continue
        append!(out, describe_entry(sys, a, a.kind, "X", units))
    end
    for p in sys.builder.param_layout
        append!(out, describe_entry(sys, p, "parameter", "P", units))
    end
    append!(out, lookup_point_outputs(sys, units))
    append!(out, derived_outputs(project, out))
    return out
end

"""
    outputs(res, block=nothing; kind=nothing, nuclide=nothing) -> Vector of descriptors

Every series the run can report, as descriptors (label, block, kind, index,
unit, source...): all of them, or those of one block, one kind or one
nuclide, or any mix -- `outputs(res, "Soil")`, `outputs(res; kind="compartment")`.
"""
function outputs(res::Results, block=nothing; kind=nothing, nuclide=nothing)
    res.outputs_cache === nothing && (res.outputs_cache = outputs_of(res.system, res.project))
    (block === nothing && kind === nothing && nuclide === nothing) && return res.outputs_cache
    return select(res, block; kind, nuclide)
end

"""The label of every series, as the application's chart and table name them."""
labels(res::Results) = [o["label"] for o in outputs(res)]

function _by_label(res::Results)
    if res.label_index === nothing
        found = Dict{Any,JDict}()
        for o in outputs(res)
            haskey(found, o["label"]) || (found[o["label"]] = o)
        end
        res.label_index = found
    end
    return res.label_index
end

function find_output(res::Results, label::AbstractString)
    o = get(_by_label(res), label, nothing)
    o === nothing && throw(KeyError("No output labelled '$label'"))
    return o
end

Base.getindex(res::Results, label::AbstractString) = series(res, label)
Base.haskey(res::Results, label::AbstractString) = haskey(_by_label(res), label)

"""The output descriptors of one block, one kind, one nuclide, or any mix (`outputs(res, block; ...)`)."""
function select(res::Results, block=nothing; kind=nothing, nuclide=nothing)
    [o for o in outputs(res) if (block === nothing || get(o, "block", nothing) == block) &&
                                (kind === nothing || get(o, "kind", nothing) == kind) &&
                                (nuclide === nothing || get(o, "nuclide", nothing) == nuclide)]
end

series(res::Results, output) = series_many(res, Any[output])[1]

"""Rows summed left to right, as the application's loops sum them."""
function _sequential_sum(cols::Vector{Vector{Float64}}, n::Int)
    acc = zeros(n)
    for c in cols
        acc .= acc .+ c
    end
    return acc
end

function series_many(res::Results, outs)
    outs = JDict[o isa AbstractString ? find_output(res, o) : o for o in outs]
    n = length(res.t)
    cols = [zeros(n) for _ in outs]
    live = Int[]
    derived = Int[]
    for (k, o) in enumerate(outs)
        if o["source"] == "P"
            cols[k] .= res.system.P[o["offset"]+1]
        elseif o["source"] == "D"
            push!(derived, k)
        else
            push!(live, k)
        end
    end
    if !isempty(derived)
        wanted = unique([outs[k]["derived"]["of"] for k in derived])
        by_label = _by_label(res)
        frm = JDict[o for o in (get(by_label, l, nothing) for l in wanted) if o !== nothing]
        got = Dict{Any,Vector{Float64}}()
        if !isempty(frm)
            for (o, col) in zip(frm, series_many(res, frm))
                got[o["label"]] = col
            end
        end
        for k in derived
            d = outs[k]["derived"]
            src = get(got, d["of"], nothing)
            if src === nothing
                cols[k] .= NaN
                continue
            end
            v = derived_reduce(d["kind"], res.t, src; at=d["at"], period=d["period"])
            if v isa AbstractVector
                cols[k] .= v[1:n]
            else
                cols[k] .= v
            end
        end
    end
    isempty(live) && return cols
    for k in live
        o = outs[k]
        o["source"] == "y" || continue
        if haskey(o, "offsets")
            cols[k] .= _sequential_sum([[res.y[i][off+1] for i in 1:n] for off in o["offsets"]], n)
        else
            off = o["offset"] + 1
            for i in 1:n
                cols[k][i] = res.y[i][off]
            end
        end
    end
    alg = [k for k in live if outs[k]["source"] != "y"]
    if !isempty(alg)
        need = sort!(unique(Int[off for k in alg for off in (haskey(outs[k], "offsets") ? outs[k]["offsets"] : [outs[k]["offset"]])]))
        column = Dict(off => j for (j, off) in enumerate(need))
        XS = algebraic_rows(res, need)
        for k in alg
            o = outs[k]
            if haskey(o, "offsets")
                cols[k] .= _sequential_sum([XS[:, column[off]] for off in o["offsets"]], n)
            else
                cols[k] .= XS[:, column[o["offset"]]]
            end
        end
    end
    return cols
end

"""The algebraic slots `need` (0-based) at every output time, a row per time."""
function algebraic_rows(res::Results, need::Vector{Int})
    n = length(res.t)
    sys = res.system
    out = zeros(n, length(need))
    keep = run_state(sys)
    restore_run_state!(sys, res.run_state)
    try
        for i in 1:n
            at_instant!(sys, res.t[i], res.y[i])
            sys.step(res.t[i], res.y[i], sys.X, sys.P, sys.data)
            for (j, s) in enumerate(need)
                out[i, j] = sys.X[s+1]
            end
        end
    finally
        restore_run_state!(sys, keep)
        sys.clock_at = NaN
    end
    return out
end

"""The states held at zero by the non-negative constraint, and for how many steps."""
function held_at_zero(res::Results)
    held = get(res.stats, "held", nothing)
    (held === nothing || !js_truthy(get(res.stats, "nsteps", 0))) && return Any[]
    out = Any[]
    for i in findall(!=(0), held)
        state = findfirst_value(s -> s.base <= i - 1 < s.base + s.width, res.system.builder.states)
        state === nothing && continue
        label = isempty(state.dims) ? state.name :
                "$(state.name) [$(join(values(tuple_by_list(res.system.builder.space, state.dims, i - 1 - state.base)), ", "))]"
        push!(out, (label=label, steps=held[i], fraction=held[i] / res.stats["nsteps"]))
    end
    return sort!(out; by=r -> (-r.fraction, lowercase(r.label)))
end

function mass_balance(res::Results)
    budget = res.system.builder.budget
    budget === nothing && return nothing
    return audit(budget, res.t, res.y; rtol=get(res.project.simulation, "rtol", nothing),
                 abstol=absolute_tolerance(res.project, res.system))
end

"""A compartment summed over its indices (or over the lists in `over`)."""
function total(res::Results, block_name::AbstractString; over=nothing)
    s = findfirst_value(x -> x.name == block_name, res.system.builder.states)
    s === nothing && throw(KeyError("No compartment named '$block_name'"))
    n = length(res.t)
    if over === nothing || isempty(over)
        return _sequential_sum([[res.y[i][s.base+off+1] for i in 1:n] for off in 0:s.width-1], n)
    end
    keep = [d for d in s.dims if !(d in over)]
    groups = OrderedDict{Vector{String},Vector{Int}}()
    for off in 0:s.width-1
        names = tuple_at(res.system.builder.space, s.dims, off)
        key = [names[findfirst(==(d), s.dims)] for d in keep]
        push!(get!(groups, key, Int[]), s.base + off)
    end
    out = Any[]
    for (key, offs) in groups
        push!(out, (index=key, dims=keep, label=isempty(keep) ? block_name : "$block_name [$(join(key, ", "))]",
                    values=_sequential_sum([[res.y[i][o+1] for i in 1:n] for o in offs], n)))
    end
    (isempty(keep) && length(out) == 1) && return out[1].values
    return out
end

"""The largest value of a series and when."""
function Base.maximum(res::Results, output)
    v = series(res, output)
    best, at = -Inf, res.t[1]
    for i in eachindex(v)
        if v[i] > best
            best, at = v[i], res.t[i]
        end
    end
    return (value=best, time=at)
end

"""The run as the application's CSV export: a time column, then one column per series."""
function csv_lines(res::Results, outs=nothing; time_origin::Float64=0.0)
    outs = outs === nothing ? outputs(res) : JDict[o isa AbstractString ? find_output(res, o) : o for o in outs]
    cols = series_many(res, outs)
    lines = String[join(["time"; [csv_cell(o["label"]) for o in outs]], ",")]
    sizehint!(lines, length(res.t) + 1)
    io = IOBuffer()
    for i in eachindex(res.t)
        print(io, js_number(time_origin == 0 ? res.t[i] : res.t[i] - time_origin))
        for c in cols
            print(io, ',', js_number(c[i]))
        end
        push!(lines, String(take!(io)))
    end
    return lines
end

"""
    to_csv(res, path=nothing; outputs=nothing, time_origin=0.0)

The run as the application's CSV export, written to `path` (returned as text
without one). `time_origin` is subtracted from the time column.
"""
function to_csv(res::Results, path=nothing; outputs=nothing, time_origin::Real=0.0)
    lines = csv_lines(res, outputs; time_origin=Float64(time_origin))
    text = join(lines, "\n")
    path === nothing && return text
    write(path, text)
    return path
end

"""One line on how the run went: solver, steps, time taken."""
function Base.summary(res::Results)
    st = res.stats
    parts = String[string(something(get(st, "solver", nothing), "no solver"))]
    get(st, "nsteps", nothing) !== nothing && push!(parts, "$(st["nsteps"]) steps")
    js_truthy(get(st, "nfailed", 0)) && push!(parts, "$(st["nfailed"]) failed")
    push!(parts, "$(length(res.t)) output times")
    haskey(res.timing, "total_ms") && push!(parts, @sprintf("%.2f s", res.timing["total_ms"] / 1000))
    held = held_at_zero(res)
    isempty(held) || push!(parts, "$(length(held)) state(s) held at zero")
    return join(parts, ", ")
end
