# Writes tests/fixtures/stats.json: what the Julia package's statistics -- the
# normal distribution, the distributions and their draws, the named streams and
# the columns of uniforms, the correlations and Iman-Conover, every method's
# sensitivity design -- make of inputs written here, for the C++ engine's tests to
# compare with (tests/test_stats.cpp).
#
#     julia --project=. ../cpp/tools/stats_fixtures.jl        (from ../julia)
#
# Each case is a function and its arguments, as JSON: numbers that must arrive to
# the bit are written as `"f:<the double's 16 hex digits>"`, and `{"$undefined":
# true}` is JavaScript's `undefined` (a key that is not there). The case list is
# written as JSON and read back before anything runs, so that both engines start
# from the very values the file holds. What a case gives is written as text --
# doubles as their bits, errors as `error:<Julia's type>`, an `ArgumentError`
# with its words -- and kept as it is when short, else as an FNV-1a hash. With
# KOMPARTMENT_FIXTURE_DUMPS set every text is written there
# (`stats.julia.txt`, a case a line).

using Kompartment
const K = Kompartment
K.set_parity!(true)

bits(x::Float64) = isnan(x) ? "nan" : string(reinterpret(UInt64, x); base=16, pad=16)
bits(x::Real) = bits(Float64(x))
function fnv(text::String)
    h = 0xcbf29ce484222325
    for b in codeunits(text)
        h = (h ⊻ b) * 0x100000001b3
    end
    return string(h; base=16, pad=16)
end
kept(text::String) = ncodeunits(text) <= 300 ? "=" * text : "#" * fnv(text)
nums(v) = join((bits(Float64(x)) for x in v), ",")

"""A double for the file: its bits, so that it arrives as it is."""
F(x::Real) = "f:" * string(reinterpret(UInt64, Float64(x)); base=16, pad=16)
unF(s::AbstractString) = reinterpret(Float64, parse(UInt64, s[3:end]; base=16))
unF(v::AbstractVector) = Float64[unF(s) for s in v]
const UNDEFINED = K.JDict("\$undefined" => true)
"""An argument as the functions take it: `undefined`, or the JSON value."""
val(v) = v isa AbstractDict && haskey(v, "\$undefined") ? K._PD_MISSING : v

"""What an error is, as both engines say it."""
function said(f)
    try
        return f()
    catch e
        e isa ArgumentError && return "error:ArgumentError:" * e.msg
        for T in (MethodError, InexactError, TypeError, BoundsError, OutOfMemoryError, DomainError, DivideError, KeyError)
            e isa T && return "error:" * string(nameof(T))
        end
        rethrow()
    end
end

"""A value as both engines write it: its type and its value, every double by its bits."""
function tdump(v)
    v === nothing && return "null"
    v isa Bool && return v ? "true" : "false"
    v isa Integer && return "i" * string(v)
    v isa AbstractFloat && return "f" * bits(Float64(v))
    v isa AbstractString && return "s(" * String(v) * ")"
    v isa AbstractMatrix && return "[" * join(("[" * join((tdump(v[r, c]) for c in axes(v, 2)), ",") * "]" for r in axes(v, 1)), ",") * "]"
    (v isa AbstractVector || v isa Tuple) && return "[" * join((tdump(x) for x in v), ",") * "]"
    v isa AbstractDict && return "{" * join((string(k) * "=" * tdump(x) for (k, x) in v), ";") * "}"
    error("cannot dump $(typeof(v))")
end

# Numbers from a fixed generator, written into the file, for what is drawn away from the special values.
let state = UInt64(88172645463325252)
    global function rnd()
        state ⊻= state << 13
        state ⊻= state >> 7
        state ⊻= state << 17
        return (state >> 11) * 2.0^-53
    end
end

# --- the grids the distributions are read at ------------------------------------------------------

const US = Float64[0.0, -0.0, 1.0, NaN, Inf, -Inf, 0.5, 0.25, 0.75, 0.1, 0.9, 1e-12, 1e-13, 5e-13, 1 - 1e-12,
                   0.999999999999, prevfloat(1.0), nextfloat(0.0), 1e-300, -0.5, 1.5, 0.02425, 0.97575, 1 / 3,
                   0.05, 0.95, 2.0, -1e-300]
append!(US, [rnd() for _ in 1:14])
const XS = Float64[-Inf, -1e300, -1.0, -0.0, 0.0, 5e-324, 1e-10, 1e-6, 1e-4, 0.001, 0.01, 0.1, 0.5, 1.0, 1.5, 2.0, 2.5,
                   3.0, 3.5, 4.0, 5.0, 7.0, 9.999, 10.0, 12.0, 100.0, 1e3, 1e5, 1e10, 1e300, Inf, NaN]
append!(XS, [10.0^(8 * rnd() - 4) for _ in 1:10])
# (Written and read back, as the cases are.)
const XJ = K.parse_json(K.json_text(Any["0.5", " 2 ", "1e-3", "Infinity", "-Infinity", "0x10", "abc", "", nothing, true, false,
                                        Any[0.5], Any["2"], Any[1, 2], K.JDict(), K.JDict("a" => 1), 3, "1e400", UNDEFINED]; indent=0))

# --- the cases ----------------------------------------------------------------------------------------

cases = Any[]
case(fn, args...) = push!(cases, K.JDict("fn" => fn, "args" => Any[args...]))
J(pairs...) = K.JDict(String(k) => v for (k, v) in pairs)
spec(kind, params; kw...) = J("kind" => kind, "params" => params, kw...)

# JavaScript's rules: truthiness, String(), Number(), ToUint32, Python's float(), probit of a value.
JS_VALUES = Any[UNDEFINED, nothing, true, false, 0, 1, -7, 0.0, -0.0, 1.5, -2.5, 1e21, 1.5e-7, 123456789012, 9007199254740993,
                "", " ", "0", "-0", "+5", "5.", ".5", "+.5e-3", "1e", "e5", "1e400", "-1e400", "1e-400", "2e-324", "4e-324",
                "0x10", "0X1f", "0o17", "0b101", "-0x10", "0x", "0xg", "Infinity", "+Infinity", "-Infinity", "infinity",
                "inf", "-inf", "NaN", "nan", "abc", "12abc", " \t\n 42 \u00a0", "\u2028 7 \ufeff", "\u0085 7", "\u1680 8 \u3000",
                "1_000", "1__0", "_1", "0x1p-2", "1d5", "\uff11\uff12", "\u0130nf", "-\u0131nf",
                Any[], Any[5], Any["5"], Any[1, 2], Any[nothing], Any[nothing, nothing], Any[Any[1, 2], 3], Any[true],
                K.JDict(), K.JDict("a" => 1), "\$", "a\u00e9b", "\u65e5\u672c", "\U0001f600", 4294967296, 4294967297, -4294967297, 2147483648,
                1.0e300, 4.294967296e9, 0.9999, -0.9999, "4294967295.9", "-1.5"]
for v in JS_VALUES
    case("jsrules", v)
end

# Named streams: seeds the code accepts, odd ones, and names in every alphabet.
SEEDS = Any[1, 0, -1, 2, 42, 4294967295, 4294967296, 4294967301, -4294967303, 1.5, -1.5, 2.9999, 1e300, -1e300,
            "42", " 42 ", "0x10", "abc", "", nothing, true, false, Any[7], Any[1, 2], K.JDict(), "1e400", 9007199254740993,
            1.0e16, -0.0]
NAMES = Any["", "a", "Kd[Tc-99]", "Q@500", "correlation:Kd[I-129]", "Quake#occurrences#0", "\u00c4rta", "\u65e5\u672c\u8a9e",
            "\U0001f600emoji", "\u2028", "a\u0000b", nothing, UNDEFINED, 5, 1.5, true, Any[1, "a"], K.JDict(), "\u0394#sobol#A#0"]
for s in SEEDS, n in NAMES[1:3]
    case("stream", s, n)
end
for n in NAMES, s in (1, 7)
    case("stream", s, n)
end
for n in NAMES
    n isa AbstractString && case("fnv", n)
end
for s in (1, 7, "x"), (name, n) in (("a", 0), ("a", 1), ("a", 2), ("b", 3), ("Kd[I-129]", 4), ("c", 7), ("d", 10), ("e", 64), ("f", 1000),
                                     ("g", -1), ("h", -5)), latin in (true, false)
    case("uniforms", s, name, n, latin)
end
for n in (-3, 0, 1, 5)
    case("take", 9, "t", n)
end

# The normal distribution.
ZS = Float64[-40, -38.5, -10, -5, -3, -2.5, -1, -0.5, -1e-10, -0.0, 0.0, 1e-20, 0.3, 0.5, 0.84, 1, 2, 3, 5, 8.3, 10, 37,
             40, Inf, -Inf, NaN]
PS = Float64[0, 1, -0.1, 1.1, NaN, Inf, -Inf, 5e-324, 1e-300, 1e-10, 0.001, 0.02, 0.02425, nextfloat(0.02425),
             prevfloat(0.02425), 0.025, 0.5, 0.97575, nextfloat(0.97575), prevfloat(0.97575), 0.99, 0.999999, prevfloat(1.0)]
for x in vcat(ZS, PS, [6 * rnd() - 3 for _ in 1:20], [rnd() for _ in 1:20])
    case("normal", F(x))
end

# Every kind of distribution: as written, with bad and missing parameters, truncated by value and
# by percentile, lists read in order and not, with words, Booleans and gaps.
SPECS = Any[
    spec("unif", J("min" => 1, "max" => 3)),
    spec("unif", J("min" => 5, "max" => 5)),
    spec("unif", J("min" => 3, "max" => 1)),
    spec("unif", J("min" => "1", "max" => " 3 ")),
    spec("unif", J("min" => "0x10", "max" => "0b11111")),
    spec("unif", J("min" => "1e-3", "max" => "Infinity")),
    spec("unif", J("min" => "abc", "max" => 2)),
    spec("unif", J("min" => nothing, "max" => 3)),
    spec("unif", J("min" => 1)),
    spec("unif", J("min" => true, "max" => Any[4])),
    spec("unif", "abc"),
    spec("unif", Any[1, 2]),
    spec("unif", nothing),
    J("kind" => "unif"),
    spec("triang", J("min" => 0, "max" => 10, "mode" => 3)),
    spec("triang", J("min" => 0, "max" => 10, "mode" => 0)),
    spec("triang", J("min" => 0, "max" => 10, "mode" => 10)),
    spec("triang", J("min" => 0, "max" => 10, "mode" => 12)),
    spec("triang", J("min" => 2, "max" => 2, "mode" => 2)),
    spec("dtriang", J("min" => 1, "max" => 4, "mode" => 2)),
    spec("dtriang", J("min" => 1, "max" => 4, "mode" => 4)),
    spec("norm", J("mean" => 5, "sd" => 2)),
    spec("norm", J("mean" => 5, "sd" => 0)),
    spec("norm", J("mean" => 5, "sd" => -1)),
    spec("norm", J("mean" => -1e300, "sd" => 1e300)),
    spec("logu", J("min" => 1e-3, "max" => 1e2)),
    spec("logu", J("min" => 0, "max" => 1)),
    spec("logu", J("min" => -1, "max" => 1)),
    spec("logt", J("min" => 1e-6, "max" => 1e-2, "mode" => 1e-4)),
    spec("logt", J("min" => 1.0000000000000002e-6, "max" => 0.0001, "mode" => 1e-5)),
    spec("logt", J("min" => 7e-12, "max" => 5e-11, "mode" => 5e-11)),
    spec("logdt", J("min" => 0.1, "max" => 100, "mode" => 1)),
    spec("logdt", J("min" => 0.1, "max" => 100, "mode" => 0.1)),
    spec("Logn4", J("gm" => 2, "gsd" => 1.5)),
    spec("Logn4", J("gm" => 2, "gsd" => 1)),
    spec("Logn4", J("gm" => -1, "gsd" => 2)),
    spec("logn", J("mean" => 3, "sd" => 1)),
    spec("logn", J("mean" => 0, "sd" => 1)),
    spec("logn", J("mean" => 1e-3, "sd" => 5e-3)),
    spec("logn5", J("p1" => 0.05, "x1" => 1, "p2" => 0.95, "x2" => 10)),
    spec("logn5", J("p1" => 0.5, "x1" => 1, "p2" => 0.5, "x2" => 10)),
    spec("logn5", J("p1" => "0.05", "x1" => "1", "p2" => " 0.95 ", "x2" => 10)),
    spec("logn5", J("p1" => 0, "x1" => 1, "p2" => 0.95, "x2" => 10)),
    spec("logn5", J("p1" => 0.05, "x1" => 10, "p2" => 0.95, "x2" => 1)),
    spec("logn5", J("p1" => "abc", "x1" => 1, "p2" => 0.95, "x2" => 10)),
    spec("logn5", J("p1" => nothing, "x1" => 1, "p2" => 0.95, "x2" => 10)),
    spec("logn5", J("p1" => true, "x1" => 1, "p2" => 0.95, "x2" => 10)),
    spec("logn5", J("p1" => "0x0.1p0", "x1" => 1, "p2" => "inf", "x2" => 10)),
    spec("logn5", J("p1" => 0.05, "x1" => 1, "x2" => 10)),
    spec("logn5", J("p1" => 0.1, "x1" => 1, "p2" => 0.9, "x2" => 10, "extra" => 1)),
    # truncated by value and by percentile
    spec("norm", J("mean" => 5, "sd" => 2); trmin=3, trmax=7),
    spec("norm", J("mean" => 5, "sd" => 2); trmin="3", trmax=nothing),
    spec("norm", J("mean" => 5, "sd" => 2); trmin=9, trmax=2),
    spec("norm", J("mean" => 5, "sd" => 2); pmin=0.1, pmax=0.9),
    spec("norm", J("mean" => 5, "sd" => 2); pmin=0.9, pmax=0.1),
    spec("norm", J("mean" => 5, "sd" => 2); pmin=-0.5, pmax=1.5),
    spec("norm", J("mean" => 5, "sd" => 2); trmin=4, pmin=0.2, trmax=8, pmax=0.7),
    spec("norm", J("mean" => 5, "sd" => 2); trmin="abc"),
    spec("norm", J("mean" => 5, "sd" => 2); trmin="1e400"),
    spec("logt", J("min" => 1e-6, "max" => 1e-2, "mode" => 1e-4); trmax=1e-3),
    spec("logt", J("min" => 1e-6, "max" => 1e-2, "mode" => 1e-4); trmin=1e-5, trmax=1e-5),
    spec("triang", J("min" => 0, "max" => 10, "mode" => 3); trmin=12),
    spec("triang", J("min" => 0, "max" => 10, "mode" => 3); trmin=6.5, trmax=0.0),
    spec("unif", J("min" => 0, "max" => 1); trmin=0.5, trmax=0.5),
    spec("unif", J("min" => 0, "max" => 1); pmin=0.25, pmax=0.25),
    spec("logu", J("min" => 1e-3, "max" => 1e2); trmin=0.01, pmax=0.5),
    spec("Logn4", J("gm" => 2, "gsd" => 1.5); trmin=1, trmax=3),
    spec("logn", J("mean" => 3, "sd" => 1); pmin=0.05),
    spec("logn5", J("p1" => 0.05, "x1" => 1, "p2" => 0.95, "x2" => 10); trmax=5, pmin=0.2),
    spec("dtriang", J("min" => 1, "max" => 4, "mode" => 2); trmin=1.5, trmax=3.5),
    spec("logdt", J("min" => 0.1, "max" => 100, "mode" => 1); pmin=nothing, pmax="0.5"),
    # lists
    J("kind" => "pg", "values" => Any[1, 2, 3]),
    J("kind" => "pg", "values" => Any[1, "a", true, nothing, Any[2], K.JDict("x" => 1), 2.5, -0.0, 7]),
    J("kind" => "pg", "values" => Any[1, "a", true, nothing, 2.5, 7], "inorder" => false),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "inorder" => "false"),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "inorder" => 0),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "inorder" => true, "pos" => 2),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "pos" => -1),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "pos" => 1.5),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "pos" => "2"),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "pos" => "abc"),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "pos" => true),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "pos" => Any[3]),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "pos" => K.JDict()),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "pos" => nothing),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "pos" => "1e40"),
    J("kind" => "pg", "values" => Any[10, 20, 30, 40], "pos" => 1e300),
    J("kind" => "pg", "values" => Any[]),
    J("kind" => "pg", "values" => "1,2"),
    J("kind" => "pg", "values" => 5),
    J("kind" => "pg", "values" => nothing),
    J("kind" => "pg"),
    J("kind" => "pg", "values" => Any[0.5], "inorder" => false),
    # not a kind, not a distribution
    J("kind" => "beta", "params" => J("a" => 1)),
    J("kind" => nothing, "params" => J("min" => 1, "max" => 2)),
    J("kind" => 5),
    J("params" => J("min" => 1, "max" => 2)),
    nothing, "abc", 5, Any[], K.JDict(), true, false, 0,
]
for s in SPECS
    case("spec", s)
end
# A list read out of order at numbers far below zero: Julia's `Int` of the index fails there.
case("vap", J("kind" => "pg", "values" => Any[1, 2], "inorder" => false), F(-1e300), 0)
case("vap", J("kind" => "pg", "values" => Any[1, 2], "inorder" => false), F(-1e18), 0)
case("vap", J("kind" => "pg", "values" => Any[1, 2], "inorder" => false), F(-5e18), 0)
case("vap", J("kind" => "pg", "values" => Any[1, 2, 3], "inorder" => false), F(-4e18), 0)
case("vap", J("kind" => "pg", "values" => Any[1, 2], "inorder" => false), F(-0.0), 0)

# Correlations: pairs and groups, every problem, the settings in every form a file holds.
NAMES5 = Any["Kd[I-129]", "Kd[Cs-135]", "Kd[Tc-99]", "k", "Q@500", "Kd", "Kd[I-129]x"]
corrs = Any[
    Any[J("a" => "Kd[I-129]", "b" => "Kd[Cs-135]", "r" => 0.8)],
    Any[J("group" => "Kd", "r" => 0.9)],
    Any[J("group" => "Kd", "r" => 0.9), J("a" => "Kd[I-129]", "b" => "Kd[Tc-99]", "r" => -0.5)],
    Any[J("a" => "k", "b" => "k", "r" => 0.3), J("a" => "k", "b" => "Q@500", "r" => 1.5), J("a" => "k", "b" => "nope", "r" => 0.2),
        J("a" => "nope", "b" => "neither", "r" => 0.2), J("b" => "k", "r" => 0.1), J("r" => 0.1), J("a" => "", "b" => "k", "r" => 0.1),
        J("a" => "k", "b" => "Q@500", "r" => "0.4"), J("a" => "Q@500", "b" => "k", "r" => 0.6), J("a" => "k", "b" => "Q@500")],
    Any[J("group" => "Q", "r" => 0.5), J("group" => "Kd[I", "r" => 0.5), J("group" => "k", "r" => 0.5), J("group" => "", "r" => 0.5),
        J("group" => 0, "r" => 0.5), J("group" => "Kd", "r" => -1), J("group" => "Kd", "r" => 1), J("group" => true, "r" => 0.2),
        J("group" => nothing, "a" => "k", "b" => "Kd", "r" => 0.2), J("group" => "Kd", "r" => nothing), J("group" => "Kd", "r" => "x")],
    Any[J("a" => 5, "b" => true, "r" => 0.1), J("a" => Any["k"], "b" => K.JDict(), "r" => 0.1), J("a" => "undefined", "b" => "k", "r" => 0.1),
        5, "text", nothing, Any[1, 2]],
    K.JDict("x" => 1, "y" => 2),
    "abc",
    "\u65e5\u672c",
    7,
    true,
    false,
    nothing,
    Any[],
]
for c in corrs
    case("pairs", J("simulation" => J("correlations" => c)), NAMES5)
    case("pairs", J("\$project" => J("simulation" => J("correlations" => c))), NAMES5)
end
case("pairs", J("simulation" => nothing), NAMES5)
case("pairs", J("other" => 1), NAMES5)
case("pairs", 5, NAMES5)
case("pairs", J("simulation" => J("correlations" => Any[J("a" => "x", "b" => "y", "r" => 0.5)])), Any["x", "y", "x"])
case("pairs", J("simulation" => J("correlations" => Any[J("group" => "g", "r" => 0.5)])), Any["g[a]", "g[b]", "g[c]", "g"])

# Iman-Conover on made-up columns: consistent and inconsistent targets, ties, zeros and NaN, and a
# name the stream cannot find.
function columns(n, k)
    return Any[Any[F(10 * rnd() - 3) for _ in 1:n] for _ in 1:k]
end
for (n, k, pairs) in ((2, 2, [(0, 1, 0.8)]), (3, 2, [(0, 1, 0.8)]), (10, 2, [(0, 1, 0.8)]), (25, 3, [(0, 1, 0.9), (1, 2, -0.7)]),
                      (40, 4, [(0, 1, 0.9), (0, 2, 0.9), (1, 2, -0.9)]), (60, 5, [(0, 4, 0.5), (1, 3, -0.2), (2, 4, 0.99)]),
                      (30, 3, [(0, 1, 1.0), (1, 2, 1.0), (0, 2, -1.0)]), (12, 3, Tuple{Int,Int,Float64}[]),
                      (50, 6, [(0, 1, 0.3), (2, 5, 0.6), (3, 4, -0.95), (0, 5, 0.1), (1, 5, 0.97), (0, 2, -0.4)]))
    cols = columns(n, k)
    case("iman", cols, Any[Any[a, b, F(r)] for (a, b, r) in pairs], Any["c$j" for j in 1:k], 21)
end
let cols = columns(20, 3)
    # ties, both zeros, NaN and infinities in a column
    cols[1][1:6] = Any[F(0.0), F(-0.0), F(0.0), F(-0.0), F(NaN), F(Inf)]
    cols[2][1:4] = Any[F(1.0), F(1.0), F(1.0), F(-Inf)]
    case("iman", cols, Any[Any[0, 1, F(0.7)], Any[1, 2, F(0.4)]], Any["a", "b", "c"], 3)
    case("iman", cols, Any[Any[0, 2, F(0.7)]], Any["a"], "seed text")
end

# The global sensitivity methods: settings, runs, refusals.
METHODS = Any["morris", "sobol", "efast", "rbdfast", "ff", "dgsm", "radial", "shapley", "nope", nothing, 5]
GIVEN = Any[UNDEFINED, nothing, K.JDict(), "text", 7,
            J("design" => "trajectories", "trajectories" => "4", "points" => 2.6, "levels" => -3, "candidates" => 2, "relative" => 1,
              "resamples" => "", "samples" => 1e16, "second" => "yes", "blocks" => 9.5e15, "estimator" => "sobol2007",
              "harmonics" => 1.4, "low" => "0.1", "high" => 0.2, "pairs" => 0, "step" => -0.1, "crossed" => K.JDict(),
              "perms" => -2, "nVar" => 1e15, "nOuter" => "abc", "nInner" => true),
            J("design" => "walks", "trajectories" => nothing, "points" => "x", "levels" => 2, "samples" => 7, "second" => false,
              "blocks" => 2, "estimator" => "nope", "harmonics" => 3, "low" => 0, "high" => 1, "step" => 0.5, "perms" => 0,
              "nVar" => 2, "nOuter" => 1, "nInner" => 2),
            J("design" => "trajectories", "trajectories" => 3, "candidates" => 5, "samples" => 16, "blocks" => 17, "harmonics" => 4,
              "low" => 0.3, "high" => 0.3, "step" => 1e-6, "perms" => 5, "nVar" => 1.5, "nOuter" => 0.5, "nInner" => 1),
            J("samples" => "1e400"),
            J("trajectories" => 1e16, "points" => 9e15, "samples" => 8.999999999999999e15, "harmonics" => 2, "nVar" => -1e16),
            J("samples" => Any[12], "harmonics" => Any["2"], "perms" => Any[], "points" => -0.5, "levels" => 2.5),
            # Past what a double counts one by one: a setting, or the runs the settings make.
            J("harmonics" => 5e7, "trajectories" => 1e8, "points" => 1e8, "samples" => 2.25e15, "perms" => 1e16, "resamples" => 9e15),
            J("harmonics" => 1.5e9, "design" => "trajectories", "candidates" => -1e16, "samples" => 2249999999999999, "blocks" => 4)]
for m in METHODS, Kn in (0, 1, 2, 3, 5, 9), g in GIVEN
    case("gsa", m, Kn, g)
end

# Every method's design, for several numbers of inputs and settings, and its refusals.
KEYS = Any["a", "Kd[I-129]", "c", "\u0394", "e"]
DESIGNS = Any[
    ("morris", nothing), ("morris", J("trajectories" => 3, "points" => 4, "levels" => 6)),
    ("morris", J("design" => "trajectories", "trajectories" => 3, "levels" => 4)),
    ("morris", J("design" => "trajectories", "trajectories" => 3, "levels" => 5, "candidates" => 8)),
    ("morris", J("design" => "trajectories", "trajectories" => 1, "candidates" => 4)),
    ("morris", J("design" => "trajectories", "trajectories" => 2, "levels" => 1e16)),
    ("morris", J("trajectories" => 2, "points" => 3, "levels" => 3e9)),
    ("morris", J("trajectories" => 1e16)),
    ("morris", J("trajectories" => 2, "candidates" => 1)),
    ("radial", J("samples" => 6)), ("radial", J("samples" => 1)), ("radial", J("samples" => 1e16)),
    ("sobol", J("samples" => 8)), ("sobol", J("samples" => 6, "second" => true, "blocks" => 3)),
    ("sobol", J("samples" => 4, "blocks" => 5)), ("sobol", J("samples" => 1e16)), ("sobol", J("samples" => 8, "blocks" => 1e16)),
    ("efast", J("samples" => 70, "harmonics" => 4)), ("efast", J("samples" => 65, "harmonics" => 4)),
    ("efast", J("samples" => 8, "harmonics" => 1)), ("efast", J("samples" => 40, "harmonics" => 2)),
    ("efast", J("samples" => 20, "harmonics" => 1e16)), ("efast", J("samples" => 4)),
    ("rbdfast", J("samples" => 30, "harmonics" => 2)), ("rbdfast", J("samples" => 16, "harmonics" => 4)),
    ("rbdfast", J("samples" => 1e16, "harmonics" => 2)),
    ("ff", nothing), ("ff", J("low" => 0.2, "high" => 0.7)), ("ff", J("low" => 0.7, "high" => 0.2)),
    ("dgsm", J("samples" => 5)), ("dgsm", J("samples" => 4, "step" => 0.25, "crossed" => true)), ("dgsm", J("samples" => 1e16)),
    ("dgsm", J("samples" => 3, "step" => 0.6)),
    ("shapley", J("nVar" => 6, "nOuter" => 2, "nInner" => 2)), ("shapley", J("perms" => 3, "nVar" => 5, "nOuter" => 1, "nInner" => 2)),
    ("shapley", J("nVar" => 1e16)), ("shapley", J("perms" => 2, "nInner" => 1)),
    ("efast", J("samples" => 20, "harmonics" => 5e7)), ("efast", J("harmonics" => 1.5e9)),
    ("morris", J("trajectories" => 1e8, "points" => 1e8)), ("morris", J("design" => "trajectories", "trajectories" => 2, "candidates" => -1e16)),
    ("nope", nothing), (nothing, nothing),
]
for (m, o) in DESIGNS, Kn in (1, 2, 3, 5), seed in (1, "7")
    (m == "shapley" && Kn == 5 && o !== nothing && !haskey(o, "perms")) && continue
    case("design", m, KEYS[1:Kn], o === nothing ? nothing : o, seed, nothing)
end
case("design", "morris", Any[], nothing, 1, nothing)
case("design", "ff", KEYS[1:3], nothing, "1e400", nothing)
case("design", "radial", KEYS[1:2], J("samples" => 3), "1e400", nothing)
case("design", "shapley", KEYS[1:2], J("nVar" => 4, "nOuter" => 1, "nInner" => 2, "perms" => 1e16), "1e400", nothing)
case("design", "sobol", KEYS[1:2], J("samples" => 1e16), "1e400", nothing)
# Shapley through a copula: consistent, only semi-definite (the conditional covariance jittered), and not one.
CORRS = Any[(2, [1.0, 0.6, 0.6, 1.0]), (3, [1.0, 0.5, -0.3, 0.5, 1.0, 0.2, -0.3, 0.2, 1.0]),
            (3, [1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0]), (3, [1.0, 0.9, 0.9, 0.9, 1.0, -0.9, 0.9, -0.9, 1.0]),
            (2, [1.0, -0.999999, -0.999999, 1.0])]
for (Kn, c) in CORRS, o in (J("nVar" => 5, "nOuter" => 2, "nInner" => 3), J("perms" => 2, "nVar" => 4, "nOuter" => 2, "nInner" => 2))
    case("design", "shapley", KEYS[1:Kn], o, 11, Any[F(x) for x in c])
end

# The pieces, called directly.
for (Kn, t, p, l) in ((1, 2, 3, 4), (3, 2, 5, 2), (2, 1, 2, 1), (2, 1, 1, 4), (3, 0, 4, 4), (2, -1, 4, 4), (2, 3, -2, 4))
    case("morris_design", Kn, t, p, l, 5, "walk")
end
for (Kn, p) in ((1, 2), (3, 4), (4, 6), (2, 5), (0, 4))
    case("morris_trajectory", Kn, p, 3, "tr", 4)
end
case("trajectory_distance", Any[Any[0, 1], Any[2, 3]], Any[Any[0, 1], Any[2, 3]])
case("trajectory_distance", Any[Any[0, 1], Any[2, 3]], Any[Any[1, 1], Any[2, 0], Any[3, 3]])
case("trajectory_distance", Any[Any[0, 0, 0]], Any[Any[1, 2, 2]])
for (Kn, p, N, k) in ((3, 4, 6, 3), (2, 4, 5, 2), (4, 6, 10, 4), (2, 2, 6, 3), (3, 4, 4, 1), (3, 4, 4, 4), (3, 4, 4, 9), (2, 4, 3, 0))
    case("optimal_trajectories", Kn, p, 4, "opt", N, k)
end
for (Kn, t, l, c) in ((2, 2, 4, 0), (3, 2, 4, 5), (1, 3, 7, 0), (2, 2, 9, -3), (2, 3, 4, 3))
    case("morris_trajectory_design", Kn, t, l, c, 6, "mtd")
end
case("radial_design", 2, Any[Any[F(0.1), F(0.2)], Any[F(0.3), F(0.4)]], Any[Any[F(0.5), F(0.6)], Any[F(0.7), F(0.8)]])
case("radial_design", 1, Any[], Any[])
for (Kn, n, second, blocks) in ((2, 3, false, 1), (2, 2, true, 2), (1, 4, true, 1), (3, 2, false, 0))
    case("sobol_design", Kn, n, second, blocks, 8)
end
for (n, M) in ((1000, 4), (65, 4), (1001, 4), (8, 1), (0, 1), (100, 2), (5, 0), (5, -1), (1e16, 4), (100, 2.5), ("x", 2),
               (1e300, 4), (2.5, 1), (66, 4), (1e3, 1000), (1000, 47434164), (1000, 47434165), (1000, 50000000),
               (1000, 1500000000), (1000, 3037000500), (8999999999999990, 4), (9e15, 4), (8.999999999999998e15, 1))
    case("efast_samples", n, M)
end
for (Kn, N, M) in ((1, 66, 4), (2, 66, 4), (3, 66, 4), (5, 66, 4), (5, 40, 4), (8, 30, 4), (0, 66, 4), (4, 9, 4), (3, 1000, 1))
    case("efast_frequencies", Kn, N, M)
end
case("efast_design", 2, 20, 2, Any[F(0.3), F(1.7)])
case("efast_design", 3, 10, 1, Any[F(0.0), F(2.0), F(1.25)])
case("efast_design", 1, 9, 1, Any[F(0.5)])
for (Kn, N) in ((1, 8), (3, 12), (2, 1), (2, 0))
    case("rbd_fast_design", Kn, N, 9)
end
for (Kn, low, high) in ((1, 0.05, 0.95), (2, 0.1, 0.9), (3, 0.2, 0.7), (5, 0.25, 0.75), (8, 0.01, 0.99), (9, 0.3, 0.6))
    case("ff_design", Kn, F(low), F(high))
end
case("dgsm_design", 2, Any[Any[F(0.1), F(0.9995)], Any[F(0.5), F(0.25)]], F(1e-3), false)
case("dgsm_design", 3, Any[Any[F(0.1), F(0.6)], Any[F(0.5), F(0.25)], Any[F(0.99), F(0.01)]], F(0.01), true)
case("dgsm_design", 1, Any[Any[F(0.7)]], F(0.4), true)
for (Kn, perms, nv, no, ni, c) in ((2, -1, 3, 2, 2, nothing), (3, -1, 2, 1, 2, nothing), (3, 2, 2, 1, 3, nothing), (2, 0, 3, 1, 1, nothing),
                                   (2, -1, 3, 2, 2, [1.0, 0.5, 0.5, 1.0]), (3, 4, 2, 2, 2, [1.0, 0.3, 0.1, 0.3, 1.0, 0.2, 0.1, 0.2, 1.0]),
                                   (2, -1, 3, 1, 1, [1.0, 2.0, 2.0, 1.0]), (2, -2, 3, 1, 1, nothing), (1, -1, 2, 1, 1, nothing))
    case("shapley_design", Kn, perms, nv, no, ni, c === nothing ? nothing : Any[F(x) for x in c], 13, "sh")
end
for k in (0, 1, 2, 3, 4, 6, 8, 16, -4)
    case("hadamard", k)
end
for n in (0, 1, 2, 3, 4)
    case("permutations", n)
end
for n in (-2, 0, 1, 2, 7, 30)
    case("random_permutation", n, 2, "perm")
end
for (n, A) in ((2, [4.0, 2.0, 2.0, 3.0]), (2, [1.0, 1.0, 1.0, 1.0]), (3, [4.0, 2.0, 0.6, 2.0, 2.0, 0.5, 0.6, 0.5, 3.0]),
               (2, [1.0, 2.0, 2.0, 1.0]), (1, [1e-15]), (1, [NaN]), (3, [1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0]), (0, Float64[]))
    case("cholesky", Any[F(x) for x in A], n)
end
for x in vcat(Float64[0, -0.0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, -0.25, -1.5, 2.5, 3.999, -7.75, 1e16, 1e300, -1e300, Inf, NaN,
                      0.49999999999999994, -0.5, -2.5, 2147483647.5, 2147483648, 4294967296, -2147483649, 1e10, -1e10],
              [8 * rnd() - 4 for _ in 1:12])
    case("small", F(x))
end
for (s, t, it) in ((1, 1, 1), (4, 400, 100), (3, 1000, 1000), (10, 500, 30000), (100, 1000, 1000), (7, 401, 25000), (0, 5, 5),
                   (1, 1, 128), (1, 1, 129), (1, 1, 130), (1, 1, 131), (2, 2, 65536), (5, 3, 16777216), (1, 671088640, 1),
                   (2, 3, 6), (-1, 5, 5), (4, 1 << 40, 1 << 30), (1, 1, 167772160), (1, 1, 234881024), (1, 1, 327680),
                   (1, 1, 458752), (1, 1, 320), (1, 1, 448), (1, 1, 64), (3, 7, 1 << 27))
    case("estimate", s, t, it)
end
for (rate, frm, until, most) in ((1e-3, 0.0, 1e4, 10000), (1.0, 5.0, 10.0, 10000), (0.0, 0.0, 1.0, 10000), (-1.0, 0.0, 1.0, 10000),
                                 (2.0, 3.0, 3.0, 10000), (NaN, 0.0, 1.0, 10000), (50.0, 0.0, 100.0, 7), (1e-9, 0.0, 1.0, 10000),
                                 (1.0, -Inf, 0.0, 5), (1.0, 0.0, Inf, 6))
    case("occurrences", F(rate), F(frm), F(until), 17, "Ev#occurrences#3", most)
end
for v in Any["text", " pad ", true, false, 3, -7, 1.0, 1.5e-5, 1e16, 2.5, -0.0, nothing, Any[1, "a\"b\$c\n", nothing, 2.5, true, Any[1.0e-5]],
             K.JDict("k" => 1, "l" => Any[]), Any[], Any[1e6, 1e5, 0.0001, 123456.0, 1234567.0, 5e-324, 1e15],
             Any[1234567.5, 123456.5, 0.00012, 1.5e-5, 2.5e-10, -0.5, 1e15 + 0.5, 12345.678, 1e22, -1.25e-7, 999999.5, 0.1,
                 -100000.5, 1.7976931348623157e308, 2.2250738585072014e-308, 0.30000000000000004],
             Any["tab\there", "\u0001\u007f", "\u00e9\u00ad\u2028\U0001f600", "back\\slash", "\e\a\b\f\v\r", "\u0085",
                 "\u00ad1", "\u00adz", "\U000f0000a", "\U000f0000z", "\u00001", "\u0000z", "\ufeffF", "\u2028"],
             K.JDict("nested" => K.JDict("x" => Any[1, K.JDict()]), "\$" => nothing)]
    case("py_str", v)
end

# --- what each case gives ------------------------------------------------------------------------------

"""Two or more numbers drawn from a stream named here."""
draws(g, n) = Float64[K.next_uniform!(g) for _ in 1:n]

function run_case(fn, args)
    if fn == "jsrules"
        v = val(args[1])
        parts = String[string(K._pd_truthy(v)), K._pd_js_str(v),
                       said(() -> bits(K._pd_to_number(v))), said(() -> string(K._sm_to_uint32(v)))]
        if v !== K._PD_MISSING
            push!(parts, said(() -> (z = K.normal_probit(v); z === nothing ? "none" : bits(z))))
        end
        v isa AbstractString && push!(parts, String(K._pd_js_trim(v)), String(strip(v)))
        return join(parts, "|")
    elseif fn == "stream"
        return said(() -> (g = K.stream_for(args[1], val(args[2])); string(g.a) * "|" * nums(draws(g, 8))))
    elseif fn == "fnv"
        return string(K.fnv_hash(args[1]))
    elseif fn == "uniforms"
        return said(() -> nums(K.uniforms(args[3], K.stream_for(args[1], args[2]); latin=args[4])))
    elseif fn == "take"
        return said(() -> nums(K.take_uniforms!(K.stream_for(args[1], args[2]), args[3])))
    elseif fn == "normal"
        x = unF(args[1])
        z = K.normal_probit(x)
        return join([bits(K.normal_phi(x)), z === nothing ? "none" : bits(z), bits(K.normal_quantile(x))], "|")
    elseif fn == "spec"
        s = args[1]
        lines = String["complete=$(K.pdf_complete(s))"]
        push!(lines, "cuts=" * said(() -> (c = K.probability_cuts(s); "$(bits(c.lo)),$(bits(c.hi)),$(c.cut),$(c.reversed)")))
        dr = try
            K.ValueDrawer(s)
        catch e
            e isa ArgumentError || rethrow()
            push!(lines, "drawer=error:ArgumentError:" * e.msg)
            nothing
        end
        for (k, u) in enumerate(US)
            at = (k - 1) % 11
            push!(lines, join([said(() -> bits(K.value_at_probability(s, u, at))),
                               dr === nothing ? "-" : said(() -> bits(K.draw_value(dr, u, at))),
                               said(() -> bits(K.pdf_quantile(s, u)))], ";"))
        end
        push!(lines, join((said(() -> bits(K.pdf_cdf(s, x))) for x in XS), ";"))
        push!(lines, join((said(() -> bits(K.pdf_cdf(s, val(x)))) * "/" * said(() -> bits(K.pdf_quantile(s, val(x)))) for x in XJ), ";"))
        return join(lines, "\n")
    elseif fn == "vap"
        return said(() -> bits(K.value_at_probability(args[1], unF(args[2]), args[3])))
    elseif fn == "pairs"
        p = args[1]
        p = p isa AbstractDict && haskey(p, "\$project") ? K.Project(p["\$project"]) : p
        cp = K.correlation_pairs(p, args[2])
        return join(["$(x.a - 1),$(x.b - 1),$(bits(x.r))" for x in cp.pairs], ";") * "\n" * join(cp.problems, "\n")
    elseif fn == "iman"
        cols = [unF(c) for c in args[1]]
        pairs = [(a=Int(a) + 1, b=Int(b) + 1, r=unF(r)) for (a, b, r) in args[2]]
        return said() do
            res = K.iman_conover(cols, pairs, args[3], args[4])
            "moved=$(join(res.columns .- 1, ","));adjusted=$(bits(res.adjusted))\n" * join((nums(c) for c in cols), "\n")
        end
    elseif fn == "gsa"
        m, Kn, g = args[1], args[2], val(args[3])
        g === K._PD_MISSING && (g = nothing)
        o = said(() -> tdump(K.gsa_options(m, Kn, g)))
        r = said(() -> tdump(K.gsa_runs(m, Kn, g)))
        f = said(() -> something(K.gsa_refusal(m, Kn, g), "none"))
        return "$o\n$r\n$f"
    elseif fn == "design"
        corr = args[5] === nothing ? nothing : unF(args[5])
        return said(() -> tdump(K.build_design(args[1], args[2], args[3]; seed=args[4], corr)))
    elseif fn == "morris_design"
        return said(() -> tdump(K.morris_design(args[1]; trajectories=args[2], points=args[3], levels=args[4],
                                                next=K.stream_for(args[5], args[6]))))
    elseif fn == "morris_trajectory"
        g = K.stream_for(args[3], args[4])
        return join((tdump(K.morris_trajectory(args[1], args[2], g)) for _ in 1:args[5]), "\n")
    elseif fn == "trajectory_distance"
        mat(rows) = isempty(rows) ? zeros(Int, 0, 0) : permutedims(hcat([Int.(r) for r in rows]...))
        return bits(K.trajectory_distance(mat(args[1]), mat(args[2])))
    elseif fn == "optimal_trajectories"
        g = K.stream_for(args[3], args[4])
        cands = [K.morris_trajectory(args[1], args[2], g) for _ in 1:args[5]]
        return said(() -> join(K.optimal_trajectories(cands, args[6]) .- 1, ","))
    elseif fn == "morris_trajectory_design"
        return said(() -> tdump(K.morris_trajectory_design(args[1]; trajectories=args[2], levels=args[3], candidates=args[4],
                                                           next=K.stream_for(args[5], args[6]))))
    elseif fn == "radial_design"
        return tdump(K.radial_design(args[1], [unF(c) for c in args[2]], [unF(c) for c in args[3]]))
    elseif fn == "sobol_design"
        Kn, n, second, blocks, seed = args
        return said(() -> tdump(K.sobol_design(Kn, n; second, blocks,
                                               draw=(k, which, b) -> K.uniforms(n, K.stream_for(seed, "$k#$which#$b")))))
    elseif fn == "efast_samples"
        return said(() -> string(K.efast_samples(args[1], args[2])))
    elseif fn == "efast_frequencies"
        return said(() -> nums(K.efast_frequencies(args[1], args[2], args[3])))
    elseif fn == "efast_design"
        return said(() -> tdump(K.efast_design(args[1], args[2]; harmonics=args[3], phases=unF(args[4]))))
    elseif fn == "rbd_fast_design"
        Kn, N, seed = args
        perms = [K.gsa_random_permutation(N, K.stream_for(seed, "$k#rbd")) for k in 1:Kn]
        return said(() -> tdump(K.rbd_fast_design(Kn, N; perms)))
    elseif fn == "ff_design"
        return tdump(K.ff_design(args[1]; low=unF(args[2]), high=unF(args[3])))
    elseif fn == "dgsm_design"
        return tdump(K.dgsm_design(args[1], [unF(c) for c in args[2]]; step=unF(args[3]), crossed=args[4]))
    elseif fn == "shapley_design"
        Kn, perms, nv, no, ni, c, seed, name = args
        return said(() -> tdump(K.shapley_design(Kn; perms, n_var=nv, n_outer=no, n_inner=ni, corr=c === nothing ? nothing : unF(c),
                                                 next=K.stream_for(seed, name))))
    elseif fn == "hadamard"
        return said(() -> tdump(K.gsa_hadamard(args[1])))
    elseif fn == "permutations"
        return tdump(K.gsa_permutations(args[1]))
    elseif fn == "random_permutation"
        return tdump(K.gsa_random_permutation(args[1], K.stream_for(args[2], args[3])))
    elseif fn == "cholesky"
        A, n = unF(args[1]), args[2]
        L = K.gsa_cholesky(A, n)
        return (L === nothing ? "none" : nums(L)) * "|" * said(() -> nums(K._gd_jitter_cholesky(A, n)))
    elseif fn == "small"
        x = unF(args[1])
        return join([bits(K.gsa_sinpi(x)), bits(K._gd_round(x)), string(K._gd_int32(x))], "|")
    elseif fn == "estimate"
        e = K.estimate(args[1], args[2], args[3])
        f = K.estimate(args[1], args[2], args[3], "float32")
        return "$(e.bytes)|$(e.text)|$(f.bytes)|$(f.text)|$(K.hold_precision(args[1], args[2], args[3]))"
    elseif fn == "occurrences"
        g = K.stream_for(args[4], args[5])
        return nums(K.sample_occurrences(unF(args[1]), unF(args[2]), unF(args[3]), g; most=args[6]))
    elseif fn == "py_str"
        return K._pb_py_str(args[1])
    end
    error("no such case: $fn")
end

# Written and read back: both engines start from the very values the file holds.
cases = K.parse_json(K.json_text(K.JDict("cases" => cases); indent=0))["cases"]
const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
texts = String[]
for c in cases
    text = run_case(c["fn"], c["args"])
    push!(texts, "$(c["fn"]) $(K.json_text(c["args"]; indent=0))\n$text")
    c["out"] = kept(text)
end
isempty(DUMPS) || write(joinpath(DUMPS, "stats.julia.txt"), join(texts, "\n\n"))
grids = K.JDict("us" => Any[F(u) for u in US], "xs" => Any[F(x) for x in XS], "xj" => XJ)
path = joinpath(@__DIR__, "..", "tests", "fixtures", "stats.json")
write(path, K.json_text(K.JDict("grids" => grids, "cases" => cases); indent=0))
println(path, ": ", length(cases), " cases, ", count(c -> startswith(c["out"], "=error"), cases), " refused")
