# Writes tests/fixtures/unitcheck.json: what the Julia engine makes of units
# and of numbers written with one, for the C++ engine's tests to compare with
# (tests/test_unitcheck.cpp).
#
#     julia --project=../julia tools/unit_fixtures.jl
#
# Unit texts as the powers and scale they are read into (every unit, spelling
# and prefix the table knows, compound units, text that is no unit); scales as
# a message writes them; equations with the unit each comes out in or the
# clash that stops it, and the same equations after every literal written
# with a unit has been scaled -- each literal's value to the bit, the unit it
# was converted to, and what was and was not converted; and equations scaled
# as the builder scales them, against a model's blocks. Doubles travel as
# their 64 bits in hex.

using Kompartment
const K = Kompartment

bits(x::Float64) = string(reinterpret(UInt64, x); base=16, pad=16)

"""A unit as one line: its text, its powers in the order they came, its scale."""
dim_line(d) = d === nothing ? "?" : string(d) * " |" * join(("$s^$n" for (s, n) in d.powers), " ") * "| " * bits(d.scale)

sexp(n::K.ENum) = "(num " * bits(n.value) * (n.unit === nothing ? "" : " [$(n.unit)]") *
                  (n.dim === nothing ? "" : " {$(dim_line(n.dim))}") * ")"
sexp(n::K.ERef) = "(ref $(n.name)" * join((" [" * (i === nothing ? "" : i) * "]" for i in n.indices), "") * ")"
sexp(n::K.ECall) = "(call $(n.name)" * join((" " * sexp(a) for a in n.args), "") * ")"
sexp(n::K.EUnary) = "(neg $(sexp(n.operand)))"
sexp(n::K.EBinary) = "($(n.op) $(sexp(n.left)) $(sexp(n.right)))"
sexp(n::K.ECond) = "(? $(sexp(n.test)) $(sexp(n.then)) $(sexp(n.otherwise)))"

# --- unit texts ----------------------------------------------------------------------------------------

function unit_row(text)
    row = K.JDict("text" => text)
    try
        row["dim"] = dim_line(K.parse_unit(text))
    catch e
        e isa InexactError || rethrow()
        row["dim"] = "throws"     # a power past what a whole number holds
    end
    return row
end

prefixes = String[p for (p, _) in K.UNIT_PREFIX]
bases = sort!(collect(K.UNIT_PREFIXABLE))
aliases = sort!(collect(keys(K.UNIT_ALIAS)))
texts = Any[]
append!(texts, bases)
append!(texts, aliases)
for p in prefixes, b in vcat(bases, aliases)
    push!(texts, p * b)
end
for u in ("m", "km", "cm", "mm", "µm", "s", "kg", "metre", "y", "L", "Bq"), d in 0:9
    push!(texts, "$u$d")
end
append!(texts, sort!(collect(K._UNIT_NONE)))
append!(texts, Any[
    "None", "NONE", "Unitless", "DIMENSIONLESS", "N/A", "[ ]", "[  m ]", "[[m]]", "[m", "m]", "[1]", "[none]", "[ - ]",
    "  ", " m ", " m ", " m　", "\u0085m", "\tm\n", " m", "﻿m", "m​",
    "kg/m3", "m^2/year", "mol per kg", "1/(m*s)", "[Bq]", "[ kg/m3 ]", "Bq/kg", "Bq kg-1", "Sv/Bq", "Sv per Bq",
    "m3 per year", "kg per m3", "kg/(m*m*m)", "1/d", "1/day", "per day", "1 per year", "1 per day per m", "g m-3",
    "g/L", "mg/m3", "cm^2/s", "m2/year", "cm^3", "dm3", "m^(1/2) * m^(1/2)", "(km)", "Tm", "pm", "m3/m2",
    "m^-1 m^2", "km·km", "m·s", "m*s", "m**s", "m//s", "m/", "/m", "*m", "m*", "(m", "m)", "()", "(())", "( m )",
    "((m))", "m (s)", "m(s)", "(m)(s)", "(m) s", "m  s", "m\ts", "m s", "ms", "m.s", "a.b", "m.", ".m", "_x", "x_y",
    "%", "m%", "%/year", "% per year", "m^", "m^2", "m^-2", "m^+2", "m^2.5", "m^0.5", "km^2.0", "m^1.5", "m^2.",
    "m^.5", "m ^ 2", "m^ 2", "m ^2", "m^(2)", "m^( 2 )", "m^(1/2)", "m^( 3 / 3 )", "m^(4/2)", "m^(1/0)", "m^(2/",
    "m^(2", "m^(/2)", "m^(1/2/3)", "m^(-1)", "m^(-2/2)", "m^()", "(m^2)^0.5", "(m^3)^(1/3)", "(m^2)^(1/2) s",
    "m^(1/3)", "kg^0", "m^0 s", "m^0", "km^0", "m^2^3", "m^-0", "s-1", "m s-1", "kg m-3", "s-", "s-x", "s -1",
    "s- 1", "s-1-1", "s-0", "m-2 s-1", "m2-1", "km2-1", "s-1.5", "m-1.0",
    "per", "per s", "m per", "m per s per s", "m pers", "m per_s", "m per%", "m per.s", "m perµ", "m peré",
    "m per(s)", "m per (s)", "m per  s", "mper s", "m^2per s", "(m per s) per s", "m per (s per s)", "per per",
    "m per per s", "m per·s", "m per2", "m per 2", "m per -s", "person", "m person",
    "2", "2.5", "2.", ".5", "+3", "-3", "-3 m", "3 m", "m 3", "m/3", "3/m", "1000 mm", "1e3", "1e3 m", "10^3 m",
    "0", "00", "1.0", "1 ", "1 1", "1 m", "1/1", "1/m/s", "1/(m s)", "1/m s", "m/s/s", "m/s*s", "m/(s*s)",
    "m/(s/s)", "kg*m/s^2", "kg m s-2", "kg·m·s^-2", "J/kg", "W/m2", "Pa s", "N/m2",
    "µ", "μ", "µm", "μm", "um", "dam", "da", "dd", "cd", "min", "mmin", "h", "mh", "kh", "month", "ka", "Ma", "kyr",
    "ky", "kyears", "hl", "hL", "hPa", "K", "mK", "N", "kN", "ft", "furlong", "ha", "t", "kt", "eV", "keV", "ppm",
    "kkg", "mkg", "µkg", "Mg", "Gg", "Tg", "kkilogram", "gg", "g2", "kg/kg", "g/g", "mg/kg", "km/m", "m/km",
    "mm/km", "Mg/g", "km2/m2", "km^2/m^2", "Tm/pm", "pm/Tm", "d/year", "year/a", "s/sec",
    "m²", "m³", "Ω", "°C", "é", "m é", "kg/m³", "µ3", "μ2", "µm2", "μm3",
    "((((((((((((((((((((((((((((((((m))))))))))))))))))))))))))))))))",
    "(((((((((((((((((((((((((((((((((m)))))))))))))))))))))))))))))))))",
    "Tm^30", "pm^40", "Tm^30/Tm^30", "Tm^-30", "Tm^26", "pm^27", "km^100", "m^1000000", "m^9007199254740993",
    "m^99999999999999999999999", "m-99999999999999999999999", "m^9223372036854775807", "m^9223372036854775808",
    "m^-9223372036854775808", "(m^3037000500)^3037000500", "m^4611686018427387904 m^4611686018427387904",
    "T", "G", "M", "k", "c", "u", "n", "p", "d", "m", "Tk", "kT", "kM", "Mk",
    "Bq/m3", "MBq/kg", "Sv/year", "mSv/a", "µSv/h", "nSv/h", "mol/L", "mmol/l", "mol/m3", "kmol/m^3",
    "L/kg", "m3/kg", "l/kg", "ml/g", "cm3/g", "m/year", "m/a", "mm/y", "mm/yr", "m3/s", "L/s", "l/d",
    "kg/year", "g/d", "t/a", "1/year", "1/a", "1/y", "1/s", "1/h", "year-1", "a-1", "y-1", "s-1 m-2",
    5, 2.5, 1.0e-5, 100.0, 0, 1, true, false, nothing, Any[], Any["m"], K.JDict(), K.JDict("m" => 1),
])
units = Any[unit_row(t) for t in texts]

# --- scales in messages -----------------------------------------------------------------------------------

scale_values = Float64[1.0, 1000.0, 0.001, 1.0e6, 999999.9999999, 999999.99999999999, 0.00099999999999, 0.0009999999999999,
                       1.0e21, 1.5e-7, 123456.789, 123456789012345.0, 1 / 3, 2 / 3, 1.0e5 + 0.1, 86400.0, 3.15576e7,
                       1 / 86400, 1 / 3.15576e7, 0.0, -0.0, Inf, -Inf, NaN, -2.5e10, -0.5, -1234.5, 1.0e-300, 5.0e-324,
                       1.7976931348623157e308, 0.1 + 0.2, 1.0e6 - 1.0e-7, 100000.00000049, 1.0e-3 * 1.0e-3, 1.0e-6,
                       1.0e12, 1.0e-12, 1.0e9, 1.0e-9, 1.0000000000001e7, 1.00000000000001e7, 2.0e7, 1.2e7, 1.02e-5,
                       1.0e100, 1.23456789012345678e-100, 5.0e6, 0.05, 0.5, 7.0, 10.0, 100.0, 1.0e5, 3.0e-4]
scales = Any[K.JDict("value" => bits(v), "text" => K.scale_text(v), "exponential" => K._to_exponential(v)) for v in scale_values]

same = Any[]
for (a, b) in (("m", "metre"), ("km", "1000 m"), ("km", "m"), ("g", "kg"), ("mg", "kg/1000000"), ("kg/m3", "kg m-3"),
               ("1/year", "per a"), ("d", "day"), ("d", "year"), ("", "-"), ("", "m"), ("m²", "m²"), ("x", "x"),
               (nothing, "1"), (nothing, nothing), ("L", "l"), ("m3", "m^3"), ("m3", "L"), ("mm2", "mm^2"),
               ("µm", "μm"), ("um", "µm"), ("m^(1/2) m^(1/2)", "m"), ("km/m", "1"), ("m/m", "1"), ("Mg", "t"),
               ("mg", "ug"), (1, ""), (2, 3), ("m", 5))
    push!(same, K.JDict("a" => a, "b" => b, "same" => K.same_unit(a, b)))
end

# --- equations -----------------------------------------------------------------------------------------------

"""The unit each name of a table is written with (`nothing`: a block whose unit is not known)."""
const TABLES = K.JDict(
    "years" => K.JDict("time" => "year", "units" => K.JDict(
        "L" => "m", "M" => "kg", "A" => "m2", "V" => "m3", "k" => "1/year", "c" => "kg/m3", "D" => "m^2/s",
        "Lkm" => "m", "U" => "", "X" => nothing, "Bad" => "m²", "P" => "%", "t" => "d", "F" => "furlong",
        "Km" => "km", "G" => "g", "Ms" => "ms", "Near.L" => "km", "R" => "km/m", "Big" => "Tm^30", "Mm" => "mm")),
    "seconds" => K.JDict("time" => "s", "units" => K.JDict(
        "k" => "1/s", "H" => "m", "Late" => "", "Rate3" => "1/s", "L" => "km", "M" => "g")),
    "nothing known" => K.JDict("time" => "year", "units" => K.JDict()),
)

sources = Any[]
seen = Set{Tuple{String,String}}()
add(table, list) = for s in list
    (table, s) in seen && continue
    push!(seen, (table, s))
    push!(sources, (table, s))
end

add("years", [
    "L + 5[km]", "L + 0.01[m]", "L + 5[km] + 3[mm]", "-5[km] + L", "L - 250[cm]", "M + 500[g]", "M + 2[mg]",
    "A + 2[cm2]", "V + 1[L]", "V + 10[cm^3]", "V + 7[dm3]", "k + 1[1/d]", "k + 1e-9[s-1]", "k + 2[per day]",
    "c + 5[mg/m3]", "c + 1[g/L]", "c + 3[g m-3]", "D + 1[cm^2/s]", "D + 1[m2/year]", "if(time > 30[d], 1, 0)",
    "time() > 6[month] ? 1 : 0", "min(time, 100[d])", "max(L, 300[cm])", "if(time >= 0.5, 2[km], L)",
    "time < 2[h] || time > 5[a]", "(L + 1[km]) * (M + 1[g])", "L + 5[ km ]", "L + 5[furlong]", "1[km] + 1[m]",
    "L + 1[m*m/m]", "L == 2000[mm] ? 1 : 0", "time + 1[year]", "sqrt(A) + 10[cm]", "L^2 + 1[km^2]",
    "power(L, 2) + 3[dm2]", "abs(L) + 1[km]", "mod(L, 3) + 1[cm]", "exp(1[km] / L)", "L + 1[µm] + 1[μm] + 1[um]",
    "Lkm + 2[km]", "sum(L, 1[km])", "hypot(L, 30[cm])", "L + 2[1/(m*s)]", "k + 3[1 per year]", "L + 1[ft]",
    "time + 12[ month ]", "k * 2[d] + 1", "L + 1[m^(1/2) * m^(1/2)]", "L + 1[(km)]", "A + 1[km·km]", "L != 1[km]",
    "L + 2[kmol]", "M + 3[Mg] - 2[kg]", "L >= 1[km] && L <= 3[km]", "min(L, 2[km], 900[mm])",
    "if(L > 1, 1[km], 2[km])", "L + 1e3[mm]", "L + .5[km]", "L + 1[]", "L + 1[-]", "L + 1[unitless]", "L + 1[m3/m2]",
    "L + 1[m^-1 m^2]", "L + 1[%]", "c + 1[kg per m3]", "c + 1[kg/(m*m*m)]", "L + 2[Tm] + 3[pm]",
    "1[g] + M", "k + 0.5[1/d]", "if(time < 2[year], k, k + 1[1/year])",
    # every way two things are put together
    "L + M", "L - M", "L * M", "L / M", "L .* M", "L ./ M", "L < M", "L <= M", "L > M", "L >= M", "L == M",
    "L ~= M", "L != M", "L && M", "L || M", "L + Km", "Km + L", "Km - L", "G < M", "M > G", "L == Km", "L + X",
    "X + L", "X * L", "L / X", "X < L", "L + U", "U + L", "U * L", "L / U", "U < L", "L + Bad", "L + P", "P + P",
    "L + 2", "2 + L", "L * 2", "2 / L", "L + R", "R + R", "R * L", "R < 2", "Big + L", "Big + Big", "Big * 2",
    "L ^ 2", "L ^ 0.5", "A ^ 0.5", "L ^ M", "L ^ 0", "L ^ -1", "L ^ -2", "U ^ L", "X ^ 2", "L .^ 3", "R ^ 2",
    "L ^ 1e300", "2 ^ L", "L ^ 2 ^ 2", "-L", "-(L + M)", "-L + M", "L + -Km",
    "L > 0 ? L : M", "L > 0 ? L : Km", "L > 0 ? L : L", "L > 0 ? U : L", "L > 0 ? L : U", "L > 0 ? X : L",
    "L > 0 ? L : X", "L > M ? 1 : 2", "L > Km ? 1 : 2", "(L > 0 ? L : M) + 1[km]",
    "if(L > 0, L, M)", "if(L > 0, L, Km)", "if(L > 0, L)", "if(L > M, 1, 2)", "if(L > 0, U, L)", "if(L > 0, X, L)",
    "min(L, M)", "max(L, Km)", "min(L)", "max(U, L, U)", "min(L, X)", "mean(L, M)", "mean(L, L)", "percentile(50, L)",
    "percentile(L, M)", "abs(L)", "fabs(L)", "ceil(L)", "floor(L)", "round(L)", "fix(L)", "hypot(L, M)", "hypot(L, L)",
    "sum(L, M)", "sum(L, L, L)", "prod(L, M)", "product(L, M)", "rampUp(L, M, 1)", "rampUp(L, L, L)",
    "rampDown(time, 1[d], 2)", "rampDown(L, Km, L)", "smoothUp(L, M, 2)", "smoothUp(L, L, M)", "smoothUp(L, L, 2)",
    "smoothDown(L, L, 1[m])", "smoothDown(L, X, M)", "smoothDown(X, L, L)", "mod(L, M)", "rem(L, M)", "rem(X, M)",
    "atan2(L, M)", "sign(L)", "sgn(M)", "exp(L)", "exp(U)", "exp(X)", "exp(L / Km)", "exp(L / L)", "log(L)", "ln(M)",
    "log10(A)", "log2(V)", "sin(L)", "cos(k)", "tan(c)", "asin(L)", "acos(L)", "atan(L)", "sinh(L)", "cosh(L)",
    "tanh(L)", "asinh(L)", "acosh(L)", "atanh(L)", "erf(L)", "erfc(L)", "factorial(L)", "binomial(L, M)",
    "binomial(U, M)", "sqrt(A)", "sqrt(L)", "sqrt(X)", "sqrt(U)", "sqrt(V * L)", "power(L, 2)", "pow(L, 0.5)",
    "pow(A, 0.5)", "power(L, M)", "power(U, 3)", "power(X, 2)", "power(L, 0)", "pow(L, 1e300)", "power(L, -1)",
    "foo(L)", "Lookup(time)", "foo(L) + 1[km]", "foo(1[km], L)", "not(L)", "and(L, M)", "xor(L, M)",
    "interpolationUseEndValues(L, 0, 1, 10, 2)", "bq2mole(L, M)", "transport_sum(L, M, 0, 1)", "ulp(L)",
    "time", "time()", "start_time()", "end_time()", "time() + L", "time() + t", "time() * k", "start_time() + 1[d]",
    "end_time() - 1[a]", "end_time() - 1[years]", "time() + 1[y]", "time() > 1[yr]", "pi + L", "pi() * L", "eps + L",
    # what a literal is written against
    "1[km] + 2", "2 + 1[km]", "X + 1[km]", "1[km] + X", "Bad + 1[km]", "U + 1[km]", "1[km] + U", "P + 1[km]",
    "min(1[km])", "max(1[km])", "min(1[])", "min(1[km], 2[m])", "min(1[km], 2[m], 3[cm])", "max(1[km], 2[kg])",
    "min(1[km], 2)", "min(2, 1[km])", "min(X, 1[km])", "min(1[km], X)", "min(1[km], X, L)", "min(X, 1[km], L)",
    "min(1[], L)", "min(L, 1[])", "L + 1[m²]", "L + 1[nope nope]", "L + 1[per]", "L + 1[m^1e300]",
    "L + 1[m^99999999999999999999999]", "L ^ 1e300 + 1[m]", "1[m] + L ^ 1e300", "pow(L, 1e300) < 1[km]",
    "if(L > 1[km], 1[km], 2[mm])", "if(L > 1[km], 1[km])", "if(1[km], 2[mm])", "if(1[km])", "ifelse(L > 1, 1[km], L)",
    "ifelse(L > 1, L, 1[km])", "ifelse(1[km], 2[mm], 3[cm])", "ifelse(1[km])", "ifelse()", "max()", "if()",
    "(L + 1[km]) + 1[mm]", "L + (1[km] + 1[mm])", "1[km] + 1[m] + L", "L + 1[km] + 1[m] + 1[cm] + 1[mm]",
    "1[mm] + (1[cm] + (1[m] + (1[km] + L)))", "1[km] - 1[m]", "1[km] == 1000[m]", "1[km] < 1[m]", "1[km] ~= 1[m]",
    "1[km] && 1[m]", "1[km] || 1[m]", "1[km] * 1[m]", "1[km] / 1[m]", "1[km] ^ 2", "2 ^ 1[km]", "1[km] + 1[kg]",
    "1[km] + 1[km]", "1[m] + 1[km]", "1[km] + 1[]", "1[] + 1[km]", "1[km] + 1[m²]", "1[m²] + 1[km]",
    "L == 2000[mm]", "L ~= 1[km]", "L <= 1[km]", "L >= 1[km]", "L < 1[km]", "L > 1[km]", "1[km] > L", "1[km] <= L",
    "time > 1 ? 1[km] : L", "time > 1 ? L : 1[km]", "time > 1 ? 1[km] : 2[m]", "L > 1 ? 1[km] : X", "L > 1 ? X : 1[km]",
    "L > 1[km] ? 1[cm] : 2[mm]", "(L > 1 ? 1[km] : L) + 1[cm]", "1[km] ? 2[m] : 3[cm]",
    "max(1[km], L) + 1[cm]", "min(L, 2[km]) < 1[mm]", "max(L, 1[km], Km, 1[mm])", "max(Km, 1[m], L)",
    "-1[km] + L", "-(1[km]) + L", "L + -1[km]", "L - -1[km]", "-(1[km] + L)", "-(L + 1[km])", "(1[km]) + L",
    "abs(1[km]) + L", "abs(1[km] + L)", "sqrt(1[km2] + A)", "exp(1[km] + L)", "foo(1[km] + L)",
    "Km + 3[mm]", "Km + 1[m]", "Km - 1[cm]", "Km + 1[Tm]", "Mm + 1[km]", "Mm + 1[m]", "Mm + 1[µm]", "G + 1[kg]",
    "G + 1[mg]", "G + 1[µg]", "G + 1[Mg]", "Ms + 1[s]", "Ms + 1[ks]", "t + 1[d]", "t + 1[days]", "t + 1[year]",
    "F + 1[furlong]", "F + 1[m]", "P + 1[%]", "R + 1[km/m]", "R + 1[m/km]", "R + 1[mm/m]", "R + 1[1]", "Big + 1[Tm^30]",
    "Big + 1[m^30]", "Near.L + 1[m]", "Near.L + 1[cm]", "L[a] + 1[km]", "L[] + 1[km]",
    "A + 1[m^2]", "A + 1[km2]", "A + 1[mm2]", "A + 1[cm^2]", "A + 1[dm2]", "A + 1[ha]", "V + 1[km3]", "V + 1[mm3]",
    "V + 1[cm3]", "V + 1[dm^3]", "V + 1[m^3]", "V + 1[m2 m]", "V + 1[cm cm cm]", "V + 1[mm*mm*mm]", "k + 1[1/a]",
    "k + 1[a-1]", "k + 1[per year]", "k + 1[1/years]", "k + 1[1/s]", "c + 1[g/m3]", "c + 1[mg/cm3]", "c + 1[kg/dm3]",
    "c + 1[Mg/km3]", "c + 1[µg/mm3]", "c + 1[g cm-3]", "D + 1[mm2/s]", "D + 1[m^2 s-1]", "D + 1[km2/s]",
    "D + 1[cm2 per s]", "D + 1[m2/ms]", "D + 1[m2/ks]",
    "L + 0.1[km]", "L + 0.7[mm]", "L + 1e-7[km]", "L + 123456.789[cm]", "L + 3.3[µm]", "L + 1e308[km]",
    "L + 5e-324[mm]", "L + 1e-320[pm]", "L + 0[km]", "L + 1e400[km]", "L - 0.3[dm]", "L + 2.2250738585072014e-308[nm]",
    "M + 0.1[g]", "M + 0.3[mg]", "M + 1.1[µg]", "M + 7.7[Mg]", "M + 9.99[Gg]", "M + 1e-15[Tg]", "M + 3[ng]", "M + 3[pg]",
])
# Numbers of every size against units of every size: where the last bit of a product shows.
let seed = UInt32(20261118)
    function rnd()       # mulberry32, as the application's sampler
        seed += 0x6d2b79f5
        t = seed
        t = (t ⊻ (t >> 15)) * (t | 0x00000001)
        t ⊻= t + (t ⊻ (t >> 7)) * (t | 0x0000003d)
        return Float64(t ⊻ (t >> 14)) / 4294967296.0
    end
    lengths = ("Tm", "Gm", "Mm", "km", "dm", "cm", "mm", "um", "µm", "μm", "nm", "pm", "metre", "kmetres")
    masses = ("Tg", "Gg", "Mg", "g", "dg", "cg", "mg", "ug", "µg", "ng", "pg", "kilogram")
    rates = ("1/a", "1/y", "per year", "year-1", "1/years")
    for i in 1:120
        v = (rnd() - 0.3) * 10.0^round(Int, (rnd() - 0.5) * 30)
        against, unit = i % 3 == 0 ? ("M", masses[1+floor(Int, rnd() * length(masses))]) :
                        i % 3 == 1 ? (rnd() < 0.5 ? "L" : (rnd() < 0.5 ? "Km" : "Mm"), lengths[1+floor(Int, rnd() * length(lengths))]) :
                        ("k", rates[1+floor(Int, rnd() * length(rates))])
        text = repr(abs(v))
        add("years", ["$against $(v < 0 ? "-" : "+") $text[$unit]"])
    end
end
add("seconds", [
    "if(time > 2[ks], 1, 0)", "time + 500[ms]", "time >= 1.5[ks] ? 2[km] : H", "k + 1[1/ks]", "k + 2[ms-1]",
    "k * Late + 1[1/ks] * (1 - Late) + 0 * Rate3", "time() + 1[s]", "time() + 1[second]", "time() + 1[seconds]",
    "time() + 1[sec]", "time() + 1[h]", "time() + 1[µs]", "start_time() < 3[Ms]", "H + 1[km]", "L + 1[m]", "M + 1[kg]",
    "M + 1[mg]", "Rate3 + 0.25[1/ms]", "H / time + 1[m/s]", "H / time() + 1[km/s]", "H / time() + 1[m/ks]",
    "H * k + 3[mm/ms]", "min(time, 1[ks], 2[ms])", "time > 1[ks] ? time : 500[ms]",
])
add("nothing known", ["L + 1[km]", "1[km] + 1[m]", "min(L, 1[km])", "time() + 1[year]", "time() + 1[a]", "time + 1[a]",
                      "L > 1[km] ? 1[m] : 2[cm]", "1[km]", "-1[km]", "(1[km])", "1[km] + 2[km] + 3[m]"])

calls = name -> true
equations = Any[]
for (table, src) in sources
    spec = TABLES[table]
    time_dim = K.parse_unit(spec["time"])
    unit_of = name -> (u = get(spec["units"], name, nothing); u === nothing ? nothing : K.parse_unit(u))
    ast = try
        K.parse_equation(src; calls)
    catch e
        e isa K.EquationParseError || rethrow()
        continue                      # not an equation: nothing to check here
    end
    row = K.JDict("table" => table, "src" => src, "literal" => K.has_unit_literal(ast))
    function unit_now()
        try
            u = K.equation_unit(ast, unit_of, time_dim)
            return u.clash === nothing ? "unit: " * dim_line(u.dim) : "clash: " * u.clash
        catch e
            e isa InexactError || rethrow()
            return "throws"
        end
    end
    row["unit"] = unit_now()
    done = K.scale_literals(ast, unit_of, time_dim)
    row["scaled"] = sexp(ast)
    row["converted"] = Any[Any[bits(c.value), c.from, c.to, bits(c.now)] for c in done.converted]
    row["unconverted"] = Any[Any[bits(c.value), c.unit] for c in done.unconverted]
    after = unit_now()
    after == row["unit"] || (row["unit_after"] = after)          # left out where scaling changes nothing of it
    # A second pass finds the literals already converted (written down only if it changes one).
    again = K.scale_literals(ast, unit_of, time_dim)
    sexp(ast) == row["scaled"] || (row["again"] = sexp(ast))
    row["again_converted"] = length(again.converted)
    push!(equations, row)
end

# --- as the builder scales them --------------------------------------------------------------------------------

const BLOCKS = K.JDict(
    "L" => K.JDict("unit" => "m"), "Near.L" => K.JDict("unit" => "km"), "Near.Rock.W" => K.JDict("unit" => "mm"),
    "Near.Only" => K.JDict("unit" => "cm"), "Q" => K.JDict("unit" => 5), "Q2" => K.JDict("unit" => 2.5),
    "R" => K.JDict("unit" => true), "R2" => K.JDict("unit" => false), "S" => K.JDict("unit" => nothing),
    "T" => K.JDict("unit" => ""), "V" => K.JDict("unit" => Any["m"]), "V2" => K.JDict("unit" => Any[]),
    "V3" => K.JDict("unit" => K.JDict("m" => 1)), "Z" => K.JDict("name" => "Z"), "Y" => K.JDict("unit" => 1.0e-5),
    "W0" => K.JDict("unit" => 0), "N1" => K.JDict("unit" => "none"), "N2" => K.JDict("unit" => "[m]"),
    "N3" => K.JDict("unit" => " km "), "Bad" => K.JDict("unit" => "m²"), "k" => K.JDict("unit" => "1/year"),
    "Far.k" => K.JDict("unit" => "1/d"), "A.B.C" => K.JDict("unit" => "kg"),
)
const SIMULATIONS = K.JDict(
    "year" => K.JDict("time_unit" => "year"), "second" => K.JDict("time_unit" => "second"),
    "day" => K.JDict("time_unit" => "day"), "hour" => K.JDict("time_unit" => "hour"),
    "minute" => K.JDict("time_unit" => "minute"), "none" => K.JDict(), "empty" => K.JDict("time_unit" => ""),
    "null" => K.JDict("time_unit" => nothing),
)
model = Any[]
function scaled_in_model(src, system, sim)
    ast = K.parse_equation(src; calls)
    b = (project=(simulation=SIMULATIONS[sim],), unit_blocks=Dict{String,K.JDict}(k => v for (k, v) in BLOCKS))
    K._scale_literals!(ast, b, system)
    push!(model, K.JDict("src" => src, "system" => system, "simulation" => sim, "scaled" => sexp(ast)))
end
for system in ("", "Near", "Near.Rock", "Far", "A.B", "Nowhere"),
    src in ("L + 1[cm]", "Near.L + 1[cm]", "W + 1[km]", "Only + 1[km]", "Near.Only + 1[km]", "Near.Rock.W + 1[m]",
            "k + 1[1/a]", "k + 1[1/d]", "Far.k + 1[1/year]", "C + 1[g]", "A.B.C + 1[g]", "L + W + 1[km]")
    scaled_in_model(src, system, "year")
end
for src in ("Q + 1[km]", "Q2 + 1[km]", "R + 1[km]", "R2 + 1[km]", "S + 1[km]", "T + 1[km]", "V + 1[km]", "V2 + 1[km]",
            "V3 + 1[km]", "Z + 1[km]", "Y + 1[km]", "W0 + 1[km]", "N1 + 1[km]", "N2 + 1[km]", "N3 + 1[m]", "Bad + 1[km]",
            "Missing + 1[km]", "min(Q, 1[km], L)", "min(S, 1[km], L)", "L + 2", "2[km]", "L + 1[]")
    scaled_in_model(src, "", "year")
end
for sim in keys(SIMULATIONS),
    src in ("time() + 1[d]", "time() + 1[day]", "time() + 1[h]", "time() + 1[hours]", "time() + 1[s]", "time() + 1[ms]",
            "time() + 1[year]", "time() + 1[a]", "time() + 1[minute]", "time() + 1[min]", "time() > 2[ks] ? 1 : 0",
            "start_time() + 1[yr]", "L / time() + 1[km/year]", "L / time() + 1[km/s]", "L / time() + 1[mm/d]")
    scaled_in_model(src, "", sim)
end

path = joinpath(@__DIR__, "..", "tests", "fixtures", "unitcheck.json")
write(path, K.json_text(K.JDict("units" => units, "scales" => scales, "same" => same, "tables" => TABLES,
                                "equations" => equations, "blocks" => BLOCKS, "simulations" => SIMULATIONS,
                                "model" => model); indent=0))
println(path, ": ", length(units), " unit texts, ", length(scales), " scales, ", length(equations), " equations, ",
        length(model), " equations against a model, ", filesize(path), " bytes")
