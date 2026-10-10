# The far-field path solved in the Laplace domain: the semi-analytical
# alternative to the cells (kompartment/engine/farfield_laplace.py, a port of
# src/domain/farfield-laplace.js), what the semi-analytical runtime
# (farfield_semi.jl) tabulates its unit responses with.
#
# The path is advection and dispersion along a fracture (TW, Pe) with sorption
# on its coating, diffusion into the rock matrix beside it, and decay and
# ingrowth along the model's decay network; its transfer matrix is a function
# of lower-triangular matrices (Parlett's recurrence, or sums over decay paths
# of divided differences from Taylor series where the diagonal clusters), and
# a response is inverted along a parabola through the saddle point on the real
# axis -- shared parabolas for nearby times, de Hoog's method where those
# fail -- and tabulated on an adaptive grid with its first two derivatives.
#
# The complex arithmetic is Python's complex type as the Python engine uses it
# (CPython's product and its mixed float/complex rules), with the application's
# square root, tanh and Smith's division, and the C library's exp, log and
# trigonometric functions: every operation in the Python engine's order, so
# that the responses are its to the last bit. Only what the engine uses is
# here: the release responses (not the inventory's, Talbot's contour or the
# convolution of inflow series, which the engine never calls).

"""A path this method cannot solve, and why."""
struct LaplacePathError <: Exception
    message::String
end
Base.showerror(io::IO, e::LaplacePathError) = print(io, e.message)

const LP_MAX_BLOCK = 16
const LP_RELEASE = 0
const LP_INVENTORY = 1
const LP_DECAYED = 2
const LP_PI = 3.141592653589793
const LP_EPS = 2.220446049250313e-16
const LP_CNAN = ComplexF64(NaN, NaN)

# --- complex arithmetic as the Python engine has it -----------------------------------------------

"""CPython's `float * complex`: the float as complex(x, 0.0), then the full product."""
@inline _rmul(x::Float64, z::ComplexF64) = ComplexF64(x * real(z) - 0.0 * imag(z), x * imag(z) + 0.0 * real(z))
"""CPython's complex product."""
@inline _cmul(a::ComplexF64, b::ComplexF64) =
    ComplexF64(real(a) * real(b) - imag(a) * imag(b), real(a) * imag(b) + imag(a) * real(b))
"""CPython's `x + complex`: the float as complex(x, 0.0)."""
@inline _radd(x::Float64, z::ComplexF64) = ComplexF64(x + real(z), 0.0 + imag(z))
"""Python's `z == 0` of a complex."""
@inline _ciszero(z::ComplexF64) = real(z) == 0 && imag(z) == 0

"""Smith's division, as the application does it; NaN for 0/0."""
@inline function _cdiv(a::ComplexF64, b::ComplexF64)
    ar = real(a)
    ai = imag(a)
    br = real(b)
    bi = imag(b)
    if abs(br) >= abs(bi)
        br == 0.0 && return LP_CNAN
        r = bi / br
        d = br + bi * r
        return ComplexF64((ar + ai * r) / d, (ai - ar * r) / d)
    end
    r = br / bi
    d = bi + br * r
    return ComplexF64((ar * r + ai) / d, (ai * r - ar) / d)
end

"""The principal square root; the cut is the negative real axis."""
@inline function _csqrt(z::ComplexF64)
    ar = real(z)
    ai = imag(z)
    if ai == 0
        ar >= 0 && return ComplexF64(sqrt(ar), 0.0)
        ar != ar && return LP_CNAN
        return ComplexF64(0.0, sqrt(-ar))
    end
    m = py_hypot(ar, ai)
    if ar >= 0
        t = sqrt(0.5 * (m + ar))
        return ComplexF64(t, ai / (2 * t))
    end
    m != m && return LP_CNAN
    t = sqrt(0.5 * (m - ar))
    return ComplexF64(abs(ai) / (2 * t), ai >= 0 ? t : -t)
end

@inline function _cexp(z::ComplexF64)
    e = cexp(real(z))
    y = imag(z)
    y - y != 0 && return LP_CNAN
    return ComplexF64(e * ccos(y), e * csin(y))
end

"""tanh, accurate for small arguments and safe for large ones."""
@inline function _ctanh(z::ComplexF64)
    ar = real(z)
    ai = imag(z)
    sg = 1.0
    if ar < 0
        ar = -ar
        ai = -ai
        sg = -1.0
    end
    if ar > 18
        e = 2 * cexp(-2 * ar)
        return ComplexF64(sg * (1 - e * ccos(2 * ai)), sg * (e * csin(2 * ai)))
    end
    d = ccosh(2 * ar) + ccos(2 * ai)
    return ComplexF64(sg * csinh(2 * ar) / d, sg * csin(2 * ai) / d)
end

"""sech^2 = 1 - tanh^2, without the cancellation near tanh = 1."""
@inline function _csech2(z::ComplexF64)
    ar = real(z)
    ai = imag(z)
    if ar < 0
        ar = -ar
        ai = -ai
    end
    e1 = cexp(-ar)
    e2 = e1 * e1
    w = ComplexF64(e2 * ccos(2 * ai), -e2 * csin(2 * ai))
    num = ComplexF64(2 * e1 * ccos(ai), -2 * e1 * csin(ai))
    s = _cdiv(num, _radd(1.0, w))
    return ComplexF64(real(s) * real(s) - imag(s) * imag(s), 2 * real(s) * imag(s))
end

"""Python's `math.log`: a domain error at zero and below."""
@inline function _py_log(x::Float64)
    x > 0 || isnan(x) || throw(DomainError(x, "math domain error"))
    return clog(x)
end

"""`Math.log`: -Infinity at zero and NaN below it."""
@inline _lp_ln(x::Float64) = x > 0 ? clog(x) : (x == 0 ? -Inf : NaN)

# --- the path ------------------------------------------------------------------------------------

"""Divided differences over subsets of points, and their scratch."""
mutable struct LPDD
    n::Int
    kind::Int
    E::Float64
    t::Float64
    z::Vector{ComplexF64}
    f::Vector{ComplexF64}
    sc::Vector{Float64}
    cl::Vector{Int}
    dist::Vector{Float64}
    memo::Dict{Int,ComplexF64}
    ncl::Int
    cl_mask::Vector{Int}
    cl_c::Vector{ComplexF64}
    cl_ok::Vector{Bool}
    cl_k::Vector{Int}
    cl_coef::Vector{Vector{ComplexF64}}
end
LPDD(nmax::Int) = LPDD(0, 0, 0.0, 0.0, zeros(ComplexF64, nmax), zeros(ComplexF64, nmax), zeros(nmax), zeros(Int, nmax),
                       zeros(nmax * nmax), Dict{Int,ComplexF64}(), 0, zeros(Int, nmax), zeros(ComplexF64, nmax),
                       fill(false, nmax), fill(-1, nmax), [ComplexF64[] for _ in 1:nmax])

mutable struct LPWorkspace
    a::Vector{ComplexF64}
    mz::Vector{ComplexF64}
    tz::Vector{ComplexF64}
    g::Vector{ComplexF64}
    v::Vector{ComplexF64}
    col::Vector{Float64}
    L::Vector{ComplexF64}
    T::Vector{ComplexF64}
    F::Vector{ComplexF64}
    E::Float64
    dd::LPDD
    clustered::Int
    evaluations::Int
end
function LPWorkspace(nmax::Int)
    nn = nmax * nmax
    return LPWorkspace(zeros(ComplexF64, nmax), zeros(ComplexF64, nmax), zeros(ComplexF64, nmax),
                       zeros(ComplexF64, nmax), zeros(ComplexF64, nmax), zeros(nmax), zeros(ComplexF64, nn),
                       zeros(ComplexF64, nn), zeros(ComplexF64, nn), 0.0, LPDD(nmax), 0, 0)
end

"""The block of a pair (i, j): the nuclides on some decay path from j to i, parents first; local
index 0 is j and the last is i."""
mutable struct LPBlock
    i::Int
    j::Int
    S::Vector{Int}
    m::Int
    A::Vector{Float64}
    lam::Vector{Float64}
    Rf::Vector{Float64}
    Rm::Vector{Float64}
    De::Vector{Float64}
    Rmin::Float64
    matrix::Bool
    s0::Float64
end

"""The real axis of one pair: the singularity, the scan's points (s, psi), the midpoints and the
tilted means between them."""
mutable struct LPAxis
    blk::LPBlock
    kind::Int
    shift::Float64
    s0::Float64
    s::Vector{Float64}
    psi::Vector{Float64}
    sm::Vector{Float64}
    D::Vector{Float64}
    tLo::Float64
end

"""A path, ready to be solved (`prepare_path`)."""
mutable struct LaplacePath
    n::Int
    names::Vector{String}
    tw::Float64
    f::Float64
    Pe::Float64
    inf_pe::Bool
    aw::Float64
    x0::Float64
    inf_x0::Bool
    rho::Float64
    lam::Vector{Float64}
    Rf::Vector{Float64}
    Rm::Vector{Float64}
    De::Vector{Float64}
    matrix::Vector{Int}
    parents::Vector{Vector{Tuple{Int,Float64}}}
    order::Vector{Int}
    pos::Vector{Int}
    reach::Matrix{Int}            # reach[j+1, i+1]: j decays (eventually) into i, or is it
    max_block::Int
    blocks::Dict{Int,Union{Nothing,LPBlock}}
    axes::Dict{Tuple{Int,Int,Int},LPAxis}
    ws::LPWorkspace
end

"""A decay table in the builder's layout, as the path reads it."""
struct LPDecay
    lam::Vector{Float64}
    ioff::Vector{Int}
    icnt::Vector{Int}
    ipar::Vector{Int}
    icoef::Vector{Float64}
end

"""The settings of one combination as numbers: `tw`, `rho_m`, `pe`, `pen_dep` and the surface once,
`kd_f`, `eps_m`, `kd_m`, `de_m` one per nuclide."""
struct LPSettings
    surface::String
    single::Dict{String,Float64}
    each::Dict{String,Vector{Float64}}
end

"""A path, ready to be solved (`prepare_path`); `LaplacePathError` with the reason for what the
method cannot solve."""
function prepare_path(settings::LPSettings, decay::Union{Nothing,LPDecay}, n::Int, names)
    n >= 1 || throw(LaplacePathError("A path needs at least one species to carry."))
    nm = names !== nothing ? String[x for x in names] : ["#$(k)" for k in 1:n]
    function one(key)
        haskey(settings.single, key) || throw(LaplacePathError("$key must be a number (got None)"))
        v = settings.single[key]
        v != v && throw(LaplacePathError("$key must be a number (got $(py_repr(v)))"))
        return v
    end
    function each(key)
        v = get(settings.each, key, nothing)
        out = zeros(n)
        for k in 1:n
            x = v === nothing ? get(settings.single, key, NaN) : v[k]
            if !isfinite(x) || x < 0
                throw(LaplacePathError("$key of $(nm[k]) must be zero or a positive number (got $(py_repr(x)))"))
            end
            out[k] = x
        end
        return out
    end
    tw = one("tw")
    rho = one("rho_m")
    Pe = one("pe")
    x0 = one("pen_dep")
    (tw > 0 && isfinite(tw)) || throw(LaplacePathError("The travel time TW must be a positive number (got $(py_repr(tw)))"))
    surface = isempty(settings.surface) ? "f" : settings.surface
    if surface == "aw"
        aw = one("aw")
        (aw >= 0 && isfinite(aw)) ||
            throw(LaplacePathError("The flow-wetted surface a_w must be zero or positive (got $(py_repr(aw)))"))
    elseif surface == "aperture"
        delta = one("aperture")
        delta > 0 || throw(LaplacePathError("The fracture aperture must be a positive length (got $(py_repr(delta)))"))
        aw = 2 / delta
    elseif surface == "f"
        f0 = one("f")
        (f0 >= 0 && isfinite(f0)) ||
            throw(LaplacePathError("The flow-related transport resistance F must be zero or positive (got $(py_repr(f0)))"))
        aw = f0 / tw
    else
        throw(LaplacePathError("Unknown way of giving the wetted surface '$surface'"))
    end
    f = aw * tw
    Pe > 0 || throw(LaplacePathError("The Peclet number must be greater than zero (got $(py_repr(Pe)))"))
    x0 > 0 || throw(LaplacePathError("The depth into the matrix must be a positive length, or Infinity (got $(py_repr(x0)))"))
    (rho >= 0 && isfinite(rho)) || throw(LaplacePathError("The rock density must be zero or positive (got $(py_repr(rho)))"))
    kd_f = each("kd_f")
    eps = each("eps_m")
    kd_m = each("kd_m")
    De = each("de_m")
    Rf = zeros(n)
    Rm = zeros(n)
    matrix = zeros(Int, n)
    for k in 1:n
        Rf[k] = 1 + kd_f[k] * aw
        Rm[k] = eps[k] + rho * kd_m[k]
        if aw > 0 && De[k] > 0 && !(Rm[k] > 0)
            throw(LaplacePathError("The matrix capacity eps + rho*Kd of $(nm[k]) must be greater than zero: a rock with " *
                                   "no porosity and no sorption has nothing for it to diffuse into."))
        end
        matrix[k] = (aw > 0 && De[k] > 0) ? 1 : 0
    end
    lam = zeros(n)
    parents = [Tuple{Int,Float64}[] for _ in 1:n]
    if decay !== nothing
        length(decay.lam) < n && throw(LaplacePathError("The decay table is shorter than the nuclide list."))
        for i in 0:n-1
            lam[i+1] = Float64(decay.lam[i+1])
            if !isfinite(lam[i+1]) || lam[i+1] < 0
                throw(LaplacePathError("The decay constant of $(nm[i+1]) must be zero or positive (got $(py_repr(lam[i+1])))"))
            end
            o = decay.ioff[i+1]
            for q in 0:decay.icnt[i+1]-1
                p = decay.ipar[o+q+1]
                c = Float64(decay.icoef[o+q+1])
                if !isfinite(c) || c < 0
                    throw(LaplacePathError("The ingrowth of $(nm[i+1]) from $(nm[p+1]) must be zero or positive (got $(py_repr(c)))"))
                end
                c == 0 && continue
                p == i && throw(LaplacePathError("$(nm[i+1]) is its own parent."))
                had = findfirst(e -> e[1] == p, parents[i+1])
                if had !== nothing
                    parents[i+1][had] = (p, parents[i+1][had][2] + c)
                else
                    push!(parents[i+1], (p, c))
                end
            end
        end
    end
    indeg = zeros(Int, n)
    children = [Int[] for _ in 1:n]
    for i in 0:n-1
        for (p, _) in parents[i+1]
            push!(children[p+1], i)
            indeg[i+1] += 1
        end
    end
    order = Int[]
    taken = fill(false, n)
    for _ in 1:n
        pick = -1
        for k in 0:n-1
            if !taken[k+1] && indeg[k+1] == 0
                pick = k
                break
            end
        end
        pick < 0 && break
        taken[pick+1] = true
        push!(order, pick)
        for c in children[pick+1]
            indeg[c+1] -= 1
        end
    end
    length(order) < n && throw(LaplacePathError("The decay network closes on itself, so it has no order to solve it in."))
    pos = zeros(Int, n)
    for (p, k) in enumerate(order)
        pos[k+1] = p - 1
    end
    reach = zeros(Int, n, n)
    for p in n-1:-1:0
        k = order[p+1]
        reach[k+1, k+1] = 1
        for c in children[k+1]
            for l in 1:n
                reach[c+1, l] != 0 && (reach[k+1, l] = 1)
            end
        end
    end
    for i in 0:n-1
        for (p, _) in parents[i+1]
            if matrix[p+1] != matrix[i+1]
                inside, outside = matrix[p+1] != 0 ? (nm[p+1], nm[i+1]) : (nm[i+1], nm[p+1])
                throw(LaplacePathError("$outside does not diffuse into the matrix (De = 0) while $inside, which it decays " *
                                       "$(matrix[p+1] != 0 ? "from" : "into"), does: give it a small De, or use the " *
                                       "discretised path."))
            end
        end
    end
    inf_pe = !isfinite(Pe)
    if inf_pe
        for k in 1:n
            if matrix[k] == 0
                throw(LaplacePathError("Plug flow (Pe = Infinity) needs matrix diffusion for every nuclide: without it " *
                                       "$(nm[k]) leaves as a pulse with no width at all."))
            end
        end
    end
    max_block = 1
    for j in 0:n-1, i in 0:n-1
        (i == j || reach[j+1, i+1] == 0) && continue
        m = count(k -> reach[j+1, k+1] != 0 && reach[k+1, i+1] != 0, 0:n-1)
        if m > LP_MAX_BLOCK
            throw(LaplacePathError("$m nuclides lie on the decay paths from $(nm[j+1]) to $(nm[i+1]); at most " *
                                   "$LP_MAX_BLOCK can be solved together."))
        end
        max_block = max(max_block, m)
    end
    return LaplacePath(n, nm, tw, f, Pe, inf_pe, aw, x0, !isfinite(x0), rho, lam, Rf, Rm, De, matrix, parents, order,
                       pos, reach, max_block, Dict{Int,Union{Nothing,LPBlock}}(), Dict{Tuple{Int,Int,Int},LPAxis}(),
                       LPWorkspace(max_block))
end

@inline _reaches(path::LaplacePath, j::Int, i::Int) = path.reach[j+1, i+1] != 0

# --- the two scalar functions, their Taylor series and length scales ---------------------------------

@inline function _tau_at(path::LaplacePath, z::ComplexF64)
    u = _csqrt(z)
    path.inf_x0 && return u
    return _cmul(u, _ctanh(_rmul(path.x0, u)))
end

function _tau_scale(path::LaplacePath, z::ComplexF64)
    zr = real(z)
    zi = imag(z)
    sc = py_hypot(zr, zi)
    if !path.inf_x0
        a = LP_PI / path.x0
        n0 = 0
        if zr < 0
            n0 = max(0, floor(Int, sqrt(-zr) / a - 0.5))
        end
        for n in max(0, n0 - 1):n0+1
            zp = -((n + 0.5) * a) * ((n + 0.5) * a)
            d = py_hypot(zr - zp, zi)
            d < sc && (sc = d)
        end
    end
    return sc
end

"""phi(g); under plug flow -TW g."""
@inline function _phi_at(path::LaplacePath, g::ComplexF64)
    tw = path.tw
    path.inf_pe && return ComplexF64(-tw * real(g), -tw * imag(g))
    B = 4 * tw / path.Pe
    S = _csqrt(ComplexF64(1 + B * real(g), B * imag(g)))
    return _cdiv(ComplexF64(-2 * tw * real(g), -2 * tw * imag(g)), ComplexF64(1 + real(S), imag(S)))
end

"""The fracture's part of member p's g at s, less d s when the pair's transform has its delay taken out."""
@inline function _g_fracture(blk::LPBlock, p::Int, sr::Float64, si::Float64, d::Float64)
    rf = blk.Rf[p+1]
    if d > 0
        e = rf - d
        return ComplexF64(rf * blk.lam[p+1] + e * sr, e * si)
    end
    return ComplexF64((sr + blk.lam[p+1]) * rf, si * rf)
end

function _h_scale(path::LaplacePath, g::ComplexF64)
    tw = path.tw
    path.inf_pe && return 1 / tw
    B = 4 * tw / path.Pe
    S = sqrt(py_hypot(1 + B * real(g), B * imag(g)))
    return _ff_min(S / tw, S * S / B)
end

const LP_BINOM_HALF = let b = zeros(260)
    b[1] = 1.0
    for n in 1:259
        b[n+1] = b[n] * (0.5 - (n - 1)) / n
    end
    b
end

"""Taylor coefficients of sqrt(A + B w) about w = 0."""
function _sqrt_series(A::ComplexF64, B::ComplexF64, K::Int)
    s0 = _csqrt(A)
    q = _cdiv(B, A)
    qr = real(q)
    qi = imag(q)
    pr = real(s0)
    pi_ = imag(s0)
    out = Vector{ComplexF64}(undef, K + 1)
    for n in 0:K
        out[n+1] = ComplexF64(LP_BINOM_HALF[n+1] * pr, LP_BINOM_HALF[n+1] * pi_)
        t = pr * qr - pi_ * qi
        pi_ = pr * qi + pi_ * qr
        pr = t
    end
    return out
end

function _tau_series(path::LaplacePath, c::ComplexF64, K::Int)
    s1 = _sqrt_series(c, ComplexF64(1.0, 0.0), K)
    path.inf_x0 && return s1
    x0 = path.x0
    s2 = zeros(ComplexF64, K + 1)
    s3 = zeros(ComplexF64, K + 1)
    s2[1] = _ctanh(ComplexF64(x0 * real(s1[1]), x0 * imag(s1[1])))
    s3[1] = _csech2(ComplexF64(x0 * real(s1[1]), x0 * imag(s1[1])))
    for n in 1:K
        ar = 0.0
        ai = 0.0
        for k in 1:n
            vr = k * x0 * real(s1[k+1])
            vi = k * x0 * imag(s1[k+1])
            q = s3[n-k+1]
            ar += vr * real(q) - vi * imag(q)
            ai += vr * imag(q) + vi * real(q)
        end
        s2[n+1] = ComplexF64(ar / n, ai / n)
        br = 0.0
        bi = 0.0
        for k in 0:n
            a = s2[k+1]
            b = s2[n-k+1]
            br += real(a) * real(b) - imag(a) * imag(b)
            bi += real(a) * imag(b) + imag(a) * real(b)
        end
        s3[n+1] = ComplexF64(-br, -bi)
    end
    out = Vector{ComplexF64}(undef, K + 1)
    for n in 0:K
        ar = 0.0
        ai = 0.0
        for k in 0:n
            a = s1[k+1]
            b = s2[n-k+1]
            ar += real(a) * real(b) - imag(a) * imag(b)
            ai += real(a) * imag(b) + imag(a) * real(b)
        end
        out[n+1] = ComplexF64(ar, ai)
    end
    return out
end

function _h_series(path::LaplacePath, c::ComplexF64, E::Float64, K::Int)
    tw = path.tw
    if path.inf_pe
        s1 = zeros(ComplexF64, K + 1)
        s1[1] = ComplexF64(-tw * real(c), -tw * imag(c))
        K >= 1 && (s1[2] = ComplexF64(-tw, 0.0))
    else
        B = 4 * tw / path.Pe
        half = path.Pe / 2
        s1 = _sqrt_series(ComplexF64(1 + B * real(c), B * imag(c)), ComplexF64(B, 0.0), K)
        for n in 1:K
            s1[n+1] = ComplexF64(real(s1[n+1]) * -half, imag(s1[n+1]) * -half)
        end
        s1[1] = _phi_at(path, c)
    end
    out = Vector{ComplexF64}(undef, K + 1)
    out[1] = _cexp(ComplexF64(real(s1[1]) + E, imag(s1[1])))
    for n in 1:K
        ar = 0.0
        ai = 0.0
        for k in 1:n
            pr = k * real(s1[k+1])
            pi_ = k * imag(s1[k+1])
            h = out[n-k+1]
            ar += pr * real(h) - pi_ * imag(h)
            ai += pr * imag(h) + pi_ * real(h)
        end
        out[n+1] = ComplexF64(ar / n, ai / n)
    end
    return out
end

"""Taylor coefficients of exp(-t (c + w)): e^(-t c) (-t)^n/n!."""
function _exp_series(t::Float64, c::ComplexF64, K::Int)
    out = Vector{ComplexF64}(undef, K + 1)
    e = _cexp(ComplexF64(-t * real(c), -t * imag(c)))
    r = real(e)
    i = imag(e)
    out[1] = e
    for n in 1:K
        r = r * (-t / n)
        i = i * (-t / n)
        out[n+1] = ComplexF64(r, i)
    end
    return out
end

# --- divided differences over subsets of points, robust for clusters -----------------------------

const LP_LINK_FRAC = 0.3
const LP_TAYLOR_FRAC = 0.5

function _dd_scale(path::LaplacePath, dd::LPDD, z::ComplexF64)
    dd.kind == 0 && return _tau_scale(path, z)
    dd.kind == 1 && return _h_scale(path, z)
    return 1 / dd.t
end

function _dd_series(path::LaplacePath, dd::LPDD, c::ComplexF64, K::Int)
    dd.kind == 0 && return _tau_series(path, c, K)
    dd.kind == 1 && return _h_series(path, c, dd.E, K)
    return _exp_series(dd.t, c, K)
end

function _dd_setup(path::LaplacePath, dd::LPDD, n::Int)
    dd.n = n
    empty!(dd.memo)
    z = dd.z
    for k in 1:n
        dd.sc[k] = _dd_scale(path, dd, z[k])
        dd.cl[k] = k - 1
    end
    anyc = false
    for a in 0:n-1, b in a+1:n-1
        dx = real(z[a+1]) - real(z[b+1])
        dy = imag(z[a+1]) - imag(z[b+1])
        d = sqrt(dx * dx + dy * dy)
        dd.dist[a*n+b+1] = d
        dd.dist[b*n+a+1] = d
        if d <= LP_LINK_FRAC * _ff_min(dd.sc[a+1], dd.sc[b+1])
            anyc = true
            ca = dd.cl[a+1]
            cb = dd.cl[b+1]
            if ca != cb
                for k in 1:n
                    dd.cl[k] == cb && (dd.cl[k] = ca)
                end
            end
        end
    end
    dd.ncl = 0
    anyc || return false
    seen = fill(-1, n)
    for k in 0:n-1
        root = dd.cl[k+1]
        if seen[root+1] < 0
            seen[root+1] = dd.ncl
            dd.cl_mask[dd.ncl+1] = 0
            dd.ncl += 1
        end
        c = seen[root+1]
        dd.cl[k+1] = c
        dd.cl_mask[c+1] |= 1 << k
    end
    for c in 1:dd.ncl
        dd.cl_ok[c] = false
        dd.cl_k[c] = -1
    end
    return true
end

@inline _low(mask::Int) = trailing_zeros(mask)
@inline _high(mask::Int) = 63 - leading_zeros(mask)

function _dd_get(path::LaplacePath, dd::LPDD, mask::Int)
    v = get(dd.memo, mask, nothing)
    v === nothing || return v
    n = dd.n
    lo = _low(mask)
    hi = _high(mask)
    local val::ComplexF64
    if lo == hi
        val = dd.f[lo+1]
    else
        c0 = dd.ncl != 0 ? dd.cl[lo+1] : -1
        cnt = 0
        m = mask
        while m != 0
            cnt += 1
            (c0 >= 0 && dd.cl[_low(m)+1] != c0) && (c0 = -1)
            m &= m - 1
        end
        t = c0 >= 0 ? _dd_taylor(path, dd, mask, cnt, c0) : nothing
        if t !== nothing
            val = t
        else
            a = lo
            b = hi
            if dd.ncl != 0 && dd.cl[a+1] == dd.cl[b+1]
                bd = -1.0
                bb = -1
                m = mask
                while m != 0
                    k = _low(m)
                    if dd.cl[k+1] != dd.cl[a+1] && dd.dist[a*n+k+1] > bd
                        bd = dd.dist[a*n+k+1]
                        bb = k
                    end
                    m &= m - 1
                end
                if bb < 0
                    m = mask
                    while m != 0
                        p = _low(m)
                        m2 = m & (m - 1)
                        while m2 != 0
                            q = _low(m2)
                            if dd.dist[p*n+q+1] > bd
                                bd = dd.dist[p*n+q+1]
                                a = p
                                bb = q
                            end
                            m2 &= m2 - 1
                        end
                        m &= m - 1
                    end
                end
                b = bb
            end
            x = _dd_get(path, dd, mask & ~(1 << a))
            y = _dd_get(path, dd, mask & ~(1 << b))
            val = _cdiv(x - y, dd.z[b+1] - dd.z[a+1])
        end
    end
    dd.memo[mask] = val
    return val
end

function _dd_taylor(path::LaplacePath, dd::LPDD, mask::Int, cnt::Int, c::Int)
    m = cnt - 1
    if dd.cl_k[c+1] < 0
        cm = dd.cl_mask[c+1]
        cr = 0.0
        ci = 0.0
        k0 = 0
        for k in 0:dd.n-1
            if cm & (1 << k) != 0
                cr += real(dd.z[k+1])
                ci += imag(dd.z[k+1])
                k0 += 1
            end
        end
        cr /= k0
        ci /= k0
        rad = 0.0
        for k in 0:dd.n-1
            if cm & (1 << k) != 0
                rad = _ff_max(rad, py_hypot(real(dd.z[k+1]) - cr, imag(dd.z[k+1]) - ci))
            end
        end
        sc = _dd_scale(path, dd, ComplexF64(cr, ci))
        q = rad / sc
        dd.cl_c[c+1] = ComplexF64(cr, ci)
        if !(q <= LP_TAYLOR_FRAC)
            dd.cl_ok[c+1] = false
            dd.cl_k[c+1] = 0
            return nothing
        end
        dd.cl_ok[c+1] = true
        mmax = k0 - 1
        extra = 2
        if q > 0
            term = 1.0
            extra = 1
            while extra < 240
                term *= q * (extra + mmax) / extra
                (term < 1e-17 && extra > 2) && break
                extra += 1
            end
        end
        K = min(255, mmax + extra + 2)
        dd.cl_k[c+1] = K
        dd.cl_coef[c+1] = _dd_series(path, dd, ComplexF64(cr, ci), K)
    end
    dd.cl_ok[c+1] || return nothing
    K = dd.cl_k[c+1]
    cc = dd.cl_c[c+1]
    L = K - m
    h = zeros(ComplexF64, L + 1)
    h[1] = ComplexF64(1.0, 0.0)
    mm = mask
    while mm != 0
        k = _low(mm)
        w = dd.z[k+1] - cc
        wr = real(w)
        wi = imag(w)
        for j in 1:L
            p = h[j]
            h[j+1] = ComplexF64(real(h[j+1]) + (wr * real(p) - wi * imag(p)), imag(h[j+1]) + (wr * imag(p) + wi * real(p)))
        end
        mm &= mm - 1
    end
    f = dd.cl_coef[c+1]
    sr = 0.0
    si = 0.0
    for j in L:-1:0
        a = f[m+j+1]
        b = h[j+1]
        sr += real(a) * real(b) - imag(a) * imag(b)
        si += real(a) * imag(b) + imag(a) * real(b)
    end
    return ComplexF64(sr, si)
end

# --- functions of lower-triangular matrices ------------------------------------------------------

const LP_NEED_ALL = 0
const LP_NEED_COLUMN = 1
const LP_NEED_CORNER = 2

function _tri_fun(path::LaplacePath, ws::LPWorkspace, m::Int, L::Vector{ComplexF64}, F::Vector{ComplexF64}, need::Int)
    dd = ws.dd
    for p in 0:m-1
        F[p*m+p+1] = dd.f[p+1]
    end
    m == 1 && return nothing
    if !_dd_setup(path, dd, m)
        z = dd.z
        for d in 1:m-1, q in 0:m-d-1
            p = q + d
            l = L[p*m+q+1]
            e = F[p*m+p+1] - F[q*m+q+1]
            ar = real(l) * real(e) - imag(l) * imag(e)
            ai = real(l) * imag(e) + imag(l) * real(e)
            for k in q+1:p-1
                g1 = L[p*m+k+1]
                f1 = F[k*m+q+1]
                f2 = F[p*m+k+1]
                g2 = L[k*m+q+1]
                ar += real(f2) * real(g2) - imag(f2) * imag(g2) - (real(g1) * real(f1) - imag(g1) * imag(f1))
                ai += real(f2) * imag(g2) + imag(f2) * real(g2) - (real(g1) * imag(f1) + imag(g1) * real(f1))
            end
            F[p*m+q+1] = _cdiv(ComplexF64(ar, ai), z[p+1] - z[q+1])
        end
        return nothing
    end
    ws.clustered += 1
    if need == LP_NEED_ALL
        for p in 1:m-1, q in 0:p-1
            F[p*m+q+1] = ComplexF64(0.0, 0.0)
        end
        for q in 0:m-2
            _path_visit(path, ws, m, L, F, q, q, 1 << q, ComplexF64(1.0, 0.0), false)
        end
    else
        for p in 1:m-1
            F[p*m+1] = ComplexF64(0.0, 0.0)
        end
        _path_visit(path, ws, m, L, F, 0, 0, 1, ComplexF64(1.0, 0.0), need == LP_NEED_CORNER)
    end
    return nothing
end

function _path_visit(path::LaplacePath, ws::LPWorkspace, m::Int, L::Vector{ComplexF64}, F::Vector{ComplexF64}, q::Int,
                     k::Int, mask::Int, prod::ComplexF64, corner_only::Bool)
    if k != q && (!corner_only || k == m - 1)
        v = _dd_get(path, ws.dd, mask)
        F[k*m+q+1] += ComplexF64(real(prod) * real(v) - imag(prod) * imag(v), real(prod) * imag(v) + imag(prod) * real(v))
    end
    for l in k+1:m-1
        e = L[l*m+k+1]
        _ciszero(e) && continue
        _path_visit(path, ws, m, L, F, q, l, mask | (1 << l),
                    ComplexF64(real(prod) * real(e) - imag(prod) * imag(e), real(prod) * imag(e) + imag(prod) * real(e)),
                    corner_only)
    end
    return nothing
end

# --- one pair's transform ----------------------------------------------------------------------

function _block_of(path::LaplacePath, i::Int, j::Int)
    key = i * path.n + j
    haskey(path.blocks, key) && return path.blocks[key]
    blk = nothing
    if _reaches(path, j, i)
        S = Int[k for k in path.order if _reaches(path, j, k) && _reaches(path, k, i)]
        m = length(S)
        loc = Dict(k => p for (p, k) in enumerate(S))
        A = zeros(m * m)
        for p in 0:m-1
            for (par, c) in path.parents[S[p+1]+1]
                q = get(loc, par, nothing)
                q === nothing && continue
                A[p*m+q] -= c
            end
        end
        Rf = Float64[path.Rf[k+1] for k in S]
        rmin = Rf[1]
        for x in @view Rf[2:end]
            x < rmin && (rmin = x)
        end
        blk = LPBlock(i, j, S, m, A, Float64[path.lam[k+1] for k in S], Rf, Float64[path.Rm[k+1] for k in S],
                      Float64[path.De[k+1] for k in S], rmin, path.matrix[S[1]+1] == 1, NaN)
    end
    path.blocks[key] = blk
    return blk
end

"""The pair's transform at s, scaled: the value is the result times e^(-ws.E)."""
function _eval_block(path::LaplacePath, ws::LPWorkspace, blk::LPBlock, s::ComplexF64, kind::Int)
    m = blk.m
    aw = path.aw
    ws.evaluations += 1
    delay = (kind != LP_INVENTORY && path.inf_pe) ? blk.Rmin : 0.0
    phi_max = -Inf
    lam = blk.lam
    Rf = blk.Rf
    De = blk.De
    for p in 0:m-1
        a = ComplexF64(real(s) + lam[p+1], imag(s))
        ws.a[p+1] = a
        g0 = _g_fracture(blk, p, real(s), imag(s), delay)
        gr = real(g0)
        gi = imag(g0)
        if blk.matrix
            fm = blk.Rm[p+1] / De[p+1]
            mz = ComplexF64(fm * real(a), fm * imag(a))
            ws.mz[p+1] = mz
            tz = _tau_at(path, mz)
            ws.tz[p+1] = tz
            gr += aw * De[p+1] * real(tz)
            gi += aw * De[p+1] * imag(tz)
        end
        g = ComplexF64(gr, gi)
        ws.g[p+1] = g
        ph = _phi_at(path, g)
        real(ph) > phi_max && (phi_max = real(ph))
    end
    E = isfinite(phi_max) ? -phi_max : 0.0
    L = ws.L
    dd = ws.dd
    A = blk.A
    if m > 1
        if blk.matrix
            dd.kind = 0
            for p in 0:m-1
                dd.z[p+1] = ws.mz[p+1]
                dd.f[p+1] = ws.tz[p+1]
                for q in 0:p-1
                    L[p*m+q+1] = ComplexF64(A[p*m+q+1] * blk.Rm[q+1] / De[p+1], 0.0)
                end
            end
            _tri_fun(path, ws, m, L, ws.T, LP_NEED_ALL)
            T = ws.T
            for p in 1:m-1
                c = aw * De[p+1]
                for q in 0:p-1
                    t = T[p*m+q+1]
                    L[p*m+q+1] = ComplexF64(A[p*m+q+1] * Rf[q+1] + c * real(t), c * imag(t))
                end
            end
        else
            for p in 1:m-1, q in 0:p-1
                L[p*m+q+1] = ComplexF64(A[p*m+q+1] * Rf[q+1], 0.0)
            end
        end
    end
    dd.kind = 1
    dd.E = E
    for p in 0:m-1
        dd.z[p+1] = ws.g[p+1]
        ph = _phi_at(path, ws.g[p+1])
        dd.f[p+1] = _cexp(ComplexF64(real(ph) + E, imag(ph)))
    end
    F = ws.F
    _tri_fun(path, ws, m, L, F, kind == LP_RELEASE ? LP_NEED_CORNER : LP_NEED_COLUMN)
    if kind == LP_RELEASE
        ws.E = E
        return F[(m-1)*m+1]
    end
    if kind == LP_DECAYED
        EK = E
        c0 = 0.0
        c1 = -1.0
    else
        EK = E < 0 ? E : 0.0
        c0 = cexp(EK)
        c1 = cexp(EK - E)
    end
    v = ws.v
    for p in 0:m-1
        fp = F[p*m+1]
        wr = (p == 0 ? c0 : 0.0) - c1 * real(fp)
        wi = -c1 * imag(fp)
        for q in 0:p-1
            a = A[p*m+q+1]
            if a != 0
                wr -= a * real(v[q+1])
                wi -= a * imag(v[q+1])
            end
        end
        v[p+1] = _cdiv(ComplexF64(wr, wi), ws.a[p+1])
    end
    ws.E = EK
    return v[m]
end

"""T_ij(s); 0 when j never becomes i."""
function lp_transfer(path::LaplacePath, sr::Float64, si::Float64, i::Int, j::Int)
    blk = _block_of(path, i, j)
    blk === nothing && return ComplexF64(0.0, 0.0)
    v = _eval_block(path, path.ws, blk, ComplexF64(sr, si), LP_RELEASE)
    lr = -path.ws.E - (path.inf_pe ? path.tw * blk.Rmin * sr : 0.0)
    li = path.inf_pe ? -path.tw * blk.Rmin * si : 0.0
    e = _cexp(ComplexF64(lr, li))
    return ComplexF64(real(v) * real(e) - imag(v) * imag(e), real(v) * imag(e) + imag(v) * real(e))
end

"""T(0) for every pair, row-major n x n."""
function transfer_at_zero(path::LaplacePath)
    n = path.n
    out = zeros(n * n)
    for i in 0:n-1, j in 0:n-1
        _block_of(path, i, j) === nothing && continue
        v = real(lp_transfer(path, 0.0, 0.0, i, j))
        isfinite(v) || (v = real(lp_transfer(path, 1e-300, 0.0, i, j)))
        out[i*n+j+1] = v
    end
    return out
end

# --- numerical inversion -------------------------------------------------------------------------

function _tau_real(path::LaplacePath, z::Float64)
    if z >= 0
        u = sqrt(z)
        return path.inf_x0 ? u : u * ctanh(path.x0 * u)
    end
    u = sqrt(-z)
    return path.inf_x0 ? NaN : -u * ctan(path.x0 * u)
end

function _singularity(path::LaplacePath, blk::LPBlock, kind::Int=LP_RELEASE)
    if kind == LP_DECAYED
        s0 = _singularity(path, blk)
        for p in 1:blk.m
            -blk.lam[p] > s0 && (s0 = -blk.lam[p])
        end
        return s0
    end
    blk.s0 == blk.s0 && return blk.s0
    s0 = -Inf
    for p in 1:blk.m
        lam = blk.lam[p]
        Rf = blk.Rf[p]
        if !blk.matrix
            sk = path.inf_pe ? -Inf : -lam - path.Pe / (4 * path.tw * Rf)
        elseif path.inf_x0
            sk = -lam
        else
            f = blk.Rm[p] / blk.De[p]
            pole = -lam - (LP_PI / (2 * path.x0)) * (LP_PI / (2 * path.x0)) / f
            if path.inf_pe
                sk = pole
            else
                gs = -path.Pe / (4 * path.tw)
                a = pole
                b = -lam
                it = 0
                while it < 200 && b - a > 1e-15 * _ff_max(abs(a), abs(b))
                    c = 0.5 * (a + b)
                    g = (c + lam) * Rf + path.aw * blk.De[p] * _tau_real(path, f * (c + lam))
                    if g > gs
                        b = c
                    else
                        a = c
                    end
                    it += 1
                end
                sk = b
            end
        end
        sk > s0 && (s0 = sk)
    end
    blk.s0 = s0
    return s0
end

function _off_lambda(blk::LPBlock, s::Float64, gap::Float64)
    for _ in 0:blk.m
        moved = false
        for p in 1:blk.m
            if abs(s + blk.lam[p]) < gap
                s = -blk.lam[p] + gap
                moved = true
            end
        end
        moved || break
    end
    return s
end

@inline _d_of(a::Tuple{Float64,Float64}, b::Tuple{Float64,Float64}) = -(b[2] - a[2]) / (b[1] - a[1])

function _real_axis(path::LaplacePath, ws::LPWorkspace, blk::LPBlock, kind::Int, shift::Float64, t_lo::Float64,
                    t_hi::Float64)
    s0 = _singularity(path, blk, kind)
    fac = py_pow(10.0, 1 / 8)
    function psi_at(s::Float64)
        at = kind == LP_INVENTORY ? _off_lambda(blk, s, 1e-7 * (s - s0)) : s
        v = _eval_block(path, ws, blk, ComplexF64(at, 0.0), kind)
        F = real(v)
        return (F > 0 && isfinite(F)) ? _py_log(F) - ws.E : -Inf
    end
    x0 = _ff_max(abs(s0), 0.0) + 1 / t_hi
    up = Tuple{Float64,Float64}[]
    dn = Tuple{Float64,Float64}[]
    wmax = -Inf
    x = x0
    for _ in 1:800
        p = psi_at(s0 + x)
        push!(up, (s0 + x, p))
        (!isfinite(p) || x > 1e12 / t_lo) && break
        m = length(up)
        if m >= 2
            a = up[m-1]
            b = up[m]
            w = 0.5 * (a[1] + b[1]) * _d_of(a, b) + 0.5 * (a[2] + b[2])
            w > wmax && (wmax = w)
            w < wmax - 120 && break
        end
        x *= fac
    end
    prev = up[1]
    d_prev = length(up) > 1 ? _d_of(up[1], up[2]) : 0.0
    x = x0 / fac
    for _ in 1:800
        s = s0 + x
        s > s0 || break
        p = psi_at(s)
        isfinite(p) || break
        D = _d_of((s, p), prev)
        D > d_prev || break
        push!(dn, (s, p))
        w = 0.5 * (s + prev[1]) * D + 0.5 * (p + prev[2])
        w > wmax && (wmax = w)
        prev = (s, p)
        d_prev = D
        (D > 10 * t_hi || x < 1e-13 * _ff_max(abs(s0), 1 / t_hi) || w < wmax - 120) && break
        x /= fac
    end
    pts = vcat(reverse(dn), up)
    extra = Float64[]
    e_hi = _ff_max(pts[end][1], 0.0)
    e_left = 0.5 * abs(s0)
    e = 1 / t_hi
    while e < _ff_max(e_hi, e_left)
        e < e_hi && push!(extra, e)
        e < e_left && push!(extra, -e)
        e *= fac
    end
    if !isempty(extra)
        have = Float64[q[1] for q in pts]
        lo0 = have[1]
        near(a, b) = abs(a - b) < 1e-6 * _ff_max(_ff_max(abs(a), abs(b)), 1 / t_hi)
        for e in extra
            (!(e > lo0) || any(h -> near(h, e), have)) && continue
            pv = psi_at(e)
            isfinite(pv) && push!(pts, (e, pv))
        end
        sort!(pts; lt=(a, b) -> a[1] < b[1], alg=Base.Sort.DEFAULT_STABLE)
        kept = [pts[1]]
        for k in 2:length(pts)
            Dn = _d_of(kept[end], pts[k])
            (!(Dn > 0) || (length(kept) >= 2 && !(Dn < _d_of(kept[end-1], kept[end])))) && continue
            push!(kept, pts[k])
        end
        pts = kept
    end
    for _ in 1:14
        length(pts) >= 4000 && break
        out = [pts[1]]
        added = false
        np_ = length(pts)
        for k in 1:np_-1
            a = pts[k]
            b = pts[k+1]
            Dk = _d_of(a, b)
            Dl = k > 1 ? _d_of(pts[k-1], a) : NaN
            Dr = k + 2 <= np_ ? _d_of(b, pts[k+2]) : NaN
            drop = _ff_max(isfinite(Dl) ? Dl - Dk : 0.0, isfinite(Dr) ? Dk - Dr : 0.0)
            w = 0.5 * (a[1] + b[1]) * Dk + 0.5 * (a[2] + b[2])
            if drop * (b[1] - a[1]) > 1 && w > wmax - 80
                s_mid = s0 + sqrt((a[1] - s0) * (b[1] - s0))
                if a[1] < s_mid < b[1]
                    p = psi_at(s_mid)
                    if isfinite(p)
                        push!(out, (s_mid, p))
                        added = true
                    end
                end
            end
            push!(out, b)
        end
        pts = out
        added || break
    end
    K = length(pts)
    sv = Float64[q[1] for q in pts]
    psi = Float64[q[2] for q in pts]
    sm = zeros(max(0, K - 1))
    D = zeros(max(0, K - 1))
    for k in 1:K-1
        sm[k] = s0 + sqrt((sv[k] - s0) * (sv[k+1] - s0))
        D[k] = (isfinite(psi[k+1]) && isfinite(psi[k])) ? -(psi[k+1] - psi[k]) / (sv[k+1] - sv[k]) : NaN
    end
    return LPAxis(blk, kind, shift, s0, sv, psi, sm, D, NaN)
end

"""The saddle for time t from the axis's table."""
struct LPSaddle
    s::Float64
    psi2::Float64
    w::Float64
    edge::Bool
    beyond::Bool
end

function _saddle_at(ax::LPAxis, t::Float64)
    D = ax.D
    sm = ax.sm
    K = length(D)
    s0 = ax.s0
    K < 2 && return nothing
    k = 0
    while k < K && !(D[k+1] <= t)
        (!isfinite(D[k+1]) && k > 0) && break
        k += 1
    end
    if k == 0
        psi2 = (D[1] - D[2]) / (sm[2] - sm[1])
        return LPSaddle(sm[1], psi2, sm[1] * t + ax.psi[1], true, false)
    end
    (k >= K || !isfinite(D[k+1])) && return LPSaddle(sm[min(k, K)], NaN, -Inf, false, true)
    a = k - 1
    b = k
    la = _py_log(D[a+1])
    lb = _py_log(D[b+1])
    f = (la - _py_log(t)) / (la - lb)
    xa = sm[a+1] - s0
    xb = sm[b+1] - s0
    ss = s0 + xa * py_pow(xb / xa, f)
    psi2 = (D[a+1] - D[b+1]) / (sm[b+1] - sm[a+1])
    psi = ax.psi[b+1] + (ax.s[b+1] - ss) * 0.5 * (t + D[b+1])
    return LPSaddle(ss, psi2, ss * t + psi, false, false)
end

"""An inversion's sums: the response and its first two derivatives, with what they say of themselves."""
mutable struct LPAcc
    h::Float64
    dh::Float64
    d2::Float64
    abs::Float64
    bad::Bool
    regrow::Bool
    cut::Bool
    stop::Float64
end
LPAcc(stop::Float64=Inf) = LPAcc(0.0, 0.0, 0.0, 0.0, false, false, false, stop)

"""What an inversion at one time gives: h, h', h'', the error estimate and the condition."""
struct LPInv
    h::Float64
    dh::Float64
    d2::Float64
    err::Float64
    cond::Float64
    regrow::Bool
    bad::Bool
end
_lp_zero() = LPInv(0.0, 0.0, 0.0, 0.0, 1.0, false, false)

function _parabola_term(path::LaplacePath, ws::LPWorkspace, ax::LPAxis, t::Float64, ss::Float64, kappa::Float64,
                        Y::Float64, jac::Float64, wgt::Float64, acc::LPAcc)
    sr = ss - kappa * Y * Y
    si = Y
    F = _eval_block(path, ws, ax.blk, ComplexF64(sr, si), ax.kind)
    ex = t * sr - ws.E
    if ex > 700
        acc.bad = true
        return Inf
    end
    (ex < -740 || _ciszero(F)) && return 0.0
    e = _cexp(ComplexF64(ex, t * si))
    ar = real(e) * real(F) - imag(e) * imag(F)
    ai = real(e) * imag(F) + imag(e) * real(F)
    q = 2 * kappa * Y
    zr = ar - ai * q
    zi = ai + ar * q
    w = wgt * jac
    acc.h += w * zr
    yr = sr * zr - si * zi
    yi = sr * zi + si * zr
    acc.dh += w * yr
    acc.d2 += w * (sr * yr - si * yi)
    mod = py_hypot(zr, zi)
    acc.abs += w * mod
    return jac * mod
end

function _parabola_sweep(path::LaplacePath, ws::LPWorkspace, ax::LPAxis, t::Float64, ss::Float64, kappa::Float64,
                         step::Float64, off::Float64, acc::LPAcc, c::Float64=0.0)
    max_mod = 0.0
    min_env = Inf
    small = 0
    last = zeros(7)
    for k in 0:19999
        u = off + k * (off != 0 ? 2 * step : step)
        Y = c > 0 ? c * csinh(u) : u
        jac = c > 0 ? c * ccosh(u) : 1.0
        if u == 0
            m0 = _parabola_term(path, ws, ax, t, ss, kappa, 0.0, jac, 0.5, acc)
            max_mod = _ff_max(max_mod, m0)
            continue
        end
        m = _parabola_term(path, ws, ax, t, ss, kappa, Y, jac, 1.0, acc)
        if k > 3 && (m > 100 * max_mod || (min_env < 1e-6 * max_mod && m > 1e-3 * max_mod))
            acc.regrow = true
            break
        end
        m > max_mod && (max_mod = m)
        last[k%7+1] = m
        if k >= 7
            mx = last[1]
            for r in 2:7
                last[r] > mx && (mx = last[r])
            end
            min_env = _ff_min(min_env, mx)
        end
        if m <= 1e-18 * max_mod
            small += 1
            (small >= 3 && k > 3) && return nothing
        else
            small = 0
        end
        acc.bad && return nothing
        ws.evaluations > acc.stop && break
    end
    acc.cut = true
    return nothing
end

function _psi_real(path::LaplacePath, ws::LPWorkspace, ax::LPAxis, s::Float64)
    v = _eval_block(path, ws, ax.blk, ComplexF64(s, 0.0), ax.kind)
    F = real(v)
    return (F > 0 && isfinite(F)) ? _py_log(F) - ws.E : NaN
end

"""psi, the tilted mean D = -psi' and psi'' at s, by central differences."""
function _local_axis(path::LaplacePath, ws::LPWorkspace, ax::LPAxis, s::Float64, scale::Float64)
    dl = _ff_min(1e-3 * (s - ax.s0), scale > 0 ? 0.1 * scale : Inf)
    pm = _psi_real(path, ws, ax, s - dl)
    p0 = _psi_real(path, ws, ax, s)
    pp = _psi_real(path, ws, ax, s + dl)
    return (psi=p0, D=(pm - pp) / (2 * dl), psi2=(pp - 2 * p0 + pm) / (dl * dl))
end

"""ln |H(g_p(s))|, the size of member p's own transform at s."""
function _ln_hk(path::LaplacePath, blk::LPBlock, p::Int, sr::Float64, si::Float64, rfc::Float64)
    lam = blk.lam[p+1]
    g0 = _g_fracture(blk, p, sr, si, rfc)
    gr = real(g0)
    gi = imag(g0)
    if blk.matrix
        fm = blk.Rm[p+1] / blk.De[p+1]
        tz = _tau_at(path, ComplexF64(fm * (sr + lam), fm * si))
        gr += path.aw * blk.De[p+1] * real(tz)
        gi += path.aw * blk.De[p+1] * imag(tz)
    end
    return real(_phi_at(path, ComplexF64(gr, gi)))
end

function _clears_ridge(path::LaplacePath, blk::LPBlock, v::Float64, t::Float64, kappa::Float64, lev::Vector{Float64},
                       lev_min::Float64, rfc::Float64)
    if path.inf_pe
        ymax = sqrt(80 / (t * kappa))
    else
        t * v + path.Pe / 2 <= lev_min && return true
        ymax = sqrt((t * v + path.Pe / 2 - lev_min + 40) / (t * kappa))
    end
    for q in 1:96
        Y = ymax * q / 96
        sr = v - kappa * Y * Y
        for p in 0:blk.m-1
            t * sr + _ln_hk(path, blk, p, sr, Y, rfc) > lev[p+1] && return false
        end
    end
    return true
end

"""How fast, at most, the phase of any member's own transform times e^(st) turns along the parabola."""
function _path_frequency(path::LaplacePath, blk::LPBlock, v::Float64, t::Float64, kappa::Float64, floor_::Float64,
                         rfc::Float64, t2::Union{Nothing,Float64}=nothing, c::Float64=0.0)
    ymax = sqrt(_ff_max(0.0, (t * v - floor_ + (path.inf_pe ? 40 : path.Pe / 2 + 40)) / (t * kappa)))
    wmax = 0.0
    wmax_u = 0.0
    for q in 0:96
        Y = ymax * q / 96
        sr = v - kappa * Y * Y
        si = Y
        for p in 0:blk.m-1
            zr0 = sr + blk.lam[p+1]
            g0 = _g_fracture(blk, p, sr, si, rfc)
            gr = real(g0)
            gi = imag(g0)
            dgr = path.inf_pe ? blk.Rf[p+1] - rfc : blk.Rf[p+1]
            dgi = 0.0
            if blk.matrix
                f = blk.Rm[p+1] / blk.De[p+1]
                aw_de = path.aw * blk.De[p+1]
                u = _csqrt(ComplexF64(f * zr0, f * si))
                tr = real(u)
                ti = imag(u)
                hh = _cdiv(ComplexF64(0.5, 0.0), u)
                if path.inf_x0
                    dr = real(hh)
                    di = imag(hh)
                else
                    th = _ctanh(ComplexF64(path.x0 * real(u), path.x0 * imag(u)))
                    tr = real(u) * real(th) - imag(u) * imag(th)
                    ti = real(u) * imag(th) + imag(u) * real(th)
                    se = _csech2(ComplexF64(path.x0 * real(u), path.x0 * imag(u)))
                    dr = real(th) * real(hh) - imag(th) * imag(hh) + 0.5 * path.x0 * real(se)
                    di = real(th) * imag(hh) + imag(th) * real(hh) + 0.5 * path.x0 * imag(se)
                end
                gr += aw_de * tr
                gi += aw_de * ti
                dgr += aw_de * f * dr
                dgi += aw_de * f * di
            end
            ph = _phi_at(path, ComplexF64(gr, gi))
            t * sr + real(ph) < floor_ && continue
            if path.inf_pe
                pr_ = -path.tw * dgr
                pi_ = -path.tw * dgi
            else
                B = 4 * path.tw / path.Pe
                sq = _csqrt(ComplexF64(1 + B * gr, B * gi))
                q_ = _cdiv(ComplexF64(-path.tw, 0.0), sq)
                pr_ = real(q_) * dgr - imag(q_) * dgi
                pi_ = real(q_) * dgi + imag(q_) * dgr
            end
            w = abs((t + pr_) - 2 * kappa * Y * pi_)
            t2 === nothing || (w = _ff_max(w, abs((t2 + pr_) - 2 * kappa * Y * pi_)))
            w > wmax && (wmax = w)
            if c > 0
                wu = w * sqrt(c * c + Y * Y)
                wu > wmax_u && (wmax_u = wu)
            end
        end
    end
    return wmax, wmax_u
end

const LP_VERTEX_BETA = 1.5

"""The vertex of the parabola for time tt: (v, the local axis at v or nothing for K, psi'')."""
function _parabola_vertex(path::LaplacePath, ws::LPWorkspace, ax::LPAxis, tt::Float64, sad::LPSaddle)
    v_min = ax.s0 + LP_VERTEX_BETA / tt
    v = _ff_max(sad.s, v_min)
    loc = nothing
    psi2 = NaN
    if ax.kind != LP_INVENTORY
        scale = _ff_min(1 / tt, (isfinite(sad.psi2) && sad.psi2 > 0) ? 1 / sqrt(sad.psi2) : Inf)
        loc = _local_axis(path, ws, ax, v, scale)
        for _ in 1:3
            (v > v_min && loc.psi2 > 0 && abs(loc.D - tt) > 0.5 * sqrt(loc.psi2)) || break
            vn = _ff_max(v + (loc.D - tt) / loc.psi2, v_min)
            ln = _local_axis(path, ws, ax, vn, scale)
            (!(abs(ln.D - tt) < abs(loc.D - tt)) || !(ln.psi2 > 0)) && break
            v = vn
            loc = ln
        end
        psi2 = loc.psi2
    end
    if !(psi2 > 0) || !isfinite(psi2)
        psi2 = (isfinite(sad.psi2) && sad.psi2 > 0) ? sad.psi2 : tt * tt
    end
    return v, loc, psi2
end

function _flatten_for_ridge(path::LaplacePath, blk::LPBlock, v::Float64, t::Float64, wv::Float64, kappa::Float64,
                            rfc::Float64)
    m = blk.m
    lev = zeros(m)
    lev_min = Inf
    for p in 0:m-1
        lev[p+1] = _ff_max(t * v + _ln_hk(path, blk, p, v, 0.0, rfc), wv) + 2
        lev_min = _ff_min(lev_min, lev[p+1])
    end
    for _ in 1:16
        _clears_ridge(path, blk, v, t, kappa, lev, lev_min, rfc) && break
        kappa /= 4
    end
    return kappa
end

"""The response and its first two derivatives at t on a parabola of its own."""
function _invert_parabola(path::LaplacePath, ws::LPWorkspace, ax::LPAxis, t::Float64, atol::Float64)
    tt = t - ax.shift
    tt > 0 || return _lp_zero()
    rtol = 1e-11
    max_eval = 6000
    sad = _saddle_at(ax, tt)
    (sad === nothing || sad.beyond || sad.w < -720) && return _lp_zero()
    n0 = ws.evaluations
    v, loc, psi2 = _parabola_vertex(path, ws, ax, tt, sad)
    wv = (loc !== nothing && isfinite(loc.psi)) ? tt * v + loc.psi : sad.w
    omega = (loc !== nothing && isfinite(loc.D)) ? abs(tt - loc.D) : 0.0
    kappa = _ff_max(psi2 / (2 * tt), 0.25 / (v - ax.s0))
    rfc = ax.shift > 0 ? ax.blk.Rmin : 0.0
    if !path.inf_pe || !path.inf_x0
        kappa = _flatten_for_ridge(path, ax.blk, v, tt, wv, kappa, rfc)
    end
    res = _lp_zero()
    for _ in 1:4
        strip = _parabola_strip(ax, v, kappa)
        psi2e = _path_curvature(psi2, tt, loc !== nothing ? loc.D : NaN, kappa)
        w_y, rate_u = _path_frequency(path, ax.blk, v, tt, kappa, wv - 25, rfc, nothing, strip)
        w_y = _ff_max(omega, w_y)
        w_u = _ff_max(omega * sqrt(strip * strip + 50 / psi2e), rate_u)
        c = _node_scale(strip, psi2e, 1.5 * LP_PI / sqrt(18.5 * psi2), w_y, w_u)
        res = _parabola_sums(path, ws, ax, tt, v, kappa, psi2, c > 0 ? w_u : w_y, rtol, atol, Float64(n0 + max_eval),
                             strip, c)
        res.regrow || break
        kappa /= 8
    end
    (res.regrow || res.bad) && return LPInv(NaN, NaN, NaN, Inf, Inf, false, false)
    return res
end

function _parabola_strip(ax::LPAxis, v::Float64, kappa::Float64)
    dist = v - ax.s0
    strip = Inf
    if dist > 0 && isfinite(dist)
        if kappa * dist < 1e-12
            strip = dist
        elseif 4 * kappa * dist >= 1
            strip = 1 / (2 * kappa)
        else
            strip = (1 - sqrt(1 - 4 * kappa * dist)) / (2 * kappa)
        end
    end
    strip > 0 || (strip = dist > 0 ? dist : Inf)
    return strip
end

@inline _path_curvature(psi2::Float64, t::Float64, dv::Float64, kappa::Float64) =
    psi2 + 2 * _ff_max(0.0, isfinite(dv) ? t - dv : 0.0) * kappa

const LP_SINH_RATIO = 0.1
const LP_SINH_STEP = 0.3

function _node_scale(strip::Float64, psi2e::Float64, gauss_step::Float64, w_y::Float64, w_u::Float64)
    (!(psi2e > 0) || !(strip * sqrt(psi2e) < LP_SINH_RATIO)) && return 0.0
    step_y = _ff_min(gauss_step, w_y > 0 ? 0.5 * LP_PI / w_y : Inf)
    0.5 * strip < step_y || return 0.0
    reach = sqrt(83 / psi2e)
    n_y = reach / (0.5 * strip)
    n_u = casinh(reach / strip) / _sinh_step(strip, gauss_step, w_u)
    return n_u < n_y ? strip : 0.0
end

@inline _sinh_step(c::Float64, gauss_step::Float64, w_u::Float64) =
    _ff_min(_ff_min(LP_SINH_STEP, w_u > 0 ? 0.5 * LP_PI / w_u : Inf), gauss_step / c)

function _parabola_sums(path::LaplacePath, ws::LPWorkspace, ax::LPAxis, tt::Float64, v::Float64, kappa::Float64,
                        psi2::Float64, omega::Float64, rtol::Float64, atol::Float64, stop::Float64, strip::Float64,
                        c::Float64=0.0)
    if c > 0
        strip_u = LP_PI / 4
        step = _sinh_step(c, 1.5 * LP_PI / sqrt(18.5 * psi2), omega)
    else
        step = 1.5 * LP_PI / sqrt(18.5 * psi2)
        omega > 0 && (step = _ff_min(step, 0.5 * LP_PI / omega))
        strip_u = strip
        step = _ff_min(step, 0.5 * strip)
    end
    ss = ax.kind == LP_INVENTORY ? _off_lambda(ax.blk, v, 0.25 * (c > 0 ? c * step : step)) : v
    acc = LPAcc(stop)
    _parabola_sweep(path, ws, ax, tt, ss, kappa, step, 0.0, acc, c)
    acc.regrow && return LPInv(NaN, NaN, NaN, Inf, Inf, true, false)
    h = acc.h * step / LP_PI
    dh = acc.dh * step / LP_PI
    d2 = acc.d2 * step / LP_PI
    err = Inf
    agreed = 0
    for level in 0:11
        (acc.bad || ws.evaluations > stop) && break
        half = step / 2
        a2 = LPAcc(stop)
        _parabola_sweep(path, ws, ax, tt, ss, kappa, half, half, a2, c)
        a2.regrow && return LPInv(NaN, NaN, NaN, Inf, Inf, true, false)
        if a2.bad
            acc.bad = true
            break
        end
        a2.cut && (acc.cut = true)
        acc.h += a2.h
        acc.dh += a2.dh
        acc.d2 += a2.d2
        acc.abs += a2.abs
        step = half
        h2 = acc.h * step / LP_PI
        err = abs(h2 - h)
        h = h2
        dh = acc.dh * step / LP_PI
        d2 = acc.d2 * step / LP_PI
        floor_ = 1e-15 * acc.abs * step / LP_PI + atol
        rel = err / _ff_max(abs(h), 1e-300)
        edge = isfinite(strip_u) ? 2 * cexp(-2 * LP_PI * strip_u / step) : 0.0
        nxt = _ff_max(rel * rel, edge)
        ok = err <= floor_ || (level >= 1 && err <= rtol * abs(h) && nxt <= rtol) ||
             (!(c > 0) && step <= 0.3 * strip_u && nxt <= rtol * 1e-2)
        agreed = ok ? agreed + 1 : 0
        if ok && (agreed >= 2 || !path.inf_pe)
            err = _ff_min(err, nxt * abs(h) + floor_)
            break
        end
    end
    acc.bad && return LPInv(NaN, NaN, NaN, Inf, Inf, false, true)
    cond = acc.abs * step / LP_PI / _ff_max(abs(h), 1e-300)
    acc.cut && (err = Inf)
    return LPInv(h, dh, d2, err, cond, false, false)
end

# --- shared contours: one parabola for the times of a cell ------------------------------------------

const LP_CELL_C = 2
const LP_CELL_F = 2
const LP_CELL_PROBES = (-0.5, -0.25, 0.0, 0.25, 0.5)
const LP_CELL_COND = 1e6
const LP_CELL_PRUNE = 1e-20
const LP_CELL_NEGLIGIBLE = 1e-20
const LP_CELL_MAX_EVAL = 24000
const LP_LN_F = clog(Float64(LP_CELL_F))
const LP_CELL_SLOPE = 1 / (2 * LP_LN_F)
const LP_LN_PRUNE = clog(LP_CELL_PRUNE)
const LP_LN2 = clog(2.0)

function _cell_span(t1::Float64, t2::Float64, sig::Float64)
    (!(sig > 0) || !isfinite(sig)) && return LP_CELL_SLOPE * _py_log(t2 / t1)
    tk = LP_CELL_C * sig / LP_LN_F
    t2 <= tk && return LP_CELL_SLOPE * _py_log(t2 / t1)
    t1 >= tk && return (t2 - t1) / (2 * LP_CELL_C * sig)
    return LP_CELL_SLOPE * _py_log(tk / t1) + (t2 - tk) / (2 * LP_CELL_C * sig)
end

"""A cell's parabola, built and summed at its probe times, and its nodes (`buildCell`)."""
mutable struct LPCell
    ok::Bool
    k::Float64
    tLo::Float64
    tA::Float64
    tHi::Float64
    why::String
    v::Float64
    step::Float64
    levels::Int
    strip::Float64
    c::Float64
    n::Int
    sr::Vector{Float64}
    si::Vector{Float64}
    gr::Vector{Float64}
    gi::Vector{Float64}
    ag::Vector{Float64}
    la::Vector{Float64}
    mE::Vector{Float64}
    lev::Vector{Int}
end
_lp_failed_cell(k, t_lo, t_a, t_hi, why) = LPCell(false, Float64(k), t_lo, t_a, t_hi, why, NaN, NaN, 0, NaN, 0.0, 0,
                                                  Float64[], Float64[], Float64[], Float64[], Float64[], Float64[],
                                                  Float64[], Int[])

"""The cells of one axis, built as times ask for them (`makeCells`)."""
mutable struct LPCells
    ax::LPAxis
    tb::Vector{Float64}
    U::Vector{Float64}
    sig::Vector{Float64}
    map::Dict{Float64,LPCell}
    peak::Float64
    infPe::Bool
    rtol::Float64
    atol::Float64
    maxEval::Int
    stats::Dict{String,Int}
    pt::Vector{Float64}
end

function _cell_u(C::LPCells, tt::Float64)
    tb = C.tb
    nb = length(tb)
    nb == 0 && return LP_CELL_SLOPE * _py_log(tt)
    tt <= tb[1] && return LP_CELL_SLOPE * _py_log(tt / tb[1])
    tt >= tb[nb] && return C.U[nb] + LP_CELL_SLOPE * _py_log(tt / tb[nb])
    lo = 0
    hi = nb - 1
    while hi - lo > 1
        c = (lo + hi) >> 1
        if tb[c+1] <= tt
            lo = c
        else
            hi = c
        end
    end
    return C.U[lo+1] + _cell_span(tb[lo+1], tt, C.sig[lo+1])
end

function _cell_t(C::LPCells, u::Float64)
    tb = C.tb
    nb = length(tb)
    U = C.U
    nb == 0 && return cexp(u / LP_CELL_SLOPE)
    u <= 0 && return tb[1] * cexp(u / LP_CELL_SLOPE)
    u >= U[nb] && return tb[nb] * cexp((u - U[nb]) / LP_CELL_SLOPE)
    lo = 0
    hi = nb - 1
    while hi - lo > 1
        c = (lo + hi) >> 1
        if U[c+1] <= u
            lo = c
        else
            hi = c
        end
    end
    t1 = tb[lo+1]
    sig = C.sig[lo+1]
    du = u - U[lo+1]
    (!(sig > 0) || !isfinite(sig)) && return t1 * cexp(du / LP_CELL_SLOPE)
    tk = LP_CELL_C * sig / LP_LN_F
    t1 >= tk && return t1 + du * 2 * LP_CELL_C * sig
    uk = LP_CELL_SLOPE * _py_log(tk / t1)
    return du <= uk ? t1 * cexp(du / LP_CELL_SLOPE) : tk + (du - uk) * 2 * LP_CELL_C * sig
end

function _make_cells(path::LaplacePath, ax::LPAxis, atol::Float64, peak::Float64)
    D = ax.D
    sm = ax.sm
    tb = Float64[]
    sb = Float64[]
    last = Inf
    for k in 1:length(D)
        d = D[k]
        if !isfinite(d)
            isempty(tb) || break
            continue
        end
        (!(d > 0) || !(d < last)) && continue
        push!(tb, d)
        push!(sb, sm[k])
        last = d
    end
    reverse!(tb)
    reverse!(sb)
    nb = length(tb)
    U = zeros(nb)
    sig = zeros(max(0, nb - 1))
    for m in 1:nb-1
        den = sb[m] - sb[m+1]
        psi2 = den != 0 ? (tb[m+1] - tb[m]) / den : NaN
        sig[m] = (psi2 > 0 && isfinite(psi2)) ? sqrt(psi2) : NaN
        U[m+1] = U[m] + _cell_span(tb[m], tb[m+1], sig[m])
    end
    if !(peak > 0)
        lp = -Inf
        for t in tb
            lp = _ff_max(lp, _log_estimate(ax, t + ax.shift))
        end
        peak = isfinite(lp) ? cexp(lp) : 0.0
    end
    stats = Dict("shared" => 0, "fallback" => 0, "negligible" => 0, "cells" => 0, "failed" => 0, "dehoog" => 0)
    return LPCells(ax, tb, U, sig, Dict{Float64,LPCell}(), peak, path.inf_pe, 1e-11, atol, LP_CELL_MAX_EVAL, stats,
                   zeros(length(LP_CELL_PROBES)))
end

"""The nodes a cell's sweeps leave: s, the weighted factor of its term, its scale and its level."""
struct LPNodes
    sr::Vector{Float64}
    si::Vector{Float64}
    gr::Vector{Float64}
    gi::Vector{Float64}
    E::Vector{Float64}
    lev::Vector{Int}
end
LPNodes() = LPNodes(Float64[], Float64[], Float64[], Float64[], Float64[], Int[])

mutable struct LPCellAcc
    h::Vector{Float64}
    abs::Vector{Float64}
    bad::Bool
    regrow::Bool
    cut::Bool
    stop::Float64
end

function _cell_sweep(path::LaplacePath, ws::LPWorkspace, C::LPCells, ss::Float64, kappa::Float64, step::Float64,
                     off::Float64, level::Int, acc::LPCellAcc, nodes::LPNodes, c::Float64=0.0)
    ax = C.ax
    blk = ax.blk
    kind = ax.kind
    P = C.pt
    npr = length(P)
    ah = acc.h
    aa = acc.abs
    mods = zeros(npr)
    max_mod = zeros(npr)
    min_env = fill(Inf, npr)
    small = zeros(Int, npr)
    last = zeros(7 * npr)
    for k in 0:19999
        u = off + k * (off != 0 ? 2 * step : step)
        Y = c > 0 ? c * csinh(u) : u
        jac = c > 0 ? c * ccosh(u) : 1.0
        wgt = u == 0 ? 0.5 : 1.0
        w = wgt * jac
        sr = ss - kappa * Y * Y
        si = Y
        F = _eval_block(path, ws, blk, ComplexF64(sr, si), kind)
        Fr = real(F)
        Fi = imag(F)
        E = ws.E
        q = 2 * kappa * Y
        gr = w * (Fr - Fi * q)
        gi = w * (Fi + Fr * q)
        push!(nodes.sr, sr)
        push!(nodes.si, si)
        push!(nodes.gr, gr)
        push!(nodes.gi, gi)
        push!(nodes.E, E)
        push!(nodes.lev, level)
        for p in 1:npr
            t = P[p]
            ex = t * sr - E
            m = 0.0
            if ex > 700
                acc.bad = true
                m = Inf
            elseif !(ex < -740 || (Fr == 0 && Fi == 0))
                e = _cexp(ComplexF64(ex, t * si))
                zr = real(e) * gr - imag(e) * gi
                zi = real(e) * gi + imag(e) * gr
                ah[p] += zr
                m = py_hypot(zr, zi)
                aa[p] += m
                m /= wgt
            end
            mods[p] = m
        end
        if u == 0
            for p in 1:npr
                max_mod[p] = _ff_max(max_mod[p], mods[p])
            end
            continue
        end
        dead = k > 3
        for p in 1:npr
            m = mods[p]
            if k > 3 && (m > 100 * max_mod[p] || (min_env[p] < 1e-6 * max_mod[p] && m > 1e-3 * max_mod[p]))
                acc.regrow = true
                return nothing
            end
            m > max_mod[p] && (max_mod[p] = m)
            last[7*(p-1)+k%7+1] = m
            if k >= 7
                env = 0.0
                for r in 7*(p-1)+1:7*(p-1)+7
                    last[r] > env && (env = last[r])
                end
                env < min_env[p] && (min_env[p] = env)
            end
            if m <= 1e-18 * max_mod[p]
                small[p] += 1
            else
                small[p] = 0
            end
            small[p] < 3 && (dead = false)
        end
        dead && return nothing
        acc.bad && return nothing
        ws.evaluations > acc.stop && break
    end
    acc.cut = true
    return nothing
end

"""The sums of a cell's parabola at every probe time (`cellSums`): (ok, why, regrow, step, levels, strip, c, ss, nodes)."""
function _cell_sums(path::LaplacePath, ws::LPWorkspace, C::LPCells, v::Float64, kappa::Float64, psi2::Float64,
                    omega::Float64, stop::Float64, strip::Float64, c::Float64=0.0)
    ax = C.ax
    npr = length(C.pt)
    rtol = C.rtol
    if c > 0
        strip_u = LP_PI / 4
        step = _sinh_step(c, 1.5 * LP_PI / sqrt(18.5 * psi2), omega)
    else
        step = 1.5 * LP_PI / sqrt(18.5 * psi2)
        omega > 0 && (step = _ff_min(step, 0.5 * LP_PI / omega))
        strip_u = strip
        step = _ff_min(step, 0.5 * strip)
    end
    ss = ax.kind == LP_INVENTORY ? _off_lambda(ax.blk, v, 0.25 * (c > 0 ? c * step : step)) : v
    acc = LPCellAcc(zeros(npr), zeros(npr), false, false, false, stop)
    nodes = LPNodes()
    fail(why) = (ok=false, why=why, regrow=false, step=NaN, levels=0, strip=NaN, c=c, ss=ss, nodes=nodes)
    _cell_sweep(path, ws, C, ss, kappa, step, 0.0, 0, acc, nodes, c)
    acc.regrow && return (ok=false, why="", regrow=true, step=NaN, levels=0, strip=NaN, c=c, ss=ss, nodes=nodes)
    (acc.bad || acc.cut) && return fail(acc.bad ? "overflow" : "cut short")
    h = Float64[x * step / LP_PI for x in acc.h]
    agreed = 0
    for level in 0:11
        ws.evaluations > stop && break
        half = step / 2
        _cell_sweep(path, ws, C, ss, kappa, half, half, level + 1, acc, nodes, c)
        acc.regrow && return (ok=false, why="", regrow=true, step=NaN, levels=0, strip=NaN, c=c, ss=ss, nodes=nodes)
        (acc.bad || acc.cut) && return fail(acc.bad ? "overflow" : "cut short")
        step = half
        edge = isfinite(strip_u) ? 2 * cexp(-2 * LP_PI * strip_u / step) : 0.0
        every = true
        for p in 1:npr
            h2 = acc.h[p] * step / LP_PI
            err = abs(h2 - h[p])
            h[p] = h2
            floor_ = 1e-15 * acc.abs[p] * step / LP_PI + C.atol
            rel = err / _ff_max(abs(h2), 1e-300)
            nxt = _ff_max(rel * rel, edge)
            if !(err <= floor_ || (level >= 1 && err <= rtol * abs(h2) && nxt <= rtol) ||
                 (!(c > 0) && step <= 0.3 * strip_u && nxt <= rtol * 1e-2))
                every = false
            end
        end
        agreed = every ? agreed + 1 : 0
        if every && (agreed >= 2 || !path.inf_pe)
            return (ok=true, why="", regrow=false, step=step, levels=level + 1, strip=strip_u, c=c, ss=ss, nodes=nodes)
        end
    end
    return fail(ws.evaluations > stop ? "budget" : "no agreement")
end

function _build_cell(path::LaplacePath, ws::LPWorkspace, C::LPCells, k::Float64)
    ax = C.ax
    t_a = _cell_t(C, k)
    t_lo = _cell_t(C, k - 0.5)
    t_hi = _cell_t(C, k + 0.5)
    fail(why) = _lp_failed_cell(k, t_lo, t_a, t_hi, why)
    (!(t_lo > 0) || !(t_a > t_lo) || !(t_hi > t_a) || !isfinite(t_hi)) && return fail("lattice")
    sad = _saddle_at(ax, t_a)
    (sad === nothing || sad.beyond || sad.w < -720) && return fail("negligible")
    n0 = ws.evaluations
    v, loc, psi2 = _parabola_vertex(path, ws, ax, t_a, sad)
    psi_v = sad.w - t_a * v
    d_v = t_a
    if loc !== nothing
        (!isfinite(loc.psi) || !isfinite(loc.D)) && return fail("axis")
        psi_v = loc.psi
        d_v = loc.D
    end
    omega = _ff_max(abs(t_lo - d_v), abs(t_hi - d_v))
    kappa = _ff_max(psi2 / (2 * t_a), 0.25 / (v - ax.s0))
    blk = ax.blk
    rfc = ax.shift > 0 ? blk.Rmin : 0.0
    if !path.inf_pe || !path.inf_x0
        kappa = _flatten_for_ridge(path, blk, v, t_lo, t_lo * v + psi_v, kappa, rfc)
    end
    C.pt = Float64[_cell_t(C, k + p) for p in LP_CELL_PROBES]
    local res
    for _ in 1:4
        strip = _parabola_strip(ax, v, kappa)
        psi2lo = _ff_max(psi2 * t_lo / t_a, psi2 + 2 * (t_lo - d_v) * kappa)
        psi2hi = psi2 * t_hi / t_a
        w_y, rate_u = _path_frequency(path, blk, v, t_lo, kappa, t_lo * v + psi_v - 25, rfc, t_hi, strip)
        w_y = _ff_max(omega, w_y)
        w_u = _ff_max(omega * sqrt(strip * strip + 50 / psi2lo), rate_u)
        c = _node_scale(strip, psi2lo, 1.5 * LP_PI / sqrt(18.5 * psi2hi), w_y, w_u)
        res = _cell_sums(path, ws, C, v, kappa, psi2hi, c > 0 ? w_u : w_y, Float64(n0 + C.maxEval), strip, c)
        res.regrow || break
        kappa /= 8
    end
    res.ok || return fail(res.regrow ? "regrowth" : res.why)
    nd = res.nodes
    n_sr = nd.sr
    n_gr = nd.gr
    n_gi = nd.gi
    n_e = nd.E
    ss = res.ss
    nn = length(n_sr)
    lg = Float64[_lp_ln(py_hypot(n_gr[q], n_gi[q])) - n_e[q] for q in 1:nn]
    top = lg[1] + LP_LN2 + LP_LN_PRUNE
    keep = Int[q for q in 1:nn if q == 1 ||
                                  !(t_lo * (n_sr[q] - ss) + lg[q] < top && t_hi * (n_sr[q] - ss) + lg[q] < top)]
    ag = Float64[py_hypot(n_gr[q], n_gi[q]) for q in keep]
    return LPCell(true, k, t_lo, t_a, t_hi, "", v, res.step, res.levels, res.strip, res.c, length(keep),
                  n_sr[keep], nd.si[keep], n_gr[keep], n_gi[keep], ag, Float64[_lp_ln(x) for x in ag],
                  Float64[-n_e[q] for q in keep], nd.lev[keep])
end

"""The response, h' and h'' at tt from a cell's nodes, or nothing when the result does not pass."""
function _cell_sample(C::LPCells, cell::LPCell, tt::Float64)
    n = cell.n
    sr = cell.sr
    si = cell.si
    gr = cell.gr
    gi = cell.gi
    ag = cell.ag
    la = cell.la
    mE = cell.mE
    lev = cell.lev
    L = cell.levels
    low = tt * sr[1] + mE[1] + la[1] + LP_LN_PRUNE
    h = 0.0
    d1 = 0.0
    d2 = 0.0
    a = 0.0
    h1 = 0.0
    a1 = 0.0
    h2 = 0.0
    for q in 1:n
        ex = tt * sr[q] + mE[q]
        ex > 700 && return nothing
        (ex < -740 || ex + la[q] < low) && continue
        e = cexp(ex)
        ph = tt * si[q]
        er = e * ccos(ph)
        ei = e * csin(ph)
        g_r = gr[q]
        g_i = gi[q]
        zr = er * g_r - ei * g_i
        zi = er * g_i + ei * g_r
        s_r = sr[q]
        s_i = si[q]
        yr = s_r * zr - s_i * zi
        yi = s_r * zi + s_i * zr
        m = e * ag[q]
        h += zr
        d1 += yr
        d2 += s_r * yr - s_i * yi
        a += m
        if lev[q] < L
            h1 += zr
            a1 += m
            lev[q] < L - 1 && (h2 += zr)
        end
    end
    rtol = C.rtol
    atol = C.atol
    strip = cell.strip
    function passes(hn, hp, an, st, level)
        err = abs(hn - hp)
        floor_ = 1e-15 * an + atol
        rel = err / _ff_max(abs(hn), 1e-300)
        nxt = _ff_max(rel * rel, isfinite(strip) ? 2 * cexp(-2 * LP_PI * strip / st) : 0.0)
        ok = err <= floor_ || (level >= 1 && err <= rtol * abs(hn) && nxt <= rtol) ||
             (!(cell.c > 0) && st <= 0.3 * strip && nxt <= rtol * 1e-2)
        return ok ? _ff_min(err, nxt * abs(hn) + floor_) : -1.0
    end
    st = cell.step
    c = st / LP_PI
    H = h * c
    H1 = h1 * 2 * c
    A = a * c
    err = passes(H, H1, A, st, L - 1)
    err >= 0 || return nothing
    (C.infPe && !(passes(H1, h2 * 4 * c, a1 * 2 * c, 2 * st, L - 2) >= 0)) && return nothing
    cond = A / _ff_max(abs(H), 1e-300)
    (!isfinite(H) || !(cond <= LP_CELL_COND || A <= LP_CELL_NEGLIGIBLE * C.peak)) && return nothing
    err > 1e-6 * abs(H) + atol && return nothing
    return LPInv(H, d1 * c, d2 * c, err, cond, false, false)
end

"""The response at t from the shared parabola of t's cell, building the cell when first asked for;
the zeros where the saddle rule makes it negligible; nothing when the cell cannot serve t."""
function _invert_shared(path::LaplacePath, ws::LPWorkspace, C::LPCells, t::Float64)
    ax = C.ax
    stats = C.stats
    tt = t - ax.shift
    if !(tt > 0)
        stats["negligible"] += 1
        return _lp_zero()
    end
    sad = _saddle_at(ax, tt)
    if sad === nothing || sad.beyond || sad.w < -720
        stats["negligible"] += 1
        return _lp_zero()
    end
    u = _cell_u(C, tt) + 0.5
    k = isfinite(u) ? floor(u) : (u == u ? u : NaN)
    cell = get(C.map, k, nothing)
    if cell === nothing
        cell = _build_cell(path, ws, C, k)
        C.map[k] = cell
        stats["cells"] += 1
        cell.ok || (stats["failed"] += 1)
    end
    r = (cell.ok && isfinite(k)) ? _cell_sample(C, cell, tt) : nothing
    if r !== nothing
        stats["shared"] += 1
    else
        stats["fallback"] += 1
    end
    return r
end

"""De Hoog's M for this path (`deHoogTerms`)."""
function _de_hoog_terms(path::LaplacePath, ax::Union{Nothing,LPAxis}=nothing, t::Float64=0.0)
    m = path.inf_pe ? 24 : max(24, ceil(Int, 1.2 * sqrt(path.Pe)))
    if ax !== nothing
        tt = t - ax.shift
        sad = tt > 0 ? _saddle_at(ax, tt) : nothing
        if sad !== nothing && !sad.beyond && sad.psi2 > 0
            m = max(m, ceil(Int, 1.7 * tt / sqrt(sad.psi2)))
        end
    end
    return min(160, m)
end

"""De Hoog's method on the Bromwich line, its `deriv`th derivative (-1 the integral)."""
function _invert_de_hoog(path::LaplacePath, ws::LPWorkspace, blk::LPBlock, kind::Int, shift::Float64, t::Float64,
                         M::Int, deriv::Int=0)
    tt = t - shift
    tt > 0 || return 0.0
    tol = 1e-12
    T = 2 * tt
    gamma = -_py_log(tol) / (2 * T)
    K = 2 * M
    a = zeros(ComplexF64, K + 1)
    E0 = 0.0
    k_use = K
    for k in 0:K
        F = _eval_block(path, ws, blk, ComplexF64(gamma, k * LP_PI / T), kind)
        k == 0 && (E0 = ws.E)
        sc = cexp(E0 - ws.E)
        v = ComplexF64(real(F) * sc, imag(F) * sc)
        for _ in 1:deriv
            sr = gamma
            si = k * LP_PI / T
            v = ComplexF64(sr * real(v) - si * imag(v), sr * imag(v) + si * real(v))
        end
        for _ in 1:(deriv < 0 ? -deriv : 0)
            v = _cdiv(v, ComplexF64(gamma, k * LP_PI / T))
        end
        a[k+1] = v
        if !(real(v) != 0 || imag(v) != 0) || !isfinite(real(v)) || !isfinite(imag(v))
            k_use = k - 1
            break
        end
    end
    mod(k_use, 2) == 1 && (k_use -= 1)
    k_use < 2 && return NaN
    Mu = k_use ÷ 2
    a[1] = ComplexF64(real(a[1]) * 0.5, imag(a[1]) * 0.5)
    q = zeros(ComplexF64, k_use)
    e = zeros(ComplexF64, k_use + 1)
    d = zeros(ComplexF64, k_use + 1)
    for k in 0:k_use-1
        q[k+1] = _cdiv(a[k+2], a[k+1])
    end
    d[1] = a[1]
    for r in 1:Mu
        for k in 0:k_use-2r
            e[k+1] = q[k+2] - q[k+1] + e[k+2]
        end
        d[2r] = -q[1]
        d[2r+1] = -e[1]
        if r < Mu
            for k in 0:k_use-2r-1
                x = q[k+2]
                y = e[k+2]
                q[k+1] = _cdiv(ComplexF64(real(x) * real(y) - imag(x) * imag(y), real(x) * imag(y) + imag(x) * real(y)),
                               e[k+1])
            end
        end
    end
    zr = ccos(LP_PI * tt / T)
    zi = csin(LP_PI * tt / T)
    A2 = ComplexF64(0.0, 0.0)
    A1 = d[1]
    B2 = ComplexF64(1.0, 0.0)
    B1 = ComplexF64(1.0, 0.0)
    for k in 1:k_use
        c = ComplexF64(real(d[k+1]) * zr - imag(d[k+1]) * zi, real(d[k+1]) * zi + imag(d[k+1]) * zr)
        if k < k_use
            An = A1 + ComplexF64(real(c) * real(A2) - imag(c) * imag(A2), real(c) * imag(A2) + imag(c) * real(A2))
            Bn = B1 + ComplexF64(real(c) * real(B2) - imag(c) * imag(B2), real(c) * imag(B2) + imag(c) * real(B2))
        else
            d1 = d[k_use] - d[k_use+1]
            hr = 0.5 * (1 + real(d1) * zr - imag(d1) * zi)
            hi = 0.5 * (real(d1) * zi + imag(d1) * zr)
            h2 = ComplexF64(hr * hr - hi * hi, 2 * hr * hi)
            u = _cdiv(c, h2)
            w = _csqrt(ComplexF64(1 + real(u), imag(u)))
            Rr = -(hr * (1 - real(w)) - hi * (-imag(w)))
            Ri = -(hr * (-imag(w)) + hi * (1 - real(w)))
            An = A1 + ComplexF64(Rr * real(A2) - Ri * imag(A2), Rr * imag(A2) + Ri * real(A2))
            Bn = B1 + ComplexF64(Rr * real(B2) - Ri * imag(B2), Rr * imag(B2) + Ri * real(B2))
        end
        A2 = A1
        A1 = An
        B2 = B1
        B1 = Bn
    end
    res = _cdiv(A1, B1)
    return cexp(gamma * tt - E0) / T * real(res)
end

# --- unit responses on adaptive grids ---------------------------------------------------------------

const LP_RESP_PER_DECADE = 10
const LP_RESP_RTOL = 2e-8
const LP_RESP_ATOL = 1e-13
const LP_RESP_MAXPTS = 6000
const LP_T_CAP = 1e12

function _log_estimate(ax::LPAxis, t::Float64)
    tt = t - ax.shift
    tt > 0 || return -Inf
    sad = _saddle_at(ax, tt)
    (sad === nothing || sad.beyond || !isfinite(sad.w)) && return -Inf
    c = (isfinite(sad.psi2) && sad.psi2 > 0) ? -0.5 * _py_log(2 * LP_PI * sad.psi2) : 0.0
    return sad.w + c
end

function _response_support(ax::LPAxis, t_min::Float64, t_max::Float64)
    d = ax.shift
    u_min = t_min - d
    u_max = t_max - d
    per = 16
    n = max(2, ceil(Int, clog10(u_max / u_min) * per) + 1)
    ts = zeros(n)
    est = zeros(n)
    wmax = -Inf
    kmax = -1
    for k in 0:n-1
        ts[k+1] = d + u_min * py_pow(u_max / u_min, k / (n - 1))
        est[k+1] = _log_estimate(ax, ts[k+1])
        if est[k+1] > wmax
            wmax = est[k+1]
            kmax = k
        end
    end
    isfinite(wmax) || return nothing
    k_lo = 0
    while k_lo < n && !(est[k_lo+1] > wmax - 62)
        k_lo += 1
    end
    k_hi = n - 1
    while k_hi > kmax && !(est[k_hi+1] > wmax - 72)
        k_hi -= 1
    end
    k_tail = n - 1
    while k_tail > kmax && !(est[k_tail+1] > wmax - 20.7)
        k_tail -= 1
    end
    return (tLo=ts[max(0, k_lo - 1)+1], tHi=k_hi >= n - 1 ? t_max : ts[min(n - 1, k_hi + 1)+1], tPeak=ts[kmax+1],
            logPeak=wmax, tTail=k_tail >= n - 1 ? t_max : ts[min(n - 1, k_tail + 1)+1])
end

"""The share of an axis's samples that fell back to de Hoog's method so far."""
mutable struct LPHint
    tries::Int
    fails::Int
end

@inline _cond_or_one(c::Float64) = c == 0.0 ? 1.0 : c

"""One sample (h, h', h'', cond, err) by the default method: the shared parabola of t's cell, t's own
where that cannot serve, de Hoog's method where that one fails too."""
function _sample(path::LaplacePath, ws::LPWorkspace, ax::LPAxis, t::Float64, atol::Float64, hint::Union{Nothing,LPHint},
                 cells::Union{Nothing,LPCells})
    hint === nothing || (hint.tries += 1)
    if cells !== nothing
        s = _invert_shared(path, ws, cells, t)
        s === nothing || return (s.h, s.dh, s.d2, _cond_or_one(s.cond), s.err)
    end
    direct = hint !== nothing && hint.tries > 16 && hint.fails > 0.75 * hint.tries
    r = direct ? LPInv(NaN, NaN, NaN, Inf, NaN, false, false) : _invert_parabola(path, ws, ax, t, atol)
    if isfinite(r.h) && !(r.err > 1e-6 * abs(r.h) + atol)
        return (r.h, r.dh, r.d2, _cond_or_one(r.cond), r.err)
    end
    hint === nothing || (hint.fails += 1)
    cells === nothing || (cells.stats["dehoog"] += 1)
    m1 = _de_hoog_terms(path, ax, t)
    m2 = min(2 * m1, 320)
    blk, kind, shift = ax.blk, ax.kind, ax.shift
    a_ = _invert_de_hoog(path, ws, blk, kind, shift, t, m1)
    b_ = _invert_de_hoog(path, ws, blk, kind, shift, t, m2)
    e_h = abs(a_ - b_)
    if isfinite(b_) && (!isfinite(r.h) || !isfinite(r.err) || e_h < r.err)
        d1 = _invert_de_hoog(path, ws, blk, kind, shift, t, m2, 1)
        d2 = _invert_de_hoog(path, ws, blk, kind, shift, t, m2, 2)
        (isfinite(d1) && isfinite(d2)) && return (b_, d1, d2, 1.0, e_h + atol)
    end
    isfinite(r.h) && return (r.h, r.dh, r.d2, _cond_or_one(r.cond), r.err)
    if direct
        s2 = _invert_parabola(path, ws, ax, t, atol)
        isfinite(s2.h) && return (s2.h, s2.dh, s2.d2, _cond_or_one(s2.cond), s2.err)
    end
    return (0.0, 0.0, 0.0, Inf, Inf)
end

@inline function _hermite5(ta::Float64, ya::Float64, da::Float64, ea::Float64, tb::Float64, yb::Float64, db::Float64,
                           eb::Float64, t::Float64)
    d = tb - ta
    x = (t - ta) / d
    x2 = x * x
    x3 = x2 * x
    x4 = x3 * x
    x5 = x4 * x
    h0 = 1 - 10 * x3 + 15 * x4 - 6 * x5
    h1 = x - 6 * x3 + 8 * x4 - 3 * x5
    h2 = 0.5 * (x2 - 3 * x3 + 3 * x4 - x5)
    h4 = -4 * x3 + 7 * x4 - 3 * x5
    h5 = 0.5 * (x3 - 2 * x4 + x5)
    return h0 * ya + d * h1 * da + d * d * h2 * ea + (1 - h0) * yb + d * h4 * db + d * d * h5 * eb
end

"""A response tabulated with its first two derivatives (`computeResponse`), and its integral."""
mutable struct LPResponse
    t::Vector{Float64}
    h::Vector{Float64}
    dh::Vector{Float64}
    d2h::Vector{Float64}
    peak::Float64
    tPeak::Float64
    integral::Float64
    maxCond::Float64
    maxErr::Float64
    m0::Float64
    T0::Float64
    expected::Float64
    balanced::Bool
    rel::Float64
    checked::Bool
end
_lp_empty_response() = LPResponse(Float64[], Float64[], Float64[], Float64[], 0.0, NaN, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0,
                                  true, 0.0, false)

function _compute_response(sampler::Function, t_a::Float64, t_b::Float64, per::Int, max_pts::Int, delay::Float64,
                           peak_estimate::Float64)
    rtol = LP_RESP_RTOL
    atol_rel = LP_RESP_ATOL
    dl = delay
    n0 = max(16, ceil(Int, clog10((t_b - dl) / (t_a - dl)) * per) + 1)
    T = Float64[]
    H = Float64[]
    D = Float64[]
    D2 = Float64[]
    peak = 0.0
    max_cond = 1.0
    max_err = 0.0
    pe = peak_estimate
    atol = pe > 0 ? 1e-3 * LP_RESP_ATOL * pe : 0.0
    hint = LPHint(0, 0)
    for k in 0:n0-1
        t = dl + (t_a - dl) * py_pow((t_b - dl) / (t_a - dl), k / (n0 - 1))
        h, dh, d2, c, e = sampler(t, atol, hint)
        e > max_err && (max_err = e)
        push!(T, t)
        push!(H, h)
        push!(D, dh)
        push!(D2, d2)
        abs(h) > peak && (peak = abs(h))
        c > max_cond && (max_cond = c)
    end
    flag = fill(true, length(T) - 1)
    for _ in 1:30
        nT = [T[1]]
        nH = [H[1]]
        nD = [D[1]]
        nD2 = [D2[1]]
        nF = Bool[]
        inserted = false
        for k in 1:length(T)-1
            if flag[k] && length(T) + length(nT) < 2 * max_pts &&
               (T[k] == dl || (T[k+1] - dl) / (T[k] - dl) > 1 + 1e-9)
                tm = T[k] == dl ? dl + 0.5 * (T[k+1] - dl) : dl + sqrt((T[k] - dl) * (T[k+1] - dl))
                h, dh, d2, c, e = sampler(tm, _ff_max(atol, 1e-3 * LP_RESP_ATOL * peak), hint)
                e > max_err && (max_err = e)
                abs(h) > peak && (peak = abs(h))
                c > max_cond && (max_cond = c)
                p = _hermite5(T[k], H[k], D[k], D2[k], T[k+1], H[k+1], D[k+1], D2[k+1], tm)
                dh0 = hint.fails > 0.5 * hint.tries
                ok = abs(h - p) <= (dh0 ? _ff_max(rtol, 1e-7) : rtol) * abs(h) + (dh0 ? _ff_max(atol_rel, 1e-10) : atol_rel) * peak
                push!(nT, tm)
                push!(nH, h)
                push!(nD, dh)
                push!(nD2, d2)
                push!(nF, !ok)
                push!(nF, !ok)
                ok || (inserted = true)
            else
                push!(nF, false)
            end
            push!(nT, T[k+1])
            push!(nH, H[k+1])
            push!(nD, D[k+1])
            push!(nD2, D2[k+1])
        end
        T, H, D, D2, flag = nT, nH, nD, nD2, nF
        (!inserted || length(T) >= max_pts) && break
    end
    n = length(T)
    integral = 0.0
    t_peak = T[1]
    pk = -Inf
    for k in 1:n
        if H[k] > pk
            pk = H[k]
            t_peak = T[k]
        end
    end
    for k in 1:n-1
        d = T[k+1] - T[k]
        integral += d * (0.5 * (H[k] + H[k+1]) + d * (D[k] - D[k+1]) / 10 + d * d * (D2[k] + D2[k+1]) / 120)
    end
    return LPResponse(T, H, D, D2, _ff_max(pk, 0.0), t_peak, integral, max_cond, max_err / _ff_max(pk, 1e-300), 0.0, 0.0,
                      0.0, true, 0.0, false)
end

function _axis_of(path::LaplacePath, blk::LPBlock, kind::Int, shift::Float64)
    key = (blk.i, blk.j, kind)
    ax = get(path.axes, key, nothing)
    if ax === nothing
        t_lo = shift > 0 ? shift * (1 + 1e-9) : path.tw * 1e-6
        ax = _real_axis(path, path.ws, blk, kind, shift, t_lo, LP_T_CAP)
        ax.tLo = t_lo
        path.axes[key] = ax
    end
    return ax
end

"""Under plug flow, what arrives before a response's first time, kept as a point mass there."""
function _add_early_mass!(path::LaplacePath, ax::LPAxis, resp::LPResponse)
    resp.m0 = 0.0
    (!path.inf_pe || ax.kind == LP_INVENTORY || length(resp.t) < 2) && return nothing
    S = _invert_de_hoog(path, path.ws, ax.blk, ax.kind, ax.shift, resp.t[1], _de_hoog_terms(path), -1)
    if S > 0 && isfinite(S)
        resp.m0 = S
        resp.integral += S
    end
    return nothing
end

"""A release response's integral against what leaves the path by its last time: (ok, checked, expected, rel)."""
function _mass_balance(path::LaplacePath, ax::LPAxis, resp::LPResponse, tol::Float64)
    T0 = resp.T0
    abs(T0) > 1e-30 || return (ok=true, checked=false, expected=T0, rel=0.0)
    expected = T0
    n = length(resp.t)
    if n > 0
        tl = resp.t[n]
        tt = tl - ax.shift
        sad = tt > 0 ? _saddle_at(ax, tt) : nothing
        rest = (sad !== nothing && !sad.beyond && sad.s <= 0) ? cexp(sad.w) : Inf
        if !(rest <= 1e-10 * abs(T0))
            S = _invert_de_hoog(path, path.ws, ax.blk, ax.kind, ax.shift, tl, _de_hoog_terms(path), -1)
            isfinite(S) && (expected = S)
        end
    end
    rel = abs(resp.integral - expected) / _ff_max(abs(T0), 1e-10)
    return (ok=rel <= tol, checked=true, expected=expected, rel=rel)
end

"""
    unit_response(path, i, j, t_max) -> LPResponse

The release of i in response to a unit pulse of j at t = 0, tabulated on an adaptive grid over
[0, t_max], its integral held to what leaves the path by its last time and worked out again from
far earlier on a finer grid when it misses (`unitResponse`, the default inversion on shared
parabolas).
"""
function unit_response(path::LaplacePath, i::Int, j::Int, t_max::Float64)
    blk = _block_of(path, i, j)
    blk === nothing && return _lp_empty_response()
    ws = path.ws
    kind = LP_RELEASE
    shift = path.inf_pe ? path.tw * blk.Rmin : 0.0
    tm = _ff_min(t_max, LP_T_CAP)
    T0 = real(lp_transfer(path, 0.0, 0.0, i, j))
    isfinite(T0) || (T0 = real(lp_transfer(path, 1e-300, 0.0, i, j)))
    ax = _axis_of(path, blk, kind, shift)
    sup = _response_support(ax, ax.tLo, LP_T_CAP)
    t_a = sup !== nothing ? sup.tLo : NaN
    t_b = sup !== nothing ? _ff_min(sup.tHi, tm) : NaN
    peak_estimate = sup !== nothing ? cexp(sup.logPeak) : 0.0
    cells = _make_cells(path, ax, peak_estimate > 0 ? 1e-3 * LP_RESP_ATOL * peak_estimate : 0.0, peak_estimate)
    sampler = (t, atol, hint) -> _sample(path, ws, ax, t, atol, hint, cells)
    resp = (sup !== nothing && t_b > t_a * (1 + 1e-9)) ?
           _compute_response(sampler, t_a, t_b, LP_RESP_PER_DECADE, LP_RESP_MAXPTS, shift, peak_estimate) :
           _lp_empty_response()
    _add_early_mass!(path, ax, resp)
    resp.T0 = T0
    tol = _ff_max(1e-5, 50 * LP_RESP_RTOL)
    bal = _mass_balance(path, ax, resp, tol)
    if !bal.ok
        t_a2 = _ff_max(ax.tLo, (sup !== nothing ? sup.tLo : ax.tLo) / 1e3)
        t_b2 = sup !== nothing ? t_b : _ff_min(LP_T_CAP, tm)
        if t_b2 > t_a2 * (1 + 1e-9)
            r2 = _compute_response(sampler, t_a2, t_b2, 2 * LP_RESP_PER_DECADE, 2 * LP_RESP_MAXPTS, shift,
                                   peak_estimate)
            _add_early_mass!(path, ax, r2)
            r2.T0 = T0
            b2 = _mass_balance(path, ax, r2, tol)
            if b2.rel < bal.rel
                resp = r2
                bal = b2
            end
        end
    end
    resp.expected = bal.expected
    resp.balanced = bal.ok
    resp.rel = bal.rel
    resp.checked = bal.checked
    return resp
end
