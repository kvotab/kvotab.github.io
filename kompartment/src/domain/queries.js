/**
 * Asking a model a question about itself.
 *
 * A name filter is the right tool when you know what the block is called. On an
 * imported assessment -- 4,500 blocks, named by somebody else, years ago -- the
 * questions that actually come up are different in kind:
 *
 *   *What reads this?*  Before changing a rate constant.
 *   *What does this need?*  Before moving a block into another model.
 *   *What does nothing read?*  Which is redundancy, or a mistake.
 *   *Which of these are transcribed numbers and which are worked out?*  Which
 *   is the line a review is drawn along.
 *
 * Every one of those is a walk the editor already does for some other reason --
 * `referencesToAny` for the delete guard, `integratingBlocks` for the
 * fingerprint. This is the same information, asked rather than inferred.
 *
 * AMBER has thirteen of these behind a Search dialog (Reference Manual §9.9),
 * and they are the part of it that most obviously belongs here: they need no
 * new concept, only an answer to a question the model can already be asked.
 *
 * Every query returns qualified names, sorted, so the caller can show them the
 * way it shows anything else.
 */

import { tokenize } from '../parser/parser.js';
import { RESERVED } from './names.js';
import { qualifiedName, systemOf, resolveReference, isWithin } from './systems.js';
import { blockNames, blockIndex, allBlocks, functionLocals } from './blocks.js';
import { EQUATION_FIELDS, RECORDER_COLLECTION } from './recorders.js';

/** Fields that hold an equation, by the collection the block lives in. */
const EQUATION_KEYS = {
	compartments: ['initial', 'dydt'],
	expressions: ['equation'],
	functions: ['equation'],
	transfers: ['rate'],
	inflows: ['rate'],
	parameters: ['value'],
};

/** Every equation a block carries, block-level and per entry, with its field. */
export function equationsOf(block, collection) {
	const keys = EQUATION_KEYS[collection]
		?? EQUATION_FIELDS[Object.entries(RECORDER_COLLECTION)
			.find(([, plural]) => plural === collection)?.[0]]
		?? [];
	const out = [];
	for (const key of keys) {
		if (typeof block[key] === 'string' && block[key].trim()) {
			out.push({ key, text: block[key] });
		}
		for (const e of block.entries ?? []) {
			if (typeof e?.[key] === 'string' && e[key].trim()) out.push({ key, text: e[key] });
		}
	}
	return out;
}

/**
 * Who reads whom: `name -> the names it reads`.
 *
 * One pass over every equation in the model, so the thirteen questions below
 * are thirteen reads of one table rather than thirteen walks. On the largest
 * assessment here that is the difference between a search that answers and one
 * that is worth avoiding.
 */
export function referenceGraph(project) {
	const index = blockIndex(project);
	const known = (n) => index.has(n);
	const reads = new Map();
	const readBy = new Map();
	const link = (from, to) => {
		if (!to || to === from) return;
		if (!reads.has(from)) reads.set(from, new Set());
		reads.get(from).add(to);
		if (!readBy.has(to)) readBy.set(to, new Set());
		readBy.get(to).add(from);
	};

	for (const [q, { block, collection }] of index) {
		const system = systemOf(block);
		for (const { key, text } of equationsOf(block, collection)) {
			const locals = functionLocals(block, key);
			let toks;
			try {
				toks = tokenize(String(text));
			} catch {
				// An equation mid-edit reads nothing. The problem strip is
				// what says so; a search should not refuse to answer because
				// one block is half-typed.
				continue;
			}
			for (let i = 0; i < toks.length; i++) {
				const tok = toks[i];
				if (tok.type !== 'ident') continue;
				if (toks[i + 1]?.type === 'lparen' && RESERVED.has(tok.value)) continue;
				if (locals?.has(tok.value)) continue;
				link(q, resolveReference(tok.value, system, known));
			}
		}
		// The endpoints a connection names are references too: a transfer
		// reads its donor as surely as its rate does.
		for (const key of ['from', 'to']) {
			if (typeof block[key] === 'string' && index.has(block[key])) link(q, block[key]);
		}
	}
	return { reads, readBy, index };
}

/** Everything reachable from `start` along `edges`, not including `start`. */
function closure(edges, start) {
	const out = new Set();
	const stack = [...(edges.get(start) ?? [])];
	while (stack.length) {
		const at = stack.pop();
		if (out.has(at)) continue;
		out.add(at);
		for (const next of edges.get(at) ?? []) stack.push(next);
	}
	out.delete(start);
	return out;
}

const sorted = (names) => [...names].sort((a, b) => a.localeCompare(b));

/**
 * The queries themselves.
 *
 * Each takes `(project, opts)` and returns qualified names. `graph` is passed
 * in by `runQuery` so several can share one walk.
 */
export const QUERIES = {
	uses: {
		label: 'That use…',
		needs: 'block',
		hint: 'Everything whose equations name the chosen block — directly, or '
			+ 'through others. What to look at before changing a rate constant.',
		run: (project, { name, direct = false, graph }) => sorted(
			direct ? (graph.readBy.get(name) ?? []) : closure(graph.readBy, name),
		),
	},
	usedBy: {
		label: 'That are used by…',
		needs: 'block',
		hint: 'Everything the chosen block needs to have a value. What has to '
			+ 'travel with it into another model.',
		run: (project, { name, direct = false, graph }) => sorted(
			direct ? (graph.reads.get(name) ?? []) : closure(graph.reads, name),
		),
	},
	unused: {
		label: 'That nothing reads',
		hint: 'Blocks no equation names. Some are meant to be read by a person '
			+ 'rather than by the model — a dose, a total — and the rest are '
			+ 'redundancy or a mistake.',
		run: (project, { graph }) => sorted(
			blockNames(project).filter((q) => !(graph.readBy.get(q)?.size)),
		),
	},
	dataOnly: {
		label: 'That are only data',
		hint: 'Blocks with no equation — a number somebody transcribed. The '
			+ 'other half of a review from the ones that are worked out.',
		run: (project) => sorted(allBlocks(project)
			.filter((b) => !equationsOf(b, b._collection).some(({ text }) => namesSomething(text)))
			.map((b) => qualifiedName(b))),
	},
	expressions: {
		label: 'That use an expression',
		hint: 'Blocks whose value is worked out from something else rather than '
			+ 'written down.',
		run: (project) => sorted(allBlocks(project)
			.filter((b) => equationsOf(b, b._collection).some(({ text }) => namesSomething(text)))
			.map((b) => qualifiedName(b))),
	},
	describedAs: {
		label: 'With a comment containing…',
		needs: 'text',
		hint: 'The comment a modeller left on a block. Where a review is '
			+ 'recorded, and where a "check this" is left.',
		run: (project, { text, caseSensitive = false }) => {
			const want = caseSensitive ? String(text) : String(text).toLowerCase();
			if (!want) return [];
			return sorted(allBlocks(project).filter((b) => {
				const c = String(b.comment ?? '');
				return (caseSensitive ? c : c.toLowerCase()).includes(want);
			}).map((b) => qualifiedName(b)));
		},
	},
	indexedOver: {
		label: 'Indexed over…',
		needs: 'list',
		hint: 'Everything that carries a value per entry of one index list.',
		run: (project, { list }) => sorted(allBlocks(project)
			.filter((b) => (b.index_lists ?? []).includes(list))
			.map((b) => qualifiedName(b))),
	},
	withUnit: {
		label: 'With the unit…',
		needs: 'text',
		hint: 'Written exactly as typed. Two blocks in Bq/m3 and Bq m-3 are the '
			+ 'same quantity spelled two ways, and finding both is how they '
			+ 'come to be spelled one.',
		run: (project, { text }) => {
			const want = String(text ?? '').trim();
			if (!want) return [];
			return sorted(allBlocks(project)
				.filter((b) => String(b.unit ?? '').trim() === want)
				.map((b) => qualifiedName(b)));
		},
	},
	unitMentions: {
		label: 'With a unit mentioning…',
		needs: 'text',
		hint: 'Anything whose unit contains the text — `Bq` finds Bq, Bq/m3 and '
			+ 'Bq/year at once.',
		run: (project, { text }) => {
			const want = String(text ?? '').trim().toLowerCase();
			if (!want) return [];
			return sorted(allBlocks(project)
				.filter((b) => String(b.unit ?? '').toLowerCase().includes(want))
				.map((b) => qualifiedName(b)));
		},
	},
	noUnit: {
		label: 'With no unit',
		hint: 'A unit is a claim about what a number means, and half of a real '
			+ 'model carries none — so this is a list of what the unit check '
			+ 'cannot help with.',
		run: (project) => sorted(allBlocks(project)
			.filter((b) => !String(b.unit ?? '').trim())
			.map((b) => qualifiedName(b))),
	},
	inSystem: {
		label: 'In the sub-system…',
		needs: 'system',
		hint: 'Everything inside one sub-system, however deep.',
		run: (project, { system }) => sorted(allBlocks(project)
			.filter((b) => {
				const home = systemOf(b);
				return home === system || isWithin(home, system);
			})
			.map((b) => qualifiedName(b))),
	},
	distributed: {
		label: 'That carry a distribution',
		hint: 'Everything a probabilistic run would sample.',
		run: (project) => sorted(allBlocks(project)
			.filter((b) => b.pdf || (b.entries ?? []).some((e) => e?.pdf))
			.map((b) => qualifiedName(b))),
	},
	notApproved: {
		label: 'That are not approved',
		hint: 'Everything a review has not signed off — never reviewed, changed '
			+ 'since, or worked out from something in one of those states. '
			+ 'The list a review works through.',
		run: (project, { qa }) => sorted([...(qa ?? new Map())]
			.filter(([, s2]) => s2.state !== 'approved')
			.map(([q]) => q)),
	},
	lapsed: {
		label: 'That were approved and lapsed',
		hint: 'Approved once, and not approved now — because the block changed, '
			+ 'or because something it is worked out from did. The list worth '
			+ 'looking at first, since somebody has already read these.',
		run: (project, { qa }) => sorted([...(qa ?? new Map())]
			.filter(([, s2]) => s2.state === 'stale' || (s2.state === 'review' && s2.why))
			.map(([q]) => q)),
	},
	locked: {
		label: 'That are locked',
		hint: 'Approved and held: the editor puts back any change to one of '
			+ 'these until it is unlocked.',
		run: (project) => sorted(allBlocks(project)
			.filter((b) => b.qa?.locked)
			.map((b) => qualifiedName(b))),
	},
	disabled: {
		label: 'That are switched off',
		hint: 'Blocks the model carries and the run does not.',
		run: (project) => sorted(allBlocks(project)
			.filter((b) => b.enabled === false)
			.map((b) => qualifiedName(b))),
	},
};

/** Whether an equation names anything at all, or is a bare number. */
function namesSomething(text) {
	try {
		return tokenize(String(text)).some((t) => t.type === 'ident');
	} catch {
		return false;
	}
}

/**
 * Runs one query.
 *
 * @param {object} project
 * @param {string} id      a key of QUERIES
 * @param {object} [opts]  whatever that query needs: `name`, `text`, `list`…
 * @returns {string[]} qualified names
 */
export function runQuery(project, id, opts = {}) {
	const q = QUERIES[id];
	if (!q) return [];
	// Only the two that walk references pay for the walk.
	const graph = opts.graph ?? (q.run.length > 1 && /uses|usedBy|unused/.test(id)
		? referenceGraph(project)
		: { reads: new Map(), readBy: new Map(), index: blockIndex(project) });
	return q.run(project, { ...opts, graph });
}
