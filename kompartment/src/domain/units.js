/**
 * Units that follow from the model, rather than being typed in.
 *
 * Its own module, low in the stack, because both sides need it: the editor
 * keeps the stored units in step after every edit, and Project falls back to
 * the same derivation for a file that never passed through the editor. The one
 * thing it imports is how a block is addressed, which is ./systems.js and is a
 * leaf itself.
 */

import { qualifiedName } from './systems.js';

/**
 * Automatic units for fluxes, the one piece of Ecolego's unit management this
 * tool keeps.
 *
 * A transfer's unit is not an independent fact: it follows from what the rate
 * equation *means*, which the "multiply by donor" flag decides.
 *
 *   multiply by donor   the equation is a rate coefficient      1/<time>
 *   otherwise           the equation is an absolute flux        <donor>/<time>
 *
 * The donor is the `from` compartment. For an inflow from outside there is no
 * donor, so the recipient sets the scale instead -- the flux is measured in
 * whatever it delivers. A `source` block is that same case by another name, so
 * it derives too.
 *
 * Units are labels here, never arithmetic: they reach the chart, the table and
 * the CSV, and nothing else. That is what makes deriving them safe.
 */
export function timeUnit(project) {
	return project.simulation?.time_unit ?? 'year';
}

function unitOfCompartment(project, name) {
	if (name == null) return '';
	// By qualified name: an endpoint is stored qualified (`NearField.Water`),
	// and matching it against a block's *local* name found nothing for every
	// compartment inside a sub-system -- so a flux out of one derived no unit
	// at all -- and found the wrong block when a root `Water` shared its name
	// with one in a sub-system.
	const c = (project.compartments ?? []).find((x) => qualifiedName(x) === name)
		?? (project.compartments ?? []).find((x) => x.name === name);
	return c ? String(c.unit ?? '').trim() : '';
}

/** `Bq/m3` over a year is `(Bq/m3)/year`, not `Bq/m3/year`. */
function per(quantity, time) {
	return /[/\s]/.test(quantity) ? `(${quantity})/${time}` : `${quantity}/${time}`;
}

/**
 * The unit a transfer or source *should* carry, given the model around it.
 *
 * Returns '' when it cannot be known -- a flux out of a compartment that has
 * no unit of its own. Blank is how this tool already says "no unit given", and
 * inventing one would be worse than saying nothing.
 */
export function derivedUnit(project, block, kind = 'transfer') {
	const t = timeUnit(project);
	if (kind === 'inflow') {
		const u = unitOfCompartment(project, block.to);
		return u ? per(u, t) : '';
	}
	// A rate coefficient is per unit time whatever it moves.
	if (block.multiply_by_donor !== false) return `1/${t}`;
	// A release out of a far-field path is that path's own value, and a path's
	// value is already an inventory per unit time -- so it is used as it
	// stands rather than divided by the time again.
	const path = (project.farfields ?? []).find((f) => qualifiedName(f) === block.from)
		?? (project.farfields ?? []).find((f) => f.name === block.from);
	if (path) return String(path.unit ?? '').trim();
	const u = unitOfCompartment(project, block.from ?? block.to);
	return u ? per(u, t) : '';
}

/** True for the kinds whose unit is derived rather than typed. */
export const DERIVED_UNIT_KINDS = ['transfer', 'inflow'];

/**
 * What a radionuclide inventory is measured in, as a label.
 *
 * Read off the model rather than passed in, because two shapes of the same
 * model reach this module: the editor's raw object, which spells it
 * `decay_unit`, and a Project, which spells it `decayUnit`.
 */
export function inventoryUnit(project) {
	const given = String(project?.decayUnit ?? project?.decay_unit ?? '').trim();
	return given === 'mol' ? 'mol' : 'Bq';
}

/**
 * The unit one material is measured in.
 *
 * Ecolego holds a unit per material -- `IMaterial.getUnit()` -- and a
 * compartment reads it from the material at the index rather than carrying one
 * of its own, which is what `Compartment.getUnit(indices)` does when it is
 * auto-managing: it looks each index up in the material model and returns that
 * material's unit.
 *
 * A radionuclide's is not stored. the contaminant catalogue keeps one decay unit for the
 * whole model and holds every nuclide's own equal to it, so it follows
 * `decay_unit` and cannot drift from the decay term it labels -- an inventory
 * is an activity or an amount, and there is no third thing it could be. Only a
 * material that is *not* a radionuclide carries a unit of its own, and the
 * corpus is full of them: stable carbon in kgC beside C-14 in Bq, water in
 * m^3, a Lotka-Volterra population in rabbits.
 *
 * @returns the unit, or '' for a material that has none and is not a nuclide
 */
export function materialUnit(project, name) {
	const lists = project?.index_lists ?? [];
	const catalogue = lists.find((l) => l?.for_contaminants) ?? null;
	const own = (catalogue?.indices ?? []).find((i) => i?.name === name);
	const stated = String(own?.unit ?? '').trim();
	if (stated) return stated;
	const nuclides = lists.find((l) => l?.for_nuclides) ?? catalogue;
	const isNuclide = nuclides
		? (nuclides.indices ?? []).some((i) => (typeof i === 'string' ? i : i?.name) === name)
		// The `nuclides: [...]` shorthand, in a file the editor has not yet
		// materialised: the names in it are radionuclides by construction.
		: (project?.nuclides ?? []).includes(name);
	return isNuclide ? inventoryUnit(project) : '';
}

/**
 * The one unit a whole material dimension is in, or '' if they differ.
 *
 * A compartment on the radionuclides is in one unit, because every index of it
 * is a radionuclide and they all follow the model's. A compartment on the
 * catalogue may not be: stable carbon in kgC sits beside C-14 in Bq, and no
 * single label is true of both. Then the block carries none and each series
 * takes its own -- see `Results.outputs`.
 */
export function dimensionUnit(project, listName) {
	const lists = project?.index_lists ?? [];
	const list = lists.find((l) => l?.name === listName);
	// A shorthand file names the dimension without writing the list down --
	// `materialDimensionName` still answers with it -- and every name in it is
	// a radionuclide, so the dimension is in the model's inventory unit.
	if (!list) {
		return lists.some((l) => l?.for_contaminants || l?.for_nuclides)
			? '' : inventoryUnit(project);
	}
	let one = null;
	for (const i of list.indices ?? []) {
		if (typeof i === 'object' && i?.enabled === false) continue;
		const u = materialUnit(project, typeof i === 'string' ? i : i?.name);
		if (!u) return '';
		if (one == null) one = u;
		else if (one !== u) return '';
	}
	return one ?? '';
}

/**
 * Fills in the unit of a compartment indexed by a material dimension.
 *
 * A compartment on that dimension holds an inventory of a material, and for a
 * radionuclide there are exactly two things that can be measured in -- an
 * activity or an amount -- so its unit is no more an independent fact than a
 * flux's is. Ecolego settles that model-wide rather than per block:
 * the contaminant catalogue keeps one unit and holds every nuclide's own unit equal to
 * it.
 *
 * Only a *blank* unit is filled in. A compartment that says `Bq/m3` means it;
 * one that says the other inventory unit is a mistake worth reporting rather
 * than one worth overwriting -- unitProblems says so. The one thing that does
 * relabel is changing the model's choice, which is setDecayUnit's job.
 *
 * And only when the dimension has one unit to give. A compartment on the
 * catalogue of a model that carries stable carbon beside C-14 is in kgC at one
 * index and Bq at the next, and writing either on the block would be a label
 * that is wrong half the time; left blank, each series carries the unit of the
 * material it holds.
 *
 * @param materialLists the material dimensions -- a name or an array of them,
 *   or null for a model that has none, where there is no inventory unit to
 *   apply and a compartment holds whatever its author says it holds
 * @param dimsOf how to read a block's dimensions; the default reads them as
 *   written, which is what the editor's model always has
 * @returns the names of the compartments it filled in
 */
export function syncInventoryUnits(project, materialLists, dimsOf = null) {
	const names = (Array.isArray(materialLists) ? materialLists : [materialLists])
		.filter(Boolean);
	if (!names.length) return [];
	const dims = dimsOf ?? ((c) => c.index_lists ?? []);
	const want = new Map(names.map((n) => [n, dimensionUnit(project, n)]));
	const filled = [];
	for (const c of project?.compartments ?? []) {
		const on = dims(c).find((d) => want.has(d));
		if (!on) continue;
		if (String(c.unit ?? '').trim()) continue;
		const u = want.get(on);
		if (!u) continue;
		c.unit = u;
		filled.push(c.name);
	}
	return filled;
}

/**
 * Brings every derived unit up to date.
 *
 * Called after any edit rather than at each of the half-dozen places that can
 * invalidate one -- the donor's unit, the donor itself, the multiply-by-donor
 * flag, the simulation's time unit, or a paste into the JSON tab. Returns the
 * names of the blocks it changed, so a caller can say what happened.
 */
export function syncDerivedUnits(project) {
	const changed = [];
	for (const [collection, kind] of [['transfers', 'transfer'], ['inflows', 'inflow']]) {
		for (const block of project[collection] ?? []) {
			const want = derivedUnit(project, block, kind);
			const have = String(block.unit ?? '');
			if (have === want) continue;
			if (want) block.unit = want;
			else delete block.unit;
			changed.push(block.name);
		}
	}
	return changed;
}
