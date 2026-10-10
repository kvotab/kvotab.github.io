# Writing HDF5 as Kompartment writes it, byte for byte.
#
# A port of the Python package's `kompartment/io/hdf5.py`, itself a port of
# the application's `src/io/hdf5.js`: the same narrow writer -- groups, arrays
# of doubles, floats, integers and strings, attributes on both -- laying out
# the same tree in the same bytes, so a file written from Julia is the file the
# application (and the Python package) would have written:
#
#     root = h5group(JDict("model" => "Two boxes"))
#     h5put(root, ["time"], h5dataset([0.0, 1.0, 2.0], H5F64, JDict("unit" => "year")))
#     h5put(root, ["IndexLists", "Radionuclides"], h5dataset(["Cs-137", "H-3"], H5STR))
#     h5put(root, ["Soil", "Cs-137"], h5dataset([1.0, 0.9, 0.8]))
#     bytes = write_hdf5(root)            # Vector{UInt8}
#
# **Which HDF5.** Version 2 object headers with a group's links held in the
# header itself ("compact" storage), which needs no B-tree: a link is a
# message, and a group of four hundred children is four hundred messages.
# Every version 2 structure ends in a Jenkins lookup3 checksum (`lookup3`).
# libhdf5 has read and written these since 1.8; h5py, h5ls, h5dump and the
# result browser's h5wasm open them.
#
# **Strings** are variable-length UTF-8 in a global heap collection, pooled:
# `TRUE` is in the file once however many datasets say it. A boolean attribute
# is written as the string `TRUE` or `FALSE`, which is what Ecolego's own files
# hold.
#
# **The tree** is made of `h5group` and `h5dataset` nodes put together with
# `h5put`. Children are written in the order they were put, which is what keeps
# a result file's nuclides in the model's order. Attributes are written in the
# order JavaScript lists an object's keys: keys that are array indices (`"0"`,
# `"17"`) first, in numeric order, then the rest in the order they were set --
# which is insertion order for an `H5Attrs` (what `h5group` and `h5dataset`
# make when given none) or any ordered dictionary (`JDict`), or a vector of
# pairs; a plain `Dict` has no order to keep.
#
# Values are converted as the application converts them: a value that is not a
# number is turned into one as JavaScript's `Number()` would (`js_to_number`:
# `nothing` is 0, a numeric string its number, anything else NaN), a float32
# dataset rounds to nearest, an int32 dataset wraps as JavaScript's
# `Int32Array` does (after the value has become a double, as every JavaScript
# number is), and text is written as `String()` writes it (`js_string`). A
# matrix (or any array of two or more dimensions) is written row by row, C
# order, as numpy and HDF5 lay it out, and gives its size as `dims` when no
# `dims` is given.
#
# References: the HDF5 File Format Specification version 3.0, sections III.A
# (superblock version 2), IV.A (object headers version 2 and their messages)
# and III.E (global heap). The checksum is `H5_checksum_lookup3` from
# `H5checksum.c`.

"""
    HDF5Error(msg)

A tree that cannot be written: a name with a slash in it, two things at one
path, a shape that does not match its values, a datatype this writer does not
know.
"""
struct HDF5Error <: Exception
    msg::String
end
Base.showerror(io::IO, e::HDF5Error) = print(io, "HDF5Error: ", e.msg)

# --- the datatypes this writer knows ----------------------------------------------------

"""
    H5Datatype

One of the datatypes the writer knows: `H5F64`, `H5F32`, `H5I32` or `H5STR`.
`kind` is `:float`, `:int` or `:vlenstr` and `size` the bytes one value takes;
a float also carries where its exponent and mantissa sit (`exp_loc`, `exp`,
`mant`) and its exponent `bias`, an integer whether it is `signed`.
"""
struct H5Datatype
    kind::Symbol
    size::Int
    exp::Int
    exp_loc::Int
    mant::Int
    bias::Int
    signed::Bool
end
H5Datatype(kind::Symbol, size::Integer; exp::Integer=0, exp_loc::Integer=0, mant::Integer=0, bias::Integer=0,
           signed::Bool=false) = H5Datatype(kind, size, exp, exp_loc, mant, bias, signed)

"""IEEE 754 doubles, little-endian: what a result series is."""
const H5F64 = H5Datatype(:float, 8; exp=11, exp_loc=52, mant=52, bias=1023)
"""IEEE 754 singles: a series that does not need the digits (a probabilistic result's realisations)."""
const H5F32 = H5Datatype(:float, 4; exp=8, exp_loc=23, mant=23, bias=127)
"""A signed 32-bit integer: counts."""
const H5I32 = H5Datatype(:int, 4; signed=true)
"""A variable-length UTF-8 string, held in the global heap."""
const H5STR = H5Datatype(:vlenstr, 16)

# --- the tree ---------------------------------------------------------------------------

"""
    H5Attrs()
    H5Attrs("unit" => "Bq", "time_dependent" => true)

A node's attributes: an ordered dictionary of name => value (an
`AbstractDict{String,Any}`), in the order the names were first set -- setting
one again keeps its place, as a JavaScript object or a Python dict does. Made
for many small ones (a result file has hundreds of thousands): two vectors and
a linear search, no hash table. A key that is not a string is stored as
`js_string` writes it, which is what the file would call it anyway.
"""
mutable struct H5Attrs <: AbstractDict{String,Any}
    keys::Vector{String}
    vals::Vector{Any}
    shared::Bool            # `keys` is another's too, and is copied before it changes
    H5Attrs() = new(String[], Any[], false)
    H5Attrs(keys::Vector{String}, vals::Vector{Any}, shared::Bool) = new(keys, vals, shared)
end
function H5Attrs(kv)
    a = H5Attrs()
    for (k, v) in kv
        a[k] = v
    end
    return a
end
H5Attrs(kv::Pair...) = H5Attrs(kv)

# The keys made the attributes' own before they change.
@inline function _h5_own_keys!(a::H5Attrs)
    if a.shared
        a.keys = copy(a.keys)
        a.shared = false
    end
    return a
end

_h5_key(k::String) = k
_h5_key(k::AbstractString) = String(k)
_h5_key(k) = js_string(k)

function _h5_slot(a::H5Attrs, k::AbstractString)
    ks = a.keys
    @inbounds for i in eachindex(ks)
        ks[i] == k && return i
    end
    return 0
end
_h5_slot(a::H5Attrs, k) = _h5_slot(a, _h5_key(k))

Base.length(a::H5Attrs) = length(a.keys)
Base.isempty(a::H5Attrs) = isempty(a.keys)
function Base.iterate(a::H5Attrs, i::Int=1)
    i > length(a.keys) && return nothing
    @inbounds return (Pair{String,Any}(a.keys[i], a.vals[i]), i + 1)
end
Base.haskey(a::H5Attrs, k) = _h5_slot(a, k) != 0
Base.get(a::H5Attrs, k, default) = (i = _h5_slot(a, k); i == 0 ? default : @inbounds a.vals[i])
Base.get(f::Base.Callable, a::H5Attrs, k) = (i = _h5_slot(a, k); i == 0 ? f() : @inbounds a.vals[i])
function Base.getindex(a::H5Attrs, k)
    i = _h5_slot(a, k)
    i == 0 && throw(KeyError(k))
    @inbounds return a.vals[i]
end
function Base.setindex!(a::H5Attrs, v, k)
    key = _h5_key(k)
    i = _h5_slot(a, key)
    if i == 0
        _h5_own_keys!(a)
        push!(a.keys, key)
        push!(a.vals, v)
    else
        @inbounds a.vals[i] = v
    end
    return a
end
function Base.delete!(a::H5Attrs, k)
    i = _h5_slot(a, k)
    if i != 0
        _h5_own_keys!(a)
        deleteat!(a.keys, i)
        deleteat!(a.vals, i)
    end
    return a
end
Base.empty!(a::H5Attrs) = (a.keys = String[]; a.shared = false; empty!(a.vals); a)
Base.copy(a::H5Attrs) = (b = H5Attrs(); append!(b.keys, a.keys); append!(b.vals, a.vals); b)
Base.empty(::H5Attrs) = H5Attrs()
Base.empty(::H5Attrs, ::Type{String}, ::Type{Any}) = H5Attrs()

"""A node of an HDF5 tree: an `H5Group` or an `H5Dataset`."""
abstract type H5Node end

"""
    H5Group

A group: `attrs` (a dictionary of attribute values) and `children` (name to
`H5Group` or `H5Dataset`, kept -- and written -- in the order the children
were put).
"""
mutable struct H5Group <: H5Node
    attrs::Any
    children::OrderedDict{String,H5Node}
end

"""
    H5Dataset

A dataset: `data` (its values), `dt` (their `H5Datatype`), `attrs` and, for a
matrix, `dims` (its dimensions; `nothing` for a plain list).
"""
mutable struct H5Dataset <: H5Node
    data::Any
    dt::H5Datatype
    attrs::Any
    dims::Union{Nothing,Vector{Any}}
end

function Base.show(io::IO, g::H5Group)
    print(io, "H5Group(", g.attrs === nothing ? 0 : length(g.attrs), " attributes, children=")
    show(io, collect(keys(g.children)))
    print(io, ")")
end
function Base.show(io::IO, d::H5Dataset)
    print(io, "H5Dataset(", _h5_length(d.data), " values, ", d.dt.kind, d.dt.size * 8, ", dims=")
    show(io, d.dims)
    print(io, ")")
end

"""
    h5group(attrs=nothing) -> H5Group

A group with the attributes given (an `H5Attrs` or any ordered dictionary,
held rather than copied; `nothing` is none yet: an empty `H5Attrs`). Children
are kept in insertion order and written in it: a compact group is searched
linearly, so any order reads, and insertion order is the one that puts a
result file's nuclides in the order the model lists them.
"""
h5group(attrs=nothing) = H5Group(attrs === nothing ? H5Attrs() : attrs, OrderedDict{String,H5Node}())

# An array of two or more dimensions as HDF5 (and numpy) store it: row by row.
_h5_c_order(v::AbstractArray) = _csv_c_order(v)

_h5_is_listlike(data) = data isa Union{AbstractArray,AbstractString,Tuple,AbstractDict}

"""
    h5dataset(data, dt=H5F64, attrs=nothing, dims=nothing) -> H5Dataset

A dataset: values, their type and attributes.

`data` is a vector of numbers, or of strings for `H5STR`. `dims` is for the
one case that is not a list: a probabilistic result, one row per output time
and one column per realisation. The values are still given flat -- HDF5 stores
them flat, the last dimension varying fastest -- so with
`dims=[times, realisations]`, `data[t * n + r + 1]` is realisation `r` at time
`t` (both counted from 0). `dims=[]` writes a single value as a scalar.

A matrix (any array of two or more dimensions) is taken row by row, with its
size as `dims` unless `dims` is given. An iterator is collected. A bare number
is not a list and gives an empty dataset, as it does in the application.

Throws `HDF5Error` when `dims` does not multiply out to the number of values.
"""
function h5dataset(data, dt::H5Datatype=H5F64, attrs=nothing, dims=nothing)
    if data isa AbstractArray && ndims(data) >= 2
        if dims === nothing
            dims = Any[size(data)...]
        end
        data = _h5_c_order(data)
    elseif !(_h5_is_listlike(data) || data isa Union{Number,Nothing,Symbol,AbstractChar}) &&
           Base.isiterable(typeof(data))
        data = collect(data)
    end
    if dims !== nothing
        dims = Any[d for d in dims]
        want = 1.0
        for d in dims
            want *= js_to_number(d)
        end
        got = _h5_length(data)
        if want != got
            shape = join((d === nothing ? "" : js_string(d) for d in dims), "×")
            throw(HDF5Error("A $(shape) dataset holds $(js_string(want)) values and was given $(got)"))
        end
    end
    return H5Dataset(data, dt, attrs === nothing ? H5Attrs() : attrs, dims)
end

"""
    h5put(root, path, node) -> node

Puts `node` at `path` in `root`, making the groups on the way. `path` is a
vector of names, `["Soil", "Cs-137"]`; empty names are skipped. A name with a
slash in it cannot be a link name -- that is the one character HDF5 reserves
-- so it is refused, and so is a second thing at one path, or anything put
inside a dataset: two results with one name is a bug in whoever built the
tree (`HDF5Error`).
"""
function h5put(root::H5Group, path, node::H5Node)
    path isa AbstractString && throw(ArgumentError("a path is a list of names, not one string"))
    if path isa Vector{String} && !any(isempty, path)
        parts = path
    else
        parts = String[]
        for p in path
            p isa AbstractString || throw(ArgumentError("a path is a list of names; $(repr(p)) is not one"))
            isempty(p) || push!(parts, String(p))
        end
    end
    isempty(parts) && throw(HDF5Error("Nothing can be put at the root itself"))
    at = root
    for k in 1:length(parts)-1
        part = parts[k]
        occursin('/', part) && throw(HDF5Error("'$(part)' cannot be a name: it has a slash in it"))
        nxt = get(at.children, part, nothing)
        if nxt === nothing
            nxt = h5group()
            at.children[part] = nxt
        elseif !(nxt isa H5Group)
            throw(HDF5Error("'$(part)' is a dataset, so nothing can be put inside it"))
        end
        at = nxt
    end
    last = parts[end]
    occursin('/', last) && throw(HDF5Error("'$(last)' cannot be a name: it has a slash in it"))
    kids = at.children
    before = length(kids)
    get!(kids, last, node)                              # one search, whether or not it is there
    length(kids) == before && throw(HDF5Error("There is already something at $(join(parts, '/'))"))
    return node
end

# --- the checksum -----------------------------------------------------------------------

@inline _h5_rot(x::UInt32, k::Int) = (x << k) | (x >> (32 - k))

@inline function _h5_word(b::Vector{UInt8}, i::Int)
    @inbounds return UInt32(b[i]) | (UInt32(b[i+1]) << 8) | (UInt32(b[i+2]) << 16) | (UInt32(b[i+3]) << 24)
end

@inline function _h5_partial(b::Vector{UInt8}, i::Int, m::Int)
    w = UInt32(0)
    @inbounds for t in 0:m-1
        w |= UInt32(b[i+t]) << (8t)
    end
    return w
end

# lookup3 over `n` bytes of `b` from the 0-based offset `off`, all of them in `b`.
function _h5_lookup3(b::Vector{UInt8}, off::Int, n::Int)
    a = bb = c = 0xdeadbeef + (n % UInt32)
    i = off + 1
    left = n
    # Twelve bytes at a time while more than twelve are left: the last one to
    # twelve go through the tail below.
    while left > 12
        a += _h5_word(b, i)
        bb += _h5_word(b, i + 4)
        c += _h5_word(b, i + 8)
        a -= c; a ⊻= _h5_rot(c, 4); c += bb
        bb -= a; bb ⊻= _h5_rot(a, 6); a += c
        c -= bb; c ⊻= _h5_rot(bb, 8); bb += a
        a -= c; a ⊻= _h5_rot(c, 16); c += bb
        bb -= a; bb ⊻= _h5_rot(a, 19); a += c
        c -= bb; c ⊻= _h5_rot(bb, 4); bb += a
        left -= 12
        i += 12
    end
    left == 0 && return c
    # The tail, as the C's fall-through switch adds it.
    left >= 9 && (c += _h5_partial(b, i + 8, left - 8))
    left >= 5 && (bb += _h5_partial(b, i + 4, min(left - 4, 4)))
    a += _h5_partial(b, i, min(left, 4))
    c ⊻= bb; c -= _h5_rot(bb, 14)
    a ⊻= c; a -= _h5_rot(c, 11)
    bb ⊻= a; bb -= _h5_rot(a, 25)
    c ⊻= bb; c -= _h5_rot(bb, 16)
    a ⊻= c; a -= _h5_rot(c, 4)
    bb ⊻= a; bb -= _h5_rot(a, 14)
    c ⊻= bb; c -= _h5_rot(bb, 24)
    return c
end

"""
    lookup3(data, start=1, len=length(data) - start + 1) -> UInt32

Jenkins' lookup3 over `len` bytes of `data` from the 1-based index `start`, as
`H5_checksum_lookup3` calls it, with an initial value of zero. Every version 2
structure ends with four bytes of this over everything before it, and a
reader that does not like the answer will not open the file. Bytes past the
end of `data` read as zeros, as in the JavaScript.
"""
function lookup3(data::AbstractVector{UInt8}, start::Integer=1, len::Integer=length(data) - start + 1)
    len = Int(len)
    start = Int(start)
    if data isa Vector{UInt8} && start >= 1 && start + len - 1 <= length(data)
        return _h5_lookup3(data, start - 1, len)
    end
    chunk = zeros(UInt8, len)
    have = clamp(length(data) - start + 1, 0, len)
    have > 0 && copyto!(chunk, 1, data, firstindex(data) + start - 1, have)
    return _h5_lookup3(chunk, 0, len)
end
lookup3(data::AbstractString, args...) = lookup3(Vector{UInt8}(codeunits(data)), args...)

# --- JavaScript's view of the values ----------------------------------------------------

"""
`TextEncoder`: UTF-8, with a lone surrogate (or a byte that is not UTF-8 at
all) written as U+FFFD rather than refused, and a surrogate pair written as
the character it makes. A valid string is returned as it is.
"""
function _h5_utf8(s::String)
    isvalid(String, s) && return s
    io = IOBuffer()
    pending = UInt32(0)                 # a high surrogate waiting for its low half
    for c in s
        u = Base.ismalformed(c) ? typemax(UInt32) : UInt32(codepoint(c))
        if pending != 0
            if 0xdc00 <= u <= 0xdfff
                print(io, Char(0x10000 + ((pending - 0xd800) << 10) + (u - 0xdc00)))
                pending = 0
                continue
            end
            print(io, '�')
            pending = 0
        end
        if 0xd800 <= u <= 0xdbff
            pending = u
        elseif isvalid(c)
            print(io, c)
        else
            print(io, '�')
        end
    end
    pending != 0 && print(io, '�')
    return String(take!(io))
end
_h5_utf8(s::AbstractString) = _h5_utf8(String(s))

"""Whether a key is a JavaScript array index: `0` or digits without a leading zero, below 2^32 - 1."""
function _h5_is_array_index(k::AbstractString)
    n = ncodeunits(k)
    (n == 0 || n > 10) && return false
    c1 = codeunit(k, 1)
    (UInt8('0') <= c1 <= UInt8('9')) || return false
    c1 == UInt8('0') && return n == 1
    v = 0
    for i in 1:n
        c = codeunit(k, i)
        (UInt8('0') <= c <= UInt8('9')) || return false
        v = 10v + Int(c - UInt8('0'))
    end
    return v < 0xFFFFFFFF
end

_h5_pairs(attrs::AbstractDict) = attrs
_h5_pairs(attrs::AbstractVector{<:Pair}) = attrs
_h5_pairs(attrs::NamedTuple) = pairs(attrs)
_h5_pairs(attrs) = throw(ArgumentError("attributes are a dictionary (or a vector of pairs), not a $(typeof(attrs))"))

# `Object.entries(attrs)` into `buf`, for attributes that are not plainly in
# order already: array-index keys first, in numeric order, then every other key
# in the order it was first set (a key seen twice keeps its first place and its
# last value).
function _h5_entries!(buf::Vector{Pair{String,Any}}, attrs)
    empty!(buf)
    attrs === nothing && return buf
    items = OrderedDict{String,Any}()
    for (k, v) in _h5_pairs(attrs)
        items[_h5_key(k)] = v
    end
    first = String[k for k in keys(items) if _h5_is_array_index(k)]
    sort!(first; by=k -> parse(Int, k))
    for k in first
        push!(buf, Pair{String,Any}(k, items[k]))
    end
    for (k, v) in items
        _h5_is_array_index(k) || push!(buf, Pair{String,Any}(k, v))
    end
    return buf
end

function _h5_no_index_keys(ks)
    for k in ks
        _h5_is_array_index(k) && return false
    end
    return true
end

_h5_length(d::AbstractArray) = length(d)
_h5_length(d::Tuple) = length(d)
_h5_length(d::AbstractString) = length(d)
_h5_length(d::AbstractDict) = length(d)
_h5_length(d) = 0

_h5_iterate(d::AbstractArray) = _h5_c_order(d)
_h5_iterate(d::Tuple) = d
_h5_iterate(d::AbstractString) = (string(c) for c in d)
_h5_iterate(d::AbstractDict) = keys(d)
_h5_iterate(d) = ()

"""`ToInt32`: truncated towards zero and wrapped modulo 2^32; NaN and the infinities are 0."""
function _h5_to_int32(x::Float64)
    isfinite(x) || return Int32(0)
    r = rem(trunc(x), 4294967296.0)            # exact
    r < 0 && (r += 4294967296.0)
    return reinterpret(Int32, UInt32(r))
end

# --- the global heap --------------------------------------------------------------------

#: A global heap collection has to be at least this big, and every
#: variable-length string in the file lives in one of them.
const _H5_HEAP_MINIMUM = 4096
#: Past this many objects the two-byte index in a heap ID runs out.
const _H5_HEAP_MAX_OBJECTS = 60000

# Strings numbered in the order they are first seen. For the global heap: every
# variable-length string in the file, pooled. A string on disk is not the
# characters but a 16-byte "global heap ID" -- how many bytes, which collection,
# which object in it -- and the characters live in the collection; identical
# strings share one object, and the k-th string added is object
# (k - 1) % 60000 + 1 of collection (k - 1) ÷ 60000. (Attribute names are
# numbered the same way, so the plan's records are plain bits.)
#
# In front of the table is a small cache by identity: a result file says TRUE,
# its unit, its block and its time hundreds of thousands of times, each time
# as the same String object, and finding the object again is cheaper than
# hashing its characters. The cache holds the strings it points at, so an
# address in it cannot come to be another string's.
struct _H5Interner
    index::Dict{String,Int}
    texts::Vector{String}               # as written: valid UTF-8
    cache_ptr::Vector{UInt}
    cache_id::Vector{Int}
    cache_ref::Vector{String}
end
_H5Interner(slots::Int=256) =
    _H5Interner(Dict{String,Int}(), String[], zeros(UInt, slots), zeros(Int, slots), fill("", slots))

function _h5_intern_text!(t::_H5Interner, text::AbstractString)
    k = get(t.index, text, 0)
    k != 0 && return k
    key = String(text)
    push!(t.texts, _h5_utf8(key))
    k = length(t.texts)
    t.index[key] = k
    return k
end

function _h5_intern!(t::_H5Interner, text::String)
    ptr = UInt(pointer(text))
    slot = (((ptr >> 4) % Int) & (length(t.cache_ptr) - 1)) + 1
    @inbounds t.cache_ptr[slot] == ptr && return t.cache_id[slot]
    k = _h5_intern_text!(t, text)
    @inbounds begin
        t.cache_ptr[slot] = ptr
        t.cache_id[slot] = k
        t.cache_ref[slot] = text
    end
    return k
end
_h5_intern!(t::_H5Interner, text::AbstractString) = _h5_intern_text!(t, text)

const _H5_TRUE = "TRUE"
const _H5_FALSE = "FALSE"

# An attribute's text: a boolean is TRUE or FALSE, which is what Ecolego's files
# say and what every reader of them tests for.
function _h5_text_id!(pool::_H5Interner, @nospecialize(v))::Int
    v isa String && return _h5_intern!(pool, v)
    v isa Bool && return _h5_intern!(pool, v ? _H5_TRUE : _H5_FALSE)
    v isa AbstractString && return _h5_intern_text!(pool, v)
    return _h5_intern!(pool, js_string(v)::String)
end
# A string dataset's values are written as `String()` writes them, so a
# boolean there is `true`.
function _h5_data_id!(pool::_H5Interner, @nospecialize(v))::Int
    v isa String && return _h5_intern!(pool, v)
    v isa AbstractString && return _h5_intern_text!(pool, v)
    return _h5_intern!(pool, js_string(v)::String)
end

# --- laying the file out ----------------------------------------------------------------

# One attribute, normalised: its name by number (the plan's `names`), and its
# values in the plan's `ids` (strings, as heap object numbers) or `nums`
# (doubles) from `first` on.
struct _H5Attr
    name::Int
    str::Bool
    scalar::Bool
    n::Int
    first::Int
end

# One object's numbers. A group's children are `plan.children[group]`.
struct _H5Obj
    attr_first::Int
    attr_count::Int
    header_size::Int
    data_size::Int
    count::Int                          # how many values a dataset holds
    ids_first::Int                      # a string dataset's heap ids, in the plan's `ids`
    group::Int                          # 0 for a dataset
end

struct _H5Plan
    pool::_H5Interner
    names::_H5Interner
    attrs::Vector{_H5Attr}
    ids::Vector{Int}
    nums::Vector{Float64}
    nodes::Vector{H5Node}               # every object, depth first
    links::Vector{String}               # the name each is linked by, as written ("" for the root)
    objs::Vector{_H5Obj}
    addr::Vector{Int}
    data_addr::Vector{Int}
    children::Vector{Vector{Int}}
    heap_at::Vector{Int}
    heap_size::Vector{Int}
    size::Int
end

_h5_datatype_size(dt::H5Datatype) =
    dt.kind === :float ? 20 : dt.kind === :int ? 12 : dt.kind === :vlenstr ? 20 :
    throw(HDF5Error("No datatype for '$(js_string(dt.kind))'"))

_h5_attr_size(a::_H5Attr, names::_H5Interner) =
    9 + ncodeunits(@inbounds names.texts[a.name]) + 1 + 20 + (a.scalar ? 4 : 12) + a.n * (a.str ? 16 : 8)

_h5_link_size(nb::Int) = 2 + (nb > 255 ? 2 : 1) + nb + 8

# The values of an attribute, in a shape the writer can size and write; the
# bytes its message takes.
function _h5_attribute!(plan_attrs::Vector{_H5Attr}, ids::Vector{Int}, nums::Vector{Float64}, pool::_H5Interner,
                        names::_H5Interner, name::String, @nospecialize(value))
    nm = _h5_intern!(names, name)
    if value isa String
        push!(ids, _h5_intern!(pool, value))
        a = _H5Attr(nm, true, true, 1, length(ids))
    elseif value isa Bool
        push!(ids, _h5_intern!(pool, value ? _H5_TRUE : _H5_FALSE))
        a = _H5Attr(nm, true, true, 1, length(ids))
    elseif value isa Float64
        push!(nums, value)
        a = _H5Attr(nm, false, true, 1, length(nums))
    elseif value isa Int
        push!(nums, Float64(value))
        a = _H5Attr(nm, false, true, 1, length(nums))
    elseif value isa Vector{Any}
        a = _h5_list_attribute!(ids, nums, pool, nm, value)
    elseif value isa AbstractArray
        a = _h5_list_attribute!(ids, nums, pool, nm, _h5_c_order(value))
    elseif value isa Tuple
        a = _h5_list_attribute!(ids, nums, pool, nm, value)
    elseif value isa AbstractString || value isa AbstractChar
        push!(ids, _h5_text_id!(pool, value))
        a = _H5Attr(nm, true, true, 1, length(ids))
    else
        push!(nums, js_to_number(value))
        a = _H5Attr(nm, false, true, 1, length(nums))
    end
    push!(plan_attrs, a)
    return 4 + _h5_attr_size(a, names)
end

function _h5_list_attribute!(ids::Vector{Int}, nums::Vector{Float64}, pool::_H5Interner, nm::Int, vals)
    text = false
    for v in vals
        if v isa AbstractString || v isa AbstractChar || v isa Bool
            text = true
            break
        end
    end
    if text
        first = length(ids) + 1
        for v in vals
            push!(ids, _h5_text_id!(pool, v))
        end
    else
        first = length(nums) + 1
        for v in vals
            push!(nums, js_to_number(v))
        end
    end
    return _H5Attr(nm, text, false, length(vals), first)
end

# The attributes of one object, normalised; the bytes their messages take.
function _h5_plan_attrs!(plan_attrs::Vector{_H5Attr}, ids::Vector{Int}, nums::Vector{Float64}, pool::_H5Interner,
                         names::_H5Interner, entries::Vector{Pair{String,Any}}, attrs)
    msgs = 0
    attrs === nothing && return msgs
    if attrs isa H5Attrs && _h5_no_index_keys(attrs.keys)
        ks, vs = attrs.keys, attrs.vals
        for i in eachindex(ks)
            v = @inbounds vs[i]
            v === nothing && continue
            msgs += _h5_attribute!(plan_attrs, ids, nums, pool, names, @inbounds(ks[i]), v)
        end
    elseif attrs isa AbstractDict{String} && _h5_no_index_keys(keys(attrs))
        for (k, v) in attrs
            v === nothing && continue
            msgs += _h5_attribute!(plan_attrs, ids, nums, pool, names, k, v)
        end
    else
        for (k, v) in _h5_entries!(entries, attrs)
            v === nothing && continue
            msgs += _h5_attribute!(plan_attrs, ids, nums, pool, names, k, v)
        end
    end
    return msgs
end

# How many values a dataset holds, and its values as the writer reads them: an
# array of two or more dimensions row by row.
_h5_flat(@nospecialize(data)) = data isa AbstractArray && ndims(data) >= 2 ? _h5_c_order(data) : data

# Walks the tree once: normalises the attributes, pools the strings, and works
# out how big every object header and data block will be, and where everything
# goes. Depth first, each object before its children -- which fixes both the
# order of the headers and the order the strings enter the heap. Walked with a
# stack of its own rather than by recursion, so a deep tree is not refused.
function _h5_plan(root::H5Group)
    pool = _H5Interner()
    names = _H5Interner(64)
    attrs = _H5Attr[]
    ids = Int[]
    nums = Float64[]
    nodes = H5Node[]
    links = String[]
    objs = _H5Obj[]
    children = Vector{Int}[]
    entries = Pair{String,Any}[]
    stack = Tuple{H5Node,String,Int}[(root, "", 0)]      # node, link name, parent object (0: none)
    while !isempty(stack)
        node, link, parent = pop!(stack)
        if parent != 0 && isempty(link)
            throw(HDF5Error("A link cannot have an empty name"))
        end
        attr_first = length(attrs) + 1
        msgs = _h5_plan_attrs!(attrs, ids, nums, pool, names, entries, node.attrs)
        attr_count = length(attrs) - attr_first + 1
        # Every object with attributes says so: without it a reader looks for
        # them in a fractal heap that is not there.
        attr_count > 0 && (msgs += 4 + 18)
        push!(nodes, node)
        push!(links, link)
        me = length(nodes)
        parent != 0 && push!(children[objs[parent].group], me)
        if node isa H5Group
            push!(children, Int[])
            group = length(children)
            msgs += 4 + 18 + 4 + 2                       # link info, group info
            kids = node.children
            kid_names = String[_h5_utf8(k) for k in keys(kids)]
            for nb in kid_names
                msgs += 4 + _h5_link_size(ncodeunits(nb))
            end
            kid_nodes = collect(values(kids))
            for j in length(kid_nodes):-1:1
                push!(stack, (kid_nodes[j], kid_names[j], me))
            end
            push!(objs, _H5Obj(attr_first, attr_count, 14 + msgs, 0, 0, 0, group))
        else
            ds = node::H5Dataset
            data = ds.data
            n = data isa Vector{Float64} ? length(data) : _h5_length(_h5_flat(data))
            ids_first = 0
            if ds.dt.kind === :vlenstr
                ids_first = length(ids) + 1
                for s in _h5_iterate(_h5_flat(data))
                    push!(ids, _h5_data_id!(pool, s))
                end
            end
            rank = ds.dims === nothing ? 1 : length(ds.dims)
            msgs += (4 + 4 + 8 * rank) + (4 + _h5_datatype_size(ds.dt)) + (4 + 2) + (4 + 18)
            push!(objs, _H5Obj(attr_first, attr_count, 14 + msgs, n * ds.dt.size, n, ids_first, 0))
        end
    end

    # Where everything goes: the superblock first, then the strings -- they
    # have to be placed before any header is written, because an attribute's
    # data is the address of the collection holding it -- then the headers,
    # then the numbers, each block on an eight-byte boundary.
    texts = pool.texts
    ncoll = max(1, cld(length(texts), _H5_HEAP_MAX_OBJECTS))
    heap_at = Vector{Int}(undef, ncoll)
    heap_size = Vector{Int}(undef, ncoll)
    at = 48
    for c in 1:ncoll
        n = 16
        lo = (c - 1) * _H5_HEAP_MAX_OBJECTS + 1
        hi = min(c * _H5_HEAP_MAX_OBJECTS, length(texts))
        for k in lo:hi
            n += 16 + 8 * cld(ncodeunits(texts[k]), 8)
        end
        # The specification's minimum. Anything left over is described by a
        # free-space object, which is what index 0 means.
        heap_at[c] = at
        heap_size[c] = max(_H5_HEAP_MINIMUM, n + 16)
        at += heap_size[c]
    end
    nobj = length(objs)
    addr = Vector{Int}(undef, nobj)
    data_addr = Vector{Int}(undef, nobj)
    for i in 1:nobj
        addr[i] = at
        at += objs[i].header_size
    end
    for i in 1:nobj
        # Nothing to point at, and address zero is the superblock: a dataset
        # with no values says so with the undefined address.
        data_addr[i] = -1
        size = objs[i].data_size
        size == 0 && continue
        at = 8 * cld(at, 8)
        data_addr[i] = at
        at += size
    end
    return _H5Plan(pool, names, attrs, ids, nums, nodes, links, objs, addr, data_addr, children, heap_at, heap_size, at)
end

# --- writing ----------------------------------------------------------------------------
#
# Into a buffer of exactly the file's size, at 0-based offsets: each helper
# writes at `p` and returns the offset after what it wrote.

@inline function _h5_u8!(b::Vector{UInt8}, p::Int, v::Integer)
    @inbounds b[p+1] = v % UInt8
    return p + 1
end
@inline function _h5_u16!(b::Vector{UInt8}, p::Int, v::Integer)
    @inbounds b[p+1] = v % UInt8
    @inbounds b[p+2] = (v >> 8) % UInt8
    return p + 2
end
@inline function _h5_u32!(b::Vector{UInt8}, p::Int, v::Integer)
    @inbounds for i in 0:3
        b[p+1+i] = (v >> (8i)) % UInt8
    end
    return p + 4
end
# Eight bytes, little-endian; -1 is the undefined address, all ones.
@inline function _h5_u64!(b::Vector{UInt8}, p::Int, v::Int)
    @inbounds for i in 0:7
        b[p+1+i] = v < 0 ? 0xff : (v >> (8i)) % UInt8
    end
    return p + 8
end
@inline function _h5_f64!(b::Vector{UInt8}, p::Int, x::Float64)
    u = reinterpret(UInt64, x)
    @inbounds for i in 0:7
        b[p+1+i] = (u >> (8i)) % UInt8
    end
    return p + 8
end
@inline function _h5_fill!(b::Vector{UInt8}, p::Int, n::Int, v::UInt8)
    n > 0 && fill!(view(b, p+1:p+n), v)
    return p + n
end
@inline function _h5_text!(b::Vector{UInt8}, p::Int, s::String)
    n = ncodeunits(s)
    n > 0 && GC.@preserve b s unsafe_copyto!(pointer(b, p + 1), pointer(s), n)
    return p + n
end

# A number as eight little-endian bytes the way the JavaScript spells it out
# (`Math.floor(n / 2 ** (8 * i)) & 0xff` for each byte): NaN and the
# infinities are zeros, a negative integer all ones above its bits.
function _h5_le!(b::Vector{UInt8}, p::Int, x)
    if x isa Integer && !(x isa Bool)
        @inbounds for i in 0:7
            b[p+1+i] = (x >> (8i)) & 0xff % UInt8
        end
        return p + 8
    end
    f = js_to_number(x)
    if !isfinite(f)
        return _h5_fill!(b, p, 8, 0x00)
    elseif f != trunc(f)
        @inbounds for i in 0:7
            b[p+1+i] = (floor(BigInt, f / 2.0^(8i)) & 0xff) % UInt8
        end
        return p + 8
    end
    return _h5_le!(b, p, BigInt(f))
end

# The datatype message's body. Version 1, which every reader understands: a
# class-and-version byte, three bytes of class-specific flags, a four-byte
# size, and then properties whose shape depends on the class.
function _h5_datatype!(b::Vector{UInt8}, p::Int, dt::H5Datatype)
    if dt.kind === :float
        # Bit 0 clear is little-endian; bits 4-5 = 2 is the usual "the leading
        # mantissa bit is implied"; bits 8-15 say where the sign sits, which
        # for these is the top bit.
        bits = 0x20 | ((dt.size * 8 - 1) << 8)
        p = _h5_u8!(b, p, (1 << 4) | 1)
        p = _h5_u8!(b, p, bits); p = _h5_u8!(b, p, bits >> 8); p = _h5_u8!(b, p, bits >> 16)
        p = _h5_u32!(b, p, dt.size)
        p = _h5_u16!(b, p, 0)                           # bit offset
        p = _h5_u16!(b, p, dt.size * 8)                 # bit precision
        p = _h5_u8!(b, p, dt.exp_loc); p = _h5_u8!(b, p, dt.exp); p = _h5_u8!(b, p, 0); p = _h5_u8!(b, p, dt.mant)
        return _h5_u32!(b, p, dt.bias)
    elseif dt.kind === :int
        p = _h5_u8!(b, p, (1 << 4) | 0)
        p = _h5_u8!(b, p, dt.signed ? 0x08 : 0x00); p = _h5_u8!(b, p, 0); p = _h5_u8!(b, p, 0)
        p = _h5_u32!(b, p, dt.size)
        p = _h5_u16!(b, p, 0)
        return _h5_u16!(b, p, dt.size * 8)
    elseif dt.kind === :vlenstr
        # Class 9, variable-length. Bits 0-3 = 1 says the sequence is a string;
        # bits 4-7 are its padding rule and bits 8-11 its character set (UTF-8).
        p = _h5_u8!(b, p, (1 << 4) | 9)
        p = _h5_u8!(b, p, 0x01); p = _h5_u8!(b, p, 0x01); p = _h5_u8!(b, p, 0x00)
        p = _h5_u32!(b, p, 16)
        # The parent type is one character, which libhdf5 writes as an eight-bit
        # unsigned integer rather than as a one-byte string.
        p = _h5_u8!(b, p, (1 << 4) | 0)
        p = _h5_u8!(b, p, 0); p = _h5_u8!(b, p, 0); p = _h5_u8!(b, p, 0)
        p = _h5_u32!(b, p, 1)
        p = _h5_u16!(b, p, 0)
        return _h5_u16!(b, p, 8)
    end
    throw(HDF5Error("No datatype for '$(js_string(dt.kind))'"))
end

# The dataspace message's body, version 2, whose "type" byte tells a scalar
# (no dimensions) from a one-element array.
function _h5_dataspace!(b::Vector{UInt8}, p::Int, dims::Union{Nothing,Vector{Any}}, n::Int)
    if dims === nothing                                  # one dimension of `n`
        p = _h5_u8!(b, p, 2); p = _h5_u8!(b, p, 1); p = _h5_u8!(b, p, 0); p = _h5_u8!(b, p, 1)
        return _h5_u64!(b, p, n)
    end
    p = _h5_u8!(b, p, 2); p = _h5_u8!(b, p, length(dims)); p = _h5_u8!(b, p, 0)
    p = _h5_u8!(b, p, isempty(dims) ? 0 : 1)
    for d in dims
        p = _h5_le!(b, p, d)
    end
    return p
end

# One message's four-byte header: its type, its size, no flags.
@inline function _h5_msg!(b::Vector{UInt8}, p::Int, kind::Integer, size::Integer)
    p = _h5_u8!(b, p, kind)
    p = _h5_u16!(b, p, size)
    return _h5_u8!(b, p, 0)
end

# The 16 bytes that stand for one variable-length string: its length, the
# address of its collection, its index in it.
@inline function _h5_heap_id!(b::Vector{UInt8}, p::Int, plan::_H5Plan, k::Int)
    p = _h5_u32!(b, p, ncodeunits(plan.pool.texts[k]))
    p = _h5_u64!(b, p, plan.heap_at[(k - 1) ÷ _H5_HEAP_MAX_OBJECTS + 1])
    return _h5_u32!(b, p, (k - 1) % _H5_HEAP_MAX_OBJECTS + 1)
end

const _H5_LITTLE_ENDIAN = ENDIAN_BOM == 0x04030201

# The numbers of a dataset, as the application's typed arrays hold them.
function _h5_f64_data!(b::Vector{UInt8}, p::Int, data, n::Int)
    if _H5_LITTLE_ENDIAN && data isa Union{Vector{Float64},Base.FastContiguousSubArray{Float64,1}}
        GC.@preserve b data unsafe_copyto!(Ptr{Float64}(pointer(b, p + 1)), pointer(data), n)
        return p + 8n
    end
    for v in _h5_iterate(data)
        p = _h5_f64!(b, p, v isa Real && !(v isa Bool) ? Float64(v) : js_to_number(v))
    end
    return p
end

function _h5_f32_data!(b::Vector{UInt8}, p::Int, data, n::Int)
    if _H5_LITTLE_ENDIAN && data isa Union{Vector{Float32},Base.FastContiguousSubArray{Float32,1}}
        GC.@preserve b data unsafe_copyto!(Ptr{Float32}(pointer(b, p + 1)), pointer(data), n)
        return p + 4n
    end
    # Doubles first, as every JavaScript number is, then rounded to the nearest
    # float32, overflowing to infinity, as a Float32Array stores them.
    for v in _h5_iterate(data)
        x = Float32(v isa Real && !(v isa Bool) ? Float64(v) : js_to_number(v))
        p = _h5_u32!(b, p, reinterpret(UInt32, x))
    end
    return p
end

function _h5_i32_data!(b::Vector{UInt8}, p::Int, data, n::Int)
    for v in _h5_iterate(data)
        x = _h5_to_int32(v isa Real && !(v isa Bool) ? Float64(v) : js_to_number(v))
        p = _h5_u32!(b, p, reinterpret(UInt32, x))
    end
    return p
end

function _h5_header!(b::Vector{UInt8}, plan::_H5Plan, i::Int)
    o = plan.objs[i]
    start = plan.addr[i]
    p = start
    p = _h5_u8!(b, p, UInt8('O')); p = _h5_u8!(b, p, UInt8('H')); p = _h5_u8!(b, p, UInt8('D'))
    p = _h5_u8!(b, p, UInt8('R'))
    p = _h5_u8!(b, p, 2)                                  # version
    p = _h5_u8!(b, p, 2)                                  # the chunk's size takes four bytes
    p = _h5_u32!(b, p, o.header_size - 14)
    node = plan.nodes[i]
    if node isa H5Group
        # Undefined addresses for both indexes: the links are here, in this
        # header, rather than in a fractal heap.
        p = _h5_msg!(b, p, 0x02, 18)
        p = _h5_u8!(b, p, 0); p = _h5_u8!(b, p, 0); p = _h5_fill!(b, p, 16, 0xff)
        p = _h5_msg!(b, p, 0x0a, 2)
        p = _h5_u8!(b, p, 0); p = _h5_u8!(b, p, 0)
        for j in plan.children[o.group]
            name = plan.links[j]
            nb = ncodeunits(name)
            long = nb > 255
            p = _h5_msg!(b, p, 0x06, _h5_link_size(nb))
            p = _h5_u8!(b, p, 1)
            p = _h5_u8!(b, p, long ? 1 : 0)
            p = long ? _h5_u16!(b, p, nb) : _h5_u8!(b, p, nb)
            p = _h5_text!(b, p, name)
            p = _h5_u64!(b, p, plan.addr[j])
        end
    else
        ds = node::H5Dataset
        rank = ds.dims === nothing ? 1 : length(ds.dims)
        p = _h5_msg!(b, p, 0x01, 4 + 8 * rank)
        p = _h5_dataspace!(b, p, ds.dims, o.count)
        p = _h5_msg!(b, p, 0x03, _h5_datatype_size(ds.dt))
        p = _h5_datatype!(b, p, ds.dt)
        # Version 3, allocated late, with no fill value of its own: every byte
        # of this dataset is written, so there is nothing to fill.
        p = _h5_msg!(b, p, 0x05, 2)
        p = _h5_u8!(b, p, 3); p = _h5_u8!(b, p, 2)
        p = _h5_msg!(b, p, 0x08, 18)
        p = _h5_u8!(b, p, 3); p = _h5_u8!(b, p, 1)
        p = _h5_u64!(b, p, plan.data_addr[i])
        p = _h5_u64!(b, p, o.data_size)
    end
    if o.attr_count > 0
        p = _h5_msg!(b, p, 0x15, 18)
        p = _h5_u8!(b, p, 0); p = _h5_u8!(b, p, 0); p = _h5_fill!(b, p, 16, 0xff)
        names = plan.names
        @inbounds for ai in o.attr_first:o.attr_first+o.attr_count-1
            a = plan.attrs[ai]
            name = names.texts[a.name]
            nb = ncodeunits(name)
            dslen = a.scalar ? 4 : 12
            p = _h5_msg!(b, p, 0x0c, _h5_attr_size(a, names))
            p = _h5_u8!(b, p, 3); p = _h5_u8!(b, p, 0)
            p = _h5_u16!(b, p, nb + 1); p = _h5_u16!(b, p, 20); p = _h5_u16!(b, p, dslen)
            p = _h5_u8!(b, p, 0)
            p = _h5_text!(b, p, name)
            p = _h5_u8!(b, p, 0)
            p = _h5_datatype!(b, p, a.str ? H5STR : H5F64)
            if a.scalar
                p = _h5_u8!(b, p, 2); p = _h5_u8!(b, p, 0); p = _h5_u8!(b, p, 0); p = _h5_u8!(b, p, 0)
            else
                p = _h5_u8!(b, p, 2); p = _h5_u8!(b, p, 1); p = _h5_u8!(b, p, 0); p = _h5_u8!(b, p, 1)
                p = _h5_u64!(b, p, a.n)
            end
            if a.str
                for k in a.first:a.first+a.n-1
                    p = _h5_heap_id!(b, p, plan, plan.ids[k])
                end
            else
                for k in a.first:a.first+a.n-1
                    p = _h5_f64!(b, p, plan.nums[k])
                end
            end
        end
    end
    p = _h5_u32!(b, p, _h5_lookup3(b, start, p - start))
    p == start + o.header_size || error("an object header came out $(p - start) bytes, not $(o.header_size)")
    return p
end

# One dataset's values, at its address.
function _h5_data!(b::Vector{UInt8}, plan::_H5Plan, i::Int, ds::H5Dataset)
    o = plan.objs[i]
    p = plan.data_addr[i]
    dt = ds.dt
    data = ds.data
    if dt.kind === :vlenstr
        for k in o.ids_first:o.ids_first+o.count-1
            p = _h5_heap_id!(b, p, plan, plan.ids[k])
        end
    elseif dt.kind === :float && dt.size == 8
        p = data isa Vector{Float64} ? _h5_f64_data!(b, p, data, o.count) : _h5_f64_data!(b, p, _h5_flat(data), o.count)
    elseif dt.kind === :float
        p = _h5_f32_data!(b, p, _h5_flat(data), o.count)
    else
        p = _h5_i32_data!(b, p, _h5_flat(data), o.count)
    end
    p == plan.data_addr[i] + o.data_size || error("a dataset's data came out $(p - plan.data_addr[i]) bytes, not $(o.data_size)")
    return p
end

"""
    write_hdf5(root::H5Group) -> Vector{UInt8}

The file, as bytes (`writeHDF5`). `root` is the tree, from `h5group`,
`h5dataset` and `h5put`. For the same tree the bytes are the application's
(and the Python package's), to the byte. Throws `HDF5Error` when the root is
not a group, a link has an empty name, or a datatype is not one the writer
knows.
"""
function write_hdf5(root)
    root isa H5Group || throw(HDF5Error("The root of a file is a group"))
    plan = _h5_plan(root)
    b = Vector{UInt8}(undef, plan.size)

    # --- the superblock, version 2.
    p = 0
    for c in (0x89, UInt8('H'), UInt8('D'), UInt8('F'), UInt8('\r'), UInt8('\n'), 0x1a, UInt8('\n'))
        p = _h5_u8!(b, p, c)
    end
    p = _h5_u8!(b, p, 2); p = _h5_u8!(b, p, 8); p = _h5_u8!(b, p, 8); p = _h5_u8!(b, p, 0)
    p = _h5_u64!(b, p, 0)                                 # base address
    p = _h5_u64!(b, p, -1)                                # no superblock extension
    p = _h5_u64!(b, p, plan.size)                         # end of file
    p = _h5_u64!(b, p, plan.addr[1])                      # the root group
    p = _h5_u32!(b, p, _h5_lookup3(b, 0, p))

    # --- the strings.
    texts = plan.pool.texts
    for c in eachindex(plan.heap_at)
        start = plan.heap_at[c]
        total = plan.heap_size[c]
        p = start
        p = _h5_u8!(b, p, UInt8('G')); p = _h5_u8!(b, p, UInt8('C')); p = _h5_u8!(b, p, UInt8('O'))
        p = _h5_u8!(b, p, UInt8('L'))
        p = _h5_u8!(b, p, 1); p = _h5_fill!(b, p, 3, 0x00)
        p = _h5_u64!(b, p, total)
        lo = (c - 1) * _H5_HEAP_MAX_OBJECTS + 1
        hi = min(c * _H5_HEAP_MAX_OBJECTS, length(texts))
        for k in lo:hi
            s = texts[k]
            # The reference count is what libhdf5 writes for a string the file
            # itself points at, which is nothing: it counts *references*, the
            # HDF5 kind, and there are none.
            p = _h5_u16!(b, p, k - lo + 1); p = _h5_u16!(b, p, 0); p = _h5_u32!(b, p, 0)
            p = _h5_u64!(b, p, ncodeunits(s))
            p = _h5_text!(b, p, s)
            p = _h5_fill!(b, p, 8 * cld(p, 8) - p, 0x00)
        end
        # What is left is one object with index zero, which is how a collection
        # says "free space" -- and there always is some.
        left = start + total - p
        if left >= 16
            p = _h5_u16!(b, p, 0); p = _h5_u16!(b, p, 0); p = _h5_u32!(b, p, 0); p = _h5_u64!(b, p, left)
            left -= 16
        end
        p = _h5_fill!(b, p, left, 0x00)
    end

    # --- the objects.
    for i in eachindex(plan.objs)
        p = _h5_header!(b, plan, i)
    end

    # --- the numbers, each block on an eight-byte boundary.
    for i in eachindex(plan.objs)
        plan.data_addr[i] < 0 && continue
        p = _h5_fill!(b, p, plan.data_addr[i] - p, 0x00)
        p = _h5_data!(b, plan, i, plan.nodes[i]::H5Dataset)
    end
    p == plan.size || error("the file came out $(p) bytes, not $(plan.size)")
    return b
end
