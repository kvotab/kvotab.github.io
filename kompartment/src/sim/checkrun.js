/**
 * Is the run resolved? The run set against itself solved more carefully.
 *
 * A run is solved to the tolerances the model gives, and nothing in it says
 * whether they were tight enough for this model: a run made too loosely draws
 * a believable curve that is out -- a peak a few per cent low and a little
 * early -- and looks exactly like a run that is right. The way to know, which
 * the tolerances' own (i) has always given, is to run again with them tighter
 * and see whether what you read off the chart moves. This is that, done for
 * the reader and done for every state at once.
 *
 * **The careful run** is the same model with both tolerances a hundred times
 * tighter -- a compartment's own absolute tolerance too -- the relative one
 * never below `RTOL_FLOOR`, where the formulas stop gaining; the step budget
 * ten times larger where the model sets one; the method and every other
 * setting the run's own. It reports at the run's own output times, whatever
 * the run chose them by, so the two are set against each other point by
 * point; a time the careful run does not have is read at the nearest it does.
 *
 * **What a difference is measured against.** Each state's largest difference
 * over the run, as a share of the most that state reaches in either run --
 * or of the run's absolute tolerance over its relative, where that is more:
 * that is the size at which the solver's own error test passes from relative
 * to absolute, and a state smaller than the run was ever asked to resolve is
 * not judged on its last digits. A run **holds** when no state moved by 0.1 %
 * of its size, **nearly holds** when none moved by 1 %, and otherwise **does
 * not**, and the states that moved most are named, with when and what each
 * run has there.
 */

import { Project } from '../domain/project.js';
import { solverDefault } from '../ode/solvers.js';
import { absoluteTolerance } from './runner.js';
import { stateLabels } from './jaccheck.js';

/** How much tighter the careful run's tolerances are. */
export const CAREFUL = 100;

/** The careful run's relative tolerance goes no lower than this. */
export const RTOL_FLOOR = 1e-12;

/** A run holds below the first, nearly holds below the second. */
export const HOLDS = 1e-3;
export const NEARLY = 1e-2;

/** How many of the states that moved most are named. */
const MOST_NAMED = 6;

/**
 * Tightens a model's tolerances in place, as the careful run has them: both a
 * hundred times tighter, the relative one no lower than `RTOL_FLOOR`; a step
 * budget the model sets ten times as large, the solvers' own defaults (a
 * million or ten million steps) left as they are; and a compartment's own
 * absolute tolerance, and an index's, a hundred times tighter with the rest.
 * What *Run with the careful setting* writes into the model, and the careful
 * run is made of.
 *
 * @returns {{rtol: number, abstol: number, floor: boolean}} `floor` when the
 *   relative tolerance could not be tightened all the way
 */
export function tightenTolerances(model) {
	const sim = model.simulation ?? (model.simulation = {});
	const rtol = Number(sim.rtol);
	const abstol = Number(sim.abstol);
	const tighter = Math.max(RTOL_FLOOR, rtol / CAREFUL);
	sim.rtol = tighter;
	sim.abstol = abstol / CAREFUL;
	const steps = Number(sim.max_steps);
	if (sim.max_steps != null && sim.max_steps !== '' && Number.isFinite(steps) && steps > 0) {
		sim.max_steps = Math.round(steps * 10);
	}
	for (const key of ['compartments', 'waste_packages']) {
		for (const b of model[key] ?? []) {
			const own = Number(b.abstol);
			if (b.abstol != null && b.abstol !== '' && Number.isFinite(own) && own > 0) b.abstol = own / CAREFUL;
			for (const e of b.entries ?? []) {
				const v = Number(e?.abstol);
				if (e?.abstol != null && e.abstol !== '' && Number.isFinite(v) && v > 0) e.abstol = v / CAREFUL;
			}
		}
	}
	return { rtol: tighter, abstol: sim.abstol, floor: tighter > rtol / CAREFUL };
}

/**
 * The careful run's model: the run's own with the tolerances tightened and
 * the output times the run's, whatever it chose them by -- a grid, a list of
 * series, or the solver's steps.
 *
 * @param {object} json      the model the run was made of, as a project file
 * @param {ArrayLike<number>} times  the run's output times
 * @returns {{model: object, rtol: number, abstol: number, floor: boolean}}
 */
export function carefulModel(json, times) {
	const model = structuredClone(json);
	const tightened = tightenTolerances(model);
	model.simulation.spacing = 'series';
	model.simulation.output_times = [{ times: Array.from(times, Number) }];
	return { model, ...tightened };
}

/** The index of the time in `t` nearest `want`, `t` sorted. */
function nearest(t, want) {
	let lo = 0;
	let hi = t.length - 1;
	while (hi - lo > 1) {
		const mid = (lo + hi) >> 1;
		if (t[mid] <= want) lo = mid;
		else hi = mid;
	}
	return Math.abs(t[hi] - want) < Math.abs(t[lo] - want) ? hi : lo;
}

/**
 * The run set against the careful one, state by state.
 *
 * @param {object} held      the run: `{project, system, t, y}`, y a row per time
 * @param {object} careful   the careful run, the same shape
 * @param {object} [o]
 * @param {Float64Array|number} [o.abstol]  the run's absolute tolerance, per
 *   state or one for all (as `absoluteTolerance` gives it)
 * @param {string[]} [o.labels]
 * @returns {object} `{verdict, worst, moved, states, times}`: `worst` the
 *   largest share any state moved; `moved` the states that moved most, each
 *   `{label, state, share, at, held, careful}`
 */
export function compareRuns(held, careful, { abstol = null, labels = null } = {}) {
	const n = held.system.layout.nstate;
	const rtol = Number(held.project.simulation.rtol);
	const atol = abstol ?? absoluteTolerance(held.project, held.system.layout);
	const names = labels ?? stateLabels(held.system.layout);
	const T = held.t.length;
	// Each of the run's times, in the careful run.
	const at = new Int32Array(T);
	let same = careful.t.length === T;
	for (let k = 0; k < T; k++) {
		at[k] = same && careful.t[k] === held.t[k] ? k : nearest(careful.t, held.t[k]);
		if (at[k] !== k) same = false;
	}
	const peak = new Float64Array(n);
	const diff = new Float64Array(n);
	const when = new Int32Array(n);
	for (let k = 0; k < T; k++) {
		const a = held.y[k];
		const b = careful.y[at[k]];
		for (let i = 0; i < n; i++) {
			const x = a[i];
			const y = b[i];
			const big = Math.max(Math.abs(x), Math.abs(y));
			if (big > peak[i]) peak[i] = big;
			const d = Math.abs(x - y);
			// A state that is not a number in one run and is in the other is as
			// far apart as two runs can be.
			if (d > diff[i] || (Number.isNaN(d) && !Number.isNaN(diff[i]))) {
				diff[i] = Number.isNaN(d) ? Infinity : d;
				when[i] = k;
			}
		}
	}
	const moved = [];
	let worst = 0;
	for (let i = 0; i < n; i++) {
		const floor = (typeof atol === 'number' ? atol : atol[i]) / rtol;
		const size = Math.max(peak[i], Number.isFinite(floor) ? floor : 0);
		const share = size > 0 ? diff[i] / size : (diff[i] > 0 ? Infinity : 0);
		if (share > worst) worst = share;
		if (share > 0) {
			moved.push({
				label: names[i] ?? `state ${i}`,
				state: i,
				share,
				at: held.t[when[i]],
				held: held.y[when[i]][i],
				careful: careful.y[at[when[i]]][i],
			});
		}
	}
	moved.sort((p, q) => q.share - p.share);
	return {
		verdict: worst < HOLDS ? 'holds' : worst < NEARLY ? 'nearly' : 'does not',
		worst,
		moved: moved.slice(0, MOST_NAMED),
		states: n,
		times: T,
		sameTimes: same,
	};
}

/**
 * Checks a run: solves the careful run and sets the run against it.
 *
 * @param {object} held     the run, as `run` returns it
 * @param {(model: Project) => object} solve  how the careful run is solved --
 *   `run` with whatever signal and progress the caller has
 * @returns {object} what `compareRuns` gives, with what each run was solved at
 */
export function checkRun(held, solve) {
	if (!held?.y || !held.t || held.y.length !== held.t.length) {
		throw new Error('The run on show does not carry its states here, so it cannot be set against another.');
	}
	const json = held.project.toJSON();
	const { model, rtol, abstol, floor } = carefulModel(json, held.t);
	const started = Date.now();
	const careful = solve(new Project(model));
	const ms = Date.now() - started;
	const report = compareRuns(held, careful);
	const sim = held.project.simulation;
	const id = sim.solver ?? 'ndf';
	return {
		...report,
		run: { rtol: Number(sim.rtol), abstol: Number(sim.abstol), steps: held.stats?.nsteps ?? null },
		careful: {
			rtol, abstol, floor, ms,
			steps: careful.stats?.nsteps ?? null,
			maxSteps: model.simulation.max_steps ?? solverDefault('max_steps', id).value ?? null,
		},
	};
}
