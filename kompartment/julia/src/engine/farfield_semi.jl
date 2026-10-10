# The runtime of a far-field path worked out semi-analytically
# (kompartment/engine/farfield_semi.py, a port of `LaplaceFarfPath` in
# src/sim/farfield-laplace.js), beside `FarfPath` for the paths on cells:
#
# * no cells: one state per nuclide (per combination of the block's other
#   dimensions) for what the path holds, d(held)/dt = in - out - Lambda held;
# * `out`, the release, is the inflow's recorded history convolved with the
#   path's unit responses (farfield_laplace.jl), worked out once per run from
#   the settings at its first instant;
# * the history is recorded at every accepted step, output time and segment
#   start, a cubic through the last four records between them; two records at
#   one instant are a step, a jump of what is held between them an amount
#   delivered at once;
# * each recorded piece is kept as six moments about its centre, and pieces
#   merge while they are narrow beside every response spacing they will still
#   meet;
# * the step being taken (from the last record to the time asked about) is
#   integrated exactly against the response, the current inflow's weight
#   being the release's derivative along it (the Jacobian's).
#
# The arithmetic is the Python engine's, numpy's pairwise sum over the
# history included, so that a run is its run to the last bit.

const SEMI_RHO = 0.5
const SEMI_NEGLIGIBLE = 1e-15
const GL5_X = (-0.906179845938664, -0.5384693101056831, 0.0, 0.5384693101056831, 0.906179845938664)
const GL5_W = (0.23692688505618908, 0.47862867049936647, 0.5688888888888889, 0.47862867049936647, 0.23692688505618908)
const SEMI_BINOM = ((1,), (1, 1), (1, 2, 1), (1, 3, 3, 1), (1, 4, 6, 4, 1), (1, 5, 10, 10, 5, 1))

# --- one response, ready to convolve -----------------------------------------------------------

"""A unit response as quintic pieces in the power basis of each piece, with their running moments
and the narrowest spacing ahead of every lag."""
struct SemiKernel
    t::Vector{Float64}
    n::Int
    np::Int
    a::Matrix{Float64}          # 6 x np: piece k's coefficients in column k
    d::Vector{Float64}
    ahead::Vector{Float64}
    t0::Float64
    t_end::Float64
    m0::Float64
    tm0::Float64
    P::Matrix{Float64}          # n x 4: integral of h u^q up to t[k]
end

function SemiKernel(r::LPResponse)
    t = r.t
    n = length(t)
    npc = max(0, n - 1)
    h = r.h
    dh = r.dh
    d2h = r.d2h
    a = zeros(6, npc)
    d = zeros(npc)
    for k in 1:npc
        dk = t[k+1] - t[k]
        ya = h[k]
        da = dk * dh[k]
        ea = dk * dk * d2h[k]
        yb = h[k+1]
        db = dk * dh[k+1]
        eb = dk * dk * d2h[k+1]
        a[1, k] = ya
        a[2, k] = da
        a[3, k] = 0.5 * ea
        a[4, k] = -10 * ya - 6 * da - 1.5 * ea + 10 * yb - 4 * db + 0.5 * eb
        a[5, k] = 15 * ya + 8 * da + 1.5 * ea - 15 * yb + 7 * db - eb
        a[6, k] = -6 * ya - 3 * da - 0.5 * ea + 6 * yb - 3 * db + 0.5 * eb
        d[k] = dk
    end
    ahead = fill(Inf, npc + 1)
    for k in npc-1:-1:0
        ahead[k+1] = _ff_min(ahead[k+2], t[k+2] - t[k+1])
    end
    m0 = r.m0 > 0 && n > 0 ? r.m0 : 0.0
    K = SemiKernel(t, n, npc, a, d, ahead, n > 0 ? t[1] : Inf, n > 0 ? t[n] : -Inf, m0, n > 0 ? t[1] : Inf, zeros(n, 4))
    for k in 0:npc-1
        part = piece_moments(K, k, t[k+1], t[k+2])
        for q in 1:4
            K.P[k+2, q] = K.P[k+1, q] + part[q]
        end
    end
    return K
end

"""The piece (from 0) that holds lag u, clamped to the grid."""
function piece_at(kern::SemiKernel, u::Float64)
    t = kern.t
    u <= t[1] && return 0
    u >= t[kern.np+1] && return kern.np - 1
    # bisect_right(t, u) - 1
    lo = 0
    hi = length(t)
    while lo < hi
        mid = (lo + hi) >> 1
        if u < t[mid+1]
            hi = mid
        else
            lo = mid + 1
        end
    end
    return lo - 1
end

@inline function _poly(kern::SemiKernel, k::Int, x::Float64)
    a = kern.a
    return a[1, k+1] + x * (a[2, k+1] + x * (a[3, k+1] + x * (a[4, k+1] + x * (a[5, k+1] + x * a[6, k+1]))))
end

"""h at lag u, zero outside the tabulated span."""
function kernel_at(kern::SemiKernel, u::Float64)
    (!(u >= kern.t0) || !(u <= kern.t_end) || kern.np < 1) && return 0.0
    k = piece_at(kern, u)
    d = kern.t[k+2] - kern.t[k+1]
    return _poly(kern, k, (u - kern.t[k+1]) / d)
end

"""The integral of h(u) u^q over [ua, ub] inside piece k, q = 0..3."""
function piece_moments(kern::SemiKernel, k::Int, ua::Float64, ub::Float64)
    o1 = 0.0
    o2 = 0.0
    o3 = 0.0
    o4 = 0.0
    ub > ua || return (o1, o2, o3, o4)
    t0 = kern.t[k+1]
    d = kern.t[k+2] - t0
    c = 0.5 * (ua + ub)
    hw = 0.5 * (ub - ua)
    for g in 1:5
        u = c + GL5_X[g] * hw
        x = (u - t0) / d
        h = _poly(kern, k, x)
        w = GL5_W[g] * hw * h
        o1 += w
        o2 += w * u
        o3 += w * u * u
        o4 += w * u * u * u
    end
    return (o1, o2, o3, o4)
end

"""The integral of h(u) u^q over [0, D], q = 0..3."""
function running_moments(kern::SemiKernel, D::Float64)
    (!(D > kern.t0) || kern.np < 1) && return (0.0, 0.0, 0.0, 0.0)
    top = _ff_min(D, kern.t_end)
    k = piece_at(kern, top)
    rest = piece_moments(kern, k, kern.t[k+1], top)
    return (kern.P[k+1, 1] + rest[1], kern.P[k+1, 2] + rest[2], kern.P[k+1, 3] + rest[3], kern.P[k+1, 4] + rest[4])
end

"""The Lagrange basis of the nodes `s` (lags, the last zero) as polynomials in x = u/D over the step."""
function lag_basis(s::Vector{Float64}, count::Int, D::Float64)
    coef = Vector{NTuple{5,Float64}}(undef, count)
    row = zeros(5)
    for k in 0:count-1
        fill!(row, 0.0)
        row[1] = 1.0
        deg = 0
        den = 1.0
        sk = s[k+1] / D
        for m in 0:count-1
            m == k && continue
            sm = s[m+1] / D
            for q in deg+1:-1:1
                row[q+1] = row[q] - sm * row[q+1]
            end
            row[1] = -sm * row[1]
            deg += 1
            den *= sk - sm
        end
        for q in 0:deg
            row[q+1] /= den
        end
        coef[k+1] = (row[1], row[2], row[3], row[4], row[5])
    end
    return coef
end

"""Moments about c scaled by w as moments about nc scaled by nw."""
function semi_shift(mu::NTuple{6,Float64}, c::Float64, w::Float64, nc::Float64, nw::Float64)
    alpha = w / nw
    beta = (c - nc) / nw
    out = zeros(6)
    for m in 0:5
        s = 0.0
        for k in 0:m
            s += SEMI_BINOM[m+1][k+1] * _js_pow(alpha, k) * _js_pow(beta, m - k) * mu[k+1]
        end
        out[m+1] = s
    end
    return out
end

"""A recorded piece integrated against the response directly."""
function semi_direct(kern::SemiKernel, t::Float64, c::Float64, w::Float64, e::NTuple{4,Float64})
    u_lo = _ff_max(t - (c + w), kern.t0)
    u_hi = _ff_min(t - (c - w), kern.t_end)
    u_hi > u_lo || return 0.0
    k = piece_at(kern, u_lo)
    u = u_lo
    total = 0.0
    tl = kern.t
    while u < u_hi && k < kern.np
        nxt = _ff_min(u_hi, tl[k+2])
        if nxt > u
            t0 = tl[k+1]
            d = tl[k+2] - t0
            mid = 0.5 * (u + nxt)
            hw = 0.5 * (nxt - u)
            for g in 1:5
                uu = mid + GL5_X[g] * hw
                x = (uu - t0) / d
                h = _poly(kern, k, x)
                s = (t - uu - c) / w
                v = e[1] + s * (e[2] + s * (e[3] + s * e[4]))
                total += GL5_W[g] * hw * h * v
            end
        end
        u = nxt
        k += 1
    end
    return total
end

# --- the recorded inflow of one source -----------------------------------------------------------

"""The inflow of one source, recorded, and what it has put into the path (`Convolver`): blocks
oldest first -- centre, half-width, six moments scaled by the half-width, and for a block still one
recorded piece its cubic in s = (tau - c)/w."""
mutable struct Convolver
    ti::Vector{Int}                 # the targets' slots (from 0)
    tk::Vector{SemiKernel}          # and their responses
    bc::Vector{Float64}
    bw::Vector{Float64}
    bm::Vector{NTuple{6,Float64}}
    bp::Vector{Union{Nothing,NTuple{4,Float64}}}
    rt::Vector{Float64}
    rv::Vector{Float64}
    last_t::Float64
    imp_t::Vector{Float64}
    imp_a::Vector{Float64}
    compact_at::Int
    count::Int
end
Convolver(ti::Vector{Int}, tk::Vector{SemiKernel}) =
    Convolver(ti, tk, Float64[], Float64[], NTuple{6,Float64}[], Union{Nothing,NTuple{4,Float64}}[], Float64[], Float64[],
              -Inf, Float64[], Float64[], 64, 0)

function _ahead(cv::Convolver, u::Float64)
    m = Inf
    for kern in cv.tk
        u >= kern.t_end && continue
        d = u <= kern.t0 ? kern.ahead[1] : kern.ahead[piece_at(kern, u)+1]
        d < m && (m = d)
    end
    return m
end

function _reach(cv::Convolver)
    m = -Inf
    for kern in cv.tk
        kern.t_end > m && (m = kern.t_end)
    end
    return m
end

function impulse!(cv::Convolver, t::Float64, amount::Float64)
    (amount == 0 || !isfinite(amount)) && return nothing
    push!(cv.imp_t, t)
    push!(cv.imp_a, amount)
    return nothing
end

function push_record!(cv::Convolver, t::Float64, v::Float64)
    cv.count += 1
    if t == cv.last_t
        v == cv.rv[end] && return nothing
        cv.rt = [t]
        cv.rv = [v]
        return nothing
    end
    t < cv.last_t && error("a far-field path was told about an earlier instant after a later one")
    isempty(cv.rt) || _piece!(cv, t, v)
    push!(cv.rt, t)
    push!(cv.rv, v)
    if length(cv.rt) > 4
        popfirst!(cv.rt)
        popfirst!(cv.rv)
    end
    cv.last_t = t
    length(cv.bc) > cv.compact_at && compact!(cv, t)
    return nothing
end

function _piece!(cv::Convolver, t::Float64, v::Float64)
    nr = length(cv.rt)
    ta = cv.rt[nr]
    c = 0.5 * (ta + t)
    w = 0.5 * (t - ta)
    count = min(nr + 1, 4)
    ns = zeros(count)
    nv = zeros(count)
    for k in 0:count-2
        ns[k+1] = (cv.rt[nr-(count-1)+k+1] - c) / w
        nv[k+1] = cv.rv[nr-(count-1)+k+1]
    end
    ns[count] = 1.0
    nv[count] = v
    e = zeros(4)
    basis = zeros(5)
    for k in 0:count-1
        fill!(basis, 0.0)
        basis[1] = 1.0
        deg = 0
        den = 1.0
        for m in 0:count-1
            m == k && continue
            for q in deg+1:-1:1
                basis[q+1] = basis[q] - ns[m+1] * basis[q+1]
            end
            basis[1] = -ns[m+1] * basis[1]
            deg += 1
            den *= ns[k+1] - ns[m+1]
        end
        for q in 0:deg
            e[q+1] += nv[k+1] * basis[q+1] / den
        end
    end
    mu = zeros(6)
    for m in 0:5
        s = 0.0
        for q in 0:3
            (q + m) % 2 == 0 && (s += e[q+1] * 2 / (q + m + 1))
        end
        mu[m+1] = w * s
    end
    push!(cv.bc, c)
    push!(cv.bw, w)
    push!(cv.bm, (mu[1], mu[2], mu[3], mu[4], mu[5], mu[6]))
    push!(cv.bp, (e[1], e[2], e[3], e[4]))
    return nothing
end

function compact!(cv::Convolver, t_now::Float64)
    reach = _reach(cv)
    bc = Float64[]
    bw = Float64[]
    bm = NTuple{6,Float64}[]
    bp = Union{Nothing,NTuple{4,Float64}}[]
    for k in eachindex(cv.bc)
        c = cv.bc[k]
        w = cv.bw[k]
        t_now - (c + w) > reach && continue
        mu = cv.bm[k]
        p = cv.bp[k]
        if !isempty(bc)
            last = length(bc)
            lo = bc[last] - bw[last]
            hi = c + w
            width = hi - lo
            if width <= SEMI_RHO * _ahead(cv, t_now - hi)
                nc = 0.5 * (lo + hi)
                nw = 0.5 * width
                merged = semi_shift(bm[last], bc[last], bw[last], nc, nw)
                mine = semi_shift(mu, c, w, nc, nw)
                for m in 1:6
                    merged[m] += mine[m]
                end
                bc[last] = nc
                bw[last] = nw
                bm[last] = (merged[1], merged[2], merged[3], merged[4], merged[5], merged[6])
                bp[last] = nothing
                continue
            end
        end
        push!(bc, c)
        push!(bw, w)
        push!(bm, mu)
        push!(bp, p)
    end
    cv.bc, cv.bw, cv.bm, cv.bp = bc, bw, bm, bp
    cv.compact_at = 2 * length(bc) + 64
    return nothing
end

"""Scratch for the history sums."""
mutable struct SemiScratch
    v::Vector{Float64}
    wide::Vector{Int}
end
SemiScratch() = SemiScratch(Float64[], Int[])

"""`searchsorted(t, u, side='right') - 1`, clipped to [0, npc - 1] (numpy's NaN-last order)."""
@inline function _np_piece(t::Vector{Float64}, u::Float64, npc::Int)
    # the count of elements <= u (NaN sorts last)
    lo = 0
    hi = length(t)
    if isnan(u)
        lo = hi
    else
        while lo < hi
            mid = (lo + hi) >> 1
            if t[mid+1] <= u
                lo = mid + 1
            else
                hi = mid
            end
        end
    end
    k = lo - 1
    return k < 0 ? 0 : (k > npc - 1 ? npc - 1 : k)
end

"""What the recorded history releases at t, added into `out[i]` for each target."""
function history!(cv::Convolver, t::Float64, out::Vector{Float64}, scr::SemiScratch)
    isempty(cv.ti) && return nothing
    nb = length(cv.bc)
    for (ti, kern) in zip(cv.ti, cv.tk)
        npc = kern.np
        npc < 1 && continue
        total = 0.0
        if nb > 0
            # The blocks' moments against the response's pieces, summed as numpy sums them;
            # the wide single pieces directly, in order.
            v = scr.v
            length(v) < nb && resize!(v, nb)
            nv = 0
            wide = scr.wide
            empty!(wide)
            anykeep = false
            @inbounds for b in 1:nb
                uc = t - cv.bc[b]
                Wd = cv.bw[b]
                (uc + Wd > kern.t0) && (uc - Wd < kern.t_end) || continue
                anykeep = true
                if cv.bp[b] !== nothing
                    young = uc - Wd
                    ka = _np_piece(kern.t, young, npc)
                    sp = young <= kern.t0 ? kern.ahead[1] : kern.ahead[ka+1]
                    if 2 * Wd > SEMI_RHO * sp
                        push!(wide, b)
                        continue
                    end
                end
                k = _np_piece(kern.t, uc, npc)
                nv += 1
                v[nv] = _from_moment(kern, k, uc, Wd, cv.bm[b])
            end
            if anykeep
                nv > 0 && (total += np_sum(v, nv))
                for b in wide
                    total += semi_direct(kern, t, cv.bc[b], cv.bw[b], cv.bp[b]::NTuple{4,Float64})
                end
            end
        end
        for r in eachindex(cv.imp_t)
            total += cv.imp_a[r] * kernel_at(kern, t - cv.imp_t[r])
        end
        out[ti+1] += total
    end
    return nothing
end

"""One block by its moments against piece k of the response (`fromMoments`)."""
@inline function _from_moment(kern::SemiKernel, k::Int, uc::Float64, w::Float64, mu::NTuple{6,Float64})
    t0 = kern.t[k+1]
    d = kern.d[k+1]
    x = (uc - t0) / d
    a = kern.a
    b0 = a[1, k+1]; b1 = a[2, k+1]; b2 = a[3, k+1]; b3 = a[4, k+1]; b4 = a[5, k+1]; b5 = a[6, k+1]
    c5 = b5
    c4 = b4 + x * c5
    c3 = b3 + x * c4
    c2 = b2 + x * c3
    c1 = b1 + x * c2
    t0c = b0 + x * c1
    c4 = c4 + x * c5
    c3 = c3 + x * c4
    c2 = c2 + x * c3
    t1c = c1 + x * c2
    c4 = c4 + x * c5
    c3 = c3 + x * c4
    t2c = c2 + x * c3
    c4 = c4 + x * c5
    t3c = c3 + x * c4
    t4c = c4 + x * c5
    t5c = c5
    r = -w / d
    return t0c * mu[1] + r * (t1c * mu[2] + r * (t2c * mu[3] + r * (t3c * mu[4] + r * (t4c * mu[5] + r * t5c * mu[6]))))
end

"""The step from a source's last record to t (or a point mass inside it), for one target: the
weights of the cubic's nodes."""
struct SemiPart
    i::Int
    w::Vector{Float64}
    count::Int
    nr::Int
    slot::Int
end

"""The step from a source's last record to t, for each target (`stepWeights`)."""
function step_weights!(out::Vector{SemiPart}, cv::Convolver, t::Float64, slot::Int)
    nr = length(cv.rt)
    D = t - cv.last_t
    (isempty(cv.ti) || nr == 0 || !(D > 0)) && return out
    count = min(nr + 1, 4)
    s = zeros(count)
    for k in 0:count-2
        s[k+1] = t - cv.rt[nr-(count-1)+k+1]
    end
    s[count] = 0.0
    coef = nothing
    for (ti, kern) in zip(cv.ti, cv.tk)
        D > kern.t0 || continue
        coef === nothing && (coef = lag_basis(s, count, D))
        mom = running_moments(kern, D)
        m1 = mom[1]
        Dq = D
        m2 = mom[2] / Dq
        Dq *= D
        m3 = mom[3] / Dq
        Dq *= D
        m4 = mom[4] / Dq
        mm = (m1, m2, m3, m4)
        w = zeros(count)
        for k in 1:count
            v = 0.0
            for q in 1:count
                v += coef[k][q] * mm[q]
            end
            w[k] = v
        end
        push!(out, SemiPart(ti, w, count, nr, slot))
    end
    return out
end

"""The point masses whose lag puts them inside the step being taken (`pointParts`)."""
function point_parts!(out::Vector{SemiPart}, cv::Convolver, t::Float64, slot::Int)
    nr = length(cv.rt)
    nr == 0 && return out
    for (ti, kern) in zip(cv.ti, cv.tk)
        kern.m0 > 0 || continue
        tau = t - kern.tm0
        tau > cv.last_t || continue
        count = min(nr + 1, 4)
        nodes = zeros(count)
        for k in 0:count-2
            nodes[k+1] = cv.rt[nr-(count-1)+k+1]
        end
        nodes[count] = t
        w = zeros(count)
        for k in 1:count
            lk = 1.0
            for m in 1:count
                m != k && (lk *= (tau - nodes[m]) / (nodes[k] - nodes[m]))
            end
            w[k] = kern.m0 * lk
        end
        push!(out, SemiPart(ti, w, count, nr, slot))
    end
    return out
end

"""The step's contribution: its node weights against the records and the current inflow `v`."""
function step_sum(cv::Convolver, part::SemiPart, v::Float64)
    w, count, nr = part.w, part.count, part.nr
    r = w[count] * v
    for k in 0:count-2
        r += w[k+1] * cv.rv[nr-(count-1)+k+1]
    end
    return r
end

# --- the path ------------------------------------------------------------------------------------

"""The unit responses of one combination: a kernel per pair (i, j) that has one, row-major."""
struct SemiCombo
    kernels::Vector{Union{Nothing,SemiKernel}}
    pairs::Int
    misses::Vector{NamedTuple{(:i, :j, :integral, :expected, :T0, :rel, :until),
                              Tuple{Int,Int,Float64,Float64,Float64,Float64,Float64}}}
end

"""Unit responses by settings, shared by every path and every run in this process (32 kept)."""
const SEMI_RESPONSES = OrderedDict{Any,SemiCombo}()
const SEMI_RESPONSES_KEEP = 32
const SEMI_RESPONSES_LOCK = ReentrantLock()

"""Forgets every response kept (`clearResponses`)."""
clear_semi_responses!() = lock(() -> empty!(SEMI_RESPONSES), SEMI_RESPONSES_LOCK)

"""One far-field block worked out semi-analytically (`LaplaceFarfPath`)."""
mutable struct LaplaceFarfPath
    base::Int
    nnuc::Int
    other_width::Int
    dim_off::Vector{Int}
    single_off::Vector{Int}
    setting_base::Dict{String,Int}
    keys::Vector{String}
    is_single::Set{String}
    surface::String
    release_base::Int
    span::Float64
    names::Union{Nothing,Vector{String}}
    block_name::String
    slots::Int
    release_slots::Vector{Int}       # 0-based X slots
    release_at::Vector{Int}          # 1-based
    held_idx::Vector{Int}            # 0-based states
    cell_starts::Vector{Int}
    D::Union{Nothing,LPDecay}
    in_tgt::Vector{Int}
    in_rate::Vector{Int}
    in_donor::Vector{Int}
    terms_into::Vector{Vector{Tuple{Int,Int}}}
    IN::Vector{Float64}
    held::Vector{Float64}
    last_held::Vector{Float64}
    rec_t::Vector{Float64}                    # the records' times, every slot's alike
    rec_v::Vector{Vector{Float64}}
    imp_t::Vector{Vector{Float64}}
    imp_v::Vector{Vector{Float64}}
    combos::Vector{Union{Nothing,SemiCombo}}
    live::Union{Nothing,Vector{Convolver}}
    sweep::Union{Nothing,Vector{Convolver}}
    sweep_at::Float64
    sweep_next::Int
    sweep_imp::Vector{Int}
    releases::Dict{Float64,Vector{Float64}}
    last_t::Float64
    hist_t::Float64
    hist_vals::Vector{Float64}
    weight_t::Float64
    cur::Vector{Float64}
    parts::Vector{SemiPart}
    weighed::Bool
    ready::Bool
    scratch::SemiScratch
    res::Vector{Float64}
end

function LaplaceFarfPath(base::Int, nnuc::Int, other_width::Int, dim_off::Vector{Int}, single_off::Vector{Int},
                         setting_base::Dict{String,Int}, keys::Vector{String}, single, surface::AbstractString,
                         release_base::Int, span::Float64, names, block_name::AbstractString)
    slots = other_width * nnuc
    release_slots = release_base .+ dim_off
    return LaplaceFarfPath(base, nnuc, other_width, dim_off, single_off, copy(setting_base), keys, Set{String}(single),
                           isempty(surface) ? "f" : String(surface), release_base, span,
                           names === nothing ? nothing : String[x for x in names], String(block_name), slots,
                           release_slots, release_slots .+ 1, base .+ collect(0:slots-1),
                           base .+ collect(0:other_width-1) .* nnuc, nothing, Int[], Int[], Int[],
                           [Tuple{Int,Int}[] for _ in 1:slots], zeros(slots), zeros(slots), zeros(slots), Float64[],
                           [Float64[] for _ in 1:slots], [Float64[] for _ in 1:slots], [Float64[] for _ in 1:slots],
                           Union{Nothing,SemiCombo}[nothing for _ in 1:other_width], nothing, nothing, -Inf, 0,
                           zeros(Int, slots), Dict{Float64,Vector{Float64}}(), -Inf, NaN, zeros(slots), NaN,
                           zeros(slots * nnuc), SemiPart[], false, false, SemiScratch(), zeros(slots))
end

@inline _tkey(t::Float64) = t == 0.0 ? 0.0 : t      # Python's dict: -0.0 and 0.0 are one key

"""The decay table the path's nuclides decay with (the builder's), or none."""
function farfield_set_decay!(F::LaplaceFarfPath, dec)
    F.D = dec === nothing ? nothing :
          LPDecay(Float64[x for x in dec.lam], Int[x for x in dec.ioff], Int[x for x in dec.icnt], Int[x for x in dec.ipar],
                  Float64[x for x in dec.icoef])
    farfield_restart!(F)
end

"""What the model's fluxes deliver into each slot: `IN[tgt] += X[rate]` times `y[donor]` where the
donor is not -1 (all 0-based)."""
function farfield_set_inflow!(F::LaplaceFarfPath, tgt, rate, donor)
    F.in_tgt = collect(Int, tgt)
    F.in_rate = collect(Int, rate)
    F.in_donor = collect(Int, donor)
    F.terms_into = [Tuple{Int,Int}[] for _ in 1:F.slots]
    for (q, x, d) in zip(F.in_tgt, F.in_rate, F.in_donor)
        push!(F.terms_into[q+1], (x, d))
    end
    return nothing
end

"""Starts a run: responses from the settings at its first instant, an empty history."""
function farfield_restart!(F::LaplaceFarfPath)
    F.ready = false
    F.live = nothing
    F.sweep = nothing
    F.sweep_at = -Inf
    F.releases = Dict{Float64,Vector{Float64}}()
    F.last_t = -Inf
    F.hist_t = NaN
    F.weight_t = NaN
    F.weighed = false
    empty!(F.rec_t)
    for s in 1:F.slots
        empty!(F.rec_v[s])
        empty!(F.imp_t[s])
        empty!(F.imp_v[s])
    end
    return nothing
end

function _setting_at(F::LaplaceFarfPath, key::String, o::Int, off::Int)
    one = isempty(F.single_off) ? 0 : F.single_off[o+1]
    return F.setting_base[key] + (key in F.is_single ? one : off)
end

function _settings_of(F::LaplaceFarfPath, X::Vector{Float64}, o::Int)
    n = F.nnuc
    single = Dict{String,Float64}()
    each = Dict{String,Vector{Float64}}()
    for key in F.keys
        if key in F.is_single
            single[key] = X[_setting_at(F, key, o, F.dim_off[o*n+1])+1]
        else
            each[key] = Float64[X[_setting_at(F, key, o, F.dim_off[o*n+m+1])+1] for m in 0:n-1]
        end
    end
    return LPSettings(F.surface, single, each)
end

function _response_key(s::LPSettings, D::Union{Nothing,LPDecay}, span::Float64, nnuc::Int)
    parts = Any[span, nnuc, s.surface]
    for key in sort!(collect(Base.keys(s.single)))
        push!(parts, key, s.single[key])
    end
    for key in sort!(collect(Base.keys(s.each)))
        push!(parts, key, Tuple(s.each[key]))
    end
    if D !== nothing
        push!(parts, Tuple(D.lam), Tuple(D.ioff), Tuple(D.icnt), Tuple(D.ipar), Tuple(D.icoef))
    end
    return Tuple(parts)
end

"""The unit responses of every combination, from the settings in X; `FarfError` with the reason for
what the method cannot solve."""
function laplace_prepare!(F::LaplaceFarfPath, X::Vector{Float64})
    for o in 0:F.other_width-1
        settings = _settings_of(F, X, o)
        key = _response_key(settings, F.D, F.span, F.nnuc)
        combo = lock(SEMI_RESPONSES_LOCK) do
            c = get(SEMI_RESPONSES, key, nothing)
            if c !== nothing
                delete!(SEMI_RESPONSES, key)            # to the end: the most recently used
                SEMI_RESPONSES[key] = c
            end
            c
        end
        if combo === nothing
            combo = _semi_responses(F, settings)
            lock(SEMI_RESPONSES_LOCK) do
                SEMI_RESPONSES[key] = combo
                while length(SEMI_RESPONSES) > SEMI_RESPONSES_KEEP
                    delete!(SEMI_RESPONSES, first(Base.keys(SEMI_RESPONSES)))
                end
            end
        end
        F.combos[o+1] = combo
    end
    F.ready = true
    F.live = _convolvers(F)
    return nothing
end

function _semi_responses(F::LaplaceFarfPath, settings::LPSettings)
    path = try
        prepare_path(settings, F.D, F.nnuc, F.names)
    catch e
        e isa LaplacePathError || rethrow()
        throw(FarfError(e.message))
    end
    n = F.nnuc
    T0 = transfer_at_zero(path)
    kernels = Union{Nothing,SemiKernel}[nothing for _ in 1:n*n]
    misses = NamedTuple{(:i, :j, :integral, :expected, :T0, :rel, :until),
                        Tuple{Int,Int,Float64,Float64,Float64,Float64,Float64}}[]
    pairs = 0
    for j in 0:n-1
        most = 0.0
        for i in 0:n-1
            T0[i*n+j+1] > most && (most = T0[i*n+j+1])
        end
        for i in 0:n-1
            _reaches(path, j, i) || continue
            T = T0[i*n+j+1]
            (!(T > SEMI_NEGLIGIBLE * most) || !(T > 1e-300)) && continue
            r = unit_response(path, i, j, F.span)
            if r.checked && !r.balanced
                push!(misses, (i=i, j=j, integral=r.integral, expected=r.expected, T0=r.T0, rel=r.rel,
                               until=isempty(r.t) ? NaN : r.t[end]))
            end
            length(r.t) < 2 && continue
            kernels[i*n+j+1] = SemiKernel(r)
            pairs += 1
        end
    end
    return SemiCombo(kernels, pairs, misses)
end

"""Every unit response that missed its mass balance (`balanceWarnings`): never a quiet shortfall."""
function laplace_balance_warnings(F::LaplaceFarfPath)
    out = JDict[]
    p4(x) = _js_precision4(x)
    name(k) = F.names !== nothing ? F.names[k+1] : "#$(k + 1)"
    for (o, combo) in enumerate(F.combos)
        combo === nothing && continue
        for m in combo.misses
            where_ = F.other_width > 1 ? " (index combination $o of $(F.other_width))" : ""
            push!(out, JDict("block" => F.block_name,
                             "message" => "the unit response of $(name(m.i)) to $(name(m.j))$where_ integrates to " *
                                          "$(p4(m.integral)), but $(p4(m.expected)) of a pulse leaves the path by " *
                                          "$(p4(m.until)) (T(0) = $(p4(m.T0))): the inversion failed there, and the " *
                                          "release worked out from it is not reliable"))
        end
    end
    return out
end

"""`Number(x).toPrecision(4)` as the Python engine writes it for these warnings (`_js_precision`)."""
function _js_precision4(x::Float64)
    isnan(x) && return "NaN"
    isinf(x) && return x > 0 ? "Infinity" : "-Infinity"
    x == 0 && return "0.000"
    s = @sprintf("%.3e", x)
    mant, ex = split(s, 'e')
    e = parse(Int, ex)
    (e < -6 || e >= 4) && return "$(mant)e$(e >= 0 ? "+" : "-")$(abs(e))"
    return @sprintf("%.*f", max(0, 3 - e), x)
end

function _convolvers(F::LaplaceFarfPath)
    n = F.nnuc
    out = Convolver[]
    for o in 0:F.other_width-1
        kernels = F.combos[o+1].kernels
        for j in 0:n-1
            ti = Int[]
            tk = SemiKernel[]
            for i in 0:n-1
                k = kernels[i*n+j+1]
                k === nothing && continue
                push!(ti, o * n + i)
                push!(tk, k)
            end
            push!(out, Convolver(ti, tk))
        end
    end
    return out
end

"""What the model's fluxes deliver into every slot at (y, X), in `F.IN` (`np.add.at`: in order)."""
function _inflow!(F::LaplaceFarfPath, y::Vector{Float64}, X::Vector{Float64})
    IN = F.IN
    fill!(IN, 0.0)
    @inbounds for q in eachindex(F.in_tgt)
        d = F.in_donor[q]
        IN[F.in_tgt[q]+1] += (d >= 0 ? y[d+1] : 1.0) * X[F.in_rate[q]+1]
    end
    return IN
end

function _weights!(F::LaplaceFarfPath, t::Float64)
    (t == F.weight_t && F.weighed) && return nothing
    n = F.nnuc
    fill!(F.cur, 0.0)
    empty!(F.parts)
    if F.live !== nothing && t > F.last_t
        live = F.live::Vector{Convolver}
        for slot in 0:F.slots-1
            start = length(F.parts) + 1
            step_weights!(F.parts, live[slot+1], t, slot)
            point_parts!(F.parts, live[slot+1], t, slot)
            for q in start:length(F.parts)
                part = F.parts[q]
                F.cur[part.i*n+(slot%n)+1] += part.w[part.count]
            end
        end
    end
    F.weighed = true
    F.weight_t = t
    return nothing
end

"""The weight of each source's current inflow in each target's release at t: `cur[slot * n + j]`."""
function laplace_current_weights(F::LaplaceFarfPath, t::Float64)
    _weights!(F, t)
    return F.cur
end

"""The release of every slot at t, into its algebraic slots."""
function farfield_release!(F::LaplaceFarfPath, y::Vector{Float64}, X::Vector{Float64}, t::Float64=NaN)
    F.ready || laplace_prepare!(F, X)
    t = Float64(t)
    kept = get(F.releases, _tkey(t), nothing)
    if kept !== nothing
        @inbounds for s in 1:F.slots
            X[F.release_at[s]] = kept[s]
        end
        return nothing
    end
    last_recorded = isempty(F.rec_t) ? -Inf : F.rec_t[end]
    if t < last_recorded || (!isempty(F.rec_t) && F.last_t == -Inf)
        _behind!(F, y, X, t)
        return nothing
    end
    hist = F.hist_vals
    if !(t == F.hist_t)
        fill!(hist, 0.0)
        if F.live !== nothing
            live = F.live::Vector{Convolver}
            for slot in 0:F.slots-1
                history!(live[slot+1], t, hist, F.scratch)
                _points_behind!(F, live[slot+1], slot, t, hist)
            end
        end
        F.hist_t = t
    end
    IN = _inflow!(F, y, X)
    _weights!(F, t)
    res = F.res
    copyto!(res, hist)
    if !isempty(F.parts)
        live = F.live::Vector{Convolver}
        for part in F.parts
            res[part.i+1] += step_sum(live[part.slot+1], part, IN[part.slot+1])
        end
    end
    @inbounds for s in 1:F.slots
        X[F.release_at[s]] = res[s]
    end
    return nothing
end

"""The release at an earlier instant than the last record: swept forward from the records again."""
function _behind!(F::LaplaceFarfPath, y::Vector{Float64}, X::Vector{Float64}, t::Float64)
    if F.sweep === nothing || t < F.sweep_at
        F.sweep = _convolvers(F)
        F.sweep_at = -Inf
        F.sweep_next = 0
        fill!(F.sweep_imp, 0)
    end
    sweep = F.sweep::Vector{Convolver}
    times = F.rec_t
    while F.sweep_next < length(times) && times[F.sweep_next+1] <= t
        q = F.sweep_next
        F.sweep_next += 1
        for slot in 1:F.slots
            push_record!(sweep[slot], times[q+1], F.rec_v[slot][q+1])
        end
    end
    for slot in 1:F.slots
        it = F.imp_t[slot]
        cv = sweep[slot]
        while F.sweep_imp[slot] < length(it) && it[F.sweep_imp[slot]+1] <= t
            q = F.sweep_imp[slot]
            F.sweep_imp[slot] += 1
            impulse!(cv, it[q+1], F.imp_v[slot][q+1])
        end
    end
    F.sweep_at = t
    out = zeros(F.slots)
    for slot in 0:F.slots-1
        history!(sweep[slot+1], t, out, F.scratch)
        _points_behind!(F, sweep[slot+1], slot, t, out)
    end
    IN = _inflow!(F, y, X)
    parts = SemiPart[]
    for slot in 0:F.slots-1
        cv = sweep[slot+1]
        empty!(parts)
        step_weights!(parts, cv, t, slot)
        point_parts!(parts, cv, t, slot)
        for part in parts
            out[part.i+1] += step_sum(cv, part, IN[slot+1])
        end
    end
    @inbounds for s in 1:F.slots
        X[F.release_at[s]] = out[s]
    end
    return nothing
end

"""The point masses whose lag reaches back into the recorded history."""
function _points_behind!(F::LaplaceFarfPath, cv::Convolver, slot::Int, t::Float64, out::Vector{Float64})
    for (ti, kern) in zip(cv.ti, cv.tk)
        kern.m0 > 0 || continue
        tau = t - kern.tm0
        tau > cv.last_t && continue
        out[ti+1] += kern.m0 * _recorded_inflow(F, slot, tau)
    end
    return nothing
end

"""What flowed into `slot` at the earlier instant tau: the cubic the history holds there."""
function _recorded_inflow(F::LaplaceFarfPath, slot::Int, tau::Float64)
    T = F.rec_t
    V = F.rec_v[slot+1]
    n = length(T)
    (n == 0 || !(tau >= T[1])) && return 0.0
    tau >= T[n] && return V[n]
    lo = 0
    hi = n - 1
    while hi - lo > 1
        c = (lo + hi) >> 1
        if T[c+1] <= tau
            lo = c
        else
            hi = c
        end
    end
    b = lo + 1
    first = b
    while first > 0 && b - first < 3 && T[first] < T[first+1]
        first -= 1
    end
    v = 0.0
    for k in first:b
        lk = 1.0
        for m in first:b
            m != k && (lk *= (tau - T[m+1]) / (T[k+1] - T[m+1]))
        end
        v += lk * V[k+1]
    end
    return v
end

"""Puts the history back to the start of a run and records its first instant."""
function farfield_prime!(F::LaplaceFarfPath, t0::Float64, y0::Vector{Float64}, X::Vector{Float64})
    F.ready || laplace_prepare!(F, X)
    empty!(F.rec_t)
    for s in 1:F.slots
        empty!(F.rec_v[s])
        empty!(F.imp_t[s])
        empty!(F.imp_v[s])
    end
    F.live = _convolvers(F)
    F.sweep = nothing
    F.releases = Dict{Float64,Vector{Float64}}()
    F.last_t = -Inf
    F.hist_t = NaN
    F.weight_t = NaN
    F.weighed = false
    farfield_store!(F, t0, y0, X)
end

"""Records an instant the solver has told the model about."""
function farfield_store!(F::LaplaceFarfPath, t::Float64, y::Vector{Float64}, X::Vector{Float64})
    F.ready || laplace_prepare!(F, X)
    F.live === nothing && (F.live = _convolvers(F))
    live = F.live::Vector{Convolver}
    t = Float64(t)
    t < F.last_t && _truncate!(F, t)
    live = F.live::Vector{Convolver}
    IN = _inflow!(F, y, X)
    held = F.held
    @inbounds for s in 1:F.slots
        held[s] = y[F.held_idx[s]+1]
    end
    same = t == F.last_t
    record = !same
    if same
        for slot in 1:F.slots
            amount = held[slot] - F.last_held[slot]
            if amount != 0
                impulse!(live[slot], t, amount)
                push!(F.imp_t[slot], t)
                push!(F.imp_v[slot], amount)
            end
            IN[slot] != F.rec_v[slot][end] && (record = true)
        end
    end
    if record
        push!(F.rec_t, t)
        for slot in 1:F.slots
            v = IN[slot]
            push!(F.rec_v[slot], v)
            push_record!(live[slot], t, v)
        end
    end
    key = _tkey(t)
    haskey(F.releases, key) || (F.releases[key] = Float64[X[F.release_at[s]] for s in 1:F.slots])
    copyto!(F.last_held, held)
    F.last_t = t
    F.hist_t = NaN
    F.weight_t = NaN
    F.weighed = false
    return nothing
end

"""Forgets everything recorded after t."""
function _truncate!(F::LaplaceFarfPath, t::Float64)
    k = length(F.rec_t)
    while k > 0 && F.rec_t[k] > t
        k -= 1
    end
    resize!(F.rec_t, k)
    for slot in 1:F.slots
        resize!(F.rec_v[slot], k)
        it = F.imp_t[slot]
        ki = length(it)
        while ki > 0 && it[ki] > t
            ki -= 1
        end
        resize!(it, ki)
        resize!(F.imp_v[slot], ki)
    end
    for key in [x for x in Base.keys(F.releases) if x > t]
        delete!(F.releases, key)
    end
    F.live = _convolvers(F)
    live = F.live::Vector{Convolver}
    for q in eachindex(F.rec_t)
        for slot in 1:F.slots
            push_record!(live[slot], F.rec_t[q], F.rec_v[slot][q])
        end
    end
    for slot in 1:F.slots
        for q in eachindex(F.imp_t[slot])
            impulse!(live[slot], F.imp_t[slot][q], F.imp_v[slot][q])
        end
    end
    F.last_t = isempty(F.rec_t) ? -Inf : F.rec_t[end]
    return nothing
end

"""What a run leaves on the path that reading its results depends on."""
laplace_run_state(F::LaplaceFarfPath) =
    (rec_t=copy(F.rec_t), rec_v=[copy(v) for v in F.rec_v], imp_t=[copy(v) for v in F.imp_t],
     imp_v=[copy(v) for v in F.imp_v], releases=Dict(k => copy(v) for (k, v) in F.releases))

"""A run's history (from `laplace_run_state`) back on the path: the results are read from it as
from the run's own."""
function laplace_restore_run_state!(F::LaplaceFarfPath, state)
    F.rec_t = copy(state.rec_t)
    F.rec_v = [copy(v) for v in state.rec_v]
    F.imp_t = [copy(v) for v in state.imp_t]
    F.imp_v = [copy(v) for v in state.imp_v]
    F.releases = Dict(k => copy(v) for (k, v) in state.releases)
    F.sweep = nothing
    F.sweep_at = -Inf
    F.last_t = -Inf
    F.live = nothing
    F.hist_t = NaN
    F.weight_t = NaN
    F.weighed = false
    return nothing
end

"""For each release slot, the states it depends on: what the inflow into the same combination
reads, since the step being taken carries it with a weight (`releasePattern`)."""
function farfield_release_dependencies(F::LaplaceFarfPath, of_x)
    n = F.nnuc
    per_o = Vector{Int}[]
    for o in 0:F.other_width-1
        parts = Int[]
        for j in 0:n-1
            for (x, d) in F.terms_into[o*n+j+1]
                d >= 0 && push!(parts, d)
                append!(parts, of_x(x))
            end
        end
        push!(per_o, sort!(unique(parts)))
    end
    return [per_o[div(slot, n)+1] for slot in 0:F.slots-1]
end

"""The release of a semi-analytical path along the state (`releaseTangent`): the weight of each
source's current inflow times that inflow's gradient."""
function farfield_laplace_gradient!(an, F::LaplaceFarfPath, G::Vector{Float64}, y::Vector{Float64}, X::Vector{Float64},
                                    t::Float64)
    cur = laplace_current_weights(F, t)
    any(!=(0.0), cur) || return nothing
    n = F.nnuc
    moving = an.sys.builder.slot_class
    for slot in 0:F.slots-1
        out = F.release_slots[slot+1]
        haskey(an.g_row_of, out) || continue
        r_out = an.g_row_of[out]
        row_cols = an.g_cols[r_out]
        isempty(row_cols) && continue
        acc = zeros(length(row_cols))
        o = div(slot, n)
        for j in 0:n-1
            w = cur[slot*n+j+1]
            w == 0 && continue
            for (x, d) in F.terms_into[o*n+j+1]
                scale = w
                if d >= 0
                    acc[searchsortedfirst(row_cols, d)] += w * X[x+1]
                    scale = w * y[d+1]
                end
                if haskey(an.g_row_of, x) && moving[x+1] == 2
                    r = an.g_row_of[x]
                    cols = an.g_cols[r]
                    if !isempty(cols)
                        lo = an.g_ptr[r]
                        for (q, c) in enumerate(cols)
                            acc[searchsortedfirst(row_cols, c)] += scale * G[lo+q-1]
                        end
                    end
                end
            end
        end
        lo = an.g_ptr[r_out]
        for q in eachindex(acc)
            G[lo+q-1] += acc[q]
        end
    end
    return nothing
end

farfield_is_laplace(::LaplaceFarfPath) = true
farfield_slots(F::LaplaceFarfPath) = F.slots
farfield_release_slots(F::LaplaceFarfPath) = F.release_slots
farfield_held_idx(F::LaplaceFarfPath) = F.held_idx
farfield_cell_starts(F::LaplaceFarfPath) = F.cell_starts
farfield_row_col(F::LaplaceFarfPath) = (Int[], Int[])
farfield_refresh!(F::LaplaceFarfPath, X) = nothing
farfield_values(F::LaplaceFarfPath) = Float64[]
farfield_rel_idx(F::LaplaceFarfPath) = [Int[] for _ in 1:F.slots]
farfield_release_weights(F::LaplaceFarfPath) = zeros(0, F.slots)
function farfield_setting_slots(F::LaplaceFarfPath)
    out = zeros(Int, F.slots, length(F.keys))
    for o in 0:F.other_width-1, m in 0:F.nnuc-1
        slot = o * F.nnuc + m
        for (k, key) in enumerate(F.keys)
            out[slot+1, k] = _setting_at(F, key, o, F.dim_off[slot+1])
        end
    end
    return out
end

"""A copy for another thread: the settings, the index vectors and the responses (which never change)
shared; the history, the caches and the scratch its own."""
function farfield_clone(F::LaplaceFarfPath)
    C = LaplaceFarfPath(F.base, F.nnuc, F.other_width, F.dim_off, F.single_off, F.setting_base, F.keys, F.is_single,
                        F.surface, F.release_base, F.span, F.names, F.block_name, F.slots, F.release_slots,
                        F.release_at, F.held_idx, F.cell_starts, F.D, F.in_tgt, F.in_rate, F.in_donor, F.terms_into,
                        zeros(F.slots), zeros(F.slots), copy(F.last_held), copy(F.rec_t), [copy(v) for v in F.rec_v],
                        [copy(v) for v in F.imp_t], [copy(v) for v in F.imp_v], copy(F.combos), nothing, nothing, -Inf,
                        0, zeros(Int, F.slots), Dict(k => copy(v) for (k, v) in F.releases), F.last_t, NaN,
                        zeros(F.slots), NaN, zeros(length(F.cur)), SemiPart[], false, F.ready, SemiScratch(),
                        zeros(F.slots))
    if F.ready
        # the live convolvers, rebuilt from the records as `_truncate!` rebuilds them
        C.live = _convolvers(C)
        live = C.live::Vector{Convolver}
        for q in eachindex(C.rec_t), slot in 1:C.slots
            push_record!(live[slot], C.rec_t[q], C.rec_v[slot][q])
        end
        for slot in 1:C.slots, q in eachindex(C.imp_t[slot])
            impulse!(live[slot], C.imp_t[slot][q], C.imp_v[slot][q])
        end
    end
    return C
end
