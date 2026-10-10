# Solving a model in its independent parts, side by side (src/sim/partition.js
# and src/sim/split.js, as the Python engine's partition.py and split.py port
# them).
#
# A large assessment is rarely one problem: its radionuclides fall into groups
# with no path between them -- each decay chain held together by its own
# ingrowth and nothing joining one chain to the next -- and solved as one
# system every state moves at the step size the worst of them needs. The
# partition finds those groups from the Jacobian's pattern; the plan decides
# whether solving them apart pays for the model in hand; the run packs the
# *jobs* -- sets of materials whose states reach no other job's -- into one bin
# per thread, builds each bin (the model with every other material switched
# off) and solves it on the model's output grid at its own steps, and files
# every state back into the whole model's vector by name. What comes out is
# an ordinary `Results` of the whole model whose states were integrated in
# pieces, worked out afterwards on the whole model's system.
#
# **Not bit for bit the whole model's.** Each bin takes the steps its own
# states need, which is the point, and so agrees with the whole to within the
# tolerance. The jobs of one bin share its steps, so how they are packed --
# which follows the number of threads -- changes the last digits; a bin is the
# same run on whichever thread takes it, and the Python package's run of it to
# the bit.
#
# **Threads, not processes.** The Python package starts a process per bin;
# here a bin is a task, so a part starts at once and nothing is sent back.
# The parts share the process's memory and its garbage collector, though, and
# a bin's build allocates: builds side by side are slower than one alone. The
# numbers auto weighs a split by are this engine's own (`SPLIT_CONSTANTS`).
#
# **Refused, whatever the setting, where it would be wrong or cannot work:** a
# model the partition declines (a delay, a snapshot or an event reaches across
# parts without showing in the Jacobian; a far-field path worked out
# semi-analytically); output at the solver's own steps, which differ in every
# part; a model with no materials to divide by; one part holding everything;
# one thread; a run that is itself one of several side by side; and, as the
# Python package refuses it, a min/max whose target reads states of more than
# one job, which no part can give back.
#
# **Carried back:** besides the states, each part's run leaves its recorders'
# histories; a min/max or running mean is taken from the job that owns the
# states its target reads, and put on the whole system, so their series are
# the run's. The far-field paths' matched layers are the whole model's: a part
# alone would size them by its own nuclides and solve another path.
#
# Parts, jobs and bins are numbered from 0 here, as the application and the
# Python package number them; states are Julia's, from 1.

# --- the partition ---------------------------------------------------------------------------

"""
    state_partition(pattern) -> (count, of, sizes, largest)

The states of each part, from a sparsity pattern (`statePartition`): two
states belong together when one reads the other, in either direction.
`of[i]` is the part state `i` belongs to, numbered from 0 in the order the
states first appear, so part 0 holds state 1 -- a property of the model, not
of how the components were found.
"""
function state_partition(pattern)
    n = pattern === nothing ? 0 : Int(pattern.n)
    n == 0 && return (count=0, of=Int[], sizes=Int[], largest=0)
    parent = collect(1:n)
    function root(x)
        while parent[x] != x
            parent[x] = parent[parent[x]]
            x = parent[x]
        end
        return x
    end
    @inbounds for j in 1:n, p in pattern.colptr[j]:pattern.colptr[j+1]-1
        a = root(pattern.rowval[p])
        b = root(j)
        a == b && continue
        a < b ? (parent[b] = a) : (parent[a] = b)
    end
    number = zeros(Int, n)
    of = Vector{Int}(undef, n)
    count = 0
    for i in 1:n
        r = root(i)
        number[r] == 0 && (count += 1; number[r] = count)
        of[i] = number[r] - 1
    end
    sizes = zeros(Int, count)
    for i in 1:n
        sizes[of[i]+1] += 1
    end
    return (count=count, of=of, sizes=sizes, largest=maximum(sizes))
end

#: The blocks whose dependency the Jacobian's pattern deliberately leaves out.
const SPLIT_UNSEEN = Dict(
    "delay" => "a delay reports the past, which no present state can move, so the Jacobian gives it no column and " *
               "a dependency through it is invisible to this partition",
    "snapshot" => "a snapshot reports the past, which no present state can move, so the Jacobian gives it no column " *
                  "and a dependency through it is invisible to this partition",
    "trigger" => "an event moves a state its condition never mentions, which is not a derivative and so is not in " *
                 "the Jacobian",
)

"""
Why this system may not be split, or `nothing` when it may (`whyNotSplit`). It
names the first thing it cannot account for rather than guessing.
"""
function why_not_split(sys::System)
    j = sys.jacobian
    (j !== nothing && getproperty(j, :available) === true) ||
        return "the model has no analytic Jacobian, so there is no sparsity pattern to read the parts off"
    (j.pattern === nothing || j.pattern.n == 0) && return "the model has no states to split"
    for rec in sys.recorders
        why = get(SPLIT_UNSEEN, rec.kind, nothing)
        why === nothing || return "'$(rec.name)' is a $(replace(rec.kind, "_" => " ")): $why"
    end
    # A semi-analytical path's release is a convolution over what flowed into it during the
    # run, and the series of a split run are worked out afterwards on the whole model's
    # system, which never saw that history.
    for p in sys.builder.farf_layout
        p[:farf].laplace && return "'$(p.name)' is worked out semi-analytically: its release is a convolution over " *
                                   "what flowed into it during the run, which the whole model the series are worked " *
                                   "out on afterwards does not have"
    end
    n = length(sys.event_slots)
    if n > 0
        many = n == 1 ? "an event" : "$n events"
        return "the model has $many, and an event moves a state its condition never mentions, which is not a " *
               "derivative and so is not in the Jacobian"
    end
    return nothing
end

"""The partition, with the reason when there is not one (`partitionOf`)."""
function partition_of(sys::System)
    refusal = why_not_split(sys)
    refusal === nothing || return (ok=false, refusal=refusal, count=1, of=nothing, sizes=nothing, largest=0)
    p = state_partition(sys.jacobian.pattern)
    return (ok=true, refusal=nothing, count=p.count, of=p.of, sizes=p.sizes, largest=p.largest)
end

# --- names and materials of the states ----------------------------------------------------------

"""
    state_keys(sys) -> Vector{String} or nothing

A name for each state that is the same for the same state in any build of the
model, whichever materials that build has (`stateKeys`): the block, its
index, and for a far-field path the cell; a mass-balance budget by its term
and family. `nothing` when two states come out with one name.
"""
function state_keys(sys::System)
    b = sys.builder
    space = b.space
    keys = Vector{Union{Nothing,String}}(nothing, sys.nstate)
    for entry in b.states
        kind = entry.kind
        farf = get(entry, :farf, nothing)
        if kind == "farfield" && farf !== nothing
            names = farf.list_name === nothing ? Union{Nothing,String}[nothing] : index_names(space, farf.list_name)
            for o in 0:farf.other_width-1
                others = isempty(farf.other_dims) ? String[] : tuple_at(space, farf.other_dims, o)
                base = entry.base + o * farf.ncells * farf.nnuc
                for m in 0:farf.nnuc-1
                    index = Union{Nothing,String}[]
                    k = 1
                    for dim in entry.dims
                        if dim == farf.list_name
                            push!(index, names[m+1])
                        else
                            push!(index, others[k])
                            k += 1
                        end
                    end
                    joined = join((v === nothing ? "" : v for v in index), ",")
                    for cell in 0:farf.ncells-1
                        keys[base+cell*farf.nnuc+m+1] = "$kind:$(entry.name)[$joined]#$cell"
                    end
                end
            end
            continue
        end
        budget = get(entry, :budget, nothing)
        if kind == "budget" && budget !== nothing
            for (t, term) in enumerate(budget.terms), f in 1:budget.nfam
                keys[entry.base+(t-1)*budget.nfam+f] = "budget:$term:$(budget.families[f])"
            end
            continue
        end
        for off in 0:entry.width-1
            index = isempty(entry.dims) ? String[] : tuple_at(space, entry.dims, off)
            keys[entry.base+off+1] = "$kind:$(entry.name)[$(join(index, ","))]"
        end
    end
    seen = Set{String}()
    for k in keys
        (k === nothing || k in seen) && return nothing
        push!(seen, k)
    end
    return Vector{String}(keys)
end

"""The material each state belongs to, or `nothing` for one that is not per material (`stateMaterials`)."""
function state_materials(sys::System)
    b = sys.builder
    space = b.space
    out = Vector{Union{Nothing,String}}(nothing, sys.nstate)
    for entry in b.states
        farf = get(entry, :farf, nothing)
        if entry.kind == "farfield" && farf !== nothing
            farf.list_name === nothing && continue
            names = index_names(space, farf.list_name)
            for o in 0:farf.other_width-1
                base = entry.base + o * farf.ncells * farf.nnuc
                for m in 0:farf.nnuc-1, cell in 0:farf.ncells-1
                    out[base+cell*farf.nnuc+m+1] = names[m+1]
                end
            end
            continue
        end
        budget = get(entry, :budget, nothing)
        if entry.kind == "budget" && budget !== nothing
            for t in 1:length(budget.terms), f in 1:budget.nfam
                family = budget.families[f]
                out[entry.base+(t-1)*budget.nfam+f] = family == UNINDEXED ? nothing : family
            end
            continue
        end
        d = _material_dim(sys, entry.dims)
        d === nothing && continue
        at = findfirst(==(d), entry.dims)
        for off in 0:entry.width-1
            out[entry.base+off+1] = tuple_at(space, entry.dims, off)[at]
        end
    end
    return out
end

# --- the jobs ----------------------------------------------------------------------------------

"""Materials whose states reach no other job's, and how many states they own."""
struct SplitJob
    materials::Vector{String}
    states::Int
end

Base.:(==)(a::SplitJob, b::SplitJob) = a.materials == b.materials && a.states == b.states

_no_jobs(why::String) = (why=why, jobs=SplitJob[], owner=Int[], keys=String[], parts=0,
                         recorders=Tuple{String,Int,Int}[])

"""
For every entry of a recorder that remembers (a min/max, a running mean):
`(key, job, slot)` -- its name, the job whose states its target reads, and its
place in the whole system's histories (from 0) -- or the refusal, when those
states are in more than one job and no part can give it back.
"""
function _recorder_owners(sys::System, owner::Vector{Int}, smallest::Int)
    out = Tuple{String,Int,Int}[]
    remembering = [r for r in sys.recorders if r.kind in ("min_max", "running_mean") && r[:mem] >= 0]
    isempty(remembering) && return out
    deps = state_dependencies(sys)
    space = sys.builder.space
    for rec in remembering
        target = rec[:aux]["target"]
        for off in 0:rec.width-1
            reads = get(deps, target.base + off, Int[])
            jobs = sort!(unique!([owner[s+1] for s in reads]))
            length(jobs) > 1 &&
                return "'$(rec.name)' remembers a value read from more than one part, so no part can give it back"
            index = isempty(rec.dims) ? String[] : tuple_at(space, rec.dims, off)
            push!(out, ("$(rec.kind):$(rec.name)[$(join(index, ","))]", isempty(jobs) ? smallest : jobs[1],
                        rec[:mem] + off))
        end
    end
    return out
end

"""
    split_jobs(sys) -> (why, jobs, owner, keys, parts, recorders)

The jobs a model's parts make: sets of materials, each with the states it
owns (`splitJobs`). `why` is the refusal, `nothing` when there are jobs.

A job is built by switching every other material off, so parts that share a
material are merged. A part with no material at all is in every job's build
and is taken from whichever job is smallest.
"""
function split_jobs(sys::System)
    part = partition_of(sys)
    part.ok || return _no_jobs(part.refusal)
    b = sys.builder
    b.material_list === nothing && return _no_jobs("the model has no materials to divide it by")
    part.count < 2 && return _no_jobs("the model is one part: every state can reach every other")
    keys = state_keys(sys)
    keys === nothing && return _no_jobs("two states of the model share a name, so a part could not be filed back by it")
    materials = state_materials(sys)
    n = sys.nstate
    of = part.of
    count = part.count

    # Parts that share a material are one job.
    parent = collect(0:count-1)
    function find(x)
        while parent[x+1] != x
            parent[x+1] = parent[parent[x+1]+1]
            x = parent[x+1]
        end
        return x
    end
    first_part = Dict{String,Int}()
    for i in 1:n
        m = materials[i]
        m === nothing && continue
        p = of[i]
        was = get(first_part, m, nothing)
        if was === nothing
            first_part[m] = p
        elseif find(was) != find(p)
            parent[find(p)+1] = find(was)
        end
    end
    # The groups with a material, numbered in the order they first appear.
    job_of = fill(-1, count)
    names = Vector{String}[]
    seen = Set{String}[]
    owned = Int[]
    carries = falses(count)
    for i in 1:n
        materials[i] === nothing || (carries[of[i]+1] = true)
    end
    for p in 0:count-1
        carries[p+1] || continue
        r = find(p)
        if job_of[r+1] < 0
            job_of[r+1] = length(names)
            push!(names, String[])
            push!(seen, Set{String}())
            push!(owned, 0)
        end
        job_of[p+1] = job_of[r+1]
    end
    length(names) < 2 && return _no_jobs("every part shares a material with another, so the model builds as one job")
    owner = zeros(Int, n)
    for i in 1:n
        j = job_of[find(of[i])+1]
        owner[i] = j
        j < 0 && continue
        owned[j+1] += 1
        m = materials[i]
        if m !== nothing && !(m in seen[j+1])
            push!(seen[j+1], m)
            push!(names[j+1], m)
        end
    end
    # The parts with no material go to the smallest job, which every build holds them anyway.
    smallest = 0
    for k in 0:length(names)-1
        owned[k+1] < owned[smallest+1] && (smallest = k)
    end
    for i in 1:n
        if owner[i] < 0
            owner[i] = smallest
            owned[smallest+1] += 1
        end
    end
    # A material the model has but no state carries rides with the smallest job, so that
    # every material is switched on somewhere.
    placed = Set{String}(m for ms in names for m in ms)
    for m in index_names(b.space, b.material_list)
        if !(m in placed)
            push!(names[smallest+1], m)
            push!(seen[smallest+1], m)
        end
    end
    recorders = _recorder_owners(sys, owner, smallest)
    recorders isa String && return _no_jobs(recorders)
    return (why=nothing, jobs=[SplitJob(names[k], owned[k]) for k in eachindex(names)], owner=owner, keys=keys,
            parts=count, recorders=recorders)
end

# --- the plan --------------------------------------------------------------------------------

"""
    SplitConstants(; shared_work, auto_states, auto_solve_ms, auto_gain, auto_gain_untimed, start_ms,
                   build_fixed, build_contention, untimed_bins)

The numbers auto weighs a split by: the application's formulas, with what
this engine measured (`SPLIT_CONSTANTS`). `SplitConstants()` holds the Python
package's, under which a plan is the Python package's plan.

- `shared_work`: the share of a whole derivative call every part pays
  whatever its size -- the solver's own work per step.
- `auto_states`: auto splits a model it has not timed only from this many
  states up.
- `auto_solve_ms`: auto splits a model it has timed only when a whole solve
  took this long.
- `auto_gain`: how much faster auto wants the split to be expected, or
  measured, to be; `auto_gain_untimed` the same for a model whose solve time
  is not known yet.
- `start_ms`: what a split costs once per run beyond its bins' builds and
  solves.
- `build_fixed`: the share of a whole build each bin pays whatever it holds,
  until a split of the model has measured it; `nothing` takes a bin's build
  to shrink with its share of the states, as the Python package does.
- `build_contention`: how much longer every bin's build takes for each other
  bin built at the same time -- they share the process: its allocator, its
  collector, its compiler. Above zero, auto weighs every number of bins up to
  one per thread and takes the quickest; at zero, one bin per thread.
- `untimed_bins`: the most bins auto packs a model into before a run of it
  has been timed (0: one per thread).
"""
Base.@kwdef struct SplitConstants
    shared_work::Float64 = 0.1
    auto_states::Int = 10000
    auto_solve_ms::Float64 = 1500.0
    auto_gain::Float64 = 1.2
    auto_gain_untimed::Float64 = 2.0
    start_ms::Float64 = 650.0
    build_fixed::Union{Nothing,Float64} = nothing
    build_contention::Float64 = 0.0
    untimed_bins::Int = 0
end

#: This engine's, measured on made-up models of independent decay chains (2,880 to 28,800
#: states) and on a large assessment, on 2 to 8 threads of a 10-core machine:
#: a bin's solve follows its share of the states nearly in proportion; a bin's build does not
#: shrink -- it is mostly the model's structure and its compiled code -- and builds side by
#: side slow each other down; and a split starts in milliseconds, where a process takes most
#: of a second.
const SPLIT_CONSTANTS = SplitConstants(shared_work=0.05, auto_states=10000, auto_solve_ms=250.0, auto_gain=1.2,
                                       auto_gain_untimed=2.0, start_ms=25.0, build_fixed=1.0, build_contention=0.3,
                                       untimed_bins=4)

"""A job's share of a whole derivative call, from its share of the states."""
job_cost(states::Real, total::Real, c::SplitConstants=SPLIT_CONSTANTS) =
    c.shared_work + (1 - c.shared_work) * (total > 0 ? states / total : 1.0)

"""
    pack_jobs(costs, workers) -> bins

Jobs into `workers` bins, largest first into the least loaded: the
longest-processing-time rule (`packJobs`). Each bin lists its jobs (from 0).
"""
function pack_jobs(costs::AbstractVector{<:Real}, workers::Integer)
    n = max(1, min(Int(workers), length(costs)))
    load = zeros(n)
    bins = [Int[] for _ in 1:n]
    order = sort(collect(0:length(costs)-1); by=i -> (-Float64(costs[i+1]), i))
    for j in order
        k = 1
        for b in 2:n
            load[b] < load[k] && (k = b)
        end
        load[k] += costs[j+1]
        push!(bins[k], j)
    end
    return [sort(b) for b in bins]
end

"""
Whether to split a run, and how (`planSplit`); and, once one has run, what
it did. `use` says whether to; `why` says why, in the application's words.
"""
mutable struct SplitPlan
    use::Bool
    mode::String
    why::String
    predicted::Union{Nothing,Float64}
    jobs::Vector{SplitJob}
    owner::Vector{Int}                       # per state: its job (from 0)
    keys::Vector{String}
    bins::Vector{Vector{Int}}                # per bin: its jobs (from 0)
    parts::Int
    recorders::Vector{Tuple{String,Int,Int}}
    # What a run of it did: a line per bin, its wall time and its gain.
    ran::Vector{OrderedDict{String,Any}}
    wall_ms::Float64
    gain::Union{Nothing,Float64}
end

_no_split(mode, why, predicted=nothing) =
    SplitPlan(false, mode, why, predicted, SplitJob[], Int[], String[], Vector{Int}[], 0, Tuple{String,Int,Int}[],
              OrderedDict{String,Any}[], 0.0, nothing)

_js_round_int(x::Real) = floor(Int, x + 0.5)

"""`n` with a comma between thousands, as Python's `f'{n:,}'` writes it."""
function _with_commas(n::Integer)
    s = string(abs(n))
    io = IOBuffer()
    for (i, ch) in enumerate(s)
        (i > 1 && (length(s) - i + 1) % 3 == 0) && write(io, ',')
        write(io, ch)
    end
    return (n < 0 ? "-" : "") * String(take!(io))
end

_known_value(known, key) = known === nothing ? nothing :
                           (v = get(known, key, nothing); v isa Real && !(v isa Bool) ? Float64(v) : nothing)

"""
    plan_split(sys, project; mode="auto", workers=1, nest=true, build_ms=0, known=nothing,
               on_grid=false, constants=SPLIT_CONSTANTS) -> SplitPlan

Whether to split this run, and how (`planSplit`). The jobs are packed by their
states into bins, as the application packs them, and a bin is built once:
one bin per thread (`workers`) when the split is asked for, and as many as
auto expects to be quickest otherwise (see `SplitConstants`). The prediction
is the application's cost model: each bin costs its share of the whole
model's build and of its solve, the bins run side by side, and a split costs
`start_ms` once. `known` is what earlier runs of this layout measured here
(`"solve_ms"`, `"gain"`, `"build_fixed"`, `"bins"`); without it the ratio is
judged on the model's shape alone, with a larger margin and only for a large
model. `build_ms` is the whole model's build. `nest=false` is a run that is
itself one of several side by side, which is not split.
"""
function plan_split(sys::System, project::Project; mode="auto", workers::Real=1, nest::Bool=true,
                    build_ms::Real=0.0, known=nothing, on_grid::Bool=false,
                    constants::SplitConstants=SPLIT_CONSTANTS)
    c = constants
    m = mode in ("on", "off") ? String(mode) : "auto"
    m == "off" && return _no_split(m, "switched off")
    sys.nstate == 0 && return _no_split(m, "the model has nothing to integrate")
    (!on_grid && project.output_mode != "grid") &&
        return _no_split(m, "the results are reported at the solver’s own steps, which would be different in every part")
    nest || return _no_split(m, "this run is itself one of several side by side, which do not start more")
    found = split_jobs(sys)
    found.why === nothing || return _no_split(m, found.why)
    n = sys.nstate
    cores = max(1, floor(Int, workers))
    cores < 2 && return _no_split(m, "there is one thread to run on: start Julia with more (julia --threads=auto)")
    # Packed by states: a bin is one build, so the work every part repeats is paid once per
    # bin whatever it holds.
    states = [j.states for j in found.jobs]
    function packed(k)
        bins = pack_jobs(states, k)
        return (bins=bins, states=[sum((states[j+1] for j in b); init=0) for b in bins])
    end
    choice = packed(cores)
    plan = SplitPlan(true, m, "", nothing, found.jobs, found.owner, found.keys, choice.bins, found.parts,
                     found.recorders, OrderedDict{String,Any}[], 0.0, nothing)
    size = "$(length(found.jobs)) parts, the largest $(_js_round_int(100 * maximum(states) / n))% of the states"
    if m == "on"
        plan.why = "asked for: $size, on $(length(choice.bins)) cores"
        return plan
    end
    # Auto: what a split is expected to gain over a whole solve of S ms, packed as `p` is.
    S = _known_value(known, "solve_ms")
    timed = S !== nothing && isfinite(S)
    B = max(0.0, Float64(build_ms))
    fixed = something(_known_value(known, "build_fixed"), c.build_fixed, Some(nothing))
    function expected(p)
        if fixed === nothing
            load = maximum(job_cost(s, n, c) for s in p.states)
            return S / (load * (B + S) + c.start_ms)
        end
        # The part of a build that does not shrink with the part, as a split of this model
        # measured it or as this engine takes it; slower for every bin built beside it.
        slower = 1 + c.build_contention * (length(p.bins) - 1)
        return S / (maximum(B * (fixed + (1 - fixed) * s / n) * slower + S * job_cost(s, n, c) for s in p.states) +
                    c.start_ms)
    end
    if timed && c.build_contention > 0
        best = -Inf
        for k in 2:min(cores, length(states))
            p = packed(k)
            e = expected(p)
            e > best && ((best, choice) = (e, p))
        end
    end
    # A split this model has had, measured, decides.
    gain = _known_value(known, "gain")
    if gain !== nothing
        gain < c.auto_gain &&
            return _no_split(m, "split, it was measured at $(js_to_fixed(gain, 1))×, which is not enough to be worth it")
        bins = _known_value(known, "bins")
        (!timed && c.build_contention > 0 && bins !== nothing) && (choice = packed(clamp(Int(bins), 2, cores)))
        plan.bins = choice.bins
        plan.predicted = gain
        plan.why = "$size; measured at $(js_to_fixed(gain, 1))× the last time, on $(length(choice.bins)) cores"
        return plan
    end
    if timed
        predicted = expected(choice)
        S < c.auto_solve_ms &&
            return _no_split(m, "a whole solve takes $(_js_round_int(S)) ms, too short to be worth dividing", predicted)
        predicted < c.auto_gain &&
            return _no_split(m, "$size; expected $(js_to_fixed(predicted, 1))× on $(length(choice.bins)) cores, not enough",
                             predicted)
        plan.bins = choice.bins
        plan.predicted = predicted
        plan.why = "$size; expected $(js_to_fixed(predicted, 1))× faster on $(length(choice.bins)) cores"
        return plan
    end
    c.untimed_bins > 0 && (choice = packed(min(cores, c.untimed_bins)))
    shape = 1 / maximum(job_cost(s, n, c) for s in choice.states)
    n < c.auto_states &&
        return _no_split(m, "$(_with_commas(n)) states, too few to be worth dividing before a run has been timed", shape)
    shape < c.auto_gain_untimed &&
        return _no_split(m, "$size; at most $(js_to_fixed(shape, 1))× on $(length(choice.bins)) cores, not enough", shape)
    plan.bins = choice.bins
    plan.predicted = shape
    plan.why = "$size; up to $(js_to_fixed(shape, 1))× faster on $(length(choice.bins)) cores"
    return plan
end

"""
    bin_jobs(plan) -> (jobs, owner, recorders)

The plan's bins as the jobs the threads are given (`binJobs`): one per bin,
its jobs' materials together, built once however many of the model's parts it
holds -- with which of the whole model's states each files (`owner`, by bin)
and which recorders' histories each gives back (`recorders`, by bin).
"""
function bin_jobs(plan::SplitPlan)
    bin_of = zeros(Int, length(plan.jobs))
    for (b, members) in enumerate(plan.bins), j in members
        bin_of[j+1] = b - 1
    end
    jobs = [SplitJob(String[m for j in members for m in plan.jobs[j+1].materials],
                     sum((plan.jobs[j+1].states for j in members); init=0)) for members in plan.bins]
    owner = [bin_of[o+1] for o in plan.owner]
    recorders = Tuple{String,Int,Int}[(key, bin_of[job+1], slot) for (key, job, slot) in plan.recorders]
    return (jobs=jobs, owner=owner, recorders=recorders)
end

# --- one bin's model ------------------------------------------------------------------------------

_is_material_list(lst) = py_truthy(get(lst, "for_contaminants", nothing)) || py_truthy(get(lst, "for_nuclides", nothing))
_index_name(i) = i isa AbstractString ? String(i) : (i isa AbstractDict ? get(i, "name", nothing) : nothing)

"""The model as one job builds it: every material switched off but its own (`partModel`)."""
function part_model(model::AbstractDict, keep; copy_it::Bool=true)
    out = copy_it ? jcopy(model) : model
    want = Set{String}(keep)
    for lst in something(get(out, "index_lists", nothing), Any[])
        _is_material_list(lst) || continue
        indices = Any[]
        for i in something(get(lst, "indices", nothing), Any[])
            idx = i isa AbstractString ? JDict("name" => String(i), "enabled" => true) : JDict(i)
            get(idx, "name", nothing) in want || (idx["enabled"] = false)
            push!(indices, idx)
        end
        lst["indices"] = indices
    end
    nuclides = get(out, "nuclides", nothing)
    nuclides isa AbstractVector && (out["nuclides"] = Any[n for n in nuclides if n in want])
    return out
end

function _is_material_index(model::AbstractDict, name)
    for lst in something(get(model, "index_lists", nothing), Any[])
        _is_material_list(lst) || continue
        any(i -> _index_name(i) == name, something(get(lst, "indices", nothing), Any[])) && return true
    end
    return false
end

function _switch_on(model::AbstractDict, name::String)
    out = jcopy(model)
    for lst in something(get(out, "index_lists", nothing), Any[])
        _is_material_list(lst) || continue
        for i in something(get(lst, "indices", nothing), Any[])
            (i isa AbstractDict && get(i, "name", nothing) == name) && (i["enabled"] = true)
        end
    end
    nuclides = get(out, "nuclides", nothing)
    if nuclides isa AbstractVector && !(name in nuclides)
        catalogue = findfirst_value(l -> py_truthy(get(l, "for_contaminants", nothing)),
                                    something(get(out, "index_lists", nothing), Any[]))
        order = catalogue === nothing ? Any[] :
                Any[_index_name(i) for i in something(get(catalogue, "indices", nothing), Any[])]
        on = Set{Any}(nuclides)
        push!(on, name)
        out["nuclides"] = Any[n for n in order if n in on]
    end
    return out
end

const _SPLIT_PINNED = r"'([^']+)' is disabled in '([^']+)'"

_split_error_text(e) = e isa Exception && hasproperty(e, :message) ? string(getproperty(e, :message)) :
                       sprint(showerror, e)

"""
    build_part(model) -> (project, system, pinned)

A job's model, built, switching back on any material its equations name
outright -- `k[C-14]` -- and trying again (`buildPart`).
"""
function build_part(model::AbstractDict)
    pinned = String[]
    current = model
    while true
        try
            project = Project(current)
            return (project=project, system=build_system(project), pinned=pinned)
        catch e
            found = match(_SPLIT_PINNED, _split_error_text(e))
            (found === nothing || found.captures[1] in pinned || !_is_material_index(current, found.captures[1])) &&
                rethrow()
            push!(pinned, found.captures[1])
            current = _switch_on(current, String(found.captures[1]))
        end
    end
end

"""Where a job's states go in the whole model's vector (`placeStates`): `(from, to)`, for the states the job owns."""
function place_states(whole::Dict{String,Int}, keys::AbstractVector{<:AbstractString}, owner::Vector{Int}, job::Int)
    frm = Int[]
    to = Int[]
    for (k, key) in enumerate(keys)
        i = get(whole, key, 0)
        (i == 0 || owner[i] != job) && continue
        push!(frm, k)
        push!(to, i)
    end
    return frm, to
end

# --- the far-field paths' layers --------------------------------------------------------------------

"""A combination of a path's other dimensions as one name (`layerKey`): its index names joined by NUL."""
layer_key(space::IndexSpace, dims, o::Integer) = isempty(dims) ? "" : join(tuple_at(space, dims, o), '\0')

"""
    whole_layers(sys, project) -> Dict or nothing

The far-field paths' matched layers as a run of the whole model lays them
out at its first instant, for a split run's parts to hold (`wholeLayers`): by
path name, then by combination of the path's other dimensions (`layer_key`),
each `(d, h, q)`; `nothing` for a model with no matched layers. A part holds
only its own materials, and left to itself would size a path's layers by
those alone -- another path than the whole model's.
"""
function whole_layers(sys::System, project::Project)
    b = sys.builder
    paths = [p for p in b.farf_layout if (F = sys.data.FARF[p[:farf_index]+1]; F isa FarfPath && F.matched)]
    isempty(paths) && return nothing
    t0 = Float64(project.simulation["start_time"])
    y = initial_state(sys)
    prime_recorders!(sys, t0, y)
    X = evaluate_algebraic!(sys, t0, y)
    out = Dict{String,Dict{String,Any}}()
    for p in paths
        F = sys.data.FARF[p[:farf_index]+1]
        farf = p[:farf]
        combos = Dict{String,Any}()
        for o in 1:farf.other_width
            try
                _lay_out!(F, X, o)
            catch
                continue          # left to the part, which says why when it runs
            end
            combos[layer_key(b.space, farf.other_dims, o - 1)] =
                (d=F.layers_d[:, o], h=F.layers_h[:, o], q=F.layers_q[o])
        end
        out[p.name] = combos
    end
    return out
end

"""
Holds the far-field paths' matched layers at those given -- by path name,
then by combination (`layer_key`), each `(d, h, q)` -- or lets every path lay
out its own again, given `nothing` (`pinLayers`). What a part of a split run
is given; see `whole_layers`.
"""
function pin_layers!(sys::System, layers)
    space = sys.builder.space
    for p in sys.builder.farf_layout
        F = sys.data.FARF[p[:farf_index]+1]
        F isa FarfPath || continue
        mine = layers === nothing ? nothing : get(layers, p.name, nothing)
        farf = p[:farf]
        farfield_pin_layers!(F, (mine === nothing || isempty(mine)) ? nothing :
                                Any[get(mine, layer_key(space, farf.other_dims, o), nothing) for o in 0:farf.other_width-1])
    end
    return sys
end

# --- the parts, back into one run ---------------------------------------------------------------------

"""What one bin's run sends back: its states by name, its counts, and its recorders' histories."""
struct PartRun
    t::Vector{Float64}
    y::Vector{Vector{Float64}}
    keys::Vector{String}
    stats::Dict{String,Any}
    held::Any
    mem::Dict{String,Recorder}
    dis::Vector{Float64}
    sampled::Vector{Vector{Float64}}
    clock::Tuple{Float64,Float64}
    build_ms::Float64
    solve_ms::Float64
    pinned::Vector{String}
end

const _SPLIT_SUMMED = ("nsteps", "nfailed", "nfevals", "npds", "ndecomps", "restarts", "breaks", "events", "jumps",
                       "nbelowtol", "negative")

"""
    assemble_parts(keys, owner, outcomes) -> (t, y, stats)

The parts, back into one run of the whole model (`assembleParts`). Every
state is filed from the job that owns it, by name; every part must have come
back on the same times, and every state must have come from one -- else this
throws and the caller solves the whole model. The counts are summed; a
held-at-zero tally is kept as a share of its own part's steps.
"""
function assemble_parts(keys::Vector{String}, owner::Vector{Int}, outcomes::AbstractVector)
    n = length(keys)
    whole = Dict{String,Int}(k => i for (i, k) in enumerate(keys))
    t = outcomes[1].t
    for o in outcomes
        (length(o.t) == length(t) && all(o.t .== t)) || error("the parts came back on different output times")
    end
    nt = length(t)
    Y = [zeros(n) for _ in 1:nt]
    filled = falses(n)
    share = zeros(n)
    held_any = false
    stats = Dict{String,Any}("nsteps" => 0, "nfailed" => 0, "nfevals" => 0)
    for (jj, o) in enumerate(outcomes)
        frm, to = place_states(whole, o.keys, owner, jj - 1)
        @inbounds for r in 1:nt
            row = o.y[r]
            dest = Y[r]
            for q in eachindex(frm)
                dest[to[q]] = row[frm[q]]
            end
        end
        filled[to] .= true
        s = o.stats
        for key in _SPLIT_SUMMED
            v = get(s, key, nothing)
            (v isa Real && !(v isa Bool) && isfinite(v)) && (stats[key] = get(stats, key, 0) + v)
        end
        (!py_truthy(get(stats, "solver", nothing)) && py_truthy(get(s, "solver", nothing))) &&
            (stats["solver"] = s["solver"])
        get(s, "sparse", nothing) === nothing || (stats["sparse"] = s["sparse"])
        add_method_steps!(stats, s)
        # What a part said about a far-field path's layers, once however many parts the path is in.
        for w in something(get(s, "layers", nothing), Any[])
            said = get!(stats, "layers", Any[])
            any(x -> get(x, "block", nothing) == get(w, "block", nothing) &&
                     get(x, "message", nothing) == get(w, "message", nothing), said) || push!(said, w)
        end
        haskey(s, "compiled") && (stats["compiled"] = get(stats, "compiled", true) === true && s["compiled"] === true)
        held = o.held
        if held !== nothing
            steps = max(1, something(get(s, "nsteps", nothing), 1))
            for q in eachindex(frm)
                v = held[frm[q]]
                if v != 0
                    share[to[q]] = v / steps
                    held_any = true
                end
            end
        end
    end
    missing_ = findfirst(!, filled)
    missing_ === nothing || error("no part carried the state '$(keys[missing_])'")
    held_any && (stats["held"] = Int[_js_round_int(v * stats["nsteps"]) for v in share])
    return (t=copy(t), y=Y, stats=stats)
end

"""The histories of the recorders that remember (a min/max, a running mean), by the name `split_jobs` gives each entry."""
function _remembered(sys::System, mem::Vector{Recorder})
    out = Dict{String,Recorder}()
    space = sys.builder.space
    for rec in sys.recorders
        (rec.kind in ("min_max", "running_mean") && rec[:mem] >= 0) || continue
        for off in 0:rec.width-1
            index = isempty(rec.dims) ? String[] : tuple_at(space, rec.dims, off)
            out["$(rec.kind):$(rec.name)[$(join(index, ","))]"] = mem[rec[:mem]+off+1]
        end
    end
    return out
end

"""
One bin, on a thread: the model with its materials alone switched on, built,
run on the output grid holding the whole model's far-field layers, and its
states, counts and recorders' histories sent back. `hear(fraction, t)` is the
part's progress; returning `false` from it stops the part.
"""
function _part_run(model::AbstractDict, materials::Vector{String}, layers, hear)
    started = time()
    project, sys, pinned = build_part(part_model(model, materials))
    # The parts are what runs side by side: each one's derivative on its own thread.
    set_threads!(sys.assembler, 1)
    build_ms = 1000 * (time() - started)
    res = run_project(project; system=sys, on_grid=true, on_progress=hear, layers=layers)
    keys = state_keys(sys)
    keys === nothing && error("two states of this part share a name")
    stats = copy(res.stats)
    held = pop!(stats, "held", nothing)
    state = res.run_state
    return PartRun(res.t, res.y, keys, stats, held, _remembered(sys, state.mem), state.dis, state.sampled,
                   (Float64(state.clock[1]), Float64(state.clock[2])), build_ms, Float64(res.timing["solve_ms"]), pinned)
end

_split_aborted() = SolverError("aborted", "Simulation aborted", 0.0)

"""
    run_split(project, sys, plan; threads=nothing, on_progress=nothing) -> NamedTuple

The whole model, solved in its parts at once, as one run (`runSplit`). Each
bin of the plan is one job (`bin_jobs`): the model with the bin's materials
switched on, built once and run in a task of its own -- as many side by side
as `threads` says (every bin by default), the largest bin first to whichever
is free. What each sends back is filed into the whole model's vector by name,
and its recorders' histories onto the whole system. `on_progress(fraction, t)`
hears the parts' mean fraction and the slowest one's clock, about ten times a
second, from the calling task; returning `false` stops every part and the run
throws `SolverError` `aborted`. Throws if anything does not add up, and the
caller solves the whole model instead.
"""
function run_split(project::Project, sys::System, plan::SplitPlan; threads=nothing, on_progress=nothing,
                   constants::SplitConstants=SPLIT_CONSTANTS)
    work = bin_jobs(plan)
    jobs = work.jobs
    nb = length(jobs)
    count = threads === nothing ? nb : clamp(Int(threads), 1, nb)
    order = sort(collect(0:nb-1); by=j -> (-jobs[j+1].states, j))
    started = time()
    # The far-field paths' layers as the whole model lays them out, for every part to hold: a
    # part alone would size them by its own nuclides.
    layers = whole_layers(sys, project)
    model = project_to_json(project)
    outcome = Vector{Union{Nothing,PartRun}}(nothing, nb)
    # Where each part is: its fraction, and its clock -- the run's start until it has said.
    progress = fill((0.0, sys.start_time), nb)
    heard = ReentrantLock()
    stop = Threads.Atomic{Bool}(false)
    next = Threads.Atomic{Int}(1)
    function hearing(j)
        return function (fraction, at)
            lock(heard) do
                progress[j+1] = (Float64(fraction), Float64(at))
            end
            return !stop[]
        end
    end
    tasks = [Threads.@spawn begin
                 try
                     while !stop[]
                         k = Threads.atomic_add!(next, 1)
                         k > nb && break
                         j = order[k]
                         outcome[j+1] = _part_run(model, jobs[j+1].materials, layers, hearing(j))
                         lock(heard) do
                             progress[j+1] = (1.0, sys.end_time)
                         end
                     end
                 catch
                     # One part that fails stops the others: the run is solved whole instead.
                     stop[] = true
                     rethrow()
                 end
             end for _ in 1:count]
    stopped = false
    try
        if on_progress !== nothing
            while true
                finished = timedwait(() -> all(istaskdone, tasks), 0.1; pollint=0.005) === :ok
                fraction, at = lock(heard) do
                    (sum(first, progress) / nb, minimum(last, progress))
                end
                if !stopped && on_progress(fraction, at) === false
                    stopped = true
                    stop[] = true
                end
                finished && break
            end
        end
    catch
        # Whatever ended it early -- the progress callback, an interrupt -- the parts still
        # running are told to stop, and are waited for, before it goes further.
        stop[] = true
        for task in tasks
            try
                wait(task)
            catch
            end
        end
        rethrow()
    end
    failed = nothing
    for task in tasks
        try
            wait(task)
        catch e
            cause = e isa TaskFailedException ? task.exception : e
            # The parts stopped because another failed say only that they stopped.
            (failed === nothing || (failed isa SolverError && failed.kind == "aborted")) && (failed = cause)
        end
    end
    stopped && throw(_split_aborted())
    failed === nothing || throw(failed)
    any(o -> o === nothing, outcome) && throw(_split_aborted())
    wall_ms = 1000 * (time() - started)
    outcomes = PartRun[o for o in outcome]
    assembled = assemble_parts(plan.keys, work.owner, outcomes)
    # The recorders' histories, from the job that owns what each one reads.
    state = run_state(sys)
    mem = state.mem
    for (key, job, slot) in work.recorders
        carried = get(outcomes[job+1].mem, key, nothing)
        carried === nothing && error("the part that owns '$key' did not send its history back")
        mem[slot+1] = carried
    end
    first_ = outcomes[1]
    restore_run_state!(sys, (mem=mem, dis=first_.dis, sampled=first_.sampled, clock=first_.clock, laplace=Any[]))
    summary = OrderedDict{String,Any}[]
    for (j, jb) in enumerate(jobs)
        o = outcomes[j]
        push!(summary, OrderedDict{String,Any}("materials" => jb.materials, "states" => jb.states,
                                               "nsteps" => get(o.stats, "nsteps", nothing), "buildMs" => o.build_ms,
                                               "solveMs" => o.solve_ms))
    end
    solving = [o.solve_ms for o in outcomes]
    n = sys.nstate
    # What one thread would have taken for the whole model, and what the split takes (each
    # part's build and solve, packed as the tasks take them): kept for deciding the next run.
    whole_ms = whole_solve_ms(summary, solving, n, constants)
    spent = [s["buildMs"] + solving[j] for (j, s) in enumerate(summary)]
    expected_ms = maximum(sum((spent[j+1] for j in b); init=0.0) for b in pack_jobs(spent, count)) + constants.start_ms
    return (t=assembled.t, y=assembled.y, stats=assembled.stats, wall_ms=wall_ms, jobs=summary, whole_ms=whole_ms,
            expected_ms=expected_ms)
end

"""
    whole_solve_ms(jobs, solving, states) -> Float64

What one thread would have taken to solve the whole model, from a split's
bins: each one's `"states"` and `"nsteps"`, and its solve (`solving`, in the
same order). Two estimates, each of which errs high in a way of its own; the
smaller is taken: the slowest bin stretched to the whole by its share of a
derivative call (`job_cost`), as the application estimates it; and every
bin's cost per step summed, the work each repeats every step counted once,
over as many steps as the most any bin took.
"""
function whole_solve_ms(jobs::AbstractVector, solving::AbstractVector{<:Real}, states::Integer,
                        c::SplitConstants=SPLIT_CONSTANTS)
    stretched = maximum(solving[j] / job_cost(jobs[j]["states"], states, c) for j in eachindex(jobs))
    steps = [get(jb, "nsteps", nothing) for jb in jobs]
    all(s -> s isa Real && !(s isa Bool) && s > 0, steps) || return stretched
    per_step = sum(solving[j] / steps[j] for j in eachindex(jobs))
    summed = per_step / (c.shared_work * length(jobs) + 1 - c.shared_work) * maximum(steps)
    return min(stretched, summed)
end

"""
The share of a whole build each part pays whatever it holds, from the parts'
builds (`f` in `B * (f + (1 - f) * share)`): their mean, held to [0, 2] --
each bin's build first taken back from what the others built beside it cost
it (`contention`, as `SplitConstants` has it).
"""
function build_fixed(jobs::AbstractVector, states::Integer, build_ms::Real; contention::Real=0.0)
    (build_ms > 0 && states > 0) || return nothing
    slower = 1 + contention * (length(jobs) - 1)
    seen = Float64[]
    for j in jobs
        share = j["states"] / states
        share < 1 && push!(seen, (j["buildMs"] / slower / build_ms - share) / (1 - share))
    end
    isempty(seen) && return nothing
    return min(2.0, max(0.0, sum(seen) / length(seen)))
end

# --- what auto learns -----------------------------------------------------------------------------------

#: A hash of this engine's code, taken as the package is compiled: what was measured with
#: other code is not taken to hold for this.
const _SPLIT_ENGINE_STAMP = let ctx = SHA.SHA256_CTX(), root = dirname(@__DIR__)
    for (dir, _, files) in walkdir(root), f in sort(files)
        endswith(f, ".jl") || continue
        path = joinpath(dir, f)
        SHA.update!(ctx, codeunits(replace(relpath(path, root), '\\' => '/')))
        SHA.update!(ctx, read(path))
    end
    bytes2hex(SHA.digest!(ctx))[1:16]
end

#: What runs of each model have cost here, for deciding whether the next one is worth
#: splitting: `split_memory_key` => `"solve_ms"`, `"gain"`, `"build_fixed"`, `"when"`. Read from
#: and written to `split_memory_path()` as well.
const _SPLIT_MEMORY = Dict{String,Dict{String,Any}}()
const _SPLIT_MEMORY_READ = Ref(false)
const _SPLIT_MEMORY_LOCK = ReentrantLock()
#: The most entries the file keeps.
const SPLIT_MEMORY_KEEP = 1000

"""
Where what auto learns is kept: `split-memory-julia.json` in `KOMPARTMENT_CACHE`
when that is set, else in the package's scratch space in the first Julia
depot; `nothing` when `KOMPARTMENT_SPLIT_MEMORY` is `0`.
"""
function split_memory_path()
    strip(get(ENV, "KOMPARTMENT_SPLIT_MEMORY", "")) == "0" && return nothing
    root = strip(get(ENV, "KOMPARTMENT_CACHE", ""))
    dir = isempty(root) ? joinpath(first(DEPOT_PATH), "scratchspaces", string(Base.PkgId(@__MODULE__).uuid)) : root
    return joinpath(dir, "split-memory-julia.json")
end

"""What a measurement is kept by: the model's layout and the engine's code."""
split_memory_key(signature::AbstractString) = "$(signature)|julia|$(_SPLIT_ENGINE_STAMP)"

function _read_split_memory!()
    _SPLIT_MEMORY_READ[] && return
    _SPLIT_MEMORY_READ[] = true
    path = split_memory_path()
    (path === nothing || !isfile(path)) && return
    kept = try
        parse_json(read(path, String))
    catch
        return
    end
    kept isa AbstractDict || return
    for (key, entry) in kept
        (entry isa AbstractDict && !haskey(_SPLIT_MEMORY, key)) && (_SPLIT_MEMORY[String(key)] = Dict{String,Any}(entry))
    end
end

#: Whether this is the package being precompiled: its workload's runs are not this machine's
#: runs of a model, and nothing they did may be kept in the image or in the file.
_precompiling() = ccall(:jl_generating_output, Cint, ()) == 1

"""What auto has learned of a model (see `split_memory_key`), or `nothing`."""
function split_recall(key::AbstractString)
    _precompiling() && return nothing
    lock(_SPLIT_MEMORY_LOCK) do
        _read_split_memory!()
        entry = get(_SPLIT_MEMORY, key, nothing)
        entry === nothing ? nothing : copy(entry)
    end
end

_split_close(a, b) = (a === nothing || b === nothing) ? a === b :
                     abs(Float64(a) - Float64(b)) <= 0.25 * max(abs(Float64(a)), abs(Float64(b)))

"""
Keeps what a run measured, here and in the file -- written whole under a name
of this process's own and moved into place, the oldest entries dropped past
`SPLIT_MEMORY_KEEP`. A measurement within a quarter of the one kept is not
written again: a script that runs a model a thousand times does not write the
file a thousand times.
"""
function split_remember!(key::AbstractString, entry::AbstractDict)
    _precompiling() && return nothing
    lock(_SPLIT_MEMORY_LOCK) do
        _read_split_memory!()
        before = get(_SPLIT_MEMORY, key, nothing)
        now_ = Dict{String,Any}(entry)
        now_["when"] = time()
        _SPLIT_MEMORY[String(key)] = now_
        (before !== nothing &&
         all(k -> _split_close(get(before, k, nothing), get(entry, k, nothing)), ("solve_ms", "gain", "build_fixed"))) &&
            return
        path = split_memory_path()
        path === nothing && return
        try
            mkpath(dirname(path))
            kept = OrderedDict{String,Any}()
            if isfile(path)
                old = try
                    parse_json(read(path, String))
                catch
                    nothing
                end
                old isa AbstractDict && merge!(kept, old)
            end
            kept[String(key)] = now_
            if length(kept) > SPLIT_MEMORY_KEEP
                when = k -> (v = get(kept[k], "when", 0.0); v isa Real ? Float64(v) : 0.0)
                newest = sort!(collect(keys(kept)); by=k -> -when(k))[1:SPLIT_MEMORY_KEEP]
                kept = OrderedDict{String,Any}(k => kept[k] for k in newest)
            end
            tmp = "$(path).$(getpid()).part"
            write(tmp, json_text(kept; indent=0))
            mv(tmp, path; force=true)
        catch e
            e isa InterruptException && rethrow()
        end
    end
    return nothing
end

# --- the run ---------------------------------------------------------------------------------------------

"""
    run_whole_or_split(project; on_progress=nothing, on_grid=false, threads=nothing, nest=true) -> Results

A run of the whole model -- solved in its parts at once when
`simulation.split` says so and the plan agrees, whole otherwise -- with the
plan's account in `stats["split"]`, as the application gives it. What
`run_project` does with a project it builds itself. `threads` is how many
bins the parts are packed into, one per thread (`Threads.nthreads()` by
default); `nest=false` is a run that is itself one of several side by side.
"""
function run_whole_or_split(project::Project; on_progress=nothing, on_grid::Bool=false, threads=nothing,
                            nest::Bool=true)
    t0 = time()
    sys = build_system(project)
    build_ms = 1000 * (time() - t0)
    key = split_memory_key(layout_signature(sys))
    known = split_recall(key)
    cores = threads === nothing ? Threads.nthreads() : Int(threads)
    mode = get(project.simulation, "split", nothing)
    plan = plan_split(sys, project; mode=py_truthy(mode) ? mode : "auto", workers=cores, nest, build_ms, known, on_grid)
    results = nothing
    if plan.use
        try
            split = run_split(project, sys, plan; threads, on_progress)
            results = Results(project, sys, split.t, split.y, split.stats,
                              Dict("build_ms" => build_ms, "solve_ms" => split.wall_ms,
                                   "total_ms" => 1000 * (time() - t0)))
            plan.ran = split.jobs
            plan.wall_ms = split.wall_ms
            whole_ms = something(_known_value(known, "solve_ms"), split.whole_ms)
            plan.gain = split.expected_ms > 0 ? whole_ms / split.expected_ms : nothing
            split_remember!(key, Dict{String,Any}("solve_ms" => whole_ms, "gain" => plan.gain,
                                                  "build_fixed" => build_fixed(split.jobs, sys.nstate, build_ms;
                                                                               contention=SPLIT_CONSTANTS.build_contention),
                                                  "bins" => length(plan.bins)))
        catch e
            (e isa SolverError && e.kind == "aborted") && rethrow()
            e isa InterruptException && rethrow()
            plan.use = false
            plan.why = "tried, and solved whole instead: $(_split_error_text(e))"
            results = nothing
        end
    end
    if results === nothing
        results = run_project(project; system=sys, on_progress, on_grid)
        results.timing["build_ms"] = build_ms
        results.timing["total_ms"] = get(results.timing, "total_ms", 0.0) + build_ms
        entry = known === nothing ? Dict{String,Any}() : copy(known)
        entry["solve_ms"] = max(0.0, get(results.timing, "solve_ms", 0.0))
        split_remember!(key, entry)
    end
    account = OrderedDict{String,Any}("used" => plan.use, "mode" => plan.mode, "why" => plan.why,
                                      "predicted" => plan.predicted)
    if plan.use
        account["parts"] = plan.parts
        account["workers"] = length(plan.bins)
        account["jobs"] = plan.ran
        account["wallMs"] = plan.wall_ms
        account["gain"] = plan.gain
    end
    results.stats["split"] = account
    return results
end
