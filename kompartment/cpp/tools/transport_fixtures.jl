# Writes tests/fixtures/transport.json: what the Julia engine makes of models
# with transport sub-systems, for the C++ engine's tests to compare with
# (tests/test_transport.cpp).
#
#     julia --project=../julia tools/transport_fixtures.jl
#
# Every bundled example (none has a transport: each comes back as it is) and
# models made up to reach every branch and every refusal of the expansion: the
# project with its transports written out -- as text (its settings, lists,
# every block as normalised, what is switched off and why, the output times to
# the bit), by a hash of that text -- or the message it is refused with, the
# kind of error and the block it names. The project as a file holds it
# (`project_to_json`), before and after, travels the same way. With
# KOMPARTMENT_FIXTURE_DUMPS set to a directory, each expanded project's text is
# written there too (`<name>.julia.json`), to be compared with the C++
# engine's (`<name>.cpp.json`, which its test writes with the same variable set).

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

sorted(d) = K.JDict(k => d[k] for k in sort!(collect(keys(d))))

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
        "implicitly_disabled" => sorted(p.implicitly_disabled), "off_reasons" => sorted(p.off_reasons),
        "disabled_systems" => Any[p.disabled_systems...],
        "systems" => Any[p.systems...], "transports" => Any[p.transports...],
        "derived_lists" => Any[sort!(collect(p.derived_lists))...],
        "decay" => K.JDict("names" => Any[dm.names...], "lambdas" => Any[bits(x) for x in dm.lambdas],
                           "parents" => Any[Any[Any[q.index, bits(q.lambda), bits(q.ratio)] for q in ps] for ps in dm.parents]),
        "grid" => Any[bits(t) for t in K.time_grid(p)],
        "layout" => p.layout, "shapes" => p.shapes, "derived" => p.derived, "view" => p.view,
    )
end

const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
cases = Any[]

"""What expansion makes of a project, into `row`."""
function expand!(row, name, p)
    row["json"] = fnv(K.json_text(K.project_to_json(p); indent=0))
    try
        x = K.expand_transports(p)
        text = K.json_text(dump(x); indent=0)
        row["hash"] = fnv(text)
        row["expanded_json"] = fnv(K.json_text(K.project_to_json(x); indent=0))
        isempty(DUMPS) || write(joinpath(DUMPS, "$name.julia.json"), K.json_text(dump(x); indent=1))
    catch e
        if e isa K.BuildError
            row["kind"] = "BuildError"
            row["error"] = e.message
            row["block"] = e.block_name
        elseif e isa K.ValidationError
            row["kind"] = "ValidationError"
            row["error"] = e.message
        else
            println(stderr, name)
            rethrow()
        end
    end
    return row
end

function record(name, model)
    # The model as its text reads back, which is what the C++ test is given.
    model = K.parse_json(K.json_text(model; indent=0))
    any(c -> c["name"] == name, cases) && error("two cases named $name")
    p = try
        K.Project(model)       # every model here is one the application loads
    catch
        println(stderr, "not a model: ", name)
        rethrow()
    end
    push!(cases, expand!(K.JDict("name" => name, "model" => model), name, p))
end

examples = joinpath(@__DIR__, "..", "..", "examples")
for f in sort(readdir(examples))
    endswith(f, ".json") || continue
    name = f[1:end-5]
    m = K.parse_json(read(joinpath(examples, f), String))
    haskey(m, "transports") && println(stderr, "$name has transports")
    push!(cases, expand!(K.JDict("name" => name, "example" => name), name, K.Project(m)))
end

# --- the models -------------------------------------------------------------------------------------------

const CHAIN_SIM = """{"start_time":0,"end_time":30,"output_points":4,"spacing":"linear","solver":"dp45","rtol":1e-10,"abstol":1e-14}"""

"""The soil column of the application's transport tests: a chain of three with a counter, a
pair-reading expression, a flow back up, an inflow, an outflow, and an operation of each kind."""
column(path="Col") = K.parse_json("""{
  "simulation": $CHAIN_SIM,
  "parameters": [{"name":"k","value":0.2},{"name":"kb","value":0.05}],
  "transports": ["$path"],
  "compartments": [
    {"name":"Begin","system":"$path","transport":"begin","initial":"if(Counter == 1, 10, 0)"},
    {"name":"End","system":"$path","transport":"end","initial":"999"},
    {"name":"Sink","initial":"0"}],
  "expressions": [
    {"name":"N","system":"$path","transport":"number","equation":"3"},
    {"name":"Counter","system":"$path","transport":"counter"},
    {"name":"Rate","system":"$path","equation":"k * Counter"},
    {"name":"Diff","system":"$path","equation":"Begin - End"},
    {"name":"Mid","system":"$path","transport":"operation","operation":"sum","argument":"point"},
    {"name":"Lower","system":"$path","transport":"operation","operation":"mean","argument":"range"},
    {"name":"Whole","system":"$path","transport":"operation","operation":"sum","argument":"all"},
    {"name":"AtHalf","equation":"$path.Mid(0.5)"},
    {"name":"LowerMean","equation":"$path.Lower(0.5, 1)"}],
  "transfers": [
    {"name":"Down","system":"$path","from":"$path.Begin","to":"$path.End","rate":"Rate * (1 + 0 * Diff)"},
    {"name":"Up","system":"$path","from":"$path.End","to":"$path.Begin","rate":"kb"},
    {"name":"Out","system":"$path","from":"$path.End","to":"Sink","rate":"k"}],
  "inflows": [{"name":"Feed","to":"$path.Begin","rate":"0.5"}]}""")

"""Two transports whose blocks read their own counter by the same bare name."""
function two_columns()
    part(path, key) = K.parse_json("""{
      "compartments": [
        {"name":"Begin","system":"$path","transport":"begin","initial":"if(Counter == 1, 10, 0)"},
        {"name":"End","system":"$path","transport":"end","initial":"999"}],
      "expressions": [
        {"name":"N","system":"$path","transport":"number","equation":"3"},
        {"name":"Counter","system":"$path","transport":"counter"},
        {"name":"Rate","system":"$path","equation":"k * Counter"}],
      "transfers": [
        {"name":"Down","system":"$path","from":"$path.Begin","to":"$path.End","rate":"Rate"},
        {"name":"Up","system":"$path","from":"$path.End","to":"$path.Begin","rate":"kb"},
        {"name":"Out","system":"$path","from":"$path.End","to":"Sink","rate":"k"}]}""")[key]
    m = K.parse_json("""{"simulation": $CHAIN_SIM, "parameters": [{"name":"k","value":0.2},{"name":"kb","value":0.05}],
      "transports": ["Col","Col2"],
      "inflows": [{"name":"Feed","to":"Col.Begin","rate":"0.5"},{"name":"Feed2","to":"Col2.Begin","rate":"0.5"}]}""")
    m["compartments"] = Any[part("Col", "compartments")..., part("Col2", "compartments")..., K.JDict("name" => "Sink", "initial" => "0")]
    m["expressions"] = Any[part("Col", "expressions")..., part("Col2", "expressions")...]
    m["transfers"] = Any[part("Col", "transfers")..., part("Col2", "transfers")...]
    return m
end

block(m, collection, name) = K.findfirst_value(b -> K.qualified_name(b) == name || b["name"] == name, m[collection])
add!(m, collection, text) = push!(get!(() -> Any[], m, collection), K.parse_json(text))
function with(f, name, make=column)
    m = make()
    f(m)
    record(name, m)
end
number!(m, equation) = (K.findfirst_value(x -> get(x, "transport", nothing) == "number", m["expressions"])["equation"] = equation; m)
numbered(name, equation) = with(m -> number!(m, equation), name)

with(m -> nothing, "column")
numbered("one element", "1.9")
numbered("two elements", "2")
numbered("twelve elements", "12")
numbered("a number from parameters", "kb * 40 + 1")
numbered("a number that is one", 3)
numbered("a number with a fraction", 2.9999)
numbered("a number from the clock", "start_time() + 3")
numbered("a number from the end of the run", "end_time() / 10")
numbered("a number from time", "time() + 2")
numbered("a number by a function", "min(3, 7) + floor(0.5)")
numbered("a number by a power", "2 ^ 2")
numbered("a number by a power of the clock", "(start_time() + 2) ^ 2")
numbered("a number by a power to the clock", "2 ^ (start_time() + 2)")
numbered("a number by power() of the clock", "power(start_time() + 2, 2) - power(2, end_time() / 30)")
numbered("a number by a condition", "if(start_time() > 1, 5, 2) + (end_time() > 1 ? 1 : 0)")
numbered("refused: a number by one to an infinite power", "2 + 1 ^ (1 / start_time())")
numbered("a number by two to an infinite power", "2 + 2 ^ (-1 / start_time())")
with("a number from the sub-system's own", ) do m
    number!(m, "n0 + own")
    add!(m, "expressions", """{"name":"n0","system":"Col","equation":"1 + 1"}""")
    add!(m, "parameters", """{"name":"own","system":"Col","value":"2"}""")
    add!(m, "parameters", """{"name":"own","value":40}""")
end
with("a number from the top level") do m
    number!(m, "top")
    add!(m, "parameters", """{"name":"top","value":true}""")
    add!(m, "parameters", """{"name":"top","system":"Elsewhere","value":40}""")
end

"""A scenario list, and a parameter that differs along it."""
function scenarios!(m; scenario="cold")
    m["index_lists"] = Any[K.parse_json("""{"name":"Climate","for_scenarios":true,"indices":["warm",{"name":"cold"},{"name":"off","enabled":false}]}"""),
                           K.parse_json("""{"name":"Era","sub_set_of":"Climate","indices":["cold"]}"""),
                           K.parse_json("""{"name":"Layer","indices":["clay","sand"]}""")]
    scenario === nothing || (m["scenario"] = scenario)
    add!(m, "parameters", """{"name":"len","index_lists":["Climate"],"value":2,"entries":[{"index":"cold","value":4},{"index":"warm","value":"5"}]}""")
    return m
end
with("a number by scenario") do m
    scenarios!(m)
    number!(m, "len")
end
with("a number by another scenario") do m
    scenarios!(m; scenario="warm")
    number!(m, "len")
end
with("a number by the first scenario") do m
    scenarios!(m; scenario=nothing)
    number!(m, "len - 3")
end
with("a number by a scenario without an entry") do m
    scenarios!(m)
    block(m, "parameters", "len")["entries"] = Any[]
    number!(m, "len")
end
with("a number itself by scenario") do m
    scenarios!(m)
    n = number!(m, "2")["expressions"][1]
    n["index_lists"] = Any["Climate"]
    n["entries"] = Any[K.parse_json("""{"index":"cold","equation":"3"}""")]
end
with("a number by a list taken from the scenarios") do m
    scenarios!(m)
    block(m, "parameters", "len")["index_lists"] = Any["Era"]
    block(m, "parameters", "len")["entries"] = Any[K.parse_json("""{"index":"cold","value":3}""")]
    number!(m, "len")
end
with("refused: a number by a list that is no scenario") do m
    scenarios!(m)
    block(m, "parameters", "len")["index_lists"] = Any["Layer"]
    block(m, "parameters", "len")["entries"] = Any[]
    number!(m, "len")
end
with("refused: a number by scenario and another list") do m
    scenarios!(m)
    block(m, "parameters", "len")["index_lists"] = Any["Climate", "Layer"]
    block(m, "parameters", "len")["entries"] = Any[]
    number!(m, "len")
end

# --- chains of every shape ------------------------------------------------------------------------------------

record("erlang", K.parse_json("""{
  "simulation": {"start_time":0,"end_time":50,"output_points":6,"spacing":"linear","solver":"dp45","rtol":1e-10,"abstol":1e-14},
  "parameters": [{"name":"k","value":0.1}],
  "transports": ["Col"],
  "compartments": [
    {"name":"Begin","system":"Col","transport":"begin","initial":"if(i == 1, 1, 0)"},
    {"name":"End","system":"Col","transport":"end","initial":"0"},
    {"name":"Sink","initial":"0"}],
  "expressions": [
    {"name":"N","system":"Col","transport":"number","equation":"2 * 2"},
    {"name":"i","system":"Col","transport":"counter"},
    {"name":"Total","system":"Col","transport":"operation","operation":"sum","argument":"all"},
    {"name":"Avg","system":"Col","transport":"operation","operation":"mean","argument":"all"}],
  "transfers": [
    {"name":"Down","system":"Col","from":"Col.Begin","to":"Col.End","rate":"k"},
    {"name":"Out","system":"Col","from":"Col.End","to":"Sink","rate":"k"}]}"""))
record("decay", K.parse_json("""{
  "nuclides": ["Sr-90","Y-90"],
  "simulation": {"start_time":0,"end_time":10,"output_points":4,"spacing":"linear","solver":"dp45","rtol":1e-10,"abstol":1e-14},
  "parameters": [{"name":"k","value":0.3}],
  "transports": ["Col"],
  "compartments": [
    {"name":"Begin","system":"Col","transport":"begin","initial":"if(i == 1, 1, 0)","index_lists":["Radionuclides"]},
    {"name":"End","system":"Col","transport":"end","initial":"0","index_lists":["Radionuclides"]}],
  "expressions": [
    {"name":"N","system":"Col","transport":"number","equation":"3","index_lists":[]},
    {"name":"i","system":"Col","transport":"counter","index_lists":[]},
    {"name":"Mean","system":"Col","transport":"operation","operation":"mean","argument":"all"}],
  "transfers": [{"name":"Down","system":"Col","from":"Col.Begin","to":"Col.End","rate":"k"}]}"""))
record("two columns", two_columns())

"""Per-index values and a dy/dt on the chain, a rate that reads a point of it, and an entry that reads a stretch of it."""
entries() = K.parse_json("""{
  "nuclides": ["Cs-137","Sr-90"],
  "simulation": {"start_time":0,"end_time":20,"output_points":4,"spacing":"linear","solver":"ndf","rtol":1e-8,"abstol":1e-12},
  "parameters": [
    {"name":"k","value":0.2,"index_lists":[]},
    {"name":"kd","value":0.01,"entries":[{"index":{"Radionuclides":"Sr-90"},"value":0.03}]}],
  "transports": ["Soil"],
  "compartments": [
    {"name":"Begin","system":"Soil","transport":"begin","initial":"if(j == 1, 5, 0) + 0 * Speed + 0 * Begin + 0 * Soil.End",
     "entries":[{"index":{"Radionuclides":"Sr-90"},"initial":"if(j == 2, 7, 1) + 0 * Begin"}],"dydt":"-kd * Begin",
     "color":"#123456","symbol":"B","comment":"the top","abstol":1e-9},
    {"name":"End","system":"Soil","transport":"end","initial":"0","dydt":"-kd * Begin + 0 * End + 0 * Soil.End",
     "entries":[{"index":{"Radionuclides":"Cs-137"},"dydt":"-2 * kd * Begin + 0 * Soil.End * j"},{"index":{"Radionuclides":"Sr-90"},"initial":"3"}],
     "color":"#654321","symbol":"E","comment":"the bottom","unit":"mol"},
    {"name":"Well","initial":"0"}],
  "expressions": [
    {"name":"N","system":"Soil","transport":"number","equation":"n0 + 1","index_lists":[]},
    {"name":"n0","system":"Soil","equation":"4","index_lists":[]},
    {"name":"j","system":"Soil","transport":"counter","index_lists":[]},
    {"name":"Speed","system":"Soil","equation":"k * (1 + j / 10)","color":"#ff0000","symbol":"S","comment":"how fast",
     "entries":[{"index":{"Radionuclides":"Sr-90"},"equation":"k * (1 + j / 5)"}]},
    {"name":"Depth","system":"Soil","transport":"operation","operation":"mean","argument":"point"},
    {"name":"Band","system":"Soil","transport":"operation","operation":"sum","argument":"range"},
    {"name":"Probe","equation":"Soil.Depth(0.3)",
     "entries":[{"index":{"Radionuclides":"Sr-90"},"equation":"Soil.Band(0.2, 0.9) / 2"}]}],
  "transfers": [
    {"name":"Down","system":"Soil","from":"Soil.Begin","to":"Soil.End","rate":"Speed","color":"#00ff00","comment":"downwards",
     "entries":[{"index":{"Radionuclides":"Sr-90"},"rate":"Speed * 2 + 0 * j"},{"index":{"Radionuclides":"Cs-137"},"rate":0.25}]},
    {"name":"Seep","system":"Soil","from":"Soil.End","to":"Well","rate":"0.05 + 0 * Soil.Depth(1)",
     "entries":[{"index":{"Radionuclides":"Sr-90"},"rate":"0.01 * Depth(0.5) + Band(0, 1)"}]}]}""")
record("entries", entries())
with(m -> number!(m, "1"), "entries on one element", entries)
with(m -> number!(m, "2"), "entries on two elements", entries)

# A chain not by nuclide in a model with nuclides, drawn between two blocks outside it.
record("a chain not by nuclide", K.parse_json("""{
  "nuclides": ["Cs-137","Sr-90"],
  "simulation": {"start_time":0,"end_time":30,"output_points":4,"spacing":"linear","solver":"ndf","rtol":1e-8,"abstol":1e-12},
  "parameters": [{"name":"k","value":0.2,"index_lists":[]}],
  "transports": ["Pipe"],
  "compartments": [
    {"name":"Tank","initial":"100","index_lists":[]},
    {"name":"Begin","system":"Pipe","transport":"begin","initial":"0","index_lists":[]},
    {"name":"End","system":"Pipe","transport":"end","initial":"0","index_lists":[]},
    {"name":"Pond","initial":"0","index_lists":[]}],
  "expressions": [
    {"name":"N","system":"Pipe","transport":"number","equation":"3","index_lists":[]},
    {"name":"Held","system":"Pipe","transport":"operation","operation":"sum","argument":"all"}],
  "transfers": [
    {"name":"Fill","from":"Tank","to":"Pipe.Begin","rate":"k","index_lists":[]},
    {"name":"Flow","system":"Pipe","from":"Begin","to":"End","rate":"k","index_lists":[]},
    {"name":"Drain","from":"Pipe.End","to":"Pond","rate":"k","index_lists":[]}]}"""))

with(m -> nothing, "a transport in a sub-system", () -> column("Near.Col"))
with("numbers where equations stand") do m
    block(m, "compartments", "Col.Begin")["initial"] = 10
    block(m, "compartments", "Col.End")["initial"] = 0.5
    block(m, "transfers", "Col.Up")["rate"] = 0.25
    block(m, "transfers", "Col.Down")["rate"] = 1.0e-5
    block(m, "expressions", "Col.Diff")["equation"] = 7
end
with("numbers where equations stand, one element") do m
    number!(m, "1")
    block(m, "compartments", "Col.Begin")["initial"] = 10
    block(m, "transfers", "Col.Up")["rate"] = 0.25
    block(m, "transfers", "Col.Down")["rate"] = 1.0e22
end
with("no counter") do m
    filter!(x -> x["name"] != "Counter", m["expressions"])
    block(m, "compartments", "Col.Begin")["initial"] = "10"
    block(m, "expressions", "Col.Rate")["equation"] = "k"
end
with("no counter, one element") do m
    number!(m, "1")
    filter!(x -> x["name"] != "Counter", m["expressions"])
    block(m, "compartments", "Col.Begin")["initial"] = "10"
    block(m, "expressions", "Col.Rate")["equation"] = "k"
end
with("no transfers inside") do m
    filter!(t -> t["name"] == "Out", m["transfers"])
end
with("no transfers inside, one element") do m
    number!(m, "1")
    filter!(t -> t["name"] == "Out", m["transfers"])
end
with("names taken") do m
    add!(m, "compartments", """{"name":"Begin_2","system":"Col","initial":"1"}""")
    add!(m, "expressions", """{"name":"Rate_1","system":"Col","equation":"1"}""")
    add!(m, "expressions", """{"name":"Rate_1_1","system":"Col","equation":"1"}""")
    add!(m, "parameters", """{"name":"Down_2","system":"Col","value":1}""")
    add!(m, "lookups", """{"name":"Up_2","system":"Col","points":[[0,1],[1,2]]}""")
    add!(m, "expressions", """{"name":"Diff_2","system":"Col","equation":"1"}""")
    add!(m, "compartments", """{"name":"Begin_2","initial":"1"}""")
end
with("names taken, five elements") do m
    number!(m, "5")
    add!(m, "compartments", """{"name":"Begin_3","system":"Col","initial":"1"}""")
    add!(m, "compartments", """{"name":"Begin_3_1","system":"Col","initial":"1"}""")
    add!(m, "transfers", """{"name":"Down_4","system":"Col","from":"Col.Begin_3","to":"Col.Begin_3_1","rate":"1"}""")
    add!(m, "index_reductions", """{"name":"Rate_3","system":"Col","target":"Begin","operation":"sum"}""")
    add!(m, "block_reductions", """{"name":"Diff_4","system":"Col","targets":"Begin + End","operation":"sum"}""")
end
with("expressions that follow one another") do m
    add!(m, "expressions", """{"name":"X","system":"Col","equation":"Rate + 1"}""")
    add!(m, "expressions", """{"name":"Y","system":"Col","equation":"2 * X"}""")
    add!(m, "expressions", """{"name":"Y2","system":"Col","equation":"Col.Y + Y3"}""")
    add!(m, "expressions", """{"name":"Y3","system":"Col","equation":"Y2"}""")
    add!(m, "expressions", """{"name":"Z","system":"Col","equation":"k + kb"}""")
    add!(m, "expressions", """{"name":"ReadsDown","system":"Col","equation":"Down + 1"}""")
    add!(m, "expressions", """{"name":"ReadsEnd","system":"Col","equation":"End * 2","entries":[]}""")
    add!(m, "expressions", """{"name":"Outside","equation":"Col.X + Col.Rate + Col.Z"}""")
    add!(m, "expressions", """{"name":"Broken","system":"Col","equation":"Counter # 2"}""")
    add!(m, "expressions", """{"name":"Calls","system":"Col","equation":"min(Counter, 2) + max(1, 2) + Rate(1)"}""")
    block(m, "transfers", "Col.Up")["rate"] = "kb * Y + 0 * ReadsDown + 0 * Z"
end
with("a bare name that is another's counter") do m
    add!(m, "expressions", """{"name":"Counter","equation":"5"}""")
    add!(m, "expressions", """{"name":"ReadsTop","equation":"Counter + 1"}""")
    add!(m, "expressions", """{"name":"ReadsTopToo","system":"Elsewhere","equation":"Counter + 1"}""")
    add!(m, "compartments", """{"name":"Begin","initial":"Counter"}""")
    add!(m, "expressions", """{"name":"Inside","system":"Col","equation":"Counter + Begin"}""")
end
with("a transfer between the ends drawn outside") do m
    add!(m, "transfers", """{"name":"Across","from":"Col.Begin","to":"Col.End","rate":"k * Col.Rate + 0 * Col.Begin"}""")
    add!(m, "transfers", """{"name":"Back","system":"Elsewhere","from":"Col.End","to":"Col.Begin","rate":"kb","multiply_by_donor":false,
                            "color":"#abcdef","comment":"upwards"}""")
end
with("refused: a transfer between the ends drawn outside reads the counter") do m
    add!(m, "transfers", """{"name":"Across","from":"Col.Begin","to":"Col.End","rate":"k * Col.Counter"}""")
end
with("a transfer between the ends drawn outside, one element") do m
    number!(m, "1")
    add!(m, "transfers", """{"name":"Across","from":"Col.Begin","to":"Col.End","rate":"k"}""")
    add!(m, "inflows", """{"name":"IntoEnd","to":"Col.End","rate":"1"}""")
    add!(m, "transfers", """{"name":"FromSink","from":"Sink","to":"Col.End","rate":"k"}""")
    add!(m, "transfers", """{"name":"Leaves","from":"Col.End","rate":"k"}""")
end
with("characters past ASCII") do m
    m["index_lists"] = Any[K.parse_json("""{"name":"Skikt","indices":["Å","ö","lera"]}""")]
    block(m, "parameters", "k")["index_lists"] = Any["Skikt"]
    block(m, "expressions", "Col.Rate")["equation"] = "k[Å] * Counter + 0 * k[ö] * Begin + 0 * End * k[Å]"
    block(m, "compartments", "Col.Begin")["initial"] = "if(Counter == 1, k[ö], 0 * k[Å] * Counter)"
    block(m, "expressions", "AtHalf")["equation"] = "k[Å] + Col.Mid(0.5) + k[ö] * Col.Lower(0, 1) + k[lera]"
    block(m, "expressions", "LowerMean")["equation"] = "Col.Lower(0.5, 1) € 2"
    block(m, "transfers", "Col.Out")["comment"] = "söderut, Col.Mid(0.5)"
end

# --- operations ---------------------------------------------------------------------------------------------------

with("operations of every kind") do m
    for (name, op, arg) in (("SumPoint", "sum", "point"), ("MeanPoint", "mean", "point"), ("SumRange", "sum", "range"),
                            ("MeanRange", "mean", "range"), ("SumAll", "sum", "all"), ("MeanAll", "mean", "all"),
                            ("Loud", " MEAN ", " Range "), ("Point", "point", "ALL"), ("Unknown", "median", "everything"))
        add!(m, "expressions", """{"name":"$name","system":"Col","transport":"operation","operation":"$op","argument":"$arg"}""")
    end
    add!(m, "expressions", """{"name":"Bare","system":"Col","transport":"operation"}""")
    add!(m, "expressions", """{"name":"WithUnit","system":"Col","transport":"operation","argument":"all","unit":"kg","color":"#111111",
                              "comment":"the lot","entries":[{"index":{},"equation":"5"}]}""")
    block(m, "compartments", "Col.Begin")["unit"] = "mol"
    add!(m, "expressions", """{"name":"Uses","equation":"Col.SumPoint(0.1) + Col.MeanPoint(0.2) + Col.SumRange(0, 0.5) + Col.MeanRange(0.5, 1) + Col.SumAll + Col.MeanAll + Col.Loud(0, 1) + Col.Point + Col.Unknown + Col.Bare + Col.WithUnit"}""")
    add!(m, "expressions", """{"name":"UsesInside","system":"Col","equation":"SumPoint(0.1) + MeanRange(0.5, 1) + Col.Loud(0.25, 0.75) + SumAll"}""")
    add!(m, "expressions", """{"name":"UsesElsewhere","system":"Other","equation":"Col.SumPoint(0.1) + Col.MeanRange(0.5, 1) + SumPoint + sin(1)"}""")
end
with("operations on one element") do m
    number!(m, "1")
    add!(m, "expressions", """{"name":"MeanAll","system":"Col","transport":"operation","operation":"mean","argument":"all"}""")
    add!(m, "expressions", """{"name":"Uses","equation":"Col.MeanAll + Col.Whole + Col.Mid(1)"}""")
end
with("operations with the element names taken at the top") do m
    add!(m, "compartments", """{"name":"Begin","initial":"1"}""")
    add!(m, "compartments", """{"name":"End","initial":"1"}""")
    add!(m, "expressions", """{"name":"Inside","system":"Col","equation":"Mid(0.5) + Lower(0, 1) + Whole"}""")
    add!(m, "expressions", """{"name":"Elsewhere","system":"Other","equation":"Col.Mid(0.5)"}""")
end
with("operations called in every way") do m
    eq(name, text) = add!(m, "expressions", K.json_text(K.JDict("name" => name, "equation" => text); indent=0))
    eq("Nested", "Col.Mid((0.5))")
    eq("InCall", "Col.Mid(min(0.2, 0.5))")
    eq("Deep", "Col.Lower(min(0.2, 0.5), max(0.6, (0.7 + 0.1)))")
    eq("Unclosed", "Col.Mid(0.5")
    eq("UnclosedDeep", "Col.Lower(0.5, (1")
    eq("Twice", "Col.Mid(0.1) + Col.Mid(0.9) * Col.Lower(0, 1)")
    eq("InsideItself", "Col.Mid(Col.Mid(0.5))")
    eq("NotCalled", "Col.Mid + Col.Lower")
    eq("Spaced", "  Col.Mid  ( 0.5 )  ")
    eq("Indexed", "Col.Mid[a](0.5)")
    eq("LooksLike", "Mid(0.5) + Col.Middle(0.5) + NotCol.Mid(0.5) + ColXMid(0.5)")
    eq("NoToken", "Col.Mid(0.5) # 1")
    eq("AfterBracket", "k[Col.Mid(0.5)] + Col.Mid(0.25)")
    eq("ANumber", 5)
    eq("Reserved", "sin(Col.Mid(0.5)) + if(Col.Mid(0.5) > 1, Col.Lower(0, 0.5), 2)")
end
with("operations read by blocks of every kind") do m
    block(m, "compartments", "Sink")["initial"] = "Col.Mid(0.5)"
    block(m, "compartments", "Sink")["dydt"] = "-Col.Lower(0, 1)"
    m["index_lists"] = Any[K.parse_json("""{"name":"Layer","indices":["clay","sand"]}""")]
    add!(m, "compartments", """{"name":"Layered","index_lists":["Layer"],"initial":"1","dydt":"0",
                               "entries":[{"index":"clay","initial":"Col.Mid(0.1)"},{"index":"sand","dydt":"Col.Lower(0.1, 0.2)","initial":"2"}]}""")
    block(m, "transfers", "Col.Out")["rate"] = "k + 0 * Mid(0.5)"
    block(m, "inflows", "Feed")["rate"] = "0.5 + 0 * Col.Lower(0, 1)"
    add!(m, "inflows", """{"name":"Layers","to":"Layered","index_lists":["Layer"],"rate":"1","entries":[{"index":"sand","rate":"Col.Mid(0.3)"}]}""")
    add!(m, "farfields", """{"name":"Rock","tw":"50 + 0 * Col.Mid(0.5)","f":"1e5","kd_f":"Col.Lower(0, 1) * 0","kd_m":"0.1","de_m":"1e-6",
                            "eps_m":"0.0018","rho_m":"2700","pe":"10","pen_dep":"12.5 + 0 * Col.Mid(1)","pen_dep_0":"","n_f":4,"n_m":3}""")
    add!(m, "min_maxes", """{"name":"Peak","target":"Col.Mid(0.5)","reset_trigger":"Tr","start_trigger":"Tr","stop_trigger":"Tr"}""")
    add!(m, "running_means", """{"name":"Mean","target":"Col.Lower(0, 1)","start_trigger":"Tr"}""")
    add!(m, "snapshots", """{"name":"Shot","target":"Col.Mid(0.5)","initial":"Col.Lower(0, 0.5)","trigger":"Tr"}""")
    add!(m, "delays", """{"name":"Late","target":"Col.Mid(0.5)","delay":"1 + 0 * Col.Lower(0, 1)"}""")
    add!(m, "triggers", """{"name":"Tr","first":"Col.Mid(0.5)","second":"Col.Lower(0, 1)"}""")
    add!(m, "parameters", """{"name":"p","value":"Col.Mid(0.5)"}""")
    add!(m, "functions", """{"name":"f","parameters":["x"],"equation":"x + Col.Mid(0.5)"}""")
    add!(m, "index_reductions", """{"name":"Red","target":"Col.Mid(0.5)","operation":"sum"}""")
end

# --- what is switched off --------------------------------------------------------------------------------------

function off!(m, collection, names...)
    for b in m[collection]
        (b["name"] in names || K.qualified_name(b) in names) && (b["enabled"] = false)
    end
end
with("switched off whole") do m
    for c in ("compartments", "transfers", "expressions"), b in m[c]
        (get(b, "system", "") == "Col" || b["name"] in ("AtHalf", "LowerMean")) && (b["enabled"] = false)
    end
    m["inflows"][1]["enabled"] = false
end
with("switched off by its sub-system") do m
    m["disabled_systems"] = Any["Col"]
    off!(m, "expressions", "AtHalf", "LowerMean")
    off!(m, "inflows", "Feed")
end
with("the two ends switched off") do m
    off!(m, "compartments", "Col.Begin", "Col.End")
    filter!(x -> !(x["name"] in ("AtHalf", "LowerMean")), m["expressions"])
    off!(m, "expressions", "Col.Rate", "Col.Diff")
    add!(m, "expressions", """{"name":"ReadsN","equation":"Col.N"}""")
end
with("refused: Begin switched off, the transfers left") do m
    off!(m, "compartments", "Col.Begin")
    filter!(x -> !(x["name"] in ("AtHalf", "LowerMean")), m["expressions"])
end
with("refused: End switched off, the transfers left") do m
    off!(m, "compartments", "Col.End")
end
with("Begin switched off") do m
    off!(m, "compartments", "Col.Begin")
    off!(m, "transfers", "Col.Down", "Col.Up", "Col.Out")
    off!(m, "inflows", "Feed")
end
with("End switched off") do m
    off!(m, "compartments", "Col.End")
    filter!(t -> t["name"] == "nothing", m["transfers"])
    empty!(m["inflows"])
end
with("refused: End switched off, the inflow left") do m
    off!(m, "compartments", "Col.End")
    filter!(t -> t["name"] == "nothing", m["transfers"])
end
with("no End, and something else switched off") do m
    filter!(c -> c["name"] != "End", m["compartments"])
    filter!(t -> t["name"] == "nothing", m["transfers"])
    empty!(m["inflows"])
    off!(m, "expressions", "Col.Rate")
end
with("refused: Begin switched off beside a second Begin") do m
    off!(m, "compartments", "Col.Begin")
    add!(m, "compartments", """{"name":"Begin2","system":"Col","transport":"begin","initial":"0"}""")
    add!(m, "compartments", """{"name":"Begin3","system":"Col","transport":"begin","initial":"0"}""")
end
with("an expression of the chain switched off") do m
    off!(m, "expressions", "Col.Diff")
    block(m, "transfers", "Col.Down")["rate"] = "Rate"
end
with("a transfer of the chain switched off") do m
    off!(m, "transfers", "Col.Up")
end
with("the outflow switched off, one element") do m
    number!(m, "1")
    off!(m, "transfers", "Col.Out")
end
with("what feeds the chain switched off") do m
    add!(m, "compartments", """{"name":"Source","initial":"1","enabled":false}""")
    add!(m, "transfers", """{"name":"In","from":"Source","to":"Col.Begin","rate":"k"}""")
    add!(m, "compartments", """{"name":"Gone","initial":"1","enabled":false}""")
    add!(m, "transfers", """{"name":"Away","from":"Col.End","to":"Gone","rate":"k"}""")
    add!(m, "inflows", """{"name":"Nowhere","to":"Gone","rate":"1"}""")
end
with("a disabled sub-system beside the chain") do m
    add!(m, "compartments", """{"name":"Pool","system":"Far.Deep","initial":"1"}""")
    add!(m, "transfers", """{"name":"ToPool","system":"Far","from":"Col.End","to":"Far.Deep.Pool","rate":"k"}""")
    m["disabled_systems"] = Any["Far", "Far"]
    m["systems"] = Any["Far", "Far.Deep", "Spare"]
end
with("a model with everything a file keeps") do m
    m["name"] = "Kept"
    m["description"] = "what a file keeps"
    m["nuclides"] = Any["Cs-137", "Ba-137m", "Sr-90"]
    block(m, "expressions", "Col.N")["index_lists"] = Any[]
    block(m, "expressions", "Col.Counter")["index_lists"] = Any[]
    m["half_lives"] = K.parse_json("""{"Cs-137":30,"Sr-90":"28.8"}""")
    m["chains"] = K.parse_json("""[["Cs-137","Ba-137m",0.944],["Sr-90","Cs-137"]]""")
    m["decay_unit"] = "mol"
    m["layout"] = K.parse_json("""{"Col.Begin":{"x":1,"y":2},"Sink":{"x":5,"y":6}}""")
    m["shapes"] = K.parse_json("""[{"kind":"text","text":"a note","x":1}]""")
    m["derived"] = K.parse_json("""[{"name":"Total","of":["Sink"]}]""")
    m["view"] = K.parse_json("""{"zoom":1.5,"system":"Col"}""")
    m["systems"] = Any["Spare.Deeper"]
    add!(m, "lookups", """{"name":"Table","points":[[0,1],[10,2]],"interpolation":"Use Input Below"}""")
    add!(m, "functions", """{"name":"twice","parameters":["x"],"equation":"2 * x"}""")
    add!(m, "waste_packages", """{"name":"Cans","inventory":"1","enabled":false}""")
    add!(m, "events", """{"name":"Ev","at":"5","actions":[{"kind":"move","from":"Sink","to":"","fraction":0.5}]}""")
    add!(m, "triggers", """{"name":"Tr","first":"Sink","second":"1","enabled":false}""")
    add!(m, "index_reductions", """{"name":"Red","target":"Sink","operation":"sum","enabled":false}""")
end

# --- no transport to write out -----------------------------------------------------------------------------------

with(m -> (m["transports"] = Any[""]), "a transport with no name")
with(m -> (m["transports"] = Any["  ", nothing]), "transports that are blank")
with(m -> (m["transports"] = Any[]), "no transports listed")
with(m -> delete!(m, "transports"), "no transports")

# --- what is refused -----------------------------------------------------------------------------------------------

numbered("refused: a number that reads a state", "Begin + 1")
numbered("refused: a number below one", "0.5")
numbered("refused: a number of zero", "0")
numbered("refused: a negative number", "-3")
numbered("refused: a number that is no number", "0 / 0")
numbered("refused: an infinite number", "1 / 0")
numbered("refused: a number that cannot be read", "3 +")
numbered("refused: a number with a character the language lacks", "3 # 1")
numbered("refused: a number by a function unknown", "foo(3)")
numbered("refused: a number that reads itself", "N + 1")
numbered("refused: a number that reads an index", "k[a] + 3")
numbered("refused: a number that reads a name unknown", "nope + 3")
numbered("a number that reads the counter", "Counter + 2")
numbered("refused: a number that is empty", "")
numbered("refused: a number far below one", "-1e30")
with("refused: a number in a circle") do m
    number!(m, "M + 1")
    add!(m, "expressions", """{"name":"M","system":"Col","equation":"L2 + 1"}""")
    add!(m, "expressions", """{"name":"L2","system":"Col","equation":"N"}""")
end
with("refused: a number from a parameter that is text") do m
    number!(m, "p + 1")
    add!(m, "parameters", """{"name":"p","value":"three"}""")
end
with("refused: a number from a parameter with no value") do m
    number!(m, "p + 1")
    add!(m, "parameters", """{"name":"p","value":null}""")
end
with("a number from parameters written as text") do m
    number!(m, "p + q + r")
    add!(m, "parameters", """{"name":"p","value":" 1 "}""")
    add!(m, "parameters", """{"name":"q","value":"1e0"}""")
    add!(m, "parameters", """{"name":"r","value":"1_0e-1"}""")
end
with("refused: a number from an infinite parameter") do m
    number!(m, "p")
    add!(m, "parameters", """{"name":"p","value":"inf"}""")
end
with("refused: a number from a compartment") do m
    number!(m, "Sink + 3")
end
with("refused: a number from a parameter switched off") do m
    number!(m, "p + 3")
    add!(m, "parameters", """{"name":"p","value":1,"enabled":false}""")
end
with("refused: no number") do m
    filter!(x -> x["name"] != "N", m["expressions"])
end
with("two numbers") do m
    add!(m, "expressions", """{"name":"N2","system":"Col","transport":"number","equation":"7"}""")
end
with("two counters") do m
    add!(m, "expressions", """{"name":"Counter2","system":"Col","transport":"counter"}""")
    block(m, "expressions", "Col.Rate")["equation"] = "k * Counter + 0 * Counter2"
end
with("refused: two Begins") do m
    add!(m, "compartments", """{"name":"Begin2","system":"Col","transport":"begin","initial":"0"}""")
end
with("refused: two Begins and three Ends") do m
    add!(m, "compartments", """{"name":"Begin2","system":"Col","transport":"begin","initial":"0"}""")
    add!(m, "compartments", """{"name":"End2","system":"Col","transport":"end","initial":"0"}""")
    add!(m, "compartments", """{"name":"End3","system":"Col","transport":"end","initial":"0"}""")
end
with("refused: no End") do m
    filter!(c -> get(c, "transport", nothing) != "end", m["compartments"])
    filter!(t -> t["name"] == "nothing", m["transfers"])
end
with("refused: no Begin") do m
    filter!(c -> get(c, "transport", nothing) != "begin", m["compartments"])
    filter!(t -> t["name"] == "Out", m["transfers"])
    empty!(m["inflows"])
end
with("refused: neither end") do m
    filter!(c -> !haskey(c, "transport"), m["compartments"])
    empty!(m["transfers"])
    empty!(m["inflows"])
end
with("refused: no End and two Begins") do m
    filter!(c -> get(c, "transport", nothing) != "end", m["compartments"])
    filter!(t -> t["name"] == "nothing", m["transfers"])
    add!(m, "compartments", """{"name":"Begin2","system":"Col","transport":"begin","initial":"0"}""")
end
with("refused: a transport with nothing in it") do m
    push!(m["transports"], "Empty")
end
with("refused: the second transport") do m
    push!(m["transports"], "Empty.Inside")
    m["transports"] = Any["Col", "Empty.Inside", "Empty"]
end
with("refused: the first of two") do m
    m["transports"] = Any["Empty", "Col"]
end
with("refused: the ends indexed apart") do m
    m["index_lists"] = Any[K.parse_json("""{"name":"Layer","indices":["clay","sand"]}""")]
    block(m, "compartments", "Col.End")["index_lists"] = Any["Layer"]
end
with("the ends indexed alike in another order") do m
    m["index_lists"] = Any[K.parse_json("""{"name":"Layer","indices":["clay","sand"]}"""),
                           K.parse_json("""{"name":"Zone","indices":["a","b"]}""")]
    block(m, "compartments", "Col.Begin")["index_lists"] = Any["Layer", "Zone"]
    block(m, "compartments", "Col.End")["index_lists"] = Any["Zone", "Layer"]
    block(m, "compartments", "Col.Begin")["entries"] = Any[K.parse_json("""{"index":["clay","a"],"initial":"Counter"}""")]
end
function counter_outside(name, collection, text, make=two_columns)
    with(name, make) do m
        add!(m, collection, text)
    end
end
counter_outside("refused: the counter read from another transport", "expressions", """{"name":"Peek","system":"Col2","equation":"Col.Counter * 2"}""")
counter_outside("refused: the counter read from the top", "expressions", """{"name":"Peek","equation":"1 + Col.Counter"}""")
counter_outside("refused: the counter read from inside a sub-system of the chain", "expressions",
                """{"name":"Peek","system":"Col.Inner","equation":"Col.Counter"}""")
counter_outside("refused: the counter read by a transfer", "transfers", """{"name":"Peek","from":"Sink","rate":"Col2.Counter"}""")
counter_outside("refused: the counter read by an inflow", "inflows", """{"name":"Peek","to":"Sink","rate":"0 * Col.Counter"}""")
counter_outside("refused: the counter read by an initial value", "compartments", """{"name":"Peek","initial":"Col.Counter"}""")
counter_outside("refused: the counter read by a dy/dt", "compartments", """{"name":"Peek","initial":"0","dydt":"Col2.Counter"}""")
with("refused: the counter read by an entry", two_columns) do m
    m["index_lists"] = Any[K.parse_json("""{"name":"Layer","indices":["clay","sand"]}""")]
    add!(m, "expressions", """{"name":"First","equation":"Counter"}""")
    add!(m, "expressions", """{"name":"Peek","index_lists":["Layer"],"equation":"1","entries":[{"index":"sand","equation":"k + Col.Counter"}]}""")
    add!(m, "expressions", """{"name":"Counter","system":"Col.Inner","equation":"1"}""")
    add!(m, "expressions", """{"name":"Fine","system":"Col.Inner","equation":"Counter"}""")
end
counter_outside("the counter's name read where it is another block", "expressions", """{"name":"Fine","system":"Col2","equation":"Counter + Col2.Counter"}""")
counter_outside("the counter read by a block that is no equation of the run", "parameters", """{"name":"Fine","value":"Col.Counter"}""")
counter_outside("the counter in text the language cannot read", "expressions", """{"name":"Fine","equation":"Col.Counter # 1"}""")
function arity(name, equation, where="AtHalf")
    with(name) do m
        block(m, "expressions", where)["equation"] = equation
    end
end
arity("refused: a point given two positions", "Col.Mid(0.5, 0.7)")
arity("refused: a point given none", "Col.Mid()")
arity("refused: a point given none, spaced", "1 + Col.Mid( )")
arity("refused: a point given three", "Col.Mid(0.1, (0.2, 0.3), 0.4)")
arity("refused: a stretch given one position", "Col.Lower(0.5)")
arity("refused: a stretch given none", "Col.Lower()")
arity("refused: a stretch given three", "Col.Lower(0, 0.5, 1)")
arity("refused: a stretch left open", "Col.Lower(")
arity("refused: a stretch given one in a call", "Col.Lower(min(0, 1))")
arity("refused: the second call of two", "Col.Mid(0.5) + Col.Mid(0.5, 1)")
with("refused: a point given two positions inside the chain") do m
    block(m, "expressions", "Col.Rate")["equation"] = "k * Counter + 0 * Mid(0.1, 0.2)"
end
with("refused: a stretch given one by a transfer's entry") do m
    m["index_lists"] = Any[K.parse_json("""{"name":"Layer","indices":["clay","sand"]}""")]
    add!(m, "compartments", """{"name":"Layered","index_lists":["Layer"],"initial":"1"}""")
    add!(m, "transfers", """{"name":"Leak","from":"Layered","rate":"1","entries":[{"index":"sand","rate":"Col.Lower(0.3)"}]}""")
end
with("refused: a point given two by a trigger") do m
    add!(m, "triggers", """{"name":"Tr","first":"Sink","second":"Col.Mid(0.5, 1)"}""")
    block(m, "expressions", "LowerMean")["equation"] = "Col.Lower(0.5)"
end
with("refused: an element's name taken by a waste package") do m
    add!(m, "waste_packages", """{"name":"Begin_2","system":"Col","inventory":"1"}""")
end
with("refused: a copy's name taken by a function") do m
    add!(m, "functions", """{"name":"Rate_1","system":"Col","parameters":["x"],"equation":"x"}""")
end
with("refused: an event moves the End of one element") do m
    number!(m, "1")
    add!(m, "events", """{"name":"Ev","at":"5","actions":[{"kind":"move","from":"Col.End","to":"Sink","fraction":0.5}]}""")
end
with("an event moves the End") do m
    add!(m, "events", """{"name":"Ev","at":"5","actions":[{"kind":"move","from":"Col.End","to":"Sink","fraction":0.5}]}""")
end

path = joinpath(@__DIR__, "..", "tests", "fixtures", "transport.json")
write(path, K.json_text(K.JDict("cases" => cases); indent=0))
println(path, ": ", length(cases), " models, ", count(c -> haskey(c, "error"), cases), " refused (",
        count(c -> get(c, "kind", "") == "ValidationError", cases), " once written out), ", filesize(path), " bytes")
for c in cases
    haskey(c, "error") != startswith(c["name"], "refused") && println("  unexpected: ", c["name"], " -- ", get(c, "error", "expanded"))
end
