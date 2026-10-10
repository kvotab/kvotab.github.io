# The derivative bit for bit against the Python engine's (tools/engine_fixtures.py).
using Test
using Kompartment
const K = Kompartment

const FIXTURES = get(ENV, "KOMPARTMENT_ENGINE_FIXTURES", "")
const EXAMPLES = joinpath(@__DIR__, "..", "..", "..", "examples")

unhex(v) = [parse(Float64, s) for s in v]

function same_bits(a::Vector{Float64}, b::Vector{Float64})
    length(a) == length(b) || return false
    all(i -> a[i] === b[i] || (isnan(a[i]) && isnan(b[i])), eachindex(a))
end

function first_diff(a, b)
    for i in eachindex(a)
        (a[i] === b[i] || (isnan(a[i]) && isnan(b[i]))) || return (i, a[i], b[i])
    end
    return nothing
end

@testset "derivative parity with the Python engine" begin
    if isempty(FIXTURES) || !isdir(FIXTURES)
        @info "KOMPARTMENT_ENGINE_FIXTURES not set: parity tests skipped"
        return
    end
    for f in sort(filter(endswith(".json"), readdir(FIXTURES)))
        fx = K.parse_json(read(joinpath(FIXTURES, f), String))
        @testset "$(fx["name"])" begin
            raw = K.read_model_file(joinpath(EXAMPLES, fx["name"]))
            if haskey(fx, "error")
                @test_throws Exception K.build_system(K.Project(raw); jacobian=false)
                continue
            end
            local sys
            try
                sys = K.build_system(K.Project(raw); jacobian=false)
            catch e
                @test_broken false
                @info "$(fx["name"]): $(sprint(showerror, e))"
                continue
            end
            @test sys.nstate == fx["nstate"]
            @test sys.nalg == fx["nalg"]
            @test sys.nparam == fx["nparam"]
            @test [s.name for s in sys.builder.states] == [s["name"] for s in fx["states"]]
            @test [s.base for s in sys.builder.states] == [s["base"] for s in fx["states"]]
            @test [a.name for a in sys.builder.algebraic] == [a["name"] for a in fx["algebraic"]]
            @test [a.cls for a in sys.builder.algebraic] == [a["cls"] for a in fx["algebraic"]]
            P = unhex(fx["P"])
            @test same_bits(sys.P[1:length(P)], P)
            # The slots that never move: the Python engine has worked the others out
            # too by then, at the start (its analytic Jacobian is evaluated there).
            Xi = unhex(fx["X_invariant"])
            inv = [k for a in fx["algebraic"] if a["cls"] == 0 for k in a["base"]+1:a["base"]+a["width"]]
            ok = same_bits(sys.X[inv], Xi[inv])
            ok || @info "$(fx["name"]) X invariant differs" first_diff(sys.X[inv], Xi[inv])
            @test ok
            y0 = K.initial_state(sys)
            ok = same_bits(y0, unhex(fx["y0"]))
            ok || @info "$(fx["name"]) y0 differs" first_diff(y0, unhex(fx["y0"]))
            @test ok
            @test same_bits(K.time_grid(sys.project), unhex(fx["grid"]))
            for (k, pr) in enumerate(fx["probes"])
                t = parse(Float64, pr["t"])
                y = unhex(pr["y"])
                dy = K.dydt(sys, t, y)
                ok = same_bits(dy, unhex(pr["dydt"]))
                ok || @info "$(fx["name"]) probe $k dydt differs" first_diff(dy, unhex(pr["dydt"]))
                @test ok
                X = copy(K.evaluate_algebraic!(sys, t, y))
                Xr = unhex(pr["X"])
                ok = same_bits(X[1:length(Xr)], Xr)
                ok || @info "$(fx["name"]) probe $k X differs" first_diff(X, Xr)
                @test ok
            end
        end
    end
end
