# A model and the run it produced, in one archive, as Kompartment writes one:
# the application's *Save with results* (src/io/dataset.js; the Python
# package's kompartment/io/dataset.py), so that an archive written here opens
# in the application as a live run, and one the application or the Python
# package wrote opens here.
#
# What is kept is the state vector, not the series: every other series is
# worked out from (t, y) on demand, so a reopened run answers every question
# a fresh one does. The archive is a ZIP with the run beside the model:
#
#     <name>.json          the model
#     results/meta.json    the run report, the layout signature, the lengths
#     results/t.f64        the output times
#     results/y.f64        the state vector at each of them, time-major
#     results/held.i32     per state, how many steps the zero-floor moved it
#     results/mem.f64      the histories of the blocks that remember
#
# The layout signature says what every number in `y` is -- every state and
# every recorder slot by name and offset -- and a stored run is refused
# against a model whose signature differs.

const DATASET_FORMAT = 1
const _DS_DIR = "results/"
const _DS_META = "results/meta.json"
const _DS_T = "results/t.f64"
const _DS_Y = "results/y.f64"
const _DS_HELD = "results/held.i32"
const _DS_MEM = "results/mem.f64"

#: The most a whole archive may expand to, as the application's reader allows.
const _DS_MAX_INFLATED = 256 * 1024 * 1024

#: The engines' names for what the application calls otherwise.
const _DS_STATS_NAMES = Dict("solver_points" => "solverPoints", "thinned_by" => "thinnedBy",
                             "steps_by" => "stepsBy", "krylov_iters" => "krylovIters")
const _DS_TIMING_NAMES = ("build_ms" => "buildMs", "solve_ms" => "solveMs", "total_ms" => "totalMs")

"""An archive whose run cannot be read: damaged, from a newer version, or not a description of the model."""
struct DatasetError <: Exception
    message::String
end
Base.showerror(io::IO, e::DatasetError) = print(io, e.message)

"""
    layout_signature(sys) -> String

What the numbers of a run mean, as one string (the application's
`layoutSignature`): every entry of the state vector and every recorder slot,
by the name and offset the builder gave it. Two models that produce this
string produce the same `y`.
"""
function layout_signature(sys::System)
    s = join(("$(x.kind):$(x.name)@$(x.base)+$(x.width)" for x in sys.builder.states), ",")
    m = join(("$(r.kind):$(r[:entry].name)@$(r[:mem])+$(r.width)" for r in sys.recorders), ",")
    return "v$(DATASET_FORMAT)|n=$(sys.nstate),$(sys.nalg),$(sys.nparam)|s=$s|m=$m"
end

_ds_bytes(v::Vector{Float64}) = collect(reinterpret(UInt8, htol.(v)))
_ds_bytes(v::Vector{Int32}) = collect(reinterpret(UInt8, htol.(v)))

"""The run's statistics as the application names them, `held` aside (it has a file of its own)."""
function _ds_stats(stats::AbstractDict)
    out = JDict()
    for k in sort!(collect(String, keys(stats)))
        k == "held" && continue
        out[get(_DS_STATS_NAMES, k, k)] = stats[k]
    end
    return out
end

"""The run's timings as the application names them."""
function _ds_timing(timing::AbstractDict)
    out = JDict()
    for (ours, theirs) in _DS_TIMING_NAMES
        haskey(timing, ours) && (out[theirs] = timing[ours])
    end
    for k in sort!(collect(String, keys(timing)))
        any(p -> p.first == k, _DS_TIMING_NAMES) || (out[k] = timing[k])
    end
    return out
end

"""
    dataset_entries(raw, res, inner; stamp=nothing, log=nothing) -> Vector{Pair{String,Vector{UInt8}}}

The entries a results archive holds, the model aside (the application's
`datasetEntries`): `results/meta.json`, `t.f64` and `y.f64`, then `held.i32`
and `mem.f64` when there is anything to put in them.
"""
function dataset_entries(raw::AbstractDict, res::Results, inner::AbstractString; stamp=nothing, log=nothing)
    t = Float64[x for x in res.t]
    rows = res.y
    nstate = isempty(rows) ? 0 : length(rows[1])
    y = Vector{Float64}(undef, length(rows) * nstate)
    for (i, row) in enumerate(rows)
        copyto!(y, (i - 1) * nstate + 1, row, 1, nstate)
    end
    held_in = get(res.stats, "held", nothing)
    held = held_in === nothing ? Int32[] : Int32[Int32(h) for h in held_in]
    # Every recorder's history end to end, its times then its values, as the
    # run left them.
    memory = res.run_state === nothing ? res.system.data.MEM : res.run_state.mem
    mem = Float64[]
    recorders = Any[]
    for m in memory
        append!(mem, m.history.t)
        append!(mem, m.history.v)
        push!(recorders, JDict("kind" => string(m.kind), "n" => length(m.history.t), "recording" => m.recording,
                               "totalTime" => m.total_time, "lastTime" => m.last_time, "resetSum" => m.reset_sum))
    end
    name = get(raw, "name", nothing)
    meta = JDict(
        "format" => DATASET_FORMAT,
        "kind" => "ecolego-results",
        "model" => String(inner),
        "name" => name === nothing ? "" : name,
        "stamp" => stamp,
        "times" => length(t),
        "states" => nstate,
        "outputs" => length(outputs(res)),
        "signature" => layout_signature(res.system),
        "stats" => _ds_stats(res.stats),
        "timing" => _ds_timing(res.timing),
        "recorders" => recorders,
        "log" => log === nothing ? nothing : Any[String(l) for l in log],
    )
    out = Pair{String,Vector{UInt8}}[
        _DS_META => Vector{UInt8}(codeunits(json_text(meta; indent=2))),
        _DS_T => _ds_bytes(t),
        _DS_Y => _ds_bytes(y),
    ]
    isempty(held) || push!(out, _DS_HELD => _ds_bytes(held))
    isempty(mem) || push!(out, _DS_MEM => _ds_bytes(mem))
    return out
end

"""A date and time as a ZIP entry carries them (MS-DOS, local time, no year before 1980): `(date, time)`.
`modified`: seconds since the epoch, a `DateTime` (local), or `nothing` for the epoch, as the application writes."""
function _ds_dos_time(modified)
    tm = modified isa DateTime ? Libc.TmStruct(datetime2unix(modified) - _ds_local_offset(modified)) :
         Libc.TmStruct(Float64(modified === nothing ? 0 : modified))
    year = max(1980, tm.year + 1900)
    date = ((year - 1980) << 9) | ((tm.month + 1) << 5) | max(1, tm.mday)
    time = (tm.hour << 11) | (tm.min << 5) | (tm.sec >> 1)
    return UInt16(date & 0xffff), UInt16(time & 0xffff)
end

"""How far local time is ahead of UTC at a local `DateTime`, in seconds."""
function _ds_local_offset(d::DateTime)
    probe = datetime2unix(d)
    tm = Libc.TmStruct(probe)
    local_as_utc = datetime2unix(DateTime(tm.year + 1900, tm.month + 1, tm.mday, tm.hour, tm.min, tm.sec))
    return local_as_utc - probe
end

"""
Entries as a ZIP archive, laid out as the application's `zip` lays one out:
local headers, deflate or stored data, a central directory and an end record;
names flagged as UTF-8, version 2.0, no extra fields, comments or ZIP64. An
entry is stored when deflate does not make it smaller, and when it would take
the deflated total past what the application's reader inflates of one archive.
"""
function _ds_zip(entries; modified=nothing, compress::Bool=true, inflate_limit::Int=_DS_MAX_INFLATED)
    date, time = _ds_dos_time(modified)
    io = IOBuffer()
    central = IOBuffer()
    count = 0
    inflated = 0
    for (name, raw) in entries
        nm = Vector{UInt8}(codeunits(String(name)))
        length(raw) > 0xffffffff && throw(DatasetError("'$name' is $(length(raw)) bytes, which needs ZIP64"))
        fits = inflated + length(raw) <= inflate_limit
        packed = (compress && fits) ? deflate_bytes(raw; level=6) : nothing
        use = packed !== nothing && length(packed) < length(raw)
        use && (inflated += length(raw))
        data = use ? packed : raw
        method = UInt16(use ? 8 : 0)
        crc = crc32(raw)
        offset = position(io)
        write(io, UInt32(0x04034b50), UInt16(20), UInt16(0x0800), method, time, date, crc,
              UInt32(length(data)), UInt32(length(raw)), UInt16(length(nm)), UInt16(0))
        write(io, nm)
        write(io, data)
        write(central, UInt32(0x02014b50), UInt16(20), UInt16(20), UInt16(0x0800), method, time, date, crc,
              UInt32(length(data)), UInt32(length(raw)), UInt16(length(nm)), UInt16(0), UInt16(0), UInt16(0),
              UInt16(0), UInt32(0), UInt32(offset))
        write(central, nm)
        count += 1
    end
    cd_offset = position(io)
    cd = take!(central)
    write(io, cd)
    write(io, UInt32(0x06054b50), UInt16(0), UInt16(0), UInt16(count), UInt16(count), UInt32(length(cd)),
          UInt32(cd_offset), UInt16(0))
    return take!(io)
end

"""`new Date().toISOString()`: now, in UTC, to the millisecond."""
_ds_now() = Dates.format(now(Dates.UTC), dateformat"yyyy-mm-ddTHH:MM:SS.sss") * "Z"

"""The model of a run, as its file holds it: a `Model`'s settled dictionary, a dictionary as it is, or the run's own."""
function _ds_raw(project, res::Results)
    project === nothing && return res.project.raw
    project isa AbstractDict && return project
    if hasproperty(project, :raw) && getproperty(project, :raw) isa AbstractDict
        r = getproperty(project, :raw)
        project isa Project || settle!(r)
        return r
    end
    throw(ArgumentError("`project` is a model, a model's dictionary or a Project"))
end

"""
    dataset_archive(res; project=nothing, inner=nothing, stamp=now, log=nothing, compress=true, modified=nothing)

A model and its run as the archive *Save with results* writes: the model at
the root as `<slug of its name>.json`, the run beside it under `results/`.
`project` is the model (a `Model` or its dictionary), by default the one the
run was built from; `stamp` when the run was made (ISO text, now by default);
`log` the run log as lines, the run's own by default (`nothing` for none);
`compress=false` stores every entry; `modified` is the entries' time stamp
(the epoch by default).
"""
function dataset_archive(res::Results; project=nothing, inner=nothing, stamp=_ds_now(), log=:default,
                         compress::Bool=true, modified=nothing)
    raw = _ds_raw(project, res)
    log === :default && (log = split(run_log(res; project=raw), "\n"))
    name = inner === nothing ? "$(slug(get(raw, "name", nothing))).json" : String(inner)
    entries = Pair{String,Vector{UInt8}}[name => Vector{UInt8}(codeunits(json_text(raw; indent=2)))]
    append!(entries, dataset_entries(raw, res, name; stamp, log))
    return _ds_zip(entries; modified, compress)
end

# --- reading ---------------------------------------------------------------------------------

"""Little-endian numbers out of an entry's bytes: as many whole values as fit."""
function _ds_read(::Type{T}, bytes::Vector{UInt8}) where {T}
    n = length(bytes) ÷ sizeof(T)
    return T[ltoh(x) for x in reinterpret(T, view(bytes, 1:n*sizeof(T)))]
end

"""The entries of an archive, by name, in the order its directory lists them; directories left out."""
function _ds_unzip(bytes::Vector{UInt8})
    z = try
        read_zip(bytes)
    catch e
        throw(DatasetError("This does not look like a ZIP archive: $(sprint(showerror, e))"))
    end
    out = OrderedDict{String,Vector{UInt8}}()
    spent = 0
    for e in z.entries
        endswith(e.name, "/") && continue
        e.size > _DS_MAX_INFLATED - spent &&
            throw(DatasetError("'$(e.name)' takes this archive past the $(_DS_MAX_INFLATED ÷ 1048576) MB a reader " *
                               "will decompress."))
        data = zip_read(z, e)
        spent += e.method == 0 ? 0 : length(data)
        out[e.name] = data
    end
    return out
end

"""
    read_dataset(entries) -> NamedTuple or nothing

The run out of an archive's entries, as plain arrays: `meta`, `t`, `flat` (the
trajectory, time-major), `held` (or nothing) and `memory` (each recorder's
history, `t` and `v`, and its scalars). `nothing` where the archive holds no run.
"""
function read_dataset(entries::AbstractDict)
    haskey(entries, _DS_META) || return nothing
    text = String(copy(entries[_DS_META]))
    startswith(text, "﻿") && (text = text[nextind(text, 1):end])
    meta = parse_json(text)
    info = meta isa AbstractDict ? meta : JDict()
    fmt = get(info, "format", nothing)
    if fmt isa Real && fmt > DATASET_FORMAT
        throw(DatasetError("These results were written by a newer version of this editor (format $(js_number(fmt)); " *
                           "this one reads $DATASET_FORMAT). The model in the file opens either way."))
    end
    t = haskey(entries, _DS_T) ? _ds_read(Float64, entries[_DS_T]) : Float64[]
    flat = haskey(entries, _DS_Y) ? _ds_read(Float64, entries[_DS_Y]) : Float64[]
    states = Int(something(get(info, "states", nothing), 0))
    length(flat) == length(t) * states ||
        throw(DatasetError("The trajectory is $(length(flat)) numbers and the file says it should be " *
                           "$(length(t) * states) ($(length(t)) times × $states states). The archive is damaged."))
    held = haskey(entries, _DS_HELD) ? _ds_read(Int32, entries[_DS_HELD]) : nothing
    mem = haskey(entries, _DS_MEM) ? _ds_read(Float64, entries[_DS_MEM]) : Float64[]
    memory = Any[]
    at = 0
    for r in something(get(info, "recorders", nothing), Any[])
        n = r isa AbstractDict ? Int(something(get(r, "n", nothing), 0)) : 0
        lo, mid, hi = min(at, length(mem)), min(at + n, length(mem)), min(at + 2n, length(mem))
        push!(memory, (info=r, t=mem[lo+1:mid], v=mem[mid+1:hi]))
        at += 2n
    end
    return (meta=info, t=t, flat=flat, states=states, held=held, memory=memory)
end

"""
    read_archive(source) -> (project, dataset, problem)

A model archive as opening one reads it: the model (the first `.json` entry
outside `results/`), its run (`nothing` when there is none) and, when the run
would not read, why -- the model opens either way. `source` is a path or bytes.
"""
function read_archive(source)
    bytes = source isa AbstractString ? read(source) : Vector{UInt8}(source)
    entries = _ds_unzip(bytes)
    any(n -> occursin(r"(^|/)model\.xml$"i, n), keys(entries)) &&
        throw(DatasetError("This is an Ecolego project (it holds a model.xml); open it with `load` or " *
                           "`import_ecolego` rather than as a model archive."))
    names = collect(keys(entries))
    name = findfirst(n -> !startswith(n, _DS_DIR) && endswith(lowercase(n), ".json"), names)
    if name === nothing
        held = join(names[1:min(4, length(names))], ", ")
        throw(DatasetError("This is a ZIP archive with no model in it -- no .json file and no model.xml. It holds " *
                           "$held."))
    end
    project = parse_json(entries[names[name]])
    dataset = nothing
    problem = nothing
    if haskey(entries, _DS_META)
        try
            dataset = read_dataset(entries)
        catch e
            e isa InterruptException && rethrow()
            problem = sprint(showerror, e)
        end
    end
    return (project=project, dataset=dataset, problem=problem)
end

"""
    restore_results(project, sys, data) -> Results

A stored run put back onto a freshly built system (the application's
`restoreResults`): refused unless its layout signature is the system's; the
recorders' histories put back, so their series are the run's.
"""
function restore_results(project::Project, sys::System, data)
    meta = data.meta
    layout_signature(sys) == get(meta, "signature", nothing) ||
        throw(DatasetError("The stored run does not describe this model's state vector, so the numbers in it cannot " *
                           "be read against it."))
    stats = Dict{String,Any}()
    st = get(meta, "stats", nothing)
    if st isa AbstractDict
        back = Dict(v => k for (k, v) in _DS_STATS_NAMES)
        for (k, v) in st
            stats[get(back, k, k)] = v
        end
    end
    data.held === nothing || (stats["held"] = Int[h for h in data.held])
    for (i, m) in enumerate(sys.data.MEM)
        i <= length(data.memory) || break
        saved = data.memory[i]
        m.history.t = copy(saved.t)
        m.history.v = copy(saved.v)
        info = saved.info
        if info isa AbstractDict
            m.recording = get(info, "recording", m.recording) === true
            m.total_time = Float64(something(get(info, "totalTime", nothing), m.total_time))
            m.last_time = Float64(something(get(info, "lastTime", nothing), m.last_time))
            m.reset_sum = Float64(something(get(info, "resetSum", nothing), m.reset_sum))
        end
    end
    n = data.states
    y = [data.flat[(i-1)*n+1:i*n] for i in eachindex(data.t)]
    timing = Dict{String,Float64}()
    tm = get(meta, "timing", nothing)
    if tm isa AbstractDict
        for (ours, theirs) in _DS_TIMING_NAMES
            v = get(tm, theirs, nothing)
            v isa Real && (timing[ours] = Float64(v))
        end
    end
    return Results(project, sys, copy(data.t), y, stats, timing)
end

"""
    load_results(source; project=nothing) -> Results

The run in a model archive -- `save(res, "run.zip")`'s, the Python package's
`Results.save`, or the application's *Save with results* -- as a live
`Results`: the model in the archive built, the stored run checked against it
and put back. `project` replaces the archive's model (it must lay its states
out the same way). Throws `DatasetError` when the archive holds no run, when
the run will not read, or when it does not describe the model.
"""
function load_results(source; project=nothing)
    got = read_archive(source)
    got.problem === nothing || throw(DatasetError(got.problem))
    got.dataset === nothing && throw(DatasetError("This archive holds a model and no run."))
    started = time()
    raw = project === nothing ? got.project : project isa AbstractDict ? project : getproperty(project, :raw)
    p = Project(raw isa Model ? raw.raw : raw)
    sys = build_system(p)
    res = restore_results(p, sys, got.dataset)
    res.timing["build_ms"] = 1000 * (time() - started)
    res.stats["opened"] = true
    return res
end
