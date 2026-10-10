# What a model's equations come to at the first instant, read back as the
# results read a run: the first row of the run's table.

module AtStartTests

using Test
using Kompartment
const K = Kompartment

@testset "values at start" begin
    m = K.load(joinpath(@__DIR__, "..", "..", "..", "examples", "biosphere.json"))
    res = run(m)
    v = values_at_start(m)
    for name in ("Soil", "Well", "Dose")
        got = v[name]
        @test got !== nothing
        for row in got["own"]
            @test row["value"] == res[row["label"]][1]
        end
    end
    @test v["no such block"] === nothing
    @test values_at_start(m, "Soil")["kind"] == "compartment"
    @test haskey(values_at_start(m, "Soil")["fields"], "initial")
end

end # module
