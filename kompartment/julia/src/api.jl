# The package's face: a model opened from a file, run, and its results read
# and saved.
#
#     m = Kompartment.load("biosphere.json")
#     res = run(m; end_time=1e5)
#     res["Dose [I-129]"]
#     to_csv(res, "biosphere.csv")

"""
    Model

A Kompartment model: the project file's dictionary as the application holds
it (`m.raw`), where it came from, and what an import from another tool
reported.
"""
mutable struct Model
    raw::JDict
    path::Union{Nothing,String}
    import_report::Any
end

Model(raw::AbstractDict; path=nothing) = Model(_normalise_raw(raw), path === nothing ? nothing : String(path), nothing)

function Base.show(io::IO, m::Model)
    counts = String[]
    for c in COLLECTIONS
        v = get(m.raw, c, nothing)
        (v isa AbstractVector && !isempty(v)) && push!(counts, "$(length(v)) $c")
    end
    print(io, "Model(", repr(get(m.raw, "name", "")), ": ", isempty(counts) ? "empty" : join(counts, ", "), ")")
end

"""What a model file holds, brought into the shape Kompartment works on, as Python's `Model(raw)` brings
it: a copy, older key spellings renamed, then normalised (see `normalise_model!`)."""
_normalise_raw(raw::AbstractDict) = normalise_model!(migrate_keys(jcopy(JDict(raw))))

"""
    load(path) -> Model

Opens a model file: Kompartment's own (`.json`, `.json.gz`, `.zip`), or an
Ecolego project or assessment (`.eco`, `.eas`, a bare `model.xml`), imported
as the application imports one -- what could not come across is in
`m.import_report`.
"""
function load(path::AbstractString)
    low = lowercase(path)
    if endswith(low, ".eco") || endswith(low, ".eas") || endswith(low, ".xml")
        return import_ecolego(path)
    end
    return Model(read_model_file(path); path=path)
end

"""A model from the text of a project file."""
function from_json(text::AbstractString)
    data = parse_json(text)
    data isa AbstractDict || throw(ArgumentError("A model is one JSON object"))
    return Model(data)
end

"""The project file's text, settled (see `settle!`) and formatted as the application writes it."""
function to_json(m::Model; indent::Integer=2)
    settle!(m.raw)
    return json_text(m.raw; indent)
end

"""
    save(m, path)

Writes the model as `.json`, `.json.gz` or `.zip`, by the name's ending,
settled and stamped as the application's *Save* stamps a file: `saved` is now
(UTC, to the millisecond), and `created` too when the model has no date of its
own; the header (`name`, `description`, `author`, `created`, `saved`) first.
"""
function save(m::Model, path::AbstractString; indent::Integer=2)
    settle!(m.raw)
    at = model_stamp()
    read_model_stamp(get(m.raw, "created", nothing)) === nothing && (m.raw["created"] = at)
    m.raw["saved"] = at
    header_first!(m.raw)
    return write_model_file(path, m.raw; indent)
end

"""The model's simulation settings, live: changing an entry changes the model."""
function simulation(m::Model)
    sim = get(m.raw, "simulation", nothing)
    if !(sim isa AbstractDict)
        sim = JDict()
        m.raw["simulation"] = sim
    end
    return sim
end

"""
    set_simulation!(m; settings...) -> m

Sets simulation settings: `set_simulation!(m; end_time=1e6, solver="ndf", non_negative=false)`.
"""
function set_simulation!(m::Model; settings...)
    sim = simulation(m)
    for (k, v) in settings
        sim[String(k)] = v
    end
    return m
end

"""The model with simulation settings replaced for one run, as a Project."""
function project(m::Model; settings...)
    isempty(settings) && return Project(m.raw)
    raw = deepcopy(m.raw)
    sim = get(raw, "simulation", nothing)
    sim isa AbstractDict || (sim = JDict(); raw["simulation"] = sim)
    for (k, v) in settings
        sim[String(k)] = v
    end
    return Project(raw)
end

"""
    build(m; settings...) -> System

The model built into equations and compiled: `dydt(sys, t, y)`,
`initial_state(sys)`, `evaluate_algebraic!(sys, t, y)`.
"""
build(m::Model; settings...) = build_system(project(m; settings...))

"""
    run(m::Model; on_progress=nothing, threads=nothing, settings...) -> Results

Runs a model with its own simulation settings, or with some replaced for this
run: `run(m; end_time=1e5, solver="ros23")`. A model whose `split` setting
says so (`run(m; split="on")`) is solved in its independent parts side by
side, one bin of them per thread -- `threads` of them, every thread Julia has
by default -- and `res.stats["split"]` says what was done.
"""
Base.run(m::Model; on_progress=nothing, threads=nothing, settings...) =
    run_project(project(m; settings...); on_progress, threads)

"""Runs a model file: `run_file("biosphere.json")`."""
run_file(path::AbstractString; kw...) = run(load(path); kw...)

"""Every series of a run as `label => values`, with `"time"` first."""
function to_dict(res::Results, outs=nothing)
    os = outs === nothing ? outputs(res) : JDict[o isa AbstractString ? find_output(res, o) : o for o in outs]
    cols = series_many(res, os)
    out = OrderedDict{String,Vector{Float64}}("time" => copy(res.t))
    for (o, c) in zip(os, cols)
        out[String(o["label"])] = c
    end
    return out
end

"""The series of a run as a matrix, a column per output (in `outputs(res)` order unless given)."""
function to_matrix(res::Results, outs=nothing)
    os = outs === nothing ? outputs(res) : JDict[o isa AbstractString ? find_output(res, o) : o for o in outs]
    cols = series_many(res, os)
    M = Matrix{Float64}(undef, length(res.t), length(cols))
    for (j, c) in enumerate(cols)
        M[:, j] = c
    end
    return M
end

"""
    run_scenarios(m, scenarios=nothing; threads=1, settings...) -> OrderedDict{String,Results}

Runs the model once per scenario of its scenario list -- every one, or those
named -- and returns the runs by scenario, in the order asked. Keyword
settings replace simulation settings for every run, as `run` takes them.
`threads` > 1 runs that many side by side, each built and solved on a
thread of its own; the runs are the same either way.

The runs side by side as one HDF5 result file: `write_scenarios_hdf5(runs, path)`.
"""
function run_scenarios(m::Model, scenarios=nothing; threads::Integer=1, settings...)
    raw = jcopy(m.raw)
    if !isempty(settings)
        sim = get(raw, "simulation", nothing)
        sim isa AbstractDict || (sim = JDict(); raw["simulation"] = sim)
        for (k, v) in settings
            sim[String(k)] = v
        end
    end
    names = scenarios === nothing ? collect(String, Project(raw).scenarios) : String[String(s) for s in scenarios]
    isempty(names) && throw(ArgumentError("This model has no scenarios: an index list marked as the scenario list, " *
                                          "with indices."))
    # A Project copies what it is given: the model need not be copied for each. Runs side by
    # side are not split again.
    side_by_side = threads > 1 && length(names) > 1
    function one(name)
        r = copy(raw)
        r["scenario"] = name
        return run_project(Project(r); nest=!side_by_side)
    end
    done = Vector{Results}(undef, length(names))
    if threads <= 1 || length(names) == 1
        for (k, name) in enumerate(names)
            done[k] = one(name)
        end
    else
        next = Threads.Atomic{Int}(1)
        workers = [Threads.@spawn begin
                       while true
                           k = Threads.atomic_add!(next, 1)
                           k > length(names) && break
                           done[k] = one(names[k])
                       end
                   end for _ in 1:min(Int(threads), length(names))]
        foreach(fetch, workers)
    end
    return OrderedDict{String,Results}(name => done[k] for (k, name) in enumerate(names))
end

"""
What a model's equations come to at the first instant of a run (the
application's editor preview): `v[name]` gives one block and each of its
settings. One pass of the code a run begins with -- the initial state, then the
algebraic slots once -- read back through the descriptors the results use, so
a value here is the first row of the run's table for the same block.
"""
struct ValuesAtStart
    project::Project
    system::System
    rows::Dict{String,Vector{Float64}}
    own::OrderedDict{String,NamedTuple{(:entry, :kind, :where),Tuple{Entry,String,String}}}
    fields::IdDict{Any,OrderedDict{String,NamedTuple{(:entry, :where),Tuple{Entry,String}}}}
    asked::Dict{String,Any}
end

const _AT_START_SOURCE = Dict("state" => "y", "algebraic" => "X", "parameter" => "P")

function ValuesAtStart(project::Project, sys::System=build_system(project; jacobian=false))
    t0 = Float64(project.simulation["start_time"])
    y = initial_state(sys)
    prime_recorders!(sys, t0, y)
    X = copy(evaluate_algebraic!(sys, t0, y))
    v = ValuesAtStart(project, sys, Dict("y" => y, "X" => X, "P" => sys.P),
                      OrderedDict{String,NamedTuple{(:entry, :kind, :where),Tuple{Entry,String,String}}}(),
                      IdDict{Any,OrderedDict{String,NamedTuple{(:entry, :where),Tuple{Entry,String}}}}(),
                      Dict{String,Any}())
    remember(e, kind, where_) = haskey(v.own, e.name) || (v.own[e.name] = (entry=e, kind=kind, where=where_))
    fields_of(block) = get!(() -> OrderedDict{String,NamedTuple{(:entry, :where),Tuple{Entry,String}}}(), v.fields,
                            block)
    b = sys.builder
    for s in b.states
        if s.kind == "waste_package"
            remember(s, "waste_inventory", "state")
        elseif s.kind == "event"
            remember(s, "event", "state")
        elseif s.kind == "compartment"
            remember(s, "compartment", "state")
            s.block === nothing || (fields_of(s.block)["initial"] = (entry=s, where="state"))
        end
    end
    for a in b.algebraic
        a.hidden || remember(a, a.kind, "algebraic")
        (a.value_key !== nothing && !isempty(a.value_key) && a.block !== nothing) &&
            (fields_of(a.block)[a.value_key] = (entry=a, where="algebraic"))
    end
    for p in b.param_layout
        remember(p, "parameter", "parameter")
        p.block === nothing || (fields_of(p.block)["value"] = (entry=p, where="parameter"))
    end
    return v
end

function _at_start_unit(v::ValuesAtStart, key, derived)
    (key == "target" || key == "initial") && return derived
    t = get(v.project.simulation, "time_unit", nothing)
    key == "delay" && return something(t, "")
    if key == "dydt"
        isempty(derived) && return ""
        return (t === nothing || t == "") ? derived : "$derived/$t"
    end
    return ""
end

function _at_start_read(v::ValuesAtStart, entry::Entry, where_::String, kind, aux=nothing)
    out = OrderedDict{String,Any}[]
    for d in describe_entry(v.system, entry, kind, _AT_START_SOURCE[where_], material_units(v.system))
        label = aux === nothing ? d["label"] : replace(d["label"], entry.name => aux.owner; count=1)
        unit = aux === nothing ? d["unit"] : _at_start_unit(v, aux.key, d["unit"])
        push!(out, OrderedDict{String,Any}("index" => d["index"], "label" => label, "unit" => unit,
                                           "value" => v.rows[d["source"]][d["offset"]+1]))
    end
    return out
end

"""`v[name]`: one block at the start -- `kind`, `dims`, its `own` values and each setting's (`fields`); `nothing` for no block."""
function Base.getindex(v::ValuesAtStart, name::AbstractString)
    haskey(v.asked, name) && return v.asked[name]
    it = get(v.own, name, nothing)
    block = it === nothing ? nothing : it.entry.block
    fields = block === nothing ? nothing : get(v.fields, block, nothing)
    if it === nothing && (fields === nothing || isempty(fields))
        v.asked[name] = nothing
        return nothing
    end
    out = OrderedDict{String,Any}("kind" => it === nothing ? nothing : it.kind,
                                  "dims" => it === nothing ? String[] : copy(it.entry.dims),
                                  "own" => it === nothing ? nothing : _at_start_read(v, it.entry, it.where, it.kind),
                                  "fields" => OrderedDict{String,Any}())
    for (key, f) in something(fields, Dict())
        # A setting worked out in a hidden slot of its own is labelled by its block.
        aux = f.entry.hidden ? (owner=name, key=key) : nothing
        out["fields"][key] = _at_start_read(v, f.entry, f.where, it === nothing ? key : it.kind, aux)
    end
    v.asked[name] = out
    return out
end

"""
    values_at_start(m, name=nothing; settings...)

What the model's equations come to at the first instant: one block's values
and each of its settings' (`kind`, `dims`, `own`, `fields`), or, without a
name, the whole `ValuesAtStart` to ask by name, `v["Soil"]`.
"""
function values_at_start(m::Model, name=nothing; settings...)
    v = ValuesAtStart(project(m; settings...))
    return name === nothing ? v : v[name]
end

"""
    ResultTable

A run's series as columns: `names` (`"time"`, then each series' label) and
`columns`, one vector each. With Tables.jl loaded -- as DataFrames, CSV.jl and
the plotting packages load it -- a `ResultTable` and a `Results` are tables:
`DataFrame(res)`, `DataFrame(Kompartment.table(res, outputs(res, "Soil")))`.
"""
struct ResultTable
    names::Vector{String}
    columns::Vector{Vector{Float64}}
end

Base.show(io::IO, t::ResultTable) =
    print(io, "ResultTable(", length(t.names) - 1, " series × ", isempty(t.columns) ? 0 : length(t.columns[1]), " times)")

"""`table(res, outs=nothing)`: the run as a [`ResultTable`](@ref), every series or those given (descriptors or labels)."""
function table(res::Results, outs=nothing)
    d = to_dict(res, outs)
    return ResultTable(collect(String, keys(d)), collect(Vector{Float64}, values(d)))
end
