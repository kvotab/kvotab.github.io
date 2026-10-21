/**
 * Where a value that is not a number came from.
 *
 * A run that stops on a NaN or an infinity used to say when and nothing else:
 * the derivative of some state was not a number, and which state, and why, was
 * left to the reader -- who had a model of thousands of equations and an error
 * that named none of them. Everything needed to say more is at hand when it
 * happens. The state the solver held is known, so the equations can be worked
 * out once more there, and a value that is not a number can be followed back
 * the way it came: from the compartments whose derivative it reached, through
 * the transfers that carried it there, and down through each equation a part at
 * a time, to the one operation that made it out of numbers -- zero divided by
 * zero, the log of a negative, an overflow -- and the values that operation
 * read.
 *
 * It is followed by value, not by name. A block that holds one index which is
 * not a number and forty-eight that are is followed only where it is read at
 * that one; a conditional is followed down the branch it took; and a part of
 * an equation is worked out by the code the derivative runs (`equationAt` in
 * ./builder.js), so what this says went wrong is what did. Only after a run has
 * failed, so a model pays nothing for it.
 *
 * Its Python and Julia twins are `kompartment/engine/nonfinite.py` and
 * `src/engine/nonfinite.jl`: an engine on this machine says the same thing, in
 * the same words.
 */

import { tupleByList, describeTuple } from './builder.js';

/** The algebraic slots the assembly of the derivative reads: see `readByDerivative` in ./localsens.js. */
const readByAssembly = (a) => a.kind === 'transfer' || a.kind === 'inflow' || a.kind === 'compartment:dydt'
	|| a.kind === 'waste_package' || a.kind === 'farfield' || a.kind === 'running_mean:target'
	|| /^(waste_package|event|farfield):/.test(a.kind);

/** How deep one value is followed: an equation that reads another, which reads another, ... */
const MOST_STEPS = 500;
/** How many elements are followed back before the rest are only counted. */
const MOST_FOLLOWED = 2000;
/** How many names a list in the message carries before it says how many more. */
const MOST_NAMED = 3;
/** How many of the values an operation read are written out. */
const MOST_READS = 6;
/** The longest a part of an equation is quoted at; longer, its middle is left out. */
const LONGEST_PART = 240;

const finite = Number.isFinite;

/**
 * Where the derivative at `(t, y)` stops being a number, and why.
 *
 * Null when it is a number throughout -- the failure was somewhere the solver
 * went that this state does not show -- and when the system cannot be taken
 * apart (one handed in by a caller with equations of its own).
 *
 * @returns {null | {
 *   t: number,
 *   states: {name: string, kind: string, count: number, index: object|null}[],
 *   stateCount: number,
 *   flows: {name: string, kind: string, count: number}[],
 *   root: object|null,
 *   others: string[],
 * }}
 */
export function nonFiniteAt(system, t, y) {
	const at = evaluated(system, t, y);
	if (!at) return null;
	const { L, state, d } = at;
	const states = groupBy(L.states, L.nstate, (i) => !finite(d[i]) || !finite(state[i]));
	if (!states.length) return null;

	// From the flows the assembly reads, in the order they are worked out.
	const { flows, blocks } = fromAssembly(at);
	const roots = blocks.map((b) => describeRoot(b, at));
	const [root = null, ...rest] = roots;
	const others = [...new Set(rest.map((r) => r.name))].filter((name) => name !== root?.name);
	return {
		t,
		states,
		stateCount: states.reduce((s, g) => s + g.count, 0),
		flows,
		root,
		others,
	};
}

/**
 * What a run would trip over, said before one is run: every block whose value
 * at the start is not a number of its own making, with what it comes from.
 * The ones the run reads -- its compartments' derivatives do -- stop it at its
 * first step, and say so and through which flows; the ones only a result
 * reads let it go on. A compartment whose initial value is not a number stops
 * it before that. `{block, message, stops}` each, in the order the equations
 * are worked out, for the strip's warnings at the start of a run.
 */
export function startWarnings(system, t0, y0) {
	const L = system?.layout;
	if (!L) return [];
	const out = [];
	for (const g of groupBy(L.states, L.nstate, (i) => !finite(y0[i]))) {
		if (g.kind !== 'compartment') continue;
		out.push({
			block: g.name,
			stops: true,
			message: `Its initial value comes to ${number(y0[g.at])}${whereText(g, L)}, so a run cannot start.`,
		});
	}
	if (out.length) return out;
	const at = evaluated(system, t0, y0);
	if (!at) return out;
	const { blocks, flowsOf } = fromAssembly(at);
	const stopping = new Set(blocks.map((b) => b.first.k));
	for (const b of blocks) {
		const r = describeRoot(b, at);
		const via = [...(flowsOf.get(b.first.k) ?? [])];
		out.push({
			block: r.name,
			stops: true,
			message: `${rootSentence(r, true)} The run reads it${via.length
				? `, through ${via.length === 1 ? 'the transfer' : 'the transfers'} ${list(via)},` : ''} `
				+ 'so it will stop at its first step.',
		});
	}
	for (const b of fromTheRest(at, stopping)) {
		const r = describeRoot(b, at);
		out.push({
			block: r.name,
			stops: false,
			message: `${rootSentence(r, true)} Only results read it, so a run goes on, `
				+ `with ${r.count > 1 ? 'these values' : 'this value'} at its first point.`,
		});
	}
	return out;
}

/**
 * The equations worked out at `(t, y)`, and a way to follow a value that is
 * not a number back through them. Null when the system cannot be taken apart
 * (one handed in by a caller with equations of its own) or will not evaluate.
 */
function evaluated(system, t, y) {
	const L = system?.layout;
	if (!L || typeof system.equationAt !== 'function') return null;
	const n = L.nstate;
	if (!(y?.length >= n)) return null;
	const state = y.length === n ? y : y.subarray(0, n);
	const d = new Float64Array(n);
	let X;
	try {
		system.dydt(t, state, d);
		// Every slot, not only those the derivative runs: a block the
		// derivative reads is in both, and its value is the same in either.
		X = system.evaluateAlgebraic(t, state);
	} catch {
		return null;
	}

	const algebraic = L.algebraic;
	const owner = new Int32Array(Math.max(1, L.nalg)).fill(-1);
	algebraic.forEach((a, k) => { if (a.width > 0) owner.fill(k, a.base, a.base + a.width); });
	const at = (offset) => {
		const k = owner[offset] ?? -1;
		return k < 0 ? null : { k, off: offset - algebraic[k].base };
	};

	// Followed once per element, however many of the flows read it.
	const memo = new Map();
	const rootOf = (k, off, depth = 0) => {
		const key = k * 4294967296 + off;
		if (memo.has(key)) return memo.get(key) ?? { k, off };
		memo.set(key, null);
		const found = follow(k, off, depth);
		memo.set(key, found);
		return found;
	};
	const follow = (k, off, depth) => {
		const here = { k, off };
		if (depth > MOST_STEPS) return here;
		const a = algebraic[k];
		// A block that remembers has no equation; what it is not a number of,
		// if anything now, is its target.
		const target = a.recorder?.aux?.target;
		if (target && a.recorder.kind !== 'trigger') {
			const next = !finite(X[target.base + off]) ? at(target.base + off) : null;
			return next ? rootOf(next.k, next.off, depth + 1) : here;
		}
		let eq = null;
		try {
			eq = system.equationAt(k, off);
		} catch {
			eq = null;
		}
		if (!eq) return here;
		const part = innermost(eq, t, state);
		if (!part) {
			// The equation comes to a number and the slot does not: the
			// slot is the rate times an availability, and it is that.
			for (const op of Object.values(a.availability?.operands ?? {})) {
				const next = !finite(X[op.base + off]) ? at(op.base + off) : null;
				if (next) return rootOf(next.k, next.off, depth + 1);
			}
			return here;
		}
		if (part.node.type === 'ref') {
			let read = null;
			try {
				read = eq.read(part.node);
			} catch {
				read = null;
			}
			const next = read?.array === 'X' ? at(read.offset) : null;
			if (next) return rootOf(next.k, next.off, depth + 1);
			return { ...here, eq, part, read };
		}
		return { ...here, eq, part };
	};

	return { L, t, state, d, X, algebraic, rootOf };
}

/**
 * The blocks that make a value that is not a number which the assembly of the
 * derivative reads -- followed back from every flow, rate and term it reads
 * that is not one, in the order they are worked out -- and the flows: which
 * transfers and inflows carry one, and which of them each block's reach.
 */
function fromAssembly(at) {
	const { algebraic, X, rootOf } = at;
	const flowsSeen = new Map();
	const flowsOf = new Map();
	const roots = [];
	let followed = 0;
	algebraic.forEach((a, k) => {
		if (!readByAssembly(a)) return;
		const flow = a.kind === 'transfer' || a.kind === 'inflow' ? blockOf(a.name) : null;
		for (let off = 0; off < a.width; off++) {
			if (finite(X[a.base + off])) continue;
			if (flow) {
				const seen = flowsSeen.get(flow) ?? { name: flow, kind: a.kind, count: 0 };
				seen.count++;
				flowsSeen.set(flow, seen);
			}
			if (followed++ >= MOST_FOLLOWED) continue;
			const r = rootOf(k, off);
			roots.push(r);
			if (flow && a.kind === 'transfer') {
				if (!flowsOf.has(r.k)) flowsOf.set(r.k, new Set());
				flowsOf.get(r.k).add(flow);
			}
		}
	});
	return { flows: [...flowsSeen.values()], blocks: byRootBlock(roots), flowsOf };
}

/**
 * The blocks that make a value that is not a number which only results read:
 * every other block's slots that are not numbers, followed back the same way,
 * less the blocks `stopping` already has.
 */
function fromTheRest(at, stopping) {
	const { algebraic, X, rootOf } = at;
	const roots = [];
	let followed = 0;
	algebraic.forEach((a, k) => {
		// The slots behind a block -- a recorder's target, an availability --
		// answer for it: the block's own slot is the one to follow.
		if (a.hidden || readByAssembly(a)) return;
		for (let off = 0; off < a.width; off++) {
			if (finite(X[a.base + off])) continue;
			if (followed++ >= MOST_FOLLOWED) return;
			const r = rootOf(k, off);
			if (!stopping.has(r.k)) roots.push(r);
		}
	});
	return byRootBlock(roots);
}

/** One root per block, at its first element, with which elements it has, in the order of the blocks. */
function byRootBlock(roots) {
	const byBlock = new Map();
	for (const r of roots) {
		const had = byBlock.get(r.k);
		if (!had) byBlock.set(r.k, { first: r, offs: new Set([r.off]) });
		else {
			had.offs.add(r.off);
			if (r.off < had.first.off) had.first = r;
		}
	}
	return [...byBlock.entries()].sort(([a], [b]) => a - b).map(([, b]) => b);
}

/**
 * The node of an equation that is not a number while every operand it was
 * worked out from is one -- the operation that made it -- and its operands.
 * Followed down the operand that is not a number, and down the branch a
 * conditional took. Null when the equation comes to a number after all.
 */
function innermost(eq, t, y) {
	const value = (node) => eq.valueOf(node, t, y);
	let node = eq.ast;
	let v = value(node);
	if (v === undefined || finite(v)) return null;
	for (;;) {
		const parts = operands(node, value);
		const next = parts.find((p) => p.value !== undefined && !finite(p.value));
		if (!next) return { node, value: v, operands: parts };
		node = next.node;
		v = next.value;
	}
}

/** The operands a node was worked out from, with their values: only the branch a conditional took. */
function operands(node, value) {
	const of = (n) => ({ node: n, value: value(n) });
	switch (node.type) {
		case 'unary':
			return [of(node.operand)];
		case 'binary':
			return [of(node.left), of(node.right)];
		case 'cond': {
			const test = of(node.test);
			if (test.value === undefined) return [test];
			return [test, of(test.value !== 0 ? node.then : node.otherwise)];
		}
		case 'call': {
			const args = node.args ?? [];
			if (node.name === 'if' && args.length >= 2) {
				const test = of(args[0]);
				if (test.value === undefined) return [test];
				const taken = test.value !== 0 ? args[1] : args[2];
				return taken ? [test, of(taken)] : [test];
			}
			return args.map(of);
		}
		default:
			return [];
	}
}

/** Where a value that is not a number starts, in the terms a message needs. */
function describeRoot({ first, offs }, { L, X, state: y, t }) {
	const a = L.algebraic[first.k];
	const name = blockOf(a.name);
	const index = a.dims.length ? tupleByList(L.indexSpace, a.dims, first.off) : null;
	const value = X[a.base + first.off];
	const root = { name, kind: a.kind, index, count: offs.size, value, part: null, source: null };
	const { eq, part, read } = first;
	if (!part) return root;
	if (part.node.type === 'ref' && read) {
		// A state or a parameter that is not a number: what the equation read.
		const holder = read.array === 'y' ? entryAt(L.states, read.offset)
			: read.array === 'P' ? entryAt(L.parameters, read.offset) : null;
		if (holder) {
			const off = read.offset - holder.base;
			root.source = {
				name: blockOf(holder.name),
				kind: read.array === 'y' ? (holder.kind ?? 'compartment') : 'parameter',
				index: holder.dims?.length ? tupleByList(L.indexSpace, holder.dims, off) : null,
				value: part.value,
			};
			return root;
		}
	}
	root.part = {
		text: equationText(part.node),
		worked: workedText(part.node, part.operands, part.value),
		reads: readsOf(part.node, eq, t, y),
	};
	return root;
}

/** The references inside a part, each once, with the value it read. */
function readsOf(node, eq, t, y) {
	const out = new Map();
	const walk = (n) => {
		if (n.type === 'ref') {
			const text = equationText(n);
			if (!out.has(text)) out.set(text, eq.valueOf(n, t, y));
			return;
		}
		for (const c of children(n)) walk(c);
	};
	walk(node);
	return [...out.entries()].map(([text, value]) => ({ text, value }));
}

function children(n) {
	switch (n.type) {
		case 'unary': return [n.operand];
		case 'binary': return [n.left, n.right];
		case 'cond': return [n.test, n.then, n.otherwise];
		case 'call': return n.args ?? [];
		default: return [];
	}
}

/** The run's states that are not numbers, a block at a time, in the order of the state vector. */
function groupBy(entries, n, bad) {
	const out = [];
	for (const s of entries ?? []) {
		let count = 0;
		let first = -1;
		for (let i = 0; i < s.width; i++) {
			const at = s.base + i;
			if (at >= n || !bad(at)) continue;
			if (first < 0) first = i;
			count++;
		}
		if (!count) continue;
		out.push({
			name: blockOf(s.name), kind: s.kind ?? 'compartment', count, first, at: s.base + first,
			dims: s.dims ?? [],
		});
	}
	return out;
}

/** ` at <index>` of a group's first, and how many more, for a block with indices. */
function whereText(g, L) {
	if (!g.dims.length) return '';
	const more = g.count - 1;
	return ` at ${describeTuple(tupleByList(L.indexSpace, g.dims, g.first))}`
		+ (more ? ` (and ${more} more of its indices)` : '');
}

/** The layout entry an offset of its array falls in. */
function entryAt(entries, offset) {
	for (const e of entries ?? []) {
		if (offset >= e.base && offset < e.base + e.width) return e;
	}
	return null;
}

/** A slot of a block's own -- `T#limit`, `M#target` -- answers as the block. */
const blockOf = (name) => String(name).split('#')[0];

// --- the words ------------------------------------------------------------------

/**
 * The message for a run that stopped on a value that is not a number, said
 * from what `nonFiniteAt` found.
 */
export function nonFiniteMessage(found, L, step = null) {
	const lines = step
		? [`The simulation produced a value that is not a number at t=${String(step.from)}.`,
			`The state it held there gives numbers; a step of ${number(step.h)} past it does not.`]
		: [`The simulation produced a value that is not a number at t=${String(found.t)}.`];
	if (found.root) lines.push(rootSentence(found.root, false));
	lines.push(reachText(found, L));
	if (found.others.length) {
		const [first, ...rest] = found.others;
		lines.push(rest.length
			? `${first} and ${rest.length} more ${rest.length === 1 ? 'block' : 'blocks'} start one of their own as well.`
			: `${first} starts one of its own as well.`);
	}
	return lines.join(' ');
}

/**
 * Where a value that is not a number starts and what made it. In a run's
 * message the block is named (`It starts in X [index]: ...`); in a warning at
 * the start the strip has named it already, so the sentence begins with its
 * value (`Comes to NaN at index ...: ...`).
 */
function rootSentence(r, atStart) {
	const more = r.count - 1;
	const others = more ? ` (and ${more} more of its indices)` : '';
	const lead = atStart
		? `Comes to ${number(r.value)} at the start${r.index ? ` at ${describeTuple(r.index)}` : ''}${others}`
		: `It starts in ${r.name}${indexText(r.index)}${others}`;
	if (r.source) {
		const s = r.source;
		const what = s.kind === 'parameter' ? `the parameter ${s.name}${indexText(s.index)}, which is`
			: s.kind === 'compartment' ? `the compartment ${s.name}${indexText(s.index)}, which holds`
				: `the state ${s.name}${indexText(s.index)}, which is`;
		return atStart
			? `${lead}: it reads ${what} ${number(s.value)}.`
			: `It starts in ${what} ${number(s.value)}, read by ${r.name}${indexText(r.index)}${others}.`;
	}
	if (r.part) return `${lead}: ${r.part.text} comes to ${r.part.worked}${readsText(r.part.reads)}.`;
	return atStart ? `${lead}.` : `${lead}, which comes to ${number(r.value)}.`;
}

/** Which compartments it reached, and through which flows. */
function reachText(found, L) {
	const { states, stateCount, flows } = found;
	const named = states.map((s) => `${s.name}${states.length === 1 && s.count === 1 && s.dims.length
		? indexText(tupleByList(L.indexSpace, s.dims, s.first)) : ''}`);
	const allCompartments = states.every((s) => s.kind === 'compartment');
	const noun = allCompartments ? 'compartment' : 'block';
	let text = states.length === 1
		? `It reaches the ${noun} ${named[0]}${stateCount > 1 ? ` (${stateCount} states)` : ''}`
		: `It reaches ${states.length} ${noun}s, ${stateCount} states in all: ${list(named)}`;
	if (flows.length) {
		const transfers = flows.filter((f) => f.kind === 'transfer').map((f) => f.name);
		const inflows = flows.filter((f) => f.kind === 'inflow').map((f) => f.name);
		const parts = [];
		if (transfers.length) parts.push(`${transfers.length === 1 ? 'the transfer' : 'the transfers'} ${list(transfers)}`);
		if (inflows.length) parts.push(`${inflows.length === 1 ? 'the inflow' : 'the inflows'} ${list(inflows)}`);
		text += `, through ${parts.join(' and ')}`;
	}
	return `${text}.`;
}

/** Up to three names, then how many more. */
function list(names) {
	if (names.length <= MOST_NAMED) {
		return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
	}
	return `${names.slice(0, MOST_NAMED).join(', ')} and ${names.length - MOST_NAMED} more`;
}

/** What an operation read, the values most likely to be the cause first. */
function readsText(reads) {
	if (!reads.length) return '';
	const telling = (v) => v === undefined || !finite(v) || v <= 0;
	const shown = reads.length <= MOST_READS ? reads
		: [...reads.filter((r) => telling(r.value)), ...reads.filter((r) => !telling(r.value))].slice(0, MOST_READS);
	const keep = new Set(shown);
	const ordered = reads.filter((r) => keep.has(r));
	const items = ordered.map((r) => `${r.text} = ${r.value === undefined ? '?' : number(r.value)}`);
	const more = reads.length - ordered.length;
	if (more) return `, with ${items.join(', ')} and ${more} more`;
	return `, with ${items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`}`;
}

const indexText = (index) => (index && Object.keys(index).length ? ` [${describeTuple(index)}]` : '');

/** A value as it is shown: four figures, written as JavaScript writes a number. */
export function number(v) {
	if (!finite(v)) return String(v);
	if (v === 0) return '0';
	return String(Number(v.toExponential(3)));
}

/** An operation with its operands' values in place of their equations: `0/0`, `log(0)`. */
function workedText(node, parts, value) {
	const v = (i) => {
		const x = parts[i]?.value;
		if (x === undefined) return '?';
		const s = number(x);
		return x < 0 ? `(${s})` : s;
	};
	switch (node.type) {
		case 'binary':
			return `${v(0)}${opText(node.op)}${v(1)}${overflows(parts, value) ? ', too large for a number' : ''}`;
		case 'unary':
			return `-${v(0)}`;
		case 'call':
			if (!parts.length) return number(value);
			return `${node.name}(${parts.map((_, i) => number(parts[i].value ?? NaN)).join(', ')})${
				overflows(parts, value) ? ', too large for a number' : ''}`;
		default:
			return number(value);
	}
}

/** Whether numbers went in and an infinity came out: an overflow rather than a domain error. */
const overflows = (parts, value) => Math.abs(value) === Infinity
	&& parts.every((p) => p.value !== undefined && finite(p.value))
	&& !parts.some((p) => p.value === 0);

const opText = (op) => (op === '*' || op === '/' || op === '^' ? op : ` ${op} `);

// --- equations back to text ---------------------------------------------------------

/** How tightly each kind of node binds, for the brackets. */
const PRECEDENCE = {
	'||': 1, '&&': 2, '==': 3, '~=': 3, '<': 4, '<=': 4, '>': 4, '>=': 4,
	'+': 5, '-': 5, '*': 6, '/': 6,
};
const UNARY = 7;
const POWER = 8;
const ATOM = 10;

function precedenceOf(node) {
	switch (node.type) {
		case 'binary': return node.op === '^' ? POWER : PRECEDENCE[node.op] ?? 0;
		case 'unary': return UNARY;
		case 'cond': return 0;
		case 'num': return node.value < 0 ? UNARY : ATOM;
		default: return ATOM;
	}
}

/**
 * A tree written back out as an equation: brackets only where the parser needs
 * them, names as they were written, numbers as JavaScript writes them. A part
 * longer than a message can carry loses its middle.
 */
export function equationText(node) {
	const text = write(node);
	if (text.length <= LONGEST_PART) return text;
	const keep = Math.floor((LONGEST_PART - 1) / 2);
	return `${text.slice(0, keep)}…${text.slice(text.length - keep)}`;
}

function write(node) {
	const wrap = (child, tighter) => (precedenceOf(child) < tighter ? `(${write(child)})` : write(child));
	switch (node.type) {
		case 'num':
			return `${String(node.value)}${node.unit != null ? `[${node.unit}]` : ''}`;
		case 'ref': {
			// The reducing blocks build references that name a list outright,
			// `{Objects: '01'}`, where an equation writes one bracket each.
			const indices = Array.isArray(node.indices) ? node.indices : Object.values(node.indices ?? {});
			return `${node.name}${indices.map((i) => `[${i ?? ''}]`).join('')}`;
		}
		case 'unary':
			return `-${wrap(node.operand, POWER)}`;
		case 'binary': {
			if (node.op === '^') {
				// Left to right, `a^b^c` is `(a^b)^c`; an exponent is one operand,
				// signed or not.
				const exponent = node.right.type === 'unary' && precedenceOf(node.right.operand) >= ATOM
					? write(node.right) : wrap(node.right, ATOM);
				return `${wrap(node.left, POWER)}^${exponent}`;
			}
			const p = PRECEDENCE[node.op] ?? 0;
			return `${wrap(node.left, p)}${opText(node.op)}${wrap(node.right, p + 1)}`;
		}
		case 'cond':
			return `${wrap(node.test, 1)} ? ${wrap(node.then, 1)} : ${wrap(node.otherwise, 1)}`;
		case 'call':
			return `${node.name}(${(node.args ?? []).map(write).join(', ')})`;
		default:
			return '?';
	}
}

// --- the run's side ----------------------------------------------------------------

/**
 * Puts what `nonFiniteAt` finds into a solver's error, where it can be found.
 *
 * Looked for at the state the solver last held -- its own, if its error
 * carries one, else the step the runner kept -- and at the instant it failed
 * with that state; else at the start of the stretch it was solving, if that is
 * where it failed, which is where a model that divides by zero at the first
 * instant fails on every solver. A failure about a value that is not a number
 * that none of those shows came from a step past the state held -- a state
 * taken below zero under a square root -- and short steps past it are tried
 * (`stepPast`).
 *
 * The message is said again with the place in it, and the block it starts in
 * becomes the error's block, which the page marks and links to. Nothing is
 * changed when nothing is found.
 *
 * @param e the error the solver threw
 * @param system the system the run was solving
 * @param {{start?: {t: number, y: ArrayLike<number>}, held?: {t: number, y: ArrayLike<number>}|null,
 *   end?: number}} where the stretch's start, the runner's last accepted step, and the run's end
 */
export function explainNonFinite(e, system, { start = null, held = null, end = NaN } = {}) {
	if (!e || typeof e !== 'object' || !system) return false;
	// Stopped from outside, or never started: nothing went wrong in the model.
	if (e.code === 'aborted' || e.code === 'span') return false;
	// The state it last held: a step the runner kept counts only if it is of
	// this stretch, not one before a corner the stretch began at.
	const from = e.lastY && finite(e.lastT) ? { t: e.lastT, y: e.lastY }
		: held && finite(held.t) && (!start || !(held.t < start.t)) ? held : null;
	const tries = [];
	if (from) {
		tries.push([from.t, from.y]);
		// Past the last step it took: what the clock alone changes there.
		if (finite(e.t) && e.t !== from.t) tries.push([e.t, from.y]);
	} else if (start && finite(start.t) && (!finite(e.t) || e.t === start.t)) {
		tries.push([start.t, start.y]);
	}
	const said = (found, step = null) => {
		// The solver's own words, for the run log and anyone who wants them.
		e.solverMessage = e.message;
		e.message = nonFiniteMessage(found, system.layout, step);
		e.nonFinite = found;
		const block = found.root?.source?.name ?? found.root?.name ?? found.states[0]?.name ?? null;
		if (block) e.blockName = block;
		return true;
	};
	for (const [t, y] of tries) {
		const found = safely(() => nonFiniteAt(system, t, Float64Array.from(y)));
		if (found) return said(found);
	}
	if (from && aboutNonNumbers(e)) {
		const past = safely(() => stepPast(system, from, Math.max(
			finite(e.t) ? 2 * Math.abs(e.t - from.t) : 0,
			finite(end) ? 1e-3 * Math.abs(end - from.t) : 0,
		)));
		if (past) return said(past.found, { from: from.t, h: past.h });
	}
	return false;
}

const safely = (fn) => {
	try {
		return fn();
	} catch {
		return null;
	}
};

/** Whether a solver's failure is about a value that is not a number, by its code or its words. */
const aboutNonNumbers = (e) => e.code === 'nonfinite'
	|| /not a number|non-finite|not-a-number|infinite|\bNaN\b/i.test(String(e.message ?? ''));

/** The shortest step the clock tells apart at `t`, which the probes past it start from. */
const EPS = 2 ** -52;

/**
 * A step past the last state the solver held, for a value that is not a
 * number only there: a state the step takes below zero under a square root, or
 * the clock reaching the instant a table divides by zero. Explicit steps from
 * that state, from the shortest the clock tells apart and four times longer
 * each time, up to `upTo` or the first that shows one -- which is the place,
 * the nearest the run could have met it. Null if none does.
 */
function stepPast(system, from, upTo) {
	const n = system.layout.nstate;
	const y = Float64Array.from(from.y).subarray(0, n);
	const f = new Float64Array(n);
	system.dydt(from.t, y, f);
	if (!f.every(finite)) return null;
	const shortest = 4 * EPS * Math.max(1, Math.abs(from.t));
	const longest = Math.max(upTo, 1024 * shortest);
	const trial = new Float64Array(n);
	for (let h = shortest; h <= longest; h *= 4) {
		for (let i = 0; i < n; i++) trial[i] = y[i] + h * f[i];
		const found = nonFiniteAt(system, from.t + h, trial);
		if (found) return { found, h };
	}
	return null;
}
