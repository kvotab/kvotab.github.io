/**
 * A name nothing in the model answers to, and the names it was probably meant
 * to be.
 *
 * An equation that names a block the model does not have is refused, and the
 * message says which name: `'Leach_rat' is not a block in this model`. On a
 * model of four thousand blocks named by somebody else the fix is rarely in
 * doubt -- it is the block a letter away -- and the slow part is finding that
 * block in the tree to read how it is spelt. So the names within a letter or
 * two of the one written are offered, the nearest first, each written the way
 * the equation would have to write it to reach that block from where it
 * stands; and offered as a change the reader makes with a click, never made
 * for them. A change made that way is an edit like any other, and undoes like
 * one.
 *
 * **What counts as near.** The optimal-string-alignment distance -- letters
 * put in, taken out, changed, or two neighbours swapped -- counted without
 * regard to case, so `water` finds `Water` before anything else. Two for a
 * name of five letters or more, one for a shorter one, and none for a single
 * letter beyond its other case: one letter from `k` is every other one-letter
 * name in the model, which is a list, not a suggestion.
 *
 * **Who is offered.** For a name read as a value: every block the equation
 * could read -- not itself, unless the field is the one about its own value
 * changing; not a block that is switched off, which would only be refused
 * again for another reason; not a transport operation, which is called rather
 * than read; and a function's parameters first, in its body. For a name
 * called: the library's functions, the model's own, its lookup tables and its
 * transport operations.
 */

import { tokenize } from '../parser/parser.js';
import { FUNCTIONS, FUNCTION_ALIASES } from '../parser/functions.js';
import { blockNames, findBlock } from './blocks.js';
import { parentOf, baseName, referenceFrom, qualifiedName, SEPARATOR } from './systems.js';
import { disabledNames } from './edit.js';
import * as tr from './transport.js';

/** How many names are offered for one that is not there. */
export const MOST_SUGGESTIONS = 3;

/**
 * The optimal-string-alignment distance between two strings, or `most + 1`
 * as soon as it is known to be larger than `most`.
 *
 * Insertions, deletions, substitutions and the transposition of two
 * neighbouring letters each count one. A row's smallest entry never falls in
 * later rows, so a row with nothing at or under `most` ends the count.
 */
export function nameDistance(a, b, most = Infinity) {
	const m = a.length;
	const n = b.length;
	if (Math.abs(m - n) > most) return most + 1;
	let before = null;
	let prev = Array.from({ length: n + 1 }, (_, j) => j);
	for (let i = 1; i <= m; i++) {
		const cur = new Array(n + 1);
		cur[0] = i;
		let low = cur[0];
		for (let j = 1; j <= n; j++) {
			const cost = a[i - 1] === b[j - 1] ? 0 : 1;
			let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
			if (before && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
				v = Math.min(v, before[j - 2] + 1);
			}
			cur[j] = v;
			if (v < low) low = v;
		}
		if (low > most) return most + 1;
		before = prev;
		prev = cur;
	}
	return prev[n];
}

/** How far a name of this length may be from the one meant. */
function reach(name) {
	const n = String(name).length;
	return n >= 5 ? 2 : n >= 2 ? 1 : 0;
}

/**
 * The names `written` was probably meant to be, nearest first.
 *
 * @param {object} project
 * @param {string} written        the name the equation has
 * @param {string} ownerName      the qualified name of the block it is in
 * @param {object} [opts]
 * @param {boolean} [opts.self]   whether the field may read its own block
 * @param {Iterable<string>|null} [opts.locals]  a function body's parameters
 * @param {boolean} [opts.call]   whether the name is called, `name(...)`
 * @param {number} [opts.most]
 * @returns {string[]} each written as the equation would have to write it
 */
export function nameSuggestions(project, written, ownerName, {
	self = false, locals = null, call = false, most = MOST_SUGGESTIONS,
} = {}) {
	const name = String(written ?? '');
	if (!name) return [];
	const lower = name.toLowerCase();
	const limit = reach(name);
	const system = parentOf(ownerName ?? '');
	const qualified = name.includes(SEPARATOR);
	const known = new Set(blockNames(project));
	const isKnown = (q) => known.has(q);
	const found = new Map();
	// rank: [nearness without case, scope, the name itself] -- smaller first.
	const offer = (text, compareWith, scope) => {
		if (!text || text === name) return;
		const d = nameDistance(lower, compareWith.toLowerCase(), limit);
		if (d > limit) return;
		const was = found.get(text);
		if (!was || d < was.d || (d === was.d && scope < was.scope)) found.set(text, { d, scope });
	};
	// Nearer the equation first: its own sub-system, then the top level, then
	// anywhere else -- which is also the order a bare name is looked for in.
	const scopeOf = (q) => (parentOf(q) === system ? 1 : parentOf(q) === '' ? 2 : 3);
	const asWritten = (q) => (qualified ? q : referenceFrom(q, system, isKnown));
	const comparedAs = (q) => (qualified ? q : baseName(q));

	if (call) {
		for (const fn of [...Object.keys(FUNCTIONS), ...Object.keys(FUNCTION_ALIASES)]) offer(fn, fn, 0);
		for (const f of project?.functions ?? []) if (f?.name) offer(String(f.name), String(f.name), 0);
		const callable = new Set([
			...(project?.lookups ?? []).map((b) => qualifiedName(b)),
			...tr.calledOperations(project).map((b) => qualifiedName(b)),
		]);
		for (const q of callable) offer(asWritten(q), comparedAs(q), scopeOf(q));
	} else {
		for (const p of locals ?? []) offer(String(p), String(p), 0);
		const off = disabledNames(project);
		const operations = new Set(tr.calledOperations(project).map((b) => qualifiedName(b)));
		for (const q of known) {
			if (q === ownerName && !self) continue;
			if (off.has(q) && !off.has(ownerName)) continue;
			if (operations.has(q)) continue;
			const hit = findBlock(project, q);
			if (hit?.kind === 'expression' && tr.roleOf(hit.block) === 'counter'
				&& !tr.counterVisibleTo(project, q, ownerName)) continue;
			offer(asWritten(q), comparedAs(q), scopeOf(q));
		}
	}
	return [...found.entries()]
		.sort(([a, p], [b, q]) => p.d - q.d || p.scope - q.scope || a.localeCompare(b))
		.slice(0, most)
		.map(([text]) => text);
}

/**
 * The fix a check's message admits, if it admits one: the name it refused and
 * the names it was probably meant to be.
 *
 * Read off the message rather than worked out beside it, so that a fix is
 * offered exactly where the check refused a name and for the name it named.
 * Two messages say a name is nobody's: one read as a value, one called.
 *
 * @returns {{written: string, call: boolean, to: string[]}|null}
 */
export function fixFor(project, message, ownerName, { self = false, locals = null } = {}) {
	const text = String(message ?? '');
	let m = /^'([^']+)' is not a block in this model/.exec(text);
	let call = false;
	if (!m) {
		m = /^Unknown function '([^']+)'/.exec(text);
		call = !!m;
	}
	if (!m) return null;
	const written = m[1];
	const to = nameSuggestions(project, written, ownerName, { self, locals, call });
	return to.length ? { written, call, to } : null;
}

/**
 * An equation with one name changed to another wherever it is written.
 *
 * By tokens, so `Kd` inside `Kd2` or inside a nuclide's index is left alone,
 * and leniently, so an equation with another fault in it can still have this
 * one put right. A name read as a value is changed where it is not called,
 * and a called one only where it is.
 */
export function replaceName(equation, from, to, { call = false } = {}) {
	const src = String(equation ?? '');
	const tokens = tokenize(src, true);
	let out = '';
	let at = 0;
	for (let i = 0; i < tokens.length; i++) {
		const tok = tokens[i];
		if (tok.type !== 'ident' || tok.value !== from) continue;
		const called = tokens[i + 1]?.type === 'lparen';
		if (called !== call) continue;
		out += src.slice(at, tok.pos) + to;
		at = tok.pos + tok.text.length;
	}
	return out + src.slice(at);
}

/** Whether two entries' index keys name the same position. */
function sameIndex(a, b) {
	const ka = Object.keys(a ?? {});
	const kb = Object.keys(b ?? {});
	return ka.length === kb.length && ka.every((k) => String(a[k]) === String(b?.[k]));
}

/**
 * Puts a fix into the model: the name changed in the one field, and the one
 * entry, the check refused it in.
 *
 * @param {object} project       changed in place
 * @param {string} where         the block's qualified name
 * @param {string} field         the field the equation is in
 * @param {object|null} index    the entry's index, or null for the block's own
 * @param {{written: string, call: boolean}} fix
 * @param {string} to            the name to write in its place
 * @returns {boolean} whether anything changed
 */
export function applyNameFix(project, where, field, index, fix, to) {
	const hit = findBlock(project, where);
	if (!hit || !fix?.written || !to) return false;
	const holder = index
		? (hit.block.entries ?? []).find((e) => sameIndex(e?.index, index))
		: hit.block;
	if (!holder || !Object.prototype.hasOwnProperty.call(holder, field)) return false;
	const value = holder[field];
	// An aggregate's targets are a list of names, each one a name and nothing
	// else: changed whole where it is the name refused.
	if (Array.isArray(value)) {
		const next = value.map((v) => (String(v) === fix.written ? to : v));
		if (next.every((v, i) => v === value[i])) return false;
		holder[field] = next;
		return true;
	}
	if (typeof value !== 'string') return false;
	const next = replaceName(value, fix.written, to, { call: !!fix.call });
	if (next === value) return false;
	holder[field] = next;
	return true;
}
