# Editing a model (the Python package's model.py): blocks reached by name,
# added with the application's defaults, renamed, moved and deleted with
# every reference following; index lists, materials and decay; sub-systems
# and transports; the diagram, derived outputs and reviews.
#
#     m = new_model("Two boxes")
#     add_nuclides!(m, ["Cs-137", "Sr-90"])
#     add_compartment!(m, "Soil", "1e10")
#     add_compartment!(m, "Well")
#     add_parameter!(m, "k", 0.05; unit="1/year")
#     add_transfer!(m, "Soil", "Well", "k")
#     rename_block!(m, "Soil", "Topsoil")
#     save(m, "two-boxes.json")
#
# The edits that reach across the model follow the change through every
# reference the way the application's editor (src/domain/edit.js) does, and
# refuse the ones it refuses, with an `EditError` that says why. What
# follows from the model -- a transfer's unit and dimensions, a transport's
# dimensions -- is brought up to date by `settle!`, which runs whenever the
# model is written out or checked; the edits that depend on it run the part
# they need on the spot.

const _ED_HOLDS_INVENTORY = ("compartment", "farfield", "waste_package")
const _ED_RELEASING = ("farfield", "waste_package")
"""The equations each block that remembers writes, and the triggers it names."""
const _ED_RECORDER_KINDS = ("min_max", "running_mean", "snapshot", "delay", "trigger")
const _ED_RECORDER_EQUATIONS = Dict(
    "min_max" => ("target",), "running_mean" => ("target",), "snapshot" => ("target", "initial"),
    "delay" => ("target", "delay"), "trigger" => ("first", "second"))
const _ED_RECORDER_TRIGGERS = Dict(
    "min_max" => ("reset_trigger", "start_trigger", "stop_trigger"),
    "running_mean" => ("reset_trigger", "start_trigger", "stop_trigger"),
    "snapshot" => ("trigger",), "delay" => (), "trigger" => ())
const _ED_RECORDER_COLLECTION = Dict(
    "min_max" => "min_maxes", "running_mean" => "running_means", "snapshot" => "snapshots", "delay" => "delays",
    "trigger" => "triggers")
"""The name each kind is given when none is."""
const _ED_DEFAULT_NAME = Dict(
    "compartment" => "C", "expression" => "E", "parameter" => "p", "lookup" => "L", "index_reduction" => "Total",
    "block_reduction" => "Sum", "function" => "Func", "min_max" => "Peak", "running_mean" => "Mean",
    "snapshot" => "Snapshot", "delay" => "Delayed", "trigger" => "Trigger", "inflow" => "In",
    "farfield" => "Farfield", "waste_package" => "Packages", "event" => "Event")
const _ED_DERIVED_KINDS = ("max", "min", "time_of_max", "at_time", "integral", "period_mean", "period_sum",
                           "period_change", "period_rate")
const _ED_PERIOD_KINDS = ("period_mean", "period_sum", "period_change", "period_rate")
const _ED_SHAPE_COLORS = ("slate", "blue", "teal", "green", "olive", "amber", "orange", "red", "purple", "brown")
const _ED_SHAPE_DASHES = ("solid", "dashed", "dotted")
const _ED_SHAPE_TEXT_FONTS = ("sans", "scribble", "serif", "mono")
const _ED_SHAPE_TEXT_ALIGNS = ("left", "center", "right")
const _ED_NOT_REVIEWED = ("x", "y", "w", "h", "shape", "colour", "color", "label", "collapsed", "comment", "note",
                          "notes", "qa")

_edge_key(name, view=nothing) = view === nothing ? _EDGE_PREFIX * name : "$(_EDGE_PREFIX)$(name)@$(view)"

"""`(x, y)` from a pair, a vector or a dictionary with `x` and `y` (`_position_of`)."""
function _position_of(xy)
    if xy isa AbstractDict
        x, y = _ed_pyfloat(xy["x"]), _ed_pyfloat(xy["y"])
    else
        a = collect(Any, xy)
        length(a) == 2 || throw(ArgumentError("a position is (x, y), not $(_py_repr(xy))"))
        x, y = _ed_pyfloat(a[1]), _ed_pyfloat(a[2])
    end
    (x === nothing || y === nothing) && throw(ArgumentError("a position is two numbers, not $(_py_repr(xy))"))
    return (x, y)
end

_list_of(v) = collect(Any, _py_iter(v))

# --- making one -----------------------------------------------------------------------------------------

"""
    new_model(name="New model", description="") -> Model

A new, empty model, as the application's *New* makes one: dated now, 0 to
1000 years on a log grid, the default solver and tolerances, and the two
material lists, empty.
"""
function new_model(name="New model", description="")
    sim = JDict(SIMULATION_DEFAULTS)
    sim["end_time"] = 1000
    raw = JDict("name" => name, "description" => description, "created" => model_stamp(), "simulation" => sim,
                "parameters" => Any[], "compartments" => Any[], "transfers" => Any[], "expressions" => Any[],
                "inflows" => Any[])
    return Model(raw)
end

"""A new, empty model called `New model` (see `new_model`)."""
Model() = new_model()

"""An independent copy of a model, as it is (not opened again)."""
Base.copy(m::Model) = Model(jcopy(m.raw), m.path, nothing)

"""The project dictionary, settled (see `settle!`), as a copy."""
function to_dict(m::Model)
    settle!(m.raw)
    return jcopy(m.raw)
end

"""
    settle!(m) -> Vector{String}

Brings what follows from the model up to date, as the application does after
every edit (see `settle!(raw)`); runs by itself whenever the model is written
out or checked. Returns the names of the blocks it changed.
"""
settle!(m::Model) = settle!(m.raw)

# --- blocks by name -------------------------------------------------------------------------------------

"""The block of that qualified name, or `nothing`."""
function get_block(m::Model, name)
    hit = _ed_find(m, _name_arg(name))
    return hit === nothing ? nothing : _view_of(m, hit[1], hit[2])
end

"""The block of that qualified name (`m["Soil"]`); an `EditError` when there is none."""
function block(m::Model, name)
    b = get_block(m, name)
    b === nothing && throw(EditError("No block named '$(_py_str(_name_arg(name)))'"))
    return b
end

Base.getindex(m::Model, name::AbstractString) = block(m, name)
Base.in(name::AbstractString, m::Model) = _ed_find(m, name) !== nothing
Base.haskey(m::Model, name::AbstractString) = _ed_find(m, name) !== nothing

"""
    blocks(m, kind=nothing, system=nothing, deep=true)
    blocks(m; kind, system, deep)

Every block, or those of one kind (`"compartment"`, `"transfer"`, ...), or
those in one sub-system (`deep`: and in the sub-systems inside it).
"""
function blocks(m::Model, kind_=nothing, system_=nothing, deep_=true; kind=kind_, system=system_, deep=deep_)
    kind isa Symbol && (kind = String(kind))
    if kind !== nothing && !(kind in _BK_KINDS)
        throw(EditError("'$(_py_str(kind))' is not a kind of block ($(join(_BK_KINDS, ", ")))"))
    end
    out = Block[]
    for c in COLLECTIONS
        (kind !== nothing && _BK_SINGULAR[c] != kind) && continue
        for b in _py_iter(get(m.raw, c, nothing))
            b isa AbstractDict || continue
            if system !== nothing
                home = system_of(b)
                (py_truthy(deep) ? is_within(home, system) : home == system) || continue
            end
            push!(out, _view_of(m, c, b))
        end
    end
    return out
end

"""The qualified names of every block, or of one kind."""
block_names(m::Model, kind_=nothing; kind=kind_) = String[qualified_name(b.raw) for b in blocks(m; kind)]

_collection_views(m::Model, collection::String) =
    Block[_view_of(m, collection, b) for b in _py_iter(get(m.raw, collection, nothing)) if b isa AbstractDict]

"""Every compartment."""
compartments(m::Model) = _collection_views(m, "compartments")
"""Every transfer."""
transfers(m::Model) = _collection_views(m, "transfers")
"""Every inflow (source term)."""
inflows(m::Model) = _collection_views(m, "inflows")
"""Every parameter."""
parameters(m::Model) = _collection_views(m, "parameters")
"""Every expression."""
expressions(m::Model) = _collection_views(m, "expressions")
"""Every lookup table."""
lookups(m::Model) = _collection_views(m, "lookups")
"""Every index reduction."""
index_reductions(m::Model) = _collection_views(m, "index_reductions")
"""Every block reduction (aggregate)."""
block_reductions(m::Model) = _collection_views(m, "block_reductions")
"""Every function."""
functions(m::Model) = _collection_views(m, "functions")
"""Every min/max."""
min_maxes(m::Model) = _collection_views(m, "min_maxes")
"""Every running mean."""
running_means(m::Model) = _collection_views(m, "running_means")
"""Every snapshot."""
snapshots(m::Model) = _collection_views(m, "snapshots")
"""Every delay."""
delays(m::Model) = _collection_views(m, "delays")
"""Every trigger."""
triggers(m::Model) = _collection_views(m, "triggers")
"""Every far-field path."""
farfields(m::Model) = _collection_views(m, "farfields")
"""Every set of waste packages."""
waste_packages(m::Model) = _collection_views(m, "waste_packages")
"""Every disruptive event."""
events(m::Model) = _collection_views(m, "events")

# --- the model's own name, description and settings ----------------------------------------------------

"""The model's name: shown in the header and used for the file name."""
function model_name(m::Model)
    s = strip(_py_or_text(get(m.raw, "name", nothing)))
    return isempty(s) ? "Untitled model" : String(s)
end
set_model_name!(m::Model, value) = (m.raw["name"] = String(strip(_py_or_text(value))); m)

"""Free text: what the model is and where it came from."""
model_description(m::Model) = _py_or_text(get(m.raw, "description", nothing))
set_model_description!(m::Model, value) = (m.raw["description"] = _py_or_text(value); m)

"""Who wrote the model, or `""`."""
model_author(m::Model) = String(strip(_py_or_text(get(m.raw, "author", nothing))))
function set_model_author!(m::Model, value)
    text = String(strip(_py_or_text(value)))
    isempty(text) ? delete!(m.raw, "author") : (m.raw["author"] = text)
    header_first!(m.raw)
    return m
end

"""Diagram geometry, keyed by qualified name, live (made when the model has none)."""
function layout(m::Model)
    get(m.raw, "layout", nothing) isa AbstractDict || (m.raw["layout"] = JDict())
    return m.raw["layout"]
end

# --- what follows from the model ------------------------------------------------------------------------

"""
    derived_unit(m, block) -> String

The unit a transfer or an inflow carries, worked out from the model: `1/<time>`
for a rate coefficient, the donor's unit per time for an absolute flux, the
receiver's per time for an inflow; `""` when it cannot be known.
"""
function derived_unit(m::Model, b)
    b = b isa Block ? b : block(m, b)
    k = _kind_name(b)
    k == "inflow" && return _ed_inflow_unit(m, b.raw)
    k == "transfer" && return _ed_transfer_unit(m, b.raw)
    throw(EditError("A $(_spaced(k))'s unit is its own, not worked out"))
end

function _ed_unit_of_compartment(m::Model, name)
    name === nothing && return ""
    cs = Any[c for c in _py_iter(get(m.raw, "compartments", nothing)) if c isa AbstractDict]
    c = findfirst_value(x -> qualified_name(x) == name, cs)
    c === nothing && (c = findfirst_value(x -> get(x, "name", nothing) == name, cs))
    return c === nothing ? "" : String(strip(_js_string(get(c, "unit", nothing))))
end

function _ed_transfer_unit(m::Model, raw::AbstractDict)
    t = _norm_time_unit(_N(m))
    get(raw, "multiply_by_donor", nothing) !== false && return "1/$t"
    paths = Any[f for f in _py_iter(get(m.raw, "farfields", nothing)) if f isa AbstractDict]
    fr = get(raw, "from", nothing)
    path = findfirst_value(f -> qualified_name(f) == fr, paths)
    path === nothing && (path = findfirst_value(f -> get(f, "name", nothing) == fr, paths))
    path !== nothing && return String(strip(_js_string(get(path, "unit", nothing))))
    u = _ed_unit_of_compartment(m, fr !== nothing ? fr : get(raw, "to", nothing))
    return isempty(u) ? "" : _per(u, t)
end

function _ed_inflow_unit(m::Model, raw::AbstractDict)
    u = _ed_unit_of_compartment(m, get(raw, "to", nothing))
    return isempty(u) ? "" : _per(u, _norm_time_unit(_N(m)))
end

_ed_sync_derived_units!(m::Model) = _sync_derived_units!(_N(m))
_ed_sync_transfer_dimensions!(m::Model) = _sync_transfer_dimensions!(_N(m))

# --- index lists ----------------------------------------------------------------------------------------

"""What a new block is indexed by when nothing says otherwise: the radionuclides, or the catalogue when there are none, or `nothing`."""
material_dimension(m::Model) = _material_dimension(_N(m))

_ed_material_list_raw(m::Model) = findfirst_value(l -> py_truthy(get(l, "for_contaminants", nothing)), _ed_stored_lists(m))
_ed_nuclide_list_stored(m::Model) = findfirst_value(l -> py_truthy(get(l, "for_nuclides", nothing)), _ed_stored_lists(m))

function _ed_editable(m::Model, name)
    lst = _ed_list_any(m, name)
    if lst !== nothing && py_truthy(get(lst, "derived", nothing))
        auto = get(lst, "auto", nothing)
        follows = auto == "compartments" ? "the model's compartments" :
                  auto == "transfers" ? "the model's transfers" : "the nuclide list"
        throw(EditError("'$(_py_str(name))' follows $follows, so it cannot be edited on its own. Change " *
                        "$(py_truthy(auto) ? "the model" : "the nuclides") and it changes with it."))
    end
    lst === nothing && throw(EditError("No index list named '$(_py_str(name))'"))
    lst["indices"] = _ed_normalise_indices(get(lst, "indices", nothing))
    return lst
end

function _ed_check_index_name(name, list_name)
    text = _py_str(name === nothing ? "" : name)
    isempty(strip(text)) && throw(EditError("An index of '$(_py_str(list_name))' has no name"))
    occursin(INDEX_NAME_BAD, text) &&
        throw(EditError("'$text' is not a usable index name: an index may not contain a line break or angle brackets"))
    return
end

"""
    add_index_list!(m, name, indices=(); subset_of=nothing, mapping_to=nothing, pairs=nothing,
                    comment=nothing, scenarios=false) -> IndexListView

Adds an index list: a root list, a sub-set of another (`subset_of`), or a
mapping onto one (`mapping_to`, with `pairs` saying which of this list's
indices each of the other's belongs to, `parent_index => own_index`).
`scenarios` makes it the model's scenario list, its first index the live
scenario. Every block's dimensions are written down first, as the
application does.
"""
function add_index_list!(m::Model, name, indices=(); subset_of=nothing, mapping_to=nothing, pairs=nothing,
                         comment=nothing, scenarios=false)
    _make_dimensions_explicit!(_N(m))
    occursin(NAME_RE, _py_str(name)) ||
        throw(EditError("'$(_py_str(name))' is not a valid index list name (letters, digits and underscore; must " *
                        "not start with a digit)"))
    name in RESERVED && throw(EditError("'$name' is a reserved name."))
    _ed_list_any(m, name) === nothing || throw(EditError("An index list named '$name' already exists"))
    (py_truthy(subset_of) && py_truthy(mapping_to)) &&
        throw(EditError("A list is a sub-set of one list or a mapping onto one, not both"))
    seen = Set{Any}()
    for i in indices
        _ed_check_index_name(i, name)
        i in seen && throw(EditError("'$(_py_str(i))' appears twice in index list '$name'"))
        push!(seen, i)
    end
    if py_truthy(subset_of)
        parent = _ed_list_any(m, subset_of)
        parent === nothing && throw(EditError("No index list named '$(_py_str(subset_of))'"))
        have = Set{Any}(_ed_index_names(parent))
        missing_ = [i for i in indices if !(i in have)]
        if !isempty(missing_)
            throw(EditError("$(join(missing_, ", ")) $(length(missing_) == 1 ? "is" : "are") not in " *
                            "'$(_py_str(subset_of))', so a sub-set of it cannot hold them"))
        end
    end
    lst = JDict("name" => name, "indices" => Any[JDict("name" => i, "enabled" => true) for i in indices])
    py_truthy(comment) && (lst["comment"] = comment)
    get(m.raw, "index_lists", nothing) isa AbstractVector || (m.raw["index_lists"] = Any[])
    push!(m.raw["index_lists"], lst)
    try
        if py_truthy(subset_of)
            set_list_role!(m, name, "sub_set", subset_of)
        elseif py_truthy(mapping_to)
            set_list_role!(m, name, "mapping", mapping_to)
            for (parent_index, own) in (py_truthy(pairs) ? _in_order(pairs, _ed_index_names(_ed_list_any(m, mapping_to))) : ())
                map_index!(m, name, parent_index, own)
            end
        end
        py_truthy(scenarios) && set_scenario_list!(m, name, true)
    catch e
        if e isa EditError
            m.raw["index_lists"] = Any[l for l in m.raw["index_lists"] if l !== lst]
        end
        rethrow()
    end
    return IndexListView(m, lst)
end

"""
    set_list_role!(m, name, role, target=nothing)

Defines a list against another: `role` `"plain"`, `"sub_set"` (of `target`)
or `"mapping"` (onto `target`).
"""
function set_list_role!(m::Model, name, role, target=nothing)
    lst = _ed_editable(m, name)
    if py_truthy(get(lst, "for_contaminants", nothing)) || py_truthy(get(lst, "for_nuclides", nothing)) ||
       py_truthy(get(lst, "derived", nothing))
        throw(EditError("'$(_py_str(name))' is built in, so it cannot be defined from another list"))
    end
    if role == "plain"
        delete!(lst, "sub_set_of")
        delete!(lst, "mapping")
        return nothing
    end
    parent = py_truthy(target) ? _ed_list_any(m, target) : nothing
    parent === nothing && throw(EditError("No index list named '$(_py_str(target))'"))
    get(parent, "name", nothing) == name && throw(EditError("A list cannot be defined from itself"))
    if py_truthy(get(parent, "sub_set_of", nothing)) || py_truthy(get(parent, "mapping", nothing))
        throw(EditError("'$(_py_str(parent["name"]))' is itself defined from another list. A sub-set or a mapping " *
                        "has to be taken from a root list."))
    end
    if role == "sub_set"
        delete!(lst, "mapping")
        lst["sub_set_of"] = parent["name"]
        have = Set{Any}(_ed_index_names(parent))
        lst["indices"] = Any[i for i in lst["indices"] if i["name"] in have]
        return nothing
    elseif role == "mapping"
        delete!(lst, "sub_set_of")
        mp = get(lst, "mapping", nothing)
        keep = (mp isa AbstractDict && get(mp, "to", nothing) == parent["name"]) ? _list_of(get(mp, "pairs", nothing)) : Any[]
        lst["mapping"] = JDict("to" => parent["name"], "pairs" => keep)
        return nothing
    end
    throw(EditError("'$(_py_str(role))' is not a way to define an index list (plain, sub_set, mapping)"))
end

"""In a mapped list: which of its indices `parent_index` belongs to (`nothing` unassigns it)."""
function map_index!(m::Model, name, parent_index, own_index)
    lst = _ed_editable(m, name)
    mp = get(lst, "mapping", nothing)
    mp isa AbstractDict || throw(EditError("'$(_py_str(name))' is not a mapped index list"))
    parent = _ed_list_any(m, get(mp, "to", nothing))
    parent === nothing && throw(EditError("No index list named '$(_py_str(get(mp, "to", nothing)))'"))
    parent_index in _ed_index_names(parent) ||
        throw(EditError("'$(_py_str(parent_index))' is not an index of '$(_py_str(parent["name"]))'"))
    if own_index !== nothing && !(own_index in Any[i["name"] for i in lst["indices"]])
        throw(EditError("'$(_py_str(own_index))' is not an index of '$(_py_str(name))'"))
    end
    pairs_ = Any[p for p in _py_iter(get(mp, "pairs", nothing)) if get(p, "to", nothing) != parent_index]
    own_index !== nothing && push!(pairs_, JDict("from" => own_index, "to" => parent_index))
    mp["pairs"] = pairs_
    return nothing
end

"""Makes a list the model's scenarios (one list at most), or stops it being them."""
function set_scenario_list!(m::Model, name, on=true)
    lst = _ed_list_any(m, name)
    lst === nothing && throw(EditError("No index list named '$(_py_str(name))'"))
    if py_truthy(on) && (py_truthy(get(lst, "for_contaminants", nothing)) || py_truthy(get(lst, "for_nuclides", nothing)) ||
                         py_truthy(get(lst, "derived", nothing)))
        throw(EditError("'$(_py_str(name))' is built in, so it cannot be the scenarios"))
    end
    for other in _ed_stored_lists(m)
        other === lst || delete!(other, "for_scenarios")
    end
    py_truthy(on) ? (lst["for_scenarios"] = true) : delete!(lst, "for_scenarios")
    names = scenarios(m)
    if !(get(m.raw, "scenario", nothing) in names)
        isempty(names) ? delete!(m.raw, "scenario") : (m.raw["scenario"] = names[1])
    end
    return nothing
end

"""The scenarios, when the model has a scenario list; the ones switched off do not run."""
function scenarios(m::Model)
    lst = findfirst_value(l -> py_truthy(get(l, "for_scenarios", nothing)), _ed_stored_lists(m))
    return lst === nothing ? Any[] : _ed_enabled_names(lst)
end

"""Which scenario is live: the one chosen, or the first."""
function scenario(m::Model)
    names = scenarios(m)
    s = get(m.raw, "scenario", nothing)
    return s in names ? s : (isempty(names) ? nothing : names[1])
end

"""Picks the live scenario (`nothing` forgets the choice)."""
function set_scenario!(m::Model, name)
    if name === nothing
        delete!(m.raw, "scenario")
        return nothing
    end
    names = scenarios(m)
    if !(name in names)
        throw(EditError("'$(_py_str(name))' is not a scenario in this model" *
                        (isempty(names) ? "" : " ($(join(names, ", ")))")))
    end
    m.raw["scenario"] = name
    return nothing
end

"""Gives the model a scenario list with these scenarios, the first live."""
add_scenarios!(m::Model, names, list_name="Scenarios") = add_index_list!(m, list_name, names; scenarios=true)

"""Renames a list and follows it into every dimension, per-index value, sub-set, mapping and app."""
function rename_index_list!(m::Model, old, new)
    _ed_editable(m, old)
    old == new && return nothing
    occursin(NAME_RE, _py_str(new)) ||
        throw(EditError("An index list name uses letters, digits and underscore, and may not start with a digit."))
    new in RESERVED && throw(EditError("'$new' is a reserved name."))
    lst = _ed_list_any(m, old)
    if py_truthy(get(lst, "for_contaminants", nothing)) || py_truthy(get(lst, "for_nuclides", nothing))
        what = py_truthy(get(lst, "for_contaminants", nothing)) ? "the material catalogue" : "the radionuclide dimension"
        throw(EditError("'$(_py_str(old))' is $what and keeps its name."))
    end
    _ed_list_any(m, new) === nothing || throw(EditError("An index list named '$new' already exists"))
    lst["name"] = new
    for other in _ed_lists(m)
        get(other, "sub_set_of", nothing) == old && (other["sub_set_of"] = new)
        mp = get(other, "mapping", nothing)
        (mp isa AbstractDict && get(mp, "to", nothing) == old) && (mp["to"] = new)
    end
    for b in _ed_all_raw(m)
        il = get(b, "index_lists", nothing)
        il isa AbstractVector && (b["index_lists"] = Any[d == old ? new : d for d in il])
        for e in _py_iter(get(b, "entries", nothing))
            ix = get(e, "index", nothing)
            if ix isa AbstractDict && haskey(ix, old)
                v = pop!(ix, old)
                ix[new] = v
            end
        end
    end
    rename_app_index_list!(m.raw, old, new)
    return nothing
end

"""The lists defined from `name` and the blocks indexed by it."""
function index_list_users(m::Model, name)
    users = Any[]
    for other in _ed_lists(m)
        mp = get(other, "mapping", nothing)
        if get(other, "sub_set_of", nothing) == name || (mp isa AbstractDict && get(mp, "to", nothing) == name)
            push!(users, other["name"])
        end
    end
    for b in _ed_all_raw(m)
        name in _py_iter(get(b, "index_lists", nothing)) && push!(users, qualified_name(b))
    end
    return _unique_in_order(users)
end

"""Deletes a list; refused while anything is defined from it or indexed by it."""
function delete_index_list!(m::Model, name)
    lst = _ed_editable(m, name)
    if py_truthy(get(lst, "for_contaminants", nothing)) || py_truthy(get(lst, "for_nuclides", nothing))
        materials_ = py_truthy(get(lst, "for_contaminants", nothing))
        what = materials_ ? "the material catalogue" : "the radionuclide dimension"
        throw(EditError("'$(_py_str(name))' is $what, which every model has. Remove its " *
                        "$(materials_ ? "materials" : "nuclides") instead."))
    end
    users = index_list_users(m, name)
    isempty(users) || throw(EditError("'$(_py_str(name))' is still used by $(join(users, ", ")). Remove it from those first.", users))
    m.raw["index_lists"] = Any[l for l in m.raw["index_lists"] if l !== lst]
    return nothing
end

function _ed_is_nuclide_role(m::Model, lst)
    py_truthy(get(lst, "for_nuclides", nothing)) && return true
    return py_truthy(get(lst, "for_contaminants", nothing)) &&
           !any(l -> py_truthy(get(l, "for_nuclides", nothing)), _ed_stored_lists(m))
end

function _ed_stored_elements(m::Model)
    root = _ed_material_list_raw(m)
    root === nothing && return nothing
    return findfirst_value(_ed_stored_lists(m)) do l
        !py_truthy(get(l, "derived", nothing)) && get(l, "mapping", nothing) isa AbstractDict &&
            get(l["mapping"], "to", nothing) == root["name"] &&
            (py_truthy(get(l, "for_elements", nothing)) || get(l, "name", nothing) == ELEMENT_LIST)
    end
end

function _ed_add_element_for!(m::Model, material)
    elements = _ed_stored_elements(m)
    elements === nothing && return
    el = element_of(material)
    name = el === nothing ? material : el
    py_truthy(name) || return
    get(elements, "indices", nothing) isa AbstractVector || (elements["indices"] = Any[])
    name in _ed_index_names(elements) || push!(elements["indices"], JDict("name" => name, "enabled" => true))
    pairs_ = get!(elements["mapping"], "pairs", Any[])
    any(p -> get(p, "to", nothing) == material, pairs_) || push!(pairs_, JDict("from" => name, "to" => material))
    return
end

"""
    add_index!(m, list_name, index)

Adds an index to a list. A radionuclide goes into the catalogue too, and one
ICRP 107 has no half-life for is made stable.
"""
function add_index!(m::Model, list_name, index)
    lst = _ed_editable(m, list_name)
    _ed_check_index_name(index, list_name)
    index in Any[i["name"] for i in lst["indices"]] &&
        throw(EditError("'$(_py_str(index))' is already in '$(_py_str(list_name))'"))
    as_nuclide = _ed_is_nuclide_role(m, lst)
    if as_nuclide
        root = _ed_material_list_raw(m)
        if root !== nothing && root !== lst
            root["indices"] = _ed_normalise_indices(get(root, "indices", nothing))
            index in Any[i["name"] for i in root["indices"]] ||
                push!(root["indices"], JDict("name" => index, "enabled" => true))
        end
    end
    push!(lst["indices"], JDict("name" => index, "enabled" => true))
    if py_truthy(get(lst, "for_nuclides", nothing)) || py_truthy(get(lst, "for_contaminants", nothing))
        _sync_nuclides!(_N(m))
        _ed_add_element_for!(m, index)
    end
    (as_nuclide && half_life(m, index) === nothing) && set_half_life!(m, index, STABLE)
    return nothing
end

"""
    remove_index!(m, list_name, index)

Removes an index, and every per-index value keyed by it. Removing a
radionuclide removes the material: the two lists hold one material.
"""
function remove_index!(m::Model, list_name, index)
    lst = _ed_editable(m, list_name)
    names = Any[i["name"] for i in lst["indices"]]
    index in names || throw(EditError("'$(_py_str(index))' is not in '$(_py_str(list_name))'"))
    if _ed_is_nuclide_role(m, lst)
        root = _ed_material_list_raw(m)
        if root !== nothing && root !== lst && index in _ed_index_names(root)
            remove_index!(m, root["name"], index)
            return nothing
        end
    end
    deleteat!(lst["indices"], findfirst(==(index), names))
    for b in _ed_all_raw(m)
        if py_truthy(get(b, "entries", nothing))
            b["entries"] = Any[e for e in b["entries"] if get(_py_or_dict(get(e, "index", nothing)), list_name, nothing) != index]
        end
    end
    for other in _ed_stored_lists(m)
        other["indices"] = _ed_normalise_indices(get(other, "indices", nothing))
        get(other, "sub_set_of", nothing) == list_name &&
            (other["indices"] = Any[i for i in other["indices"] if i["name"] != index])
        mp = get(other, "mapping", nothing)
        if mp isa AbstractDict && get(mp, "to", nothing) == list_name
            mp["pairs"] = Any[p for p in _py_iter(get(mp, "pairs", nothing)) if get(p, "to", nothing) != index]
        end
    end
    if py_truthy(get(lst, "for_contaminants", nothing)) || py_truthy(get(lst, "for_nuclides", nothing))
        _sync_nuclides!(_N(m))
        if py_truthy(get(lst, "for_contaminants", nothing)) && get(m.raw, "half_lives", nothing) isa AbstractDict
            delete!(m.raw["half_lives"], index)
        end
        py_truthy(get(lst, "for_contaminants", nothing)) && _ed_drop_empty_element!(m, index)
    end
    return nothing
end

function _ed_drop_empty_element!(m::Model, material)
    elements = _ed_stored_elements(m)
    elements === nothing && return
    el = element_of(material)
    name = el === nothing ? material : el
    name in _ed_index_names(elements) || return
    any(p -> get(p, "from", nothing) == name, _py_iter(get(elements["mapping"], "pairs", nothing))) && return
    remove_index!(m, elements["name"], name)
    return
end

"""
    rename_index!(m, list_name, old, new)

Renames an index everywhere it is written: per-index values, sub-sets,
mappings, the live scenario, half-lives, decay pairs, an app's indices and
`X[old]` in equations (unless another list has an index of that name).
"""
function rename_index!(m::Model, list_name, old, new)
    lst = _ed_editable(m, list_name)
    old in Any[i["name"] for i in lst["indices"]] || throw(EditError("'$(_py_str(old))' is not in '$(_py_str(list_name))'"))
    to = String(strip(_py_str(new === nothing ? "" : new)))
    isempty(to) && throw(EditError("An index needs a name"))
    to == old && return nothing
    _ed_check_index_name(to, list_name)
    material_roles = py_truthy(get(lst, "for_contaminants", nothing)) || py_truthy(get(lst, "for_nuclides", nothing))
    kin = material_roles ? Any[l for l in _ed_stored_lists(m) if py_truthy(get(l, "for_contaminants", nothing)) ||
                                                                 py_truthy(get(l, "for_nuclides", nothing))] : Any[lst]
    kin_names = Any[l["name"] for l in kin]
    for l in kin
        if l !== lst && to in _ed_index_names(l)
            throw(EditError("'$(_py_str(l["name"]))' already has an index called '$to'"))
        end
    end
    to in Any[i["name"] for i in lst["indices"]] && throw(EditError("'$(_py_str(list_name))' already has an index called '$to'"))
    for l in kin
        l["indices"] = Any[(i isa AbstractDict ? (get(i, "name", nothing) == old ? (j = JDict(i); j["name"] = to; j) : i) :
                            (i == old ? to : i)) for i in _py_iter(get(l, "indices", nothing))]
    end
    elsewhere = any(l -> !(l["name"] in kin_names) && any(i -> index_name(i) in (old, to), _py_iter(get(l, "indices", nothing))),
                    _ed_lists(m))
    if !elsewhere
        _each_equation(m) do text, system, blk, locals_
            rewrite_written_indices(text, n -> n == old ? to : nothing)
        end
    end
    for b in _ed_all_raw(m)
        for e in _py_iter(get(b, "entries", nothing))
            ix = get(e, "index", nothing)
            ix isa AbstractDict || continue
            for n in kin_names
                get(ix, n, nothing) == old && (ix[n] = to)
            end
        end
    end
    rename_app_index!(m.raw, kin_names, old, to)
    for other in _ed_stored_lists(m)
        other["name"] in kin_names && continue
        if get(other, "sub_set_of", nothing) in kin_names
            for i in _py_iter(get(other, "indices", nothing))
                (i isa AbstractDict && get(i, "name", nothing) == old) && (i["name"] = to)
            end
        end
        mp = get(other, "mapping", nothing)
        if mp isa AbstractDict && get(mp, "to", nothing) in kin_names
            for p in _py_iter(get(mp, "pairs", nothing))
                get(p, "to", nothing) == old && (p["to"] = to)
            end
        end
    end
    mp = get(lst, "mapping", nothing)
    if mp isa AbstractDict
        for p in _py_iter(get(mp, "pairs", nothing))
            get(p, "from", nothing) == old && (p["from"] = to)
        end
    end
    (py_truthy(get(lst, "for_scenarios", nothing)) && get(m.raw, "scenario", nothing) == old) && (m.raw["scenario"] = to)
    if material_roles
        _sync_nuclides!(_N(m))
        hl = get(m.raw, "half_lives", nothing)
        if hl isa AbstractDict && haskey(hl, old)
            v = pop!(hl, old)
            hl[to] = v
        end
        for pair in _py_iter(get(m.raw, "chains", nothing))
            pair[1] == old && (pair[1] = to)
            pair[2] == old && (pair[2] = to)
        end
    end
    return nothing
end

"""Takes an index out of the run or back in. For a material, in both material lists."""
function set_index_enabled!(m::Model, list_name, index, on)
    lst = _ed_editable(m, list_name)
    idx = findfirst_value(i -> i["name"] == index, lst["indices"])
    idx === nothing && throw(EditError("'$(_py_str(index))' is not in '$(_py_str(list_name))'"))
    idx["enabled"] = py_truthy(on)
    if py_truthy(get(lst, "for_contaminants", nothing)) || py_truthy(get(lst, "for_nuclides", nothing))
        for other in _ed_stored_lists(m)
            (other === lst || !(py_truthy(get(other, "for_contaminants", nothing)) ||
                                py_truthy(get(other, "for_nuclides", nothing)))) && continue
            twin = findfirst_value(i -> i isa AbstractDict && get(i, "name", nothing) == index, _py_iter(get(other, "indices", nothing)))
            twin === nothing || (twin["enabled"] = py_truthy(on))
        end
        _sync_nuclides!(_N(m))
    end
    return nothing
end

function _ed_enabled_of(m::Model, dim)
    lst = _ed_list_any(m, dim)
    if lst === nothing
        return dim == NUCLIDE_LIST ? collect(Any, _py_iter(get(m.raw, "nuclides", nothing))) : Any[]
    end
    return _ed_enabled_names(lst)
end

"""Every combination of the enabled indices of `dims`, the last varying fastest: the order the solver lays a block's values out in."""
function index_combinations(m::Model, dims)
    py_truthy(dims) || return JDict[]
    rows = JDict[JDict()]
    for d in dims
        nxt = JDict[]
        for r in rows, n in _ed_enabled_of(m, d)
            row = JDict(r)
            row[d] = n
            push!(nxt, row)
        end
        rows = nxt
    end
    return rows
end

"""How many values a block indexed by `dims` holds (1 for none)."""
function combination_count(m::Model, dims)
    n = 1
    for d in dims
        n *= length(_ed_enabled_of(m, d))
    end
    return n
end

"""The index lists the model stores (the derived ones are not stored)."""
index_lists(m::Model) = IndexListView[IndexListView(m, l) for l in _ed_stored_lists(m)]

"""Every index list, the derived `Elements`, `Compartments` and `Transfers` included."""
all_index_lists(m::Model) = IndexListView[IndexListView(m, l) for l in _ed_lists(m)]

"""The index list of that name (derived ones included)."""
function index_list(m::Model, name)
    lst = _ed_list_any(m, name)
    lst === nothing && throw(EditError("No index list named '$(_py_str(name))'"))
    return IndexListView(m, lst)
end

# --- materials, radionuclides and decay -----------------------------------------------------------------

"""Every material in the catalogue, radionuclides included."""
function materials(m::Model)
    lst = _ed_material_list_raw(m)
    return lst === nothing ? collect(Any, _py_iter(get(m.raw, "nuclides", nothing))) : _ed_index_names(lst)
end

"""The radionuclides: the materials that have a half-life."""
function nuclides(m::Model)
    lst = _ed_nuclide_list_stored(m)
    return lst === nothing ? Any[] : _ed_index_names(lst)
end

"""
    add_nuclides!(m, names, half_lives=nothing, pairs=nothing) -> Vector

Adds radionuclides, to the radionuclide list and the catalogue. A name ICRP
107 knows arrives with its half-life; one it does not is made stable until
told otherwise. `half_lives` sets overrides, in years (or `"stable"`), for
names in this call; `pairs` -- `[(parent, daughter, branching), ...]` --
replaces every decay pair out of these nuclides, a pair that would close a
loop skipped. Returns the names added.
"""
function add_nuclides!(m::Model, names, half_lives=nothing, pairs=nothing)
    wanted = _unique_in_order(names)
    lst = _ed_nuclide_list_stored(m)
    if lst === nothing
        _ensure_material_lists!(_N(m))
        lst = _ed_nuclide_list_stored(m)
    end
    have = Set{Any}(nuclides(m))
    added = Any[]
    for n in wanted
        n in have && continue
        add_index!(m, lst["name"], n)
        push!(added, n)
    end
    if py_truthy(half_lives)
        for (n, years) in _in_order(half_lives, wanted)
            n in wanted && set_half_life!(m, n, years)
        end
    end
    plist = pairs === nothing ? Any[] : collect(Any, pairs)
    if !isempty(plist)
        chains = _ed_own_chains!(m)
        mine = Set{Any}(wanted)
        filter!(c -> !(c[1] in mine), chains)
        for p in plist
            parent, daughter = p[1], p[2]
            ratio = length(p) > 2 ? p[3] : 1
            (parent == daughter || _ed_reaches(chains, daughter, parent)) && continue
            push!(chains, Any[parent, daughter, _model_js_number(ratio)])
        end
    end
    return added
end

"""Adds a material that does not decay -- stable carbon, water, a population -- with its own unit."""
function add_material!(m::Model, name, unit=nothing)
    root = _ed_material_list_raw(m)
    if root === nothing
        _ensure_material_lists!(_N(m))
        root = _ed_material_list_raw(m)
    end
    add_index!(m, root["name"], name)
    py_truthy(unit) && set_material_unit!(m, name, unit)
    return nothing
end

"""Removes a material (or a radionuclide) and everything keyed by it."""
function remove_material!(m::Model, name)
    root = _ed_material_list_raw(m)
    (root === nothing || !(name in materials(m))) && throw(EditError("'$(_py_str(name))' is not a material of this model"))
    remove_index!(m, root["name"], name)
    return nothing
end
const remove_nuclide! = remove_material!

"""The unit of a material that does not decay. A radionuclide's is the model's decay unit."""
function set_material_unit!(m::Model, name, unit)
    root = _ed_material_list_raw(m)
    root === nothing && throw(EditError("This model has no materials"))
    root["indices"] = _ed_normalise_indices(get(root, "indices", nothing))
    idx = findfirst_value(i -> i["name"] == name, root["indices"])
    idx === nothing && throw(EditError("'$(_py_str(name))' is not a material of this model"))
    nuc = _ed_nuclide_list_stored(m)
    if nuc !== nothing && nuc !== root && name in _ed_index_names(nuc)
        throw(EditError("'$(_py_str(name))' is a radionuclide, and an inventory of one is measured in " *
                        "$(join(DECAY_UNITS, " or ")) for the whole model -- set decay_unit instead. A material " *
                        "with a unit of its own is one that does not decay."))
    end
    u = String(strip(_py_or_text(unit)))
    isempty(u) ? delete!(idx, "unit") : (idx["unit"] = u)
    _ed_sync_derived_units!(m)
    return nothing
end

"""The unit one material is measured in: its own, or the decay unit for a radionuclide; `""` when it has none."""
material_unit(m::Model, name) = _material_unit(_N(m), name)

"""What a radionuclide inventory is measured in: `"Bq"` or `"mol"`."""
decay_unit(m::Model) = _decay_unit(_N(m))

"""
    set_decay_unit!(m, unit)

`"Bq"` or `"mol"`. Relabels the compartments that carried the other unit, as
the application does; no number is converted.
"""
function set_decay_unit!(m::Model, unit)
    want = String(strip(_js_string(unit)))
    want in DECAY_UNITS ||
        throw(EditError("'$(_py_str(unit))' is not a unit an inventory can be held in ($(join(DECAY_UNITS, " or ")))"))
    was = decay_unit(m)
    m.raw["decay_unit"] = want
    if was != want
        for c in _py_iter(get(m.raw, "compartments", nothing))
            strip(_js_string(get(c, "unit", nothing))) == was && (c["unit"] = want)
        end
    end
    _ed_sync_derived_units!(m)
    return nothing
end

"""
    half_life(m, nuclide)

The half-life the model gives a nuclide, in years: its own override or ICRP
107's; `Inf` when stable, `nothing` when nothing knows it.
"""
function half_life(m::Model, nuclide)
    hl = get(m.raw, "half_lives", nothing)
    own = py_truthy(hl) ? get(hl, nuclide, nothing) : nothing
    own !== nothing && return means_stable(own) ? Inf : _model_js_number(own)
    return half_life(nuclide)
end

"""Overrides a half-life, in years; `"stable"` (or `Inf`) for a nuclide that does not decay; `nothing` drops the override."""
function set_half_life!(m::Model, nuclide, years)
    if years === nothing
        get(m.raw, "half_lives", nothing) isa AbstractDict && delete!(m.raw["half_lives"], nuclide)
        return nothing
    end
    get(m.raw, "half_lives", nothing) isa AbstractDict || (m.raw["half_lives"] = JDict())
    hl = m.raw["half_lives"]
    if means_stable(years)
        hl[nuclide] = STABLE
        return nothing
    end
    v = _model_js_number(years)
    v > 0 || throw(EditError("A half-life must be greater than zero"))
    hl[nuclide] = v
    return nothing
end

"""
    decay_chains(m) -> Vector{Tuple}

The decay pairs in force, `(parent, daughter, branching)`: the model's own
when it states them, otherwise the ones ICRP 107 gives the materials it
carries (`default_chains`).
"""
function decay_chains(m::Model)
    own = get(m.raw, "chains", nothing)
    py_truthy(own) && return Tuple[(p[1], p[2], length(p) > 2 ? p[3] : 1) for p in own]
    return Tuple[p for p in default_chains(materials(m))]
end

"""Whether the model states its decay pairs rather than following its nuclides."""
has_own_chains(m::Model) = py_truthy(get(m.raw, "chains", nothing))

function _ed_own_chains!(m::Model)
    if !py_truthy(get(m.raw, "chains", nothing))
        m.raw["chains"] = Any[Any[p...] for p in decay_chains(m)]
    end
    return m.raw["chains"]
end

function _ed_check_pair(parent, daughter, ratio)
    (py_truthy(parent) && py_truthy(daughter)) || throw(EditError("A decay pair needs both nuclides"))
    parent == daughter && throw(EditError("A nuclide cannot decay into itself"))
    r = _model_js_number(ratio)
    (r > 0 && !(r > 1)) || throw(EditError("A branching ratio must be greater than 0 and at most 1"))
    return
end

function _ed_reaches(chains, start, goal)
    seen = Set{Any}()
    stack = Any[start]
    while !isempty(stack)
        n = pop!(stack)
        n == goal && return true
        n in seen && continue
        push!(seen, n)
        append!(stack, (c[2] for c in chains if c[1] == n))
    end
    return false
end

"""States the decay pairs outright, `[(parent, daughter, branching), ...]`: from then on the chains no longer follow the nuclides."""
function set_decay_chains!(m::Model, pairs)
    chains = Any[]
    for p in pairs
        parent, daughter = p[1], p[2]
        ratio = length(p) > 2 ? p[3] : 1
        _ed_check_pair(parent, daughter, ratio)
        _ed_reaches(chains, daughter, parent) &&
            throw(EditError("That would make a loop: $(_py_str(parent)) is already reachable from $(_py_str(daughter))."))
        push!(chains, Any[parent, daughter, _model_js_number(ratio)])
    end
    m.raw["chains"] = chains
    return nothing
end

"""Forgets the model's own pairs: the chains follow the nuclides again."""
reset_decay_chains!(m::Model) = (delete!(m.raw, "chains"); nothing)

"""Adds a decay pair. The first edit writes the chains in force into the model."""
function add_decay_pair!(m::Model, parent, daughter, ratio=1)
    _ed_check_pair(parent, daughter, ratio)
    chains = _ed_own_chains!(m)
    any(c -> c[1] == parent && c[2] == daughter, chains) &&
        throw(EditError("$(_py_str(parent)) to $(_py_str(daughter)) is already in the chain list"))
    _ed_reaches(chains, daughter, parent) &&
        throw(EditError("That would make a loop: $(_py_str(parent)) is already reachable from $(_py_str(daughter))."))
    push!(chains, Any[parent, daughter, _model_js_number(ratio)])
    return nothing
end

"""Removes a decay pair. The first edit writes the chains in force into the model."""
function remove_decay_pair!(m::Model, parent, daughter)
    chains = _ed_own_chains!(m)
    for (k, c) in enumerate(chains)
        if c[1] == parent && c[2] == daughter
            deleteat!(chains, k)
            return nothing
        end
    end
    throw(EditError("$(_py_str(parent)) to $(_py_str(daughter)) is not in the chain list"))
end

"""Sets a decay pair's branching ratio. The first edit writes the chains in force into the model."""
function set_decay_ratio!(m::Model, parent, daughter, ratio)
    r = _model_js_number(ratio)
    (r > 0 && !(r > 1)) || throw(EditError("A branching ratio must be greater than 0 and at most 1"))
    for c in _ed_own_chains!(m)
        if c[1] == parent && c[2] == daughter
            c[3] = r
            return nothing
        end
    end
    throw(EditError("$(_py_str(parent)) to $(_py_str(daughter)) is not in the chain list"))
end

# --- dimensions --------------------------------------------------------------------------------------------

"""What a new block of `kind` is indexed by: the radionuclides (or the catalogue) for most kinds, nothing for a parameter or a lookup table."""
function default_dimensions(m::Model, kind)
    kind in ("parameter", "lookup") && return Any[]
    name = material_dimension(m)
    return py_truthy(name) ? Any[name] : Any[]
end

function _ed_check_dims(m::Model, kind, dims)
    lists = _ed_lists(m)
    out = Any[]
    for d in dims
        lst = find_list(lists, d)
        lst === nothing && throw(EditError("No index list named '$(_py_str(d))'"))
        list_applies(lst, kind) || throw(EditError(list_applies_why(lst, kind)))
        push!(out, d)
    end
    clash = clashing_dimensions(lists, out)
    clash === nothing || throw(EditError(clashing_dimensions_why(clash)))
    if kind in ("farfield", "waste_package")
        rl = findfirst_value(l -> py_truthy(get(l, "for_contaminants", nothing)), lists)
        root = rl === nothing ? nothing : rl["name"]
        py_truthy(root) || (root = material_dimension(m))
        decaying = [d for d in out if py_truthy(root) && is_decay_dim(lists, d, root)]
        if length(decaying) > 1
            throw(EditError("$(kind == "farfield" ? "A far-field path runs" : "Waste packages run") one decay chain, " *
                            "and '$(decaying[1])' and '$(decaying[2])' are two radionuclide dimensions. Index it by " *
                            "one of them."))
        end
    end
    return out
end

"""
    set_dimensions!(m, block, dims) -> Vector

Sets which index lists a block is indexed by, dropping the per-index values
keyed by a list it no longer has. Returns the names of the connections,
transport parts and reductions whose dimensions followed.
"""
function set_dimensions!(m::Model, blk, dims)
    b = blk isa Block ? blk : block(m, blk)
    k = _kind_name(b)
    if k in ("function", "event")
        py_truthy(dims) && throw(EditError("A $k is not indexed"))
        return Any[]
    end
    dims = _ed_check_dims(m, k, collect(Any, dims))
    raw = b.raw
    raw["index_lists"] = copy(dims)
    _prune_entries!(raw, dims)
    followed = Any[]
    k == "compartment" && append!(followed, _sync_connection_dims!(_N(m), qualified_name(raw)))
    append!(followed, _sync_transport_dims!(_N(m), raw, dims))
    append!(followed, _ed_sync_reduction_dims!(m, qualified_name(raw)))
    return followed
end

function _ed_reduced_of(own, dims)
    have = Set{Any}(own)
    missing_ = [d for d in dims if !(d in have)]
    return length(missing_) == 1 ? missing_[1] : nothing
end

function _reduced_list(m::Model, b::Block)
    target = get(b.raw, "target", nothing)
    py_truthy(target) || return nothing
    q = resolve_reference(_py_str(target), b.system, _ed_known(m))
    hit = _ed_find(m, q)
    hit === nothing && return nothing
    return _ed_reduced_of(_py_iter(get(b.raw, "index_lists", nothing)), _effective_dims(_N(m), hit[2]))
end

function _ed_sync_reduction_dims!(m::Model, name=nothing)
    known = _ed_known(m)
    touched = Any[]
    for o in _py_iter(get(m.raw, "index_reductions", nothing))
        py_truthy(get(o, "target", nothing)) || continue
        q = resolve_reference(_js_string(o["target"]), system_of(o), known)
        (q === nothing || (name !== nothing && q != name)) && continue
        hit = _ed_find(m, q)
        hit === nothing && continue
        dims = _effective_dims(_N(m), hit[2])
        keep = _ed_reduced_of(_py_iter(get(o, "index_lists", nothing)), dims)
        reduced = keep in dims ? keep : (isempty(dims) ? nothing : dims[1])
        nxt = Any[d for d in dims if d != reduced]
        _list_of(get(o, "index_lists", nothing)) == nxt && continue
        o["index_lists"] = nxt
        _prune_entries!(o, nxt)
        push!(touched, get(o, "name", nothing))
    end
    for g in _py_iter(get(m.raw, "block_reductions", nothing))
        reads_ = name === nothing
        union_ = Any[]
        for ref in _py_iter(get(g, "targets", nothing))
            q = resolve_reference(_js_string(ref), system_of(g), known)
            q === nothing && continue
            q == name && (reads_ = true)
            hit = _ed_find(m, q)
            for d in (hit === nothing ? Any[] : _effective_dims(_N(m), hit[2]))
                d in union_ || push!(union_, d)
            end
        end
        (!reads_ || _list_of(get(g, "index_lists", nothing)) == union_) && continue
        g["index_lists"] = union_
        _prune_entries!(g, union_)
        push!(touched, get(g, "name", nothing))
    end
    return touched
end

# --- adding blocks -------------------------------------------------------------------------------------------

function _ed_name_problem(name)
    is_name(name) || return "'$(_py_str(name))' is not a valid name: use letters, digits and underscore, and do not start with a digit."
    name in RESERVED && return "'$name' is a reserved name."
    return nothing
end

function _ed_check_new_name(m::Model, name, system, allow=nothing)
    problem = _ed_name_problem(name)
    problem === nothing || throw(EditError(problem))
    target = qualify(system, name)
    if target != allow && _ed_find(m, target) !== nothing
        throw(EditError("'$name' is already used by another block" * (py_truthy(system) ? " in '$system'." : ".")))
    end
    (target != allow && target in _ed_system_set(m)) && throw(EditError("'$name' is already used by a sub-system."))
    return
end

_ed_id_taken(m::Model, qname) = _ed_find(m, qname) !== nothing || qname in _ed_system_set(m)

"""`base`, or `base1`, `base2`, ... -- the first name free in `system` (among its blocks and sub-systems)."""
function unique_name(m::Model, base, system="")
    _ed_id_taken(m, qualify(system, base)) || return String(base)
    for i in 1:99999
        _ed_id_taken(m, qualify(system, "$base$i")) || return "$base$i"
    end
    throw(EditError("Could not find a free name based on '$base'"))
end

_ed_name_for(m::Model, kind, name, system) = name !== nothing ? name : unique_name(m, _ED_DEFAULT_NAME[kind], system)

function _ed_check_system(m::Model, system)
    (py_truthy(system) && !(system in _ed_system_set(m))) && throw(EditError("No sub-system named '$(_py_str(system))'"))
    return
end

"""Checks a new block's name and puts it in the model, its sub-system written where the application writes it."""
function _ed_append!(m::Model, collection::String, raw::JDict, system, position=nothing; system_first::Bool=false)
    _ed_check_system(m, system)
    _ed_check_new_name(m, raw["name"], system)
    if py_truthy(system)
        if system_first
            out = JDict("system" => system)
            for (k, v) in raw
                out[k] = v
            end
            raw = out
        else
            raw = JDict(raw)
            raw["system"] = system
        end
    end
    get(m.raw, collection, nothing) isa AbstractVector || (m.raw[collection] = Any[])
    push!(m.raw[collection], raw)
    _ed_register!(m, collection, raw)
    b = _view_of(m, collection, raw)
    position === nothing || _set_position!(m, qualified_name(raw), _position_of(position))
    return b
end

function _ed_extras!(raw::JDict, comment, symbol)
    py_truthy(comment) && (raw["comment"] = comment)
    py_truthy(symbol) && (raw["symbol"] = symbol)
    return
end

_ed_dims_for(m::Model, kind, index_lists) =
    index_lists !== nothing ? _ed_check_dims(m, kind, collect(Any, index_lists)) : default_dimensions(m, kind)

"""
    add_compartment!(m, name=nothing, initial="0"; unit=nothing, index_lists=nothing, system="", dydt=nothing,
                     non_negative=true, handle_decay=true, abstol=nothing, comment=nothing, symbol=nothing,
                     position=nothing) -> Compartment

Adds a compartment: a state variable holding an inventory. `index_lists`
defaults to the radionuclides when the model has any, and `unit` to the
model's decay unit; `dydt` is an extra term in the rate of change,
`non_negative` keeps the inventory from going below zero, `abstol` is its
own absolute tolerance, `position` where it is drawn.
"""
function add_compartment!(m::Model, name_=nothing, initial_="0"; name=name_, initial=initial_, unit=nothing,
                          index_lists=nothing, system="", dydt=nothing, non_negative=true, handle_decay=true,
                          abstol=nothing, comment=nothing, symbol=nothing, position=nothing)
    n = _ed_name_for(m, "compartment", name, system)
    raw = JDict("name" => n)
    raw["initial"] = equation_text(initial)
    raw["unit"] = unit !== nothing ? unit : decay_unit(m)
    raw["handle_decay"] = py_truthy(handle_decay)
    raw["index_lists"] = _ed_dims_for(m, "compartment", index_lists)
    dydt === nothing || (raw["dydt"] = equation_text(dydt))
    py_truthy(non_negative) || (raw["non_negative"] = false)
    if abstol !== nothing
        v = _field_coerce(_field_of(:compartment, :abstol), abstol)
        v > 0 || throw(EditError("$(_py_str(n)): an absolute tolerance has to be greater than zero"))
        raw["abstol"] = v
    end
    _ed_extras!(raw, comment, symbol)
    return _ed_append!(m, "compartments", raw, system, position)
end

"""
    add_parameter!(m, name=nothing, value=0; unit="", index_lists=nothing, system="", distribution=nothing,
                   comment=nothing, symbol=nothing, position=nothing) -> Parameter

Adds a parameter: a constant, one per index when indexed (not indexed unless
`index_lists` says so). `distribution` is what a probabilistic run draws it
from (see `Kompartment.distributions`).
"""
function add_parameter!(m::Model, name_=nothing, value_=0; name=name_, value=value_, unit="", index_lists=nothing,
                        system="", distribution=nothing, comment=nothing, symbol=nothing, position=nothing)
    n = _ed_name_for(m, "parameter", name, system)
    raw = JDict("name" => n, "value" => 0, "unit" => unit, "index_lists" => _ed_dims_for(m, "parameter", index_lists))
    _ed_extras!(raw, comment, symbol)
    draft = Parameter(m, raw)
    draft.value = value
    distribution === nothing || (draft.distribution = distribution)
    return _ed_append!(m, "parameters", raw, system, position)
end

"""
    add_expression!(m, name=nothing, equation="0"; unit="", index_lists=nothing, system="", comment=nothing,
                    symbol=nothing, position=nothing) -> Expression

Adds an expression: an algebraic quantity worked out from the state, indexed
by the radionuclides by default when the model has any (`index_lists=[]`
for a single value).
"""
function add_expression!(m::Model, name_=nothing, equation_="0"; name=name_, equation=equation_, unit="",
                         index_lists=nothing, system="", comment=nothing, symbol=nothing, position=nothing)
    n = _ed_name_for(m, "expression", name, system)
    raw = JDict("name" => n)
    raw["equation"] = equation_text(equation)
    raw["unit"] = unit
    raw["index_lists"] = _ed_dims_for(m, "expression", index_lists)
    _ed_extras!(raw, comment, symbol)
    return _ed_append!(m, "expressions", raw, system, position)
end

"""A connection end as the application stores it: qualified, a transport meaning its End as a donor and its Begin as a receiver."""
function _ed_endpoint(m::Model, name, end_)
    name === nothing && return nothing
    name = _name_arg(name)
    q = name
    if q in transports(m)
        p = _norm_transport_parts(_N(m), q)
        part = end_ == "from" ? p.end_ : p.begin_
        if part === nothing
            throw(EditError("'$(_py_str(name))' has no $(end_ == "from" ? "End" : "Begin") compartment, so there is " *
                            "nothing in it to connect $(end_ == "from" ? "from" : "to")."))
        end
        q = qualified_name(part)
    end
    kind = _ed_kind_of(m, q)
    kind === nothing && throw(EditError("'$(_py_str(name))' is not a block in this model"))
    kind in ("compartment", "farfield") && return q
    if kind == "waste_package"
        end_ == "from" && return q
        throw(EditError("'$(_py_str(name))' is a set of waste packages: nothing flows into them, their release comes out"))
    end
    throw(EditError("'$(_py_str(name))' is not a compartment"))
end

function _ed_release_taken(m::Model, path, allow=nothing)
    held = Any[t for t in _py_iter(get(m.raw, "transfers", nothing))
               if get(t, "from", nothing) == path && qualified_name(t) != allow]
    isempty(held) && return ""
    to = py_truthy(get(held[1], "to", nothing)) ? held[1]["to"] : "outside the model"
    return "$path already delivers its release to $to, as '$(_py_str(get(held[1], "name", nothing)))'. A block has one " *
           "release, and a second line carrying it would deliver the whole of it again."
end

"""
    add_transfer!(m, source, target, rate="0"; name=nothing, multiply_by_donor=nothing, index_lists=nothing,
                  system=nothing, sum_extra_indices=false, comment=nothing, symbol=nothing) -> Transfer

Adds a transfer from `source` to `target`, by qualified names -- either may
be `nothing`, for outside the model, and a transport stands for its End as
a source and its Begin as a target. `rate` is a rate coefficient, multiplied
by the donor's inventory, unless `multiply_by_donor` is off (an absolute
flux); it is on by default when there is a donor. The name defaults to
`Source_Target`; the transfer lives in its donor's sub-system (its
receiver's when there is no donor) and is indexed by what its two ends
share. A transfer out of a far-field path or waste packages carries their
release: its rate is their name, and a block has one release.
"""
function add_transfer!(m::Model, source, target, rate_="0"; rate=rate_, name=nothing, multiply_by_donor=nothing,
                       index_lists=nothing, system=nothing, sum_extra_indices=false, comment=nothing, symbol=nothing)
    src = _ed_endpoint(m, source, "from")
    tgt = _ed_endpoint(m, target, "to")
    (src === nothing && tgt === nothing) && throw(EditError("A transfer needs a source, a target, or both"))
    (src !== nothing && src == tgt) && throw(EditError("A transfer cannot start and end at the same compartment"))
    release = src !== nothing && _ed_kind_of(m, src) in _ED_RELEASING
    if release
        taken = _ed_release_taken(m, src)
        isempty(taken) || throw(EditError(taken))
    end
    home = system !== nothing ? system : parent_of(src !== nothing ? src : tgt)
    base = (py_truthy(src) && py_truthy(tgt)) ? "$(base_name(src))_$(base_name(tgt))" : "T"
    n = name !== nothing ? name : unique_name(m, base, home)
    if index_lists !== nothing
        dims = _ed_check_dims(m, "transfer", collect(Any, index_lists))
    else
        shared = _transfer_dims(_N(m), JDict("from" => src, "to" => tgt))
        dims = shared !== nothing ? collect(Any, shared.dims) : Any[]
        if shared === nothing
            for e in (src, tgt)
                e === nothing && continue
                hit = _ed_find(m, e)
                for d in (hit === nothing ? Any[] : _effective_dims(_N(m), hit[2]))
                    d in dims || push!(dims, d)
                end
            end
        end
    end
    raw = JDict("name" => n, "from" => src, "to" => tgt)
    raw["rate"] = release ? src : equation_text(rate)
    raw["multiply_by_donor"] = release ? false : (multiply_by_donor !== nothing ? py_truthy(multiply_by_donor) : src !== nothing)
    raw["index_lists"] = dims
    unit = _ed_transfer_unit(m, raw)
    isempty(unit) || (raw["unit"] = unit)
    py_truthy(sum_extra_indices) && (raw["sum_extra_indices"] = true)
    _ed_extras!(raw, comment, symbol)
    return _ed_append!(m, "transfers", raw, home; system_first=true)
end

"""
    add_inflow!(m, target, rate="0"; name=nothing, index_lists=nothing, system=nothing, sum_extra_indices=false,
                comment=nothing, symbol=nothing) -> Inflow

Adds an inflow (source term): an absolute flux into `target` -- a
compartment or a far-field path -- from outside the model. It lives in its
target's sub-system and is indexed as its target is.
"""
function add_inflow!(m::Model, target, rate_="0"; rate=rate_, name=nothing, index_lists=nothing, system=nothing,
                     sum_extra_indices=false, comment=nothing, symbol=nothing)
    py_truthy(target) || throw(EditError("A source needs a target compartment"))
    tgt = _ed_endpoint(m, target, "to")
    home = system !== nothing ? system : parent_of(tgt)
    n = _ed_name_for(m, "inflow", name, home)
    if index_lists !== nothing
        dims = _ed_check_dims(m, "inflow", collect(Any, index_lists))
    else
        shared = _transfer_dims(_N(m), JDict("from" => nothing, "to" => tgt))
        dims = shared !== nothing ? collect(Any, shared.dims) : default_dimensions(m, "inflow")
    end
    raw = JDict("name" => n, "to" => tgt)
    raw["rate"] = equation_text(rate)
    unit = _ed_inflow_unit(m, raw)
    isempty(unit) || (raw["unit"] = unit)
    raw["index_lists"] = dims
    py_truthy(sum_extra_indices) && (raw["sum_extra_indices"] = true)
    _ed_extras!(raw, comment, symbol)
    return _ed_append!(m, "inflows", raw, home)
end
const add_source! = add_inflow!

"""
    add_lookup!(m, name=nothing, points=nothing; interpolation="linear", cyclic=false, argument=nothing, unit="",
                index_lists=nothing, system="", comment=nothing, symbol=nothing, position=nothing) -> Lookup

Adds a lookup table: a value following `points` `[(x, y), ...]`, read at the
simulation clock or -- with an `argument` -- called as `Name(x)`. Without
points it is a flat line at zero over the run.
"""
function add_lookup!(m::Model, name_=nothing, points_=nothing; name=name_, points=points_, interpolation="linear",
                     cyclic=false, argument=nothing, unit="", index_lists=nothing, system="", comment=nothing,
                     symbol=nothing, position=nothing)
    interpolation in INTERPOLATIONS ||
        throw(EditError("'$(_py_str(interpolation))' is not an interpolation rule ($(join(INTERPOLATIONS, ", ")))"))
    n = _ed_name_for(m, "lookup", name, system)
    if points === nothing
        sim = get(m.raw, "simulation", nothing)
        py_truthy(sim) || (sim = JDict())
        st, en = get(sim, "start_time", nothing), get(sim, "end_time", nothing)
        start = _model_js_number(st !== nothing ? st : 0)
        stop = _model_js_number(en !== nothing ? en : 1)
        start = isfinite(start) ? start : 0
        points = Any[Any[start, 0], Any[(isfinite(stop) && stop > start) ? stop : start + 1, 0]]
    end
    raw = JDict("name" => n, "unit" => unit, "interpolation" => interpolation, "cyclic" => py_truthy(cyclic),
                "points" => Any[], "index_lists" => _ed_dims_for(m, "lookup", index_lists))
    _ed_extras!(raw, comment, symbol)
    draft = Lookup(m, raw)
    draft.points = points
    py_truthy(argument) && (draft.argument = argument)
    return _ed_append!(m, "lookups", raw, system, position)
end

"""
    add_index_reduction!(m, name=nothing, target=nothing; over=nothing, operation="sum", percentile=nothing,
                         unit="", system="", comment=nothing, symbol=nothing, position=nothing) -> IndexReduction

Adds an index reduction: `target` reduced along one of its index lists
(`over`; its first by default) -- `sum`, `product`, `min`, `max`, `mean` or
`percentile` (with `percentile`, 0 to 100). `target` is written as an
equation would write it from `system`.
"""
function add_index_reduction!(m::Model, name_=nothing, target_=nothing; name=name_, target=target_, over=nothing,
                              operation="sum", percentile=nothing, unit="", system="", comment=nothing,
                              symbol=nothing, position=nothing)
    operation in OPERATIONS || throw(EditError("'$(_py_str(operation))' is not a reduction ($(join(OPERATIONS, ", ")))"))
    if operation == "percentile"
        pv = percentile === nothing ? nothing : _ed_pyfloat(percentile)
        (percentile !== nothing && pv === nothing) && throw(ArgumentError("could not convert $(_py_repr(percentile)) to float"))
        (pv !== nothing && 0 <= pv <= 100) ||
            throw(EditError("A percentile reduction needs a percentile between 0 and 100"))
    end
    n = _ed_name_for(m, "index_reduction", name, system)
    raw = JDict("name" => n, "target" => nothing, "operation" => operation, "unit" => unit, "index_lists" => Any[])
    percentile === nothing || (raw["percentile"] = percentile)
    _ed_extras!(raw, comment, symbol)
    if py_truthy(target)
        dims = _ed_reduction_dims(m, system, target, over, Any[])
        raw["target"] = target
        raw["index_lists"] = dims
    end
    return _ed_append!(m, "index_reductions", raw, system, position)
end

"""
    set_reduction_target!(m, name, target; over=nothing)

Points an index reduction at a block and re-derives its dimensions: the
target's, less the one it reduces over (`over`; else the one it reduced
before, when the new target has it; else the first).
"""
function set_reduction_target!(m::Model, name, target; over=nothing)
    b = block(m, name)
    _kind_name(b) == "index_reduction" || throw(EditError("'$(_py_str(_name_arg(name)))' is not an index operation"))
    if !py_truthy(target)
        b.raw["target"] = nothing
        return nothing
    end
    b.raw["index_lists"] = _ed_reduction_dims(m, b.system, target, over, _list_of(get(b.raw, "index_lists", nothing)))
    b.raw["target"] = target
    delete!(b.raw, "per_nuclide")
    return nothing
end

function _ed_reduction_dims(m::Model, system, target, over, own)
    q = resolve_reference(target, system, _ed_known(m))
    hit = _ed_find(m, q)
    hit === nothing && throw(EditError("No block named '$(_py_str(target))'"))
    dims = _effective_dims(_N(m), hit[2])
    (over !== nothing && !(over in dims)) && throw(EditError("'$(qualified_name(hit[2]))' is not indexed by '$(_py_str(over))'"))
    keep = over !== nothing ? over : _ed_reduced_of(own, dims)
    reduced = keep in dims ? keep : (isempty(dims) ? nothing : dims[1])
    return Any[d for d in dims if d != reduced]
end

"""
    add_block_reduction!(m, name=nothing, targets=(); operation="sum", unit="", system="", comment=nothing,
                         symbol=nothing, position=nothing) -> BlockReduction

Adds a block reduction (aggregate): several blocks combined element-wise --
`sum`, `product`, `min`, `max` or `mean` -- indexed by the union of their
dimensions.
"""
function add_block_reduction!(m::Model, name_=nothing, targets_=(); name=name_, targets=targets_, operation="sum",
                              unit="", system="", comment=nothing, symbol=nothing, position=nothing)
    operation in AGGREGATE_OPERATIONS ||
        throw(EditError("'$(_py_str(operation))' is not a reduction an aggregate can do ($(join(AGGREGATE_OPERATIONS, ", ")))"))
    n = _ed_name_for(m, "block_reduction", name, system)
    raw = JDict("name" => n, "targets" => Any[], "operation" => operation, "unit" => unit, "index_lists" => Any[])
    _ed_extras!(raw, comment, symbol)
    tlist = collect(Any, targets)
    dims = _ed_aggregate_dims(m, system, tlist)
    raw["targets"] = tlist
    raw["index_lists"] = dims
    return _ed_append!(m, "block_reductions", raw, system, position)
end

"""Sets what a block reduction combines, and re-derives its dimensions."""
function set_aggregate_targets!(m::Model, name, targets)
    b = block(m, name)
    _kind_name(b) == "block_reduction" || throw(EditError("'$(_py_str(_name_arg(name)))' is not an aggregate"))
    tlist = collect(Any, targets)
    b.raw["index_lists"] = _ed_aggregate_dims(m, b.system, tlist)
    b.raw["targets"] = tlist
    return nothing
end

function _ed_aggregate_dims(m::Model, system, targets)
    known = _ed_known(m)
    union_ = Any[]
    for ref in targets
        q = resolve_reference(ref, system, known)
        hit = _ed_find(m, q)
        hit === nothing && throw(EditError("No block named '$(_py_str(ref))'"))
        for d in _effective_dims(_N(m), hit[2])
            d in union_ || push!(union_, d)
        end
    end
    return union_
end

"""
    add_function!(m, name=nothing, parameters=("x",), equation=""; unit="", system="", comment=nothing) -> FunctionBlock

Adds a function: a body (`equation`) in terms of its `parameters`, callable
from any equation as `name(a, b)`.
"""
function add_function!(m::Model, name_=nothing, parameters_=("x",), equation_=""; name=name_, parameters=parameters_,
                       equation=equation_, unit="", system="", comment=nothing)
    n = _ed_name_for(m, "function", name, system)
    raw = JDict("name" => n, "parameters" => Any[], "equation" => equation_text(equation), "unit" => unit)
    py_truthy(comment) && (raw["comment"] = comment)
    raw["parameters"] = _ed_function_parameters(m, parameters)
    return _ed_append!(m, "functions", raw, system; system_first=true)
end

"""Sets a function's parameters: names, not repeated, not reserved, not a block's."""
function set_function_parameters!(m::Model, name, parameters)
    b = block(m, name)
    _kind_name(b) == "function" || throw(EditError("No function named '$(_py_str(_name_arg(name)))'"))
    b.raw["parameters"] = _ed_function_parameters(m, parameters)
    return nothing
end

function _ed_function_parameters(m::Model, parameters)
    taken = _ed_idx(m)
    out = Any[]
    for p in parameters
        p = String(strip(_py_str(p === nothing ? "" : p)))
        isempty(p) && continue
        occursin(NAME_RE, p) ||
            throw(EditError("'$p' is not a valid parameter name: letters, digits and underscore, not starting with a digit."))
        p in RESERVED && throw(EditError("'$p' is the name of a built-in function."))
        p in out && throw(EditError("'$p' is named twice."))
        haskey(taken, p) && throw(EditError("'$p' is already a block in this model, so the body would have no way to " *
                                            "mean the block. Choose another name for the parameter."))
        push!(out, p)
    end
    return out
end

function _ed_recorder!(m::Model, kind, name, watched, fields::Vector, unit, system, comment, index_lists, position)
    n = _ed_name_for(m, kind, name, system)
    if index_lists !== nothing
        dims = _ed_check_dims(m, kind, collect(Any, index_lists))
    else
        dims = Any[]
        if watched !== nothing && !isempty(strip(_py_str(watched)))
            r = resolve_reference(String(strip(_py_str(watched))), system, _ed_known(m))
            q = r !== nothing ? r : _py_str(watched)
            hit = _ed_find(m, q)
            dims = hit === nothing ? Any[] : _effective_dims(_N(m), hit[2])
        end
    end
    raw = JDict("name" => n, "index_lists" => dims, "unit" => unit)
    for (k, v) in fields
        raw[k] = v
    end
    py_truthy(comment) && (raw["comment"] = comment)
    return _ed_append!(m, _ED_RECORDER_COLLECTION[kind], raw, system, position)
end

"""
    add_min_max!(m, name=nothing, target="0"; operation="max", reset_trigger=nothing, start_trigger=nothing,
                 stop_trigger=nothing, unit="", system="", index_lists=nothing, comment=nothing, position=nothing)

Adds a min/max: the largest (or smallest) value `target` has taken, indexed
as the block it watches. The triggers name trigger blocks that restart,
start or stop it.
"""
function add_min_max!(m::Model, name_=nothing, target_="0"; name=name_, target=target_, operation="max",
                      reset_trigger=nothing, start_trigger=nothing, stop_trigger=nothing, unit="", system="",
                      index_lists=nothing, comment=nothing, position=nothing)
    operation in EXTREMES || throw(EditError("'$(_py_str(operation))' is not a min/max operation ($(join(EXTREMES, ", ")))"))
    fields = ["target" => equation_text(target), "operation" => operation, "reset_trigger" => reset_trigger,
              "start_trigger" => start_trigger, "stop_trigger" => stop_trigger]
    return _ed_recorder!(m, "min_max", name, target, fields, unit, system, comment, index_lists, position)
end

"""Adds a running mean: the mean of `target` over the time it has recorded."""
function add_running_mean!(m::Model, name_=nothing, target_="0"; name=name_, target=target_, reset_trigger=nothing,
                           start_trigger=nothing, stop_trigger=nothing, unit="", system="", index_lists=nothing,
                           comment=nothing, position=nothing)
    fields = ["target" => equation_text(target), "reset_trigger" => reset_trigger, "start_trigger" => start_trigger,
              "stop_trigger" => stop_trigger]
    return _ed_recorder!(m, "running_mean", name, target, fields, unit, system, comment, index_lists, position)
end

"""Adds a snapshot: `target` as it was when `trigger` last fired, `initial` until then."""
function add_snapshot!(m::Model, name_=nothing, target_="0", trigger_=nothing; name=name_, target=target_,
                       trigger=trigger_, initial="0", unit="", system="", index_lists=nothing, comment=nothing,
                       position=nothing)
    fields = ["target" => equation_text(target), "trigger" => trigger, "initial" => equation_text(initial)]
    return _ed_recorder!(m, "snapshot", name, target, fields, unit, system, comment, index_lists, position)
end

"""Adds a delay: `target` as it was `delay` ago."""
function add_delay!(m::Model, name_=nothing, target_="0", delay_="0"; name=name_, target=target_, delay=delay_,
                    unit="", system="", index_lists=nothing, comment=nothing, position=nothing)
    fields = ["target" => equation_text(target), "delay" => equation_text(delay)]
    return _ed_recorder!(m, "delay", name, target, fields, unit, system, comment, index_lists, position)
end

"""
Adds a trigger: the instant `first` crosses `second` (`rising`, `falling` or
`both`). The solver stops there, and recorders and snapshots can be driven
by it.
"""
function add_trigger!(m::Model, name_=nothing, first_="0", second_="0"; name=name_, first=first_, second=second_,
                      direction="rising", unit="", system="", index_lists=nothing, comment=nothing, position=nothing)
    direction in DIRECTIONS ||
        throw(EditError("'$(_py_str(direction))' is not a crossing direction ($(join(DIRECTIONS, ", ")))"))
    fields = ["first" => equation_text(first), "second" => equation_text(second), "direction" => direction]
    return _ed_recorder!(m, "trigger", name, first, fields, unit, system, comment, index_lists, position)
end

const _ED_FARF_OPTIONAL_KEYS = ("aw", "aperture")

"""
    add_farfield!(m, name=nothing; index_lists=nothing, system="", comment=nothing, position=nothing, settings...)

Adds a far-field path (FARFCOMP), indexed by the radionuclides when the
model has them and by nothing otherwise, with the defaults of a new path for
every setting not given (`tw`, `surface`, `f`, `aw`, `aperture`, `kd_f`,
`kd_m`, `de_m`, `eps_m`, `rho_m`, `pe`, `pen_dep`, `pen_dep_0`, `n_f`,
`n_m`, `o_b`, `n_b`, `grid`, `handle_decay`, `report_cells`, `method`).
"""
function add_farfield!(m::Model, name_=nothing; name=name_, index_lists=nothing, system="", comment=nothing,
                       position=nothing, settings...)
    material = material_dimension(m)
    unknown = [String(k) for k in keys(settings) if !haskey(FARF_DEFAULTS, String(k)) && !(String(k) in _ED_FARF_OPTIONAL_KEYS)]
    isempty(unknown) || throw(EditError("A far-field path has no setting $(join(map(_py_repr, unknown), ", "))"))
    n = _ed_name_for(m, "farfield", name, system)
    raw = JDict("name" => n)
    for (k, v) in jcopy(FARF_DEFAULTS)
        raw[k] = v
    end
    raw["unit"] = "$(decay_unit(m))/$(_norm_time_unit(_N(m)))"
    raw["index_lists"] = index_lists !== nothing ? _ed_check_dims(m, "farfield", collect(Any, index_lists)) :
                         (py_truthy(material) ? Any[material] : Any[])
    py_truthy(comment) && (raw["comment"] = comment)
    draft = Farfield(m, raw)
    for (k, v) in settings
        setproperty!(draft, k, v)
    end
    return _ed_append!(m, "farfields", raw, system, position)
end

"""
    add_waste_package!(m, name=nothing; failure="never", index_lists=nothing, system="", comment=nothing,
                       position=nothing, settings...)

Adds a set of waste packages, indexed by the radionuclides when the model
has any. `failure` and the settings its law reads (`fail_at`, `fail_from`,
`fail_to`, `fail_start`, `fail_rate`, `fail_scale`, `fail_shape`), and
`inventory`, `irf`, `degradation_rate`, `packages`, `handle_decay` may be
given.
"""
function add_waste_package!(m::Model, name_=nothing; name=name_, failure="never", index_lists=nothing, system="",
                            comment=nothing, position=nothing, settings...)
    unknown = [String(k) for k in keys(settings) if !haskey(WASTE_DEFAULTS, String(k)) || String(k) == "failure"]
    isempty(unknown) || throw(EditError("Waste packages have no setting $(join(map(_py_repr, unknown), ", ")) here"))
    material = material_dimension(m)
    n = _ed_name_for(m, "waste_package", name, system)
    raw = JDict("name" => n)
    for (k, v) in jcopy(WASTE_DEFAULTS)
        raw[k] = v
    end
    raw["unit"] = "$(decay_unit(m))/$(_norm_time_unit(_N(m)))"
    raw["index_lists"] = index_lists !== nothing ? _ed_check_dims(m, "waste_package", collect(Any, index_lists)) :
                         (py_truthy(material) ? Any[material] : Any[])
    py_truthy(comment) && (raw["comment"] = comment)
    draft = WastePackage(m, raw)
    for (k, v) in settings
        setproperty!(draft, k, v)
    end
    failure != "never" && set_failure!(draft, failure)
    return _ed_append!(m, "waste_packages", raw, system, position)
end

"""
    add_event!(m, name=nothing; timing="at", at="", rate="", start="", until="", sampled=true, system="",
               comment=nothing, position=nothing) -> Event

Adds a disruptive event: once `at` a time (`timing="at"`), or at random at
`rate` per unit time between `start` and `until` (`timing="poisson"`; blank
is the run's start and end). Give it actions with `add_fail_action!` and
`add_move_action!`.
"""
function add_event!(m::Model, name_=nothing; name=name_, timing="at", at="", rate="", start="", until="",
                    sampled=true, system="", comment=nothing, position=nothing)
    n = _ed_name_for(m, "event", name, system)
    raw = JDict("name" => n)
    for (k, v) in jcopy(DIS_DEFAULTS)
        raw[k] = v
    end
    raw["unit"] = ""
    raw["index_lists"] = Any[]
    py_truthy(comment) && (raw["comment"] = comment)
    draft = Event(m, raw)
    draft.timing = timing
    draft.at = at
    draft.rate = rate
    draft.start = start
    draft.until = until
    draft.sampled = sampled
    return _ed_append!(m, "events", raw, system, position)
end

# --- connections and releases -----------------------------------------------------------------------------

"""
    set_connection_end!(m, name, end_, target) -> Block

Re-attaches one end (`"from"` or `"to"`) of a transfer or inflow; `nothing`
is outside the model. A transfer moves with its donor.
"""
function set_connection_end!(m::Model, name, end_, target)
    b = block(m, name)
    end_ in ("from", "to") || throw(EditError("'$(_py_str(end_))' is not an end of a connection (from, to)"))
    k = _kind_name(b)
    if k == "inflow"
        end_ == "from" && throw(EditError("A source always comes from outside the model"))
        target === nothing && throw(EditError("A source needs a target compartment"))
        b.raw["to"] = _ed_endpoint(m, target, "to")
        _ed_sync_transfer_dimensions!(m)
        return _ed_rehome!(m, b)
    end
    k == "transfer" || throw(EditError("'$(_py_str(_name_arg(name)))' is not a connection"))
    new = _ed_endpoint(m, target, end_)
    other = end_ == "from" ? get(b.raw, "to", nothing) : get(b.raw, "from", nothing)
    (new !== nothing && new == other) && throw(EditError("A transfer cannot start and end at the same compartment"))
    (new === nothing && other === nothing) && throw(EditError("A transfer needs a compartment at one end at least"))
    if end_ == "from" && new !== nothing && _ed_kind_of(m, new) in _ED_RELEASING
        taken = _ed_release_taken(m, new, _bk_qualified_name(b))
        isempty(taken) || throw(EditError(taken))
    end
    b.raw[end_] = new
    get(b.raw, "from", nothing) === nothing && (b.raw["multiply_by_donor"] = false)
    if get(b.raw, "from", nothing) !== nothing && _ed_kind_of(m, b.raw["from"]) in _ED_RELEASING
        b.raw["rate"] = b.raw["from"]
        b.raw["multiply_by_donor"] = false
    end
    _ed_sync_transfer_dimensions!(m)
    return _ed_rehome!(m, b)
end

function _ed_rehome!(m::Model, b::Block)
    fr = get(b.raw, "from", nothing)
    home = parent_of(fr !== nothing ? fr : get(b.raw, "to", nothing))
    b.system == home && return b
    return block(m, move_block!(m, _bk_qualified_name(b), home))
end

"""
    set_release!(m, path, to) -> Union{Transfer,Nothing}

Sends a far-field path's or waste packages' release to a compartment, or
nowhere (`nothing`: the release is only read, by name). A block has one
release, so pointing it somewhere new moves the one there is.
"""
function set_release!(m::Model, path, to)
    b = block(m, path)
    _kind_name(b) in _ED_RELEASING || throw(EditError("'$(_py_str(_name_arg(path)))' has no release to send anywhere"))
    q = _bk_qualified_name(b)
    held = Any[t for t in _py_iter(get(m.raw, "transfers", nothing)) if get(t, "from", nothing) == q]
    if to === nothing || to == ""
        for t in held
            delete_block!(m, qualified_name(t))
        end
        return nothing
    end
    target = _ed_endpoint(m, to, "to")
    (length(held) == 1 && get(held[1], "to", nothing) == target) && return block(m, qualified_name(held[1]))
    if !isempty(held)
        for t in held[2:end]
            delete_block!(m, qualified_name(t))
        end
        return set_connection_end!(m, qualified_name(held[1]), "to", target)
    end
    return add_transfer!(m, q, target)
end

# --- the equations of the model, walked --------------------------------------------------------------------

"""
Calls `fn(text, system, block, locals)` on every equation in the model; text
returned replaces the equation. Per-index equations are visited as their
block's, and so are a transfer's availability operands and an event's
action shares (`_each_equation`).
"""
function _each_equation(fn, m::Model)
    raw = m.raw
    function visit(holder, key, system, blk, locals_=nothing)
        holder isa AbstractDict || return
        v = get(holder, key, nothing)
        if v isa AbstractString
            nxt = fn(v, system, blk, locals_)
            nxt === nothing || (holder[key] = nxt)
        end
        return
    end
    function both(blk, key, locals_=nothing)
        blk isa AbstractDict || return
        system = system_of(blk)
        visit(blk, key, system, blk, locals_)
        for e in _py_iter(get(blk, "entries", nothing))
            visit(e, key, system, blk, locals_)
        end
        return
    end
    for t in _py_iter(get(raw, "transfers", nothing))
        both(t, "rate")
        a = t isa AbstractDict ? get(t, "availability", nothing) : nothing
        if a isa AbstractDict
            for key in ("limit", "top", "bottom")
                visit(a, key, system_of(t), t)
            end
        end
    end
    for s in _py_iter(get(raw, "inflows", nothing))
        both(s, "rate")
    end
    for e in _py_iter(get(raw, "expressions", nothing))
        both(e, "equation")
    end
    for kind in _ED_RECORDER_KINDS
        for b in _py_iter(get(raw, _ED_RECORDER_COLLECTION[kind], nothing))
            for key in (_ED_RECORDER_EQUATIONS[kind]..., _ED_RECORDER_TRIGGERS[kind]...)
                both(b, key)
            end
        end
    end
    for f in _py_iter(get(raw, "functions", nothing))
        f isa AbstractDict || continue
        both(f, "equation", Set{String}(_py_str(p) for p in _py_iter(get(f, "parameters", nothing))))
    end
    for c in _py_iter(get(raw, "compartments", nothing))
        both(c, "initial")
        both(c, "dydt")
    end
    for f in _py_iter(get(raw, "farfields", nothing))
        for key in FARF_EQUATION_KEYS
            both(f, key)
        end
    end
    for w in _py_iter(get(raw, "waste_packages", nothing))
        for key in WASTE_EQUATION_KEYS
            both(w, key)
        end
    end
    for d in _py_iter(get(raw, "events", nothing))
        for key in DIS_EQUATION_KEYS
            both(d, key)
        end
        d isa AbstractDict || continue
        for a in _py_iter(get(d, "actions", nothing))
            visit(a, "fraction", system_of(d), d)
        end
    end
    return
end

"""Calls `fn(name, system, block)` on every block name a reduction reduces; what it returns replaces the name (`_each_target`)."""
function _each_target(fn, m::Model)
    for o in _py_iter(get(m.raw, "index_reductions", nothing))
        system = system_of(o)
        t = get(o, "target", nothing)
        (t isa AbstractString && !isempty(t)) && (o["target"] = fn(t, system, o))
        for e in _py_iter(get(o, "entries", nothing))
            et = get(e, "target", nothing)
            (et isa AbstractString && !isempty(et)) && (e["target"] = fn(et, system, o))
        end
    end
    for g in _py_iter(get(m.raw, "block_reductions", nothing))
        system = system_of(g)
        ts = get(g, "targets", nothing)
        ts isa AbstractVector && (g["targets"] = Any[fn(t, system, g) for t in ts])
        for e in _py_iter(get(g, "entries", nothing))
            ets = get(e, "targets", nothing)
            ets isa AbstractVector && (e["targets"] = Any[fn(t, system, g) for t in ets])
        end
    end
    return
end

"""
    references_graph(m) -> OrderedDict

Every block's qualified name => the blocks it reads: in its equations, as
its targets, at its ends, in its actions.
"""
function references_graph(m::Model)
    known = _ed_known(m)
    reads_ = OrderedDict{String,Vector{String}}(q => String[] for q in _ed_idx_order(m))
    function note(referrer, target)
        (target === nothing || target == referrer || !haskey(reads_, target)) && return
        lst = get!(reads_, referrer, String[])
        target in lst || push!(lst, target)
        return
    end
    _each_equation(m) do text, system, blk, locals_
        for q in references_in(text, system, known; skip=locals_)
            note(qualified_name(blk), q)
        end
        return nothing
    end
    _each_target(m) do ref, system, blk
        note(qualified_name(blk), resolve_reference(strip(ref), system, known))
        return ref
    end
    for t in _py_iter(get(m.raw, "transfers", nothing))
        note(qualified_name(t), get(t, "from", nothing))
        note(qualified_name(t), get(t, "to", nothing))
    end
    for s in _py_iter(get(m.raw, "inflows", nothing))
        note(qualified_name(s), get(s, "to", nothing))
    end
    for d in _py_iter(get(m.raw, "events", nothing))
        for a in _py_iter(get(d, "actions", nothing))
            for end_ in ("block", "from", "to")
                v = get(a, end_, nothing)
                (v isa AbstractString && !isempty(strip(v))) &&
                    note(qualified_name(d), resolve_reference(strip(v), system_of(d), known))
            end
        end
    end
    return reads_
end

"""The blocks `name` reads: in its equations, as its targets, at its ends."""
function reads(m::Model, name)
    name = _name_arg(name)
    block(m, name)
    return get(references_graph(m), name, String[])
end

"""The blocks that read `name`: in an equation, as a reduction target, as a transfer end or in an event's action."""
function references_to(m::Model, name)
    name = _name_arg(name)
    block(m, name)
    return String[q for (q, targets) in references_graph(m) if name in targets]
end

# --- renaming, moving, deleting -----------------------------------------------------------------------------

function _ed_refuse_shadowed(m::Model, known, retarget)
    shadowed = Tuple{String,String,String,String}[]
    _each_equation(m) do text, system, blk, locals_
        replace_ = function (q, _system)
            r = retarget(q, system, blk)
            r === nothing && return nothing
            to, where_ = r
            spelled = reference_from(to, where_, known)
            found = resolve_reference(spelled, where_, known)
            (found !== nothing && !isempty(found) && found != to) &&
                push!(shadowed, (qualified_name(blk), spelled, to, where_))
            return nothing
        end
        rewrite_references(text, system, known, replace_, locals_)
        return nothing
    end
    if !isempty(shadowed)
        blk, spelled, to, where_ = shadowed[1]
        more = length(shadowed) > 1 ? " (and $(length(shadowed) - 1) more)" : ""
        throw(EditError("'$blk' reads '$to', which from inside '$(isempty(where_) ? "the top level" : where_)' would " *
                        "have to be written '$spelled' -- and there that name means a different block. Rename or " *
                        "move one of the two first.$more", [s[1] for s in shadowed]))
    end
    return
end

function _ed_retarget_all!(m::Model, new_name_of, new_system_of, also_known=())
    known = _ed_known(m, also_known)
    function moved(q, system, blk)
        r = new_name_of(q)
        to = _truthy_text(r) ? r : q
        where_ = new_system_of(system, blk)
        return (to == q && where_ == system) ? nothing : (to, where_)
    end
    _ed_refuse_shadowed(m, known, moved)
    for conn in Iterators.flatten((_py_iter(get(m.raw, "transfers", nothing)), _py_iter(get(m.raw, "inflows", nothing))))
        for end_ in ("from", "to")
            v = get(conn, end_, nothing)
            if v !== nothing
                r = new_name_of(v)
                conn[end_] = _truthy_text(r) ? r : v
            end
        end
    end
    for d in _py_iter(get(m.raw, "events", nothing))
        for a in _py_iter(get(d, "actions", nothing))
            for end_ in ("block", "from", "to")
                v = get(a, end_, nothing)
                if v isa AbstractString && !isempty(v)
                    r = new_name_of(v)
                    a[end_] = _truthy_text(r) ? r : v
                end
            end
        end
    end
    _each_equation(m) do text, system, blk, locals_
        replace_ = function (q, _system)
            r = moved(q, system, blk)
            return r === nothing ? nothing : reference_from(r[1], r[2], known)
        end
        return rewrite_references(text, system, known, replace_, locals_)
    end
    _each_target(m) do ref, system, blk
        q = resolve_reference(ref, system, known)
        q === nothing && return ref
        r = moved(q, system, blk)
        return r === nothing ? ref : reference_from(r[1], r[2], known)
    end
    # An app built on the model names blocks by their qualified names too.
    retarget_app_names!(m.raw, new_name_of)
    moves = OrderedDict{String,OrderedDict{String,String}}()
    for (collection, list_name) in (("compartments", COMPARTMENT_LIST), ("transfers", TRANSFER_LIST))
        mv = OrderedDict{String,String}()
        for b in _py_iter(get(m.raw, collection, nothing))
            was = qualified_name(b)
            to = new_name_of(was)
            (_truthy_text(to) && to != was) && (mv[was] = to)
        end
        isempty(mv) || (moves[list_name] = mv)
    end
    _ed_retarget_block_indexes!(m, moves)
    return
end

function _ed_retarget_block_indexes!(m::Model, moves)
    any(!isempty, values(moves)) || return
    lists = _ed_lists(m)
    written = OrderedDict{String,Union{Nothing,String}}()
    for (list_name, mv) in moves
        for (frm, to) in mv
            ambiguous = any(l -> get(l, "name", nothing) != list_name && frm in _ed_index_names(l), lists)
            written[frm] = (ambiguous || haskey(written, frm)) ? nothing : to
        end
    end
    for b in _ed_all_raw(m)
        for e in _py_iter(get(b, "entries", nothing))
            ix = get(e, "index", nothing)
            ix isa AbstractDict || continue
            for (list_name, mv) in moves
                was = get(ix, list_name, nothing)
                (was !== nothing && haskey(mv, was)) && (ix[list_name] = mv[was])
            end
        end
    end
    retarget_app_indexes!(m.raw, moves)
    any(v -> _truthy_text(v), values(written)) || return
    mapping = n -> get(written, n, nothing)
    _each_equation(m) do text, system, blk, locals_
        rewrite_written_indices(text, mapping)
    end
    _each_target(m) do ref, system, blk
        rewrite_written_indices(ref, mapping)
    end
    return
end

function _ed_retarget_layout!(m::Model, new_name_of, canvas_of=nothing)
    lay = get(m.raw, "layout", nothing)
    (lay isa AbstractDict && !isempty(lay)) || return
    nxt = JDict()
    for (key, value) in lay
        edge = _parse_edge_key(key)
        if edge !== nothing
            name, canvas = edge
            if !(canvas === nothing || canvas == "")
                if canvas_of !== nothing
                    canvas = canvas_of(canvas)
                else
                    r = new_name_of(canvas)
                    canvas = _truthy_text(r) ? r : canvas
                end
            end
            r = new_name_of(name)
            nxt[_edge_key(_truthy_text(r) ? r : name, canvas)] = value
            continue
        end
        r = new_name_of(key)
        nxt[_truthy_text(r) ? r : key] = value
    end
    m.raw["layout"] = nxt
    return
end

"""
    rename_block!(m, name, new_name) -> String

Renames a block -- a local name; `move_block!` changes its sub-system -- and
follows the change through every reference: equations, transfer ends,
reduction targets, event actions, per-index values keyed by it, an app's
references, its place on the diagram. Returns the new qualified name.
"""
function rename_block!(m::Model, name, new_name)
    name = _name_arg(name)
    b = block(m, name)
    base_name(new_name) != new_name &&
        throw(EditError("'$(_py_str(new_name))' is a path, not a name. Use move_block() to put a block in another sub-system."))
    target = qualify(b.system, new_name)
    target == name && return name
    _ed_check_new_name(m, new_name, b.system, name)
    _ed_retarget_all!(m, q -> q == name ? target : nothing, (s, blk) -> s, (target,))
    b.raw["name"] = new_name
    lay = get(m.raw, "layout", nothing)
    if lay isa AbstractDict && !isempty(lay)
        # One name moves, and its entries move to the end, as the application's do.
        keys_ = Any[name]
        for k in keys(lay)
            e = _parse_edge_key(k)
            (e === nothing ? "" : e[1]) == name && push!(keys_, k)
        end
        for key in keys_
            haskey(lay, key) || continue
            edge = _parse_edge_key(key)
            to = edge !== nothing ? _edge_key(target, edge[2]) : target
            v = pop!(lay, key)
            lay[to] = v
        end
    end
    _ed_invalidate!(m)
    return target
end

"""
    move_block!(m, name, system="") -> String

Moves a block into another sub-system (`""`: the top level), numbering its
name if it is taken there, and rewrites every reference. A compartment takes
its outgoing transfers and its inflows with it. Returns the new qualified
name.
"""
function move_block!(m::Model, name, system="")
    name = _name_arg(name)
    b = block(m, name)
    _ed_check_system(m, system)
    b.system == system && return name
    role = get(b.raw, "transport", nothing)
    home = _norm_transport_of(_N(m), b.raw)
    home === nothing || throw(EditError("'$(_bk_local_name(b))' is the transport $(_py_str(role)) of '$home' and stays in it."))
    py_truthy(role) && delete!(b.raw, "transport")
    local_ = b.name
    k = 1
    while _ed_find(m, qualify(system, local_)) !== nothing
        local_ = "$(b.name)$k"
        k += 1
    end
    target = qualify(system, local_)
    raw = b.raw
    _ed_retarget_all!(m, q -> q == name ? target : nothing, (s, blk) -> blk === raw ? system : s, (target,))
    _ed_retarget_layout!(m, q -> q == name ? target : nothing)
    raw["name"] = local_
    py_truthy(system) ? (raw["system"] = system) : delete!(raw, "system")
    _ed_invalidate!(m)
    if _kind_name(b) == "compartment"
        attached = Any[t for t in _py_iter(get(m.raw, "transfers", nothing)) if get(t, "from", nothing) == target]
        append!(attached, (s for s in _py_iter(get(m.raw, "inflows", nothing)) if get(s, "to", nothing) == target))
        for conn in attached
            system_of(conn) != system && move_block!(m, qualified_name(conn), system)
        end
    end
    return target
end

"""
    move_blocks!(m, names, system="") -> OrderedDict

Moves several blocks into one sub-system as one edit: all of them or none.
Returns `old name => new name`.
"""
function move_blocks!(m::Model, names, system="")
    wanted = _unique_in_order(_name_arg(n) for n in names)
    _ed_check_system(m, system)
    for n in wanted
        block(m, n)
    end
    before = jcopy(m.raw)
    moved = OrderedDict{String,String}()
    try
        for n in wanted
            haskey(moved, n) && continue
            moved[n] = move_block!(m, n, system)
        end
    catch e
        if e isa EditError
            empty!(m.raw)
            for (k, v) in before
                m.raw[k] = v
            end
            _ed_invalidate!(m)
        end
        rethrow()
    end
    return moved
end

function _ed_guard_transport_parts(m::Model, going)
    for name in going
        hit = _ed_find(m, name)
        hit === nothing && continue
        raw = hit[2]
        role = get(raw, "transport", nothing)
        role in ("begin", "end", "number") || continue
        path = _norm_transport_of(_N(m), raw)
        path === nothing && continue
        all(b -> qualified_name(b) in going, (b for b in _ed_all_raw(m) if system_of(b) == path)) && continue
        throw(EditError("'$(_py_str(get(raw, "name", nothing)))' is the transport $role of '$path', and a transport is a " *
                        "chain from its Begin to its End. Delete the transport instead, with " *
                        "delete_system(path, contents=\"delete\")."))
    end
    return
end

"""
    delete_blocks!(m, names) -> Vector{String}

Deletes several blocks as one edit. The transfers and inflows of a
compartment (or a path, or waste packages) go with it. Anything outside the
set still reading one of them refuses the delete, naming what reads it --
two blocks reading each other can go together. Returns what was removed.
"""
function delete_blocks!(m::Model, names)
    wanted = _unique_in_order(_name_arg(n) for n in names)
    for n in wanted
        block(m, n)
    end
    going = OrderedDict{String,Nothing}(n => nothing for n in wanted)
    for n in wanted
        _ed_kind_of(m, n) in _ED_HOLDS_INVENTORY || continue
        for t in _py_iter(get(m.raw, "transfers", nothing))
            (get(t, "from", nothing) == n || get(t, "to", nothing) == n) && get!(going, qualified_name(t), nothing)
        end
        for s in _py_iter(get(m.raw, "inflows", nothing))
            get(s, "to", nothing) == n && get!(going, qualified_name(s), nothing)
        end
    end
    gone = Set{String}(keys(going))
    _ed_guard_transport_parts(m, collect(keys(going)))
    graph = references_graph(m)
    blocked = OrderedDict{String,Vector{String}}()
    for (referrer, targets) in graph
        referrer in gone && continue
        for t in targets
            t in gone && push!(get!(blocked, t, String[]), referrer)
        end
    end
    if !isempty(blocked)
        order = [n for n in keys(going) if haskey(blocked, n)]
        first_ = order[1]
        rest = length(blocked) - 1
        throw(EditError("'$first_' is still used by $(join(blocked[first_], ", "))." *
                        (rest > 0 ? " $rest more of the selection $(rest == 1 ? "is" : "are") too." : "") *
                        " Change those equations first.",
                        _unique_in_order(u for n in order for u in blocked[n])))
    end
    removed = String[]
    for q in keys(going)
        hit = _ed_find(m, q)
        hit === nothing && continue
        collection, raw = hit
        m.raw[collection] = Any[b for b in m.raw[collection] if b !== raw]
        _ed_invalidate!(m)
        lay = get(m.raw, "layout", nothing)
        lay isa AbstractDict && delete!(lay, q)
        push!(removed, q)
        list_name = collection == "compartments" ? COMPARTMENT_LIST : collection == "transfers" ? TRANSFER_LIST : nothing
        if list_name !== nothing
            for b in _ed_all_raw(m)
                if get(b, "entries", nothing) isa AbstractVector
                    b["entries"] = Any[e for e in b["entries"]
                                       if get(_py_or_dict(get(e, "index", nothing)), list_name, nothing) != q]
                end
            end
        end
    end
    return removed
end

"""
    delete_block!(m, name) -> Vector{String}

Deletes a block. A compartment's (or path's, or packages') transfers and
inflows go with it; anything else still reading it refuses the delete.
Returns the qualified names removed.
"""
delete_block!(m::Model, name) = delete_blocks!(m, (_name_arg(name),))

# --- sub-systems and transports -------------------------------------------------------------------------------

"""Every sub-system, as a dotted path, shallowest first."""
systems(m::Model) = _ed_systems(m)

"""The sub-systems that are transports: a chain of N compartments drawn as two."""
transports(m::Model) = String[p for p in _norm_transports(_N(m))]

function _ed_next_system_name(m::Model, parent, base, allow=nothing)
    existing = union(_ed_system_set(m), _ed_names(m))
    py_truthy(allow) && (existing = setdiff(existing, (allow,)))
    local_ = base
    i = 1
    while qualify(parent, local_) in existing
        local_ = "$base$i"
        i += 1
    end
    return local_
end

"""
    add_system!(m, name=nothing, parent="") -> String

Creates a sub-system inside `parent` (`""`: the top level) and returns its
path. A name another sub-system already has there is numbered (`Sub`
becomes `Sub1`); one a block has is refused.
"""
function add_system!(m::Model, name=nothing, parent="")
    _ed_check_system(m, parent)
    if py_truthy(parent) && parent in transports(m)
        throw(EditError("'$parent' is a transport, which is a chain of compartments and holds no sub-system of its own."))
    end
    if name !== nothing
        problem = _ed_name_problem(name)
        problem === nothing || throw(EditError(problem))
        _ed_find(m, qualify(parent, name)) !== nothing &&
            throw(EditError("'$name' is already used by a block in $(py_truthy(parent) ? _py_repr(parent) : "this model"). " *
                            "A sub-system and a block cannot share a name."))
    end
    path = qualify(parent, _ed_next_system_name(m, parent, name !== nothing ? name : "Sub"))
    get(m.raw, "systems", nothing) isa AbstractVector || (m.raw["systems"] = Any[systems(m)...])
    push!(m.raw["systems"], path)
    _ed_forget_systems!(m)
    return path
end

"""Renames a sub-system -- and so every block inside it -- following every reference. Returns the new path."""
function rename_system!(m::Model, path, new_name)
    py_truthy(path) || throw(EditError("The model itself has no name to change"))
    _ed_check_system(m, path)
    if !py_truthy(new_name) || base_name(new_name) != new_name || !is_valid_path(new_name)
        throw(EditError("'$(_py_str(new_name))' is not a valid name for a sub-system (letters, digits and underscore; " *
                        "must not start with a digit)"))
    end
    parent = parent_of(path)
    target = qualify(parent, new_name)
    target == path && return path
    target in _ed_system_set(m) &&
        throw(EditError("'$new_name' is already a sub-system of $(py_truthy(parent) ? _py_repr(parent) : "this model")"))
    _ed_find(m, target) !== nothing &&
        throw(EditError("'$new_name' is already used by a block in $(py_truthy(parent) ? _py_repr(parent) : "this model"). " *
                        "A sub-system and a block cannot share a name."))
    new_name in RESERVED && throw(EditError("'$new_name' is a reserved name."))
    return _ed_relocate_system!(m, path, target)
end

"""Moves a sub-system into another (`""`: the top level), numbering its name if taken there. Returns its new path."""
function move_system!(m::Model, path, parent="")
    py_truthy(path) || throw(EditError("The model itself cannot be moved"))
    _ed_check_system(m, path)
    _ed_check_system(m, parent)
    if py_truthy(parent) && is_within(parent, path)
        throw(EditError(parent == path ? "'$(base_name(path))' cannot be moved into itself" :
                        "'$(base_name(path))' cannot be moved into '$parent', which is inside it"))
    end
    if py_truthy(parent) && parent in transports(m)
        throw(EditError("'$parent' is a transport, which is a chain of compartments and holds no sub-system of its own."))
    end
    parent_of(path) == parent && return path
    taken = union(_ed_system_set(m), _ed_names(m))
    local_ = base_name(path)
    k = 1
    while qualify(parent, local_) in taken
        local_ = "$(base_name(path))$k"
        k += 1
    end
    return _ed_relocate_system!(m, path, qualify(parent, local_))
end

"""`path` with its prefix `old` replaced by `new` (`reparent`)."""
function _ed_reparent(path, old, new)
    path == old && return new
    if py_truthy(old) && startswith(path, old * SEPARATOR)
        rest = path[nextind(path, ncodeunits(old) + 1):end]
        return qualify(new, rest)
    end
    py_truthy(old) || return py_truthy(path) ? qualify(new, path) : new
    return path
end

function _ed_disabled_systems(m::Model)
    out = String[]
    for p in _py_iter(get(m.raw, "disabled_systems", nothing))
        p === nothing && continue
        s = String(strip(_py_str(p)))
        isempty(s) || push!(out, s)
    end
    return out
end

function _ed_relocate_system!(m::Model, path, target)
    moved = OrderedDict{String,String}()
    for b in _ed_all_raw(m)
        is_within(system_of(b), path) &&
            (moved[qualified_name(b)] = qualify(_ed_reparent(system_of(b), path, target), get(b, "name", "")))
    end
    _ed_retarget_all!(m, q -> get(moved, q, nothing), (s, blk) -> _ed_reparent(s, path, target), collect(values(moved)))
    _ed_retarget_layout!(m, q -> get(moved, q, nothing),
                         canvas -> is_within(canvas, path) ? _ed_reparent(canvas, path, target) : canvas)
    systems_before = systems(m)
    for b in _ed_all_raw(m)
        is_within(system_of(b), path) && (b["system"] = _ed_reparent(system_of(b), path, target))
    end
    m.raw["systems"] = _unique_in_order(_ed_reparent(p, path, target) for p in systems_before)
    trs = transports(m)
    isempty(trs) || (m.raw["transports"] = Any[_ed_reparent(p, path, target) for p in trs])
    ds = _ed_disabled_systems(m)
    isempty(ds) || (m.raw["disabled_systems"] = Any[_ed_reparent(p, path, target) for p in ds])
    lay = get(m.raw, "layout", nothing)
    if lay isa AbstractDict && get(lay, path, nothing) !== nothing
        v = pop!(lay, path)
        lay[target] = v
    end
    for sh in _py_iter(get(m.raw, "shapes", nothing))
        sh isa AbstractDict || continue
        s = _py_or_text(get(sh, "system", nothing))
        if is_within(s, path)
            to = _ed_reparent(s, path, target)
            py_truthy(to) ? (sh["system"] = to) : delete!(sh, "system")
        end
    end
    _ed_invalidate!(m)
    return target
end

"""
    delete_system!(m, path, contents="move") -> String

Removes a sub-system. Its contents move out to the sub-system around it
(numbered where names collide), or are deleted with `contents="delete"` --
which a transport always needs. Returns the parent's path.
"""
function delete_system!(m::Model, path, contents="move")
    py_truthy(path) || throw(EditError("The model itself cannot be removed"))
    _ed_check_system(m, path)
    contents in ("move", "delete") || throw(EditError("contents is 'move' or 'delete'"))
    parent = parent_of(path)
    systems_before = systems(m)
    systems_out = OrderedDict{String,String}()
    if contents == "delete"
        delete_blocks!(m, [qualified_name(b) for b in _ed_all_raw(m) if is_within(system_of(b), path)])
        shapes_ = get(m.raw, "shapes", nothing)
        if shapes_ isa AbstractVector
            m.raw["shapes"] = Any[sh for sh in shapes_
                                  if !(sh isa AbstractDict && is_within(_py_or_text(get(sh, "system", nothing)), path))]
        end
    else
        if path in transports(m)
            throw(EditError("'$path' is a transport, and a transport is a chain from its Begin to its End rather than a " *
                            "place blocks are kept: its parts cannot be let out as ordinary blocks. Delete it, with " *
                            "everything in it (contents=\"delete\")."))
        end
        taken_systems = Set{String}(p for p in systems_before if !is_within(p, path))
        nested = sort([p for p in systems_before if is_within(p, path) && p != path]; by=p -> length(path_parts(p)))
        for p in nested
            frm = parent_of(p)
            home = frm == path ? parent : get(systems_out, frm, frm)
            local_ = base_name(p)
            k = 1
            while qualify(home, local_) in taken_systems
                local_ = "$(base_name(p))$k"
                k += 1
            end
            to = qualify(home, local_)
            push!(taken_systems, to)
            systems_out[p] = to
        end
        home_of(system) = system == path ? parent : get(systems_out, system, _ed_reparent(system, path, parent))
        moved = OrderedDict{String,String}()
        taken = _ed_names(m)
        for b in _ed_all_raw(m)
            is_within(system_of(b), path) || continue
            to_sys = home_of(system_of(b))
            nm = _py_str(get(b, "name", ""))
            local_ = nm
            k = 1
            while qualify(to_sys, local_) in taken
                local_ = "$nm$k"
                k += 1
            end
            push!(taken, qualify(to_sys, local_))
            moved[qualified_name(b)] = qualify(to_sys, local_)
        end
        _ed_retarget_all!(m, q -> get(moved, q, nothing), (s, blk) -> is_within(s, path) ? home_of(s) : s,
                          collect(values(moved)))
        _ed_retarget_layout!(m, q -> get(moved, q, nothing))
        for b in _ed_all_raw(m)
            was = qualified_name(b)
            haskey(moved, was) || continue
            now = moved[was]
            b["system"] = parent_of(now)
            b["name"] = base_name(now)
            py_truthy(b["system"]) || delete!(b, "system")
        end
        lay = get(m.raw, "layout", nothing)
        for (was, now) in systems_out
            if lay isa AbstractDict && get(lay, was, nothing) !== nothing
                v = pop!(lay, was)
                lay[now] = v
            end
        end
        for sh in _py_iter(get(m.raw, "shapes", nothing))
            sh isa AbstractDict || continue
            s = _py_or_text(get(sh, "system", nothing))
            if is_within(s, path)
                to = _ed_reparent(s, path, parent)
                py_truthy(to) ? (sh["system"] = to) : delete!(sh, "system")
            end
        end
    end
    keep(p) = p == path ? nothing : is_within(p, path) ? get(systems_out, p, nothing) : p
    _ed_invalidate!(m)
    m.raw["systems"] = _unique_in_order(q for q in (keep(p) for p in systems(m)) if py_truthy(q))
    if !isempty(_ed_disabled_systems(m))
        ds = Any[q for q in (keep(p) for p in _ed_disabled_systems(m)) if py_truthy(q)]
        isempty(ds) ? delete!(m.raw, "disabled_systems") : (m.raw["disabled_systems"] = ds)
    end
    trs = transports(m)
    isempty(trs) || (m.raw["transports"] = Any[q for q in (keep(p) for p in trs) if py_truthy(q)])
    lay = get(m.raw, "layout", nothing)
    lay isa AbstractDict && delete!(lay, path)
    _ed_invalidate!(m)
    return parent
end

"""Whether a sub-system takes part in the run: neither it nor any sub-system around it is switched off."""
function system_enabled(m::Model, path)
    py_truthy(path) || return true
    return !any(p -> is_within(path, p), _ed_disabled_systems(m))
end

"""Switches a whole sub-system on or off; its blocks keep their own switches."""
function set_system_enabled!(m::Model, path, on)
    (py_truthy(path) && path in _ed_system_set(m)) || throw(EditError("No sub-system named '$(_py_str(path))'"))
    off = Any[p for p in _ed_disabled_systems(m) if p != path]
    py_truthy(on) || push!(off, path)
    isempty(off) ? delete!(m.raw, "disabled_systems") : (m.raw["disabled_systems"] = off)
    return nothing
end

"""
    add_transport!(m, name="Transport", parent=""; number="5", position=nothing) -> String

Makes a transport: a sub-system standing for a chain of `number` identical
compartments, with the four blocks the application puts in one -- the Begin
and End compartments, N and the element counter i. Returns its path.
"""
function add_transport!(m::Model, name="Transport", parent=""; number="5", position=nothing)
    path = add_system!(m, name !== nothing ? name : "Transport", parent)
    get(m.raw, "transports", nothing) isa AbstractVector || (m.raw["transports"] = Any[transports(m)...])
    push!(m.raw["transports"], path)
    _ed_forget_systems!(m)
    position === nothing || _set_position!(m, path, _position_of(position))
    begin_ = add_compartment!(m, unique_name(m, "Begin", path); system=path, position=(80, 90))
    begin_.raw["transport"] = "begin"
    end_ = add_compartment!(m, unique_name(m, "End", path); system=path, position=(420, 90))
    end_.raw["transport"] = "end"
    n = add_expression!(m, unique_name(m, "N", path), number; system=path)
    n.raw["transport"] = "number"
    n.raw["index_lists"] = Any[]
    _set_position!(m, qualified_name(n.raw), (80, 210))
    i = add_expression!(m, unique_name(m, "i", path), "1"; system=path)
    i.raw["transport"] = "counter"
    i.raw["index_lists"] = Any[]
    _set_position!(m, qualified_name(i.raw), (420, 210))
    return path
end

"""
    add_transport_operation!(m, system, name=nothing; operation="mean", argument="all", position=nothing) -> Expression

Adds an operation over a transport's chain: the `sum` or `mean` of its
compartments, read as a value (`argument="all"`) or called with a position
along it (`"point"`) or two (`"range"`).
"""
function add_transport_operation!(m::Model, system, name=nothing; operation="mean", argument="all", position=nothing)
    system in transports(m) ||
        throw(EditError("'$(py_truthy(system) ? _py_str(system) : "The top level")' is not a transport, so an operation " *
                        "over its chain has nothing to work on."))
    operation in _BK_TRANSPORT_OPERATIONS ||
        throw(EditError("'$(_py_str(operation))' is not a transport operation ($(join(_BK_TRANSPORT_OPERATIONS, ", ")))"))
    argument in _BK_TRANSPORT_ARGUMENTS ||
        throw(EditError("'$(_py_str(argument))' is not a way of reading one ($(join(_BK_TRANSPORT_ARGUMENTS, ", ")))"))
    b = _norm_transport_parts(_N(m), system).begin_
    begin_ = b === nothing ? JDict() : b
    n = name !== nothing ? name : unique_name(m, "TransportOp", system)
    raw = JDict("name" => n, "equation" => "0", "unit" => get(begin_, "unit", ""),
                "index_lists" => _list_of(get(begin_, "index_lists", nothing)),
                "transport" => "operation", "operation" => operation, "argument" => argument)
    return _ed_append!(m, "expressions", raw, system, position)
end

# --- layout, shapes, derived outputs ----------------------------------------------------------------------------

function _set_position!(m::Model, name, xy)
    lay = layout(m)
    entry = get(lay, name, nothing)
    if xy === nothing
        if entry isa AbstractDict
            delete!(entry, "x")
            delete!(entry, "y")
            isempty(entry) && delete!(lay, name)
        end
        return
    end
    entry isa AbstractDict || (entry = JDict())
    entry["x"] = _ed_js_round(xy[1])
    entry["y"] = _ed_js_round(xy[2])
    lay[name] = entry
    return
end

function _set_size!(m::Model, name, wh)
    lay = layout(m)
    entry = get(lay, name, nothing)
    if wh === nothing
        if entry isa AbstractDict
            delete!(entry, "w")
            delete!(entry, "h")
        end
        return
    end
    entry isa AbstractDict || (entry = JDict("x" => 0, "y" => 0))
    w, h = _ed_pyfloat(wh[1]), _ed_pyfloat(wh[2])
    entry["w"] = _ed_js_round(min(520, max(60, w)))
    entry["h"] = _ed_js_round(min(320, max(32, h)))
    lay[name] = entry
    return
end

"""Where a sub-system's node is drawn on its parent's canvas."""
function system_position(m::Model, path)
    entry = get(layout(m), path, nothing)
    return (entry isa AbstractDict && haskey(entry, "x") && haskey(entry, "y")) ? (entry["x"], entry["y"]) : nothing
end

"""Places a sub-system's node on its parent's canvas (`nothing` forgets it)."""
function set_system_position!(m::Model, path, xy)
    _ed_check_system(m, path)
    _set_position!(m, path, xy === nothing ? nothing : _position_of(xy))
    return nothing
end

"""The annotations drawn on the canvases, in drawing order."""
shapes(m::Model) = Shape[Shape(m, s) for s in _py_iter(get(m.raw, "shapes", nothing)) if s isa AbstractDict]

"""
    add_shape!(m, figure, x=0, y=0, w=180, h=120; system="", style...) -> Shape

Draws a shape on a sub-system's canvas: `figure` is `rect`, `ellipse`,
`arrow`, `line`, `sticky` or another of the application's figures, `(x, y)`
its top-left corner. `style` sets `fill`, `line`, `line_width`, `dash`,
`text` and the rest of what a shape has.
"""
function add_shape!(m::Model, figure, x=0, y=0, w=180, h=120; system="", style...)
    name = String(strip(_py_or_text(figure)))
    isempty(name) && throw(EditError("A shape needs a figure to draw"))
    _ed_check_system(m, system)
    taken = Set{Any}(get(s, "id", nothing) for s in _py_iter(get(m.raw, "shapes", nothing)) if s isa AbstractDict)
    k = 1
    while "sh$k" in taken
        k += 1
    end
    raw = JDict("id" => "sh$k", "figure" => name)
    py_truthy(system) && (raw["system"] = system)
    for (key, v) in ("x" => _ed_js_round(x), "y" => _ed_js_round(y), "w" => _ed_js_round(w), "h" => _ed_js_round(h),
                     "fill" => "slate", "line" => "slate", "line_width" => 2, "dash" => "solid")
        raw[key] = v
    end
    if name == "sticky"
        for (key, v) in ("fill" => "amber", "line" => "none", "text_font" => "scribble", "text_align" => "left",
                         "text_size" => 18)
            raw[key] = v
        end
    end
    get(m.raw, "shapes", nothing) isa AbstractVector || (m.raw["shapes"] = Any[])
    push!(m.raw["shapes"], raw)
    shape = Shape(m, raw)
    try
        update!(shape; style...)
    catch e
        e isa EditError && (m.raw["shapes"] = Any[s for s in m.raw["shapes"] if s !== raw])
        rethrow()
    end
    return shape
end

"""Removes a shape by its id."""
function remove_shape!(m::Model, shape_id)
    shapes_ = _py_iter(get(m.raw, "shapes", nothing))
    for (k, s) in enumerate(shapes_)
        if s isa AbstractDict && get(s, "id", nothing) == shape_id
            deleteat!(m.raw["shapes"], k)
            return nothing
        end
    end
    throw(EditError("No shape '$(_py_str(shape_id))'"))
end

"""Numbers read off the finished curves -- a peak, when it peaked, a total -- live: each `{name, kind, of, at?, period?}`."""
function derived(m::Model)
    get(m.raw, "derived", nothing) isa AbstractVector || (m.raw["derived"] = Any[])
    return m.raw["derived"]
end

"""
    add_derived!(m, name, kind, of; at=nothing, period=nothing) -> JDict

Adds a number read off a finished curve: `kind` is one of `max`, `min`,
`time_of_max`, `at_time`, `integral`, `period_mean`, `period_sum`,
`period_change`, `period_rate`; `of` the series' label as the chart spells
it (`"Soil [Cs-137]"`); `at` for `at_time`, `period` for the period kinds.
"""
function add_derived!(m::Model, name, kind, of; at=nothing, period=nothing)
    isempty(strip(_py_or_text(name))) && throw(EditError("A derived output needs a name"))
    kind in _ED_DERIVED_KINDS || throw(EditError("'$(_py_str(kind))' is not one of $(join(_ED_DERIVED_KINDS, ", "))."))
    isempty(strip(_py_or_text(of))) && throw(EditError("It does not say which series it is of."))
    d = JDict("name" => name, "kind" => kind, "of" => of)
    if kind == "at_time"
        (at === nothing || !isfinite(_model_js_number(at))) &&
            throw(EditError("'$(_py_str(at))' is not a time. It has to be a number of the run's time unit."))
        d["at"] = at
    end
    if kind in _ED_PERIOD_KINDS
        (period === nothing || !(_model_js_number(period) > 0)) &&
            throw(EditError("'$(_py_str(period))' is not a period. It has to be a length of time greater than zero."))
        d["period"] = period
    end
    push!(derived(m), d)
    return d
end

"""Removes a derived output by its name."""
function remove_derived!(m::Model, name)
    before = length(derived(m))
    m.raw["derived"] = Any[d for d in derived(m) if get(d, "name", nothing) != name]
    length(m.raw["derived"]) == before && throw(EditError("No derived output named '$(_py_str(name))'"))
    return nothing
end

# --- review tracking ----------------------------------------------------------------------------------------------

"""Whether the model tracks which definitions have been reviewed."""
function review_tracking(m::Model)
    sim = get(m.raw, "simulation", nothing)
    return py_truthy(sim) && get(sim, "qa", nothing) === true
end

function set_review_tracking!(m::Model, on)
    sim = simulation(m)
    py_truthy(on) ? (sim["qa"] = true) : delete!(sim, "qa")
    return nothing
end

"""`JSON.stringify(value, allow)`: the property list applies at every depth."""
function _stringify_allowed(value, allow)
    value === nothing && return "null"
    value isa Bool && return value ? "true" : "false"
    value isa Real && return js_number(value)
    value isa AbstractString && return json_text(value; indent=0)
    if value isa AbstractDict
        return "{" * join((json_text(k; indent=0) * ":" * _stringify_allowed(value[k], allow) for k in allow if haskey(value, k)), ",") * "}"
    end
    (value isa AbstractVector || value isa Tuple) && return "[" * join((_stringify_allowed(v, allow) for v in value), ",") * "]"
    return "null"
end

"""
    review_stamp(block) -> String

What a review of a block covers, as the application stamps it: everything
but where and how it is drawn, its comment and the record itself.
"""
function review_stamp(blk)
    raw = blk isa Block ? blk.raw : blk
    keep = JDict(k => v for (k, v) in raw if !(k in _ED_NOT_REVIEWED))
    if get(raw, "entries", nothing) isa AbstractVector
        keep["entries"] = Any[e isa AbstractDict ? JDict(k => v for (k, v) in e if !(k in _ED_NOT_REVIEWED)) : e
                              for e in raw["entries"]]
    end
    return _stringify_allowed(keep, sort!(collect(keys(keep))))
end
review_stamp(::Model, blk) = review_stamp(blk)

"""
    record_review!(m, name, status="approved"; by="", reviewer="", comment="", locked=false, at=nothing)

Records an approval (`status="approved"`) or a request for review
(`"review"`) on a block, stamped as the application stamps it. `locked`
(approvals only) makes the application refuse edits to it.
"""
function record_review!(m::Model, name, status="approved"; by="", reviewer="", comment="", locked=false, at=nothing)
    b = block(m, name)
    qa = get(b.raw, "qa", nothing)
    if !(qa isa AbstractDict)
        qa = JDict("history" => Any[])
        b.raw["qa"] = qa
    end
    entry = JDict("status" => status == "approved" ? "approved" : "review",
                  "by" => String(strip(_py_or_text(by))), "reviewer" => String(strip(_py_or_text(reviewer))),
                  "comment" => String(strip(_py_or_text(comment))),
                  "at" => py_truthy(at) ? at : model_stamp())
    qa["status"] = entry["status"]
    qa["stamp"] = review_stamp(b)
    qa["locked"] = entry["status"] == "approved" && py_truthy(locked)
    history = Any[_py_iter(get(qa, "history", nothing))..., entry]
    qa["history"] = length(history) > 50 ? history[end-49:end] : history
    return qa
end

"""Forgets a block's review record entirely."""
clear_review!(m::Model, name) = (delete!(block(m, name).raw, "qa"); nothing)

"""
    review_status(m) -> OrderedDict

Every block's review state: `approved`; `stale` (changed since it was
approved); `review` (marked so, or reads something that is not approved);
`none`.
"""
function review_status(m::Model)
    out = OrderedDict{String,String}()
    idx = _ed_idx(m)
    for q in _ed_idx_order(m)
        raw = idx[q][2]
        qa = get(raw, "qa", nothing)
        if !(qa isa AbstractDict) || !py_truthy(get(qa, "status", nothing))
            out[q] = "none"
        elseif qa["status"] != "approved"
            out[q] = "review"
        elseif get(qa, "stamp", nothing) != review_stamp(raw)
            out[q] = "stale"
        else
            out[q] = "approved"
        end
    end
    graph = references_graph(m)
    for _ in 1:(length(out) + 1)
        moved = false
        for q in collect(keys(out))
            out[q] == "approved" || continue
            if any(d -> get(out, d, "approved") != "approved", get(graph, q, String[]))
                out[q] = "review"
                moved = true
            end
        end
        moved || break
    end
    return out
end

# --- size and checks -------------------------------------------------------------------------------------------

"""How many state variables the solver will integrate, as the application counts them."""
function state_count(m::Model)
    N = _N(m)
    n = 0
    for collection in ("compartments", "running_means")
        for b in _py_iter(get(m.raw, collection, nothing))
            n += combination_count(m, _effective_dims(N, b))
        end
    end
    for f in _py_iter(get(m.raw, "farfields", nothing))
        n += _ed_farfield_cells(f) * combination_count(m, _effective_dims(N, f))
    end
    for w in _py_iter(get(m.raw, "waste_packages", nothing))
        n += 2 * combination_count(m, _effective_dims(N, w))
    end
    n += length(_py_iter(get(m.raw, "events", nothing)))
    sim = get(m.raw, "simulation", nothing)
    if py_truthy(sim) && py_truthy(get(sim, "mass_balance", nothing))
        mat = material_dimension(m)
        n += 6 * ((py_truthy(mat) ? combination_count(m, Any[mat]) : 0) + 1)
    end
    return n
end

_ed_count_number(v) = (f = _ed_pyfloat(v); f === nothing ? NaN : f)

function _ed_farfield_extra_cells(block)
    nb = get(block, "n_b", nothing)
    if nb === nothing || (nb isa AbstractString && isempty(strip(nb)))
        _ed_count_number(get(block, "o_b", nothing)) != 4 && return 0
        n = _ed_count_number(get(block, "n_f", nothing))
        p = _ed_count_number(get(block, "pe", nothing))
        (_is_whole_float(n) && n >= 1) || return 0
        (p > 0 && p != Inf) || (p = 10.0)
        rho = (2 * n - p) / (2 * n + p)
        rho > 0 || return 0
        k, left = 0, 1.0
        while left > 0.1 && k < 10000
            left *= rho
            k += 1
        end
        return k
    end
    return trunc(Int, _ed_count_number(nb))
end

function _ed_farfield_cells(block)
    method = get(block, "method", nothing)
    method == "semi-analytical" && return 1
    (method === nothing || method == "" || method == "discretized") || return 0
    nf = trunc(Int, _ed_count_number(get(block, "n_f", 20)))
    nm = trunc(Int, _ed_count_number(get(block, "n_m", 20)))
    return (nf + _ed_farfield_extra_cells(block)) * (nm + 1)
end

"""
    put_values!(m, values) -> Int

Writes `{"key", "value"}` pairs into the model, `key` a slot label as the
sampler and the optimiser spell it (`"k"`, `"Kd[I-129]"`): the block's own
value, or its value at the index the label names. A key naming no block, a
value that is not a finite number and a value the block refuses are passed
over. Returns how many were written.
"""
function put_values!(m::Model, values)
    n = 0
    for v in values
        value = get(v, "value", nothing)
        (value isa Bool || !(value isa Real) || !isfinite(value)) && continue
        key = get(v, "key", nothing)
        mt = match(r"^([^\[]+)((?:\[[^\]]*\])*)$", key === nothing ? "" : _py_str(key))
        mt === nothing && continue
        b = get_block(m, String(mt.captures[1]))
        b === nothing && continue
        lists = _list_of(get(b.raw, "index_lists", nothing))
        parts_ = [String(c.captures[1]) for c in eachmatch(r"\[([^\]]*)\]", mt.captures[2])]
        at = JDict(lists[i] => part for (i, part) in enumerate(parts_) if i <= length(lists))
        try
            if isempty(at)
                set_value!(b, js_text(value), nothing, "value")
            else
                set_value!(b, js_text(value), at, "value")
            end
        catch e
            (e isa EditError || e isa ArgumentError || e isa KeyError || e isa MethodError) && continue
            rethrow()
        end
        n += 1
    end
    return n
end
