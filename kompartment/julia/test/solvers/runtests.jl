# The Julia solvers against the Python engine's, case by case
# (tools/solver_fixtures.py writes fixtures.json).
#
#   julia --startup-file=no --project=kompartment/julia kompartment/julia/test/solvers/runtests.jl
#
# On a dense problem a run must take the Python run's steps -- the same
# accepted times, the same counts -- and give its outputs bit for bit; a
# failure must say what Python's says, word for word. On the sparse path
# (KLU here, SuperLU there) the two agree to the tolerance.

using Test
using SparseArrays

isdefined(@__MODULE__, :MiniJSON) || include(joinpath(@__DIR__, "minijson.jl"))

isdefined(@__MODULE__, :SolverTest) || include(joinpath(@__DIR__, "module.jl"))
using .SolverTest
const ST = SolverTest
include(joinpath(@__DIR__, "problems.jl"))

const FIXTURES = joinpath(@__DIR__, "fixtures.json")

# --- decoding -----------------------------------------------------------------------------

ishexfloat(s::AbstractString) = startswith(s, "0x") || startswith(s, "-0x") || s in ("inf", "-inf", "nan")
dec(x) = x
dec(x::AbstractString) = ishexfloat(x) ? parse(Float64, x) : String(x)
dec(x::AbstractVector) = [dec(v) for v in x]
dec(x::AbstractDict) = Dict{String,Any}(String(k) => dec(v) for (k, v) in x)
fvec(x) = Float64[Float64(v) for v in x]

# --- running a case as the fixture did ----------------------------------------------------

struct Run
    result::Any            # a Solution, or the segments of a restarted run
    error::Union{Nothing,ST.SolverError}
    steps::Vector{Float64}
    progress::Vector{Any}
    abstol::Any
end

function run_case(c::Dict{String,Any})
    f, parts, events = PROBLEMS[c["problem"]](c["params"])
    jac = jacobian_of(parts, c["jac"])
    tspan = fvec(c["tspan"])
    y0 = fvec(c["y0"])
    steps = Float64[]
    progress = Any[]
    on_accepted = ST.StepCallback((t, y) -> (push!(steps, t); nothing))
    opts = Dict{String,Any}(c["opts"])
    solver = c["solver"]
    if get(opts, "on_step", false) === true
        opts["on_step"] = ST.RunProgress((a, n, t) -> (push!(progress, Any[a, n, t]); true))
    end
    if haskey(opts, "abstol") && opts["abstol"] isa AbstractVector
        opts["abstol"] = fvec(opts["abstol"])
    end
    if haskey(opts, "mass")
        opts["mass"] = fvec(opts["mass"])
    end
    solve = (span, y) -> begin
        if solver == "ndf"
            kw = Dict{Symbol,Any}(Symbol(k) => v for (k, v) in opts)
            if haskey(kw, :non_negative)
                kw[:non_negative] = Int[i + 1 for i in kw[:non_negative]]
            end
            ST.ndf(f, span, y; jacobian=jac, events=events, on_accepted=on_accepted, kw...)
        else
            o = Dict{String,Any}(opts)
            o["jacobian"] = jac
            o["events"] = events
            o["on_accepted"] = on_accepted
            ST.SOLVERS[solver == "variable_order" ? "ndf" : solver](f, span, y, o)
        end
    end
    result = nothing
    err = nothing
    try
        if c["restart"] === false
            result = solve(tspan, y0)
        else
            segments = ST.Solution[]
            t = tspan[1]
            y = y0
            nxt = 1
            for _ in 1:12
                while nxt <= length(tspan) && tspan[nxt] <= t
                    nxt += 1
                end
                nxt > length(tspan) && break
                span = vcat(t, tspan[nxt:end])
                r = solve(span, y)
                push!(segments, r)
                r.stopped === nothing && break
                t = r.stopped.t
                y = copy(r.stopped.y)
                y[2] = -0.8 * y[2]
                if c["restart"] == "floor"
                    y[1] = 0.0
                end
            end
            result = segments
        end
    catch e
        e isa ST.SolverError || rethrow()
        err = e
    end
    return Run(result, err, steps, progress, get(opts, "abstol", nothing))
end

# --- comparing ----------------------------------------------------------------------------

bits_equal(a::Float64, b::Float64) = isequal(a, b)
bits_equal(a::AbstractVector, b::AbstractVector) = length(a) == length(b) && all(isequal.(a, b))

const STAT_KEYS = ("nsteps", "nfailed", "nfevals", "npds", "ndecomps", "nsolves", "nbelowtol", "negative")

"""Where two step sequences part, for the report."""
function first_divergence(a::Vector{Float64}, b::Vector{Float64})
    for i in 1:min(length(a), length(b))
        isequal(a[i], b[i]) || return (i, a[i], b[i])
    end
    length(a) == length(b) && return nothing
    return (min(length(a), length(b)) + 1, nothing, nothing)
end

function compare_solution(name, sol::ST.Solution, ref::Dict{String,Any}; exact::Bool, rtol::Float64, atol::Float64,
                          stride::Int=1)
    rs = ref["stats"]
    if exact
        @test fvec(ref["t"]) == sol.t
        @test length(sol.y) == length(ref["y"])
        for (i, row) in enumerate(ref["y"])
            i > length(sol.y) && break
            ok = bits_equal(fvec(row), sol.y[i])
            ok || @info "$name: output row $i differs" maxabs = maximum(abs.(fvec(row) .- sol.y[i]))
            @test ok
        end
        for k in STAT_KEYS
            haskey(rs, k) || continue
            ok = rs[k] == sol.stats[k]
            ok || @info "$name: stats[$k]" python = rs[k] julia = sol.stats[k]
            @test ok
        end
        if haskey(rs, "held")
            if rs["held"] === nothing
                @test sol.stats["held"] === nothing
            else
                @test sol.stats["held"] == Int.(rs["held"])
            end
        end
        if haskey(ref, "end")
            @test isequal(Float64(ref["end"]["t"]), sol.end_t)
            @test bits_equal(fvec(ref["end"]["y"]), sol.end_y)
        end
    else
        @test fvec(ref["t"]) == sol.t
        @test length(sol.y) == length(ref["y"])
        worst = 0.0
        for (i, row) in enumerate(ref["y"])
            i > length(sol.y) && break
            r = fvec(row)
            yj = sol.y[i][1:stride:end]
            for j in eachindex(r)
                scale = 10 * (rtol * max(abs(r[j]), abs(yj[j])) + atol)
                worst = max(worst, abs(r[j] - yj[j]) / scale)
            end
        end
        worst <= 1 || @info "$name: outputs differ beyond 10x the tolerance" worst
        @test worst <= 1
        for k in ("nsteps", "ndecomps")
            ok = abs(rs[k] - sol.stats[k]) <= 0.25 * rs[k] + 5
            ok || @info "$name: stats[$k]" python = rs[k] julia = sol.stats[k]
            @test ok
        end
    end
    st = ref["stopped"]
    if st === nothing
        @test sol.stopped === nothing
    else
        @test sol.stopped !== nothing
        if sol.stopped !== nothing
            @test isequal(Float64(st["t"]), sol.stopped.t)
            @test bits_equal(fvec(st["y"]), sol.stopped.y)
            @test Int[w + 1 for w in st["which"]] == sol.stopped.which
        end
    end
end

function check_case(c::Dict{String,Any})
    name = c["name"]
    exact = c["exact"]
    run = run_case(c)
    opts = c["opts"]
    rtol = Float64(get(opts, "rtol", 1e-3))
    ab = get(opts, "abstol", 1e-6)
    atol = ab isa AbstractVector ? maximum(fvec(ab)) : Float64(ab)
    ref_steps = fvec(c["steps"])
    if exact
        d = first_divergence(ref_steps, run.steps)
        d === nothing || @info "$name: the accepted steps part at step $(d[1])" python = d[2] julia = d[3] npython = length(ref_steps) njulia = length(run.steps)
        @test d === nothing
    end
    if haskey(c, "error")
        e = c["error"]
        @test run.error !== nothing
        run.error === nothing && return
        @test run.error.kind == e["kind"]
        ok = run.error.message == e["message"]
        ok || @info "$name: the messages differ" python = e["message"] julia = run.error.message
        @test ok
        @test isequal(Float64(e["t"]), run.error.t)
        if e["stats"] !== nothing
            for k in keys(e["stats"])
                @test e["stats"][k] == run.error.stats[k]
            end
            @test isequal(Float64(e["last_t"]), run.error.last_t)
            @test length(e["trace"]) == length(run.error.trace)
            for (a, b) in zip(e["trace"], run.error.trace)
                @test isequal(Float64(a["t"]), b["t"]) && isequal(Float64(a["h"]), b["h"]) && a["k"] == b["k"] &&
                      isequal(Float64(a["err"]), b["err"]) && a["newton"] == b["newton"] && a["failed"] == b["failed"]
            end
        else
            @test isempty(run.error.stats)
        end
        return
    end
    if run.error !== nothing
        @info "$name: Julia failed where Python did not" run.error.kind run.error.message
        @test run.error === nothing
        return
    end
    if c["restart"] !== false
        segs = c["segments"]
        @test length(segs) == length(run.result)
        for (i, (ref, sol)) in enumerate(zip(segs, run.result))
            compare_solution("$name segment $i", sol, ref; exact=exact, rtol=rtol, atol=atol, stride=c["stride"])
        end
    else
        compare_solution(name, run.result, c["result"]; exact=exact, rtol=rtol, atol=atol, stride=c["stride"])
    end
    if !isempty(c["progress"]) || !isempty(run.progress)
        @test length(c["progress"]) == length(run.progress)
        for (a, b) in zip(c["progress"], run.progress)
            @test isequal(Float64(a[1]), b[1]) && a[2] == b[2] && isequal(Float64(a[3]), b[3])
        end
    end
    if haskey(c, "abstol_after")
        @test bits_equal(fvec(c["abstol_after"]), run.abstol)
    end
end

const DOC = dec(MiniJSON.parse_json(read(FIXTURES, String)))

@testset "solvers against the Python engine" begin
    @test DOC["numba"] == true          # the Python runs used the application's dense LU
    for c in DOC["cases"]
        @testset "$(c["name"])" begin
            check_case(c)
        end
    end
end

@testset "the pieces against Python's" begin
    U = DOC["units"]
    @testset "numbers in messages (Python's float repr)" begin
        bad = [(x, r, ST._pyrepr(Float64(x))) for (x, r) in U["repr"] if "repr:" * ST._pyrepr(Float64(x)) != r]
        isempty(bad) || @info "repr differs" first(bad, 5)
        @test isempty(bad)
    end
    @testset "ulp (the C library's log2 and pow)" begin
        bad = [(x, u) for (x, u) in U["ulp"] if !isequal(ST._ndf_ulp(Float64(x)), Float64(u))]
        isempty(bad) || @info "ulp differs" first(bad, 5)
        @test isempty(bad)
    end
    @testset "colour_columns" begin
        for c in U["colour"]
            p = ST.Pattern(c["n"], Int[r + 1 for r in c["rows"]], Int[q + 1 for q in c["cols"]])
            @test ST.colour_columns(p) == [Int[j + 1 for j in g] for g in c["groups"]]
        end
    end
    @testset "dense or sparse (IterationMatrix)" begin
        for c in U["decisions"]
            p = ST.Pattern(c["n"], Int[r + 1 for r in c["rows"]], Int[q + 1 for q in c["cols"]])
            # The values travel in the Python pattern's order, which is this pattern's.
            W = ST.IterationMatrix(c["n"], p, fvec(c["values"]), c["mode"])
            @test W.sparse == c["sparse"]
            ST._mat_release!(W)
        end
    end
end

@testset "aborted runs" begin
    f, parts, _ = prob_robertson(nothing)
    jac = jacobian_of(parts, "exact")
    y0 = [1.0, 0.0, 0.0]
    calls = Ref(0)
    # variable_order: asked every 64 evaluations, (fraction, n, t); false stops the run
    opts = Dict{String,Any}("rtol" => 1e-6, "abstol" => 1e-10, "jacobian" => jac,
                            "on_step" => (a, n, t) -> (calls[] += 1; calls[] < 3))
    e = try
        ST.variable_order(f, [0.0, 4e6], y0, opts); nothing
    catch err
        err
    end
    @test e isa ST.SolverError && e.kind == "aborted" && e.message == "Simulation aborted"
    @test calls[] == 3
    # the NDF's own on_step(t, nsteps): every 16 steps
    seen = Int[]
    e = try
        ST.ndf(f, [0.0, 4e6], y0; rtol=1e-6, abstol=1e-10, jacobian=jac,
               on_step=ST.StepProgress((t, n) -> (push!(seen, n); n < 32))); nothing
    catch err
        err
    end
    @test e isa ST.SolverError && e.kind == "aborted" && e.message == "Aborted"
    @test seen == [16, 32]
    # the one-step methods: every 32 steps, (fraction, nsteps, t)
    for solver in ("ros23", "dp45")
        seen3 = Int[]
        o = Dict{String,Any}("rtol" => 1e-4, "abstol" => 1e-8, "jacobian" => jac,
                             "on_step" => (a, n, t) -> (push!(seen3, n); false))
        e = try
            ST.SOLVERS[solver](f, [0.0, 4e6], y0, o); nothing
        catch err
            err
        end
        @test e isa ST.SolverError && e.kind == "aborted" && e.message == "Simulation aborted"
        @test seen3 == [32]
    end
end

@testset "a stopped KLU factorisation is freed" begin
    f, parts, _ = prob_landscape(Dict("nb" => 20))
    jac = jacobian_of(parts, "exact")
    sol = ST.ndf(f, [0.0, 1.0, 100.0], zeros(200); rtol=1e-6, abstol=1e-12, jacobian=jac, matrix="sparse")
    @test sol.stats["sparse"] == true && sol.stats["lu"] == "KLU"
    @test all(isfinite, sol.y[end])
end
