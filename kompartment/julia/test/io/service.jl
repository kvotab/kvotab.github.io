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

@testset "the analyses on the Julia engine, and those it leaves to the page" begin
    bio = read(joinpath(EXAMPLES, "biosphere.json"), String)
    dir = mktempdir()
    job(id, kind, options) = K.json_text(Dict("op" => "job", "id" => id, "kind" => kind, "model" => bio,
                                              "options" => options, "out" => joinpath(dir, "$id.zip")); indent=0)
    lines = [
        job("t1", "probabilistic", Dict("seed" => 3, "tornado" => Dict("low" => 0.05, "high" => 0.95))),
        job("r1", "replay", Dict("index" => 5, "seed" => 11, "iterations" => 20)),
        job("g1", "probabilistic", Dict("gsa" => Dict("method" => "morris", "options" => Dict()))),
        job("c1", "calibrate", Dict()),
        job("s1", "local-sensitivity", Dict("parameters" => ["leachRate[I-129]"])),
    ]
    out = IOBuffer()
    K.serve_stdio(; input=IOBuffer(join(lines, "\n") * "\n"), output=out)
    events = [K.parse_json(l) for l in split(String(take!(out)), '\n') if !isempty(l)]
    ends = Dict(e["id"] => e for e in events if get(e, "event", "") in ("done", "error"))
    @test ends["t1"]["event"] == "done" && ends["r1"]["event"] == "done"
    # A tornado's swung inputs counted from 0, as the page counts them.
    meta = K.parse_json(String(copy(K._ds_unzip(read(joinpath(dir, "t1.zip")))["results/sample/meta.json"])))
    @test meta["iterations"] == 31 && meta["stats"]["tornado"]["swung"] == collect(0:14)
    # A realisation replayed, counted from 0 as well.
    replayed = K.parse_json(String(copy(K._ds_unzip(read(joinpath(dir, "r1.zip")))["results/meta.json"])))["replayed"]
    @test (replayed["index"], replayed["iterations"], length(replayed["values"])) == (5, 20, 15)
    # What it does not do, said before anything runs, for the page to do itself.
    for id in ("g1", "c1", "s1")
        @test ends[id]["event"] == "error" && ends[id]["name"] == "NotOnThisEngine"
    end
end
