# A model and its run in one archive, and the run read back: every series the
# same, the recorders' histories put back, and the archives that cannot be
# read refused in words.

module DatasetTests

using Test
using Kompartment
const K = Kompartment

const EXAMPLES = joinpath(@__DIR__, "..", "..", "..", "examples")

@testset "a run saved with its model" begin
    for f in ("biosphere.json", "recorders.json", "waste-packages.json")
        m = K.load(joinpath(EXAMPLES, f))
        res = run(m)
        for compress in (true, false)
            bytes = K.dataset_archive(res; compress, stamp="2026-01-01T00:00:00.000Z")
            again = K.load_results(bytes)
            @test again.t == res.t
            @test all(again[l] == res[l] || all(isnan, res[l]) for l in labels(res))
            @test again.stats["opened"] === true
        end
    end
    # Through save, and the model given back as it was.
    m = K.load(joinpath(EXAMPLES, "recorders.json"))
    res = run(m)
    mktempdir() do dir
        path = joinpath(dir, "run.zip")
        save(res, path)
        got = K.read_archive(path)
        @test got.problem === nothing && got.dataset !== nothing
        @test K.json_text(got.project; indent=2) == K.json_text(res.project.raw; indent=2)
        @test_throws ArgumentError save(res, path; blocks=["Lake"])
    end
    # Refused: another model's layout, an archive with no run, something that is no archive.
    other = K.load(joinpath(EXAMPLES, "biosphere.json"))
    @test_throws K.DatasetError K.load_results(K.dataset_archive(res); project=other)
    plain = K._ds_zip(["model.json" => Vector{UInt8}(codeunits(to_json(m)))])
    @test_throws K.DatasetError K.load_results(plain)
    @test_throws K.DatasetError K.load_results(Vector{UInt8}(codeunits("not a zip")))
end

end # module
