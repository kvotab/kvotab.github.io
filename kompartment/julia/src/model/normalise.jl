# A model brought into the shape Kompartment works on, as the application
# does when it opens one (kompartment/python/kompartment/model.py: what
# `Model(raw)` does after `migrate_keys`, and `Model.settle`).
#
# Reading a file: the `nuclides` shorthand written out as the two material
# lists; a block's `default` and the per-nuclide maps of older files
# (`values_by_nuclide`, `initial` as a dictionary) as per-index entries; an
# entry's copy of its transfer's `multiply_by_donor` dropped where it agrees;
# the material catalogue and the radionuclides present; transfer ends written
# as qualified names; every block's dimensions written down. Then what
# follows from the model -- a flux's dimensions from its two ends (and a
# transport's from what it is connected to), a blank compartment unit on a
# material dimension from the materials, every transfer's and inflow's unit
# from its donor and the time unit -- brought up to date, which `settle!`
# does again (with the diagram entries of blocks that no longer exist
# dropped) whenever the model is written.
#
# The rules are Python's, read with Python's truthiness: an empty list or
# dictionary is false here, where JavaScript would call it true.

"""Whether a value is true as Python reads it (`if v:`): `nothing`, `false`,
zero and empty text, lists and dictionaries are not."""
function py_truthy(v)
    v === nothing && return false
    v isa Bool && return v
    v isa Real && return !iszero(v)
    (v isa AbstractString || v isa AbstractVector || v isa AbstractDict || v isa Tuple) && return !isempty(v)
    return true
end

"""The value key each collection stores per index (`ENTRY_KEY` in edit.js), by collection."""
const _ENTRY_KEY_BY_COLLECTION = Dict(
    "compartments" => "initial", "transfers" => "rate", "expressions" => "equation", "parameters" => "value",
    "inflows" => "rate", "lookups" => "points", "index_reductions" => "target", "block_reductions" => "targets",
    "functions" => "equation", "farfields" => "kd_f", "waste_packages" => "inventory", "events" => "at")

"""The collections whose blocks hold an inventory: what a flux may run between."""
const _INVENTORY_COLLECTIONS = ("compartments", "farfields", "waste_packages")

"""The top of a model file, in the order it is written (`HEADER_KEYS` in src/domain/edit.js)."""
const HEADER_KEYS = ("name", "description", "author", "created", "saved")

const _EDGE_PREFIX = "edge:"

"""A model's dictionary being normalised, and its blocks by qualified name (built once: nothing here renames one)."""
mutable struct _ModelNorm
    raw::AbstractDict
    idx::Union{Nothing,Dict{String,Tuple{String,Any}}}
end
_ModelNorm(raw::AbstractDict) = _ModelNorm(raw, nothing)

# --- reading values as Python does --------------------------------------------------------

"""Python's `str(v)` (a float as its repr)."""
_norm_str(v) = v isa AbstractString ? String(v) : py_text(v)

"""`v`, or `default` where Python reads `v` as false (`v or default`)."""
_py_or(v, default) = py_truthy(v) ? v : default

"""`String(v ?? '')`, as the application reads a unit (`_js_string` in model.py)."""
function _js_string(v)
    v === nothing && return ""
    v isa Bool && return v ? "true" : "false"
    v isa Real && return js_number(v)
    return _norm_str(v)
end

"""`Number(v)` as model.py's `_js_number` reads a per-nuclide value: a number stays as it is."""
function _model_js_number(v)
    v === nothing && return NaN
    v isa Bool && return v ? 1.0 : 0.0
    v isa Real && return v
    s = strip(_norm_str(v))
    isempty(s) && return 0.0
    return py_float(s)
end

"""What `for x in (v or [])` goes over in Python: a list's items, a dictionary's keys, a text's characters."""
function _py_iter(v)
    py_truthy(v) || return ()
    (v isa AbstractVector || v isa Tuple) && return v
    v isa AbstractDict && return collect(Any, keys(v))
    v isa AbstractString && return Any[string(c) for c in v]
    return ()
end

"""A collection's list as `raw.get(key) or []` gives it."""
_norm_list(raw, key) = _py_iter(get(raw, key, nothing))

"""A vector that can take any value, `v` itself when it already can."""
_any_vector(v) = v isa Vector{Any} ? v : collect(Any, v)

_name_text(n) = n isa AbstractString ? String(n) : n === nothing ? "" : _norm_str(n)

# --- blocks by name -------------------------------------------------------------------------

function _norm_index!(N::_ModelNorm)
    if N.idx === nothing
        idx = Dict{String,Tuple{String,Any}}()
        for collection in COLLECTIONS
            for b in _norm_list(N.raw, collection)
                b isa AbstractDict || continue
                q = qualified_name(b)
                haskey(idx, q) || (idx[q] = (collection, b))
            end
        end
        N.idx = idx
    end
    return N.idx
end

_norm_find(N::_ModelNorm, name) = name === nothing ? nothing : get(_norm_index!(N), name, nothing)

# --- index lists ----------------------------------------------------------------------------

_stored_lists(N::_ModelNorm) = Any[l for l in _norm_list(N.raw, "index_lists") if l isa AbstractDict]

"""Every list, the derived ones (Elements, Compartments, Transfers) included. The two block lists are
not given their indices: nothing that reads this list needs them."""
function _all_lists(N::_ModelNorm)
    out = derive_elements(_stored_lists(N))
    for (name, collection, what) in ((COMPARTMENT_LIST, "compartments", "compartment"),
                                     (TRANSFER_LIST, "transfers", "transfer"))
        any(l -> jget(l, "name") == name, out) && continue
        any(b -> b isa AbstractDict && !py_truthy(get(b, "hidden", nothing)) &&
                 get(b, "name", nothing) isa AbstractString && !isempty(b["name"]),
            _norm_list(N.raw, collection)) || continue
        push!(out, JDict("name" => name, "derived" => true, "auto" => collection,
                         "note" => "One index per $what in the model — the $(what)s are the indices, so there is " *
                                   "nothing to edit here. Add a $what and this list gains an index; rename one and " *
                                   "the index follows."))
    end
    return out
end

_list_any(N::_ModelNorm, name) = find_list(_all_lists(N), name)

_material_list_raw(N::_ModelNorm) = findfirst_value(l -> py_truthy(get(l, "for_contaminants", nothing)), _stored_lists(N))

function _nuclide_list_raw(N::_ModelNorm)
    lists = _stored_lists(N)
    l = findfirst_value(l -> py_truthy(get(l, "for_nuclides", nothing)), lists)
    l === nothing || return l
    return findfirst_value(l -> py_truthy(get(l, "for_contaminants", nothing)), lists)
end

"""What a block is indexed by when nothing says otherwise: the radionuclides, or the catalogue when there
are none, or nothing when the model has no materials at all."""
function _material_dimension(N::_ModelNorm)
    nuc = findfirst_value(l -> py_truthy(get(l, "for_nuclides", nothing)), _stored_lists(N))
    explicit = (nuc !== nothing && py_truthy(get(nuc, "indices", nothing))) ? nuc : _material_list_raw(N)
    if explicit !== nothing
        return py_truthy(get(explicit, "indices", nothing)) ? explicit["name"] : nothing
    end
    py_truthy(get(N.raw, "nuclides", nothing)) && return NUCLIDE_LIST
    return nothing
end

function _decay_unit(N::_ModelNorm)
    u = strip(_js_string(get(N.raw, "decay_unit", nothing)))
    return u in ("Bq", "mol") ? String(u) : "Bq"
end

function _unique_list_name(N::_ModelNorm, base::String)
    _list_any(N, base) === nothing && return base
    for i in 1:999
        _list_any(N, "$base$i") === nothing && return "$base$i"
    end
    error("Could not find a free name based on '$base'")
end

# --- dimensions -----------------------------------------------------------------------------

function _effective_dims(N::_ModelNorm, b)
    il = get(b, "index_lists", nothing)
    il isa AbstractVector && return collect(Any, il)
    (haskey(b, "actions") || haskey(b, "timing")) && return Any[]
    if haskey(b, "from") || haskey(b, "to")
        shared = _transfer_dims(N, b)
        shared !== nothing && return collect(Any, shared.dims)
    end
    name = _material_dimension(N)
    (py_truthy(name) && get(b, "per_nuclide", nothing) !== false) && return Any[name]
    return Any[]
end

function _end_dims(N::_ModelNorm, name)
    name === nothing && return nothing
    hit = _norm_find(N, name)
    (hit === nothing || !(hit[1] in _INVENTORY_COLLECTIONS)) && return nothing
    b = hit[2]
    il = get(b, "index_lists", nothing)
    il isa AbstractVector && return collect(Any, il)
    material = _material_dimension(N)
    return (py_truthy(material) && get(b, "per_nuclide", nothing) !== false) ? Any[material] : Any[]
end

_transfer_dims(N::_ModelNorm, b, lists=nothing) =
    shared_dims(lists === nothing ? _all_lists(N) : lists, _end_dims(N, get(b, "from", nothing)),
                _end_dims(N, get(b, "to", nothing)))

function _narrows(N::_ModelNorm, dims, derived, lists=nothing)
    length(dims) != length(derived) && return false
    lists === nothing && (lists = _all_lists(N))
    return all(d -> any(w -> d == w || jget(find_list(lists, d), "sub_set_of") == w, derived), dims)
end

"""Drops the entries keyed by a list a block is no longer indexed by."""
function _prune_entries!(block, dims)
    ents = get(block, "entries", nothing)
    py_truthy(ents) || return
    block["entries"] = Any[e for e in _py_iter(ents) if all(k -> k in dims, _py_iter(jget(e, "index")))]
    return
end

function _sync_connection_dims!(N::_ModelNorm, name=nothing)
    lists = _all_lists(N)
    function dims_of(n)
        hit = _norm_find(N, n)
        return hit === nothing ? Any[] : _effective_dims(N, hit[2])
    end
    function wanted(t)
        shared = _transfer_dims(N, t, lists)
        shared !== nothing && return collect(Any, shared.dims)
        union_ = Any[]
        for d in Iterators.flatten((dims_of(get(t, "from", nothing)), dims_of(get(t, "to", nothing))))
            d in union_ || push!(union_, d)
        end
        return union_
    end
    touched = Any[]
    for collection in ("transfers", "inflows")
        for t in _norm_list(N.raw, collection)
            t isa AbstractDict || continue
            if name !== nothing && get(t, "to", nothing) != name &&
               (collection == "inflows" || get(t, "from", nothing) != name)
                continue
            end
            want = wanted(t)
            have = collect(Any, _py_iter(get(t, "index_lists", nothing)))
            _narrows(N, have, want, lists) && continue
            if have != want
                t["index_lists"] = want
                _prune_entries!(t, want)
                push!(touched, get(t, "name", nothing))
            end
        end
    end
    return touched
end

# --- transports -----------------------------------------------------------------------------

"""The transports a model declares, by path."""
function _norm_transports(N::_ModelNorm)
    out = String[]
    for p in _norm_list(N.raw, "transports")
        path = p isa AbstractString ? p : p isa AbstractDict ? get(p, "name", nothing) : nothing
        py_truthy(path) && push!(out, string(path))
    end
    return out
end

"""A transport's parts as the model holds them: the first Begin, End, number and counter, and every operation."""
function _norm_transport_parts(N::_ModelNorm, path)
    found = Dict{String,Any}("begin" => nothing, "end" => nothing, "number" => nothing, "counter" => nothing)
    operations = Any[]
    for (collection, roles) in (("compartments", ("begin", "end")), ("expressions", ("number", "counter", "operation")))
        for b in _norm_list(N.raw, collection)
            b isa AbstractDict || continue
            system_of(b) != path && continue
            role = get(b, "transport", nothing)
            role in roles || continue
            if role == "operation"
                push!(operations, b)
            elseif found[role] === nothing
                found[role] = b
            end
        end
    end
    return (begin_=found["begin"], end_=found["end"], number=found["number"], counter=found["counter"],
            operations=operations)
end

function _norm_transport_of(N::_ModelNorm, b)
    py_truthy(get(b, "transport", nothing)) || return nothing
    path = system_of(b)
    return (py_truthy(path) && path in _norm_transports(N)) ? path : nothing
end

"""The other ends and the operations of a transport follow one end's new dimensions."""
function _sync_transport_dims!(N::_ModelNorm, raw_b, dims)
    get(raw_b, "transport", nothing) in ("begin", "end") || return Any[]
    path = _norm_transport_of(N, raw_b)
    py_truthy(path) || return Any[]
    p = _norm_transport_parts(N, path)
    followed = Any[]
    for other in Any[p.begin_, p.end_, p.operations...]
        (other === nothing || other === raw_b) && continue
        sort(collect(Any, _py_iter(get(other, "index_lists", nothing)))) == sort(collect(Any, dims)) && continue
        other["index_lists"] = collect(Any, dims)
        _prune_entries!(other, dims)
        q = qualified_name(other)
        push!(followed, q)
        get(other, "transport", nothing) != "operation" && append!(followed, _sync_connection_dims!(N, q))
    end
    return followed
end

"""What flows into a transport's two ends from outside it, and what they flow out to."""
function _transport_ends(N::_ModelNorm, path)
    p = _norm_transport_parts(N, path)
    inside(n) = (hit = _norm_find(N, n); hit !== nothing && system_of(hit[2]) == path)
    heads = Set{String}(qualified_name(b) for b in (p.begin_, p.end_) if b !== nothing)
    frm = Any[]
    to = Any[]
    for t in _norm_list(N.raw, "transfers")
        t isa AbstractDict || continue
        tf, tt = get(t, "from", nothing), get(t, "to", nothing)
        (tt !== nothing && tt in heads && tf !== nothing && !inside(tf)) && push!(frm, tf)
        (tf !== nothing && tf in heads && tt !== nothing && !inside(tt)) && push!(to, tt)
    end
    return unique(frm), unique(to)
end

"""The dimensions a transport takes from what it is connected to, or `nothing` when they cannot be told."""
function _transport_dims(N::_ModelNorm, path, lists)
    frm, to = _transport_ends(N, path)
    names = Any[frm..., to...]
    isempty(names) && return nothing
    plain(dims) = Any[d for d in _py_iter(dims) if !py_truthy(jget(find_list(lists, d), "for_scenarios"))]
    root(n) = lineage(lists, n).root
    acc = nothing
    for n in names
        hit = _norm_find(N, n)
        (hit === nothing || !(hit[1] in _INVENTORY_COLLECTIONS)) && return nothing
        d = _effective_dims(N, hit[2])
        if acc === nothing
            acc = d
            continue
        end
        dims = Any[]
        rest = plain(d)
        for s in plain(acc)
            at = findfirst(t -> root(t) == root(s), rest)
            at === nothing && continue
            t = popat!(rest, at)
            if s == t
                push!(dims, s)
                continue
            end
            ls, lt = find_list(lists, s), find_list(lists, t)
            narrower = jget(ls, "sub_set_of") == t ? s : (jget(lt, "sub_set_of") == s ? t : nothing)
            narrower === nothing && return nothing
            push!(dims, narrower)
        end
        acc = dims
    end
    return (dims=acc === nothing ? Any[] : acc,)
end

function _sync_transport_inheritance!(N::_ModelNorm, lists)
    changed = Any[]
    for path in _norm_transports(N)
        p = _norm_transport_parts(N, path)
        p.begin_ === nothing && continue
        inherited = _transport_dims(N, path, lists)
        inherited === nothing && continue
        have = _effective_dims(N, p.begin_)
        (have == inherited.dims || _narrows(N, have, inherited.dims, lists)) && continue
        p.begin_["index_lists"] = collect(Any, inherited.dims)
        _prune_entries!(p.begin_, inherited.dims)
        push!(changed, qualified_name(p.begin_))
        append!(changed, _sync_transport_dims!(N, p.begin_, inherited.dims))
    end
    return changed
end

# --- what follows from the model (syncDerivedUnits) ------------------------------------------

function _sync_transfer_dimensions!(N::_ModelNorm)
    lists = _all_lists(N)
    changed = _sync_transport_inheritance!(N, lists)
    for collection in ("transfers", "inflows")
        for b in _norm_list(N.raw, collection)
            b isa AbstractDict || continue
            shared = _transfer_dims(N, b, lists)
            (shared === nothing || !(get(b, "index_lists", nothing) isa AbstractVector)) && continue
            _narrows(N, b["index_lists"], shared.dims, lists) && continue
            b["index_lists"] = collect(Any, shared.dims)
            push!(changed, get(b, "name", nothing))
        end
    end
    return changed
end

function _material_dimension_names(N::_ModelNorm)
    lists = _all_lists(N)
    rootl = findfirst_value(l -> py_truthy(jget(l, "for_contaminants")), lists)
    root = rootl === nothing ? nothing : rootl["name"]
    if !py_truthy(root)
        name = _material_dimension(N)
        return py_truthy(name) ? Any[name] : Any[]
    end
    return Any[l["name"] for l in lists if is_decay_dim(lists, l["name"], root) && py_truthy(jget(l, "indices"))]
end

function _material_unit(N::_ModelNorm, name)
    lists = _stored_lists(N)
    catalogue = findfirst_value(l -> py_truthy(get(l, "for_contaminants", nothing)), lists)
    own = findfirst_value(i -> i isa AbstractDict && get(i, "name", nothing) == name, _py_iter(jget(catalogue, "indices")))
    stated = strip(_js_string(jget(own, "unit")))
    isempty(stated) || return String(stated)
    nuclides = findfirst_value(l -> py_truthy(get(l, "for_nuclides", nothing)), lists)
    nuclides === nothing && (nuclides = catalogue)
    is_nuclide = nuclides !== nothing ? any(i -> index_name(i) == name, _py_iter(get(nuclides, "indices", nothing))) :
                 any(x -> x == name, _py_iter(get(N.raw, "nuclides", nothing)))
    return is_nuclide ? _decay_unit(N) : ""
end

function _dimension_unit(N::_ModelNorm, list_name)
    lists = _stored_lists(N)
    lst = find_list(lists, list_name)
    if lst === nothing
        return any(l -> py_truthy(get(l, "for_contaminants", nothing)) || py_truthy(get(l, "for_nuclides", nothing)), lists) ?
               "" : _decay_unit(N)
    end
    one = nothing
    for i in _py_iter(get(lst, "indices", nothing))
        (i isa AbstractDict && get(i, "enabled", nothing) === false) && continue
        u = _material_unit(N, index_name(i))
        isempty(u) && return ""
        if one === nothing
            one = u
        elseif one != u
            return ""
        end
    end
    return something(one, "")
end

function _sync_inventory_units!(N::_ModelNorm)
    names = _material_dimension_names(N)
    isempty(names) && return Any[]
    want = Dict{Any,String}()
    for n in names
        want[n] = _dimension_unit(N, n)
    end
    filled = Any[]
    for c in _norm_list(N.raw, "compartments")
        c isa AbstractDict || continue
        on = findfirst_value(d -> haskey(want, d), _effective_dims(N, c))
        (on === nothing || !isempty(strip(_js_string(get(c, "unit", nothing))))) && continue
        u = want[on]
        isempty(u) && continue
        c["unit"] = u
        push!(filled, get(c, "name", nothing))
    end
    return filled
end

function _norm_time_unit(N::_ModelNorm)
    sim = get(N.raw, "simulation", nothing)
    t = py_truthy(sim) ? jget(sim, "time_unit") : nothing
    return t !== nothing ? _norm_str(t) : "year"
end

"""`Bq/m3` over a year is `(Bq/m3)/year`, not `Bq/m3/year`."""
_per(quantity::AbstractString, time::AbstractString) =
    any(c -> c in ('/', ' ', '\t', '\n', '\r', '\f', '\v'), quantity) ? "($quantity)/$time" : "$quantity/$time"

"""The first of `blocks` under each key `key(b)`, as `next(x for x in blocks if key(x) == k)` finds it."""
function _first_by(key, blocks)
    out = Dict{Any,Any}()
    for b in blocks
        b isa AbstractDict || continue
        k = key(b)
        haskey(out, k) || (out[k] = b)
    end
    return out
end

function _sync_flux_units!(N::_ModelNorm)
    t = _norm_time_unit(N)
    comps = _norm_list(N.raw, "compartments")
    comp_q = _first_by(qualified_name, comps)
    comp_n = _first_by(x -> get(x, "name", nothing), comps)
    paths = _norm_list(N.raw, "farfields")
    path_q = _first_by(qualified_name, paths)
    path_n = _first_by(x -> get(x, "name", nothing), paths)
    function unit_of_compartment(name)
        name === nothing && return ""
        c = get(comp_q, name, nothing)
        c === nothing && (c = get(comp_n, name, nothing))
        return c === nothing ? "" : String(strip(_js_string(get(c, "unit", nothing))))
    end
    function transfer_unit(b)
        get(b, "multiply_by_donor", nothing) !== false && return "1/$t"
        fr = get(b, "from", nothing)
        path = fr === nothing ? nothing : get(path_q, fr, nothing)
        path === nothing && (path = get(path_n, fr, nothing))
        path !== nothing && return String(strip(_js_string(get(path, "unit", nothing))))
        u = unit_of_compartment(fr !== nothing ? fr : get(b, "to", nothing))
        return isempty(u) ? "" : _per(u, t)
    end
    function inflow_unit(b)
        u = unit_of_compartment(get(b, "to", nothing))
        return isempty(u) ? "" : _per(u, t)
    end
    changed = Any[]
    for (collection, unit_of) in (("transfers", transfer_unit), ("inflows", inflow_unit))
        for b in _norm_list(N.raw, collection)
            b isa AbstractDict || continue
            want = unit_of(b)
            _js_string(get(b, "unit", nothing)) == want && continue
            if isempty(want)
                delete!(b, "unit")
            else
                b["unit"] = want
            end
            push!(changed, get(b, "name", nothing))
        end
    end
    return changed
end

function _sync_derived_units!(N::_ModelNorm)
    changed = _sync_transfer_dimensions!(N)
    append!(changed, _sync_inventory_units!(N))
    append!(changed, _sync_flux_units!(N))
    return changed
end

# --- the shape Kompartment works on (materialiseShorthand) ------------------------------------

function _materialise_legacy_entries!(N::_ModelNorm)
    for collection in COLLECTIONS
        key = get(_ENTRY_KEY_BY_COLLECTION, collection, nothing)
        key === nothing && continue
        for b in _norm_list(N.raw, collection)
            (b isa AbstractDict && haskey(b, "default")) || continue
            haskey(b, key) || (b[key] = b["default"])
            delete!(b, "default")
        end
    end
    material = _material_dimension(N)
    py_truthy(material) || return

    function add(block, index, key, value)
        ents = get(block, "entries", nothing)
        if !(ents isa AbstractVector)
            ents = Any[]
            block["entries"] = ents
        elseif !(ents isa Vector{Any})
            ents = collect(Any, ents)
            block["entries"] = ents
        end
        for e in ents
            if _py_or(jget(e, "index"), JDict()) == index
                haskey(e, key) || (e[key] = value)
                return
            end
        end
        push!(ents, JDict("index" => index, key => value))
    end

    for p in _norm_list(N.raw, "parameters")
        p isa AbstractDict || continue
        vmap = get(p, "values_by_nuclide", nothing)
        (py_truthy(vmap) && vmap isa AbstractDict) || continue
        material in _effective_dims(N, p) || continue
        for (nuc, v) in vmap
            add(p, JDict(material => nuc), "value", _model_js_number(v))
        end
        delete!(p, "values_by_nuclide")
    end
    for c in _norm_list(N.raw, "compartments")
        c isa AbstractDict || continue
        imap = get(c, "initial", nothing)
        (py_truthy(imap) && imap isa AbstractDict) || continue
        material in _effective_dims(N, c) || continue
        for (nuc, v) in imap
            add(c, JDict(material => nuc), "initial", _js_string(v))
        end
        c["initial"] = "0"
    end
    return
end

"""An entry's copy of its transfer's `multiply_by_donor` that agrees with it, which older imports kept on
every row, dropped (`dropDonorCopies`); one that disagrees stays, for the Project to name."""
function _drop_donor_copies!(N::_ModelNorm)
    for t in _norm_list(N.raw, "transfers")
        (t isa AbstractDict && get(t, "entries", nothing) isa AbstractVector) || continue
        own = get(t, "multiply_by_donor", nothing) !== false
        dropped = false
        for e in t["entries"]
            if e isa AbstractDict && haskey(e, "multiply_by_donor") && (e["multiply_by_donor"] !== false) == own
                delete!(e, "multiply_by_donor")
                dropped = true
            end
        end
        if dropped
            t["entries"] = Any[e for e in t["entries"] if !(e isa AbstractDict) || any(k -> k != "index", keys(e))]
        end
    end
    return
end

function _sync_nuclides!(N::_ModelNorm)
    lst = _nuclide_list_raw(N)
    if lst === nothing
        delete!(N.raw, "nuclides")
        return
    end
    N.raw["nuclides"] = Any[index_name(i) for i in _py_iter(get(lst, "indices", nothing))
                            if !(i isa AbstractDict && get(i, "enabled", nothing) === false)]
    return
end

function _ensure_material_lists!(N::_ModelNorm)
    split = split_material_roles(N.raw)
    if split !== N.raw && get(split, "index_lists", nothing) isa AbstractVector
        N.raw["index_lists"] = split["index_lists"]
    end
    materials = _material_list_raw(N)
    nuclides = findfirst_value(l -> py_truthy(get(l, "for_nuclides", nothing)), _stored_lists(N))
    (materials !== nothing && nuclides !== nothing) && return
    _make_dimensions_explicit!(N)
    get(N.raw, "index_lists", nothing) isa AbstractVector || (N.raw["index_lists"] = Any[])
    lists = _any_vector(N.raw["index_lists"])
    N.raw["index_lists"] = lists
    if materials === nothing
        materials = JDict(
            "name" => _unique_list_name(N, MATERIAL_LIST),
            "for_contaminants" => true,
            "comment" => "Every material the model knows.",
            "indices" => Any[i isa AbstractString ? JDict("name" => i, "enabled" => true) : JDict(i)
                             for i in _py_iter(jget(nuclides, "indices"))],
        )
        insert!(lists, 1, materials)
    end
    if nuclides === nothing
        nuclides = JDict(
            "name" => _unique_list_name(N, NUCLIDE_LIST),
            "for_nuclides" => true,
            "sub_set_of" => materials["name"],
            "comment" => "The materials that have a half-life.",
            "indices" => Any[],
        )
        at = findfirst(l -> l === materials, lists)
        insert!(lists, at + 1, nuclides)
    end
    _sync_nuclides!(N)
    return
end

function _qualify_endpoints!(N::_ModelNorm)
    ends = Set{String}(qualified_name(c) for c in _norm_list(N.raw, "compartments") if c isa AbstractDict)
    known = n -> n in ends
    for conn in Iterators.flatten((_norm_list(N.raw, "transfers"), _norm_list(N.raw, "inflows")))
        conn isa AbstractDict || continue
        for end_ in ("from", "to")
            ref = get(conn, end_, nothing)
            ref === nothing && continue
            if !known(ref)
                r = resolve_reference(ref, system_of(conn), known)
                conn[end_] = py_truthy(r) ? r : ref
            end
        end
    end
    return
end

function _make_dimensions_explicit!(N::_ModelNorm)
    for collection in COLLECTIONS
        for b in _norm_list(N.raw, collection)
            b isa AbstractDict || continue
            b["index_lists"] = _effective_dims(N, b)
            delete!(b, "per_nuclide")
        end
    end
    return
end

function _normalise_shape!(N::_ModelNorm)
    raw = N.raw
    nuclides = get(raw, "nuclides", nothing)
    if py_truthy(nuclides) &&
       !any(l -> l isa AbstractDict && (py_truthy(get(l, "for_contaminants", nothing)) || py_truthy(get(l, "for_nuclides", nothing))),
            _norm_list(raw, "index_lists"))
        indices = Any[JDict("name" => n, "enabled" => true) for n in _py_iter(nuclides)]
        raw["index_lists"] = Any[
            JDict("name" => MATERIAL_LIST, "for_contaminants" => true, "indices" => Any[JDict(i) for i in indices]),
            JDict("name" => NUCLIDE_LIST, "for_nuclides" => true, "sub_set_of" => MATERIAL_LIST, "indices" => indices),
            _norm_list(raw, "index_lists")...,
        ]
    end
    _materialise_legacy_entries!(N)
    _drop_donor_copies!(N)
    _ensure_material_lists!(N)
    _qualify_endpoints!(N)
    _make_dimensions_explicit!(N)
    return
end

"""
    normalise_model!(raw) -> raw

Brings a model's dictionary, in place, into the shape Kompartment works on, as
the application does when it opens a file (after `migrate_keys`, which renames
older keys and returns a copy): the material lists present, every block's
dimensions written down, transfer ends written as qualified names, older
per-nuclide values as entries, and the units that follow from the model
filled in. Nothing else about the model changes.
"""
function normalise_model!(raw::AbstractDict)
    N = _ModelNorm(raw)
    _normalise_shape!(N)
    _sync_derived_units!(N)
    return raw
end

# --- settling, before the model is written ---------------------------------------------------

function _parse_edge_key(key)
    s = string(key)
    startswith(s, _EDGE_PREFIX) || return nothing
    rest = s[ncodeunits(_EDGE_PREFIX)+1:end]
    at = findfirst('@', rest)
    return at === nothing ? (rest, nothing) : (rest[1:prevind(rest, at)], rest[nextind(rest, at):end])
end

"""Every sub-system a model has (declared, transports, and those its blocks sit in)."""
function _norm_systems(N::_ModelNorm)
    block_systems = String[]
    for collection in COLLECTIONS
        for b in _norm_list(N.raw, collection)
            b isa AbstractDict && push!(block_systems, system_of(b))
        end
    end
    return system_paths(collect(Any, _norm_list(N.raw, "systems")), collect(Any, _norm_list(N.raw, "transports")),
                        block_systems)
end

function _prune_layout!(N::_ModelNorm)
    layout = get(N.raw, "layout", nothing)
    (layout isa AbstractDict && !isempty(layout)) || return
    names = Set{String}(_norm_systems(N))
    union!(names, keys(_norm_index!(N)))
    for k in collect(keys(layout))
        edge = _parse_edge_key(k)
        owner = edge === nothing ? k : edge[1]
        canvas_gone = edge !== nothing && !(edge[2] === nothing || edge[2] == "") && !(edge[2] in names)
        (!(owner in names) || canvas_gone) && delete!(layout, k)
    end
    return
end

"""
    settle!(raw) -> Vector{String}

Brings what follows from the model up to date, as the application does after
every edit and Python's `Model.settle` before the model is written: every
flux's dimensions from its two ends (and every transport's from what it is
connected to), a blank compartment unit on a material dimension from the
materials, every transfer's and inflow's unit from its donor and the time
unit, and the diagram entries of blocks that no longer exist dropped. Returns
the names of the blocks it changed.
"""
function settle!(raw::AbstractDict)
    N = _ModelNorm(raw)
    _prune_layout!(N)
    return String[_name_text(n) for n in _sync_derived_units!(N)]
end

"""Puts the header (`name`, `description`, `author`, `created`, `saved`) first, in place (`headerFirst`)."""
function header_first!(raw::AbstractDict)
    ks = collect(keys(raw))
    want = Any[k for k in HEADER_KEYS if haskey(raw, k)]
    append!(want, (k for k in ks if !(k in HEADER_KEYS)))
    want == ks && return raw
    items = [k => raw[k] for k in want]
    empty!(raw)
    for (k, v) in items
        raw[k] = v
    end
    return raw
end

"""A time as the application writes one: `toISOString`, UTC to the millisecond."""
model_stamp(when::DateTime=Dates.now(Dates.UTC)) = Dates.format(when, dateformat"yyyy-mm-ddTHH:MM:SS.sss") * "Z"

@inline _iso_digit(b::Vector{UInt8}, p::Int) = p <= length(b) && UInt8('0') <= b[p] <= UInt8('9')

# CPython 3.12's `parse_hh_mm_ss_ff` (Modules/_datetimemodule.c), over the
# NUL-terminated bytes `b` from `p` to `p_end` (exclusive): `(rv, h, m, s, us)`,
# rv < 0 for a failure, 1 when something is left over.
function _iso_hh_mm_ss_ff(b::Vector{UInt8}, p::Int, p_end::Int)
    vals = [0, 0, 0]
    has_separator = true
    for i in 1:3
        for _ in 1:2
            _iso_digit(b, p) || return (-3, 0, 0, 0, 0)
            vals[i] = 10 * vals[i] + (b[p] - UInt8('0'))
            p += 1
        end
        c = b[p]
        p += 1
        i == 1 && (has_separator = c == UInt8(':'))
        if p >= p_end
            return (c != 0x00 ? 1 : 0, vals[1], vals[2], vals[3], 0)
        elseif has_separator && c == UInt8(':')
            continue
        elseif c == UInt8('.') || c == UInt8(',')
            break
        elseif !has_separator
            p -= 1
        else
            return (-4, 0, 0, 0, 0)
        end
    end
    to_parse = min(p_end - p, 6)
    us = 0
    for _ in 1:to_parse
        _iso_digit(b, p) || return (-3, 0, 0, 0, 0)
        us = 10 * us + (b[p] - UInt8('0'))
        p += 1
    end
    1 <= to_parse < 6 && (us *= 10^(6 - to_parse))
    while _iso_digit(b, p)
        p += 1
    end
    return (b[p] != 0x00 ? 1 : 0, vals[1], vals[2], vals[3], us)
end

# CPython 3.12's `parse_isoformat_time`: `(rv, h, m, s, us, tz_seconds, tz_us)`,
# rv 0 without a zone, 1 with one, < 0 for a failure.
function _iso_time(b::Vector{UInt8}, p::Int, p_end::Int)
    tz = p
    while true
        c = b[tz]
        (c == UInt8('Z') || c == UInt8('+') || c == UInt8('-')) && break
        tz += 1
        tz < p_end || break
    end
    rv, h, m, s, us = _iso_hh_mm_ss_ff(b, p, tz)
    rv < 0 && return (rv, 0, 0, 0, 0, 0, 0)
    tz == p_end && return rv == 1 ? (-5, 0, 0, 0, 0, 0, 0) : (0, h, m, s, us, 0, 0)
    if b[tz] == UInt8('Z')
        return b[tz+1] != 0x00 ? (-5, 0, 0, 0, 0, 0, 0) : (1, h, m, s, us, 0, 0)
    end
    sign = b[tz] == UInt8('-') ? -1 : 1
    rz, zh, zm, zs, zus = _iso_hh_mm_ss_ff(b, tz + 1, p_end)
    rz != 0 && return (-5, 0, 0, 0, 0, 0, 0)
    return (1, h, m, s, us, sign * (zh * 3600 + zm * 60 + zs), sign * zus)
end

"""
    read_model_stamp(value) -> Union{DateTime,Nothing}

A stamp read back as a time (UTC, to the millisecond), or `nothing` for one
that is not a date and time: what Python's `datetime.fromisoformat` accepts
once a `Z` is read as `+00:00`, after a `YYYY-MM-DDT` start.
"""
function read_model_stamp(value)
    value isa AbstractString || return nothing
    occursin(r"^\d{4}-\d{2}-\d{2}T", value) || return nothing
    text = replace(String(value), "Z" => "+00:00")
    b = Vector{UInt8}(codeunits(text))
    len = length(b)
    push!(b, 0x00)
    y, mo, d = parse(Int, text[1:4]), parse(Int, text[6:7]), parse(Int, text[9:10])
    rv, h, mi, s, us, zsec, zus = _iso_time(b, 12, len + 1)
    rv < 0 && return nothing
    (1 <= y <= 9999 && 1 <= mo <= 12 && 1 <= d <= Dates.daysinmonth(y, mo)) || return nothing
    (h <= 23 && mi <= 59 && s <= 59) || return nothing
    zone_us = zsec * 1_000_000 + zus
    abs(zone_us) < 86_400_000_000 || return nothing
    # The instant in UTC, to the millisecond below it.
    return DateTime(y, mo, d, h, mi, s) + Dates.Millisecond(fld(us - (rv == 1 ? zone_us : 0), 1000))
end
