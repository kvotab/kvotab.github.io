# A run that meets a value that is not a number says where it starts, in the
# application's words (engine/nonfinite.jl; src/sim/nonfinite.js and the
# Python engine's tests/test_nonfinite.py hold the same sentences); the
# warnings at the start of a run say the same before one; and the seeds of the
# blocks that remember are worked out until they settle.

module NonFiniteTests

using Test
using Kompartment
const K = Kompartment

const SIMULATION = """{"start_time": 0, "end_time": 10, "output_points": 3, "spacing": "linear", "solver": "SOLVER",
    "rtol": 1e-6, "abstol": 1e-9, "time_unit": "year"}"""

# Packages that may crack: none have, and the concentration in them is 0/0.
cracked(solver="ndf"; n_cracked=0, initial="0") = K.from_json("""{
    "name": "cracked packages", "nuclides": ["Cs-137", "Sr-90"],
    "simulation": $(replace(SIMULATION, "SOLVER" => solver)),
    "index_lists": [{"name": "Radionuclides", "for_contaminants": true,
                     "indices": [{"name": "Cs-137"}, {"name": "Sr-90"}]}],
    "parameters": [{"name": "N_cracked", "value": $n_cracked}, {"name": "V", "value": 2},
                   {"name": "limit", "value": 100}],
    "compartments": [{"name": "Waste", "initial": "$initial", "index_lists": ["Radionuclides"]},
                     {"name": "Wall", "initial": "0", "index_lists": ["Radionuclides"]}],
    "expressions": [{"name": "C_waste", "equation": "min(Waste/(V*N_cracked), limit)", "index_lists": ["Radionuclides"]},
                    {"name": "C_out", "equation": "Wall/(V*N_cracked)", "index_lists": ["Radionuclides"]}],
    "transfers": [{"name": "Diffusion", "from": "Waste", "to": "Wall", "rate": "N_cracked*C_waste",
                   "multiply_by_donor": false, "index_lists": ["Radionuclides"]}],
    "inflows": []}""")

const CRACKED_SAYS = "The simulation produced a value that is not a number at t=0. It starts in C_waste " *
                     "[Radionuclides=Cs-137] (and 1 more of its indices): Waste/(V*N_cracked) comes to 0/0, with " *
                     "Waste = 0, V = 2 and N_cracked = 0. It reaches 2 compartments, 4 states in all: Waste and Wall, " *
                     "through the transfer Diffusion."

const STOPS = "Comes to NaN at the start at Radionuclides=Cs-137 (and 1 more of its indices): Waste/(V*N_cracked) " *
              "comes to 0/0, with Waste = 0, V = 2 and N_cracked = 0. The run reads it, through the transfer " *
              "Diffusion, so it will stop at its first step."
const GOES_ON = "Comes to NaN at the start at Radionuclides=Cs-137 (and 1 more of its indices): Wall/(V*N_cracked) " *
                "comes to 0/0, with Wall = 0, V = 2 and N_cracked = 0. Only results read it, so a run goes on, with " *
                "these values at its first point."

function failure(m)
    try
        run(m)
    catch e
        e isa K.SolverError && return e
        rethrow()
    end
    error("the run went")
end

@testset "a value that is not a number says where it starts" begin
    for solver in ("ndf", "ros23", "dp45")
        e = failure(cracked(solver))
        @test e.message == CRACKED_SAYS
        @test e.block_name == "C_waste"
        @test e.solver_message !== nothing && e.solver_message != e.message
        @test e.hint === nothing
    end

    # A compartment a hair below zero under a square root: the state the solver
    # held gives numbers, and the step it could not take does not.
    below_zero(solver) = K.from_json("""{
        "name": "below zero",
        "simulation": $(replace(replace(SIMULATION, "SOLVER" => solver), "\"output_points\": 3" => "\"output_points\": 20",
                                "\"time_unit\"" => "\"non_negative\": false, \"time_unit\"")),
        "compartments": [{"name": "A", "initial": "1", "non_negative": false}, {"name": "B", "initial": "0"}],
        "expressions": [{"name": "R", "equation": "sqrt(A)"}],
        "transfers": [{"name": "Drain", "from": "A", "to": "B", "rate": "0.5 + 0*R", "multiply_by_donor": false},
                      {"name": "Leak", "from": "B", "to": null, "rate": "0.01*R", "multiply_by_donor": false}],
        "parameters": [], "inflows": []}""")
    said = r"^The simulation produced a value that is not a number at t=([\d.e+-]+)\. The state it held there gives numbers; a step of [\d.e+-]+ past it does not\. It starts in R: sqrt\(A\) comes to sqrt\(-[\d.e+-]+\), with A = -[\d.e+-]+\. It reaches 2 compartments, 2 states in all: A and B, through the transfers Drain and Leak\.$"
    for solver in ("ndf", "ros23", "dp45")
        e = failure(below_zero(solver))
        m = match(said, e.message)
        @test m !== nothing
        m === nothing || @test isapprox(parse(Float64, m.captures[1]), 2.0; atol=1e-9)
        @test e.block_name == "R"
    end
end

@testset "the warnings at the start" begin
    w = K.values_at_start(cracked()).warnings
    @test length(w) == 2
    @test w[1]["block"] == "C_waste" && w[1]["stops"] === true && w[1]["message"] == STOPS
    @test w[2]["block"] == "C_out" && w[2]["stops"] === false && w[2]["message"] == GOES_ON
    @test isempty(K.values_at_start(cracked(; n_cracked=1)).warnings)
    bad = K.values_at_start(cracked(; initial="0/N_cracked")).warnings
    @test length(bad) == 1 && bad[1]["block"] == "Waste" && bad[1]["stops"] === true &&
          bad[1]["message"] == "Its initial value comes to NaN at Radionuclides=Cs-137 (and 1 more of its indices), " *
                               "so a run cannot start."
end

@testset "an equation is written back as the parser read it, and as the application writes it" begin
    written_back = [
        "a/(b*c)" => "a/(b*c)", "a-b-c" => "a - b - c", "a-(b-c)" => "a - (b - c)", "-a^2" => "-a^2",
        "(-a)^2" => "(-a)^2", "2^-3" => "2^-3", "2^-3^2" => "2^-3^2", "a^b^c" => "a^b^c", "a^(b^c)" => "a^(b^c)",
        "-(a*b)" => "-(a*b)", "-a*b" => "-a*b", "a*-b" => "a*-b", "min(a, b*c, -d)" => "min(a, b*c, -d)",
        "x>1 && y<2" => "x > 1 && y < 2", "(a || b) && c" => "(a || b) && c",
        "a ? b : c ? d : e" => "a ? b : (c ? d : e)", "(a ? b : c) + 1" => "(a ? b : c) + 1",
        "if(c, a+1, b)" => "if(c, a + 1, b)", "a*(b+c)/d" => "a*(b + c)/d", "1e-5*a" => "0.00001*a",
        "0.01[m]*a" => "0.01[m]*a", "Cs[Cs-137]*2" => "Cs[Cs-137]*2", "M[_Ra-226][Pb-210]" => "M[_Ra-226][Pb-210]",
        "M[][x]" => "M[][x]", "a == b" => "a == b", "a ~= b" => "a ~= b", "not(z)" => "not(z)",
        "exp(-(a+b)/c)" => "exp(-(a + b)/c)", "sqrt(a - b)^0.5" => "sqrt(a - b)^0.5",
    ]
    for (eq, written) in written_back
        text = K.equation_text(K.parse_equation(eq))
        @test text == written
        @test repr(K.parse_equation(text)) == repr(K.parse_equation(eq))
    end
end

@testset "a peak read through a delay starts at its target" begin
    # The seeds were worked out in one pass, before any block that remembers had
    # a history: the delayed volume read 0, the dose divided by it, and the peak
    # kept what that made for the whole run.
    m = K.from_json("""{
        "name": "peak through a delay", "simulation": $(replace(SIMULATION, "SOLVER" => "ndf")),
        "lookups": [{"name": "V", "points": [[0, 2], [10, 2]]}],
        "delays": [{"name": "V_delay", "target": "V", "delay": "0.001"}],
        "compartments": [{"name": "A", "initial": "1"}],
        "transfers": [{"name": "Out", "from": "A", "to": null, "rate": "0.1"}],
        "expressions": [{"name": "Dose", "equation": "A/V_delay"}],
        "min_maxes": [{"name": "Peak", "operation": "max", "target": "Dose"}],
        "parameters": [], "inflows": []}""")
    res = run(m)
    peak, dose = res["Peak"], res["Dose"]
    @test all(isfinite, peak)
    @test isapprox(peak[1], 0.5; atol=1e-12)
    @test isapprox(peak[1], dose[1]; atol=1e-12)
    @test isempty(K.values_at_start(m).warnings)
end

end # module
