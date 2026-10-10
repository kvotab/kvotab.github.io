# The Ecolego importer against the Python package's: the same file, the same
# project (as JSON text, key order included) and the same report, field for
# field; for a file neither can read, the same refusal and message.
#
#     KOMPARTMENT_ECO_FIXTURES=<dir> julia --project=. test/importers/test_eco.jl
#
# The expected answers are written by tools/eco_fixtures.py into a directory
# outside the repository (real project files are client data); without it
# the comparison is skipped and only the pieces below are checked. Set
# KOMPARTMENT_ECO_ONLY to a regular expression to run the cases whose label
# matches it, KOMPARTMENT_ECO_SOURCE to `synthetic` or `real` to run only
# those, KOMPARTMENT_ECO_VERBOSE=1 to print where each mismatch starts.

module EcoImporterTest

using Test

# The importer and only what it uses, so the test does not depend on the
# rest of the package (which may be mid-edit).
module E
using OrderedCollections: OrderedDict
using Dates, Printf
const SRC = joinpath(@__DIR__, "..", "..", "src")
include(joinpath(SRC, "util", "jsnum.jl"))
include(joinpath(SRC, "util", "zip.jl"))
include(joinpath(SRC, "util", "jsonio.jl"))
include(joinpath(SRC, "model", "names.jl"))
include(joinpath(SRC, "model", "decay.jl"))
include(joinpath(SRC, "model", "indexlists.jl"))
include(joinpath(SRC, "engine", "farfield_domain.jl"))
include(joinpath(SRC, "model", "keys.jl"))
include(joinpath(SRC, "model", "simulation.jl"))
include(joinpath(SRC, "importers", "eco.jl"))
end

const FIXTURES = get(ENV, "KOMPARTMENT_ECO_FIXTURES", "")
const ONLY = let o = get(ENV, "KOMPARTMENT_ECO_ONLY", "")
    isempty(o) ? nothing : Regex(o)
end
const VERBOSE = get(ENV, "KOMPARTMENT_ECO_VERBOSE", "") == "1"
const SOURCE = get(ENV, "KOMPARTMENT_ECO_SOURCE", "")     # "synthetic" or "real": only those

# Where two texts first differ, with a little context.
function first_difference(a::String, b::String)
    la, lb = split(a, '\n'), split(b, '\n')
    for k in 1:max(length(la), length(lb))
        x = k <= length(la) ? la[k] : "<end>"
        y = k <= length(lb) ? lb[k] : "<end>"
        x == y && continue
        return "line $k:\n  julia:  $(first(x, 300))\n  python: $(first(y, 300))"
    end
    return "(no difference)"
end

# The Python exception each Julia one stands for.
python_name(e::E.EcoImportError) = "EcoImportError"
python_name(e::ArgumentError) = "ValueError"
python_name(e::ErrorException) = "NotImplementedError"
python_name(e) = string(typeof(e))
message(e::E.EcoImportError) = e.msg
message(e::ArgumentError) = e.msg
message(e::ErrorException) = e.msg
message(e) = sprint(showerror, e)

"""One case: `:same`, `:skipped` (a real file that changed or went away),
or a description of what differs."""
function check_case(rec)
    cid = rec["id"]
    base = joinpath(FIXTURES, "cases", cid)
    kind = rec["kind"]
    file_name = rec["file_name"]
    version = rec["version"]
    if rec["source"] == "real"
        path = rec["path"]
        isfile(path) || return :skipped
        filesize(path) == rec["size"] || return :skipped
    end
    result = try
        if kind == "xml"
            E.import_model_xml(read(base * ".payload", String); file_name=file_name, version=version)
        elseif kind == "file"
            E.import_eco_file(read(base * ".payload"); file_name=file_name, version=version)
        else
            E.import_eco_file(rec["path"]; version=version)
        end
    catch e
        e isa InterruptException && rethrow()
        e
    end
    if isfile(base * ".error.json")
        want = E.parse_json(read(base * ".error.json", String))
        result isa Exception || return "Python refused it ($(want["type"]): $(want["message"])), Julia did not"
        got = (python_name(result), message(result))
        got == (want["type"], want["message"]) && return :same
        return "refused differently:\n  julia:  $(got[1]): $(got[2])\n  python: $(want["type"]): $(want["message"])"
    end
    if result isa Exception
        return "Julia refused it: $(sprint(showerror, result))"
    end
    project, report = result
    want_project = read(base * ".project.json", String)
    want_report = read(base * ".report.json", String)
    got_project = E.json_text(project)
    got_project == want_project || return "project differs at " * first_difference(got_project, want_project)
    got_report = E.json_text(E.to_dict(report))
    got_report == want_report || return "report differs at " * first_difference(got_report, want_report)
    return :same
end

@testset "Ecolego importer" begin
    @testset "pieces" begin
        # decode_xml_bytes
        @test E.decode_eco_xml_bytes(UInt8[0xfe, 0xff, 0x00, 0x41]) == "A"
        @test E.decode_eco_xml_bytes(UInt8[0xff, 0xfe, 0x41, 0x00]) == "A"
        @test E.decode_eco_xml_bytes(UInt8[0xef, 0xbb, 0xbf, 0x41]) == "A"
        @test E.decode_eco_xml_bytes(UInt8[0xef, 0xbb, 0xbf, 0xef, 0xbb, 0xbf, 0x41]) == "A"
        @test E.decode_eco_xml_bytes(UInt8[0x41, 0xc3]) == "A\ufffd"
        # XML errors count UTF-16 code units; CDATA is verbatim
        err = try
            E.parse_eco_xml("<a>\U0001F600</b>")
        catch e
            e
        end
        @test err isa E.EcoXMLError && err.position == 9
        @test E._eco_text(E.parse_eco_xml("<a x=\"1\" x=\"2\"><![CDATA[&amp;]]>&amp;</a>")) == "&amp;&"
        @test E._eco_attr(E.parse_eco_xml("<a x=\"1\" y=\"0\" x=\"2\"/>"), "x") == "2"
        # Number()
        for (text, want) in [("", 0.0), (" 12 ", 12.0), ("0x1A", 26.0), (".5", 0.5), ("5.", 5.0),
                             ("-Infinity", -Inf), ("\u00a012\u00a0", 12.0), ("1e400", Inf), ("1e-400", 0.0)]
            @test E._eco_to_number(text) === want
        end
        for text in ["-0x1A", "1e", ".", "infinity", "1_000", "\x1c12", "NaN", "0x"]
            @test isnan(E._eco_to_number(text))
        end
        # toPrecision, toExponential, Math.round, dates
        @test E._eco_round_significant(1000500, 4) == 1001000
        @test E._eco_round_significant(1.25, 2) == 1.3
        @test E._eco_to_exponential(1001000.0) == "1.001e+6"
        @test E._eco_js_round(-2.5) == -2
        @test E._eco_js_round(0.49999999999999994) == 0
        @test E._eco_iso_date(1621966224401) == "2021-05-25"
        # localeCompare, as Node gave it
        words = ["a_", "a0", "aA", "aa", "a", "A", "_a", "B", "b", "Ab", "aB", "AB", "ab", "L_1", "L1", "L10",
                 "L2", "Z9", "z_", "__", "_", "_0", "0", "Nuclides", "Landscape_objects", "nuclides"]
        node = ["_", "__", "_0", "_a", "0", "a", "A", "a_", "a0", "aa", "aA", "ab", "aB", "Ab", "AB", "b", "B",
                "L_1", "L1", "L10", "L2", "Landscape_objects", "nuclides", "Nuclides", "z_", "Z9"]
        @test sort(words; by=E._eco_collation_key) == node
        # Python's casing
        @test E._eco_py_lower("ΟΔΟΣ") == "οδος"
        @test E._eco_py_upper("straße") == "STRASSE"
        @test E._eco_js_trim("\u2028 x\u00a0y \ufeff") == "x\u00a0y"
    end

    if isempty(FIXTURES) || !isfile(joinpath(FIXTURES, "manifest.json"))
        @info "No Ecolego fixtures (set KOMPARTMENT_ECO_FIXTURES to what tools/eco_fixtures.py wrote); " *
              "the comparison with the Python importer is skipped."
        @test_skip "fixtures"
    else
        manifest = E.parse_json(read(joinpath(FIXTURES, "manifest.json"), String))
        same = 0
        skipped = 0
        failed = String[]
        @testset "fixtures" begin
            for rec in manifest
                ONLY === nothing || occursin(ONLY, rec["label"]) || continue
                isempty(SOURCE) || rec["source"] == SOURCE || continue
                outcome = check_case(rec)
                if outcome === :skipped
                    skipped += 1
                    continue
                end
                if outcome === :same
                    same += 1
                else
                    push!(failed, "$(rec["id"]) ($(rec["label"])): $outcome")
                    VERBOSE && println(failed[end])
                end
                @test outcome === :same
            end
        end
        println("Ecolego importer: $same identical, $(length(failed)) different, $skipped skipped")
        for f in first(failed, 20)
            println(first(f, 2000))
        end
    end
end

end # module
