# What the Ecolego importer takes from the rest of Kompartment, and the rules
# of JavaScript (and of Python) it leans on. A port of the Python package's
# `kompartment/importers/_eco_maps.py`; private to `importers/eco.jl`.
#
# Two kinds of thing:
#
# * The small mappers the application's `src/io/eco.js` imports from other
#   modules: how Ecolego spells an interpolation rule, a reduction, an extreme
#   and an event direction; the solvers' names; the length of a year; what each
#   kind of block is called.
#
# * The language rules the importer's output depends on: `Number('')` is 0,
#   `trim()` and `\s` know their own set of spaces, a string's length counts
#   UTF-16 code units, an object lists its integer-like keys first,
#   `localeCompare` sorts by the Unicode collation, a plain object answers
#   `constructor`, `toPrecision` rounds a tie away from zero -- and, since the
#   reference is the Python port, Python's own `str.lower()` and `str.upper()`
#   where it reads file text through them.

# --- strings ---------------------------------------------------------------------------

# What JavaScript's `trim()`, `\s` and `Number()` count as white space: the
# WhiteSpace and LineTerminator code points.
@inline function _eco_is_js_space(c::Char)
    if c <= '\x7f'
        return c == ' ' || ('\t' <= c <= '\r')
    end
    return c == ' ' || c == ' ' || (' ' <= c <= ' ') || c == ' ' || c == ' ' ||
           c == ' ' || c == ' ' || c == '　' || c == '﻿'
end

# Whether the bytes from `i` begin with one of the JavaScript spaces; returns
# the number of bytes it takes (0 when none). ASCII is checked by the caller.
@inline function _eco_js_space_bytes(cu, i::Int, n::Int)
    b = @inbounds cu[i]
    if b < 0x80
        return (b == 0x20 || (0x09 <= b <= 0x0d)) ? 1 : 0
    end
    if b == 0xc2
        return (i + 1 <= n && @inbounds(cu[i+1]) == 0xa0) ? 2 : 0
    elseif b == 0xe1
        return (i + 2 <= n && @inbounds(cu[i+1]) == 0x9a && @inbounds(cu[i+2]) == 0x80) ? 3 : 0
    elseif b == 0xe2
        i + 2 <= n || return 0
        b1 = @inbounds cu[i+1]
        b2 = @inbounds cu[i+2]
        if b1 == 0x80
            return ((0x80 <= b2 <= 0x8a) || b2 == 0xa8 || b2 == 0xa9 || b2 == 0xaf) ? 3 : 0
        elseif b1 == 0x81
            return b2 == 0x9f ? 3 : 0
        end
        return 0
    elseif b == 0xe3
        return (i + 2 <= n && @inbounds(cu[i+1]) == 0x80 && @inbounds(cu[i+2]) == 0x80) ? 3 : 0
    elseif b == 0xef
        return (i + 2 <= n && @inbounds(cu[i+1]) == 0xbb && @inbounds(cu[i+2]) == 0xbf) ? 3 : 0
    end
    return 0
end

# The bytes `a..b` of a string's code units less JavaScript's white space at
# either end: the range that is left (empty when `b < a`).
function _eco_js_trim_range(cu, a::Int, b::Int)
    while a <= b
        k = _eco_js_space_bytes(cu, a, b)
        k == 0 && break
        a += k
    end
    while b >= a
        # the start of the character ending at `b`
        s0 = b
        while s0 > a && (@inbounds(cu[s0]) & 0xc0) == 0x80
            s0 -= 1
        end
        _eco_js_space_bytes(cu, s0, b) == b - s0 + 1 || break
        b = s0 - 1
    end
    return a, b
end

"""`text.trim()`, with JavaScript's idea of white space."""
function _eco_js_trim(s::AbstractString)
    str = String(s)
    n = ncodeunits(str)
    n == 0 && return str
    cu = codeunits(str)
    a, b = _eco_js_trim_range(cu, 1, n)
    b < a && return ""
    (a == 1 && b == n) && return str
    return String(view(cu, a:b))
end
_eco_js_trim(::Nothing) = ""

"""`text.trim()` of part of a string, as a view of it: no copy."""
function _eco_js_trim_sub(s::SubString{String})
    str = s.string
    a = s.offset + 1
    b = s.offset + s.ncodeunits
    a, b = _eco_js_trim_range(codeunits(str), a, b)
    b < a && return SubString(str, 1, 0)
    return SubString(str, a, thisind(str, b))
end
_eco_js_trim_sub(s::String) = _eco_js_trim_sub(SubString(s))

"""`text.length`: UTF-16 code units, so a character outside the Basic
Multilingual Plane counts twice."""
function _eco_js_len(s::AbstractString)
    n = 0
    for c in s
        n += c > '￿' ? 2 : 1
    end
    return n
end

"""How many UTF-16 code units the bytes of `s` before byte `i` hold: a
position as JavaScript numbers it."""
function _eco_utf16_pos(s::String, i::Int)
    n = 0
    k = 1
    stop = min(i, ncodeunits(s) + 1)
    while k < stop
        c = s[k]
        n += c > '￿' ? 2 : 1
        k = nextind(s, k)
    end
    return n
end

"""`text.replace(/[^A-Za-z0-9_]/g, '_')`: on UTF-16 code units, so a
character outside the Basic Multilingual Plane becomes two underscores."""
function _eco_js_identifier(s::AbstractString)
    io = IOBuffer(sizehint=ncodeunits(s))
    for c in s
        if ('A' <= c <= 'Z') || ('a' <= c <= 'z') || ('0' <= c <= '9') || c == '_'
            write(io, c)
        else
            write(io, c > '￿' ? "__" : "_")
        end
    end
    return String(take!(io))
end

_eco_is_ascii_digit(c::Char) = '0' <= c <= '9'
_eco_is_ident_char(b::UInt8) = (0x41 <= b <= 0x5a) || (0x61 <= b <= 0x7a) || (0x30 <= b <= 0x39) || b == 0x5f
_eco_is_name_part(b::UInt8) = _eco_is_ident_char(b) || b == 0x2e

"""Whether `s` equals the ASCII word `w` with ASCII letters compared
regardless of case: `re.fullmatch(w, s, re.I | re.A)` for a plain word."""
function _eco_ascii_ieq(s::AbstractString, w::AbstractString)
    ncodeunits(s) == ncodeunits(w) || return false
    a, b = codeunits(s), codeunits(w)
    @inbounds for k in 1:length(a)
        x, y = a[k], b[k]
        (0x41 <= x <= 0x5a) && (x += 0x20)
        (0x41 <= y <= 0x5a) && (y += 0x20)
        x == y || return false
    end
    return true
end

# --- Python's str.lower() and str.upper() -------------------------------------------------
#
# Python maps case with Unicode's full mappings: `'straße'.upper()` is
# `STRASSE`, `'ﬆ'.upper()` is `ST`, `'İ'.lower()` is `i̇`, and a capital
# sigma at the end of a word lowers to `ς`. Julia's `uppercase` and
# `lowercase` map one character to one; the full mappings are added here.

const _ECO_UPPER_MULTI = Dict{Char,String}(Char(k) => v for (k, v) in (
    0x00DF => "\u0053\u0053", 0x0149 => "\u02BC\u004E", 0x01F0 => "\u004A\u030C",
    0x0390 => "\u0399\u0308\u0301", 0x03B0 => "\u03A5\u0308\u0301", 0x0587 => "\u0535\u0552",
    0x1E96 => "\u0048\u0331", 0x1E97 => "\u0054\u0308", 0x1E98 => "\u0057\u030A", 0x1E99 => "\u0059\u030A",
    0x1E9A => "\u0041\u02BE", 0x1F50 => "\u03A5\u0313", 0x1F52 => "\u03A5\u0313\u0300",
    0x1F54 => "\u03A5\u0313\u0301", 0x1F56 => "\u03A5\u0313\u0342", 0x1F80 => "\u1F08\u0399",
    0x1F81 => "\u1F09\u0399", 0x1F82 => "\u1F0A\u0399", 0x1F83 => "\u1F0B\u0399",
    0x1F84 => "\u1F0C\u0399", 0x1F85 => "\u1F0D\u0399", 0x1F86 => "\u1F0E\u0399",
    0x1F87 => "\u1F0F\u0399", 0x1F88 => "\u1F08\u0399", 0x1F89 => "\u1F09\u0399",
    0x1F8A => "\u1F0A\u0399", 0x1F8B => "\u1F0B\u0399", 0x1F8C => "\u1F0C\u0399",
    0x1F8D => "\u1F0D\u0399", 0x1F8E => "\u1F0E\u0399", 0x1F8F => "\u1F0F\u0399",
    0x1F90 => "\u1F28\u0399", 0x1F91 => "\u1F29\u0399", 0x1F92 => "\u1F2A\u0399",
    0x1F93 => "\u1F2B\u0399", 0x1F94 => "\u1F2C\u0399", 0x1F95 => "\u1F2D\u0399",
    0x1F96 => "\u1F2E\u0399", 0x1F97 => "\u1F2F\u0399", 0x1F98 => "\u1F28\u0399",
    0x1F99 => "\u1F29\u0399", 0x1F9A => "\u1F2A\u0399", 0x1F9B => "\u1F2B\u0399",
    0x1F9C => "\u1F2C\u0399", 0x1F9D => "\u1F2D\u0399", 0x1F9E => "\u1F2E\u0399",
    0x1F9F => "\u1F2F\u0399", 0x1FA0 => "\u1F68\u0399", 0x1FA1 => "\u1F69\u0399",
    0x1FA2 => "\u1F6A\u0399", 0x1FA3 => "\u1F6B\u0399", 0x1FA4 => "\u1F6C\u0399",
    0x1FA5 => "\u1F6D\u0399", 0x1FA6 => "\u1F6E\u0399", 0x1FA7 => "\u1F6F\u0399",
    0x1FA8 => "\u1F68\u0399", 0x1FA9 => "\u1F69\u0399", 0x1FAA => "\u1F6A\u0399",
    0x1FAB => "\u1F6B\u0399", 0x1FAC => "\u1F6C\u0399", 0x1FAD => "\u1F6D\u0399",
    0x1FAE => "\u1F6E\u0399", 0x1FAF => "\u1F6F\u0399", 0x1FB2 => "\u1FBA\u0399",
    0x1FB3 => "\u0391\u0399", 0x1FB4 => "\u0386\u0399", 0x1FB6 => "\u0391\u0342",
    0x1FB7 => "\u0391\u0342\u0399", 0x1FBC => "\u0391\u0399", 0x1FC2 => "\u1FCA\u0399",
    0x1FC3 => "\u0397\u0399", 0x1FC4 => "\u0389\u0399", 0x1FC6 => "\u0397\u0342",
    0x1FC7 => "\u0397\u0342\u0399", 0x1FCC => "\u0397\u0399", 0x1FD2 => "\u0399\u0308\u0300",
    0x1FD3 => "\u0399\u0308\u0301", 0x1FD6 => "\u0399\u0342", 0x1FD7 => "\u0399\u0308\u0342",
    0x1FE2 => "\u03A5\u0308\u0300", 0x1FE3 => "\u03A5\u0308\u0301", 0x1FE4 => "\u03A1\u0313",
    0x1FE6 => "\u03A5\u0342", 0x1FE7 => "\u03A5\u0308\u0342", 0x1FF2 => "\u1FFA\u0399",
    0x1FF3 => "\u03A9\u0399", 0x1FF4 => "\u038F\u0399", 0x1FF6 => "\u03A9\u0342",
    0x1FF7 => "\u03A9\u0342\u0399", 0x1FFC => "\u03A9\u0399", 0xFB00 => "\u0046\u0046",
    0xFB01 => "\u0046\u0049", 0xFB02 => "\u0046\u004C", 0xFB03 => "\u0046\u0046\u0049",
    0xFB04 => "\u0046\u0046\u004C", 0xFB05 => "\u0053\u0054", 0xFB06 => "\u0053\u0054", 0xFB13 => "\u0544\u0546",
    0xFB14 => "\u0544\u0535", 0xFB15 => "\u0544\u053B", 0xFB16 => "\u054E\u0546", 0xFB17 => "\u0544\u053D",
))

_eco_isascii_str(s::AbstractString) = all(<(0x80), codeunits(s))

"""`s.upper()` as Python maps it."""
function _eco_py_upper(s::AbstractString)
    _eco_isascii_str(s) && return uppercase(String(s))
    io = IOBuffer()
    for c in s
        m = get(_ECO_UPPER_MULTI, c, nothing)
        m === nothing ? write(io, uppercase(c)) : write(io, m)
    end
    return String(take!(io))
end

# Python's `_PyUnicode_IsCased` and `_PyUnicode_IsCaseIgnorable`, near enough:
# what decides whether a capital sigma ends a word.
function _eco_is_cased(c::Char)
    isuppercase(c) || islowercase(c) ||
        Base.Unicode.category_code(c) == Base.Unicode.UTF8PROC_CATEGORY_LT
end
function _eco_is_case_ignorable(c::Char)
    c in ('\'', '.', ':', '^', '`', '¨', '­', '¯', '´', '·', '¸', '‘', '’',
          '․', '‧') && return true
    cat = Base.Unicode.category_code(c)
    return cat == Base.Unicode.UTF8PROC_CATEGORY_MN || cat == Base.Unicode.UTF8PROC_CATEGORY_ME ||
           cat == Base.Unicode.UTF8PROC_CATEGORY_CF || cat == Base.Unicode.UTF8PROC_CATEGORY_LM ||
           cat == Base.Unicode.UTF8PROC_CATEGORY_SK
end

"""`s.lower()` as Python maps it."""
function _eco_py_lower(s::AbstractString)
    _eco_isascii_str(s) && return lowercase(String(s))
    chars = collect(s)
    io = IOBuffer()
    for (k, c) in enumerate(chars)
        if c == 'İ'
            write(io, "i̇")
        elseif c == 'Σ'
            # Final_Sigma: a cased letter before (case-ignorables skipped), and
            # none after.
            j = k - 1
            while j >= 1 && _eco_is_case_ignorable(chars[j])
                j -= 1
            end
            final = j >= 1 && _eco_is_cased(chars[j])
            if final && k < length(chars)
                j = k + 1
                while j <= length(chars) && _eco_is_case_ignorable(chars[j])
                    j += 1
                end
                final = j > length(chars) || !_eco_is_cased(chars[j])
            end
            write(io, final ? 'ς' : 'σ')
        else
            write(io, lowercase(c))
        end
    end
    return String(take!(io))
end

# --- numbers --------------------------------------------------------------------------------

# A decimal literal as JavaScript reads one: `[+-]?(Infinity|digits[.digits]|.digits)(e[+-]digits)?`.
_eco_is_js_decimal(s::AbstractString) = _eco_is_js_decimal(codeunits(s))
function _eco_is_js_decimal(cu::AbstractVector{UInt8})
    n = length(cu)
    i = 1
    n == 0 && return false
    (cu[i] == UInt8('+') || cu[i] == UInt8('-')) && (i += 1)
    i > n && return false
    if n - i + 1 == 8 && cu[i] == UInt8('I') && view(cu, i:n) == codeunits("Infinity")
        return true
    end
    d1 = 0
    while i <= n && 0x30 <= cu[i] <= 0x39
        i += 1; d1 += 1
    end
    d2 = 0
    if i <= n && cu[i] == UInt8('.')
        i += 1
        while i <= n && 0x30 <= cu[i] <= 0x39
            i += 1; d2 += 1
        end
    end
    d1 + d2 == 0 && return false
    if i <= n && (cu[i] == UInt8('e') || cu[i] == UInt8('E'))
        i += 1
        i <= n && (cu[i] == UInt8('+') || cu[i] == UInt8('-')) && (i += 1)
        d3 = 0
        while i <= n && 0x30 <= cu[i] <= 0x39
            i += 1; d3 += 1
        end
        d3 == 0 && return false
    end
    return i > n
end

# `float(s)` for a decimal literal: the nearest double, infinity past the
# range and zero below it.
function _eco_parse_decimal(s::AbstractString)
    cu = codeunits(s)
    (!isempty(cu) && cu[end] == UInt8('y')) && return cu[1] == UInt8('-') ? -Inf : Inf    # ...Infinity
    v = tryparse(Float64, s)
    v !== nothing && return v
    # Out of range: what the C library makes of it, as Python's float does.
    str = String(s)
    return ccall(:strtod, Cdouble, (Cstring, Ptr{Ptr{UInt8}}), str, C_NULL)
end

# `int(digits, base)` in Python: the base's prefix may lead, and every
# character must be a digit of the base. `nothing` where Python raises.
function _eco_py_int(digits::AbstractString, base::Int)
    s = String(digits)
    if ncodeunits(s) >= 2 && s[1] == '0'
        p = lowercase(s[2])
        if (base == 16 && p == 'x') || (base == 8 && p == 'o') || (base == 2 && p == 'b')
            s = s[3:end]
        end
    end
    isempty(s) && return nothing
    for c in s
        v = ('0' <= c <= '9') ? c - '0' : ('a' <= c <= 'z') ? c - 'a' + 10 : ('A' <= c <= 'Z') ? c - 'A' + 10 : 99
        v < base || return nothing
    end
    return parse(BigInt, s; base=base)
end

"""
    _eco_to_number(v) -> Float64

JavaScript's `Number(v)` as the importer's Python port reads it: `nothing`
(null), `""` and nothing but spaces are 0; a decimal literal, `Infinity`
with an optional sign, or an unsigned `0x`/`0o`/`0b` integer; anything else
NaN.
"""
_eco_to_number(::Nothing) = 0.0
_eco_to_number(v::Bool) = v ? 1.0 : 0.0
_eco_to_number(v::Real) = Float64(v)
function _eco_to_number(v::AbstractString)
    s = _eco_js_trim(v)
    isempty(s) && return 0.0
    _eco_is_js_decimal(s) && return _eco_parse_decimal(s)
    cu = codeunits(s)
    if length(cu) >= 3 && cu[1] == UInt8('0') && cu[2] in codeunits("xXoObB") &&
       all(b -> _eco_is_ident_char(b) && b != UInt8('_'), view(cu, 3:length(cu)))
        base = cu[2] in codeunits("xX") ? 16 : cu[2] in codeunits("oO") ? 8 : 2
        whole = _eco_py_int(s[3:end], base)
        whole === nothing && return NaN
        return Float64(whole)
    end
    return NaN
end
_eco_to_number(v) = NaN

"""`Number.isFinite(v)`: a number, and neither infinite nor NaN."""
_eco_is_finite(v) = v isa Real && !(v isa Bool) && isfinite(v)

"""`Math.round(x)`: halves go up, towards positive infinity."""
function _eco_js_round(x::Real)
    f = Float64(x)
    isfinite(f) || return f
    r = floor(f)
    f - r >= 0.5 && (r += 1)
    return r
end

"""`Math.floor(x)`."""
_eco_js_floor(x::Real) = (f = Float64(x); isfinite(f) ? floor(f) : f)

"""`String(x)` for what the importer writes into its messages."""
function _eco_js_string(x)
    x === nothing && return "null"
    x isa Bool && return x ? "true" : "false"
    if x isa Real
        f = Float64(x)
        isnan(f) && return "NaN"
        isinf(f) && return f > 0 ? "Infinity" : "-Infinity"
        return js_number(f)
    end
    return string(x)
end

# The exact decimal digits of a positive finite double, and the exponent of
# the first of them: `x = d1.d2d3... × 10^adjusted`.
function _eco_exact_decimal(x::Float64)
    sig = significand(x)                     # in [1, 2)
    e = exponent(x)
    m = BigInt(ldexp(sig, 52))               # the 53-bit integer significand (or fewer for subnormals)
    p = e - 52
    if p >= 0
        digits = string(m << p)
        return digits, length(digits) - 1
    end
    digits = string(m * big(5)^(-p))
    return digits, length(digits) - 1 + p
end

"""`Number(x.toPrecision(digits))`: the double's exact value rounded, a tie
away from zero (Python's `Decimal.quantize` with `ROUND_HALF_UP`)."""
function _eco_round_significant(x::Real, digits::Int)
    f = Float64(x)
    (f == 0 || !isfinite(f)) && return f
    d, adjusted = _eco_exact_decimal(abs(f))
    keep = d[1:min(digits, length(d))]
    up = length(d) > digits && d[digits+1] >= '5'
    kept = parse(BigInt, keep)
    kept = up ? kept + 1 : kept
    # value = kept × 10^(adjusted - digits + 1), as written for the parser
    exp10 = adjusted - length(keep) + 1
    v = _eco_parse_decimal(string(kept) * "e" * string(exp10))
    return f < 0 ? -v : v
end

"""`x.toExponential()`: the shortest digits that read back as `x`, written
`1.5e+7`."""
function _eco_to_exponential(x::Real)
    f = Float64(x)
    isfinite(f) || return _eco_js_string(f)
    f == 0 && return "0e+0"
    sign = f < 0 ? "-" : ""
    digits, n = shortest_digits(abs(f))
    e = n - 1
    mant = length(digits) == 1 ? digits : string(digits[1], '.', digits[2:end])
    return string(sign, mant, 'e', e >= 0 ? '+' : '-', abs(e))
end

# --- dates ------------------------------------------------------------------------------------

"""`new Date(ms).toISOString().slice(0, 10)`; `ArgumentError("Invalid time
value")` past what a `Date` holds, where JavaScript raises a `RangeError`
(Python a `ValueError`)."""
function _eco_iso_date(ms::Real)
    f = Float64(ms)
    (!isfinite(f) || abs(f) > 8.64e15) && throw(ArgumentError("Invalid time value"))
    t = trunc(Int, f)
    days = fld(t, 86400000)
    y, m, d = _eco_civil_from_days(days)
    year = 0 <= y <= 9999 ? lpad(string(y), 4, '0') : string(y > 0 ? '+' : '-', lpad(string(abs(y)), 6, '0'))
    s = string(year, '-', lpad(string(m), 2, '0'), '-', lpad(string(d), 2, '0'))
    return first(s, 10)
end

function _eco_civil_from_days(z::Int)
    z += 719468
    era = fld(z, 146097)
    doe = z - era * 146097
    yoe = fld(doe - fld(doe, 1460) + fld(doe, 36524) - fld(doe, 146096), 365)
    y = yoe + era * 400
    doy = doe - (365 * yoe + fld(yoe, 4) - fld(yoe, 100))
    mp = fld(5 * doy + 2, 153)
    d = doy - fld(153 * mp + 2, 5) + 1
    m = mp < 10 ? mp + 3 : mp - 9
    return y + (m <= 2 ? 1 : 0), m, d
end

# --- objects ----------------------------------------------------------------------------------

function _eco_is_array_index(k::AbstractString)
    cu = codeunits(k)
    isempty(cu) && return false
    length(cu) > 1 && cu[1] == UInt8('0') && return false
    all(b -> 0x30 <= b <= 0x39, cu) || return false
    length(cu) > 10 && return false
    return parse(Int, k) <= 4294967294
end

"""`d` with its keys in the order a JavaScript object lists them: the
integer-like ones (0 to 2^32 - 2) first, in numeric order, then the rest in
the order they were added."""
function _eco_js_object_order(d::AbstractDict)
    ints = [k for k in keys(d) if _eco_is_array_index(k)]
    isempty(ints) && return d
    out = JDict()
    for k in sort(ints; by=k -> parse(Int, k))
        out[k] = d[k]
    end
    for (k, v) in d
        haskey(out, k) || (out[k] = v)
    end
    return out
end

"""What a plain JavaScript object answers for a key it inherits from
`Object.prototype`: `constructor`, `toString` and the rest are functions,
`__proto__` the prototype itself. JSON leaves a function out of an object
(`null` in an array) and writes the prototype as `{}`; see
[`_eco_json_ready!`](@ref)."""
struct _EcoInherited
    key::String
    is_function::Bool
end

const _ECO_PROTOTYPE_MEMBERS = Dict{String,_EcoInherited}(
    k => _EcoInherited(k, k != "__proto__") for k in (
        "constructor", "__defineGetter__", "__defineSetter__", "hasOwnProperty", "__lookupGetter__",
        "__lookupSetter__", "isPrototypeOf", "propertyIsEnumerable", "toString", "valueOf", "__proto__",
        "toLocaleString"))

"""`table[key]` where `table` is a plain JavaScript object: its own value,
or what every object inherits, or `nothing`."""
function _eco_plain_lookup(table::AbstractDict, key::AbstractString)
    v = get(table, key, nothing)
    v !== nothing && return v
    return get(_ECO_PROTOTYPE_MEMBERS, key, nothing)
end

"""`value` as `JSON.stringify` would see it, changed in place."""
function _eco_json_ready!(value)
    if value isa _EcoInherited
        return value.is_function ? nothing : JDict()
    elseif value isa AbstractDict
        for k in collect(keys(value))
            v = value[k]
            if v isa _EcoInherited && v.is_function
                delete!(value, k)
            else
                value[k] = _eco_json_ready!(v)
            end
        end
        return value
    elseif value isa AbstractVector{<:Number}
        return value
    elseif value isa AbstractVector
        for i in eachindex(value)
            value[i] = _eco_json_ready!(value[i])
        end
        return value
    end
    return value
end

# --- localeCompare --------------------------------------------------------------------------

"""A sort key that orders names as `a.localeCompare(b)` does in Node, for
what an index list can be called: underscore before digits before letters,
case ignored until everything else is equal, then lower case before upper."""
function _eco_collation_key(text::AbstractString)
    primary = Int[]
    tertiary = Int[]
    for c in text
        o = Int(c)
        if c == '_'
            push!(primary, 1)
        elseif 48 <= o <= 57
            push!(primary, 2 + o - 48)
        elseif 97 <= o <= 122
            push!(primary, 12 + o - 97)
        elseif 65 <= o <= 90
            push!(primary, 12 + o - 65)
        else
            push!(primary, 100 + o)
        end
        push!(tertiary, 65 <= o <= 90 ? 1 : 0)
    end
    return (primary, tertiary)
end

# --- the mappers eco.js imports -----------------------------------------------------------

"""Seconds per year: this tool's year, the Julian one of 365.25 days."""
const _ECO_SECONDS_PER_YEAR = 365.25 * 24 * 3600

"""Seconds per year as Ecolego's `year` unit has it, 365.2425 days."""
const _ECO_ECOLEGO_YEAR = 31556952

"""How many seconds a year of half-life is in an .eco file whose model runs in
`unit`: this tool's year for a model in days or anything shorter, Ecolego's
for one in years."""
_eco_seconds_per_year(unit) = unit in ("minute", "second", "hour", "day") ? _ECO_SECONDS_PER_YEAR :
                              Float64(_ECO_ECOLEGO_YEAR)

const _ECO_INTERPOLATION_FROM_ECO = Dict{String,Any}(
    "Interpolation-Use End Values" => "linear",
    "Interpolation-Extrapolation" => "extrapolate",
    "Use Input Below" => "below",
    "Use Input Above" => "above",
    "Use Input Nearest" => "nearest",
)

"""A lookup table's interpolation rule from Ecolego's `<lookup-option>`, or
`nothing`; a name a plain object inherits comes back as an `_EcoInherited`."""
_eco_interpolation_from_eco(name) =
    _eco_plain_lookup(_ECO_INTERPOLATION_FROM_ECO, _eco_js_trim(name === nothing ? "" : string(name)))

const _ECO_OPERATION_FROM_ECO = Dict{String,String}(
    "SUM" => "sum", "PRODUCT" => "product", "MIN" => "min", "MAX" => "max", "MEAN" => "mean",
    "PERCENTILE" => "percentile",
    "Sum" => "sum", "Product" => "product", "Minimum" => "min", "Maximum" => "max", "Mean" => "mean",
    "Percentile" => "percentile",
)

"""An index operation's or aggregate's reduction from Ecolego's `<operation>`."""
_eco_operation_from_eco(name) = get(_ECO_OPERATION_FROM_ECO, _eco_js_trim(name === nothing ? "" : string(name)), nothing)

"""The recorder kinds, by Ecolego's block type."""
const _ECO_KIND_FROM_ECO = Dict{String,String}(
    "min-max" => "min_max",
    "running-mean" => "running_mean",
    "snapshot" => "snapshot",
    "delay" => "delay",
    "discrete-event" => "trigger",
)

"""Which of a recorder's fields name a discrete event."""
const _ECO_EVENT_FIELDS = Dict{String,Vector{String}}(
    "min_max" => ["reset_trigger", "start_trigger", "stop_trigger"],
    "running_mean" => ["reset_trigger", "start_trigger", "stop_trigger"],
    "snapshot" => ["trigger"],
    "delay" => String[],
    "trigger" => String[],
)

"""Which of a recorder's fields hold an equation."""
const _ECO_EQUATION_FIELDS = Dict{String,Vector{String}}(
    "min_max" => ["target"],
    "running_mean" => ["target"],
    "snapshot" => ["target", "initial"],
    "delay" => ["target", "delay"],
    "trigger" => ["first", "second"],
)

"""`"min"` or `"max"` from a min/max block's `<operation>`, or `nothing`."""
function _eco_extreme_from_eco(name)
    s = _eco_py_upper(_eco_js_trim(name === nothing ? "" : string(name)))
    return s == "MIN" ? "min" : s == "MAX" ? "max" : nothing
end

const _ECO_DIRECTION_FROM_ECO = Dict{String,Any}(
    "RIGHT" => "rising",
    "LEFT" => "falling",
    "BOTH" => "both",
    "->" => "rising",
    "<-" => "falling",
    ">-<" => "both",
)

"""A discrete event's direction from Ecolego's `<direction>`, or `nothing`:
upper-cased first and then as written, into a plain object."""
function _eco_direction_from_eco(name)
    s = _eco_js_trim(name === nothing ? "" : string(name))
    found = _eco_plain_lookup(_ECO_DIRECTION_FROM_ECO, _eco_py_upper(s))
    found === nothing && (found = _eco_plain_lookup(_ECO_DIRECTION_FROM_ECO, s))
    return found
end

"""Each solver's name in the interface (`SOLVER_INFO` in src/ode/solvers.js)."""
const _ECO_SOLVER_LABELS = Dict{String,String}(
    "ndf" => "stiff, NDF",
    "ros23" => "stiff, low order, Rosenbrock 2-3",
    "dp45" => "non-stiff, Dormand-Prince 4-5",
    "auto" => "stiff or non-stiff, switching as it runs",
    "auto_julia" => "stiff or non-stiff, as DifferentialEquations.jl chooses",
    "rodas5p" => "stiff, Rosenbrock 5",
    "radau5" => "stiff, Radau IIA 5",
    "fbdf" => "stiff, fixed-leading-coefficient BDF",
    "fbdf_krylov" => "stiff, FBDF by GMRES, no matrix",
    "qndf" => "stiff, quasi-constant-step NDF",
    "kencarp4" => "stiff, ESDIRK 4",
    "trbdf2" => "stiff, ESDIRK 2 (loose tolerances)",
    "rosenbrock23" => "stiff, low order, Rosenbrock 2-3 as in Julia",
    "tsit5" => "non-stiff, Tsitouras 5",
    "vern7" => "non-stiff, Verner 7",
    "scipy_bdf" => "SciPy BDF, stiff",
    "scipy_radau" => "SciPy Radau IIA, stiff",
    "scipy_lsoda" => "SciPy LSODA, auto-switching",
)

"""Both of a solver's names, `stiff, NDF (ndf)`; the id alone for one this
tool does not have."""
function _eco_solver_name(solver_id)
    label = solver_id isa AbstractString ? get(_ECO_SOLVER_LABELS, solver_id, nothing) : nothing
    return label !== nothing && !isempty(label) ? "$label ($solver_id)" : _eco_js_string(solver_id)
end

"""What each kind of block is called in the interface, in the plural."""
const _ECO_KIND_LABEL = Dict{String,String}(
    "compartment" => "Compartments",
    "transfer" => "Transfers",
    "inflow" => "Inflows",
    "expression" => "Expressions",
    "parameter" => "Parameters",
    "lookup" => "Lookup tables",
    "index_reduction" => "Reduce over an index",
    "block_reduction" => "Combine blocks",
    "function" => "Functions",
    "min_max" => "Min/max",
    "running_mean" => "Running means",
    "snapshot" => "Snapshots",
    "delay" => "Delays",
    "trigger" => "Triggers",
    "farfield" => "Far-field pathways",
    "waste_package" => "Waste packages",
    "event" => "Events",
    "farfield_inventory" => "Path inventories",
    "farfield_cell" => "Path cells",
    "waste_inventory" => "Package inventories",
)

"""Each collection's kind of block (`SINGULAR` in the Python package's blocks.py)."""
const _ECO_SINGULAR = Dict{String,String}(
    "compartments" => "compartment", "transfers" => "transfer", "inflows" => "inflow",
    "parameters" => "parameter", "expressions" => "expression", "lookups" => "lookup",
    "index_reductions" => "index_reduction", "block_reductions" => "block_reduction",
    "functions" => "function", "min_maxes" => "min_max", "running_means" => "running_mean",
    "snapshots" => "snapshot", "delays" => "delay", "triggers" => "trigger", "farfields" => "farfield",
    "waste_packages" => "waste_package", "events" => "event",
)
