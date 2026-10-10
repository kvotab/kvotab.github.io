# Transport sub-systems and numbers written with a unit, built and run bit for
# bit as the Python package builds and runs them.
#
# The models are tools/model_fixtures.py's (the made-up chains, unit
# literals and older files, or Ecolego projects imported with --eco), with
# the Python engine's numbers for them from tools/engine_fixtures.py and
# tools/run_fixtures.py, under one or more fixture roots:
#
#     ROOT/runnable/NAME.json or ROOT/text/NAME.json   the models
#     ROOT/engine/NAME.json                            the derivative, at a few states
#     ROOT/runs/NAME.json                              a whole run
#
#     KOMPARTMENT_TRANSPORT_FIXTURES=ROOT[:ROOT...] julia --project test/engine/transport.jl
#
# Each model is opened as `Kompartment.load` opens a file (normalised as
# Python's `Model` normalises one) and settled, as Python's `to_dict()`
# settles it, before it is built.

module TransportParityTests

using Test
using Kompartment
const K = Kompartment

const ROOTS = filter(isdir, split(get(ENV, "KOMPARTMENT_TRANSPORT_FIXTURES", ""), ':'; keepempty=false))

unhex(v) = [parse(Float64, s) for s in v]

function same_bits(a::AbstractVector{Float64}, b::AbstractVector{Float64})
    length(a) == length(b) || return false
    return all(i -> a[i] === b[i] || (isnan(a[i]) && isnan(b[i])), eachindex(a))
end

function first_diff(a, b)
    length(a) == length(b) || return (:length, length(a), length(b))
    for i in eachindex(a)
        (a[i] === b[i] || (isnan(a[i]) && isnan(b[i]))) || return (i, a[i], b[i])
    end
    return nothing
end

"""Where two texts first part, for the log."""
function first_text_difference(got, want)
    gl, wl = split(got, '\n'), split(want, '\n')
    k = findfirst(i -> i > length(gl) || i > length(wl) || gl[i] != wl[i], 1:max(length(gl), length(wl)))
    k === nothing && return nothing
    return (line=k, julia=k <= length(gl) ? gl[k] : "<none>", python=k <= length(wl) ? wl[k] : "<none>")
end

"""The model a fixture was made from."""
function model_path(root, name)
    for sub in ("runnable", "text")
        p = joinpath(root, sub, name)
        isfile(p) && return p
    end
    return nothing
end

"""The error as the Python fixtures write it: `Type: message`."""
said(e) = "$(nameof(typeof(e))): $(sprint(showerror, e))"

"""
    check_error(err, want)

The error the Python engine raised, said the same way. A `ValidationError` that
names its block is said without the name here as long as the struct's own
constructor (message and block both `String`s) is chosen over the one in
src/engine/project.jl that writes `block: message`; that case is marked broken,
so it shows up once that is mended.
"""
function check_error(err, want)
    @test err !== nothing
    err === nothing && return
    if err isa K.ValidationError && err.block !== nothing && said(err) != want &&
       want == "ValidationError: $(err.block): $(err.message)"
        @test_broken said(err) == want
    else
        @test said(err) == want
    end
end

"""The model opened and settled, as Python's `Model.load(path).to_dict()` gives it."""
function opened(path)
    m = K.load(path)
    K.settle!(m.raw)
    return m
end

@testset "transports and unit literals against the Python engine" begin
    if isempty(ROOTS)
        @info "KOMPARTMENT_TRANSPORT_FIXTURES not set: transport parity tests skipped"
        return
    end
    for root in ROOTS
        # The engine's Project of each model, and of it with its transports
        # written out, as Python's Project.to_json() writes them.
        text = joinpath(root, "text")
        projects = isdir(text) ? sort(filter(endswith(".project.json"), readdir(text))) : String[]
        @testset "project: $(f)" for f in projects
            name = f[1:end-length(".project.json")]
            m = opened(joinpath(text, name * ".input.json"))
            p = K.Project(m.raw)
            got = K.json_text(K.project_to_json(p))
            want = read(joinpath(text, f), String)
            got == want || @info "$name: Project.to_json differs" first_text_difference(got, want)
            @test got == want
            expanded = joinpath(text, name * ".expanded.json")
            if isfile(expanded)
                got = K.json_text(K.project_to_json(K.expand_transports(p)))
                want = read(expanded, String)
                got == want || @info "$name: the expanded project differs" first_text_difference(got, want)
                @test got == want
            end
        end
        engine = joinpath(root, "engine")
        isdir(engine) || continue
        @testset "derivative: $(f)" for f in sort(filter(endswith(".json"), readdir(engine)))
            fx = K.parse_json(read(joinpath(engine, f), String))
            path = model_path(root, fx["name"])
            @test path !== nothing
            path === nothing && continue
            if haskey(fx, "error")
                err = try
                    K.build_system(K.Project(opened(path).raw); jacobian=false)
                    nothing
                catch e
                    e
                end
                check_error(err, fx["error"])
                continue
            end
            m = opened(path)
            p = K.Project(m.raw)
            sys = K.build_system(p; jacobian=false)
            @test sys.nstate == fx["nstate"]
            @test sys.nalg == fx["nalg"]
            @test sys.nparam == fx["nparam"]
            @test [s.name for s in sys.builder.states] == [s["name"] for s in fx["states"]]
            @test [s.base for s in sys.builder.states] == [s["base"] for s in fx["states"]]
            @test [a.name for a in sys.builder.algebraic] == [a["name"] for a in fx["algebraic"]]
            @test [a.cls for a in sys.builder.algebraic] == [a["cls"] for a in fx["algebraic"]]
            P = unhex(fx["P"])
            @test same_bits(sys.P[1:length(P)], P)
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
                ok || @info "$(fx["name"]) probe $k X differs" first_diff(X[1:length(Xr)], Xr)
                @test ok
            end
            got = fx["derivative_blocks"] === nothing ? nothing : sort!(collect(sys.builder.derivative_blocks))
            @test got == fx["derivative_blocks"]
        end
        runs = joinpath(root, "runs")
        isdir(runs) || continue
        @testset "run: $(f)" for f in sort(filter(endswith(".json"), readdir(runs)))
            fx = K.parse_json(read(joinpath(runs, f), String))
            path = model_path(root, fx["name"])
            @test path !== nothing
            path === nothing && continue
            if haskey(fx, "error")
                err = try
                    run(opened(path))
                    nothing
                catch e
                    e
                end
                check_error(err, fx["error"])
                continue
            end
            m = opened(path)
            res = run(m)
            outs = K.outputs(res)
            @test [o["label"] for o in outs] == [o["label"] for o in fx["outputs"]]
            cols = K.series_many(res, outs)
            stats_same = all(get(res.stats, k, nothing) == v for (k, v) in fx["stats"] if k != "held") &&
                         (!haskey(fx["stats"], "held") || collect(res.stats["held"]) == fx["stats"]["held"])
            t_same = same_bits(res.t, unhex(fx["t"]))
            series_same = length(cols) == length(fx["series"]) &&
                          all(same_bits(c, unhex(w)) for (c, w) in zip(cols, fx["series"]))
            identical = stats_same && t_same && series_same && K.to_csv(res) == fx["csv"]
            if identical || get(fx["stats"], "sparse", false) !== true
                for (k, v) in fx["stats"]
                    k == "held" && continue
                    got = get(res.stats, k, nothing)
                    got == v || @info "$(fx["name"]) stats[$k]: $got, Python $v"
                    @test got == v
                end
                haskey(fx["stats"], "held") && @test collect(res.stats["held"]) == fx["stats"]["held"]
                t_same || @info "$(fx["name"]) t differs" first_diff(res.t, unhex(fx["t"]))
                @test t_same
                for (o, c, want) in zip(fx["outputs"], cols, fx["series"])
                    ok = same_bits(c, unhex(want))
                    ok || @info "$(fx["name"]) $(o["label"]) differs" first_diff(c, unhex(want))
                    @test ok
                end
                @test K.to_csv(res) == fx["csv"]
            else
                # The sparse path factorises with SciPy's SuperLU in Python and with
                # KLU here (src/solvers/): the solves round differently in the last
                # bits, and a stiff run carries that on, while the derivative and the
                # analytic Jacobian are the same to the bit. The same run within its
                # tolerance, then.
                @test_broken identical
                t_same || @info "$(fx["name"]): the output times (the solver's own steps here) differ, so the series are not compared"
                if t_same
                    rtol = Float64(something(get(K.simulation(m), "rtol", nothing), 1e-3))
                    worst = 0.0
                    for (c, want) in zip(cols, fx["series"])
                        w = unhex(want)
                        fin = isfinite.(w)
                        scale = any(fin) ? maximum(abs, w[fin]) : 0.0
                        d = abs.(c .- w)
                        d = d[isfinite.(d)]
                        isempty(d) || scale == 0 || (worst = max(worst, maximum(d) / scale))
                    end
                    worst < 10 * rtol || @info "$(fx["name"]): sparse path, worst difference $worst of the scale"
                    @test worst < 10 * rtol
                end
            end
        end
    end
end

end # module TransportParityTests
