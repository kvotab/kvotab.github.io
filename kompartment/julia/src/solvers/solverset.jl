# The solvers a run can be given, by the id the model file stores
# (engine/solverset.py: the NDF, the Rosenbrock 2-3 and the Dormand-Prince
# 4-5). Each takes `(f, tspan, y0, opts)` with `f!(dy, t, y)` the derivative
# and `opts` a Dict{String,Any} with the Python engine's keys, and returns a
# `Solution`: a row per requested time reached, and where an event stopped
# the run.

const SOLVER_HINTS = Dict{String,String}(
    "singular" => "A compartment with no way in and no way out will do this.",
    "noPattern" => "Give the model an analytic Jacobian, or run fewer states.",
)

_solverset_non_finite_error(at::Float64) =
    SolverError("nonfinite", "The simulation produced a value that is not a number at t=$(_pyrepr(at)). An " *
                             "equation divides by zero, takes the log of zero or a negative, or overflows; the state " *
                             "or rate that went first is where to look.", at)

"""What `variableOrder` says when the NDF fails with `e`."""
function variable_order_failure(e::SolverError, t0::Float64)::SolverError
    (e.kind == "aborted" || e.kind == "span") && return e
    at = isnan(e.t) ? t0 : e.t
    if e.kind == "stalled" || e.kind == "steps"
        return SolverError(e.kind, "$(e.message) Something is holding a state where it cannot go: most often a " *
                                   "compartment kept at zero by \"cannot go negative\" while its equations push it " *
                                   "below. Turn that setting off on the compartment to see what the model really " *
                                   "does.", at)
    end
    e.kind == "nonfinite" && return _solverset_non_finite_error(at)
    if e.kind == "singular" || e.kind == "jacobian"
        return SolverError(e.kind, e.message, at)
    end
    return SolverError(e.kind, "variableOrder failed: $(e.message). If the model is not stiff, dormandPrince may do " *
                               "better; if it is very stiff, try tightening the tolerances.", at)
end

"""
    variable_order(f, tspan, y0, opts) -> Solution

The NDF (BDF with `opts["bdf"]`): `variableOrder` in the application, the
Python engine's `solverset.variable_order`. `opts` keys as Python's:
"rtol", "abstol" (a number or a vector), "non_negative" (a Bool per state),
"max_order", "bdf", "hmax", "h0", "max_steps", "error_norm",
"norm_control", "matrix", "below_tol_run", "stagnation_tol", "jacobian"
(a JacobianSpec), "events" (EventFunctions), "on_accepted" and "on_output"
(called `(t, y)`), "on_step" (called `(fraction, n, t)` every 64 derivative
evaluations; false aborts), "auto_abstol", "ends_only"; "carry" and the
rest are read by other solvers and ignored here.
"""
function variable_order(f::RHSFunction, tspan_in::AbstractVector{<:Real}, y0::AbstractVector{<:Real},
                        opts::AbstractDict)::Solution
    tspan = Vector{Float64}(tspan_in)
    t0, t_final = tspan[1], tspan[end]
    if !(abs(t_final - t0) > 0)
        throw(SolverError("span", "Simulation start and end time are equal", t0))
    end
    abstol = get(opts, "abstol", 1e-6)
    nn = _opt(opts, "non_negative")
    non_negative = nn === nothing ? Int[] : Int[i for (i, v) in enumerate(nn) if _truthy(v)]
    span = abs(t_final - t0)
    span = span != 0 ? span : 1.0
    on_step = _run_progress(_opt(opts, "on_step"))
    counter = Ref(0)
    fun = if on_step === nothing
        RHSFunction((dy, t, y) -> begin
            counter[] += 1
            f(dy, t, y)
            nothing
        end)
    else
        last = Ref(0.0)
        RHSFunction((dy, t, y) -> begin
            counter[] += 1
            f(dy, t, y)
            if (counter[] & 63) == 0
                progress = _pymin(1.0, abs(t - t0) / span)
                if progress > last[]
                    last[] = progress
                    if !on_step(progress, counter[], t)
                        throw(SolverError("aborted", "Simulation aborted", t))
                    end
                end
            end
            nothing
        end)
    end
    max_steps = _opt(opts, "max_steps")
    stagnation = _opt(opts, "stagnation_tol")
    error_norm = _opt(opts, "error_norm")
    matrix = _opt(opts, "matrix")
    below = _opt(opts, "below_tol_run")
    events = _opt(opts, "events")
    result = try
        ndf(fun, tspan, y0;
            rtol=Float64(_opt_or(opts, "rtol", 1e-3)),
            abstol=abstol isa Real ? Float64(abstol) : abstol,
            non_negative=non_negative,
            hmax=Float64(_opt_or(opts, "hmax", 0.0)),
            h0=Float64(_opt_or(opts, "h0", 0.0)),
            max_order=_opt_or(opts, "max_order", 5),
            jacobian=_jacobian_spec(_opt(opts, "jacobian")),
            bdf=_truthy(_opt(opts, "bdf")),
            hints=SOLVER_HINTS,
            norm_control=_truthy(_opt(opts, "norm_control")),
            auto_abstol=_truthy(_opt(opts, "auto_abstol")),
            ends_only=_truthy(_opt(opts, "ends_only")),
            events=events === nothing ? nothing : events::EventFunctions,
            on_accepted=_step_callback(_opt(opts, "on_accepted")),
            on_output=_step_callback(_opt(opts, "on_output")),
            max_steps=_truthy(max_steps) ? Float64(max_steps) : 1e6,
            stagnation_tol=(stagnation !== nothing && stagnation > 0) ? Float64(stagnation) : 0.0,
            error_norm=_truthy(error_norm) ? String(error_norm) : "max",
            matrix=_truthy(matrix) ? String(matrix) : "auto",
            below_tol_run=below === nothing ? nothing : Float64(below))
    catch e
        e isa SolverError || rethrow()
        failure = variable_order_failure(e, t0)
        failure === e && rethrow()
        throw(failure)
    end
    if isempty(result.t) || isempty(result.y)
        throw(SolverError("output", "the variable-order solver produced no output", t0))
    end
    s = result.stats
    stats = Dict{String,Any}("nsteps" => s["nsteps"], "nfailed" => s["nfailed"], "nfevals" => counter[],
                             "npds" => s["npds"], "ndecomps" => s["ndecomps"], "nsolves" => s["nsolves"],
                             "nbelowtol" => s["nbelowtol"], "sparse" => get(s, "sparse", false),
                             "fill" => get(s, "fill", nothing), "negative" => get(s, "negative", 0),
                             "held" => get(s, "held", nothing), "points" => length(result.t),
                             "solver" => _truthy(_opt(opts, "bdf")) ? "bdf" : "ndf")
    return Solution(result.t, result.y, result.end_t, result.end_y, result.stopped, stats)
end

"""The solvers by id, each `(f, tspan, y0, opts) -> Solution`."""
const SOLVERS = Dict{String,Function}(
    "ndf" => variable_order,
    "ros23" => rosenbrock23,
    "dp45" => dormand_prince,
)
