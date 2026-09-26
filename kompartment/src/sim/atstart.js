/**
 * What a model's equations work out to at the first instant of a run.
 *
 * This is the editor's question rather than the solver's. You have written
 * `Total_inventory * Leaching_fraction` in a compartment's initial inventory,
 * or `k_out * (1 - Retention)` as a rate, and what you want to know before
 * running anything is what that *is*. Every equation in a model has an answer
 * at the start: the compartments hold their initial inventories, the clock
 * reads `start_time`, the remembering blocks hold their seeds, and nothing has
 * happened yet. So the answer is one pass over the same generated code the
 * solver runs for its first step -- `initialState`, then `evaluateAlgebraic`
 * once, and nothing else.
 *
 * It is deliberately the *same* pass, read back through the same descriptors:
 * what the settings dialog shows for a block is the first row of the Table tab
 * for that block, down to the label and the unit. Two ways of working out the
 * same number would eventually disagree, and the one in the dialog would be
 * the one nobody could check.
 *
 * Nothing here refuses a value for being strange. A model that divides by a
 * compartment starting at zero *has* an infinity in it at t=0, and saying so
 * beside the equation is the whole point -- half the imported corpus has one
 * somewhere. Only a model that will not build at all has no answer.
 */

import { buildSystem } from './builder.js';
import { describeEntry } from './runner.js';

/** What a block's own value comes from, given the layout entry it lives in. */
const SOURCE = { state: 'y', algebraic: 'X', parameter: 'P' };

/**
 * Every value in a model at the first instant.
 *
 * @param project a `Project`
 * @param {{system?: object}} [opts] a system already built for this project,
 *   when the caller has one -- building is the expensive half (a couple of
 *   seconds on a landscape model, twenty milliseconds on an ordinary one)
 *   and the evaluation is a tenth of a millisecond.
 * @returns {{t0: number, of: (name: string) => object|null, size: number}}
 */
export function valuesAtStart(project, { system = null } = {}) {
	// No analytic derivative: nothing here differentiates anything, and on a
	// large model generating df/dy is a quarter to a half of the build.
	const sys = system ?? buildSystem(project, { jacobian: false });
	const t0 = project.simulation.start_time;

	const y = sys.initialState();
	// The remembering blocks read their own history, and at the start that
	// history is the seed a run would prime them with: a min/max starts at its
	// target, a snapshot at its own initial. Without this they would be read
	// out of whatever the last evaluation happened to leave behind.
	sys.primeRecorders?.(t0, y);
	// Copied: `evaluateAlgebraic` hands back the buffer it works in, and the
	// next call to it -- ours or anyone's -- overwrites what is in there.
	const X = Float64Array.from(sys.evaluateAlgebraic(t0, y));
	// `y` is ours -- `initialState` allocates a fresh one each call -- and the
	// parameters are filled once when the system is built and never written
	// again, so only the algebraic buffer above needs copying.
	const rows = { y, X, P: sys.parameterValues };
	// What the answers are read through, taken out of the system and the
	// project here: the functions below outlive this call, and a closure that
	// named either would keep the whole build alive with them -- its compiled
	// code and its Jacobian, 108 MB on the largest imported assessment -- for
	// the few values an editor asks about.
	const layout = sys.layout;
	const timeUnit = project.simulation.time_unit ?? '';

	// One pass over the layout, keeping only what a name can be looked up by.
	// The landscape models carry a quarter of a million values across three and
	// a half thousand blocks, so the values themselves are left in the two
	// arrays and sliced when something actually asks for a block.
	const own = new Map();
	const fields = new Map();
	const remember = (entry, kind, where) => {
		if (!own.has(entry.name)) own.set(entry.name, { entry, kind, where });
	};

	for (const s of sys.layout.states) {
		// A running mean's integral is machinery rather than a result, exactly
		// as in `Results.outputs`: the block's own value is an algebraic slot.
		// The two inventories inside waste packages are worth a number at the
		// start too: what the packages hold, and nothing exposed yet.
		if (s.kind === 'waste_package') { remember(s, 'waste_inventory', 'state'); continue; }
		// An event's count starts at nothing, and says so.
		if (s.kind === 'event') { remember(s, 'event', 'state'); continue; }
		if (s.kind !== 'compartment') continue;
		remember(s, 'compartment', 'state');
		fieldsOf(fields, s.block).set('initial', { entry: s, where: 'state' });
	}
	for (const a of sys.layout.algebraic) {
		// The slots behind a remembering block -- its target, its delay, a
		// snapshot's own initial, the two sides of an event -- are named with
		// a `#` and marked hidden so they cannot be mistaken for blocks. They
		// are not blocks, but each one *is* an equation somebody typed into a
		// field of the dialog, which is exactly what this is for.
		if (!a.hidden) remember(a, a.kind, 'algebraic');
		if (a.valueKey) fieldsOf(fields, a.block).set(a.valueKey, { entry: a, where: 'algebraic' });
	}
	for (const p of sys.layout.parameters ?? []) {
		remember(p, 'parameter', 'parameter');
		fieldsOf(fields, p.block).set('value', { entry: p, where: 'parameter' });
	}

	/**
	 * The unit of one of the slots behind a block, which is rarely the
	 * block's own.
	 *
	 * `describeEntry` gives every slot the unit its block claims, falling back
	 * to the inventory unit of the material at that index. For the block's own
	 * value that is right. For the equations it is built from it usually is
	 * not: a delay is a length of time, an event's two sides are whatever is
	 * being compared, and a far-field path's porosity is a fraction -- none of
	 * them the path's Bq/year. Those go without, because a wrong unit beside a
	 * number is worse than no unit at all.
	 *
	 * Two of them do report the block's own quantity, and keep the unit the
	 * descriptor worked out rather than the one the block happens to write
	 * down: what a recorder is watching is what that recorder reports, and a
	 * snapshot reads its `initial` until its event first fires. Taking
	 * `block.unit` for those instead dropped the per-index unit of a model
	 * whose materials are measured in different things -- Bq at one index and
	 * kgC at the next -- and labelled the same quantity two ways in one panel.
	 *
	 * @param derived what `describeEntry` said, fallback included
	 */
	const unitOfField = (key, block, derived) => {
		if (key === 'target' || key === 'initial') return derived;
		if (key === 'delay') return timeUnit;
		// A compartment's dy/dt term is a change in its own quantity per unit
		// of time -- `EquationValidator` gives it `targetUnit/timeUnit`.
		if (key === 'dydt') {
			const t = timeUnit;
			return derived ? (t ? `${derived}/${t}` : derived) : '';
		}
		return '';
	};

	const read = (entry, where, kind, aux = null) => describeEntry(
		layout, entry, kind, SOURCE[where],
	).map((d) => ({
		index: d.index,
		// `Peak_dose#target [Cs-137]` is the name of a slot, not of anything
		// anybody wrote: what they wrote is a field of `Peak_dose`.
		label: aux ? d.label.replace(entry.name, aux.owner) : d.label,
		unit: aux ? unitOfField(aux.key, entry.block, d.unit) : d.unit,
		value: rows[d.source][d.offset],
	}));

	/**
	 * One block's values, and the values of the equations it is made of.
	 *
	 * `own` is what the chart would draw for it; `fields` is keyed by the
	 * property the equation was written in -- `initial`, `equation`, `rate`,
	 * `target`, `delay`, `first`, `second`, and a far-field path's own
	 * properties. A dialog asks for the field it is drawing a box for; the
	 * Information view asks for `own`.
	 */
	const describe = (name) => {
		const it = own.get(name);
		const block = it?.entry.block ?? null;
		const map = block ? fields.get(block) : null;
		if (!it && !map) return null;
		const out = {
			kind: it?.kind ?? null,
			dims: it?.entry.dims ?? [],
			own: it ? read(it.entry, it.where, it.kind) : null,
			fields: new Map(),
		};
		for (const [key, f] of map ?? []) {
			const aux = f.entry.hidden ? { owner: name, key } : null;
			out.fields.set(key, read(f.entry, f.where, it?.kind ?? key, aux));
		}
		return out;
	};

	// Remembered, because the same block is asked about over and over: a grid
	// of fifty-three nuclides asks once per row, and every panel showing one
	// asks again on every edit. Slicing the values out is cheap; describing
	// them -- a label and a unit per index -- is not, and on a block carrying
	// a hundred and sixty thousand of them it is the whole cost. Only the
	// blocks actually asked about are kept, and the whole thing is thrown away
	// when the model changes.
	const asked = new Map();

	return {
		t0,
		size: own.size,
		of(name) {
			if (!asked.has(name)) asked.set(name, describe(name));
			return asked.get(name);
		},
	};
}

function fieldsOf(fields, block) {
	if (!block) return new Map();
	let m = fields.get(block);
	if (!m) { m = new Map(); fields.set(block, m); }
	return m;
}
