# Running an optimisation against the model: calibration. The Python package's
# `kompartment/engine/calibrate.py` (the application's `src/sim/calibrate.js`).
# ../stats/optimise.jl knows how to walk downhill and nothing about
# compartments; this is the other half -- what one evaluation *is*: set the
# parameters, work the invariants out again, solve, and read the endpoints at
# the times the targets name.
#
# **The system is built once.** Everything a candidate changes is read live --
# `P` is the array the compiled code holds and `initial_state` a call rather
# than a value -- which is the same reason a probabilistic run can integrate a
# thousand times off one build.
#
# **A variable may be searched in its logarithm** (`space: "log"`): a rate
# constant known to within orders of magnitude is not usefully stepped by a
# fixed amount. Only `P` ever sees the value itself.
#
# **An evaluation that will not solve is not an error.** A corner of the box
# the solver cannot carry comes back as NaN readings -- a miss of 1e6 per
# target -- which every method reads as "not that way".
#
# **How well the values are known** comes after the search: the residuals
# differenced along each value about the answer, and `precision_of`
# (../stats/precision.jl) on what that gives -- standard errors, ranges and
# correlations. Its runs are not counted among the search's evaluations.

"""
    reading_of(res, target) -> Float64

One endpoint's value out of a finished run (`readingOf`): `target` is
`{"output", "when", "time"}`, the series labelled `output` read at its highest
(`"peak"`), at the end (`"end"`), or at the output time nearest `time` -- the
nearest rather than an interpolation, since a target is compared against what
the model says. NaN when the run has no such series.
"""
function reading_of(res::Results, target)
    want_label = _pd_prop(target, "output")
    want_label isa AbstractString || return NaN
    o = nothing
    for x in outputs(res)
        label = get(x, "label", nothing)
        if something(label, "") == want_label
            o = x
            break
        end
    end
    o === nothing && return NaN
    v = series_many(res, [o])[1]
    t = res.t
    isempty(v) && return NaN
    when = _pd_prop(target, "when")
    if when == "peak"
        best = -Inf
        for x in v
            x > best && (best = Float64(x))
        end
        return best
    end
    when == "end" && return Float64(v[end])
    want = _pd_to_number(_pd_prop(target, "time"))
    at = 1
    gap = Inf
    for i in eachindex(t)
        d = abs(t[i] - want)
        if d < gap
            gap = d
            at = i
        end
    end
    return Float64(v[at])
end

"""
    variables_of(m) -> Vector{JDict}

The variables of a model, as an optimisation can offer them: every parameter
slot, `{"key", "name", "index", "slot", "value", "unit"}` (`variablesOf`).
"""
function variables_of(m)
    sys = build_system(_ls_project(m))
    return [JDict("key" => slot_label(e), "name" => e["name"], "index" => e["index"], "slot" => e["slot"],
                  "value" => e["value"], "unit" => something(e["unit"], "")) for e in parameter_slots(sys)]
end

_cb_within(want::Float64, got::Float64) =
    (isfinite(got) && isfinite(want)) && (want == 0 ? abs(got) < 1e-12 : abs((got - want) / want) < 0.01)

"""
    calibrate(m; targets, variables, method="nelder", max_evals=300, seed=1, on_progress=nothing,
              signal=nothing, precision=true) -> JDict

Solves for the parameter values that put the endpoints where they are asked to
be (`calibrate`). `targets` are `{"output", "when", "time", "value", "scale",
"weight"}` (see `reading_of` and `objective_of`); `variables` are `{"key",
"lower", "upper", "space", "start"}`, `key` a slot label (`slot_label`),
`space` `"linear"` or `"log"`, `start` the model's own value when not a number;
`method` a key of `OPTIMISE_METHODS` (`"nelder"` when it names none);
`max_evals` the budget (300, at least 10); `seed` for differential evolution.
`on_progress` hears `(evals, fx, best, values)` after every evaluation; `signal`
(a function answering whether to stop, a `Ref{Bool}`, or a dictionary with
`"aborted"`) stops the search before the next one. `precision=false` leaves out
how well the values are known, and the runs it takes.

Returns `{"ok", "matched", "method", "reason", "evals", "ms", "objective",
"values", "precision", "targets"}`: `values[i]` = `{"key", "was", "value",
"lower", "upper", "pinned"}` and `targets[i]` = `{"output", "want", "got",
"scale"}`. `matched` says whether every target is met to 1%, which `ok` --
numbers came back -- does not. `precision` is `precision_of`'s answer with
`"runs"`, the runs it took, beside it: worked out after the search, its runs
not among `evals`; `nothing` for a search that was stopped (or a stop while it
was worked out), for one whose best point the model could not finish, and with
`precision=false`.
"""
function calibrate(m; targets=nothing, variables=nothing, method=nothing, max_evals=nothing, seed=nothing,
                   on_progress=nothing, signal=nothing, precision=true)
    started = time()
    c = _cb_set_up(m, targets, variables, signal)
    vars_ = c.vars
    ctx = (start=Float64[v.start for v in vars_], objective=x -> c.evaluate(x).objective,
           residuals=x -> c.evaluate(x).residuals)
    run_method = something(_op_lookup(OPTIMISE_METHODS, method), OPTIMISE_METHODS["nelder"])
    on_step = on_progress === nothing ? nothing : p -> on_progress((
        evals=p.evals, fx=p.fx, best=p.best,
        # In the values a reader knows, not in the search space.
        values=p.best_x === nothing ? nothing : Float64[v.space.from(p.best_x[i]) for (i, v) in enumerate(vars_)]))
    budget = _pd_nullish(max_evals) ? 300 : max_evals
    out = run_method(ctx, (lower=Float64[v.lower for v in vars_], upper=Float64[v.upper for v in vars_],
                           max_evals=_pd_jmax(10.0, _gd_round(_pd_to_number(budget))),
                           seed=_pd_nullish(seed) ? 1 : seed, signal=signal, on_step=on_step))

    # The best point, read once more so the readings reported are the ones that
    # belong to the values reported.
    readings = nothing
    objective = out.fx
    residuals = nothing
    if out.x !== nothing
        got = c.evaluate(out.x)
        readings = c.readings()
        objective = got.objective
        residuals = got.residuals
    end
    values = out.x === nothing ? JDict[] : _cb_values_at(c, out.x)
    # How well they are known: after the search, so nothing the search decided
    # depends on it and its count of evaluations is its own. Not for a search
    # that was stopped -- a stop is a stop -- nor one the model could not finish
    # at its best point.
    found_precision = nothing
    if out.x !== nothing && precision !== false && out.reason != "stopped" && !c.stopped() && all(isfinite, readings)
        found_precision = _cb_precision_around(c, out.x, residuals, values)
    end
    c.restore()

    targets = c.targets
    return JDict(
        "ok" => out.x !== nothing && _op_is_finite_num(objective),
        "matched" => readings !== nothing &&
                     all(_cb_within(_pd_to_number(_pd_prop(t, "value")), readings[i]) for (i, t) in enumerate(targets)),
        "method" => _pd_nullish(method) ? "nelder" : method,
        "reason" => out.reason,
        "evals" => out.evals,
        "ms" => round(Int, 1000 * (time() - started)),
        "objective" => objective,
        "values" => values,
        "precision" => found_precision,
        "targets" => [JDict("output" => _pd_prop(t, "output"), "want" => _pd_to_number(_pd_prop(t, "value")),
                            "got" => readings === nothing ? NaN : readings[i],
                            "scale" => _pd_nullish(_pd_prop(t, "scale")) ? "relative" : _pd_prop(t, "scale"))
                      for (i, t) in enumerate(targets)],
    )
end

"""
What every evaluation needs, set up once (`setUp`): the targets, the variables
in the space each is searched in, and what one evaluation is -- the parameters
set, the invariants worked out again, a run, the endpoints read -- with the way
back to what the model held before.
"""
function _cb_set_up(m, targets, variables, signal)
    proj = _ls_project(m)
    targets = Any[t for t in something(targets, Any[]) if _pd_truthy(t) && _pd_truthy(_pd_prop(t, "output"))]
    isempty(targets) && throw(OptimiseError("No endpoint has been given a target value."))
    wanted = collect(something(variables, Any[]))
    isempty(wanted) && throw(OptimiseError("No parameter has been allowed to vary."))

    sys = build_system(proj)
    by_label = Dict{Any,JDict}()
    for e in parameter_slots(sys)
        by_label[slot_label(e)] = e
    end
    vars_ = NamedTuple[]
    for v in wanted
        key = _pd_prop(v, "key")
        found = key isa AbstractString ? get(by_label, key, nothing) : nothing
        found === nothing && throw(OptimiseError("'$(_pd_js_str(key))' is not a parameter of this model."))
        space = something(_op_lookup(OPTIMISE_SPACES, _pd_prop(v, "space")), OPTIMISE_SPACES["linear"])
        lo = _pd_to_number(_pd_prop(v, "lower"))
        hi = _pd_to_number(_pd_prop(v, "upper"))
        hi > lo || throw(OptimiseError("'$(_pd_js_str(key))' has no range: $(_pd_js_str(lo)) to $(_pd_js_str(hi))."))
        # A range that does not end gives a search no size to start from.
        (isfinite(lo) && isfinite(hi)) ||
            throw(OptimiseError("'$(_pd_js_str(key))' needs finite bounds: $(_pd_js_str(lo)) to $(_pd_js_str(hi))."))
        space.ok(lo, hi) || throw(OptimiseError("'$(_pd_js_str(key))' is searched in the logarithm, so both bounds have " *
                                                "to be above zero."))
        s = _pd_to_number(_pd_prop(v, "start"))
        at0 = isfinite(s) ? s : found["value"]
        push!(vars_, (key=String(key), slot=Int(found["slot"]), space=space, lower=space.to(lo), upper=space.to(hi),
                      start=space.to(_pd_jmin(hi, _pd_jmax(lo, _op_is_finite_num(at0) ? Float64(at0) : lo)))))
    end

    P = sys.P
    # What the model held before any of this, so it can be put back.
    before = Float64[P[v.slot+1] for v in vars_]
    last = Ref{Any}(nothing)
    # A run is not stopped part way: the search stops between evaluations.
    function evaluate(x)
        for (i, v) in enumerate(vars_)
            P[v.slot+1] = v.space.from(x[i])
        end
        evaluate_invariant!(sys)
        last[] = try
            res = run_project(proj; system=sys, on_grid=true)
            Float64[reading_of(res, t) for t in targets]
        catch e
            e isa InterruptException && rethrow()
            # A corner the solver cannot carry is a fact about the model.
            fill(NaN, length(targets))
        end
        return objective_of(last[], targets)
    end
    function restore()
        for (i, v) in enumerate(vars_)
            P[v.slot+1] = before[i]
        end
        evaluate_invariant!(sys)
    end
    return (targets=targets, vars=vars_, before=before, evaluate=evaluate, restore=restore,
            readings=() -> last[], stopped=() -> _op_aborted(signal))
end

"""The values at a point of the search, as the model holds them, and which sit on a bound (`valuesAt`)."""
function _cb_values_at(c, x)
    values = JDict[]
    for (i, v) in enumerate(c.vars)
        from = v.space.from
        # Within a thousandth of the range searched, in the space it was
        # searched in, is *on* a bound -- the same rule at every bound, 0 included.
        reach = abs(v.upper - v.lower) * 1e-3
        u = x[i]
        pinned = abs(u - v.lower) <= reach ? "lower" : abs(u - v.upper) <= reach ? "upper" : nothing
        push!(values, JDict("key" => v.key, "was" => c.before[i], "value" => from(u), "lower" => from(v.lower),
                            "upper" => from(v.upper), "pinned" => pinned))
    end
    return values
end

"""
How far each value is moved to difference the residuals for the precision: a
thousandth -- of the value itself where it is searched as it is, of its
logarithm's unit where it is searched in the logarithm -- and never more than a
quarter of the range.
"""
const PRECISION_STEP = 1e-3

"""
The precision of the values found (`precisionAround`): the residuals
differenced along each value about the answer -- central where both sides are
inside the bounds, one-sided against a bound -- and `precision_of` on what that
gives. A value on a bound is held; one the model would not run around is said
so. `nothing` when the signal stops it part way.
"""
function _cb_precision_around(c, x, residuals, values)
    vars_ = c.vars
    columns = Union{Nothing,Vector{Float64}}[]
    failed = Union{Nothing,String}[]
    runs = 0
    function at(k, u)
        xp = Float64[e for e in x]
        xp[k] = u
        runs += 1
        got = c.evaluate(xp)
        return all(isfinite, c.readings()) ? got.residuals : nothing
    end
    for (k, v) in enumerate(vars_)
        c.stopped() && return nothing
        if values[k]["pinned"] !== nothing
            push!(columns, nothing)
            push!(failed, nothing)
            continue
        end
        span = v.upper - v.lower
        own = v.space === OPTIMISE_SPACES["log"] ? 1.0 : abs(x[k])
        h = min(span / 4, PRECISION_STEP * (own > 0 ? own : span))
        up = x[k] + h <= v.upper
        down = x[k] - h >= v.lower
        col = nothing
        if h > 0 && up && down
            p = at(k, x[k] + h)
            q = p === nothing ? nothing : at(k, x[k] - h)
            if p !== nothing && q !== nothing
                col = Float64[(p[i] - q[i]) / (2 * h) for i in eachindex(p)]
            end
        elseif h > 0 && (up || down)
            step = up ? h : -h
            p = at(k, x[k] + step)
            p === nothing || (col = Float64[(p[i] - residuals[i]) / step for i in eachindex(p)])
        end
        push!(columns, col)
        push!(failed, col === nothing ? "did not run" : nothing)
    end
    out = precision_of(; residuals, columns, keys=String[v.key for v in vars_],
                       spaces=String[v.space === OPTIMISE_SPACES["log"] ? "log" : "linear" for v in vars_],
                       values=Float64[v["value"] for v in values], pinned=Any[v["pinned"] for v in values], failed)
    out["runs"] = runs
    return out
end

"""
    calibration_precision(m; targets, variables, values) -> Union{JDict,Nothing}

The precision of values a calibration found, worked out at them as `calibrate`
works it out at its own (`calibrationPrecision`): `targets` and `variables` as
`calibrate` takes them, `values` a result's `"values"` in the variables' order.
`nothing` when the model cannot be finished there.
"""
function calibration_precision(m; targets=nothing, variables=nothing, values=nothing)
    c = _cb_set_up(m, targets, variables, nothing)
    try
        found = collect(something(values, Any[]))
        length(found) == length(c.vars) ||
            throw(OptimiseError("The values do not match the parameters that were varied."))
        x = Float64[v.space.to(_pd_to_number(_pd_prop(found[i], "value"))) for (i, v) in enumerate(c.vars)]
        got = c.evaluate(x)
        all(isfinite, c.readings()) || return nothing
        return _cb_precision_around(c, x, got.residuals, _cb_values_at(c, x))
    finally
        c.restore()
    end
end
