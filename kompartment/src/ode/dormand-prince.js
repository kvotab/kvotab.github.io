/**
 * The explicit Runge-Kutta (4,5) pair of Dormand and Prince.
 *
 * The tableau is from J. R. Dormand and P. J. Prince, "A family of embedded
 * Runge-Kutta formulae", J. Comp. Appl. Math. 6(1) 19-26 (1980): seven
 * stages, the last evaluated at the new point so that it is the first stage
 * of the next step, and a fifth-order solution with a fourth-order error
 * estimate. The dense output is the quartic interpolant that comes free with
 * the pair, as tabulated by Hairer, Nørsett and Wanner, *Solving Ordinary
 * Differential Equations I*, section II.6.
 *
 * Everything around the step -- step-size control, events, output, the
 * constraint -- is the shared driver in ./onestep.js. Non-negativity here
 * participates only in the error test: an explicit pair cannot hold a state
 * on its bound, since its stages straddle the kink and disagree by the whole
 * jump, so a constraint that binds is something this method reports rather
 * than carries.
 */

import { integrate, SolverError, nonFiniteError, STALL_WINDOW_STEPS, STALL_SPAN_FRACTION } from './onestep.js';

export { SolverError, nonFiniteError, STALL_WINDOW_STEPS, STALL_SPAN_FRACTION };

/** Nodes c_2..c_7 of the tableau. */
const NODES = [1 / 5, 3 / 10, 4 / 5, 8 / 9, 1, 1];

/** Coefficients a_ij of stages 2..7 on the stages before them. */
const STAGE = [
	[1 / 5],
	[3 / 40, 9 / 40],
	[44 / 45, -56 / 15, 32 / 9],
	[19372 / 6561, -25360 / 2187, 64448 / 6561, -212 / 729],
	[9017 / 3168, -355 / 33, 46732 / 5247, 49 / 176, -5103 / 18656],
	[35 / 384, 0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84],
];

/** The difference between the fifth- and fourth-order solutions, per stage. */
const ERROR = [71 / 57600, 0, -71 / 16695, 71 / 1920, -17253 / 339200, 22 / 525, -1 / 40];

/** The free interpolant: per stage, the coefficients of s, s², s³ and s⁴. */
const DENSE = [
	[1, -183 / 64, 37 / 12, -145 / 128],
	[0, 0, 0, 0],
	[0, 1500 / 371, -1000 / 159, 1000 / 371],
	[0, -125 / 32, 125 / 12, -375 / 64],
	[0, 9477 / 3392, -729 / 106, 25515 / 6784],
	[0, -11 / 7, 11 / 3, -55 / 28],
	[0, 3 / 2, -4, 5 / 2],
];

export const dormandPrinceMethod = {
	id: 'dp45',
	order: 4,
	defaultMaxSteps: 1e7,
	holdsAtZero: false,
	snapsToConstraint: false,

	stepBudgetMessage: (maxSteps, t) => (
		`Exceeded ${maxSteps} steps at t=${t}; the system may be stiff `
		+ '-- try a stiff solver (variableOrder or rosenbrock23).'
	),
	floorMessage: (t, hmin, worst) => (
		`Unable to meet integration tolerances at t=${t} without reducing the `
		+ `step below the smallest allowed (${hmin}). State ${worst} is the `
		+ 'worst offender; the system is probably stiff -- try a stiff '
		+ 'solver (variableOrder or rosenbrock23).'
	),
	stallMessage: (t, window, spanCovered) => (
		`The solver stopped making progress at t=${t}: ${window} steps `
		+ `advanced the clock by less than ${spanCovered}. Either the system is stiff `
		+ '-- try a stiff solver (variableOrder or rosenbrock23) -- or a discontinuous rate '
		+ 'is holding a state against zero.'
	),

	setUp({ neq, rhs }) {
		const k = new Array(7);
		for (let i = 0; i < 7; i++) k[i] = new Float64Array(neq);
		const stage = new Float64Array(neq);
		// The step the interpolant belongs to.
		let tFrom = 0;
		let hFrom = 0;
		let yFrom = null;

		const combine = (y, h, row, out) => {
			for (let i = 0; i < neq; i++) {
				let acc = 0;
				for (let j = 0; j < row.length; j++) if (row[j] !== 0) acc += row[j] * k[j][i];
				out[i] = y[i] + h * acc;
			}
			return out;
		};

		return {
			start(t, y) {
				rhs(t, y, k[0]);
				return 1;
			},
			derivativeAtStart() {
				return k[0];
			},
			attempt(t, y, h, tnew, ynew, err) {
				for (let s = 0; s < 5; s++) {
					rhs(t + h * NODES[s], combine(y, h, STAGE[s], stage), k[s + 1]);
				}
				combine(y, h, STAGE[5], ynew);
				rhs(tnew, ynew, k[6]);
				for (let i = 0; i < neq; i++) {
					let acc = 0;
					for (let j = 0; j < 7; j++) if (ERROR[j] !== 0) acc += ERROR[j] * k[j][i];
					err[i] = acc;
				}
				tFrom = t;
				hFrom = h;
				yFrom = y;
				return { fevals: 6, scale: 1 };
			},
			denseAt(tq, out) {
				const s = (tq - tFrom) / hFrom;
				const s2 = s * s;
				const s3 = s2 * s;
				const s4 = s3 * s;
				for (let i = 0; i < neq; i++) {
					let acc = 0;
					for (let j = 0; j < 7; j++) {
						const c = DENSE[j];
						const w = c[0] * s + c[1] * s2 + c[2] * s3 + c[3] * s4;
						if (w !== 0) acc += w * k[j][i];
					}
					out[i] = yFrom[i] + hFrom * acc;
				}
				return out;
			},
			accept(tnew, ynew, reprojected) {
				// The last stage is the first of the next step -- unless the
				// state it was evaluated at has since been projected.
				let spent = 0;
				if (reprojected) { rhs(tnew, ynew, k[6]); spent = 1; }
				k[0].set(k[6]);
				return spent;
			},
			restart() {
				return 0;
			},
			stats() {
				return {};
			},
		};
	},
};

/**
 * @param {(t: number, y: Float64Array, out: Float64Array) => Float64Array} f
 * @param {number[]|Float64Array} tspan  output grid; first and last bound the run
 * @param {Float64Array} y0
 * @param {object} opts  see ./onestep.js
 * @returns {{ t: Float64Array, y: Float64Array[], stats: object }}
 */
export function dormandPrince(f, tspan, y0, opts = {}) {
	return integrate(dormandPrinceMethod, f, tspan, y0, opts);
}
