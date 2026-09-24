# What GlobalSensitivity.jl makes of fixed designs and data, for the port in
# kompartment/src/domain/gsa.js to be checked against.
#
# Every case hands both sides the same numbers: the design or the sample, the
# outputs, and wherever the method draws random numbers of its own (eFAST's
# phases, RBD-FAST's permutations, δ's bootstrap, the MI shuffles) the draws
# themselves, replayed from the same RNG. The test functions are the usual
# made-up ones -- Ishigami, linear, a product -- so nothing here is anybody's
# data.
#
#   julia --project=<env with GlobalSensitivity 2.12.8, StableRNGs, JSON3,
#         Distributions, Copulas> scripts/gen-gsa-ref.jl
#
# writes kompartment/test/fixtures/gsa-reference.json. Arrays of numbers are
# stored as base64 of their little-endian Float64 bytes, which is exact and
# half the size of the decimals; the test decodes them.

using GlobalSensitivity, StableRNGs, JSON3, Distributions, Random, Statistics, Base64
import Copulas: SklarDist, IndependentCopula

const OUT = joinpath(@__DIR__, "..", "kompartment", "test", "fixtures", "gsa-reference.json")

ishi(x) = sin(x[1]) + 7 * sin(x[2])^2 + 0.1 * x[3]^4 * sin(x[1])

# A function that remembers what it was called with, in order.
function recording(f)
    calls = Vector{Vector{Float64}}()
    g = x -> (push!(calls, collect(Float64, x)); f(x))
    return g, calls
end

b64(v) = base64encode(reinterpret(UInt8, collect(Float64, v)))
cols(M) = [b64(M[i, :]) for i in 1:size(M, 1)]
ref = Dict{String, Any}()
ref["version"] = string(pkgversion(GlobalSensitivity))

# --- Sobol: A and B given, every estimator, pairs, and two blocks.
let
    rng = StableRNG(11)
    d, n = 3, 128
    A = -π .+ 2π .* rand(rng, d, n)
    B = -π .+ 2π .* rand(rng, d, n)
    g, calls = recording(ishi)
    r = gsa(g, Sobol(order = [0, 1, 2]), A, B)
    y = [ishi(c) for c in calls]
    cases = Dict{String, Any}()
    for est in (:Jansen1999, :Sobol2007, :Homma1996, :Janon2014)
        s = gsa(ishi, Sobol(order = [0, 1, 2]), A, B; Ei_estimator = est)
        cases[lowercase(string(est))] = Dict("S1" => b64(s.S1), "ST" => b64(s.ST), "S2" => cols(s.S2))
    end
    A2 = -π .+ 2π .* rand(rng, d, 2n)
    B2 = -π .+ 2π .* rand(rng, d, 2n)
    g2, calls2 = recording(ishi)
    s2 = gsa(g2, Sobol(order = [0, 1], nboot = 2), A2, B2)
    ref["sobol"] = Dict(
        "d" => d, "n" => n, "A" => cols(A), "B" => cols(B), "y" => b64(y), "estimators" => cases,
        "blocks" => Dict("A" => cols(A2), "B" => cols(B2), "y" => b64([ishi(c) for c in calls2]),
            "S1" => b64(s2.S1), "ST" => b64(s2.ST), "S1ci" => b64(s2.S1_Conf_Int), "STci" => b64(s2.ST_Conf_Int)),
    )
end

# --- eFAST: the phases replayed from the same RNG.
function efast_case(f, K, N, seed)
    lb, ub = -π, π
    g, calls = recording(f)
    r = gsa(g, eFAST(), [[lb, ub] for _ in 1:K]; samples = N, rng = StableRNG(seed))
    rng = StableRNG(seed)
    phases = [2rand(rng) for _ in 1:K]
    return Dict("K" => K, "N" => N, "phases" => b64(phases), "y" => b64([f(c) for c in calls]),
        "S1" => b64(vec(r.S1)), "ST" => b64(vec(r.ST)))
end
linear5(x) = x[1] + 2x[2] + 3x[3] + 0.5x[4] + 0.1x[5] * x[1]
ref["efast"] = [efast_case(ishi, 3, 400, 42), efast_case(linear5, 5, 200, 7)]

# --- RBD-FAST: the permutations replayed.
function rbd_case(K, N, seed)
    f = x -> ishi(-π .+ 2π .* x)
    g, calls = recording(f)
    s = gsa(g, GlobalSensitivity.RBDFAST(); num_params = K, samples = N, rng = StableRNG(seed))
    rng = StableRNG(seed)
    perms = [randperm(rng, N) .- 1 for _ in 1:K]
    return Dict("K" => K, "N" => N, "perms" => perms, "y" => b64([f(c) for c in calls]),
        "S1" => b64(collect(s)))
end
ref["rbdfast"] = [rbd_case(3, 399, 3), rbd_case(3, 400, 4)]

# --- Morris: its own design, recorded, and the analysis of it.
let
    f = x -> x[1] + 2x[2]^2 + x[3] * x[4] + 0.2
    out = Dict{String, Any}()
    for rel in (false, true)
        g, calls = recording(f)
        m = gsa(g, Morris(p_steps = [10, 10, 10, 10], relative_scale = rel,
            num_trajectory = 5, len_design_mat = 8), [[0.0, 1.0] for _ in 1:4]; rng = StableRNG(9))
        out[rel ? "relative" : "plain"] = Dict(
            "u" => [b64([c[k] for c in calls]) for k in 1:4], "y" => b64([f(c) for c in calls]),
            "mean" => b64(vec(m.means)), "meanStar" => b64(vec(m.means_star)),
            "variance" => b64(vec(m.variances)))
    end
    out["trajectories"] = 5
    out["points"] = 8
    ref["morris"] = out
end

# --- Fractional factorial. Integer levels: it copies its matrix of ±1s and
# writes the levels into the copy, which is a matrix of Int, so a level of 0.2
# is an InexactError there.
let
    f = x -> 3x[1] - 2x[2] + x[3] * x[4] + 0.5x[5]
    me, sq = gsa(f, FractionalFactorial(); num_params = 5, p_range = [(1, 3) for _ in 1:5])
    ref["ff"] = Dict("K" => 5, "low" => 1, "high" => 3, "main" => b64(me), "squared" => b64(sq))
end

# --- DGSM: the points replayed from the global RNG it uses.
let
    f = x -> x[1] + 2x[2] + 6x[3] + x[1] * x[2]^2
    distr = [Uniform(0, 1) for _ in 1:3]
    Random.seed!(123)
    r = gsa(f, DGSM(crossed = true), distr; samples = 200)
    Random.seed!(123)
    XX = [rand.(distr) for _ in 1:200]
    ref["dgsm"] = Dict("x" => [b64([p[k] for p in XX]) for k in 1:3],
        "a" => b64(r.a), "absa" => b64(r.absa), "asq" => b64(r.asq), "sigma" => b64(r.sigma), "tao" => b64(r.tao),
        "crossed" => cols(r.crossed), "abscrossed" => cols(r.abscrossed), "crossedsq" => cols(r.crossedsq))
end

# --- Shapley: all 3! orders, which are deterministic; the sample recorded.
let
    f = x -> x[1] + 2x[2] + 3x[3] + x[1] * x[3]
    g, calls = recording(f)
    dist = SklarDist(IndependentCopula(3), (Normal(), Normal(), Normal()))
    r = gsa(g, Shapley(n_perms = -1, n_var = 500, n_outer = 20, n_inner = 3), dist)
    ref["shapley"] = Dict("K" => 3, "nVar" => 500, "nOuter" => 20, "nInner" => 3,
        "y" => b64([f(c) for c in calls]), "effects" => b64(r.shapley_effects), "stdErr" => b64(r.std_err),
        "lower" => b64(r.CI_lower), "upper" => b64(r.CI_upper))
end

# --- From a sample: δ, EASI, RSA and mutual information.
let
    rng = StableRNG(21)
    X = -π .+ 2π .* rand(rng, 3, 200)
    Y = [ishi(X[:, j]) for j in 1:200]
    m = DeltaMoment(nboot = 8)
    d = gsa(X, Y, m; rng = StableRNG(5))
    rr = StableRNG(5)
    resamples = [[collect(r[i, :] .- 1) for i in 1:8] for r in (rand(rr, 1:200, 8, 200) for _ in 1:3)]
    ref["delta"] = Dict("x" => cols(X), "y" => b64(Y), "resamples" => resamples,
        "delta" => b64(d.deltas), "adjusted" => b64(d.adjusted_deltas),
        "low" => b64(d.adjusted_deltas_low), "high" => b64(d.adjusted_deltas_hi))
end

let
    rng = StableRNG(31)
    X = -π .+ 2π .* rand(rng, 3, 400)
    Y = [ishi(X[:, j]) for j in 1:400]
    e = gsa(X, Y, EASI())
    e2 = gsa(X, Y, EASI(dct_method = true))
    X5 = -π .+ 2π .* rand(rng, 3, 399)
    Y5 = [ishi(X5[:, j]) for j in 1:399]
    e5 = gsa(X5, Y5, EASI())
    ref["easi"] = Dict("x" => cols(X), "y" => b64(Y), "S1" => b64(e.S1), "S1c" => b64(e.S1_Corr),
        "dctS1" => b64(e2.S1), "dctS1c" => b64(e2.S1_Corr),
        "odd" => Dict("x" => cols(X5), "y" => b64(Y5), "S1" => b64(e5.S1), "S1c" => b64(e5.S1_Corr)))
end

let
    rng = StableRNG(41)
    X = rand(rng, 3 + 10, 200)
    Y = [ishi(-π .+ 2π .* X[1:3, j]) for j in 1:200]
    r = GlobalSensitivity._compute_rsa(X, Y, RSA())
    ref["rsa"] = Dict("x" => cols(X), "y" => b64(Y), "K" => 3, "S" => b64(r.S), "dummyMean" => r.Sd[1],
        "dummySdSkippingFirst" => r.Sd[2])
end

let
    rng = StableRNG(51)
    X = rand(rng, 3, 150)
    Y = [ishi(-π .+ 2π .* X[:, j]) for j in 1:150]
    m = MutualInformation(n_bootstraps = 20)
    Random.seed!(99)
    shuffles = Vector{Vector{Vector{Int}}}()
    for _ in 1:3
        idx = collect(1:150)
        these = Vector{Vector{Int}}()
        for _ in 1:20
            shuffle!(idx)
            push!(these, idx .- 1)
        end
        push!(shuffles, these)
    end
    Random.seed!(99)
    mi, bounds = GlobalSensitivity._compute_mi(X, Y, m)
    ref["mi"] = Dict("x" => cols(X), "y" => b64(Y), "shuffles" => shuffles, "mi" => b64(mi), "bounds" => b64(bounds))
end

open(OUT, "w") do io
    JSON3.write(io, ref)
end
println("wrote ", OUT)
