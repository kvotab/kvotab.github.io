/**
 * Disruptive events: something happens to the model at an instant.
 *
 * A safety assessment is not only slow processes. A canister is breached by an
 * earthquake; a glacier scrapes the soil off a landscape object; a well is
 * drilled through the repository. GoldSim writes these as *Events* -- timed,
 * or triggered by a Poisson process -- with *consequences* on its Sources and
 * Cells, and the disruptive-event scenarios of an SKB assessment are the same
 * thing in prose. Ecolego's discrete event is a crossing (`first - second`
 * changing sign) that takes snapshots and resets recorders; it does not move
 * mass. This block does.
 *
 * WHEN. Either `at` a time -- an equation that comes to a number before the
 * run, which may be a parameter with a distribution, so a probabilistic run
 * draws it -- or as a Poisson process with a `rate` (occurrences per unit
 * time) between `from` and `until`, the whole run when those are blank.
 *
 * WHAT. A list of actions, each a share of something:
 *
 *   fail    a fraction of the intact packages in a waste-package block fail
 *           at once -- the fraction moves to the exposed waste form and its
 *           instant-release part goes wherever the block's release goes
 *   move    a fraction of a compartment's inventory moves to another
 *           compartment, or out of the model
 *
 * TWO READINGS OF A RANDOM EVENT, and both are right. A deterministic run has
 * no dice: a Poisson event is read in its *expected-value* form, which for a
 * share `f` at rate `λ` is a hazard `f·λ` on what it acts on -- an extra term
 * in the waste block's failure hazard, an extra first-order transfer between
 * the compartments -- and the block's own value is the expected number of
 * occurrences so far, `∫λ dt` over the window. A probabilistic run samples:
 * each realisation draws its own occurrence times from a stream keyed by the
 * block's name and the realisation's number, so a replay reproduces them, and
 * applies the actions as jumps at those times, with the expected-value terms
 * switched off so nothing is counted twice. The block's value is then the
 * number of occurrences so far, a staircase. A timed event is a jump in both.
 *
 * WHAT IT IS NOT. A change to a parameter, or to an equation, at an instant --
 * GoldSim's "triggered" changes to any element. That is a different feature
 * (a parameter that is a step function of time already does most of it), and
 * an event that moved arbitrary quantities would be an event nothing could
 * audit.
 */

import { qualifiedName } from './systems.js';

/** When it happens, as a model spells it. */
export const TIMINGS = ['at', 'poisson'];

export const TIMING_LABEL = {
	at: 'at a time',
	poisson: 'at random, at a rate',
};

export const TIMING_BLURB = {
	at: 'Once, at the time given. An equation that comes to a number before the run '
		+ '— a parameter with a distribution draws it per realisation.',
	poisson: 'As a Poisson process: occurrences at the given rate, independently, between '
		+ 'the two times (the whole run when they are blank). A deterministic run takes '
		+ 'the expected-value form; a probabilistic realisation draws the occurrences.',
};

/** What it does, as a model spells it. */
export const ACTIONS = ['fail', 'move'];

export const ACTION_LABEL = {
	fail: 'fail a share of the packages in',
	move: 'move a share of',
};

export const ACTION_BLURB = {
	fail: 'The share of the still-intact packages that fail at the occurrence: their '
		+ 'inventory moves to the exposed waste form, and the instant-release part goes '
		+ 'wherever the block’s release is delivered.',
	move: 'The share of the compartment’s inventory that moves at the occurrence — to '
		+ 'another compartment, or out of the model.',
};

/** The block-level equations, in the order the panel shows them. */
export const DIS_EQUATION_KEYS = ['at', 'rate', 'from', 'until'];

export const DIS_LABEL = { at: 'At', rate: 'Rate', from: 'From', until: 'Until' };

export const DIS_HELP = {
	at: 'When it happens, in the model’s time unit.',
	rate: 'Occurrences per unit time. 1e-5 a year is one in a hundred thousand years.',
	from: 'No occurrence before this. Blank: from the start of the run.',
	until: 'No occurrence after this. Blank: to the end of the run.',
};

export const DIS_DEFAULTS = {
	timing: 'at',
	at: '',
	rate: '',
	from: '',
	until: '',
	// Whether a probabilistic run draws the occurrences. Off, a random event
	// keeps its expected-value form in every realisation, which is the choice
	// when the question is about the parameters and not about the dice.
	sampled: true,
	actions: [],
};

/** Which of the block-level equations each timing reads. */
export const TIMING_KEYS = { at: ['at'], poisson: ['rate', 'from', 'until'] };

/** The timing, `at` unless the block says a known other. */
export function timingOf(block) {
	return TIMINGS.includes(block?.timing) ? block.timing : 'at';
}

/**
 * The actions as the model holds them: one object each, strings for the
 * equations, unknown kinds kept as written so `disruptionProblems` can name them.
 */
export function normaliseActions(raw) {
	if (!Array.isArray(raw)) return [];
	return raw.filter((a) => a && typeof a === 'object').map((a) => {
		const out = { kind: String(a.kind ?? 'move'), fraction: String(a.fraction ?? '1') };
		if (out.kind === 'fail') out.block = a.block == null ? null : String(a.block);
		else {
			out.from = a.from == null ? null : String(a.from);
			out.to = a.to == null || a.to === '' ? null : String(a.to);
		}
		return out;
	});
}

/**
 * Occurrence times of a Poisson process at a constant rate over a window.
 *
 * Exponential gaps, `-ln(u)/rate`, from the stream given -- which is what
 * makes the draw a function of the seed, the block and the realisation, and
 * so reproducible. Capped, because a rate typed with the wrong exponent would
 * otherwise ask for a million jumps.
 *
 * @param {number} rate  occurrences per unit time
 * @param {number} from  the window
 * @param {number} until
 * @param {() => number} stream  uniforms in (0, 1) -- `streamFor` in ./sample.js
 * @returns {number[]} ascending, strictly inside the window
 */
export function sampleOccurrences(rate, from, until, stream, max = 10000) {
	const out = [];
	if (!(rate > 0) || !(until > from)) return out;
	let t = from;
	for (;;) {
		const u = stream();
		t += -Math.log(u > 0 ? u : Number.MIN_VALUE) / rate;
		if (t >= until) break;
		out.push(t);
		if (out.length >= max) break;
	}
	return out;
}

/** The share as it reads: `0.1` is 10 %, `f_quake` is itself. */
export function shareText(fraction) {
	const v = Number(String(fraction ?? '').trim());
	return Number.isFinite(v) ? `${Math.round(v * 1000) / 10}%` : String(fraction ?? '').trim() || '?';
}

/** One line: when, then what. */
export function describeDisruption(block) {
	const say = (k) => String(block?.[k] ?? '').trim() || '?';
	const when = timingOf(block) === 'at'
		? `at ${say('at')}`
		: `Poisson ${say('rate')}${String(block?.from ?? '').trim() || String(block?.until ?? '').trim()
			? ` in ${String(block.from ?? '').trim() || 'start'} – ${String(block.until ?? '').trim() || 'end'}` : ''}`;
	const what = normaliseActions(block?.actions).map((a) => (a.kind === 'fail'
		? `fails ${shareText(a.fraction)} of ${a.block ?? '?'}`
		: `moves ${shareText(a.fraction)} of ${a.from ?? '?'} ${a.to ? `to ${a.to}` : 'out'}`));
	return what.length ? `${when} · ${what.join(', ')}` : `${when} · does nothing but count`;
}

/**
 * What is wrong with the model's disruptive events, before the run.
 *
 * @param {object} project
 * @returns {Array<{name: string, field: string|null, message: string}>}
 */
export function disruptionProblems(project) {
	const out = [];
	const wastes = new Set((project?.waste_packages ?? []).map((w) => qualifiedName(w)));
	const compartments = new Set((project?.compartments ?? []).map((c) => qualifiedName(c)));
	for (const b of project?.events ?? []) {
		const name = qualifiedName(b);
		const timing = b.timing ?? 'at';
		if (!TIMINGS.includes(timing)) {
			out.push({ name, field: 'timing', message: `'${timing}' is not a way for an event to happen (${TIMINGS.join(', ')}).` });
			continue;
		}
		if (timing === 'at' && !String(b.at ?? '').trim()) {
			out.push({ name, field: 'at', message: 'An event at a time needs the time: a number or an equation.' });
		}
		if (timing === 'poisson' && !String(b.rate ?? '').trim()) {
			out.push({ name, field: 'rate', message: 'A random event needs its rate: occurrences per unit time.' });
		}
		// A blank is not a number -- it is "the start" or "the end".
		const num = (text) => {
			const t = String(text ?? '').trim();
			if (!t) return null;
			const v = Number(t);
			return Number.isFinite(v) ? v : null;
		};
		if (timing === 'poisson' && num(b.rate) != null && num(b.rate) < 0) {
			out.push({ name, field: 'rate', message: 'A rate cannot be negative.' });
		}
		if (timing === 'poisson' && num(b.from) != null && num(b.until) != null && !(num(b.until) > num(b.from))) {
			out.push({ name, field: 'until', message: `The window ends (${num(b.until)}) before it opens (${num(b.from)}).` });
		}
		normaliseActions(b.actions).forEach((a, k) => {
			const field = `actions[${k}]`;
			if (!ACTIONS.includes(a.kind)) {
				out.push({ name, field, message: `'${a.kind}' is not something an event can do (${ACTIONS.join(', ')}).` });
				return;
			}
			if (a.kind === 'fail') {
				if (!a.block) out.push({ name, field, message: 'Which packages fail? Name a waste-package block.' });
				else if (!wastes.has(a.block)) {
					out.push({ name, field, message: `'${a.block}' is not a set of waste packages, so it has no packages to fail.` });
				}
			} else {
				if (!a.from) out.push({ name, field, message: 'Move what? Name a compartment.' });
				else if (!compartments.has(a.from)) {
					out.push({ name, field, message: `'${a.from}' is not a compartment, so there is nothing to move out of it.` });
				}
				if (a.to != null && !compartments.has(a.to)) {
					out.push({ name, field, message: `'${a.to}' is not a compartment, so nothing can be moved into it.` });
				}
				if (a.to != null && a.to === a.from) {
					out.push({ name, field, message: `Moving ${a.from} into itself changes nothing.` });
				}
			}
			const f = num(a.fraction);
			if (f != null && (f < 0 || f > 1)) {
				out.push({ name, field, message: `A share is between 0 and 1; ${f} is not.` });
			}
		});
	}
	return out;
}
