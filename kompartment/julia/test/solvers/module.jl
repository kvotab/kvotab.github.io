# The solvers on their own, without the rest of the package: lang/jsmath.jl
# (for cpow and clog2) and src/solvers in a module of their own, the way
# module Kompartment includes them.
module SolverTest
using LinearAlgebra, SparseArrays, Printf
import FunctionWrappers
import FunctionWrappers: FunctionWrapper
const _SRC = normpath(joinpath(@__DIR__, "..", "..", "src"))
include(joinpath(_SRC, "lang", "jsmath.jl"))
include(joinpath(_SRC, "solvers", "solvers.jl"))
end
