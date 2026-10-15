/**
 * Where a step has to end so as not to pass over a pulse in a table.
 *
 * A solver looks at the derivative at the ends of its steps and at its stages
 * inside them, and nowhere else. A table read at the clock that rises and
 * falls back between two of those places is never seen, and what it would
 * have put into the model is lost: a twenty-year pulse at year 10,000, in a
 * model that had nothing in it until then, arrives as nothing at all, and a
 * spike on top of a steady release as the steady release alone. The error
 * test cannot help, because it judges a step by what the step saw.
 *
 * So each turn of each such table -- a point higher than both its neighbours,
 * or lower -- is a place a step may not cover whole when the turn matters:
 * when the area it adds to the straight line between its neighbours is more
 * than rtol of what the table holds over that step. A wiggle in a long series
 * of numbers does not; a pulse after a time of zero always does. Such a step
 * ends at the turn instead, where the solver sees it and takes the steps it
 * needs. A table with points higher and lower all along it costs a check per
 * step and lands nowhere, unless a step comes long enough to pass a turn
 * that holds more than rtol of what it passes.
 *
 * A turn is judged over the stretch a step would have to cover to miss it
 * altogether, by the interpolation rule: the two neighbours for straight
 * lines, the turn's own flat stretch for the step-wise rules. Where a step
 * ends is inside that stretch, never on a jump, where a time that comes out
 * an ulp short would read the value before it. Tables read at an expression
 * rather than the clock, and cyclic tables, are left out: the first turn
 * where the expression does, and a cycle passed over many times is a matter
 * of its average, not of one turn.
 *
 * The same rule is python/kompartment/engine/landing.py and
 * julia/src/engine/landing.jl, number for number.
 */

const EPS = 2 ** -52;

/** Turns judged together: one maximum each, so a long step skips quiet stretches. */
export const LANDING_BLOCK = 32;

/**
 * @param {Array<{x: ArrayLike<number>, y: ArrayLike<number>, interpolation?: string}>} tables
 *        the tables read at the clock, each once
 * @param {number} rtol
 * @returns {((t: number, tNext: number) => number) | null}  where a step from
 *        t to tNext is to end instead, or NaN; null when no table has a turn
 */
export function tableLanding(tables, rtol) {
	const tabs = [];
	for (const table of tables) {
		const x = table.x;
		const y = table.y;
		const n = x.length;
		if (n < 3) continue;
		const rule = table.interpolation ?? 'linear';
		const A = [];
		const B = [];
		const AT = [];
		const CRIT = [];
		for (let i = 1; i < n - 1; i++) {
			const y0 = y[i - 1];
			const y1 = y[i];
			const y2 = y[i + 1];
			if (!((y1 > y0 && y1 >= y2) || (y1 < y0 && y1 <= y2))) continue;
			const x0 = x[i - 1];
			const x1 = x[i];
			const x2 = x[i + 1];
			// The stretch a step has to cover to see none of the turn, and the
			// time inside it to end on.
			let a;
			let b;
			let at;
			if (rule === 'below') {
				a = x1; b = x2; at = 0.5 * (x1 + x2);
			} else if (rule === 'above') {
				a = x0; b = x1; at = 0.5 * (x0 + x1);
			} else if (rule === 'nearest') {
				a = 0.5 * (x0 + x1); b = 0.5 * (x1 + x2); at = x1;
			} else {
				a = x0; b = x2; at = x0 < x1 && x1 < x2 ? x1 : 0.5 * (x0 + x2);
			}
			if (!(b - a > 1024 * EPS * Math.max(Math.abs(a), Math.abs(b)))) continue;
			const span = x2 - x0;
			const chord = y0 + (y2 - y0) * ((x1 - x0) / span);
			const bump = 0.5 * span * Math.abs(y1 - chord);
			if (!(bump > 0)) continue;
			A.push(a);
			B.push(b);
			AT.push(at);
			CRIT.push(bump / rtol);
		}
		const m = A.length;
		if (!m) continue;
		const ay = new Float64Array(n);
		const cum = new Float64Array(n);
		for (let j = 0; j < n; j++) ay[j] = Math.abs(y[j]);
		for (let j = 1; j < n; j++) cum[j] = cum[j - 1] + 0.5 * (x[j] - x[j - 1]) * (ay[j - 1] + ay[j]);
		const nb = Math.ceil(m / LANDING_BLOCK);
		const blockMax = new Float64Array(nb);
		for (let q = 0; q < nb; q++) {
			let top = 0;
			for (let i = q * LANDING_BLOCK; i < Math.min(m, (q + 1) * LANDING_BLOCK); i++) {
				if (CRIT[i] > top) top = CRIT[i];
			}
			blockMax[q] = top;
		}
		tabs.push({
			x: Float64Array.from(x), ay, cum,
			A: Float64Array.from(A), B: Float64Array.from(B), AT: Float64Array.from(AT),
			CRIT: Float64Array.from(CRIT), blockMax,
		});
	}
	if (!tabs.length) return null;

	return (t, tNext) => {
		if (!(tNext > t)) return NaN;
		let best = NaN;
		for (const tab of tabs) {
			const i = earliestTurn(tab, t, tNext);
			if (i >= 0 && !(tab.AT[i] >= best)) best = tab.AT[i];
		}
		return best;
	};
}

/**
 * The first turn of `tab` that a step from t to tNext covers whole and that
 * holds more than rtol of what the table holds over the step; -1 for none.
 * The turns are in order, and so are their stretches and landing times.
 */
function earliestTurn(tab, t, tNext) {
	const { A, B, CRIT, blockMax } = tab;
	const m = A.length;
	// From the first stretch that starts at or after t ...
	let lo = 0;
	let hi = m;
	while (lo < hi) {
		const mid = (lo + hi) >> 1;
		if (A[mid] < t) lo = mid + 1;
		else hi = mid;
	}
	const i0 = lo;
	// ... to the last that ends at or before tNext.
	lo = i0;
	hi = m;
	while (lo < hi) {
		const mid = (lo + hi) >> 1;
		if (B[mid] <= tNext) lo = mid + 1;
		else hi = mid;
	}
	const i1 = lo;
	if (i1 <= i0) return -1;
	const held = heldBy(tab, tNext) - heldBy(tab, t);
	let i = i0;
	while (i < i1) {
		const q = Math.floor(i / LANDING_BLOCK);
		const end = Math.min(i1, (q + 1) * LANDING_BLOCK);
		if (i === q * LANDING_BLOCK && end === (q + 1) * LANDING_BLOCK && !(blockMax[q] > held)) {
			i = end;
			continue;
		}
		for (; i < end; i++) if (CRIT[i] > held) return i;
	}
	return -1;
}

/** The area under |table| up to s: straight lines between points, flat beyond them. */
function heldBy(tab, s) {
	const { x, ay, cum } = tab;
	const n = x.length;
	if (s <= x[0]) return (s - x[0]) * ay[0];
	if (s >= x[n - 1]) return cum[n - 1] + (s - x[n - 1]) * ay[n - 1];
	let lo = 0;
	let hi = n - 1;
	while (lo < hi) {
		const mid = (lo + hi + 1) >> 1;
		if (x[mid] <= s) lo = mid;
		else hi = mid - 1;
	}
	const j = Math.min(lo, n - 2);
	const dx = x[j + 1] - x[j];
	const v = dx > 0 ? ay[j] + (ay[j + 1] - ay[j]) * ((s - x[j]) / dx) : ay[j + 1];
	return cum[j] + 0.5 * (s - x[j]) * (ay[j] + v);
}
