/**
 * Finding a block.
 *
 * A project is a dozen arrays -- compartments here, expressions there -- and
 * the rest of the application does not want to know which array anything is
 * in. It addresses a block by one string, its *qualified name*: `Water` at the
 * root, `NearField.Water` in a sub-system. This is the layer that turns that
 * string back into the block, and it is the bottom of the editor: it knows
 * about collections and names, and nothing at all about editing.
 *
 * Lifted out of edit.js, which had grown to 8,800 lines and 267 exports and
 * was the reason a fingerprint could be written 6,000 lines away from the list
 * of collections it depended on. Everything here was already in that file and
 * is re-exported from it, so nothing that imports `edit.js` had to change.
 */

import { qualifiedName, COLLECTIONS } from './systems.js';

/**
 * The collections a project's blocks live in.
 *
 * One list, kept in ./systems.js, which is the file underneath this one: the
 * two used to be written out separately and the other copy went stale.
 */
export const KINDS = COLLECTIONS;

/** The singular name of each collection: what one of its blocks is. */
export const SINGULAR = {
	compartments: 'compartment',
	expressions: 'expression',
	parameters: 'parameter',
	lookups: 'lookup',
	index_reductions: 'index_reduction',
	block_reductions: 'block_reduction',
	functions: 'function',
	min_maxes: 'min_max',
	running_means: 'running_mean',
	snapshots: 'snapshot',
	delays: 'delay',
	triggers: 'trigger',
	farfields: 'farfield',
	waste_packages: 'waste_package',
	events: 'event',
	transfers: 'transfer',
	inflows: 'inflow',
};

/** The collection each singular kind lives in. */
export const PLURAL = Object.fromEntries(
	Object.entries(SINGULAR).map(([plural, singular]) => [singular, plural]),
);

/**
 * Every block in the project, tagged with the collection it came from.
 *
 * A *copy* of each, which is what makes it safe to hand around and wrong to
 * write to: the tag is added for the reader's benefit and the block itself
 * stays where it lives. `blockIndex` is the one to reach for when the block
 * has to be edited, or when there are many lookups to do.
 */
export function allBlocks(project) {
	const out = [];
	for (const kind of KINDS) {
		for (const b of project[kind] ?? []) out.push({ ...b, kind: SINGULAR[kind], _collection: kind });
	}
	return out;
}

/**
 * Every block by its qualified name, in one pass.
 *
 * `findBlock` is a linear scan, and a linear scan is the right shape for the
 * ninety-odd places that ask for one block and then get on with something
 * else. It is the wrong shape for the handful that ask once per *reference*:
 * the unit check resolves every identifier in every equation, which on a
 * 4,278-block model is around 168,000 lookups, each walking every collection
 * and building a qualified name for every block it passes -- three quarters of
 * a billion string concatenations for one pass over the model, and that pass
 * happens on every edit.
 *
 * Measured on that model: 48.8 µs a lookup against 0.1 µs through this, and
 * 1 ms to build. Handed in rather than cached, for the reason `known` is: the
 * project is edited in place and there is no revision to invalidate a cache
 * against, so the only safe cache is one whose lifetime you can see -- a
 * single scan, which cannot edit the model it is scanning.
 *
 * @returns {Map<string, {block: object, collection: string, kind: string}>}
 */
export function blockIndex(project) {
	const map = new Map();
	for (const kind of KINDS) {
		for (const b of project[kind] ?? []) {
			const q = qualifiedName(b);
			// First wins, as the scan did: two blocks may not share a name,
			// but a model mid-edit can be in that state for a keystroke.
			if (!map.has(q)) map.set(q, { block: b, collection: kind, kind: SINGULAR[kind] });
		}
	}
	return map;
}

/**
 * A block by its qualified name -- `Water` at the root, `NearField.Water` in a
 * sub-system. That one string is how the whole editor addresses a block, which
 * is why so little outside this file had to learn about the hierarchy.
 *
 * @param {Map} [index] from `blockIndex`, for a caller doing this in a loop.
 */
export function findBlock(project, name, index = null) {
	if (index) return index.get(name) ?? null;
	for (const kind of KINDS) {
		const b = (project[kind] ?? []).find((x) => qualifiedName(x) === name);
		if (b) return { block: b, collection: kind, kind: SINGULAR[kind] };
	}
	return null;
}

/** Every block's qualified name. */
export function blockNames(project) {
	const out = [];
	for (const kind of KINDS) for (const b of project[kind] ?? []) out.push(qualifiedName(b));
	return out;
}

/** Whether a name is already a block's. */
export function nameTaken(project, name) {
	return KINDS.some((k) => (project[k] ?? []).some((b) => qualifiedName(b) === name));
}

/**
 * A predicate over every block's name, for `resolveReference`.
 *
 * Built once and handed to a whole scan rather than per block: built per
 * block it was the model walked once for each of them, and a second of every
 * keystroke on a large one.
 */
export function knownNames(project) {
	const set = new Set(blockNames(project));
	return (n) => set.has(n);
}

/**
 * A user-defined function's own parameters, which are not block names.
 *
 * `f(x, y) = x * y` names `x` and `y`, and neither is a reference to anything
 * in the model -- so every walk that resolves identifiers has to be told to
 * skip them. Here because it is part of deciding what a name means, which is
 * what this file is.
 */
export function functionLocals(block, key) {
	return block?.kind === 'function' || (key === 'equation' && Array.isArray(block?.parameters))
		? new Set((block.parameters ?? []).map(String))
		: null;
}
