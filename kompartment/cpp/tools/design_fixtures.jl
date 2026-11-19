# Writes tests/fixtures/design.json: the designs the Julia package draws for
# probabilistic runs of models -- the sampling plan, the names, every value drawn
# to the bit, the statistics, a sensitivity design's own -- what a realisation in
# a range is set to, and the system a realisation is set into: its parameters,
# its invariant algebra, its tables, its events' dice. For the C++ engine's tests
# to compare with (tests/test_design.cpp).
#
#     julia --project=. ../cpp/tools/design_fixtures.jl        (from ../julia)
#
# The bundled examples (most have no distribution, and are refused in the
# Julia package's words), and models made up to reach each branch: every kind of
# distribution on parameters and their entries, lookup points that carry one,
# correlation groups and correlations with every problem, the plan narrowed by
# `simulation.varied`, a sub-system, a scenario list, disruptive events whose
# occurrences are drawn with fixed settings or not drawn (settings that follow
# the clock or the state, `sampled` false), events alone. Each under seeds,
# iteration counts, Latin hypercube or not, varied lists, tornadoes and every
# sensitivity method, and their refusals. A case's text is kept as an FNV-1a
# hash; with KOMPARTMENT_FIXTURE_DUMPS set every text is written there
# (`design.julia.txt`).

using Kompartment
const K = Kompartment
K.set_parity!(true)

bits(x::Float64) = isnan(x) ? "nan" : string(reinterpret(UInt64, x); base=16, pad=16)
function fnv(text::String)
    h = 0xcbf29ce484222325
    for b in codeunits(text)
        h = (h ⊻ b) * 0x100000001b3
    end
    return string(h; base=16, pad=16)
end
kept(text::String) = ncodeunits(text) <= 300 ? "=" * text : "#" * fnv(text)
nums(v) = join((bits(Float64(x)) for x in v), ",")
F(x::Real) = "f:" * string(reinterpret(UInt64, Float64(x)); base=16, pad=16)
unF(s::AbstractString) = reinterpret(Float64, parse(UInt64, s[3:end]; base=16))

function said(f)
    try
        return f()
    catch e
        e isa ArgumentError && return "error:ArgumentError:" * e.msg
        for T in (MethodError, InexactError, TypeError, BoundsError, OutOfMemoryError, DomainError, DivideError, KeyError)
            e isa T && return "error:" * string(nameof(T))
        end
        rethrow()
    end
end

function tdump(v)
    v === nothing && return "null"
    v isa Bool && return v ? "true" : "false"
    v isa Integer && return "i" * string(v)
    v isa AbstractFloat && return "f" * bits(Float64(v))
    v isa AbstractString && return "s(" * String(v) * ")"
    v isa AbstractMatrix && return "[" * join(("[" * join((tdump(v[r, c]) for c in axes(v, 2)), ",") * "]" for r in axes(v, 1)), ",") * "]"
    (v isa AbstractVector || v isa Tuple) && return "[" * join((tdump(x) for x in v), ",") * "]"
    v isa AbstractDict && return "{" * join((string(k) * "=" * tdump(x) for (k, x) in v), ";") * "}"
    error("cannot dump $(typeof(v))")
end

# --- the models --------------------------------------------------------------------------------------

const SIM = """{"start_time": 0, "end_time": 10, "output_points": 5, "spacing": "linear", "solver": "ndf", "rtol": 1e-6,
                "abstol": 1e-9, "time_unit": "year"}"""

models = Any[]
model(name, text) = push!(models, (name, K.parse_json(text)))

model("every kind", """{"name": "every kind", "simulation": $SIM,
 "index_lists": [{"name": "Zone", "indices": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}],
 "parameters": [
   {"name": "k_unif", "value": 0.1, "pdf": {"kind": "unif", "params": {"min": 0.05, "max": 0.2}}},
   {"name": "k_tri", "value": 3, "pdf": {"kind": "triang", "params": {"min": 1, "max": 5, "mode": 3}}},
   {"name": "k_dtri", "value": 2, "pdf": {"kind": "dtriang", "params": {"min": 1, "max": 4, "mode": 2}}},
   {"name": "k_norm", "value": 5, "pdf": {"kind": "norm", "params": {"mean": 5, "sd": 1}, "trmin": 3, "trmax": 7}},
   {"name": "k_logu", "value": 0.01, "pdf": {"kind": "logu", "params": {"min": 0.001, "max": 0.1}}},
   {"name": "k_logt", "value": 1e-4, "pdf": {"kind": "logt", "params": {"min": 1e-6, "max": 1e-2, "mode": 1e-4}, "pmin": 0.1, "pmax": 0.95}},
   {"name": "k_logdt", "value": 1, "pdf": {"kind": "logdt", "params": {"min": 0.1, "max": 10, "mode": 1}}},
   {"name": "k_logn4", "value": 2, "pdf": {"kind": "Logn4", "params": {"gm": 2, "gsd": 1.5}}},
   {"name": "k_logn", "value": 3, "pdf": {"kind": "logn", "params": {"mean": 3, "sd": 1}, "trmax": "4"}},
   {"name": "k_logn5", "value": 3, "pdf": {"kind": "logn5", "params": {"p1": 0.05, "x1": 1, "p2": 0.95, "x2": 10}}},
   {"name": "k_list", "value": 2, "pdf": {"kind": "pg", "values": [1, 2, "x", true, null, 4], "inorder": true, "pos": 1}},
   {"name": "k_list2", "value": 6, "pdf": {"kind": "pg", "values": [5, 6, "w", 7], "inorder": false}},
   {"name": "k_bad", "value": 1, "pdf": {"kind": "unif", "params": {"min": 1}}},
   {"name": "k_none", "value": 1},
   {"name": "Kd", "value": 0.5, "index_lists": ["Zone"], "pdf": {"kind": "unif", "params": {"min": 0.1, "max": 1}},
    "entries": [{"index": {"Zone": "a"}, "value": 0.2, "pdf": {"kind": "logt", "params": {"min": 0.01, "max": 1, "mode": 0.1}}},
                {"index": {"Zone": "c"}, "value": 0.7, "pdf": null}]}],
 "compartments": [{"name": "A", "initial": "1", "index_lists": ["Zone"]}, {"name": "B", "initial": "0", "index_lists": ["Zone"]}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "Kd * k_unif", "index_lists": ["Zone"]}],
 "expressions": [{"name": "E", "equation": "k_tri + k_norm * k_logt + k_list + k_list2 + k_logn5"},
                 {"name": "EK", "equation": "Kd * 2 + k_dtri", "index_lists": ["Zone"]}],
 "inflows": []}""")

model("groups and correlations", """{"name": "groups", "simulation": {"start_time": 0, "end_time": 10, "output_points": 5,
  "spacing": "linear", "solver": "ndf", "time_unit": "year", "correlations": [
    {"a": "p1", "b": "p2", "r": 0.8}, {"a": "p2", "b": "p3", "r": 0.7}, {"a": "p1", "b": "p3", "r": -0.6},
    {"group": "Kd", "r": 0.5}, {"a": "p4", "b": "p4", "r": 0.3}, {"a": "p1", "b": "nope", "r": 0.2},
    {"a": "p2", "b": "p1", "r": 0.1}, {"a": "p1", "b": "Rf", "r": 0.4}, {"a": "Kd[d]", "b": "p4", "r": -0.3}, {"r": 2}]},
 "index_lists": [{"name": "Zone", "indices": [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}]}],
 "parameters": [
   {"name": "p1", "value": 1, "pdf": {"kind": "unif", "params": {"min": 0, "max": 2}}},
   {"name": "p2", "value": 1, "pdf": {"kind": "norm", "params": {"mean": 1, "sd": 0.2}}},
   {"name": "p3", "value": 1, "pdf": {"kind": "triang", "params": {"min": 0, "max": 3, "mode": 1}}},
   {"name": "p4", "value": 1, "pdf": {"kind": "logu", "params": {"min": 0.1, "max": 10}}},
   {"name": "Rf", "value": 1, "pdf": {"kind": "unif", "params": {"min": 1, "max": 5}, "group": " sorb "}},
   {"name": "Kd", "value": 1, "index_lists": ["Zone"], "pdf": {"kind": "logu", "params": {"min": 0.01, "max": 1}, "group": "sorb"},
    "entries": [{"index": {"Zone": "d"}, "value": 1, "pdf": {"kind": "unif", "params": {"min": 0.5, "max": 1.5}, "group": 5}}]},
   {"name": "q", "value": 2, "pdf": {"kind": "pg", "values": [1, 2, 3], "group": ["x", 1.5, null]}},
   {"name": "w", "value": 2, "pdf": {"kind": "unif", "params": {"min": 1, "max": 3}, "group": "  "}},
   {"name": "v", "value": 2, "pdf": {"kind": "unif", "params": {"min": 1, "max": 3}, "group": 2.5}}],
 "compartments": [{"name": "A", "initial": "p1 + p2"}],
 "transfers": [{"name": "Out", "from": "A", "to": null, "rate": "p3 * p4 * Rf * q * w * v * 0.01"}],
 "expressions": [{"name": "S", "equation": "Kd * 2", "index_lists": ["Zone"]}],
 "inflows": []}""")

model("tables", """{"name": "tables", "simulation": $SIM,
 "index_lists": [{"name": "Zone", "indices": [{"name": "a"}, {"name": "b"}]}],
 "parameters": [{"name": "k", "value": 1, "pdf": {"kind": "unif", "params": {"min": 0.5, "max": 2}}}],
 "lookups": [
   {"name": "Q", "points": [[0, 1, {"kind": "unif", "params": {"min": 0.5, "max": 1.5}}], [5, 2], [10, 3, {"kind": "norm", "params": {"mean": 3, "sd": 0.3}}]],
    "interpolation": "linear"},
   {"name": "F", "argument": "x", "points": [[0, 0], [2, 1, {"kind": "triang", "params": {"min": 0.5, "max": 1.5, "mode": 1}}], [4, 3]],
    "interpolation": "linear"},
   {"name": "R", "index_lists": ["Zone"], "points": [[0, 1], [10, 2]],
    "entries": [{"index": {"Zone": "b"}, "points": [[10, 5, {"kind": "unif", "params": {"min": 4, "max": 6}}], [0, 4, {"kind": "pg", "values": [3, "no", 5]}]]}]}],
 "compartments": [{"name": "A", "initial": "1"}],
 "transfers": [{"name": "Out", "from": "A", "to": null, "rate": "k * Q * 0.01"}],
 "expressions": [{"name": "G", "equation": "F(2.5) + F(1) + k"}, {"name": "H", "equation": "R", "index_lists": ["Zone"]}],
 "inflows": []}""")

const EVENTS = """[
   {"name": "E1", "timing": "poisson", "rate": "quake_rate", "from": "", "until": "", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.1"}]},
   {"name": "E2", "timing": "poisson", "rate": "quake_rate * 2", "from": "t0", "until": "500", "actions": [{"kind": "move", "from": "A", "to": null, "fraction": "0.05"}]},
   {"name": "E3", "timing": "poisson", "rate": "0.01 * time()", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.1"}]},
   {"name": "E4", "timing": "poisson", "rate": "A * 1e-4", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.1"}]},
   {"name": "E5", "timing": "poisson", "rate": "0.001", "sampled": false, "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.1"}]},
   {"name": "E6", "timing": "at", "at": "250", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.1"}]},
   {"name": "E7", "timing": "poisson", "rate": "0.003", "sampled": 0, "from": "-50", "until": "2000", "actions": [{"kind": "move", "from": "B", "to": "A", "fraction": "0.2"}]},
   {"name": "E8", "timing": "poisson", "rate": "0", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.1"}]},
   {"name": "E9", "timing": "poisson", "rate": "50", "from": "10", "until": "20", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.01"}]},
   {"name": "E10", "timing": "poisson", "rate": "t0 / 1e4", "from": "900", "until": "t0 * 2", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.01"}]}]"""
model("events", """{"name": "events", "simulation": {"start_time": 0, "end_time": 1000, "output_points": 5, "spacing": "linear",
  "solver": "ndf", "time_unit": "year"},
 "parameters": [{"name": "quake_rate", "value": 0.002, "pdf": {"kind": "logu", "params": {"min": 0.001, "max": 0.01}}},
                {"name": "t0", "value": 100, "pdf": {"kind": "unif", "params": {"min": 50, "max": 150}}}],
 "compartments": [{"name": "A", "initial": "100"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "0.001"}],
 "events": $EVENTS, "expressions": [], "inflows": []}""")

model("events alone", """{"name": "dice only", "simulation": {"start_time": 0, "end_time": 1000, "output_points": 5, "spacing": "linear",
  "solver": "ndf", "time_unit": "year"},
 "parameters": [{"name": "quake_rate", "value": 0.002}, {"name": "t0", "value": 100}],
 "compartments": [{"name": "A", "initial": "100"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "0.001"}],
 "events": $EVENTS, "expressions": [], "inflows": []}""")

model("events never drawn", """{"name": "no dice", "simulation": {"start_time": 0, "end_time": 1000, "output_points": 5, "spacing": "linear",
  "solver": "ndf", "time_unit": "year"},
 "parameters": [{"name": "r", "value": 0.002}],
 "compartments": [{"name": "A", "initial": "100"}],
 "events": [{"name": "E", "timing": "poisson", "rate": "r", "sampled": false, "actions": [{"kind": "move", "from": "A", "to": null, "fraction": "0.1"}]},
            {"name": "F", "timing": "at", "at": "5", "actions": [{"kind": "move", "from": "A", "to": null, "fraction": "0.1"}]}],
 "transfers": [], "expressions": [], "inflows": []}""")

model("sub-system", """{"name": "sub", "simulation": $SIM, "systems": ["Far"],
 "parameters": [{"name": "k", "system": "Far", "value": 1, "pdf": {"kind": "unif", "params": {"min": 0, "max": 2}}},
                {"name": "k", "value": 2, "pdf": {"kind": "norm", "params": {"mean": 2, "sd": 0.5}}}],
 "compartments": [{"name": "A", "system": "Far", "initial": "1"}, {"name": "B", "initial": "1"}],
 "transfers": [{"name": "T", "system": "Far", "from": "A", "to": null, "rate": "k"}, {"name": "U", "from": "B", "to": null, "rate": "k"}],
 "expressions": [], "inflows": []}""")

scen = K.parse_json(read(joinpath(@__DIR__, "..", "..", "examples", "scenarios.json"), String))
for p in scen["parameters"]
    if p["name"] == "Runoff"
        p["pdf"] = K.parse_json("""{"kind": "unif", "params": {"min": 0.01, "max": 0.03}}""")
        p["entries"][1]["pdf"] = K.parse_json("""{"kind": "unif", "params": {"min": 0.015, "max": 0.025}}""")
    elseif p["name"] == "Flush"
        p["pdf"] = K.parse_json("""{"kind": "logu", "params": {"min": 0.05, "max": 0.2}}""")
    end
end
push!(models, ("scenarios with distributions", scen))
# The same in another scenario, and with the distribution a scenario's own only: a realisation
# draws from the distribution of the scenario that runs.
scen_drier = K.jcopy(scen)
scen_drier["scenario"] = "Drier"
push!(models, ("scenarios with distributions, the drier one", scen_drier))
scen_own = K.jcopy(scen)
for p in scen_own["parameters"]
    p["name"] == "Runoff" && delete!(p, "pdf")
end
push!(models, ("scenarios with a distribution of one scenario's own", scen_own))

kinds = models[1][2]
for (what, varied) in (("varied in the settings", Any["k_unif", "Kd[b]", "nope", 5, "Q@0"]), ("varied naming nothing there", Any["nope"]),
                       ("varied empty", Any[]), ("varied as text", "k_unif"), ("varied by block name", Any["Kd", "k_list"]))
    m = K.jcopy(kinds)
    m["simulation"]["varied"] = varied
    push!(models, (what, m))
end

examples_dir = joinpath(@__DIR__, "..", "..", "examples")
examples = sort!([splitext(f)[1] for f in readdir(examples_dir) if endswith(f, ".json")])

# --- the options a design is asked for ---------------------------------------------------------------

J(pairs...) = K.JDict(String(k) => v for (k, v) in pairs)
GSA = Any[J("method" => "morris", "options" => J("trajectories" => 3, "points" => 4, "levels" => 4)),
          J("method" => "morris", "options" => J("design" => "trajectories", "trajectories" => 2, "candidates" => 4, "levels" => 4)),
          J("method" => "sobol", "options" => J("samples" => 4, "second" => true)),
          J("method" => "efast", "options" => J("samples" => 20, "harmonics" => 2)),
          J("method" => "rbdfast", "options" => J("samples" => 16, "harmonics" => 2)),
          J("method" => "ff"),
          J("method" => "dgsm", "options" => J("samples" => 3, "crossed" => true)),
          J("method" => "radial", "options" => J("samples" => 4)),
          J("method" => "shapley", "options" => J("perms" => 2, "nVar" => 6, "nOuter" => 1, "nInner" => 2))]
OPTIONS = Any[J(),
              J("seed" => 7, "iterations" => 13, "latin" => false),
              J("seed" => "abc", "iterations" => 2),
              J("seed" => 3, "iterations" => 3),
              J("iterations" => 1),
              J("iterations" => F(0.4)),
              J("iterations" => F(2.5)),
              J("iterations" => F(-5)),
              J("seed" => 11, "iterations" => 40, "varied" => Any["k_unif", "Kd[a]", "p1", "p2", "Rf", "Q@0", "quake_rate", "Flush", "k"]),
              J("seed" => 5, "iterations" => 6, "varied" => Any[]),
              J("tornado" => true),
              J("tornado" => J("low" => 0.1, "high" => 0.8), "varied" => Any["k_unif", "Kd[b]", "p2", "Kd[d]", "q", "F@2", "t0", "Runoff"]),
              J("tornado" => J("high" => 1)),
              J("tornado" => J("low" => "x")),
              # The ends read as the application reads them: text as a number, null as no end given.
              J("tornado" => J("low" => " 0.2 ", "high" => nothing)),
              J("tornado" => J("low" => true, "high" => Any["0x0.8"], "other" => 1)),
              J("tornado" => J("low" => "", "high" => Any[0.9])),
              J("tornado" => J(), "iterations" => 4),
              J("tornado" => false, "iterations" => 4),
              J("tornado" => 0, "seed" => 2),
              J("gsa" => J("method" => "nope")),
              J("gsa" => "text"),
              J("gsa" => J(), "iterations" => 3),
              J("gsa" => J("method" => "morris", "options" => "x")),
              J("gsa" => J("method" => "ff"), "varied" => Any[]),
              J("gsa" => GSA[9], "varied" => Any["p1", "p2", "p3", "Kd[a]", "Kd[d]", "k_unif", "k_tri"], "seed" => 9),
              J("seed" => "1e400", "iterations" => 3),
              J("iterations" => F(NaN)),
              J("iterations" => F(1e300))]
for g in GSA
    push!(OPTIONS, J("gsa" => g, "seed" => 4))
end

cases = Any[]
for (name, m) in models, o in OPTIONS
    push!(cases, K.JDict("name" => name, "model" => name, "options" => o))
end
for ex in examples
    push!(cases, K.JDict("name" => "example $ex", "example" => ex, "options" => J()))
end
for o in (J("seed" => 3, "iterations" => 25), J("seed" => 3, "iterations" => 25, "latin" => false), J("tornado" => true),
          J("gsa" => GSA[1], "seed" => 2), J("gsa" => GSA[3], "seed" => 2), J("gsa" => GSA[9], "seed" => 2),
          J("seed" => 8, "iterations" => 10, "varied" => Any["Kd[I-129]", "Kd[Cs-135]", "rho", "intake"]))
    push!(cases, K.JDict("name" => "example biosphere", "example" => "biosphere", "options" => o))
end
for o in (J("iterations" => 4), J("tornado" => true), J("gsa" => GSA[6]), J("iterations" => 3, "seed" => "q"))
    push!(cases, K.JDict("name" => "example waste-packages", "example" => "waste-packages", "options" => o))
end

# --- what each case gives ------------------------------------------------------------------------------

function options_of(o)
    it = haskey(o, "iterations") ? (v = o["iterations"]; v isa AbstractString ? unF(v) : Float64(v)) : nothing
    return (seed=get(o, "seed", 1), iterations=it, latin=get(o, "latin", true),
            varied=haskey(o, "varied") ? String[string(v) for v in o["varied"]] : nothing,
            tornado=get(o, "tornado", nothing), gsa=get(o, "gsa", nothing))
end

"""The system a realisation is set into: its parameters, invariant slots, tables and dice."""
function system_text(sys)
    X = Float64[sys.X[i] for i in 1:sys.nalg if sys.slot_class[i] == 0]
    tabs = join((nums(t.y) for t in sys.data.TAB), ";")
    times = join((nums(t) for t in sys.sampled_times), ";")
    return "P=$(nums(sys.P))\nX=$(nums(X))\nTAB=$tabs\nDIS=$(nums(sys.data.DIS))\nT=$times"
end

function run_case(c, model)
    project = K.Project(model)
    sys = K.build_system(project)
    o = options_of(c["options"])
    local d
    try
        d = K.design_for(project, sys; o...)
    catch e
        return said(() -> throw(e))
    end
    n = d.iterations
    lines = String["plan=" * tdump(Any[e for e in d.plan]), "names=" * join(d.names, "|"), "best=" * nums(d.best),
                   "varies=" * join(Int.(d.varies), ""), "iterations=$n", "values=" * nums(vec(d.values)), "seed=" * tdump(d.seed),
                   "stats=" * tdump(d.stats), "gsa=" * (d.gsa_design === nothing ? "none" : tdump(d.gsa_design)),
                   "designed=$(K.is_designed(d)),$(K.is_tornado(d)),$(K.is_gsa(d))"]
    for (frm, to) in ((0, n), (1, min(n, 4)), (n - 1, n), (0, 0), (2, 2), (n, n + 1), (3, 1))
        push!(lines, "effective $frm $to=" * said(() -> nums(vec(K._pb_effective(d, frm, to)))))
    end
    eff = K._pb_effective(d, 0, n)
    push!(lines, "built\n" * system_text(sys))
    for i in (0, 1, n - 1, 1)
        0 <= i < n || continue
        # (A seed that cannot be read fails here first where nothing is sampled but the dice.)
        failed = said(() -> (K._pb_apply!(sys, d, eff, i + 1, i); ""))
        if !isempty(failed)
            push!(lines, "realisation $i: $failed")
            break
        end
        push!(lines, "realisation $i\n" * system_text(sys))
    end
    return join(lines, "\n")
end

examples_raw = Dict(ex => K.parse_json(read(joinpath(examples_dir, ex * ".json"), String)) for ex in examples)
# Written and read back: both engines start from the very values the file holds.
models_json = K.JDict(name => m for (name, m) in models)
back = K.parse_json(K.json_text(K.JDict("models" => models_json, "cases" => cases); indent=0))
models_json, cases = back["models"], back["cases"]
const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
texts = String[]
for c in cases
    m = haskey(c, "example") ? examples_raw[c["example"]] : models_json[c["model"]]
    took = @elapsed text = run_case(c, m)
    took > 5 && println(stderr, c["name"], ": ", round(took; digits=1), " s")
    push!(texts, "## $(c["name"]) $(K.json_text(c["options"]; indent=0))\n$text")
    c["out"] = kept(text)
end
isempty(DUMPS) || write(joinpath(DUMPS, "design.julia.txt"), join(texts, "\n\n"))
endpoints = Any[Any[k, K.can_be_endpoint(k)] for k in Any["parameter", "lookup", "compartment", "expression", nothing, 5, ""]]
path = joinpath(@__DIR__, "..", "tests", "fixtures", "design.json")
write(path, K.json_text(K.JDict("endpoints" => endpoints, "models" => models_json, "cases" => cases); indent=0))
println(path, ": ", length(cases), " cases, ", count(c -> startswith(c["out"], "=error"), cases), " refused")
