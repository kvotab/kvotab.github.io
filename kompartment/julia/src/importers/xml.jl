# A small XML reader, the one the Ecolego importer reads model.xml with: a
# port of the Python package's `kompartment/importers/_xml.py` (itself a port
# of the application's `src/io/xml.js`), so that a file is read the same way
# in all three. The same subset of XML -- elements, attributes, text, CDATA,
# comments, processing instructions, declarations skipped, the five predefined
# entities and numeric character references, and nothing else (no
# namespaces, no DTDs, no entity declarations) -- the same malformed files
# refused with the same message and position, and the same text for every
# element.
#
# It reads the document's bytes with a hand-written scanner. An element's
# text is every piece of text directly inside it, concatenated; it is kept as
# where its pieces lie in the document and only put together when asked for
# (`_eco_text`), since an importer reads the text of few of the elements a
# model.xml of tens of megabytes holds.

"""A document this reader cannot read. `position` is where it gave up,
counted in UTF-16 code units as the application counts, or `nothing`."""
struct EcoXMLError <: Exception
    message::String
    position::Union{Nothing,Int}
end
EcoXMLError(message::AbstractString) = EcoXMLError(String(message), nothing)
function Base.showerror(io::IO, e::EcoXMLError)
    print(io, e.position === nothing ? e.message : "$(e.message) (at character $(e.position))")
end
_eco_message(e::EcoXMLError) = e.position === nothing ? e.message : "$(e.message) (at character $(e.position))"

# Where the text pieces lie: the document and, per piece, its byte range, its
# kind (0: text with no `&`, 1: text to decode, 2: CDATA) and the next piece
# of the same element.
mutable struct _EcoXMLDoc
    src::String
    pstart::Vector{Int}
    pstop::Vector{Int}           # exclusive
    pkind::Vector{UInt8}
    pnext::Vector{Int}
end

"""One element: `name`, `attrs` (in the order written; a repeated attribute
keeps its first place and its last value), `children`, and its text,
read with [`_eco_text`](@ref)."""
mutable struct EcoXMLNode
    name::String
    attrs::Vector{Pair{String,String}}
    children::Vector{EcoXMLNode}
    doc::_EcoXMLDoc
    tfirst::Int                  # the first text piece (0: none)
    tlast::Int
    self_closing::Bool
end

const _ECO_NO_ATTRS = Pair{String,String}[]
const _ECO_NO_CHILDREN = EcoXMLNode[]

Base.show(io::IO, n::EcoXMLNode) = print(io, "<EcoXMLNode $(n.name) $(length(n.children)) children>")

"""The element's text: every piece of text directly inside it, concatenated,
entities decoded (CDATA as written)."""
function _eco_text(n::EcoXMLNode)
    k = n.tfirst
    k == 0 && return ""
    d = n.doc
    if k == n.tlast
        return _eco_piece(d, k)
    end
    io = IOBuffer()
    while k != 0
        write(io, _eco_piece(d, k))
        k = d.pnext[k]
    end
    return String(take!(io))
end

function _eco_piece(d::_EcoXMLDoc, k::Int)
    a, b = d.pstart[k], d.pstop[k]
    s = String(view(codeunits(d.src), a:b-1))
    return d.pkind[k] == 0x01 ? _eco_decode_entities(s) : s
end

"""The attribute `key`, or `default`."""
function _eco_attr(n::EcoXMLNode, key::AbstractString, default=nothing)
    for p in n.attrs
        p.first == key && return p.second
    end
    return default
end
_eco_hasattr(n::EcoXMLNode, key::AbstractString) = any(p -> p.first == key, n.attrs)

# --- entities -------------------------------------------------------------------------

const _ECO_ENTITIES = Dict{String,String}("amp" => "&", "lt" => "<", "gt" => ">", "quot" => "\"", "apos" => "'")

@inline _eco_is_hex(b::UInt8) = (0x30 <= b <= 0x39) || (0x41 <= b <= 0x46) || (0x61 <= b <= 0x66)
@inline _eco_is_alpha(b::UInt8) = (0x41 <= b <= 0x5a) || (0x61 <= b <= 0x7a)

"""The five predefined entities and numeric character references decoded;
anything else (`&nbsp;`, `&#1114112;`) left as written. The rule is the
regular expression `&(#x?[0-9a-fA-F]+|[a-zA-Z]+);`, a reference read by
`parseInt`: the longest run of digits at its start."""
function _eco_decode_entities(text::String)
    cu = codeunits(text)
    n = length(cu)
    amp = findfirst(==(UInt8('&')), cu)
    amp === nothing && return text
    io = IOBuffer(sizehint=n)
    i = 1                         # what has been copied up to
    j = amp
    while j !== nothing && j <= n
        # Try to match at j.
        k = j + 1
        stop = 0                  # the index of the `;` when matched
        if k <= n && cu[k] == UInt8('#')
            k += 1
            if k <= n && cu[k] == UInt8('x')
                m = k + 1
                while m <= n && _eco_is_hex(cu[m])
                    m += 1
                end
                (m > k + 1 && m <= n && cu[m] == UInt8(';')) && (stop = m)
            else
                m = k
                while m <= n && _eco_is_hex(cu[m])
                    m += 1
                end
                (m > k && m <= n && cu[m] == UInt8(';')) && (stop = m)
            end
        else
            m = k
            while m <= n && _eco_is_alpha(cu[m])
                m += 1
            end
            (m > k && m <= n && cu[m] == UInt8(';')) && (stop = m)
        end
        if stop == 0
            j = findnext(==(UInt8('&')), cu, j + 1)
            continue
        end
        whole = view(cu, j:stop)
        body = view(cu, j+1:stop-1)
        replacement = _eco_entity(body)
        write(io, view(cu, i:j-1))
        if replacement === nothing
            write(io, whole)
        else
            write(io, replacement)
        end
        i = stop + 1
        j = findnext(==(UInt8('&')), cu, i)
    end
    write(io, view(cu, i:n))
    return String(take!(io))
end

# What one matched reference stands for, or `nothing` to leave it as written.
function _eco_entity(body)
    if body[1] == UInt8('#')
        hex = length(body) >= 2 && (body[2] == UInt8('x') || body[2] == UInt8('X'))
        digits = hex ? view(body, 3:length(body)) : view(body, 2:length(body))
        base = hex ? 16 : 10
        code = 0
        count = 0
        big = false
        for b in digits
            v = (0x30 <= b <= 0x39) ? Int(b - 0x30) : (base == 16 && 0x61 <= b <= 0x66) ? Int(b - 0x61 + 10) :
                (base == 16 && 0x41 <= b <= 0x46) ? Int(b - 0x41 + 10) : -1
            v < 0 && break
            count += 1
            big || (code = code * base + v)
            code > 0x10ffff && (big = true)
        end
        count == 0 && return nothing
        (big || code > 0x10ffff) && return nothing
        (0xd800 <= code <= 0xdfff) && return nothing
        return string(Char(code))
    end
    return get(_ECO_ENTITIES, String(Vector{UInt8}(body)), nothing)
end

# --- the scanner -------------------------------------------------------------------------

# Names (of elements and attributes) are few and repeat: each is made once.
struct _EcoNames
    table::Dict{String,String}
end
_EcoNames() = _EcoNames(Dict{String,String}())
@inline function _eco_intern(t::_EcoNames, src::String, a::Int, b::Int)
    # b is exclusive; a < b.
    sub = SubString(src, a, prevind(src, b))
    s = get(t.table, sub, nothing)
    s === nothing || return s
    s = String(sub)
    t.table[s] = s
    return s
end

@inline function _eco_memchr(src::String, byte::UInt8, from::Int)
    n = ncodeunits(src)
    from > n && return 0
    p = GC.@preserve src ccall(:memchr, Ptr{UInt8}, (Ptr{UInt8}, Cint, Csize_t),
                                pointer(src, from), byte, n - from + 1)
    return p == C_NULL ? 0 : Int(p - pointer(src)) + 1
end

@inline function _eco_starts(cu, i::Int, n::Int, lit::NTuple{N,UInt8}) where {N}
    i + N - 1 <= n || return false
    @inbounds for k in 1:N
        cu[i+k-1] == lit[k] || return false
    end
    return true
end

function _eco_findstr(src::String, needle::String, from::Int)
    r = findnext(needle, src, from)
    return r === nothing ? 0 : first(r)
end

# Where a reader gives up: the message, and the position in UTF-16 code units.
@noinline _eco_xml_fail(src::String, message::String, at::Int) =
    throw(EcoXMLError(message, _eco_utf16_pos(src, at)))

# A name, from byte `i`: everything up to JavaScript's white space, `/`, `>`
# or `=`. Returns the name and where it ends.
@inline function _eco_read_name(src::String, cu, i::Int, n::Int, names::_EcoNames)
    start = i
    @inbounds while i <= n
        b = cu[i]
        if b < 0x80
            (b == 0x2f || b == 0x3e || b == 0x3d || b == 0x20 || (0x09 <= b <= 0x0d)) && break
        else
            _eco_js_space_bytes(cu, i, n) > 0 && break
        end
        i += 1
    end
    i == start && _eco_xml_fail(src, "Expected a name", i)
    return _eco_intern(names, src, start, i), i
end

# XML's own white space, skipped between attributes.
@inline function _eco_skip_space(cu, i::Int, n::Int)
    @inbounds while i <= n
        b = cu[i]
        (b == 0x20 || b == 0x09 || b == 0x0a || b == 0x0d) || break
        i += 1
    end
    return i
end

# One piece of text for the innermost open element; outside every element,
# text is not anyone's.
@inline function _eco_add_piece!(doc::_EcoXMLDoc, stack::Vector{EcoXMLNode}, a::Int, b::Int, kind::UInt8)
    (isempty(stack) || a >= b) && return
    node = @inbounds stack[end]
    push!(doc.pstart, a)
    push!(doc.pstop, b)
    push!(doc.pkind, kind)
    push!(doc.pnext, 0)
    k = length(doc.pstart)
    if node.tfirst == 0
        node.tfirst = k
    else
        @inbounds doc.pnext[node.tlast] = k
    end
    node.tlast = k
    return
end

"""
    parse_eco_xml(src) -> EcoXMLNode

Reads a document; returns its root element. Throws [`EcoXMLError`](@ref) for
what it cannot read, with the application's message.
"""
function parse_eco_xml(src::String)
    cu = codeunits(src)
    n = length(cu)
    doc = _EcoXMLDoc(src, Int[], Int[], UInt8[], Int[])
    names = _EcoNames()
    stack = EcoXMLNode[]
    root = nothing
    i = 1

    while i <= n
        lt = _eco_memchr(src, UInt8('<'), i)
        if lt == 0
            isempty(stack) || _eco_add_piece!(doc, stack, i, n + 1, _eco_memchr_range(src, UInt8('&'), i, n + 1) ? 0x01 : 0x00)
            break
        end
        if lt > i && !isempty(stack)
            _eco_add_piece!(doc, stack, i, lt, _eco_memchr_range(src, UInt8('&'), i, lt) ? 0x01 : 0x00)
        end
        i = lt

        if _eco_starts(cu, i, n, (0x3c, 0x21, 0x2d, 0x2d))               # <!--
            e = _eco_findstr(src, "-->", i + 4)
            e == 0 && _eco_xml_fail(src, "Unterminated comment", i)
            i = e + 3
            continue
        end
        if _eco_starts(cu, i, n, (0x3c, 0x21, 0x5b, 0x43, 0x44, 0x41, 0x54, 0x41, 0x5b))  # <![CDATA[
            e = _eco_findstr(src, "]]>", i + 9)
            e == 0 && _eco_xml_fail(src, "Unterminated CDATA section", i)
            _eco_add_piece!(doc, stack, i + 9, e, 0x02)
            i = e + 3
            continue
        end
        if _eco_starts(cu, i, n, (0x3c, 0x3f))                           # <?
            e = _eco_findstr(src, "?>", i + 2)
            e == 0 && _eco_xml_fail(src, "Unterminated processing instruction", i)
            i = e + 2
            continue
        end
        if _eco_starts(cu, i, n, (0x3c, 0x21))                           # <!
            e = _eco_memchr(src, UInt8('>'), i + 2)
            e == 0 && _eco_xml_fail(src, "Unterminated declaration", i)
            i = e + 1
            continue
        end

        if _eco_starts(cu, i, n, (0x3c, 0x2f))                           # </
            name, i = _eco_read_name(src, cu, i + 2, n, names)
            i = _eco_skip_space(cu, i, n)
            (i > n || @inbounds(cu[i]) != UInt8('>')) && _eco_xml_fail(src, "Expected '>' closing </$name", i)
            i += 1
            isempty(stack) && _eco_xml_fail(src, "Unexpected closing tag </$name>", i)
            open_ = pop!(stack)
            open_.name == name || _eco_xml_fail(src, "Closing tag </$name> does not match <$(open_.name)>", i)
            continue
        end

        name, i = _eco_read_name(src, cu, i + 1, n, names)
        attrs = _ECO_NO_ATTRS
        self_closing = false
        while true
            i = _eco_skip_space(cu, i, n)
            i > n && _eco_xml_fail(src, "Unterminated tag", i)
            b = @inbounds cu[i]
            if b == UInt8('>')
                i += 1
                break
            end
            if b == UInt8('/') && i + 1 <= n && @inbounds(cu[i+1]) == UInt8('>')
                i += 2
                self_closing = true
                break
            end
            attr, i = _eco_read_name(src, cu, i, n, names)
            i = _eco_skip_space(cu, i, n)
            (i > n || @inbounds(cu[i]) != UInt8('=')) && _eco_xml_fail(src, "Expected '=' after attribute '$attr'", i)
            i = _eco_skip_space(cu, i + 1, n)
            quote_ = i <= n ? @inbounds(cu[i]) : 0x00
            (quote_ == UInt8('"') || quote_ == UInt8('\'')) ||
                _eco_xml_fail(src, "Expected a quoted value for attribute '$attr'", i)
            i += 1
            e = _eco_memchr(src, quote_, i)
            e == 0 && _eco_xml_fail(src, "Unterminated value for attribute '$attr'", i)
            raw = String(view(cu, i:e-1))
            value = _eco_memchr_range(src, UInt8('&'), i, e) ? _eco_decode_entities(raw) : raw
            if attrs === _ECO_NO_ATTRS
                attrs = Pair{String,String}[attr => value]
            else
                at = 0
                for k in eachindex(attrs)
                    if attrs[k].first == attr
                        at = k
                        break
                    end
                end
                at == 0 ? push!(attrs, attr => value) : (attrs[at] = attr => value)
            end
            i = e + 1
        end
        node = EcoXMLNode(name, attrs, _ECO_NO_CHILDREN, doc, 0, 0, self_closing)

        if !isempty(stack)
            parent = @inbounds stack[end]
            if parent.children === _ECO_NO_CHILDREN
                parent.children = EcoXMLNode[node]
            else
                push!(parent.children, node)
            end
        elseif root !== nothing
            _eco_xml_fail(src, "More than one root element", i)
        else
            root = node
        end
        self_closing || push!(stack, node)
    end

    isempty(stack) || throw(EcoXMLError("Unclosed element <$(stack[end].name)>"))
    root === nothing && throw(EcoXMLError("The document has no elements"))
    return root::EcoXMLNode
end

function _eco_memchr_range(src::String, byte::UInt8, a::Int, b::Int)
    # whether `byte` is in bytes a..b-1
    b <= a && return false
    p = GC.@preserve src ccall(:memchr, Ptr{UInt8}, (Ptr{UInt8}, Cint, Csize_t), pointer(src, a), byte, b - a)
    return p != C_NULL
end

# --- convenience accessors ------------------------------------------------------------

"""The first direct child called `name`, or `nothing`."""
function _eco_child(node::Union{Nothing,EcoXMLNode}, name::AbstractString)
    node === nothing && return nothing
    for c in node.children
        c.name == name && return c
    end
    return nothing
end

"""Every direct child called `name`."""
function _eco_children(node::Union{Nothing,EcoXMLNode}, name::AbstractString)
    node === nothing && return EcoXMLNode[]
    return EcoXMLNode[c for c in node.children if c.name == name]
end

"""The text of the first child called `name`, trimmed, or `fallback` when
there is no such child or its text is blank."""
function _eco_child_text(node::Union{Nothing,EcoXMLNode}, name::AbstractString, fallback=nothing)
    c = _eco_child(node, name)
    c === nothing && return fallback
    t = _eco_trimmed_text(c)
    return t == "" ? fallback : t
end

# `_eco_js_trim(_eco_text(n))`, copying the text once when it is one piece.
function _eco_trimmed_text(n::EcoXMLNode)
    k = n.tfirst
    k == 0 && return ""
    d = n.doc
    if k == n.tlast && d.pkind[k] != 0x01
        cu = codeunits(d.src)
        a, b = _eco_js_trim_range(cu, d.pstart[k], d.pstop[k] - 1)
        return b < a ? "" : String(view(cu, a:b))
    end
    return _eco_js_trim(_eco_text(n))
end

"""A child's text as a finite number, or `fallback`."""
function _eco_child_number(node::Union{Nothing,EcoXMLNode}, name::AbstractString, fallback=nothing)
    t = _eco_child_text(node, name)
    t === nothing && return fallback
    v = _eco_to_number(t)
    return isfinite(v) ? v : fallback
end

"""Whether a child's text is `true` (in any case); `fallback` when there is none."""
function _eco_child_bool(node::Union{Nothing,EcoXMLNode}, name::AbstractString, fallback=nothing)
    t = _eco_child_text(node, name)
    t === nothing && return fallback
    return _eco_py_lower(t) == "true"
end

"""Every element under `node`, `node` first, depth first in document order."""
function _eco_walk(f, node::EcoXMLNode)
    stack = EcoXMLNode[node]
    while !isempty(stack)
        el = pop!(stack)
        f(el) === :stop && return :stop
        ch = el.children
        for k in length(ch):-1:1
            push!(stack, ch[k])
        end
    end
    return nothing
end

"""The first element anywhere under `node` (`node` included) called `name`,
or `nothing`."""
function _eco_find(node::EcoXMLNode, name::AbstractString)
    found = nothing
    _eco_walk(node) do el
        if el.name == name
            found = el
            return :stop
        end
        return nothing
    end
    return found
end
