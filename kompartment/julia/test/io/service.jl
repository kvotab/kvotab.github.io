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
