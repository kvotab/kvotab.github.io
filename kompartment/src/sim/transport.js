/**
 * Unrolling a transport sub-system into the chain it stands for.
 *
 * Ecolego draws a transport as two compartments, Begin and End, and runs it as
 * N. the standard transport equation
 * lays N states side by side per index tuple and, for each pair of neighbours
 * (i, i+1), sets two static ints -- BEGIN = i, END = i+1 -- and evaluates the
 * transfers drawn between Begin and End with every reference to Begin reading
 * state i and every reference to End reading state i+1:
 *
 *     BEGIN=0; END=1;              dydt[pos]      = <Begin's transfers>
 *     for i in 1..last-1:
 *       BEGIN=i-1; END=i;          dydt[pos+i]    = <what arrives from above>
 *       BEGIN=i;   END=i+1;        dydt[pos+i]   += <what leaves below> + decay
 *     BEGIN=last-1; END=last;      dydt[pos+last] = <what arrives from above>
 *     BEGIN=last;                  dydt[pos+last]+= <End's external transfers> + decay
 *     BEGIN=0; END=last;           (reset: outside the loop Begin is the first
 *                                   element and End the last)
 *
 * The element counter (`getCurrentElement`) answers BEGIN+1 while that runs,
 * so inside a transfer between the two it is the 1-based number of the element
 * the pair starts at, and outside it is 1. The initial condition is Begin's,
 * for every element (`writeGetInitialConditionMethod` reads only Begin's
 * INITIAL_CONDITION, with BEGIN = i so that the counter can appear in it).
 * With N = 1 (`SingleCompartmentDifferentialsEquationFetcher`) the two are one
 * state: everything drawn into or out of either applies to it, and the
 * transfers between them are dropped.
 *
 * This tool does the same thing at a different time. Before the model is
 * built, every transport is rewritten into ordinary blocks -- N compartments
 * of which the first keeps Begin's name and the last End's, N-1 copies of each
 * transfer drawn between them, one per pair of neighbours, with Begin, End and
 * the counter substituted -- and the builder, the solvers and the results see
 * a model with nothing unusual in it. The compartments in the middle are
 * marked `hidden`, so they take part in the run and stay out of the lists of
 * results, exactly as Ecolego's anonymous states do.
 *
 * Two things Ecolego decides by evaluation order are decided here by rule.
 * An expression *inside* the transport that reads Begin, End, the counter or
 * one of the internal transfers is uncached inside a transport
 * (the usual caching) and so reads whichever pair is current; here
 * it is copied per pair like the transfers, and the copy is what the copied
 * transfers read. Its original stays, as what the block comes to seen from
 * outside: Begin the first element, End the last. The counter is not read
 * from outside at all -- the build refuses it, since which pair is current is
 * a question with no answer there. And a transfer drawn from *outside*
 * into Begin, or out of End, reads Begin and End as the first and last
 * elements, where some of them happen to be evaluated with the pair
 * (0, 1) or (last, last) current.
 */

import { Project } from '../domain/project.js';
import { tokenize, TokenType as T } from '../parser/parser.js';
import { lookupFunction } from '../parser/functions.js';
import {
	qualifiedName, systemOf, resolveReference, referenceFrom, qualify, baseName, parentOf,
} from '../domain/systems.js';
import {
	transportPaths, transportParts, transportNumber, internalTransfers, roleOf,
} from '../domain/transport.js';
import { RECORDER_COLLECTION, EQUATION_FIELDS, EVENT_FIELDS } from '../domain/recorders.js';
import { FARF_EQUATION_KEYS } from '../domain/farfield.js';

/** A transport that cannot be unrolled. The builder reports it as a BuildError. */
export class TransportError extends Error {
	constructor(message, blockName = null) {
		super(message);
		this.name = 'TransportError';
		this.blockName = blockName;
	}
}

/** Which fields of each collection hold an equation, for the call-site rewrite. */
const EQUATION_KEYS = {
	compartments: ['initial', 'dydt'],
	transfers: ['rate'],
	inflows: ['rate'],
	expressions: ['equation'],
	farfields: FARF_EQUATION_KEYS,
};
for (const [kind, plural] of Object.entries(RECORDER_COLLECTION)) {
	EQUATION_KEYS[plural] = [...EQUATION_FIELDS[kind], ...EVENT_FIELDS[kind]];
}

/**
 * The project with every transport unrolled, or the project itself when it has
 * none. A new `Project`, built from the old one's JSON with the chains written
 * out; the old one is not touched.
 */
export function expandTransports(project) {
	const paths = transportPaths(project).filter((p) => project.systems.includes(p));
	if (!paths.length) return project;

	// The blocks are shared with the project and never written to; the
	// collections this adds to and takes from are copied.
	const raw = { ...project.toJSON() };
	raw.compartments = [...(raw.compartments ?? [])];
	raw.expressions = [...(raw.expressions ?? [])];
	raw.transfers = [...(raw.transfers ?? [])];
	raw.inflows = [...(raw.inflows ?? [])];
	// An ordinary model from here on.
	delete raw.transports;

	// Every name a reference can resolve to, and every name in use -- the
	// second grows as elements and copies are named.
	const known = new Set();
	for (const key of Object.keys(EQUATION_KEYS).concat(['parameters', 'lookups',
		'index_reductions', 'block_reductions'])) {
		for (const b of raw[key] ?? []) known.add(qualifiedName(b));
	}
	const taken = new Set(known);

	// The parts of a transport that is switched off, which go with it.
	const off = new Set();
	for (const path of paths) expandOne(project, raw, path, known, taken, off);

	const derived = new Project(raw);
	// The names the original switched off, so that a reference to one is
	// still answered with "that is disabled" rather than "unknown name".
	derived.disabled = new Set([...project.disabled, ...derived.disabled, ...off]);
	derived.implicitlyDisabled = new Map([
		...project.implicitlyDisabled, ...derived.implicitlyDisabled,
	]);
	return derived;
}

/** A block as the derived project should carry it: the same, minus its part. */
function plain(block, patch = {}) {
	const { transport, qname, kind, ...rest } = block;
	const out = { ...rest };
	for (const [key, value] of Object.entries(patch)) {
		if (value === undefined) delete out[key];
		else out[key] = value;
	}
	return out;
}

/**
 * Rewrites the references in one equation, token by token, the way
 * `edit.rewriteEquation` does: an identifier is resolved from `system`, and
 * `replace` says what it becomes -- or null to leave it.
 */
function rewriteRefs(text, system, known, replace) {
	const src = String(text ?? '');
	if (!src) return src;
	let tokens;
	try {
		tokens = tokenize(src);
	} catch {
		return src;
	}
	let out = '';
	let cursor = 0;
	for (let i = 0; i < tokens.length; i++) {
		const tok = tokens[i];
		if (tok.type !== T.IDENT) continue;
		if (tokens[i + 1]?.type === T.LPAREN && lookupFunction(tok.value)) continue;
		const q = resolveReference(tok.value, system, (n) => known.has(n));
		if (q == null) continue;
		const to = replace(q);
		if (to == null || to === tok.value) continue;
		out += src.slice(cursor, tok.pos) + to;
		cursor = tok.pos + tok.text.length;
	}
	return out + src.slice(cursor);
}

/**
 * Rewrites every call of an operation, `Op(x)`, into the built-in that works
 * it out over the chain: `transport_point(c1, ..., cn, x)`. The chain's
 * compartments go first, spelled as the caller's sub-system would spell them,
 * and the caller's own arguments follow.
 */
function rewriteCalls(text, system, target, fnName, elements, arity, known, ownerName) {
	const src = String(text ?? '');
	if (!src || !src.includes(baseName(target))) return src;
	let tokens;
	try {
		tokens = tokenize(src);
	} catch {
		return src;
	}
	let out = '';
	let cursor = 0;
	for (let i = 0; i < tokens.length; i++) {
		const tok = tokens[i];
		if (tok.type !== T.IDENT || tokens[i + 1]?.type !== T.LPAREN) continue;
		if (lookupFunction(tok.value)) continue;
		const q = resolveReference(tok.value, system, (n) => known.has(n));
		if (q !== target) continue;
		// How many arguments the caller wrote: the commas at depth one
		// between this '(' and its ')'.
		let depth = 0;
		let commas = 0;
		let empty = true;
		for (let j = i + 1; j < tokens.length; j++) {
			const t = tokens[j];
			if (t.type === T.LPAREN) depth++;
			else if (t.type === T.RPAREN) { depth--; if (depth === 0) break; }
			else if (t.type === T.COMMA && depth === 1) commas++;
			if (depth === 1 && j > i + 1) empty = false;
		}
		const given = empty ? 0 : commas + 1;
		if (given !== arity) {
			throw new TransportError(
				`'${tok.value}' is a transport operation that takes ${arity === 1
					? 'one position along the chain, between 0 and 1'
					: 'two positions along the chain, each between 0 and 1'}; `
				+ `${given} argument${given === 1 ? ' was' : 's were'} given.`,
				ownerName,
			);
		}
		const spelled = elements.map((e) => referenceFrom(e, system, (n) => known.has(n)));
		const open = tokens[i + 1];
		out += src.slice(cursor, tok.pos) + `${fnName}(${spelled.join(', ')}, `;
		cursor = open.pos + 1;
	}
	return out + src.slice(cursor);
}

function expandOne(project, raw, path, known, taken, off) {
	const parts = transportParts(project, path);
	// A transport is switched off by switching off its Begin or its End: the
	// chain has nowhere to start or to stop, so the whole of it is left out
	// of the run -- `preconditions.isIncluded(begin)` decides the same in
	// the rule -- and its other parts go with it. Anything drawn into or out
	// of the two is already off, since a connection follows its ends.
	const switchedOff = [...project.disabled].some((n) => parentOf(n) === path);
	if ((parts.begins.length === 0 || parts.ends.length === 0) && switchedOff) {
		const going = new Set([
			...parts.begins, ...parts.ends, ...parts.numbers, ...parts.counters, ...parts.operations,
		].map((b) => b.qname));
		raw.compartments = raw.compartments.filter((b) => !going.has(qualifiedName(b)));
		raw.expressions = raw.expressions.filter((b) => !going.has(qualifiedName(b)));
		for (const name of going) off.add(name);
		return;
	}
	if (parts.begins.length !== 1 || parts.ends.length !== 1) {
		const count = (list, what) => `${list.length || 'no'} ${what}`
			+ `${list.length === 1 ? '' : list.length ? 's' : ''}`;
		const what = [];
		if (parts.begins.length !== 1) what.push(count(parts.begins, 'Begin compartment'));
		if (parts.ends.length !== 1) what.push(count(parts.ends, 'End compartment'));
		throw new TransportError(
			`'${path}' is a transport with ${what.join(' and ')}. A transport is a chain `
			+ 'from one Begin to one End.',
			path,
		);
	}
	const B = parts.begin;
	const E = parts.end;
	const bq = B.qname;
	const eq = E.qname;
	const dimsOf = (b) => [...(b.index_lists ?? [])].sort().join(' ');
	if (dimsOf(B) !== dimsOf(E)) {
		throw new TransportError(
			`'${eq}' is not indexed by the same lists as '${bq}'. Every compartment of the `
			+ 'chain is one compartment repeated, so Begin and End must match.', eq,
		);
	}
	const { n, why } = transportNumber(project, parts);
	if (why) throw new TransportError(why, parts.number?.qname ?? path);

	const C = parts.counter;
	const cq = C?.qname ?? null;
	const internal = internalTransfers(project, parts);
	const internalNames = new Set(internal.map((t) => t.qname));

	// The expressions inside the transport that read the pair: Begin, End,
	// the counter, a transfer between the two, or one another.
	const dependent = [];
	const dependentNames = new Set();
	const pairNames = () => new Set([
		bq, eq, ...(cq ? [cq] : []), ...internalNames, ...dependentNames,
	]);
	const refsAny = (block, keys, names) => {
		const texts = [];
		for (const key of keys) {
			if (typeof block[key] === 'string') texts.push(block[key]);
			for (const e of block.entries ?? []) if (typeof e[key] === 'string') texts.push(e[key]);
		}
		return texts.some((text) => {
			let found = false;
			rewriteRefs(text, path, known, (q) => { if (names.has(q)) found = true; return null; });
			return found;
		});
	};
	for (let grew = true; grew;) {
		grew = false;
		const names = pairNames();
		for (const x of project.expressions) {
			if (systemOf(x) !== path || roleOf(x) || dependentNames.has(x.qname)) continue;
			if (refsAny(x, ['equation'], names)) {
				dependent.push(x);
				dependentNames.add(x.qname);
				grew = true;
			}
		}
	}

	// The counter is which pair of neighbours is being assembled, and outside
	// the chain there is no pair. Read from outside it used to come to 1 --
	// the state the statics are left in, and not a number anything
	// meant -- so the build refuses it, as the checker and the strip do.
	if (cq) {
		const only = new Set([cq]);
		const outside = [
			...project.expressions.map((x) => [x, ['equation']]),
			...project.transfers.map((t) => [t, ['rate']]),
			...project.inflows.map((s) => [s, ['rate']]),
			...project.compartments.map((c) => [c, ['initial', 'dydt']]),
		].find(([b, keys]) => systemOf(b) !== path && refsAny(b, keys, only));
		if (outside) {
			throw new TransportError(
				`'${outside[0].qname}' reads '${cq}', the element counter of '${path}', from `
				+ 'outside the transport. The counter counts the compartments of the chain '
				+ 'and has a value only inside it.', outside[0].qname,
			);
		}
	}

	// Names for the elements and the copies. The first and last elements are
	// Begin and End themselves; the ones between are Begin's name numbered,
	// kept clear of anything the model already calls that.
	const fresh = (base) => {
		let name = base;
		for (let i = 1; taken.has(qualify(path, name)); i++) name = `${base}_${i}`;
		taken.add(qualify(path, name));
		return name;
	};
	const elemLocal = new Array(n + 1);
	elemLocal[1] = B.name;
	if (n > 1) elemLocal[n] = E.name;
	for (let e = 2; e < n; e++) elemLocal[e] = fresh(`${B.name}_${e}`);
	const elemQ = (e) => qualify(path, elemLocal[e]);
	const elements = [];
	for (let e = 1; e <= n; e++) elements.push(elemQ(e));

	const copyKey = (q, e) => `${q} ${e}`;
	const copyName = new Map();
	for (let e = 1; e < n; e++) {
		for (const x of dependent) copyName.set(copyKey(x.qname, e), fresh(`${x.name}_${e}`));
		// The transfer for the first pair keeps the drawn transfer's own name;
		// the others are numbered by the pair they join.
		for (const t of internal) {
			copyName.set(copyKey(t.qname, e), e === 1 ? t.name : fresh(`${t.name}_${e}`));
		}
	}
	// What each name becomes in the copy for the pair (e, e+1).
	const replaceFor = (e) => (q) => {
		if (q === bq) return elemLocal[e];
		if (q === eq) return elemLocal[e + 1];
		if (q === cq) return String(e);
		return copyName.get(copyKey(q, e)) ?? null;
	};
	const rewrite = (text, e) => rewriteRefs(text, path, known, replaceFor(e));
	const rewriteEntries = (entries, key, e) => (entries ?? []).map((en) => (
		typeof en[key] === 'string' ? { ...en, [key]: rewrite(en[key], e) } : { ...en }
	));
	// In an initial condition only the counter can mean anything per element:
	// no compartment has a value yet, and BEGIN = i is set for exactly
	// this. `writeGetInitialConditionMethod`.
	const rewriteInitial = (text, e) => rewriteRefs(text, path, known,
		(q) => (q === cq ? String(e) : null));

	const without = (list, names) => list.filter((b) => !names.has(qualifiedName(b)));

	// --- the chain --------------------------------------------------------
	if (n === 1) {
		// One state. End is Begin by another name; what was drawn into or out
		// of End is drawn into or out of Begin; the transfers between them
		// go. `SingleCompartmentDifferentialsEquationFetcher`.
		raw.compartments = without(raw.compartments, new Set([eq]));
		raw.expressions.push(plain(E, {
			equation: B.name, unit: E.unit || B.unit, index_lists: [...(B.index_lists ?? [])],
			entries: [], initial: undefined, abstol: undefined, non_negative: undefined,
			handle_decay: undefined, dydt: undefined,
		}));
		const rewire = (conn) => {
			if (internalNames.has(qualifiedName(conn))) return null;
			if (conn.from !== eq && conn.to !== eq) return conn;
			return {
				...conn,
				from: conn.from === eq ? bq : conn.from,
				to: conn.to === eq ? bq : conn.to,
			};
		};
		raw.transfers = raw.transfers.map(rewire).filter(Boolean);
		raw.inflows = raw.inflows.map(rewire).filter(Boolean);
	} else {
		for (let e = 2; e < n; e++) {
			raw.compartments.push(plain(B, {
				name: elemLocal[e], system: path, hidden: true,
				// For anything held per compartment, a slice in the middle is
				// Begin: a compartment-indexed value inside a transport resolves
				// the chain against Begin's index, since the slices have none.
				alias: { compartment: bq },
				initial: rewriteInitial(B.initial, e),
				// Begin's dy/dt term is every slice's too -- the format's
				// `InternalEquationFetcher` reads getDifferentialEquation(begin)
				// for each position -- rewritten for the pair, so a `Begin`
				// in it is this slice and an `End` the next one down.
				dydt: typeof B.dydt === 'string' ? rewrite(B.dydt, e) : undefined,
				entries: rewriteEntries(rewriteEntries(B.entries, 'initial', e), 'dydt', e),
				color: undefined, symbol: undefined, comment: '',
			}));
		}
		// End keeps its name, its unit and its looks, and takes everything
		// that makes an element from Begin: the initial condition (its own is
		// not read -- see the file comment), the decay switch, the tolerance.
		raw.compartments = raw.compartments.map((c) => (qualifiedName(c) !== eq ? c : plain(B, {
			name: E.name, system: path, unit: E.unit || B.unit,
			comment: E.comment, color: E.color, symbol: E.symbol,
			initial: rewriteInitial(B.initial, n),
			// ...but not the dy/dt term. End's row is generated from End --
			// `ExternalEndEquationFetcher` calls generateDifferentialEquation
			// on the End -- so End keeps its own term, and Begin's per-index
			// terms stay behind with Begin's.
			dydt: typeof E.dydt === 'string' ? rewrite(E.dydt, n) : undefined,
			entries: [
				...rewriteEntries(B.entries, 'initial', n)
					.map(({ dydt, ...rest }) => rest)
					.filter((en) => Object.keys(en).some((k) => k !== 'index')),
				...(E.entries ?? [])
					.filter((en) => typeof en.dydt === 'string')
					.map((en) => ({ index: en.index, dydt: rewrite(en.dydt, n) })),
			],
		})));
		// The transfers between the pairs, and the expressions they read. The
		// drawn transfer becomes the one joining the first pair, under its own
		// name -- so a value held per transfer, a flow say, still finds it --
		// and the others are hidden copies that answer for the Transfers list
		// as it does (see `alias`, and `implicitIndices` in ./builder.js).
		// `_source_` and `_target_` are Begin and End for every pair, which is
		// what the source-compartment index holds throughout.
		raw.transfers = without(raw.transfers, internalNames);
		for (let e = 1; e < n; e++) {
			for (const x of dependent) {
				raw.expressions.push(plain(x, {
					name: copyName.get(copyKey(x.qname, e)), system: path, hidden: true,
					equation: rewrite(x.equation, e),
					entries: rewriteEntries(x.entries, 'equation', e),
					color: undefined, symbol: undefined, comment: '',
				}));
			}
			for (const t of internal) {
				const forward = t.from === bq;
				raw.transfers.push(plain(t, {
					name: copyName.get(copyKey(t.qname, e)), system: path,
					...(e === 1 ? {} : { hidden: true, color: undefined, comment: '' }),
					alias: { transfer: t.qname, from: t.from, to: t.to },
					from: forward ? elemQ(e) : elemQ(e + 1),
					to: forward ? elemQ(e + 1) : elemQ(e),
					rate: rewrite(t.rate, e),
					entries: rewriteEntries(t.entries, 'rate', e),
				}));
			}
		}
	}
	// With one slice there is no pair, and a transfer drawn between the two
	// ends is no transfer at all. What it still is, to anything that reads
	// it by name, is its rate.
	if (n === 1) {
		for (const t of internal) {
			raw.expressions.push(plain(t, {
				equation: t.rate,
				entries: (t.entries ?? []).map((en) => {
					const { rate, ...rest } = en;
					return typeof rate === 'string' ? { ...rest, equation: rate } : rest;
				}),
				from: undefined, to: undefined, multiply_by_donor: undefined,
				index_lists: [...(B.index_lists ?? [])],
			}));
		}
	}
	// The counter is 1 wherever it is not substituted, and is not a result.
	if (C) {
		raw.expressions = raw.expressions.map((x) => (qualifiedName(x) !== cq ? x
			: plain(C, { equation: '1', hidden: true })));
	}
	// N stays as the expression it is.
	raw.expressions = raw.expressions.map((x) => (qualifiedName(x) !== parts.number.qname ? x
		: plain(x)));

	// --- the operations ----------------------------------------------------
	const locals = elements.map((q) => baseName(q));
	for (const op of parts.operations) {
		const oq = op.qname;
		const mean = (op.operation ?? 'mean') === 'mean';
		if ((op.argument ?? 'all') === 'all') {
			const total = locals.length === 1 ? locals[0] : locals.join(' + ');
			raw.expressions = raw.expressions.map((x) => (qualifiedName(x) !== oq ? x : plain(op, {
				equation: mean ? `(${total}) / ${n}` : total,
				index_lists: [...(B.index_lists ?? [])],
				unit: op.unit || B.unit,
				entries: [], operation: undefined, argument: undefined,
			})));
			continue;
		}
		// Called, not read: the block goes, and every call of it becomes the
		// built-in over the chain. the transport code generator writes no
		// result method for one with arguments, so it is not a result there
		// either.
		raw.expressions = without(raw.expressions, new Set([oq]));
		const point = op.argument === 'point';
		const fnName = point ? 'transport_point' : mean ? 'transport_mean' : 'transport_sum';
		const arity = point ? 1 : 2;
		for (const [collection, keys] of Object.entries(EQUATION_KEYS)) {
			raw[collection] = (raw[collection] ?? []).map((b) => {
				const system = systemOf(b);
				const owner = qualifiedName(b);
				let changed = null;
				for (const key of keys) {
					if (typeof b[key] === 'string') {
						const next = rewriteCalls(b[key], system, oq, fnName, elements, arity, taken, owner);
						if (next !== b[key]) (changed ??= { ...b })[key] = next;
					}
					(b.entries ?? []).forEach((en, i) => {
						if (typeof en[key] !== 'string') return;
						const next = rewriteCalls(en[key], system, oq, fnName, elements, arity, taken, owner);
						if (next === en[key]) return;
						changed ??= { ...b };
						if (changed.entries === b.entries) changed.entries = b.entries.map((x) => ({ ...x }));
						changed.entries[i][key] = next;
					});
				}
				return changed ?? b;
			});
		}
	}
}
