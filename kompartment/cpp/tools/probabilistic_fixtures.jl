# Writes tests/fixtures/probabilistic.json: probabilistic runs by the Julia package
# with parity on -- every realisation of the series kept, to the bit, in the
# precision held -- and what is read off them, for the C++ engine's tests to
# compare with (tests/test_probabilistic.cpp).
#
#     julia --project=. ../cpp/tools/probabilistic_fixtures.jl        (from ../julia)
#
# The bundled examples (most have no distribution, and are refused in the Julia
# package's words; some are given a spread on every parameter, as
# julia/tools/prob_fixtures.py gives them), and models made up to reach each
# branch: every kind of distribution on parameters and their entries, lookup
# points with spreads, Poisson events and timed ones (a run reported at times
# besides the grid), events alone, realisations that fail for some draws and a
# first realisation that fails, a value that stops being a number mid-run, draws
# that are no number, derived series, far-field paths on cells (sums of states)
# and semi-analytical, histories, a model with no states. Each under seeds,
# Latin hypercube or not, varied lists, keep lists by block and by label, a range
# of realisations, tornadoes, every sensitivity method with a small design,
# float32 holding forced by a small `most_bytes`, and the size refusal.
#
# For each run: the times, the kept series' descriptors and every value, the
# samples, which ran, the inputs, the statistics (without "ms" and "threads"),
# the run log (with "ms" and "threads" fixed), the sample archive's entries (the
# meta's stamp fixed, every binary entry hashed), the bands for several
# percentiles and masks, the answers the service gives (`realisations`,
# `column`, `realisation`, `bands`) and its refusals, and a series' quantiles,
# mean and median intervals. Besides: realisations replayed as runs, one
# realisation's series taken out of its run by hand-made descriptors (sums of
# algebraic slots), and `percentiles_for` on odd lists. A case's text is kept as
# an FNV-1a hash; with KOMPARTMENT_FIXTURE_DUMPS set every text is written there
# (`probabilistic.julia.txt`).

using Kompartment
const K = Kompartment
K.set_parity!(true)

bits(x::Float64) = isnan(x) ? "nan" : string(reinterpret(UInt64, x); base=16, pad=16)
bits(x::Float32) = isnan(x) ? "nan" : string(reinterpret(UInt32, x); base=16, pad=8)
bits(x::Integer) = bits(Float64(x))
function fnv(bytes::AbstractVector{UInt8})
    h = 0xcbf29ce484222325
    for b in bytes
        h = (h ⊻ b) * 0x100000001b3
    end
    return string(h; base=16, pad=16)
end
fnv(text::AbstractString) = fnv(codeunits(String(text)))
kept(text::String) = ncodeunits(text) <= 300 ? "=" * text : "#" * fnv(text)
nums(v) = join((bits(x) for x in v), ",")

function said(f)
    try
        return f()
    catch e
        e isa ArgumentError && return "error:ArgumentError:" * e.msg
        e isa ErrorException && return "error:ErrorException:" * e.msg
        e isa K.SolverError && return "error:SolverError:" * e.message
        e isa K.BuildError && return "error:BuildError:" * e.message
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
    (v isa AbstractVector || v isa Tuple) && return "[" * join((tdump(x) for x in v), ",") * "]"
    v isa AbstractDict && return "{" * join((string(k) * "=" * tdump(x) for (k, x) in v), ";") * "}"
    error("cannot dump $(typeof(v))")
end

J(pairs...) = K.JDict(String(k) => v for (k, v) in pairs)
P(text) = K.parse_json(text)

# --- the models --------------------------------------------------------------------------------------

const SIM = """{"start_time": 0, "end_time": 10, "output_points": 5, "spacing": "linear", "solver": "ndf", "rtol": 1e-6,
                "abstol": 1e-9, "time_unit": "year"}"""

models = Any[]
model(name, text) = push!(models, (name, P(text)))

model("every kind", """{"name": "every kind", "simulation": $SIM,
 "index_lists": [{"name": "Zone", "indices": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}],
 "parameters": [
   {"name": "k_unif", "value": 0.1, "pdf": {"kind": "unif", "params": {"min": 0.05, "max": 0.2}}},
   {"name": "k_tri", "value": 3, "pdf": {"kind": "triang", "params": {"min": 1, "max": 5, "mode": 3}}},
   {"name": "k_dtri", "value": 2, "pdf": {"kind": "dtriang", "params": {"min": 1, "max": 4, "mode": 2}}},
   {"name": "k_norm", "value": 5, "pdf": {"kind": "norm", "params": {"mean": 5, "sd": 1}, "trmin": 3, "trmax": 7}},
   {"name": "k_logu", "value": 0.01, "pdf": {"kind": "logu", "params": {"min": 0.001, "max": 0.1}}},
   {"name": "k_logt", "value": 1e-4, "pdf": {"kind": "logt", "params": {"min": 1e-6, "max": 1e-2, "mode": 1e-4}, "pmin": 0.1, "pmax": 0.95}},
   {"name": "k_logn4", "value": 2, "pdf": {"kind": "Logn4", "params": {"gm": 2, "gsd": 1.5}}},
   {"name": "k_list", "value": 2, "pdf": {"kind": "pg", "values": [1, 2, "x", true, null, 4], "inorder": true, "pos": 1}},
   {"name": "k_list2", "value": 6, "pdf": {"kind": "pg", "values": [5, 6, "w", 7], "inorder": false}},
   {"name": "k_bad", "value": 1, "pdf": {"kind": "unif", "params": {"min": 1}}},
   {"name": "k_none", "value": 1},
   {"name": "Kd", "value": 0.5, "index_lists": ["Zone"], "pdf": {"kind": "unif", "params": {"min": 0.1, "max": 1}},
    "entries": [{"index": {"Zone": "a"}, "value": 0.2, "pdf": {"kind": "logt", "params": {"min": 0.01, "max": 1, "mode": 0.1}}},
                {"index": {"Zone": "c"}, "value": 0.7, "pdf": null}]}],
 "compartments": [{"name": "A", "initial": "1", "index_lists": ["Zone"]}, {"name": "B", "initial": "0", "index_lists": ["Zone"]}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "Kd * k_unif", "index_lists": ["Zone"]}],
 "expressions": [{"name": "E", "equation": "k_tri + k_norm * k_logt + k_list + k_list2 + k_bad + k_logn4"},
                 {"name": "EK", "equation": "Kd * 2 + k_dtri + k_logu", "index_lists": ["Zone"]}],
 "inflows": []}""")

model("small", """{"name": "small", "simulation": $SIM,
 "parameters": [{"name": "a", "value": 1, "pdf": {"kind": "unif", "params": {"min": 0.5, "max": 1.5}}},
                {"name": "b", "value": 2, "pdf": {"kind": "norm", "params": {"mean": 2, "sd": 0.2}}},
                {"name": "c", "value": 0.3, "pdf": {"kind": "triang", "params": {"min": 0.1, "max": 0.5, "mode": 0.3}, "group": "G"}},
                {"name": "d", "value": 0.4, "pdf": {"kind": "unif", "params": {"min": 0.2, "max": 0.6}, "group": "G"}}],
 "compartments": [{"name": "X", "initial": "a * 10"}, {"name": "Y", "initial": "0"}],
 "transfers": [{"name": "XY", "from": "X", "to": "Y", "rate": "b * c * 0.1"}, {"name": "Lost", "from": "Y", "to": null, "rate": "d * 0.05"}],
 "expressions": [{"name": "Sum", "equation": "X + Y"}], "inflows": []}""")

model("groups and correlations", """{"name": "groups", "simulation": {"start_time": 0, "end_time": 10, "output_points": 5,
  "spacing": "linear", "solver": "ndf", "time_unit": "year", "correlations": [
    {"a": "p1", "b": "p2", "r": 0.8}, {"a": "p2", "b": "p3", "r": 0.7}, {"a": "p1", "b": "p3", "r": -0.6},
    {"group": "Kd", "r": 0.5}, {"a": "p4", "b": "p4", "r": 0.3}, {"a": "p1", "b": "nope", "r": 0.2},
    {"a": "p1", "b": "Rf", "r": 0.4}, {"a": "Kd[d]", "b": "p4", "r": -0.3}]},
 "index_lists": [{"name": "Zone", "indices": [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}]}],
 "parameters": [
   {"name": "p1", "value": 1, "pdf": {"kind": "unif", "params": {"min": 0, "max": 2}}},
   {"name": "p2", "value": 1, "pdf": {"kind": "norm", "params": {"mean": 1, "sd": 0.2}}},
   {"name": "p3", "value": 1, "pdf": {"kind": "triang", "params": {"min": 0, "max": 3, "mode": 1}}},
   {"name": "p4", "value": 1, "pdf": {"kind": "logu", "params": {"min": 0.1, "max": 10}}},
   {"name": "Rf", "value": 1, "pdf": {"kind": "unif", "params": {"min": 1, "max": 5}, "group": " sorb "}},
   {"name": "Kd", "value": 1, "index_lists": ["Zone"], "pdf": {"kind": "logu", "params": {"min": 0.01, "max": 1}, "group": "sorb"},
    "entries": [{"index": {"Zone": "d"}, "value": 1, "pdf": {"kind": "unif", "params": {"min": 0.5, "max": 1.5}, "group": 5}}]}],
 "compartments": [{"name": "A", "initial": "p1 + p2"}],
 "transfers": [{"name": "Out", "from": "A", "to": null, "rate": "p3 * p4 * Rf * 0.01"}],
 "expressions": [{"name": "S", "equation": "Kd * 2", "index_lists": ["Zone"]}],
 "inflows": []}""")

model("tables", """{"name": "tables", "simulation": $SIM,
 "index_lists": [{"name": "Zone", "indices": [{"name": "a"}, {"name": "b"}]}],
 "parameters": [{"name": "k", "value": 1, "pdf": {"kind": "unif", "params": {"min": 0.5, "max": 2}}}],
 "lookups": [
   {"name": "Q", "points": [[0, 1, {"kind": "unif", "params": {"min": 0.5, "max": 1.5}}], [5, 2], [10, 3, {"kind": "norm", "params": {"mean": 3, "sd": 0.3}}]],
    "interpolation": "linear"},
   {"name": "R", "index_lists": ["Zone"], "points": [[0, 1], [10, 2]],
    "entries": [{"index": {"Zone": "b"}, "points": [[10, 5, {"kind": "unif", "params": {"min": 4, "max": 6}}], [0, 4, {"kind": "pg", "values": [3, "no", 5]}]]}]}],
 "compartments": [{"name": "A", "initial": "1"}],
 "transfers": [{"name": "Out", "from": "A", "to": null, "rate": "k * Q * 0.01"}],
 "expressions": [{"name": "H", "equation": "R * k", "index_lists": ["Zone"]}],
 "inflows": []}""")

const EVENTS = """[
   {"name": "E1", "timing": "poisson", "rate": "quake_rate", "from": "", "until": "", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.1"}]},
   {"name": "E2", "timing": "poisson", "rate": "quake_rate * 2", "from": "t0", "until": "500", "actions": [{"kind": "move", "from": "A", "to": null, "fraction": "0.05"}]},
   {"name": "E5", "timing": "poisson", "rate": "0.001", "sampled": false, "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.1"}]},
   {"name": "E6", "timing": "at", "at": "333", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.1"}]},
   {"name": "E9", "timing": "poisson", "rate": "0.02", "from": "10", "until": "200", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.01"}]}]"""
model("events", """{"name": "events", "simulation": {"start_time": 0, "end_time": 1000, "output_points": 5, "spacing": "linear",
  "solver": "ndf", "time_unit": "year"},
 "parameters": [{"name": "quake_rate", "value": 0.002, "pdf": {"kind": "logu", "params": {"min": 0.001, "max": 0.01}}},
                {"name": "t0", "value": 100, "pdf": {"kind": "unif", "params": {"min": 50, "max": 150}}}],
 "compartments": [{"name": "A", "initial": "100"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "0.001"}],
 "expressions": [{"name": "Moved", "equation": "B / (A + B)"}],
 "events": $EVENTS, "inflows": []}""")

model("events alone", """{"name": "dice only", "simulation": {"start_time": 0, "end_time": 1000, "output_points": 6, "spacing": "linear",
  "solver": "ndf", "time_unit": "year"},
 "parameters": [{"name": "quake_rate", "value": 0.004}, {"name": "t0", "value": 100}],
 "compartments": [{"name": "A", "initial": "100"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "0.001"}],
 "events": $EVENTS, "expressions": [], "inflows": []}""")

model("failing", """{"name": "some fail", "simulation": {"start_time": 0, "end_time": 1000, "output_points": 6, "spacing": "linear",
  "solver": "ndf", "time_unit": "year"},
 "parameters": [{"name": "k", "value": 1, "pdf": {"kind": "pg", "values": [1, 0, 2, 0, 3, 4, 0]}},
                {"name": "m", "value": 1, "pdf": {"kind": "unif", "params": {"min": 0.5, "max": 1.5}}}],
 "compartments": [{"name": "A", "initial": "1e3 / k"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "m * 1e-3"}], "expressions": [], "inflows": []}""")

model("first fails", """{"name": "first fails", "simulation": {"start_time": 0, "end_time": 1000, "output_points": 6, "spacing": "linear",
  "solver": "ndf", "time_unit": "year"},
 "parameters": [{"name": "k", "value": 1, "pdf": {"kind": "pg", "values": [0, 1, 2]}},
                {"name": "m", "value": 1, "pdf": {"kind": "unif", "params": {"min": 0.5, "max": 1.5}}}],
 "compartments": [{"name": "A", "initial": "1e3 / k"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "m * 1e-3"}], "expressions": [], "inflows": []}""")

model("not a number mid-run", """{"name": "mid-run", "simulation": {"start_time": 0, "end_time": 1000, "output_points": 6, "spacing": "linear",
  "solver": "ndf", "time_unit": "year"},
 "parameters": [{"name": "k", "value": 3, "pdf": {"kind": "unif", "params": {"min": 1.2, "max": 3}}}],
 "compartments": [{"name": "A", "initial": "100"}, {"name": "B", "initial": "0"}],
 "expressions": [{"name": "R", "equation": "sqrt(k - time / 500) * 1e-3"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "R"}], "inflows": []}""")

model("carry", """{"name": "gaps", "simulation": {"start_time": 0, "end_time": 1000, "output_points": 5, "spacing": "linear",
  "solver": "ndf", "time_unit": "year"},
 "parameters": [{"name": "p", "value": 1.0, "pdf": {"kind": "pg", "values": [0.5, null, 2.0, null, null, 4.0]}},
                {"name": "p_rand", "value": 1.0, "pdf": {"kind": "pg", "values": [null, 0.3, null, 0.9], "inorder": false}},
                {"name": "q_bad", "value": 1.0, "pdf": {"kind": "logt", "params": {"min": -1, "max": 10, "mode": 1}}},
                {"name": "w", "value": 1.0, "pdf": {"kind": "logu", "params": {"min": 0.1, "max": 10}}}],
 "compartments": [{"name": "C", "initial": "100"}],
 "transfers": [{"name": "Loss", "from": "C", "to": null, "rate": "1e-3 * p * p_rand * q_bad * w"}],
 "expressions": [{"name": "Seen", "equation": "p + 10 * p_rand + 100 * q_bad + 1000 * w"}], "inflows": []}""")

model("derived", """{"name": "derived", "simulation": {"start_time": 0, "end_time": 100, "output_points": 11, "spacing": "linear",
  "solver": "ndf", "rtol": 1e-7, "time_unit": "year"},
 "parameters": [{"name": "k", "value": 0.05, "pdf": {"kind": "unif", "params": {"min": 0.02, "max": 0.08}}},
                {"name": "s", "value": 2, "pdf": {"kind": "triang", "params": {"min": 1, "max": 3, "mode": 2}}}],
 "compartments": [{"name": "A", "initial": "100"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k"}, {"name": "Bout", "from": "B", "to": null, "rate": "0.01"}],
 "expressions": [{"name": "Flux", "equation": "k * A * s"}],
 "derived": [{"name": "PeakB", "kind": "max", "of": "B"}, {"name": "LeastFlux", "kind": "min", "of": "Flux"},
             {"name": "WhenB", "kind": "time_of_max", "of": "B"}, {"name": "B at 33", "kind": "at_time", "of": "B", "at": 33},
             {"name": "Released", "kind": "integral", "of": "Flux"}, {"name": "Mean10", "kind": "period_mean", "of": "Flux", "period": 10},
             {"name": "Sum20", "kind": "period_sum", "of": "B", "period": 20}, {"name": "Change", "kind": "period_change", "of": "A", "period": 25},
             {"name": "Rate", "kind": "period_rate", "of": "Released", "period": 10}, {"name": "PeakRelease", "kind": "max", "of": "Released"},
             {"name": "Nowhere", "kind": "max", "of": "Not a series"}],
 "inflows": []}""")

model("no states", """{"name": "no states", "simulation": $SIM,
 "parameters": [{"name": "a", "value": 1, "pdf": {"kind": "unif", "params": {"min": 0.5, "max": 1.5}}}],
 "lookups": [{"name": "T", "points": [[0, 1], [10, 3, {"kind": "unif", "params": {"min": 2, "max": 4}}]], "interpolation": "linear"}],
 "expressions": [{"name": "Y", "equation": "a * T * time"}], "compartments": [], "transfers": [], "inflows": []}""")

model("history", """{"name": "history", "simulation": {"start_time": 0, "end_time": 50, "output_points": 6, "spacing": "linear",
  "solver": "ndf", "time_unit": "year"},
 "parameters": [{"name": "k", "value": 0.1, "pdf": {"kind": "unif", "params": {"min": 0.05, "max": 0.2}}},
                {"name": "lag", "value": 5, "pdf": {"kind": "unif", "params": {"min": 2, "max": 8}}}],
 "compartments": [{"name": "A", "initial": "10"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k * (1 + sin(time))"}],
 "min_maxes": [{"name": "Peak", "of": "AB", "operation": "max"}],
 "running_means": [{"name": "Avg", "of": "AB"}],
 "delays": [{"name": "Late", "of": "A", "delay": "lag"}],
 "expressions": [{"name": "E", "equation": "Peak + Avg + Late"}], "inflows": []}""")

# Paths of made-up nuclides, a chain with a branch: the first semi-analytical, the second on cells, reporting every cell.
model("far field", """{"name":"far field",
  "simulation":{"start_time":0,"end_time":3e4,"output_points":8,"spacing":"log","solver":"ndf","rtol":1e-8,"abstol":1e-16,"time_unit":"year"},
  "nuclides":["Aa-1","Bb-2","Cc-3"],"half_lives":{"Aa-1":2000,"Bb-2":800,"Cc-3":5000},"chains":[["Aa-1","Bb-2",0.6],["Aa-1","Cc-3",0.4]],"decay_unit":"mol",
  "parameters":[{"name":"k_leach","value":1e-3,"index_lists":[],"pdf":{"kind":"logu","params":{"min":5e-4,"max":2e-3}}},
                {"name":"Pe_rock","value":10,"index_lists":[],"pdf":{"kind":"unif","params":{"min":5,"max":20}}},
                {"name":"Kd_deep","value":2e-3,"index_lists":[],"pdf":{"kind":"unif","params":{"min":1e-3,"max":4e-3}}}],
  "compartments":[{"name":"Near","initial":"0","index_lists":["Radionuclides"],"entries":[{"index":{"Radionuclides":"Aa-1"},"initial":"500"}]},
                  {"name":"Mid","initial":"0","index_lists":["Radionuclides"]},{"name":"Down","initial":"0","index_lists":["Radionuclides"]}],
  "transfers":[{"name":"Leach","from":"Near","to":"Rock","rate":"k_leach","multiply_by_donor":true},
               {"name":"Between","from":"Rock","to":"Mid","rate":"Rock","multiply_by_donor":false,"index_lists":["Radionuclides"]},
               {"name":"Onward","from":"Mid","to":"Deep","rate":"0.05","multiply_by_donor":true},
               {"name":"Out","from":"Deep","to":"Down","rate":"Deep","multiply_by_donor":false,"index_lists":["Radionuclides"]}],
  "farfields":[{"name":"Rock","method":"semi-analytical","index_lists":["Radionuclides"],"surface":"f","tw":"50","f":"5e4","kd_f":"2e-4","kd_m":"1e-3","de_m":"1e-4",
                "eps_m":"0.005","rho_m":"2700","pe":"Pe_rock","pen_dep":"0.1","pen_dep_0":"","n_f":5,"n_m":4,"o_b":4,"n_b":"","grid":"matched",
                "handle_decay":true,"report_cells":false,"unit":"mol/year"},
               {"name":"Deep","index_lists":["Radionuclides"],"surface":"aw","aw":"800","tw":"200","kd_f":"0","kd_m":"Kd_deep","de_m":"5e-5",
                "eps_m":"0.003","rho_m":"2600","pe":"4","pen_dep":"0.3","pen_dep_0":"0.004","n_f":4,"n_m":3,"o_b":1,"n_b":"","grid":"reference",
                "handle_decay":true,"report_cells":true,"unit":"mol/year"}], "expressions": [], "inflows": []}""")

scen = P(read(joinpath(@__DIR__, "..", "..", "examples", "scenarios.json"), String))
for p in scen["parameters"]
    if p["name"] == "Runoff"
        p["pdf"] = P("""{"kind": "unif", "params": {"min": 0.01, "max": 0.03}}""")
        p["entries"][1]["pdf"] = P("""{"kind": "unif", "params": {"min": 0.015, "max": 0.025}}""")
    elseif p["name"] == "Flush"
        p["pdf"] = P("""{"kind": "logu", "params": {"min": 0.05, "max": 0.2}}""")
    end
end
push!(models, ("scenarios with distributions", scen))

examples_dir = joinpath(@__DIR__, "..", "..", "examples")
examples = sort!([splitext(f)[1] for f in readdir(examples_dir) if endswith(f, ".json")])
examples_raw = Dict(ex => P(read(joinpath(examples_dir, ex * ".json"), String)) for ex in examples)

"""A bundled example with a spread of ten per cent either way on every parameter that is a number, and on the
second point of every lookup table (as julia/tools/prob_fixtures.py makes one)."""
function with_spread(ex)
    m = K.jcopy(examples_raw[ex])
    for key in ("layout", "view")
        delete!(m, key)
    end
    m["name"] = "$(get(m, "name", ex)) (spread)"
    for p in something(get(m, "parameters", nothing), Any[])
        v = get(p, "value", nothing)
        (v isa Bool || !(v isa Real) || v == 0) && continue
        lo, hi = minmax(0.9 * v, 1.1 * v)
        p["pdf"] = J("kind" => "unif", "params" => J("min" => lo, "max" => hi))
    end
    for lk in something(get(m, "lookups", nothing), Any[])
        pts = get(lk, "points", nothing)
        (pts isa AbstractVector && length(pts) >= 2 && pts[2] isa AbstractVector && length(pts[2]) >= 2) || continue
        y = pts[2][2]
        (y isa Real && !(y isa Bool) && y != 0) || continue
        lo, hi = minmax(0.9 * y, 1.1 * y)
        pts[2] = Any[pts[2][1], y, J("kind" => "triang", "params" => J("min" => lo, "max" => hi, "mode" => y))]
    end
    return m
end
for ex in ("recorders", "lookup-driver", "thermostat", "bouncing-ball", "four-compartment", "post-processing", "waste-packages")
    push!(models, ("$ex with a spread", with_spread(ex)))
end

# --- the cases ----------------------------------------------------------------------------------------------

GSA = Any[J("method" => "morris", "options" => J("trajectories" => 3, "points" => 4, "levels" => 4)),
          J("method" => "morris", "options" => J("design" => "trajectories", "trajectories" => 2, "candidates" => 4, "levels" => 4)),
          J("method" => "sobol", "options" => J("samples" => 4, "second" => true)),
          J("method" => "efast", "options" => J("samples" => 20, "harmonics" => 2)),
          J("method" => "rbdfast", "options" => J("samples" => 16, "harmonics" => 2)),
          J("method" => "ff"),
          J("method" => "dgsm", "options" => J("samples" => 3, "crossed" => true)),
          J("method" => "radial", "options" => J("samples" => 4)),
          J("method" => "shapley", "options" => J("perms" => 2, "nVar" => 6, "nOuter" => 1, "nInner" => 2))]

cases = Any[]
case(name, o) = push!(cases, J("name" => name, "model" => name, "options" => o))
example(ex, o) = push!(cases, J("name" => "example $ex", "example" => ex, "options" => o))

case("every kind", J("iterations" => 12, "seed" => 3))
case("every kind", J("iterations" => 9, "seed" => 7, "latin" => false))
case("every kind", J("iterations" => 10, "seed" => 5, "varied" => Any["k_unif", "Kd[b]", "k_list", "nope"], "keep" => Any["A", "E"]))
case("every kind", J("iterations" => 10, "seed" => 5, "keep" => Any["A [b]", "EK [c]", "AB [a]", "B"]))
case("every kind", J("iterations" => 11, "seed" => 2, "range" => Any[3, 8]))
case("every kind", J("iterations" => 11, "seed" => 2, "range" => Any[0, 100]))
case("every kind", J("iterations" => 6, "seed" => 2, "range" => Any[6, 6]))
case("every kind", J("tornado" => true))
case("every kind", J("tornado" => J("low" => 0.2, "high" => 0.7), "varied" => Any["k_unif", "Kd[b]", "k_list"], "keep" => Any["EK"]))
case("every kind", J("iterations" => 8, "seed" => 1, "most_bytes" => 100, "large" => true, "asked_bytes" => 1000000000))
case("every kind", J("iterations" => 8, "seed" => 1, "most_bytes" => 100))
case("every kind", J("iterations" => 8, "seed" => 1, "most_bytes" => 1000000000, "large" => true, "asked_bytes" => 50))
case("every kind", J("iterations" => 4, "seed" => 1, "keep" => Any["nothing here"]))
case("every kind", J("iterations" => 4, "seed" => 1, "keep" => Any[]))
case("every kind", J("iterations" => 30, "seed" => 9))
case("small", J("iterations" => 20, "seed" => 11))
case("small", J("tornado" => J("low" => 0.1, "high" => 0.9)))
case("small", J("tornado" => true, "varied" => Any["b"]))
for g in GSA
    case("small", J("gsa" => g, "seed" => 4))
end
case("small", J("gsa" => GSA[3], "seed" => 4, "keep" => Any["Sum"], "most_bytes" => 50, "large" => true, "asked_bytes" => 100000))
case("groups and correlations", J("iterations" => 12, "seed" => 2))
case("groups and correlations", J("iterations" => 12, "seed" => 2, "latin" => false, "varied" => Any["p1", "p2", "p4", "Kd[a]"]))
case("groups and correlations", J("gsa" => GSA[9], "seed" => 3))
case("tables", J("iterations" => 10, "seed" => 4))
case("tables", J("tornado" => true))
case("events", J("iterations" => 10, "seed" => 6))
case("events", J("tornado" => true))
case("events", J("gsa" => GSA[6], "seed" => 2))
case("events alone", J("iterations" => 6, "seed" => 2))
case("failing", J("iterations" => 14, "seed" => 8))
case("failing", J("iterations" => 14, "seed" => 8, "range" => Any[2, 9]))
case("first fails", J("iterations" => 5, "seed" => 1))
case("not a number mid-run", J("iterations" => 8, "seed" => 3))
case("carry", J("iterations" => 12, "seed" => 12))
case("carry", J("iterations" => 12, "seed" => 12, "range" => Any[4, 7]))
case("derived", J("iterations" => 6, "seed" => 1))
case("derived", J("iterations" => 6, "seed" => 1, "keep" => Any["Rate", "B at 33", "Flux"], "most_bytes" => 10, "large" => true, "asked_bytes" => 100000))
case("no states", J("iterations" => 5, "seed" => 2))
case("history", J("iterations" => 6, "seed" => 5))
case("far field", J("iterations" => 4, "seed" => 2))
case("scenarios with distributions", J("iterations" => 6, "seed" => 3))
for ex in ("recorders", "lookup-driver", "thermostat", "bouncing-ball", "four-compartment", "post-processing", "waste-packages")
    case("$ex with a spread", J("iterations" => 4, "seed" => 21))
end
for ex in examples
    example(ex, J("iterations" => 3, "seed" => 1))
end
example("biosphere", J("iterations" => 20, "seed" => 1))
example("biosphere", J("iterations" => 10, "seed" => 7, "latin" => false, "keep" => Any["Dose"]))
example("biosphere", J("iterations" => 12, "seed" => 9, "varied" => Any["Kd[I-129]", "soilLeach"], "keep" => Any["Dose", "Soil [I-129]"]))
example("biosphere", J("tornado" => J("low" => 0.05, "high" => 0.95), "keep" => Any["Dose"]))
example("waste-packages", J("iterations" => 8, "seed" => 5, "keep" => Any["Biosphere", "NearField"]))

replays = Any[]
replay(name, number, o) = push!(replays, J("name" => name, "model" => name, "number" => number, "options" => o))
for n in (1, 2, 12, 0, 15)
    replay("every kind", n, J("iterations" => 12, "seed" => 3))
end
replay("every kind", 3, J("tornado" => J("low" => 0.2, "high" => 0.7), "varied" => Any["k_unif", "Kd[b]", "k_list"]))
replay("small", 2, J("gsa" => GSA[1], "seed" => 4))
replay("carry", 5, J("iterations" => 12, "seed" => 12))
replay("events", 3, J("iterations" => 10, "seed" => 6))
replay("failing", 2, J("iterations" => 14, "seed" => 8))
replay("derived", 2, J("iterations" => 6, "seed" => 1, "latin" => false))
replay("far field", 3, J("iterations" => 4, "seed" => 2))

# --- what each case gives ---------------------------------------------------------------------------------

unF(s::AbstractString) = reinterpret(Float64, parse(UInt64, s[3:end]; base=16))
function options_of(o)
    iterations = haskey(o, "iterations") ? Float64(o["iterations"]) : nothing
    range = haskey(o, "range") ? (o["range"][1], o["range"][2]) : nothing
    return (iterations=iterations,
            kw=(seed=get(o, "seed", 1), latin=get(o, "latin", true),
                varied=haskey(o, "varied") ? String[string(v) for v in o["varied"]] : nothing,
                keep=haskey(o, "keep") ? String[string(v) for v in o["keep"]] : nothing,
                threads=1, range=range, tornado=get(o, "tornado", nothing), gsa=get(o, "gsa", nothing),
                most_bytes=get(o, "most_bytes", K.PROB_MOST_BYTES), asked_bytes=get(o, "asked_bytes", K.PROB_MOST_BYTES_ASKED),
                large=get(o, "large", false)))
end

"""The masks a case's bands are read under, made from the number of realisations."""
function masks(n)
    mixed = Any[1, 0, 0.5, nothing, "x", NaN, true, false, -0.0, 2]
    return Any[("none", nothing), ("bools", Bool[i % 3 != 1 for i in 0:n-1]), ("ints", Any[(i * 7) % 4 == 0 ? 0 : 1 for i in 0:n-1]),
               ("mixed", Any[mixed[i%length(mixed)+1] for i in 0:n-1]), ("short", Any[1 for _ in 1:max(0, n - 1)]),
               ("off", Any[0 for _ in 1:n])]
end
const PERCENTILES = Any[("default", nothing), ("tenths", Any[0.1, 0.9]), ("again", Any[0.9, 0.5, 0.05, 0.5]),
                        ("odd", Any[0, 1, -1, "0.25", true, nothing, "x", NaN, 0.75]), ("text", "0.3")]

function bands_text(bs)
    lines = String[]
    for b in bs
        push!(lines, "q=" * join((nums(y) for y in b["q"]), ";") * " at=" * nums(b["quantiles"]) * " mean=" * nums(b["mean"]) *
                     " sd=" * nums(b["sd"].sd) * " n=" * join(b["sd"].n, ",") * " med=" * join((nums(v) for v in values(b["med"])), ";") *
                     " flat=" * string(get(b, "flat", false)))
    end
    return join(lines, "\n")
end

"""The questions the service is asked of a kept sample, made from its shape, and their answers."""
function questions(n, count)
    all_ = Any[k for k in 0:count-1]
    return Any[("realisations", J("series" => all_)), ("realisations", J()), ("realisations", J("series" => 1)),
               ("column", J("series" => Any[0, count - 1], "at" => 1)), ("column", J("series" => Any[count - 1], "at" => 1000000)),
               ("column", J("series" => Any[0], "at" => -3)), ("column", J("series" => all_)),
               ("realisation", J("series" => all_, "index" => n - 1)), ("realisation", J("series" => Any[0], "index" => 1000000)),
               ("realisation", J("series" => Any[count - 1], "index" => -2)),
               ("bands", J("percentiles" => Any[0.1, 0.9], "mask" => Any[(i * 7) % 4 == 0 ? 0 : 1 for i in 0:n-1])),
               ("bands", J("percentiles" => nothing, "mask" => nothing)),
               ("bands", J("mask" => Any[1 for _ in 1:n+1])),
               ("realisations", J("series" => Any[count])), ("realisations", J("series" => Any[true])),
               ("realisations", J("series" => Any[1.0])), ("realisations", J("series" => Any[-1])),
               ("realisations", J("series" => "ab")), ("column", J("series" => J("a" => 1))),
               ("column", J("series" => Any[0], "at" => 2.5)), ("realisation", J("series" => Any[0], "index" => "x")),
               ("series", J("labels" => Any["x"])), ("forget", J())]
end

answer_dir = mktempdir()
function answer(op, prob, q)
    path = joinpath(answer_dir, "answer.f64")
    rm(path; force=true)
    q2 = copy(q)
    q2["out"] = path
    K._service_sample_answer(op, prob, q2)
    return nums(reinterpret(Float64, read(path)))
end

function entries_text(entries)
    lines = String[]
    for (name, bytes) in entries
        if endswith(name, ".json")
            push!(lines, "$name:\n" * String(copy(bytes)))
        else
            push!(lines, "$name=$(length(bytes)):" * fnv(bytes))
        end
    end
    return join(lines, "\n")
end

function run_case(c, model)
    project = K.Project(model)
    o = options_of(c["options"])
    local prob
    refused = said(() -> (prob = K.run_probabilistic(project, o.iterations; o.kw...); ""))
    isempty(refused) || return refused
    n = prob.iterations
    lines = String["precision=$(prob.precision) iterations=$n range=$(first(prob.range)):$(last(prob.range)) held=$(length(prob.ran))",
                   "plan=" * tdump(Any[e for e in prob.plan]), "names=" * join(prob.names, "|"),
                   "outputs=" * tdump(Any[x for x in prob.outputs]), "t=" * nums(prob.t)]
    for (w, M) in enumerate(prob.values)
        push!(lines, "series $w=" * nums(vec(permutedims(M))))
    end
    push!(lines, "samples=" * nums(vec(prob.samples)), "ran=" * join(Int.(prob.ran)), "inputs=" * tdump(Any[x for x in prob.inputs]))
    push!(lines, "stats=" * tdump(K.OrderedDict{String,Any}(k => v for (k, v) in prob.stats if !(k in ("ms", "threads")))))
    push!(lines, "labels=" * join(K.labels(prob), "|"))
    isempty(prob.outputs) || push!(lines, "realisations $(prob.outputs[end]["label"])=" * nums(Float64.(vec(permutedims(K.realisations(prob, prob.outputs[end]["label"]))))))
    push!(lines, "no such label=" * said(() -> nums(vec(K.realisations(prob, "no such label")))))
    isempty(prob.names) || push!(lines, "sample $(prob.names[end])=" * nums(K.sample(prob, prob.names[end])))
    prob.stats["ms"] = 1234.5
    prob.stats["threads"] = 1
    push!(lines, "log\n" * K.run_log(prob))
    prob.stats["threads"] = 3
    push!(lines, "log\n" * join(K.probabilistic_log_lines(prob), "\n"))
    for series in (true, false)
        push!(lines, "entries $series\n" * said(() -> entries_text(K.sample_entries(prob; stamp="then", series))))
    end
    count = K._an_count(prob)
    for (pname, pct) in PERCENTILES, (mname, mask) in masks(n)
        (pname == "default" || mname in ("none", "mixed")) || continue
        push!(lines, "bands $pname $mname\n" * said(() -> bands_text(K.bands(prob; percentiles=pct, mask))))
    end
    for (op, q) in questions(n, count)
        push!(lines, "answer $op $(K.json_text(q; indent=0))=" * said(() -> answer(op, prob, q)))
    end
    if count > 0
        label = K._an_output(prob, 1)["label"]
        mask = masks(n)[2][2]
        push!(lines, "quantiles=" * said(() -> join(("$(bits(q)):" * nums(y) for (q, y) in K.quantiles(prob, label)), ";")))
        push!(lines, "quantiles again=" * said(() -> join(("$(bits(q)):" * nums(y) for (q, y) in K.quantiles(prob, label; qs=(0.9, 0.1, 0.9), mask)), ";")))
        push!(lines, "mean=" * said(() -> nums(K.realisations_mean(prob, label; mask))))
        push!(lines, "median spread=" * said(() -> join((nums(v) for v in values(K.median_spread(prob, label; mask))), ";")))
        last_ = K._an_output(prob, count)["label"]
        push!(lines, "median spread last=" * said(() -> join((nums(v) for v in values(K.median_spread(prob, last_; z=1.0))), ";")))
    end
    return join(lines, "\n")
end

function replay_case(c, model)
    project = K.Project(model)
    o = options_of(c["options"])
    kw = (seed=o.kw.seed, iterations=o.iterations, latin=o.kw.latin, varied=o.kw.varied, tornado=o.kw.tornado, gsa=o.kw.gsa)
    local r
    refused = said(() -> (r = K.run_realisation(project, c["number"]; kw...); ""))
    isempty(refused) || return refused
    res = r.results
    counts = join(("$key=$(res.stats[key])" for key in ("nsteps", "nfailed", "nfevals", "events", "jumps", "restarts") if haskey(res.stats, key)), " ")
    values_ = join(("$(v.name)=$(bits(v.value)):$(v.held)" for v in r.values), "|")
    return "number=$(r.number) iterations=$(r.iterations) values=$values_\npoints=$(length(res.t)) $counts\n" * K.to_csv(res)
end

"""One realisation's series taken out of its run by descriptors made by hand: a sum of algebraic slots, a sum of
states, a parameter, a derived series -- on the grid, and from a run reported at other times."""
function take_cases()
    out = Any[]
    for (name, on_grid) in (("every kind", true), ("derived", true), ("events", true), ("history", true), ("far field", false),
                            ("post-processing with a spread", false))
        m = Dict(models)[name]
        p = K.Project(m)
        sys = K.build_system(p)
        outs = K.outputs_of(sys, p)
        xs = [x["offset"] for x in outs if x["source"] == "X"]
        ys = [x["offset"] for x in outs if x["source"] == "y" && !haskey(x, "offsets")]
        ps = [x["offset"] for x in outs if x["source"] == "P"]
        kept_ = K.JDict[]
        isempty(xs) || append!(kept_, [J("label" => "X sum", "source" => "X", "offsets" => Any[xs[end], xs[1], xs[min(2, end)]]),
                                       J("label" => "one X", "source" => "X", "offset" => xs[1])])
        isempty(ys) || append!(kept_, [J("label" => "y sum", "source" => "y", "offsets" => Any[ys[end], ys[1]]),
                                       J("label" => "one y", "source" => "y", "offset" => ys[1])])
        isempty(ps) || push!(kept_, J("label" => "P", "source" => "P", "offset" => ps[1]))
        append!(kept_, [x for x in outs if x["source"] == "D" || haskey(x, "offsets")])
        push!(out, J("name" => name, "on_grid" => on_grid, "kept" => kept_))
    end
    return out
end

function take_case(c, model)
    p = K.Project(model)
    sys = K.build_system(p)
    res = K.run_project(p; system=sys, on_grid=c["on_grid"])
    grid = K.time_grid(p)
    kept_ = K.JDict[x for x in c["kept"]]
    values_ = [Matrix{Float64}(undef, length(grid), 1) for _ in kept_]
    K._pb_take!(values_, res, kept_, K._PBTake(kept_), 1, grid, K._pb_take_buffer(kept_, grid))
    return "rows=$(length(res.t)) grid=$(length(grid))\n" * join((nums(v[:, 1]) for v in values_), "\n")
end

models_json = K.JDict(name => m for (name, m) in models)
takes = take_cases()
back = K.parse_json(K.json_text(K.JDict("models" => models_json, "cases" => cases, "replays" => replays, "takes" => takes); indent=0))
models_json, cases, replays, takes = back["models"], back["cases"], back["replays"], back["takes"]
model_of(c) = haskey(c, "example") ? examples_raw[c["example"]] : models_json[c["model"]]
const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
texts = String[]
function record!(c, text)
    push!(texts, "## $(c["name"]) $(K.json_text(c["options"]; indent=0))\n$text")
    c["out"] = kept(text)
end
for c in cases
    took = @elapsed text = run_case(c, model_of(c))
    took > 5 && println(stderr, c["name"], ": ", round(took; digits=1), " s")
    record!(c, text)
end
for c in replays
    record!(c, replay_case(c, model_of(c)))
end
for c in takes
    c["options"] = K.JDict("on_grid" => c["on_grid"])
    record!(c, take_case(c, models_json[c["name"]]))
end
lists = Any[pct for (_, pct) in PERCENTILES]
percentiles = Any[nums(K.percentiles_for(l)) for l in lists]
isempty(DUMPS) || write(joinpath(DUMPS, "probabilistic.julia.txt"), join(texts, "\n\n"))
path = joinpath(@__DIR__, "..", "tests", "fixtures", "probabilistic.json")
write(path, K.json_text(K.JDict("models" => models_json, "cases" => cases, "replays" => replays, "takes" => takes,
                                "percentiles" => percentiles); indent=0))
println(path, ": ", length(cases), " runs (", count(c -> startswith(c["out"], "=error"), cases), " refused), ", length(replays),
        " replays, ", length(takes), " taken by hand")
