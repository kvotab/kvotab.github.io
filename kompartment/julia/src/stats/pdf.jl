# Probability distributions on a parameter, as Kompartment reads and draws
# them: the part of the Python package's `kompartment/stats/pdf.py` (the
# application's `src/domain/pdf.js`) that a probabilistic run needs -- which
# kinds there are, whether one is filled in, its forward and inverse CDF and
# the two probabilities a truncation leaves.
#
# A distribution is a dictionary, as a model file stores it:
#
#     {"kind": "logt", "params": {"min": 7e-12, "max": 5e-11, "mode": 1e-11},
#      "values": null, "trmin": null, "trmax": null, "pmin": null, "pmax": null,
#      "group": null, "inorder": true, "pos": 0}
#
# Every function is the Python one step for step, down to the order of the
# operations, so that a value drawn here is the value the Python package (and
# the application) draws:
#
# - The arithmetic is V8's: `js_exp` and `js_log` (src/lang/jsmath.jl) are the
#   ports of fdlibm the Python package uses, bit for bit; the normal CDF and
#   quantile go through src/stats/normal.jl, which uses the C library as
#   Python's `math` does.
# - JavaScript's rules where a value is not a plain number: `null` counts as 0
#   in arithmetic and a missing key as NaN, `Math.max` of a NaN is NaN, and so
#   on, so a distribution that is only half filled in gives what it gives in
#   the application rather than raising.

"""JavaScript's `undefined`: a key that is not there, as distinct from `null` (`nothing`)."""
struct PdfMissing end
const _PD_MISSING = PdfMissing()
Base.show(io::IO, ::PdfMissing) = print(io, "undefined")

"""What each kind takes, in the application's order (`PDF_KINDS`)."""
const PDF_KIND_PARAMS = OrderedDict{String,Vector{String}}(
    "unif" => ["min", "max"],
    "triang" => ["min", "max", "mode"],
    "dtriang" => ["min", "max", "mode"],
    "norm" => ["mean", "sd"],
    "logu" => ["min", "max"],
    "logt" => ["min", "max", "mode"],
    "logdt" => ["min", "max", "mode"],
    "Logn4" => ["gm", "gsd"],
    "logn" => ["mean", "sd"],
    "logn5" => ["p1", "x1", "p2", "x2"],
    "pg" => String[],
)

"""The order the editor offers the kinds in: the shapes first, the list last."""
const PDF_KIND_IDS = collect(keys(PDF_KIND_PARAMS))

# --- JavaScript's rules, where Julia's differ ---------------------------------------------

"""`obj?.[key]`: the value, or `undefined` for a key (or an object) that is not there."""
_pd_prop(obj::AbstractDict, key::String) = get(obj, key, _PD_MISSING)
_pd_prop(obj, key::String) = _PD_MISSING

"""`v == null`: `null` or `undefined`."""
_pd_nullish(v) = v === nothing || v === _PD_MISSING

"""JavaScript's ToBoolean: an empty dictionary or list is true, 0, NaN and '' are not."""
function _pd_truthy(v)
    (v === nothing || v === _PD_MISSING) && return false
    v isa Bool && return v
    v isa Real && return !(v == 0 || isnan(v))
    v isa AbstractString && return !isempty(v)
    return true
end

const _PD_JS_SPACE = Set{Char}(['\t', '\n', '\v', '\f', '\r', ' ', ' ', ' ', ' ', ' ',
                                ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ',
                                ' ', ' ', ' ', ' ', ' ', '　', '﻿'])
const _PD_DECIMAL = r"^[+-]?(?:Infinity|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\z"
const _PD_OTHER = r"^0(?:[xX]([0-9a-fA-F]+)|[oO]([0-7]+)|[bB]([01]+))\z"

"""`String.prototype.trim`."""
_pd_js_trim(s::AbstractString) = strip(c -> c in _PD_JS_SPACE, s)

"""`Number(s)` for a string: JavaScript's StringToNumber."""
function _pd_string_to_number(s::AbstractString)
    t = _pd_js_trim(s)
    isempty(t) && return 0.0
    m = match(_PD_OTHER, t)
    if m !== nothing
        for (digits, base) in zip(m.captures, (16, 8, 2))
            digits === nothing && continue
            return Float64(parse(BigInt, digits; base))
        end
    end
    if occursin(_PD_DECIMAL, t)
        body = lstrip(t, ['+', '-'])
        body == "Infinity" && return startswith(t, "-") ? -Inf : Inf
        return parse(Float64, t)
    end
    return NaN
end

"""`String(x)` for a number: NaN and the infinities included, an integer as the double it is."""
function _pd_js_number_str(x::Real)
    f = Float64(x)
    isnan(f) && return "NaN"
    isinf(f) && return f > 0 ? "Infinity" : "-Infinity"
    return js_number(f)
end

"""`String(v)` for anything a model file can hold."""
function _pd_js_str(v)
    v === _PD_MISSING && return "undefined"
    v === nothing && return "null"
    v isa Bool && return v ? "true" : "false"
    v isa AbstractString && return String(v)
    v isa Real && return _pd_js_number_str(v)
    v isa AbstractVector && return join((_pd_nullish(e) ? "" : _pd_js_str(e) for e in v), ",")
    v isa AbstractDict && return "[object Object]"
    return string(v)
end

"""`Number(v)`: `null` is 0, `undefined` NaN, a string read as JavaScript reads one."""
function _pd_to_number(v)
    v === _PD_MISSING && return NaN
    v === nothing && return 0.0
    v isa Bool && return v ? 1.0 : 0.0
    v isa Real && return Float64(v)
    v isa AbstractString && return _pd_string_to_number(v)
    v isa AbstractVector && return _pd_string_to_number(_pd_js_str(v))
    return NaN
end

"""A distribution's parameter as JavaScript's arithmetic reads it: `null` is 0, missing NaN."""
_pd_param(p, key::String) = _pd_to_number(_pd_prop(p, key))

"""`Math.max(a, b)`: NaN if either is, and +0 above -0."""
function _pd_jmax(a::Float64, b::Float64)
    (isnan(a) || isnan(b)) && return NaN
    a == b && return signbit(a) ? b : a
    return a > b ? a : b
end

"""`Math.min(a, b)`: NaN if either is, and -0 below +0."""
function _pd_jmin(a::Float64, b::Float64)
    (isnan(a) || isnan(b)) && return NaN
    a == b && return signbit(a) ? a : b
    return a < b ? a : b
end

"""`Math.sqrt`: NaN below zero rather than an error."""
_pd_sqrt(x::Float64) = x >= 0 ? sqrt(x) : NaN

"""The kind's parameter names, or `nothing` for anything that is not a kind's own name."""
_pd_meta(kind) = kind isa AbstractString ? get(PDF_KIND_PARAMS, kind, nothing) : nothing

"""
    pdf_complete(spec) -> Bool

Whether every number the kind needs is filled in (for a list, whether it has values).
"""
function pdf_complete(spec)
    _pd_truthy(spec) || return false
    kind = _pd_prop(spec, "kind")
    params = _pd_meta(kind)
    params === nothing && return false
    if kind == "pg"
        values = _pd_prop(spec, "values")
        (values isa AbstractDict || values isa Real || _pd_nullish(values)) && return false
        values isa AbstractVector && return length(values) > 0
        values isa AbstractString && return length(values) > 0
        return false
    end
    p = _pd_prop(spec, "params")
    return all(k -> !_pd_nullish(_pd_prop(p, k)), params)
end

# --- the forward and inverse CDF -------------------------------------------------------------

"""`spec.params ?? {}`; like the application, fails on no distribution at all."""
function _pd_params_of(spec)
    _pd_nullish(spec) && throw(ArgumentError("no distribution: the application cannot read the parameters of null either"))
    p = _pd_prop(spec, "params")
    return _pd_nullish(p) ? JDict() : p
end

"""Logn.muprim / sigmaprim: an arithmetic mean and sd carried into log space."""
_pd_logn_log_space(mean::Float64, sd::Float64) =
    (js_log((mean * mean) / sqrt((sd * sd) + (mean * mean))), _pd_sqrt(js_log(1 + ((sd * sd) / (mean * mean)))))

"""A parameter as handed to `probit`, which reads it with Python's `float()`."""
function _pd_arg_raw(p, key::String)
    v = _pd_prop(p, key)
    return v === _PD_MISSING ? NaN : v
end

"""A log-normal's log-space mean and sd, whichever way it was written; `nothing` where there is none."""
function _pd_log_space(spec)
    kind = _pd_prop(spec, "kind")
    p = _pd_prop(spec, "params")
    p = _pd_nullish(p) ? JDict() : p
    kind == "Logn4" && return (js_log(_pd_param(p, "gm")), js_log(_pd_param(p, "gsd")))
    kind == "logn" && return _pd_logn_log_space(_pd_param(p, "mean"), _pd_param(p, "sd"))
    if kind == "logn5"
        z1 = normal_probit(_pd_arg_raw(p, "p1"))
        z2 = normal_probit(_pd_arg_raw(p, "p2"))
        (z1 === nothing || z2 === nothing || z1 == z2) && return nothing
        sigma = (js_log(_pd_param(p, "x2")) - js_log(_pd_param(p, "x1"))) / (z2 - z1)
        sigma > 0 || return nothing
        return (js_log(_pd_param(p, "x1")) - sigma * z1, sigma)
    end
    return nothing
end

"""
    pdf_cdf(spec, x) -> Float64

The probability of being at or below `x`, before truncation (`cdf_at`): exact
where the shape is elementary, through the normal CDF for the three
log-normals; 0 for a kind it does not know.
"""
function pdf_cdf(spec, x0)
    p = _pd_params_of(spec)
    kind = _pd_prop(spec, "kind")
    x = _pd_to_number(x0)
    if kind == "unif"
        a = _pd_param(p, "min")
        b = _pd_param(p, "max")
        x <= a && return 0.0
        x >= b && return 1.0
        return (x - a) / (b - a)
    elseif kind == "triang"
        a = _pd_param(p, "min")
        b = _pd_param(p, "max")
        c = _pd_param(p, "mode")
        x <= a && return 0.0
        x >= b && return 1.0
        x <= c && return ((x - a) * (x - a)) / ((b - a) * (c - a))
        return 1 - ((b - x) * (b - x)) / ((b - a) * (b - c))
    elseif kind == "dtriang"
        a = _pd_param(p, "min")
        b = _pd_param(p, "max")
        c = _pd_param(p, "mode")
        x <= a && return 0.0
        x >= b && return 1.0
        x <= c && return ((x - a) * (x - a)) / (2 * ((c - a) * (c - a)))
        return 1 - ((b - x) * (b - x)) / (2 * ((b - c) * (b - c)))
    elseif kind == "logu"
        a = _pd_param(p, "min")
        b = _pd_param(p, "max")
        x <= a && return 0.0
        x >= b && return 1.0
        return (js_log(x) - js_log(a)) / (js_log(b) - js_log(a))
    elseif kind == "logt"
        la = js_log(_pd_param(p, "min"))
        lb = js_log(_pd_param(p, "max"))
        lc = js_log(_pd_param(p, "mode"))
        x <= _pd_param(p, "min") && return 0.0
        x >= _pd_param(p, "max") && return 1.0
        lx = js_log(x)
        lx <= lc && return ((lx - la) * (lx - la)) / ((lc - la) * (lb - la))
        return 1 - ((lb - lx) * (lb - lx)) / ((lb - la) * (lb - lc))
    elseif kind == "logdt"
        x <= _pd_param(p, "min") && return 0.0
        x >= _pd_param(p, "max") && return 1.0
        la = js_log(_pd_param(p, "min"))
        lb = js_log(_pd_param(p, "max"))
        lc = js_log(_pd_param(p, "mode"))
        lx = js_log(x)
        lx <= lc && return ((lx - la) * (lx - la)) / (2 * ((lc - la) * (lc - la)))
        return 1 - ((lb - lx) * (lb - lx)) / (2 * ((lb - lc) * (lb - lc)))
    elseif kind == "norm"
        return normal_phi((x - _pd_param(p, "mean")) / _pd_param(p, "sd"))
    elseif kind == "Logn4" || kind == "logn" || kind == "logn5"
        x <= 0 && return 0.0
        ls = _pd_log_space(spec)
        return ls === nothing ? 0.0 : normal_phi((js_log(x) - ls[1]) / ls[2])
    end
    return 0.0
end

"""`probit(u)` where JavaScript multiplies by it: its `null` outside (0, 1) counts as 0."""
_pd_probit_or_zero(u::Float64) = something(normal_probit(u), 0.0)

"""
    pdf_quantile(spec, u) -> Float64

The value at probability `u`, before truncation (`quantile`); NaN for a kind it
does not know. As in the application, the normal kinds read `probit(u)`, which
is 0 outside (0, 1): the quantile of 0 or 1 of a normal is its mean.
"""
function pdf_quantile(spec, u0)
    p = _pd_params_of(spec)
    kind = _pd_prop(spec, "kind")
    u = _pd_to_number(u0)
    if kind == "unif"
        a = _pd_param(p, "min")
        return a + u * (_pd_param(p, "max") - a)
    elseif kind == "triang"
        a = _pd_param(p, "min")
        b = _pd_param(p, "max")
        c = _pd_param(p, "mode")
        split = (c - a) / (b - a)
        u <= split && return a + _pd_sqrt((u * (b - a)) * (c - a))
        return b - _pd_sqrt(((1 - u) * (b - a)) * (b - c))
    elseif kind == "dtriang"
        a = _pd_param(p, "min")
        b = _pd_param(p, "max")
        c = _pd_param(p, "mode")
        u <= 0.5 && return a + _pd_sqrt(2 * u) * (c - a)
        return b - (b - c) * _pd_sqrt(2 * (1 - u))
    elseif kind == "logu"
        la = js_log(_pd_param(p, "min"))
        return js_exp(la + u * (js_log(_pd_param(p, "max")) - la))
    elseif kind == "logt"
        la = js_log(_pd_param(p, "min"))
        lb = js_log(_pd_param(p, "max"))
        lc = js_log(_pd_param(p, "mode"))
        split = (lc - la) / (lb - la)
        lx = u <= split ? la + _pd_sqrt((u * (lb - la)) * (lc - la)) :
             lb - _pd_sqrt(((1 - u) * (lb - la)) * (lb - lc))
        return js_exp(lx)
    elseif kind == "logdt"
        la = js_log(_pd_param(p, "min"))
        lb = js_log(_pd_param(p, "max"))
        lc = js_log(_pd_param(p, "mode"))
        lx = u <= 0.5 ? la + _pd_sqrt(2 * u) * (lc - la) : lb - (lb - lc) * _pd_sqrt(2 * (1 - u))
        return js_exp(lx)
    elseif kind == "norm"
        return _pd_param(p, "mean") + _pd_param(p, "sd") * _pd_probit_or_zero(u)
    elseif kind == "Logn4" || kind == "logn" || kind == "logn5"
        ls = _pd_log_space(spec)
        return ls === nothing ? NaN : js_exp(ls[1] + ls[2] * _pd_probit_or_zero(u))
    end
    return NaN
end

"""
    probability_cuts(spec) -> (lo, hi, cut, reversed)

The two probabilities a truncated curve is read between, as the sampler reads
it: `trmin`/`trmax` through the CDF, `pmin`/`pmax` as they are, the tighter on
each side. A cut the wrong way round -- Ecolego's `trmin=6.5,trmax=0.0` -- is
no cut at all: `cut` is false then, and `reversed` true.
"""
function probability_cuts(spec)
    lo = 0.0
    hi = 1.0
    trmin = _pd_prop(spec, "trmin")
    trmax = _pd_prop(spec, "trmax")
    pmin = _pd_prop(spec, "pmin")
    pmax = _pd_prop(spec, "pmax")
    _pd_nullish(trmin) || (lo = _pd_jmax(lo, pdf_cdf(spec, trmin)))
    _pd_nullish(trmax) || (hi = _pd_jmin(hi, pdf_cdf(spec, trmax)))
    _pd_nullish(pmin) || (lo = _pd_jmax(lo, _pd_to_number(pmin)))
    _pd_nullish(pmax) || (hi = _pd_jmin(hi, _pd_to_number(pmax)))
    hi > lo || return (lo=0.0, hi=1.0, cut=false, reversed=true)
    return (lo=lo, hi=hi, cut=lo > 0 || hi < 1, reversed=false)
end
