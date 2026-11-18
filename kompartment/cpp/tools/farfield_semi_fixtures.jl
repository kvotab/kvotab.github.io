# Writes tests/fixtures/farfield_semi.json: what the Julia engine makes of
# far-field paths worked out semi-analytically (farfield_semi.jl), for the C++
# engine's tests to compare with (tests/test_farfield_semi.cpp).
#
#     julia --project=../julia tools/farfield_semi_fixtures.jl
#
# With parity on, models made up here to reach every branch of the runtime: the
# bundled far-field example and a made-up chain with a branch, paths
# semi-analytical alone, in a row and beside paths on cells, fed by transfers,
# inflows and packages that fail, on another index list, plug flow, infinite
# depth, each way of giving the wetted surface, restarts at corners and at
# events, responses that miss their mass balance, and what a semi-analytical
# path refuses. For each: the paths as laid out and their unit responses; the
# series they report; the derivative and every slot at a few instants; a
# history recorded step by step -- an instant told twice, a release asked for
# behind the last record, an instant earlier than the last -- with the
# convolvers it leaves; the Jacobian; whole runs (differenced and exact, and
# again on the same system) with the warnings they give; and a run on settings
# changed under the system. A short text is kept as it is, a long one as a
# hash; with KOMPARTMENT_FIXTURE_DUMPS set every text is written there
# (`<name>.semi.julia.txt`).

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
nums(v) = join((isnan(x) ? "nan" : bits(Float64(x)) for x in v), ",")
ints(v) = join(v, ",")
kept(text::String) = length(text) <= 400 ? "=" * text : "#" * fnv(text)
J(text) = K.parse_json(text)

const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
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

function states(y0)
    n = length(y0)
    return [copy(y0), [y0[i] * (1.0 + 0.25 * ((i * 7) % 5)) + 0.5 * ((i * 3) % 4) for i in 1:n], [abs(y0[i]) * 0.3 + 1e-3 * i for i in 1:n]]
end
instants(sys) = (sys.start_time, sys.start_time + 0.37 * (sys.end_time - sys.start_time), sys.end_time)

"""A semi-analytical path as it was laid out (a path on cells by its name alone)."""
function layout_text(F)
    F isa K.LaplaceFarfPath || return "cells"
    D = F.D === nothing ? "none" : join([nums(F.D.lam), ints(F.D.ioff), ints(F.D.icnt), ints(F.D.ipar), nums(F.D.icoef)], "/")
    return join(["base=$(F.base) nnuc=$(F.nnuc) other_width=$(F.other_width) release_base=$(F.release_base) surface=$(F.surface) " *
                 "slots=$(F.slots) span=$(nums([F.span])) block=$(F.block_name)",
                 "keys=" * join(F.keys, ","), "single=" * join(sort!(collect(F.is_single)), ","), "dim_off=" * ints(F.dim_off),
                 "single_off=" * ints(F.single_off), "release=" * ints(F.release_slots), "held=" * ints(F.held_idx),
                 "starts=" * ints(F.cell_starts), "names=" * (F.names === nothing ? "-" : join(F.names, ",")), "decay=" * D,
                 "in=" * ints(F.in_tgt) * "|" * ints(F.in_rate) * "|" * ints(F.in_donor),
                 "settings=" * ints(vec(K.farfield_setting_slots(F)))], "\n")
end

"""A path's unit responses: each combination's kernels, the pairs it has and those that missed."""
function responses_text(F)
    F isa K.LaplaceFarfPath || return "cells"
    lines = String[]
    for (o, combo) in enumerate(F.combos)
        if combo === nothing
            push!(lines, "combination $o: none")
            continue
        end
        push!(lines, "combination $o: pairs=$(combo.pairs)")
        for m in combo.misses
            push!(lines, "missed $(m.i) $(m.j) " * nums([m.integral, m.expected, m.T0, m.rel, m.until]))
        end
        for (q, k) in enumerate(combo.kernels)
            k === nothing && continue
            push!(lines, "kernel $(q - 1) n=$(k.n) np=$(k.np) " * nums([k.t0, k.t_end, k.m0, k.tm0]) * " " *
                         fnv(join([nums(k.t), nums(vec(k.a)), nums(k.d), nums(k.ahead), nums(vec(permutedims(k.P)))], "|")))
        end
    end
    return join(lines, "\n")
end

"""One convolver: its blocks (hashed), its last records and its impulses."""
function convolver_text(cv)
    bm = reduce(vcat, (collect(m) for m in cv.bm); init=Float64[])
    bp = join((p === nothing ? "-" : nums(collect(p)) for p in cv.bp), ";")
    return "n=$(length(cv.bc)) at=$(cv.compact_at) count=$(cv.count) last=$(nums([cv.last_t])) rt=$(nums(cv.rt)) rv=$(nums(cv.rv)) " *
           "imp=$(nums(cv.imp_t))/$(nums(cv.imp_a)) ti=$(ints(cv.ti)) " * fnv(join([nums(cv.bc), nums(cv.bw), nums(bm), bp], "|"))
end

"""What a run has left on a semi-analytical path: its records, its impulses, the releases kept and its convolvers."""
function history_text(F)
    F isa K.LaplaceFarfPath || return "cells"
    lines = ["records=$(length(F.rec_t)) " * fnv(nums(F.rec_t)) * " last=$(nums([F.last_t])) ready=$(F.ready)"]
    for s in 1:F.slots
        push!(lines, "slot $(s - 1) " * fnv(nums(F.rec_v[s])) * " imp=$(nums(F.imp_t[s]))/$(nums(F.imp_v[s]))")
    end
    ks = sort!(collect(keys(F.releases)))
    push!(lines, "releases=$(length(ks)) " * fnv(join((nums([k]) * ":" * nums(F.releases[k]) for k in ks), ";")))
    if F.live === nothing
        push!(lines, "live none")
    else
        for cv in F.live
            push!(lines, convolver_text(cv))
        end
    end
    return join(lines, "\n")
end
histories_text(sys) = join((history_text(F) for F in sys.data.FARF), "\n--\n")

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
    said_ = join(("$(w["block"]): $(w["message"])" for key in ("farfield", "layers") for w in get(res.stats, key, Any[])), "\n")
    return "points=$(length(res.t)) $counts csv=$(fnv(K.to_csv(res)))\n$said_"
end
run_or_refusal(f) =
    try
        run_text(f())
    catch e
        refusal(e)
    end

function audit_text(a)
    lines = ["worst=$(nums([a.worst])) at=$(nums([a.at])) family=$(something(a.worst_family, "-")) closed=$(a.closed)"]
    for f in a.families
        push!(lines, "$(f.name) idle=$(f.idle) scale=$(nums([f.scale])) worst=$(nums([f.worst])) relative=$(nums([f.relative])) at=$(nums([f.at]))")
    end
    push!(lines, "total scale=$(nums([a.total.scale])) worst=$(nums([a.total.worst])) relative=$(nums([a.total.relative])) at=$(nums([a.total.at]))")
    return join(lines, "\n")
end

"""The releases of every semi-analytical path in X, and their current weights at t."""
function releases_text(sys, t)
    parts = String[]
    for F in sys.data.FARF
        F isa K.LaplaceFarfPath || continue
        push!(parts, nums([sys.X[s+1] for s in F.release_slots]) * " w=" * nums(K.laplace_current_weights(F, t)))
    end
    return join(parts, " / ")
end

"""A history recorded step by step on a system just built: smooth states, an instant told twice with
what the paths hold moved between, the release asked for behind the last record and between records,
an instant earlier than the last (forgetting what came after), and on."""
function history_sections!(out, p)
    sys = K.build_system(p)
    y0 = K.initial_state(sys)
    K.prime_recorders!(sys, sys.start_time, y0)
    span = sys.end_time - sys.start_time
    n = length(y0)
    state(k) = [y0[i] * (1.0 + 0.01 * k) + 1e-3 * ((i * 7 + k) % 5) + 0.05 * k * ((i % 3) == 0) for i in 1:n]
    times = [(x = k / 90; sys.start_time + span * (x * x * x)) for k in 1:90]
    lines = String[]
    try
        for k in 1:90
            t = times[k]
            y = state(k)
            if k == 30
                # the same instant again, what the paths hold moved: an amount delivered at once
                K.store_step!(sys, t, y)
                y2 = copy(y)
                for F in sys.data.FARF
                    F isa K.LaplaceFarfPath || continue
                    for s in F.held_idx
                        y2[s+1] += 0.25 * (1 + abs(y2[s+1]))
                    end
                end
                K.store_step!(sys, t, y2)
                push!(lines, "twice $k: " * releases_text(sys, t))
                continue
            end
            if k == 50
                # the release behind the last record, and between the records before it
                K.evaluate_algebraic!(sys, times[40], state(40))
                push!(lines, "behind $k: " * releases_text(sys, times[40]))
                K.evaluate_algebraic!(sys, 0.5 * (times[44] + times[45]), state(44))
                push!(lines, "between $k: " * releases_text(sys, 0.5 * (times[44] + times[45])))
            end
            if k == 70
                # an instant earlier than the last: what came after it is forgotten
                K.store_step!(sys, times[65], state(65))
                push!(lines, "earlier $k: " * releases_text(sys, times[65]))
            end
            K.store_step!(sys, t, y)
            if k % 9 == 0
                ahead = t + 0.3 * (times[min(k + 1, 90)] - t) + 1e-9 * span
                K.evaluate_algebraic!(sys, ahead, state(k + 1))
                push!(lines, "ahead $k: " * releases_text(sys, ahead))
                push!(lines, "dy $k: " * nums(K.dydt(sys, ahead, state(k + 1))))
            end
        end
        out["history steps"] = join(lines, "\n")
        out["history"] = histories_text(sys)
        # A copy, then its own steps beside the system's: the same releases.
        C = K.clone_system(sys)
        t = times[90] * 1.01
        a = copy(K.evaluate_algebraic!(sys, t, state(91)))
        b = copy(K.evaluate_algebraic!(C, t, state(91)))
        out["history copied"] = (nums(a) == nums(b) ? "alike " : "otherwise ") * histories_text(C)
    catch e
        out["history steps"] = join(lines, "\n") * "\n" * refusal(e)
    end
end

function sections(model; changed=nothing)
    out = K.JDict()
    numeric = K.jcopy(model)
    get!(numeric, "simulation", K.JDict())["jacobian"] = "numeric"
    p = K.Project(model)
    sys = K.build_system(p)
    out["layout"] = join((layout_text(F) for F in sys.data.FARF), "\n--\n")
    out["responses"] = join((responses_text(F) for F in sys.data.FARF), "\n--\n")
    out["warnings"] = join(("$(w["block"]): $(w["message"])" for w in K.farfield_warnings(sys).farfield), "\n")
    out["outputs"] = outputs_text(sys, p)

    y0 = K.initial_state(sys)
    out["y0"] = nums(y0)
    K.prime_recorders!(sys, sys.start_time, y0)
    out["primed"] = histories_text(sys)
    for (k, (t, y)) in enumerate(zip(instants(sys), states(y0)))
        try
            X = copy(K.evaluate_algebraic!(sys, t, y))
            dy = K.dydt(sys, t, y)
            out["X$k"] = nums(X)
            out["dy$k"] = nums(dy)
        catch e
            out["X$k"] = refusal(e)
            break
        end
    end
    history_sections!(out, p)

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
        # some history first, so that the step being taken carries the current inflow with a weight
        for (q, f) in enumerate((1e-3, 1e-2, 3e-2))
            K.store_step!(sys, sys.start_time + f * (sys.end_time - sys.start_time), y0 .* (1 + 0.1 * q))
        end
        for (k, (t, y)) in enumerate(zip(instants(sys), states(y0)))
            Jv = zeros(j.nnz)
            tt = max(t, sys.start_time + 0.05 * (sys.end_time - sys.start_time))
            out["J$k"] = try
                ok = K.analytic_evaluate!(Jv, an, tt, y)
                "$(ok ? 1 : 0):" * nums(Jv) * "|" * nums(an.G)
            catch e
                refusal(e)
            end
        end
    end

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
    out["history after"] = histories_text(sys)
    out["run again"] = run_or_refusal(() -> K.run_project(p; system=sys))
    if changed !== nothing
        # a parameter the paths read, changed under the system: the next run works the responses out again
        name, value = changed
        e = sys.builder.param_by_name[name]
        for q in 0:e.width-1
            sys.P[e.base+q+1] = value
        end
        K.evaluate_invariant!(sys)
        out["run changed"] = run_or_refusal(() -> K.run_project(p; system=sys))
    end
    return out
end

cases = Any[]
function record(name, model; changed=nothing)
    t0 = time()
    row = K.JDict("name" => name, "model" => model, "changed" => changed === nothing ? nothing : Any[changed[1], bits(changed[2])])
    out = try
        sections(model; changed)
    catch e
        (e isa K.BuildError || e isa K.ValidationError) || (println(stderr, "while working out ", name); rethrow())
        K.JDict("refused" => refusal(e))
    end
    isempty(DUMPS) || write(joinpath(DUMPS, "$name.semi.julia.txt"), join(("## $k\n$(replace(v, "," => "\n"))" for (k, v) in out), "\n"))
    row["values"] = K.JDict(k => kept(v) for (k, v) in out)
    push!(cases, row)
    println(rpad(name, 52), round(time() - t0; digits=2), " s  ", haskey(out, "refused") ? first(out["refused"], 90) : "")
    flush(stdout)
end

"""The bundled example worked out semi-analytically, over a shorter span with fewer output times."""
function semi(f=m -> nothing; block...)
    m = K.jcopy(EXAMPLE)
    for key in ("layout", "view", "description")
        delete!(m, key)
    end
    path = m["farfields"][1]
    path["method"] = "semi-analytical"
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

"""Paths of made-up nuclides, a chain with a branch, the first (`which` = 1), the second (2) or both (3) semi-analytical."""
function made(f=m -> nothing; which=3)
    m = J("""{"name":"made",
  "simulation":{"start_time":0,"end_time":3e4,"output_points":16,"spacing":"log","solver":"ndf","rtol":1e-8,"abstol":1e-16,"time_unit":"year"},
  "nuclides":["Aa-1","Bb-2","Cc-3"],"half_lives":{"Aa-1":2000,"Bb-2":800,"Cc-3":5000},"chains":[["Aa-1","Bb-2",0.6],["Aa-1","Cc-3",0.4]],"decay_unit":"mol",
  "parameters":[{"name":"k_leach","value":1e-3,"index_lists":[]},{"name":"Pe_rock","value":10,"index_lists":[]}],
  "compartments":[{"name":"Near","initial":"0","index_lists":["Radionuclides"],"entries":[{"index":{"Radionuclides":"Aa-1"},"initial":"500"}]},
                  {"name":"Mid","initial":"0","index_lists":["Radionuclides"]},{"name":"Down","initial":"0","index_lists":["Radionuclides"]}],
  "transfers":[{"name":"Leach","from":"Near","to":"Rock","rate":"k_leach","multiply_by_donor":true},
               {"name":"Between","from":"Rock","to":"Mid","rate":"Rock","multiply_by_donor":false,"index_lists":["Radionuclides"]},
               {"name":"Onward","from":"Mid","to":"Deep","rate":"0.05","multiply_by_donor":true},
               {"name":"Out","from":"Deep","to":"Down","rate":"Deep","multiply_by_donor":false,"index_lists":["Radionuclides"]}],
  "inflows":[{"name":"Drip","to":"Deep","rate":"1e-3 * (time > 2000)","index_lists":["Radionuclides"]}],
  "farfields":[{"name":"Rock","index_lists":["Radionuclides"],"surface":"f","tw":"50","f":"5e4","kd_f":"2e-4","kd_m":"1e-3","de_m":"1e-4",
                "eps_m":"0.005","rho_m":"2700","pe":"Pe_rock","pen_dep":"0.1","pen_dep_0":"","n_f":5,"n_m":4,"o_b":4,"n_b":"","grid":"matched",
                "handle_decay":true,"report_cells":false,"unit":"mol/year",
                "entries":[{"index":{"Radionuclides":"Bb-2"},"kd_f":"5e-4","kd_m":"3e-3","de_m":"2e-4"},{"index":{"Radionuclides":"Cc-3"},"kd_f":"1e-4","kd_m":"5e-4"}]},
               {"name":"Deep","index_lists":["Radionuclides"],"surface":"aw","aw":"800","tw":"200","kd_f":"0","kd_m":"2e-3","de_m":"5e-5",
                "eps_m":"0.003","rho_m":"2600","pe":"4","pen_dep":"0.3","pen_dep_0":"0.004","n_f":4,"n_m":3,"o_b":1,"n_b":"","grid":"reference",
                "handle_decay":true,"report_cells":true,"unit":"mol/year"}]}""")
    which & 1 != 0 && (m["farfields"][1]["method"] = "semi-analytical")
    which & 2 != 0 && (m["farfields"][2]["method"] = "semi-analytical")
    f(m)
    return m
end
packages(m; fail_at="700") = (m["waste_packages"] = Any[J("""{"name":"Pack","index_lists":["Radionuclides"],"failure":"at","fail_at":"$fail_at","inventory":"0","irf":"0.2",
  "degradation_rate":"2e-3","handle_decay":true,"entries":[{"index":{"Radionuclides":"Aa-1"},"inventory":"1000"}]}""")];
                              push!(m["transfers"], J("""{"name":"Carrier","from":"Pack","to":"Near","rate":"Pack","multiply_by_donor":false,"index_lists":["Radionuclides"]}""")))

# --- the bundled example ---------------------------------------------------------------------------------------
record("semi", semi(); changed=("De_matrix", -1.0))
record("semi, the example's span", semi(m -> (m["simulation"]["end_time"] = 1e6; m["simulation"]["output_points"] = 60;
                                              m["simulation"]["output_times"] = Any[K.JDict("kind" => "log", "points" => 60, "from" => 1, "to" => nothing)])))
record("semi, no decay", semi(handle_decay=false))
record("semi, plug flow", semi(pe="1e400"))
record("semi, infinite depth", semi(pen_dep="1e400"))
record("semi, plug flow, infinite depth", semi(pe="1e400", pen_dep="1e400"))
record("semi, an aperture", semi(surface="aperture", aperture="0.001"))
record("semi, a_w", semi(surface="aw", aw="2"))
record("semi, no matrix", semi(de_m="0"))
record("semi, a first layer on the clock", semi(pen_dep_0="0.002 * (1 + rampUp(time, 2e3, 6e3))"))
# (the well a thousandth as stiff, and a looser tolerance: an explicit solver takes steps the well's flushing allows)
mild(solver) = m -> (m["simulation"]["solver"] = solver; m["simulation"]["rtol"] = 1e-6; m["parameters"][3]["value"] = 1e4)
record("semi, Rosenbrock", semi(mild("ros23")))
record("semi, Dormand-Prince", semi(mild("dp45")))
record("semi, the audit", semi(m -> (m["simulation"]["mass_balance"] = true)))
record("semi, a travel time past the run", semi(tw="1e6"))
# responses that miss their mass balance: the run warns of each
record("semi, plug flow past the run", semi(pe="1e400", tw="1e5"))
record("semi, a travel time far past the run", semi(tw="1e10"))
record("semi, every cell reported", semi(report_cells=true))
record("semi, a parameter on the clock", semi(m -> (m["parameters"][1]["value"] = "1e-3 * (1 + (time > 5000))")))
record("semi, a corner", semi(m -> (m["transfers"][1]["rate"] = "leach_rate * (1 + (time > 5000))")))

# --- the made-up chain ----------------------------------------------------------------------------------------
record("made, both semi", made(); changed=("Pe_rock", 0.0))
record("made, the first semi", made(which=1))
record("made, the second semi", made(which=2))
record("made, stable", made(m -> (m["half_lives"] = J("""{"Aa-1":"stable","Bb-2":"stable","Cc-3":"stable"}"""); m["chains"] = Any[])))
record("made, one without decay", made(m -> (m["farfields"][2]["handle_decay"] = false)))
record("made, the audit", made(m -> (m["simulation"]["mass_balance"] = true)))
record("made, fed by an inflow alone", made(m -> (m["transfers"] = m["transfers"][2:4]; m["inflows"][1]["to"] = "Rock"; m["inflows"][1]["rate"] = "2e-3")))
# rates into a path that follow the state: the release's gradient carries theirs
record("made, a leach rate that reads the state", made(m -> (m["transfers"][1]["rate"] = "k_leach * (1 + 1e-3 * Near)")))
record("made, an inflow that reads the state", made(m -> (m["transfers"] = m["transfers"][2:4]; m["inflows"][1]["to"] = "Rock";
                                                          m["inflows"][1]["rate"] = "2e-3 * (1 + 1e-2 * Down)")))
record("made, a path nothing leaves", made(m -> (m["transfers"] = m["transfers"][1:1]; m["farfields"] = m["farfields"][1:1]; m["inflows"] = Any[]); which=1))
record("made, a path straight into a path", made(m -> (m["transfers"][2]["to"] = "Deep")))
record("made, a release given as a rate by the donor", made(m -> (m["transfers"][2]["multiply_by_donor"] = true)))
record("made, a release read", made(m -> (m["expressions"] = Any[J("""{"name":"Dose","equation":"Deep * 2.5 + Rock[Aa-1]","index_lists":["Radionuclides"]}""")])))
record("made, plug flow", made(m -> (m["farfields"][1]["pe"] = "1e400")))
record("made, packages that fail before a path", made(m -> packages(m)))
record("made, packages straight into a path", made(m -> (packages(m); m["transfers"][end]["to"] = "Rock")))
record("made, packages failing over time", made(m -> (packages(m); p = m["waste_packages"][1]; p["failure"] = "weibull"; p["fail_start"] = "100";
                                                      p["fail_scale"] = "3000"; p["fail_shape"] = "2"; p["packages"] = 20)))
record("made, a corner and an event at a time", made(m -> (m["inflows"][1]["rate"] = "1e-3 * (time > 2000) * (1 + (time > 5000))";
                                                            m["events"] = Any[J("""{"name":"Flood","timing":"at","at":"9000","actions":[{"kind":"move","from":"Near","to":"","fraction":"0.5"}]}""")])))
record("made, events set off by a trigger", made(m -> (m["triggers"] = Any[J("""{"name":"Arrived","first":"Down[Aa-1]","second":"1e-3","index_lists":[]}"""),
                                                                            J("""{"name":"Late","first":"time","second":"12000","index_lists":[]}""")];
                                                       m["events"] = Any[J("""{"name":"Flush","timing":"trigger","trigger":"Arrived","actions":[{"kind":"move","from":"Near","to":"","fraction":"0.5"}]}""")];
                                                       m["snapshots"] = Any[J("""{"name":"Held","target":"Rock","trigger":"Late","initial":"0"}""")];
                                                       m["min_maxes"] = Any[J("""{"name":"Peak","target":"Deep"}""")];
                                                       m["running_means"] = Any[J("""{"name":"Mean","target":"Rock","start_trigger":"Late"}""")])))
record("made, an event moving into a path", made(m -> (m["events"] = Any[J("""{"name":"Spill","timing":"at","at":"3000","actions":[{"kind":"move","from":"Near","to":"Rock","fraction":"0.3"}]}""")])))
record("made, a delay of a release", made(m -> (m["delays"] = Any[J("""{"name":"Later","target":"Deep","delay":"500"}""")])))

# --- other index lists -------------------------------------------------------------------------------------
record("made, two routes", made() do m
    m["index_lists"] = Any[J("""{"name":"Routes","indices":["Fast","Slow"]}""")]
    for c in m["compartments"]
        c["index_lists"] = Any["Radionuclides", "Routes"]
    end
    for t in m["transfers"]
        haskey(t, "index_lists") && (t["index_lists"] = Any["Radionuclides", "Routes"])
    end
    m["inflows"][1]["index_lists"] = Any["Radionuclides", "Routes"]
    for F in m["farfields"]
        F["index_lists"] = Any["Radionuclides", "Routes"]
    end
    push!(m["parameters"], J("""{"name":"TW_route","value":50,"index_lists":["Routes"],"entries":[{"index":{"Routes":"Slow"},"value":120}]}"""))
    m["farfields"][1]["tw"] = "TW_route"
end)
record("made, two routes, the slow one past the run", made() do m
    m["index_lists"] = Any[J("""{"name":"Routes","indices":["Fast","Slow"]}""")]
    for c in m["compartments"]
        c["index_lists"] = Any["Radionuclides", "Routes"]
    end
    for t in m["transfers"]
        haskey(t, "index_lists") && (t["index_lists"] = Any["Radionuclides", "Routes"])
    end
    m["inflows"][1]["index_lists"] = Any["Radionuclides", "Routes"]
    for F in m["farfields"]
        F["index_lists"] = Any["Radionuclides", "Routes"]
    end
    push!(m["parameters"], J("""{"name":"TW_route","value":50,"index_lists":["Routes"],"entries":[{"index":{"Routes":"Slow"},"value":1e5}]}"""))
    m["farfields"][1]["tw"] = "TW_route"
    m["farfields"][1]["pe"] = "1e400"
end)
record("a tracer along three routes", J("""{"name":"tracer",
  "simulation":{"start_time":0,"end_time":5000,"output_points":20,"spacing":"log","solver":"ndf","rtol":1e-8,"abstol":1e-16,"time_unit":"year"},
  "index_lists":[{"name":"Routes","indices":["Fast","Slow","Slower"]}],
  "parameters":[{"name":"T","value":20,"index_lists":["Routes"],"entries":[{"index":{"Routes":"Slow"},"value":60},{"index":{"Routes":"Slower"},"value":200}]}],
  "compartments":[{"name":"Source","initial":"1000","index_lists":["Routes"]},{"name":"Sink","initial":"0","index_lists":["Routes"]}],
  "transfers":[{"name":"Leach","from":"Source","to":"Rock","rate":"1e-3","multiply_by_donor":true},
               {"name":"Out","from":"Rock","to":"Sink","rate":"Rock","multiply_by_donor":false,"index_lists":["Routes"]}],
  "farfields":[{"name":"Rock","method":"semi-analytical","index_lists":["Routes"],"tw":"T","surface":"f","f":"2e4","kd_f":"0","kd_m":"1e-3","de_m":"1e-4",
                "eps_m":"0.005","rho_m":"2700","pe":"10","pen_dep":"0.5","pen_dep_0":"","n_f":4,"n_m":3,"o_b":4,"n_b":"","grid":"matched",
                "handle_decay":true,"report_cells":false,"unit":"g/year"}]}"""))
record("a tracer, no lists at all", J("""{"name":"tracer",
  "simulation":{"start_time":0,"end_time":5000,"output_points":20,"spacing":"log","solver":"ndf","rtol":1e-8,"abstol":1e-16,"time_unit":"year"},
  "compartments":[{"name":"Source","initial":"1000"},{"name":"Sink","initial":"0"}],
  "transfers":[{"name":"Leach","from":"Source","to":"Rock","rate":"1e-3","multiply_by_donor":true},
               {"name":"Out","from":"Rock","to":"Sink","rate":"Rock","multiply_by_donor":false}],
  "farfields":[{"name":"Rock","method":"semi-analytical","index_lists":[],"tw":"20","surface":"f","f":"2e4","kd_f":"0","kd_m":"1e-3","de_m":"1e-4",
                "eps_m":"0.005","rho_m":"2700","pe":"10","pen_dep":"0.5","pen_dep_0":"","n_f":8,"n_m":6,"o_b":4,"n_b":"","grid":"matched",
                "handle_decay":true,"report_cells":true}]}"""))

# --- what a semi-analytical path refuses ------------------------------------------------------------------
record("semi, T_w on the clock", semi(tw="50 * (1 + 0.5 * rampUp(time, 1e3, 1e4))"))
record("semi, Kd following the state", semi(m -> (m["parameters"][4]["value"] = "1e-3 * (1 + Vault[U-238] * 0)")))
record("semi, a Peclet number of zero", semi(pe="0"))
record("semi, a negative depth", semi(pen_dep="-1"))
record("semi, no porosity", semi(eps_m="0", kd_m="0"))
record("semi, a surface there is none of", semi(surface="width"))
record("made, the second refused", made(m -> (m["farfields"][2]["aw"] = "800 - 1000 * (time > 1e4)")))
record("made, its own release flowing in", made(m -> (m["transfers"][1]["rate"] = "k_leach * (1 + Rock[Aa-1])")))
record("made, a matrix only the parent has", made(m -> (m["farfields"][1]["entries"][1]["de_m"] = "0"); which=1))

path = joinpath(@__DIR__, "..", "tests", "fixtures", "farfield_semi.json")
write(path, K.json_text(K.JDict("cases" => cases); indent=0))
println(path, ": ", length(cases), " models, ", count(c -> haskey(c["values"], "refused"), cases), " refused")
