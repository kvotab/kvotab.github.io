# Reading JSON: a small, strict reader over the bytes of the text.
#
# Objects come back as ordered dictionaries (`JDict`), in the file's key order;
# arrays as `Vector{Any}`; `null` as `nothing`; a number written without a
# fraction or an exponent as an `Int64` when it fits, every other number as
# the `Float64` JavaScript reads it as (Infinity past the range).

struct JSONError <: Exception
    message::String
    position::Int
end
Base.showerror(io::IO, e::JSONError) = print(io, e.message, " (at byte ", e.position, ")")

mutable struct _JSONReader
    s::Vector{UInt8}
    i::Int
    n::Int
end

@inline function _skip_ws!(r::_JSONReader)
    s, i, n = r.s, r.i, r.n
    @inbounds while i <= n
        c = s[i]
        (c == 0x20 || c == 0x0a || c == 0x0d || c == 0x09) || break
        i += 1
    end
    r.i = i
end

_json_fail(r::_JSONReader, what) = throw(JSONError(what, r.i))

function _read_value(r::_JSONReader, depth::Int)
    depth > 10000 && _json_fail(r, "JSON nested too deeply")
    _skip_ws!(r)
    r.i > r.n && _json_fail(r, "Unexpected end of JSON")
    c = @inbounds r.s[r.i]
    if c == UInt8('{')
        return _read_object(r, depth)
    elseif c == UInt8('[')
        return _read_array(r, depth)
    elseif c == UInt8('"')
        return _read_string(r)
    elseif c == UInt8('t')
        _expect_word(r, "true")
        return true
    elseif c == UInt8('f')
        _expect_word(r, "false")
        return false
    elseif c == UInt8('n')
        _expect_word(r, "null")
        return nothing
    elseif c == UInt8('-') || (UInt8('0') <= c <= UInt8('9'))
        return _read_number(r)
    end
    _json_fail(r, "Unexpected character '$(Char(c))' in JSON")
end

function _expect_word(r::_JSONReader, w::String)
    m = ncodeunits(w)
    if r.i + m - 1 > r.n || any(k -> r.s[r.i+k-1] != codeunit(w, k), 1:m)
        _json_fail(r, "Unexpected text in JSON")
    end
    r.i += m
end

function _read_object(r::_JSONReader, depth::Int)
    r.i += 1
    out = JDict()
    _skip_ws!(r)
    if r.i <= r.n && r.s[r.i] == UInt8('}')
        r.i += 1
        return out
    end
    while true
        _skip_ws!(r)
        (r.i <= r.n && r.s[r.i] == UInt8('"')) || _json_fail(r, "Expected a key in a JSON object")
        key = _read_string(r)
        _skip_ws!(r)
        (r.i <= r.n && r.s[r.i] == UInt8(':')) || _json_fail(r, "Expected ':' in a JSON object")
        r.i += 1
        out[key] = _read_value(r, depth + 1)
        _skip_ws!(r)
        r.i > r.n && _json_fail(r, "Unexpected end of JSON in an object")
        c = r.s[r.i]
        r.i += 1
        c == UInt8('}') && return out
        c == UInt8(',') || _json_fail(r, "Expected ',' or '}' in a JSON object")
    end
end

function _read_array(r::_JSONReader, depth::Int)
    r.i += 1
    out = Any[]
    _skip_ws!(r)
    if r.i <= r.n && r.s[r.i] == UInt8(']')
        r.i += 1
        return out
    end
    while true
        push!(out, _read_value(r, depth + 1))
        _skip_ws!(r)
        r.i > r.n && _json_fail(r, "Unexpected end of JSON in an array")
        c = r.s[r.i]
        r.i += 1
        c == UInt8(']') && return out
        c == UInt8(',') || _json_fail(r, "Expected ',' or ']' in a JSON array")
    end
end

@inline function _hex4(r::_JSONReader, at::Int)
    at + 3 <= r.n || _json_fail(r, "A \\u escape is cut short")
    v = 0
    for k in 0:3
        c = r.s[at+k]
        d = UInt8('0') <= c <= UInt8('9') ? c - UInt8('0') :
            UInt8('a') <= c <= UInt8('f') ? c - UInt8('a') + 10 :
            UInt8('A') <= c <= UInt8('F') ? c - UInt8('A') + 10 : _json_fail(r, "A \\u escape needs four hex digits")
        v = v * 16 + d
    end
    return v
end

function _read_string(r::_JSONReader)
    s = r.s
    i = r.i + 1
    start = i
    # The common case: no escapes, copied in one go.
    @inbounds while i <= r.n
        c = s[i]
        c == UInt8('"') && (r.i = i + 1; return String(s[start:i-1]))
        c == UInt8('\\') && break
        c < 0x20 && _json_fail(r, "A control character inside a JSON string")
        i += 1
    end
    io = IOBuffer()
    write(io, view(s, start:i-1))
    @inbounds while i <= r.n
        c = s[i]
        if c == UInt8('"')
            r.i = i + 1
            return String(take!(io))
        elseif c == UInt8('\\')
            i + 1 <= r.n || break
            e = s[i+1]
            if e == UInt8('"') || e == UInt8('\\') || e == UInt8('/')
                write(io, e)
                i += 2
            elseif e == UInt8('b')
                write(io, UInt8('\b')); i += 2
            elseif e == UInt8('f')
                write(io, UInt8('\f')); i += 2
            elseif e == UInt8('n')
                write(io, UInt8('\n')); i += 2
            elseif e == UInt8('r')
                write(io, UInt8('\r')); i += 2
            elseif e == UInt8('t')
                write(io, UInt8('\t')); i += 2
            elseif e == UInt8('u')
                u = _hex4(r, i + 2)
                i += 6
                if 0xd800 <= u <= 0xdbff && i + 5 <= r.n && s[i] == UInt8('\\') && s[i+1] == UInt8('u')
                    lo = _hex4(r, i + 2)
                    if 0xdc00 <= lo <= 0xdfff
                        u = 0x10000 + ((u - 0xd800) << 10) + (lo - 0xdc00)
                        i += 6
                    end
                end
                # A lone surrogate is kept as the replacement character.
                write(io, (0xd800 <= u <= 0xdfff) ? '�' : Char(u))
            else
                r.i = i
                _json_fail(r, "An unknown escape in a JSON string")
            end
        else
            c < 0x20 && (r.i = i; _json_fail(r, "A control character inside a JSON string"))
            write(io, c)
            i += 1
        end
    end
    r.i = i
    _json_fail(r, "A JSON string is not closed")
end

function _read_number(r::_JSONReader)
    s = r.s
    start = r.i
    i = start
    i <= r.n && s[i] == UInt8('-') && (i += 1)
    integer = true
    @inbounds while i <= r.n
        c = s[i]
        if UInt8('0') <= c <= UInt8('9')
            i += 1
        elseif c == UInt8('.') || c == UInt8('e') || c == UInt8('E') || c == UInt8('+') || c == UInt8('-')
            integer = false
            i += 1
        else
            break
        end
    end
    r.i = i
    text = String(s[start:i-1])
    if integer
        v = tryparse(Int64, text)
        v !== nothing && return v
    end
    v = tryparse(Float64, text)
    if v === nothing
        # Past the range of a double: JavaScript reads it as Infinity (or 0).
        occursin(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$", text) || _json_fail(r, "'$text' is not a JSON number")
        v = Float64(parse(BigFloat, text))
    end
    return v
end

"""
    parse_json(text) -> Any

JSON text as Julia values: objects as ordered `JDict`s, arrays as
`Vector{Any}`, `null` as `nothing`, numbers as `Int64` or `Float64`.
"""
function parse_json(bytes::AbstractVector{UInt8})
    s = bytes isa Vector{UInt8} ? bytes : Vector{UInt8}(bytes)
    r = _JSONReader(s, 1, length(s))
    # A byte-order mark is not part of the text.
    if r.n >= 3 && s[1] == 0xef && s[2] == 0xbb && s[3] == 0xbf
        r.i = 4
    end
    v = _read_value(r, 0)
    _skip_ws!(r)
    r.i <= r.n && _json_fail(r, "Unexpected text after the JSON value")
    return v
end
parse_json(text::AbstractString) = parse_json(Vector{UInt8}(codeunits(String(text))))
