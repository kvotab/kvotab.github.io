/**
 * The driver the one-step methods share.
 *
 * An explicit Runge-Kutta pair and a Rosenbrock pair differ in how they take a
 * step and in nothing else that matters to a caller: both produce a new state
 * and an estimate of its error, both carry a dense output over the step, and
 * both want the same things done around that -- a step size chosen from the
 * estimate, an end landed on exactly, the discrete events located, the
 * requested output times read off the interpolant, a state that may not go
 * negative kept that way, and a run that has stopped advancing refused rather
 * than continued. Those are here, once. A method supplies the step.
 *
 * WHAT A METHOD SUPPLIES. `method.setUp(ctx)` is called once and returns an
 * object with:
 *
 *   start(t, y)                          the derivative at the start; returns
 *                                        the evaluations spent
 *   attempt(t, y, h, tnew, ynew, err)    one step of size h into `ynew`, its
 *                                        error vector into `err`; returns
 *                                        {fevals, scale}, with `scale` the
 *                                        factor the weighted error is
 *                                        multiplied by along with |h|
 *   denseAt(tq, out)                     the state inside the step just tried
 *   accept(tnew, ynew, reprojected)      the step was taken; returns fevals
 *   restart(t, y)                        the start state was changed under it
 *                                        (a state put onto its constraint);
 *                                        returns fevals
 *   stats()                              whatever else it counted
 *
 * and the method itself carries `id`, `order` (of the error estimate, which
 * sets the exponent the step is controlled with), `defaultMaxSteps`, and two
 * flags for the constraint: `holdsAtZero`, whether the derivative of a state
 * on its bound is held at zero for it, and `snapsToConstraint`, whether a
 * state within its tolerance of the bound and pushed past it is put onto it.
 *
 * THE CONSTRAINT. A state that may not go negative and would is treated two
 * ways, both here. Its violation joins the error test -- a step that carries
 * it below zero by more than its tolerance is rejected and cut like any other
 * -- and what is left below zero after an accepted step, within tolerance by
 * construction, is projected onto zero and counted. Whether the method also
 * integrates the projected system, holding such a state's derivative at zero,
 * is the method's to say: a Rosenbrock step from the bound does, an explicit
 * pair does not, since its stages would straddle the kink and disagree by the
 * whole jump.
 */

import { locateCrossing } from './events.js';

/** Machine epsilon for a double. */
const EPS = 2 ** -52;

/**
 * The stall guard: how many accepted steps to look back over, and how small a
 * fraction of the run they may have covered before the solver is judged to be
 * pinned rather than merely slow. Measured in elapsed time, not step size: a
 * pinned solver alternates tiny accepted steps with rejected larger ones, so
 * the step size on its own looks healthy.
 */
export const STALL_WINDOW_STEPS = 2000;
export const STALL_SPAN_FRACTION = 1e-9;

/** Steps accepted at the floor in a row before the run is refused. */
const MAX_AT_FLOOR = 20;

/** Safety on the step the error estimate allows; the least and most it may change by. */
const SAFETY = 0.9;
const SHRINK_LEAST = 0.1;
const GROW_MOST = 5;

export class SolverError extends Error {
	constructor(message, t, index) {
		super(message);
		this.name = 'SolverError';
		this.t = t;
		this.index = index;
	}
}

/**
 * The one report for a state or derivative that is not a number, so that the
 * solvers say the same thing about the same fault. `index` is the state that
 * was seen to go, when one is known.
 */
export function nonFiniteError(t, index) {
	const where = index == null ? '' : ` (state ${index})`;
	return new SolverError(
		`The state or its derivative became non-finite at t=${t}${where}. Check for `
		+ `division by zero, a negative base raised to a fractional power, or an `
		+ `initial value that is not a number.`,
		t, index,
	);
}

/** The smallest step that moves the clock at `t`. */
function stepFloor(t) {
	return 16 * EPS * Math.abs(t);
}

/**
 * The derivative of the projected system: where a constrained state is at or
 * below zero and its equation would take it lower, it is held. `<= 0` so a
 * state the projection has just put on zero is held there. The largest
 * derivative held back per state since the last reset is kept for the
 * driver, which judges a step's "held at zero" by it.
 */
function heldDerivative(f, nonNegative) {
	const wrapped = (t, y, out) => {
		f(t, y, out);
		for (let i = 0; i < y.length; i++) {
			if (nonNegative[i] && y[i] <= 0 && out[i] < 0) {
				if (-out[i] > wrapped.push[i]) wrapped.push[i] = -out[i];
				out[i] = 0;
			}
		}
		return out;
	};
	wrapped.push = new Float64Array(nonNegative.length);
	return wrapped;
}

/**
 * @param {object} method  see the file comment
 * @param {(t: number, y: Float64Array, out: Float64Array) => Float64Array} f
 * @param {ArrayLike<number>} tspan  the output times; first and last bound the run
 * @param {Float64Array} y0
 * @param {object} opts  rtol, abstol (number or per state), hmax, hmin, h0,
 *   nonNegative (bool[]), maxSteps, events, jacobian, onAccepted(t, y),
 *   onOutput(t, y) for every requested time as it is passed,
 *   onStep(progress, nsteps, t) -> false to abort
 * @returns {{t: Float64Array, y: Float64Array[], stopped: object|null, stats: object}}
 */
export function integrate(method, f, tspan, y0, opts = {}) {
	const neq = y0.length;
	const npts = tspan.length;
	const t0 = tspan[0];
	const tEnd = tspan[npts - 1];
	const dir = Math.sign(tEnd - t0);
	if (dir === 0) throw new SolverError('Simulation start and end time are equal', t0);
	const span = Math.abs(tEnd - t0);

	const rtol = opts.rtol ?? 1e-3;
	const atol = new Float64Array(neq);
	if (typeof opts.abstol === 'number' || opts.abstol == null) atol.fill(opts.abstol ?? 1e-6);
	else for (let i = 0; i < neq; i++) atol[i] = opts.abstol[i];
	// What the error test divides by, with |y|: the absolute tolerance in
	// units of the relative one.
	const threshold = new Float64Array(neq);
	for (let i = 0; i < neq; i++) threshold[i] = atol[i] / rtol;

	const nonNegative = opts.nonNegative ?? null;
	const maxSteps = opts.maxSteps ?? method.defaultMaxSteps ?? 1e6;
	const maxAtFloor = opts.maxConsecutiveMinStep ?? MAX_AT_FLOOR;
	const hmax = opts.hmax > 0 ? Math.min(opts.hmax, span) : 0.1 * span;
	const hminOpt = opts.hmin > 0 ? opts.hmin : 0;
	const stallWindow = opts.stallWindow ?? STALL_WINDOW_STEPS;
	const stallSpan = STALL_SPAN_FRACTION * span;
	const exponent = 1 / (method.order + 1);

	const rhs = nonNegative && method.holdsAtZero ? heldDerivative(f, nonNegative) : f;
	const stepper = method.setUp({ neq, rhs, f, threshold, atol, rtol, opts });

	// Output: one row per requested time.
	const tout = new Float64Array(npts);
	const yout = new Array(npts);
	let nout = 0;
	const record = (tv, yv) => { tout[nout] = tv; yout[nout] = Float64Array.from(yv); nout++; };

	let t = t0;
	const y = Float64Array.from(y0);
	const ynew = new Float64Array(neq);
	const errVec = new Float64Array(neq);
	const interp = new Float64Array(neq);
	record(t0, y);
	let nextOut = 1;

	let nsteps = 0, nfailed = 0, nfevals = 0, nbelowtol = 0, negative = 0;
	const held = nonNegative && method.holdsAtZero ? new Int32Array(neq) : null;

	// Discrete events: every one is terminal, so the step is cut back to the
	// crossing and the caller restarts from it.
	const events = opts.events ?? null;
	const vL = events ? new Float64Array(events.n) : null;
	const vR = events ? new Float64Array(events.n) : null;
	if (events) events.fun(t0, y, vL);
	let stopped = null;

	nfevals += stepper.start(t, y);

	/** |v| against the larger of the two states and the threshold, at its worst; NaN if any entry is. */
	const weighted = (v, ya, yb) => {
		let worst = 0;
		let at = 0;
		for (let i = 0; i < neq; i++) {
			const e = Math.abs(v[i]) / Math.max(Math.abs(ya[i]), Math.abs(yb[i]), threshold[i]);
			if (!(e >= 0) || !Number.isFinite(yb[i])) return { worst: NaN, at: i };
			if (e > worst) { worst = e; at = i; }
		}
		return { worst, at };
	};

	// --- the first step ----------------------------------------------------------
	// From the size of y' against y, and of y'' out of one explicit Euler
	// trial: a hundredth of the tolerance is asked of the local error a step
	// of the method's order would make.
	let stepSize;
	if (opts.h0 > 0) {
		stepSize = opts.h0;
	} else {
		const f0 = stepper.derivativeAtStart();
		const d0 = weighted(y, y, y).worst / rtol;
		const d1 = weighted(f0, y, y).worst / rtol;
		let guess = d0 < 1e-5 || d1 < 1e-5 ? 1e-6 : 0.01 * (d0 / d1);
		guess = Math.min(guess, hmax);
		const trial = new Float64Array(neq);
		const ftry = new Float64Array(neq);
		for (let i = 0; i < neq; i++) trial[i] = y[i] + dir * guess * f0[i];
		rhs(t0 + dir * guess, trial, ftry);
		nfevals++;
		for (let i = 0; i < neq; i++) ftry[i] -= f0[i];
		let d2 = weighted(ftry, y, y).worst / rtol / guess;
		if (!Number.isFinite(d2)) d2 = 100 * d1;
		const m = Math.max(d1, d2);
		const h1 = m <= 1e-15 ? Math.max(1e-6, guess * 1e-3) : (0.01 / m) ** exponent;
		stepSize = Math.min(100 * guess, h1);
	}
	stepSize = Math.min(hmax, Math.max(stepFloor(t0), hminOpt, stepSize));

	let atFloor = 0;
	let stallStep = 0;
	let stallT = t0;

	for (;;) {
		if (nsteps > maxSteps) {
			throw new SolverError(method.stepBudgetMessage(maxSteps, t), t);
		}

		const hmin = Math.max(stepFloor(t), hminOpt);
		stepSize = Math.min(hmax, Math.max(hmin, stepSize));
		let h = dir * stepSize;
		let last = false;
		if (1.1 * stepSize >= Math.abs(tEnd - t)) {
			h = tEnd - t;
			stepSize = Math.abs(h);
			last = true;
		}

		let err = 0;
		let worstAt = 0;
		let failedOnce = false;
		let restart = false;
		let tnew = t;
		for (;;) {
			tnew = last ? tEnd : t + h;
			h = tnew - t;
			const { fevals, scale } = stepper.attempt(t, y, h, tnew, ynew, errVec);
			nfevals += fevals;
			const w = weighted(errVec, y, ynew);
			err = w.worst * stepSize * scale;
			worstAt = w.at;

			// A stage that is not a number is a failed step, not a fatal one:
			// a stage can overshoot into the square root of a slightly negative
			// inventory, or past the instant a rate stops being defined, and a
			// shorter step lands inside the domain again. When even the
			// smallest step cannot be made to say a number, the run is refused.
			if (!Number.isFinite(err)) {
				nfailed++;
				if (stepSize <= hmin) throw nonFiniteError(t, worstAt);
				failedOnce = true;
				stepSize = Math.max(hmin, 0.1 * stepSize);
				h = dir * stepSize;
				last = false;
				continue;
			}

			// A constrained state below zero by more than its tolerance is an
			// error like any other, and the step that put it there is cut --
			// halved, since the estimate says nothing about where the crossing
			// lies.
			let forConstraint = false;
			if (nonNegative && err <= rtol) {
				let worst = 0;
				for (let i = 0; i < neq; i++) {
					if (nonNegative[i] && ynew[i] < 0) {
						const v = -ynew[i] / threshold[i];
						if (v > worst) { worst = v; worstAt = i; }
					}
				}
				if (worst > rtol) { err = worst; forConstraint = true; }
			}

			if (err <= rtol) { atFloor = 0; break; }

			nfailed++;
			// A state within its tolerance of the bound and pushed past it by
			// every step tried never reaches the bound by halving: each shorter
			// step lands it a little nearer, still positive, and the next tries
			// again. Put onto the bound instead, where the method that holds a
			// state there can hold it, and the step is retried from there. The
			// change is smaller than the error test could tell.
			if (forConstraint && method.snapsToConstraint) {
				let snapped = false;
				for (let i = 0; i < neq; i++) {
					if (nonNegative[i] && ynew[i] < 0 && y[i] > 0 && y[i] <= atol[i]) {
						y[i] = 0;
						snapped = true;
					}
				}
				if (snapped) {
					nfevals += stepper.restart(t, y);
					restart = true;
					break;
				}
			}
			const before = stepSize;
			if (forConstraint || failedOnce) stepSize = Math.max(hmin, 0.5 * stepSize);
			else stepSize = Math.max(hmin, stepSize * Math.max(SHRINK_LEAST, SAFETY * (rtol / err) ** exponent));
			failedOnce = true;
			if (stepSize <= hmin) {
				// Nothing shorter is possible: the step is taken as it is and
				// counted, and a run of them is refused.
				if (++atFloor >= maxAtFloor) {
					throw new SolverError(method.floorMessage(t, hmin, worstAt), t, worstAt);
				}
				stepSize = before;
				nbelowtol++;
				break;
			}
			h = dir * stepSize;
			last = false;
		}
		if (restart) continue;
		nsteps++;

		// What is left below zero is within tolerance -- the error test saw to
		// that -- and is projected onto the bound. Counted, because a
		// projection is a number the method did not compute.
		let reprojected = false;
		if (nonNegative) {
			for (let i = 0; i < neq; i++) {
				if (nonNegative[i] && ynew[i] < 0) { ynew[i] = 0; reprojected = true; negative++; }
				// Held through this step: the derivative held back would have
				// moved the state by more than its tolerance over the step. A
				// projection alone is not a hold.
				if (held && rhs.push[i] * stepSize > atol[i]) held[i]++;
			}
			if (held) rhs.push.fill(0);
		}

		if (nsteps - stallStep >= stallWindow) {
			if (Math.abs(tnew - stallT) < stallSpan) {
				throw new SolverError(method.stallMessage(tnew, stallWindow, stallSpan), tnew);
			}
			stallStep = nsteps;
			stallT = tnew;
		}

		const denseAt = (tq) => {
			stepper.denseAt(tq, interp);
			if (nonNegative) for (let i = 0; i < neq; i++) if (nonNegative[i] && interp[i] < 0) interp[i] = 0;
			return interp;
		};

		if (events) {
			// The event that stopped the previous segment is still sitting on
			// zero at `t0`; the locator is told so and steps past it.
			const hit = locateCrossing(events, t, vL, tnew, ynew, vR, denseAt, t0);
			if (hit) {
				tnew = hit.t;
				ynew.set(denseAt(tnew));
				vR.set(hit.values);
				stopped = { t: tnew, y: Float64Array.from(ynew), which: hit.which };
				last = true;
			}
			vL.set(vR);
		}

		while (nextOut < npts) {
			const tq = tspan[nextOut];
			if (dir * (tnew - tq) < 0) break;
			const at = tq === tnew ? ynew : denseAt(tq);
			record(tq, at);
			if (opts.onOutput) opts.onOutput(tq, at);
			nextOut++;
		}

		if (opts.onAccepted) opts.onAccepted(tnew, ynew);

		if (opts.onStep && (nsteps & 31) === 0) {
			if (opts.onStep(Math.abs(tnew - t0) / span, nsteps, tnew) === false) {
				throw new SolverError('Simulation aborted', tnew);
			}
		}

		if (last) break;

		// The step is taken. Told to the method only now, after the output:
		// its dense output belongs to the step as it was taken, and what the
		// method rotates or re-evaluates for the next step must not reach it.
		nfevals += stepper.accept(tnew, ynew, reprojected);

		// The next step, from this one's error -- only when it went through
		// first time; a step that failed on the way has been cut already.
		if (!failedOnce) {
			const grow = err > 0 ? SAFETY * (rtol / err) ** exponent : GROW_MOST;
			stepSize *= Math.min(GROW_MOST, Math.max(SHRINK_LEAST, grow));
		}

		t = tnew;
		y.set(ynew);
	}

	return {
		t: tout.subarray(0, nout),
		y: yout.slice(0, nout),
		stopped,
		stats: {
			nsteps, nfailed, nfevals, nbelowtol, negative, held,
			solver: method.id,
			...stepper.stats(),
		},
	};
}
