/**
 * What changed between two versions of a model.
 *
 * GoldSim keeps a version history inside the file and can print a report of
 * the differences between any two versions. This tool has an undo stack and a
 * file; the report is the useful half of that feature without the history: two
 * models in, a list of differences out, in words a reviewer can read. The two
 * models are the one in front of you and either the file as it was opened or
 * another file altogether -- the second is how a modeller answers "what did
 * they change between the January and the March assessment".
 *
 * The comparison is by name, block for block, field for field. Layout is left
 * out (where a block sits on the canvas is not a change to the model); a
 * comment is not, because a changed comment is a changed model to a reviewer.
 * A block that vanished under one name and appeared under another with
 * everything else identical is reported as renamed rather than as two changes,
 * since that is what happened.
 */

import { COLLECTIONS, qualifiedName } from './systems.js';

/** Fields that describe the drawing, not the model. */
const LAYOUT = new Set(['x', 'y', 'w', 'h', 'shape', 'colour', 'color', 'collapsed', 'label']);

/** Top-level keys that are compared some other way than as a block collection. */
const HEADER = new Set(['name', 'description']);
const OWN = new Set(['simulation', 'nuclides', 'index_lists', ...COLLECTIONS, ...HEADER]);

/** One kind's singular, for the report. */
export function singular(kind) {
	const map = {
		compartments: 'compartment', expressions: 'expression', parameters: 'parameter',
		lookups: 'lookup', index_reductions: 'index operation', block_reductions: 'block_reduction',
		min_maxes: 'min/max', running_means: 'running mean', snapshots: 'snapshot',
		delays: 'delay', triggers: 'discrete event', farfields: 'far-field path',
		functions: 'function', transfers: 'transfer', inflows: 'inflow',
	};
	return map[kind] ?? kind;
}

/** Stable JSON: the same object spelt the same way whatever the key order. */
function canonical(v) {
	if (v === undefined) return 'undefined';
	return JSON.stringify(v, (key, value) => {
		if (value && typeof value === 'object' && !Array.isArray(value)) {
			const out = {};
			for (const k of Object.keys(value).sort()) out[k] = value[k];
			return out;
		}
		return value;
	});
}

const same = (a, b) => canonical(a) === canonical(b);

/** A block without its layout, for telling a rename from a change. */
function body(block) {
	const out = {};
	for (const [k, v] of Object.entries(block ?? {})) if (!LAYOUT.has(k) && k !== 'name') out[k] = v;
	return canonical(out);
}

/** The key an indexed entry is filed under: its index, or its indices. */
function entryKey(e) {
	if (e?.index != null) return String(e.index);
	if (Array.isArray(e?.indices)) return e.indices.join(',');
	return canonical(e);
}

/**
 * The fields that differ between two blocks of one name.
 *
 * Indexed entries are matched by their index rather than by position, so a
 * value changed at `Cs-137` is reported as `entries[Cs-137].value` and an
 * entry added is reported as added, not as every entry after it having moved.
 *
 * @returns {Array<{field: string, before: *, after: *}>}
 */
export function fieldChanges(before, after) {
	const out = [];
	const keys = new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})]);
	for (const k of [...keys].sort()) {
		if (LAYOUT.has(k) || k === 'name') continue;
		const a = before?.[k];
		const b = after?.[k];
		if (same(a, b)) continue;
		if (k === 'entries' && (Array.isArray(a) || Array.isArray(b))) {
			const was = new Map((a ?? []).map((e) => [entryKey(e), e]));
			const now = new Map((b ?? []).map((e) => [entryKey(e), e]));
			for (const [key, e] of was) {
				if (!now.has(key)) out.push({ field: `entries[${key}]`, before: e, after: undefined });
			}
			for (const [key, e] of now) {
				if (!was.has(key)) { out.push({ field: `entries[${key}]`, before: undefined, after: e }); continue; }
				const prior = was.get(key);
				const sub = new Set([...Object.keys(prior ?? {}), ...Object.keys(e ?? {})]);
				for (const f of [...sub].sort()) {
					if (f === 'index' || f === 'indices') continue;
					if (!same(prior?.[f], e?.[f])) {
						out.push({ field: `entries[${key}].${f}`, before: prior?.[f], after: e?.[f] });
					}
				}
			}
			continue;
		}
		out.push({ field: k, before: a, after: b });
	}
	return out;
}

/** The name a list or a nuclide goes by, whether it is a string or an object. */
const nameOf = (x) => (typeof x === 'string' ? x : String(x?.name ?? ''));

/**
 * The differences between two models.
 *
 * @returns {{
 *   same: boolean,
 *   name: {before: string, after: string}|null,
 *   description: {before: string, after: string}|null,
 *   blocks: {
 *     added: Array<{kind: string, name: string}>,
 *     removed: Array<{kind: string, name: string}>,
 *     renamed: Array<{kind: string, from: string, to: string}>,
 *     changed: Array<{kind: string, name: string, fields: Array<{field: string, before: *, after: *}>}>,
 *     counted: {before: number, after: number},
 *   },
 *   lists: Array<{name: string, added: string[], removed: string[], fields: Array}>,
 *   listsAdded: string[], listsRemoved: string[],
 *   nuclides: {added: string[], removed: string[], changed: Array<{name: string, fields: Array}>},
 *   settings: Array<{field: string, before: *, after: *}>,
 *   other: Array<{field: string, before: *, after: *}>,
 * }}
 */
export function compareModels(before, after) {
	before ??= {};
	after ??= {};
	const out = {
		same: true,
		name: null,
		description: null,
		blocks: { added: [], removed: [], renamed: [], changed: [], counted: { before: 0, after: 0 } },
		lists: [], listsAdded: [], listsRemoved: [],
		nuclides: { added: [], removed: [], changed: [] },
		settings: [],
		other: [],
	};

	for (const k of HEADER) {
		const a = String(before[k] ?? '');
		const b = String(after[k] ?? '');
		if (a !== b) out[k] = { before: a, after: b };
	}

	// Blocks, kind by kind. A name is unique within a kind and across kinds
	// alike, but the report says the kind so the reader need not know that.
	for (const kind of COLLECTIONS) {
		const was = new Map((before[kind] ?? []).map((b) => [qualifiedName(b), b]));
		const now = new Map((after[kind] ?? []).map((b) => [qualifiedName(b), b]));
		out.blocks.counted.before += was.size;
		out.blocks.counted.after += now.size;
		const removed = [];
		for (const [name, b] of was) {
			if (!now.has(name)) { removed.push([name, b]); continue; }
			const fields = fieldChanges(b, now.get(name));
			if (fields.length) out.blocks.changed.push({ kind, name, fields });
		}
		const added = [];
		for (const [name, b] of now) if (!was.has(name)) added.push([name, b]);
		// A rename: gone under one name, back under another, otherwise the
		// same. Matched on the whole body, so two blocks that merely look
		// alike are not paired -- an added and a removed parameter both
		// holding `1` would be, and that is a defensible reading of it.
		const bodies = new Map();
		for (const [name, b] of removed) {
			const key = body(b);
			if (!bodies.has(key)) bodies.set(key, []);
			bodies.get(key).push(name);
		}
		const paired = new Set();
		for (const [name, b] of added) {
			const key = body(b);
			const from = bodies.get(key)?.shift();
			if (from === undefined) { out.blocks.added.push({ kind, name }); continue; }
			paired.add(from);
			out.blocks.renamed.push({ kind, from, to: name });
		}
		for (const [name] of removed) if (!paired.has(name)) out.blocks.removed.push({ kind, name });
	}

	// Index lists: by name, then by member.
	{
		const was = new Map((before.index_lists ?? []).map((l) => [nameOf(l), l]));
		const now = new Map((after.index_lists ?? []).map((l) => [nameOf(l), l]));
		for (const name of was.keys()) if (!now.has(name)) out.listsRemoved.push(name);
		for (const [name, l] of now) {
			if (!was.has(name)) { out.listsAdded.push(name); continue; }
			const prior = was.get(name);
			const a = new Set((prior.indices ?? []).map(nameOf));
			const b = new Set((l.indices ?? []).map(nameOf));
			const added = [...b].filter((x) => !a.has(x));
			const removed = [...a].filter((x) => !b.has(x));
			const fields = fieldChanges(
				{ ...prior, indices: undefined, name: undefined },
				{ ...l, indices: undefined, name: undefined },
			);
			// Members that stayed but changed -- a material's unit, say.
			const byName = new Map((prior.indices ?? []).map((i) => [nameOf(i), i]));
			for (const i of l.indices ?? []) {
				const p = byName.get(nameOf(i));
				if (p === undefined || typeof i === 'string' || typeof p === 'string') continue;
				for (const f of fieldChanges({ ...p, name: undefined }, { ...i, name: undefined })) {
					fields.push({ ...f, field: `${nameOf(i)}.${f.field}` });
				}
			}
			if (added.length || removed.length || fields.length) {
				out.lists.push({ name, added, removed, fields });
			}
		}
	}

	// Nuclides: names, and what is said about each.
	{
		const was = new Map((before.nuclides ?? []).map((n) => [nameOf(n), n]));
		const now = new Map((after.nuclides ?? []).map((n) => [nameOf(n), n]));
		for (const name of was.keys()) if (!now.has(name)) out.nuclides.removed.push(name);
		for (const [name, n] of now) {
			if (!was.has(name)) { out.nuclides.added.push(name); continue; }
			const p = was.get(name);
			if (typeof n === 'string' && typeof p === 'string') continue;
			const fields = fieldChanges(
				typeof p === 'string' ? {} : { ...p, name: undefined },
				typeof n === 'string' ? {} : { ...n, name: undefined },
			);
			if (fields.length) out.nuclides.changed.push({ name, fields });
		}
	}

	// The simulation settings, key by key.
	out.settings = fieldChanges(before.simulation ?? {}, after.simulation ?? {});

	// Anything else at the top level, whole.
	for (const k of new Set([...Object.keys(before), ...Object.keys(after)])) {
		if (OWN.has(k)) continue;
		if (!same(before[k], after[k])) out.other.push({ field: k, before: before[k], after: after[k] });
	}

	out.same = !out.name && !out.description
		&& !out.blocks.added.length && !out.blocks.removed.length
		&& !out.blocks.renamed.length && !out.blocks.changed.length
		&& !out.lists.length && !out.listsAdded.length && !out.listsRemoved.length
		&& !out.nuclides.added.length && !out.nuclides.removed.length && !out.nuclides.changed.length
		&& !out.settings.length && !out.other.length;
	return out;
}

/** A value as the report prints it: short, and unmistakably absent when absent. */
export function shown(v, width = 72) {
	if (v === undefined) return '(absent)';
	if (v === null) return 'null';
	if (typeof v === 'string') return v === '' ? '(empty)' : v;
	if (typeof v === 'number' || typeof v === 'boolean') return String(v);
	const text = JSON.stringify(v);
	return text.length > width ? `${text.slice(0, width - 1)}…` : text;
}

/** One line per differing field: `value 0.1 → 0.2`. */
function fieldLines(fields, indent) {
	return fields.map((f) => `${indent}${f.field}: ${shown(f.before)} → ${shown(f.after)}`);
}

/** The one-line count: "3 added, 1 removed, 4 changed, 1 renamed". */
export function summary(diff) {
	if (diff.same) return 'no differences';
	const b = diff.blocks;
	const parts = [];
	if (b.added.length) parts.push(`${b.added.length} added`);
	if (b.removed.length) parts.push(`${b.removed.length} removed`);
	if (b.changed.length) parts.push(`${b.changed.length} changed`);
	if (b.renamed.length) parts.push(`${b.renamed.length} renamed`);
	const rest = diff.lists.length + diff.listsAdded.length + diff.listsRemoved.length
		+ diff.nuclides.added.length + diff.nuclides.removed.length + diff.nuclides.changed.length;
	if (rest) parts.push(`${rest} in the lists and nuclides`);
	if (diff.settings.length) parts.push(`${diff.settings.length} setting${diff.settings.length === 1 ? '' : 's'}`);
	if (diff.name || diff.description) parts.push('the name or description');
	if (diff.other.length) parts.push(`${diff.other.length} other`);
	return parts.join(', ');
}

/**
 * The report, as lines of text.
 *
 * @param {object} diff  from `compareModels`
 * @param {{before?: string, after?: string}} labels  what the two versions are
 *   called -- file names, usually
 */
export function reportLines(diff, { before = 'the earlier version', after = 'this model' } = {}) {
	const lines = [`Version report: ${after} against ${before}`];
	if (diff.same) { lines.push('', 'No differences.'); return lines; }
	lines.push(`Blocks: ${diff.blocks.counted.before} before, ${diff.blocks.counted.after} after — ${summary(diff)}`);
	if (diff.name) lines.push(`Name: ${shown(diff.name.before)} → ${shown(diff.name.after)}`);
	if (diff.description) lines.push(`Description: ${shown(diff.description.before)} → ${shown(diff.description.after)}`);

	const b = diff.blocks;
	if (b.added.length || b.removed.length || b.renamed.length || b.changed.length) lines.push('');
	for (const x of b.added) lines.push(`+ ${singular(x.kind)} ${x.name}`);
	for (const x of b.removed) lines.push(`- ${singular(x.kind)} ${x.name}`);
	for (const x of b.renamed) lines.push(`↔ ${singular(x.kind)} ${x.from} → ${x.to} (renamed)`);
	for (const x of b.changed) {
		lines.push(`~ ${singular(x.kind)} ${x.name}`);
		lines.push(...fieldLines(x.fields, '    '));
	}

	if (diff.listsAdded.length || diff.listsRemoved.length || diff.lists.length) {
		lines.push('', 'Index lists');
		for (const n of diff.listsAdded) lines.push(`+ ${n}`);
		for (const n of diff.listsRemoved) lines.push(`- ${n}`);
		for (const l of diff.lists) {
			const bits = [];
			if (l.added.length) bits.push(`+ ${l.added.join(', ')}`);
			if (l.removed.length) bits.push(`- ${l.removed.join(', ')}`);
			lines.push(`~ ${l.name}${bits.length ? `: ${bits.join('; ')}` : ''}`);
			lines.push(...fieldLines(l.fields, '    '));
		}
	}

	const n = diff.nuclides;
	if (n.added.length || n.removed.length || n.changed.length) {
		lines.push('', 'Nuclides');
		if (n.added.length) lines.push(`+ ${n.added.join(', ')}`);
		if (n.removed.length) lines.push(`- ${n.removed.join(', ')}`);
		for (const x of n.changed) {
			lines.push(`~ ${x.name}`);
			lines.push(...fieldLines(x.fields, '    '));
		}
	}

	if (diff.settings.length) {
		lines.push('', 'Simulation settings');
		lines.push(...fieldLines(diff.settings, ''));
	}
	if (diff.other.length) {
		lines.push('', 'Elsewhere');
		lines.push(...fieldLines(diff.other, ''));
	}
	return lines;
}
