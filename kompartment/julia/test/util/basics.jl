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
