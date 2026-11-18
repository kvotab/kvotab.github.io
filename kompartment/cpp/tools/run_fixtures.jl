# Writes tests/fixtures/runs.json: whole runs by the Julia engine with parity
# on, for the C++ engine's tests to compare with (tests/test_runs.cpp).
#
#     julia --project=../julia tools/run_fixtures.jl
#
# Every model of tests/fixtures/builder.json that is built, run twice: with
# the Jacobian differenced through its pattern (`simulation.jacobian =
# "numeric"`) and as the model stands (the exact Jacobian where it has one).
# A run is kept as a hash of the application's table of it (every series at
# every output time, as text) with its step counts, or as the message it
# fails with. With KOMPARTMENT_FIXTURE_DUMPS set the tables are written there
# (`<name>.<numeric|exact>.julia.csv`).

using Kompartment
const K = Kompartment
K.set_parity!(true)

function fnv(text::String)
    h = 0xcbf29ce484222325
    for b in codeunits(text)
        h = (h ⊻ b) * 0x100000001b3
    end
    return string(h; base=16, pad=16)
end

const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
function one(name, model, how)
    m = K.jcopy(model)
    sim = get!(m, "simulation", K.JDict())
    how == "numeric" && (sim["jacobian"] = "numeric")
    out = K.JDict()
    try
        p = K.Project(m)
        sys = K.build_system(p)
        res = K.run_project(p; system=sys)
        text = K.to_csv(res)
        isempty(DUMPS) || write(joinpath(DUMPS, "$name.$how.julia.csv"), text)
        out["csv"] = fnv(text)
        out["points"] = length(res.t)
        for key in ("solver", "nsteps", "nfailed", "nfevals", "events", "jumps", "restarts")
            v = get(res.stats, key, nothing)
            v === nothing || (out[key] = v)
        end
    catch e
        e isa K.SolverError || e isa K.BuildError || e isa ErrorException || (println(stderr, "while running ", name); rethrow())
        out["error"] = e isa ErrorException ? e.msg : e.message
    end
    return out
end

examples = joinpath(@__DIR__, "..", "..", "examples")
cases = Any[]
for c in K.parse_json(read(joinpath(@__DIR__, "..", "tests", "fixtures", "builder.json"), String))["cases"]
    haskey(c, "sections") || continue
    model = haskey(c, "example") ? K.parse_json(read(joinpath(examples, c["example"] * ".json"), String)) : c["model"]
    row = haskey(c, "example") ? K.JDict("name" => c["name"], "example" => c["example"]) : K.JDict("name" => c["name"], "model" => model)
    row["numeric"] = one(c["name"], model, "numeric")
    row["exact"] = one(c["name"], model, "exact")
    push!(cases, row)
end
path = joinpath(@__DIR__, "..", "tests", "fixtures", "runs.json")
write(path, K.json_text(K.JDict("cases" => cases); indent=0))
println(path, ": ", length(cases), " models, ", count(c -> haskey(c["exact"], "error"), cases), " fail")
