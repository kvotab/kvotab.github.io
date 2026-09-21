/**
 * When results are saved: the output time grid.
 *
 * The time-series generators a model file can ask for --
 * `GeometricTimeSeries`, `LinearTimeSeries`, `CustomTimeSeries` -- and
 * `TimeSeriesList`, which combines several of them into one sorted set of
 * times. The arithmetic below is theirs, read off the inflow: each generator
 * has its own first and last time point, walks from the first in equal steps
 * (equal *ratios*, for the geometric one), skips whatever falls before the
 * simulation starts, and stops at whichever comes first of its own end and the
 * simulation's.
 *
 * WHY IT IS WORTH HAVING. A safety assessment starts at zero and runs for a
 * hundred thousand years, and a single geometric series over that span cannot
 * describe both ends of it: `log` spacing from a start of zero has to begin
 * somewhere above zero, and everything that happens between the start and that
 * first point is not saved at all. A pulse released in the first year is
 * invisible. With a list, the first year gets a series of its own -- or a
 * handful of times written out by hand -- and the rest of the run keeps the
 * geometric one it needs.
 *
 * The result is a *set*: the union of every series, sorted, with the
 * simulation's own start and end always in it, and duplicates removed. Two
 * series that overlap therefore cost nothing.
 */

/** The kinds of series a list can hold. */
export const SERIES_KINDS = ['log', 'linear', 'times'];

/**
 * How the output times are chosen.
 *
 *   log, linear   one series over the whole run, from `output_points` -- the
 *                 shorthand every file of this tool's own uses
 *   series        a list of them, combined; see above. Ecolego's
 *                 `<time-series-list>` with "Produce specified output only"
 *   solver        no grid at all: the solver's own accepted steps are the
 *                 output. Ecolego's "Produce no additional output", which is
 *                 its *default*, and `EOutputMode.Accepted` in a file
 *   both          the series *and* the solver's steps, combined. Ecolego's
 *                 "Produce additional output"
 *
 * The last three are read out of a .eco file: see readOutputTimes in
 * ../io/eco.js.
 */
export const SPACINGS = ['log', 'linear', 'series', 'solver', 'both'];

/** Two times are the same time when they are this close, relatively. */
const SAME = 1e-9;

/**
 * One series' own time points, inside the simulation's window.
 *
 * `from` and `to` may be null, which is Ecolego's `D_AUTO`: the simulation's
 * own start and end. A `times` series carries its points instead.
 *
 * @param {{kind?: string, spacing?: string, from?: number|null,
 *   to?: number|null, points?: number, times?: number[]}} spec
 * @param {number} t0 when the simulation starts
 * @param {number} t1 when it ends
 * @returns {number[]} in increasing order, possibly empty
 */
export function seriesTimes(spec, t0, t1) {
	const kind = seriesKind(spec);
	if (kind === 'times') {
		// CustomTimeSeries: what was written down, minus anything outside the
		// run -- a time the solver never reaches is not a time it can report.
		return (spec.times ?? [])
			.map((v) => Number(v))
			.filter((v) => Number.isFinite(v) && v >= t0 && v <= t1)
			.sort((a, b) => a - b);
	}

	const n = Math.round(Number(spec.points ?? 0));
	if (!(n >= 2)) return [];
	let from = spec.from == null ? t0 : Number(spec.from);
	const to = spec.to == null ? t1 : Number(spec.to);
	if (!Number.isFinite(from) || !Number.isFinite(to)) return [];

	const out = [];
	// The last time this series may reach: its own end, or the run's.
	const last = Math.min(t1, to);

	if (kind === 'log') {
		// A geometric series cannot start at or below zero, and Ecolego's
		// answer is to start at 1 -- which is the whole reason a model that
		// starts at zero needs a second series for its first year.
		if (from <= 0) from = 1;
		if (!(to > from)) return [];
		const step = (Math.log10(to) - Math.log10(from)) / (n - 1);
		if (!(step > 0)) return [];
		const logFrom = Math.log10(from);
		for (let c = 0; c < n * 4 + 8; c++) {
			const v = 10 ** (logFrom + step * c);
			if (v > last * (1 + SAME)) break;
			if (v >= t0) out.push(v);
		}
		return out;
	}

	// Linear.
	const step = (to - from) / (n - 1);
	if (!(step > 0)) return [];
	for (let c = 0; c < n * 4 + 8; c++) {
		const v = from + step * c;
		if (v > last + Math.abs(step) * SAME) break;
		if (v >= t0) out.push(v);
	}
	return out;
}

/** Which sort of series a spec is, however it was written. */
export function seriesKind(spec) {
	if (Array.isArray(spec?.times)) return 'times';
	const named = String(spec?.kind ?? spec?.spacing ?? 'log');
	return SERIES_KINDS.includes(named) ? named : 'log';
}

/**
 * Ecolego's `TimeSeriesList`: every series, sorted, without duplicates.
 *
 * The simulation's start and end are always in the result. They bound the run
 * whatever the series say, and a result that did not include the state it
 * started from would be missing the one point every chart is read against.
 *
 * Duplicates are removed with a relative tolerance rather than by equality.
 * Two series that meet -- a linear one ending at 1 and a geometric one
 * starting there -- produce 1 and 0.9999999999999998, and a grid with both in
 * it has two columns for one time.
 *
 * @returns {Float64Array}
 */
export function combineSeries(list, t0, t1) {
	const all = [t0, t1];
	// Appended one at a time rather than spread. `push(...times)` passes every
	// element as an argument, and a series of 125,000 points is past what a
	// call can carry: it threw `Maximum call stack size exceeded` from inside
	// what looks like an ordinary array append.
	for (const spec of list ?? []) {
		for (const v of seriesTimes(spec, t0, t1)) all.push(v);
	}
	all.sort((a, b) => a - b);

	const out = [];
	for (const v of all) {
		if (!Number.isFinite(v)) continue;
		const last = out[out.length - 1];
		if (last !== undefined && Math.abs(v - last) <= Math.abs(last || v) * SAME) continue;
		out.push(v);
	}
	return Float64Array.from(out);
}

/** One line saying what a series is, for a panel or a report. */
export function describeSeries(spec, t0 = null, t1 = null) {
	const kind = seriesKind(spec);
	if (kind === 'times') {
		const times = (spec.times ?? []).filter((v) => Number.isFinite(Number(v)));
		return times.length
			? `${times.length} time${times.length === 1 ? '' : 's'}: `
				+ times.slice(0, 4).map(fmt).join(', ') + (times.length > 4 ? ', …' : '')
			: 'no times yet';
	}
	const n = Math.round(Number(spec.points ?? 0));
	const from = spec.from == null ? (t0 == null ? 'the start' : fmt(t0)) : fmt(spec.from);
	const to = spec.to == null ? (t1 == null ? 'the end' : fmt(t1)) : fmt(spec.to);
	return `${n} ${kind === 'log' ? 'logarithmic' : 'even'} point${n === 1 ? '' : 's'}, `
		+ `${from} to ${to}`;
}

/**
 * The times in a series that the run will never reach.
 *
 * `seriesTimes` drops them silently, which is the right thing for a solver --
 * a time outside the run is not a time it can report -- and the wrong thing
 * for a modeller, who wrote those numbers down on purpose. A list written for
 * a hundred-thousand-year run and then used on a thousand-year one saves nine
 * of its twelve times and says nothing about the other three.
 *
 * Only `times` series have numbers of their own to lose this way. A log or a
 * linear series has ends rather than points, and what those do when they fall
 * outside the run is `clippedEnds`.
 *
 * @returns {number[]} the times outside `t0`..`t1`, in the order written
 */
export function droppedTimes(spec, t0, t1) {
	if (seriesKind(spec) !== 'times') return [];
	return (spec.times ?? [])
		.map((v) => Number(v))
		.filter((v) => Number.isFinite(v) && (v < t0 || v > t1));
}

/**
 * Which of a series' own ends lie outside the run, and so do not mean what
 * they say.
 *
 * A `from` before the run starts does not make the series start earlier; it
 * makes the first points fall off. A `to` past the end does worse: the step is
 * worked out from `from` to `to`, so a series of 100 points "to 1e6" on a run
 * that ends at 1e5 is not 100 points over the run -- it is the 84 of them that
 * happen to land inside it, and the spacing is the one the longer run would
 * have had. Neither is refused, and neither is visible from the count.
 *
 * @returns {Array<{end: 'from'|'to', value: number}>}
 */
export function clippedEnds(spec, t0, t1) {
	if (seriesKind(spec) === 'times') return [];
	const out = [];
	for (const end of ['from', 'to']) {
		const v = spec?.[end];
		if (v == null) continue;
		const n = Number(v);
		if (!Number.isFinite(n)) continue;
		if (n < t0 || n > t1) out.push({ end, value: n });
	}
	return out;
}

/** A time, short enough for a label. */
export function fmtTime(v) {
	return fmt(v);
}

/** A time, short enough for a label. */
function fmt(v) {
	const n = Number(v);
	if (!Number.isFinite(n)) return String(v);
	if (n !== 0 && (Math.abs(n) >= 1e5 || Math.abs(n) < 1e-3)) {
		return Number(n.toPrecision(4)).toExponential().replace('e+', 'e');
	}
	return String(Number(n.toPrecision(6)));
}
