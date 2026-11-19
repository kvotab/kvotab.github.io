# Numbers, JSON and the equation language, as the application has them.

using Test
using Kompartment
const K = Kompartment

@testset "numbers as JavaScript writes them" begin
    @test K.js_number(1.5e-5) == "0.000015"
    @test K.js_number(1e-7) == "1e-7"
    @test K.js_number(100000.0) == "100000"
    @test K.js_number(1e21) == "1e+21"
    @test K.js_number(1.5e21) == "1.5e+21"
    @test K.js_number(-0.000001) == "-0.000001"
    @test K.js_number(123.456) == "123.456"
    @test K.js_number(0.1 + 0.2) == "0.30000000000000004"
    @test K.js_number(NaN) == "null"
    @test K.js_number(7) == "7"
    @test K.js_number_of("") == 0.0
    @test K.js_number_of(" 12 ") == 12.0
    @test isnan(K.js_number_of("abc"))
    @test K.js_number_of("-Infinity") == -Inf
end

@testset "a value written as text, as JavaScript's Number() reads it" begin
    # Every reader of a block's value: the project's, the builder's, a table's, a time
    # series'. Not as Python's float() reads text: no underscore between digits, no `inf`
    # and no other case of Infinity, no digits but ASCII ones; past a double, Infinity.
    readers = (K.js_number_of, K._builder_number, K._lk_number, K._ts_number)
    want = Dict(" 1 " => 1.0, "1e0" => 1.0, "0x10" => 16.0, "0o17" => 15.0, "0b101" => 5.0, "" => 0.0,
                "1." => 1.0, ".5" => 0.5, "Infinity" => Inf, "+Infinity" => Inf, "-Infinity" => -Inf,
                "1e400" => Inf, "-1e400" => -Inf, "1_0e-1" => NaN, "1_000" => NaN, "inf" => NaN,
                "infinity" => NaN, "INFINITY" => NaN, "nan" => NaN, "-0x10" => NaN, "\u0661" => NaN,
                "1e" => NaN, "abc" => NaN)
    for (text, v) in want, f in readers
        @test isequal(f(text), v)
    end
end

@testset "JSON" begin
    v = K.parse_json("{\"b\": 1, \"a\": [1.5, -0, 1e400, \"x\\u00e9\\n\", null, true], \"c\": {}}")
    @test collect(keys(v)) == ["b", "a", "c"]
    @test v["b"] === 1
    @test v["a"][1] === 1.5
    @test v["a"][3] == Inf
    @test v["a"][4] == "xé\n"
    @test v["a"][5] === nothing
    @test K.json_text(v; indent=0) == "{\"b\":1,\"a\":[1.5,0,null,\"xé\\n\",null,true],\"c\":{}}"
    @test_throws K.JSONError K.parse_json("{\"a\": }")
end

@testset "the equation language" begin
    @test K.parse_equation("2^3^2") isa K.EBinary
    sys_raw = K.JDict("name" => "t", "simulation" => K.JDict("end_time" => 1, "output_points" => 2),
                      "parameters" => Any[K.JDict("name" => "a", "value" => 2)],
                      "expressions" => Any[K.JDict("name" => "e1", "equation" => "2^3^2"),
                                           K.JDict("name" => "e2", "equation" => "-a^2"),
                                           K.JDict("name" => "e3", "equation" => "2^-1"),
                                           K.JDict("name" => "e4", "equation" => "a > 1 ? 10 : 20"),
                                           K.JDict("name" => "e5", "equation" => "round(-0.5) + round(2.5)"),
                                           K.JDict("name" => "e6", "equation" => "log(0) + sqrt(-1)"),
                                           K.JDict("name" => "e7", "equation" => "max(1, a, 3) + min(5, a)")])
    res = run(K.Model(sys_raw))
    @test res["e1"][1] == 64
    @test res["e2"][1] == -4
    @test res["e3"][1] == 0.5
    @test res["e4"][1] == 10
    @test res["e5"][1] == 3
    @test isnan(res["e6"][1])
    @test res["e7"][1] == 5
end

@testset "V8's arithmetic" begin
    @test K.js_exp(1.0) == 2.718281828459045
    @test K.js_log(10.0) == 2.302585092994046
    @test K.js_pow(10.0, -6.0) == 1e-6
    @test K.js_log10(1e11) == 11.0
end

@testset "white space as JavaScript takes it" begin
    # `trim()`, `Number()` and `\s` take a byte-order mark and the line and paragraph separators,
    # and neither U+0085 nor U+001C to U+001F -- which Julia's `isspace` and Python's `strip()`
    # do the other way round in part.
    for c in ('\ufeff', '\u2028', '\u2029', '\u00a0', '\u3000', '\t', '\v')
        @test K.js_space(c) && K.js_trim("$(c)mol$(c)") == "mol"
    end
    for c in ('\u0085', '\x1c', '\x1f', '\u200b')
        @test !K.js_space(c) && K.js_trim("$(c)mol") == "$(c)mol"
    end
    @test K.js_number_of("\ufeff 1\u2028") == 1.0 && isnan(K.js_number_of("\u0085 1"))
    @test K.element_of("Cs\ufeff137") == "Cs" && K.element_of("Cs\u0085137") === nothing
    # A model's text, as the application reads it: a snapshot's trigger, and a min/max's
    # operation, with each kind at an end.
    examples = joinpath(@__DIR__, "..", "..", "..", "examples")
    ball(trigger) = (m = K.read_model_file(joinpath(examples, "bouncing-ball.json"));
                     m["snapshots"][1]["trigger"] = trigger; K.build_system(K.Project(m)))
    @test ball("\ufeffBounce") isa K.System && ball("Bounce\u2028") isa K.System
    @test_throws "is not the name of a discrete event" ball("\x1cBounce")
    @test_throws "is not the name of a discrete event" ball("Bounce\u0085")
    peak(op) = (m = K.read_model_file(joinpath(examples, "scenarios.json")); m["min_maxes"][1]["operation"] = op; K.Project(m))
    @test peak("max\ufeff") isa K.Project
    @test_throws "is not a min/max operation" peak("max\u0085")
end

@testset "patterns as JavaScript matches them" begin
    # Its `\d`, `\b` and `/i` know ASCII alone -- Julia's patterns take Unicode's digits, letters and
    # case foldings as well.
    @test !K.means_stable("\u017ftable") && K.means_stable("STABLE") && !K.means_stable("\u0130nf") && K.means_stable(" Infinity ")
    @test string(K.parse_unit("m per\u00b5g")) == "1e+9 m/kg"
    @test string(K.parse_unit("m pers")) != string(K.parse_unit("m per s"))
    @test K._nf_says_no_number("\u00e9NaN") && !K._nf_says_no_number("xNaN") && K._nf_says_no_number("Not a Number")
    examples = joinpath(@__DIR__, "..", "..", "..", "examples")
    switches(entries) = (m = K.read_model_file(joinpath(examples, "four-compartment.json"));
                         m["simulation"]["switch_times"] = entries; K.switch_times(K.Project(m)))
    @test isempty(switches(Any["\u0661\u0662"])) && switches(Any["12"]) == [12.0]
end
