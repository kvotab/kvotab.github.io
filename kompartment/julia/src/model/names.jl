# Names, sub-systems and how a name written in an equation finds its block.
#
# A block has a local name (`Water`) and lives in a sub-system, a dotted path
# (`NearField.Geosphere`; the top level is ""). Its qualified name is the two
# joined, `NearField.Geosphere.Water`. An equation refers to a block by a
# name resolved from the sub-system it is written in: a dotted name is a full
# path from the top level; a bare name is looked up in the writer's own
# sub-system first, then at the top level -- never in between.

"""What a block, an index list or a sub-system component may be called."""
const NAME_RE = r"^[A-Za-z_][A-Za-z0-9_]*$"

const SEPARATOR = '.'

"""The names no block may take: the language's functions and kept words."""
const RESERVED = let
    data = parse_json(read(joinpath(@__DIR__, "..", "..", "data", "reserved.json"), String))
    Set{String}(String.(data["names"]))
end

is_name(name) = name isa AbstractString && occursin(NAME_RE, name)

"""What is wrong with `name` as a block's local name, or `nothing`."""
function name_problem(name)
    is_name(name) || return "'$(name)' is not a valid name: use letters, digits and underscore, and do not start with a digit."
    name in RESERVED && return "'$(name)' is a reserved name."
    return nothing
end

"""The components of a sub-system path; "" has none."""
path_parts(path) = path === nothing || path == "" ? String[] : [String(p) for p in split(string(path), SEPARATOR) if !isempty(p)]

"""`system` and `name` joined into a qualified name."""
qualify(system, name) = (system === nothing || system == "") ? String(name) : string(system, SEPARATOR, name)

"""The sub-system a path is inside: `A.B.C` -> `A.B`, `A` -> ""."""
parent_of(path) = join(path_parts(path)[1:end-1], SEPARATOR)

"""The last component of a path: `A.B.C` -> `C`."""
function base_name(path)
    path === nothing && return ""
    s = path isa String ? path : string(path)
    # The last component that is not empty, as `path_parts` counts them.
    hi = lastindex(s)
    while hi >= 1 && s[hi] == SEPARATOR
        hi = prevind(s, hi)
    end
    hi < 1 && return ""
    lo = findprev(==(SEPARATOR), s, hi)
    return lo === nothing ? (hi == lastindex(s) ? s : s[1:hi]) : s[nextind(s, lo):hi]
end

"""Whether `path` is `ancestor` or somewhere inside it; everything is within ""."""
function is_within(path, ancestor)
    (ancestor === nothing || ancestor == "") && return true
    p = path === nothing ? "" : string(path)
    return p == ancestor || startswith(p, string(ancestor, SEPARATOR))
end

"""Whether a sub-system path is well formed: every component a name."""
function is_valid_path(path)
    (path === nothing || path == "") && return true
    return all(c -> occursin(NAME_RE, c), split(string(path), SEPARATOR))
end

"""The sub-system a raw block lives in."""
system_of(block) = (s = jget(block, "system"); s === nothing || s == false ? "" : string(s))

"""A raw block's qualified name."""
qualified_name(block) = qualify(system_of(block), (n = jget(block, "name"); n === nothing ? "" : string(n)))

"""
    resolve_reference(reference, system, known) -> Union{String,Nothing}

The qualified name a reference written in `system` means, or `nothing`.
`known(qname)` says whether a block of that name exists.
"""
function resolve_reference(reference, system, known)
    ref = string(reference)
    if occursin(SEPARATOR, ref)
        return known(ref) ? ref : nothing
    end
    own = qualify(system, ref)
    known(own) && return own
    return known(ref) ? ref : nothing
end

"""How a reference to `target` is written from inside `system`."""
function reference_from(target, system, known)
    parent = parent_of(target)
    local_ = base_name(target)
    if (parent == "" || parent == system) && resolve_reference(local_, system, known) == target
        return local_
    end
    return target
end

# JavaScript's `localeCompare` for identifier-like names: case folded first,
# lower case before upper on a tie (Python's `(casefold, swapcase)` key).
_swapcase(s) = map(c -> isuppercase(c) ? lowercase(c) : islowercase(c) ? uppercase(c) : c, s)
locale_key(s::AbstractString) = (lowercase(s), _swapcase(s))

"""
    system_paths(declared, transports, block_systems) -> Vector{String}

Every sub-system a model has, shallowest first: every prefix of every
declared path, transport path and block's sub-system.
"""
function system_paths(declared, transports, block_systems)
    seen = Set{String}()
    for source in (declared, transports)
        source === nothing && continue
        for item in source
            path = item isa AbstractDict ? get(item, "name", nothing) : item
            path isa AbstractString && _add_prefixes!(seen, path)
        end
    end
    for path in block_systems
        _add_prefixes!(seen, path)
    end
    return sort!(collect(seen); by=p -> (length(path_parts(p)), locale_key(p)))
end

function _add_prefixes!(seen, path)
    ps = path_parts(path)
    for k in 1:length(ps)
        push!(seen, join(ps[1:k], SEPARATOR))
    end
end
