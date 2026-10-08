/**
 * The spread of a set of realisations at each time: the statistics a sample is
 * drawn with.
 *
 * A probabilistic run here is summarised by these (see ./probabilistic.js),
 * and so is a probabilistic run another tool stored (../io/ecoruns.js) -- one
 * definition, so a band beside a band is the same statistic of both.
 *
 * Both read a series realisation-major: `values[i * times + j]` is
 * realisation i at time j.
 */

/** The band a probabilistic result is drawn as, unless the model says otherwise. */
const QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95];

/**
 * The percentiles a run's bands are drawn at.
 *
 * The model's own list where it has one -- GoldSim keeps the percentile pairs
 * with the model, and so does this -- else the default. Always with the median,
 * because the line through the band is the median and a band with no line is
 * a cloud. Sorted and deduplicated, so a pair typed twice is one pair.
 */
export function percentilesFor(list) {
	const want = new Set([0.5]);
	for (const p of Array.isArray(list) ? list : QUANTILES) {
		const v = Number(p);
		if (Number.isFinite(v) && v > 0 && v < 1) want.add(v);
	}
	return [...want].sort((a, b) => a - b);
}

/**
 * The band at each time: the quantiles asked for, across realisations.
 *
 * Sorted per time rather than interpolated between order statistics, which is
 * the definition anyone checking this by hand would use. Realisations that
 * failed are NaN and are left out, so a band is over what actually ran and the
 * count says how many that was. A `mask` -- 1 to use a realisation, 0 not to
 * -- leaves out the rest, which is how a band is drawn over the categories of
 * realisation a reader has chosen to keep.
 *
 * @returns {{q: number, y: Float64Array}[]} in the order asked for
 */
export function quantiles(values, times, iterations, qs = [0.05, 0.5, 0.95], mask = null) {
	const out = qs.map((q) => ({ q, y: new Float64Array(times) }));
	const column = new Float64Array(iterations);
	for (let j = 0; j < times; j++) {
		let n = 0;
		for (let i = 0; i < iterations; i++) {
			if (mask && !mask[i]) continue;
			const v = values[i * times + j];
			if (Number.isFinite(v)) column[n++] = v;
		}
		const slice = column.subarray(0, n);
		slice.sort();
		for (let k = 0; k < qs.length; k++) {
			out[k].y[j] = n ? slice[Math.min(n - 1, Math.max(0, Math.round(qs[k] * (n - 1))))] : NaN;
		}
	}
	return out;
}

/** The mean at each time, over the realisations that ran. */
export function meanOf(values, times, iterations, mask = null) {
	const out = new Float64Array(times);
	for (let j = 0; j < times; j++) {
		let sum = 0;
		let n = 0;
		for (let i = 0; i < iterations; i++) {
			if (mask && !mask[i]) continue;
			const v = values[i * times + j];
			if (Number.isFinite(v)) { sum += v; n++; }
		}
		out[j] = n ? sum / n : NaN;
	}
	return out;
}
