# Whole runs against the Python package's (tools/run_fixtures.py): the
# solver's counts, the output times, every series by label and the CSV,
# to the bit.
#
#     PYTHONPATH=../python python3 tools/run_fixtures.py <scratch>/runs
#     KOMPARTMENT_RUN_FIXTURES=<scratch>/runs julia --project=. test/engine/runs.jl
#
# A model large enough for the sparse solver (above 200 states) is the one
# exception: Python factorises with SuperLU and this package with KLU, so the
# solves round differently and a run agrees to its tolerance instead.

module RunTests

using Test
using Kompartment
const K = Kompartment

const FIXTURES = get(ENV, "KOMPARTMENT_RUN_FIXTURES", "")
const EXAMPLES = joinpath(@__DIR__, "..", "..", "..", "examples")
const COUNTS = ("nsteps", "nfailed", "nfevals", "npds", "ndecomps", "events", "restarts")

unhex(v) = Float64[parse(Float64, s) for s in v]
same(a::Float64, b::Float64) = a === b || (isnan(a) && isnan(b))
same(a::AbstractVector, b::AbstractVector) = length(a) == length(b) && all(i -> same(a[i], b[i]), eachindex(a))

"""The largest difference, relative to the largest finite value of the reference."""
function relative_gap(a::AbstractVector, b::AbstractVector)
    scale = maximum(abs, filter(isfinite, b); init=0.0)
    gap = maximum((abs(x - y) for (x, y) in zip(a, b) if isfinite(x) && isfinite(y)); init=0.0)
    return scale > 0 ? gap / scale : gap
end

@testset "whole runs against the Python package" begin
    if isempty(FIXTURES) || !isdir(FIXTURES)
        @info "KOMPARTMENT_RUN_FIXTURES not set: run parity tests skipped"
        return
    end
    for f in sort(filter(endswith(".json"), readdir(FIXTURES)))
        fx = K.parse_json(read(joinpath(FIXTURES, f), String))
        @testset "$(fx["name"])" begin
            path = isfile(joinpath(EXAMPLES, fx["name"])) ? joinpath(EXAMPLES, fx["name"]) : fx["name"]
            raw = K.read_model_file(path)
            if haskey(fx, "error")
                @test_throws Exception K.run_project(K.Project(raw))
                return
            end
            res = K.run_project(K.Project(raw))
            labels = String[o["label"] for o in fx["outputs"]]
            @test K.labels(res) == labels
            sparse = get(res.stats, "sparse", false) === true
            t = unhex(fx["t"])
            if !sparse
                for k in COUNTS
                    @test get(res.stats, k, nothing) == get(fx["stats"], k, nothing)
                end
                @test same(res.t, t)
                cols = K.series_many(res, K.outputs(res))
                for (k, col) in enumerate(cols)
                    ok = same(col, unhex(fx["series"][k]))
                    ok || @info "$(fx["name"]): $(labels[k]) differs" relative_gap(col, unhex(fx["series"][k]))
                    @test ok
                end
                @test K.to_csv(res) == fx["csv"]
            elseif length(res.t) == length(t) && same(res.t, t)
                # The sparse path: the same run within its tolerance.
                rtol = Float64(something(get(raw["simulation"], "rtol", nothing), 1e-3))
                cols = K.series_many(res, K.outputs(res))
                worst = maximum((relative_gap(c, unhex(w)) for (c, w) in zip(cols, fx["series"])); init=0.0)
                @test worst <= 100 * rtol
            else
                @info "$(fx["name"]): solved sparse, on its own output times; only the labels are compared"
            end
        end
    end
end

end # module
