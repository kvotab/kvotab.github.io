# Steps that end on the turns of a table rather than pass over a pulse
# (engine/landing.jl; kompartment/engine/landing.py and src/sim/landing.js in
# the other two engines, whose tests these follow).
#
# A table read at the clock that rises and falls back between two steps used to
# go unseen: a pulse after a time of none arrived as nothing, a spike on a
# steady release as the steady release alone. These pin the rule (where a step
# ends, by interpolation rule, and that a wiggle does not move it), which
# tables a model's rule is made from, and that the package's solvers now
# deliver what the table puts out.

module LandingTests

using Test
using Kompartment
const K = Kompartment

table(points, interpolation="linear") = (x=[p[1] for p in points], y=[p[2] for p in points], interpolation=interpolation)

const PULSES = (
    ("a pulse at 1e4 after none", [[0, 0], [1e4, 0], [1e4 + 10, 1], [1e4 + 20, 0], [1e6, 0]]),
    ("a pulse at 3e5 after none", [[0, 0], [3e5, 0], [3e5 + 10, 1], [3e5 + 20, 0], [1e6, 0]]),
    ("a spike on a steady release", [[0, 1e-6], [1e4, 1e-6], [1e4 + 10, 1], [1e4 + 20, 1e-6], [1e6, 1e-6]]),
)

"""Feed -> A at the table's rate, A -> Out slowly: whatever the table puts out is in A and Out at the end."""
pulse_model(points, solver) = K.Model(Dict{String,Any}(
    "name" => "pulse",
    "simulation" => Dict{String,Any}("start_time" => 0, "end_time" => 1e6, "output_points" => 50, "spacing" => "log",
                                     "solver" => solver, "rtol" => 1e-6, "abstol" => 1e-9, "time_unit" => "year"),
    "lookups" => Any[Dict{String,Any}("name" => "release", "interpolation" => "linear", "points" => points)],
    "compartments" => Any[Dict{String,Any}("name" => "Feed", "initial" => "1000"),
                          Dict{String,Any}("name" => "A", "initial" => "0"),
                          Dict{String,Any}("name" => "Out", "initial" => "0")],
    "transfers" => Any[Dict{String,Any}("name" => "in", "from" => "Feed", "to" => "A", "rate" => "release",
                                        "multiply_by_donor" => false),
                       Dict{String,Any}("name" => "drain", "from" => "A", "to" => "Out", "rate" => "1e-3")],
))

integral(points) = sum((points[i][1] - points[i-1][1]) * (points[i][2] + points[i-1][2]) / 2 for i in 2:length(points))

landing_of(raw, rtol) = K.table_landing(K.build_system(K.Project(raw); jacobian=false), rtol)

@testset "where a step ends" begin
    pulse = [[0, 0], [10, 0], [20, 1], [30, 0], [100, 0]]
    land = K.table_landing([table(pulse)], 1e-3)
    @test land(0.0, 1000.0) == 20
    @test isnan(land(0.0, 25.0))            # a step that ends inside the pulse sees it
    @test land(15.0, 1000.0) == 30          # the pulse meets zero again: a turn of its own
    @test isnan(land(25.0, 1000.0))
    @test isnan(land(1000.0, 0.0))          # a step backwards lands nowhere
    @test K.table_landing([table(pulse, "below")], 1e-3)(0.0, 1000.0) == 25
    @test K.table_landing([table(pulse, "above")], 1e-3)(0.0, 1000.0) == 15
    @test K.table_landing([table(pulse, "nearest")], 1e-3)(0.0, 1000.0) == 20
    @test K.table_landing([table([[0, 1], [10, 1], [20, 0], [30, 1], [100, 1]])], 1e-3)(0.0, 1000.0) == 20  # a dip
    @test isnan(K.table_landing([table([[0, 1], [10, 1], [20, 1 + 1e-7], [30, 1], [1e4, 1]])], 1e-3)(0.0, 1e4))  # a wiggle
    land = K.table_landing([table([[0, 0], [500, 0], [510, 1], [520, 0]]), table(pulse)], 1e-3)
    @test (land(0.0, 1000.0), land(25.0, 1000.0)) == (20, 510)
    noisy = vcat([[0.0, 1.0]], [[Float64(i), 1 + (isodd(i) ? 1e-6 : 0.0)] for i in 1:400],
                 [[410, 1], [420, 50], [430, 1], [1000, 1]])
    land = K.table_landing([table(noisy)], 1e-3)
    @test land(0.0, 1000.0) == 420
    @test isnan(land(0.0, 405.0))           # only the small turns
    @test K.table_landing([table([[0, 0], [10, 1], [20, 2]]), table([[0, 5], [1, 5]])], 1e-3) === nothing
end

@testset "a model gets one only where a table turns" begin
    base = Dict{String,Any}(
        "name" => "turns",
        "simulation" => Dict{String,Any}("start_time" => 0, "end_time" => 100, "output_points" => 11,
                                         "spacing" => "linear", "rtol" => 1e-6, "abstol" => 1e-9),
        "compartments" => Any[Dict{String,Any}("name" => "A", "initial" => "1")],
        "transfers" => Any[Dict{String,Any}("name" => "T", "from" => "A", "to" => nothing, "rate" => "1e-3")])
    @test landing_of(base, 1e-6) === nothing
    base["transfers"] = Any[Dict{String,Any}("name" => "T", "from" => "A", "to" => nothing, "rate" => "L * 1e-3")]
    lookup(points; cyclic=false) =
        Any[Dict{String,Any}("name" => "L", "interpolation" => "linear", "points" => points, "cyclic" => cyclic)]
    @test landing_of(merge(base, Dict("lookups" => lookup([[0, 1], [50, 2], [100, 3]]))), 1e-6) === nothing
    @test landing_of(merge(base, Dict("lookups" => lookup([[0, 1], [50, 9], [100, 1]]))), 1e-6)(0.0, 100.0) == 50
    @test landing_of(merge(base, Dict("lookups" => lookup([[0, 1], [50, 9], [100, 1]]; cyclic=true))), 1e-6) === nothing
end

@testset "the pulses arrive" begin
    for parity in (false, true)
        K.set_parity!(parity)
        for (what, points) in PULSES, solver in ("ndf", "ros23", "dp45")
            total = integral(points)
            res = run(pulse_model(points, solver))
            got = res["A"][end] + res["Out"][end]
            @test abs(got / total - 1) < 1e-3
        end
    end
    K.set_parity!(false)
end

end # module
