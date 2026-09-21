/**
 * Lookup tables: a value that changes with time.
 *
 * The table is a list of (x, y) points and a rule for reading between and
 * beyond them; in almost every real model x is the simulation clock, which is
 * how a model says "the flow rate follows this measured series" or "the
 * glaciation rescales the groundwater from year 10000".
 *
 * Five rules, named here for what they do, with the counts they carry across
 * the 200 model files on this machine:
 *
 *   linear       straight lines between the points, held flat at the ends
 *                (spelled Interpolation-Use End Values in a file, and the
 *                default there)                                            3261
 *   below        the value at or before x                                    90
 *   extrapolate  as `linear`, but the end segments are continued outwards     31
 *   above        the value at or after x                                       0
 *   nearest      the value of whichever point is closer                        0
 *
 * `cyclic` wraps x into the table's own span first, so a year of data can
 * drive a century of simulation. Nothing in the corpus uses it; it is four
 * lines and it is what the file format says, so it is here.
 *
 * The usual implementation walks a cursor from wherever it left off, which is fast while a
 * solver steps forwards and slow when it steps back. A stiff solver does both,
 * and it re-evaluates the same instant repeatedly inside a Newton iteration, so
 * this looks the point up by bisection instead: no state, no history, the same
 * answer whatever order the solver asks in.
 */

/** The rules, in the order the interface offers them. */
export const INTERPOLATIONS = ['linear', 'extrapolate', 'below', 'above', 'nearest'];

/** How Ecolego spells them in a saved project. */
const FROM_ECO = {
	'Interpolation-Use End Values': 'linear',
	'Interpolation-Extrapolation': 'extrapolate',
	'Use Input Below': 'below',
	'Use Input Above': 'above',
	'Use Input Nearest': 'nearest',
};

export function interpolationFromEco(name) {
	return FROM_ECO[String(name ?? '').trim()] ?? null;
}

/** A one-line description, for the inspector and the import report. */
export const INTERPOLATION_BLURB = {
	linear: 'straight lines between the points, held flat beyond the ends',
	extrapolate: 'straight lines, with the end segments continued outwards',
	below: 'the value at or before the lookup point',
	above: 'the value at or after the lookup point',
	nearest: 'the value of whichever point is closer',
};

export class LookupError extends Error {
	constructor(message) {
		super(message);
		this.name = 'LookupError';
	}
}

/**
 * Normalises `points` into two sorted arrays.
 *
 * Accepts `[[x, y], ...]`, which is how the project file writes it, or a pair
 * of arrays, which is how the .eco file stores it. Points are sorted by x --
 * a table written out of order would otherwise be read as a saw.
 */
export function toTable(points) {
	let xs;
	let ys;
	// [xs, ys]: two equally long lists of numbers. Every element has to *be* a
	// number, not merely be there: a two-point table whose points each carry a
	// distribution is `[[x, y, pdf], [x, y, pdf]]`, two arrays of three, which
	// otherwise reads as a pair of parallel columns and takes the spread for a
	// coordinate.
	const flat = (a) => Array.isArray(a)
		&& a.every((v) => typeof v === 'number' || typeof v === 'string');
	if (Array.isArray(points) && points.length === 2
		&& flat(points[0]) && flat(points[1])
		&& points[0].length === points[1].length && points[0].length !== 2) {
		[xs, ys] = points;
	} else {
		const pairs = points ?? [];
		xs = pairs.map((p) => (Array.isArray(p) ? p[0] : p?.x));
		ys = pairs.map((p) => (Array.isArray(p) ? p[1] : p?.y));
	}

	const order = xs.map((x, i) => i).sort((a, b) => Number(xs[a]) - Number(xs[b]));
	const x = new Float64Array(order.length);
	const y = new Float64Array(order.length);
	order.forEach((from, i) => {
		x[i] = Number(xs[from]);
		y[i] = Number(ys[from]);
	});
	return { x, y };
}

/**
 * A table ready to be read.
 *
 * @param {Array} points        [[x, y], ...] or [xs, ys]
 * @param {object} [options]    { interpolation, cyclic }
 * @returns {{at: (x: number) => number, slopeAt: (x: number) => number,
 *            length: number, first: number, last: number}}
 */
export function makeTable(points, { interpolation = 'linear', cyclic = false } = {}) {
	if (!INTERPOLATIONS.includes(interpolation)) {
		throw new LookupError(
			`'${interpolation}' is not an interpolation rule `
			+ `(${INTERPOLATIONS.join(', ')})`,
		);
	}
	const { x, y } = toTable(points);
	const n = x.length;
	if (!n) throw new LookupError('A lookup table needs at least one point');
	for (let i = 0; i < n; i++) {
		if (!Number.isFinite(x[i])) throw new LookupError('A lookup point has no x value');
	}

	const first = x[0];
	const last = x[n - 1];
	const span = last - first;
	const wrap = cyclic && span > 0
		? (v) => {
			// The arithmetic to match: a remainder that keeps its sign, put
			// back on the table's own interval.
			const a = (v - first) % span;
			return a >= 0 ? a + first : a + span + first;
		}
		: (v) => v;

	/** The last index with x[i] <= v, clamped into [0, n - 2]. */
	const segment = (v) => {
		let lo = 0;
		let hi = n - 1;
		while (lo < hi) {
			const mid = (lo + hi + 1) >> 1;
			if (x[mid] <= v) lo = mid;
			else hi = mid - 1;
		}
		return Math.min(lo, n - 2);
	};

	const between = (v, i) => {
		const dx = x[i + 1] - x[i];
		// Two points at the same x: the later one wins, which is how a table
		// expresses a step.
		if (dx === 0) return y[i + 1];
		return y[i] + ((v - x[i]) / dx) * (y[i + 1] - y[i]);
	};

	const at = (raw) => {
		const v = wrap(raw);
		// A single point is that value everywhere. The convention is to return whatever
		// its cache happened to hold, which for a table read at t0 is zero --
		// a bug this tool does not reproduce.
		if (n === 1) return y[0];

		if (v <= first) {
			if (interpolation !== 'extrapolate') return y[0];
			return between(v, 0);
		}
		if (v >= last) {
			if (interpolation !== 'extrapolate') return y[n - 1];
			return between(v, n - 2);
		}

		const i = segment(v);
		switch (interpolation) {
			case 'below':
				return y[i];
			case 'above':
				return x[i] === v ? y[i] : y[i + 1];
			case 'nearest': {
				const dx = x[i + 1] - x[i];
				return dx === 0 || (v - x[i]) / dx < 0.5 ? y[i] : y[i + 1];
			}
			default:
				return between(v, i);
		}
	};

	/**
	 * dy/dx at a point, which is what a Jacobian wants when the lookup key is
	 * an expression rather than the clock. Zero for the piecewise-constant
	 * rules, and at a point where the value jumps: a step has no slope, and
	 * inventing one would put an entry of 1/0 into the iteration matrix.
	 */
	const slopeAt = (raw) => {
		if (n === 1) return 0;
		if (interpolation === 'below' || interpolation === 'above'
			|| interpolation === 'nearest') return 0;
		const v = wrap(raw);
		if (v < first || v > last) {
			if (interpolation !== 'extrapolate') return 0;
			const i = v < first ? 0 : n - 2;
			const dx = x[i + 1] - x[i];
			return dx === 0 ? 0 : (y[i + 1] - y[i]) / dx;
		}
		const i = segment(v);
		const dx = x[i + 1] - x[i];
		return dx === 0 ? 0 : (y[i + 1] - y[i]) / dx;
	};

	return { at, slopeAt, length: n, first, last, x, y, interpolation, cyclic };
}

/**
 * The `interpolation*` functions an equation can call directly, whose
 * arguments are the lookup point followed by the table, interleaved:
 * `interpolationUseEndValues(XI, X1, Y1, X2, Y2, ...)`.
 *
 * Ecolego offers these beside the block, and models use them for a table too
 * small to be worth a block of its own -- 343 calls across the corpus, all of
 * them the end-values form.
 */
export function interpolateArgs(args, interpolation) {
	const [key, ...rest] = args;
	if (rest.length < 2 || rest.length % 2 !== 0) {
		throw new LookupError(
			`interpolation needs a lookup value and then x, y pairs; got `
			+ `${rest.length} value(s) after it`,
		);
	}
	const pairs = [];
	for (let i = 0; i < rest.length; i += 2) pairs.push([rest[i], rest[i + 1]]);
	return makeTable(pairs, { interpolation }).at(key);
}

/** The slope of that same table at the lookup point. */
export function interpolateSlope(args, interpolation) {
	const [key, ...rest] = args;
	if (rest.length < 2 || rest.length % 2 !== 0) return 0;
	const pairs = [];
	for (let i = 0; i < rest.length; i += 2) pairs.push([rest[i], rest[i + 1]]);
	return makeTable(pairs, { interpolation }).slopeAt(key);
}
