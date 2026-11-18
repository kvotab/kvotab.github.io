# Writes tests/fixtures/nonfinite.json: what the Julia engine says, with parity
# on, of a run that meets a value that is not a number, for the C++ engine's
# tests to compare with (tests/test_nonfinite.cpp).
#
#     julia --project=. ../cpp/tools/nonfinite_fixtures.jl        (from ../julia)
#
# Models made up to meet one in every way engine/nonfinite.jl tells apart -- in
# a state, a derivative, an algebraic slot, a table, a waste package; by a
# division by zero, a logarithm of zero or of a negative, an overflow; at the
# start and in the middle of a run, a step past the state held; inside a
# sub-system, at one index of several and at many; through transfers, inflows,
# a recorder's target, an availability, a sum over an index, a chain of
# expressions longer than is followed; and runs that fail otherwise, or are
# refused (a parameter cannot be one) -- each run on the NDF, the Rosenbrock
# 2-3 and the Dormand-Prince 4-5 (the longest on the NDF alone): the error's
# kind, its message, the block it names, the solver's own message and the
# hint, kept whole, or that the run went. Beside each, the warnings at the
# start of a run (`start_warnings`). Then equations written back as text
# (`equation_text`).

using Kompartment
const K = Kompartment
K.set_parity!(true)

J(pairs...) = K.JDict(String(k) => v for (k, v) in pairs)
const SOLVERS = ("ndf", "ros23", "dp45")
const SIM = J("start_time" => 0, "end_time" => 10, "output_points" => 3, "spacing" => "linear", "solver" => "ndf",
              "rtol" => 1e-6, "abstol" => 1e-9, "time_unit" => "year")

"""A model of blocks, every collection there, the simulation's settings over the usual ones."""
function M(name; sim=J(), kw...)
    m = J("name" => name, "simulation" => merge(K.jcopy(SIM), sim), "parameters" => [], "compartments" => [],
          "transfers" => [], "expressions" => [], "inflows" => [])
    for (k, v) in kw
        m[String(k)] = v
    end
    return m
end
P(name, value; kw...) = J("name" => name, "value" => value, (String(k) => v for (k, v) in kw)...)
C(name, initial="0"; kw...) = J("name" => name, "initial" => initial, (String(k) => v for (k, v) in kw)...)
E(name, equation; kw...) = J("name" => name, "equation" => equation, (String(k) => v for (k, v) in kw)...)
T(name, from, to, rate; kw...) = J("name" => name, "from" => from, "to" => to, "rate" => rate, "multiply_by_donor" => false,
                                   (String(k) => v for (k, v) in kw)...)
I(name, to, rate; kw...) = J("name" => name, "to" => to, "rate" => rate, (String(k) => v for (k, v) in kw)...)

const RN = [J("name" => "Radionuclides", "for_contaminants" => true, "indices" => [J("name" => "Cs-137"), J("name" => "Sr-90")])]

cases = Any[]
add!(name, model; solvers=SOLVERS) = push!(cases, (name, model, solvers))

# Packages that may crack: none have, and the concentration in them is 0/0 (the engines' own tests).
cracked(; n_cracked=0, initial="0", to="Wall") = M("cracked packages"; nuclides=["Cs-137", "Sr-90"], index_lists=RN,
    parameters=[P("N_cracked", n_cracked), P("V", 2), P("limit", 100)],
    compartments=[C("Waste", initial; index_lists=["Radionuclides"]), C("Wall"; index_lists=["Radionuclides"])],
    expressions=[E("C_waste", "min(Waste/(V*N_cracked), limit)"; index_lists=["Radionuclides"]),
                 E("C_out", "Wall/(V*N_cracked)"; index_lists=["Radionuclides"])],
    transfers=[T("Diffusion", "Waste", to, "N_cracked*C_waste"; index_lists=["Radionuclides"])])
add!("cracked packages", cracked())
add!("cracked packages, mended", cracked(; n_cracked=1))
add!("cracked packages, the initial value 0/0", cracked(; initial="0/N_cracked"))
one_cracked = cracked(; to=nothing)
one_cracked["parameters"][1] = J("name" => "N_cracked", "value" => 1, "index_lists" => ["Radionuclides"],
                                 "entries" => [J("index" => "Cs-137", "value" => 0)])
add!("cracked packages, one index", one_cracked)

# A compartment a hair below zero under a square root: the state held gives numbers, the step past it does not.
below_zero = M("below zero"; sim=J("output_points" => 20, "non_negative" => false),
    compartments=[C("A", "1"; non_negative=false), C("B")], expressions=[E("R", "sqrt(A)")],
    transfers=[T("Drain", "A", "B", "0.5 + 0*R"), T("Leak", "B", nothing, "0.01*R")])
add!("below zero", below_zero)

# Each operation that makes a value that is not a number out of numbers.
op(name, eq; params=[P("k", 1), P("big", 1e200), P("V", 2), P("N", 0)], initial="0") =
    M(name; parameters=params, compartments=[C("A", initial), C("B")], expressions=[E("X", eq)],
      transfers=[T("Out", "A", "B", "0.1*X")])
add!("a division of a number by zero", op("divided", "A/(V*N)"; initial="1"))
add!("zero divided by zero", op("zero by zero", "A/(V*N)"))
add!("the log of zero", op("log of zero", "log(A)"))
add!("the log of a negative", op("log of a negative", "log(A - 1)"))
add!("the square root of a negative", op("root of a negative", "sqrt(-k - A)"))
add!("an overflow in a function", op("exp", "exp(k*1000)"))
add!("an overflow in a product", op("product", "big*big"))
add!("an overflow in a power", op("power", "big^2"))
add!("an overflow in a sum", op("sum", "1e308 + 1e308*k"))
add!("infinity less infinity", op("difference", "exp(1000*k) - exp(1000)"))
add!("a power of a negative", op("power of a negative", "(A - k)^0.5"))
add!("a condition's branch", op("if", "if(A >= 0, 1/A, 0)"))
add!("a condition's other branch", op("ternary", "A > 0 ? 0 : log(A)"))
add!("the clock's end", op("end time", "A/(end_time() - 10) + k"; initial="1"))
add!("the clock's start", op("start time", "log(start_time())*k"))
add!("a minimum of numbers and one that is not", op("min", "min(k, A/N, 3)"))
add!("the negative of a log", op("minus", "-log(A)*k"))
many_reads = [P("a$i", v) for (i, v) in enumerate([1, -2, 3, 0, 5, 6, 7])]
add!("many values read", op("many reads", "(a1*a2*a3*a4*a5*a6*a7)/(b - b)"; params=[many_reads; P("b", 1)]))
add!("six values read", op("six reads", "(a1*a2*a3*a4*a5)/(b - b)"; params=[many_reads; P("b", 1)]))
add!("a long equation", op("long", "(" * join(("a$(mod1(i, 7)) * $i" for i in 1:30), " + ") * ")/(b - b)";
                                params=[many_reads; P("b", 1)]))
add!("a number with a unit", op("units", "A/(0[m]*k)"))

# A parameter that is not a number, read by a transfer, and at one index of several: refused before a run.
add!("a parameter that is not a number", M("parameter"; parameters=[P("p", "0/0")], compartments=[C("A", "1"), C("B")],
                                           transfers=[T("Out", "A", "B", "p*A")]))
add!("a parameter infinite at one index", M("parameter by index"; nuclides=["Cs-137", "Sr-90"], index_lists=RN,
    parameters=[J("name" => "p", "value" => 1, "index_lists" => ["Radionuclides"],
                  "entries" => [J("index" => "Sr-90", "value" => "1/0")])],
    compartments=[C("A", "1"; index_lists=["Radionuclides"]), C("B"; index_lists=["Radionuclides"])],
    transfers=[T("Out", "A", "B", "p*A"; index_lists=["Radionuclides"])]))

# A state that grows past the largest number: it is the compartment that holds infinity.
add!("a state that overflows", M("overflow"; sim=J("end_time" => 4, "output_points" => 5),
    compartments=[C("A"), C("B")], inflows=[I("Pour", "A", "1e308")], transfers=[T("Drain", "A", "B", "A*1e-300")]))
add!("a state that overflows, read by nothing", M("overflow alone"; sim=J("end_time" => 4, "output_points" => 5),
    compartments=[C("A")], inflows=[I("Pour", "A", "1e308")]))
add!("a rate that grows past the largest number", M("blow-up"; sim=J("end_time" => 2, "output_points" => 5),
    compartments=[C("A", "1"), C("B")], transfers=[T("Back", "B", "A", "A*A")]); solvers=("ndf", "ros23"))

# Mid-run: the log of a clock that reaches zero.
add!("a log of the time left", M("time left"; parameters=[P("k", 0.01)], compartments=[C("A", "1"), C("B")],
    expressions=[E("L", "log(5 - time())")], transfers=[T("Out", "A", "B", "k*L*L")]))

# At a switch time, the first instant of the stretch after it.
add!("at a switch time", M("switch"; sim=J("switch_times" => [5]), parameters=[P("k", 0.01)], compartments=[C("A", "1"), C("B")],
    expressions=[E("L", "if(time() < 5, 1, log(time() - 5))")], transfers=[T("Out", "A", "B", "k*L")]))

# A table: at the clock, its values too large to interpolate between; and one read at an argument.
add!("a table at the clock", M("table"; lookups=[J("name" => "V", "points" => [[0, 1e308], [10, -1e308]])],
    compartments=[C("A", "1"), C("B")], transfers=[T("Out", "A", "B", "1e-300*V")]))
add!("a table read at an argument", M("table argument"; parameters=[P("k", 0.5)],
    lookups=[J("name" => "F", "points" => [[0, 1e308], [1, -1e308]], "argument" => "x")],
    compartments=[C("A", "1"), C("B")], expressions=[E("G", "F(k)")], transfers=[T("Out", "A", "B", "1e-300*G")]))
add!("a table read at a value that is not one", M("table at NaN"; parameters=[P("k", 0)],
    lookups=[J("name" => "F", "points" => [[0, 0], [1, 1]], "argument" => "x")],
    compartments=[C("A"), C("B")], expressions=[E("G", "F(A/k)")], transfers=[T("Out", "A", "B", "G")]))

# Inside a sub-system, and at one index of several there.
add!("inside a sub-system", M("sub-system"; parameters=[P("V", 2), P("N", 0)],
    compartments=[C("A"; system="Near"), C("B"; system="Near")], expressions=[E("X", "A/(V*N)"; system="Near")],
    transfers=[T("Out", "A", "B", "N + X"; system="Near")]))
add!("inside a sub-system, by index", M("sub-system by index"; nuclides=["Cs-137", "Sr-90"], index_lists=RN,
    parameters=[J("name" => "N", "value" => 1, "index_lists" => ["Radionuclides"], "entries" => [J("index" => "Sr-90", "value" => 0)])],
    compartments=[C("A"; system="Deep.Rock", index_lists=["Radionuclides"]), C("B"; system="Deep.Rock", index_lists=["Radionuclides"])],
    expressions=[E("X", "A/N"; system="Deep.Rock", index_lists=["Radionuclides"])],
    transfers=[T("Out", "A", "B", "X"; system="Deep.Rock", index_lists=["Radionuclides"])]))

# What it reaches: flows of both kinds, many of them, many compartments, other sources.
add!("transfers and inflows", M("flows"; parameters=[P("k", 0)], compartments=[C("A"), C("B")],
    expressions=[E("X", "k/k")],
    transfers=[T("T1", "A", "B", "X"), T("T2", "B", "A", "2*X")], inflows=[I("I1", "A", "X"), I("I2", "B", "X + 1")]))
add!("many transfers", M("many flows"; parameters=[P("k", 0)], compartments=[C("A"), C("B")], expressions=[E("X", "k/k")],
    transfers=[T("T$i", isodd(i) ? "A" : "B", isodd(i) ? "B" : "A", "X*$i") for i in 1:5]))
add!("one inflow", M("one inflow"; parameters=[P("k", 0)], compartments=[C("A")], inflows=[I("Feed", "A", "k/k")]))
add!("many compartments", M("many compartments"; parameters=[P("k", 0)], compartments=[C("S"); [C("A$i") for i in 1:5]],
    expressions=[E("X", "log(k)")], transfers=[T("T$i", "S", "A$i", "X") for i in 1:5]))
for n in 2:4
    add!("$n sources", M("sources"; parameters=[P("k", 0)], compartments=[C("A"), C("B")],
        expressions=[E("X$i", i == 1 ? "k/k" : i == 2 ? "log(k)" : "sqrt(k - $i)") for i in 1:n],
        transfers=[T("T$i", "A", "B", "X$i") for i in 1:n]))
end
add!("two sources in one block", M("same block"; parameters=[P("k", 0)], compartments=[C("A"), C("B")],
    expressions=[E("X", "k/k"), E("Y", "X + log(k)")], transfers=[T("T1", "A", "B", "X"), T("T2", "A", "B", "Y + 1/k")]))

# Blocks that remember: a peak, a running mean, of a value that is not a number.
add!("a peak's target", M("peak"; parameters=[P("V", 0)], compartments=[C("A", "1"), C("B")],
    expressions=[E("Dose", "A/V")], min_maxes=[J("name" => "Peak", "operation" => "max", "target" => "Dose")],
    transfers=[T("Out", "A", "B", "0.1*Peak")]))
add!("a running mean's target", M("mean"; parameters=[P("V", 0)], compartments=[C("A", "1"), C("B")],
    expressions=[E("Dose", "log(V)*A")], running_means=[J("name" => "Avg", "target" => "Dose")],
    transfers=[T("Out", "A", "B", "0.1")]))
add!("a peak only results read", M("peak read by nothing"; parameters=[P("V", 0)], compartments=[C("A", "1"), C("B")],
    expressions=[E("Dose", "A/V")], min_maxes=[J("name" => "Peak", "operation" => "max", "target" => "Dose")],
    transfers=[T("Out", "A", "B", "0.1*A")]))

# A transfer's availability that is not a number while its rate is one.
add!("an availability", M("availability"; parameters=[P("k", 0.1), P("z", 0)], compartments=[C("A", "1"), C("B")],
    transfers=[J("name" => "Out", "from" => "A", "to" => "B", "rate" => "k", "multiply_by_donor" => true,
                 "availability" => J("scheme" => "limit", "limit" => "z/z"))]))

# A chain longer than is followed: it starts where the following stopped.
chain = M("chain"; parameters=[P("k", 0)], compartments=[C("A"), C("B")],
          expressions=[E("E0", "k/k"); [E("E$i", "E$(i-1)") for i in 1:510]], transfers=[T("Out", "A", "B", "E510")])
add!("a chain longer than is followed", chain; solvers=("ndf",))

# More elements than are followed.
wide_list = [J("name" => "Cells", "indices" => [J("name" => "c$(lpad(i, 4, '0'))") for i in 1:2100])]
add!("more elements than are followed", M("wide"; index_lists=wide_list, parameters=[P("k", 0)],
    compartments=[C("A"; index_lists=["Cells"]), C("B"; index_lists=["Cells"])],
    expressions=[E("X", "A/k"; index_lists=["Cells"])], transfers=[T("Out", "A", "B", "X"; index_lists=["Cells"])]);
     solvers=("ndf",))

# A sum over an index whose numbers overflow: the list's references written out.
add!("a sum over an index that overflows", M("reduction"; nuclides=["Cs-137", "Sr-90"], index_lists=RN,
    parameters=[P("big", 1e308)], compartments=[C("A", "1"), C("B")],
    expressions=[E("Ez", "big"; index_lists=["Radionuclides"])],
    index_reductions=[J("name" => "Tot", "target" => "Ez", "operation" => "sum", "index_lists" => [])],
    transfers=[T("Out", "A", "B", "1e-300*Tot")]))

# Runs that fail otherwise: nothing to say about numbers, and the hints stay.
add!("too many steps", M("steps"; sim=J("max_steps" => 5, "end_time" => 1e4), parameters=[P("k", 1)],
    compartments=[C("A", "1"), C("B")], transfers=[J("name" => "Out", "from" => "A", "to" => "B", "rate" => "k*(1 + sin(time()))")]))
add!("too many steps, held at zero", M("held"; sim=J("max_steps" => 300), parameters=[P("k", 0.3)],
    compartments=[C("A", "1"), C("B")], transfers=[T("Out", "A", "B", "k")]))

# Waste packages: a release rate that is not a number reaches a block of its own kind.
wp = K.parse_json(read(joinpath(@__DIR__, "..", "..", "examples", "waste-packages.json"), String))
wp["waste_packages"][1]["degradation_rate"] = "matrix_rate*0/0"
wp["simulation"]["end_time"] = 2000
add!("a waste package's degradation", wp; solvers=("ndf",))

function outcome(m, solver)
    m = K.jcopy(m)
    m["simulation"]["solver"] = solver
    out = K.JDict()
    try
        p = K.Project(m)
        res = K.run_project(p; system=K.build_system(p))
        out["ran"] = length(res.t)
    catch e
        if e isa K.SolverError
            out["kind"] = e.kind
            out["message"] = e.message
            out["block"] = e.block_name
            out["solver_message"] = e.solver_message
            out["hint"] = e.hint
        elseif e isa K.BuildError || e isa K.ValidationError || e isa ErrorException || e isa ArgumentError
            out["refused"] = e isa ErrorException ? e.msg : e.message
        else
            rethrow()
        end
    end
    return out
end

function warnings(m)
    try
        p = K.Project(m)
        sys = K.build_system(p; jacobian=false)
        t0 = Float64(p.simulation["start_time"])
        y = K.initial_state(sys)
        K.prime_recorders!(sys, t0, y)
        K.evaluate_algebraic!(sys, t0, y)
        return Any[K.JDict("block" => w["block"], "message" => w["message"], "stops" => w["stops"])
                   for w in K.start_warnings(sys, t0, y)]
    catch e
        return K.JDict("refused" => e isa ErrorException ? e.msg : hasproperty(e, :message) ? e.message : string(e))
    end
end

out = Any[]
for (name, m, solvers) in cases
    row = K.JDict("name" => name, "model" => m)
    for s in solvers
        row[s] = outcome(m, s)
    end
    row["warnings"] = warnings(m)
    push!(out, row)
end

# Equations written back as the parser read them (the engines' own tests hold the first ones).
equations = ["a/(b*c)", "a-b-c", "a-(b-c)", "-a^2", "(-a)^2", "2^-3", "2^-3^2", "a^b^c", "a^(b^c)", "-(a*b)", "-a*b",
             "a*-b", "min(a, b*c, -d)", "x>1 && y<2", "(a || b) && c", "a ? b : c ? d : e", "(a ? b : c) + 1",
             "if(c, a+1, b)", "a*(b+c)/d", "1e-5*a", "0.01[m]*a", "Cs[Cs-137]*2", "M[_Ra-226][Pb-210]", "M[][x]",
             "a == b", "a ~= b", "a != b", "not(z)", "exp(-(a+b)/c)", "sqrt(a - b)^0.5", "a .* b ./ c .^ d",
             "1e21 + 1e-7 + 0.1 + 123456789012", "-(-a)", "a - -b", "a^-b^c", "(a^b)^c", "-a^-b", "2^(-3)",
             "a <= b || c >= d && e < f", "!(a)", "a ? (b ? c : d) : e", "f()", "g(a)(b)",
             join(("x$i" for i in 1:80), " + "), join(("\u00e5\u00e4\u00f6$i" for i in 1:60), " * ")]
texts = Any[]
for eq in equations
    t = try
        K.equation_text(K.parse_equation(eq))
    catch e
        K.JDict("refused" => e isa ErrorException ? e.msg : hasproperty(e, :message) ? e.message : string(e))
    end
    push!(texts, Any[eq, t])
end

path = joinpath(@__DIR__, "..", "tests", "fixtures", "nonfinite.json")
write(path, K.json_text(K.JDict("cases" => out, "equations" => texts); indent=0))
said = count(r -> any(s -> haskey(r[s], "solver_message") && r[s]["solver_message"] !== nothing, filter(k -> k in SOLVERS, collect(keys(r)))), out)
println(path, ": ", length(out), " models (", said, " explained), ", length(texts), " equations")
