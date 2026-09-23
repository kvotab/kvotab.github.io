/**
 * The variable-order NDF/BDF solver, for stiff systems.
 *
 * This wraps the integrator in ndf.js and presents it in the shape every
 * solver here shares. It is the method the older desktop tools default to for
 * stiff problems, and the one imported models ask for more often than any
 * other, so a model that comes in from a file runs under what it asked for.
 *
 * Everything below is adaptation, not numerics: the derivative convention
 * (`f(t, y, out)` here, `f(t, y)` returning an array there), the progress
 * report and the abort, the list of constrained states, and the translation
 * of the integrator's named failures into the advice a modeller can act on.
 *
 * `opts.jacobian` hands it df/dy instead of leaving it to difference one -- a
 * constant matrix, a function (t, y), or the sparse object ../sim/jacobian.js
 * generates from the model, which also lets the iteration matrix be factorised
 * sparsely. See ./ndf.js.
 */

import { ndf, NdfFailure } from './ndf.js';
import { SolverError, nonFiniteError } from './dormand-prince.js';

/**
 * Same signature as dormandPrince/rosenbrock23 in this directory.
 *
 * @param {(t: number, y: Float64Array, out: Float64Array) => Float64Array} f
 * @param {number[]|Float64Array} tspan  output grid; first and last bound the run
 * @param {Float64Array} y0
 * @param {object} opts  rtol, abstol, hmax, h0, nonNegative, maxOrder, bdf,
 *                       onStep, signal
 * @returns {{ t: Float64Array, y: Float64Array[], stats: object }}
 */
export function variableOrder(f, tspan, y0, opts = {}) {
	const neq = y0.length;
	const t0 = tspan[0];
	const tfinal = tspan[tspan.length - 1];
	if (!(Math.abs(tfinal - t0) > 0)) {
		throw new SolverError('Simulation start and end time are equal', t0);
	}

	const rtol = opts.rtol ?? 1e-3;
	const abstol = typeof opts.abstol === 'number' || opts.abstol == null
		? new Array(neq).fill(opts.abstol ?? 1e-6)
		: Array.from(opts.abstol);

	// Non-negativity is expressed as a list of state indices.
	const nonNegative = [];
	if (opts.nonNegative) {
		for (let i = 0; i < neq; i++) if (opts.nonNegative[i]) nonNegative.push(i);
	}

	let nfevals = 0;
	const span = Math.abs(tfinal - t0) || 1;
	let lastReport = 0;

	/** Bridges the two derivative conventions, and carries progress + abort. */
	const fun = (t, y) => {
		nfevals++;
		// A fresh array each call: the caller's `f` may keep what it is handed
		// (a block that remembers reads its own past derivatives), so one
		// reused buffer would corrupt that history.
		const dy = new Array(neq);
		f(t, y, dy);

		if (opts.onStep && (nfevals & 63) === 0) {
			const progress = Math.min(1, Math.abs(t - t0) / span);
			// Report monotonically: the solver evaluates ahead of and behind
			// the accepted point, so raw t jitters.
			if (progress > lastReport) {
				lastReport = progress;
				// The clock goes with the fraction: on a stiff model the first
				// per cent of the span can be a tenth of the run, and a bar
				// reading 0% with nothing else moving is the one that gets
				// mistaken for a hang.
				if (opts.onStep(progress, nfevals, t) === false) {
					throw new SolverError('Simulation aborted', t);
				}
			}
		}
		return dy;
	};

	let result;
	try {
		result = ndf(fun, tspan, y0, {
			// Discrete events, in the shape every solver here takes them.
			events: opts.events ?? null,
			onAccepted: opts.onAccepted ?? null,
			onOutput: opts.onOutput ?? null,
			rtol,
			abstol,
			nonNegative,
			hmax: opts.hmax ?? -1,
			h0: opts.h0 ?? -1,
			maxOrder: opts.maxOrder ?? 5,
			// The step budget is a setting of the model like the rest.
			...(opts.maxSteps > 0 ? { maxSteps: opts.maxSteps } : {}),
			...(opts.stagnationTol > 0 ? { stagnationTol: opts.stagnationTol } : {}),
			// facsimile.html's three, passed only where the model sets them, so
			// an unset one is the solver's own default rather than an undefined.
			...(opts.errorNorm ? { errorNorm: opts.errorNorm } : {}),
			...(opts.matrix ? { matrix: opts.matrix } : {}),
			...(opts.belowTolRun != null ? { belowTolRun: opts.belowTolRun } : {}),
			jacobian: opts.jacobian ?? null,
			// false selects the NDF formulas, which is what variableOrder does by
			// default; true falls back to plain BDF.
			bdf: opts.bdf ?? false,
			normControl: opts.normControl ?? false,
			autoAbstol: opts.autoUpdateAbsTol ?? false,
			// The caller may be keeping its own points off `onAccepted` and will
			// use only the two ends of what comes back.
			endsOnly: !!opts.endsOnly,
		});
	} catch (e) {
		if (e instanceof SolverError) throw e;
		// What the model's own arithmetic throws -- a far-field setting that
		// cannot mean anything, say -- is the model's to report, as it is
		// under dormandPrince and rosenbrock23; wrapped here it came out with
		// advice about stiffness and tolerances, which is advice about the
		// wrong thing.
		if (!(e instanceof NdfFailure)) throw e;
		const at = e.t ?? t0;
		switch (e.code) {
			case 'stalled':
			case 'steps':
				// A run that cannot advance is a different failure from one
				// that cannot meet its tolerances, and the advice for it is
				// different too: no tolerance and no other solver helps a
				// state being held against a bound, so do not send the reader
				// round that loop.
				throw new SolverError(
					`${e.message} Something is holding a state where it cannot go: most `
					+ `often a compartment kept at zero by "cannot go negative" while its `
					+ `equations push it below. Turn that setting off on the compartment `
					+ `to see what the model really does.`,
					at,
				);
			case 'nonfinite':
				// Say what it is: no tolerance mends a square root of a
				// negative inventory.
				throw nonFiniteError(at);
			case 'singular':
			case 'jacobian':
				throw new SolverError(e.message, at);
			default:
				throw new SolverError(
					`variableOrder failed: ${e.message}. If the model is not stiff, dormandPrince may do `
					+ `better; if it is very stiff, try tightening the tolerances.`,
					at,
				);
		}
	}

	if (!result.t?.length || !result.y?.length) {
		throw new SolverError('the variable-order solver produced no output', t0);
	}

	return {
		t: result.t,
		y: result.y,
		stopped: result.stopped
			? { t: result.stopped.t, y: result.stopped.y, which: result.stopped.which ?? [] }
			: null,
		stats: {
			nsteps: result.stats.nsteps,
			nfailed: result.stats.nfailed,
			nfevals,
			// Partial derivatives, factorisations and back-solves. With an
			// analytic Jacobian npds stops driving nfevals, which is the point
			// of supplying one.
			npds: result.stats.npds,
			ndecomps: result.stats.ndecomps,
			nsolves: result.stats.nsolves,
			nbelowtol: result.stats.nbelowtol,
			sparse: result.stats.sparse ?? false,
			fill: result.stats.fill ?? null,
			// The constraint's account: projections onto zero, and per state
			// the steps it was held through. See ndf.js.
			negative: result.stats.negative ?? 0,
			held: result.stats.held ?? null,
			points: result.t.length,
			// Which of the two formulas ran, since they are one integrator
			// under two names. See SOLVER_INFO in ./solvers.js.
			solver: opts.bdf ? 'bdf' : 'ndf',
		},
	};
}
