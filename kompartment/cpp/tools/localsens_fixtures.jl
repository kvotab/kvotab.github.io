# Writes tests/fixtures/localsens.json: local sensitivities (dy/dp) by the Julia
# package with parity on, for the C++ engine's tests to compare with
# (tests/test_localsens.cpp, and tests/test_service.cpp for the service's answers).
#
#     julia --project=. ../cpp/tools/localsens_fixtures.jl        (from ../julia)
#
# Every model of tests/fixtures/builder.json that is built (tools/builder_fixtures.jl
# first) with its first three parameter slots, df/dp differentiated and differenced;
# the cases the Julia package's own tests take from the Python package
# (julia/tools/analysis_fixtures.py: every bundled example, the far-field example on
# two cells of each kind with its path's own settings as parameters); and models made
# up to reach each branch -- linear and nonlinear, parameters read by the derivative
# and by the initial state only, invariant algebra and the clock's interpolation,
# indexed parameters, decay chains, switch times and the corners a parameter places,
# events (timed, expected, set off by triggers), the zero floor holding a state, the
# analytic Jacobian declining mid-run, blocks that remember, availabilities, explicit
# terms and sources, the mass-balance audit, the differenced Jacobian, every refusal of
# `uncarried` and of the problem, a differenced solve that fails and its rewording, a
# run stopped by its progress.
#
# For each case: the problem -- the parameters chosen, the slots, the steps, the initial
# state with dy0/dp, the tolerances and the weight floor, the big Jacobian's pattern and
# colouring, the right-hand side and the big Jacobian's values at three points, the
# block iteration matrix formed and solved with and without a state held -- then the run:
# its progress, the times, every series of y and dy/dp, the counts (without "ms"), the
# states as the page names them and every elasticity; or the refusal in its words. For
# each model: its parameter slots and their labels, the states as the page names them,
# whether df/dp is generated and why not, what `uncarried` says of every slot and of all
# of them, and df/dp itself along every parameter slot at three points. Besides: the
# solver's words taken out of a message, the rewording of a differenced failure,
# elasticities and slot labels on odd inputs, and the service's answers to
# `local-sensitivity` jobs. Every number as its bits; a case's text kept as an FNV-1a
# hash past 300 bytes. With KOMPARTMENT_FIXTURE_DUMPS set every text is written there
# (`localsens.julia.txt`).

using Kompartment
const K = Kompartment
K.set_parity!(true)

bits(x::Float64) = isnan(x) ? "nan" : string(reinterpret(UInt64, x); base=16, pad=16)
bits(x::Integer) = bits(Float64(x))
function fnv(text::AbstractString)
    h = 0xcbf29ce484222325
    for b in codeunits(String(text))
        h = (h ⊻ b) * 0x100000001b3
    end
    return string(h; base=16, pad=16)
end
kept(text::String) = ncodeunits(text) <= 300 ? "=" * text : "#" * fnv(text)
nums(v) = join((bits(Float64(x)) for x in v), ",")
ints(v) = join(v, ",")

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

"""What a call gives, or the error it raises as the service names it: its type, its message, and a solver's kind,
hint and block."""
function said(f)
    try
        return f()
    catch e
        e isa InterruptException && rethrow()
        info = K._service_error("", e)
        s = "error:" * string(info["name"]) * ":" * string(info["message"])
        if e isa K.SolverError
            s *= "|kind=" * e.kind * "|hint=" * string(something(e.hint, "")) * "|block=" * string(something(e.block_name, ""))
        end
        return s
    end
end

J(pairs...) = K.JDict(String(k) => v for (k, v) in pairs)
P(text) = K.parse_json(text)

const ROOT = joinpath(@__DIR__, "..", "..")
examples_dir = joinpath(ROOT, "examples")
examples = sort!([splitext(f)[1] for f in readdir(examples_dir) if endswith(f, ".json")])
examples_raw = Dict(ex => P(read(joinpath(examples_dir, ex * ".json"), String)) for ex in examples)

# --- the models ------------------------------------------------------------------------------------------

const SIM = """{"start_time": 0, "end_time": 10, "output_points": 11, "spacing": "linear", "solver": "ndf", "rtol": 1e-6,
                "abstol": 1e-9, "time_unit": "year"}"""
sim(extra) = replace(SIM, "\"time_unit\"" => extra * ", \"time_unit\"")

models = Any[]
model(name, text) = push!(models, (name, P(text)))

model("linear", """{"name": "linear", "simulation": $SIM,
 "parameters": [{"name": "a0", "value": 5}, {"name": "k", "value": 0.3}, {"name": "k2", "value": 0.1}, {"name": "c", "value": 7},
                {"name": "neg", "value": -2}, {"name": "zero", "value": 0}],
 "compartments": [{"name": "A", "initial": "a0"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k"}, {"name": "Bout", "from": "B", "to": null, "rate": "k2 + 0.01 * neg + zero"}],
 "expressions": [{"name": "Unused", "equation": "c * 2"}]}""")

model("linear, tiny budget", """{"name": "tiny", "simulation": $(sim("\"max_steps\": 10")),
 "parameters": [{"name": "a0", "value": 5}, {"name": "k", "value": 0.3}, {"name": "k2", "value": 0.1}],
 "compartments": [{"name": "A", "initial": "a0"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k"}, {"name": "Bout", "from": "B", "to": null, "rate": "k2"}]}""")

model("nonlinear", """{"name": "nonlinear", "simulation": $SIM,
 "parameters": [{"name": "vmax", "value": 2}, {"name": "km", "value": 0.5}, {"name": "kq", "value": 0.05}, {"name": "A0", "value": 3}],
 "compartments": [{"name": "A", "initial": "A0"}, {"name": "B", "initial": "0.1"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "vmax / (km + A)"}, {"name": "Bout", "from": "B", "to": null, "rate": "kq * B"}]}""")

model("nonlinear, differenced Jacobian", """{"name": "nonlinear numeric", "simulation": $(sim("\"jacobian\": \"numeric\"")),
 "parameters": [{"name": "vmax", "value": 2}, {"name": "km", "value": 0.5}, {"name": "kq", "value": 0.05}, {"name": "A0", "value": 3}],
 "compartments": [{"name": "A", "initial": "A0"}, {"name": "B", "initial": "0.1"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "vmax / (km + A)"}, {"name": "Bout", "from": "B", "to": null, "rate": "kq * B"}]}""")

const ALGEBRA = """
 "parameters": [{"name": "k", "value": 0.1}, {"name": "c", "value": 0.05}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}, {"name": "C", "initial": "0"}, {"name": "D", "initial": "0"}],
 "expressions": [{"name": "E1", "equation": "k * 2"}, {"name": "E2", "equation": "E1 + c"}, {"name": "F", "equation": "k * (1 + 0.1 * time)"},
                 {"name": "G", "equation": "k * A"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "E2"}, {"name": "BC", "from": "B", "to": "C", "rate": "F"},
               {"name": "CD", "from": "C", "to": "D", "rate": "G"}]"""
model("invariant algebra", """{"name": "algebra", "simulation": $SIM, $ALGEBRA}""")
model("invariant algebra, the clock interpolated", """{"name": "algebra interpolated", "simulation": $(sim("\"min_change_time\": 0.7")), $ALGEBRA}""")

model("indexed", """{"name": "indexed", "nuclides": ["Cs-137", "Sr-90"], "simulation": $SIM,
 "index_lists": [{"name": "Zone", "indices": ["a", "b"]}],
 "parameters": [{"name": "Kd", "value": 1, "index_lists": ["Radionuclides", "Zone"],
                 "entries": [{"index": {"Zone": "b"}, "value": 2}, {"index": {"Radionuclides": "Sr-90", "Zone": "a"}, "value": 3}]},
                {"name": "k_leach", "value": 0.1, "index_lists": []}],
 "compartments": [{"name": "Soil", "initial": "1", "index_lists": ["Radionuclides", "Zone"]},
                  {"name": "Water", "initial": "0", "index_lists": ["Radionuclides", "Zone"]}],
 "transfers": [{"name": "Leach", "from": "Soil", "to": "Water", "rate": "k_leach / Kd", "index_lists": ["Radionuclides", "Zone"]}]}""")

model("decay chain", """{"name": "chain", "nuclides": ["U-238", "U-234", "Th-230"], "simulation": $SIM, "decay_unit": "mol",
 "half_lives": {"U-238": 5, "U-234": 3, "Th-230": 8}, "chains": [["U-238", "U-234", 1], ["U-234", "Th-230", 1]],
 "parameters": [{"name": "s0", "value": 2, "index_lists": []}, {"name": "k", "value": 0.2, "index_lists": []}],
 "compartments": [{"name": "Rock", "initial": "0", "index_lists": ["Radionuclides"], "entries": [{"index": {"Radionuclides": "U-238"}, "initial": "s0"}]},
                  {"name": "Water", "initial": "0", "index_lists": ["Radionuclides"]}],
 "transfers": [{"name": "Leach", "from": "Rock", "to": "Water", "rate": "k", "index_lists": ["Radionuclides"]}]}""")

model("switch times", """{"name": "switches", "simulation": $(sim("\"switch_times\": [3, \"t_sw\", \"Tx\"]")),
 "parameters": [{"name": "t_sw", "value": 6}, {"name": "k", "value": 0.2}, {"name": "u", "value": 1}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "expressions": [{"name": "R", "equation": "if(time < t_sw, k, 2 * k)"}, {"name": "Tx", "equation": "u * 8"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "R"}]}""")

model("a scenario's corner", """{"name": "scenario corner", "simulation": $(sim("\"switch_times\": [\"T_sw\"]")),
 "index_lists": [{"name": "Climate", "for_scenarios": true, "indices": ["warm", "cold"]}], "scenario": "cold",
 "parameters": [{"name": "T_sw", "value": 6, "index_lists": ["Climate"], "entries": [{"index": "cold", "value": 4}]}, {"name": "k", "value": 0.2}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "expressions": [{"name": "R", "equation": "if(time < T_sw, k, 2 * k)"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "R"}]}""")

const EVENT_BASE = """
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k"}]"""
model("an event inside the run", """{"name": "event inside", "simulation": $SIM,
 "parameters": [{"name": "t_ev", "value": 5}, {"name": "k", "value": 0.05}], $EVENT_BASE,
 "events": [{"name": "Spill", "timing": "at", "at": "t_ev", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.5"}]}]}""")
model("an event past the run", """{"name": "event past", "simulation": $SIM,
 "parameters": [{"name": "t_ev", "value": 20}, {"name": "k", "value": 0.05}], $EVENT_BASE,
 "events": [{"name": "Spill", "timing": "at", "at": "t_ev", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.5"}]}]}""")
model("an expected event", """{"name": "expected", "simulation": $SIM,
 "parameters": [{"name": "lam", "value": 0.1}, {"name": "share", "value": 0.3}, {"name": "k", "value": 0.05}], $EVENT_BASE,
 "events": [{"name": "Leak", "timing": "poisson", "rate": "lam", "from": "2", "until": "8", "sampled": false,
             "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "share"}]}]}""")
model("an event a trigger sets off", """{"name": "triggered", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.2}], $EVENT_BASE,
 "triggers": [{"name": "Tr", "first": "A", "second": "0.5", "direction": "falling"}],
 "events": [{"name": "Ev", "timing": "trigger", "trigger": "Tr", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.5"}]}]}""")

model("the zero floor", """{"name": "floor", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.2}, {"name": "k2", "value": 0.15}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}, {"name": "C", "initial": "1"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k", "multiply_by_donor": false},
               {"name": "CB", "from": "C", "to": "B", "rate": "k2", "multiply_by_donor": false}]}""")

model("the Jacobian declines", """{"name": "declines", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.5}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k * sqrt(A)", "multiply_by_donor": false}]}""")

const REMEMBER_BASE = """
 "parameters": [{"name": "k", "value": 0.2}, {"name": "k2", "value": 0.5}, {"name": "lag", "value": 2}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}, {"name": "C", "initial": "0"}],
 "triggers": [{"name": "Tr", "first": "A", "second": "0.5", "direction": "falling"}]"""
remember(name, rates, extra) = model(name, """{"name": "$name", "simulation": $SIM, $REMEMBER_BASE,
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k"}, {"name": "BC", "from": "B", "to": "C", "rate": "$rates", "multiply_by_donor": false}],
 $extra}""")
remember("a running mean the rates read", "Avg * k2", """ "running_means": [{"name": "Avg", "target": "A"}]""")
remember("a running mean switched, read", "Avg * k2", """ "running_means": [{"name": "Avg", "target": "A", "reset_trigger": "Tr"}]""")
remember("a running mean switched, unread", "k2 * B", """ "running_means": [{"name": "Avg", "target": "A", "reset_trigger": "Tr"}],
 "expressions": [{"name": "Report", "equation": "Avg * 2"}]""")
remember("a peak the rates read", "Peak * k2", """ "min_maxes": [{"name": "Peak", "target": "B", "operation": "max"}]""")
remember("a peak unread", "k2 * B", """ "min_maxes": [{"name": "Peak", "target": "B", "operation": "max", "reset_trigger": "Tr"}],
 "expressions": [{"name": "Report", "equation": "Peak * 2"}]""")
remember("a delay the rates read", "Late * k2", """ "delays": [{"name": "Late", "target": "A", "delay": "lag"}]""")
remember("a delay by a parameter, unread", "k2 * B", """ "delays": [{"name": "Late", "target": "A", "delay": "lag"}],
 "expressions": [{"name": "Report", "equation": "Late * 2"}]""")
remember("a snapshot the rates read", "Snap * k2", """ "snapshots": [{"name": "Snap", "target": "A", "trigger": "Tr", "initial": "k"}]""")

model("an availability", """{"name": "availability", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.2}, {"name": "lim", "value": 0.4}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k", "availability": {"scheme": "limit", "limit": "lim * 2"}}]}""")

model("explicit terms and a source", """{"name": "terms", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.2}, {"name": "s", "value": 0.1}, {"name": "src", "value": 0.3}],
 "compartments": [{"name": "A", "initial": "1", "dydt": "-k * A + s"}, {"name": "B", "initial": "0"}],
 "inflows": [{"name": "In", "to": "B", "rate": "src * 2"}]}""")

model("the audit", """{"name": "audit", "nuclides": ["Cs-137"], "simulation": $(sim("\"mass_balance\": true")),
 "parameters": [{"name": "k", "value": 0.2}, {"name": "k2", "value": 0.1}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k"}, {"name": "Bout", "from": "B", "to": null, "rate": "k2"}]}""")

model("df/dp not a number at the start", """{"name": "infinite", "simulation": $SIM,
 "parameters": [{"name": "k0", "value": 0}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "sqrt(k0)"}]}""")

model("a function with no rule of a parameter", """{"name": "no rule", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.01}, {"name": "n", "value": 3}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k * factorial(n)"}]}""")

model("a function with no rule of the state", """{"name": "no Jacobian", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.01}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k * factorial(A)"}]}""")

model("waste packages failing over time", """{"name": "packages", "nuclides": ["Cs-137"], "simulation": $SIM,
 "parameters": [{"name": "deg", "value": 0.01, "index_lists": []}, {"name": "k", "value": 0.1, "index_lists": []}],
 "waste_packages": [{"name": "W", "inventory": "1e3", "irf": "0.1", "degradation_rate": "deg", "failure": "weibull", "fail_start": "0",
                     "fail_scale": "20", "fail_shape": "2", "packages": 10}],
 "compartments": [{"name": "A", "initial": "0"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "Rel", "from": "W", "to": "A", "rate": "W", "multiply_by_donor": false}, {"name": "AB", "from": "A", "to": "B", "rate": "k"}]}""")

model("a lookup point drawn", """{"name": "drawn point", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.1}],
 "lookups": [{"name": "Q", "points": [[0, 1, {"kind": "unif", "params": {"min": 0.5, "max": 1.5}}], [10, 2]], "interpolation": "linear"}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k * Q"}]}""")

model("thirteen", """{"name": "thirteen", "simulation": $SIM,
 "index_lists": [{"name": "Box", "indices": ["b1", "b2", "b3", "b4", "b5", "b6", "b7", "b8", "b9", "b10", "b11", "b12", "b13"]}],
 "parameters": [{"name": "K", "value": 0.1, "index_lists": ["Box"]}],
 "compartments": [{"name": "A", "initial": "1", "index_lists": ["Box"]}],
 "transfers": [{"name": "Out", "from": "A", "to": null, "rate": "K", "index_lists": ["Box"]}]}""")

model("values not written", """{"name": "blank", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.2}, {"name": "b", "value": ""}, {"name": "nn", "value": null}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k + b + nn"}]}""")

# Growth at 4 and 1/2 a year: I - a·J is singular at a = 1/4 and 1/2.
model("growth", """{"name": "growth", "simulation": $(replace(SIM, "\"end_time\": 10" => "\"end_time\": 2")),
 "parameters": [{"name": "r", "value": 4}, {"name": "r2", "value": 0.5}, {"name": "k", "value": 0.1}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}, {"name": "C", "initial": "1"}],
 "inflows": [{"name": "GA", "to": "A", "rate": "r * A"}, {"name": "GC", "to": "C", "rate": "r2 * C"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k", "multiply_by_donor": false}]}""")

model("tolerances of their own", """{"name": "own abstol", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.2}],
 "compartments": [{"name": "A", "initial": "1", "abstol": 1e-12}, {"name": "B", "initial": "0", "abstol": "1e-7"}, {"name": "C", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k"}, {"name": "BC", "from": "B", "to": "C", "rate": "k * 0.5"}]}""")

model("the run's ends and a table", """{"name": "leaves", "simulation": $(replace(SIM, "\"start_time\": 0" => "\"start_time\": 1")),
 "parameters": [{"name": "k", "value": 0.2}, {"name": "c", "value": 0.3}],
 "lookups": [{"name": "F", "points": [[0, 0], [1, 1], [3, 2], [10, 2.5]], "argument": "x", "index_lists": []}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "expressions": [{"name": "Span", "equation": "k * (end_time() - start_time()) * 0.01 + c * F(A + k)"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "Span"}]}""")

model("an availability beside another rate", """{"name": "availability beside", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.2}, {"name": "lim", "value": 0.4}, {"name": "other", "value": 3}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}, {"name": "C", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k", "availability": {"scheme": "limit", "limit": "lim * 2"}},
               {"name": "BC", "from": "B", "to": "C", "rate": "other * 0.01"}]}""")

model("nothing available", """{"name": "none available", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.2}, {"name": "lim", "value": 0}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k", "availability": {"scheme": "limit", "limit": "lim * 2"}}]}""")

const BY_NUCLIDE = """ "nuclides": ["Cs-137", "Sr-90"], "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.2, "index_lists": []}, {"name": "k2", "value": 0.5, "index_lists": []}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}, {"name": "C", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k"}, {"name": "BC", "from": "B", "to": "C", "rate": "Avg * k2", "multiply_by_donor": false}]"""
model("a mean by nuclide the rates read", """{"name": "mean by nuclide", $BY_NUCLIDE,
 "running_means": [{"name": "Avg", "target": "A"}]}""")
model("a mean by nuclide switched at one", """{"name": "mean switched at one", $BY_NUCLIDE,
 "triggers": [{"name": "Tr", "first": "A", "second": "0.5", "direction": "falling"}],
 "running_means": [{"name": "Avg", "target": "A", "entries": [{"index": {"Radionuclides": "Sr-90"}, "stop_trigger": "Tr"}]}]}""")

model("no parameters", """{"name": "bare", "simulation": $SIM,
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "0.1"}]}""")

# The far-field example on two cells of each kind (julia/tools/analysis_fixtures.py): its matrix layers laid out
# `grid`; with `surface`, the path's own settings as parameters too.
function small_farfield(grid="matched", surface=nothing; steps=nothing, method=nothing)
    m = K.jcopy(examples_raw["farfield"])
    ff = m["farfields"][1]
    ff["n_f"] = 2
    ff["n_m"] = 2
    ff["grid"] = grid
    method === nothing || (ff["method"] = method)
    if surface !== nothing
        p(name, value, unit) = push!(m["parameters"], J("name" => name, "value" => value, "unit" => unit, "index_lists" => Any[]))
        p("TW", 50, "year")
        p("Pe", 2, "")
        p("Depth", 12.5, "m")
        ff["tw"], ff["pe"], ff["pen_dep"] = "TW", "Pe", "Depth"
        if surface == "f"
            p("F", 1e5, "year/m")
            ff["f"] = "F"
        else
            p("Gap", 1e-3, "m")
            ff["surface"], ff["aperture"] = "aperture", "Gap"
        end
    end
    steps === nothing || (m["simulation"]["max_steps"] = steps)
    return m
end
push!(models, ("far field, matched", small_farfield()))
push!(models, ("far field, reference", small_farfield("reference")))
push!(models, ("far field, reference, f", small_farfield("reference", "f")))
push!(models, ("far field, aperture", small_farfield("matched", "aperture")))
push!(models, ("far field, f, a budget of steps", small_farfield("matched", "f"; steps=5000)))
push!(models, ("far field, semi-analytical", small_farfield(; method="semi-analytical")))

# A model with a transport, a parameter its switch time: the builder writes the transport out into a project of its
# own, whose blocks are copies, and moving the parameter there leaves the switch times of the project asked about
# where they were -- so the corner it places is not seen, and its dy/dp is integrated (a fault of the Julia package
# the C++ engine keeps: see `uncarried` there).
builder_cases = [c for c in K.parse_json(read(joinpath(ROOT, "cpp", "tests", "fixtures", "builder.json"), String))["cases"] if haskey(c, "sections")]
let col = K.jcopy(only(c for c in builder_cases if c["name"] == "transport: column")["model"])
    col["simulation"]["switch_times"] = Any["kb_sw"]
    push!(col["parameters"], J("name" => "kb_sw", "value" => 12))
    push!(models, ("a transport, a parameter its switch time", col))
end

models_json = K.JDict(name => m for (name, m) in models)

# --- the cases ----------------------------------------------------------------------------------------------

cases = Any[]
case(name, params; o...) = push!(cases, J("name" => name, "model" => name, "parameters" => params, "options" => J(o...)))
example(ex, params; o...) = push!(cases, J("name" => "example $ex", "example" => ex, "parameters" => params, "options" => J(o...)))

case("linear", Any["k", "k2", "a0"])
case("linear", Any["k", "k2", "a0"]; differenced=true)
case("linear", Any["neg", "zero", "c"])
case("linear", Any["neg", "zero"]; differenced=true)
case("linear", Any["k", "k"])
case("linear", Any["a0"]; differenced=true)
case("linear", Any["k", "nope", "a0", 5, nothing])
case("linear", Any["k"]; most=0)
case("linear", Any["k", "k2"]; most="1")
case("linear", Any["k", "k2"]; most="abc")
case("linear", Any[])
case("linear", Any["nope"])
case("linear", "k")
case("linear", 5)
case("linear", J("k" => 1))
case("linear", nothing)
case("linear", true)
case("linear", Any["k"]; abort=true)
case("linear, tiny budget", Any["k"])
case("linear, tiny budget", Any["k"]; differenced=true)
case("linear, tiny budget", Any["k", "k2", "a0"]; differenced=true)
case("linear, tiny budget", Any["k2", "a0"]; differenced=true)
case("nonlinear", Any["vmax", "km", "kq", "A0"])
case("nonlinear", Any["vmax", "km", "kq", "A0"]; differenced=true)
case("nonlinear, differenced Jacobian", Any["vmax", "km", "kq"])
case("nonlinear, differenced Jacobian", Any["vmax", "kq"]; differenced=true)
case("invariant algebra", Any["k", "c"])
case("invariant algebra", Any["k", "c"]; differenced=true)
case("invariant algebra, the clock interpolated", Any["k", "c"])
case("invariant algebra, the clock interpolated", Any["k", "c"]; differenced=true)
case("indexed", Any["Kd[Cs-137][a]", "Kd[Sr-90][a]", "k_leach", "Kd[Sr-90][b]"])
case("indexed", Any["Kd[Cs-137][b]", "k_leach"]; differenced=true)
case("decay chain", Any["s0", "k"])
case("decay chain", Any["s0", "k"]; differenced=true)
case("switch times", Any["k"])
case("switch times", Any["k"]; differenced=true)
case("switch times", Any["k", "t_sw"])
case("switch times", Any["u"])
case("a scenario's corner", Any["k"])
case("a scenario's corner", Any["T_sw"])
case("an event inside the run", Any["k"])
case("an event past the run", Any["k", "t_ev"])
case("an expected event", Any["lam", "share", "k"])
case("an event a trigger sets off", Any["k"])
case("the zero floor", Any["k", "k2"])
case("the zero floor", Any["k"]; differenced=true)
case("the Jacobian declines", Any["k"])
case("the Jacobian declines", Any["k"]; differenced=true)
case("a running mean the rates read", Any["k", "k2"])
case("a running mean the rates read", Any["k", "k2"]; differenced=true)
case("a running mean switched, read", Any["k"])
case("a running mean switched, unread", Any["k", "k2"])
case("a peak the rates read", Any["k"])
case("a peak unread", Any["k", "k2"])
case("a delay the rates read", Any["k"])
case("a delay by a parameter, unread", Any["k", "lag"])
case("a snapshot the rates read", Any["k"])
case("an availability", Any["k", "lim"])
case("an availability", Any["k", "lim"]; differenced=true)
case("explicit terms and a source", Any["k", "s", "src"])
case("explicit terms and a source", Any["s", "src"]; differenced=true)
case("the audit", Any["k[Cs-137]", "k2[Cs-137]"])
case("the audit", Any["k[Cs-137]", "k2[Cs-137]"]; differenced=true)
case("df/dp not a number at the start", Any["k0"])
case("a function with no rule of a parameter", Any["k", "n"])
case("a function with no rule of the state", Any["k"])
case("waste packages failing over time", Any["deg", "k"])
case("a lookup point drawn", Any["k"])
case("thirteen", Any["K[b$i]" for i in 1:13])
case("thirteen", Any["K[b$i]" for i in 1:12])
case("thirteen", Any["K[b$i]" for i in 1:13]; most=13)
case("no parameters", Any["k"])
case("values not written", Any["k", "b", "nn"])
case("growth", Any["r", "r2", "k"])
case("growth", Any["r", "k"]; differenced=true)
case("tolerances of their own", Any["k"])
case("tolerances of their own", Any["k"]; differenced=true)
case("the run's ends and a table", Any["k", "c"])
case("the run's ends and a table", Any["k", "c"]; differenced=true)
case("an availability beside another rate", Any["k", "lim", "other"])
case("nothing available", Any["k", "lim"])
case("nothing available", Any["k", "lim"]; differenced=true)
case("a mean by nuclide the rates read", Any["k", "k2"])
case("a mean by nuclide the rates read", Any["k", "k2"]; differenced=true)
case("a mean by nuclide switched at one", Any["k"])
case("far field, matched", Any["leach_rate[U-234]"])
case("far field, matched", Any["well_flow[U-238]"])
case("far field, matched", Any["De_matrix[U-234]"])
case("far field, matched", Any["Kd_matrix[U-234]"])
case("far field, matched", Any["leach_rate[U-234]"]; differenced=true)
case("far field, aperture", Any["TW"])
case("far field, aperture", Any["Gap"])
case("far field, reference, f", Any["Depth"])
case("far field, reference", Any["De_matrix[U-238]", "Kd_matrix[U-234]"])
case("far field, f, a budget of steps", Any["TW"])
case("far field, f, a budget of steps", Any["TW"]; differenced=true)
case("far field, semi-analytical", Any["leach_rate[U-234]"])
case("a transport, a parameter its switch time", Any["kb_sw", "k"])

# The bundled examples, as julia/tools/analysis_fixtures.py takes them, and each once more with its first
# parameter slot differenced.
for (ex, params, differenced) in (("biosphere", ["leachRate[I-129]", "geoTransit"], false), ("brusselator", ["A", "B"], false),
                                  ("brusselator", ["A", "B"], true), ("exponential-decay", ["k", "y0"], false),
                                  ("four-compartment", ["p12[Fo-42]", "p23[Fo-42]", "p13[Fo-42]"], false),
                                  ("four-compartment", ["p13[Fo-42]", "p34[Fo-42]"], true),
                                  ("harmonic-oscillator", ["period", "zeta", "x0"], false), ("lookup-driver", ["V_rego", "k_sed", "DC"], false),
                                  ("lookup-driver", ["V_rego", "k_sed"], true), ("lotka-volterra", ["alpha", "beta", "gamma"], false),
                                  ("michaelis-menten", ["S0", "E0", "kf"], false), ("michaelis-menten", ["kr", "kcat"], true),
                                  ("recorders", ["k_out[Cs-137]", "Volume[Cs-137]", "DoseCoeff[Cs-137]"], false),
                                  ("recorders", ["Volume[Cs-137]", "Limit"], true), ("scenarios", ["Runoff", "LakeVolume", "Flush"], false),
                                  ("sir-epidemic", ["N", "I0", "beta"], false), ("van-der-pol-stiff", ["mu"], false), ("van-der-pol", ["mu"], true),
                                  ("bouncing-ball", ["g", "v0"], false), ("decay-chain", String[], false), ("post-processing", ["DC[I-129]"], false),
                                  ("waste-packages", ["matrix_rate"], false), ("robertson", ["k2", "k3"], true))
    example(ex, Any[params...]; differenced)
end

# Every model the builder's fixtures build (kept once, in "builder", and named by its place there), with its first
# three parameter slots.
builder_models = Any[]
for c in builder_cases
    model_ = haskey(c, "example") ? examples_raw[c["example"]] : c["model"]
    labels = try
        [K.slot_label(e) for e in K.parameter_slots(K.build_system(K.Project(model_)))]
    catch e
        String[]
    end
    row = haskey(c, "example") ? J("example" => c["example"]) : J("model" => model_)
    row["name"] = "builder: " * c["name"]
    push!(builder_models, row)
    for differenced in (false, true)
        push!(cases, J("name" => row["name"], "builder" => length(builder_models) - 1, "parameters" => Any[labels[1:min(3, end)]...],
                       "options" => J("differenced" => differenced)))
    end
end

# --- what each case gives ---------------------------------------------------------------------------------

"""Where the problem is looked at: its initial state at the start, two states made from it at later instants."""
function points(t0, t1, Y0, n)
    N = length(Y0)
    return [(t0, copy(Y0)),
            (t0 + 0.37 * (t1 - t0), [i <= n ? Y0[i] * (1.0 + 0.25 * ((i * 7) % 5)) + 0.5 * ((i * 3) % 4) : Y0[i] + 0.1 * ((i * 5) % 7) - 0.3
                                    for i in 1:N]),
            (t1, [abs(Y0[i]) * 0.3 + 1e-3 * i for i in 1:N])]
end

min_change(project) = (v = K.py_float(something(get(project.simulation, "min_change_time", nothing), 0)); isfinite(v) ? v : 0.0)

function problem_lines(pr, project)
    sys = pr.system
    lines = String["n=$(pr.n) m=$(pr.m) tangent=$(pr.tangent) why=$(something(pr.why.reason, "-")) rtol=$(bits(pr.rtol))",
                   "chosen=" * tdump(pr.chosen), "wanted=" * tdump(pr.wanted),
                   "steps=" * nums([K.step_for(sys.P[e["slot"]+1]) for e in pr.wanted]),
                   "y0=" * nums(pr.y0), "abstol=" * nums(pr.abstol),
                   "floor=" * ints(pr.weight_floor[1]) * "|" * nums(pr.weight_floor[2])]
    big = pr.jacobian.pattern
    push!(lines, "pattern=" * ints(big.colptr .- 1) * "|" * ints(big.rowval .- 1))
    push!(lines, "groups=" * (pr.jacobian.groups === nothing ? "none" : join((ints(g .- 1) for g in pr.jacobian.groups), "|")))
    push!(lines, "evaluate=$(pr.jacobian.evaluate !== nothing)")
    # As a run starts: the clock's anchors where the stretch starts, the histories primed.
    t0, t1 = sys.start_time, sys.end_time
    mc = min_change(project)
    K.use_clock_interpolation!(sys, mc, t0)
    pr.equations.on_segment(t0, mc)
    K.prime_recorders!(sys, t0, pr.y0)
    N = length(pr.y0)
    nnz = K.pattern_nnz(big)
    for (k, (t, Y)) in enumerate(points(t0, t1, pr.y0, pr.n))
        out = zeros(N)
        push!(lines, "dydt $k=" * said(() -> (pr.equations.dydt(out, t, Y); nums(out))))
        pr.jacobian.evaluate === nothing && continue
        vals = zeros(nnz)
        ok = false
        push!(lines, "jac $k=" * said(() -> (ok = pr.jacobian.evaluate(vals, t, Y); "$(ok ? 1 : 0):" * nums(vals))))
        (k == 1 && ok) || continue
        # The block iteration matrix, formed and solved as the NDF forms and solves it: with no state held, with the
        # first held (the states' block factorised twice), and with none again.
        push!(lines, "matrix=" * said(() -> begin
            W = pr.equations.iteration_matrix(N, big, vals, "auto", nothing, K.SOLVER_HINTS)
            held = zeros(UInt8, N)
            held[1] = 0x01
            parts = String[]
            for (h, a) in ((nothing, 1e-3 * (t1 - t0)), (held, 0.25), (nothing, 2.0))
                msg = K._mat_form!(W, a, vals, h)
                x = [0.125 * ((i * 37) % 11) - 0.6 for i in 1:N]
                msg === nothing && K._mat_solve_inplace!(W, x)
                info = K._mat_info(W)
                push!(parts, "held=$(h !== nothing) a=$(bits(a)) msg=$(something(msg, "-")) sparse=$(info["sparse"]) lu=$(info["lu"]) " *
                             "fill=$(tdump(info["fill"])) x=" * nums(x))
            end
            K._mat_release!(W)
            join(parts, "\n")
        end))
    end
    return lines
end

function run_lines(project_model, params, o)
    prog = Tuple{Float64,Float64}[]
    abort = get(o, "abort", false) === true
    local r
    err = said(() -> (r = K.run_sensitivity(K.Project(project_model), params; most=get(o, "most", nothing),
                                            differenced=get(o, "differenced", false) === true,
                                            on_progress=(f, at) -> (push!(prog, (Float64(f), Float64(at))); !abort)); ""))
    lines = String["progress=" * join(("$(bits(f)):$(bits(at))" for (f, at) in prog), ",")]
    isempty(err) || return push!(lines, err)
    stats = copy(r.stats)
    delete!(stats, "ms")
    push!(lines, "tangent=$(r.tangent) points=$(length(r.t)) stats=" * tdump(stats), "chosen=" * tdump(r.chosen),
          "series=" * tdump(r.series), "t=" * nums(r.t))
    for i in eachindex(r.y)
        push!(lines, "y $i=" * nums(r.y[i]))
    end
    for k in eachindex(r.sens), i in eachindex(r.sens[k])
        push!(lines, "s $k $i=" * nums(r.sens[k][i]))
    end
    for k in eachindex(r.sens), i in eachindex(r.sens[k])
        push!(lines, "e $k $i=" * nums(K.elasticity(r.y[i], r.sens[k][i], r.chosen[k]["value"])))
    end
    return lines
end

function case_text(model_, params, o)
    local pr
    project = nothing
    head = said(() -> (project = K.Project(model_);
                       pr = K.sensitivity_problem(project, params; most=get(o, "most", nothing),
                                                  differenced=get(o, "differenced", false) === true); ""))
    isempty(head) || return head
    lines = problem_lines(pr, project)
    push!(lines, "run")
    append!(lines, run_lines(model_, params, o))
    return join(lines, "\n")
end

"""A model's parameter slots and states as the page names them, whether df/dp is generated, what `uncarried` says,
and df/dp along every parameter slot at three points."""
function slots_text(model_)
    local sys, project
    head = said(() -> (project = K.Project(model_); sys = K.build_system(project); ""))
    isempty(head) || return head
    slots = K.parameter_slots(sys)
    lines = String["slots=" * tdump(slots), "labels=" * join((K.slot_label(e) for e in slots), "|"),
                   "series=" * tdump(K.state_series(sys))]
    t = K.param_tangent(sys)
    push!(lines, "tangent=$(t.available) reason=$(something(t.reason, "-"))")
    push!(lines, "uncarried=" * said(() -> something(K.uncarried(project, sys, slots), "-")))
    for e in slots
        push!(lines, "uncarried $(e["slot"])=" * said(() -> something(K.uncarried(project, sys, [e]), "-")))
    end
    t.available || return join(lines, "\n")
    y0 = K.initial_state(sys)
    K.prime_recorders!(sys, sys.start_time, y0)
    np = sys.nparam
    for (k, (tt, y)) in enumerate(points(sys.start_time, sys.end_time, y0, length(y0)))
        for slot in 0:np-1
            w = zeros(np)
            w[slot+1] = 1.0
            push!(lines, "pvp $k $slot=" * said(() -> nums(K.param_pvp(t.plan, tt, y, w))))
        end
        push!(lines, "pvp $k ones=" * said(() -> nums(K.param_pvp(t.plan, tt, y, [0.5 + 0.25 * (i % 3) for i in 1:np]))))
    end
    return join(lines, "\n")
end

# --- the rest ---------------------------------------------------------------------------------------------

# The solver's words, out of the messages a solve gives up with.
const ADVICE = ". If the model is not stiff, dormandPrince may do better. Or tighten the tolerances."
const HELD = " Something is holding a state where it cannot go: the floor at zero."
words_in = Any["variableOrder failed: Exceeded 5000 steps at t=3. Nothing this solver can do with the step size will finish this run" * ADVICE,
               "variableOrder failed: Step size fell below the minimum at t=1e-7" * ADVICE * HELD,
               "variableOrder failed: The tolerances cannot be met at t=2." * HELD,
               "Exceeded 10 steps at t=1" * ADVICE, "variableOrder failed: no advice here", "", HELD, "variableOrder failed: " * ADVICE,
               "variableOrder failed: x" * HELD * ADVICE, "variableOrder failed: two" * ADVICE * ADVICE, "variableOrder failed: é" * ADVICE]
words = Any[J("in" => m, "out" => K._ls_solver_words(m)) for m in words_in]

# Differenced failures reworded: problems of each kind, errors of every kind, at a time and at none.
failures = Any[]
for (mname, params, differenced) in (("linear", Any["k"], true), ("linear", Any["k", "k2"], true), ("linear", Any["neg", "zero", "a0"], true),
                                     ("df/dp not a number at the start", Any["k0"], false), ("linear", Any["k"], false),
                                     ("waste packages failing over time", Any["deg", "k"], false))
    pr = K.sensitivity_problem(K.Project(models_json[mname]), params; differenced)
    for kind in ("tolerance", "stalled", "steps", "nonfinite", "aborted", "singular"), t in (3.25, NaN, 1e-7)
        e = K.SolverError(kind, words_in[(length(failures)%length(words_in))+1], t)
        said_ = K._ls_differenced_failure(e, pr, differenced)
        push!(failures, J("model" => mname, "parameters" => params, "differenced" => differenced, "kind" => kind, "t" => bits(t),
                          "message" => e.message,
                          "out" => said_ === nothing ? "-" :
                                   "$(said_.kind)|$(said_.message)|$(bits(said_.t))|$(something(said_.hint, "-"))"))
    end
end

# Elasticities and slot labels on odd inputs.
elastic = Any[]
for p in Any[2.0, 0, "2.5", nothing, "x", true, -1.5e-3]
    y = [1.0, 0.0, -2.0, NaN, Inf, 3.0]
    s = [0.5, 1.0, 3.0, 1.0, 2.0]
    push!(elastic, J("p" => p, "out" => nums(K.elasticity(y, s, p))))
end
labels_in = Any[J("name" => "K", "index" => J("b" => "x", "10" => "p", "2" => "q")), J("name" => "K", "index" => J()),
                J("name" => "K", "index" => J("a" => nothing, "b" => "y")),
                J("name" => "K", "index" => J("01" => "y", "4294967295" => "big", "x" => "w", "4294967294" => "ok", "0" => "z")),
                J("name" => 5, "index" => J("a" => 1.5)), J("name" => 5, "index" => J()), J("index" => J("a" => "x")),
                J("name" => "K", "index" => "a list"),
                J("name" => "K", "index" => J("a" => true, "b" => J("c" => 1), "c" => Any[1, nothing, "t"]))]
labels = Any[J("in" => l, "out" => string(K.slot_label(l))) for l in labels_in]

# The service: local-sensitivity jobs as the page sends them, and what the engine says and writes.
service_dir = mktempdir()
function service_case(id, model_text, options)
    path = joinpath(service_dir, id * ".json")
    events = Any[]
    job = J("id" => id, "kind" => "local-sensitivity", "model" => model_text, "options" => options, "out" => path)
    K._service_job(job, e -> push!(events, e), () -> false)
    said_ = String[e["event"] == "stage" ? "stage:" * e["stage"] : e["event"] for e in events if e["event"] != "progress"]
    last = events[end]
    text = isfile(path) ? replace(read(path, String), r"\"ms\":[0-9]+" => "\"ms\":0") : ""
    return J("id" => id, "model" => model_text, "options" => options, "events" => said_,
             "name" => get(last, "name", nothing), "message" => get(last, "message", nothing), "hint" => get(last, "hint", nothing),
             "out" => isempty(text) ? "" : kept(text))
end
ex_text(ex) = read(joinpath(examples_dir, ex * ".json"), String)
service = Any[service_case("ls-exp", ex_text("exponential-decay"), J("parameters" => Any["k", "y0"])),
              service_case("ls-bio", ex_text("biosphere"), J("parameters" => Any["leachRate[I-129]", "geoTransit", "Kd[Cs-135]"])),
              service_case("ls-four", ex_text("four-compartment"), J("parameters" => Any["p12[Fo-42]"])),
              service_case("ls-ball", ex_text("bouncing-ball"), J("parameters" => Any["g"])),
              service_case("ls-none", ex_text("exponential-decay"), J()),
              service_case("ls-text", ex_text("exponential-decay"), J("parameters" => "k")),
              service_case("ls-robertson", ex_text("robertson"), J("parameters" => Any["k1"])),
              service_case("ls-bad", "{not json", J("parameters" => Any["k"]))]

# --- written ------------------------------------------------------------------------------------------------

back = K.parse_json(K.json_text(K.JDict("models" => models_json, "cases" => cases, "builder" => builder_models); indent=0))
models_json, cases, builder_models = back["models"], back["cases"], back["builder"]
model_of(c) = haskey(c, "example") ? examples_raw[c["example"]] : haskey(c, "builder") ? model_of(builder_models[c["builder"]+1]) :
              c["model"] isa AbstractString ? models_json[c["model"]] : c["model"]
const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
texts = String[]
function record!(c, text, head)
    push!(texts, "## $head\n$text")
    c["out"] = kept(text)
end
for c in cases
    params = c["parameters"]
    took = @elapsed text = case_text(model_of(c), params, c["options"])
    took > 5 && println(stderr, c["name"], ": ", round(took; digits=1), " s")
    record!(c, text, "$(c["name"]) $(K.json_text(params; indent=0)) $(K.json_text(c["options"]; indent=0))")
end
slots = Any[]
for (name, m) in models
    row = J("name" => name, "model" => name)
    record!(row, slots_text(models_json[name]), "slots $name")
    push!(slots, row)
end
for ex in examples
    row = J("name" => "example $ex", "example" => ex)
    record!(row, slots_text(examples_raw[ex]), "slots example $ex")
    push!(slots, row)
end
for (k, b) in enumerate(builder_models)
    haskey(b, "example") && continue
    row = J("name" => b["name"], "builder" => k - 1)
    record!(row, slots_text(b["model"]), "slots $(b["name"])")
    push!(slots, row)
end
isempty(DUMPS) || write(joinpath(DUMPS, "localsens.julia.txt"), join(texts, "\n\n"))
path = joinpath(@__DIR__, "..", "tests", "fixtures", "localsens.json")
write(path, K.json_text(K.JDict("models" => models_json, "builder" => builder_models, "cases" => cases, "slots" => slots, "words" => words,
                                "failures" => failures, "elasticity" => elastic, "labels" => labels, "service" => service); indent=0))
refused = count(c -> startswith(c["out"], "=error"), cases)
println(path, ": ", length(cases), " cases (", refused, " refused), ", length(slots), " models' slots, ", length(failures),
        " failures reworded or not, ", length(service), " service jobs")
