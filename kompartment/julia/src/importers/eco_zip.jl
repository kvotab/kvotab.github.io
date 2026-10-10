# The entries of an Ecolego archive (.eco, .eas), read as the Python port of
# the importer reads them: the central directory as Python's `zipfile` reads
# it (end record found the same way, entries counted by the directory's size,
# ZIP64 sizes and offsets, an archive with something before it), with its
# refusals, and the data through each entry's local header -- stored and
# deflated entries only, no CRC check, a deflated `.xml` entry inflated up
# front and everything else when first asked for (an assessment's results
# never are), one decompression allowance for the whole archive, and the
# application's messages for what cannot be read.

using Zlib_jll: libz

"""The most one entry, and the whole archive, may expand to."""
const _ECO_MAX_INFLATED = 256 * 1024 * 1024

# What zipfile raises, before the importer says it in its own words.
struct _EcoBadZip <: Exception
    msg::String
end

# One entry of the central directory, as zipfile's ZipInfo has it.
struct _EcoZipInfo
    orig_name::Vector{UInt8}      # the name's bytes
    utf8::Bool                    # flagged as UTF-8 (bit 11)
    flag_bits::UInt16
    compress_type::UInt16
    compress_size::Int128         # Python's integers: a ZIP64 field can hold up to 2^64 - 1
    file_size::Int128
    header_offset::Int128
end

@inline _eco_le16(d, i) = Int(d[i]) | (Int(d[i+1]) << 8)
@inline _eco_le32(d, i) = Int(d[i]) | (Int(d[i+1]) << 8) | (Int(d[i+2]) << 16) | (Int(d[i+3]) << 24)
@inline _eco_le64(d, i) = UInt64(_eco_le32(d, i)) | (UInt64(_eco_le32(d, i + 4)) << 32)

# `BytesIO.seek(offset, 2)` followed by `read(count)`: a position before the
# start is the start.
function _eco_read_from_end(data::Vector{UInt8}, offset::Int, count::Int)
    n = length(data)
    pos = max(n + offset, 0)
    return view(data, pos+1:min(pos + count, n)), pos
end

function _eco_rfind(data::AbstractVector{UInt8}, sig::NTuple{4,UInt8})
    for i in length(data)-3:-1:1
        (data[i] == sig[1] && data[i+1] == sig[2] && data[i+2] == sig[3] && data[i+3] == sig[4]) && return i
    end
    return 0
end

# The end of central directory record as zipfile's `_EndRecData` finds it:
# `(signature64, size, offset, location)`, or `nothing` for no ZIP archive.
function _eco_end_record(data::Vector{UInt8})
    filesize = length(data)
    rec, _ = _eco_read_from_end(data, -22, typemax(Int) ÷ 2)
    if length(rec) == 22 && rec[1] == 0x50 && rec[2] == 0x4b && rec[3] == 0x05 && rec[4] == 0x06 &&
       rec[21] == 0x00 && rec[22] == 0x00
        endrec = (sig64=false, size=Int128(_eco_le32(rec, 13)), offset=Int128(_eco_le32(rec, 17)),
                  location=Int128(filesize - 22))
        return _eco_end_record64(data, -22, endrec)
    end
    max_comment_start = max(filesize - (1 << 16) - 22, 0)
    tail = view(data, max_comment_start+1:filesize)
    start = _eco_rfind(tail, (0x50, 0x4b, 0x05, 0x06))
    if start > 0
        length(tail) - start + 1 < 22 && return nothing
        r = view(tail, start:start+21)
        endrec = (sig64=false, size=Int128(_eco_le32(r, 13)), offset=Int128(_eco_le32(r, 17)),
                  location=Int128(max_comment_start + start - 1))
        return _eco_end_record64(data, max_comment_start + start - 1 - filesize, endrec)
    end
    return nothing
end

function _eco_end_record64(data::Vector{UInt8}, offset::Int, endrec)
    loc, _ = _eco_read_from_end(data, offset - 20, 20)
    length(loc) == 20 || return endrec
    (loc[1] == 0x50 && loc[2] == 0x4b && loc[3] == 0x06 && loc[4] == 0x07) || return endrec
    diskno = _eco_le32(loc, 5)
    disks = _eco_le32(loc, 17)
    (diskno != 0 || disks > 1) && throw(_EcoBadZip("zipfiles that span multiple disks are not supported"))
    rec, _ = _eco_read_from_end(data, offset - 20 - 56, 56)
    length(rec) == 56 || return endrec
    (rec[1] == 0x50 && rec[2] == 0x4b && rec[3] == 0x06 && rec[4] == 0x06) || return endrec
    return (sig64=true, size=Int128(_eco_le64(rec, 41)), offset=Int128(_eco_le64(rec, 49)), location=endrec.location)
end

# zipfile's `_RealGetContents`: the entries of the central directory.
function _eco_central_directory(data::Vector{UInt8})
    endrec = _eco_end_record(data)
    endrec === nothing && throw(_EcoBadZip("File is not a zip file"))
    size_cd = endrec.size
    offset_cd = endrec.offset
    concat = endrec.location - size_cd - offset_cd
    endrec.sig64 && (concat -= 56 + 20)
    start_dir = offset_cd + concat
    start_dir < 0 && throw(_EcoBadZip("Bad offset for central directory"))
    n = length(data)
    cd = view(data, Int(min(start_dir, n))+1:Int(min(start_dir + size_cd, n)))
    p = 1                                     # the read position in `cd`
    take(k) = (a = p; p = min(p + k, length(cd) + 1); view(cd, a:p-1))
    infos = _EcoZipInfo[]
    total = 0
    while total < size_cd
        centdir = take(46)
        length(centdir) == 46 || throw(_EcoBadZip("Truncated central directory"))
        (centdir[1] == 0x50 && centdir[2] == 0x4b && centdir[3] == 0x01 && centdir[4] == 0x02) ||
            throw(_EcoBadZip("Bad magic number for central directory"))
        extract_version = Int(centdir[7])
        flags = UInt16(_eco_le16(centdir, 9))
        method = UInt16(_eco_le16(centdir, 11))
        compress_size = Int128(_eco_le32(centdir, 21))
        file_size = Int128(_eco_le32(centdir, 25))
        name_len = _eco_le16(centdir, 29)
        extra_len = _eco_le16(centdir, 31)
        comment_len = _eco_le16(centdir, 33)
        header_offset = Int128(_eco_le32(centdir, 43))
        name = Vector{UInt8}(take(name_len))
        utf8 = (flags & 0x0800) != 0
        # zipfile decodes a flagged name strictly, and fails on one that is not UTF-8.
        utf8 && _eco_utf8_strict(name)
        extra = Vector{UInt8}(take(extra_len))
        take(comment_len)
        if extract_version > 63
            error(@sprintf("zip file version %.1f", extract_version / 10))
        end
        file_size, compress_size, header_offset = _eco_decode_extra(extra, name, file_size, compress_size,
                                                                    header_offset)
        push!(infos, _EcoZipInfo(name, utf8, flags, method, compress_size, file_size, header_offset + concat))
        total += 46 + name_len + extra_len + comment_len
    end
    return infos
end

# ZipInfo._decodeExtra: the ZIP64 sizes and offset, and the checks on the
# unicode path field (whose name zipfile uses for nothing the importer reads).
function _eco_decode_extra(extra::Vector{UInt8}, name::Vector{UInt8}, file_size::Int128, compress_size::Int128,
                           header_offset::Int128)
    k = 1
    while length(extra) - k + 1 >= 4
        tp = _eco_le16(extra, k)
        ln = _eco_le16(extra, k + 2)
        if ln + 4 > length(extra) - k + 1
            throw(_EcoBadZip(@sprintf("Corrupt extra field %04x (size=%d)", tp, ln)))
        end
        body = view(extra, k+4:k+3+ln)
        if tp == 0x0001
            q = 1
            field = ""
            function next8()
                q + 7 <= length(body) || throw(_EcoBadZip("Corrupt zip64 extra field. $field not found."))
                v = Int128(_eco_le64(body, q))
                q += 8
                return v
            end
            if file_size == 0xffffffff
                field = "File size"
                file_size = next8()
            end
            if compress_size == 0xffffffff
                field = "Compress size"
                compress_size = next8()
            end
            if header_offset == 0xffffffff
                field = "Header offset"
                header_offset = next8()
            end
        elseif tp == 0x7075
            length(body) >= 5 || throw(_EcoBadZip("Corrupt unicode path extra field (0x7075)"))
            up_version = body[1]
            up_crc = UInt32(_eco_le32(body, 2))
            if up_version == 1 && up_crc == crc32(name)
                try
                    _eco_utf8_strict(view(body, 6:length(body)))
                catch e
                    e isa _EcoDecodeError || rethrow()
                    throw(_EcoBadZip("Corrupt unicode path extra field (0x7075): invalid utf-8 bytes"))
                end
            end
        end
        k += ln + 4
    end
    return file_size, compress_size, header_offset
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

# The name the application gives an entry: UTF-8 whatever the flag says (a
# flagged name was checked by the directory's reader), less a leading
# byte-order mark.
_eco_entry_name(info::_EcoZipInfo) = _eco_without_bom(_eco_utf8_replace(info.orig_name))

"""The entries of a ZIP archive; [`EcoImportError`](@ref) for one that cannot be read."""
function _eco_unzip(data::Vector{UInt8})
    infos = try
        _eco_central_directory(data)
    catch e
        if e isa _EcoBadZip
            e.msg == "File is not a zip file" && throw(EcoImportError(
                "This does not look like a ZIP archive. An Ecolego project (.eco) is a " *
                "zipped project folder; a bare model.xml should be opened directly instead."))
            e.msg in ("Bad magic number for central directory", "Truncated central directory") &&
                throw(EcoImportError("The central directory is damaged"))
            throw(EcoImportError("The archive is damaged: $(e.msg)"))
        elseif e isa _EcoDecodeError
            throw(EcoImportError("The archive is damaged: $(e.msg)"))
        end
        rethrow()
    end

    archive = _EcoArchive(data, String[], Dict{String,_EcoEntry}(), 0)
    size = length(data)
    for info in infos
        name = _eco_entry_name(info)
        if (info.flag_bits & 0x1) != 0
            throw(EcoImportError(
                "'$name' is encrypted. Ecolego can obfuscate a project on save; " *
                "re-save it without that option, or export the model, before importing."))
        end
        endswith(name, "/") && continue          # a directory
        offset = info.header_offset
        if offset < 0 || offset + 30 > size
            throw(EcoImportError(
                "'$name' says its data begins at byte $offset, which is " *
                "outside this $size-byte archive."))
        end
        o = Int(offset)
        (data[o+1] == 0x50 && data[o+2] == 0x4b && data[o+3] == 0x03 && data[o+4] == 0x04) ||
            throw(EcoImportError("The local header for '$name' is damaged"))
        name_len = _eco_le16(data, o + 27)
        extra_len = _eco_le16(data, o + 29)
        start = offset + 30 + name_len + extra_len
        compressed = info.compress_size
        if start > size || start + compressed > size
            throw(EcoImportError(
                "'$name' claims $compressed bytes from $start, which " *
                "runs past the end of this $size-byte archive."))
        end
        raw = Int(start)+1:Int(start + compressed)
        method = info.compress_type
        entry = if method == 0
            _EcoEntry(nothing, raw, false, info.file_size)
        elseif method == 8
            if endswith(_eco_py_lower(name), ".xml")
                _EcoEntry(_eco_inflate(archive, name, raw, info.file_size), raw, true, info.file_size)
            else
                _EcoEntry(nothing, raw, true, info.file_size)
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
