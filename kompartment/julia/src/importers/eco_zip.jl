# The entries of an Ecolego archive (.eco, .eas), read as the application's
# `unzip` (src/io/zip.js) reads them, and so as the Python package's `_unzip`
# does: the end record nearest the end of the file, the ZIP64 end record where
# the locator says it is, as many central records as the end record counts,
# from where it says they start, each entry's name as UTF-8 whatever its flag
# says (less a leading byte-order mark), and ZIP64 sizes from the first ZIP64
# record only; then the data through each entry's local header -- stored and
# deflated entries only, no CRC check, a deflated `.xml` entry inflated up
# front and everything else when first asked for (an assessment's results
# never are), one decompression allowance for the whole archive, and the
# application's messages for what cannot be read.
#
# A 64-bit count from the file is kept whole (Int128), where the application
# holds it as a double: no comparison here can tell the two apart -- one that
# large is past the end of any archive either way -- and a message writes it
# through `_eco_js_string`, which rounds it as `Number()` does.

using Zlib_jll: libz

"""The most one entry, and the whole archive, may expand to."""
const _ECO_MAX_INFLATED = 256 * 1024 * 1024

@inline _eco_le16(d, i) = Int(d[i]) | (Int(d[i+1]) << 8)
@inline _eco_le32(d, i) = Int(d[i]) | (Int(d[i+1]) << 8) | (Int(d[i+2]) << 16) | (Int(d[i+3]) << 24)
@inline _eco_le64(d, i) = UInt64(_eco_le32(d, i)) | (UInt64(_eco_le32(d, i + 4)) << 32)

# Whether the four bytes from offset `p` (counted from 0) are `PK`, `c`, `e`.
@inline _eco_zip_sig(d, p::Integer, c::UInt8, e::UInt8) =
    d[p+1] == 0x50 && d[p+2] == 0x4b && d[p+3] == c && d[p+4] == e

# `findEOCD`: the end of central directory record in the last 64 KB, the one
# nearest the end, as `(at, count, offset)` (`at` counted from 0); `nothing`
# when there is none.
function _eco_end_record(data::Vector{UInt8})
    n = length(data)
    for p in n-22:-1:max(0, n - 0x10000 - 22)
        _eco_zip_sig(data, p, 0x05, 0x06) &&
            return (at=p, count=Int128(_eco_le16(data, p + 11)), offset=Int128(_eco_le32(data, p + 17)))
    end
    return nothing
end

# `findZip64`: the ZIP64 end record the locator before the end record points
# at, as `(count, offset)`; `nothing` when there is none.
function _eco_zip64_end(data::Vector{UInt8}, end_at::Int)
    locator = end_at - 20
    (locator < 0 || locator + 20 > length(data)) && return nothing
    _eco_zip_sig(data, locator, 0x06, 0x07) || return nothing
    at = Int128(_eco_le64(data, locator + 9))
    # 56 bytes: through the central directory offset, the last field wanted.
    if at > Int128(2)^53 - 1 || at + 56 > length(data)
        throw(EcoImportError("This archive says its ZIP64 directory is at byte $at, which is outside " *
                             "its own $(length(data)) bytes."))
    end
    _eco_zip_sig(data, at, 0x06, 0x06) || return nothing
    return (count=Int128(_eco_le64(data, at + 33)), offset=Int128(_eco_le64(data, at + 49)))
end

# `readZip64Extra`: the sizes and offset a central record left at 0xFFFFFFFF,
# from the first ZIP64 record in its extra field (`start` counted from 0) --
# the uncompressed size, the compressed size and the offset, those that are
# saturated, in that order. Any record after the first is not read.
function _eco_zip64_sizes(data::Vector{UInt8}, start::Int, len::Int, expected::Int128, compressed::Int128,
                          offset::Int128, name::String)
    p = start
    # The walk is clamped to the archive, and each 64-bit read to its record.
    stop_all = min(start + len, length(data))
    while p + 4 <= stop_all
        kind = _eco_le16(data, p + 1)
        size = _eco_le16(data, p + 3)
        if kind == 0x0001
            q = Ref(p + 4)
            stop = min(p + 4 + size, stop_all)
            function take()
                q[] + 8 > stop && throw(EcoImportError(
                    "The ZIP64 record for '$name' says it is $size bytes long but " *
                    "does not hold the sizes it promises; the archive looks damaged."))
                v = Int128(_eco_le64(data, q[] + 1))
                q[] += 8
                return v
            end
            expected == 0xffffffff && (expected = take())
            compressed == 0xffffffff && (compressed = take())
            offset == 0xffffffff && (offset = take())
            break
        end
        p += 4 + size
    end
    return expected, compressed, offset
end

# An entry's bytes: stored, inflated, or still to be inflated.
mutable struct _EcoEntry
    data::Union{Nothing,Vector{UInt8}}
    raw::UnitRange{Int}           # where its compressed bytes lie in the archive
    deflated::Bool
    expected::Int128
end

"""The entries of a ZIP archive, by name, most of them decompressed only when
asked for. A name repeated in the directory keeps its first place and its
last entry."""
mutable struct _EcoArchive
    bytes::Vector{UInt8}
    names::Vector{String}
    entries::Dict{String,_EcoEntry}
    spent::Int
end

_eco_names(a::_EcoArchive) = a.names

function _eco_get(a::_EcoArchive, name::String)
    e = a.entries[name]
    if e.data === nothing
        if e.deflated
            e.data = _eco_inflate(a, name, e.raw, e.expected)
        else
            e.data = a.bytes[e.raw]
        end
    end
    return e.data
end

_eco_mb(x) = _eco_js_string(_eco_js_round(x / 1048576))

# The decompression allowance, shared by every entry.
function _eco_check_allowance(a::_EcoArchive, name::String, size::Integer)
    left = _ECO_MAX_INFLATED - a.spent
    size <= left && return
    throw(EcoImportError(
        "'$name' takes this archive past the $(_eco_mb(_ECO_MAX_INFLATED)) MB this reader " *
        "will decompress in total: $(_eco_mb(a.spent)) MB have come out already and " *
        "this entry adds $(_eco_mb(size)) more. No real project expands that far, so " *
        "the archive is either damaged or built to exhaust memory."))
end

# zlib's words for the damage the application's own inflater names the same way.
const _ECO_INFLATE_MESSAGES = Dict(
    "invalid block type" => "Invalid block type",
    "invalid stored block lengths" => "Stored block length check failed",
    "invalid distance too far back" => "Back-reference points before the output",
)

const _ECO_Z_SYNC_FLUSH = Cint(2)
const _ECO_Z_DATA_ERROR = Cint(-3)
const _ECO_Z_MEM_ERROR = Cint(-4)
const _ECO_Z_STREAM_ERROR = Cint(-2)
const _ECO_Z_NEED_DICT = Cint(2)

# Raw deflate, as `zlib.decompressobj(-15).decompress(raw, max_length)`: the
# output (at most `max_length` bytes), whether the stream ended, and zlib's
# message for damage (`nothing` when there was none).
function _eco_raw_inflate(src::AbstractVector{UInt8}, max_length::Int, size_hint::Int)
    input = Vector{UInt8}(src)
    z = ZStream()
    rc = ccall((:inflateInit2_, libz), Cint, (Ref{ZStream}, Cint, Ptr{UInt8}, Cint),
               z, -15, _zlib_version(), sizeof(ZStream))
    rc == Z_OK || error("inflateInit2 failed: $(_zmsg(z, rc))")
    out = Vector{UInt8}(undef, clamp(size_hint + 1, 1024, max(max_length, 1)))
    produced = 0
    eof = false
    damage = nothing
    try
        GC.@preserve input out begin
            z.next_in = pointer(input)
            z.avail_in = Cuint(length(input))
            while true
                if produced == length(out)
                    produced >= max_length && break
                    resize!(out, min(max(2 * length(out), 1024), max_length))
                end
                z.next_out = pointer(out, produced + 1)
                z.avail_out = Cuint(length(out) - produced)
                before = z.avail_out
                rc = ccall((:inflate, libz), Cint, (Ref{ZStream}, Cint), z, _ECO_Z_SYNC_FLUSH)
                produced += Int(before - z.avail_out)
                if rc == Z_STREAM_END
                    eof = true
                    break
                elseif rc == Z_OK || rc == Z_BUF_ERROR
                    # More room helps only when the output filled up.
                    z.avail_out == 0 || break
                else
                    # CPython's `zlib_error`, after the importer's `split(': ', 1)[-1]`.
                    damage = z.msg != C_NULL ? first(unsafe_string(z.msg), 200) :
                             rc == _ECO_Z_STREAM_ERROR ? "inconsistent stream state" :
                             rc == _ECO_Z_DATA_ERROR ? "invalid input data" :
                             "Error $rc while decompressing data"
                    break
                end
            end
        end
    finally
        ccall((:inflateEnd, libz), Cint, (Ref{ZStream},), z)
    end
    resize!(out, produced)
    return out, eof, damage
end

# One deflated entry, within what is left of the allowance, checked against
# the size the directory claims.
function _eco_inflate(a::_EcoArchive, name::String, raw::UnitRange{Int}, expected::Integer)
    if expected > _ECO_MAX_INFLATED
        throw(EcoImportError(
            "'$name' says it expands to $(_eco_mb(expected)) MB, " *
            "past the $(_eco_mb(_ECO_MAX_INFLATED)) MB this reader will " *
            "decompress. No real model is that large."))
    end
    _eco_check_allowance(a, name, expected)
    limit = min(_ECO_MAX_INFLATED, _ECO_MAX_INFLATED - a.spent)
    buf, eof, damage = _eco_raw_inflate(view(a.bytes, raw), limit + 1, Int(expected))
    if damage !== nothing
        throw(EcoImportError("Could not decompress '$name': $(get(_ECO_INFLATE_MESSAGES, damage, damage))"))
    end
    if length(buf) > limit
        throw(EcoImportError(
            "Could not decompress '$name': the entry expands to more than " *
            "$(_eco_mb(limit)) MB, which is far larger than any real model " *
            "-- the archive is either damaged or built to exhaust memory"))
    end
    eof || throw(EcoImportError("Could not decompress '$name': Compressed data ended unexpectedly"))
    _eco_check_allowance(a, name, length(buf))
    a.spent += length(buf)
    if expected != 0 && length(buf) != expected
        throw(EcoImportError(
            "'$name' inflated to $(length(buf)) bytes but the directory says " *
            "$expected; the archive looks damaged."))
    end
    return buf
end

"""The entries of a ZIP archive; [`EcoImportError`](@ref) for one that cannot be read."""
function _eco_unzip(data::Vector{UInt8})
    found = _eco_end_record(data)
    found === nothing && throw(EcoImportError(
        "This does not look like a ZIP archive. An Ecolego project (.eco) is a " *
        "zipped project folder; a bare model.xml should be opened directly instead."))
    entry_count, p = found.count, found.offset
    # ZIP64, for the rare enormous project.
    if entry_count == 0xffff || p == 0xffffffff
        z64 = _eco_zip64_end(data, found.at)
        z64 === nothing || ((entry_count, p) = (z64.count, z64.offset))
    end

    archive = _EcoArchive(data, String[], Dict{String,_EcoEntry}(), 0)
    size = length(data)
    i = Int128(0)
    while i < entry_count
        i += 1
        (p < 0 || p + 46 > size || !_eco_zip_sig(data, p, 0x01, 0x02)) &&
            throw(EcoImportError("The central directory is damaged"))
        c = Int(p)
        flags = _eco_le16(data, c + 9)
        method = _eco_le16(data, c + 11)
        compressed = Int128(_eco_le32(data, c + 21))
        expected = Int128(_eco_le32(data, c + 25))
        name_len = _eco_le16(data, c + 29)
        extra_len = _eco_le16(data, c + 31)
        comment_len = _eco_le16(data, c + 33)
        offset = Int128(_eco_le32(data, c + 43))
        # The record's three variable parts have to fit too.
        c + 46 + name_len + extra_len + comment_len > size &&
            throw(EcoImportError("The central directory runs past the end of this $size-byte archive"))
        name = _eco_without_bom(_eco_utf8_replace(data, c + 47, c + 46 + name_len))
        if (flags & 0x1) != 0
            throw(EcoImportError(
                "'$name' is encrypted. Ecolego can obfuscate a project on save; " *
                "re-save it without that option, or export the model, before importing."))
        end
        # ZIP64 extended information, when the 32-bit fields are saturated.
        if compressed == 0xffffffff || expected == 0xffffffff || offset == 0xffffffff
            expected, compressed, offset = _eco_zip64_sizes(data, c + 46 + name_len, extra_len, expected,
                                                            compressed, offset, name)
        end
        p += 46 + name_len + extra_len + comment_len
        endswith(name, "/") && continue          # a directory
        if offset < 0 || offset + 30 > size
            throw(EcoImportError(
                "'$name' says its data begins at byte $(_eco_js_string(offset)), which is " *
                "outside this $size-byte archive."))
        end
        # The local header repeats the name and extra field, and its extra
        # field length can differ from the central one.
        o = Int(offset)
        _eco_zip_sig(data, o, 0x03, 0x04) || throw(EcoImportError("The local header for '$name' is damaged"))
        start = o + 30 + _eco_le16(data, o + 27) + _eco_le16(data, o + 29)
        if start > size || start + compressed > size
            throw(EcoImportError(
                "'$name' claims $(_eco_js_string(compressed)) bytes from $start, which " *
                "runs past the end of this $size-byte archive."))
        end
        raw = start+1:start+Int(compressed)
        entry = if method == 0
            _EcoEntry(nothing, raw, false, expected)
        elseif method == 8
            if endswith(_eco_py_lower(name), ".xml")
                _EcoEntry(_eco_inflate(archive, name, raw, expected), raw, true, expected)
            else
                _EcoEntry(nothing, raw, true, expected)
            end
        else
            throw(EcoImportError(
                "'$name' uses compression method $method, which is not supported " *
                "(only stored and deflate are)."))
        end
        haskey(archive.entries, name) || push!(archive.names, name)
        archive.entries[name] = entry
    end
    return archive
end
