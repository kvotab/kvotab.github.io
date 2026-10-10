# Renaming the keys an older project file uses (src/domain/keys.js).
#
# Keys are snake_case now; files written when they were camelCase, or before
# some collections were renamed, still open. The rename matters: an unknown
# key is ignored rather than reported, so a stale `multiplyByDonor: false`
# would quietly turn back into the default `true`.

const KEYS_PROJECT = Dict("halfLives" => "half_lives", "indexLists" => "index_lists")
const KEYS_COLLECTION = Dict(
    "sources" => "inflows", "discrete_events" => "triggers", "disruptions" => "events",
    "index_operations" => "index_reductions", "aggregates" => "block_reductions",
)
const KEYS_INDEX_LIST = Dict("forMaterials" => "for_contaminants", "for_materials" => "for_contaminants",
                             "forNuclides" => "for_nuclides", "subSetOf" => "sub_set_of")
const KEYS_SIMULATION = Dict("startTime" => "start_time", "endTime" => "end_time",
                             "outputPoints" => "output_points", "timeUnit" => "time_unit")
const OLD_SOLVER_IDS = Dict("ode15s" => "ndf", "ode15s_bdf" => "bdf", "ode23s" => "ros23", "ode45" => "dp45")
const KEYS_VIEW = Dict(
    "showExpressions" => "show_expressions", "showParameters" => "show_parameters", "showLookups" => "show_lookups",
    "showReductions" => "show_reductions", "showInfluences" => "show_influences", "showSinks" => "show_sinks",
    "connectionLabel" => "connection_label",
)
const KEYS_BLOCK = Dict(
    "indexLists" => "index_lists", "handleDecay" => "handle_decay", "multiplyByDonor" => "multiply_by_donor",
    "reset_event" => "reset_trigger", "start_event" => "start_trigger", "stop_event" => "stop_trigger",
    "event" => "trigger", "resetEvent" => "reset_trigger", "startEvent" => "start_trigger",
    "stopEvent" => "stop_trigger", "perNuclide" => "per_nuclide", "valuesByNuclide" => "values_by_nuclide",
)
const KEYS_ENTRY = Dict("multiplyByDonor" => "multiply_by_donor", "reset_event" => "reset_trigger",
                        "start_event" => "start_trigger", "stop_event" => "stop_trigger", "event" => "trigger")

"""Every collection of blocks in a project file."""
const COLLECTIONS = ("compartments", "expressions", "parameters", "lookups", "index_reductions",
                     "block_reductions", "min_maxes", "running_means", "snapshots", "delays", "triggers",
                     "farfields", "waste_packages", "events", "functions", "transfers", "inflows")

"""`obj` with its keys renamed, each where the old one stood; the new spelling wins."""
function rename_keys(obj, mapping::Dict{String,String})
    obj isa AbstractDict || return obj
    out = JDict()
    for (k, v) in obj
        to = get(mapping, k, nothing)
        if to === nothing
            out[k] = v
            continue
        end
        haskey(obj, to) && continue
        out[to] = v
    end
    return out
end

function _migrate_farfield_targets(raw)
    farfields = get(raw, "farfields", nothing)
    farfields isa AbstractVector || return raw
    moved = Any[]
    kept = Any[]
    for f in farfields
        to = f isa AbstractDict ? get(f, "to", nothing) : nothing
        if !(f isa AbstractDict) || to === nothing || to == ""
            push!(kept, f)
            continue
        end
        g = JDict(k => v for (k, v) in f if k != "to")
        push!(kept, g)
        name = get(f, "name", nothing)
        t = JDict()
        js_truthy(get(f, "system", nothing)) && (t["system"] = f["system"])
        t["name"] = js_truthy(name) ? "$(name)_release" : "release"
        t["from"] = name
        t["to"] = js_str(to)
        t["rate"] = js_truthy(name) ? name : "0"
        t["multiply_by_donor"] = false
        push!(moved, t)
    end
    isempty(moved) && return raw
    out = JDict(raw)
    out["farfields"] = kept
    out["transfers"] = Any[something(get(raw, "transfers", nothing), Any[])..., moved...]
    return out
end

function _migrate_farfield_defaults(raw)
    farfields = get(raw, "farfields", nothing)
    farfields isa AbstractVector || return raw
    changed = false
    out_f = Any[]
    for f in farfields
        if !(f isa AbstractDict)
            push!(out_f, f)
            continue
        end
        missing_keys = [k for k in keys(FARF_LEGACY) if !haskey(f, k)]
        if isempty(missing_keys)
            push!(out_f, f)
            continue
        end
        changed = true
        g = JDict(f)
        for k in missing_keys
            g[k] = FARF_LEGACY[k]
        end
        push!(out_f, g)
    end
    changed || return raw
    out = JDict(raw)
    out["farfields"] = out_f
    return out
end

"""
    migrate_keys(raw) -> JDict

A copy of `raw` with every older key renamed to the current one; also moves
a far-field path's old `to` into a release transfer, renames the built-in
index lists written under their old names, and splits a single material list
into the catalogue and the radionuclides it carries.
"""
function migrate_keys(raw)
    raw isa AbstractDict || return raw
    out = rename_keys(rename_keys(jcopy(raw), KEYS_PROJECT), KEYS_COLLECTION)
    if get(out, "index_lists", nothing) isa AbstractVector
        out["index_lists"] = Any[rename_keys(l, KEYS_INDEX_LIST) for l in out["index_lists"]]
    end
    out = split_material_roles(rename_built_in_lists(_migrate_farfield_defaults(_migrate_farfield_targets(out))))
    sim = get(out, "simulation", nothing)
    if sim isa AbstractDict
        sim = rename_keys(sim, KEYS_SIMULATION)
        solver = get(sim, "solver", nothing)
        if solver isa AbstractString && haskey(OLD_SOLVER_IDS, solver)
            sim["solver"] = OLD_SOLVER_IDS[solver]
        end
        if get(sim, "solver", nothing) == "bdf"
            # The plain BDFs are the NDF with its switch on.
            sim["solver"] = "ndf"
            sim["bdf"] = true
        end
        out["simulation"] = sim
    end
    get(out, "view", nothing) isa AbstractDict && (out["view"] = rename_keys(out["view"], KEYS_VIEW))
    for key in COLLECTIONS
        blocks = get(out, key, nothing)
        blocks isa AbstractVector || continue
        renamed = Any[]
        for b in blocks
            if !(b isa AbstractDict)
                push!(renamed, b)
                continue
            end
            nb = rename_keys(b, KEYS_BLOCK)
            if get(nb, "entries", nothing) isa AbstractVector
                nb["entries"] = Any[rename_keys(e, KEYS_ENTRY) for e in nb["entries"]]
            end
            push!(renamed, nb)
        end
        out[key] = renamed
    end
    return out
end
