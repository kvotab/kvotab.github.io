# Models opened as the Python package opens them, and written as it writes
# them: `to_json(Model(raw))` byte for byte the text of Python's
# `kp.Model.from_dict(raw).to_json()`, and `save` the file Python's
# `Model.save` writes, stamps aside.
#
# tools/model_fixtures.py writes the fixtures, for every model it is given:
#
#     NAME.input.json      the model as given
#     NAME.expected.json   Python's to_json() of it (NAME.error.txt where Python refuses it)
#     NAME.saved.json      the file Python's save() writes, stamped at SAVED_STAMP
#     NAME.source.txt      an imported Ecolego project's file: imported here too
#
#     KOMPARTMENT_MODEL_FIXTURES=DIR[:DIR...] julia --project test/model/normalise.jl
#
# The checks that need no fixtures run without them.

module NormaliseTests

using Test
using Dates
using Kompartment
const K = Kompartment

const DIRS = filter(isdir, split(get(ENV, "KOMPARTMENT_MODEL_FIXTURES", ""), ':'; keepempty=false))
const SAVED_STAMP = "2026-01-02T03:04:05.678Z"
const STAMP = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"

"""Where two texts first part, for the log."""
function first_difference(got, want)
    gl, wl = split(got, '\n'), split(want, '\n')
    k = findfirst(i -> i > length(gl) || i > length(wl) || gl[i] != wl[i], 1:max(length(gl), length(wl)))
    k === nothing && return nothing
    return (line=k, julia=k <= length(gl) ? gl[k] : "<none>", python=k <= length(wl) ? wl[k] : "<none>")
end

"""The text `save` writes for `m`, with this save's stamp written as `SAVED_STAMP`."""
function saved_text(m)
    path = tempname() * ".json"
    try
        K.save(m, path)
        text = read(path, String)
        stamp = K.parse_json(text)["saved"]
        @test occursin(STAMP, stamp)
        return replace(text, "\"$stamp\"" => "\"$SAVED_STAMP\"")
    finally
        rm(path; force=true)
    end
end

model(text) = K.Model(K.parse_json(text))

@testset "a model opened and written as Python does it" begin
    @testset "without fixtures" begin
        m = model("""{"nuclides": ["Cs-137", "Sr-90"],
            "compartments": [{"name": "A", "initial": {"Cs-137": "100", "Sr-90": 50}}, {"name": "B", "unit": ""}],
            "parameters": [{"name": "k", "default": 0.01, "values_by_nuclide": {"Cs-137": 0.2}},
                           {"name": "q", "value": 1, "per_nuclide": false}],
            "transfers": [{"name": "T", "from": "A", "to": "B", "rate": "k"},
                          {"name": "F", "from": "B", "rate": "q", "multiply_by_donor": false}]}""")
        raw = m.raw
        # The shorthand as the two lists it stands for, the catalogue first.
        @test [l["name"] for l in raw["index_lists"]] == ["Contaminants", "Radionuclides"]
        @test raw["index_lists"][2]["sub_set_of"] == "Contaminants"
        # A legacy default and per-nuclide map as the value and an entry.
        k = raw["parameters"][1]
        @test k["value"] == 0.01 && !haskey(k, "default") && !haskey(k, "values_by_nuclide")
        @test k["entries"] == Any[K.JDict("index" => K.JDict("Radionuclides" => "Cs-137"), "value" => 0.2)]
        a = raw["compartments"][1]
        @test a["initial"] == "0"
        @test [e["initial"] for e in a["entries"]] == ["100", "50"]
        # Every block's dimensions written down; per_nuclide: false means none.
        @test all(b -> b["index_lists"] == ["Radionuclides"], raw["compartments"])
        @test raw["parameters"][2]["index_lists"] == Any[] && !haskey(raw["parameters"][2], "per_nuclide")
        # The units that follow from the model.
        @test raw["compartments"][2]["unit"] == "Bq"
        @test raw["transfers"][1]["unit"] == "1/year"
        @test raw["transfers"][2]["unit"] == "Bq/year"
        # Written twice, the same text: settling again changes nothing.
        text = K.to_json(m)
        @test K.to_json(m) == text
        @test K.to_json(model(text)) == text

        # A stale flux follows its ends; a narrower one the model states stays.
        m = model("""{"index_lists": [{"name": "Object", "indices": ["Lake", "Mire"]},
                                      {"name": "Wet", "sub_set_of": "Object", "indices": ["Lake"]}],
            "compartments": [{"name": "A", "index_lists": ["Object"]}, {"name": "B", "index_lists": ["Object"]}],
            "transfers": [{"name": "stale", "from": "A", "to": "B", "index_lists": []},
                          {"name": "narrow", "from": "A", "to": "B", "index_lists": ["Wet"]}]}""")
        @test [t["index_lists"] for t in m.raw["transfers"]] == [["Object"], ["Wet"]]
        @test K.settle!(m.raw) == String[]

        # Settling drops the diagram entries of what is gone, and says what it changed.
        m = model("""{"compartments": [{"name": "A"}], "layout": {"A": {"x": 1}, "Gone": {"x": 2},
                      "edge:A@Nowhere": {}, "edge:A": {}}}""")
        m.raw["transfers"] = Any[K.JDict("name" => "T", "from" => "A", "rate" => "1", "index_lists" => Any[])]
        @test K.settle!(m.raw) == ["T"]
        @test collect(keys(m.raw["layout"])) == ["A", "edge:A"]

        # Saved: stamped now, created kept when it is a date, the header first.
        m = model("""{"compartments": [{"name": "A"}], "author": "Someone", "created": "2025-03-04T05:06:07+02:00",
                      "name": "Dated"}""")
        text = saved_text(m)
        @test startswith(text, "{\n  \"name\": \"Dated\",\n  \"author\": \"Someone\",\n  \"created\": \"2025-03-04T05:06:07+02:00\",\n  \"saved\": \"$SAVED_STAMP\",")
        m = model("""{"compartments": [{"name": "A"}], "created": "not a date"}""")
        @test startswith(saved_text(m), "{\n  \"created\": \"$SAVED_STAMP\",\n  \"saved\": \"$SAVED_STAMP\",")
        @test occursin(STAMP, K.model_stamp())
        @test K.model_stamp(DateTime(2026, 1, 2, 3, 4, 5, 678)) == SAVED_STAMP

        # A stamp read back as Python's datetime.fromisoformat reads it.
        @test K.read_model_stamp("2025-03-04T05:06:07.890Z") == DateTime(2025, 3, 4, 5, 6, 7, 890)
        @test K.read_model_stamp("2025-03-04T05:06:07+02:00") == DateTime(2025, 3, 4, 3, 6, 7)
        @test K.read_model_stamp("2025-03-04T0506") == DateTime(2025, 3, 4, 5, 6)
        @test K.read_model_stamp("2025-03-04T05:06:07x+00:00") == DateTime(2025, 3, 4, 5, 6, 7)
        @test K.read_model_stamp("2025-03-04T05:06:07xx+00:00") === nothing
        @test K.read_model_stamp("2025-02-29T00:00:00Z") === nothing
        @test K.read_model_stamp("2025-03-04T24:00:00Z") === nothing
        @test K.read_model_stamp("2025-03-04T05:06:07+24:00") === nothing
        @test K.read_model_stamp("2025-03-04") === nothing
        @test K.read_model_stamp(20250304) === nothing
    end

    for dir in DIRS
        names = sort([f[1:end-length(".input.json")] for f in readdir(dir) if endswith(f, ".input.json")])
        @testset "$(basename(dirname(dir)))/$(basename(dir)): $name" for name in names
            raw = K.parse_json(read(joinpath(dir, name * ".input.json"), String))
            refused = joinpath(dir, name * ".error.txt")
            if isfile(refused)
                @test_throws Exception K.Model(raw)
                continue
            end
            want = read(joinpath(dir, name * ".expected.json"), String)
            m = K.Model(raw)
            got = K.to_json(m)
            got == want || @info "$name: to_json differs" first_difference(got, want)
            @test got == want
            saved = joinpath(dir, name * ".saved.json")
            if isfile(saved)
                got = saved_text(m)
                want_saved = read(saved, String)
                got == want_saved || @info "$name: save differs" first_difference(got, want_saved)
                @test got == want_saved
            end
            source = joinpath(dir, name * ".source.txt")
            if isfile(source) && isfile(read(source, String))
                got = K.to_json(K.import_ecolego(read(source, String)))
                got == want || @info "$name: imported here, to_json differs" first_difference(got, want)
                @test got == want
            end
        end
    end
    isempty(DIRS) && @info "KOMPARTMENT_MODEL_FIXTURES not set: only the checks that need no fixtures ran"
end

end # module NormaliseTests
