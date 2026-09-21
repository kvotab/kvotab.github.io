/**
 * The DifferentialEquations.jl methods, in this tool's solver shape.
 *
 * `src/ode/julia/` is a package of stiff solvers ported from
 * [DifferentialEquations.jl][sciml] -- FBDF, QNDF, Rodas5P, RadauIIA5,
 * KenCarp4, TRBDF2 -- written for the browser and vendored here whole. This
 * file is the adapter: it takes what a solver in this project is handed
 * (`f, tspan, y0, opts`) and gives back what one is expected to return
 * (`{t, y, stopped, stats}`), so the runner, the event loop and the status
 * line treat them exactly as they treat `ndf`.
 *
 * WHY THEY ARE WORTH HAVING. The three solvers this tool wrote itself are one
 * family and one lineage, ported by the same hand, checked against
 * closed-form solutions. What that cannot catch is a mistake shared between
 * this tool and its tests. There were already two answers to that -- the SciPy
 * solvers -- but they are `remote`: they download a Python runtime on first
 * use and do not work offline. These are a second opinion that is always
 * there, and two of them are things this tool has nothing like:
 *
 *   Rodas5P     a Rosenbrock-Wanner method, which has no nonlinear iteration
 *               at all, so there is nothing for a Newton to fail at. The one
 *               to reach for when a model will not converge.
 *   RadauIIA5   fully implicit Runge-Kutta, order 5, L-stable. It suffers the
 *               least order reduction on a stiff problem and is the one to
 *               believe when two others disagree.
 *   FBDF        fixed-leading-coefficient BDF: the same family as ndf but
 *               a different formulation, so it agrees for different reasons.
 *
 * WHAT THE ADAPTER HAS TO DO. Four things do not line up by themselves:
 *
 *   the Jacobian   this tool hands over an *evaluator* that fills a values
 *                  array against a CSC pattern; the package wants a callback
 *                  that fills its own matrix. The patterns are the same shape,
 *                  so sparse is a copy and dense is a scatter -- and a call
 *                  that declines (a non-finite entry at this point) answers
 *                  `false`, which the package's cache reads as "difference
 *                  this one".
 *   the output     this tool asks for a row per point of `tspan`; the package
 *                  calls that `saveat`.
 *   events         both are "a vector of functions whose sign change stops the
 *                  run", and every one of this tool's is terminal.
 *   failure        this tool throws a `SolverError`; the package returns a
 *                  retcode. A run that stopped at an event is not a failure.
 *
 * [sciml]: https://docs.sciml.ai/DiffEqDocs/stable/
 */

import { ODEProblem, solve, Success, Terminated } from './julia/index.js';
import { FBDF } from './julia/solvers/fbdf.js';
import { QNDF } from './julia/solvers/qndf.js';
import { Rodas5P } from './julia/solvers/rosenbrock.js';
import { RadauIIA5 } from './julia/solvers/radau.js';
import { TRBDF2, KenCarp4 } from './julia/solvers/esdirk.js';
import { SolverError } from './dormand-prince.js';

/** The methods offered, by the id a project file stores. */
const ALGORITHMS = Object.assign(Object.create(null), {
	fbdf: FBDF,
	qndf: QNDF,
	rodas5p: Rodas5P,
	radau5: RadauIIA5,
	kencarp4: KenCarp4,
	trbdf2: TRBDF2,
});

/**
 * This tool's analytic Jacobian, as a callback that fills the package's matrix.
 *
 * The two agree on the pattern -- CSC, `colPtr` and `rowIdx` -- so the sparse
 * case is one `set`. Dense is a scatter through the same pattern, which is
 * what the package does with a dense matrix and a pattern anyway.
 *
 * `evaluate` answers null where the matrix would have a non-finite entry, and
 * the answer to that is the same one this tool's own solvers give: difference
 * that one call rather than hand over an infinity. `false` is how the
 * package's cache is told so.
 */
function jacobianFor(jacobian) {
	if (!jacobian) return null;
	const { pattern } = jacobian;
	const { colPtr, rowIdx } = pattern;
	return (t, u, J) => {
		const values = jacobian.evaluate(t, u);
		if (!values) return false;
		if (J.values) { J.values.set(values); return true; }
		// Dense: `data` is column-major, n per column, and only the pattern's
		// entries are written -- so it is cleared first, as the package's own
		// differencing path clears it.
		const n = pattern.n;
		J.data.fill(0);
		for (let j = 0; j < n; j++) {
			for (let k = colPtr[j]; k < colPtr[j + 1]; k++) J.data[j * n + rowIdx[k]] = values[k];
		}
		return true;
	};
}

/**
 * One of the package's methods, wrapped as a solver of this project's.
 *
 * @param {string} id  what the project file stores
 * @returns {(f: Function, tspan: ArrayLike<number>, y0: ArrayLike<number>,
 *   opts: object) => {t: Float64Array, y: Float64Array[], stopped: object|null, stats: object}}
 */
export function julia(id) {
	const algorithm = ALGORITHMS[id];
	if (!algorithm) throw new SolverError(`'${id}' is not one of the ported methods`, 0);

	return function solveIt(f, tspan, y0, opts = {}) {
		const grid = Float64Array.from(tspan);
		const t0 = grid[0];
		const tf = grid[grid.length - 1];
		if (!(tf !== t0)) throw new SolverError('Simulation start and end time are equal', t0);

		// Only the two ends are read back when the points come from
		// `onAccepted`, and asking for the rest is an allocation per step that
		// is then discarded. The same bargain `ndf` makes -- see `endsOnly`.
		const saveat = opts.endsOnly ? Float64Array.from([t0, tf]) : grid;

		const events = opts.events
			? {
				n: opts.events.n,
				// The same `(t, y, out)` this tool's own solvers are handed.
				fun: (t, u, out) => opts.events.fun(t, u, out),
				direction: Array.from(opts.events.direction ?? []),
				// Every discrete event in this tool is terminal: the solver
				// stops at the crossing and the runner starts it again from
				// there, having done whatever the event does. See
				// `solveWithEvents` in ../sim/runner.js.
				terminal: true,
			}
			: null;

		const problem = new ODEProblem(f, y0, [t0, tf], {
			jac: jacobianFor(opts.jacobian),
			jacPattern: opts.jacobian?.pattern ?? null,
			events,
		});

		// Only the options that were actually given. The package merges what it
		// is handed over its own defaults, so a key present and `undefined`
		// *replaces* the default rather than leaving it -- `dtmax: undefined`
		// turned every step size into a NaN and the run never left t0.
		const settings = {
			reltol: opts.rtol ?? 1e-3,
			abstol: opts.abstol ?? 1e-6,
			saveat,
			saveEverystep: false,
			// This tool's own extension, and the reason the idea travelled in
			// this direction: see AutoUpdateAbsTol in ./ndf.js.
			autoAbstol: !!opts.autoUpdateAbsTol,
		};
		if (opts.nonNegative?.some?.(Boolean)) settings.nonNegative = opts.nonNegative;
		if (opts.hmax > 0) settings.dtmax = opts.hmax;
		if (opts.h0 > 0) settings.dt = opts.h0;
		// The rest of the model's solver settings, under the package's names.
		// Only the ones this method reads are ever set on a model -- see
		// SOLVER_OPTIONS in ./solvers.js -- but they are forwarded whatever
		// arrives, because a setting reaching a method that ignores it is
		// harmless and a setting silently dropped here would not be.
		if (opts.maxSteps > 0) settings.maxiters = opts.maxSteps;
		if (opts.maxOrder > 0) settings.maxOrder = opts.maxOrder;
		if (opts.minOrder > 0) settings.minOrder = opts.minOrder;
		if (opts.errorNorm) settings.norm = opts.errorNorm;
		if (opts.newtonKappa > 0) settings.kappa = opts.newtonKappa;
		if (opts.maxJacAge > 0) settings.maxJacAge = opts.maxJacAge;
		if (opts.belowTolRun > 0) settings.belowTolRun = opts.belowTolRun;
		if (opts.matrix) settings.matrix = opts.matrix;
		if (opts.onAccepted) settings.onAccepted = opts.onAccepted;
		// The two things a caller may want to stop for: an abort from the page,
		// and a progress bar that wants the clock.
		if (opts.signal || opts.onProgress) {
			settings.progress = (t) => {
				opts.onProgress?.(Math.min(1, Math.abs(t - t0) / Math.abs(tf - t0)));
				return !opts.signal?.aborted;
			};
		}

		let sol;
		try {
			sol = solve(problem, algorithm(), settings);
		} catch (e) {
			throw new SolverError(e.message, e.t ?? t0);
		}

		// A run that stopped at an event did what it was asked; anything else
		// that is not Success is a failure this tool reports as one.
		if (sol.retcode !== Success && sol.retcode !== Terminated) {
			throw new SolverError(
				`${sol.message || sol.retcode} (${id})`,
				sol.t[sol.t.length - 1] ?? t0,
			);
		}

		// The event that stopped the run, if one did. The package names the one
		// index that fired; this tool's solvers hand back a list, because
		// The bracketing search can find two crossings in one step -- so the one
		// becomes a list of one.
		const fired = sol.events?.length ? sol.events[sol.events.length - 1] : null;
		const stopped = fired
			? {
				t: fired.t,
				y: Float64Array.from(fired.u),
				which: Array.isArray(fired.which) ? fired.which : [fired.which],
			}
			: null;

		const s = sol.stats;
		return {
			t: Float64Array.from(sol.t),
			y: sol.u.map((u) => Float64Array.from(u)),
			stopped,
			stats: {
				nsteps: s.nsteps ?? 0,
				nfailed: s.nreject ?? 0,
				nfevals: s.nf ?? 0,
				// The package counts Jacobians and W-factorisations separately,
				// which is what this tool's `npds` and `ndecomps` mean.
				npds: s.njacs ?? 0,
				ndecomps: s.nw ?? 0,
				nsolves: s.nsolve ?? 0,
				solver: id,
				sparse: !!s.sparse,
				fill: s.fill ?? null,
			},
		};
	};
}
