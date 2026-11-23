/**
 * exp, log, log10, log1p, expm1 and pow, computed here rather than by the
 * browser: the same numbers in every browser, every Node and on every
 * processor.
 *
 * `Math.exp` and its kin are not exact, and the standard does not say which
 * of the two nearest doubles they return. Each engine answers with its own
 * library, and the answers part in the last bit: Node 20, Node 26 and Chrome
 * 157 each round some arguments differently from the other two (Chrome's exp
 * one argument in twenty). Nothing a model computes depends on that bit, but
 * some numbers are compared to the last digit -- the output times, where a
 * time column that differs in its seventeenth digit makes two result files
 * that cannot be joined on time, and the statistics of a sample (densities,
 * quantiles, fits), which the engines reproduce bit for bit. Those go through
 * this module; the equations of a model, and the solvers, use `Math`.
 *
 * These are fdlibm's routines (Sun's freely distributable libm, which V8's
 * ieee754 ports and several C libraries descend from), step for step. JavaScript
 * rounds every operation as IEEE 754 binary64 says, with nothing fused, so the
 * same steps give the same bits wherever they run. The Python package carries
 * the same routines in python/kompartment/jsmath.py, and its tests check the
 * two against each other bit for bit.
 *
 * The answers keep JavaScript's rules where fdlibm's C differs: `pow(1, NaN)`
 * and `pow(±1, ±Infinity)` are NaN, as in JavaScript and unlike C, and
 * `pow(NaN, 0)` is 1 in both.
 */

// The two 32-bit halves of a double, read and written through one buffer.
// HI is the half with the sign and the exponent.
const F64 = new Float64Array(1);
const U32 = new Uint32Array(F64.buffer);
const I32 = new Int32Array(F64.buffer);
const HI = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1 ? 1 : 0;
const LO = 1 - HI;

/** The high word of a double, signed as fdlibm's int. */
const highOf = (x) => { F64[0] = x; return I32[HI]; };
/** The low word, unsigned. */
const lowOf = (x) => { F64[0] = x; return U32[LO]; };
/** A double from its two words; each is taken modulo 2**32. */
const fromWords = (hi, lo) => { U32[HI] = hi; U32[LO] = lo; return F64[0]; };
/** The double with the low word cleared. */
const lowZero = (x) => { F64[0] = x; U32[LO] = 0; return F64[0]; };

// --- exp -------------------------------------------------------------------

const O_THRESHOLD = 7.09782712893383973096e+02;
const U_THRESHOLD = -7.45133219101941108420e+02;
const LN2HI = [6.93147180369123816490e-01, -6.93147180369123816490e-01];
const LN2LO = [1.90821492927058770002e-10, -1.90821492927058770002e-10];
const HALF = [0.5, -0.5];
const INVLN2 = 1.44269504088896338700e+00;
const P1 = 1.66666666666666019037e-01;
const P2 = -2.77777777770155933842e-03;
const P3 = 6.61375632143793436117e-05;
const P4 = -1.65339022054652515390e-06;
const P5 = 4.13813679705723846039e-08;
const E = 2.718281828459045;
const TWOM1000 = 9.33263618503218878990e-302;
const TWO1023 = 8.988465674311579539e307;

/** e ** x. */
export function exp(x) {
	x = +x;
	F64[0] = x;
	let hx = U32[HI];
	const lx = U32[LO];
	const xsb = hx >>> 31;
	hx &= 0x7fffffff;
	let hi = 0;
	let lo = 0;
	let k = 0;
	if (hx >= 0x40862e42) {
		if (hx >= 0x7ff00000) {
			if (((hx & 0xfffff) | lx) !== 0) return x + x;
			return xsb === 0 ? x : 0;
		}
		if (x > O_THRESHOLD) return Infinity;
		if (x < U_THRESHOLD) return 0;
	}
	if (hx > 0x3fd62e42) {
		if (hx < 0x3ff0a2b2) {
			if (x === 1) return E;
			hi = x - LN2HI[xsb];
			lo = LN2LO[xsb];
			k = 1 - xsb - xsb;
		} else {
			k = Math.trunc(INVLN2 * x + HALF[xsb]);
			const t = k;
			hi = x - t * LN2HI[0];
			lo = t * LN2LO[0];
		}
		x = hi - lo;
	} else if (hx < 0x3e300000) {
		return 1 + x;
	} else {
		k = 0;
	}
	const t = x * x;
	const twopk = k >= -1021
		? fromWords(0x3ff00000 + (k << 20), 0)
		: fromWords(0x3ff00000 + ((k + 1000) << 20), 0);
	const c = x - t * (P1 + t * (P2 + t * (P3 + t * (P4 + t * P5))));
	if (k === 0) return 1 - ((x * c) / (c - 2) - x);
	const y = 1 - ((lo - (x * c) / (2 - c)) - hi);
	if (k >= -1021) {
		if (k === 1024) return y * 2 * TWO1023;
		return y * twopk;
	}
	return y * twopk * TWOM1000;
}

// --- log and log10 -----------------------------------------------------------

const LN2_HI = 6.93147180369123816490e-01;
const LN2_LO = 1.90821492927058770002e-10;
const TWO54 = 1.80143985094819840000e+16;
const LG1 = 6.666666666666735130e-01;
const LG2 = 3.999999999940941908e-01;
const LG3 = 2.857142874366239149e-01;
const LG4 = 2.222219843214978396e-01;
const LG5 = 1.818357216161805012e-01;
const LG6 = 1.531383769920937332e-01;
const LG7 = 1.479819860511658591e-01;
const IVLN10 = 4.34294481903251816668e-01;
const LOG10_2HI = 3.01029995663611771306e-01;
const LOG10_2LO = 3.69423907715893078616e-13;

/** The natural logarithm. */
export function log(x) {
	x = +x;
	F64[0] = x;
	let hx = I32[HI];
	const lx = U32[LO];
	let k = 0;
	if (hx < 0x00100000) {
		if (((hx & 0x7fffffff) | lx) === 0) return -Infinity;
		if (hx < 0) return NaN;
		k -= 54;
		x *= TWO54;
		hx = highOf(x);
	}
	if (hx >= 0x7ff00000) return x + x;
	k += (hx >> 20) - 1023;
	hx &= 0x000fffff;
	let i = (hx + 0x95f64) & 0x100000;
	x = fromWords(hx | (i ^ 0x3ff00000), lowOf(x));
	k += i >> 20;
	const f = x - 1;
	if ((0x000fffff & (2 + hx)) < 3) {
		if (f === 0) {
			if (k === 0) return 0;
			const dk = k;
			return dk * LN2_HI + dk * LN2_LO;
		}
		const r = f * f * (0.5 - 0.33333333333333333 * f);
		if (k === 0) return f - r;
		const dk = k;
		return dk * LN2_HI - ((r - dk * LN2_LO) - f);
	}
	const s = f / (2 + f);
	const dk = k;
	const z = s * s;
	i = hx - 0x6147a;
	const w = z * z;
	const j = 0x6b851 - hx;
	const t1 = w * (LG2 + w * (LG4 + w * LG6));
	const t2 = z * (LG1 + w * (LG3 + w * (LG5 + w * LG7)));
	i |= j;
	const r = t2 + t1;
	if (i > 0) {
		const hfsq = 0.5 * f * f;
		if (k === 0) return f - (hfsq - s * (hfsq + r));
		return dk * LN2_HI - ((hfsq - (s * (hfsq + r) + dk * LN2_LO)) - f);
	}
	if (k === 0) return f - s * (f - r);
	return dk * LN2_HI - ((s * (f - r) - dk * LN2_LO) - f);
}

/** The logarithm to base 10. */
export function log10(x) {
	x = +x;
	F64[0] = x;
	let hx = I32[HI];
	let lx = U32[LO];
	let k = 0;
	if (hx < 0x00100000) {
		if (((hx & 0x7fffffff) | lx) === 0) return -Infinity;
		if (hx < 0) return NaN;
		k -= 54;
		x *= TWO54;
		F64[0] = x;
		hx = I32[HI];
		lx = U32[LO];
	}
	if (hx >= 0x7ff00000) return x + x;
	if (hx === 0x3ff00000 && lx === 0) return 0;
	k += (hx >> 20) - 1023;
	const i = k < 0 ? 1 : 0;
	hx = (hx & 0x000fffff) | ((0x3ff - i) << 20);
	const y = k + i;
	x = fromWords(hx, lx);
	const z = y * LOG10_2LO + IVLN10 * log(x);
	return z + y * LOG10_2HI;
}

// --- pow ---------------------------------------------------------------------

const BP = [1, 1.5];
const DP_H = [0, 5.84962487220764160156e-01];
const DP_L = [0, 1.35003920212974897128e-08];
const TWO53 = 9007199254740992;
const L1 = 5.99999999999994648725e-01;
const L2 = 4.28571428578550184252e-01;
const L3 = 3.33333329818377432918e-01;
const L4 = 2.72728123808534006489e-01;
const L5 = 2.30660745775561754067e-01;
const L6 = 2.06975017800338417784e-01;
const PW_LG2 = 6.93147180559945286227e-01;
const PW_LG2_H = 6.93147182464599609375e-01;
const PW_LG2_L = -1.90465429995776804525e-09;
const OVT = 8.0085662595372944372e-17;
const CP = 9.61796693925975554329e-01;
const CP_H = 9.61796700954437255859e-01;
const CP_L = -7.02846165095275826516e-09;
const IVLN2 = 1.44269504088896338700e+00;
const IVLN2_H = 1.44269502162933349609e+00;
const IVLN2_L = 1.92596299112661746887e-08;

// Powers of two the scaling below multiplies by: exact, built from their bits.
const TWO1023P = fromWords(0x7fe00000, 0);
const TWOM969 = fromWords((0x3ff - 969) << 20, 0);

/**
 * x * 2 ** n, rounded once, as C's ldexp (Python's math.ldexp) rounds it: a
 * result that falls among the subnormals is rounded only by the last
 * multiplication. musl's scalbn.
 */
export function ldexp(x, n) {
	let y = x;
	if (n > 1023) {
		y *= TWO1023P;
		n -= 1023;
		if (n > 1023) {
			y *= TWO1023P;
			n -= 1023;
			if (n > 1023) n = 1023;
		}
	} else if (n < -1022) {
		y *= TWOM969;
		n += 969;
		if (n < -1022) {
			y *= TWOM969;
			n += 969;
			if (n < -1022) n = -1022;
		}
	}
	return y * fromWords((0x3ff + n) << 20, 0);
}

/** x ** y, as `Math.pow` and `**` answer it at the edges. */
export function pow(x, y) {
	x = +x;
	y = +y;
	if (y !== y) return NaN;
	if (Math.abs(x) === 1 && (y === Infinity || y === -Infinity)) return NaN;
	F64[0] = x;
	const hx = I32[HI];
	const lx = U32[LO];
	F64[0] = y;
	const hy = I32[HI];
	const ly = U32[LO];
	let ix = hx & 0x7fffffff;
	const iy = hy & 0x7fffffff;
	if ((iy | ly) === 0) return 1;
	if (ix > 0x7ff00000 || (ix === 0x7ff00000 && lx !== 0) || iy > 0x7ff00000 || (iy === 0x7ff00000 && ly !== 0)) {
		return x + y;
	}
	// Whether y is an odd integer (1), an even one (2) or neither (0), for x < 0.
	let yisint = 0;
	if (hx < 0) {
		if (iy >= 0x43400000) {
			yisint = 2;
		} else if (iy >= 0x3ff00000) {
			const k = (iy >> 20) - 0x3ff;
			if (k > 20) {
				const j = ly >>> (52 - k);
				if (((j << (52 - k)) >>> 0) === ly) yisint = 2 - (j & 1);
			} else if (ly === 0) {
				const j = iy >> (20 - k);
				if ((j << (20 - k)) === iy) yisint = 2 - (j & 1);
			}
		}
	}
	if (ly === 0) {
		if (iy === 0x7ff00000) {
			if (((ix - 0x3ff00000) | lx) === 0) return y - y;
			if (ix >= 0x3ff00000) return hy >= 0 ? y : 0;
			return hy < 0 ? -y : 0;
		}
		if (iy === 0x3ff00000) {
			if (hy < 0) return 1 / x;
			return x;
		}
		if (hy === 0x40000000) return x * x;
		if (hy === 0x3fe00000 && hx >= 0) return Math.sqrt(x);
	}
	let ax = Math.abs(x);
	if (lx === 0 && (ix === 0x7ff00000 || ix === 0 || ix === 0x3ff00000)) {
		let z = ax;
		if (hy < 0) z = 1 / z;
		if (hx < 0) {
			if (((ix - 0x3ff00000) | yisint) === 0) z = NaN;
			else if (yisint === 1) z = -z;
		}
		return z;
	}
	let n = (hx >> 31) + 1;
	if ((n | yisint) === 0) return NaN;
	let s = 1;
	if ((n | (yisint - 1)) === 0) s = -1;
	let t1;
	let t2;
	if (iy > 0x41e00000) {
		if (iy > 0x43f00000) {
			if (ix <= 0x3fefffff) return hy < 0 ? Infinity : 0;
			if (ix >= 0x3ff00000) return hy > 0 ? Infinity : 0;
		}
		if (ix < 0x3fefffff) return hy < 0 ? s * Infinity : s * 0;
		if (ix > 0x3ff00000) return hy > 0 ? s * Infinity : s * 0;
		const t = ax - 1;
		const w = (t * t) * (0.5 - t * (0.3333333333333333333333 - t * 0.25));
		const u = IVLN2_H * t;
		const v = t * IVLN2_L - w * IVLN2;
		t1 = lowZero(u + v);
		t2 = v - (t1 - u);
	} else {
		n = 0;
		if (ix < 0x00100000) {
			ax *= TWO53;
			n -= 53;
			ix = highOf(ax);
		}
		n += (ix >> 20) - 0x3ff;
		const j = ix & 0x000fffff;
		ix = j | 0x3ff00000;
		let k;
		if (j <= 0x3988e) {
			k = 0;
		} else if (j < 0xbb67a) {
			k = 1;
		} else {
			k = 0;
			n += 1;
			ix -= 0x00100000;
		}
		ax = fromWords(ix, lowOf(ax));
		let u = ax - BP[k];
		let v = 1 / (ax + BP[k]);
		const ss = u * v;
		const sH = lowZero(ss);
		let tH = fromWords(((ix >> 1) | 0x20000000) + 0x00080000 + (k << 18), 0);
		let tL = ax - (tH - BP[k]);
		const sL = v * ((u - sH * tH) - sH * tL);
		let s2 = ss * ss;
		let r = s2 * s2 * (L1 + s2 * (L2 + s2 * (L3 + s2 * (L4 + s2 * (L5 + s2 * L6)))));
		r += sL * (sH + ss);
		s2 = sH * sH;
		tH = lowZero(3 + s2 + r);
		tL = r - ((tH - 3) - s2);
		u = sH * tH;
		v = sL * tH + tL * ss;
		const pH = lowZero(u + v);
		const pL = v - (pH - u);
		const zH = CP_H * pH;
		const zL = CP_L * pH + pL * CP + DP_L[k];
		const t = n;
		t1 = lowZero(((zH + zL) + DP_H[k]) + t);
		t2 = zL - (((t1 - t) - DP_H[k]) - zH);
	}
	const y1 = lowZero(y);
	const pL = (y - y1) * t1 + y * t2;
	let pH = y1 * t1;
	let z = pL + pH;
	F64[0] = z;
	let j = I32[HI];
	let i = U32[LO];
	if (j >= 0x40900000) {
		if (((j - 0x40900000) | i) !== 0) return s * Infinity;
		if (pL + OVT > z - pH) return s * Infinity;
	} else if ((j & 0x7fffffff) >= 0x4090cc00) {
		if (((j - (0xc090cc00 | 0)) | i) !== 0) return s * 0;
		if (pL <= z - pH) return s * 0;
	}
	i = j & 0x7fffffff;
	let k = (i >> 20) - 0x3ff;
	n = 0;
	if (i > 0x3fe00000) {
		n = j + (0x00100000 >> (k + 1));
		k = ((n & 0x7fffffff) >> 20) - 0x3ff;
		const t = fromWords(n & ~(0x000fffff >> k), 0);
		n = ((n & 0x000fffff) | 0x00100000) >> (20 - k);
		if (j < 0) n = -n;
		pH -= t;
	}
	let t = lowZero(pL + pH);
	const u = t * PW_LG2_H;
	const v = (pL - (t - pH)) * PW_LG2 + t * PW_LG2_L;
	z = u + v;
	const w = v - (z - u);
	t = z * z;
	t1 = z - t * (P1 + t * (P2 + t * (P3 + t * (P4 + t * P5))));
	const r = (z * t1) / (t1 - 2) - (w + z * w);
	z = 1 - (r - z);
	// The exponent put back: through the words where the result stays normal,
	// by one rounded scaling where it does not. In doubles, not 32-bit ints,
	// so that a sum past 2**31 cannot wrap.
	j = highOf(z) + n * 1048576;
	if (Math.floor(j / 1048576) <= 0) {
		z = ldexp(z, n);
	} else {
		F64[0] = z;
		z = fromWords(U32[HI] + n * 1048576, U32[LO]);
	}
	return s * z;
}

// --- log1p and expm1 -----------------------------------------------------------

const EXPM1_Q1 = -3.33333333333331316428e-02;
const EXPM1_Q2 = 1.58730158725481460165e-03;
const EXPM1_Q3 = -7.93650757867487942473e-05;
const EXPM1_Q4 = 4.00821782732936239552e-06;
const EXPM1_Q5 = -2.01099218183624371326e-07;

/** log(1 + x), accurate for x near 0. */
export function log1p(x) {
	x = +x;
	const hx = highOf(x);
	const ax = hx & 0x7fffffff;
	let k = 1;
	let f = 0;
	let c = 0;
	let hu = 0;
	if (hx < 0x3fda827a) { // 1 + x < sqrt(2)+
		if (ax >= 0x3ff00000) return x === -1 ? -Infinity : NaN; // x <= -1
		if (ax < 0x3e200000) { // |x| < 2**-29
			if (ax < 0x3c900000) return x; // |x| < 2**-54
			return x - x * x * 0.5;
		}
		if (hx > 0 || hx <= -1076707644) { // (int32_t)0xbfd2bec4: sqrt(2)/2- <= 1 + x < sqrt(2)+
			k = 0;
			f = x;
			hu = 1;
		}
	}
	if (hx >= 0x7ff00000) return x + x;
	if (k !== 0) {
		let u;
		if (hx < 0x43400000) {
			u = 1 + x;
			hu = highOf(u);
			k = (hu >> 20) - 1023;
			c = k > 0 ? 1 - (u - x) : x - (u - 1); // the correction term
			c /= u;
		} else {
			u = x;
			hu = highOf(u);
			k = (hu >> 20) - 1023;
			c = 0;
		}
		hu &= 0x000fffff;
		const low = lowOf(u);
		if (hu < 0x6a09e) { // u ~< sqrt(2)
			u = fromWords(hu | 0x3ff00000, low);
		} else {
			k += 1;
			u = fromWords(hu | 0x3fe00000, low);
			hu = (0x00100000 - hu) >> 2;
		}
		f = u - 1;
	}
	const hfsq = 0.5 * f * f;
	const dk = k;
	if (hu === 0) { // |f| < 2**-20
		if (f === 0) {
			if (k === 0) return 0;
			c += dk * LN2_LO;
			return dk * LN2_HI + c;
		}
		const r = hfsq * (1 - 0.66666666666666666 * f);
		if (k === 0) return f - r;
		return dk * LN2_HI - ((r - (dk * LN2_LO + c)) - f);
	}
	const s = f / (2 + f);
	const z = s * s;
	const r = z * (LG1 + z * (LG2 + z * (LG3 + z * (LG4 + z * (LG5 + z * (LG6 + z * LG7))))));
	if (k === 0) return f - (hfsq - s * (hfsq + r));
	return dk * LN2_HI - ((hfsq - (s * (hfsq + r) + (dk * LN2_LO + c))) - f);
}

/** e ** x - 1, accurate for x near 0. */
export function expm1(x) {
	x = +x;
	F64[0] = x;
	let hx = U32[HI];
	const lx = U32[LO];
	const xsb = hx & 0x80000000;
	hx &= 0x7fffffff;
	if (hx >= 0x4043687a) { // |x| >= 56 ln2
		if (hx >= 0x40862e42) { // |x| >= 709.78...
			if (hx >= 0x7ff00000) {
				if (((hx & 0xfffff) | lx) !== 0) return x + x;
				return xsb === 0 ? x : -1;
			}
			if (x > 7.09782712893383973096e+02) return Infinity;
		}
		if (xsb !== 0) return -1; // x < -56 ln2
	}
	let c = 0;
	let k;
	if (hx > 0x3fd62e42) { // |x| > 0.5 ln2
		let hi;
		let lo;
		if (hx < 0x3ff0a2b2) { // and |x| < 1.5 ln2
			if (xsb === 0) {
				hi = x - LN2_HI;
				lo = LN2_LO;
				k = 1;
			} else {
				hi = x + LN2_HI;
				lo = -LN2_LO;
				k = -1;
			}
		} else {
			k = Math.trunc(INVLN2 * x + (xsb === 0 ? 0.5 : -0.5));
			const t = k;
			hi = x - t * LN2_HI;
			lo = t * LN2_LO;
		}
		x = hi - lo;
		c = (hi - x) - lo;
	} else if (hx < 0x3c900000) { // |x| < 2**-54
		return x;
	} else {
		k = 0;
	}
	const hfx = 0.5 * x;
	const hxs = x * hfx;
	const r1 = 1 + hxs * (EXPM1_Q1 + hxs * (EXPM1_Q2 + hxs * (EXPM1_Q3 + hxs * (EXPM1_Q4 + hxs * EXPM1_Q5))));
	let t = 3 - r1 * hfx;
	let e = hxs * ((r1 - t) / (6 - x * t));
	if (k === 0) return x - (x * e - hxs);
	e = x * (e - c) - c;
	e -= hxs;
	if (k === -1) return 0.5 * (x - e) - 0.5;
	if (k === 1) {
		if (x < -0.25) return -2 * (e - (x + 0.5));
		return 1 + 2 * (x - e);
	}
	let y;
	if (k <= -2 || k > 56) {
		y = 1 - (e - x);
		if (k === 1024) y = y * 2 * 8.98846567431158e+307;
		else y = y * ldexp(1, k);
		return y - 1;
	}
	if (k < 20) {
		t = fromWords(0x3ff00000 - (0x200000 >> k), 0); // 1 - 2**-k
		y = t - (e - x);
	} else {
		t = fromWords((0x3ff - k) << 20, 0); // 2**-k
		y = x - (e + t);
		y += 1;
	}
	return y * ldexp(1, k);
}
