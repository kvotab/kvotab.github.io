# The package's tests. The parity tests against the Python package run only
# where their fixtures have been written (see each file and tools/*.py, and
# the README's table); everything else needs nothing but this package and the
# bundled examples.
#
#     julia --project=. test/runtests.jl
#     julia --project=. --threads=auto test/runtests.jl     # the probabilistic runs on threads too

using Test

# What auto learns of the runs here is not kept for later processes, and nothing kept from
# earlier ones decides whether a run here is split.
ENV["KOMPARTMENT_SPLIT_MEMORY"] = "0"

# Each file in a module of its own: several define the same helpers.
const FILES = [
    "util/basics.jl",
    "engine/known_answers.jl",
    "engine/parity.jl",
    "engine/runs.jl",
    "engine/farfield.jl",
    "engine/transport.jl",
    "engine/probabilistic.jl",
    "engine/analyses.jl",
    "engine/scenarios.jl",
    "engine/split.jl",
    "engine/fast.jl",
    "engine/speed.jl",
    "engine/atstart.jl",
    "engine/nonfinite.jl",
    "engine/landing.jl",
    "engine/runlog.jl",
    "model/normalise.jl",
    "model/edit.jl",
    "solvers/runtests.jl",
    "solvers/sparselu.jl",
    "io/test_hdf5.jl",
    "io/dataset.jl",
    "io/service.jl",
    "importers/test_eco.jl",
]

using Kompartment

@testset "Kompartment" begin
    for f in FILES
        # Every file in the engine's default, fast mode unless it asks for parity itself (those
        # checked against the Python package's own results).
        Kompartment.set_parity!(false)
        m = Module(Symbol(replace(f, r"[/.]" => "_")))
        Core.eval(m, :(include(x) = Base.include($m, x)))
        Base.include(m, joinpath(@__DIR__, f))
    end
end
