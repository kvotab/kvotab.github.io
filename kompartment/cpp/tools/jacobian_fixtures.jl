# Writes tests/fixtures/jacobian.json: what the Julia engine makes of df/dy, for
# the C++ engine's tests to compare with (tests/test_jacobian.cpp).
#
#     julia --project=../julia tools/jacobian_fixtures.jl
#
# Every model of tests/fixtures/builder.json that is built (run
# tools/builder_fixtures.jl first), and models made up here to reach every
# tangent rule and every refusal, with parity on: whether the Jacobian is
# there, constant, free of the state, and why not; its pattern and colouring;
# the plan made of it directly (a model refused for an infinite entry at the
# start still has one); and the values the plan writes at a few instants and
# states, with the gradients of the slots they are assembled from -- each as a
# hash of its text, the numbers as their bits. With
# KOMPARTMENT_FIXTURE_DUMPS set, the text itself is written there
# (`<name>.jacobian.julia.txt`).

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
ints(v) = join(v, ",")

"""Where the Jacobian is asked for: the initial state at the start, two states made from it
at later instants, and -- after the second has been recorded as a step taken -- the
initial one again at another instant, so that a block that remembers has something to
remember that is not what it reads."""
function points(sys, y0)
    n = length(y0)
    t0, t1 = sys.start_time, sys.end_time
    return [(t0, copy(y0)),
            (t0 + 0.37 * (t1 - t0), [y0[i] * (1.0 + 0.25 * ((i * 7) % 5)) + 0.5 * ((i * 3) % 4) for i in 1:n]),
            (t1, [abs(y0[i]) * 0.3 + 1e-3 * i for i in 1:n]),
            (t0 + 0.6 * (t1 - t0), copy(y0))]
end

function jacobian_out(model)
    sys = K.build_system(K.Project(model))
    out = K.JDict()
    j = sys.jacobian
    if !(j isa K.JacobianInfo)
        out["info"] = "none: $(j.reason)"
        return out
    end
    an0 = j.analytic
    out["info"] = "available=$(j.available) constant=$(j.constant) state_free=$(an0 === nothing ? "-" : an0.state_free) " *
                  "reason=$(something(j.reason, "")) budget_rows=$(something(j.budget_rows, "")) nnz=$(j.nnz) colours=$(j.colours)"
    out["pattern"] = ints(j.pattern.colptr .- 1) * "|" * ints(j.pattern.rowval .- 1)
    out["groups"] = join((ints(g .- 1) for g in j.groups), "|")
    an = try
        K.Analytic(sys, j.pattern, K.full_budget(sys))
    catch e
        e isa K.NoDerivative || rethrow()
        out["plan"] = "refused: $(e.what)"
        nothing
    end
    an === nothing && return out
    out["plan"] = "constant=$(an.constant) state_free=$(an.state_free) rows=$(length(an.g_rows)) entries=$(an.g_nnz)"
    y0 = K.initial_state(sys)
    K.prime_recorders!(sys, sys.start_time, y0)
    for (k, (t, y)) in enumerate(points(sys, y0))
        J = zeros(j.nnz)
        out["J$k"] = try
            ok = K.analytic_evaluate!(J, an, t, y)
            # (The gradients of the slots too: an entry of the Jacobian is a sum over many of
            # them, and a last bit lost in one is seldom seen in the sum.)
            out["G$k"] = nums(an.G)
            "$(ok ? 1 : 0):" * nums(J)
        catch e
            e isa InterruptException && rethrow()
            "threw"
        end
        k == 2 && K.store_step!(sys, t, y)
    end
    return out
end

const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
const VERBOSE = !isempty(get(ENV, "KOMPARTMENT_FIXTURE_VERBOSE", ""))
cases = Any[]
function record(name, model; example=nothing, smooth=false)
    out = try
        jacobian_out(model)
    catch e
        (e isa K.BuildError || e isa K.ValidationError) || (println(stderr, "while working out ", name); rethrow())
        println(stderr, "NOT BUILT: ", name, ": ", e.message)
        return
    end
    isempty(DUMPS) || write(joinpath(DUMPS, "$name.jacobian.julia.txt"), join(("## $k\n$(replace(v, "," => "\n"))" for (k, v) in out), "\n"))
    VERBOSE && println(rpad(name, 44), " ", out["info"], "  ::  ", get(out, "plan", ""), "  ", join((get(out, "J$k", "-")[1:1] for k in 1:4), ""))
    row = example === nothing ? K.JDict("name" => name, "model" => model) : K.JDict("name" => name, "example" => example)
    # The lines a person reads are kept as they are; the numbers as hashes.
    row["info"] = out["info"]
    haskey(out, "plan") && (row["plan"] = out["plan"])
    row["values"] = K.JDict(k => fnv(v) for (k, v) in out if k != "info" && k != "plan")
    # `smooth`: the model's derivative is smooth at the points asked, so its Jacobian can be
    # checked against differences there, every entry.
    smooth && (row["smooth"] = true)
    push!(cases, row)
end

examples = joinpath(@__DIR__, "..", "..", "examples")
for c in K.parse_json(read(joinpath(@__DIR__, "..", "tests", "fixtures", "builder.json"), String))["cases"]
    haskey(c, "sections") || continue
    if haskey(c, "example")
        record(c["name"], K.parse_json(read(joinpath(examples, c["example"] * ".json"), String)); example=c["example"])
    else
        record(c["name"], c["model"])
    end
end

# --- models made up to reach every rule ----------------------------------------------------------------
#
# Compartments by nuclide (A, B, B2), by nuclide and zone (Z) and single ones
# (C, D, E; D and E start empty), and for each equation given an expression
# `R<i>` and a transfer whose rate it is: from A to B where the equation is
# by nuclide, from C to D where it is one number -- by turns multiplied by the
# donor and not.

rules_base() = K.parse_json("""{"name":"rules","nuclides":["U-238","U-234","Cs-137"],"simulation":{"end_time":100},
  "index_lists":[{"name":"Zones","indices":["a","b"]}],
  "parameters":[{"name":"k","value":0.1,"index_lists":[]},{"name":"two","value":2,"index_lists":[]},{"name":"three","value":3,"index_lists":[]},
                {"name":"half","value":1.5,"index_lists":[]},{"name":"zero","value":0,"index_lists":[]},
                {"name":"kn","value":1.5,"entries":[{"index":"U-234","value":3},{"index":"Cs-137","value":0.5}]},
                {"name":"kz","value":1,"index_lists":["Zones"],"entries":[{"index":"b","value":2.5}]}],
  "compartments":[{"name":"A","initial":"2 * kn"},{"name":"B","initial":"0.3 + kn"},{"name":"B2","initial":"0"},
                  {"name":"Z","initial":"kz","index_lists":["Radionuclides","Zones"]},
                  {"name":"C","initial":"0.7","index_lists":[]},{"name":"D","initial":"0","index_lists":[]},{"name":"E","initial":"0","index_lists":[]}],
  "expressions":[],"transfers":[],
  "lookups":[{"name":"F","points":[[0,0],[1,1],[3,2],[10,2.5]],"argument":"x","index_lists":[]},
             {"name":"Fx","points":[[0,0],[1,1],[3,2]],"argument":"x","interpolation":"extrapolate","index_lists":[]},
             {"name":"Fb","points":[[0,0],[1,1],[3,2]],"argument":"x","interpolation":"below","index_lists":[]},
             {"name":"Fa","points":[[0,0],[1,1],[3,2]],"argument":"x","interpolation":"above","index_lists":[]},
             {"name":"Fnear","points":[[0,0],[1,1],[3,2]],"argument":"x","interpolation":"nearest","index_lists":[]},
             {"name":"Fc","points":[[0,0],[1,1],[2.5,0.5]],"argument":"x","cyclic":true,"index_lists":[]},
             {"name":"Fs","points":[[0,0],[1,1],[1,3],[4,2]],"argument":"x","index_lists":[]},
             {"name":"F1","points":[[2,5]],"argument":"x","index_lists":[]},
             {"name":"Fn","points":[[0,1],[5,2]],"argument":"x","entries":[{"index":"U-234","points":[[0,3],[2,4],[5,1]]}]},
             {"name":"Ft","points":[[0,1],[50,2],[100,0.5]],"index_lists":[]}]}""")

function rules(f, name, equations; smooth=false)
    m = rules_base()
    for (i, eq) in enumerate(equations)
        scalar = startswith(eq, "1:")
        eq = scalar ? eq[3:end] : eq
        e = K.JDict("name" => "R$i", "equation" => eq)
        scalar && (e["index_lists"] = Any[])
        push!(m["expressions"], e)
        t = scalar ? K.JDict("name" => "T$i", "from" => "C", "to" => "D", "rate" => "R$i", "index_lists" => Any[]) :
            K.JDict("name" => "T$i", "from" => "A", "to" => "B", "rate" => "R$i")
        t["multiply_by_donor"] = isodd(i)
        push!(m["transfers"], t)
    end
    f(m)
    record(name, m; smooth=smooth)
end
rules(name, equations; smooth=false) = rules(m -> nothing, name, equations; smooth=smooth)

# Each built-in with a rule of its own, smooth where it is asked.
rules("rules: roots, exponentials, logarithms", ["abs(A - 2.5) * k", "sqrt(A + B)", "exp(-0.1 * A)", "log(A + 1)", "log10(A + B + 1)", "log2(2 + A)",
                                                 "ln(1 + A * B)", "fabs(B - A)", "1:sqrt(C) + exp(C) * log(C + 2)", "1:log10(C + 1) * log2(C + 1)"]; smooth=true)
rules("rules: trigonometry", ["sin(0.3 * A)", "cos(A * B * 0.1)", "tan(0.05 * A)", "asin(A / (A + 1))", "acos(B / (B + A + 1))", "atan(A - B)",
                              "atan2(A, B)", "atan2(1, A)", "atan2(B, 2)", "hypot(A, B)", "hypot(A, 3)", "hypot(4, B)", "1:sin(C) * cos(C) + atan2(C, C + 1)"]; smooth=true)
rules("rules: hyperbolic", ["sinh(0.2 * A)", "cosh(0.2 * A)", "tanh(A - B)", "asinh(A * B)", "acosh(A + 1.5)", "atanh(A / (A + 2))", "1:tanh(C) + asinh(C) * acosh(C + 2)"]; smooth=true)
rules("rules: erf, ulp, units", ["erf(0.3 * A)", "erfc(0.3 * A - 0.2 * B)", "ulp(A) * 1e15", "ulp(B - A) * 1e15", "bq2mole(A, 4.5) * 1e16", "bq2mole(2e15, A + 1)",
                                 "mole2bq(A * 1e-16, 30)", "mole2bq(1e-16, A + B)", "bq2mole(A * 1e15, B + 1)", "mole2bq(A * 1e-16, B + 1)", "1:erf(C) - erfc(C)"]; smooth=true)
rules("rules: mod and rem", ["mod(A, 0.7)", "mod(5, A + 0.1)", "mod(A, B + 0.01)", "rem(A, 0.7)", "rem(5, A + 0.1)", "rem(A - 3, B + 0.01)", "mod(A, zero)", "rem(A, 0 * k)",
                             "1:mod(C, 0.3) + rem(7, C + 1)"])
rules("rules: a divisor of zero", ["mod(A, B2)", "rem(A, B2)", "1:mod(C, D) + C", "1:rem(C, E)", "mod(3, B2)", "rem(3, B2)"])
rules("rules: ramps and smooth steps", ["rampDown(A, 1, 4)", "rampUp(A, 4, 1)", "rampDown(A * B, kn, 2 * kn + 1)", "rampUp(A, two, three)", "smoothDown(A, 2, 3)",
                                        "smoothUp(A, 2, 3)", "smoothDown(A, kn, kn)", "smoothUp(A + B, 3, 1)", "smoothDown(A, 2, 0.25)", "smoothUp(A - 3, 2, half)",
                                        "1:rampDown(C, 0, 1) + smoothUp(C, 1, 2)", "1:smoothDown(D, 1, 2) * C", "rampUp(B2, 1, 1)", "smoothUp(B2, 0, 2) + smoothDown(A, 0, 2)"])
rules("rules: interpolation over arguments", ["interpolationUseEndValues(A, 0, 0, 1, 2, 5, 3)", "interpolationExtrapolation(A, 0, 0, 1, 2, 5, 3)",
                                              "interpolationUseEndValues(A * B, 0, kn, 2, 2 * kn, 9, 1)", "interpolationExtrapolation(B - A, 0, 0, 1, k)",
                                              "interpolationUseEndValues(A, 1, 5)", "interpolationUseEndValues(A, 3, 1, 1, 2, 2, 7)",
                                              "1:interpolationExtrapolation(C, 0, 1, 1, 3) + interpolationUseEndValues(C, 0, 1, 1, 1, 1, 4, 2, 5)"])
# Powers, with every kind of exponent.
rules("rules: powers by a constant", ["A ^ 0", "A ^ 1", "A ^ 2", "A ^ 0.5", "A ^ 3", "A ^ -1", "A ^ 1.5", "A ^ -0.5", "(A + B) ^ 2.5", "(A * B) ^ 2", "1:C ^ 2 + C ^ 0.5 + C ^ -2",
                                      "power(A, 2)", "power(A, 0.5)", "pow(A, 3)", "power(A, 0)", "power(A, 1)", "power(A + 1, -1)"]; smooth=true)
rules("rules: powers by a parameter", ["A ^ two", "A ^ three", "A ^ half", "A ^ zero", "A ^ kn", "(A + B) ^ kn", "A ^ (kn - 1)", "A ^ (two - 3)", "A ^ k",
                                       "power(A, two)", "power(A, kn)", "power(A, three)", "power(A, half + kn)", "1:C ^ two + C ^ half + power(C, three)"]; smooth=true)
rules("rules: powers of a base that stands still", ["two ^ A", "kn ^ A", "2 ^ (A - B)", "zero ^ A", "(0 - two) ^ A", "power(two, A)", "power(kn, A * 0.5)", "power(3, B)",
                                                    "1:2 ^ C + power(half, C)", "1 ^ A", "(0 - 1) ^ A"])
rules("rules: powers that move at both ends", ["A ^ B", "A ^ A", "(A + 1) ^ (B * 0.5)", "power(A, B)", "power(A, A)", "B2 ^ A", "A ^ B2", "B2 ^ B2", "power(B2, A)",
                                               "power(A, B2)", "1:C ^ C + D ^ C + C ^ D", "(A - 3) ^ B", "(A - 3) ^ 2", "(A - 3) ^ three", "(A - 3) ^ kn"])
# A power worked out by the C library where numpy's short cut (a square root, a square, a
# reciprocal) gives another last bit: the compartment starts at such arguments.
rules("rules: powers where pow is not the short cut", ["Q ^ kq", "Q ^ half", "power(Q, kq)", "power(Q, half)", "Q ^ (kq - 1)", "Q ^ 0.5", "Q ^ two", "Q ^ -1", "Q ^ three",
                                                       "(Q * 1) ^ kq + Q ^ (two - 3)", "power(Q, kq - 1) + power(Q, 0.5)"]) do m
    push!(m["parameters"], K.JDict("name" => "q", "value" => 1.336539, "entries" => Any[K.JDict("index" => "U-234", "value" => 2.171926), K.JDict("index" => "Cs-137", "value" => 1.16506)]))
    push!(m["parameters"], K.JDict("name" => "kq", "value" => 1.5, "entries" => Any[K.JDict("index" => "U-234", "value" => 3), K.JDict("index" => "Cs-137", "value" => 0)]))
    push!(m["compartments"], K.JDict("name" => "Q", "initial" => "q", "handle_decay" => false))
    for t in m["transfers"]
        t["from"] = "Q"
    end
end
# Rules handed a tangent that is not one, so that the order of each rule's products shows.
let g = "(A * B * 0.1 + kn * 0.2)", h = "(A * B * 0.1 + kn * 0.2) / (1 + A * B * 0.1 + kn * 0.2)"
    rules("rules: seeds that are not one",
          ["abs($g - 1)", "sqrt($g)", "exp(-$g)", "log($g)", "log10($g)", "log2($g)", "hypot($g, A)", "hypot(B, $g)", "sin($g)", "cos($g)", "tan($g * 0.3)", "asin($h)", "acos($h)",
           "atan($g)", "sinh($g)", "cosh($g)", "tanh($g)", "asinh($g)", "acosh(1 + $g)", "atanh($h)", "erf($g)", "erfc($g)", "atan2($g, A + B)", "atan2(A - B, $g)", "mod($g, 0.37)",
           "mod(7, $g)", "rem($g, 0.37)", "rem(7, $g)", "ulp($g) * 1e15", "rampDown($g, 0.1, 3)", "rampUp($g, 0.1, 3)", "smoothDown($g, 1.5, 2.5)", "smoothUp($g, kn, 0.7)",
           "interpolationUseEndValues($g, 0, 0, 1, 2, 5, 3)", "interpolationExtrapolation($g, 0, 0, 1, 2, 5, 3)", "bq2mole($g * 1e15, 4.5)", "bq2mole(2e15, $g)",
           "mole2bq($g * 1e-16, 30)", "mole2bq(1e-16, $g)", "$g ^ 2", "$g ^ 0.5", "$g ^ 3.7", "$g ^ kn", "$g ^ two", "kn ^ $g", "2 ^ $g", "power($g, 2.5)", "power(1.7, $g)",
           "min($g, A)", "max($g, B)", "sum($g, $g, A)", "prod($g, A, B)", "mean($g, B)", "F($g)", "Fn($g)", "-$g / (1 + $g)", "A / $g", "if($g > 1, $g * $g, sqrt($g))"])
end
# A tangent of zero under a rule that would make it NaN (0/0 at the square root of nothing):
# a column the expression does not reach gets 0.
rules("rules: seeds of zero", ["sqrt(A * 0) + A", "(A * zero) ^ 0.5 + A", "sqrt(if(A > 100, A, 0)) + B", "power(if(A > 100, A, 0), 0.5) + B", "if(A < 100, 0, A) ^ half + A",
                               "1:1 / (1 + sqrt(if(C > 5, C, 0))) + C", "atan2(if(A > 100, A, 0), if(A > 100, B, 0)) + A", "hypot(A * 0, B * 0) + B", "acosh(1 + 0 * A) + A",
                               "asin(1 + 0 * A) + B", "A ^ (0 * B) + B", "(0 * A) ^ B + A", "rampUp(A * 0, 0, 1) + smoothUp(A * 0, 1, 2) + A", "min(A * 0, B * 0) + max(0 * A, 0) + A",
                               "log(1 + 0 * A) / (0 * A + 1) + A", "(A * 0) ^ 2 + (A * 0) ^ 3 + (A * 0) ^ -1 * 0 + A", "sqrt(if(A > 100, A, 0) * if(B > 100, B, 0)) + A"])
rules("rules: seeds that cancel into nothing finite", ["(A - A) ^ 0.5 + A", "sqrt(B - B) + A", "1:log(C - C) * 0"])
# What the walk handles itself.
rules("rules: min, max, sum, prod, mean", ["min(A, B)", "max(A, B)", "min(A, B, 2.5)", "max(A, 1, B, kn)", "min(A, A)", "max(A, A * 1)", "min(A)", "max(B)",
                                           "sum(A, B, k)", "sum(A)", "prod(A, B, k)", "prod(A, B, A)", "product(A, 2)", "prod(B)", "mean(A, B, 2)", "mean(A)",
                                           "mean(A, A, B, kn)", "1:min(C, 1) + max(C, 0.2) + sum(C, C) + prod(C, C, 3) + mean(C, 1)", "max(A, B2) + min(B2, 0)",
                                           "prod(B2, A, B)", "min(A, B) * max(A, B) + sum(A * B, B) / mean(A, 2)"])
rules("rules: staircases", ["A * ceil(B)", "floor(A) + A", "round(A) * B", "fix(A) + sqrt(A)", "sign(A - 2.5) * A", "sgn(A) + B", "not(A) + A", "and(A, B) * A",
                            "or(A, B2) * B", "nand(A, B) + A", "nor(A, B2) * A", "xor(A, B2) + B", "eps() * A", "pi() * A", "ceil(A)", "floor(A * B)", "round(A)", "sign(A)",
                            "1:ceil(C) * C + floor(C) + round(C * 3) * C", "ceil(A) ^ 2", "A ^ ceil(B)", "min(ceil(A), A)", "exp(floor(A)) * A"])
rules("rules: comparisons and conditions", ["if(A > 2.5, A * 2, B)", "if(time > 50, A, 0)", "(A > B) * A", "(A < 1 && B > 0) + A", "(A >= B || A <= 1) * B",
                                            "if(A > 2.5, 2, 3) * B", "if(B, A, 2 * A)", "if(A == B, 1, A)", "if(A ~= 3, A ^ 2, 1)", "if(A > 2.5, A)", "if(A > 2.5, k, A * A)",
                                            "if(A > B, if(A > 4, A, B), sqrt(A))", "1:if(C > 0.5, C * C, 0 - C)", "-A * (B > 1)", "-(A * B) + (-A) ^ 2", "if(time, A, B)"])
rules("rules: tables read at the state", ["F(A)", "Fx(A)", "Fb(A)", "Fa(A)", "Fnear(A)", "Fc(A)", "Fs(A)", "F1(A)", "Fn(A)", "Fn(A * B)", "F(A) * Fx(B - 2)", "F(F(A))",
                                          "1:F(C) + Fx(C - 5) + Fc(C * 30)", "Ft * A", "F(time / 20) * A", "Fn(time / 30) + A", "Fx(A - 20) + Fx(A + 20)", "exp(-F(A))",
                                          "Fc(A - 9) * Fn(B2)"])
# Slots read through slots: the chain rule, an expression at a time.
rules("rules: slots through slots", ["A * B", "R1 * R1 + A", "sqrt(R2) + R1", "R3 * R1 / (1 + R2)", "1:C * C", "1:R5 * R5 + C", "R6 + A", "R7 * R4 + R6",
                                     "sum(R1, R2, R3)", "prod(R1, R4, k)", "min(R1, R2) + max(R3, R4)", "if(R1 > R2, R3, R4)", "F(R1 * 0.1)", "R1 ^ R5", "R1 ^ 2 + R6 ^ kn"]; smooth=true) do m
    push!(m["expressions"], K.JDict("name" => "Rz", "equation" => "Z * kz + R1", "index_lists" => Any["Radionuclides", "Zones"]))
    push!(m["transfers"], K.JDict("name" => "Tz", "from" => "Z", "to" => "A", "rate" => "Rz * 0.01", "index_lists" => Any["Radionuclides", "Zones"], "sum_extra_indices" => true))
    m["index_reductions"] = Any[K.JDict("name" => "RzSum", "target" => "Rz", "operation" => "sum", "index_lists" => Any["Radionuclides"])]
    push!(m["transfers"], K.JDict("name" => "Ts", "from" => "A", "to" => "B2", "rate" => "RzSum * 1e-3"))
end
rules("rules: the terms a compartment states", ["A * 0"]; smooth=true) do m
    m["compartments"][1]["dydt"] = "-k * A * A + B"
    m["compartments"][5]["dydt"] = "C * (1 - C) - C * D"
    m["compartments"][6]["dydt"] = "C * D - k * D"
    m["compartments"][4]["entries"] = Any[K.JDict("index" => K.JDict("Zones" => "a"), "dydt" => "sqrt(Z) - Z")]
end
rules("rules: linear, moving with the clock", ["time * k", "Ft", "1:F(time / 10)"]) do m
    for t in m["transfers"]
        t["multiply_by_donor"] = true
    end
end
rules(m -> (for t in m["transfers"]; t["multiply_by_donor"] = true; end), "rules: linear and constant", ["k * kn", "two", "1:three * k"])
rules("rules: a release passed on bare", ["k"]) do m
    m["waste_packages"] = Any[K.JDict("name" => "W", "inventory" => "1e3", "irf" => "0.1", "degradation_rate" => "1e-3", "failure" => "at", "fail_at" => "10")]
    m["transfers"] = Any[K.JDict("name" => "Rel", "from" => "W", "to" => "A", "rate" => "W", "multiply_by_donor" => false),
                         K.JDict("name" => "AB", "from" => "A", "to" => "B", "rate" => "k")]
end

# Availability: the factor a statement multiplies its own slot by.
function availability(name, scheme; smooth=false, extra=m -> nothing)
    rules(name, ["A * 0.01 + k", "sqrt(A + B) * 0.1", "1:C * 0.5 + k", "k"]; smooth=smooth) do m
        for (i, t) in enumerate(m["transfers"])
            t["multiply_by_donor"] = true
            i == 3 || (t["availability"] = scheme)
        end
        m["transfers"][3]["availability"] = K.JDict("scheme" => "limit", "limit" => "0.2 + D")
        push!(m["transfers"], K.JDict("name" => "Tz", "from" => "Z", "to" => "A", "rate" => "0.02 * kz", "index_lists" => Any["Radionuclides", "Zones"],
                                      "sum_extra_indices" => true, "availability" => scheme))
        extra(m)
    end
end
availability("availability: a limit that moves", K.JDict("scheme" => "limit", "limit" => "1 + 0.5 * C"))
availability("availability: a limit never reached", K.JDict("scheme" => "limit", "limit" => "1e6 + C"); smooth=true)
availability("availability: a limit, what is left", K.JDict("scheme" => "limit", "limit" => "0.5 * kn", "unavailable" => true))
availability("availability: shared along the nuclides", K.JDict("scheme" => "shared_limit", "limit" => "2 + C", "over" => "Radionuclides"))
availability("availability: shared, in moles", K.JDict("scheme" => "shared_limit", "limit" => "1e-20 * (1 + C)", "over" => "Radionuclides", "basis" => "moles"))
availability("availability: langmuir", K.JDict("scheme" => "langmuir", "top" => "1 + C", "bottom" => "2 + kn"); smooth=true)
availability("availability: langmuir, shared, what is left", K.JDict("scheme" => "shared_langmuir", "top" => "k", "bottom" => "2 + C * C", "over" => "Radionuclides", "unavailable" => true); smooth=true)
availability("availability: with the audit, whole", K.JDict("scheme" => "limit", "limit" => "1 + 0.5 * C"); extra=m -> (m["simulation"]["mass_balance"] = true; m["simulation"]["solver"] = "ros23"))
availability("availability: with the audit, at the diagonal", K.JDict("scheme" => "langmuir", "top" => "1 + C", "bottom" => "2 + kn"); extra=m -> (m["simulation"]["mass_balance"] = true))

# The audit's budgets, whole (ros23) or at their diagonal (ndf), and off.
for (label, solver, audit) in (("ndf", "ndf", true), ("ros23", "ros23", true), ("dp45", "dp45", true), ("the default solver", nothing, true), ("off, ros23", "ros23", false))
    rules("audit: $label", ["A * B * 0.01", "sqrt(A) * k", "1:C * 0.5", "k", "R1 + R2"]; smooth=true) do m
        m["simulation"]["mass_balance"] = audit
        solver === nothing || (m["simulation"]["solver"] = solver)
        m["compartments"][2]["dydt"] = "-0.01 * B * B"
        m["inflows"] = Any[K.JDict("name" => "In", "to" => "A", "rate" => "1 + 0.1 * C")]
        push!(m["transfers"], K.JDict("name" => "Out", "from" => "B", "rate" => "0.01 * (1 + C)"))
    end
end

# Blocks that remember, read by rates.
function remembering(name, f=m -> nothing; equations=["Mx * 0.01", "Mn * 0.01 + k", "Rm * 0.01", "Sn * 0.01 + Dl * 0.01", "1:Mc + Rc", "Dn * 0.1", "Mx * Rm * 1e-3"])
    rules(name, equations) do m
        m["min_maxes"] = Any[K.JDict("name" => "Mx", "target" => "A * B"), K.JDict("name" => "Mn", "target" => "A + B", "operation" => "min", "reset_trigger" => "Tr"),
                             K.JDict("name" => "Mc", "target" => "C * C", "index_lists" => Any[])]
        m["running_means"] = Any[K.JDict("name" => "Rm", "target" => "sqrt(A)"), K.JDict("name" => "Rc", "target" => "C", "index_lists" => Any[], "stop_trigger" => "Tr")]
        m["snapshots"] = Any[K.JDict("name" => "Sn", "target" => "A", "trigger" => "Tr", "initial" => "k")]
        m["delays"] = Any[K.JDict("name" => "Dl", "target" => "A * 2", "delay" => "5"), K.JDict("name" => "Dn", "target" => "B", "delay" => "kn + time / 100")]
        m["triggers"] = Any[K.JDict("name" => "Tr", "first" => "time", "second" => "50", "index_lists" => Any[])]
        f(m)
    end
end
remembering("recorders read by rates")
remembering("recorders read by rates, with the audit whole", m -> (m["simulation"]["mass_balance"] = true; m["simulation"]["solver"] = "ros23"))
remembering("recorders: a mean of a mean, a peak of a peak", m -> (push!(m["min_maxes"], K.JDict("name" => "Mm", "target" => "Mx + Rm"));
                                                                   push!(m["running_means"], K.JDict("name" => "Rr", "target" => "Rm * Mn"))); equations=["Mm * 0.01", "Rr * 0.01", "Mx * 0.01", "1:Rc"])
remembering("recorders: targets that stand still", m -> (m["min_maxes"][1]["target"] = "kn * time"; m["running_means"][1]["target"] = "kn"); equations=["Mx * 0.01", "Rm * 0.01", "k"])

# Waste packages and events whose rates and shares move with the state.
function packages(name, f=m -> nothing)
    rules(name, ["A * 1e-3", "1:C * 0.1"]) do m
        m["waste_packages"] = Any[K.JDict("name" => "W", "inventory" => "1e3", "irf" => "0.1 * C / (1 + C)", "degradation_rate" => "1e-3 * (1 + C)", "failure" => "weibull",
                                          "fail_start" => "1", "fail_scale" => "50", "fail_shape" => "2", "packages" => 10),
                                  K.JDict("name" => "W2", "inventory" => "5", "failure" => "uniform", "fail_from" => "1", "fail_to" => "90"),
                                  K.JDict("name" => "W3", "inventory" => "7", "irf" => "0.2", "degradation_rate" => "0.01", "failure" => "at", "fail_at" => "20", "index_lists" => Any[])]
        push!(m["transfers"], K.JDict("name" => "Rel", "from" => "W", "to" => "A", "rate" => "W", "multiply_by_donor" => false))
        push!(m["transfers"], K.JDict("name" => "Rel2", "from" => "W2", "to" => "B", "rate" => "W2 * (1 + D)", "multiply_by_donor" => false))
        push!(m["transfers"], K.JDict("name" => "Rel3", "from" => "W3", "to" => "C", "rate" => "W3", "multiply_by_donor" => false, "index_lists" => Any[]))
        m["events"] = Any[K.JDict("name" => "Quake", "timing" => "poisson", "rate" => "1e-3 * (1 + C)", "from" => "10",
                                  "actions" => Any[K.JDict("kind" => "fail", "block" => "W", "fraction" => "0.5 * C / (1 + C)"),
                                                   K.JDict("kind" => "move", "from" => "A", "to" => "B2", "fraction" => "0.1 + 0.1 * D / (1 + D)"),
                                                   K.JDict("kind" => "move", "from" => "B", "to" => "", "fraction" => "0.2")]),
                          K.JDict("name" => "Flood", "timing" => "poisson", "rate" => "2e-3", "actions" => Any[K.JDict("kind" => "move", "from" => "C", "to" => "E", "fraction" => "k * C")]),
                          K.JDict("name" => "Late", "timing" => "at", "at" => "80", "actions" => Any[K.JDict("kind" => "move", "from" => "B2", "fraction" => "k")])]
        f(m)
    end
end
packages("packages and events that move with the state")
packages("packages and events, with the audit whole", m -> (m["simulation"]["mass_balance"] = true; m["simulation"]["solver"] = "ros23"))
packages("packages and events, with the audit at the diagonal", m -> (m["simulation"]["mass_balance"] = true))

# An infinite entry at the start: the plan is there, the Jacobian is not handed on.
rules("not finite at the start: sqrt of an empty compartment", ["sqrt(B2)", "A * 0.1"])
rules("not finite at the start: log", ["log(B2) * B2", "1:log(D)"])
rules("not finite at the start: a power", ["B2 ^ 0.5", "1:D ^ -1"])

# --- what has no derivative -----------------------------------------------------------------------------
rules("refused: factorial", ["factorial(A)"])
rules("refused: binomial", ["A + binomial(5, A)"])
rules("refused: a percentile", ["percentile(50, A, B, k)"])
rules("refused: a percentile along a list", ["k"]) do m
    push!(m["expressions"], K.JDict("name" => "Rz", "equation" => "Z * kz", "index_lists" => Any["Radionuclides", "Zones"]))
    m["index_reductions"] = Any[K.JDict("name" => "P90", "target" => "Rz", "operation" => "percentile", "percentile" => 90, "index_lists" => Any["Radionuclides"])]
    push!(m["transfers"], K.JDict("name" => "Tp", "from" => "A", "to" => "B2", "rate" => "P90 * 1e-3"))
end
rules("refused: a table that depends on the state", ["interpolationUseEndValues(1, 0, A, 1, 2)"])
rules("refused: a table's x that depends on the state", ["A + interpolationExtrapolation(A, 0, 1, B, 2)"])
rules("refused: a ramp whose ends depend on the state", ["rampDown(1, A, 4)"])
rules("refused: a ramp whose far end depends on the state", ["rampUp(A, 1, B)"])
rules("refused: a smooth step whose scale depends on the state", ["smoothDown(A, B, 2)"])
rules("refused: a smooth step whose steepness depends on the state", ["k", "smoothUp(1, 2, A)"])
rules("refused: inside a staircase, still refused", ["ceil(factorial(A))"])
rules("refused: the second of two", ["sqrt(A)", "1:binomial(C, 2)", "factorial(A)"])
rules("refused: through a slot", ["A * 2", "factorial(R1)"])
rules("not refused: what the state does not reach", ["A * factorial(3) + binomial(5, 2) * percentile(50, k, two, three)", "factorial(kn + 1.5) * A",
                                                     "rampDown(time, 10, 50) * A", "smoothUp(time, 20, kn) * A", "interpolationUseEndValues(time, 0, kn, 100, 2) * B"])
remembering("refused: a delay whose lag depends on the state", m -> (m["delays"][2]["delay"] = "1 + A"))
remembering("not refused: a delay nobody reads", m -> (m["delays"][2]["delay"] = "1 + A"); equations=["Mx * 0.01", "Dl * 0.01"])

path = joinpath(@__DIR__, "..", "tests", "fixtures", "jacobian.json")
write(path, K.json_text(K.JDict("cases" => cases); indent=0))
println(path, ": ", length(cases), " models, ", count(c -> startswith(get(c, "plan", ""), "refused"), cases), " refused, ",
        count(c -> occursin("available=true", c["info"]), cases), " with an exact Jacobian")
