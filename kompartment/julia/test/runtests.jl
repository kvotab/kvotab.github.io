# The package's tests. The parity tests against the Python package run only
# where their fixtures have been written (see each file and tools/*.py, and
# the README's table); everything else needs nothing but this package and the
# bundled examples.
#
#     julia --project=. test/runtests.jl
#     julia --project=. --threads=auto test/runtests.jl     # the probabilistic runs on threads too

using Test

# Each file in a module of its own: several define the same helpers.
const FILES = [
    "util/basics.jl",
    "engine/known_answers.jl",
    "engine/parity.jl",
    "engine/runs.jl",
    "engine/farfield.jl",
    "engine/transport.jl",
    "engine/probabilistic.jl",
    "engine/scenarios.jl",
    "engine/atstart.jl",
    "engine/runlog.jl",
    "model/normalise.jl",
    "model/edit.jl",
    "solvers/runtests.jl",
    "io/test_hdf5.jl",
    "io/dataset.jl",
    "importers/test_eco.jl",
]

@testset "Kompartment" begin
    for f in FILES
        m = Module(Symbol(replace(f, r"[/.]" => "_")))
        Core.eval(m, :(include(x) = Base.include($m, x)))
        Base.include(m, joinpath(@__DIR__, f))
    end
end
