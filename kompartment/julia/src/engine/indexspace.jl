# The index-list model of one project: enabled indices, strides, and the tables
# that carry a position from one list into another (`IndexSpace` in
# src/domain/indexlists.js).
#
# Positions are counted from 0 here, as the application counts them, and a
# translation table holds -1 where a position has no counterpart: `table[k+1]`
# is where position `k` goes.

struct IndexSpaceError <: Exception
    message::String
    detail::Union{Nothing,String}
end
IndexSpaceError(msg::AbstractString) = IndexSpaceError(String(msg), nothing)
Base.showerror(io::IO, e::IndexSpaceError) = print(io, e.message)

"""One index of a list: its name and whether it is switched on."""
struct ListIndex
    name::String
    enabled::Bool
end

mutable struct IndexList
    name::String
    for_contaminants::Bool
    for_nuclides::Bool
    for_scenarios::Bool
    sub_set_of::Union{Nothing,String}
    mapping::Union{Nothing,JDict}
    indices::Vector{ListIndex}
    enabled::Vector{ListIndex}
    size::Int
    position_of::Dict{String,Int}     # enabled name => position (from 0)
    names::Set{String}
    root_name::Union{Nothing,String}
    up::Vector{Int}                   # position here => position in the root (-1: none)
    down::Vector{Int}                 # position in the root => position here (-1: none)
    is_scenario::Bool
end

function IndexList(raw::AbstractDict)
    idx = ListIndex[]
    for i in something(get(raw, "indices", nothing), Any[])
        if i isa AbstractString
            push!(idx, ListIndex(i, true))
        else
            push!(idx, ListIndex(string(something(get(i, "name", nothing), "")), get(i, "enabled", nothing) !== false))
        end
    end
    sub = get(raw, "sub_set_of", nothing)
    m = get(raw, "mapping", nothing)
    return IndexList(String(raw["name"]), js_truthy(get(raw, "for_contaminants", nothing)),
                     js_truthy(get(raw, "for_nuclides", nothing)), js_truthy(get(raw, "for_scenarios", nothing)),
                     js_truthy(sub) ? String(sub) : nothing, js_truthy(m) ? JDict(m) : nothing,
                     idx, ListIndex[], 0, Dict{String,Int}(), Set{String}(), nothing, Int[], Int[], false)
end

enabled_names(l::IndexList) = [i.name for i in l.enabled]

mutable struct IndexSpace
    lists::Dict{String,IndexList}
    order::Vector{String}
    stride_cache::Dict{Vector{String},Vector{Int}}
    scenario_root::Union{Nothing,String}
    scenario::Union{Nothing,String}
    relate_cache::Dict{Tuple{String,String},Any}   # `relate`'s answers: a build asks the same ones thousands of times
end

function IndexSpace(raw_lists)
    space = IndexSpace(Dict{String,IndexList}(), String[], Dict{Vector{String},Vector{Int}}(), nothing, nothing,
                       Dict{Tuple{String,String},Any}())
    for raw in raw_lists
        (raw isa AbstractDict && js_truthy(get(raw, "name", nothing))) || throw(IndexSpaceError("An index list needs a name"))
        haskey(space.lists, raw["name"]) && throw(IndexSpaceError("Duplicate index list '$(raw["name"])'"))
        lst = IndexList(raw)
        space.lists[lst.name] = lst
        push!(space.order, lst.name)
    end
    _resolve!(space)
    return space
end

_identity_table(n) = collect(0:n-1)

function _compose(inner::Vector{Int}, outer::Vector{Int})
    out = fill(-1, length(inner))
    for k in eachindex(inner)
        inner[k] >= 0 && (out[k] = outer[inner[k]+1])
    end
    return out
end

function _resolve!(space::IndexSpace)
    for lst in values(space.lists)
        lst.enabled = [i for i in lst.indices if i.enabled]
        lst.size = length(lst.enabled)
        lst.position_of = Dict(i.name => k - 1 for (k, i) in enumerate(lst.enabled))
        lst.names = Set(i.name for i in lst.indices)
    end
    for name in space.order
        lst = space.lists[name]
        if lst.sub_set_of !== nothing
            root = get(space.lists, lst.sub_set_of, nothing)
            root === nothing && throw(IndexSpaceError("Index list '$(lst.name)' is a sub-set of '$(lst.sub_set_of)', " *
                                                      "which does not exist", lst.name))
            root.sub_set_of !== nothing && throw(IndexSpaceError("'$(lst.name)' is a sub-set of '$(root.name)', which " *
                                                                 "is itself a sub-set. Sub-sets must be taken from a root list.", lst.name))
            for idx in lst.enabled
                idx.name in root.names || throw(IndexSpaceError("'$(idx.name)' is in the sub-set '$(lst.name)' but not " *
                                                                "in its root list '$(root.name)'", lst.name))
            end
            if any(i -> !haskey(root.position_of, i.name), lst.enabled)
                lst.enabled = [i for i in lst.enabled if haskey(root.position_of, i.name)]
                lst.size = length(lst.enabled)
                lst.position_of = Dict(i.name => k - 1 for (k, i) in enumerate(lst.enabled))
            end
        end
        if lst.mapping !== nothing
            target = get(space.lists, get(lst.mapping, "to", nothing), nothing)
            target === nothing && throw(IndexSpaceError("Index list '$(lst.name)' maps to '$(get(lst.mapping, "to", nothing))', " *
                                                        "which does not exist", lst.name))
        end
    end
    for name in space.order
        _place!(space, space.lists[name], Set{String}())
    end
    _place_scenarios!(space)
end

function _place!(space::IndexSpace, lst::IndexList, seen::Set{String})
    lst.root_name !== nothing && return lst
    lst.name in seen && throw(IndexSpaceError("Index list '$(lst.name)' is defined in terms of itself", lst.name))
    push!(seen, lst.name)
    parent_name = lst.sub_set_of !== nothing ? lst.sub_set_of :
                  (lst.mapping !== nothing ? get(lst.mapping, "to", nothing) : nothing)
    if !js_truthy(parent_name)
        lst.root_name = lst.name
        lst.up = _identity_table(lst.size)
        lst.down = _identity_table(lst.size)
        return lst
    end
    parent = _place!(space, get_list(space, parent_name), seen)
    step_up = lst.sub_set_of !== nothing ? _by_name(lst, parent) : _mapped_up(lst, parent)
    step_down = lst.sub_set_of !== nothing ? _by_name(parent, lst) : _mapped_down(lst, parent)
    lst.root_name = parent.root_name
    lst.up = _compose(step_up, parent.up)
    lst.down = _compose(parent.down, step_down)
    return lst
end

function _by_name(a::IndexList, b::IndexList)
    table = fill(-1, a.size)
    for (k, idx) in enumerate(a.enabled)
        table[k] = get(b.position_of, idx.name, -1)
    end
    return table
end

_pairs(lst::IndexList) = something(get(something(lst.mapping, JDict()), "pairs", nothing), Any[])

function _mapped_up(lst::IndexList, parent::IndexList)
    table = fill(-1, lst.size)
    for pair in _pairs(lst)
        k = get(lst.position_of, jget(pair, "from"), nothing)
        pos = get(parent.position_of, jget(pair, "to"), nothing)
        (k === nothing || pos === nothing || table[k+1] >= 0) && continue
        table[k+1] = pos
    end
    return table
end

function _mapped_down(lst::IndexList, parent::IndexList)
    table = fill(-1, parent.size)
    for pair in _pairs(lst)
        k = get(parent.position_of, jget(pair, "to"), nothing)
        pos = get(lst.position_of, jget(pair, "from"), nothing)
        (k === nothing || pos === nothing) && continue
        table[k+1] = pos
    end
    return table
end

# --- scenarios -----------------------------------------------------------------------

function _place_scenarios!(space::IndexSpace)
    space.scenario_root = nothing
    for name in space.order
        lst = space.lists[name]
        if lst.for_scenarios && lst.root_name == lst.name
            space.scenario_root = lst.name
            break
        end
    end
    if space.scenario_root === nothing
        for name in space.order
            lst = space.lists[name]
            if lst.for_scenarios
                space.scenario_root = lst.root_name
                break
            end
        end
    end
    for lst in values(space.lists)
        lst.is_scenario = space.scenario_root !== nothing && lst.root_name == space.scenario_root
    end
    found = scenarios(space)
    space.scenario = isempty(found) ? nothing : found[1]
end

scenarios(space::IndexSpace) = space.scenario_root === nothing ? String[] : index_names(space, space.scenario_root)

function is_scenario_dim(space::IndexSpace, name)
    lst = get(space.lists, name, nothing)
    return lst !== nothing && lst.is_scenario
end

function set_scenario!(space::IndexSpace, name)
    available = scenarios(space)
    space.scenario = (name !== nothing && name in available) ? String(name) : nothing
    return space.scenario
end

function scenario_index_in(space::IndexSpace, dim)
    lst = get(space.lists, dim, nothing)
    (lst === nothing || !lst.is_scenario || space.scenario === nothing) && return nothing
    root = space.lists[space.scenario_root]
    root_pos = get(root.position_of, space.scenario, nothing)
    root_pos === nothing && return nothing
    pos = lst === root ? root_pos : lst.down[root_pos+1]
    return pos >= 0 ? lst.enabled[pos+1].name : nothing
end

function without_scenarios(space::IndexSpace, dims)
    dims === nothing && return String[]
    space.scenario_root === nothing && return String[String(d) for d in dims]
    return String[String(d) for d in dims if !is_scenario_dim(space, d)]
end

function pin_scenario(space::IndexSpace, dims, tuple_::AbstractDict)
    (space.scenario_root === nothing || space.scenario === nothing) && return tuple_
    out = tuple_
    for d in something(dims, String[])
        is_scenario_dim(space, d) || continue
        name = scenario_index_in(space, d)
        name === nothing && continue
        out === tuple_ && (out = copy(tuple_))
        out[d] = name
    end
    return out
end

# --- queries ------------------------------------------------------------------------------

has_list(space::IndexSpace, name) = name !== nothing && haskey(space.lists, name)

function get_list(space::IndexSpace, name)
    lst = name === nothing ? nothing : get(space.lists, name, nothing)
    lst === nothing && throw(IndexSpaceError("No index list named '$(name)'"))
    return lst
end

list_size(space::IndexSpace, name) = get_list(space, name).size
index_names(space::IndexSpace, name) = String[i.name for i in get_list(space, name).enabled]

function material_list(space::IndexSpace)
    for name in space.order
        space.lists[name].for_contaminants && return space.lists[name]
    end
    return nothing
end

function nuclide_list(space::IndexSpace)
    for name in space.order
        space.lists[name].for_nuclides && return space.lists[name]
    end
    return nothing
end

function strides(space::IndexSpace, dims)
    key = Vector{String}(dims)
    hit = get(space.stride_cache, key, nothing)
    hit !== nothing && return hit
    sizes = [list_size(space, d) for d in key]
    st = ones(Int, length(key))
    for i in length(key)-1:-1:1
        st[i] = st[i+1] * sizes[i+1]
    end
    space.stride_cache[key] = st
    return st
end

function width(space::IndexSpace, dims)
    n = 1
    for d in dims
        n *= list_size(space, d)
    end
    return n
end

function offset_of(space::IndexSpace, dims, tuple_)
    st = strides(space, dims)
    off = 0
    for (i, d) in enumerate(dims)
        pos = get(get_list(space, d).position_of, tuple_[i], nothing)
        pos === nothing && throw(IndexSpaceError("'$(tuple_[i])' is not an enabled index of '$d'"))
        off += pos * st[i]
    end
    return off
end

"""The index names at a 0-based offset of a block of dimensions `dims`."""
function tuple_at(space::IndexSpace, dims, offset::Integer)
    st = strides(space, dims)
    out = String[]
    rest = offset
    for (i, d) in enumerate(dims)
        k = div(rest, st[i])
        rest -= k * st[i]
        push!(out, get_list(space, d).enabled[k+1].name)
    end
    return out
end

"""
    positions(space, dims) -> Vector{Vector{Int}}

For every offset of a block of these dimensions, its 0-based position along
each dimension: one vector per dimension, in offset order (the last
dimension fastest).
"""
function positions(space::IndexSpace, dims)
    isempty(dims) && return Vector{Int}[]
    sizes = [list_size(space, d) for d in dims]
    w = prod(sizes)
    w == 0 && return [Int[] for _ in dims]
    nd = length(dims)
    out = [Vector{Int}(undef, w) for _ in 1:nd]
    st = strides(space, dims)
    @inbounds for off in 0:w-1
        rest = off
        for i in 1:nd
            k = div(rest, st[i])
            rest -= k * st[i]
            out[i][off+1] = k
        end
    end
    return out
end

"""How a position in `to_list` translates into `from_list`: `(kind=:same)`,
`(kind=:map, table, partial)`, or `nothing` for unrelated lists."""
function relate(space::IndexSpace, from_list, to_list)
    from_list == to_list && return (kind=:same, table=Int[], partial=false)
    (from_list isa String && to_list isa String) || return _relate(space, from_list, to_list)
    key = (from_list, to_list)
    found = get(space.relate_cache, key, missing)
    found === missing || return found
    rel = _relate(space, from_list, to_list)
    space.relate_cache[key] = rel
    return rel
end

function _relate(space::IndexSpace, from_list, to_list)
    a = get_list(space, from_list)
    b = get_list(space, to_list)
    a.root_name == b.root_name || return nothing
    table = fill(-1, b.size)
    for k in 1:b.size
        r = b.up[k]
        r >= 0 && (table[k] = a.down[r+1])
    end
    return (kind=:map, table=table, partial=any(<(0), table))
end

function missing_from(space::IndexSpace, dim, frm)
    rel = relate(space, dim, frm)
    (rel === nothing || rel.kind === :same) && return String[]
    names = index_names(space, frm)
    out = [names[k] for k in 1:length(rel.table) if rel.table[k] < 0 && k <= length(names)]
    return isempty(out) ? ["missing indices"] : out
end

"""One target dimension's term of a projection."""
struct ProjTerm
    stride::Int
    dim::String
    fixed::Int             # -1 when the position comes from the source
    from::Int              # which source dimension (1-based), 0 when fixed
    table::Union{Nothing,Vector{Int}}
    partial::Bool
end

"""
    projection(space, source_dims, target_dims, fixed=Dict(), context=(owner=nothing, target=nothing))

How to read a block of `target_dims` from inside one of `source_dims`: one
term per target dimension, carried directly, through a sub-set's or a
mapping's table, or pinned to one index.
"""
function projection(space::IndexSpace, source_dims, target_dims, fixed_indices=nothing, context=nothing)
    fixed_indices = something(fixed_indices, Dict{String,String}())
    ctx_target = context === nothing ? nothing : get(context, :target, nothing)
    ctx_owner = context === nothing ? nothing : get(context, :owner, nothing)
    st = strides(space, target_dims)
    terms = ProjTerm[]
    for (i, dim) in enumerate(target_dims)
        stride = st[i]
        if haskey(fixed_indices, dim)
            pos = get(get_list(space, dim).position_of, fixed_indices[dim], nothing)
            pos === nothing && throw(IndexSpaceError("'$(fixed_indices[dim])' is not an enabled index of '$dim'"))
            push!(terms, ProjTerm(stride, dim, pos, 0, nothing, false))
            continue
        end
        best = nothing
        for (s, sd) in enumerate(source_dims)
            rel = relate(space, dim, sd)
            rel === nothing && continue
            if rel.kind === :same
                best = ProjTerm(stride, dim, -1, s, nothing, false)
                break
            end
            here = ProjTerm(stride, dim, -1, s, rel.table, rel.partial)
            if best === nothing || (best.partial && !here.partial)
                best = here
            end
        end
        if best === nothing || best.partial
            what = ctx_target !== nothing ? "'$ctx_target'" : "that block"
            where_ = ctx_owner !== nothing ? "'$ctx_owner'" : "this block"
            first_name = (n = index_names(space, dim); isempty(n) ? "index" : n[1])
        end
        if best !== nothing && best.partial
            frm = source_dims[best.from]
            throw(IndexSpaceError("$what is indexed by '$dim', which does not cover every index of '$frm' -- so for " *
                                  "some of them $where_ has no value to read. Give '$dim' the missing " *
                                  "$(join(missing_from(space, dim, frm), ", ")), or write an explicit index, as in " *
                                  "$(something(ctx_target, "block"))[$first_name].", dim))
        end
        if best === nothing
            throw(IndexSpaceError("$what is indexed by '$dim', which $where_ is not indexed by and cannot reach. Give " *
                                  "an explicit index, as in $(something(ctx_target, "block"))[$first_name], or add " *
                                  "'$dim' to $where_.", dim))
        end
        push!(terms, best)
    end
    return terms
end

function normalise_dims(dims)
    seen = Set{String}()
    out = String[]
    for d in something(dims, Any[])
        ds = string(d)
        ds in seen && throw(IndexSpaceError("Index list '$ds' is used twice on the same block"))
        push!(seen, ds)
        push!(out, ds)
    end
    return out
end
