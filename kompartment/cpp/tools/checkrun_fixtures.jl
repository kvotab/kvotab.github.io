# Writes tests/fixtures/checkrun.json: Check the run by the Julia package with parity on, for
# the C++ engine's tests to compare with (tests/test_checkrun.cpp).
#
#     julia --project=. ../cpp/tools/checkrun_fixtures.jl        (from ../julia)
#
# Every model solved whole (`split` off: a split follows what earlier runs measured). For each
# bundled example below and three made-up models (a compartment with its own
# absolute tolerance and a step budget, a run that nearly holds and one that does not): what each state is
# called, and the report of a check of a run of it -- the careful run's time left out -- as
# the JSON text the service writes. Then runs made up to reach every rule of the comparison
# (a state not a number in one run, infinite in one, in both, one that never moves, one
# under the absolute tolerance over the relative, shares that tie, a careful run at other
# times), every number as its bits.

using Kompartment
const K = Kompartment
K.set_parity!(true)

bits(x::Real) = (y = Float64(x); isnan(y) ? "nan" : string(reinterpret(UInt64, y); base=16, pad=16))
const examples_dir = joinpath(@__DIR__, "..", "..", "examples")
J(pairs...) = K.JDict(pairs...)

function made_up(name; extra...)
    sim = J("start_time" => 0, "end_time" => 20, "output_points" => 21, "spacing" => "linear", "solver" => "ndf",
            "rtol" => 1e-3, "abstol" => 1e-8, "time_unit" => "year", "split" => "off")
    for (k, v) in extra
        sim[String(k)] = v
    end
    J("name" => name,
      "simulation" => sim,
      "parameters" => Any[J("name" => "k", "value" => "0.7", "unit" => "1/year")],
      "compartments" => Any[J("name" => "A", "initial" => "1", "unit" => "Bq", "index_lists" => Any[], "abstol" => "1e-12"),
                            J("name" => "B", "initial" => "0", "unit" => "Bq", "index_lists" => Any[])],
      "transfers" => Any[J("name" => "AB", "from" => "A", "to" => "B", "rate" => "k", "unit" => "1/year", "index_lists" => Any[])])
end

cases = Any[]
for ex in ("four-compartment", "decay-chain", "waste-packages", "landscape", "farfield", "lotka-volterra")
    m = K.parse_json(read(joinpath(examples_dir, ex * ".json"), String))
    # Solved whole: whether a run is split into its independent parts follows what earlier runs
    # measured, and a run in parts takes other steps.
    m["simulation"]["split"] = "off"
    push!(cases, J("name" => ex, "model" => m))
end
push!(cases, J("name" => "own tolerance and a budget", "model" => made_up("own"; max_steps=5000)))
# Loose enough that the careful run moves it: a run that nearly holds, and one that does not.
push!(cases, J("name" => "a run that nearly holds", "model" => made_up("loose"; rtol=0.3, abstol=1e-2, solver="dp45")))
push!(cases, J("name" => "a run that does not hold", "model" => made_up("looser"; rtol=0.5, abstol=0.1)))

for c in cases
    raw = c["model"]
    held = K.run_project(K.Project(K.jcopy(raw)))
    report = K.check_run(held, p -> K.run_project(p); model=K.jcopy(raw))
    delete!(report["careful"], "ms")
    c["labels"] = K.state_labels(held.system)
    c["report"] = K.json_text(report; indent=0)
    println(c["name"], ": ", report["verdict"], " ", report["worst"], " (", length(c["labels"]), " states)")
end

# Runs made up to reach every rule of the comparison.
compare_model = J("name" => "made up",
                  "simulation" => J("start_time" => 0, "end_time" => 3, "output_points" => 4, "spacing" => "linear", "rtol" => 1e-3,
                                    "abstol" => 1e-6),
                  "compartments" => Any[J("name" => n, "initial" => "1", "unit" => "Bq", "index_lists" => Any[])
                                        for n in ("A", "B", "C", "D", "E", "F", "G", "H")])
t = [0.0, 1.0, 2.0, 3.0]
held_y = [[1, 2, 3, 1e-5, 0, 5, 5, 1], [1, 2, NaN, 2e-5, 0, 5, 5, Inf], [1, NaN, 3, 1e-5, 0, 6, 6, Inf], [1, 2, NaN, 1e-5, 0, 7, 7, 1]]
careful_y = [[1, 2, 3, 1e-5, 0, 5, 5, 1], [1.001, 2, 3, 2.0001e-5, 0, 5.5, 5.5, 1], [1, 2, NaN, 1e-5, 0, 6, 6, Inf],
             [1, 2, 4, 3e-5, 0, 7, 7, 2]]
proj = K.Project(K.jcopy(compare_model))
sys = K.build_system(proj)
compares = Any[]
for (ct, cy) in ((t, careful_y), ([0.0, 0.9, 1.6, 2.4, 3.0], vcat(careful_y, [careful_y[end]])), ([0.0, 1.5, 3.0], careful_y[[1, 2, 4]]))
    run_of(tt, yy) = (project=proj, system=sys, t=Float64.(tt), y=[Float64.(row) for row in yy], stats=Dict{String,Any}())
    r = K.compare_runs(run_of(t, held_y), run_of(ct, cy))
    push!(compares, J("held_t" => bits.(t), "held_y" => [bits.(row) for row in held_y], "careful_t" => bits.(ct),
                      "careful_y" => [bits.(row) for row in cy], "report" => K.json_text(r; indent=0)))
end

path = joinpath(@__DIR__, "..", "tests", "fixtures", "checkrun.json")
write(path, K.json_text(J("cases" => cases, "compare_model" => compare_model, "compares" => compares); indent=0))
println(path, ": ", length(cases), " checks, ", length(compares), " comparisons")
