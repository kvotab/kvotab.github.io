# A probabilistic run as the application's archive holds one: `results/sample/`
# beside the model, as src/io/dataset.js writes it (`sampleEntries`) and reads it
# back (`readSample`, `sampleResult`). The local server's Julia engine hands a
# probabilistic run to the page this way, and the page holds it as the sample it
# is -- bands, histograms and *What drove it* worked out there from these numbers.

const _DS_SAMPLE_DIR = "results/sample/"
const _DS_SAMPLE_META = "results/sample/meta.json"
const _DS_SAMPLE_T = "results/sample/t.f64"
const _DS_SAMPLE_DRAWS = "results/sample/draws.f64"
const _DS_SAMPLE_RAN = "results/sample/ran.u8"

"""The sample's own format, bumped only as `DATASET_FORMAT` is."""
const SAMPLE_FORMAT = 1

_sample_bytes(v::AbstractVector{T}) where {T<:Union{Float32,Float64}} = collect(reinterpret(UInt8, htol.(collect(v))))

"""
The run's statistics as the page reads them: a tornado's swung inputs, and the
inputs of each of a sensitivity design's factors, counted from 0, as it counts them.
"""
function _sample_stats(stats::AbstractDict)
    out = stats
    tornado = get(stats, "tornado", nothing)
    if tornado isa AbstractDict && haskey(tornado, "swung")
        out = copy(out)
        out["tornado"] = merge(copy(tornado), Dict("swung" => Any[Int(k) - 1 for k in tornado["swung"]]))
    end
    gsa = get(stats, "gsa", nothing)
    if gsa isa AbstractDict && get(gsa, "factors", nothing) isa AbstractVector
        out = copy(out)
        factors = Any[f isa AbstractDict && haskey(f, "members") ?
                      merge(copy(f), Dict("members" => Any[Int(k) - 1 for k in f["members"]])) : f
                      for f in gsa["factors"]]
        out["gsa"] = merge(copy(gsa), Dict("factors" => factors))
    end
    return out
end

"""
    sample_entries(prob; stamp=nothing, series=true) -> Vector{Pair{String,Vector{UInt8}}}

A probabilistic run as the entries of `results/sample/` (the application's
`sampleEntries`): the kept series realisation after realisation, in the
precision the run held them in, then each varied input's draws, which realisations
integrated, and what it all is. The varied parameters are listed after the kept
series as the page lists them (`flat`, with the column of draws each came from,
counted from 0); they are not written as series, and come back from their draws.

`series=false` leaves the kept series out, for a sample the local server's
engine holds and answers for (`onEngine` in the meta): the page asks for what
it shows as it shows it, and holds the draws, the times and which realisations
ran.
"""
function sample_entries(r::ProbabilisticResults{T}; stamp=nothing, series::Bool=true) where {T}
    n = r.iterations
    times = length(r.t)
    each = n * times
    held = Vector{T}(undef, series ? length(r.values) * each : 0)
    # A series is held a realisation to a row; the file has each realisation's
    # times one after another.
    for (j, m) in enumerate(r.values)
        size(m) == (n, times) ||
            throw(ArgumentError("series $j is $(size(m, 1)) × $(size(m, 2)), not $n × $times: a part of a run cannot be written as a sample"))
        series || continue
        at = (j - 1) * each
        for i in 1:n, k in 1:times
            held[at+(i-1)*times+k] = m[i, k]
        end
    end
    draws = vec(permutedims(r.samples))
    outputs = Any[r.outputs...]
    flat = Int[0 for _ in r.outputs]
    drawn_from = Int[-1 for _ in r.outputs]
    for inp in r.inputs
        push!(outputs, inp["output"])
        push!(flat, 1)
        push!(drawn_from, Int(inp["k"]) - 1)
    end
    meta = OrderedDict{String,Any}(
        "format" => SAMPLE_FORMAT,
        "kind" => "kompartment-sample",
        "stamp" => stamp,
        "iterations" => n,
        "times" => times,
        "precision" => T === Float32 ? "float32" : "double",
        "kept" => length(r.values),
        "outputs" => outputs,
        "flat" => flat,
        "drawnFrom" => drawn_from,
        "plan" => r.plan,
        "stats" => _sample_stats(r.stats),
    )
    series || (meta["onEngine"] = true)
    entries = Pair{String,Vector{UInt8}}[
        _DS_SAMPLE_META => Vector{UInt8}(codeunits(json_text(meta; indent=1))),
        _DS_SAMPLE_T => _sample_bytes(r.t),
    ]
    series && push!(entries, "$(_DS_SAMPLE_DIR)series.$(T === Float32 ? "f32" : "f64")" => _sample_bytes(held))
    push!(entries, _DS_SAMPLE_DRAWS => _sample_bytes(draws), _DS_SAMPLE_RAN => collect(UInt8, r.ran))
    return entries
end

"""
    sample_archive(prob; project=nothing, inner=nothing, stamp=now, compress=true, modified=nothing, series=true) -> Vector{UInt8}

The model and a probabilistic run of it as one archive: the model at the root
(by default the one the run was made from), the sample under `results/sample/`
-- without its series (`series=false`) when the engine holds the sample.
"""
function sample_archive(r::ProbabilisticResults; project=nothing, inner=nothing, stamp=_ds_now(),
                        compress::Bool=true, modified=nothing, series::Bool=true)
    raw = project === nothing ? r.project.raw : project isa AbstractDict ? project : getproperty(project, :raw)
    name = inner === nothing ? "$(slug(get(raw, "name", nothing))).json" : String(inner)
    entries = Pair{String,Vector{UInt8}}[name => Vector{UInt8}(codeunits(json_text(raw; indent=2)))]
    append!(entries, sample_entries(r; stamp, series))
    return _ds_zip(entries; modified, compress)
end
