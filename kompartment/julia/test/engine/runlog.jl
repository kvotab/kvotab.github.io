# The run log, and the number formats it writes as the page writes them.

module RunLogTests

using Test
using Kompartment
const K = Kompartment

# What Node prints for x.toFixed(0), x.toFixed(2), x.toExponential(1) and x.toExponential(3).
const JS = [(1.005, "1", "1.00", "1.0e+0", "1.005e+0"), (2.5, "3", "2.50", "2.5e+0", "2.500e+0"),
            (1.45, "1", "1.45", "1.4e+0", "1.450e+0"), (0.0, "0", "0.00", "0.0e+0", "0.000e+0"),
            (-0.0004, "-0", "-0.00", "-4.0e-4", "-4.000e-4"), (123456.789, "123457", "123456.79", "1.2e+5", "1.235e+5"),
            (1e21, "1e+21", "1e+21", "1.0e+21", "1.000e+21"), (5e-7, "0", "0.00", "5.0e-7", "5.000e-7"),
            (0.000123456, "0", "0.00", "1.2e-4", "1.235e-4"), (-2.5, "-3", "-2.50", "-2.5e+0", "-2.500e+0"),
            (1 / 3, "0", "0.33", "3.3e-1", "3.333e-1"), (1e-300, "0", "0.00", "1.0e-300", "1.000e-300"),
            (9.995, "10", "9.99", "1.0e+1", "9.995e+0")]

@testset "run log" begin
    for (x, f0, f2, e1, e3) in JS
        @test (K.js_to_fixed(x, 0), K.js_to_fixed(x, 2), K.js_to_exponential(x, 1), K.js_to_exponential(x, 3)) ==
              (f0, f2, e1, e3)
    end
    m = K.load(joinpath(@__DIR__, "..", "..", "..", "examples", "recorders.json"))
    lines = split(run_log(run(m)), "\n")
    @test startswith(lines[1], "Kompartment run log — build Julia")
    @test lines[3] == "model: Peak dose and when it happened"
    @test "  steps: 2205, rejected: 12, f evaluations: 6643" in lines
    @test "  df/dy: analytic, dense, 2 colours" in lines
    prob = run_probabilistic(K.load(joinpath(@__DIR__, "..", "..", "..", "examples", "biosphere.json")), 8;
                             keep=["Dose"], threads=1)
    @test occursin("realisations: 8", run_log(prob))
end

end # module
