/**
 * Fitting a model to numbers somebody already knows.
 *
 * The question this answers is the other way round from a run: not *what does
 * this model give*, but *what would the inputs have to be for it to give
 * this*. A measured concentration in a lake, a dose an assessment has to
 * match, a release rate calibrated against a field study -- each is one or
 * more endpoints with a value they are supposed to come out at, and a handful
 * of parameters allowed to move between bounds until they do.
 *
 * ---------------------------------------------------------------------------
 * WHAT IS MINIMISED
 *
 * The sum of weighted squared residuals. A residual is how far one endpoint is
 * from its target, and *how that distance is measured is a choice the data
 * makes*:
 *
 *   `absolute`  `got - want`. For a quantity whose scale is the point -- a
 *               mass balance that has to come to zero.
 *   `relative`  `(got - want) / want`. The default, because two endpoints in
 *               different units are otherwise not comparable and the larger
 *               one simply wins.
 *   `log`       `ln(got) - ln(want)`. For a dose or a concentration, which are
 *               argued about in orders of magnitude; being out by a factor of
 *               two is the same error at 1e-9 as at 1e3, and neither of the
 *               other two says so.
 *
 * ---------------------------------------------------------------------------
 * THE ALGORITHMS
 *
 * Every evaluation is a whole integration, so what matters is how few of them
 * a method needs and whether it can be stopped. All three are derivative-free
 * in the model (the solver is a black box), bound-constrained, deterministic
 * given a seed, and report progress after every evaluation.
 *
 *   **Nelder-Mead** -- a simplex of `n+1` points that reflects, expands and
 *   contracts its way downhill. Few evaluations, no derivatives, and the right
 *   first thing to try on two to six parameters. It is a *local* method: it
 *   finds the bottom of the valley it starts in.
 *
 *   **Levenberg-Marquardt** -- the classic for least squares, and this is a
 *   least-squares problem. It builds a Jacobian of the residuals by finite
 *   differences -- `n` extra evaluations an iteration -- and steps between
 *   Gauss-Newton and gradient descent as the fit allows. Fastest of the three
 *   near a solution, and the one to use when a good starting guess is known.
 *
 *   **Differential evolution** -- a population that crosses its members with
 *   the difference between two others. Slowest by far and the only one here
 *   that is *global*: it does not care where it starts and it climbs out of a
 *   local minimum that traps the other two. Use it when the parameters range
 *   over decades and nobody knows the answer to within a factor of ten.
 *
 * References: Nelder & Mead 1965; Marquardt 1963; Storn & Price 1997.
 */

import { rng } from './sample.js';

export class OptimiseError extends Error {
	constructor(message) {
		super(message);
		this.name = 'OptimiseError';
	}
}

/** How a residual is measured. */
export const SCALES = {
	absolute: {
		label: 'absolute',
		blurb: 'got − want. For a quantity whose own scale is the point.',
		of: (got, want) => got - want,
	},
	relative: {
		label: 'relative',
		blurb: 'divided by the target, so endpoints in different units weigh alike.',
		of: (got, want) => (want === 0 ? got : (got - want) / Math.abs(want)),
	},
	log: {
		label: 'logarithmic',
		blurb: 'the ratio, so being out by a factor of two counts the same at 1e−9 '
			+ 'as at 1e3. Needs both to be above zero.',
		of: (got, want) => {
			if (!(got > 0) || !(want > 0)) return NaN;
			return Math.log(got) - Math.log(want);
		},
	},
};

/** How a variable moves between its bounds. */
export const SPACES = {
	linear: {
		label: 'linear',
		to: (v) => v,
		from: (u) => u,
		ok: () => true,
	},
	log: {
		label: 'logarithmic',
		blurb: 'searched in the logarithm, which is how a rate constant known only '
			+ 'to within orders of magnitude has to be searched.',
		to: (v) => Math.log(v),
		from: (u) => Math.exp(u),
		ok: (lo, hi) => lo > 0 && hi > 0,
	},
};

/** The objective, from one set of endpoint readings. */
export function objectiveOf(readings, targets) {
	let sum = 0;
	const residuals = [];
	for (let i = 0; i < targets.length; i++) {
		const t = targets[i];
		const scale = SCALES[t.scale] ?? SCALES.relative;
		const w = Number.isFinite(t.weight) && t.weight > 0 ? t.weight : 1;
		const r = scale.of(readings[i], Number(t.value));
		// A residual that is not a number is a model that did not produce one
		// there. Counted as a large miss rather than as NaN, which would make
		// every comparison false and the search wander.
		const use = Number.isFinite(r) ? Math.sqrt(w) * r : 1e6;
		residuals.push(use);
		sum += use * use;
	}
	return { objective: sum, residuals };
}

/** Into the bounds, whatever was asked for. */
const clamp = (v, lo, hi) => (v < lo ? lo : (v > hi ? hi : v));

function clampAll(x, lower, upper) {
	const out = new Float64Array(x.length);
	for (let i = 0; i < x.length; i++) out[i] = clamp(x[i], lower[i], upper[i]);
	return out;
}

/**
 * Wraps an objective so it is counted, stoppable and never asked twice for
 * the same point.
 */
function budgeted(f, { maxEvals, onStep, signal }) {
	let evals = 0;
	let best = Infinity;
	let bestX = null;
	const seen = new Map();
	const call = (x) => {
		if (signal?.aborted) throw new OptimiseError('stopped');
		if (evals >= maxEvals) throw new OptimiseError('budget');
		// A simplex revisits a vertex it already knows; so does a population
		// that converged. Each of those is a whole integration.
		const key = Array.from(x, (v) => v.toPrecision(12)).join(',');
		const had = seen.get(key);
		if (had !== undefined) return had;
		evals += 1;
		const fx = f(x);
		const use = Number.isFinite(fx) ? fx : Infinity;
		seen.set(key, use);
		if (use < best) { best = use; bestX = Float64Array.from(x); }
		onStep?.({ evals, fx: use, best, x: Float64Array.from(x), bestX });
		return use;
	};
	return {
		call,
		done: (reason) => ({
			x: bestX ? Array.from(bestX) : null,
			fx: best,
			evals,
			reason,
		}),
	};
}

/**
 * Nelder-Mead, with the bounds applied by clamping.
 *
 * The textbook coefficients (reflect 1, expand 2, contract 0.5, shrink 0.5).
 * The initial simplex steps each coordinate by 5% of its range, which for a
 * bounded problem is a size that means something -- the usual "5% of the
 * value" has nothing to say about a variable whose value is zero.
 */
export function nelderMead(f, start, {
	lower, upper, maxEvals = 400, tol = 1e-8, onStep = null, signal = null,
} = {}) {
	const n = start.length;
	if (!n) throw new OptimiseError('Nothing to vary.');
	const budget = budgeted(f, { maxEvals, onStep, signal });
	const at = (x) => budget.call(clampAll(x, lower, upper));

	try {
		// The simplex: the start, then one step along each axis.
		const simplex = [Float64Array.from(start)];
		for (let i = 0; i < n; i++) {
			const x = Float64Array.from(start);
			const span = upper[i] - lower[i];
			const step = span > 0 ? span * 0.05 : Math.abs(x[i]) * 0.05 + 1e-6;
			x[i] = clamp(x[i] + step, lower[i], upper[i]);
			// A vertex that landed on top of another is no vertex: step the
			// other way rather than starting with a degenerate simplex.
			if (x[i] === start[i]) x[i] = clamp(start[i] - step, lower[i], upper[i]);
			simplex.push(x);
		}
		let fs = simplex.map(at);

		for (;;) {
			// Sorted by value: the best first, the worst last.
			const order = fs.map((_, i) => i).sort((a, b) => fs[a] - fs[b]);
			const pts = order.map((i) => simplex[i]);
			const vals = order.map((i) => fs[i]);
			for (let i = 0; i <= n; i++) { simplex[i] = pts[i]; fs[i] = vals[i]; }

			// Converged when the simplex has collapsed onto one value.
			const spread = Math.abs(fs[n] - fs[0])
				/ (Math.abs(fs[0]) + Math.abs(fs[n]) + 1e-300);
			if (spread < tol) return budget.done('converged');

			// The centroid of all but the worst.
			const mid = new Float64Array(n);
			for (let i = 0; i < n; i++) {
				for (let k = 0; k < n; k++) mid[k] += simplex[i][k] / n;
			}
			const along = (t) => {
				const x = new Float64Array(n);
				for (let k = 0; k < n; k++) x[k] = mid[k] + t * (mid[k] - simplex[n][k]);
				return x;
			};

			const xr = along(1);
			const fr = at(xr);
			if (fr < fs[0]) {
				const xe = along(2);
				const fe = at(xe);
				if (fe < fr) { simplex[n] = xe; fs[n] = fe; } else { simplex[n] = xr; fs[n] = fr; }
				continue;
			}
			if (fr < fs[n - 1]) { simplex[n] = xr; fs[n] = fr; continue; }
			// Contract, on whichever side is better.
			const xc = fr < fs[n] ? along(0.5) : along(-0.5);
			const fc = at(xc);
			if (fc < Math.min(fr, fs[n])) { simplex[n] = xc; fs[n] = fc; continue; }
			// Nothing helped: pull everything halfway towards the best.
			for (let i = 1; i <= n; i++) {
				const x = new Float64Array(n);
				for (let k = 0; k < n; k++) x[k] = simplex[0][k] + 0.5 * (simplex[i][k] - simplex[0][k]);
				simplex[i] = clampAll(x, lower, upper);
				fs[i] = at(simplex[i]);
			}
		}
	} catch (e) {
		if (e instanceof OptimiseError) return budget.done(e.message);
		throw e;
	}
}

/**
 * Levenberg-Marquardt on a finite-difference Jacobian.
 *
 * `residuals(x)` gives the vector whose squares are being summed, which is
 * what lets this use the structure the other two throw away: near a solution
 * `JᵀJ` is the curvature, and one step of Gauss-Newton is worth many of a
 * simplex. `lambda` slides between that and gradient descent -- down by ten
 * when a step helps, up by ten when it does not.
 *
 * The step `h` for the difference is relative to the variable's own range, so
 * a parameter of 1e-9 and one of 1e6 are both differenced sensibly.
 */
export function levenbergMarquardt(residuals, start, {
	lower, upper, maxEvals = 400, tol = 1e-10, onStep = null, signal = null,
} = {}) {
	const n = start.length;
	if (!n) throw new OptimiseError('Nothing to vary.');
	let last = null;
	const f = (x) => {
		last = residuals(x);
		let s = 0;
		for (const r of last) s += r * r;
		return Number.isFinite(s) ? s : Infinity;
	};
	const budget = budgeted(f, { maxEvals, onStep, signal });
	const evalAt = (x) => {
		const fx = budget.call(clampAll(x, lower, upper));
		return { fx, r: last ? Float64Array.from(last) : null };
	};

	try {
		let x = clampAll(start, lower, upper);
		let { fx, r } = evalAt(x);
		if (!r) return budget.done('no residuals');
		const m = r.length;
		let lambda = 1e-3;

		for (;;) {
			// The Jacobian, column by column: one extra evaluation each.
			const J = [];
			for (let k = 0; k < n; k++) {
				const span = upper[k] - lower[k];
				const h = (span > 0 ? span : Math.abs(x[k]) + 1) * 1e-6;
				const xp = Float64Array.from(x);
				xp[k] = clamp(x[k] + h, lower[k], upper[k]);
				const step = xp[k] - x[k];
				if (step === 0) { J.push(new Float64Array(m)); continue; }
				const got = evalAt(xp);
				const col = new Float64Array(m);
				for (let i = 0; i < m; i++) col[i] = (got.r[i] - r[i]) / step;
				J.push(col);
			}

			// JᵀJ and Jᵀr, which are `n × n` and `n` however long the
			// residual vector is.
			const A = Array.from({ length: n }, () => new Float64Array(n));
			const g = new Float64Array(n);
			for (let a = 0; a < n; a++) {
				for (let b = a; b < n; b++) {
					let s = 0;
					for (let i = 0; i < m; i++) s += J[a][i] * J[b][i];
					A[a][b] = s; A[b][a] = s;
				}
				let s = 0;
				for (let i = 0; i < m; i++) s += J[a][i] * r[i];
				g[a] = s;
			}

			let stepped = false;
			for (let tries = 0; tries < 12; tries++) {
				const M = A.map((row, a) => {
					const copy = Float64Array.from(row);
					// Marquardt's own scaling: the damping follows the
					// curvature rather than being the same in every direction.
					copy[a] += lambda * (A[a][a] > 0 ? A[a][a] : 1);
					return copy;
				});
				const dx = solve(M, g);
				if (!dx) { lambda *= 10; continue; }
				const trial = new Float64Array(n);
				for (let k = 0; k < n; k++) trial[k] = x[k] - dx[k];
				const got = evalAt(trial);
				if (got.fx < fx) {
					const gain = (fx - got.fx) / (Math.abs(fx) + 1e-300);
					x = clampAll(trial, lower, upper);
					fx = got.fx;
					r = got.r;
					lambda = Math.max(lambda / 10, 1e-12);
					stepped = true;
					if (gain < tol) return budget.done('converged');
					break;
				}
				lambda *= 10;
				if (lambda > 1e12) return budget.done('converged');
			}
			if (!stepped) return budget.done('converged');
		}
	} catch (e) {
		if (e instanceof OptimiseError) return budget.done(e.message);
		throw e;
	}
}

/** Gauss with partial pivoting. Null where the matrix is singular. */
function solve(A, b) {
	const n = b.length;
	const M = A.map((row, i) => {
		const r = new Float64Array(n + 1);
		r.set(row);
		r[n] = b[i];
		return r;
	});
	for (let c = 0; c < n; c++) {
		let p = c;
		for (let i = c + 1; i < n; i++) if (Math.abs(M[i][c]) > Math.abs(M[p][c])) p = i;
		if (!(Math.abs(M[p][c]) > 1e-300)) return null;
		[M[c], M[p]] = [M[p], M[c]];
		for (let i = c + 1; i < n; i++) {
			const k = M[i][c] / M[c][c];
			if (k === 0) continue;
			for (let j = c; j <= n; j++) M[i][j] -= k * M[c][j];
		}
	}
	const x = new Float64Array(n);
	for (let i = n - 1; i >= 0; i--) {
		let s = M[i][n];
		for (let j = i + 1; j < n; j++) s -= M[i][j] * x[j];
		x[i] = s / M[i][i];
	}
	return x;
}

/**
 * Differential evolution, `rand/1/bin`.
 *
 * A population spread over the whole box, each member crossed with another
 * plus the difference between two more. It needs no starting guess and it is
 * the only one of the three that climbs out of a local minimum -- which for a
 * model whose parameters range over decades is not a luxury.
 *
 * The start, where there is one, is put into the population rather than
 * ignored: a guess nobody trusts is still better than a uniform draw.
 */
export function differentialEvolution(f, {
	lower, upper, start = null, popSize = 0, maxEvals = 2000, seed = 1,
	F = 0.7, CR = 0.9, onStep = null, signal = null,
} = {}) {
	const n = lower.length;
	if (!n) throw new OptimiseError('Nothing to vary.');
	// Ten per variable is the usual advice, floored so a one-variable problem
	// still has a population and capped so a ten-variable one still finishes.
	const N = popSize > 3 ? popSize : Math.min(60, Math.max(8, 10 * n));
	const next = rng(seed);
	const budget = budgeted(f, { maxEvals, onStep, signal });

	try {
		const pop = [];
		const fit = [];
		for (let i = 0; i < N; i++) {
			const x = new Float64Array(n);
			if (i === 0 && start) {
				for (let k = 0; k < n; k++) x[k] = clamp(start[k], lower[k], upper[k]);
			} else {
				for (let k = 0; k < n; k++) x[k] = lower[k] + next() * (upper[k] - lower[k]);
			}
			pop.push(x);
			fit.push(budget.call(x));
		}

		for (;;) {
			for (let i = 0; i < N; i++) {
				let a = i; let b = i; let c = i;
				while (a === i) a = Math.floor(next() * N);
				while (b === i || b === a) b = Math.floor(next() * N);
				while (c === i || c === a || c === b) c = Math.floor(next() * N);
				const trial = new Float64Array(n);
				// At least one coordinate always comes from the mutant, or a
				// trial could be its own parent and the population stall.
				const must = Math.floor(next() * n);
				for (let k = 0; k < n; k++) {
					trial[k] = (k === must || next() < CR)
						? clamp(pop[a][k] + F * (pop[b][k] - pop[c][k]), lower[k], upper[k])
						: pop[i][k];
				}
				const ft = budget.call(trial);
				if (ft <= fit[i]) { pop[i] = trial; fit[i] = ft; }
			}
			// Converged when the whole population agrees.
			const lo = Math.min(...fit);
			const hi = Math.max(...fit);
			if (hi - lo <= Math.abs(lo) * 1e-10) return budget.done('converged');
		}
	} catch (e) {
		if (e instanceof OptimiseError) return budget.done(e.message);
		throw e;
	}
}

/** The three, by the key a file stores. */
export const METHODS = {
	nelder: {
		label: 'Nelder–Mead',
		blurb: 'A simplex walking downhill. Few evaluations, no derivatives, and the '
			+ 'right first thing to try on a handful of parameters. Finds the bottom '
			+ 'of the valley it starts in.',
		global: false,
		run: (ctx, opts) => nelderMead(ctx.objective, ctx.start, opts),
	},
	lm: {
		label: 'Levenberg–Marquardt',
		blurb: 'The classic for least squares, and this is one. Costs one extra '
			+ 'evaluation per variable each iteration to build a Jacobian, and is the '
			+ 'fastest of the three once it is near. Wants a decent starting guess.',
		global: false,
		run: (ctx, opts) => levenbergMarquardt(ctx.residuals, ctx.start, opts),
	},
	de: {
		label: 'Differential evolution',
		blurb: 'A population crossed with its own differences. Much the slowest, and '
			+ 'the only one that climbs out of a local minimum — which is what to '
			+ 'reach for when the parameters range over decades.',
		global: true,
		run: (ctx, opts) => differentialEvolution(ctx.objective, { ...opts, start: ctx.start }),
	},
};
