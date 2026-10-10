# Runs checked against closed forms and against the application's rules,
# needing nothing but this package and the bundled examples.

using Test
using LinearAlgebra
using Kompartment
const K = Kompartment

const EXAMPLES = joinpath(@__DIR__, "..", "..", "..", "examples")

@testset "known answers" begin
    @testset "exponential decay against exp(-kt)" begin
        res = run(K.load(joinpath(EXAMPLES, "exponential-decay.json")))
        y = res["y"]
        exact = res["Exact"]
        @test maximum(abs.(y .- exact)) < 1e-6
        @test exact[end] ≈ exp(-10.0) rtol = 1e-14
    end

    @testset "a decay chain against the matrix exponential" begin
        m = K.load(joinpath(EXAMPLES, "decay-chain.json"))
        res = run(m)
        p = K.project(m)
        dm = K.decay_model(p)
        n = length(dm.names)
        # dA/dt = M A, activities: each daughter grows by its own lambda times the parent's share.
        M = zeros(n, n)
        for i in 1:n
            M[i, i] = -dm.lambdas[i]
            for par in dm.parents[i]
                M[i, par.index+1] += par.lambda * par.ratio
            end
        end
        A0 = zeros(n)
        A0[1] = 1e12
        for (k, t) in enumerate(res.t)
            k % 40 == 0 || continue
            exact = exp(M * t) * A0
            for (i, name) in enumerate(dm.names)
                got = res["Waste [$name]"][k]
                @test isapprox(got, exact[i]; rtol=1e-5, atol=1e-6 * maximum(abs, exact))
            end
        end
    end

    @testset "every bundled example runs" begin
        for f in sort(filter(endswith(".json"), readdir(EXAMPLES)))
            m = K.load(joinpath(EXAMPLES, f))
            local res
            try
                res = run(m)
            catch e
                e isa K.BuildError && occursin("not supported", e.message) && continue
                rethrow()
            end
            @test length(res.t) >= 2
            @test all(o -> haskey(o, "label"), K.outputs(res))
            cols = K.series_many(res, K.outputs(res))
            @test all(c -> length(c) == length(res.t), cols)
        end
    end

    @testset "a run is reproducible and a clone runs alike" begin
        m = K.load(joinpath(EXAMPLES, "recorders.json"))
        p = K.project(m)
        sys = K.build_system(p)
        a = K.run_project(p; system=sys)
        b = K.run_project(p; system=K.clone_system(sys))
        c = K.run_project(p; system=sys)
        for (x, y, z) in zip(K.series_many(a, K.outputs(a)), K.series_many(b, K.outputs(b)), K.series_many(c, K.outputs(c)))
            @test all(x .=== y)
            @test all(x .=== z)
        end
    end
end
