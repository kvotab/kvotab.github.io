/**
 * What changed between two versions of a model.
 *
 * The results on screen are of the model as it was when it ran, and they stay
 * on screen after an edit, under a list of what has changed since: a solver
 * swapped or a tolerance tightened reads differently from a parameter doubled,
 * and which of them it was decides whether the curves still answer the
 * question somebody was asking of them. This is that list, in the model's own
 * terms -- a setting from one value to another, a block added, deleted,
 * renamed or moved, the fields of a block that changed -- and the editor puts
 * it into words.
 *
 * Every change says whether it can move a number in a run. A comment, a
 * colour or a block's distribution cannot, and neither can the settings of a
 * probabilistic run; the judgement is `NOT_NUMERIC`'s, the one that decides
 * whether an edit needs a re-solve (./fingerprint.js), and like it this errs
 * one way only: what is not known to change no number is said to change one.
 */

import { COLLECTIONS, qualifiedName, baseName } from './systems.js';
import { SINGULAR } from './blocks.js';
import { NOT_NUMERIC, canonical } from './fingerprint.js';

/** Fields of a block that change how it is drawn or described, and no number. */
const BLOCK_LOOKS = new Set([...NOT_NUMERIC, 'line_width', 'dash', 'symbol', 'qa']);

/** Fields of the model itself that describe it, and change no number. */
const MODEL_LOOKS = new Set(['name', 'description', 'author', 'app']);

/**
 * Fields of the model that are the diagram: where the blocks are drawn, what
 * it shows, the shapes on it. Not listed at all -- moving a block is not an
 * edit that leaves results behind, and renaming one moves its place on the
 * diagram to the new name, which is the rename said a second time.
 */
const DIAGRAM = new Set(['layout', 'view', 'shapes']);

/**
 * Simulation settings that change no number in a deterministic run: the ones a
 * probabilistic run, a screening or a sensitivity analysis reads, and the QA
 * switch.
 */
const SETTING_LOOKS = new Set([
	'iterations', 'seed', 'sampling', 'partial', 'varied', 'percentiles', 'correlations',
	'show_mean', 'tornado_low', 'tornado_high', 'gsa', 'categories', 'endpoints', 'qa',
]);

/** A value as text in which the order of an object's keys is no difference. */
const text = (v) => (v === undefined ? 'undefined' : JSON.stringify(v, canonical));

/**
 * Each block of a model by collection and qualified name, with its text --
 * kept for the model the results were run from, which is compared against
 * after every edit and never changes. Keyed on the object, so a snapshot that
 * is replaced takes its index with it.
 */
const indexes = new WeakMap();

function indexOf(raw, keep) {
	if (keep && indexes.has(raw)) return indexes.get(raw);
	const index = new Map();
	for (const kind of COLLECTIONS) {
		const blocks = new Map();
		for (const b of raw?.[kind] ?? []) {
			if (b && typeof b === 'object') blocks.set(qualifiedName(b), { block: b, plain: JSON.stringify(b) });
		}
		index.set(kind, blocks);
	}
	if (keep) indexes.set(raw, index);
	return index;
}

/** Whether two values of `enabled` mean the same: left out is on. */
const sameSwitch = (a, b) => (a !== false) === (b !== false);

/** The fields of a block that differ, each saying whether it can move a number. */
function fieldChanges(a, b) {
	const out = [];
	for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) {
		if (key === 'name' || key === 'system') continue;
		const from = a[key];
		const to = b[key];
		if (key === 'enabled' ? sameSwitch(from, to) : text(from) === text(to)) continue;
		// What a block holds per index differs as a whole; it moves a number
		// unless what differs in it is only what moves none.
		const numeric = key === 'entries'
			? text(withoutLooks(from)) !== text(withoutLooks(to))
			: !BLOCK_LOOKS.has(key);
		out.push({ key, from, to, numeric });
	}
	return out;
}

/** A block's values per index, without the fields that change no number. */
function withoutLooks(entries) {
	if (!Array.isArray(entries)) return entries;
	return entries.map((e) => {
		if (!e || typeof e !== 'object') return e;
		const out = {};
		for (const [k, v] of Object.entries(e)) if (!BLOCK_LOOKS.has(k)) out[k] = v;
		return out;
	});
}

/**
 * A block as it would be under any name and in any sub-system, and whatever
 * it looks like: what is the same block, renamed or moved, when a colour was
 * changed on the way.
 */
function body(b) {
	const out = {};
	for (const [k, v] of Object.entries(b)) {
		if (k !== 'name' && k !== 'system' && !BLOCK_LOOKS.has(k)) out[k] = k === 'entries' ? withoutLooks(v) : v;
	}
	return text(out);
}

/**
 * What changed from `before` to `after`.
 *
 * `before` is read and never written, and is expected to stay as it is: the
 * index of its blocks is kept against it, so that comparing the same snapshot
 * with a model edited again and again walks the snapshot once.
 *
 * @returns {Array<object>} in the order a reader wants them -- the settings,
 *   then the index lists and what else the model holds besides its blocks,
 *   then the blocks, kind by kind. Each is one of
 *   `{where: 'setting', key, from, to, numeric}`,
 *   `{where: 'model', key, from, to, numeric}` (a field of the model other
 *   than its blocks, its settings and its index lists),
 *   `{where: 'list', key, change, numeric}` (an index list, by name), or
 *   `{where: 'block', change, kind, block, to?, fields?, numeric}`, where
 *   `change` is 'added', 'removed', 'renamed', 'moved' or 'changed', `block`
 *   is the qualified name it had, `to` the one it has after a rename or a
 *   move, and `fields` what differs in a changed one.
 */
export function modelChanges(before, after) {
	const out = [];
	if (!before || !after) return out;

	// --- the settings, one by one.
	const was = before.simulation ?? {};
	const now = after.simulation ?? {};
	for (const key of new Set([...Object.keys(was), ...Object.keys(now)])) {
		if (text(was[key]) === text(now[key])) continue;
		out.push({ where: 'setting', key, from: was[key], to: now[key], numeric: !SETTING_LOOKS.has(key) });
	}

	// --- the index lists, by name.
	const lists = (raw) => new Map((raw.index_lists ?? []).map((l) => [l?.name, l]));
	const listsWere = lists(before);
	const listsNow = lists(after);
	for (const [name, list] of listsNow) {
		if (!listsWere.has(name)) out.push({ where: 'list', key: name, change: 'added', numeric: true });
		else if (text(listsWere.get(name)) !== text(list)) out.push({ where: 'list', key: name, change: 'changed', numeric: true });
	}
	for (const name of listsWere.keys()) {
		if (!listsNow.has(name)) out.push({ where: 'list', key: name, change: 'removed', numeric: true });
	}

	// --- whatever else the model holds besides its blocks.
	const skip = new Set([...COLLECTIONS, ...DIAGRAM, 'simulation', 'index_lists']);
	for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
		if (skip.has(key) || text(before[key]) === text(after[key])) continue;
		out.push({ where: 'model', key, from: before[key], to: after[key], numeric: !MODEL_LOOKS.has(key) });
	}

	// --- the blocks, kind by kind.
	const wasIndex = indexOf(before, true);
	const nowIndex = indexOf(after, false);
	for (const kind of COLLECTIONS) {
		const what = SINGULAR[kind] ?? kind;
		const old = wasIndex.get(kind);
		const cur = nowIndex.get(kind);
		const gone = [];
		const added = [];
		for (const [name, { block, plain }] of cur) {
			const prior = old.get(name);
			if (!prior) { added.push(name); continue; }
			// Most blocks are untouched, and their text says so at once;
			// only where it differs is it read field by field, which also
			// lets a difference of key order alone fall away.
			if (prior.plain === plain) continue;
			const fields = fieldChanges(prior.block, block);
			if (fields.length) {
				out.push({
					where: 'block', change: 'changed', kind: what, block: name, fields,
					numeric: fields.some((f) => f.numeric),
				});
			}
		}
		for (const name of old.keys()) if (!cur.has(name)) gone.push(name);

		// A block that left one name and arrived at another, unchanged
		// otherwise: moved into another sub-system, or renamed.
		const byBody = new Map();
		for (const name of gone) {
			const key = body(old.get(name).block);
			if (!byBody.has(key)) byBody.set(key, []);
			byBody.get(key).push(name);
		}
		const paired = new Set();
		for (const name of added) {
			const like = (byBody.get(body(cur.get(name).block)) ?? []).filter((n) => !paired.has(n));
			// Moved: the same block by the same name, in another sub-system.
			let from = like.find((n) => baseName(n) === baseName(name));
			// Renamed: known by its place on the diagram, which a rename takes
			// to the new name. The same contents alone are not enough -- a
			// block deleted and a new one made, both as they come, are alike
			// in everything but the name, and are not one block renamed.
			if (from == null) {
				const at = after.layout?.[name];
				if (at != null) from = like.find((n) => before.layout?.[n] != null && text(before.layout[n]) === text(at));
			}
			if (from == null) continue;
			paired.add(from);
			paired.add(name);
			const moved = baseName(from) === baseName(name);
			out.push({ where: 'block', change: moved ? 'moved' : 'renamed', kind: what, block: from, to: name, numeric: true });
		}
		for (const name of added) {
			if (!paired.has(name)) out.push({ where: 'block', change: 'added', kind: what, block: name, numeric: true });
		}
		for (const name of gone) {
			if (!paired.has(name)) out.push({ where: 'block', change: 'removed', kind: what, block: name, numeric: true });
		}
	}
	return out;
}
