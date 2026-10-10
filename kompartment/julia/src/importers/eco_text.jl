# Bytes as text, as the Python port of the Ecolego importer decodes them:
# CPython's UTF-8 and UTF-16 decoders with `errors='replace'` (one U+FFFD for
# each maximal ill-formed subpart, as the browser's `TextDecoder` does too),
# and the message of the `UnicodeDecodeError` its strict UTF-8 decoder raises.

# One step of CPython's UTF-8 decoder at byte `i` of `b[i:stop]`: the
# character's code point and length, or an error: `(:end, k)` for a
# sequence cut short by the end (the rest of the bytes are its range),
# `(:start, 1)` for a byte that cannot begin one and `(:cont, k)` for a
# sequence broken after its first `k` bytes.
@inline function _eco_utf8_step(b, i::Int, stop::Int)
    c = @inbounds b[i]
    c < 0x80 && return (:ok, UInt32(c), 1)
    left = stop - i + 1
    iscont(x) = (x & 0xc0) == 0x80
    if c < 0xe0
        c < 0xc2 && return (:start, UInt32(0), 1)
        left < 2 && return (:end, UInt32(0), left)
        c2 = @inbounds b[i+1]
        iscont(c2) || return (:cont, UInt32(0), 1)
        return (:ok, (UInt32(c & 0x1f) << 6) | UInt32(c2 & 0x3f), 2)
    end
    if c < 0xf0
        if left < 3
            left < 2 && return (:end, UInt32(0), left)
            c2 = @inbounds b[i+1]
            (!iscont(c2) || (c2 < 0xa0 ? c == 0xe0 : c == 0xed)) && return (:cont, UInt32(0), 1)
            return (:end, UInt32(0), left)
        end
        c2 = @inbounds b[i+1]
        c3 = @inbounds b[i+2]
        iscont(c2) || return (:cont, UInt32(0), 1)
        (c == 0xe0 && c2 < 0xa0) && return (:cont, UInt32(0), 1)
        (c == 0xed && c2 >= 0xa0) && return (:cont, UInt32(0), 1)
        iscont(c3) || return (:cont, UInt32(0), 2)
        return (:ok, (UInt32(c & 0x0f) << 12) | (UInt32(c2 & 0x3f) << 6) | UInt32(c3 & 0x3f), 3)
    end
    if c < 0xf5
        if left < 4
            left < 2 && return (:end, UInt32(0), left)
            c2 = @inbounds b[i+1]
            (!iscont(c2) || (c2 < 0x90 ? c == 0xf0 : c == 0xf4)) && return (:cont, UInt32(0), 1)
            left < 3 && return (:end, UInt32(0), left)
            c3 = @inbounds b[i+2]
            iscont(c3) || return (:cont, UInt32(0), 2)
            return (:end, UInt32(0), left)
        end
        c2 = @inbounds b[i+1]
        c3 = @inbounds b[i+2]
        c4 = @inbounds b[i+3]
        iscont(c2) || return (:cont, UInt32(0), 1)
        (c == 0xf0 && c2 < 0x90) && return (:cont, UInt32(0), 1)
        (c == 0xf4 && c2 >= 0x90) && return (:cont, UInt32(0), 1)
        iscont(c3) || return (:cont, UInt32(0), 2)
        iscont(c4) || return (:cont, UInt32(0), 3)
        return (:ok, (UInt32(c & 0x07) << 18) | (UInt32(c2 & 0x3f) << 12) | (UInt32(c3 & 0x3f) << 6) |
                     UInt32(c4 & 0x3f), 4)
    end
    return (:start, UInt32(0), 1)
end

"""
    _eco_utf8_replace(bytes, start=1, stop=length(bytes)) -> String

`bytes[start:stop].decode('utf-8', 'replace')`: well-formed text as it is,
and one U+FFFD in place of each maximal ill-formed subpart.
"""
function _eco_utf8_replace(b::AbstractVector{UInt8}, start::Int=1, stop::Int=length(b))
    v = view(b, start:stop)
    isvalid(String, v) && return String(Vector{UInt8}(v))
    io = IOBuffer(sizehint=stop - start + 1)
    i = start
    while i <= stop
        kind, cp, k = _eco_utf8_step(b, i, stop)
        if kind === :ok
            write(io, view(b, i:i+k-1))
        else
            write(io, '�')
        end
        i += k
    end
    return String(take!(io))
end

"""
    _eco_utf8_strict(bytes) -> String

`bytes.decode('utf-8')`; an `_EcoDecodeError` with CPython's message for
bytes that are not UTF-8.
"""
struct _EcoDecodeError <: Exception
    msg::String
end
Base.showerror(io::IO, e::_EcoDecodeError) = print(io, e.msg)

function _eco_utf8_strict(b::AbstractVector{UInt8})
    isvalid(String, b) && return String(Vector{UInt8}(b))
    n = length(b)
    i = 1
    while i <= n
        kind, cp, k = _eco_utf8_step(b, i, n)
        if kind !== :ok
            reason = kind === :end ? "unexpected end of data" :
                     kind === :start ? "invalid start byte" : "invalid continuation byte"
            first0 = i - 1                       # positions count from 0
            last0 = i - 1 + k - 1
            if k == 1
                throw(_EcoDecodeError("'utf-8' codec can't decode byte 0x$(string(b[i]; base=16, pad=2)) " *
                                      "in position $first0: $reason"))
            end
            throw(_EcoDecodeError("'utf-8' codec can't decode bytes in position $first0-$last0: $reason"))
        end
        i += k
    end
    return String(Vector{UInt8}(b))           # not reached
end

"""
    _eco_utf16_replace(bytes, start, little_endian) -> String

`bytes[start:].decode('utf-16-be' or 'utf-16-le', 'replace')` as CPython
decodes it: a lone surrogate is one U+FFFD, a high surrogate with nothing
after it (an odd byte included) one more, and an odd byte at the end one.
"""
function _eco_utf16_replace(b::AbstractVector{UInt8}, start::Int, little_endian::Bool)
    n = length(b)
    io = IOBuffer(sizehint=n - start + 1)
    unit(i) = little_endian ? (UInt16(b[i+1]) << 8) | UInt16(b[i]) : (UInt16(b[i]) << 8) | UInt16(b[i+1])
    q = start
    while true
        if n - q + 1 < 2
            q <= n && write(io, '�')        # "truncated data": the odd byte
            break
        end
        ch = unit(q)
        q += 2
        if ch < 0xd800 || ch > 0xdfff
            write(io, Char(ch))
            continue
        end
        if ch >= 0xdc00                        # a low surrogate on its own: "illegal encoding"
            write(io, '�')
            continue
        end
        if n - q + 1 < 2                       # "unexpected end of data": the rest is one error
            write(io, '�')
            break
        end
        ch2 = unit(q)
        if 0xdc00 <= ch2 <= 0xdfff
            q += 2
            write(io, Char(0x10000 + ((UInt32(ch) - 0xd800) << 10) + (UInt32(ch2) - 0xdc00)))
        else                                   # "illegal UTF-16 surrogate": the high one alone
            write(io, '�')
        end
    end
    return String(take!(io))
end

_eco_without_bom(text::String) = startswith(text, '﻿') ? text[nextind(text, 1):end] : text

"""
    decode_eco_xml_bytes(bytes) -> String

XML bytes as text, honouring a byte-order mark: UTF-16 big-endian (as
Ecolego 5 wrote it) or little-endian, or UTF-8 with or without one.
Undecodable bytes become U+FFFD, and one further byte-order mark after the
first is dropped too. `decode_xml_bytes` in the Python package.
"""
function decode_eco_xml_bytes(b::AbstractVector{UInt8})
    n = length(b)
    if n >= 2
        b[1] == 0xfe && b[2] == 0xff && return _eco_without_bom(_eco_utf16_replace(b, 3, false))
        b[1] == 0xff && b[2] == 0xfe && return _eco_without_bom(_eco_utf16_replace(b, 3, true))
    end
    if n >= 3 && b[1] == 0xef && b[2] == 0xbb && b[3] == 0xbf
        return _eco_without_bom(_eco_utf8_replace(b, 4, n))
    end
    return _eco_without_bom(_eco_utf8_replace(b, 1, n))
end
