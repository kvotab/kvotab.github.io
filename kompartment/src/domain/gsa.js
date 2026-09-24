/**
 * Global sensitivity analysis: the methods of GlobalSensitivity.jl.
 *
 * ./sensitivity.js answers "which inputs does this output move with" from the
 * sample a probabilistic run has already drawn: correlations and regressions.
 * This is the rest of the field as SciML's GlobalSensitivity.jl
 * (github.com/SciML/GlobalSensitivity.jl, MIT) collects it, ported from its
 * source at v2.12.8:
 *
 *   - **designed**, each with an experiment of its own that the model is run
 *     over: Morris's elementary effects, Sobol's variance decomposition,
 *     eFAST, RBD-FAST, a two-level fractional factorial, derivative-based
 *     measures (DGSM) and Shapley effects;
 *   - **from a sample**, reading any sample the way the correlations do: EASI,
 *     Borgonovo's moment-independent δ, regional sensitivity analysis (RSA)
 *     and mutual information. The regression family -- SRC, PCC and their
 *     rank forms -- is ./sensitivity.js's, and stays there: see below.
 *
 * **Everything is done in probability space.** GlobalSensitivity.jl takes a
 * box of bounds, `[lb, ub]` per input, and draws its designs in it. A model
 * here has distributions instead -- a log-triangular sorption coefficient, a
 * normal with no bounds at all -- so each design is drawn in the unit
 * hypercube, `u` in (0, 1) per input, and a point becomes a run through each
 * input's inverse CDF, exactly as a Latin hypercube sample does
 * (`valueAtProbability`). A method written for uniform inputs is then
 * correct for every distribution, and an elementary effect or a derivative is
 * per unit of probability, so the inputs are comparable with each other
 * whatever their units. It is what GlobalSensitivity.jl itself does when it is
 * handed distributions (eFAST), and what SALib does for all of them.
 *
 * **Where this differs from GlobalSensitivity.jl, on purpose:**
 *
 *   - The designs are drawn from the tool's own seeded streams, one per input,
 *     Latin hypercube where a method samples freely -- not from Julia's RNG or
 *     a Sobol sequence. A run is a function of its seed, and the same seed
 *     gives the same columns to an input whatever other inputs the model has
 *     gained (see `streamFor`).
 *   - Morris's levels are the middles of `p` equal slices of probability,
 *     `(j + ½)/p`, rather than a grid that includes both ends: the ends of an
 *     unbounded distribution are infinite. Its candidate trajectories are not
 *     generated: in probability space every trajectory has the same spread --
 *     each step moves one input one level -- so the selection keeps the first
 *     ones it is given and the rest are never used.
 *   - eFAST raises the number of points per curve to the next one at which
 *     the harmonics fit under the Nyquist frequency; GlobalSensitivity.jl
 *     indexes past the end of its spectrum there and stops.
 *   - DGSM differentiates with respect to probability by finite differences,
 *     where GlobalSensitivity.jl differentiates the Julia function with respect
 *     to the value by automatic differentiation. A model here is an ODE solve,
 *     not a function a dual number can be pushed through. In probability space
 *     its `sigma` and `tao`, written for inputs on [0, 1], hold for every
 *     distribution.
 *   - A fractional factorial of one input is two runs; GlobalSensitivity.jl
 *     cannot build a Hadamard matrix of order one.
 *   - RSA's spread of the dummy inputs is over all of them. GlobalSensitivity.jl
 *     leaves the first out of the standard deviation (`+ 1 + 1`), which reads as
 *     a slip.
 *   - δ's density of a class of realisations whose outputs are all the same
 *     takes the whole output's bandwidth; KernelDensity.jl takes 0.9 in the
 *     output's units, which is a spike no grid resolves (see `kdeBandwidth`).
 *     Outputs with ties are the rule in a model that holds a value until a
 *     release arrives, and there it gave a δ in the millions.
 *   - Its regression method fits without an intercept and ranks by `sortperm`,
 *     which is the permutation that sorts and not the ranks. ./sensitivity.js
 *     centres and ranks properly, and is what the tool reports.
 *
 * Each estimator is otherwise the same arithmetic, and ../../test/run.js
 * checks them against GlobalSensitivity.jl's own results on the same designs
 * and data (`test/fixtures/gsa-reference.json`, from `scripts/gen-gsa-ref.jl`).
 *
 * **And what SALib adds**, from ./salib.js, which the registry below offers
 * beside them: the radial one-at-a-time design, Morris's own trajectories with
 * the optimal selection, bootstrap intervals on μ*, the Sobol indices and ν,
 * the fractional factorial's interactions and RBD-FAST's bias correction --
 * and, for a plain sample, PAWN and discrepancy.
 */

import { rfft, irfft, powerSpectrum, dct2 } from './fft.js';
import { phi, normalQuantile } from './pdf.js';
import {
	radialDesign, radialIndices, morrisTrajectoryDesign, muStarInterval, sobolBootstrap,
	ffInteractions, unskew, dgsmSpread,
} from './salib.js';

/* -------------------------------------------------------------------------
 * The small things every method needs, done the way Julia's Statistics does
 * them, so that the same data give the same numbers.
 * ---------------------------------------------------------------------- */

// The standard normal's inverse CDF, to full precision, lives with the
// distributions and is exported from here too for what already reads it here.
export { normalQuantile };

function mean(a, from = 0, to = a.length) {
	let s = 0;
	for (let i = from; i < to; i++) s += a[i];
	return s / (to - from);
}

/** The sample variance, over n - 1, in two passes as Julia's `var` does. */
function variance(a, from = 0, to = a.length) {
	const n = to - from;
	const m = mean(a, from, to);
	let s = 0;
	for (let i = from; i < to; i++) s += (a[i] - m) ** 2;
	return s / (n - 1);
}

const std = (a) => Math.sqrt(variance(a));

/**
 * Julia's default `quantile`, Hyndman and Fan's type 7: linear between the
 * order statistics either side of `(n - 1)p + 1`.
 */
export function quantile7(values, p) {
	const v = Float64Array.from(values).sort();
	const n = v.length;
	if (n === 1) return v[0];
	const aleph = n * p + (1 - p);
	const j = Math.min(n - 1, Math.max(1, Math.trunc(aleph)));
	const g = Math.min(1, Math.max(0, aleph - j));
	const a = v[j - 1];
	const b = v[j];
	return a + g * (b - a);
}

/** Ranks from 1, ties sharing the mean of the places they span. */
export function averageRanks(x) {
	const order = sortPerm(x);
	const r = new Float64Array(x.length);
	for (let p = 0; p < order.length;) {
		let q = p;
		while (q + 1 < order.length && x[order[q + 1]] === x[order[p]]) q++;
		const mid = (p + q) / 2 + 1;
		for (let j = p; j <= q; j++) r[order[j]] = mid;
		p = q + 1;
	}
	return r;
}

/**
 * Normal scores: each value replaced by the standard normal's quantile at its
 * rank, `Φ⁻¹((r - ½)/n)`. The same order, and a marginal that a Gaussian
 * kernel and Silverman's rule were made for.
 */
export function normalScores(y) {
	const r = averageRanks(y);
	const n = y.length;
	return r.map((v) => normalQuantile((v - 0.5) / n));
}

/** The indices that sort `x`, ties in their original order. */
export function sortPerm(x) {
	const idx = Array.from({ length: x.length }, (_, i) => i);
	idx.sort((a, b) => (x[a] < x[b] ? -1 : x[a] > x[b] ? 1 : a - b));
	return idx;
}

/**
 * Competition ranks ("1224"): a tie takes the lowest rank of the places it
 * spans, as StatsBase's `competerank` does.
 */
export function competeRank(x) {
	const order = sortPerm(x);
	const r = new Float64Array(x.length);
	for (let p = 0; p < order.length; p++) {
		const i = order[p];
		r[i] = p > 0 && x[order[p - 1]] === x[i] ? r[order[p - 1]] : p + 1;
	}
	return r;
}

/** `sin(πx)`, reduced exactly first, as Julia's `sinpi`. */
export function sinpi(x) {
	let r = x % 2;
	if (r < 0) r += 2;
	if (r < 0.25) return Math.sin(Math.PI * r);
	if (r < 0.75) return Math.cos(Math.PI * (r - 0.5));
	if (r < 1.25) return -Math.sin(Math.PI * (r - 1));
	if (r < 1.75) return -Math.cos(Math.PI * (r - 1.5));
	return Math.sin(Math.PI * (r - 2));
}

/** `n` evenly spaced from `a` to `b`, both included. */
function linspace(a, b, n) {
	const out = new Float64Array(n);
	if (n === 1) { out[0] = a; return out; }
	const step = (b - a) / (n - 1);
	for (let i = 0; i < n; i++) out[i] = a + i * step;
	out[n - 1] = b;
	return out;
}

/** A uniformly random permutation of 0..n-1, Fisher-Yates from the end. */
export function randomPermutation(n, next) {
	const p = Array.from({ length: n }, (_, i) => i);
	for (let i = n - 1; i > 0; i--) {
		const j = Math.floor(next() * (i + 1));
		const t = p[i]; p[i] = p[j]; p[j] = t;
	}
	return p;
}

/** A standard normal from two uniforms, Box-Muller; the stream decides both. */
function gaussian(next) {
	let u = next();
	while (!(u > 0)) u = next();
	const v = next();
	return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/** Every permutation of 0..n-1, in lexicographic order, as Combinatorics'. */
export function permutationsOf(n) {
	const out = [];
	const a = Array.from({ length: n }, (_, i) => i);
	for (;;) {
		out.push(a.slice());
		let i = n - 2;
		while (i >= 0 && a[i] >= a[i + 1]) i--;
		if (i < 0) return out;
		let j = n - 1;
		while (a[j] <= a[i]) j--;
		[a[i], a[j]] = [a[j], a[i]];
		for (let l = i + 1, r = n - 1; l < r; l++, r--) [a[l], a[r]] = [a[r], a[l]];
	}
}

/** Unit-hypercube columns, one per factor, `points` long. */
function columns(K, points) {
	return Array.from({ length: K }, () => new Float64Array(points));
}

/* -------------------------------------------------------------------------
 * Morris's elementary effects.
 *
 * GlobalSensitivity.jl's variant, which is a random walk rather than the
 * textbook trajectory: each of `trajectories` walks is `points` long, and
 * every step moves one input, chosen at random, one level up or down on a grid
 * of `levels`, bouncing off the ends. An elementary effect is the change in
 * the output over the change in the input; its mean says how much an input
 * matters and in which direction, the mean of its absolute value (μ*) how
 * much whatever the direction, and its variance how much the effect depends
 * on where it is taken -- a curve, or an interaction.
 * ---------------------------------------------------------------------- */

/**
 * @param {number} K
 * @param {{trajectories?: number, points?: number, levels?: number, next: () => number}} o
 */
export function morrisDesign(K, { trajectories = 10, points = 10, levels = 100, next }) {
	if (!(levels >= 2)) throw new Error('Morris needs at least two levels.');
	if (!(points >= 2)) throw new Error('A Morris trajectory needs at least two points.');
	const u = columns(K, trajectories * points);
	const at = new Int32Array(K);
	for (let t = 0; t < trajectories; t++) {
		// `rand(rng, 1:p)` for each input: where the walk starts.
		for (let k = 0; k < K; k++) at[k] = Math.floor(next() * levels);
		for (let s = 0; s < points; s++) {
			const j = Math.floor(next() * K);
			at[j] += next() < 0.5 ? -1 : 1;
			if (at[j] > levels - 1) at[j] -= 2;
			else if (at[j] < 0) at[j] += 2;
			for (let k = 0; k < K; k++) u[k][t * points + s] = (at[k] + 0.5) / levels;
		}
	}
	return { method: 'morris', K, trajectories, points, levels, u, runs: trajectories * points };
}

/**
 * @returns {{mean: Float64Array, meanStar: Float64Array, variance: Float64Array,
 *   count: Int32Array, effects: number[][]}} per input; an input no step moved
 *   has a count of 0. `effects` are the elementary effects themselves, in the
 *   order the design made them, for an interval on μ* (see ./salib.js).
 */
export function morrisIndices(y, design, { relative = false } = {}) {
	const { K, trajectories, points, u } = design;
	const effects = Array.from({ length: K }, () => []);
	for (let t = 0; t < trajectories; t++) {
		let y1 = y[t * points];
		for (let j = t * points; j < (t + 1) * points - 1; j++) {
			const y2 = y1;
			let changed = -1;
			let del = 0;
			for (let k = 0; k < K; k++) {
				const d = u[k][j + 1] - u[k][j];
				if (changed < 0 && Math.abs(d) > 0) changed = k;
				del += d;
			}
			y1 = y[j + 1];
			let e;
			if (!relative) e = (y1 - y2) / del;
			else e = del > 0 ? (y1 - y2) / (y2 * del) : (y1 - y2) / (y1 * del);
			if (changed >= 0) effects[changed].push(e);
		}
	}
	const out = {
		mean: new Float64Array(K), meanStar: new Float64Array(K),
		variance: new Float64Array(K), count: new Int32Array(K), effects,
	};
	for (let k = 0; k < K; k++) {
		const e = effects[k];
		out.count[k] = e.length;
		if (!e.length) continue;
		out.mean[k] = mean(e);
		out.meanStar[k] = mean(e.map(Math.abs));
		// One effect has no spread; Julia says NaN, and so does this.
		out.variance[k] = e.length > 1 ? variance(e) : NaN;
	}
	return out;
}

/* -------------------------------------------------------------------------
 * Sobol's indices, by Saltelli's design.
 *
 * Two independent samples A and B of `n` points each, and for every input a
 * third, A with that one input's column taken from B. The first-order index
 * S₁ is the share of the output's variance that input explains alone
 * (Saltelli 2010's estimator); the total index Sₜ the share it has a hand in,
 * interactions included (Jansen 1999's by default; Homma and Saltelli 1996,
 * Sobol 2007 and Janon 2014 are the other choices GlobalSensitivity.jl
 * offers). Second order adds B with each column from A, and gives every
 * pair's interaction. `blocks` repeats the whole design that many times and
 * reports the mean, with a confidence interval from the spread between them.
 * ---------------------------------------------------------------------- */

export const SOBOL_ESTIMATORS = ['jansen1999', 'sobol2007', 'homma1996', 'janon2014'];

/** How many runs a Sobol design is: (K + 2)n per block, (2K + 2)n with pairs. */
export function sobolRuns(K, n, { second = false, blocks = 1 } = {}) {
	return blocks * (second ? 2 * K + 2 : K + 2) * n;
}

/**
 * @param {number} K
 * @param {number} n  points in each of A and B
 * @param {object} o
 * @param {(k: number, which: 'A'|'B', block: number) => Float64Array} o.draw
 *   the n uniforms of factor k in A or B
 */
export function sobolDesign(K, n, { second = false, blocks = 1, draw }) {
	const per = (second ? 2 * K + 2 : K + 2) * n;
	const u = columns(K, blocks * per);
	for (let b = 0; b < blocks; b++) {
		const base = b * per;
		for (let k = 0; k < K; k++) {
			const A = draw(k, 'A', b);
			const B = draw(k, 'B', b);
			const col = u[k];
			col.set(A, base);
			col.set(B, base + n);
			// A with column j from B, for each j; then B with column j from A.
			for (let j = 0; j < K; j++) col.set(k === j ? B : A, base + (2 + j) * n);
			if (second) {
				for (let j = 0; j < K; j++) col.set(k === j ? A : B, base + (2 + K + j) * n);
			}
		}
	}
	return { method: 'sobol', K, n, second, blocks, u, runs: blocks * per };
}

/**
 * @returns {{S1, ST, S2, S1ci, STci, S2ci}} `S2` is K×K, row-major, the upper
 *   triangle filled; the intervals are null for one block
 */
export function sobolIndices(y, { K, n, second = false, blocks = 1, estimator = 'jansen1999', conf = 0.95 }) {
	const step = second ? 2 * K + 2 : K + 2;
	const S1s = [];
	const STs = [];
	const S2s = [];
	for (let b = 0; b < blocks; b++) {
		const base = b * step * n;
		const fA = y.subarray(base, base + n);
		const fB = y.subarray(base + n, base + 2 * n);
		const fAi = (k) => y.subarray(base + (2 + k) * n, base + (3 + k) * n);
		const fBi = (k) => y.subarray(base + (2 + K + k) * n, base + (3 + K + k) * n);
		// The variance over A and B together, 2n points.
		const vary = variance(y, base, base + 2 * n);
		const V = new Float64Array(K);
		const E = new Float64Array(K);
		let sumA = 0;
		for (let i = 0; i < n; i++) sumA += fA[i];
		for (let k = 0; k < K; k++) {
			const a = fAi(k);
			let v = 0;
			for (let i = 0; i < n; i++) v += fB[i] * (a[i] - fA[i]);
			V[k] = v / n;
			E[k] = totalEffect(estimator, fA, a, n, sumA);
		}
		const S1 = V.map((v) => v / vary);
		const ST = E.map((e) => e / vary);
		S1s.push(S1);
		STs.push(ST);
		if (second) {
			const S2 = new Float64Array(K * K);
			for (let k = 0; k < K; k++) {
				const bk = fBi(k);
				for (let j = k + 1; j < K; j++) {
					const aj = fAi(j);
					let s = 0;
					for (let i = 0; i < n; i++) s += bk[i] * aj[i] - fA[i] * fB[i];
					S2[k * K + j] = (s / n - (V[k] + V[j])) / vary;
				}
			}
			S2s.push(S2);
		}
	}
	if (blocks === 1) {
		return { S1: S1s[0], ST: STs[0], S2: second ? S2s[0] : null, S1ci: null, STci: null, S2ci: null };
	}
	const z = normalQuantile((1 + conf) / 2);
	const pool = (list, len) => {
		const m = new Float64Array(len);
		const ci = new Float64Array(len);
		for (let i = 0; i < len; i++) {
			const v = list.map((a) => a[i]);
			m[i] = mean(v);
			ci[i] = (z * std(v)) / Math.sqrt(v.length);
		}
		return [m, ci];
	};
	const [S1, S1ci] = pool(S1s, K);
	const [ST, STci] = pool(STs, K);
	const [S2, S2ci] = second ? pool(S2s, K * K) : [null, null];
	return { S1, ST, S2, S1ci, STci, S2ci };
}

/** The `E_i` term of a total index, by one of the four estimators. */
function totalEffect(estimator, fA, a, n, sumA) {
	switch (estimator) {
		case 'homma1996': {
			const m = sumA / n;
			let ss = 0;
			let dot = 0;
			for (let i = 0; i < n; i++) { ss += (fA[i] - m) ** 2; dot += fA[i] * a[i]; }
			return ss / (n - 1) - dot / n + m ** 2;
		}
		case 'sobol2007': {
			let s = 0;
			for (let i = 0; i < n; i++) s += fA[i] * (fA[i] - a[i]);
			return s / n;
		}
		case 'janon2014': {
			let sq = 0;
			let sum = 0;
			let dot = 0;
			let half = 0;
			let halfSq = 0;
			for (let i = 0; i < n; i++) {
				sq += fA[i] ** 2 + a[i] ** 2;
				sum += fA[i] + a[i];
				dot += fA[i] * a[i];
				half += (fA[i] + a[i]) / 2;
				halfSq += (fA[i] ** 2 + a[i] ** 2) / 2;
			}
			const first = sq / (2 * n) - (sum / (2 * n)) ** 2;
			const num = (1 / n) * dot - ((1 / n) * half) ** 2;
			const den = (1 / n) * halfSq - ((1 / n) * half) ** 2;
			return first * (1 - num / den);
		}
		default: {
			let s = 0;
			for (let i = 0; i < n; i++) s += (fA[i] - a[i]) ** 2;
			return s / (2 * n);
		}
	}
}

/* -------------------------------------------------------------------------
 * eFAST: Saltelli, Tarantola and Chan's extended Fourier amplitude test.
 *
 * One curve through the inputs per input: the input under study oscillates
 * at a high frequency ω₁ and every other at a lower one, so its variance is
 * the power at ω₁ and its harmonics (S₁) and what is left once everything at
 * the others' frequencies is taken away is its total (Sₜ). `samples` points
 * per curve, K curves.
 * ---------------------------------------------------------------------- */

/** The smallest number of points at or above `n` that eFAST can use with `M` harmonics. */
export function efastSamples(n, M = 4) {
	let N = Math.max(Math.round(n), 4 * M * M + 1);
	for (;;) {
		const w = Math.floor((N - 1) / (2 * M));
		if (Math.floor(w / (2 * M)) >= 1 && M * w <= Math.floor(N / 2) - 1) return N;
		N++;
	}
}

/** ω₁ and the complementary frequencies, as GlobalSensitivity.jl chooses them. */
export function efastFrequencies(K, N, M = 4) {
	const omega = [Math.floor((N - 1) / (2 * M))];
	const m = Math.floor(omega[0] / (2 * M));
	if (m >= K - 1) {
		// floor.(Int, range(1, m, length = K - 1))
		const r = K - 1 === 1 ? [1] : Array.from({ length: K - 1 }, (_, i) => 1 + (i * (m - 1)) / (K - 2));
		for (const v of r) omega.push(Math.floor(v));
	} else {
		for (let i = 0; i < K - 1; i++) omega.push((i % m) + 1);
	}
	return omega;
}

/**
 * @param {number[]} phases  one per curve, in [0, 2): `2rand(rng)`
 */
export function efastDesign(K, N, { harmonics: M = 4, phases }) {
	const omega = efastFrequencies(K, N, M);
	const u = columns(K, K * N);
	const temp = new Array(K);
	for (let i = 0; i < K; i++) {
		temp[i] = omega[0];
		for (let k = 0; k < i; k++) temp[k] = omega[k + 1];
		for (let k = i + 1; k < K; k++) temp[k] = omega[k];
		const phi0 = phases[i];
		for (let j = 0; j < K; j++) {
			const col = u[j];
			for (let r = 0; r < N; r++) {
				const s = (2 / N) * r;
				col[i * N + r] = 0.5 + (1 / Math.PI) * Math.asin(sinpi(temp[j] * s + phi0));
			}
		}
	}
	return { method: 'efast', K, N, harmonics: M, omega, u, runs: K * N };
}

export function efastIndices(y, { K, N, harmonics: M = 4, omega }) {
	const S1 = new Float64Array(K);
	const ST = new Float64Array(K);
	const w = omega[0];
	const last = Math.floor(N / 2) - 1;
	for (let i = 0; i < K; i++) {
		const P = powerSpectrum(centred(y, i * N, (i + 1) * N));
		let z = 0;
		for (let k = 1; k <= last; k++) z += P[k];
		let first = 0;
		for (let p = 1; p <= M; p++) first += P[p * w];
		let low = 0;
		for (let k = 1; k <= Math.floor(w / 2); k++) low += P[k];
		S1[i] = first / z;
		ST[i] = 1 - low / z;
	}
	return { S1, ST };
}

/**
 * A slice, less its mean. Every spectral method here reads frequencies from
 * one up, and the mean is all of frequency zero and nothing else -- so taking
 * it away changes no coefficient that is read, and keeps a large mean's
 * rounding out of the small ones that are.
 */
function centred(y, from = 0, to = y.length) {
	const m = mean(y, from, to);
	const out = new Float64Array(to - from);
	for (let i = from; i < to; i++) out[i - from] = y[i] - m;
	return out;
}

/* -------------------------------------------------------------------------
 * RBD-FAST: Tarantola, Gatelli and Mara's random balance design.
 *
 * One curve for all the inputs at once: every input runs through the same
 * periodic path in its own random order, and sorting the runs back into one
 * input's order makes the output periodic in it. Its first-order index is the
 * power in the first `harmonics` frequencies. `samples` runs in all.
 * ---------------------------------------------------------------------- */

/**
 * @param {number[][]} perms  one random permutation of 0..N-1 per input
 */
export function rbdFastDesign(K, N, { perms }) {
	const s0 = linspace(-Math.PI, Math.PI, N);
	const s = [];
	const u = columns(K, N);
	for (let k = 0; k < K; k++) {
		const sk = new Float64Array(N);
		for (let i = 0; i < N; i++) sk[i] = s0[perms[k][i]];
		s.push(sk);
		for (let i = 0; i < N; i++) u[k][i] = 0.5 + Math.asin(Math.sin(sk[i])) / Math.PI;
	}
	return { method: 'rbdfast', K, N, s, u, runs: N };
}

export function rbdFastIndices(y, { K, s }, { harmonics: H = 6 } = {}) {
	const out = new Float64Array(K);
	const N = y.length;
	for (let k = 0; k < K; k++) {
		const order = sortPerm(s[k]);
		const yp = new Float64Array(N);
		for (let i = 0; i < N; i++) yp[i] = y[order[i]];
		const P = powerSpectrum(centred(yp));
		const end = P.length - 1;
		let V = 0;
		for (let j = 1; j < end; j++) V += P[j];
		V = 2 * V + P[end];
		let Vi = 0;
		for (let j = 1; j <= H; j++) Vi += P[j];
		out[k] = (2 * Vi) / V;
	}
	return out;
}

/* -------------------------------------------------------------------------
 * A two-level fractional factorial of resolution IV (Saltelli 2008, eq. 2.31):
 * the columns of a Hadamard matrix and of its negative, each input at a low
 * or a high value. The main effect of an input is its contrast with the
 * output; `2^⌈log₂K⌉ · 2` runs.
 * ---------------------------------------------------------------------- */

/** A Sylvester-Hadamard matrix of order `k`, a power of two, by expanding window. */
export function hadamard(k) {
	const h = Array.from({ length: k }, () => new Int8Array(k).fill(1));
	h[1][1] = -1;
	let bot = 2;
	let right = 2;
	while (bot < k) {
		for (let r = 0; r < bot; r++) {
			for (let c = 0; c < right; c++) {
				const v = h[r][c];
				h[r][c + right] = v;
				h[r + bot][c] = v;
				h[r + bot][c + right] = -v;
			}
		}
		bot *= 2;
		right *= 2;
	}
	return h;
}

/**
 * @param {number} K
 * @param {{low?: number, high?: number}} o  the probabilities the two levels are at
 */
export function ffDesign(K, { low = 0.05, high = 0.95 } = {}) {
	let k2 = 2;
	while (k2 < K) k2 *= 2;
	const H = hadamard(k2);
	const rows = 2 * k2;
	const signs = Array.from({ length: rows }, (_, r) => (r < k2 ? H[r] : H[r - k2].map((v) => -v)));
	const u = columns(K, rows);
	for (let k = 0; k < K; k++) {
		for (let r = 0; r < rows; r++) u[k][r] = signs[r][k] > 0 ? high : low;
	}
	return { method: 'ff', K, rows, signs, low, high, u, runs: rows };
}

export function ffIndices(y, { K, rows, signs }) {
	const main = new Float64Array(K);
	for (let c = 0; c < K; c++) {
		let s = 0;
		for (let r = 0; r < rows; r++) s += y[r] * signs[r][c];
		main[c] = s / rows;
	}
	return { main, squared: main.map((v) => v * v) };
}

/* -------------------------------------------------------------------------
 * DGSM: Sobol and Kucherenko's derivative-based measures.
 *
 * The derivative of the output with respect to each input, at `samples`
 * points, and statistics of it: its mean `a`, the mean of its magnitude, and
 * the mean of its square ν -- which bounds the total Sobol index from above,
 * `Sₜ ≤ ν / (π² Var y)` for uniform inputs, which inputs in probability
 * space are. Each point costs K + 1 runs, one step per input; with `crossed`,
 * K(K - 1)/2 more for the mixed second derivatives.
 * ---------------------------------------------------------------------- */

/**
 * @param {Float64Array[]} base  one column of `samples` uniforms per input
 * @param {{step?: number, crossed?: boolean}} o  the step, in probability
 */
export function dgsmDesign(K, base, { step = 1e-3, crossed = false } = {}) {
	const N = base[0]?.length ?? 0;
	const per = 1 + K + (crossed ? (K * (K - 1)) / 2 : 0);
	const u = columns(K, N * per);
	// Forward, except where that would leave (0, 1): then back.
	const h = new Float64Array(N * K);
	for (let i = 0; i < N; i++) {
		for (let k = 0; k < K; k++) h[i * K + k] = base[k][i] + step < 1 ? step : -step;
		const at = i * per;
		for (let p = 0; p < per; p++) for (let k = 0; k < K; k++) u[k][at + p] = base[k][i];
		for (let k = 0; k < K; k++) u[k][at + 1 + k] += h[i * K + k];
		if (crossed) {
			let p = at + 1 + K;
			for (let a = 0; a < K; a++) {
				for (let b = a + 1; b < K; b++, p++) {
					u[a][p] += h[i * K + a];
					u[b][p] += h[i * K + b];
				}
			}
		}
	}
	return { method: 'dgsm', K, N, per, step, crossed, h, base, u, runs: N * per };
}

/**
 * The derivatives a DGSM design measured: `g[i·K + k]`, the first derivative
 * at point i along input k, and with `crossed` the mixed second ones,
 * `H[(i·K + a)·K + b]`.
 */
export function dgsmDerivatives(y, { K, N, per, crossed, h }) {
	const g = new Float64Array(N * K);
	for (let i = 0; i < N; i++) {
		const y0 = y[i * per];
		for (let k = 0; k < K; k++) g[i * K + k] = (y[i * per + 1 + k] - y0) / h[i * K + k];
	}
	let H = null;
	if (crossed) {
		H = new Float64Array(N * K * K);
		for (let i = 0; i < N; i++) {
			const at = i * per;
			let p = 1 + K;
			for (let a = 0; a < K; a++) {
				for (let b = a + 1; b < K; b++, p++) {
					const d = (y[at + p] - y[at + 1 + a] - y[at + 1 + b] + y[at])
						/ (h[i * K + a] * h[i * K + b]);
					H[(i * K + a) * K + b] = d;
					H[(i * K + b) * K + a] = d;
				}
			}
		}
	}
	const y0 = new Float64Array(N);
	for (let i = 0; i < N; i++) y0[i] = y[i * per];
	return { g, H, y0 };
}

/**
 * GlobalSensitivity.jl's statistics of the derivatives, and the bound on the
 * total index that ν gives.
 *
 * @param {Float64Array} g     `g[i·K + k]`
 * @param {Float64Array[]} base  where they were taken, in probability
 * @param {{H?: Float64Array|null, y0?: Float64Array|null}} [o]  the mixed
 *   derivatives, and the outputs at the points for the variance of the bound
 */
export function dgsmStatistics(g, base, { H = null, y0 = null } = {}) {
	const K = base.length;
	const N = base[0]?.length ?? 0;
	const a = new Float64Array(K);
	const absa = new Float64Array(K);
	const asq = new Float64Array(K);
	const sigma = new Float64Array(K);
	const tao = new Float64Array(K);
	for (let k = 0; k < K; k++) {
		let s = 0;
		let sa = 0;
		let s2 = 0;
		let st = 0;
		let ss = 0;
		for (let i = 0; i < N; i++) {
			const d = g[i * K + k];
			const x = base[k][i];
			s += d;
			sa += Math.abs(d);
			s2 += d * d;
			st += (d * d * (1 - 3 * x + x * x)) / 6;
			ss += 0.5 * x * (1 - x) * d * d;
		}
		a[k] = s / N;
		absa[k] = sa / N;
		asq[k] = s2 / N;
		tao[k] = st / N;
		sigma[k] = ss / N;
	}
	const vary = y0 && y0.length > 1 ? variance(y0) : NaN;
	const bound = asq.map((v) => v / (Math.PI * Math.PI * vary));
	let crossed = null;
	if (H) {
		crossed = { mean: new Float64Array(K * K), abs: new Float64Array(K * K), sq: new Float64Array(K * K) };
		for (let p = 0; p < K; p++) {
			for (let q = p + 1; q < K; q++) {
				let s = 0;
				let sa = 0;
				let s2 = 0;
				for (let i = 0; i < N; i++) {
					const d = H[(i * K + p) * K + q];
					s += d;
					sa += Math.abs(d);
					s2 += d * d;
				}
				for (const [m, v] of [[crossed.mean, s / N], [crossed.abs, sa / N], [crossed.sq, s2 / N]]) {
					m[p * K + q] = v;
					m[q * K + p] = v;
				}
			}
		}
	}
	return { a, absa, asq, sigma, tao, variance: vary, bound, crossed };
}

/** Both of the above, from a design's outputs. */
export function dgsmIndices(y, design) {
	const { g, H, y0 } = dgsmDerivatives(y, design);
	return dgsmStatistics(g, design.base, { H, y0 });
}

/* -------------------------------------------------------------------------
 * Shapley effects: Song, Nelson and Staum's algorithm.
 *
 * An input's Shapley effect is its share of the output's variance when every
 * other input's share is fairly attributed -- the average, over the orders in
 * which inputs could be learnt, of what learning this one adds. Unlike
 * Sobol's indices they add up to one when inputs are correlated, which is
 * what they are for: with `corr` the inputs are drawn from a Gaussian copula
 * and every conditional sample respects it. Exact over all K! orders, or
 * Monte Carlo over `perms` random ones.
 * ---------------------------------------------------------------------- */

/** The lower Cholesky factor of a symmetric matrix, or null if it is not positive definite. */
export function cholesky(A, n) {
	const L = new Float64Array(n * n);
	for (let i = 0; i < n; i++) {
		for (let j = 0; j <= i; j++) {
			let s = A[i * n + j];
			for (let k = 0; k < j; k++) s -= L[i * n + k] * L[j * n + k];
			if (i === j) {
				if (!(s > 1e-14)) return null;
				L[i * n + i] = Math.sqrt(s);
			} else {
				L[i * n + j] = s / L[j * n + j];
			}
		}
	}
	return L;
}

/** The inputs' joint law in probability space: independent, or a Gaussian copula. */
function copula(K, corr, next) {
	const sub = (idx) => {
		const m = idx.length;
		const S = new Float64Array(m * m);
		for (let a = 0; a < m; a++) for (let b = 0; b < m; b++) S[a * m + b] = corr[idx[a] * K + idx[b]];
		return S;
	};
	// z ~ N(mean, LLᵀ), returned as probabilities.
	const drawZ = (m, L, mu) => {
		const e = Array.from({ length: m }, () => gaussian(next));
		const z = new Float64Array(m);
		for (let a = 0; a < m; a++) {
			let s = mu ? mu[a] : 0;
			for (let b = 0; b <= a; b++) s += L[a * m + b] * e[b];
			z[a] = s;
		}
		return z;
	};
	const toU = (z) => z.map((v) => phi(v));
	const cache = new Map();
	return {
		/** `n` draws of the inputs `idx` from their joint marginal. */
		subset(idx, n) {
			if (!corr) return Array.from({ length: n }, () => idx.map(() => next()));
			const key = idx.join(',');
			let L = cache.get(key);
			if (!L) { L = cholesky(sub(idx), idx.length); cache.set(key, L); }
			if (!L) throw new Error('The correlations between these inputs are not a valid correlation matrix.');
			return Array.from({ length: n }, () => toU(drawZ(idx.length, L)));
		},
		/** `n` draws of the inputs `plus` given `minus` at the probabilities `uMinus`. */
		given(plus, minus, uMinus, n) {
			if (!corr) return Array.from({ length: n }, () => plus.map(() => next()));
			// GlobalSensitivity.jl's `find_cond_mean_var`: B - C'D⁻¹C, and
			// C'D⁻¹ times the conditioning values as normal scores.
			const p = plus.length;
			const q = minus.length;
			const zMinus = uMinus.map((v) => normalQuantile(v));
			const D = sub(minus);
			const Ld = cholesky(D, q);
			if (!Ld) throw new Error('The correlations between these inputs are not a valid correlation matrix.');
			// Solve D X = C for X = D⁻¹C, one column per member of `plus`.
			const X = new Float64Array(q * p);
			for (let c = 0; c < p; c++) {
				const col = new Float64Array(q);
				for (let r = 0; r < q; r++) col[r] = corr[minus[r] * K + plus[c]];
				const w = new Float64Array(q);
				for (let r = 0; r < q; r++) {
					let s = col[r];
					for (let l = 0; l < r; l++) s -= Ld[r * q + l] * w[l];
					w[r] = s / Ld[r * q + r];
				}
				for (let r = q - 1; r >= 0; r--) {
					let s = w[r];
					for (let l = r + 1; l < q; l++) s -= Ld[l * q + r] * X[l * p + c];
					X[r * p + c] = s / Ld[r * q + r];
				}
			}
			const mu = new Float64Array(p);
			const cov = new Float64Array(p * p);
			for (let a = 0; a < p; a++) {
				let s = 0;
				for (let r = 0; r < q; r++) s += X[r * p + a] * zMinus[r];
				mu[a] = s;
				for (let b = 0; b < p; b++) {
					let c = corr[plus[a] * K + plus[b]];
					for (let r = 0; r < q; r++) c -= corr[minus[r] * K + plus[a]] * X[r * p + b];
					cov[a * p + b] = c;
				}
			}
			// Symmetrised, and a variance rounding made a hair negative is zero.
			for (let a = 0; a < p; a++) {
				for (let b = a + 1; b < p; b++) {
					const v = (cov[a * p + b] + cov[b * p + a]) / 2;
					cov[a * p + b] = v;
					cov[b * p + a] = v;
				}
			}
			const L = cholesky(cov, p) ?? jitterCholesky(cov, p);
			return Array.from({ length: n }, () => toU(drawZ(p, L, mu)));
		},
	};
}

/** A Cholesky factor of a matrix that is positive semi-definite but not quite definite. */
function jitterCholesky(A, n) {
	for (let eps = 1e-12; eps < 1; eps *= 10) {
		const B = Float64Array.from(A);
		for (let i = 0; i < n; i++) B[i * n + i] += eps;
		const L = cholesky(B, n);
		if (L) return L;
	}
	throw new Error('A conditional covariance could not be factorised.');
}

/**
 * @param {number} K
 * @param {object} o
 * @param {number} [o.perms]   random orders; `-1` (or K ≤ 1) for all K! of them
 * @param {number} o.nVar      points for the output's variance
 * @param {number} o.nOuter    conditioning points per step
 * @param {number} [o.nInner]  conditional draws per conditioning point
 * @param {Float64Array|null} [o.corr]  a K×K correlation matrix of the normal scores
 * @param {() => number} o.next
 */
export function shapleyDesign(K, { perms = -1, nVar, nOuter, nInner = 3, corr = null, next }) {
	const orders = perms === -1 ? permutationsOf(K) : Array.from({ length: perms }, () => randomPermutation(K, next));
	const law = copula(K, corr, next);
	const all = Array.from({ length: K }, (_, k) => k);
	const runs = nVar + orders.length * (K - 1) * nOuter * nInner;
	const u = columns(K, runs);
	let at = 0;
	for (const row of law.subset(all, nVar)) {
		for (let k = 0; k < K; k++) u[k][at] = row[k];
		at++;
	}
	for (const perm of orders) {
		for (let j = 1; j < K; j++) {
			const plus = perm.slice(0, j);
			const minus = perm.slice(j);
			const outer = law.subset(minus, nOuter);
			for (const fixed of outer) {
				const inner = law.given(plus, minus, fixed, nInner);
				for (const drawn of inner) {
					for (let a = 0; a < plus.length; a++) u[plus[a]][at] = drawn[a];
					for (let b = 0; b < minus.length; b++) u[minus[b]][at] = fixed[b];
					at++;
				}
			}
		}
	}
	return { method: 'shapley', K, orders, nVar, nOuter, nInner, correlated: !!corr, u, runs };
}

export function shapleyIndices(y, { K, orders, nVar, nOuter, nInner }) {
	const Sh = new Float64Array(K);
	const Sh2 = new Float64Array(K);
	const vary = variance(y, 0, nVar);
	let at = nVar;
	for (const perm of orders) {
		let prev = 0;
		for (let j = 0; j < K; j++) {
			if (j === K - 1) {
				Sh[perm[j]] += vary - prev;
				prev = vary;
				continue;
			}
			const cVar = new Float64Array(nOuter);
			for (let l = 0; l < nOuter; l++) {
				cVar[l] = variance(y, at, at + nInner);
				at += nInner;
			}
			const C = mean(cVar);
			const d = C - prev;
			let d2 = 0;
			for (let l = 0; l < nOuter; l++) d2 += (cVar[l] - prev) ** 2;
			Sh2[perm[j]] += d2 / nOuter - d * d;
			Sh[perm[j]] += d;
			prev = C;
		}
	}
	const m = orders.length;
	const effects = Sh.map((v) => v / m / vary);
	const se = Sh2.map((v) => Math.sqrt(v / m / (vary * vary) / nOuter));
	return {
		effects,
		stdErr: se,
		lower: effects.map((v, k) => v - 1.96 * se[k]),
		upper: effects.map((v, k) => v + 1.96 * se[k]),
	};
}

/* -------------------------------------------------------------------------
 * From a sample: EASI.
 *
 * Plischke's effective algorithm for sensitivity indices reads a first-order
 * index off any sample: sort the runs by one input, fold them into a
 * triangle so the output becomes periodic in it, and take the power in the
 * first few harmonics. `S1c` is Tissot and Prieur's correction for the bias a
 * random design leaves in that.
 * ---------------------------------------------------------------------- */

export function easi(x, y, { harmonics: H = 4, dct = false } = {}) {
	const n = y.length;
	const order = sortPerm(x);
	let s;
	if (dct) {
		const yp = new Float64Array(n);
		for (let i = 0; i < n; i++) yp[i] = y[order[i]];
		const c = centred(yp);
		let den = 0;
		for (let i = 0; i < n; i++) den += c[i] * c[i];
		const X = dct2(c, Math.min(H, n - 1) + 1);
		let num = 0;
		for (let k = 1; k < X.length; k++) num += X[k] * X[k];
		s = num / den;
	} else {
		const yp = new Float64Array(n);
		let j = 0;
		for (let k = 0; k < n; k += 2) yp[j++] = y[order[k]];
		for (let k = 2 * Math.floor(n / 2) - 1; k >= 1; k -= 2) yp[j++] = y[order[k]];
		const P = powerSpectrum(centred(yp));
		const top = P.length - 2;
		let num = 0;
		let den = 0;
		for (let k = 1; k <= top; k++) {
			den += P[k];
			if (k <= H) num += P[k];
		}
		s = num / den;
	}
	const lambda = (2 * H) / n;
	return { s1: s, s1c: s - (lambda / (1 - lambda)) * (1 - s) };
}

/* -------------------------------------------------------------------------
 * From a sample: Borgonovo's moment-independent δ.
 *
 * How far knowing an input moves the output's whole *distribution*, not only
 * its variance: half the expected area between the output's density and its
 * density given the input, estimated by cutting the input into classes and
 * comparing kernel density estimates. The adjusted δ subtracts the bias a
 * bootstrap measures, and the interval is around that.
 *
 * The kernel density estimate is KernelDensity.jl's, ported with it (MIT):
 * Silverman's bandwidth, linear binning onto 2048 points, the Gaussian
 * applied in Fourier space, and a quadratic B-spline through the result
 * (Interpolations.jl's, MIT) to read it anywhere else -- so that the δ a
 * given sample gives here is the one GlobalSensitivity.jl gives.
 * ---------------------------------------------------------------------- */

/**
 * Silverman's rule of thumb, as KernelDensity.jl's `default_bandwidth`.
 *
 * Data with no spread at all -- one value, or every value the same -- have
 * nothing to take a width from, and KernelDensity.jl falls back to a width of
 * one *in the data's own units*. For a dose of 1e7 that is a spike far
 * narrower than any grid the density is read on, and the δ it feeds comes out
 * in the millions. `fallback`, where given, is used instead; δ passes the
 * bandwidth of the whole output, so a class of identical values is a bump of
 * the width the output itself is resolved at.
 */
export function kdeBandwidth(data, fallback = null) {
	const n = data.length;
	if (n <= 1) return fallback ?? 0.9;
	const sd = std(data);
	const iqr = (quantile7(data, 0.75) - quantile7(data, 0.25)) / 1.34;
	let width = Math.min(sd, iqr);
	if (width === 0) {
		if (sd === 0 && fallback != null) return fallback;
		width = sd === 0 ? 1 : sd;
	}
	return 0.9 * width * n ** -0.2;
}

/**
 * A Gaussian kernel density estimate on `npoints` points spanning the data
 * and four bandwidths either side.
 *
 * @returns {{lo: number, hi: number, step: number, density: Float64Array, coef: Float64Array}}
 */
export function kde(data, { npoints = 2048, fallback = null } = {}) {
	const bw = kdeBandwidth(data, fallback);
	if (!(bw > 0)) throw new Error('Bandwidth must be positive');
	let mn = Infinity;
	let mx = -Infinity;
	for (const v of data) { if (v < mn) mn = v; if (v > mx) mx = v; }
	const lo = mn - 4 * bw;
	const hi = mx + 4 * bw;
	const s = (hi - lo) / (npoints - 1);
	const mid = (i) => (i === npoints - 1 ? hi : lo + i * s);
	// Jones and Lotwick's linear binning.
	const grid = new Float64Array(npoints);
	const ainc = 1 / (s * s);
	const w = 1 / data.length;
	for (const x of data) {
		let k = Math.round((x - lo) / s);
		if (k < 0) k = 0;
		if (k > npoints - 1) k = npoints - 1;
		while (k > 0 && mid(k - 1) >= x) k--;
		while (k < npoints && mid(k) < x) k++;
		const j = k - 1;
		if (j >= 0 && j <= npoints - 2) {
			grid[j] += (mid(k) - x) * ainc * w;
			grid[k] += (x - mid(j)) * ainc * w;
		}
	}
	// The Gaussian's characteristic function applied to the binned data's.
	const ft = rfft(grid);
	const c = (-2 * Math.PI) / (s * npoints);
	for (let j = 0; j < ft.re.length; j++) {
		const t = j * c;
		const f = Math.exp(-((bw * bw) / 2) * t * t);
		ft.re[j] *= f;
		ft.im[j] *= f;
	}
	const density = irfft(ft, npoints);
	for (let i = 0; i < npoints; i++) if (density[i] < 0) density[i] = 0;
	return { lo, hi, step: s, density, coef: splineCoefficients(density) };
}

/**
 * The coefficients of Interpolations.jl's `BSpline(Quadratic(Line(OnGrid())))`
 * through `y`: padded one at each end, with the second derivative zero at
 * both ends. The end rows make the first and last coefficients the data
 * themselves, which leaves a tridiagonal system for the rest.
 */
function splineCoefficients(y) {
	const n = y.length;
	const c = new Float64Array(n + 2);
	c[1] = y[0];
	c[n] = y[n - 1];
	const m = n - 2;
	if (m > 0) {
		// c[d-1]/8 + 3c[d]/4 + c[d+1]/8 = y[d-1] for d = 2..n-1, by Thomas.
		const cp = new Float64Array(m);
		const dp = new Float64Array(m);
		for (let i = 0; i < m; i++) {
			let r = y[i + 1];
			if (i === 0) r -= c[1] / 8;
			if (i === m - 1) r -= c[n] / 8;
			const denom = 0.75 - (i > 0 ? 0.125 * cp[i - 1] : 0);
			cp[i] = 0.125 / denom;
			dp[i] = (r - (i > 0 ? 0.125 * dp[i - 1] : 0)) / denom;
		}
		c[m + 1] = dp[m - 1];
		for (let i = m - 2; i >= 0; i--) c[i + 2] = dp[i] - cp[i] * c[i + 3];
	}
	c[0] = 2 * c[1] - c[2];
	c[n + 1] = 2 * c[n] - c[n - 1];
	return c;
}

/** The estimate at each of `xs`, and zero outside the grid, as `pdf(kde, xs)`. */
export function kdePdf(k, xs) {
	const n = k.density.length;
	const out = new Float64Array(xs.length);
	for (let i = 0; i < xs.length; i++) {
		const x = xs[i];
		if (!(x >= k.lo && x <= k.hi)) continue;
		const xi = (x - k.lo) / k.step + 1;
		const xm = xi < n + 0.5 ? Math.floor(xi + 0.5) : Math.ceil(xi + 0.5) - 1;
		const d = xi - xm;
		out[i] = ((d - 0.5) ** 2 / 2) * k.coef[xm - 1]
			+ (0.75 - d * d) * k.coef[xm]
			+ ((d + 0.5) ** 2 / 2) * k.coef[xm + 1];
	}
	return out;
}

function trapz(x, y) {
	let s = 0;
	for (let i = 0; i < x.length - 1; i++) s += (x[i + 1] - x[i]) * (y[i] + y[i + 1]);
	return s / 2;
}

/** The number of classes GlobalSensitivity.jl cuts `n` realisations into. */
export function deltaClasses(n) {
	const e = 2 / (7 + Math.tanh((1500 - n) / 500));
	return Math.round(Math.min(Math.ceil(n ** e), 48));
}

function deltaOnce(x, y, ygrid, cut) {
	const n = y.length;
	let same = true;
	for (let i = 1; i < n && same; i++) if (y[i] !== y[0]) same = false;
	if (same) return 0;
	const fallback = kdeBandwidth(y);
	const fy = kdePdf(kde(y), ygrid);
	const rank = competeRank(x);
	let total = 0;
	for (let j = 0; j < cut.length - 1; j++) {
		const members = [];
		for (let i = 0; i < n; i++) if (rank[i] > cut[j] && rank[i] <= cut[j + 1]) members.push(y[i]);
		if (!members.length) continue;
		const fyc = kdePdf(kde(members, { fallback }), ygrid);
		const diff = new Float64Array(ygrid.length);
		for (let g = 0; g < ygrid.length; g++) diff[g] = Math.abs(fy[g] - fyc[g]);
		total += members.length * trapz(ygrid, diff);
	}
	return total / (2 * n);
}

/**
 * @param {ArrayLike<number>} x  one input's values
 * @param {ArrayLike<number>} y  the output, the same length
 * @param {object} [o]
 * @param {number} [o.boots]      bootstrap resamples for the bias and interval
 * @param {number} [o.conf]
 * @param {number} [o.grid]       points the densities are compared at
 * @param {number|null} [o.classes]
 * @param {() => number} [o.next]
 * @param {Int32Array[]|null} [o.resamples]  the resamples themselves, for a test
 */
export function deltaMoment(x, y, {
	boots = 500, conf = 0.95, grid = 2048, classes = null, next = Math.random, resamples = null,
} = {}) {
	const n = y.length;
	const M = classes ?? deltaClasses(n);
	const cut = Array.from({ length: M + 1 }, (_, j) => (j * n) / M);
	let lo = Infinity;
	let hi = -Infinity;
	for (const v of y) { if (v < lo) lo = v; if (v > hi) hi = v; }
	const ygrid = linspace(lo, hi, grid);
	const delta = deltaOnce(x, y, ygrid, cut);
	const B = resamples ? resamples.length : boots;
	if (!B) return { delta, adjusted: delta, low: NaN, high: NaN };
	const bs = new Float64Array(B);
	const xi = new Float64Array(n);
	const yi = new Float64Array(n);
	for (let b = 0; b < B; b++) {
		for (let i = 0; i < n; i++) {
			const r = resamples ? resamples[b][i] : Math.floor(next() * n);
			xi[i] = x[r];
			yi[i] = y[r];
		}
		bs[b] = deltaOnce(xi, yi, ygrid, cut);
	}
	const adjusted = 2 * delta - mean(bs);
	const band = (normalQuantile(0.5 + conf / 2) * std(bs)) / Math.sqrt(B);
	return { delta, adjusted, low: adjusted - band, high: adjusted + band };
}

/* -------------------------------------------------------------------------
 * From a sample: regional sensitivity analysis.
 *
 * Split the runs into those whose output is above a threshold ("behavioural")
 * and the rest, and measure how differently an input is distributed in the
 * two: the Kolmogorov-Smirnov distance between the two empirical CDFs. An
 * input that makes no difference has the two the same. Dummy inputs -- draws
 * that the model never saw -- say how large a distance chance alone gives.
 * ---------------------------------------------------------------------- */

export function rsaScore(x, flag) {
	const order = sortPerm(x);
	let acc = 0;
	let rej = 0;
	const A = new Float64Array(order.length);
	const R = new Float64Array(order.length);
	order.forEach((i, p) => {
		acc += flag[i];
		rej += 1 - flag[i];
		A[p] = acc;
		R[p] = rej;
	});
	let best = 0;
	for (let p = 0; p < order.length; p++) {
		const d = Math.abs(A[p] / acc - R[p] / rej);
		if (Number.isNaN(d)) return NaN;
		if (d > best) best = d;
	}
	return best;
}

/**
 * @param {ArrayLike<number>[]} xs  one column per input
 * @param {ArrayLike<number>} y
 * @param {{threshold?: number|null, dummies?: ArrayLike<number>[]}} [o]
 *   the threshold defaults to the output's mean
 */
export function rsa(xs, y, { threshold = null, dummies = [] } = {}) {
	const t = threshold ?? mean(y);
	const flag = new Float64Array(y.length);
	for (let i = 0; i < y.length; i++) flag[i] = y[i] > t ? 1 : 0;
	const scores = xs.map((x) => rsaScore(x, flag));
	const d = dummies.map((x) => rsaScore(x, flag));
	return {
		threshold: t,
		behavioural: flag.reduce((s, v) => s + v, 0),
		scores: Float64Array.from(scores),
		dummyMean: d.length ? mean(d) : NaN,
		dummySd: d.length > 1 ? std(d) : NaN,
	};
}

/* -------------------------------------------------------------------------
 * From a sample: mutual information.
 *
 * How many bits knowing an input tells about the output, from histograms
 * with √n bins a side -- ComplexityMeasures.jl's `ValueHistogram`, whose
 * binning this reproduces. The sensitivity is what is left of it above the
 * `conf` quantile of the same measure with the output shuffled, which is what
 * chance alone would give.
 * ---------------------------------------------------------------------- */

const F64 = new Float64Array(1);
const U64 = new BigUint64Array(F64.buffer);

/** The next representable number above `x`, `n` times. */
function nextUp(x, n = 1) {
	let v = x;
	for (let i = 0; i < n; i++) {
		if (v === 0) { v = Number.MIN_VALUE; continue; }
		F64[0] = v;
		U64[0] = v > 0 ? U64[0] + 1n : U64[0] - 1n;
		v = F64[0];
	}
	return v;
}

/** Bin edges as `RectangularBinning(bins)` lays them over one column. */
function binner(x, bins) {
	let mn = Infinity;
	let mx = -Infinity;
	for (const v of x) { if (v < mn) mn = v; if (v > mx) mx = v; }
	const top = nextUp(mx, 2);
	const width = (top - mn) / bins;
	return (v) => Math.floor((v - mn) / width);
}

function entropyOfCounts(counts, n) {
	let h = 0;
	for (const c of counts) {
		if (!c) continue;
		const p = c / n;
		h -= p * Math.log2(p);
	}
	return h;
}

export function histogramEntropy(x, bins) {
	const at = binner(x, bins);
	const counts = new Map();
	for (const v of x) {
		const b = at(v);
		counts.set(b, (counts.get(b) ?? 0) + 1);
	}
	return entropyOfCounts(counts.values(), x.length);
}

export function jointEntropy(x, y, bins) {
	const ax = binner(x, bins);
	const ay = binner(y, bins);
	const counts = new Map();
	for (let i = 0; i < x.length; i++) {
		const key = ax(x[i]) * (bins + 2) + ay(y[i]);
		counts.set(key, (counts.get(key) ?? 0) + 1);
	}
	return entropyOfCounts(counts.values(), x.length);
}

/**
 * @param {object} [o]
 * @param {number} [o.boots]   shuffles of the output for the chance level
 * @param {number} [o.conf]
 * @param {() => number} [o.next]
 * @param {Int32Array[]|null} [o.shuffles]  the shuffled orders themselves, for a test
 */
export function mutualInformation(x, y, { boots = 1000, conf = 0.95, next = Math.random, shuffles = null } = {}) {
	const n = y.length;
	const bins = Math.round(Math.sqrt(n));
	const hx = histogramEntropy(x, bins);
	const hy = histogramEntropy(y, bins);
	const mi = hx + hy - jointEntropy(x, y, bins);
	const B = shuffles ? shuffles.length : boots;
	const nulls = new Float64Array(B);
	const perm = Float64Array.from(y);
	for (let b = 0; b < B; b++) {
		if (shuffles) {
			for (let i = 0; i < n; i++) perm[i] = y[shuffles[b][i]];
		} else {
			for (let i = n - 1; i > 0; i--) {
				const j = Math.floor(next() * (i + 1));
				const t = perm[i]; perm[i] = perm[j]; perm[j] = t;
			}
		}
		nulls[b] = hx + hy - jointEntropy(x, perm, bins);
	}
	const bound = B ? quantile7(nulls, conf) : NaN;
	return { mi, bound, s: Math.max(0, mi - bound) };
}

/* -------------------------------------------------------------------------
 * The designed methods as the tool offers them: what each is called, what it
 * can be told, how many runs that comes to, how its design is drawn from a
 * run's seed, and what its answer looks like as a table.
 * ---------------------------------------------------------------------- */

/**
 * Each method's settings: `[key, label, default, kind, title]`, where a default
 * that is a function is worked out from the number of inputs.
 */
export const GSA_METHODS = {
	morris: {
		label: 'Morris elementary effects',
		short: 'Morris',
		blurb: 'Random walks through the inputs, one input moved one level at a time. μ* says how '
			+ 'much an input matters, μ which way, σ how much its effect depends on where it is '
			+ 'taken — a curve or an interaction. Cheap: a screening method, for many inputs.',
		options: [
			['design', 'Design', 'walks', 'choice', 'How the runs are laid out: GlobalSensitivity.jl’s random walks, or Morris’s own trajectories as SALib samples them, each moving every input once by half its range.',
				[['walks', 'Random walks'], ['trajectories', 'Trajectories (SALib)']]],
			['trajectories', 'Trajectories', 10, 'int', 'How many walks, or trajectories.'],
			['points', 'Walk length', 10, 'int', 'Walks only: runs in each; each step after the first is one elementary effect. A trajectory is K + 1 runs.'],
			['levels', 'Levels', 100, 'int', 'How many levels each input’s probability is cut into. A walk moves one level a step; a trajectory, half of them.'],
			['candidates', 'Candidates', 0, 'int', 'Trajectories only: draw this many and keep the most spread out — Campolongo’s optimal trajectories, by Ruano’s local search. 0 keeps every one drawn.'],
			['relative', 'Relative', false, 'switch', 'Each effect divided by the output, so it is a proportion rather than in the output’s units.'],
			['resamples', 'Bootstrap', 100, 'int', 'Resamples for SALib’s interval on μ*; 0 for none.'],
		],
	},
	sobol: {
		label: 'Sobol indices',
		short: 'Sobol',
		blurb: 'The variance decomposition: S₁ is the share of the spread an input explains alone, '
			+ 'Sₜ the share it has a hand in, interactions included. Saltelli’s design, two samples '
			+ 'and one more per input. The reference method, and the most expensive.',
		options: [
			['samples', 'Samples', 1000, 'int', 'Points in each of the two base samples, A and B.'],
			['second', 'Pairs, S₂', false, 'switch', 'Every pair’s interaction too, at the cost of K more samples.'],
			['blocks', 'Blocks', 1, 'int', 'Repeat the design this many times and give an interval from the spread between them.'],
			['estimator', 'Sₜ estimator', 'jansen1999', 'choice', 'How Sₜ is estimated from the samples.',
				[['jansen1999', 'Jansen 1999'], ['sobol2007', 'Sobol 2007'], ['homma1996', 'Homma and Saltelli 1996'], ['janon2014', 'Janon 2014']]],
			['resamples', 'Bootstrap', 100, 'int', 'With one block: resamples for SALib’s bootstrap interval on each index, from the one design. 0 for none.'],
		],
	},
	efast: {
		label: 'eFAST',
		short: 'eFAST',
		blurb: 'The extended Fourier amplitude test: one curve per input, along which that input '
			+ 'oscillates fast and the rest slowly, and the variances read off the spectrum. S₁ and '
			+ 'Sₜ for about the price of Sobol’s S₁.',
		options: [
			['samples', 'Curve length', 1000, 'int', 'Runs along each input’s curve; K curves in all.'],
			['harmonics', 'Harmonics', 4, 'int', 'How many harmonics of the input’s frequency count as its own.'],
		],
	},
	rbdfast: {
		label: 'RBD-FAST',
		short: 'RBD-FAST',
		blurb: 'Random balance design: one curve for every input at once, each in its own random '
			+ 'order. First-order indices only, but for a fixed number of runs whatever the number '
			+ 'of inputs.',
		options: [
			['samples', 'Samples', 1000, 'int', 'Runs in all.'],
			['harmonics', 'Harmonics', 6, 'int', 'How many harmonics count as the input’s.'],
		],
	},
	ff: {
		label: 'Fractional factorial',
		short: 'Fractional factorial',
		blurb: 'Every input at a low or a high value in a two-level design of resolution IV. Main '
			+ 'effects, clear of two-way interactions, from a handful of runs.',
		options: [
			['low', 'Low level', 0.05, 'number', 'The probability each input’s low level is at.'],
			['high', 'High level', 0.95, 'number', 'The probability each input’s high level is at.'],
			['pairs', 'Pairs', false, 'switch', 'Every pair’s two-way interaction effect too, from the same runs (SALib’s). In this design each is aliased with others: what is measured for a pair is its sum with the pairs aliased with it.'],
		],
	},
	dgsm: {
		label: 'Derivative-based measures (DGSM)',
		short: 'DGSM',
		blurb: 'The derivative of the output with respect to each input, at sampled points. ν, the '
			+ 'mean squared derivative, bounds the total Sobol index from above. K + 1 runs a point.',
		options: [
			['samples', 'Points', 100, 'int', 'Where the derivatives are taken.'],
			['step', 'Step', 0.001, 'number', 'The finite-difference step, in probability.'],
			['crossed', 'Cross terms', false, 'switch', 'Every pair’s second derivative too, K(K − 1)/2 more runs a point.'],
			['resamples', 'Bootstrap', 100, 'int', 'Resamples for SALib’s interval on ν; 0 for none.'],
		],
	},
	radial: {
		label: 'Radial one-at-a-time',
		short: 'Radial',
		blurb: 'Campolongo, Saltelli and Cariboni’s design: base points spread over the whole space, each '
			+ 'moved one input at a time towards a second point. Elementary effects to screen with, as '
			+ 'Morris’s, and Jansen’s total index from the same runs — N(K + 1) of them.',
		options: [
			['samples', 'Base points', 100, 'int', 'How many; each costs K + 1 runs.'],
			['resamples', 'Bootstrap', 100, 'int', 'Resamples for the intervals on μ* and Sₜ; 0 for none.'],
		],
	},
	shapley: {
		label: 'Shapley effects',
		short: 'Shapley',
		blurb: 'Each input’s fair share of the variance, over the orders the inputs could be learnt '
			+ 'in. They add up to one when inputs are correlated, which is what they are for: the '
			+ 'model’s correlations are honoured through a Gaussian copula.',
		options: [
			// Song, Nelson and Staum's advice: over random orders, one outer
			// sample and three inner ones, and spend the runs on orders; over
			// all of them, more outer samples, since there are no more orders
			// to take. All of them is K! and stops being affordable at five.
			['perms', 'Orders', (K) => (K <= 4 ? 0 : 100), 'int', 'Random orders of the inputs; 0 for all K! of them.'],
			['nVar', 'Variance runs', 1000, 'int', 'Runs for the output’s total variance.'],
			['nOuter', 'Outer samples', (K) => (K <= 4 ? 10 : 1), 'int', 'Conditioning points per step of an order.'],
			['nInner', 'Inner samples', 3, 'int', 'Conditional draws per conditioning point.'],
		],
	},
};

export const GSA_METHOD_IDS = Object.keys(GSA_METHODS);

/** A method's settings with every one filled in. */
export function gsaOptions(method, K, given = {}) {
	const out = {};
	for (const [key, , def, kind, , choices] of GSA_METHODS[method]?.options ?? []) {
		const want = given?.[key];
		const d = typeof def === 'function' ? def(K) : def;
		if (kind === 'switch') out[key] = want == null ? d : !!want;
		else if (kind === 'choice') out[key] = choices.some(([v]) => v === want) ? want : d;
		else {
			const v = Number(want);
			out[key] = Number.isFinite(v) && want !== '' && want != null
				? (kind === 'int' ? Math.round(v) : v) : d;
		}
	}
	return out;
}

const factorial = (n) => (n <= 1 ? 1 : n * factorial(n - 1));

/** How many runs a design of `method` over `K` inputs is, before any is made. */
export function gsaRuns(method, K, options = {}) {
	const o = gsaOptions(method, K, options);
	switch (method) {
		case 'morris': return o.trajectories * (o.design === 'trajectories' ? K + 1 : o.points);
		case 'radial': return o.samples * (K + 1);
		case 'sobol': return sobolRuns(K, o.samples, { second: o.second, blocks: o.blocks });
		case 'efast': return K * efastSamples(o.samples, o.harmonics);
		case 'rbdfast': return o.samples;
		case 'ff': { let k2 = 2; while (k2 < K) k2 *= 2; return 2 * k2; }
		case 'dgsm': return o.samples * (1 + K + (o.crossed ? (K * (K - 1)) / 2 : 0));
		case 'shapley': {
			const orders = o.perms > 0 ? o.perms : factorial(K);
			return o.nVar + orders * (K - 1) * o.nOuter * o.nInner;
		}
		default: return 0;
	}
}

/** Why a design cannot be made as asked, in a sentence, or null. */
export function gsaRefusal(method, K, options = {}) {
	const o = gsaOptions(method, K, options);
	if (!GSA_METHODS[method]) return `There is no method called ${method}.`;
	if (K < 1) return 'Nothing is sampled, so there is nothing to vary.';
	const positive = (v) => Number.isInteger(v) && v >= 1;
	switch (method) {
		case 'morris':
			if (!positive(o.trajectories) || !(o.points >= 2) || !(o.levels >= 2)) {
				return 'Morris needs at least one trajectory of two points, over at least two levels.';
			}
			if (o.design === 'trajectories' && o.candidates > 0 && o.candidates < o.trajectories) {
				return 'Fewer candidates than trajectories to keep; 0 keeps every one drawn.';
			}
			break;
		case 'radial':
			if (!(o.samples >= 2)) return 'The radial design needs at least two base points.';
			break;
		case 'sobol':
			if (!(o.samples >= 2) || !positive(o.blocks)) return 'Sobol needs at least two samples and one block.';
			if (o.blocks > 1 && o.blocks > o.samples) return 'More blocks than samples.';
			break;
		case 'efast': case 'rbdfast':
			if (!(o.samples >= 8) || !positive(o.harmonics)) return 'This needs at least a few samples and one harmonic.';
			if (method === 'rbdfast' && 2 * o.harmonics >= o.samples / 2) return 'Too many harmonics for so few samples.';
			break;
		case 'ff':
			if (!(o.low > 0 && o.high < 1 && o.low < o.high)) return 'The two levels must be probabilities, the low one below the high.';
			break;
		case 'dgsm':
			if (!(o.samples >= 2)) return 'DGSM needs at least two points.';
			if (!(o.step > 0 && o.step < 0.5)) return 'The step must be a small probability.';
			break;
		case 'shapley':
			if (o.perms <= 0 && K > 8) return `All ${K}! orders of ${K} inputs is too many; give a number of random orders.`;
			if (!(o.nVar >= 2) || !positive(o.nOuter) || !(o.nInner >= 2)) {
				return 'Shapley needs at least two variance samples, one outer and two inner samples.';
			}
			break;
		default:
	}
	return null;
}

/**
 * The design, drawn from a run's seed.
 *
 * Every column that a method samples freely comes from a stream named after
 * the input it belongs to, Latin hypercube, the way a probabilistic run draws
 * -- so the same seed gives an input the same numbers whichever other inputs
 * are in the model. The walks, the orders and the conditional draws, which
 * belong to no one input, have one stream of their own each.
 *
 * @param {string} method
 * @param {string[]} keys   one name per input, for its streams
 * @param {object} options
 * @param {{seed?: number, corr?: Float64Array|null, streamFor: Function, uniforms: Function}} ctx
 */
export function buildDesign(method, keys, options, { seed = 1, corr = null, streamFor, uniforms }) {
	const K = keys.length;
	const o = gsaOptions(method, K, options);
	const refused = gsaRefusal(method, K, o);
	if (refused) throw new Error(refused);
	const col = (name, n) => uniforms(n, streamFor(seed, name), { latin: true });
	let d;
	switch (method) {
		case 'morris':
			d = o.design === 'trajectories'
				? morrisTrajectoryDesign(K, { ...o, next: streamFor(seed, '#gsa#morris') })
				: morrisDesign(K, { ...o, next: streamFor(seed, '#gsa#morris') });
			break;
		case 'radial':
			d = radialDesign(K, keys.map((key) => col(`${key}#radial#base`, o.samples)),
				keys.map((key) => col(`${key}#radial#step`, o.samples)));
			break;
		case 'sobol':
			d = sobolDesign(K, o.samples, {
				second: o.second, blocks: o.blocks,
				draw: (k, which, b) => col(`${keys[k]}#sobol#${which}#${b}`, o.samples),
			});
			break;
		case 'efast': {
			const N = efastSamples(o.samples, o.harmonics);
			const phases = keys.map((key) => 2 * streamFor(seed, `${key}#efast`)());
			d = efastDesign(K, N, { harmonics: o.harmonics, phases });
			break;
		}
		case 'rbdfast':
			d = rbdFastDesign(K, o.samples, {
				perms: keys.map((key) => randomPermutation(o.samples, streamFor(seed, `${key}#rbdfast`))),
			});
			break;
		case 'ff':
			d = ffDesign(K, o);
			break;
		case 'dgsm':
			d = dgsmDesign(K, keys.map((key) => col(`${key}#dgsm`, o.samples)), o);
			break;
		case 'shapley':
			d = shapleyDesign(K, {
				perms: o.perms > 0 ? o.perms : -1, nVar: o.nVar, nOuter: o.nOuter, nInner: o.nInner,
				corr, next: streamFor(seed, '#gsa#shapley'),
			});
			break;
		default:
			throw new Error(`There is no method called ${method}.`);
	}
	d.options = o;
	// What the intervals are drawn from, so that reading the table again gives
	// the same one: see `gsaTable`.
	d.seed = seed;
	return d;
}

/**
 * What a table of a method's answer holds: the columns, and which of them the
 * rows are ranked by. `index` columns are shares of the variance, drawn as a
 * bar against one; `value` columns are in the output's units (or per unit
 * probability), and are numbers.
 */
function columnsFor(design) {
	const o = design.options ?? {};
	switch (design.method) {
		case 'morris': return {
			rank: 'meanStar',
			columns: [
				['meanStar', 'μ*', 'value', 'The mean of the elementary effects’ magnitudes: how much this input matters, whichever way.'],
				...(o.resamples > 1 ? [['meanStarCi', '± μ*', 'value', 'Half-width of the 95 % interval on μ*, SALib’s: this input’s effects resampled.']] : []),
				['mean', 'μ', 'value', 'The mean elementary effect: its sign says which way the output moves as the input rises.'],
				['sd', 'σ', 'value', 'The spread of the elementary effects: large where the effect depends on where it is taken — a curve, or an interaction.'],
				['count', 'n', 'count', 'How many elementary effects this input has.'],
			],
		};
		case 'radial': return {
			rank: 'ST',
			columns: [
				['ST', 'Sₜ', 'index', 'Total index, by Jansen’s estimator: the share of the variance this input has a hand in.'],
				...(o.resamples > 1 ? [['STci', '± Sₜ', 'value', 'Half-width of the 95 % interval on Sₜ, from the base points resampled.']] : []),
				['meanStar', 'μ*', 'value', 'The mean magnitude of the elementary effects, as Morris’s, from points spread over the whole space.'],
				...(o.resamples > 1 ? [['meanStarCi', '± μ*', 'value', 'Half-width of the 95 % interval on μ*, SALib’s.']] : []),
				['mean', 'μ', 'value', 'The mean elementary effect: which way the output moves.'],
				['sd', 'σ', 'value', 'The spread of the elementary effects.'],
			],
		};
		case 'sobol': return {
			rank: 'ST',
			columns: [
				['S1', 'S₁', 'index', 'First-order index: the share of the variance this input explains alone.'],
				['ST', 'Sₜ', 'index', 'Total index: the share it has a hand in, interactions included.'],
				...(o.blocks > 1 ? [
					['S1ci', '± S₁', 'value', 'Half-width of the interval on S₁, from the spread between blocks.'],
					['STci', '± Sₜ', 'value', 'Half-width of the interval on Sₜ.'],
				] : o.resamples > 1 ? [
					['S1ci', '± S₁', 'value', 'Half-width of the 95 % interval on S₁, SALib’s: the runs of the one design resampled.'],
					['STci', '± Sₜ', 'value', 'Half-width of the 95 % interval on Sₜ, likewise.'],
				] : []),
			],
		};
		case 'efast': return {
			rank: 'ST',
			columns: [
				['S1', 'S₁', 'index', 'First-order index, from the power at this input’s frequency and its harmonics.'],
				['ST', 'Sₜ', 'index', 'Total index: one less everything at the other inputs’ frequencies.'],
			],
		};
		case 'rbdfast': return {
			rank: 'S1',
			columns: [
				['S1', 'S₁', 'index', 'First-order index, from the first harmonics along this input’s order.'],
				['S1c', 'S₁ corrected', 'index', 'The same with Tissot and Prieur’s correction for the bias a random design leaves in it, which SALib applies.'],
			],
		};
		case 'ff': return {
			rank: 'absMain',
			columns: [
				['main', 'Main effect', 'value', 'Half the difference between the output’s mean with this input high and with it low.'],
				['squared', 'Squared', 'value', 'The main effect squared, which is what ranks them.'],
			],
		};
		case 'dgsm': return {
			rank: 'asq',
			columns: [
				['bound', 'Sₜ ≤', 'index', 'Upper bound on the total Sobol index: ν / (π² Var y). An input with a small bound is safely unimportant.'],
				['asq', 'ν', 'value', 'The mean squared derivative, per unit probability squared.'],
				...(o.resamples > 1 ? [['asqCi', '± ν', 'value', 'Half-width of the 95 % interval on ν, SALib’s: the points resampled.']] : []),
				['asqSd', 'sd', 'value', 'The spread of the squared derivative across the points, SALib’s vi_std.'],
				['a', 'mean', 'value', 'The mean derivative: which way the output moves.'],
				['absa', '|mean|', 'value', 'The mean of the derivative’s magnitude.'],
				['sigma', 'σ', 'value', 'GlobalSensitivity.jl’s sigma: the mean of u(1 − u)/2 times the squared derivative.'],
				['tao', 'τ', 'value', 'GlobalSensitivity.jl’s tao: the mean of (1 − 3u + u²)/6 times the squared derivative.'],
			],
		};
		case 'shapley': return {
			rank: 'effect',
			columns: [
				['effect', 'Shapley', 'index', 'This input’s share of the variance, fairly attributed; they add up to one.'],
				['ci', '±', 'value', 'Half-width of the 95 % interval, from the spread between outer samples; none with one of them.'],
			],
		};
		default: return { rank: null, columns: [] };
	}
}

/**
 * One method's answer for one output, as rows.
 *
 * The intervals SALib adds are bootstraps, drawn from `next`: a stream of the
 * run's seed, so reading the table again gives the same one. `intervals:
 * false` leaves them out, for the curve over time, which reads only the rank.
 *
 * @param {object} design  from `buildDesign`
 * @param {Float64Array} y  the output at every design point
 * @param {{next?: () => number, intervals?: boolean}} [o]
 * @returns {{columns, rank, rows: Array<{k: number, values: object}>, pairs: Array|null,
 *   failed: number, variance: number}}
 */
export function gsaTable(design, y, { next = Math.random, intervals = true } = {}) {
	const { K } = design;
	const failed = y.reduce((s, v) => s + (Number.isFinite(v) ? 0 : 1), 0);
	// An output that came out the same in every run has no spread to share
	// out, and every index of it would be 0/0.
	let flat = true;
	for (let i = 1; i < y.length && flat; i++) if (y[i] !== y[0]) flat = false;
	const { columns, rank } = columnsFor(design);
	const rows = Array.from({ length: K }, (_, k) => ({ k, values: {} }));
	let pairs = null;
	if (!failed && !flat) {
		const o = design.options ?? {};
		const set = (key, arr) => { for (let k = 0; k < K; k++) rows[k].values[key] = arr[k]; };
		switch (design.method) {
			case 'morris': {
				const r = morrisIndices(y, design, { relative: !!o.relative });
				set('meanStar', r.meanStar);
				set('mean', r.mean);
				set('sd', r.variance.map(Math.sqrt));
				set('count', r.count);
				if (o.resamples > 1) {
					set('meanStarCi', intervals
						? muStarInterval(r.effects, { resamples: o.resamples, next })
						: new Float64Array(K).fill(NaN));
				}
				for (let k = 0; k < K; k++) {
					if (!r.count[k]) for (const c of ['meanStar', 'mean', 'sd']) rows[k].values[c] = NaN;
				}
				break;
			}
			case 'radial': {
				const r = radialIndices(y, design, { resamples: intervals ? o.resamples : 0, next });
				set('ST', r.ST);
				set('meanStar', r.muStar);
				set('mean', r.mu);
				set('sd', r.sigma);
				if (o.resamples > 1) { set('STci', r.STci); set('meanStarCi', r.muStarCi); }
				break;
			}
			case 'sobol': {
				const r = sobolIndices(y, { K, n: design.n, second: design.second, blocks: design.blocks, estimator: o.estimator });
				set('S1', r.S1);
				set('ST', r.ST);
				// With one design, SALib's bootstrap gives the interval blocks would.
				if (!r.S1ci && o.resamples > 1 && intervals) {
					const b = sobolBootstrap(y, design, { resamples: o.resamples, next });
					r.S1ci = b.S1ci;
					r.STci = b.STci;
					r.S2ci = b.S2ci;
				}
				if (r.S1ci) { set('S1ci', r.S1ci); set('STci', r.STci); }
				if (r.S2) {
					pairs = [];
					for (let a = 0; a < K; a++) {
						for (let b = a + 1; b < K; b++) {
							pairs.push({ a, b, value: r.S2[a * K + b], ci: r.S2ci ? r.S2ci[a * K + b] : null });
						}
					}
					pairs.sort((p, q) => Math.abs(q.value) - Math.abs(p.value));
				}
				break;
			}
			case 'efast': {
				const r = efastIndices(y, design);
				set('S1', r.S1);
				set('ST', r.ST);
				break;
			}
			case 'rbdfast': {
				const S1 = rbdFastIndices(y, design, { harmonics: o.harmonics });
				set('S1', S1);
				set('S1c', S1.map((v) => unskew(v, o.harmonics, design.N)));
				break;
			}
			case 'ff': {
				const r = ffIndices(y, design);
				set('main', r.main);
				set('squared', r.squared);
				set('absMain', r.main.map(Math.abs));
				if (o.pairs) pairs = ffInteractions(y, design).sort((p, q) => Math.abs(q.value) - Math.abs(p.value));
				break;
			}
			case 'dgsm': {
				const r = dgsmIndices(y, design);
				for (const key of ['bound', 'asq', 'a', 'absa', 'sigma', 'tao']) set(key, r[key]);
				const spreadOf = dgsmSpread(dgsmDerivatives(y, design).g, K, design.N,
					{ resamples: intervals ? o.resamples : 0, next });
				set('asqSd', spreadOf.sd);
				if (o.resamples > 1) set('asqCi', spreadOf.ci);
				if (r.crossed) {
					pairs = [];
					for (let a = 0; a < K; a++) {
						for (let b = a + 1; b < K; b++) pairs.push({ a, b, value: r.crossed.sq[a * K + b] });
					}
					pairs.sort((p, q) => q.value - p.value);
				}
				break;
			}
			case 'shapley': {
				const r = shapleyIndices(y, design);
				set('effect', r.effects);
				// The standard error is read off the spread between outer
				// samples, and with one of them there is none to read: it
				// comes out as exactly zero, which is not an interval.
				set('ci', r.stdErr.map((v) => (design.nOuter > 1 ? 1.96 * v : NaN)));
				break;
			}
			default:
		}
	}
	const by = (r) => {
		const v = r.values[rank];
		return Number.isFinite(v) ? v : -Infinity;
	};
	rows.sort((p, q) => by(q) - by(p));
	return { method: design.method, columns, rank, rows, pairs, failed, flat: !failed && flat };
}

/** The number a method is ranked by, for one input -- what its curve over time is of. */
export function gsaMain(design, y) {
	const t = gsaTable(design, y, { intervals: false });
	const out = new Float64Array(design.K).fill(NaN);
	for (const r of t.rows) out[r.k] = r.values[t.rank];
	return out;
}
