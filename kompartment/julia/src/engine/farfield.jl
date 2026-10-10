# The far-field pathway (FARFCOMP) at run time: a dual-porosity transport
# model behind one block (kompartment/engine/farfield.py, which ports
# src/domain/farfield.js and `FarfPath` in src/sim/farfield.js).
#
# A path on cells has, for every nuclide and every index of its other
# dimensions, a fracture of n_f (+ n_b) cells and n_m matrix layers behind
# each; its rates are worked out from its setting slots whenever they move
# (`refresh!`), on matched layers laid out once per run or on the reference
# implementation's layers, and its release is read off its last cells. A path
# worked out semi-analytically (farfield_semi.jl, on the transfer functions of
# farfield_laplace.jl) has one state per nuclide, for what it holds.
#
# The arithmetic is the Python engine's operation for operation -- numpy's
# and CPython's where those differ from Julia's (`math.hypot`, `np.sum`,
# `np.spacing`, builtin `min`/`max`, `float ** int`) -- so that a run is the
# Python engine's to the last bit. The builder keeps the application's
# 0-based offsets; arrays here are 1-based.

# --- arithmetic as Python and numpy have it ------------------------------------------------

"""Python's builtin `max(a, b)`: the first unless the second is greater (NaN and ties keep `a`)."""
@inline _ff_max(a, b) = b > a ? b : a
"""Python's builtin `min(a, b)`: the first unless the second is less."""
@inline _ff_min(a, b) = b < a ? b : a

"""numpy's `spacing`: the distance to the next double away from zero, signed like x; either zero gives the least positive double."""
@inline function np_spacing(x::Float64)
    x == 0.0 && return 5.0e-324
    (isnan(x) || isinf(x)) && return NaN
    return (x > 0 ? nextfloat(x) : prevfloat(x)) - x
end

"""numpy's `sign` of a float: 1, -1, 0 for either zero, NaN for NaN."""
@inline np_sign(x::Float64) = x > 0 ? 1.0 : x < 0 ? -1.0 : x == 0 ? 0.0 : NaN

"""CPython's `math.hypot(x, y)` (`vector_norm`: lossless scaling, error-free squares, compensated
sums and a differential correction of the root), not the C library's `hypot`."""
function py_hypot(x::Float64, y::Float64)
    ax = abs(x)
    ay = abs(y)
    found_nan = isnan(ax) | isnan(ay)
    mx = 0.0
    ax > mx && (mx = ax)
    ay > mx && (mx = ay)
    return _vector_norm2(ax, ay, mx, found_nan)
end

function _vector_norm2(ax::Float64, ay::Float64, mx::Float64, found_nan::Bool)
    isinf(mx) && return mx
    found_nan && return NaN
    mx == 0.0 && return mx
    max_e = exponent(mx) + 1                       # frexp's exponent
    if max_e < -1023
        dmin = floatmin(Float64)
        return dmin * _vector_norm2(ax / dmin, ay / dmin, mx / dmin, found_nan)
    end
    scale = ldexp(1.0, -max_e)
    csum = 1.0
    frac1 = 0.0
    frac2 = 0.0
    x = ax * scale
    hi = x * x
    lo = fma(x, x, -hi)
    s = csum + hi
    frac2 += (csum - s) + hi
    csum = s
    frac1 += lo
    x = ay * scale
    hi = x * x
    lo = fma(x, x, -hi)
    s = csum + hi
    frac2 += (csum - s) + hi
    csum = s
    frac1 += lo
    h = sqrt(csum - 1.0 + (frac1 + frac2))
    hi = -h * h
    lo = fma(-h, h, -hi)
    s = csum + hi
    frac2 += (csum - s) + hi
    csum = s
    frac1 += lo
    x = csum - 1.0 + (frac1 + frac2)
    h += x / (2.0 * h)
    return h / scale
end

"""numpy's pairwise summation of `v[lo:lo+n-1]` (`pairwise_sum_DOUBLE`: blocks of 8 accumulators
up to 128 terms, halves above)."""
function np_pairwise(v::AbstractVector{Float64}, lo::Int, n::Int)
    if n < 8
        res = 0.0
        @inbounds for i in 0:n-1
            res += v[lo+i]
        end
        return res
    elseif n <= 128
        @inbounds begin
            r1 = v[lo]; r2 = v[lo+1]; r3 = v[lo+2]; r4 = v[lo+3]
            r5 = v[lo+4]; r6 = v[lo+5]; r7 = v[lo+6]; r8 = v[lo+7]
            i = 8
            stop = n - (n % 8)
            while i < stop
                r1 += v[lo+i]; r2 += v[lo+i+1]; r3 += v[lo+i+2]; r4 += v[lo+i+3]
                r5 += v[lo+i+4]; r6 += v[lo+i+5]; r7 += v[lo+i+6]; r8 += v[lo+i+7]
                i += 8
            end
            res = ((r1 + r2) + (r3 + r4)) + ((r5 + r6) + (r7 + r8))
            while i < n
                res += v[lo+i]
                i += 1
            end
        end
        return res
    end
    n2 = div(n, 2)
    n2 -= n2 % 8
    return np_pairwise(v, lo, n2) + np_pairwise(v, lo + n2, n - n2)
end

"""`np.sum` of the first `n` values of a 1-D float array: the reduction's initial 0.0 plus the pairwise sum."""
np_sum(v::AbstractVector{Float64}, n::Int=length(v)) = 0.0 + np_pairwise(v, 1, n)

"""CPython's `float ** float` for finite results: its special cases, then libm's `pow` of the
magnitude with the sign put back; an overflow (Python's OverflowError) is infinite."""
function py_pow(iv::Float64, iw::Float64)
    iw == 0.0 && return 1.0
    isnan(iv) && return iv
    isnan(iw) && return iv == 1.0 ? 1.0 : iw
    if isinf(iw)
        iv = abs(iv)
        iv == 1.0 && return 1.0
        return (iw > 0.0) == (iv > 1.0) ? abs(iw) : 0.0
    end
    odd = rem(abs(iw), 2.0) == 1.0                  # DOUBLE_IS_ODD_INTEGER
    if isinf(iv)
        iw > 0.0 && return odd ? iv : abs(iv)
        return odd ? copysign(0.0, iv) : 0.0
    end
    if iv == 0.0
        iw < 0.0 && throw(DomainError(iv, "0.0 cannot be raised to a negative power"))
        return odd ? iv : 0.0
    end
    negate = false
    if iv < 0.0
        iw == floor(iw) || throw(DomainError(iv, "a negative number raised to a fractional power"))
        iv = -iv
        negate = odd
    end
    iv == 1.0 && return negate ? -1.0 : 1.0
    ix = cpow(iv, iw)
    return negate ? -ix : ix
end

"""`farfield._js_pow`: Python's `q ** j` for a whole j >= 0, infinite where Python overflows."""
@inline function _js_pow(q::Float64, j::Int)
    j == 0 && return 1.0
    odd = isodd(j)
    isnan(q) && return q
    (q == 0 || isinf(q)) && return odd ? q : abs(q)
    q == 1.0 && return 1.0
    r = cpow(abs(q), Float64(j))
    isinf(r) && return Inf
    return (odd && q < 0) ? -r : r
end

"""`farfield._div`: a / b as JavaScript has it."""
@inline function _js_div(a::Float64, b::Float64)
    b != 0 && return a / b
    (a == 0 || a != a) && return NaN
    return copysign(Inf, a) * copysign(1.0, b)
end

"""A number as the Python engine's messages write it (`_num_text`: JavaScript's integers, Python's repr)."""
function _num_text(x::Real)
    f = Float64(x)
    isnan(f) && return "NaN"
    isinf(f) && return f > 0 ? "Infinity" : "-Infinity"
    (isinteger(f) && abs(f) < 1e21) && return string(BigInt(f))
    return py_repr(f)
end

# --- errors ----------------------------------------------------------------------------------

"""A far-field path whose settings cannot describe a path."""
struct FarfError <: Exception
    message::String
end
Base.showerror(io::IO, e::FarfError) = print(io, e.message)

# --- the geometry ------------------------------------------------------------------------------

"""How far down the transfer function may fall before a frequency stops mattering (e^-25), and
how many times thinner than the depth diffusion reaches there the first matched layer is."""
const FARF_ATTENUATION = 25.0
const FARF_RESOLVE = 10.0
"""How much matched layers may grow from one to the next before they are said to be coarse at depth."""
const COARSE_GROWTH = 2.5

"""Dekker's zeroin (1969), as the reports write it, on `fn`."""
function zeroin(fn::F, a::Float64, b::Float64) where {F}
    fa = fn(a)
    fc = fa
    c = a
    fb = 0.0
    for _ in 1:1000
        fb = fn(b)
        if np_sign(fb) == np_sign(fc)
            c = a
            fc = fa
        end
        if abs(fc) < abs(fb)
            a, b, c = b, c, b
            fa, fb, fc = fb, fc, fb
        end
        m = (b + c) / 2
        abs(m - b) <= np_spacing(abs(b)) && return b
        p = (b - a) * fb
        q = fa - fb
        if p < 0
            q = -q
            p = -p
        end
        a = b
        fa = fb
        if p <= np_spacing(q)
            b += np_sign(c - b) * np_spacing(b)
        elseif p <= (m - b) * q
            b += p / q
        else
            b = m
        end
    end
    return b
end

"""`layer_depths`' geo(x): the series of nm layers from a first layer x, less the depth."""
struct _GeoSeries
    nm::Int
    pen_dep::Float64
end
function (f::_GeoSeries)(x::Float64)
    s = 0.0
    for k in 1:f.nm
        s += x * cexp(Float64(k))
    end
    return s - f.pen_dep
end

"""`layer_depths`' total(q): d0 q^j added up, less the depth."""
struct _PowerSeries
    d0::Float64
    nm::Int
    pen_dep::Float64
end
function (f::_PowerSeries)(q::Float64)
    s = 0.0
    for j in 0:f.nm-1
        s += f.d0 * _js_pow(q, j)
    end
    return s - f.pen_dep
end

"""`matched_grid`'s total(r): d0 multiplied by r layer after layer, added up, less the depth."""
struct _ProductSeries
    d0::Float64
    nm::Int
    pen_dep::Float64
end
function (f::_ProductSeries)(r::Float64)
    acc = 0.0
    t = f.d0
    for _ in 1:f.nm
        acc += t
        t *= r
    end
    return acc - f.pen_dep
end

"""The rock matrix's layer thicknesses (the reference layers, `get_d`) into `d`: a geometric series
adding up to the penetration depth; `first` NaN where it is to be worked out."""
function layer_depths!(d::AbstractVector{Float64}, pen_dep::Float64, nm::Int, aw::Float64, first::Float64)
    (pen_dep > 0 && isfinite(pen_dep)) ||
        throw(FarfError("The penetration depth must be a positive length (got $(py_repr(pen_dep)))"))
    (aw > 0 && isfinite(aw)) ||
        throw(FarfError("F/TW must be positive: it is the flow-wetted surface per unit volume of water (got $(py_repr(aw)))"))
    d0 = first
    if !isfinite(d0) || !(d0 > 0)
        E = 2.718281828459045
        d0 = zeroin(_GeoSeries(nm, pen_dep), 1e-12 / E, 2 / aw / E) * E
    end
    if d0 * nm > pen_dep * (1 + 1e-12)
        throw(FarfError("$nm matrix layers starting at $(py_repr(d0)) m cannot add up to a penetration depth of " *
                        "$(py_repr(pen_dep)) m: the layers grow with depth, so the first must be smaller than " *
                        "$(py_repr(pen_dep / nm)) m. Use a thinner first layer, fewer layers, a greater depth, or leave " *
                        "the first layer empty to have it worked out."))
    end
    total = _PowerSeries(d0, nm, pen_dep)
    hi = 100.0
    while total(hi) < 0 && hi < 1e300
        hi *= 100
    end
    q = zeroin(total, 1.0, hi)
    for j in 0:nm-1
        d[j+1] = d0 * _js_pow(q, j)
    end
    return d
end

"""The depth diffusion reaches into the rock at the fastest frequency the path lets through, for
one nuclide (`penetration_scale`)."""
function penetration_scale(de::Float64, rm::Float64, lam::Float64, rf::Float64, aw::Float64, tw::Float64, pe::Float64)
    ((de > 0) && (rm > 0) && (aw > 0) && isfinite(aw)) || return Inf
    ((tw > 0) && (pe > 0)) || return Inf
    G = (FARF_ATTENUATION * (1 + FARF_ATTENUATION / pe)) / tw
    A = aw * sqrt(de * rm)
    u = (2 * G) / (A + sqrt(A * A + 4 * rf * G))
    u2 = _ff_max(u * u, (isfinite(lam) && lam > 0) ? lam : 0.0)
    ((u2 > 0) && isfinite(u2)) || return Inf
    return sqrt(de / rm / u2)
end

"""The matched layers (`matchedGrid`) into `d`, `h`; returns q, the ratio of the series. `first`
NaN where the first layer is to be worked out from `scales()`, the shallowest penetration scale."""
function matched_grid!(d::AbstractVector{Float64}, h::AbstractVector{Float64}, pen_dep::Float64, nm::Int,
                       first::Float64, scales::Function)
    (pen_dep > 0 && isfinite(pen_dep)) ||
        throw(FarfError("The penetration depth must be a positive length (got $(_num_text(pen_dep)))"))
    d0 = first
    if !isfinite(d0) || !(d0 > 0)
        L = scales()
        even = pen_dep / nm
        if !(L < Inf)
            d0 = even
        else
            d0 = L / FARF_RESOLVE
            d0 < even || (d0 = even)
        end
    end
    if d0 * nm > pen_dep * (1 + 1e-12)
        throw(FarfError("$nm matrix layers starting at $(_num_text(d0)) m cannot add up to a penetration depth of " *
                        "$(_num_text(pen_dep)) m: the layers grow with depth, so the first must be smaller than " *
                        "$(_num_text(pen_dep / nm)) m. Use a thinner first layer, fewer layers, a greater depth, or " *
                        "leave the first layer empty to have it worked out."))
    end
    q = 1.0
    if nm == 1 || d0 * nm >= pen_dep * (1 - 1e-12)
        for j in 1:nm
            d[j] = pen_dep / nm
        end
    else
        total = _ProductSeries(d0, nm, pen_dep)
        hi = 2.0
        while total(hi) < 0 && hi < 1e300
            hi *= 2
        end
        q = zeroin(total, 1.0, hi)
        d[1] = d0
        for j in 2:nm
            d[j] = d[j-1] * q
        end
    end
    h[1] = d[1] / (1 + sqrt(q))
    for j in 2:nm
        h[j] = sqrt(d[j-1] * d[j])
    end
    return q
end

"""A layer's thickness for a person, as the application writes it (`thicknessText`)."""
function _thickness_text(x::Float64)
    x >= 1 && return "$(js_to_precision(x, 3)) m"
    x >= 1e-3 && return "$(js_to_precision(x * 1e3, 3)) mm"
    return "$(js_to_precision(x * 1e6, 3)) µm"
end

"""`x.toPrecision(p)`: the exact binary value rounded to p digits, a tie going up."""
function js_to_precision(x::Float64, p::Int)
    isnan(x) && return "NaN"
    s = ""
    if x < 0
        s = "-"
        x = -x
    end
    isinf(x) && return s * "Infinity"
    if x == 0
        m = "0"^p
        e = 0
    else
        r = Rational{BigInt}(x)
        pow10(k) = k >= 0 ? big(10)^k // 1 : 1 // big(10)^(-k)
        e = 0
        while r >= pow10(e + 1)
            e += 1
        end
        while r < pow10(e)
            e -= 1
        end
        scaled = r * pow10(p - 1 - e)
        n = floor(BigInt, scaled + 1 // 2)
        if n >= big(10)^p
            n = div(n, 10)
            e += 1
        end
        m = string(n)
        if e < -6 || e >= p
            m = m[1:1] * (p != 1 ? "." * m[2:end] : "")
            return s * m * "e" * (e >= 0 ? "+" : "-") * string(abs(e))
        end
    end
    e == p - 1 && return s * m
    e >= 0 && return s * m[1:e+1] * "." * m[e+2:end]
    return s * "0." * "0"^(-(e + 1)) * m
end

"""What to say about matched layers that grow by more than `COARSE_GROWTH`, or `nothing`."""
function coarse_layers_warning(d::AbstractVector{Float64}, q::Float64, where_::AbstractString="")
    q > COARSE_GROWTH || return nothing
    isempty(d) && return nothing
    depth = 0.0
    for x in d
        depth += x
    end
    need = 1
    step = d[1]
    reach = d[1]
    while reach < depth * (1 - 1e-12) && need < 10000
        step *= 2
        reach += step
        need += 1
    end
    return "the $(length(d)) matrix layers$where_ grow by $(js_to_precision(q, 3)) from a first layer of " *
           "$(_thickness_text(d[1])), which is coarse at depth: $need layers would keep the growth to 2"
end

# --- the cells ---------------------------------------------------------------------------------

"""The (row, column) pairs the transport matrix fills, in cell numbering (from 0)."""
function cell_structure(g)
    nf, nm, ob, nb = g.n_f, g.n_m, g.o_b, g.n_b
    NF = nf + nb
    rows = Int[]
    cols = Int[]
    cell(k, j) = cell_index(k, j, nm)
    at(r, c) = (push!(rows, r); push!(cols, c))
    for k in 0:NF-1
        at(cell(k, 0), cell(k, 0))
    end
    for k in 0:NF-1, j in 1:nm
        at(cell(k, j), cell(k, j))
    end
    for k in 1:NF-1
        at(cell(k, 0), cell(k - 1, 0))
        at(cell(k - 1, 0), cell(k, 0))
    end
    ob == 3 && at(cell(NF - 1, 0), cell(NF - 3, 0))
    for k in 0:NF-1
        at(cell(k, 1), cell(k, 0))
        at(cell(k, 0), cell(k, 1))
    end
    for j in 0:nm-2, k in 0:NF-1
        at(cell(k, j + 2), cell(k, j + 1))
        at(cell(k, j + 1), cell(k, j + 2))
    end
    return rows, cols
end

"""The cells the release is read from (`get_release`); for the semi-infinite outlet, the plane at the release point."""
function release_cells(g)
    nf, nm, nb, ob = g.n_f, g.n_m, g.n_b, g.o_b
    cell(k) = cell_index(k - 1, 0, nm)
    nb > 0 && return [cell(nf), cell(nf + 1)]
    ob == 2 && return [cell(nf), cell(nf - 1)]
    ob == 3 && return [cell(nf), cell(nf - 1), cell(nf - 2)]
    return [cell(nf)]
end

"""One slot's settings, as `FarfPath._setting` reads them (NaN where the path has no such setting;
`pen_dep_0` NaN where it is not positive)."""
mutable struct FarfSetting
    tw::Float64
    f::Float64
    aw::Float64
    aperture::Float64
    kd_f::Float64
    kd_m::Float64
    de_m::Float64
    eps_m::Float64
    rho_m::Float64
    pe::Float64
    pen_dep::Float64
    pen_dep_0::Float64
    lam::Float64
end
FarfSetting() = FarfSetting(NaN, NaN, NaN, NaN, NaN, NaN, NaN, NaN, NaN, NaN, NaN, NaN, 0.0)

"""One far-field block on cells at run time: its cells for every nuclide and every index of its
other dimensions, the rates worked out from its setting slots, the release read off its last cells."""
mutable struct FarfPath
    nf::Int
    nm::Int
    ob::Int
    nb::Int
    structure::NamedTuple
    block_name::String
    base::Int
    nnuc::Int
    other_width::Int
    dim_off::Vector{Int}
    single_off::Vector{Int}
    keys::Vector{String}
    key_pos::Vector{Int}           # where each of FARF_EQUATION_KEYS is among `keys` (0: not there)
    release_base::Int
    matched::Bool
    surface::String
    ncells::Int
    nnz::Int
    nrel::Int
    slots::Int
    rows::Vector{Int}              # cell numbering, from 0
    cols::Vector{Int}
    setting_idx::Matrix{Int}       # slots x keys, 0-based X slots (Python's setting_idx)
    setting_at::Matrix{Int}        # keys x slots, 1-based, for the refresh
    row_flat::Vector{Int}          # 0-based states, slot by slot
    col_flat::Vector{Int}
    rel_idx::Matrix{Int}           # nrel x slots, 0-based states
    rel_at::Matrix{Int}            # the same, 1-based
    release_slots::Vector{Int}     # 0-based X slots
    release_at::Vector{Int}        # 1-based
    cell_starts::Vector{Int}       # 0-based
    # what a run changes
    vals::Vector{Float64}          # nnz per slot, slot after slot
    rel_w::Matrix{Float64}         # nrel x slots
    seen::Matrix{Float64}          # keys x slots
    lam::Vector{Float64}
    layers_d::Matrix{Float64}      # nm x other_width (matched)
    layers_h::Matrix{Float64}
    layers_q::Vector{Float64}
    laid_out::Vector{Bool}
    pins::Union{Nothing,Vector{Any}}
    # scratch
    changed::Vector{Bool}
    setting::FarfSetting
    ref_d::Vector{Float64}
    mmf::Vector{Float64}
    mmb::Vector{Float64}
end

function FarfPath(structure, base::Int, nnuc::Int, other_width::Int, dim_off::Vector{Int}, single_off::Vector{Int},
                  setting_base::Dict{String,Int}, single, release_base::Int, keys::Vector{String}, grid::AbstractString,
                  surface::AbstractString, block_name::AbstractString)
    g = structure
    nf, nm, ob, nb = g.n_f, g.n_m, g.o_b, g.n_b
    ncells = (nf + nb) * (nm + 1)
    rows, cols = cell_structure(g)
    nnz = length(rows)
    rel_cells = release_cells(g)
    nrel = length(rel_cells)
    slots = other_width * nnuc
    nkeys = length(keys)
    is_single = Set{String}(single)
    setting_idx = zeros(Int, slots, nkeys)
    for o in 0:other_width-1, m in 0:nnuc-1
        slot = o * nnuc + m
        off = dim_off[slot+1]
        for (k, key) in enumerate(keys)
            one = isempty(single_off) ? 0 : single_off[o+1]
            setting_idx[slot+1, k] = setting_base[key] + (key in is_single ? one : off)
        end
    end
    row_flat = Vector{Int}(undef, slots * nnz)
    col_flat = Vector{Int}(undef, slots * nnz)
    rel_idx = Matrix{Int}(undef, nrel, slots)
    for o in 0:other_width-1, m in 0:nnuc-1
        s = o * nnuc + m
        obase = base + o * ncells * nnuc
        for e in 1:nnz
            row_flat[s*nnz+e] = obase + rows[e] * nnuc + m
            col_flat[s*nnz+e] = obase + cols[e] * nnuc + m
        end
        for r in 1:nrel
            rel_idx[r, s+1] = obase + rel_cells[r] * nnuc + m
        end
    end
    cell_starts = Int[base + o * ncells * nnuc + c * nnuc for o in 0:other_width-1 for c in 0:ncells-1]
    release_slots = release_base .+ dim_off
    key_pos = Int[something(findfirst(==(k), keys), 0) for k in FARF_EQUATION_KEYS]
    return FarfPath(nf, nm, ob, nb, g, String(block_name), base, nnuc, other_width, dim_off, single_off, keys, key_pos,
                    release_base, grid == "matched", surface in SURFACES ? String(surface) : "f", ncells, nnz, nrel,
                    slots, rows, cols, setting_idx, permutedims(setting_idx) .+ 1, row_flat, col_flat, rel_idx,
                    rel_idx .+ 1, release_slots, release_slots .+ 1, cell_starts,
                    zeros(slots * nnz), zeros(nrel, slots), fill(NaN, nkeys, slots), zeros(nnuc),
                    zeros(nm, other_width), zeros(nm, other_width), fill(NaN, other_width), fill(false, other_width),
                    nothing, fill(false, slots), FarfSetting(), zeros(nm), zeros(max(0, nm - 1)), zeros(max(0, nm - 1)))
end

# The equation keys, by their place in FARF_EQUATION_KEYS.
const _K_TW, _K_F, _K_AW, _K_APERTURE, _K_KD_F, _K_KD_M, _K_DE_M, _K_EPS_M, _K_RHO_M, _K_PE, _K_PEN_DEP, _K_PEN_DEP_0 =
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12

@inline _xset(F::FarfPath, X::Vector{Float64}, slot::Int, key::Int) =
    (p = F.key_pos[key]; p == 0 ? NaN : @inbounds X[F.setting_at[p, slot]])

"""Slot `slot`'s (1-based) settings into the path's scratch record (`FarfPath._setting`)."""
function _read_setting!(F::FarfPath, X::Vector{Float64}, slot::Int)
    s = F.setting
    s.tw = _xset(F, X, slot, _K_TW)
    s.f = _xset(F, X, slot, _K_F)
    s.aw = _xset(F, X, slot, _K_AW)
    s.aperture = _xset(F, X, slot, _K_APERTURE)
    s.kd_f = _xset(F, X, slot, _K_KD_F)
    s.kd_m = _xset(F, X, slot, _K_KD_M)
    s.de_m = _xset(F, X, slot, _K_DE_M)
    s.eps_m = _xset(F, X, slot, _K_EPS_M)
    s.rho_m = _xset(F, X, slot, _K_RHO_M)
    s.pe = _xset(F, X, slot, _K_PE)
    s.pen_dep = _xset(F, X, slot, _K_PEN_DEP)
    v = _xset(F, X, slot, _K_PEN_DEP_0)
    s.pen_dep_0 = v > 0 ? v : NaN
    s.lam = F.lam[(slot-1)%F.nnuc+1]
    return s
end

"""The flow-wetted surface per unit volume of water, however the path gives it."""
@inline function _wetted_surface(surface::String, s::FarfSetting)
    surface == "aw" && return s.aw
    surface == "aperture" && return _js_div(2.0, s.aperture)
    return _js_div(s.f, s.tw)
end

function _surface_problem(surface::String, s::FarfSetting, aw::Float64)
    (aw > 0 && isfinite(aw)) && return nothing
    surface == "aw" && return "The flow-wetted surface a_w must be positive: it is the wetted surface per unit volume of " *
                              "water (got $(_num_text(aw)))"
    surface == "aperture" && return "The fracture aperture must be a positive length: the wetted surface is 2/δ per unit " *
                                    "volume of water (got δ = $(_num_text(s.aperture)))"
    return "F/TW must be positive: it is the flow-wetted surface per unit volume of water (got $(_num_text(aw)))"
end

const _ROCK_FIELDS = ((:kd_f, "kd_f"), (:kd_m, "kd_m"), (:de_m, "de_m"), (:eps_m, "eps_m"), (:rho_m, "rho_m"))

"""Why one slot's rock settings cannot be used, or `nothing` (`rockSettingProblem`)."""
function rock_setting_problem(s::FarfSetting)
    for (field, key) in _ROCK_FIELDS
        v = getfield(s, field)
        (v >= 0 && isfinite(v)) && continue
        return "$(ROCK_TERM[key]) must be zero or positive (got $(js_text(v)))"
    end
    return nothing
end

"""One slot's rates (`coefficients`), its matrix values into `F.vals` and its release weights into
`F.rel_w`. `layers` is 0 for the reference layers, which are worked out first into `F.ref_d` unless
`ref_ready`; o is the combination (1-based)."""
function _slot_rates!(F::FarfPath, s::FarfSetting, slot::Int, o::Int, ref_ready::Bool)
    nf, nm = F.nf, F.nm
    pe = s.pe
    (pe > 0 && isfinite(pe)) ||
        throw(FarfError("The Peclet number must be greater than zero: the dispersion is TW/Pe (got $(_num_text(pe)))"))
    aw = _wetted_surface(F.surface, s)
    bad = _surface_problem(F.surface, s, aw)
    bad === nothing || throw(FarfError(bad))
    (s.tw > 0 && isfinite(s.tw)) || throw(FarfError("The travel time T_w must be positive (got $(_num_text(s.tw)))"))
    rock = rock_setting_problem(s)
    rock === nothing || throw(FarfError(rock))
    r_m = s.eps_m + s.rho_m * s.kd_m
    if !(r_m > 0 && isfinite(r_m))
        throw(FarfError("The matrix capacity eps + rho*Kd must be greater than zero (got $(py_repr(s.eps_m)) + " *
                        "$(py_repr(s.rho_m))*$(py_repr(s.kd_m)) = $(py_repr(r_m))). A rock with no porosity and no " *
                        "sorption has nothing for the nuclide to diffuse into."))
    end
    f_df = 1 / (1 + s.kd_f * aw)
    adv_f = (f_df * nf) / s.tw
    d_f = _ff_max(0.0, adv_f * (nf / pe - 0.5))
    de = s.de_m
    mmf, mmb = F.mmf, F.mmb
    if F.matched
        d = view(F.layers_d, :, o)
        h = view(F.layers_h, :, o)
        diff_fm1 = (f_df * aw * de) / h[1]
        diff_m1f = de / (r_m * d[1] * h[1])
        @inbounds for j in 1:nm-1
            mmf[j] = de / (r_m * d[j] * h[j+1])
            mmb[j] = de / (r_m * d[j+1] * h[j+1])
        end
    else
        d = F.ref_d
        ref_ready || layer_depths!(d, s.pen_dep, nm, aw, s.pen_dep_0)
        diff_fm1 = (f_df * 2 * aw * de) / d[1]
        diff_m1f = (2 * de) / (r_m * d[1] * d[1])
        @inbounds for j in 1:nm-1
            mmf[j] = (2 * de) / (r_m * d[j] * (d[j] + d[j+1]))
            mmb[j] = (2 * de) / (r_m * d[j+1] * (d[j+1] + d[j]))
        end
    end
    _cell_values!(F, (slot - 1) * F.nnz, adv_f, d_f, diff_fm1, diff_m1f)
    _release_weights!(F, slot, adv_f, d_f)
    return nothing
end

"""The transport matrix's values, in the order `cell_structure` lists them, into `F.vals[at+1:]`."""
function _cell_values!(F::FarfPath, at::Int, adv_f::Float64, d_f::Float64, diff_fm1::Float64, diff_m1f::Float64)
    out = F.vals
    nm, ob = F.nm, F.ob
    NF = F.nf + F.nb
    mmf, mmb = F.mmf, F.mmb
    @inbounds begin
        i = at + 1
        frac_loss = -(adv_f + 2 * d_f + diff_fm1)
        for k in 0:NF-1
            out[i+k] = frac_loss
        end
        out[i] += d_f
        if ob == 1
            out[i+NF-1] += d_f
        elseif ob == 2
            out[i+NF-1] += 2 * d_f
        elseif ob == 3
            out[i+NF-1] += 3 * d_f
        end
        i += NF
        for k in 1:NF, j in 1:nm
            if j == 1
                out[i] = -(diff_m1f + mmf[1])
            elseif j == nm
                out[i] = -mmb[nm-1]
            else
                out[i] = -(mmf[j] + mmb[j-1])
            end
            i += 1
        end
        for k in 1:NF-1
            v = d_f + adv_f
            if k == NF - 1
                if ob == 2
                    v -= d_f
                elseif ob == 3
                    v -= 3 * d_f
                end
            end
            out[i] = v
            out[i+1] = d_f
            i += 2
        end
        if ob == 3
            out[i] = d_f
            i += 1
        end
        for k in 1:NF
            out[i] = diff_fm1
            out[i+1] = diff_m1f
            i += 2
        end
        for j in 1:nm-1, k in 1:NF
            out[i] = mmf[j]
            out[i+1] = mmb[j]
            i += 2
        end
    end
    return nothing
end

"""The release weights of slot `slot` (1-based) from the rates (`release_weights`)."""
function _release_weights!(F::FarfPath, slot::Int, adv_f::Float64, d_f::Float64)
    w = F.rel_w
    if F.nb > 0
        w[1, slot] = adv_f + d_f
        w[2, slot] = -d_f
    elseif F.ob == 0
        w[1, slot] = adv_f + d_f
    elseif F.ob == 1
        w[1, slot] = adv_f
    elseif F.ob == 2
        w[1, slot] = adv_f - d_f
        w[2, slot] = d_f
    else
        w[1, slot] = adv_f - 2 * d_f
        w[2, slot] = 3 * d_f
        w[3, slot] = -d_f
    end
    return nothing
end

"""The matched layers of combination o (1-based), from every nuclide on it, each one's rock settings
checked first (`FarfPath._lay_out`)."""
function _lay_out!(F::FarfPath, X::Vector{Float64}, o::Int)
    nnuc = F.nnuc
    first_slot = (o - 1) * nnuc + 1
    s = _read_setting!(F, X, first_slot)
    aw = _wetted_surface(F.surface, s)
    pen_dep, first, tw, pe = s.pen_dep, s.pen_dep_0, s.tw, s.pe
    for m in 0:nnuc-1
        n = _read_setting!(F, X, first_slot + m)
        rock = rock_setting_problem(n)
        rock === nothing || throw(FarfError(rock))
    end
    scales = function ()
        L = Inf
        for m in 0:nnuc-1
            n = _read_setting!(F, X, first_slot + m)
            v = penetration_scale(n.de_m, n.eps_m + n.rho_m * n.kd_m, F.lam[m+1], 1 + n.kd_f * aw, aw, tw, pe)
            v < L && (L = v)
        end
        return L
    end
    F.layers_q[o] = matched_grid!(view(F.layers_d, :, o), view(F.layers_h, :, o), pen_dep, F.nm, first, scales)
    return nothing
end

"""Works the rates out again for every slot whose settings moved (`FarfPath.refresh`); the
matched layers of a combination are laid out at its first refresh of a run."""
function farfield_refresh!(F::FarfPath, X::Vector{Float64})
    nkeys = size(F.setting_at, 1)
    any_changed = false
    @inbounds for slot in 1:F.slots
        ch = false
        for k in 1:nkeys
            if X[F.setting_at[k, slot]] != F.seen[k, slot]
                ch = true
                break
            end
        end
        F.changed[slot] = ch
        any_changed |= ch
    end
    if !any_changed
        F.matched || return nothing
        all(F.laid_out) && return nothing
    end
    nnuc = F.nnuc
    for o in 1:F.other_width
        lo = (o - 1) * nnuc + 1
        hi = o * nnuc
        fresh = F.matched && !F.laid_out[o]
        if !fresh
            any_o = false
            for slot in lo:hi
                F.changed[slot] && (any_o = true; break)
            end
            any_o || continue
        end
        fresh && _lay_out!(F, X, o)
        ref_ready = false
        try
            for slot in lo:hi
                (!fresh && !F.changed[slot]) && continue
                s = _read_setting!(F, X, slot)
                _slot_rates!(F, s, slot, o, ref_ready)
                ref_ready = true
                @inbounds for k in 1:nkeys
                    F.seen[k, slot] = X[F.setting_at[k, slot]]
                end
            end
        catch
            fresh && (F.laid_out[o] = false)
            rethrow()
        end
        fresh && (F.laid_out[o] = true)
    end
    return nothing
end

"""The release out of the far end of every slot, into its slot of X: each slot's weighted sum
added up one cell at a time from zero, in the cells' order."""
function farfield_release!(F::FarfPath, y::Vector{Float64}, X::Vector{Float64}, t::Float64=0.0)
    farfield_refresh!(F, X)
    w = F.rel_w
    @inbounds for slot in 1:F.slots
        q = 0.0
        for r in 1:F.nrel
            q += w[r, slot] * y[F.rel_at[r, slot]]
        end
        X[F.release_at[slot]] = q
    end
    return nothing
end

"""Starts a run: the matched layers are laid out again at its first instant and held to its end
(`FarfPath.restart`); layers held from outside are this run's before it starts."""
function farfield_restart!(F::FarfPath)
    fill!(F.laid_out, false)
    fill!(F.seen, NaN)
    pins = F.pins
    (pins === nothing || isempty(pins)) && return nothing
    nm = F.nm
    for o in 1:F.other_width
        g = o <= length(pins) ? pins[o] : nothing
        g === nothing && continue
        d = _pin_field(g, :d)
        h = _pin_field(g, :h)
        (d === nothing || h === nothing || length(d) != nm || length(h) != nm) && continue
        F.layers_d[:, o] .= Float64.(d)
        F.layers_h[:, o] .= Float64.(h)
        F.layers_q[o] = Float64(_pin_field(g, :q))
        F.laid_out[o] = true
    end
    return nothing
end

_pin_field(g::AbstractDict, k::Symbol) = get(g, String(k), get(g, k, nothing))
_pin_field(g, k::Symbol) = hasproperty(g, k) ? getproperty(g, k) : nothing

"""Holds a combination's matched layers at those given -- one `(d, h, q)` per combination, or
`nothing` for one left to lay out its own -- or, given `nothing`, lets every combination lay out
its own again (`pinLayers`)."""
function farfield_pin_layers!(F::FarfPath, pins)
    F.pins = (F.matched && pins !== nothing && !isempty(pins)) ? Any[p for p in pins] : nothing
    farfield_restart!(F)
end

"""The decay constants the path's nuclides decay with (for the matched layers), or none."""
function farfield_set_decay!(F::FarfPath, dec)
    fill!(F.lam, 0.0)
    if dec !== nothing
        n = min(F.nnuc, length(dec.lam))
        F.lam[1:n] .= dec.lam[1:n]
    end
    farfield_restart!(F)
end

"""What the run has to say about this path's layers (`layerWarnings`): `(block, message)` per
combination whose matched layers grow by more than `COARSE_GROWTH`."""
function farfield_layer_warnings(F::FarfPath)
    out = JDict[]
    F.matched || return out
    for o in 1:F.other_width
        F.laid_out[o] || continue
        where_ = F.other_width > 1 ? " (index combination $o of $(F.other_width))" : ""
        msg = coarse_layers_warning(view(F.layers_d, :, o), F.layers_q[o], where_)
        msg === nothing || push!(out, JDict("block" => F.block_name, "message" => msg))
    end
    return out
end

farfield_is_laplace(::FarfPath) = false
farfield_setting_slots(F::FarfPath) = F.setting_idx
farfield_slots(F::FarfPath) = F.slots
farfield_release_slots(F::FarfPath) = F.release_slots
farfield_held_idx(F::FarfPath) = Int[]
farfield_set_inflow!(F::FarfPath, a, b, c) = nothing
farfield_cell_starts(F::FarfPath) = F.cell_starts
farfield_row_col(F::FarfPath) = (F.row_flat, F.col_flat)
farfield_values(F::FarfPath) = F.vals
farfield_prime!(F::FarfPath, t0, y0, values) = nothing
farfield_store!(F::FarfPath, t, y, values) = nothing
farfield_rel_idx(F::FarfPath) = [F.rel_idx[:, s] for s in 1:F.slots]
farfield_release_weights(F::FarfPath) = F.rel_w
farfield_release_dependencies(F::FarfPath, of_x) = Vector{Int}[]
farfield_laplace_gradient!(an, F::FarfPath, G, y, X, t) = nothing

"""A copy of a path for another thread: the structure and the index vectors shared, what a run
changes its own."""
function farfield_clone(F::FarfPath)
    C = FarfPath(F.nf, F.nm, F.ob, F.nb, F.structure, F.block_name, F.base, F.nnuc, F.other_width, F.dim_off,
                 F.single_off, F.keys, F.key_pos, F.release_base, F.matched, F.surface, F.ncells, F.nnz, F.nrel,
                 F.slots, F.rows, F.cols, F.setting_idx, F.setting_at, F.row_flat, F.col_flat, F.rel_idx, F.rel_at,
                 F.release_slots, F.release_at, F.cell_starts,
                 copy(F.vals), copy(F.rel_w), copy(F.seen), copy(F.lam), copy(F.layers_d), copy(F.layers_h),
                 copy(F.layers_q), copy(F.laid_out), F.pins === nothing ? nothing : copy(F.pins),
                 copy(F.changed), FarfSetting(), copy(F.ref_d), copy(F.mmf), copy(F.mmb))
    return C
end

# --- the semi-analytical path ---------------------------------------------------------------------

include("farfield_laplace.jl")
include("farfield_semi.jl")

# --- what the builder, the system and the runner call ----------------------------------------------

"""
    make_farfield_path(b, p, rel, setting_base, keys_)

The run-time object of far-field block `p` (a layout entry), its release slots starting at
`rel.base` and its settings at `setting_base`. A semi-analytical path's release reads what flows in
at the same instant, so it is worked out after every rate that delivers into the path.
"""
function make_farfield_path(b, p::Entry, rel::Entry, setting_base::Dict{String,Int}, keys_)
    farf = p[:farf]
    keys = String[k for k in keys_]
    single = String[k for k in keys if !(k in FARF_NUCLIDE_KEYS)]
    if farf.laplace
        for t in b.project.blocks["transfers"]
            to = get(t, "to", nothing)
            if js_truthy(to) && !haskey(b.state_by_name, to) && get(b.path_by_name, to, nothing) === p
                push!(rel.needs, t["qname"])
            end
        end
        for src in b.project.blocks["inflows"]
            to = get(src, "to", nothing)
            if !(to isa AbstractString && haskey(b.state_by_name, to)) &&
               (to isa AbstractString ? get(b.path_by_name, to, nothing) : nothing) === p
                push!(rel.needs, src["qname"])
            end
        end
        sim = b.project.simulation
        names = farf.list_name === nothing ? nothing : index_names(b.space, farf.list_name)
        return LaplaceFarfPath(p.base, farf.nnuc, farf.other_width, collect(Int, farf.dim_off),
                               collect(Int, farf.single_off), setting_base, keys, single, surface_of(p.block), rel.base,
                               Float64(sim["end_time"]) - Float64(sim["start_time"]), names, p.name)
    end
    grid = get(p.block, "grid", nothing) == "matched" ? "matched" : "reference"
    return FarfPath(farf.structure, p.base, farf.nnuc, farf.other_width, collect(Int, farf.dim_off),
                    collect(Int, farf.single_off), setting_base, single, rel.base, keys, grid, surface_of(p.block),
                    p.name)
end

"""What each setting is called in a message: the application's labels as text."""
const FARF_TEXT = Dict("tw" => "Tw", "f" => "F", "aw" => "aw", "aperture" => "δ", "kd_f" => "Kd,f",
                       "kd_m" => "Kd,m", "de_m" => "De,m", "eps_m" => "εm", "rho_m" => "ρm", "pe" => "Pe",
                       "pen_dep" => "PENDEP", "pen_dep_0" => "PENDEP0")

"""Python's `str()` of what a block holds for a setting, for a message."""
_ff_text(v::AbstractString) = String(v)
_ff_text(v::Bool) = v ? "True" : "False"
_ff_text(v::Integer) = string(v)
_ff_text(v::AbstractFloat) = py_repr(Float64(v))
_ff_text(::Nothing) = ""
_ff_text(v) = string(v)

"""
    semi_refusals(b, X)

What a semi-analytical path cannot be, found once the settings that never move are worked out: a
setting that follows the clock or the state, and a path its method cannot solve.
"""
function semi_refusals(b, X::Vector{Float64})
    for p in b.farf_layout
        p[:farf].laplace || continue
        for key in active_equation_keys(p.block)
            slot = get(b.alg_by_name, "$(p.name)#$key", nothing)
            (slot === nothing || key == "pen_dep_0") && continue
            cls = slot.width > 0 ? Int(maximum(b.slot_class[slot.base+1:slot.base+slot.width])) : 0
            cls == 0 && continue
            said = strip(_ff_text(get(p.block, key, nothing)))
            throw(BuildError("'$(p.local_name)' is worked out semi-analytically, which solves the path once for the " *
                             "whole run, so its settings have to be constants -- and " *
                             "$(get(FARF_TEXT, key, key)) follows the $(cls == 1 ? "clock" : "state of the model")" *
                             (isempty(said) ? "" : " ('$said')") *
                             ". Give it a constant, or work the path out on cells, which reads its settings as they " *
                             "change.", p.name))
        end
        try
            laplace_prepare!(b.FARF[p[:farf_index]+1], X)
        catch e
            e isa FarfError || rethrow()
            throw(BuildError("'$(p.local_name)' cannot be worked out semi-analytically: $(e.message)", p.name))
        end
    end
    return nothing
end

"""
    farfield_outputs(sys, entry) -> Vector{JDict}

The series a far-field path reports: what it holds per nuclide (summed over its cells, the extra
cells of a semi-infinite outlet left out) and, with `report_cells`, every cell.
"""
function farfield_outputs(sys, entry::Entry)
    farf = entry[:farf]
    block = entry.block
    space = sys.builder.space
    held = held_cells(block)
    raw_unit = get(block, "unit", nothing)
    unit_text = raw_unit === nothing ? "" : _ff_text(raw_unit)
    unit = replace(unit_text, r"/[^/]*$" => "")
    isempty(unit) && (unit = "Bq")
    cells = js_truthy(get(block, "report_cells", nothing)) ? cell_names(block) : nothing
    names = farf.list_name === nothing ? Any[nothing] : Any[n for n in index_names(space, farf.list_name)]
    material = sys.builder.material_list
    has_material = material !== nothing && material != ""
    out = JDict[]
    for o in 0:farf.other_width-1
        others = isempty(farf.other_dims) ? String[] : tuple_at(space, farf.other_dims, o)
        base = entry.base + o * farf.ncells * farf.nnuc
        for m in 0:farf.nnuc-1
            nuclide = names[m+1]
            index = Any[]
            k = 0
            for dim in entry.dims
                if dim == farf.list_name
                    push!(index, nuclide)
                else
                    k += 1
                    push!(index, others[k])
                end
            end
            suffix = isempty(index) ? "" : " [$(join(index, ", "))]"
            offsets = Int[base + c * farf.nnuc + m for c in 0:held-1]
            push!(out, JDict("kind" => "farfield_inventory", "block" => "$(entry.name) held",
                             "nuclide" => has_material ? nuclide : nothing, "index" => isempty(index) ? nothing : index,
                             "dims" => collect(Any, entry.dims), "label" => "$(entry.name) held$suffix", "unit" => unit,
                             "source" => "y", "offsets" => offsets))
            cells === nothing && continue
            for cell in 0:farf.ncells-1
                push!(out, JDict("kind" => "farfield_cell", "block" => "$(entry.name).$(cells[cell+1])",
                                 "nuclide" => has_material ? nuclide : nothing,
                                 "index" => isempty(index) ? nothing : index, "dims" => collect(Any, entry.dims),
                                 "label" => "$(entry.name).$(cells[cell+1])$suffix", "unit" => unit, "source" => "y",
                                 "offset" => base + cell * farf.nnuc + m))
            end
        end
    end
    return out
end

"""Every far-field path's warnings of a run: semi-analytical responses that missed their mass
balance (`stats.farfield`) and matched layers coarse at depth (`stats.layers`)."""
function farfield_warnings(sys)
    balance = JDict[]
    layers = JDict[]
    for F in sys.data.FARF
        if F isa LaplaceFarfPath
            append!(balance, laplace_balance_warnings(F))
        elseif F isa FarfPath
            append!(layers, farfield_layer_warnings(F))
        end
    end
    return (farfield=balance, layers=layers)
end
