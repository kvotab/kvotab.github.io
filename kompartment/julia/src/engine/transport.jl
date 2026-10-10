# Transport sub-systems, unrolled into the chain they stand for
# (kompartment/python/kompartment/engine/transport.py, itself a port of
# src/sim/transport.js and the helpers of src/domain/transport.js).
#
# A transport is a sub-system drawn as two compartments -- its Begin and its
# End -- standing for a chain of N identical ones. Before anything is laid
# out, the chain is written out as ordinary compartments and transfers: the
# elements in between are copies of Begin (marked `hidden`), the transfers
# between Begin and End are repeated for every pair, and the expressions those
# read are copied per pair. A transport operation (the sum or mean over the
# chain, or a value at a point along it) becomes an expression or a call of
# `transport_point`/`transport_sum`/`transport_mean`. The result is a new
# `Project`, so nothing downstream has to know a chain from a model.

"""A transport that cannot be unrolled, and the block (or sub-system) it is about."""
struct TransportError <: Exception
    message::String
    block_name::Union{Nothing,String}
end
TransportError(message::AbstractString, block_name=nothing) =
    TransportError(String(message), block_name === nothing ? nothing : string(block_name))
Base.showerror(io::IO, e::TransportError) = print(io, e.message)

"""The equations of each collection a transport expansion reads and rewrites, in the Python engine's order."""
const TRANSPORT_EQUATION_KEYS = let
    d = OrderedDict{String,Vector{String}}(
        "compartments" => ["initial", "dydt"],
        "transfers" => ["rate"],
        "inflows" => ["rate"],
        "expressions" => ["equation"],
        "farfields" => collect(String, FARF_EQUATION_KEYS),
    )
    for (kind, plural) in (("min_max", "min_maxes"), ("running_mean", "running_means"), ("snapshot", "snapshots"),
                           ("delay", "delays"), ("trigger", "triggers"))
        d[plural] = String[EQUATION_FIELDS[kind]..., EVENT_FIELDS[kind]...]
    end
    d
end

"""A key a patch removes rather than sets (JavaScript's `undefined`)."""
struct _Undefined end
const _UNDEFINED = _Undefined()

transport_role(block) = py_truthy(block) ? get(block, "transport", nothing) : nothing

"""The sub-systems of a project that are transports."""
function transport_paths(project::Project)
    return String[p for p in project.transports if !isempty(p)]
end

_project_blocks(project::Project, key) = get(project.blocks, key, JDict[])

"""
What an expansion looks blocks up by, worked out once: the project's blocks do
not change while it runs, and a model of many transports would otherwise read
every block of the model again for each one. Every lookup gives what the scan
it stands for gives, in the same order.

- `own`: collection => sub-system => its blocks, in the project's order;
- `pairs`: a transfer's `(from, to)` => its positions among the project's transfers;
- `names`: a block (by identity) => its qualified name, worked out once;
- `reading`: a base name => where it is read, `(group, position)` in the order
  the counter check scans the groups, made when a counter is first checked.
"""
mutable struct _TransportIndex
    own::Dict{String,Dict{String,Vector{JDict}}}
    pairs::Dict{Tuple{Any,Any},Vector{Int}}
    names::IdDict{Any,String}
    reading::Union{Nothing,Dict{String,Vector{Tuple{Int,Int}}}}
end

function _transport_index(project::Project)
    own = Dict{String,Dict{String,Vector{JDict}}}()
    for key in ("compartments", "expressions", "transfers", "inflows")
        by = Dict{String,Vector{JDict}}()
        for b in _project_blocks(project, key)
            push!(get!(() -> JDict[], by, system_of(b)), b)
        end
        own[key] = by
    end
    pairs = Dict{Tuple{Any,Any},Vector{Int}}()
    for (k, t) in enumerate(_project_blocks(project, "transfers"))
        push!(get!(() -> Int[], pairs, (get(t, "from", nothing), get(t, "to", nothing))), k)
    end
    return _TransportIndex(own, pairs, IdDict{Any,String}(), nothing)
end

"""A block's qualified name, worked out once per block."""
_qname(ix::_TransportIndex, b) = get!(() -> qualified_name(b), ix.names, b)

"""The groups the counter check reads, in its order: the blocks and the keys of each."""
_counter_groups(project::Project) = ((_project_blocks(project, "expressions"), ["equation"]),
                                     (_project_blocks(project, "transfers"), ["rate"]),
                                     (_project_blocks(project, "inflows"), ["rate"]),
                                     (_project_blocks(project, "compartments"), ["initial", "dydt"]))

"""
A block's texts under `keys`, and the last component of every name they hold --
worked out once for each block in an expansion (the project's blocks do not
change while it runs).
"""
function _texts_of(read, tokens, block, keys)
    at = (objectid(block), Tuple(keys))
    got = get(read, at, nothing)
    if got === nothing
        texts = String[]
        for key in keys
            v = get(block, key, nothing)
            v isa AbstractString && push!(texts, String(v))
            for e in _py_iter(get(block, "entries", nothing))
                x = jget(e, key)
                x isa AbstractString && push!(texts, String(x))
            end
        end
        last = Set{String}()
        for text in texts
            toks = _transport_tokens(text, tokens)
            toks === nothing && continue
            for tok in toks
                tok.type === :ident && push!(last, base_name(tok.text))
            end
        end
        got = (texts, last)
        read[at] = got
    end
    return got
end

"""Where each base name is read among the counter check's groups: `(group, position)`, in its scan order."""
function _reading_index!(ix::_TransportIndex, project::Project, read, tokens)
    ix.reading === nothing || return ix.reading
    out = Dict{String,Vector{Tuple{Int,Int}}}()
    for (g, (blocks, keys)) in enumerate(_counter_groups(project))
        for (pos, b) in enumerate(blocks)
            _, last = _texts_of(read, tokens, b, keys)
            for name in last
                push!(get!(() -> Tuple{Int,Int}[], out, name), (g, pos))
            end
        end
    end
    for v in values(out)
        sort!(v)
    end
    ix.reading = out
    return out
end

"""
    transport_parts(project, path)

A transport's parts: its Begin and End compartments, its number and counter,
and its operations (every one of each, and the first as `begin_` and so on).
"""
function transport_parts(project::Project, path, ix::Union{Nothing,_TransportIndex}=nothing)
    own(key) = ix === nothing ? [b for b in _project_blocks(project, key) if system_of(b) == path] :
               get(ix.own[key], path, JDict[])
    with_role(key, role) = [b for b in own(key) if transport_role(b) == role]
    begins = with_role("compartments", "begin")
    ends = with_role("compartments", "end")
    numbers = with_role("expressions", "number")
    counters = with_role("expressions", "counter")
    operations = with_role("expressions", "operation")
    first_or_nothing(v) = isempty(v) ? nothing : v[1]
    return (path=path, begin_=first_or_nothing(begins), begins=begins, end_=first_or_nothing(ends), ends=ends,
            number=first_or_nothing(numbers), numbers=numbers, counter=first_or_nothing(counters),
            counters=counters, operations=operations)
end

"""The transfers drawn between a transport's Begin and End, either way."""
function internal_transfers(project::Project, parts, ix::Union{Nothing,_TransportIndex}=nothing)
    b = parts.begin_ === nothing ? nothing : qualified_name(parts.begin_)
    e = parts.end_ === nothing ? nothing : qualified_name(parts.end_)
    (py_truthy(b) && py_truthy(e)) || return JDict[]
    every = _project_blocks(project, "transfers")
    if ix !== nothing
        at = sort!(unique!(vcat(get(ix.pairs, (b, e), Int[]), get(ix.pairs, (e, b), Int[]))))
        return JDict[every[k] for k in at]
    end
    return [t for t in every
            if (get(t, "from", nothing) == b && get(t, "to", nothing) == e) ||
               (get(t, "from", nothing) == e && get(t, "to", nothing) == b)]
end

"""How many compartments a transport's chain has: `(n, value, why)`, `why` saying why not when it cannot be known."""
function transport_number(project::Project, parts)
    N = parts.number
    if N === nothing
        return (n=nothing, value=nothing,
                why="'$(parts.path)' has no transport number, so the length of its chain is not known. Add one " *
                    "(an expression with the part \"number\").")
    end
    name = qualified_name(N)
    value = constant_value(project, N, "expression")
    if value === nothing
        return (n=nothing, value=nothing,
                why="'$name' cannot be worked out before the run starts. The number of compartments in a transport " *
                    "may use numbers, parameters and expressions made of those, and nothing that changes over the run.")
    end
    n = abs(value) < 9.0e18 ? trunc(Int, value) : (value > 0 ? typemax(Int) : typemin(Int))
    if n < 1
        return (n=nothing, value=value, why="'$name' comes to $(js_number(value)), and a transport needs at least one compartment.")
    end
    return (n=n, value=value, why=nothing)
end

"""A block's copy without its transport part, its qualified name and its kind, with `patch` applied in its order."""
function _plain_block(block, patch=nothing)
    out = JDict()
    for (k, v) in block
        (k == "transport" || k == "qname" || k == "kind") && continue
        out[k] = v
    end
    if patch !== nothing
        for (key, value) in patch
            if value === _UNDEFINED
                delete!(out, key)
            else
                out[key] = value
            end
        end
    end
    return out
end

"""`tokenize(src)`, or `nothing` where it fails -- kept in `cache` when one is given."""
function _transport_tokens(src::String, cache)
    if cache !== nothing
        hit = get(cache, src, cache)
        hit !== cache && return hit
    end
    tokens = try
        tokenize(src)
    catch e
        e isa EquationSyntaxError || rethrow()
        nothing
    end
    cache !== nothing && (cache[src] = tokens)
    return tokens
end

"""The characters `a+1 .. b` of `src` (0-based character offsets, as the tokenizer counts)."""
@inline _char_slice(src::String, chars::Union{Nothing,Vector{Char}}, a::Int, b::Int) =
    chars === nothing ? src[a+1:b] : String(chars[a+1:b])

"""
    _rewrite_refs(text, system, known, replace, cache=nothing) -> String

`text` with every name that refers to a block replaced by `replace(qname)`
where that gives something else; everything between is kept as written.
"""
function _rewrite_refs(text, system, known, replace, cache=nothing)
    src = text === nothing ? "" : _norm_str(text)
    isempty(src) && return src
    tokens = _transport_tokens(src, cache)
    tokens === nothing && return src
    chars = isascii(src) ? nothing : collect(src)
    nchar = chars === nothing ? ncodeunits(src) : length(chars)
    out = IOBuffer()
    cursor = 0
    isknown = n -> n in known
    for (i, tok) in enumerate(tokens)
        tok.type === :ident || continue
        (i < length(tokens) && tokens[i+1].type === :lparen && lookup_function(tok.text) !== nothing) && continue
        q = resolve_reference(tok.text, system, isknown)
        q === nothing && continue
        to = replace(q)
        (to === nothing || to == tok.text) && continue
        print(out, _char_slice(src, chars, cursor, tok.pos), to)
        cursor = tok.pos + length(tok.text)
    end
    cursor == 0 && return src
    print(out, _char_slice(src, chars, cursor, nchar))
    return String(take!(out))
end

"""`text` with every call of the operation `target` written as a call of `fn_name` over the chain's elements."""
function _rewrite_calls(text, system, target, fn_name, elements, arity, known, owner)
    src = text === nothing ? "" : _norm_str(text)
    (isempty(src) || !occursin(base_name(target), src)) && return src
    tokens = try
        tokenize(src)
    catch e
        e isa EquationSyntaxError || rethrow()
        return src
    end
    chars = isascii(src) ? nothing : collect(src)
    nchar = chars === nothing ? ncodeunits(src) : length(chars)
    isknown = n -> n in known
    out = IOBuffer()
    cursor = 0
    for (i, tok) in enumerate(tokens)
        (tok.type !== :ident || i + 1 > length(tokens) || tokens[i+1].type !== :lparen) && continue
        lookup_function(tok.text) !== nothing && continue
        q = resolve_reference(tok.text, system, isknown)
        q == target || continue
        depth = 0
        commas = 0
        empty = true
        for j in i+1:length(tokens)
            t = tokens[j]
            if t.type === :lparen
                depth += 1
            elseif t.type === :rparen
                depth -= 1
                depth == 0 && break
            elseif t.type === :comma && depth == 1
                commas += 1
            end
            (depth == 1 && j > i + 1) && (empty = false)
        end
        given = empty ? 0 : commas + 1
        if given != arity
            wants = arity == 1 ? "one position along the chain, between 0 and 1" :
                    "two positions along the chain, each between 0 and 1"
            was = given == 1 ? " was" : "s were"
            throw(TransportError("'$(tok.text)' is a transport operation that takes $wants; $given argument$was given.",
                                 owner))
        end
        spelled = [reference_from(e, system, isknown) for e in elements]
        opening = tokens[i+1]
        print(out, _char_slice(src, chars, cursor, tok.pos), fn_name, "(", join(spelled, ", "), ", ")
        cursor = opening.pos + 1
    end
    cursor == 0 && return src
    print(out, _char_slice(src, chars, cursor, nchar))
    return String(take!(out))
end

"""
    project_to_json(p::Project) -> JDict

The project as a file holds it (Python's `Project.to_json`, the application's
`toJSON`): the blocks that run and the ones switched off, normalised, in the
same key order.
"""
function project_to_json(p::Project)
    every(key) = Any[get(p.blocks, key, JDict[])..., get(p.switched_off, key, JDict[])...]
    out = JDict("name" => p.name, "description" => p.description, "simulation" => p.simulation,
                "nuclides" => p.nuclides, "half_lives" => p.half_lives_override, "decay_unit" => p.decay_unit)
    p.chains_override !== nothing && (out["chains"] = p.chains_override)
    out["index_lists"] = Any[l for l in p.index_lists if !(l["name"] in p.derived_lists)]
    py_truthy(p.scenario) && (out["scenario"] = p.scenario)
    for key in ("parameters", "compartments", "expressions", "transfers", "inflows")
        out[key] = every(key)
    end
    for key in ("lookups", "index_reductions", "block_reductions", "functions", "min_maxes", "running_means",
                "snapshots", "delays", "triggers", "farfields", "waste_packages", "events")
        present = key in ("index_reductions", "triggers") ? get(p.blocks, key, JDict[]) : every(key)
        isempty(present) || (out[key] = every(key))
    end
    isempty(p.transports) || (out["transports"] = collect(Any, p.transports))
    isempty(p.disabled_systems) || (out["disabled_systems"] = collect(Any, unique(p.disabled_systems)))
    isempty(p.systems) || (out["systems"] = collect(Any, p.systems))
    out["layout"] = p.layout
    isempty(p.shapes) || (out["shapes"] = p.shapes)
    isempty(p.derived) || (out["derived"] = p.derived)
    (p.view !== nothing && !isempty(p.view)) && (out["view"] = p.view)
    return out
end

"""
    expand_transports(project) -> Project

The project with every transport written out as its chain. What stops a
transport being one is a `BuildError` naming the block concerned, as the
builder reports it.
"""
function expand_transports(project::Project)
    try
        return _expand_transports(project)
    catch e
        e isa TransportError || rethrow()
        throw(BuildError(e.message, e.block_name))
    end
end

function _expand_transports(project::Project)
    paths = [q for q in transport_paths(project) if q in project.systems]
    isempty(paths) && return project
    raw = JDict(project_to_json(project))
    for key in ("compartments", "expressions", "transfers", "inflows")
        raw[key] = collect(Any, _py_iter(get(raw, key, nothing)))
    end
    delete!(raw, "transports")
    known = Set{String}()
    for key in Iterators.flatten((keys(TRANSPORT_EQUATION_KEYS), ("parameters", "lookups", "index_reductions", "block_reductions")))
        for b in _py_iter(get(raw, key, nothing))
            push!(known, qualified_name(b))
        end
    end
    taken = copy(known)
    off = Set{String}()
    tokens = Dict{String,Any}()
    read = Dict{Any,Any}()
    ix = _transport_index(project)
    for path in paths
        _expand_one!(project, raw, path, known, taken, off, tokens, read, ix)
    end
    # A Project copies what it is given, so raw needs no copy of its own.
    derived = Project(raw)
    derived.disabled = union(Set{String}(project.disabled), derived.disabled, off)
    derived.implicitly_disabled = merge(project.implicitly_disabled, derived.implicitly_disabled)
    return derived
end

function _expand_one!(project::Project, raw::JDict, path::String, known::Set{String}, taken::Set{String},
                      off::Set{String}, tokens, read, ix::_TransportIndex)
    parts = transport_parts(project, path, ix)
    switched_off = any(n -> parent_of(n) == path, project.disabled)
    if (isempty(parts.begins) || isempty(parts.ends)) && switched_off
        going = Set{String}(b["qname"] for b in Iterators.flatten((parts.begins, parts.ends, parts.numbers,
                                                                   parts.counters, parts.operations)))
        raw["compartments"] = Any[b for b in raw["compartments"] if !(_qname(ix, b) in going)]
        raw["expressions"] = Any[b for b in raw["expressions"] if !(_qname(ix, b) in going)]
        union!(off, going)
        return
    end
    if length(parts.begins) != 1 || length(parts.ends) != 1
        function count(lst, what)
            n = length(lst)
            return "$(n == 0 ? "no" : string(n)) $what$(n == 1 ? "" : (n != 0 ? "s" : ""))"
        end
        what = String[]
        length(parts.begins) != 1 && push!(what, count(parts.begins, "Begin compartment"))
        length(parts.ends) != 1 && push!(what, count(parts.ends, "End compartment"))
        throw(TransportError("'$path' is a transport with $(join(what, " and ")). A transport is a chain from one Begin " *
                             "to one End.", path))
    end
    B, E = parts.begin_, parts.end_
    bq, eq = B["qname"], E["qname"]
    dims_text(b) = join(sort!(String[string(d) for d in _py_iter(get(b, "index_lists", nothing))]), " ")
    if dims_text(B) != dims_text(E)
        throw(TransportError("'$eq' is not indexed by the same lists as '$bq'. Every compartment of the chain is one " *
                             "compartment repeated, so Begin and End must match.", eq))
    end
    number = transport_number(project, parts)
    number.why !== nothing && throw(TransportError(number.why, parts.number !== nothing ? parts.number["qname"] : path))
    n = number.n
    C = parts.counter
    cq = C === nothing ? nothing : C["qname"]
    internal = internal_transfers(project, parts, ix)
    internal_names = Set{String}(t["qname"] for t in internal)
    dependent = JDict[]
    dependent_names = Set{String}()

    function pair_names()
        s = Set{String}([bq, eq])
        cq === nothing || push!(s, cq)
        union!(s, internal_names, dependent_names)
        return s
    end

    # A reference keeps its last component whatever it resolves to, so a
    # block none of whose names ends as one of `bases` refers to none of `names`.
    function refs_any(block, keys, names, bases)
        texts, last = _texts_of(read, tokens, block, keys)
        any(b -> b in last, bases) || return false
        for text in texts
            any(b -> occursin(b, text), bases) || continue
            found = Ref(false)
            note = q -> (q in names && (found[] = true); nothing)
            # Resolved where the block that writes it sits: from inside this
            # chain, a bare `i` in a second transport was this one's counter.
            _rewrite_refs(text, system_of(block), known, note, tokens)
            found[] && return true
        end
        return false
    end

    grew = true
    inside = get(ix.own["expressions"], path, JDict[])
    while grew
        grew = false
        names = pair_names()
        bases = Set{String}(base_name(q) for q in names)
        for x in inside
            (py_truthy(transport_role(x)) || x["qname"] in dependent_names) && continue
            if refs_any(x, ["equation"], names, bases)
                push!(dependent, x)
                push!(dependent_names, x["qname"])
                grew = true
            end
        end
    end
    if cq !== nothing
        only = Set{String}([cq])
        bases = Set{String}([base_name(cq)])
        outside = nothing
        # Only a block that reads a name ending as the counter's can refer to it:
        # those, in the order the groups are scanned.
        groups = _counter_groups(project)
        for (g, pos) in get(_reading_index!(ix, project, read, tokens), base_name(cq), Tuple{Int,Int}[])
            blocks, keys = groups[g]
            b = blocks[pos]
            if system_of(b) != path && refs_any(b, keys, only, bases)
                outside = b
                break
            end
        end
        if outside !== nothing
            throw(TransportError("'$(outside["qname"])' reads '$cq', the element counter of '$path', from outside the " *
                                 "transport. The counter counts the compartments of the chain and has a value only " *
                                 "inside it.", outside["qname"]))
        end
    end

    function fresh(base)
        name = base
        i = 1
        while qualify(path, name) in taken
            name = "$(base)_$i"
            i += 1
        end
        push!(taken, qualify(path, name))
        return name
    end

    bname = string(B["name"])
    elem_local = Vector{Union{Nothing,String}}(nothing, n)
    elem_local[1] = bname
    n > 1 && (elem_local[n] = string(E["name"]))
    for e in 2:n-1
        elem_local[e] = fresh("$(bname)_$e")
    end
    elem_q(e) = qualify(path, elem_local[e])
    elements = String[elem_q(e) for e in 1:n]
    copy_name = Dict{String,String}()
    for e in 1:n-1
        for x in dependent
            copy_name["$(x["qname"]) $e"] = fresh("$(x["name"])_$e")
        end
        for t in internal
            copy_name["$(t["qname"]) $e"] = e == 1 ? string(t["name"]) : fresh("$(t["name"])_$e")
        end
    end

    function replace_for(e)
        return function (q)
            q == bq && return elem_local[e]
            # End read from End's own equations (e == n) has no element after it: the
            # name stays, as in the application (Python's list index fails there).
            q == eq && return e < n ? elem_local[e+1] : nothing
            (cq !== nothing && q == cq) && return string(e)
            return get(copy_name, "$q $e", nothing)
        end
    end
    rewrite(text, e) = _rewrite_refs(text, path, known, replace_for(e), tokens)
    function rewrite_entries(entries, key, e)
        out = Any[]
        for en in _py_iter(entries)
            if jget(en, key) isa AbstractString
                c = JDict(en)
                c[key] = rewrite(en[key], e)
                push!(out, c)
            else
                push!(out, JDict(en))
            end
        end
        return out
    end
    rewrite_initial(text, e) = _rewrite_refs(text, path, known, q -> (cq !== nothing && q == cq) ? string(e) : nothing, tokens)
    without(lst, names) = Any[b for b in lst if !(_qname(ix, b) in names)]
    b_dims() = collect(Any, _py_iter(get(B, "index_lists", nothing)))
    either_unit(x) = _py_or(get(x, "unit", nothing), get(B, "unit", nothing))

    if n == 1
        raw["compartments"] = without(raw["compartments"], Set([eq]))
        push!(raw["expressions"], _plain_block(E, (
            "equation" => B["name"], "unit" => either_unit(E), "index_lists" => b_dims(), "entries" => Any[],
            "initial" => _UNDEFINED, "abstol" => _UNDEFINED, "non_negative" => _UNDEFINED,
            "handle_decay" => _UNDEFINED, "dydt" => _UNDEFINED)))
        function rewire(conn)
            _qname(ix, conn) in internal_names && return nothing
            (get(conn, "from", nothing) != eq && get(conn, "to", nothing) != eq) && return conn
            out = JDict(conn)
            out["from"] = get(conn, "from", nothing) == eq ? bq : get(conn, "from", nothing)
            out["to"] = get(conn, "to", nothing) == eq ? bq : get(conn, "to", nothing)
            return out
        end
        raw["transfers"] = Any[c for c in (rewire(c) for c in raw["transfers"]) if c !== nothing]
        raw["inflows"] = Any[c for c in (rewire(c) for c in raw["inflows"]) if c !== nothing]
    else
        for e in 2:n-1
            push!(raw["compartments"], _plain_block(B, (
                "name" => elem_local[e], "system" => path, "hidden" => true, "alias" => JDict("compartment" => bq),
                "initial" => rewrite_initial(get(B, "initial", nothing), e),
                "dydt" => get(B, "dydt", nothing) isa AbstractString ? rewrite(B["dydt"], e) : _UNDEFINED,
                "entries" => rewrite_entries(rewrite_entries(get(B, "entries", nothing), "initial", e), "dydt", e),
                "color" => _UNDEFINED, "symbol" => _UNDEFINED, "comment" => "")))
        end
        function end_block(c)
            _qname(ix, c) != eq && return c
            initial_entries = Any[]
            for en in rewrite_entries(get(B, "entries", nothing), "initial", n)
                rest = JDict(k => v for (k, v) in en if k != "dydt")
                any(k -> k != "index", keys(rest)) && push!(initial_entries, rest)
            end
            dydt_entries = Any[JDict("index" => jget(en, "index"), "dydt" => rewrite(en["dydt"], n))
                               for en in _py_iter(get(E, "entries", nothing)) if jget(en, "dydt") isa AbstractString]
            return _plain_block(B, (
                "name" => E["name"], "system" => path, "unit" => either_unit(E),
                "comment" => get(E, "comment", nothing), "color" => get(E, "color", nothing),
                "symbol" => get(E, "symbol", nothing),
                "initial" => rewrite_initial(get(B, "initial", nothing), n),
                "dydt" => get(E, "dydt", nothing) isa AbstractString ? rewrite(E["dydt"], n) : _UNDEFINED,
                "entries" => Any[initial_entries..., dydt_entries...]))
        end
        raw["compartments"] = Any[end_block(c) for c in raw["compartments"]]
        raw["transfers"] = without(raw["transfers"], internal_names)
        for e in 1:n-1
            for x in dependent
                push!(raw["expressions"], _plain_block(x, (
                    "name" => copy_name["$(x["qname"]) $e"], "system" => path, "hidden" => true,
                    "equation" => rewrite(get(x, "equation", nothing), e),
                    "entries" => rewrite_entries(get(x, "entries", nothing), "equation", e),
                    "color" => _UNDEFINED, "symbol" => _UNDEFINED, "comment" => "")))
            end
            for t in internal
                forward = get(t, "from", nothing) == bq
                patch = Pair{String,Any}[
                    "name" => copy_name["$(t["qname"]) $e"], "system" => path,
                    "alias" => JDict("transfer" => t["qname"], "from" => get(t, "from", nothing), "to" => get(t, "to", nothing)),
                    "from" => forward ? elem_q(e) : elem_q(e + 1),
                    "to" => forward ? elem_q(e + 1) : elem_q(e),
                    "rate" => rewrite(get(t, "rate", nothing), e),
                    "entries" => rewrite_entries(get(t, "entries", nothing), "rate", e)]
                e != 1 && append!(patch, Pair{String,Any}["hidden" => true, "color" => _UNDEFINED, "comment" => ""])
                push!(raw["transfers"], _plain_block(t, patch))
            end
        end
    end
    if n == 1
        for t in internal
            entries = Any[]
            for en in _py_iter(get(t, "entries", nothing))
                rest = JDict(k => v for (k, v) in en if k != "rate")
                if jget(en, "rate") isa AbstractString
                    rest["equation"] = en["rate"]
                end
                push!(entries, rest)
            end
            push!(raw["expressions"], _plain_block(t, (
                "equation" => get(t, "rate", nothing), "entries" => entries, "from" => _UNDEFINED, "to" => _UNDEFINED,
                "multiply_by_donor" => _UNDEFINED, "index_lists" => b_dims())))
        end
    end
    if C !== nothing
        raw["expressions"] = Any[_qname(ix, x) != cq ? x : _plain_block(C, ("equation" => "1", "hidden" => true))
                                 for x in raw["expressions"]]
    end
    number_q = parts.number["qname"]
    raw["expressions"] = Any[_qname(ix, x) != number_q ? x : _plain_block(x) for x in raw["expressions"]]
    locals_ = String[base_name(q) for q in elements]
    for op in parts.operations
        oq = op["qname"]
        mean = _py_or(get(op, "operation", nothing), "mean") == "mean"
        if _py_or(get(op, "argument", nothing), "all") == "all"
            total = length(locals_) == 1 ? locals_[1] : join(locals_, " + ")
            raw["expressions"] = Any[_qname(ix, x) != oq ? x : _plain_block(op, (
                "equation" => mean ? "($total) / $n" : total, "index_lists" => b_dims(),
                "unit" => _py_or(get(op, "unit", nothing), get(B, "unit", nothing)), "entries" => Any[],
                "operation" => _UNDEFINED, "argument" => _UNDEFINED)) for x in raw["expressions"]]
            continue
        end
        raw["expressions"] = without(raw["expressions"], Set([oq]))
        point = get(op, "argument", nothing) == "point"
        fn_name = point ? "transport_point" : (mean ? "transport_mean" : "transport_sum")
        arity = point ? 1 : 2
        for (collection, keys_) in TRANSPORT_EQUATION_KEYS
            new_list = Any[]
            for b in _py_iter(get(raw, collection, nothing))
                system = system_of(b)
                owner = _qname(ix, b)
                changed = nothing
                for key in keys_
                    v = get(b, key, nothing)
                    if v isa AbstractString
                        nxt = _rewrite_calls(v, system, oq, fn_name, elements, arity, taken, owner)
                        if nxt != v
                            changed === nothing && (changed = JDict(b))
                            changed[key] = nxt
                        end
                    end
                    for (i, en) in enumerate(_py_iter(get(b, "entries", nothing)))
                        x = jget(en, key)
                        x isa AbstractString || continue
                        nxt = _rewrite_calls(x, system, oq, fn_name, elements, arity, taken, owner)
                        nxt == x && continue
                        changed === nothing && (changed = JDict(b))
                        if get(changed, "entries", nothing) === get(b, "entries", nothing)
                            changed["entries"] = Any[JDict(y) for y in _py_iter(get(b, "entries", nothing))]
                        end
                        changed["entries"][i][key] = nxt
                    end
                end
                push!(new_list, changed === nothing ? b : changed)
            end
            (haskey(raw, collection) || !isempty(new_list)) && (raw[collection] = new_list)
        end
    end
    return nothing
end
