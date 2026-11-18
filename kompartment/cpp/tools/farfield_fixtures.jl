# Writes tests/fixtures/farfield.json: what the Julia engine makes of far-field
# paths, for the C++ engine's tests to compare with (tests/test_farfield.cpp).
#
#     julia --project=../julia tools/farfield_fixtures.jl
#
# Two parts, with parity on.
#
# `helpers` -- the arithmetic and the geometry a path is made of, each called on
# numbers written here: Python's hypot, numpy's sum and spacing, the powers,
# the root-finder, the reference and the matched layers with their refusals,
# the penetration scale, the cells' structure, the texts.
#
# `cases` -- models made up here to reach every branch of a path on cells:
# matched and reference layers, every outflow condition, settings that follow
# the clock and the state, rates per nuclide, other index lists, paths in a
# row and side by side, paths fed by transfers, inflows and waste packages,
# with and without decay, restarts at corners and at events, and what a path
# refuses in the middle of a run. For each: the path as it is laid out, the
# series it reports, the derivative and every slot at a few instants with the
# path's rates and layers there, the tangents of its rates, the Jacobian, whole
# runs (differenced and exact, and again on the same system), and runs on
# layers held from outside. A short text is kept as it is, a long one as a
# hash; with KOMPARTMENT_FIXTURE_DUMPS set every text is written there
# (`<name>.farfield.julia.txt`).

using Kompartment
const K = Kompartment
K.set_parity!(true)

bits(x::Float64) = string(reinterpret(UInt64, x); base=16, pad=16)
unbits(s) = reinterpret(Float64, parse(UInt64, s; base=16))
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
kept(text::String) = length(text) <= 400 ? "=" * text : "#" * fnv(text)

# --- the helpers -------------------------------------------------------------------------------------------

helpers = Any[]
"""One call: the function's name, its numbers (as bits), its whole numbers and texts, and what it gave."""
function helper(fn, out; x=Float64[], n=Int[], s=String[])
    push!(helpers, K.JDict("fn" => fn, "x" => Any[bits(Float64(v)) for v in x], "n" => Any[v for v in n], "s" => Any[v for v in s],
                           "out" => out))
end
said(f) =
    try
        f()
    catch e
        e isa K.FarfError ? "error: $(e.message)" : e isa DomainError ? "throws" : rethrow()
    end

const SPECIAL = [0.0, -0.0, 1.0, -1.0, 0.5, 2.0, 3.0, -3.0, 2.5, 1e-320, 5e-324, 2.2250738585072014e-308, 1e308, 1.7976931348623157e308, Inf, -Inf, NaN,
                 1e21, 1e20, 123456789.0, 0.1, 12.5, -7.25, 1e-7, 1.5e-5, 99.95, 0.00012345, 9.995, 999.5, 0.9995, 1e-300, 3e200, 1.0000000000000002]
for a in SPECIAL
    helper("np_spacing", nums([K.np_spacing(a)]); x=[a])
    helper("np_sign", nums([K.np_sign(a)]); x=[a])
    helper("num_text", K._num_text(a); x=[a])
    for p in (1, 2, 3, 4, 7, 17)
        helper("to_precision", K.js_to_precision(a, p); x=[a], n=[p])
    end
    for b in SPECIAL
        helper("py_hypot", nums([K.py_hypot(a, b)]); x=[a, b])
        helper("js_div", nums([K._js_div(a, b)]); x=[a, b])
        helper("py_pow", said(() -> nums([K.py_pow(a, b)])); x=[a, b])
    end
    for j in (0, 1, 2, 3, 7, 12, 40, 1000)
        helper("ff_pow", nums([K._js_pow(a, j)]); x=[a], n=[j])
    end
end
for a in (2.5e-3, 3.6e-3, 0.0125, 1.4375, 2.675, 1.005, 0.000001, 0.0000001234, 123456.5, 5e-7 * 1e6, 0.00036 * 1e3, 1e21 + 1e5, 0.5, 1.5, 2.5, 0.05, 0.15, 0.25)
    for p in (1, 2, 3)
        helper("to_precision", K.js_to_precision(a, p); x=[a], n=[p])
    end
end
# Numbers without a pattern: a linear congruential sequence, scaled.
function sequence(count, seed, scale)
    out = Float64[]
    state = UInt64(seed)
    for _ in 1:count
        state = state * 6364136223846793005 + 1442695040888963407
        push!(out, (Float64(state >> 11) / 9007199254740992.0 - 0.5) * scale)
    end
    return out
end
for (count, seed) in ((0, 1), (1, 2), (7, 3), (8, 4), (9, 5), (15, 6), (16, 7), (127, 8), (128, 9), (129, 10), (255, 11), (256, 12), (300, 13), (1000, 14), (4097, 15))
    v = sequence(count, seed, 1e6)
    helper("np_sum", nums([K.np_sum(v)]); x=v)
end
for (a, b) in zip(sequence(40, 21, 1e3), sequence(40, 22, 1e-3))
    helper("py_hypot", nums([K.py_hypot(a, b)]); x=[a, b])
    helper("py_pow", said(() -> nums([K.py_pow(abs(a), b * 1e4)])); x=[abs(a), b * 1e4])
end
# The root-finder on a cubic, from several brackets.
cubic(x) = x * x * x - 2 * x - 5
for (a, b) in ((2.0, 3.0), (3.0, 2.0), (0.0, 5.0), (-10.0, 10.0), (2.0945514815423265, 3.0), (2.5, 2.75))
    helper("zeroin", nums([K.zeroin(cubic, a, b)]); x=[a, b])
end
# The penetration scale: (de, rm, lam, rf, aw, tw, pe).
for args in ((1e-6, 2.7, 0.0, 1.0, 2000.0, 50.0, 10.0), (1e-6, 4.59, 4.9e-6, 1.0, 2000.0, 50.0, 10.0), (4e-7, 135.0, 9.2e-6, 11.0, 1000.0, 20.0, 25.0),
             (0.0, 2.7, 0.0, 1.0, 2000.0, 50.0, 10.0), (1e-6, 0.0, 0.0, 1.0, 2000.0, 50.0, 10.0), (1e-6, 2.7, 0.0, 1.0, Inf, 50.0, 10.0),
             (1e-6, 2.7, 0.0, 1.0, 2000.0, 0.0, 10.0), (1e-6, 2.7, 0.0, 1.0, 2000.0, 50.0, -1.0), (1e-6, 2.7, 1e3, 1.0, 2000.0, 50.0, 10.0),
             (1e-6, 2.7, NaN, 1.0, 2000.0, 50.0, 10.0), (1e-6, 2.7, Inf, 1.0, 2000.0, 50.0, 10.0), (1e-6, 2.7, 0.0, NaN, 2000.0, 50.0, 10.0),
             (1e-300, 1e300, 0.0, 1.0, 1e-300, 1e300, 1e-300), (1e-6, 2.7, 0.0, 1.0, 2000.0, 1e300, 1e300))
    helper("penetration_scale", nums([K.penetration_scale(args...)]); x=collect(args))
end
# The reference layers: (pen_dep, aw, first), nm; and their tangent along (d_pen_dep, d_aw, d_first).
for (pen_dep, aw, first, nm) in ((12.5, 2000.0, NaN, 20), (12.5, 2000.0, NaN, 6), (12.5, 2000.0, 0.001, 6), (0.5, 1000.0, NaN, 2), (0.5, 1000.0, 0.25, 2),
                                 (0.5, 1000.0, 0.1, 5), (0.5, 1000.0, 0.1000000001, 5), (0.5, 1000.0, 0.2, 5), (12.5, 1e-3, NaN, 6), (12.5, 0.01, NaN, 3),
                                 (0.0, 1000.0, NaN, 6), (-1.0, 1000.0, NaN, 6), (Inf, 1000.0, NaN, 6), (NaN, 1000.0, NaN, 6), (12.5, 0.0, NaN, 6),
                                 (12.5, -2.0, NaN, 6), (12.5, Inf, NaN, 6), (12.5, NaN, NaN, 6), (1e-9, 2000.0, NaN, 6), (1e6, 2000.0, NaN, 12),
                                 (12.5, 2000.0, 0.0, 6), (12.5, 2000.0, -1.0, 6), (12.5, 2000.0, Inf, 6), (12.5, 2000.0, 3.0, 6), (12.5, 2000.0, 12.5 / 6, 6))
    d = zeros(nm)
    out = said(() -> nums(K.layer_depths!(d, pen_dep, nm, aw, first)))
    helper("layer_depths", out; x=[pen_dep, aw, first], n=[nm])
    startswith(out, "error") && continue
    for (dp, da, df) in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.25, -3.0, 1e-4))
        dd = zeros(nm)
        K._layer_depths_tangent!(dd, pen_dep, nm, aw, first, d, dp, da, df)
        helper("layer_depths_tangent", nums(dd); x=[pen_dep, aw, first, dp, da, df], n=[nm])
    end
end
# The matched layers: (pen_dep, first, the shallowest scale), nm.
for (pen_dep, first, L, nm) in ((12.5, NaN, 0.036, 20), (12.5, NaN, 0.036, 6), (12.5, NaN, Inf, 6), (12.5, NaN, NaN, 6), (12.5, NaN, 1e3, 6), (12.5, NaN, 1e-9, 6),
                                (12.5, 0.001, 0.0, 6), (12.5, 0.0005, 0.0, 12), (0.5, 0.25, 0.0, 2), (0.5, 0.2500000000001, 0.0, 2), (0.5, 0.1, 0.0, 5),
                                (0.5, 0.2, 0.0, 5), (12.5, 0.0, 0.5, 3), (12.5, -1.0, 0.5, 3), (12.5, Inf, 0.5, 3), (0.0, NaN, 0.036, 6), (-2.0, NaN, 0.036, 6),
                                (Inf, NaN, 0.036, 6), (NaN, NaN, 0.036, 6), (12.5, NaN, 0.036, 1), (12.5, 1.0, 0.036, 1), (1e6, 1e-6, 0.0, 4), (12.5, 12.5 / 6, 0.0, 6),
                                (100.0, 1e-5, 0.0, 3), (12.5, NaN, 20.83, 6), (12.5, NaN, 20.84, 6))
    d = zeros(nm)
    h = zeros(nm)
    out = said(() -> (q = K.matched_grid!(d, h, pen_dep, nm, first, () -> L); "$(nums(d))|$(nums(h))|$(nums([q]))"))
    helper("matched_grid", out; x=[pen_dep, first, L], n=[nm])
    startswith(out, "error") && continue
    q = K.matched_grid!(d, h, pen_dep, nm, first, () -> L)
    for where_ in ("", " (index combination 2 of 3)")
        helper("coarse", something(K.coarse_layers_warning(d, q, where_), "nothing"); x=[q; d], s=[where_])
    end
end
helper("coarse", something(K.coarse_layers_warning(Float64[], 3.0, ""), "nothing"); x=[3.0], s=[""])
helper("coarse", something(K.coarse_layers_warning([2e-7, 1.0, 3.0], 2.5000000000000004, ""), "nothing"); x=[2.5000000000000004, 2e-7, 1.0, 3.0], s=[""])
helper("coarse", something(K.coarse_layers_warning([1.5, 10.0, 80.0], 2.5, ""), "nothing"); x=[2.5, 1.5, 10.0, 80.0], s=[""])
helper("coarse", something(K.coarse_layers_warning([1.5, 10.0, 80.0], 7.123456, " there"), "nothing"); x=[7.123456, 1.5, 10.0, 80.0], s=[" there"])
helper("coarse", something(K.coarse_layers_warning([0.0, 10.0, 80.0], 1e9, ""), "nothing"); x=[1e9, 0.0, 10.0, 80.0], s=[""])
# The cells: (n_f, n_m, o_b, n_b).
for (nf, nm, ob, nb) in ((1, 2, 0, 0), (1, 2, 1, 0), (2, 2, 2, 0), (3, 2, 3, 0), (3, 3, 2, 2), (4, 2, 3, 1), (2, 5, 1, 3), (6, 6, 2, 5), (5, 2, 0, 1), (3, 4, 3, 3))
    g = (n_f=nf, n_m=nm, o_b=ob, n_b=nb, downstream=false)
    rows, cols = K.cell_structure(g)
    helper("cells", "$(ints(rows))|$(ints(cols))|$(ints(K.release_cells(g)))"; n=[nf, nm, ob, nb])
end

# --- the models --------------------------------------------------------------------------------------------

const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
const VERBOSE = !isempty(get(ENV, "KOMPARTMENT_FIXTURE_VERBOSE", ""))
examples = joinpath(@__DIR__, "..", "..", "examples")
const EXAMPLE = K.parse_json(read(joinpath(examples, "farfield.json"), String))

"""What went wrong, as the test reads it: the kind of refusal and its words."""
function refusal(e)
    e isa K.FarfError && return "path: $(e.message)"
    e isa K.SolverError && return "solver: $(e.message)"
    e isa K.BuildError && return "build: $(e.message)"
    e isa K.ValidationError && return "model: $(e.message)"
    rethrow(e)
end

"""The states the derivative is asked at: the initial one, and two made from it."""
function states(y0)
    n = length(y0)
    return [copy(y0), [y0[i] * (1.0 + 0.25 * ((i * 7) % 5)) + 0.5 * ((i * 3) % 4) for i in 1:n], [abs(y0[i]) * 0.3 + 1e-3 * i for i in 1:n]]
end
instants(sys) = (sys.start_time, sys.start_time + 0.37 * (sys.end_time - sys.start_time), sys.end_time)

"""A path as it was laid out."""
function layout_text(F)
    F isa K.FarfPath || return "semi-analytical"
    return join(["nf=$(F.nf) nm=$(F.nm) ob=$(F.ob) nb=$(F.nb) base=$(F.base) nnuc=$(F.nnuc) other_width=$(F.other_width) release_base=$(F.release_base) " *
                 "matched=$(F.matched) surface=$(F.surface) ncells=$(F.ncells) nnz=$(F.nnz) nrel=$(F.nrel) slots=$(F.slots) block=$(F.block_name)",
                 "keys=" * join(F.keys, ","), "key_pos=" * ints(F.key_pos .- 1), "rows=" * ints(F.rows), "cols=" * ints(F.cols),
                 "settings=" * ints(vec(F.setting_idx)), "row_flat=" * ints(F.row_flat), "col_flat=" * ints(F.col_flat), "rel=" * ints(vec(F.rel_idx)),
                 "release=" * ints(F.release_slots), "starts=" * ints(F.cell_starts), "lam=" * nums(F.lam)], "\n")
end

"""What a run has changed of a path: its rates and its layers."""
function path_text(F)
    F isa K.FarfPath || return "semi-analytical"
    return join(["vals=" * nums(F.vals), "rel_w=" * nums(vec(F.rel_w)), "d=" * nums(vec(F.layers_d)), "h=" * nums(vec(F.layers_h)), "q=" * nums(F.layers_q),
                 "laid_out=" * ints(Int.(F.laid_out))], "\n")
end
paths_text(sys) = join((path_text(F) for F in sys.data.FARF), "\n--\n")

"""The series the paths report."""
function outputs_text(sys, p)
    lines = String[]
    for o in K.outputs_of(sys, p)
        startswith(o["kind"], "farfield") || continue
        idx = o["index"] === nothing ? "-" : join(o["index"], ",")
        at = haskey(o, "offsets") ? "offsets=" * ints(o["offsets"]) : "offset=$(o["offset"])"
        push!(lines, "$(o["kind"])|$(o["block"])|$(something(o["nuclide"], "-"))|$idx|$(join(o["dims"], ","))|$(o["label"])|$(o["unit"])|$(o["source"])|$at")
    end
    return join(lines, "\n")
end

"""A run as the test compares it: the application's table of it, its counts, and what the paths said."""
function run_text(res)
    counts = join(("$key=$(res.stats[key])" for key in ("nsteps", "nfailed", "nfevals", "events", "jumps", "restarts") if haskey(res.stats, key)), " ")
    said_ = join(("$(w["block"]): $(w["message"])" for w in get(res.stats, "layers", Any[])), "\n")
    return "points=$(length(res.t)) $counts csv=$(fnv(K.to_csv(res)))\n$said_"
end
run_or_refusal(f) =
    try
        run_text(f())
    catch e
        refusal(e)
    end

function layers_text(layers)
    layers === nothing && return "none"
    lines = String[]
    for name in sort!(collect(keys(layers))), key in sort!(collect(keys(layers[name])))
        g = layers[name][key]
        push!(lines, "$name|$(replace(key, '\0' => '/'))|$(nums(g.d))|$(nums(g.h))|$(nums([g.q]))")
    end
    return join(lines, "\n")
end

"""Layers to hold that are not the model's own: every other combination's, a quarter thicker; of the rest, every other
one's with a layer too few, which a path does not take; the others left to the paths."""
function altered(layers)
    out = Dict{String,Dict{String,Any}}()
    k = 0
    for name in sort!(collect(keys(layers)))
        out[name] = Dict{String,Any}()
        for key in sort!(collect(keys(layers[name])))
            k += 1
            g = layers[name][key]
            if isodd(k)
                out[name][key] = (d=g.d .* 1.25, h=g.h .* 1.25, q=g.q)
            elseif k % 4 == 0
                out[name][key] = (d=g.d[1:end-1], h=g.h, q=g.q)
            end
        end
    end
    return out
end

"""The audit of a run, family by family."""
function audit_text(a)
    lines = ["worst=$(nums([a.worst])) at=$(nums([a.at])) family=$(something(a.worst_family, "-")) closed=$(a.closed)"]
    for f in a.families
        push!(lines, "$(f.name) idle=$(f.idle) scale=$(nums([f.scale])) worst=$(nums([f.worst])) relative=$(nums([f.relative])) at=$(nums([f.at]))")
    end
    push!(lines, "total scale=$(nums([a.total.scale])) worst=$(nums([a.total.worst])) relative=$(nums([a.total.relative])) at=$(nums([a.total.at]))")
    return join(lines, "\n")
end

function sections(model)
    out = K.JDict()
    numeric = K.jcopy(model)
    get!(numeric, "simulation", K.JDict())["jacobian"] = "numeric"
    p = K.Project(model)
    sys = K.build_system(p)
    out["layout"] = join((layout_text(F) for F in sys.data.FARF), "\n--\n")
    out["outputs"] = outputs_text(sys, p)

    # The derivative and every slot at a few instants, with the paths' rates and layers there;
    # then the tangents of the rates along a direction made up here.
    y0 = K.initial_state(sys)
    out["y0"] = nums(y0)
    K.prime_recorders!(sys, sys.start_time, y0)
    for (k, (t, y)) in enumerate(zip(instants(sys), states(y0)))
        try
            X = copy(K.evaluate_algebraic!(sys, t, y))
            dy = K.dydt(sys, t, y)
            out["X$k"] = nums(X)
            out["dy$k"] = nums(dy)
            out["paths$k"] = paths_text(sys)
        catch e
            out["X$k"] = refusal(e)
            break
        end
    end
    X = copy(sys.X)
    dX = [((i * 37) % 11 - 5) * 1e-3 * (abs(X[i]) + 1) for i in eachindex(X)]
    out["tangent"] = join((F isa K.FarfPath ?
                           try
                               T = K.FarfTangent(F)
                               still = K.farfield_tangent!(T, F, X, zeros(length(X)))
                               moving = K.farfield_tangent!(T, F, X, dX)
                               "still=$still moving=$moving\ndvals=$(nums(T.dvals))\ndrel=$(nums(vec(T.drel)))"
                           catch e
                               refusal(e)
                           end : "semi-analytical" for F in sys.data.FARF), "\n--\n")

    # The Jacobian: whether there is one, its pattern, and its values where the derivative was asked.
    sys = K.build_system(p)
    j = sys.jacobian
    an0 = j.analytic
    out["jacobian"] = "available=$(j.available) constant=$(j.constant) state_free=$(an0 === nothing ? "-" : an0.state_free) " *
                      "reason=$(something(j.reason, "")) budget_rows=$(something(j.budget_rows, "")) nnz=$(j.nnz) colours=$(j.colours)"
    out["pattern"] = ints(j.pattern.colptr .- 1) * "|" * ints(j.pattern.rowval .- 1)
    an = try
        K.Analytic(sys, j.pattern, K.full_budget(sys))
    catch e
        e isa K.NoDerivative || rethrow()
        out["plan"] = "refused: $(e.what)"
        nothing
    end
    if an !== nothing
        out["plan"] = "constant=$(an.constant) state_free=$(an.state_free) rows=$(length(an.g_rows)) entries=$(an.g_nnz)"
        y0 = K.initial_state(sys)
        K.prime_recorders!(sys, sys.start_time, y0)
        for (k, (t, y)) in enumerate(zip(instants(sys), states(y0)))
            J = zeros(j.nnz)
            out["J$k"] = try
                ok = K.analytic_evaluate!(J, an, t, y)
                "$(ok ? 1 : 0):" * nums(J) * "|" * nums(an.G)
            catch e
                refusal(e)
            end
        end
    end

    # Whole runs: with the Jacobian differenced, then as the model stands -- twice on one
    # system, the second run laying its layers out afresh -- and on layers held from outside.
    out["run numeric"] = run_or_refusal(() -> (pn = K.Project(numeric); K.run_project(pn; system=K.build_system(pn))))
    sys = K.build_system(p)
    res = try
        K.run_project(p; system=sys)
    catch e
        out["run"] = refusal(e)
        nothing
    end
    if res !== nothing
        out["run"] = run_text(res)
        a = K.mass_balance(res)
        a === nothing || (out["audit"] = audit_text(a))
    end
    out["paths after"] = paths_text(sys)
    out["run again"] = run_or_refusal(() -> K.run_project(p; system=sys))
    layers = try
        K.whole_layers(sys, p)
    catch e
        out["layers"] = refusal(e)
        nothing
    end
    if layers !== nothing
        out["layers"] = layers_text(layers)
        out["run on its layers"] = run_or_refusal(() -> K.run_project(p; system=sys, layers=layers))
        other = altered(layers)
        out["run on other layers"] = run_or_refusal(() -> K.run_project(p; system=sys, layers=other))
        out["paths on other layers"] = paths_text(sys)
        out["run let go"] = run_or_refusal(() -> K.run_project(p; system=sys))
    end
    return out
end

cases = Any[]
function record(name, model)
    row = K.JDict("name" => name, "model" => model)
    out = try
        sections(model)
    catch e
        (e isa K.BuildError || e isa K.ValidationError) || (println(stderr, "while working out ", name); rethrow())
        K.JDict("refused" => refusal(e))
    end
    isempty(DUMPS) || write(joinpath(DUMPS, "$name.farfield.julia.txt"), join(("## $k\n$(replace(v, "," => "\n"))" for (k, v) in out), "\n"))
    VERBOSE && println(rpad(name, 40), " ", join(("$k: $(first(v, 150))" for (k, v) in out if !startswith(v, r"[0-9a-f]{16}|nf=") && length(v) < 600), "\n" * " "^41))
    row["values"] = K.JDict(k => kept(v) for (k, v) in out)
    push!(cases, row)
end

"""The bundled example with a shorter path and fewer output times, its block changed by `block` and the model by `f`."""
function farfield(f=m -> nothing; n_f=6, n_m=6, block...)
    m = K.jcopy(EXAMPLE)
    for key in ("layout", "view", "description")
        delete!(m, key)
    end
    path = m["farfields"][1]
    path["n_f"] = n_f
    path["n_m"] = n_m
    for (k, v) in block
        path[String(k)] = v
    end
    sim = m["simulation"]
    sim["end_time"] = 2e4
    sim["output_points"] = 12
    sim["output_times"] = Any[K.JDict("kind" => "log", "points" => 12, "from" => 1, "to" => nothing)]
    f(m)
    return m
end
J(text) = K.parse_json(text)

# --- the layers and the outflow --------------------------------------------------------------------
record("matched, every cell reported", farfield(report_cells=true))
record("matched, as long as the example", farfield(n_f=20, n_m=20))
record("reference, as long as the example", farfield(n_f=20, n_m=20, grid="reference"))
for grid in ("reference", "matched"), (ob, nb) in ((0, ""), (0, 2), (1, ""), (1, 0), (1, 2), (2, ""), (2, 3), (3, ""), (3, 1), (4, ""), (4, 0), (4, 2))
    record("$grid, outflow $ob with $(nb == "" ? "no" : nb) extra cells", farfield(grid=grid, o_b=ob, n_b=nb, report_cells=(ob == 3)))
end
record("matched, little dispersion", farfield(grid="matched", o_b=4, n_b=2, pe="25"))
record("reference, no dispersion at all", farfield(grid="reference", o_b=3, n_b="", pe="50"))
record("reference, two layers and one cell", farfield(grid="reference", n_f=1, n_m=2, o_b=1, n_b=""))
record("matched, two layers and two cells", farfield(grid="matched", n_f=2, n_m=2, o_b=2, n_b=""))
record("matched, dense matrix", farfield(m -> (m["simulation"]["matrix"] = "dense"); grid="matched"))
record("reference, Rosenbrock", farfield(m -> (m["simulation"]["solver"] = "ros23"); grid="reference", n_f=4, n_m=3))

# --- the surface, the first layer, the rates per nuclide ----------------------------------------------
record("a_w and rates per nuclide",
       farfield(grid="matched", surface="aw", aw="2000", kd_f="1e-4", eps_m="0.002",
                entries=Any[J("""{"index":{"Radionuclides":"Th-230"},"kd_f":"5e-3","eps_m":"0.001"}"""), J("""{"index":{"Radionuclides":"U-234"},"kd_f":"2e-4"}""")]))
record("an aperture, reference, a first layer", farfield(grid="reference", surface="aperture", aperture="0.001", pen_dep_0="0.001"))
record("an aperture, matched, a first layer", farfield(grid="matched", surface="aperture", aperture="0.002", pen_dep_0="0.0005"))
record("matched, a first layer that is the even one", farfield(grid="matched", pen_dep="6", pen_dep_0="1"))
record("coarse at depth", farfield(grid="matched", n_m=3, pen_dep_0="0.0001"))
record("held in moles", farfield(m -> (m["decay_unit"] = "mol"); unit="mol/year", report_cells=true, n_f=2, n_m=2))
record("held in a unit with no time", farfield(unit="kg", n_f=2, n_m=2))
record("held in no unit", farfield(unit="", n_f=2, n_m=2))

# --- decay -----------------------------------------------------------------------------------------
record("no decay, matched", farfield(grid="matched", handle_decay=false))
record("no decay, reference", farfield(grid="reference", handle_decay=false, o_b=1, n_b=0))
record("a longer chain", farfield(m -> (m["nuclides"] = Any["U-238", "U-234", "Th-230", "Ra-226", "Pb-210"]; m["expressions"] = Any[];
                                        m["parameters"][4]["entries"] = Any[]); grid="matched"))
record("the audit, matched", farfield(m -> (m["simulation"]["mass_balance"] = true); grid="matched", n_f=4, n_m=3))
record("the audit, reference, no decay", farfield(m -> (m["simulation"]["mass_balance"] = true); grid="reference", handle_decay=false, n_f=4, n_m=3))

# --- settings that follow the clock ----------------------------------------------------------------
record("T_w from a table, matched", farfield(m -> (m["lookups"] = Any[J("""{"name":"TW_factor","unit":"","interpolation":"linear","per_nuclide":false,
       "points":[[0,1.0],[1000,1.0],[5000,1.6],[12000,0.8],[20000,1.2]]}""")]); grid="matched", tw="50 * TW_factor"))
record("F from a table, reference", farfield(m -> (m["lookups"] = Any[J("""{"name":"F_table","unit":"year/m","interpolation":"linear","per_nuclide":false,
       "points":[[0,1e5],[3000,2e5],[9000,5e4],[20000,1e5]]}""")]); grid="reference", f="F_table"))
record("F on the clock, reference", farfield(grid="reference", f="1e5 * (1 + interpolationUseEndValues(time, 0, 0, 2e4, 1))"))
record("T_w on the clock, matched", farfield(grid="matched", tw="50 * (1 + 0.5 * rampUp(time, 1e3, 1e4))"))
record("Kd on the clock, reference", farfield(grid="reference", kd_m="Kd_matrix * (1 + rampUp(time, 1e3, 1e4))"))
record("Kd on the clock, matched", farfield(grid="matched", kd_m="Kd_matrix * (1 + rampUp(time, 1e3, 1e4))", kd_f="1e-5 * rampUp(time, 0, 5e3)"))
record("the depth on the clock, matched", farfield(grid="matched", pen_dep="12.5 * (1 + rampUp(time, 1e3, 1e4))"))
record("the depth on the clock, reference", farfield(grid="reference", pen_dep="12.5 * (1 + rampUp(time, 1e3, 1e4))", pen_dep_0="0.002 * (1 + rampUp(time, 2e3, 6e3))"))
record("the clock interpolated", farfield(m -> (m["simulation"]["min_change_time"] = 500); grid="matched", tw="50 * (1 + 0.5 * rampUp(time, 1e3, 1e4))"))
record("Pe on the clock through one half", farfield(grid="reference", pe="30 - 25 * rampUp(time, 1e3, 1e4)", o_b=3, n_b=1))

record("one nuclide's Kd on the clock, matched",
       farfield(grid="matched", entries=Any[J("""{"index":{"Radionuclides":"Th-230"},"kd_m":"0.05 * (1 + rampUp(time, 1e3, 1e4))","kd_f":"1e-4 * rampUp(time, 0, 5e3)"}""")]))
record("one nuclide's Kd on the clock, reference",
       farfield(grid="reference", entries=Any[J("""{"index":{"Radionuclides":"U-234"},"kd_m":"0.0017 * (1 + rampUp(time, 1e3, 1e4))","de_m":"1e-6 * (1 + rampUp(time, 5e3, 1e4))"}""")]))

# --- settings that follow the state ----------------------------------------------------------------
record("T_w on the state", farfield(grid="reference", tw="50 * (1 + Vault[U-238] / 1e12)"))
record("Kd on the state", farfield(grid="matched", kd_m="Kd_matrix * (1 + Well / (1e3 + Well))"))

# --- what a path refuses in a run ----------------------------------------------------------------------
record("Pe turns negative", farfield(grid="reference", pe="10 - 20 * (time > 1e4)"))
record("Pe is zero", farfield(grid="matched", pe="0"))
record("Pe is not a number", farfield(grid="reference", pe="0 / 0"))
record("a_w is zero", farfield(grid="reference", surface="aw", aw="0"))
record("a_w is infinite", farfield(grid="matched", surface="aw", aw="1 / 0"))
record("the aperture is negative", farfield(grid="reference", surface="aperture", aperture="0 - 0.001"))
record("F is zero", farfield(grid="matched", f="0"))
record("T_w is zero under F", farfield(grid="reference", tw="0"))
record("T_w is zero under a_w", farfield(grid="reference", surface="aw", aw="2000", tw="0"))
record("T_w is negative under an aperture", farfield(grid="matched", surface="aperture", aperture="0.001", tw="0 - 50"))
record("Kd in the matrix negative, matched", farfield(m -> (m["parameters"][4]["entries"][3]["value"] = -0.05); grid="matched"))
record("Kd in the matrix negative, reference", farfield(m -> (m["parameters"][4]["entries"][3]["value"] = -0.05); grid="reference"))
record("the diffusivity not a number", farfield(grid="reference", de_m="De_matrix * (0 / 0)"))
record("the density negative on the clock", farfield(grid="matched", rho_m="2700 - 3000 * (time > 5e3)"))
record("nothing to diffuse into", farfield(grid="reference", eps_m="0", kd_m="0"))
record("nothing to diffuse into, matched", farfield(grid="matched", eps_m="0", kd_m="0 * Kd_matrix"))
record("the depth is zero, matched", farfield(grid="matched", pen_dep="12.5 * 0"))
record("the depth is zero, reference", farfield(grid="reference", pen_dep="12.5 * 0"))
record("layers that cannot add up, matched", farfield(grid="matched", pen_dep_0="2.5 + 0 * time"))
record("layers that cannot add up, reference", farfield(grid="reference", pen_dep_0="2.5 + 0 * time"))
record("layers that cannot add up, said of the model", farfield(grid="reference", pen_dep_0="2.5"))
record("a negative Kd, said of the model", farfield(grid="matched", kd_m="-1"))
record("a method there is none of", farfield(method="guessed"))
record("a grid there is none of", farfield(grid="finer"))
record("too few cells for the outflow", farfield(n_f=2, o_b=3, n_b=""))
record("semi-analytical", farfield(method="semi-analytical"))

# --- other index lists, several paths --------------------------------------------------------------
function two_paths(grid; n_f=4, n_m=4, tw="TW_path * (1 + 0.5 * rampUp(time, 1e3, 1e4))", block...)
    farfield(; n_f, n_m, grid, index_lists=Any["Radionuclides", "Paths"], tw, block...) do m
        m["index_lists"] = Any[J("""{"name":"Paths","indices":[{"name":"Short","enabled":true},{"name":"Long","enabled":true}]}""")]
        for c in m["compartments"]
            c["index_lists"] = Any["Radionuclides", "Paths"]
        end
        for t in m["transfers"]
            haskey(t, "index_lists") && (t["index_lists"] = Any["Radionuclides", "Paths"])
        end
        push!(m["parameters"], J("""{"name":"TW_path","value":50,"index_lists":["Paths"],"entries":[{"index":{"Paths":"Long"},"value":120}]}"""))
        m["expressions"] = Any[]
    end
end
record("two combinations, matched", two_paths("matched"))
record("two combinations, reference", two_paths("reference"))
record("two combinations, both coarse", two_paths("matched"; n_m=3, pen_dep_0="0.0001", tw="TW_path"))
record("two combinations, one refused", two_paths("matched"; tw="90 - TW_path"))
record("two combinations, one refused, reference", two_paths("reference"; tw="90 - TW_path"))
record("three dimensions", farfield(n_f=3, n_m=3, grid="matched", index_lists=Any["Paths", "Radionuclides", "Zones"], tw="TW_path * TW_zone", report_cells=true) do m
    m["index_lists"] = Any[J("""{"name":"Paths","indices":["Short","Long"]}"""), J("""{"name":"Zones","indices":["North","South"]}""")]
    for c in m["compartments"]
        c["index_lists"] = Any["Paths", "Radionuclides", "Zones"]
    end
    for t in m["transfers"]
        haskey(t, "index_lists") && (t["index_lists"] = Any["Paths", "Radionuclides", "Zones"])
    end
    push!(m["parameters"], J("""{"name":"TW_path","value":50,"index_lists":["Paths"],"entries":[{"index":{"Paths":"Long"},"value":120}]}"""))
    push!(m["parameters"], J("""{"name":"TW_zone","value":1,"index_lists":["Zones"],"entries":[{"index":{"Zones":"South"},"value":1.5}]}"""))
    m["expressions"] = Any[]
end)
record("a tracer, no lists at all", J("""{"name":"tracer",
  "simulation":{"start_time":0,"end_time":5000,"output_points":20,"spacing":"log","solver":"ndf","rtol":1e-8,"abstol":1e-16,"time_unit":"year"},
  "compartments":[{"name":"Source","initial":"1000"},{"name":"Sink","initial":"0"}],
  "transfers":[{"name":"Leach","from":"Source","to":"Rock","rate":"1e-3","multiply_by_donor":true},
               {"name":"Out","from":"Rock","to":"Sink","rate":"Rock","multiply_by_donor":false}],
  "farfields":[{"name":"Rock","index_lists":[],"tw":"20","surface":"f","f":"2e4","kd_f":"0","kd_m":"1e-3","de_m":"1e-4","eps_m":"0.005","rho_m":"2700","pe":"10",
                "pen_dep":"0.5","pen_dep_0":"","n_f":8,"n_m":6,"o_b":4,"n_b":"","grid":"matched","handle_decay":true,"report_cells":true}]}"""))

record("a tracer along two routes", J("""{"name":"tracer",
  "simulation":{"start_time":0,"end_time":5000,"output_points":20,"spacing":"log","solver":"ndf","rtol":1e-8,"abstol":1e-16,"time_unit":"year"},
  "index_lists":[{"name":"Routes","indices":["Fast","Slow","Slower"]}],
  "parameters":[{"name":"T","value":20,"index_lists":["Routes"],"entries":[{"index":{"Routes":"Slow"},"value":60},{"index":{"Routes":"Slower"},"value":200}]}],
  "compartments":[{"name":"Source","initial":"1000","index_lists":["Routes"]},{"name":"Sink","initial":"0","index_lists":["Routes"]}],
  "transfers":[{"name":"Leach","from":"Source","to":"Rock","rate":"1e-3","multiply_by_donor":true},
               {"name":"Out","from":"Rock","to":"Sink","rate":"Rock","multiply_by_donor":false,"index_lists":["Routes"]}],
  "farfields":[{"name":"Rock","index_lists":["Routes"],"tw":"T","surface":"f","f":"2e4","kd_f":"0","kd_m":"1e-3","de_m":"1e-4","eps_m":"0.005","rho_m":"2700","pe":"10",
                "pen_dep":"0.5","pen_dep_0":"1e-5","n_f":4,"n_m":3,"o_b":4,"n_b":"","grid":"matched","handle_decay":true,"report_cells":false,"unit":"g/year"}]}"""))

"""Paths of made-up nuclides: a chain with a branch, fed by a compartment, an inflow and packages that fail."""
made(f=m -> nothing) = (m = J("""{"name":"made",
  "simulation":{"start_time":0,"end_time":3e4,"output_points":16,"spacing":"log","solver":"ndf","rtol":1e-8,"abstol":1e-16,"time_unit":"year"},
  "nuclides":["Aa-1","Bb-2","Cc-3"],"half_lives":{"Aa-1":2000,"Bb-2":800,"Cc-3":5000},"chains":[["Aa-1","Bb-2",0.6],["Aa-1","Cc-3",0.4]],"decay_unit":"mol",
  "parameters":[{"name":"k_leach","value":1e-3,"index_lists":[]}],
  "compartments":[{"name":"Near","initial":"0","index_lists":["Radionuclides"],"entries":[{"index":{"Radionuclides":"Aa-1"},"initial":"500"}]},
                  {"name":"Mid","initial":"0","index_lists":["Radionuclides"]},{"name":"Down","initial":"0","index_lists":["Radionuclides"]}],
  "transfers":[{"name":"Leach","from":"Near","to":"Rock","rate":"k_leach","multiply_by_donor":true},
               {"name":"Between","from":"Rock","to":"Mid","rate":"Rock","multiply_by_donor":false,"index_lists":["Radionuclides"]},
               {"name":"Onward","from":"Mid","to":"Deep","rate":"0.05","multiply_by_donor":true},
               {"name":"Out","from":"Deep","to":"Down","rate":"Deep","multiply_by_donor":false,"index_lists":["Radionuclides"]}],
  "inflows":[{"name":"Drip","to":"Deep","rate":"1e-3 * (time > 2000)","index_lists":["Radionuclides"]}],
  "farfields":[{"name":"Rock","index_lists":["Radionuclides"],"surface":"f","tw":"50","f":"5e4","kd_f":"2e-4","kd_m":"1e-3","de_m":"1e-4",
                "eps_m":"0.005","rho_m":"2700","pe":"10","pen_dep":"0.1","pen_dep_0":"","n_f":5,"n_m":4,"o_b":4,"n_b":"","grid":"matched",
                "handle_decay":true,"report_cells":false,"unit":"mol/year",
                "entries":[{"index":{"Radionuclides":"Bb-2"},"kd_f":"5e-4","kd_m":"3e-3","de_m":"2e-4"},{"index":{"Radionuclides":"Cc-3"},"kd_f":"1e-4","kd_m":"5e-4"}]},
               {"name":"Deep","index_lists":["Radionuclides"],"surface":"aw","aw":"800","tw":"200","kd_f":"0","kd_m":"2e-3","de_m":"5e-5",
                "eps_m":"0.003","rho_m":"2600","pe":"4","pen_dep":"0.3","pen_dep_0":"0.004","n_f":4,"n_m":3,"o_b":1,"n_b":"","grid":"reference",
                "handle_decay":true,"report_cells":true,"unit":"mol/year"}]}"""); f(m); m)
record("two paths in a row", made())
record("two paths in a row, stable", made(m -> (m["half_lives"] = J("""{"Aa-1":"stable","Bb-2":"stable","Cc-3":"stable"}"""); m["chains"] = Any[])))
record("two paths in a row, one without decay", made(m -> (m["farfields"][2]["handle_decay"] = false)))
record("two paths in a row, both matched and coarse", made(m -> (m["farfields"][2]["grid"] = "matched"; m["farfields"][2]["pen_dep_0"] = "1e-5"; m["farfields"][1]["n_m"] = 2;
                                                                 m["farfields"][1]["pen_dep_0"] = "1e-4")))
record("two paths in a row, the audit", made(m -> (m["simulation"]["mass_balance"] = true)))
record("two paths, the second refused", made(m -> (m["farfields"][2]["aw"] = "800 - 1000 * (time > 1e4)")))
record("a path fed by an inflow alone", made(m -> (m["transfers"] = m["transfers"][2:4]; m["inflows"][1]["to"] = "Rock"; m["inflows"][1]["rate"] = "2e-3")))
record("a path nothing leaves", made(m -> (m["transfers"] = m["transfers"][1:1]; m["farfields"] = m["farfields"][1:1]; m["inflows"] = Any[])))
record("a path straight into a path", made(m -> (m["transfers"][2]["to"] = "Deep")))
record("a path read with an index it has not", made(m -> (m["expressions"] = Any[J("""{"name":"Dose","equation":"Rock[Nope]","index_lists":[]}""")])))
record("a path's release given as a rate by the donor", made(m -> (m["transfers"][2]["multiply_by_donor"] = true)))
record("a path whose release is read", made(m -> (m["expressions"] = Any[J("""{"name":"Dose","equation":"Deep * 2.5 + Rock[Aa-1]","index_lists":["Radionuclides"]}""")])))

# --- restarts: packages that fail, corners, events ------------------------------------------
packages(m; fail_at="700") = (m["waste_packages"] = Any[J("""{"name":"Pack","index_lists":["Radionuclides"],"failure":"at","fail_at":"$fail_at","inventory":"0","irf":"0.2",
  "degradation_rate":"2e-3","handle_decay":true,"entries":[{"index":{"Radionuclides":"Aa-1"},"inventory":"1000"}]}""")];
                                 push!(m["transfers"], J("""{"name":"Carrier","from":"Pack","to":"Near","rate":"Pack","multiply_by_donor":false,"index_lists":["Radionuclides"]}""")))
record("packages that fail before a path", made(m -> packages(m)))
record("packages straight into a path", made(m -> (packages(m); m["transfers"][end]["to"] = "Rock")))
record("packages that fail before a path, the audit", made(m -> (packages(m); m["simulation"]["mass_balance"] = true)))
record("packages failing over time before a path", made(m -> (packages(m); p = m["waste_packages"][1]; p["failure"] = "weibull"; p["fail_start"] = "100"; p["fail_scale"] = "3000";
                                                            p["fail_shape"] = "2"; p["packages"] = 20)))
record("a corner and an event at a time", made(m -> (m["farfields"][1]["tw"] = "50 * (1 + (time > 5000))";
                                                      m["events"] = Any[J("""{"name":"Flood","timing":"at","at":"9000","actions":[{"kind":"move","from":"Near","to":"","fraction":"0.5"}]}""")])))
record("events set off by a trigger", made(m -> (m["triggers"] = Any[J("""{"name":"Arrived","first":"Down[Aa-1]","second":"1e-3","index_lists":[]}"""),
                                                                      J("""{"name":"Late","first":"time","second":"12000","index_lists":[]}""")];
                                                 m["events"] = Any[J("""{"name":"Flush","timing":"trigger","trigger":"Arrived","actions":[{"kind":"move","from":"Near","to":"","fraction":"0.5"}]}""")];
                                                 m["snapshots"] = Any[J("""{"name":"Held","target":"Rock","trigger":"Late","initial":"0"}""")];
                                                 m["min_maxes"] = Any[J("""{"name":"Peak","target":"Deep"}""")];
                                                 m["running_means"] = Any[J("""{"name":"Mean","target":"Rock","start_trigger":"Late"}""")])))
record("a delay of a release", made(m -> (m["delays"] = Any[J("""{"name":"Later","target":"Deep","delay":"500"}""")])))

path = joinpath(@__DIR__, "..", "tests", "fixtures", "farfield.json")
write(path, K.json_text(K.JDict("helpers" => helpers, "cases" => cases); indent=0))
println(path, ": ", length(helpers), " helper calls, ", length(cases), " models, ", count(c -> haskey(c["values"], "refused"), cases), " refused")
