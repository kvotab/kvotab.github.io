# The engine's default, fast mode (src/util/parity.jl): Julia's own dense LU, the
# NDF where a model asks for the Rosenbrock 2-3, one Newton iteration a step on a
# linear model -- each held to the accuracy of parity mode (the Python package's
# arithmetic, which the other test files check to the bit), against a reference
# solved to a far tighter tolerance.

module FastTests

using Test, LinearAlgebra
using Kompartment
const K = Kompartment

const EXAMPLES = joinpath(@__DIR__, "..", "..", "..", "examples")
example(name) = K.load(joinpath(EXAMPLES, "$name.json"))

"""The largest gap from a reference run over every state, each as a share of its own peak."""
function gap(r, ref)
    (length(r.y) == length(ref.y) && r.t == ref.t) || return Inf
    peak = [maximum(abs(row[i]) for row in ref.y) for i in eachindex(ref.y[1])]
    return maximum((abs(r.y[k][i] - ref.y[k][i]) / max(peak[i], 1e-300) for k in eachindex(r.y) for i in eachindex(peak));
                   init=0.0)
end

@testset "Julia's own dense LU" begin
    K.set_parity!(false)
    for n in (1, 2, 5, 16, 33, 100)
        A = [sin(i * j) + (i == j ? n : 0.0) for i in 1:n, j in 1:n]
        J = vec(-A)                                  # Mass - a*J with a = 1 and Mass = I: I + A
        held = zeros(UInt8, n)
        fail = zeros(2)
        lu = zeros(n, n)
        piv = zeros(Int, n)
        @test K._fast_form_dense!(lu, 1.0, J, held, ones(n), fail) == 0
        @test K._fast_factor!(lu, piv, fail) == K._LU_OK
        b = [cos(i) for i in 1:n]
        @test K._fast_solve!(copy(b), lu, piv) ≈ (Matrix(1.0I, n, n) + A) \ b rtol = 1e-12
    end
    # A singular matrix fails at the column the application's LU names, a pivot that is not a
    # number as not a number.
    fail = zeros(2)
    @test K._fast_factor!([1.0 2.0; 2.0 4.0], zeros(Int, 2), fail) == K._LU_SINGULAR && fail[1] == 1
    @test K._fast_factor!([NaN 1.0; 1.0 1.0], zeros(Int, 2), fail) == K._LU_NONFINITE
    @test K._fast_form_dense!(zeros(2, 2), 1.0, [1.0, Inf, 0.0, 1.0], zeros(UInt8, 2), ones(2), fail) ==
          -K._LU_NONFINITE && fail[1] == 0
end

@testset "the NDF where a model asks for the Rosenbrock 2-3" begin
    K.set_parity!(false)
    m = example("biosphere")
    @test K.simulation(m)["solver"] == "ros23"
    r = run(m; split="off")
    @test (r.stats["solver"], r.stats["asked"]) == ("ndf", "ros23")
    @test occursin("solver run: ndf, the quicker for the ros23 the model asks for", K.run_log(r))
    # The model's own, by the policy or with parity.
    K.set_solver_policy!(:model)
    try
        r2 = run(m; split="off")
        @test r2.stats["solver"] == "ros23" && !haskey(r2.stats, "asked")
    finally
        K.set_solver_policy!(:fastest)
    end
    K.set_parity!(true)
    @test run(m; split="off").stats["solver"] == "ros23"
    K.set_parity!(false)
    # A quicker solver that cannot finish: the model's own runs instead.
    ndf = K.SOLVERS["ndf"]
    K.SOLVERS["ndf"] = (f, t, y, o) -> throw(K.SolverError("tolerance", "made to fail for the test", 0.0))
    try
        r3 = run(m; split="off")
        @test (r3.stats["solver"], r3.stats["tried"]) == ("ros23", "ndf")
        @test occursin("solver run: the model's own, after ndf could not finish", K.run_log(r3))
    finally
        K.SOLVERS["ndf"] = ndf
    end
end

@testset "one Newton iteration a step on a linear model" begin
    m = example("biosphere")
    counts = Dict{Bool,Tuple{Int,Int}}()
    for exact in (true, false)
        K.set_parity!(exact)
        r = run(m; split="off", solver="ndf")
        counts[exact] = (r.stats["nsolves"], r.stats["nsteps"])
    end
    @test counts[true][1] >= 1.9 * counts[true][2]      # ode15s: two a step
    @test counts[false][1] <= 1.2 * counts[false][2]    # here: one
    K.set_parity!(false)
end

@testset "every example as accurate as in parity mode" begin
    for f in sort(readdir(EXAMPLES))
        endswith(f, ".json") || continue
        name = f[1:end-5]
        m = example(name)
        sim = K.simulation(m)
        # Reported at the solver's own steps, which are each mode's own.
        get(sim, "spacing", "grid") in ("solver", "both") && continue
        rtol = Float64(something(get(sim, "rtol", nothing), 1e-3))
        abstol = Float64(something(get(sim, "abstol", nothing), 1e-6))
        K.set_parity!(true)
        ref = try
            run(m; split="off", solver="ndf", rtol=1e-11, abstol=1e-3 * abstol)
        catch
            nothing
        end
        ref === nothing && continue
        err = Dict{Bool,Float64}()
        for exact in (true, false)
            K.set_parity!(exact)
            err[exact] = gap(run(m; split="off"), ref)
        end
        @testset "$name" begin
            @test err[false] <= max(3 * err[true], 10 * rtol)
        end
    end
    K.set_parity!(false)
end

@testset "a probabilistic run as in parity mode" begin
    m = example("biosphere")
    vals = Dict{Bool,Vector{Matrix{Float64}}}()
    for exact in (true, false)
        K.set_parity!(exact)
        prob = run_probabilistic(m, 20; seed=1, threads=1)
        vals[exact] = [prob[l] for l in K.labels(prob)]
    end
    worst = maximum(maximum(abs.(a .- b)) / max(maximum(abs, a), 1e-300) for (a, b) in zip(vals[true], vals[false]))
    @test worst < 1e-3
    K.set_parity!(false)
end

end # module
