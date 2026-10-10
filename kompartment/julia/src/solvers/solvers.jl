# The integrators, and how they fail.
#
# Ports of the Python engine's own solvers (kompartment/engine/solvers): the
# variable-order NDF that is the default, the Rosenbrock 2-3 and the
# Dormand-Prince 4-5, the iteration matrix they factorise, the event location
# they share, and `variable_order` -- how a run's settings become the NDF's
# arguments. The per-state arithmetic is the Python engine's element for
# element and in its order (no fused multiply-adds, sums kept sequential), the
# powers in the step-size formulas are the C library's (`cpow`, as Python's
# `**` is), and a dense matrix of up to 200 states is factorised by the
# application's own LU -- so on a dense problem a run takes the Python
# engine's steps and gives its numbers to the last bit. A sparse matrix is
# factorised by KLU (SuiteSparse) where Python uses SuperLU: there the two
# agree to the tolerance, not to the bit.
#
# Messages are the Python engine's, word for word -- the indices they quote
# (a state, a column) are counted from zero as there.
#
# Included inside `module Kompartment`, which has `using LinearAlgebra,
# SparseArrays` and `import FunctionWrappers: FunctionWrapper`; needs
# `cpow` and `clog2` from lang/jsmath.jl.

using SuiteSparse_jll: libklu

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

include("pyfmt.jl")
include("pattern.jl")
include("kernels.jl")
include("klu.jl")
include("matrix.jl")
include("events.jl")
include("ndf.jl")
include("onestep.jl")
include("solverset.jl")
