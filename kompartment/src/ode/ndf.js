/**
 * A variable-order, variable-step integrator for stiff systems, built on the
 * numerical differentiation formulas (NDFs) of orders one to five, with the
 * backward differentiation formulas (BDFs) as the special case of every
 * kappa set to zero.
 *
 * WHAT THE METHOD IS. Both families fit a polynomial through the most recent
 * k+1 solution values and ask that its derivative at the new time equal the
 * right-hand side there. Written in backward differences of the solution,
 * that is
 *
 *     sum_{m=1..k} (1/m) ∇^m y_{n+1}  -  h f(t_{n+1}, y_{n+1})  =  0
 *
 * for the BDF of order k, and the NDF adds a multiple of the predictor's
 * miss, kappa·gamma_k·(y_{n+1} - y⁰_{n+1}), which buys a smaller error
 * constant at a slight cost in stability: L. F. Shampine and M. W. Reichelt,
 * "The MATLAB ODE Suite", SIAM J. Sci. Comput. 18(1) 1-22 (1997), section 2,
 * give the kappa values used here and the error estimate; E. Hairer and G.
 * Wanner, *Solving Ordinary Differential Equations II*, 2nd ed., Springer
 * (1996), chapter V, are the source for the backward-difference formulation
 * and for the order and step-size strategy. The step size is held constant
 * for as long as the error test allows, and the difference table is rescaled
 * when it changes, which is the quasi-constant-step arrangement.
 *
 * HOW THIS FILE IS ARRANGED. The integrator is a driver over four parts, each
 * of which can be read on its own:
 *
 *   DifferenceTable    the columns ∇^j y_n, the predictor read off them, the
 *                      corrector's history term, and the two linear maps that
 *                      re-express them at another step size or another
 *                      endpoint. One of those maps is also the interpolant.
 *   Weighting          the norm every test is measured in -- per state
 *                      against max(|y|, abstol/rtol), or over the whole
 *                      vector with norm control.
 *   jacobianSource     the four shapes df/dy may be handed over in, and a
 *   Differencer        differenced one for when it is not, or when what was
 *                      handed over declines a point.
 *   iterationMatrix    I - (h/l_k)·J, held and factorised densely or in CSC,
 *                      whichever measured fill says is cheaper.
 *
 * THREE THINGS BEYOND THE PUBLISHED METHOD, each here because a compartment
 * model needed it:
 *
 *   a constraint that binds   `nonNegative` states are integrated as the
 *                             projected system: where such a state is at zero
 *                             and its equations push it lower, its derivative
 *                             is held at zero and its row of the Jacobian
 *                             with it. The run reports every projection and,
 *                             per state, every step it was held through.
 *   a Jacobian that declines  a supplied df/dy may answer null at a point --
 *                             an entry that is not finite there -- and that
 *                             one evaluation is differenced instead.
 *   a stall                   a run that accepts steps but covers none of
 *                             the interval says so and stops, rather than
 *                             grinding until the tab is closed.
 */

import { sparseIterationMatrix } from './sparse.js';
import { LU } from './linalg.js';
import { locateCrossing } from './events.js';

/** Machine epsilon for a double. */
const EPS = 2 ** -52;

/** The highest order offered. The NDFs above five are not stable enough to be worth having. */
export const MAX_ORDER = 5;

/**
 * kappa_k for k = 1..5: the NDF's departure from the BDF of the same order,
 * as published. The BDFs are the same formulas with every kappa zero.
 */
const KAPPA = [-0.185, -1 / 9, -0.0823, -0.0415, 0];

/** gamma_k = sum_{j=1..k} 1/j: the coefficient the corrector puts on ∇^{k+1}. */
const GAMMA = [1, 3 / 2, 11 / 6, 25 / 12, 137 / 60];

/** At most this many Newton iterations per attempt at a step. */
const NEWTON_MAX = 4;
/** The Newton error allowed, as a fraction of rtol, so the error test reads a converged corrector. */
const NEWTON_TOL = 0.3;
/** A contraction rate at or above this is not converging. */
const RATE_LIMIT = 0.9;
/** The smallest contraction rate believed, so one good step cannot vouch for every later one. */
const RATE_FLOOR = 0.02;
/** A correction this far under rtol is converged whatever its rate says. */
const CONVERGED_FLOOR = 1e-3;

/** Safety on the step the error estimate allows, at this order and at the neighbours. */
const SAFETY = 0.8;
const SAFETY_LOWER = 0.75;
const SAFETY_HIGHER = 0.7;
/** The step may not grow by more than this in one change. */
const MAX_GROWTH = 10;
/** Cut on a Newton iteration that will not converge at a fresh Jacobian. */
const NEWTON_CUT = 0.25;

/**
 * The stall guard. Covering almost none of the interval is not on its own
 * evidence of a stall -- a violent initial transient legitimately crawls, and
 * then recovers as the step grows -- so both have to hold: no ground covered
 * over the window, and no larger step than a window ago.
 */
const STALL_WINDOW_STEPS = 2000;
const STALL_SPAN_FRACTION = 1e-10;

/**
 * Steps accepted in a row without meeting the error test because the step
 * could not be cut any further. One is a discontinuity being crossed; twenty
 * is a run that will never meet its tolerances.
 */
const MAX_BELOW_TOLERANCE = 20;

/**
 * How much of a dense iteration matrix is worth holding: `neq` rows of `neq`
 * doubles is 8·neq² bytes, and a quarter of a gigabyte is the most one matrix
 * should ask a browser tab for. That puts the boundary near 5,700 states.
 */
const DENSE_MAX_BYTES = 256 * 1024 * 1024;

/**
 * How this solver fails, for the wrapper in variable-order.js to read off
 * `code` rather than off the words:
 *
 *   'tolerance'  cannot meet the error test without a step below the floor
 *   'nonfinite'  a state, a derivative or the error estimate is not a number
 *   'singular'   the iteration matrix I - h·J cannot be factorised
 *   'stalled'    accepted steps that cover none of the interval
 *   'steps'      more steps than the budget allows
 *   'jacobian'   the Jacobian option is not a shape this solver accepts
 */
export class NdfFailure extends Error {
	constructor(code, message, t) {
		super(message);
		this.name = 'NdfFailure';
		this.code = code;
		this.t = t;
	}
}

/* ------------------------------------------------------------------------ *
 * Small numerics
 * ------------------------------------------------------------------------ */

/** The spacing of doubles at `x`. */
function ulp(x) {
	const a = Math.abs(x);
	if (!(a > 0)) return Number.MIN_VALUE;
	return 2 ** Math.max(Math.floor(Math.log2(a)) - 52, -1074);
}

/** The smallest step that moves the clock at `t`. */
function stepFloor(t) {
	return 16 * ulp(t);
}

/**
 * The Newton backward-difference basis at `s` steps past the table's end:
 * c_0 = 1 and c_j = c_{j-1}·(s + j - 1)/j, so that a polynomial through
 * equally spaced points reads sum_j c_j(s)·∇^j y at s.
 */
function basisAt(s, k, out) {
	out[0] = 1;
	for (let j = 1; j <= k; j++) out[j] = out[j - 1] * ((s + j - 1) / j);
	return out;
}

/** Binomial coefficient, for the small integers this file needs. */
function choose(n, r) {
	let v = 1;
	for (let i = 1; i <= r; i++) v = (v * (n - r + i)) / i;
	return v;
}

/**
 * The linear map that re-expresses backward differences of a degree-k
 * polynomial on another grid.
 *
 * The new grid ends `sEnd` old steps past the table's end and has a spacing
 * of `ratio` old steps. The new m-th difference is the alternating sum of the
 * polynomial's values at the new points, and each value is read through the
 * basis above, so the whole map is a (k+1)×(k+1) matrix with T[m][j] = 0 for
 * j < m -- an m-th difference of a polynomial of lower degree is zero, and it
 * is written as exactly that rather than left to rounding.
 *
 * `sEnd = 0` is a change of step size in place; `sEnd < 0` is what an event
 * inside the step asks for, where the table has to end at the event instead.
 */
function regridMatrix(k, sEnd, ratio) {
	const T = new Array(k + 1);
	const c = new Float64Array(k + 1);
	const values = new Array(k + 1);
	for (let i = 0; i <= k; i++) values[i] = Float64Array.from(basisAt(sEnd - i * ratio, k, c));
	for (let m = 0; m <= k; m++) {
		const row = new Float64Array(k + 1);
		for (let j = m; j <= k; j++) {
			let acc = 0;
			for (let i = 0; i <= m; i++) acc += (i % 2 ? -1 : 1) * choose(m, i) * values[i][j];
			row[j] = acc;
		}
		T[m] = row;
	}
	return T;
}

/* ------------------------------------------------------------------------ *
 * The difference table
 * ------------------------------------------------------------------------ */

/**
 * The backward differences of the solution at the current point: `cols[j]`
 * holds ∇^j y_n for every state, with `cols[0]` the state itself. Columns run
 * to maxOrder + 2, since choosing an order needs the difference one above the
 * order in use, and forming that needs the one above again.
 */
class DifferenceTable {
	constructor(neq, maxOrder) {
		this.neq = neq;
		this.cols = new Array(maxOrder + 3);
		for (let j = 0; j < this.cols.length; j++) this.cols[j] = new Float64Array(neq);
		this._scratch = new Float64Array(neq);
		this._basis = new Float64Array(maxOrder + 3);
	}

	/** The table at the start: the state, and h·y' as its first difference. */
	start(y, hf) {
		this.cols[0].set(y);
		this.cols[1].set(hf);
		for (let j = 2; j < this.cols.length; j++) this.cols[j].fill(0);
	}

	/** The state itself. */
	get y() {
		return this.cols[0];
	}

	/** The order-k predictor, sum_{j=0..k} ∇^j y_n. */
	predict(k, out) {
		const c = this.cols;
		out.set(c[0]);
		for (let j = 1; j <= k; j++) {
			const col = c[j];
			for (let i = 0; i < out.length; i++) out[i] += col[i];
		}
		return out;
	}

	/**
	 * The corrector's history term, sum_{j=1..k} gamma_j ∇^j y_n: what the
	 * order-k formula's left-hand side comes to before the new value is known,
	 * so that sum_{m=1..k} (1/m)∇^m y_{n+1} = history + gamma_k·d, with d the
	 * correction to the predictor.
	 */
	history(k, out) {
		const c = this.cols;
		out.fill(0);
		for (let j = 1; j <= k; j++) {
			const col = c[j];
			const g = GAMMA[j - 1];
			for (let i = 0; i < out.length; i++) out[i] += g * col[i];
		}
		return out;
	}

	/**
	 * Folds an accepted correction in. `d` is ∇^{k+1} y_{n+1} -- the new value
	 * less the predictor -- and every lower difference follows from
	 * ∇^j y_{n+1} = ∇^j y_n + ∇^{j+1} y_{n+1}. The difference two above the
	 * order, which an order increase would be judged by, is formed on the way.
	 */
	advance(k, d) {
		const c = this.cols;
		const top = c[k + 1];
		const above = c[k + 2];
		for (let i = 0; i < d.length; i++) {
			above[i] = d[i] - top[i];
			top[i] = d[i];
		}
		for (let j = k; j >= 0; j--) {
			const col = c[j];
			const next = c[j + 1];
			for (let i = 0; i < col.length; i++) col[i] += next[i];
		}
	}

	/** The same polynomial, on a grid with `ratio` times the spacing. */
	rescale(k, ratio) {
		this.regrid(k, 0, ratio);
	}

	/**
	 * The same polynomial, on a grid ending `sEnd` steps past the current end
	 * with `ratio` times the spacing. Columns above k are not a property of
	 * the polynomial and are left as they are; the caller knows they are stale.
	 */
	regrid(k, sEnd, ratio) {
		const T = regridMatrix(k, sEnd, ratio);
		const c = this.cols;
		const tmp = this._scratch;
		// Row m of the new table reads only old columns m and above, so working
		// upwards from m = 0 overwrites nothing that is still needed.
		for (let m = 0; m <= k; m++) {
			const row = T[m];
			tmp.fill(0);
			for (let j = m; j <= k; j++) {
				const w = row[j];
				if (w === 0) continue;
				const col = c[j];
				for (let i = 0; i < tmp.length; i++) tmp[i] += w * col[i];
			}
			c[m].set(tmp);
		}
	}

	/**
	 * The interpolant: the degree-k polynomial through the last k+1 points,
	 * read `s` steps past the current end (so s in [-1, 0] is the last step).
	 * States the caller names are held at or above zero, as the solution is.
	 */
	valueAt(k, s, out, clampAtZero) {
		const c = this.cols;
		const b = basisAt(s, k, this._basis);
		out.set(c[0]);
		for (let j = 1; j <= k; j++) {
			const w = b[j];
			const col = c[j];
			for (let i = 0; i < out.length; i++) out[i] += w * col[i];
		}
		if (clampAtZero) {
			for (let m = 0; m < clampAtZero.length; m++) {
				const i = clampAtZero[m];
				if (out[i] < 0) out[i] = 0;
			}
		}
		return out;
	}

	/** A state that has just been projected onto zero has no history worth keeping. */
	forget(i) {
		for (let j = 1; j < this.cols.length; j++) this.cols[j][i] = 0;
	}
}

/* ------------------------------------------------------------------------ *
 * The norm the tests are measured in
 * ------------------------------------------------------------------------ */

/**
 * Every size in this solver is measured against the solution: per state,
 * |v_i| over max(|y_i|, |y_i,new|, abstol_i/rtol), and the result compared
 * with rtol. Under norm control the whole vector is weighed at once, by its
 * 2-norm over the larger of the two states' norms.
 *
 * Two of these are kept when the absolute tolerance floats: the error test
 * measures against the floor as it now is, the Newton test against the floor
 * the run began with. See `autoAbstol` below.
 */
class Weighting {
	constructor(neq, threshold, normControl) {
		this.threshold = threshold;
		this.normControl = normControl;
		this.inv = new Float64Array(normControl ? 1 : neq);
	}

	/** Sets the weights for a step from `y` to `ynew`. */
	update(y, ynew) {
		const th = this.threshold;
		const inv = this.inv;
		if (this.normControl) {
			inv[0] = 1 / Math.max(twoNorm(y), twoNorm(ynew), th[0]);
			return;
		}
		for (let i = 0; i < y.length; i++) {
			inv[i] = 1 / Math.max(Math.abs(y[i]), Math.abs(ynew[i]), th[i]);
		}
	}

	/** The weighted size of `v`. NaN if any entry is. */
	of(v) {
		const inv = this.inv;
		if (this.normControl) return twoNorm(v) * inv[0];
		let m = 0;
		for (let i = 0; i < v.length; i++) {
			const a = Math.abs(v[i]) * inv[i];
			if (a !== a) return NaN;
			if (a > m) m = a;
		}
		return m;
	}

	/** The weighted size of `a + b`, without forming it. */
	ofSum(a, b) {
		const inv = this.inv;
		if (this.normControl) {
			let ss = 0;
			for (let i = 0; i < a.length; i++) { const v = a[i] + b[i]; ss += v * v; }
			return Math.sqrt(ss) * inv[0];
		}
		let m = 0;
		for (let i = 0; i < a.length; i++) {
			const v = Math.abs(a[i] + b[i]) * inv[i];
			if (v !== v) return NaN;
			if (v > m) m = v;
		}
		return m;
	}
}

/** Plain Euclidean norm. */
function twoNorm(v) {
	let ss = 0;
	for (let i = 0; i < v.length; i++) ss += v[i] * v[i];
	return Math.sqrt(ss);
}

/* ------------------------------------------------------------------------ *
 * The constraint
 * ------------------------------------------------------------------------ */

/**
 * The right-hand side of the projected system: where a constrained state is
 * at or below zero and its own equation would take it lower, the derivative
 * is held at zero. `<= 0` rather than `< 0`, so a state the projection has
 * just put on zero is held there rather than let below first.
 *
 * Two things are remembered from the last evaluation for the integrator to
 * read: which rows were held, since those rows of the Jacobian are then zero
 * and the iteration matrix has to say so; and the largest derivative held
 * back per constrained state, which is what a step's report of "held at zero"
 * is judged by -- a hold against round-off is not a hold.
 */
function projectedDerivative(f, constrained, neq) {
	const heldRows = new Uint8Array(neq);
	const push = new Float64Array(constrained.length);
	const call = (t, y) => {
		const dy = f(t, y);
		for (let m = 0; m < constrained.length; m++) {
			const i = constrained[m];
			if (y[i] <= 0 && dy[i] < 0) {
				if (-dy[i] > push[m]) push[m] = -dy[i];
				dy[i] = 0;
				heldRows[i] = 1;
			} else {
				heldRows[i] = 0;
			}
		}
		return dy;
	};
	return { call, heldRows, push };
}

/* ------------------------------------------------------------------------ *
 * The Jacobian
 * ------------------------------------------------------------------------ */

/**
 * The `jacobian` option, normalised to one shape:
 *
 *   an array of rows          constant: evaluated once, never stale
 *   a function (t, y)         dense rows, re-evaluated when Newton stalls
 *   { pattern, evaluate }     the pattern's values in CSC -- what
 *                             ../sim/jacobian.js builds -- with an optional
 *                             column colouring `groups` for differencing
 *                             through the pattern, and a `constant` flag
 *   { evaluateDense }         dense rows filled in place
 *
 * `evaluate` may answer null: no usable matrix at this point. The caller
 * differences that one call and asks again next time.
 */
function jacobianSource(option, neq) {
	if (option == null) return null;
	if (typeof option === 'function') {
		return { sparse: false, constant: false, evaluate: (t, y) => option(t, y) };
	}
	if (Array.isArray(option)) {
		if (option.length !== neq) {
			throw new NdfFailure('jacobian',
				`Jacobian is ${option.length}x? but the system has ${neq} equations`);
		}
		return { sparse: false, constant: true, evaluate: () => option };
	}
	if (option.pattern && typeof option.evaluate === 'function') {
		if (option.pattern.n !== neq) {
			throw new NdfFailure('jacobian',
				`Jacobian pattern is ${option.pattern.n}x${option.pattern.n} but the system has ${neq} equations`);
		}
		return {
			sparse: true,
			constant: !!option.constant,
			pattern: option.pattern,
			groups: Array.isArray(option.groups) ? option.groups : null,
			evaluate: (t, y) => option.evaluate(t, y),
		};
	}
	if (typeof option.evaluateDense === 'function') {
		const rows = new Array(neq);
		for (let i = 0; i < neq; i++) rows[i] = new Float64Array(neq);
		return {
			sparse: false,
			constant: !!option.constant,
			evaluate: (t, y) => option.evaluateDense(t, y, rows),
		};
	}
	throw new NdfFailure('jacobian',
		'Jacobian must be a matrix, a function (t, y), or an object with a pattern and an evaluate(t, y)');
}

/**
 * df/dy by forward differences, one column at a time or -- given a sparsity
 * pattern and a colouring of its columns -- one group of columns at a time.
 *
 * A colouring is a set of column groups within which no two columns share a
 * row, so every column of a group can be perturbed in the same evaluation and
 * told apart afterwards by the rows each owns. On a model of sixteen thousand
 * states with a hundred colours that is the difference between a hundred
 * evaluations and sixteen thousand, and between storing the pattern's entries
 * and storing the square.
 *
 * The increment for column j is sqrt(eps) times the larger of |y_j| and the
 * state's own error threshold, rounded to what the addition actually changed
 * so the difference quotient divides by the perturbation that was made.
 */
class Differencer {
	constructor(f, neq, threshold, pattern, groups) {
		this.f = f;
		this.neq = neq;
		this.threshold = threshold;
		this.pattern = pattern;
		this.groups = groups;
		this.ytry = new Float64Array(neq);
		this.delta = new Float64Array(neq);
	}

	_increment(y, j) {
		let del = Math.sqrt(EPS) * Math.max(Math.abs(y[j]), this.threshold[j]);
		if (del === 0) del = Math.sqrt(EPS);
		const moved = (y[j] + del) - y[j];
		return moved === 0 ? del : moved;
	}

	/** Dense rows, one evaluation per column. */
	dense(t, y, fy, rows) {
		const ytry = this.ytry;
		ytry.set(y);
		for (let j = 0; j < this.neq; j++) {
			const del = this._increment(y, j);
			ytry[j] = y[j] + del;
			const fj = this.f(t, ytry);
			ytry[j] = y[j];
			for (let i = 0; i < this.neq; i++) rows[i][j] = (fj[i] - fy[i]) / del;
		}
		return rows;
	}

	/** The pattern's values, one evaluation per colour. */
	sparse(t, y, fy, out) {
		const { colPtr, rowIdx } = this.pattern;
		const ytry = this.ytry;
		const delta = this.delta;
		const groups = this.groups ?? this._singletons();
		for (const group of groups) {
			ytry.set(y);
			for (const j of group) {
				delta[j] = this._increment(y, j);
				ytry[j] = y[j] + delta[j];
			}
			const fg = this.f(t, ytry);
			for (const j of group) {
				const del = delta[j];
				for (let p = colPtr[j]; p < colPtr[j + 1]; p++) {
					const i = rowIdx[p];
					out[p] = (fg[i] - fy[i]) / del;
				}
			}
		}
		return out;
	}

	_singletons() {
		if (!this._single) {
			this._single = new Array(this.neq);
			for (let j = 0; j < this.neq; j++) this._single[j] = [j];
		}
		return this._single;
	}
}

/* ------------------------------------------------------------------------ *
 * The iteration matrix
 * ------------------------------------------------------------------------ */

/**
 * I - a·J, held, factorised and solved: densely through ./linalg.js, or in
 * CSC through ./sparse.js when a pattern was supplied and one real
 * factorisation of each ordering says the fill is worth it. Rows named in
 * `held` are rows of a state the constraint is holding, whose derivative is
 * identically zero: they become rows of the identity.
 */
function iterationMatrix(neq, jac, values) {
	const mustBeSparse = neq * neq * 8 > DENSE_MAX_BYTES;
	if (jac?.sparse) {
		const sparse = sparseIterationMatrix(neq, jac.pattern, values, { mustBeSparse });
		if (sparse) return maskedSparse(sparse, jac.pattern);
	}
	if (mustBeSparse) {
		throw new Error(
			`This model has ${neq} states, and without a sparsity pattern the solver `
			+ `would have to hold the iteration matrix as ${neq} by ${neq} numbers -- `
			+ `${(neq * neq * 8 / 1073741824).toFixed(1)} GB, which no browser tab has. `
			+ 'Give the model an analytic Jacobian (see the Generated code tab for why '
			+ 'it was declined), or run fewer states.',
		);
	}
	return dense(neq, jac?.sparse ? jac.pattern : null);
}

function maskedSparse(inner, pattern) {
	let masked = null;
	return {
		sparse: true,
		fill: inner.fill,
		form(a, values, held) {
			let use = values;
			if (held) {
				if (!masked) masked = new Float64Array(pattern.nnz);
				masked.set(values);
				const { n, colPtr, rowIdx } = pattern;
				for (let j = 0; j < n; j++) {
					for (let p = colPtr[j]; p < colPtr[j + 1]; p++) if (held[rowIdx[p]]) masked[p] = 0;
				}
				use = masked;
			}
			inner.form(a, use);
		},
		solve(rhs) {
			return inner.solve(rhs);
		},
	};
}

function dense(neq, pattern) {
	const W = new Array(neq);
	for (let i = 0; i < neq; i++) W[i] = new Float64Array(neq);
	const lu = new LU(neq);
	return {
		sparse: false,
		fill: null,
		form(a, J, held) {
			if (pattern) {
				for (let i = 0; i < neq; i++) W[i].fill(0);
				const { colPtr, rowIdx } = pattern;
				for (let j = 0; j < neq; j++) {
					for (let p = colPtr[j]; p < colPtr[j + 1]; p++) W[rowIdx[p]][j] = -a * J[p];
				}
			} else {
				for (let i = 0; i < neq; i++) {
					const row = W[i];
					const src = J[i];
					for (let j = 0; j < neq; j++) row[j] = -a * src[j];
				}
			}
			for (let i = 0; i < neq; i++) {
				const row = W[i];
				if (held && held[i]) row.fill(0);
				row[i] += 1;
			}
			// A pivot that is not a number solves to finite nonsense -- x/Inf
			// is 0 -- so the matrix is checked before it is factorised, and
			// the column named.
			for (let i = 0; i < neq; i++) {
				const row = W[i];
				for (let j = 0; j < neq; j++) {
					if (!Number.isFinite(row[j])) {
						throw new Error(
							`The iteration matrix I - h*J has a pivot that is not a number `
							+ `(${row[j]}) at column ${j}: the Jacobian has a non-finite entry there.`,
						);
					}
				}
			}
			lu.factorize(W);
			if (lu.singular) {
				let col = 0;
				while (col < neq - 1 && lu.lu[col][col] !== 0) col++;
				throw new Error(
					`The iteration matrix I - h*J is singular at column ${col}. `
					+ 'A compartment with no way in and no way out will do this.',
				);
			}
		},
		solve(rhs) {
			return lu.solve(rhs);
		},
	};
}

/* ------------------------------------------------------------------------ *
 * The integrator
 * ------------------------------------------------------------------------ */

/**
 * @param {(t: number, y: Float64Array) => ArrayLike<number>} f  the right-hand
 *        side; the array it returns is read at once and may be reused
 * @param {ArrayLike<number>} tspan  the output times; the first and last bound the run
 * @param {ArrayLike<number>} y0
 * @param {object} [options]
 *   rtol, abstol (number or per state), normControl, nonNegative (state
 *   indices), autoAbstol, maxSteps, stagnationTol, hmax, h0, maxOrder, bdf,
 *   jacobian, events ({n, direction, fun(t, y, out)}), onAccepted(t, y),
 *   onOutput(t, y) for every requested time as it is passed, endsOnly (keep
 *   only the first and last rows)
 * @returns {{t: Float64Array, y: Float64Array[], stopped: object|null, stats: object}}
 */
export function ndf(f, tspan, y0, options = {}) {
	const o = {
		rtol: 1e-3,
		abstol: 1e-6,
		normControl: false,
		nonNegative: [],
		autoAbstol: false,
		maxSteps: 1e6,
		stagnationTol: 0,
		stallWindow: STALL_WINDOW_STEPS,
		hmax: -1,
		h0: -1,
		maxOrder: MAX_ORDER,
		bdf: false,
		jacobian: null,
		events: null,
		onAccepted: null,
		onOutput: null,
		endsOnly: false,
		...options,
	};
	const neq = y0.length;
	const npts = tspan.length;
	const t0 = tspan[0];
	const tEnd = tspan[npts - 1];
	const dir = Math.sign(tEnd - t0);
	const span = Math.abs(tEnd - t0);
	if (!(span > 0)) throw new NdfFailure('tolerance', 'Simulation start and end time are equal', t0);

	const maxOrder = Math.max(1, Math.min(MAX_ORDER, Math.round(o.maxOrder)));
	// The corrector's leading coefficient (1 - kappa_k)·gamma_k, and the error
	// constant kappa_k·gamma_k + 1/(k+1) that multiplies ∇^{k+1} y_{n+1};
	// both indexed by order. Every kappa zero is the BDF.
	const leading = new Float64Array(MAX_ORDER + 2);
	const errorConst = new Float64Array(MAX_ORDER + 2);
	for (let k = 1; k <= MAX_ORDER; k++) {
		const kappa = o.bdf ? 0 : KAPPA[k - 1];
		leading[k] = (1 - kappa) * GAMMA[k - 1];
		errorConst[k] = kappa * GAMMA[k - 1] + 1 / (k + 1);
	}

	const rtol = o.rtol;
	const atol = new Float64Array(neq);
	if (typeof o.abstol === 'number') atol.fill(o.abstol);
	else for (let i = 0; i < neq; i++) atol[i] = o.abstol[i];
	const threshold = new Float64Array(neq);
	for (let i = 0; i < neq; i++) threshold[i] = atol[i] / rtol;
	// With a floating absolute tolerance the error test's floor moves and the
	// Newton test's does not: whether a component is accurate enough is fairly
	// judged against its own history, but how well this step's equations have
	// been solved is not, and loosening that leaves a stage half-solved and the
	// error estimate reading a corrector that did not converge.
	const newtonThreshold = o.autoAbstol ? threshold.slice() : threshold;
	const errorWeight = new Weighting(neq, threshold, o.normControl);
	const newtonWeight = o.autoAbstol ? new Weighting(neq, newtonThreshold, o.normControl) : errorWeight;

	const hmax = o.hmax < 0 ? 0.1 * span : Math.min(o.hmax, span);

	// The constraint, and the derivative the solver integrates.
	const constrained = Int32Array.from(o.nonNegative);
	const projected = constrained.length ? projectedDerivative(f, constrained, neq) : null;
	const rhs = projected ? projected.call : f;
	const clampList = constrained.length ? constrained : null;

	// Statistics.
	let nsteps = 0, nfailed = 0, npds = 0, ndecomps = 0, nsolves = 0, nbelowtol = 0, negative = 0;
	const held = constrained.length ? new Int32Array(neq) : null;

	// Output, one row per requested time.
	const tout = [];
	const yout = [];
	const record = (tv, yv) => {
		if (o.endsOnly && tout.length > 1) {
			tout[1] = tv;
			yout[1] = Float64Array.from(yv);
			return;
		}
		tout.push(tv);
		yout.push(Float64Array.from(yv));
	};
	let nextOut = 1;

	// The state lives in the table's first column.
	const table = new DifferenceTable(neq, maxOrder);
	const y = table.y;
	y.set(y0);
	record(t0, y);
	let t = t0;

	const f0 = rhs(t0, y);
	for (let i = 0; i < neq; i++) {
		if (!Number.isFinite(y[i]) || !Number.isFinite(f0[i])) {
			throw new NdfFailure('nonfinite',
				`The state or its derivative is not a number at t=${t0} (state ${i}).`, t0);
		}
	}

	// Events: read at both ends of every step, located inside it when they cross.
	const events = o.events;
	const vL = events ? new Float64Array(events.n) : null;
	const vR = events ? new Float64Array(events.n) : null;
	if (events) events.fun(t0, y, vL);
	let stopped = null;

	// --- the Jacobian, and the matrix built from it ---------------------------
	const jac = jacobianSource(o.jacobian, neq);
	const differ = new Differencer(f, neq, threshold, jac?.sparse ? jac.pattern : null, jac?.groups ?? null);
	let denseRows = null;
	let sparseValues = null;
	let J = null;
	let jacFresh = false;
	const differenced = (fy) => {
		if (jac?.sparse) {
			if (!sparseValues) sparseValues = new Float64Array(jac.pattern.nnz);
			return differ.sparse(t, y, fy, sparseValues);
		}
		if (!denseRows) {
			denseRows = new Array(neq);
			for (let i = 0; i < neq; i++) denseRows[i] = new Float64Array(neq);
		}
		return differ.dense(t, y, fy, denseRows);
	};
	const evaluateJacobian = (fy) => {
		npds++;
		const supplied = jac ? jac.evaluate(t, y) : null;
		J = supplied ?? differenced(fy ?? rhs(t, y));
		jacFresh = true;
	};
	evaluateJacobian(f0);

	const W = iterationMatrix(neq, jac, J);
	// Which rows the constraint holds for the step being taken, and which W
	// was formed with. The mask is read once per step, from the derivative at
	// the point the step starts from: a state hovering on zero can be caught
	// and released again between one Newton evaluation and the next, and a
	// matrix that followed every flicker was re-formed for ever and never
	// took a step. It changes inside a step only when a state W holds is
	// found to have been released -- see the check after the iteration.
	const heldNow = held ? new Uint8Array(neq) : null;
	const heldInW = held ? new Uint8Array(neq) : null;
	const readHeld = () => { if (projected) heldNow.set(projected.heldRows); };
	const heldMoved = () => {
		if (!projected) return false;
		for (let m = 0; m < constrained.length; m++) {
			const i = constrained[m];
			if (heldNow[i] !== heldInW[i]) return true;
		}
		return false;
	};
	/** A state W holds whose derivative the last evaluation did not hold: released inside the step. */
	const releasedInW = () => {
		if (!projected) return false;
		let any = false;
		for (let m = 0; m < constrained.length; m++) {
			const i = constrained[m];
			if (heldInW[i] && !projected.heldRows[i]) { heldNow[i] = 0; any = true; }
		}
		return any;
	};
	let anyHeld = false;
	let hW = 0;
	let kW = 0;
	let rate = -1;
	let k = 1;
	let h = 0; //      the step about to be taken
	let hTable = 0; // the spacing the difference table is expressed in
	const formW = () => {
		if (projected) {
			heldInW.set(heldNow);
			anyHeld = false;
			for (let m = 0; m < constrained.length; m++) if (heldInW[constrained[m]]) { anyHeld = true; break; }
		}
		try {
			W.form(h / leading[k], J, anyHeld ? heldInW : null);
		} catch (e) {
			throw new NdfFailure('singular', `${e.message} (at t=${t})`, t);
		}
		ndecomps++;
		hW = h;
		kW = k;
		rate = -1;
	};

	// --- the first step -------------------------------------------------------
	// Sized from y' and an estimate of y'' out of one explicit Euler trial,
	// for the first-order start: the local error of the step is of the order
	// of h²·y''/2, and a hundredth of the tolerance is asked of it.
	let stepSize;
	if (o.h0 > 0) {
		stepSize = o.h0;
	} else {
		errorWeight.update(y, y);
		const d0 = errorWeight.of(y) / rtol;
		const d1 = errorWeight.of(f0) / rtol;
		let guess = d0 < 1e-5 || d1 < 1e-5 ? 1e-6 : 0.01 * (d0 / d1);
		guess = Math.min(guess, hmax);
		const trial = new Float64Array(neq);
		const df = new Float64Array(neq);
		for (let i = 0; i < neq; i++) trial[i] = y[i] + dir * guess * f0[i];
		const f1 = rhs(t0 + dir * guess, trial);
		for (let i = 0; i < neq; i++) df[i] = f1[i] - f0[i];
		let d2 = errorWeight.of(df) / rtol / guess;
		if (!Number.isFinite(d2)) d2 = 100 * d1;
		const m = Math.max(d1, d2);
		const h1 = m <= 1e-15 ? Math.max(1e-6, guess * 1e-3) : Math.sqrt(0.01 / m);
		stepSize = Math.min(100 * guess, h1);
	}
	stepSize = Math.min(hmax, Math.max(stepFloor(t0), stepSize));
	h = dir * stepSize;

	// Order one to begin with, the table's first difference being h·y'.
	{
		const hf = new Float64Array(neq);
		for (let i = 0; i < neq; i++) hf[i] = h * f0[i];
		table.start(y, hf);
	}
	hTable = h;
	readHeld();
	formW();

	// --- work arrays ------------------------------------------------------------
	const pred = new Float64Array(neq);
	const hist = new Float64Array(neq);
	const d = new Float64Array(neq);
	const ynew = new Float64Array(neq);
	const resid = new Float64Array(neq);
	const interp = new Float64Array(neq);

	let consecutive = 0; // steps taken at this h and k since either changed
	let maskReforms = 0; // re-formations of W for a moved constraint, this step
	let belowTolRun = 0;
	let last = false;
	let tnew = t0;
	let stallStep = 0;
	let stallT = t0;
	let stallH = 0;

	/** The interpolant over the step just taken, for events and output. */
	const denseAt = (tq) => table.valueAt(k, (tq - tnew) / h, interp, clampList);

	/** Cuts (or grows) the step by `factor`, rescaling the table to match. */
	const changeStep = (factor) => {
		const hNew = dir * Math.max(stepFloor(t), Math.abs(h) * factor);
		if (hNew !== hTable) {
			table.rescale(k, hNew / hTable);
			hTable = hNew;
		}
		h = hNew;
		consecutive = 0;
		maskReforms = 0;
	};

	/**
	 * Puts constrained states that `should` be onto the bound: a state within
	 * its absolute tolerance of zero that the step is pushing below it. The
	 * move is smaller than the error test could tell, and it ends two things
	 * no shorter step mends -- a Newton iteration flipping across the kink at
	 * zero on every evaluation, and round-off below zero from a coupling to
	 * states many orders larger. The mask is then read afresh at the start
	 * point, since the state is now on the bound and may be held there.
	 */
	const snapOntoBound = (should) => {
		let snapped = false;
		for (let m = 0; m < constrained.length; m++) {
			const i = constrained[m];
			if (y[i] > 0 && y[i] <= atol[i] && should(i)) {
				y[i] = 0;
				table.forget(i);
				negative++;
				snapped = true;
			}
		}
		if (snapped) {
			rhs(t, y);
			readHeld();
			formW();
		}
		return snapped;
	};

	const floorFailure = (nonfinite) => {
		const hmin = stepFloor(t);
		if (nonfinite) {
			return new NdfFailure('nonfinite',
				`The state or its derivative became non-finite at t=${t}, and no step `
				+ `size above the smallest allowed (${hmin}) gives a number.`, t);
		}
		return new NdfFailure('tolerance',
			`Failure at t=${t}.  Unable to meet integration tolerances without reducing `
			+ `the step size below the smallest value allowed (${hmin}) at time t.`, t);
	};

	for (;;) {
		// --- the step to try ------------------------------------------------
		const hmin = stepFloor(t);
		stepSize = Math.min(hmax, Math.max(hmin, Math.abs(h)));
		last = false;
		let hTry = dir * stepSize;
		if (1.1 * stepSize >= Math.abs(tEnd - t)) {
			hTry = tEnd - t;
			last = true;
		}
		if (hTry !== hTable) {
			table.rescale(k, hTry / hTable);
			hTable = hTry;
			consecutive = 0;
		}
		h = hTry;
		maskReforms = 0;
		// The mask for this step. The last evaluation was at an iterate a
		// correction short of the state the step starts from, and for a state
		// on the bound that correction can be the difference between held and
		// not; where any constrained state sits on the bound the derivative
		// is read there, once, and the mask taken from that.
		if (projected) {
			let onBound = false;
			for (let m = 0; m < constrained.length; m++) if (y[constrained[m]] <= 0) { onBound = true; break; }
			if (onBound) rhs(t, y);
			readHeld();
		}
		if (h !== hW || k !== kW || heldMoved()) formW();

		// --- attempts at it --------------------------------------------------
		let err = 0;
		let firstFailure = true;
		for (;;) {
			tnew = last ? tEnd : t + h;
			table.predict(k, pred);
			table.history(k, hist);
			ynew.set(pred);
			d.fill(0);
			if (projected) projected.push.fill(0);
			errorWeight.update(y, ynew);
			if (newtonWeight !== errorWeight) newtonWeight.update(y, ynew);
			const roundoff = 100 * EPS * newtonWeight.of(ynew);

			// The simplified Newton iteration on the correction d, against the
			// matrix W = I - (h/l_k)·J formed for this step size and order:
			//
			//     W·Δ = (h·f(t_{n+1}, y⁰ + d) - history)/l_k - d
			//
			// The contraction rate measured between two corrections says how
			// much error the last one leaves behind, and a rate remembered from
			// an earlier step at the same W lets a step be taken on one
			// iteration when that estimate is already inside the tolerance.
			let outcome = 'converged';
			let prev = 0;
			let rho = rate;
			const scale = 1 / leading[k];
			for (let iter = 1; iter <= NEWTON_MAX; iter++) {
				const fv = rhs(tnew, ynew);
				for (let i = 0; i < neq; i++) resid[i] = (h * fv[i] - hist[i]) * scale - d[i];
				const delta = W.solve(resid);
				nsolves++;
				const size = newtonWeight.of(delta);
				if (!Number.isFinite(size)) { outcome = 'nonfinite'; break; }
				for (let i = 0; i < neq; i++) {
					d[i] += delta[i];
					ynew[i] = pred[i] + d[i];
				}
				if (size <= roundoff || size <= CONVERGED_FLOOR * rtol) break;
				if (iter === 1) {
					if (rate >= 0 && (rate / (1 - rate)) * size <= NEWTON_TOL * rtol) break;
					prev = size;
					continue;
				}
				const ratio = size / prev;
				if (ratio >= RATE_LIMIT) {
					// A correction that has stopped shrinking. Ordinarily that
					// is an iteration not converging and the step is too long
					// for it. Where the right-hand side cancels so heavily that
					// its residual cannot be evaluated any finer, the correction
					// stalls at the arithmetic's floor instead, and no shorter
					// step mends that; `stagnationTol` lets such a correction
					// be taken on its size alone, at a Jacobian for this point.
					if (o.stagnationTol > 0 && jacFresh && size <= o.stagnationTol * rtol) break;
					outcome = 'slow';
					break;
				}
				rho = Math.max(ratio, RATE_FLOOR);
				const remaining = (rho / (1 - rho)) * size;
				if (remaining <= NEWTON_TOL * rtol) break;
				if (iter === NEWTON_MAX || remaining * rho ** (NEWTON_MAX - iter) > NEWTON_TOL * rtol) {
					outcome = 'slow';
					break;
				}
				prev = size;
			}

			if (outcome !== 'converged') {
				nfailed++;
				// Cheapest remedy first: a state the iteration met the kink
				// with, put onto the bound; then a Jacobian from an earlier
				// point; only then a shorter step.
				if (projected && snapOntoBound((i) => projected.heldRows[i])) continue;
				if (!jacFresh) { evaluateJacobian(null); readHeld(); formW(); continue; }
				if (Math.abs(h) <= hmin) throw floorFailure(outcome === 'nonfinite');
				changeStep(NEWTON_CUT);
				last = false;
				formW();
				continue;
			}
			// A state W held whose equations, at the point the iteration
			// settled on, no longer push it below zero has been released inside
			// the step. Against the holding matrix it could only have stayed
			// put, so the step is taken again with the row restored -- once;
			// a state caught and released within one step is left to the
			// error test.
			if (maskReforms < 1 && releasedInW()) {
				maskReforms++;
				nfailed++;
				formW();
				continue;
			}
			rate = rho;

			// --- the error test ----------------------------------------------
			err = errorConst[k] * errorWeight.of(d);
			if (!Number.isFinite(err)) {
				throw new NdfFailure('nonfinite',
					`The error estimate is not a number at t=${t}: a tolerance or a state weight is NaN.`, t);
			}
			// A constrained state below zero by more than its tolerance is an
			// error like any other, and the step that put it there is cut.
			let forConstraint = false;
			if (projected) {
				let worst = 0;
				for (let m = 0; m < constrained.length; m++) {
					const i = constrained[m];
					if (ynew[i] < 0) {
						const v = -ynew[i] / threshold[i];
						if (v > worst) worst = v;
					}
				}
				if (worst > rtol && worst > err) { err = worst; forConstraint = true; }
			}
			if (err <= rtol) { belowTolRun = 0; break; }

			nfailed++;
			// A state within its tolerance of the bound and pushed past it is
			// put onto the bound and the step tried again from there.
			if (forConstraint && snapOntoBound((i) => ynew[i] < 0)) continue;
			if (Math.abs(h) <= hmin) {
				// Nothing shorter is possible. The step is taken as it is and
				// counted, so the run can say how many of its numbers it could
				// not justify; a run of them is a run that will never finish.
				if (++belowTolRun > MAX_BELOW_TOLERANCE) throw floorFailure(false);
				nbelowtol++;
				break;
			}
			let factor;
			if (firstFailure) {
				firstFailure = false;
				factor = Math.max(0.1, SAFETY * (rtol / err) ** (1 / (k + 1)));
				// Would the order below have allowed a longer step? Its error
				// is read off ∇^k y_{n+1}, which is the table's column k plus
				// the correction. A drop in order never buys a longer step
				// than the one that just failed.
				if (k > 1) {
					const errLower = errorConst[k - 1] * errorWeight.ofSum(table.cols[k], d);
					const lower = Math.max(0.1, SAFETY_LOWER * (rtol / errLower) ** (1 / k));
					if (lower > factor) {
						k--;
						factor = Math.min(1, lower);
					}
				}
			} else {
				factor = 0.5;
			}
			changeStep(factor);
			last = false;
			formW();
		}

		// --- accepted ------------------------------------------------------------
		nsteps++;
		if (nsteps > o.maxSteps) {
			throw new NdfFailure('steps',
				`Exceeded ${o.maxSteps} steps at t=${t}. Nothing this solver can do with `
				+ 'the step size will finish this run.', t);
		}
		if (nsteps - stallStep >= o.stallWindow) {
			const crawling = Math.abs(tnew - stallT) < span * STALL_SPAN_FRACTION;
			const notGrowing = Math.abs(h) <= 2 * stallH;
			if (crawling && notGrowing) {
				throw new NdfFailure('stalled',
					`The solver stopped making progress at t=${tnew}: ${o.stallWindow} `
					+ `accepted steps advanced the clock by less than ${span * STALL_SPAN_FRACTION}, `
					+ 'and the step size is no longer growing.', tnew);
			}
			stallStep = nsteps;
			stallT = tnew;
			stallH = Math.abs(h);
		}

		table.advance(k, d);
		if (projected) {
			for (let m = 0; m < constrained.length; m++) {
				const i = constrained[m];
				if (y[i] < 0) {
					y[i] = 0;
					negative++;
					table.forget(i);
				}
				// Held through this step: the derivative held back would have
				// moved the state by more than its tolerance over the step. A
				// projection alone is not a hold -- the error test bounded it.
				if (projected.push[m] * Math.abs(h) > atol[i]) held[i]++;
			}
		}

		if (events) {
			const hit = locateCrossing(events, t, vL, tnew, y, vR, denseAt, t0);
			if (hit) {
				// The table is re-expressed to end at the crossing, with the
				// step from the start of this one to it, so the state there is
				// its first column and the interpolant below covers [t, tE].
				const tE = hit.t;
				table.regrid(k, (tE - tnew) / h, (tE - t) / h);
				h = tE - t;
				hTable = h;
				tnew = tE;
				consecutive = 0;
				if (clampList) for (const i of clampList) if (y[i] < 0) y[i] = 0;
				vR.set(hit.values);
				stopped = { t: tE, y: Float64Array.from(y), which: hit.which };
				last = true;
			}
			vL.set(vR);
		}

		while (nextOut < npts) {
			const tq = tspan[nextOut];
			if (dir * (tnew - tq) < 0) break;
			const at = tq === tnew ? y : denseAt(tq);
			record(tq, at);
			if (o.onOutput) o.onOutput(tq, at);
			nextOut++;
		}
		if (o.onAccepted) o.onAccepted(tnew, y);

		t = tnew;
		if (last) break;

		if (o.autoAbstol) {
			for (let i = 0; i < neq; i++) {
				const floor = rtol * Math.abs(y[i]);
				if (floor > atol[i]) {
					atol[i] = floor;
					threshold[i] = floor / rtol;
				}
			}
		}

		// --- the next step's size and order ------------------------------------
		// Only after k+1 steps at constant step and order, when the whole table
		// is made of real steps at this spacing and the differences an order
		// change is judged by can be believed.
		consecutive++;
		if (consecutive >= k + 1) {
			const allowed = (e, q, safety) => (
				e > 0 ? Math.min(MAX_GROWTH, safety * (rtol / e) ** (1 / (q + 1))) : MAX_GROWTH
			);
			let bestK = k;
			let best = allowed(err, k, SAFETY);
			if (k > 1) {
				const eLower = errorConst[k - 1] * errorWeight.of(table.cols[k]);
				const g = allowed(eLower, k - 1, SAFETY_LOWER);
				if (g > best) { best = g; bestK = k - 1; }
			}
			if (k < maxOrder) {
				const eHigher = errorConst[k + 1] * errorWeight.of(table.cols[k + 2]);
				const g = allowed(eHigher, k + 1, SAFETY_HIGHER);
				if (g > best) { best = g; bestK = k + 1; }
			}
			if (best > 1) {
				k = bestK;
				h *= best;
				consecutive = 0;
			}
		}
		if (!jac?.constant) jacFresh = false;
	}

	return {
		t: Float64Array.from(tout),
		y: yout,
		stopped,
		stats: {
			nsteps, nfailed, npds, ndecomps, nsolves, nbelowtol, negative, held,
			sparse: W.sparse,
			fill: W.fill,
		},
	};
}
