/**
 * Model editing operations.
 *
 * These are pure functions over the plain project object -- no DOM, no
 * validation side effects -- so the graphical editor and the tests exercise
 * exactly the same code.
 *
 * Referential integrity is the whole point of putting them here: renaming a
 * compartment has to follow through into every transfer endpoint and every
 * equation that mentions it, and deleting one has to be refused when something
 * still refers to it.
 */

import { tokenize, parse, collectReferences, ParseError } from '../parser/parser.js';
import { describePDF } from './pdf.js';
import { NAME_RE, RESERVED } from './names.js';
import {
	NUCLIDE_LIST,
	MATERIAL_LIST,
	ELEMENT_LIST,
	COMPARTMENT_LIST,
	TRANSFER_LIST,
	deriveElements,
	deriveBlockLists,
	splitMaterialRoles,
	sharedDims,
	summedDims,
	summedDimsWhy,
	lineage,
	clashingDimensions,
	clashingDimensionsWhy,
	listApplies,
	listAppliesWhy,
	isDecayDim,
	parentListName,
} from './indexlists.js';
import {
	RECORDER_KINDS,
	EQUATION_FIELDS,
	EVENT_FIELDS,
	EXTREMES,
	DIRECTIONS,
	RECORDER_COLLECTION,
} from './recorders.js';
import {
	HALF_LIVES as BUILT_IN_HALF_LIVES,
	defaultChains,
	DECAY_UNITS,
	elementOf,
} from './nuclides.js';
import {
	derivedUnit,
	timeUnit,
	DERIVED_UNIT_KINDS,
	inventoryUnit,
	materialUnit,
	dimensionUnit,
	syncDerivedUnits as syncFluxUnits,
	syncInventoryUnits,
} from './units.js';
import {
	parseUnit,
	equationUnit,
	namesSomething,
	sameUnit,
	scaleText,
	scaleLiterals,
} from './unitcheck.js';
import {
	qualifiedName,
	systemOf,
	qualify,
	parentOf,
	parts,
	baseName,
	systemPaths,
	isWithin,
	reparent,
	isValidPath,
	resolveReference,
	referenceFrom,
	scopeChain,
} from './systems.js';
import { layoutFlow, hangRows, onGrid, alignBoxes, ARRANGEMENTS } from './layout.js';
// The two layers underneath this one, lifted out of it. Re-exported below, so
// that the ninety-odd places importing `edit` for `findBlock` or
// `integrationFingerprint` did not all have to learn where they moved to.
import {
	KINDS,
	SINGULAR,
	PLURAL,
	allBlocks,
	blockIndex,
	findBlock,
	blockNames,
	nameTaken,
	knownNames,
	functionLocals,
} from './blocks.js';
import { integratingBlocks, integrationFingerprint } from './fingerprint.js';
import * as tr from './transport.js';
import { switchTimeProblems } from './switchtimes.js';
import { derivedProblems } from './derived.js';
import {
	SPACINGS,
	SERIES_KINDS,
	combineSeries,
	seriesTimes,
	seriesKind,
	describeSeries,
	droppedTimes,
	clippedEnds,
	fmtTime,
} from './timeseries.js';
import {
	FARF_DEFAULTS,
	FARF_EQUATION_KEYS,
	FARF_NUCLIDE_KEYS,
	FARF_SINGLE_KEYS,
	FARF_STRUCTURE_KEYS,
	FARF_HELP,
	FARF_LABEL,
	FARF_TERM,
	OUTFLOWS,
	OUTFLOW_LABEL,
	CONTINUES,
	cellCount,
	cellNames,
	structureProblem,
	geometryProblem,
	dispersionWarning,
	gridPeclet,
	extraCells,
	isSemiAnalytic,
} from './farfield.js';
import {
	WASTE_EQUATION_KEYS, WASTE_NUCLIDE_KEYS, WASTE_LABEL, WASTE_HELP, WASTE_DEFAULTS,
	wasteProblems, describeWaste,
} from './wastepackage.js';
import {
	DIS_EQUATION_KEYS, DIS_DEFAULTS, disruptionProblems, describeDisruption,
} from './disruption.js';
import { schemeOf, operandKeys, OPERAND_KEYS } from './availability.js';

export {
	KINDS, SINGULAR, PLURAL, allBlocks, blockIndex, findBlock, blockNames,
	nameTaken, knownNames, functionLocals,
} from './blocks.js';
export { integratingBlocks, integrationFingerprint } from './fingerprint.js';

export class EditError extends Error {
	constructor(message, detail) {
		super(message);
		this.name = 'EditError';
		this.detail = detail ?? null;
	}
}




/**
 * What each kind of block is called in the interface, in the plural.
 *
 * Here rather than in a view because the search chips, the block tree and the
 * add menus all name the same thing, and they have to name it the same way.
 */
export const KIND_LABEL = {
	compartment: 'Compartments',
	transfer: 'Transfers',
	inflow: 'Inflows',
	expression: 'Expressions',
	parameter: 'Parameters',
	lookup: 'Lookup tables',
	index_reduction: 'Reduce over an index',
	block_reduction: 'Combine blocks',
	function: 'Functions',
	min_max: 'Min/max',
	running_mean: 'Running means',
	snapshot: 'Snapshots',
	delay: 'Delays',
	trigger: 'Triggers',
	farfield: 'Far-field pathways',
	waste_package: 'Waste packages',
	event: 'Events',
	// Not block kinds: two sorts of result a far-field path reports, which the
	// chart's filter chips name through this same table. Without them a chip
	// read "farfield_inventorys".
	farfield_inventory: 'Path inventories',
	farfield_cell: 'Path cells',
	waste_inventory: 'Package inventories',
};

// What a name may be: the identifier rule and the reserved names, shared
// with `Project` and the importer. See ./names.js.

/**
 * The diagram layout, prototype-free and ready to be written into.
 *
 * Every path that *writes* a position goes through here rather than touching
 * `project.layout` directly, and it is the only place the map is created --
 * created as `{}` somewhere else, the next write undoes this.
 *
 * Reading a plain map is harmless (`getPosition` asks for coordinates and
 * `Object.prototype` has none), but three other things are not: `map[name] =`
 * with `name` of `__proto__` on a fresh object reaches the prototype,
 * `entry.x = ...` after `map.__proto__` then writes to every object in the
 * program, and `name in map` answers yes for names nobody placed. All three
 * were live: renaming a block a file called `__proto__` put `x` and `y` on
 * `Object.prototype` before anything had been dragged.
 */
function layoutOf(project) {
	if (!project.layout || Object.getPrototypeOf(project.layout) !== null) {
		project.layout = Object.assign(Object.create(null), project.layout ?? {});
	}
	return project.layout;
}

/**
 * `C1`, `C2`, ... skipping whatever is already used *in that sub-system*.
 * `base` is a local name, and so is the result.
 */
export function uniqueName(project, base, system = '') {
	const free = (local) => !idTaken(project, qualify(system, local));
	if (free(base)) return base;
	for (let i = 1; i < 10000; i++) {
		if (free(`${base}${i}`)) return `${base}${i}`;
	}
	throw new EditError(`Could not find a free name based on '${base}'`);
}

/**
 * `name` is a local name; `system` says which sub-system it has to be unique
 * in, since that is the scope Ecolego makes names unique in.
 */
export function validateName(project, name, { allow, system = '' } = {}) {
	if (!NAME_RE.test(name ?? '')) {
		return 'Use letters, digits and underscore; do not start with a digit.';
	}
	if (RESERVED.has(name)) return `'${name}' is a reserved name.`;
	const target = qualify(system, name);
	if (target !== allow && nameTaken(project, target)) {
		return system
			? `'${name}' is already used by another block in '${system}'.`
			: `'${name}' is already used by another block.`;
	}
	// A sub-system is the other thing an id can be. Ecolego has one namespace
	// for both -- the rule for which blocks a sub-system may hold says so, and
	// `moveSystem` here already refuses the mirror image -- and letting the
	// two collide made a selection ambiguous: `selectionParts` asks about
	// sub-systems first, so deleting the block deleted the sub-system's
	// contents instead.
	if (target !== allow && systems(project).includes(target)) {
		return `'${name}' is already used by a sub-system.`;
	}
	return null;
}

/**
 * Whether a name is already somebody's: a block's or a sub-system's.
 *
 * The two share one namespace, so anything choosing a free name has to ask
 * about both -- `uniqueName` used to ask only about blocks and would hand
 * back the name of a sub-system standing right beside it.
 */
export function idTaken(project, name) {
	return nameTaken(project, name) || systems(project).includes(name);
}

// --- creation -------------------------------------------------------------

function ensure(project, kind) {
	if (!Array.isArray(project[kind])) project[kind] = [];
	return project[kind];
}

// Every `add` takes the sub-system the block belongs to. It defaults to the
// root, so a caller that has never heard of sub-systems behaves as before.
const placed = (block, system) => (system ? { ...block, system } : block);

export function addCompartment(project, { name, at, system = '' } = {}) {
	const n = name ?? uniqueName(project, 'C', system);
	const block = placed({
		// Labelled in whatever this model's inventories are in, the way
		// the rule for a new nuclide gives a new nuclide the material
		// model's decay unit. A new compartment in a model that counts atoms
		// should not arrive saying Bq.
		name: n, initial: '0', unit: decayUnit(project), handle_decay: true,
		index_lists: defaultDimsFor(project, 'compartment'),
	}, system);
	ensure(project, 'compartments').push(block);
	if (at) setPosition(project, qualify(system, n), at);
	return block;
}

export function addExpression(project, { name, equation, system = '' } = {}) {
	const n = name ?? uniqueName(project, 'E', system);
	const block = placed({
		name: n, equation: equation ?? '0', unit: '',
		index_lists: defaultDimsFor(project, 'expression'),
	}, system);
	ensure(project, 'expressions').push(block);
	return block;
}

export function addParameter(project, { name, value, system = '' } = {}) {
	const n = name ?? uniqueName(project, 'p', system);
	const block = placed({
		name: n, value: value ?? 0, unit: '',
		index_lists: defaultDimsFor(project, 'parameter'),
	}, system);
	ensure(project, 'parameters').push(block);
	return block;
}

/**
 * A lookup table: a value that follows a series of points rather than an
 * equation. New ones start as a flat line at zero over the simulated span, so
 * the block is usable the moment it exists and its editor has something to
 * draw; Ecolego starts with an empty table, which reads as zero anyway.
 */
export function addLookup(project, { name, points, system = '' } = {}) {
	const n = name ?? uniqueName(project, 'L', system);
	const start = Number(project.simulation?.start_time ?? 0);
	const end = Number(project.simulation?.end_time ?? 1);
	const block = placed({
		name: n, unit: '', interpolation: 'linear', cyclic: false,
		points: points ?? [[Number.isFinite(start) ? start : 0, 0],
			[Number.isFinite(end) && end > start ? end : start + 1, 0]],
		index_lists: defaultDimsFor(project, 'lookup'),
	}, system);
	ensure(project, 'lookups').push(block);
	return block;
}

/**
 * An index operation: one block, reduced along one of its index lists.
 *
 * Its dimensions are the target's minus the one it reduces over, which is what
 * makes the block mean anything at all -- so they are worked out here rather
 * than left to the caller.
 */
export function addIndexOperation(project, { name, target, operation, over, system = '' } = {}) {
	const n = name ?? uniqueName(project, 'Total', system);
	const found = target ? findBlock(project, target) : null;
	const dims = effectiveDims(project, found?.block ?? {});
	// Reduce over the named list, or the first one, keeping the rest.
	const reduced = over && dims.includes(over) ? over : dims[0];
	const block = placed({
		name: n, target: target ?? null, operation: operation ?? 'sum', unit: '',
		index_lists: dims.filter((d) => d !== reduced),
	}, system);
	ensure(project, 'index_reductions').push(block);
	return block;
}

/**
 * Points an index operation at a different block, and re-derives its
 * dimensions from that block's.
 *
 * The two belong together: an index operation *is* its target with one
 * dimension collapsed, so a target whose dimensions do not match leaves a
 * block that cannot be built. Ecolego keeps them in step the same way --
 * the dimension rule listens for the target's dimensions
 * changing and resets its own.
 */
export function setReductionTarget(project, name, target, { over = null } = {}) {
	const found = findBlock(project, name);
	if (!found || found.kind !== 'index_reduction') {
		throw new EditError(`'${name}' is not an index operation`);
	}
	const block = found.block;
	block.target = target || null;
	if (!target) return block;
	const t = findBlock(project, target);
	if (!t) throw new EditError(`No block named '${target}'`);
	const dims = effectiveDims(project, t.block);
	// Keep whichever list it already reduced, when the new target has it.
	// `block._over` used to stand here and was never written by anything, so
	// re-pointing a reduction always fell back to the first dimension.
	const keep = over ?? reducedList(block, dims);
	const reduced = keep && dims.includes(keep) ? keep : dims[0];
	block.index_lists = dims.filter((d) => d !== reduced);
	delete block.per_nuclide;
	return block;
}

/**
 * Which of its target's dimensions a reduction collapses.
 *
 * Not stored: an index operation *is* its target with one dimension gone, so
 * the one it reduces is the one the target has and it does not. Null when that
 * does not single one out -- a target that has just gained two dimensions, or
 * one whose dimensions the reduction has drifted away from entirely.
 */
function reducedList(op, dims) {
	const own = new Set(op.index_lists ?? []);
	const missing = dims.filter((d) => !own.has(d));
	return missing.length === 1 ? missing[0] : null;
}

/**
 * Re-derives the dimensions of every reduction that reads a block.
 *
 * The same bargain `syncConnectionDims` makes, for the same reason. An index
 * operation is its target with one dimension collapsed and an aggregate is the
 * union of its targets' dimensions, so changing a block's dimensions changes
 * theirs -- and leaving them behind is not a warning but a broken model: the
 * builder needs the reduction's shape to match what it reduces, and a
 * reduction one dimension too wide reads the same slot repeatedly instead.
 * Ecolego keeps them in step the same way, through
 * the dimension rule.
 *
 * @param blockName re-derive only the reductions reading this block, or every
 *   reduction when null.
 */
export function syncReductionDims(project, blockName = null) {
	const known = knownNames(project);
	const dimsOf = (ref, system) => {
		const q = resolveReference(String(ref ?? ''), system, known);
		if (!q) return null;
		if (blockName != null && q !== blockName) return null;
		const found = findBlock(project, q);
		return found ? effectiveDims(project, found.block) : null;
	};
	const touched = [];

	for (const o of project.index_reductions ?? []) {
		if (!o.target) continue;
		const dims = dimsOf(o.target, systemOf(o));
		if (!dims) continue;
		const keep = reducedList(o, dims);
		const reduced = keep && dims.includes(keep) ? keep : dims[0];
		const next = dims.filter((d) => d !== reduced);
		if (sameList(o.index_lists ?? [], next)) continue;
		o.index_lists = next;
		pruneEntriesToDims(o, next);
		touched.push(o.name);
	}

	for (const g of project.block_reductions ?? []) {
		const system = systemOf(g);
		// An aggregate reduces several blocks element-wise, so it has to be
		// wide enough to reach all of them: the union, which is what
		// `addAggregate` builds.
		let reads = blockName == null;
		const union = [];
		for (const ref of g.targets ?? []) {
			const q = resolveReference(String(ref ?? ''), system, known);
			if (!q) continue;
			if (q === blockName) reads = true;
			const found = findBlock(project, q);
			for (const d of found ? effectiveDims(project, found.block) : []) {
				if (!union.includes(d)) union.push(d);
			}
		}
		if (!reads || sameList(g.index_lists ?? [], union)) continue;
		g.index_lists = union;
		pruneEntriesToDims(g, union);
		touched.push(g.name);
	}

	return touched;
}

/** Every block a reduction could sensibly be pointed at. */
export function reducibleBlocks(project, { indexed = false } = {}) {
	return allBlocks(project)
		.filter((b) => b.kind !== 'transfer' && b.kind !== 'inflow')
		.filter((b) => !indexed || effectiveDims(project, b).length > 0)
		.map((b) => qualifiedName(b));
}

/** An block_reduction: several blocks, reduced element-wise at each index. */
export function addAggregate(project, { name, targets, operation, system = '' } = {}) {
	const n = name ?? uniqueName(project, 'Sum', system);
	const list = targets ?? [];
	// Wide enough to reach every target: the union of what they are indexed by.
	const dims = [];
	for (const t of list) {
		const found = findBlock(project, t);
		for (const d of effectiveDims(project, found?.block ?? {})) {
			if (!dims.includes(d)) dims.push(d);
		}
	}
	const block = placed({
		name: n, targets: [...list], operation: operation ?? 'sum', unit: '',
		index_lists: dims,
	}, system);
	ensure(project, 'block_reductions').push(block);
	return block;
}

/**
 * The names an equation carries that are nobody's block.
 *
 * One case so far: a user-defined function's body may name its parameters, and
 * a parameter may shadow a block -- `ADV(position, kd)` in a model full of Kd
 * values is Ecolego's own example. Every walk over equations goes through
 * `forEachEquation`, which asks this, so a rename cannot reach into a body and
 * rewrite a parameter, and nothing counts one as a reference.
 */

/**
 * Sets the parameters of a function, refusing what a body could not use.
 *
 * The rules are `Project`'s, applied as the box is typed in rather than when
 * the model is next loaded: a name the parser can read, no repeats, nothing
 * reserved, and nothing that is already a block. That last one is what keeps
 * the single name space single -- see the note in ./project.js.
 */
export function setFunctionParameters(project, name, list) {
	const found = findBlock(project, name);
	if (!found || found.kind !== 'function') {
		throw new EditError(`No function named '${name}'`);
	}
	const taken = new Set(blockNames(project));
	const seen = new Set();
	const out = [];
	for (const raw of list ?? []) {
		const p = String(raw ?? '').trim();
		if (!p) continue;
		if (!NAME_RE.test(p)) {
			throw new EditError(
				`'${p}' is not a valid parameter name: letters, digits and underscore, `
				+ 'not starting with a digit.',
			);
		}
		if (RESERVED.has(p)) throw new EditError(`'${p}' is the name of a built-in function.`);
		if (seen.has(p)) throw new EditError(`'${p}' is named twice.`);
		if (taken.has(p)) {
			throw new EditError(
				`'${p}' is already a block in this model, so the body would have no way `
				+ 'to mean the block. Choose another name for the parameter.',
			);
		}
		seen.add(p);
		out.push(p);
	}
	found.block.parameters = out;
	return out;
}

/**
 * A user-defined function: one body, called from any equation.
 *
 * No position: a function is drawn nowhere, having no value of its own to
 * draw. It does live in a sub-system like any other block, and its body reads
 * that sub-system's names wherever it is called from. See ../sim/functions.js.
 */
export function addFunction(project, { name, parameters, equation, unit, system = '' } = {}) {
	const n = name ?? uniqueName(project, 'Func', system);
	const params = (parameters ?? ['x']).map((p) => String(p ?? '').trim()).filter(Boolean);
	const block = {
		...(system ? { system } : {}),
		name: n,
		parameters: params,
		// Empty on purpose: a function with a body that is a guess is worse
		// than one the problem strip asks you to write. The dialog opens on
		// it, and until it is written the model says so rather than running.
		equation: equation ?? '',
		unit: unit ?? '',
	};
	ensure(project, 'functions').push(block);
	return block;
}

/**
 * One of the five blocks that depend on what has already happened.
 *
 * They all take the same shape -- a target to watch and, for some of them, an
 * event to be driven by -- so one function makes all five. A new one is
 * indexed the way its target is, which is what the format's own delay
 * does and what makes `Peak[nuclide]` follow `Dose[nuclide]` without asking.
 */
export function addRecorder(project, kind, { name, target, system = '', ...rest } = {}) {
	if (!RECORDER_KINDS.includes(kind)) {
		throw new EditError(`'${kind}' is not a block that remembers`);
	}
	const base = { min_max: 'Peak', running_mean: 'Mean', snapshot: 'Snapshot',
		delay: 'Delayed', trigger: 'Trigger' }[kind];
	const n = name ?? uniqueName(project, base, system);

	// Indexed like whatever it watches, so the two line up without the user
	// having to say so.
	const watched = kind === 'trigger' ? (rest.first ?? null) : target;
	const found = watched ? findBlock(project, resolveReference(
		String(watched).trim(), system, (x) => nameTaken(project, x),
	) ?? watched) : null;
	const dims = found ? [...effectiveDims(project, found.block)] : [];

	const fields = { index_lists: dims, unit: '' };
	if (kind === 'trigger') {
		fields.first = rest.first ?? '0';
		fields.second = rest.second ?? '0';
		fields.direction = rest.direction ?? 'rising';
		if (!DIRECTIONS.includes(fields.direction)) {
			throw new EditError(
				`'${fields.direction}' is not a crossing direction `
				+ `(${DIRECTIONS.join(', ')})`,
			);
		}
	} else {
		fields.target = target ?? '0';
	}
	if (kind === 'min_max') {
		fields.operation = rest.operation ?? 'max';
		if (!EXTREMES.includes(fields.operation)) {
			throw new EditError(
				`'${fields.operation}' is not a min/max operation (${EXTREMES.join(', ')})`,
			);
		}
	}
	if (kind === 'snapshot') {
		fields.trigger = rest.trigger ?? null;
		fields.initial = rest.initial ?? '0';
	}
	if (kind === 'delay') fields.delay = rest.delay ?? '0';
	if (kind === 'min_max' || kind === 'running_mean') {
		fields.reset_trigger = rest.reset_trigger ?? null;
		fields.start_trigger = rest.start_trigger ?? null;
		fields.stop_trigger = rest.stop_trigger ?? null;
	}

	const block = placed({ name: n, ...fields }, system);
	ensure(project, RECORDER_COLLECTION[kind]).push(block);
	return block;
}

/** Blocks a recorder could watch: anything with a value of its own. */
export function watchableBlocks(project) {
	return allBlocks(project)
		.filter((b) => b.kind !== 'transfer' && b.kind !== 'inflow'
			&& b.kind !== 'trigger')
		.map((b) => qualifiedName(b.block));
}

/** The discrete events in the model, which is what an event field may name. */
export function discreteEvents(project) {
	return (project.triggers ?? []).map((b) => qualifiedName(b));
}

export function addSource(project, { name, to, rate, system } = {}) {
	if (!to) throw new EditError('A source needs a target compartment');
	to = transportEndpoint(project, to, 'to');
	// A far-field path counts: a source term is a delivery from outside the
	// model, and a path is somewhere it can be delivered.
	const problem = endpointProblem(project, to, 'to');
	if (problem) throw new EditError(problem);
	// A source has no donor, so it lives with the compartment it feeds.
	const home = system ?? connectionHome(null, to);
	const n = name ?? uniqueName(project, 'In', home);
	// What the compartment it feeds is indexed by: a source is a transfer from
	// outside, and the desktop tool gives one the whole of its target's
	// dimensions. A fixed per-nuclide default was wrong the moment the
	// compartment was on anything else.
	const shared = transferDims(project, { from: null, to });
	const block = placed({
		name: n, to, rate: rate ?? '0', unit: 'Bq/year',
		index_lists: shared ? [...shared.dims] : defaultDimsFor(project, 'inflow'),
	}, home);
	ensure(project, 'inflows').push(block);
	return block;
}

/**
 * A far-field path: a dual-porosity transport model behind one block.
 *
 * It arrives indexed by the radionuclides when the model has them -- one path
 * per nuclide, with the decay chain running between them -- and by nothing
 * otherwise: one quantity that does not decay, which the dimension box can
 * turn into a path per chemical species, per object, or whatever else the
 * model's lists hold. Nothing about a path needs a nuclide: a species that is
 * stable, or on a list that is not the radionuclides, simply does not decay.
 * The reference implementation's own numbers
 * for the physics -- twenty cells by twenty layers is what SKB's assessments
 * use -- and this tool's for the outlet and the matrix layers; see
 * `FARF_DEFAULTS`.
 */
export function addFarfield(project, { name, at, system = '' } = {}) {
	const n = name ?? uniqueName(project, 'Farfield', system);
	// Both forms of the dimension: a flagged index list, or the older
	// `nuclides` shorthand that Project desugars into one.
	const list = materialDimensionName(project);
	const block = placed({
		name: n, ...FARF_DEFAULTS,
		unit: `${decayUnit(project)}/${project.simulation?.time_unit ?? 'year'}`,
		// Indexed by the radionuclides, which is what a path is most often
		// for; with none, by nothing, and the dimension box in the panel is
		// where anything else is chosen.
		index_lists: list ? [list] : [],
	}, system);
	ensure(project, 'farfields').push(block);
	if (at) setPosition(project, qualify(system, n), at);
	return block;
}

/**
 * Adds a set of waste packages: the source term with its barriers, as one
 * block. Indexed by the radionuclides when the model has them, and by nothing
 * otherwise -- one quantity in a container that fails. See ./wastepackage.js.
 */
export function addWastePackage(project, { name, at, system = '' } = {}) {
	const n = name ?? uniqueName(project, 'Packages', system);
	const list = materialDimensionName(project);
	const block = placed({
		name: n, ...WASTE_DEFAULTS,
		unit: `${decayUnit(project)}/${project.simulation?.time_unit ?? 'year'}`,
		index_lists: list ? [list] : [],
	}, system);
	ensure(project, 'waste_packages').push(block);
	if (at) setPosition(project, qualify(system, n), at);
	return block;
}

/** How many states a set of waste packages puts in the vector: intact and exposed, per index. */
export function wasteStates(project, block) {
	const width = combinationCount(project, effectiveDims(project, block));
	return { states: 2 * width, width };
}

export { describeWaste };

/**
 * Adds a disruptive event: something that happens to the model at an instant,
 * once or at random. Indexed by nothing; it acts on whole blocks. See
 * ./disruption.js.
 */
export function addDisruption(project, { name, at, system = '' } = {}) {
	const n = name ?? uniqueName(project, 'Event', system);
	const block = placed({ name: n, ...DIS_DEFAULTS, actions: [], unit: '', index_lists: [] }, system);
	ensure(project, 'events').push(block);
	if (at) setPosition(project, qualify(system, n), at);
	return block;
}

export { describeDisruption };

/**
 * What is worth saying about a path before it is run, beyond what makes it
 * invalid. Two things a model can legally ask for and probably does not mean.
 *
 * @returns {string|null}
 */
export function farfieldWarning(project, block) {
	// Worked out exactly, the release is the flux past the far end and
	// nothing else: there are no cells to read it inside, or to extrapolate.
	if (isSemiAnalytic(block)) return null;
	const releases = releaseTransfers(project, qualifiedName(block));
	if (!releases.length) return null;
	const where = releases.map((t) => t.to).filter(Boolean);
	if (!where.length) return null;
	// The semi-infinite outlet's extra cells are rock past the release point,
	// so what they hold has been released already. The reference
	// implementation's are the path's own, read inside.
	if (Number(block.o_b) !== CONTINUES && extraCells(block) > 0) {
		return `the release is read inside the path, ${extraCells(block)} cell`
			+ `${extraCells(block) === 1 ? '' : 's'} before its far end, so the mass `
			+ `it reports is still in the path: delivering it to `
			+ `${where.join(' and ')} counts it twice`;
	}
	// A quadratic extrapolation reads a negative flux before the front
	// arrives, and a compartment that cannot go negative deadlocks against it.
	if (Number(block.o_b) === 3) {
		const held = where.filter(
			(n) => findBlock(project, n)?.block?.non_negative !== false,
		);
		if (held.length) {
			return `a quadratically extrapolated outflow reads a negative flux at `
				+ `very early times, and ${held.join(' and ')} cannot go negative — `
				+ `the solver will stall. Use a linear outflow, or turn off "Cannot `
				+ `go negative" on ${held.length === 1 ? held[0] : 'those compartments'}`;
		}
	}
	return null;
}

/**
 * How many states a path costs, so the editor can say so before a run: cells
 * per nuclide times the nuclides, times whatever else it is indexed by.
 */
export function farfieldStates(project, block) {
	const cells = cellCount(block);
	// The same two calls `stateCount` makes, so the two cannot disagree -- and
	// `effectiveDims` is what accounts for a model still carrying the
	// `nuclides` shorthand rather than a written-down list.
	const width = combinationCount(project, effectiveDims(project, block));
	return { cells, states: cells * width };
}

/**
 * @param from  compartment name, or null for an external source
 * @param to    compartment name, or null for a sink
 */
/**
 * The sub-system a connection belongs in: its donor's.
 *
 * Not a matter of taste. Of the 1,333 transfers in the real models here whose
 * two ends are in different sub-systems, 1,333 sit with the donor and none at
 * the top level; all 358 outflows sit with the donor too. `Sub.C1 -> C2` is a
 * transfer out of `Sub`, and it is written from inside `Sub`, which is what
 * decides how its rate equation resolves.
 *
 * With no donor -- a source, or an inflow from outside the model -- there is
 * only the receiver to follow.
 */
export function connectionHome(from, to) {
	const end = from ?? to;
	return end == null ? '' : parentOf(end);
}

/**
 * Whether a name may be one end of a connection, and what to say when it may
 * not.
 *
 * A compartment may be either end. A far-field path may be the *receiving*
 * end -- a flux delivered into it lands in its first fracture cell -- but
 * never the donor: what leaves a path is its own release, read off the block,
 * and a transfer taking from a cell would take the same mass twice.
 *
 * One function because the four ways to make a connection -- drawing one,
 * dragging an end onto something else, the matrix grid, a hand-written file --
 * all have to agree about it, and they did not: the diagram offered a path as
 * a target and `addTransfer` then refused it.
 *
 * @returns {string|null} what is wrong, or null
 */
export function endpointProblem(project, name, end = 'to') {
	const found = findBlock(project, name);
	if (!found) return `'${name}' is not a block in this model`;
	if (found.kind === 'compartment') return null;
	// A far-field path is a legal endpoint either way round: a flux delivered
	// into it lands in its first fracture cell, and a line drawn out of it
	// carries the release out of its far end. What that line cannot do is end
	// at another path -- a release is an inventory per unit time arriving from
	// outside, and a path's inlet takes exactly that, but chaining two of them
	// with nothing in between hides where the mass is.
	if (found.kind === 'farfield') return null;
	// Waste packages release; nothing is delivered into them. A line drawn
	// out of the block carries what leaves the packages.
	if (found.kind === 'waste_package') {
		return end === 'from' ? null
			: `'${name}' is a set of waste packages: nothing flows into them, their release comes out`;
	}
	return `'${name}' is not a compartment`;
}

/** The kinds whose value is a release that a transfer drawn out of them carries. */
export const RELEASING = new Set(['farfield', 'waste_package']);

/**
 * A transfer that carries a far-field path's release rather than a flux
 * between two compartments.
 *
 * Its rate is not a number anybody types: it *is* the release out of the far
 * end of the path, which the block already works out. So the equation is the
 * path's own name and the editor holds it there -- a rate that could be edited
 * would be a second answer to a question the block has already answered.
 */
export function isReleaseTransfer(project, block) {
	if (!block || block.from == null) return false;
	return RELEASING.has(findBlock(project, block.from)?.kind);
}

/** The releases drawn out of one path, in the order they were drawn. */
export function releaseTransfers(project, pathName) {
	return (project.transfers ?? []).filter((t) => t.from === pathName);
}

/**
 * Why a second release out of a path is refused.
 *
 * A path has one release: it is the flux out of the far end of the fracture,
 * a single quantity the block works out for itself. Two transfers carrying it
 * would each deliver the whole of it, so the model would release twice what
 * the path let through -- and neither line would look wrong. The diagram, the
 * transfer grid and the panel all went through `addTransfer`, and none of them
 * stopped it.
 *
 * Not the same as a compartment, which may drain into several places at once:
 * there the rate of each is the modeller's to write, and the sum is the model.
 * Here there is nothing to divide.
 */
export function releaseTaken(project, pathName, { allow = null } = {}) {
	const held = releaseTransfers(project, pathName)
		.filter((t) => qualifiedName(t) !== allow);
	if (!held.length) return '';
	const to = held[0].to ?? 'outside the model';
	return `${pathName} already delivers its release to ${to}, as '${held[0].name}'. `
		+ `A block has one release -- for a path the flux out of the far end, for `
		+ `waste packages what leaves them -- and a second line carrying it would `
		+ `deliver the whole of it again. Move that one, or give ${to} a transfer onward.`;
}

/**
 * Sends a path's release to a compartment, or to nowhere.
 *
 * The same edit as drawing the line on the diagram, reached from the panel for
 * the case where the compartment is off screen -- and the one place that knows
 * a path has exactly one release, so pointing it somewhere new moves the line
 * that is there rather than adding a second.
 *
 * @param to a compartment's qualified name, or null/'' for read-only
 * @returns the transfer, or null when the release was switched off
 */
export function setRelease(project, pathName, to) {
	const found = findBlock(project, pathName);
	if (!RELEASING.has(found?.kind)) {
		throw new EditError(`'${pathName}' has no release to send anywhere`);
	}
	const held = releaseTransfers(project, pathName);
	const target = to == null || to === '' ? null : String(to);

	if (target == null) {
		// Switched off: the line goes, and the flux stays readable as the
		// path's own name in any equation.
		for (const t of held) deleteBlock(project, qualifiedName(t));
		return null;
	}
	const problem = endpointProblem(project, target, 'to');
	if (problem) throw new EditError(problem);

	// Already there: nothing to do, and re-pointing a transfer at where it
	// already goes would rename it for no reason.
	if (held.length === 1 && held[0].to === target) return held[0];
	if (held.length) {
		// Move the one that is there. Any others are the ones this rule now
		// forbids -- a model saved before it existed -- and they go.
		const keep = held[0];
		for (const t of held.slice(1)) deleteBlock(project, qualifiedName(t));
		return setConnectionEnd(project, qualifiedName(keep), 'to', target);
	}
	return addTransfer(project, pathName, target);
}

export function addTransfer(project, from, to, { name, rate, system } = {}) {
	// A transport named as an end means its End as a donor and its Begin as a
	// receiver -- see `transportEndpoint`.
	from = transportEndpoint(project, from, 'from');
	to = transportEndpoint(project, to, 'to');
	if (from == null && to == null) {
		throw new EditError('A transfer needs a source, a target, or both');
	}
	if (from != null && from === to) {
		throw new EditError('A transfer cannot start and end at the same compartment');
	}
	for (const [end, v] of [['from', from], ['to', to]]) {
		if (v == null) continue;
		const problem = endpointProblem(project, v, end);
		if (problem) throw new EditError(problem);
	}
	// A path has one release, and so have waste packages. See `releaseTaken`.
	if (from != null && RELEASING.has(findBlock(project, from)?.kind)) {
		const taken = releaseTaken(project, from);
		if (taken) throw new EditError(taken);
	}
	// Several transfers may join the same two compartments. A model often
	// separates the paths between two places -- advection and diffusion, or one
	// route per nuclide group -- and summing them by hand into a single rate
	// loses the ability to name, plot or switch off each one. The engine adds
	// the fluxes, which is what parallel paths mean.
	const home = system ?? connectionHome(from, to);
	const base = from && to
		? `${baseName(from)}_${baseName(to)}`
		: 'T';
	const n = name ?? uniqueName(project, base, home);
	// A transfer is indexed by the indices its two ends have in common -- see
	// `sharedDims`. Where the ends do not correspond, which Ecolego refuses
	// outright, it takes the union: that is the only shape that can reach both
	// ends at all, and the flux then needs `sum_extra_indices` before it will
	// build. Drawing the connection is not the same as meaning the total, so
	// the tick is left to the modeller and the problem strip asks for it.
	const shared = transferDims(project, { from: from ?? null, to: to ?? null });
	const endpointDims = shared ? [...shared.dims] : [];
	if (!shared) {
		for (const end of [from, to]) {
			if (end == null) continue;
			const f = findBlock(project, end);
			for (const d of effectiveDims(project, f.block)) {
				if (!endpointDims.includes(d)) endpointDims.push(d);
			}
		}
	}
	// A release out of a path: the rate is the path itself, and there is no
	// donor inventory to multiply by -- the mass has already left the path,
	// taken off its last cell by the outflow condition.
	const release = from != null && RELEASING.has(findBlock(project, from)?.kind);
	const block = {
		...(home ? { system: home } : {}),
		name: n, from: from ?? null, to: to ?? null,
		rate: release ? from : (rate ?? '0'),
		multiply_by_donor: release ? false : from != null,
		index_lists: endpointDims,
	};
	// Not a fixed '1/year': the unit follows from the donor and the model's
	// time unit. See ./units.js.
	const unit = derivedUnit(project, block, 'transfer');
	if (unit) block.unit = unit;
	ensure(project, 'transfers').push(block);
	return block;
}

/** Every transfer running from `from` to `to`, in the order they were added. */
export function transfersBetween(project, from, to) {
	return (project.transfers ?? []).filter((t) => t.from === from && t.to === to);
}

// --- mutation -------------------------------------------------------------

export function updateBlock(project, name, patch) {
	const found = findBlock(project, name);
	if (!found) throw new EditError(`No block named '${name}'`);
	// The two fields that are the block's identity go through the edits that
	// follow them through the model: a name assigned here would leave every
	// reference to the old one dangling.
	for (const key of ['name', 'system']) {
		if (key in (patch ?? {})) {
			throw new EditError(
				`'${key}' is not changed this way: use ${key === 'name' ? 'renameBlock' : 'moveBlock'}, `
				+ 'which follows the change through the references.',
			);
		}
	}
	Object.assign(found.block, patch);
	return found.block;
}

/**
 * Every equation in the model, with the sub-system it is written in.
 *
 * `fn(text, system)` returns replacement text, or undefined to leave it. Entry
 * equations are visited too: a per-index rate is as much a reference as the
 * block-level one, and rewriting only the latter used to leave the other
 * pointing at a name that no longer existed.
 */
function forEachEquation(project, fn) {
	// The block is passed as well as its sub-system: an entry's equation
	// belongs to the block that holds it, and a caller that is moving blocks
	// about has to tell one block's equations from its neighbour's.
	const visit = (holder, key, system, block) => {
		// The names that mean something only inside this equation come with
		// it: a caller rewriting references has to leave them alone.
		const next = fn(holder[key], system, block, functionLocals(block, key));
		if (next !== undefined) holder[key] = next;
	};
	const both = (block, key) => {
		const system = systemOf(block);
		if (typeof block[key] === 'string') visit(block, key, system, block);
		for (const e of block.entries ?? []) {
			if (typeof e[key] === 'string') visit(e, key, system, block);
		}
	};

	for (const t of project.transfers ?? []) {
		both(t, 'rate');
		// A transfer's availability -- a solubility limit, or the two terms
		// of an isotherm -- is part of its rate, and its operands are
		// equations like the rate's own. Missed here, a rename left a limit
		// naming a block that was no longer there.
		const a = t.availability;
		if (a && typeof a === 'object') {
			for (const key of OPERAND_KEYS) {
				if (typeof a[key] === 'string') visit(a, key, systemOf(t), t);
			}
		}
	}
	for (const s of project.inflows ?? []) both(s, 'rate');
	for (const e of project.expressions ?? []) both(e, 'equation');
	// A block that remembers writes equations too -- what it watches, how long
	// it delays it, what it starts at -- and an event field names a discrete
	// event, which is a reference like any other.
	for (const [kind, plural] of Object.entries(RECORDER_COLLECTION)) {
		for (const b of project[plural] ?? []) {
			for (const key of EQUATION_FIELDS[kind]) both(b, key);
			for (const key of EVENT_FIELDS[kind]) both(b, key);
		}
	}
	// A function's body is an equation like any other -- it reads the model
	// in its own sub-system -- with its parameters as extra names that a
	// rename must not touch. `visit` hands those to the caller.
	for (const f of project.functions ?? []) both(f, 'equation');
	for (const c of project.compartments ?? []) {
		both(c, 'initial');
		// The explicit dy/dt term, Ecolego's differentialEquation: an
		// equation read with the state, and rewritten like every other.
		both(c, 'dydt');
		// The legacy per-nuclide map, whose values are equations too.
		if (c.initial && typeof c.initial === 'object' && !Array.isArray(c.initial)) {
			for (const k of Object.keys(c.initial)) {
				const next = fn(String(c.initial[k]), systemOf(c), c);
				if (next !== undefined) c.initial[k] = next;
			}
		}
	}
	// A far-field path's settings are equations -- a travel time from a lookup
	// table, a Kd from a parameter, a resistance scaled by an expression --
	// and they were invisible to every walker in this file. So a rename left
	// them naming a block that no longer existed, `referencesTo` said nothing
	// was using a parameter that was, and a delete that should have been
	// refused went through and broke the model instead.
	for (const f of project.farfields ?? []) {
		for (const key of FARF_EQUATION_KEYS) both(f, key);
	}
	for (const w of project.waste_packages ?? []) {
		for (const key of WASTE_EQUATION_KEYS) both(w, key);
	}
	// A disruptive event: when, and the share each action takes -- an
	// equation on the action itself, visited as the block's.
	for (const d of project.events ?? []) {
		for (const key of DIS_EQUATION_KEYS) both(d, key);
		for (const a of d.actions ?? []) {
			if (typeof a.fraction === 'string') visit(a, 'fraction', systemOf(d), d);
		}
	}
}

/**
 * Rewrites the references in one equation.
 *
 * Works on tokens rather than text, so `C1` inside `C10` or a function name is
 * left alone, and each identifier is *resolved* before it is judged: inside a
 * sub-system, `Kd` and the model's `Kd` are different blocks and only one of
 * them is being renamed.
 */
function rewriteEquation(equation, system, known, replace, skip = null) {
	const src = String(equation ?? '');
	if (!src) return src;
	let tokens;
	try {
		tokens = tokenize(src);
	} catch {
		return src; // unparseable: leave it for the user to fix
	}
	let out = '';
	let cursor = 0;
	for (let i = 0; i < tokens.length; i++) {
		const tok = tokens[i];
		if (tok.type !== 'ident') continue;
		// An identifier followed by '(' is usually a function call rather than
		// a block reference -- except for a lookup table with an argument,
		// which is written exactly that way. A block name may not collide with
		// a function name (RESERVED), so the function table settles it: `min(`
		// is a call, anything else in front of a '(' is the model's own.
		if (tokens[i + 1]?.type === 'lparen' && RESERVED.has(tok.value)) continue;
		// A name that is local to this equation is not a reference to
		// anything: a user-defined function's parameters are the only ones so
		// far, and they may shadow a block, so a rename of that block must
		// not reach in here. See `functionLocals`.
		if (skip?.has(tok.value)) continue;
		const q = resolveReference(tok.value, system, known);
		if (q == null) continue;
		const to = replace(q, system);
		if (to == null || to === tok.value) continue;
		out += src.slice(cursor, tok.pos) + to;
		cursor = tok.pos + tok.text.length;
	}
	return out + src.slice(cursor);
}

/**
 * Follows a compartment or transfer through the list its name is an index of.
 *
 * The two derived dimensions are made of block names, so renaming a block
 * renames an index -- and everything keyed by that index has to come along, or
 * a value set for `C1` would quietly become a value set for nothing. Two
 * places carry one:
 *
 *   an entry's key      `{ index: { Compartments: 'C1' }, value: 3 }`
 *   an equation         `Kd[C1]`, written by hand to reach one compartment
 *
 * The equation case is careful about which brackets it touches. A bracket says
 * which *index* is meant, not which list, so a model with a landscape object
 * called `C1` would have `Kd[C1]` meaning that object -- and rewriting it
 * because a compartment happens to share the name would break an equation that
 * was right. So an index name that any other list also holds is left alone: an
 * ambiguity is not something a rename should resolve on its own.
 *
 * @param listName which derived list the name is an index of
 */
function retargetBlockIndex(project, from, to, listName) {
	retargetBlockIndexes(project, new Map([[listName, new Map([[from, to]])]]));
}

/**
 * The same edit for a whole set of names at once.
 *
 * `renameBlock` moves one name and can afford to do it one at a time.
 * Everything that moves names in bulk -- `moveBlock`, `moveSystem`,
 * `renameSystem`, `deleteSystem` keeping its contents -- cannot: a compartment
 * inside a renamed sub-system wears a *qualified* name as its index, so
 * renaming `NearField` to `Geosphere` renames the index `NearField.Water` to
 * `Geosphere.Water` and everything keyed by it has to come along. Doing that
 * as a sequence of single renames would also chase its own tail when two
 * blocks swap names.
 *
 * @param moves listName -> Map(old index name -> new one)
 */
function retargetBlockIndexes(project, moves) {
	if (![...moves.values()].some((m) => m.size)) return;

	// The ambiguity rule of the single-name case, per list: an index name some
	// *other* list also holds is left alone inside brackets, because a bracket
	// says which index is meant and not which list, and a rename has no
	// business resolving that on its own. The entry keys are unambiguous --
	// they name their list -- so they always follow.
	const written = new Map();
	for (const [listName, m] of moves) {
		for (const [from, to] of m) {
			const ambiguous = indexLists(project).some((l) => l.name !== listName
				&& (l.indices ?? []).some((i) => (typeof i === 'string' ? i : i?.name) === from));
			// Two lists moving the same name in different directions is not
			// something a bracket can express either.
			if (!ambiguous && !written.has(from)) written.set(from, to);
			else written.set(from, null);
		}
	}

	for (const block of allBlocksLive(project)) {
		for (const entry of block.entries ?? []) {
			for (const [listName, m] of moves) {
				const was = entry.index?.[listName];
				if (was != null && m.has(was)) entry.index[listName] = m.get(was);
			}
		}
	}

	if (![...written.values()].some(Boolean)) return;
	const rewrite = (text) => rewriteWrittenIndices(text, (n) => written.get(n) ?? null);
	forEachEquation(project, (text) => rewrite(text));
	forEachTarget(project, (ref) => rewrite(ref));
}

/** `Kd[C1]` -> `Kd[C2]`, leaving everything else exactly as written. */
function renameWrittenIndex(equation, from, to) {
	return rewriteWrittenIndices(equation, (n) => (n === from ? to : null));
}

/**
 * Rewrites the index names written in brackets, and nothing else.
 *
 * `mapping` is asked about each bracketed name and answers with the name it
 * should become, or null to leave it alone. Everything outside the brackets --
 * spacing, the rest of the equation, text this function does not understand --
 * comes through unchanged, which is the point: an equation the modeller typed
 * should come back looking like the one they typed.
 */
function rewriteWrittenIndices(equation, mapping) {
	const src = String(equation ?? '');
	if (!src.includes('[')) return src;
	let tokens;
	try {
		tokens = tokenize(src);
	} catch {
		return src;
	}
	let out = '';
	let cursor = 0;
	for (const tok of tokens) {
		if (tok.type !== 'index') continue;
		const from = tok.value.trim();
		const to = mapping(from);
		if (to == null || to === from) continue;
		out += src.slice(cursor, tok.pos) + tok.text.replace(from, to);
		cursor = tok.pos + tok.text.length;
	}
	return out + src.slice(cursor);
}

/** Drops what was keyed by an index that has gone with its block. */
function dropBlockIndex(project, name, listName) {
	for (const block of allBlocksLive(project)) {
		if (!Array.isArray(block.entries)) continue;
		block.entries = block.entries.filter((e) => e.index?.[listName] !== name);
	}
}


/**
 * An equation split into plain text and the blocks it names.
 *
 * The same walk `rewriteEquation` does -- tokenise, skip function calls, ask
 * `resolveReference` what each identifier means from where it is written --
 * but returning the pieces instead of a new string, so a reader can make each
 * reference clickable. Ecolego's information view does this with
 * `<a href="ref://ecolego/<id>">`; here the caller decides what a reference
 * becomes.
 *
 * A segment with a `name` is a reference to that block, by its qualified name;
 * one without is literal text. Concatenating every `text` gives the equation
 * back exactly, so nothing is lost or reformatted on the way through.
 *
 * @param {object} project
 * @param {string} equation
 * @param {string} [system] the sub-system the equation is written in
 * @returns {Array<{text: string, name?: string}>}
 */
export function equationSegments(project, equation, system = '') {
	const src = String(equation ?? '');
	if (!src) return [];
	let tokens;
	try {
		tokens = tokenize(src);
	} catch {
		// Unparseable: still worth reading, just not worth linking.
		return [{ text: src }];
	}
	const known = knownNames(project);
	const out = [];
	let cursor = 0;
	for (let i = 0; i < tokens.length; i++) {
		const tok = tokens[i];
		if (tok.type !== 'ident') continue;
		// `min(` is a call; `Q_gw(` is a lookup table read at an argument.
		if (tokens[i + 1]?.type === 'lparen' && RESERVED.has(tok.value)) continue;
		const name = resolveReference(tok.value, system, known);
		if (name == null) continue;
		if (tok.pos > cursor) out.push({ text: src.slice(cursor, tok.pos) });
		out.push({ text: tok.text, name });
		cursor = tok.pos + tok.text.length;
	}
	if (cursor < src.length) out.push({ text: src.slice(cursor) });
	return out;
}

/**
 * Points every reference to `oldName` at `newName` instead: connection
 * endpoints, and every equation, each written the way that scope should write
 * it -- local when the target is in the referrer's own sub-system or at the
 * root, qualified otherwise.
 */
/**
 * Refuses an edit that cannot be spelled, before anything is written.
 *
 * A root block is written by its bare name, and from inside a sub-system that
 * has a block of the same name the bare name means the other one -- there is
 * no absolute spelling to fall back on, here or in Ecolego. So renaming root
 * `Water` to `Lake` while `A` holds a `Lake` of its own would turn
 * `A.X = Water * 2` into `A.X = Lake * 2`, which reads `A.Lake`: the same
 * block name, a different block, and the model would go on building and
 * running with a different number in it. `pasteBlocks` detects exactly this
 * and reports it; an edit to the model in place has to stop instead, since
 * there is nothing left to report to afterwards.
 *
 * @param retarget (q, system, block) -> { to, where } for a reference that
 *   the edit changes, or null for one it leaves alone
 */
function refuseShadowed(project, known, retarget) {
	const shadowed = [];
	forEachEquation(project, (text, system, block, locals) => {
		rewriteEquation(text, system, known, (q) => {
			const r = retarget(q, system, block);
			if (!r) return null;
			const spelled = referenceFrom(r.to, r.where, known);
			// A name the edit is about to create resolves to nothing yet, and
			// that is not a clash: only a spelling that already finds *another*
			// block is.
			const found = resolveReference(spelled, r.where, known);
			if (found && found !== r.to) {
				shadowed.push({ block: qualifiedName(block), reference: spelled, means: r.to, where: r.where });
			}
			return null;
		}, locals);
		return undefined;
	});
	if (!shadowed.length) return;
	const s = shadowed[0];
	const more = shadowed.length > 1 ? ` (and ${shadowed.length - 1} more)` : '';
	throw new EditError(
		`'${s.block}' reads '${s.means}', which from inside '${s.where || 'the top level'}' `
		+ `would have to be written '${s.reference}' -- and there that name means a `
		+ `different block. Rename or move one of the two first.${more}`,
		shadowed.map((x) => x.block),
	);
}

function retargetReferences(project, oldName, newName) {
	// The old name still has to resolve while the rewrite runs, so the set of
	// known names is taken to include it.
	const set = new Set([...blockNames(project), oldName, newName]);
	const known = (n) => set.has(n);
	refuseShadowed(project, known, (q, system) => (q === oldName ? { to: newName, where: system } : null));
	for (const t of project.transfers ?? []) {
		if (t.from === oldName) t.from = newName;
		if (t.to === oldName) t.to = newName;
	}
	for (const s of project.inflows ?? []) {
		if (s.to === oldName) s.to = newName;
	}
	for (const d of project.events ?? []) {
		for (const a of d.actions ?? []) {
			for (const end of ['block', 'from', 'to']) if (a[end] === oldName) a[end] = newName;
		}
	}
	forEachEquation(project, (text, system, block, locals) => rewriteEquation(
		text, system, known,
		(q, from) => (q === oldName ? referenceFrom(newName, from, known) : null),
		locals,
	));
	// A reduction names the blocks it reduces instead of writing an equation,
	// so those names are references too and have to follow the rename.
	forEachTarget(project, (ref, system) => (
		resolveReference(ref, system, known) === oldName
			? referenceFrom(newName, system, known)
			: ref
	));
}

/**
 * Visits every block name an `index_operation` or `aggregate` reduces, block
 * level and per entry, replacing it with whatever `fn` returns.
 *
 * The block is handed over as well as its sub-system, for the same reason
 * `forEachEquation` does it: a caller copying blocks about has to tell one
 * block's targets from its neighbour's.
 */
function forEachTarget(project, fn) {
	for (const o of project.index_reductions ?? []) {
		const system = systemOf(o);
		if (typeof o.target === 'string' && o.target) o.target = fn(o.target, system, o);
		for (const e of o.entries ?? []) {
			if (typeof e.target === 'string' && e.target) e.target = fn(e.target, system, o);
		}
	}
	for (const g of project.block_reductions ?? []) {
		const system = systemOf(g);
		const list = (arr) => (Array.isArray(arr) ? arr.map((t) => fn(t, system, g)) : arr);
		if (Array.isArray(g.targets)) g.targets = list(g.targets);
		for (const e of g.entries ?? []) {
			if (Array.isArray(e.targets)) e.targets = list(e.targets);
		}
	}
}

/** Moves a block's diagram position, and any bend or pipe on its connection, with it. */
function retargetLayout(project, oldName, newName) {
	if (!project.layout || oldName === newName) return;
	const layout = layoutOf(project);
	// Its bend, and its pipe on every canvas: see `waypointKey`.
	const keys = [oldName, ...Object.keys(layout).filter((k) => parseEdgeKey(k)?.name === oldName)];
	for (const key of keys) {
		// `hasOwnProperty`, not `in`: on a map that has not been through
		// `layoutOf` yet, `'__proto__' in layout` is true of every object, and
		// the two lines below then copied `Object.prototype` under the new
		// name and wrote into it from there.
		if (!Object.prototype.hasOwnProperty.call(layout, key)) continue;
		const edge = parseEdgeKey(key);
		const to = edge ? waypointKey(newName, edge.view) : newName;
		layout[to] = layout[key];
		delete layout[key];
	}
}

/**
 * Renames a block and follows the change through every reference: transfer
 * endpoints, source targets, and any equation or initial condition that
 * mentions it.
 *
 * `newName` is a local name: a rename does not move a block between
 * sub-systems. That is `moveBlock`.
 */
export function renameBlock(project, oldName, newName) {
	const found = findBlock(project, oldName);
	if (!found) throw new EditError(`No block named '${oldName}'`);
	const system = systemOf(found.block);
	const local = baseName(newName) === newName ? newName : null;
	if (local == null) {
		throw new EditError(
			`'${newName}' is a path, not a name. Use "move" to put a block in another `
			+ `sub-system.`,
		);
	}
	const target = qualify(system, local);
	if (target === oldName) return;

	const problem = validateName(project, local, { allow: oldName, system });
	if (problem) throw new EditError(problem);

	// References first: that is where a rename that cannot be spelled is
	// refused, and it has to be refused before the block has changed.
	retargetReferences(project, oldName, target);
	found.block.name = local;
	retargetLayout(project, oldName, target);
	// A compartment's or a transfer's name is also an index of the dimension
	// made of them, so everything keyed by it follows the rename.
	if (found.kind === 'compartment') {
		retargetBlockIndex(project, oldName, target, COMPARTMENT_LIST);
	} else if (found.kind === 'transfer') {
		retargetBlockIndex(project, oldName, target, TRANSFER_LIST);
	}
}

/**
 * Substitutes one identifier for another inside a single equation, ignoring
 * sub-systems: the caller has already decided that this text refers to that
 * block. Kept as the simple case of `rewriteEquation`.
 */
export function renameInEquation(equation, oldName, newName) {
	return rewriteEquation(
		equation, '', (n) => n === oldName, (q) => (q === oldName ? newName : null),
	);
}

/**
 * Every "A is read by B" pair in the model, as qualified names.
 *
 * This is what the diagram's influence layer draws, and what the block list
 * would need to answer "where does this total come from". Kept here rather
 * than in the diagram because it is a fact about the model, not about the
 * view -- and because a block can be read in three different ways, which is
 * exactly the sort of thing that gets one of them forgotten:
 *
 *   an equation mentions it     an expression, a transfer or source rate
 *   a reduction names it        an index operation's target, an aggregate's
 *   a connection attaches to it a transfer's endpoints -- deliberately *not*
 *                               included, since the transfer's own arrow
 *                               already says so
 *
 * The second kind is why this exists: a reduction has no equation, so
 * scanning equations alone drew no arrow into an index operation or an
 * aggregate at all.
 *
 * @returns {Array<{from: string, to: string}>} `from` is read by `to`
 */
/**
 * The kinds whose value cannot be the same at every time of a run.
 *
 * The engine's own list, from `timeInvariantAlgebraic` in ../sim/builder.js,
 * which decides the same thing for a different reason -- what an initial
 * condition may read. It is written out twice because the two run over
 * different material: the builder over a laid-out system it has already
 * compiled, this over the raw model, before anything has been built and while
 * it may still be too broken to build at all. A test runs both over every
 * bundled example and requires the same answer.
 *
 * A compartment is the state being integrated. A far-field path's release
 * comes out of that state. A lookup table without an argument is read at the
 * clock, and one with an argument has no value of its own to ask about. The
 * blocks that remember are functions of history by definition, and an event's
 * value is the gap between its two expressions.
 */
const VARYING_KINDS = new Set([
	'compartment', 'farfield', 'waste_package', 'event', 'lookup',
	'min_max', 'running_mean', 'snapshot', 'delay', 'trigger',
]);

/** The clock, as an equation spells it: a bare `time`. */
function readsClock(text) {
	try {
		return tokenize(String(text ?? '')).some((t) => t.type === 'ident' && t.value === 'time');
	} catch { return false; }
}

/**
 * Whether a block is the same number for the whole run, and what decides it.
 *
 * The question a reader of somebody else's model asks about every box in it:
 * is this a constant, or does it move? It is not answerable by looking --
 * `Kd * rho / porosity` is three parameters and never changes, and
 * `Kd * Water` is the same shape and changes at every step -- so the model is
 * asked instead.
 *
 * The walk is the dependency graph `influences` already builds, plus the
 * clock, which is not a block and so is not in it. A block varies when it is
 * one of the kinds that always does, when any equation of it reads `time`, or
 * when anything it reads varies; and the answer names the *nearest* reason,
 * since that is the one the reader can do something about.
 *
 * Conservative where it cannot tell: a reference into a cycle, which a model
 * should not contain and the loader refuses, is read as varying rather than
 * as constant. Calling something constant that is not is the answer that does
 * real harm -- it is what an initial condition is allowed to read.
 *
 * @returns {{constant: boolean, why: string, because: string|null}} `because`
 *   is the block the answer turns on, when it is a block
 */
export function constancy(project, name, graph = null) {
	const found = findBlock(project, name);
	if (!found) return { constant: false, why: 'no such block', because: null };

	// Who reads whom, once for the whole walk: the caller may be asking about
	// every block in the model in turn, and this is the expensive half.
	const reads = graph ?? readsGraph(project);
	// `allBlocks` tags each one with the collection it came from, which is the
	// kind: the raw model has no field for it.
	const kindOf = new Map(allBlocks(project).map((b) => [qualifiedName(b), b.kind]));

	const clockOf = new Map();
	forEachEquation(project, (text, system, block) => {
		if (readsClock(text)) clockOf.set(qualifiedName(block), true);
		return undefined;
	});

	const seen = new Map();
	const walk = (at, trail) => {
		if (seen.has(at)) return seen.get(at);
		// A cycle: unresolvable here, and refused by the loader. Varying is
		// the safe half of the answer.
		if (trail.has(at)) return { constant: false, why: 'it is part of a cycle', because: null };
		trail.add(at);
		const kind = kindOf.get(at);
		let answer;
		if (kind && VARYING_KINDS.has(kind)) {
			answer = { constant: false, why: VARYING_WHY[kind], because: null };
		} else if (clockOf.get(at)) {
			answer = { constant: false, why: 'it reads the clock', because: null };
		} else {
			answer = { constant: true, why: 'everything it reads is constant too', because: null };
			for (const dep of reads.get(at) ?? []) {
				const sub = walk(dep, trail);
				if (sub.constant) continue;
				// One step, not the whole chain. `A reads B, which reads C,
				// which the solver integrates` is a sentence nobody finishes,
				// and the reader can follow the link to B and be told the same
				// thing about it. What is worth saying here is which of the
				// things it reads is the one that moves.
				const how = VARYING_KINDS.has(kindOf.get(dep))
					? DEPENDENCY_WHY[kindOf.get(dep)]
					: clockOf.get(dep) ? 'which reads the clock' : 'which varies';
				// `{}` stands for the block named in `because`, so that a
				// reader that can draw a link -- the Information view -- can
				// put one there without hunting for the name in the sentence.
				// `constancyText` fills it in for everyone else.
				answer = { constant: false, why: `it reads {}, ${how}`, because: dep };
				break;
			}
		}
		trail.delete(at);
		seen.set(at, answer);
		return answer;
	};

	const qname = qualifiedName(found.block);
	const answer = walk(qname, new Set());
	// A parameter is a number and reads nothing, so the generic "everything it
	// reads" is true of it and says nothing. Ecolego calls it a constant.
	if (answer.constant && found.kind === 'parameter') {
		return { constant: true, why: 'it is a parameter — a number', because: null };
	}
	return answer;
}

/**
 * `constancy`'s reason as plain text: `{}` filled in with the block it names.
 *
 * @param {{why: string, because: string|null}} answer
 */
export function constancyText(answer) {
	if (!answer?.because) return answer?.why ?? '';
	return answer.why.replace('{}', baseName(answer.because));
}

/** Why each of the always-varying kinds does, said of the block itself. */
const VARYING_WHY = {
	compartment: 'the solver integrates it',
	farfield: 'its release comes out of the state the solver integrates',
	waste_package: 'its release comes out of the inventories the solver integrates',
	event: 'it counts occurrences as the run goes',
	lookup: 'a table is read at the clock',
	min_max: 'it watches the run as it goes',
	running_mean: 'it watches the run as it goes',
	snapshot: 'it watches the run as it goes',
	delay: 'it watches the run as it goes',
	trigger: 'its value is the gap between its two expressions',
};

/** The same, said of a block this one reads. */
const DEPENDENCY_WHY = {
	compartment: 'which the solver integrates',
	farfield: 'whose release comes out of the state',
	waste_package: 'whose release comes out of the state',
	event: 'which counts occurrences as the run goes',
	lookup: 'which is a table read at the clock',
	min_max: 'which watches the run as it goes',
	running_mean: 'which watches the run as it goes',
	snapshot: 'which watches the run as it goes',
	delay: 'which watches the run as it goes',
	trigger: 'whose value is the gap between two expressions',
};

/** `influences` as a lookup from a block to everything it reads. */
function readsGraph(project) {
	const reads = new Map();
	for (const { from, to } of influences(project)) {
		if (!reads.has(to)) reads.set(to, new Set());
		reads.get(to).add(from);
	}
	return reads;
}

export function influences(project) {
	const known = new Set(blockNames(project));
	const has = (n) => known.has(n);
	const out = [];
	const seen = new Set();

	const add = (block, refs) => {
		const to = qualifiedName(block);
		const system = systemOf(block);
		for (const r of refs) {
			if (!r) continue;
			const from = resolveReference(String(r), system, has);
			if (!from || from === to) continue;
			const key = `${from}\u0000${to}`;
			if (seen.has(key)) continue;
			seen.add(key);
			out.push({ from, to });
		}
	};

	// What an equation reads. Block level and per entry: a rate that only
	// differs for one nuclide still depends on whatever it mentions.
	const namesIn = (text, locals = null) => {
		try {
			return tokenize(String(text ?? ''))
				.filter((t, i, all) => t.type === 'ident'
					&& !(all[i + 1]?.type === 'lparen' && RESERVED.has(t.value))
					// A function's parameters are names of the body's own.
					&& !locals?.has(t.value))
				.map((t) => t.value);
		} catch { return []; }
	};
	const fromEquations = (list, key) => {
		for (const b of list ?? []) {
			const locals = functionLocals(b, key);
			const texts = [b[key], ...(b.entries ?? []).map((e) => e[key])];
			add(b, texts.flatMap((t) => namesIn(t, locals)));
		}
	};
	fromEquations(project.expressions, 'equation');
	fromEquations(project.transfers, 'rate');
	fromEquations(project.inflows, 'rate');
	// A compartment's explicit dy/dt term is read with the state, exactly as
	// a source's rate is, so what it names influences the compartment.
	fromEquations(project.compartments, 'dydt');
	// ...and so is its initial condition, which used to be left out on the
	// grounds that it is read once, before the run. That is true of *when* it
	// is read and says nothing about *whether* it is a dependency: an
	// inventory written as `Conc * Volume` comes from those two blocks, and a
	// compartment whose start is a function call is exactly the case this was
	// asked about. Leaving it out also made two panels disagree -- a function
	// said it was used by the compartment, and the compartment said it used
	// nothing -- since "Used by" reads `referencesTo`, which never skipped it.
	fromEquations(project.compartments, 'initial');
	// Calling a function is reading it: that is what puts the callers under
	// "Used by" on a function's own page, and what the delete gate reads.
	fromEquations(project.functions, 'equation');
	// A far-field path reads the model through its settings -- a travel time
	// from a lookup table, a Kd per nuclide, a resistance scaled by an
	// expression -- and every one of them is an equation like any other.
	for (const key of FARF_EQUATION_KEYS) fromEquations(project.farfields, key);
	// What a block that remembers watches, and which event drives it: both are
	// dependencies, and both are drawn as influences.
	for (const [kind, plural] of Object.entries(RECORDER_COLLECTION)) {
		for (const key of EQUATION_FIELDS[kind]) fromEquations(project[plural], key);
		for (const key of EVENT_FIELDS[kind]) {
			for (const b of project[plural] ?? []) {
				add(b, [b[key], ...(b.entries ?? []).map((e) => e[key])]
					.filter((v) => typeof v === 'string' && v.trim())
					.map((v) => v.trim()));
			}
		}
	}

	// What a reduction names.
	for (const o of project.index_reductions ?? []) {
		add(o, [o.target, ...(o.entries ?? []).map((e) => e.target)]);
	}
	for (const g of project.block_reductions ?? []) {
		add(g, [...(g.targets ?? []), ...(g.entries ?? []).flatMap((e) => e.targets ?? [])]);
	}

	// The blocks that read the model through settings of their own rather
	// than through one equation. Left out, they had no arrows at all: a
	// parameter setting when the canisters fail was drawn as reading nothing
	// and being read by nobody, which is the one thing on the diagram that
	// was plainly not true. Every one is what the Used-by lists and the
	// delete gate already count (see `referencesTo`), so the three agree.
	//
	// Waste packages: the inventory, the instant-release fraction, the
	// degradation rate and the failure settings, all equations.
	for (const key of WASTE_EQUATION_KEYS) fromEquations(project.waste_packages, key);
	// An event: its time or its rate and window, each action's share -- and,
	// by name, the blocks its actions act on: the packages it fails, the
	// compartments a share moves between. Named in the event, so drawn into
	// it, as everything a block's definition names is.
	for (const key of DIS_EQUATION_KEYS) fromEquations(project.events, key);
	for (const d of project.events ?? []) {
		for (const a of d.actions ?? []) {
			const named = ['block', 'from', 'to']
				.map((k) => a[k]).filter((v) => typeof v === 'string' && v.trim()).map((v) => v.trim());
			add(d, [...namesIn(a.fraction), ...named]);
		}
	}
	// A transfer's availability -- a solubility limit, or the two terms of an
	// isotherm -- is part of its rate.
	for (const t of project.transfers ?? []) {
		const scheme = schemeOf(t);
		if (scheme) add(t, operandKeys(scheme).flatMap((k) => namesIn(scheme[k])));
	}

	return out;
}

/**
 * Which field of each kind of block carries an equation whose unit is checked,
 * and what it is checked against.
 *
 *   own       the unit the block itself declares
 *   derived   the unit the model says it must have -- a flux
 *   time      the simulation's time unit
 *   rate      the unit the block declares, per unit of time: a change in it
 *   match     no declared unit; the fields are checked against each other
 *
 * The two odd ones are Ecolego's: `validateUnit` checks a compartment's
 * *derivative* against `<compartment>/<time>` rather than the compartment's
 * own unit -- which in this tool is the transfer, whose unit is derived
 * already -- and a delay time against the time unit.
 */
const UNIT_TARGET = {
	compartment: { initial: 'own', dydt: 'rate' },
	expression: { equation: 'own' },
	transfer: { rate: 'derived' },
	inflow: { rate: 'derived' },
	min_max: { target: 'own' },
	running_mean: { target: 'own' },
	snapshot: { target: 'own', initial: 'own' },
	delay: { target: 'own', delay: 'time' },
	trigger: { first: 'match', second: 'match' },
};

/**
 * Unit mismatches in a block's equations.
 *
 * Warnings, never errors: the engine treats units as labels, so a model with a
 * mismatch still runs and still gives the numbers it always gave. What it may
 * not be is what its author meant.
 *
 * Silent whenever it cannot know -- a block with no unit, an equation naming
 * one, a function whose unit rule is not written down. Half of a real model
 * carries no units at all, and a checker that guessed at those would be noise
 * rather than a warning.
 *
 * @returns {Array<{name: string, field: string, index: object|null,
 *   expected: string, found: string, message: string}>}
 */
/**
 * The unit of a block named in an equation, resolved from where it is written.
 *
 * Shared by the checker and by the recommendation below, which have to agree:
 * a unit suggested from an equation and then typed in must leave the checker
 * with nothing to say.
 */
function unitResolver(project, block, known = knownNames(project), index = null) {
	const system = systemOf(block);
	return (written) => {
		const target = resolveReference(String(written), system, known);
		if (!target) return null;
		// This is the lookup the whole model-wide scan is made of -- one per
		// identifier in one equation, and there are six figures of those.
		// `index` is what turns it from a walk of every collection into a
		// hash; see `blockIndex`.
		const found = findBlock(project, target, index);
		if (!found) return null;
		const text = DERIVED_UNIT_KINDS.includes(found.kind)
			? derivedUnit(project, found.block, found.kind)
			: found.block.unit;
		return text ? parseUnit(text) : null;
	};
}

/**
 * The unit an equation says a block is in, for a block that does not say.
 *
 * Not applied, offered: a unit is the modeller's claim about what a number
 * means, and a tool that filled it in silently would be putting words in
 * their mouth -- the more so because half of a real model carries no units at
 * all and the equation only settles the ones it can reach. Where it *can*
 * reach, the answer is worth having: an expression `TCOut*C3` over a transfer
 * in 1/year and a compartment in Bq is in Bq/year, and nothing but the
 * equation knows that.
 *
 * Silent unless it can be sure: a block with a unit already, an equation that
 * is a bare number, one that names something with no unit of its own, a
 * function with no unit rule, or a result that comes out dimensionless -- for
 * which the honest label is nothing at all.
 *
 * A compartment on the radionuclide dimension is settled by the model instead
 * (see syncInventoryUnits), so this never has to answer for one.
 *
 * @returns {{unit: string, field: string, from: string}|null}
 */
export function suggestedUnit(project, block, kind) {
	if (!block || String(block.unit ?? '').trim()) return null;
	if (writtenByTheRun(block)) return null;
	const fields = UNIT_TARGET[kind];
	if (!fields) return null;
	const unitOf = unitResolver(project, block);
	const time = parseUnit(timeUnit(project));
	for (const [field, how] of Object.entries(fields)) {
		// Only the fields whose unit *is* this block's unit. A delay's time is
		// in the time unit whatever the block holds, and a derived one is not
		// the block's to claim.
		if (how !== 'own') continue;
		const text = block[field];
		if (typeof text !== 'string' || !text.trim()) continue;
		let ast;
		try {
			ast = parse(text);
		} catch {
			continue;
		}
		if (!namesSomething(ast)) continue;
		const { dim, clash } = equationUnit(ast, unitOf, time);
		if (clash || !dim || dim.isOne) continue;
		return { unit: String(dim), field, from: text.trim() };
	}
	return null;
}

export function unitProblems(project, block, kind,
	{ known = null, material: materialName = undefined, index = null } = {}) {
	const fields = UNIT_TARGET[kind];
	if (!fields) return [];
	if (writtenByTheRun(block)) return [];
	const qname = qualifiedName(block);
	const time = parseUnit(timeUnit(project));
	// `known` is the set of every block's name, which the model-wide scan
	// builds once and hands in: built here per block, it was the whole model
	// walked once per block, and a second of every keystroke on a large one.
	const unitOf = unitResolver(project, block, known ?? knownNames(project), index);

	const wanted = (how) => {
		if (how === 'time') return time;
		// A change in the block's own quantity per unit of time: what an
		// explicit dy/dt term is in. `EquationValidator` says the same of
		// the differential-equation property -- "it has the unit of a
		// transfer" -- and builds `targetUnit + "/" + timeUnit`.
		if (how === 'rate') {
			const own = block.unit ? parseUnit(block.unit) : null;
			return own && time ? own.over(time) : null;
		}
		if (how === 'derived') {
			const text = derivedUnit(project, block, kind);
			return text ? parseUnit(text) : null;
		}
		return block.unit ? parseUnit(block.unit) : null;
	};

	const out = [];

	// A compartment on the radionuclide dimension holds the model's inventory
	// unit. There are two of them and the choice is the model's, so one that
	// says the *other* one is not a difference of opinion: it is a state the
	// model cannot be in -- Ecolego keeps a single unit in the contaminant catalogue and
	// holds every nuclide's own unit equal to it -- and the numbers in the
	// model are read as being in whichever unit is chosen, so the label being
	// wrong means the decay term is being applied to something else.
	//
	// Not overwritten, said. The unit was typed in on purpose; which of the
	// two is meant is the question, and the answer is the modeller's.
	if (kind === 'compartment') {
		// Handed in by the model-wide scan for the same reason `known` is:
		// working it out here walks every index list -- and the derived ones
		// are built from every compartment and every transfer in the model --
		// so per block it is the model squared, and on a 600-compartment model
		// it was 180 ms of every edit, twice over.
		const material = materialName === undefined
			? materialDimensionName(project) : materialName;
		const written = String(block.unit ?? '').trim();
		const want = inventoryUnit(project);
		const other = want === 'Bq' ? 'mol' : 'Bq';
		if (material && written && sameUnit(written, other)
			&& effectiveDims(project, block).includes(material)) {
			out.push({
				name: qname,
				field: 'unit',
				index: null,
				expected: want,
				found: written,
				detail: `holds ${written}, but this model\u2019s inventories are in ${want}`,
				message: `${qname}: holds ${written}, but this model\u2019s `
					+ `inventories are in ${want}`,
			});
		}
	}

	const look = (holder, index) => {
		const matched = [];
		for (const [field, how] of Object.entries(fields)) {
			const text = holder[field];
			if (typeof text !== 'string' || !text.trim()) continue;
			let ast;
			try {
				ast = parse(text);
			} catch {
				continue; // a broken equation is reported as a broken equation
			}
			if (!namesSomething(ast)) continue;
			// A literal written against something whose unit is known is
			// converted to that unit before anything is judged -- so the
			// checker is silent about exactly the equations the run converts,
			// and speaks about exactly the ones it does not. See
			// `scaleLiterals`.
			for (const u of scaleLiterals(ast, unitOf, time).unconverted) {
				out.push({
					name: qname, field, index, expected: '', found: '',
					detail: `${scaleText(u.value)}[${u.unit}] is not converted: nothing it is `
						+ 'written against says what unit it is in',
					message: `${qname}: ${field} — ${scaleText(u.value)}[${u.unit}] is not `
						+ 'converted: nothing it is written against says what unit it is in',
				});
			}
			const { dim, clash } = equationUnit(ast, unitOf, time);
			if (clash) {
				out.push({
					name: qname, field, index, expected: '', found: '',
					detail: `${clash}`,
					message: `${qname}: ${field} — ${clash}`,
				});
				continue;
			}
			if (!dim) continue;
			if (how === 'match') { matched.push([field, dim]); continue; }
			const want = wanted(how);
			if (!want || want.equals(dim)) continue;
			// What the block is measured against depends on where the unit
			// came from, and saying which is the difference between a useful
			// warning and an argument with the tool.
			const says = how === 'derived'
				? `a flux out of ${block.from ?? block.to ?? 'here'} must be ${want}`
				: how === 'time'
					? `a time is in ${want}`
					: how === 'rate'
						? `a change in ${block.unit} over time is in ${want}`
						: `this block says ${want}`;
			// The same quantity a prefix apart -- kBq where Bq was wanted --
			// is the commonest mismatch there is and the easiest to fix, and
			// the message should hand over the factor rather than leave the
			// reader to work out that the two are related at all. Nothing
			// converts: the factor is the modeller's to write in.
			const scaled = want.sameKind(dim) ? scaleNote(dim, want) : '';
			out.push({
				name: qname,
				field,
				index,
				expected: String(want),
				found: String(dim),
				detail: `works out as ${dim}, but ${says}${scaled}`,
				message: `${qname}: ${field} works out as ${dim}, but ${says}${scaled}`,
			});
		}
		if (matched.length === 2 && !matched[0][1].equals(matched[1][1])
			&& !matched[0][1].isOne && !matched[1][1].isOne) {
			out.push({
				name: qname, field: matched[0][0], index,
				expected: String(matched[0][1]), found: String(matched[1][1]),
				detail: `compares ${matched[0][1]} with ${matched[1][1]}`,
				message: `${qname}: compares ${matched[0][1]} with ${matched[1][1]}`,
			});
		}
	};

	look(block, null);
	for (const e of block.entries ?? []) look(e, e.index ?? null);
	return out;
}

/**
 * " — the same quantity, 1000 times larger; nothing here converts, so the
 * factor is yours to write in". For a `found` that is `want` a scale apart.
 */
function scaleNote(found, want) {
	const f = found.factor(want);
	const times = f >= 1 ? scaleText(f) : scaleText(1 / f);
	const way = f >= 1 ? 'larger' : 'smaller';
	return ` — the same quantity, ${times} times ${way}; nothing here converts, `
		+ 'so the factor is yours to write in';
}

/** Every unit mismatch in the model, in the order the blocks are held. */
export function allUnitProblems(project) {
	const out = [];
	const known = knownNames(project);
	// Once, not once per block: see the note in `unitProblems`. The index is
	// here for the same reason and matters more -- `known` saved a walk per
	// *block*, this saves one per *reference*, and there are two orders of
	// magnitude more of those.
	const index = blockIndex(project);
	const material = materialDimensionName(project);
	for (const collection of KINDS) {
		const kind = SINGULAR[collection];
		for (const b of project?.[collection] ?? []) {
			// Named, since a list over the whole model is read by block.
			for (const p of unitProblems(project, b, kind, { known, material, index })) out.push({ ...p, name: qualifiedName(b) });
		}
	}
	return out;
}

/**
 * What the model should be told about but runs regardless: a unit that does
 * not agree with what its equation works out to, and a far-field path whose
 * release is delivered somewhere it will be counted twice or held against.
 * The shape `allEquationProblems` has, so the two lists can be marked alike.
 *
 * Not everything here belongs to a block. A saved time outside the run is a
 * number the modeller wrote down and the run will never reach, and it has no
 * name to be marked beside -- so those carry `name: null` and `goto`, which
 * says which editor answers them. The strip lists them; nothing marks them,
 * because there is nothing to put a mark on.
 *
 * @returns {Array<{name: string|null, field: string|null, message: string,
 *   goto?: string}>}
 */
export function modelWarnings(project, { unitProblems = null } = {}) {
	// The scan is handed in where the caller has already done it. The editor
	// does: it lists the unit problems for the strip and then asks for the
	// warnings, and the two used to walk every block in the model twice for
	// the same answer -- once here and once in the rail's info card.
	const out = (unitProblems ?? allUnitProblems(project)).map((p) => ({
		name: p.name, field: p.field ?? 'unit', message: `Units: ${p.detail}`,
	}));
	for (const f of project?.farfields ?? []) {
		for (const w of [farfieldWarning(project, f), dispersionWarning(f)]) {
			if (w) out.push({ name: qualifiedName(f), field: null, message: `${w[0].toUpperCase()}${w.slice(1)}` });
		}
	}
	// Waste packages that cannot fail the way they say: the run refuses them,
	// and the strip says why before it is tried.
	for (const p of wasteProblems(project)) out.push({ name: p.name, field: p.field, message: p.message });
	for (const p of disruptionProblems(project)) out.push({ name: p.name, field: p.field, message: p.message });
	out.push(...emptyDimensionWarnings(project));
	out.push(...savedTimeWarnings(project));
	out.push(...leakingTransferWarnings(project));
	// A switch time that cannot be resolved, or one outside the run: the model
	// runs, one corner less accurately than it could. See ./switchtimes.js.
	for (const p of switchTimeProblems(project)) {
		out.push({ name: p.name, field: p.field, message: p.message });
	}
	// A derived parameter pointing at a series no run produces.
	for (const p of derivedProblems(project)) {
		out.push({ name: p.name, field: p.field, message: p.message });
	}
	return out;
}

/**
 * Transfers that keep running into a compartment that has been switched off.
 *
 * The rule is Ecolego's and is right: only a transfer's *donor* decides whether
 * it runs, so one whose target is disabled goes on draining its donor and what
 * it moves leaves the model, exactly as a flux to `outside` does. The
 * Information view says so on the block.
 *
 * It is said here as well because of what it costs and how quietly: the
 * donor's curve does not change, nothing fails to build, and the inventory that
 * used to arrive somewhere now arrives nowhere -- a mass balance that no longer
 * balances, discovered by adding the compartments up and wondering. Switching a
 * compartment off is one click and this is two blocks away from it.
 *
 * Only this direction. A transfer whose donor is off goes off with it, which is
 * what anybody switching off a donor expects, and nothing is lost by it.
 */
function leakingTransferWarnings(project) {
	const out = [];
	for (const [key, why] of implicitlyDisabled(project)) {
		if (!key.endsWith('#to')) continue;
		const name = key.slice(0, -'#to'.length);
		// The compartment it is aimed at, out of the sentence `implicitlyDisabled`
		// wrote about it. Read back rather than resolved again here: which
		// block an end names is the one thing that needs the scope walk, and
		// two answers to it that could disagree would be worse than this.
		const target = /'([^']+)'/.exec(why)?.[1] ?? 'a disabled compartment';
		out.push({
			name,
			field: 'to',
			// Said as the consequence, not the cause. The cause is on screen
			// already -- the compartment is drawn greyed -- and what is not is
			// that the model is still moving inventory into it and losing it.
			message: `Flows into ${target}, which is disabled. It still runs, so what `
				+ 'it moves leaves the model rather than arriving anywhere.',
		});
	}
	return out;
}

/**
 * Blocks that hold no values, because a dimension they carry is empty.
 *
 * A list with nothing enabled in it has width zero, so a block indexed by it
 * has no slots: it contributes nothing to the run, reports nothing on the
 * chart and is in the model as a name and a shape. This used to be refused
 * outright -- the generator crashed on it -- and refusing it was wrong: a real
 * calculation case leaves a list empty on purpose, and model B
 * has four such blocks for waste types its variant does not have.
 *
 * Worth saying all the same, on the block rather than on the list: a block
 * that quietly holds nothing looks exactly like one that is working, and the
 * one place anybody would look for it is the block itself.
 */
export function emptyDimensionWarnings(project) {
	const lists = indexLists(project);
	const empty = new Set(lists
		.filter((l) => !(l.indices ?? []).some((i) => i.enabled !== false))
		.map((l) => l.name));
	if (!empty.size) return [];
	const out = [];
	for (const collection of KINDS) {
		for (const block of project?.[collection] ?? []) {
			const bad = (block?.index_lists ?? []).filter((d) => empty.has(d));
			if (!bad.length) continue;
			out.push({
				name: qualifiedName(block),
				field: 'index lists',
				message: `Holds no values: ${bad.length === 1 ? `'${bad[0]}' has` : `${bad.join(', ')} have`} `
					+ 'no enabled indices, so this block has no slots at all. It is not in '
					+ 'the run and nothing can read it. Enable an index, or take the list off it.',
			});
		}
	}
	return out;
}

/**
 * What is wrong with the output grid without being wrong enough to refuse.
 *
 * Every one of these is a number written into the saved-times editor that the
 * run cannot use, and every one of them was silent until now: `seriesTimes`
 * drops what falls outside the run and returns what is left, so a series that
 * saves three of its twelve times and a series that saves all twelve are the
 * same object with the same count beside it. The editor says "nothing in the
 * run" for the one case where *everything* is lost, and the sidebar repeats
 * it, and neither is looked at unless something has already gone wrong.
 *
 * The run's own start and end are always saved, so none of this can leave a
 * model with no output at all -- which is why they are warnings.
 *
 * @returns {Array<{name: null, field: string, message: string, goto: string}>}
 */
export function savedTimeWarnings(project) {
	const sim = project?.simulation ?? {};
	const spacing = sim.spacing ?? 'log';
	// The shorthand spacings have no series to be wrong about, and `solver`
	// has no grid at all: the steps the solver accepts are the output.
	if (spacing !== 'series' && spacing !== 'both') return [];
	const t0 = Number(sim.start_time ?? 0);
	const t1 = Number(sim.end_time ?? 0);
	if (!Number.isFinite(t0) || !Number.isFinite(t1) || !(t1 > t0)) return [];
	const run = `the run (${fmtTime(t0)} to ${fmtTime(t1)})`;
	const out = [];
	const say = (message) => out.push({
		name: null, field: 'saved times', message, goto: 'saved-times',
	});
	const list = Array.isArray(sim.output_times) ? sim.output_times : [];

	list.forEach((spec, i) => {
		// Named by what it is rather than by what it holds: a `times` series
		// is about to have its own numbers quoted back, and describing it as
		// "12 times: 1, 2, 3, …" first makes one sentence out of two lists.
		const which = seriesKind(spec) === 'times'
			? `Series ${i + 1} (${(spec.times ?? []).length} times)`
			: `Series ${i + 1} (${describeSeries(spec, t0, t1)})`;
		// Nothing at all: the one case that was already said, now said where
		// the rest of the model's warnings are said.
		if (!seriesTimes(spec, t0, t1).length) {
			say(`${which} is entirely outside ${run}, so it saves nothing. `
				+ 'Change its ends, or the run’s, or remove it.');
			return;
		}
		// Some of it: the times that were written down and will not be saved.
		const dropped = droppedTimes(spec, t0, t1);
		if (dropped.length) {
			const shown = dropped.slice(0, 6).map(fmtTime).join(', ');
			say(`${which} has ${dropped.length} time${dropped.length === 1 ? '' : 's'} `
				+ `outside ${run}, so ${dropped.length === 1 ? 'it is' : 'they are'} `
				+ `not saved: ${shown}${dropped.length > 6 ? ', …' : ''}`);
		}
		// An end outside the run does not extend the run; it moves the points.
		for (const { end, value } of clippedEnds(spec, t0, t1)) {
			say(`${which} runs ${end} ${fmtTime(value)}, which is outside ${run}. `
				+ `The spacing is worked out over the series' own ends, so what is `
				+ 'saved is the part of it that lands inside the run rather than '
				+ 'the number of points asked for.');
		}
	});
	return out;
}

/**
 * The marks a diagram, a tree or a panel puts beside a name: what is wrong
 * with each block, and -- carried up -- with each sub-system that holds one.
 *
 * A problem in `foo.bar.Expr` is found by browsing to it, and browsing starts
 * at the top, where only `foo` is drawn. So every sub-system on the way down
 * carries the mark of the worst thing inside it, with a count: `foo` says
 * there is a problem in it, `foo.bar` says the same, and `foo.bar.Expr` says
 * what it is. An error outranks a warning, so a sub-system with one of each
 * is marked as broken, and its count says two.
 *
 * @param entries `{ where, level: 'error'|'warning', message }`, one per
 *   fault; `where` a qualified block name, or a sub-system path
 * @returns {Map<string, {level: string, message: string, count: number,
 *   inside: Array<{name: string, level: string, message: string}>}>}
 *   keyed by block name and by every sub-system path above one
 */
export function propagateMarks(entries) {
	const marks = new Map();
	const worse = (a, b) => (a === 'error' || b === 'error' ? 'error' : 'warning');
	for (const e of entries ?? []) {
		if (!e?.where) continue;
		const own = marks.get(e.where);
		if (!own) {
			marks.set(e.where, { level: e.level, message: e.message, count: 1, inside: [] });
		} else {
			// The first message is kept and the rest counted: a badge with three
			// sentences on it is a badge nobody reads, and "and 2 more" is the
			// difference between fixing one field and thinking you are done.
			own.count += 1;
			if (e.level === 'error' && own.level !== 'error') {
				own.level = 'error';
				own.message = e.message;
			}
		}
	}
	// Up the tree. Each block's marks reach every sub-system above it, once
	// per block rather than once per fault, so a sub-system's count is blocks.
	for (const [name, own] of [...marks]) {
		if (own.inside.length) continue;
		for (let p = parentOf(name); p; p = parentOf(p)) {
			const at = marks.get(p);
			const summary = { name, level: own.level, message: own.message };
			if (!at) {
				marks.set(p, { level: own.level, message: '', count: 0, inside: [summary] });
			} else {
				at.inside.push(summary);
				at.level = worse(at.level, own.level);
			}
		}
	}
	// A sub-system's own message, from what it holds. One that has a fault of
	// its own -- a transport with no End -- keeps that as the lead.
	for (const [name, m] of marks) {
		if (!m.inside.length) continue;
		m.inside.sort((a, b) => (a.level === b.level ? a.name.localeCompare(b.name) : a.level === 'error' ? -1 : 1));
		const errors = m.inside.filter((x) => x.level === 'error').length;
		const warnings = m.inside.length - errors;
		// Both halves say what they are counting. `10 with a warning` reads as
		// ten warnings, and it is ten *blocks* -- the model that prompted this
		// has twenty-nine warnings across those ten, so the two numbers a
		// reader sees, here and in the problem strip, did not agree and
		// neither said what it was counting.
		const what = [
			errors ? `${errors} block${errors === 1 ? '' : 's'} with a problem` : '',
			warnings ? `${warnings} block${warnings === 1 ? '' : 's'} with a warning` : '',
		].filter(Boolean).join(', ');
		const inside = `${what} inside ${baseName(name)} — first: ${m.inside[0].name}: ${m.inside[0].message}`;
		m.message = m.message ? `${m.message} Also ${inside}` : `${inside[0].toUpperCase()}${inside.slice(1)}`;
	}
	return marks;
}

/** Qualified names of blocks whose equations mention `name`. */
export function referencesTo(project, name) {
	return referencesToAny(project, [name]).get(name) ?? [];
}

/**
 * The same question asked about many names at once, in one walk of the model.
 *
 * `referencesTo` reads every equation in the model and tokenises it, which is
 * the only way to answer honestly -- a reference is a name in an equation, and
 * whether a bare `Water` means this sub-system's or the top level's depends on
 * what exists. That is fine for one name and quadratic for a selection:
 * deleting a sub-system asks it once per block going, so a 3,789-block model's
 * `Biosphere_models` -- 2,147 blocks out of 3,789 -- tokenised the whole model
 * 2,147 times and took **29 seconds**.
 *
 * The work does not depend on which name is being asked about, so it is done
 * once: every equation is tokenised once, every identifier resolved once, and
 * the answer filed under whichever of the wanted names it landed on.
 *
 * @returns a Map from each name asked about to the qualified names of the
 *   blocks that refer to it, in the order the model holds them
 */
export function referencesToAny(project, names) {
	const want = new Set(names);
	const out = new Map([...want].map((n) => [n, []]));
	if (!want.size) return out;

	// Which names are blocks at all, so a bare reference can be scoped. Built
	// once for the whole walk; this was the other half of the cost.
	const set = new Set(blockNames(project));
	for (const n of want) set.add(n);
	const known = (n) => set.has(n);

	const seen = new Map([...want].map((n) => [n, new Set()]));
	const note = (target, referrer) => {
		if (target == null || target === referrer || !want.has(target)) return;
		const already = seen.get(target);
		if (already.has(referrer)) return;
		already.add(referrer);
		out.get(target).push(referrer);
	};
	// Every name an equation resolves to, tokenised once whatever is asked.
	const resolved = (eq, system, locals = null) => {
		const hits = [];
		try {
			const toks = tokenize(String(eq ?? ''));
			for (let i = 0; i < toks.length; i++) {
				const t = toks[i];
				if (t.type !== 'ident') continue;
				// A built-in function call is not a reference to a block; a
				// user-defined one is, and that is what makes a function
				// impossible to delete while an equation still calls it.
				if (toks[i + 1]?.type === 'lparen' && RESERVED.has(t.value)) continue;
				// A name of the equation's own -- a function's parameter --
				// refers to nothing, whatever the model happens to call.
				if (locals?.has(t.value)) continue;
				const q = resolveReference(t.value, system, known);
				if (q != null) hits.push(q);
			}
		} catch { /* an equation that will not parse refers to nothing */ }
		return hits;
	};
	const noteEquation = (block, key, referrer, system, locals = null) => {
		if (typeof block[key] === 'string') {
			for (const q of resolved(block[key], system, locals)) note(q, referrer);
		}
		for (const e of block.entries ?? []) {
			if (typeof e[key] === 'string') {
				for (const q of resolved(e[key], system, locals)) note(q, referrer);
			}
		}
	};
	const noteName = (value, referrer, system) => {
		if (typeof value !== 'string' || !value.trim()) return;
		note(resolveReference(value.trim(), system, known), referrer);
	};

	// The collections in the order `referencesTo` has always walked them, so
	// the names an error lists come out in the order they used to.
	for (const t of project.transfers ?? []) {
		const q = qualifiedName(t);
		note(t.from, q);
		note(t.to, q);
		noteEquation(t, 'rate', q, systemOf(t));
		// Its availability's operands read the model as the rate does: a
		// parameter that is a transfer's solubility limit cannot be deleted
		// out from under it.
		const a = t.availability;
		if (a && typeof a === 'object') {
			for (const key of OPERAND_KEYS) {
				if (typeof a[key] === 'string') {
					for (const r of resolved(a[key], systemOf(t))) note(r, q);
				}
			}
		}
	}
	for (const s of project.inflows ?? []) {
		const q = qualifiedName(s);
		note(s.to, q);
		noteEquation(s, 'rate', q, systemOf(s));
	}
	for (const e of project.expressions ?? []) {
		noteEquation(e, 'equation', qualifiedName(e), systemOf(e));
	}
	// A block that remembers watches something, and may be driven by an event.
	// Deleting either out from under it leaves a model that no longer builds.
	for (const [kind, plural] of Object.entries(RECORDER_COLLECTION)) {
		for (const b of project[plural] ?? []) {
			const q = qualifiedName(b);
			const system = systemOf(b);
			for (const key of EQUATION_FIELDS[kind]) noteEquation(b, key, q, system);
			for (const key of EVENT_FIELDS[kind]) {
				noteName(b[key], q, system);
				for (const e of b.entries ?? []) noteName(e[key], q, system);
			}
		}
	}
	// A reduction names the blocks it reduces rather than writing an equation,
	// so those are references too -- and deleting one out from under a
	// reduction leaves a model that no longer builds.
	for (const o of project.index_reductions ?? []) {
		const q = qualifiedName(o);
		const system = systemOf(o);
		noteName(o.target, q, system);
		for (const e of o.entries ?? []) noteName(e.target, q, system);
	}
	for (const g of project.block_reductions ?? []) {
		const q = qualifiedName(g);
		const system = systemOf(g);
		for (const t of g.targets ?? []) noteName(t, q, system);
		for (const e of g.entries ?? []) {
			for (const t of e.targets ?? []) noteName(t, q, system);
		}
	}
	// A function's body reads the model like any other equation, in its own
	// sub-system, with its parameters left out: those are names of its own.
	for (const f of project.functions ?? []) {
		noteEquation(f, 'equation', qualifiedName(f), systemOf(f), functionLocals(f, 'equation'));
	}
	for (const c of project.compartments ?? []) {
		const q = qualifiedName(c);
		const system = systemOf(c);
		noteEquation(c, 'initial', q, system);
		noteEquation(c, 'dydt', q, system);
		// The older per-nuclide map: `initial: { "Cs-137": "..." }`.
		if (c.initial && typeof c.initial === 'object' && !Array.isArray(c.initial)) {
			for (const v of Object.values(c.initial)) {
				for (const r of resolved(String(v), system)) note(r, q);
			}
		}
	}
	// A far-field path reads the model through ten settings, every one of them
	// an equation. Missing here, a parameter a path depended on could be
	// deleted without a word -- this is the check that refuses it.
	for (const f of project.farfields ?? []) {
		const q = qualifiedName(f);
		const system = systemOf(f);
		for (const key of FARF_EQUATION_KEYS) noteEquation(f, key, q, system);
	}
	for (const w of project.waste_packages ?? []) {
		const q = qualifiedName(w);
		const system = systemOf(w);
		for (const key of WASTE_EQUATION_KEYS) noteEquation(w, key, q, system);
	}
	// A disruptive event reads its time or rate, each action's share, and --
	// by name rather than by equation -- the blocks it acts on.
	for (const d of project.events ?? []) {
		const q = qualifiedName(d);
		const system = systemOf(d);
		for (const key of DIS_EQUATION_KEYS) noteEquation(d, key, q, system);
		for (const a of d.actions ?? []) {
			noteEquation(a, 'fraction', q, system);
			for (const end of ['block', 'from', 'to']) noteName(a[end], q, system);
		}
	}
	return out;
}

/* --- what the integration depends on ------------------------------------ */
// Moved to ./fingerprint.js, and re-exported at the head of this file so that
// nothing importing `edit` had to change. See the note there for why it is
// worth reading on its own.

/**
 * Deletes a block. Transfers and sources attached to a compartment go with it,
 * since they cannot exist without their endpoint. Anything else that still
 * refers to the block blocks the delete, and is named in the error.
 */
export function deleteBlock(project, name) {
	const found = findBlock(project, name);
	if (!found) throw new EditError(`No block named '${name}'`);

	// Everything that would go: the block, and for a compartment the
	// connections attached to it, which cannot outlive their endpoint.
	// A far-field path is an endpoint like a compartment: a release comes out
	// of it and a source can go in, and both go with it.
	const attached = HOLDS_INVENTORY.has(found.kind)
		? [
			...(project.transfers ?? []).filter((t) => t.from === name || t.to === name),
			...(project.inflows ?? []).filter((s) => s.to === name),
		]
		: [];
	// Qualified, like everything else the editor compares: this list is
	// checked against what `referencesTo` reports, and it reports paths. With
	// bare names, deleting a connected compartment *inside a sub-system* was
	// refused by the transfer that was going to be deleted along with it --
	// invisible at the top level, where the two spellings are the same.
	const removed = [name, ...attached.map((b) => qualifiedName(b))];
	guardTransportParts(project, new Set(removed));

	// Checked before anything is removed. This used to run after the attached
	// connections had already been spliced out, so a refused delete left the
	// compartment in place with its transfers gone -- a failed edit that
	// destroyed data anyway. And checked for the connections going with it
	// as well as for the block: a transfer is read by name too.
	const users = referencesToAny(project, removed);
	for (const gone of removed) {
		const stillReferenced = (users.get(gone) ?? []).filter((n) => !removed.includes(n));
		if (stillReferenced.length) {
			throw new EditError(
				`'${gone}' is still used by ${stillReferenced.join(', ')}. ` +
				`Change those equations first.`,
				stillReferenced,
			);
		}
	}

	for (const b of attached) spliceBlock(project, qualifiedName(b));
	spliceBlock(project, name);
	// A value set for a compartment that no longer exists is not a value set
	// for anything -- and left behind, it makes the model unloadable, because
	// its index is gone from the derived `Compartments` list. `deleteBlocks`
	// has always done this; the single-block path, which is the one the
	// settings dialog's Delete button uses, did not.
	for (const gone of [name, ...attached.map((b) => qualifiedName(b))]) {
		const kind = gone === name ? found.kind
			: (attached.find((b) => qualifiedName(b) === gone)?.from !== undefined
				? 'transfer' : 'inflow');
		if (kind === 'compartment') dropBlockIndex(project, gone, COMPARTMENT_LIST);
		else if (kind === 'transfer') dropBlockIndex(project, gone, TRANSFER_LIST);
	}
	return removed;
}

/**
 * Takes a block out of the model, with no questions asked.
 *
 * Every caller checks first -- what is still using it, what else is going with
 * it -- and those checks differ, so the removal itself is the only part worth
 * sharing.
 */
function spliceBlock(project, name) {
	const found = findBlock(project, name);
	if (!found) return null;
	const list = project[found.collection];
	list.splice(list.indexOf(found.block), 1);
	if (project.layout) delete project.layout[name];
	return found;
}

// --- geometry -------------------------------------------------------------

export function setPosition(project, name, { x, y }) {
	// A file does not come through `validateName`, so the map is made
	// prototype-free before anything merges into it. See `layoutOf`.
	layoutOf(project);
	// Merged into whatever is there, not written over it. A layout entry also
	// carries an explicit size, and replacing the entry on every pointer move
	// meant that dragging a block you had resized snapped it back to the
	// default -- and took the size out of the file with it, not merely off the
	// screen. `setBlockSize` has always merged; this is the other half of that.
	const entry = project.layout[name] ?? {};
	entry.x = Math.round(x);
	entry.y = Math.round(y);
	project.layout[name] = entry;
}

/**
 * Where a block is drawn, or null when nothing has placed it yet.
 *
 * A layout entry can exist without coordinates -- it also holds an explicit
 * size, which survives the block being moved to another diagram -- so this
 * asks about the coordinates rather than about the entry.
 */
export function getPosition(project, name) {
	const entry = project.layout?.[name];
	if (!entry || !Number.isFinite(entry.x) || !Number.isFinite(entry.y)) return null;
	return entry;
}

/**
 * Forgets where a block was drawn, so it is placed again from scratch.
 *
 * What a block moved into a sub-system wants: the coordinates it was dropped
 * at belong to the diagram it has just left, and say nothing about where it
 * belongs among its new neighbours.
 */
export function clearPosition(project, name) {
	const entry = project.layout?.[name];
	if (!entry) return project;
	// The coordinates belong to the diagram it has just left. Its size does
	// not: a block you had made wide is still that block, and deleting the
	// whole entry meant dropping it into a sub-system quietly resized it.
	delete entry.x;
	delete entry.y;
	if (!Object.keys(entry).length) delete project.layout[name];
	return project;
}

/**
 * Lines up or spreads out a hand-picked set of blocks.
 *
 * The other half of `autoLayout`: that one decides where everything goes, and
 * this one is for the times when you have already decided and only want the
 * six of them level. Sub-systems count as blocks here, because on the diagram
 * they are drawn as one.
 *
 * Anything that is not drawn as a node -- a connection, most of all -- has no
 * box to line up and is refused rather than quietly given one at the origin.
 * The caller is expected to have narrowed the selection to what is on the
 * diagram in front of it; this is the backstop.
 *
 * See `alignShapes` for the same eight arrangements over the drawing layer.
 *
 * @param {string[]} names blocks or sub-systems, in any order
 * @param {string} how one of `ARRANGEMENTS`
 * @returns {number} how many actually moved
 */
export function alignBlocks(project, names, how) {
	if (!ARRANGEMENTS.includes(how)) throw new EditError(`No such arrangement: '${how}'`);
	const boxes = [...new Set(names)].map((name) => {
		const kind = findBlock(project, name)?.kind
			?? (name && systems(project).includes(name) ? 'system' : null);
		if (!kind) throw new EditError(`No block named '${name}'`);
		if (kind !== 'system' && !NODE_KINDS.includes(kind)) {
			throw new EditError(`${name} is drawn as a connection, not as a box`);
		}
		// Where it is drawn: a block with no coordinates yet is drawn at the
		// origin, so that is where it is lined up from.
		const pos = project.layout?.[name];
		const size = blockSize(project, name, kind);
		return { name, x: pos?.x ?? 0, y: pos?.y ?? 0, w: size.w, h: size.h };
	});

	let moved = 0;
	alignBoxes(boxes, how).forEach((p, i) => {
		if (p.x === boxes[i].x && p.y === boxes[i].y) return;
		setPosition(project, boxes[i].name, p);
		moved++;
	});
	return moved;
}

/**
 * Automatic positions, from what the diagram actually draws.
 *
 * Two graphs decide where a block goes, and they are not the same graph:
 *
 *   transfers    move material between compartments, so they are the flow.
 *                They rank the compartments into columns, left to right.
 *   influences   say which block reads which, so they are the supply. They
 *                place everything that is not a compartment underneath the
 *                flow, near whatever reads it.
 *
 * Keeping them apart is what makes the result stable: the diagram can hide
 * expressions, parameters, lookup tables and reductions, and hiding them must
 * not move the compartments. So the flow is ranked by transfers alone, and the
 * rest hangs off the positions that produces.
 *
 * The graph work itself -- layering, crossing reduction, coordinates -- is in
 * `layout.js`, which knows nothing about projects. This is the part that knows
 * a project: which blocks are drawn in which sub-system, what a transfer that
 * crosses a sub-system boundary is drawn as, and where an influence into a
 * transfer's rate lands.
 */

/** The kinds of block that are drawn hanging beneath the flow. */
const SUPPLY_KINDS = ['expressions', 'parameters', 'lookups', 'index_reductions', 'block_reductions'];

/**
 * Everything the layout needs about a project, worked out once.
 *
 * Each sub-system is laid out on its own, so the obvious pass asks, for each
 * of them, which of the model's blocks and lines belong to it. On a landscape
 * model that is two hundred sub-systems against twelve thousand influences,
 * and asking took most of two seconds. So they are bucketed instead: a block
 * belongs to exactly one sub-system, and a line is drawn in the few that can
 * see either of its ends -- the sub-system holding it, and each one out to the
 * root, which `scopeChain` already spells out.
 */
function diagramPlan(project) {
	const paths = ['', ...systemPaths(project)];
	const children = new Map(paths.map((p) => [p, []]));
	for (const p of paths) if (p) children.get(parentOf(p))?.push(p);

	const blocks = new Map(paths.map((p) => [p, []]));
	for (const kind of ['compartments', ...SUPPLY_KINDS]) {
		for (const b of project[kind] ?? []) {
			blocks.get(systemOf(b))?.push({ id: qualifiedName(b), kind: SINGULAR[kind] });
		}
	}

	const links = new Map(paths.map((p) => [p, []]));
	const transfers = new Map(paths.map((p) => [p, []]));
	const inflows = new Map(paths.map((p) => [p, []]));
	const drawnIn = (a, b) => {
		const where = new Set(scopeChain(parentOf(a ?? '')));
		for (const s of scopeChain(parentOf(b ?? ''))) where.add(s);
		return where;
	};
	for (const t of project.transfers ?? []) {
		for (const s of drawnIn(t.from, t.to)) transfers.get(s)?.push(t);
	}
	for (const s of project.inflows ?? []) {
		for (const at of drawnIn(s.to, s.to)) inflows.get(at)?.push(s);
	}
	for (const l of influences(project)) {
		for (const s of drawnIn(l.from, l.to)) links.get(s)?.push(l);
	}

	return { paths, children, blocks, links, transfers, inflows };
}

/**
 * What the diagram of `system` draws: the flow, the blocks that supply it, and
 * the influences rewritten so that every name is one of the nodes on screen.
 *
 * A transfer whose far end is inside a child sub-system is drawn to that
 * sub-system's own node, and so is an influence -- `_visibleEnd` in the
 * diagram is the same rule, and the two have to agree or blocks end up placed
 * for lines that are not drawn.
 */
function diagramOf(project, system, plan) {
	const here = parts(system);
	const visible = (name) => {
		if (name == null) return null;
		const owner = parentOf(name);
		if (owner === system) return name;
		if (!isWithin(owner, system)) return null;
		return qualify(system, parts(owner)[here.length]);
	};

	const flow = [];
	const supply = [];
	for (const { id, kind } of plan.blocks.get(system) ?? []) {
		const node = { id, ...blockSize(project, id, kind) };
		(kind === 'compartment' ? flow : supply).push(node);
	}
	// A sub-system stands for its contents, so it takes part in the flow: a
	// model whose top level is nothing but sub-systems still has a shape.
	for (const path of plan.children.get(system) ?? []) {
		flow.push({ id: path, ...blockSize(project, path, 'system') });
	}

	const inFlow = new Set(flow.map((n) => n.id));
	const edges = [];
	for (const t of plan.transfers.get(system) ?? []) {
		const from = visible(t.from);
		const to = visible(t.to);
		if (!from || !to || from === to) continue;
		if (inFlow.has(from) && inFlow.has(to)) edges.push({ from, to });
	}

	const links = [];
	for (const l of plan.links.get(system) ?? []) {
		const from = visible(l.from);
		const to = visible(l.to);
		if (!from || !to || from === to) continue;
		// Between two flow nodes this is a dependency across a sub-system
		// boundary, which is as much a reason to put one left of the other as
		// a transfer is. Compartments themselves are never read by anything --
		// only expressions, transfers and reductions read -- so this never
		// distorts a plain compartment flow.
		if (inFlow.has(from) && inFlow.has(to)) edges.push({ from, to });
		else links.push({ from, to });
	}

	return { system, visible, flow, supply, edges, links };
}

/**
 * Where an influence can land, besides on a node: the middle of a connection,
 * which is where the diagram draws the end of an arrow into a rate.
 *
 * Most parameters in a real model feed a transfer rate rather than a block, so
 * without this they would have nothing to be near and would pile up in file
 * order at the left.
 */
function anchorPoints(view, plan, at) {
	const anchors = new Map();
	for (const n of [...view.flow, ...view.supply]) {
		const p = at.get(n.id);
		if (p) anchors.set(n.id, { x: p.x + n.w / 2, y: p.y + n.h / 2 });
	}
	const midpoint = (...ends) => {
		const known = ends.map((e) => anchors.get(e)).filter(Boolean);
		if (!known.length) return null;
		return {
			x: known.reduce((s, p) => s + p.x, 0) / known.length,
			y: known.reduce((s, p) => s + p.y, 0) / known.length,
		};
	};
	for (const t of plan.transfers.get(view.system) ?? []) {
		const mid = midpoint(view.visible(t.from), view.visible(t.to));
		if (mid) anchors.set(qualifiedName(t), mid);
	}
	for (const s of plan.inflows.get(view.system) ?? []) {
		const mid = midpoint(view.visible(s.to));
		if (mid) anchors.set(qualifiedName(s), mid);
	}
	return anchors;
}

/** Moves a set of positions so that the top left of it is at the origin. */
function toOrigin(at, originX, originY) {
	let minX = Infinity;
	let minY = Infinity;
	for (const p of at.values()) {
		minX = Math.min(minX, p.x);
		minY = Math.min(minY, p.y);
	}
	if (!Number.isFinite(minX)) return at;
	for (const [id, p] of at) {
		// On the lattice: node heights are not multiples of the pitch -- a
		// compartment is 54 -- so stacking rows by height alone lands between
		// the lines, and the grid drawn behind the canvas would disagree with
		// every row of a model nobody had touched by hand.
		at.set(id, {
			x: onGrid(p.x - minX + originX),
			y: onGrid(p.y - minY + originY),
		});
	}
	return at;
}

const gapsFrom = (spacingX, spacingY) => ({
	gapX: Math.max(40, spacingX - DEFAULT_SIZE.compartment.w),
	gapY: Math.max(24, spacingY - DEFAULT_SIZE.compartment.h),
});

/**
 * Whether anything `autoLayout` would place is still without a position.
 *
 * With a plan and a sub-system, only that sub-system's own diagram: its
 * blocks, and the child sub-systems that stand on it as nodes. Without them,
 * the whole model. Exactly the set the loop below writes to, so a `false` here
 * means the layout would place nothing.
 */
function needsPlacing(project, plan = null, system = null) {
	if (plan) {
		for (const { id } of plan.blocks.get(system) ?? []) {
			if (!getPosition(project, id)) return true;
		}
		for (const path of plan.children.get(system) ?? []) {
			if (!getPosition(project, path)) return true;
		}
		return false;
	}
	for (const kind of ['compartments', ...SUPPLY_KINDS]) {
		for (const b of project[kind] ?? []) {
			if (!getPosition(project, qualifiedName(b))) return true;
		}
	}
	for (const path of systemPaths(project)) {
		if (!getPosition(project, path)) return true;
	}
	return false;
}

/**
 * Lays the whole model out, one sub-system at a time.
 *
 * Each sub-system is laid out on its own because that is how it is drawn: one
 * at a time, in its own coordinates. Ranking the whole model at once would
 * spread a sub-system's blocks across a canvas nobody sees at once.
 *
 * Positions the user has already set are left alone -- this fills in the
 * blanks. `relayout` on the diagram clears them first, which is what makes the
 * same function serve as both "tidy this up" and "place what has just
 * arrived".
 */
export function autoLayout(project, { spacingX = 260, spacingY = 110, originX = 90, originY = 70 } = {}) {
	layoutOf(project);
	// Nothing to place. The diagram calls this on every edit -- `setProject`
	// does, and every edit goes through it -- and on a landscape model the
	// plan alone buckets twelve thousand influences across two hundred
	// sub-systems before the ranking starts. All of that was computed and then
	// thrown away by the `getPosition` test at the bottom of the loop, because
	// every block already had a position. The answer is the same; this is the
	// work it takes to get there.
	if (!needsPlacing(project)) return project;
	const { gapX, gapY } = gapsFrom(spacingX, spacingY);
	const plan = diagramPlan(project);

	for (const system of plan.paths) {
		if (!needsPlacing(project, plan, system)) continue;
		const view = diagramOf(project, system, plan);
		if (!view.flow.length && !view.supply.length) continue;

		const flow = layoutFlow(view.flow, view.edges, { gapX, gapY });
		const anchors = anchorPoints(view, plan, flow.at);
		const rows = hangRows(view.supply, view.links, anchors, {
			top: view.flow.length ? flow.h + gapY * 1.5 : 0,
			gapX,
			gapY,
		});

		const at = toOrigin(new Map([...flow.at, ...rows.at]), originX, originY);
		for (const [name, p] of at) {
			if (getPosition(project, name)) continue;
			setPosition(project, name, p);
		}
	}
	return project;
}

/**
 * Gives a position to blocks that have none, without moving anything.
 *
 * A block added from the block list, or one that a diagram toggle has just
 * revealed, arrives with no geometry. Putting it at the origin buries it under
 * whatever is already there, and putting it in a row at the bottom by kind --
 * which is what this used to do -- puts a parameter as far as it can be from
 * the transfer that reads it.
 *
 * So it is placed the way `autoLayout` places supply: under the middle of
 * whatever it is joined to, below everything already on the diagram.
 */
export function placeLoose(project, { spacingX = 260, spacingY = 110, originX = 90, originY = 70 } = {}) {
	layoutOf(project);
	// This runs on every diagram toggle, and almost always has nothing to do.
	const unplaced = (name) => !getPosition(project, name);
	const anyMissing = ['compartments', ...SUPPLY_KINDS]
		.some((kind) => (project[kind] ?? []).some((b) => unplaced(qualifiedName(b))))
		|| systemPaths(project).some(unplaced);
	if (!anyMissing) return project;

	const { gapX, gapY } = gapsFrom(spacingX, spacingY);
	const plan = diagramPlan(project);

	for (const system of plan.paths) {
		const view = diagramOf(project, system, plan);
		const placed = new Map();
		const missing = [];
		let bottom = -Infinity;
		for (const n of [...view.flow, ...view.supply]) {
			const p = getPosition(project, n.id);
			if (!p) { missing.push(n); continue; }
			placed.set(n.id, { x: p.x, y: p.y });
			bottom = Math.max(bottom, p.y + n.h);
		}
		if (!missing.length) continue;

		const anchors = anchorPoints(view, plan, placed);
		const rows = hangRows(missing, view.links, anchors, {
			top: Number.isFinite(bottom) ? bottom + gapY : originY,
			gapX,
			gapY,
		});

		// With nothing on the diagram to be near, there was nothing to anchor
		// the row to either, so it starts where a fresh layout would.
		let shift = 0;
		if (!anchors.size) {
			let leftmost = Infinity;
			for (const p of rows.at.values()) leftmost = Math.min(leftmost, p.x);
			if (Number.isFinite(leftmost)) shift = originX - leftmost;
		}
		for (const [name, p] of rows.at) {
			// On the lattice, as `autoLayout` places things: a block that
			// arrives from the block list, or one a diagram toggle has just
			// revealed, should land where a dragged one would.
			setPosition(project, name, { x: onGrid(p.x + shift), y: onGrid(p.y) });
		}
	}
	return project;
}

/**
 * Drops geometry for blocks that no longer exist.
 *
 * Everything drawn on the diagram keeps a position, not just compartments:
 * expressions are nodes too, and transfers may carry a waypoint. Keying only
 * on compartments silently deleted an expression's position on every edit,
 * which made expressions impossible to move.
 */
export function pruneLayout(project) {
	if (!project.layout) return project;

	// A sub-system is drawn as a node too, so its position is a layout entry
	// with no block behind it.
	const names = new Set(systemPaths(project));
	for (const kind of KINDS) {
		for (const b of project[kind] ?? []) names.add(qualifiedName(b));
	}

	for (const k of Object.keys(project.layout)) {
		// Edge geometry is stored under an "edge:<name>" key, and a pipe's
		// under "edge:<name>@<canvas>" -- which goes with the canvas too.
		const edge = parseEdgeKey(k);
		const owner = edge ? edge.name : k;
		const canvasGone = edge?.view != null && edge.view !== '' && !names.has(edge.view);
		if (!names.has(owner) || canvasGone) delete project.layout[k];
	}
	return project;
}

/** Layout key prefix for a connection's waypoint. */
export const EDGE_PREFIX = 'edge:';

/**
 * The layout key of a connection's geometry, on one canvas.
 *
 * A connection is drawn whole on one canvas -- the one both its ends can be
 * seen from, as themselves or as the sub-system nodes holding them -- and its
 * bend there is `edge:<name>`, as it always was. On a deeper canvas one end is
 * out of sight and the line ends in a pipe that says where it goes, put where
 * the reader dragged it. The two used to be one point: dragging the pipe
 * inside a sub-system bent the line on the canvas above, and bending that line
 * moved the pipe. So a pipe is `edge:<name>@<canvas>`, one per canvas it is
 * drawn on, and `view` is that canvas -- null for the whole drawing.
 */
export function waypointKey(name, view = null) {
	return view == null ? EDGE_PREFIX + name : `${EDGE_PREFIX}${name}@${view}`;
}

/**
 * What a layout key is about, if it is a connection's: the connection, and
 * the canvas (`null` for the whole drawing). A name never holds `@`.
 */
export function parseEdgeKey(key) {
	if (!String(key).startsWith(EDGE_PREFIX)) return null;
	const rest = key.slice(EDGE_PREFIX.length);
	const at = rest.indexOf('@');
	return at < 0 ? { name: rest, view: null } : { name: rest.slice(0, at), view: rest.slice(at + 1) };
}

/** The bend point of a transfer or source on one canvas, or null when it runs straight. */
export function getWaypoint(project, name, view = null) {
	return project.layout?.[waypointKey(name, view)] ?? null;
}

export function setWaypoint(project, name, point, view = null) {
	layoutOf(project);
	const key = waypointKey(name, view);
	if (point == null) {
		delete project.layout[key];
		return;
	}
	project.layout[key] = {
		x: Math.round(point.x),
		y: Math.round(point.y),
	};
}

/**
 * A connection's geometry dropped on every canvas it is drawn on: one of its
 * ends has moved, and each bend and pipe was placed against the old ones.
 */
export function clearWaypoints(project, name) {
	for (const key of Object.keys(project.layout ?? {})) {
		if (parseEdgeKey(key)?.name === name) delete project.layout[key];
	}
}

// --- index lists ------------------------------------------------------------

/** All index lists, or an empty array. */
/**
 * The index lists a model has, including the ones it derives.
 *
 * Three of them are not written down. The element dimension follows the
 * nuclide list; the compartment and transfer dimensions follow the model's own
 * blocks. All three are worked out here and marked `derived`: the editor shows
 * them and a block can be indexed by them, but nothing can edit one, because
 * there is nothing to edit that would not immediately be recomputed. See
 * ../domain/indexlists.js.
 */
export function indexLists(project) {
	return deriveBlockLists(deriveElements(project?.index_lists ?? []), project);
}

/**
 * The first pair of a block's dimensions that are one dimension twice.
 *
 * The rules themselves are in ./indexlists.js, over the lists; this is the
 * project-level way in, so that a caller with a raw model does not have to
 * know that the derived lists have to be worked out first.
 *
 * @returns {{a: string, b: string, root: string}|null}
 */
export function dimensionsClash(project, dims) {
	return clashingDimensions(indexLists(project), dims);
}

/**
 * Which output series contribute nothing to the run, by position.
 *
 * Every point of one of these lies outside the run's start and end -- a
 * `times` list written for a run that has since been shortened, a `from` past
 * the end. Skipped rather than refused: the solver never reaches those times,
 * so it cannot report them, and there is nothing else to say. Said in the
 * saved-times editor and on the sidebar, so a series that quietly does nothing
 * is not mistaken for one that is working.
 */
export function outsideSeries(project) {
	const sim = project?.simulation ?? {};
	if ((sim.spacing ?? 'log') !== 'series' && sim.spacing !== 'both') return [];
	const start = Number(sim.start_time ?? 0);
	const end = Number(sim.end_time ?? 0);
	const list = Array.isArray(sim.output_times) ? sim.output_times : [];
	const out = [];
	list.forEach((spec, i) => { if (!seriesTimes(spec, start, end).length) out.push(i); });
	return out;
}

// --- scenarios --------------------------------------------------------------

/**
 * The scenario index list, if the model has one.
 *
 * Ecolego marks exactly one list with `predefined-type = SCENARIOS`, and it is
 * a root: a sub-set or a mapping of it is the same dimension but not the
 * declaration of it. So the first flagged list is the one.
 */
export function scenarioList(project) {
	return (project?.index_lists ?? []).find((l) => l.for_scenarios) ?? null;
}

/**
 * Whether a dimension is the scenario dimension, by whatever name it reaches
 * it.
 *
 * A sub-set or a mapping of the scenario list is the same dimension -- which
 * is how `IndexSpace` decides it, and the simulation drops all of them: one
 * scenario is live and every block indexed by it is read at that one. A panel
 * asking "is there a value per index here" has to ask this rather than compare
 * names, or a sub-set of the scenarios looks like an ordinary dimension.
 */
export function isScenarioDim(project, name) {
	const root = scenarioList(project)?.name ?? null;
	if (!root) return false;
	const byName = new Map((project?.index_lists ?? []).map((l) => [l.name, l]));
	let at = name;
	// Bounded by the number of lists: a cycle in `sub_set_of` is a broken file
	// rather than a reason to hang.
	for (let i = 0; at && i <= byName.size; i++) {
		if (at === root) return true;
		const list = byName.get(at);
		at = parentListName(list);
	}
	return false;
}

/** The scenarios a model offers, by name; the disabled ones do not run. */
export function scenarioNames(project) {
	return (scenarioList(project)?.indices ?? [])
		.map((i) => (typeof i === 'string' ? { name: i, enabled: true } : i))
		.filter((i) => i?.name && i.enabled !== false)
		.map((i) => i.name);
}

/**
 * Which scenario a run uses: the one chosen, or the first.
 *
 * Ecolego runs one simulation per scenario; this tool runs the one that is
 * selected, reading every block indexed by the scenario list at that index --
 * which is what a single one of those runs does.
 */
export function activeScenario(project) {
	const names = scenarioNames(project);
	if (!names.length) return null;
	return names.includes(project?.scenario) ? project.scenario : names[0];
}

/** Chooses the scenario to run. */
export function setScenario(project, name) {
	const names = scenarioNames(project);
	if (name == null) { delete project.scenario; return null; }
	if (!names.includes(name)) {
		throw new EditError(
			`'${name}' is not a scenario in this model`
			+ (names.length ? ` (${names.join(', ')})` : ''),
		);
	}
	project.scenario = name;
	return name;
}

/**
 * Whether any parameter carries a distribution, block-level or per index.
 *
 * Cheap on purpose: the panel asks on every render, and the answer decides
 * whether a probabilistic run is offered at all. Reading the model rather than
 * building it, because building a large one is a second and this is a question
 * about what is written down.
 */
export function hasDistributions(project) {
	for (const p of project?.parameters ?? []) {
		if (p.pdf) return true;
		for (const e of p.entries ?? []) if (e.pdf) return true;
	}
	// A point of a lookup table may carry its own spread, which is dice as
	// much as a parameter's is: the curve is different in every realisation.
	// Missed here, the Probabilistic button is not offered at all for a model
	// whose only uncertainty is in its tables.
	for (const l of project?.lookups ?? []) {
		if (hasPointSpread(l.points)) return true;
		for (const e of l.entries ?? []) if (hasPointSpread(e.points)) return true;
	}
	// A disruptive event that draws its occurrences is dice too: every
	// realisation is a different run even with every parameter fixed.
	for (const d of project?.events ?? []) {
		if ((d.timing ?? 'at') === 'poisson' && d.sampled !== false) return true;
	}
	return false;
}

/** Whether any point of a table carries a distribution: `[x, y, pdf]`. */
function hasPointSpread(points) {
	return Array.isArray(points) && points.some((pt) => Array.isArray(pt) && pt[2]);
}

/** Whether a list is worked out from another rather than written down. */
export function isDerivedList(project, name) {
	return !!indexLists(project).find((l) => l.name === name)?.derived;
}

/** Refuses an edit to a list the model does not actually store. */
function assertEditable(project, name) {
	if (!isDerivedList(project, name)) return;
	const list = indexLists(project).find((l) => l.name === name);
	const follows = list?.auto === 'compartments' ? "the model's compartments"
		: list?.auto === 'transfers' ? "the model's transfers"
			: 'the nuclide list';
	throw new EditError(
		`'${name}' follows ${follows}, so it cannot be edited on its own. `
		+ `Change ${list?.auto ? 'the model' : 'the nuclides'} and it changes with it.`,
	);
}

export function findIndexList(project, name) {
	const list = indexLists(project).find((l) => l.name === name) ?? null;
	if (list) normaliseListIndices(list);
	return list;
}

/**
 * Indices may be written as bare strings in a hand-edited file. Project
 * normalises those on load, but these helpers work on the raw object, so they
 * normalise in place the first time a list is touched.
 */
function normaliseListIndices(list) {
	if (!Array.isArray(list.indices)) { list.indices = []; return list; }
	let changed = false;
	list.indices = list.indices.map((i) => {
		if (typeof i === 'string') { changed = true; return { name: i, enabled: true }; }
		if (i.enabled === undefined) { changed = true; return { ...i, enabled: true }; }
		return i;
	});
	return list;
}

export function addIndexList(project, { name, base, indices } = {}) {
	// Write down what every block is indexed by *now*, so adding a list cannot
	// change it behind the user's back.
	makeDimensionsExplicit(project);
	if (!project.index_lists) project.index_lists = [];
	// `name` is a demand and fails if it is taken; `base` is a suggestion that
	// steps aside for one that is.
	const n = name ?? uniqueIndexListName(project, base ?? 'Dimension');
	// The same gate a block's name goes through, since a list's name is a key
	// too: on every entry's index map, and in the dimension pickers.
	// `Project` would refuse the model afterwards; better refused here, where
	// the name can still be changed.
	if (!NAME_RE.test(n)) {
		throw new EditError(
			`'${n}' is not a valid index list name (letters, digits and underscore; `
			+ 'must not start with a digit)',
		);
	}
	if (RESERVED.has(n)) throw new EditError(`'${n}' is a reserved name.`);
	if (findIndexList(project, n)) {
		throw new EditError(`An index list named '${n}' already exists`);
	}
	const list = {
		name: n,
		indices: (indices ?? ['i1', 'i2']).map((i) => (
			typeof i === 'string' ? { name: i, enabled: true } : i
		)),
	};
	project.index_lists.push(list);
	return list;
}

/**
 * What an index list is defined against: nothing, a sub-set of another list, or
 * a mapping onto one.
 *
 *   plain     an axis of its own
 *   sub_set   a few of another list's indices, by name -- `Extremes` out of
 *             `Climate`. Ecolego's sub-set handling.
 *   mapping   several of another list's indices grouped into one of these --
 *             an element per nuclide, a coarse class per object. Ecolego's
 *             Mapping.
 *
 * Changing the role rewrites the list to suit it: a sub-set keeps only the
 * indices its parent has, and a mapping starts with every parent index
 * unassigned, because a half-written mapping is a model that will not build.
 */
export function setListRole(project, name, role, target = null) {
	assertEditable(project, name);
	const list = findIndexList(project, name);
	if (!list) throw new EditError(`No index list named '${name}'`);
	if (list.for_contaminants || list.for_nuclides || list.derived) {
		throw new EditError(`'${name}' is built in, so it cannot be defined from another list`);
	}

	if (role === 'plain') {
		delete list.sub_set_of;
		delete list.mapping;
		return list;
	}

	const parent = target ? findIndexList(project, target) : null;
	if (!parent) throw new EditError(`No index list named '${target}'`);
	if (parent.name === name) throw new EditError('A list cannot be defined from itself');
	if (parent.sub_set_of || parent.mapping) {
		throw new EditError(
			`'${parent.name}' is itself defined from another list. A sub-set or a `
			+ 'mapping has to be taken from a root list.',
		);
	}

	if (role === 'sub_set') {
		delete list.mapping;
		list.sub_set_of = parent.name;
		// A sub-set holds only names its parent has. Anything else would fail
		// to resolve, so it is dropped here where it can be seen rather than
		// at the next run.
		const have = new Set((parent.indices ?? []).map((i) => i.name));
		list.indices = (list.indices ?? []).filter((i) => have.has(i.name));
		return list;
	}

	if (role === 'mapping') {
		delete list.sub_set_of;
		// Kept if it was already mapped to the same list: re-picking the same
		// target should not throw the pairs away.
		const pairs = list.mapping?.to === parent.name ? (list.mapping.pairs ?? []) : [];
		list.mapping = { to: parent.name, pairs };
		return list;
	}

	throw new EditError(`'${role}' is not a way to define an index list`);
}

/**
 * Which index of a mapped list a parent index belongs to.
 *
 * The many-to-one direction, which is the one worth editing: an element list
 * is written by saying which element each nuclide is, not the other way round.
 * `null` unassigns it.
 */
export function setMappedIndex(project, name, parentIndex, ownIndex) {
	assertEditable(project, name);
	const list = findIndexList(project, name);
	if (!list?.mapping) throw new EditError(`'${name}' is not a mapped index list`);
	const parent = findIndexList(project, list.mapping.to);
	if (!parent) throw new EditError(`No index list named '${list.mapping.to}'`);
	if (!(parent.indices ?? []).some((i) => i.name === parentIndex)) {
		throw new EditError(`'${parentIndex}' is not an index of '${parent.name}'`);
	}
	if (ownIndex != null && !(list.indices ?? []).some((i) => i.name === ownIndex)) {
		throw new EditError(`'${ownIndex}' is not an index of '${name}'`);
	}
	// One parent index belongs to one index here, so the old pair goes.
	const pairs = (list.mapping.pairs ?? []).filter((p) => p.to !== parentIndex);
	if (ownIndex != null) pairs.push({ from: ownIndex, to: parentIndex });
	list.mapping.pairs = pairs;
	return list;
}

/**
 * Marks an index list as the model's scenarios, or stops it being them.
 *
 * Exactly one list can be: Ecolego has a single `SCENARIOS` predefined type,
 * and the whole idea is that one index of it is live at a time. Making a
 * second the scenarios would leave the question of which one the simulation
 * follows, so the first is demoted.
 */
export function setScenarioList(project, name, on = true) {
	const list = findIndexList(project, name);
	if (!list) throw new EditError(`No index list named '${name}'`);
	if (on && (list.for_contaminants || list.for_nuclides || list.derived)) {
		throw new EditError(`'${name}' is built in, so it cannot be the scenarios`);
	}
	for (const other of project.index_lists ?? []) {
		if (other !== list) delete other.for_scenarios;
	}
	if (on) list.for_scenarios = true;
	else delete list.for_scenarios;
	// The chosen scenario has to be one of this list's indices, or none.
	const names = scenarioNames(project);
	if (!names.includes(project.scenario)) {
		if (names.length) project.scenario = names[0];
		else delete project.scenario;
	}
	return list;
}

function uniqueIndexListName(project, base) {
	if (!findIndexList(project, base)) return base;
	for (let i = 1; i < 1000; i++) {
		const n = `${base}${i}`;
		if (!findIndexList(project, n)) return n;
	}
	throw new EditError(`Could not find a free name based on '${base}'`);
}

/**
 * Renames an index list and follows it into every block dimension, entry key,
 * sub-set reference and mapping target.
 */
export function renameIndexList(project, oldName, newName) {
	assertEditable(project, oldName);
	if (oldName === newName) return;
	if (!NAME_RE.test(newName)) {
		throw new EditError(
			'An index list name uses letters, digits and underscore, and may not start '
			+ 'with a digit.',
		);
	}
	// `__proto__` most of all: a list's name keys every entry's index map,
	// and renaming a list to that left every per-index value keyed on
	// nothing -- silently the block's default from then on.
	if (RESERVED.has(newName)) throw new EditError(`'${newName}' is a reserved name.`);
	const list = findIndexList(project, oldName);
	if (!list) throw new EditError(`No index list named '${oldName}'`);
	if (list.for_contaminants || list.for_nuclides) {
		throw new EditError(
			`'${oldName}' is ${list.for_contaminants ? 'the material catalogue' : 'the radionuclide dimension'}`
			+ ` and keeps its name; the Decay panel and the nuclide table are `
			+ `written in terms of it.`,
		);
	}
	if (findIndexList(project, newName)) {
		throw new EditError(`An index list named '${newName}' already exists`);
	}

	list.name = newName;

	for (const other of indexLists(project)) {
		if (other.sub_set_of === oldName) other.sub_set_of = newName;
		if (other.mapping?.to === oldName) other.mapping.to = newName;
	}

	for (const kind of KINDS) {
		for (const block of project[kind] ?? []) {
			if (Array.isArray(block.index_lists)) {
				block.index_lists = block.index_lists.map((d) => (d === oldName ? newName : d));
			}
			for (const entry of block.entries ?? []) {
				if (entry.index && oldName in entry.index) {
					entry.index[newName] = entry.index[oldName];
					delete entry.index[oldName];
				}
			}
		}
	}
}

/** Blocks and lists that depend on an index list. */
export function indexListUsers(project, name) {
	const users = [];
	for (const other of indexLists(project)) {
		if (other.sub_set_of === name || other.mapping?.to === name) users.push(other.name);
	}
	for (const kind of KINDS) {
		for (const block of project[kind] ?? []) {
			if ((block.index_lists ?? []).includes(name)) users.push(block.name);
		}
	}
	return [...new Set(users)];
}

export function deleteIndexList(project, name) {
	assertEditable(project, name);
	const list = findIndexList(project, name);
	if (!list) throw new EditError(`No index list named '${name}'`);
	if (list.for_contaminants || list.for_nuclides) {
		throw new EditError(
			`'${name}' is ${list.for_contaminants ? 'the material catalogue' : 'the radionuclide dimension'}`
			+ `, which every model has. Remove its `
			+ `${list.for_contaminants ? 'materials' : 'nuclides'} instead.`,
		);
	}
	const users = indexListUsers(project, name);
	if (users.length) {
		throw new EditError(
			`'${name}' is still used by ${users.join(', ')}. Remove it from those first.`,
			users,
		);
	}
	project.index_lists.splice(project.index_lists.indexOf(list), 1);
}

export function addIndex(project, listName, indexName) {
	assertEditable(project, listName);
	const list = findIndexList(project, listName);
	if (!list) throw new EditError(`No index list named '${listName}'`);
	if (list.indices.some((i) => i.name === indexName)) {
		throw new EditError(`'${indexName}' is already in '${listName}'`);
	}
	// A radionuclide is a material: adding one to the sub-set puts it in the
	// catalogue too, which is what `materialAdded` does -- every material goes
	// in `allMaterial`, and one that is a nuclide goes in `allRadionuclides`
	// as well. Without this the sub-set would name something its root does not
	// have, which is a model that will not load, and the only way to add a
	// nuclide would be to type it into the catalogue and then pick it here.
	const asNuclide = isNuclideRole(project, list);
	if (asNuclide) {
		const root = materialList(project);
		if (root && root !== list && !root.indices.some((i) => i.name === indexName)) {
			root.indices.push({ name: indexName, enabled: true });
		}
	}
	const index = { name: indexName, enabled: true };
	list.indices.push(index);
	if (list.for_nuclides || list.for_contaminants) {
		syncNuclides(project);
		// ...and the element it belongs to, so the grouping still covers the
		// materials it groups. A derived element list works this out for
		// itself; a stored one -- which is what an imported model has -- does
		// not follow anything, and a material no element stands for is a
		// material nothing indexed by the elements can be read at.
		addElementFor(project, indexName);
	}
	if (asNuclide) {
		// A nuclide with no half-life anywhere stops the model running, and
		// the useful default for a name ICRP 107 has never heard of is stable:
		// the model still runs, and the value is there to be changed. Guessing
		// a decay rate would be worse than assuming none. This is a much rarer
		// case than it was -- the database has 1,512 nuclides -- so it now
		// means a name that is not a nuclide, or one spelled differently.
		if (halfLifeOf(project, indexName) == null) {
			setHalfLife(project, indexName, Infinity);
		}
	}
	// Returned like every other add*, so a caller can select what it made.
	return index;
}

/**
 * Gives a material its element, in an element list that is written down.
 *
 * The element of a nuclide's name is its symbol, so C-12 joins C-14 under `C`:
 * they are one element and one sorption coefficient is right for both. A name
 * that is not a nuclide's is its own element -- water, or Lotka-Volterra's
 * rabbits -- because there is nothing else it could belong to.
 *
 * Only the element list. A model's own grouping of its materials -- `Species`
 * in 32 of the corpus files -- is a classification this cannot guess at, so a
 * new material is left out of it and the build says so if anything reads it,
 * naming the list and the missing index.
 */
function addElementFor(project, materialName) {
	const root = materialList(project);
	if (!root) return;
	const elements = indexLists(project).find((l) => !l.derived && l.mapping?.to === root.name
		&& (l.for_elements || l.name === ELEMENT_LIST));
	if (!elements) return;
	const name = elementOf(materialName) ?? materialName;
	if (!name) return;
	if (!(elements.indices ?? []).some((i) => i.name === name)) {
		(elements.indices ??= []).push({ name, enabled: true });
	}
	elements.mapping.pairs ??= [];
	if (!elements.mapping.pairs.some((p) => p.to === materialName)) {
		elements.mapping.pairs.push({ from: name, to: materialName });
	}
}

/**
 * Removes an index, and any entry keyed by it.
 *
 * Removing a radionuclide removes the *material*: there is one material, and
 * the radionuclide list is the part of the catalogue that has a half-life, so
 * taking it out of one takes it out of both -- which is what deleting it in
 * Ecolego's Materials view does. A material that should stay in the model
 * without decaying is not removed here; it is added to the catalogue, where
 * it is a material like stable carbon or water.
 */
export function removeIndex(project, listName, indexName) {
	assertEditable(project, listName);
	const list = findIndexList(project, listName);
	if (!list) throw new EditError(`No index list named '${listName}'`);
	const at = list.indices.findIndex((i) => i.name === indexName);
	if (at < 0) throw new EditError(`'${indexName}' is not in '${listName}'`);
	if (isNuclideRole(project, list)) {
		const root = materialList(project);
		if (root && root !== list && root.indices.some((i) => i.name === indexName)) {
			// Through the catalogue, whose own removal takes every sub-set of
			// it -- this list among them -- and every mapping pair with it.
			return removeIndex(project, root.name, indexName);
		}
	}
	list.indices.splice(at, 1);

	for (const kind of KINDS) {
		for (const block of project[kind] ?? []) {
			if (!block.entries) continue;
			block.entries = block.entries.filter((e) => e.index?.[listName] !== indexName);
		}
	}
	// A sub-set cannot keep an index its root has lost.
	for (const other of indexLists(project)) {
		normaliseListIndices(other);
		if (other.sub_set_of === listName) {
			other.indices = other.indices.filter((i) => i.name !== indexName);
		}
		if (other.mapping?.to === listName) {
			other.mapping.pairs = (other.mapping.pairs ?? []).filter((p) => p.to !== indexName);
		}
	}
	if (list.for_contaminants || list.for_nuclides) {
		syncNuclides(project);
		// The material is gone, so what was known about it goes with it. A
		// half-life left behind would come back the next time a material of
		// that name was added, saying something the model never said.
		if (list.for_contaminants && project.half_lives) delete project.half_lives[indexName];
		// And the element it was the last member of. `materialRenamed` does the
		// same -- `allElements.remove(oldElementIndex)` once no radionuclide of
		// that element remains -- and an element standing for nothing is a
		// column in every chemistry parameter that can never be read.
		if (list.for_contaminants) dropEmptyElement(project, indexName);
	}
}

/**
 * Drops an element that the material just removed was the last member of.
 *
 * Only an element list that is written down: a derived one follows the
 * materials by itself. And only an element nothing maps to any more, so an
 * element a modeller put there for a material still to come is left alone --
 * it has nothing mapped to it either, but it never had.
 */
function dropEmptyElement(project, materialName) {
	const root = materialList(project);
	if (!root) return;
	const elements = indexLists(project).find((l) => !l.derived && l.mapping?.to === root.name
		&& (l.for_elements || l.name === ELEMENT_LIST));
	if (!elements) return;
	const name = elementOf(materialName) ?? materialName;
	if (!(elements.indices ?? []).some((i) => i.name === name)) return;
	if ((elements.mapping.pairs ?? []).some((p) => p.from === name)) return;
	// Through `removeIndex`, so that anything keyed by that element goes with
	// it rather than being left pointing at a column that no longer exists.
	removeIndex(project, elements.name, name);
}

/**
 * Renames one index, and follows it everywhere the old name was written.
 *
 * Everywhere is: the entry keys of every block indexed by this list, the
 * sub-sets that select it by name, the mappings that group it, and the
 * `scenario` chosen for the run. Without this a typo could only be fixed by
 * removing the index -- which takes every value keyed on it with it -- and
 * adding it back.
 */
export function renameIndex(project, listName, oldName, newName) {
	assertEditable(project, listName);
	const list = findIndexList(project, listName);
	if (!list) throw new EditError(`No index list named '${listName}'`);
	const idx = list.indices.find((i) => i.name === oldName);
	if (!idx) throw new EditError(`'${oldName}' is not in '${listName}'`);
	const to = String(newName ?? '').trim();
	if (!to) throw new EditError('An index needs a name');
	if (to === oldName) return list;
	// Every list the rename has to be carried into. A material is one
	// material: renaming it in the radionuclide sub-set renames it in the
	// catalogue and the other way about, which is what `materialRenamed` does
	// -- it renames the index of `allMaterial` and moves the element mapping
	// with it. Every other list is only itself.
	const kin = (list.for_contaminants || list.for_nuclides)
		? indexLists(project).filter((l) => l.for_contaminants || l.for_nuclides)
		: [list];
	const kinNames = new Set(kin.map((l) => l.name));
	for (const l of kin) {
		if (l !== list && l.indices.some((i) => i.name === to)) {
			throw new EditError(`'${l.name}' already has an index called '${to}'`);
		}
	}
	if (list.indices.some((i) => i.name === to)) {
		throw new EditError(`'${listName}' already has an index called '${to}'`);
	}
	for (const l of kin) {
		const i = (l.indices ?? []).find((x) => x.name === oldName);
		if (i) i.name = to;
	}

	// The name as written in brackets: `K[Lake]` has to become `K[Pond]`, or
	// the build fails with "not an enabled index" the moment the entry keys
	// below have been moved. Under the same rule `retargetBlockIndexes`
	// keeps for a compartment's name: a bracket says which index is meant
	// and not which list, so a name that some *other* list also holds is
	// left alone -- rewriting it would change equations about that list.
	// A list straight out of a file may still spell its indices as bare
	// strings, so both spellings are read.
	const nameOfIndex = (i) => (typeof i === 'string' ? i : i?.name);
	const elsewhere = indexLists(project).some((l) => !kinNames.has(l.name)
		&& (l.indices ?? []).some((i) => nameOfIndex(i) === oldName || nameOfIndex(i) === to));
	if (!elsewhere) {
		forEachEquation(project, (text) => renameWrittenIndex(text, oldName, to));
	}

	// Every value keyed on any of them.
	for (const kind of KINDS) {
		for (const block of project[kind] ?? []) {
			for (const e of block.entries ?? []) {
				if (!e.index) continue;
				for (const n of kinNames) if (e.index[n] === oldName) e.index[n] = to;
			}
		}
	}
	// And every list defined against any of them, in both directions.
	for (const other of project.index_lists ?? []) {
		if (kinNames.has(other.name)) continue;
		if (kinNames.has(other.sub_set_of)) {
			for (const i of other.indices ?? []) if (i.name === oldName) i.name = to;
		}
		if (kinNames.has(other.mapping?.to)) {
			for (const p of other.mapping.pairs ?? []) if (p.to === oldName) p.to = to;
		}
	}
	if (list.mapping) {
		for (const p of list.mapping.pairs ?? []) if (p.from === oldName) p.from = to;
	}
	if (list.for_scenarios && project.scenario === oldName) project.scenario = to;
	if (list.for_contaminants || list.for_nuclides) {
		syncNuclides(project);
		// A nuclide's half-life and its decay pairs are keyed by its name too,
		// and they are the two things a rename used to lose: the override went
		// back to whatever ICRP 107 says for a name that may not be in it at
		// all, and every pair still named the old spelling, so the chain
		// quietly stopped reaching the renamed member.
		if (project.half_lives && oldName in project.half_lives) {
			const hl = project.half_lives[oldName];
			delete project.half_lives[oldName];
			project.half_lives[to] = hl;
		}
		for (const pair of project.chains ?? []) {
			if (pair[0] === oldName) pair[0] = to;
			if (pair[1] === oldName) pair[1] = to;
		}
	}
	return list;
}

export function setIndexEnabled(project, listName, indexName, enabled) {
	assertEditable(project, listName);
	const list = findIndexList(project, listName);
	if (!list) throw new EditError(`No index list named '${listName}'`);
	const idx = list.indices.find((i) => i.name === indexName);
	if (!idx) throw new EditError(`'${indexName}' is not in '${listName}'`);
	idx.enabled = !!enabled;
	// Switched on or off is a property of the material, not of the list it is
	// being looked at in: `indexEnabled` sets it on `allMaterial` and the
	// sub-set follows. Left unpropagated, a nuclide switched off in the
	// catalogue but still on in the sub-set is a model that refuses to load --
	// a sub-set cannot put back an index its root has switched off.
	if (list.for_contaminants || list.for_nuclides) {
		for (const other of indexLists(project)) {
			if (other === list || !(other.for_contaminants || other.for_nuclides)) continue;
			const twin = (other.indices ?? []).find((i) => i.name === indexName);
			if (twin) twin.enabled = !!enabled;
		}
		syncNuclides(project);
	}
}

/** Keeps the `nuclides` shorthand in step with the radionuclide list. */
function syncNuclides(project) {
	const list = indexLists(project).find((l) => l.for_nuclides)
		?? indexLists(project).find((l) => l.for_contaminants);
	if (!list) { delete project.nuclides; return; }
	project.nuclides = list.indices.filter((i) => i.enabled !== false).map((i) => i.name);
}

/**
 * Sets which index lists a block is indexed by.
 *
 * @param followed  an array to collect the names of the connections and
 *   reductions whose own dimensions had to follow, for a caller that wants to
 *   say so.
 */
export function setBlockDimensions(project, blockName, dims, { followed = null } = {}) {
	const found = findBlock(project, blockName);
	if (!found) throw new EditError(`No block named '${blockName}'`);
	for (const d of dims) {
		const list = findIndexList(project, d);
		if (!list) {
			throw new EditError(`No index list named '${d}'`);
		}
		if (!listApplies(list, found.kind)) {
			throw new EditError(listAppliesWhy(list, found.kind));
		}
	}
	const clash = dimensionsClash(project, dims);
	if (clash) throw new EditError(clashingDimensionsWhy(clash));
	// A far-field path may be indexed by whatever a compartment may be -- a
	// path per landscape object is what these models are made of -- with one
	// exception `Project` holds too: the decay chain runs along exactly one
	// dimension, so two radionuclide dimensions on one path are two chains
	// along one fracture. The editor used to refuse everything but the
	// radionuclides alone, on a rule `Project` had already relaxed, so it
	// could not build a model the loader accepted.
	if (found.kind === 'farfield' || found.kind === 'waste_package') {
		const lists = indexLists(project);
		const root = lists.find((l) => l.for_contaminants)?.name ?? materialDimensionName(project, lists);
		const decaying = root ? dims.filter((d) => isDecayDim(lists, d, root)) : [];
		if (decaying.length > 1) {
			throw new EditError(
				`${found.kind === 'farfield' ? 'A far-field path runs' : 'Waste packages run'} `
				+ `one decay chain, and '${decaying.join("' and '")}' `
				+ 'are two radionuclide dimensions. Index it by one of them.',
			);
		}
	}
	found.block.index_lists = [...dims];
	// Entries keyed by a dimension the block no longer has would be rejected
	// by validation, so drop them here rather than fail later.
	if (found.block.entries) {
		found.block.entries = found.block.entries.filter(
			(e) => Object.keys(e.index ?? {}).every((k) => dims.includes(k)),
		);
	}
	// A connection has to be able to reach both of its endpoints, so changing
	// a compartment's dimensions changes theirs too.
	const moved = found.kind === 'compartment'
		? syncConnectionDims(project, blockName)
		: [];
	// The two ends of a transport chain are one compartment repeated, and an
	// operation over the chain has a value wherever the chain has one, so
	// all of them follow whichever end was changed.
	// `TransportBegin.setIndexLists` does the same to End and the operations.
	moved.push(...syncTransportDims(project, found.block, dims));
	// And a reduction is its target's shape with one dimension gone, so it
	// follows the target's dimensions the same way.
	moved.push(...syncReductionDims(project, blockName));
	// Collected for the caller rather than returned, because the block is what
	// this returns and always has been. A caller that runs the syncs again to
	// find out gets nothing back: they have already been done here, which is
	// why the panel's "these followed" message never appeared.
	if (followed) followed.push(...moved);
	return found.block;
}

/**
 * Gives the other parts of a transport the dimensions one of its ends was
 * just given. Returns the names of what followed.
 */
function syncTransportDims(project, block, dims) {
	const role = tr.roleOf(block);
	if (role !== 'begin' && role !== 'end') return [];
	const path = tr.transportOf(project, block);
	if (!path) return [];
	const parts = tr.transportParts(project, path);
	const followed = [];
	for (const other of [parts.begin, parts.end, ...parts.operations]) {
		if (!other || other === block) continue;
		const had = [...(other.index_lists ?? [])].sort().join(' ');
		if (had === [...dims].sort().join(' ')) continue;
		other.index_lists = [...dims];
		if (other.entries) {
			other.entries = other.entries.filter(
				(e) => Object.keys(e.index ?? {}).every((k) => dims.includes(k)),
			);
		}
		const name = qualifiedName(other);
		followed.push(name);
		if (tr.roleOf(other) !== 'operation') followed.push(...syncConnectionDims(project, name));
	}
	return followed;
}

/**
 * Re-derives the dimensions of every connection touching a compartment.
 *
 * A flux is indexed by the indices its two ends have in common -- see
 * `sharedDims` -- so changing a compartment changes every transfer attached to
 * it, and leaving one behind on a dimension neither end has is a build error
 * about a block the user never touched.
 *
 * Where the ends do not correspond at all, which Ecolego refuses outright,
 * there is no intersection to take and the flux falls back to the **union** of
 * the two: fewer than that and it cannot say which cell of the endpoint it
 * moves. The union reaches both ends by adding its cells up at whichever end
 * is the narrower, which is a real thing to want and is the one shape this
 * tool allows where the desktop tool refuses -- but only where the flux says
 * `sum_extra_indices`. See `summedFluxDims`.
 */
export function syncConnectionDims(project, compartmentName = null) {
	const dimsOf = (name) => {
		if (name == null) return [];
		const f = findBlock(project, name);
		return f ? effectiveDims(project, f.block) : [];
	};
	const wanted = (block) => {
		const shared = transferDims(project, block);
		if (shared) return shared.dims;
		const union = [];
		for (const d of [...dimsOf(block.from), ...dimsOf(block.to)]) {
			if (!union.includes(d)) union.push(d);
		}
		return union;
	};

	const touched = [];

	for (const t of project.transfers ?? []) {
		if (compartmentName != null
			&& t.from !== compartmentName && t.to !== compartmentName) continue;
		// A narrower dimension the model states is the modeller's, not a stale
		// one: a flux over some of what its ends share stays as written. Same
		// rule as `syncTransferDimensions`, which does this after every edit.
		const want = wanted(t);
		if (narrows(project, t.index_lists ?? [], want)) continue;
		if (!sameList(t.index_lists ?? [], want)) {
			t.index_lists = want;
			pruneEntriesToDims(t, want);
			touched.push(t.name);
		}
	}

	for (const src of project.inflows ?? []) {
		if (compartmentName != null && src.to !== compartmentName) continue;
		const want = wanted(src);
		if (narrows(project, src.index_lists ?? [], want)) continue;
		if (!sameList(src.index_lists ?? [], want)) {
			src.index_lists = want;
			pruneEntriesToDims(src, want);
			touched.push(src.name);
		}
	}

	return touched;
}

const sameList = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);

function pruneEntriesToDims(block, dims) {
	if (!block.entries) return;
	block.entries = block.entries.filter(
		(e) => Object.keys(e.index ?? {}).every((k) => dims.includes(k)),
	);
}

// --- per-index entries ------------------------------------------------------

/** The value key each kind of block stores per index combination. */
export const ENTRY_KEY = {
	compartment: 'initial',
	transfer: 'rate',
	expression: 'equation',
	parameter: 'value',
	inflow: 'rate',
	lookup: 'points',
	index_reduction: 'target',
	block_reduction: 'targets',
	// A function has no values per index -- it is called, not read at one --
	// but its body is the field the panels edit, and this is the table they
	// ask. `setIndexes` finds no entries for one, so no grid is ever built.
	function: 'equation',
	// A path has no single value. What the per-index grid edits is the four
	// settings that belong to the *nuclide* rather than to the path -- the
	// chemistry -- and `kd_f` is the first of them, in the order the panel
	// shows them. The path's own settings hold one value and are not in the
	// grid at all.
	farfield: 'kd_f',
	// Waste packages: what they hold is the value, per nuclide.
	waste_package: 'inventory',
	// A disruptive event has no value per index; its time is the field the
	// panel edits first.
	event: 'at',
};

/**
 * Per-index properties that are not the block's value.
 *
 * `ENTRY_KEY` is what a block *is* at an index -- an initial inventory, a rate,
 * an equation -- and it is one thing per kind, with one exception that earns
 * its place: a compartment's own absolute error tolerance, held beside the
 * initial condition so that a tolerance can be set for one nuclide of one
 * compartment.
 *
 * Blank at every level means the simulation's own absolute tolerance, which is
 * what `fallback` is for: a per-index box shows the value that would be used
 * if it stays empty, rather than an empty box that says nothing.
 */
export const ENTRY_EXTRA = {
	// A parameter's distribution, per index for the same reason its value is:
	// a sorption coefficient has one per nuclide per material, and
	// model B carries 615 of them. Not a number, so the cell is a
	// button on to the editor -- see ../ui/pdfeditor.js -- and what it shows is
	// `describePDF`.
	parameter: [{
		key: 'pdf',
		pdf: true,
		label: 'distribution',
		// Not a number or a flag, so anything listing what an entry carries has
		// to be told how to say it -- without this the Information view read
		// `distribution [object Object]`, which is what `String(spec)` gives.
		describe: describePDF,
		title: 'The distribution this value was drawn from, one per entry, kept '
			+ 'with the model. A run here is deterministic and uses the value '
			+ 'beside it.',
	}],
	compartment: [{
		// The extra term in this index's rate of change: an equation rather
		// than a number, so the
		// box takes one and checks it as one -- see `equation` in the panel.
		key: 'dydt',
		equation: true,
		label: 'dy/dt',
		title: 'An extra term in the rate of change of this index, added to what its '
			+ 'transfers and decay give. Blank uses the compartment’s own; may read '
			+ 'anything, this compartment included.',
	}, {
		key: 'abstol',
		label: 'abs. tol.',
		title: 'Absolute error tolerance for this index. Blank uses the '
			+ "compartment's, then the simulation's.",
		fallback: (project) => project?.simulation?.abstol,
	}, {
		// The floor is applied per state, and one nuclide of one compartment
		// is one state -- so it can be let go of in one cell and nowhere else.
		// A daughter that dips below zero while its parent is being integrated
		// hard is exactly that case: pinning it hides what the model is doing,
		// and pinning the whole compartment hides more than that.
		key: 'non_negative',
		flag: true,
		label: 'floor',
		title: 'Whether this index cannot go below zero. Blank follows the '
			+ "compartment's own setting.",
		on: 'cannot go negative',
		off: 'may go negative',
	}],
	// A far-field path: the chemistry, which is a property of the nuclide and
	// so may differ from one to the next. Sorption on the fracture coating and
	// in the matrix, diffusion through the pore water, and the porosity the
	// species sees.
	farfield: FARF_NUCLIDE_KEYS.slice(1).map((key) => ({
		key,
		label: FARF_LABEL[key],
		title: FARF_HELP[key],
	})),
	// Waste packages: the instant-release fraction is a property of the
	// nuclide -- what is in the gap, not bound in the matrix -- and the
	// degradation rate the waste form's, which differs by waste type; so both
	// may differ from one index to the next. See WASTE_NUCLIDE_KEYS.
	waste_package: WASTE_NUCLIDE_KEYS.slice(1).map((key) => ({
		key,
		label: WASTE_LABEL[key],
		title: WASTE_HELP[key],
	})),
};

/** The value keys a kind's per-index grid edits, the block's value first. */
export function entryKeys(kind) {
	return [ENTRY_KEY[kind], ...(ENTRY_EXTRA[kind] ?? []).map((x) => x.key)]
		.filter(Boolean);
}

/**
 * Every index combination that carries something of its own.
 *
 * Counted across all of a kind's per-index keys, not just the block's value:
 * a compartment with a tolerance set for one nuclide and no initial value
 * there has one combination set, and a count that said none would be wrong in
 * the badge, in the grid and in the list of what to show.
 */
export function setIndexes(block, kind) {
	const keys = entryKeys(kind);
	return (block?.entries ?? [])
		.filter((e) => keys.some((k) => Object.prototype.hasOwnProperty.call(e, k)))
		.map((e) => e.index ?? {});
}

/** Enabled index names for each of a block's dimensions, in declared order. */
export function dimensionIndices(project, dims) {
	return (dims ?? []).map((name) => {
		const list = findIndexList(project, name);
		// A file written with the `nuclides: [...]` shorthand names a
		// dimension that is not an index list yet -- Project desugars it on
		// load and the editor materialises it on open, but a project object
		// straight off disk still spells it the old way, and reading that as a
		// dimension of no indices would make every per-nuclide block look
		// scalar. See materialDimensionName, which returns this name for it.
		if (!list) return name === NUCLIDE_LIST ? [...(project.nuclides ?? [])] : [];
		return list.indices.filter((i) => i.enabled !== false).map((i) => i.name);
	});
}

/**
 * Every index combination of a block, as { listName: indexName } objects, in
 * row-major order -- the same order the builder lays out its values.
 */
export function indexCombinations(project, dims) {
	const per = dimensionIndices(project, dims);
	if (!per.length) return [];
	let rows = [{}];
	dims.forEach((name, d) => {
		const next = [];
		for (const row of rows) {
			for (const idx of per[d]) next.push({ ...row, [name]: idx });
		}
		rows = next;
	});
	return rows;
}

export function combinationCount(project, dims) {
	return dimensionIndices(project, dims).reduce((n, l) => n * l.length, 1);
}

/**
 * How many state variables the model has: the length of the vector the solver
 * integrates.
 *
 * One per compartment per index combination, plus one per running mean -- a
 * running mean is `dS/dt = target`, and the builder puts its states in the
 * same vector after the compartments, which is what makes it a state block.
 * Nothing else is integrated: a delay keeps a
 * history buffer, and every other block is algebraic.
 *
 * The builder works the same number out again while laying out that vector
 * (`stateLayout` in ../sim/builder.js). This is it from the raw project, so a
 * panel can say how big a model is without building it -- and a test holds the
 * two to the same answer over every example.
 */
export function stateCount(project) {
	let n = 0;
	for (const collection of ['compartments', 'running_means']) {
		for (const block of project[collection] ?? []) {
			n += combinationCount(project, effectiveDims(project, block));
		}
	}
	// A far-field path carries one inventory per cell as well: a whole
	// transport model behind one block, and usually most of the state vector.
	for (const block of project.farfields ?? []) {
		n += cellCount(block) * combinationCount(project, effectiveDims(project, block));
	}
	// Waste packages hold two inventories per index: intact and exposed.
	for (const block of project.waste_packages ?? []) {
		n += 2 * combinationCount(project, effectiveDims(project, block));
	}
	// A disruptive event counts its occurrences in a state of its own.
	n += (project.events ?? []).length;
	// The mass-balance audit appends six budgets per family -- one family per
	// radionuclide and one for what is not indexed by any. See
	// ./massbalance.js and the builder.
	if (project.simulation?.mass_balance) {
		const list = materialDimensionName(project);
		n += 6 * ((list ? combinationCount(project, [list]) : 0) + 1);
	}
	return n;
}

const sameIndex = (a, b) => {
	const ka = Object.keys(a ?? {});
	const kb = Object.keys(b ?? {});
	if (ka.length !== kb.length) return false;
	return ka.every((k) => a[k] === b[k]);
};

/** The entry whose key is exactly `index`, or null. */
export function findEntry(block, index) {
	return (block.entries ?? []).find((e) => sameIndex(e.index, index)) ?? null;
}

/**
 * The value that applies at an index combination: the most specific entry that
 * matches, falling back to the block-level default. Mirrors valueAt() in
 * project.js, but works on the raw (un-normalised) block the editor holds.
 */
export function effectiveValue(block, key, index) {
	let best;
	let bestScore = -1;
	for (const entry of block.entries ?? []) {
		if (!Object.prototype.hasOwnProperty.call(entry, key)) continue;
		let score = 0;
		let ok = true;
		for (const [list, name] of Object.entries(entry.index ?? {})) {
			if (index[list] !== name) { ok = false; break; }
			score++;
		}
		if (ok && score > bestScore) { bestScore = score; best = entry[key]; }
	}
	return bestScore >= 0 ? best : block[key];
}

/** True when this exact combination carries its own value. */
export function isOverridden(block, key, index) {
	const e = findEntry(block, index);
	return !!e && Object.prototype.hasOwnProperty.call(e, key);
}

/** Sets the value for one index combination, creating the entry if needed. */
export function setEntryValue(project, blockName, index, key, value) {
	const found = findBlock(project, blockName);
	if (!found) throw new EditError(`No block named '${blockName}'`);
	const block = found.block;

	for (const list of Object.keys(index)) {
		if (!(block.index_lists ?? []).includes(list)) {
			throw new EditError(`'${blockName}' is not indexed by '${list}'`);
		}
	}

	if (!Array.isArray(block.entries)) block.entries = [];
	let entry = findEntry(block, index);
	if (!entry) {
		entry = { index: { ...index } };
		block.entries.push(entry);
	}
	entry[key] = value;
	return entry;
}

/**
 * Removes the override at one index combination, so the block default applies
 * again. Drops the entry entirely once it carries nothing.
 */
export function clearEntryValue(project, blockName, index, key) {
	const found = findBlock(project, blockName);
	if (!found) throw new EditError(`No block named '${blockName}'`);
	const block = found.block;
	const entry = findEntry(block, index);
	if (!entry) return;
	delete entry[key];
	const remaining = Object.keys(entry).filter((k) => k !== 'index');
	if (!remaining.length) {
		block.entries.splice(block.entries.indexOf(entry), 1);
	}
}

/** Every override a block carries for `key`, with its index. */
export function overrides(block, key) {
	return (block.entries ?? [])
		.filter((e) => Object.prototype.hasOwnProperty.call(e, key))
		.map((e) => ({ index: e.index ?? {}, value: e[key] }));
}

/**
 * Re-attaches one end of a connection.
 *
 * @param end     'from' or 'to'
 * @param target  a compartment name, or null for outside the model
 */
export function setConnectionEnd(project, name, end, target) {
	const found = findBlock(project, name);
	if (!found) throw new EditError(`No connection named '${name}'`);
	const conn = found.block;
	target = transportEndpoint(project, target, end);

	if (found.kind === 'inflow') {
		if (end === 'from') {
			throw new EditError('A source always comes from outside the model');
		}
		if (target == null) throw new EditError('A source needs a target compartment');
		const problem = endpointProblem(project, target, 'to');
		if (problem) throw new EditError(problem);
		conn.to = target;
		rehome(project, conn);
		return conn;
	}

	if (found.kind !== 'transfer') {
		throw new EditError(`'${name}' is not a connection`);
	}

	if (target != null) {
		const problem = endpointProblem(project, target, end);
		if (problem) throw new EditError(problem);
	}

	const other = end === 'from' ? conn.to : conn.from;
	if (target != null && target === other) {
		throw new EditError('A transfer cannot start and end at the same compartment');
	}
	if (target == null && other == null) {
		throw new EditError('A transfer needs a compartment at one end at least');
	}
	// Moving a donor end onto a path is the other way a second release gets
	// drawn. The line being moved does not count against the rule: pointing
	// the one release at somewhere else is the edit this is for.
	if (end === 'from' && target != null
		&& RELEASING.has(findBlock(project, target)?.kind)) {
		const taken = releaseTaken(project, target, { allow: name });
		if (taken) throw new EditError(taken);
	}

	conn[end] = target;
	// An absolute flux has no donor to multiply by.
	if (conn.from == null) conn.multiply_by_donor = false;
	// Moving the donor end onto a path makes it a release: the rate becomes
	// the path itself, and there is no inventory to multiply by. Moving it off
	// one again leaves the path's name standing as an ordinary equation, which
	// is still the release and still means something -- so it is left alone
	// rather than reset to zero behind the modeller's back.
	if (isReleaseTransfer(project, conn)) {
		conn.rate = conn.from;
		conn.multiply_by_donor = false;
	}
	// Re-attaching the donor end moves the transfer: it is written from inside
	// whichever sub-system it now flows out of.
	rehome(project, conn);
	return conn;
}

/** Moves a connection to the sub-system its endpoints now put it in. */
function rehome(project, conn) {
	const home = connectionHome(conn.from, conn.to);
	if (systemOf(conn) === home) return conn;
	moveBlock(project, qualifiedName(conn), home);
	return conn;
}

// --- sub-systems ------------------------------------------------------------

/**
 * The sub-systems the model is organised into, as dotted paths, shallowest
 * first. See ./systems.js for what a path means.
 */
export function systems(project) {
	return systemPaths(project);
}

/** The blocks of one sub-system: its own, or everything beneath it. */
export function blocksIn(project, system = '', { deep = false } = {}) {
	return allBlocks(project).filter((b) => (deep
		? isWithin(systemOf(b), system)
		: systemOf(b) === system));
}

/** The sub-systems directly inside `system`. */
export function childSystems(project, system = '') {
	return systems(project).filter((p) => parentOf(p) === system);
}

// --- transports -------------------------------------------------------------
// A sub-system that stands for a chain of N compartments, drawn as its first
// and its last. What one is, and how it runs, are in ./transport.js and
// ../sim/transport.js; here is what the editor does to one.

export const TRANSPORT_ROLE_LABEL = tr.ROLE_LABEL;
export const TRANSPORT_ROLE_BLURB = tr.ROLE_BLURB;
export const TRANSPORT_OPERATIONS = tr.OPERATIONS;
export const TRANSPORT_ARGUMENTS = tr.ARGUMENTS;
export const isTransport = tr.isTransport;
export const transportPaths = tr.transportPaths;
export const transportParts = tr.transportParts;
export const transportOf = tr.transportOf;
export const transportRole = tr.roleOf;
export const transportNumber = tr.transportNumber;
export const transportProblems = tr.transportProblems;

/**
 * What a block is called in a panel: its part in a transport, when it is one
 * and its sub-system is a transport, or nothing.
 */
export function roleLabel(project, block) {
	return tr.transportOf(project, block) ? tr.ROLE_LABEL[tr.roleOf(block)] : null;
}

/**
 * Whether a block's equation is the run's to write rather than the user's: a
 * transport's counter, and its operations. Nothing checks what is in the box.
 */
function writtenByTheRun(block) {
	return ['counter', 'operation'].includes(tr.roleOf(block));
}

/**
 * Refuses to delete the parts a transport is made of while it is still a
 * transport, unless the whole of it is going. `going` is every name about to
 * go. Dissolving the transport first makes them ordinary blocks.
 */
function guardTransportParts(project, going) {
	for (const name of going) {
		const found = findBlock(project, name);
		if (!found) continue;
		const role = tr.roleOf(found.block);
		if (!['begin', 'end', 'number'].includes(role)) continue;
		const path = tr.transportOf(project, found.block);
		if (!path) continue;
		const whole = blocksIn(project, path).every((b) => going.has(qualifiedName(b)));
		if (whole) continue;
		throw new EditError(
			`'${found.block.name}' is the ${tr.ROLE_LABEL[role].toLowerCase()} of '${path}', `
			+ `and a transport is a chain from its Begin to its End. Delete the transport `
			+ 'instead, with everything in it.',
		);
	}
}

/**
 * Makes a transport: a sub-system, and the four blocks Ecolego's
 * `CreateTransportSubSystemAction` puts in it -- Begin, End, N and the element
 * counter, under the default names the block factory gives them. The two
 * compartments are indexed as a new compartment would be; N and the counter
 * are counts and take no dimension.
 *
 * @returns {string} the path of the new sub-system.
 */
export function addTransport(project, { name, parent = '', at } = {}) {
	const path = addSystem(project, { name: name ?? 'Transport', parent });
	if (!Array.isArray(project.transports)) project.transports = tr.transportPaths(project);
	project.transports.push(path);
	if (at) setPosition(project, path, at);

	const begin = addCompartment(project, {
		name: uniqueName(project, 'Begin', path), system: path, at: { x: 80, y: 90 },
	});
	begin.transport = 'begin';
	const end = addCompartment(project, {
		name: uniqueName(project, 'End', path), system: path, at: { x: 420, y: 90 },
	});
	end.transport = 'end';
	const number = addExpression(project, {
		name: uniqueName(project, 'N', path), equation: '5', system: path,
	});
	number.transport = 'number';
	number.index_lists = [];
	setPosition(project, qualify(path, number.name), { x: 80, y: 210 });
	const counter = addExpression(project, {
		name: uniqueName(project, 'i', path), equation: '1', system: path,
	});
	counter.transport = 'counter';
	counter.index_lists = [];
	setPosition(project, qualify(path, counter.name), { x: 420, y: 210 });
	return path;
}

/**
 * Adds an operation over a transport's chain: the sum or the mean of its
 * compartments, read as a value or called with a position (or two) along it.
 * Indexed as Begin is, and in Begin's unit, which is what
 * a transport operation's unit rule answers.
 */
export function addTransportOperation(project, {
	name, system, operation = 'mean', argument = 'all', at,
} = {}) {
	if (!tr.isTransport(project, system)) {
		throw new EditError(
			`'${system || 'The top level'}' is not a transport, so an operation over its `
			+ 'chain has nothing to work on.',
		);
	}
	if (!tr.OPERATIONS.includes(operation)) {
		throw new EditError(`'${operation}' is not a transport operation (${tr.OPERATIONS.join(', ')})`);
	}
	if (!tr.ARGUMENTS.includes(argument)) {
		throw new EditError(`'${argument}' is not a way of reading one (${tr.ARGUMENTS.join(', ')})`);
	}
	const parts = tr.transportParts(project, system);
	const n = name ?? uniqueName(project, 'TransportOp', system);
	const block = placed({
		name: n, equation: '0', unit: parts.begin?.unit ?? '',
		index_lists: [...(parts.begin?.index_lists ?? [])],
		transport: 'operation', operation, argument,
	}, system);
	ensure(project, 'expressions').push(block);
	if (at) setPosition(project, qualify(system, n), at);
	return block;
}

/**
 * The rows and columns of the transfer grid, in order, with the sub-systems
 * folded or unfolded.
 *
 * The grid is square -- row i and column i are the same thing -- and the
 * blocks are on its diagonal, so a sub-system has to be a *contiguous run* of
 * slots or it cannot be drawn as a group at all. That is what this arranges: a
 * system's own blocks, then each of its children, depth first, so everything
 * inside a sub-system sits together on both axes.
 *
 * A **closed** sub-system is one slot. Everything inside it is represented by
 * it, so a flux from a block outside into any block within lands on that one
 * row or column, and the several that may then share a cell stack in it the
 * way parallel transfers always have. What is left over is the transfers
 * *between* two blocks inside it: those have nowhere to go on a grid that no
 * longer has rows for either end, so they are counted rather than dropped --
 * `inside` on the slot -- and the cell says how many.
 *
 * An **open** one gets a slot of its own as well as its members: a header,
 * which nothing can flow into or out of, and which is what gives the group a
 * corner to put its name and its close button in. A frame is then the square
 * from the header to the last member, which is what `frames` describes.
 *
 * @param open a Set of sub-system paths that are open; everything else is
 *   closed. The root is not a sub-system and is always unfolded.
 * @returns {{slots: object[], frames: object[], index: Map}}
 */
export function matrixPlan(project, open = new Set()) {
	const paths = new Set(systems(project));
	const isPath = new Set([...(project.farfields ?? []), ...(project.waste_packages ?? [])]
		.map((f) => qualifiedName(f)));
	const ownBlocks = (system) => [
		...(project.compartments ?? []),
		...(project.farfields ?? []),
		...(project.waste_packages ?? []),
	].filter((b) => systemOf(b) === system).map((b) => qualifiedName(b));

	const slots = [];
	const frames = [];
	const walk = (system, depth) => {
		for (const name of ownBlocks(system)) {
			slots.push({
				kind: 'block', name, local: baseName(name), isPath: isPath.has(name), depth,
			});
		}
		for (const child of childSystems(project, system)) {
			if (open.has(child)) {
				const from = slots.length;
				slots.push({ kind: 'head', path: child, local: baseName(child), depth });
				walk(child, depth + 1);
				frames.push({ path: child, from, to: slots.length - 1, depth });
			} else {
				slots.push({
					kind: 'group', path: child, local: baseName(child), depth,
					// What it holds, for the badge on its cell. Only what
					// would appear on this grid -- the compartments and the
					// far-field paths -- because that is what "open it and
					// you will see" means here. A count of every block kind
					// inside said 137 for a sub-system that contributes five
					// rows, which answers a question nobody asked.
					blocks: [
						...(project.compartments ?? []),
						...(project.farfields ?? []),
					].filter((b) => isWithin(systemOf(b), child)).length,
					systems: [...paths].filter((p) => p !== child && isWithin(p, child)).length,
				});
			}
		}
	};
	walk('', 0);
	// The world beyond the model, last: it is not part of any sub-system, and
	// it is on the grid only when something actually crosses that boundary. A
	// row and a column standing empty in every model that has no source term
	// and no outflow is furniture -- and on the diagram the same fluxes are
	// drawn where their block is rather than at the top level, so this is the
	// one view that gathers them, which is worth doing only when there are any.
	const crosses = (project.inflows ?? []).length > 0
		|| (project.transfers ?? []).some((t) => t.from == null || t.to == null);
	if (crosses) slots.push({ kind: 'outside', depth: 0 });

	// What each slot stands for, when anything asks which flux belongs where.
	// A header stands for nothing: it is a label.
	const idOf = (slot) => (slot.kind === 'block' ? slot.name
		: slot.kind === 'group' ? slot.path
			: slot.kind === 'outside' ? null : undefined);
	const index = new Map();
	slots.forEach((slot, at) => {
		const id = idOf(slot);
		if (id !== undefined) index.set(id, at);
	});

	/**
	 * Which slot a block's flux lands on: the outermost *closed* sub-system it
	 * is inside, or the block itself when every ancestor is open. Null stays
	 * null -- outside the model is outside the model.
	 */
	const representative = (name) => {
		if (name == null) return null;
		const owner = parentOf(name);
		if (!owner) return name;
		const p = parts(owner);
		for (let i = 1; i <= p.length; i++) {
			const path = p.slice(0, i).join('.');
			if (paths.has(path) && !open.has(path)) return path;
		}
		return name;
	};

	return { slots, frames, index, representative };
}

/**
 * Rewrites every reference in the model when names move in bulk -- a
 * sub-system renamed, or a block moved into one.
 *
 * `newNameOf` maps an old qualified name to its new one; `newSystemOf(system,
 * block)` gives the sub-system an equation will be *written in* once the move
 * is done, which decides whether a reference can stay local or has to become a
 * path. Both are applied against the old world, so this must run before the
 * blocks themselves are moved.
 *
 * A reference is re-written when the name it points at moves **or** when the
 * equation holding it does. The second half is easy to miss and silent when it
 * goes wrong: an expression inside `NearField` reading `Water` means
 * `NearField.Water`, and moving that expression to the top level without
 * touching its text leaves it reading a different block of the same name --
 * the wrong answer, with nothing to say so.
 */
function retargetAll(project, newNameOf, newSystemOf, alsoKnown = null) {
	// `alsoKnown` are names that will exist when this edit is done but do not
	// yet -- the new spellings of blocks that are moving. Without them
	// `referenceFrom` cannot tell that a local reference still finds its
	// block, and writes the full path instead of leaving the text alone.
	const here = knownNames(project);
	const known = alsoKnown ? (n) => here(n) || alsoKnown.has(n) : here;

	refuseShadowed(project, known, (q, system, block) => {
		const to = newNameOf(q) ?? q;
		const where = newSystemOf(system, block);
		return to === q && where === system ? null : { to, where };
	});

	for (const conn of [...(project.transfers ?? []), ...(project.inflows ?? [])]) {
		for (const end of ['from', 'to']) {
			if (conn[end] == null) continue;
			conn[end] = newNameOf(conn[end]) ?? conn[end];
		}
	}
	forEachEquation(project, (text, system, block) => rewriteEquation(
		text, system, known,
		(q) => {
			const to = newNameOf(q) ?? q;
			const where = newSystemOf(system, block);
			// Nothing moved on either side: leave the text exactly as the
			// user wrote it. Re-emitting every reference in the model on every
			// rename would reformat equations nobody touched.
			if (to === q && where === system) return null;
			return referenceFrom(to, where, known);
		},
	));
	// A reduction names the blocks it reduces instead of writing an equation,
	// so those names are references too -- and this walker is the reason they
	// have to be re-written here as well. `retargetReferences` and
	// `pasteBlocks` have always done it; this, the third caller of the same
	// idea, did not, and the result was silent: moving an aggregate between
	// sub-systems left its target reading the *other* sub-system's block of
	// that name, and the model went on building and running with a different
	// number in it.
	forEachTarget(project, (ref, system, block) => {
		const q = resolveReference(ref, system, known);
		if (!q) return ref;
		const to = newNameOf(q) ?? q;
		const where = newSystemOf(system, block);
		if (to === q && where === system) return ref;
		return referenceFrom(to, where, known);
	});
	// A compartment's and a transfer's *qualified* name is an index of the
	// dimension made of them, so a move or a sub-system rename renames indices
	// too -- and everything keyed by one has to follow. `renameBlock` has
	// always done this for the one name it changes; the bulk edits did not,
	// and the loss was silent: a per-compartment parameter carrying a value
	// for `NearField.Water` kept it under that key after the sub-system was
	// renamed, so the value stopped being found and the block default applied
	// instead, with a different number and nothing to say so.
	const moves = new Map();
	for (const [collection, listName] of
		[['compartments', COMPARTMENT_LIST], ['transfers', TRANSFER_LIST]]) {
		const m = new Map();
		for (const b of project[collection] ?? []) {
			const was = qualifiedName(b);
			const to = newNameOf(was);
			if (to && to !== was) m.set(was, to);
		}
		if (m.size) moves.set(listName, m);
	}
	retargetBlockIndexes(project, moves);
}

/**
 * Moves diagram positions and connection bends to follow renamed blocks.
 *
 * `canvasOf` says where a canvas went, for a pipe's key (`edge:<name>@<canvas>`,
 * see `waypointKey`): a sub-system that is renamed or moved takes its canvas,
 * and the pipes drawn on it, along. Without it a canvas is taken to be a block
 * name like any other, which a sub-system path never is.
 */
function retargetLayoutAll(project, newNameOf, canvasOf = null) {
	if (!project.layout) return;
	// Prototype-free like everything `layoutOf` hands out: rebuilt as `{}`,
	// this quietly undid that guarantee after every move.
	const next = Object.create(null);
	for (const [key, value] of Object.entries(project.layout)) {
		const edge = parseEdgeKey(key);
		if (edge) {
			// The connection's name, and the canvas a pipe is on, which is a
			// sub-system path and moves with a renamed or moved sub-system.
			const view = edge.view == null || edge.view === '' ? edge.view
				: canvasOf ? canvasOf(edge.view) : (newNameOf(edge.view) ?? edge.view);
			next[waypointKey(newNameOf(edge.name) ?? edge.name, view)] = value;
			continue;
		}
		next[newNameOf(key) ?? key] = value;
	}
	project.layout = next;
}

/**
 * The name a new sub-system of `parent` would be given: `Sub`, then `Sub1`.
 *
 * Separate from `addSystem` because a menu offering to create one wants to
 * show the name first, and the offer and the act must not disagree.
 */
export function nextSystemName(project, parent = '', base = 'Sub', allow = null) {
	// Blocks too: one namespace for both. See `idTaken`.
	const existing = new Set([...systems(project), ...blockNames(project)]);
	// Except the block that is about to vacate the name -- `addSystem`'s
	// `allow`. Without this, making a sub-system called after the block going
	// into it numbered past that very block and named it `Soil1`.
	if (allow) existing.delete(allow);
	let local = base;
	for (let i = 1; existing.has(qualify(parent, local)); i++) local = `${base}${i}`;
	return local;
}

/**
 * Creates a sub-system.
 *
 * It exists as soon as it is declared, before anything is in it: an empty
 * sub-system is where the next block goes, and has to survive a save.
 */
export function addSystem(project, { name, parent = '', allow = null } = {}) {
	if (parent && !systems(project).includes(parent)) {
		throw new EditError(`No sub-system named '${parent}'`);
	}
	// A transport holds the compartments of its chain and nothing else, which
	// is what the rule for what may be moved where says of moving a sub-system into one.
	if (parent && tr.isTransport(project, parent)) {
		throw new EditError(
			`'${parent}' is a transport, which is a chain of compartments and holds no `
			+ 'sub-system of its own.',
		);
	}
	if (name != null && !isValidPath(name)) {
		throw new EditError(
			`'${name}' is not a valid name (letters, digits and underscore; must not `
			+ `start with a digit)`,
		);
	}
	// A block of that name is in the way: the two share one namespace, and
	// unlike a sub-system's name -- which `nextSystemName` numbers past -- a
	// block's cannot be side-stepped without picking a name nobody asked for.
	// `allow` is the one exception: the block that is about to move into it
	// and vacate the name, which is how a sub-system comes to be called after
	// the block it holds. See `moveIntoNewSystem`. A name nobody asked for
	// (`name` left out) is numbered past blocks and sub-systems alike.
	if (name != null && nameTaken(project, qualify(parent, name)) && qualify(parent, name) !== allow) {
		throw new EditError(
			`'${name}' is already used by a block in `
			+ `${parent ? `'${parent}'` : 'this model'}. A sub-system and a block cannot `
			+ 'share a name.',
		);
	}
	const path = qualify(parent, nextSystemName(project, parent, name ?? undefined, allow));

	if (!Array.isArray(project.systems)) project.systems = systems(project);
	project.systems.push(path);
	return path;
}

/** Renames a sub-system, and every name inside it, following the references. */
export function renameSystem(project, path, newName) {
	if (!path) throw new EditError('The model itself has no name to change');
	if (!systems(project).includes(path)) {
		throw new EditError(`No sub-system named '${path}'`);
	}
	if (baseName(newName) !== newName || !isValidPath(newName)) {
		throw new EditError(
			`'${newName}' is not a valid name for a sub-system (letters, digits and `
			+ `underscore; must not start with a digit)`,
		);
	}
	const parent = parentOf(path);
	const target = qualify(parent, newName);
	if (target === path) return path;
	if (systems(project).includes(target)) {
		throw new EditError(`'${newName}' is already a sub-system of `
			+ `${parent ? `'${parent}'` : 'this model'}`);
	}
	// And a block of that name is equally in the way: one namespace for both.
	if (nameTaken(project, target)) {
		throw new EditError(`'${newName}' is already used by a block in `
			+ `${parent ? `'${parent}'` : 'this model'}. A sub-system and a block cannot `
			+ 'share a name.');
	}
	if (RESERVED.has(newName)) {
		throw new EditError(`'${newName}' is a reserved name.`);
	}
	return relocateSystem(project, path, target);
}

/**
 * Moves a sub-system into another one, or out to the top level.
 *
 * A sub-system is not a thing with a place of its own -- it is a path prefix
 * that blocks wear -- so moving one *is* renaming it: every block inside gets a
 * new qualified name, every sub-system nested in it follows, and everything
 * that pointed at any of them is rewritten. That is exactly the edit
 * `renameSystem` makes, so the two share it.
 *
 * Refused when the target is the sub-system itself or something inside it:
 * nothing can contain itself, and the path arithmetic would otherwise produce
 * names that resolve to nothing.
 *
 * A name already used among its new siblings is numbered, as a block's is when
 * it moves -- a drop is a gesture, and refusing one over a name is worse than
 * landing as `NearField1`. Being already there is not refused either, so
 * dropping a selection that partly overlaps its target does the obvious thing
 * with the rest of it.
 *
 * @returns {string} the path it now has.
 */
export function moveSystem(project, path, parent = '') {
	if (!path) throw new EditError('The model itself cannot be moved');
	if (!systems(project).includes(path)) {
		throw new EditError(`No sub-system named '${path}'`);
	}
	if (parent && !systems(project).includes(parent)) {
		throw new EditError(`No sub-system named '${parent}'`);
	}
	if (isWithin(parent, path)) {
		throw new EditError(parent === path
			? `'${baseName(path)}' cannot be moved into itself`
			: `'${baseName(path)}' cannot be moved into '${parent}', which is inside it`);
	}
	if (parent && tr.isTransport(project, parent)) {
		throw new EditError(
			`'${parent}' is a transport, which is a chain of compartments and holds no `
			+ 'sub-system of its own.',
		);
	}
	if (parentOf(path) === parent) return path;

	// A sub-system and a block cannot share an id -- which is what
	// the rule for which blocks a sub-system may hold says too -- so both are in the
	// way of the name it lands under.
	const taken = new Set([...systems(project), ...blockNames(project)]);
	let local = baseName(path);
	for (let i = 1; taken.has(qualify(parent, local)); i++) local = `${baseName(path)}${i}`;
	return relocateSystem(project, path, qualify(parent, local));
}

/**
 * The edit under both renaming and moving a sub-system: every path that starts
 * with `path` becomes one that starts with `target`.
 */
function relocateSystem(project, path, target) {
	// The paths as they are before anything moves. Read afterwards, the list
	// held the old paths the file declares *and* the new ones the moved
	// blocks now imply, and both reparented to the same place: a rename of
	// `Outer` wrote `Top` twice, and a move wrote `Y.X` twice.
	const before = systems(project);
	const moved = new Map();
	for (const b of allBlocks(project)) {
		if (!isWithin(systemOf(b), path)) continue;
		moved.set(qualifiedName(b), qualify(reparent(systemOf(b), path, target), b.name));
	}
	// The rewriter is told the names these blocks are about to wear as well as
	// the ones they wear now. A reference *inside* the sub-system was written
	// local, and has to stay local: knowing only the old names,
	// `referenceFrom` could not find the block it was spelling and fell back
	// to the full path, so renaming a sub-system quietly rewrote every
	// equation in it into a form nobody had typed.
	retargetAll(project, (n) => moved.get(n) ?? null,
		(system) => reparent(system, path, target),
		new Set(moved.values()));
	retargetLayoutAll(project, (n) => moved.get(n) ?? null,
		(canvas) => (isWithin(canvas, path) ? reparent(canvas, path, target) : canvas));

	for (const b of allBlocksLive(project)) {
		if (isWithin(systemOf(b), path)) b.system = reparent(systemOf(b), path, target);
	}
	project.systems = [...new Set(before.map((p) => reparent(p, path, target)))];
	if (tr.transportPaths(project).length) {
		project.transports = tr.transportPaths(project).map((p) => reparent(p, path, target));
	}
	if (disabledSystems(project).length) {
		project.disabled_systems = disabledSystems(project).map((p) => reparent(p, path, target));
	}
	// The sub-system's own node on the diagram moves with it.
	if (project.layout?.[path]) {
		project.layout[target] = project.layout[path];
		delete project.layout[path];
	}
	// So does whatever was drawn on its canvas: a group box round four
	// compartments belongs with them, not with the path they used to wear.
	for (const sh of shapes(project)) {
		if (!isWithin(sh.system ?? '', path)) continue;
		const to = reparent(sh.system ?? '', path, target);
		if (to) sh.system = to;
		else delete sh.system;
	}
	return target;
}

/**
 * Removes a sub-system. Its contents move to the sub-system around it unless
 * `contents: 'delete'` is asked for, because losing a hundred blocks to a
 * mis-click is not a thing an editor should make easy.
 */
export function deleteSystem(project, path, { contents = 'move' } = {}) {
	if (!path) throw new EditError('The model itself cannot be removed');
	if (!systems(project).includes(path)) {
		throw new EditError(`No sub-system named '${path}'`);
	}
	const parent = parentOf(path);
	// Where each sub-system nested inside this one has gone, filled in by the
	// `move` branch and read by the tail. Empty when the contents were
	// deleted, which is what `keep` below reads as "it went with them".
	let systemsOut = null;

	if (contents === 'delete') {
		// One edit for the lot rather than one `deleteBlock` at a time: that
		// checks its block against the whole model, so two blocks inside here
		// that read each other would each be held up by the other though the
		// pair is going together -- which made this refuse to delete most
		// sub-systems worth deleting. What is still reading them from
		// *outside* refuses it, which is the point of checking at all.
		deleteBlocks(project, blocksIn(project, path, { deep: true })
			.map((b) => qualifiedName(b)));
	} else {
		// A transport is not dissolved. Its parts are not blocks that happen
		// to share a sub-system: Begin and End are one compartment repeated N
		// times, the counter is a number the chain supplies, and an operation
		// has no equation of its own. Let loose they are a compartment with a
		// misleading name, an expression that says 1, and a block that comes
		// to nothing -- a model that builds and means something other than it
		// did, with no line saying so. the rule for what may be moved where will not let
		// any of them leave; this is the same rule for the container.
		if (tr.isTransport(project, path)) {
			throw new EditError(
				`'${path}' is a transport, and a transport is a chain from its Begin to `
				+ 'its End rather than a place blocks are kept: its parts cannot be let '
				+ 'out as ordinary blocks. Delete it, with everything in it.',
			);
		}
		// The sub-systems nested inside it come out too, and one whose name is
		// already used among its new siblings is numbered -- as a block's is.
		// Without this, dissolving a `Geo` that held `Geo.Column` merged its
		// blocks into an unrelated `Column` at the top level.
		//
		// Shallowest first, so a deeper one can be hung off whatever its
		// parent has just become rather than working the path out twice.
		systemsOut = new Map();
		const takenSystems = new Set(systems(project).filter((p) => !isWithin(p, path)));
		const nested = systems(project)
			.filter((p) => isWithin(p, path) && p !== path)
			.sort((a, b) => parts(a).length - parts(b).length);
		for (const p of nested) {
			const from = parentOf(p);
			const home = from === path ? parent : (systemsOut.get(from) ?? from);
			let local = baseName(p);
			for (let i = 1; takenSystems.has(qualify(home, local)); i++) local = `${baseName(p)}${i}`;
			const to = qualify(home, local);
			takenSystems.add(to);
			systemsOut.set(p, to);
		}
		const homeOf = (system) => (system === path ? parent
			: systemsOut.get(system) ?? reparent(system, path, parent));

		// Names that would collide once the wrapper is gone are numbered.
		const moved = new Map();
		const taken = new Set(blockNames(project));
		for (const b of allBlocks(project)) {
			if (!isWithin(systemOf(b), path)) continue;
			const to = homeOf(systemOf(b));
			let local = b.name;
			for (let i = 1; taken.has(qualify(to, local)); i++) local = `${b.name}${i}`;
			taken.add(qualify(to, local));
			moved.set(qualifiedName(b), qualify(to, local));
		}
		// With the names the blocks are about to wear, as `relocateSystem`
		// does: without them a local reference inside a dissolved nested
		// sub-system was rewritten to its full path.
		retargetAll(project, (n) => moved.get(n) ?? null, homeOf, new Set(moved.values()));
		retargetLayoutAll(project, (n) => moved.get(n) ?? null);
		for (const b of allBlocksLive(project)) {
			const was = qualifiedName(b);
			if (!moved.has(was)) continue;
			const now = moved.get(was);
			b.system = parentOf(now);
			b.name = baseName(now);
			if (!b.system) delete b.system;
		}
		// The node each of them is drawn as, on the canvas it has moved to.
		for (const [was, now] of systemsOut) {
			if (!project.layout?.[was]) continue;
			const layout = layoutOf(project);
			layout[now] = layout[was];
			delete layout[was];
		}
	}

	// The shapes drawn inside it go where its blocks go: out to the
	// sub-system around it, or away with the contents when that is what was
	// asked for. A drawing left behind on a canvas nobody can open is a
	// drawing that only shows up in the file.
	if (contents === 'delete') {
		deleteShapes(project, shapesInDeep(project, path).map((sh) => sh.id));
	} else {
		for (const sh of shapesInDeep(project, path)) {
			const to = reparent(sh.system ?? '', path, parent);
			if (to) sh.system = to;
			else delete sh.system;
		}
	}

	// The wrapper itself goes either way. What was nested in it goes with it
	// when the contents were deleted, and comes out under the name
	// `systemsOut` gave it when they were moved.
	const keep = (p) => (p === path ? null
		: isWithin(p, path) ? (systemsOut?.get(p) ?? null) : p);
	// Once each: a nested path the file declares and the one its moved-out
	// blocks now imply come out under the same name.
	project.systems = [...new Set(systems(project).map(keep).filter(Boolean))];
	// A transport is a sub-system with a role, and the role travels with it.
	// Dropped instead, its Begin and End kept their parts while the chain
	// they stand for did not exist: the model ran as two compartments rather
	// than N, and nothing said so.
	if (disabledSystems(project).length) {
		project.disabled_systems = disabledSystems(project).map(keep).filter(Boolean);
		if (!project.disabled_systems.length) delete project.disabled_systems;
	}
	if (tr.transportPaths(project).length) {
		project.transports = tr.transportPaths(project).map(keep).filter(Boolean);
	}
	if (project.layout) delete project.layout[path];
	return parent;
}

/**
 * Re-homes the connections that belong with a compartment.
 *
 * A transfer lives in its donor's sub-system, so a compartment that moves
 * takes its outgoing transfers with it -- and its source terms, which have no
 * donor and follow their receiver. What flows *into* it stays where it is,
 * with the donors it comes from.
 */
function rehomeConnections(project, name, record = null) {
	const home = parentOf(name);
	const attached = [
		...(project.transfers ?? []).filter((t) => t.from === name),
		...(project.inflows ?? []).filter((s) => s.to === name),
	];
	for (const conn of attached) {
		if (systemOf(conn) === home) continue;
		const was = qualifiedName(conn);
		moveBlock(project, was, home, record);
	}
}

/**
 * Moves one block into another sub-system, renaming it if the name is taken.
 *
 * `record`, when given, collects every move this makes -- the block's own and
 * any connection carried along with it -- keyed by the name each had before.
 */
export function moveBlock(project, name, system = '', record = null) {
	const found = findBlock(project, name);
	if (!found) throw new EditError(`No block named '${name}'`);
	if (system && !systems(project).includes(system)) {
		throw new EditError(`No sub-system named '${system}'`);
	}
	const block = found.block;
	// Already there. Still recorded: the map answers "where is each of the
	// blocks I named now", and the answer for this one is "where it was".
	if (systemOf(block) === system) { record?.set(name, name); return name; }
	// A part of a transport stays in it: the chain is those blocks, and moving
	// one out would leave a transport with no Begin. the rule for what may be moved where
	// refuses the same move for Begin, End, N and the counter; an operation is
	// held too, since it is a sum or a mean over this chain and means nothing
	// beside another. There is no way to make one an ordinary block: a
	// transport is deleted whole or kept whole.
	const home = tr.transportOf(project, block);
	if (home) {
		throw new EditError(
			`'${block.name}' is the ${tr.ROLE_LABEL[tr.roleOf(block)].toLowerCase()} of `
			+ `'${home}' and stays in it.`,
		);
	}
	// A part that has somehow lost its transport -- a copy pasted loose, a
	// block edited by hand -- is a plain block wherever it lands.
	if (tr.roleOf(block)) delete block.transport;

	let local = block.name;
	for (let i = 1; nameTaken(project, qualify(system, local)); i++) local = `${block.name}${i}`;
	const target = qualify(system, local);

	// The moved block's own equations are re-read from where it lands; every
	// other block's stay where they were written. The name it is about to
	// wear is passed as known, so a neighbour in the sub-system it lands in
	// goes on reading it by its bare name rather than its full path.
	retargetAll(project,
		(n) => (n === name ? target : null),
		(s, b) => (b === block ? system : s),
		new Set([target]));
	retargetLayoutAll(project, (n) => (n === name ? target : null));
	block.name = local;
	if (system) block.system = system;
	else delete block.system;
	record?.set(name, target);
	// The connections that belong with it go too, or a transfer would be left
	// in a sub-system its donor has left.
	if (found.kind === 'compartment') rehomeConnections(project, target, record);
	return target;
}

/**
 * Moves several blocks into the same sub-system, as one edit.
 *
 * Not a loop the caller can write for itself: a name that is free when the
 * first block lands may be taken by the time the third does, and each move
 * rewrites the references of the ones still to come. Doing it here means the
 * whole set either arrives or nothing does -- a half-moved selection is a
 * model with references pointing at both worlds.
 *
 * A block already in `system` is left alone rather than being refused, so
 * dropping a selection that partly overlaps its target does the obvious thing.
 *
 * @returns {Map<string, string>} old qualified name -> new one, in the order
 *   they were moved.
 */
export function moveBlocks(project, names, system = '', { snapshot = true } = {}) {
	const wanted = [...new Set(names)];
	if (system && !systems(project).includes(system)) {
		throw new EditError(`No sub-system named '${system}'`);
	}
	for (const name of wanted) {
		if (!findBlock(project, name)) throw new EditError(`No block named '${name}'`);
	}

	// Checked, then done: a set that cannot all move must not half-move.
	// `snapshot: false` is for a caller that has already taken one --
	// `moveSelection` -- so a drag does not clone a 4,000-block model twice.
	const before = snapshot ? structuredClone(project) : null;
	const moved = new Map();
	try {
		for (const name of wanted) {
			// Already there: a compartment moved earlier in this batch took
			// its outgoing connections with it, and one of them may be a
			// member of the batch too.
			if (moved.has(name)) continue;
			moveBlock(project, name, system, moved);
		}
	} catch (e) {
		if (before) {
			for (const key of Object.keys(project)) delete project[key];
			Object.assign(project, before);
		}
		throw e;
	}
	return moved;
}

/**
 * Moves a selection of blocks and sub-systems into one sub-system, as one edit.
 *
 * The sub-systems go first: a block that lands beside one of them must be
 * numbered against the names it finds there, and those names are not settled
 * until the sub-systems have arrived.
 *
 * @returns {{moved: Map<string, string>, systems: Map<string, string>}} what
 *   each block and each sub-system is called now, keyed by what it was called.
 */
export function moveSelection(project, names, system = '') {
	const { systems: chosen, blocks } = selectionParts(project, names);
	if (system && !systems(project).includes(system)) {
		throw new EditError(`No sub-system named '${system}'`);
	}
	// Checked, then done: a set that cannot all move must not half-move.
	const snapshot = structuredClone(project);
	try {
		const systemsMoved = new Map();
		for (const path of chosen) {
			// The one it is being dropped *into* is left where it is, rather
			// than refusing the whole gesture over it: dropping three
			// sub-systems onto one of the three means the other two move.
			// Something *inside* one of them is still refused -- nothing can
			// end up inside itself -- which `moveSystem` decides.
			if (path === system) { systemsMoved.set(path, path); continue; }
			systemsMoved.set(path, moveSystem(project, path, system));
		}
		return { moved: moveBlocks(project, blocks, system, { snapshot: false }), systems: systemsMoved };
	} catch (e) {
		for (const key of Object.keys(project)) delete project[key];
		Object.assign(project, snapshot);
		throw e;
	}
}

// --- copying --------------------------------------------------------------

/** How far a copy is offset from its original when nothing says where to put it. */
const CLONE_NUDGE = 28;

/**
 * Which connections come along with a set of blocks, and which cannot.
 *
 * A transfer is not really a thing you copy on its own: it is the arrow
 * between two compartments, and it means nothing without both of them. So the
 * rule is the one the request asked for, generalised to the ends a connection
 * can actually have: **a connection comes along when every compartment it
 * touches is coming along too**. Both ends selected, and the transfer follows.
 * One end selected, and it does not -- copying it would produce a transfer
 * pointing at a compartment somewhere else in the model, which is a different
 * model, not a copy of this one.
 *
 * The same rule covers the ends that are already outside: an outflow's only
 * compartment is its donor, and a source's is its receiver, so either comes
 * along with that one block.
 *
 * @returns {{carried: string[], stranded: string[]}} the connections that
 *   follow, and the ones that were asked for but cannot.
 */
function connectionsWith(project, chosen) {
	const compartments = new Set([...chosen].filter(
		(n) => findBlock(project, n)?.kind === 'compartment',
	));
	const ends = (conn) => [conn.from, conn.to].filter((e) => e != null);
	const whole = (conn) => ends(conn).every((e) => compartments.has(e));
	const touches = (conn) => ends(conn).some((e) => compartments.has(e));

	const carried = [];
	const stranded = [];
	for (const conn of [...(project.transfers ?? []), ...(project.inflows ?? [])]) {
		const q = qualifiedName(conn);
		if (chosen.has(q)) {
			// Asked for by name. It still needs its compartments.
			if (!whole(conn)) stranded.push(q);
			continue;
		}
		if (touches(conn) && whole(conn)) carried.push(q);
	}
	return { carried, stranded };
}

/**
 * Whether a selection holds anything that can be taken somewhere on its own.
 *
 * A transfer is the arrow between two compartments and is nothing without
 * them. Copied alone it would paste as a connection pointing at blocks that
 * are not in the copy, which is not a copy of anything; moved alone it would
 * sit in a sub-system its own two ends are not in, which is not a model.
 * `connectionsWith` already strands such a connection rather than carrying it
 * -- this is the same rule asked one step earlier, so that a menu can decline
 * instead of the act producing nothing or something broken.
 *
 * True as soon as one thing would travel: a sub-system, any block that is not
 * a connection, or a connection whose compartments are in the selection too.
 * It answers Cut, Copy and Move, which are three ways of asking it.
 */
export function canTravel(project, names) {
	const chosen = [...new Set(names ?? [])];
	if (!chosen.length) return false;
	const paths = systems(project);
	// A sub-system carries everything inside it, so it is always something.
	if (chosen.some((n) => paths.includes(n))) return true;
	const compartments = new Set(chosen.filter(
		(n) => findBlock(project, n)?.kind === 'compartment',
	));
	return chosen.some((n) => {
		const found = findBlock(project, n);
		if (!found) return false;
		if (found.kind !== 'transfer' && found.kind !== 'inflow') return true;
		const ends = [found.block.from, found.block.to].filter((e) => e != null);
		return ends.every((e) => compartments.has(e));
	});
}

const isConnection = (project, name) => {
	const kind = findBlock(project, name)?.kind;
	return kind === 'transfer' || kind === 'inflow';
};

/**
 * What a selection of names actually names.
 *
 * A selection can hold sub-systems as well as blocks: on the diagram a
 * sub-system is a node like any other, and in the tree it is a row like any
 * other. It is not the same kind of thing, though -- it is a name that blocks
 * live under -- so anything acting on a selection has to sort the two out
 * first, and two kinds of overlap go with them.
 *
 * A chosen sub-system inside another chosen sub-system is dropped: the
 * ancestor already carries it. And a chosen block inside a chosen sub-system
 * is dropped for the same reason -- copying it as well would paste two copies
 * of it, and deleting it as well would delete it twice.
 *
 * @returns {{systems: string[], blocks: string[], inside: string[]}} the
 *   sub-systems chosen, the blocks chosen in their own right, and the blocks
 *   that were named but are coming along inside a sub-system anyway. A name
 *   that is neither is dropped rather than refused, so a selection that has
 *   outlived what it named does not make every action fail.
 */
export function selectionParts(project, names) {
	const wanted = [...new Set(names)];
	const paths = systems(project);
	const chosen = wanted.filter((n) => paths.includes(n));
	const roots = chosen.filter((p) => !chosen.some((q) => q !== p && isWithin(p, q)));
	const blocks = [];
	const inside = [];
	for (const n of wanted) {
		if (paths.includes(n)) continue;
		const found = findBlock(project, n);
		if (!found) continue;
		if (roots.some((p) => isWithin(systemOf(found.block), p))) inside.push(n);
		else blocks.push(n);
	}
	return { systems: roots, blocks, inside };
}

/**
 * Everything a copy of some blocks has to carry, ready for `pasteBlocks`.
 *
 * Blocks only, and a name that is not one is ignored: `copySelection` is the
 * one that takes a selection of blocks and sub-systems together.
 */
export function copyBlocks(project, names) {
	const wanted = [...new Set(names)].filter((n) => findBlock(project, n));
	if (!wanted.length) throw new EditError('Nothing to copy');
	return copySelection(project, wanted);
}

/** The part of `path` below `root`: `A.B.C` inside `A` is `B.C`, and `A` is ``. */
const below = (path, root) => (path === root ? '' : path.slice(root.length + 1));

/** The other direction, where the empty relative path means the root itself. */
const under = (root, rel) => (rel ? qualify(root, rel) : root);

/**
 * A place on one sub-system's canvas that nothing is drawn at yet.
 *
 * Where a paste goes when nobody said where. Coordinates belong to the canvas
 * they were taken from: on a different one they mean nothing, and a copy that
 * lands squarely on top of a block that was already there reads as a fault
 * rather than as a paste. Below everything, at the left edge, which is where
 * `autoLayout` would have started a new row.
 */
export function freeSpotIn(project, system) {
	const seen = allBlocks(project)
		.filter((b) => systemOf(b) === system)
		.map((b) => project.layout?.[qualifiedName(b)])
		.concat(childSystems(project, system).map((p) => project.layout?.[p]))
		.filter((e) => Number.isFinite(e?.x) && Number.isFinite(e?.y));
	if (!seen.length) return { x: 90, y: 70 };
	return {
		x: Math.min(...seen.map((e) => e.x)),
		y: Math.max(...seen.map((e) => e.y + (e.h ?? 54))) + 90,
	};
}

/**
 * Everything a copy of a selection has to carry, ready for `pasteBlocks`.
 *
 * Deep clones, taken now rather than on paste: the point of a clipboard is
 * that what you copied is what you get, however the model changes in between
 * -- including a block being deleted, which would otherwise make the paste
 * fail with a message about a block the user is no longer looking at.
 *
 * A selection can name blocks and sub-systems together, and the two are
 * carried differently. A block is carried as itself. A sub-system is not a
 * block -- it is a name that other things live under -- so what a copy of one
 * carries is its contents: every block inside it however deep, every
 * sub-system nested in it (including the empty ones, which are where the next
 * block goes), and the arrows between them. Each of those is remembered by
 * where it sits *relative to the sub-system*, because that is the only part
 * that survives the copy landing somewhere else under another name.
 *
 * The rule about connections is one rule for the whole copy, which is what
 * makes it worth having only one: **a connection comes along when every
 * compartment it touches is coming along too**. So the arrows inside a copied
 * sub-system follow it; an arrow that leaves it does not, since copying that
 * would wire the copy into the original's neighbours, which is a change to the
 * model rather than a copy of part of it; and an arrow between a block on the
 * canvas and a compartment inside a copied sub-system comes along when both
 * were selected, which is the same rule read across the two.
 *
 * @returns {{kind: string, parts: Array<object>, blocks: Array<object>,
 *            system: string|null, stranded: string[]}}
 *   `parts` is one entry per sub-system copied, and every block says which of
 *   them it belongs to -- or -1 for the ones chosen in their own right.
 *   `system` is the canvas it all came from, or null when it came from more
 *   than one, which the tree allows and the diagram does not.
 */
export function copySelection(project, names) {
	const { systems: chosen, blocks: loose } = selectionParts(project, names);
	if (!chosen.length && !loose.length) throw new EditError('Nothing to copy');

	const parts = chosen.map((path) => ({
		path,
		name: baseName(path),
		from: parentOf(path),
		// Its own place on the parent's canvas, which is the one coordinate
		// that has to move: everything inside is drawn on its own canvas and
		// lands looking exactly as it did.
		node: project.layout?.[path] ? { ...project.layout[path] } : null,
		// The sub-system itself is the empty relative path, so an empty one
		// still copies as a sub-system rather than as nothing at all.
		subs: systems(project).filter((p) => isWithin(p, path)).map((p) => below(p, path)),
		// Which of those are transports, so the copy is a chain as the
		// original was.
		transports: systems(project)
			.filter((p) => isWithin(p, path) && tr.isTransport(project, p))
			.map((p) => below(p, path)),
		// And which are switched off, so a copy of a disabled sub-system is
		// a disabled sub-system rather than a live one nobody asked for.
		disabled: systems(project)
			.filter((p) => isWithin(p, path) && disabledSystems(project).includes(p))
			.map((p) => below(p, path)),
		// What is drawn on its canvases. A group box round four compartments
		// is part of how the sub-system reads, and a copy of it that arrived
		// with the boxes and without the drawing round them was a copy of the
		// wrong thing. Kept by the canvas each is on, relative to the
		// sub-system, the same way its blocks are.
		shapes: shapesInDeep(project, path).map((sh) => ({
			...structuredClone(sh),
			rel: below(sh.system ?? '', path),
		})),
	}));
	const partOf = (system) => parts.findIndex((p) => isWithin(system, p.path));
	const within = allBlocks(project)
		.filter((b) => partOf(systemOf(b)) >= 0)
		.map((b) => qualifiedName(b));

	const { carried, stranded } = connectionsWith(project, new Set([...loose, ...within]));
	const strandedSet = new Set(stranded);
	const coming = [...loose, ...within].filter((n) => !strandedSet.has(n));
	// Blocks first, then the connections between them: pasted in this order,
	// a transfer's endpoints already exist by the time it lands.
	const order = [
		...coming.filter((n) => !isConnection(project, n)),
		...coming.filter((n) => isConnection(project, n)),
		...carried,
	];
	if (!order.length && !parts.length) {
		// Everything asked for was a connection with nowhere to land. Said in
		// terms of what to do about it, since "nothing to copy" about a thing
		// that is plainly selected reads as a fault in the program.
		throw new EditError(stranded.length
			? `'${stranded[0]}' is the arrow between two compartments, so it cannot `
				+ 'be copied on its own. Select the compartments at both ends of it too.'
			: 'Nothing to copy');
	}

	const blocks = order.map((n) => {
		const found = findBlock(project, n);
		const part = partOf(systemOf(found.block));
		return {
			name: n,
			collection: found.collection,
			block: structuredClone(found.block),
			part,
			rel: part >= 0 ? below(systemOf(found.block), parts[part].path) : null,
			layout: project.layout?.[n] ? { ...project.layout[n] } : null,
			bend: project.layout?.[EDGE_PREFIX + n]
				? { ...project.layout[EDGE_PREFIX + n] }
				: null,
		};
	});
	// Where the copy was taken from, meaning the canvas it was drawn on: the
	// homes of the blocks chosen in their own right, and for a sub-system the
	// parent it is a node on. What is inside a sub-system is not on that
	// canvas at all, so it does not have a say.
	const homes = new Set([
		...blocks.filter((b) => b.part < 0).map((b) => parentOf(b.name)),
		...parts.map((p) => p.from),
	]);
	return {
		kind: 'clip',
		// Without `path`, which names something in the model this copy has
		// already stopped depending on.
		parts: parts.map(({ path, ...rest }) => rest),
		blocks,
		system: homes.size === 1 ? [...homes][0] : null,
		stranded,
	};
}

/** Everything a copy of one whole sub-system has to carry. */
export function copySystem(project, path) {
	if (!path) throw new EditError('The model itself is not a sub-system');
	if (!systems(project).includes(path)) {
		throw new EditError(`No sub-system named '${path}'`);
	}
	return copySelection(project, [path]);
}

/**
 * Puts a copy of what `copySelection` took into the model.
 *
 * Three things have to be true of the result, and each of them is a place this
 * could go wrong quietly.
 *
 * A name already used in the sub-system it lands in gets a number, as
 * everything else in this file does -- `Water`, then `Water1`.
 *
 * Every reference *within the copy* follows the copy: a pasted transfer joins
 * the pasted compartments, and a pasted expression reads the pasted parameter
 * rather than the original. References *out* of the copy are left pointing
 * where they pointed, which is the other half of the same rule: a copied
 * transfer whose rate is `k` still means the `k` that was not copied.
 *
 * And a reference is resolved from where it was *written* and re-spelled for
 * where it *lands*: an equation saying `k` inside `NearField`, pasted into
 * `FarField`, has to go on meaning `NearField.k` -- resolving it in its new
 * home would silently rebind it to a different block with the same name.
 *
 * @param {object} project
 * @param {object} payload from `copySelection`
 * @param {{system?: string|null, at?: {x: number, y: number}|null}} [opts]
 *   `system` is where they all go; null means each keeps its own, which is
 *   what cloning in place means. `at` is where the group's top-left corner
 *   goes on the diagram.
 * @returns {{added: string[], renamed: Array<[string, string]>,
 *            dropped: string[], lostEntries: number,
 *            shadowed: Array<{block: string, reference: string, where: string}>}}
 *   `dropped` names the index lists the receiving model does not have, and
 *   `lostEntries` counts the per-index values that went with them -- both only
 *   possible when the copy came from another model. `shadowed` lists the
 *   references that could not be re-spelled for where the copy landed, and
 *   therefore now mean a different block.
 */
export function pasteBlocks(project, payload, { system = null, at = null } = {}) {
	const parts = payload?.parts ?? [];
	if (!payload || (!payload.blocks?.length && !parts.length)) {
		throw new EditError('Nothing to paste');
	}
	if (system) {
		if (!systems(project).includes(system)) {
			throw new EditError(`No sub-system named '${system}'`);
		}
	}

	// Each sub-system in the copy lands as a new sub-system of the target,
	// under a name free among its siblings, and everything it carries hangs
	// off that at the depth it was copied from. Nothing inside it can collide
	// with anything, since what it lands in is a sub-system that did not exist
	// a moment ago: the copy keeps every name it had, which is the point of
	// copying it.
	const roots = [];
	const newSystems = [];
	const newTransports = [];
	const newDisabled = [];
	const takenSystems = new Set(systems(project));
	for (const part of parts) {
		const parent = system == null ? (part.from ?? '') : system;
		if (parent && !systems(project).includes(parent)) {
			throw new EditError(`No sub-system named '${parent}'`);
		}
		// Not `nextSystemName`, which asks the project: the project does not
		// yet know the names this same paste has already claimed, and two
		// copies of one sub-system must not both be offered `NearField1`.
		let local = part.name;
		for (let i = 1; takenSystems.has(qualify(parent, local)); i++) {
			local = `${part.name}${i}`;
		}
		const root = qualify(parent, local);
		roots.push(root);
		takenSystems.add(root);
		// `qualify` puts a separator in unconditionally, so the root's own
		// relative path -- the empty string -- has to be recognised rather
		// than passed through it: `qualify('NF1', '')` is `NF1.`, and every
		// name under it came out with two dots in the middle.
		for (const rel of part.subs ?? ['']) {
			const path = under(root, rel);
			newSystems.push(path);
			takenSystems.add(path);
		}
		for (const rel of part.transports ?? []) newTransports.push(under(root, rel));
		for (const rel of part.disabled ?? []) newDisabled.push(under(root, rel));
	}
	const homeOf = (item) => {
		if (item.part >= 0) return under(roots[item.part], item.rel ?? '');
		return system == null ? (item.block.system ?? '') : system;
	};

	// Landing on a canvas the copy did not come from, with nobody saying
	// where: its own coordinates are meaningless there, so a clear spot is
	// found instead. Worked out now, before anything is inserted, or it would
	// be looking at the copies as well.
	const canvas = system ?? (payload.system ?? '');
	const foreign = system != null && system !== payload.system;
	const spot = at ?? (foreign ? freeSpotIn(project, canvas) : null);

	// Every name settled before anything is inserted: two copies of the same
	// block in one paste must not both be offered `Water1`.
	const taken = new Set(blockNames(project));
	const map = new Map();
	const renamed = [];
	for (const item of payload.blocks) {
		const home = homeOf(item);
		let local = item.block.name;
		if (taken.has(qualify(home, local))) {
			// Not `uniqueName`, which asks the project: the project does not
			// yet know about the names this same paste has already claimed.
			for (let i = 1; taken.has(qualify(home, local)); i++) {
				local = `${item.block.name}${i}`;
			}
			renamed.push([item.name, qualify(home, local)]);
		}
		const now = qualify(home, local);
		taken.add(now);
		map.set(item.name, now);
	}

	// The copies, still wearing the names and sub-systems they were taken
	// from: the rewrite below has to read their equations from where they were
	// written before it can re-spell them for where they are going.
	const clones = payload.blocks.map((item) => ({
		item, block: structuredClone(item.block), now: map.get(item.name),
	}));
	const staging = {};
	for (const c of clones) {
		if (!Array.isArray(staging[c.item.collection])) staging[c.item.collection] = [];
		staging[c.item.collection].push(c.block);
	}

	// An index list the model on the receiving end has never heard of would
	// make it unbuildable, which is a strange thing for a paste to do. Only
	// possible across models, since a copy carries no lists of its own.
	const known0 = indexLists(project);
	const lists = new Set(known0.map((l) => l.name));
	// The two dimensions made of the model's own blocks are *about to* exist
	// where the blocks arriving are the first of their kind: a model with no
	// compartments has no `Compartments` list, and a paste that brings three
	// compartments and a value per compartment would otherwise drop the
	// dimension on the way in and leave the values with nowhere to sit.
	const autoOf = new Map(known0.filter((l) => l.auto).map((l) => [l.name, l.auto]));
	for (const [name, collection] of [
		[COMPARTMENT_LIST, 'compartments'], [TRANSFER_LIST, 'transfers'],
	]) {
		if (lists.has(name)) continue;
		if (!clones.some((c) => c.item.collection === collection)) continue;
		lists.add(name);
		autoOf.set(name, collection);
	}
	const dropped = [];
	for (const c of clones) {
		if (!Array.isArray(c.block.index_lists)) continue;
		const keep = c.block.index_lists.filter((d) => lists.has(d));
		if (keep.length === c.block.index_lists.length) continue;
		for (const d of c.block.index_lists) if (!lists.has(d)) dropped.push(d);
		if (keep.length) c.block.index_lists = keep;
		else delete c.block.index_lists;
	}
	// And an entry keyed by an index the receiving model does not have is
	// worse than a dimension it does not have: `Project` refuses the whole
	// model over one, so a paste would leave it unrunnable with a message
	// about an index nobody has heard of. The per-index values go; the block's
	// own value, which they were overriding, is what is left.
	const indicesIn = new Map(known0.map(
		(l) => [l.name, new Set((l.indices ?? []).map((i) => i.name))],
	));
	// An index of one of those two dimensions *is* a block, so a value held
	// per compartment is keyed by a compartment's name -- and a name is
	// exactly what a paste changes. Two things follow, and without them a
	// per-compartment value quietly moves to a different compartment: a key
	// naming a block that is arriving is re-spelled with the name it arrives
	// under, the way an equation naming it is; and it is then not dropped for
	// naming an index the model does not have, because it is about to.
	for (const c of clones) {
		for (const e of c.block.entries ?? []) {
			for (const [list, index] of Object.entries(e.index ?? {})) {
				if (!autoOf.has(list)) continue;
				const to = map.get(index);
				if (to) e.index[list] = to;
			}
		}
	}
	for (const [list, collection] of autoOf) {
		if (!indicesIn.has(list)) indicesIn.set(list, new Set());
		const set = indicesIn.get(list);
		for (const c of clones) if (c.item.collection === collection) set.add(c.now);
	}
	let lostEntries = 0;
	for (const c of clones) {
		if (!Array.isArray(c.block.entries)) continue;
		const keep = c.block.entries.filter((e) => Object.entries(e.index ?? {})
			.every(([list, index]) => indicesIn.get(list)?.has(index)));
		if (keep.length === c.block.entries.length) continue;
		lostEntries += c.block.entries.length - keep.length;
		if (keep.length) c.block.entries = keep;
		else delete c.block.entries;
	}

	// Both spellings resolve while the rewrite runs: the old names are what
	// the equations say, and the new ones are what they are becoming.
	const namesKnown = new Set([...blockNames(project), ...map.values()]);
	const known = (n) => namesKnown.has(n);
	for (const c of clones) {
		for (const end of ['from', 'to']) {
			if (c.block[end] == null) continue;
			c.block[end] = map.get(c.block[end]) ?? c.block[end];
		}
	}
	const landing = (block) => {
		const c = clones.find((x) => x.block === block);
		return c ? parentOf(c.now) : '';
	};
	// A reference the notation cannot express from where the copy lands.
	//
	// A block at the top level is written by its bare name, and inside a
	// sub-system that has a block of the same name the bare name means the
	// other one -- there is no absolute spelling to fall back on, in this tool
	// or in Ecolego. So the text is left exactly as it was written, which is
	// the least wrong of the things it could say, and the caller is told: a
	// reference that quietly means a different block is the one outcome of a
	// paste that must not pass without a word.
	const shadowed = [];
	const spell = (to, where, from, block) => {
		const text = referenceFrom(to, where, known);
		if (resolveReference(text, where, known) === to) return text;
		shadowed.push({
			block: block ? baseName(landingName(clones, block)) : '?',
			reference: text,
			where: where || 'the top level',
		});
		return null;
	};
	forEachEquation(staging, (text, from, block) => rewriteEquation(
		text, from, known,
		(q) => {
			const to = map.get(q) ?? q;
			const where = landing(block);
			if (to === q && where === from) return null;
			return spell(to, where, from, block);
		},
	));
	// A reduction names what it reduces instead of writing an equation, and
	// those names are references like any other. `forEachTarget` walks the
	// staged copies only, so nothing outside the paste is touched.
	forEachTarget(staging, (ref, from, block) => {
		const q = resolveReference(ref, from, known);
		if (q == null) return ref;
		const to = map.get(q) ?? q;
		const where = block ? landing(block) : from;
		if (to === q && where === from) return ref;
		return spell(to, where, from, block) ?? ref;
	});

	// Now they can wear their new names.
	for (const c of clones) {
		c.block.name = baseName(c.now);
		const home = parentOf(c.now);
		if (home) c.block.system = home;
		else delete c.block.system;
		// A part of a transport copied on its own is a plain block: the chain
		// it was part of is not coming, and a second Begin beside the first
		// would make the transport it lands in unbuildable.
		if (c.item.part < 0 && tr.roleOf(c.block)) {
			const role = tr.roleOf(c.block);
			delete c.block.transport;
			if (role === 'counter') c.block.equation = '1';
			if (role === 'operation') {
				c.block.equation = '0';
				delete c.block.operation;
				delete c.block.argument;
			}
		}
		ensure(project, c.item.collection).push(c.block);
	}

	// Where they are drawn.
	//
	// The nodes that land on the canvas pasted onto are the blocks chosen in
	// their own right and the one node standing for each sub-system in the
	// copy. The group keeps its shape -- its own arrangement is most of what
	// makes it worth copying -- so one offset moves all of them.
	layoutOf(project);
	const nodes = [
		...payload.blocks.filter((b) => b.part < 0 && Number.isFinite(b.layout?.x))
			.map((b) => b.layout),
		...parts.map((p) => p.node).filter((n) => Number.isFinite(n?.x)),
	];
	let dx = CLONE_NUDGE;
	let dy = CLONE_NUDGE;
	if (spot && nodes.length) {
		dx = spot.x - Math.min(...nodes.map((n) => n.x));
		dy = spot.y - Math.min(...nodes.map((n) => n.y));
	}
	parts.forEach((part, i) => {
		if (part.node && Number.isFinite(part.node.x)) {
			project.layout[roots[i]] = {
				...part.node,
				x: Math.round(part.node.x + dx),
				y: Math.round(part.node.y + dy),
			};
		} else if (spot) {
			project.layout[roots[i]] = { x: Math.round(spot.x), y: Math.round(spot.y) };
		}
	});
	for (const c of clones) {
		// What is inside a copied sub-system is drawn on that sub-system's
		// *own* canvas, in its own coordinates, and has to land looking
		// exactly as it did -- getting this wrong would be visible, shifting
		// the contents of every copy for no reason. So the offset moves the
		// node standing for it and not the things inside.
		const ox = c.item.part >= 0 ? 0 : dx;
		const oy = c.item.part >= 0 ? 0 : dy;
		const src = c.item.layout;
		if (src && Number.isFinite(src.x)) {
			project.layout[c.now] = {
				...src, x: Math.round(src.x + ox), y: Math.round(src.y + oy),
			};
		}
		if (c.item.bend) {
			project.layout[EDGE_PREFIX + c.now] = {
				x: Math.round(c.item.bend.x + ox), y: Math.round(c.item.bend.y + oy),
			};
		}
	}

	// The sub-systems themselves, including any that are empty: `systems`
	// derives what it can from the blocks, so only the empty ones would
	// otherwise be lost -- and an empty sub-system is where the next block
	// goes, which is worth carrying.
	if (newSystems.length) {
		project.systems = [...new Set([...systems(project), ...newSystems])];
	}
	if (newTransports.length) {
		project.transports = [...new Set([...tr.transportPaths(project), ...newTransports])];
	}
	if (newDisabled.length) {
		project.disabled_systems = [...new Set([...disabledSystems(project), ...newDisabled])];
	}

	// What was drawn on the copied sub-system's canvases. New ids, because a
	// shape's id is its identity in this model and the original's are taken;
	// the coordinates are its own canvas's and land unchanged, exactly as the
	// blocks beside them do.
	let pastedShapes = 0;
	parts.forEach((part, i) => {
		for (const sh of part.shapes ?? []) {
			const { rel, id, system: _was, ...rest } = sh;
			const home = under(roots[i], rel ?? '');
			if (!Array.isArray(project.shapes)) project.shapes = [];
			project.shapes.push({
				...rest,
				id: nextShapeId(project),
				...(home ? { system: home } : {}),
			});
			pastedShapes++;
		}
	});

	return {
		added: clones.map((c) => c.now),
		// The one sub-system, when a sub-system is all this was: the caller
		// shows that as itself rather than by its contents.
		system: roots.length === 1 && !payload.blocks.some((b) => b.part < 0)
			? roots[0]
			: null,
		systems: roots,
		renamed,
		dropped: [...new Set(dropped)],
		lostEntries,
		shadowed,
		shapes: pastedShapes,
	};
}

/** The name a staged copy is about to be given, for a message about it. */
const landingName = (clones, block) => clones.find((c) => c.block === block)?.now ?? '';

/**
 * Copies blocks and pastes them straight back where they came from.
 *
 * Not `copyBlocks` followed by `pasteBlocks` at the call site, because the
 * two have to see the same model: anything between them -- a re-render, an
 * auto-run -- and the second half would be working from a model the first half
 * did not describe.
 */
export function cloneBlocks(project, names) {
	const payload = copyBlocks(project, names);
	const result = pasteBlocks(project, payload, { system: null });
	return { ...result, stranded: payload.stranded };
}

/** Copies a sub-system and puts the copy beside it, in the same parent. */
export function cloneSystem(project, path) {
	const payload = copySystem(project, path);
	const result = pasteBlocks(project, payload, { system: null });
	return { ...result, stranded: payload.stranded };
}

/**
 * Deletes a selection of blocks and sub-systems as one edit.
 *
 * A sub-system stands for everything inside it, so deleting one deletes its
 * contents however deep -- there is nothing else it could mean, since the
 * sub-system is only a name and the blocks are what is really there. `Dissolve`
 * is the other half of the pair, and keeps them.
 *
 * One `deleteBlocks` for the lot rather than one call per sub-system: what
 * counts as still in use is decided across the whole set, so a block inside a
 * sub-system and a block outside it that read each other can go together --
 * and either would refuse to go alone.
 *
 * @returns {{removed: string[], systems: string[]}} every block that went,
 *   including the connections that could not outlive an endpoint, and the
 *   sub-systems that went with them.
 */
export function deleteSelection(project, names) {
	const { systems: chosen, blocks } = selectionParts(project, names);
	const inside = chosen.flatMap(
		(p) => blocksIn(project, p, { deep: true }).map((b) => qualifiedName(b)),
	);
	const removed = deleteBlocks(project, [...new Set([...blocks, ...inside])]);
	if (chosen.length) {
		project.systems = systems(project).filter(
			(p) => !chosen.some((c) => isWithin(p, c)),
		);
		if (tr.transportPaths(project).length) {
			project.transports = tr.transportPaths(project).filter(
				(p) => !chosen.some((c) => isWithin(p, c)),
			);
		}
		if (disabledSystems(project).length) {
			project.disabled_systems = disabledSystems(project).filter(
				(p) => !chosen.some((c) => isWithin(p, c)),
			);
			if (!project.disabled_systems.length) delete project.disabled_systems;
		}
		// The sub-systems' own nodes, and anything still keyed on a name
		// inside them -- a connection's bend outlives `spliceBlock`, which
		// only knows about the block's own entry.
		for (const key of Object.keys(project.layout ?? {})) {
			const edge = parseEdgeKey(key);
			const named = edge ? edge.name : key;
			// ...and a pipe drawn on one of the canvases that are going.
			const on = edge?.view ?? null;
			if (chosen.some((c) => isWithin(named, c) || (on && isWithin(on, c)))) delete project.layout[key];
		}
	}
	return { removed, systems: chosen };
}

/**
 * Deletes several blocks as one edit.
 *
 * The difference from deleting them one at a time is what counts as still in
 * use: two blocks that refer to each other can be deleted together, and cannot
 * be deleted apart. Refusing the pair because each holds the other would make
 * a selection undeletable for no reason a user could act on.
 *
 * @returns {string[]} every block that went, including the connections that
 *   could not outlive an endpoint.
 */
export function deleteBlocks(project, names) {
	const wanted = [...new Set(names)];
	for (const name of wanted) {
		if (!findBlock(project, name)) throw new EditError(`No block named '${name}'`);
	}

	// Everything that will go, worked out before anything does: the blocks
	// themselves, plus the connections hanging off any compartment in the set.
	const going = new Set(wanted);
	for (const name of wanted) {
		const kind = findBlock(project, name)?.kind;
		if (!HOLDS_INVENTORY.has(kind)) continue;
		for (const t of project.transfers ?? []) {
			if (t.from === name || t.to === name) going.add(qualifiedName(t));
		}
		for (const src of project.inflows ?? []) {
			if (src.to === name) going.add(qualifiedName(src));
		}
	}

	guardTransportParts(project, going);

	// One walk of the model for the whole selection, not one per block: this
	// is the difference between deleting a large sub-system in milliseconds
	// and in half a minute. See `referencesToAny`.
	//
	// Over everything that is going, not only what was named: a transfer
	// that leaves with its compartment is read by name too -- an expression
	// summing the outflows, say -- and asking only about the compartments
	// let it go while `E = Water_Sed * 2` still read it.
	const users = referencesToAny(project, [...going]);
	const blocked = new Map();
	for (const name of going) {
		const outside = (users.get(name) ?? []).filter((n) => !going.has(n));
		if (outside.length) blocked.set(name, outside);
	}
	if (blocked.size) {
		const [first, users] = [...blocked][0];
		const rest = blocked.size - 1;
		throw new EditError(
			`'${first}' is still used by ${users.join(', ')}.`
			+ `${rest ? ` ${rest} more of the selection ${rest === 1 ? 'is' : 'are'} too.` : ''}`
			+ ' Change those equations first.',
			[...new Set([...blocked.values()].flat())],
		);
	}

	// Removed directly rather than one `deleteBlock` at a time: that checks
	// each block against the whole model, and two blocks that read each other
	// would each be held up by the other, though the pair is going together.
	const removed = [];
	for (const name of going) {
		// Which list its name was an index of, before it stops being a block.
		const kind = findBlock(project, name)?.kind;
		if (!spliceBlock(project, name)) continue;
		removed.push(name);
		// A value set for a compartment that no longer exists is not a value
		// set for anything -- and left behind it would come back to life the
		// day a new block took the name.
		if (kind === 'compartment') dropBlockIndex(project, name, COMPARTMENT_LIST);
		else if (kind === 'transfer') dropBlockIndex(project, name, TRANSFER_LIST);
	}
	return removed;
}

/**
 * Moves a block into a sub-system made for it, in the one it is already in.
 *
 * Two edits that are only ever wanted together. Organising a model that
 * arrived flat -- which is how most of them arrive -- means going through it
 * saying "this belongs in a part of its own", and doing that as `New
 * sub-system here` followed by `Move into` leaves an empty sub-system behind
 * the moment you stop halfway.
 *
 * The new sub-system is a child of the one the block is in, so the block goes
 * down a level rather than across. A name already used by a sub-system there
 * is *used*, not side-stepped into `Sand1`: `created` says which happened, so
 * the caller can say so. A name already used by a **block** is refused -- a
 * sub-system and a block cannot share an id, which is what
 * the rule for which blocks a sub-system may hold says too -- unless that block is the
 * one being moved, which is about to vacate the name.
 *
 * `names` may be one block or several; several go in together, and the
 * sub-system is put where the top-left of the group was.
 *
 * @returns {{system: string, moved: Map<string, string>, created: boolean}}
 *   where they went, what each is now called, and whether the sub-system is
 *   new.
 */
export function moveIntoNewSystem(project, names, systemName = null) {
	const wanted = (Array.isArray(names) ? names : [names]).filter(Boolean);
	if (!wanted.length) throw new EditError('Nothing to move');
	for (const n of wanted) {
		if (!findBlock(project, n)) throw new EditError(`No block named '${n}'`);
	}
	const parent = systemOf(findBlock(project, wanted[0]).block);

	const local = systemName == null || String(systemName).trim() === ''
		? nextSystemName(project, parent)
		: String(systemName).trim();
	if (baseName(local) !== local || !isValidPath(local)) {
		throw new EditError(
			`'${local}' is not a valid name for a sub-system (letters, digits and `
			+ 'underscore; must not start with a digit, and no dots -- this makes one '
			+ 'level, not a path)',
		);
	}

	const path = qualify(parent, local);
	if (nameTaken(project, path) && !wanted.includes(path)) {
		throw new EditError(
			`'${path}' is already a block, and a sub-system cannot share its name`,
		);
	}

	const created = !systems(project).includes(path);
	// `allow`: the name may be a block's, when that block is one of the ones
	// moving in -- the check just above is what settles that.
	if (created) addSystem(project, { name: local, parent, allow: path });

	// The container takes the place of what went into it, so the eye finds it
	// where the blocks were: the top-left corner of the group.
	const at = wanted.map((n) => getPosition(project, n)).filter(Boolean);
	const moved = moveBlocks(project, wanted, path);
	if (created && at.length) {
		setPosition(project, path, {
			x: Math.min(...at.map((p) => p.x)),
			y: Math.min(...at.map((p) => p.y)),
		});
	}
	return { system: path, moved, created };
}

/**
 * Writes every connection's endpoints as qualified names.
 *
 * A file may name them relatively -- `Water` inside a sub-system -- and the
 * engine resolves that on load. The editor compares endpoints against block
 * names all over the place, so it is worth doing once here rather than scoping
 * at every comparison.
 */
export function qualifyEndpoints(project) {
	const compartments = new Set(
		(project.compartments ?? []).map((c) => qualifiedName(c)),
	);
	const known = (n) => compartments.has(n);
	for (const conn of [...(project.transfers ?? []), ...(project.inflows ?? [])]) {
		for (const end of ['from', 'to']) {
			const ref = conn[end];
			if (ref == null) continue;
			// An endpoint is an id first and a relative name second; see
			// Project._resolveEndpoints for why that order matters.
			conn[end] = known(ref)
				? ref
				: resolveReference(ref, systemOf(conn), known) ?? ref;
		}
	}
	return project;
}

/** The live block objects, as opposed to the copies `allBlocks` returns. */
function allBlocksLive(project) {
	const out = [];
	for (const kind of KINDS) for (const b of project[kind] ?? []) out.push(b);
	return out;
}

// --- the material dimensions ------------------------------------------------

/**
 * The two material dimensions, which every model has.
 *
 * Decay and ingrowth act along the materials, and in this domain that is not
 * an optional extra -- it is what the tool is for. So they are built in:
 * always present, not renamable and not removable, and what they contain is
 * edited like any other list while the physics behind them (half lives,
 * chains) lives on the Decay panel.
 *
 * There are two of them because Ecolego has two, maintained together in
 * the rule for a new contaminant:
 *
 *   `Materials`       every material the model knows -- radionuclides, and
 *                     whatever else it carries: stable carbon beside C-14,
 *                     water, a population of rabbits
 *   `Radionuclides`   a sub-set of it, the ones that have a half-life; adding
 *                     one here adds the material to the catalogue as well
 *
 * A compartment may be indexed by either. Decay is applied per index from the
 * half-life of the name at it, so a compartment on the catalogue decays its
 * radionuclides and carries the rest unchanged -- which is exactly what
 * the standard decay term does, looking each index
 * up in the material model and decaying it if that entry is a nuclide.
 *
 * `for_materials` and `for_nuclides` stay in the file format as the markers of
 * which list holds which role, because an imported project may already name
 * them something else and renaming index lists in someone's model is not this
 * function's business.
 */
export const MATERIAL_LIST_NAME = MATERIAL_LIST;

/** The radionuclides among them. */
export const NUCLIDE_LIST_NAME = NUCLIDE_LIST;

/** The catalogue, or null in a raw file that has none. */
export function materialList(project) {
	return indexLists(project).find((l) => l.for_contaminants) ?? null;
}

/**
 * The radionuclides, or null in a raw file that has none.
 *
 * Falls back to the catalogue, because a file may state only one list and then
 * that list is both: it is what `splitMaterialRoles` has not yet been able to
 * tell apart, and what an older file means by its single material dimension.
 */
export function nuclideList(project) {
	const lists = indexLists(project);
	return lists.find((l) => l.for_nuclides)
		?? lists.find((l) => l.for_contaminants)
		?? null;
}

/**
 * Whether a list is where this model's radionuclides live.
 *
 * The flagged sub-set, or the catalogue itself in a file that states only one
 * material list -- which is what an older file is, and what a raw object
 * written by hand is likely to be. `splitMaterialRoles` tells the two apart
 * as a file is read; this is what the editor goes by until it has.
 */
function isNuclideRole(project, list) {
	if (!list) return false;
	if (list.for_nuclides) return true;
	return !!list.for_contaminants && !indexLists(project).some((l) => l.for_nuclides);
}

/** True for either of them: the two lists the interface protects. */
export function isBuiltInMaterialList(project, name) {
	const list = indexLists(project).find((l) => l.name === name);
	return !!list && (!!list.for_contaminants || !!list.for_nuclides);
}

/**
 * Both material lists, created if the project has neither.
 *
 * Called when a model is loaded, so everything downstream can rely on them
 * existing. Existing flagged lists are left exactly as they are, whatever they
 * are called.
 */
export function ensureMaterialLists(project) {
	// A model that states one list doing both jobs -- an older file, or an
	// imported one whose material dimension is called something else -- is
	// split into the two. Exactly the rule `splitMaterialRoles` applies as a
	// file is read, reused rather than written again, so there is one answer
	// to what a model's material dimensions are.
	const split = splitMaterialRoles(project);
	if (split !== project && Array.isArray(split.index_lists)) {
		project.index_lists = split.index_lists;
	}
	let materials = materialList(project);
	let nuclides = indexLists(project).find((l) => l.for_nuclides) ?? null;
	if (materials && nuclides) return { materials, nuclides };

	// Written down first, so creating a list cannot change what any block is
	// indexed by (see makeDimensionsExplicit).
	makeDimensionsExplicit(project);
	if (!Array.isArray(project.index_lists)) project.index_lists = [];

	if (!materials) {
		materials = {
			name: findIndexList(project, MATERIAL_LIST_NAME)
				? uniqueIndexListName(project, MATERIAL_LIST_NAME)
				: MATERIAL_LIST_NAME,
			for_contaminants: true,
			comment: 'Every material the model knows.',
			// A catalogue made under an existing radionuclide list holds what
			// that list holds: the sub-set below cannot name anything the root
			// above it does not have.
			//
			// An index may be written as a bare string -- the file format
			// allows `indices: ['I-129']` -- and spreading one of those copies
			// its *characters*, giving `{0: 'I', 1: '-', ...}`: an index with
			// no name, which the build refuses with "An index of 'Materials'
			// has no name" about a list the model never wrote.
			indices: (nuclides?.indices ?? []).map((i) => (typeof i === 'string'
				? { name: i, enabled: true }
				: { ...i })),
		};
		// First: it is the dimension the rest of the model is usually shaped by.
		project.index_lists.unshift(materials);
	}
	if (!nuclides) {
		nuclides = {
			name: findIndexList(project, NUCLIDE_LIST_NAME)
				? uniqueIndexListName(project, NUCLIDE_LIST_NAME)
				: NUCLIDE_LIST_NAME,
			for_nuclides: true,
			sub_set_of: materials.name,
			comment: 'The materials that have a half-life.',
			indices: [],
		};
		project.index_lists.splice(
			project.index_lists.indexOf(materials) + 1, 0, nuclides,
		);
	}
	syncNuclidesFromMaterialList(project);
	return { materials, nuclides };
}

/** The catalogue, created with its sub-set if the project has none. */
export function ensureMaterialList(project) {
	return ensureMaterialLists(project).materials;
}

/** The radionuclide list, created with its catalogue if the project has none. */
export function ensureNuclideList(project) {
	return ensureMaterialLists(project).nuclides;
}

/** True for the catalogue; it is one of the two the interface protects. */
export function isMaterialList(project, name) {
	return materialList(project)?.name === name;
}

/** True for the radionuclide list. */
export function isNuclideList(project, name) {
	return nuclideList(project)?.name === name;
}

/**
 * What one material is measured in, and setting it.
 *
 * Only a material that is not a radionuclide has one of its own. Ecolego holds
 * every nuclide's unit equal to the model's decay unit -- the contaminant catalogue
 * keeps the one and writes it onto the others -- because an inventory of a
 * radionuclide is an activity or an amount and the decay term is written in
 * terms of which. So a nuclide's unit is not a separate fact, and setting one
 * here is refused with the setting that does move it.
 */
export function setMaterialUnit(project, name, unit) {
	const root = materialList(project);
	if (!root) throw new EditError('This model has no materials');
	const index = (root.indices ?? []).find((i) => i.name === name);
	if (!index) throw new EditError(`'${name}' is not a material of this model`);
	const nuclides = indexLists(project).find((l) => l.for_nuclides);
	if (nuclides && nuclides !== root
		&& (nuclides.indices ?? []).some((i) => i.name === name)) {
		throw new EditError(
			`'${name}' is a radionuclide, and an inventory of one is measured in `
			+ `${DECAY_UNITS.join(' or ')} for the whole model -- change that under `
			+ `Decay and every nuclide follows. A material with a unit of its own `
			+ `is one that does not decay.`,
		);
	}
	const u = String(unit ?? '').trim();
	if (u) index.unit = u;
	else delete index.unit;
	syncDerivedUnits(project);
	return index;
}

/**
 * Adds nuclides to the radionuclide list, creating both lists if need be.
 *
 * Kept as one call because "give this model these nuclides" is a common thing
 * to say, in tests especially.
 */
export function addMaterialIndexList(project, { nuclides } = {}) {
	const list = ensureNuclideList(project);
	for (const n of nuclides ?? []) {
		if (!list.indices.some((i) => i.name === n)) addIndex(project, list.name, n);
	}
	return list;
}

/** Keeps the `nuclides` shorthand in step with whichever list is material. */
export function syncNuclidesFromMaterialList(project) {
	const list = nuclideList(project);
	if (!list) { delete project.nuclides; return; }
	project.nuclides = list.indices
		.filter((i) => i.enabled !== false)
		.map((i) => i.name);
}

// --- half-lives -------------------------------------------------------------

/**
 * How a stable nuclide is stored.
 *
 * Not `Infinity`: JSON has no such number, and `JSON.stringify` turns it into
 * `null`, which reads back as "no half-life at all" -- so a stable nuclide
 * survived until the file was saved and then broke the model on reload. The
 * word says what it means and round-trips.
 */
/**
 * What a radionuclide inventory is measured in: `Bq` or `mol`.
 *
 * `Bq` when the model does not say, which is Ecolego's default and what every
 * nuclide in the corpus carries.
 */
export function decayUnit(project) {
	const given = String(project?.decay_unit ?? '').trim();
	return DECAY_UNITS.includes(given) ? given : 'Bq';
}

/**
 * Changes what a radionuclide inventory is measured in.
 *
 * One numerical consequence, and it is the ingrowth coefficient: see
 * `DECAY_UNITS` in nuclides.js for why, and why it is exact either way rather
 * than one being an approximation of the other. Nothing is converted -- the
 * numbers in the model are read as being in whatever unit is chosen, which is
 * what Ecolego does too, and `bq2mole`/`mole2bq` are there for an equation
 * that needs to cross over.
 *
 * The labels do follow, though. A compartment carrying the *other*
 * radionuclide unit is relabelled, because a model that says `Bq` while its
 * ingrowth counts atoms is the trap this setting exists to close. Anything
 * else -- a blank unit, a concentration, something chosen on purpose -- is
 * left exactly as written and named in the report instead of being guessed at.
 *
 * @returns {{unit: string, was: string, relabelled: string[], left: string[]}}
 */
export function setDecayUnit(project, unit) {
	const want = String(unit ?? '').trim();
	if (!DECAY_UNITS.includes(want)) {
		throw new EditError(
			`'${unit}' is not a unit an inventory can be held in `
			+ `(${DECAY_UNITS.join(' or ')})`,
		);
	}
	const was = decayUnit(project);
	project.decay_unit = want;
	const relabelled = [];
	const left = [];
	if (was !== want) {
		for (const c of project.compartments ?? []) {
			const u = String(c.unit ?? '').trim();
			if (u === was) {
				c.unit = want;
				relabelled.push(qualifiedName(c));
			} else if (u && u !== want) {
				left.push(qualifiedName(c));
			}
		}
		// A compartment on the radionuclide dimension that never had a unit
		// is relabelled too -- from nothing -- and counts as relabelled in
		// what this reports. See syncInventoryUnits.
		relabelled.push(...syncInventoryUnits(
			project, materialDimensionNames(project),
			(c) => effectiveDims(project, c),
		));
		// A flux is its donor's unit over the time unit, so the transfers and
		// sources of everything just relabelled follow.
		syncFluxUnits(project);
	}
	return { unit: want, was, relabelled, left };
}

export const STABLE = 'stable';

/** True for anything that means "does not decay". */
function meansStable(v) {
	if (v === Infinity) return true;
	return typeof v === 'string' && /^(stable|inf(inity)?)$/i.test(v.trim());
}

/**
 * Sets a half-life in years, as an override on the built-in table.
 * Pass null to drop the override and fall back to the built-in value, or
 * Infinity (or "stable") for a nuclide that does not decay.
 */
export function setHalfLife(project, nuclide, years) {
	if (years == null) {
		if (project.half_lives) delete project.half_lives[nuclide];
		return;
	}
	if (!project.half_lives) project.half_lives = {};
	if (meansStable(years)) {
		project.half_lives[nuclide] = STABLE;
		return;
	}
	const v = Number(years);
	if (!(v > 0)) {
		throw new EditError('A half-life must be greater than zero');
	}
	project.half_lives[nuclide] = v;
}

/**
 * The half-life this project gives a nuclide, in years.
 *
 * Infinity for a stable one, null when nothing anywhere knows it -- which now
 * means a name ICRP 107 has never heard of, since its table is the default.
 * One reader for a value that can be written as a number or as the word
 * `stable`.
 *
 * `builtIn` is still a parameter so a caller can ask what the model would say
 * without the database behind it, but it defaults to the database.
 */
export function halfLifeOf(project, nuclide, builtIn = BUILT_IN_HALF_LIVES) {
	const own = (project.half_lives ?? {})[nuclide];
	if (own != null) return meansStable(own) ? Infinity : Number(own);
	const base = builtIn[nuclide];
	if (base == null) return null;
	return meansStable(base) ? Infinity : Number(base);
}

/** Whether a nuclide's half-life is set on the project rather than built in. */
export function hasHalfLifeOverride(project, nuclide) {
	return Object.prototype.hasOwnProperty.call(project.half_lives ?? {}, nuclide);
}

// --- decay chains -----------------------------------------------------------

/** The nuclides a raw project carries, whichever way it spells them. */
export function projectNuclides(project) {
	const list = materialList(project);
	if (list) return list.indices.map((i) => i.name);
	return [...(project?.nuclides ?? [])];
}

/**
 * The chains a project actually uses.
 *
 * `project.chains`, when present, *replaces* the default rather than adding to
 * it -- see Project's constructor. So the first edit has to materialise the
 * default, or setting one pair would silently delete every other chain in the
 * model.
 *
 * The default is no longer a table: it is the published chains collapsed onto
 * the nuclides this model carries, so it changes when the nuclide list does.
 * Which means writing `project.chains` is a real decision -- from that moment
 * the model's chains stop following its nuclides -- and it is only ever
 * written by an edit that means exactly that.
 */
export function effectiveChains(project) {
	if (project.chains) return project.chains;
	return defaultChains(projectNuclides(project));
}

function ownChains(project) {
	if (!project.chains) project.chains = effectiveChains(project).map((c) => [...c]);
	return project.chains;
}

export function addDecayPair(project, parent, daughter, ratio = 1) {
	if (!parent || !daughter) throw new EditError('A decay pair needs both nuclides');
	if (parent === daughter) {
		throw new EditError('A nuclide cannot decay into itself');
	}
	const r = Number(ratio);
	if (!(r > 0) || r > 1) {
		throw new EditError('A branching ratio must be greater than 0 and at most 1');
	}
	const chains = ownChains(project);
	if (chains.some((c) => c[0] === parent && c[1] === daughter)) {
		throw new EditError(`${parent} to ${daughter} is already in the chain list`);
	}
	// A cycle would make ingrowth feed itself indefinitely.
	if (reachesThrough(chains, daughter, parent)) {
		throw new EditError(
			`That would make a loop: ${parent} is already reachable from ${daughter}.`,
		);
	}
	chains.push([parent, daughter, r]);
	return chains;
}

/** Is `to` reachable from `from` by following the chains? */
function reachesThrough(chains, from, to) {
	const seen = new Set();
	const stack = [from];
	while (stack.length) {
		const n = stack.pop();
		if (n === to) return true;
		if (seen.has(n)) continue;
		seen.add(n);
		for (const c of chains) if (c[0] === n) stack.push(c[1]);
	}
	return false;
}

export function removeDecayPair(project, parent, daughter) {
	const chains = ownChains(project);
	const at = chains.findIndex((c) => c[0] === parent && c[1] === daughter);
	if (at < 0) throw new EditError(`${parent} to ${daughter} is not in the chain list`);
	chains.splice(at, 1);
}

export function setDecayRatio(project, parent, daughter, ratio) {
	const r = Number(ratio);
	if (!(r > 0) || r > 1) {
		throw new EditError('A branching ratio must be greater than 0 and at most 1');
	}
	const chains = ownChains(project);
	const pair = chains.find((c) => c[0] === parent && c[1] === daughter);
	if (!pair) throw new EditError(`${parent} to ${daughter} is not in the chain list`);
	pair[2] = r;
}

/**
 * Puts a set of radionuclides into the model, with their half-lives and the
 * decay pairs between them.
 *
 * One entry point, because the three halves of "add these nuclides" have to
 * agree: the index list gains the names, the half-life map gains their values,
 * and the chain list gains the pairs *and loses the ones it already had among
 * those same nuclides*. That last part is why this is not three calls -- a
 * model that already carried `U-238 -> U-234` from the built-in table would
 * otherwise end up with that pair twice, once with each table's branching.
 *
 * Half-lives are written as explicit overrides rather than left to the
 * built-in table. That is the honest thing: a chain worked out from a
 * published database should carry that database's numbers, in the project
 * file, where they can be read and cited -- and the built-in table is a
 * hand-entered subset that disagrees with ICRP 107 about six nuclides.
 *
 * @param {object} project
 * @param {object} sel
 * @param {string[]} sel.names        the nuclides to model
 * @param {Array<[string, string, number]>} [sel.pairs]  parent, daughter, branching
 * @param {Record<string, number>} [sel.halfLives]       in years; Infinity for stable
 * @returns {{added: string[], already: string[], pairs: number, replaced: number}}
 */
export function applyNuclides(project, sel) {
	const names = [...new Set(sel.names ?? [])];
	if (!names.length) throw new EditError('No nuclides to add');
	// Into the radionuclides, which is what the database holds. The catalogue
	// above gains every one of them on the way: see `addIndex`.
	const list = ensureNuclideList(project);

	const have = new Set(list.indices.map((i) => i.name));
	const added = [];
	const already = [];
	for (const name of names) {
		if (have.has(name)) { already.push(name); continue; }
		addIndex(project, list.name, name);
		added.push(name);
	}

	for (const [name, years] of Object.entries(sel.halfLives ?? {})) {
		if (!names.includes(name)) continue;
		setHalfLife(project, name, years);
	}

	let replaced = 0;
	const pairs = sel.pairs ?? [];
	if (pairs.length) {
		const chains = ownChains(project);
		const mine = new Set(names);
		// Every pair *out of* one of these nuclides goes, not only the ones
		// that land on another of them. What a selected nuclide decays into is
		// exactly what the collapse worked out, and the alternative leaves the
		// model contradicting itself: choosing a threshold that says Po-210 is
		// not modelled, and keeping `Pb-210 -> Po-210` from the built-in
		// table. A pair out of a nuclide this selection says nothing about is
		// left alone.
		for (let i = chains.length - 1; i >= 0; i--) {
			if (mine.has(chains[i][0])) {
				chains.splice(i, 1);
				replaced++;
			}
		}
		for (const [parent, daughter, ratio] of pairs) {
			if (parent === daughter) continue;
			// The computed pairs are acyclic among themselves, but they are
			// being added to a list that may not be, so this is checked rather
			// than assumed -- a cycle would make the decay matrix singular.
			if (reachesThrough(chains, daughter, parent)) continue;
			chains.push([parent, daughter, Number(ratio)]);
		}
	}

	return { added, already, pairs: pairs.length, replaced };
}

/**
 * @returns {string|null} an error message, or null when the equation is usable
 */
/**
 * A reusable equation checker for one model.
 *
 * The two sets it closes over -- every block's qualified name, and which of
 * them are lookup tables -- cost O(blocks) to build and do not change between
 * one equation and the next. `validateEquation` used to build them per call,
 * which made a whole-model scan quadratic: on a 1,600-block model that is
 * three million set insertions on every keystroke, and the scan runs on every
 * edit. Built once here instead.
 */
export function equationChecker(project) {
	// Resolved the way the builder resolves it, against qualified names and in
	// the owner's own sub-system. Matching local names against local names
	// instead reported every qualified reference as unknown, and quietly
	// accepted a bare name that only exists in some other sub-system.
	const known = new Set(blockNames(project));
	// A disabled block is known -- the name is somebody's -- and has no value,
	// which is a different complaint from an unknown one and has a different
	// fix. Said here, as the equation is typed, rather than left for the build.
	const off = disabledNames(project);
	// A lookup table read at an argument is *called*: `Q_gw(time)`, not
	// `Q_gw`. That is not a function the parser's table contains, so it has to
	// be told, exactly as sim/builder.js tells it (`callTarget`). Without the
	// same courtesy here, every model that drives something from a table
	// showed a red field and a complaint about an unknown function while
	// running perfectly well.
	const tables = new Set((project?.lookups ?? []).map((b) => qualifiedName(b)));
	// So is a transport operation read at a position: `Depth(0.5)`, or
	// `Depth(0, 0.5)` for a stretch. It has no value of its own to refer to.
	const called = new Set(tr.calledOperations(project).map((b) => qualifiedName(b)));
	const counters = new Set((project?.expressions ?? [])
		.filter((b) => tr.roleOf(b) === 'counter' && tr.transportOf(project, b))
		.map((b) => qualifiedName(b)));
	// The user-defined functions, by name and by how many arguments each
	// takes. A function is global -- the file keeps one flat
	// list on the model -- so a bare name is the whole of it.
	const functions = new Map((project?.functions ?? [])
		.filter((f) => f?.name)
		.map((f) => [f.name, (f.parameters ?? []).map(String)]));
	const calledHow = (q) => {
		const b = (project?.expressions ?? []).find((x) => qualifiedName(x) === q);
		return b?.argument === 'range' ? '(0, 0.5)' : '(0.5)';
	};

	/**
	 * One equation, checked.
	 *
	 * `locals` are names the equation may use that are not blocks: a
	 * function's parameters, and nothing else so far. Inside a body they are
	 * the *only* names allowed -- a body may not read the model -- which is
	 * what `only` says.
	 */
	return (equation, ownerName, { self = false, locals = null } = {}) => {
		const system = parentOf(ownerName ?? '');
		const resolve = (n) => resolveReference(n, system, (x) => known.has(x));
		const calls = (n) => {
			const q = resolve(n) ?? '';
			return tables.has(q) || called.has(q) || functions.has(n);
		};
		const arity = (ast) => {
			if (!ast || typeof ast !== 'object') return null;
			if (ast.type === 'call' && functions.has(ast.name)) {
				const want = functions.get(ast.name);
				if (ast.name === ownerName) {
					return `'${ast.name}' calls itself. A function is worked out where it `
						+ 'is called, so there would be nothing to stop at';
				}
				if ((ast.args ?? []).length !== want.length) {
					return `'${ast.name}' takes ${want.length} argument`
						+ `${want.length === 1 ? '' : 's'}`
						+ `${want.length ? ` (${want.join(', ')})` : ''}, but is called with `
						+ `${(ast.args ?? []).length}`;
				}
			}
			for (const part of [ast.operand, ast.left, ast.right, ast.test, ast.then,
				ast.otherwise, ...(ast.args ?? [])]) {
				const bad = arity(part);
				if (bad) return bad;
			}
			return null;
		};

		let ast;
		try {
			ast = parse(String(equation ?? ''), { calls });
		} catch (e) {
			if (e instanceof ParseError) {
				return `${e.message} (at character ${e.position + 1})`;
			}
			throw e;
		}
		const wrongArity = arity(ast);
		if (wrongArity) return wrongArity;
		for (const ref of collectReferences(ast)) {
			// A function's parameters are names in its body and nowhere else.
			// Everything else in a body is a block, read at the top level:
			// see ../sim/functions.js.
			if (locals?.has(ref)) continue;
			const q = resolve(ref);
			// A block may not read its own value -- there is nothing to read
			// until it has been worked out -- except in the one field that
			// is *about* its own value changing: a compartment's dy/dt term,
			// where `-k*C` inside C is the whole point. `self` says so.
			if (q === ownerName && !self) return `'${ref}' refers to itself`;
			if (!q) {
				return `'${ref}' is not a block in this model`
					+ (system ? `, or in '${system}'` : '');
			}
			if (off.has(q) && !off.has(ownerName)) {
				return `'${ref}' is disabled, so it has no value here. Enable it, `
					+ `or disable this block as well`;
			}
			if (called.has(q)) {
				return `'${ref}' is a transport operation read at a position along the `
					+ `chain, so it has no value of its own; call it, as ${ref}${calledHow(q)}`;
			}
			// The element counter has a value only inside its own chain: it
			// is which pair of neighbours is being assembled, and outside the
			// transport there is no pair. See `tr.counterVisibleTo`.
			if (counters.has(q) && !tr.counterVisibleTo(project, q, ownerName)) {
				return `'${ref}' is the element counter of '${parentOf(q)}', and counts the `
					+ 'compartments of that chain: it has a value only inside the transport.';
			}
		}
		return null;
	};
}

/** One equation, checked. For a field that has just been typed in. */
export function validateEquation(project, equation, ownerName, opts = {}) {
	return equationChecker(project)(equation, ownerName, opts);
}

/**
 * Which of a block's fields hold something the parser has to read.
 *
 * Not `VALUE_KEYS`: a parameter's value is a number, a lookup's points are a
 * table, and a transfer's `multiply_by_donor` is a flag -- none of them parse
 * as an expression. The recorders' own fields are already written down in
 * ./recorders.js, so they are taken from there rather than repeated.
 */
const EXPRESSION_FIELDS = {
	compartment: ['initial', 'dydt'],
	function: ['equation'],
	transfer: ['rate'],
	expression: ['equation'],
	inflow: ['rate'],
	index_reduction: ['target'],
	block_reduction: ['targets'],
	...EQUATION_FIELDS,
};

/**
 * The fields that may name their own block. One so far: a compartment's dy/dt
 * term is a statement about how its own value changes, and reads it.
 */
const SELF_READING_FIELDS = { compartment: ['dydt'] };

/**
 * Every equation in the model that will not parse or names something missing.
 *
 * The model-wide half of `validateEquation`, and the reason it is here rather
 * than in a panel: a broken equation used to be reported by a notice that
 * faded after seven seconds and a red border on one field in one panel, so a
 * model could sit there unrunnable with nothing on screen saying why. This is
 * what the workspace strip reads.
 *
 * Both halves of a block's value are checked -- the block-level one and every
 * per-index entry -- because a model whose default is fine and whose Cs-137
 * entry is `0q` is exactly as unrunnable as one with it the other way round.
 *
 * @returns {Array<{name: string, kind: string, field: string, index: object|null,
 *                  message: string}>}
 */
export function allEquationProblems(project, { only = null } = {}) {
	const check = equationChecker(project);
	const out = [];
	for (const collection of KINDS) {
		for (const block of project[collection] ?? []) {
			const name = qualifiedName(block);
			if (only && name !== only) continue;
			// A disabled block may be broken: that is very often why it was
			// disabled. It takes no part in the run, so what is in its boxes
			// is nobody's problem until it is switched on again.
			if (!isEnabled(block)) continue;
			const kind = SINGULAR[collection];
			// A transport's counter and its operations have no equation of
			// their own: the run writes them. What is in the box is nobody's.
			if (kind === 'expression' && ['counter', 'operation'].includes(tr.roleOf(block))) continue;
			for (const field of EXPRESSION_FIELDS[kind] ?? []) {
				const one = (value, index) => {
					// An empty field is not a broken equation: plenty of them
					// are optional, and the ones that are not are caught by
					// the builder with a better message than a parse error.
					if (value == null) return;
					// An aggregate's `targets` is a list of block names rather
					// than one expression, and joining it into a string gives
					// the parser `Regolith,Water` to choke on -- which is how
					// this scan first reported a perfectly good example as
					// broken. Each name is checked on its own.
					if (Array.isArray(value)) {
						for (const item of value) one(item, index);
						return;
					}
					// A value written as a per-nuclide map -- `initial:
					// { 'Cs-137': '1e6' }`, which is how an older file and
					// Ecolego's own exports spell it -- is not an equation.
					// `materialiseLegacyEntries` turns those into entries when
					// the model is opened, and until then there is nothing
					// here to parse: reporting `[object Object]` as a syntax
					// error would be this scan inventing a problem.
					if (typeof value === 'object') return;
					if (String(value).trim() === '') return;
					const message = check(value, name, {
						self: (SELF_READING_FIELDS[kind] ?? []).includes(field),
					});
					if (message) out.push({ name, kind, field, index, message });
				};
				// A function's body is checked in its own scope: its
				// parameters are the only names in it, and an empty one is a
				// function that cannot run -- which is what an import makes
				// of a call whose body could not come across.
				if (kind === 'function') {
					const params = new Set((block.parameters ?? []).map(String));
					const text = String(block.equation ?? '').trim();
					if (!text) {
						out.push({
							name, kind, field, index: null,
							message: `'${name}' has no body yet: write what it works out to`
								+ (params.size ? ` in terms of ${[...params].join(', ')}` : ''),
						});
						continue;
					}
					const message = check(text, name, { locals: params });
					if (message) out.push({ name, kind, field, index: null, message });
					continue;
				}
				one(block[field], null);
				for (const entry of block.entries ?? []) {
					if (Object.prototype.hasOwnProperty.call(entry, field)) {
						one(entry[field], entry.index ?? null);
					}
				}
			}
		}
	}
	return out;
}

/**
 * What is wrong with the simulation settings, by setting.
 *
 * Keyed so a panel can mark the field that is wrong rather than saying
 * something about the model as a whole -- which is the difference between "the
 * model will not run" and a red border on `Rel. tolerance`.
 *
 * The tolerances are the reason this exists. Nothing checked them: `rtol: 0`
 * is a finite number, so the field accepted it, `Project` had no opinion, and
 * the solver then asked for `(0 / err) ** (1 / (k + 1))` as its step-size
 * factor -- which is zero, so it halved the step forever and failed thousands
 * of steps later with a stall, naming neither the setting nor the value.
 *
 * @returns {Array<{key: string, message: string}>}
 */
export function simulationProblems(project) {
	const sim = project?.simulation ?? {};
	const out = [];
	const say = (key, message) => out.push({ key, message });
	const num = (key) => {
		const v = Number(sim[key]);
		return Number.isFinite(v) ? v : null;
	};

	const start = num('start_time');
	const end = num('end_time');
	if (start === null) say('start_time', 'Start time must be a number');
	if (end === null) say('end_time', 'End time must be a number');
	if (start !== null && end !== null && !(end > start)) {
		say('end_time', `End time must be greater than the start time (${sim.start_time})`);
	}
	if ((sim.spacing ?? 'log') === 'log' && start !== null && start < 0) {
		say('start_time', 'Logarithmic output needs a start time of zero or more');
	}

	// How the output times are chosen decides which of these is even a
	// question: a list of series carries its own counts, and the solver's own
	// steps are however many it takes.
	const spacing = sim.spacing ?? 'log';
	if (!SPACINGS.includes(spacing)) {
		say('spacing', `'${spacing}' is not a way of choosing output times`);
	} else if (spacing === 'series') {
		const list = Array.isArray(sim.output_times) ? sim.output_times : [];
		if (!list.length) {
			say('spacing', 'No output series: add one, or choose another spacing');
		}
		// A time outside the run is skipped, not refused -- a time the solver
		// never reaches is not a time it can report, and that is all. A
		// series with nothing inside the run used to be an error here; it is
		// a series that contributes nothing, and the saved-times editor and
		// the sidebar say so (`outsideSeries`). The run's own start and end
		// are always saved, so the grid is never empty.
	} else if (spacing !== 'solver') {
		const points = num('output_points');
		if (points === null || !(points >= 2)) {
			say('output_points', 'At least 2 output points are needed');
		}
	}

	// Both tolerances: strictly greater than zero. A tolerance of zero asks
	// for a perfect answer, which no step can deliver, and a negative one is
	// not a tolerance at all.
	for (const [key, label] of [['rtol', 'Relative'], ['abstol', 'Absolute']]) {
		const v = num(key);
		if (v === null) say(key, `${label} tolerance must be a number`);
		else if (!(v > 0)) say(key, `${label} tolerance must be greater than zero`);
		else if (key === 'rtol' && v >= 1) {
			say(key, 'A relative tolerance of 1 or more asks for no accuracy at all');
		}
	}
	return out;
}

// --- keeping dimensions explicit --------------------------------------------

/**
 * The dimensions a block *currently* has, including the legacy inference.
 *
 * Project applies this rule when a block carries no `index_lists`: if the model
 * has a material list and the block has not opted out with `per_nuclide:false`,
 * it is indexed by that list. That exists so `nuclides: [...]` shorthand
 * models keep working, and it is right for them.
 *
 * It is wrong once index lists are edited in the UI, because a block the user
 * never ticked would silently pick the material list up. Hence
 * makeDimensionsExplicit below.
 */
export function effectiveDims(project, block) {
	if (Array.isArray(block.index_lists)) return [...block.index_lists];
	// A disruptive event acts on whole blocks and is indexed by nothing,
	// however the file spells it -- told by its shape, since a raw block
	// carries no kind.
	if (block && (Object.hasOwn(block, 'actions') || Object.hasOwn(block, 'timing'))) return [];
	// A flux is indexed by the indices its two ends have in common, and that
	// is not a choice -- see `transferDims`. A transfer that says nothing
	// takes them rather than the radionuclides, which is only right for a
	// block that stands on its own.
	const shared = hasEnds(block) ? transferDims(project, block) : null;
	if (shared) return [...shared.dims];
	const name = materialDimensionName(project);
	if (name && block.per_nuclide !== false) return [name];
	return [];
}

/** A block with ends: a transfer, or a source, which is a transfer from outside. */
function hasEnds(block) {
	return !!block && (Object.hasOwn(block, 'from') || Object.hasOwn(block, 'to'));
}

/**
 * What a transfer is indexed by, worked out from the blocks at its two ends.
 *
 * `sharedDims` is the rule; this is what looks the ends up. An end that names
 * no block of this model -- the model boundary, which this tool writes as a
 * null endpoint -- contributes nothing, and the transfer takes the other end's
 * dimensions whole, as the dimension rule does for a source/sink.
 *
 * @returns `{ dims, shared }`, or null when the ends do not correspond and
 *   there is no rule to follow.
 */
export function transferDims(project, block, lists = indexLists(project)) {
	const endDims = (name) => {
		if (name == null) return null;
		const found = findBlock(project, name);
		if (!found || !HOLDS_INVENTORY.has(found.kind)) return null;
		// Its own dimensions, never this rule again: a transfer's end is a
		// compartment or a path, and neither is a connection.
		if (Array.isArray(found.block.index_lists)) return [...found.block.index_lists];
		const material = materialDimensionName(project, lists);
		return material && found.block.per_nuclide !== false ? [material] : [];
	};
	return sharedDims(lists, endDims(block.from ?? null), endDims(block.to ?? null));
}

/** The kinds a flux can run between: the ones that hold an inventory. */
const HOLDS_INVENTORY = new Set(['compartment', 'farfield', 'waste_package']);

/**
 * The compartment a transport stands for at one end of a connection.
 *
 * A transport is drawn as one block, and a line drawn to it or from it means
 * the obvious thing: what flows *in* arrives at the head of the chain, its
 * Begin, and what flows *out* leaves the tail, its End. So a connection may
 * name the transport itself and this says which compartment it meant --
 * `addTransfer`, `addSource` and `setConnectionEnd` all ask. Anything that is
 * not a transport is handed back as it came, so the callers need no branch.
 *
 * @param {'from'|'to'} end which end of the connection the name is at
 */
export function transportEndpoint(project, name, end) {
	if (name == null || !tr.isTransport(project, name)) return name;
	const parts = tr.transportParts(project, name);
	const part = end === 'from' ? parts.end : parts.begin;
	if (!part) {
		throw new EditError(
			`'${name}' has no ${end === 'from' ? 'End' : 'Begin'} compartment, so there is `
			+ `nothing in it to connect ${end === 'from' ? 'from' : 'to'}.`,
		);
	}
	return qualifiedName(part);
}

/**
 * What each end of a flux would have to be added up over, end by end.
 *
 * The editor's way in to `summedDims`, which is the rule. A transfer or source
 * carrying a dimension the compartment at one of its ends has not got reaches
 * that end's one cell from every index of it: a total on the way in, or a
 * donor drawn down once per index. Ecolego refuses the shape outright;
 * this tool allows it where the flux says
 * `sum_extra_indices`, and the settings dialog offers the tick exactly when
 * this answers with something.
 *
 * @returns {Array<{end: 'from'|'to', name: string, dims: string[]}>}
 */
export function summedFluxDims(project, block, lists = indexLists(project)) {
	if (!block || !hasEnds(block)) return [];
	const fluxDims = effectiveDims(project, block);
	const out = [];
	for (const end of ['from', 'to']) {
		const name = block[end] ?? null;
		if (name == null) continue;
		const found = findBlock(project, name);
		if (!found || !HOLDS_INVENTORY.has(found.kind)) continue;
		const dims = summedDims(lists, fluxDims, effectiveDims(project, found.block));
		if (dims.length) out.push({ end, name, dims });
	}
	return out;
}

/**
 * Why a flux that sums will not build until it says it means to, or null.
 *
 * The same sentence `Project` refuses with, so that the editor's warning and
 * the problem strip are one wording rather than two. Null once the flux says
 * `sum_extra_indices`, which is the modeller answering the question.
 */
export function summedFluxWhy(project, block, lists = indexLists(project)) {
	if (!block || block.sum_extra_indices) return null;
	const [first] = summedFluxDims(project, block, lists);
	if (!first) return null;
	const sizeOf = (name) => {
		const list = lists.find((l) => l.name === name);
		if (!list) return null;
		return (list.indices ?? []).filter(
			(i) => typeof i === 'string' || i?.enabled !== false,
		).length || null;
	};
	return summedDimsWhy({
		flux: block.name, end: first.end, endName: first.name, dims: first.dims, sizeOf,
	});
}

/**
 * The outside ends of a transport: what feeds its Begin, and what its End
 * delivers to.
 *
 * Every connection touching Begin or End whose other end is not itself in the
 * chain -- a compartment upstream, a compartment downstream, a far-field path
 * either way, and the flows back the other way as well. The model boundary
 * (a null end, or a source term) is not an end: it has no dimensions to
 * contribute, exactly as `sharedDims` treats a transfer to outside.
 *
 * @returns {{from: string[], to: string[]}} qualified names, donors first
 */
export function transportEnds(project, path) {
	const parts = tr.transportParts(project, path);
	// In the chain: directly in the transport, which holds no sub-system.
	const inside = (name) => {
		const found = name == null ? null : findBlock(project, name);
		return !!found && systemOf(found.block) === path;
	};
	const heads = new Set([parts.begin, parts.end].filter(Boolean).map(qualifiedName));
	const from = [];
	const to = [];
	for (const t of project.transfers ?? []) {
		if (t.to != null && heads.has(t.to) && t.from != null && !inside(t.from)) from.push(t.from);
		if (t.from != null && heads.has(t.from) && t.to != null && !inside(t.to)) to.push(t.to);
	}
	return { from: [...new Set(from)], to: [...new Set(to)] };
}

/**
 * What a transport is indexed by, worked out from what it is connected to.
 *
 * The same rule a transfer follows, applied to the chain as a whole: the chain
 * is one compartment repeated, it sits between what feeds it and what it
 * delivers to, and its indices are the ones those have in common -- paired by
 * root, narrowed to a sub-set where one end is one, and dropped where an end
 * has no dimension of that root at all. A chain fed per nuclide and object
 * that delivers to a compartment per nuclide is a chain per nuclide, and the
 * inflow into it is then the one flux that sums, which its own row says. A
 * transport connected at one end only takes that end's dimensions whole; one
 * connected to nothing has nothing to inherit and keeps what it says, which is
 * what `addTransport` gave it.
 *
 * Ecolego does not derive this: `TransportBegin.setIndexLists` pushes Begin's
 * choice to End and the operations and stops there, and the modeller keeps
 * the ends in step by hand.
 *
 * @returns `{ dims, shared, from, to }`, or null when there is nothing to
 *   inherit, or two ends are sub-sets of one root that merely overlap -- an
 *   intersection no list of the model names, which `sharedDims` refuses too.
 */
export function transportDims(project, path, lists = indexLists(project)) {
	const ends = transportEnds(project, path);
	const names = [...ends.from, ...ends.to];
	if (!names.length) return null;
	const dimsOf = (name) => {
		const found = findBlock(project, name);
		if (!found || !HOLDS_INVENTORY.has(found.kind)) return null;
		return effectiveDims(project, found.block);
	};
	let acc = null;
	const shared = [];
	for (const name of names) {
		const d = dimsOf(name);
		if (d == null) return null;
		if (acc == null) { acc = d; continue; }
		const s = commonDims(lists, acc, d);
		if (!s) return null;
		acc = s.dims;
		shared.push(...s.shared);
	}
	return { dims: acc ?? [], shared, from: ends.from, to: ends.to };
}

/**
 * The dimensions two blocks have in common, by root: `sharedDims` without its
 * refusal of ends of different dimension. A root only one of them carries is
 * left out rather than refused, because this is asked about a chain between
 * two compartments, not about a flux -- the flux between them will say what
 * it sums over, on its own row. Null only where a root's two sub-sets merely
 * overlap, which no list of the model names.
 *
 * @returns `{ dims, shared }` in `a`'s order
 */
function commonDims(lists, a, b) {
	const all = lists ?? [];
	const plain = (dims) => (dims ?? []).filter((d) => !all.find((l) => l.name === d)?.for_scenarios);
	const rootOf = (name) => lineage(all, name).root;
	const dims = [];
	const shared = [];
	const rest = plain(b);
	for (const s of plain(a)) {
		const at = rest.findIndex((t) => rootOf(t) === rootOf(s));
		if (at < 0) continue;
		const [t] = rest.splice(at, 1);
		if (s === t) { dims.push(s); continue; }
		const ls = all.find((l) => l.name === s);
		const lt = all.find((l) => l.name === t);
		const narrower = ls?.sub_set_of === t ? s : lt?.sub_set_of === s ? t : null;
		if (!narrower) return null;
		dims.push(narrower);
		shared.push({ from: s, to: t, dims: narrower });
	}
	return { dims, shared };
}

/**
 * Gives every transport the dimensions its connections imply -- see
 * `transportDims` -- and its End and operations Begin's, as
 * `TransportBegin.setIndexLists` does. A narrowing the model states is kept,
 * on the same rule `syncTransferDimensions` keeps it for a flux.
 *
 * @returns the names of the blocks it changed
 */
export function syncTransportInheritance(project, lists = indexLists(project)) {
	const changed = [];
	for (const path of tr.transportPaths(project)) {
		const parts = tr.transportParts(project, path);
		if (!parts.begin) continue;
		const inherited = transportDims(project, path, lists);
		if (!inherited) continue;
		const have = effectiveDims(project, parts.begin);
		if (sameList(have, inherited.dims)) continue;
		if (narrows(project, have, inherited.dims, lists)) continue;
		parts.begin.index_lists = [...inherited.dims];
		pruneEntriesToDims(parts.begin, inherited.dims);
		changed.push(qualifiedName(parts.begin));
		changed.push(...syncTransportDims(project, parts.begin, inherited.dims));
	}
	return changed;
}

/**
 * Keeps every flux's dimensions in step with the blocks at its ends.
 *
 * The equivalent of Ecolego's the dimension rule, which listens to
 * both ends and re-derives whenever either changes its index lists. Here there
 * is one pass after each edit instead of a listener per transfer, for the same
 * reason the units have one: it covers every way an edit can reach a model,
 * including the matrix editor and the JSON tab.
 *
 * **A narrower dimension that the model states is kept.** A transfer may be
 * written over a sub-set of what its ends share -- a loss that only applies to
 * the wetland objects, say -- and that is a real thing to want and a thing
 * this tool can express where Ecolego cannot. What is replaced is a dimension
 * that no longer follows from the ends at all, which is what a stale one is:
 * an endpoint was changed, or moved onto another list, and the flux was left
 * pointing at a dimension neither end has.
 *
 * @returns the names of the fluxes it re-derived
 */
export function syncTransferDimensions(project) {
	const changed = [];
	// The index lists once, not once per transfer: deriving the two block
	// lists builds an index per compartment and per transfer, and doing that
	// 4,600 times over a 4,600-transfer model was a quarter of a second after
	// every keystroke.
	const lists = indexLists(project);
	// The chains first: a transport takes its dimensions from what it is
	// connected to, and the transfers to and from it then take theirs from
	// the chain, so the order is the order of the dependency.
	changed.push(...syncTransportInheritance(project, lists));
	for (const collection of ['transfers', 'inflows']) {
		for (const block of project[collection] ?? []) {
			const shared = transferDims(project, block, lists);
			// The ends do not correspond -- a flux into a block of fewer
			// dimensions, which is a reduction and this tool's own. There is
			// no rule to apply, so what the model says stands.
			if (!shared) continue;
			if (!Array.isArray(block.index_lists)) continue;
			if (narrows(project, block.index_lists, shared.dims, lists)) continue;
			block.index_lists = [...shared.dims];
			changed.push(block.name);
		}
	}
	return changed;
}

/**
 * Whether `dims` is `derived` itself, or the same dimensions narrowed.
 *
 * A narrowing keeps every dimension and takes a sub-set of some of them --
 * `[Radionuclides, Wetland]` where the ends share `[Radionuclides, Object]`.
 * *Dropping* one is not a narrowing but a reduction, and a flux with no
 * dimensions at all is not a deliberate anything: reading an empty list as a
 * narrowing of everything left every scalar flux scalar, whatever happened to
 * the compartments at its ends.
 */
function narrows(project, dims, derived, lists = indexLists(project)) {
	if (dims.length !== derived.length) return false;
	return dims.every((d) => derived.some((w) => d === w
		|| lists.find((l) => l.name === d)?.sub_set_of === w));
}

/**
 * The name of the radionuclide dimension, accounting for both forms it can
 * take: an index list flagged `for_nuclides`, or the older `nuclides: [...]`
 * shorthand, which Project desugars into a list of exactly this name.
 *
 * The radionuclides and not the catalogue around them, because this answers
 * "what is a block per, when nothing says" -- and a new compartment is per
 * radionuclide. A model that carries stable carbon or a population of rabbits
 * beside its nuclides says so by indexing that compartment by the catalogue,
 * which is a choice rather than a default.
 *
 * Reading only the explicit lists would return nothing for a shorthand file,
 * and writing that down would quietly strip the nuclide dimension from every
 * block in it.
 */
/**
 * Every dimension that holds materials: the catalogue, the radionuclides, and
 * a model's own selection out of either.
 *
 * A compartment on any of them holds an inventory, so any of them settles the
 * unit -- and a model that keeps `Mobile` out of its radionuclides indexes
 * compartments by that. Asking for one name labelled those with nothing.
 */
export function materialDimensionNames(project) {
	const lists = indexLists(project);
	const root = lists.find((l) => l.for_contaminants)?.name ?? null;
	if (!root) {
		const name = materialDimensionName(project);
		return name ? [name] : [];
	}
	return lists
		.filter((l) => l.indices?.length && isDecayDim(lists, l.name, root))
		.map((l) => l.name);
}

export function materialDimensionName(project, lists = indexLists(project)) {
	// The radionuclides, or the catalogue when there are none: a model whose
	// materials do not decay -- Lotka-Volterra's rabbits and foxes, a lake's
	// stable carbon -- keeps them all in the catalogue and its radionuclide
	// list is empty.
	const nuclides = lists.find((l) => l.for_nuclides);
	const explicit = nuclides?.indices?.length ? nuclides : materialList(project);
	// An empty material dimension is not a dimension. Both are always there
	// now, and a model with nothing in either is a plain compartment model:
	// giving its blocks a zero-width dimension would leave them with no values
	// at all.
	if (explicit) return explicit.indices.length ? explicit.name : null;
	if ((project.nuclides ?? []).length) return NUCLIDE_LIST;
	return null;
}

/**
 * `nuclides: [...]` is sugar for an index list, and Project desugars it on
 * load -- but the editor works on the raw object, so a shorthand model would
 * show no index lists to edit. Materialise it once, on the way in, so there is
 * only one representation in front of the user.
 *
 * Here rather than in the editor shell because it is not a question about the
 * interface: it is the one shape every other function in this file expects a
 * model to be in, and importing blocks out of a file needs that shape as much
 * as opening one does.
 */
export function materialiseShorthand(raw) {
	if (raw.nuclides?.length
		&& !(raw.index_lists ?? []).some((l) => l.for_contaminants || l.for_nuclides)) {
		// Both of them: the shorthand names radionuclides, and every one of
		// them is a material, so the catalogue starts out holding the same
		// names. See `desugarNuclides`, which does this on the read side.
		const indices = raw.nuclides.map((n) => ({ name: n, enabled: true }));
		raw.index_lists = [
			{
				name: MATERIAL_LIST_NAME,
				for_contaminants: true,
				indices: indices.map((i) => ({ ...i })),
			},
			{
				name: NUCLIDE_LIST_NAME,
				for_nuclides: true,
				sub_set_of: MATERIAL_LIST_NAME,
				indices,
			},
			...(raw.index_lists ?? []),
		];
	}

	// Per-nuclide value maps and the older `default` key become entries and
	// plain values, so the editor and the engine read the same thing. Without
	// this, a model's real per-index values are invisible in the interface --
	// examples/biosphere.json is written that way.
	materialiseLegacyEntries(raw);

	// The two material dimensions are built in: every model has them, so make
	// sure they are there before anything reads the model's shape.
	ensureMaterialLists(raw);

	// Connection endpoints are stored as qualified names, so nothing in the
	// editor has to scope a comparison. See qualifyEndpoints.
	qualifyEndpoints(raw);

	// Write every block's dimensions down, whichever form the file used.
	//
	// Project infers a missing `index_lists` as "the material list, unless
	// per_nuclide is false". That is right for a file written in the shorthand,
	// but it means a block the editor shows as un-indexed can be per-nuclide
	// in the engine -- the two disagree, and results carry an index the user
	// never asked for. Making it explicit on load removes the divergence
	// without changing what any existing file means.
	makeDimensionsExplicit(raw);
}

/**
 * Writes down every block's current dimensions.
 *
 * Called before any change to the index-list model, so that change cannot
 * alter what a block is indexed by. Because the dims written are the ones in
 * force at the time, this is semantics-preserving by construction: creating a
 * radionuclide list no longer reaches back and makes every existing block
 * per-nuclide.
 */
export function makeDimensionsExplicit(project) {
	for (const kind of KINDS) {
		for (const block of project[kind] ?? []) {
			block.index_lists = effectiveDims(project, block);
			delete block.per_nuclide;
		}
	}
	return project;
}

/**
 * Dimensions to give a newly created block.
 *
 * A model with radionuclides almost always wants a new compartment, transfer
 * or expression to hold one value per nuclide -- and a transfer between
 * per-nuclide compartments has to be, or the build cannot resolve it.
 * Parameters are the exception: most are a single value shared across
 * nuclides, and so is a lookup table -- a measured series is a property of the
 * place, not of the nuclide in it. Either way it is one tick to change.
 */
export function defaultDimsFor(project, kind) {
	if (kind === 'parameter' || kind === 'lookup') return [];
	const name = materialDimensionName(project);
	return name ? [name] : [];
}

// --- appearance -------------------------------------------------------------

/** Node shapes the diagram can draw. */
export const SHAPES = ['rounded', 'rect', 'ellipse', 'hexagon', 'cylinder', 'diamond'];

/**
 * The shape each kind of block gets when it has none of its own.
 *
 * This is the single source of truth for that. It used to be duplicated in the
 * graph editor while `setBlockShape` treated 'rounded' as "store nothing"
 * regardless of kind -- so choosing Rounded box for a parameter deleted the
 * key and the hexagon default came straight back, and the inspector displayed
 * 'rounded' for a block it was drawing as a hexagon.
 */
export const DEFAULT_SHAPE = {
	compartment: 'rounded',
	expression: 'rounded',
	parameter: 'hexagon',
	lookup: 'rect',
	index_reduction: 'rounded',
	block_reduction: 'rounded',
	// A function is called rather than read, and the brackets on its label
	// say so; the shape is an expression's, which is what it is.
	function: 'rounded',
	// The blocks that remember are drawn apart from the flow: a recorder is a
	// meter on the model, and a discrete event is an instant rather than a
	// quantity, which is what the diamond says.
	min_max: 'rect',
	running_mean: 'rect',
	snapshot: 'rect',
	delay: 'cylinder',
	trigger: 'diamond',
	// A path holds inventory like a compartment, but a great deal of it and in
	// a structure of its own, so it is drawn as a squarer box than a
	// compartment rather than as another rounded one.
	farfield: 'rect',
	waste_package: 'rect',
	event: 'diamond',
	inflow: 'rounded',
	transfer: 'rounded',
};

export function defaultShapeFor(kind) {
	return DEFAULT_SHAPE[kind] ?? 'rounded';
}

/** The shape a block is actually drawn with. */
export function blockShape(project, blockName, kind = null) {
	const found = findBlock(project, blockName);
	if (!found) return defaultShapeFor(kind);
	return found.block.shape ?? defaultShapeFor(kind ?? found.kind);
}

/** Default box size per kind of block, in diagram units. */
export const DEFAULT_SIZE = {
	compartment: { w: 136, h: 54 },
	farfield: { w: 152, h: 58 },
	waste_package: { w: 152, h: 58 },
	event: { w: 140, h: 56 },
	expression: { w: 136, h: 54 },
	parameter: { w: 120, h: 44 },
	lookup: { w: 132, h: 54 },
	index_reduction: { w: 136, h: 54 },
	block_reduction: { w: 136, h: 54 },
	// Wider: the label carries the signature, `TR_adv(LAI, leaf_width)`.
	function: { w: 148, h: 54 },
	min_max: { w: 136, h: 54 },
	running_mean: { w: 136, h: 54 },
	snapshot: { w: 136, h: 54 },
	delay: { w: 128, h: 54 },
	trigger: { w: 130, h: 54 },
	inflow: { w: 120, h: 44 },
	transfer: { w: 120, h: 44 },
	// A sub-system stands for everything inside it, so it is drawn larger.
	system: { w: 168, h: 62 },
};

export const MIN_SIZE = { w: 60, h: 32 };
export const MAX_SIZE = { w: 520, h: 320 };

/** Which kinds of block are drawn as nodes on the diagram. */
export const NODE_KINDS = [
	'compartment', 'expression', 'parameter', 'lookup',
	'index_reduction', 'block_reduction', 'function',
	'min_max', 'running_mean', 'snapshot', 'delay', 'trigger',
	'farfield', 'waste_package', 'event',
];

/** Whether a block takes part in the run, by its own switch alone. Absent means it does. */
export function isEnabled(block) {
	return block?.enabled !== false;
}

/** The sub-systems switched off, as paths. */
export function disabledSystems(project) {
	return [...(project?.disabled_systems ?? [])]
		.map((p) => String(p ?? '').trim()).filter(Boolean);
}

/**
 * Whether a sub-system takes part in the run: neither it nor any sub-system
 * around it is switched off. The top level always does.
 */
export function isSystemEnabled(project, path) {
	if (!path) return true;
	return !disabledSystems(project).some((p) => isWithin(path, p));
}

/**
 * The sub-system that keeps a block out of the run, or null.
 *
 * The outermost one, since that is the switch a reader would have to find:
 * a block in `NF.Inner` with `NF` off is off because of `NF`, whatever
 * `NF.Inner` says about itself.
 */
export function disablingSystem(project, block) {
	const home = systemOf(block);
	if (!home) return null;
	const off = disabledSystems(project).filter((p) => isWithin(home, p));
	if (!off.length) return null;
	return off.sort((a, b) => a.length - b.length)[0];
}

/**
 * Whether a block takes part in the run, counting the sub-systems around it.
 *
 * Ecolego's `SubSystemBlock implements IBlock`: a sub-system is a block, with
 * a block's switch, and switching one off takes everything inside with it.
 * This is the question the diagram, the tree and the Information view ask
 * about every block; `isEnabled` is only the block's own answer.
 */
export function isEffectivelyEnabled(project, block) {
	return isEnabled(block) && isSystemEnabled(project, systemOf(block));
}

/**
 * The qualified names of every block that is switched off -- by its own
 * switch, or by a sub-system around it.
 */
export function disabledNames(project) {
	return new Set(allBlocks(project)
		.filter((b) => !isEffectivelyEnabled(project, b)).map(qualifiedName));
}

/**
 * Switches a whole sub-system on or off.
 *
 * Off, every block in it and every sub-system inside it is left out of the
 * run, and the run reads exactly as it would with each of them switched off
 * by hand -- a transfer out of one is off with it, one into it delivers to the
 * boundary, and nothing enabled may read any of them. What differs is that
 * the blocks keep their own switches: turning the sub-system back on returns
 * it to exactly what it was, including any block that was off on its own.
 *
 * Kept as a list of paths beside `transports`, for the same reason: a
 * sub-system is a path its blocks wear, and has nowhere else to carry a flag.
 */
export function setSystemEnabled(project, path, on) {
	if (!path || !systems(project).includes(path)) {
		throw new EditError(`No sub-system named '${path}'`);
	}
	const off = disabledSystems(project).filter((p) => p !== path);
	if (!on) off.push(path);
	if (off.length) project.disabled_systems = off;
	else delete project.disabled_systems;
	return isSystemEnabled(project, path);
}

/**
 * The connections a disabled compartment takes with it, and why.
 *
 * Ecolego's rule: a transfer whose donor is
 * disabled is disabled with it, since there is no inventory for it to move; a
 * source term into a disabled compartment has nothing to feed. A transfer
 * *into* a disabled compartment stays on, and what it moves leaves the model
 * -- which is also worth saying, so it is here under the key `name#to`. The
 * same rule `Project._followDisabledEnds` applies when the model is built,
 * read off the raw model so the diagram and the Information view can show it.
 *
 * @returns {Map<string, string>} qualified name -> the reason, in words
 */
export function implicitlyDisabled(project) {
	const off = disabledNames(project);
	const out = new Map();
	if (!off.size) return out;
	// A block that is off because the sub-system around it is: not its own
	// doing, so it is said, and by the sub-system that did it.
	for (const b of allBlocks(project)) {
		if (!isEnabled(b)) continue;
		const by = disablingSystem(project, b);
		if (by) out.set(qualifiedName(b), `it is in '${by}', which is disabled`);
	}
	const ends = new Set([
		...(project.compartments ?? []), ...(project.farfields ?? []), ...(project.waste_packages ?? []),
	].map(qualifiedName));
	const endOf = (conn, key) => {
		const ref = conn[key];
		if (ref == null) return null;
		return ends.has(ref) ? ref : resolveReference(ref, systemOf(conn), (n) => ends.has(n)) ?? ref;
	};
	for (const t of project.transfers ?? []) {
		if (!isEnabled(t)) continue;
		const from = endOf(t, 'from');
		const to = endOf(t, 'to');
		if (from != null && off.has(from)) {
			out.set(qualifiedName(t), `its donor '${from}' is disabled, so there is no inventory for it to move`);
		} else if (to != null && off.has(to)) {
			out.set(`${qualifiedName(t)}#to`, `it flows into '${to}', which is disabled, so what it moves leaves the model`);
		}
	}
	for (const src of project.inflows ?? []) {
		if (!isEnabled(src)) continue;
		const to = endOf(src, 'to');
		if (to != null && off.has(to)) {
			out.set(qualifiedName(src), `it flows into '${to}', which is disabled, so there is nothing for it to feed`);
		}
	}
	return out;
}

/**
 * Switches a block on or off.
 *
 * Ecolego's `enabled`, on every block: off, it stays in the model with its
 * equations and its values and is left out when the model is built. That is
 * what lets a model with a broken block in it run -- as long as nothing that
 * is still on reads the broken one, which the builder and the problem scan
 * both say by name. Written as `enabled: false` only; on is the absence of
 * the key, so a file that has never heard of it reads the same.
 */
export function setBlockEnabled(project, blockName, on) {
	const found = findBlock(project, blockName);
	if (!found) throw new EditError(`No block named '${blockName}'`);
	if (on) delete found.block.enabled;
	else found.block.enabled = false;
	return found.block;
}

export function setBlockColor(project, blockName, color) {
	const found = findBlock(project, blockName);
	if (!found) throw new EditError(`No block named '${blockName}'`);
	if (color == null || color === '') delete found.block.color;
	else found.block.color = color;
	return found.block;
}

/** The widths a connection's line may be drawn at, in model units. */
export const EDGE_WIDTHS = [1, 1.8, 2.6, 4];

/**
 * How a connection's line is drawn, with the defaults filled in.
 *
 * A transfer used to take its whole appearance from its endpoints, which is
 * right until a model has thirty of them: then telling one route from another
 * is what the drawing is for, and a colour, a weight and a dash are the three
 * things a line has to say it with. The vocabulary is the one the canvas
 * shapes already use -- `line_width` and `dash`, the same keys and the same
 * three dash names -- so the file format has one way of describing a line.
 *
 * Read through here by both the diagram and the transfer grid, so the two
 * cannot disagree about what a connection looks like. Nothing is written to
 * the block: a connection with no appearance of its own keeps `null`, and the
 * renderer falls back to the theme.
 */
export function connectionLook(conn) {
	const color = String(conn?.color ?? '').trim();
	const width = Number(conn?.line_width);
	const dash = SHAPE_DASHES.includes(conn?.dash) ? conn.dash : null;
	return {
		color: color || null,
		// Bounded rather than refused on read: a width out of a file is not a
		// reason to fail to draw the model.
		width: Number.isFinite(width) && width > 0
			? Math.min(12, Math.max(0.25, width))
			: null,
		dash: dash === 'solid' ? null : dash,
	};
}

/**
 * Sets how a connection's line is drawn. Unknown keys are refused, not stored.
 *
 * Null or the default clears the override, which is the same thing: a
 * connection with none follows the theme, and writing the default into the
 * file would only make it look edited.
 */
export function setConnectionLook(project, name, patch = {}) {
	const found = findBlock(project, name);
	if (!found) throw new EditError(`No connection named '${name}'`);
	if (found.kind !== 'transfer' && found.kind !== 'inflow') {
		throw new EditError(`'${name}' is not a connection`);
	}
	const conn = found.block;
	for (const [key, value] of Object.entries(patch)) {
		if (key === 'color') {
			if (value == null || value === '') delete conn.color;
			else conn.color = String(value);
			continue;
		}
		if (key === 'line_width') {
			const n = Number(value);
			if (value == null || value === '') { delete conn.line_width; continue; }
			if (!Number.isFinite(n) || !(n > 0)) {
				throw new EditError(`'${value}' is not a line width`);
			}
			conn.line_width = Math.min(12, Math.max(0.25, n));
			continue;
		}
		if (key === 'dash') {
			if (value == null || value === '' || value === 'solid') {
				delete conn.dash;
				continue;
			}
			if (!SHAPE_DASHES.includes(value)) {
				throw new EditError(`'${value}' is not a line style`);
			}
			conn.dash = value;
			continue;
		}
		throw new EditError(`A connection's appearance has no '${key}'`);
	}
	return conn;
}

/**
 * Sets a block's shape. Passing null, or the default for that block's kind,
 * clears the override -- which is the same thing, since the fallback *is* that
 * default. Any other shape is stored.
 */
export function setBlockShape(project, blockName, shape) {
	const found = findBlock(project, blockName);
	if (!found) throw new EditError(`No block named '${blockName}'`);

	if (shape == null || shape === '') {
		delete found.block.shape;
		return found.block;
	}
	if (!SHAPES.includes(shape)) {
		throw new EditError(`'${shape}' is not a shape (${SHAPES.join(', ')})`);
	}
	if (shape === defaultShapeFor(found.kind)) delete found.block.shape;
	else found.block.shape = shape;
	return found.block;
}

/**
 * A block's format, for Copy format: how it looks, and nothing it does.
 *
 * A node's colour and shape; a connection's colour, weight and dash. The
 * shape is the one it is drawn with, its kind's when it has none of its own:
 * a shape is the same in every theme, and a parameter's hexagon pasted onto a
 * compartment is what the reader saw and asked for. A colour it has not set
 * is copied as not set -- `null` -- rather than as the colour it happens to be
 * drawn in, because a kind's colour is the theme's and changes with it, and
 * pasting it as a fixed value would pin the targets to one theme.
 *
 * @returns {{kind: 'node'|'line', from: string, color: string|null,
 *   shape?: string|null, line_width?: number|null, dash?: string|null}|null}
 */
export function formatOf(project, name) {
	const found = findBlock(project, name);
	if (!found) return null;
	if (NODE_KINDS.includes(found.kind)) {
		return {
			kind: 'node',
			from: name,
			color: found.block.color ?? null,
			shape: blockShape(project, name, found.kind),
		};
	}
	if (found.kind === 'transfer' || found.kind === 'inflow') {
		const look = connectionLook(found.block);
		return { kind: 'line', from: name, color: look.color, line_width: look.width, dash: look.dash };
	}
	return null;
}

/**
 * Puts a copied format on blocks, as much of it as each can take: the colour
 * on anything with one, the shape on a node, the weight and the dash on a
 * connection. A node's shape copied onto a connection is not a shape it can
 * have, and is left out rather than refused, so one paste onto a mixed
 * selection does what it can for every block in it.
 *
 * @returns {string[]} the blocks it changed
 */
export function applyFormat(project, names, format) {
	if (!format) return [];
	const changed = [];
	for (const name of names) {
		const found = findBlock(project, name);
		if (!found || name === format.from) continue;
		const before = JSON.stringify([found.block.color, found.block.shape, found.block.line_width, found.block.dash]);
		if (NODE_KINDS.includes(found.kind)) {
			setBlockColor(project, name, format.color);
			if (format.kind === 'node' && format.shape) setBlockShape(project, name, format.shape);
		} else if (found.kind === 'transfer' || found.kind === 'inflow') {
			setConnectionLook(project, name, format.kind === 'line'
				? { color: format.color, line_width: format.line_width, dash: format.dash }
				: { color: format.color });
		} else {
			continue;
		}
		const after = JSON.stringify([found.block.color, found.block.shape, found.block.line_width, found.block.dash]);
		if (after !== before) changed.push(name);
	}
	return changed;
}

/** The size a block is drawn at: its own, or the default for its kind. */
export function blockSize(project, blockName, kind) {
	const pos = project.layout?.[blockName];
	const base = DEFAULT_SIZE[kind] ?? DEFAULT_SIZE.compartment;
	return {
		w: pos?.w ?? base.w,
		h: pos?.h ?? base.h,
	};
}

/**
 * Resizes a block. Size lives in the layout beside the position, since it is
 * presentation rather than model, and is clamped so a node cannot be dragged
 * away to nothing.
 */
export function setBlockSize(project, blockName, { w, h }) {
	layoutOf(project);
	const entry = project.layout[blockName] ?? { x: 0, y: 0 };
	if (w != null) {
		entry.w = Math.round(Math.min(MAX_SIZE.w, Math.max(MIN_SIZE.w, w)));
	}
	if (h != null) {
		entry.h = Math.round(Math.min(MAX_SIZE.h, Math.max(MIN_SIZE.h, h)));
	}
	project.layout[blockName] = entry;
	return entry;
}

/** Drops an explicit size, returning the block to its default. */
export function clearBlockSize(project, blockName) {
	const entry = project.layout?.[blockName];
	if (!entry) return;
	delete entry.w;
	delete entry.h;
}

// --- which results are saved ------------------------------------------------

/**
 * The blocks this model is set up to save: Ecolego's **endpoints**.
 *
 * `<outputs><output id="..."/></outputs>` in its simulation settings, which
 * `JavaSimulator` writes a result series for and for nothing else. This tool
 * keeps every series a run produces -- they are worked out from the states on
 * request -- so the list decides nothing about the run. It decides what an
 * export offers, which on a model of eight hundred thousand series is the
 * difference between a file you can open and one you cannot.
 *
 * Names of blocks, in the order they were chosen. A name with no block behind
 * it is dropped here rather than at the file gate: a block can be deleted
 * after it was made an endpoint, and that is not a broken model.
 *
 * **Not every result is named after a block.** A far-field path reports the
 * inventory it holds as `Rock held` and its cells as `Rock.gravel1` -- names a
 * run makes up, since the path is one block and its contents are hundreds of
 * series (see `farfieldOutputs` in ../sim/runner.js). Those are worth choosing
 * and were being dropped on the way back in, so a choice of them did not
 * survive reopening the picker. A name counts when a real block is at the
 * front of it, at a boundary.
 *
 * **A parameter is not one, nor a lookup table** (`canBeEndpoint`). An
 * Ecolego list often names parameters, and they are left in the file as it
 * said them and skipped here.
 */
export function endpoints(project) {
	const list = project?.simulation?.endpoints;
	if (!Array.isArray(list)) return [];
	const kindOf = new Map(allBlocks(project).map((b) => [qualifiedName(b), b.kind]));
	const derived = (name) => {
		for (const cut of [name.lastIndexOf(' '), name.lastIndexOf('.')]) {
			if (cut > 0 && kindOf.has(name.slice(0, cut))) return true;
		}
		return false;
	};
	return list.map((n) => String(n))
		.filter((n) => (kindOf.has(n) ? canBeEndpoint(kindOf.get(n)) : derived(n)));
}

/**
 * Whether a block of this kind can be an endpoint: anything but an input --
 * a parameter or a lookup table.
 *
 * An endpoint is a result a run is asked to keep, and an input is not a
 * result. A parameter is a constant: one number in a deterministic run, and
 * in a probabilistic one the number each realisation drew. A lookup table is
 * the same thing at a list of times: each point that carries a spread is drawn
 * once per realisation, like one index of a parameter. A probabilistic run
 * keeps every input it varies as its draws, whatever the list says (see
 * `inputs` in ../sim/probabilistic.js). Offering them made the list mostly
 * inputs on an imported assessment, and priced a run for thousands of curves
 * that are one number each.
 */
export function canBeEndpoint(kind) {
	return kind !== 'parameter' && kind !== 'lookup';
}

/**
 * Sets it. Returns whether anything changed, so a caller need not decide.
 *
 * An empty list is removed rather than stored: a model with no endpoints and
 * a model that has never been asked are the same model, and a `"endpoints": []`
 * in the file would say otherwise.
 */
export function setEndpoints(project, names) {
	if (!project.simulation) project.simulation = {};
	const sim = project.simulation;
	const before = Array.isArray(sim.endpoints) ? sim.endpoints : [];
	const seen = new Set();
	const out = [];
	for (const n of names ?? []) {
		const name = String(n);
		if (!name || seen.has(name)) continue;
		seen.add(name);
		out.push(name);
	}
	if (before.length === out.length && before.every((n, i) => n === out[i])) return false;
	if (out.length) sim.endpoints = out;
	else delete sim.endpoints;
	return true;
}

// --- when results are saved -------------------------------------------------

/**
 * The series the output grid is built from.
 *
 * Live objects, so the editor can change one in place -- but read through
 * here, because a hand-written file may leave a series half-written and the
 * panel should show what the engine will make of it rather than what was
 * typed.
 */
export function outputSeries(project) {
	const list = project?.simulation?.output_times;
	return Array.isArray(list) ? list : [];
}

/** The times those series come to, combined: what a run will actually save. */
export function outputTimes(project) {
	const sim = project?.simulation ?? {};
	return combineSeries(outputSeries(project), Number(sim.start_time ?? 0),
		Number(sim.end_time ?? 0));
}

/**
 * Changes how the output times are chosen.
 *
 * Moving to `series` seeds the list from the shorthand that was in force, so
 * the first thing shown is the grid the model already had rather than an empty
 * editor -- and the second series, the one for the first year, is then an
 * addition to something recognisable.
 */
export function setSpacing(project, spacing) {
	if (!SPACINGS.includes(spacing)) {
		throw new EditError(
			`'${spacing}' is not a way of choosing output times `
			+ `(${SPACINGS.join(', ')})`,
		);
	}
	if (!project.simulation) project.simulation = {};
	const sim = project.simulation;
	if ((spacing === 'series' || spacing === 'both') && !outputSeries(project).length) {
		sim.output_times = [{
			kind: sim.spacing === 'linear' ? 'linear' : 'log',
			points: Math.max(2, Math.round(Number(sim.output_points ?? 250))),
			from: null,
			to: null,
		}];
	}
	sim.spacing = spacing;
	return sim.spacing;
}

/** Adds a series of one kind, with something sensible in it. */
export function addOutputSeries(project, kind = 'log', patch = {}) {
	if (!SERIES_KINDS.includes(kind)) {
		throw new EditError(`'${kind}' is not a kind of series`);
	}
	if (!project.simulation) project.simulation = {};
	const sim = project.simulation;
	if (!Array.isArray(sim.output_times)) sim.output_times = [];
	const t0 = Number(sim.start_time ?? 0);
	const t1 = Number(sim.end_time ?? 0);
	const spec = kind === 'times'
		? { kind, times: [] }
		: {
			kind,
			points: kind === 'log' ? 100 : 11,
			// A new series is offered over the part of the run the one already
			// there cannot describe: the stretch before a logarithmic series
			// can start, which is the reason for having a list at all.
			from: kind === 'linear' ? t0 : null,
			to: kind === 'linear' ? Math.min(t1, Math.max(t0 + 1, 1)) : null,
			...patch,
		};
	sim.output_times.push(kind === 'times' ? { ...spec, ...patch } : spec);
	return spec;
}

/** Changes one series. Unknown keys are refused rather than stored. */
export function updateOutputSeries(project, index, patch = {}) {
	const list = outputSeries(project);
	const spec = list[index];
	if (!spec) throw new EditError(`No output series ${index + 1}`);
	const allowed = new Set(['kind', 'points', 'from', 'to', 'times']);
	for (const [key, value] of Object.entries(patch)) {
		if (!allowed.has(key)) throw new EditError(`A series has no '${key}'`);
		if (key === 'kind') {
			if (!SERIES_KINDS.includes(value)) {
				throw new EditError(`'${value}' is not a kind of series`);
			}
			spec.kind = value;
			// The two shapes carry different things, and leaving the other
			// behind would mean a series that looks like one kind and is read
			// as the other.
			if (value === 'times') {
				spec.times = spec.times ?? [];
				delete spec.points;
				delete spec.from;
				delete spec.to;
			} else {
				delete spec.times;
				spec.points = Math.max(2, Math.round(Number(spec.points ?? 100)));
				if (spec.from === undefined) spec.from = null;
				if (spec.to === undefined) spec.to = null;
			}
			continue;
		}
		if (key === 'times') {
			spec.times = (Array.isArray(value) ? value : [])
				.map((v) => Number(v))
				.filter((v) => Number.isFinite(v))
				.sort((a, b) => a - b);
			continue;
		}
		if (key === 'points') {
			const n = Math.round(Number(value));
			if (!(n >= 2)) throw new EditError('A series needs at least 2 points');
			spec.points = n;
			continue;
		}
		// `from` and `to`: a number, or nothing at all for the simulation's own.
		if (value == null || value === '') { spec[key] = null; continue; }
		const v = Number(value);
		if (!Number.isFinite(v)) throw new EditError(`'${value}' is not a time`);
		spec[key] = v;
	}
	return spec;
}

export function deleteOutputSeries(project, index) {
	const list = outputSeries(project);
	if (!list[index]) throw new EditError(`No output series ${index + 1}`);
	list.splice(index, 1);
	// An empty list is not a way of choosing times: fall back to the shorthand
	// rather than leave a model that cannot say when to save anything.
	if (!list.length) project.simulation.spacing = 'log';
	return list.length;
}

// --- shapes drawn on the canvas ---------------------------------------------

/**
 * Shapes are annotation, not model.
 *
 * A compartment model can say that water flows from the soil to the well at a
 * rate; it has no way to say that these four compartments are the near field,
 * or to draw the lake that two of them stand for. So a diagram carries a list
 * of shapes of its own: boxes to group things in, arrows to point with, and a
 * dictionary of the things these models are usually about -- see
 * ../ui/figures.js for what they look like.
 *
 * They live in `project.shapes` rather than in `layout`, because they are
 * content: someone drew them, and they are saved with the model for the same
 * reason a block's position is. Nothing in the engine reads them -- `Project`
 * carries them across untouched and the solver never sees them.
 *
 * Each one belongs to one sub-system's canvas, the way a block does, and the
 * order of the list is the order they are drawn in: later is on top. All of
 * them are drawn behind every block, which is the whole point of a group box.
 */

/** The colours a shape can be, as tokens resolved per theme. See app.css. */
export const SHAPE_COLORS = [
	'slate', 'blue', 'teal', 'green', 'olive',
	'amber', 'orange', 'red', 'purple', 'brown',
];

/** ...and 'none', which is a colour a fill or a line can be asked for. */
export const NO_COLOR = 'none';

export const SHAPE_DASHES = ['solid', 'dashed', 'dotted'];

/** Line widths offered, in model units. */
export const SHAPE_WIDTHS = [1, 2, 3, 5];

/** Label sizes offered, in model units. */
export const SHAPE_TEXT_SIZES = [11, 14, 18, 24];

/**
 * The hands a shape's text can be written in.
 *
 * `scribble` is a handwriting face, and it is a *stack* rather than a font
 * this project ships: nothing here downloads anything, so it asks for the
 * handwriting faces that come with the common systems and falls back to the
 * generic `cursive` when none is there. See `--decor-hand` in app.css.
 */
export const SHAPE_TEXT_FONTS = ['sans', 'scribble', 'serif', 'mono'];

/** Where the text sits across the shape. */
export const SHAPE_TEXT_ALIGNS = ['left', 'center', 'right'];

const SHAPE_DEFAULTS = {
	fill: 'slate',
	line: 'slate',
	line_width: 2,
	dash: 'solid',
	text: '',
	text_size: 14,
	text_font: 'sans',
	text_bold: false,
	text_italic: false,
	text_align: 'center',
	flip_x: false,
	flip_y: false,
};

/**
 * What a figure starts as, where that is not the common default.
 *
 * A sticky note is the one figure whose whole point is how it looks: yellow,
 * unoutlined, written by hand and ranged left, because that is what a sticky
 * note is. Kept here rather than in the drawing, because these are the values
 * written into the model when one is added -- and so are the modeller's to
 * change afterwards, which is why they are defaults and not fixed.
 */
const FIGURE_DEFAULTS = {
	sticky: {
		fill: 'amber',
		line: NO_COLOR,
		text_font: 'scribble',
		text_align: 'left',
		text_size: 18,
	},
};

/** The smallest a shape may be dragged to, and the largest. */
export const SHAPE_MIN = 8;
export const SHAPE_MAX = 4000;

/** Every shape in the model, in drawing order. Live objects. */
export function shapes(project) {
	return Array.isArray(project?.shapes) ? project.shapes : [];
}

/** The shapes drawn on one sub-system's canvas, in drawing order. */
export function shapesIn(project, system = '') {
	const here = system ?? '';
	return shapes(project).filter((sh) => (sh.system ?? '') === here);
}

/** ...and everything drawn inside it, however deeply nested. */
export function shapesInDeep(project, system = '') {
	return shapes(project).filter((sh) => isWithin(sh.system ?? '', system));
}

export function findShape(project, id) {
	return shapes(project).find((sh) => sh.id === id) ?? null;
}

/**
 * A shape as everything downstream can rely on reading it.
 *
 * The renderer must never be the thing that decides what a missing width
 * means, and a hand-written or half-edited file is exactly where those gaps
 * come from -- so every reader goes through here.
 */
export function readShape(sh) {
	const num = (v, fallback) => (Number.isFinite(Number(v)) ? Number(v) : fallback);
	const size = (v, fallback) => Math.min(SHAPE_MAX, Math.max(SHAPE_MIN, num(v, fallback)));
	const bound = (v) => Math.max(-SHAPE_MAX, Math.min(SHAPE_MAX, v));
	return {
		...SHAPE_DEFAULTS,
		...sh,
		id: String(sh?.id ?? ''),
		figure: String(sh?.figure ?? 'rect'),
		system: sh?.system ?? '',
		x: num(sh?.x, 0),
		y: num(sh?.y, 0),
		// A line and an arrow are drawn corner to corner, so one side of
		// theirs is legitimately zero and either may be negative -- that is
		// which way it points, not a mistake. Only the magnitude is bounded
		// here; the figures clamp what they cannot draw (see figureParts).
		w: bound(num(sh?.w, 160)),
		h: bound(num(sh?.h, 120)),
		line_width: Math.min(20, Math.max(0.5, num(sh?.line_width, 2))),
		text: String(sh?.text ?? ''),
		text_size: size(sh?.text_size, 14),
		text_font: SHAPE_TEXT_FONTS.includes(sh?.text_font) ? sh.text_font : 'sans',
		text_align: SHAPE_TEXT_ALIGNS.includes(sh?.text_align) ? sh.text_align : 'center',
		text_bold: !!sh?.text_bold,
		text_italic: !!sh?.text_italic,
		fill: colourOf(sh?.fill, SHAPE_DEFAULTS.fill),
		line: colourOf(sh?.line, SHAPE_DEFAULTS.line),
		dash: SHAPE_DASHES.includes(sh?.dash) ? sh.dash : 'solid',
		flip_x: !!sh?.flip_x,
		flip_y: !!sh?.flip_y,
	};
}

function colourOf(v, fallback) {
	const name = String(v ?? '').trim();
	if (name === NO_COLOR) return NO_COLOR;
	return SHAPE_COLORS.includes(name) ? name : fallback;
}

/** An id nothing else in the model is using. */
function nextShapeId(project) {
	const taken = new Set(shapes(project).map((sh) => sh.id));
	for (let i = 1; ; i++) {
		const id = `sh${i}`;
		if (!taken.has(id)) return id;
	}
}

/**
 * Adds a shape to one canvas.
 *
 * `at` is where it was asked for -- the point the menu was opened from -- and
 * it is taken as the shape's *middle*, because that is where the pointer was
 * and a shape that appeared with its corner there would land somewhere nobody
 * pointed at.
 */
export function addShape(project, figure, { system = '', at = null, size = null } = {}) {
	const name = String(figure ?? '').trim();
	if (!name) throw new EditError('A shape needs a figure to draw');
	if (system && !systems(project).includes(system)) {
		throw new EditError(`No sub-system named '${system}'`);
	}
	const w = size?.w ?? 180;
	const h = size?.h ?? 120;
	const shape = {
		id: nextShapeId(project),
		figure: name,
		...(system ? { system } : {}),
		x: onGrid((at?.x ?? 0) - w / 2),
		y: onGrid((at?.y ?? 0) - h / 2),
		w: Math.round(w),
		h: Math.round(h),
		// Written down rather than left to the defaults, so the file says what
		// the shape is; a label and its size are written only once there is a
		// label, and the flips only once something is flipped.
		fill: SHAPE_DEFAULTS.fill,
		line: SHAPE_DEFAULTS.line,
		line_width: SHAPE_DEFAULTS.line_width,
		dash: SHAPE_DEFAULTS.dash,
		// ...and whatever this figure starts as instead. See FIGURE_DEFAULTS.
		...(FIGURE_DEFAULTS[name] ?? {}),
	};
	if (!Array.isArray(project.shapes)) project.shapes = [];
	project.shapes.push(shape);
	return shape;
}

/** Changes one shape's properties. Unknown keys are refused, not stored. */
export function updateShape(project, id, patch = {}) {
	const shape = findShape(project, id);
	if (!shape) throw new EditError(`No shape '${id}'`);
	const allowed = new Set([
		'figure', 'x', 'y', 'w', 'h', 'fill', 'line', 'line_width',
		'dash', 'text', 'text_size', 'text_font', 'text_align',
		'text_bold', 'text_italic', 'flip_x', 'flip_y',
	]);
	for (const [key, value] of Object.entries(patch)) {
		if (!allowed.has(key)) throw new EditError(`A shape has no '${key}'`);
		if (key === 'fill' || key === 'line') {
			const name = String(value ?? '').trim();
			if (name !== NO_COLOR && !SHAPE_COLORS.includes(name)) {
				throw new EditError(`'${value}' is not a shape colour`);
			}
			shape[key] = name;
			continue;
		}
		if (key === 'dash' && !SHAPE_DASHES.includes(value)) {
			throw new EditError(`'${value}' is not a line style`);
		}
		if (key === 'text_font' && !SHAPE_TEXT_FONTS.includes(value)) {
			throw new EditError(`'${value}' is not a hand to write in (${SHAPE_TEXT_FONTS.join(', ')})`);
		}
		if (key === 'text_align' && !SHAPE_TEXT_ALIGNS.includes(value)) {
			throw new EditError(`'${value}' is not an alignment (${SHAPE_TEXT_ALIGNS.join(', ')})`);
		}
		if (key === 'text_bold' || key === 'text_italic') {
			// Written only when it is on: an `false` in every shape in the file
			// is noise, the same bargain the flips make.
			if (value) shape[key] = true;
			else delete shape[key];
			continue;
		}
		if (key === 'text') {
			// Blank means no label, and an empty property is noise in the file.
			const text = String(value ?? '');
			if (text.trim()) shape.text = text;
			else delete shape.text;
			continue;
		}
		if ((key === 'flip_x' || key === 'flip_y')) {
			if (value) shape[key] = true;
			else delete shape[key];
			continue;
		}
		shape[key] = value;
	}
	return shape;
}

/** Moves shapes by a delta, keeping them on the canvas they are on. */
export function moveShapes(project, ids, dx, dy) {
	const moved = [];
	for (const id of ids) {
		const shape = findShape(project, id);
		if (!shape) continue;
		shape.x = Math.round((Number(shape.x) || 0) + dx);
		shape.y = Math.round((Number(shape.y) || 0) + dy);
		moved.push(shape);
	}
	return moved;
}

/**
 * Lines up or spreads out a hand-picked set of shapes.
 *
 * `alignBlocks` for the drawing layer, and the same eight arrangements, with
 * one difference: a line or an arrow is drawn corner to corner, so its width
 * and height carry its direction and either may be negative. What is lined up
 * is the box a shape occupies, and it is moved there rather than placed there,
 * so an arrow that pointed up and to the left still does.
 *
 * @returns {number} how many actually moved
 */
export function alignShapes(project, ids, how) {
	if (!ARRANGEMENTS.includes(how)) throw new EditError(`No such arrangement: '${how}'`);
	const boxes = [...new Set(ids)].map((id) => {
		const sh = findShape(project, id);
		if (!sh) throw new EditError(`No shape '${id}'`);
		const r = readShape(sh);
		return {
			id,
			x: Math.min(r.x, r.x + r.w),
			y: Math.min(r.y, r.y + r.h),
			w: Math.abs(r.w),
			h: Math.abs(r.h),
		};
	});

	let moved = 0;
	alignBoxes(boxes, how).forEach((p, i) => {
		const was = boxes[i];
		if (p.x === was.x && p.y === was.y) return;
		moveShapes(project, [was.id], p.x - was.x, p.y - was.y);
		moved++;
	});
	return moved;
}

/**
 * Sets one shape's box.
 *
 * The box is normalised, so a corner dragged past the opposite one flips the
 * shape rather than giving it a negative width -- except that a line or an
 * arrow is *drawn* corner to corner, and for those the sign is the direction
 * it points, so their box is left as the drag made it.
 */
export function setShapeBox(project, id, { x, y, w, h }, { keepSign = false } = {}) {
	const shape = findShape(project, id);
	if (!shape) throw new EditError(`No shape '${id}'`);
	let box = { x, y, w, h };
	if (!keepSign) {
		if (w < 0) { box.x = x + w; box.w = -w; }
		if (h < 0) { box.y = y + h; box.h = -h; }
		box.w = Math.max(SHAPE_MIN, box.w);
		box.h = Math.max(SHAPE_MIN, box.h);
	}
	box.w = Math.min(SHAPE_MAX, box.w);
	box.h = Math.min(SHAPE_MAX, box.h);
	Object.assign(shape, {
		x: Math.round(box.x), y: Math.round(box.y),
		w: Math.round(box.w), h: Math.round(box.h),
	});
	return shape;
}

/** Removes shapes. Nothing refers to a shape, so nothing can refuse this. */
export function deleteShapes(project, ids) {
	const wanted = new Set(ids);
	const before = shapes(project).length;
	if (!before) return 0;
	project.shapes = shapes(project).filter((sh) => !wanted.has(sh.id));
	return before - project.shapes.length;
}

/** Copies shapes, offset a little so the copy is visible. */
export function duplicateShapes(project, ids, { dx = 20, dy = 20 } = {}) {
	const made = [];
	for (const id of ids) {
		const shape = findShape(project, id);
		if (!shape) continue;
		const copy = {
			...structuredClone(shape),
			id: nextShapeId(project),
			x: Math.round((Number(shape.x) || 0) + dx),
			y: Math.round((Number(shape.y) || 0) + dy),
		};
		project.shapes.push(copy);
		made.push(copy);
	}
	return made;
}

/**
 * Moves shapes to the front or the back of the drawing order.
 *
 * Only among themselves: every shape is drawn behind every block, so "to the
 * front" means in front of the other shapes, not in front of the model.
 */
export function orderShapes(project, ids, where = 'front') {
	const wanted = new Set(ids);
	const chosen = shapes(project).filter((sh) => wanted.has(sh.id));
	if (!chosen.length) return [];
	const rest = shapes(project).filter((sh) => !wanted.has(sh.id));
	project.shapes = where === 'back' ? [...chosen, ...rest] : [...rest, ...chosen];
	return chosen;
}

/** Moves shapes onto another sub-system's canvas. */
export function moveShapesTo(project, ids, system = '') {
	if (system && !systems(project).includes(system)) {
		throw new EditError(`No sub-system named '${system}'`);
	}
	const moved = [];
	for (const id of ids) {
		const shape = findShape(project, id);
		if (!shape) continue;
		if (system) shape.system = system;
		else delete shape.system;
		moved.push(shape);
	}
	return moved;
}

/** The box round a set of shapes, for fitting the view to a diagram. */
export function shapesBox(list) {
	let box = null;
	for (const raw of list) {
		const sh = readShape(raw);
		const x0 = Math.min(sh.x, sh.x + sh.w);
		const y0 = Math.min(sh.y, sh.y + sh.h);
		const x1 = Math.max(sh.x, sh.x + sh.w);
		const y1 = Math.max(sh.y, sh.y + sh.h);
		box = box
			? {
				x0: Math.min(box.x0, x0), y0: Math.min(box.y0, y0),
				x1: Math.max(box.x1, x1), y1: Math.max(box.y1, y1),
			}
			: { x0, y0, x1, y1 };
	}
	return box;
}

// --- diagram view state -----------------------------------------------------

/**
 * `connection_label` says what the text along a transfer or source line is:
 *
 *   name   the block's name -- the default, since it is what the rest of the
 *          interface calls the transfer, and it stays short
 *   rate   the rate equation, and for a rate coefficient the donor it
 *          multiplies, so the label reads as the flux it stands for
 *   none   nothing
 */
export const CONNECTION_LABELS = ['name', 'rate', 'none'];

const DEFAULT_VIEW = {
	show_expressions: true,
	show_parameters: false,
	// A lookup table draws its own curve on the canvas, which is the one thing
	// about it worth seeing at a glance -- the name says which driver it is and
	// the sparkline says what it does. Hidden by default it was a block you had
	// to know was there to look for.
	show_lookups: true,
	// Index operations and aggregates are usually a model's outputs, so they
	// are shown like expressions rather than hidden like parameters.
	show_reductions: true,
	// A function is an expression with arguments, so it is drawn like one.
	// There are never many -- the models that have any have one or two -- and
	// the arrows to and from one say a great deal about how a model is put
	// together: what the body reads, and which equations call it.
	show_functions: true,
	// Whether the list of warnings under the tabs is shown. On, because a
	// warning nobody sees is a warning that may as well not have been worked
	// out -- and switchable, because a model can carry thirty that its author
	// has looked at and decided about, and a strip that says so on every edit
	// from then on is in the way rather than in the picture. Saved with the
	// model, since it is that model's warnings that were read.
	//
	// The *list*, and only the list: the amber marks on the diagram and in
	// the tree stay either way. They are one glyph beside a name rather than
	// a panel across the top, they are how a warning is found once the list
	// has been put away, and hiding the summary is not the same as deciding
	// the blocks are fine.
	show_warning_list: true,
	// So are the blocks that remember: a peak dose is a result, and the event
	// that drives one belongs beside it.
	show_recorders: true,
	show_influences: false,
	// The cloud at the end of a flow that leaves the model. On a diagram with
	// many outflows it is repetition, so it can be turned off.
	show_sinks: true,
	// And the one at the start of a flow that comes in from outside it. Its
	// own switch rather than the same one: a model of this kind has an outflow
	// on nearly every compartment and two or three source terms, so the reason
	// to turn the first off -- the same mark over and over -- is not a reason
	// to lose the few that say where the inventory enters.
	show_sources: true,
	// The line of prose under the diagram. Off by default: it is six lines of
	// the canvas's height, and the canvas is what the tab is for. `Show > the
	// help line under the diagram` in the empty-canvas menu brings it back,
	// the Help tab has the same material at length, and every gesture it
	// describes is also in a tooltip on the thing that performs it.
	show_help: false,
	// The lattice behind the diagram, and whether what is dragged lands on it.
	// Both on, which is what this editor has always done -- the grid was drawn
	// unconditionally and every move and resize was snapped. What is new is
	// being able to say no to either, and that the two are now the same
	// lattice: the grid is drawn at the pitch a drag snaps to, so a block that
	// looks aligned is aligned.
	show_grid: true,
	snap_to_grid: true,
	connection_label: 'name',
};

/**
 * What the diagram shows. Presentation state, kept in the project so it
 * survives a save and reload the way node positions do -- Ecolego keeps the
 * equivalent in views.xml.
 */
export function view(project) {
	return { ...DEFAULT_VIEW, ...(project.view ?? {}) };
}

export function setView(project, patch) {
	if (patch.connection_label != null
		&& !CONNECTION_LABELS.includes(patch.connection_label)) {
		throw new EditError(
			`'${patch.connection_label}' is not a label mode `
			+ `(${CONNECTION_LABELS.join(', ')})`,
		);
	}
	if (patch.show_influences != null && typeof patch.show_influences !== 'boolean'
		&& !INFLUENCE_MODES.includes(patch.show_influences)) {
		throw new EditError(
			`'${patch.show_influences}' is not a way of showing influences `
			+ `(${INFLUENCE_MODES.join(', ')})`,
		);
	}
	project.view = { ...view(project), ...patch };
	return project.view;
}

/**
 * Which influences the diagram draws: none, all of them, or only those of the
 * blocks selected -- every arrow into or out of any of them, which on a model
 * of any size is the one set that can be read.
 *
 * `show_influences` was a switch, and a file written then says `true` or
 * `false`; those are all and none.
 */
export const INFLUENCE_MODES = ['none', 'all', 'selected'];

export function influenceMode(project) {
	const v = view(project).show_influences;
	if (v === true) return 'all';
	return INFLUENCE_MODES.includes(v) ? v : 'none';
}

/**
 * The text drawn along a connection, for the current label mode.
 *
 * A rate coefficient is only half of the flux -- the other half is the donor
 * it multiplies -- so showing `k` alone for one transfer and `k` for another
 * that is an absolute flux says the same thing about two different quantities.
 * With the donor named, the label reads as what actually moves.
 */
export function connectionLabelText(project, conn, kind = 'transfer') {
	const mode = view(project).connection_label;
	if (mode === 'none') return '';
	if (mode === 'name') return conn.name ?? '';
	const rate = String(conn.rate ?? '');
	if (!rate) return '';
	const donor = kind === 'transfer' && conn.multiply_by_donor !== false
		? conn.from
		: null;
	return donor ? `${rate} \u00b7 ${donor}` : rate;
}

// --- the model's own name and description ------------------------------------

/**
 * What to call a model that has no name of its own.
 *
 * Ecolego takes the name from the project folder, so a model there always has
 * one. Here a project can arrive from a paste or a bare model.xml with the
 * field missing or blank, and every place that shows it -- the header, the
 * saved filename, the CSV -- needs the same answer.
 */
export const UNTITLED = 'Untitled model';

export function modelName(project) {
	const n = String(project.name ?? '').trim();
	return n || UNTITLED;
}

/** Stored trimmed, and dropped rather than stored blank. */
export function setModelName(project, name) {
	const n = String(name ?? '').trim();
	if (n) project.name = n;
	else delete project.name;
	return modelName(project);
}

export function modelDescription(project) {
	return String(project.description ?? '');
}

/**
 * Free text; newlines are kept, since a description is often a few lines of
 * provenance. Only trailing whitespace goes.
 */
export function setModelDescription(project, text) {
	const d = String(text ?? '').replace(/\s+$/, '');
	if (d) project.description = d;
	else delete project.description;
	return modelDescription(project);
}

/**
 * The top of a model file, in the order it is written: what the model is
 * called and what it is, who wrote it, and when it was made and last saved.
 * The rest of the file follows in whatever order it already had.
 */
export const HEADER_KEYS = ['name', 'description', 'author', 'created', 'saved'];

/**
 * Puts the header first, in place: the same object, its keys re-ordered.
 *
 * A field that is added later -- the author typed in, the first save stamped
 * -- would otherwise land at the bottom of the file, below a layout of a
 * thousand lines, where nobody reading the JSON would look for who wrote it.
 */
function headerFirst(project) {
	const keys = Object.keys(project);
	const want = [...HEADER_KEYS.filter((k) => keys.includes(k)), ...keys.filter((k) => !HEADER_KEYS.includes(k))];
	if (want.every((k, i) => k === keys[i])) return project;
	const values = want.map((k) => project[k]);
	for (const k of keys) delete project[k];
	want.forEach((k, i) => { project[k] = values[i]; });
	return project;
}

export function modelAuthor(project) {
	return String(project.author ?? '').trim();
}

/** Who wrote the model: stored trimmed, and dropped rather than stored blank. */
export function setModelAuthor(project, name) {
	const a = String(name ?? '').trim();
	if (a) project.author = a;
	else delete project.author;
	headerFirst(project);
	return modelAuthor(project);
}

/** Whether a stamp is a time that can be read back: an ISO 8601 date and time. */
export function readStamp(value) {
	if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T/.test(value)) return null;
	const at = new Date(value);
	return Number.isFinite(at.getTime()) ? at : null;
}

/**
 * Records a save: `saved` becomes `when`, and `created` too if the model has
 * none -- a model made before the field existed is dated by its first save,
 * which is the earliest this tool can vouch for.
 *
 * Neither is an edit. Nothing is run again for them, the Save button does not
 * light up, and an undo leaves them alone (see `keepStamps`): they are facts
 * about the file, not about the model in it.
 *
 * @returns the project, stamped in place
 */
export function stampSaved(project, when = new Date()) {
	const at = when.toISOString();
	if (!readStamp(project.created)) project.created = at;
	project.saved = at;
	return headerFirst(project);
}

/** Records that a model has just been made, now. */
export function stampCreated(project, when = new Date()) {
	project.created = when.toISOString();
	delete project.saved;
	return headerFirst(project);
}

/**
 * Carries the file's two stamps from one version of a model to another: an
 * undo puts the model back as it was, but not the time it was last saved.
 */
export function keepStamps(to, from) {
	for (const key of ['created', 'saved']) {
		if (from?.[key] == null) delete to[key];
		else to[key] = from[key];
	}
	return headerFirst(to);
}

// --- units that follow from the model ---------------------------------------

// The derivations themselves live in ./units.js, so that Project can use them
// too without importing the editor. Reached through this module because every
// other edit in the application is, and because the editor is what knows which
// dimension the radionuclides are on.
/**
 * Brings every unit that follows from the model up to date.
 *
 * Two rules, and they are separate functions because they are separate facts:
 * a flux is its donor over the time unit, and a compartment indexed by the
 * radionuclide list holds the model's inventory unit. Called after any edit
 * rather than at each of the dozen places that can invalidate one.
 *
 * @returns the names of the blocks it changed
 */
export function syncDerivedUnits(project) {
	// A flux's *dimension* follows from its ends in the same way its unit
	// follows from its donor, and it has to be settled first: the unit is read
	// off a block whose shape this may just have changed.
	syncTransferDimensions(project);
	// Inventories first. A flux is derived from its donor's unit, so a
	// compartment that is about to be filled in has to be filled in before
	// anything is read off it.
	const inventories = syncInventoryUnits(
		project,
		materialDimensionNames(project),
		// As the block currently reads, not only as it is written down: a file
		// in the `nuclides: [...]` shorthand carries the dimension by
		// inference until makeDimensionsExplicit has run over it.
		(c) => effectiveDims(project, c),
	);
	const fluxes = syncFluxUnits(project);
	return [...inventories, ...fluxes];
}
export {
	timeUnit, derivedUnit, DERIVED_UNIT_KINDS, inventoryUnit,
	materialUnit, dimensionUnit,
};
// The output-time generators live in ./timeseries.js, next to the arithmetic;
// reached through here like every other edit.
export {
	SPACINGS, SERIES_KINDS, seriesTimes, seriesKind, describeSeries, combineSeries,
	droppedTimes, clippedEnds,
} from './timeseries.js';
// The two rules about which dimensions a block may carry: whose they are is
// ./indexlists.js, reached through here like everything else the editor does.
export {
	AUTO_DIM_KINDS, listApplies, listAppliesWhy,
	clashingDimensionsWhy as dimensionsClashWhy,
	// The rule a flux's dimensions follow, reached through here like the rest.
	sharedDims,
} from './indexlists.js';

/**
 * The dimension a block's inventory decays along, or null.
 *
 * Decay and ingrowth are per nuclide: they couple a compartment's states along
 * the radionuclide dimension, and a compartment that has none has nothing for
 * them to act on. The engine has always worked this way -- a compartment with
 * no nuclide dimension is skipped -- so this is what the editor asks before
 * offering to switch it on.
 */
export function decayDimensionOf(project, block) {
	const material = materialDimensionName(project);
	if (!material) return null;
	const lists = indexLists(project);
	return effectiveDims(project, block)
		.find((d) => isDecayDim(lists, d, material)) ?? null;
}

// --- legacy key names -------------------------------------------------------

// Reached through this module for the same reason: the editor works on the raw
// project object, so it is the editor that has to rename an old file's keys.
export { migrateKeys, LEGACY_KEYS } from './keys.js';

// --- what a block is called on screen ---------------------------------------

// Reached through this module like everything else the editor does; the parse
// itself is in ./symbol.js so nothing that only needs to *draw* a symbol has
// to import the editor.
export {
	symbolRuns, symbolText, displayName, hasSymbol, SYMBOL_TAGS,
} from './symbol.js';

// --- the hierarchy ----------------------------------------------------------

// Reached through this module like everything else the editor does. See
// ./systems.js for what a qualified name is.
export {
	qualifiedName, systemOf, qualify, parentOf, baseName, isWithin,
} from './systems.js';

// --- legacy value maps ------------------------------------------------------

/**
 * Folds the two per-nuclide shorthands into entries, in place.
 *
 *   parameter:   values_by_nuclide: { "I-129": 1e-5, ... }
 *   compartment: initial:         { "I-129": "3e12", ... }
 *
 * Project already understands both (see normaliseEntries there), so a file
 * using them runs correctly -- but only the engine's copy is converted, and
 * the editor works on the raw object. The result was a model whose per-index
 * values were real to the solver and invisible in the interface: the entry
 * grids showed every combination inheriting the default. The bundled
 * biosphere example is written this way.
 *
 * Converting once, on load, leaves one representation in front of the user.
 * Semantics are preserved by construction: an index that already has an entry
 * for that key keeps it, which is the same precedence Project applies (equal
 * specificity, first match wins).
 */
export function materialiseLegacyEntries(project) {
	let moved = 0;

	// `default` is an older name for the block-level value. Project honours it
	// but the editor showed nothing, since it looks for `value` (or `initial`,
	// or `equation`).
	for (const kind of KINDS) {
		const key = ENTRY_KEY[SINGULAR[kind]];
		for (const block of project[kind] ?? []) {
			if (block.default === undefined) continue;
			if (block[key] === undefined) block[key] = block.default;
			delete block.default;
			moved++;
		}
	}

	const material = materialDimensionName(project);
	if (!material) return moved;

	const add = (block, index, key, value) => {
		const existing = findEntry(block, index);
		if (existing && Object.prototype.hasOwnProperty.call(existing, key)) return;
		if (existing) existing[key] = value;
		else (block.entries ??= []).push({ index, [key]: value });
		moved++;
	};

	for (const p of project.parameters ?? []) {
		const map = p.values_by_nuclide;
		if (!map || typeof map !== 'object') continue;
		// A block that is not indexed by the material list cannot hold these,
		// and Project ignores them too, so they are left where they are.
		if (!effectiveDims(project, p).includes(material)) continue;
		for (const [nuc, v] of Object.entries(map)) {
			add(p, { [material]: nuc }, 'value', Number(v));
		}
		delete p.values_by_nuclide;
	}

	for (const c of project.compartments ?? []) {
		const map = c.initial;
		if (!map || typeof map !== 'object' || Array.isArray(map)) continue;
		if (!effectiveDims(project, c).includes(material)) continue;
		for (const [nuc, v] of Object.entries(map)) {
			add(c, { [material]: nuc }, 'initial', String(v));
		}
		// As Project does: the map was the whole story, so the default is zero.
		c.initial = '0';
	}

	return moved;
}

// --- finding blocks by name -------------------------------------------------

/**
 * A name filter for the block list, and for highlighting on the diagram.
 *
 * Two behaviours in one box, because both are what people expect from it:
 *
 *   `wat`      matches anywhere in the name -- the common case is typing a
 *              few letters of something you know is there
 *   `C*_out`   with `*` or `?` present, it is a pattern over the whole name
 *              (`*` any run, `?` one character), which is how you ask for
 *              "everything ending in _out" without also matching a name that
 *              merely contains it
 *
 * Case-insensitive either way. Anything else in the query -- a dot, a bracket
 * -- is a literal, so a search box cannot become a regular-expression
 * injection.
 */
export function nameMatcher(query) {
	const q = String(query ?? '').trim();
	if (!q) return () => true;

	if (!/[*?]/.test(q)) {
		const needle = q.toLowerCase();
		return (name) => String(name ?? '').toLowerCase().includes(needle);
	}

	const rx = new RegExp(
		`^${q.replace(/[.*+?^${}()|[\]\\]/g, (ch) => {
			if (ch === '*') return '.*';
			if (ch === '?') return '.';
			return `\\${ch}`;
		})}$`,
		'i',
	);
	return (name) => rx.test(String(name ?? ''));
}

/** The block kinds a search can be limited to, in the order they are listed. */
export const SEARCH_KINDS = [
	'compartment', 'transfer', 'inflow', 'expression', 'parameter', 'lookup',
	'index_reduction', 'block_reduction', 'function',
	'min_max', 'running_mean', 'snapshot', 'delay', 'trigger',
];

/**
 * Blocks whose name matches, limited to the given kinds.
 *
 * @param {object} project
 * @param {{query?: string, kinds?: string[]|Set<string>}} [filter]
 *   An empty or absent `kinds` means every kind, not none: a filter nobody has
 *   touched must not hide the model.
 * @returns {{name: string, kind: string}[]} `name` is the qualified name --
 *   the one string the rest of the editor addresses a block by, and the one
 *   the diagram tags its nodes and connections with. Returning the bare name
 *   meant the diagram never lit up a match inside a sub-system.
 */
export function searchBlocks(project, filter = {}) {
	const matches = nameMatcher(filter.query);
	const kinds = filter.kinds && [...filter.kinds].length
		? new Set(filter.kinds)
		: null;
	// The answer to a structured question -- see ./queries.js -- pinned over
	// the list. It narrows rather than replaces, so the name box and the kind
	// chips still work on top of it: "the things that read `leachRate`" and
	// then "of those, the transfers".
	const only = filter.only ? new Set(filter.only) : null;
	return allBlocks(project)
		// Either spelling matches: `Water` finds every Water in the model, and
		// `NearField.*` finds one sub-system's worth.
		.filter((b) => (!kinds || kinds.has(b.kind))
			&& (!only || only.has(qualifiedName(b)))
			&& (matches(b.name) || matches(qualifiedName(b))))
		.map((b) => ({ name: qualifiedName(b), kind: b.kind }));
}

/**
 * The model as a tree: sub-systems nested the way their names say, with the
 * blocks of each hanging beneath it.
 *
 * The panel on the right used to be a flat list grouped by kind, which said
 * where a block lived only in its tooltip. In an Ecolego model a name means
 * nothing without its sub-system -- `Water` in three systems is three blocks,
 * and the one you want is the one in `Biosphere` -- so the shape of the model
 * is the useful spine, and the kind of a block is better carried by an icon
 * beside it than by a heading it has to be filed under.
 *
 * `filter` is the one `searchBlocks` takes: a name pattern and a set of kinds.
 * A sub-system survives filtering when it, or anything beneath it, still holds
 * a block -- pruning on a system's own blocks alone would cut the path to a
 * match and leave the match unreachable.
 *
 * Empty sub-systems are in the tree whether or not the filter is on, unless
 * the filter prunes them: one that has just been created has to be visible to
 * be filled, and one that has been emptied is a fact about the model.
 *
 * @param {object} project
 * @param {{query?: string, kinds?: string[]|Set<string>}} [filter]
 * @param {{group?: boolean}} [opts]  `group` puts a sub-system's blocks in
 *   kind order before name order, which is what the grouped view reads: it
 *   takes each run of one kind as a heading. Ungrouped, the order is the name
 *   alone -- with no headings, kind order is an order only somebody who knows
 *   the collection list can see, and a name is what is being looked for.
 * @returns {{path: string, name: string, systems: object[], blocks: object[],
 *   count: number, deep: number}} the top level, whose `systems` are its
 *   direct children, and so on down.
 */
const NAME_ORDER = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

export function blockTree(project, filter = {}, opts = {}) {
	const matches = nameMatcher(filter.query);
	const kinds = filter.kinds && [...filter.kinds].length
		? new Set(filter.kinds)
		: null;
	const only = filter.only ? new Set(filter.only) : null;
	const filtering = !!String(filter.query ?? '').trim() || !!kinds || !!only;

	const byPath = new Map();
	const at = (path) => {
		const found = byPath.get(path);
		if (found) return found;
		const node = {
			path,
			name: path ? baseName(path) : modelName(project),
			systems: [],
			blocks: [],
			count: 0,
			deep: 0,
		};
		byPath.set(path, node);
		// A path implies its parents, so a system nested three deep brings the
		// two above it into the tree even if neither holds a block itself.
		if (path) at(parentOf(path)).systems.push(node);
		return node;
	};
	at('');
	for (const path of systemPaths(project)) at(path);

	const rank = new Map(KINDS.map((k, i) => [k, i]));
	for (const collection of KINDS) {
		const kind = SINGULAR[collection];
		if (kinds && !kinds.has(kind)) continue;
		for (const b of project?.[collection] ?? []) {
			const name = qualifiedName(b);
			if (only && !only.has(name)) continue;
			if (!matches(b.name) && !matches(name)) continue;
			at(systemOf(b)).blocks.push({ kind, collection, name, label: b.name, block: b });
		}
	}

	// One collator, not one per comparison: `localeCompare` with options
	// builds a collator each call, and on a model of 3,789 blocks that alone
	// was 50 ms of every redraw of the panel.
	const byName = NAME_ORDER.compare;
	const finish = (node) => {
		for (const s of node.systems) finish(s);
		node.systems.sort((a, b) => byName(a.name, b.name));
		// Grouped, kind first -- in the order the rest of the editor lists
		// them -- because the headings are cut from the runs of one kind that
		// makes. Ungrouped, by name: there are no headings to file a block
		// under, so kind order is an order only somebody who already knows the
		// collection list can see, and the thing being looked for is a name.
		node.blocks.sort(opts.group
			? (a, b) => (rank.get(a.collection) - rank.get(b.collection))
				|| byName(a.label, b.label)
			: (a, b) => byName(a.label, b.label));
		if (filtering) node.systems = node.systems.filter((s) => s.deep > 0);
		node.count = node.blocks.length;
		node.deep = node.count + node.systems.reduce((t, s) => t + s.deep, 0);
		return node;
	};
	return finish(at(''));
}

// Everything a FARFCOMP block is made of, re-exported so the interface reaches
// one module for the model. See ./farfield.js.
export {
	FARF_DEFAULTS, FARF_EQUATION_KEYS, FARF_NUCLIDE_KEYS, FARF_SINGLE_KEYS,
	FARF_STRUCTURE_KEYS, FARF_CHOICE_KEYS, FARF_HELP, FARF_LABEL, FARF_TERM, OUTFLOWS,
	OUTFLOW_LABEL, OUTFLOW_ORDER, CONTINUES, SURFACES, SURFACE_KEY, SURFACE_LABEL, GRIDS,
	GRID_LABEL, FARF_SURFACE_DEFAULTS, FARF_LEGACY, cellCount, cellNames, heldCells,
	structureProblem, geometryProblem, dispersionWarning, gridPeclet, extraCells,
	autoExtraCells, activeEquationKeys, surfaceOf, usesCells, isSemiAnalytic, FARF_METHODS,
	METHOD_LABEL,
} from './farfield.js';

// Waste packages: the source term with its barriers. Re-exported so the panels
// import one module for the model, as with the far-field path above.
export {
	FAILURES, FAILURE_LABEL, FAILURE_BLURB, FAILURE_KEYS,
	WASTE_NUCLIDE_KEYS, WASTE_SINGLE_KEYS, WASTE_EQUATION_KEYS, WASTE_LABEL, WASTE_HELP,
	failureOf, failedFraction,
} from './wastepackage.js';

// Disruptive events: something happens at an instant. Re-exported for the
// panels, as with the two block kinds above.
export {
	TIMINGS, TIMING_LABEL, TIMING_BLURB, TIMING_KEYS, ACTIONS, ACTION_LABEL, ACTION_BLURB,
	DIS_EQUATION_KEYS, DIS_LABEL, DIS_HELP, timingOf, normaliseActions, shareText,
} from './disruption.js';
