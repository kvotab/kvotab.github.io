# Writes tests/fixtures/split.json: models solved in their independent parts by the
# Julia package with parity on, for the C++ engine's tests to compare with
# (tests/test_split.cpp).
#
#     julia --project=. ../cpp/tools/split_fixtures.jl        (from ../julia)
#
# For every bundled example and models made up to reach each branch -- decay
# chains, a shared solubility limit holding the nuclides of one element together,
# far-field paths on cells (with I-129 beside a chain, and on two combinations of
# another list), the mass-balance audit's budgets, states of no material, a
# material no state carries, recorders that remember, a material named outright,
# and every refusal -- this writes: the partition, the names states are filed back
# by, their materials, the jobs; the plan under each of a set of options (modes,
# threads, a run side by side, build times, what earlier runs measured) and three
# sets of constants, its decisions and its words, with the jobs its threads would be
# given; the far-field paths' layers as the whole model lays them out. Then split
# runs at 2 and 4 threads -- and a few on bins fixed by hand -- each state at each
# time, every series, the counts summed and the account (its timings aside), and
# their run log with the timings fixed; a split that fails and is solved whole; the
# formulas on numbers made up for them (job_cost, pack_jobs, whole_solve_ms,
# build_fixed, the thousands, the jobs of bins, partitions of patterns, parts
# assembled and refused, models cut to one job's materials and built).
#
# Nothing here depends on how many threads Julia was started with. A case's text is
# kept as an FNV-1a hash; with KOMPARTMENT_FIXTURE_DUMPS set every text is written
# there (`split.julia.txt`).

using Kompartment
using Dates
const K = Kompartment
K.set_parity!(true)
# What auto learns from these runs is kept in this process only.
ENV["KOMPARTMENT_SPLIT_MEMORY"] = "0"

bits(x::Float64) = isnan(x) ? "nan" : string(reinterpret(UInt64, x); base=16, pad=16)
bits(x::Real) = bits(Float64(x))
function fnv(text::AbstractString)
    h = 0xcbf29ce484222325
    for b in codeunits(String(text))
        h = (h ⊻ b) * 0x100000001b3
    end
    return string(h; base=16, pad=16)
end
kept(text::String) = ncodeunits(text) <= 300 ? "=" * text : "#" * fnv(text)
short(text::String) = ncodeunits(text) <= 200 ? text : "#" * fnv(text)
nums(v) = join((bits(x) for x in v), ",")
ints(v) = v === nothing ? "null" : join((string(x) for x in v), ",")
str(v) = v === nothing ? "null" : String(v)
num(v) = v === nothing ? "null" : bits(v)

function said(f)
    try
        return f()
    catch e
        e isa ArgumentError && return "error:ArgumentError:" * e.msg
        e isa ErrorException && return "error:ErrorException:" * e.msg
        e isa K.SolverError && return "error:SolverError:" * e.message
        e isa K.BuildError && return "error:BuildError:" * e.message
        e isa K.ValidationError && return "error:ValidationError:" * e.message
        for T in (MethodError, InexactError, TypeError, BoundsError, KeyError)
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
"""A dictionary that Julia keeps in no order of its own, its keys sorted."""
sorted_dump(d) = "{" * join((k * "=" * tdump(d[k]) for k in sort!(collect(String, keys(d)))), ";") * "}"

J(pairs...) = K.JDict(String(k) => v for (k, v) in pairs)
P(text) = K.parse_json(text)

# --- the models --------------------------------------------------------------------------------------

const SIM = """{"start_time": 0, "end_time": 100, "output_points": 21, "spacing": "linear", "solver": "ndf", "rtol": 1e-8,
                "abstol": 1e-14, "time_unit": "year"}"""

"""`count` decay chains of `length` made-up nuclides through `compartments` compartments in a line (the Julia package's own)."""
function chains(count::Int, length::Int, compartments::Int; points::Int=40, rtol::Float64=1e-6)
    letters = "abcdefghijklmnopqrstuvwxyz"
    names = String[]
    half = K.JDict()
    pairs = Any[]
    for c in 0:count-1
        element = "Q" * letters[c%26+1] * (c < 26 ? "" : string(letters[c÷26+1]))
        chain = ["$element-$(100 + k)" for k in 0:length-1]
        for (k, name) in enumerate(chain)
            push!(names, name)
            half[name] = K.cpow(10.0, 1 + (((k - 1) * 7 + c * 3) % 11) * 0.5)
        end
        append!(pairs, Any[Any[chain[k], chain[k+1], 1.0] for k in 1:length-1])
    end
    return K.JDict(
        "name" => "$count chains of $length through $compartments", "nuclides" => Any[names...],
        "half_lives" => half, "chains" => pairs,
        "simulation" => K.JDict("start_time" => 0, "end_time" => 1e5, "output_points" => points, "spacing" => "log",
                                "solver" => "ndf", "rtol" => rtol, "abstol" => 1e-6, "time_unit" => "year"),
        "parameters" => Any[K.JDict("name" => "k$j", "value" => K.cpow(10.0, -1 - j * 0.7), "index_lists" => Any[])
                            for j in 0:4],
        "compartments" => Any[K.JDict("name" => "C$i", "initial" => i == 0 ? "1e6" : "0",
                                      "index_lists" => Any["Radionuclides"]) for i in 0:compartments-1],
        "transfers" => Any[K.JDict("name" => "T$i", "from" => "C$i", "to" => "C$(i + 1)", "rate" => "k$(i % 5)",
                                   "index_lists" => Any["Radionuclides"]) for i in 0:compartments-2])
end

"""Two nuclides through three compartments: two parts, one per nuclide."""
function two(; extra...)
    m = P("""{"name": "two", "nuclides": ["Cs-137", "Sr-90"], "simulation": $SIM,
              "parameters": [{"name": "k1", "value": 0.2}, {"name": "k2", "value": 0.05}],
              "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}, {"name": "C", "initial": "0"}],
              "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k1"}, {"name": "BC", "from": "B", "to": "C", "rate": "k2"}]}""")
    for (k, v) in extra
        m[String(k)] = v
    end
    return m
end

examples_dir = joinpath(@__DIR__, "..", "..", "examples")
examples = sort!([splitext(f)[1] for f in readdir(examples_dir) if endswith(f, ".json")])
examples_raw = Dict(ex => P(read(joinpath(examples_dir, ex * ".json"), String)) for ex in examples)

"""`x` without its comments, wherever they are."""
function uncommented!(x)
    if x isa AbstractDict
        delete!(x, "comment")
        foreach(uncommented!, values(x))
    elseif x isa AbstractVector
        foreach(uncommented!, x)
    end
    return x
end

"""The far-field example with I-129 beside its U-238 chain: two parts on one path's layers (the Julia package's own)."""
function farfield_two_parts(; points=60)
    model = uncommented!(K.jcopy(examples_raw["farfield"]))
    for key in ("layout", "view", "description")
        delete!(model, key)
    end
    model["nuclides"] = Any[model["nuclides"]..., "I-129"]
    model["simulation"]["spacing"] = "log"
    model["simulation"]["output_points"] = points
    delete!(model["simulation"], "output_times")
    # One of its expressions reads U-238 by name, which a part without it refuses.
    model["expressions"] = Any[]
    push!(get!(model["compartments"][1], "entries", Any[]), J("index" => J("Radionuclides" => "I-129"), "initial" => "1e12"))
    kd = first(p for p in model["parameters"] if p["name"] == "Kd_matrix")
    push!(kd["entries"], J("index" => J("Radionuclides" => "I-129"), "value" => 0))
    return model
end

"""The same on two combinations of another list -- a short path and a long one -- with fewer cells."""
function farfield_on_paths()
    model = farfield_two_parts(; points=40)
    model["index_lists"] = Any[P("""{"name":"Paths","indices":[{"name":"Short","enabled":true},{"name":"Long","enabled":true}]}""")]
    for c in model["compartments"]
        c["index_lists"] = Any["Radionuclides", "Paths"]
    end
    for t in model["transfers"]
        haskey(t, "index_lists") && (t["index_lists"] = Any["Radionuclides", "Paths"])
    end
    push!(model["parameters"], P("""{"name":"TW_path","value":50,"index_lists":["Paths"],"entries":[{"index":{"Paths":"Long"},"value":120}]}"""))
    path = model["farfields"][1]
    path["index_lists"] = Any["Radionuclides", "Paths"]
    path["tw"] = "TW_path"
    path["n_f"] = 6
    path["n_m"] = 5
    return model
end

models = Any[]
model(name, m) = push!(models, (name, m))

model("chains(3,4,3)", chains(3, 4, 3))
model("chains(5,3,4)", chains(5, 3, 4))
model("chains(6,5,4)", chains(6, 5, 4))
model("chains(12,4,6)", chains(12, 4, 6))
model("chains(12,4,45)", chains(12, 4, 45))
model("chains(16,12,15)", chains(16, 12, 15; points=60, rtol=1e-8))
model("chains(12,4,210)", chains(12, 4, 210))
model("two", two())
model("recording", two(min_maxes=Any[J("name" => "PeakB", "target" => "B", "operation" => "max"),
                                     J("name" => "LowA", "target" => "A", "operation" => "min")],
                       running_means=Any[J("name" => "MeanB", "target" => "B")]))
# A min/max per nuclide of what no state moves: each entry goes to the smallest job, whose part holds
# only its own nuclide's entry, so the split is solved whole (a fault of the package's, kept).
model("a min/max of no state, per nuclide", two(expressions=Any[J("name" => "E", "equation" => "k1 * (1 + sin(time))",
                                                                  "index_lists" => Any["Radionuclides"])],
                                                min_maxes=Any[J("name" => "PeakE", "target" => "E", "operation" => "max",
                                                                "index_lists" => Any["Radionuclides"])]))
model("across", two(index_reductions=Any[J("name" => "TotalB", "target" => "B", "operation" => "sum", "per_nuclide" => false,
                                           "index_lists" => Any[])],
                    min_maxes=Any[J("name" => "PeakTotal", "target" => "TotalB", "operation" => "max", "index_lists" => Any[])]))
model("pinned", P("""{"name": "pinned", "nuclides": ["Cs-137", "Sr-90"],
   "simulation": {"start_time": 0, "end_time": 100, "output_points": 11, "spacing": "linear", "solver": "ndf", "rtol": 1e-9,
                  "abstol": 1e-14, "time_unit": "year"},
   "parameters": [{"name": "Coef", "index_lists": ["Radionuclides"], "value": 0.01,
                   "entries": [{"index": {"Radionuclides": "Cs-137"}, "value": 0.05}]}],
   "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
   "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "Coef[Cs-137]"}]}"""))
model("farfield and I-129", farfield_two_parts())
model("farfield on two paths and I-129", farfield_on_paths())
# A solubility shared by an element's isotopes over the derived list of elements: the pattern has each
# element's leach read every nuclide the donor holds, so the model is one part.
model("a solubility shared over the elements", P("""{"name": "solubility", "nuclides": ["Cs-135", "Cs-137", "Sr-90", "I-129"],
   "simulation": {"start_time": 0, "end_time": 200, "output_points": 21, "spacing": "linear", "solver": "ndf", "rtol": 1e-8,
                  "abstol": 1e-12, "time_unit": "year"},
   "parameters": [{"name": "k", "value": 0.3}],
   "compartments": [{"name": "Waste", "initial": "1", "index_lists": ["Radionuclides"],
                     "entries": [{"index": {"Radionuclides": "Cs-137"}, "initial": "3"}, {"index": {"Radionuclides": "I-129"}, "initial": "0.5"}]},
                    {"name": "Water", "initial": "0", "index_lists": ["Radionuclides"]},
                    {"name": "Sea", "initial": "0", "index_lists": ["Radionuclides"]}],
   "transfers": [{"name": "Leach", "from": "Waste", "to": "Water", "rate": "k", "multiply_by_donor": true, "index_lists": ["Radionuclides"],
                  "availability": {"scheme": "shared_limit", "limit": "0.5", "over": "Elements"}},
                 {"name": "Flow", "from": "Water", "to": "Sea", "rate": "0.05", "index_lists": ["Radionuclides"]}]}"""))
# A solubility shared by caesium's isotopes on a list of their own: they leave together, strontium and
# iodine apart.
model("a solubility shared by caesium's isotopes", P("""{"name": "caesium", "nuclides": ["Cs-135", "Cs-137", "Sr-90", "I-129"],
   "simulation": {"start_time": 0, "end_time": 200, "output_points": 21, "spacing": "linear", "solver": "ndf", "rtol": 1e-8,
                  "abstol": 1e-12, "time_unit": "year"},
   "index_lists": [{"name": "Caesium", "sub_set_of": "Contaminants", "indices": ["Cs-135", "Cs-137"]},
                   {"name": "Others", "sub_set_of": "Contaminants", "indices": ["Sr-90", "I-129"]}],
   "parameters": [{"name": "k", "value": 0.3}],
   "compartments": [{"name": "WasteCs", "initial": "1", "index_lists": ["Caesium"], "entries": [{"index": {"Caesium": "Cs-137"}, "initial": "3"}]},
                    {"name": "WasteOther", "initial": "0.5", "index_lists": ["Others"]},
                    {"name": "Water", "initial": "0", "index_lists": ["Radionuclides"]},
                    {"name": "Sea", "initial": "0", "index_lists": ["Radionuclides"]}],
   "transfers": [{"name": "LeachCs", "from": "WasteCs", "to": "Water", "rate": "k", "multiply_by_donor": true, "index_lists": ["Caesium"],
                  "availability": {"scheme": "shared_limit", "limit": "0.5", "over": "Caesium"}},
                 {"name": "LeachOther", "from": "WasteOther", "to": "Water", "rate": "k", "multiply_by_donor": true, "index_lists": ["Others"]},
                 {"name": "Flow", "from": "Water", "to": "Sea", "rate": "0.05", "index_lists": ["Radionuclides"]}]}"""))
# The audit's budgets: a family per nuclide and one for what is not by nuclide.
budget = chains(3, 3, 3; points=21)
budget["simulation"]["mass_balance"] = true
push!(budget["compartments"], J("name" => "Clock", "initial" => "1", "index_lists" => Any[]))
push!(budget["transfers"], J("name" => "Tick", "from" => "Clock", "to" => nothing, "rate" => "0.01", "index_lists" => Any[]))
model("the audit's budgets", budget)
# A state of no material, in a part of its own: it goes with the smallest job.
model("a state of no material", two(compartments=Any[J("name" => "A", "initial" => "1"), J("name" => "B", "initial" => "0"),
                                                      J("name" => "C", "initial" => "0"),
                                                      J("name" => "Clock", "initial" => "2", "index_lists" => Any[])],
                                    transfers=Any[J("name" => "AB", "from" => "A", "to" => "B", "rate" => "k1"),
                                                  J("name" => "BC", "from" => "B", "to" => "C", "rate" => "k2"),
                                                  J("name" => "Tick", "from" => "Clock", "to" => nothing, "rate" => "0.03", "index_lists" => Any[])]))
# A material no state carries: the compartments are indexed by a sub-set of the nuclides.
model("a material no state carries", P("""{"name": "subset", "nuclides": ["Cs-137", "Sr-90", "I-129"], "simulation": $SIM,
   "index_lists": [{"name": "Some", "sub_set_of": "Contaminants", "indices": ["Cs-137", "Sr-90"]}],
   "parameters": [{"name": "k1", "value": 0.2}],
   "compartments": [{"name": "A", "initial": "1", "index_lists": ["Some"]}, {"name": "B", "initial": "0", "index_lists": ["Some"]}],
   "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k1", "index_lists": ["Some"]}]}"""))
# A part that cannot start where the whole can: the whole run it falls back on.
model("a part that fails", P("""{"name": "fails apart", "nuclides": ["Qa-100", "Qb-100"], "half_lives": {"Qa-100": 30, "Qb-100": 50},
   "simulation": $SIM,
   "parameters": [{"name": "Share", "value": 0, "index_lists": ["Radionuclides"], "entries": [{"index": {"Radionuclides": "Qa-100"}, "value": 1}]}],
   "index_reductions": [{"name": "Total", "target": "Share", "operation": "sum", "per_nuclide": false, "index_lists": []}],
   "compartments": [{"name": "A", "initial": "1 / Total", "index_lists": ["Radionuclides"]}, {"name": "B", "initial": "0", "index_lists": ["Radionuclides"]}],
   "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "0.1", "index_lists": ["Radionuclides"]}]}"""))
# The refusals.
model("refused: nothing to integrate", P("""{"name": "no states", "simulation": $SIM, "parameters": [{"name": "a", "value": 1}]}"""))
model("refused: no analytic Jacobian", two(transfers=Any[J("name" => "AB", "from" => "A", "to" => "B", "rate" => "0.1 * factorial(B)")]))
model("refused: a delay", two(delays=Any[J("name" => "Late", "target" => "B", "delay" => "10")]))
model("refused: a trigger", two(triggers=Any[J("name" => "Half", "first" => "B", "second" => "0.5", "direction" => "rising")]))
model("refused: one material in two parts", P("""{"name": "shared", "nuclides": ["Cs-137"], "simulation": $SIM,
   "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}, {"name": "C", "initial": "1"}, {"name": "D", "initial": "0"}],
   "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "0.1"}, {"name": "CD", "from": "C", "to": "D", "rate": "0.3"}]}"""))
semi = farfield_two_parts()
semi["farfields"][1]["method"] = "semi-analytical"
semi["farfields"][1]["n_f"] = 5
semi["farfields"][1]["n_m"] = 4
model("refused: a semi-analytical path", semi)
steps = two()
steps["simulation"]["spacing"] = "solver"
model("refused: the solver's own steps", steps)

# --- what each model is asked --------------------------------------------------------------------------

#: The options every model is planned under: off, on at several thread counts and one, side by
#: side, held to the grid, and every branch of auto.
const OPTIONS = Any[
    J("mode" => "off", "workers" => 4),
    J("mode" => "on", "workers" => 4),
    J("mode" => "on", "workers" => 3),
    J("mode" => "on", "workers" => 16),
    J("mode" => "on", "workers" => 2),
    J("mode" => "on", "workers" => 1),
    J("mode" => "on", "workers" => 2.7),
    J("mode" => "on", "workers" => 0),
    J("mode" => "on", "workers" => 4, "nest" => false),
    J("mode" => "on", "workers" => 4, "on_grid" => true),
    J("mode" => "auto", "workers" => 4),
    J("mode" => "auto", "workers" => 8),
    J("mode" => "auto", "workers" => 8, "on_grid" => true),
    J("mode" => "auto", "workers" => 8, "known" => J("solve_ms" => 200)),
    J("mode" => "auto", "workers" => 4, "known" => J("solve_ms" => 60000), "build_ms" => 100),
    J("mode" => "auto", "workers" => 8, "known" => J("solve_ms" => 60000), "build_ms" => 100),
    J("mode" => "auto", "workers" => 2, "known" => J("solve_ms" => 5000), "build_ms" => 2000),
    J("mode" => "auto", "workers" => 6, "known" => J("solve_ms" => 2000), "build_ms" => 1500),
    J("mode" => "auto", "workers" => 8, "known" => J("solve_ms" => 600), "build_ms" => 40),
    J("mode" => "auto", "workers" => 4, "known" => J("solve_ms" => 60000, "gain" => 1.1)),
    J("mode" => "auto", "workers" => 4, "known" => J("solve_ms" => 900, "gain" => 2.1)),
    J("mode" => "auto", "workers" => 8, "known" => J("gain" => 2.5, "bins" => 3)),
    J("mode" => "auto", "workers" => 8, "known" => J("gain" => 2.5, "bins" => 30)),
    J("mode" => "auto", "workers" => 8, "known" => J("gain" => 2.5, "bins" => 1)),
    J("mode" => "auto", "workers" => 8, "known" => J("gain" => 2.5, "bins" => 2.5)),
    J("mode" => "auto", "workers" => 4, "known" => J("solve_ms" => 4000, "build_fixed" => 1.0), "build_ms" => 3000),
    J("mode" => "auto", "workers" => 8, "known" => J("solve_ms" => 40000, "build_fixed" => 0.8), "build_ms" => 500),
    J("mode" => "auto", "workers" => 8, "known" => J("solve_ms" => 40000, "build_fixed" => 0.0), "build_ms" => 500),
    J("mode" => "auto", "workers" => 4, "known" => J("solve_ms" => "fast", "gain" => true, "build_fixed" => nothing)),
    J("mode" => "auto", "workers" => 4, "known" => J("solve_ms" => 3000), "build_ms" => -5),
    J("mode" => "auto", "workers" => 5, "known" => J("solve_ms" => 1e300), "build_ms" => 1e3),
    J("mode" => "nonsense", "workers" => 4, "known" => J("solve_ms" => 60000), "build_ms" => 10),
    J("mode" => true, "workers" => 4),
]

constants_json(c::K.SplitConstants) = J("shared_work" => c.shared_work, "auto_states" => c.auto_states, "auto_solve_ms" => c.auto_solve_ms,
                                        "auto_gain" => c.auto_gain, "auto_gain_untimed" => c.auto_gain_untimed, "start_ms" => c.start_ms,
                                        "build_fixed" => c.build_fixed, "build_contention" => c.build_contention,
                                        "untimed_bins" => c.untimed_bins)
constants_of(c) = K.SplitConstants(shared_work=c["shared_work"], auto_states=c["auto_states"], auto_solve_ms=c["auto_solve_ms"],
                                   auto_gain=c["auto_gain"], auto_gain_untimed=c["auto_gain_untimed"], start_ms=c["start_ms"],
                                   build_fixed=c["build_fixed"], build_contention=c["build_contention"], untimed_bins=c["untimed_bins"])
#: The Julia package's own, the Python package's, and a set made up to reach the rest.
const CONSTANTS = Any[constants_json(K.SPLIT_CONSTANTS), constants_json(K.SplitConstants()),
                      constants_json(K.SplitConstants(shared_work=0.2, auto_states=50, auto_solve_ms=100.0, auto_gain=1.05,
                                                      auto_gain_untimed=1.3, start_ms=5.0, build_fixed=0.4, build_contention=0.1,
                                                      untimed_bins=3))]

#: Where the C++ engine's words are its own: the Julia package tells a run on one thread to start
#: Julia with more, which this engine cannot be told (as the Julia package's tests take the Python
#: package's "one core" for its "one thread").
const CPP_WORDS = Dict("there is one thread to run on: start Julia with more (julia --threads=auto)" => "there is one thread to run on")
cpp_words(why) = get(CPP_WORDS, why, why)

jobs_text(jobs) = join(("$(join(j.materials, ","))/$(j.states)" for j in jobs), ";")
recorders_text(rs) = join(("$k/$j/$s" for (k, j, s) in rs), ";")

function plan_text(plan)
    t = "use=$(plan.use) mode=$(plan.mode) why=$(cpp_words(plan.why)) predicted=$(num(plan.predicted))"
    plan.use || return t
    binned = K.bin_jobs(plan)
    return t * " jobs=$(jobs_text(plan.jobs)) owner=$(short(ints(plan.owner))) bins=" * join((ints(b) for b in plan.bins), ";") *
           " parts=$(plan.parts) recorders=$(recorders_text(plan.recorders)) | binned jobs=$(jobs_text(binned.jobs))" *
           " owner=$(short(ints(binned.owner))) recorders=$(recorders_text(binned.recorders))"
end

function model_text(m)
    project = K.Project(K.jcopy(m))
    sys = K.build_system(project)
    lines = String[]
    part = K.partition_of(sys)
    push!(lines, "partition ok=$(part.ok) refusal=$(str(part.refusal)) count=$(part.count) largest=$(part.largest) " *
                 "of=$(short(ints(part.of))) sizes=$(short(ints(part.sizes)))")
    if sys.nstate > 0
        named = K.state_keys(sys)
        push!(lines, "keys=" * (named === nothing ? "null" : short(join(named, "|"))))
        push!(lines, "materials=" * short(join((m === nothing ? "~" : m for m in K.state_materials(sys)), "|")))
    end
    jobs = K.split_jobs(sys)
    push!(lines, jobs.why !== nothing ? "jobs why=$(jobs.why)" :
                 "jobs=$(jobs_text(jobs.jobs)) owner=$(short(ints(jobs.owner))) parts=$(jobs.parts) recorders=$(recorders_text(jobs.recorders))")
    for (i, o) in enumerate(OPTIONS), (k, c) in enumerate(CONSTANTS)
        text = said(() -> plan_text(K.plan_split(sys, project; mode=o["mode"], workers=o["workers"], nest=get(o, "nest", true),
                                                 build_ms=get(o, "build_ms", 0.0), known=get(o, "known", nothing),
                                                 on_grid=get(o, "on_grid", false), constants=constants_of(c))))
        push!(lines, "plan $i/$k $text")
    end
    # Last: laying the layers out works the whole system out at its first instant.
    layers = K.whole_layers(sys, project)
    if layers === nothing
        push!(lines, "layers=null")
    else
        for path in sort!(collect(keys(layers))), key in sort!(collect(keys(layers[path])))
            g = layers[path][key]
            push!(lines, "layers $path $(replace(key, '\0' => '|')) d=$(nums(g.d)) h=$(nums(g.h)) q=$(bits(g.q))")
        end
    end
    return join(lines, "\n")
end

# --- the runs ----------------------------------------------------------------------------------------------

const AT = DateTime(2026, 11, 18, 9, 30, 5, 123)
const BUILD = "fixture build"
const BUILD_MS = 12.35
const SOLVE_MS = 678.5

function with_split(raw, mode)
    r = K.jcopy(raw)
    get!(r, "simulation", K.JDict())["split"] = mode
    return r
end

function stats_text(stats)
    keep = Dict{String,Any}(k => v for (k, v) in stats if k != "split")
    return sorted_dump(keep)
end

"""The results a run gave: the times, every state at every time, every series as the application's table has them."""
results_text(res) = "t=$(nums(res.t))\ny=" * join((nums(row) for row in res.y), ";") * "\ncsv\n" * K.to_csv(res)

function account_text(account)
    lines = ["account keys=$(join(collect(keys(account)), ",")) used=$(account["used"]) mode=$(account["mode"]) why=$(cpp_words(account["why"])) " *
             "predicted=$(num(account["predicted"]))"]
    if account["used"]
        push!(lines, "parts=$(account["parts"]) workers=$(account["workers"]) jobs=" *
                     join(("$(join(j["materials"], ","))/$(j["states"])/$(tdump(j["nsteps"]))/$(join(collect(keys(j)), ","))" for j in account["jobs"]), ";"))
    end
    return join(lines, "\n")
end

"""A split run as `run_project` makes it, the model's split switched on, at `threads` threads."""
function run_text(m, threads)
    project = K.Project(with_split(m, "on"))
    res = K.run_project(project; threads)
    account = res.stats["split"]
    lines = [account_text(account), "stats=$(stats_text(res.stats))", results_text(res)]
    # The log, its timings fixed.
    res.timing["build_ms"] = BUILD_MS
    res.timing["solve_ms"] = SOLVE_MS
    if account["used"]
        account["wallMs"] = SOLVE_MS
        account["gain"] = 2.25
        for (k, job) in enumerate(account["jobs"])
            job["buildMs"] = 1.25 * k
            job["solveMs"] = 100.5 * k
        end
    end
    push!(lines, "log\n" * K.run_log(res; build=BUILD, at=AT))
    return join(lines, "\n")
end

"""A split run on bins fixed by hand, as `run_split` makes it."""
function binned_text(m, bins, threads)
    project = K.Project(with_split(m, "on"))
    sys = K.build_system(project)
    plan = K.plan_split(sys, project; mode="on", workers=max(2, length(bins)))
    plan.bins = [Int.(b) for b in bins]
    split = K.run_split(project, sys, plan; threads)
    res = K.Results(project, sys, split.t, split.y, split.stats, Dict("build_ms" => 0.0, "solve_ms" => 0.0, "total_ms" => 0.0))
    jobs = join(("$(join(j["materials"], ","))/$(j["states"])/$(tdump(j["nsteps"]))" for j in split.jobs), ";")
    return "jobs=$jobs\nstats=$(stats_text(split.stats))\n" * results_text(res)
end

runs = Any[]
run_case(name, threads) = push!(runs, J("name" => name, "threads" => threads))
binned_case(name, bins, threads) = push!(runs, J("name" => name, "threads" => threads, "bins" => bins))
for name in ("biosphere", "landscape", "waste-packages", "chains(6,5,4)", "recording", "pinned", "farfield and I-129",
             "farfield on two paths and I-129", "a solubility shared by caesium's isotopes", "the audit's budgets", "a state of no material",
             "a material no state carries", "a part that fails"), threads in (2, 4)
    run_case(name, threads)
end
run_case("chains(16,12,15)", 4)
run_case("a solubility shared over the elements", 2)
run_case("a min/max of no state, per nuclide", 2)
binned_case("biosphere", Any[Any[0, 3], Any[1, 2]], 2)
binned_case("biosphere", Any[Any[2], Any[0, 1, 3]], 1)
binned_case("chains(6,5,4)", Any[Any[0, 1, 2], Any[3], Any[4, 5]], 3)
binned_case("landscape", Any[Any[0, 1, 2]], 2)

# --- the formulas on numbers made up for them ----------------------------------------------------------

function formulas_text()
    lines = String[]
    cs = [constants_of(c) for c in CONSTANTS]
    for c in cs, (s, t) in ((25, 100), (0, 100), (100, 100), (7, 0), (3, 9), (2880, 28800), (1, 3))
        push!(lines, "job_cost $s $t = $(bits(K.job_cost(s, t, c)))")
    end
    for (k, (costs, w)) in enumerate((([5, 3, 3, 2, 1], 2), ([5, 3, 3, 2, 1], 3), ([1, 1, 1, 1], 3), ([10], 4), (Int[], 3),
                       ([4, 4, 4, 4, 4, 4, 4], 3), ([2.5, 1.25, 3.75, 0.5], 2), ([5, 3, 3, 2, 1], 0), ([7, 1, 1, 1, 1, 1, 1, 1], 2),
                       ([0.1 + 0.2, 0.3, 0.30000000000000004, 0.3], 2)))
        push!(lines, "pack_jobs $k = " * join((ints(b) for b in K.pack_jobs(costs, w)), ";"))
    end
    Jw(states, nsteps) = Dict{String,Any}("states" => states, "nsteps" => nsteps)
    for c in cs, (jobs, solving, n) in (([Jw(50, 1000), Jw(50, 1000)], [1000.0, 1000.0], 100),
                                        ([Jw(10, 1000), Jw(90, 800)], [900.0, 300.0], 100),
                                        ([Jw(10, 100), Jw(90, 1000)], [100.0, 1000.0], 100),
                                        ([Jw(10, nothing), Jw(90, 800)], [900.0, 300.0], 100),
                                        ([Jw(10, 0), Jw(90, 800)], [900.0, 300.0], 100),
                                        ([Jw(10, true), Jw(90, 800)], [900.0, 300.0], 100),
                                        ([Jw(3, 17), Jw(5, 23), Jw(7, 29)], [1.5, 2.25, 3.125], 15),
                                        ([Jw(2880, 1626), Jw(5760, 1702), Jw(20160, 1590)], [80.3, 161.7, 655.1], 28800))
        push!(lines, "whole_solve_ms $(length(jobs)) = $(bits(K.whole_solve_ms(jobs, solving, n, c)))")
    end
    Bj(states, ms) = Dict{String,Any}("states" => states, "buildMs" => ms)
    for (jobs, n, b, k) in (([Bj(10, 550.0), Bj(30, 650.0)], 100, 500.0, 0.0), ([Bj(10, 715.0), Bj(30, 845.0)], 100, 500.0, 0.3),
                            ([Bj(10, 550.0), Bj(30, 650.0)], 100, 0.0, 0.0), ([Bj(100, 1.0)], 100, 1.0, 0.0), ([Bj(10, 1e9)], 100, 1.0, 0.0),
                            ([Bj(10, 1.0)], 100, 100.0, 0.0), ([Bj(10, 3.0), Bj(20, 4.0), Bj(30, 5.0), Bj(40, 6.0)], 100, 9.0, 0.05),
                            ([Bj(10, 550.0)], 0, 500.0, 0.0), ([Bj(2880, 31.5), Bj(5760, 44.25), Bj(8640, 61.0)], 28800, 102.5, 0.0))
        v = K.build_fixed(jobs, n, b; contention=k)
        push!(lines, "build_fixed $(length(jobs)) $n $(bits(b)) $(bits(k)) = $(num(v))")
    end
    for x in (0, 7, 999, 1000, 10080, 1234567, -1234567, 100000, 12345678901)
        push!(lines, "with_commas $x = $(K._with_commas(x))")
    end
    plan3 = K._no_split("on", "")
    plan3.jobs = [K.SplitJob(["A"], 3), K.SplitJob(["B", "C"], 5), K.SplitJob(["D"], 2)]
    plan3.bins = [[1], [0, 2]]
    plan3.owner = [0, 0, 0, 1, 1, 1, 1, 1, 2, 2]
    plan3.recorders = [("min_max:Peak[D]", 2, 7), ("running_mean:Mean[B]", 1, 3)]
    got = K.bin_jobs(plan3)
    push!(lines, "bin_jobs = $(jobs_text(got.jobs)) owner=$(ints(got.owner)) recorders=$(recorders_text(got.recorders))")
    return join(lines, "\n")
end

"""Patterns from the application's compressed columns (counted from 0): `(n, colptr, rowval)`."""
const PATTERNS = Any[(5, [0, 2, 4, 5, 7, 9], [0, 1, 0, 1, 2, 3, 4, 3, 4]), (4, [0, 1, 2, 3, 4], [3, 1, 2, 3]),
                     (4, [0, 1, 2, 3, 4], [2, 3, 0, 1]), (1, [0, 1], [0]), (6, [0, 1, 2, 3, 4, 5, 6], [5, 4, 3, 2, 1, 0]),
                     (7, [0, 2, 3, 5, 6, 6, 8, 9], [0, 6, 1, 2, 4, 3, 5, 1, 6])]

function pattern(n, colptr, rowval)
    rows = Int[]
    cols = Int[]
    for j in 1:n, p in colptr[j]+1:colptr[j+1]
        push!(rows, rowval[p] + 1)
        push!(cols, j)
    end
    return K.Pattern(n, rows, cols)
end

function partitions_text()
    lines = String[]
    for (n, colptr, rowval) in PATTERNS
        p = K.state_partition(pattern(n, colptr, rowval))
        push!(lines, "pattern $n: count=$(p.count) of=$(ints(p.of)) sizes=$(ints(p.sizes)) largest=$(p.largest)")
    end
    p = K.state_partition(nothing)
    push!(lines, "none: count=$(p.count) largest=$(p.largest)")
    return join(lines, "\n")
end

#: Parts as a run sends them back, to be assembled: on the same times or not, every state carried or
#: not, counts of each kind, tallies at zero, the far-field paths' words.
const ASSEMBLE = P("""[
 {"name": "two parts", "keys": ["x", "y", "z"], "owner": [0, 1, 1],
  "outcomes": [{"t": [0, 1, 2], "y": [[1, 9], [2, 9], [3, 9]], "keys": ["x", "q"],
                "stats": {"nsteps": 10, "nfailed": 1, "nfevals": 30, "npds": 2, "solver": "ndf", "sparse": false, "compiled": true,
                          "negative": 0, "events": 2.5, "jumps": true, "fill": 3,
                          "layers": [{"block": "Rock", "message": "coarse"}]},
                "held": [4, 0]},
               {"t": [0, 1, 2], "y": [[5, 6], [7, 8], [9, 10]], "keys": ["z", "y"],
                "stats": {"nsteps": 7, "nfailed": 0, "nfevals": 21, "npds": 1, "restarts": 2, "breaks": 1, "solver": "ros23", "sparse": true,
                          "compiled": true, "events": 1, "nbelowtol": 3,
                          "layers": [{"block": "Rock", "message": "coarse"}, {"block": "Deep", "message": "coarse"}]},
                "held": [0, 3]}]},
 {"name": "a part not compiled, no solver said", "keys": ["x", "y"], "owner": [1, 0],
  "outcomes": [{"t": [0, 5], "y": [[1], [2]], "keys": ["y"], "stats": {"nsteps": 3, "solver": "", "compiled": false}, "held": null},
               {"t": [0, 5], "y": [[3], [4]], "keys": ["x"], "stats": {"nsteps": 4, "solver": "dp45", "compiled": true}, "held": [2]}]},
 {"name": "other times", "keys": ["x", "y"], "owner": [0, 1],
  "outcomes": [{"t": [0, 1], "y": [[1], [2]], "keys": ["x"], "stats": {}, "held": null},
               {"t": [0, 2], "y": [[1], [2]], "keys": ["y"], "stats": {}, "held": null}]},
 {"name": "fewer times", "keys": ["x", "y"], "owner": [0, 1],
  "outcomes": [{"t": [0, 1], "y": [[1], [2]], "keys": ["x"], "stats": {}, "held": null},
               {"t": [0], "y": [[1]], "keys": ["y"], "stats": {}, "held": null}]},
 {"name": "a state no part carried", "keys": ["x", "z"], "owner": [0, 1],
  "outcomes": [{"t": [0, 1], "y": [[1], [2]], "keys": ["x"], "stats": {}, "held": null},
               {"t": [0, 1], "y": [[1], [2]], "keys": ["x"], "stats": {}, "held": null}]}
]""")

function assemble_text(c)
    outcomes = [(t=Float64.(o["t"]), y=[Float64.(r) for r in o["y"]], keys=String.(o["keys"]), stats=Dict{String,Any}(o["stats"]),
                 held=o["held"] === nothing ? nothing : Int.(o["held"])) for o in c["outcomes"]]
    return said(() -> begin
        a = K.assemble_parts(String.(c["keys"]), Int.(c["owner"]), outcomes)
        "t=$(nums(a.t)) y=" * join((nums(r) for r in a.y), ";") * " stats=$(sorted_dump(a.stats))"
    end)
end

#: Models cut to one job's materials: what the cut model holds, and what it builds.
const PARTS = J("lists" => P("""{"name": "lists", "nuclides": ["Cs-137", "Sr-90", 5, "I-129"],
       "index_lists": [{"name": "Contaminants", "for_contaminants": true,
                        "indices": ["Cs-137", {"name": "Sr-90", "enabled": false, "colour": "red"}, {"name": "I-129"}, {"name": "Cl-36", "enabled": true}]},
                       {"name": "Radionuclides", "for_nuclides": true, "sub_set_of": "Contaminants", "indices": ["Cs-137", "I-129"]},
                       {"name": "Zones", "indices": ["a", "b"]}]}"""),
                "keeps" => Any[Any["Cs-137"], Any["Sr-90", "I-129"], Any[], Any["Cs-137", "Cl-36", "Nowhere"]],
                "built" => Any[Any["Sr-90"], Any["Cs-137"]],
                "rates" => Any["Coef[Cs-137] * Coef[I-129]", "Coef[Cs-137] + Nothing_here"])

function parts_text(fx)
    lines = String[]
    for keep in fx["keeps"]
        push!(lines, "part_model $(join(keep, ",")) = " * K.json_text(K.part_model(fx["lists"], String.(keep)); indent=0))
    end
    # Cut as a split run cuts it: from the model as its project writes it, every list written out.
    pinned = K.project_to_json(K.Project(K.jcopy(models_json["pinned"])))
    for keep in fx["built"]
        part = K.build_part(K.part_model(pinned, String.(keep)))
        push!(lines, "build_part $(join(keep, ",")) pinned=$(join(part.pinned, ",")) keys=$(join(K.state_keys(part.system), "|")) " *
                     "nuclides=$(K.json_text(K.project_to_json(part.project)["nuclides"]; indent=0))")
    end
    for rate in fx["rates"]
        bad = K.jcopy(models_json["pinned"])
        bad["transfers"][1]["rate"] = rate
        bad["nuclides"] = Any["Cs-137", "Sr-90", "I-129"]
        push!(lines, "build_part $rate = " *
                     said(() -> (p = K.build_part(K.part_model(K.project_to_json(K.Project(bad)), ["Sr-90"])); "pinned " * join(p.pinned, ","))))
    end
    return join(lines, "\n")
end

# --- written out -------------------------------------------------------------------------------------------

models_json = K.JDict(name => m for (name, m) in models)
back = K.parse_json(K.json_text(K.JDict("models" => models_json, "runs" => runs); indent=0))
models_json, runs = back["models"], back["runs"]
model_of(name) = haskey(models_json, name) ? models_json[name] : examples_raw[name]

const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
texts = String[]
function record!(row, head, text)
    push!(texts, "## $head\n$text")
    row["out"] = kept(text)
    return row
end

cases = Any[]
for name in [examples; [name for (name, _) in models]]
    took = @elapsed text = model_text(model_of(name))
    took > 5 && println(stderr, name, ": ", round(took; digits=1), " s")
    push!(cases, record!(J("name" => name), "model $name", text))
end
for r in runs
    took = @elapsed text = haskey(r, "bins") ? binned_text(model_of(r["name"]), r["bins"], r["threads"]) : run_text(model_of(r["name"]), r["threads"])
    took > 5 && println(stderr, r["name"], " on ", r["threads"], ": ", round(took; digits=1), " s")
    record!(r, "run $(r["name"]) on $(r["threads"])" * (haskey(r, "bins") ? " bins $(K.json_text(r["bins"]; indent=0))" : ""), text)
end
formulas = record!(J(), "formulas", formulas_text())
partitions = record!(J("patterns" => Any[J("n" => n, "colptr" => colptr, "rowval" => rowval) for (n, colptr, rowval) in PATTERNS]),
                     "partitions", partitions_text())
assembled = Any[record!(K.JDict(k => v for (k, v) in c), "assemble $(c["name"])", assemble_text(c)) for c in ASSEMBLE]
parts_fx = K.parse_json(K.json_text(PARTS; indent=0))
parts = record!(parts_fx, "parts", parts_text(parts_fx))

isempty(DUMPS) || write(joinpath(DUMPS, "split.julia.txt"), join(texts, "\n\n"))
path = joinpath(@__DIR__, "..", "tests", "fixtures", "split.json")
write(path, K.json_text(K.JDict("models" => models_json, "options" => OPTIONS, "constants" => CONSTANTS, "cases" => cases, "runs" => runs,
                                "formulas" => formulas, "partitions" => partitions, "assemble" => assembled, "parts" => parts,
                                "at" => Dates.format(AT, dateformat"yyyy-mm-ddTHH:MM:SS.sss") * "Z", "build" => BUILD,
                                "build_ms" => BUILD_MS, "solve_ms" => SOLVE_MS); indent=0))
println(path, ": ", length(cases), " models, ", length(cases) * length(OPTIONS) * length(CONSTANTS), " plans, ", length(runs), " runs")
