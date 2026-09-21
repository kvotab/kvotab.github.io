/**
 * What the state trajectory is a function of.
 *
 * The integration reads a *part* of a model. A compartment's inventory follows
 * its initial value and the rates in and out of it; those rates are equations,
 * which read parameters and expressions, which read others. Everything on that
 * chain decides `y(t)`. Everything off it -- a dose computed from a well
 * concentration, a parameter only that dose reads -- is worked out from `y(t)`
 * afterwards and cannot change it.
 *
 * That split is what lets an edit to the second kind of thing skip the solve:
 * `Results` keeps only the states, and every expression is evaluated from
 * `(t, y)` when something asks for it, so a model whose integrating part has
 * not changed does not need solving again. On model G that is the
 * difference between a minute and seventeen.
 *
 * **Everything here is conservative in one direction and one direction only.**
 * Anything this cannot rule out is included, so an edit that changes nothing
 * may still cost a re-solve -- which is what happened for every edit before
 * any of this existed. The other error, reporting a model unchanged when its
 * states have moved, leaves a wrong curve on the screen looking like a right
 * one, and nothing downstream catches it. Two of those got through review:
 * `transports`, which is a flag on the side rather than a block, and a
 * `systems=` line that turned out to record only how many sub-systems there
 * were. Both have tests now.
 *
 * Its own file rather than a region of edit.js, which is where it was written:
 * the reasoning above is the whole of what this is, and it deserves to be read
 * without 8,000 lines of editing around it.
 */

import { tokenize } from '../parser/parser.js';
import { RESERVED } from './names.js';
import { qualifiedName, systemOf, resolveReference, COLLECTIONS } from './systems.js';
import { EQUATION_FIELDS, EVENT_FIELDS, RECORDER_COLLECTION, REMEMBERING_KINDS } from './recorders.js';
import { FARF_EQUATION_KEYS } from './farfield.js';
import { WASTE_EQUATION_KEYS } from './wastepackage.js';
import { DIS_EQUATION_KEYS } from './disruption.js';
import { blockNames, allBlocks, functionLocals } from './blocks.js';
import * as tr from './transport.js';

/**
 * Fields that cannot change a number, so an edit to one need not re-solve.
 *
 * Kept short and by name rather than by guessing: everything not listed here
 * counts, which is the direction that is safe to be wrong in. A stale
 * fingerprint costs a re-solve nobody needed; a fingerprint that missed a
 * change would leave a wrong curve on the screen looking like a right one.
 */
const NOT_NUMERIC = new Set([
	'comment', 'pdf', 'x', 'y', 'w', 'h', 'shape', 'colour', 'color', 'label',
	'collapsed', 'note', 'notes',
]);

/** A replacer that sorts every object's keys, so key order never changes a fingerprint. */
function canonical(key, value) {
	if (value && typeof value === 'object' && !Array.isArray(value)) {
		const out = {};
		for (const k of Object.keys(value).sort()) out[k] = value[k];
		return out;
	}
	return value;
}

/** The simulation settings the trajectory is a function of. */
const SOLVE_SETTINGS = [
	'solver', 'rtol', 'abstol', 'start_time', 'end_time', 'output_points',
	'spacing', 'output_times', 'non_negative', 'saturation_enabled', 'time_unit',
	'max_step', 'initial_step',
	// The solver's own settings: each one changes how the run is stepped.
	'max_steps', 'max_order', 'min_order', 'norm_control', 'error_norm', 'stagnation_tol',
	'newton_kappa', 'max_jac_age', 'below_tol_run', 'matrix',
	// Not a solver setting, but it appends states to the vector and changes
	// what the run reports, so a run without it is not a run with it.
	'mass_balance',
	// This one changes the error test itself, so it changes the trajectory.
	'auto_abstol',
];

/**
 * Every block the state trajectory is a function of.
 *
 * The integration reads a *part* of a model. A compartment's inventory follows
 * its initial value and the rates in and out of it; those rates are equations,
 * which read parameters and expressions, which read others. Everything on that
 * chain decides `y(t)`. Everything off it -- a dose computed from a well
 * concentration, a parameter only that dose reads -- is worked out from `y(t)`
 * afterwards and cannot change it.
 *
 * That split is not a nicety here: `Results` keeps only the states, and every
 * expression is evaluated from `(t, y)` when something asks for it. So a model
 * whose integrating part has not changed does not need solving again, however
 * much of the rest of it has -- and on model G that is the difference
 * between a minute and seventeen.
 *
 * Walked forwards from the roots, where `referencesToAny` walks backwards from
 * a name; the edges are the same edges, read the other way.
 *
 * @returns {Set<string>} qualified names, the roots included
 */
export function integratingBlocks(project) {
	const set = new Set(blockNames(project));
	const known = (n) => set.has(n);
	const reads = new Map();
	const roots = [];

	const edge = (from, to) => {
		if (to == null || to === from) return;
		if (!reads.has(from)) reads.set(from, new Set());
		reads.get(from).add(to);
	};
	const eqRefs = (eq, system, locals = null) => {
		const hits = [];
		try {
			const toks = tokenize(String(eq ?? ''));
			for (let i = 0; i < toks.length; i++) {
				const tok = toks[i];
				if (tok.type !== 'ident') continue;
				if (toks[i + 1]?.type === 'lparen' && RESERVED.has(tok.value)) continue;
				if (locals?.has(tok.value)) continue;
				const q = resolveReference(tok.value, system, known);
				if (q != null) hits.push(q);
			}
		} catch { /* an equation that will not parse reads nothing */ }
		return hits;
	};
	const fromEquation = (block, key, owner, system, locals = null) => {
		if (typeof block[key] === 'string') {
			for (const q of eqRefs(block[key], system, locals)) edge(owner, q);
		}
		for (const e of block.entries ?? []) {
			if (typeof e[key] === 'string') {
				for (const q of eqRefs(e[key], system, locals)) edge(owner, q);
			}
		}
	};
	const fromName = (value, owner, system) => {
		if (typeof value !== 'string' || !value.trim()) return;
		edge(owner, resolveReference(value.trim(), system, known));
	};

	// --- the roots: everything that is a state, or that moves one.
	for (const c of project.compartments ?? []) {
		const q = qualifiedName(c);
		const system = systemOf(c);
		roots.push(q);
		fromEquation(c, 'initial', q, system);
		fromEquation(c, 'dydt', q, system);
		if (c.initial && typeof c.initial === 'object' && !Array.isArray(c.initial)) {
			for (const v of Object.values(c.initial)) {
				for (const r of eqRefs(String(v), system)) edge(q, r);
			}
		}
	}
	for (const tr of project.transfers ?? []) {
		const q = qualifiedName(tr);
		roots.push(q);
		edge(q, tr.from);
		edge(q, tr.to);
		fromEquation(tr, 'rate', q, systemOf(tr));
	}
	for (const s of project.inflows ?? []) {
		const q = qualifiedName(s);
		roots.push(q);
		edge(q, s.to);
		fromEquation(s, 'rate', q, systemOf(s));
	}
	// A far-field path holds states of its own, and every one of its settings
	// is an equation that decides them.
	for (const f of project.farfields ?? []) {
		const q = qualifiedName(f);
		const system = systemOf(f);
		roots.push(q);
		for (const key of FARF_EQUATION_KEYS) fromEquation(f, key, q, system);
	}
	// Waste packages hold two inventories the solver integrates, and every
	// setting on them is an equation that decides what leaves.
	for (const w of project.waste_packages ?? []) {
		const q = qualifiedName(w);
		const system = systemOf(w);
		roots.push(q);
		for (const key of WASTE_EQUATION_KEYS) fromEquation(w, key, q, system);
	}
	// A disruptive event moves mass: its time or rate, each action's share and
	// the blocks it acts on all decide the trajectory.
	for (const d of project.events ?? []) {
		const q = qualifiedName(d);
		const system = systemOf(d);
		roots.push(q);
		for (const key of DIS_EQUATION_KEYS) fromEquation(d, key, q, system);
		for (const a of d.actions ?? []) fromEquation(a, 'fraction', q, system);
	}
	// A transport's own blocks are roots, whatever reads them.
	//
	// A chain is not written down as compartments and transfers: `Begin`,
	// `End`, the transport number and the element counter are a *recipe*, and
	// the builder expands them into as many compartments and as many internal
	// transfers as the number says. Nothing in the model names the number in
	// an equation -- the builder reads it -- so walking the references never
	// reaches it, and `Col.N` going from 3 to 7 left this set, and the
	// fingerprint built from it, byte for byte identical while the state
	// vector doubled. Every block carrying a role is therefore a root, and so
	// is anything it reads: the number and the counter may themselves be
	// equations over parameters.
	for (const b of allBlocks(project)) {
		if (!tr.roleOf(b)) continue;
		const q = qualifiedName(b);
		const system = systemOf(b);
		roots.push(q);
		for (const key of ['equation', 'initial', 'dydt', 'value']) {
			fromEquation(b, key, q, system);
		}
	}

	// --- and the edges of everything else, so the closure can follow them.
	for (const e of project.expressions ?? []) {
		fromEquation(e, 'equation', qualifiedName(e), systemOf(e));
	}
	for (const f of project.functions ?? []) {
		fromEquation(f, 'equation', qualifiedName(f), systemOf(f),
			functionLocals(f, 'equation'));
	}
	for (const [kind, plural] of Object.entries(RECORDER_COLLECTION)) {
		for (const b of project[plural] ?? []) {
			const q = qualifiedName(b);
			const system = systemOf(b);
			for (const key of EQUATION_FIELDS[kind] ?? []) fromEquation(b, key, q, system);
			for (const key of EVENT_FIELDS[kind] ?? []) {
				fromName(b[key], q, system);
				for (const e of b.entries ?? []) fromName(e[key], q, system);
			}
		}
	}
	for (const o of project.index_reductions ?? []) {
		const q = qualifiedName(o);
		const system = systemOf(o);
		fromName(o.target, q, system);
		for (const e of o.entries ?? []) fromName(e.target, q, system);
	}
	for (const g of project.block_reductions ?? []) {
		const q = qualifiedName(g);
		const system = systemOf(g);
		for (const target of g.targets ?? []) fromName(target, q, system);
		for (const e of g.entries ?? []) {
			for (const target of e.targets ?? []) fromName(target, q, system);
		}
	}
	// A lookup is read at the clock and holds its own table, so nothing it
	// reads is a reference -- but a rate may read *it*, which the edge above
	// from the rate already records.

	// --- the closure.
	const out = new Set();
	const stack = [...roots];
	while (stack.length) {
		const at = stack.pop();
		if (at == null || out.has(at)) continue;
		out.add(at);
		for (const next of reads.get(at) ?? []) stack.push(next);
	}
	return out;
}

/**
 * A fingerprint of everything `y(t)` is a function of.
 *
 * Two models with the same fingerprint have the same trajectory, so the second
 * need not be solved: the first one's states are still the answer, and every
 * expression over them is worked out on demand anyway.
 *
 * Conservative in the one direction that matters. Anything it cannot rule out
 * is included, so an edit that changes nothing may still cost a re-solve --
 * which is what happens today for every edit. The other error, reporting a
 * model unchanged when its states have moved, would leave a wrong curve on the
 * screen looking like a right one, and nothing downstream would catch it.
 */
export function integrationFingerprint(project) {
	// A model that remembers is never reusable, whatever else is true of it.
	//
	// The trajectory is not the only thing a run produces. A peak dose, a mean
	// from a given year, a value a century ago -- each is accumulated *during*
	// the integration, into a history the system carries, and `Results` reads
	// those histories back when it is asked. A system built fresh and handed
	// somebody else's trajectory has never run and remembers nothing: on
	// `examples/recorders.json` the peak dose came back as 6.35 where the run
	// recorded 0.00057, and the value a century ago as zero. Both are numbers,
	// neither is wrong-looking, and nothing downstream would have caught it.
	//
	// Refused here rather than worked around. Carrying the histories across
	// would mean proving the new system's memory layout matches the old one's,
	// which is the same proof as the state layout and a good deal less obvious
	// -- and the whole point of this is to be sure.
	for (const kind of REMEMBERING_KINDS) {
		if ((project[RECORDER_COLLECTION[kind]] ?? []).length) return null;
	}

	const inside = integratingBlocks(project);
	const sim = project.simulation ?? {};
	const parts = [];

	for (const key of SOLVE_SETTINGS) parts.push(`${key}=${JSON.stringify(sim[key] ?? null)}`);
	// The index lists shape every block in the model, and the nuclides bring
	// their own decay constants into every compartment's derivative.
	parts.push(`lists=${JSON.stringify(project.index_lists ?? null)}`);
	parts.push(`nuclides=${JSON.stringify(project.nuclides ?? null)}`);
	parts.push(`halflives=${JSON.stringify(project.half_lives ?? null)}`);
	// The sub-systems, by path, and which of them are switched off.
	//
	// This used to read `(project.systems ?? []).map((s) => [qualifiedName(s),
	// s.enabled !== false])` -- but `project.systems` is a list of *path
	// strings*, not blocks, so `qualifiedName('Geosphere')` was `''` and
	// `'Geosphere'.enabled` was `undefined` for every one of them. The whole
	// line evaluated to `[["",true],["",true],...]`: it recorded how many
	// sub-systems there were and nothing else. It looked like a guard and was
	// not one. Sorted, because neither list has a meaningful order and a
	// re-ordering is not a change to any number.
	parts.push(`systems=${JSON.stringify([...(project.systems ?? [])].sort())}`);
	parts.push(`disabled=${JSON.stringify(
		[...(project.disabledSystems ?? project.disabled_systems ?? [])].sort())}`);
	// Which sub-systems are transport chains.
	//
	// Not a block and not an equation: a flag on the side, read by the builder
	// when it decides whether a sub-system is two compartments or a chain of
	// N. With it missing, a model with `transports: ['Col']` and the same
	// model with `transports: []` fingerprinted identically *and* laid their
	// states out identically -- so both this test and the worker's structural
	// one passed -- while the answer moved by a factor of two and a half.
	parts.push(`transports=${JSON.stringify(tr.transportPaths(project).sort())}`);

	// Every block on the chain, in a fixed order, with the fields that can
	// change a number. A block's own kind is in the key, so a compartment and
	// an expression that happen to share a name cannot collide.
	for (const kind of COLLECTIONS) {
		for (const b of project[kind] ?? []) {
			const q = qualifiedName(b);
			if (!inside.has(q)) continue;
			const keep = {};
			for (const [k, v] of Object.entries(b)) {
				if (NOT_NUMERIC.has(k)) continue;
				keep[k] = v;
			}
			// Entries carry values per index, and the same fields are dropped
			// from each of them.
			if (Array.isArray(b.entries)) {
				keep.entries = b.entries.map((e) => {
					const out = {};
					for (const [k, v] of Object.entries(e)) {
						if (!NOT_NUMERIC.has(k)) out[k] = v;
					}
					return out;
				});
			}
			// Canonical at every level. An array replacer filters *nested* keys
			// too, so an entry's index and an event's actions were hashed as
			// empty objects: two shares could differ without the run noticing.
			parts.push(`${kind}:${q}=${JSON.stringify(keep, canonical)}`);
		}
	}
	return parts.join('\n');
}

