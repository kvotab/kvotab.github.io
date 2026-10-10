# Probabilistic runs bit for bit against the Python package's
# (tools/prob_fixtures.py): the named streams, the columns of uniforms, a value
# drawn from every kind of distribution, the normal CDF and quantile, the
# correlation pairs and Iman-Conover's permutations; then whole runs -- the
# sampling plan, every value drawn, every realisation of every series kept, the
# statistics and the failures -- with one thread and with every thread Julia
# was started with, which must give the same numbers.
#
# From kompartment/julia (the fixtures go to a scratch directory, never the repository):
#
#     PYTHONPATH=../python python3 tools/prob_fixtures.py <scratch>/prob
#     KOMPARTMENT_PROB_FIXTURES=<scratch>/prob julia --threads=8 --project=. test/engine/probabilistic.jl
#
# Without the fixtures only the first testset runs: what needs nothing but the
# bundled examples (progress, a slice of the design, a model with nothing to draw).

using Test
if !@isdefined(K)
    using Kompartment
    const K = Kompartment
end

const PROB_FIXTURES = get(ENV, "KOMPARTMENT_PROB_FIXTURES", "")

_unhex(s::AbstractString) = parse(Float64, s)
_unhex(v::AbstractVector) = Float64[parse(Float64, s) for s in v]
_same(a::Float64, b::Float64) = a === b || (isnan(a) && isnan(b))
_same(a::AbstractVector, b::AbstractVector) = length(a) == length(b) && all(i -> _same(Float64(a[i]), Float64(b[i])), eachindex(a))
_first_diff(a, b) = (i = findfirst(i -> !_same(Float64(a[i]), Float64(b[i])), eachindex(a)); i === nothing ? nothing : (i, a[i], b[i]))

"""A value as tools/prob_fixtures.py writes it: hex text, null for none (NaN), {"\$b": x} for a boolean."""
function _drawn(v)
    v === nothing && return NaN
    v isa AbstractDict && return Float64(v["\$b"])
    return parse(Float64, v)
end

"""A statistic as tools/prob_fixtures.py writes it: {"\$f": hex} for a float."""
_plain(v) = v isa AbstractDict ? (haskey(v, "\$f") ? parse(Float64, v["\$f"]) : Dict(k => _plain(x) for (k, x) in v)) :
            v isa AbstractVector ? Any[_plain(x) for x in v] : v

"""
A failure's message as the Python package words it. The one difference is
not this port's: Python's runner writes an initial inventory that is not a
number as JSON would (`null`), where the application and Julia's runner write
JavaScript's `String()` of it (`Infinity`, `NaN`).
"""
_python_words(msg::AbstractString) = replace(msg, r"(starts at|works out to) (Infinity|-Infinity|NaN)" => s"\1 null")

"""The keyword arguments of a case, in Julia's names."""
function _options(o)
    kw = Dict{Symbol,Any}(:seed => o["seed"])
    haskey(o, "latin") && (kw[:latin] = o["latin"])
    haskey(o, "keep") && (kw[:keep] = String[k for k in o["keep"]])
    haskey(o, "varied") && (kw[:varied] = String[k for k in o["varied"]])
    haskey(o, "range_") && (kw[:range] = (o["range_"][1] + 1):o["range_"][2])
    haskey(o, "tornado") && (kw[:tornado] = (low=Float64(o["tornado"]["low"]), high=Float64(o["tornado"]["high"])))
    return kw
end

"""
Within `rtol` of the series' largest finite value, NaN where the other is NaN:
for a model with a far-field path, whose deterministic run is not yet the
Python engine's to the last bit (about 1e-8 apart on farfield.json).
"""
function _close(a::AbstractVector, b::AbstractVector, rtol::Float64)
    length(a) == length(b) || return false
    scale = maximum(abs, filter(isfinite, b); init=0.0)
    return all(i -> _same(Float64(a[i]), b[i]) || abs(a[i] - b[i]) <= rtol * scale, eachindex(a))
end

function _check_run(prob, fx; rtol::Float64=0.0)
    @test prob.iterations == fx["iterations"]
    @test prob.range == (fx["from"]+1):fx["to"]
    @test prob.precision == fx["precision"]
    @test prob.names == fx["names"]
    plan = fx["plan"]
    @test length(prob.plan) == length(plan)
    for (e, p) in zip(prob.plan, plan)
        @test e["slot"] == p["slot"]
        @test e["name"] == p["name"]
        @test collect(e["index"]) == collect(p["index"])
        @test K.json_text(e["spec"]; indent=0) == K.json_text(p["spec"]; indent=0)
    end
    # The design: every value drawn, for every input.
    @test size(prob.samples) == (length(plan), length(prob.range))
    for (k, row) in enumerate(fx["samples"])
        ok = _same(prob.samples[k, :], _unhex(row))
        ok || @info "$(fx["name"]): input $(prob.names[k]) drawn differently" _first_diff(prob.samples[k, :], _unhex(row))
        @test ok
    end
    @test _same(prob.t, _unhex(fx["t"]))
    @test [o["label"] for o in prob.outputs] == [o["label"] for o in fx["outputs"]]
    @test [o["kind"] for o in prob.outputs] == [o["kind"] for o in fx["outputs"]]
    @test [o["offset"] for o in prob.outputs] == [o["offset"] for o in fx["outputs"]]
    # Every realisation of every series, realisation-major as Python holds them.
    for (w, flat) in enumerate(fx["values"])
        M = prob.values[w]
        got = vec(permutedims(M))
        ok = rtol == 0 ? _same(got, _unhex(flat)) : _close(got, _unhex(flat), rtol)
        ok || @info "$(fx["name"]): $(prob.outputs[w]["label"]) differs" _first_diff(got, _unhex(flat))
        @test ok
    end
    @test [(i["output"]["label"], i["output"]["offset"], i["k"]) for i in prob.inputs] ==
          [(i["label"], i["offset"], i["k"] + 1) for i in fx["inputs"]]
    @test Int.(prob.ran) == fx["ran"]
    st = _plain(fx["stats"])
    @test prob.stats["failed"] == st["failed"]
    @test _python_words.(prob.stats["trouble"]) == st["trouble"]
    @test prob.stats["seed"] == st["seed"]
    @test prob.stats["latin"] == st["latin"]
    @test prob.stats["sampled"] == st["sampled"]
    if haskey(st, "tornado")
        @test prob.stats["tornado"]["low"] == st["tornado"]["low"]
        @test prob.stats["tornado"]["high"] == st["tornado"]["high"]
        @test prob.stats["tornado"]["swung"] == st["tornado"]["swung"] .+ 1
    else
        @test prob.stats["correlated"] == st["correlated"]
        @test Float64(prob.stats["correlationAdjusted"]) === Float64(st["correlationAdjusted"])
        @test prob.stats["correlationProblems"] == st["correlationProblems"]
        @test [(g["name"], g["members"]) for g in prob.stats["groups"]] == [(g["name"], g["members"]) for g in st["groups"]]
    end
end

"""A time as the fixtures give it (from 0, "peak", "max" or none) in Julia's terms (from 1, :peak, :max, nothing)."""
_at(at) = at === nothing ? nothing : at isa Integer ? at + 1 : Symbol(at)
_where(w) = w === nothing ? nothing : w + 1

function _check_band(b, want)
    @test all(_same(y, _unhex(w)) for (y, w) in zip(b["q"], want["q"]))
    @test b["quantiles"] == Float64.(want["quantiles"])
    @test _same(b["mean"], _unhex(want["mean"]))
    @test _same(b["sd"].sd, _unhex(want["sd"]))
    @test b["sd"].n == want["n"]
    @test all(_same(b["med"][k], _unhex(v)) for (k, v) in want["med"])
    @test get(b, "flat", false) == want["flat"]
end

function _check_analysis(prob, an)
    @test vcat(K.labels(prob), [i["output"]["label"] for i in prob.inputs]) == vcat(an["labels"], an["inputs"])
    mask = Bool[m for m in an["mask"]]
    q = an["quantiles"]
    got = K.quantiles(prob, q["label"])
    @test all(_same(got[parse(Float64, k)], _unhex(v)) for (k, v) in q["q"])
    @test _same(K.realisations_mean(prob, q["label"]), _unhex(q["mean"]))
    ms = K.median_spread(prob, q["label"])
    @test all(_same(ms[k], _unhex(v)) for (k, v) in q["med"])
    if haskey(an, "tornado")
        for t in an["tornado"]
            got = K.tornado_table(prob, t["label"]; stat=t["stat"], at=t["at"] + 1)
            @test got["index"] == t["index"] + 1
            @test _same(got["central"], _unhex(t["central"]))
            @test length(got["rows"]) == length(t["rows"])
            for (r, w) in zip(got["rows"], t["rows"])
                @test (r["k"], r["name"], r["where"]) == (w[1] + 1, w[2], w[3])
                @test _same([r["low"], r["high"], r["lowInput"], r["highInput"], r["swing"]], _unhex(w[4:8]))
            end
        end
        return
    end
    for s in an["summary"]
        got = K.summary(prob, s["label"]; at=_at(s["at"]), mask=s["masked"] ? mask : nothing)
        @test got["at"] == _where(s["where"])
        if s["peaks"] === nothing
            @test got["peaks"] === nothing
        else
            @test (got["peaks"]["median"], got["peaks"]["low"], got["peaks"]["high"], got["peaks"]["n"]) ==
                  (_unhex(s["peaks"]["median"]), _unhex(s["peaks"]["low"]), _unhex(s["peaks"]["high"]), s["peaks"]["n"])
        end
        @test _same(got["column"], _unhex(s["column"]))
        sm = got["summary"]
        @test sm["n"] == s["n"]
        ok = _same([sm[k] for k in ("mean", "sd", "skewness", "kurtosis", "min", "max", "dkw")], _unhex(s["numbers"]))
        ok || @info "summary differs" s["label"] s["at"] s["masked"]
        @test ok
        @test _same(sm["meanBounds"], _unhex(s["bounds"]))
        @test _same([p.value for p in sm["percentiles"]], _unhex(s["percentiles"]))
    end
    for d in an["what_drove"]
        got = K.what_drove(prob, d["label"]; at=_at(d["at"]), translate=d["translate"], mask=d["masked"] ? mask : nothing)
        @test got["at"] == _where(d["where"])
        @test got["index"] == d["index"] + 1
        @test (got["kept"], got["using"]) == (d["kept"], d["using"])
        rows_ok = length(got["rows"]) == length(d["rows"]) &&
                  all((r["k"], r["name"], r["where"]) == (w[1] + 1, w[4], w[5]) &&
                      _same([r["pearson"], r["spearman"]], _unhex(w[2:3])) for (r, w) in zip(got["rows"], d["rows"]))
        rows_ok || @info "what drove it: rows differ" d["label"] d["at"] d["translate"] d["masked"]
        @test rows_ok
        @test all(c["k"] == w[1] + 1 && _same(c["y"], _unhex(w[2])) for (c, w) in zip(got["curves"], d["curves"]))
        m, w = got["measures"], d["measures"]
        if w === nothing
            @test m === nothing
        else
            ok = (m["ok"], m["used"], m["dropped"]) == (w["ok"], w["used"], w["dropped"]) &&
                 _same(m["r2"], _unhex(w["r2"])) && _same(m["src"], _unhex(w["src"])) && _same(m["b"], _unhex(w["b"])) &&
                 _same(m["pcc"], _unhex(w["pcc"])) && _same(m["s1"], _unhex(w["s1"]))
            ok || @info "what drove it: measures differ" d["label"] d["at"] d["translate"] d["masked"] m w
            @test ok
        end
    end
    for (b, want) in zip(K.bands(prob), an["bands"])
        _check_band(b, want)
    end
    for (b, want) in zip(K.bands(prob; percentiles=[0.1, 0.9], mask=mask), an["bands_masked"])
        _check_band(b, want)
    end
end

const PROB_EXAMPLES = joinpath(@__DIR__, "..", "..", "..", "examples")

@testset "probabilistic runs: progress, slices, refusals" begin
    m = K.load(joinpath(PROB_EXAMPLES, "biosphere.json"))
    heard = Tuple{Int,Int}[]
    whole = K.run_probabilistic(m, 30; seed=3, keep=["Dose"], threads=Threads.nthreads(),
                                on_progress=(done, total) -> push!(heard, (done, total)))
    # Once per realisation, one at a time, rising, whichever thread finished it.
    @test heard == [(k, 30) for k in 1:30]
    @test whole.stats["threads"] == min(Threads.nthreads(), 29)
    @test size(whole.values[1]) == (30, length(whole.t))
    @test size(whole.samples) == (length(whole.plan), 30)
    @test whole.ran == ones(UInt8, 30)
    @test K.labels(whole) == ["Dose [I-129]", "Dose [Cl-36]", "Dose [Tc-99]", "Dose [Se-79]"]
    @test whole["Dose [I-129]"] === whole.values[1]
    @test K.sample(whole, "Kd[I-129]") == whole.samples[findfirst(==("Kd[I-129]"), whole.names), :]
    # A slice of the design is those rows of the whole, to the bit.
    part = K.run_probabilistic(m, 30; seed=3, keep=["Dose"], range=11:20, threads=2)
    @test part.range == 11:20
    @test all(isequal(part.values[w], whole.values[w][11:20, :]) for w in eachindex(part.values))
    @test isequal(part.samples, whole.samples[:, 11:20])
    # The progress line, on a stream that is not a terminal: a line per tenth, and the last word.
    io = IOBuffer()
    K.run_probabilistic(m, 20; seed=3, keep=["Dose"], progress=io, threads=1)
    text = String(take!(io))
    @test startswith(text, "Probabilistic run [------------------------] 0/20 realisations")
    @test occursin("Probabilistic run: 20 realisations in ", text)
    # Nothing to draw: refused in the application's words.
    @test_throws ArgumentError K.run_probabilistic(K.load(joinpath(PROB_EXAMPLES, "decay-chain.json")), 5)
    @test_throws ArgumentError K.run_probabilistic(m, 5; gsa=Dict("method" => "sobol"))
    # A tornado: one central run, then each input low and high.
    tor = K.run_tornado(m; keep=["Dose"], threads=Threads.nthreads())
    @test tor.iterations == 2 * length(tor.plan) + 1
    @test tor.stats["tornado"]["swung"] == collect(1:length(tor.plan))
    t = K.tornado_table(tor, "Dose [I-129]")
    @test length(t["rows"]) == length(tor.plan)
    @test issorted([r["swing"] for r in t["rows"]]; rev=true)
end

@testset "probabilistic runs against the Python package" begin
    if isempty(PROB_FIXTURES) || !isdir(PROB_FIXTURES)
        @info "KOMPARTMENT_PROB_FIXTURES not set: probabilistic parity tests skipped"
        return
    end
    units = K.parse_json(read(joinpath(PROB_FIXTURES, "units.json"), String))

    @testset "named streams" begin
        for s in units["streams"]
            g = K.stream_for(s["seed"], s["name"])
            @test Int(g.a) == s["state"]
            @test [K.next_uniform!(g) for _ in 1:5] == _unhex(s["draws"])
        end
    end

    @testset "columns of uniforms" begin
        for c in units["uniforms"]
            u = K.uniforms(c["n"], K.stream_for(c["seed"], c["name"]); latin=c["latin"])
            @test _same(u, _unhex(c["u"]))
        end
    end

    @testset "a value from every kind of distribution" begin
        us = _unhex(units["us"])
        for d in units["draws"]
            spec = d["spec"]
            got = [K.value_at_probability(spec, u, (k - 1) % 11) for (k, u) in enumerate(us)]
            want = Float64[_drawn(v) for v in d["value"]]
            ok = _same(got, want)
            ok || @info "value_at_probability differs" spec _first_diff(got, want)
            @test ok
            haskey(d, "error") && continue
            @test _same([K.pdf_quantile(spec, u) for u in us], _unhex(d["quantile"]))
            xs = _unhex(d["x"])
            @test _same([K.pdf_cdf(spec, x) for x in xs], _unhex(d["cdf"]))
            c = K.probability_cuts(spec)
            @test (c.lo, c.hi, c.cut, c.reversed) == (_unhex(d["cuts"][1]), _unhex(d["cuts"][2]), d["cuts"][3], d["cuts"][4])
        end
    end

    @testset "the normal CDF and quantile" begin
        n = units["normal"]
        zs = _unhex(n["z"])
        @test _same([K.normal_phi(z) for z in zs], _unhex(n["phi"]))
        @test _same([K.kf_erfc(z) for z in zs], _unhex(n["erfc"]))
        @test _same([K.kf_erf(z) for z in zs], _unhex(n["erf"]))
        ps = _unhex(n["p"])
        @test _same([something(K.normal_probit(p), NaN) for p in ps], [v === nothing ? NaN : _unhex(v) for v in n["probit"]])
        @test _same([K.normal_quantile(p) for p in ps], _unhex(n["quantile"]))
    end

    @testset "correlation pairs and their problems" begin
        p = units["pairs"]
        got = K.correlation_pairs(p["project"], p["names"])
        @test [(x.a, x.b, x.r) for x in got.pairs] == [(a + 1, b + 1, _unhex(r)) for (a, b, r) in p["pairs"]]
        @test got.problems == p["problems"]
    end

    @testset "what a run of a shape holds" begin
        for e in units["estimates"]
            series, times, iterations = e["shape"]
            for precision in ("double", "float32")
                got = K.estimate(series, times, iterations, precision)
                @test (got.bytes, got.text) == (e[precision]["bytes"], e[precision]["text"])
            end
            @test K.hold_precision(series, times, iterations) == e["hold"]
        end
    end

    @testset "Iman-Conover" begin
        for c in units["iman_conover"]
            columns = [_unhex(b) for b in c["before"]]
            pairs = [(a=a + 1, b=b + 1, r=Float64(r)) for (a, b, r) in c["pairs"]]
            res = K.iman_conover(columns, pairs, c["names"], 21)
            @test res.columns == c["moved"] .+ 1
            @test Float64(res.adjusted) === _unhex(c["adjusted"])
            for (col, want) in zip(columns, c["after"])
                @test _same(col, _unhex(want))
            end
        end
    end

    runs = joinpath(PROB_FIXTURES, "runs")
    for f in sort(filter(endswith(".json"), readdir(runs)))
        fx = K.parse_json(read(joinpath(runs, f), String))
        @testset "$(fx["name"])" begin
            raw = K.read_model_file(joinpath(PROB_FIXTURES, "models", fx["model"]))
            o = fx["options"]
            kw = _options(o)
            iterations = haskey(o, "tornado") ? nothing : o["iterations"]
            if haskey(fx, "error")
                # Refused as the Python package refuses it, in the same words.
                message = try
                    K.run_probabilistic(K.Project(raw), iterations; kw...)
                    nothing
                catch e
                    e isa ArgumentError ? e.msg : sprint(showerror, e)
                end
                @test message == split(fx["error"], ": "; limit=2)[2]
                continue
            end
            # Every thread Julia has, then one: the same numbers both ways.
            many = K.run_probabilistic(K.Model(raw), iterations; threads=Threads.nthreads(), kw...)
            farfield = !isempty(something(get(raw, "farfields", nothing), Any[]))
            _check_run(many, fx; rtol=farfield ? 1e-6 : 0.0)
            # The result file the user's script writes, byte for byte, where the package has the writer.
            if haskey(fx, "h5") && isdefined(K, :probabilistic_tree) && isdefined(K, :write_hdf5)
                @testset "result file" begin
                    for (want, file) in fx["h5"]["files"]
                        bytes = K.write_hdf5(K.probabilistic_tree(many, want; project=raw, now=fx["h5"]["now"]))
                        @test bytes == read(joinpath(PROB_FIXTURES, "h5", file))
                    end
                end
            end
            haskey(fx, "analysis") && @testset "analysis" _check_analysis(many, fx["analysis"])
            one = K.run_probabilistic(K.Project(raw), iterations; threads=1, kw...)
            @test one.stats["threads"] == 1
            @test all(isequal(a, b) for (a, b) in zip(one.values, many.values))
            @test isequal(one.samples, many.samples)
            @test one.ran == many.ran
            @test one.stats["trouble"] == many.stats["trouble"]
        end
    end
end
