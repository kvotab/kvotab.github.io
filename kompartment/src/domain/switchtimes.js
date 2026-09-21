/**
 * The times a model says it changes at.
 *
 * A solver chooses its own steps, and it chooses them by looking at how well a
 * polynomial fits what it has just seen. That works because the thing it is
 * fitting is smooth. A source that switches on at year 1,000, a cap that fails
 * at 300, a well drilled at 50 -- each is a place where the model is not
 * smooth, and an adaptive stepper meets one of those in one of two ways:
 *
 *   - it takes a step across it, fits a polynomial through a discontinuity,
 *     and reports a number that is nowhere near right; or
 *   - it rejects that step, halves, rejects again, and bisects its way over
 *     the corner at considerable cost.
 *
 * Neither is necessary, because the model *knows* where the corners are. This
 * is the list, and ../sim/runner.js restarts the solver at each of them -- the
 * same treatment a discrete event gets, for the same reason. AMBER calls them
 * Switch Time parameters and says the same thing rather more bluntly: without
 * them "the solvers may behave poorly, or even give incorrect results (e.g.
 * missing a sharp spike in a source term or transfer rate)".
 *
 * **A lookup table needs no declaration.** Its points are already places the
 * value may turn, and the builder knows them. This is for the times that are
 * written into an equation instead -- the second argument of a `stepUp`, the
 * two ends of a `rampUp`, the year in an `if(time() > 1000, …)`.
 *
 * Written on the simulation as `switch_times`: numbers, or the names of
 * parameters and expressions that come to a number before the run starts.
 * A name is allowed because a switch time is usually *also* a parameter --
 * `t_cap_fails` appears in the equation and in this list, and writing the year
 * twice is how the two come to disagree.
 */

import { constantValue } from './transport.js';
import { qualifiedName } from './systems.js';
import { failureOf, failureTimeKeys } from './wastepackage.js';
import { timingOf } from './disruption.js';

/** What the simulation declares, as written. */
export function declaredSwitchTimes(project) {
	const list = project?.simulation?.switch_times;
	return Array.isArray(list) ? list : [];
}

/**
 * Those times as numbers, in order, inside the run.
 *
 * Anything that cannot be resolved is left out rather than guessed at, and
 * `switchTimeProblems` is what says so -- this is called from the solver, where
 * throwing would turn a mis-typed name into a model that will not run at all.
 *
 * The ends of the run are not breaks: the solver starts and stops there
 * anyway. Duplicates go, because two names for the same year are one corner.
 *
 * @returns {number[]} strictly inside (start, end), ascending
 */
export function switchTimes(project) {
	const sim = project?.simulation ?? {};
	const start = Number(sim.start_time ?? 0);
	const end = Number(sim.end_time ?? 0);
	const out = new Set();
	for (const entry of declaredSwitchTimes(project)) {
		const v = resolveSwitchTime(project, entry);
		if (v == null) continue;
		if (!(v > start) || !(v < end)) continue;
		out.add(v);
	}
	// The times waste packages start or finish failing are corners too, and
	// the block already knows them: a number, or the name of a parameter that
	// comes to one. An equation that does not is no corner, which costs one
	// step's accuracy and nothing else. See ./wastepackage.js.
	for (const w of project?.waste_packages ?? []) {
		for (const key of failureTimeKeys(failureOf(w))) {
			const v = resolveSwitchTime(project, w[key]);
			if (v == null || !(v > start) || !(v < end)) continue;
			out.add(v);
		}
	}
	// A disruptive event at a time is a corner too, and the window of a random
	// one is two: the expected-value rate switches on and off there.
	for (const d of project?.events ?? []) {
		const keys = timingOf(d) === 'at' ? ['at'] : ['from', 'until'];
		for (const key of keys) {
			const v = resolveSwitchTime(project, d[key]);
			if (v == null || !(v > start) || !(v < end)) continue;
			out.add(v);
		}
	}
	return [...out].sort((a, b) => a - b);
}

/** One entry: a number, or the name of something that comes to one. */
export function resolveSwitchTime(project, entry) {
	if (typeof entry === 'number') return Number.isFinite(entry) ? entry : null;
	const name = String(entry ?? '').trim();
	if (!name) return null;
	// A bare number written as text, which is what a form field produces.
	if (/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(name)) return Number(name);
	const found = findByName(project, name);
	if (!found) return null;
	const v = constantValue(project, found.block, found.kind);
	return Number.isFinite(v) ? v : null;
}

/** A parameter or an expression by qualified name. */
function findByName(project, name) {
	for (const [collection, kind] of [['parameters', 'parameter'], ['expressions', 'expression']]) {
		const b = (project?.[collection] ?? []).find((x) => qualifiedName(x) === name);
		if (b) return { block: b, kind };
	}
	return null;
}

/**
 * What is wrong with the list, for the problem strip.
 *
 * Warnings rather than errors throughout: a switch time that cannot be
 * resolved costs accuracy at one corner, and refusing to run the model over it
 * would be a worse answer than running it the way it ran before any of this
 * existed.
 *
 * @returns {Array<{name: string|null, field: string, message: string}>}
 */
export function switchTimeProblems(project) {
	const sim = project?.simulation ?? {};
	const start = Number(sim.start_time ?? 0);
	const end = Number(sim.end_time ?? 0);
	const out = [];
	const seen = new Map();
	for (const entry of declaredSwitchTimes(project)) {
		const written = typeof entry === 'number' ? String(entry) : String(entry ?? '').trim();
		if (!written) continue;
		const v = resolveSwitchTime(project, entry);
		if (v == null) {
			out.push({
				name: null,
				field: 'switch times',
				message: `'${written}' is not a switch time. It has to be a number, or the `
					+ 'name of a parameter or expression that comes to one before the run '
					+ 'starts — a time that depends on the state cannot be known in advance.',
			});
			continue;
		}
		if (!(v > start) || !(v < end)) {
			out.push({
				name: null,
				field: 'switch times',
				message: `The switch time '${written}' is ${v}, which is outside the run `
					+ `(${start} to ${end}). The solver stops at both ends anyway, so this `
					+ 'one does nothing.',
			});
			continue;
		}
		if (seen.has(v)) {
			out.push({
				name: null,
				field: 'switch times',
				message: `'${written}' and '${seen.get(v)}' are both ${v}. One corner is `
					+ 'one restart; the second is ignored.',
			});
			continue;
		}
		seen.set(v, written);
	}
	return out;
}
