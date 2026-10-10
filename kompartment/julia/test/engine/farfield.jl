# The far-field pathway against the Python engine, bit for bit
# (tools/farfield_fixtures.py writes the fixtures: the bundled example and
# variants of it -- matched and reference layers, every outflow condition,
# settings following the clock and the state, other index lists, the
# semi-analytical method -- with the layout and the derivative at probe states,
# the analytic Jacobian there, whole runs, and every unit response a
# semi-analytical path tabulates). Point KOMPARTMENT_FARFIELD_FIXTURES at that
# directory; without it only the checks that need no fixtures run.
module FarfieldTests

using Test
using Kompartment
const K = Kompartment

const DIR = get(ENV, "KOMPARTMENT_FARFIELD_FIXTURES", "")
const EXAMPLES = joinpath(@__DIR__, "..", "..", "..", "examples")

unhex(v) = Float64[parse(Float64, s) for s in v]
same_bits(a, b) = length(a) == length(b) && all(i -> a[i] === b[i] || (isnan(a[i]) && isnan(b[i])), eachindex(a))
fixture(sub, f) = K.parse_json(read(joinpath(DIR, sub, f), String))
model_of(name) = K.read_model_file(joinpath(DIR, "models", name * ".json"))
names_in(sub) = isdir(joinpath(DIR, sub)) ? sort([f[1:end-5] for f in readdir(joinpath(DIR, sub)) if endswith(f, ".json")]) :
                String[]
"""What Python said, without the exception's class name."""
said(msg) = replace(msg, r"^[A-Za-z_]+(Error|Exception): " => "")

function small_example(; semi=false)
    raw = K.read_model_file(joinpath(EXAMPLES, "farfield.json"))
    p = raw["farfields"][1]
    p["n_f"] = 6
    p["n_m"] = 6
    p["tw"] = "50 * (1 + 0.5 * rampUp(time, 1e3, 1e4))"
    if semi
        p["method"] = "semi-analytical"
        p["tw"] = "50"
    end
    raw["simulation"]["end_time"] = 2e4
    raw["simulation"]["matrix"] = "dense"
    return raw
end

@testset "far-field pathway" begin
    @testset "a run is reproducible and a clone runs alike" begin
        for semi in (false, true)
            p = K.Project(small_example(; semi=semi))
            sys = K.build_system(p)
            a = K.run_project(p; system=sys)
            b = K.run_project(p; system=K.clone_system(sys))
            c = K.run_project(p; system=sys)
            @test a.stats["nsteps"] == b.stats["nsteps"] == c.stats["nsteps"]
            for (x, y, z) in zip(K.series_many(a, K.outputs(a)), K.series_many(b, K.outputs(b)),
                                 K.series_many(c, K.outputs(c)))
                @test all(x .=== y)
                @test all(x .=== z)
            end
        end
    end

    @testset "the refresh and the release allocate nothing" begin
        p = K.Project(small_example())
        sys = K.build_system(p)
        F = only(sys.data.FARF)
        X = sys.X
        y = K.initial_state(sys) .+ 1.0
        tw = sys.builder.alg_by_name["Rock#tw"].base + 1
        K.farfield_release!(F, y, X)
        X[tw] += 1.0
        K.farfield_release!(F, y, X)
        X[tw] += 1.0
        @test (@allocated K.farfield_refresh!(F, X)) == 0
        X[tw] += 1.0
        @test (@allocated K.farfield_release!(F, y, X)) == 0
    end

    if isempty(DIR) || !isdir(DIR)
        @info "KOMPARTMENT_FARFIELD_FIXTURES not set: far-field parity tests skipped"
    else
        @testset "unit responses of $(name)" for name in names_in("resp")
            fx = fixture("resp", name * ".json")
            for p in fx["paths"]
                st = K.LPSettings(something(p["surface"], "f"),
                                  Dict{String,Float64}(k => parse(Float64, v) for (k, v) in p["single"]),
                                  Dict{String,Vector{Float64}}(k => unhex(v) for (k, v) in p["each"]))
                D = p["D"] === nothing ? nothing :
                    K.LPDecay(unhex(p["D"]["lam"]), Int.(p["D"]["ioff"]), Int.(p["D"]["icnt"]), Int.(p["D"]["ipar"]),
                              unhex(p["D"]["icoef"]))
                names = p["names"] === nothing ? nothing : String.(p["names"])
                path = K.prepare_path(st, D, p["nnuc"], names)
                @test same_bits(K.transfer_at_zero(path), unhex(p["T0"]))
                @test path.ws.evaluations == p["evals0"]
                span = parse(Float64, p["span"])
                for r in p["responses"]
                    jr = K.unit_response(path, r["i"], r["j"], span)
                    @test same_bits(jr.t, unhex(r["t"]))
                    @test same_bits(jr.h, unhex(r["h"]))
                    @test same_bits(jr.dh, unhex(r["dh"]))
                    @test same_bits(jr.d2h, unhex(r["d2h"]))
                    @test jr.m0 === parse(Float64, r["m0"])
                    @test jr.integral === parse(Float64, r["integral"])
                    @test jr.T0 === parse(Float64, r["T0"])
                    @test jr.rel === parse(Float64, r["rel"])
                    @test jr.balanced == r["balanced"]
                    # the same control flow, not just the same numbers
                    @test path.ws.evaluations == r["evals"]
                end
            end
        end

        @testset "derivative of $(name)" for name in names_in("engine")
            fx = fixture("engine", name * ".json")
            raw = model_of(name)
            if haskey(fx, "error")
                err = try
                    K.build_system(K.Project(raw))
                    nothing
                catch e
                    e
                end
                @test err !== nothing
                err === nothing || @test sprint(showerror, err) == said(fx["error"])
                continue
            end
            sys = K.build_system(K.Project(raw))
            @test sys.nstate == fx["nstate"]
            @test sys.nalg == fx["nalg"]
            @test [s.name for s in sys.builder.states] == [s["name"] for s in fx["states"]]
            @test [s.base for s in sys.builder.states] == [s["base"] for s in fx["states"]]
            @test [a.name for a in sys.builder.algebraic] == [a["name"] for a in fx["algebraic"]]
            @test [a.cls for a in sys.builder.algebraic] == [a["cls"] for a in fx["algebraic"]]
            Xi = unhex(fx["X_invariant"])
            inv = [k for a in fx["algebraic"] if a["cls"] == 0 for k in a["base"]+1:a["base"]+a["width"]]
            @test same_bits(sys.X[inv], Xi[inv])
            @test same_bits(K.initial_state(sys), unhex(fx["y0"]))
            for pr in fx["probes"]
                t = parse(Float64, pr["t"])
                y = unhex(pr["y"])
                @test same_bits(K.dydt(sys, t, y), unhex(pr["dydt"]))
                Xr = unhex(pr["X"])
                @test same_bits(copy(K.evaluate_algebraic!(sys, t, y))[1:length(Xr)], Xr)
            end
            jf = joinpath(DIR, "jac", name * ".json")
            if isfile(jf)
                jx = fixture("jac", name * ".json")
                j = sys.jacobian
                @test j.available == jx["available"]
                @test j.constant == jx["constant"]
                @test j.pattern.colptr .- 1 == jx["col_ptr"]
                @test j.pattern.rowval .- 1 == jx["row_idx"]
                if j.available && jx["available"]
                    for (k, pr) in enumerate(fx["probes"])
                        J = zeros(K.pattern_nnz(j.pattern))
                        K.analytic_evaluate!(J, j.analytic, parse(Float64, pr["t"]), unhex(pr["y"]))
                        @test same_bits(J, unhex(jx["values"][k]))
                    end
                end
            end
        end

        @testset "run of $(name)" for name in names_in("runs")
            fx = fixture("runs", name * ".json")
            raw = model_of(name)
            if haskey(fx, "error")
                err = try
                    K.run_project(K.Project(raw))
                    nothing
                catch e
                    e
                end
                @test err !== nothing
                err === nothing || @test sprint(showerror, err) == said(fx["error"])
                continue
            end
            res = K.run_project(K.Project(raw))
            outs = K.outputs(res)
            @test [o["label"] for o in outs] == [o["label"] for o in fx["outputs"]]
            for (o, po) in zip(outs, fx["outputs"])
                for key in ("block", "kind", "nuclide", "index", "dims", "unit", "source", "offset", "timeDependent")
                    a = get(o, key, nothing)
                    b = get(po, key, nothing)
                    @test a == b || (a isa AbstractVector && b isa AbstractVector && collect(a) == collect(b))
                end
            end
            cols = K.series_many(res, outs)
            if get(fx["stats"], "sparse", false) === true || res.system.nstate > 200
                # Only the application's own dense LU (up to 200 states) is the same
                # arithmetic on both engines: on the sparse LU the Python engine
                # factorises with SuperLU and this one with KLU, and above 200 dense
                # states each with its own LAPACK. Their round-off parts after the
                # first steps, so the run is held to the solver's tolerance instead.
                @test res.stats["nsteps"] == fx["stats"]["nsteps"]
                for (c, ph) in zip(cols, fx["series"])
                    p = unhex(ph)
                    sc = maximum(abs, p; init=0.0)
                    @test length(c) == length(p) && (sc == 0 ? all(iszero, c) : maximum(abs.(c .- p)) / sc < 1e-6)
                end
                continue
            end
            for (k, v) in fx["stats"]
                k == "held" && continue
                @test string(get(res.stats, k, nothing)) == string(v)
            end
            haskey(fx["stats"], "held") && @test collect(get(res.stats, "held", Int[])) == collect(fx["stats"]["held"])
            @test same_bits(res.t, unhex(fx["t"]))
            for (c, ph) in zip(cols, fx["series"])
                @test same_bits(c, unhex(ph))
            end
            @test K.to_csv(res) == fx["csv"]
        end
    end
end

end # module
