# The integrators, and how they fail.
#
# Ports of the Python engine's own solvers (kompartment/engine/solvers): the
# variable-order NDF that is the default, the Rosenbrock 2-3 and the
# Dormand-Prince 4-5, the iteration matrix they factorise, the event location
# they share, and `variable_order` -- how a run's settings become the NDF's
# arguments. The per-state arithmetic is the Python engine's element for
# element and in its order (no fused multiply-adds, sums kept sequential), the
# powers in the step-size formulas are the C library's (`cpow`, as Python's
# `**` is), a dense matrix of up to 200 states is factorised by the
# application's own LU and a sparse one by its sparse LUs, as the Python
# engine factorises them -- so a run takes the Python engine's steps and gives
# its numbers to the last bit. A dense matrix of more than 200 states is
# LAPACK's in both, whose two builds can round differently.
#
# Messages are the Python engine's, word for word -- the indices they quote
# (a state, a column) are counted from zero as there.
#
# Included inside `module Kompartment`, which has `using LinearAlgebra,
# SparseArrays` and `import FunctionWrappers: FunctionWrapper`; needs
# `cpow` and `clog2` from lang/jsmath.jl.

"""A run the solver could not finish. `kind` says how, `t` where.

Kinds: 'span', 'tolerance', 'nonfinite', 'singular', 'stalled', 'steps',
'jacobian', 'aborted', 'output'. `t`, `last_t` are NaN where Python's are
None; `trace`, `last_y` and `stats` are empty until the solver fills them.
"""
mutable struct SolverError <: Exception
    kind::String
    message::String
    t::Float64
    trace::Vector{Any}
    last_t::Float64
    last_y::Vector{Float64}
    stats::Dict{String,Any}
    hint::Union{Nothing,String}
end

SolverError(kind::AbstractString, message::AbstractString, t::Real=NaN) =
    SolverError(String(kind), String(message), Float64(t), Any[], NaN, Float64[], Dict{String,Any}(), nothing)

Base.showerror(io::IO, e::SolverError) = print(io, e.message)

"""The derivative: `f!(dy, t, y)` writes every element of `dy`."""
const RHSFunction = FunctionWrapper{Nothing,Tuple{Vector{Float64},Float64,Vector{Float64}}}
"""A Jacobian's values: `evaluate(vals, t, y)` writes them and returns true, or returns false to decline."""
const JacobianEvaluate = FunctionWrapper{Bool,Tuple{Vector{Float64},Float64,Vector{Float64}}}
"""Event functions: `fun(out, t, y)` writes the `n` values."""
const EventFunction = FunctionWrapper{Nothing,Tuple{Vector{Float64},Float64,Vector{Float64}}}
"""`on_accepted(t, y)` / `on_output(t, y)`."""
const StepCallback = FunctionWrapper{Nothing,Tuple{Float64,Vector{Float64}}}
"""The NDF's own `on_step(t, nsteps)`: false aborts."""
const StepProgress = FunctionWrapper{Bool,Tuple{Float64,Int}}
"""A runner's `on_step(fraction, n, t)` (Python's opts['on_step']): false aborts."""
const RunProgress = FunctionWrapper{Bool,Tuple{Float64,Int,Float64}}
"""`landing(t, t_next)`: where a step from t to t_next is to end instead, or NaN (engine/landing.jl)."""
const StepLanding = FunctionWrapper{Float64,Tuple{Float64,Float64}}

"""
Rows for a solver's output (`opts["rows"]`), handed out in turn and used again from
the first by the next run (`reset_rows!`): a thread of a probabilistic run keeps
one, its realisations' series read out before the next starts, so that a large
model's rows -- hundreds of megabytes a realisation -- are not made anew each time.
"""
mutable struct RowPool
    rows::Vector{Vector{Float64}}
    next::Int
end
RowPool() = RowPool(Vector{Float64}[], 1)
reset_rows!(pool::RowPool) = (pool.next = 1; pool)

"""The next row of `pool`, holding a copy of `y`."""
function take_row!(pool::RowPool, y::Vector{Float64})
    k = pool.next
    pool.next = k + 1
    if k > length(pool.rows)
        push!(pool.rows, copy(y))
    elseif length(pool.rows[k]) == length(y)
        copyto!(pool.rows[k], y)
    else
        pool.rows[k] = copy(y)
    end
    return pool.rows[k]
end

include("pyfmt.jl")
include("pattern.jl")
include("kernels.jl")
include("sparselu.jl")
include("matrix.jl")
include("events.jl")
include("ndf.jl")
include("onestep.jl")
include("solverset.jl")
