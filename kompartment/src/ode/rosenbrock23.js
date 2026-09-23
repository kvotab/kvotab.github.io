/**
 * A Rosenbrock (2,3) pair, for stiff systems.
 *
 * The method is the linearly implicit W-method described by L. F. Shampine
 * and M. W. Reichelt, "The MATLAB ODE Suite", SIAM J. Sci. Comput. 18(1) 1-22
 * (1997), section 4: two stages, one Jacobian and one factorisation per step,
 * and an embedded third-order estimate to judge the step by. With
 * d = 1/(2 + √2) and W = I - h·d·J, the stages are
 *
 *     W k1 = f(t, y) + h·d·f_t
 *     W k2 = f(t + h/2, y + h/2·k1) - k1               (then k2 += k1)
 *     y_{n+1} = y + h·k2
 *     W k3 = f(t + h, y_{n+1}) - (6 + √2)(k2 - f(t + h/2, ·)) - 2(k1 - f(t, y)) + h·d·f_t
 *
 * and the error estimate is (h/6)(k1 - 2k2 + k3). It is the solver that
 * matters for a radionuclide chain whose half-lives span many orders of
 * magnitude: an explicit method grinds its step to nothing on the fastest
 * nuclide, and this one does not.
 *
 * The iteration matrix is factorised densely through ./linalg.js, or in CSC
 * through ./sparse.js where a supplied pattern pays for it. Everything around
 * the step -- step-size control, events, output, the constraint -- is the
 * shared driver in ./onestep.js.
 *
 * The published pair has no non-negativity option. This one takes the
 * option's meaning from the methods that have it: the derivative of a state
 * on its bound may not carry it lower, a violation larger than the tolerance
 * fails the error test and cuts the step, and what is left below zero after
 * an accepted step is projected back and counted. A state held at zero keeps
 * delivering whatever its outflows say, so an empty compartment drained at an
 * absolute rate of one for ten years still hands ten units to its neighbour
 * -- the projected system the option asks for. A constraint that takes hold
 * *inside* a run is another matter: a one-step method's stages straddle the
 * kink and disagree by the whole jump, so the step is cut and cut again, and
 * the driver's stall guard is what ends that with an explanation.
 */

import { LU } from './linalg.js';
import { sparseIterationMatrix } from './sparse.js';
import { integrate, SolverError } from './onestep.js';

/** What this tool adds to the shared sparse LU's singular message. */
const SINGULAR_HINT = 'A compartment with no way in and no way out will do this.';

const D = 1 / (2 + Math.SQRT2);
const E32 = 6 + Math.SQRT2;
const EPS = 2 ** -52;
const SQRT_EPS = Math.sqrt(EPS);

/**
 * df/dy by forward differences of the derivative the method integrates, one
 * column per evaluation, or through a sparsity pattern and a colouring of its
 * columns when one was supplied. The increment for a column is sqrt(eps)
 * times the larger of the state and its error threshold, rounded to what the
 * addition actually changed.
 */
function differences(rhs, neq, threshold) {
	const ytry = new Float64Array(neq);
	const ftry = new Float64Array(neq);
	const delta = new Float64Array(neq);
	const increment = (y, j) => {
		let del = SQRT_EPS * Math.max(Math.abs(y[j]), threshold[j]);
		if (del === 0) del = SQRT_EPS;
		const moved = (y[j] + del) - y[j];
		return moved === 0 ? del : moved;
	};
	return {
		dense(t, y, fy, rows) {
			ytry.set(y);
			for (let j = 0; j < neq; j++) {
				const del = increment(y, j);
				ytry[j] = y[j] + del;
				rhs(t, ytry, ftry);
				ytry[j] = y[j];
				for (let i = 0; i < neq; i++) rows[i][j] = (ftry[i] - fy[i]) / del;
			}
			return neq;
		},
		sparse(t, y, fy, pattern, groups, out) {
			const { colPtr, rowIdx } = pattern;
			let spent = 0;
			const perturb = (cols) => {
				ytry.set(y);
				for (const j of cols) {
					delta[j] = increment(y, j);
					ytry[j] = y[j] + delta[j];
				}
				rhs(t, ytry, ftry);
				spent++;
				for (const j of cols) {
					for (let p = colPtr[j]; p < colPtr[j + 1]; p++) {
						out[p] = (ftry[rowIdx[p]] - fy[rowIdx[p]]) / delta[j];
					}
				}
			};
			if (groups) for (const g of groups) perturb(g);
			else for (let j = 0; j < neq; j++) perturb([j]);
			return spent;
		},
	};
}

export const rosenbrockMethod = {
	id: 'ros23',
	order: 2,
	defaultMaxSteps: 1e6,
	holdsAtZero: true,
	snapsToConstraint: true,

	stepBudgetMessage: (maxSteps, t) => `Exceeded ${maxSteps} steps at t=${t}.`,
	floorMessage: (t, hmin) => (
		`Unable to meet integration tolerances at t=${t} without reducing `
		+ `the step below the smallest allowed (${hmin}).`
	),
	stallMessage: (t, window, spanCovered) => (
		`The solver stopped making progress at t=${t}: ${window} steps `
		+ `advanced the clock by less than ${spanCovered}. This usually means a `
		+ 'state reaching zero while its equations push it below -- a constraint '
		+ 'that binds is not one a one-step method can carry; turn "cannot go '
		+ 'negative" off on the compartment to see what the model really does, '
		+ 'or use variableOrder -- or that a rate changes faster than the step size '
		+ 'can follow.'
	),

	/**
	 * `opts.jacobian` supplies df/dy instead of differencing it: a function
	 * (t, y, J) filling dense rows, or the object ../sim/jacobian.js builds,
	 * whose `constant` flag says the matrix never changes -- and since this
	 * method re-forms its Jacobian at every step, that flag turns n+1
	 * evaluations per step into one. An `evaluate` that answers null has no
	 * usable matrix at that point, and the step differences instead.
	 */
	setUp({ neq, rhs, threshold, opts }) {
		const supplied = opts.jacobian ?? null;
		const analytic = typeof supplied === 'function'
			? supplied
			: supplied?.evaluateDense
				? (t, y, J) => supplied.evaluateDense(t, y, J)
				: null;
		const constant = !!supplied?.constant;
		const pattern = supplied?.pattern ?? null;
		const groups = Array.isArray(supplied?.groups) ? supplied.groups : null;
		const diff = differences(rhs, neq, threshold);

		const J = new Array(neq);
		for (let i = 0; i < neq; i++) J[i] = new Float64Array(neq);
		let values = pattern ? new Float64Array(pattern.nnz) : null;
		const f0 = new Float64Array(neq);
		const f1 = new Float64Array(neq);
		const f2 = new Float64Array(neq);
		const ft = new Float64Array(neq);
		const tmp = new Float64Array(neq);
		let k1 = null;
		let k2 = null;
		let npds = 0;
		let ndecomps = 0;
		let spent = 0;
		let needJacobian = true;
		let dfdtAt = NaN; // the start time df/dt was last formed for
		// The step the interpolant belongs to.
		let tFrom = 0;
		let hFrom = 0;
		let yFrom = null;

		/** The pattern's values at (t, y): supplied, or differenced through it. */
		const sparseJacobian = (t, y) => {
			const got = supplied.evaluate(t, y);
			if (got) return got;
			spent += diff.sparse(t, y, f0, pattern, groups, values);
			return values;
		};
		/** Dense rows at (t, y): supplied, or differenced. */
		const denseJacobian = (t, y) => {
			if (analytic && analytic(t, y, J) !== null) return J;
			spent += diff.dense(t, y, f0, J);
			return J;
		};
		/** A pattern's values scattered into dense rows, for a factorisation the fill made dense. */
		const scatter = (vals) => {
			for (let i = 0; i < neq; i++) J[i].fill(0);
			for (let j = 0; j < neq; j++) {
				for (let p = pattern.colPtr[j]; p < pattern.colPtr[j + 1]; p++) J[pattern.rowIdx[p]][j] = vals[p];
			}
		};

		// The linear algebra: sparse where a pattern was given and the fill
		// says it pays, dense otherwise.
		let sparse = null;
		let dense = null;
		let lu = null;
		const solveWith = (h, t) => {
			if (sparse) {
				try {
					sparse.form(h * D, values);
				} catch (e) {
					throw new SolverError(`${e.message} (at t=${t})`, t);
				}
				ndecomps++;
				return (b) => sparse.solve(b);
			}
			for (let i = 0; i < neq; i++) {
				const row = dense[i];
				const src = J[i];
				for (let j = 0; j < neq; j++) row[j] = -h * D * src[j];
				row[i] += 1;
			}
			lu.factorize(dense);
			if (lu.singular) {
				throw new SolverError(
					`The iteration matrix is singular at t=${t}. A compartment may be `
					+ 'disconnected or a transfer rate may be non-finite.', t,
				);
			}
			ndecomps++;
			return (b) => lu.solve(b);
		};

		return {
			start(t, y) {
				rhs(t, y, f0);
				if (pattern) {
					// One factorisation of each ordering decides whether the
					// pattern pays; a matrix this size is often better dense.
					values = sparseJacobian(t, y);
					npds++;
					needJacobian = false;
					sparse = sparseIterationMatrix(neq, pattern, values, { hint: SINGULAR_HINT });
					if (!sparse) scatter(values);
				}
				if (!sparse) {
					dense = new Array(neq);
					for (let i = 0; i < neq; i++) dense[i] = new Float64Array(neq);
					lu = new LU(neq);
				}
				return 1;
			},
			derivativeAtStart() {
				return f0;
			},
			attempt(t, y, h, tnew, ynew, err) {
				const before = spent;
				// A constant Jacobian is formed once; anything else at the
				// start of every step, as the method requires.
				if (needJacobian && !(constant && npds > 0)) {
					if (sparse) values = sparseJacobian(t, y);
					else if (analytic || !pattern) denseJacobian(t, y);
					else scatter(sparseJacobian(t, y));
					npds++;
				}
				needJacobian = false;
				// df/dt by a one-sided difference, once per step: it depends on
				// where the step starts and not on how long it is.
				if (dfdtAt !== t) {
					const dt = Math.sign(h) * Math.min(SQRT_EPS * Math.max(Math.abs(t), Math.abs(t + h)), Math.abs(h));
					rhs(t + dt, y, f1);
					spent++;
					for (let i = 0; i < neq; i++) ft[i] = (f1[i] - f0[i]) / dt;
					dfdtAt = t;
				}
				const solve = solveWith(h, t);

				for (let i = 0; i < neq; i++) tmp[i] = f0[i] + h * D * ft[i];
				k1 = solve(tmp);
				for (let i = 0; i < neq; i++) tmp[i] = y[i] + 0.5 * h * k1[i];
				rhs(t + 0.5 * h, tmp, f1);
				for (let i = 0; i < neq; i++) tmp[i] = f1[i] - k1[i];
				k2 = solve(tmp);
				for (let i = 0; i < neq; i++) k2[i] += k1[i];
				for (let i = 0; i < neq; i++) ynew[i] = y[i] + h * k2[i];
				rhs(tnew, ynew, f2);
				for (let i = 0; i < neq; i++) {
					tmp[i] = f2[i] - E32 * (k2[i] - f1[i]) - 2 * (k1[i] - f0[i]) + h * D * ft[i];
				}
				const k3 = solve(tmp);
				spent += 2;
				for (let i = 0; i < neq; i++) err[i] = k1[i] - 2 * k2[i] + k3[i];
				tFrom = t;
				hFrom = h;
				yFrom = y;
				const fevals = spent - before;
				return { fevals, scale: 1 / 6 };
			},
			denseAt(tq, out) {
				// The quadratic through the two ends of the step with the
				// slope f(t, y) at its start: P(s) = y + s·h·f0 + s²·h·(k2 - f0).
				const s = (tq - tFrom) / hFrom;
				for (let i = 0; i < neq; i++) {
					out[i] = yFrom[i] + s * hFrom * f0[i] + s * s * hFrom * (k2[i] - f0[i]);
				}
				return out;
			},
			accept(tnew, ynew, reprojected) {
				// The next step starts from the state after the projection,
				// so the derivative it starts from has to be read there.
				let used = 0;
				if (reprojected) { rhs(tnew, ynew, f2); used = 1; }
				f0.set(f2);
				needJacobian = true;
				dfdtAt = NaN;
				return used;
			},
			restart(t, y) {
				rhs(t, y, f0);
				needJacobian = true;
				dfdtAt = NaN;
				return 1;
			},
			stats() {
				return {
					npds, ndecomps,
					sparse: !!sparse,
					fill: sparse ? sparse.fill : null,
				};
			},
		};
	},
};

/**
 * @param {(t: number, y: Float64Array, out: Float64Array) => Float64Array} f
 * @param {number[]|Float64Array} tspan  output grid; first and last bound the run
 * @param {Float64Array} y0
 * @param {object} opts  see ./onestep.js, plus `jacobian`
 * @returns {{ t: Float64Array, y: Float64Array[], stats: object }}
 */
export function rosenbrock23(f, tspan, y0, opts = {}) {
	return integrate(rosenbrockMethod, f, tspan, y0, opts);
}
