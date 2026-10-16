# The analyses that solve a model again, against the Python package's
# (tools/analysis_fixtures.py): the global sensitivity designs, calibration by
# each of its methods, and dy/dp -- bit for bit, in parity mode.
#
# From kompartment/julia (the fixtures go to a scratch directory, never the repository):
#
#     PYTHONPATH=../python python3 tools/analysis_fixtures.py <scratch>/analyses
#     KOMPARTMENT_ANALYSIS_FIXTURES=<scratch>/analyses julia --project=. test/engine/analyses.jl
#
# Without the fixtures, what needs nothing but the bundled examples: the
# designs' settings, refusals and layouts, a design's runs and how they are
# saved, a calibration that finds a known answer, and dy/dp against the
# solution of exponential decay.

using Test
if !@isdefined(K)
    using Kompartment
    const K = Kompartment
end
K.set_parity!(true)

const ANALYSIS_FIXTURES = get(ENV, "KOMPARTMENT_ANALYSIS_FIXTURES", "")
const ANALYSIS_EXAMPLES = joinpath(@__DIR__, "..", "..", "..", "examples")

_ex(name) = K.load(joinpath(ANALYSIS_EXAMPLES, name))

"""Exponential decay with a uniform distribution on each of its two parameters."""
function _decay_with_spreads()
    raw = K.parse_json(read(joinpath(ANALYSIS_EXAMPLES, "exponential-decay.json"), String))
    pdf(lo, hi) = K.JDict("kind" => "unif", "params" => K.JDict("min" => lo, "max" => hi), "values" => nothing,
                          "trmin" => nothing, "trmax" => nothing, "inorder" => true, "pos" => 0)
    raw["parameters"][1]["pdf"] = pdf(0.5, 1.5)
    raw["parameters"][2]["pdf"] = pdf(0.5, 2.0)
    return K.Model(raw)
end

@testset "sensitivity designs" begin
    # Settings: the defaults, what can be read of what is given, and Shapley's that follow K.
    o = K.gsa_options("sobol", 3, Dict("samples" => "40", "second" => 1, "estimator" => "nope", "blocks" => 2.4))
    @test o == K.OrderedDict("samples" => 40, "second" => true, "blocks" => 2, "estimator" => "jansen1999",
                             "resamples" => 100)
    @test (K.gsa_options("shapley", 3)["perms"], K.gsa_options("shapley", 3)["nOuter"]) == (0, 10)
    @test (K.gsa_options("shapley", 6)["perms"], K.gsa_options("shapley", 6)["nOuter"]) == (100, 1)
    @test isempty(K.gsa_options("nope", 3))
    # Refusals, in the application's words.
    @test K.gsa_refusal("nope", 3) == "There is no method called nope."
    @test K.gsa_refusal("sobol", 0) == "Nothing is sampled, so there is nothing to vary."
    @test K.gsa_refusal("morris", 3, Dict("design" => "trajectories", "trajectories" => 5, "candidates" => 3)) ==
          "Fewer candidates than trajectories to keep; 0 keeps every one drawn."
    @test K.gsa_refusal("sobol", 3, Dict("samples" => 4, "blocks" => 5)) == "More blocks than samples."
    @test K.gsa_refusal("rbdfast", 3, Dict("samples" => 20, "harmonics" => 6)) == "Too many harmonics for so few samples."
    @test K.gsa_refusal("ff", 3, Dict("low" => 0.9, "high" => 0.1)) ==
          "The two levels must be probabilities, the low one below the high."
    @test K.gsa_refusal("shapley", 9, Dict("perms" => 0)) ==
          "All 9! orders of 9 inputs is too many; give a number of random orders."
    @test K.gsa_refusal("shapley", 9) === nothing      # a hundred random orders, past four inputs
    @test K.gsa_refusal("dgsm", 3) === nothing
    # Every method's layout: as many runs as it says, every probability inside (0, 1).
    keys_ = ["a", "b", "c"]
    for (method, options) in (("morris", Dict()), ("morris", Dict("design" => "trajectories", "candidates" => 12)),
                              ("radial", Dict("samples" => 5)), ("sobol", Dict("samples" => 4, "second" => true)),
                              ("efast", Dict("samples" => 70)), ("rbdfast", Dict("samples" => 40)), ("ff", Dict()),
                              ("dgsm", Dict("samples" => 5, "crossed" => true)), ("shapley", Dict("nVar" => 10)))
        d = K.build_design(method, keys_, options; seed=7)
        @test size(d["u"]) == (3, K.gsa_runs(method, 3, options)) == (3, d["runs"])
        @test all(u -> 0 <= u <= 1, d["u"])
        @test d["seed"] == 7 && d["options"] == K.gsa_options(method, 3, options)
        # The same seed, the same design; another, another.
        @test K.build_design(method, keys_, options; seed=7)["u"] == d["u"]
        method == "ff" || @test K.build_design(method, keys_, options; seed=8)["u"] != d["u"]
    end
    # Saltelli's: A, B, then A with each column from B.
    d = K.build_design("sobol", keys_, Dict("samples" => 4); seed=7)
    A, B = d["u"][:, 1:4], d["u"][:, 5:8]
    for j in 1:3
        AB = d["u"][:, 4j+5:4j+8]
        @test AB[j, :] == B[j, :] && AB[setdiff(1:3, j), :] == A[setdiff(1:3, j), :]
    end
    # The factorial: each input low or high, the second half the first's mirror.
    f = K.build_design("ff", keys_, Dict("low" => 0.1, "high" => 0.8); seed=7)["u"]
    @test size(f) == (3, 8) && all(u -> u in (0.1, 0.8), f)
    @test all(f[:, 1:4] .+ f[:, 5:8] .== 0.9)
    # A walk's points sit at the middles of the levels.
    w = K.build_design("morris", keys_, Dict("levels" => 8); seed=7)["u"]
    @test all(u -> isinteger(u * 8 - 0.5), w)
    @test_throws ArgumentError K.build_design("sobol", keys_, Dict("samples" => 1))

    # A design run on a model: a factor per input, its points read through the distributions.
    m = _decay_with_spreads()
    prob = K.run_gsa(m, "ff"; keep=["y"], threads=1)
    @test prob.iterations == 4 && size(prob.gsa_design["u"]) == (2, 4)
    g = prob.stats["gsa"]
    @test g["method"] == "ff" && g["factors"] == [K.OrderedDict("key" => "k", "group" => nothing, "members" => [1]),
                                                   K.OrderedDict("key" => "y0", "group" => nothing, "members" => [2])]
    @test (g["correlated"], g["correlationsUsed"], g["correlationShrunk"]) == (0, false, 0.0)
    @test sort(unique(prob.samples[1, :])) == [0.5 + 0.05 * 1.0, 0.5 + 0.95 * 1.0]
    @test sort(unique(prob.samples[2, :])) == [0.5 + 0.05 * 1.5, 0.5 + 0.95 * 1.5]
    # Each run is the model at its point: y(2) = y0 exp(-2k), to the run's tolerance.
    at2 = findfirst(==(2.0), prob.t)
    for i in 1:4
        k, y0 = prob.samples[1, i], prob.samples[2, i]
        @test isapprox(prob["y"][i, at2], y0 * exp(-2k); rtol=1e-5)
    end
    # The page counts a factor's inputs from 0.
    meta = K.parse_json(String(copy(K._ds_unzip(K.sample_archive(prob))["results/sample/meta.json"])))
    @test [f["members"] for f in meta["stats"]["gsa"]["factors"]] == [[0], [1]]
    # Only what is varied is a factor; the rest is held at its own value.
    held = K.run_gsa(m, "ff"; keep=["y"], varied=["k"], threads=1)
    @test length(held.stats["gsa"]["factors"]) == 1 && all(==(1.0), held.samples[2, :])
    @test_throws ArgumentError K.run_gsa(m, "ff"; varied=["nothere"])
    # A realisation of a design, replayed as a run.
    one = K.run_realisation(m, 3; gsa=Dict("method" => "ff"))
    @test one.number == 3 && one.iterations == 4 && [v.value for v in one.values] == prob.samples[:, 3]
end

@testset "calibration" begin
    m = _ex("exponential-decay.json")
    want = log(5) / 2          # y(2) = exp(-2k) = 0.2
    targets = [Dict("output" => "y", "when" => "at", "time" => 2, "value" => 0.2)]
    steps = Any[]
    r = K.calibrate(m; targets, variables=[Dict("key" => "k", "lower" => 0.1, "upper" => 3)], max_evals=80,
                    on_progress=p -> push!(steps, p))
    @test r["ok"] && r["matched"] && r["method"] == "nelder"
    @test isapprox(r["values"][1]["value"], want; rtol=1e-4) && r["values"][1]["was"] == 1.0
    @test r["values"][1]["pinned"] === nothing && r["values"][1]["lower"] == 0.1
    @test [p.evals for p in steps] == collect(1:r["evals"])
    @test issorted([p.best for p in steps]; rev=true)
    @test r["targets"][1]["output"] == "y" && isapprox(r["targets"][1]["got"], 0.2; rtol=1e-6)
    # The model is put back as it was.
    @test K.run(m)["y"] == K.run(_ex("exponential-decay.json"))["y"]
    # Levenberg-Marquardt in the logarithm, and differential evolution from a seed: the same answer.
    lm = K.calibrate(m; targets, variables=[Dict("key" => "k", "lower" => 0.1, "upper" => 3, "space" => "log")],
                     method="lm")
    @test lm["matched"] && lm["reason"] == "converged" && isapprox(lm["values"][1]["value"], want; rtol=1e-4)
    de = K.calibrate(m; targets, variables=[Dict("key" => "k", "lower" => 0.1, "upper" => 3)], method="de",
                     max_evals=300, seed=5)
    @test isapprox(de["values"][1]["value"], want; rtol=1e-3)
    # A search stopped before it starts has nothing to say.
    stopped = K.calibrate(m; targets, variables=[Dict("key" => "k", "lower" => 0.1, "upper" => 3)],
                          signal=Ref(true))
    @test (stopped["ok"], stopped["reason"], stopped["evals"], stopped["values"]) == (false, "stopped", 0, [])
    # Refused, in the application's words.
    @test_throws K.OptimiseError K.calibrate(m; targets=[], variables=[Dict("key" => "k")])
    err(; kw...) = try
        K.calibrate(m; targets, kw...)
        nothing
    catch e
        sprint(showerror, e)
    end
    @test err(variables=[Dict("key" => "kk", "lower" => 0, "upper" => 1)]) == "'kk' is not a parameter of this model."
    @test err(variables=[Dict("key" => "k", "lower" => 2, "upper" => 1)]) == "'k' has no range: 2 to 1."
    @test err(variables=[Dict("key" => "k", "lower" => 0, "upper" => 1, "space" => "log")]) ==
          "'k' is searched in the logarithm, so both bounds have to be above zero."
    @test [v["key"] for v in K.variables_of(m)] == ["k", "y0"]
end

@testset "dy/dp" begin
    m = _ex("exponential-decay.json")
    # y = y0 exp(-k t): dy/dk = -t y0 exp(-k t), dy/dy0 = exp(-k t).
    for differenced in (false, true)
        r = K.run_sensitivity(m, ["k", "y0"]; differenced)
        @test r.tangent == !differenced
        @test [c["label"] for c in r.chosen] == ["k", "y0"] && [c["value"] for c in r.chosen] == [1.0, 1.0]
        @test r.series[1]["label"] == "y" && !r.series[1]["hidden"] && r.stats["states"] == 3
        @test maximum(abs.(r.y[1] .- exp.(-r.t))) < 1e-5
        @test maximum(abs.(r.sens[1][1] .+ r.t .* exp.(-r.t))) < 1e-5
        @test maximum(abs.(r.sens[2][1] .- exp.(-r.t))) < 1e-5
        @test K.elasticity(r.y[1], r.sens[1][1], 1.0)[end] ≈ -10 rtol = 1e-4
    end
    # The slots, as the page names them.
    @test K.slot_label(K.parameter_slots(K.build_system(K.project(_ex("biosphere.json"))))[1]) == "leachRate[I-129]"
    # Refused, each for its own reason, in the application's words.
    refusal(name, params; kw...) = try
        K.run_sensitivity(_ex(name), params; kw...)
        nothing
    catch e
        e isa K.SensitivityError ? e.message : rethrow()
    end
    @test startswith(refusal("bouncing-ball.json", ["g"]), "'T_bounce' remembers the path of the run")
    @test startswith(refusal("waste-packages.json", ["matrix_rate"]), "'Glaciation' makes the state jump at t=100000")
    @test startswith(refusal("post-processing.json", ["DC[I-129]"]),
                     "This model has no analytic Jacobian, and the sensitivity equations are driven by it.")
    @test refusal("decay-chain.json", String[]) == "Name at least one parameter to take the sensitivity to."
    @test startswith(refusal("exponential-decay.json", ["k", "y0"]; most=1), "2 parameters at once")
    @test_throws ArgumentError K.run_sensitivity(m, "k")
end

@testset "dy/dp past a far-field path" begin
    # The far-field example on two cells of each kind. A path's rates read its
    # settings and its cells are states: along a parameter the settings do not read
    # (a leach rate into it, the flow of the well it releases into) df/dp is
    # generated; along one they read (a diffusivity, a Kd) it is differenced.
    small() = (m = K.parse_json(read(joinpath(ANALYSIS_EXAMPLES, "farfield.json"), String));
               m["farfields"][1]["n_f"] = 2; m["farfields"][1]["n_m"] = 2; K.Model(m))
    sys = K.build_system(K.project(small()))
    t = K.param_tangent(sys)
    @test t.available
    slots = K.parameter_slots(sys)
    @test sort([K.slot_label(e) for e in slots if e["slot"] in t.read]) ==
          ["$p[$n]" for p in ("De_matrix", "Kd_matrix") for n in ("Th-230", "U-234", "U-238")]
    along(label) = (w = zeros(sys.nparam);
                    w[only(e["slot"] for e in slots if K.slot_label(e) == label)+1] = 1.0;
                    K.param_pvp(t.plan, 10.0, K.initial_state(sys), w))
    @test all(isfinite, along("leach_rate[U-234]")) && all(isnan, along("De_matrix[U-234]"))
    # U-234's leach rate: generated, the run goes through; differenced, the leach term
    # is lost to the rounding of U-238's ingrowth in the vault, far past dy/dp's absolute
    # tolerance, and the solver gives up -- which is said as that.
    r = K.run_sensitivity(small(), ["leach_rate[U-234]"])
    @test r.exact == [true] && r.stats["nsteps"] > 100 && all(isfinite, r.sens[1][1])
    e = try
        K.run_sensitivity(small(), ["leach_rate[U-234]"]; differenced=true)
        nothing
    catch err
        err
    end
    @test e isa K.SolverError && e.kind == "stalled"
    @test startswith(e.message, "The sensitivity equations could not be integrated past t=0.00000")
    @test occursin("df/dp along leach_rate[U-234] is worked out by a difference, as asked, which is right to about " *
                   "eight figures", e.message)
    @test endswith(e.message, "the model's absolute tolerance over the parameter's value, 1.0e-12 for " *
                              "leach_rate[U-234]. A looser absolute tolerance is the first thing to try.")
    @test occursin(r"^The solver stopped making progress at t=[^ ]+: 2000 accepted steps advanced the clock by less " *
                   r"than 0\.0001, and the step size is no longer growing\.$", e.hint)
end

# --- against the Python package -----------------------------------------------------------------

_fx(v) = v isa AbstractDict ? (haskey(v, "\$f") ? parse(Float64, v["\$f"]) :
                               Dict{String,Any}(String(k) => _fx(x) for (k, x) in v)) :
         v isa AbstractVector ? Any[_fx(x) for x in v] : v
_mine(v) = v isa AbstractDict ? Dict{String,Any}(String(k) => _mine(x) for (k, x) in v) :
           v isa NamedTuple ? Dict{String,Any}(String(k) => _mine(x) for (k, x) in pairs(v)) :
           v isa AbstractVector ? Any[_mine(x) for x in v] : v
"""Equal as JSON is: numbers by value (a NaN equal to a NaN), whatever their type."""
_alike(a, b) = (a isa Real && !(a isa Bool) && b isa Real && !(b isa Bool)) ? isequal(Float64(a), Float64(b)) :
               (a isa AbstractDict && b isa AbstractDict) ?
               (Set(keys(a)) == Set(keys(b)) && all(_alike(a[k], b[k]) for k in keys(a))) :
               (a isa AbstractVector && b isa AbstractVector) ?
               (length(a) == length(b) && all(_alike(x, y) for (x, y) in zip(a, b))) : isequal(a, b)
_hexes(v) = Float64[parse(Float64, s) for s in v]

@testset "the analyses against the Python package" begin
    if isempty(ANALYSIS_FIXTURES)
        @info "No analysis fixtures: run tools/analysis_fixtures.py OUTDIR and pass OUTDIR in " *
              "KOMPARTMENT_ANALYSIS_FIXTURES to check the designs, calibrations and dy/dp bit for bit"
        @test true
    else
        @testset "design $(splitext(f)[1])" for f in sort(readdir(joinpath(ANALYSIS_FIXTURES, "designs")))
            fx = K.parse_json(read(joinpath(ANALYSIS_FIXTURES, "designs", f), String))
            proj = K.project(K.Model(fx["model"]))
            varied = fx["varied"] === nothing ? nothing : String[v for v in fx["varied"]]
            d = K.design_for(proj, K.build_system(proj); seed=fx["seed"], gsa=fx["gsa"], varied)
            @test d.names == fx["names"] && d.iterations == fx["iterations"]
            @test isequal(d.gsa_design["u"], permutedims(reduce(hcat, [_hexes(r) for r in fx["u"]])))
            @test isequal(d.values, permutedims(reduce(hcat, [_hexes(r) for r in fx["values"]])))
            @test _alike(_mine(K._sample_stats(d.stats)["gsa"]), _fx(fx["stats"]))
        end
        @testset "calibration $(splitext(f)[1])" for f in sort(readdir(joinpath(ANALYSIS_FIXTURES, "calibrations")))
            fx = K.parse_json(read(joinpath(ANALYSIS_FIXTURES, "calibrations", f), String))
            steps = Any[]
            got = try
                K.calibrate(_ex(fx["file"]); targets=get(fx, "targets", nothing),
                            variables=get(fx, "variables", nothing), method=get(fx, "method", nothing),
                            max_evals=get(fx, "maxEvals", nothing), seed=get(fx, "seed", nothing),
                            on_progress=p -> push!(steps, p))
            catch e
                e isa K.OptimiseError || rethrow()
                e
            end
            if haskey(fx, "error")
                @test got isa K.OptimiseError && got.message == fx["error"][2]
            else
                delete!(got, "ms")
                @test _alike(_mine(got), _fx(fx["result"]))
                @test _alike(_mine(steps), _fx(fx["steps"]))
            end
        end
        @testset "dy/dp $(splitext(f)[1])" for f in sort(readdir(joinpath(ANALYSIS_FIXTURES, "sensitivity")))
            fx = K.parse_json(read(joinpath(ANALYSIS_FIXTURES, "sensitivity", f), String))
            got = try
                K.run_sensitivity(K.Model(fx["model"]), String[p for p in fx["parameters"]];
                                  differenced=fx["differenced"])
            catch e
                e
            end
            if haskey(fx, "error")
                @test got isa Exception && sprint(showerror, got) == fx["error"][2]
                # A solve that gives up: the solver's own words, as its hint.
                fx["error"][3] === nothing || @test got.hint == fx["error"][3]
            else
                @test got.t == _hexes(fx["t"])
                @test all(isequal(got.y[i], _hexes(fx["y"][i])) for i in eachindex(fx["y"]))
                @test all(isequal(got.sens[k][i], _hexes(fx["sens"][k][i]))
                          for k in eachindex(fx["sens"]) for i in eachindex(fx["sens"][k]))
                @test got.stats["nsteps"] == fx["nsteps"] && got.stats["restarts"] == fx["restarts"]
                @test _alike(_mine(got.chosen), _fx(fx["chosen"]))
                @test [(s["offset"], s["label"], s["hidden"]) for s in got.series] ==
                      [(s["offset"], s["label"], s["hidden"]) for s in fx["series"]]
            end
        end
        @testset "df/dp generated: $name" for (name, want) in
                K.parse_json(read(joinpath(ANALYSIS_FIXTURES, "tangents.json"), String))
            t = K.param_tangent(K.build_system(K.project(_ex(name))))
            @test t.available == want["available"] && t.reason == want["reason"]
            @test sort!(collect(t.read)) == want["read_by_paths"]
        end
    end
end
