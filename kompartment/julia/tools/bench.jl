# How long a model takes here, from the model to the result file: build and
# compile, solve, the series written out.
#
#     julia --project=. tools/bench.jl              # the made-up chains, then the bundled examples
#     julia --project=. -t auto tools/bench.jl      # the same on every core
#     julia --project=. tools/bench.jl model.json   # a model of your own (any file `load` opens)
#
# The made-up model is the Python package's timing model (`chains` in
# python/tests/test_engine_split.py): 16 decay chains of 12 made-up nuclides
# through 150 compartments in a line, 28,800 states, none reaching another.
# Each is run twice in this process and the second run is reported, so the
# times are without Julia's compilation of the package's own code.

using Kompartment
using Printf

const K = Kompartment

"""`count` decay chains of `length` made-up nuclides through `compartments` compartments in a line."""
function chains(count::Int, length::Int, compartments::Int; points::Int=300, rtol::Float64=1e-8)
    letters = "abcdefghijklmnopqrstuvwxyz"
    names = String[]
    half = K.JDict()
    pairs = Any[]
    for c in 0:count-1
        element = "Q" * letters[c%26+1] * (c < 26 ? "" : string(letters[c÷26+1]))
        chain = ["$element-$(100 + k)" for k in 0:length-1]
        for (k, name) in enumerate(chain)
            push!(names, name)
            half[name] = K.cpow(10.0, 1 + (((k - 1) * 7 + c * 3) % 11) * 0.5)   # Python's 10 ** x: the C library's pow
        end
        append!(pairs, Any[Any[chain[k], chain[k+1], 1.0] for k in 1:length-1])
    end
    return K.JDict(
        "name" => "$count chains of $length through $compartments",
        "nuclides" => Any[names...],
        "half_lives" => half,
        "chains" => pairs,
        "simulation" => K.JDict("start_time" => 0, "end_time" => 1e5, "output_points" => points, "spacing" => "log",
                                "solver" => "ndf", "rtol" => rtol, "abstol" => 1e-6, "time_unit" => "year"),
        "parameters" => Any[K.JDict("name" => "k$j", "value" => K.cpow(10.0, -1 - j * 0.7), "index_lists" => Any[]) for j in 0:4],
        "compartments" => Any[K.JDict("name" => "C$i", "initial" => i == 0 ? "1e6" : "0",
                                      "index_lists" => Any["Radionuclides"]) for i in 0:compartments-1],
        "transfers" => Any[K.JDict("name" => "T$i", "from" => "C$i", "to" => "C$(i + 1)", "rate" => "k$(i % 5)",
                                   "index_lists" => Any["Radionuclides"]) for i in 0:compartments-2],
    )
end

"""Builds, solves and writes one model; the times in seconds."""
function once(m::Model)
    t0 = time()
    p = K.project(m)
    sys = K.build_system(p)
    t1 = time()
    res = K.run_project(p; system=sys)
    t2 = time()
    path = tempname() * ".h5"
    save(res, path)
    t3 = time()
    rm(path; force=true)
    return (build=t1 - t0, solve=t2 - t1, write=t3 - t2, res=res, states=sys.nstate)
end

function report(label::AbstractString, m::Model)
    once(m)
    r = once(m)
    @printf("%-34s %7d states  build %6.3f s  solve %7.3f s  write %6.3f s  %s\n", label, r.states, r.build,
            r.solve, r.write, summary(r.res))
end

println("Julia $(VERSION), $(Threads.nthreads()) thread$(Threads.nthreads() == 1 ? "" : "s")")
if isempty(ARGS)
    report("16 chains x 12 through 150", Model(chains(16, 12, 150)))
    examples = joinpath(@__DIR__, "..", "..", "examples")
    for f in sort(readdir(examples))
        endswith(f, ".json") || continue
        report(f, K.load(joinpath(examples, f)))
    end
else
    for f in ARGS
        report(basename(f), K.load(f))
    end
end
