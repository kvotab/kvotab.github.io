# Fitting a model to numbers somebody already knows: the optimisers. The
# Python package's `kompartment/stats/optimise.py` (the application's
# `src/domain/optimise.js`); engine/calibrate.jl is the other half, what one
# evaluation of the model is.
#
# What is minimised is the sum of weighted squared residuals (`objective_of`),
# each measured on its target's own scale -- `absolute` (got - want),
# `relative` (divided by the target; the default) or `log` (the log of the
# ratio). The algorithms (`OPTIMISE_METHODS`), all derivative-free in the
# model, bound-constrained, deterministic given a seed, and reporting after
# every evaluation: Nelder-Mead (a simplex of n + 1 points; local, few
# evaluations), Levenberg-Marquardt (least squares on a finite-difference
# Jacobian of the residuals; fastest near a solution), differential evolution
# (`rand/1/bin`; slow, and the only global one).
#
# **The same steps as the application.** Every step is its arithmetic in its
# order, the random stream is mulberry32 (`Mulberry32`), a point is recognised
# as seen before by the same `toPrecision(12)` text, and the logarithmic space
# and scale use V8's `Math.log` and `Math.exp` (`js_log`, `js_exp`): run on the
# same function, the three methods here visit the same points in the same order
# and stop at the same evaluation as the application's and the Python package's.
# Faithful to a fault, too: Nelder-Mead keeps the unclamped points in its
# simplex (only the evaluation is clamped), so its centroid can lie outside the
# box.
#
# References: Nelder & Mead 1965; Marquardt 1963; Storn & Price 1997.

"""An optimisation that cannot start ("Nothing to vary."), or -- inside the
optimisers, where it is caught -- one being stopped ("stopped", "budget")."""
struct OptimiseError <: Exception
    message::String
end
Base.showerror(io::IO, e::OptimiseError) = print(io, e.message)

_op_is_num(v) = v isa Real && !(v isa Bool)
_op_is_finite_num(v) = _op_is_num(v) && isfinite(v)

"""`entryOf(table, key)`: the table's own entry for the key made a string, or nothing."""
_op_lookup(table::AbstractDict, key) = get(table, key isa AbstractString ? String(key) : _pd_js_str(key), nothing)

"""`signal?.aborted`: a function answering whether to stop, a dictionary with `"aborted"`, a `Ref`."""
function _op_aborted(signal)
    (signal === nothing || signal === _PD_MISSING) && return false
    signal isa Function && return _pd_truthy(signal())
    signal isa AbstractDict && return _pd_truthy(get(signal, "aborted", nothing))
    signal isa Ref && return _pd_truthy(signal[])
    return _pd_truthy(hasproperty(signal, :aborted) ? getproperty(signal, :aborted) : false)
end

# --- how a residual is measured, and how a variable moves ----------------------------------

_op_relative(got::Float64, want::Float64) = want == 0 ? got : (got - want) / abs(want)
_op_log_ratio(got::Float64, want::Float64) = (got > 0 && want > 0) ? js_log(got) - js_log(want) : NaN

"""How a residual is measured, by the key a target stores."""
const OPTIMISE_SCALES = Dict{String,Function}(
    "absolute" => (got, want) -> got - want,
    "relative" => _op_relative,
    "log" => _op_log_ratio,
)

"""How a variable moves between its bounds, by the key a variable stores: `(to, from, ok)`."""
const OPTIMISE_SPACES = Dict{String,NamedTuple{(:to, :from, :ok),Tuple{Function,Function,Function}}}(
    "linear" => (to=identity, from=identity, ok=(lo, hi) -> true),
    "log" => (to=js_log, from=js_exp, ok=(lo, hi) -> lo > 0 && hi > 0),
)

"""`readings[i]` as arithmetic reads it: missing is NaN."""
function _op_reading(readings, i::Int)
    i > length(readings) && return NaN
    v = readings[i]
    return _op_is_num(v) ? Float64(v) : _pd_to_number(v)
end

"""
    objective_of(readings, targets) -> (objective, residuals)

The objective from one set of endpoint readings: the sum of squares, and the
residuals. Each target is `{"value", "scale", "weight"}`: `scale` a key of
`OPTIMISE_SCALES` (relative when it names none), `weight` a positive number (1
otherwise) that multiplies the square. A residual that is not a number -- a
model that did not produce one there -- counts as a miss of 1e6 rather than as
NaN, which would make every comparison false and the search wander.
"""
function objective_of(readings, targets)
    total = 0.0
    residuals = Float64[]
    for (i, t) in enumerate(targets)
        scale = something(_op_lookup(OPTIMISE_SCALES, _pd_prop(t, "scale")), OPTIMISE_SCALES["relative"])
        w = _pd_prop(t, "weight")
        weight = _op_is_finite_num(w) && w > 0 ? Float64(w) : 1.0
        r = scale(_op_reading(readings, i), _pd_to_number(_pd_prop(t, "value")))
        use = _op_is_finite_num(r) ? sqrt(weight) * r : 1e6
        push!(residuals, use)
        total += use * use
    end
    return (objective=total, residuals=residuals)
end

# --- what every method shares --------------------------------------------------------------

_op_clamp(v::Float64, lo::Float64, hi::Float64) = v < lo ? lo : (v > hi ? hi : v)
_op_clamp_all(x, lower, upper) = Float64[_op_clamp(x[i], lower[i], upper[i]) for i in eachindex(x)]

"""`Float64Array.from(values)`, read to length `n`: past the end is NaN."""
function _op_numbers(values, n::Int)
    out = Float64[_pd_to_number(v) for v in Iterators.take(values, n)]
    while length(out) < n
        push!(out, NaN)
    end
    return out
end

function _op_bounds(lower, upper, n::Int)
    (lower === nothing || upper === nothing) && throw(ArgumentError("lower and upper bounds are required"))
    return _op_numbers(lower, n), _op_numbers(upper, n)
end

"""
An objective counted, stoppable and never asked twice for the same point
(`budgeted`). `keep`, where given, is asked after each evaluation for whatever
else of it the caller needs -- the residual vector Levenberg-Marquardt
differences -- which is stored with the point and handed back by `kept`.
"""
mutable struct _OpBudget
    f::Function
    max_evals::Float64
    on_step::Any
    signal::Any
    keep::Any
    evals::Int
    best::Float64
    best_x::Union{Nothing,Vector{Float64}}
    seen::Dict{String,Tuple{Float64,Any}}
    kept::Any
end
_OpBudget(f, max_evals, on_step, signal; keep=nothing) =
    _OpBudget(f, _pd_to_number(max_evals), on_step, signal, keep, 0, Inf, nothing, Dict{String,Tuple{Float64,Any}}(),
              nothing)

function _op_call!(b::_OpBudget, x::Vector{Float64})
    _op_aborted(b.signal) && throw(OptimiseError("stopped"))
    b.evals >= b.max_evals && throw(OptimiseError("budget"))
    # A simplex revisits a vertex it already knows; so does a population that
    # converged. Each of those is a whole integration.
    key = join((js_to_precision(v, 12) for v in x), ",")
    had = get(b.seen, key, nothing)
    if had !== nothing
        b.kept = had[2]
        return had[1]
    end
    b.evals += 1
    fx = b.f(copy(x))
    use = _op_is_finite_num(fx) ? Float64(fx) : Inf
    b.kept = b.keep === nothing ? nothing : b.keep()
    b.seen[key] = (use, b.kept)
    if use < b.best
        b.best = use
        b.best_x = copy(x)
    end
    b.on_step === nothing || b.on_step((evals=b.evals, fx=use, best=b.best, x=copy(x), best_x=b.best_x))
    return use
end

_op_done(b::_OpBudget, reason::AbstractString) =
    (x=b.best_x === nothing ? nothing : copy(b.best_x), fx=b.best, evals=b.evals, reason=String(reason))

# --- Nelder-Mead ----------------------------------------------------------------------------

"""
    nelder_mead(f, start; lower, upper, max_evals=400, tol=1e-8, on_step=nothing, signal=nothing)

Nelder-Mead, with the bounds applied by clamping (`nelderMead`): the textbook
coefficients (reflect 1, expand 2, contract 0.5, shrink 0.5), an initial
simplex that steps each coordinate by 5% of its range, converged when the
simplex's values agree to `tol`, relatively. Returns `(x, fx, evals, reason)`:
the best point seen (`nothing` if none was), its value, how many evaluations,
and why it stopped -- "converged", "budget" or "stopped".
"""
function nelder_mead(f, start; lower=nothing, upper=nothing, max_evals=nothing, tol=nothing, on_step=nothing,
                     signal=nothing)
    n = length(start)
    n == 0 && throw(OptimiseError("Nothing to vary."))
    max_evals = something(max_evals, 400)
    tol = Float64(something(tol, 1e-8))
    lower, upper = _op_bounds(lower, upper, n)
    budget = _OpBudget(f, max_evals, on_step, signal)
    at(x) = _op_call!(budget, _op_clamp_all(x, lower, upper))
    raw_start = collect(start)
    s0 = _op_numbers(raw_start, n)
    try
        # The simplex: the start, then one step along each axis.
        simplex = Vector{Float64}[copy(s0)]
        for i in 1:n
            x = copy(s0)
            span = upper[i] - lower[i]
            step = span > 0 ? span * 0.05 : abs(x[i]) * 0.05 + 1e-6
            x[i] = _op_clamp(x[i] + step, lower[i], upper[i])
            # A vertex that landed on top of another is no vertex: step the
            # other way rather than starting with a degenerate simplex.
            if _op_is_num(raw_start[i]) && x[i] == raw_start[i]
                x[i] = _op_clamp(Float64(raw_start[i]) - step, lower[i], upper[i])
            end
            push!(simplex, x)
        end
        fs = Float64[at(x) for x in simplex]
        while true
            # Sorted by value: the best first, the worst last, a stable sort.
            order = sortperm(fs; alg=MergeSort, lt=<)
            simplex = simplex[order]
            fs = fs[order]
            # Converged when the simplex has collapsed onto one value.
            spread = abs(fs[n+1] - fs[1]) / (abs(fs[1]) + abs(fs[n+1]) + 1e-300)
            spread < tol && return _op_done(budget, "converged")
            # The centroid of all but the worst.
            mid = zeros(n)
            for i in 1:n, k in 1:n
                mid[k] += simplex[i][k] / n
            end
            along(t) = Float64[mid[k] + t * (mid[k] - simplex[n+1][k]) for k in 1:n]
            xr = along(1.0)
            fr = at(xr)
            if fr < fs[1]
                xe = along(2.0)
                fe = at(xe)
                if fe < fr
                    simplex[n+1], fs[n+1] = xe, fe
                else
                    simplex[n+1], fs[n+1] = xr, fr
                end
                continue
            end
            if fr < fs[n]
                simplex[n+1], fs[n+1] = xr, fr
                continue
            end
            # Contract, on whichever side is better.
            xc = fr < fs[n+1] ? along(0.5) : along(-0.5)
            fc = at(xc)
            if fc < (fs[n+1] < fr ? fs[n+1] : fr)
                simplex[n+1], fs[n+1] = xc, fc
                continue
            end
            # Nothing helped: pull everything halfway towards the best.
            for i in 2:n+1
                x = Float64[simplex[1][k] + 0.5 * (simplex[i][k] - simplex[1][k]) for k in 1:n]
                simplex[i] = _op_clamp_all(x, lower, upper)
                fs[i] = at(simplex[i])
            end
        end
    catch e
        e isa OptimiseError || rethrow()
        return _op_done(budget, e.message)
    end
end

# --- Levenberg-Marquardt --------------------------------------------------------------------

"""Gauss with partial pivoting; `nothing` where the matrix is singular."""
function _op_solve(A::Vector{Vector{Float64}}, b::Vector{Float64})
    n = length(b)
    M = [vcat(A[i][1:n], b[i]) for i in 1:n]
    for c in 1:n
        p = c
        for i in c+1:n
            abs(M[i][c]) > abs(M[p][c]) && (p = i)
        end
        abs(M[p][c]) > 1e-300 || return nothing
        M[c], M[p] = M[p], M[c]
        for i in c+1:n
            k = M[i][c] / M[c][c]
            k == 0 && continue
            row, pivot = M[i], M[c]
            for j in c:n+1
                row[j] -= k * pivot[j]
            end
        end
    end
    x = zeros(n)
    for i in n:-1:1
        s = M[i][n+1]
        for j in i+1:n
            s -= M[i][j] * x[j]
        end
        x[i] = s / M[i][i]
    end
    return x
end

"""`values[i]`, NaN past the end."""
_op_index(values, i::Int) = i <= length(values) ? values[i] : NaN

"""
    levenberg_marquardt(residuals, start; lower, upper, max_evals=400, tol=1e-10, on_step=nothing, signal=nothing)

Levenberg-Marquardt on a finite-difference Jacobian (`levenbergMarquardt`):
`residuals(x)` gives the vector whose squares are summed. Each iteration
differences it once per variable, forward, by 1e-6 of the variable's range (or
of `|x| + 1` for one with none), solves the damped normal equations
`(JᵀJ + λ·diag(JᵀJ)) dx = Jᵀr` by Gauss elimination, and slides λ down by ten
when a step helps and up by ten when it does not. Converged when a step gains
less than `tol` relatively, or no step helps. Returns as `nelder_mead`.
"""
function levenberg_marquardt(residuals, start; lower=nothing, upper=nothing, max_evals=nothing, tol=nothing,
                             on_step=nothing, signal=nothing)
    n = length(start)
    n == 0 && throw(OptimiseError("Nothing to vary."))
    max_evals = something(max_evals, 400)
    tol = Float64(something(tol, 1e-10))
    lower, upper = _op_bounds(lower, upper, n)
    last = Ref{Any}(nothing)
    function f(x)
        last[] = residuals(x)
        s = 0.0
        for r in last[]
            s += r * r
        end
        return _op_is_finite_num(s) ? s : Inf
    end
    # The residuals are kept with the point they belong to, so a point the
    # budget answers from memory comes back with its own.
    budget = _OpBudget(f, max_evals, on_step, signal;
                       keep=() -> last[] === nothing ? nothing : Float64[_pd_to_number(v) for v in last[]])
    function eval_at(x)
        fx = _op_call!(budget, _op_clamp_all(x, lower, upper))
        k = budget.kept
        return fx, (k === nothing ? nothing : copy(k))
    end
    try
        x = _op_clamp_all(_op_numbers(start, n), lower, upper)
        fx, r = eval_at(x)
        r === nothing && return _op_done(budget, "no residuals")
        m = length(r)
        lam = 1e-3
        while true
            # The Jacobian, column by column: one extra evaluation each.
            J = Vector{Float64}[]
            for k in 1:n
                span = upper[k] - lower[k]
                a, b = (span > 0 ? span : abs(x[k]) + 1) * 1e-6, abs(x[k]) * 1e-9
                h = b > a ? b : a
                xp = copy(x)
                xp[k] = _op_clamp(x[k] + h, lower[k], upper[k])
                xp[k] == x[k] && (xp[k] = _op_clamp(x[k] - h, lower[k], upper[k]))
                step = xp[k] - x[k]
                if step == 0
                    push!(J, zeros(m))
                    continue
                end
                _, got_r = eval_at(xp)
                push!(J, Float64[(_op_index(got_r, i) - r[i]) / step for i in 1:m])
            end
            # JᵀJ and Jᵀr, which are n x n and n however long the residual vector is.
            A = [zeros(n) for _ in 1:n]
            g = zeros(n)
            for a in 1:n
                for b in a:n
                    s = 0.0
                    Ja, Jb = J[a], J[b]
                    for i in 1:m
                        s += Ja[i] * Jb[i]
                    end
                    A[a][b] = s
                    A[b][a] = s
                end
                s = 0.0
                Ja = J[a]
                for i in 1:m
                    s += Ja[i] * r[i]
                end
                g[a] = s
            end
            stepped = false
            for _ in 1:12
                M = Vector{Float64}[]
                for a in 1:n
                    row = copy(A[a])
                    # Marquardt's own scaling: the damping follows the curvature
                    # rather than being the same in every direction.
                    row[a] += lam * (A[a][a] > 0 ? A[a][a] : 1.0)
                    push!(M, row)
                end
                dx = _op_solve(M, g)
                if dx === nothing
                    lam *= 10
                    continue
                end
                trial = Float64[x[k] - dx[k] for k in 1:n]
                got_fx, got_r = eval_at(trial)
                if got_fx < fx
                    gain = (fx - got_fx) / (abs(fx) + 1e-300)
                    x = _op_clamp_all(trial, lower, upper)
                    fx = got_fx
                    r = got_r
                    lam = 1e-12 > lam / 10 ? 1e-12 : lam / 10
                    stepped = true
                    gain < tol && return _op_done(budget, "converged")
                    break
                end
                lam *= 10
                lam > 1e12 && return _op_done(budget, "converged")
            end
            stepped || return _op_done(budget, "converged")
        end
    catch e
        e isa OptimiseError || rethrow()
        return _op_done(budget, e.message)
    end
end

# --- differential evolution -----------------------------------------------------------------

"""
    differential_evolution(f; lower, upper, start=nothing, pop_size=0, max_evals=2000, seed=1,
                           F=0.7, CR=0.9, on_step=nothing, signal=nothing)

Differential evolution, `rand/1/bin` (`differentialEvolution`): a population
spread over the whole box -- `pop_size`, or ten per variable between 8 and 60 --
each member crossed with another plus `F` times the difference between two
more, coordinate by coordinate with probability `CR` (and always in one). The
start, where there is one, is the first member; the stream is mulberry32
seeded with `seed`. Converged when the whole population agrees to 1e-10,
relatively. Returns as `nelder_mead`.
"""
function differential_evolution(f; lower=nothing, upper=nothing, start=nothing, pop_size=0, max_evals=nothing,
                                seed=1, F=nothing, CR=nothing, on_step=nothing, signal=nothing)
    lower === nothing && throw(ArgumentError("lower and upper bounds are required"))
    n = length(lower)
    n == 0 && throw(OptimiseError("Nothing to vary."))
    lower, upper = _op_bounds(lower, upper, n)
    max_evals = something(max_evals, 2000)
    F = Float64(something(F, 0.7))
    CR = Float64(something(CR, 0.9))
    # Ten per variable is the usual advice, floored so a one-variable problem
    # still has a population and capped so a ten-variable one still finishes.
    size_ = _pd_to_number(pop_size)
    N = size_ > 3 ? size_ : Float64(min(60, max(8, 10n)))
    nxt = Mulberry32(seed)
    budget = _OpBudget(f, max_evals, on_step, signal)
    try
        pop = Vector{Float64}[]
        fit = Float64[]
        first = _pd_truthy(start) ? _op_numbers(start, n) : nothing
        i = 0
        while i < N
            x = if i == 0 && first !== nothing
                Float64[_op_clamp(first[k], lower[k], upper[k]) for k in 1:n]
            else
                Float64[lower[k] + next_uniform!(nxt) * (upper[k] - lower[k]) for k in 1:n]
            end
            push!(pop, x)
            push!(fit, _op_call!(budget, x))
            i += 1
        end
        while true
            i = 0
            while i < N
                a = b = c = i
                while a == i
                    a = floor(Int, next_uniform!(nxt) * N)
                end
                while b == i || b == a
                    b = floor(Int, next_uniform!(nxt) * N)
                end
                while c == i || c == a || c == b
                    c = floor(Int, next_uniform!(nxt) * N)
                end
                # At least one coordinate always comes from the mutant, or a
                # trial could be its own parent and the population stall.
                must = floor(Int, next_uniform!(nxt) * n)
                pa, pb, pc, pi_ = pop[a+1], pop[b+1], pop[c+1], pop[i+1]
                trial = zeros(n)
                for k in 0:n-1
                    if k == must || next_uniform!(nxt) < CR
                        trial[k+1] = _op_clamp(pa[k+1] + F * (pb[k+1] - pc[k+1]), lower[k+1], upper[k+1])
                    else
                        trial[k+1] = pi_[k+1]
                    end
                end
                ft = _op_call!(budget, trial)
                if ft <= fit[i+1]
                    pop[i+1] = trial
                    fit[i+1] = ft
                end
                i += 1
            end
            # Converged when the whole population agrees.
            lo = minimum(fit)
            hi = maximum(fit)
            hi - lo <= abs(lo) * 1e-10 && return _op_done(budget, "converged")
        end
    catch e
        e isa OptimiseError || rethrow()
        return _op_done(budget, e.message)
    end
end

"""
The three methods, by the key a file stores: each `run(ctx, opts)` takes
`ctx = (start, objective, residuals)` and the options (`lower`, `upper`,
`max_evals`, `seed`, `on_step`, `signal`); what a method does not read it ignores.
"""
const OPTIMISE_METHODS = Dict{String,Function}(
    "nelder" => (ctx, o) -> nelder_mead(ctx.objective, ctx.start; lower=o.lower, upper=o.upper,
                                        max_evals=o.max_evals, on_step=o.on_step, signal=o.signal),
    "lm" => (ctx, o) -> levenberg_marquardt(ctx.residuals, ctx.start; lower=o.lower, upper=o.upper,
                                            max_evals=o.max_evals, on_step=o.on_step, signal=o.signal),
    "de" => (ctx, o) -> differential_evolution(ctx.objective; lower=o.lower, upper=o.upper, start=ctx.start,
                                               max_evals=o.max_evals, seed=o.seed, on_step=o.on_step,
                                               signal=o.signal),
)
