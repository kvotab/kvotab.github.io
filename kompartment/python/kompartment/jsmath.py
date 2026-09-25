"""V8's ``Math.exp``, ``Math.log``, ``Math.log10``, ``Math.log1p``,
``Math.expm1`` and ``**``, as the application's numbers come out of them.

V8 does not call the C library for these: it carries its own ports of fdlibm
(``src/base/ieee754.cc``), and they differ from the platform's ``libm`` in the
last bit for a fraction of arguments -- about one in ten for exp, one in 250
for log1p, one in 1,500 for log. Nothing a model computes depends on that bit,
but some things are compared with the application's to the last digit: the
output times (a time column that differs in its seventeenth digit makes two
result files that cannot be joined on time), and the statistics of a sample --
densities, quantiles, fits -- which the tests check bit for bit. Those use
these; the equations of a model use numpy.

``exp``, ``log``, ``log10``, ``log1p`` and ``expm1`` agree with V8 bit for bit
(checked on 100,000 arguments across their ranges); ``log_array`` and
``log1p_array`` are ``log`` and ``log1p`` over a numpy array, value for value.
``pow`` is fdlibm's, which V8 no longer uses unchanged: it agrees on about 96%
of arguments and is one unit in the last place off on the rest -- still closer
than the platform's ``pow``. It only places the points of a logarithmic series.

Pure Python (numpy only for the two array versions), so the statistics can use
it without the engine.
"""

from __future__ import annotations

import math
import struct

_LN2_HI = 6.93147180369123816490e-01
_LN2_LO = 1.90821492927058770002e-10
_TWO54 = 1.80143985094819840000e+16
_LG1 = 6.666666666666735130e-01
_LG2 = 3.999999999940941908e-01
_LG3 = 2.857142874366239149e-01
_LG4 = 2.222219843214978396e-01
_LG5 = 1.818357216161805012e-01
_LG6 = 1.531383769920937332e-01
_LG7 = 1.479819860511658591e-01

_O_THRESHOLD = 7.09782712893383973096e+02
_U_THRESHOLD = -7.45133219101941108420e+02
_LN2HI = (6.93147180369123816490e-01, -6.93147180369123816490e-01)
_LN2LO = (1.90821492927058770002e-10, -1.90821492927058770002e-10)
_HALF = (0.5, -0.5)
_INVLN2 = 1.44269504088896338700e+00
_P1 = 1.66666666666666019037e-01
_P2 = -2.77777777770155933842e-03
_P3 = 6.61375632143793436117e-05
_P4 = -1.65339022054652515390e-06
_P5 = 4.13813679705723846039e-08
_E = 2.718281828459045
_TWOM1000 = 9.33263618503218878990e-302
_TWO1023 = 8.988465674311579539e307

_IVLN10 = 4.34294481903251816668e-01
_LOG10_2HI = 3.01029995663611771306e-01
_LOG10_2LO = 3.69423907715893078616e-13


def _words(x: float):
    bits = struct.unpack('<Q', struct.pack('<d', x))[0]
    return (bits >> 32) & 0xFFFFFFFF, bits & 0xFFFFFFFF


def _from_words(hi: int, lo: int) -> float:
    return struct.unpack('<d', struct.pack('<Q', ((hi & 0xFFFFFFFF) << 32) | (lo & 0xFFFFFFFF)))[0]


def _signed(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def exp(x: float) -> float:
    """``Math.exp``."""
    x = float(x)
    hx, lx = _words(x)
    xsb = (hx >> 31) & 1
    hx &= 0x7FFFFFFF
    hi = lo = 0.0
    k = 0
    if hx >= 0x40862E42:
        if hx >= 0x7FF00000:
            if ((hx & 0xFFFFF) | lx) != 0:
                return x + x
            return x if xsb == 0 else 0.0
        if x > _O_THRESHOLD:
            return math.inf
        if x < _U_THRESHOLD:
            return 0.0
    if hx > 0x3FD62E42:
        if hx < 0x3FF0A2B2:
            if x == 1.0:
                return _E
            hi = x - _LN2HI[xsb]
            lo = _LN2LO[xsb]
            k = 1 - xsb - xsb
        else:
            k = int(_INVLN2 * x + _HALF[xsb])
            t = float(k)
            hi = x - t * _LN2HI[0]
            lo = t * _LN2LO[0]
        x = hi - lo
    elif hx < 0x3E300000:
        return 1.0 + x
    else:
        k = 0
    t = x * x
    if k >= -1021:
        twopk = _from_words(0x3FF00000 + ((k << 20) & 0xFFFFFFFF), 0)
    else:
        twopk = _from_words(0x3FF00000 + (((k + 1000) << 20) & 0xFFFFFFFF), 0)
    c = x - t * (_P1 + t * (_P2 + t * (_P3 + t * (_P4 + t * _P5))))
    if k == 0:
        return 1.0 - ((x * c) / (c - 2.0) - x)
    y = 1.0 - ((lo - (x * c) / (2.0 - c)) - hi)
    if k >= -1021:
        if k == 1024:
            return y * 2.0 * _TWO1023
        return y * twopk
    return y * twopk * _TWOM1000


def log(x: float) -> float:
    """``Math.log``."""
    x = float(x)
    hx, lx = _words(x)
    hx = _signed(hx)
    k = 0
    if hx < 0x00100000:
        if ((hx & 0x7FFFFFFF) | lx) == 0:
            return -math.inf
        if hx < 0:
            return math.nan
        k -= 54
        x *= _TWO54
        hx = _signed(_words(x)[0])
    if hx >= 0x7FF00000:
        return x + x
    k += (hx >> 20) - 1023
    hx &= 0x000FFFFF
    i = (hx + 0x95F64) & 0x100000
    x = _from_words(hx | (i ^ 0x3FF00000), _words(x)[1])
    k += i >> 20
    f = x - 1.0
    if (0x000FFFFF & (2 + hx)) < 3:
        if f == 0.0:
            if k == 0:
                return 0.0
            dk = float(k)
            return dk * _LN2_HI + dk * _LN2_LO
        r = f * f * (0.5 - 0.33333333333333333 * f)
        if k == 0:
            return f - r
        dk = float(k)
        return dk * _LN2_HI - ((r - dk * _LN2_LO) - f)
    s = f / (2.0 + f)
    dk = float(k)
    z = s * s
    i = hx - 0x6147A
    w = z * z
    j = 0x6B851 - hx
    t1 = w * (_LG2 + w * (_LG4 + w * _LG6))
    t2 = z * (_LG1 + w * (_LG3 + w * (_LG5 + w * _LG7)))
    i |= j
    r = t2 + t1
    if i > 0:
        hfsq = 0.5 * f * f
        if k == 0:
            return f - (hfsq - s * (hfsq + r))
        return dk * _LN2_HI - ((hfsq - (s * (hfsq + r) + dk * _LN2_LO)) - f)
    if k == 0:
        return f - s * (f - r)
    return dk * _LN2_HI - ((s * (f - r) - dk * _LN2_LO) - f)


def log10(x: float) -> float:
    """``Math.log10``."""
    x = float(x)
    hx, lx = _words(x)
    hx = _signed(hx)
    k = 0
    if hx < 0x00100000:
        if ((hx & 0x7FFFFFFF) | lx) == 0:
            return -math.inf
        if hx < 0:
            return math.nan
        k -= 54
        x *= _TWO54
        hx, lx = _words(x)
        hx = _signed(hx)
    if hx >= 0x7FF00000:
        return x + x
    if hx == 0x3FF00000 and lx == 0:
        return 0.0
    k += (hx >> 20) - 1023
    i = 1 if k < 0 else 0
    hx = (hx & 0x000FFFFF) | ((0x3FF - i) << 20)
    y = float(k + i)
    x = _from_words(hx, lx)
    z = y * _LOG10_2LO + _IVLN10 * log(x)
    return z + y * _LOG10_2HI


_PW_BP = (1.0, 1.5)
_PW_DP_H = (0.0, 5.84962487220764160156e-01)
_PW_DP_L = (0.0, 1.35003920212974897128e-08)
_PW_TWO53 = 9007199254740992.0
_PW_L1 = 5.99999999999994648725e-01
_PW_L2 = 4.28571428578550184252e-01
_PW_L3 = 3.33333329818377432918e-01
_PW_L4 = 2.72728123808534006489e-01
_PW_L5 = 2.30660745775561754067e-01
_PW_L6 = 2.06975017800338417784e-01
_PW_LG2 = 6.93147180559945286227e-01
_PW_LG2_H = 6.93147182464599609375e-01
_PW_LG2_L = -1.90465429995776804525e-09
_PW_OVT = 8.0085662595372944372e-17
_PW_CP = 9.61796693925975554329e-01
_PW_CP_H = 9.61796700954437255859e-01
_PW_CP_L = -7.02846165095275826516e-09
_PW_IVLN2 = 1.44269504088896338700e+00
_PW_IVLN2_H = 1.44269502162933349609e+00
_PW_IVLN2_L = 1.92596299112661746887e-08


def _low_zero(x: float) -> float:
    return _from_words(_words(x)[0], 0)


def _scalbn(x: float, n: int) -> float:
    return math.ldexp(x, n)


def pow(x: float, y: float) -> float:  # noqa: A001 - the name is the point
    """``Math.pow`` (and ``**``)."""
    x = float(x)
    y = float(y)
    if math.isnan(y):
        return math.nan
    if abs(x) == 1.0 and math.isinf(y):
        return math.nan
    hx, lx = _words(x)
    hy, ly = _words(y)
    hx = _signed(hx)
    hy = _signed(hy)
    ix = hx & 0x7FFFFFFF
    iy = hy & 0x7FFFFFFF
    if (iy | ly) == 0:
        return 1.0
    if ix > 0x7FF00000 or (ix == 0x7FF00000 and lx != 0) or iy > 0x7FF00000 or (iy == 0x7FF00000 and ly != 0):
        return x + y
    yisint = 0
    if hx < 0:
        if iy >= 0x43400000:
            yisint = 2
        elif iy >= 0x3FF00000:
            k = (iy >> 20) - 0x3FF
            if k > 20:
                j = ly >> (52 - k)
                if ((j << (52 - k)) & 0xFFFFFFFF) == ly:
                    yisint = 2 - (j & 1)
            elif ly == 0:
                j = iy >> (20 - k)
                if (j << (20 - k)) == iy:
                    yisint = 2 - (j & 1)
    if ly == 0:
        if iy == 0x7FF00000:
            if ((ix - 0x3FF00000) | lx) == 0:
                return y - y
            if ix >= 0x3FF00000:
                return y if hy >= 0 else 0.0
            return -y if hy < 0 else 0.0
        if iy == 0x3FF00000:
            if hy < 0:
                return 1.0 / x if x != 0 else math.copysign(math.inf, x)
            return x
        if hy == 0x40000000:
            return x * x
        if hy == 0x3FE00000 and hx >= 0:
            return math.sqrt(x)
    ax = abs(x)
    if lx == 0 and (ix == 0x7FF00000 or ix == 0 or ix == 0x3FF00000):
        z = ax
        if hy < 0:
            z = 1.0 / z if z != 0 else math.inf
        if hx < 0:
            if ((ix - 0x3FF00000) | yisint) == 0:
                z = math.nan
            elif yisint == 1:
                z = -z
        return z
    n = (hx >> 31) + 1
    if (n | yisint) == 0:
        return math.nan
    s = 1.0
    if (n | (yisint - 1)) == 0:
        s = -1.0
    if iy > 0x41E00000:
        if iy > 0x43F00000:
            if ix <= 0x3FEFFFFF:
                return math.inf if hy < 0 else 0.0
            if ix >= 0x3FF00000:
                return math.inf if hy > 0 else 0.0
        if ix < 0x3FEFFFFF:
            return s * math.inf if hy < 0 else s * 0.0
        if ix > 0x3FF00000:
            return s * math.inf if hy > 0 else s * 0.0
        t = ax - 1.0
        w = (t * t) * (0.5 - t * (0.3333333333333333333333 - t * 0.25))
        u = _PW_IVLN2_H * t
        v = t * _PW_IVLN2_L - w * _PW_IVLN2
        t1 = _low_zero(u + v)
        t2 = v - (t1 - u)
    else:
        n = 0
        if ix < 0x00100000:
            ax *= _PW_TWO53
            n -= 53
            ix = _words(ax)[0]
        n += (ix >> 20) - 0x3FF
        j = ix & 0x000FFFFF
        ix = j | 0x3FF00000
        if j <= 0x3988E:
            k = 0
        elif j < 0xBB67A:
            k = 1
        else:
            k = 0
            n += 1
            ix -= 0x00100000
        ax = _from_words(ix, _words(ax)[1])
        u = ax - _PW_BP[k]
        v = 1.0 / (ax + _PW_BP[k])
        ss = u * v
        s_h = _low_zero(ss)
        t_h = _from_words(((ix >> 1) | 0x20000000) + 0x00080000 + (k << 18), 0)
        t_l = ax - (t_h - _PW_BP[k])
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
        z_l = _PW_CP_L * p_h + p_l * _PW_CP + _PW_DP_L[k]
        t = float(n)
        t1 = _low_zero(((z_h + z_l) + _PW_DP_H[k]) + t)
        t2 = z_l - (((t1 - t) - _PW_DP_H[k]) - z_h)
    y1 = _low_zero(y)
    p_l = (y - y1) * t1 + y * t2
    p_h = y1 * t1
    z = p_l + p_h
    j, i = _words(z)
    j = _signed(j)
    if j >= 0x40900000:
        if ((j - 0x40900000) | i) != 0:
            return s * math.inf
        if p_l + _PW_OVT > z - p_h:
            return s * math.inf
    elif (j & 0x7FFFFFFF) >= 0x4090CC00:
        if ((j - _signed(0xC090CC00)) | i) != 0:
            return s * 0.0
        if p_l <= z - p_h:
            return s * 0.0
    i = j & 0x7FFFFFFF
    k = (i >> 20) - 0x3FF
    n = 0
    if i > 0x3FE00000:
        n = j + (0x00100000 >> (k + 1))
        k = ((n & 0x7FFFFFFF) >> 20) - 0x3FF
        t = _from_words(n & ~(0x000FFFFF >> k), 0)
        n = ((n & 0x000FFFFF) | 0x00100000) >> (20 - k)
        if j < 0:
            n = -n
        p_h -= t
    t = _low_zero(p_l + p_h)
    u = t * _PW_LG2_H
    v = (p_l - (t - p_h)) * _PW_LG2 + t * _PW_LG2_L
    z = u + v
    w = v - (z - u)
    t = z * z
    t1 = z - t * (_P1 + t * (_P2 + t * (_P3 + t * (_P4 + t * _P5))))
    r = (z * t1) / (t1 - 2.0) - (w + z * w)
    z = 1.0 - (r - z)
    j = _signed(_words(z)[0])
    j += n << 20
    if (j >> 20) <= 0:
        z = _scalbn(z, n)
    else:
        hi, lo = _words(z)
        z = _from_words(hi + (n << 20), lo)
    return s * z


# --- log1p, expm1, and log and log1p over arrays ---------------------------------------------------

_LG = (6.666666666666735130e-01, 3.999999999940941908e-01, 2.857142874366239149e-01,
       2.222219843214978396e-01, 1.818357216161805012e-01, 1.531383769920937332e-01,
       1.479819860511658591e-01)
_EXPM1_Q = (-3.33333333333331316428e-02, 1.58730158725481460165e-03, -7.93650757867487942473e-05,
            4.00821782732936239552e-06, -2.01099218183624371326e-07)

_F64 = struct.Struct('<d')
_U64 = struct.Struct('<Q')


def _bits(x: float) -> int:
    return _U64.unpack(_F64.pack(x))[0]


def _from_bits(b: int) -> float:
    return _F64.unpack(_U64.pack(b & 0xFFFFFFFFFFFFFFFF))[0]


def log1p(x: float) -> float:
    """``Math.log1p``, as V8 computes it."""
    x = float(x)
    hx = _bits(x) >> 32
    if hx & 0x80000000:
        hx -= 0x100000000
    ax = hx & 0x7FFFFFFF
    k = 1
    f = c = 0.0
    hu = 0
    if hx < 0x3FDA827A:  # 1+x < sqrt(2)+
        if ax >= 0x3FF00000:  # x <= -1.0
            return -math.inf if x == -1.0 else math.nan
        if ax < 0x3E200000:  # |x| < 2**-29
            if ax < 0x3C900000:  # |x| < 2**-54
                return x
            return x - x * x * 0.5
        if hx > 0 or hx <= -1076707644:  # (int32_t)0xbfd2bec4: sqrt(2)/2- <= 1+x < sqrt(2)+
            k = 0
            f = x
            hu = 1
    if hx >= 0x7FF00000:
        return x + x
    if k != 0:
        if hx < 0x43400000:
            u = 1.0 + x
            hu = _bits(u) >> 32
            k = (hu >> 20) - 1023
            c = 1.0 - (u - x) if k > 0 else x - (u - 1.0)  # the correction term
            c /= u
        else:
            u = x
            hu = _bits(u) >> 32
            k = (hu >> 20) - 1023
            c = 0.0
        hu &= 0x000FFFFF
        low = _bits(u) & 0xFFFFFFFF
        if hu < 0x6A09E:  # u ~< sqrt(2)
            u = _from_bits(((hu | 0x3FF00000) << 32) | low)
        else:
            k += 1
            u = _from_bits(((hu | 0x3FE00000) << 32) | low)
            hu = (0x00100000 - hu) >> 2
        f = u - 1.0
    hfsq = 0.5 * f * f
    dk = float(k)
    if hu == 0:  # |f| < 2**-20
        if f == 0.0:
            if k == 0:
                return 0.0
            c += dk * _LN2_LO
            return dk * _LN2_HI + c
        r = hfsq * (1.0 - 0.66666666666666666 * f)
        if k == 0:
            return f - r
        return dk * _LN2_HI - ((r - (dk * _LN2_LO + c)) - f)
    lp1, lp2, lp3, lp4, lp5, lp6, lp7 = _LG
    s = f / (2.0 + f)
    z = s * s
    r = z * (lp1 + z * (lp2 + z * (lp3 + z * (lp4 + z * (lp5 + z * (lp6 + z * lp7))))))
    if k == 0:
        return f - (hfsq - s * (hfsq + r))
    return dk * _LN2_HI - ((hfsq - (s * (hfsq + r) + (dk * _LN2_LO + c))) - f)


def expm1(x: float) -> float:
    """``Math.expm1``, as V8 computes it."""
    x = float(x)
    b = _bits(x)
    hx = b >> 32
    xsb = hx & 0x80000000
    hx &= 0x7FFFFFFF
    if hx >= 0x4043687A:  # |x| >= 56 ln2
        if hx >= 0x40862E42:  # |x| >= 709.78...
            if hx >= 0x7FF00000:
                if ((hx & 0xFFFFF) | (b & 0xFFFFFFFF)) != 0:
                    return x + x
                return x if xsb == 0 else -1.0
            if x > 7.09782712893383973096e+02:
                return math.inf
        if xsb != 0:  # x < -56 ln2
            return -1.0
    c = 0.0
    if hx > 0x3FD62E42:  # |x| > 0.5 ln2
        if hx < 0x3FF0A2B2:  # and |x| < 1.5 ln2
            if xsb == 0:
                hi = x - _LN2_HI
                lo = _LN2_LO
                k = 1
            else:
                hi = x + _LN2_HI
                lo = -_LN2_LO
                k = -1
        else:
            k = int(_INVLN2 * x + (0.5 if xsb == 0 else -0.5))
            t = float(k)
            hi = x - t * _LN2_HI
            lo = t * _LN2_LO
        x = hi - lo
        c = (hi - x) - lo
    elif hx < 0x3C900000:  # |x| < 2**-54
        return x
    else:
        k = 0
    q1, q2, q3, q4, q5 = _EXPM1_Q
    hfx = 0.5 * x
    hxs = x * hfx
    r1 = 1.0 + hxs * (q1 + hxs * (q2 + hxs * (q3 + hxs * (q4 + hxs * q5))))
    t = 3.0 - r1 * hfx
    e = hxs * ((r1 - t) / (6.0 - x * t))
    if k == 0:
        return x - (x * e - hxs)
    e = x * (e - c) - c
    e -= hxs
    if k == -1:
        return 0.5 * (x - e) - 0.5
    if k == 1:
        if x < -0.25:
            return -2.0 * (e - (x + 0.5))
        return 1.0 + 2.0 * (x - e)
    if k <= -2 or k > 56:
        y = 1.0 - (e - x)
        if k == 1024:
            y = y * 2.0 * 8.98846567431158e+307
        else:
            y = y * math.ldexp(1.0, k)
        return y - 1.0
    if k < 20:
        t = _from_bits((0x3FF00000 - (0x200000 >> k)) << 32)  # 1 - 2**-k
        y = t - (e - x)
    else:
        t = _from_bits(((0x3FF - k) << 20) << 32)  # 2**-k
        y = x - (e + t)
        y += 1.0
    return y * math.ldexp(1.0, k)


def log_array(x: Any) -> Any:
    """``Math.log`` over an array, as V8 computes it; a new float64 array (numpy)."""
    import numpy as np
    x = np.array(x, dtype=np.float64)
    with np.errstate(all='ignore'):
        b = x.view(np.uint64)
        hx = (b >> np.uint64(32)).astype(np.int64)
        hx = np.where(hx >= 0x80000000, hx - 0x100000000, hx)
        lx = (b & np.uint64(0xFFFFFFFF)).astype(np.int64)
        k = np.zeros(x.shape, dtype=np.int64)
        tiny = hx < 0x00100000
        zero = tiny & (((hx & 0x7FFFFFFF) | lx) == 0)
        neg = tiny & ~zero & (hx < 0)
        sub = tiny & ~zero & ~neg
        xw = x.copy()
        if sub.any():
            xs = xw[sub] * _TWO54
            xw[sub] = xs
            k[sub] -= 54
            bs = xs.view(np.uint64)
            hx[sub] = (bs >> np.uint64(32)).astype(np.int64)
            lx[sub] = (bs & np.uint64(0xFFFFFFFF)).astype(np.int64)
        special = hx >= 0x7FF00000
        k = k + (hx >> 20) - 1023
        hm = hx & 0x000FFFFF
        i = (hm + 0x95F64) & 0x100000
        xn = (((hm | (i ^ 0x3FF00000)) << 32) | lx).astype(np.uint64).view(np.float64)
        k = k + (i >> 20)
        f = xn - 1.0
        dk = k.astype(np.float64)
        r1 = f * f * (0.5 - 0.33333333333333333 * f)
        small = np.where(f == 0.0,
                         np.where(k == 0, 0.0, dk * _LN2_HI + dk * _LN2_LO),
                         np.where(k == 0, f - r1, dk * _LN2_HI - ((r1 - dk * _LN2_LO) - f)))
        lg1, lg2, lg3, lg4, lg5, lg6, lg7 = _LG
        s = f / (2.0 + f)
        z = s * s
        ii = hm - 0x6147A
        w = z * z
        j = 0x6B851 - hm
        t1 = w * (lg2 + w * (lg4 + w * lg6))
        t2 = z * (lg1 + w * (lg3 + w * (lg5 + w * lg7)))
        ii = ii | j
        r = t2 + t1
        hfsq = 0.5 * f * f
        above = np.where(k == 0, f - (hfsq - s * (hfsq + r)),
                         dk * _LN2_HI - ((hfsq - (s * (hfsq + r) + dk * _LN2_LO)) - f))
        below = np.where(k == 0, f - s * (f - r), dk * _LN2_HI - ((s * (f - r) - dk * _LN2_LO) - f))
        out = np.where((0x000FFFFF & (2 + hm)) < 3, small, np.where(ii > 0, above, below))
        out = np.where(special, xw + xw, out)
        out = np.where(zero, -np.inf, out)
        out = np.where(neg, np.nan, out)
    return out


def log1p_array(x: Any) -> Any:
    """``Math.log1p`` over an array, as V8 computes it; a new float64 array (numpy)."""
    import numpy as np
    x = np.array(x, dtype=np.float64)
    with np.errstate(all='ignore'):
        hx = (x.view(np.uint64) >> np.uint64(32)).astype(np.int64)
        hx = np.where(hx >= 0x80000000, hx - 0x100000000, hx)
        ax = hx & 0x7FFFFFFF
        low_half = hx < 0x3FDA827A
        at_most_m1 = low_half & (ax >= 0x3FF00000)
        tiny = low_half & ~at_most_m1 & (ax < 0x3E200000)
        k0 = low_half & ~at_most_m1 & ~tiny & ((hx > 0) | (hx <= -1076707644))
        special = ~low_half & (hx >= 0x7FF00000)
        big = hx >= 0x43400000
        u = np.where(big, x, 1.0 + x)
        ub = u.view(np.uint64)
        hu = (ub >> np.uint64(32)).astype(np.int64)
        kk = (hu >> 20) - 1023
        c = np.where(big, 0.0, np.where(kk > 0, 1.0 - (u - x), x - (u - 1.0)) / u)
        hu = hu & 0x000FFFFF
        lowu = (ub & np.uint64(0xFFFFFFFF)).astype(np.int64)
        norm = hu < 0x6A09E
        un = np.where(norm, ((hu | 0x3FF00000) << 32) | lowu,
                      ((hu | 0x3FE00000) << 32) | lowu).astype(np.uint64).view(np.float64)
        kk = np.where(norm, kk, kk + 1)
        hu = np.where(norm, hu, (0x00100000 - hu) >> 2)
        f = np.where(k0, x, un - 1.0)
        k = np.where(k0, 0, kk)
        hu = np.where(k0, 1, hu)
        c = np.where(k0, 0.0, c)
        hfsq = 0.5 * f * f
        dk = k.astype(np.float64)
        r0 = hfsq * (1.0 - 0.66666666666666666 * f)
        flat = np.where(f == 0.0,
                        np.where(k == 0, 0.0, dk * _LN2_HI + (c + dk * _LN2_LO)),
                        np.where(k == 0, f - r0, dk * _LN2_HI - ((r0 - (dk * _LN2_LO + c)) - f)))
        lp1, lp2, lp3, lp4, lp5, lp6, lp7 = _LG
        s = f / (2.0 + f)
        z = s * s
        r = z * (lp1 + z * (lp2 + z * (lp3 + z * (lp4 + z * (lp5 + z * (lp6 + z * lp7))))))
        general = np.where(k == 0, f - (hfsq - s * (hfsq + r)),
                           dk * _LN2_HI - ((hfsq - (s * (hfsq + r) + (dk * _LN2_LO + c))) - f))
        out = np.where(hu == 0, flat, general)
        out = np.where(special, x + x, out)
        out = np.where(tiny, np.where(ax < 0x3C900000, x, x - x * x * 0.5), out)
        out = np.where(at_most_m1, np.where(x == -1.0, -np.inf, np.nan), out)
    return out
