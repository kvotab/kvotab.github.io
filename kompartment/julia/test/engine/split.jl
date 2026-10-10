# Solving a model in its independent parts (src/engine/split.jl), as the
# Python package's tests hold its split (python/tests/test_engine_split.py):
#
# * the partition, the names states are filed back by, their materials, the
#   jobs, every plan -- its bins included -- and every refusal, against the
#   Python package's (tools/split_fixtures.py), with its constants put in;
# * a split run against the Python package's split run of the same bins, to
#   the bit: the same parts, built the same, solved the same;
# * a split run against the whole model's, to the tolerance, and what a split
#   carries back: the recorders' histories, the far-field layers, the
#   materials a part names outright.
#
#     PYTHONPATH=../python python3 tools/split_fixtures.py <scratch>/split
#     KOMPARTMENT_SPLIT_FIXTURES=<scratch>/split julia --project=. -t 4 test/engine/split.jl
#
# Set KOMPARTMENT_SPLIT_TIMING=1 for a timing on the Python package's made-up model of
# independent decay chains, whole against split (julia --threads=auto).

module SplitTests

using Test
using Kompartment
const K = Kompartment

const FIXTURES = get(ENV, "KOMPARTMENT_SPLIT_FIXTURES", "")
# What auto learns from these runs is kept in this process only, and nothing kept from runs
# before decides them.
haskey(ENV, "KOMPARTMENT_SPLIT_MEMORY") || (ENV["KOMPARTMENT_SPLIT_MEMORY"] = "0")
const EXAMPLES = joinpath(@__DIR__, "..", "..", "..", "examples")

#: How far a split run may be from the whole run, as a share of each series' peak: what the
#: application's and the Python package's own tests allow.
const AGREE = 2e-4

const SIM = K.JDict("start_time" => 0, "end_time" => 100, "output_points" => 21, "spacing" => "linear",
                    "solver" => "ndf", "rtol" => 1e-8, "abstol" => 1e-14, "time_unit" => "year")

example(name) = K.read_model_file(joinpath(EXAMPLES, "$name.json"))

function with_split(raw, mode; settings...)
    r = K.jcopy(raw)
    sim = get!(r, "simulation", K.JDict())
    sim["split"] = mode
    for (k, v) in settings
        sim[String(k)] = v
    end
    return K.Project(r)
end

unhex(v) = Float64[parse(Float64, s) for s in v]
same(a::AbstractVector, b::AbstractVector) = length(a) == length(b) && all(i -> a[i] === b[i], eachindex(a))

"""The largest difference over every series, each as a share of its peak."""
function worst(a::K.Results, b::K.Results)
    outs = K.outputs(a)
    theirs = Dict(o["label"] => o for o in K.outputs(b))
    ca = K.series_many(a, outs)
    cb = K.series_many(b, [theirs[o["label"]] for o in outs])
    out = 0.0
    for (x, y) in zip(ca, cb)
        keep = [i for i in eachindex(x) if isfinite(x[i]) && isfinite(y[i])]
        isempty(keep) && continue
        peak = maximum(abs, x[keep])
        out = max(out, maximum(abs.(x[keep] .- y[keep])) / (peak == 0 ? 1.0 : peak))
    end
    return out
end

# --- made-up models (the Python package's own) ---------------------------------------------------

"""`count` decay chains of `length` made-up nuclides through `compartments` compartments in a line."""
function chains(count::Int, length::Int, compartments::Int; points::Int=40, rtol::Float64=1e-6)
    letters = "abcdefghijklmnopqrstuvwxyz"
    names = String[]
    half = K.JDict()
    pairs = Any[]
    for c in 0:count-1
        element = "Q" * letters[c%26+1] * (c < 26 ? "" : string(letters[c÷26+1]))
        chain = ["$element-$(100 + k)" for k in 0:length-1]
        for (k, name) in enumerate(chain)
            push!(names, name)
            half[name] = K.cpow(10.0, 1 + (((k - 1) * 7 + c * 3) % 11) * 0.5)
        end
        append!(pairs, Any[Any[chain[k], chain[k+1], 1.0] for k in 1:length-1])
    end
    return K.JDict(
        "name" => "$count chains of $length through $compartments", "nuclides" => Any[names...],
        "half_lives" => half, "chains" => pairs,
        "simulation" => K.JDict("start_time" => 0, "end_time" => 1e5, "output_points" => points, "spacing" => "log",
                                "solver" => "ndf", "rtol" => rtol, "abstol" => 1e-6, "time_unit" => "year"),
        "parameters" => Any[K.JDict("name" => "k$j", "value" => K.cpow(10.0, -1 - j * 0.7), "index_lists" => Any[])
                            for j in 0:4],
        "compartments" => Any[K.JDict("name" => "C$i", "initial" => i == 0 ? "1e6" : "0",
                                      "index_lists" => Any["Radionuclides"]) for i in 0:compartments-1],
        "transfers" => Any[K.JDict("name" => "T$i", "from" => "C$i", "to" => "C$(i + 1)", "rate" => "k$(i % 5)",
                                   "index_lists" => Any["Radionuclides"]) for i in 0:compartments-2])
end

"""Two nuclides through three compartments: two parts, one per nuclide."""
function two(; extra...)
    m = K.JDict("name" => "two", "nuclides" => Any["Cs-137", "Sr-90"], "simulation" => K.jcopy(SIM),
                "parameters" => Any[K.JDict("name" => "k1", "value" => 0.2), K.JDict("name" => "k2", "value" => 0.05)],
                "compartments" => Any[K.JDict("name" => n, "initial" => n == "A" ? "1" : "0") for n in ("A", "B", "C")],
                "transfers" => Any[K.JDict("name" => "AB", "from" => "A", "to" => "B", "rate" => "k1"),
                                   K.JDict("name" => "BC", "from" => "B", "to" => "C", "rate" => "k2")])
    for (k, v) in extra
        m[String(k)] = v
    end
    return m
end

const RECORDING = two(min_maxes=Any[K.JDict("name" => "PeakB", "target" => "B", "operation" => "max"),
                                    K.JDict("name" => "LowA", "target" => "A", "operation" => "min")],
                      running_means=Any[K.JDict("name" => "MeanB", "target" => "B")])
const ACROSS = two(index_reductions=Any[K.JDict("name" => "TotalB", "target" => "B", "operation" => "sum",
                                                "per_nuclide" => false, "index_lists" => Any[])],
                   min_maxes=Any[K.JDict("name" => "PeakTotal", "target" => "TotalB", "operation" => "max",
                                         "index_lists" => Any[])])
const PINNED = K.JDict(
    "name" => "pinned", "nuclides" => Any["Cs-137", "Sr-90"],
    "simulation" => merge(K.jcopy(SIM), K.JDict("output_points" => 11, "rtol" => 1e-9)),
    "parameters" => Any[K.JDict("name" => "Coef", "index_lists" => Any["Radionuclides"], "value" => 0.01,
                                "entries" => Any[K.JDict("index" => K.JDict("Radionuclides" => "Cs-137"),
                                                         "value" => 0.05)])],
    "compartments" => Any[K.JDict("name" => "A", "initial" => "1"), K.JDict("name" => "B", "initial" => "0")],
    "transfers" => Any[K.JDict("name" => "AB", "from" => "A", "to" => "B", "rate" => "Coef[Cs-137]")])

"""The far-field example with I-129 beside its U-238 chain: two parts on one path's layers."""
function farfield_two_parts()
    model = example("farfield")
    model["nuclides"] = Any[model["nuclides"]..., "I-129"]
    model["simulation"]["spacing"] = "log"
    delete!(model["simulation"], "output_times")
    # One of its expressions reads U-238 by name, which a part without it refuses.
    model["expressions"] = Any[]
    push!(get!(model["compartments"][1], "entries", Any[]),
          K.JDict("index" => K.JDict("Radionuclides" => "I-129"), "initial" => "1e12"))
    kd = first(p for p in model["parameters"] if p["name"] == "Kd_matrix")
    push!(kd["entries"], K.JDict("index" => K.JDict("Radionuclides" => "I-129"), "value" => 0))
    return model
end

# --- the plan, by hand and against the Python package's --------------------------------------------

"""A pattern from the application's compressed columns (counted from 0)."""
function pattern(n, colptr, rowval)
    rows = Int[]
    cols = Int[]
    for j in 1:n, p in colptr[j]+1:colptr[j+1]
        push!(rows, rowval[p] + 1)
        push!(cols, j)
    end
    return K.Pattern(n, rows, cols)
end

@testset "the partition, by hand (the application's cases)" begin
    three = K.state_partition(pattern(5, [0, 2, 4, 5, 7, 9], [0, 1, 0, 1, 2, 3, 4, 3, 4]))
    @test three.count == 3
    @test three.of == [0, 0, 1, 2, 2]
    @test three.sizes == [2, 1, 2]
    @test three.largest == 2
    # One direction is enough to join two states.
    one_way = K.state_partition(pattern(4, [0, 1, 2, 3, 4], [3, 1, 2, 3]))
    @test one_way.count == 3
    @test one_way.of[1] == one_way.of[4]
    # Numbered by first appearance, whatever the components' own order.
    @test K.state_partition(pattern(4, [0, 1, 2, 3, 4], [2, 3, 0, 1])).of == [0, 1, 0, 1]
    @test K.state_partition(nothing).count == 0
end

const JULIA_WORDS = Dict(
    "this run is itself in a worker process, which does not start more" =>
        "this run is itself one of several side by side, which do not start more",
    "there is one core to run on" => "there is one thread to run on: start Julia with more (julia --threads=auto)")

job_view(j::K.SplitJob) = (j.materials, j.states)
job_view(j::AbstractDict) = (String.(j["materials"]), j["states"])
jobs_view(jobs) = [job_view(j) for j in jobs]

@testset "plans against the Python package's" begin
    if isempty(FIXTURES) || !isdir(FIXTURES)
        @info "KOMPARTMENT_SPLIT_FIXTURES not set: split parity tests skipped"
    else
        for f in sort(filter(endswith(".json"), readdir(FIXTURES)))
            fx = K.parse_json(read(joinpath(FIXTURES, f), String))
            @testset "$(fx["name"])" begin
                project = K.Project(K.jcopy(fx["model"]))
                sys = K.build_system(project)
                part = K.partition_of(sys)
                theirs = fx["partition"]
                @test part.ok == theirs["ok"]
                @test part.refusal == theirs["refusal"]
                @test part.count == theirs["count"]
                @test part.largest == theirs["largest"]
                if part.ok
                    @test part.of == theirs["of"]
                    @test part.sizes == theirs["sizes"]
                end
                if sys.nstate > 0
                    @test K.state_keys(sys) == fx["keys"]
                    @test K.state_materials(sys) == fx["materials"]
                end
                jobs = K.split_jobs(sys)
                if fx["jobs"]["ok"]
                    @test jobs.why === nothing
                    @test jobs_view(jobs.jobs) == jobs_view(fx["jobs"]["jobs"])
                    @test jobs.owner == fx["jobs"]["owner"]
                    @test jobs.parts == fx["jobs"]["parts"]
                    @test [collect(r) for r in jobs.recorders] == fx["jobs"]["recorders"]
                else
                    @test jobs.why == fx["jobs"]["why"]
                end
                c = fx["constants"]
                constants = K.SplitConstants(shared_work=c["SHARED_WORK"], auto_states=c["AUTO_STATES"],
                                             auto_solve_ms=c["AUTO_SOLVE_MS"], auto_gain=c["AUTO_GAIN"],
                                             auto_gain_untimed=c["AUTO_GAIN_UNTIMED"], start_ms=c["START_MS"])
                for entry in fx["plans"]
                    o = entry["options"]
                    p = entry["plan"]
                    mine = K.plan_split(sys, project; mode=o["mode"], workers=o["workers"],
                                        nest=get(o, "nest", true), build_ms=get(o, "build_ms", 0.0),
                                        known=get(o, "known", nothing), constants)
                    @test mine.use == p["use"]
                    @test mine.mode == p["mode"]
                    @test mine.why == get(JULIA_WORDS, p["why"], p["why"])
                    @test mine.predicted == p["predicted"]
                    if p["use"]
                        @test jobs_view(mine.jobs) == jobs_view(p["jobs"])
                        @test mine.owner == p["owner"]
                        @test mine.bins == p["bins"]
                        @test mine.parts == p["parts"]
                        binned = K.bin_jobs(mine)
                        @test jobs_view(binned.jobs) == jobs_view(p["binned"]["jobs"])
                        @test binned.owner == p["binned"]["owner"]
                        @test [collect(r) for r in binned.recorders] == p["binned"]["recorders"]
                    end
                end
                if haskey(fx, "layers")
                    given = K.whole_layers(sys, project)
                    @test given !== nothing
                    for (path, combos) in fx["layers"], (key, g) in combos
                        mine = given[path][key]
                        @test same(mine.d, unhex(g["d"]))
                        @test same(mine.h, unhex(g["h"]))
                        @test mine.q === parse(Float64, g["q"])
                    end
                end
            end
        end
    end
end

@testset "split runs against the Python package's, to the bit" begin
    if isempty(FIXTURES) || !isdir(FIXTURES)
        @info "KOMPARTMENT_SPLIT_FIXTURES not set: split run parity tests skipped"
    else
        for f in sort(filter(endswith(".json"), readdir(FIXTURES)))
            fx = K.parse_json(read(joinpath(FIXTURES, f), String))
            for r in fx["runs"]
                @testset "$(fx["name"]) on $(r["workers"])" begin
                    res = K.run_project(with_split(fx["model"], "on"); threads=r["workers"])
                    account = res.stats["split"]
                    @test account["used"]
                    @test account["why"] == r["why"]
                    @test [(j["materials"], j["states"], j["nsteps"]) for j in account["jobs"]] ==
                          [(String.(j["materials"]), j["states"], j["nsteps"]) for j in r["jobs"]]
                    @test res.stats["nsteps"] == r["nsteps"]
                    @test same(res.t, unhex(r["t"]))
                    @test all(length(row) == r["nstate"] for row in res.y)
                    outs = K.outputs(res)
                    @test [o["label"] for o in outs] == r["labels"]
                    y = unhex(r["y"])                                     # row by row, as numpy ravels them
                    if get(res.stats, "sparse", false) !== true
                        @test same(reduce(vcat, res.y), y)
                        for (o, col, want) in zip(outs, K.series_many(res, outs), r["series"])
                            ok = same(col, unhex(want))
                            ok || @info "$(fx["name"]): $(o["label"]) differs"
                            @test ok
                        end
                    else
                        # A part above 200 states is factorised by KLU here and by SuperLU in
                        # Python: the same steps (above), the values to round-off.
                        @test maximum(abs.(reduce(vcat, res.y) .- y)) <= 1e-12 * maximum(abs, y)
                        rtol = Float64(fx["model"]["simulation"]["rtol"])
                        for (col, want) in zip(K.series_many(res, outs), r["series"])
                            w = unhex(want)
                            keep = [i for i in eachindex(w) if isfinite(w[i])]
                            peak = maximum(abs, w[keep]; init=0.0)
                            @test maximum(abs.(col[keep] .- w[keep]); init=0.0) <= 100 * rtol * (peak == 0 ? 1.0 : peak)
                        end
                    end
                end
            end
        end
    end
end

# --- this engine's numbers ----------------------------------------------------------------------

@testset "this engine's constants and its formulas" begin
    bio = K.Project(example("biosphere"))
    sys = K.build_system(bio)
    C = K.SPLIT_CONSTANTS
    P = K.SplitConstants()                    # the Python package's, under which a plan is its plan
    plan(; kw...) = K.plan_split(sys, bio; mode="auto", workers=8, kw...)
    @test K.job_cost(25, 100) == C.shared_work + (1 - C.shared_work) * 0.25
    @test K.pack_jobs([5, 3, 3, 2, 1], 2) == [[0, 3], [1, 2, 4]]
    # The Python package's prediction: a bin's build shrinks with its share.
    p = plan(known=Dict("solve_ms" => 40000.0), build_ms=500.0, constants=P)
    @test p.predicted == 40000.0 / ((P.shared_work + (1 - P.shared_work) * 0.25) * 40500.0 + P.start_ms)
    @test p.use && length(p.bins) == 4
    # This engine's: every bin pays a whole build, slower for each built beside it, and auto
    # takes the number of bins expected to be quickest -- here one per part.
    p = plan(known=Dict("solve_ms" => 40000.0), build_ms=500.0)
    slower = 1 + C.build_contention * (4 - 1)
    @test p.predicted ≈ 40000.0 / (500.0 * slower + 40000.0 * K.job_cost(4, 16) + C.start_ms) rtol = 1e-12
    @test p.use && length(p.bins) == 4
    # The decisions.
    small = plan()
    @test !small.use
    @test small.why == "16 states, too few to be worth dividing before a run has been timed"
    short = plan(known=Dict("solve_ms" => C.auto_solve_ms - 1))
    @test !short.use
    @test occursin("too short to be worth dividing", short.why)
    @test plan(known=Dict("solve_ms" => 10.0, "gain" => 1.3)).use
    @test !plan(known=Dict("solve_ms" => 1e6, "gain" => 1.1)).use
    # A long solve beside a long build: a build each bin pays in full is not worth dividing.
    whole_builds = plan(known=Dict("solve_ms" => 4000.0, "build_fixed" => 1.0), build_ms=3000.0)
    shrinking = plan(known=Dict("solve_ms" => 4000.0, "build_fixed" => 0.0), build_ms=3000.0)
    @test !whole_builds.use && occursin("not enough", whole_builds.why)
    @test shrinking.use && whole_builds.predicted < shrinking.predicted
    # Under the Python package's constants, a learned share at its default is its prediction.
    same_share = plan(known=Dict("solve_ms" => 4000.0, "build_fixed" => P.shared_work), build_ms=3000.0, constants=P)
    @test same_share.predicted ≈ plan(known=Dict("solve_ms" => 4000.0), build_ms=3000.0, constants=P).predicted rtol = 1e-12
    # The bins and their weight: packed by states, a bin of two parts weighed as one build.
    p12 = K.Project(chains(12, 4, 6))
    s12 = K.build_system(p12)
    n = s12.nstate
    on = K.plan_split(s12, p12; mode="on", workers=8)
    sizes = [j.states for j in on.jobs]
    @test length(sizes) == 12
    @test on.bins == K.pack_jobs(sizes, 8)
    heaviest = maximum(sum(sizes[j+1] for j in b) for b in on.bins)
    @test heaviest == 2 * sizes[1]
    timed = K.plan_split(s12, p12; mode="auto", workers=8, known=Dict("solve_ms" => 40000.0), build_ms=500.0,
                         constants=P)
    @test timed.predicted == 40000.0 / (K.job_cost(heaviest, n, P) * 40500.0 + P.start_ms)
    measured = K.plan_split(s12, p12; mode="auto", workers=8, known=Dict("solve_ms" => 40000.0, "build_fixed" => 0.8),
                            build_ms=500.0, constants=P)
    bin_ms = 500.0 * (0.8 + 0.2 * heaviest / n) + 40000.0 * K.job_cost(heaviest, n, P)
    @test measured.predicted ≈ 40000.0 / (bin_ms + P.start_ms) rtol = 1e-12
    # This engine's auto weighs every number of bins and takes the quickest, the fewest on a tie.
    for (S, B) in ((40000.0, 500.0), (2000.0, 1500.0), (600.0, 40.0))
        mine = K.plan_split(s12, p12; mode="auto", workers=8, known=Dict("solve_ms" => S), build_ms=B)
        expect = map(2:8) do k
            bins = K.pack_jobs(sizes, k)
            heavy = maximum(sum(sizes[j+1] for j in b) for b in bins)
            S / (B * (1.0 + 0.0 * heavy / n) * (1 + C.build_contention * (k - 1)) + S * K.job_cost(heavy, n) + C.start_ms)
        end
        best = findmax(expect)
        @test mine.predicted ≈ best[1] rtol = 1e-12
        @test mine.use == (best[1] >= C.auto_gain)
        @test !mine.use || length(mine.bins) == best[2] + 1
    end
    # What a measured split says it gained decides, on the bins it ran on when the solve is not known.
    again = K.plan_split(s12, p12; mode="auto", workers=8, known=Dict("gain" => 2.5, "bins" => 3))
    @test again.use && length(again.bins) == 3
    @test again.why == "12 parts, the largest 8% of the states; measured at 2.5× the last time, on 3 cores"
    # The jobs a thread is given.
    plan3 = K._no_split("on", "")
    plan3.jobs = [K.SplitJob(["A"], 3), K.SplitJob(["B", "C"], 5), K.SplitJob(["D"], 2)]
    plan3.bins = [[1], [0, 2]]
    plan3.owner = [0, 0, 0, 1, 1, 1, 1, 1, 2, 2]
    plan3.recorders = [("min_max:Peak[D]", 2, 7), ("running_mean:Mean[B]", 1, 3)]
    got = K.bin_jobs(plan3)
    @test got.jobs == [K.SplitJob(["B", "C"], 5), K.SplitJob(["A", "D"], 5)]
    @test got.owner == [1, 1, 1, 0, 0, 0, 0, 0, 1, 1]
    @test got.recorders == [("min_max:Peak[D]", 1, 7), ("running_mean:Mean[B]", 0, 3)]
    # The whole solve estimated from the bins.
    J(states, nsteps) = Dict{String,Any}("states" => states, "nsteps" => nsteps)
    @test K.whole_solve_ms([J(50, 1000), J(50, 1000)], [1000.0, 1000.0], 100) ≈ 1000.0 / K.job_cost(50, 100)
    summed = (900.0 / 1000 + 300.0 / 800) / (2 * C.shared_work + 1 - C.shared_work) * 1000
    @test summed < 900.0 / K.job_cost(10, 100)
    @test K.whole_solve_ms([J(10, 1000), J(90, 800)], [900.0, 300.0], 100) ≈ summed
    @test K.whole_solve_ms([J(10, 100), J(90, 1000)], [100.0, 1000.0], 100) ≈ 1000.0 / K.job_cost(90, 100)
    @test K.whole_solve_ms([J(10, nothing), J(90, 800)], [900.0, 300.0], 100) == 900.0 / K.job_cost(10, 100)
    # The share of a build every part pays: as measured, and with what bins beside it cost taken back.
    Bj(states, ms) = Dict{String,Any}("states" => states, "buildMs" => ms)
    @test K.build_fixed([Bj(10, 550.0), Bj(30, 650.0)], 100, 500.0) ≈ ((1.1 - 0.1) / 0.9 + (1.3 - 0.3) / 0.7) / 2
    @test K.build_fixed([Bj(10, 715.0), Bj(30, 845.0)], 100, 500.0; contention=0.3) ≈
          ((1.1 - 0.1) / 0.9 + (1.3 - 0.3) / 0.7) / 2
    @test K.build_fixed([Bj(10, 550.0), Bj(30, 650.0)], 100, 0.0) === nothing
    @test K.build_fixed([Bj(100, 1.0)], 100, 1.0) === nothing
    @test K.build_fixed([Bj(10, 1e9)], 100, 1.0) == 2.0
    # Untimed, auto wants a large model of many parts, packed into a few bins.
    p_big = K.Project(chains(12, 4, 210))
    s_big = K.build_system(p_big)
    @test s_big.nstate >= C.auto_states
    big = K.plan_split(s_big, p_big; mode="auto", workers=8)
    @test big.use
    @test occursin("up to", big.why)
    @test length(big.bins) == C.untimed_bins
    few = K.plan_split(s_big, p_big; mode="auto", workers=2)
    @test !few.use
    @test occursin("not enough", few.why)
    @test K._with_commas(10080) == "10,080" && K._with_commas(999) == "999" && K._with_commas(1234567) == "1,234,567"
end

# --- split runs -------------------------------------------------------------------------------------

@testset "split runs" begin
    # Each decides from a clean slate, not from what an earlier run timed.
    empty!(K._SPLIT_MEMORY)

    @testset "the examples agree with the whole" begin
        for (name, parts) in (("biosphere", 4), ("landscape", 3), ("waste-packages", 4))
            whole = K.run_project(with_split(example(name), "off"))
            parted = K.run_project(with_split(example(name), "on"); threads=4)
            account = parted.stats["split"]
            @test account["used"]
            @test length(account["jobs"]) == parts
            @test parted.t == whole.t
            @test worst(whole, parted) < AGREE
            @test parted.stats["nsteps"] > 0
            @test parted.stats["solver"] == whole.stats["solver"]
            @test whole.stats["split"] == Dict("used" => false, "mode" => "off", "why" => "switched off",
                                               "predicted" => nothing)
        end
    end

    @testset "the account and the log" begin
        parted = K.run_project(with_split(example("biosphere"), "on"); threads=3)
        account = parted.stats["split"]
        @test collect(keys(account)) == ["used", "mode", "why", "predicted", "parts", "workers", "jobs", "wallMs", "gain"]
        @test account["why"] == "asked for: 4 parts, the largest 25% of the states, on 3 cores"
        @test (account["used"], account["mode"], account["parts"], account["workers"]) == (true, "on", 4, 3)
        @test account["predicted"] === nothing
        # A line per thread: four parts of four states on three, the first given two of them.
        @test [j["materials"] for j in account["jobs"]] == [["I-129", "Se-79"], ["Cl-36"], ["Tc-99"]]
        @test [j["states"] for j in account["jobs"]] == [8, 4, 4]
        for job in account["jobs"]
            @test collect(keys(job)) == ["materials", "states", "nsteps", "buildMs", "solveMs"]
            @test job["nsteps"] > 0
        end
        @test account["wallMs"] > 0
        @test account["gain"] > 0
        @test parted.timing["solve_ms"] == account["wallMs"]
        log = K.run_log(parted)
        @test occursin("split: 4 independent parts on 3 cores (on) — asked for: 4 parts", log)
        @test occursin("I-129, Se-79: 8 states,", log)
        # Saved with its run, the account goes along.
        mktempdir() do dir
            path = joinpath(dir, "parted.zip")
            K.save(parted, path)
            @test isfile(path)
        end
    end

    @testset "a bin is one build, and the same run wherever it goes" begin
        project = with_split(example("biosphere"), "on")
        two_ = K.run_project(project; threads=2)
        account = two_.stats["split"]
        @test account["workers"] == 2
        @test [j["materials"] for j in account["jobs"]] == [["I-129", "Tc-99"], ["Cl-36", "Se-79"]]
        again = K.run_project(with_split(example("biosphere"), "on"); threads=2)
        @test again.y == two_.y
        @test again.stats["nsteps"] == two_.stats["nsteps"]
        # Each bin is a run of the model with its materials alone switched on.
        whole = K.build_system(project)
        work = K.bin_jobs(K.plan_split(whole, project; mode="on", workers=2))
        where_ = Dict(key => i for (i, key) in enumerate(K.state_keys(whole)))
        for (b, job) in enumerate(account["jobs"])
            part = K.build_part(K.part_model(K.project_to_json(project), job["materials"]))
            alone = K.run_project(part.project; system=part.system, on_grid=true)
            @test alone.stats["nsteps"] == job["nsteps"]
            filed = 0
            for (k, key) in enumerate(K.state_keys(part.system))
                i = where_[key]
                work.owner[i] == b - 1 || continue
                @test all(two_.y[r][i] === alone.y[r][k] for r in eachindex(two_.t))
                filed += 1
            end
            @test filed == job["states"]
        end
        # A thread per part: each part at its own steps, which agree with the bins' to the tolerance.
        four = K.run_project(with_split(example("biosphere"), "on"); threads=4)
        @test [j["materials"] for j in four.stats["split"]["jobs"]] == [["I-129"], ["Cl-36"], ["Tc-99"], ["Se-79"]]
        @test worst(two_, four) < AGREE
    end

    @testset "a far-field path in several parts is solved on the whole model's layers" begin
        model = farfield_two_parts()
        whole = K.run_project(with_split(model, "off"))
        parted = K.run_project(with_split(model, "on"); threads=2)
        @test parted.stats["split"]["used"]
        @test length(parted.stats["split"]["jobs"]) == 2
        @test worst(whole, parted) < 1e-6
        # The layers a split hands its parts are the ones the whole run lays out, to the bit.
        project = with_split(model, "on")
        given = K.whole_layers(K.build_system(project), project)["Rock"][""]
        F = whole.system.data.FARF[1]
        @test given.d == F.layers_d[:, 1]
        @test given.h == F.layers_h[:, 1]
        @test given.q === F.layers_q[1]
        # A part alone lays out its own; given them, it holds them; run again without, lets go.
        tracer = K.build_part(K.part_model(K.project_to_json(project), ["I-129"]))
        K.run_project(tracer.project; system=tracer.system, on_grid=true, layers=Dict("Rock" => Dict("" => given)))
        @test tracer.system.data.FARF[1].layers_d[1, 1] == given.d[1]
        K.run_project(tracer.project; system=tracer.system, on_grid=true)
        @test tracer.system.data.FARF[1].layers_d[1, 1] > 3 * given.d[1]
    end

    @testset "made-up chains" begin
        model = chains(6, 5, 4)
        whole = K.run_project(with_split(model, "off"))
        parted = K.run_project(with_split(model, "on"); threads=3)
        @test parted.stats["split"]["parts"] == 6
        @test parted.stats["split"]["workers"] == 3
        @test worst(whole, parted) < AGREE
    end

    @testset "a min/max and a running mean come back" begin
        whole = K.run_project(with_split(RECORDING, "off"))
        parted = K.run_project(with_split(RECORDING, "on"); threads=2)
        @test parted.stats["split"]["used"]
        @test worst(whole, parted) < AGREE
        # The peak is a peak, not the value at the end.
        @test parted["PeakB [Cs-137]"][end] > parted["B [Cs-137]"][end] * 1.5
    end

    @testset "a min/max of more than one part is solved whole" begin
        r = K.run_project(with_split(ACROSS, "on"); threads=2)
        @test !r.stats["split"]["used"]
        @test r.stats["split"]["why"] ==
              "'PeakTotal' remembers a value read from more than one part, so no part can give it back"
        whole = K.run_project(with_split(ACROSS, "off"))
        @test r["PeakTotal"] == whole["PeakTotal"]
    end

    @testset "a part switches on what it names" begin
        whole = K.run_project(with_split(PINNED, "off"))
        parted = K.run_project(with_split(PINNED, "on"); threads=2)
        @test parted.stats["split"]["used"]
        @test worst(whole, parted) < 1e-6
    end

    @testset "progress, and a stop" begin
        heard = Tuple{Float64,Float64}[]
        model = example("biosphere")
        r = K.run_project(with_split(model, "on"); threads=4, on_progress=(f, at) -> (push!(heard, (f, at)); nothing))
        @test r.stats["split"]["used"]
        @test !isempty(heard)
        @test heard[end] == (1.0, Float64(model["simulation"]["end_time"]))
        @test all(heard[k][1] <= heard[k+1][1] && heard[k][2] <= heard[k+1][2] for k in 1:length(heard)-1)
        # Stopped: the parts stop and the run says so.
        long = with_split(model, "on"; end_time=model["simulation"]["end_time"] * 1000)
        err = try
            K.run_project(long; threads=4, on_progress=(f, at) -> false)
            nothing
        catch e
            e
        end
        @test err isa K.SolverError && err.kind == "aborted"
    end

    @testset "not split side by side, or with the system given" begin
        r = K.run_project(with_split(example("biosphere"), "on"); threads=4, nest=false)
        @test !r.stats["split"]["used"]
        @test r.stats["split"]["why"] == "this run is itself one of several side by side, which do not start more"
        project = with_split(example("biosphere"), "on")
        @test !haskey(K.run_project(project; system=K.build_system(project)).stats, "split")
        one = K.run_project(with_split(example("biosphere"), "on"); threads=1)
        @test one.stats["split"]["why"] == "there is one thread to run on: start Julia with more (julia --threads=auto)"
    end

    @testset "a split that does not add up is solved whole" begin
        model = example("biosphere")
        failed = Ref(false)
        # The first word from the split fails it, as parts that came back on different times would.
        once = (f, at) -> failed[] ? nothing : (failed[] = true; error("the parts came back on different output times"))
        r = K.run_project(with_split(model, "on"); threads=4, on_progress=once)
        @test !r.stats["split"]["used"]
        @test r.stats["split"]["why"] == "tried, and solved whole instead: the parts came back on different output times"
        @test worst(K.run_project(with_split(model, "off")), r) < 1e-12
        # And the parts' own errors: times that differ, a state no part carried.
        a = (t=[0.0, 1.0], y=[[1.0], [2.0]], keys=["x"], stats=Dict{String,Any}(), held=nothing)
        b = (t=[0.0, 2.0], y=[[1.0], [2.0]], keys=["y"], stats=Dict{String,Any}(), held=nothing)
        @test_throws ErrorException("the parts came back on different output times") K.assemble_parts(["x", "y"], [0, 1], [a, b])
        @test_throws ErrorException("no part carried the state 'z'") K.assemble_parts(["x", "z"], [0, 1], [a, a])
    end

    @testset "auto is the default, and learns" begin
        empty!(K._SPLIT_MEMORY)
        model = K.Model(example("biosphere"))
        first_ = run(model; threads=4)
        @test first_.stats["split"] == Dict("used" => false, "mode" => "auto", "predicted" => first_.stats["split"]["predicted"],
                                            "why" => "16 states, too few to be worth dividing before a run has been timed")
        again = run(model; threads=4)
        @test !again.stats["split"]["used"]
        @test occursin(r"^a whole solve takes \d+ ms, too short to be worth dividing$", again.stats["split"]["why"])
    end

    @testset "what auto learns is kept for the next process" begin
        mktempdir() do dir
            saved = (get(ENV, "KOMPARTMENT_CACHE", nothing), get(ENV, "KOMPARTMENT_SPLIT_MEMORY", nothing))
            ENV["KOMPARTMENT_CACHE"] = dir
            delete!(ENV, "KOMPARTMENT_SPLIT_MEMORY")
            try
                empty!(K._SPLIT_MEMORY)
                K._SPLIT_MEMORY_READ[] = false
                run(K.Model(example("biosphere")); threads=4)
                path = joinpath(dir, "split-memory-julia.json")
                @test isfile(path)
                kept = K.parse_json(read(path, String))
                @test length(kept) == 1
                key, entry = first(kept)
                @test occursin("|julia|", key)
                @test entry["solve_ms"] > 0
                # A process that starts afresh reads it before it plans.
                empty!(K._SPLIT_MEMORY)
                K._SPLIT_MEMORY_READ[] = false
                again = run(K.Model(example("biosphere")); threads=4)
                @test occursin(r"^a whole solve takes \d+ ms, too short", again.stats["split"]["why"])
            finally
                for (name, v) in zip(("KOMPARTMENT_CACHE", "KOMPARTMENT_SPLIT_MEMORY"), saved)
                    v === nothing ? delete!(ENV, name) : (ENV[name] = v)
                end
                empty!(K._SPLIT_MEMORY)
                K._SPLIT_MEMORY_READ[] = false
            end
        end
    end
end

@testset "timing: independent chains, whole against split" begin
    if isempty(get(ENV, "KOMPARTMENT_SPLIT_TIMING", ""))
        @info "KOMPARTMENT_SPLIT_TIMING not set: the timing skipped"
    else
        empty!(K._SPLIT_MEMORY)
        # Julia's own code compiled first, as the Python package's is cached: a small split.
        K.run_project(with_split(chains(6, 5, 4), "on"); threads=3)
        model = chains(16, 12, 150; points=300, rtol=1e-8)
        started = time()
        whole = K.run_project(with_split(model, "off"))
        whole_s = time() - started
        lines = ["$(length(model["nuclides"])) nuclides x $(length(model["compartments"])) compartments = " *
                 "$(K._with_commas(whole.system.nstate)) states, $(Threads.nthreads()) threads",
                 "  whole: $(round(whole_s; digits=2)) s (build $(round(Int, whole.timing["build_ms"])) ms, " *
                 "solve $(round(Int, whole.timing["solve_ms"])) ms, $(whole.stats["nsteps"]) steps)"]
        peak = maximum(maximum(abs, row) for row in whole.y)
        for threads in unique([2, 4, 8, Threads.nthreads()])
            started = time()
            parted = K.run_project(with_split(model, "on"); threads)
            split_s = time() - started
            jobs = parted.stats["split"]["jobs"]
            # Every state, against the largest: the far end of the line holds amounts at the
            # absolute tolerance, which agree only to it.
            off = maximum(maximum(abs.(a .- b)) for (a, b) in zip(parted.y, whole.y)) / peak
            push!(lines, "  split on $threads: $(round(split_s; digits=2)) s, $(round(whole_s / split_s; digits=2))x " *
                         "(solve wall $(round(Int, parted.stats["split"]["wallMs"])) ms; parts: build " *
                         "$(round(Int, minimum(j["buildMs"] for j in jobs)))-$(round(Int, maximum(j["buildMs"] for j in jobs))) ms, " *
                         "solve $(round(Int, minimum(j["solveMs"] for j in jobs)))-$(round(Int, maximum(j["solveMs"] for j in jobs))) ms, " *
                         "$(minimum(j["nsteps"] for j in jobs))-$(maximum(j["nsteps"] for j in jobs)) steps; " *
                         "worst $(round(off; sigdigits=2)) of the peak)")
            @test off < 1e-6
        end
        println("\n", join(lines, "\n"))
    end
end

end # module
