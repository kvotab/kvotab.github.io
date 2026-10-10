# Numbers as JavaScript reads and writes them.
#
# A model file is JSON written by JavaScript, and much of what a run reports
# (labels, the CSV export, messages) quotes numbers the way JavaScript's
# `String(x)` prints them: the shortest digits that read back as the same
# number -- which Julia's `repr` finds too -- laid out by JavaScript's rule,
# plain from 1e-6 up to 1e21 and exponential beyond (`0.000015`, `1e-7`,
# `1.5e+21`). Reading follows `Number(v)`: an empty string is 0, anything
# that is not a number is NaN.

"""
    shortest_digits(x) -> (digits, n)

The shortest decimal digits that round-trip to the positive finite `x`, and
the exponent `n` with `x = 0.digits × 10^n`.
"""
function shortest_digits(x::Float64)
    s = repr(x)                       # e.g. "1.2345e-7", "123.45", "1.0e21"
    e = 0
    k = findfirst(==('e'), s)
    if k !== nothing
        e = parse(Int, s[k+1:end])
        s = s[1:k-1]
    end
    dot = findfirst(==('.'), s)
    intpart = dot === nothing ? s : s[1:dot-1]
    frac = dot === nothing ? "" : s[dot+1:end]
    digits = intpart * frac
    n = length(intpart) + e           # value = 0.(intpart frac) × 10^(len(intpart)+e)
    # Strip leading zeros (each moves the point one place).
    lead = 0
    while lead < length(digits) - 1 && digits[lead+1] == '0'
        lead += 1
    end
    if lead > 0
        digits = digits[lead+1:end]
        n -= lead
    end
    # Strip trailing zeros.
    stop = length(digits)
    while stop > 1 && digits[stop] == '0'
        stop -= 1
    end
    return digits[1:stop], n
end

"""
    js_number(x) -> String

`x` as JavaScript's `String(x)` writes it; NaN and the infinities as `null`,
which is what `JSON.stringify` makes of them. Integers print as they are.
"""
js_number(x::Bool) = x ? "true" : "false"
js_number(x::Integer) = string(x)
function js_number(x::AbstractFloat)
    f = Float64(x)
    (isnan(f) || isinf(f)) && return "null"
    f == 0 && return "0"
    sign = f < 0 ? "-" : ""
    digits, n = shortest_digits(abs(f))
    k = length(digits)
    if k <= n <= 21
        return sign * digits * "0"^(n - k)
    elseif 0 < n <= 21
        return sign * digits[1:n] * "." * digits[n+1:end]
    elseif -6 < n <= 0
        return sign * "0." * "0"^(-n) * digits
    end
    e = n - 1
    mant = k == 1 ? digits : digits[1:1] * "." * digits[2:end]
    return sign * mant * "e" * (e >= 0 ? "+" : "-") * string(abs(e))
end

"""
    js_text(v) -> String

What JavaScript's `String(v)` makes of a value a model's JSON can hold, for
messages that quote what was written: `NaN`, `Infinity`, `null`, lists joined
by commas.
"""
function js_text(v)
    v === nothing && return "null"
    v isa Bool && return v ? "true" : "false"
    if v isa Real
        f = Float64(v)
        isnan(f) && return "NaN"
        isinf(f) && return f > 0 ? "Infinity" : "-Infinity"
        return js_number(v)
    end
    v isa AbstractVector && return join((x === nothing ? "" : js_text(x) for x in v), ",")
    v isa AbstractDict && return "[object Object]"
    return string(v)
end

"""
    js_str(v) -> String

`String(v)` for what a model file holds where an equation is expected:
strings as they are, numbers as JavaScript prints them.
"""
js_str(v::AbstractString) = String(v)
js_str(v::Bool) = v ? "true" : "false"
js_str(v::Real) = js_number(v)
js_str(::Nothing) = "null"
js_str(v) = string(v)

const _JS_SPACE = (' ', '\t', '\n', '\r', '\v', '\f', ' ', '﻿', ' ', ' ')

_js_strip(s::AbstractString) = strip(c -> c in _JS_SPACE || isspace(c), s)

"""
    js_number_of(v) -> Float64

JavaScript's `Number(v)` for what a model file can hold: `nothing` (null) and
`""` are 0, booleans 1 and 0, text that is not a number NaN.
"""
js_number_of(::Nothing) = 0.0
js_number_of(v::Bool) = v ? 1.0 : 0.0
js_number_of(v::Real) = Float64(v)
function js_number_of(v::AbstractString)
    s = _js_strip(v)
    isempty(s) && return 0.0
    low = lowercase(s)
    (low == "infinity" || low == "+infinity") && return Inf
    low == "-infinity" && return -Inf
    # Julia's parser takes "inf", "nan", "1_000", hex floats and so on, which
    # JavaScript does not; take only what Number() would.
    if occursin(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$", s)
        return parse(Float64, s)
    elseif occursin(r"^0[xX][0-9a-fA-F]+$", s)
        return Float64(parse(BigInt, s[3:end]; base=16))
    elseif occursin(r"^0[oO][0-7]+$", s)
        return Float64(parse(BigInt, s[3:end]; base=8))
    elseif occursin(r"^0[bB][01]+$", s)
        return Float64(parse(BigInt, s[3:end]; base=2))
    end
    return NaN
end
js_number_of(v::AbstractVector) = length(v) == 0 ? 0.0 : length(v) == 1 ? js_number_of(v[1]) : NaN
js_number_of(v) = NaN

"""
    js_truthy_switch(v, default) -> Bool

A switch as the application reads one from a file: on unless it says
`false`, `"false"` or 0 when the default is on; off unless it says `true`,
`"true"` or 1 when the default is off.
"""
function js_truthy_switch(v, default::Bool)
    if default
        return !(v === false || v == "false" || (v isa Real && !(v isa Bool) && v == 0))
    end
    return v === true || v == "true" || (v isa Real && !(v isa Bool) && v == 1)
end

"""
    round_half_up(x) -> Float64

`Math.floor(x + 0.5)`: the rounding the application applies to counts written
as numbers.
"""
round_half_up(x::Float64) = floor(x + 0.5)
