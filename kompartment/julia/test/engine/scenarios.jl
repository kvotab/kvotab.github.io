# A model's scenarios run one after the other and side by side on threads:
# the same runs either way, each the run of the model with its scenario chosen.

module ScenarioTests

using Test
using Kompartment
const K = Kompartment

@testset "scenarios" begin
    m = K.load(joinpath(@__DIR__, "..", "..", "..", "examples", "scenarios.json"))
    one = run_scenarios(m)
    @test collect(keys(one)) == ["Present", "Warmer and wetter", "Drier"]
    many = run_scenarios(m; threads=Threads.nthreads())
    @test all(one[k].t == many[k].t && one[k].y == many[k].y for k in keys(one))
    # Each is the model's own run with that scenario.
    raw = K.jcopy(m.raw)
    raw["scenario"] = "Drier"
    alone = run(K.Model(raw))
    @test alone.y == one["Drier"].y
    # Some, by name, with a setting replaced.
    two = run_scenarios(m, ["Drier", "Present"]; end_time=10)
    @test collect(keys(two)) == ["Drier", "Present"]
    @test two["Drier"].t[end] == 10
    @test_throws ArgumentError run_scenarios(K.load(joinpath(@__DIR__, "..", "..", "..", "examples", "decay-chain.json")))
    @test startswith(String(write_scenarios_hdf5(one)), "\x89HDF")
end

end # module
