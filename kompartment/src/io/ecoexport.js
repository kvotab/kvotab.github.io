/**
 * Exporter for Ecolego 6 project files (.eco): the other direction of ./eco.js.
 *
 * The importer is the specification. Everything written here is written the
 * way that reader reads it -- the archive's layout, the element and attribute
 * names, the block types, the spelling of every enumeration -- so a model
 * exported and imported again comes back as the model that went out, apart
 * from what the report names. Where this tool has something an Ecolego
 * project has no place for, it is left out and said so, never written in a
 * form Ecolego would read as something else; where an exact translation into
 * Ecolego's own constructs exists, that is what is written, and the report
 * says that too.
 *
 *   exportEco(project)       -> { bytes, xml, report }   the .eco archive
 *   exportModelXML(project)  -> { xml, report }          model.xml alone
 *
 * **What the archive is.** Three entries at the root, as an Ecolego 6 project
 * folder zipped: `.version`, a properties file saying which Ecolego format this
 * is; `model.xml`, the model; and `views.xml`, the diagram -- written empty,
 * since this tool's layout is not Ecolego's and Ecolego lays a model out itself.
 * Every entry is **stored**, not deflated. Deflate is the platform's, and the
 * browser's, Node's and Python's encoders choose different bytes for the same
 * text; stored entries make an export the same file wherever it is made, which
 * is what lets the Python package be checked against this one byte for byte.
 *
 * **Ids.** In an Ecolego file a block's id is its qualified name
 * (`NearField.Water`) and a sub-system's is its path, and those are the ids
 * written here. An index list's id is its name and an index's is its name too,
 * made safe for the comma-separated `index=` attribute an entry is keyed by.
 * Every block, sub-system and the project carry a GUID, derived from the
 * project's name and the id so that the same model exports to the same bytes.
 *
 * **Values per index.** An Ecolego entry is one row of a block's table: one
 * index combination and every column at it. An entry here may name only some
 * of a block's lists and only some of its values, the most specific match
 * winning per value. So each row is written with the value every column
 * actually has at that combination, and an entry naming fewer lists than the
 * block has is written as one row per combination it covers.
 *
 * See the Guide's *Exporting to Ecolego* for what maps to what.
 */

import { zip, crc32 } from './zip.js';
import { migrateKeys, materialiseShorthand, syncDerivedUnits } from '../domain/edit.js';
import { HALF_LIVES, defaultChains, SECONDS_PER_YEAR } from '../domain/nuclides.js';
import {
	deriveElements, sharedDims, summedDims, lineage,
	COMPARTMENT_LIST, TRANSFER_LIST, SOURCE_INDEX, TARGET_INDEX,
} from '../domain/indexlists.js';
import { resolveReference, parentOf, baseName } from '../domain/systems.js';
import { interpolationFromEco } from '../domain/lookup.js';
import { operationFromEco } from '../domain/reduce.js';
import { extremeFromEco, directionFromEco } from '../domain/recorders.js';
import { kindInfo, quantile, complete } from '../domain/pdf.js';
import { tokenize } from '../parser/parser.js';
import { RESERVED } from '../domain/names.js';

export class ExportError extends Error {
	constructor(message) {
		super(message);
		this.name = 'ExportError';
	}
}

/** The Ecolego format this writes: what `.version` says and the importer reads. */
export const ECOLEGO_VERSION = '6.5';

/** views.xml: Ecolego's diagram, empty -- see the note at the top. */
export const VIEWS_XML = '<?xml version="1.0" encoding="UTF-8"?>\n<presentation-model>\n</presentation-model>\n';

/**
 * A fixed table that is safe to index with text out of a model: on a plain
 * object `SOLVER_TO_ECO['constructor']` is a function, which would be written
 * into the file as the name of a solver. Every table below that is looked up
 * by something the model says goes through this.
 */
const table = (entries) => Object.assign(Object.create(null), entries);

/**
 * The type name each kind of block is written under, as the importer reads
 * it (`SUPPORTED` in ./eco.js). A transport part and a function are decided per
 * block, below.
 */
const ECO_TYPE = table({
	parameters: 'parameter',
	compartments: 'compartment',
	expressions: 'expression',
	functions: 'expression',
	lookups: 'lookup-table',
	index_reductions: 'index-operation',
	block_reductions: 'aggregate',
	min_maxes: 'min-max',
	running_means: 'running-mean',
	snapshots: 'snapshot',
	delays: 'delay',
	triggers: 'discrete-event',
});

/** The order components are written in: each collection in the model's own order. */
const COMPONENT_COLLECTIONS = [
	'parameters', 'compartments', 'expressions', 'functions', 'lookups',
	'index_reductions', 'block_reductions',
	'min_maxes', 'running_means', 'snapshots', 'delays', 'triggers',
];

/** Every collection of blocks, for resolving references. */
const ALL_COLLECTIONS = [
	...COMPONENT_COLLECTIONS, 'transfers', 'inflows', 'farfields', 'waste_packages', 'events',
];

/** What each collection is called in the report. */
const KIND_WORD = table({
	parameters: 'parameter',
	compartments: 'compartment',
	expressions: 'expression',
	functions: 'function',
	lookups: 'lookup table',
	index_reductions: 'index operation',
	block_reductions: 'aggregate',
	min_maxes: 'min/max',
	running_means: 'running mean',
	snapshots: 'snapshot',
	delays: 'delay',
	triggers: 'trigger',
	transfers: 'transfer',
	inflows: 'inflow',
	farfields: 'far-field pathway',
	waste_packages: 'waste package',
	events: 'event',
});

/** A lookup table's interpolation rule as Ecolego spells it: `FROM_ECO` in ../domain/lookup.js, reversed. */
const INTERPOLATION_TO_ECO = table({
	linear: 'Interpolation-Use End Values',
	extrapolate: 'Interpolation-Extrapolation',
	below: 'Use Input Below',
	above: 'Use Input Above',
	nearest: 'Use Input Nearest',
});

/** A reduction as Ecolego's enumeration spells it. */
const OPERATION_TO_ECO = table({
	sum: 'SUM', product: 'PRODUCT', min: 'MIN', max: 'MAX', mean: 'MEAN', percentile: 'PERCENTILE',
});

/** An event's direction as Ecolego spells it: `DIRECTION_FROM_ECO`, reversed. */
const DIRECTION_TO_ECO = table({ rising: 'RIGHT', falling: 'LEFT', both: 'BOTH' });

/**
 * The solver each of this tool's is written as.
 *
 * The first three are the same method under Ecolego's name and are read back
 * as they went. The rest are either the same method under a name the importer
 * maps elsewhere (RADAU5, ODE23TB) or the closest Ecolego has; the report says
 * which.
 */
const SOLVER_TO_ECO = table({
	ndf: 'ODE15S',
	ros23: 'ODE23S',
	dp45: 'ODE45',
	qndf: 'ODE15S',
	fbdf: 'ODE15S',
	radau5: 'RADAU5',
	trbdf2: 'ODE23TB',
	rodas5p: 'ODE23S',
	kencarp4: 'ODE15S',
	scipy_bdf: 'ODE15S',
	scipy_radau: 'RADAU5',
	scipy_lsoda: 'ODE15S',
});

/** The three that go out and come back as themselves. */
const SOLVER_EXACT = new Set(['ndf', 'ros23', 'dp45']);

/** Why each of the others is written as it is. */
const SOLVER_WHY = table({
	qndf: 'the same numerical differentiation formulas, which this tool reads back as ndf',
	radau5: 'Ecolego’s Radau IIA of order 5, which this tool reads back as ndf',
	trbdf2: 'Ecolego’s TR-BDF2, which this tool reads back as ros23',
	fbdf: 'the nearest Ecolego has: another BDF formulation',
	rodas5p: 'the nearest Ecolego has: its Rosenbrock solver, of lower order',
	kencarp4: 'the nearest Ecolego has for a stiff model',
	scipy_bdf: 'the nearest Ecolego has: the same family, a different implementation',
	scipy_radau: 'Ecolego’s Radau IIA of order 5, which this tool reads back as ndf',
	scipy_lsoda: 'the nearest Ecolego has for a stiff model',
});

/**
 * How results are saved, as `<output-options>` spells it. See readOutputTimes
 * in ./eco.js.
 */
const OUTPUT_OPTION = table({
	solver: 'Produce no additional output',
	both: 'Produce additional output',
	series: 'Produce specified output only',
});

/** Ecolego's "not set" for a time series' end: the simulation's own start or end. */
const D_AUTO_TEXT = '-7.92842341234234E11';

/** A floor far enough below any inventory to be none: see `lowerSaturation`. */
const NO_FLOOR = '-1.0E300';

/**
 * What this tool writes on the lists it makes itself (`ensureMaterialLists` in
 * ../domain/edit.js, `splitMaterialRoles` and `deriveElements` in
 * ../domain/indexlists.js): not somebody's comment, so not one left out.
 */
const BUILT_IN_COMMENT = /^(Every material the model knows\.( The radionuclides among them are in .+\.)?|The materials that have a half-life\.|One index per element of .+, kept in step with it\.)$/;

/** The property type an index list's predefined role is written with. */
const PREDEFINED_TYPE = 'se.facilia.ecolego.domain.EcolegoIndexList$PredefinedType';

/**
 * The chemical elements in order of atomic number, for a nuclide's `<z>`. One
 * string, so the Python port carries the same table character for character.
 */
const ELEMENT_SYMBOLS = (
	'H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn '
	+ 'Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce '
	+ 'Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn '
	+ 'Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl '
	+ 'Mc Lv Ts Og'
).split(' ');

/**
 * The settings a model here may carry that an Ecolego project has no field
 * for, in the order the report names them. Each is named only when the model
 * actually sets it.
 */
const UNCARRIED_SETTINGS = [
	'bdf', 'max_step', 'initial_step', 'max_steps', 'max_order', 'min_order', 'newton_kappa',
	'max_jac_age', 'below_tol_run', 'stagnation_tol', 'error_norm', 'matrix', 'jacobian',
	'norm_control', 'auto_abstol', 'mass_balance', 'split', 'switch_times', 'min_change_time',
	'partial', 'percentiles', 'categories', 'gsa', 'tornado_low', 'tornado_high', 'qa', 'show_mean',
];

// --- the report --------------------------------------------------------------

/**
 * What an export did, in the shape of the importer's ImportReport: what was
 * left out and why, what was written in another form, what was renamed, and
 * what else is worth knowing -- and how many of each kind of thing went out.
 */
export class ExportReport {
	constructor() {
		this.skipped = [];    // { type, name, why } -- left out
		this.rewritten = [];  // { type, name, how } -- written as an equivalent Ecolego construct
		this.renamed = [];    // { from, to }
		this.warnings = [];
		this.counts = {};
	}

	// Each said once: a block's table is written row by row, and the same
	// reason can come up at every row of it.
	skip(type, name, why) {
		if (!this.skipped.some((s) => s.type === type && s.name === name && s.why === why)) {
			this.skipped.push({ type, name, why });
		}
	}

	rewrite(type, name, how) {
		if (!this.rewritten.some((s) => s.type === type && s.name === name && s.how === how)) {
			this.rewritten.push({ type, name, how });
		}
	}

	rename(from, to) { this.renamed.push({ from, to }); }
	warn(message) { if (!this.warnings.includes(message)) this.warnings.push(message); }

	get ok() { return this.skipped.length === 0; }

	/** A short human summary, for the UI and the console. */
	summary() {
		const c = this.counts;
		const parts = [
			`${c.compartments} compartment(s)`, `${c.transfers} transfer(s)`,
			`${c.parameters} parameter(s)`, `${c.expressions} expression(s)`,
		];
		for (const [key, word] of [
			['functions', 'function(s)'], ['lookups', 'lookup table(s)'],
			['index_reductions', 'index operation(s)'], ['block_reductions', 'aggregate(s)'],
			['min_maxes', 'min/max block(s)'], ['running_means', 'running mean(s)'],
			['snapshots', 'snapshot(s)'], ['delays', 'delay(s)'], ['triggers', 'discrete event(s)'],
			['systems', 'sub-system(s)'],
		]) {
			if (c[key]) parts.push(`${c[key]} ${word}`);
		}
		const lines = [
			`Exported ${parts.join(', ')}, ${c.index_lists} index list(s), ${c.nuclides} nuclide(s).`,
		];
		if (this.skipped.length) {
			const byType = new Map();
			for (const s of this.skipped) byType.set(s.type, (byType.get(s.type) ?? 0) + 1);
			lines.push(
				`Left out ${this.skipped.length} thing(s) an Ecolego project has no place for: `
				+ [...byType].map(([t, n]) => `${n} ${t}`).join(', ') + '.',
			);
		}
		if (this.rewritten.length) {
			lines.push(`Wrote ${this.rewritten.length} thing(s) in the equivalent Ecolego form.`);
		}
		if (this.renamed.length) {
			lines.push(`Renamed ${this.renamed.map((r) => `${r.from} → ${r.to}`).join(', ')}.`);
		}
		for (const w of this.warnings) lines.push(w);
		return lines.join('\n');
	}
}

// --- the entry points ------------------------------------------------------------

/**
 * A model as an Ecolego 6 project archive.
 *
 * @param {object} project  the model, as it is saved (it is not changed)
 * @param {{modified?: Date}} [options]  `modified` is written as the project's
 *   modification date and on the archive's entries; left out, the entries are
 *   dated 1980-01-01, the earliest a ZIP can say, and no date is written into
 *   the model -- so the same model gives the same bytes
 * @returns {Promise<{bytes: Uint8Array, xml: string, report: ExportReport}>}
 */
export async function exportEco(project, options = {}) {
	const { xml, report, facts } = buildModelXML(project, options);
	const enc = new TextEncoder();
	const bytes = await zip([
		{ name: '.version', bytes: enc.encode(versionFile(facts)) },
		{ name: 'model.xml', bytes: enc.encode(xml) },
		{ name: 'views.xml', bytes: enc.encode(VIEWS_XML) },
	], {
		// Local midnight, so every time zone writes the same two DOS fields.
		modified: options.modified ?? new Date(1980, 0, 1),
		store: true,
	});
	return { bytes, xml, report };
}

/** model.xml alone, and what the export did. */
export function exportModelXML(project, options = {}) {
	const { xml, report } = buildModelXML(project, options);
	return { xml, report };
}

/**
 * `.version`: a properties file, one setting per line, as Java writes them.
 * The two `-required` flags say whether the model needs the ODE solver and the
 * nuclide database, which is what they are named for.
 */
function versionFile(facts) {
	return [
		`version=${ECOLEGO_VERSION}`,
		'track-changes=false',
		`ode-required=${facts.states ? 'true' : 'false'}`,
		`nuclidedb-required=${facts.nuclides ? 'true' : 'false'}`,
		'',
	].join('\n');
}

// --- the model -------------------------------------------------------------------

function buildModelXML(project, options) {
	if (!project || typeof project !== 'object' || Array.isArray(project)) {
		throw new ExportError('A model is one JSON object.');
	}
	// The model as the editor holds it once opened: keys in today's spelling,
	// the shorthands turned into lists and entries, every dimension written
	// down and every derived unit worked out. A copy, so the caller's model is
	// not touched.
	const raw = migrateKeys(structuredClone(project));
	materialiseShorthand(raw);
	syncDerivedUnits(raw);

	const report = new ExportReport();
	const ctx = new Context(raw, report);
	ctx.decideLists();
	ctx.decideMaterials();
	ctx.decideBlocks();
	ctx.checkNames();

	const w = new XmlWriter();
	w.open('data-model');
	writeProjectProperties(w, raw, ctx, options);
	writeMaterials(w, ctx);
	writeIndexLists(w, ctx);
	writeDecayChains(w, ctx);
	writeHierarchy(w, ctx);
	writeBlocks(w, ctx);
	writeSimulation(w, raw, ctx);
	writeProbabilistic(w, raw, ctx);
	w.close('data-model');

	report.counts = ctx.counts();
	return {
		xml: w.document(),
		report,
		facts: { states: ctx.hasStates(), nuclides: ctx.nuclideCount() },
	};
}

// --- what the model holds, worked out once -----------------------------------------

/** An index name, whichever of its two shapes a list holds it in. */
const indexName = (i) => (typeof i === 'string' ? i : i?.name);

/** Whether a list's index is switched on. */
const indexOn = (i) => typeof i === 'string' || i?.enabled !== false;

/** A block's qualified name. */
const qnameOf = (b) => (b?.system ? `${b.system}.${b.name}` : String(b?.name ?? ''));

class Context {
	constructor(raw, report) {
		this.raw = raw;
		this.report = report;
		/** What the project is called in the file, and what its GUIDs are keyed by. */
		this.projectName = String(raw.name ?? '').trim() || 'model';
		this.lists = Array.isArray(raw.index_lists) ? raw.index_lists : [];
		/** Every block, by qualified name: { collection, block }. */
		this.blocks = new Map();
		for (const collection of ALL_COLLECTIONS) {
			for (const block of raw[collection] ?? []) {
				if (!block || typeof block !== 'object') continue;
				const q = qnameOf(block);
				if (!this.blocks.has(q)) this.blocks.set(q, { collection, block });
			}
		}
		/** Qualified names left out, with the reason. */
		this.skippedBlocks = new Map();
		/** Transfers written in another form: qualified name -> plan. */
		this.fluxPlans = new Map();
		/** Source and sink components to write: [{ name, id, system, type }]. */
		this.boundaries = [];
	}

	known(name) { return this.blocks.has(name); }

	// --- index lists ------------------------------------------------------------

	/**
	 * Which lists go out, under which names and ids, and how their indices are
	 * addressed. The two lists made of the model's own blocks do not go out --
	 * Ecolego has no such dimension -- and a block indexed by either is left
	 * out below. The element list does, whether the model stores it or it is
	 * derived: Ecolego keeps one beside the materials in every project.
	 */
	decideLists() {
		const { report } = this;
		this.material = this.lists.find((l) => l?.for_contaminants) ?? null;
		this.nuclideList = this.lists.find((l) => l?.for_nuclides) ?? null;
		// The list a string-keyed entry means, as `Project.nuclideListName` has it.
		this.nuclideListName = this.nuclideList?.name ?? this.material?.name ?? null;

		this.autoLists = new Set();
		const out = [];
		for (const list of this.lists) {
			if (!list || typeof list !== 'object') continue;
			if (list.auto || (list.derived && (list.name === COMPARTMENT_LIST || list.name === TRANSFER_LIST))) {
				this.autoLists.add(list.name);
				continue;
			}
			out.push(list);
		}
		// The derived dimensions, which a model does not store.
		for (const name of [COMPARTMENT_LIST, TRANSFER_LIST]) {
			if (!out.some((l) => l.name === name)) this.autoLists.add(name);
		}
		let elements = out.find((l) => l.for_elements) ?? null;
		/** Every list the dimension rules read: the model's, and the element list derived beside them. */
		this.allLists = this.lists;
		if (!elements) {
			const derived = deriveElements(this.lists).find((l) => l.derived && l.for_elements);
			if (derived) {
				elements = derived;
				out.push(derived);
				this.allLists = [...this.lists, derived];
			}
		}
		this.elementList = elements;
		this.exportLists = out;

		// Ecolego calls the catalogue `Materials`; this tool calls it
		// `Contaminants`. The file gets Ecolego's name unless a list of the
		// model's already has it, and the importer renames it back on the way
		// in.
		this.listIds = new Map();
		const taken = new Set(out.map((l) => l.name));
		for (const list of out) {
			let id = list.name;
			if (list === this.material && list.name !== 'Materials' && !taken.has('Materials')) {
				id = 'Materials';
				report.rename(list.name, 'Materials');
			}
			this.listIds.set(list.name, id);
		}

		// Index ids. An index is addressed by its name, trimmed and without the
		// commas that separate the ids of an entry's key.
		this.indexIds = new Map();
		for (const list of out) {
			const ids = new Map();
			const used = new Set();
			for (const raw of list.indices ?? []) {
				const name = indexName(raw);
				if (name == null || ids.has(name)) continue;
				let base = String(name).trim().replace(/,/g, '_');
				if (base === '') base = 'index';
				let id = base;
				for (let n = 2; used.has(id); n++) id = `${base}_${n}`;
				used.add(id);
				ids.set(name, id);
				if (String(name) !== String(name).trim()) {
					report.warn(`The index '${name}' of '${list.name}' begins or ends with a space, which an `
						+ '.eco file does not keep: it is read back without it.');
				}
			}
			this.indexIds.set(list.name, ids);
		}

		// A list the importer would take for Ecolego's own by its name alone.
		for (const [flag, word] of [['for_scenarios', 'scenarios'], ['for_elements', 'elements']]) {
			if (out.some((l) => l[flag])) continue;
			const named = out.find((l) => String(l.name).trim().toLowerCase() === word
				&& !l.for_contaminants && !l.for_nuclides);
			if (named) {
				report.warn(`'${named.name}' is not this model's ${word.slice(0, -1)} dimension, but a list `
					+ `of that name with no other list marked as one is read as it when the file is `
					+ `imported. Rename it if that is not what it is.`);
			}
		}
	}

	/** The index names of one list, in order, every one of them. */
	indicesOf(listName) {
		const list = this.exportLists.find((l) => l.name === listName);
		return (list?.indices ?? []).map(indexName).filter((n) => n != null);
	}

	/** Whether a block's dimensions include one that does not go out. */
	autoDimOf(dims) {
		return dims.find((d) => this.autoLists.has(d)) ?? null;
	}

	/** A list's id in the file. */
	listId(name) { return this.listIds.get(name) ?? name; }

	/** An index's id in the file. */
	indexId(listName, name) { return this.indexIds.get(listName)?.get(name) ?? String(name); }

	// --- materials ------------------------------------------------------------------

	/**
	 * Which of the catalogue's materials are radionuclides, and their half-lives.
	 *
	 * Ecolego keeps one list of materials and marks each as a radionuclide or
	 * not; its radionuclide list is exactly the ones that are. A material here
	 * is written as a radionuclide when it is in this model's radionuclide list
	 * or has a half-life to decay by.
	 */
	decideMaterials() {
		const { raw, report } = this;
		const overrides = raw.half_lives && typeof raw.half_lives === 'object' ? raw.half_lives : {};
		const inNuclides = new Set((this.nuclideList?.indices ?? []).map(indexName));
		const halfLife = (name) => {
			if (Object.prototype.hasOwnProperty.call(overrides, name) && overrides[name] != null) {
				const v = overrides[name];
				if (v === Infinity || /^\s*(stable|inf(inity)?)\s*$/i.test(String(v))) return Infinity;
				const n = Number(v);
				if (Number.isFinite(n) && n > 0) return n;
			}
			const db = HALF_LIVES[name];
			return typeof db === 'number' ? db : null;
		};
		this.materials = [];
		const catalogue = (this.material?.indices ?? []).map(indexName).filter((n) => n != null);
		const units = new Map();
		for (const i of this.material?.indices ?? []) {
			if (typeof i === 'object' && i && String(i.unit ?? '').trim()) units.set(i.name, String(i.unit).trim());
		}
		for (const name of catalogue) {
			const years = halfLife(name);
			const nuclide = inNuclides.has(name) || (years != null && Number.isFinite(years));
			this.materials.push({
				name, nuclide, years: nuclide ? years : null, unit: units.get(name) ?? '',
			});
		}
		this.nuclideNames = this.materials.filter((m) => m.nuclide).map((m) => m.name);
		const listed = [...inNuclides].filter((n) => n != null);
		const added = this.nuclideNames.filter((n) => !inNuclides.has(n));
		if (added.length && this.nuclideList) {
			report.warn(`${added.join(', ')} ${added.length === 1 ? 'decays' : 'decay'} and `
				+ `${added.length === 1 ? 'is' : 'are'} not in '${this.nuclideList.name}'. Ecolego's `
				+ `radionuclide list holds every material that decays, so the file's does.`);
		}
		const outside = listed.filter((n) => !catalogue.includes(n));
		if (outside.length) {
			report.warn(`'${this.nuclideList.name}' names ${outside.join(', ')}, which `
				+ `${outside.length === 1 ? 'is' : 'are'} not in the catalogue of materials; `
				+ `${outside.length === 1 ? 'it was' : 'they were'} left out of it.`);
		}

		// The decay pairs: the model's own, or those the database gives the
		// catalogue, as the run works them out. A pair naming a nuclide the
		// model does not carry takes no part in a run and is not written.
		const nuclides = new Set(this.nuclideNames);
		const ceiling = Number(raw.simulation?.decay_ceiling);
		const stated = Array.isArray(raw.chains) ? raw.chains : null;
		const pairs = stated
			? stated.filter((p) => Array.isArray(p)).map((p) => [String(p[0]), String(p[1]), p[2] === undefined ? 1 : Number(p[2])])
			: defaultChains(catalogue, Number.isFinite(ceiling) && ceiling > 0 ? ceiling : Infinity);
		this.chains = pairs.filter(([a, b]) => nuclides.has(a) && nuclides.has(b));
		const dropped = pairs.length - this.chains.length;
		if (stated && dropped) {
			report.rewrite('decay chain', `${dropped} pair(s)`, 'name nuclides the model does not '
				+ 'carry, so they took no part in its run and were not written');
		}
	}

	nuclideCount() { return this.nuclideNames.length; }

	// --- blocks ---------------------------------------------------------------------

	/**
	 * What goes out and what does not.
	 *
	 * First the blocks that have no Ecolego equivalent at all, then everything
	 * that reads one of them -- an equation that names a block the file does
	 * not have is not a model Ecolego can run -- until nothing more falls.
	 */
	decideBlocks() {
		const { raw, report } = this;
		const skip = (q, why) => { if (!this.skippedBlocks.has(q)) this.skippedBlocks.set(q, why); };

		for (const b of raw.farfields ?? []) {
			if (!b || typeof b !== 'object') continue;
			skip(qnameOf(b), 'a far-field pathway (FARFCOMP) is a transport model of its own, which Ecolego has no block for');
		}
		for (const b of raw.waste_packages ?? []) {
			if (!b || typeof b !== 'object') continue;
			skip(qnameOf(b), 'waste packages and their barriers have no Ecolego block');
		}
		for (const b of raw.events ?? []) {
			if (!b || typeof b !== 'object') continue;
			skip(qnameOf(b), 'a disruptive event and what it does to the model have no Ecolego equivalent');
		}
		for (const collection of COMPONENT_COLLECTIONS) {
			for (const b of raw[collection] ?? []) {
				if (!b || typeof b !== 'object') continue;
				const q = qnameOf(b);
				const dims = Array.isArray(b.index_lists) ? b.index_lists : [];
				const auto = this.autoDimOf(dims);
				if (auto) {
					skip(q, `it is indexed by '${auto}', a list made of the model's own blocks, which Ecolego has no equivalent for`);
					continue;
				}
				if (collection === 'functions' && !(Array.isArray(b.parameters) && b.parameters.some((p) => String(p ?? '').trim()))) {
					skip(q, 'a function with no parameters would be read as an expression, and its calls would not parse');
					continue;
				}
				if (collection === 'lookups') {
					const rule = b.interpolation == null || b.interpolation === ''
						? 'linear' : (interpolationFromEco(b.interpolation) ?? b.interpolation);
					if (!INTERPOLATION_TO_ECO[rule]) {
						skip(q, `its interpolation rule '${b.interpolation}' is not one Ecolego has`);
						continue;
					}
				}
				if (this.usesEnds(b, collection)) {
					skip(q, `it reads '${SOURCE_INDEX}' or '${TARGET_INDEX}', which only a transfer here can`);
				}
			}
		}
		const compartmentNames = new Set((raw.compartments ?? []).map(qnameOf));
		for (const collection of ['transfers', 'inflows']) {
			for (const t of raw[collection] ?? []) {
				if (!t || typeof t !== 'object') continue;
				const q = qnameOf(t);
				const why = this.fluxProblem(t, collection, compartmentNames);
				if (why) skip(q, why);
			}
		}

		// Everything that reads what is left out.
		for (;;) {
			let fell = false;
			for (const [q, { collection, block }] of this.blocks) {
				if (this.skippedBlocks.has(q)) continue;
				if (collection === 'farfields' || collection === 'waste_packages' || collection === 'events') continue;
				const lost = this.readsSkipped(block, collection);
				if (lost) {
					skip(q, `it reads '${lost}', which is left out`);
					fell = true;
					continue;
				}
				if (collection === 'transfers' || collection === 'inflows') {
					const end = [block.from, block.to].find((e) => e != null && this.skippedBlocks.has(this.resolveEnd(e, block)));
					if (end != null) {
						skip(q, `it connects to '${end}', which is left out`);
						fell = true;
					}
				}
			}
			if (!fell) break;
		}

		for (const [q, why] of this.skippedBlocks) {
			const found = this.blocks.get(q);
			report.skip(KIND_WORD[found?.collection] ?? 'block', q, why);
		}
		this.planFluxes();
	}

	/** A connection's end, as a qualified name. */
	resolveEnd(ref, conn) {
		if (ref == null) return null;
		if (this.known(ref)) return ref;
		return resolveReference(ref, conn?.system ?? '', (n) => this.known(n)) ?? ref;
	}

	/** Whether any equation of a block writes `_source_` or `_target_` as an index. */
	usesEnds(block, collection) {
		for (const text of this.equationsOf(block, collection)) {
			let toks;
			try { toks = tokenize(String(text)); } catch (e) { continue; } // an equation that will not tokenize reads nothing
			for (const t of toks) {
				if (t.type === 'index' && (t.value.trim() === SOURCE_INDEX || t.value.trim() === TARGET_INDEX)) return true;
			}
		}
		return false;
	}

	/** Every equation a block holds, block-level and per index. */
	equationsOf(block, collection) {
		const keys = EQUATION_KEYS[collection] ?? [];
		const out = [];
		const take = (holder) => {
			for (const k of keys) {
				const v = holder?.[k];
				if (Array.isArray(v)) { for (const x of v) if (typeof x === 'string') out.push(x); } else if (typeof v === 'string') out.push(v);
			}
		};
		take(block);
		for (const e of Array.isArray(block.entries) ? block.entries : []) take(e);
		const a = block.availability;
		if (a && typeof a === 'object') {
			for (const k of ['limit', 'top', 'bottom']) if (typeof a[k] === 'string') out.push(a[k]);
		}
		return out;
	}

	/** The first block a block's equations name that is left out, or null. */
	readsSkipped(block, collection) {
		const system = block.system ?? '';
		const locals = collection === 'functions' && Array.isArray(block.parameters)
			? new Set(block.parameters.map((p) => String(p ?? '').trim())) : null;
		for (const text of this.equationsOf(block, collection)) {
			let toks;
			try { toks = tokenize(String(text)); } catch (e) { continue; } // an equation that will not tokenize reads nothing
			for (let i = 0; i < toks.length; i++) {
				const t = toks[i];
				if (t.type !== 'ident') continue;
				if (toks[i + 1]?.type === 'lparen' && RESERVED.has(t.value)) continue;
				if (locals?.has(t.value)) continue;
				const q = resolveReference(t.value, system, (n) => this.known(n));
				if (q != null && this.skippedBlocks.has(q)) return q;
			}
		}
		return null;
	}

	/** The dimensions of the block at one end of a connection, or null for the boundary. */
	endDims(ref, conn) {
		if (ref == null) return null;
		const q = this.resolveEnd(ref, conn);
		const found = this.blocks.get(q);
		if (!found) return null;
		return Array.isArray(found.block.index_lists) ? found.block.index_lists : [];
	}

	/** Why a transfer or inflow cannot go out, or null when it can. */
	fluxProblem(t, collection, compartments) {
		const ends = collection === 'inflows' ? [null, t.to] : [t.from ?? null, t.to ?? null];
		for (const [ref, what] of [[ends[0], 'donor'], [ends[1], 'receiver']]) {
			if (ref == null) continue;
			const q = this.resolveEnd(ref, t);
			if (compartments.has(q)) continue;
			const found = this.blocks.get(q);
			if (found?.collection === 'farfields') return `its ${what} is the far-field pathway '${q}', which is left out`;
			if (found?.collection === 'waste_packages') return `its ${what} is the waste package '${q}', which is left out`;
			return `its ${what} '${ref}' is not a compartment of this model`;
		}
		if (ends[0] == null && ends[1] == null) return 'it has neither a donor nor a receiver';
		const dims = Array.isArray(t.index_lists) ? t.index_lists : [];
		const auto = this.autoDimOf(dims);
		if (auto) return `it is indexed by '${auto}', a list made of the model's own blocks, which Ecolego has no equivalent for`;
		const from = this.endDims(ends[0], t);
		const to = this.endDims(ends[1], t);
		if (t.sum_extra_indices === true || t.sum_extra_indices === 'true') {
			const extra = [...(from ? summedDims(this.allLists, dims, from) : []), ...(to ? summedDims(this.allLists, dims, to) : [])];
			if (extra.length) {
				return `it adds its flux up over ${[...new Set(extra)].join(', ')} on the way into or out of an end `
					+ 'that is not indexed by it, which an Ecolego transfer cannot do';
			}
		}
		const shared = sharedDims(this.allLists, from, to);
		if (!shared) {
			return 'its two ends are not indexed alike, so an Ecolego transfer could not be drawn between them';
		}
		const narrowed = sameList(shared.dims, dims) ? null : this.narrowing(dims, shared.dims);
		if (!sameList(shared.dims, dims) && !narrowed) {
			return `it is indexed by ${dims.join(' × ') || 'nothing'}, which is neither what its two ends share `
				+ `(${shared.dims.join(' × ') || 'nothing'}) nor a sub-set of it`;
		}
		const a = t.availability;
		if (collection === 'transfers' && a && typeof a === 'object' && a.scheme) {
			if (a.scheme === 'shared_limit' || a.scheme === 'shared_langmuir') {
				return `its availability is shared over ${a.over ?? 'a group'}, which has no Ecolego equivalent`;
			}
			if (a.scheme !== 'limit' && a.scheme !== 'langmuir') return `its availability scheme '${a.scheme}' is not one this tool knows`;
			const blank = (a.scheme === 'limit' ? ['limit'] : ['top', 'bottom']).filter((k) => String(a[k] ?? '').trim() === '');
			if (blank.length) return `its availability has no ${blank.join(' or ')} to write into its rate`;
			if (narrowed) return 'it is both narrowed and limited by an availability, which cannot be written as one Ecolego transfer';
		}
		return null;
	}

	/**
	 * How each transfer and inflow goes out: its dimensions in the file, its
	 * two ends, and the rows of its table.
	 */
	planFluxes() {
		const { raw, report } = this;
		const usedNames = new Map(); // system -> names taken there
		const taken = (system) => {
			if (!usedNames.has(system)) {
				const set = new Set();
				for (const [q] of this.blocks) if (parentOf(q) === system) set.add(baseName(q));
				for (const path of this.systemPathsList()) if (parentOf(path) === system) set.add(baseName(path));
				usedNames.set(system, set);
			}
			return usedNames.get(system);
		};
		const boundary = (name, system, type) => {
			const set = taken(system);
			let local = `${name}_${type}`;
			for (let n = 2; set.has(local); n++) local = `${name}_${type}_${n}`;
			set.add(local);
			const id = system ? `${system}.${local}` : local;
			this.boundaries.push({ name: local, id, system, type });
			return id;
		};
		for (const collection of ['transfers', 'inflows']) {
			for (const t of raw[collection] ?? []) {
				if (!t || typeof t !== 'object') continue;
				const q = qnameOf(t);
				if (this.skippedBlocks.has(q)) continue;
				const inflow = collection === 'inflows';
				const fromRef = inflow ? null : (t.from ?? null);
				const toRef = t.to ?? null;
				const from = fromRef == null ? null : this.resolveEnd(fromRef, t);
				const to = toRef == null ? null : this.resolveEnd(toRef, t);
				const dims = Array.isArray(t.index_lists) ? [...t.index_lists] : [];
				const fromDims = this.endDims(fromRef, t);
				const toDims = this.endDims(toRef, t);
				const shared = sharedDims(this.allLists, fromDims, toDims);
				const plan = {
					collection, from, to, dims, fileDims: dims, intersection: false,
					narrowed: null, availability: null,
				};
				if (shared && !sameList(shared.dims, dims)) {
					// Already known to be a narrowing: anything else was left out
					// in `fluxProblem`.
					const narrowed = this.narrowing(dims, shared.dims);
					plan.fileDims = shared.dims;
					plan.narrowed = narrowed;
					const onto = narrowed.filter((n) => !n.same).map((n) => n.list);
					report.rewrite(KIND_WORD[collection], q, `it is narrowed onto ${onto.join(', ')}; `
						+ 'written over what its two ends share, with a zero rate outside '
						+ (onto.length === 1 ? 'that sub-set' : 'those sub-sets'));
				}
				// Two ends of different dimensions are joined over what they have
				// in common, which Ecolego works out itself and writes as a list
				// with no id -- see intersectionDims in ./eco.js.
				if (fromDims && toDims && !sameList(fromDims, toDims) && !plan.narrowed) plan.intersection = true;
				const a = t.availability;
				if (!inflow && a && typeof a === 'object' && (a.scheme === 'limit' || a.scheme === 'langmuir')) {
					plan.availability = { ...a, donor: this.referenceFrom(from, t.system ?? '') };
					report.rewrite(KIND_WORD[collection], q, `its availability (${a.unavailable ? 'held back, ' : ''}${a.scheme === 'limit' ? 'a solubility limit' : 'Langmuir sorption'}) `
						+ 'is written into its rate, which then gives the same flux');
				}
				if (inflow) {
					report.rewrite('inflow', q, 'written as a transfer from a source, which is how Ecolego feeds a '
						+ 'compartment from outside; it comes back as a transfer');
				}
				if (from == null) plan.source = boundary(t.name, t.system ?? '', 'source');
				if (to == null) plan.sink = boundary(t.name, t.system ?? '', 'sink');
				if (from == null && !inflow && t.multiply_by_donor === true) {
					report.warn(`'${q}' has no donor and says it multiplies by one; it is written as the absolute flux it is.`);
				}
				this.fluxPlans.set(q, plan);
			}
		}
	}

	/**
	 * A transfer's dimensions as a narrowing of what its ends share -- the same
	 * lists, one or more taken to a sub-set -- or null when it is something
	 * else. Matched by root, as the ends themselves are.
	 */
	narrowing(dims, shared) {
		if (dims.length !== shared.length) return null;
		const rootOf = (n) => lineage(this.allLists, n).root;
		const rest = [...dims];
		const out = [];
		for (const d of shared) {
			const at = rest.findIndex((x) => rootOf(x) === rootOf(d));
			if (at < 0) return null;
			const own = rest.splice(at, 1)[0];
			if (own === d) { out.push({ list: own, of: d, same: true }); continue; }
			// A sub-set of the shared list, however many steps down -- and
			// sub-sets all the way: a grouping on the way is not a narrowing.
			const above = lineage(this.allLists, own).above;
			const at2 = above.findIndex((s) => s.name === d);
			if (at2 < 0 || above.slice(0, at2 + 1).some((s) => s.mapped)) return null;
			out.push({ list: own, of: d, same: false });
		}
		const narrowed = out.filter((n) => !n.same);
		return narrowed.length ? out : null;
	}

	/** How a block is written when referred to from `system`. */
	referenceFrom(target, system) {
		if (target == null) return null;
		const home = parentOf(target);
		if (!home || home === system) {
			const local = baseName(target);
			if (resolveReference(local, system, (n) => this.known(n)) === target) return local;
		}
		return target;
	}

	/** A reference to a block as its id: the qualified name, where it resolves. */
	idOf(ref, system) {
		if (ref == null) return null;
		const text = String(ref).trim();
		if (!/^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(text)) return String(ref);
		return resolveReference(text, system ?? '', (n) => this.known(n)) ?? text;
	}

	/** Every sub-system path, parents before children, in the order the model names them. */
	systemPathsList() {
		if (this.paths) return this.paths;
		const { raw } = this;
		const seen = new Set();
		const out = [];
		const add = (path) => {
			const p = String(path ?? '').split('.').filter(Boolean);
			for (let i = 1; i <= p.length; i++) {
				const at = p.slice(0, i).join('.');
				if (!seen.has(at)) { seen.add(at); out.push(at); }
			}
		};
		for (const s of raw.systems ?? []) add(typeof s === 'string' ? s : s?.name);
		for (const s of raw.transports ?? []) add(typeof s === 'string' ? s : s?.name);
		for (const collection of ALL_COLLECTIONS) {
			for (const b of raw[collection] ?? []) {
				if (this.skippedBlocks.has(qnameOf(b))) continue;
				add(b?.system);
			}
		}
		this.paths = out;
		return out;
	}

	/**
	 * Names this tool's importer would read back differently, said before the
	 * file is used. Its name mapper (`NameMapper` in ./eco.js) keeps index
	 * lists, top-level sub-systems and top-level blocks in one set of names
	 * and numbers the second of two that meet -- and a function's name, which
	 * no block may have, wherever it is.
	 */
	checkNames() {
		const top = new Map();
		const clashes = [];
		const claim = (name, what) => {
			const had = top.get(name);
			if (had) clashes.push(`'${name}' (${had}, ${what})`);
			else top.set(name, what);
		};
		for (const list of this.exportLists) claim(this.listId(list.name), 'index list');
		const reserved = [];
		for (const path of this.systemPathsList()) {
			if (RESERVED.has(baseName(path))) reserved.push(`'${path}'`);
			if (!path.includes('.')) claim(path, 'sub-system');
		}
		for (const collection of [...COMPONENT_COLLECTIONS, 'transfers', 'inflows']) {
			for (const b of this.raw[collection] ?? []) {
				if (!this.goesOut(b) || b.system) continue;
				claim(String(b.name), KIND_WORD[collection]);
			}
		}
		if (clashes.length) {
			this.report.warn(`${clashes.join(', ')}: an index list and something at the top of the model share a `
				+ 'name. This tool’s importer reads the two by one set of names, so reading the file back here '
				+ 'numbers the second of them and rewrites what refers to it.');
		}
		if (reserved.length) {
			this.report.warn(`${reserved.join(', ')} ${reserved.length === 1 ? 'is a sub-system' : 'are sub-systems'} `
				+ 'named after a function, which this tool’s importer numbers when it reads the file back.');
		}
	}

	/** Whether a block of a collection goes out. */
	goesOut(b) { return !!b && typeof b === 'object' && !this.skippedBlocks.has(qnameOf(b)); }

	hasStates() {
		return (this.raw.compartments ?? []).some((c) => this.goesOut(c))
			|| (this.raw.running_means ?? []).some((c) => this.goesOut(c));
	}

	counts() {
		const n = (collection) => (this.raw[collection] ?? []).filter((b) => this.goesOut(b)).length;
		return {
			index_lists: this.exportLists.length,
			compartments: n('compartments'),
			transfers: n('transfers') + n('inflows'),
			parameters: n('parameters'),
			expressions: n('expressions'),
			functions: n('functions'),
			lookups: n('lookups'),
			index_reductions: n('index_reductions'),
			block_reductions: n('block_reductions'),
			min_maxes: n('min_maxes'),
			running_means: n('running_means'),
			snapshots: n('snapshots'),
			delays: n('delays'),
			triggers: n('triggers'),
			systems: this.systemPathsList().length,
			nuclides: this.nuclideNames.length,
		};
	}
}

/** Which of a block's values are equations, for finding what it reads. */
const EQUATION_KEYS = table({
	compartments: ['initial', 'dydt'],
	transfers: ['rate'],
	inflows: ['rate'],
	expressions: ['equation'],
	functions: ['equation'],
	index_reductions: ['target'],
	block_reductions: ['targets'],
	min_maxes: ['target', 'reset_trigger', 'start_trigger', 'stop_trigger'],
	running_means: ['target', 'reset_trigger', 'start_trigger', 'stop_trigger'],
	snapshots: ['target', 'trigger', 'initial'],
	delays: ['target', 'delay'],
	triggers: ['first', 'second'],
});

/** The values each kind of block holds per index: `VALUE_KEYS` in ../domain/project.js. */
const VALUE_KEYS = table({
	compartments: ['initial', 'abstol', 'non_negative', 'dydt'],
	transfers: ['rate', 'multiply_by_donor'],
	inflows: ['rate'],
	expressions: ['equation'],
	parameters: ['value', 'pdf'],
	lookups: ['points'],
	index_reductions: ['target'],
	block_reductions: ['targets'],
	min_maxes: ['target', 'reset_trigger', 'start_trigger', 'stop_trigger'],
	running_means: ['target', 'reset_trigger', 'start_trigger', 'stop_trigger'],
	snapshots: ['target', 'trigger', 'initial'],
	delays: ['target', 'delay'],
	triggers: ['first', 'second', 'direction'],
});

/** What each kind holds when it says nothing: `DEFAULTS` in ../domain/project.js. */
const VALUE_DEFAULTS = table({
	compartments: { initial: '0', non_negative: true },
	transfers: { rate: '0', multiply_by_donor: true },
	inflows: { rate: '0' },
	expressions: { equation: '0' },
	parameters: { value: 0 },
	lookups: { points: [] },
	index_reductions: { target: null },
	block_reductions: { targets: [] },
	min_maxes: { target: '0' },
	running_means: { target: '0' },
	snapshots: { target: '0', initial: '0' },
	delays: { target: '0', delay: '0' },
	triggers: { first: '0', second: '0', direction: 'rising' },
});

/** Whether two dimension lists are the same lists in the same order. */
function sameList(a, b) {
	return a.length === b.length && a.every((x, i) => x === b[i]);
}

// --- the table of a block ----------------------------------------------------------

/**
 * A block's values as Ecolego's table holds them: the value of every column at
 * the default, and one row per index combination an entry reaches, each with
 * the value every column has there.
 *
 * `valueAt` in ../domain/project.js is the rule: for each value on its own,
 * the entry naming the most of the block's lists wins, the first of equals,
 * and the block's own value where none applies. An entry with no index at all
 * is the widest match there is, so it stands in for the block's own value.
 *
 * @returns {{defaults: object, rows: Array<{combo: string[], values: object}>, dropped: number}}
 */
function tableOf(block, collection, dims, ctx, { lists = null } = {}) {
	const keys = VALUE_KEYS[collection];
	const listOf = lists ?? ((d) => ctx.indicesOf(d));
	const indexSets = dims.map((d) => new Set(listOf(d)));
	const defaults = {};
	for (const k of keys) {
		defaults[k] = block[k] !== undefined ? block[k] : VALUE_DEFAULTS[collection]?.[k];
	}
	const valid = [];
	let dropped = 0;
	for (const e of Array.isArray(block.entries) ? block.entries : []) {
		if (!e || typeof e !== 'object') continue;
		const index = entryIndex(e.index, dims, ctx.nuclideListName);
		if (!index) { dropped++; continue; }
		const names = Object.keys(index);
		if (names.some((l) => !dims.includes(l) || !indexSets[dims.indexOf(l)].has(index[l]))) { dropped++; continue; }
		if (!keys.some((k) => Object.prototype.hasOwnProperty.call(e, k))) continue;
		valid.push({ index, entry: e, score: names.length });
	}
	// The widest match: an entry keyed by nothing replaces the block's value.
	for (const k of keys) {
		const wide = valid.find((v) => v.score === 0 && Object.prototype.hasOwnProperty.call(v.entry, k));
		if (wide) defaults[k] = wide.entry[k];
	}
	const full = new Map();
	const partial = [];
	const keyOf = (combo) => combo.join('\u0000');
	for (const v of valid) {
		if (v.score === 0) continue;
		if (v.score === dims.length) {
			const at = keyOf(dims.map((d) => v.index[d]));
			if (!full.has(at)) full.set(at, []);
			full.get(at).push(v);
		} else {
			partial.push(v);
		}
	}
	// The combinations entries reach, in the order the entries are written.
	const combos = [];
	const seen = new Set();
	for (const v of valid) {
		if (v.score === 0) continue;
		const choices = dims.map((d, i) => (v.index[d] !== undefined ? [v.index[d]] : [...indexSets[i]]));
		for (const combo of product(choices)) {
			const at = keyOf(combo);
			if (seen.has(at)) continue;
			seen.add(at);
			combos.push(combo);
		}
	}
	const rows = combos.map((combo) => {
		const values = {};
		const exact = full.get(keyOf(combo)) ?? [];
		for (const k of keys) {
			const own = exact.find((v) => Object.prototype.hasOwnProperty.call(v.entry, k));
			if (own) { values[k] = own.entry[k]; continue; }
			let best = null;
			for (const v of partial) {
				if (!Object.prototype.hasOwnProperty.call(v.entry, k)) continue;
				if (!dims.every((d, i) => v.index[d] === undefined || v.index[d] === combo[i])) continue;
				if (!best || v.score > best.score) best = v;
			}
			values[k] = best ? best.entry[k] : defaults[k];
		}
		return { combo, values };
	});
	return { defaults, rows, dropped, expanded: partial.length > 0 };
}

/** Every combination of one choice from each list, the first varying slowest. */
function product(choices) {
	let out = [[]];
	for (const options of choices) {
		const next = [];
		for (const head of out) for (const o of options) next.push([...head, o]);
		out = next;
	}
	return out;
}

/**
 * An entry's index as an object keyed by list, however it was written; null
 * for one that cannot be read. `normaliseEntryIndex` in ../domain/project.js.
 */
function entryIndex(index, dims, nuclideListName) {
	if (index == null) return {};
	if (typeof index === 'string') {
		const list = dims.length === 1 ? dims[0] : nuclideListName;
		return list ? { [list]: index } : null;
	}
	if (Array.isArray(index)) {
		if (index.length !== dims.length) return null;
		const out = {};
		index.forEach((v, i) => { if (v != null) out[dims[i]] = v; });
		return out;
	}
	if (typeof index !== 'object') return null;
	return { ...index };
}

// --- numbers and text ---------------------------------------------------------------

/**
 * A number as Java's `Double.toString` writes it, which is how an Ecolego file
 * writes every number: the shortest digits that read back as the same double,
 * plain between 10^-3 and 10^7 with at least one digit after the point
 * (`1000.0`, `0.001`), and `1.0E-4` beyond.
 */
export function javaDouble(x) {
	const v = Number(x);
	if (Number.isNaN(v)) return 'NaN';
	if (v === Infinity) return 'Infinity';
	if (v === -Infinity) return '-Infinity';
	if (v === 0) return Object.is(v, -0) ? '-0.0' : '0.0';
	const sign = v < 0 ? '-' : '';
	const a = Math.abs(v);
	const [mantissa, exponent] = a.toExponential().split('e');
	const digits = mantissa.replace('.', '');
	const e = Number(exponent);
	if (a >= 1e-3 && a < 1e7) {
		if (e >= 0) {
			const whole = digits.slice(0, e + 1).padEnd(e + 1, '0');
			return `${sign}${whole}.${digits.slice(e + 1) || '0'}`;
		}
		return `${sign}0.${'0'.repeat(-e - 1)}${digits}`;
	}
	return `${sign}${digits[0]}.${digits.slice(1) || '0'}E${e}`;
}

/** Java's `Arrays.toString` of doubles: `[0.0, 500.0]`. */
function javaArray(values) {
	return `[${values.map(javaDouble).join(', ')}]`;
}

const bits = new Float64Array(1);
const words = new BigInt64Array(bits.buffer);

/** The double `n` steps along from `x` (positive and finite). */
function ulpStep(x, n) {
	bits[0] = x;
	words[0] += BigInt(n);
	return bits[0];
}

/**
 * A half-life in seconds that the importer's division reads back as exactly
 * the years it was: `years × SECONDS_PER_YEAR` where that is so, and otherwise
 * the nearest double within a few steps of it that is.
 */
export function secondsFor(years) {
	const s = years * SECONDS_PER_YEAR;
	if (!Number.isFinite(s) || s <= 0 || s / SECONDS_PER_YEAR === years) return s;
	for (let k = 1; k <= 4; k++) {
		for (const c of [ulpStep(s, k), ulpStep(s, -k)]) {
			if (c / SECONDS_PER_YEAR === years) return c;
		}
	}
	return s;
}

/**
 * A GUID for one thing in the file: four CRC-32s of its key and the project's
 * name, laid out as a UUID with the version nibble that marks a
 * vendor-defined one. Deterministic, so the same model exports to the same
 * bytes, and different between two differently named models.
 */
export function guidFor(project, key) {
	const enc = new TextEncoder();
	const hex = (salt) => crc32(enc.encode(`${salt}\u0000${project}\u0000${key}`))
		.toString(16).padStart(8, '0').toUpperCase();
	const a = hex('a');
	const b = hex('b');
	const c = hex('c');
	const d = hex('d');
	const variant = ((parseInt(c[0], 16) & 0x3) | 0x8).toString(16).toUpperCase();
	return `${a}-${b.slice(0, 4)}-8${b.slice(5, 8)}-${variant}${c.slice(1, 4)}-${c.slice(4, 8)}${d}`;
}

/**
 * Text XML 1.0 can hold: the control characters it forbids outright, even as
 * references, become U+FFFD. A model's text is typed, and none of them has a
 * meaning in it.
 */
function xmlSafe(text) {
	return String(text).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/g, '\ufffd');
}

function escapeAttr(text) {
	return xmlSafe(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;').replace(/\t/g, '&#9;').replace(/\n/g, '&#10;').replace(/\r/g, '&#13;');
}

function escapeText(text) {
	return xmlSafe(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
		.replace(/\r/g, '&#13;');
}

/** CDATA, which is how Ecolego writes an equation; one that holds `]]>` is split around it. */
function cdata(text) {
	return `<![CDATA[${xmlSafe(text).replace(/\r/g, '\n').split(']]>').join(']]]]><![CDATA[>')}]]>`;
}

/** A writer of indented XML, one element per line, as Ecolego's persister lays it out. */
class XmlWriter {
	constructor() {
		this.lines = ['<?xml version="1.0" encoding="UTF-8"?>'];
		this.depth = 0;
	}

	static attrs(pairs) {
		return (pairs ?? []).filter(([, v]) => v != null).map(([k, v]) => ` ${k}="${escapeAttr(v)}"`).join('');
	}

	line(text) { this.lines.push(`${'\t'.repeat(this.depth)}${text}`); }
	open(name, attrs) { this.line(`<${name}${XmlWriter.attrs(attrs)}>`); this.depth++; }
	close(name) { this.depth--; this.line(`</${name}>`); }
	empty(name, attrs) { this.line(`<${name}${XmlWriter.attrs(attrs)}/>`); }
	/** An element holding plain text; empty text is an empty element. */
	text(name, value, attrs) {
		this.line(`<${name}${XmlWriter.attrs(attrs)}>${escapeText(value ?? '')}</${name}>`);
	}
	/** An element holding CDATA, or nothing when the value is empty. */
	cdata(name, value, attrs) {
		const v = value == null ? '' : String(value);
		this.line(`<${name}${XmlWriter.attrs(attrs)}>${v === '' ? '' : cdata(v)}</${name}>`);
	}
	/** The finished document. */
	document() { return `${this.lines.join('\n')}\n`; }
}

// --- the sections -------------------------------------------------------------------

function writeProjectProperties(w, raw, ctx, options) {
	const name = ctx.projectName;
	w.open('project-properties', [['name', name]]);
	w.cdata('guid', guidFor(name, 'project'));
	if (options.modified instanceof Date && Number.isFinite(options.modified.getTime())) {
		w.text('modification-date', String(options.modified.getTime()));
	}
	const description = String(raw.description ?? '').trim();
	if (description) w.cdata('property', description, [['name', 'comment'], ['type', 'string']]);
	w.close('project-properties');
}

/** `Cs-137` -> [55, 137]; null for a name that is not a nuclide's. */
function nuclideNumbers(name) {
	const m = /^([A-Za-z]{1,3})-?(\d+)/.exec(String(name ?? '').trim());
	if (!m) return null;
	const symbol = m[1][0].toUpperCase() + m[1].slice(1).toLowerCase();
	const z = ELEMENT_SYMBOLS.indexOf(symbol) + 1;
	return z > 0 ? [z, Number(m[2])] : null;
}

function writeMaterials(w, ctx) {
	const unit = String(ctx.raw.decay_unit ?? 'Bq').trim() === 'mol' ? 'mol' : 'Bq';
	w.open('material-model');
	for (const m of ctx.materials) {
		const id = ctx.indexId(ctx.material.name, m.name);
		if (m.nuclide) {
			w.open('nuclide', [['name', m.name]]);
			w.text('id', id);
			w.text('unit', unit);
			w.text('half-life', m.years != null && Number.isFinite(m.years) ? javaDouble(secondsFor(m.years)) : 'Infinity');
			const za = nuclideNumbers(m.name);
			if (za) { w.text('z', String(za[0])); w.text('a', String(za[1])); }
			w.close('nuclide');
		} else {
			w.open('material', [['name', m.name]]);
			w.text('id', id);
			if (m.unit) w.text('unit', m.unit);
			w.close('material');
		}
	}
	w.close('material-model');
}

function writeIndexLists(w, ctx) {
	const { report } = ctx;
	w.open('index-list-model');
	for (const list of ctx.exportLists) {
		const id = ctx.listId(list.name);
		w.open('index-list', [['name', id]]);
		w.text('id', id);
		const flags = [
			[list === ctx.material, 'MATERIALS'],
			[list === ctx.nuclideList, 'RADIONUCLIDES'],
			[!!list.for_scenarios, 'SCENARIOS'],
			[list === ctx.elementList, 'ELEMENTS'],
		].filter(([on]) => on).map(([, t]) => t);
		if (flags.length) {
			w.text('property', flags[0], [['name', 'predefined-type'], ['type', PREDEFINED_TYPE]]);
			if (flags.length > 1) {
				report.warn(`'${list.name}' is marked as more than one of Ecolego's own lists `
					+ `(${flags.join(', ')}); it is written as ${flags[0]}.`);
			}
		}
		// The radionuclide list is Ecolego's own: every material that decays.
		const indices = list === ctx.nuclideList ? nuclideIndices(ctx) : (list.indices ?? []);
		for (const i of indices) {
			const name = indexName(i);
			if (name == null) continue;
			const ownList = list === ctx.nuclideList && !(list.indices ?? []).some((x) => indexName(x) === name);
			const iid = ownList ? ctx.indexId(ctx.material.name, name) : ctx.indexId(list.name, name);
			w.open('index', [['name', String(name).trim()], ['enabled', indexOn(i) ? 'true' : 'false']]);
			w.text('id', iid);
			w.close('index');
		}
		if (list.sub_set_of && ctx.listIds.has(list.sub_set_of)) {
			w.empty('sub-set', [['of', ctx.listId(list.sub_set_of)]]);
		} else if (list.sub_set_of) {
			report.warn(`'${list.name}' is a sub-set of '${list.sub_set_of}', which is not written; it goes out as a list of its own.`);
		}
		const mapping = list.mapping && typeof list.mapping === 'object' ? list.mapping : null;
		if (mapping?.to && ctx.listIds.has(mapping.to)) {
			w.open('mapping', [['to', ctx.listId(mapping.to)]]);
			for (const pair of Array.isArray(mapping.pairs) ? mapping.pairs : []) {
				if (pair?.from == null || pair?.to == null) continue;
				w.empty('map', [['from', ctx.indexId(list.name, pair.from)], ['to', ctx.indexId(mapping.to, pair.to)]]);
			}
			w.close('mapping');
		} else if (list.mapping) {
			report.warn(`'${list.name}' maps onto a list that is not written; it goes out as a list of its own.`);
		}
		const comment = String(list.comment ?? '').trim();
		if (comment && list !== ctx.elementList && !BUILT_IN_COMMENT.test(comment)) {
			ctx.listComments = (ctx.listComments ?? 0) + 1;
		}
		w.close('index-list');
	}
	w.close('index-list-model');
	if (ctx.listComments) {
		report.warn(`${ctx.listComments} index list comment(s) were left out: an Ecolego index list has no comment.`);
	}
}

/** The radionuclide list's indices as Ecolego keeps it: the model's own, then any other material that decays. */
function nuclideIndices(ctx) {
	const own = ctx.nuclideList.indices ?? [];
	const names = new Set(own.map(indexName));
	const catalogue = new Set(ctx.materials.map((m) => m.name));
	const out = own.filter((i) => catalogue.has(indexName(i)));
	for (const m of ctx.materials) {
		if (m.nuclide && !names.has(m.name)) out.push({ name: m.name, enabled: true });
	}
	return out;
}

function writeDecayChains(w, ctx) {
	w.open('nuclide-decay-model');
	for (const [parent, daughter, ratio] of ctx.chains) {
		w.empty('decay-pair', [['parent', parent], ['daughter', daughter], ['rate', javaDouble(ratio)]]);
	}
	w.close('nuclide-decay-model');
}

function writeHierarchy(w, ctx) {
	const { raw } = ctx;
	const transports = new Set((raw.transports ?? []).map((s) => (typeof s === 'string' ? s : s?.name)));
	const off = new Set(Array.isArray(raw.disabled_systems) ? raw.disabled_systems.map((p) => String(p ?? '').trim()) : []);
	w.open('hierarchy-model');
	// The root first, and with neither a name nor an id: it is not a level of
	// anything, and a block at the top has no <sub-system> to name it by.
	w.open('sub-system-block');
	w.cdata('guid', guidFor(ctx.projectName, 'root'));
	w.close('sub-system-block');
	for (const path of ctx.systemPathsList()) {
		w.open('sub-system-block', [['name', baseName(path)], ['type', transports.has(path) ? 'transport' : null]]);
		w.text('id', path);
		w.cdata('guid', guidFor(ctx.projectName, `system:${path}`));
		if (parentOf(path)) w.text('sub-system', parentOf(path));
		w.text('enabled', off.has(path) ? 'false' : 'true');
		w.close('sub-system-block');
	}
	w.close('hierarchy-model');
}

// --- blocks ---------------------------------------------------------------------------

function writeBlocks(w, ctx) {
	const { raw } = ctx;
	w.open('block-model');
	for (const collection of COMPONENT_COLLECTIONS) {
		for (const block of raw[collection] ?? []) {
			if (!block || typeof block !== 'object') continue;
			if (ctx.skippedBlocks.has(qnameOf(block))) continue;
			writeComponent(w, ctx, block, collection);
		}
	}
	for (const b of ctx.boundaries) {
		w.open('component', [['name', b.name], ['type', b.type], ['dimension', '0'], ['index-lists', '']]);
		w.text('id', b.id);
		w.cdata('guid', guidFor(ctx.projectName, `block:${b.id}`));
		if (b.system) w.text('sub-system', b.system);
		w.text('enabled', 'true');
		w.close('component');
	}
	for (const collection of ['transfers', 'inflows']) {
		for (const t of raw[collection] ?? []) {
			if (!t || typeof t !== 'object') continue;
			const plan = ctx.fluxPlans.get(qnameOf(t));
			if (plan) writeConnection(w, ctx, t, plan);
		}
	}
	w.close('block-model');
	if (ctx.expandedEntries) {
		ctx.report.rewrite('values per index', `${ctx.expandedEntries} block(s)`, 'an entry that names only '
			+ 'some of a block’s index lists is written as one row per index combination it covers, '
			+ 'which is how an Ecolego table holds it');
	}
	if (ctx.droppedEntries) {
		ctx.report.warn(`${ctx.droppedEntries} entr${ctx.droppedEntries === 1 ? 'y was' : 'ies were'} `
			+ 'keyed by an index list or index the block is not indexed by, and took no part in the run; '
			+ `${ctx.droppedEntries === 1 ? 'it was' : 'they were'} not written.`);
	}
}

/** The dimension attributes of a block: how many lists, and their ids. */
function dimAttrs(ctx, dims, intersection = false) {
	return [['dimension', String(dims.length)], ['index-lists', intersection ? '' : dims.map((d) => ctx.listId(d)).join(',')]];
}

/** The id, GUID, place, switch, unit and comment every block carries. */
function writeCommon(w, ctx, block, q) {
	w.text('id', q);
	w.cdata('guid', guidFor(ctx.projectName, `block:${q}`));
	if (block.system) w.text('sub-system', block.system);
	w.text('enabled', block.enabled === false ? 'false' : 'true');
	const unit = String(block.unit ?? '').trim();
	if (unit) w.text('unit', unit);
	const comment = String(block.comment ?? '').trim();
	if (comment) w.cdata('comment', comment);
}

/** The key of an entry row: the ids of its indices, in the block's order. */
function rowKey(ctx, dims, combo) {
	return combo.map((name, i) => ctx.indexId(dims[i], name)).join(',');
}

function writeComponent(w, ctx, block, collection) {
	const q = qnameOf(block);
	const transports = new Set((ctx.raw.transports ?? []).map((s) => (typeof s === 'string' ? s : s?.name)));
	const inTransport = transports.has(block.system ?? '');
	let role = collection === 'compartments' && ['begin', 'end'].includes(block.transport) ? block.transport
		: collection === 'expressions' && ['number', 'counter', 'operation'].includes(block.transport) ? block.transport
			: null;
	if (role && !inTransport) {
		ctx.report.warn(`'${q}' is marked as the ${role} of a transport but is not inside one; it is written as a plain ${KIND_WORD[collection]}.`);
		role = null;
	}
	const type = role === 'begin' ? 'transport-begin' : role === 'end' ? 'transport-end'
		: role === 'number' ? 'transport-number' : role === 'counter' ? 'transport-element-counter'
			: role === 'operation' ? 'transport-operation' : ECO_TYPE[collection];
	const dims = collection === 'functions' ? [] : (Array.isArray(block.index_lists) ? block.index_lists : []);
	w.open('component', [['name', block.name], ['type', type], ...dimAttrs(ctx, dims)]);
	writeCommon(w, ctx, block, q);

	if (role === 'counter') { w.close('component'); return; }
	if (role === 'operation') {
		const op = String(block.operation ?? '').trim().toLowerCase();
		w.cdata('operation', op === 'sum' || op === 'point' ? 'SUM' : 'MEAN');
		const arg = String(block.argument ?? '').trim().toLowerCase();
		const args = arg === 'range' ? [['from', 'From'], ['to', 'To']] : arg === 'point' ? [['point', 'Point']] : [];
		for (const [key, label] of args) {
			w.open('argument');
			w.text('argument-key', key);
			w.text('argument-name', label);
			w.close('argument');
		}
		w.close('component');
		return;
	}
	if (role === 'number') w.text('evaluation-mode', 'SIMULATION');

	const table = collection === 'functions' ? null : tableOf(block, collection, dims, ctx);
	if (table?.expanded) ctx.expandedEntries = (ctx.expandedEntries ?? 0) + 1;
	if (table?.dropped) ctx.droppedEntries = (ctx.droppedEntries ?? 0) + table.dropped;
	const system = block.system ?? '';

	switch (collection) {
		case 'parameters': {
			writeParameterRows(w, ctx, block, q, dims, table);
			break;
		}
		case 'compartments': {
			w.text('handle-decay', block.handle_decay === false ? 'false' : 'true');
			writeCompartmentRows(w, ctx, q, dims, table);
			break;
		}
		case 'expressions': {
			writeRows(w, ctx, dims, table, 'expression', (values) => {
				w.cdata('equation', equationText(values.equation, '0'));
			});
			break;
		}
		case 'functions': {
			for (const p of block.parameters ?? []) {
				const name = String(p ?? '').trim();
				if (!name) continue;
				w.open('argument');
				w.text('argument-key', name);
				w.text('argument-name', name);
				w.close('argument');
			}
			w.open('entry', [['type', 'expression']]);
			w.cdata('equation', equationText(block.equation, ''));
			w.close('entry');
			break;
		}
		case 'lookups': {
			const rule = block.interpolation == null || block.interpolation === ''
				? 'linear' : (interpolationFromEco(block.interpolation) ?? block.interpolation);
			w.cdata('lookup-option', INTERPOLATION_TO_ECO[rule]);
			w.text('lookup-cyclic', block.cyclic === true || block.cyclic === 'true' ? 'true' : 'false');
			const argument = block.argument == null ? '' : String(block.argument).trim();
			if (argument) {
				w.open('argument');
				w.text('argument-key', argument);
				w.text('argument-name', argument);
				w.close('argument');
			}
			writeRows(w, ctx, dims, table, 'lookup-table', (values) => {
				const pts = lookupPoints(values.points, ctx, q);
				w.cdata('lookup-table-time-points', javaArray(pts.map((p) => p[0])));
				w.cdata('lookup-table-values', javaArray(pts.map((p) => p[1])));
			});
			break;
		}
		case 'index_reductions': {
			const op = operationOf(block.operation);
			w.cdata('operation', OPERATION_TO_ECO[op] ?? 'SUM');
			if (block.percentile != null && block.percentile !== '' && Number.isFinite(Number(block.percentile))) {
				w.text('percentile', javaDouble(Number(block.percentile)));
			}
			writeRows(w, ctx, dims, table, 'expression', (values) => {
				w.cdata('equation', values.target == null ? '' : ctx.idOf(values.target, system));
			});
			break;
		}
		case 'block_reductions': {
			const op = operationOf(block.operation);
			w.cdata('operation', OPERATION_TO_ECO[op === 'percentile' ? 'sum' : op] ?? 'SUM');
			writeRows(w, ctx, dims, table, 'expression', (values) => {
				w.cdata('equation', targetsOf(values.targets).map((t) => ctx.idOf(t, system)).join('+'));
			});
			break;
		}
		case 'min_maxes':
		case 'running_means': {
			if (collection === 'min_maxes') {
				w.cdata('operation', (extremeFromEco(block.operation) ?? 'max') === 'min' ? 'MIN' : 'MAX');
			}
			writeRows(w, ctx, dims, table, collection === 'min_maxes' ? 'min-max' : 'running-mean', (values) => {
				w.cdata('target-expression', targetText(ctx, values.target, system));
				for (const [key, tag] of [['reset_trigger', 'reset-event'], ['start_trigger', 'start-recording-event'], ['stop_trigger', 'stop-recording-event']]) {
					if (values[key] != null && String(values[key]).trim() !== '') w.cdata(tag, ctx.idOf(values[key], system));
				}
			});
			break;
		}
		case 'snapshots': {
			writeRows(w, ctx, dims, table, 'snapshot', (values) => {
				w.cdata('snapshot-target', targetText(ctx, values.target, system));
				if (values.trigger != null && String(values.trigger).trim() !== '') w.cdata('snapshot-event', ctx.idOf(values.trigger, system));
				w.cdata('snapshot-initial-value', equationText(values.initial, '0'));
			});
			break;
		}
		case 'delays': {
			writeRows(w, ctx, dims, table, 'delay', (values) => {
				w.cdata('delay-target', targetText(ctx, values.target, system));
				w.cdata('delay-time', equationText(values.delay, '0'));
			});
			break;
		}
		case 'triggers': {
			const directions = new Set();
			writeRows(w, ctx, dims, table, 'discrete-event', (values) => {
				w.cdata('first-expression', equationText(values.first, '0'));
				w.cdata('second-expression', equationText(values.second, '0'));
				const dir = values.direction == null || values.direction === ''
					? 'rising' : (directionFromEco(values.direction) ?? values.direction);
				directions.add(DIRECTION_TO_ECO[dir] ?? 'RIGHT');
				w.cdata('direction', DIRECTION_TO_ECO[dir] ?? 'RIGHT');
			});
			if (directions.size > 1) {
				ctx.report.warn(`'${q}' fires in a different direction at some indices. The file says so index `
					+ 'by index; this tool reads back only the block’s own direction.');
			}
			break;
		}
		default:
			break;
	}
	w.close('component');
}

/** An equation as text -- a number written as JavaScript writes it -- and nothing as the default. */
function equationText(value, fallback) {
	return value == null ? fallback : String(value);
}

/** A recorder's target: an equation, with a single reference written as the block's id. */
function targetText(ctx, value, system) {
	const text = equationText(value, '0');
	return /^\s*[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*\s*$/.test(text) ? ctx.idOf(text, system) : text;
}

function operationOf(raw) {
	if (raw == null || raw === '') return 'sum';
	return operationFromEco(raw) ?? String(raw);
}

function targetsOf(targets) {
	if (targets == null) return [];
	const list = typeof targets === 'string' ? targets.split('+') : Array.isArray(targets) ? targets : [];
	return list.map((t) => String(t).trim()).filter((t) => t !== '');
}

/**
 * A table's points as number pairs sorted by time, as Ecolego keeps a table.
 * A point's own distribution is counted, for the report, and not written.
 */
function lookupPoints(points, ctx, q) {
	let pairs = Array.isArray(points) ? points : [];
	if (pairs.length === 2 && Array.isArray(pairs[0]) && Array.isArray(pairs[1])
		&& pairs[0].length === pairs[1].length
		&& pairs[0].every((v) => typeof v === 'number' || typeof v === 'string')
		&& pairs[0].length !== 2) {
		pairs = pairs[0].map((x, i) => [x, pairs[1][i]]);
	}
	const out = [];
	for (const p of pairs) {
		const [x, y, pdf] = Array.isArray(p) ? p : [p?.x, p?.y, p?.pdf];
		if (pdf) {
			ctx.report.skip('distribution', q, 'a distribution on a point of a lookup table has no Ecolego '
				+ 'equivalent; the points keep their values');
		}
		out.push([Number(x), Number(y)]);
	}
	const sorted = out.map((p, i) => [p, i]).sort((a, b) => a[0][0] - b[0][0] || a[1] - b[1]).map(([p]) => p);
	if (sorted.some((p, i) => p !== out[i])) {
		ctx.report.rewrite('lookup table', q, 'its points are written in order of time, as Ecolego keeps a table');
	}
	return sorted;
}

/** Writes a block's default entry and its rows. */
function writeRows(w, ctx, dims, table, type, body) {
	w.open('entry', [['type', type]]);
	body(table.defaults);
	w.close('entry');
	for (const row of table.rows) {
		w.open('entry', [['type', type], ['index', rowKey(ctx, dims, row.combo)]]);
		body(row.values);
		w.close('entry');
	}
}

function writeParameterRows(w, ctx, block, q, dims, table) {
	// An index with no distribution in the file is read back with the
	// block's own, so an index whose own is left out -- or that has none on
	// purpose -- beside a block distribution that is written is worth saying.
	const shared = pdfFor(table.defaults.pdf, ctx, q) != null;
	let inherits = false;
	const body = (values) => {
		const v = values.value;
		const n = typeof v === 'number' ? v : Number(v);
		if (typeof v === 'string' && v.trim() !== '' && !Number.isFinite(n) && !/^\s*[+-]?infinity\s*$/i.test(v)) {
			ctx.report.warn(`'${q}' holds '${v}', which is not a number; it was written as it is.`);
			w.cdata('value', v);
		} else {
			w.cdata('value', javaDouble(v == null || v === '' ? 0 : n));
		}
		const pdf = pdfFor(values.pdf, ctx, q);
		if (pdf) {
			w.open('pdf', [['function', pdf.kind]]);
			w.cdata('pdf-value', pdf.text);
			w.close('pdf');
		} else if (values !== table.defaults && shared) {
			inherits = true;
		}
	};
	writeRows(w, ctx, dims, table, 'parameter', body);
	if (inherits) {
		ctx.report.warn(`'${q}' has an index with no distribution in the file beside a block that has one; `
			+ 'this tool reads that index back with the block’s distribution.');
	}
}

function writeCompartmentRows(w, ctx, q, dims, table) {
	const floors = new Set();
	const body = (values) => {
		w.cdata('initial-condition', equationText(values.initial, '0'));
		const on = values.non_negative !== false && values.non_negative !== 'false' && values.non_negative !== 0;
		floors.add(on);
		w.text('lower-saturation', on ? '0.0' : NO_FLOOR);
		w.text('upper-saturation', '');
		const tol = values.abstol;
		const t = tol == null || tol === '' ? null : Number(tol);
		w.text('abs-tol', t != null && Number.isFinite(t) && t > 0 ? javaDouble(t) : '');
		const dydt = values.dydt == null ? '' : String(values.dydt).trim();
		w.cdata('differential-equation', dydt);
	};
	writeRows(w, ctx, dims, table, 'compartment', body);
	if (floors.size > 1) {
		ctx.report.warn(`'${q}' may go negative at some indices and not at others. The file says so index `
			+ 'by index; this tool reads it back as one setting for the whole block, which may go negative.');
	}
}

/**
 * A distribution in Ecolego's spelling, or null for one that has none.
 *
 * The expression is Ecolego's, `logt(min=1.0E-5,max=0.001,mode=1.0E-4)`, with
 * the kind in `function=`. A truncation stated as percentiles of the curve is
 * written as the values those percentiles fall at, which cuts the curve in the
 * same place; a correlation group has no Ecolego spelling and is left off.
 */
function pdfFor(spec, ctx, q) {
	if (!spec || typeof spec !== 'object') return null;
	const meta = kindInfo(spec.kind);
	if (!meta) return null;
	if (spec.kind === 'dtriang' || spec.kind === 'logdt') {
		ctx.report.skip('distribution', q, `'${meta.label}' is not a shape Ecolego has; the value is kept`);
		return null;
	}
	const bitsOut = [];
	if (spec.kind === 'pg') {
		const values = (Array.isArray(spec.values) ? spec.values : []).map(Number).filter((v) => Number.isFinite(v));
		bitsOut.push(`values=${values.map(javaDouble).join(';')}`);
	} else {
		for (const p of meta.params) {
			const v = spec.params?.[p.key];
			bitsOut.push(v == null || v === '' ? p.key : `${p.key}=${javaDouble(Number(v))}`);
		}
	}
	let trmin = spec.trmin == null || spec.trmin === '' ? null : Number(spec.trmin);
	let trmax = spec.trmax == null || spec.trmax === '' ? null : Number(spec.trmax);
	const pmin = spec.pmin == null || spec.pmin === '' ? null : Number(spec.pmin);
	const pmax = spec.pmax == null || spec.pmax === '' ? null : Number(spec.pmax);
	if (pmin != null || pmax != null) {
		if (spec.kind !== 'pg' && complete(spec)) {
			if (pmin != null) {
				const at = quantile(spec, pmin);
				trmin = trmin == null ? at : Math.max(trmin, at);
			}
			if (pmax != null) {
				const at = quantile(spec, pmax);
				trmax = trmax == null ? at : Math.min(trmax, at);
			}
			ctx.report.rewrite('distribution', q, 'its truncation at percentiles of the curve is written as the '
				+ 'values those percentiles fall at, which cut it in the same place');
		} else {
			ctx.report.skip('truncation', q, 'a truncation at percentiles of a distribution that is not filled in, '
				+ 'or of a list, has no value to be written as');
		}
	}
	if (trmin != null && !Number.isNaN(trmin)) bitsOut.push(`trmin=${javaDouble(trmin)}`);
	if (trmax != null && !Number.isNaN(trmax)) bitsOut.push(`trmax=${javaDouble(trmax)}`);
	if (spec.group != null && String(spec.group).trim() !== '') {
		ctx.report.skip('correlation group', q, `the group '${String(spec.group).trim()}' has no Ecolego spelling; `
			+ 'its members are sampled independently there');
	}
	if (spec.kind === 'pg') {
		bitsOut.push(`inorder=${spec.inorder === false ? 'false' : 'true'}`);
		const pos = Number(spec.pos ?? 0);
		bitsOut.push(`pos=${Number.isFinite(pos) ? String(Math.round(pos)) : '0'}`);
	}
	return { kind: spec.kind, text: `${meta.expr}(${bitsOut.join(',')})` };
}

function writeConnection(w, ctx, t, plan) {
	const q = qnameOf(t);
	const dims = plan.fileDims;
	w.open('connection', [
		['name', t.name], ['type', 'transfer'],
		['source', plan.from ?? plan.source], ['target', plan.to ?? plan.sink],
		...dimAttrs(ctx, dims, plan.intersection),
	]);
	writeCommon(w, ctx, t, q);
	const collection = plan.collection === 'inflows' ? 'inflows' : 'transfers';
	const absolute = plan.from == null;
	const rate = (text) => availabilityRate(equationText(text, '0'), plan.availability);
	const donor = (values) => (absolute ? false
		: values.multiply_by_donor !== false && values.multiply_by_donor !== 'false' && values.multiply_by_donor !== 0);
	const body = (values) => {
		w.cdata('transfer-equation', rate(values.rate));
		w.text('multiply-with-donor', donor(values) ? 'true' : 'false');
	};
	if (plan.narrowed) {
		// Over what the ends share, and nothing moves outside the sub-set.
		const table = tableOf(t, collection, plan.dims, ctx);
		const own = (combo) => {
			const tuple = {};
			plan.narrowed.forEach((n, i) => { tuple[n.list] = combo[i]; });
			return tuple;
		};
		const inside = plan.narrowed.map((n) => new Set(ctx.indicesOf(n.list)));
		w.open('entry', [['type', 'transfer']]);
		w.cdata('transfer-equation', '0');
		w.text('multiply-with-donor', donor(table.defaults) ? 'true' : 'false');
		w.close('entry');
		const shared = plan.narrowed.map((n) => ctx.indicesOf(n.of));
		for (const combo of product(shared)) {
			if (!combo.every((name, i) => inside[i].has(name))) continue;
			const tuple = own(combo);
			const values = valueAtRow(table, plan.dims, tuple);
			w.open('entry', [['type', 'transfer'], ['index', rowKey(ctx, plan.narrowed.map((n) => n.of), combo)]]);
			body(values);
			w.close('entry');
		}
		w.close('connection');
		return;
	}
	const table = tableOf(t, collection, plan.dims, ctx);
	if (table.expanded) ctx.expandedEntries = (ctx.expandedEntries ?? 0) + 1;
	if (table.dropped) ctx.droppedEntries = (ctx.droppedEntries ?? 0) + table.dropped;
	writeRows(w, ctx, plan.dims, table, 'transfer', body);
	w.close('connection');
}

/** The values a table holds at one combination of its own lists, keyed by list. */
function valueAtRow(table, dims, tuple) {
	const combo = dims.map((d) => tuple[d]);
	const hit = table.rows.find((r) => r.combo.every((c, i) => c === combo[i]));
	return hit ? hit.values : table.defaults;
}

/**
 * A rate with an availability folded in, so that `rate × donor` is the flux
 * the availability gives: `expressionOf` in ../domain/availability.js, written
 * in the equation language rather than in JavaScript.
 */
function availabilityRate(rate, a) {
	if (!a) return rate;
	const D = a.donor;
	const [limit, top, bottom] = ['limit', 'top', 'bottom'].map((k) => String(a[k] ?? '').trim());
	let body;
	if (a.scheme === 'limit') {
		body = `if(${D} > 0, min((${limit}) / ${D}, 1), 1)`;
	} else {
		body = `if((${D} + (${bottom})) == 0, 1, (${D} + (${top})) / (${D} + (${bottom})))`;
	}
	if (a.unavailable) body = `(1 - ${body})`;
	return `(${rate}) * ${body}`;
}

// --- simulation ---------------------------------------------------------------------

/** The times a logarithmic grid holds: `Project.timeGrid`, to the last bit. */
function logGrid(start, end, n) {
	const t = new Array(n);
	const lo = start > 0 ? start : Math.max(end, 1) * 1e-6;
	const a = Math.log(lo);
	const b = Math.log(end);
	t[0] = start;
	for (let i = 1; i < n; i++) t[i] = Math.exp(a + ((b - a) * i) / (n - 1));
	t[n - 1] = end;
	return t;
}

function writeSimulation(w, raw, ctx) {
	const { report } = ctx;
	const sim = raw.simulation && typeof raw.simulation === 'object' ? raw.simulation : {};
	const num = (v, fallback) => {
		const n = v == null || v === '' ? NaN : Number(v);
		return Number.isFinite(n) ? n : fallback;
	};
	const start = num(sim.start_time, 0);
	const end = num(sim.end_time, 1e5);
	w.open('simulation-settings');
	w.text('start-time', javaDouble(start));
	w.text('end-time', javaDouble(end));
	const unit = ['second', 'minute', 'hour', 'day', 'year'].includes(sim.time_unit) ? sim.time_unit : 'year';
	w.text('time-unit', unit);

	const solver = String(sim.solver ?? 'ndf');
	const eco = SOLVER_TO_ECO[solver] ?? 'ODE15S';
	w.text('java-solver', eco);
	if (!SOLVER_EXACT.has(solver)) {
		report.rewrite('solver', solver, `written as ${eco}: ${SOLVER_WHY[solver] ?? 'the nearest Ecolego has'}`);
	} else if (solver === 'ndf' && (sim.bdf === true || sim.bdf === 'true')) {
		report.warn('The model runs the plain BDF formulas; the file asks for ODE15S, whose formulas are the numerical differentiation ones.');
	}
	w.text('rel-error-tolerance', javaDouble(num(sim.rtol, 1e-3)));
	w.text('abs-error-tolerance', javaDouble(num(sim.abstol, 1e-6)));
	const floor = !(sim.non_negative === false || sim.non_negative === 'false' || sim.non_negative === 0);
	w.text('saturation-enabled', floor ? 'true' : 'false');
	w.text('simulation-type', 'DETERMINISTIC');

	// When results are saved.
	const spacing = ['log', 'linear', 'series', 'solver', 'both'].includes(sim.spacing) ? sim.spacing : 'log';
	const points = Math.max(2, Math.round(num(sim.output_points, 250)));
	const series = normaliseSeries(sim.output_times);
	let mode;
	let written = [];
	if (spacing === 'solver') {
		mode = 'solver';
	} else if (spacing === 'series' || (spacing === 'both' && series.length)) {
		mode = spacing === 'both' ? 'both' : 'series';
		written = series;
		if (!series.length) {
			report.warn('The model asks for its output on a list of series and lists none; the file says so too.');
		}
	} else if (spacing === 'linear') {
		mode = 'series';
		written = [{ kind: 'linear', points, from: null, to: null }];
		report.rewrite('output times', `${points} even points`, 'written as one linear time series over the run');
	} else {
		// A logarithmic grid, alone or beside the solver's own steps: its
		// times, written out, since Ecolego's geometric series from a start of
		// zero begins at 1 and this grid begins far below it.
		mode = spacing === 'both' ? 'both' : 'series';
		written = [{ kind: 'times', times: logGrid(start, end, points) }];
		report.rewrite('output times', `${points} logarithmic points`, 'written as the list of those times, '
			+ 'since a geometric series in the file would begin at 1 rather than where this grid begins');
	}
	w.text('output-options', OUTPUT_OPTION[mode]);
	if (written.length) {
		w.open('time-series-list');
		for (const s of written) {
			if (s.kind === 'times') {
				w.open('time-series', [['type', 'custom']]);
				w.cdata('values', javaArray(s.times));
				w.close('time-series');
			} else {
				w.open('time-series', [['type', s.kind === 'log' ? 'geometric' : 'linear']]);
				w.text('time-series-start-time', s.from == null ? D_AUTO_TEXT : javaDouble(s.from));
				w.text('time-series-end-time', s.to == null ? D_AUTO_TEXT : javaDouble(s.to));
				w.text('n', String(s.points));
				w.close('time-series');
			}
		}
		w.close('time-series-list');
	}
	if (spacing === 'solver' && sim.output_points != null && points !== 250) {
		report.warn(`The model's ${points} output points are not written: with the solver's own steps as the output, an Ecolego file has no count of points.`);
	}

	// The endpoints, as the ids of the blocks that went out.
	const endpoints = [];
	const lost = [];
	for (const name of Array.isArray(sim.endpoints) ? sim.endpoints : []) {
		const text = String(name);
		const q = ctx.known(text) ? text : null;
		if (q && !ctx.skippedBlocks.has(q) && !endpoints.includes(q)) endpoints.push(q);
		else if (!q || ctx.skippedBlocks.has(q)) lost.push(text);
	}
	if (endpoints.length) {
		w.open('outputs');
		for (const q of endpoints) w.empty('output', [['id', q]]);
		w.close('outputs');
	}
	if (lost.length) {
		report.warn(`${lost.length} endpoint(s) (${lost.slice(0, 4).join(', ')}${lost.length > 4 ? ', …' : ''}) `
			+ 'name a block or a series that is not in the file, and were left off its list of outputs.');
	}
	w.close('simulation-settings');

	// What has nowhere to go.
	const set = UNCARRIED_SETTINGS.filter((k) => {
		const v = sim[k];
		if (v == null || v === '' || v === false || v === 'false') return false;
		// What each says when it leaves the choice to the solver or the tool.
		if ((k === 'max_step' || k === 'initial_step') && Number(v) === 0) return false;
		if (k === 'split' && v === 'auto') return false;
		if (Array.isArray(v) && !v.length) return false;
		if (typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length) return false;
		return true;
	});
	if (set.length) {
		report.warn(`Settings an Ecolego project has no field for were left out: ${set.join(', ')}.`);
	}
	if (raw.scenario != null) {
		const scenarios = ctx.exportLists.filter((l) => l.for_scenarios)
			.flatMap((l) => (l.indices ?? []).filter(indexOn).map(indexName));
		if (scenarios.length && scenarios[0] !== raw.scenario && scenarios.includes(raw.scenario)) {
			report.warn(`The scenario the model has chosen, '${raw.scenario}', is not written: Ecolego runs every `
				+ `scenario, and this tool opens an imported model on the first, '${scenarios[0]}'.`);
		}
	}
	if (Array.isArray(raw.derived) && raw.derived.length) {
		report.skip('derived numbers', `${raw.derived.length} number(s)`, 'numbers read off finished curves have no Ecolego equivalent');
	}
	// The diagram is not the model -- the importer does not read Ecolego's
	// either -- so it is a line in the report rather than a loss.
	const drawn = (v) => !!v && typeof v === 'object' && (Array.isArray(v) ? v.length > 0 : Object.keys(v).length > 0);
	const colours = (raw.compartments ?? []).filter((c) => c?.color && !ctx.skippedBlocks.has(qnameOf(c))).length;
	const diagram = [
		drawn(raw.layout) ? 'its layout' : null,
		drawn(raw.shapes) ? 'the shapes drawn on it' : null,
		drawn(raw.view) ? 'what it shows' : null,
		colours ? `${colours} compartment colour${colours === 1 ? '' : 's'}` : null,
	].filter(Boolean);
	if (diagram.length) {
		report.warn(`The diagram is this tool’s own and is not written (${diagram.join(', ')}): Ecolego lays a model out itself.`);
	}
}

/** The output series a model lists, read as ../domain/project.js reads them. */
function normaliseSeries(raw) {
	const out = [];
	for (const spec of Array.isArray(raw) ? raw : []) {
		if (!spec || typeof spec !== 'object') continue;
		if (Array.isArray(spec.times)) {
			const times = spec.times.map((v) => Number(v)).filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
			if (times.length) out.push({ kind: 'times', times });
			continue;
		}
		const named = String(spec.kind ?? spec.spacing ?? 'log');
		const kind = named === 'linear' ? 'linear' : named === 'times' ? 'times' : 'log';
		if (kind === 'times') continue;
		const points = Math.round(Number(spec.points ?? 0));
		if (!(points >= 2)) continue;
		const n = (v) => (v == null || v === '' ? null : Number(v));
		const from = n(spec.from);
		const to = n(spec.to);
		out.push({ kind, points, from: Number.isFinite(from) ? from : null, to: Number.isFinite(to) ? to : null });
	}
	return out;
}

function writeProbabilistic(w, raw, ctx) {
	const { report } = ctx;
	const sim = raw.simulation && typeof raw.simulation === 'object' ? raw.simulation : {};
	const n = Math.round(Number(sim.iterations));
	const s = Math.round(Number(sim.seed));
	w.open('probabilistic-settings');
	w.text('no-simulations', String(Number.isFinite(n) && n > 0 ? n : 1000));
	w.text('seed', String(Number.isFinite(s) ? s : 1));
	w.text('sampling', sim.sampling === 'random' ? 'Random' : 'Latin Hypercube');
	const varied = [];
	for (const name of Array.isArray(sim.varied) ? sim.varied : []) {
		const text = String(name);
		const found = ctx.blocks.get(text);
		if (found && found.collection === 'parameters' && !ctx.skippedBlocks.has(text)) varied.push(text);
	}
	if (varied.length) {
		w.open('probabilistic-parameters');
		for (const q of varied) w.text('selected-parameter', q);
		w.close('probabilistic-parameters');
	}
	const kept = Array.isArray(sim.varied) ? sim.varied.length - varied.length : 0;
	if (kept > 0) {
		report.warn(`${kept} of the inputs the model varies are not parameters in the file (a lookup point, or a `
			+ 'block that is left out) and were left off its list.');
	}
	w.close('probabilistic-settings');
	if (Array.isArray(sim.correlations) && sim.correlations.length) {
		report.skip('correlation', `${sim.correlations.length} pair(s)`, 'this tool’s correlations are not written: '
			+ 'the form an Ecolego file keeps them in is not one this tool reads');
	}
}
