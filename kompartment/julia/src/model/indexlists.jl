# The rules of Kompartment's index lists (src/domain/indexlists.js).
#
# Every block is indexed by an ordered list of index lists -- its dimensions
# -- and holds one value per combination of their indices. A list is a root,
# a sub-set of another list (`sub_set_of`), or a mapping onto another
# (`mapping: {to, pairs}`). Two lists are built in: the material catalogue
# (`for_contaminants`, `Contaminants`) and the radionuclides (`for_nuclides`,
# `Radionuclides`), a sub-set of it. Three are derived from the model and
# never written to the file: `Elements`, `Compartments` and `Transfers`.

const MATERIAL_LIST = "Contaminants"
const NUCLIDE_LIST = "Radionuclides"
const ELEMENT_LIST = "Elements"
const COMPARTMENT_LIST = "Compartments"
const TRANSFER_LIST = "Transfers"

"""What the built-in lists used to be called, for files written then."""
const WAS = Dict(NUCLIDE_LIST => "Nuclide", ELEMENT_LIST => "Element", MATERIAL_LIST => "Materials")

"""The kinds of block that may be indexed by `Compartments` or `Transfers`."""
const AUTO_DIM_KINDS = Set(["expression", "parameter", "lookup", "block_reduction", "index_reduction"])

"""The words that stand for a transfer's own two ends inside its equations."""
const SOURCE_INDEX = "_source_"
const TARGET_INDEX = "_target_"

index_name(index) = index isa AbstractString ? String(index) : jget(index, "name")

find_list(lists, name) = (lists === nothing ? nothing :
                          findfirst_value(l -> l isa AbstractDict && get(l, "name", nothing) == name, lists))

"""The first element of `xs` for which `pred` holds, or `nothing`."""
function findfirst_value(pred, xs)
    for x in xs
        pred(x) && return x
    end
    return nothing
end

function parent_list_name(lst)
    lst === nothing && return nothing
    s = jget(lst, "sub_set_of")
    js_truthy(s) && return s
    m = jget(lst, "mapping")
    js_truthy(m) || return nothing
    return m isa AbstractString ? m : jget(m, "to")
end

"""How a list reaches its root: `(root, mapped, above)`; `above` is the chain
of lists above it, nearest first, each `(name, mapped)`."""
function lineage(lists, name)
    at = name
    mapped = false
    above = Tuple{String,Bool}[]
    seen = Set{Any}()
    while js_truthy(at) && !(at in seen)
        push!(seen, at)
        lst = find_list(lists, at)
        m = jget(lst, "mapping")
        mto = js_truthy(m) ? (m isa AbstractDict ? get(m, "to", nothing) : m) : nothing
        nxt = js_truthy(mto) ? mto : jget(lst, "sub_set_of")
        js_truthy(nxt) || break
        js_truthy(mto) && (mapped = true)
        push!(above, (String(nxt), js_truthy(mto)))
        at = nxt
    end
    return (root=js_truthy(at) ? at : name, mapped=mapped, above=above)
end

root_of(lists, name) = lineage(lists, name).root

"""Whether a block of `kind` may be indexed by `lst`."""
function list_applies(lst, kind)
    lst === nothing && return false
    js_truthy(jget(lst, "auto")) || return true
    return kind in AUTO_DIM_KINDS
end

function list_applies_why(lst, kind)
    list_applies(lst, kind) && return ""
    lst === nothing && return "That index list is not in this model."
    one = jget(lst, "auto") == "compartments" ? "compartment" : "transfer"
    own = kind == one ? "A $one is one of them already: that is what lets a value indexed by " *
                        "'$(lst["name"])' be read inside a $one with no index at all. " : ""
    return "'$(lst["name"])' has one index per $one, and a $(replace(kind, '_' => ' ')) cannot be indexed by " *
           "them. $(own)Only an expression, a parameter, a lookup table, an aggregate or an index operation can."
end

"""The first pair of dimensions that are one dimension twice, or `nothing`."""
function clashing_dimensions(lists, dims)
    seen = [(name=d, lineage(lists, d)...) for d in something(dims, String[])]
    auto_of(n) = (l = find_list(lists, n); l === nothing ? nothing : get(l, "auto", nothing))
    for i in 1:length(seen), j in i+1:length(seen)
        a, b = seen[i], seen[j]
        a.name == b.name && continue
        if a.root == b.root
            b_above_a = findfirst_value(x -> x[1] == b.name, a.above)
            a_above_b = findfirst_value(x -> x[1] == a.name, b.above)
            link = b_above_a !== nothing ? b_above_a : a_above_b
            how = link === nothing ? "siblings" : (link[2] ? "grouping" : "sub_set")
            below = b_above_a !== nothing ? a.name : (a_above_b !== nothing ? b.name : nothing)
            above = below == a.name ? b.name : (below == b.name ? a.name : nothing)
            return (a=a.name, b=b.name, root=a.root, how=how, below=below, above=above)
        end
        ra, rb = auto_of(a.root), auto_of(b.root)
        if js_truthy(ra) && js_truthy(rb) && ra != rb
            return (a=a.name, b=b.name, root=nothing, how="blocks", below=nothing, above=nothing)
        end
    end
    return nothing
end

function clashing_dimensions_why(clash)
    clash === nothing && return ""
    a, b, root, how = clash.a, clash.b, clash.root, clash.how
    how == "blocks" && return "'$a' has one index per compartment and '$b' one per transfer, and a block cannot " *
                              "be indexed by both. Pick one."
    how == "siblings" && return "'$a' and '$b' are both taken from '$root', so a block indexed by both would be " *
                                "indexed by the same dimension twice. Pick one."
    below, above = clash.below, clash.above
    how == "grouping" && return "'$below' is a grouping of '$above', so a block indexed by both would be indexed " *
                                "by the same dimension twice. Pick one."
    return "'$below' is a sub-set of '$above', so a block indexed by both would be indexed by the same dimension " *
           "twice. Pick one."
end

"""The dimensions a flux varies along: the scenario list is not one."""
function _plain(lists, dims)
    out = String[]
    for d in something(dims, String[])
        lst = find_list(lists, d)
        lst !== nothing && js_truthy(get(lst, "for_scenarios", nothing)) && continue
        push!(out, d)
    end
    return out
end

"""
    shared_dims(lists, source, target) -> Union{Nothing,NamedTuple}

What a transfer between two blocks is indexed by: the indices both ends have.
`source`/`target` are the two ends' dimensions, `nothing` for the model
boundary.
"""
function shared_dims(lists, source, target)
    source === nothing && target === nothing && return nothing
    if source === nothing || target === nothing
        return (dims=_plain(lists, source === nothing ? target : source), shared=Any[])
    end
    a, b = _plain(lists, source), _plain(lists, target)
    length(a) == length(b) || return nothing
    isempty(a) && return (dims=String[], shared=Any[])
    rest = copy(b)
    matched = Union{Nothing,String}[]
    for s in a
        k = findfirst(t -> root_of(lists, t) == root_of(lists, s), rest)
        push!(matched, k === nothing ? nothing : popat!(rest, k))
    end
    dims = String[]
    shared = Any[]
    for (s, t) in zip(a, matched)
        t === nothing && return nothing
        if s == t
            push!(dims, s)
            continue
        end
        ls, lt = find_list(lists, s), find_list(lists, t)
        narrower = jget(ls, "sub_set_of") == t ? s : (jget(lt, "sub_set_of") == s ? t : nothing)
        narrower === nothing && return nothing
        push!(dims, narrower)
        push!(shared, (from=s, to=t, dims=narrower))
    end
    return (dims=dims, shared=shared)
end

"""The flux's dimensions one of its ends cannot follow."""
function summed_dims(lists, flux_dims, end_dims)
    roots = Set(root_of(lists, d) for d in _plain(lists, end_dims))
    return [d for d in _plain(lists, flux_dims) if !(root_of(lists, d) in roots)]
end

"""Whether the nuclides decay along a dimension."""
function is_decay_dim(lists, name, material)
    (js_truthy(name) && js_truthy(material)) || return false
    lst = find_list(lists, name)
    (lst === nothing || js_truthy(get(lst, "mapping", nothing))) && return false
    return root_of(lists, name) == root_of(lists, material)
end

# --- reading a file -------------------------------------------------------------

_copy_with(d::AbstractDict, pairs::Pair...) = (out = JDict(d); for (k, v) in pairs; out[k] = v; end; out)

"""Renames the built-in lists in a file written under their old names."""
function rename_built_in_lists(raw)
    raw isa AbstractDict || return raw
    lists = get(raw, "index_lists", nothing) isa AbstractVector ? raw["index_lists"] : Any[]
    taken = Set(get(l, "name", nothing) for l in lists if l isa AbstractDict)
    function flagged(l)
        l isa AbstractDict || return false
        for k in ("for_contaminants", "for_materials", "forMaterials")
            get(l, k, nothing) !== nothing && return js_truthy(l[k])
        end
        return false
    end
    material = findfirst_value(flagged, lists)
    mapping = Dict{String,String}()
    rename(to) = (was = get(WAS, to, nothing); (was === nothing || to in taken) || (mapping[was] = to))
    if material !== nothing ? get(material, "name", nothing) == WAS[NUCLIDE_LIST] : js_truthy(get(raw, "nuclides", nothing))
        rename(NUCLIDE_LIST)
    end
    element = findfirst_value(lists) do l
        l isa AbstractDict && get(l, "name", nothing) == WAS[ELEMENT_LIST] &&
            (js_truthy(get(l, "for_elements", nothing)) ||
             (get(l, "mapping", nothing) isa AbstractDict && js_truthy(get(l["mapping"], "to", nothing)) &&
              material !== nothing && l["mapping"]["to"] == get(material, "name", nothing)))
    end
    element !== nothing && rename(ELEMENT_LIST)
    material !== nothing && get(material, "name", nothing) == WAS[MATERIAL_LIST] && rename(MATERIAL_LIST)
    isempty(mapping) && return raw
    to(name) = name isa AbstractString ? get(mapping, name, name) : name
    out = JDict(raw)
    if !isempty(lists)
        new_lists = Any[]
        for l in lists
            if !(l isa AbstractDict)
                push!(new_lists, l)
                continue
            end
            n = _copy_with(l, "name" => to(get(l, "name", nothing)))
            js_truthy(get(l, "sub_set_of", nothing)) && (n["sub_set_of"] = to(l["sub_set_of"]))
            if get(l, "mapping", nothing) isa AbstractDict && js_truthy(get(l["mapping"], "to", nothing))
                n["mapping"] = _copy_with(l["mapping"], "to" => to(l["mapping"]["to"]))
            end
            push!(new_lists, n)
        end
        out["index_lists"] = new_lists
    end
    for (key, value) in raw
        (key == "index_lists" || !(value isa AbstractVector)) && continue
        changed = false
        blocks = Any[]
        for b in value
            if !(b isa AbstractDict)
                push!(blocks, b)
                continue
            end
            dims = get(b, "index_lists", nothing) isa AbstractVector ? b["index_lists"] : nothing
            needs_dims = dims !== nothing && !isempty(dims) && any(d -> haskey(mapping, d), dims)
            entries = get(b, "entries", nothing) isa AbstractVector ? b["entries"] : nothing
            needs_entries = entries !== nothing && !isempty(entries) &&
                            any(e -> e isa AbstractDict && get(e, "index", nothing) isa AbstractDict &&
                                         any(d -> haskey(mapping, d), keys(e["index"])), entries)
            if !needs_dims && !needs_entries
                push!(blocks, b)
                continue
            end
            changed = true
            nb = JDict(b)
            needs_dims && (nb["index_lists"] = Any[to(d) for d in dims])
            if needs_entries
                nb["entries"] = Any[(e isa AbstractDict && get(e, "index", nothing) isa AbstractDict) ?
                                    _copy_with(e, "index" => JDict(to(d) => i for (d, i) in e["index"])) : e
                                    for e in entries]
            end
            push!(blocks, nb)
        end
        changed && (out[key] = blocks)
    end
    return out
end

function _free_name(taken, want)
    used = Set(taken)
    name = want
    n = 2
    while name in used
        name = "$want$n"
        n += 1
    end
    return name
end

"""Tells the two material roles apart in a file that has them as one list."""
function split_material_roles(raw)
    raw isa AbstractDict || return raw
    lists = get(raw, "index_lists", nothing) isa AbstractVector ? raw["index_lists"] : Any[]
    (isempty(lists) || any(l -> l isa AbstractDict && js_truthy(get(l, "for_nuclides", nothing)), lists)) && return raw
    flagged = findfirst_value(l -> l isa AbstractDict && js_truthy(get(l, "for_contaminants", nothing)), lists)
    flagged === nothing && return raw
    function as_nuclides(l)
        n = _copy_with(l, "for_nuclides" => true)
        delete!(n, "for_contaminants")
        return n
    end
    parent = js_truthy(get(flagged, "sub_set_of", nothing)) ? find_list(lists, flagged["sub_set_of"]) : nothing
    local root, nxt
    if parent !== nothing
        root = parent["name"]
        nxt = Any[l === flagged ? as_nuclides(l) : (l === parent ? _copy_with(l, "for_contaminants" => true) : l)
                  for l in lists]
    else
        sub = findfirst_value(l -> l isa AbstractDict && get(l, "sub_set_of", nothing) == get(flagged, "name", nothing) &&
                                   get(l, "name", nothing) in (NUCLIDE_LIST, WAS[NUCLIDE_LIST]), lists)
        if sub !== nothing
            root = flagged["name"]
            nxt = Any[l === sub ? _copy_with(l, "for_nuclides" => true) : l for l in lists]
        else
            get(flagged, "name", nothing) == MATERIAL_LIST && return raw
            root = _free_name([get(l, "name", nothing) for l in lists if l isa AbstractDict], MATERIAL_LIST)
            catalogue = JDict(
                "name" => root,
                "for_contaminants" => true,
                "comment" => "Every material the model knows. The radionuclides among them are in $(get(flagged, "name", nothing)).",
                "indices" => Any[i isa AbstractString ? JDict("name" => i, "enabled" => true) : JDict(i)
                                 for i in something(get(flagged, "indices", nothing), Any[])],
            )
            nxt = Any[]
            for l in lists
                if l !== flagged
                    push!(nxt, l)
                    continue
                end
                push!(nxt, catalogue)
                push!(nxt, _copy_with(as_nuclides(l), "sub_set_of" => root))
            end
        end
    end
    nuclides = nothing
    for l in nxt
        if l isa AbstractDict && js_truthy(get(l, "for_nuclides", nothing))
            nuclides = l["name"]
            break
        end
    end
    if !js_truthy(nuclides) || nuclides == root
        return _copy_with(raw, "index_lists" => nxt)
    end
    fixed = Any[]
    for l in nxt
        if !(l isa AbstractDict) || js_truthy(get(l, "for_nuclides", nothing))
            push!(fixed, l)
        elseif get(l, "sub_set_of", nothing) == nuclides
            push!(fixed, _copy_with(l, "sub_set_of" => root))
        elseif get(l, "mapping", nothing) isa AbstractDict && get(l["mapping"], "to", nothing) == nuclides
            push!(fixed, _copy_with(l, "mapping" => _copy_with(l["mapping"], "to" => root)))
        else
            push!(fixed, l)
        end
    end
    return _copy_with(raw, "index_lists" => fixed)
end

"""The `nuclides: [...]` shorthand as the two lists it stands for."""
function desugar_nuclides(raw)
    nuclides = something(get(raw, "nuclides", nothing), Any[])
    existing = something(get(raw, "index_lists", nothing), Any[])
    (nuclides isa AbstractVector && !isempty(nuclides)) || return existing
    if any(l -> l isa AbstractDict && (get(l, "name", nothing) in (NUCLIDE_LIST, WAS[NUCLIDE_LIST]) ||
                                       js_truthy(get(l, "for_contaminants", nothing)) ||
                                       js_truthy(get(l, "for_nuclides", nothing))), existing)
        return existing
    end
    root = _free_name([get(l, "name", nothing) for l in existing if l isa AbstractDict], MATERIAL_LIST)
    indices = Any[JDict("name" => n, "enabled" => true) for n in nuclides]
    return Any[
        JDict("name" => root, "for_contaminants" => true, "indices" => Any[JDict(i) for i in indices]),
        JDict("name" => NUCLIDE_LIST, "for_nuclides" => true, "sub_set_of" => root, "indices" => indices),
        existing...,
    ]
end

"""The lists with the derived element list added, when the model has none."""
function derive_elements(lists)
    material = findfirst_value(l -> js_truthy(get(l, "for_contaminants", nothing)), lists)
    material === nothing && return collect(Any, lists)
    if any(l -> js_truthy(get(l, "for_elements", nothing)) || get(l, "name", nothing) in (ELEMENT_LIST, WAS[ELEMENT_LIST]), lists)
        return collect(Any, lists)
    end
    names = String[]
    dormant = String[]
    pairs = Any[]
    for raw in something(get(material, "indices", nothing), Any[])
        nuclide = index_name(raw)
        el = element_of(something(nuclide, ""))
        el = el === nothing ? nuclide : el
        js_truthy(el) || continue
        if raw isa AbstractDict && get(raw, "enabled", nothing) === false
            el in dormant || push!(dormant, el)
            continue
        end
        el in names || push!(names, el)
        push!(pairs, JDict("from" => el, "to" => nuclide))
    end
    off = [e for e in dormant if !(e in names)]
    isempty(names) && isempty(off) && return collect(Any, lists)
    return Any[lists...,
        JDict("name" => ELEMENT_LIST, "for_elements" => true, "derived" => true,
              "comment" => "One index per element of $(material["name"]), kept in step with it.",
              "mapping" => JDict("to" => material["name"], "pairs" => pairs),
              "indices" => Any[[JDict("name" => n, "enabled" => true) for n in names];
                               [JDict("name" => n, "enabled" => false) for n in off]])]
end

"""The lists with `Compartments` and `Transfers` added."""
function derive_block_lists(lists, model)
    out = collect(Any, lists)
    for (name, collection, what) in ((COMPARTMENT_LIST, "compartments", "compartment"),
                                     (TRANSFER_LIST, "transfers", "transfer"))
        any(l -> get(l, "name", nothing) == name, out) && continue
        names = String[]
        for b in something(get(model, collection, nothing), Any[])
            (b isa AbstractDict && !js_truthy(get(b, "hidden", nothing))) || continue
            sys = get(b, "system", nothing)
            n = js_truthy(sys) ? "$(sys).$(get(b, "name", nothing))" : get(b, "name", nothing)
            (n isa AbstractString && !isempty(n)) && push!(names, n)
        end
        isempty(names) && continue
        push!(out, JDict("name" => name, "derived" => true, "auto" => collection,
                         "note" => "One index per $what in the model — the $(what)s are the indices, so there is " *
                                   "nothing to edit here. Add a $what and this list gains an index; rename one and the " *
                                   "index follows.",
                         "indices" => Any[JDict("name" => n, "enabled" => true) for n in names]))
    end
    return out
end
