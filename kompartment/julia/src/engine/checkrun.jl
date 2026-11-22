# Is the run resolved? The run set against itself solved more carefully: the
# Python package's `kompartment/engine/checkrun.py` (the application's
# `src/sim/checkrun.js`, with the names `stateLabels` in `src/sim/jaccheck.js`
# gives the states). Done where the run is held, so that a page checking a run
# this engine holds need not fetch it.
#
# The careful run is the same model with both tolerances a hundred times
# tighter -- a compartment's own absolute tolerance too -- the relative one
# never below `CHECK_RTOL_FLOOR`, the step budget ten times larger where the
# model sets one, at the run's own output times. Each state's largest
# difference over the run is measured as a share of the most it reaches in
# either run, or of the run's absolute tolerance over its relative where that
# is more: a run holds below 0.1 %, nearly holds below 1 %, and otherwise does
# not. Nothing here rounds -- absolute values, maxima, one division -- so on the
# same two runs it gives the Python package's report to the bit.

"""How much tighter the careful run's tolerances are."""
const CHECK_CAREFUL = 100
"""The careful run's relative tolerance goes no lower than this."""
const CHECK_RTOL_FLOOR = 1e-12
"""A run holds below the first, nearly holds below the second."""
const CHECK_HOLDS = 1e-3
const CHECK_NEARLY = 1e-2
const _CR_MOST_NAMED = 6
"""The solvers whose own step budget is ten million (`PORTED_IDS`, `auto` aside)."""
const _CR_TEN_MILLION = ("dp45", "auto_julia", "rodas5p", "radau5", "fbdf", "fbdf_krylov", "qndf", "kencarp4", "trbdf2",
                         "rosenbrock23", "tsit5", "vern7")

"""`v != null && v !== ''`."""
_cr_set(v) = v !== _PD_MISSING && v !== nothing && !(v isa AbstractString && v == "")

"""
    tighten_tolerances!(model) -> NamedTuple

Tightens a model's tolerances in place, as the careful run has them
(`tightenTolerances`): both a hundred times tighter, the relative one no lower
than `CHECK_RTOL_FLOOR`; a step budget the model sets ten times as large; a
compartment's own absolute tolerance, and an index's, a hundred times tighter.
Returns `(rtol, abstol, floor)`, `floor` when the relative tolerance could not
be tightened all the way.
"""
function tighten_tolerances!(model::AbstractDict)
    sim = get(model, "simulation", nothing)
    sim isa AbstractDict || (sim = model["simulation"] = JDict())
    rtol = _pd_to_number(_pd_prop(sim, "rtol"))
    abstol = _pd_to_number(_pd_prop(sim, "abstol"))
    tighter = _pd_jmax(CHECK_RTOL_FLOOR, rtol / CHECK_CAREFUL)
    sim["rtol"] = tighter
    sim["abstol"] = abstol / CHECK_CAREFUL
    given = _pd_prop(sim, "max_steps")
    steps = _pd_to_number(given)
    if _cr_set(given) && isfinite(steps) && steps > 0
        sim["max_steps"] = _gd_round(steps * 10)
    end
    for key in ("compartments", "waste_packages")
        blocks = get(model, key, nothing)
        blocks isa AbstractVector || continue
        for b in blocks
            b isa AbstractDict || continue
            own = _pd_prop(b, "abstol")
            n = _pd_to_number(own)
            (_cr_set(own) && isfinite(n) && n > 0) && (b["abstol"] = n / CHECK_CAREFUL)
            entries = get(b, "entries", nothing)
            entries isa AbstractVector || continue
            for e in entries
                e isa AbstractDict || continue
                v = _pd_prop(e, "abstol")
                x = _pd_to_number(v)
                (_cr_set(v) && isfinite(x) && x > 0) && (e["abstol"] = x / CHECK_CAREFUL)
            end
        end
    end
    return (rtol=tighter, abstol=sim["abstol"], floor=tighter > rtol / CHECK_CAREFUL)
end

"""
    careful_model(model, times) -> (model, tightened)

The careful run's model (`carefulModel`): the run's own with the tolerances
tightened and the output times the run's.
"""
function careful_model(model::AbstractDict, times)
    out = jcopy(model)
    tightened = tighten_tolerances!(out)
    out["simulation"]["spacing"] = "series"
    out["simulation"]["output_times"] = Any[JDict("times" => Any[Float64(x) for x in times])]
    return out, tightened
end

"""The index (from 1) of the time in `t` nearest `want`, `t` sorted."""
function _cr_nearest(t, want::Float64)
    lo = 0
    hi = length(t) - 1
    while hi - lo > 1
        mid = (lo + hi) >> 1
        if t[mid+1] <= want
            lo = mid
        else
            hi = mid
        end
    end
    return (abs(t[hi+1] - want) < abs(t[lo+1] - want) ? hi : lo) + 1
end

"""
    state_labels(sys) -> Vector{String}

What each state is called (`stateLabels`): a block's name with its index, a
far-field path's with the cell, `state i` for one nothing names.
"""
function state_labels(sys::System)
    n = sys.nstate
    labels = Vector{Union{Nothing,String}}(nothing, n)
    space = sys.builder.space
    units = material_units(sys)
    for entry in sys.builder.states
        try
            farf = get(entry, :farf, nothing)
            if entry.kind == "farfield" && farf !== nothing
                nnuc, other_dims, other_width = farf.nnuc, farf.other_dims, farf.other_width
                ncells, list_name = farf.ncells, farf.list_name
                names = list_name === nothing ? Any[nothing] : index_names(space, list_name)
                cells = try
                    cell_names(entry.block)
                catch e
                    e isa InterruptException && rethrow()
                    nothing
                end
                for o in 0:other_width-1
                    others = isempty(other_dims) ? String[] : tuple_at(space, other_dims, o)
                    base = entry.base + o * ncells * nnuc
                    for m in 0:nnuc-1
                        index = Any[]
                        k = 0
                        for dim in entry.dims
                            if dim == list_name
                                push!(index, names[m+1])
                            else
                                push!(index, others[k+1])
                                k += 1
                            end
                        end
                        suffix = isempty(index) ? "" : " [" * join((x === nothing ? "" : string(x) for x in index), ", ") * "]"
                        for cell in 0:ncells-1
                            name = (cells !== nothing && cell < length(cells) && cells[cell+1] !== nothing) ?
                                   cells[cell+1] : "cell $(cell + 1)"
                            labels[base+cell*nnuc+m+1] = "$(entry.name)$suffix $name"
                        end
                    end
                end
                continue
            end
            for d in describe_entry(sys, entry, entry.kind, "y", units)
                labels[d["offset"]+1] = d["label"]
            end
        catch e
            e isa InterruptException && rethrow()
            for i in 0:entry.width-1
                labels[entry.base+i+1] = entry.width > 1 ? "$(entry.name) [$i]" : entry.name
            end
        end
    end
    return String[(x === nothing || isempty(x)) ? "state $(i - 1)" : x for (i, x) in enumerate(labels)]
end

"""
    compare_runs(held, careful; abstol=nothing, labels=nothing) -> JDict

The run set against the careful one, state by state (`compareRuns`): `held` and
`careful` are runs (`project`, `system`, `t`, `y` a row per time). Returns
`{"verdict", "worst", "moved", "states", "times", "sameTimes"}`, `moved` the
states that moved most, each `{"label", "state", "share", "at", "held",
"careful"}` (`state` from 0).
"""
function compare_runs(held, careful; abstol=nothing, labels=nothing)
    n = held.system.nstate
    rtol = _pd_to_number(_pd_prop(held.project.simulation, "rtol"))
    atol = abstol === nothing ? absolute_tolerance(held.project, held.system) : abstol
    names = labels === nothing ? state_labels(held.system) : labels
    ht = Float64[x for x in held.t]
    ct = Float64[x for x in careful.t]
    T = length(ht)
    # Each of the run's times, in the careful run.
    at = zeros(Int, T)
    same = length(ct) == T
    for k in 1:T
        at[k] = (same && ct[k] == ht[k]) ? k : _cr_nearest(ct, ht[k])
        at[k] != k && (same = false)
    end
    peak = zeros(n)
    diff = zeros(n)
    when = ones(Int, n)
    for k in 1:T
        a = held.y[k]
        b = careful.y[at[k]]
        for i in 1:n
            x = Float64(a[i])
            y = Float64(b[i])
            # Math.max of the two magnitudes: NaN if either is, and a NaN is never a peak.
            big = (isnan(x) || isnan(y)) ? NaN : max(abs(x), abs(y))
            big > peak[i] && (peak[i] = big)
            d = abs(x - y)
            # A state that is not a number in one run and is in the other is as
            # far apart as two runs can be.
            if d > diff[i] || isnan(d)
                diff[i] = isnan(d) ? Inf : d
                when[i] = k
            end
        end
    end
    share = zeros(n)
    worst = 0.0
    for i in 1:n
        floor_ = (atol isa Real ? Float64(atol) : Float64(atol[i])) / rtol
        size = max(peak[i], isfinite(floor_) ? floor_ : 0.0)
        s = size > 0 ? diff[i] / size : (diff[i] > 0 ? Inf : 0.0)
        share[i] = s
        s > worst && (worst = s)
    end
    moving = Int[i for i in 1:n if share[i] > 0]
    order = sort(moving; by=i -> share[i], rev=true, alg=MergeSort)
    moved = JDict[]
    for i in order[1:min(length(order), _CR_MOST_NAMED)]
        w = when[i]
        push!(moved, JDict("label" => (i <= length(names) ? names[i] : "state $(i - 1)"), "state" => i - 1,
                           "share" => share[i], "at" => ht[w], "held" => Float64(held.y[w][i]),
                           "careful" => Float64(careful.y[at[w]][i])))
    end
    return JDict("verdict" => worst < CHECK_HOLDS ? "holds" : worst < CHECK_NEARLY ? "nearly" : "does not",
                 "worst" => worst, "moved" => moved, "states" => n, "times" => T, "sameTimes" => same)
end

"""`model.simulation.max_steps ?? solverDefault('max_steps', id).value ?? null`, `id` the run's solver."""
function _cr_max_steps(model::AbstractDict, solver)
    sim = get(model, "simulation", JDict())
    given = get(sim, "max_steps", nothing)
    given === nothing || return given
    id = solver === nothing ? "ndf" : solver
    id == "auto" && return nothing
    return id in _CR_TEN_MILLION ? 1.0e7 : 1.0e6
end

"""
    check_run(held, solve; model=held.project.raw) -> JDict

Checks a run (`checkRun`): solves the careful run -- `solve(project)`, a run
with whatever signal and progress the caller has -- and sets the run against
it. `model` is the model the run was made of, as a project file. Returns what
`compare_runs` gives, with what each run was solved at: `run` `{"rtol",
"abstol", "steps"}` and `careful` `{"rtol", "abstol", "floor", "ms", "steps",
"maxSteps"}`.
"""
function check_run(held, solve; model=nothing)
    (held.y === nothing || length(held.y) != length(held.t)) &&
        throw(ArgumentError("The run on show does not carry its states here, so it cannot be set against another."))
    json = model === nothing ? held.project.raw : model
    careful_json, tightened = careful_model(json, held.t)
    started = time()
    careful = solve(Project(careful_json))
    ms = (time() - started) * 1000
    report = compare_runs(held, careful)
    sim = held.project.simulation
    report["run"] = JDict("rtol" => _pd_to_number(_pd_prop(sim, "rtol")), "abstol" => _pd_to_number(_pd_prop(sim, "abstol")),
                          "steps" => get(held.stats, "nsteps", nothing))
    report["careful"] = JDict("rtol" => tightened.rtol, "abstol" => tightened.abstol, "floor" => tightened.floor, "ms" => ms,
                              "steps" => get(careful.stats, "nsteps", nothing),
                              "maxSteps" => _cr_max_steps(careful_json, get(sim, "solver", nothing)))
    return report
end
