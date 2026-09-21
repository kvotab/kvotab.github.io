/**
 * Sub-systems: the hierarchy a model is organised into.
 *
 * Ecolego groups blocks into sub-systems, which nest, and scopes names inside
 * them: two compartments called `Water` in different sub-systems are different
 * compartments, and an equation inside one of them that says `Water` means its
 * own. Reaching across is done with a qualified name -- `NearField.Water`, or
 * `NearField.Bentoniteinlet.Comp_5` -- which is exactly what a saved project
 * stores as a block's id.
 *
 * This tool used to have one flat namespace, which is why a real assessment
 * model imported but would not build: its equations navigate the hierarchy, and
 * there was no hierarchy to navigate.
 *
 * The representation here is deliberately shallow. A block keeps its own local
 * `name` and gains a `system` -- the dotted path of the sub-system holding it,
 * absent at the root. Everything else in the application goes on addressing
 * blocks by one string, their *qualified* name, which for a model without
 * sub-systems is the name it always was. That is what keeps every existing
 * file, and every existing part of the editor, working unchanged.
 */

/** What separates the parts of a qualified name, as in the .eco format. */
export const SEPARATOR = '.';

import { NAME_RE } from './names.js';

/** `NearField.Bentoniteinlet` -> ['NearField', 'Bentoniteinlet']. */
export function parts(path) {
	return path ? String(path).split(SEPARATOR).filter(Boolean) : [];
}

/** The path of a block's sub-system, or '' at the root. */
export function systemOf(block) {
	return block?.system ?? '';
}

/** The one string the rest of the application addresses a block by. */
export function qualify(system, name) {
	return system ? `${system}${SEPARATOR}${name}` : name;
}

/** A block's qualified name: its sub-system's path, then its own name. */
export function qualifiedName(block) {
	return qualify(systemOf(block), block?.name ?? '');
}

/** The sub-system containing `path`, or '' when it is already at the root. */
export function parentOf(path) {
	const p = parts(path);
	p.pop();
	return p.join(SEPARATOR);
}

/** The last component of a path: the sub-system's own name. */
export function baseName(path) {
	const p = parts(path);
	return p.length ? p[p.length - 1] : '';
}

/**
 * Every sub-system a name is visible from, innermost first: the enclosing
 * system, then each of its ancestors, ending at the root. This is the search
 * order for resolving a reference, and the reason `Water` inside a sub-system
 * finds its own before the model's.
 */
export function scopeChain(system) {
	const chain = [];
	let at = system ?? '';
	for (;;) {
		chain.push(at);
		if (!at) return chain;
		at = parentOf(at);
	}
}

/** Whether `path` is `system` itself or lies inside it. */
export function isWithin(path, system) {
	if (!system) return true;
	return path === system || String(path ?? '').startsWith(system + SEPARATOR);
}

/** Whether `path` is a direct child of `system`. */
export function isDirectChild(path, system) {
	return parentOf(path) === (system ?? '') && !!path;
}

/** A path with one prefix swapped for another, used when a sub-system moves. */
export function reparent(path, from, to) {
	if (!from) return to ? qualify(to, path) : path;
	if (path === from) return to;
	if (!isWithin(path, from)) return path;
	const tail = path.slice(from.length + 1);
	return to ? qualify(to, tail) : tail;
}

/**
 * Whether every component of a path is a usable identifier.
 *
 * The split is deliberately unfiltered: `A..B` and `A.` have an empty
 * component, and quietly dropping it would accept a path that no block could
 * ever be addressed by.
 */
export function isValidPath(path) {
	if (!path) return true;
	const p = String(path).split(SEPARATOR);
	return p.every((c) => NAME_RE.test(c));
}

/**
 * The sub-systems a project contains, as paths, deepest last.
 *
 * A sub-system exists because it is declared, not merely because something is
 * in it: an empty one is a real place to put the next block, and has to survive
 * a save. Anything a block claims as its system is included even if it was
 * never declared, so a hand-edited file cannot lose blocks into a sub-system
 * the editor does not show.
 */
export function systemPaths(project, blocks = null) {
	const seen = new Set();
	const add = (path) => {
		if (!path) return;
		// A nested path implies its ancestors.
		const p = parts(path);
		for (let i = 1; i <= p.length; i++) seen.add(p.slice(0, i).join(SEPARATOR));
	};
	for (const s of project?.systems ?? []) add(typeof s === 'string' ? s : s?.name);
	// A transport is a sub-system too -- one with a role -- and is declared in
	// its own list, so that the list of paths can stay a list of paths. See
	// ./transport.js.
	for (const s of project?.transports ?? []) add(typeof s === 'string' ? s : s?.name);
	for (const b of blocks ?? allBlocks(project)) add(systemOf(b));
	return [...seen].sort((a, b) => parts(a).length - parts(b).length || a.localeCompare(b));
}

/**
 * The collections a project's blocks live in.
 *
 * Here rather than in ./edit.js because this file is the one underneath: the
 * editor imports it, not the other way round, and `edit.KINDS` re-exports this
 * so there is one list. It used to be written out twice, and the copy here
 * went stale -- it never gained the far-field paths or any of the five kinds
 * that remember, so a sub-system holding nothing but a delay was not a
 * sub-system as far as `systemPaths` was concerned, and the diagram had
 * nowhere to draw it.
 */
export const COLLECTIONS = [
	'compartments', 'expressions', 'parameters', 'lookups',
	'index_reductions', 'block_reductions',
	'min_maxes', 'running_means', 'snapshots', 'delays', 'triggers',
	'farfields',
	// Waste packages: the source term with its barriers. See ./wastepackage.js.
	'waste_packages',
	// Disruptive events: something happens to the model at an instant. See ./disruption.js.
	'events',
	// A function is a block too, though it is the one kind with no value: it
	// is called rather than read, it lives at the top level rather than in a
	// sub-system, and it is drawn nowhere. It is here so that the one name
	// space holds it -- a function and a compartment cannot share a name --
	// and so that renaming, deleting, searching and the block tree treat it
	// as what it is. See ./functions.js.
	'functions',
	'transfers', 'inflows',
];

/** Every block in the project, whatever its kind. */
export function allBlocks(project) {
	const out = [];
	for (const kind of COLLECTIONS) {
		for (const b of project?.[kind] ?? []) out.push(b);
	}
	return out;
}

/**
 * Resolves a reference the way an equation means it.
 *
 * This is the mirror of how Ecolego *writes* a reference -- the rule below is
 * read off the project files, and followed here rather than inventing a
 * scoping of this tool's own:
 *
 *   if the target is in the writer's own namespace, or at the root,
 *       write its local name
 *   otherwise
 *       write its full id
 *
 * So reading is: a bare name is mine, or failing that the model's; a name with
 * a dot in it is a full path from the root. Nothing in between -- a block in an
 * *intermediate* ancestor is written qualified, so it is read that way too, and
 * an outward walk through the ancestors would resolve references Ecolego never
 * writes, and could quietly bind one to the wrong block.
 *
 * The one genuine ambiguity is the format's own: with a `Volume` inside `A` and
 * another at the root, Ecolego writes both as `Volume`. The nearer one wins,
 * which is the only reading under which a sub-system's own block is its own.
 *
 * `known` answers whether a qualified name exists. Returns the qualified name,
 * or null when nothing matches.
 */
export function resolveReference(reference, system, known) {
	if (String(reference).includes(SEPARATOR)) {
		return known(reference) ? reference : null;
	}
	const own = qualify(system, reference);
	if (known(own)) return own;
	return known(reference) ? reference : null;
}

/**
 * How a block should be *written* when referred to from `system` -- the same
 * rule in the other direction. Used when an equation is rewritten after a
 * rename or a move, so a reference that was local stays local.
 */
export function referenceFrom(target, system, known = null) {
	const targetSystem = parentOf(target);
	if (!targetSystem || targetSystem === (system ?? '')) {
		const local = baseName(target);
		// ... but only when the short form still finds this block. A `Water` at
		// the root is shadowed by a `Water` in the sub-system doing the
		// writing, and writing `Water` there would quietly rebind it.
		if (!known || resolveReference(local, system, known) === target) return local;
	}
	return target;
}
