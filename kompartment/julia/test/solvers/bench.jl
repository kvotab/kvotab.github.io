# How fast the Julia NDF is (warm, best of several), on the problems
# tools/solver_fixtures.py --bench times in Python: Robertson, and the
# landscape-like linear system of 2,000 and 20,000 states (KLU), and the
# dense cases of fixtures.json.
#
#   julia --startup-file=no --project=kompartment/julia kompartment/julia/test/solvers/bench.jl

using SparseArrays, Printf
isdefined(@__MODULE__, :SolverTest) || include(joinpath(@__DIR__, "module.jl"))
using .SolverTest
const ST = SolverTest
include(joinpath(@__DIR__, "problems.jl"))
isdefined(@__MODULE__, :MiniJSON) || include(joinpath(@__DIR__, "minijson.jl"))

function best_of(fn, repeat)
    best = Inf
    out = nothing
    for _ in 1:repeat
        GC.gc(false)
        t0 = time_ns()
        out = fn()
        best = min(best, (time_ns() - t0) / 1e9)
    end
    return best, out
end

const ROB_T = [0.0, 0.4, 4.0, 40.0, 400.0, 4e3, 4e4, 4e5, 4e6]

function bench_robertson()
    f, parts, _ = prob_robertson(nothing)
    jac = jacobian_of(parts, "exact")
    y0 = [1.0, 0.0, 0.0]
    run() = ST.ndf(f, ROB_T, y0; rtol=1e-6, abstol=1e-10, jacobian=jac)
    run()
    sec, sol = best_of(run, 50)
    bytes = @allocated run()
    @printf("robertson exact jac: %.3f ms per solve, %d steps, %.1f KiB allocated per solve\n",
            sec * 1e3, sol.stats["nsteps"], bytes / 1024)
end

function bench_landscape(nb, repeat)
    f, parts, _ = prob_landscape(Dict("nb" => nb))
    jac = jacobian_of(parts, "exact")
    n = nb * 10
    span = [0.0, 1.0, 10.0, 100.0, 1000.0, 1e4, 1e5]
    y0 = zeros(n)
    run() = ST.ndf(f, span, y0; rtol=1e-6, abstol=1e-12, jacobian=jac)
    run()
    sec, sol = best_of(run, repeat)
    bytes = @allocated run()
    s = sol.stats
    @printf("landscape n=%d (%s) %8.1f ms, %d steps, %d failed, %d decomps, %d solves, fill=%s, %.1f MiB allocated\n",
            n, s["lu"], sec * 1e3, s["nsteps"], s["nfailed"], s["ndecomps"], s["nsolves"], string(s["fill"]),
            bytes / 2^20)
end

"""The dense cases of fixtures.json, timed as tools/solver_fixtures.py --bench times them."""
function bench_dense()
    doc = MiniJSON.parse_json(read(joinpath(@__DIR__, "fixtures.json"), String))
    dec(x) = x
    dec(x::AbstractString) = (startswith(x, "0x") || startswith(x, "-0x") || x in ("inf", "-inf", "nan")) ?
                             parse(Float64, x) : String(x)
    dec(x::AbstractVector) = [dec(v) for v in x]
    dec(x::AbstractDict) = Dict{String,Any}(String(k) => dec(v) for (k, v) in x)
    byname = Dict(c["name"] => dec(c) for c in doc["cases"])
    for name in ("rob_exact", "rob_nojac", "vdp1000", "orego", "hires", "chain80_nojac", "chain150_dense",
                 "ros_rob_exact", "ros_chain80", "dp_vdp1")
        c = byname[name]
        f, parts, events = PROBLEMS[c["problem"]](c["params"])
        jac = jacobian_of(parts, c["jac"])
        tspan = Float64.(c["tspan"])
        y0 = Float64.(c["y0"])
        opts = Dict{String,Any}(c["opts"])
        delete!(opts, "on_step")
        run = if c["solver"] == "ndf"
            kw = Dict{Symbol,Any}(Symbol(k) => v for (k, v) in opts)
            () -> ST.ndf(f, tspan, y0; jacobian=jac, kw...)
        else
            o = copy(opts)
            o["jacobian"] = jac
            () -> ST.SOLVERS[c["solver"]](f, tspan, y0, o)
        end
        run()
        sec, sol = best_of(run, 20)
        @printf("%-16s %9.3f ms per solve, %d steps\n", name, sec * 1e3, sol.stats["nsteps"])
    end
end

bench_dense()
bench_robertson()
bench_landscape(200, 10)
bench_landscape(2000, 5)
