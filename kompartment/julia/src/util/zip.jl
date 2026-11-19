# ZIP archives and gzip streams, through the zlib Julia ships with.
#
# Model files come as `.json`, `.json.gz` and `.zip`; Ecolego's `.eco` and
# `.eas` are ZIP archives too. This reads and writes the subset of the format
# those use: stored and deflated entries, no encryption; an archive is read as
# the application reads one (see the reading part).

using Zlib_jll: libz

mutable struct ZStream
    next_in::Ptr{UInt8}
    avail_in::Cuint
    total_in::Culong
    next_out::Ptr{UInt8}
    avail_out::Cuint
    total_out::Culong
    msg::Ptr{UInt8}
    state::Ptr{Cvoid}
    zalloc::Ptr{Cvoid}
    zfree::Ptr{Cvoid}
    opaque::Ptr{Cvoid}
    data_type::Cint
    adler::Culong
    reserved::Culong
    ZStream() = new(C_NULL, 0, 0, C_NULL, 0, 0, C_NULL, C_NULL, C_NULL, C_NULL, C_NULL, 0, 0, 0)
end

const Z_OK = Cint(0)
const Z_STREAM_END = Cint(1)
const Z_BUF_ERROR = Cint(-5)
const Z_NO_FLUSH = Cint(0)
const Z_FINISH = Cint(4)
const Z_DEFLATED = Cint(8)
const Z_DEFAULT_STRATEGY = Cint(0)

_zlib_version() = ccall((:zlibVersion, libz), Ptr{UInt8}, ())

function _zmsg(z::ZStream, code)
    z.msg == C_NULL ? "zlib error $code" : unsafe_string(z.msg)
end

"""
    inflate_bytes(data; window_bits=-15, size_hint=0) -> Vector{UInt8}

`data` decompressed: a raw deflate stream (`window_bits` -15, as in a ZIP
entry), a gzip stream (31) or either zlib or gzip (47).
"""
function inflate_bytes(data::AbstractVector{UInt8}; window_bits::Integer=-15, size_hint::Integer=0)
    src = data isa Vector{UInt8} ? data : Vector{UInt8}(data)
    z = ZStream()
    rc = ccall((:inflateInit2_, libz), Cint, (Ref{ZStream}, Cint, Ptr{UInt8}, Cint),
               z, window_bits, _zlib_version(), sizeof(ZStream))
    rc == Z_OK || error("inflateInit2 failed: $(_zmsg(z, rc))")
    out = Vector{UInt8}(undef, max(size_hint, 4 * length(src), 1024))
    produced = 0
    try
        GC.@preserve src out begin
            z.next_in = pointer(src)
            z.avail_in = Cuint(length(src))
            while true
                if produced == length(out)
                    resize!(out, 2 * length(out))
                end
                z.next_out = pointer(out, produced + 1)
                z.avail_out = Cuint(length(out) - produced)
                before = z.avail_out
                rc = ccall((:inflate, libz), Cint, (Ref{ZStream}, Cint), z, Z_NO_FLUSH)
                produced += Int(before - z.avail_out)
                rc == Z_STREAM_END && break
                if rc == Z_BUF_ERROR && z.avail_in == 0
                    error("the compressed data ends before its stream does")
                end
                rc == Z_OK || rc == Z_BUF_ERROR || error("inflate failed: $(_zmsg(z, rc))")
                # Out of output room is handled at the loop's top; a stall with
                # room left and no input left is a truncated stream.
                if z.avail_in == 0 && z.avail_out > 0 && rc != Z_OK
                    error("the compressed data ends before its stream does")
                end
            end
        end
    finally
        ccall((:inflateEnd, libz), Cint, (Ref{ZStream},), z)
    end
    resize!(out, produced)
    return out
end

"""
    deflate_bytes(data; level=6, window_bits=-15) -> Vector{UInt8}

`data` compressed as a raw deflate stream (or gzip, with `window_bits` 31).
"""
function deflate_bytes(data::AbstractVector{UInt8}; level::Integer=6, window_bits::Integer=-15)
    src = data isa Vector{UInt8} ? data : Vector{UInt8}(data)
    z = ZStream()
    rc = ccall((:deflateInit2_, libz), Cint, (Ref{ZStream}, Cint, Cint, Cint, Cint, Cint, Ptr{UInt8}, Cint),
               z, level, Z_DEFLATED, window_bits, 8, Z_DEFAULT_STRATEGY, _zlib_version(), sizeof(ZStream))
    rc == Z_OK || error("deflateInit2 failed: $(_zmsg(z, rc))")
    bound = ccall((:deflateBound, libz), Culong, (Ref{ZStream}, Culong), z, length(src))
    out = Vector{UInt8}(undef, Int(bound) + 64)
    produced = 0
    try
        GC.@preserve src out begin
            z.next_in = pointer(src)
            z.avail_in = Cuint(length(src))
            while true
                if produced == length(out)
                    resize!(out, 2 * length(out))
                end
                z.next_out = pointer(out, produced + 1)
                z.avail_out = Cuint(length(out) - produced)
                before = z.avail_out
                rc = ccall((:deflate, libz), Cint, (Ref{ZStream}, Cint), z, Z_FINISH)
                produced += Int(before - z.avail_out)
                rc == Z_STREAM_END && break
                rc == Z_OK || rc == Z_BUF_ERROR || error("deflate failed: $(_zmsg(z, rc))")
            end
        end
    finally
        ccall((:deflateEnd, libz), Cint, (Ref{ZStream},), z)
    end
    resize!(out, produced)
    return out
end

"""The CRC-32 of a byte vector, as ZIP and gzip check their contents."""
function crc32(data::AbstractVector{UInt8}, crc::UInt32=UInt32(0))
    src = data isa Vector{UInt8} ? data : Vector{UInt8}(data)
    GC.@preserve src begin
        return ccall((:crc32, libz), Culong, (Culong, Ptr{UInt8}, Cuint), crc, pointer(src), length(src)) % UInt32
    end
end

gunzip(data::AbstractVector{UInt8}) = inflate_bytes(data; window_bits=31)
gzip(data::AbstractVector{UInt8}; level::Integer=6) = deflate_bytes(data; level, window_bits=31)

is_gzip(data::AbstractVector{UInt8}) = length(data) >= 2 && data[1] == 0x1f && data[2] == 0x8b
is_zip(data::AbstractVector{UInt8}) = length(data) >= 4 && data[1] == 0x50 && data[2] == 0x4b && data[3] == 0x03 &&
                                      data[4] == 0x04

# --- reading -----------------------------------------------------------------
#
# The entries of a ZIP archive, read as the application reads one: `unzip` in
# src/io/zip.js, which is what reads an Ecolego project, a workbook, a model
# saved as an archive and the run beside it. The end record nearest the end of
# the file is the one read; the ZIP64 end record where the locator says it is;
# as many central records as the end record counts, from where it says they
# start; each entry's name as UTF-8 whatever its flag says (less a leading
# byte-order mark); ZIP64 sizes from the first ZIP64 record only. Stored and
# deflated entries only, no encrypted ones, no CRC check; a deflated `.xml`
# entry inflated as the directory is read and everything else when first asked
# for, all within one allowance for the whole archive and one for each entry; a
# name repeated in the directory keeps its first place and its last entry.
# Every number the file gives is checked before it is used, and what cannot be
# read is said in the application's words.
#
# A 64-bit count from the file is kept whole (Int128), where the application
# holds it as a double: no comparison here can tell the two apart -- one that
# large is past the end of any archive either way -- and a message writes it
# as JavaScript writes the double that holds it. A damaged deflate stream is
# named in zlib's words where the application's inflater names it otherwise.

"""An archive, or an entry of one, that cannot be read: the application's `ZipError`."""
struct ZipReadError <: Exception
    msg::String
end
Base.showerror(io::IO, e::ZipReadError) = print(io, e.msg)

"""The most one entry, and the whole archive, may expand to (`MAX_INFLATED`)."""
const ZIP_MAX_INFLATED = 256 * 1024 * 1024

@inline _zle16(d, i) = Int(d[i]) | (Int(d[i+1]) << 8)
@inline _zle32(d, i) = Int(d[i]) | (Int(d[i+1]) << 8) | (Int(d[i+2]) << 16) | (Int(d[i+3]) << 24)
@inline _zle64(d, i) = UInt64(_zle32(d, i)) | (UInt64(_zle32(d, i + 4)) << 32)

# Whether the four bytes from offset `p` (counted from 0) are `PK`, `c`, `e`.
@inline _zip_sig(d, p::Integer, c::UInt8, e::UInt8) =
    d[p+1] == 0x50 && d[p+2] == 0x4b && d[p+3] == c && d[p+4] == e

# `findEOCD`: the end of central directory record in the last 64 KB, the one
# nearest the end, as `(at, count, offset)` (`at` counted from 0); `nothing`
# when there is none.
function _zip_end_record(data::Vector{UInt8})
    n = length(data)
    for p in n-22:-1:max(0, n - 0x10000 - 22)
        _zip_sig(data, p, 0x05, 0x06) &&
            return (at=p, count=Int128(_zle16(data, p + 11)), offset=Int128(_zle32(data, p + 17)))
    end
    return nothing
end

# `findZip64`: the ZIP64 end record the locator before the end record points
# at, as `(count, offset)`; `nothing` when there is none.
function _zip64_end(data::Vector{UInt8}, end_at::Int, error)
    locator = end_at - 20
    (locator < 0 || locator + 20 > length(data)) && return nothing
    _zip_sig(data, locator, 0x06, 0x07) || return nothing
    at = Int128(_zle64(data, locator + 9))
    # 56 bytes: through the central directory offset, the last field wanted.
    if at > Int128(2)^53 - 1 || at + 56 > length(data)
        throw(error("This archive says its ZIP64 directory is at byte $at, which is outside " *
                             "its own $(length(data)) bytes."))
    end
    _zip_sig(data, at, 0x06, 0x06) || return nothing
    return (count=Int128(_zle64(data, at + 33)), offset=Int128(_zle64(data, at + 49)))
end

# `readZip64Extra`: the sizes and offset a central record left at 0xFFFFFFFF,
# from the first ZIP64 record in its extra field (`start` counted from 0) --
# the uncompressed size, the compressed size and the offset, those that are
# saturated, in that order. Any record after the first is not read.
function _zip64_sizes(data::Vector{UInt8}, start::Int, len::Int, expected::Int128, compressed::Int128,
                          offset::Int128, name::String, error)
    p = start
    # The walk is clamped to the archive, and each 64-bit read to its record.
    stop_all = min(start + len, length(data))
    while p + 4 <= stop_all
        kind = _zle16(data, p + 1)
        size = _zle16(data, p + 3)
        if kind == 0x0001
            q = Ref(p + 4)
            stop = min(p + 4 + size, stop_all)
            function take()
                q[] + 8 > stop && throw(error(
                    "The ZIP64 record for '$name' says it is $size bytes long but " *
                    "does not hold the sizes it promises; the archive looks damaged."))
                v = Int128(_zle64(data, q[] + 1))
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
mutable struct _ZipItem
    data::Union{Nothing,Vector{UInt8}}
    raw::UnitRange{Int}           # where its compressed bytes lie in the archive
    deflated::Bool
    expected::Int128
end

"""
The entries of an archive, by name in the directory's order: a dictionary whose values are
inflated when first asked for and kept (`ZipEntries` in src/io/zip.js). Its keys are the names
and cost nothing; iterating its pairs inflates.
"""
mutable struct ZipEntries <: AbstractDict{String,Vector{UInt8}}
    bytes::Vector{UInt8}
    names::Vector{String}
    items::Dict{String,_ZipItem}
    spent::Int
    limit::Int                    # what the whole archive may inflate to
    entry::Int                    # and one entry
    error::Any                    # what is raised, with a message
end

Base.length(z::ZipEntries) = length(z.names)
Base.keys(z::ZipEntries) = z.names
Base.haskey(z::ZipEntries, name) = haskey(z.items, name)
Base.get(z::ZipEntries, name, default) = haskey(z, name) ? z[name] : default
Base.iterate(z::ZipEntries, i::Int=1) = i > length(z.names) ? nothing : (z.names[i] => z[z.names[i]], i + 1)

function Base.getindex(z::ZipEntries, name::AbstractString)
    it = z.items[name]
    if it.data === nothing
        it.data = it.deflated ? _zip_inflate(z, String(name), it.raw, it.expected) : z.bytes[it.raw]
    end
    return it.data
end

zip_names(z::ZipEntries) = copy(z.names)
zip_read(z::ZipEntries, name::AbstractString) = z[name]

"""`Math.round(x / 1048576)`, written as JavaScript writes it."""
_zip_mb(x) = js_number(floor(Float64(x) / 1048576 + 0.5))

# The decompression allowance, shared by every entry (`Budget`).
function _zip_check(z::ZipEntries, name::String, size::Integer)
    size <= z.limit - z.spent && return
    throw(z.error(
        "'$name' takes this archive past the $(_zip_mb(z.limit)) MB this reader " *
        "will decompress in total: $(_zip_mb(z.spent)) MB have come out already and " *
        "this entry adds $(_zip_mb(size)) more. No real project expands that far, so " *
        "the archive is either damaged or built to exhaust memory."))
end

# zlib's words for the damage the application's own inflater names the same way.
const _ZIP_INFLATE_MESSAGES = Dict(
    "invalid block type" => "Invalid block type",
    "invalid stored block lengths" => "Stored block length check failed",
    "invalid distance too far back" => "Back-reference points before the output",
)

const _ZIP_Z_SYNC_FLUSH = Cint(2)
const _ZIP_Z_DATA_ERROR = Cint(-3)
const _ZIP_Z_MEM_ERROR = Cint(-4)
const _ZIP_Z_STREAM_ERROR = Cint(-2)
const _ZIP_Z_NEED_DICT = Cint(2)

# Raw deflate, as `zlib.decompressobj(-15).decompress(raw, max_length)`: the
# output (at most `max_length` bytes), whether the stream ended, and zlib's
# message for damage (`nothing` when there was none).
function _zip_raw_inflate(src::AbstractVector{UInt8}, max_length::Int, size_hint::Int)
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
                rc = ccall((:inflate, libz), Cint, (Ref{ZStream}, Cint), z, _ZIP_Z_SYNC_FLUSH)
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
                             rc == _ZIP_Z_STREAM_ERROR ? "inconsistent stream state" :
                             rc == _ZIP_Z_DATA_ERROR ? "invalid input data" :
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

# One deflated entry, within what is left of the allowance, checked against the
# size the directory claims (`inflateEntry`).
function _zip_inflate(z::ZipEntries, name::String, raw::UnitRange{Int}, expected::Integer)
    if expected > z.entry
        throw(z.error(
            "'$name' says it expands to $(_zip_mb(expected)) MB, " *
            "past the $(_zip_mb(z.entry)) MB this reader will " *
            "decompress. No real model is that large."))
    end
    _zip_check(z, name, expected)
    limit = min(z.entry, z.limit - z.spent)
    buf, eof, damage = _zip_raw_inflate(view(z.bytes, raw), limit + 1, Int(expected))
    if damage !== nothing
        throw(z.error("Could not decompress '$name': $(get(_ZIP_INFLATE_MESSAGES, damage, damage))"))
    end
    if length(buf) > limit
        throw(z.error(
            "Could not decompress '$name': the entry expands to more than " *
            "$(_zip_mb(limit)) MB, which is far larger than any real model " *
            "-- the archive is either damaged or built to exhaust memory"))
    end
    eof || throw(z.error("Could not decompress '$name': Compressed data ended unexpectedly"))
    _zip_check(z, name, length(buf))
    z.spent += length(buf)
    if expected != 0 && length(buf) != expected
        throw(z.error(
            "'$name' inflated to $(length(buf)) bytes but the directory says " *
            "$(js_number(Float64(expected))); the archive looks damaged."))
    end
    return buf
end

"""
    read_zip(data; inflate_limit, entry_limit, error=ZipReadError) -> ZipEntries

The entries of a ZIP archive, read as the application's `unzip` reads them (see above).
`inflate_limit` is what the whole archive may inflate to and `entry_limit` one entry, the
application's 256 MB unless a test says otherwise. What cannot be read raises `error(message)`
in the application's words -- as the archive is read, or when an entry left deflated is first
asked for.
"""
function read_zip(data::Vector{UInt8}; inflate_limit::Integer=ZIP_MAX_INFLATED, entry_limit::Integer=ZIP_MAX_INFLATED,
                  error=ZipReadError)
    found = _zip_end_record(data)
    found === nothing && throw(error(
        "This does not look like a ZIP archive. An Ecolego project (.eco) is a " *
        "zipped project folder; a bare model.xml should be opened directly instead."))
    entry_count, p = found.count, found.offset
    # ZIP64, for the rare enormous project.
    if entry_count == 0xffff || p == 0xffffffff
        z64 = _zip64_end(data, found.at, error)
        z64 === nothing || ((entry_count, p) = (z64.count, z64.offset))
    end

    archive = ZipEntries(data, String[], Dict{String,_ZipItem}(), 0, Int(inflate_limit), Int(entry_limit), error)
    size = length(data)
    i = Int128(0)
    while i < entry_count
        i += 1
        (p < 0 || p + 46 > size || !_zip_sig(data, p, 0x01, 0x02)) &&
            throw(error("The central directory is damaged"))
        c = Int(p)
        flags = _zle16(data, c + 9)
        method = _zle16(data, c + 11)
        compressed = Int128(_zle32(data, c + 21))
        expected = Int128(_zle32(data, c + 25))
        name_len = _zle16(data, c + 29)
        extra_len = _zle16(data, c + 31)
        comment_len = _zle16(data, c + 33)
        offset = Int128(_zle32(data, c + 43))
        # The record's three variable parts have to fit too.
        c + 46 + name_len + extra_len + comment_len > size &&
            throw(error("The central directory runs past the end of this $size-byte archive"))
        name = _eco_without_bom(_eco_utf8_replace(data, c + 47, c + 46 + name_len))
        if (flags & 0x1) != 0
            throw(error(
                "'$name' is encrypted. Ecolego can obfuscate a project on save; " *
                "re-save it without that option, or export the model, before importing."))
        end
        # ZIP64 extended information, when the 32-bit fields are saturated.
        if compressed == 0xffffffff || expected == 0xffffffff || offset == 0xffffffff
            expected, compressed, offset = _zip64_sizes(data, c + 46 + name_len, extra_len, expected, compressed,
                                                            offset, name, error)
        end
        p += 46 + name_len + extra_len + comment_len
        endswith(name, "/") && continue          # a directory
        if offset < 0 || offset + 30 > size
            throw(error(
                "'$name' says its data begins at byte $(js_number(Float64(offset))), which is " *
                "outside this $size-byte archive."))
        end
        # The local header repeats the name and extra field, and its extra
        # field length can differ from the central one.
        o = Int(offset)
        _zip_sig(data, o, 0x03, 0x04) || throw(error("The local header for '$name' is damaged"))
        start = o + 30 + _zle16(data, o + 27) + _zle16(data, o + 29)
        if start > size || start + compressed > size
            throw(error(
                "'$name' claims $(js_number(Float64(compressed))) bytes from $start, which " *
                "runs past the end of this $size-byte archive."))
        end
        raw = start+1:start+Int(compressed)
        entry = if method == 0
            _ZipItem(nothing, raw, false, expected)
        elseif method == 8
            if endswith(_js_ascii_lower(name), ".xml")   # `/\.xml$/i`
                _ZipItem(_zip_inflate(archive, name, raw, expected), raw, true, expected)
            else
                _ZipItem(nothing, raw, true, expected)
            end
        else
            throw(error(
                "'$name' uses compression method $method, which is not supported " *
                "(only stored and deflate are)."))
        end
        haskey(archive.items, name) || push!(archive.names, name)
        archive.items[name] = entry
    end
    return archive
end

read_zip(path::AbstractString; kw...) = read_zip(read(path); kw...)

# --- writing -----------------------------------------------------------------

"""
    write_zip(entries; deflate=true, modified=(1980, 1, 1, 0, 0, 0)) -> Vector{UInt8}

A ZIP archive of `entries`, pairs of name and bytes, in that order: each
deflated (when that is smaller) or stored, dated `modified` (year, month,
day, hour, minute, second in local DOS time).
"""
function write_zip(entries; deflate::Bool=true, modified=(1980, 1, 1, 0, 0, 0), level::Integer=6)
    io = IOBuffer()
    central = IOBuffer()
    y, mo, d, h, mi, s = modified
    dos_time = UInt16((h << 11) | (mi << 5) | (s ÷ 2))
    dos_date = UInt16(((y - 1980) << 9) | (mo << 5) | d)
    count = 0
    for (name, bytes) in entries
        data = bytes isa Vector{UInt8} ? bytes : Vector{UInt8}(codeunits(String(bytes)))
        nm = Vector{UInt8}(codeunits(String(name)))
        crc = crc32(data)
        method = UInt16(0)
        payload = data
        if deflate && !isempty(data)
            packed = deflate_bytes(data; level)
            if length(packed) < length(data)
                method = UInt16(8)
                payload = packed
            end
        end
        offset = position(io)
        utf8 = any(>(0x7f), nm) ? UInt16(0x0800) : UInt16(0)
        write(io, UInt32(0x04034b50), UInt16(20), utf8, method, dos_time, dos_date, crc,
              UInt32(length(payload)), UInt32(length(data)), UInt16(length(nm)), UInt16(0))
        write(io, nm)
        write(io, payload)
        write(central, UInt32(0x02014b50), UInt16(20), UInt16(20), utf8, method, dos_time, dos_date, crc,
              UInt32(length(payload)), UInt32(length(data)), UInt16(length(nm)), UInt16(0), UInt16(0),
              UInt16(0), UInt16(0), UInt32(0), UInt32(offset))
        write(central, nm)
        count += 1
    end
    cd_offset = position(io)
    cd = take!(central)
    write(io, cd)
    write(io, UInt32(0x06054b50), UInt16(0), UInt16(0), UInt16(count), UInt16(count), UInt32(length(cd)),
          UInt32(cd_offset), UInt16(0))
    return take!(io)
end
