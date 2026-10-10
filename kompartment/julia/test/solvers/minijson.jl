# A small JSON reader for fixtures.json, so that the solver tests need no
# package beyond the standard library: objects become Dict{String,Any},
# arrays Vector{Any}, numbers Int or Float64, and strings String.

module MiniJSON

function parse_json(s::AbstractString)
    b = Vector{UInt8}(codeunits(s))
    v, i = _value(b, _skip(b, 1))
    i = _skip(b, i)
    i <= length(b) && error("trailing characters at $i")
    return v
end

function _skip(b, i)
    while i <= length(b) && (b[i] == UInt8(' ') || b[i] == UInt8('\n') || b[i] == UInt8('\r') || b[i] == UInt8('\t'))
        i += 1
    end
    return i
end

function _value(b, i)
    c = b[i]
    if c == UInt8('{')
        d = Dict{String,Any}()
        i = _skip(b, i + 1)
        if b[i] == UInt8('}')
            return d, i + 1
        end
        while true
            k, i = _string(b, _skip(b, i))
            i = _skip(b, i)
            b[i] == UInt8(':') || error("expected : at $i")
            v, i = _value(b, _skip(b, i + 1))
            d[k] = v
            i = _skip(b, i)
            if b[i] == UInt8(',')
                i = _skip(b, i + 1)
            elseif b[i] == UInt8('}')
                return d, i + 1
            else
                error("expected , or } at $i")
            end
        end
    elseif c == UInt8('[')
        a = Any[]
        i = _skip(b, i + 1)
        if b[i] == UInt8(']')
            return a, i + 1
        end
        while true
            v, i = _value(b, _skip(b, i))
            push!(a, v)
            i = _skip(b, i)
            if b[i] == UInt8(',')
                i += 1
            elseif b[i] == UInt8(']')
                return a, i + 1
            else
                error("expected , or ] at $i")
            end
        end
    elseif c == UInt8('"')
        return _string(b, i)
    elseif c == UInt8('t')
        return true, i + 4
    elseif c == UInt8('f')
        return false, i + 5
    elseif c == UInt8('n')
        return nothing, i + 4
    else
        j = i
        while j <= length(b) && (UInt8('0') <= b[j] <= UInt8('9') || b[j] in UInt8.(('-', '+', '.', 'e', 'E')))
            j += 1
        end
        t = String(b[i:j-1])
        v = any(ch -> ch in t, ('.', 'e', 'E')) ? parse(Float64, t) : parse(Int, t)
        return v, j
    end
end

function _string(b, i)
    b[i] == UInt8('"') || error("expected a string at $i")
    io = IOBuffer()
    i += 1
    while b[i] != UInt8('"')
        if b[i] == UInt8('\\')
            e = b[i+1]
            if e == UInt8('u')
                write(io, Char(parse(UInt16, String(b[i+2:i+5]); base=16)))
                i += 6
                continue
            end
            write(io, e == UInt8('n') ? '\n' : e == UInt8('t') ? '\t' : e == UInt8('r') ? '\r' :
                      e == UInt8('b') ? '\b' : e == UInt8('f') ? '\f' : Char(e))
            i += 2
        else
            write(io, b[i])
            i += 1
        end
    end
    return String(take!(io)), i + 1
end

end # module
