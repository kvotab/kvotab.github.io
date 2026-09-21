/**
 * Transport sub-systems: a chain of N identical compartments, drawn as two.
 *
 * Ecolego's TransportSubSystem is the way a model discretises transport
 * through a homogeneous material -- a soil column, a sediment, a stretch of
 * river -- without drawing every slice of it. The modeller draws two
 * compartments in it, *Begin* and *End*, connects them with the transfers one
 * slice exchanges with the next, connects the outside world to Begin and End,
 * and writes down N. When the model runs, Begin and End stand at the two ends
 * of a chain of N compartments, the N-1 pairs of neighbours are connected by
 * copies of the transfers drawn between Begin and End, and everything from
 * outside arrives at the first or leaves from the last.
 *
 * Four blocks inside carry the parts (CreateTransportSubSystemAction makes all
 * four when the sub-system is made):
 *
 *   Begin    a compartment; the first in the chain. Its initial condition and
 *            its decay setting are every element's.
 *   End      a compartment; the last in the chain.
 *   N        an expression, unitless: how many compartments the chain has.
 *            TransportNumber; it has to be known before the run starts.
 *   Counter  an expression with no equation of its own: inside a transfer
 *            between Begin and End it is the number of the element that
 *            transfer is leaving, 1 for Begin. TransportElementCounter.
 *
 * and a fifth that may be added any number of times:
 *
 *   Operation  the sum or the mean over the chain -- of all of it, or of the
 *              stretch a caller asks for: `Op(x)` reads the element at a
 *              fraction x of the way along, `Op(a, b)` sums or averages the
 *              stretch from a to b. TransportOperation.
 *
 * This file is what the editor needs: which sub-systems are transports, which
 * blocks are their parts, what N comes to, and what is wrong with one. The
 * run itself is in ../sim/transport.js, which unrolls the chain into ordinary
 * compartments and transfers before the model is built, so that nothing in
 * the builder, the solvers or the results has to know a chain from a model.
 */

import { parse, ParseError, tokenize } from '../parser/parser.js';
import { emit, buildFunction } from '../parser/compile.js';
import { FUNCTIONS } from '../parser/functions.js';
import { qualifiedName, systemOf, resolveReference } from './systems.js';
import { parentListName } from './indexlists.js';

/** Which parts of a transport each kind of block can be. */
export const ROLES = {
	compartment: ['begin', 'end'],
	expression: ['number', 'counter', 'operation'],
};

/** What a transport operation works out over the chain. */
export const OPERATIONS = ['sum', 'mean'];

/** How a transport operation is read: as a value, or called with 1 or 2 positions. */
export const ARGUMENTS = ['all', 'point', 'range'];

/** What each part is called in the interface. Ecolego's own labels. */
export const ROLE_LABEL = {
	begin: 'Transport begin',
	end: 'Transport end',
	number: 'Transport number',
	counter: 'Transport counter',
	operation: 'Transport operation',
};

/** One line on each, for the panels. */
export const ROLE_BLURB = {
	begin: 'The first compartment of the chain. Its initial condition and its '
		+ 'decay setting are every element’s.',
	end: 'The last compartment of the chain. Everything that leaves the chain '
		+ 'leaves from here.',
	number: 'How many compartments the chain has. Worked out before the run '
		+ 'starts, so it may only use numbers and parameters.',
	counter: 'Inside a transfer between Begin and End, the number of the element '
		+ 'the transfer leaves: 1 at Begin. It has a value only inside the transport.',
	operation: 'The sum or the mean over the chain’s compartments.',
};

/** The block's part in a transport, or null. */
export function roleOf(block) {
	return block?.transport ?? null;
}

/** The transport sub-systems a project declares, as paths. */
export function transportPaths(project) {
	const list = project?.transports ?? [];
	return [...list].map((p) => (typeof p === 'string' ? p : p?.name)).filter(Boolean);
}

/** Whether a sub-system is a transport. */
export function isTransport(project, path) {
	return !!path && transportPaths(project).includes(path);
}

/**
 * The parts of one transport, by role. Every candidate is listed as well as
 * the one taken, so a panel can say "two Begins" rather than pick one quietly.
 *
 * Only the sub-system's own blocks count: Ecolego does not let a sub-system be
 * moved into a transport, so there is nothing deeper to look in.
 */
export function transportParts(project, path) {
	const own = (blocks) => (blocks ?? []).filter((b) => systemOf(b) === path);
	const withRole = (blocks, role) => own(blocks).filter((b) => roleOf(b) === role);
	const begins = withRole(project?.compartments, 'begin');
	const ends = withRole(project?.compartments, 'end');
	const numbers = withRole(project?.expressions, 'number');
	const counters = withRole(project?.expressions, 'counter');
	const operations = withRole(project?.expressions, 'operation');
	return {
		path,
		begin: begins[0] ?? null, begins,
		end: ends[0] ?? null, ends,
		number: numbers[0] ?? null, numbers,
		counter: counters[0] ?? null, counters,
		operations,
	};
}

/**
 * Whether a block may read a transport's element counter: only a block in
 * the same transport.
 *
 * The counter is not an expression of the model's. Ecolego's
 * The element counter is an ordinary entry block -- not a `TransportNumber
 * extends Expression` -- and what it answers, `getCurrentElement`, is which
 * pair of neighbours the chain is being assembled for, which is a question
 * that only has an answer inside the chain. Outside it the value used to be
 * 1, which is not a number anything meant; now it is not a value at all.
 *
 * @param counter the counter block, or its qualified name
 * @param reader the block reading it, or its qualified name
 */
export function counterVisibleTo(project, counter, reader) {
	const c = typeof counter === 'string' ? findBlockLoose(project, counter) : counter;
	if (!c || roleOf(c) !== 'counter') return true;
	const home = transportOf(project, c);
	if (!home) return true;
	const r = typeof reader === 'string' ? findBlockLoose(project, reader) : reader;
	return !!r && systemOf(r) === home;
}

/**
 * Every block whose equations name any of `targets`: expressions, the rates of
 * transfers and sources, and a compartment's initial inventory, per entry as
 * well as at the block level. The same walk `edit.referencesTo` makes, kept
 * here because edit.js imports this file and not the other way about.
 *
 * **Once for all the targets, not once per target.** This was written the
 * other way -- one name at a time -- and it rebuilt the set of every block's
 * qualified name and re-tokenised every equation in the model for each of
 * them. A model with 58 transports therefore made 58 passes over 3,421
 * transfers, which was 840 ms of a scan the editor runs on every edit. The
 * targets are known up front, so the pass happens once and the answers come
 * out in a map.
 *
 * @param {Set<string>|string[]} targets  qualified names
 * @returns {Map<string, object[]>} one entry per target, readers in model order
 */
function readersOfEach(project, targets) {
	const want = targets instanceof Set ? targets : new Set(targets);
	const out = new Map();
	for (const t of want) out.set(t, []);
	if (!want.size) return out;

	const known = new Set();
	for (const key of Object.keys(project ?? {})) {
		if (!Array.isArray(project[key])) continue;
		for (const b of project[key]) if (b && typeof b === 'object' && b.name) known.add(qualifiedName(b));
	}
	const has = (n) => known.has(n);
	/** Which of the targets this text names, from where it is written. */
	const named = (text, system, into) => {
		if (typeof text !== 'string' || !text) return;
		try {
			for (const tok of tokenize(text)) {
				if (tok.type !== 'ident') continue;
				const q = resolveReference(tok.value, system, has);
				if (q != null && want.has(q)) into.add(q);
			}
		} catch { /* an equation that will not parse names nothing */ }
	};
	const scan = (blocks, key) => {
		for (const b of blocks ?? []) {
			const system = systemOf(b);
			const hits = new Set();
			named(b[key], system, hits);
			for (const e of b.entries ?? []) named(e[key], system, hits);
			for (const q of hits) out.get(q).push(b);
		}
	};
	scan(project?.expressions, 'equation');
	scan(project?.transfers, 'rate');
	scan(project?.inflows, 'rate');
	scan(project?.compartments, 'initial');
	scan(project?.compartments, 'dydt');
	return out;
}

/** A block by qualified name, over every collection, without edit.js. */
function findBlockLoose(project, name) {
	for (const key of Object.keys(project ?? {})) {
		if (!Array.isArray(project[key])) continue;
		const b = project[key].find((x) => x && typeof x === 'object' && qualifiedName(x) === name);
		if (b) return b;
	}
	return null;
}

/**
 * The transport a block is a part of, or null: a block with a role, sitting
 * directly in a sub-system that is a transport.
 */
export function transportOf(project, block) {
	if (!roleOf(block)) return null;
	const path = systemOf(block);
	return isTransport(project, path) ? path : null;
}

/**
 * The transfers drawn between Begin and End, in either direction: the ones the
 * chain is made of. the rule for a chain’s internal connections names exactly
 * these -- source Begin and target End, or the reverse.
 */
export function internalTransfers(project, parts) {
	const b = parts.begin ? qualifiedName(parts.begin) : null;
	const e = parts.end ? qualifiedName(parts.end) : null;
	if (!b || !e) return [];
	return (project?.transfers ?? []).filter((t) => (
		(t.from === b && t.to === e) || (t.from === e && t.to === b)
	));
}

/**
 * The transport operations a caller has to *call*: the ones that take a
 * position, or two, and so have no value of their own to refer to by name.
 * The equation checker accepts a call to these as it accepts a call to a
 * lookup table with an argument.
 */
export function calledOperations(project) {
	return (project?.expressions ?? [])
		.filter((b) => roleOf(b) === 'operation' && (b.argument ?? 'all') !== 'all'
			&& isTransport(project, systemOf(b)));
}

/**
 * What an expression comes to before the run starts, or null when it cannot be
 * known then.
 *
 * Numbers, arithmetic, the built-in functions, parameters, and other
 * expressions that pass the same test -- and nothing else: no compartment (it
 * has no value yet), no transfer, no lookup table, no block indexed by
 * anything. A parameter indexed by the scenario list is read at the active
 * scenario, which is the one value it has in a run.
 *
 * How many cells a transport has may be written as a literal or as a
 * reference to a parameter, and is otherwise settled when the run starts.
 * Here the run starts with the state vector already laid out, so N has to be
 * settled before it, and an arithmetic of parameters is as settled as a
 * literal.
 *
 * `time` reads as the start time, which is when Ecolego evaluates it.
 */
export function constantValue(project, block, kind, seen = new Set()) {
	if (!block) return null;
	const dims = block.index_lists ?? [];
	if (kind === 'parameter') {
		const v = Number(constantEntry(project, block, 'value', dims));
		return Number.isFinite(v) ? v : null;
	}
	if (kind !== 'expression') return null;
	const text = constantEntry(project, block, 'equation', dims);
	if (text == null) return null;
	let ast;
	try {
		ast = parse(String(text));
	} catch (e) {
		if (e instanceof ParseError) return null;
		throw e;
	}
	const system = systemOf(block);
	const own = qualifiedName(block);
	const find = (q) => {
		const p = (project?.parameters ?? []).find((b) => qualifiedName(b) === q);
		if (p) return { block: p, kind: 'parameter' };
		const x = (project?.expressions ?? []).find((b) => qualifiedName(b) === q);
		return x ? { block: x, kind: 'expression' } : null;
	};
	let ok = true;
	const js = emit(ast, (name, indices) => {
		if (!ok) return '0';
		if (indices && indices.length) { ok = false; return '0'; }
		const q = resolveReference(name, system, (n) => !!find(n));
		if (!q || q === own || seen.has(q)) { ok = false; return '0'; }
		const target = find(q);
		const v = constantValue(project, target.block, target.kind, new Set([...seen, own]));
		if (v == null) { ok = false; return '0'; }
		return v < 0 ? `(${v})` : String(v);
	});
	if (!ok) return null;
	const sim = project?.simulation ?? {};
	const start = Number(sim.start_time ?? 0);
	const end = Number(sim.end_time ?? 0);
	let v;
	try {
		v = buildFunction([], `return ${js};`)(FUNCTIONS, { t: start, startTime: start, endTime: end });
	} catch {
		return null;
	}
	return Number.isFinite(v) ? v : null;
}

/**
 * A block's value for the run, when it has one: its default, or -- indexed by
 * the scenario list alone -- its entry at the active scenario. Indexed by
 * anything else it holds several values, and this answers null.
 */
function constantEntry(project, block, key, dims) {
	if (!dims.length) return block[key];
	const scenarioLists = new Set(scenarioDims(project));
	if (!dims.every((d) => scenarioLists.has(d))) return null;
	const active = activeScenarioName(project);
	const entry = (block.entries ?? []).find((e) => e && Object.prototype.hasOwnProperty.call(e, key)
		&& Object.values(e.index ?? {}).every((i) => i === active));
	return entry ? entry[key] : block[key];
}

/** The scenario list and every sub-set or mapping of it, by name. */
function scenarioDims(project) {
	const lists = project?.index_lists ?? [];
	const root = lists.find((l) => l.for_scenarios)?.name ?? null;
	if (!root) return [];
	const byName = new Map(lists.map((l) => [l.name, l]));
	return lists.filter((l) => {
		let at = l.name;
		for (let i = 0; at && i <= byName.size; i++) {
			if (at === root) return true;
			const list = byName.get(at);
			at = parentListName(list);
		}
		return false;
	}).map((l) => l.name);
}

function activeScenarioName(project) {
	const list = (project?.index_lists ?? []).find((l) => l.for_scenarios);
	const names = (list?.indices ?? [])
		.map((i) => (typeof i === 'string' ? { name: i, enabled: true } : i))
		.filter((i) => i?.name && i.enabled !== false)
		.map((i) => i.name);
	if (!names.length) return null;
	return names.includes(project?.scenario) ? project.scenario : names[0];
}

/**
 * How many compartments a transport's chain has, or why that cannot be said.
 *
 * an integer cast: the value is truncated towards zero, so 4.9 is four
 * elements. Fewer than one is refused -- a chain of no compartments has
 * nowhere for its inflows to go -- as is anything the run cannot know before
 * it starts.
 *
 * @returns {{n: number|null, value: number|null, why: string|null}}
 */
export function transportNumber(project, parts) {
	const N = parts.number;
	if (!N) {
		return {
			n: null, value: null,
			why: `'${parts.path}' has no transport number, so the length of its chain is `
				+ 'not known. Add one (an expression with the part "number").',
		};
	}
	const name = qualifiedName(N);
	const value = constantValue(project, N, 'expression');
	if (value == null) {
		return {
			n: null, value: null,
			why: `'${name}' cannot be worked out before the run starts. The number of `
				+ 'compartments in a transport may use numbers, parameters and expressions '
				+ 'made of those, and nothing that changes over the run.',
		};
	}
	const n = Math.trunc(value);
	if (n < 1) {
		return {
			n: null, value,
			why: `'${name}' comes to ${value}, and a transport needs at least one `
				+ 'compartment.',
		};
	}
	return { n, value, why: null };
}

/** Whether two blocks are indexed by the same lists, in any order. */
function sameDims(a, b) {
	const x = [...(a?.index_lists ?? [])].sort();
	const y = [...(b?.index_lists ?? [])].sort();
	return x.length === y.length && x.every((d, i) => d === y[i]);
}

/**
 * What is wrong with the transports in a model, for the problem strip: a
 * chain that cannot be built. Each finding names the sub-system and, where
 * there is one, the block it is about.
 *
 * @returns {Array<{path: string, name: string|null, message: string}>}
 */
export function transportProblems(project) {
	const out = [];
	const paths = transportPaths(project);
	const partsOf = new Map(paths.map((path) => [path, transportParts(project, path)]));
	// Every counter in the model at once: one pass over every equation,
	// rather than one pass per chain. See `readersOfEach`.
	const counters = new Map();
	for (const [path, parts] of partsOf) {
		for (const counter of parts.counters) counters.set(qualifiedName(counter), counter);
	}
	const readers = readersOfEach(project, new Set(counters.keys()));
	for (const path of paths) {
		const parts = partsOf.get(path);
		const say = (name, message) => out.push({ path, name, message });
		// The counter read from outside its chain, named by the block reading
		// it: the equation checker says the same under the box, and the
		// builder refuses the model; this is the strip's line.
		for (const counter of parts.counters) {
			const cq = qualifiedName(counter);
			for (const reader of readers.get(cq) ?? []) {
				if (counterVisibleTo(project, counter, reader)) continue;
				say(qualifiedName(reader),
					`'${qualifiedName(reader)}' reads '${cq}', the element counter of '${path}', `
					+ 'from outside the transport. The counter counts the compartments of the '
					+ 'chain and has a value only inside it.');
			}
		}
		if (parts.begins.length !== 1) {
			say(parts.begins[1] ? qualifiedName(parts.begins[1]) : null,
				parts.begins.length
					? `'${path}' has ${parts.begins.length} Begin compartments; a transport has `
						+ 'exactly one.'
					: `'${path}' has no Begin compartment. A transport is a chain from its `
						+ 'Begin to its End.');
		}
		if (parts.ends.length !== 1) {
			say(parts.ends[1] ? qualifiedName(parts.ends[1]) : null,
				parts.ends.length
					? `'${path}' has ${parts.ends.length} End compartments; a transport has `
						+ 'exactly one.'
					: `'${path}' has no End compartment. A transport is a chain from its `
						+ 'Begin to its End.');
		}
		if (parts.numbers.length > 1) {
			say(qualifiedName(parts.numbers[1]),
				`'${path}' has ${parts.numbers.length} transport numbers; a chain has one length.`);
		}
		if (parts.counters.length > 1) {
			say(qualifiedName(parts.counters[1]),
				`'${path}' has ${parts.counters.length} transport counters; one is enough, since `
				+ 'both count the same thing.');
		}
		const { why } = transportNumber(project, parts);
		if (why) say(parts.number ? qualifiedName(parts.number) : null, why);
		if (parts.begin && parts.end && !sameDims(parts.begin, parts.end)) {
			say(qualifiedName(parts.end),
				`'${qualifiedName(parts.end)}' is not indexed by the same lists as `
				+ `'${qualifiedName(parts.begin)}'. Every compartment of the chain is one `
				+ 'compartment repeated, so Begin and End must match.');
		}
		for (const op of parts.operations) {
			if (parts.begin && !sameDims(op, parts.begin)) {
				say(qualifiedName(op),
					`'${qualifiedName(op)}' is not indexed by the same lists as `
					+ `'${qualifiedName(parts.begin)}'. An operation over the chain has a `
					+ 'value wherever the chain has one.');
			}
		}
	}
	return out;
}
