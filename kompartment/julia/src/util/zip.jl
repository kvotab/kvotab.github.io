# ZIP archives and gzip streams, through the zlib Julia ships with.
#
# Model files come as `.json`, `.json.gz` and `.zip`; Ecolego's `.eco` and
# `.eas` are ZIP archives too. This reads and writes the subset of the format
# those use: stored and deflated entries, no encryption, no ZIP64 beyond the
# sizes a model reaches.

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

"""One entry of a ZIP archive: its name and where its data lies."""
struct ZipEntry
    name::String
    method::UInt16
    crc::UInt32
    compressed::Int
    size::Int
    local_offset::Int
end

"""A ZIP archive read into memory: its bytes and its central directory."""
struct ZipArchive
    data::Vector{UInt8}
    entries::Vector{ZipEntry}
end

@inline _u16(d, i) = UInt16(d[i]) | (UInt16(d[i+1]) << 8)
@inline _u32(d, i) = UInt32(d[i]) | (UInt32(d[i+1]) << 8) | (UInt32(d[i+2]) << 16) | (UInt32(d[i+3]) << 24)
@inline _u64(d, i) = UInt64(_u32(d, i)) | (UInt64(_u32(d, i + 4)) << 32)

"""
    read_zip(data) -> ZipArchive

Reads a ZIP archive's central directory (ZIP64 sizes included).
"""
function read_zip(data::Vector{UInt8})
    n = length(data)
    # The end-of-central-directory record: 22 bytes plus a comment of at most 64 KiB.
    eocd = 0
    for i in (n - 21):-1:max(1, n - 21 - 65535)
        if data[i] == 0x50 && data[i+1] == 0x4b && data[i+2] == 0x05 && data[i+3] == 0x06
            eocd = i
            break
        end
    end
    eocd == 0 && error("not a ZIP archive: no central directory")
    count = Int(_u16(data, eocd + 10))
    cd_size = Int(_u32(data, eocd + 12))
    cd_offset = Int(_u32(data, eocd + 16))
    if (cd_offset == 0xffffffff || count == 0xffff) && eocd > 20
        loc = eocd - 20
        if _u32(data, loc) == 0x07064b50
            z64 = Int(_u64(data, loc + 8)) + 1
            if _u32(data, z64) == 0x06064b50
                count = Int(_u64(data, z64 + 32))
                cd_size = Int(_u64(data, z64 + 40))
                cd_offset = Int(_u64(data, z64 + 48))
            end
        end
    end
    entries = ZipEntry[]
    p = cd_offset + 1
    for _ in 1:count
        _u32(data, p) == 0x02014b50 || error("a damaged ZIP archive: a central directory entry is not where it should be")
        flags = _u16(data, p + 8)
        method = _u16(data, p + 10)
        crc = _u32(data, p + 16)
        csize = Int(_u32(data, p + 20))
        usize = Int(_u32(data, p + 24))
        nlen = Int(_u16(data, p + 28))
        xlen = Int(_u16(data, p + 30))
        clen = Int(_u16(data, p + 32))
        loff = Int(_u32(data, p + 42))
        raw = data[p+46:p+45+nlen]
        name = (flags & 0x0800) != 0 || isvalid(String, raw) ? String(raw) : String(map(Char, raw))
        # ZIP64 extra field: the sizes and offset that did not fit.
        x = p + 46 + nlen
        xend = x + xlen
        while x + 4 <= xend
            id = _u16(data, x)
            len = Int(_u16(data, x + 2))
            if id == 0x0001
                q = x + 4
                if usize == 0xffffffff
                    usize = Int(_u64(data, q)); q += 8
                end
                if csize == 0xffffffff
                    csize = Int(_u64(data, q)); q += 8
                end
                if loff == 0xffffffff
                    loff = Int(_u64(data, q)); q += 8
                end
            end
            x += 4 + len
        end
        push!(entries, ZipEntry(name, method, crc, csize, usize, loff))
        p += 46 + nlen + xlen + clen
    end
    return ZipArchive(data, entries)
end

read_zip(path::AbstractString) = read_zip(read(path))

zip_names(z::ZipArchive) = [e.name for e in z.entries]

function _entry(z::ZipArchive, name::AbstractString)
    for e in z.entries
        e.name == name && return e
    end
    throw(KeyError(name))
end

"""
    zip_read(z, name) -> Vector{UInt8}

The contents of one entry, decompressed and checked against its CRC.
"""
function zip_read(z::ZipArchive, e::ZipEntry)
    d = z.data
    p = e.local_offset + 1
    _u32(d, p) == 0x04034b50 || error("a damaged ZIP archive: '$(e.name)' is not where the directory says")
    start = p + 30 + Int(_u16(d, p + 26)) + Int(_u16(d, p + 28))
    raw = view(d, start:start+e.compressed-1)
    out = if e.method == 0
        Vector{UInt8}(raw)
    elseif e.method == 8
        inflate_bytes(raw; size_hint=e.size)
    else
        error("'$(e.name)' is compressed by method $(e.method), which this cannot read")
    end
    length(out) == e.size || error("'$(e.name)' holds $(length(out)) bytes, where the archive says $(e.size)")
    crc32(out) == e.crc || error("'$(e.name)' fails its CRC check: the archive is damaged")
    return out
end
zip_read(z::ZipArchive, name::AbstractString) = zip_read(z, _entry(z, name))

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
