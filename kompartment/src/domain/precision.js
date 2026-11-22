/**
 * How well the values a calibration found are known.
 *
 * A calibration answers *what would the inputs have to be*; the next question
 * anybody asks of the answer is *how sure is it*. Least squares answers that
 * from two things it already has at the answer: how much misfit is left, and
 * how the endpoints move when each value moves. Near the answer the residuals
 * are close to straight in the values, `r(u) ~ r0 + J (u - u*)`, and then
 *
 *     cov(u) = s^2 (J^T J)^-1,   s^2 = |r0|^2 / (m - n)
 *
 * for `m` residuals and `n` values found: the leftover misfit spread over the
 * degrees of freedom the fit did not spend, carried to the values by how
 * strongly the endpoints pin each of them. Each value's standard error is the
 * root of its diagonal entry, its range about 95 % that times Student's t on
 * `m - n` degrees of freedom, and the off-diagonal entries, scaled to the
 * diagonal, are the correlations: two values near +1 or -1 move together, so
 * the endpoints fix their combination rather than either of them.
 *
 * **In the space the search moved in.** A value searched in its logarithm has
 * its standard error in the logarithm too, which makes its range a factor
 * either way -- `x 1.8` -- rather than a plus-or-minus that could run below
 * nought. The residuals are the search's own: weighted by the root of each
 * target's weight and measured as the target asks (absolute, relative or as a
 * logarithm), so `s` is in those terms.
 *
 * **What it cannot say.** With no more targets than values (`m <= n`) there is
 * no misfit left to judge by: the correlations still follow from `J`, the
 * standard errors do not. A value that came out on a bound is not at a
 * minimum the endpoints chose, so it is held where it is and given no range,
 * and the others' are worked out with it held. A value no endpoint moves --
 * a column of `J` that is nothing -- is said to have no effect rather than an
 * infinite range. And the whole is a linearisation: it is as good as the
 * model is straight over each range, and it treats the misfit as independent
 * scatter of one size, which a calibration to a handful of exact numbers is
 * not. The page says so beside it.
 */

import { normalQuantile } from './pdf.js';

/** Lanczos's coefficients for g = 7, n = 9: ln Gamma to about 1e-15. */
const LANCZOS = [
	0.99999999999980993, 676.5203681218851, -1259.1392167224028,
	771.32342877765313, -176.61502916214059, 12.507343278686905,
	-0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7,
];

/** The logarithm of the gamma function. */
export function lnGamma(x) {
	if (x < 0.5) return Math.log(Math.PI / Math.abs(Math.sin(Math.PI * x))) - lnGamma(1 - x);
	const z = x - 1;
	let a = LANCZOS[0];
	const t = z + 7.5;
	for (let i = 1; i < 9; i++) a += LANCZOS[i] / (z + i);
	return 0.5 * Math.log(2 * Math.PI) + (z + 0.5) * Math.log(t) - t + Math.log(a);
}

/** The continued fraction of the incomplete beta function, by Lentz's method. */
function betaFraction(a, b, x) {
	const TINY = 1e-300;
	const qab = a + b;
	const qap = a + 1;
	const qam = a - 1;
	let c = 1;
	let d = 1 - (qab * x) / qap;
	if (Math.abs(d) < TINY) d = TINY;
	d = 1 / d;
	let h = d;
	for (let m = 1; m <= 500; m++) {
		const m2 = 2 * m;
		let aa = (m * (b - m) * x) / ((qam + m2) * (a + m2));
		d = 1 + aa * d;
		if (Math.abs(d) < TINY) d = TINY;
		c = 1 + aa / c;
		if (Math.abs(c) < TINY) c = TINY;
		d = 1 / d;
		h *= d * c;
		aa = (-(a + m) * (qab + m) * x) / ((a + m2) * (qap + m2));
		d = 1 + aa * d;
		if (Math.abs(d) < TINY) d = TINY;
		c = 1 + aa / c;
		if (Math.abs(c) < TINY) c = TINY;
		d = 1 / d;
		const step = d * c;
		h *= step;
		if (Math.abs(step - 1) < 1e-15) break;
	}
	return h;
}

/** The regularised incomplete beta function, I_x(a, b). */
export function incompleteBeta(x, a, b) {
	if (!(x > 0)) return 0;
	if (!(x < 1)) return 1;
	const front = Math.exp(lnGamma(a + b) - lnGamma(a) - lnGamma(b)
		+ a * Math.log(x) + b * Math.log1p(-x));
	return x < (a + 1) / (a + b + 2)
		? (front * betaFraction(a, b, x)) / a
		: 1 - (front * betaFraction(b, a, 1 - x)) / b;
}

/** Student's t distribution with `dof` degrees of freedom: P(T <= t). */
export function studentCdf(t, dof) {
	const tail = 0.5 * incompleteBeta(dof / (dof + t * t), dof / 2, 0.5);
	return t >= 0 ? 1 - tail : tail;
}

/**
 * Student's t quantile: the t below which a share `p` lies.
 *
 * Closed forms for one and two degrees of freedom, the normal's beyond ten
 * million, and between them the distribution function inverted by bisection
 * to the last bit -- a few hundred evaluations of a continued fraction, once
 * per calibration.
 */
export function studentQuantile(p, dof) {
	if (!(p > 0 && p < 1) || !(dof > 0)) return NaN;
	if (p === 0.5) return 0;
	if (dof === 1) return Math.tan(Math.PI * (p - 0.5));
	if (dof === 2) return (2 * p - 1) / Math.sqrt(2 * p * (1 - p));
	if (dof > 1e7) return normalQuantile(p);
	const q = p > 0.5 ? p : 1 - p;
	let lo = 0;
	let hi = Math.max(2, 2 * normalQuantile(q));
	while (studentCdf(hi, dof) < q) hi *= 2;
	for (let i = 0; i < 300 && hi - lo > 1e-15 * hi; i++) {
		const mid = 0.5 * (lo + hi);
		if (studentCdf(mid, dof) < q) lo = mid;
		else hi = mid;
	}
	const t = 0.5 * (lo + hi);
	return p > 0.5 ? t : -t;
}

/**
 * Inverts a symmetric positive matrix scaled to unit diagonal, by
 * Gauss-Jordan with partial pivoting; null when a pivot falls under `tiny`,
 * which on a matrix of correlations means two columns of J nearly in line.
 */
function invertScaled(S, tiny = 1e-12) {
	const n = S.length;
	const M = S.map((row, i) => {
		const r = new Float64Array(2 * n);
		r.set(row);
		r[n + i] = 1;
		return r;
	});
	for (let c = 0; c < n; c++) {
		let p = c;
		for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
		if (!(Math.abs(M[p][c]) > tiny)) return null;
		[M[c], M[p]] = [M[p], M[c]];
		const piv = M[c][c];
		for (let k = 0; k < 2 * n; k++) M[c][k] /= piv;
		for (let r = 0; r < n; r++) {
			if (r === c) continue;
			const f = M[r][c];
			if (f === 0) continue;
			for (let k = 0; k < 2 * n; k++) M[r][k] -= f * M[c][k];
		}
	}
	return M.map((row) => Float64Array.from(row.subarray(n)));
}

/**
 * The precision of a least-squares answer, from its residuals and their
 * derivatives there.
 *
 * @param {object} o
 * @param {ArrayLike<number>} o.residuals   the search's own residuals at the answer
 * @param {Array<ArrayLike<number>|null>} o.columns  dr/du for each value, in
 *   the space the search moved in; null for one held (on a bound) or one the
 *   model would not run around
 * @param {string[]} o.keys
 * @param {string[]} o.spaces     'linear' or 'log', per value
 * @param {number[]} o.values     the values found, as the model holds them
 * @param {Array<string|null>} [o.pinned]  'lower', 'upper' or null, per value
 * @param {Array<string|null>} [o.failed]  why a value has no column, where the
 *   model did not run around it
 * @param {number} [o.level]      the share the ranges hold
 * @returns {object} `{targets, free, dof, spread, t, level, reason, values,
 *   correlations}`: per value `{key, se, low, high, factor, held}` -- `se` in
 *   the value's own units (for a logarithmic one, the value times its
 *   standard error in the logarithm), `factor` the range's either way for a
 *   logarithmic one, `held` why it has none ('lower', 'upper', 'no effect',
 *   or the reason it could not be differenced)
 */
export function precisionOf({
	residuals, columns, keys, spaces, values, pinned = [], failed = [], level = 0.95,
}) {
	const m = residuals.length;
	const n = keys.length;
	const held = keys.map((_, k) => pinned[k] ?? failed[k] ?? (columns[k] ? null : 'held'));
	// A value no endpoint moves: its column is nothing, so the matrix would be
	// singular for a reason the reader can be told plainly.
	for (let k = 0; k < n; k++) {
		if (held[k] || !columns[k]) continue;
		let any = false;
		for (let i = 0; i < m && !any; i++) if (columns[k][i] !== 0) any = true;
		if (!any) held[k] = 'no effect';
	}
	const free = [];
	for (let k = 0; k < n; k++) if (!held[k]) free.push(k);
	let ssr = 0;
	for (let i = 0; i < m; i++) ssr += residuals[i] * residuals[i];
	const dof = m - free.length;
	const out = {
		targets: m,
		free: free.length,
		dof,
		spread: dof > 0 ? Math.sqrt(ssr / dof) : null,
		t: dof > 0 ? studentQuantile(0.5 + level / 2, dof) : null,
		level,
		reason: null,
		values: keys.map((key, k) => ({
			key, se: null, low: null, high: null, factor: null, held: held[k],
		})),
		correlations: null,
	};
	if (!free.length) { out.reason = 'nothing free'; return out; }

	// J^T J over the values left free, scaled to unit diagonal so that the
	// pivots say how nearly in line two columns are, whatever their units.
	const A = free.map((a) => free.map((b) => {
		let s = 0;
		for (let i = 0; i < m; i++) s += columns[a][i] * columns[b][i];
		return s;
	}));
	const d = A.map((row, i) => Math.sqrt(row[i]));
	const S = A.map((row, i) => Float64Array.from(row, (v, j) => v / (d[i] * d[j])));
	const Sinv = invertScaled(S);
	if (!Sinv) { out.reason = 'cannot tell apart'; return out; }
	// The inverse of a symmetric matrix, symmetric to the last bit: the two
	// halves Gauss-Jordan gives differ in it, and a correlation is one number.
	const matrix = free.map((_, a) => free.map((__, b) => (
		a === b ? 1 : (0.5 * (Sinv[a][b] + Sinv[b][a])) / Math.sqrt(Sinv[a][a] * Sinv[b][b]))));
	out.correlations = { keys: free.map((k) => keys[k]), matrix };
	if (!(dof > 0)) { out.reason = 'no spare targets'; return out; }

	const s2 = ssr / dof;
	free.forEach((k, a) => {
		// (J^T J)^-1 = D^-1 S^-1 D^-1, so the variance is s^2 S^-1[a][a] / d[a]^2.
		const seU = Math.sqrt((s2 * Sinv[a][a]) / (d[a] * d[a]));
		const v = values[k];
		const row = out.values[k];
		if (spaces[k] === 'log') {
			row.factor = Math.exp(out.t * seU);
			row.low = v / row.factor;
			row.high = v * row.factor;
			row.se = Math.abs(v) * seU;
		} else {
			row.se = seU;
			row.low = v - out.t * seU;
			row.high = v + out.t * seU;
		}
	});
	return out;
}
