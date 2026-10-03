# Writes resources/tests/ode/julia/ref/default.json: what DifferentialEquations.jl does
# on the problems in resources/tests/ode/julia/problems-default.mjs, for
# resources/tests/ode/julia/test-default.mjs to compare the port with.
#
#     julia --project=<env> scripts/gen-ode-default-ref.jl
#
# The environment needs OrdinaryDiffEq (7.8.1 when this was written, with
# OrdinaryDiffEqDefault 2.6.2, OrdinaryDiffEqCore 4.18.1, OrdinaryDiffEqTsit5
# 2.1.5, OrdinaryDiffEqVerner 2.4.2, OrdinaryDiffEqRosenbrock 2.7.5,
# OrdinaryDiffEqBDF 2.4.12), ADTypes and JSON3.
#
# The problems are written out twice, here and in problems-default.mjs, and are
# to be changed together. Each has its exact Jacobian; the default algorithm
# is DefaultODEAlgorithm(autodiff = AutoFiniteDiff()), what solve(prob) builds,
# so its Krylov FBDF differences J·v as the port does. For each run the file
# keeps the counts, the algorithm chosen at every saved point (alg_choice,
# compressed into runs), and the final state; for each problem a reference
# final state at reltol 1e-12 from Rodas5P with the exact Jacobian (Vern9 at
# 1e-14 for the non-stiff one).

using OrdinaryDiffEq, OrdinaryDiffEqDefault, ADTypes, LinearAlgebra, SparseArrays, JSON3
using Pkg

const OUT = joinpath(@__DIR__, "..", "resources", "tests", "ode", "julia", "ref", "default.json")

# --- the problems: the twins of problems-default.mjs ----------------------------

function rober!(du, y, p, t)
    du[1] = -0.04 * y[1] + 1e4 * y[2] * y[3]
    du[2] = 0.04 * y[1] - 1e4 * y[2] * y[3] - 3e7 * y[2] * y[2]
    du[3] = 3e7 * y[2] * y[2]
    nothing
end
function roberjac!(J, y, p, t)
    J[1, 1] = -0.04; J[1, 2] = 1e4 * y[3]; J[1, 3] = 1e4 * y[2]
    J[2, 1] = 0.04; J[2, 2] = -1e4 * y[3] - 6e7 * y[2]; J[2, 3] = -1e4 * y[2]
    J[3, 1] = 0.0; J[3, 2] = 6e7 * y[2]; J[3, 3] = 0.0
    nothing
end

function vdp!(du, y, p, t)
    du[1] = y[2]
    du[2] = 1000 * ((1 - y[1] * y[1]) * y[2]) - y[1]
    nothing
end
function vdpjac!(J, y, p, t)
    J[1, 1] = 0.0; J[1, 2] = 1.0
    J[2, 1] = -2000 * y[1] * y[2] - 1; J[2, 2] = 1000 * (1 - y[1] * y[1])
    nothing
end

function hires!(du, y, p, t)
    du[1] = -1.71 * y[1] + 0.43 * y[2] + 8.32 * y[3] + 0.0007
    du[2] = 1.71 * y[1] - 8.75 * y[2]
    du[3] = -10.03 * y[3] + 0.43 * y[4] + 0.035 * y[5]
    du[4] = 8.32 * y[2] + 1.71 * y[3] - 1.12 * y[4]
    du[5] = -1.745 * y[5] + 0.43 * y[6] + 0.43 * y[7]
    du[6] = -280 * y[6] * y[8] + 0.69 * y[4] + 1.71 * y[5] - 0.43 * y[6] + 0.69 * y[7]
    du[7] = 280 * y[6] * y[8] - 1.81 * y[7]
    du[8] = -280 * y[6] * y[8] + 1.81 * y[7]
    nothing
end
function hiresjac!(J, y, p, t)
    fill!(J, 0.0)
    J[1, 1] = -1.71; J[1, 2] = 0.43; J[1, 3] = 8.32
    J[2, 1] = 1.71; J[2, 2] = -8.75
    J[3, 3] = -10.03; J[3, 4] = 0.43; J[3, 5] = 0.035
    J[4, 2] = 8.32; J[4, 3] = 1.71; J[4, 4] = -1.12
    J[5, 5] = -1.745; J[5, 6] = 0.43; J[5, 7] = 0.43
    J[6, 4] = 0.69; J[6, 5] = 1.71; J[6, 6] = -280 * y[8] - 0.43; J[6, 7] = 0.69; J[6, 8] = -280 * y[6]
    J[7, 6] = 280 * y[8]; J[7, 7] = -1.81; J[7, 8] = 280 * y[6]
    J[8, 6] = -280 * y[8]; J[8, 7] = 1.81; J[8, 8] = -280 * y[6]
    nothing
end

const OS = 77.27
const OW = 0.161
const OQ = 8.375e-6
function orego!(du, y, p, t)
    du[1] = OS * (y[2] + y[1] * (1 - OQ * y[1] - y[2]))
    du[2] = (y[3] - (1 + y[1]) * y[2]) / OS
    du[3] = OW * (y[1] - y[3])
    nothing
end
function oregojac!(J, y, p, t)
    J[1, 1] = OS * (1 - 2 * OQ * y[1] - y[2]); J[1, 2] = OS * (1 - y[1]); J[1, 3] = 0.0
    J[2, 1] = -y[2] / OS; J[2, 2] = -(1 + y[1]) / OS; J[2, 3] = 1 / OS
    J[3, 1] = OW; J[3, 2] = 0.0; J[3, 3] = -OW
    nothing
end

const KE = 0.6
function kepler!(du, y, p, t)
    r2 = y[1] * y[1] + y[2] * y[2]
    r3 = r2 * sqrt(r2)
    du[1] = y[3]
    du[2] = y[4]
    du[3] = -y[1] / r3
    du[4] = -y[2] / r3
    nothing
end
function keplerjac!(J, y, p, t)
    r2 = y[1] * y[1] + y[2] * y[2]
    r = sqrt(r2)
    r3 = r2 * r
    r5 = r3 * r2
    fill!(J, 0.0)
    J[1, 3] = 1.0; J[2, 4] = 1.0
    J[3, 1] = -1 / r3 + 3 * y[1] * y[1] / r5; J[3, 2] = 3 * y[1] * y[2] / r5
    J[4, 1] = 3 * y[1] * y[2] / r5; J[4, 2] = -1 / r3 + 3 * y[2] * y[2] / r5
    nothing
end

function heat(n)
    dx = 1 / (n + 1)
    c = 1 / (dx * dx)
    u0 = [sin(pi * (j * dx)) + 0.5 * sin(3pi * (j * dx)) for j in 1:n]
    f!(du, u, p, t) = begin
        for i in 1:n
            l = i > 1 ? u[i-1] : 0.0
            r = i < n ? u[i+1] : 0.0
            du[i] = (l - 2 * u[i] + r) / (dx * dx)
        end
        nothing
    end
    jac!(J, u, p, t) = begin
        for i in 1:n
            i > 1 && (J[i, i-1] = c)
            J[i, i] = -2c
            i < n && (J[i, i+1] = c)
        end
        nothing
    end
    proto = spdiagm(-1 => ones(n - 1), 0 => ones(n), 1 => ones(n - 1))
    ("heat$n", ODEFunction(f!; jac = jac!, jac_prototype = proto), u0, (0.0, 0.1))
end

function chain(n)
    k = [10.0^(4 - 8 * (i - 1) / (n - 1)) for i in 1:n]
    f!(du, u, p, t) = begin
        du[1] = -k[1] * u[1]
        for i in 2:n
            du[i] = k[i-1] * u[i-1] - k[i] * u[i]
        end
        nothing
    end
    jac!(J, u, p, t) = begin
        for i in 1:n
            J[i, i] = -k[i]
            i > 1 && (J[i, i-1] = k[i-1])
        end
        nothing
    end
    proto = spdiagm(0 => ones(n), -1 => ones(n - 1))
    u0 = zeros(n); u0[1] = 1.0
    ("chain$n", ODEFunction(f!; jac = jac!, jac_prototype = proto), u0, (0.0, 100.0))
end

problems = Dict{String, Any}(
    "rober" => (ODEFunction(rober!; jac = roberjac!), [1.0, 0.0, 0.0], (0.0, 1e5), :stiff),
    "vdp1000" => (ODEFunction(vdp!; jac = vdpjac!), [2.0, 0.0], (0.0, 3000.0), :stiff),
    "hires" => (ODEFunction(hires!; jac = hiresjac!), [1.0, 0, 0, 0, 0, 0, 0, 0.0057], (0.0, 321.8122), :stiff),
    "orego" => (ODEFunction(orego!; jac = oregojac!), [1.0, 2.0, 3.0], (0.0, 360.0), :stiff),
    "kepler" => (ODEFunction(kepler!; jac = keplerjac!), [1 - KE, 0.0, 0.0, sqrt((1 + KE) / (1 - KE))], (0.0, 20.0), :nonstiff),
)
for n in (30, 200, 600, 700)
    name, f, u0, tspan = heat(n)
    problems[name] = (f, u0, tspan, :stiff)
end
for n in (40, 120, 800)
    name, f, u0, tspan = chain(n)
    problems[name] = (f, u0, tspan, :stiff)
end

# --- the runs: the twins of COMPARISONS in problems-default.mjs ------------------

const RUNS = [
    ("kepler", "Tsit5", 1e-3, 1e-6),
    ("kepler", "Vern7", 1e-8, 1e-10),
    ("kepler", "DefaultODEAlgorithm", 1e-3, 1e-6),
    ("kepler", "DefaultODEAlgorithm", 1e-8, 1e-10),
    ("rober", "Rosenbrock23", 1e-3, 1e-6),
    ("rober", "DefaultODEAlgorithm", 1e-3, 1e-6),
    ("rober", "DefaultODEAlgorithm", 1e-8, 1e-10),
    ("vdp1000", "DefaultODEAlgorithm", 1e-3, 1e-6),
    ("hires", "Rosenbrock23", 1e-3, 1e-6),
    ("hires", "DefaultODEAlgorithm", 1e-3, 1e-6),
    ("hires", "DefaultODEAlgorithm", 1e-8, 1e-10),
    ("orego", "DefaultODEAlgorithm", 1e-3, 1e-6),
    ("heat30", "DefaultODEAlgorithm", 1e-3, 1e-6),
    ("heat200", "DefaultODEAlgorithm", 1e-3, 1e-6),
    ("heat700", "DefaultODEAlgorithm", 1e-3, 1e-6),
    ("chain40", "DefaultODEAlgorithm", 1e-3, 1e-6),
    ("chain120", "DefaultODEAlgorithm", 1e-3, 1e-6),
    ("chain800", "DefaultODEAlgorithm", 1e-3, 1e-6),
    # At a tight tolerance, where FBDF's first step after a switch is what
    # decides how the switching goes.
    ("heat200", "DefaultODEAlgorithm", 1e-6, 1e-9),
    ("heat600", "DefaultODEAlgorithm", 1e-6, 1e-9),
    ("chain40", "DefaultODEAlgorithm", 1e-6, 1e-9),
    ("chain120", "DefaultODEAlgorithm", 1e-6, 1e-9),
]

algorithm(name) = name == "Tsit5" ? Tsit5() :
                  name == "Vern7" ? Vern7() :
                  name == "Rosenbrock23" ? Rosenbrock23(autodiff = AutoFiniteDiff()) :
                  name == "DefaultODEAlgorithm" ? DefaultODEAlgorithm(autodiff = AutoFiniteDiff()) :
                  error(name)

function compress(choice)
    out = Vector{Vector{Int}}()
    for a in choice
        if !isempty(out) && out[end][1] == a
            out[end][2] += 1
        else
            push!(out, [a, 1])
        end
    end
    out
end

function main()
    results = Dict{String, Any}()
    for (name, (f, u0, tspan, kind)) in problems
        prob = ODEProblem(f, u0, tspan)
        ref = kind == :stiff ?
            solve(prob, Rodas5P(autodiff = AutoFiniteDiff()); reltol = 1e-12, abstol = 1e-16, save_everystep = false) :
            solve(prob, Vern9(); reltol = 1e-14, abstol = 1e-16, save_everystep = false)
        results[name] = Dict("reference" => collect(ref.u[end]), "referenceRetcode" => string(ref.retcode), "runs" => Any[])
    end
    for (name, alg, rtol, atol) in RUNS
        f, u0, tspan, _ = problems[name]
        sol = solve(ODEProblem(f, u0, tspan), algorithm(alg); reltol = rtol, abstol = atol)
        st = sol.stats
        push!(results[name]["runs"], Dict(
            "alg" => alg, "reltol" => rtol, "abstol" => atol, "retcode" => string(sol.retcode),
            "naccept" => st.naccept, "nreject" => st.nreject, "nf" => st.nf, "njacs" => st.njacs,
            "nsolve" => st.nsolve, "points" => length(sol.t),
            "runs" => alg == "DefaultODEAlgorithm" ? compress(sol.alg_choice) : nothing,
            "final" => collect(sol.u[end]),
        ))
        println(rpad("$name $alg $rtol", 42), sol.retcode, " naccept=", st.naccept, " nreject=", st.nreject,
                alg == "DefaultODEAlgorithm" ? " runs=$(compress(sol.alg_choice))" : "")
    end
    versions = Dict(string(p.name) => string(p.version) for p in values(Pkg.dependencies())
                    if p.name in ("OrdinaryDiffEq", "OrdinaryDiffEqDefault", "OrdinaryDiffEqCore",
                                  "OrdinaryDiffEqTsit5", "OrdinaryDiffEqVerner", "OrdinaryDiffEqRosenbrock",
                                  "OrdinaryDiffEqBDF", "LinearSolve", "Krylov"))
    mkpath(dirname(OUT))
    open(OUT, "w") do io
        JSON3.write(io, Dict("julia" => string(VERSION), "packages" => versions, "problems" => results))
    end
    println("wrote ", OUT)
end

main()
