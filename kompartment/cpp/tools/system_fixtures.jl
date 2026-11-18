# Writes tests/fixtures/system.json: what the Julia engine's built systems work
# out, for the C++ engine's tests to compare with (tests/test_system.cpp).
#
#     julia --project=../julia tools/system_fixtures.jl
#
# Every model of tests/fixtures/builder.json that is built (run
# tools/builder_fixtures.jl first), with parity on: the initial state, the
# slots that never move, and at a few instants and states the derivative and
# every algebraic slot -- each as a hash of its numbers' bits. With
# KOMPARTMENT_FIXTURE_DUMPS set, the numbers themselves are written there
# (`<name>.system.julia.txt`).

using Kompartment
const K = Kompartment
K.set_parity!(true)

bits(x::Float64) = string(reinterpret(UInt64, x); base=16, pad=16)
function fnv(text::String)
    h = 0xcbf29ce484222325
    for b in codeunits(text)
        h = (h ⊻ b) * 0x100000001b3
    end
    return string(h; base=16, pad=16)
end
# A NaN is a NaN whatever its bits.
nums(v) = join((isnan(x) ? "nan" : bits(Float64(x)) for x in v), ",")

"""The states the derivative is asked at: the initial one, and two made from it."""
function states(y0)
    n = length(y0)
    return [copy(y0), [y0[i] * (1.0 + 0.25 * ((i * 7) % 5)) + 0.5 * ((i * 3) % 4) for i in 1:n],
            [abs(y0[i]) * 0.3 + 1e-3 * i for i in 1:n]]
end

const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
examples = joinpath(@__DIR__, "..", "..", "examples")
cases = Any[]
for c in K.parse_json(read(joinpath(@__DIR__, "..", "tests", "fixtures", "builder.json"), String))["cases"]
    haskey(c, "sections") || continue
    model = haskey(c, "example") ? K.parse_json(read(joinpath(examples, c["example"] * ".json"), String)) : c["model"]
    sys = K.build_system(K.Project(model))
    out = K.JDict()
    y0 = K.initial_state(sys)
    out["y0"] = nums(y0)
    # (Only the slots that never move: the others hold whatever was last worked out.)
    out["invariant"] = nums(Float64[sys.X[i] for i in 1:sys.nalg if sys.slot_class[i] == 0])
    K.prime_recorders!(sys, sys.start_time, y0)
    t0, t1 = sys.start_time, sys.end_time
    for (k, (t, y)) in enumerate(zip((t0, t0 + 0.37 * (t1 - t0), t1), states(y0)))
        X = copy(K.evaluate_algebraic!(sys, t, y))
        dy = K.dydt(sys, t, y)
        out["X$k"] = nums(X)
        out["dy$k"] = nums(dy)
    end
    isempty(DUMPS) || write(joinpath(DUMPS, "$(c["name"]).system.julia.txt"), join(("## $k\n$(replace(v, "," => "\n"))" for (k, v) in out), "\n"))
    row = haskey(c, "example") ? K.JDict("name" => c["name"], "example" => c["example"]) : K.JDict("name" => c["name"], "model" => model)
    row["values"] = K.JDict(k => fnv(v) for (k, v) in out)
    push!(cases, row)
end
path = joinpath(@__DIR__, "..", "tests", "fixtures", "system.json")
write(path, K.json_text(K.JDict("cases" => cases); indent=0))
println(path, ": ", length(cases), " models")
