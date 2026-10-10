# Numbers read off finished curves: the peak, when it peaked, the total
# (src/domain/derived.js). A derived value is an output like any other, worked
# out from (t, y) when asked for; the kinds that are curves (the running
# integral, per-period means and sums) give one value per output time, the
# rest one number.

const DERIVED_KINDS = ("max", "min", "time_of_max", "at_time", "integral", "period_mean", "period_sum",
                       "period_change", "period_rate")
const PERIOD_KINDS = ("period_mean", "period_sum", "period_change", "period_rate")

is_series_kind(kind) = kind == "integral" || kind in PERIOD_KINDS

function derived_unit(kind, source_unit, time_unit)
    u = strip(js_str(something(source_unit, "")))
    tu = strip(js_str(something(time_unit, "")))
    kind == "time_of_max" && return String(tu)
    kind in ("integral", "period_sum") && return isempty(u) ? "" : "$u $tu"
    kind == "period_rate" && return isempty(u) ? "" : "$u/$tu"
    return String(u)
end

function derived_reduce(kind, t::AbstractVector{Float64}, values::AbstractVector{Float64}; at=nothing, period=nothing)
    n = min(length(t), length(values))
    kind == "integral" && return derived_integral(t, values, n)
    kind in PERIOD_KINDS && return by_period(kind, t, values, n, py_float(something(period, NaN)))
    n == 0 && return NaN
    kind == "at_time" && return derived_value_at(t, values, n, py_float(something(at, NaN)))
    best = NaN
    best_at = NaN
    for i in 1:n
        v = values[i]
        isfinite(v) || continue
        if best != best || (kind == "min" ? v < best : v > best)
            best = v
            best_at = t[i]
        end
    end
    return kind == "time_of_max" ? best_at : best
end

function derived_value_at(t, values, n, at)
    (n == 0 || !isfinite(at)) && return NaN
    at <= t[1] && return values[1]
    at >= t[n] && return values[n]
    lo, hi = 0, n - 1
    while hi - lo > 1
        mid = (lo + hi) >> 1
        if t[mid+1] <= at
            lo = mid
        else
            hi = mid
        end
    end
    span = t[hi+1] - t[lo+1]
    span > 0 || return values[lo+1]
    a, b = values[lo+1], values[hi+1]
    isfinite(a) || return b
    isfinite(b) || return a
    return a + ((at - t[lo+1]) / span) * (b - a)
end

function derived_integral(t, values, n=min(length(t), length(values)))
    out = zeros(n)
    total = 0.0
    for i in 2:n
        dt = t[i] - t[i-1]
        a, b = values[i-1], values[i]
        if dt > 0 && isfinite(a) && isfinite(b)
            total += 0.5 * (a + b) * dt
        end
        out[i] = total
    end
    return out
end

function by_period(kind, t, values, n, period)
    out = fill(NaN, n)
    (n == 0 || !(period > 0)) && return out
    t0, t_end = t[1], t[n]
    running = derived_integral(t, values, n)
    function integral_to(x)
        x <= t0 && return 0.0
        x >= t_end && return running[n]
        lo, hi = 0, n - 1
        while hi - lo > 1
            mid = (lo + hi) >> 1
            if t[mid+1] <= x
                lo = mid
            else
                hi = mid
            end
        end
        a = values[lo+1]
        b = derived_value_at(t, values, n, x)
        (!isfinite(a) || !isfinite(b)) && return running[lo+1]
        return running[lo+1] + 0.5 * (a + b) * (x - t[lo+1])
    end
    j = 0
    k = 0
    while true
        frm = t0 + k * period
        frm > t_end && break
        to = min(t_end, frm + period)
        span = to - frm
        if kind == "period_mean"
            v = span > 0 ? (integral_to(to) - integral_to(frm)) / span : derived_value_at(t, values, n, frm)
        elseif kind == "period_sum"
            v = integral_to(to) - integral_to(frm)
        else
            change = derived_value_at(t, values, n, to) - derived_value_at(t, values, n, frm)
            v = kind == "period_change" ? change : (span > 0 ? change / span : NaN)
        end
        while j < n && (t[j+1] < to || (to == t_end && t[j+1] <= t_end))
            out[j+1] = v
            j += 1
        end
        to == t_end && break
        k += 1
    end
    return out
end

function derived_blocks(project::Project)
    out = Any[]
    for b in project.derived
        b isa AbstractDict || continue
        isempty(strip(js_str(something(get(b, "name", nothing), "")))) && continue
        get(b, "kind", nothing) in DERIVED_KINDS || continue
        isempty(strip(js_str(something(get(b, "of", nothing), "")))) && continue
        push!(out, b)
    end
    return out
end

"""The derived values a run can report, admitted in passes so one may be of another."""
function derived_outputs(project::Project, known_outputs::Vector{JDict})
    out = JDict[]
    pending = derived_blocks(project)
    isempty(pending) && return out
    known = Set{Any}(o["label"] for o in known_outputs)
    by_label = Dict{Any,JDict}(o["label"] => o for o in known_outputs)
    time_unit = something(get(project.simulation, "time_unit", nothing), "year")
    passes = 0
    while !isempty(pending) && passes <= length(pending)
        later = Any[]
        for d in pending
            name = js_str(d["name"])
            if !(d["of"] in known) || name in known
                push!(later, d)
                continue
            end
            src = get(by_label, d["of"], nothing)
            o = JDict("kind" => "derived", "source" => "D", "block" => name, "label" => name,
                      "unit" => derived_unit(d["kind"], src === nothing ? nothing : get(src, "unit", nothing), time_unit),
                      "derived" => JDict("kind" => d["kind"], "of" => d["of"], "at" => py_float(something(get(d, "at", nothing), NaN)),
                                         "period" => py_float(something(get(d, "period", nothing), NaN))),
                      "dims" => Any[], "index" => nothing)
            is_series_kind(d["kind"]) || (o["timeDependent"] = false)
            push!(out, o)
            by_label[name] = o
            push!(known, name)
        end
        length(later) == length(pending) && break
        pending = later
        passes += 1
    end
    return out
end
