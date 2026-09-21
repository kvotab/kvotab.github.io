/**
 * What may be written at the caret of an equation.
 *
 * Ecolego has this: the equation cell editor keeps a `JPopupMenu` of a
 * `JXList`, the space bar opens it (`AutoCompleteAction`) and Enter replaces
 * the word under the caret with what is chosen
 * (`EquationEditor.valueReceived`, which calls `replaceRange(value,
 * startOfCurrentWord, endOfCurrentWord)`). What it offers is every search item
 * in the model, unfiltered and unsorted; it also refuses to open inside `[ ]`,
 * where an index name is being typed.
 *
 * The shape here is the same -- a word under the caret, replaced by a choice
 * -- with three differences, each of which is the reason the original is
 * awkward to use on a model of any size:
 *
 *   - it filters as you type, rather than showing all 900 names every time;
 *   - it offers *functions* as well as blocks, with their signatures, which is
 *     the half you cannot look up without leaving the editor;
 *   - it completes index names *inside* the brackets rather than giving up
 *     there, because `[F.18:00_51_FORSMARK]` is not a thing anyone should have
 *     to type from memory.
 *
 * Everything in this file is a pure function of the project and the text, so
 * the awkward parts -- where a word starts, what a name means from inside a
 * sub-system, which of two blocks a bare name would bind to -- are tested
 * without a browser. ../ui/complete.js is the popup and nothing else.
 */

import { functionNames, functionHelp } from '../parser/function-help.js';
import {
	qualifiedName, resolveReference, referenceFrom, systemOf,
} from './systems.js';
import { KINDS, SINGULAR, effectiveDims, dimensionIndices } from './edit.js';
import { COMPARTMENT_LIST, SOURCE_INDEX, TARGET_INDEX } from './indexlists.js';

/** Whether the equation being written belongs to a transfer. */
const isTransfer = (project, name) => !!name
	&& (project?.transfers ?? []).some((t) => qualifiedName(t) === name);

/** What an identifier, or a dotted path of them, is made of. */
const NAME_CHAR = /[A-Za-z0-9_.]/;
const NAME_START = /[A-Za-z_]/;

/**
 * The word being completed, and the span it occupies.
 *
 * Two kinds of word, because an equation has two namespaces in it. A `name` is
 * an identifier or a dotted path -- a block, or a function. An `index` is
 * whatever is inside a `[ ]`, which is not an identifier at all: real models
 * index by `F.18:00_51_FORSMARK`, `_Ra-226` and `01`, so the span runs to the
 * bracket rather than to the first character that is not a letter.
 *
 * Returns null where nothing can be completed: in the middle of a number, or
 * against a word that starts with a digit.
 *
 * @param {string} text
 * @param {number} caret
 * @returns {{start: number, end: number, word: string, kind: 'name'|'index',
 *   owner?: string, slot?: number}|null}
 */
export function wordAt(text, caret) {
	const src = String(text ?? '');
	const at = Math.max(0, Math.min(caret ?? 0, src.length));

	// Inside brackets? Walk back for an unclosed `[`, exactly as the format's
	// `checkInsideBrackets` does.
	let open = -1;
	for (let i = at - 1; i >= 0; i--) {
		if (src[i] === ']') break;
		if (src[i] === '[') { open = i; break; }
	}
	if (open >= 0) {
		let end = at;
		while (end < src.length && src[end] !== ']' && src[end] !== '[') end++;
		// Which bracket of the reference this is, and whose it is: `M[a][b]`
		// pins M's second dimension in the second pair.
		let slot = 0;
		let i = open;
		while (i > 0 && src[i - 1] === ']') {
			slot++;
			i -= 2;
			while (i >= 0 && src[i] !== '[') i--;
			if (i < 0) return null;
		}
		let nameEnd = i;
		while (nameEnd > 0 && /\s/.test(src[nameEnd - 1])) nameEnd--;
		let nameStart = nameEnd;
		while (nameStart > 0 && NAME_CHAR.test(src[nameStart - 1])) nameStart--;
		const owner = src.slice(nameStart, nameEnd);
		if (!owner || !NAME_START.test(owner[0])) return null;
		return {
			start: open + 1, end, word: src.slice(open + 1, at), kind: 'index', owner, slot,
		};
	}

	let start = at;
	while (start > 0 && NAME_CHAR.test(src[start - 1])) start--;
	let end = at;
	while (end < src.length && NAME_CHAR.test(src[end])) end++;
	// `2.5e3` is a number, and `x.5` is not a path: a word that does not begin
	// with a letter is not something this can complete.
	if (start < src.length && !NAME_START.test(src[start] ?? '')) return null;
	return { start, end, word: src.slice(start, at), kind: 'name' };
}

/** Whether the next thing after `end`, ignoring spaces, is an opening paren. */
function callFollows(text, end) {
	let i = end;
	while (i < text.length && (text[i] === ' ' || text[i] === '\t')) i++;
	return text[i] === '(';
}

/**
 * Every block that can be named from `system`, written the way it has to be
 * written from there.
 *
 * `referenceFrom` decides the text: a local name where that binds to this
 * block, its full path otherwise. The result is checked by resolving it again,
 * which drops the one case the .eco format cannot express -- a root `Volume`
 * seen from a sub-system that has a `Volume` of its own is shadowed, and
 * offering `Volume` there would quietly insert a reference to the wrong block.
 *
 * @param {object} project
 * @param {{system?: string, exclude?: string}} opts `exclude` is the block
 *   being edited: an equation that names itself is a cycle, not a completion.
 */
export function blockCandidates(project, { system = '', exclude = null } = {}) {
	const names = [];
	const found = [];
	for (const collection of KINDS) {
		for (const block of project?.[collection] ?? []) {
			const name = qualifiedName(block);
			names.push(name);
			found.push({ name, block, collection });
		}
	}
	const set = new Set(names);
	const known = (n) => set.has(n);

	const out = [];
	for (const { name, block, collection } of found) {
		if (name === exclude) continue;
		// A transport's element counter is readable only inside its chain, so
		// outside it is not offered -- offering it would be offering a mistake
		// the checker then reports.
		if (block.transport === 'counter' && systemOf(block) !== system) continue;
		const insert = referenceFrom(name, system, known);
		if (resolveReference(insert, system, known) !== name) continue;
		out.push({
			type: 'block',
			insert,
			match: insert,
			label: insert,
			name,
			kind: SINGULAR[collection],
			collection,
			block,
			unit: block.unit ?? '',
		});
	}
	return out;
}

/**
 * Every function the parser knows, canonical names and the aliases both.
 *
 * The aliases are here because .eco files use them -- `ln`, `pow`, `fabs`,
 * `sgn`, `product` -- and someone who types `ln` should be offered `ln`, not
 * quietly handed `log`.
 *
 * Built once. The blocks have to be gathered again on every keystroke, since
 * the model is what is being edited, but the function library is fixed at
 * compile time and rebuilding it fifty-eight times a character is fifty-eight
 * regular expressions for an answer that cannot have changed.
 */
let functions = null;
export function functionCandidates() {
	if (functions) return functions;
	functions = [];
	for (const name of functionNames()) {
		const help = functionHelp(name);
		if (!help) continue;
		functions.push({
			type: 'function',
			insert: name,
			match: name,
			label: help.signature,
			name,
			help,
		});
	}
	return functions;
}

/**
 * The index names that may go in one bracket of one reference: `Soil[` offers
 * the radionuclides, and its second bracket offers the objects.
 *
 * Every dimension's indices, not only the one this bracket is in. Ecolego
 * resolves a bracket **by name, not by position**
 * (index-name resolution, and sim/builder.js `pinIndices` here), and
 * that is not a technicality: of the 506 two-bracket references in the .eco
 * files tested here, 200 are written in the order the *other* dimension would
 * suggest. So a positional list would refuse to offer two references in five
 * that real models contain. The dimension this bracket sits in comes first,
 * since that is the order Ecolego writes them in, and the list each index
 * belongs to is carried along for the caller to show.
 *
 * An unindexed block, and a bracket past the end of the dimensions -- which is
 * an error rather than an empty choice -- have nothing to offer, and the popup
 * simply does not open.
 */
export function indexCandidates(
	project, { owner, slot = 0, system = '', writtenIn = null } = {},
) {
	const set = new Set(blockNamesOf(project));
	const target = resolveReference(owner, system, (n) => set.has(n));
	if (!target) return [];
	for (const collection of KINDS) {
		const block = (project?.[collection] ?? []).find((b) => qualifiedName(b) === target);
		if (!block) continue;
		const dims = effectiveDims(project, block);
		if (slot >= dims.length) return [];
		const order = [dims[slot], ...dims.filter((_, i) => i !== slot)];
		const out = [];
		const seen = new Set();
		// A transfer's own two ends. They are the only way to reach a
		// per-compartment value from a transfer, and nothing about the
		// equation says they exist -- so they are offered first, where they
		// apply, and are worth more than any single compartment name here.
		if (order.includes(COMPARTMENT_LIST) && isTransfer(project, writtenIn)) {
			for (const [word, what] of [
				[SOURCE_INDEX, 'the compartment this transfer flows out of'],
				[TARGET_INDEX, 'the compartment this transfer flows into'],
			]) {
				out.push({
					type: 'index', insert: word, match: word, label: word, name: word,
					list: what, rank: -1000 + out.length,
				});
				seen.add(word);
			}
		}
		dimensionIndices(project, order).forEach((names, i) => {
			for (const name of names) {
				// One list may appear twice in a block's dimensions -- a matrix
				// over a list and a copy of it -- and the same name twice in
				// the list is one thing to offer, not two.
				if (seen.has(name)) continue;
				seen.add(name);
				// The order a list declares its indices in is the model's own,
				// and it usually means something -- a decay chain, a sequence
				// of objects. `rank` keeps it, where the general tie-break
				// would sort `Lake` above `I-129` for being shorter.
				out.push({
					type: 'index', insert: name, match: name, label: name, name,
					list: order[i], rank: i * 1000 + out.length,
				});
			}
		});
		return out;
	}
	return [];
}

function blockNamesOf(project) {
	const out = [];
	for (const collection of KINDS) {
		for (const b of project?.[collection] ?? []) out.push(qualifiedName(b));
	}
	return out;
}

/**
 * The candidates a word matches, best first.
 *
 * Five tiers, and a candidate is placed in the first it satisfies:
 *
 *   0. it starts with the word, spelled the same way;
 *   1. the last part of a path does -- typing `Water` finds
 *      `NearField.Water`, which is most of the reason paths are worth having;
 *   2. it starts with the word, ignoring case;
 *   3. the last part of a path does, ignoring case;
 *   4. the word appears anywhere in it.
 *
 * Case is what separates 0-1 from 2-3, and it does more work here than it
 * looks like it should. Block names in this domain are capitalised and
 * function names are not, so typing `mi` offers `min` before `Mixing` and
 * typing `Mi` offers `Mixing` before `min`, without either being a rule about
 * blocks and functions.
 *
 * Within a tier the model's own blocks come before the function library, and
 * shorter names before longer ones, so an exact name is not buried under
 * everything it is a prefix of. A candidate may carry its own `rank` to be
 * ordered by instead, which is how a list of index names keeps the order the
 * model declares them in. An empty word matches everything, which is what
 * asking for the list without typing anything should do.
 */
export function rankCompletions(word, candidates, limit = 100) {
	const w = String(word ?? '');
	const lower = w.toLowerCase();
	const scored = [];

	for (const c of candidates) {
		const m = c.match;
		const tail = m.slice(m.lastIndexOf('.') + 1);
		let tier;
		if (!w) tier = 2;
		else if (m.startsWith(w)) tier = 0;
		else if (tail.startsWith(w)) tier = 1;
		else if (m.toLowerCase().startsWith(lower)) tier = 2;
		else if (tail.toLowerCase().startsWith(lower)) tier = 3;
		else if (m.toLowerCase().includes(lower)) tier = 4;
		else continue;
		scored.push({ c, tier, rank: c.rank ?? (c.type === 'function' ? 1 : 0) });
	}

	scored.sort((a, b) => a.tier - b.tier
		|| a.rank - b.rank
		|| a.c.match.length - b.c.match.length
		|| (a.c.match < b.c.match ? -1 : a.c.match > b.c.match ? 1 : 0));

	return { items: scored.slice(0, limit).map((s) => s.c), total: scored.length };
}

/**
 * Everything the caller needs to show a completion popup: where the word is,
 * what could replace it, and what each replacement would do to the text.
 *
 * `insert` is what the span becomes and `caret` says where the caret lands
 * relative to the end of it, so a function comes out as `min(|)` with the
 * caret between the parentheses and an index as `[Cs-137]` with its bracket
 * closed -- unless one is already there, in which case nothing is doubled.
 *
 * `functions` is off for the few fields that hold a list of block names
 * rather than an expression -- an aggregate's targets are written `A + B + C`,
 * and `min(` would be nothing but a wrong answer offered politely.
 *
 * @param {object} project
 * @param {{text: string, caret: number, system?: string, owner?: string,
 *   limit?: number, functions?: boolean}} opts `owner` is the qualified name
 *   of the block whose equation this is.
 */
export function completionsAt(project, {
	text, caret, system = '', owner = null, limit = 100, functions = true,
	locals = null,
}) {
	const src = String(text ?? '');
	const at = wordAt(src, caret);
	if (!at) return null;

	// A user-defined function's parameters are names in its body and nowhere
	// else, so they are offered there and only there -- first, since they are
	// what a body is mostly made of. See ../sim/functions.js.
	const source = at.kind === 'index'
		? indexCandidates(project, {
			owner: at.owner, slot: at.slot, system, writtenIn: owner,
		})
		: [
			...(locals ? [...locals].map((name) => ({
				type: 'local', insert: name, match: name, label: name, name,
			})) : []),
			...blockCandidates(project, { system, exclude: owner }),
			...(functions ? functionCandidates() : []),
		];
	if (!source.length) return null;

	const { items, total } = rankCompletions(at.word, source, limit);
	if (!items.length) return null;

	const closed = src[at.end] === ']';
	const called = callFollows(src, at.end);
	const placed = items.map((c) => {
		if (c.type === 'index') {
			return { ...c, insert: closed ? c.insert : `${c.insert}]`, caret: 0 };
		}
		if (called) return { ...c, caret: 0 };
		if (c.type === 'function' && c.help.maxArity > 0) {
			return { ...c, insert: `${c.insert}()`, caret: -1 };
		}
		// A lookup table read at an argument is not a value: it is called, and
		// it cannot be referred to by name alone (LookupTable.OptionArgument
		// in the format, and the hint the inspector shows beside the setting).
		if (c.type === 'block' && c.collection === 'lookups' && c.block.argument) {
			return { ...c, insert: `${c.insert}()`, caret: -1 };
		}
		// A user-defined function is called, never read: it has no value of
		// its own, only a body and the arguments it is handed.
		if (c.type === 'block' && c.collection === 'functions') {
			return { ...c, insert: `${c.insert}()`, caret: c.block.parameters?.length ? -1 : 0 };
		}
		return { ...c, caret: 0 };
	});

	return {
		start: at.start, end: at.end, word: at.word, kind: at.kind,
		items: placed, total,
	};
}

/**
 * The text and caret position after taking one of them.
 *
 * Separate from the popup so that what a completion *does* to an equation can
 * be tested directly, and so the same rule applies however it was chosen.
 */
export function applyCompletion(text, { start, end }, item) {
	const src = String(text ?? '');
	const next = src.slice(0, start) + item.insert + src.slice(end);
	return { text: next, caret: start + item.insert.length + (item.caret ?? 0) };
}

/**
 * What the chart's search box could be looking for: the names in a run's
 * outputs, each once, with how many lines it would find.
 *
 * Two kinds of name make up a label -- `Soil [Cs-137, Lake]` is a block and
 * two indices -- and either is a reasonable thing to type. A block first, an
 * index after, since a block is usually what is being looked for and the
 * indices are how the lines under it are told apart. Within a kind, the order
 * the outputs come in, which is the model's own.
 *
 * @param {Array<{kind: string, block: string, label: string, unit?: string,
 *   dims?: string[], index?: string[]}>} outputs
 * @returns {Array<{type: 'search', what: 'block'|'index', label: string,
 *   match: string, insert: string, count: number, rank: number}>}
 */
export function searchCandidates(outputs) {
	const blocks = new Map();
	const indices = new Map();
	for (const o of outputs ?? []) {
		const name = o.block ?? o.label;
		if (!blocks.has(name)) blocks.set(name, { kind: o.kind, count: 0, units: new Set() });
		const b = blocks.get(name);
		b.count++;
		if (o.unit) b.units.add(o.unit);
		(o.index ?? []).forEach((idx, at) => {
			const list = o.dims?.[at] ?? '';
			const key = `${list} ${idx}`;
			if (!indices.has(key)) indices.set(key, { list, name: idx, count: 0 });
			indices.get(key).count++;
		});
	}
	const lines = (n) => `${n} line${n === 1 ? '' : 's'}`;
	// The rank is the model's own order, so that a list opened before
	// anything is typed reads as the model does rather than shortest-first;
	// what is typed still sorts by how well it matches, above the rank.
	const out = [];
	let seq = 0;
	for (const [name, b] of blocks) {
		const unit = b.units.size === 1 ? [...b.units][0] : null;
		out.push({
			type: 'search', what: 'block', kind: b.kind, label: name, match: name, insert: name,
			count: b.count, rank: seq++,
			detail: lines(b.count),
			say: [b.kind.replace(/_/g, ' '), lines(b.count), ...(unit ? [unit] : [])].join(' - '),
		});
	}
	// An index is what is typed, and the same name in two lists -- a nuclide
	// in the materials and among the radionuclides, a compartment in the
	// Compartments list and a sub-set of it -- is one thing to type. Offered
	// once, naming every list it is in; and not at all where it is a block's
	// name too, since the block's row already says it.
	const byName = new Map();
	for (const { list, name, count } of indices.values()) {
		if (blocks.has(name)) continue;
		if (!byName.has(name)) byName.set(name, { lists: [], count: 0 });
		const e = byName.get(name);
		if (!e.lists.includes(list)) e.lists.push(list);
		e.count += count;
	}
	seq = 1e6;
	for (const [name, e] of byName) {
		out.push({
			type: 'search', what: 'index', list: e.lists.join(', '), label: name, match: name,
			insert: name, count: e.count, rank: seq++,
			detail: e.lists.join(', '),
			say: `An index of ${e.lists.join(' and of ')} - ${lines(e.count)}`,
		});
	}
	return out;
}
