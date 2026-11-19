# Writes tests/fixtures/hdf5.json: HDF5 files written by the Julia package with parity
# on, for the C++ engine's tests to compare with byte for byte (tests/test_hdf5.cpp).
#
#     julia --project=. ../cpp/tools/hdf5_fixtures.jl        (from ../julia)
#
# The writer (io/hdf5.jl) on trees made up step by step -- every datatype and the values
# each is given as, empty and large datasets, many children, attribute orders with keys
# that are array indices, strings that are not ASCII or not UTF-8, pooled strings past a
# global heap collection's size, int32 wrapping, NaN and the infinities, dimensions given
# as numbers, text and fractions, and the refusals; lookup3 on its own; text as
# `TextEncoder` writes it and a string's characters as Julia cuts them, on byte strings
# that are UTF-8 and that are not. The result files (io/resultfile.jl): trees of made-up
# descriptors and models (`result_tree`, every realisation, a mean, one realisation), the
# runs of every bundled example and of made-up models (indexed by one list and two, values
# that cannot change over the run, units, derived series), chosen series by label, by
# position and by descriptor, another model's name and lists, values from elsewhere;
# probabilistic runs (every realisation as float32, the mean, one realisation by number,
# rounded and clamped, with and without the inputs, a part of the run, float32 holding,
# realisations that fail, tornadoes and a sensitivity design) and probabilistic results
# made up by hand; scenarios side by side; and `save` -- a block's series, a time origin,
# a table, the refusals.
#
# A file is kept as an FNV-1a hash of its bytes and its length; a refusal as its words.
# With KOMPARTMENT_FIXTURE_DUMPS set every file is written there (`hdf5-<n>.julia.h5`, the
# case's number from 1 in the order the test makes them) and a table of what each case is
# (`hdf5.julia.txt`), for `cmp`. Times given in seconds since the epoch are read in UTC.
# Files `save` writes go in a folder of the system's temporary one, removed at the end, and
# what auto learns about splitting a model is not kept (KOMPARTMENT_SPLIT_MEMORY=0).

using Kompartment
using Dates
const K = Kompartment
K.set_parity!(true)

# What auto learns about splitting a model is not kept from these runs (the test does the same).
ENV["KOMPARTMENT_SPLIT_MEMORY"] = "0"
# A time in seconds since the epoch is read as local time: UTC here and in the test.
ENV["TZ"] = "UTC"
ccall(:tzset, Cvoid, ())

J(pairs...) = K.JDict(String(k) => v for (k, v) in pairs)
P(text) = K.parse_json(text)

function fnv(bytes::AbstractVector{UInt8})
    h = 0xcbf29ce484222325
    for b in bytes
        h = (h ⊻ b) * 0x100000001b3
    end
    return string(h; base=16, pad=16)
end
kept(bytes::AbstractVector{UInt8}) = "#" * fnv(bytes) * ":" * string(length(bytes))

"""What a case gives: a file's bytes, or a refusal in the package's words."""
function said(f)
    try
        return f()
    catch e
        e isa K.HDF5Error && return "error:HDF5Error:" * e.msg
        e isa ArgumentError && return "error:ArgumentError:" * e.msg
        e isa K.SolverError && return "error:SolverError:" * e.message
        e isa K.BuildError && return "error:BuildError:" * e.message
        e isa K.ValidationError && return "error:ValidationError:" * e.message
        e isa ErrorException && return "error:ErrorException:" * e.msg
        for T in (Base.InvalidCharError, BoundsError, KeyError, MethodError, InexactError, TypeError, DomainError)
            e isa T && return "error:" * string(nameof(T))
        end
        rethrow()
    end
end

const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
const TABLE = String[]
const COUNT = Ref(0)
"""A case's answer as the fixture keeps it, the file dumped where asked."""
function answer(what::String, got)
    COUNT[] += 1
    if got isa AbstractVector{UInt8}
        isempty(DUMPS) || write(joinpath(DUMPS, "hdf5-$(COUNT[]).julia.h5"), got)
        out = kept(got)
    else
        out = String(got)
    end
    push!(TABLE, "$(COUNT[]) $what $out")
    return out
end

# --- values as the fixture writes them ---------------------------------------------------------
#
# JSON keeps what it can; the rest is written as a dictionary of one key starting with `$`:
# {"$float": "NaN" | "Infinity" | "-Infinity" | "-0"}, {"$f64": [...]} (doubles, held as
# doubles), {"$f32": [...]} (singles), {"$cp": [code points]} (a string, a surrogate written
# as Julia's `Char` writes one), {"$bytes": "hex"} (a string of any bytes), {"$gen": {...}}
# (numbers made by a generator both sides run), {"$strings": {"prefix", "n", "mod"}}.

function F(x::Real)
    x = Float64(x)
    isnan(x) && return J("\$float" => "NaN")
    isinf(x) && return J("\$float" => x > 0 ? "Infinity" : "-Infinity")
    (x == 0 && signbit(x)) && return J("\$float" => "-0")
    return x
end
f64(xs) = J("\$f64" => Any[F(x) for x in xs])
f32(xs) = J("\$f32" => Any[F(x) for x in xs])
cp(cps...) = J("\$cp" => Any[Int(c) for c in cps])
bytes(hex) = J("\$bytes" => hex)
gen(n, seed; kind="f64", specials=false) = J("\$gen" => J("n" => n, "seed" => seed, "kind" => kind, "specials" => specials))

function splitmix!(s::Base.RefValue{UInt64})
    s[] += 0x9e3779b97f4a7c15
    z = s[]
    z = (z ⊻ (z >> 30)) * 0xbf58476d1ce4e5b9
    z = (z ⊻ (z >> 27)) * 0x94d049bb133111eb
    return z ⊻ (z >> 31)
end

"""The numbers a `\$gen` makes: across eighty powers of two, NaN, the infinities, -0.0 and the
least subnormal sprinkled in when asked."""
function generated(g)
    n = Int(g["n"])
    s = Ref(UInt64(g["seed"]))
    specials = g["specials"] === true
    out = Vector{Float64}(undef, n)
    for k in 0:n-1
        m = Float64(splitmix!(s) >> 11) * 0x1p-53
        e = Int(splitmix!(s) % 81) - 40
        x = ldexp(2m - 1, e)
        if specials
            k % 101 == 7 && (x = NaN)
            k % 103 == 11 && (x = Inf)
            k % 107 == 13 && (x = -Inf)
            k % 109 == 17 && (x = -0.0)
            k % 113 == 19 && (x = 5e-324)
        end
        out[k+1] = x
    end
    kind = g["kind"]
    kind == "f32" && return Float32.(out)
    kind == "any" && return Any[x for x in out]
    return out
end

num(x) = x isa AbstractDict ? Float64(dec(x)) : Float64(x)

function dec(v)
    if v isa AbstractDict
        if length(v) == 1
            k, x = first(v)
            if startswith(k, '$')
                if k == "\$float"
                    return x == "NaN" ? NaN : x == "Infinity" ? Inf : x == "-Infinity" ? -Inf : -0.0
                end
                k == "\$f64" && return Float64[num(y) for y in x]
                k == "\$f32" && return Float32[Float32(num(y)) for y in x]
                k == "\$cp" && return join(Char(UInt32(c)) for c in x)
                k == "\$bytes" && return String(hex2bytes(x))
                k == "\$gen" && return generated(x)
                if k == "\$strings"
                    m = get(x, "mod", 0)
                    return Any[string(x["prefix"], m > 0 ? j % m : j) for j in 0:x["n"]-1]
                end
            end
        end
        return K.JDict(String(k) => dec(x) for (k, x) in v)
    elseif v isa AbstractVector
        return Any[dec(x) for x in v]
    end
    return v
end

stamp(s) = s === nothing ? nothing : haskey(s, "epoch") ? Float64(s["epoch"]) : DateTime(s["local"]...)
const NOW = J("local" => Any[2026, 10, 10, 9, 5, 7])

# --- trees made up step by step --------------------------------------------------------------------

mutable struct Rec
    ops::Vector{Any}
    n::Int
end
Rec() = Rec(Any[], 0)
function group!(r::Rec, attrs=nothing)
    push!(r.ops, J("op" => "group", "id" => r.n, "attrs" => attrs))
    return (r.n += 1) - 1
end
function dataset!(r::Rec, data, dt="F64", attrs=nothing, dims=nothing)
    push!(r.ops, J("op" => "dataset", "id" => r.n, "data" => data, "dt" => dt, "attrs" => attrs, "dims" => dims))
    return (r.n += 1) - 1
end
place!(r::Rec, root, path, node) = push!(r.ops, J("op" => "put", "root" => root, "path" => Any[path...], "node" => node))
function at!(r::Rec, root, path)
    push!(r.ops, J("op" => "at", "id" => r.n, "root" => root, "path" => Any[path...]))
    return (r.n += 1) - 1
end
set_attr!(r::Rec, node, key, value) = push!(r.ops, J("op" => "set_attr", "node" => node, "key" => key, "value" => value))
delete_attr!(r::Rec, node, key) = push!(r.ops, J("op" => "delete_attr", "node" => node, "key" => key))

const TREES = Any[]
function tree(build, name)
    r = Rec()
    root = build(r)
    push!(TREES, J("name" => name, "ops" => r.ops, "root" => root))
end

tree("empty root") do r
    group!(r)
end

tree("root attributes") do r
    group!(r, J("name" => "Two boxes", "17" => "seventeen", "count" => 3, "0" => "zero", "ratio" => 0.1, "3" => 3.5,
                "01" => "not an index", "flag" => true, "off" => false, "4294967294" => "the largest index",
                "4294967295" => "not an index", "none" => nothing, "list" => Any[1, 2.5, -3], "strings" => Any["a", "b", "a"],
                "mixed" => Any[1, "two", nothing, 3.25, 1e21, 1e-7, true], "bools" => Any[true, false, true],
                "nulls_and_numbers" => Any[nothing, 1, nothing], "empty_list" => Any[], "nan" => F(NaN), "inf" => F(Inf),
                "ninf" => F(-Inf), "negzero" => F(-0.0), "big" => 2^53 + 1, "huge" => 1.7976931348623157e308, "tiny" => 5e-324,
                "numeric_string" => "5", "dict" => J("a" => 1), "nested" => Any[Any[1, 2], Any[3]],
                "nested_text" => Any["x", Any[1, 2], Any[3, nothing]], "special_list" => Any[F(NaN), F(-0.0), F(Inf), 1],
                "special_text" => Any["s", F(NaN), F(-Inf), F(-0.0), 0.1 + 0.2], "dict_in_list" => Any[J("a" => 1), 2],
                "dict_in_text" => Any[J(), "t"], "åäö" => "non-ASCII name", "value åäö 日本 😀" => "non-ASCII value åäö 日本 😀",
                "empty" => "", "spaces" => "  padded  ",
                "number_texts" => Any[100000, 0.000015, 1e-7, 1e21, 1.5e300, F(-0.0), 123456789012345680.0, 0.1 + 0.2],
                "number_texts_str" => Any["n", 100000, 0.000015, 1e-7, 1e21, 1.5e300, F(-0.0), 123456789012345680.0, 0.1 + 0.2,
                                          5e-324, 1.1805916207174113e21, -1e-7, 1e-6, 1.23e-18, 1e20, 2^53 + 1, F(NaN), F(-Inf)]))
end

tree("only index keys") do r
    group!(r, J("10" => "ten", "2" => "two", "0" => "zero", "1" => true, "11" => Any[1, 2], "4294967294" => 9))
end

tree("nested") do r
    root = group!(r, J("model" => "nested"))
    leaf = dataset!(r, Any[1.0, 2.0, 3.0], "F64", J("unit" => "Bq"))
    place!(r, root, ["a", "b", "c", "d", "e"], leaf)
    place!(r, root, ["", "a", "", "x"], dataset!(r, Any[4.0], "F64", J("unit" => "kg")))
    place!(r, root, ["a", "b", "y"], dataset!(r, Any["p", "q"], "STR"))
    g = group!(r, J("kind" => "explicit"))
    place!(r, root, ["a", "g"], g)
    place!(r, root, ["a", "g", "z"], dataset!(r, Any[7, 8, 9], "I32"))
    # attributes set on groups put made, after they were made
    set_attr!(r, at!(r, root, ["a"]), "IndexLists", Any["Radionuclides"])
    b = at!(r, root, ["a", "b"])
    set_attr!(r, b, "time_dependent", true)
    set_attr!(r, b, "0", "first")
    set_attr!(r, b, "time_dependent", false)      # set again: keeps its place
    set_attr!(r, b, "gone", 5)
    delete_attr!(r, b, "gone")
    set_attr!(r, g, "kind", nothing)              # set to nothing: not written
    root
end

tree("many children") do r
    root = group!(r, J("children" => 400))
    for k in 0:399
        name = "child $(lpad(k, 3, '0')) $("åäö"[[1, 3, 5][k%3+1]])"
        if k % 7 == 0
            node = group!(r, J("k" => k, "even" => k % 2 == 0))
            place!(r, root, [name], node)
            place!(r, root, [name, "inner"], dataset!(r, gen(k % 5, k), "F64"))
        else
            place!(r, root, [name], dataset!(r, gen(k % 11, 1000 + k; kind=k % 2 == 0 ? "f64" : "any"), "F64",
                                           J("unit" => ["Bq", "kg", "m"][k%3+1], "k" => k)))
        end
    end
    root
end

tree("datasets") do r
    root = group!(r, J("model" => "datasets"))
    put(name, args...) = place!(r, root, [name], dataset!(r, args...))
    put("f64", f64([0.0, 1.0, -1.5, 1e300, 5e-324, -0.0, NaN, Inf, -Inf, 2^53 + 1, 7]))
    put("f64_values", Any[0.0, 1, -1.5, F(NaN), F(-0.0), F(Inf), 2^53 + 1, 9007199254740993, -7])
    put("f64_empty", f64(Float64[]), "F64", J("note" => "nothing"))
    put("f64_empty_values", Any[], "F64")
    put("f64_from_text", Any["5", " 0x10 ", "", nothing, true, false, "abc", "1e999", "1e-400", "Infinity", "-Infinity",
                             "infinity", "1_000", ".5", "5.", "+3", "0b101", "0o17", " 5﻿", "\u00855", " 5 ",
                             "0x", "00012", "-.5e-3", "1e", Any[], Any[5], Any["5"], Any[1, 2], Any[nothing], Any[true],
                             J("a" => 1), J(), "2.4703282292062327e-324", "0X1f", "0b2"], "F64")
    put("f64_str_data", "abc 5 é", "F64")
    put("f64_number_data", 5.0, "F64")
    put("f64_null_data", nothing, "F64")
    put("f64_bool_data", true, "F64")
    put("f64_dict_data", J("5" => 1, "x" => 2, " 7 " => 3), "F64")
    put("f64_from_f32", f32([0.1, 3.4e38, NaN, -0.0]), "F64")
    put("f32", Any[0.1, 1e39, -1e39, 3.4028235677973366e38, 3.4028235677973362e38, -1e-50, 16777217, F(NaN),
                   1.401298464324817e-45, 7e-46, 1.1529215733070807e18, nothing, "2.5", F(-0.0), F(Inf)], "F32")
    put("f32_from_f64", f64([0.1, 1e39, 2.5, 7e-46, -1e-50, 16777217]), "F32")
    put("f32_typed", f32([0.1, 2.5, NaN, -Inf]), "F32")
    put("f32_str_data", "1 2", "F32")
    put("i32", Any[2^31, -2^31 - 1, 4294967296 + 5, 1.9, -1.9, F(NaN), F(Inf), F(-Inf), 1e20, "12", nothing, true, -0.5,
                   2^53 + 1, -4294967297, F(-0.0), 2147483647.9, -2147483648.9, 4294967295, 1.7976931348623157e308,
                   "-0x10", Any[3], "abc"], "I32")
    put("i32_from_f64", f64([2.0^31, -2.0^31 - 1, 1.5e10, -0.0, NaN]), "I32")
    put("i32_from_f32", f32([3e9, -3e9, 2.5]), "I32")
    put("i32_str_data", "9a", "I32")
    put("str", Any["Cs-137", "åäö", "日本", "😀", "", "Cs-137", "åäö", 1, 1.5, 1e21, nothing, true, false, Any[1, 2], J("a" => 1),
                   "TRUE", F(NaN), F(-0.0), 2^53 + 1, Any[nothing, Any[1, nothing]], 5e-324],
        "STR", J("unit" => "Cs-137", "flag" => true))
    put("str_empty", Any[], "STR")
    put("str_text_data", "xyz åäö 😀", "STR")
    put("str_dict_data", J("k1" => 1, "Cs-137" => 2), "STR")
    put("str_number_data", 7, "STR")
    put("str_from_f64", f64([1.0, 0.1, 1e21, NaN, -Inf, -0.0, 5e-324]), "STR")
    put("str_from_f32", f32([0.1, 16777217, 1e-45]), "STR")
    put("matrix_f64", f64((0:11) ./ 7.0), "F64", J("shape" => Any[3, 4]), Any[3, 4])
    put("matrix_f32", f64((0:5) ./ 3.0), "F32", nothing, Any[2, 3])
    put("cube", f64(0:23), "F64", nothing, Any[2, 3, 4])
    put("flat_dims", Any[1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "F32", J("n_iter" => 3), Any[2, 3])
    put("dims_float_text", Any[1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "F64", nothing, Any[2.0, "3"])
    put("dims_fraction", f64(1:5), "F64", nothing, Any[2.5, 2])
    put("dims_negative", f64(1:2), "F64", nothing, Any[-1, -2])
    put("dims_negative_fraction", f64(1:3), "F64", nothing, Any[-1.5, -2])
    put("dims_big", Any[], "F64", nothing, Any[0, 1.8446744073709552e19])
    put("dims_huge_negative", Any[], "F64", nothing, Any[0, -3.6893488147419103e19, -1.0e300])
    put("dims_bool_null_text", f64(1:2), "F64", nothing, Any[true, "2", Any[1]])
    put("scalar", Any[42.0], "F64", nothing, Any[])
    put("scalar_str", Any["one"], "STR", nothing, Any[])
    put("scalar_i32", Any[-3], "I32", J("what" => "a scalar"), Any[])
    put("dims_zero", Any[], "F64", nothing, Any[0, 5])
    put("np_bool", Any[true, false, true], "F64")
    root
end

tree("dims that do not multiply out") do r
    root = group!(r)
    place!(r, root, ["x"], dataset!(r, f64([1.0, 2.0, 3.0]), "F64", nothing, Any[2, 2]))
    root
end

tree("dims of nothing and text") do r
    root = group!(r)
    place!(r, root, ["x"], dataset!(r, f64([1.0, 2.0]), "F64", nothing, Any[nothing, "two", F(NaN), 2.5]))
    root
end

tree("dims of infinity") do r
    root = group!(r)
    place!(r, root, ["x"], dataset!(r, Any[], "F64", nothing, Any[F(Inf), 0]))
    root
end

tree("names") do r
    root = group!(r, J("model" => "names"))
    long = "L"^300
    place!(r, root, [long], dataset!(r, f64([1.0]), "F64", J(long => "long attribute name")))
    place!(r, root, ["å"^200], dataset!(r, f64([2.0])))           # 400 bytes: a long link
    place!(r, root, ["x"^255], dataset!(r, f64([3.0])))           # exactly 255
    place!(r, root, ["y"^256], dataset!(r, f64([4.0])))           # just over
    place!(r, root, ["with space", "Cs-137"], dataset!(r, f64([5.0])))
    place!(r, root, ["k.eff"], dataset!(r, f64([6.0])))
    place!(r, root, ["Söil ⁄ Lake"], dataset!(r, f64([7.0])))
    place!(r, root, ["🙂"^70], dataset!(r, f64([8.0])))            # 280 bytes
    root
end

tree("text that is not UTF-8") do r
    root = group!(r, J("lone" => cp(0xd800), "pair" => cp(0xd83d, 0xde00), "joined" => "😀", "reversed" => cp(0xdc00, 0xd800),
                       "list" => Any[cp(0xdbff), "ok", bytes("ff41")], "bad" => bytes("41e28242"), "cut" => bytes("f09f98")))
    place!(r, root, ["s"], dataset!(r, Any[cp(0xd800), cp(0x61, 0xdc00, 0x62), "😀", cp(0xd83d, 0xde00), cp(0xdc00, 0xd800), "😀",
                                        bytes("80"), bytes("c0"), bytes("e080"), bytes("f4908080"), bytes("f5808080"), bytes("f8"),
                                        bytes("ed9fbf"), bytes("ee8080"), bytes("f48fbfbf"), bytes("eda080edb080"), bytes("00ff00")], "STR"))
    place!(r, root, [bytes("6162ff")], dataset!(r, Any[1], "F64"))
    place!(r, root, ["chars"], dataset!(r, bytes("61e282ffc3a9eda080"), "STR"))
    place!(r, root, ["char numbers"], dataset!(r, bytes("35ff3620"), "F64"))
    set_attr!(r, root, bytes("6e616d65ff"), "an attribute name that is not UTF-8")
    set_attr!(r, root, cp(0x6b, 0xd800), cp(0x76, 0xdfff))
    root
end

tree("an overlong form") do r
    root = group!(r, J("x" => bytes("c080")))
    root
end

tree("an overlong form in a name") do r
    root = group!(r)
    place!(r, root, [bytes("e08080")], dataset!(r, Any[1]))
    root
end

tree("an overlong form in data") do r
    root = group!(r)
    place!(r, root, ["s"], dataset!(r, Any["ok", bytes("f0808080")], "STR"))
    root
end

tree("two collections") do r
    # More strings than one global heap collection holds (60000): the second collection, and
    # heap IDs that point into both.
    root = group!(r, J("first" => "string 0", "last" => "string 69999"))
    place!(r, root, ["strings"], dataset!(r, J("\$strings" => J("prefix" => "string ", "n" => 70000)), "STR"))
    place!(r, root, ["again"], dataset!(r, Any["string 59999", "string 60000", "new one", "string 5"], "STR",
                                       J("unit" => "string 65000", "other" => "after them all")))
    place!(r, root, ["pooled"], dataset!(r, J("\$strings" => J("prefix" => "p", "n" => 130000, "mod" => 65000)), "STR"))
    root
end

tree("three collections of long strings") do r
    root = group!(r)
    place!(r, root, ["long"], dataset!(r, J("\$strings" => J("prefix" => "x"^200, "n" => 125000)), "STR"))
    root
end

tree("big") do r
    root = group!(r, J("model" => "big"))
    place!(r, root, ["time"], dataset!(r, gen(1000, 7), "F64", J("unit" => "year")))
    place!(r, root, ["big"], dataset!(r, gen(1_000_000, 1; specials=true), "F64", J("unit" => "Bq")))
    place!(r, root, ["big32"], dataset!(r, gen(100_000, 2; kind="f32", specials=true), "F32"))
    place!(r, root, ["big32 from doubles"], dataset!(r, gen(100_000, 3; specials=true), "F32"))
    place!(r, root, ["big int"], dataset!(r, gen(50_000, 4; kind="any", specials=true), "I32"))
    place!(r, root, ["big text"], dataset!(r, gen(20_000, 5; specials=true), "STR"))
    root
end

tree("a second thing at one path") do r
    root = group!(r)
    place!(r, root, ["a", "b"], dataset!(r, Any[1]))
    place!(r, root, ["a", "", "b"], dataset!(r, Any[2]))
    root
end

tree("inside a dataset") do r
    root = group!(r)
    place!(r, root, ["a"], dataset!(r, Any[1]))
    place!(r, root, ["a", "b"], dataset!(r, Any[2]))
    root
end

tree("a slash in a name") do r
    root = group!(r)
    place!(r, root, ["x/y"], dataset!(r, Any[1]))
    root
end

tree("a slash on the way") do r
    root = group!(r)
    place!(r, root, ["x/y", "z"], dataset!(r, Any[1]))
    root
end

tree("nothing but empty names") do r
    root = group!(r)
    place!(r, root, ["", ""], dataset!(r, Any[1]))
    root
end

tree("a dataset as the root") do r
    dataset!(r, Any[1])
end

const DT = Dict("F64" => K.H5F64, "F32" => K.H5F32, "I32" => K.H5I32, "STR" => K.H5STR)

function build_tree(c)
    nodes = Dict{Int,Any}()
    for op in c["ops"]
        kind = op["op"]
        if kind == "group"
            nodes[op["id"]] = K.h5group(dec(op["attrs"]))
        elseif kind == "dataset"
            nodes[op["id"]] = K.h5dataset(dec(op["data"]), DT[op["dt"]], dec(op["attrs"]), dec(op["dims"]))
        elseif kind == "put"
            K.h5put(nodes[op["root"]], String[dec(p) for p in op["path"]], nodes[op["node"]])
        elseif kind == "at"
            node = nodes[op["root"]]
            for p in op["path"]
                node = node.children[dec(p)]
            end
            nodes[op["id"]] = node
        elseif kind == "set_attr"
            nodes[op["node"]].attrs[dec(op["key"])] = dec(op["value"])
        elseif kind == "delete_attr"
            delete!(nodes[op["node"]].attrs, dec(op["key"]))
        else
            error("unknown op $kind")
        end
    end
    return K.write_hdf5(nodes[c["root"]])
end

# --- lookup3, and text as it is written ------------------------------------------------------------

pattern(n, seed) = UInt8[(k * 131 + seed * 7 + (k >> 3) * 17) % 256 for k in 0:n-1]
const LOOKUPS = Any[]
for n in vcat(0:40, [47, 48, 49, 59, 60, 61, 100, 1000, 4096]), seed in (1, 2)
    push!(LOOKUPS, J("n" => n, "seed" => seed))
end
# Bytes past the end read as zeros.
for (n, start, len) in ((10, 0, 12), (10, 5, 12), (30, 0, 30), (30, 29, 13), (5, 5, 4), (5, 9, 3), (0, 0, 7))
    push!(LOOKUPS, J("n" => n, "seed" => 3, "start" => start, "len" => len))
end

const UTF8 = Any[]
for hex in ["", "41", "c380", "eda080", "eda080edb080", "edb080eda080", "c080", "c0", "c1bf", "c2", "e080", "e08080", "e0a080",
            "f0808080", "f0908080", "f4908080", "f5808080", "f7bfbfbf", "f8", "fe", "ff", "80", "bf", "ff41", "e282", "e28241",
            "f09f9880", "f09f98", "f09f", "41eda08042", "edbfbf", "eda0", "eda080eda080", "eda080edb0", "efbfbd", "00", "6100",
            "c3a9c3", "e2828c", "f48fbfbf", "e0a0", "dfbf", "df", "edb080", "ed9fbf", "ee8080", "c0af", "e0828f", "f08282ac",
            "41c08042", "eda080c080", "c080eda080", "f0808080f09f9880"]
    push!(UTF8, hex)
end
let s = Ref(UInt64(99)), interesting = UInt8[0x00, 0x41, 0x7f, 0x80, 0x8f, 0x90, 0x9f, 0xa0, 0xbf, 0xc0, 0xc1, 0xc2, 0xdf, 0xe0,
                                              0xed, 0xee, 0xef, 0xf0, 0xf4, 0xf5, 0xf7, 0xf8, 0xff, 0xb0, 0xdc, 0xd8, 0x2f]
    for _ in 1:1200
        n = Int(splitmix!(s) % 9) + 1
        b = UInt8[interesting[Int(splitmix!(s) % length(interesting))+1] for _ in 1:n]
        push!(UTF8, bytes2hex(b))
    end
end

function utf8_case(hex)
    s = String(hex2bytes(hex))
    chars = join((bytes2hex(codeunits(string(c))) for c in s), ",")
    out = try
        bytes2hex(codeunits(K._h5_utf8(s)))
    catch e
        e isa Base.InvalidCharError || rethrow()
        "error:" * sprint(showerror, e)
    end
    return J("in" => hex, "out" => out, "chars" => chars, "count" => length(s))
end

# --- descriptors and models -------------------------------------------------------------------------

"""A descriptor as the application makes one (`o` in julia/tools/hdf5_fixtures.py)."""
function O(label; block=:auto, kind="compartment", nuclide=nothing, index=nothing, dims=nothing, unit="Bq", extra...)
    d = J("kind" => kind, "block" => block === :auto ? String(split(label, " [")[1]) : block, "nuclide" => nuclide,
          "index" => index, "dims" => dims === nothing ? Any[] : dims, "label" => label, "unit" => unit, "source" => "y",
          "offset" => 0)
    for (k, v) in extra
        d[String(k)] = v
    end
    return d
end

DEMO = Any[
    O("Soil [Cs-137]"; nuclide="Cs-137", index=Any["Cs-137"], dims=Any["Radionuclides"]),
    O("Soil [H-3]"; nuclide="H-3", index=Any["H-3"], dims=Any["Radionuclides"]),
    O("NearField.Flux"; kind="expression", unit="Bq/y"),
    O("Dose [Lake, Cs-137]"; kind="expression", nuclide="Cs-137", index=Any["Lake", "Cs-137"], dims=Any["Areas", "Radionuclides"], unit="Sv/y"),
    O("Dose [Lake, H-3]"; kind="expression", nuclide="H-3", index=Any["Lake", "H-3"], dims=Any["Areas", "Radionuclides"], unit="Sv"),
    O("Dose [Mire, Cs-137]"; kind="expression", nuclide="Cs-137", index=Any["Mire", "Cs-137"], dims=Any["Areas", "Radionuclides"], unit="Sv/y"),
    O("Flow [A, x]"; kind="transfer", index=Any["A", "x"], dims=Any["L1", "L2"], unit="m3/y"),
    O("Flow [B, x]"; kind="transfer", nuclide="Pu-239", index=Any["B", "x"], dims=Any["L1", "L2"], unit="m3/y"),
    O("porosity"; kind="parameter", unit="unitless", source="P", timeDependent=false),
    O("Kd [Cs-137]"; kind="parameter", nuclide="Cs-137", index=Any["Cs-137"], dims=Any["Radionuclides"], unit="m3/kg", source="P", timeDependent=false),
    O("a/b [x]"; block="a/b", index=Any["x/y"], dims=Any["L2"], unit=nothing),
    O(" spaced "; block="  spaced  ", unit=0),
    O("dot"; block="."),
    O("empty block"; block=""),
    O("dots"; block="sys..sub.Block"),
    O("quote \"x\", y\nz"; block="Odd", unit="Bq"),
    O("Söil [Cs-137]"; nuclide="Cs-137", index=Any["Cs-137"], dims=Any["Radionuclides"]),
    J("kind" => "compartment", "block" => nothing, "label" => nothing, "unit" => "Bq"),
    J("kind" => nothing, "unit" => "Bq"),
    J("unit" => "Bq"),
    O("Numbers [1, 2]"; index=Any[1, 2], dims=Any["N", "M"], nuclide=2),
    O("Short dims [Lake, Cs-137]"; nuclide="Cs-137", index=Any["Lake", "Cs-137"], dims=Any["Radionuclides"]),
    O("Null dims [p, q]"; index=Any["p", "q"], dims=Any[nothing, nothing]),
    O("NearField"; kind="expression", unit="Bq"),
    O("Pair [Lake, Cs-137]"; nuclide=nothing, index=Any["Lake", "Cs-137"], dims=Any["Areas", ""]),
    O("Bool unit"; unit=true),
    O("Number nuclide [Cs-137]"; nuclide=137, index=Any["Cs-137"], dims=Any["Radionuclides"]),
    O("Units [a]"; block="Units", index=Any["a"], dims=Any["U"], unit="kg"),
    O("Units [b]"; block="Units", index=Any["b"], dims=Any["U"], unit="g"),
    O("Units [c]"; block="Units", index=Any["c"], dims=Any["U"], unit="kg"),
    O("Same [a]"; block="Same", index=Any["a"], dims=Any["U"], unit=1),
    O("Same [b]"; block="Same", index=Any["b"], dims=Any["U"], unit=true),
    O("Same [c]"; block="Same", index=Any["c"], dims=Any["U"], unit=1.0),
    O("Listed [a]"; block="Listed", index=Any["a"], dims=Any["U"], unit=Any["m", 1]),
    O("Listed [b]"; block="Listed", index=Any["b"], dims=Any["U"], unit=Any["m", 1.0]),
    O("Text index"; block="Chars", index="ab", dims="UV"),
    O("Dict index"; block="Keys", index=J("k" => 1), dims=J("D" => 2)),
    O("Numbered nuclide [7]"; index=Any[7.0, 8], dims=Any["N", "M"], nuclide=7),
    O("Still group [a]"; block="Still", index=Any["a"], dims=Any["U"], timeDependent=false),
    O("Number block"; block=12.5),
    O("List block"; block=Any["x", "y"]),
    O("Truthy dim [a]"; block="TD", index=Any["a"], dims=Any[0]),
]

demo_columns(n, times, seed) = Any[gen(times, seed * 100 + k; specials=true) for k in 0:n-1]

const DESCRIPTION = "Line one & <two>\r\nline three\r\n\r\n\r\nSecond paragraph\rwith a CR.\n\n  "
PROJECT = J("name" => "Demo model", "description" => DESCRIPTION,
            "simulation" => J("time_unit" => "day", "start_time" => "5", "end_time" => nothing, "solver" => "bdf"),
            "index_lists" => Any[J("name" => "Cases", "for_scenarios" => true, "indices" => Any["A", "B"])])
INDEX_LISTS = Any[
    J("name" => "Radionuclides", "indices" => Any[J("name" => "Cs-137", "enabled" => true), J("name" => "H-3", "enabled" => false),
                                                  "Bare", nothing, J("name" => nothing), Any["x"], J("name" => 137)]),
    J("name" => "Areas", "elements" => Any["Lake", "Mire", nothing]),
    J("name" => "Empty", "indices" => Any[]),
    J("name" => "a/b", "elements" => Any["x"]),
    J("elements" => Any["y"]),
    J("name" => "Radionuclides", "elements" => Any["dup"]),
    J("name" => nothing, "indices" => Any[J("name" => "n1")]),
    J("name" => "Chars", "elements" => "xyz"),
    J("name" => "Off", "indices" => Any[J("name" => "gone", "enabled" => false)]),
    J("name" => "Keys", "indices" => J("k1" => 1, "k2" => 2)),
    J("name" => " .. ", "elements" => Any[1.5, true, Any[1, 2], J()]),
    "not a list",
    J("name" => "Zero", "indices" => 0, "elements" => Any["z"]),
]

const RESULT_TREES = Any[]
function rt_case(name; t, outputs, columns, which, project=nothing, index_lists=nothing, now=NOW, realisations=nothing, sample=nothing)
    push!(RESULT_TREES, J("name" => name, "t" => t, "outputs" => outputs, "columns" => columns, "which" => which, "project" => project,
                          "index_lists" => index_lists, "now" => now, "realisations" => realisations, "sample" => sample))
end

let t = f64([0.0, 1.0, 2.5, 10.0, 1e3, 1e5]), cols = demo_columns(length(DEMO), 6, 3), every = collect(1:length(DEMO))
    rt_case("every kind of descriptor"; t, outputs=DEMO, columns=cols, which=every, project=PROJECT, index_lists=INDEX_LISTS)
    rt_case("some, again and again"; t, outputs=DEMO, columns=cols, which=[4, 1, 4, 9, 9, 3, 24],
            project=J("name" => 7, "simulation" => J("time_unit" => Any["a", "b"], "start_time" => "x", "end_time" => 1e21, "solver" => 3)))
    rt_case("seconds since the epoch"; t=f64([0.0, 1.0, 2.5]), outputs=DEMO[1:3], columns=Any[gen(3, k) for k in 1:3], which=[1, 2, 3],
            now=J("epoch" => 1760000000.75))
    rt_case("seconds before the epoch"; t=f64([0.0]), outputs=DEMO[1:1], columns=Any[gen(1, 1)], which=[1], now=J("epoch" => -1.25))
    rt_case("a carried second"; t=f64([0.0]), outputs=DEMO[1:1], columns=Any[gen(1, 1)], which=[1], now=J("epoch" => 1759999999.9999996))
    rt_case("no times"; t=f64(Float64[]), outputs=DEMO[1:2], columns=Any[f64(Float64[]), f64(Float64[])], which=[1, 2],
            project=J("name" => nothing, "description" => "   ", "simulation" => nothing))
    rt_case("a model that is not a dictionary"; t=f64([0.0, 1.0]), outputs=DEMO[9:10], columns=Any[gen(2, 1), gen(2, 2)], which=[1, 2],
            project="a model?", index_lists=J("Radionuclides" => Any["x"]))
    rt_case("a description that is not text"; t=f64([1.0]), outputs=DEMO[1:1], columns=Any[gen(1, 3)], which=[1],
            project=J("description" => Any[1, nothing, "two"], "simulation" => "not a dictionary"))
    rt_case("nothing chosen"; t, outputs=DEMO, columns=cols, which=Int[], project=PROJECT, index_lists=INDEX_LISTS[1:2])
    rt_case("a descriptor whose dims are a number"; t, outputs=Any[O("x"; index=Any["a"], dims=5)], columns=cols[1:1], which=[1])
    rt_case("a list whose indices are true"; t, outputs=DEMO[1:1], columns=cols[1:1], which=[1],
            index_lists=Any[J("name" => "T", "indices" => true)])
    rt_case("a place taken 999 times over"; t=f64([0.0]), outputs=Any[O("NearField"; kind="expression"), O("NearField.Flux"; kind="expression")],
            columns=Any[gen(1, 1), gen(1, 2)], which=[1, 2])
    rt_case("numbered past a name taken"; t=f64([0.0]), outputs=Any[O("A"; block="A"), O("A"; block="A"), O("A"; block="A"),
                                                                    O("IndexLists"; block="IndexLists"), O("time"; block="time")],
            columns=Any[gen(1, k) for k in 1:5], which=[1, 2, 3, 4, 5], index_lists=Any[J("name" => "A", "elements" => Any["a"])])

    rt_t = f64([0.0, 1.0, 2.0, 3.0])
    n = 5
    routs = Any[DEMO[1], DEMO[2], DEMO[9], DEMO[10], DEMO[3], DEMO[4], DEMO[findfirst(o -> get(o, "label", nothing) == "Still group [a]", DEMO)]]
    rcols = demo_columns(length(routs), 4, 9)
    mats = Any[Any[1, f32(generated(J("n" => 4 * n, "seed" => 51, "kind" => "f64", "specials" => true)))],
               Any[2, f64(generated(J("n" => 4 * n, "seed" => 52, "kind" => "f64", "specials" => false)))],
               Any[3, f32(generated(J("n" => n, "seed" => 53, "kind" => "f64", "specials" => false)))],
               Any[4, f32(generated(J("n" => n + 3, "seed" => 54, "kind" => "f64", "specials" => false)))],      # cut to n
               Any[6, f32(generated(J("n" => 4 * n, "seed" => 56, "kind" => "f64", "specials" => false)))],
               Any[7, f32(generated(J("n" => n + 2, "seed" => 57, "kind" => "f64", "specials" => false)))]]
    rt_case("every realisation"; t=rt_t, outputs=routs, columns=rcols, which=collect(1:7), project=PROJECT, index_lists=INDEX_LISTS[1:2],
            realisations=J("iterations" => n, "matrices" => mats))
    rt_case("every realisation, a sample besides"; t=rt_t, outputs=routs, columns=rcols, which=collect(1:7), project=PROJECT,
            realisations=J("iterations" => n, "matrices" => mats), sample=J("iterations" => 99, "of" => 3))
    rt_case("every realisation, cut by a negative count"; t=rt_t, outputs=routs[3:4], columns=rcols[3:4], which=[1, 2],
            realisations=J("iterations" => -2, "matrices" => Any[Any[1, f32([1, 2, 3])], Any[2, f32([1, 2, 3, 4, 5, 6])]]))
    rt_case("every realisation, counted in text"; t=rt_t, outputs=routs[3:3], columns=rcols[3:3], which=[1],
            realisations=J("iterations" => "2", "matrices" => Any[Any[1, f32([1, 2, 3])]]))
    rt_case("every realisation, a count that is no number"; t=rt_t, outputs=routs[1:1], columns=rcols[1:1], which=[1],
            realisations=J("iterations" => nothing, "matrices" => Any[Any[1, f32(Float64[])]]))
    rt_case("every realisation, a count that is not there"; t=rt_t, outputs=routs[1:1], columns=rcols[1:1], which=[1],
            realisations=J("matrices" => Any[Any[1, f32(1:20)]]))
    rt_case("every realisation, of none"; t=rt_t, outputs=routs[3:3], columns=rcols[3:3], which=[1],
            realisations=J("matrices" => Any[]))
    rt_case("every realisation, the wrong shape"; t=rt_t, outputs=routs[1:1], columns=rcols[1:1], which=[1],
            realisations=J("iterations" => 5, "matrices" => Any[Any[1, f32(1:19)]]))
    rt_case("the mean"; t, outputs=DEMO, columns=cols, which=every[1:12], project=PROJECT, sample=J("iterations" => 100, "of" => "mean"))
    rt_case("one realisation"; t, outputs=DEMO, columns=cols, which=every[1:12], project=PROJECT, sample=J("iterations" => 100, "of" => 7))
    rt_case("one realisation, said oddly"; t, outputs=DEMO[1:3], columns=cols[1:3], which=[1, 2, 3], project=PROJECT, sample=J("of" => "12"))
    rt_case("a sample of nothing"; t, outputs=DEMO[1:3], columns=cols[1:3], which=[1, 2, 3], sample=J("iterations" => nothing, "of" => nothing))
    rt_case("a sample that says nothing"; t, outputs=DEMO[9:10], columns=cols[9:10], which=[1, 2], sample=J())
end

# The models made up to reach what the bundled examples do not.
const MODELS = Any[]
model(name, text) = push!(MODELS, (name, P(text)))

model("two lists", """{"name": "two lists", "description": "Two dimensions & <more>\\n\\nA second paragraph.",
 "simulation": {"start_time": 0, "end_time": 100, "output_points": 6, "spacing": "linear", "solver": "ndf", "rtol": 1e-6,
                "abstol": 1e-9, "time_unit": "year"},
 "nuclides": ["Cs-137", "I-129"], "half_lives": {"Cs-137": 30.17, "I-129": 1.57e7}, "decay_unit": "Bq",
 "index_lists": [{"name": "Zone", "indices": [{"name": "a"}, {"name": "b"}, {"name": "c", "enabled": false}]}],
 "parameters": [{"name": "k", "value": 0.05}, {"name": "Kd", "value": 0.5, "index_lists": ["Zone"], "unit": "m3/kg"}],
 "compartments": [{"name": "Soil", "initial": "100", "index_lists": ["Zone", "Radionuclides"]},
                  {"name": "Lake", "initial": "0", "index_lists": ["Zone", "Radionuclides"]}],
 "transfers": [{"name": "Leach", "from": "Soil", "to": "Lake", "rate": "k * Kd", "index_lists": ["Zone", "Radionuclides"]}],
 "expressions": [{"name": "Dose", "equation": "Lake * 1e-9", "index_lists": ["Zone", "Radionuclides"], "unit": "Sv/y"},
                 {"name": "Total", "equation": "Lake[a][Cs-137] + Lake[b][I-129]"}],
 "derived": [{"name": "PeakTotal", "kind": "max", "of": "Total [Cs-137]"}, {"name": "Released", "kind": "integral", "of": "Total [I-129]"},
             {"name": "When", "kind": "time_of_max", "of": "Dose [b, Cs-137]"}, {"name": "Nowhere", "kind": "max", "of": "Not a series"}],
 "inflows": []}""")

model("units", """{"name": "units", "description": "Units of every kind.",
 "simulation": {"start_time": 10, "end_time": 50, "output_points": 5, "spacing": "linear", "solver": "ndf", "time_unit": "day"},
 "index_lists": [{"name": "Phase", "indices": [{"name": "solid"}, {"name": "liquid"}]}],
 "parameters": [{"name": "rate", "value": 0.01, "unit": "1/day"}, {"name": "mass", "value": 2, "unit": "kg"},
                {"name": "share", "value": 0.5, "index_lists": ["Phase"], "unit": ""}],
 "compartments": [{"name": "Tank", "initial": "mass * 1000", "unit": "g"}, {"name": "Sink", "initial": "0", "unit": "g"},
                  {"name": "Parts", "initial": "share", "index_lists": ["Phase"], "unit": "mol"}],
 "transfers": [{"name": "Drain", "from": "Tank", "to": "Sink", "rate": "rate"}, {"name": "Mix", "from": "Parts", "to": null, "rate": "rate",
               "index_lists": ["Phase"]}],
 "expressions": [{"name": "Flow", "equation": "rate * Tank", "unit": "g/day"}, {"name": "Ratio", "equation": "Sink / (Tank + Sink)", "unit": "unitless"},
                 {"name": "PerPhase", "equation": "Parts * 2", "index_lists": ["Phase"], "unit": "mol"}],
 "inflows": []}""")

model("events", """{"name": "events", "simulation": {"start_time": 0, "end_time": 1000, "output_points": 5, "spacing": "linear",
  "solver": "ndf", "time_unit": "year", "output_mode": "both"},
 "parameters": [{"name": "quake_rate", "value": 0.002, "pdf": {"kind": "logu", "params": {"min": 0.001, "max": 0.01}}},
                {"name": "t0", "value": 100, "pdf": {"kind": "unif", "params": {"min": 50, "max": 150}}}],
 "compartments": [{"name": "A", "initial": "100"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "0.001"}],
 "expressions": [{"name": "Moved", "equation": "B / (A + B)"}],
 "events": [{"name": "E6", "timing": "at", "at": "333", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "0.1"}]}],
 "inflows": []}""")

model("small", """{"name": "small", "simulation": {"start_time": 0, "end_time": 10, "output_points": 5, "spacing": "linear", "solver": "ndf",
  "rtol": 1e-6, "abstol": 1e-9, "time_unit": "year"},
 "parameters": [{"name": "a", "value": 1, "pdf": {"kind": "unif", "params": {"min": 0.5, "max": 1.5}}},
                {"name": "b", "value": 2, "pdf": {"kind": "norm", "params": {"mean": 2, "sd": 0.2}}},
                {"name": "c", "value": 0.3, "pdf": {"kind": "triang", "params": {"min": 0.1, "max": 0.5, "mode": 0.3}, "group": "G"}},
                {"name": "d", "value": 0.4, "pdf": {"kind": "unif", "params": {"min": 0.2, "max": 0.6}, "group": "G"}}],
 "compartments": [{"name": "X", "initial": "a * 10"}, {"name": "Y", "initial": "0"}],
 "transfers": [{"name": "XY", "from": "X", "to": "Y", "rate": "b * c * 0.1"}, {"name": "Lost", "from": "Y", "to": null, "rate": "d * 0.05"}],
 "expressions": [{"name": "Sum", "equation": "X + Y"}],
 "derived": [{"name": "PeakY", "kind": "max", "of": "Y"}, {"name": "Y at 4", "kind": "at_time", "of": "Y", "at": 4}],
 "inflows": []}""")

model("failing", """{"name": "some fail", "simulation": {"start_time": 0, "end_time": 1000, "output_points": 6, "spacing": "linear",
  "solver": "ndf", "time_unit": "year"},
 "parameters": [{"name": "k", "value": 1, "pdf": {"kind": "pg", "values": [1, 0, 2, 0, 3, 4, 0]}},
                {"name": "m", "value": 1, "pdf": {"kind": "unif", "params": {"min": 0.5, "max": 1.5}}}],
 "compartments": [{"name": "A", "initial": "1e3 / k"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "m * 1e-3"}], "expressions": [], "inflows": []}""")

model("zoned", """{"name": "zoned", "simulation": {"start_time": 0, "end_time": 20, "output_points": 5, "spacing": "linear",
  "solver": "ndf", "time_unit": "year"},
 "index_lists": [{"name": "Zone", "indices": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}],
 "parameters": [{"name": "Kd", "value": 0.5, "index_lists": ["Zone"], "pdf": {"kind": "unif", "params": {"min": 0.1, "max": 1}},
                 "entries": [{"index": {"Zone": "a"}, "value": 0.2, "pdf": {"kind": "logu", "params": {"min": 0.01, "max": 1}}}]},
                {"name": "k", "value": 0.1, "pdf": {"kind": "triang", "params": {"min": 0.05, "max": 0.2, "mode": 0.1}}}],
 "compartments": [{"name": "A", "initial": "1", "index_lists": ["Zone"], "unit": "mol"}, {"name": "B", "initial": "0", "index_lists": ["Zone"], "unit": "mol"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "Kd * k", "index_lists": ["Zone"]}],
 "expressions": [{"name": "Share", "equation": "B / (A + B)", "index_lists": ["Zone"], "unit": "unitless"}],
 "derived": [{"name": "Most", "kind": "max", "of": "Share [b]"}],
 "inflows": []}""")

model("scenario sides", """{"name": "scenario sides", "scenario": "Wet",
 "simulation": {"start_time": 0, "end_time": 100, "output_points": 4, "spacing": "linear", "solver": "ndf", "time_unit": "year",
                "output_mode": "both"},
 "index_lists": [{"name": "Weather", "for_scenarios": true, "indices": ["Dry", "Wet", "Storm"]},
                 {"name": "Zone", "indices": [{"name": "a"}, {"name": "b"}]}],
 "parameters": [{"name": "Rain", "value": 1, "index_lists": ["Weather"],
                 "entries": [{"index": {"Weather": "Wet"}, "value": 3}, {"index": {"Weather": "Storm"}, "value": 9}]},
                {"name": "Hit", "value": 50, "index_lists": ["Weather"], "entries": [{"index": {"Weather": "Storm"}, "value": 37}]}],
 "compartments": [{"name": "Soil", "initial": "100", "index_lists": ["Zone"], "unit": "kg"},
                  {"name": "River", "initial": "0", "index_lists": ["Zone"], "unit": "kg"}],
 "transfers": [{"name": "Wash", "from": "Soil", "to": "River", "rate": "Rain * 0.001", "index_lists": ["Zone"]}],
 "expressions": [{"name": "Load", "equation": "River * Rain", "index_lists": ["Zone"], "unit": "kg"}],
 "events": [{"name": "Flood", "timing": "at", "at": "Hit", "actions": [{"kind": "move", "from": "Soil", "to": "River", "fraction": "0.2"}]}],
 "inflows": []}""")

model("no scenarios", """{"name": "no scenarios", "simulation": {"start_time": 0, "end_time": 1, "output_points": 2, "solver": "ndf"},
 "compartments": [{"name": "A", "initial": "1"}], "transfers": [], "expressions": [], "inflows": []}""")

# --- what each case makes -------------------------------------------------------------------------------

const EXAMPLES_DIR = joinpath(@__DIR__, "..", "..", "examples")
const EXAMPLES = sort!([splitext(f)[1] for f in readdir(EXAMPLES_DIR) if endswith(f, ".json")])
const EXAMPLES_RAW = Dict(ex => P(read(joinpath(EXAMPLES_DIR, ex * ".json"), String)) for ex in EXAMPLES)

const RESULTS = Any[]
results(name, where; o...) = push!(RESULTS, J("name" => name, where..., (String(k) => v for (k, v) in o)...))
for ex in EXAMPLES
    results("example $ex", ("example" => ex,))
end
results("biosphere, chosen", ("example" => "biosphere",); which=Any["Dose [I-129]", 4, J("\$output" => 1), "Soil [Tc-99]", 1, true])
results("biosphere, by a label not there", ("example" => "biosphere",); which=Any["Dose [I-129]", "No such series"])
results("biosphere, by a descriptor not there", ("example" => "biosphere",); which=Any[J("label" => "nope", "block" => "x")])
results("biosphere, past the last", ("example" => "biosphere",); which=Any[1000])
results("biosphere, another model's name", ("example" => "biosphere",);
        project=J("name" => "Another", "description" => "Its own words.", "simulation" => J("time_unit" => "s", "solver" => "dp45")),
        index_lists=Any[J("name" => "Mine", "elements" => Any["one", "two"])])
results("biosphere, no lists", ("example" => "biosphere",); index_lists=Any[])
results("biosphere, values from elsewhere", ("example" => "biosphere",); double=true, which=Any[2, 3, 2])
results("biosphere, seconds since the epoch", ("example" => "biosphere",); now=J("epoch" => 1.7e9))
results("waste packages, chosen", ("example" => "waste-packages",); which=Any["Quake", "NearField [Ni-59]", 2])
for (name, _) in MODELS
    name == "no scenarios" && continue
    results("model $name", ("model" => name,))
end
results("two lists, chosen", ("model" => "two lists",); which=Any["Dose [b, I-129]", "PeakTotal", "Kd [a]", 3])

const PROBS = Any[]
prob(name, where, run, trees) = push!(PROBS, J("name" => name, where..., "run" => run, "trees" => trees))
W(want; o...) = J("want" => want, (String(k) => v for (k, v) in o)...)
const WANTS = Any[W("all"), W("mean"), W(1), W(3), W(0), W(1e9), W("2"), W(F(NaN)), W(2.5), W(3.5), W(-7), W("x"),
                  W("all"; inputs=false), W("mean"; inputs=false), W(2; inputs=false)]
prob("small", ("model" => "small",), J("iterations" => 12, "seed" => 3), WANTS)
prob("small, keep two", ("model" => "small",), J("iterations" => 9, "seed" => 5, "keep" => Any["Y", "PeakY"]),
     Any[W("all"), W("mean"), W(4), W("all"; which=Any["b", 1, "PeakY"]), W("mean"; which=Any[J("\$output" => 2), "a"]),
         W("all"; which=Any["nope"]), W(2; which=Any[99])])
prob("small, 150 realisations", ("model" => "small",), J("iterations" => 150, "seed" => 7), Any[W("mean"), W("all"), W(150), W(151)])
prob("small, 300 realisations", ("model" => "small",), J("iterations" => 300, "seed" => 2, "keep" => Any["Sum"]), Any[W("mean"), W(299)])
prob("small, float32", ("model" => "small",), J("iterations" => 10, "seed" => 1, "most_bytes" => 100, "large" => true, "asked_bytes" => 1000000000),
     Any[W("all"), W("mean"), W(5), W("all"; inputs=false)])
prob("small, part of the run", ("model" => "small",), J("iterations" => 20, "seed" => 4, "range" => Any[5, 12]),
     Any[W("all"), W("mean"), W(3), W(100)])
prob("small, a tornado", ("model" => "small",), J("tornado" => true), Any[W("all"), W("mean"), W(3)])
prob("small, a design", ("model" => "small",), J("gsa" => J("method" => "morris", "options" => J("trajectories" => 2, "points" => 4, "levels" => 4)),
                                                 "seed" => 4), Any[W("all"), W("mean")])
prob("small, another model's name", ("model" => "small",), J("iterations" => 6, "seed" => 1),
     Any[W("all"; project=J("name" => "Dict", "nuclides" => Any["Cs-137", "H-3"], "compartments" => Any[J("name" => "Soil"), J("name" => "Lake")],
                           "transfers" => Any[J("name" => "Leach")],
                           "index_lists" => Any[J("name" => "Zone", "indices" => Any["p", "q"])])),
         W("mean"; project_model="two lists"), W(2; index_lists=Any[J("name" => "Own", "elements" => Any["x"])]),
         W("mean"; project=J("name" => "plain"), index_lists=Any[])])
prob("failing", ("model" => "failing",), J("iterations" => 14, "seed" => 8), Any[W("all"), W("mean"), W(2), W(3)])
prob("zoned", ("model" => "zoned",), J("iterations" => 8, "seed" => 6), Any[W("all"), W("mean"), W(5)])
prob("events", ("model" => "events",), J("iterations" => 6, "seed" => 2), Any[W("all"), W("mean")])
prob("biosphere", ("example" => "biosphere",), J("iterations" => 3, "seed" => 1), Any[W("all"), W("mean"), W(2)])

"""A probabilistic result made up by hand, for what a run does not make: a series that cannot
change kept, values that are not numbers, two inputs of one label, no rows."""
const MADE = Any[]
made(name, spec, trees) = push!(MADE, J("name" => name, "prob" => spec, "trees" => trees))
let n = 9, times = 4
    outs = Any[O("Soil [Cs-137]"; nuclide="Cs-137", index=Any["Cs-137"], dims=Any["Radionuclides"]),
               O("Peak"; kind="expression", unit="Bq", timeDependent=false), O("Flux"; kind="expression", unit="Bq/y")]
    vals = Any[gen(n * times, 61; specials=true), gen(n * times, 62), gen(n * times, 63; specials=true)]
    samples = gen(3 * n, 64)
    inputs = Any[J("output" => O("porosity"; kind="parameter", unit="unitless", source="P", timeDependent=false), "k" => 1),
                 J("output" => O("Kd [Cs-137]"; kind="parameter", nuclide="Cs-137", index=Any["Cs-137"], dims=Any["Radionuclides"],
                                 unit="m3/kg", source="P", timeDependent=false), "k" => 3),
                 J("output" => O("Flux"; kind="parameter", source="P", timeDependent=false), "k" => 2),
                 J("output" => O("porosity"; kind="parameter", unit="unitless", source="P", timeDependent=false), "k" => 2)]
    spec = J("t" => f64([0.0, 10.0, 20.0, 30.0]), "outputs" => outs, "values" => vals, "samples" => samples, "inputs" => inputs,
             "ran" => Any[1, 1, 0, 1, 1, 1, 1, 0, 1], "precision" => "double", "model" => "small")
    made("by hand", spec, Any[W("all"), W("mean"), W(3), W(3; inputs=false), W("all"; which=Any["Peak", "Kd [Cs-137]", 6])])
    spec32 = copy(spec)
    spec32["precision"] = "float32"
    made("by hand, float32", spec32, Any[W("all"), W("mean"), W(8)])
    one = J("t" => f64([5.0]), "outputs" => outs[1:2], "values" => Any[gen(200, 71; specials=true), gen(200, 72)], "samples" => gen(200, 73),
            "inputs" => inputs[1:1], "ran" => Any[k % 9 == 0 ? 0 : 1 for k in 1:200], "precision" => "double", "model" => "small")
    made("by hand, one time, 200 rows", one, Any[W("mean"), W("all"), W(200)])
    none = J("t" => f64([0.0, 1.0]), "outputs" => Any[], "values" => Any[], "samples" => gen(0, 1), "inputs" => Any[],
             "ran" => Any[], "precision" => "double", "model" => "small")
    made("by hand, nothing", none, Any[W("all"), W("mean"), W(1)])
    # An input whose descriptor does not say it cannot change: every realisation of it is one
    # value each, which a file of every realisation then takes for a time-major matrix.
    lag = copy(spec)
    lag["inputs"] = Any[J("output" => O("lag"; kind="parameter", unit="year", source="P"), "k" => 2)]
    made("by hand, an input that may change", lag, Any[W("all"), W("mean"), W(4)])
end

const SCENARIOS = Any[]
scenarios(name, where; o...) = push!(SCENARIOS, J("name" => name, where..., (String(k) => v for (k, v) in o)...))
scenarios("example scenarios", ("example" => "scenarios",))
scenarios("example scenarios, the second read against", ("example" => "scenarios",); active="Warmer and wetter")
scenarios("example scenarios, chosen", ("example" => "scenarios",); which=Any["Lake", 1, "Dose"], active="Drier")
scenarios("example scenarios, two of them", ("example" => "scenarios",); names=Any["Drier", "Present"])
scenarios("example scenarios, one", ("example" => "scenarios",); names=Any["Drier"])
scenarios("example scenarios, another model's name", ("example" => "scenarios",); project=J("name" => "Given"),
          index_lists=Any[J("name" => "L", "elements" => Any["x"])])
scenarios("example scenarios, one not run", ("example" => "scenarios",); active="Nowhere")
scenarios("scenario sides", ("model" => "scenario sides",))
scenarios("scenario sides, stormy", ("model" => "scenario sides",); active="Storm", which=Any["Load [a]", "Soil [b]", "Flood"])
scenarios("scenario sides, two threads", ("model" => "scenario sides",); threads=2)
scenarios("no scenarios", ("model" => "no scenarios",))
scenarios("biosphere, as scenarios", ("example" => "biosphere",); names=Any["x", "y"])

const SAVES = Any[]
saves(name, where; o...) = push!(SAVES, J("name" => name, where..., (String(k) => v for (k, v) in o)...))
saves("biosphere", ("example" => "biosphere",); path="out.h5")
saves("biosphere, two blocks from a time", ("example" => "biosphere",); path="Out.HDF5", blocks=Any["Soil", "Dose"], time_origin=100)
saves("biosphere, the table of two blocks", ("example" => "biosphere",); path="out.csv", blocks=Any["Soil", "Dose"], time_origin=-2.5)
saves("biosphere, the table of some", ("example" => "biosphere",); path="out.csv", which=Any["Dose [I-129]", 3])
saves("biosphere, the whole table", ("example" => "biosphere",); path="out.csv")
saves("biosphere, a block not there", ("example" => "biosphere",); path="out.h5", blocks=Any["Nowhere"])
saves("biosphere, blocks and series", ("example" => "biosphere",); path="out.h5", blocks=Any["Soil"], which=Any[1])
saves("biosphere, an archive from a time", ("example" => "biosphere",); path="out.zip", time_origin=1)
saves("biosphere, a table with a name", ("example" => "biosphere",); path="out.csv", project=J("name" => "x"))
saves("biosphere, an ending not known", ("example" => "biosphere",); path="out.txt")
saves("two lists, he5", ("model" => "two lists",); path="x.he5", which=Any["Dose [a, Cs-137]"], time_origin=0.5)
saves("small, every realisation from a time", ("model" => "small",); path="prob.h5", probabilistic=J("iterations" => 7, "seed" => 2), want="all", time_origin=3)
saves("small, the mean", ("model" => "small",); path="prob.H5", probabilistic=J("iterations" => 7, "seed" => 2), want="mean")

# --- through the JSON both sides read -------------------------------------------------------------------

models_json = K.JDict(name => m for (name, m) in MODELS)
back = K.parse_json(K.json_text(J("trees" => TREES, "lookup3" => LOOKUPS, "utf8" => UTF8, "result_trees" => RESULT_TREES,
                                  "models" => models_json, "results" => RESULTS, "probabilistic" => PROBS, "made" => MADE,
                                  "scenarios" => SCENARIOS, "saves" => SAVES); indent=0))
trees_, lookups_, utf8_, rts_ = back["trees"], back["lookup3"], back["utf8"], back["result_trees"]
models_, results_, probs_, made_, scenarios_, saves_ = back["models"], back["results"], back["probabilistic"], back["made"],
                                                      back["scenarios"], back["saves"]
model_of(c) = haskey(c, "example") ? EXAMPLES_RAW[c["example"]] : models_[c["model"]]

function run_res(model)
    p = K.Project(model)
    sys = K.build_system(p)
    return K.run_project(p; system=sys)
end

which_of(w, outs) = w === nothing ? nothing : Any[x isa AbstractDict && haskey(x, "\$output") ? outs[x["\$output"]] : dec(x) for x in w]

for c in trees_
    c["out"] = answer("tree $(c["name"])", said(() -> build_tree(c)))
end
for c in lookups_
    data = pattern(c["n"], c["seed"])
    c["out"] = Int(haskey(c, "start") ? K.lookup3(data, c["start"] + 1, c["len"]) : K.lookup3(data))
end
utf8_ = Any[utf8_case(hex) for hex in utf8_]

for c in rts_
    function build()
        outs = dec(c["outputs"])
        cols = [dec(col) for col in c["columns"]]
        realisations = nothing
        if c["realisations"] !== nothing
            r = c["realisations"]
            mats = Dict{Int,Any}(Int(p[1]) => dec(p[2]) for p in r["matrices"])
            realisations = K.JDict("matrix_for" => (i -> get(mats, i, nothing)))
            haskey(r, "iterations") && (realisations["iterations"] = dec(r["iterations"]))
        end
        sample = c["sample"] === nothing ? nothing : dec(c["sample"])
        tree = K.result_tree(; t=dec(c["t"]), outputs=outs, column=i -> cols[i], which=Int[w for w in c["which"]],
                             project=dec(c["project"]), index_lists=dec(c["index_lists"]), now=stamp(c["now"]), realisations, sample)
        return K.write_hdf5(tree)
    end
    c["out"] = answer("result tree $(c["name"])", said(build))
end

for c in results_
    function build()
        res = run_res(model_of(c))
        outs = K.outputs(res)
        column = get(c, "double", false) == true ? (i -> 2 .* K.series(res, outs[i])) : nothing
        return K.write_results_hdf5(res, nothing, which_of(get(c, "which", nothing), outs); now=stamp(get(c, "now", NOW)),
                                    project=dec(get(c, "project", nothing)), index_lists=dec(get(c, "index_lists", nothing)), column)
    end
    c["out"] = answer("results $(c["name"])", said(build))
end

function run_prob(model, o)
    kw = (seed=get(o, "seed", 1), latin=get(o, "latin", true), threads=1,
          keep=haskey(o, "keep") ? String[string(v) for v in o["keep"]] : nothing,
          range=haskey(o, "range") ? (o["range"][1], o["range"][2]) : nothing, tornado=get(o, "tornado", nothing),
          gsa=get(o, "gsa", nothing), most_bytes=get(o, "most_bytes", K.PROB_MOST_BYTES), large=get(o, "large", false),
          asked_bytes=get(o, "asked_bytes", K.PROB_MOST_BYTES_ASKED))
    iterations = haskey(o, "iterations") ? Float64(o["iterations"]) : nothing
    return K.run_probabilistic(K.Project(model), iterations; kw...)
end

function prob_tree(prob, t)
    outputs = vcat(Any[o for o in prob.outputs],
                   Any[i["output"] for i in prob.inputs if !(get(i["output"], "label", nothing) in Set(get(o, "label", nothing) for o in prob.outputs))])
    which = which_of(get(t, "which", nothing), outputs)
    project = haskey(t, "project_model") ? K.Project(models_[t["project_model"]]) : dec(get(t, "project", nothing))
    tree = K.probabilistic_tree(prob, dec(t["want"]); which, project, index_lists=dec(get(t, "index_lists", nothing)),
                                now=stamp(get(t, "now", NOW)), inputs=get(t, "inputs", true))
    return K.write_hdf5(tree)
end

for c in probs_
    local p
    refused = said(() -> (p = run_prob(model_of(c), c["run"]); UInt8[]))
    for t in c["trees"]
        t["out"] = answer("probabilistic $(c["name"]) $(K.json_text(t; indent=0))", refused isa String ? refused : said(() -> prob_tree(p, t)))
    end
end

"""A made-up probabilistic result as the Julia package holds one."""
function made_prob(spec)
    t = dec(spec["t"])
    times = length(t)
    outs = K.JDict[o for o in spec["outputs"]]
    ran = UInt8[r for r in spec["ran"]]
    n = length(ran)
    T = spec["precision"] == "float32" ? Float32 : Float64
    values = Matrix{T}[permutedims(reshape(T.(dec(v)), times, n)) for v in spec["values"]]
    flat = dec(spec["samples"])
    inputs = K.JDict[i for i in spec["inputs"]]
    rows = isempty(flat) ? 0 : length(flat) ÷ n
    samples = reshape(flat, rows, n)
    project = K.Project(models_[spec["model"]])
    return K.ProbabilisticResults{T}(t, outs, values, samples, K.JDict[], String[], inputs, ran, n, 1:n, spec["precision"],
                                     K.OrderedDict{String,Any}(), project, nothing)
end

for c in made_
    p = made_prob(c["prob"])
    for t in c["trees"]
        t["out"] = answer("made $(c["name"]) $(K.json_text(t; indent=0))", said(() -> prob_tree(p, t)))
    end
end

for c in scenarios_
    function build()
        raw = model_of(c)
        names = haskey(c, "names") ? String[n for n in c["names"]] : collect(String, K.Project(raw).scenarios)
        isempty(names) && throw(ArgumentError("This model has no scenarios: an index list marked as the scenario list, with indices."))
        # As `run_scenarios(m; split="off")` runs them: each whole, whatever auto has learnt.
        model = K.jcopy(raw)
        sim = get(model, "simulation", nothing)
        sim isa AbstractDict || (sim = K.JDict(); model["simulation"] = sim)
        sim["split"] = "off"
        runs = K.OrderedDict{String,Any}()
        for name in names
            r = copy(model)
            r["scenario"] = name
            runs[name] = K.run_project(K.Project(r))
        end
        outs = K.outputs(first(values(runs)))
        return K.write_scenarios_hdf5(runs, nothing, which_of(get(c, "which", nothing), outs); active=get(c, "active", nothing),
                                      project=dec(get(c, "project", nothing)), index_lists=dec(get(c, "index_lists", nothing)),
                                      now=stamp(NOW))
    end
    c["out"] = answer("scenarios $(c["name"])", said(build))
end

const SAVE_DIR = mktempdir()
for (k, c) in enumerate(saves_)
    function build()
        path = joinpath(SAVE_DIR, "$k-" * c["path"])
        if haskey(c, "probabilistic")
            p = run_prob(model_of(c), c["probabilistic"])
            K.save(p, path; want=c["want"], time_origin=get(c, "time_origin", 0.0), now=stamp(NOW))
        else
            res = run_res(model_of(c))
            kw = Dict{Symbol,Any}()
            haskey(c, "blocks") && (kw[:blocks] = String[b for b in c["blocks"]])
            haskey(c, "which") && (kw[:outputs] = which_of(c["which"], K.outputs(res)))
            haskey(c, "time_origin") && (kw[:time_origin] = c["time_origin"])
            haskey(c, "project") && (kw[:project] = dec(c["project"]))
            endswith(lowercase(c["path"]), ".csv") || endswith(lowercase(c["path"]), ".zip") || (kw[:now] = stamp(NOW))
            K.save(res, path; kw...)
        end
        return read(path)
    end
    # The folder the files went to is not part of a refusal's words.
    got = said(build)
    got isa String && (got = replace(got, joinpath(SAVE_DIR, "$k-") => ""))
    c["out"] = answer("save $(c["name"])", got)
end
rm(SAVE_DIR; recursive=true)

isempty(DUMPS) || write(joinpath(DUMPS, "hdf5.julia.txt"), join(TABLE, "\n"))
path = joinpath(@__DIR__, "..", "tests", "fixtures", "hdf5.json")
write(path, K.json_text(J("now" => NOW, "trees" => trees_, "lookup3" => lookups_, "utf8" => utf8_, "result_trees" => rts_, "models" => models_,
                          "results" => results_, "probabilistic" => probs_, "made" => made_, "scenarios" => scenarios_, "saves" => saves_); indent=0))
refusals = count(l -> occursin(" error:", l), TABLE)
println(path, ": ", COUNT[], " files and refusals (", refusals, " refused), ", length(lookups_), " lookup3 checks, ", length(utf8_), " strings")
