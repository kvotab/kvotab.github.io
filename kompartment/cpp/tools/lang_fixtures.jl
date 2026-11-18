# Writes tests/fixtures/lang.json: what the Julia engine makes of the equation
# language, for the C++ engine's tests to compare with (tests/test_lang.cpp).
#
#     julia --project=../julia tools/lang_fixtures.jl
#
# Equations (every one in the bundled examples, and cases made up to reach
# each rule of the grammar) as the trees they parse into or the message they
# are refused with; the built-in functions and V8's own exp, log, log10, pow,
# log1p and expm1 at arguments that reach their branches. Doubles travel as
# their 64 bits in hex.

using Kompartment
const K = Kompartment

bits(x::Float64) = string(reinterpret(UInt64, x); base=16, pad=16)

sexp(n::K.ENum) = n.unit === nothing ? "(num $(bits(n.value)))" : "(num $(bits(n.value)) [$(n.unit)])"
sexp(n::K.ERef) = "(ref $(n.name)" * join((" [" * (i === nothing ? "" : i) * "]" for i in n.indices), "") * ")"
sexp(n::K.ECall) = "(call $(n.name)" * join((" " * sexp(a) for a in n.args), "") * ")"
sexp(n::K.EUnary) = "(neg $(sexp(n.operand)))"
sexp(n::K.EBinary) = "($(n.op) $(sexp(n.left)) $(sexp(n.right)))"
sexp(n::K.ECond) = "(? $(sexp(n.test)) $(sexp(n.then)) $(sexp(n.otherwise)))"

function texts!(out, v)
    if v isa AbstractDict
        for (_, x) in v
            texts!(out, x)
        end
    elseif v isa AbstractVector
        foreach(x -> texts!(out, x), v)
    elseif v isa AbstractString
        push!(out, v)
    end
end

sources = String[]
examples = joinpath(@__DIR__, "..", "..", "examples")
for f in sort(readdir(examples))
    endswith(f, ".json") && texts!(sources, K.parse_json(read(joinpath(examples, f), String)))
end
append!(sources, [
    "", "   ", "1", "1e-5", "1.0E10", ".5", "5.", "2e", "2*ex", "1e+", "0.01[m]", "3[ kg/m3 ]", "2[]", "1[",
    "a+b*c", "a-b-c", "a/b/c", "2^3^2", "-a^2", "2^-1", "2^--1", "2^+a", "-(-a)", "+a", "a.^b.*c./d",
    "a<=b", "a>=b", "a==b", "a~=b", "a!=b", "a&&b||c", "a||b&&c", "a<b==c", "a?b:c", "a?b:c?d:e", "(a?b:c)?d:e",
    "a ? b", "a ? b : ", "min(a,b)", "max(a)", "min()", "if(a,b)", "if(a,b,c)", "if(a,b,c,d)", "pow(a,b)", "ln(x)",
    "fabs(x)", "sgn(x)", "product(a,b)", "pi", "pi()", "eps", "time", "time()", "time(1)", "start_time+end_time",
    "foo(1)", "Lookup(time)", "A.B.C", "A.B.C[x][y]", "A[]", "A[ x ]", "A[x][]", "A.b c", "A..B", "A.1", "a.b.1c",
    "a b", "a,b", "(a", "a)", "a +", "*a", "a # b", "a ? b : c : d", "x[Å]", "é", "1 é", "[x]", "]",
    "sum(a,b,c)", "mean(a)", "and(a,b)", "or(a)", "xor(a,b,c)", "not(a)", "percentile(50,a,b,c)",
    "interpolationUseEndValues(t,0,1,10,2)", "rampDown(x,1,2)", "smoothUp(x,1,2)", "bq2mole(a,b)",
    "transport_sum(a,b,0,1)", "hypot(3,4)", "atan2(1,2)", "erf(0.5)+erfc(0.5)", "1e400", "0x10", "1_000",
    "a\n+\tb\r", "((((((((((a))))))))))", "-" ^ 50 * "a", "(" ^ 3000 * "a" * ")" ^ 3000, "a" * "+a" ^ 4000,
])
sources = unique(sources)
calls = name -> name in ("Lookup", "foo")
parsed = Any[]
for s in sources
    row = K.JDict("src" => s)
    try
        row["tree"] = sexp(K.parse_equation(s; calls))
    catch e
        e isa K.EquationParseError || rethrow()
        row["error"] = e.message
        row["position"] = e.position
    end
    try
        row["names"] = Any[K.names_in(s)...]
    catch e
        row["names"] = Any[]
    end
    push!(parsed, row)
end

# --- the functions ---------------------------------------------------------------------------------

seed = Ref(UInt32(12345))
function rnd()       # mulberry32, as the application's sampler
    seed[] += 0x6d2b79f5
    t = seed[]
    t = (t ⊻ (t >> 15)) * (t | 0x00000001)
    t ⊻= t + (t ⊻ (t >> 7)) * (t | 0x0000003d)
    return ((t ⊻ (t >> 14)) % UInt32) / 4294967296
end
special = [0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 2.0, -2.0, 0.46875, 0.46876, 1e-17, 1e-300, 1e300, -1e300, 5e-324, 170.0,
           170.5, 171.0, 3.0, 2.5, -2.5, 0.49999999999999994, Inf, -Inf, NaN, 709.0, 710.0, -745.0, -746.0, 1e-9, 0.3,
           1.5, 100.0, 1e22, 2.0^53, 0.1, 10.0, 1.0000000000000002, 0.9999999999999999, 33.0, 7.0, -7.0]
randoms(n, scale) = [(rnd() - 0.5) * 2 * scale for _ in 1:n]
wide(n) = [(rnd() < 0.5 ? -1 : 1) * exp((rnd() - 0.5) * 80) for _ in 1:n]

one = Dict("round" => K.kf_round, "sqrt" => K.kf_sqrt, "sign" => K.kf_sign, "ulp" => K.kf_ulp, "not" => K.kf_not,
           "factorial" => K.kf_factorial, "erf" => K.kf_erf, "erfc" => K.kf_erfc, "fix" => K.kf_fix,
           "js_exp" => K.js_exp, "js_log" => K.js_log, "js_log10" => K.js_log10, "js_log1p" => K.js_log1p,
           "js_expm1" => K.js_expm1)
two = Dict("np_pow" => K.np_pow, "jspow" => K.kf_jspow, "jspow1" => K.kf_jspow1, "mod" => K.kf_mod, "rem" => K.kf_rem,
           "min" => K.kf_min, "max" => K.kf_max, "binomial" => K.kf_binomial, "bq2mole" => K.kf_bq2mole,
           "mole2bq" => K.kf_mole2bq, "js_pow" => K.js_pow)
three = Dict("rampDown" => K.kf_ramp_down, "rampUp" => K.kf_ramp_up,
             "smoothDown" => (a, b, c) -> K.kf_smooth_down(a, b, c, true),
             "smoothDownEach" => (a, b, c) -> K.kf_smooth_down(a, b, c, false),
             "smoothUp" => (a, b, c) -> K.kf_smooth_up(a, b, c, true))
calls_out = Any[]
xs1 = vcat(special, randoms(40, 3.0), wide(40))
for name in sort(collect(keys(one))), x in xs1
    push!(calls_out, Any[name, Any[bits(x)], bits(one[name](x))])
end
xs2 = vcat(special[1:8], [NaN, Inf, -Inf, 3.0, 0.5000000001, 1e300], randoms(3, 3.0), wide(3))
for name in sort(collect(keys(two))), a in xs2, b in xs2
    push!(calls_out, Any[name, Any[bits(a), bits(b)], bits(two[name](a, b))])
end
xs3 = [0.0, -0.0, 1.0, -1.0, 0.5, 2.0, NaN, Inf, 0.3]
for name in sort(collect(keys(three))), a in xs3, b in xs3, c in xs3
    push!(calls_out, Any[name, Any[bits(a), bits(b), bits(c)], bits(three[name](a, b, c))])
end
# Many arguments: sorting as V8 sorts, percentiles, transport operations.
many = Any[]
for n in (0, 1, 2, 3, 5, 8, 20, 63, 64, 70), trial in 1:4
    v = Float64[rnd() < 0.15 && trial > 1 ? NaN : (rnd() < 0.1 ? 0.0 : (rnd() < 0.1 ? -0.0 : round((rnd() - 0.5) * 10; digits=trial))) for _ in 1:n]
    push!(many, Any["sort", Any[bits(x) for x in v], Any[bits(x) for x in K.js_sort_numbers(v)]])
    for phi in (0.0, 5.0, 25.0, 50.0, 75.0, 99.0, 100.0, -1.0, 101.0, NaN)
        push!(many, Any["percentile", Any[bits(phi), (bits(x) for x in v)...], bits(K.kf_percentile(phi, v))])
    end
end
for n in (1, 2, 3, 7), trial in 1:3
    cells = Float64[round(rnd() * 10; digits=3) for _ in 1:n]
    for x in (0.0, 0.2, 0.5, 0.999, 1.0, NaN, -0.1, 1.1, 1 / 3)
        r = try bits(K.kf_transport_point(vcat(cells, x))) catch e; "error: " * e.message end
        push!(many, Any["transport_point", Any[bits(c) for c in vcat(cells, x)], r])
    end
    for a in (0.0, 0.1, 0.5, 1.0, 1 / 3, NaN, -0.1), b in (0.0, 0.25, 0.7, 1.0, 1.2, 2 / 3), mean in (false, true)
        r = try bits(K.kf_transport_range(vcat(cells, a, b), mean)) catch e; "error: " * e.message end
        push!(many, Any[mean ? "transport_mean" : "transport_sum", Any[bits(c) for c in vcat(cells, a, b)], r])
    end
end

numbers = Any[]
for x in vcat(special, wide(40), [100000.0, 0.000015, 1e-7, 1.5e21, 1e21, 123456789012345680000.0, 0.1 + 0.2, 1e16, 1e15, 0.0001, 1e-5])
    push!(numbers, Any[bits(x), K.js_number(x), K.js_text(x), K._pyrepr(x)])
end

out = K.JDict("parse" => parsed, "calls" => calls_out, "many" => many, "numbers" => numbers)
path = joinpath(@__DIR__, "..", "tests", "fixtures", "lang.json")
write(path, K.json_text(out; indent=0))
println(path, ": ", length(parsed), " equations, ", length(calls_out), " calls, ", length(many), " of many arguments, ",
        length(numbers), " numbers")
