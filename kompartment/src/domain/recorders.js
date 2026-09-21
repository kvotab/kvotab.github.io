/**
 * The five blocks that depend on what has already happened.
 *
 * Everything else in a model is a function of the state as it stands: give it
 * `(t, y)` and it can be worked out. These five cannot --
 *
 *   min/max         the largest (or smallest) its target has been
 *   running mean    the mean of its target over the time it has been recording
 *   snapshot        whatever its target was when an event last fired
 *   delay           what its target was a given time ago
 *   discrete event  not a value so much as an instant: the moment an
 *                   expression crosses another, which the solver stops at
 *
 * -- so they keep a history as the solver goes (`../sim/history.js`), and the
 * discrete event is what drives the other four: a snapshot is taken when one
 * fires, and a min/max or a running mean can be started, stopped and reset by
 * one.
 *
 * This module is the vocabulary: what the kinds are called, what an Ecolego
 * file spells them as, and the one-line descriptions the interface shows. The
 * behaviour is in `../sim/history.js` and the code generator.
 *
 * The min/max, the running mean, the snapshot, the delay and the trigger:
 * every block whose value depends on what has already happened.
 */

/** The block kinds this module covers, in the order the interface offers them. */
export const RECORDER_KINDS = [
	'min_max', 'running_mean', 'snapshot', 'delay', 'trigger',
];

/** The four that keep a history and read it back. */
export const REMEMBERING_KINDS = ['min_max', 'running_mean', 'snapshot', 'delay'];

/**
 * Where each of them lives in a project.
 *
 * Here rather than in the editor and again in the builder, which is how it was
 * written: the same five lines in two files, each of which has to be found and
 * changed when a sixth kind arrives.
 */
export const RECORDER_COLLECTION = {
	min_max: 'min_maxes',
	running_mean: 'running_means',
	snapshot: 'snapshots',
	delay: 'delays',
	trigger: 'triggers',
};

/** What each is called in the interface. */
export const RECORDER_LABEL = {
	min_max: 'Min/max',
	running_mean: 'Running mean',
	snapshot: 'Snapshot',
	delay: 'Delay',
	trigger: 'Trigger',
};

/** A one-line description, for the inspector and the import report. */
export const RECORDER_BLURB = {
	min_max: 'the largest or smallest value its target has taken',
	running_mean: 'the mean of its target over the time it has been recording',
	snapshot: 'its target as it was when a trigger last fired',
	delay: 'its target as it was a given time ago',
	trigger: 'the instant one expression crosses another',
};

/** How an .eco file spells each type, and what this tool calls it. */
/**
 * Lookups keyed by something a project file said.
 *
 * On a null prototype, every one of them. A plain object answers
 * `obj.constructor`, `obj.toString`, `obj.valueOf` and the rest with an
 * inherited member -- truthy, and not what was asked for -- so a whitelist
 * written as a plain object admits exactly the names it exists to refuse. The
 * damage is different in each case (a solver that is `Object`, a reduction
 * whose name prints as `function Object() { [native code] }`) and the cure is
 * the same.
 */
export const KIND_FROM_ECO = Object.assign(Object.create(null), {
	'min-max': 'min_max',
	'running-mean': 'running_mean',
	snapshot: 'snapshot',
	delay: 'delay',
	'discrete-event': 'trigger',
});

// --- min/max ---------------------------------------------------------------

/** Which extreme a min/max block keeps. */
export const EXTREMES = ['max', 'min'];

export function extremeFromEco(name) {
	const s = String(name ?? '').trim().toUpperCase();
	return s === 'MIN' ? 'min' : s === 'MAX' ? 'max' : null;
}

// --- discrete events -------------------------------------------------------

/**
 * Which way an event function must be going through zero to count.
 *
 * The function is `first - second`, and Ecolego names the directions after
 * what the *second* expression does: LEFT is `second - first` approaching zero
 * from below, which is `first - second` on its way down. What reaches the
 * solver is the usual convention -- +1 for a crossing on the way up, -1 on the
 * way down, 0 for either -- which is exactly what the standard convention
 * writes.
 */
export const DIRECTIONS = ['rising', 'falling', 'both'];

export const DIRECTION_SIGN = { rising: 1, falling: -1, both: 0 };

export const DIRECTION_BLURB = {
	rising: 'when the first expression rises past the second',
	falling: 'when the first expression falls past the second',
	both: 'whenever they cross, either way',
};

const DIRECTION_FROM_ECO = {
	RIGHT: 'rising',
	LEFT: 'falling',
	BOTH: 'both',
	'->': 'rising',
	'<-': 'falling',
	'>-<': 'both',
};

export function directionFromEco(name) {
	const s = String(name ?? '').trim();
	return DIRECTION_FROM_ECO[s.toUpperCase()] ?? DIRECTION_FROM_ECO[s] ?? null;
}

/**
 * Which of a block's fields name a discrete event rather than hold a value.
 *
 * Stored as equations whose one token is a reference to the trigger block, so
 * they are read the same way a reference in any other equation is -- and the
 * diagram draws them as influences for the same reason.
 */
export const EVENT_FIELDS = {
	min_max: ['reset_trigger', 'start_trigger', 'stop_trigger'],
	running_mean: ['reset_trigger', 'start_trigger', 'stop_trigger'],
	snapshot: ['trigger'],
	delay: [],
	trigger: [],
};

/** What each event field does when it fires, for `Recorder.fire`. */
export const EVENT_ACTION = {
	reset_trigger: 'reset',
	start_trigger: 'start',
	stop_trigger: 'stop',
	trigger: 'snapshot',
};

/** The fields of each kind that hold an ordinary equation. */
export const EQUATION_FIELDS = {
	min_max: ['target'],
	running_mean: ['target'],
	snapshot: ['target', 'initial'],
	delay: ['target', 'delay'],
	trigger: ['first', 'second'],
};
