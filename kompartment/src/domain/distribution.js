/**
 * What a sample of one output looks like, in numbers.
 *
 * A band on a chart is the 5th and 95th percentile at every time. Asked "what
 * is the probability the dose exceeds the limit", or "how sure is that mean",
 * the band has no answer, and those are the questions a probabilistic
 * assessment exists to put numbers on. GoldSim's Distribution Summary is the
 * page that does: mean with confidence bounds, standard deviation, skewness,
 * kurtosis, the count, a percentile table, a calculator between value and
 * probability, and a conditional tail expectation. This is that page's
 * arithmetic, over one column of the matrix a run keeps -- one output at one
 * time -- sorted once so that every question after the first is a lookup.
 *
 * Everything here is the plain sample statistic, with the one convention
 * stated: the percentile at `p` is the value at position `p·(n−1)` of the
 * sorted sample, linearly interpolated, which is what the bands use rounded
 * and what a spreadsheet's PERCENTILE gives. The confidence bounds are the
 * ones a finite sample honestly supports -- normal-approximation bounds on the
 * mean, and the Dvoretzky–Kiefer–Wolfowitz band on the whole distribution
 * function, which holds for any shape at all and says how much of what the
 * CDF shows is sampling noise.
 */

/**
 * One output at one time, over the realisations, sorted and finite.
 *
 * @param {Float64Array} values  realisation-major, `iterations × times`
 * @param {Uint8Array|null} [mask]  1 to keep a realisation, 0 to screen it out
 */
export function sortedColumn(values, times, iterations, at, mask = null) {
	const out = new Float64Array(iterations);
	let n = 0;
	for (let i = 0; i < iterations; i++) {
		if (mask && !mask[i]) continue;
		const v = values[i * times + at];
		if (Number.isFinite(v)) out[n++] = v;
	}
	return out.subarray(0, n).sort();
}

/** The value at cumulative probability `p`, interpolated between order statistics. */
export function valueAt(sorted, p) {
	const n = sorted.length;
	if (!n) return NaN;
	if (n === 1) return sorted[0];
	const x = Math.min(1, Math.max(0, p)) * (n - 1);
	const lo = Math.floor(x);
	const hi = Math.min(n - 1, lo + 1);
	return sorted[lo] + (sorted[hi] - sorted[lo]) * (x - lo);
}

/** The fraction of the sample at or below `x`: the empirical CDF. */
export function probabilityOf(sorted, x) {
	const n = sorted.length;
	if (!n) return NaN;
	// Binary search for the first entry above x.
	let lo = 0;
	let hi = n;
	while (lo < hi) {
		const mid = (lo + hi) >> 1;
		if (sorted[mid] <= x) lo = mid + 1; else hi = mid;
	}
	return lo / n;
}

/**
 * The mean of the sample above its `q`-quantile: what the bad cases average to.
 *
 * The number a regulator asks for after the 95th percentile -- not where the
 * tail starts but how heavy it is.
 */
export function conditionalTailExpectation(sorted, q) {
	const n = sorted.length;
	if (!n) return NaN;
	const from = Math.min(n - 1, Math.floor(Math.min(1, Math.max(0, q)) * n));
	let s = 0;
	for (let i = from; i < n; i++) s += sorted[i];
	return s / (n - from);
}

/** The percentiles a summary tabulates. */
export const PERCENTILES = [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99];

/**
 * The summary itself.
 *
 * @param {Float64Array} sorted  from `sortedColumn`
 * @returns {object} n, mean, sd, skewness, kurtosis (excess), min, max,
 *   meanBounds (95%), percentiles, dkw (the 95% band half-width on the CDF)
 */
export function describeSample(sorted) {
	const n = sorted.length;
	if (!n) {
		return {
			n: 0, mean: NaN, sd: NaN, skewness: NaN, kurtosis: NaN, min: NaN, max: NaN,
			meanBounds: [NaN, NaN], percentiles: [], dkw: NaN,
		};
	}
	let s = 0;
	for (let i = 0; i < n; i++) s += sorted[i];
	const mean = s / n;
	let m2 = 0;
	let m3 = 0;
	let m4 = 0;
	for (let i = 0; i < n; i++) {
		const d = sorted[i] - mean;
		const d2 = d * d;
		m2 += d2;
		m3 += d2 * d;
		m4 += d2 * d2;
	}
	// The sample standard deviation (n−1), which is what a confidence bound
	// on the mean wants; the moments for shape use the population form, which
	// is the textbook definition of the coefficients.
	const sd = n > 1 ? Math.sqrt(m2 / (n - 1)) : 0;
	const v = m2 / n;
	const skewness = v > 0 ? (m3 / n) / v ** 1.5 : NaN;
	const kurtosis = v > 0 ? (m4 / n) / (v * v) - 3 : NaN;
	const half = n > 1 ? 1.959964 * sd / Math.sqrt(n) : 0;
	return {
		n,
		mean,
		sd,
		skewness,
		kurtosis,
		min: sorted[0],
		max: sorted[n - 1],
		meanBounds: [mean - half, mean + half],
		percentiles: PERCENTILES.map((p) => ({ p, value: valueAt(sorted, p) })),
		// DKW: P(sup|F_n − F| > ε) ≤ 2·exp(−2nε²), so at 95% ε = √(ln(2/0.05)/(2n)).
		dkw: Math.sqrt(Math.log(2 / 0.05) / (2 * n)),
	};
}

/** How many bins a histogram may be asked for. */
export const HIST_BINS = { min: 2, max: 200 };

/**
 * A histogram of the sample, for the density panel.
 *
 * Bins by Sturges' rule unless told otherwise, on a log axis where the sample
 * is positive and spans decades -- a dose sample is, and on a linear axis it
 * is one tall bin and a tail nobody can see.
 *
 * `scale` overrules that judgement: `linear` and `log` are the reader's own
 * choice of what the bin *edges* are spaced by, which is a different question
 * from how the counts are drawn and is the one that decides what shape the
 * sample appears to have. **A log request on a sample that reaches zero or
 * below cannot be honoured** -- there is no logarithm of it to bin by -- so it
 * falls back to linear and says so in `wanted`, which is what the panel reads
 * to explain itself.
 *
 * @param {Float64Array} sorted  the column, ascending
 * @param {number|null} [bins]   how many, or null for Sturges' rule
 * @param {'auto'|'linear'|'log'} [scale] what the edges are spaced by
 * @returns {{edges: Float64Array, counts: Uint32Array, log: boolean,
 *   wanted: string, refused: boolean}}
 */
export function histogram(sorted, bins = null, scale = 'auto') {
	const n = sorted.length;
	if (n < 2) {
		return {
			edges: new Float64Array(0), counts: new Uint32Array(0),
			log: false, wanted: scale, refused: false,
		};
	}
	const asked = Math.round(Number(bins));
	const k = Number.isFinite(asked) && asked >= HIST_BINS.min
		? Math.min(HIST_BINS.max, asked)
		: Math.max(5, Math.min(60, Math.ceil(Math.log2(n) + 1)));
	const lo = sorted[0];
	const hi = sorted[n - 1];
	// Decades, judged on the body of the sample and not its extremes: the
	// smallest of two thousand uniforms is a ten-thousandth, and that alone
	// would put a flat sample on a log axis.
	const can = lo > 0;
	const log = scale === 'log' ? can
		: scale === 'linear' ? false
			: can && valueAt(sorted, 0.95) / valueAt(sorted, 0.05) > 100;
	const refused = scale === 'log' && !can;
	const edges = new Float64Array(k + 1);
	for (let b = 0; b <= k; b++) {
		edges[b] = log
			? Math.exp(Math.log(lo) + (Math.log(hi) - Math.log(lo)) * (b / k))
			: lo + (hi - lo) * (b / k);
	}
	const counts = new Uint32Array(k);
	for (let i = 0; i < n; i++) {
		const x = sorted[i];
		let b = log
			? Math.floor(((Math.log(x) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))) * k)
			: Math.floor(((x - lo) / (hi - lo)) * k);
		if (b >= k) b = k - 1;
		if (b < 0) b = 0;
		counts[b]++;
	}
	return { edges, counts, log, wanted: scale, refused };
}
