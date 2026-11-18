# Writes tests/fixtures/project.json: what the Julia engine's Project makes of
# models, for the C++ engine's tests to compare with (tests/test_project.cpp).
#
#     julia --project=../julia tools/project_fixtures.jl
#
# Every bundled example, and models made from them to reach the checks: the
# project as text (its settings, lists, decay pairs, every block as
# normalised, what is switched off, the output times to the bit) by a hash of
# that text, or the message a model is refused with. With
# KOMPARTMENT_FIXTURE_DUMPS set to a directory, each project's text is written
# there too (`<name>.julia.json`), to be compared with the C++ engine's
# (`<name>.cpp.json`, which its test writes with the same variable set).

using Kompartment
const K = Kompartment

bits(x::Float64) = string(reinterpret(UInt64, x); base=16, pad=16)

function fnv(text::String)
    h = 0xcbf29ce484222325
    for b in codeunits(text)
        h = (h ⊻ b) * 0x100000001b3
    end
    return string(h; base=16, pad=16)
end

function dump(p::K.Project)
    blocks = K.JDict()
    for c in K.BLOCK_COLLECTIONS
        blocks[c] = Any[b for b in p.blocks[c]]
    end
    off = K.JDict()
    for c in K.BLOCK_COLLECTIONS
        haskey(p.switched_off, c) && (off[c] = Any[b["qname"] for b in p.switched_off[c]])
    end
    dm = K.decay_model(p)
    return K.JDict(
        "name" => p.name, "description" => p.description, "simulation" => p.simulation,
        "output_mode" => p.output_mode, "decay_unit" => p.decay_unit,
        "index_lists" => Any[l for l in p.index_lists], "chains" => p.chains,
        "material_list" => p.material_list_name, "nuclide_list" => p.nuclide_list_name,
        "scenario" => p.scenario, "scenarios" => Any[p.scenarios...],
        "blocks" => blocks, "switched_off" => off, "disabled" => Any[sort!(collect(p.disabled))...],
        "implicitly_disabled" => K.JDict(k => p.implicitly_disabled[k] for k in sort!(collect(keys(p.implicitly_disabled)))),
        "systems" => Any[p.systems...], "transports" => Any[p.transports...],
        "derived_lists" => Any[sort!(collect(p.derived_lists))...],
        "decay" => K.JDict("names" => Any[dm.names...], "lambdas" => Any[bits(x) for x in dm.lambdas],
                           "parents" => Any[Any[Any[q.index, bits(q.lambda), bits(q.ratio)] for q in ps] for ps in dm.parents]),
        "grid" => Any[bits(t) for t in K.time_grid(p)],
    )
end

const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
cases = Any[]
function record(name, model)
    row = K.JDict("name" => name, "model" => model)
    try
        p = K.Project(model)
        text = K.json_text(dump(p); indent=0)
        row["hash"] = fnv(text)
        isempty(DUMPS) || write(joinpath(DUMPS, "$name.julia.json"), K.json_text(dump(p); indent=1))
    catch e
        (e isa K.ValidationError) || (println(stderr, name); rethrow())
        row["error"] = e.message
    end
    push!(cases, row)
end

examples = joinpath(@__DIR__, "..", "..", "examples")
models = K.JDict()
for f in sort(readdir(examples))
    endswith(f, ".json") || continue
    models[f[1:end-5]] = K.parse_json(read(joinpath(examples, f), String))
end
for (name, m) in models
    row = K.JDict("name" => name, "example" => name)
    p = K.Project(m)
    row["hash"] = fnv(K.json_text(dump(p); indent=0))
    isempty(DUMPS) || write(joinpath(DUMPS, "$name.julia.json"), K.json_text(dump(p); indent=1))
    push!(cases, row)
end

base() = K.jcopy(models["biosphere"])
two() = K.parse_json("""{"name":"two","nuclides":["Cs-137","Sr-90"],"simulation":{"end_time":100},
  "parameters":[{"name":"k1","value":0.2},{"name":"k2","value":0.05}],
  "compartments":[{"name":"A","initial":"1"},{"name":"B","initial":"0"},{"name":"C","initial":"0"}],
  "transfers":[{"name":"AB","from":"A","to":"B","rate":"k1"},{"name":"BC","from":"B","to":"C","rate":"k2"}]}""")
function with(f, name, make=two)
    m = make()
    f(m)
    record(name, m)
end

with(m -> nothing, "two")
with(m -> (m["simulation"]["spacing"] = "linear"; m["simulation"]["output_points"] = 11), "linear")
with(m -> (m["simulation"]["spacing"] = "series";
           m["simulation"]["output_times"] = Any[K.JDict("kind" => "log", "points" => 5, "from" => 1, "to" => 100),
                                                 K.JDict("kind" => "linear", "points" => 4),
                                                 K.JDict("times" => Any[3, "7.5", 1e9, 50])]), "series")
with(m -> (m["simulation"]["spacing"] = "both"), "both")
with(m -> (m["simulation"]["spacing"] = "solver"), "solver")
with(m -> (m["simulation"]["start_time"] = "10"; m["simulation"]["end_time"] = "1e3"), "numbers as text")
with(m -> (m["simulation"] = K.JDict("startTime" => 1, "endTime" => 50, "outputPoints" => 7, "solver" => "ode15s_bdf")), "old keys")
with(m -> (m["simulation"]["max_order"] = 3; m["simulation"]["min_order"] = "2"; m["simulation"]["max_step"] = ""), "orders")
with(m -> (m["simulation"]["time_unit"] = "day"), "days")
with(m -> (m["decay_unit"] = "mol"), "mol")
with(m -> (m["half_lives"] = K.JDict("Cs-137" => "stable", "Sr-90" => 30)), "own half-lives")
with(m -> (m["chains"] = Any[Any["Cs-137", "Sr-90"], Any["Sr-90", "Cs-137", 0.5]]), "own chains")
with(m -> (m["chains"] = Any[]), "no chains")
with(m -> (m["nuclides"] = Any["U-238", "U-234", "Th-230", "Ra-226", "Pb-210", "Po-210"]), "a chain")
with(m -> (m["compartments"][1]["initial"] = K.JDict("Cs-137" => 5, "Sr-90" => "2")), "initial by nuclide")
with(m -> (m["parameters"][1]["values_by_nuclide"] = K.JDict("Cs-137" => 0.5)), "values by nuclide")
with(m -> (m["parameters"][1]["default"] = 7; delete!(m["parameters"][1], "value")), "default value")
with(m -> (m["compartments"][2]["enabled"] = false), "a disabled compartment")
with(m -> (m["compartments"][3]["enabled"] = false), "a disabled target")
with(m -> (m["compartments"][1]["system"] = "Near"; m["transfers"][1]["system"] = "Near"; m["transfers"][1]["from"] = "A";
           m["transfers"][1]["to"] = "B"), "a sub-system")
with(m -> (for c in m["compartments"]; c["system"] = "Near.Rock"; end; for t in m["transfers"]; t["system"] = "Near.Rock"; end;
           m["disabled_systems"] = Any["Near"]), "a disabled sub-system")
with(m -> (m["index_lists"] = Any[K.JDict("name" => "Zones", "indices" => Any["a", "b", K.JDict("name" => "c", "enabled" => false)])];
           m["compartments"][1]["index_lists"] = Any["Radionuclides", "Zones"];
           m["compartments"][1]["entries"] = Any[K.JDict("index" => Any["Cs-137", "a"], "initial" => "3"),
                                                 K.JDict("index" => K.JDict("Zones" => "b"), "initial" => "4", "abstol" => 1e-9)];
           m["transfers"][1]["sum_extra_indices"] = "true"), "an own list")
with(m -> (m["index_lists"] = Any[K.JDict("name" => "Climate", "for_scenarios" => true, "indices" => Any["warm", "cold"])];
           m["scenario"] = "cold"; m["parameters"][1]["index_lists"] = Any["Climate"];
           m["parameters"][1]["entries"] = Any[K.JDict("index" => "cold", "value" => 0.1)]), "scenarios")
with(m -> (m["lookups"] = Any[K.JDict("name" => "L", "points" => Any[Any[0, 10, 20], Any[1, 2, 3]], "interpolation" => "Use Input Below",
                                      "cyclic" => 1, "index_lists" => Any[])]), "a lookup")
with(m -> (m["expressions"] = Any[K.JDict("name" => "E", "equation" => "A + B"), K.JDict("name" => "S", "equation" => 2, "index_lists" => Any[])];
           m["index_reductions"] = Any[K.JDict("name" => "Tot", "target" => "E", "operation" => "SUM", "index_lists" => Any[])];
           m["block_reductions"] = Any[K.JDict("name" => "Agg", "targets" => "A + B", "operation" => "Maximum")]), "reductions")
with(m -> (m["functions"] = Any[K.JDict("name" => "f", "parameters" => Any["x", " y "], "equation" => "x*y")];
           m["min_maxes"] = Any[K.JDict("name" => "M", "target" => "A", "operation" => "MIN")];
           m["running_means"] = Any[K.JDict("name" => "R", "target" => "A")];
           m["snapshots"] = Any[K.JDict("name" => "Sn", "target" => "A", "trigger" => "T")];
           m["delays"] = Any[K.JDict("name" => "D", "target" => "A", "delay" => "5")];
           m["triggers"] = Any[K.JDict("name" => "T", "first" => "A", "second" => "0.5", "direction" => "LEFT")]), "blocks that remember")
with(m -> (m["inflows"] = Any[K.JDict("name" => "In", "to" => "A", "rate" => "1")];
           m["transfers"][1]["multiply_by_donor"] = false; m["compartments"][1]["unit"] = "kg/m3"), "units that follow")
with(m -> (m["nuclides"] = Any[]; delete!(m, "nuclides")), "no nuclides")
with(m -> (m["events"] = Any[K.JDict("name" => "Ev", "timing" => "poisson", "rate" => "1e-3", "from" => 10, "until" => "50",
                                     "actions" => Any[K.JDict("kind" => "move", "from" => "A", "to" => "", "fraction" => 0.5)])]), "an event")

# --- what is refused ---------------------------------------------------------------------------------
with(m -> (m["simulation"]["end_time"] = "soon"), "refused: end time")
with(m -> (m["simulation"]["end_time"] = 0), "refused: ends before it starts")
with(m -> (m["simulation"]["max_order"] = 7), "refused: order")
with(m -> (m["simulation"]["min_order"] = 4; m["simulation"]["max_order"] = 2), "refused: orders crossed")
with(m -> (m["simulation"]["matrix"] = "banded"), "refused: matrix")
with(m -> (m["simulation"]["time_unit"] = "week"), "refused: time unit")
with(m -> (m["simulation"]["spacing"] = "random"), "refused: spacing")
with(m -> (m["simulation"]["output_points"] = 1), "refused: points")
with(m -> (m["simulation"]["output_points"] = 2e6), "refused: too many points")
with(m -> (m["simulation"]["rtol"] = 0), "refused: rtol")
with(m -> (m["simulation"]["start_time"] = -1), "refused: log from below zero")
with(m -> (m["decay_unit"] = "g"), "refused: decay unit")
with(m -> (m["half_lives"] = K.JDict("Cs-137" => -1)), "refused: half-life")
with(m -> (m["chains"] = Any[Any["Cs-137"]]), "refused: decay pair")
with(m -> (m["chains"] = Any[Any["Cs-137", "Sr-90", 2]]), "refused: branching")
with(m -> (m["nuclides"] = Any["Xx-1"]), "refused: unknown nuclide")
with(m -> (m["compartments"][1]["name"] = "1A"), "refused: name")
with(m -> (m["compartments"][1]["name"] = "sin"), "refused: reserved")
with(m -> (m["compartments"][2]["name"] = "A"), "refused: duplicate")
with(m -> (m["compartments"][1]["system"] = "a b"), "refused: path")
with(m -> (m["compartments"][1]["abstol"] = -1), "refused: abstol")
with(m -> (m["compartments"][1]["index_lists"] = Any["Nope"]), "refused: unknown list")
with(m -> (m["compartments"][1]["index_lists"] = Any["Radionuclides", "Radionuclides"]), "refused: a list twice")
with(m -> (m["compartments"][1]["index_lists"] = Any["Radionuclides", "Contaminants"]), "refused: one dimension twice")
with(m -> (m["compartments"][1]["index_lists"] = Any["Compartments"]), "refused: a block list on a compartment")
with(m -> (m["compartments"][1]["entries"] = Any[K.JDict("index" => "Xe-1", "initial" => "1")]), "refused: entry index")
with(m -> (m["compartments"][1]["entries"] = Any[K.JDict("index" => Any["a", "b"], "initial" => "1")]), "refused: entry components")
with(m -> (m["compartments"][1]["entries"] = Any[K.JDict("index" => 3, "initial" => "1")]), "refused: entry not an index")
with(m -> (m["transfers"][1]["from"] = "Z"), "refused: source")
with(m -> (m["transfers"][1]["to"] = "Z"), "refused: target")
with(m -> (m["transfers"][1]["to"] = "A"), "refused: both ends")
with(m -> (m["transfers"][1]["from"] = nothing; m["transfers"][1]["to"] = nothing), "refused: no ends")
with(m -> (m["transfers"][1]["entries"] = Any[K.JDict("index" => "Cs-137", "rate" => "1", "multiply_by_donor" => false)]), "refused: by donor per entry")
with(m -> (m["compartments"][1]["index_lists"] = Any[]), "refused: summed dimensions")
with(m -> (m["inflows"] = Any[K.JDict("name" => "In", "to" => "Z")]), "refused: inflow target")
with(m -> (m["index_lists"] = Any[K.JDict("name" => "Z z", "indices" => Any["a"])]), "refused: list name")
with(m -> (m["index_lists"] = Any[K.JDict("name" => "Z", "indices" => Any["a", "a"])]), "refused: index twice")
with(m -> (m["index_lists"] = Any[K.JDict("name" => "Z", "indices" => Any["a<b"])]), "refused: index name")
with(m -> (m["index_lists"] = Any[K.JDict("name" => "Z", "sub_set_of" => "Y", "indices" => Any["a"])]), "refused: sub-set of nothing")
with(m -> (m["index_lists"] = Any[K.JDict("name" => "G", "mapping" => K.JDict("to" => "Radionuclides", "pairs" => Any[K.JDict("from" => "x", "to" => "Cs-137")]),
                                          "indices" => Any["g"])]), "refused: mapping from")
with(m -> (m["lookups"] = Any[K.JDict("name" => "L", "points" => Any[Any[0, "x"]])]), "refused: lookup point")
with(m -> (m["lookups"] = Any[K.JDict("name" => "L", "points" => Any[Any[0, 1]], "interpolation" => "cubic")]), "refused: interpolation")
with(m -> (m["lookups"] = Any[K.JDict("name" => "L", "points" => 5)]), "refused: points not a list")
with(m -> (m["index_reductions"] = Any[K.JDict("name" => "T", "operation" => "median", "target" => "A")]), "refused: reduction")
with(m -> (m["index_reductions"] = Any[K.JDict("name" => "T", "operation" => "percentile", "percentile" => 120, "target" => "A")]), "refused: percentile")
with(m -> (m["index_reductions"] = Any[K.JDict("name" => "T")]), "refused: nothing to reduce")
with(m -> (m["block_reductions"] = Any[K.JDict("name" => "T")]), "refused: no targets")
with(m -> (m["block_reductions"] = Any[K.JDict("name" => "T", "targets" => 5)]), "refused: targets")
with(m -> (m["functions"] = Any[K.JDict("name" => "f", "parameters" => Any["x", "x"])]), "refused: parameter twice")
with(m -> (m["min_maxes"] = Any[K.JDict("name" => "M", "operation" => "mean")]), "refused: extreme")
with(m -> (m["triggers"] = Any[K.JDict("name" => "T", "direction" => "up")]), "refused: direction")
with(m -> (m["events"] = Any[K.JDict("name" => "Ev")]), "refused: event without a time")
with(m -> (m["events"] = Any[K.JDict("name" => "Ev", "at" => "5", "actions" => Any[K.JDict("kind" => "move", "from" => "Q")])]), "refused: event moves nothing")
with(m -> (m["events"] = Any[K.JDict("name" => "Ev", "at" => "5", "actions" => Any[K.JDict("kind" => "move", "from" => "A", "fraction" => 2)])]), "refused: share")
with(m -> (m["waste_packages"] = Any[K.JDict("name" => "W", "failure" => "uniform", "fail_from" => 10, "fail_to" => 5)]), "refused: failures")
with(m -> (m["waste_packages"] = Any[K.JDict("name" => "W", "failure" => "sometimes")]), "refused: way of failing")
with(m -> (m["waste_packages"] = Any[K.JDict("name" => "W", "irf" => "1.5")]), "refused: irf")
with(m -> (m["farfields"] = Any[K.JDict("name" => "F", "n_f" => 0)]), "refused: path cells")
with(m -> (m["farfields"] = Any[K.JDict("name" => "F", "kd_m" => "-1")]), "refused: rock")
with(m -> (m["farfields"] = Any[K.JDict("name" => "F", "pen_dep" => "1", "pen_dep_0" => "0.5", "n_m" => 12, "n_f" => 5, "o_b" => 4, "n_b" => "",
                                        "grid" => "matched", "surface" => "f", "method" => "discretized")]), "refused: path depths")
with(m -> (m["disabled_systems"] = Any["Nowhere"]), "refused: disabled sub-system")
with(m -> (m["systems"] = Any["A"]), "refused: block and sub-system")

path = joinpath(@__DIR__, "..", "tests", "fixtures", "project.json")
write(path, K.json_text(K.JDict("cases" => cases); indent=0))
println(path, ": ", length(cases), " models, ", count(c -> haskey(c, "error"), cases), " refused")
