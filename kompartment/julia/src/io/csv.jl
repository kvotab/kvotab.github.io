# CSV as the application writes it, and the two conversions its writers share.
#
# A port of the Python package's `kompartment/io/csv.py` (itself a port of the
# application's `src/io/csv.js`): one rule -- quote a field that would
# otherwise be read as more than one -- and the two places that apply it, the
# header and the rows of a results table.
#
# A row is not quoted cell by cell: the numbers in it are written as
# JavaScript's `String(x)` writes them (`100000`, `1e-7`, `NaN`, `Infinity`)
# and joined with commas, and only the header's labels go through `csv_cell`.
# Every indexed output's label holds a comma (`Soil [Cs-137, Lake]`), which is
# why the header needs it and the numbers do not.
#
# The two conversions every file writer follows are here too: `js_string` is
# `String(value)` and `js_to_number` is `Number(value)`, exactly as the Python
# package has them. (`js_number_of` in util/jsnum.jl is close but not the same:
# it reads `infinity` in any case, takes `[true]` as 1 and strips U+0085; a
# file writer that has to match the Python package to the byte uses these.)

"""
JavaScript's WhiteSpace and LineTerminator characters, which `Number()` and
`trim()` strip. Not Julia's `isspace`: that takes U+0085 and leaves U+FEFF,
U+2028 and U+2029, and JavaScript does the opposite.
"""
const JS_WHITESPACE = "\t\n\v\f\r          " *
                      "        　﻿"

@inline function _csv_is_js_space(c::AbstractChar)
    c <= ' ' && return c == ' ' || '\t' <= c <= '\r'
    c < '\u00a0' && return false
    return c == '\u00a0' || c == '\u1680' || '\u2000' <= c <= '\u200a' || c == '\u2028' || c == '\u2029' ||
           c == '\u202f' || c == '\u205f' || c == '\u3000' || c == '\ufeff'
end

"""`s` with JavaScript's whitespace stripped from both ends (`s` itself when there is none)."""
function _csv_js_strip(s::AbstractString)
    isempty(s) && return s
    (_csv_is_js_space(first(s)) || _csv_is_js_space(last(s))) || return s
    return strip(_csv_is_js_space, s)
end

const _CSV_NEEDS_QUOTES = r"[\",\r\n]"
const _CSV_DECIMAL = r"\A[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\z"
const _CSV_NON_DECIMAL = r"\A0(?:[xX][0-9a-fA-F]+|[oO][0-7]+|[bB][01]+)\z"

"""
    is_js_boolean(v) -> Bool

Whether `v` is what JavaScript would call a boolean: `true` or `false`.
"""
is_js_boolean(v) = v isa Bool

function _csv_number_text(x::Float64)
    isnan(x) && return "NaN"
    isinf(x) && return x > 0 ? "Infinity" : "-Infinity"
    return js_number(x)
end

# The values of an array in the order JavaScript (and numpy's `tolist`) would
# list them: a matrix row by row.
_csv_c_order(v::AbstractVector) = v
_csv_c_order(v::Tuple) = v
_csv_c_order(v::AbstractArray{<:Any,0}) = [v[]]
_csv_c_order(v::AbstractArray) = vec(permutedims(v, ndims(v):-1:1))

"""
    js_string(value) -> String

`String(value)`: a value as JavaScript writes it as text.

A number is written as JavaScript writes it -- `100000`, `0.000015`, `1e-7`,
`1e+21`, `NaN`, `Infinity` -- an integer first becoming the double JavaScript
would hold. `nothing` is `null`, a boolean `true` or `false`, a vector (or
tuple, or array, row by row) its elements joined with commas (`nothing`
inside one written as nothing, as `Array.prototype.join` does), and a
dictionary `[object Object]`.
"""
js_string(::Nothing) = "null"
js_string(v::String) = v
js_string(v::AbstractString) = String(v)
js_string(v::AbstractChar) = string(v)
js_string(v::Bool) = v ? "true" : "false"
js_string(v::Integer) = _csv_number_text(Float64(v))
js_string(v::AbstractFloat) = _csv_number_text(Float64(v))
js_string(v::Real) = _csv_number_text(Float64(v))
js_string(v::Union{AbstractArray,Tuple}) = join((x === nothing ? "" : js_string(x) for x in _csv_c_order(v)), ",")
js_string(::AbstractDict) = "[object Object]"
js_string(v::Symbol) = String(v)
js_string(v) = string(v)

"""
`Number(s)` for a string: JavaScript's grammar, not Julia's. Julia's parser
takes `inf`, `nan` and `1_000`, which JavaScript reads as NaN, and refuses
`1e999` and `1e-400`, which JavaScript reads as Infinity and 0.
"""
function _csv_string_to_number(s::AbstractString)
    t = _csv_js_strip(s)
    isempty(t) && return 0.0
    if occursin(_CSV_NON_DECIMAL, t)
        c = codeunit(t, 2)
        base = (c == UInt8('x') || c == UInt8('X')) ? 16 : (c == UInt8('o') || c == UInt8('O')) ? 8 : 2
        return Float64(parse(BigInt, SubString(t, 3); base))
    end
    if occursin(_CSV_DECIMAL, t)
        endswith(t, "Infinity") && return codeunit(t, 1) == UInt8('-') ? -Inf : Inf
        x = tryparse(Float64, t)
        x === nothing || return x
        # Out of a double's range, where Julia refuses what Python and
        # JavaScript round: to the infinities, to zero, or to a subnormal.
        return setprecision(BigFloat, 4096) do
            Float64(parse(BigFloat, t))
        end
    end
    return NaN
end

"""
    js_to_number(value) -> Float64

`Number(value)`: a value as JavaScript turns it into a number.

`nothing` (JavaScript's `null`) is 0, a boolean 1 or 0, a string read by
JavaScript's own grammar (blank is 0, `0x10` is 16, `1_000` and `inf` are NaN),
a vector what its text reads as (`[]` is 0, `[5]` is 5, `[1, 2]` is NaN) and
anything else NaN.
"""
js_to_number(::Nothing) = 0.0
js_to_number(v::Bool) = v ? 1.0 : 0.0
js_to_number(v::Float64) = v
js_to_number(v::Integer) = Float64(v)
js_to_number(v::Real) = Float64(v)
js_to_number(v::AbstractString) = _csv_string_to_number(v)
js_to_number(v::AbstractChar) = _csv_string_to_number(string(v))
js_to_number(v::Union{AbstractArray,Tuple}) = _csv_string_to_number(js_string(v))
js_to_number(::AbstractDict) = NaN
js_to_number(v) = NaN

"""
    csv_cell(text) -> String

One CSV field, quoted when it has to be (`csvCell`): a field holding a comma,
a quote or a line break is put in quotes, and a quote inside it doubled
(RFC 4180). `nothing` is an empty field; any other value is first written as
`js_string` writes it.
"""
function csv_cell(text)
    s = text === nothing ? "" : js_string(text)
    return occursin(_CSV_NEEDS_QUOTES, s) ? "\"" * replace(s, "\"" => "\"\"") * "\"" : s
end

"""
    csv_row(values) -> String

One CSV line as the application joins a row, `row.join(',')`: each value as
`js_string` writes it and `nothing` as nothing, nothing quoted. This is how
the numbers of a table go out; the header, whose labels do need quoting, is
`csv_header`.
"""
csv_row(values) = join((v === nothing ? "" : js_string(v) for v in values), ",")

"""
    csv_header(labels) -> String

The header line: `time`, then every label through `csv_cell`.
"""
csv_header(labels) = join(Iterators.flatten((("time",), (csv_cell(l) for l in labels))), ",")

function _csv_table_row(t, columns, i::Int)
    io = IOBuffer()
    t[i] === nothing || print(io, js_string(t[i]))
    for col in columns
        write(io, ',')
        # A column shorter than the times leaves its cell empty.
        if i <= length(col)
            v = col[firstindex(col) + i - 1]
            v === nothing || print(io, js_string(v))
        end
    end
    return String(take!(io))
end

"""
    csv_lines(t, labels, columns)

The lines of a table's CSV, one at a time (`Results.csvLines`), as a lazy
iterator. `t` is the output times, `labels` one label per series and
`columns` one vector of values per series, in the same order. The first line
is `csv_header`; then one line per time, the time first. A column shorter
than `t` leaves its cell empty, as the application's does.
"""
function csv_lines(t, labels, columns)
    tt = collect(t)
    return Iterators.flatten(((csv_header(labels),), (_csv_table_row(tt, columns, i) for i in eachindex(tt))))
end

"""
    to_csv(t, labels, columns) -> String

A table's CSV as one string (`Results.toCSV`): `csv_lines` joined with `\\n`,
with no line break after the last.
"""
to_csv(t::AbstractVector, labels::AbstractVector, columns::AbstractVector) = join(csv_lines(t, labels, columns), "\n")
