"""
    Kompartment.distributions

Probability distributions on parameters and lookup-table points, as a model
file stores them (the Python package's `kompartment.distributions`):

    {"kind": "logt", "params": {"min": 1e-5, "max": 1e-3, "mode": 1e-4},
     "values": null, "trmin": null, "trmax": null, "inorder": true, "pos": 0}

`make_pdf` builds one, checked as the application checks it; so do the
functions named after each kind:

```julia
const dist = Kompartment.distributions
m["k"].distribution = dist.log_triangular(0.01, 0.1, 0.05)
set_distribution!(m["Kd"], "norm"; at="Cs-137", mean=0.05, sd=0.01, trmin=0)
```

| kind     | what                        | parameters               |
|:---------|:----------------------------|:-------------------------|
| `unif`   | uniform                     | `min`, `max`             |
| `triang` | triangular                  | `min`, `max`, `mode`     |
| `dtriang`| double-triangular           | `min`, `max`, `mode`     |
| `norm`   | normal                      | `mean`, `sd`             |
| `logu`   | log-uniform                 | `min`, `max`             |
| `logt`   | log-triangular              | `min`, `max`, `mode`     |
| `logdt`  | log-double-triangular       | `min`, `max`, `mode`     |
| `Logn4`  | log-normal (geometric)      | `gm`, `gsd`              |
| `logn`   | log-normal (mean, SD)       | `mean`, `sd`             |
| `logn5`  | log-normal (two quantiles)  | `p1`, `x1`, `p2`, `x2`   |
| `pg`     | a list of values            | none; the sample in `values` |

Any of them may be truncated by value (`trmin`, `trmax`) or by percentile of
its own curve (`pmin`, `pmax`, probabilities: 0.05, not 5), and may name a
correlation `group`.
"""
module distributions

using OrderedCollections: OrderedDict
using ..Kompartment: JDict, _ed_pyfloat, _py_str, _py_repr, _py_g, py_truthy

"""A distribution that cannot be written down."""
struct DistributionError <: Exception
    message::String
end
Base.showerror(io::IO, e::DistributionError) = print(io, "DistributionError: ", e.message)

"""kind => (label, [(parameter, must be positive)], only defined above zero, is a list)."""
const KINDS = OrderedDict{String,Tuple{String,Vector{Tuple{String,Bool}},Bool,Bool}}(
    "unif" => ("Uniform", [("min", false), ("max", false)], false, false),
    "triang" => ("Triangular", [("min", false), ("max", false), ("mode", false)], false, false),
    "dtriang" => ("Double-triangular", [("min", false), ("max", false), ("mode", false)], false, false),
    "norm" => ("Normal", [("mean", false), ("sd", true)], false, false),
    "logu" => ("Log-uniform", [("min", true), ("max", true)], true, false),
    "logt" => ("Log-triangular", [("min", true), ("max", true), ("mode", true)], true, false),
    "logdt" => ("Log-double-triangular", [("min", true), ("max", true), ("mode", true)], true, false),
    "Logn4" => ("Log-normal (geometric)", [("gm", true), ("gsd", true)], true, false),
    "logn" => ("Log-normal (mean, SD)", [("mean", true), ("sd", true)], true, false),
    "logn5" => ("Log-normal (two quantiles)", [("p1", false), ("x1", true), ("p2", false), ("x2", true)], true, false),
    "pg" => ("List of values", Tuple{String,Bool}[], false, true),
)

"""The kinds, in the order the application offers them."""
const KIND_IDS = Tuple(keys(KINDS))

function _num(value)
    (value === nothing || (value isa AbstractString && value == "")) && return nothing
    v = _ed_pyfloat(value)
    v === nothing && throw(DistributionError("'$(_py_str(value))' is not a number"))
    (isnan(v) || isinf(v)) && throw(DistributionError("'$(_py_str(value))' is not a finite number"))
    return (isinteger(v) && value isa Integer) ? Int(v) : v
end

function _int(v)
    v isa Integer && return Int(v)
    v isa AbstractFloat && return trunc(Int, v)
    v isa AbstractString && return parse(Int, strip(v))
    throw(ArgumentError("$(_py_repr(v)) is not a whole number"))
end

"""
    make_pdf(kind; values=nothing, trmin=nothing, trmax=nothing, pmin=nothing, pmax=nothing,
             group=nothing, inorder=true, pos=0, check=true, params...) -> JDict

A distribution, as Kompartment stores one: `params` are the kind's own
parameters by name; one left out is stored as `nothing`, which the
application takes as a distribution not yet filled in. `values` is the
sample of a `pg` (list of values). With `check` the result is checked by
`pdf_problems` and refused if anything is wrong.
"""
function make_pdf(kind; values=nothing, trmin=nothing, trmax=nothing, pmin=nothing, pmax=nothing,
                  group=nothing, inorder=true, pos=0, check::Bool=true, params...)
    haskey(KINDS, kind) ||
        throw(DistributionError("'$(_py_str(kind))' is not a kind of distribution ($(join(KIND_IDS, ", ")))"))
    label, keys_, _positive, is_list = KINDS[kind]
    known = String[k for (k, _) in keys_]
    unknown = String[String(k) for k in keys(params) if !(String(k) in known)]
    if !isempty(unknown)
        takes = isempty(known) ? "none (give values=[...])" : join(known, ", ")
        throw(DistributionError("A $(lowercase(label)) distribution has no parameter " *
                                "$(join(map(_py_repr, unknown), ", ")); it takes $takes"))
    end
    p = JDict()
    for k in known
        p[k] = _num(get(params, Symbol(k), nothing))
    end
    spec = JDict("kind" => String(kind), "params" => p)
    if is_list
        values === nothing && throw(ArgumentError("'NoneType' object is not iterable"))
        sample = Any[]
        for v in values
            f = _ed_pyfloat(v)
            f === nothing && throw(ArgumentError("could not convert $(_py_repr(v)) to float"))
            push!(sample, f)
        end
        spec["values"] = sample
    else
        spec["values"] = nothing
    end
    spec["trmin"] = _num(trmin)
    spec["trmax"] = _num(trmax)
    pmin === nothing || (spec["pmin"] = _num(pmin))
    pmax === nothing || (spec["pmax"] = _num(pmax))
    if group !== nothing && !isempty(strip(_py_str(group)))
        spec["group"] = String(strip(_py_str(group)))
    end
    spec["inorder"] = py_truthy(inorder)
    spec["pos"] = _int(pos)
    if check
        problems = pdf_problems(spec)
        isempty(problems) || throw(DistributionError(join(problems, " ")))
    end
    return spec
end

"""Uniform between `min` and `max`."""
uniform(min, max; truncation...) = make_pdf("unif"; min=min, max=max, truncation...)
"""Triangular from `min` to `max`, most likely at `mode`."""
triangular(min, max, mode; truncation...) = make_pdf("triang"; min=min, max=max, mode=mode, truncation...)
"""Double-triangular: half the probability on each side of `mode`."""
double_triangular(min, max, mode; truncation...) = make_pdf("dtriang"; min=min, max=max, mode=mode, truncation...)
"""Normal with mean `mean` and standard deviation `sd`."""
normal(mean, sd; truncation...) = make_pdf("norm"; mean=mean, sd=sd, truncation...)
"""Log-uniform between `min` and `max` (both positive)."""
log_uniform(min, max; truncation...) = make_pdf("logu"; min=min, max=max, truncation...)
"""Triangular in ln x (all three positive)."""
log_triangular(min, max, mode; truncation...) = make_pdf("logt"; min=min, max=max, mode=mode, truncation...)
"""Double-triangular in ln x (all three positive)."""
log_double_triangular(min, max, mode; truncation...) = make_pdf("logdt"; min=min, max=max, mode=mode, truncation...)
"""Log-normal by the arithmetic mean and standard deviation of the quantity."""
lognormal(mean, sd; truncation...) = make_pdf("logn"; mean=mean, sd=sd, truncation...)
"""Log-normal by its geometric mean and geometric standard deviation (> 1)."""
lognormal_geometric(gm, gsd; truncation...) = make_pdf("Logn4"; gm=gm, gsd=gsd, truncation...)
"""Log-normal through two quantiles: a fraction `p1` below `x1`, `p2` below `x2`."""
lognormal_quantiles(p1, x1, p2, x2; truncation...) = make_pdf("logn5"; p1=p1, x1=x1, p2=p2, x2=x2, truncation...)
"""A sample drawn somewhere else, taken one value per realisation."""
value_list(values, in_order=true, pos=0; truncation...) =
    make_pdf("pg"; values=values, inorder=in_order, pos=pos, truncation...)

_get(d, k) = d isa AbstractDict ? get(d, k, nothing) : nothing

"""
    pdf_problems(spec) -> Vector{String}

What is wrong with a distribution, in words; empty when nothing is. The
application's own checks (`pdfProblems` in src/domain/pdf.js) but the last,
whether the numbers describe a curve that can be drawn at all.
"""
function pdf_problems(spec)
    out = String[]
    (py_truthy(spec) && spec isa AbstractDict) || return out
    kind = get(spec, "kind", nothing)
    (kind isa AbstractString && haskey(KINDS, kind)) || return out
    _label, keys_, positive, _is_list = KINDS[kind]
    p = get(spec, "params", nothing)
    py_truthy(p) || (p = JDict())
    for (key, must_be_positive) in keys_
        v = _get(p, key)
        v === nothing && continue
        (must_be_positive && !(v > 0)) && push!(out, "$key has to be more than zero.")
    end
    for key in ("pmin", "pmax")
        v = get(spec, key, nothing)
        if v !== nothing && !(0 <= v <= 1)
            push!(out, "A percentile truncation is a probability, so it has to be between 0 and 1 -- 0.05 for " *
                       "the 5th percentile, not 5.")
            break
        end
    end
    pmin, pmax = get(spec, "pmin", nothing), get(spec, "pmax", nothing)
    if pmin !== nothing && pmax !== nothing && !(pmax > pmin)
        push!(out, "The percentile truncation is inside out -- nothing is left between them.")
    end
    if positive
        for key in ("trmin", "trmax")
            v = get(spec, key, nothing)
            if v !== nothing && v < 0
                push!(out, "This distribution is only defined above zero, so it cannot be truncated below it.")
                break
            end
        end
    end
    mn, mx, mode = _get(p, "min"), _get(p, "max"), _get(p, "mode")
    if kind in ("unif", "triang", "dtriang", "logu", "logt", "logdt")
        if mn !== nothing && mx !== nothing && !(mx > mn)
            push!(out, "The range is empty -- the maximum has to be above the minimum.")
        end
    end
    if kind in ("triang", "dtriang", "logt", "logdt") && mode !== nothing
        (mn !== nothing && mode < mn) && push!(out, "The most likely value is below the minimum.")
        (mx !== nothing && mode > mx) && push!(out, "The most likely value is above the maximum.")
    end
    gsd = _get(p, "gsd")
    if kind == "Logn4" && gsd !== nothing && 0 < gsd <= 1
        push!(out, "A geometric standard deviation of 1 or less is a single value, not a spread -- it has to be more than 1.")
    end
    if kind == "logn5"
        for key in ("p1", "p2")
            v = _get(p, key)
            if v !== nothing && !(0 < v < 1)
                push!(out, "A quantile is a probability, so it has to be between 0 and 1.")
                break
            end
        end
        p1, p2 = _get(p, "p1"), _get(p, "p2")
        (p1 !== nothing && p2 !== nothing && p1 == p2) && push!(out, "The two quantiles have to be different.")
    end
    trmin, trmax = get(spec, "trmin", nothing), get(spec, "trmax", nothing)
    if trmin !== nothing && trmax !== nothing && !(trmax > trmin)
        push!(out, "The truncation is inside out -- nothing is left.")
    end
    return out
end

"""A distribution in a few words: `log-triangular(min=1e-05, max=0.001, mode=0.0001)`."""
function describe(spec)
    py_truthy(spec) || return "none"
    kind = get(spec, "kind", nothing)
    (kind isa AbstractString && haskey(KINDS, kind)) || return _py_str(kind)
    label = lowercase(KINDS[kind][1])
    if kind == "pg"
        vals = get(spec, "values", nothing)
        return "$label of $(py_truthy(vals) ? length(vals) : 0)"
    end
    p = get(spec, "params", nothing)
    bits = String[v isa Real ? "$k=$(_py_g(v))" : "$k=?" for (k, v) in (py_truthy(p) ? p : JDict())]
    return "$label($(join(bits, ", ")))"
end

end # module distributions

using .distributions: make_pdf, pdf_problems, DistributionError
