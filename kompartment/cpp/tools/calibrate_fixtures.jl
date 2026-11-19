# Writes tests/fixtures/calibrate.json: the optimisers and calibrations by the Julia
# package with parity on, for the C++ engine's tests to compare with
# (tests/test_calibrate.cpp, and tests/test_service.cpp for the service's answers).
#
#     julia --project=. ../cpp/tools/calibrate_fixtures.jl        (from ../julia)
#
# The optimisers on functions made up for the purpose -- smooth, flat, not a number in a
# region, infinite everywhere, at the bounds and past them, raising, giving up -- from
# starts inside the box, on its bounds and outside it, with budgets that run out and
# searches stopped by their signal, every refusal, and the odd values a caller can pass
# (bounds as text, starts with gaps, a budget that is no number, seeds and populations of
# every kind): every step each reports, and what each gives. Beside them the pieces:
# `objective_of` on readings and targets of every kind, the elimination `_op_solve`, the
# keys a point is known by, and the scales, spaces and methods looked up by odd keys.
# Then `reading_of` on runs of every bundled example (the far-field one on two cells) and
# of models made up to reach each kind of series, `variables_of` on each, and
# calibrations: bundled examples and made-up
# models against targets read at the peak, at the end and at a time, variables in the
# value and in its logarithm, each method under several seeds and budgets, a model that
# will not solve in a corner of the box, targets that are not there or cannot be met,
# stopped searches and every refusal -- every step said and the answer (without "ms").
# Last, the service's answers to `calibrate` jobs: what it says, what it writes (its
# time taken said as 0) and every step's `detail` as the service builds it. Every number
# as its bits; a case's text kept as an FNV-1a hash past 300 bytes. With
# KOMPARTMENT_FIXTURE_DUMPS set every text is written there (`calibrate.julia.txt`).

using Kompartment
const K = Kompartment
K.set_parity!(true)

bits(x::Real) = (y = Float64(x); isnan(y) ? "nan" : string(reinterpret(UInt64, y); base=16, pad=16))
function fnv(text::AbstractString)
    h = 0xcbf29ce484222325
    for b in codeunits(String(text))
        h = (h ⊻ b) * 0x100000001b3
    end
    return string(h; base=16, pad=16)
end
kept(text::String) = ncodeunits(text) <= 300 ? "=" * text : "#" * fnv(text)
nums(v) = join((bits(Float64(x)) for x in v), ",")

function tdump(v)
    v === nothing && return "null"
    v isa Bool && return v ? "true" : "false"
    v isa Integer && return "i" * string(v)
    v isa AbstractFloat && return "f" * bits(Float64(v))
    v isa AbstractString && return "s(" * String(v) * ")"
    (v isa AbstractVector || v isa Tuple) && return "[" * join((tdump(x) for x in v), ",") * "]"
    v isa AbstractDict && return "{" * join((string(k) * "=" * tdump(x) for (k, x) in v), ";") * "}"
    error("cannot dump $(typeof(v))")
end

"""What a call gives, or the error it raises as the service names it: its type and its message."""
function said(f)
    try
        return f()
    catch e
        e isa InterruptException && rethrow()
        info = K._service_error("", e)
        return "error:" * string(info["name"]) * ":" * string(info["message"])
    end
end

J(pairs...) = K.JDict(String(k) => v for (k, v) in pairs)
P(text) = K.parse_json(text)

const ROOT = joinpath(@__DIR__, "..", "..")
examples_dir = joinpath(ROOT, "examples")
examples = sort!([splitext(f)[1] for f in readdir(examples_dir) if endswith(f, ".json")])
examples_raw = Dict(ex => P(read(joinpath(examples_dir, ex * ".json"), String)) for ex in examples)

# --- the functions the optimisers are run on (tests/test_calibrate.cpp has each, in the same arithmetic) ----------

const CENTRE = [0.3, -0.2, 0.7, 0.05]
function sphere(x)
    s = 0.0
    for i in eachindex(x)
        d = x[i] - CENTRE[(i-1)%4+1]
        s += d * d
    end
    return s
end
const FUNCTIONS = Dict{String,Function}(
    "sphere" => sphere,
    "rosenbrock" => x -> (a = 1 - x[1]; b = x[2] - x[1] * x[1]; a * a + 100 * b * b),
    "flat" => x -> 5.0,
    "nan right" => x -> x[1] > 0.5 ? NaN : sphere(x),
    "inf left" => x -> x[1] < 0.1 ? Inf : sphere(x),
    "corner" => x -> (a = x[1] - 2; b = x[2] + 3; a * a + b * b),
    "abs" => x -> abs(x[1] - 0.25) + abs(x[2] + 0.5),
    "explog" => x -> K.js_exp(x[1]) - 2 * x[1] + K.js_log(1 + x[2] * x[2]),
    "plateaus" => x -> floor(x[1] * 4) + 0.5 * floor(x[2] * 3),
    "never" => x -> Inf,
    "huge" => x -> 1e200 * (1 + x[1] * x[1]) * 1e200,
    "throws" => x -> x[1] > 0.6 ? error("boom") : sphere(x),
    "gives up" => x -> x[1] > 0.6 ? throw(K.OptimiseError("gave up")) : sphere(x),
    "negative zero" => x -> -0.0 * x[1],
    "one" => x -> (d = x[1] * x[1] - 2; d * d),
)
const DATA = ((0.0, 2.0), (1.0, 1.2), (2.0, 0.75), (4.0, 0.3), (7.0, 0.07))
const RESIDUALS = Dict{String,Function}(
    "line" => x -> [x[1] + x[2] - 1, x[1] - x[2] - 0.5, 2 * x[1] + 0.25 * x[2] - 3],
    "rosen" => x -> [1 - x[1], 10 * (x[2] - x[1] * x[1])],
    "expfit" => x -> [x[2] * K.js_exp(-x[1] * t) - d for (t, d) in DATA],
    "nan right" => x -> x[1] > 0.5 ? [NaN, x[2]] : [x[1] - 0.2, x[2] - 0.1],
    "inf jacobian" => x -> [x[1] > 0.3 ? Inf : x[1] - 0.5, x[2] - 0.25],
    "empty" => x -> Float64[],
    "one" => x -> [x[1] * x[1] - 2],
    "flat" => x -> [1.0, 2.0],
    "throws" => x -> x[1] > 0.6 ? error("boom") : [x[1] - 0.7, x[2]],
    "far out" => x -> [(x[1] - 1000000.005) * 3, x[2] - 2],
    # Downhill on each tooth, a step up at the next: only ever smaller steps help, and the damping climbs.
    "sawtooth" => x -> [floor(10 * x[1]) / 10 - 0.05 * x[1] + 1],
    # Residuals that cannot all be zero: Gauss-Newton creeps in, every step a little better.
    "mixed" => x -> [x[1] - 1, x[1] * x[1] - 4, 0.5 * x[1] - 0.3],
    "far apart" => x -> [x[1] - 3, x[1] * x[1] - 1, x[1] + 2],
    "two" => x -> [x[1] - 1, x[2] - 2, x[1] * x[2] - 4, x[1] * x[1] - x[2]],
)

# --- the optimiser cases ---------------------------------------------------------------------------------------

optimise = Any[]
opt(method, fn, start, o...) = push!(optimise, J("method" => method, "fn" => fn, "start" => start, "options" => J(o...)))
BOX2 = ("lower" => Any[-1, -1], "upper" => Any[1, 1])
UNIT2 = ("lower" => Any[0, 0], "upper" => Any[1, 1])

# Nelder-Mead.
opt("nelder", "sphere", Any[0.5, 0.5], BOX2...)
opt("nelder", "sphere", Any[0, 0, 0], "lower" => Any[-1, -1, -1], "upper" => Any[1, 1, 1], "max_evals" => 60)
opt("nelder", "sphere", Any[0.1, 0.2, 0.3, 0.4], "lower" => Any[-1, -1, -1, -1], "upper" => Any[1, 1, 1, 1], "max_evals" => 150)
opt("nelder", "rosenbrock", Any[-1.2, 1], "lower" => Any[-2, -2], "upper" => Any[2, 2])
opt("nelder", "rosenbrock", Any[-1.2, 1], "lower" => Any[-2, -2], "upper" => Any[2, 2], "tol" => 1e-3)
opt("nelder", "rosenbrock", Any[-1.2, 1], "lower" => Any[-2, -2], "upper" => Any[2, 2], "tol" => 0, "max_evals" => 90)
opt("nelder", "flat", Any[0.5, 0.5], BOX2...)
opt("nelder", "nan right", Any[0.4, 0.1], BOX2...)
opt("nelder", "inf left", Any[0.2, 0.3], BOX2...)
opt("nelder", "corner", Any[0.5, 0.5], UNIT2...)
opt("nelder", "sphere", Any[3, -2], UNIT2...)
opt("nelder", "sphere", Any[1.0, 1.0], UNIT2...)
opt("nelder", "sphere", Any[1, 0], UNIT2...)
opt("nelder", "corner", Any[1, 0], UNIT2...)
opt("nelder", "sphere", Any[0.5, 0.2], "lower" => Any[0.5, 0], "upper" => Any[0.5, 1])
opt("nelder", "sphere", Any[0.5, 0.5], BOX2..., "max_evals" => 1)
opt("nelder", "sphere", Any[0.5, 0.5], BOX2..., "max_evals" => 0)
opt("nelder", "sphere", Any[0.5, 0.5], BOX2..., "max_evals" => "7")
opt("nelder", "flat", Any[0.5, 0.5], BOX2..., "max_evals" => "abc")
opt("nelder", "sphere", Any[0.5, 0.5], BOX2..., "max_evals" => nothing)
opt("nelder", "sphere", Any[0.5, 0.5], BOX2..., "max_evals" => true)
opt("nelder", "sphere", Any[0.5, 0.5], BOX2..., "abort" => 0)
opt("nelder", "sphere", Any[0.5, 0.5], BOX2..., "abort" => 5)
opt("nelder", "abs", Any[0.9, 0.9], BOX2...)
opt("nelder", "explog", Any[0.1, 0.8], BOX2...)
opt("nelder", "plateaus", Any[0.3, 0.6], UNIT2...)
opt("nelder", "never", Any[0.5, 0.5], BOX2..., "max_evals" => 15)
opt("nelder", "huge", Any[0.5, 0.5], BOX2..., "max_evals" => 15)
opt("nelder", "throws", Any[0.5, 0.5], UNIT2...)
opt("nelder", "gives up", Any[0.5, 0.5], UNIT2...)
opt("nelder", "negative zero", Any[0.5, -0.5], BOX2...)
opt("nelder", "sphere", Any[nothing, "0.2"], BOX2...)
opt("nelder", "sphere", Any[true, -1], BOX2...)
opt("nelder", "sphere", Any["1", 1], UNIT2...)
opt("nelder", "sphere", Any[], BOX2...)
opt("nelder", "sphere", Any[0.5, 0.5], "upper" => Any[1, 1])
opt("nelder", "sphere", Any[0.5, 0.5], "lower" => Any[0, 0], "upper" => nothing)
opt("nelder", "one", 0.3, "lower" => Any[0], "upper" => Any[3])
opt("nelder", "one", Any[1], "lower" => Any[0], "upper" => Any[3])
opt("nelder", "sphere", Any[0.5, 0.5], "lower" => Any[0], "upper" => Any[1])
opt("nelder", "sphere", Any[0.5, 0.5], "lower" => Any["0", "-0.5"], "upper" => Any["1", "abc"])
opt("nelder", "sphere", Any[0.5, 0.5], "lower" => Any[nothing, true], "upper" => Any[1, 2])
# A start with no number in it: every point the simplex makes is "NaN,NaN", answered from memory and never counted
# against the budget, so the search goes on until it is stopped (a fault of the Julia package's, and the
# application's, kept here: only the signal ends these).
opt("nelder", "sphere", "ab", BOX2..., "abort" => 3000)
opt("nelder", "sphere", J("a" => 1, "b" => 2), BOX2..., "abort" => 2000)
opt("nelder", "sphere", "é1", BOX2..., "abort" => 1000)
opt("nelder", "sphere", Any[0.5, 0.5], "lower" => -1, "upper" => 1)
opt("nelder", "sphere", Any[0.5, 0.25], "lower" => Any[0, 0], "upper" => Any[0.5, 0.25])

# Levenberg-Marquardt.
opt("lm", "line", Any[0, 0], "lower" => Any[-5, -5], "upper" => Any[5, 5])
opt("lm", "rosen", Any[-1.2, 1], "lower" => Any[-2, -2], "upper" => Any[2, 2], "max_evals" => 200)
opt("lm", "expfit", Any[0.1, 1], "lower" => Any[0, 0], "upper" => Any[5, 10])
opt("lm", "expfit", Any[0.1, 1], "lower" => Any[0, 0], "upper" => Any[0.3, 1.5])
opt("lm", "expfit", Any[0.3, 1.5], "lower" => Any[0, 0], "upper" => Any[0.3, 1.5])
opt("lm", "expfit", Any[0.1, 1], "lower" => Any[0, 1], "upper" => Any[5, 1])
opt("lm", "nan right", Any[0.45, 0.2], BOX2...)
opt("lm", "inf jacobian", Any[0.25, 0.1], BOX2...)
opt("lm", "empty", Any[0.5, 0.5], BOX2...)
opt("lm", "one", Any[1], "lower" => Any[0], "upper" => Any[3])
opt("lm", "flat", Any[0.5, 0.5], BOX2...)
opt("lm", "rosen", Any[-1.2, 1], "lower" => Any[-2, -2], "upper" => Any[2, 2], "max_evals" => 3)
opt("lm", "rosen", Any[-1.2, 1], "lower" => Any[-2, -2], "upper" => Any[2, 2], "max_evals" => 0)
opt("lm", "rosen", Any[-1.2, 1], "lower" => Any[-2, -2], "upper" => Any[2, 2], "abort" => 4)
opt("lm", "throws", Any[0.5, 0.5], UNIT2...)
opt("lm", "rosen", Any[-1.2, 1], "lower" => Any[-2, -2], "upper" => Any[2, 2], "tol" => 1e-3)
opt("lm", "line", Any[9, -9], "lower" => Any[-5, -5], "upper" => Any[5, 5])
opt("lm", "line", Any[], "lower" => Any[-5, -5], "upper" => Any[5, 5])
opt("lm", "line", Any[0, 0], "lower" => Any[-5, -5])
opt("lm", "far out", Any[1000000.01, 1], "lower" => Any[999999.98, 0], "upper" => Any[1000000.02, 4])
opt("lm", "line", Any[0, nothing], "lower" => Any[-5, "-5"], "upper" => Any[5, 5])
opt("lm", "line", Any[0, 0], "lower" => Any[-5, -5], "upper" => Any[5, 5], "max_evals" => "abc")
opt("lm", "rosen", Any[-1.2, 1], "lower" => Any[-2, -2], "upper" => Any[2, 2], "tol" => 0, "max_evals" => 300)
opt("lm", "expfit", Any[0.1, 1], "lower" => Any[0, 0], "upper" => Any[5, 10], "tol" => 0, "max_evals" => 300)
opt("lm", "sawtooth", Any[0.55], "lower" => Any[0], "upper" => Any[1])
opt("lm", "sawtooth", Any[0.55], "lower" => Any[0], "upper" => Any[1], "tol" => 0, "max_evals" => 400)
opt("lm", "mixed", Any[3], "lower" => Any[0], "upper" => Any[5], "tol" => 0, "max_evals" => 300)
opt("lm", "far apart", Any[4], "lower" => Any[-5], "upper" => Any[5], "tol" => 0, "max_evals" => 300)
opt("lm", "two", Any[3, 0.5], "lower" => Any[-5, -5], "upper" => Any[5, 5], "tol" => 0, "max_evals" => 300)
opt("lm", "two", Any[3, 0.5], "lower" => Any[-5, -5], "upper" => Any[5, 5])

# Differential evolution.
opt("de", "sphere", nothing, BOX2..., "max_evals" => 200)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 200, "seed" => 7)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "seed" => "3")
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "seed" => 2.9)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "seed" => nothing)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "seed" => -1)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "pop_size" => 5)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "pop_size" => 3.5)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "pop_size" => 3)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "pop_size" => "12")
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "F" => 0.5, "CR" => 0.3)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "CR" => 0)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "F" => 0)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "start" => Any[0.3, -0.2])
opt("de", "sphere", nothing, BOX2..., "max_evals" => 120, "start" => Any[5, -5])
opt("de", "sphere", nothing, BOX2..., "max_evals" => 60, "start" => 0)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 60, "start" => 0.25)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 60, "start" => Any[])
opt("de", "sphere", nothing, BOX2..., "max_evals" => 60, "start" => "")
opt("de", "flat", nothing, BOX2..., "max_evals" => 100)
opt("de", "never", nothing, BOX2..., "max_evals" => 30)
opt("de", "nan right", nothing, BOX2..., "max_evals" => 100)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 100, "abort" => 10)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 5)
opt("de", "sphere", nothing, BOX2..., "max_evals" => 0)
opt("de", "sphere", nothing, "upper" => Any[1, 1])
opt("de", "sphere", nothing, "lower" => Any[], "upper" => Any[1, 1])
opt("de", "sphere", nothing, "lower" => Any[-1, -1])
opt("de", "throws", nothing, UNIT2..., "max_evals" => 100)
opt("de", "gives up", nothing, UNIT2..., "max_evals" => 100)
opt("de", "rosenbrock", nothing, "lower" => Any[-2, -2], "upper" => Any[2, 2], "max_evals" => 300)
opt("de", "sphere", nothing, "lower" => fill(-1, 7), "upper" => fill(1, 7), "max_evals" => 150)
opt("de", "one", nothing, "lower" => Any[0], "upper" => Any[3], "max_evals" => 80)
opt("de", "plateaus", nothing, UNIT2..., "max_evals" => 80, "seed" => 11)
opt("de", "sphere", nothing, "lower" => Any[-1, "x"], "upper" => Any[1, 1], "max_evals" => 40)
opt("de", "sphere", nothing, BOX2..., "max_evals" => nothing, "pop_size" => 4)
opt("de", "sphere", nothing, "lower" => 0, "upper" => 1, "max_evals" => 40)

# --- the pieces --------------------------------------------------------------------------------------------------

objective = Any[]
for (readings_, targets) in (
        (Any[1.0, 2.0, 3.0], Any[J("value" => 1.5), J("value" => 2, "scale" => "absolute"), J("value" => 3.5, "scale" => "log")]),
        (Any[1.0, 0.0, -1.0], Any[J("value" => 0), J("value" => 0, "scale" => "log"), J("value" => -1, "scale" => "log")]),
        (Any[2.0, 2.0, 2.0, 2.0, 2.0], Any[J("value" => 1, "weight" => 4), J("value" => 1, "weight" => "4"), J("value" => 1, "weight" => 0),
                                         J("value" => 1, "weight" => -2), J("value" => 1, "weight" => true)]),
        (Any[1.0], Any[J("value" => 1), J("value" => 2), J("value" => 3, "scale" => "absolute")]),
        (Any[nothing, "2.5", true, Any[1], J("a" => 1), "x"], Any[J("value" => 1) for _ in 1:6]),
        (Any[1.0, 1.0, 1.0], Any["x", 5, nothing]),
        (Any[1.0, 1.0, 1.0, 1.0, 1.0], Any[J("value" => 2, "scale" => Any["log"]), J("value" => 2, "scale" => "LOG"), J("value" => 2, "scale" => 5),
                                         J("value" => "abc"), J("value" => "0.5", "scale" => nothing)]),
        (Any[1e300, 1e10, 3.0], Any[J("value" => 1e-300), J("value" => 0, "weight" => 1e300), J("value" => 1)]),
        (Any[], Any[]),
        (Any[0.5, 0.25], Any[J("value" => 0.5, "scale" => "relative"), J("value" => 0.125, "scale" => "log", "weight" => 9)]))
    push!(objective, J("readings" => readings_, "targets" => targets))
end

solve = Any[]
for (A, b) in (([[2.0, 1.0], [1.0, 3.0]], [1.0, 2.0]), ([[0.0, 1.0], [1.0, 0.0]], [3.0, 4.0]), ([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0]),
               ([[4.0]], [2.0]), ([[0.0]], [1.0]), ([[1e-301]], [1.0]), ([[NaN, 1.0], [1.0, 1.0]], [1.0, 1.0]),
               ([[1.0, 2.0, 3.0], [4.0, 5.0, 6.5], [7.0, 8.5, 10.0]], [1.0, -1.0, 0.5]),
               ([[1e-3, 1.0, 0.0, 2.0], [1.0, 1e-3, 1.0, 0.0], [0.0, 1.0, 1e-3, 1.0], [2.0, 0.0, 1.0, 1e-3]], [1.0, 2.0, 3.0, 4.0]),
               ([[-0.0, 1.0], [1.0, -0.0]], [-0.0, 0.0]), ([[Inf, 1.0], [1.0, 1.0]], [1.0, 1.0]))
    x = K._op_solve([copy(r) for r in A], copy(b))
    push!(solve, J("A" => [nums(r) for r in A], "b" => nums(b), "out" => x === nothing ? "none" : nums(x)))
end

key_values = [0.1, 1 / 3, 1e-7, 123456789012.5, -0.0, 0.0, 1e21, 5e-324, floatmax(Float64), NaN, Inf, -Inf, 0.30000000000000004,
              999999999999.5, 999999999999.4, 1.00000000000049999, 2.0^-30, -1234.5678901234567, 1e-300, 4.35]
point_keys = J("values" => nums(key_values), "out" => join((K.js_to_precision(v, 12) for v in key_values), "|"))

lookup_keys = Any["absolute", "relative", "log", "linear", "LOG", nothing, 5, Any["log"], Any["lm"], J("a" => 1), "constructor", "toString", "",
                  "nelder", "de", "lm", true]
missing_key = K._PD_MISSING
which(table, key) = (f = K._op_lookup(table, key); f === nothing ? "none" : only(k for (k, g) in table if g === f))
lookups = Any[J("key" => k, "scale" => which(K.OPTIMISE_SCALES, k), "space" => which(K.OPTIMISE_SPACES, k), "method" => which(K.OPTIMISE_METHODS, k))
              for k in lookup_keys]
push!(lookups, J("missing" => true, "scale" => which(K.OPTIMISE_SCALES, missing_key), "space" => which(K.OPTIMISE_SPACES, missing_key),
                 "method" => which(K.OPTIMISE_METHODS, missing_key)))
pairs_ = [(2.0, 1.0), (0.0, 0.0), (-1.0, 2.0), (1.0, 0.0), (3.0, -2.0), (1e-300, 1e300), (NaN, 1.0), (Inf, 2.0), (0.5, 0.25)]
scales = K.JDict(name => join((bits(f(g, w)) for (g, w) in pairs_), ",") for (name, f) in sort!(collect(K.OPTIMISE_SCALES); by=first))
scales["pairs"] = join(("$(bits(g)):$(bits(w))" for (g, w) in pairs_), ",")
space_values = [0.5, 1.0, 2.0, 1e-9, 0.0, -1.0, NaN, Inf]
spaces = K.JDict(name => join(("$(bits(s.to(v))):$(bits(s.from(v))):$(s.ok(v, 2v))" for v in space_values), ",")
                 for (name, s) in sort!(collect(K.OPTIMISE_SPACES); by=first))
spaces["values"] = nums(space_values)

# --- the models --------------------------------------------------------------------------------------------------

const SIM = """{"start_time": 0, "end_time": 10, "output_points": 11, "spacing": "linear", "solver": "ndf", "rtol": 1e-6,
                "abstol": 1e-9, "time_unit": "year"}"""
sim(extra) = replace(SIM, "\"time_unit\"" => extra * ", \"time_unit\"")

models = Any[]
model(name, text) = push!(models, (name, P(text)))

model("decay", """{"name": "decay", "simulation": $SIM,
 "parameters": [{"name": "a0", "value": 5}, {"name": "k", "value": 0.3}, {"name": "k2", "value": 0.1}, {"name": "c", "value": 7},
                {"name": "blank", "value": ""}, {"name": "listed", "value": [2]}],
 "compartments": [{"name": "A", "initial": "a0"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k"}, {"name": "Bout", "from": "B", "to": null, "rate": "k2 + 0 * blank * listed"}],
 "expressions": [{"name": "Flux", "equation": "k * A"}, {"name": "Twice", "equation": "c * 2"}]}""")

# Past k = 1 the rate is no number, and the run stops on it: a corner of the box that does not solve.
model("corner", """{"name": "corner", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.5}, {"name": "s", "value": 1}],
 "compartments": [{"name": "A", "initial": "s"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "sqrt(1 - k)"}]}""")

model("indexed", """{"name": "indexed", "nuclides": ["Cs-137", "Sr-90"], "simulation": $SIM,
 "index_lists": [{"name": "Zone", "indices": ["a", "b"]}],
 "parameters": [{"name": "Kd", "value": 1, "index_lists": ["Radionuclides", "Zone"],
                 "entries": [{"index": {"Zone": "b"}, "value": 2}, {"index": {"Radionuclides": "Sr-90", "Zone": "a"}, "value": 3}]},
                {"name": "k_leach", "value": 0.1, "index_lists": []}],
 "compartments": [{"name": "Soil", "initial": "1", "index_lists": ["Radionuclides", "Zone"]},
                  {"name": "Water", "initial": "0", "index_lists": ["Radionuclides", "Zone"]}],
 "transfers": [{"name": "Leach", "from": "Soil", "to": "Water", "rate": "k_leach / Kd", "index_lists": ["Radionuclides", "Zone"]}]}""")

model("algebra", """{"name": "algebra", "simulation": $(sim("\"min_change_time\": 0.7")),
 "parameters": [{"name": "k", "value": 0.1}, {"name": "c", "value": 0.05}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}, {"name": "C", "initial": "0"}],
 "expressions": [{"name": "E1", "equation": "k * 2"}, {"name": "E2", "equation": "E1 + c"}, {"name": "F", "equation": "k * (1 + 0.1 * time)"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "E2"}, {"name": "BC", "from": "B", "to": "C", "rate": "F"}]}""")

model("derived", """{"name": "derived", "simulation": {"start_time": 0, "end_time": 100, "output_points": 11, "spacing": "linear",
  "solver": "ndf", "rtol": 1e-7, "time_unit": "year"},
 "parameters": [{"name": "k", "value": 0.05}, {"name": "s", "value": 2}],
 "compartments": [{"name": "A", "initial": "100"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k"}, {"name": "Bout", "from": "B", "to": null, "rate": "0.01"}],
 "expressions": [{"name": "Flux", "equation": "k * A * s"}],
 "derived": [{"name": "PeakB", "kind": "max", "of": "B"}, {"name": "WhenB", "kind": "time_of_max", "of": "B"},
             {"name": "B at 33", "kind": "at_time", "of": "B", "at": 33}, {"name": "Released", "kind": "integral", "of": "Flux"},
             {"name": "Mean10", "kind": "period_mean", "of": "Flux", "period": 10}, {"name": "Nowhere", "kind": "max", "of": "Not a series"}]}""")

model("no states", """{"name": "no states", "simulation": $SIM,
 "parameters": [{"name": "a", "value": 1}, {"name": "b", "value": 0.5}],
 "lookups": [{"name": "T", "points": [[0, 1], [10, 3]], "interpolation": "linear"}],
 "expressions": [{"name": "Y", "equation": "a * T * time + b"}], "compartments": [], "transfers": [], "inflows": []}""")

model("event", """{"name": "event", "simulation": $SIM,
 "parameters": [{"name": "t_ev", "value": 5}, {"name": "k", "value": 0.05}, {"name": "share", "value": 0.5}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k"}],
 "events": [{"name": "Spill", "timing": "at", "at": "t_ev", "actions": [{"kind": "move", "from": "A", "to": "B", "fraction": "share"}]}]}""")

# A stiff decay with an explicit solver and a budget of steps: past a rate the run gives up.
model("budget", """{"name": "budget", "simulation": $(replace(sim("\"max_steps\": 60"), "\"ndf\"" => "\"dp45\"")),
 "parameters": [{"name": "k", "value": 1}],
 "compartments": [{"name": "A", "initial": "1"}, {"name": "B", "initial": "0"}],
 "transfers": [{"name": "AB", "from": "A", "to": "B", "rate": "k"}]}""")

model("nan series", """{"name": "nan series", "simulation": $SIM,
 "parameters": [{"name": "k", "value": 0.2}, {"name": "z", "value": 0}],
 "compartments": [{"name": "A", "initial": "1"}],
 "transfers": [{"name": "Out", "from": "A", "to": null, "rate": "k"}],
 "expressions": [{"name": "Ratio", "equation": "z / z + A"}, {"name": "Half", "equation": "if(time < 5, z / z, A)"}]}""")

"""The far-field example on two cells of each kind (julia/tools/analysis_fixtures.py)."""
function small_farfield()
    m = K.jcopy(examples_raw["farfield"])
    ff = m["farfields"][1]
    ff["n_f"] = 2
    ff["n_m"] = 2
    ff["grid"] = "matched"
    return m
end
push!(models, ("far field", small_farfield()))

models_json = K.JDict(name => m for (name, m) in models)

# --- reading_of and variables_of ----------------------------------------------------------------------------------

"""Targets for every series of a run, read at the peak, at the end and in the middle, and odd ones on its first."""
function targets_for(labels, t)
    out = Any[]
    mid = t[1] + 0.37 * (t[end] - t[1])
    for l in labels
        push!(out, J("output" => l, "when" => "peak"), J("output" => l, "when" => "end"), J("output" => l, "when" => "at", "time" => mid))
    end
    isempty(labels) && return out
    l = labels[1]
    push!(out, J("output" => l, "time" => t[min(3, end)]), J("output" => l, "when" => "at", "time" => -1e9),
          J("output" => l, "when" => "at", "time" => 1e30), J("output" => l, "when" => "at", "time" => "abc"),
          J("output" => l, "when" => "at", "time" => nothing), J("output" => l, "when" => "at"), J("output" => l, "when" => "PEAK"),
          J("output" => l, "when" => nothing, "time" => string(t[end])), J("output" => l, "when" => Any["peak"]),
          J("output" => l, "time" => (t[1] + t[min(2, end)]) / 2), J("when" => "peak"), J("output" => 5, "when" => "peak"),
          J("output" => "nope", "when" => "end"), J("output" => "", "when" => "end"), "a target", nothing, Any[l])
    return out
end

readings = Any[]
variables = Any[]
function reading_case(name, m)
    targets = try
        proj = K.Project(m)
        res = K.run_project(proj; system=K.build_system(proj), on_grid=true)
        targets_for([o["label"] for o in K.outputs(res)], res.t)
    catch e
        e isa InterruptException && rethrow()
        Any[J("output" => "A", "when" => "end")]
    end
    push!(readings, J("name" => name, "targets" => targets))
    push!(variables, J("name" => name))
end
for (name, m) in models
    reading_case(name, m)
end
for ex in examples
    ex == "farfield" && continue
    reading_case("example " * ex, examples_raw[ex])
end

# --- the calibrations -------------------------------------------------------------------------------------------

calibrations = Any[]
cal(name, model_, o...) = push!(calibrations, J("name" => name, (model_ isa AbstractString && haskey(models_json, model_) ? "model" : "example") => model_,
                                                 "options" => J(o...)))
T(output; o...) = J("output" => output, (String(k) => v for (k, v) in o)...)
V(key; o...) = J("key" => key, (String(k) => v for (k, v) in o)...)

# The Python package's cases (julia/tools/analysis_fixtures.py).
cal("exp-nelder", "exponential-decay", "method" => "nelder", "maxEvals" => 60,
    "variables" => [V("k"; lower=0.1, upper=3, space="linear", start=nothing)], "targets" => [T("y"; when="at", time=2, value=0.2, scale="relative")])
cal("exp-lm", "exponential-decay", "method" => "lm", "maxEvals" => 60,
    "variables" => [V("k"; lower=0.1, upper=3, space="log"), V("y0"; lower=0.5, upper=2)],
    "targets" => [T("y"; when="at", time=2, value=0.2), T("y"; when="end", value=1e-4, scale="log")])
for seed in (3, 1, 9, "4", nothing)
    cal("exp-de seed $(repr(seed))", "exponential-decay", "method" => "de", "maxEvals" => 50, "seed" => seed,
        "variables" => [V("k"; lower=0.1, upper=3), V("y0"; lower=0.5, upper=2, start=1.5)],
        "targets" => [T("y"; when="peak", value=1.2, weight=2), T("y"; when="at", time=5, value=0.01, scale="absolute")])
end
cal("mm-nelder", "michaelis-menten", "method" => "nelder", "maxEvals" => 40,
    "variables" => [V("kf"; lower=0.1, upper=10, space="log"), V("kcat"; lower=0.05, upper=5, space="log")],
    "targets" => [T("P"; when="at", time=100, value=3), T("S"; when="at", time=300, value=1)])
cal("four-lm", "four-compartment", "method" => "lm", "maxEvals" => 30,
    "variables" => [V("p12[Fo-42]"; lower=1e-7, upper=1e-3, space="log"), V("p23[Fo-42]"; lower=1e-7, upper=1e-3, space="log")],
    "targets" => [T("C2 [Fo-42]"; when="peak", value=2e9, scale="log"), T("C3 [Fo-42]"; when="end", value=1e4, scale="log")])
cal("four-unknown-method", "four-compartment", "method" => "simplex", "maxEvals" => 12,
    "variables" => [V("p13[Fo-42]"; lower=1e-7, upper=1e-3, space="nonsense")],
    "targets" => [T("nothere"; when="peak", value=2), T("C4 [Fo-42]"; when="peak", value=1e9)])

# More of the bundled examples, each method.
cal("lotka nelder", "lotka-volterra", "method" => "nelder", "maxEvals" => 40,
    "variables" => [V("alpha"; lower=0.5, upper=2), V("beta"; lower=0.1, upper=1, space="log")],
    "targets" => [T("Prey"; when="at", time=10, value=5), T("Predator"; when="peak", value=4)])
cal("sir lm", "sir-epidemic", "method" => "lm", "maxEvals" => 40,
    "variables" => [V("beta"; lower=0.05, upper=1, space="log"), V("gamma"; lower=0.01, upper=0.5)],
    "targets" => [T("I"; when="peak", value=300), T("R"; when="end", value=800, weight=0.5)])
cal("biosphere nelder", "biosphere", "method" => "nelder", "maxEvals" => 25,
    "variables" => [V("leachRate[I-129]"; lower=1e-6, upper=1e-3, space="log"), V("geoTransit"; lower=1e-5, upper=1e-2, space="log")],
    "targets" => [T("Well [I-129]"; when="peak", value=2e7, scale="log"), T("Well [I-129]"; when="end", value=1000, scale="log")])
cal("lookup de", "lookup-driver", "method" => "de", "maxEvals" => 30, "seed" => 2,
    "variables" => [V("V_rego"; lower=0.5, upper=5), V("k_sed"; lower=1e-4, upper=1e-1, space="log")],
    "targets" => [T("Dose [I-129]"; when="peak", value=1e-9, scale="log")])
cal("recorders nelder", "recorders", "method" => "nelder", "maxEvals" => 20,
    "variables" => [V("k_out[Cs-137]"; lower=0.01, upper=1, space="log")],
    "targets" => [T("Peak_dose [Cs-137]"; when="end", value=1e-6, scale="log")])
cal("scenarios lm", "scenarios", "method" => "lm", "maxEvals" => 25,
    "variables" => [V("Runoff"; lower=0.01, upper=1), V("Flush"; lower=0.01, upper=2, space="log")],
    "targets" => [T("Peak_dose"; when="end", value=2e-7, scale="log"), T("Lake"; when="at", time=150, value=0.5)])
cal("decay-chain none", "decay-chain", "variables" => [V("x"; lower=0, upper=1)], "targets" => [T("Waste [Pu-241]"; value=1)])
cal("far field nelder", "far field", "method" => "nelder", "maxEvals" => 10,
    "variables" => [V("leach_rate[U-234]"; lower=1e-5, upper=1e-2, space="log")],
    "targets" => [T("Well [U-234]"; when="peak", value=1e-3, scale="log")])
cal("robertson lm", "robertson", "method" => "lm", "maxEvals" => 15,
    "variables" => [V("k1"; lower=0.01, upper=0.1, space="log")], "targets" => [T("B"; when="peak", value=3e-5, scale="log")])
cal("bouncing nelder", "bouncing-ball", "method" => "nelder", "maxEvals" => 20,
    "variables" => [V("g"; lower=5, upper=15), V("v0"; lower=0, upper=10)], "targets" => [T("Height"; when="peak", value=8)])
cal("waste de", "waste-packages", "method" => "de", "maxEvals" => 12, "seed" => 5,
    "variables" => [V("matrix_rate"; lower=1e-8, upper=1e-4, space="log")],
    "targets" => [T("NearField [Cs-137]"; when="at", time=1e5, value=1e-3, scale="log")])
cal("post nelder", "post-processing", "method" => "nelder", "maxEvals" => 15,
    "variables" => [V("DC[I-129]"; lower=1e-10, upper=1e-6, space="log")], "targets" => [T("Dose_total"; when="peak", value=1e-5, scale="log")])
cal("van der pol lm", "van-der-pol", "method" => "lm", "maxEvals" => 20,
    "variables" => [V("mu"; lower=0.2, upper=3)], "targets" => [T("x"; when="at", time=10, value=1)])
cal("brusselator de", "brusselator", "method" => "de", "maxEvals" => 25, "seed" => 8,
    "variables" => [V("A"; lower=0.5, upper=2), V("B"; lower=1, upper=4)], "targets" => [T("X"; when="peak", value=3), T("Y"; when="end", value=2)])

# Made-up models: every kind of target, of variable and of setting.
const DT = [T("B"; when="at", time=4, value=2.5), T("Flux"; when="peak", value=1.2), T("A"; when="end", value=0.4, scale="log")]
for method in ("nelder", "lm", "de")
    cal("decay $method", "decay", "method" => method, "maxEvals" => 50, "variables" => [V("k"; lower=0.01, upper=2), V("a0"; lower=1, upper=10)],
        "targets" => DT)
    cal("decay $method log", "decay", "method" => method, "maxEvals" => 50,
        "variables" => [V("k"; lower=0.01, upper=2, space="log"), V("k2"; lower=1e-3, upper=1, space="log")], "targets" => DT)
    cal("corner $method", "corner", "method" => method, "maxEvals" => 40, "variables" => [V("k"; lower=0, upper=2), V("s"; lower=0.5, upper=2)],
        "targets" => [T("B"; when="end", value=0.9), T("A"; when="at", time=1, value=0.6)])
end
for seed in (1, 0, "7", 2.5, -1, true)
    cal("corner de seed $(repr(seed))", "corner", "method" => "de", "maxEvals" => 30, "seed" => seed,
        "variables" => [V("k"; lower=0.2, upper=1.5)], "targets" => [T("B"; when="end", value=0.95)])
end
cal("decay every kind of target", "decay", "maxEvals" => 25, "variables" => [V("k"; lower=0.01, upper=2)],
    "targets" => Any[T("B"; when="at", time=4, value=2.5), T("B"; when="at", time=4.4, value=2.5, scale="absolute"),
                     T("B"; when="at", time=-3, value=0.1), T("B"; when="at", time=1e9, value=4), T("B"; when="at", time="abc", value=0.1),
                     T("B"; when="at", value=0.1), T("A"; when="peak", value="5"), T("A"; when="end", value=0.4, scale=Any["log"]),
                     T("A"; when="end", value=0.4, scale="nonsense", weight="2"), T("Flux"; when="end", value=0.1, weight=4),
                     T("Flux"; when="peak", value=0.1, weight=0), T("Flux"; when="peak", value=0.1, weight=-1),
                     T("Flux"; when="peak", value=0.1, weight=true), T("Twice"; when="end", value=14), T("k"; when="end", value=0.25),
                     T("nothere"; when="end", value=1), T(5; when="end", value=1), T(""; value=1), nothing, "B", T(Any["B"]; when="end", value=1),
                     T("B"; when="end", value=0), T("B"; when="end", value=-2, scale="log"), J("output" => "B", "when" => "end")])
cal("decay a target that cannot be met", "decay", "maxEvals" => 30, "variables" => [V("k"; lower=0.01, upper=2)],
    "targets" => [T("B"; when="end", value=-5, scale="log")])
cal("decay unmet, budget not a number", "decay", "maxEvals" => "abc", "variables" => [V("k"; lower=0.01, upper=2)],
    "targets" => [T("B"; when="end", value=-5, scale="log")])
cal("decay out of reach", "decay", "maxEvals" => 30, "variables" => [V("k"; lower=0.01, upper=2)],
    "targets" => [T("B"; when="end", value=50)])
cal("decay a target with no number", "decay", "maxEvals" => 30, "variables" => [V("k"; lower=0.01, upper=2)],
    "targets" => [T("B"; when="end", value="abc"), T("A"; when="end", value=0.4)])
cal("decay a target of zero", "decay", "maxEvals" => 30, "variables" => [V("k"; lower=0.01, upper=2)],
    "targets" => [T("B"; when="at", time=0, value=0, scale="absolute"), T("A"; when="end", value=0.4)])
# A misfit too large to square: every point's objective is Infinity, none is the best, and nothing comes back.
cal("decay a misfit too large to square", "decay", "maxEvals" => 12, "variables" => [V("k"; lower=0.01, upper=2)],
    "targets" => [T("B"; when="end", value=-1e200, scale="absolute")])
cal("decay starts", "decay", "maxEvals" => 20,
    "variables" => Any[V("k"; lower=0.01, upper=2, start=5), V("a0"; lower=1, upper=10, start="3"), V("k2"; lower=0.01, upper=1, start=nothing),
                       V("c"; lower=1, upper=9, start="abc")], "targets" => DT)
cal("decay starts from values written oddly", "decay", "maxEvals" => 15,
    "variables" => Any[V("blank"; lower=-1, upper=1), V("listed"; lower=0.5, upper=3), V("k"; lower=0.5, upper=0.6, space="log")], "targets" => DT)
cal("decay the same key twice", "decay", "maxEvals" => 20, "variables" => [V("k"; lower=0.01, upper=2), V("k"; lower=0.5, upper=1)], "targets" => DT)
cal("decay bounds as text", "decay", "maxEvals" => 20, "variables" => [V("k"; lower="0.01", upper="2"), V("a0"; lower=nothing, upper=true)],
    "targets" => DT)
for budget in (nothing, 3, "15", 12.5, 12.4, -5, true)
    cal("decay budget $(repr(budget))", "decay", "maxEvals" => budget, "variables" => [V("k"; lower=0.01, upper=2)], "targets" => DT[1:1])
end
for method in ("lm", "de", "nelder", nothing, 5, "toString", Any["lm"], "LM")
    cal("decay method $(repr(method))", "decay", "method" => method, "maxEvals" => 20, "variables" => [V("k"; lower=0.01, upper=2)],
        "targets" => DT[1:2])
end
cal("decay stopped before it starts", "decay", "abort" => 0, "variables" => [V("k"; lower=0.01, upper=2)], "targets" => DT)
cal("decay stopped", "decay", "abort" => 7, "variables" => [V("k"; lower=0.01, upper=2), V("a0"; lower=1, upper=10)], "targets" => DT)
cal("decay lm stopped", "decay", "method" => "lm", "abort" => 5, "variables" => [V("k"; lower=0.01, upper=2)], "targets" => DT)
cal("decay de stopped", "decay", "method" => "de", "abort" => 12, "variables" => [V("k"; lower=0.01, upper=2)], "targets" => DT)
cal("indexed", "indexed", "maxEvals" => 30, "variables" => [V("Kd[Cs-137][a]"; lower=0.5, upper=5, space="log"), V("k_leach"; lower=0.01, upper=1)],
    "targets" => [T("Water [Cs-137, a]"; when="end", value=0.3), T("Soil [Sr-90, b]"; when="at", time=5, value=0.9)])
cal("algebra lm", "algebra", "method" => "lm", "maxEvals" => 30, "variables" => [V("k"; lower=0.01, upper=1), V("c"; lower=0, upper=0.5)],
    "targets" => [T("C"; when="end", value=0.2), T("E2"; when="end", value=0.3), T("F"; when="at", time=6, value=0.15)])
cal("derived nelder", "derived", "maxEvals" => 30, "variables" => [V("k"; lower=0.01, upper=0.2), V("s"; lower=1, upper=3)],
    "targets" => [T("PeakB"; when="end", value=40), T("B at 33"; when="end", value=30), T("Released"; when="end", value=80, scale="log"),
                  T("Mean10"; when="peak", value=8), T("WhenB"; when="end", value=60), T("Nowhere"; when="end", value=1)])
cal("no states", "no states", "maxEvals" => 25, "variables" => [V("a"; lower=0, upper=3), V("b"; lower=-1, upper=1)],
    "targets" => [T("Y"; when="at", time=5, value=7), T("Y"; when="end", value=31, scale="absolute")])
cal("event", "event", "maxEvals" => 30, "variables" => [V("t_ev"; lower=1, upper=9), V("share"; lower=0, upper=1)],
    "targets" => [T("B"; when="at", time=6, value=0.6), T("A"; when="end", value=0.3)])
cal("budget of steps", "budget", "maxEvals" => 30, "variables" => [V("k"; lower=0.1, upper=1000, space="log")],
    "targets" => [T("B"; when="at", time=1, value=0.9)])
cal("nan series", "nan series", "maxEvals" => 20, "variables" => [V("k"; lower=0.01, upper=1)],
    "targets" => [T("Ratio"; when="peak", value=1), T("Half"; when="peak", value=0.5), T("Half"; when="end", value=0.3)])

# Refusals, in the Julia package's words.
for (name, targets) in (("no targets", Any[]), ("a target with no output", Any[T(""; value=1)]), ("targets null", nothing),
                        ("targets a text", "abc"), ("targets a number", 5), ("targets a dictionary", J("output" => "B")))
    cal("refused: $name", "decay", "variables" => [V("k"; lower=0, upper=1)], "targets" => targets)
end
for (name, vars) in (("no variables", Any[]), ("variables null", nothing), ("variables an empty text", ""), ("variables an empty dictionary", J()),
                     ("variables a text", "k"), ("variables a number", 5), ("variables a dictionary", J("key" => "k")),
                     ("an unknown key", [V("kk"; lower=0, upper=1)]), ("a key that is a number", [V(5; lower=0, upper=1)]),
                     ("no key", Any[J("lower" => 0, "upper" => 1)]), ("a variable that is a text", Any["k"]),
                     ("lower above upper", [V("k"; lower=2, upper=1)]), ("no bounds", [V("k")]), ("equal bounds", [V("k"; lower=1, upper=1)]),
                     ("a bound that is no number", [V("k"; lower=0, upper="x")]), ("log from 0", [V("k"; lower=0, upper=1, space="log")]),
                     ("log below 0", [V("k"; lower=-1, upper=1, space=Any["log"])]), ("a dictionary key", [V(J("a" => 1); lower=0, upper=1)]))
    cal("refused: $name", "decay", "variables" => vars, "targets" => DT)
end
cal("refused: no targets before no variables", "decay", "variables" => Any[], "targets" => Any[])
# Infinite bounds are a range (Infinity is above -Infinity): the simplex steps to Infinity, then to points that are no
# number, each answered from memory, and the search would go on until stopped (the fault above).
cal("decay infinite bounds", "decay", "maxEvals" => 30, "abort" => 4000, "variables" => [V("k"; lower="-Infinity", upper="Infinity")],
    "targets" => DT)
cal("refused: a model that will not build", "decay", "variables" => [V("k"; lower=0, upper=1)], "targets" => DT, "break" => true)

# --- the service --------------------------------------------------------------------------------------------------

service_dir = mktempdir()
function service_case(id, model_text, options)
    path = joinpath(service_dir, id * ".json")
    events = Any[]
    job = J("id" => id, "kind" => "calibrate", "model" => model_text, "options" => options, "out" => path)
    K._service_job(job, e -> push!(events, e), () -> false)
    said_ = String[e["event"] == "stage" ? "stage:" * e["stage"] : e["event"] for e in events if e["event"] != "progress"]
    last = events[end]
    text = isfile(path) ? replace(read(path, String), r"\"ms\":[0-9]+" => "\"ms\":0") : ""
    # Every step's detail as the service builds it, from a calibration of the same job here: what the service says
    # is some of them, every one the step its count names.
    steps = String[]
    try
        o = options isa AbstractDict ? options : K.JDict()
        K.calibrate(K.from_json(model_text); targets=get(o, "targets", nothing), variables=get(o, "variables", nothing),
                    method=get(o, "method", nothing), max_evals=get(o, "maxEvals", nothing), seed=get(o, "seed", nothing),
                    on_progress=p -> push!(steps, K.json_text(K.OrderedDict{String,Any}("evals" => p.evals, "fx" => p.fx, "best" => p.best,
                                                                                       "values" => p.values); indent=0)))
    catch e
        e isa InterruptException && rethrow()
    end
    for e in events
        e["event"] == "progress" || continue
        d = K.json_text(e["detail"]; indent=0)
        n = e["detail"]["evals"]
        (1 <= n <= length(steps) && steps[n] == d) || error("$id: the service said $d, the step $n is $(get(steps, n, "-"))")
    end
    return J("id" => id, "model" => model_text, "options" => options, "events" => said_, "name" => get(last, "name", nothing),
             "message" => get(last, "message", nothing), "hint" => get(last, "hint", nothing),
             "out" => isempty(text) ? "" : kept(text), "steps" => Any[kept(s) for s in steps])
end
ex_text(ex) = read(joinpath(examples_dir, ex * ".json"), String)
DT_EXP = [T("y"; when="at", time=2, value=0.2)]
service = Any[service_case("cal-exp", ex_text("exponential-decay"),
                           J("targets" => DT_EXP, "variables" => [V("k"; lower=0.1, upper=3)], "method" => "nelder", "maxEvals" => 40, "seed" => 1)),
              service_case("cal-lm", ex_text("four-compartment"),
                           J("targets" => [T("C2 [Fo-42]"; when="peak", value=2e9, scale="log")],
                             "variables" => [V("p12[Fo-42]"; lower=1e-7, upper=1e-3, space="log")], "method" => "lm", "maxEvals" => 20)),
              service_case("cal-de", ex_text("exponential-decay"),
                           J("targets" => DT_EXP, "variables" => [V("k"; lower=0.1, upper=3), V("y0"; lower=0.5, upper=2)], "method" => "de",
                             "maxEvals" => 30, "seed" => 5)),
              service_case("cal-corner", K.json_text(models_json["corner"]),
                           J("targets" => [T("B"; when="end", value=0.9)], "variables" => [V("k"; lower=0, upper=2)], "maxEvals" => 25)),
              service_case("cal-huge", K.json_text(models_json["decay"]),
                           J("targets" => [T("B"; when="end", value=-1e200, scale="absolute")], "variables" => [V("k"; lower=0.01, upper=2)],
                             "maxEvals" => 12)),
              service_case("cal-unmet", K.json_text(models_json["decay"]),
                           J("targets" => [T("B"; when="end", value=-5, scale="log")], "variables" => [V("k"; lower=0.01, upper=2)])),
              service_case("cal-none", ex_text("exponential-decay"), J("targets" => Any[], "variables" => [V("k"; lower=0.1, upper=3)])),
              service_case("cal-unknown", ex_text("exponential-decay"), J("targets" => DT_EXP, "variables" => [V("kk"; lower=0.1, upper=3)])),
              service_case("cal-range", ex_text("exponential-decay"), J("targets" => DT_EXP, "variables" => [V("k"; lower=3, upper=0.1)])),
              service_case("cal-empty", ex_text("exponential-decay"), J()),
              service_case("cal-text", ex_text("exponential-decay"), "targets"),
              service_case("cal-bad", "{not json", J("targets" => DT_EXP, "variables" => [V("k"; lower=0.1, upper=3)]))]

# --- written ------------------------------------------------------------------------------------------------------

back = K.parse_json(K.json_text(K.JDict("models" => models_json, "optimise" => optimise, "calibrations" => calibrations, "readings" => readings,
                                        "variables" => variables, "objective" => objective); indent=0))
models_json, optimise, calibrations, readings, variables, objective =
    back["models"], back["optimise"], back["calibrations"], back["readings"], back["variables"], back["objective"]
model_of(c) = haskey(c, "example") ? examples_raw[c["example"]] : models_json[c["model"]]
const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
texts = String[]
function record!(c, text, head)
    push!(texts, "## $head\n$text")
    c["out"] = kept(text)
end

"""A signal that answers true from its `after + 1`-th call on, or none."""
signal_of(o) = (after = get(o, "abort", nothing); after === nothing ? nothing : (calls = Ref(0); () -> (calls[] += 1; calls[] > after)))
step_line(p) = "$(p.evals) $(bits(p.fx)) $(bits(p.best)) $(nums(p.x)) $(p.best_x === nothing ? "none" : nums(p.best_x))"
result_line(out) = "x=$(out.x === nothing ? "none" : nums(out.x)) fx=$(bits(out.fx)) evals=$(out.evals) reason=$(out.reason)"

for c in optimise
    o = c["options"]
    steps = String[]
    on_step = p -> push!(steps, step_line(p))
    signal = signal_of(o)
    lower, upper = get(o, "lower", nothing), get(o, "upper", nothing)
    max_evals, tol = get(o, "max_evals", nothing), get(o, "tol", nothing)
    out = said(() -> begin
        r = if c["method"] == "nelder"
            K.nelder_mead(FUNCTIONS[c["fn"]], c["start"]; lower, upper, max_evals, tol, on_step, signal)
        elseif c["method"] == "lm"
            K.levenberg_marquardt(RESIDUALS[c["fn"]], c["start"]; lower, upper, max_evals, tol, on_step, signal)
        else
            K.differential_evolution(FUNCTIONS[c["fn"]]; lower, upper, start=get(o, "start", nothing), pop_size=get(o, "pop_size", 0), max_evals,
                                     seed=get(o, "seed", 1), F=get(o, "F", nothing), CR=get(o, "CR", nothing), on_step, signal)
        end
        result_line(r)
    end)
    record!(c, join([steps; out], "\n"), "optimise $(c["method"]) $(c["fn"]) $(K.json_text(c["start"]; indent=0)) $(K.json_text(o; indent=0))")
end

named(name) = haskey(models_json, name) ? models_json[name] : examples_raw[replace(name, "example " => "")]
for c in objective
    o = K.objective_of(c["readings"], c["targets"])
    c["out"] = bits(o.objective) * "|" * nums(o.residuals)
end
for c in readings
    m = named(c["name"])
    record!(c, said(() -> begin
        proj = K.Project(m)
        res = K.run_project(proj; system=K.build_system(proj), on_grid=true)
        nums([K.reading_of(res, t) for t in c["targets"]])
    end), "readings $(c["name"])")
end
for c in variables
    record!(c, said(() -> tdump(K.variables_of(K.Project(named(c["name"]))))), "variables $(c["name"])")
end

for c in calibrations
    o = c["options"]
    m = model_of(c)
    get(o, "break", false) === true && (m = K.jcopy(m); m["transfers"][1]["rate"] = "k *")
    steps = String[]
    on_progress = p -> push!(steps, "$(p.evals) $(bits(p.fx)) $(bits(p.best)) $(p.values === nothing ? "none" : nums(p.values))")
    took = @elapsed out = said(() -> begin
        r = K.calibrate(K.Project(m); targets=get(o, "targets", nothing), variables=get(o, "variables", nothing), method=get(o, "method", nothing),
                        max_evals=get(o, "maxEvals", nothing), seed=get(o, "seed", nothing), on_progress, signal=signal_of(o))
        delete!(r, "ms")
        tdump(r)
    end)
    took > 5 && println(stderr, c["name"], ": ", round(took; digits=1), " s")
    record!(c, join([steps; out], "\n"), "calibrate $(c["name"]) $(K.json_text(o; indent=0))")
end

isempty(DUMPS) || write(joinpath(DUMPS, "calibrate.julia.txt"), join(texts, "\n\n"))
path = joinpath(@__DIR__, "..", "tests", "fixtures", "calibrate.json")
write(path, K.json_text(K.JDict("models" => models_json, "optimise" => optimise, "objective" => objective, "solve" => solve, "keys" => point_keys,
                                "lookups" => lookups, "scales" => scales, "spaces" => spaces, "readings" => readings, "variables" => variables,
                                "calibrations" => calibrations, "service" => service); indent=0))
refused = count(c -> startswith(c["out"], "=error:"), calibrations)
println(path, ": ", length(optimise), " optimisations, ", length(readings), " models read, ", length(calibrations), " calibrations (", refused,
        " refused), ", length(service), " service jobs")
