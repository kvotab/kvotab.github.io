# A parameter's probability distribution as Ecolego writes it, read into the
# dictionary a model file stores: `parse_pdf` of the Python package's
# `kompartment/stats/pdf.py` (`parsePdf` in the application's
# src/domain/pdf.js), as far as the importer needs it.

# The kinds a distribution can be, in the order the application lists them:
# each with the name its expression is written with and its parameters.
const _ECO_PDF_KINDS = (
    ("unif", "unif", ("min", "max")),
    ("triang", "triang", ("min", "max", "mode")),
    ("dtriang", "dtriang", ("min", "max", "mode")),
    ("norm", "norm", ("mean", "sd")),
    ("logu", "logu", ("min", "max")),
    ("logt", "logt", ("min", "max", "mode")),
    ("logdt", "logdt", ("min", "max", "mode")),
    ("Logn4", "logn", ("gm", "gsd")),
    ("logn", "logn", ("mean", "sd")),
    ("logn5", "logn", ("p1", "x1", "p2", "x2")),
    ("pg", "pg", ()),
)

function _eco_pdf_meta(kind)
    kind isa AbstractString || return nothing
    for k in _ECO_PDF_KINDS
        k[1] == kind && return k
    end
    return nothing
end

# `Number(s)` for a string, as pdf.py reads one: a decimal literal (with
# `Infinity`), or `0x`, `0o`, `0b` digits of that base only; anything else
# NaN. On the bytes `a..b` of `str`, so that a list of a million values is
# read without a copy of each.
function _eco_pdf_number_range(str::String, a::Int, b::Int)
    cu = codeunits(str)
    a, b = _eco_js_trim_range(cu, a, b)
    b < a && return 0.0
    if b - a >= 2 && cu[a] == UInt8('0')
        p = cu[a+1]
        base = (p == UInt8('x') || p == UInt8('X')) ? 16 : (p == UInt8('o') || p == UInt8('O')) ? 8 :
               (p == UInt8('b') || p == UInt8('B')) ? 2 : 0
        if base != 0
            ok = true
            for k in a+2:b
                c = cu[k]
                v = (0x30 <= c <= 0x39) ? Int(c - 0x30) : (0x61 <= c <= 0x66) ? Int(c - 0x61 + 10) :
                    (0x41 <= c <= 0x46) ? Int(c - 0x41 + 10) : 99
                if v >= base
                    ok = false
                    break
                end
            end
            ok && return Float64(parse(BigInt, String(view(cu, a+2:b)); base=base))
        end
    end
    _eco_is_js_decimal(view(cu, a:b)) || return NaN
    return _eco_parse_decimal(SubString(str, a, b))
end
_eco_pdf_string_to_number(s::SubString{String}) =
    _eco_pdf_number_range(s.string, s.offset + 1, s.offset + s.ncodeunits)
_eco_pdf_string_to_number(s::String) = _eco_pdf_number_range(s, 1, ncodeunits(s))

# A number, or `nothing` for nothing, an empty string or what is not a finite number.
function _eco_pdf_num(v)
    (v === nothing || v == "") && return nothing
    n = _eco_pdf_string_to_number(v)
    return isfinite(n) ? n : nothing
end

# A name rather than a number (a correlation group's); `nothing` for nothing.
function _eco_pdf_token(v)
    v === nothing && return nothing
    t = _eco_js_trim_sub(v)
    return isempty(t) ? nothing : String(t)
end

# The first `byte` in the bytes `from..stop` of `str`, or 0.
function _eco_memchr_upto(str::String, byte::UInt8, from::Int, stop::Int)
    stop < from && return 0
    p = GC.@preserve str ccall(:memchr, Ptr{UInt8}, (Ptr{UInt8}, Cint, Csize_t),
                                pointer(str, from), byte, stop - from + 1)
    return p == C_NULL ? 0 : Int(p - pointer(str)) + 1
end

# `str[a..b]` as a view; empty when `b < a`.
_eco_sub(str::String, a::Int, b::Int) = b < a ? SubString(str, 1, 0) : SubString(str, a, thisind(str, b))

"""
    _eco_parse_pdf(expr, function_name="") -> Union{JDict,Nothing}

Reads Ecolego's expression into a distribution; `nothing` if it is not one.
`expr` is the `<pdf-value>` text, `logt(min=1,max=9,mode=3)`;
`function_name` the `function=` attribute, which names the kind (and tells
the three log-normals apart). A list's values are separated by `;`:
`pg(values=1;2;3,inorder=true,pos=0)`.
"""
function _eco_parse_pdf(expr, function_name="")
    text = _eco_js_trim(expr === nothing ? "" : string(expr))
    isempty(text) && return nothing
    # `name<spaces>(body)<spaces>` to the end: the text is trimmed, so it ends
    # with the closing bracket.
    cu = codeunits(text)
    n = length(cu)
    (_eco_is_alpha(cu[1]) || cu[1] == UInt8('_')) || return nothing
    k = 2
    while k <= n && _eco_is_ident_char(cu[k])
        k += 1
    end
    name = String(view(cu, 1:k-1))
    while k <= n
        sp = _eco_js_space_bytes(cu, k, n)
        sp == 0 && break
        k += sp
    end
    (k <= n && cu[k] == UInt8('(')) || return nothing
    (n >= k + 1 && cu[n] == UInt8(')')) || return nothing

    # Commas separate arguments; a list's own values are separated by `;`.
    args = Dict{String,SubString{String}}()
    bare = String[]
    p = k + 1                      # the body is bytes k+1 .. n-1
    stop = n - 1
    while true
        q = _eco_memchr_upto(text, UInt8(','), p, stop)
        e = q == 0 ? stop : q - 1  # this piece is p..e
        at = _eco_memchr_upto(text, UInt8('='), p, e)
        if at == 0
            word = _eco_js_trim_sub(_eco_sub(text, p, e))
            isempty(word) || push!(bare, String(word))
        else
            args[String(_eco_js_trim_sub(_eco_sub(text, p, at - 1)))] = _eco_js_trim_sub(_eco_sub(text, at + 1, e))
        end
        q == 0 && break
        p = q + 1
    end

    kind = _eco_pdf_meta(function_name) !== nothing ? String(function_name) : nothing
    if kind === nothing
        has(k) = haskey(args, k) || k in bare
        if name == "logn"
            kind = (has("gm") || has("gsd")) ? "Logn4" : (has("p1") || has("x1")) ? "logn5" : "logn"
        else
            for m in _ECO_PDF_KINDS
                if m[2] == name
                    kind = m[1]
                    break
                end
            end
        end
    end
    kind === nothing && return nothing

    pos = _eco_pdf_num(get(args, "pos", nothing))
    params = JDict()
    spec = JDict(
        "kind" => kind,
        "params" => params,
        "values" => nothing,
        "trmin" => _eco_pdf_num(get(args, "trmin", nothing)),
        "trmax" => _eco_pdf_num(get(args, "trmax", nothing)),
        "pmin" => _eco_pdf_num(get(args, "pmin", nothing)),
        "pmax" => _eco_pdf_num(get(args, "pmax", nothing)),
        "group" => _eco_pdf_token(get(args, "group", nothing)),
        "inorder" => get(args, "inorder", nothing) != "false",
        "pos" => pos !== nothing ? pos : 0,
    )
    for p in _eco_pdf_meta(kind)[3]
        params[p] = _eco_pdf_num(get(args, p, nothing))
    end
    if kind == "pg"
        raw = get(args, "values", nothing)
        # Plain numbers, which a list of sampled values has by the million.
        values = Float64[]
        if raw !== nothing && !isempty(raw)
            str = raw.string
            a = raw.offset + 1
            b = raw.offset + raw.ncodeunits
            sizehint!(values, count(==(UInt8(';')), view(codeunits(str), a:b)) + 1)
            while true
                q = _eco_memchr_upto(str, UInt8(';'), a, b)
                v = _eco_pdf_number_range(str, a, q == 0 ? b : q - 1)
                isfinite(v) && push!(values, v)
                q == 0 && break
                a = q + 1
            end
        end
        spec["values"] = values
    end
    return spec
end
