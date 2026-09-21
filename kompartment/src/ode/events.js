/**
 * Locating the instant an event function crosses zero inside a step.
 *
 * A discrete event is an expression that changes sign -- `first - second`,
 * upwards, downwards or either way -- and the model wants it applied at the
 * instant of the crossing, not at whichever time the solver's next step
 * happens to land on. A step that spans a thousand years and merely notices
 * the sign change at its end is not the same model.
 *
 * So after every accepted step the event functions are read at both ends of
 * it, and where a component has changed sign the crossing is pinned down with
 * a bracketing search over the solver's own dense output. Every event in this
 * tool is terminal: the integration stops at the earliest crossing, the model
 * applies the event, and the solver is started again from there. Only the
 * earliest crossing in a step is therefore ever needed.
 *
 * The search is a safeguarded regula falsi. Each iteration takes the secant
 * root of whichever crossing component predicts the earliest crossing, and
 * falls back to the midpoint whenever that root lies outside the bracket or
 * the same end of the bracket has been kept twice running -- the Illinois
 * remedy, which is what stops a function that grazes zero from pinning one
 * end of the bracket in place.
 *
 * **A zero at the start of a segment is not a crossing.** The event that
 * stopped the previous segment is exactly zero at the instant the next one
 * begins, and by the sign test alone it "crosses" the moment it moves. A
 * caller that restarts after each event would be walked round that loop for
 * ever, and worse, a genuine crossing of a *different* event in the same step
 * would be hidden behind the false one. So the caller says where the segment
 * began, and a component that is exactly zero there is judged by where it has
 * gone half a tolerance later: away from zero and it is simply not crossing,
 * still on zero and it is left alone until it moves.
 */

/** Machine epsilon for a double. */
const EPS = 2 ** -52;

/** Whether component `i` changes sign between two sets of event values in the allowed direction. */
export function crosses(vL, vR, direction, i) {
	const a = vL[i];
	const b = vR[i];
	if (Math.sign(a) === Math.sign(b)) return false;
	return direction[i] * (b - a) >= 0;
}

/** Whether any component crosses. */
export function anyCrossing(vL, vR, direction) {
	for (let i = 0; i < vL.length; i++) if (crosses(vL, vR, direction, i)) return true;
	return false;
}

/**
 * How closely a crossing in `[tL, tR]` is pinned down: a few dozen units of
 * round-off in the times themselves, and never more than the step, so that a
 * very short step is not bisected for ever. The floor of one keeps a run that
 * starts at zero from asking for a tolerance of zero. It is scaled by the
 * *step's* times and not by the run's end: the same number scaled by the end
 * of a million-year run swallowed every crossing within 3e-8 of a segment's
 * start, which is a whole step at the start of a decay chain.
 */
export function crossingTolerance(tL, tR) {
	const scale = Math.max(Math.abs(tL), Math.abs(tR), 1);
	return Math.min(Math.abs(tR - tL), 64 * EPS * scale);
}

/** The earliest secant root any crossing component predicts, as a fraction of the bracket. */
function earliestSecant(vlo, vhi, direction) {
	let frac = 1;
	for (let i = 0; i < vlo.length; i++) {
		if (!crosses(vlo, vhi, direction, i)) continue;
		const a = vlo[i];
		const b = vhi[i];
		let f = a === b ? 0.5 : -a / (b - a);
		if (!(f > 0 && f < 1)) f = 0.5;
		if (f < frac) frac = f;
	}
	return frac;
}

/**
 * The earliest zero-crossing in `(tL, tR]`, or null when there is none.
 *
 * @param {(t: number) => ArrayLike<number>} valuesAt  event values at a time
 *        inside the step, read off the solver's own dense output. The array
 *        handed back may be kept by the search, so it must be a fresh one.
 * @param {number} tL  time at the start of the step
 * @param {ArrayLike<number>} vL  event values there
 * @param {number} tR  time at the end of the step
 * @param {ArrayLike<number>} vR  event values there
 * @param {ArrayLike<number>} direction  +1, -1 or 0 per component
 * @param {{tol?: number, tStart?: number}|number} [opts]
 *        `tol`: how closely to pin the crossing down. A bare number is read
 *        as this. `tStart`: the time the *segment* began at; a component that
 *        is exactly zero there is the event that stopped the previous segment
 *        and is not a crossing until it has left zero.
 * @returns {{t: number, values: ArrayLike<number>, which: number[]}|null}
 */
export function firstCrossing(valuesAt, tL, vL, tR, vR, direction, opts) {
	if (typeof opts === 'number') opts = { tol: opts };
	const tol = opts?.tol ?? crossingTolerance(tL, tR);
	const tStart = opts?.tStart;
	const tdir = Math.sign(tR - tL);

	let lo = tL;
	let vlo = vL;
	// The resting zero. A component sitting exactly on zero where the segment
	// began has no secant to offer and is not a crossing: it is judged by
	// where it has gone half a tolerance in.
	if (tStart !== undefined && tL === tStart) {
		let resting = false;
		for (let i = 0; i < vL.length; i++) if (vL[i] === 0 && vR[i] !== 0) { resting = true; break; }
		if (resting) {
			lo = tL + tdir * 0.5 * tol;
			if (tdir * (tR - lo) <= 0) return null;
			vlo = Array.from(valuesAt(lo));
			// Still on zero half a tolerance in: it has not moved, and a
			// component that has not moved is left out of the search.
			for (let i = 0; i < vlo.length; i++) if (vlo[i] === 0 && vL[i] === 0) vlo[i] = vR[i];
		}
	}
	if (!anyCrossing(vlo, vR, direction)) return null;

	let hi = tR;
	let vhi = vR;
	// Which end the last probe replaced: +1 the right, -1 the left, 0 neither
	// yet. Two probes running that move the same end are the sign of a root
	// the secant cannot reach, and the next probe bisects.
	let kept = 0;
	let sameEnd = 0;
	for (let iter = 0; iter < 80 && Math.abs(hi - lo) > tol; iter++) {
		let mid;
		if (sameEnd >= 2) {
			mid = 0.5 * (lo + hi);
		} else {
			mid = lo + earliestSecant(vlo, vhi, direction) * (hi - lo);
			// Not within a tolerance of either end, or the bracket stops
			// shrinking on a function that is nearly flat at one end.
			const inner = 0.5 * tol;
			if (tdir * (mid - lo) < inner) mid = lo + tdir * inner;
			if (tdir * (hi - mid) < inner) mid = hi - tdir * inner;
			if (!(tdir * (mid - lo) > 0 && tdir * (hi - mid) > 0)) mid = 0.5 * (lo + hi);
		}
		const vmid = valuesAt(mid);
		if (anyCrossing(vlo, vmid, direction)) {
			hi = mid;
			vhi = vmid;
			sameEnd = kept === 1 ? sameEnd + 1 : 1;
			kept = 1;
		} else {
			lo = mid;
			vlo = vmid;
			sameEnd = kept === -1 ? sameEnd + 1 : 1;
			kept = -1;
		}
	}

	const which = [];
	for (let i = 0; i < vlo.length; i++) if (crosses(vlo, vhi, direction, i)) which.push(i);
	// The bracket has closed on the crossing: its right end is the first
	// time at which the event has happened.
	return { t: hi, values: vhi, which };
}

/**
 * The event check after one accepted step, in the shape the solvers call it.
 * The event values at the end of the step are written into `vR`, and the
 * earliest crossing inside the step comes back, or null. The caller decides
 * what to do with the hit and rolls `vL` forward itself, since the hit's
 * values replace `vR` when the step is cut short.
 *
 * @param {{n: number, direction: ArrayLike<number>, fun: Function}} events
 * @param {number} t  start of the step
 * @param {Float64Array} vL  event values there
 * @param {number} tnew  end of the step
 * @param {Float64Array} ynew  state there
 * @param {Float64Array} vR  filled with the event values at `tnew`
 * @param {(tq: number) => Float64Array} denseAt  the solver's own interpolant;
 *        the state it returns is read at once and may be a reused buffer
 * @param {number} tStart  the time this segment of the run began at
 */
export function locateCrossing(events, t, vL, tnew, ynew, vR, denseAt, tStart) {
	events.fun(tnew, ynew, vR);
	if (!anyCrossing(vL, vR, events.direction)) return null;
	const at = (tq) => {
		const out = new Float64Array(events.n);
		events.fun(tq, denseAt(tq), out);
		return out;
	};
	return firstCrossing(at, t, vL, tnew, vR, events.direction, { tStart });
}
