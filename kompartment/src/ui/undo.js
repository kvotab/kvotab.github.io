/**
 * Undo and redo for the editor.
 *
 * Worth saying that this is not a given: the desktop tools in this family do
 * not offer undo at all, and a modeller who has spent an afternoon in one
 * knows why that hurts.
 *
 * The usual way to build one is a stack of commands, each edit knowing how to
 * put itself back. That wants an edit to be an object; here an edit is any of
 * about a hundred functions in edit.js writing straight into the model, and
 * asking each of them for an inverse would be a hundred chances to write one
 * that is subtly wrong -- and a hundred and first as soon as an edit is added.
 * So this takes the other road: snapshots. The model is a plain JSON object --
 * that is what the JSON tab shows and what Save writes -- so a snapshot is
 * `JSON.stringify` and restoring one is `JSON.parse`. Nothing can be missed,
 * because nothing has to be enumerated.
 *
 * The catch is size. The biggest models here are real: one landscape model
 * is 8 MB of JSON, so two hundred snapshots of it would be 1.6 GB. But two
 * consecutive snapshots of it differ in a few dozen characters -- one number
 * in one block -- and the rest is identical text. So only the part that
 * differs is kept: the characters between the longest common prefix and the
 * longest common suffix, which for that model measured 18 characters for a
 * block move rather than 8 million. The scan that finds them compares 64 KB at
 * a time with `===` (one memcmp inside the engine) before falling back to a
 * character loop inside the single chunk that differs: about a millisecond on
 * those 8 MB, against 28 for the character loop alone.
 *
 * Deltas are stored backwards -- the current state in full, each older step as
 * the patch that reaches it from the step after it. That way the state in hand
 * is always the one needed next, and one undo is one splice.
 */

import { KINDS, SINGULAR } from '../domain/edit.js';
import { qualifiedName, systemOf, baseName, parentOf } from '../domain/systems.js';

/**
 * How much text to compare at a time while looking for the common ends.
 *
 * Big enough that the per-comparison overhead disappears, small enough that
 * the character loop inside the odd chunk out stays short.
 */
const CHUNK = 1 << 16;

/** How many characters of stored difference to hold before dropping the oldest step. */
const BUDGET = 16e6;

/** How many steps to keep, however small they are. */
const LIMIT = 200;

/** The length of the longest run of characters `a` and `b` start with. */
export function commonPrefix(a, b) {
	const n = Math.min(a.length, b.length);
	let i = 0;
	while (i + CHUNK <= n && a.substr(i, CHUNK) === b.substr(i, CHUNK)) i += CHUNK;
	while (i < n && a.charCodeAt(i) === b.charCodeAt(i)) i++;
	return i;
}

/**
 * The length of the longest run of characters `a` and `b` end with, looking
 * back no further than `max` -- which the caller sets so that the common tail
 * cannot reach into the common head and count the same characters twice.
 */
export function commonSuffix(a, b, max) {
	let i = 0;
	while (i + CHUNK <= max
		&& a.substr(a.length - i - CHUNK, CHUNK) === b.substr(b.length - i - CHUNK, CHUNK)) {
		i += CHUNK;
	}
	while (i < max && a.charCodeAt(a.length - 1 - i) === b.charCodeAt(b.length - 1 - i)) i++;
	return i;
}

/**
 * What to splice into `base` to get `target`. `apply(base, diff(base, target))`
 * is `target`, for any two strings.
 */
export function diff(base, target) {
	const p = commonPrefix(base, target);
	const s = commonSuffix(base, target, Math.min(base.length, target.length) - p);
	return { p, s, mid: target.slice(p, target.length - s) };
}

/** The other half of `diff`. */
export function apply(base, d) {
	return base.slice(0, d.p) + d.mid + base.slice(base.length - d.s);
}

/**
 * The parts of a model whose change has a name.
 *
 * A full diff of two snapshots would say exactly what changed, but it would
 * cost a parse of the older one on every edit -- 21 ms on the big model, to
 * write a label nobody may read. This is the cheap half, gathered by walking
 * the blocks rather than the text: on the largest model in the corpus that is
 * 404 of them, which is nothing.
 */
export function shapeOf(raw) {
	if (!raw) return null;
	const blocks = [];
	const systems = new Set();
	for (const kind of KINDS) {
		for (const b of raw[kind] ?? []) {
			blocks.push(`${kind} ${qualifiedName(b)}`);
			const sys = systemOf(b);
			if (sys) systems.add(sys);
		}
	}
	const layout = [];
	for (const [k, v] of Object.entries(raw.layout ?? {})) {
		layout.push(`${k} ${v?.x ?? ''},${v?.y ?? ''},${v?.w ?? ''},${v?.h ?? ''}`);
	}
	return {
		blocks,
		// Sorted, both of them: which order two sub-systems were first
		// mentioned in is not an edit, and neither is which order two blocks
		// were laid out in.
		systems: [...systems].sort(),
		layout: layout.sort(),
		lists: JSON.stringify(raw.index_lists ?? null),
		simulation: JSON.stringify(raw.simulation ?? null),
		view: JSON.stringify(raw.view ?? null),
		shapes: JSON.stringify(raw.shapes ?? null),
		name: raw.name ?? '',
		description: raw.description ?? '',
	};
}

/** The members of `a` that are not in `b`. */
function missing(a, b) {
	const set = new Set(b);
	return a.filter((x) => !set.has(x));
}

const partsOf = (entry) => {
	const at = entry.indexOf(' ');
	const kind = entry.slice(0, at);
	const qname = entry.slice(at + 1);
	return {
		kind,
		qname,
		what: (SINGULAR[kind] ?? 'block').replace(/_/g, ' '),
		name: baseName(qname),
	};
};

const plural = (n, one) => (n === 1 ? one : `${n} ${one}s`);

/**
 * What to call the step from one shape to the next.
 *
 * `hint` is whatever the editor was pointed at when the edit was made -- the
 * block whose settings are open, or the selection -- which is what names the
 * many edits that change a value rather than the shape of anything.
 */
export function describe(before, after, hint) {
	if (!before || !after) return 'Edit';
	const added = missing(after.blocks, before.blocks).map(partsOf);
	const gone = missing(before.blocks, after.blocks).map(partsOf);

	if (added.length && !gone.length) {
		return added.length === 1
			? `Add ${added[0].what} ${added[0].name}`
			: `Add ${plural(added.length, 'block')}`;
	}
	if (gone.length && !added.length) {
		return gone.length === 1
			? `Delete ${gone[0].what} ${gone[0].name}`
			: `Delete ${plural(gone.length, 'block')}`;
	}
	if (added.length && added.length === gone.length) {
		// A block that left one name and arrived at another. That happens two
		// ways and they read differently: the name changed, or the block moved
		// to another sub-system and took its qualified name with it.
		const moved = added.filter((a) => gone.some((g) => g.name === a.name));
		if (moved.length === added.length) {
			const into = parentOf(moved[0].qname);
			return added.length === 1
				? `Move ${moved[0].name} to ${into || 'the top level'}`
				: `Move ${plural(added.length, 'block')}`;
		}
		if (added.length === 1) return `Rename ${gone[0].name} to ${added[0].name}`;
		return `Rename ${plural(added.length, 'block')}`;
	}
	if (added.length || gone.length) return 'Change blocks';

	if (before.systems.join('\n') !== after.systems.join('\n')) {
		const inn = missing(after.systems, before.systems);
		const out = missing(before.systems, after.systems);
		if (inn.length === 1 && !out.length) return `Add sub-system ${baseName(inn[0])}`;
		if (out.length === 1 && !inn.length) return `Delete sub-system ${baseName(out[0])}`;
		return 'Change sub-systems';
	}
	if (before.lists !== after.lists) return 'Edit index lists';
	if (before.simulation !== after.simulation) return 'Change simulation settings';
	if (before.shapes !== after.shapes) return 'Edit drawing';
	if (before.name !== after.name) return 'Rename the model';
	if (before.description !== after.description) return 'Edit the description';
	if (before.view !== after.view) return 'Change what the diagram shows';

	if (before.layout.join('\n') !== after.layout.join('\n')) {
		const changed = missing(after.layout, before.layout)
			.map((s) => s.slice(0, s.indexOf(' ')));
		if (changed.length && changed.every((k) => k.startsWith('edge:'))) {
			return `Reshape ${plural(changed.length, 'line')}`;
		}
		return `Move ${plural(changed.length || 1, 'block')}`;
	}

	return hint ? `Edit ${baseName(hint)}` : 'Edit';
}

/**
 * The steps taken, and where among them the editor is.
 *
 * The editor hands over the whole model after every edit and asks for one back
 * on undo; it never has to say what changed. An edit that changed nothing -- a
 * field committed at the value it already held, a menu that re-asserted a
 * setting -- is recognised here and takes no step, because an undo that does
 * nothing visible looks exactly like an undo that is broken.
 */
export class UndoStack {
	constructor({ limit = LIMIT, budget = BUDGET } = {}) {
		this.limit = limit;
		this.budget = budget;
		this.reset(null, null);
	}

	/** A model was loaded: this is where its history starts. */
	reset(raw, view) {
		this.undos = [];
		this.redos = [];
		this.cur = raw ? JSON.stringify(raw) : null;
		this.shape = shapeOf(raw);
		this.view = view ?? null;
	}

	/**
	 * The editor moved without editing anything.
	 *
	 * Selecting a block is not a step -- an undo that only moved the highlight
	 * would be maddening -- but it is what the *next* step should put back.
	 * Without this, deleting a block and undoing it brought the block back
	 * with nothing selected, because the last thing the stack had heard about
	 * the selection was from whenever the previous edit happened.
	 */
	note(view) {
		if (view) this.view = view;
	}

	get canUndo() { return this.undos.length > 0; }

	get canRedo() { return this.redos.length > 0; }

	/** What undoing would take back, for the button offering it. */
	get undoLabel() { return this.undos[this.undos.length - 1]?.label ?? null; }

	get redoLabel() { return this.redos[this.redos.length - 1]?.label ?? null; }

	/** The characters of difference being held, which the budget is spent in. */
	get cost() {
		const add = (n, e) => n + e.d.mid.length;
		return this.undos.reduce(add, 0) + this.redos.reduce(add, 0);
	}

	/**
	 * Records the model as it now is, one step on from what was recorded last.
	 *
	 * `coalesce`, when two records in a row carry the same one, folds the
	 * second into the first so the pair is a single step. The colour picker is
	 * the reason it exists: it reports every colour the pointer passes over,
	 * and a drag across the spectrum would otherwise put two hundred steps
	 * between the colour chosen and the one before it.
	 *
	 * `layoutOnly` is the editor's own word for an edit that cannot change a
	 * number -- a block moved, a line bent, the model renamed. It is carried
	 * on the step so that undoing one is as cheap as making it was: no re-run,
	 * and no results thrown away.
	 *
	 * @returns {boolean} whether this was a step at all.
	 */
	record(raw, view, {
		coalesce = null, hint = null, layoutOnly = false, label = null,
	} = {}) {
		if (!raw) return false;
		if (this.cur == null) { this.reset(raw, view); return false; }
		const text = JSON.stringify(raw);
		if (text === this.cur) {
			// Not a step -- but the view is still the latest one, and the step
			// back from here should return to where the editor is now rather
			// than to where it was when the last real edit was made.
			this.view = view ?? this.view;
			return false;
		}
		const shape = shapeOf(raw);
		const top = this.undos[this.undos.length - 1];
		if (coalesce && top && top.key === coalesce) {
			const began = apply(this.cur, top.d);
			if (began === text) {
				// The burst came back to where it started -- a colour swept
				// away and back again. Leaving the step there would offer an
				// undo that does nothing.
				this.undos.pop();
			} else {
				// Re-aim the step already on the stack at the new text, so
				// that it still leads back to where this burst began. Its
				// label is left alone for the same reason: it names the first
				// of them.
				top.d = diff(text, began);
				// One edit in the burst that could change a number makes the
				// whole burst one that could.
				top.layoutOnly = top.layoutOnly && !!layoutOnly;
			}
		} else {
			this.undos.push({
				d: diff(text, this.cur),
				view: this.view,
				label: label ?? describe(this.shape, shape, hint),
				key: coalesce,
				layoutOnly: !!layoutOnly,
			});
		}
		// Anything recorded is a new branch: what was undone is no longer
		// ahead of where this is going.
		this.redos = [];
		this.cur = text;
		this.shape = shape;
		this.view = view ?? null;
		this.trim();
		return true;
	}

	/** Drops the oldest steps until the stack is inside both of its limits. */
	trim() {
		while (this.undos.length > this.limit) this.undos.shift();
		while (this.undos.length > 1 && this.cost > this.budget) this.undos.shift();
	}

	undo() { return this._step(this.undos, this.redos); }

	redo() { return this._step(this.redos, this.undos); }

	/**
	 * One step in either direction: they are the same move, and which stack is
	 * which is the only difference between them.
	 */
	_step(from, to) {
		const step = from.pop();
		if (!step) return null;
		const text = apply(this.cur, step.d);
		to.push({
			d: diff(text, this.cur),
			view: this.view,
			label: step.label,
			key: null,
			layoutOnly: step.layoutOnly,
		});
		const raw = JSON.parse(text);
		this.cur = text;
		this.shape = shapeOf(raw);
		this.view = step.view;
		return { raw, view: step.view, label: step.label, layoutOnly: !!step.layoutOnly };
	}
}
