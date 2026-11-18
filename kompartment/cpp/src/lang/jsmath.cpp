#include "lang/jsmath.hpp"

#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>

namespace kompartment {

namespace {

const double LN2_HI = 6.93147180369123816490e-01;
const double LN2_LO = 1.90821492927058770002e-10;
const double TWO54 = 1.80143985094819840000e+16;
const double LG1 = 6.666666666666735130e-01;
const double LG2 = 3.999999999940941908e-01;
const double LG3 = 2.857142874366239149e-01;
const double LG4 = 2.222219843214978396e-01;
const double LG5 = 1.818357216161805012e-01;
const double LG6 = 1.531383769920937332e-01;
const double LG7 = 1.479819860511658591e-01;
const double O_THRESHOLD = 7.09782712893383973096e+02;
const double U_THRESHOLD = -7.45133219101941108420e+02;
const double LN2HI[2] = {6.93147180369123816490e-01, -6.93147180369123816490e-01};
const double LN2LO[2] = {1.90821492927058770002e-10, -1.90821492927058770002e-10};
const double HALF[2] = {0.5, -0.5};
const double INVLN2 = 1.44269504088896338700e+00;
const double P1 = 1.66666666666666019037e-01;
const double P2 = -2.77777777770155933842e-03;
const double P3 = 6.61375632143793436117e-05;
const double P4 = -1.65339022054652515390e-06;
const double P5 = 4.13813679705723846039e-08;
const double E = 2.718281828459045;
const double TWOM1000 = 9.33263618503218878990e-302;
const double TWO1023 = 8.988465674311579539e307;
const double IVLN10 = 4.34294481903251816668e-01;
const double LOG10_2HI = 3.01029995663611771306e-01;
const double LOG10_2LO = 3.69423907715893078616e-13;
const double INF = std::numeric_limits<double>::infinity();
const double NaN = std::numeric_limits<double>::quiet_NaN();

inline std::uint64_t bits(double x) {
    std::uint64_t b;
    std::memcpy(&b, &x, 8);
    return b;
}
inline double from_bits(std::uint64_t b) {
    double x;
    std::memcpy(&x, &b, 8);
    return x;
}
// The high and low words, as signed 64-bit integers holding 32 unsigned bits each.
inline void words(double x, std::int64_t& hi, std::int64_t& lo) {
    std::uint64_t b = bits(x);
    hi = static_cast<std::int64_t>((b >> 32) & 0xffffffffu);
    lo = static_cast<std::int64_t>(b & 0xffffffffu);
}
inline std::int64_t high_word(double x) { return static_cast<std::int64_t>((bits(x) >> 32) & 0xffffffffu); }
inline std::int64_t low_word(double x) { return static_cast<std::int64_t>(bits(x) & 0xffffffffu); }
inline double from_words(std::int64_t hi, std::int64_t lo) {
    return from_bits((static_cast<std::uint64_t>(hi & 0xffffffff) << 32) | static_cast<std::uint64_t>(lo & 0xffffffff));
}
inline std::int64_t signed32(std::int64_t v) {
    v &= 0xffffffff;
    return (v & 0x80000000) != 0 ? v - 4294967296LL : v;
}
inline double low_zero(double x) { return from_words(high_word(x), 0); }

}  // namespace

double js_exp(double x) {
    std::int64_t hx, lx;
    words(x, hx, lx);
    std::int64_t xsb = (hx >> 31) & 1;
    hx &= 0x7fffffff;
    double hi = 0.0, lo = 0.0;
    std::int64_t k = 0;
    if (hx >= 0x40862e42) {
        if (hx >= 0x7ff00000) {
            if (((hx & 0xfffff) | lx) != 0) return x + x;
            return xsb == 0 ? x : 0.0;
        }
        if (x > O_THRESHOLD) return INF;
        if (x < U_THRESHOLD) return 0.0;
    }
    if (hx > 0x3fd62e42) {
        if (hx < 0x3ff0a2b2) {
            if (x == 1.0) return E;
            hi = x - LN2HI[xsb];
            lo = LN2LO[xsb];
            k = 1 - xsb - xsb;
        } else {
            k = static_cast<std::int64_t>(INVLN2 * x + HALF[xsb]);
            double t = static_cast<double>(k);
            hi = x - t * LN2HI[0];
            lo = t * LN2LO[0];
        }
        x = hi - lo;
    } else if (hx < 0x3e300000) {
        return 1.0 + x;
    } else {
        k = 0;
    }
    double t = x * x;
    double twopk = k >= -1021 ? from_words(0x3ff00000 + ((k << 20) & 0xffffffff), 0)
                              : from_words(0x3ff00000 + (((k + 1000) << 20) & 0xffffffff), 0);
    double c = x - t * (P1 + t * (P2 + t * (P3 + t * (P4 + t * P5))));
    if (k == 0) return 1.0 - ((x * c) / (c - 2.0) - x);
    double y = 1.0 - ((lo - (x * c) / (2.0 - c)) - hi);
    if (k >= -1021) {
        if (k == 1024) return y * 2.0 * TWO1023;
        return y * twopk;
    }
    return y * twopk * TWOM1000;
}

double js_log(double x) {
    std::int64_t hx, lx;
    words(x, hx, lx);
    hx = signed32(hx);
    std::int64_t k = 0;
    if (hx < 0x00100000) {
        if (((hx & 0x7fffffff) | lx) == 0) return -INF;
        if (hx < 0) return NaN;
        k -= 54;
        x *= TWO54;
        hx = signed32(high_word(x));
    }
    if (hx >= 0x7ff00000) return x + x;
    k += (hx >> 20) - 1023;
    hx &= 0x000fffff;
    std::int64_t i = (hx + 0x95f64) & 0x100000;
    x = from_words(hx | (i ^ 0x3ff00000), low_word(x));
    k += i >> 20;
    double f = x - 1.0;
    if ((0x000fffff & (2 + hx)) < 3) {
        if (f == 0.0) {
            if (k == 0) return 0.0;
            double dk = static_cast<double>(k);
            return dk * LN2_HI + dk * LN2_LO;
        }
        double r = f * f * (0.5 - 0.33333333333333333 * f);
        if (k == 0) return f - r;
        double dk = static_cast<double>(k);
        return dk * LN2_HI - ((r - dk * LN2_LO) - f);
    }
    double s = f / (2.0 + f);
    double dk = static_cast<double>(k);
    double z = s * s;
    i = hx - 0x6147a;
    double w = z * z;
    std::int64_t j = 0x6b851 - hx;
    double t1 = w * (LG2 + w * (LG4 + w * LG6));
    double t2 = z * (LG1 + w * (LG3 + w * (LG5 + w * LG7)));
    i |= j;
    double r = t2 + t1;
    if (i > 0) {
        double hfsq = 0.5 * f * f;
        if (k == 0) return f - (hfsq - s * (hfsq + r));
        return dk * LN2_HI - ((hfsq - (s * (hfsq + r) + dk * LN2_LO)) - f);
    }
    if (k == 0) return f - s * (f - r);
    return dk * LN2_HI - ((s * (f - r) - dk * LN2_LO) - f);
}

double js_log10(double x) {
    std::int64_t hx, lx;
    words(x, hx, lx);
    hx = signed32(hx);
    std::int64_t k = 0;
    if (hx < 0x00100000) {
        if (((hx & 0x7fffffff) | lx) == 0) return -INF;
        if (hx < 0) return NaN;
        k -= 54;
        x *= TWO54;
        words(x, hx, lx);
        hx = signed32(hx);
    }
    if (hx >= 0x7ff00000) return x + x;
    if (hx == 0x3ff00000 && lx == 0) return 0.0;
    k += (hx >> 20) - 1023;
    std::int64_t i = k < 0 ? 1 : 0;
    hx = (hx & 0x000fffff) | ((0x3ff - i) << 20);
    double y = static_cast<double>(k + i);
    x = from_words(hx, lx);
    double z = y * LOG10_2LO + IVLN10 * js_log(x);
    return z + y * LOG10_2HI;
}

namespace {
const double PW_BP[2] = {1.0, 1.5};
const double PW_DP_H[2] = {0.0, 5.84962487220764160156e-01};
const double PW_DP_L[2] = {0.0, 1.35003920212974897128e-08};
const double PW_TWO53 = 9007199254740992.0;
const double PW_L1 = 5.99999999999994648725e-01;
const double PW_L2 = 4.28571428578550184252e-01;
const double PW_L3 = 3.33333329818377432918e-01;
const double PW_L4 = 2.72728123808534006489e-01;
const double PW_L5 = 2.30660745775561754067e-01;
const double PW_L6 = 2.06975017800338417784e-01;
const double PW_LG2 = 6.93147180559945286227e-01;
const double PW_LG2_H = 6.93147182464599609375e-01;
const double PW_LG2_L = -1.90465429995776804525e-09;
const double PW_OVT = 8.0085662595372944372e-17;
const double PW_CP = 9.61796693925975554329e-01;
const double PW_CP_H = 9.61796700954437255859e-01;
const double PW_CP_L = -7.02846165095275826516e-09;
const double PW_IVLN2 = 1.44269504088896338700e+00;
const double PW_IVLN2_H = 1.44269502162933349609e+00;
const double PW_IVLN2_L = 1.92596299112661746887e-08;
}  // namespace

double js_pow(double x, double y) {
    if (std::isnan(y)) return NaN;
    if (std::fabs(x) == 1.0 && std::isinf(y)) return NaN;
    std::int64_t hx, lx, hy, ly;
    words(x, hx, lx);
    words(y, hy, ly);
    hx = signed32(hx);
    hy = signed32(hy);
    std::int64_t ix = hx & 0x7fffffff;
    std::int64_t iy = hy & 0x7fffffff;
    if ((iy | ly) == 0) return 1.0;
    if (ix > 0x7ff00000 || (ix == 0x7ff00000 && lx != 0) || iy > 0x7ff00000 || (iy == 0x7ff00000 && ly != 0)) return x + y;
    std::int64_t yisint = 0;
    if (hx < 0) {
        if (iy >= 0x43400000) {
            yisint = 2;
        } else if (iy >= 0x3ff00000) {
            std::int64_t k = (iy >> 20) - 0x3ff;
            if (k > 20) {
                std::int64_t j = ly >> (52 - k);
                if (((j << (52 - k)) & 0xffffffff) == ly) yisint = 2 - (j & 1);
            } else if (ly == 0) {
                std::int64_t j = iy >> (20 - k);
                if ((j << (20 - k)) == iy) yisint = 2 - (j & 1);
            }
        }
    }
    if (ly == 0) {
        if (iy == 0x7ff00000) {
            if (((ix - 0x3ff00000) | lx) == 0) return y - y;
            if (ix >= 0x3ff00000) return hy >= 0 ? y : 0.0;
            return hy < 0 ? -y : 0.0;
        }
        if (iy == 0x3ff00000) {
            if (hy < 0) return x != 0 ? 1.0 / x : std::copysign(INF, x);
            return x;
        }
        if (hy == 0x40000000) return x * x;
        if (hy == 0x3fe00000 && hx >= 0) return std::sqrt(x);
    }
    double ax = std::fabs(x);
    if (lx == 0 && (ix == 0x7ff00000 || ix == 0 || ix == 0x3ff00000)) {
        double z = ax;
        if (hy < 0) z = z != 0 ? 1.0 / z : INF;
        if (hx < 0) {
            if (((ix - 0x3ff00000) | yisint) == 0) z = NaN;
            else if (yisint == 1) z = -z;
        }
        return z;
    }
    std::int64_t n = (hx >> 31) + 1;
    if ((n | yisint) == 0) return NaN;
    double s = 1.0;
    if ((n | (yisint - 1)) == 0) s = -1.0;
    double t1, t2;
    if (iy > 0x41e00000) {
        if (iy > 0x43f00000) {
            if (ix <= 0x3fefffff) return hy < 0 ? INF : 0.0;
            if (ix >= 0x3ff00000) return hy > 0 ? INF : 0.0;
        }
        if (ix < 0x3fefffff) return hy < 0 ? s * INF : s * 0.0;
        if (ix > 0x3ff00000) return hy > 0 ? s * INF : s * 0.0;
        double t = ax - 1.0;
        double w = (t * t) * (0.5 - t * (0.3333333333333333333333 - t * 0.25));
        double u = PW_IVLN2_H * t;
        double v = t * PW_IVLN2_L - w * PW_IVLN2;
        t1 = low_zero(u + v);
        t2 = v - (t1 - u);
    } else {
        n = 0;
        if (ix < 0x00100000) {
            ax *= PW_TWO53;
            n -= 53;
            ix = high_word(ax);
        }
        n += (ix >> 20) - 0x3ff;
        std::int64_t j = ix & 0x000fffff;
        ix = j | 0x3ff00000;
        std::int64_t k;
        if (j <= 0x3988e) {
            k = 0;
        } else if (j < 0xbb67a) {
            k = 1;
        } else {
            k = 0;
            n += 1;
            ix -= 0x00100000;
        }
        ax = from_words(ix, low_word(ax));
        double u = ax - PW_BP[k];
        double v = 1.0 / (ax + PW_BP[k]);
        double ss = u * v;
        double s_h = low_zero(ss);
        double t_h = from_words(((ix >> 1) | 0x20000000) + 0x00080000 + (k << 18), 0);
        double t_l = ax - (t_h - PW_BP[k]);
        double s_l = v * ((u - s_h * t_h) - s_h * t_l);
        double s2 = ss * ss;
        double r = s2 * s2 * (PW_L1 + s2 * (PW_L2 + s2 * (PW_L3 + s2 * (PW_L4 + s2 * (PW_L5 + s2 * PW_L6)))));
        r += s_l * (s_h + ss);
        s2 = s_h * s_h;
        t_h = low_zero(3.0 + s2 + r);
        t_l = r - ((t_h - 3.0) - s2);
        u = s_h * t_h;
        v = s_l * t_h + t_l * ss;
        double p_h = low_zero(u + v);
        double p_l = v - (p_h - u);
        double z_h = PW_CP_H * p_h;
        double z_l = PW_CP_L * p_h + p_l * PW_CP + PW_DP_L[k];
        double t = static_cast<double>(n);
        t1 = low_zero(((z_h + z_l) + PW_DP_H[k]) + t);
        t2 = z_l - (((t1 - t) - PW_DP_H[k]) - z_h);
    }
    double y1 = low_zero(y);
    double p_l = (y - y1) * t1 + y * t2;
    double p_h = y1 * t1;
    double z = p_l + p_h;
    std::int64_t j, i;
    words(z, j, i);
    j = signed32(j);
    if (j >= 0x40900000) {
        if (((j - 0x40900000) | i) != 0) return s * INF;
        if (p_l + PW_OVT > z - p_h) return s * INF;
    } else if ((j & 0x7fffffff) >= 0x4090cc00) {
        if (((j - signed32(0xc090cc00LL)) | i) != 0) return s * 0.0;
        if (p_l <= z - p_h) return s * 0.0;
    }
    i = j & 0x7fffffff;
    std::int64_t k = (i >> 20) - 0x3ff;
    n = 0;
    if (i > 0x3fe00000) {
        n = j + (0x00100000 >> (k + 1));
        k = ((n & 0x7fffffff) >> 20) - 0x3ff;
        double t = from_words(n & ~(static_cast<std::int64_t>(0x000fffff) >> k), 0);
        n = ((n & 0x000fffff) | 0x00100000) >> (20 - k);
        if (j < 0) n = -n;
        p_h -= t;
    }
    double t = low_zero(p_l + p_h);
    double u = t * PW_LG2_H;
    double v = (p_l - (t - p_h)) * PW_LG2 + t * PW_LG2_L;
    z = u + v;
    double w = v - (z - u);
    t = z * z;
    t1 = z - t * (P1 + t * (P2 + t * (P3 + t * (P4 + t * P5))));
    double r = (z * t1) / (t1 - 2.0) - (w + z * w);
    z = 1.0 - (r - z);
    j = signed32(high_word(z));
    j += n << 20;
    if ((j >> 20) <= 0) {
        z = std::ldexp(z, static_cast<int>(n));
    } else {
        std::int64_t hi, lo;
        words(z, hi, lo);
        z = from_words(hi + (n << 20), lo);
    }
    return s * z;
}

double js_log1p(double x) {
    std::int64_t hx = static_cast<std::int64_t>(bits(x) >> 32);
    if ((hx & 0x80000000) != 0) hx -= 4294967296LL;
    std::int64_t ax = hx & 0x7fffffff;
    std::int64_t k = 1;
    double f = 0.0, c = 0.0;
    std::int64_t hu = 0;
    if (hx < 0x3fda827a) {
        if (ax >= 0x3ff00000) return x == -1.0 ? -INF : NaN;
        if (ax < 0x3e200000) {
            if (ax < 0x3c900000) return x;
            return x - x * x * 0.5;
        }
        if (hx > 0 || hx <= -1076707644) {
            k = 0;
            f = x;
            hu = 1;
        }
    }
    if (hx >= 0x7ff00000) return x + x;
    if (k != 0) {
        double u;
        if (hx < 0x43400000) {
            u = 1.0 + x;
            hu = static_cast<std::int64_t>(bits(u) >> 32);
            k = (hu >> 20) - 1023;
            c = k > 0 ? 1.0 - (u - x) : x - (u - 1.0);
            c /= u;
        } else {
            u = x;
            hu = static_cast<std::int64_t>(bits(u) >> 32);
            k = (hu >> 20) - 1023;
            c = 0.0;
        }
        hu &= 0x000fffff;
        std::uint64_t low = bits(u) & 0xffffffffu;
        if (hu < 0x6a09e) {
            u = from_bits((static_cast<std::uint64_t>(hu | 0x3ff00000) << 32) | low);
        } else {
            k += 1;
            u = from_bits((static_cast<std::uint64_t>(hu | 0x3fe00000) << 32) | low);
            hu = (0x00100000 - hu) >> 2;
        }
        f = u - 1.0;
    }
    double hfsq = 0.5 * f * f;
    double dk = static_cast<double>(k);
    if (hu == 0) {
        if (f == 0.0) {
            if (k == 0) return 0.0;
            c += dk * LN2_LO;
            return dk * LN2_HI + c;
        }
        double r = hfsq * (1.0 - 0.66666666666666666 * f);
        if (k == 0) return f - r;
        return dk * LN2_HI - ((r - (dk * LN2_LO + c)) - f);
    }
    double s = f / (2.0 + f);
    double z = s * s;
    double r = z * (LG1 + z * (LG2 + z * (LG3 + z * (LG4 + z * (LG5 + z * (LG6 + z * LG7))))));
    if (k == 0) return f - (hfsq - s * (hfsq + r));
    return dk * LN2_HI - ((hfsq - (s * (hfsq + r) + (dk * LN2_LO + c))) - f);
}

double js_expm1(double x) {
    static const double Q[5] = {-3.33333333333331316428e-02, 1.58730158725481460165e-03, -7.93650757867487942473e-05,
                                4.00821782732936239552e-06, -2.01099218183624371326e-07};
    std::uint64_t b = bits(x);
    std::int64_t hx = static_cast<std::int64_t>(b >> 32);
    std::int64_t xsb = hx & 0x80000000;
    hx &= 0x7fffffff;
    if (hx >= 0x4043687a) {
        if (hx >= 0x40862e42) {
            if (hx >= 0x7ff00000) {
                if (((hx & 0xfffff) | static_cast<std::int64_t>(b & 0xffffffffu)) != 0) return x + x;
                return xsb == 0 ? x : -1.0;
            }
            if (x > 7.09782712893383973096e+02) return INF;
        }
        if (xsb != 0) return -1.0;
    }
    double c = 0.0;
    std::int64_t k;
    if (hx > 0x3fd62e42) {
        double hi, lo;
        if (hx < 0x3ff0a2b2) {
            if (xsb == 0) {
                hi = x - LN2_HI;
                lo = LN2_LO;
                k = 1;
            } else {
                hi = x + LN2_HI;
                lo = -LN2_LO;
                k = -1;
            }
        } else {
            k = static_cast<std::int64_t>(INVLN2 * x + (xsb == 0 ? 0.5 : -0.5));
            double t = static_cast<double>(k);
            hi = x - t * LN2_HI;
            lo = t * LN2_LO;
        }
        x = hi - lo;
        c = (hi - x) - lo;
    } else if (hx < 0x3c900000) {
        return x;
    } else {
        k = 0;
    }
    double hfx = 0.5 * x;
    double hxs = x * hfx;
    double r1 = 1.0 + hxs * (Q[0] + hxs * (Q[1] + hxs * (Q[2] + hxs * (Q[3] + hxs * Q[4]))));
    double t = 3.0 - r1 * hfx;
    double e = hxs * ((r1 - t) / (6.0 - x * t));
    if (k == 0) return x - (x * e - hxs);
    e = x * (e - c) - c;
    e -= hxs;
    if (k == -1) return 0.5 * (x - e) - 0.5;
    if (k == 1) {
        if (x < -0.25) return -2.0 * (e - (x + 0.5));
        return 1.0 + 2.0 * (x - e);
    }
    double y;
    if (k <= -2 || k > 56) {
        y = 1.0 - (e - x);
        y = k == 1024 ? y * 2.0 * 8.98846567431158e+307 : y * std::ldexp(1.0, static_cast<int>(k));
        return y - 1.0;
    }
    if (k < 20) {
        t = from_bits(static_cast<std::uint64_t>(static_cast<std::int64_t>(0x3ff00000) - (static_cast<std::int64_t>(0x200000) >> k)) << 32);
        y = t - (e - x);
    } else {
        t = from_bits(static_cast<std::uint64_t>((static_cast<std::int64_t>(0x3ff) - k) << 20) << 32);
        y = x - (e + t);
        y += 1.0;
    }
    return y * std::ldexp(1.0, static_cast<int>(k));
}

}  // namespace kompartment
