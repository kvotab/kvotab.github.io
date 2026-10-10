# The arithmetic of the language and of the application.
#
# Two families. The model's own equations are evaluated with the C library's
# exp, log, pow and the rest -- which is what the Python engine's numpy and
# numba use too, so a derivative here is the Python engine's to the last bit.
# Julia's own `exp` and `^` are as accurate, but round differently in the
# last place for a few per cent of arguments.
#
# And V8's own `Math.exp`, `Math.log`, `Math.log10`, `Math.pow`, `Math.log1p`
# and `Math.expm1` -- V8 carries ports of fdlibm (src/base/ieee754.cc) -- for
# the few numbers that are compared with the application's to the last digit:
# the output times of a logarithmic grid, above all, where a time column that
# differs in its seventeenth digit makes two result files that cannot be
# joined on time.

const LIBM = Sys.isapple() ? "libSystem.B.dylib" : Sys.iswindows() ? "msvcrt" : "libm.so.6"

# The C library's functions, called as numpy calls them.
@inline cexp(x::Float64) = ccall((:exp, LIBM), Float64, (Float64,), x)
@inline clog(x::Float64) = ccall((:log, LIBM), Float64, (Float64,), x)
@inline clog10(x::Float64) = ccall((:log10, LIBM), Float64, (Float64,), x)
@inline clog2(x::Float64) = ccall((:log2, LIBM), Float64, (Float64,), x)
@inline cpow(x::Float64, y::Float64) = ccall((:pow, LIBM), Float64, (Float64, Float64), x, y)
@inline csin(x::Float64) = ccall((:sin, LIBM), Float64, (Float64,), x)
@inline ccos(x::Float64) = ccall((:cos, LIBM), Float64, (Float64,), x)
@inline ctan(x::Float64) = ccall((:tan, LIBM), Float64, (Float64,), x)
@inline casin(x::Float64) = ccall((:asin, LIBM), Float64, (Float64,), x)
@inline cacos(x::Float64) = ccall((:acos, LIBM), Float64, (Float64,), x)
@inline catan(x::Float64) = ccall((:atan, LIBM), Float64, (Float64,), x)
@inline catan2(y::Float64, x::Float64) = ccall((:atan2, LIBM), Float64, (Float64, Float64), y, x)
@inline csinh(x::Float64) = ccall((:sinh, LIBM), Float64, (Float64,), x)
@inline ccosh(x::Float64) = ccall((:cosh, LIBM), Float64, (Float64,), x)
@inline ctanh(x::Float64) = ccall((:tanh, LIBM), Float64, (Float64,), x)
@inline casinh(x::Float64) = ccall((:asinh, LIBM), Float64, (Float64,), x)
@inline cacosh(x::Float64) = ccall((:acosh, LIBM), Float64, (Float64,), x)
@inline catanh(x::Float64) = ccall((:atanh, LIBM), Float64, (Float64,), x)
@inline chypot(x::Float64, y::Float64) = ccall((:hypot, LIBM), Float64, (Float64, Float64), x, y)
@inline clog1p(x::Float64) = ccall((:log1p, LIBM), Float64, (Float64,), x)
@inline cexpm1(x::Float64) = ccall((:expm1, LIBM), Float64, (Float64,), x)

# --- V8's fdlibm ports --------------------------------------------------------------

const _LN2_HI = 6.93147180369123816490e-01
const _LN2_LO = 1.90821492927058770002e-10
const _TWO54 = 1.80143985094819840000e+16
const _LG1 = 6.666666666666735130e-01
const _LG2 = 3.999999999940941908e-01
const _LG3 = 2.857142874366239149e-01
const _LG4 = 2.222219843214978396e-01
const _LG5 = 1.818357216161805012e-01
const _LG6 = 1.531383769920937332e-01
const _LG7 = 1.479819860511658591e-01
const _O_THRESHOLD = 7.09782712893383973096e+02
const _U_THRESHOLD = -7.45133219101941108420e+02
const _LN2HI = (6.93147180369123816490e-01, -6.93147180369123816490e-01)
const _LN2LO = (1.90821492927058770002e-10, -1.90821492927058770002e-10)
const _HALF = (0.5, -0.5)
const _INVLN2 = 1.44269504088896338700e+00
const _P1 = 1.66666666666666019037e-01
const _P2 = -2.77777777770155933842e-03
const _P3 = 6.61375632143793436117e-05
const _P4 = -1.65339022054652515390e-06
const _P5 = 4.13813679705723846039e-08
const _E = 2.718281828459045
const _TWOM1000 = 9.33263618503218878990e-302
const _TWO1023 = 8.988465674311579539e307
const _IVLN10 = 4.34294481903251816668e-01
const _LOG10_2HI = 3.01029995663611771306e-01
const _LOG10_2LO = 3.69423907715893078616e-13

@inline function _words(x::Float64)
    b = reinterpret(UInt64, x)
    return Int64((b >> 32) & 0xffffffff), Int64(b & 0xffffffff)
end
@inline _from_words(hi::Integer, lo::Integer) =
    reinterpret(Float64, (UInt64(hi & 0xffffffff) << 32) | UInt64(lo & 0xffffffff))
@inline function _signed32(v::Int64)
    v &= 0xffffffff
    return (v & 0x80000000) != 0 ? v - 4294967296 : v
end

"""`Math.exp`, as V8 computes it."""
function js_exp(x::Float64)
    hx, lx = _words(x)
    xsb = (hx >> 31) & 1
    hx &= 0x7fffffff
    hi = lo = 0.0
    k = 0
    if hx >= 0x40862e42
        if hx >= 0x7ff00000
            ((hx & 0xfffff) | lx) != 0 && return x + x
            return xsb == 0 ? x : 0.0
        end
        x > _O_THRESHOLD && return Inf
        x < _U_THRESHOLD && return 0.0
    end
    if hx > 0x3fd62e42
        if hx < 0x3ff0a2b2
            x == 1.0 && return _E
            hi = x - _LN2HI[xsb+1]
            lo = _LN2LO[xsb+1]
            k = 1 - xsb - xsb
        else
            k = trunc(Int, _INVLN2 * x + _HALF[xsb+1])
            t = Float64(k)
            hi = x - t * _LN2HI[1]
            lo = t * _LN2LO[1]
        end
        x = hi - lo
    elseif hx < 0x3e300000
        return 1.0 + x
    else
        k = 0
    end
    t = x * x
    twopk = k >= -1021 ? _from_words(0x3ff00000 + ((k << 20) & 0xffffffff), 0) :
            _from_words(0x3ff00000 + (((k + 1000) << 20) & 0xffffffff), 0)
    c = x - t * (_P1 + t * (_P2 + t * (_P3 + t * (_P4 + t * _P5))))
    k == 0 && return 1.0 - ((x * c) / (c - 2.0) - x)
    y = 1.0 - ((lo - (x * c) / (2.0 - c)) - hi)
    if k >= -1021
        k == 1024 && return y * 2.0 * _TWO1023
        return y * twopk
    end
    return y * twopk * _TWOM1000
end

"""`Math.log`, as V8 computes it."""
function js_log(x::Float64)
    hx, lx = _words(x)
    hx = _signed32(hx)
    k = 0
    if hx < 0x00100000
        ((hx & 0x7fffffff) | lx) == 0 && return -Inf
        hx < 0 && return NaN
        k -= 54
        x *= _TWO54
        hx = _signed32(_words(x)[1])
    end
    hx >= 0x7ff00000 && return x + x
    k += (hx >> 20) - 1023
    hx &= 0x000fffff
    i = (hx + 0x95f64) & 0x100000
    x = _from_words(hx | (i ⊻ 0x3ff00000), _words(x)[2])
    k += i >> 20
    f = x - 1.0
    if (0x000fffff & (2 + hx)) < 3
        if f == 0.0
            k == 0 && return 0.0
            dk = Float64(k)
            return dk * _LN2_HI + dk * _LN2_LO
        end
        r = f * f * (0.5 - 0.33333333333333333 * f)
        k == 0 && return f - r
        dk = Float64(k)
        return dk * _LN2_HI - ((r - dk * _LN2_LO) - f)
    end
    s = f / (2.0 + f)
    dk = Float64(k)
    z = s * s
    i = hx - 0x6147a
    w = z * z
    j = 0x6b851 - hx
    t1 = w * (_LG2 + w * (_LG4 + w * _LG6))
    t2 = z * (_LG1 + w * (_LG3 + w * (_LG5 + w * _LG7)))
    i |= j
    r = t2 + t1
    if i > 0
        hfsq = 0.5 * f * f
        k == 0 && return f - (hfsq - s * (hfsq + r))
        return dk * _LN2_HI - ((hfsq - (s * (hfsq + r) + dk * _LN2_LO)) - f)
    end
    k == 0 && return f - s * (f - r)
    return dk * _LN2_HI - ((s * (f - r) - dk * _LN2_LO) - f)
end

"""`Math.log10`, as V8 computes it."""
function js_log10(x::Float64)
    hx, lx = _words(x)
    hx = _signed32(hx)
    k = 0
    if hx < 0x00100000
        ((hx & 0x7fffffff) | lx) == 0 && return -Inf
        hx < 0 && return NaN
        k -= 54
        x *= _TWO54
        hx, lx = _words(x)
        hx = _signed32(hx)
    end
    hx >= 0x7ff00000 && return x + x
    (hx == 0x3ff00000 && lx == 0) && return 0.0
    k += (hx >> 20) - 1023
    i = k < 0 ? 1 : 0
    hx = (hx & 0x000fffff) | ((0x3ff - i) << 20)
    y = Float64(k + i)
    x = _from_words(hx, lx)
    z = y * _LOG10_2LO + _IVLN10 * js_log(x)
    return z + y * _LOG10_2HI
end

const _PW_BP = (1.0, 1.5)
const _PW_DP_H = (0.0, 5.84962487220764160156e-01)
const _PW_DP_L = (0.0, 1.35003920212974897128e-08)
const _PW_TWO53 = 9007199254740992.0
const _PW_L1 = 5.99999999999994648725e-01
const _PW_L2 = 4.28571428578550184252e-01
const _PW_L3 = 3.33333329818377432918e-01
const _PW_L4 = 2.72728123808534006489e-01
const _PW_L5 = 2.30660745775561754067e-01
const _PW_L6 = 2.06975017800338417784e-01
const _PW_LG2 = 6.93147180559945286227e-01
const _PW_LG2_H = 6.93147182464599609375e-01
const _PW_LG2_L = -1.90465429995776804525e-09
const _PW_OVT = 8.0085662595372944372e-17
const _PW_CP = 9.61796693925975554329e-01
const _PW_CP_H = 9.61796700954437255859e-01
const _PW_CP_L = -7.02846165095275826516e-09
const _PW_IVLN2 = 1.44269504088896338700e+00
const _PW_IVLN2_H = 1.44269502162933349609e+00
const _PW_IVLN2_L = 1.92596299112661746887e-08

@inline _low_zero(x::Float64) = _from_words(_words(x)[1], 0)

"""fdlibm's `pow`, which V8's `Math.pow` was: it places the points of a logarithmic series."""
function js_pow(x::Float64, y::Float64)
    isnan(y) && return NaN
    (abs(x) == 1.0 && isinf(y)) && return NaN
    hx, lx = _words(x)
    hy, ly = _words(y)
    hx = _signed32(hx)
    hy = _signed32(hy)
    ix = hx & 0x7fffffff
    iy = hy & 0x7fffffff
    (iy | ly) == 0 && return 1.0
    if ix > 0x7ff00000 || (ix == 0x7ff00000 && lx != 0) || iy > 0x7ff00000 || (iy == 0x7ff00000 && ly != 0)
        return x + y
    end
    yisint = 0
    if hx < 0
        if iy >= 0x43400000
            yisint = 2
        elseif iy >= 0x3ff00000
            k = (iy >> 20) - 0x3ff
            if k > 20
                j = ly >> (52 - k)
                if ((j << (52 - k)) & 0xffffffff) == ly
                    yisint = 2 - (j & 1)
                end
            elseif ly == 0
                j = iy >> (20 - k)
                if (j << (20 - k)) == iy
                    yisint = 2 - (j & 1)
                end
            end
        end
    end
    if ly == 0
        if iy == 0x7ff00000
            ((ix - 0x3ff00000) | lx) == 0 && return y - y
            ix >= 0x3ff00000 && return hy >= 0 ? y : 0.0
            return hy < 0 ? -y : 0.0
        end
        if iy == 0x3ff00000
            hy < 0 && return x != 0 ? 1.0 / x : copysign(Inf, x)
            return x
        end
        hy == 0x40000000 && return x * x
        (hy == 0x3fe00000 && hx >= 0) && return sqrt(x)
    end
    ax = abs(x)
    if lx == 0 && (ix == 0x7ff00000 || ix == 0 || ix == 0x3ff00000)
        z = ax
        hy < 0 && (z = z != 0 ? 1.0 / z : Inf)
        if hx < 0
            if ((ix - 0x3ff00000) | yisint) == 0
                z = NaN
            elseif yisint == 1
                z = -z
            end
        end
        return z
    end
    n = (hx >> 31) + 1
    (n | yisint) == 0 && return NaN
    s = 1.0
    (n | (yisint - 1)) == 0 && (s = -1.0)
    local t1::Float64, t2::Float64
    if iy > 0x41e00000
        if iy > 0x43f00000
            ix <= 0x3fefffff && return hy < 0 ? Inf : 0.0
            ix >= 0x3ff00000 && return hy > 0 ? Inf : 0.0
        end
        ix < 0x3fefffff && return hy < 0 ? s * Inf : s * 0.0
        ix > 0x3ff00000 && return hy > 0 ? s * Inf : s * 0.0
        t = ax - 1.0
        w = (t * t) * (0.5 - t * (0.3333333333333333333333 - t * 0.25))
        u = _PW_IVLN2_H * t
        v = t * _PW_IVLN2_L - w * _PW_IVLN2
        t1 = _low_zero(u + v)
        t2 = v - (t1 - u)
    else
        n = 0
        if ix < 0x00100000
            ax *= _PW_TWO53
            n -= 53
            ix = _words(ax)[1]
        end
        n += (ix >> 20) - 0x3ff
        j = ix & 0x000fffff
        ix = j | 0x3ff00000
        if j <= 0x3988e
            k = 0
        elseif j < 0xbb67a
            k = 1
        else
            k = 0
            n += 1
            ix -= 0x00100000
        end
        ax = _from_words(ix, _words(ax)[2])
        u = ax - _PW_BP[k+1]
        v = 1.0 / (ax + _PW_BP[k+1])
        ss = u * v
        s_h = _low_zero(ss)
        t_h = _from_words(((ix >> 1) | 0x20000000) + 0x00080000 + (k << 18), 0)
        t_l = ax - (t_h - _PW_BP[k+1])
        s_l = v * ((u - s_h * t_h) - s_h * t_l)
        s2 = ss * ss
        r = s2 * s2 * (_PW_L1 + s2 * (_PW_L2 + s2 * (_PW_L3 + s2 * (_PW_L4 + s2 * (_PW_L5 + s2 * _PW_L6)))))
        r += s_l * (s_h + ss)
        s2 = s_h * s_h
        t_h = _low_zero(3.0 + s2 + r)
        t_l = r - ((t_h - 3.0) - s2)
        u = s_h * t_h
        v = s_l * t_h + t_l * ss
        p_h = _low_zero(u + v)
        p_l = v - (p_h - u)
        z_h = _PW_CP_H * p_h
        z_l = _PW_CP_L * p_h + p_l * _PW_CP + _PW_DP_L[k+1]
        t = Float64(n)
        t1 = _low_zero(((z_h + z_l) + _PW_DP_H[k+1]) + t)
        t2 = z_l - (((t1 - t) - _PW_DP_H[k+1]) - z_h)
    end
    y1 = _low_zero(y)
    p_l = (y - y1) * t1 + y * t2
    p_h = y1 * t1
    z = p_l + p_h
    j, i = _words(z)
    j = _signed32(j)
    if j >= 0x40900000
        ((j - 0x40900000) | i) != 0 && return s * Inf
        p_l + _PW_OVT > z - p_h && return s * Inf
    elseif (j & 0x7fffffff) >= 0x4090cc00
        ((j - _signed32(Int64(0xc090cc00))) | i) != 0 && return s * 0.0
        p_l <= z - p_h && return s * 0.0
    end
    i = j & 0x7fffffff
    k = (i >> 20) - 0x3ff
    n = 0
    if i > 0x3fe00000
        n = j + (0x00100000 >> (k + 1))
        k = ((n & 0x7fffffff) >> 20) - 0x3ff
        t = _from_words(n & ~(0x000fffff >> k), 0)
        n = ((n & 0x000fffff) | 0x00100000) >> (20 - k)
        j < 0 && (n = -n)
        p_h -= t
    end
    t = _low_zero(p_l + p_h)
    u = t * _PW_LG2_H
    v = (p_l - (t - p_h)) * _PW_LG2 + t * _PW_LG2_L
    z = u + v
    w = v - (z - u)
    t = z * z
    t1 = z - t * (_P1 + t * (_P2 + t * (_P3 + t * (_P4 + t * _P5))))
    r = (z * t1) / (t1 - 2.0) - (w + z * w)
    z = 1.0 - (r - z)
    j = _signed32(_words(z)[1])
    j += n << 20
    if (j >> 20) <= 0
        z = ldexp(z, n)
    else
        hi, lo = _words(z)
        z = _from_words(hi + (n << 20), lo)
    end
    return s * z
end

const _EXPM1_Q = (-3.33333333333331316428e-02, 1.58730158725481460165e-03, -7.93650757867487942473e-05,
                  4.00821782732936239552e-06, -2.01099218183624371326e-07)

@inline _bits(x::Float64) = reinterpret(UInt64, x)
@inline _from_bits(b::Integer) = reinterpret(Float64, UInt64(b & 0xffffffffffffffff))

"""`Math.log1p`, as V8 computes it."""
function js_log1p(x::Float64)
    hx = Int64(_bits(x) >> 32)
    (hx & 0x80000000) != 0 && (hx -= 4294967296)
    ax = hx & 0x7fffffff
    k = 1
    f = c = 0.0
    hu = 0
    if hx < 0x3fda827a
        if ax >= 0x3ff00000
            return x == -1.0 ? -Inf : NaN
        end
        if ax < 0x3e200000
            ax < 0x3c900000 && return x
            return x - x * x * 0.5
        end
        if hx > 0 || hx <= -1076707644
            k = 0
            f = x
            hu = 1
        end
    end
    hx >= 0x7ff00000 && return x + x
    if k != 0
        local u::Float64
        if hx < 0x43400000
            u = 1.0 + x
            hu = Int64(_bits(u) >> 32)
            k = (hu >> 20) - 1023
            c = k > 0 ? 1.0 - (u - x) : x - (u - 1.0)
            c /= u
        else
            u = x
            hu = Int64(_bits(u) >> 32)
            k = (hu >> 20) - 1023
            c = 0.0
        end
        hu &= 0x000fffff
        low = Int64(_bits(u) & 0xffffffff)
        if hu < 0x6a09e
            u = _from_bits(((hu | 0x3ff00000) << 32) | low)
        else
            k += 1
            u = _from_bits(((hu | 0x3fe00000) << 32) | low)
            hu = (0x00100000 - hu) >> 2
        end
        f = u - 1.0
    end
    hfsq = 0.5 * f * f
    dk = Float64(k)
    if hu == 0
        if f == 0.0
            k == 0 && return 0.0
            c += dk * _LN2_LO
            return dk * _LN2_HI + c
        end
        r = hfsq * (1.0 - 0.66666666666666666 * f)
        k == 0 && return f - r
        return dk * _LN2_HI - ((r - (dk * _LN2_LO + c)) - f)
    end
    s = f / (2.0 + f)
    z = s * s
    r = z * (_LG1 + z * (_LG2 + z * (_LG3 + z * (_LG4 + z * (_LG5 + z * (_LG6 + z * _LG7))))))
    k == 0 && return f - (hfsq - s * (hfsq + r))
    return dk * _LN2_HI - ((hfsq - (s * (hfsq + r) + (dk * _LN2_LO + c))) - f)
end

"""`Math.expm1`, as V8 computes it."""
function js_expm1(x::Float64)
    b = _bits(x)
    hx = Int64(b >> 32)
    xsb = hx & 0x80000000
    hx &= 0x7fffffff
    if hx >= 0x4043687a
        if hx >= 0x40862e42
            if hx >= 0x7ff00000
                ((hx & 0xfffff) | Int64(b & 0xffffffff)) != 0 && return x + x
                return xsb == 0 ? x : -1.0
            end
            x > 7.09782712893383973096e+02 && return Inf
        end
        xsb != 0 && return -1.0
    end
    c = 0.0
    local k::Int
    if hx > 0x3fd62e42
        local hi::Float64, lo::Float64
        if hx < 0x3ff0a2b2
            if xsb == 0
                hi = x - _LN2_HI
                lo = _LN2_LO
                k = 1
            else
                hi = x + _LN2_HI
                lo = -_LN2_LO
                k = -1
            end
        else
            k = trunc(Int, _INVLN2 * x + (xsb == 0 ? 0.5 : -0.5))
            t = Float64(k)
            hi = x - t * _LN2_HI
            lo = t * _LN2_LO
        end
        x = hi - lo
        c = (hi - x) - lo
    elseif hx < 0x3c900000
        return x
    else
        k = 0
    end
    q1, q2, q3, q4, q5 = _EXPM1_Q
    hfx = 0.5 * x
    hxs = x * hfx
    r1 = 1.0 + hxs * (q1 + hxs * (q2 + hxs * (q3 + hxs * (q4 + hxs * q5))))
    t = 3.0 - r1 * hfx
    e = hxs * ((r1 - t) / (6.0 - x * t))
    k == 0 && return x - (x * e - hxs)
    e = x * (e - c) - c
    e -= hxs
    k == -1 && return 0.5 * (x - e) - 0.5
    if k == 1
        x < -0.25 && return -2.0 * (e - (x + 0.5))
        return 1.0 + 2.0 * (x - e)
    end
    if k <= -2 || k > 56
        y = 1.0 - (e - x)
        y = k == 1024 ? y * 2.0 * 8.98846567431158e+307 : y * ldexp(1.0, k)
        return y - 1.0
    end
    if k < 20
        t = _from_bits((Int64(0x3ff00000) - (Int64(0x200000) >> k)) << 32)
        y = t - (e - x)
    else
        t = _from_bits(((Int64(0x3ff) - k) << 20) << 32)
        y = x - (e + t)
        y += 1.0
    end
    return y * ldexp(1.0, k)
end
