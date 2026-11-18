# Writes tests/fixtures/builder.json: what the Julia engine's builder makes of
# models, for the C++ engine's tests to compare with (tests/test_builder.cpp).
#
#     julia --project=../julia tools/builder_fixtures.jl
#
# Every model of tests/fixtures/project.json that is read (run
# tools/project_fixtures.jl first), and models made up here to reach the
# builder's branches and refusals. A built model is written out section by
# section -- the layout, the parameters, the tables, each pass's statements as
# merged, the derivative's phases, the jumps, the events -- and each section
# kept as a hash of its text, or the model as the message it is refused with.
# With KOMPARTMENT_FIXTURE_DUMPS set to a directory the sections' text is
# written there too (`<name>.builder.julia.txt`).

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
ints(v) = join(v, ",")
nums(v) = join((bits(Float64(x)) for x in v), ",")

function leaf_text(l::K.TLeaf)
    k = l.kind
    k in (:T, :T0, :T1) && return String(k)
    k === :K && return l.values === nothing ? "K($(bits(l.value)))" : "K[$(nums(l.values))]"
    return l.indices === nothing ? "$k($(l.index))" : "$k[$(ints(l.indices))]"
end
tree_text(t::K.TLeaf) = leaf_text(t)
tree_text(t::K.TNeg) = "neg(" * tree_text(t.a) * ")"
tree_text(t::K.TBin) = "(" * String(t.op) * " " * tree_text(t.a) * " " * tree_text(t.b) * ")"
tree_text(t::K.TCond) = "(? " * tree_text(t.test) * " " * tree_text(t.a) * " " * tree_text(t.b) * ")"
tree_text(t::K.TCall) = t.key * "(" * join((tree_text(a) for a in t.args), ",") * ")"
tree_text(t::K.TTab) = "tab(" * leaf_text(t.leaf) * "," * tree_text(t.arg) * ")"

function stmt_text(s::K.Stmt)
    sp = s.special
    if sp isa K.FarfieldRelease
        return "special farfield $(sp.index) $(sp.laplace)"
    elseif sp isa K.RecorderRead
        return "special $(sp.kind) out=$(ints(sp.out)) mem=$(ints(sp.mem)) arg=$(ints(sp.arg)) state=$(ints(sp.state))"
    end
    return "$(s.array) $(s.multiply ? "*=" : "=") w=$(s.width) out=$(ints(K.out_indices(s))) :: $(tree_text(s.tree))"
end
stmts_text(v) = join((stmt_text(s) for s in v), "\n")

function jump_text(op)
    op isa K.JumpCount && return "count $(op.slot)"
    op isa K.JumpFail && return "fail share=$(op.share_slot) intact=$(ints(op.intact)) exposed=$(ints(op.exposed)) irf=$(ints(op.irf)) to=$(ints(op.to)) budget=$(ints(op.budget))"
    return "move share=$(op.share_slot) from=$(ints(op.from)) to=$(ints(op.to)) budget=$(ints(op.budget))"
end

function sections(b::K.Builder)
    out = K.JDict()
    io = IOBuffer()
    println(io, "nstate=$(b.nstate) nalg=$(b.nalg) nparam=$(b.nparam)")
    for s in b.states
        println(io, "state $(s.name)|$(s.kind)|$(s.base)|$(s.width)|$(join(s.dims, ","))|$(s.hidden)")
    end
    for s in b.param_layout
        println(io, "param $(s.name)|$(s.base)|$(s.width)|$(join(s.dims, ","))")
    end
    for s in b.point_layout
        println(io, "point $(s.name)|$(s[:off])|$(s[:point])|$(s[:slot])|$(s[:tab])|$(s[:row])")
    end
    for s in b.algebraic
        println(io, "alg $(s.name)|$(s.kind)|$(s.base)|$(s.width)|$(s.level)|$(s.cls)|$(join(s.dims, ","))|$(join(s.reads_alg, ","))|$(s.hidden)")
    end
    out["layout"] = String(take!(io))
    out["P"] = nums(b.P)
    out["tables"] = join(("$(nums(t.x))|$(nums(t.y))|$(t.interpolation)|$(t.cyclic)|$(t.wraps)" for t in b.TAB), "\n")
    out["invariant"] = stmts_text(K.merge_statements(b.pass_stmts[0]))
    out["clock"] = stmts_text(K.merge_statements(b.pass_stmts[1]))
    out["moving"] = stmts_text(K.merge_statements(b.pass_stmts[2]))
    out["derivative"] = b.derivative_stmts === nothing ? "all" :
                        join(sort!(collect(b.derivative_blocks)), ",") * "\n" * stmts_text(K.merge_statements(b.derivative_stmts))
    before = K.merge_statements([K.Stmt(s.out, s.tree, s.width, s.block, s.level, s.mergeable, s.special, s.array, s.multiply) for s in b.initial_before])
    out["initial"] = stmts_text(before) * "\n--\n" * stmts_text(K.merge_statements(b.initial_stmts))
    out["classes"] = join(Int.(b.slot_class), ",")
    out["phases"] = join(("$(ph.kind) tgt=$(ints(ph.tgt)) a=$(ints(ph.a)) b=$(ints(ph.b)) c=$(ints(ph.c)) f=$(nums(ph.f)) s1=$(ph.s1) s2=$(ph.s2)" for ph in b.phases), "\n")
    out["flux"] = "nflux=$(b.nflux) rate=$(ints(b.flux_rate)) mbd=$(ints(b.flux_mbd)) src=$(ints(b.flux_mbd_src))"
    out["decay"] = join(("$l: lam=$(nums(b.DEC_tables[l].lam)) ioff=$(ints(b.DEC_tables[l].ioff)) icnt=$(ints(b.DEC_tables[l].icnt)) ipar=$(ints(b.DEC_tables[l].ipar)) icoef=$(nums(b.DEC_tables[l].icoef))" for l in b.decay_lists), "\n")
    out["jumps"] = join(("$(j.name) slot=$(j.slot === nothing ? "none" : j.slot) text=$(j.text) index=$(j.index) fired_by=$(ints(j.fired_by))\n" *
                         join((jump_text(op) for op in j.ops), "\n") for j in b.jump_specs), "\n")
    handlers = join(("$k: " * join(("$(h.rec.name)@$(h.off):$(h.action)" for h in b.event_handlers[k]), " ") for k in sort!(collect(keys(b.event_handlers)))), "\n")
    out["events"] = join(("$(e.slot) $(e.direction) $(e.name) $(e.index === nothing ? "" : K.describe_tuple(e.index))" for e in b.event_slots), "\n") * "\n--\n" * handlers
    out["memory"] = join(("$(m.kind) $(m.sign) $(m.starts_recording)" for m in b.MEM), "\n")
    if b.budget !== nothing
        out["budget"] = "base=$(b.budget.base) nfam=$(b.budget.nfam) families=$(join(b.budget.families, ",")) " *
                        join(("$(m.name):$(m.base):$(m.width):$(ints(m.fam_of))" for m in b.budget.members), " ")
    end
    return out
end

const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
cases = Any[]
function record(name, model; example=nothing)
    row = example === nothing ? K.JDict("name" => name, "model" => model) : K.JDict("name" => name, "example" => example)
    try
        b = K.build(K.Project(model))
        secs = sections(b)
        row["sections"] = K.JDict(k => fnv(v) for (k, v) in secs)
        isempty(DUMPS) || write(joinpath(DUMPS, "$name.builder.julia.txt"), join(("## $k\n$v" for (k, v) in secs), "\n"))
    catch e
        if e isa K.BuildError || e isa K.ValidationError
            row["error"] = e.message
        else
            println(stderr, "while building ", name)
            rethrow()
        end
    end
    push!(cases, row)
end

examples = joinpath(@__DIR__, "..", "..", "examples")
project_cases = K.parse_json(read(joinpath(@__DIR__, "..", "tests", "fixtures", "project.json"), String))["cases"]
for c in project_cases
    haskey(c, "hash") || continue
    if haskey(c, "example")
        record(c["name"], K.parse_json(read(joinpath(examples, c["example"] * ".json"), String)); example=c["example"])
    else
        record(c["name"], c["model"])
    end
end

# The models with transports of tests/fixtures/transport.json (tools/transport_fixtures.jl
# first) that are written out: each chain, then built.
for c in K.parse_json(read(joinpath(@__DIR__, "..", "tests", "fixtures", "transport.json"), String))["cases"]
    (haskey(c, "model") && haskey(c, "hash") && c["hash"] != c["json"]) || continue
    record("transport: " * c["name"], c["model"])
end

base() = K.parse_json("""{"name":"made","nuclides":["U-238","U-234","Th-230","Cs-137"],"simulation":{"end_time":1000,"mass_balance":true},
  "index_lists":[{"name":"Zones","indices":["a","b","c"]},{"name":"Half","sub_set_of":"Zones","indices":["a","b"]},
                 {"name":"Groups","mapping":{"to":"Zones","pairs":[{"from":"g1","to":"a"},{"from":"g1","to":"b"},{"from":"g2","to":"c"}]},"indices":["g1","g2"]}],
  "parameters":[{"name":"k","value":0.1,"index_lists":[]},{"name":"kz","value":1,"index_lists":["Zones"],"entries":[{"index":"b","value":2},{"index":"c","value":3}]},
                {"name":"kn","value":0.01,"entries":[{"index":"U-234","value":0.02}]}],
  "compartments":[{"name":"A","initial":"1e3 * kn"},{"name":"B","initial":"0","index_lists":["Radionuclides","Zones"]},{"name":"C","initial":"k","index_lists":[]}],
  "expressions":[{"name":"E","equation":"A * kn + time"},{"name":"Ez","equation":"B * kz","index_lists":["Radionuclides","Zones"]},
                 {"name":"Mixed","equation":"k","index_lists":["Radionuclides","Zones"],"entries":[{"index":{"Zones":"b"},"equation":"kz * 2"},{"index":{"Radionuclides":"U-234","Zones":"c"},"equation":"B[U-238][a] + Mixed[U-238][a]"}]},
                 {"name":"Self","equation":"if(time < 5, 1, Self2[b])","index_lists":["Zones"]},{"name":"Self2","equation":"kz + min(k, 3) ^ 2","index_lists":["Zones"]},
                 {"name":"OnHalf","equation":"kz * 10","index_lists":["Half"]},{"name":"ByGroup","equation":"1","index_lists":["Groups"],"entries":[{"index":"g2","equation":"5"}]},
                 {"name":"ReadsGroup","equation":"ByGroup + OnHalf[a]","index_lists":["Zones"]},
                 {"name":"PerComp","equation":"k","index_lists":["Compartments"],"entries":[{"index":"A","equation":"3"}]},
                 {"name":"PerTrans","equation":"2","index_lists":["Transfers"]}],
  "transfers":[{"name":"AB","from":"A","to":"B","rate":"kz * PerComp[_source_] * PerTrans","index_lists":["Radionuclides","Zones"],"sum_extra_indices":true},
               {"name":"BC","from":"B","to":"C","rate":"kn","index_lists":["Radionuclides","Zones"],"sum_extra_indices":true},
               {"name":"Bout","from":"B","rate":"1e-3 * PerComp[_source_]","multiply_by_donor":true},
               {"name":"Cin","to":"C","rate":"E","multiply_by_donor":false,"index_lists":["Radionuclides"],"sum_extra_indices":true}],
  "inflows":[{"name":"In","to":"A","rate":"1 + Tab"}],
  "lookups":[{"name":"Tab","points":[[0,0],[10,1],[100,5]],"index_lists":[]},{"name":"TabN","points":[[0,1],[5,2]],"entries":[{"index":"U-234","points":[[0,3],[5,4]]}]},
             {"name":"F","points":[[0,0],[1,1]],"argument":"x","interpolation":"extrapolate","index_lists":[]}],
  "index_reductions":[{"name":"Tot","target":"Ez","operation":"sum","index_lists":["Radionuclides"]},{"name":"P90","target":"Ez","operation":"percentile","percentile":90,"index_lists":["Zones"]}],
  "block_reductions":[{"name":"Agg","targets":["E","Tot"],"operation":"max"}],
  "functions":[{"name":"dbl","parameters":["x"],"equation":"2 * x + k"}]}""")
function with(f, name)
    m = base()
    f(m)
    record(name, m)
end
with(m -> nothing, "made")
with(m -> (m["simulation"]["mass_balance"] = false), "made without the audit")
with(m -> (push!(m["expressions"], K.JDict("name" => "UsesF", "equation" => "F(time) + dbl(TabN) + dbl(dbl(k))"))), "tables and functions called")
with(m -> (m["compartments"][1]["dydt"] = "-k * A"; m["compartments"][2]["entries"] = Any[K.JDict("index" => K.JDict("Zones" => "a"), "dydt" => "1")]), "explicit terms")
with(m -> (m["transfers"][1]["availability"] = K.JDict("scheme" => "limit", "limit" => "5 * kz")), "availability: limit")
with(m -> (m["transfers"][3]["availability"] = K.JDict("scheme" => "shared_limit", "limit" => "5", "over" => "Radionuclides", "basis" => "moles", "unavailable" => true);
           m["transfers"][3]["index_lists"] = Any["Radionuclides", "Zones"]), "availability: shared, in moles")
with(m -> (m["transfers"][3]["availability"] = K.JDict("scheme" => "shared_langmuir", "top" => "1", "bottom" => "kz", "over" => "Groups");
           m["transfers"][3]["index_lists"] = Any["Radionuclides", "Zones"]), "availability: shared by groups")
with(m -> (m["transfers"][1]["availability"] = K.JDict("scheme" => "langmuir", "top" => "1", "bottom" => "2")), "availability: langmuir")
with(m -> (m["min_maxes"] = Any[K.JDict("name" => "Mx", "target" => "A", "reset_trigger" => "Tr"), K.JDict("name" => "Mn", "target" => "C", "operation" => "min", "index_lists" => Any[], "start_trigger" => "Tr2[U-234]")];
           m["running_means"] = Any[K.JDict("name" => "Rm", "target" => "A", "stop_trigger" => "Tr")];
           m["snapshots"] = Any[K.JDict("name" => "Sn", "target" => "A", "trigger" => "Tr", "initial" => "k")];
           m["delays"] = Any[K.JDict("name" => "Dl", "target" => "C", "delay" => "5", "index_lists" => Any[])];
           m["triggers"] = Any[K.JDict("name" => "Tr", "first" => "time", "second" => "50", "index_lists" => Any[]),
                               K.JDict("name" => "Tr2", "first" => "A", "second" => "1", "direction" => "falling", "entries" => Any[K.JDict("index" => "Cs-137", "direction" => "both")])]), "blocks that remember")
with(m -> (m["waste_packages"] = Any[K.JDict("name" => "W", "inventory" => "1e6", "irf" => "0.1", "degradation_rate" => "1e-3", "failure" => "weibull", "fail_start" => "10", "fail_scale" => "100", "fail_shape" => "2", "packages" => 10),
                                     K.JDict("name" => "W2", "inventory" => "5", "failure" => "at", "fail_at" => "20 * k", "index_lists" => Any[]),
                                     K.JDict("name" => "W3", "inventory" => "5", "failure" => "uniform", "fail_from" => "1", "fail_to" => "9")];
           push!(m["transfers"], K.JDict("name" => "Rel", "from" => "W", "to" => "A", "rate" => "W", "multiply_by_donor" => false));
           m["events"] = Any[K.JDict("name" => "Quake", "timing" => "poisson", "rate" => "1e-3", "from" => "10", "actions" => Any[K.JDict("kind" => "fail", "block" => "W", "fraction" => "0.5"), K.JDict("kind" => "move", "from" => "A", "to" => "", "fraction" => "0.1")]),
                             K.JDict("name" => "Flood", "timing" => "at", "at" => "500", "actions" => Any[K.JDict("kind" => "move", "from" => "C", "fraction" => "k")])]), "packages and events")
with(m -> (m["triggers"] = Any[K.JDict("name" => "Tr", "first" => "A", "second" => "1")];
           m["events"] = Any[K.JDict("name" => "Ev", "timing" => "trigger", "trigger" => "Tr", "actions" => Any[K.JDict("kind" => "move", "from" => "A", "to" => "", "fraction" => "1")]),
                             K.JDict("name" => "Ev2", "timing" => "trigger", "trigger" => "Tr[U-234]", "actions" => Any[])]), "events set off by triggers")
with(m -> (m["index_lists"] = vcat(m["index_lists"], Any[K.JDict("name" => "Climate", "for_scenarios" => true, "indices" => Any["warm", "cold"])]);
           m["scenario"] = "cold"; m["parameters"][1]["index_lists"] = Any["Climate"]; m["parameters"][1]["entries"] = Any[K.JDict("index" => "cold", "value" => 0.5)]), "a scenario")
with(m -> (m["compartments"][2]["handle_decay"] = false; m["decay_unit"] = "mol"), "decay off, in moles")
with(m -> (m["index_lists"] = Any[K.JDict("name" => "Zones", "indices" => Any[K.JDict("name" => "a", "enabled" => false)])];
           m["expressions"] = Any[K.JDict("name" => "Ez", "equation" => "B * 2", "index_lists" => Any["Radionuclides", "Zones"])];
           m["parameters"] = m["parameters"][1:1]; m["index_reductions"] = Any[]; m["block_reductions"] = Any[];
           m["transfers"] = Any[K.JDict("name" => "AB", "from" => "A", "to" => "B", "rate" => "k", "index_lists" => Any["Radionuclides", "Zones"], "sum_extra_indices" => true)];
           m["inflows"] = Any[]; m["compartments"][1]["initial"] = "1"), "an empty list")
with(m -> (m["nuclides"] = Any["U-238", "U-234", "Th-230", "Ra-226", "Pb-210", "Po-210", "Cs-137"]), "a longer chain")

# --- numbers written with a unit ---------------------------------------------------------------------------
function units(m)
    m["parameters"][1]["unit"] = "m"
    m["parameters"][2]["unit"] = "mm"
    push!(m["parameters"], K.JDict("name" => "area", "value" => 2.5, "unit" => "m^2", "index_lists" => Any[]))
    push!(m["parameters"], K.JDict("name" => "rate", "value" => 0.3, "unit" => "1/year", "index_lists" => Any[]))
end
with(m -> (units(m); m["expressions"][1]["equation"] = "k + 25[cm] + A * 0"), "a unit: centimetres to metres")
with(m -> (units(m); m["expressions"][5]["equation"] = "kz + 0.01[m] + min(kz, 3[cm]) ^ 2"), "a unit: metres to millimetres, in a min")
with(m -> (units(m); m["expressions"][1]["equation"] = "if(k > 30[mm], area + 1e4[cm^2], area - 1[dm^2]) + A * 0"), "a unit: compared and chosen against")
with(m -> (units(m); m["expressions"][1]["equation"] = "k + 1[kg] + 2[] + A * 0"), "a unit: one that does not convert")
with(m -> (units(m); m["transfers"][2]["rate"] = "kn + 0 * (rate - 1e-3[1/year]) + 0 * (k - 5[um])"), "a unit: in a transfer's rate")
with(m -> (units(m); m["simulation"]["time_unit"] = "d"; m["expressions"][1]["equation"] = "time + 2[d] + k * 0 + 3[km] * 0 + A * 0"), "a unit: against the clock")
with(m -> (units(m); m["functions"][1]["equation"] = "2 * x + k + 10[cm]"; m["expressions"][1]["equation"] = "dbl(A) + dbl(1[mm])"), "a unit: in a function")

# --- what the builder refuses ----------------------------------------------------------------------------
with(m -> (m["expressions"][1]["equation"] = "Nope + 1"), "refused: unknown name")
with(m -> (m["expressions"][1]["equation"] = "nope(1)"), "refused: unknown function")
with(m -> (m["expressions"][1]["equation"] = "A +"), "refused: syntax")
with(m -> (m["expressions"][1]["equation"] = "E + 1"), "refused: reads itself")
with(m -> (m["expressions"][1]["equation"] = "Tot"), "refused: a circle")
with(m -> (m["expressions"][1]["equation"] = "B"), "refused: a dimension it cannot reach")
with(m -> (m["expressions"][1]["equation"] = "B[a][b]"), "refused: pinned twice")
with(m -> (m["expressions"][1]["equation"] = "B[zz]"), "refused: not an index")
with(m -> (m["expressions"][1]["equation"] = "A[U-238][a]"), "refused: too many indices")
with(m -> (m["expressions"][1]["equation"] = "OnHalf"; m["expressions"][1]["index_lists"] = Any["Zones"]), "refused: a sub-set that does not cover")
with(m -> (m["expressions"][1]["equation"] = "PerComp"), "refused: which compartment")
with(m -> (m["expressions"][1]["equation"] = "PerTrans"), "refused: which transfer")
with(m -> (m["expressions"][1]["equation"] = "PerComp[_source_]"), "refused: an end outside a transfer")
with(m -> (m["transfers"][3]["rate"] = "PerComp[_target_]"), "refused: an end outside the model")
with(m -> (m["expressions"][1]["equation"] = "F"), "refused: a table not called")
with(m -> (m["expressions"][1]["equation"] = "F(1, 2)"), "refused: a table called with two")
with(m -> (m["expressions"][1]["equation"] = "dbl(1, 2)"), "refused: a function's arguments")
with(m -> (m["functions"][1]["equation"] = "dbl(x)"), "refused: a function calling itself")
with(m -> (m["functions"][1]["equation"] = ""), "refused: a function with no body")
with(m -> (m["functions"][1]["equation"] = "x[a]"), "refused: an index of an argument")
with(m -> (m["compartments"][1]["initial"] = "A"), "refused: an initial reading a compartment")
with(m -> (m["compartments"][1]["initial"] = "E"), "refused: an initial reading the clock")
with(m -> (m["compartments"][1]["initial"] = "Nope"), "refused: an initial reading nothing")
with(m -> (m["parameters"][1]["value"] = "many"), "refused: a value that is no number")
with(m -> (m["transfers"][4]["multiply_by_donor"] = true), "refused: by a donor it has not")
with(m -> (m["transfers"][4]["availability"] = K.JDict("scheme" => "limit", "limit" => "1")), "refused: availability without a donor")
with(m -> (m["index_reductions"][1]["target"] = "C"), "refused: nothing to reduce over")
with(m -> (m["index_reductions"][1]["target"] = "Nope"), "refused: reducing nothing")
with(m -> (m["block_reductions"][1]["targets"] = Any["B"]), "refused: an aggregate out of reach")
with(m -> (m["snapshots"] = Any[K.JDict("name" => "Sn", "target" => "A", "trigger" => "E")]), "refused: not a discrete event")
with(m -> (m["snapshots"] = Any[K.JDict("name" => "Sn", "target" => "A", "trigger" => "E + 1")]), "refused: an expression for an event")
with(m -> (m["events"] = Any[K.JDict("name" => "Ev", "timing" => "trigger", "trigger" => "E", "actions" => Any[])]), "refused: not a trigger")
with(m -> (m["events"] = Any[K.JDict("name" => "Ev", "at" => "5", "actions" => Any[K.JDict("kind" => "move", "from" => "A", "to" => "B")])]), "refused: a move between different shapes")
with(m -> (m["expressions"][1]["enabled"] = false; m["expressions"][2]["equation"] = "E"), "refused: a disabled block read")
with(m -> (m["lookups"][1]["points"] = Any[]; m["lookups"][1]["entries"] = Any[]), "an empty table")

path = joinpath(@__DIR__, "..", "tests", "fixtures", "builder.json")
write(path, K.json_text(K.JDict("cases" => cases); indent=0))
println(path, ": ", length(cases), " models, ", count(c -> haskey(c, "error"), cases), " refused")
