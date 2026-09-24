/**
 * Global sensitivity analysis: what SALib adds to GlobalSensitivity.jl.
 *
 * ./gsa.js is a port of GlobalSensitivity.jl. SALib (github.com/SALib/SALib,
 * MIT), the Python library most assessments reach for, has methods and
 * refinements that one does not, and this ports those from its source at
 * v1.6.0:
 *
 *   - **PAWN** (Pianosi and Wagener), which reads any sample: how far the
 *     output's distribution moves, as a Kolmogorov-Smirnov distance, when one
 *     input is held to a slice of its range;
 *   - **discrepancy** (Puy, Roy and Saltelli), which reads any sample too: how
 *     far each input's scatter against the output is from an even spread;
 *   - the **radial one-at-a-time design** (Campolongo, Saltelli and Cariboni),
 *     and its two readings: elementary effects, and Jansen's total index;
 *   - Morris's **trajectories**, the design SALib samples -- where
 *     GlobalSensitivity.jl walks -- with the **optimal** selection among
 *     candidates by Ruano, Ewald and Kolar's local search;
 *   - **bootstrap intervals** SALib's way, for μ*, the Sobol indices and
 *     DGSM's ν;
 *   - the **two-way interaction effects** of the fractional factorial, and
 *     the bias correction SALib applies to RBD-FAST.
 *
 * Everything is done in probability space, as in ./gsa.js: see there.
 *
 * **Where this differs from SALib, on purpose:**
 *
 *   - Morris's levels are the middles of `p` equal slices of probability,
 *     `(j + ½)/p`, as the tool's other Morris design has them, not a grid from
 *     0 to 1: the ends of an unbounded distribution are infinite. A step is
 *     SALib's, half the levels, which is half the range of probability.
 *   - PAWN's slice edges are `i/S`, clamped at 1. SALib's come from numpy's
 *     `arange(0, 1 + 1/S, 1/S)`, which for some `S` (6, 9, 21, ...) has one edge
 *     more, at a probability above one, and SALib then stops.
 *   - The interval on Jansen's total index resamples the base points. SALib
 *     indexes the differences with a (resamples × inputs) array, which draws
 *     as many rows as there are inputs and is not a bootstrap of anything.
 *   - Discrepancy is read on ranks when it comes from a sample -- the input's
 *     and the output's -- which are uniform whatever the distributions. SALib
 *     scales the input by its bounds, which for any input that is not uniform
 *     inflates its measure (as its own documentation warns), and the output by
 *     its extremes, which puts a skewed one -- a dose over decades -- at the
 *     bottom of the square for nearly every point, so that every input's
 *     share comes out the same.
 *   - Random draws -- resamples, candidate trajectories -- come from the tool's
 *     seeded streams, not numpy's. The tests replay numpy's to compare.
 *
 * ../../test/run.js checks each against SALib's own results on the same
 * samples (`test/fixtures/salib-reference.json`, from
 * `scripts/gen-salib-ref.py`).
 */

import { normalQuantile } from './pdf.js';

/* -------------------------------------------------------------------------
 * Small things, done as numpy does them.
 * ---------------------------------------------------------------------- */

/** numpy's `quantile(x, q)`, method 'linear', of values already sorted. */
function quantileSorted(sorted, q) {
	const n = sorted.length;
	if (!n) return NaN;
	const at = (n - 1) * q;
	const lo = Math.floor(at);
	const hi = Math.min(n - 1, lo + 1);
	const g = at - lo;
	const a = sorted[lo];
	const b = sorted[hi];
	// numpy's `_lerp`, which works from the nearer end for accuracy.
	return g >= 0.5 ? b - (b - a) * (1 - g) : a + (b - a) * g;
}

function meanOf(a) {
	let s = 0;
	for (let i = 0; i < a.length; i++) s += a[i];
	return s / a.length;
}

/** The standard deviation, over `n - ddof`. */
function sdOf(a, ddof = 1) {
	const m = meanOf(a);
	let s = 0;
	for (let i = 0; i < a.length; i++) s += (a[i] - m) ** 2;
	return Math.sqrt(s / (a.length - ddof));
}

/** The variance over `n`, numpy's default. */
function varOf(a) {
	const m = meanOf(a);
	let s = 0;
	for (let i = 0; i < a.length; i++) s += (a[i] - m) ** 2;
	return s / a.length;
}

function medianOf(a) {
	const s = Float64Array.from(a).sort();
	const n = s.length;
	if (!n) return NaN;
	return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}

/**
 * `resamples` bootstrap samples of `n` indices each, drawn with replacement:
 * `out[r * n + i]`. The same shape numpy's `randint(n, size=(resamples, n))`
 * gives, so the tests can hand in numpy's own.
 */
export function resampleIndices(n, resamples, next) {
	const out = new Int32Array(n * resamples);
	for (let i = 0; i < out.length; i++) out[i] = Math.min(n - 1, Math.floor(next() * n));
	return out;
}

/** `norm.ppf(0.5 + conf/2)`: the half-width of an interval, in standard deviations. */
function zOf(conf) {
	return normalQuantile(0.5 + conf / 2);
}

/* -------------------------------------------------------------------------
 * From a sample: PAWN.
 *
 * Hold one input to a slice of its range -- `slides` slices, each an equal
 * share of the sample by that input's quantiles -- and compare the output's
 * distribution in the slice with its distribution overall, by the
 * Kolmogorov-Smirnov distance between the two empirical CDFs. An input that
 * does not matter leaves them the same in every slice. The statistics across
 * the slices are the answer, the median the one usually reported.
 * ---------------------------------------------------------------------- */

/** The two-sample Kolmogorov-Smirnov statistic, scipy's `ks_2samp(a, b).statistic`. */
export function ksStatistic(a, b) {
	const x = Float64Array.from(a).sort();
	const z = Float64Array.from(b).sort();
	const n1 = x.length;
	const n2 = z.length;
	if (!n1 || !n2) return NaN;
	let i = 0;
	let j = 0;
	let best = 0;
	// At every value either sample holds, the two CDFs taken from the right:
	// scipy's `searchsorted(..., side='right')` over the pooled sample.
	while (i < n1 || j < n2) {
		const v = j >= n2 || (i < n1 && x[i] <= z[j]) ? x[i] : z[j];
		while (i < n1 && x[i] <= v) i++;
		while (j < n2 && z[j] <= v) j++;
		const d = Math.abs(i / n1 - j / n2);
		if (d > best) best = d;
	}
	return Math.min(1, best);
}

/**
 * @param {ArrayLike<number>} x  one input over the sample
 * @param {ArrayLike<number>} y  the output
 * @param {{slides?: number}} [o]
 * @returns {{minimum, mean, median, maximum, cv, stdev, ks: Float64Array}}
 *   `ks` per slice, NaN where a slice holds nothing
 */
export function pawn(x, y, { slides = 10 } = {}) {
	const S = Math.max(1, Math.round(slides));
	const step = 1 / S;
	const sorted = Float64Array.from(x).sort();
	const edges = new Float64Array(S + 1);
	for (let i = 0; i <= S; i++) edges[i] = quantileSorted(sorted, Math.min(1, i * step));
	const ks = new Float64Array(S).fill(NaN);
	for (let s = 0; s < S; s++) {
		// Half open, as SALib has them: the largest value of the input is in
		// no slice.
		const sel = [];
		for (let r = 0; r < x.length; r++) if (x[r] >= edges[s] && x[r] < edges[s + 1]) sel.push(y[r]);
		if (sel.length) ks[s] = ksStatistic(sel, y);
	}
	const got = Array.from(ks).filter((v) => !Number.isNaN(v));
	if (!got.length) return { minimum: NaN, mean: NaN, median: NaN, maximum: NaN, cv: NaN, stdev: NaN, ks };
	const m = meanOf(got);
	const stdev = sdOf(got, 0);
	return {
		minimum: Math.min(...got), mean: m, median: medianOf(got), maximum: Math.max(...got),
		cv: stdev / m, stdev, ks,
	};
}

/* -------------------------------------------------------------------------
 * From a sample: discrepancy.
 *
 * Puy, Roy and Saltelli: plot an input against the output and ask how far the
 * points are from covering the square evenly. An input the output does not
 * depend on scatters them evenly; one it does piles them along a curve. The
 * measure is a discrepancy of the two-dimensional point set -- scipy's
 * `qmc.discrepancy`, whose four kinds are here -- and each input's share of
 * the total over all of them is its sensitivity.
 * ---------------------------------------------------------------------- */

export const DISCREPANCIES = ['WD', 'CD', 'MD', 'L2-star'];

/**
 * The discrepancy of the points (u[i], v[i]), each in [0, 1]: scipy's
 * `qmc.discrepancy`, squared for CD, WD and MD as scipy returns them, and the
 * root of the square for L2-star, as it returns that one.
 */
export function discrepancy2d(u, v, method = 'WD') {
	const n = u.length;
	if (!n) return NaN;
	let pair = 0;
	let one = 0;
	switch (method) {
		case 'CD': {
			for (let i = 0; i < n; i++) {
				const ai = Math.abs(u[i] - 0.5);
				const bi = Math.abs(v[i] - 0.5);
				one += (1 + 0.5 * ai - 0.5 * ai * ai) * (1 + 0.5 * bi - 0.5 * bi * bi);
				for (let j = 0; j < n; j++) {
					const aj = Math.abs(u[j] - 0.5);
					const bj = Math.abs(v[j] - 0.5);
					pair += (1 + 0.5 * ai + 0.5 * aj - 0.5 * Math.abs(u[i] - u[j]))
						* (1 + 0.5 * bi + 0.5 * bj - 0.5 * Math.abs(v[i] - v[j]));
				}
			}
			return (13 / 12) ** 2 - (2 / n) * one + pair / (n * n);
		}
		case 'MD': {
			for (let i = 0; i < n; i++) {
				const ai = Math.abs(u[i] - 0.5);
				const bi = Math.abs(v[i] - 0.5);
				one += (5 / 3 - 0.25 * ai - 0.25 * ai * ai) * (5 / 3 - 0.25 * bi - 0.25 * bi * bi);
				for (let j = 0; j < n; j++) {
					const aj = Math.abs(u[j] - 0.5);
					const bj = Math.abs(v[j] - 0.5);
					const du = Math.abs(u[i] - u[j]);
					const dv = Math.abs(v[i] - v[j]);
					pair += (15 / 8 - 0.25 * ai - 0.25 * aj - 0.75 * du + 0.5 * du * du)
						* (15 / 8 - 0.25 * bi - 0.25 * bj - 0.75 * dv + 0.5 * dv * dv);
				}
			}
			return (19 / 12) ** 2 - (2 / n) * one + pair / (n * n);
		}
		case 'L2-star': {
			for (let i = 0; i < n; i++) {
				one += (1 - u[i] * u[i]) * (1 - v[i] * v[i]);
				for (let j = 0; j < n; j++) pair += (1 - Math.max(u[i], u[j])) * (1 - Math.max(v[i], v[j]));
			}
			return Math.sqrt(Math.max(0, (1 / 3) ** 2 - ((2 ** (1 - 2)) / n) * one + pair / (n * n)));
		}
		default: {
			for (let i = 0; i < n; i++) {
				for (let j = 0; j < n; j++) {
					const du = Math.abs(u[i] - u[j]);
					const dv = Math.abs(v[i] - v[j]);
					pair += (1.5 - du * (1 - du)) * (1.5 - dv * (1 - dv));
				}
			}
			return -((4 / 3) ** 2) + pair / (n * n);
		}
	}
}

/**
 * Each input's share of the discrepancy, SALib's `discrepancy.analyze`.
 *
 * @param {ArrayLike<number>[]} us  one column per input, each in [0, 1]
 * @param {ArrayLike<number>} y     the output, which is scaled to [0, 1] here
 * @returns {{shares: Float64Array, raw: Float64Array}}
 */
export function discrepancyShares(us, y, method = 'WD') {
	let lo = Infinity;
	let hi = -Infinity;
	for (let i = 0; i < y.length; i++) { lo = Math.min(lo, y[i]); hi = Math.max(hi, y[i]); }
	const v = new Float64Array(y.length);
	for (let i = 0; i < y.length; i++) v[i] = (y[i] - lo) / (hi - lo);
	const raw = Float64Array.from(us, (u) => discrepancy2d(u, v, method));
	let sum = 0;
	for (const d of raw) sum += d;
	return { shares: raw.map((d) => d / sum), raw };
}

/** A sample's column as probabilities: its average ranks over n, less a half. */
export function rankProbabilities(x) {
	const n = x.length;
	const order = Array.from({ length: n }, (_, i) => i).sort((a, b) => x[a] - x[b]);
	const out = new Float64Array(n);
	for (let p = 0; p < n;) {
		let q = p;
		while (q + 1 < n && x[order[q + 1]] === x[order[p]]) q++;
		const r = (p + q) / 2 + 0.5;
		for (let k = p; k <= q; k++) out[order[k]] = r / n;
		p = q + 1;
	}
	return out;
}

/* -------------------------------------------------------------------------
 * The radial one-at-a-time design, Campolongo, Saltelli and Cariboni 2011.
 *
 * `N` base points and as many independent perturbation points; each base
 * point is run as it is and then once per input with that one input taken
 * from its perturbation point. `N(K + 1)` runs, and two readings of them: the
 * elementary effect of each move, as Morris's but from points spread over
 * the whole space, and Jansen's estimate of the total Sobol index from the
 * same differences.
 * ---------------------------------------------------------------------- */

/**
 * @param {number} K
 * @param {Float64Array[]} base  one column of N uniforms per input
 * @param {Float64Array[]} step  the perturbation points, likewise
 */
export function radialDesign(K, base, step) {
	const N = base[0]?.length ?? 0;
	const per = K + 1;
	const u = Array.from({ length: K }, () => new Float64Array(N * per));
	for (let j = 0; j < N; j++) {
		for (let p = 0; p < per; p++) for (let k = 0; k < K; k++) u[k][j * per + p] = base[k][j];
		for (let k = 0; k < K; k++) u[k][j * per + 1 + k] = step[k][j];
	}
	return { method: 'radial', K, N, per, base, step, u, runs: N * per };
}

/**
 * The elementary effects and the total indices of a radial design, with
 * bootstrap intervals on μ* and Sₜ.
 *
 * @param {Float64Array} y
 * @param {object} design  from `radialDesign`
 * @param {{resamples?: number, conf?: number, next?: () => number, indices?: Int32Array,
 *   stIndices?: Int32Array}} [o]  the resamples are drawn from `next` unless
 *   given; `stIndices` for Sₜ's own, which default to the same
 */
export function radialIndices(y, design, { resamples = 100, conf = 0.95, next = Math.random, indices = null, stIndices = null } = {}) {
	const { K, N, per, base, step } = design;
	const ee = Array.from({ length: K }, () => new Float64Array(N));
	const d = Array.from({ length: K }, () => new Float64Array(N));
	const yb = new Float64Array(N);
	for (let j = 0; j < N; j++) {
		yb[j] = y[j * per];
		for (let k = 0; k < K; k++) {
			const diff = yb[j] - y[j * per + 1 + k];
			d[k][j] = diff;
			const e = diff / (base[k][j] - step[k][j]);
			// numpy's `nan_to_num`: nothing for a 0/0, the largest number for a
			// division by zero.
			ee[k][j] = Number.isNaN(e) ? 0 : e === Infinity ? Number.MAX_VALUE : e === -Infinity ? -Number.MAX_VALUE : e;
		}
	}
	const R = resamples;
	const idx = R > 1 ? (indices ?? resampleIndices(N, R, next)) : null;
	const idxT = R > 1 ? (stIndices ?? idx) : null;
	const z = zOf(conf);
	const varB = varOf(yb);
	const mu = new Float64Array(K);
	const muStar = new Float64Array(K);
	const sigma = new Float64Array(K);
	const muStarCi = new Float64Array(K).fill(NaN);
	const ST = new Float64Array(K);
	const STci = new Float64Array(K).fill(NaN);
	const at = new Float64Array(R);
	for (let k = 0; k < K; k++) {
		mu[k] = meanOf(ee[k]);
		muStar[k] = meanOf(ee[k].map(Math.abs));
		sigma[k] = sdOf(ee[k], 1);
		let s = 0;
		for (let j = 0; j < N; j++) s += d[k][j] ** 2;
		ST[k] = s / (2 * N) / varB;
		if (!idx) continue;
		for (let r = 0; r < R; r++) {
			let a = 0;
			for (let j = 0; j < N; j++) a += Math.abs(ee[k][idx[r * N + j]]);
			at[r] = a / N;
		}
		muStarCi[k] = z * sdOf(at, 1);
		for (let r = 0; r < R; r++) {
			// Resampled whole: the base point, its perturbation and so the
			// variance the index is a share of.
			let a = 0;
			const b = new Float64Array(N);
			for (let j = 0; j < N; j++) {
				const i = idxT[r * N + j];
				a += d[k][i] ** 2;
				b[j] = yb[i];
			}
			at[r] = a / (2 * N) / varOf(b);
		}
		STci[k] = z * sdOf(at, 1);
	}
	return { mu, muStar, sigma, muStarCi, ST, STci, effects: ee };
}

/* -------------------------------------------------------------------------
 * Morris's trajectories, as SALib samples them.
 *
 * Each of `r` trajectories starts at a random point of a `p`-level grid in the
 * lower half of each input's range and moves every input once, in a random
 * order and a random direction, by half the levels: K + 1 runs. That is
 * Morris's 1991 design, which GlobalSensitivity.jl's random walks are not.
 * Campolongo, Cariboni and Saltelli's refinement is to draw more candidates
 * than are wanted and keep the ones most spread out over the inputs, which
 * Ruano, Ewald and Kolar's local search does in seconds where trying every
 * combination would take a lifetime.
 * ---------------------------------------------------------------------- */

/**
 * One trajectory, in levels (0 to p - 1): `(K + 1)` rows of `K`.
 *
 * @param {number} K
 * @param {number} p  levels, even
 * @param {() => number} next
 */
export function morrisTrajectory(K, p, next) {
	const half = p / 2;
	// Which input moves at each step, and which way.
	const order = Array.from({ length: K }, (_, k) => k);
	for (let i = K - 1; i > 0; i--) {
		const j = Math.floor(next() * (i + 1));
		[order[i], order[j]] = [order[j], order[i]];
	}
	const dir = Array.from({ length: K }, () => (next() < 0.5 ? -1 : 1));
	// The start, from the lower half of the levels, so a step up stays in range.
	const start = Array.from({ length: K }, () => Math.floor(next() * half));
	const rows = [];
	const at = start.slice();
	// A step down starts from the top: the trajectory is Morris's B*, which
	// moves an input from x* to x* + Δ or back, whichever its direction says.
	for (let k = 0; k < K; k++) if (dir[k] < 0) at[k] += half;
	rows.push(at.slice());
	for (const k of order) {
		at[k] += dir[k] * half;
		rows.push(at.slice());
	}
	return rows;
}

/**
 * SALib's distance between two trajectories: every point of one to every
 * point of the other, Euclidean, summed -- held in single precision, as SALib
 * holds its distance matrix, so a tie is broken where SALib breaks it.
 */
export function trajectoryDistance(m, l) {
	let s = 0;
	let same = m.length === l.length;
	for (let a = 0; a < m.length; a++) {
		for (let b = 0; b < l.length; b++) {
			let q = 0;
			for (let k = 0; k < m[a].length; k++) q += (m[a][k] - l[b][k]) ** 2;
			s += Math.sqrt(q);
		}
		if (same) for (let k = 0; k < m[a].length; k++) if (m[a][k] !== l[a][k]) same = false;
	}
	return same ? 0 : Math.fround(s);
}

/** SALib's `sum_distances`: the root of the summed squared distances between every pair. */
function spread(indices, D) {
	let s = 0;
	for (let a = 0; a < indices.length; a++) {
		for (let b = a + 1; b < indices.length; b++) s += D[indices[a]][indices[b]] ** 2;
	}
	return Math.sqrt(s);
}

/** The position of the largest, the last of equals as numpy's `argsort()[-1]` has it. */
function lastMax(values) {
	let best = 0;
	for (let i = 1; i < values.length; i++) if (values[i] >= values[best]) best = i;
	return best;
}

/**
 * The `k` most spread-out of the candidate trajectories: SALib's
 * `LocalOptimisation.find_local_maximum`, Ruano et al. 2012.
 *
 * @param {number[][][]} candidates  trajectories, each (K + 1) rows of K
 * @param {number} k
 * @returns {number[]} which candidates, ascending
 */
export function optimalTrajectories(candidates, k) {
	const N = candidates.length;
	if (k >= N) return candidates.map((_, i) => i);
	const D = Array.from({ length: N }, () => new Float64Array(N));
	for (let j = 0; j < N; j++) {
		for (let l = j + 1; l < N; l++) {
			const d = trajectoryDistance(candidates[j], candidates[l]);
			D[j][l] = d;
			D[l][j] = d;
		}
	}
	const byRow = D.map((row) => Array.from(row.keys()).sort((a, b) => row[a] - row[b] || a - b));
	const tried = [];
	const scores = [];
	for (let i = 1; i < k; i++) {
		// Each row's i farthest, and the row itself.
		const sets = byRow.map((order, r) => [...order.slice(N - i).reverse(), r]);
		let best = sets[lastMax(sets.map((s) => spread(s, D)))];
		for (let m = 1; m <= k - i - 1; m++) {
			const grown = [];
			for (let c = 0; c < N; c++) if (!best.includes(c)) grown.push([...best, c]);
			best = grown[lastMax(grown.map((s) => spread(s, D)))];
		}
		tried.push(best);
		scores.push(spread(best, D));
	}
	return [...tried[lastMax(scores)]].sort((a, b) => a - b);
}

/**
 * A trajectory design: `trajectories` of them, K + 1 runs each, in probability
 * at the middles of the level slices. With `candidates` above the number
 * wanted, that many are drawn and the most spread out kept.
 */
export function morrisTrajectoryDesign(K, { trajectories = 10, levels = 4, candidates = 0, next }) {
	const p = Math.max(2, 2 * Math.round(levels / 2));
	const drawn = Math.max(trajectories, Math.round(candidates) || 0);
	const all = Array.from({ length: drawn }, () => morrisTrajectory(K, p, next));
	const keep = drawn > trajectories ? optimalTrajectories(all, trajectories) : all.map((_, i) => i);
	const points = K + 1;
	const u = Array.from({ length: K }, () => new Float64Array(keep.length * points));
	keep.forEach((c, t) => {
		all[c].forEach((row, s) => {
			for (let k = 0; k < K; k++) u[k][t * points + s] = (row[k] + 0.5) / p;
		});
	});
	return {
		method: 'morris', design: 'trajectories', K, trajectories: keep.length, points, levels: p,
		candidates: drawn, u, runs: keep.length * points,
	};
}

/**
 * The bootstrap interval on μ*, SALib's `_compute_mu_star_confidence`: the
 * elementary effects of each input resampled with replacement.
 *
 * @param {ArrayLike<number>[]} effects  per input
 * @param {{resamples?: number, conf?: number, next?: () => number,
 *   indices?: (k: number, n: number) => Int32Array}} [o]
 */
export function muStarInterval(effects, { resamples = 100, conf = 0.95, next = Math.random, indices = null } = {}) {
	const z = zOf(conf);
	return Float64Array.from(effects, (e, k) => {
		const n = e.length;
		if (n < 2 || resamples < 2) return NaN;
		const idx = indices ? indices(k, n) : resampleIndices(n, resamples, next);
		const at = new Float64Array(resamples);
		for (let r = 0; r < resamples; r++) {
			let s = 0;
			for (let i = 0; i < n; i++) s += Math.abs(e[idx[r * n + i]]);
			at[r] = s / n;
		}
		return z * sdOf(at, 1);
	});
}

/* -------------------------------------------------------------------------
 * Sobol's indices: SALib's bootstrap interval.
 *
 * The runs of a Saltelli design resampled row by row -- the same rows of A, B
 * and every A_B -- and the indices worked out again from each resample, on
 * the output standardised as SALib standardises it and with numpy's
 * variance; the interval is the spread of those. One design is enough, where
 * blocks need several.
 * ---------------------------------------------------------------------- */

/**
 * @param {Float64Array} y  over a one-block design laid out as `sobolDesign` lays it
 * @param {{K: number, n: number, second?: boolean}} d
 * @param {{resamples?: number, conf?: number, next?: () => number, indices?: Int32Array}} [o]
 *   `indices[r * n + i]`, as `resampleIndices`
 * @returns {{S1ci: Float64Array, STci: Float64Array, S2ci: Float64Array|null}}
 */
export function sobolBootstrap(y, { K, n, second = false }, { resamples = 100, conf = 0.95, next = Math.random, indices = null } = {}) {
	const R = resamples;
	const idx = indices ?? resampleIndices(n, R, next);
	const per = (second ? 2 * K + 2 : K + 2) * n;
	const m = meanOf(y.subarray(0, per));
	const sd = Math.sqrt(varOf(y.subarray(0, per)));
	const Y = (i) => (y[i] - m) / sd;
	const col = (c) => (i) => Y(c * n + i);
	const A = col(0);
	const B = col(1);
	const AB = (k) => col(2 + k);
	const BA = (k) => col(2 + K + k);
	const z = zOf(conf);
	// The two estimators on one resample: SALib's `first_order` and
	// `total_order`, over `np.var(np.r_[A, B])`.
	const varAB = (rows) => {
		let s = 0;
		for (const i of rows) s += A(i) + B(i);
		const mean = s / (2 * rows.length);
		let ss = 0;
		for (const i of rows) ss += (A(i) - mean) ** 2 + (B(i) - mean) ** 2;
		return ss / (2 * rows.length);
	};
	const S1ci = new Float64Array(K);
	const STci = new Float64Array(K);
	const S2ci = second ? new Float64Array(K * K).fill(NaN) : null;
	const rowsOf = (r) => Array.from({ length: n }, (_, i) => idx[i * R + r]);
	const resampled = Array.from({ length: R }, (_, r) => rowsOf(r));
	const vars = resampled.map(varAB);
	const first = (rows, v, ab) => {
		let s = 0;
		for (const i of rows) s += B(i) * (ab(i) - A(i));
		return s / rows.length / v;
	};
	for (let k = 0; k < K; k++) {
		const f = new Float64Array(R);
		const t = new Float64Array(R);
		for (let r = 0; r < R; r++) {
			const rows = resampled[r];
			f[r] = first(rows, vars[r], AB(k));
			let s = 0;
			for (const i of rows) s += (A(i) - AB(k)(i)) ** 2;
			t[r] = (0.5 * s) / rows.length / vars[r];
		}
		S1ci[k] = z * sdOf(f, 1);
		STci[k] = z * sdOf(t, 1);
	}
	if (second) {
		for (let j = 0; j < K; j++) {
			for (let k = j + 1; k < K; k++) {
				const s2 = new Float64Array(R);
				for (let r = 0; r < R; r++) {
					const rows = resampled[r];
					let s = 0;
					for (const i of rows) s += BA(j)(i) * AB(k)(i) - A(i) * B(i);
					s2[r] = s / rows.length / vars[r] - first(rows, vars[r], AB(j)) - first(rows, vars[r], AB(k));
				}
				S2ci[j * K + k] = z * sdOf(s2, 1);
			}
		}
	}
	return { S1ci, STci, S2ci };
}

/* -------------------------------------------------------------------------
 * The fractional factorial's interactions, and RBD-FAST's bias.
 * ---------------------------------------------------------------------- */

/**
 * Every pair's two-way interaction effect, SALib's `ff.interactions`: the
 * output's contrast with the product of the two inputs' signs. In a design of
 * resolution IV these are aliased with one another -- what is measured for a
 * pair is the sum over every pair aliased with it -- but clear of the main
 * effects.
 *
 * @param {Float64Array} y
 * @param {{K: number, rows: number, signs: ArrayLike<number>[]}} design  from `ffDesign`
 * @returns {Array<{a: number, b: number, value: number}>}
 */
export function ffInteractions(y, { K, rows, signs }) {
	const out = [];
	for (let b = 0; b < K; b++) {
		for (let a = 0; a < b; a++) {
			let s = 0;
			for (let r = 0; r < rows; r++) s += y[r] * signs[r][a] * signs[r][b];
			out.push({ a, b, value: s / rows });
		}
	}
	return out;
}

/**
 * Tissot and Prieur's correction of an RBD-FAST first-order index for the
 * bias a random design leaves in it -- SALib's `unskew_S1`, with `M` the
 * harmonics and `N` the runs.
 */
export function unskew(S1, M, N) {
	const lambda = (2 * M) / N;
	return S1 - (lambda / (1 - lambda)) * (1 - S1);
}

/* -------------------------------------------------------------------------
 * DGSM: the spread of the squared derivative, and SALib's interval on ν.
 * ---------------------------------------------------------------------- */

/**
 * @param {Float64Array} g  `g[i·K + k]`, as `dgsmDerivatives` gives them
 * @param {number} K
 * @param {number} N
 * @param {{resamples?: number, conf?: number, next?: () => number,
 *   indices?: (k: number) => Int32Array}} [o]  each input's resamples, drawn
 *   afresh for each as SALib draws them unless given
 * @returns {{sd: Float64Array, ci: Float64Array}} the standard deviation of the
 *   squared derivative (numpy's, over n) and the half-width of the interval
 *   on its mean, ν, from the points resampled
 */
export function dgsmSpread(g, K, N, { resamples = 100, conf = 0.95, next = Math.random, indices = null } = {}) {
	const sd = new Float64Array(K);
	const ci = new Float64Array(K).fill(NaN);
	const z = zOf(conf);
	for (let k = 0; k < K; k++) {
		const sq = new Float64Array(N);
		for (let i = 0; i < N; i++) sq[i] = g[i * K + k] ** 2;
		sd[k] = Math.sqrt(varOf(sq));
		if (resamples < 2) continue;
		const idx = indices ? indices(k) : resampleIndices(N, resamples, next);
		const at = new Float64Array(resamples);
		for (let r = 0; r < resamples; r++) {
			let s = 0;
			for (let i = 0; i < N; i++) s += sq[idx[r * N + i]];
			at[r] = s / N;
		}
		ci[k] = z * sdOf(at, 1);
	}
	return { sd, ci };
}
