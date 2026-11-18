# Writes tests/fixtures/laplace.json: what the Julia engine's Laplace-domain
# far field (farfield_laplace.jl) makes of paths made up here, for the C++
# engine's tests to compare with (tests/test_laplace.cpp).
#
#     julia --project=../julia tools/laplace_fixtures.jl
#
# Two parts, with parity on.
#
# `helpers` -- the complex arithmetic the path is written in (Smith's division,
# the square root, exp, tanh, sech^2, CPython's products), Python's log and the
# quintic Hermite step, each called on numbers written here.
#
# `paths` -- paths made up to reach every branch: each way of giving the wetted
# surface, every refusal, decay chains with and without branching, clustered
# and near-clustered diagonals, matrix diffusion on and off, finite and
# infinite depth, plug flow, the settings' extremes. For each, in this order:
# the path as prepared; its unit responses as the runtime asks for them, with
# the evaluation counters; T(0); the transfer function at a few points; the
# scalar functions and their Taylor series; each pair's transform of every kind,
# its singularities, its real axis, saddles, support, inversions on a parabola
# of their own and by de Hoog's method, and the shared cells. A short text is
# kept as it is, a long one as a hash; with KOMPARTMENT_FIXTURE_DUMPS set every
# text is written there (`<name>.laplace.julia.txt`).

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
cx(z) = nums([real(z), imag(z)])
cxs(v) = join((cx(z) for z in v), ";")
kept(text::String) = length(text) <= 400 ? "=" * text : "#" * fnv(text)
said(f) =
    try
        f()
    catch e
        e isa K.LaplacePathError ? "refused: $(e.message)" : e isa DomainError ? "throws" : e isa InexactError ? "inexact" : rethrow()
    end

# --- the helpers -------------------------------------------------------------------------------------------

helpers = Any[]
helper(fn, out; x=Float64[]) = push!(helpers, K.JDict("fn" => fn, "x" => Any[bits(Float64(v)) for v in x], "out" => out))

const SPECIAL = [0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 2.0, -3.0, 1e-300, -1e-300, 5e-324, 1e-8, 17.9, 18.0, 18.1, 20.0, -25.0, 300.0,
                 710.0, -745.0, 1e10, -1e10, 1e300, Inf, -Inf, NaN, 3.141592653589793, 1.5707963267948966, 0.1, 7.25]
for a in SPECIAL, b in SPECIAL
    z = ComplexF64(a, b)
    helper("csqrt", cx(K._csqrt(z)); x=[a, b])
    helper("cexp", cx(K._cexp(z)); x=[a, b])
    helper("ctanh", cx(K._ctanh(z)); x=[a, b])
    helper("csech2", cx(K._csech2(z)); x=[a, b])
    helper("rmul", cx(K._rmul(a, ComplexF64(b, a))); x=[a, b])
    helper("radd", cx(K._radd(a, ComplexF64(b, a))); x=[a, b])
end
const SMALL = [0.0, -0.0, 1.0, -2.5, 1e-300, Inf, NaN]
for a in SMALL, b in SMALL, c in SMALL, d in SMALL
    helper("cdiv", cx(K._cdiv(ComplexF64(a, b), ComplexF64(c, d))); x=[a, b, c, d])
    helper("cmul", cx(K._cmul(ComplexF64(a, b), ComplexF64(c, d))); x=[a, b, c, d])
end
for a in SPECIAL
    helper("py_log", said(() -> nums([K._py_log(a)])); x=[a])
    helper("lp_ln", nums([K._lp_ln(a)]); x=[a])
end
# Numbers from a fixed generator, for the steps and the arithmetic away from the special values.
let state = UInt64(88172645463325252)
    global function rnd()
        state ⊻= state << 13
        state ⊻= state >> 7
        state ⊻= state << 17
        return (state >> 11) * 2.0^-53
    end
end
for _ in 1:400
    v = [(rnd() - 0.3) * 10.0^(round(Int, 6 * rnd()) - 3) for _ in 1:9]
    v[5] = v[1] + abs(v[5]) + 1e-3
    helper("hermite5", nums([K._hermite5(v...)]); x=v)
    a, b, c, d = v[1] * 1e3, v[2], v[3] * 1e-2, v[4]
    helper("csqrt", cx(K._csqrt(ComplexF64(a, b))); x=[a, b])
    helper("ctanh", cx(K._ctanh(ComplexF64(c, d * 40))); x=[c, d * 40])
    helper("csech2", cx(K._csech2(ComplexF64(c, d * 40))); x=[c, d * 40])
    helper("cexp", cx(K._cexp(ComplexF64(b, a))); x=[b, a])
    helper("cdiv", cx(K._cdiv(ComplexF64(a, b), ComplexF64(c, d))); x=[a, b, c, d])
end

# --- the paths -----------------------------------------------------------------------------------------------

"""A decay table in the builder's layout from rates and (parent, daughter, coefficient) links."""
function decay_table(lam, pairs)
    n = length(lam)
    par = [Tuple{Int,Float64}[] for _ in 1:n]
    for (p, d, c) in pairs
        push!(par[d+1], (p, Float64(c)))
    end
    ioff = Int[]
    icnt = Int[]
    ipar = Int[]
    icoef = Float64[]
    for i in 1:n
        push!(ioff, length(ipar))
        push!(icnt, length(par[i]))
        for (p, c) in par[i]
            push!(ipar, p)
            push!(icoef, c)
        end
    end
    return K.LPDecay(Float64.(lam), ioff, icnt, ipar, icoef)
end
chain_links(lam) = [(k, k + 1, lam[k+1]) for k in 0:length(lam)-2]
const LN2 = log(2.0)
halves(h) = [isfinite(x) ? LN2 / x : 0.0 for x in h]

cases = Any[]
function case(name; surface="", single=Dict{String,Float64}(), each=Dict{String,Vector{Float64}}(), decay=nothing, n=1, names=nothing,
              tmax=nothing, pairs=nothing, inner=true)
    push!(cases, (name=name, surface=surface, single=Dict{String,Float64}(single), each=Dict{String,Vector{Float64}}(each), decay=decay,
                  n=n, names=names, tmax=tmax, pairs=pairs, inner=inner))
end
rock(; kw...) = merge(Dict{String,Float64}("rho_m" => 2700.0, "kd_f" => 0.0, "eps_m" => 0.005, "kd_m" => 0.0, "de_m" => 1e-5),
                      Dict{String,Float64}(String(k) => Float64(v) for (k, v) in kw))

# The Python package's set (kompartment/julia/tools/farfield_fixtures.py, laplace_cases).
let lam = halves([1.4e7])
    case("sharp_5440"; surface="aw", single=Dict("aw" => 4.9, "tw" => 260.0, "rho_m" => 2700.0, "pe" => 5440.0, "pen_dep" => 0.038,
                                                  "eps_m" => 0.002),
         each=Dict("kd_f" => [6.6e-5], "kd_m" => [0.0], "de_m" => [7.1e-7]), decay=decay_table(lam, []))
end
let lam = halves([2.727e5])
    case("spike"; surface="aw", single=Dict("aw" => 380.5, "tw" => 119.84, "rho_m" => 2700.0, "pe" => Inf, "pen_dep" => 0.0817,
                                             "eps_m" => 1.085e-4),
         each=Dict("kd_f" => [0.0], "kd_m" => [0.0], "de_m" => [3.157e-3]), decay=decay_table(lam, []))
end
let lam = halves([13.05, 8.216e5])
    case("hair"; surface="aw", single=Dict("aw" => 0.3922, "tw" => 50.27, "rho_m" => 2700.0, "pe" => Inf, "pen_dep" => Inf,
                                            "eps_m" => 1.888e-4),
         each=Dict("kd_f" => [0.0, 0.0], "kd_m" => [3.703e-4, 0.0], "de_m" => [1.508e-6, 1.508e-6]), decay=decay_table(lam, [(0, 1, lam[1])]),
         n=2)
end
let lam = halves([4.468e9, 2.455e5, 7.54e4])
    case("like_example"; single=rock(tw=50, f=1e5, pe=10, pen_dep=12.5, eps_m=0.0018, de_m=3.15e-5), each=Dict("kd_m" => [0.0017, 0.0017, 0.05]),
         decay=decay_table(lam, chain_links(lam)), n=3, tmax=1e6)
end
let lam = halves([2.4e5, Inf])
    case("plug_thin"; single=rock(tw=100, f=2e4, pe=Inf, pen_dep=0.05, kd_f=1e-4, eps_m=0.005), each=Dict("kd_m" => [1e-3, 0.01]),
         decay=decay_table(lam, chain_links(lam)), n=2)
end
let lam = halves([1e5, 3e4])
    case("front_3000"; single=rock(tw=20, f=3e3, pe=3000, pen_dep=1, eps_m=0.003, de_m=2e-5), each=Dict("kd_m" => [5e-4, 2e-3]),
         decay=decay_table(lam, chain_links(lam)), n=2)
end
case("tail_300"; single=rock(tw=50, f=1e3, pe=300, pen_dep=Inf, eps_m=0.002), decay=decay_table([0.0], []))
case("tube_1e5"; single=rock(tw=100, f=20, pe=1e5, pen_dep=1, de_m=1e-4), tmax=1e6)
case("tube_1e6"; single=rock(tw=100, f=20, pe=1e6, pen_dep=1, de_m=1e-4), tmax=1e6)
case("no_matrix"; single=rock(tw=30, f=5e4, pe=20, pen_dep=1, kd_f=1e-4, de_m=0), decay=decay_table([1e-5], []))
case("thin_chain_plug"; surface="aw", single=Dict("aw" => 4.401, "tw" => 2741.36, "rho_m" => 2700.0, "pe" => Inf, "pen_dep" => 0.001016,
                                                   "kd_f" => 0.00096121, "eps_m" => 0.0138),
     each=Dict("kd_m" => [0.0, 0.0, 0.0], "de_m" => [1e-5, 1e-5, 1e-5]), decay=decay_table([1e-4, 2e-5, 1e-6], [(0, 1, 1e-4), (1, 2, 2e-5)]), n=3)

# More: the other surfaces, branching, clusters, the extremes.
let lam = halves([3e3, 1e4])
    case("aperture"; surface="aperture", single=rock(tw=40, aperture=1e-4, pe=50, pen_dep=0.5, kd_m=1e-3), decay=decay_table(lam, chain_links(lam)),
         n=2, names=["Ra226", "Pb210"])
end
let lam = [2e-4, 5e-5, 3e-5, 1e-6]
    case("diamond"; single=rock(tw=60, f=4e4, pe=20, pen_dep=2.0), each=Dict("kd_m" => [1e-3, 2e-3, 5e-4, 1e-2]),
         decay=decay_table(lam, [(0, 1, 0.6 * lam[1]), (0, 2, 0.4 * lam[1]), (1, 3, lam[2]), (2, 3, lam[3])]), n=4)
end
let lam = [1e-4, 1e-4, 1e-4]
    case("cluster_equal"; single=rock(tw=80, f=3e4, pe=15, pen_dep=1.0, kd_m=2e-3), decay=decay_table(lam, chain_links(lam)), n=3)
    case("cluster_equal_inf"; single=rock(tw=80, f=3e4, pe=15, pen_dep=Inf, kd_m=2e-3), decay=decay_table(lam, chain_links(lam)), n=3)
    case("cluster_equal_plug"; single=rock(tw=80, f=3e4, pe=Inf, pen_dep=0.3, kd_m=2e-3), decay=decay_table(lam, chain_links(lam)), n=3)
end
let lam = [1e-4, 1e-4 * (1 + 1e-9), 1e-4 * (1 - 2e-9)]
    case("cluster_near"; single=rock(tw=80, f=3e4, pe=15, pen_dep=1.0, kd_m=2e-3), decay=decay_table(lam, chain_links(lam)), n=3)
end
let lam = [3e-5, 3e-5 * (1 + 1e-4), 2e-3, 2e-3]
    case("cluster_partial"; single=rock(tw=25, f=8e3, pe=40, pen_dep=0.8), each=Dict("kd_m" => [1e-3, 1e-3, 4e-3, 4e-3]),
         decay=decay_table(lam, chain_links(lam)), n=4)
end
let lam = [5e-5, 2e-5, 1e-6]
    case("no_matrix_chain"; single=rock(tw=30, f=5e4, pe=20, pen_dep=1, de_m=0), each=Dict("kd_f" => [1e-4, 3e-4, 0.0]),
         decay=decay_table(lam, chain_links(lam)), n=3)
    case("no_matrix_cluster"; single=rock(tw=30, f=5e4, pe=20, pen_dep=1, de_m=0, kd_f=2e-4), decay=decay_table([5e-5, 5e-5, 5e-5],
         chain_links([5e-5, 5e-5, 5e-5])), n=3)
end
case("pe_small"; single=rock(tw=10, f=1e4, pe=0.05, pen_dep=0.4, kd_m=1e-3), decay=decay_table([1e-5], []))
case("x0_tiny"; single=rock(tw=10, f=1e5, pe=25, pen_dep=1e-4, kd_m=1e-3), decay=decay_table([1e-4], []))
case("aw_zero"; surface="aw", single=rock(tw=12, aw=0.0, pe=30, pen_dep=1), decay=decay_table([2e-3], []))
case("f_zero"; single=rock(tw=12, f=0.0, pe=30, pen_dep=1))
case("kd_f_big"; single=rock(tw=5, f=1e3, pe=12, pen_dep=0.2, kd_f=0.5, kd_m=1e-2), decay=decay_table([1e-6], []))
case("lam_big"; single=rock(tw=200, f=1e4, pe=8, pen_dep=0.5, kd_m=1e-3), decay=decay_table([0.5], []))
case("tw_tiny"; single=rock(tw=1e-3, f=50, pe=100, pen_dep=0.01, kd_m=1e-4), decay=decay_table([1e-8], []))
case("tw_huge"; single=rock(tw=1e7, f=1e9, pe=4, pen_dep=3.0, kd_m=1e-4), decay=decay_table([1e-9], []))
let lam = [2e-4, 1e-5, 4e-5]
    # the same link given twice (summed), a link of zero (left out), and per-nuclide settings throughout
    case("merged_links"; single=Dict("tw" => 70.0, "f" => 2e4, "pe" => 12.0, "pen_dep" => 0.6, "rho_m" => 2600.0),
         each=Dict("kd_f" => [0.0, 1e-4, 0.0], "eps_m" => [0.004, 0.006, 0.005], "kd_m" => [1e-3, 2e-3, 3e-3], "de_m" => [1e-5, 2e-5, 3e-5]),
         decay=decay_table(lam, [(0, 1, 0.5 * lam[1]), (0, 1, 0.5 * lam[1]), (1, 2, lam[2]), (0, 2, 0.0)]), n=3, names=["A", "B", "C"])
end
let lam = [1e-3, 1e-3, 5e-4, 1e-5, 1e-5, 2e-6]
    case("branching_six"; single=rock(tw=45, f=2e4, pe=18, pen_dep=1.5, kd_m=1e-3),
         decay=decay_table(lam, [(0, 1, 0.3e-3), (0, 2, 0.7e-3), (1, 3, 1e-3), (2, 3, 2e-4), (2, 4, 3e-4), (3, 5, 1e-5), (4, 5, 1e-5)]), n=6,
         pairs=[(5, 0), (3, 0), (4, 2), (5, 5)])
end
let lam = [1e-4 * 1.6^k for k in 0:15]
    case("sixteen"; single=rock(tw=30, f=1e4, pe=20, pen_dep=1.0, kd_m=1e-3), decay=decay_table(lam, chain_links(lam)), n=16,
         pairs=[(15, 0), (1, 0)], inner=false)
end
let lam = [1e-4 * (1 + k / 20) for k in 0:15]
    # one cluster of sixteen whose series does not converge: every subset's divided difference (T(0) only, and a short pair)
    case("sixteen_clustered"; single=rock(tw=30, f=1e4, pe=20, pen_dep=1.0, kd_m=1e-3), decay=decay_table(lam, chain_links(lam)), n=16,
         pairs=[(1, 0)], inner=false)
end
let lam = [1e-4, 0.0]
    case("stable_daughter"; single=rock(tw=50, f=1e4, pe=10, pen_dep=1.0, kd_m=1e-3), decay=decay_table(lam, chain_links(lam)), n=2)
end
case("plug_short_tmax"; single=rock(tw=100, f=1e4, pe=Inf, pen_dep=0.5, kd_m=1e-3), decay=decay_table([1e-5], []), tmax=50.0)
case("tmax_small"; single=rock(tw=100, f=1e4, pe=20, pen_dep=0.5, kd_m=1e-3), decay=decay_table([1e-5], []), tmax=1e-3)

# Every refusal.
let ok = rock(tw=10, f=1e4, pe=10, pen_dep=1)
    without(k) = (d = copy(ok); delete!(d, k); d)
    with(k, v) = (d = copy(ok); d[k] = v; d)
    case("no_species"; single=ok, n=0)
    case("no_tw"; single=without("tw"))
    case("tw_nan"; single=with("tw", NaN))
    case("tw_zero"; single=with("tw", 0.0))
    case("tw_inf"; single=with("tw", Inf))
    case("no_rho"; single=without("rho_m"))
    case("no_pe"; single=without("pe"))
    case("no_depth"; single=without("pen_dep"))
    case("aw_negative"; surface="aw", single=with("aw", -1.0))
    case("aw_missing"; surface="aw", single=ok)
    case("aperture_zero"; surface="aperture", single=with("aperture", 0.0))
    case("f_negative"; single=with("f", -1.0))
    case("f_inf"; single=with("f", Inf))
    case("no_f"; single=without("f"))
    case("surface_unknown"; surface="width", single=ok)
    case("pe_zero"; single=with("pe", 0.0))
    case("pe_negative"; single=with("pe", -2.0))
    case("depth_zero"; single=with("pen_dep", 0.0))
    case("depth_negative"; single=with("pen_dep", -1.0))
    case("rho_negative"; single=with("rho_m", -1.0))
    case("rho_inf"; single=with("rho_m", Inf))
    case("kd_f_negative"; single=with("kd_f", -1.0))
    case("kd_f_nan"; single=with("kd_f", NaN))
    case("eps_missing"; single=without("eps_m"))
    case("kd_m_inf"; single=ok, each=Dict("kd_m" => [0.0, Inf]), n=2, names=["U238", "U234"])
    case("de_negative"; single=ok, each=Dict("de_m" => [-1e-5]))
    case("no_capacity"; single=with("eps_m", 0.0))
    case("decay_short"; single=ok, decay=decay_table([1e-5], []), n=2)
    case("lam_negative"; single=ok, decay=decay_table([-1e-5], []))
    case("lam_nan"; single=ok, decay=decay_table([NaN], []))
    case("ingrowth_negative"; single=ok, decay=decay_table([1e-5, 0.0], [(0, 1, -1e-5)]), n=2)
    case("ingrowth_inf"; single=ok, decay=decay_table([1e-5, 0.0], [(0, 1, Inf)]), n=2, names=["Pu239", "U235"])
    case("own_parent"; single=ok, decay=decay_table([1e-5, 0.0], [(1, 1, 1e-5)]), n=2)
    case("closed_loop"; single=ok, decay=decay_table([1e-5, 2e-5], [(0, 1, 1e-5), (1, 0, 2e-5)]), n=2)
    case("matrix_from"; single=ok, each=Dict("de_m" => [1e-5, 0.0]), decay=decay_table([1e-5, 0.0], [(0, 1, 1e-5)]), n=2)
    case("matrix_into"; single=ok, each=Dict("de_m" => [0.0, 1e-5]), decay=decay_table([1e-5, 0.0], [(0, 1, 1e-5)]), n=2)
    case("plug_no_matrix"; single=with("pe", Inf), each=Dict("de_m" => [1e-5, 0.0]), n=2)
    let lam = [1e-4 * (1 + k / 20) for k in 0:16]
        case("seventeen"; single=ok, decay=decay_table(lam, chain_links(lam)), n=17)
    end
end

const SVALS = [(0.0, 0.0), (1e-300, 0.0), (1.0, 0.0), (1.0, 3.0), (10.0, -1.0), (1e-6, 1e3), (-1e-3, 0.5), (1e-2, 1e-2)]

function sections(c)
    S = K.JDict()
    st = K.LPSettings(c.surface, c.single, c.each)
    local path
    try
        path = K.prepare_path(st, c.decay, c.n, c.names)
    catch e
        e isa K.LaplacePathError || rethrow()
        S["refused"] = e.message
        return S
    end
    n = path.n
    ws = path.ws
    S["path"] = join([ints(path.order), ints(path.pos), string(path.max_block), nums(path.lam), nums(path.Rf), nums(path.Rm), nums(path.De),
                      ints(path.matrix), join((join(("$p:$(bits(q))" for (p, q) in path.parents[i]), " ") for i in 1:n), "/"),
                      nums([path.tw, path.f, path.Pe, path.aw, path.x0, path.rho]), "$(path.inf_pe) $(path.inf_x0)",
                      ints([path.reach[j, i] for j in 1:n for i in 1:n]), join(path.names, " ")], "|")
    tmax = c.tmax === nothing ? 1e12 : c.tmax
    # The unit responses first, as the runtime asks for them of a path just prepared.
    for j in 0:n-1, i in 0:n-1
        c.pairs !== nothing && !((i, j) in c.pairs) && continue
        S["response $i $j"] = said() do
            r = K.unit_response(path, i, j, tmax)
            join([nums(r.t), nums(r.h), nums(r.dh), nums(r.d2h),
                  nums([r.peak, r.tPeak, r.integral, r.maxCond, r.maxErr, r.m0, r.T0, r.expected, r.rel]),
                  "$(r.balanced) $(r.checked) $(ws.evaluations) $(ws.clustered)"], "\n")
        end
    end
    S["T0"] = nums(K.transfer_at_zero(path)) * " $(ws.evaluations)"
    c.inner || return S
    lines = String[]
    for i in 0:n-1, j in 0:n-1, (sr, si) in SVALS
        push!(lines, cx(K.lp_transfer(path, sr / path.tw, si / path.tw, i, j)))
    end
    push!(lines, "evaluations $(ws.evaluations) clustered $(ws.clustered)")
    S["transfer"] = join(lines, "\n")
    lines = String[]
    zs = [ComplexF64(1e-3 / path.tw, 0.0), ComplexF64(1 / path.tw, 2 / path.tw), ComplexF64(-0.5 / path.tw, 0.1 / path.tw), ComplexF64(5.0, -7.0),
          ComplexF64(-30.0, 0.0), ComplexF64(-30.0, 1e-3), ComplexF64(1e-9, 1e4), ComplexF64(-1e3, -1e2)]
    for z in zs
        push!(lines, said(() -> cx(K._tau_at(path, z)) * " " * nums([K._tau_scale(path, z), K._h_scale(path, z)]) * " " * cx(K._phi_at(path, z))))
        for k in (0, 1, 4, 17)
            push!(lines, said(() -> cxs(K._sqrt_series(z, ComplexF64(0.5, -0.25), k))))
            push!(lines, said(() -> cxs(K._tau_series(path, z, k))))
            push!(lines, said(() -> cxs(K._h_series(path, z, 0.75, k))))
            push!(lines, said(() -> cxs(K._exp_series(2.5, z, k))))
        end
    end
    S["series"] = join(lines, "\n")
    for j in 0:n-1, i in 0:n-1
        c.pairs !== nothing && !((i, j) in c.pairs) && continue
        blk = K._block_of(path, i, j)
        blk === nothing && continue
        lines = String[]
        push!(lines, ints(blk.S) * " " * nums(blk.A) * " " * nums([blk.Rmin]) * " $(blk.matrix)")
        for kind in (K.LP_RELEASE, K.LP_INVENTORY, K.LP_DECAYED), (sr, si) in SVALS[3:end]
            push!(lines, said(() -> cx(K._eval_block(path, ws, blk, ComplexF64(sr / path.tw, si / path.tw), kind)) * " " * nums([ws.E])))
        end
        push!(lines, nums([K._singularity(path, blk), K._singularity(path, blk, K.LP_DECAYED)]) * " $(ws.evaluations) $(ws.clustered)")
        S["block $i $j"] = join(lines, "\n")
        shift = path.inf_pe ? path.tw * blk.Rmin : 0.0
        ax = K._axis_of(path, blk, K.LP_RELEASE, shift)
        lines = String[]
        push!(lines, nums([ax.s0, ax.tLo, ax.shift]))
        push!(lines, nums(ax.s))
        push!(lines, nums(ax.psi))
        push!(lines, nums(ax.sm))
        push!(lines, nums(ax.D))
        sup = K._response_support(ax, ax.tLo, K.LP_T_CAP)
        push!(lines, sup === nothing ? "no support" : nums([sup.tLo, sup.tHi, sup.tPeak, sup.logPeak, sup.tTail]))
        tp = sup === nothing ? shift + path.tw : sup.tPeak
        times = [shift + (tp - shift) * f for f in (1e-3, 0.03, 0.3, 1.0, 3.0, 30.0, 1e3)]
        for t in times
            push!(lines, said() do
                sad = K._saddle_at(ax, t - shift)
                sad === nothing ? "none" : nums([sad.s, sad.psi2, sad.w]) * " $(sad.edge) $(sad.beyond)"
            end)
            push!(lines, said(() -> nums([K._log_estimate(ax, t)]) * " $(K._de_hoog_terms(path, ax, t))"))
        end
        push!(lines, "$(K._de_hoog_terms(path)) $(ws.evaluations)")
        S["axis $i $j"] = join(lines, "\n")
        # The axis's other kinds, laid out as the release's is.
        lines = String[]
        for kind in (K.LP_INVENTORY, K.LP_DECAYED)
            push!(lines, said() do
                a2 = K._axis_of(path, blk, kind, 0.0)
                join([nums([a2.s0, a2.tLo]), nums(a2.s), nums(a2.psi), nums(a2.D)], "\n")
            end)
        end
        S["axes $i $j"] = join(lines, "\n")
        lines = String[]
        M = K._de_hoog_terms(path)
        for t in times[2:6]
            for atol in (0.0, 1e-20)
                push!(lines, said() do
                    r = K._invert_parabola(path, ws, ax, t, atol)
                    nums([r.h, r.dh, r.d2, r.err, r.cond]) * " $(r.regrow) $(r.bad) $(ws.evaluations)"
                end)
            end
            for deriv in (-1, 0, 1, 2)
                push!(lines, said(() -> nums([K._invert_de_hoog(path, ws, blk, K.LP_RELEASE, shift, t, M, deriv)])))
            end
            push!(lines, said(() -> nums([K._invert_de_hoog(path, ws, blk, K.LP_RELEASE, shift, t, K._de_hoog_terms(path, ax, t))]) *
                                    " $(ws.evaluations)"))
        end
        S["invert $i $j"] = join(lines, "\n")
        lines = String[]
        C = K._make_cells(path, ax, 0.0, 0.0)
        push!(lines, nums(C.tb))
        push!(lines, nums(C.U))
        push!(lines, nums(C.sig))
        push!(lines, nums([C.peak]))
        for t in times
            push!(lines, said(() -> nums([K._cell_u(C, t - shift), K._cell_t(C, K._cell_u(C, t - shift))])))
            push!(lines, said() do
                r = K._invert_shared(path, ws, C, t)
                r === nothing ? "nothing" : nums([r.h, r.dh, r.d2, r.err, r.cond])
            end)
        end
        push!(lines, join(("$k=$(C.stats[k])" for k in ("shared", "fallback", "negligible", "cells", "failed", "dehoog")), " ") *
                     " $(ws.evaluations)")
        for k in sort(collect(keys(C.map)))
            cell = C.map[k]
            push!(lines, "$(nums([k])) $(cell.ok) $(cell.why) $(cell.levels) $(cell.n) " *
                         nums([cell.tLo, cell.tA, cell.tHi, cell.v, cell.step, cell.strip, cell.c]) * " " *
                         fnv(join([nums(cell.sr), nums(cell.si), nums(cell.gr), nums(cell.gi), nums(cell.ag), nums(cell.la), nums(cell.mE),
                                   ints(cell.lev)], "|")))
        end
        S["cells $i $j"] = join(lines, "\n")
    end
    return S
end

dumps = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
paths = Any[]
for c in cases
    t0 = time()
    S = sections(c)
    if !isempty(dumps)
        open(joinpath(dumps, "$(c.name).laplace.julia.txt"), "w") do f
            print(f, join(("## $k\n$(replace(v, "," => "\n"))" for (k, v) in S), "\n"))
        end
    end
    D = c.decay === nothing ? nothing :
        K.JDict("lam" => Any[bits(x) for x in c.decay.lam], "ioff" => Any[c.decay.ioff...], "icnt" => Any[c.decay.icnt...],
                "ipar" => Any[c.decay.ipar...], "icoef" => Any[bits(x) for x in c.decay.icoef])
    push!(paths, K.JDict("name" => c.name, "surface" => c.surface,
                         "single" => K.JDict(k => bits(c.single[k]) for k in sort(collect(keys(c.single)))),
                         "each" => K.JDict(k => Any[bits(x) for x in c.each[k]] for k in sort(collect(keys(c.each)))),
                         "decay" => D, "n" => c.n, "names" => c.names === nothing ? nothing : Any[c.names...],
                         "tmax" => bits(c.tmax === nothing ? 1e12 : Float64(c.tmax)),
                         "pairs" => c.pairs === nothing ? nothing : Any[Any[i, j] for (i, j) in c.pairs], "inner" => c.inner,
                         "values" => K.JDict(k => kept(v) for (k, v) in S)))
    println(rpad(c.name, 24), round(time() - t0; digits=2), " s  ", length(S), " sections")
end
out = joinpath(@__DIR__, "..", "tests", "fixtures", "laplace.json")
write(out, K.json_text(K.JDict("helpers" => helpers, "paths" => paths); indent=0))
println(out, ": ", length(helpers), " helper calls, ", length(paths), " paths, ", count(p -> haskey(p["values"], "refused"), paths), " refused")
