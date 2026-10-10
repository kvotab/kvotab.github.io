# What makes runs quicker without changing a number: the passes compiled for a
# model kept for the next build of it; a probabilistic run's draws read from each
# distribution worked out once, its series read straight into its matrices, its
# rows used again from realisation to realisation; an interpolation's points read
# where they stand; the run's settings worked out once per system. Each against
# the way it replaced, to the bit, in both modes.

module SpeedTests

using Test
using Kompartment
const K = Kompartment

const EXAMPLES = joinpath(@__DIR__, "..", "..", "..", "examples")
example(name) = K.load(joinpath(EXAMPLES, "$name.json"))

"""A small generator of its own (a 64-bit LCG), so that the cases are the same everywhere."""
mutable struct Draws
    s::UInt64
end
next!(d::Draws) = (d.s = d.s * 0x5851f42d4c957f2d + 0x14057b7ef767814f; d.s)
pick(d::Draws, v) = v[1+Int(next!(d) >> 33)%length(v)]
unit(d::Draws) = Float64(next!(d) >> 11) / 2.0^53

@testset "a model built again takes the code compiled for it" begin
    m = example("biosphere")
    p = K.project(m)
    a = K.build_system(p)
    b = K.build_system(K.project(m))
    @test a.step === b.step && a.clock === b.clock && a.once === b.once && a.initial === b.initial
    # Another model's code is its own, and the two systems run alike.
    @test K.build_system(K.project(example("decay-chain"))).step !== a.step
    ra = K.run_project(p; system=a)
    rb = K.run_project(p; system=b)
    @test ra.t == rb.t && ra.y == rb.y
end

@testset "an interpolation's points read where they stand" begin
    d = Draws(7)
    xs_from = [0.0, 1.0, 2.0, 2.0, 5.0, -3.0, 1e-300, 7.5]
    ys_from = [0.0, 1.0, -2.0, 3.5, NaN, 1e10]
    same = 0
    total = 0
    for _ in 1:20_000
        n = 1 + Int(next!(d) >> 40) % 6
        xs = sort([pick(d, xs_from) for _ in 1:n])
        unit(d) < 0.1 && reverse!(xs)                          # out of order: made into a table
        unit(d) < 0.03 && (xs[1+Int(next!(d) >> 40)%n] = pick(d, [NaN, Inf]))
        key = pick(d, [unit(d) * 12 - 4, xs[1], xs[end], NaN, -Inf, Inf])
        args = Float64[key]
        for k in 1:n
            push!(args, xs[k], pick(d, ys_from))
        end
        for rule in (:linear, :extrapolate)
            a = try K.interpolate_args(Tuple(args), rule) catch e; e isa K.LookupError ? :refused : rethrow() end
            b = try K.interpolate_args(args, String(rule)) catch e; e isa K.LookupError ? :refused : rethrow() end
            total += 1
            same += isequal(a, b)
        end
    end
    @test same == total
    # A count of arguments the table refuses is refused alike.
    for args in ([1.0], [1.0, 2.0], [1.0, 2.0, 3.0, 4.0])
        @test_throws K.LookupError K.interpolate_args(Tuple(args), :linear)
    end
end

@testset "a distribution's draws, its reading worked out once" begin
    d = Draws(11)
    nums = [0.0, 1.0, 2.5, 10.0, 1e-6, 3e3, -1.0, 0.5, 0.9, 0.1, 100.0]
    kinds = collect(keys(K.PDF_KIND_PARAMS))
    same = 0
    total = 0
    for _ in 1:20_000
        kind = pick(d, kinds)
        params = K.JDict()
        for key in K.PDF_KIND_PARAMS[kind]
            params[key] = unit(d) < 0.02 ? pick(d, [nothing, "2", "x"]) : pick(d, nums)
        end
        if kind in ("triang", "dtriang", "logt", "logdt") && unit(d) < 0.7
            lo, mo, hi = sort([pick(d, nums), pick(d, nums), pick(d, nums)])
            params["min"], params["mode"], params["max"] = lo, mo, hi
        end
        spec = K.JDict("kind" => kind, "params" => params)
        if kind == "pg"
            spec["values"] = unit(d) < 0.9 ? [pick(d, nums) for _ in 1:1+Int(next!(d) >> 40)%5] : nothing
            unit(d) < 0.5 && (spec["inorder"] = false)
            unit(d) < 0.3 && (spec["pos"] = pick(d, [0, 2, "1"]))
        end
        unit(d) < 0.2 && (spec["trmin"] = pick(d, nums))
        unit(d) < 0.2 && (spec["trmax"] = pick(d, nums))
        unit(d) < 0.1 && (spec["pmin"] = pick(d, [0.1, 0.5, 0.0]))
        unit(d) < 0.1 && (spec["pmax"] = pick(d, [0.9, 0.5, 1.0]))
        unit(d) < 0.01 && (spec = pick(d, [nothing, K.JDict(), K.JDict("kind" => "nope")]))
        drawer = K.ValueDrawer(spec)
        for _ in 1:4
            u = pick(d, [unit(d), 0.0, 1.0, 0.5, 1e-300, 1 - 1e-15])
            at = Int(next!(d) >> 50)
            total += 1
            same += isequal(K.draw_value(drawer, u, at), K.value_at_probability(spec, u, at))
        end
    end
    @test same == total
end

@testset "a realisation's series read straight into the matrices" begin
    for name in ("biosphere", "waste-packages", "recorders", "farfield", "landscape"), exact in (true, false)
        K.set_parity!(exact)
        m = example(name)
        p = K.project(m)
        sys = K.build_system(p)
        r = K.run_project(p; system=sys, on_grid=true)
        kept = K.JDict[o for o in K.outputs(r) if K.can_be_endpoint(get(o, "kind", nothing))]
        grid = K.time_grid(p)
        # (a run reported at times besides the grid's: each grid time read at the first row at or after it)
        rows = [min(searchsortedfirst(r.t, g), length(r.t)) for g in grid]
        take = K._PBTake(kept)
        for T in (Float64, Float32)
            values = [fill(T(-1), length(grid), 3) for _ in kept]
            K._pb_take!(values, r, kept, take, 2, grid, K._pb_take_buffer(kept, grid))
            cols = K.series_many(r, kept)
            @testset "$name $(exact ? "parity" : "fast") $T" begin
                @test all(isequal(values[w][:, 2], T.(cols[w][rows])) for w in eachindex(kept))
                @test all(all(==(T(-1)), values[w][:, [1, 3]]) for w in eachindex(kept))
            end
        end
    end
    K.set_parity!(false)
end

@testset "a run's rows used again by the next" begin
    m = example("biosphere")
    p = K.project(m)
    sys = K.build_system(p)
    plain = K.run_project(p; system=sys, on_grid=true)
    pool = K.RowPool()
    a = K.run_project(p; system=sys, on_grid=true, rows=pool)
    @test a.t == plain.t && a.y == plain.y
    first_rows = copy(a.y)
    b = K.run_project(p; system=sys, on_grid=true, rows=pool)
    @test b.y == plain.y && all(b.y[i] === first_rows[i] for i in eachindex(b.y))
    # A probabilistic run, whose threads keep a pool each, gives what one without would.
    K.set_parity!(true)
    prob = run_probabilistic(m, 6; seed=2, threads=2)
    one = K.run_realisation(m, 5; seed=2, iterations=6)
    label = K.labels(prob)[end]
    @test one.results.t == prob.t
    @test prob[label][5, :] == K.series(one.results, K.find_output(one.results, label))
    K.set_parity!(false)
end

@testset "every realisation on the threads, the first with the rest" begin
    # geoTransit handed out from a list, realisation by realisation: an absurd rate breaks one.
    function with_list(values)
        d = K.read_model_file(joinpath(EXAMPLES, "biosphere.json"))
        for p in d["parameters"]
            p["name"] == "geoTransit" &&
                (p["pdf"] = K.JDict("kind" => "pg", "values" => Any[values...], "inorder" => true, "pos" => 0))
        end
        return Model(d)
    end
    # A failure in the first realisation fails the run, as it did when the first ran alone.
    @test_throws K.SolverError run_probabilistic(with_list([1e308, 2e-4, 2e-4, 2e-4]), 4; seed=1, threads=2)
    # Any other is recorded, and the run goes on, telling its progress once per realisation.
    told = Int[]
    prob = run_probabilistic(with_list([2e-4, 1e308, 2e-4, 2e-4]), 4; seed=1, threads=2,
                             on_progress=(done, total) -> push!(told, done))
    @test prob.stats["failed"] == 1 && prob.ran == UInt8[1, 0, 1, 1] && told == 1:4
    @test all(isnan, prob[K.labels(prob)[end]][2, :])
end

@testset "the run's settings worked out once per system" begin
    m = example("biosphere")
    p = K.project(m)
    sys = K.build_system(p)
    abstol, nonneg = K.run_tolerances(p, sys)
    @test isequal(abstol, K.absolute_tolerance(p, sys)) && nonneg == K.non_negative_states(p, sys)
    # Kept for the project; another project, or other settings, are worked out afresh.
    @test sys.run_settings[1] === p
    set_simulation!(m; abstol=1e-9)
    p2 = K.project(m)
    abstol2, _ = K.run_tolerances(p2, sys)
    @test isequal(abstol2, K.absolute_tolerance(p2, sys)) && sys.run_settings[1] === p2
end

@testset "a linear model's Jacobian known to be one" begin
    flags(name) = (j = K.build_system(K.project(example(name))).jacobian.analytic; (j.constant, j.state_free))
    @test flags("biosphere") == (true, true)           # constant
    @test flags("lookup-driver") == (false, true)      # moving with the clock only
    @test flags("van-der-pol") == (false, false)       # with the state
end

end # module
