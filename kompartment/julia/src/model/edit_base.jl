# What the editing API stands on: the error it raises, Python's way of writing
# values into messages and reading numbers, the model's blocks by name and its
# sub-systems (kept between edits as the Python package keeps them), the index
# lists including the ones worked out from the model, and the rewriting of
# references in equations and in an app laid out on the model.
#
# The editing API is the Python package's (kompartment/python/kompartment:
# model.py, blocks.py, equations.py, apps.py), which is itself checked against
# the application's src/domain/edit.js: the same edits make the same file,
# key order included, and refuse what it refuses with the same words.

"""
    EditError(message, detail=nothing)

An edit the model cannot take: a name already used, a block that does not
exist, a value outside what the setting allows, a delete that would leave an
equation reading nothing. `detail` names what was in the way, where that is a
list of blocks.
"""
struct EditError <: Exception
    message::String
    detail::Union{Nothing,Vector{String}}
end
EditError(message::AbstractString) = EditError(String(message), nothing)
EditError(message::AbstractString, detail) =
    EditError(String(message), detail === nothing ? nothing : String[string(x) for x in detail])
Base.showerror(io::IO, e::EditError) = print(io, "EditError: ", e.message)

# --- Python's way of writing a value into a message ----------------------------------------------

_py_printable(c::Char) = isvalid(c) && (c == ' ' ||
    !(Base.Unicode.category_abbrev(c) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp", "Zs")))

"""Python's `repr` of a string: single quotes unless it holds one and no double quote."""
function _py_repr_str(s::AbstractString)
    q = (occursin('\'', s) && !occursin('"', s)) ? '"' : '\''
    io = IOBuffer()
    write(io, q)
    for c in s
        if c == q || c == '\\'
            write(io, '\\', c)
        elseif c == '\t'
            write(io, "\\t")
        elseif c == '\n'
            write(io, "\\n")
        elseif c == '\r'
            write(io, "\\r")
        elseif _py_printable(c)
            write(io, c)
        else
            u = isvalid(c) ? UInt32(c) : UInt32(0xfffd)
            if u < 0x100
                write(io, "\\x", string(u; base=16, pad=2))
            elseif u < 0x10000
                write(io, "\\u", string(u; base=16, pad=4))
            else
                write(io, "\\U", string(u; base=16, pad=8))
            end
        end
    end
    write(io, q)
    return String(take!(io))
end

"""Python's `repr(v)` of a value a model holds, for messages (`{v!r}`)."""
function _py_repr(v)
    v === nothing && return "None"
    v isa Bool && return v ? "True" : "False"
    v isa Integer && return string(v)
    v isa AbstractFloat && return py_repr(v)
    v isa AbstractString && return _py_repr_str(v)
    v isa Symbol && return _py_repr_str(String(v))
    v isa Tuple && return length(v) == 1 ? "(" * _py_repr(v[1]) * ",)" : "(" * join((_py_repr(x) for x in v), ", ") * ")"
    v isa AbstractVector && return "[" * join((_py_repr(x) for x in v), ", ") * "]"
    v isa AbstractDict && return "{" * join((_py_repr(k) * ": " * _py_repr(x) for (k, x) in v), ", ") * "}"
    v isa AbstractSet && return isempty(v) ? "set()" : "{" * join((_py_repr(x) for x in v), ", ") * "}"
    return string(v)
end

"""Python's `str(v)`, which an f-string writes (`{v}`)."""
_py_str(v::AbstractString) = String(v)
_py_str(v) = _py_repr(v)

"""`str(v or '')`: a value Python reads as false is the empty text."""
_py_or_text(v) = py_truthy(v) ? _py_str(v) : ""

"""Python's `format(v, 'g')`."""
function _py_g(v)
    f = Float64(v)
    isnan(f) && return "nan"
    isinf(f) && return f > 0 ? "inf" : "-inf"
    return @sprintf("%g", f)
end

"""`key.replace('_', ' ')`."""
_spaced(key) = replace(string(key), '_' => ' ')

# --- Python's way of reading a number -------------------------------------------------------------

const _PY_FLOAT_RE = r"^[+-]?(?:(?:[0-9](?:_?[0-9])*)?\.[0-9](?:_?[0-9])*|[0-9](?:_?[0-9])*\.?)(?:[eE][+-]?[0-9](?:_?[0-9])*)?$"
const _PY_INFNAN_RE = r"^[+-]?(?:inf|infinity|nan)$"i

"""
    _ed_pyfloat(v) -> Union{Float64,Nothing}

Python's `float(v)`, or `nothing` where it raises: a number as it is, a
boolean as 1 or 0, text as Python reads it (whitespace around it, `1_000`,
`inf`, `nan`), anything else refused.
"""
function _ed_pyfloat(v)
    v isa Bool && return v ? 1.0 : 0.0
    v isa Real && return Float64(v)
    v isa AbstractString || return nothing
    s = strip(v)
    if occursin(_PY_INFNAN_RE, s)
        lowercase(lstrip(s, ['+', '-'])) == "nan" && return NaN
        return startswith(s, "-") ? -Inf : Inf
    end
    occursin(_PY_FLOAT_RE, s) || return nothing
    return parse(Float64, replace(s, "_" => ""))
end

"""`v.is_integer()` for a float."""
_is_whole_float(v::Float64) = isfinite(v) && isinteger(v)

"""`int(v)` of a whole float: an `Int` where one holds it."""
_py_int(v::Float64) = (-9.223372036854776e18 <= v < 9.223372036854776e18) ? Int(v) : BigInt(v)

"""`Math.round`: halves go up, towards positive infinity (`_js_round`)."""
function _ed_js_round(v)
    f = _ed_pyfloat(v)
    f === nothing && throw(ArgumentError("$(_py_repr(v)) is not a number"))
    return _py_int(floor(f + 0.5))
end

"""
    equation_text(value) -> String

An equation as the file stores it: a string as it is, a number written as
JavaScript writes it, `nothing` as the empty equation.
"""
function equation_text(value)
    value isa Bool && throw(EditError("$(_py_repr(value)) is not an equation"))
    value isa Real && return js_number(value)
    value === nothing && return ""
    return _py_str(value)
end

"""The number an equation is when it is one written out, as JavaScript's `Number` reads it; `nothing` otherwise."""
function _written_number(text::AbstractString)
    t = strip(text)
    (isempty(t) || occursin('_', t)) && return nothing
    v = _ed_pyfloat(t)
    (v === nothing || !isfinite(v)) && return nothing
    return v
end

"""`list(dict.fromkeys(xs))`: the values in order, each once."""
function _unique_in_order(xs)
    seen = Set{Any}()
    out = Any[]
    for x in xs
        x in seen && continue
        push!(seen, x)
        push!(out, x)
    end
    return out
end

"""A block given by name or as a view: its name."""
_name_arg(x) = x

# --- the model's blocks by name, and its sub-systems, kept between edits ----------------------------

mutable struct _EdState
    index::Union{Nothing,Dict{String,Tuple{String,Any}}}
    order::Vector{String}          # the index's names in the order the Python dictionary has them
    index_fp::Vector{Any}
    systems::Union{Nothing,Vector{String}}
    systems_fp::Any
    system_lookup::Set{String}
end

const _ED_STATES = WeakKeyDict{Model,_EdState}()

_ed_state(m::Model) = get!(() -> _EdState(nothing, String[], Any[], nothing, nothing, Set{String}()), _ED_STATES, m)

_ed_len(v) = (v isa AbstractVector || v isa AbstractDict || v isa AbstractString) ? length(v) : 0

"""Each collection as the model holds it, and how long it is: what says the index is still right."""
function _ed_fingerprint(raw)
    fp = Vector{Any}(undef, 2 * length(COLLECTIONS))
    for (k, c) in enumerate(COLLECTIONS)
        v = get(raw, c, nothing)
        fp[2k-1] = v
        fp[2k] = _ed_len(v)
    end
    return fp
end

function _ed_same_fingerprint(old::Vector{Any}, raw)
    length(old) == 2 * length(COLLECTIONS) || return false
    for (k, c) in enumerate(COLLECTIONS)
        v = get(raw, c, nothing)
        (old[2k-1] === v && old[2k] == _ed_len(v)) || return false
    end
    return true
end

function _ed_rebuild_index!(m::Model, st::_EdState=_ed_state(m))
    idx = Dict{String,Tuple{String,Any}}()
    order = String[]
    raw = m.raw
    for c in COLLECTIONS
        for b in _py_iter(get(raw, c, nothing))
            b isa AbstractDict || continue
            q = qualified_name(b)
            if !haskey(idx, q)
                idx[q] = (c, b)
                push!(order, q)
            end
        end
    end
    st.index = idx
    st.order = order
    st.index_fp = _ed_fingerprint(raw)
    return idx
end

"""Every block by qualified name, the first of a name winning (`_idx`)."""
function _ed_idx(m::Model)
    st = _ed_state(m)
    (st.index === nothing || !_ed_same_fingerprint(st.index_fp, m.raw)) && _ed_rebuild_index!(m, st)
    return st.index::Dict{String,Tuple{String,Any}}
end

"""The index's names in the order the Python package walks them."""
function _ed_idx_order(m::Model)
    _ed_idx(m)
    return _ed_state(m).order
end

"""The block of a qualified name, `(collection, raw)`, or `nothing` (`_find`)."""
function _ed_find(m::Model, name)
    name === nothing && return nothing
    name isa AbstractString || return nothing
    hit = get(_ed_idx(m), name, nothing)
    if hit !== nothing && qualified_name(hit[2]) != name
        _ed_rebuild_index!(m)
        hit = get(_ed_idx(m), name, nothing)
    end
    return hit
end

"""Forgets what is known about the model's names and sub-systems (`_invalidate`)."""
function _ed_invalidate!(m::Model)
    st = _ed_state(m)
    st.index = nothing
    st.systems = nothing
    return
end

"""A block just appended, added to the index (`_register`)."""
function _ed_register!(m::Model, collection::String, raw::AbstractDict)
    st = _ed_state(m)
    if st.index !== nothing
        q = qualified_name(raw)
        if !haskey(st.index, q)
            st.index[q] = (collection, raw)
            push!(st.order, q)
        end
        st.index_fp = _ed_fingerprint(m.raw)
    end
    return
end

"""Whether a qualified name is a block, with `extra` names counted too (`_known`)."""
function _ed_known(m::Model, extra=())
    idx = _ed_idx(m)
    more = Set{String}(string(x) for x in extra)
    isempty(more) && return n -> haskey(idx, n)
    return n -> haskey(idx, n) || n in more
end

_ed_names(m::Model) = Set{String}(keys(_ed_idx(m)))

"""The kind of the block of a name, or `nothing`."""
function _ed_kind_of(m::Model, name)
    hit = _ed_find(m, name)
    return hit === nothing ? nothing : _BK_SINGULAR[hit[1]]
end

"""The model as the normalising code reads it, sharing the index."""
_N(m::Model) = _ModelNorm(m.raw, _ed_idx(m))

"""Every block's dictionary, in the collections' order (`_all_raw`)."""
function _ed_all_raw(m::Model)
    out = Any[]
    for c in COLLECTIONS
        for b in _py_iter(get(m.raw, c, nothing))
            b isa AbstractDict && push!(out, b)
        end
    end
    return out
end

"""Every sub-system, as a set: kept until `systems` or `transports` change, or an edit forgets it (`_system_set`)."""
function _ed_system_set(m::Model)
    st = _ed_state(m)
    raw = m.raw
    sy, tr = get(raw, "systems", nothing), get(raw, "transports", nothing)
    fp = (sy, _ed_len(sy), tr, _ed_len(tr))
    old = st.systems_fp
    same = old isa Tuple && old[1] === fp[1] && old[2] == fp[2] && old[3] === fp[3] && old[4] == fp[4]
    if st.systems === nothing || !same
        block_systems = String[system_of(b) for b in _ed_all_raw(m)]
        st.systems = system_paths(collect(Any, _py_iter(sy)), collect(Any, _py_iter(tr)), block_systems)
        st.systems_fp = fp
        st.system_lookup = Set{String}(st.systems)
    end
    return st.system_lookup
end

"""Every sub-system, as a dotted path, shallowest first."""
function _ed_systems(m::Model)
    _ed_system_set(m)
    return copy(_ed_state(m).systems::Vector{String})
end

_ed_forget_systems!(m::Model) = (_ed_state(m).systems = nothing; nothing)

# --- index lists, the derived ones included ---------------------------------------------------------

"""
`Compartments` or `Transfers`: one index per block, worked out from the model
when something reads its indices (`_BlockList`).
"""
mutable struct _EdBlockList <: AbstractDict{String,Any}
    d::JDict
    model::AbstractDict
    collection::String
end

function _EdBlockList(model::AbstractDict, name::String, collection::String, what::String)
    d = JDict("name" => name, "derived" => true, "auto" => collection,
              "note" => "One index per $what in the model — the $(what)s are the indices, so there is " *
                        "nothing to edit here. Add a $what and this list gains an index; rename one and the " *
                        "index follows.")
    return _EdBlockList(d, model, collection)
end

function _ebl_fill!(l::_EdBlockList)
    haskey(l.d, "indices") && return
    names = Any[]
    for b in _py_iter(get(l.model, l.collection, nothing))
        (b isa AbstractDict && !py_truthy(get(b, "hidden", nothing))) || continue
        sys = get(b, "system", nothing)
        n = py_truthy(sys) ? "$(_py_str(sys)).$(_py_str(get(b, "name", nothing)))" : get(b, "name", nothing)
        (n isa AbstractString && !isempty(n)) && push!(names, n)
    end
    l.d["indices"] = Any[JDict("name" => n, "enabled" => true) for n in names]
    return
end

Base.get(l::_EdBlockList, k, default) = (k == "indices" && _ebl_fill!(l); get(l.d, k, default))
Base.getindex(l::_EdBlockList, k) = (k == "indices" && _ebl_fill!(l); l.d[k])
Base.haskey(l::_EdBlockList, k) = k == "indices" || haskey(l.d, k)
Base.setindex!(l::_EdBlockList, v, k) = (l.d[k] = v; l)
Base.delete!(l::_EdBlockList, k) = (delete!(l.d, k); l)
Base.length(l::_EdBlockList) = (_ebl_fill!(l); length(l.d))
Base.iterate(l::_EdBlockList) = (_ebl_fill!(l); iterate(l.d))
Base.iterate(l::_EdBlockList, state) = iterate(l.d, state)

"""The lists the model stores."""
_ed_stored_lists(m::Model) = Any[l for l in _py_iter(get(m.raw, "index_lists", nothing)) if l isa AbstractDict]

"""Every list, the derived ones (Elements, Compartments, Transfers) included (`_lists`)."""
function _ed_lists(m::Model)
    out = derive_elements(_ed_stored_lists(m))
    for (name, collection, what) in ((COMPARTMENT_LIST, "compartments", "compartment"),
                                     (TRANSFER_LIST, "transfers", "transfer"))
        any(l -> jget(l, "name") == name, out) && continue
        any(b -> b isa AbstractDict && !py_truthy(get(b, "hidden", nothing)) &&
                 get(b, "name", nothing) isa AbstractString && !isempty(b["name"]),
            _py_iter(get(m.raw, collection, nothing))) || continue
        push!(out, _EdBlockList(m.raw, name, collection, what))
    end
    return out
end

_ed_list_any(m::Model, name) = find_list(_ed_lists(m), name)
_ed_stored_list(m::Model, name) = find_list(_ed_stored_lists(m), name)

"""Indices as objects: `"Cs-137"` becomes `{"name": "Cs-137", "enabled": true}` (each a copy)."""
function _ed_normalise_indices(indices)
    out = Any[]
    for i in _py_iter(indices)
        if i isa AbstractString
            push!(out, JDict("name" => String(i), "enabled" => true))
        else
            j = JDict(i)
            haskey(j, "enabled") || (j["enabled"] = true)
            push!(out, j)
        end
    end
    return out
end

"""The names of a list's indices."""
_ed_index_names(lst) = Any[index_name(i) for i in _py_iter(jget(lst, "indices"))]

"""The indices of a list that take part in the run."""
_ed_enabled_names(lst) = Any[index_name(i) for i in _py_iter(jget(lst, "indices"))
                             if !(i isa AbstractDict && get(i, "enabled", nothing) === false)]

# --- references written in equations ----------------------------------------------------------------

function _ed_tokens(src::AbstractString)
    try
        return tokenize(src)
    catch e
        e isa EquationSyntaxError || rethrow()
        return nothing
    end
end

"""
    rewrite_references(equation, system, known, replace, skip=nothing) -> String

Rewrites the block references in one equation: `replace(qname, system)`
answers with the text a reference to that block should now be written as, or
`nothing` to leave it. Everything between the names that move is copied as
it was typed; text that will not tokenize comes back unchanged.
"""
function rewrite_references(equation, system, known, replace, skip=nothing)
    src = equation === nothing ? "" : _py_str(equation)
    isempty(src) && return src
    tokens = _ed_tokens(src)
    tokens === nothing && return src
    chars = collect(src)
    io = IOBuffer()
    cursor = 0
    for tok in reference_tokens(tokens, skip)
        q = resolve_reference(tok.text, system, known)
        q === nothing && continue
        to = replace(q, system)
        (to === nothing || to == tok.text) && continue
        write(io, String(chars[cursor+1:tok.pos]))
        write(io, to)
        cursor = tok.pos + length(tok.text)
    end
    write(io, String(chars[cursor+1:end]))
    return String(take!(io))
end

"""
    rewrite_written_indices(equation, mapping) -> String

Rewrites index names written in brackets, and nothing else: `mapping(name)`
answers with the name it should become, or `nothing`. `K[Lake]` becomes
`K[Pond]`.
"""
function rewrite_written_indices(equation, mapping)
    src = equation === nothing ? "" : _py_str(equation)
    occursin('[', src) || return src
    tokens = _ed_tokens(src)
    tokens === nothing && return src
    chars = collect(src)
    io = IOBuffer()
    cursor = 0
    for tok in tokens
        tok.type === :index || continue
        was = String(strip(tok.text))
        to = mapping(was)
        (to === nothing || to == was) && continue
        write(io, String(chars[cursor+1:tok.pos]))
        write(io, replace(tok.text, was => to; count=1))
        cursor = tok.pos + length(tok.text)
    end
    write(io, String(chars[cursor+1:end]))
    return String(take!(io))
end

"""What is wrong with an equation's characters, or `nothing`: the tokenizer's check only."""
function check_syntax(equation)
    text = _py_or_text(equation)
    try
        tokenize(text)
    catch e
        e isa EquationSyntaxError || rethrow()
        return "$(e.message) at position $(e.position + 1)"
    end
    return nothing
end

"""Whether an equation, written as text, reads the simulation clock."""
function reads_clock(equation::AbstractString)
    tokens = _ed_tokens(equation)
    tokens === nothing && return false
    return any(t -> t.type === :ident && t.text == "time", tokens)
end

# --- an app laid out on the model (src/domain/apps.js) ------------------------------------------------

const _APP_WALK_DEPTH = 8
const _APP_UNSAFE_KEYS = ("__proto__", "constructor", "prototype")

function _app_pages(raw::AbstractDict)
    app = get(raw, "app", nothing)
    pages = app isa AbstractDict ? get(app, "pages", nothing) : nothing
    return pages isa AbstractVector ? pages : Any[]
end

function _app_walk(fn, components, depth::Int)
    (components isa AbstractVector && depth <= _APP_WALK_DEPTH) || return
    for c in components
        c isa AbstractDict || continue
        get(c, "target", nothing) isa AbstractDict && fn(c["target"])
        if get(c, "series", nothing) isa AbstractVector
            for s in c["series"]
                s isa AbstractDict && fn(s)
            end
        end
        _app_walk(fn, get(c, "components", nothing), depth + 1)
        if get(c, "tabs", nothing) isa AbstractVector
            for t in c["tabs"]
                t isa AbstractDict && _app_walk(fn, get(t, "components", nothing), depth + 1)
            end
        end
    end
    return
end

function _app_each_reference(fn, raw::AbstractDict)
    for page in _app_pages(raw)
        page isa AbstractDict && _app_walk(fn, get(page, "components", nothing), 0)
    end
    return
end

_truthy_text(x) = x isa AbstractString && !isempty(x)

function _app_follow_name(name::AbstractString, new_name_of)
    to = new_name_of(name)
    _truthy_text(to) && return to
    chars = collect(name)
    # A series a run names after a block -- a far-field path's `Rock held` and
    # `Rock.gravel1` -- follows the block at the front of it.
    for sep in (' ', '.')
        k = findlast(==(sep), chars)
        cut = k === nothing ? -1 : k - 1
        cut <= 0 && continue
        head = new_name_of(String(chars[1:cut]))
        _truthy_text(head) && return head * String(chars[cut+1:end])
    end
    return name
end

"""Follows a rename or a move of blocks into the app."""
function retarget_app_names!(raw::AbstractDict, new_name_of)
    _app_each_reference(raw) do ref
        b = get(ref, "block", nothing)
        (b isa AbstractString && !isempty(b)) && (ref["block"] = _app_follow_name(b, new_name_of))
    end
    return
end

"""Follows several index renames at once: list name => (old index => new)."""
function retarget_app_indexes!(raw::AbstractDict, moves)
    _app_each_reference(raw) do ref
        index = get(ref, "index", nothing)
        index isa AbstractDict || return
        for (list_name, mv) in moves
            was = get(index, list_name, nothing)
            (was isa AbstractString && haskey(mv, was)) && (index[list_name] = mv[was])
        end
    end
    return
end

"""Follows an index rename in every list named."""
rename_app_index!(raw::AbstractDict, lists, old, new) =
    retarget_app_indexes!(raw, [String(n) => Dict{String,Any}(old => new) for n in lists])

"""Follows a list rename: an index keyed by `old` is keyed by `new`."""
function rename_app_index_list!(raw::AbstractDict, old, new)
    new in _APP_UNSAFE_KEYS && return
    _app_each_reference(raw) do ref
        index = get(ref, "index", nothing)
        if index isa AbstractDict && haskey(index, old)
            v = pop!(index, old)
            index[new] = v
        end
    end
    return
end
