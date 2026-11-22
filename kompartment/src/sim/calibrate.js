/**
 * Running an optimisation against the model.
 *
 * `../domain/optimise.js` knows how to walk downhill and nothing about
 * compartments; this is the other half -- what one evaluation *is*. Which is a
 * whole integration: set the parameters, work the invariants out again, solve,
 * and read the endpoints at the times the targets name.
 *
 * **The system is built once.** Everything a candidate changes is read live --
 * `P` is the array the generated code holds and `initialState()` is a call
 * rather than a value -- which is the same reason a probabilistic run can
 * integrate a thousand times off one build. See `applyPoint` in
 * ./probabilistic.js.
 *
 * **A variable may be searched in its logarithm.** A rate constant known to
 * within orders of magnitude is not usefully stepped by a fixed amount, and a
 * simplex told to step 5% of a range that spans 1e-9 to 1e-3 will spend every
 * evaluation in the top decade. The search happens in whatever space the
 * variable declares; only `P` ever sees the value itself.
 *
 * **An evaluation that will not solve is not an error.** A combination of
 * parameters can be stiffer than the solver can carry, and on a boundary of
 * the feasible region that is normal rather than exceptional. It comes back as
 * an infinite objective, which every method here reads as "not that way".
 */

import { buildSystem } from './builder.js';
import { run } from './runner.js';
import { Project } from '../domain/project.js';
import { parameterSlots, slotLabel } from './localsens.js';
import {
	SPACES, METHODS, objectiveOf, OptimiseError, entryOf,
} from '../domain/optimise.js';
import { precisionOf } from '../domain/precision.js';

/** Where a target is read: a time, the peak, or the end of the run. */
export const WHENS = {
	at: { label: 'at a time' },
	peak: { label: 'at its highest' },
	end: { label: 'at the end of the run' },
};

/** One endpoint's value out of a finished run. */
export function readingOf(results, target) {
	const outputs = results.outputs();
	const o = outputs.find((x) => (x.label ?? '') === target.output);
	if (!o) return NaN;
	const v = results.series(o);
	const t = results.t;
	if (!v?.length) return NaN;
	if (target.when === 'peak') {
		let best = -Infinity;
		for (let i = 0; i < v.length; i++) if (v[i] > best) best = v[i];
		return best;
	}
	if (target.when === 'end') return v[v.length - 1];
	// Nearest output time to the one asked for. Interpolating would invent a
	// value the model never reported, and a target is compared against what
	// the model says rather than against a line drawn through it.
	const want = Number(target.time);
	let at = 0;
	let gap = Infinity;
	for (let i = 0; i < t.length; i++) {
		const d = Math.abs(t[i] - want);
		if (d < gap) { gap = d; at = i; }
	}
	return v[at];
}

/**
 * The variables of a model, as an optimisation can offer them.
 *
 * Every parameter slot, not only the distributed ones: a calibration varies
 * whatever it is told to, and a parameter with no distribution is the usual
 * thing to calibrate.
 */
export function variablesOf(project) {
	const p = project instanceof Project ? project : new Project(project);
	const system = buildSystem(p);
	return parameterSlots(system).map((e) => ({
		key: slotLabel(e),
		name: e.name,
		index: e.index,
		slot: e.slot,
		value: e.value,
		// The slot's own, as the chart labels it: read off the slot rather
		// than off a block the slot never carried, which left every unit
		// empty.
		unit: e.unit ?? '',
	}));
}

/**
 * Solves for the parameter values that put the endpoints where they are asked
 * to be.
 *
 * @param {object|Project} input
 * @param {object} opts
 * @param {Array} opts.targets    `{output, when, time, value, scale, weight}`
 * @param {Array} opts.variables  `{key, lower, upper, space, start}`
 * @param {string} opts.method    a key of `METHODS`
 * @param {number} [opts.maxEvals]
 * @param {(p: object) => void} [opts.onProgress]
 * @param {{aborted: boolean}} [opts.signal]
 */
export function calibrate(input, opts = {}) {
	const started = Date.now();
	const c = setUp(input, opts);
	const { targets, vars } = c;

	const ctx = {
		start: vars.map((v) => v.start),
		objective: (x) => c.evaluate(x).objective,
		residuals: (x) => c.evaluate(x).residuals,
	};

	const method = entryOf(METHODS, opts.method) ?? METHODS.nelder;
	const out = method.run(ctx, {
		lower: vars.map((v) => v.lower),
		upper: vars.map((v) => v.upper),
		maxEvals: Math.max(10, Math.round(opts.maxEvals ?? 300)),
		seed: opts.seed ?? 1,
		signal: opts.signal,
		onProgress: null,
		onStep: opts.onProgress
			? (p) => opts.onProgress({
				evals: p.evals,
				fx: p.fx,
				best: p.best,
				// In the values a reader knows, not in the search space.
				values: p.bestX ? vars.map((v, i) => v.space.from(p.bestX[i])) : null,
			})
			: null,
	});

	// The best point, read once more so the readings reported are the ones
	// that belong to the values reported -- the last evaluation was whatever
	// the method tried last, which is usually not the best.
	let readings = null;
	let objective = out.fx;
	let residuals = null;
	if (out.x) {
		const got = c.evaluate(out.x, true);
		readings = c.readings();
		objective = got.objective;
		residuals = got.residuals;
	}
	const values = out.x ? valuesAt(c, out.x) : [];
	// How well they are known, from the misfit left and how the endpoints
	// move with each value there: after the search, so nothing the search
	// decided depends on it and its count of evaluations is its own. Not for
	// a search that was stopped -- a Stop is a Stop -- nor one the model could
	// not finish at its best point.
	const precision = out.x && opts.precision !== false && out.reason !== 'stopped'
		&& !opts.signal?.aborted && readings.every(Number.isFinite)
		? precisionAround(c, out.x, residuals, values)
		: null;
	c.restore();

	return {
		ok: !!out.x && Number.isFinite(objective),
		// Whether the answer actually *is* one. `ok` only says numbers came
		// back; a search that ran into a bound and stopped comes back with
		// numbers too, and calling that solved would be the report lying about
		// the one thing it is for.
		matched: !!readings && targets.every((t, i) => {
			const want = Number(t.value);
			const got = readings[i];
			if (!Number.isFinite(got) || !Number.isFinite(want)) return false;
			if (want === 0) return Math.abs(got) < 1e-12;
			return Math.abs((got - want) / want) < 0.01;
		}),
		method: opts.method ?? 'nelder',
		reason: out.reason,
		evals: out.evals,
		ms: Date.now() - started,
		objective,
		values,
		precision,
		targets: targets.map((t, i) => ({
			output: t.output,
			want: Number(t.value),
			got: readings ? readings[i] : NaN,
			scale: t.scale ?? 'relative',
		})),
	};
}

/**
 * What every evaluation needs, set up once: the targets, the variables in the
 * space each is searched in, and what one evaluation is -- the parameters
 * set, the invariants worked out again, a run, the endpoints read -- with the
 * way back to what the model held before.
 */
function setUp(input, opts) {
	const project = input instanceof Project ? input : new Project(input);
	const targets = (opts.targets ?? []).filter((t) => t && t.output);
	if (!targets.length) throw new OptimiseError('No endpoint has been given a target value.');
	const wanted = opts.variables ?? [];
	if (!wanted.length) throw new OptimiseError('No parameter has been allowed to vary.');

	const system = buildSystem(project);
	const byLabel = new Map(parameterSlots(system).map((e) => [slotLabel(e), e]));
	const vars = wanted.map((v) => {
		const found = byLabel.get(v.key);
		if (!found) throw new OptimiseError(`'${v.key}' is not a parameter of this model.`);
		// An own entry or the default: see `entryOf`.
		const space = entryOf(SPACES, v.space) ?? SPACES.linear;
		const lo = Number(v.lower);
		const hi = Number(v.upper);
		if (!(hi > lo)) throw new OptimiseError(`'${v.key}' has no range: ${lo} to ${hi}.`);
		// A range that does not end gives a search no size to start from.
		if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
			throw new OptimiseError(`'${v.key}' needs finite bounds: ${lo} to ${hi}.`);
		}
		if (!space.ok(lo, hi)) {
			throw new OptimiseError(`'${v.key}' is searched in the logarithm, so both bounds `
				+ 'have to be above zero.');
		}
		const at0 = Number.isFinite(Number(v.start)) ? Number(v.start) : found.value;
		return {
			key: v.key,
			slot: found.slot,
			space,
			lower: space.to(lo),
			upper: space.to(hi),
			start: space.to(Math.min(hi, Math.max(lo, Number.isFinite(at0) ? at0 : lo))),
		};
	});

	const P = system.parameterValues;
	// What the model held before any of this, so it can be put back: an
	// optimisation must not leave the system somewhere nobody asked for.
	const before = vars.map((v) => P[v.slot]);

	let lastReadings = null;
	// `final` is the report's own reading of the best point, which is not
	// a step of the search and is not stopped: handed the signal, a run with
	// nothing to integrate threw 'Cancelled' once it had finished, and a
	// stopped search reported its best values beside NaN readings.
	const evaluate = (x, final = false) => {
		for (let i = 0; i < vars.length; i++) P[vars[i].slot] = vars[i].space.from(x[i]);
		system.evaluateInvariant();
		try {
			const results = run(project, { system, signal: final ? undefined : opts.signal, onGrid: true });
			lastReadings = targets.map((t) => readingOf(results, t));
		} catch {
			// Not a failure of the optimisation: a corner of the box the
			// solver cannot carry is a fact about the model, and every method
			// here reads an infinite objective as "not that way".
			lastReadings = targets.map(() => NaN);
		}
		return objectiveOf(lastReadings, targets);
	};
	const restore = () => {
		for (let i = 0; i < vars.length; i++) P[vars[i].slot] = before[i];
		system.evaluateInvariant();
	};
	return { project, targets, vars, before, evaluate, restore, readings: () => lastReadings };
}

/** The values at a point of the search, as the model holds them, and which sit on a bound. */
function valuesAt(c, x) {
	return c.vars.map((v, i) => {
		const value = v.space.from(x[i]);
		const lo = v.space.from(v.lower);
		const hi = v.space.from(v.upper);
		// Within a thousandth of a bound is *on* it: the search wanted to
		// go further and was not allowed, which is the one thing about an
		// answer a reader has to be told. A thousandth of the range the
		// search moved over, in the space it moved in: measured against
		// the bound itself, a bound of 0 was reached only at exactly 0.
		const near = (u, bound) => Math.abs(u - bound) <= Math.abs(v.upper - v.lower) * 1e-3;
		return {
			key: v.key,
			was: c.before[i],
			value,
			lower: lo,
			upper: hi,
			pinned: near(x[i], v.lower) ? 'lower' : (near(x[i], v.upper) ? 'upper' : null),
		};
	});
}

/**
 * How far each value is moved to difference the residuals for the precision:
 * a thousandth -- of the value itself where it is searched as it is, of its
 * logarithm's unit where it is searched in the logarithm, which is a tenth of
 * a per cent of the value either way -- and never more than a quarter of the
 * range. Large beside the run's own error (its tolerance, about 1e-6 of each
 * reading), small beside the bend of a model over a per cent.
 */
const PRECISION_STEP = 1e-3;

/**
 * The precision of the values found: the residuals differenced along each
 * value about the answer -- central where both sides are inside the bounds,
 * one-sided against a bound -- and `precisionOf` on what that gives. A value
 * on a bound is held; one the model would not run around is said so.
 */
function precisionAround(c, x, residuals, values) {
	const { vars } = c;
	const columns = [];
	const failed = [];
	let runs = 0;
	const at = (k, u) => {
		const xp = Float64Array.from(x);
		xp[k] = u;
		runs++;
		const got = c.evaluate(xp);
		return c.readings().every(Number.isFinite) ? got.residuals : null;
	};
	for (let k = 0; k < vars.length; k++) {
		const v = vars[k];
		if (values[k].pinned) { columns.push(null); failed.push(null); continue; }
		const span = v.upper - v.lower;
		const own = v.space === SPACES.log ? 1 : Math.abs(x[k]);
		const h = Math.min(span / 4, PRECISION_STEP * (own > 0 ? own : span));
		const up = x[k] + h <= v.upper;
		const down = x[k] - h >= v.lower;
		let col = null;
		if (h > 0 && up && down) {
			const p = at(k, x[k] + h);
			const q = p ? at(k, x[k] - h) : null;
			if (p && q) col = p.map((pi, i) => (pi - q[i]) / (2 * h));
		} else if (h > 0 && (up || down)) {
			const step = up ? h : -h;
			const p = at(k, x[k] + step);
			if (p) col = p.map((pi, i) => (pi - residuals[i]) / step);
		}
		columns.push(col);
		failed.push(col ? null : 'did not run');
	}
	const out = precisionOf({
		residuals,
		columns,
		keys: vars.map((v) => v.key),
		spaces: vars.map((v) => (v.space === SPACES.log ? 'log' : 'linear')),
		values: values.map((v) => v.value),
		pinned: values.map((v) => v.pinned),
		failed,
	});
	out.runs = runs;
	return out;
}

/**
 * The precision of values a calibration found somewhere else -- on an engine
 * that reports the values and not this -- worked out here as a calibration
 * here works it out, at the values reported.
 *
 * @param {object|Project} input
 * @param {object} opts
 * @param {Array} opts.targets     as `calibrate` takes them
 * @param {Array} opts.variables   as `calibrate` takes them
 * @param {Array} opts.values      the result's `values`, in the variables' order
 */
export function calibrationPrecision(input, opts = {}) {
	const c = setUp(input, opts);
	try {
		const values = opts.values ?? [];
		if (values.length !== c.vars.length) {
			throw new OptimiseError('The values do not match the parameters that were varied.');
		}
		const x = Float64Array.from(c.vars, (v, i) => v.space.to(Number(values[i].value)));
		const got = c.evaluate(x, true);
		if (!c.readings().every(Number.isFinite)) return null;
		return precisionAround(c, x, got.residuals, valuesAt(c, x));
	} finally {
		c.restore();
	}
}
