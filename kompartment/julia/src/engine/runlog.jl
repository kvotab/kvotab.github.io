# The run log: what a run was, in words that survive it -- program, date, the
# settings, how the solve went, what was held at zero, whether the mass balance
# closed. The application's src/domain/runlog.js (the Python package's
# kompartment/engine/runlog.py), which the page shows under *Run log* and
# writes into a results archive; numbers written as the page writes them.

"""`x.toFixed(digits)`: the exact value rounded half up; `String(x)` from 1e21."""
function js_to_fixed(x::Real, digits::Integer)
    v = Float64(x)
    isnan(v) && return "NaN"
    abs(v) >= 1e21 && return js_text(v)
    sign = v < 0 ? "-" : ""
    n = floor(BigInt, Rational{BigInt}(abs(v)) * big(10)^digits + 1 // 2)
    s = string(n)
    digits == 0 && return sign * s
    length(s) <= digits && (s = "0"^(digits - length(s) + 1) * s)
    return sign * s[1:end-digits] * "." * s[end-digits+1:end]
end

"""`x.toExponential(f)`: the exact value rounded to f + 1 digits, a tie going up."""
function js_to_exponential(x::Real, f::Integer)
    v = Float64(x)
    isnan(v) && return "NaN"
    sign = v < 0 ? "-" : ""
    v = abs(v)
    isinf(v) && return sign * "Infinity"
    if v == 0
        m = "0"^(f + 1)
        e = 0
    else
        r = Rational{BigInt}(v)
        pow10(k) = k >= 0 ? big(10)^k // 1 : 1 // big(10)^(-k)
        e = 0
        while r >= pow10(e + 1)
            e += 1
        end
        while r < pow10(e)
            e -= 1
        end
        n = floor(BigInt, r * pow10(f - e) + 1 // 2)
        if n >= big(10)^(f + 1)
            n = div(n, 10)
            e += 1
        end
        m = string(n)
    end
    f != 0 && (m = m[1:1] * "." * m[2:end])
    return sign * m * "e" * (e >= 0 ? "+" : "-") * string(abs(e))
end

"""A number as the mass-balance audit's report writes it."""
function _rl_audit_num(x::Real)
    v = Float64(x)
    v == 0 && return "0"
    (abs(v) >= 1e-3 && abs(v) < 1e6) && return js_text(parse(Float64, js_to_precision(v, 4)))
    return js_to_exponential(v, 3)
end

"""The mass-balance audit in words (`describeAudit`): whether it closes, then a line per family."""
function describe_audit(a, time_unit="")
    unit = (time_unit === nothing || time_unit == "") ? "" : " $(time_unit)"
    out = String[]
    if a.closed
        out_line = "mass balance: closes — worst relative residual $(js_to_exponential(a.worst, 1))"
        a.worst_family === nothing || (out_line *= " ($(a.worst_family) at t = $(_rl_audit_num(a.at))$unit)")
        push!(out, out_line)
    else
        push!(out, "mass balance: DOES NOT CLOSE — relative residual $(js_to_exponential(a.worst, 2)) in " *
                   "$(js_text(a.worst_family)) at t = $(_rl_audit_num(a.at))$unit; a state held at zero, or an amount " *
                   "the equations moved that nothing accounts for")
    end
    for f in a.families
        if f.unresolved
            push!(out, "  $(f.name): never more than $(_rl_audit_num(f.scale)) held or moved, within the absolute " *
                       "tolerance $(_rl_audit_num(f.floor)) -- too little for the solver to resolve, so not audited")
            continue
        end
        if f.idle
            push!(out, "  $(f.name): nothing held or moved")
            continue
        end
        r = f.final
        parts = ["start $(_rl_audit_num(r["start"]))", "+ in $(_rl_audit_num(r["in"]))",
                 "− out $(_rl_audit_num(r["out"]))", "− decay $(_rl_audit_num(r["decay"]))",
                 "+ ingrowth $(_rl_audit_num(r["ingrowth"]))"]
        for key in ("explicit", "between")
            x = r[key]
            x == 0 || push!(parts, "$(x < 0 ? "−" : "+") $key $(_rl_audit_num(abs(x)))")
        end
        push!(out, "  $(f.name): holds $(_rl_audit_num(r["inventory"])) at the end = $(join(parts, " ")); residual " *
                   "$(_rl_audit_num(r["residual"])) ($(js_to_exponential(f.relative, 1)) relative, worst at t = " *
                   "$(_rl_audit_num(f.at))$unit)")
    end
    return out
end

_rl_given(v) = v !== nothing && !(v isa AbstractString && isempty(v))

"""One line per setting, in the order somebody reads them."""
function _rl_settings_lines(sim::AbstractDict, raw::AbstractDict)
    out = String[]
    put(label, v) = _rl_given(v) && push!(out, "  $label: $(js_text(v))")
    put("time unit", get(sim, "time_unit", nothing))
    put("span", "$(js_text(get(sim, "start_time", nothing))) – $(js_text(get(sim, "end_time", nothing)))")
    spacing = get(sim, "spacing", nothing)
    put("output times", spacing == "series" ? "a series of the model’s own" :
                        "$(js_text(something(get(sim, "output_points", nothing), "?"))), $(something(spacing, "log"))")
    put("solver", get(sim, "solver", nothing))
    put("relative tolerance", get(sim, "rtol", nothing))
    put("absolute tolerance", get(sim, "abstol", nothing))
    put("cannot go negative", get(sim, "non_negative", nothing) === false ? "off everywhere" : "per compartment")
    js_truthy(get(sim, "mass_balance", nothing)) && put("mass-balance audit", "on")
    js_truthy(get(sim, "auto_abstol", nothing)) &&
        put("tolerance follows the solution", "each component’s absolute tolerance rises with it")
    unit = something(get(raw, "decay_unit", nothing), get(raw, "decayUnit", nothing), "")
    put("decay unit", strip(js_text(unit)) == "mol" ? "mol" : "Bq")
    ceiling = get(sim, "decay_ceiling", nothing)
    (ceiling isa Real && ceiling > 0) && put("decay chains stop above", "$(js_text(ceiling)) years")
    return out
end

"""`s.slice(0, units)` in UTF-16 code units, as JavaScript counts them."""
function _rl_utf16_prefix(s::AbstractString, units::Int)
    n = 0
    for (i, c) in pairs(s)
        n += UInt32(c) >= 0x10000 ? 2 : 1
        n > units && return s[1:prevind(s, i)]
    end
    return String(s)
end

"""Every run of JavaScript's white space (`/\\s+/g`) as one space."""
function _rl_one_space(text::AbstractString)
    io = IOBuffer()
    gap = false
    for c in text
        if isspace(c) || c in ('\u00a0', '\ufeff', '\u2028', '\u2029', '\u1680', '\u202f', '\u205f', '\u3000')
            gap = true
        else
            gap && print(io, ' ')
            gap = false
            print(io, c)
        end
    end
    gap && print(io, ' ')
    return String(take!(io))
end

"""`date.toISOString()`: UTC, to the millisecond."""
_rl_iso(at::DateTime) = Dates.format(at, dateformat"yyyy-mm-ddTHH:MM:SS.sss") * "Z"

"""
    run_log_lines(res; project=nothing, build="", at=now) -> Vector{String}

The log of a deterministic run, as lines (the application's `runLogLines`):
the model, its settings, how the run went -- steps, how df/dy was obtained, a
split asked for, output points, timings -- what was held at zero, the
far-field paths' warnings and the mass-balance audit.
"""
function run_log_lines(res::Results; project=nothing, build::AbstractString="", at::DateTime=now(Dates.UTC))
    raw = project === nothing ? res.project.raw : project isa AbstractDict ? project : getproperty(project, :raw)
    sim = res.project.simulation
    s = res.stats
    out = String[]
    push!(out, "Kompartment run log" * (isempty(build) ? "" : " — build $build"))
    push!(out, _rl_iso(at))
    push!(out, "model: $(js_text(something(get(raw, "name", nothing), "Untitled")))")
    description = get(raw, "description", nothing)
    if description isa AbstractString && !isempty(description)
        push!(out, "  " * _rl_utf16_prefix(_rl_one_space(description), 200))
    end
    push!(out, "")
    push!(out, "settings")
    append!(out, _rl_settings_lines(get(raw, "simulation", sim) isa AbstractDict ? get(raw, "simulation", sim) : sim,
                                    raw))
    push!(out, "")
    push!(out, "run")
    if get(s, "integrated", nothing) === false
        push!(out, "  nothing integrated: no compartments, the algebraic blocks over the output grid")
    else
        push!(out, "  states: $(res.system.nstate)")
        push!(out, "  steps: $(js_text(something(get(s, "nsteps", nothing), "?"))), rejected: " *
                   "$(js_text(something(get(s, "nfailed", nothing), 0))), f evaluations: " *
                   "$(js_text(something(get(s, "nfevals", nothing), "?")))")
        js_truthy(get(s, "nbelowtol", nothing)) && push!(out, "  steps taken below tolerance: $(js_text(s["nbelowtol"]))")
        haskey(s, "events") && s["events"] !== nothing &&
            push!(out, "  events: $(js_text(s["events"])), restarts: $(js_text(something(get(s, "restarts", nothing), 0)))")
        haskey(s, "jumps") && s["jumps"] !== nothing &&
            push!(out, "  jumps: $(js_text(s["jumps"])) — package failures at a time and disruptive events, applied to " *
                       "the state at their corners")
        j = res.system.jacobian
        if j isa JacobianInfo && j.available
            push!(out, "  df/dy: analytic, $(get(s, "sparse", false) === true ? "sparse" : "dense")" *
                       (j.colours > 0 ? ", $(j.colours) colours" : "") * (j.constant ? ", constant" : ""))
        elseif j !== nothing
            reason = hasproperty(j, :reason) ? j.reason : nothing
            push!(out, "  df/dy: differenced" * (reason isa AbstractString && !isempty(reason) ? " — $reason" : ""))
        end
    end
    split = get(s, "split", nothing)
    if split isa AbstractDict && get(split, "used", false) !== true
        push!(out, "  not split ($(js_text(get(split, "mode", nothing)))): $(js_text(get(split, "why", nothing)))")
    end
    push!(out, "  output points: $(length(res.t))")
    push!(out, "  series: $(length(outputs(res)))")
    push!(out, "  compile: $(js_to_fixed(get(res.timing, "build_ms", 0.0), 1)) ms, solve: " *
               "$(js_to_fixed(get(res.timing, "solve_ms", 0.0), 0)) ms")
    held = held_at_zero(res)
    if !isempty(held)
        push!(out, "")
        push!(out, "held at zero: $(length(held)) state$(length(held) == 1 ? "" : "s") the model pushed below zero")
        for h in held[1:min(20, end)]
            push!(out, "  $(h.label): $(h.steps) steps, $(js_to_fixed(100 * h.fraction, 1))% of the run")
        end
        length(held) > 20 && push!(out, "  and $(length(held) - 20) more")
    end
    for (key, head) in (("farfield", n -> "semi-analytical far-field paths: $n unit response$(n == 1 ? "" : "s") " *
                                          "missed $(n == 1 ? "its" : "their") mass balance"),
                        ("layers", n -> "far-field matrix layers: $n $(n == 1 ? "path grows" : "paths grow") coarse at depth"))
        said = get(s, key, nothing)
        (said isa AbstractVector && !isempty(said)) || continue
        push!(out, "")
        push!(out, head(length(said)))
        for w in said
            push!(out, "  $(js_text(get(w, "block", nothing))): $(js_text(get(w, "message", nothing)))")
        end
    end
    audit = mass_balance(res)
    if audit !== nothing
        push!(out, "")
        append!(out, describe_audit(audit, get(sim, "time_unit", "")))
    end
    return out
end

"""The log of a probabilistic run or a tornado, as lines (`probabilisticLogLines`)."""
function probabilistic_log_lines(prob)
    s = prob.stats
    tornado = get(s, "tornado", nothing)
    out = String["", tornado !== nothing ? "tornado" : "probabilistic run",
                 "  $(tornado !== nothing ? "design points" : "realisations"): $(prob.iterations)"]
    if tornado === nothing
        push!(out, "  seed: $(js_text(get(s, "seed", nothing))), sampling: " *
                   "$(get(s, "latin", true) === false ? "independent draws" : "Latin hypercube")")
    else
        low = js_text(round_half_up(100 * tornado["low"]))
        high = js_text(round_half_up(100 * tornado["high"]))
        push!(out, "  swung to the $(low)th and $(high)th percentiles")
    end
    push!(out, "  sampled inputs: $(something(get(s, "sampled", nothing), length(prob.plan)))")
    if js_truthy(get(s, "correlated", nothing))
        adjusted = get(s, "correlationAdjusted", 0.0)
        push!(out, "  correlated inputs: $(s["correlated"])" *
                   (adjusted isa Real && adjusted > 0 ? ", target matrix moved by up to $(js_to_fixed(adjusted, 3)) " *
                                                        "to be achievable" : ""))
    end
    for p in something(get(s, "correlationProblems", nothing), String[])
        push!(out, "  correlation ignored: $p")
    end
    threads = get(s, "threads", 1)
    threads isa Integer && threads > 1 && push!(out, "  over $threads threads")
    push!(out, "  wall clock: $(js_to_fixed(get(s, "ms", 0.0) / 1000, 1)) s")
    if js_truthy(get(s, "failed", nothing))
        push!(out, "  failed realisations: $(s["failed"])")
        for line in something(get(s, "trouble", nothing), String[])
            push!(out, "    $line")
        end
    end
    return out
end

_rl_build() = "Julia $(pkgversion(@__MODULE__))"

"""
    run_log(res; project=nothing, build="Julia <version>", at=now) -> String

The log of a run, as the application's *Run log* shows it and a results
archive keeps it: the model, its settings and how the run went.
`run_log(prob)` gives a probabilistic run's.
"""
run_log(res::Results; project=nothing, build::AbstractString=_rl_build(), at::DateTime=now(Dates.UTC)) =
    join(run_log_lines(res; project, build, at), "\n")
run_log(prob) = join(probabilistic_log_lines(prob), "\n")
