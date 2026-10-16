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
              signal=nothing) -> JDict

Solves for the parameter values that put the endpoints where they are asked to
be (`calibrate`). `targets` are `{"output", "when", "time", "value", "scale",
"weight"}` (see `reading_of` and `objective_of`); `variables` are `{"key",
"lower", "upper", "space", "start"}`, `key` a slot label (`slot_label`),
`space` `"linear"` or `"log"`, `start` the model's own value when not a number;
`method` a key of `OPTIMISE_METHODS` (`"nelder"` when it names none);
`max_evals` the budget (300, at least 10); `seed` for differential evolution.
`on_progress` hears `(evals, fx, best, values)` after every evaluation; `signal`
(a function answering whether to stop, a `Ref{Bool}`, or a dictionary with
`"aborted"`) stops the search before the next one.

Returns `{"ok", "matched", "method", "reason", "evals", "ms", "objective",
"values", "targets"}`: `values[i]` = `{"key", "was", "value", "lower", "upper",
"pinned"}` and `targets[i]` = `{"output", "want", "got", "scale"}`. `matched`
says whether every target is met to 1%, which `ok` -- numbers came back --
does not.
"""
function calibrate(m; targets=nothing, variables=nothing, method=nothing, max_evals=nothing, seed=nothing,
                   on_progress=nothing, signal=nothing)
    started = time()
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
    ctx = (start=Float64[v.start for v in vars_], objective=x -> evaluate(x).objective,
           residuals=x -> evaluate(x).residuals)
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
    if out.x !== nothing
        got = evaluate(out.x)
        readings = last[]
        objective = got.objective
    end
    for (i, v) in enumerate(vars_)
        P[v.slot+1] = before[i]
    end
    evaluate_invariant!(sys)

    values = JDict[]
    if out.x !== nothing
        for (i, v) in enumerate(vars_)
            from = v.space.from
            # Within a thousandth of the range searched, in the space it was
            # searched in, is *on* a bound -- the same rule at every bound, 0 included.
            reach = abs(v.upper - v.lower) * 1e-3
            u = out.x[i]
            pinned = abs(u - v.lower) <= reach ? "lower" : abs(u - v.upper) <= reach ? "upper" : nothing
            push!(values, JDict("key" => v.key, "was" => before[i], "value" => from(u), "lower" => from(v.lower),
                                "upper" => from(v.upper), "pinned" => pinned))
        end
    end
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
        "targets" => [JDict("output" => _pd_prop(t, "output"), "want" => _pd_to_number(_pd_prop(t, "value")),
                            "got" => readings === nothing ? NaN : readings[i],
                            "scale" => _pd_nullish(_pd_prop(t, "scale")) ? "relative" : _pd_prop(t, "scale"))
                      for (i, t) in enumerate(targets)],
    )
end
