/**
 * A distribution fitted to a sample, and the fits ranked.
 *
 * The shapes are the ones a parameter can be given (./pdf.js), so a fit is an
 * expression that can be written straight back into a model:
 * `logt(min=…,max=…,mode=…)` rather than a Weibull the model has no way to
 * draw from. The three log-normal spellings are one shape, fitted once --
 * as a geometric mean and SD by maximum likelihood, which is where that
 * method's answer is, and as an arithmetic mean and SD by moments, which is
 * where that one's is.
 *
 * **Maximum likelihood** is the parameters under which this sample is the
 * most probable. For the normal and log-normal that is the mean and SD, of
 * the values or of their logarithms; for the two uniforms it is the smallest
 * and largest value; for the four triangles it is a search, because the
 * likelihood of a triangle has no closed-form maximum. Its mode, though, is
 * always one of the realisations (Oliver 1972: between two neighbours the
 * log-likelihood is convex in the mode, so it peaks at an end), which leaves
 * the two ends to search over -- a profile over the order statistics inside
 * a Nelder–Mead over the ends.
 *
 * **Moments** are the parameters whose mean and variance are the sample's,
 * and for a three-parameter shape its skewness as well: as many moments as
 * the shape has numbers. Of the values themselves, not their logarithms --
 * that is what the method is, and it is why it differs from the other on a
 * log shape: the mean of a skewed sample is carried by its largest values.
 * A shape that cannot be as skewed as the sample is -- a triangle's skewness
 * is at most 2√2/5 -- is given the most skewness it can have, and says so.
 *
 * The fits are ranked by a goodness-of-fit statistic: Kolmogorov–Smirnov's
 * largest gap between the two cumulative curves, Anderson–Darling's A², which
 * weighs the tails where a dose limit is read, or AIC, the likelihood with
 * two per parameter taken off. The p-values that come with the first two are
 * for a distribution fixed before the sample was seen. For one fitted to the
 * sample they are too large (Lilliefors), so they rank and they do not accept
 * -- except for the distribution a parameter was *specified* with, which is
 * exactly the case they are for.
 */

import { kindInfo, densityAt, cumulativeAt } from './pdf.js';

export const FIT_METHODS = [
	['mle', 'maximum likelihood', 'The parameters under which this sample is the most probable.'],
	['mom', 'method of moments', 'The parameters whose mean and variance — and skewness, for a three-parameter '
		+ 'shape — are the sample’s.'],
];

export const FIT_TESTS = [
	['ad', 'Anderson–Darling', 'A²: the squared gap between the cumulative curves, weighted towards the tails. '
		+ 'Smaller is better.'],
	['ks', 'Kolmogorov–Smirnov', 'D: the largest gap between the cumulative curves. Smaller is better.'],
	['aic', 'AIC', 'Akaike’s information criterion: −2 × log-likelihood + 2 per fitted parameter. Smaller is better; '
		+ 'shown less the smallest in the table.'],
];

/** The shapes, in the order the model's editor offers them. */
export const FIT_FAMILIES = [
	{ id: 'unif', label: 'Uniform', params: 2 },
	{ id: 'triang', label: 'Triangular', params: 3 },
	{ id: 'dtriang', label: 'Double-triangular', params: 3 },
	{ id: 'norm', label: 'Normal', params: 2 },
	{ id: 'logu', label: 'Log-uniform', params: 2, positive: true },
	{ id: 'logt', label: 'Log-triangular', params: 3, positive: true },
	{ id: 'logdt', label: 'Log-double-triangular', params: 3, positive: true },
	{ id: 'logn', label: 'Log-normal', params: 2, positive: true },
];

/** Fewer than this and a fit is a guess with decimals. */
export const FIT_MIN_SAMPLE = 5;

/** Mean, variance, skewness -- the population ones, over `n`. */
export function sampleMoments(x) {
	const n = x.length;
	let mean = 0;
	for (let i = 0; i < n; i++) mean += x[i];
	mean /= n;
	let m2 = 0; let m3 = 0;
	for (let i = 0; i < n; i++) {
		const d = x[i] - mean;
		m2 += d * d;
		m3 += d * d * d;
	}
	m2 /= n;
	m3 /= n;
	return { n, mean, m2, sd: Math.sqrt(m2), skew: m2 > 0 ? m3 / m2 ** 1.5 : 0 };
}

/* -------------------------------------------------------------------------
 * The triangles, standardised: a peak at `r` on [0, 1]. The triangle holds
 * `r` of its probability left of the peak; the double triangle holds half
 * there wherever the peak is. Either side is a right triangle, so a piece
 * is `r·V` on the left and `1 − (1−r)·W` on the right, with V and W the same
 * variable: density 2v on [0, 1].
 * ---------------------------------------------------------------------- */

const leftWeight = (r, double) => (double ? 0.5 : r);

/** E[Zᵏ] for k = 1..3, from the binomial expansion of each piece. */
function shapeRaw(r, double) {
	const wl = leftWeight(r, double);
	const q = 1 - r;
	const out = [1];
	for (let k = 1; k <= 3; k++) {
		// E[Vᵏ] = 2/(k+2); the right piece expanded in powers of (1−r),
		// which stays exact when the peak is near the right end.
		let right = 0;
		for (let j = 0, c = 1; j <= k; j++) {
			right += c * (-q) ** j * (2 / (j + 2));
			c = (c * (k - j)) / (j + 1);
		}
		out.push(wl * r ** k * (2 / (k + 2)) + (1 - wl) * right);
	}
	return out;
}

/** Mean, SD and skewness of the standardised shape. */
function shapeMoments(r, double) {
	const [, m1, m2, m3] = shapeRaw(r, double);
	const v = m2 - m1 * m1;
	return { mean: m1, sd: Math.sqrt(v), skew: (m3 - 3 * m1 * m2 + 2 * m1 ** 3) / v ** 1.5 };
}

/**
 * The peak at which `measure(r)` equals `target`: a scan for a change of
 * sign and bisection inside it. None -- the target is out of the shape's
 * reach -- gives the nearest, flagged `clamped`.
 */
function solveShape(measure, target, lo, hi) {
	const steps = 64;
	let prevR = lo;
	let prev = measure(lo) - target;
	let best = { r: lo, gap: Math.abs(prev) };
	if (prev === 0) return { r: lo, clamped: false };
	for (let s = 1; s <= steps; s++) {
		const r = lo + ((hi - lo) * s) / steps;
		const now = measure(r) - target;
		if (!Number.isFinite(now)) { prevR = r; prev = now; continue; }
		if (Math.abs(now) < best.gap) best = { r, gap: Math.abs(now) };
		if (now === 0) return { r, clamped: false };
		if (Number.isFinite(prev) && (prev < 0) !== (now < 0)) {
			let a = prevR; let b = r; let fa = prev;
			for (let it = 0; it < 60; it++) {
				const m = (a + b) / 2;
				const fm = measure(m) - target;
				if ((fm < 0) === (fa < 0)) { a = m; fa = fm; } else b = m;
			}
			return { r: (a + b) / 2, clamped: false };
		}
		prevR = r;
		prev = now;
	}
	return { r: best.r, clamped: true };
}

/* -------------------------------------------------------------------------
 * The log shapes' moments. X = exp(Y) with Y = ln(min) + L·Z, so E[Xᵏ] is Z's
 * moment generating function at kL -- which is e^kL times E[e^(−kL(1−Z))],
 * a number in (0, 1] that neither overflows nor, for a spread of hundreds of
 * decades, underflows to nothing. Every ratio the fit needs is of those.
 * ---------------------------------------------------------------------- */

/** E[e^(−sV)] for V with density 2v on [0, 1], any real `s`. */
function rampMgf(s) {
	if (Math.abs(s) < 0.5) {
		// 2 Σ (−s)ⁿ / (n! (n+2)), where the closed form cancels.
		let sum = 0; let term = 1;
		for (let n = 0; n < 24; n++) {
			sum += term / (n + 2);
			term *= -s / (n + 1);
		}
		return 2 * sum;
	}
	return (2 * (1 - Math.exp(-s) * (1 + s))) / (s * s);
}

/** e^(−t)·E[e^(sV)], kept finite however large `s` is (s ≤ t). */
function rampMgfUp(s, t) {
	if (s < 0.5) return Math.exp(-t) * rampMgf(-s);
	return (2 * (Math.exp(s - t) * (s - 1) + Math.exp(-t))) / (s * s);
}

/** E[e^(−t(1−Z))] for the peak shape. */
function peakScaled(t, r, double) {
	const wl = leftWeight(r, double);
	return wl * rampMgfUp(t * r, t) + (1 - wl) * rampMgf(t * (1 - r));
}

/** E[e^(−t(1−U))] for U uniform. */
function flatScaled(t) {
	return t < 1e-12 ? 1 : -Math.expm1(-t) / t;
}

/** The squared coefficient of variation and the skewness of X = e^(L·Z). */
function logMoments(scaled, L) {
	const m1 = scaled(L); const m2 = scaled(2 * L); const m3 = scaled(3 * L);
	const v = m2 / (m1 * m1) - 1;
	const c = m2 - m1 * m1;
	return { cv2: v, skew: (m3 - 3 * m1 * m2 + 2 * m1 ** 3) / c ** 1.5, m1 };
}

/** The spread L at which the squared CV is `cv2`, or null out of reach. */
function spreadFor(scaled, cv2) {
	let a = Math.log(1e-5); let b = Math.log(1400);
	if (!(logMoments(scaled, Math.exp(b)).cv2 >= cv2)) return null;
	if (logMoments(scaled, Math.exp(a)).cv2 >= cv2) return Math.exp(a);
	for (let it = 0; it < 80; it++) {
		const m = (a + b) / 2;
		if (logMoments(scaled, Math.exp(m)).cv2 < cv2) a = m; else b = m;
	}
	return Math.exp((a + b) / 2);
}

/* -------------------------------------------------------------------------
 * Maximum likelihood for the triangles.
 * ---------------------------------------------------------------------- */

/**
 * The log-likelihood of the triangle on [a, b] whose mode is the best of the
 * candidates, over `z` sorted in (a, b). The candidates are the order
 * statistics and, for the plain triangle, the two ends (a mode at the end is
 * a right triangle, which it can be; the double triangle's would put half its
 * probability on one point).
 *
 * The double triangle's density jumps at the mode -- each side holds half
 * the probability whatever its width -- so a realisation at the mode is worth
 * 1/(c−a) on the left and 1/(b−c) on the right, and the likelihood's top can
 * be the mode a hair *below* a realisation, with that one on the right. Both
 * are candidates; `below` says it was the second. The plain triangle is
 * continuous at its mode and the two are the same.
 */
function triangleProfile(z, a, b, double) {
	const n = z.length;
	const w = b - a;
	let right = 0;
	for (let i = 0; i < n; i++) right += Math.log1p(-(z[i] - a) / w);
	const base = double ? -n * Math.log(w) : n * Math.LN2 - n * Math.log(w);
	const p = double ? 2 : 1;
	let best = { ll: -Infinity, at: -1, below: false };
	if (!double) best = { ll: base + right, at: -1, below: false }; // the mode at `a`
	let left = 0;
	for (let r = 0; r < n; r++) {
		const u = (z[r] - a) / w;
		const lu = Math.log(u);
		const lv = Math.log1p(-u);
		if (double) {
			const ll = base + left - p * r * lu + right - p * (n - r) * lv;
			if (ll > best.ll) best = { ll, at: r, below: true };
		}
		left += lu;
		right -= lv;
		const ll = base + left - p * (r + 1) * lu + right - p * (n - r - 1) * lv;
		if (ll > best.ll) best = { ll, at: r, below: false };
	}
	if (!double && base + left > best.ll) best = { ll: base + left, at: n, below: false }; // the mode at `b`
	return best;
}

/** The largest number below `v`, or near enough: a hair under it. */
const under = (v) => (v === 0 ? -Number.MIN_VALUE : v - Math.abs(v) * Number.EPSILON);

/** A small Nelder–Mead, for the two ends. */
function nelderMead(f, x0, { step = 0.7, iterations = 160, tol = 1e-10 } = {}) {
	const d = x0.length;
	let pts = [x0.slice()];
	for (let i = 0; i < d; i++) {
		const x = x0.slice();
		x[i] += step;
		pts.push(x);
	}
	let vals = pts.map(f);
	for (let it = 0; it < iterations; it++) {
		const order = vals.map((v, i) => i).sort((i, j) => vals[i] - vals[j]);
		pts = order.map((i) => pts[i]);
		vals = order.map((i) => vals[i]);
		if (Math.abs(vals[d] - vals[0]) <= tol * (1 + Math.abs(vals[0]))) break;
		const c = new Array(d).fill(0);
		for (let i = 0; i < d; i++) for (let j = 0; j < d; j++) c[j] += pts[i][j] / d;
		const along = (t) => c.map((cj, j) => cj + t * (pts[d][j] - cj));
		const xr = along(-1); const fr = f(xr);
		if (fr < vals[0]) {
			const xe = along(-2); const fe = f(xe);
			if (fe < fr) { pts[d] = xe; vals[d] = fe; } else { pts[d] = xr; vals[d] = fr; }
		} else if (fr < vals[d - 1]) {
			pts[d] = xr; vals[d] = fr;
		} else {
			const xc = along(fr < vals[d] ? -0.5 : 0.5); const fc = f(xc);
			if (fc < Math.min(fr, vals[d])) {
				pts[d] = xc; vals[d] = fc;
			} else {
				for (let i = 1; i <= d; i++) {
					pts[i] = pts[i].map((v, j) => pts[0][j] + 0.5 * (v - pts[0][j]));
					vals[i] = f(pts[i]);
				}
			}
		}
	}
	let k = 0;
	for (let i = 1; i <= d; i++) if (vals[i] < vals[k]) k = i;
	return { x: pts[k], value: vals[k] };
}

/**
 * The triangle of largest likelihood through sorted `y`: its ends, and its
 * mode as the index of the realisation it is at (-1 and n for the ends) and
 * whether it is a hair below that one (see `triangleProfile`).
 *
 * Standardised to [0, 1] first, so that an end a hair outside the sample is
 * still outside it in floating point whatever the sample's offset, and the
 * ends are searched as their distance past the extremes, on a log scale:
 * `a = −e^α`, `b = 1 + e^β`, both from a trillionth of the range to a few
 * hundred ranges.
 */
function triangleMle(y, double) {
	const n = y.length;
	const lo = y[0];
	const span = y[n - 1] - lo;
	const z = Float64Array.from(y, (v) => (v - lo) / span);
	const clamp = (v) => Math.min(6, Math.max(-28, v));
	const cost = ([al, be]) => -triangleProfile(z, -Math.exp(clamp(al)), 1 + Math.exp(clamp(be)), double).ll;
	let best = null;
	for (const s of [-4, -1.5]) {
		const got = nelderMead(cost, [s, s]);
		if (!best || got.value < best.value) best = got;
	}
	const a = -Math.exp(clamp(best.x[0]));
	const b = 1 + Math.exp(clamp(best.x[1]));
	const { at, below } = triangleProfile(z, a, b, double);
	return { min: lo + a * span, max: lo + b * span, at, below };
}

/**
 * The mode `triangleMle` found, in the units of `sorted`: a realisation taken
 * as it is rather than back through the standardisation (or a logarithm), or
 * a hair under it.
 */
function modeOf(found, sorted, min, max) {
	if (found.at < 0) return min;
	if (found.at >= sorted.length) return max;
	return found.below ? under(sorted[found.at]) : sorted[found.at];
}

/* -------------------------------------------------------------------------
 * The fits.
 * ---------------------------------------------------------------------- */

const logsOf = (x) => Float64Array.from(x, Math.log);

/**
 * One shape fitted to `sorted` by `method`.
 *
 * @returns {{spec: object, edges?: boolean, note?: string}|{why: string}}
 *   `edges`: the fit's ends are the sample's extremes, which the tests then
 *   leave out (see `scoreFit`); `note`: what the fit had to give up.
 */
export function fitFamily(id, sorted, method) {
	const got = fitShape(id, sorted, method);
	if (got.why) return got;
	// What a moment fit asks of a log shape can be past what a number holds:
	// a minimum of e^-800 is zero, and a zero minimum is no log shape at all.
	const p = got.spec.params;
	const ok = Object.values(p).every(Number.isFinite)
		&& (p.min == null || p.max > p.min)
		&& (p.mode == null || (p.mode >= p.min && p.mode <= p.max))
		&& (!FIT_FAMILIES.find((f) => f.id === id)?.positive || !(p.min <= 0));
	return ok ? got : { why: 'would need numbers beyond what a computer holds' };
}

function fitShape(id, sorted, method) {
	const fam = FIT_FAMILIES.find((f) => f.id === id);
	if (!fam) return { why: 'not a shape a parameter can have' };
	const n = sorted.length;
	if (n < FIT_MIN_SAMPLE) return { why: `needs at least ${FIT_MIN_SAMPLE} realisations` };
	if (!(sorted[n - 1] > sorted[0])) return { why: 'every realisation has the same value' };
	if (fam.positive && !(sorted[0] > 0)) return { why: 'needs every value above zero' };
	const mom = method === 'mom';
	const x = sampleMoments(sorted);
	// A log shape a thousandth wide is its linear shape to the sixth figure,
	// and its third moment is lost in the rounding of the first two.
	if (mom && fam.positive && id !== 'logn' && x.sd < 1e-3 * x.mean) {
		return { why: 'too narrow for its moments to tell it from the linear shape' };
	}
	const spec = (kind, params, extra = {}) => ({ spec: { kind, params }, ...extra });

	switch (id) {
		case 'norm':
			return spec('norm', { mean: x.mean, sd: x.sd });
		case 'unif':
			return mom
				? spec('unif', { min: x.mean - Math.sqrt(3) * x.sd, max: x.mean + Math.sqrt(3) * x.sd })
				: spec('unif', { min: sorted[0], max: sorted[n - 1] }, { edges: true });
		case 'logn': {
			if (mom) return spec('logn', { mean: x.mean, sd: x.sd });
			const l = sampleMoments(logsOf(sorted));
			return spec('Logn4', { gm: Math.exp(l.mean), gsd: Math.exp(l.sd) });
		}
		case 'logu': {
			if (!mom) return spec('logu', { min: sorted[0], max: sorted[n - 1] }, { edges: true });
			const L = spreadFor(flatScaled, x.m2 / (x.mean * x.mean));
			if (L == null) return { why: 'would need a range of more than 600 decades' };
			const la = Math.log(x.mean) - L - Math.log(flatScaled(L));
			return spec('logu', { min: Math.exp(la), max: Math.exp(la + L) });
		}
		case 'triang': case 'dtriang': {
			const double = id === 'dtriang';
			if (!mom) {
				const found = triangleMle(sorted, double);
				return spec(id, { min: found.min, max: found.max, mode: modeOf(found, sorted, found.min, found.max) });
			}
			// The peak from the skewness, which is the shape's alone; then the
			// width from the SD and the position from the mean.
			const [rlo, rhi] = double ? [1e-4, 1 - 1e-4] : [0, 1];
			const { r, clamped } = solveShape((q) => shapeMoments(q, double).skew, x.skew, rlo, rhi);
			const m = shapeMoments(r, double);
			const w = x.sd / m.sd;
			const min = x.mean - w * m.mean;
			return spec(id, { min, max: min + w, mode: min + r * w }, clamped
				? { note: `the sample is more skewed than a ${fam.label.toLowerCase()} shape can be` } : {});
		}
		case 'logt': case 'logdt': {
			const double = id === 'logdt';
			if (!mom) {
				// The triangle in the logarithms, which is where it is one.
				const found = triangleMle(logsOf(sorted), double);
				const min = Math.exp(found.min);
				const max = Math.exp(found.max);
				return spec(id, { min, max, mode: modeOf(found, sorted, min, max) });
			}
			// Two unknowns of the shape, the spread L and the peak r, from the
			// CV and the skewness, neither of which depends on where it sits:
			// for each peak the spread that gives the CV, then the peak whose
			// skewness is the sample's. The position last, from the mean.
			const cv2 = x.m2 / (x.mean * x.mean);
			const [rlo, rhi] = double ? [1e-3, 1 - 1e-3] : [0, 1];
			const spreadAt = (r) => spreadFor((t) => peakScaled(t, r, double), cv2);
			const skewAt = (r) => {
				const L = spreadAt(r);
				return L == null ? NaN : logMoments((t) => peakScaled(t, r, double), L).skew;
			};
			const { r, clamped } = solveShape(skewAt, x.skew, rlo, rhi);
			const L = spreadAt(r);
			if (L == null) return { why: 'would need a range of more than 600 decades' };
			const la = Math.log(x.mean) - L - Math.log(peakScaled(L, r, double));
			return spec(id, { min: Math.exp(la), max: Math.exp(la + L), mode: Math.exp(la + r * L) }, clamped
				? { note: 'no shape of this kind has both the sample’s spread and its skewness — the nearest' } : {});
		}
		default:
			return { why: 'not a shape a parameter can have' };
	}
}

/* -------------------------------------------------------------------------
 * The scores.
 * ---------------------------------------------------------------------- */

/**
 * Kolmogorov's distribution: the probability of a gap at least `d` between
 * the empirical and the true curve over `n` points, with Stephens's
 * correction for a finite sample (Numerical Recipes' `probks`).
 */
export function ksPValue(d, n) {
	const sq = Math.sqrt(n);
	const lambda = (sq + 0.12 + 0.11 / sq) * d;
	if (lambda < 0.2) return 1;
	const a2 = -2 * lambda * lambda;
	let fac = 2; let sum = 0; let before = 0;
	for (let j = 1; j <= 100; j++) {
		const term = fac * Math.exp(a2 * j * j);
		sum += term;
		if (Math.abs(term) <= 0.001 * before || Math.abs(term) <= 1e-8 * sum) return Math.min(1, Math.max(0, sum));
		fac = -fac;
		before = Math.abs(term);
	}
	return 1;
}

/**
 * The probability of an A² at least `a2`, from the limiting distribution
 * (Marsaglia & Marsaglia 2004, `ADinf`, good to 2e-6).
 */
export function adPValue(a2) {
	if (!(a2 > 0)) return 1;
	if (!Number.isFinite(a2)) return 0;
	const z = a2;
	const below = z < 2
		? (Math.exp(-1.2337141 / z) / Math.sqrt(z))
			* (2.00012 + (0.247105 - (0.0649821 - (0.0347962 - (0.011672 - 0.00168691 * z) * z) * z) * z) * z)
		: Math.exp(-Math.exp(1.0776 - (2.30695 - (0.43424 - (0.082433 - (0.008056 - 0.0003146 * z) * z) * z) * z) * z));
	return Math.min(1, Math.max(0, 1 - below));
}

/**
 * How well `spec` describes `sorted`: K–S D and A² with their p-values, and
 * the log-likelihood and AIC for `k` fitted parameters.
 *
 * A fit whose ends *are* the sample's extremes -- the two uniforms by maximum
 * likelihood -- puts those two realisations at probability 0 and 1 by
 * construction, and A² is infinite at either. Given its ends, though, the
 * realisations between them are a sample of the same curve, and that is what
 * the tests are asked about (`edges`). A realisation outside any other fit is
 * a realisation that fit calls impossible: A² and AIC are infinite then, and
 * `outside` counts them.
 */
export function scoreFit(sorted, spec, k, { edges = false } = {}) {
	const n = sorted.length;
	let ll = 0;
	let outside = 0;
	for (let i = 0; i < n; i++) {
		const f = densityAt(spec, sorted[i]);
		if (!(f > 0)) outside++;
		ll += Math.log(f);
	}
	if (Number.isNaN(ll)) ll = -Infinity;
	const F = [];
	for (let i = 0; i < n; i++) {
		const f = cumulativeAt(spec, sorted[i]);
		if (edges && (f <= 0 || f >= 1)) continue;
		F.push(f);
	}
	const m = F.length;
	let d = 0; let a2 = 0;
	for (let i = 0; i < m; i++) {
		d = Math.max(d, (i + 1) / m - F[i], F[i] - i / m);
		a2 += (2 * i + 1) * (Math.log(F[i]) + Math.log1p(-F[m - 1 - i]));
	}
	a2 = m ? -m - a2 / m : NaN;
	if (Number.isNaN(a2) || a2 === -Infinity) a2 = Infinity;
	return {
		ll, k, aic: 2 * k - 2 * ll,
		ks: d, ksP: m ? ksPValue(d, m) : NaN,
		ad: a2, adP: adPValue(a2),
		tested: m, outside,
	};
}

/**
 * Every shape fitted by `method`, scored. Those that could not be are there
 * too, with `why`, so a table can say what was tried.
 */
export function fitAll(sorted, method = 'mle') {
	return FIT_FAMILIES.map((fam) => {
		const got = fitFamily(fam.id, sorted, method);
		if (got.why) return { family: fam.id, label: fam.label, method, why: got.why };
		const score = scoreFit(sorted, got.spec, fam.params, { edges: got.edges });
		return { family: fam.id, label: fam.label, method, spec: got.spec, note: got.note ?? null, ...score };
	});
}

/** The fits in order of `test`, best first; the ones that failed last. */
export function rankFits(fits, test = 'ad') {
	const key = test === 'ks' ? 'ks' : test === 'aic' ? 'aic' : 'ad';
	const val = (f) => (f.why || !Number.isFinite(f[key]) ? Infinity : f[key]);
	return fits.slice().sort((a, b) => {
		if (!!a.why !== !!b.why) return a.why ? 1 : -1;
		const d = val(a) - val(b);
		return Number.isNaN(d) || d === 0 ? 0 : d;
	});
}

/** A fitted spec as the model would take it, to four significant figures. */
export function fitText(spec) {
	const meta = kindInfo(spec.kind);
	if (!meta) return '';
	const fmt = (v) => String(Number(v.toPrecision(4)));
	return `${meta.expr}(${meta.params.map((p) => `${p.key}=${fmt(spec.params[p.key])}`).join(',')})`;
}
