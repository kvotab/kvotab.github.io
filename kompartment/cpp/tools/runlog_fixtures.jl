# Writes tests/fixtures/runlog.json: the run log the Julia engine writes, with
# parity on, for the C++ engine's tests to compare with (tests/test_runlog.cpp).
#
#     julia --project=. ../cpp/tools/runlog_fixtures.jl        (from ../julia)
#
# First the number formats the log writes with (`toFixed`, `toExponential`,
# `toPrecision`), on numbers chosen to reach each rounding and on random ones.
# Then the log of every bundled example under several settings -- each solver,
# the audit on and off, the audit in every time unit, the tolerance that
# follows the solution, "cannot go negative" off, a solver asked for that the
# run does not take -- of every model tools/run_fixtures.jl runs (those of
# builder.json, named), and of models made up to reach the rest: states held at
# zero, an audit of amounts too small to resolve, a derivative infinite at the
# start (df/dy differenced), a run with no states, what the header and the
# settings say of whatever a model file holds there, and what a run's counts
# hold that this engine's runs do not make themselves (a split, a switching
# solver's methods, steps below tolerance, a solver that could not finish,
# far-field warnings). A log is kept as a hash of its text -- the date, the
# build and the timings fixed -- or a run as the message it fails with. With
# KOMPARTMENT_FIXTURE_DUMPS set the logs are written there
# (`<case>.runlog.julia.txt`); a case's name never holds a slash.

using Kompartment
using Dates
using Random
const K = Kompartment
K.set_parity!(true)

function fnv(text::String)
    h = 0xcbf29ce484222325
    for b in codeunits(text)
        h = (h ⊻ b) * 0x100000001b3
    end
    return string(h; base=16, pad=16)
end

const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
const AT = DateTime(2026, 11, 18, 9, 30, 5, 123)
const BUILD = "fixture build"
# The timings the log writes, the same in every run: each a tie or near one.
const BUILD_MS = 12.35
const SOLVE_MS = 678.5

# --- the number formats ---------------------------------------------------------------------

const FIXED = [0, 1, 2, 3, 5, 10, 20]
const EXPONENTIAL = [0, 1, 2, 3, 6, 15, 20]
const PRECISION = [1, 2, 4, 7, 15, 21]

formats(x::Float64) = join([[K.js_to_fixed(x, d) for d in FIXED]; [K.js_to_exponential(x, f) for f in EXPONENTIAL];
                            [K.js_to_precision(x, p) for p in PRECISION]], "|")

function numbers()
    xs = Float64[0.0, -0.0, NaN, Inf, -Inf, 5e-324, 2.2250738585072014e-308, 1.7976931348623157e308, 1e21, -1e21,
                 9.999999999999999e20, 1e21 - 65536, 0.5, 1.5, 2.5, -2.5, 0.25, 0.75, 0.125, 0.375, 0.0625, 1.0625, 1.005,
                 1.45, 9.995, 123456.789, 0.000123456, 1 / 3, 2 / 3, pi, exp(1), 1e-7, 5e-7, 9.5, 99.5, 999.5, 0.95, 0.995,
                 9.9995, 1e15 + 0.5, 4.35, 0.045, 1.0e-300, 12.35, 678.5, 99.95, 0.9999999999999999, 999999.5, 1e6, 1e-3,
                 0.00099999, 100 * 0.123456, 2.0^60, 2.0^-60, 123.456e10, -0.0004]
    for d in 0:3, k in 0:30
        push!(xs, (k + 0.5) / 10.0^d)
    end
    rng = MersenneTwister(20261118)
    for _ in 1:600
        push!(xs, (rand(rng) < 0.5 ? -1 : 1) * rand(rng) * 10.0^rand(rng, -30:30))
    end
    return xs
end

written(x::Float64) = isnan(x) ? "NaN" : isinf(x) ? (x > 0 ? "Infinity" : "-Infinity") : x

# --- runs -----------------------------------------------------------------------------------

"""A model with changes set over it: the simulation's key by key, the rest whole; `nothing` takes a key away."""
function changed(model, set)
    m = K.jcopy(model)
    set === nothing && return m
    for (k, v) in set
        if k == "simulation" && v isa AbstractDict
            sim = get!(m, "simulation", K.JDict())
            for (sk, sv) in v
                sv === nothing ? delete!(sim, sk) : (sim[sk] = sv)
            end
        else
            v === nothing ? delete!(m, k) : (m[k] = v)
        end
    end
    return m
end

function one(case, model)
    m = changed(model, get(case, "set", nothing))
    out = K.JDict()
    try
        p = K.Project(m)
        sys = K.build_system(p)
        solver = get(case, "solver", nothing)
        res = solver === nothing ? K.run_project(p; system=sys) : K.run_project(p; system=sys, solver=solver)
        res.timing["build_ms"] = BUILD_MS
        res.timing["solve_ms"] = SOLVE_MS
        for (k, v) in something(get(case, "inject", nothing), K.JDict())
            res.stats[k] = v
        end
        project = get(case, "project", nothing)
        text = K.run_log(res; project=project === nothing ? nothing : project, build=BUILD, at=AT)
        isempty(DUMPS) || write(joinpath(DUMPS, "$(case["name"]).runlog.julia.txt"), text)
        out["log"] = fnv(text)
        out["lines"] = count(==('\n'), text) + 1
    catch e
        e isa K.SolverError || e isa K.BuildError || e isa K.ValidationError || e isa ErrorException ||
            e isa ArgumentError || (println(stderr, "while running ", case["name"]); rethrow())
        out["error"] = e isa ErrorException ? e.msg : e.message
    end
    return out
end

examples_dir = joinpath(@__DIR__, "..", "..", "examples")
cases = Any[]
models = Dict{String,Any}()
function add!(name; example=nothing, model=nothing, kw...)
    case = K.JDict("name" => name)
    example !== nothing ? (case["example"] = example) : model !== nothing ? (case["model"] = model) : nothing
    for (k, v) in kw
        case[String(k)] = v
    end
    push!(cases, case)
end
J(pairs...) = K.JDict(String(k) => v for (k, v) in pairs)

# Every bundled example, as it stands and under several settings.
const UNITS = ["second", "minute", "hour", "day", "year"]
examples = sort!([splitext(f)[1] for f in readdir(examples_dir) if endswith(f, ".json")])
for (i, ex) in enumerate(examples)
    raw = K.parse_json(read(joinpath(examples_dir, ex * ".json"), String))
    models[ex] = raw
    sim = get(raw, "simulation", K.JDict())
    own = something(get(sim, "solver", nothing), "ndf")
    add!("$ex: as it stands"; example=ex)
    # An explicit solver on a stiff model is held to a number of steps: it fails, in words.
    for s in ("ndf", "ros23", "dp45")
        s == own && continue
        add!("$ex: on $s"; example=ex, set=J("simulation" => s == "dp45" ? J("solver" => s, "max_steps" => 20000) : J("solver" => s)))
    end
    add!("$ex: the audit $(K.js_truthy(get(sim, "mass_balance", nothing)) ? "off" : "on")"; example=ex,
         set=J("simulation" => J("mass_balance" => !K.js_truthy(get(sim, "mass_balance", nothing)))))
    # The audit in every time unit for a few; in one each, in turn, for the rest.
    for u in (i <= 3 ? UNITS : [UNITS[mod1(i, length(UNITS))]])
        add!("$ex: the audit in $u"; example=ex, set=J("simulation" => J("mass_balance" => true, "time_unit" => u)))
    end
    add!("$ex: the tolerance follows the solution"; example=ex, set=J("simulation" => J("auto_abstol" => true)))
    add!("$ex: cannot go negative off"; example=ex, set=J("simulation" => J("non_negative" => false)))
    add!("$ex: the NDF for the Rosenbrock asked for"; example=ex, set=J("simulation" => J("solver" => "ros23")), solver="ndf")
end
add!("decay-chain: no time unit written"; example="decay-chain", set=J("simulation" => J("time_unit" => nothing, "mass_balance" => true)))
add!("decay-chain: the Jacobian differenced"; example="decay-chain", set=J("simulation" => J("jacobian" => "numeric")))

# Every model the run fixtures run, by its name in builder.json.
for c in K.parse_json(read(joinpath(@__DIR__, "..", "tests", "fixtures", "builder.json"), String))["cases"]
    haskey(c, "sections") || continue
    haskey(c, "example") && continue
    models["built: $(c["name"])"] = c["model"]
    add!("built: $(c["name"])"; built=c["name"])
end

# States held at zero: tanks drained at a constant rate past empty, each for a share of the
# run of its own, under names whose order is the lower case's.
const SIMULATION = J("start_time" => 0, "end_time" => 10, "output_points" => 12, "spacing" => "linear", "solver" => "ndf",
                     "rtol" => 1e-6, "abstol" => 1e-9, "time_unit" => "year")
function drained(n, solver)
    names = [("\u00c4rta", "apa", "Zeta", "beta", "\u00d8l", "omega")[mod1(i, 6)] * string(i; pad=2) for i in 1:n]
    J("name" => "drained tanks",
      "simulation" => merge(K.jcopy(SIMULATION), J("solver" => solver)),
      "index_lists" => [J("name" => "Tanks", "indices" => [J("name" => nm) for nm in names])],
      "parameters" => [J("name" => "k", "index_lists" => ["Tanks"], "value" => 0.1,
                         "entries" => [J("index" => nm, "value" => 0.15 + 0.05 * (i % 9)) for (i, nm) in enumerate(names)])],
      "compartments" => [J("name" => "Tank", "initial" => "1", "index_lists" => ["Tanks"]),
                         J("name" => "Sink", "initial" => "0", "index_lists" => ["Tanks"])],
      "transfers" => [J("name" => "Drain", "from" => "Tank", "to" => "Sink", "rate" => "k", "multiply_by_donor" => false,
                        "index_lists" => ["Tanks"])],
      "expressions" => [], "inflows" => [])
end
for n in (1, 3, 25)
    add!("held: $n tanks"; model=drained(n, "ndf"))
end
add!("held: 1 tank on ros23"; model=drained(1, "ros23"))
# The one-step methods chatter at a floor they hold: held to a number of steps, they fail, in words.
add!("held: 3 tanks on ros23"; model=changed(drained(3, "ros23"), J("simulation" => J("max_steps" => 3000))))
add!("held: 1 tank on dp45"; model=changed(drained(1, "dp45"), J("simulation" => J("max_steps" => 3000))))
single = drained(1, "ndf")
single["index_lists"] = []
single["parameters"] = [J("name" => "k", "value" => 0.3)]
for c in single["compartments"]
    delete!(c, "index_lists")
end
delete!(single["transfers"][1], "index_lists")
add!("held: one tank, not indexed"; model=single)
add!("held: with the audit"; model=changed(drained(3, "ndf"), J("simulation" => J("mass_balance" => true))))

# The audit of amounts too small for the solver to resolve; and an exact derivative that is
# infinite at the start, so df/dy is differenced.
add!("the audit of too little"; model=J("name" => "too little", "simulation" => merge(K.jcopy(SIMULATION), J("abstol" => 1e-3, "mass_balance" => true)),
                                        "parameters" => [], "compartments" => [J("name" => "A", "initial" => "1e-6"), J("name" => "B", "initial" => "0")],
                                        "transfers" => [J("name" => "Out", "from" => "A", "to" => "B", "rate" => "0.1")],
                                        "expressions" => [], "inflows" => []))
add!("a derivative infinite at the start"; model=J("name" => "a root at zero", "simulation" => K.jcopy(SIMULATION), "parameters" => [],
                                  "compartments" => [J("name" => "A", "initial" => "0"), J("name" => "B", "initial" => "0")],
                                  "inflows" => [J("name" => "Feed", "to" => "A", "rate" => "1")],
                                  "transfers" => [J("name" => "Out", "from" => "A", "to" => "B", "rate" => "sqrt(A)", "multiply_by_donor" => false)],
                                  "expressions" => []))

# A run with nothing to integrate.
add!("no states"; model=J("name" => "only expressions", "simulation" => K.jcopy(SIMULATION),
                          "parameters" => [J("name" => "a", "value" => 2)],
                          "expressions" => [J("name" => "E", "equation" => "a*time()")],
                          "compartments" => [], "transfers" => [], "inflows" => []))

# The header and the settings: whatever a model file holds there, written as the run's
# log writes it, for a run of a small model.
const SMALL = "exponential-decay"
long = repeat("Long text ", 19) * "ab" * "\U0001F600" * "cd"
headers = [
    "a description of runs of white space" => J("name" => "spaced", "description" => "  one\t\ttwo\n\nthree \u00a0four\u2028five\ufeffsix\u0085seven  "),
    "a description longer than 200 units, cut at an astral character" => J("name" => "long", "description" => long),
    "a description of exactly 200 units" => J("name" => "exact", "description" => repeat("x", 200)),
    "a description that is not text" => J("name" => "number", "description" => 42),
    "an empty description" => J("name" => "empty", "description" => ""),
    "no name" => J("description" => "nameless"),
    "a name that is a number" => J("name" => 3.5),
    "a name with a line break" => J("name" => "two\nlines"),
    "decay in mol" => J("name" => "m", "decay_unit" => " mol\n"),
    "decay in mol, the old key" => J("name" => "m", "decayUnit" => "mol"),
    "decay in MOL" => J("name" => "m", "decay_unit" => "MOL"),
    "decay unit null, the old key mol" => J("name" => "m", "decay_unit" => nothing, "decayUnit" => "mol"),
    "decay unit a number" => J("name" => "m", "decay_unit" => 5),
]
settings = [
    "no simulation" => nothing,
    "an empty simulation" => J(),
    "a simulation that is not a dictionary" => [1, 2],
    "every setting" => J("time_unit" => "day", "start_time" => 0.5, "end_time" => 1e21, "output_points" => 250,
                         "spacing" => "linear", "solver" => "ros23", "rtol" => 1e-7, "abstol" => 1e-12,
                         "non_negative" => false, "mass_balance" => true, "auto_abstol" => true, "decay_ceiling" => 1e5),
    "settings as text" => J("time_unit" => "", "start_time" => "0", "end_time" => "1e5", "output_points" => "100",
                            "spacing" => "log", "solver" => "", "rtol" => "1e-6", "abstol" => nothing,
                            "non_negative" => "false", "mass_balance" => "yes", "auto_abstol" => 0, "decay_ceiling" => "100"),
    "a series of the model's own" => J("spacing" => "series", "output_points" => 3),
    "no output points, no spacing" => J("start_time" => -1.5, "end_time" => nothing),
    "output points null" => J("output_points" => nothing, "spacing" => "linear"),
    "a spacing that is not text" => J("spacing" => 2, "output_points" => [1, nothing, 3]),
    "decay chains stop above zero" => J("decay_ceiling" => 0),
    "decay chains stop above true" => J("decay_ceiling" => true),
    "decay chains stop above a negative" => J("decay_ceiling" => -1),
    "decay chains stop above a huge one" => J("decay_ceiling" => 1.5e300),
    "switches as numbers" => J("mass_balance" => 1, "auto_abstol" => 0.5, "non_negative" => 0),
    "settings that are lists and dictionaries" => J("solver" => ["a", "b"], "rtol" => J("x" => 1), "time_unit" => true),
]
for (what, raw) in headers
    add!("header: $what"; example=SMALL, project=raw)
end
for (what, sim) in settings
    raw = J("name" => "settings")
    sim === nothing || (raw["simulation"] = sim)
    add!("settings: $what"; example=SMALL, project=raw)
end

# What a run's counts can hold that this engine's own runs do not make.
farfield_said = [J("block" => "Path A", "message" => "its unit response for Cs-135 misses its mass balance by 2.3%"),
                 J("block" => "Path B", "message" => "the same for I-129")]
injected = [
    "a switching solver's methods" => J("steps_by" => J("Tsit5" => 12, "Rosenbrock23" => 300), "switches" => 3),
    "one method, one step" => J("steps_by" => J("Tsit5" => 1), "switches" => 1),
    "methods by the page's key" => J("stepsBy" => J("A" => 2.0), "switches" => nothing),
    "methods not a dictionary" => J("steps_by" => [1, 2]),
    "steps below tolerance" => J("nbelowtol" => 17),
    "no steps below tolerance" => J("nbelowtol" => 0),
    "a solver that could not finish" => J("tried" => "ndf"),
    "a solver asked for" => J("asked" => "ros23", "solver" => "ndf"),
    "no counts" => J("nsteps" => nothing, "nfailed" => nothing, "nfevals" => nothing),
    "events and jumps" => J("events" => 4, "restarts" => nothing, "jumps" => 2),
    "events null" => J("events" => nothing, "jumps" => nothing),
    "not integrated" => J("integrated" => false),
    "integrated said" => J("integrated" => true),
    "a split" => J("split" => J("used" => true, "parts" => 3, "workers" => 2, "mode" => "auto", "why" => "the nuclides do not meet",
                                "gain" => 1.85,
                                "jobs" => [J("materials" => ["Cs-135", "I-129"], "states" => 40, "nsteps" => 120, "buildMs" => 3.25,
                                             "solveMs" => 10.5),
                                           J("materials" => ["Se-79"], "states" => 20, "buildMs" => 0.05),
                                           J("states" => 5, "nsteps" => 7, "solveMs" => 2.5)])),
    "a split without jobs" => J("split" => J("used" => 1, "workers" => 4, "mode" => "on", "why" => "asked for", "gain" => 0)),
    "not split" => J("split" => J("used" => false, "mode" => "off", "why" => "the model is one part")),
    "a split that is not a dictionary" => J("split" => "yes"),
    "far-field warnings" => J("farfield" => farfield_said, "layers" => farfield_said[1:1]),
    "one far-field warning" => J("farfield" => farfield_said[2:2], "layers" => farfield_said),
    "far-field warnings empty" => J("farfield" => [], "layers" => nothing),
    "held counts" => J("held" => [3, 0], "nsteps" => 10),
    "held counts, no steps" => J("held" => [3, 0], "nsteps" => 0),
    "the sparse LU" => J("sparse" => true),
]
for (what, stats) in injected
    add!("counts: $what"; example=SMALL, inject=stats)
end
add!("counts: far-field warnings beside the audit"; example="farfield", set=J("simulation" => J("mass_balance" => true)),
     inject=J("farfield" => farfield_said))

rows = Any[]
for x in numbers()
    push!(rows, Any[written(x), fnv(formats(x))])
end
isempty(DUMPS) || write(joinpath(DUMPS, "numbers.runlog.julia.txt"), join((formats(x) for x in numbers()), "\n"))
out = Any[]
for case in cases
    model = haskey(case, "example") ? models[case["example"]] : haskey(case, "built") ? models[case["name"]] : case["model"]
    took = @elapsed r = one(case, model)
    took > 5 && println(stderr, case["name"], ": ", round(took; digits=1), " s")
    merge!(case, r)
    push!(out, case)
end
path = joinpath(@__DIR__, "..", "tests", "fixtures", "runlog.json")
write(path, K.json_text(K.JDict("at" => K._rl_iso(AT), "build" => BUILD, "build_ms" => BUILD_MS, "solve_ms" => SOLVE_MS,
                                "numbers" => rows, "cases" => out); indent=0))
println(path, ": ", length(rows), " numbers, ", length(out), " logs, ", count(c -> haskey(c, "error"), out), " runs that fail")
