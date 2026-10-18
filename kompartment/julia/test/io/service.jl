# The engine behind the application's local server (src/service.jl), and the
# archive a probabilistic run goes back to the page in (src/io/sample.jl): the
# layout the page reads, and the service's protocol, a line of JSON at a time.

using Test
using Kompartment
const K = Kompartment

const EXAMPLES = joinpath(@__DIR__, "..", "..", "..", "examples")

@testset "a probabilistic run as the archive holds it" begin
    prob = run_probabilistic(K.load(joinpath(EXAMPLES, "biosphere.json")), 9; seed=11, threads=1)
    entries = Dict(K.sample_entries(prob; stamp="then"))
    meta = K.parse_json(String(copy(entries["results/sample/meta.json"])))
    n, times = prob.iterations, length(prob.t)
    @test (meta["format"], meta["kind"], meta["iterations"], meta["times"]) == (1, "kompartment-sample", n, times)
    @test meta["kept"] == length(prob.values)
    series = reinterpret(Float64, entries["results/sample/series.f64"])
    @test length(series) == length(prob.values) * n * times
    # Realisation after realisation, each one's times together.
    @test series[1:times] == prob.values[1][1, :]
    @test series[times+1:2times] == prob.values[1][2, :]
    draws = reinterpret(Float64, entries["results/sample/draws.f64"])
    @test draws[1:n] == prob.samples[1, :]
    kept = length(prob.outputs)
    @test meta["flat"] == vcat(zeros(Int, kept), ones(Int, length(prob.inputs)))
    # The column of draws a varied parameter came from, counted from 0 as the page counts.
    @test meta["drawnFrom"][1:kept] == fill(-1, kept)
    @test meta["drawnFrom"][kept+1:end] == [Int(i["k"]) - 1 for i in prob.inputs]
    @test entries["results/sample/ran.u8"] == prob.ran
    archive = K._ds_unzip(K.sample_archive(prob))
    @test haskey(archive, "results/sample/meta.json")
    @test any(k -> endswith(k, ".json") && !startswith(k, "results/"), keys(archive))
end

@testset "the service: jobs in, and what became of each out" begin
    four = read(joinpath(EXAMPLES, "four-compartment.json"), String)
    bio = read(joinpath(EXAMPLES, "biosphere.json"), String)
    dir = mktempdir()
    job(id, kind, model; options...) = K.json_text(Dict("op" => "job", "id" => id, "kind" => kind, "model" => model,
                                                        "options" => Dict(string(k) => v for (k, v) in options),
                                                        "out" => joinpath(dir, "$id.zip")); indent=0)
    lines = [
        # Stopped before it was started: it says so, and is not run.
        K.json_text(Dict("op" => "cancel", "id" => "c1"); indent=0),
        job("r1", "run", four),
        job("p1", "probabilistic", bio; iterations=6, seed=4),
        job("c1", "run", four),
        job("x1", "draw", four),
    ]
    out = IOBuffer()
    K.serve_stdio(; input=IOBuffer(join(lines, "\n") * "\n"), output=out)
    events = [K.parse_json(l) for l in split(String(take!(out)), '\n') if !isempty(l)]
    @test events[1]["event"] == "ready" && events[1]["engine"] == "julia"
    ends = Dict(e["id"] => e["event"] for e in events if get(e, "event", "") in ("done", "error", "cancelled"))
    @test ends == Dict("r1" => "done", "p1" => "done", "c1" => "cancelled", "x1" => "error")
    @test haskey(K._ds_unzip(read(joinpath(dir, "r1.zip"))), "results/meta.json")
    @test haskey(K._ds_unzip(read(joinpath(dir, "p1.zip"))), "results/sample/series.f64")
    @test !isfile(joinpath(dir, "c1.zip"))
    problem = only(e for e in events if get(e, "id", "") == "x1" && e["event"] == "error")
    # The message without its type in front: the page shows the name beside it.
    @test problem["name"] == "ArgumentError" && startswith(problem["message"], "'draw' is not a kind of job")
end

@testset "a kept run: sent without its states, asked about, let go of" begin
    four = read(joinpath(EXAMPLES, "four-compartment.json"), String)
    made = K.run(K.from_json(four))
    labels = [String(o["label"]) for o in K.outputs(made)]
    dir = mktempdir()
    inp = Pipe()
    Base.link_pipe!(inp; reader_supports_async=true, writer_supports_async=true)
    outp = Pipe()
    Base.link_pipe!(outp; reader_supports_async=true, writer_supports_async=true)
    server = @async K.serve_stdio(; input=inp.out, output=outp.in)
    ask(d) = (println(inp.in, K.json_text(d; indent=0)); flush(inp.in))
    # What is said under `id`, once it is done or refused.
    ended(id) = while true
        e = K.parse_json(readline(outp.out))
        get(e, "id", "") == id && get(e, "event", "") in ("done", "error") && return e
    end
    ask(Dict("op" => "job", "id" => "r1", "kind" => "run", "model" => four, "options" => Dict("keep" => true),
             "out" => joinpath(dir, "r1.zip")))
    @test ended("r1")["event"] == "done"
    light = K._ds_unzip(read(joinpath(dir, "r1.zip")))
    meta = K.parse_json(String(copy(light["results/meta.json"])))
    @test !haskey(light, "results/y.f64") && meta["onEngine"] === true && haskey(meta, "massBalance")
    # What the page reads of the run besides its series, so that it need not build the model.
    @test [o["label"] for o in meta["page"]["outputs"]] == labels
    @test meta["page"]["stateCount"] == length(made.y[1]) && haskey(meta["page"], "jacobian")
    # Every series, by label, as a run here works them out.
    ask(Dict("op" => "series", "id" => "q1", "run" => "r1", "labels" => labels, "out" => joinpath(dir, "q1.f64")))
    @test ended("q1")["event"] == "done"
    @test reinterpret(Float64, read(joinpath(dir, "q1.f64"))) == reduce(vcat, K.series_many(made, labels))
    ask(Dict("op" => "series", "id" => "q2", "run" => "r1", "labels" => ["Nowhere"], "out" => joinpath(dir, "q2")))
    @test occursin("no series called 'Nowhere'", ended("q2")["message"])
    # The whole run, states and all.
    ask(Dict("op" => "archive", "id" => "q3", "run" => "r1", "out" => joinpath(dir, "q3.zip")))
    @test ended("q3")["event"] == "done"
    @test haskey(K._ds_unzip(read(joinpath(dir, "q3.zip"))), "results/y.f64")
    # Let go of, and then said to be gone.
    ask(Dict("op" => "forget", "id" => "q4", "run" => "r1"))
    @test ended("q4")["event"] == "done"
    ask(Dict("op" => "series", "id" => "q5", "run" => "r1", "labels" => labels, "out" => joinpath(dir, "q5.f64")))
    @test occursin("no longer holds that run", ended("q5")["message"])
    close(inp.in)
    wait(server)
end

@testset "a kept sample: sent without its series, asked about, let go of" begin
    bio = read(joinpath(EXAMPLES, "biosphere.json"), String)
    prob = run_probabilistic(K.from_json(bio), 10; seed=4, threads=1)
    n, times = prob.iterations, length(prob.t)
    count = length(prob.outputs) + length(prob.inputs)
    kept, varied = length(prob.outputs), length(prob.inputs)
    dir = mktempdir()
    inp = Pipe()
    Base.link_pipe!(inp; reader_supports_async=true, writer_supports_async=true)
    outp = Pipe()
    Base.link_pipe!(outp; reader_supports_async=true, writer_supports_async=true)
    server = @async K.serve_stdio(; input=inp.out, output=outp.in)
    ask(d) = (println(inp.in, K.json_text(d; indent=0)); flush(inp.in))
    ended(id) = while true
        e = K.parse_json(readline(outp.out))
        get(e, "id", "") == id && get(e, "event", "") in ("done", "error") && return e
    end
    doubles(name) = reinterpret(Float64, read(joinpath(dir, name)))
    ask(Dict("op" => "job", "id" => "p1", "kind" => "probabilistic", "model" => bio,
             "options" => Dict("iterations" => 10, "seed" => 4, "keep" => true, "workers" => 1),
             "out" => joinpath(dir, "p1.zip")))
    @test ended("p1")["event"] == "done"
    light = K._ds_unzip(read(joinpath(dir, "p1.zip")))
    meta = K.parse_json(String(copy(light["results/sample/meta.json"])))
    @test meta["onEngine"] === true && !any(k -> occursin("series.", k), keys(light))
    @test haskey(light, "results/sample/draws.f64") && haskey(light, "results/sample/ran.u8")
    @test (meta["iterations"], meta["times"], length(meta["outputs"])) == (n, times, count)
    # Per series: a run per percentile, the mean, the deviation and its count,
    # and the median's two intervals -- Python's layout.
    laid_out(bs) = reduce(vcat, [vcat(b["q"]..., b["mean"], b["sd"].sd, Float64.(b["sd"].n), b["med"]["errLo"],
                                      b["med"]["errHi"], b["med"]["bodyLo"], b["med"]["bodyHi"]) for b in bs])
    same(a, b) = length(a) == length(b) && reinterpret(UInt64, collect(a)) == reinterpret(UInt64, collect(b))
    mask = [1, 1, 0, 1, 0, 1, 1, 1, 0, 1]
    ask(Dict("op" => "bands", "id" => "q1", "run" => "p1", "percentiles" => [0.05, 0.5, 0.95], "mask" => nothing,
             "out" => joinpath(dir, "q1")))
    @test ended("q1")["event"] == "done"
    @test same(doubles("q1"), laid_out(K.bands(prob; percentiles=[0.05, 0.5, 0.95])))
    ask(Dict("op" => "bands", "id" => "q2", "run" => "p1", "percentiles" => [0.25, 0.75], "mask" => mask,
             "out" => joinpath(dir, "q2")))
    @test ended("q2")["event"] == "done"
    @test same(doubles("q2"), laid_out(K.bands(prob; percentiles=[0.25, 0.5, 0.75], mask)))
    @test length(doubles("q2")) == 10 * (kept * times + varied)
    # Series numbered from 0 as the meta lists them: the kept ones, then each varied parameter.
    ask(Dict("op" => "realisations", "id" => "q3", "run" => "p1", "series" => [1, kept], "out" => joinpath(dir, "q3")))
    @test ended("q3")["event"] == "done"
    got = doubles("q3")
    @test same(got[1:n*times], vec(permutedims(Float64.(prob.values[2]))))
    @test same(got[n*times+1:end], vec(K._an_matrix(prob, kept + 1)))
    ask(Dict("op" => "column", "id" => "q4", "run" => "p1", "series" => [0, kept], "at" => 7, "out" => joinpath(dir, "q4")))
    @test ended("q4")["event"] == "done"
    @test same(doubles("q4"), vcat(Float64.(prob.values[1][:, 8]), K._an_matrix(prob, kept + 1)[:, 1]))
    ask(Dict("op" => "realisation", "id" => "q5", "run" => "p1", "series" => [2, kept + 1], "index" => 3,
             "out" => joinpath(dir, "q5")))
    @test ended("q5")["event"] == "done"
    @test same(doubles("q5"), vcat(Float64.(prob.values[3][4, :]), K._an_matrix(prob, kept + 2)[4, :]))
    # Asked wrongly, or what a run is asked: said so.
    ask(Dict("op" => "column", "id" => "q6", "run" => "p1", "series" => [count], "at" => 0, "out" => joinpath(dir, "q6")))
    @test occursin("no series $count", ended("q6")["message"])
    ask(Dict("op" => "bands", "id" => "q7", "run" => "p1", "percentiles" => [0.5], "mask" => [1, 0], "out" => joinpath(dir, "q7")))
    @test occursin("2 entries for 10 realisations", ended("q7")["message"])
    ask(Dict("op" => "series", "id" => "q8", "run" => "p1", "labels" => ["A"], "out" => joinpath(dir, "q8")))
    @test occursin("'series' is not something", ended("q8")["message"])
    # The whole sample, series and all.
    ask(Dict("op" => "archive", "id" => "q9", "run" => "p1", "out" => joinpath(dir, "q9.zip")))
    @test ended("q9")["event"] == "done"
    @test haskey(K._ds_unzip(read(joinpath(dir, "q9.zip"))), "results/sample/series.f64")
    # Let go of, and then said to be gone.
    ask(Dict("op" => "forget", "id" => "q10", "run" => "p1"))
    @test ended("q10")["event"] == "done"
    ask(Dict("op" => "column", "id" => "q11", "run" => "p1", "series" => [0], "at" => 0, "out" => joinpath(dir, "q11")))
    @test occursin("no longer holds that run", ended("q11")["message"])
    close(inp.in)
    wait(server)
end

@testset "the analyses on the Julia engine" begin
    bio = read(joinpath(EXAMPLES, "biosphere.json"), String)
    decay = read(joinpath(EXAMPLES, "exponential-decay.json"), String)
    dir = mktempdir()
    job(id, kind, options; model=bio, out="$id.zip") =
        K.json_text(Dict("op" => "job", "id" => id, "kind" => kind, "model" => model, "options" => options,
                         "out" => joinpath(dir, out)); indent=0)
    lines = [
        job("t1", "probabilistic", Dict("seed" => 3, "tornado" => Dict("low" => 0.05, "high" => 0.95))),
        job("r1", "replay", Dict("index" => 5, "seed" => 11, "iterations" => 20)),
        job("g1", "probabilistic", Dict("seed" => 4, "blocks" => ["Dose"],
                                        "gsa" => Dict("method" => "morris",
                                                      "options" => Dict("trajectories" => 2, "points" => 3)))),
        job("c1", "calibrate", Dict("targets" => [Dict("output" => "y", "when" => "at", "time" => 2, "value" => 0.2)],
                                    "variables" => [Dict("key" => "k", "lower" => 0.1, "upper" => 3)],
                                    "method" => "lm", "maxEvals" => 40); model=decay, out="c1.json"),
        job("s1", "local-sensitivity", Dict("parameters" => ["leachRate[I-129]"]); out="s1.json"),
        job("e1", "calibrate", Dict("targets" => [], "variables" => []); model=decay, out="e1.json"),
    ]
    out = IOBuffer()
    K.serve_stdio(; input=IOBuffer(join(lines, "\n") * "\n"), output=out)
    events = [K.parse_json(l) for l in split(String(take!(out)), '\n') if !isempty(l)]
    ends = Dict(e["id"] => e for e in events if get(e, "event", "") in ("done", "error"))
    @test all(ends[id]["event"] == "done" for id in ("t1", "r1", "g1", "c1", "s1"))
    # A tornado's swung inputs counted from 0, as the page counts them.
    meta = K.parse_json(String(copy(K._ds_unzip(read(joinpath(dir, "t1.zip")))["results/sample/meta.json"])))
    @test meta["iterations"] == 31 && meta["stats"]["tornado"]["swung"] == collect(0:14)
    # A realisation replayed, counted from 0 as well.
    replayed = K.parse_json(String(copy(K._ds_unzip(read(joinpath(dir, "r1.zip")))["results/meta.json"])))["replayed"]
    @test (replayed["index"], replayed["iterations"], length(replayed["values"])) == (5, 20, 15)
    # A sensitivity design's runs, each factor's inputs counted from 0: the points
    # are the design's, as the page draws it.
    meta = K.parse_json(String(copy(K._ds_unzip(read(joinpath(dir, "g1.zip")))["results/sample/meta.json"])))
    @test meta["iterations"] == 6 && meta["stats"]["gsa"]["method"] == "morris"
    @test [f["members"] for f in meta["stats"]["gsa"]["factors"]] == [[k] for k in 0:14]
    proj = K.project(K.from_json(bio))
    d = K.design_for(proj, K.build_system(proj); seed=4,
                     gsa=Dict("method" => "morris", "options" => Dict("trajectories" => 2, "points" => 3)))
    draws = K._ds_unzip(read(joinpath(dir, "g1.zip")))["results/sample/draws.f64"]
    @test reinterpret(Float64, draws) == vec(permutedims(d.values))
    # A calibration: each step's best said as it goes, and the answer as JSON.
    @test any(e -> get(e, "id", "") == "c1" && e["event"] == "progress" && haskey(e, "detail") &&
                   haskey(e["detail"], "best"), events)
    c1 = K.parse_json(read(joinpath(dir, "c1.json"), String))
    @test c1["matched"] && c1["method"] == "lm" && isapprox(c1["values"][1]["value"], log(5) / 2; rtol=1e-4)
    # dy/dp: every state the page shows, with its derivative.
    s1 = K.parse_json(read(joinpath(dir, "s1.json"), String))
    @test [c["label"] for c in s1["chosen"]] == ["leachRate[I-129]"] && s1["stats"]["states"] == 32
    @test length(s1["states"]) == 16 && s1["states"][1]["name"] == "Repository [I-129]"
    @test length(s1["states"][1]["y"]) == length(s1["t"]) && length(s1["states"][1]["sens"]) == 1
    # A calibration that cannot start says why.
    @test ends["e1"]["event"] == "error" && ends["e1"]["name"] == "OptimiseError" &&
          ends["e1"]["message"] == "No endpoint has been given a target value."
end
