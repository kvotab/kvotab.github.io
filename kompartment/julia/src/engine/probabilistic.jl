# Running a model many times over its distributions: the Python package's
# `kompartment/engine/probabilistic.py` (the application's
# `src/sim/probabilistic.js`), with the realisations shared out between
# Julia's threads rather than between processes.
#
# A probabilistic run draws a value for every distributed parameter (and every
# lookup point that carries a spread) per realisation, integrates the model
# again, and keeps the series asked for -- every realisation of them, because
# a band is read off all of them.
#
# **Built once, integrated many times.** The model is built and compiled once;
# each thread runs its share of the realisations on a copy of the built system
# of its own (`clone_system`, which shares the compiled code), rewriting the
# parameters the compiled code reads and working the invariant algebra out
# again for each. **The design is drawn whole** before any realisation runs:
# Latin hypercube is a statement about a whole column, and each input draws
# from a stream named after it, so any number of threads gives the same
# answer, to the last bit, as one; each realisation's numbers are those it has
# in a serial run, and in the Python package's.
#
# Besides a sample, a *tornado* (every input swung alone to a low and a high
# probability) runs the same way. The Python package's global sensitivity
# designs (`gsa=`) are not ported.
#
# Python's names, and these:
#
#     m.run_probabilistic(iterations, seed=, latin=, varied=, keep=, workers=,
#                         on_progress=, progress=, large=, range_=, tornado=)
#     run_probabilistic(m, iterations; seed, latin, varied, keep, threads,
#                       on_progress, progress, large, range, tornado)
#
# `workers` (processes) is `threads` here; `range_` (a 0-based, end-exclusive
# pair) is `range`, a range of realisation numbers counted from 1; `compiled`
# has no counterpart (every model here is compiled); `gsa` is refused.

const PROB_MOST_BYTES = 1073741824
const PROB_MOST_BYTES_ASKED = 4 * 1073741824
const _PB_MIN_VALUE = 5e-324

"""Anything but an input: not a parameter, not a lookup table."""
can_be_endpoint(kind) = !(kind == "parameter" || kind == "lookup")

"""Python's `str(v)`, for a name or a group a model file gives."""
function _pb_py_str(v)
    v isa AbstractString && return String(v)
    v isa Bool && return v ? "True" : "False"
    v isa Integer && return string(v)
    v isa AbstractFloat && return py_repr(v)
    v === nothing && return "None"
    return string(v)
end

"""Python's `max(a, b)` and `min(a, b)`: the first unless the second is strictly beyond it."""
_pb_pymax(a::Float64, b::Float64) = b > a ? b : a
_pb_pymin(a::Float64, b::Float64) = b < a ? b : a

"""The correlation group a plan entry's distribution belongs to, or `nothing`."""
function sample_group(entry::AbstractDict)
    spec = get(entry, "spec", nothing)
    g = spec isa AbstractDict ? get(spec, "group", nothing) : nothing
    t = g === nothing ? "" : strip(_pb_py_str(g))
    return isempty(t) ? nothing : String(t)
end

"""A sampled input's name, as the application spells it: `Kd[I-129]`, `Q@500`, `k`."""
function sample_slot_name(entry::AbstractDict)
    index = get(entry, "index", nothing)
    idx = index isa AbstractDict ? collect(values(index)) : Any[]
    if isempty(idx)
        name = get(entry, "name", nothing)
        return (name === nothing || name == "") ? "" : _pb_py_str(name)
    end
    return "$(entry["name"])[$(join((_pb_py_str(v) for v in idx), "]["))]"
end

"""
    estimate(series, times, iterations, precision="double") -> (bytes, text)

The bytes a run of this shape holds (`double` while running, `float32` in a file).
"""
function estimate(series::Integer, times::Integer, iterations::Integer, precision::AbstractString="double")
    b = Int(series) * Int(times) * Int(iterations) * (precision == "float32" ? 4 : 8)
    text = b >= 1073741824 ? @sprintf("%.1f GB", b / 1073741824) :
           b >= 1048576 ? "$(round(Int, b / 1048576)) MB" : "$(max(1, round(Int, b / 1024))) kB"
    return (bytes=b, text=text)
end

"""`"float32"` when a run of this shape would hold more than a gigabyte as doubles, else `"double"`."""
hold_precision(series::Integer, times::Integer, iterations::Integer) =
    estimate(series, times, iterations).bytes > PROB_MOST_BYTES ? "float32" : "double"

"""A Poisson process's occurrence times between two times, drawn from `stream`."""
function sample_occurrences(rate::Float64, frm::Float64, until::Float64, stream::Mulberry32; most::Int=10000)
    out = Float64[]
    (rate > 0 && until > frm) || return out
    t = frm
    while true
        u = next_uniform!(stream)
        t += (-js_log(u > 0 ? u : _PB_MIN_VALUE)) / rate
        t >= until && break
        push!(out, t)
        length(out) >= most && break
    end
    return out
end

"""
    sampling_plan(project, sys=build_system(project)) -> Vector{JDict}

The distributions a model would sample, `[{"slot", "name", "index", "spec"}]`
(see `distributed_slots`), narrowed to the inputs `simulation.varied` names
when it names any that are there.
"""
function sampling_plan(project::Project, sys::System=build_system(project; jacobian=false))
    every = distributed_slots(sys)
    chosen = get(project.simulation, "varied", nothing)
    (chosen isa AbstractVector && !isempty(chosen)) || return every
    want = Set{Any}(chosen)
    kept = JDict[e for e in every if sample_slot_name(e) in want || e["name"] in want]
    return isempty(kept) ? every : kept
end

"""What every realisation of a run sets (`designFor`), the values of every one drawn at the start."""
struct SampleDesign
    plan::Vector{JDict}
    names::Vector{String}
    best::Vector{Float64}           # the model's own value of each input
    varies::Vector{Bool}
    iterations::Int
    values::Matrix{Float64}         # inputs × iterations: what realisation i draws for input k
    seed::Any
    stats::OrderedDict{String,Any}
end

is_tornado(d::SampleDesign) = haskey(d.stats, "tornado")

"""A tornado's two probabilities, from `true`, a dictionary or a named tuple."""
function _pb_tornado_ends(tornado)
    tornado === true && return (0.05, 0.95)
    get_(k, default) = tornado isa AbstractDict ? get(tornado, String(k), get(tornado, k, default)) :
                       hasproperty(tornado, k) ? getproperty(tornado, k) : default
    return (Float64(get_(:low, 0.05)), Float64(get_(:high, 0.95)))
end

_pb_truthy_opt(x) = !(x === nothing || x === false || (x isa AbstractDict && isempty(x)) ||
                      (x isa NamedTuple && isempty(x)))

"""
    design_for(project, sys; seed=1, iterations=100, latin=true, varied=nothing, tornado=nothing) -> SampleDesign

Every realisation's values, drawn whole: one column of uniforms per sampled
input on a stream named after it (or after its correlation group), Latin
hypercube or random, the correlations the model asks for put in by
Iman-Conover, each uniform read through its input's distribution. `varied`
holds every other input at its own value; `tornado` (`(low=0.05, high=0.95)`)
swings each varied input alone instead.
"""
function design_for(project::Project, sys::System; seed=1, iterations=nothing, latin::Bool=true, varied=nothing,
                    tornado=nothing, gsa=nothing)
    _pb_truthy_opt(gsa) && throw(ArgumentError("Global sensitivity designs (gsa=) are not ported to Julia yet: run " *
                                               "them with the Python package."))
    tornado = _pb_truthy_opt(tornado) ? tornado : nothing
    plan = sampling_plan(project, sys)
    dice = any(D -> D[:timing] == "poisson" && get(D.block, "sampled", nothing) !== false,
               sys.builder.disruption_layout)
    if isempty(plan) && !(dice && tornado === nothing)
        tail = dice ? ", and a tornado swings parameters; the disruptive events are what varies here, and they need " *
                      "a probabilistic run." :
               ", so every realisation would be the same run. Give a parameter one first — the curve at the end of " *
               "its row in the left panel — or add a disruptive event that draws its occurrences."
        throw(ArgumentError("No parameter in this model has a distribution" * tail))
    end
    names = String[sample_slot_name(e) for e in plan]
    best = Float64[sys.P[e["slot"]+1] for e in plan]
    wanted = varied === nothing ? nothing : Set{String}(_pb_py_str(v) for v in varied)
    varies = Bool[wanted === nothing || names[k] in wanted for k in eachindex(plan)]
    if tornado !== nothing
        low, high = _pb_tornado_ends(tornado)
        swung = Int[k for k in eachindex(plan) if varies[k]]
        n = 2 * length(swung) + 1
        values = Matrix{Float64}(undef, length(plan), n)
        for i in 0:n-1, k in eachindex(plan)
            if i == 0 || swung[(i-1)÷2+1] != k
                values[k, i+1] = best[k]
            else
                values[k, i+1] = value_at_probability(plan[k]["spec"], (i - 1) % 2 == 0 ? low : high, i)
            end
        end
        stats = OrderedDict{String,Any}("seed" => seed, "latin" => false, "sampled" => length(plan),
                                        "tornado" => OrderedDict{String,Any}("low" => low, "high" => high,
                                                                             "swung" => swung))
        return SampleDesign(plan, names, best, varies, n, values, seed, stats)
    end
    count = iterations === nothing ? 100.0 : Float64(iterations)
    n = max(1, Int(floor(count + 0.5)))
    draws = Vector{Float64}[uniforms(n, stream_for(seed, something(sample_group(e), names[k])); latin=latin)
                            for (k, e) in enumerate(plan)]
    cp = correlation_pairs(project, names)
    problems = copy(cp.problems)
    grouped = Set{Int}(k for (k, e) in enumerate(plan) if sample_group(e) !== nothing)
    for pr in cp.pairs
        (pr.a in grouped || pr.b in grouped) || continue
        who = pr.a in grouped ? names[pr.a] : names[pr.b]
        push!(problems, "$(names[pr.a]) and $(names[pr.b]): $who is in a correlation group, which already fixes its " *
                        "sample. The correlation was ignored.")
    end
    usable = [pr for pr in cp.pairs if varies[pr.a] && varies[pr.b] && !(pr.a in grouped) && !(pr.b in grouped)]
    corr = iman_conover(draws, usable, names, seed)
    values = Matrix{Float64}(undef, length(plan), n)
    for k in eachindex(plan)
        spec = plan[k]["spec"]
        for i in 1:n
            values[k, i] = varies[k] ? value_at_probability(spec, draws[k][i], i - 1) : best[k]
        end
    end
    groups = OrderedDict{String,Vector{String}}()
    for (k, e) in enumerate(plan)
        g = sample_group(e)
        g === nothing || push!(get!(groups, g, String[]), names[k])
    end
    stats = OrderedDict{String,Any}("seed" => seed, "latin" => latin, "sampled" => length(plan),
                                    "correlated" => length(corr.columns), "correlationAdjusted" => corr.adjusted,
                                    "correlationProblems" => problems,
                                    "groups" => [OrderedDict{String,Any}("name" => g, "members" => m) for (g, m) in groups])
    return SampleDesign(plan, names, best, varies, n, values, seed, stats)
end

"""
What each input's slot in `P` holds for realisations `frm` to `to - 1` (from 0)
as a serial run holds it: the value drawn where it is a number; the model's own
for an input that is held; and, for a varied input whose draw is not a number,
what the slot held from the realisation before (the model's own for the first).
"""
function _pb_effective(design::SampleDesign, frm::Int, to::Int)
    nplan = length(design.plan)
    eff = Matrix{Float64}(undef, nplan, to - frm)
    for k in 1:nplan
        prev = design.best[k]
        for c in 1:to-frm
            v = design.values[k, frm+c]
            if isfinite(v)
                prev = v
            elseif !design.varies[k]
                prev = design.best[k]
            end
            eff[k, c] = prev
        end
    end
    return eff
end

"""Sets one realisation's values into `sys`, ready to run: the parameters, the invariant algebra, the events' dice."""
function _pb_apply!(sys::System, design::SampleDesign, eff::Matrix{Float64}, column::Int, i::Int)
    P = sys.P
    for (k, e) in enumerate(design.plan)
        P[e["slot"]+1] = eff[k, column]
    end
    evaluate_invariant!(sys)
    draw_disruptions!(sys, design.seed, i; sample=!is_tornado(design))
    return sys
end

"""This realisation's occurrences (`i` counted from 0) of every random event that draws them."""
function draw_disruptions!(sys::System, seed, i::Integer; sample::Bool=true)
    for D in sys.builder.disruption_layout
        index = D[:index]
        if D[:timing] != "poisson" || get(D.block, "sampled", nothing) === false || !sample
            set_disruption!(sys, index, false)
            continue
        end
        setting = D[:setting]
        slot_of(key) = haskey(setting, key) ? setting[key].base : nothing
        rate_slot, from_slot, until_slot = slot_of("rate"), slot_of("from"), slot_of("until")
        fixed(slot) = slot === nothing || sys.slot_class[slot+1] == 0
        if !fixed(rate_slot) || !fixed(from_slot) || !fixed(until_slot)
            set_disruption!(sys, index, false)
            continue
        end
        rate = rate_slot === nothing ? NaN : slot_value(sys, rate_slot)
        frm = from_slot === nothing ? sys.start_time : slot_value(sys, from_slot)
        until = until_slot === nothing ? sys.end_time : slot_value(sys, until_slot)
        stream = stream_for(seed, "$(D[:q])#occurrences#$i")
        times = sample_occurrences(rate, _pb_pymax(frm, sys.start_time), _pb_pymin(until, sys.end_time), stream)
        set_disruption!(sys, index, true, times)
    end
end

# --- what a run keeps ----------------------------------------------------------------------

"""
    ProbabilisticResults

What a probabilistic run kept: every realisation of each kept series, the
values drawn, and the statistics read off them.

- `t`: the output times every realisation was reported on;
- `outputs`: the kept series' descriptors (`"label"`, `"block"`, `"kind"`, ...);
- `values`: one matrix per kept series, realisations × times (row `i` is
  realisation `i`; a failed realisation's row is NaN), `Float64`, or
  `Float32` when a run of this shape would hold more than a gigabyte;
- `samples`: inputs × realisations, what was drawn for each sampled input;
- `plan`, `names`: the sampled inputs (`"slot"` from 0, `"name"`, `"index"`,
  `"spec"`) and their names as the application spells them (`Kd[I-129]`);
- `inputs`: the varied parameters as series, `"output"` a descriptor and `"k"`
  its row of `samples`;
- `ran`: 1 per realisation that ran, 0 where it failed;
- `iterations`, `range` (the realisation numbers held, from 1: all of them
  unless a `range` was asked for);
- `precision` (`"double"` or `"float32"`), `stats` (`"failed"`, `"trouble"`,
  `"ms"`, `"seed"`, `"latin"`, `"sampled"`, `"correlated"`,
  `"correlationAdjusted"`, `"correlationProblems"`, `"groups"`, `"threads"`;
  a tornado's `"tornado" => {"low", "high", "swung"}`).
"""
mutable struct ProbabilisticResults{T<:AbstractFloat}
    t::Vector{Float64}
    outputs::Vector{JDict}
    values::Vector{Matrix{T}}
    samples::Matrix{Float64}
    plan::Vector{JDict}
    names::Vector{String}
    inputs::Vector{JDict}
    ran::Vector{UInt8}
    iterations::Int
    range::UnitRange{Int}
    precision::String
    stats::OrderedDict{String,Any}
    project::Project
end

Base.show(io::IO, r::ProbabilisticResults) =
    print(io, "<ProbabilisticResults: ", r.iterations, " runs, ", length(r.outputs), " series kept, ", length(r.plan),
          " inputs, ", get(r.stats, "failed", 0), " failed>")

"""The kept series' labels."""
labels(r::ProbabilisticResults) = String[o["label"] for o in r.outputs]

function _pb_index(r::ProbabilisticResults, label)
    label isa Integer && return Int(label)
    for (k, o) in enumerate(r.outputs)
        o["label"] == label && return k
    end
    throw(KeyError("No kept series labelled '$label'"))
end

"""Every realisation of one kept series (by label or position): a matrix of realisations × times."""
realisations(r::ProbabilisticResults, label) = r.values[_pb_index(r, label)]
Base.getindex(r::ProbabilisticResults, label) = realisations(r, label)

"""The values one sampled input took, by its name (`Kd[Cs-137]`)."""
function sample(r::ProbabilisticResults, name::AbstractString)
    k = findfirst(==(name), r.names)
    k === nothing && throw(KeyError("No sampled input named '$name'"))
    return r.samples[k, :]
end

# --- the run ---------------------------------------------------------------------------------

"""The caller's `keep`: nothing (every endpoint), a function `(name, descriptor) -> Bool`, or names."""
function _pb_keep_fn(keep)
    keep === nothing && return nothing
    keep isa Function && return keep
    names = keep isa AbstractString ? Set{String}([keep]) : Set{String}(_pb_py_str(k) for k in keep)
    return (name, o) -> name in names || get(o, "label", nothing) in names
end

"""What a descriptor is kept by: its block, else its label."""
function _pb_keep_name(o::AbstractDict)
    b = get(o, "block", nothing)
    (b === nothing || b == "") || return b
    l = get(o, "label", nothing)
    return (l === nothing || l == "") ? "" : l
end

"""One realisation's kept series, onto the sample's grid, into row `row` of each matrix."""
function _pb_take!(values::Vector{Matrix{T}}, res::Results, kept::Vector{JDict}, row::Int,
                   grid::Vector{Float64}) where {T}
    times = length(grid)
    t = res.t
    rows = length(t) == times ? nothing : Int[min(searchsortedfirst(t, g), length(t)) for g in grid]
    cols = series_many(res, kept)
    for (w, c) in enumerate(cols)
        M = values[w]
        if rows === nothing
            @inbounds for j in 1:times
                M[row, j] = c[j]
            end
        else
            @inbounds for j in 1:times
                M[row, j] = c[rows[j]]
            end
        end
    end
end

"""
    run_probabilistic(m, iterations=100; seed=1, latin=true, varied=nothing, keep=nothing,
                      threads=Threads.nthreads(), on_progress=nothing, progress=false,
                      large=false, range=nothing, tornado=nothing) -> ProbabilisticResults

Runs `iterations` realisations of a model (a `Model` or a `Project`) over its
distributions and keeps the series asked for.

`keep` says which: `nothing` for every endpoint (anything but an input), a list
of block names or labels, or a function `(name, descriptor) -> Bool`. Every
varied parameter is kept as its draws, in `samples`. `seed` and `latin`
(Latin hypercube, else random) are the sampling's; the model's own settings
are `simulation(m)["seed"]` and `simulation(m)["sampling"] == "latin"`.
`varied` holds every input it does not name at its own value. `tornado =
(low=0.05, high=0.95)` swings each input alone instead (see `run_tornado`).

The model is built once. `threads` threads share the realisations (at most
`Threads.nthreads()`; start Julia with `--threads`), each on a copy of the
built system of its own; the design is drawn whole first, so the answer does
not depend on how many. The first realisation runs before the others, and a
failure there fails the run, since it says which series there are; a later
one that fails is recorded -- its row NaN, `ran` 0, `stats["failed"]` counted
and the first five in `stats["trouble"]` -- and the run goes on.

`on_progress(done, total)` is called after every realisation, from whichever
thread finished it, one call at a time and `done` rising; `progress=true`
draws a progress line on standard error (or on an `IO` passed as
`progress`). A run that would hold more than a gigabyte of doubles keeps
float32; past 1 GB even so it is refused unless `large=true` (4 GB). `range`
runs only those realisations (numbers from 1) of the whole design.
"""
function run_probabilistic(m::Model, iterations=100; kw...)
    return run_probabilistic(project(m), iterations; kw...)
end

function run_probabilistic(project::Project, iterations=100; seed=1, latin::Bool=true, varied=nothing,
                           keep=nothing, threads::Integer=Threads.nthreads(), on_progress=nothing, progress=false,
                           large::Bool=false, range=nothing, tornado=nothing, gsa=nothing)
    started = time()
    line = nothing
    if progress !== false && progress !== nothing
        what = _pb_truthy_opt(tornado) ? "runs" : "realisations"
        line = ProgressLine(iterations isa Real ? Int(floor(Float64(iterations) + 0.5)) : 0; what=what,
                            io=progress === true ? stderr : progress)
    end
    tell = on_progress === nothing ? line :
           line === nothing ? on_progress : (done, total) -> (line(done, total); on_progress(done, total))
    local res
    try
        sys = build_system(project)
        design = design_for(project, sys; seed, iterations, latin, varied, tornado, gsa)
        line === nothing || set_total!(line, design.iterations)
        res = _pb_run(project, sys, design, keep, range, tell, large, started, threads)
    catch
        line === nothing || close_line!(line; stopped=true)
        rethrow()
    end
    line === nothing || close_line!(line; failed=Int(get(res.stats, "failed", 0)))
    return res
end

"""
    run_tornado(m; low=0.05, high=0.95, kw...) -> ProbabilisticResults

Every varied input swung alone to a low and a high probability, the rest held
at their own values: two runs per input and one central run (run 1).
"""
run_tornado(m; low=0.05, high=0.95, kw...) = run_probabilistic(m, nothing; tornado=(low=low, high=high), kw...)

"""The realisations a run holds, `frm` to `to - 1` counted from 0: all of them, or those `range` numbers (from 1)."""
function _pb_slice(range, iterations::Int)
    range === nothing && return (0, iterations)
    frm = max(0, min(iterations - 1, Int(round(first(range))) - 1))
    to = max(frm + 1, min(iterations, Int(round(last(range)))))
    return (frm, to)
end

function _pb_run(project::Project, sys::System, design::SampleDesign, keep, range, on_progress, large::Bool,
                 started::Float64, threads::Integer)
    plan, iterations = design.plan, design.iterations
    frm, to = _pb_slice(range, iterations)
    span = to - frm
    samples = design.values[:, frm+1:to]
    eff = _pb_effective(design, frm, to)

    _pb_apply!(sys, design, eff, 1, frm)
    first_run = run_project(project; system=sys, on_grid=true)
    outs = outputs(first_run)
    label_index = _by_label(first_run)
    keep_fn = _pb_keep_fn(keep)
    wanted = Int[k for (k, o) in enumerate(outs) if can_be_endpoint(get(o, "kind", nothing)) &&
                                                     (keep_fn === nothing || keep_fn(_pb_keep_name(o), o))]
    column = Dict{Int,Int}()
    if !is_tornado(design)
        for (k, e) in enumerate(plan)
            design.varies[k] && (column[e["slot"]] = k)
        end
    end
    inputs = JDict[JDict("output" => o, "k" => column[o["offset"]]) for o in outs
                   if o["source"] == "P" && haskey(column, o["offset"])]
    grid = time_grid(project)
    times = length(grid)
    precision = hold_precision(length(wanted), times, iterations)
    size_ = estimate(length(wanted), times, iterations, precision)
    if size_.bytes > (large ? PROB_MOST_BYTES_ASKED : PROB_MOST_BYTES)
        what = is_tornado(design) ? "runs" : "realisations"
        fewer = is_tornado(design) ? "fewer inputs" : "fewer realisations"
        extra = precision == "float32" ? " even held as float32" : ""
        throw(ErrorException("$iterations $what of $(length(wanted)) series over $times times is $(size_.text)$extra; " *
                             "pass large=true to go ahead on a machine with the memory for it, or choose fewer " *
                             "endpoints, or $fewer."))
    end
    kept = outs[wanted]
    T = precision == "float32" ? Float32 : Float64
    values = [Matrix{T}(undef, span, times) for _ in wanted]
    _pb_take!(values, first_run, kept, 1, grid)
    first_run = nothing
    on_progress === nothing || on_progress(1, span)
    ran = ones(UInt8, span)
    ntasks, failures = _pb_parallel!(values, ran, project, sys, design, eff, frm, to, kept, outs, label_index, grid,
                                     on_progress, threads)
    stats = OrderedDict{String,Any}("failed" => length(failures),
                                    "trouble" => String["realisation $(i + 1): $msg" for (i, msg) in failures[1:min(5, end)]],
                                    "ms" => 1000 * (time() - started))
    merge!(stats, design.stats)
    stats["threads"] = max(1, ntasks)
    return ProbabilisticResults{T}(grid, kept, values, samples, plan, design.names, inputs, ran, iterations,
                                   frm+1:to, precision, stats, project)
end

"""
A copy of a built system for another thread (`clone_system`), its analytic
Jacobian's far-field plans pointed at the copy's own paths. `clone_jacobian`
shares the plans, and a far-field plan holds the path it refreshes: shared, the
copies would refresh the first system's paths with their own slots, from
several threads at once.
"""
function _pb_clone(sys::System)
    c = clone_system(sys)
    j = c.jacobian
    (j isa JacobianInfo && j.analytic !== nothing) || return c
    an = j.analytic
    farf(p) = p isa SpecialPlan && (p.kind === :farfield || p.kind === :laplace)
    any(farf, an.plans) || return c
    own(p) = c.data.FARF[p.entry[:farf_index]+1]
    an.plans = Any[farf(p) && p.path === sys.data.FARF[p.entry[:farf_index]+1] ?
                   SpecialPlan(p.kind, p.entry, own(p), p.dst) : p for p in an.plans]
    return c
end

"""
Realisations `frm + 1` to `to - 1` (from 0) shared out between threads, each on
a system of its own, taking the next realisation not yet taken as it finishes
one. Returns how many threads ran and the failures, by realisation.
"""
function _pb_parallel!(values::Vector{Matrix{T}}, ran::Vector{UInt8}, project::Project, sys::System,
                       design::SampleDesign, eff::Matrix{Float64}, frm::Int, to::Int, kept::Vector{JDict},
                       outs::Vector{JDict}, label_index, grid::Vector{Float64}, on_progress,
                       threads::Integer) where {T}
    failures = Tuple{Int,String}[]
    rest = to - frm - 1
    rest <= 0 && return (0, failures)
    span = to - frm
    ntasks = clamp(min(Int(threads), Threads.nthreads()), 1, rest)
    next = Threads.Atomic{Int}(frm + 1)
    stop = Threads.Atomic{Bool}(false)
    progress_lock = ReentrantLock()
    done = Ref(1)
    systems = System[sys]
    for _ in 2:ntasks
        push!(systems, _pb_clone(sys))
    end
    function work(s::System)
        while !stop[]
            i = Threads.atomic_add!(next, 1)
            i >= to && break
            row = i - frm + 1
            _pb_apply!(s, design, eff, row, i)
            message = nothing
            try
                r = run_project(project; system=s, on_grid=true)
                r.outputs_cache = outs
                r.label_index = label_index
                _pb_take!(values, r, kept, row, grid)
            catch e
                e isa InterruptException && rethrow()
                message = sprint(showerror, e)
            end
            if message !== nothing
                ran[row] = 0x00
                for M in values
                    M[row, :] .= T(NaN)
                end
            end
            lock(progress_lock) do
                message === nothing || push!(failures, (i, message))
                done[] += 1
                on_progress === nothing || on_progress(done[], span)
            end
        end
        return nothing
    end
    tasks = [Threads.@spawn begin
                 try
                     work($s)
                 catch e
                     stop[] = true
                     e
                 end
             end for s in systems]
    local errors
    try
        errors = [fetch(t) for t in tasks]
    catch
        # Interrupted while waiting: the threads finish the realisation each is on, and stop.
        stop[] = true
        foreach(t -> try wait(t) catch end, tasks)
        rethrow()
    end
    for e in errors
        e === nothing || throw(e)
    end
    sort!(failures; by=first)
    return (ntasks, failures)
end

"""
    run_realisation(m, number; seed=1, iterations=100, latin=true, varied=nothing, tornado=nothing)

One realisation of a probabilistic run (`number` from 1), as an ordinary run:
`(results, number, iterations, values)`, `values` each input's
`(name, value, held)`. A fresh system, so an input whose draw is not a number
keeps the model's own value.
"""
function run_realisation(m, number::Integer; seed=1, iterations=nothing, latin::Bool=true, varied=nothing,
                         tornado=nothing)
    proj = m isa Project ? m : project(m)
    sys = build_system(proj)
    design = design_for(proj, sys; seed, iterations, latin, varied, tornado)
    i = min(design.iterations - 1, max(0, Int(number) - 1))
    eff = _pb_effective(design, i, i + 1)
    _pb_apply!(sys, design, eff, 1, i)
    results = run_project(proj; system=sys)
    tor = is_tornado(design)
    values = [(name=design.names[k], value=design.values[k, i+1],
               held=!design.varies[k] || (tor && design.values[k, i+1] == design.best[k]))
              for k in eachindex(design.plan)]
    return (results=results, number=i + 1, iterations=design.iterations, values=values)
end

"""
    save(prob::ProbabilisticResults, path; want="all", time_origin=0.0, kwargs...) -> path

Writes a probabilistic run as the HDF5 result file the application's *Save →
Realisations* writes: every realisation (`want="all"`, float32), their mean
(`"mean"`) or one realisation by number (from 1). `time_origin` is subtracted
from the file's `/time` and nothing else. The other keyword arguments are
`probabilistic_tree`'s; the model named in the file is the run's own unless
`project=` says otherwise.
"""
function save(prob::ProbabilisticResults, path::AbstractString; want="all", time_origin::Real=0.0, kwargs...)
    tree = probabilistic_tree(prob, want; kwargs...)
    if time_origin != 0
        stamp = tree.children["time"]
        stamp.data = Float64.(stamp.data) .- Float64(time_origin)
    end
    write(path, write_hdf5(tree))
    return path
end

# --- a line that says how far a long run has got -----------------------------------------------

"""
A progress line (the Python package's `ProgressLine`):

    Probabilistic run [#########---------------] 380/1000 realisations  38%  0:41, about 1:07 left

redrawn in place on a terminal, at most ten times a second, and written as a
line per tenth of the way elsewhere. The time left is the pace since the first
run finished, which also built the model.
"""
mutable struct ProgressLine
    total::Int
    what::String
    title::String
    io::IO
    in_place::Bool
    started::Float64
    done::Int
    first_at::Float64
    first_done::Int
    drawn::Float64
    width::Int
    tenth::Int
    closed::Bool
end

const _PL_BAR = 24
const _PL_REDRAW = 0.1

function ProgressLine(total::Integer; what="realisations", title="Probabilistic run", io::IO=stderr)
    line = ProgressLine(max(0, Int(total)), String(what), String(title), io, io isa Base.TTY, time(), 0, NaN, 0, 0.0,
                        0, 0, false)
    _pl_draw!(line)
    return line
end

"""`m:ss`, or `h:mm:ss` from an hour."""
function progress_clock(seconds::Real)
    s = max(0, round(Int, seconds))
    h, s = divrem(s, 3600)
    m, s = divrem(s, 60)
    return h > 0 ? @sprintf("%d:%02d:%02d", h, m, s) : @sprintf("%d:%02d", m, s)
end

function _pl_left(line::ProgressLine)
    (isnan(line.first_at) || line.done <= line.first_done || line.done >= line.total) && return nothing
    pace = (time() - line.first_at) / (line.done - line.first_done)
    return pace * (line.total - line.done)
end

function _pl_text(line::ProgressLine)
    n, total = line.done, line.total
    share = total > 0 ? n / total : 1.0
    fill = round(Int, _PL_BAR * share)
    text = "$(line.title) [$("#"^fill)$("-"^(_PL_BAR - fill))] $n/$total $(line.what) " *
           @sprintf("%3.0f%%", 100 * share) * "  $(progress_clock(time() - line.started))"
    left = _pl_left(line)
    return left === nothing ? text : "$text, about $(progress_clock(left)) left"
end

function _pl_write(line::ProgressLine, text::AbstractString)
    try
        print(line.io, text)
        flush(line.io)
    catch
    end
end

function _pl_draw!(line::ProgressLine)
    text = _pl_text(line)
    if line.in_place
        _pl_write(line, "\r" * text * " "^max(0, line.width - length(text)))
        line.width = length(text)
        line.drawn = time()
    elseif line.done == 0
        _pl_write(line, text * "\n")
    end
end

function set_total!(line::ProgressLine, total::Integer)
    line.total = max(0, Int(total))
    (line.in_place && !line.closed) && _pl_draw!(line)
    return line
end

function (line::ProgressLine)(done::Integer, total=nothing)
    line.closed && return
    total === nothing || (line.total = max(0, Int(total)))
    done = Int(done)
    done <= line.done && return
    now = time()
    if isnan(line.first_at)
        line.first_at = now
        line.first_done = done
    end
    line.done = done
    if line.in_place
        (now - line.drawn >= _PL_REDRAW || done >= line.total) && _pl_draw!(line)
        return
    end
    tenth = line.total > 0 ? (10 * done) ÷ line.total : 10
    if line.tenth < tenth < 10
        line.tenth = tenth
        _pl_write(line, _pl_text(line) * "\n")
    end
    return
end

function close_line!(line::ProgressLine; failed::Integer=0, stopped::Bool=false)
    line.closed && return
    line.closed = true
    took = progress_clock(time() - line.started)
    text = stopped ? "$(line.title) stopped after $(line.done) of $(line.total) $(line.what), $took" :
           "$(line.title): $(line.total) $(line.what) in $took" * (failed > 0 ? ", $failed failed" : "")
    if line.in_place
        _pl_write(line, "\r" * text * " "^max(0, line.width - length(text)) * "\n")
    else
        _pl_write(line, text * "\n")
    end
end
