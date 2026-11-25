/**
 * Groups: a way of sorting the blocks of one sub-system into named sets.
 *
 * A sub-system is a namespace. Moving a block into one changes its id --
 * `Water` becomes `NearField.Water` -- and every equation that names it is
 * rewritten. A group is the other thing Ecolego has for the same job, without
 * that: its blocks keep the id they had, because a group declares no namespace
 * and the id rule skips it (see "Sub-systems" in INTERNALS.md). So a group is
 * organisation and nothing else. No equation can name one, no run reads one,
 * and putting a block into a group or taking it out changes no number.
 *
 * What a model file says:
 *
 *   - `groups`, a list of declarations, each `{name, system?, group?}`: the
 *     group's name, the sub-system it belongs to (absent at the top level) and
 *     the group it is inside, if any -- a group of the same sub-system. Beside
 *     those it keeps how it is drawn: `x`, `y`, `w` and `h` for its area on the
 *     diagram, `collapsed` when it is drawn folded up into one node, `matrix`
 *     for its place on the transfer grid's diagonal, `color` for its outline.
 *   - `group` on a block: the name of a group of the block's own sub-system.
 *   - `group` in a sub-system's layout entry, for a sub-system that sits in a
 *     group of the sub-system around it. A sub-system has no object of its own
 *     to carry it -- `systems` is a list of paths -- and its layout entry is
 *     the one place that already follows it through every rename and move, in
 *     the editor and in the Python and Julia packages alike.
 *
 * A group's name is unique among the groups of its sub-system, and is all a
 * member says. Elsewhere it is known by an id, `group:` and its qualified name
 * (`group:Biosphere.Wells`), which cannot be a block's or a sub-system's: the
 * colon is not in any name. That id is what the diagram, the transfer grid and
 * a selection hold.
 *
 * Read leniently, the way a layout is: a member naming a group its sub-system
 * does not have is in no group, a group naming a parent that is not there is at
 * the top of its sub-system, and a loop of parents is cut where it closes. A
 * hand-edited file therefore draws as something, and nothing here can refuse a
 * model or move a number.
 */

import {
	qualify, parentOf, baseName, parts, systemPaths, systemOf, SEPARATOR, COLLECTIONS,
} from './systems.js';
import { NAME_RE } from './names.js';

/**
 * How far a group's area reaches past what it holds on the diagram, and the
 * band along its top that its name is written in. The layout leaves this much
 * room round a group's members and the diagram draws exactly that, so the two
 * are one pair of numbers.
 */
export const GROUP_PAD = 18;
export const GROUP_HEAD = 30;

/** What starts every group's id. Not a character a name can hold. */
export const GROUP_PREFIX = 'group:';

/** The id of the group called `name` in `system` (`''`: the top level). */
export function groupId(system, name) {
	return GROUP_PREFIX + qualify(system ?? '', name);
}

/** Whether a string is a group's id rather than a block's or a sub-system's name. */
export function isGroupId(id) {
	return typeof id === 'string' && id.length > GROUP_PREFIX.length && id.startsWith(GROUP_PREFIX);
}

/** A group's id taken apart: its sub-system and its own name. Null for anything else. */
export function splitGroupId(id) {
	if (!isGroupId(id)) return null;
	const q = id.slice(GROUP_PREFIX.length);
	return { system: parentOf(q), name: baseName(q) };
}

/** The name a group's id ends in, or the id itself when it is not one. */
export function groupName(id) {
	return splitGroupId(id)?.name ?? String(id ?? '');
}

/** The sub-system whose canvas a group is drawn on. */
export function groupSystem(id) {
	return splitGroupId(id)?.system ?? '';
}

/**
 * The declarations as the file has them, the malformed ones left out. Live
 * objects: what the editor changes, it changes here.
 */
export function groupList(project) {
	const list = project?.groups;
	if (!Array.isArray(list)) return [];
	return list.filter((g) => g && typeof g === 'object' && !Array.isArray(g)
		&& typeof g.name === 'string' && NAME_RE.test(g.name)
		&& (g.system == null || typeof g.system === 'string'));
}

/**
 * Every group of the model, by id: `{id, name, system, parent, decl}`, with
 * `parent` the id of the group it is in or null, and `decl` the declaration
 * itself.
 *
 * Worked out once by whoever is about to ask many questions -- a render asks
 * one per block -- and handed to the questions below. The first declaration of
 * an id wins; a group of a sub-system the model does not have is not one.
 */
export function groupIndex(project) {
	const index = new Map();
	const declared = groupList(project);
	if (!declared.length) return index;
	const paths = new Set(['', ...systemPaths(project)]);
	for (const g of declared) {
		const system = g.system ?? '';
		if (!paths.has(system)) continue;
		const id = groupId(system, g.name);
		if (index.has(id)) continue;
		index.set(id, { id, name: g.name, system, parent: null, decl: g });
	}
	for (const info of index.values()) {
		const p = info.decl.group;
		if (typeof p !== 'string' || !p) continue;
		const pid = groupId(info.system, p);
		if (pid !== info.id && index.has(pid)) info.parent = pid;
	}
	// A loop of parents -- only a hand-edited file can hold one -- is cut
	// where the walk up from a group first meets itself again, so that every
	// chain ends and the file's own order decides where.
	for (const info of index.values()) {
		const seen = new Set([info.id]);
		let at = info;
		while (at.parent) {
			if (seen.has(at.parent)) { at.parent = null; break; }
			seen.add(at.parent);
			at = index.get(at.parent);
		}
	}
	return index;
}

/** A layout entry, when the map really holds one (see `ownEntry` in ./edit.js). */
function layoutEntry(project, key) {
	const layout = project?.layout;
	if (!layout || !Object.prototype.hasOwnProperty.call(layout, key)) return null;
	const entry = layout[key];
	return entry && typeof entry === 'object' ? entry : null;
}

/** The group a block is in, as an id, or null. */
export function groupOfBlock(block, index) {
	const name = block?.group;
	if (typeof name !== 'string' || !name) return null;
	const id = groupId(systemOf(block), name);
	return index.has(id) ? id : null;
}

/** The group a sub-system sits in -- one of its parent's -- as an id, or null. */
export function groupOfSystem(project, path, index) {
	if (!path) return null;
	const name = layoutEntry(project, path)?.group;
	if (typeof name !== 'string' || !name) return null;
	const id = groupId(parentOf(path), name);
	return index.has(id) ? id : null;
}

/** The groups `id` is in, outermost first, ending with `id` itself. */
export function groupChain(index, id) {
	const out = [];
	for (let at = id; at && index.has(at); at = index.get(at).parent) out.unshift(at);
	return out;
}

/** Whether group `id` is `outer` or lies inside it, however deep. */
export function groupWithin(index, id, outer) {
	for (let at = id; at; at = index.get(at)?.parent ?? null) {
		if (at === outer) return true;
	}
	return false;
}

/**
 * Everything a block or a sub-system is inside, outermost first: every
 * sub-system on the way down to it, and at each of those levels the groups it
 * puts the next step in. What the transfer grid folds a row into, and what
 * a reader would say if asked where the thing is.
 *
 * @param {object} project
 * @param {string} name a block's qualified name, or a sub-system's path
 * @param {Map} index from `groupIndex`
 * @param {{block?: object|null}} [opts] the block, when `name` is one
 */
export function containersOf(project, name, index, { block = null } = {}) {
	const out = [];
	const system = block ? systemOf(block) : parentOf(name);
	const steps = parts(system);
	for (let i = 0; i <= steps.length; i++) {
		// What stands on the canvas of steps[0..i): the next sub-system down,
		// or, at the last level, the thing itself.
		const own = i < steps.length ? steps.slice(0, i + 1).join(SEPARATOR) : null;
		const grouped = own
			? groupOfSystem(project, own, index)
			: (block ? groupOfBlock(block, index) : groupOfSystem(project, name, index));
		if (grouped) out.push(...groupChain(index, grouped));
		if (own) out.push(own);
	}
	return out;
}

/** The groups of one sub-system (`''`: the top level), in the file's order. */
export function groupsOn(index, system) {
	const here = system ?? '';
	return [...index.values()].filter((g) => g.system === here);
}

/**
 * The members of a group: the blocks, sub-systems and groups directly in it,
 * or with `deep` everything inside it however many groups down. Blocks and
 * sub-systems are by name and path, groups by id.
 */
export function groupMembers(project, id, index, { deep = false } = {}) {
	const out = { blocks: [], systems: [], groups: [] };
	const info = index.get(id);
	if (!info) return out;
	const inside = (gid) => (deep ? groupWithin(index, gid, id) : gid === id);
	for (const g of index.values()) {
		if (g.id !== id && g.parent && inside(g.parent)) out.groups.push(g.id);
	}
	for (const kind of COLLECTIONS) {
		for (const b of project?.[kind] ?? []) {
			if (!b || systemOf(b) !== info.system) continue;
			const gid = groupOfBlock(b, index);
			if (gid && inside(gid)) out.blocks.push(qualify(info.system, b.name));
		}
	}
	for (const path of systemPaths(project)) {
		if (parentOf(path) !== info.system) continue;
		const gid = groupOfSystem(project, path, index);
		if (gid && inside(gid)) out.systems.push(path);
	}
	return out;
}
