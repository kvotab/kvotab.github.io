# The editing API against the Python package's: the same edits make the same
# file, byte for byte, refuse what it refuses with the same words, and return
# what it returns.
#
# tools/edit_fixtures.py writes the fixtures -- made-up models and every
# bundled example, each with a list of edits applied through the Python
# package, and after each the model's to_json() text, the refusal or what the
# call returned:
#
#     python3 tools/edit_fixtures.py DIR
#     KOMPARTMENT_EDIT_FIXTURES=DIR julia --project test/model/edit.jl
#
# The checks that need no fixtures run without them.

module EditTests

using Test
using Dates
using Kompartment
const K = Kompartment

const DIR = get(ENV, "KOMPARTMENT_EDIT_FIXTURES", "")

# --- fixture-free checks ---------------------------------------------------------------------------------

function two_boxes()
    m = K.new_model("Two boxes")
    K.add_nuclides!(m, ["Cs-137", "Sr-90"])
    K.add_compartment!(m, "Soil"; initial="1e10")
    K.add_compartment!(m, "Well")
    K.add_parameter!(m, "k", 0.05; unit="1/year")
    K.add_transfer!(m, "Soil", "Well"; rate="k")
    return m
end

@testset "editing a model" begin
    @testset "building" begin
        m = two_boxes()
        @test m.nuclides == ["Cs-137", "Sr-90"] && m.materials == ["Cs-137", "Sr-90"]
        @test m["Soil"] isa K.Compartment && m["Soil"].index_lists == ["Radionuclides"]
        @test m["k"].index_lists == []
        t = m["Soil_Well"]
        @test t isa K.Transfer
        @test (t.source, t.target, t.rate, t.multiply_by_donor, t.unit) == ("Soil", "Well", "k", true, "1/year")
        @test K.state_count(m) == 4
        @test K.check(m) == String[]
        @test K.get_block(m, "Nothing") === nothing
        @test_throws K.EditError m["Nothing"]
        @test "Soil" in m && !("Nothing" in m)
        @test K.block_names(m; kind="compartment") == ["Soil", "Well"]
        @test [b.name for b in K.compartments(m)] == ["Soil", "Well"]
        # Default names follow the application.
        m2 = K.new_model()
        @test K.add_compartment!(m2).name == "C"
        @test K.add_compartment!(m2).name == "C1"
        @test K.add_transfer!(m2, "C", "C1").name == "C_C1"
        @test K.add_transfer!(m2, "C", "C1").name == "C_C11"
        @test K.add_transfer!(m2, "C", nothing).name == "T"
        # Names are checked, and a failed add leaves nothing behind.
        before = K.to_json(m)
        for bad in ("1abc", "a-b", "exp", "Soil", "")
            @test_throws K.EditError K.add_parameter!(m, bad, 1)
        end
        err = try
            K.add_parameter!(m, "q", "not a number")
        catch e
            e
        end
        @test err isa K.EditError && err.message == "q: 'not a number' is not a number, and a parameter's value is one"
        @test K.to_json(m) == before
    end

    @testset "values per index" begin
        m = two_boxes()
        soil = m["Soil"]
        K.set_value!(soil, "5e9"; at="Cs-137")
        K.set_entry!(soil, "Sr-90"; initial="2", abstol=1e-3)
        @test K.value_at(soil, "Cs-137") == "5e9"
        @test K.value_at(soil, Dict("Radionuclides" => "Sr-90")) == "2"
        @test K.value_at(soil; at="Sr-90", key="abstol") == 1e-3
        @test K.value_at(soil, (Radionuclides="Sr-90",)) == "2"
        @test soil.value == "1e10"
        K.clear_value!(soil, "Cs-137")
        @test K.value_at(soil, "Cs-137") == "1e10"
        @test_throws K.EditError K.set_value!(soil, "1"; at="U-238")
        @test length(K.combinations(soil)) == 2
        soil.initial = 3
        @test soil.initial == "3"
        @test_throws K.EditError (m["Soil_Well"].dash = "wavy")
        # Distributions, from the module that makes them.
        dist = K.distributions
        m["k"].distribution = dist.log_triangular(0.01, 0.1, 0.05)
        @test m["k"].distribution["kind"] == "logt"
        @test_throws K.DistributionError dist.uniform(2, 1)
        K.set_dimensions!(m, "k", ["Radionuclides"])
        K.set_distribution!(m["k"], "norm"; at="Cs-137", mean=0.05, sd=0.01)
        @test K.distribution_at(m["k"], "Cs-137")["params"] == K.JDict("mean" => 0.05, "sd" => 0.01)
        @test occursin("log-triangular", dist.describe(m["k"].distribution))
    end

    @testset "edits that reach across the model" begin
        m = two_boxes()
        K.add_expression!(m, "Conc", "Soil * 2 + Soil_Well"; index_lists=[])
        @test K.rename_block!(m, "Soil", "Topsoil") == "Topsoil"
        @test m["Conc"].equation == "Topsoil * 2 + Soil_Well"
        @test m["Soil_Well"].source == "Topsoil"
        K.add_system!(m, "Near")
        @test K.move_block!(m, "Topsoil", "Near") == "Near.Topsoil"
        @test m["Near.Soil_Well"].system == "Near"
        @test m["Conc"].equation == "Near.Topsoil * 2 + Near.Soil_Well"
        err = try
            K.delete_block!(m, "Near.Topsoil")
        catch e
            e
        end
        @test err isa K.EditError && err.detail == ["Conc"]
        @test K.delete_blocks!(m, ["Near.Topsoil", "Conc"]) == ["Near.Topsoil", "Conc", "Near.Soil_Well"]
        @test K.rename_system!(m, "Near", "Nearfield") == "Nearfield"
        @test m.systems == ["Nearfield"]
        @test K.delete_system!(m, "Nearfield") == ""
        @test m.systems == String[]
    end

    @testset "index lists, decay, the simulation and the view" begin
        m = two_boxes()
        l = K.add_index_list!(m, "Object", ["Lake", "Mire"])
        K.add_parameter!(m, "Kd", 0; index_lists=["Radionuclides", "Object"])
        K.set_value!(m["Kd"], 0.03; at=("Cs-137", "Lake"))
        K.rename_index!(l, "Lake", "Pond")
        @test K.overrides(m["Kd"]) == [(K.JDict("Radionuclides" => "Cs-137", "Object" => "Pond"), 0.03)]
        # An index given as a Dict, which keeps no order, is written in the block's order of dimensions.
        e = K.set_entry!(m["Kd"], Dict("Object" => "Mire", "Radionuclides" => "Sr-90"); value=0.5)
        @test collect(keys(e["index"])) == ["Radionuclides", "Object"]
        @test K.value_at(m["Kd"], (Object="Mire", Radionuclides="Sr-90")) == 0.5
        @test_throws K.EditError K.delete_index_list!(m, "Object")
        K.add_nuclides!(m, ["U-238", "U-234"])
        @test K.half_life(m, "U-238") > 4e9
        @test_throws K.EditError K.add_decay_pair!(m, "U-234", "U-238")
        m.decay_unit = "mol"
        @test m["Soil"].unit == "mol" && m.decay_unit == "mol"
        sim = m.simulation
        sim.end_time = 1e6
        K.update!(sim; rtol=1e-6, solver="radau5")
        @test (sim.end_time, sim.rtol, sim.solver) == (1e6, 1e-6, "radau5")
        @test_throws K.EditError (sim.solver = "euler")
        @test_throws K.EditError (sim["max_order"] = 7)
        @test K.simulation(m) isa AbstractDict && K.simulation(m)["solver"] == "radau5"
        m.view.show_parameters = true
        @test m.view.show_parameters == true
        @test_throws K.EditError (m.view.connection_label = "bold")
        m.name = "  Renamed "
        @test m.name == "Renamed" && m.raw["name"] == "Renamed"
        c = copy(m)
        K.rename_block!(c, "Soil", "Ground")
        @test "Soil" in m && !("Soil" in c)
    end
end

# --- the Python package's edits, replayed -----------------------------------------------------------------

"""A value from the fixture as the Julia API is given it."""
function dec(v, m)
    if v isa AbstractDict
        if length(v) == 1
            k = first(keys(v))
            x = v[k]
            k == "\$float" && return x == "inf" ? Inf : x == "-inf" ? -Inf : NaN
            k == "\$tuple" && return Tuple(dec(y, m) for y in x)
            k == "\$block" && return K.block(m, x)
            if k == "\$dist"
                fn, args, kw = x
                return getfield(K.distributions, Symbol(fn))(dec(args, m)...; (Symbol(a) => dec(b, m) for (a, b) in kw)...)
            end
        end
        return K.JDict(String(k) => dec(x, m) for (k, x) in v)
    end
    v isa AbstractVector && return Any[dec(x, m) for x in v]
    return v
end

"""What a call returned, as the fixture writes Python's."""
enc(x::K.Block) = K.JDict("\$block" => K.qualified_name(x.raw))
enc(x::K.IndexListView) = K.JDict("\$list" => x.name)
enc(x::K.Shape) = K.JDict("\$shape" => x.id)
enc(x::K.OutputSeries) = K.JDict("\$series" => enc(x.raw))
enc(x::K.SimulationView) = K.JDict("\$simulation" => enc(x.raw))
enc(x::K.ViewSettings) = K.JDict("\$view" => enc(K.to_dict(x)))
enc(x::K.Model) = K.JDict("\$model" => x.name)
enc(x::DateTime) = K.JDict("\$time" => K.model_stamp(x))
enc(x::AbstractDict) = K.JDict(string(k) => enc(v) for (k, v) in x)
enc(x::Union{AbstractVector,Tuple}) = Any[enc(v) for v in x]
enc(x) = x

const MODEL_FN = Dict{String,Any}("get" => K.get_block, "names" => K.block_names, "copy" => copy,
                                  "add_source" => K.add_source!, "remove_nuclide" => K.remove_nuclide!)
const BLOCK_FN = Dict{String,Any}(
    "index" => K.entry_index, "rename" => K.rename_block!, "move_to" => K.move_block!, "delete" => K.delete_block!,
    "references" => K.references_to, "get" => (b, k, d=nothing) -> get(b, k, d), "keys" => keys,
    "set_point_distribution" => (b, i, kind; kw...) -> K.set_point_distribution!(b, i + 1, kind; kw...))
const LIST_FN = Dict{String,Any}("set_enabled" => K.set_index_enabled!, "rename" => K.rename_index_list!,
                                 "delete" => K.delete_index_list!, "users" => K.index_list_users)
const SIM_FN = Dict{String,Any}(
    "set" => (s, k, v) -> (s[k] = v; nothing), "get" => (s, k, d=nothing) -> get(s, k, d),
    "remove_output_series" => (s, i) -> K.remove_output_series!(s, i + 1))
const VIEW_FN = Dict{String,Any}("set" => K.update!)
const SHAPE_FN = Dict{String,Any}("move_to" => K.move_shape!, "delete" => K.remove_shape!)
"""What Python returns nothing from and Julia returns the thing changed from."""
const NO_RESULT = Set([("s", "update"), ("v", "set"), ("sh", "update")])

function api(name::String, table)
    haskey(table, name) && return table[name]
    s = Symbol(name * "!")
    isdefined(K, s) && return getfield(K, s)
    return getfield(K, Symbol(name))
end

"""The Julia property for a Python attribute."""
prop(attr) = attr == "end" ? :stop : Symbol(attr)

"""Applies one recorded operation; returns `(result, compare_result)`."""
function apply(m, op)
    tag = op[1]
    if tag in ("m", "b", "l", "s", "v", "sh", "d")
        if tag == "m"
            target, table, method, args, kw = m, MODEL_FN, op[2], op[3], op[4]
        elseif tag == "b"
            target, table, method, args, kw = K.block(m, op[2]), BLOCK_FN, op[3], op[4], op[5]
        elseif tag == "l"
            target, table, method, args, kw = K.index_list(m, op[2]), LIST_FN, op[3], op[4], op[5]
        elseif tag == "s"
            target, table, method, args, kw = m.simulation, SIM_FN, op[2], op[3], op[4]
        elseif tag == "v"
            target, table, method, args, kw = m.view, VIEW_FN, op[2], op[3], op[4]
        elseif tag == "sh"
            target = only(s for s in K.shapes(m) if s.id == op[2])
            table, method, args, kw = SHAPE_FN, op[3], op[4], op[5]
        else
            target, table, method, args, kw = nothing, nothing, op[2], op[3], op[4]
        end
        a = dec(args, m)
        k = [Symbol(x) => dec(y, m) for (x, y) in kw]
        if tag == "d"
            return getfield(K.distributions, Symbol(method))(a...; k...), true
        end
        f = api(method, table)
        return f(target, a...; k...), !((tag, method) in NO_RESULT)
    end
    if tag == "m="
        setproperty!(m, Symbol(op[2]), dec(op[3], m))
    elseif tag == "m?"
        return getproperty(m, Symbol(op[2])), true
    elseif tag == "b="
        setproperty!(K.block(m, op[2]), Symbol(op[3]), dec(op[4], m))
    elseif tag == "b?"
        return getproperty(K.block(m, op[2]), Symbol(op[3])), true
    elseif tag == "b[]="
        K.block(m, op[2])[op[3]] = dec(op[4], m)
    elseif tag == "l="
        setproperty!(K.index_list(m, op[2]), Symbol(op[3]), dec(op[4], m))
    elseif tag == "l?"
        return getproperty(K.index_list(m, op[2]), Symbol(op[3])), true
    elseif tag == "s="
        setproperty!(m.simulation, Symbol(op[2]), dec(op[3], m))
    elseif tag == "s?"
        return getproperty(m.simulation, Symbol(op[2])), true
    elseif tag == "o="
        setproperty!(m.simulation.output_series[op[2]+1], prop(op[3]), dec(op[4], m))
    elseif tag == "o?"
        return getproperty(m.simulation.output_series[op[2]+1], prop(op[3])), true
    elseif tag == "v="
        setproperty!(m.view, Symbol(op[2]), dec(op[3], m))
    elseif tag == "v?"
        return getproperty(m.view, Symbol(op[2])), true
    elseif tag == "r="
        m.raw[op[2]] = dec(op[3], m)
    elseif tag == "sh?"
        return getproperty(only(s for s in K.shapes(m) if s.id == op[2]), Symbol(op[3])), true
    else
        error("unknown operation $(repr(op))")
    end
    return nothing, false
end

"""Python's message for a refusal of the point a Julia position counts from 1."""
expected_message(op, msg) =
    (op[1] == "b" && op[3] == "set_point_distribution") ?
    replace(msg, r"has no point (-?\d+)$" => s -> "has no point $(parse(Int, match(r"-?\d+$", s).match) + 1)") : msg

"""
Whether Julia's refusal says what Python's does. Deleting several parts of a
transport at once is refused naming one of them: Python names whichever its
set yields first, which changes with the process's string hashes
(PYTHONHASHSEED), and Julia the first in the order they were given.
"""
function same_refusal(mine, theirs)
    mine == theirs && return true
    guard = r"^'[^']*' is the transport (begin|end|number) of '[^']*', and a transport is a chain from its Begin to its End\. "
    return occursin(guard, mine) && occursin(guard, theirs)
end

"""Where two texts first part, for the log."""
function first_difference(got, want)
    gl, wl = split(got, '\n'), split(want, '\n')
    k = findfirst(i -> i > length(gl) || i > length(wl) || gl[i] != wl[i], 1:max(length(gl), length(wl)))
    k === nothing && return nothing
    return "line $k: julia $(k <= length(gl) ? repr(gl[k]) : "<none>") / python $(k <= length(wl) ? repr(wl[k]) : "<none>")"
end

function replay(path)
    case = K.parse_json(read(path, String))
    name = case["name"]
    problems = String[]
    start = case["start"]
    if haskey(start, "new")
        m = K.new_model(start["new"]...)
        m.raw["created"] = start["created"]
    else
        m = K.Model(start["model"])
    end
    text = K.to_json(m)
    if text != case["initial"]
        push!(problems, "$name: opened differently, $(first_difference(text, case["initial"]))")
        return problems, 0
    end
    want_text = case["initial"]
    done = 0
    for (k, step) in enumerate(case["steps"])
        op = step["op"]
        where_ = "$name step $k $(K.json_text(op; indent=0))"
        err = step["error"]
        got = nothing
        thrown = nothing
        compare = false
        try
            got, compare = apply(m, op)
        catch e
            thrown = e
        end
        if err === nothing
            if thrown !== nothing
                push!(problems, "$where_: Julia refused what Python did not: $(sprint(showerror, thrown))")
            elseif compare && step["result"] !== nothing
                mine = K.json_text(enc(got); indent=0)
                mine == step["result"] || push!(problems, "$where_: returned $mine, Python $(step["result"])")
            end
        else
            cls, msg = err["class"], expected_message(op, err["message"])
            if thrown === nothing
                push!(problems, "$where_: Python refused ($cls: $msg), Julia did not")
            elseif cls == "EditError" || cls == "DistributionError"
                ok = (cls == "EditError" ? thrown isa K.EditError : thrown isa K.DistributionError) &&
                     same_refusal(thrown.message, msg)
                ok || push!(problems, "$where_: refused with $(sprint(showerror, thrown)); Python $cls: $msg")
            end
        end
        step["json"] === nothing || (want_text = step["json"])
        text = K.to_json(m)
        if text != want_text
            push!(problems, "$where_: the model differs, $(first_difference(text, want_text))")
            return problems, done
        end
        done += 1
    end
    return problems, done
end

if isempty(DIR) || !isdir(DIR)
    @info "KOMPARTMENT_EDIT_FIXTURES is not set: the edits are not replayed against Python's (tools/edit_fixtures.py writes them)"
else
    @testset "edits replayed against the Python package" begin
        files = sort(filter(f -> endswith(f, ".json"), readdir(DIR; join=true)))
        @test !isempty(files)
        total = 0
        failed = String[]
        for f in files
            problems, done = replay(f)
            total += done
            append!(failed, problems)
            @test isempty(problems)
        end
        for p in first(failed, 40)
            println(p)
        end
        println("Edits replayed: $(length(files)) cases, $total operations, $(length(failed)) problems")
    end
end

end # module
