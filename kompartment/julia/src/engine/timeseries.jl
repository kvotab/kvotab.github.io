# When results are saved: the output time grid (src/domain/timeseries.js).
#
# A list of series -- geometric, linear, or times written out -- combines into
# one sorted set of times, the run's own start and end always in it and
# duplicates removed with a relative tolerance.

"""Two times are the same time when they are this close, relatively."""
const SAME_TIME = 1e-9

_ts_number(v::Nothing) = 0.0
_ts_number(v) = (f = py_float(v); f)

function series_kind(spec)
    spec !== nothing && get(spec, "times", nothing) isa AbstractVector && return "times"
    k = jget(spec, "kind")
    named = js_str(k !== nothing ? k : (jget(spec, "spacing") !== nothing ? spec["spacing"] : "log"))
    return named in SERIES_KINDS ? named : "log"
end

"""One series' own time points inside the run, in increasing order."""
function series_times(spec, t0::Float64, t1::Float64)
    kind = series_kind(spec)
    if kind == "times"
        vals = [_ts_number(v) for v in something(get(spec, "times", nothing), Any[])]
        return sort!([v for v in vals if isfinite(v) && t0 <= v <= t1])
    end
    n = _ts_number(get(spec, "points", 0))
    n = isfinite(n) ? floor(n + 0.5) : n
    n >= 2 || return Float64[]
    n = Int(n)
    frm = get(spec, "from", nothing) === nothing ? t0 : _ts_number(spec["from"])
    to = get(spec, "to", nothing) === nothing ? t1 : _ts_number(spec["to"])
    (isfinite(frm) && isfinite(to)) || return Float64[]
    out = Float64[]
    last = min(t1, to)
    if kind == "log"
        frm <= 0 && (frm = 1.0)
        to > frm || return Float64[]
        step = (js_log10(to) - js_log10(frm)) / (n - 1)
        step > 0 || return Float64[]
        log_from = js_log10(frm)
        for c in 0:(n*4+7)
            v = js_pow(10.0, log_from + step * c)
            v > last * (1 + SAME_TIME) && break
            v >= t0 && push!(out, v)
        end
        return out
    end
    step = (to - frm) / (n - 1)
    step > 0 || return Float64[]
    for c in 0:(n*4+7)
        v = frm + step * c
        v > last + abs(step) * SAME_TIME && break
        v >= t0 && push!(out, v)
    end
    return out
end

"""Every series, sorted, without duplicates; the run's start and end always in."""
function combine_series(series, t0::Float64, t1::Float64)
    every = Float64[t0, t1]
    for spec in something(series, Any[])
        append!(every, series_times(spec, t0, t1))
    end
    sort!(every)
    out = Float64[]
    for v in every
        isfinite(v) || continue
        if !isempty(out)
            last = out[end]
            abs(v - last) <= abs(last == 0 ? v : last) * SAME_TIME && continue
        end
        push!(out, v)
    end
    return out
end
