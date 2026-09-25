/**
 * Test fixtures for the .eco exporter (src/io/ecoexport.js), shared by
 * test/run.js and the Python package's tests (python/tests/node/eco_export.mjs).
 *
 * Two things:
 *
 *  - **Made-up models**, one per corner of the format: every block kind, index
 *    lists with sub-sets, mappings, scenarios and material units, values per
 *    index (partial ones among them), every distribution, sub-systems nested,
 *    switched off and transporting, decay chains, and the things that have no
 *    Ecolego equivalent. The numbers are invented; nothing here comes from a
 *    real assessment.
 *
 *  - **What a model means**, as one JSON value: `canonicalModel`. Built from
 *    the application's own rules -- `Project` normalises every block and
 *    `valueAt` answers what each value is at every index combination -- so
 *    two models that say the same thing in different words give the same
 *    text. That is what a round trip is checked with: the importer spells some
 *    things its own way (a description with its provenance appended, every
 *    half-life and decay pair written out, a scalar block marked
 *    `per_nuclide: false`, an entry per index where the model had one per
 *    nuclide), and none of those is a change of meaning.
 */

import * as ed from '../src/domain/edit.js';
import { Project, valueAt } from '../src/domain/project.js';
import { defaultChains } from '../src/domain/nuclides.js';
import { resolveReference, systemPaths } from '../src/domain/systems.js';

/** A model as the editor holds it once opened. */
export function openedModel(project) {
	const m = ed.migrateKeys(structuredClone(project));
	ed.materialiseShorthand(m);
	ed.syncDerivedUnits(m);
	return m;
}

const SINGULAR = {
	parameters: 'parameter', compartments: 'compartment', expressions: 'expression',
	functions: 'function', lookups: 'lookup', index_reductions: 'index_reduction',
	block_reductions: 'block_reduction', min_maxes: 'min_max', running_means: 'running_mean',
	snapshots: 'snapshot', delays: 'delay', triggers: 'trigger', transfers: 'transfer',
	inflows: 'inflow',
};

const KEYS = {
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
	functions: [],
};

const EQUATION = new Set(['initial', 'dydt', 'equation', 'rate', 'first', 'second', 'delay']);
const REFERENCE = new Set(['reset_trigger', 'start_trigger', 'stop_trigger', 'trigger']);

/** A number to fifteen significant figures: what a text round trip must keep. */
const round = (x, digits = 15) => (typeof x === 'number' && Number.isFinite(x) ? Number(x.toPrecision(digits)) : x);

/** The description, without what the importer appends about where it came from. */
export function withoutProvenance(text) {
	const s = String(text ?? '');
	const at = s.lastIndexOf('Imported from Ecolego');
	if (at < 0 || (at > 0 && s[at - 1] !== '\n')) return s.trim();
	return s.slice(0, at).trim();
}

function canonicalPdf(spec) {
	if (!spec || typeof spec !== 'object') return null;
	const out = { kind: spec.kind, params: {} };
	for (const [k, v] of Object.entries(spec.params ?? {}).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) {
		out.params[k] = v == null ? null : round(Number(v));
	}
	for (const k of ['trmin', 'trmax', 'pmin', 'pmax']) {
		out[k] = spec[k] == null || spec[k] === '' ? null : round(Number(spec[k]));
	}
	if (spec.kind === 'pg') {
		out.values = (spec.values ?? []).map((v) => round(Number(v)));
		out.inorder = spec.inorder !== false;
		out.pos = Number(spec.pos ?? 0);
	}
	return out;
}

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
 * What a model means, as one JSON-able value with its keys in a fixed order.
 *
 * `exclude` names blocks (qualified) to leave out of the comparison -- what an
 * export's report says it left out or wrote in another form. `imported` strips
 * the provenance the importer appends to the description.
 */
export function canonicalModel(project, { exclude = [], imported = false } = {}) {
	const raw = openedModel(project);
	const P = new Project(structuredClone(raw));
	const skip = new Set(exclude);
	const known = new Set();
	for (const collection of [...Object.keys(SINGULAR), 'farfields', 'waste_packages', 'events']) {
		for (const b of raw[collection] ?? []) known.add(b.system ? `${b.system}.${b.name}` : b.name);
	}
	const has = (n) => known.has(n);
	const resolve = (ref, system) => {
		const text = String(ref).trim();
		return resolveReference(text, system ?? '', has) ?? text;
	};
	const single = (v, system) => {
		const text = v == null ? '0' : String(v).trim();
		return /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(text) ? resolve(text, system) : text;
	};

	const lists = P.index_lists.filter((l) => !l.auto);
	const indicesOf = (name) => (P.index_lists.find((l) => l.name === name)?.indices ?? []).map((i) => i.name);

	const valueFor = (block, collection, key, tuple) => {
		const v = valueAt(block, key, tuple);
		const system = block.system ?? '';
		if (EQUATION.has(key)) {
			if (v == null) return null;
			const text = String(v).trim();
			return key === 'dydt' && text === '' ? null : text;
		}
		switch (key) {
			case 'abstol': return v == null || v === '' ? null : Number(v);
			case 'non_negative': return v !== false && v !== 'false' && v !== 0;
			case 'multiply_by_donor':
				return collection === 'inflows' || block.from == null ? false : v !== false && v !== 'false';
			case 'value': return round(Number(v));
			case 'pdf': return canonicalPdf(v);
			case 'points': {
				const pts = (v ?? []).map((p) => [round(Number(p[0])), round(Number(p[1]))]);
				return pts.map((p, i) => [p, i]).sort((a, b) => a[0][0] - b[0][0] || a[1] - b[1]).map(([p]) => p);
			}
			case 'target':
				if (collection === 'index_reductions') return v == null ? null : resolve(v, system);
				return single(v, system);
			case 'targets': return (v ?? []).map((t) => resolve(t, system));
			case 'direction': return v ?? 'rising';
			default:
				if (REFERENCE.has(key)) return v == null || String(v).trim() === '' ? null : resolve(v, system);
				return v ?? null;
		}
	};

	const blocks = [];
	for (const collection of Object.keys(SINGULAR)) {
		for (const rawBlock of raw[collection] ?? []) {
			const q = rawBlock.system ? `${rawBlock.system}.${rawBlock.name}` : rawBlock.name;
			if (skip.has(q)) continue;
			const b = P._block(structuredClone(rawBlock), SINGULAR[collection]);
			const kind = collection === 'inflows' ? 'transfers' : collection;
			const dims = b.index_lists ?? [];
			const out = {
				q, kind, dims: [...dims],
				unit: String(b.unit ?? '').trim(),
				comment: String(b.comment ?? '').trim(),
				enabled: rawBlock.enabled !== false,
			};
			if (collection === 'compartments') {
				out.handle_decay = b.handle_decay !== false;
				out.transport = b.transport ?? null;
			}
			if (collection === 'transfers' || collection === 'inflows') {
				const end = (r) => (r == null ? null : has(r) ? r : resolve(r, b.system));
				out.from = collection === 'inflows' ? null : end(rawBlock.from ?? null);
				out.to = end(rawBlock.to ?? null);
			}
			if (collection === 'expressions') {
				out.transport = b.transport ?? null;
				if (b.transport === 'operation') { out.operation = b.operation; out.argument = b.argument; }
			}
			if (collection === 'functions') {
				out.parameters = b.parameters;
				out.equation = String(b.equation ?? '').trim();
			}
			if (collection === 'lookups') {
				out.interpolation = b.interpolation;
				out.cyclic = !!b.cyclic;
				out.argument = b.argument ?? null;
			}
			if (collection === 'index_reductions') {
				out.operation = b.operation;
				out.percentile = b.percentile ?? null;
			}
			if (collection === 'block_reductions' || collection === 'min_maxes') out.operation = b.operation;
			const grid = {};
			if (b.transport !== 'counter' && b.transport !== 'operation') {
				for (const combo of product(dims.map((d) => indicesOf(d)))) {
					const tuple = {};
					dims.forEach((d, i) => { tuple[d] = combo[i]; });
					const values = {};
					for (const key of KEYS[collection]) values[key] = valueFor(b, collection, key, tuple);
					grid[combo.join(' | ')] = values;
				}
			}
			out.grid = grid;
			blocks.push(out);
		}
	}
	blocks.sort((a, b) => (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : a.q < b.q ? -1 : a.q > b.q ? 1 : 0));

	const catalogue = lists.find((l) => l.for_contaminants);
	const nuclideList = lists.find((l) => l.for_nuclides);
	const catalogueNames = (catalogue?.indices ?? []).map((i) => i.name);
	const inNuclides = new Set((nuclideList?.indices ?? []).map((i) => i.name));
	const decays = (n) => inNuclides.has(n) || Number.isFinite(P.halfLives[n]);
	const nuclides = new Set(catalogueNames.filter(decays));
	const pairs = Array.isArray(raw.chains)
		? raw.chains.map((p) => [String(p[0]), String(p[1]), p[2] === undefined ? 1 : Number(p[2])])
		: defaultChains(catalogueNames, P.decayCeiling);

	const sim = P.simulation;
	const byName = (a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
	return {
		name: String(raw.name ?? '').trim() || 'model',
		description: imported ? withoutProvenance(raw.description) : String(raw.description ?? '').trim(),
		lists: lists.slice().sort(byName).map((l) => ({
			name: l.name,
			roles: ['for_contaminants', 'for_nuclides', 'for_scenarios', 'for_elements'].filter((k) => l[k]),
			sub_set_of: l.sub_set_of ?? null,
			mapping: l.mapping ? { to: l.mapping.to, pairs: (l.mapping.pairs ?? []).map((p) => [p.from, p.to]) } : null,
			indices: l.indices.map((i) => [i.name, i.enabled !== false, l === catalogue ? (i.unit ?? '') : '']),
		})),
		decay_unit: P.decayUnit,
		half_lives: catalogueNames.map((n) => [n, Number.isFinite(P.halfLives[n]) ? round(P.halfLives[n]) : null]),
		chains: pairs.filter(([a, b]) => nuclides.has(a) && nuclides.has(b)).map(([a, b, r]) => [a, b, round(r)]),
		scenario: P.scenario ?? null,
		systems: systemPaths(raw).slice().sort(),
		transports: (raw.transports ?? []).map(String).sort(),
		disabled_systems: (raw.disabled_systems ?? []).map(String).sort(),
		simulation: {
			start: sim.start_time, end: sim.end_time, time_unit: sim.time_unit,
			rtol: sim.rtol, abstol: sim.abstol, non_negative: sim.non_negative,
			solver: sim.solver,
			iterations: sim.iterations, seed: sim.seed, sampling: sim.sampling,
			mode: P.outputMode,
			times: P.outputMode === 'solver' ? null : Array.from(P.timeGrid()).map((t) => round(t, 12)),
			endpoints: [...new Set((raw.simulation?.endpoints ?? []).map(String).filter((n) => has(n) && !skip.has(n)))],
			varied: (raw.simulation?.varied ?? []).map(String).filter((n) => has(n) && !skip.has(n)),
		},
		blocks,
	};
}

// --- made-up models -------------------------------------------------------------------

const logt = (min, max, mode, extra = {}) => ({
	kind: 'logt', params: { min, max, mode }, values: null, trmin: null, trmax: null, inorder: true, pos: 0, ...extra,
});

/**
 * Every block kind, in two sub-systems, over nuclides, objects and a sub-set
 * and a mapping of them, with values per index -- some keyed by every list,
 * some by only one -- and a distribution of every kind Ecolego has.
 */
export const EVERY_KIND = {
	name: 'Every kind of block',
	description: 'A made-up model with one of everything an .eco file can hold.\nSecond line of the description.',
	nuclides: ['Cs-137', 'Sr-90', 'Y-90'],
	decay_unit: 'Bq',
	index_lists: [
		{ name: 'Contaminants', for_contaminants: true, indices: [
			{ name: 'Cs-137', enabled: true }, { name: 'Sr-90', enabled: true }, { name: 'Y-90', enabled: true },
			{ name: 'Carbon', enabled: true, unit: 'kgC' },
		] },
		{ name: 'Radionuclides', for_nuclides: true, sub_set_of: 'Contaminants', indices: [
			{ name: 'Cs-137', enabled: true }, { name: 'Sr-90', enabled: true }, { name: 'Y-90', enabled: true },
		] },
		{ name: 'Objects', indices: [{ name: 'Lake', enabled: true }, { name: 'Mire', enabled: true }, { name: 'Forest', enabled: false }] },
		{ name: 'Wet', sub_set_of: 'Objects', indices: [{ name: 'Lake', enabled: true }, { name: 'Mire', enabled: true }] },
		{ name: 'Region', indices: [{ name: 'North', enabled: true }, { name: 'South', enabled: true }] },
		{ name: 'ObjRegion', mapping: { to: 'Region', pairs: [{ from: 'Lake', to: 'North' }, { from: 'Mire', to: 'South' }] },
			indices: [{ name: 'Lake', enabled: true }, { name: 'Mire', enabled: true }] },
	],
	systems: ['Near', 'Near.Buffer', 'Far', 'Empty'],
	simulation: {
		start_time: 0, end_time: 200, output_points: 60, spacing: 'log', solver: 'ndf',
		rtol: 1e-7, abstol: 1e-12, time_unit: 'year', non_negative: true,
		iterations: 250, seed: 7, sampling: 'random',
		endpoints: ['Near.Soil', 'Dose', 'Near.k_leach'],
		varied: ['Near.k_leach', 'Kd'],
	},
	parameters: [
		{ name: 'k_leach', system: 'Near', index_lists: ['Objects'], value: 0.01, unit: '1/year', comment: 'Leaching, per object',
			pdf: logt(0.001, 0.1, 0.01),
			entries: [
				{ index: { Objects: 'Lake' }, value: 0.05, pdf: { kind: 'unif', params: { min: 0.01, max: 0.09 }, values: null, trmin: null, trmax: null, inorder: true, pos: 0 } },
				{ index: { Objects: 'Mire' }, value: 0.02 },
			] },
		{ name: 'Kd', index_lists: ['Radionuclides'], value: 0.1, unit: 'm3/kg', entries: [
			{ index: { Radionuclides: 'Cs-137' }, value: 1.5, pdf: { kind: 'Logn4', params: { gm: 1.5, gsd: 3 }, values: null, trmin: 0.1, trmax: 20, inorder: true, pos: 0 } },
			{ index: { Radionuclides: 'Sr-90' }, value: 0.02, pdf: { kind: 'norm', params: { mean: 0.02, sd: 0.005 }, values: null, trmin: 0, trmax: null, inorder: true, pos: 0 } },
			{ index: { Radionuclides: 'Y-90' }, value: 0.3, pdf: { kind: 'logn', params: { mean: 0.3, sd: 0.1 }, values: null, trmin: null, trmax: null, inorder: true, pos: 0 } },
		] },
		{ name: 'rho', value: 1500, unit: 'kg/m3', pdf: { kind: 'triang', params: { min: 1200, max: 1800, mode: 1500 }, values: null, trmin: null, trmax: null, inorder: true, pos: 0 } },
		{ name: 'porosity', value: 0.3, pdf: { kind: 'logu', params: { min: 0.1, max: 0.5 }, values: null, trmin: null, trmax: null, inorder: true, pos: 0 } },
		{ name: 'uptake', value: 2e-6, pdf: { kind: 'logn5', params: { p1: 0.05, x1: 1e-6, p2: 0.95, x2: 5e-6 }, values: null, trmin: null, trmax: null, inorder: true, pos: 0 } },
		{ name: 'sampled', value: 3, pdf: { kind: 'pg', params: {}, values: [1, 2, 3, 4.5], trmin: null, trmax: null, inorder: false, pos: 2 } },
		{ name: 'half_filled', value: 1, pdf: { kind: 'logt', params: { min: null, max: null, mode: null }, values: null, trmin: null, trmax: null, inorder: true, pos: 0 } },
		{ name: 'DoseCoeff', index_lists: ['Radionuclides'], value: 1e-8, unit: 'Sv/Bq', entries: [
			{ index: { Radionuclides: 'Cs-137' }, value: 1.3e-8 },
		] },
		{ name: 'regional', index_lists: ['Region'], value: 1, entries: [{ index: { Region: 'South' }, value: 2 }] },
		{ name: 'disabled_one', value: 4, enabled: false, comment: 'Switched off' },
	],
	compartments: [
		{ name: 'Soil', system: 'Near', index_lists: ['Radionuclides', 'Objects'], unit: 'Bq', initial: '0', abstol: 1e-9,
			comment: 'Top soil,\nwith a comment on two lines & an <angle> and ]]> in it',
			entries: [
				{ index: { Radionuclides: 'Cs-137', Objects: 'Lake' }, initial: '1e10' },
				{ index: { Radionuclides: 'Sr-90' }, initial: '2e9' },
				{ index: { Objects: 'Mire' }, abstol: 1e-6 },
			] },
		{ name: 'Deep', system: 'Near.Buffer', index_lists: ['Radionuclides', 'Objects'], unit: 'Bq', initial: '0', handle_decay: false },
		{ name: 'Lake', index_lists: ['Radionuclides'], unit: 'Bq', initial: '0', dydt: '0', entries: [
			{ index: { Radionuclides: 'Y-90' }, dydt: '-1e-3 * Lake[Y-90]' },
		] },
		{ name: 'Carbon_pool', index_lists: ['Contaminants'], initial: '1', entries: [{ index: { Contaminants: 'Carbon' }, initial: '100' }] },
		{ name: 'Store', system: 'Far', index_lists: [], unit: 'kg', initial: '5', non_negative: false },
	],
	expressions: [
		{ name: 'Total', system: 'Near', index_lists: ['Objects'], unit: 'Bq', equation: 'Soil[Cs-137] + Near.Buffer.Deep[Cs-137]',
			entries: [{ index: { Objects: 'Forest' }, equation: '0' }] },
		{ name: 'Conc', index_lists: ['Radionuclides'], unit: 'Bq/m3', equation: 'Lake / 1e6' },
		{ name: 'Dose', index_lists: ['Radionuclides'], unit: 'Sv', equation: 'Conc * DoseCoeff * Uptake_f(2, rho)' },
		{ name: 'WithTable', equation: 'Retardation(3) + Sorption[Lake]' },
	],
	functions: [
		{ name: 'Uptake_f', parameters: ['a', 'b'], equation: 'a * b / 1000', unit: '', comment: 'A function of two arguments' },
	],
	lookups: [
		{ name: 'Sorption', index_lists: ['Objects'], unit: 'm3/kg', interpolation: 'below', cyclic: false,
			points: [[0, 1], [50, 2], [100, 4]], entries: [{ index: { Objects: 'Lake' }, points: [[0, 2], [100, 8]] }] },
		{ name: 'Retardation', interpolation: 'extrapolate', cyclic: true, argument: 'X', points: [[0, 0], [10, 20]] },
		{ name: 'Nearest', interpolation: 'Use Input Nearest', points: [[0, 1], [5, 3]] },
		{ name: 'Above', interpolation: 'above', points: [[0, 1], [5, 3]] },
	],
	index_reductions: [
		{ name: 'Soil_total', system: 'Near', index_lists: ['Radionuclides'], unit: 'Bq', target: 'Soil', operation: 'sum' },
		{ name: 'Soil_p90', system: 'Near', index_lists: ['Radionuclides'], unit: 'Bq', target: 'Soil', operation: 'percentile', percentile: 90 },
		{ name: 'Mean_regional', target: 'regional', operation: 'mean', index_lists: [] },
	],
	block_reductions: [
		{ name: 'Everywhere', system: 'Near', index_lists: ['Radionuclides', 'Objects'], unit: 'Bq', targets: ['Soil', 'Near.Buffer.Deep'], operation: 'max' },
		{ name: 'Product', index_lists: ['Radionuclides'], targets: ['Conc', 'Dose'], operation: 'product' },
	],
	triggers: [
		{ name: 'Crossing', first: 'time', second: '100', direction: 'rising' },
		{ name: 'Falling', index_lists: ['Radionuclides'], first: 'Dose', second: '1e-12', direction: 'falling',
			entries: [{ index: { Radionuclides: 'Y-90' }, second: '1e-13' }] },
	],
	min_maxes: [
		{ name: 'Peak', index_lists: ['Radionuclides'], target: 'Dose', operation: 'max', reset_trigger: 'Crossing' },
		{ name: 'Lowest', system: 'Near', index_lists: ['Objects'], target: 'Total', operation: 'min' },
	],
	running_means: [
		{ name: 'Mean_dose', index_lists: ['Radionuclides'], target: 'Dose', start_trigger: 'Crossing', stop_trigger: 'Falling' },
	],
	snapshots: [
		{ name: 'When', target: 'time', trigger: 'Crossing', initial: '-1' },
	],
	delays: [
		{ name: 'Lagged', index_lists: ['Radionuclides'], target: 'Dose', delay: '10' },
	],
	transfers: [
		{ name: 'Leach', system: 'Near', from: 'Near.Soil', to: 'Near.Buffer.Deep', index_lists: ['Radionuclides', 'Objects'],
			rate: 'k_leach / (1 + Kd * rho / porosity)', unit: '1/year',
			entries: [{ index: { Radionuclides: 'Y-90', Objects: 'Lake' }, rate: '0.5' }] },
		{ name: 'Drain', system: 'Near.Buffer', from: 'Near.Buffer.Deep', to: null, index_lists: ['Radionuclides', 'Objects'],
			rate: '0.01' },
		{ name: 'CarbonToLake', from: 'Carbon_pool', to: 'Lake', index_lists: ['Radionuclides'], rate: '1e-3',
			comment: 'Between a block on the catalogue and one on its radionuclides: over what the two share' },
		{ name: 'Out', from: 'Lake', to: null, index_lists: ['Radionuclides'], rate: '0.02', multiply_by_donor: true },
		{ name: 'Feed', from: null, to: 'Lake', index_lists: ['Radionuclides'], rate: '5', multiply_by_donor: false },
		{ name: 'Absolute', from: 'Lake', to: null, index_lists: ['Radionuclides'], rate: '1e-3', multiply_by_donor: false,
			entries: [{ index: { Radionuclides: 'Cs-137' }, multiply_by_donor: true, rate: '1e-4' }] },
	],
	inflows: [
		{ name: 'Rain', to: 'Near.Soil', index_lists: ['Radionuclides', 'Objects'], rate: '10', unit: 'Bq/year' },
	],
	chains: [['Sr-90', 'Y-90', 1]],
};

/**
 * A transport sub-system: a soil column of N compartments drawn as its first
 * and its last, with a counter and two operations over it.
 */
export const TRANSPORT = {
	name: 'Column',
	description: 'A transport sub-system.',
	nuclides: ['I-129'],
	systems: ['Column'],
	transports: ['Column'],
	simulation: { start_time: 0, end_time: 100, output_points: 40, spacing: 'linear', solver: 'dp45', rtol: 1e-8, abstol: 1e-12, time_unit: 'year' },
	compartments: [
		{ name: 'Lake', index_lists: [], unit: 'Bq', initial: '100' },
		{ name: 'Begin', system: 'Column', transport: 'begin', index_lists: [], unit: 'Bq', initial: '0' },
		{ name: 'End', system: 'Column', transport: 'end', index_lists: [], unit: 'Bq', initial: '0' },
	],
	expressions: [
		{ name: 'N', system: 'Column', transport: 'number', index_lists: [], equation: '4' },
		{ name: 'i', system: 'Column', transport: 'counter', index_lists: [], equation: '1' },
		{ name: 'Total', system: 'Column', transport: 'operation', index_lists: [], operation: 'sum', argument: 'all' },
		{ name: 'At', system: 'Column', transport: 'operation', index_lists: [], operation: 'mean', argument: 'point' },
		{ name: 'Stretch', system: 'Column', transport: 'operation', index_lists: [], operation: 'sum', argument: 'range' },
		{ name: 'Halfway', index_lists: [], equation: 'Column.At(0.5) + Column.Stretch(0.2, 0.8)' },
	],
	transfers: [
		{ name: 'Feed', from: 'Lake', to: 'Column.Begin', index_lists: [], rate: '0.1' },
		{ name: 'Down', system: 'Column', from: 'Column.Begin', to: 'Column.End', index_lists: [], rate: '0.2 * i' },
	],
};

/** A switched-off sub-system, a series list, the solver's own steps, amounts in moles and a decay chain of four. */
export const SWITCHES = {
	name: 'Switches and series',
	nuclides: ['U-238', 'U-234', 'Th-230', 'Ra-226'],
	decay_unit: 'mol',
	half_lives: { 'U-234': 245500 },
	systems: ['On', 'Off'],
	disabled_systems: ['Off'],
	simulation: {
		start_time: 10, end_time: 1e5, output_points: 100, spacing: 'series', solver: 'ros23', rtol: 1e-6, abstol: 1e-15,
		time_unit: 'year', non_negative: false,
		output_times: [{ kind: 'linear', points: 5, from: null, to: 1000 }, { kind: 'log', points: 20, from: 1000, to: null }, { kind: 'times', times: [50, 5000, 12345.678] }],
	},
	compartments: [
		{ name: 'A', system: 'On', index_lists: ['Radionuclides'], unit: 'mol', initial: '1', entries: [{ index: { Radionuclides: 'U-238' }, initial: '100' }] },
		{ name: 'B', system: 'Off', index_lists: ['Radionuclides'], unit: 'mol', initial: '0' },
		{ name: 'C', index_lists: ['Radionuclides'], unit: 'mol', initial: '0', non_negative: false },
	],
	transfers: [
		{ name: 'AC', system: 'On', from: 'On.A', to: 'C', index_lists: ['Radionuclides'], rate: '1e-4' },
		{ name: 'BC', system: 'Off', from: 'Off.B', to: 'C', index_lists: ['Radionuclides'], rate: '1e-4' },
	],
};

/** A scenario list, a model with no materials at all, and the solver's own steps. */
export const SCENARIO_ONLY = {
	name: 'Scenario only',
	index_lists: [
		{ name: 'Climate', for_scenarios: true, indices: [{ name: 'Wet', enabled: true }, { name: 'Dry', enabled: true }] },
	],
	scenario: 'Wet',
	simulation: { start_time: 0, end_time: 50, output_points: 30, spacing: 'both', solver: 'ndf', rtol: 1e-6, abstol: 1e-10, time_unit: 'day' },
	parameters: [{ name: 'k', index_lists: ['Climate'], value: 0.1, entries: [{ index: { Climate: 'Dry' }, value: 0.01 }] }],
	compartments: [{ name: 'Pool', index_lists: [], unit: 'kg', initial: '10' }],
	transfers: [{ name: 'Drain', from: 'Pool', to: null, index_lists: [], rate: 'k' }],
};

/**
 * What an .eco file has no place for, beside things that have an exact
 * translation: a far-field path, waste packages, an event, a flux summed into
 * an end of fewer dimensions, a narrowed flux, availabilities, a block indexed
 * by the transfers, a function of nothing, the two distributions Ecolego lacks,
 * a percentile truncation and a correlation group.
 */
export const NO_EQUIVALENT = {
	name: 'No equivalent',
	nuclides: ['Cs-137', 'I-129'],
	index_lists: [
		{ name: 'Contaminants', for_contaminants: true, indices: [{ name: 'Cs-137', enabled: true }, { name: 'I-129', enabled: true }] },
		{ name: 'Radionuclides', for_nuclides: true, sub_set_of: 'Contaminants', indices: [{ name: 'Cs-137', enabled: true }, { name: 'I-129', enabled: true }] },
		{ name: 'Object', indices: [{ name: 'Lake', enabled: true }, { name: 'Mire', enabled: true }, { name: 'Forest', enabled: true }] },
		{ name: 'Wetland', sub_set_of: 'Object', indices: [{ name: 'Lake', enabled: true }, { name: 'Mire', enabled: true }] },
	],
	simulation: { start_time: 0, end_time: 1000, output_points: 50, spacing: 'log', solver: 'radau5', rtol: 1e-6, abstol: 1e-9, time_unit: 'year',
		bdf: true, mass_balance: true, correlations: [{ a: 'k', b: 'Kd', rho: 0.5 }] },
	parameters: [
		{ name: 'k', value: 0.01, pdf: { kind: 'dtriang', params: { min: 0.001, max: 0.1, mode: 0.02 }, values: null, trmin: null, trmax: null, inorder: true, pos: 0 } },
		{ name: 'Kd', value: 1, pdf: { kind: 'logdt', params: { min: 0.1, max: 10, mode: 2 }, values: null, trmin: null, trmax: null, inorder: true, pos: 0 } },
		{ name: 'cut', value: 5, pdf: { kind: 'norm', params: { mean: 5, sd: 1 }, values: null, trmin: 2, trmax: null, pmin: 0.05, pmax: 0.95, inorder: true, pos: 0 } },
		{ name: 'grouped', value: 2, pdf: { kind: 'unif', params: { min: 1, max: 3 }, values: null, trmin: null, trmax: null, group: 'G1', inorder: true, pos: 0 } },
		{ name: 'per_transfer', index_lists: ['Transfers'], value: 0.1 },
		{ name: 'limit', value: 1e6 },
	],
	compartments: [
		{ name: 'Water', index_lists: ['Radionuclides', 'Object'], initial: '1e8' },
		{ name: 'Downstream', index_lists: ['Radionuclides'], initial: '0' },
		{ name: 'Vault', index_lists: ['Radionuclides'], initial: '1e9' },
		{ name: 'Sediment', index_lists: ['Radionuclides'], initial: '0' },
	],
	expressions: [
		{ name: 'Reads_path', index_lists: ['Radionuclides'], equation: 'Path * 2' },
		{ name: 'Reads_that', index_lists: ['Radionuclides'], equation: 'Reads_path + 1' },
		{ name: 'Ends', index_lists: [], equation: 'per_transfer[_source_]' },
		{ name: 'Calls_nothing', index_lists: [], equation: 'Zero() + 1' },
	],
	functions: [{ name: 'Zero', parameters: [], equation: '0' }],
	lookups: [{ name: 'Spread', points: [[0, 1, { kind: 'unif', params: { min: 0.5, max: 1.5 }, values: null, trmin: null, trmax: null, inorder: true, pos: 0 }], [10, 2]] }],
	farfields: [{ name: 'Path', index_lists: ['Radionuclides'], tw: '50', f: '1e5', kd_f: '0', kd_m: '0.01', de_m: '1e-6',
		eps_m: '0.002', rho_m: '2700', pe: '10', pen_dep: '12.5', n_f: 10, n_m: 10, o_b: 1, n_b: 0 }],
	waste_packages: [{ name: 'Canisters', index_lists: ['Radionuclides'], packages: 10, inventory: '1e12', irf: '0.01',
		degradation_rate: '1e-6', failure: 'never' }],
	events: [{ name: 'Quake', timing: 'at', at: '500', sampled: false, actions: [{ kind: 'move', from: 'Vault', to: null, fraction: '0.5' }] }],
	transfers: [
		{ name: 'Discharge', from: 'Water', to: 'Downstream', index_lists: ['Radionuclides', 'Object'], sum_extra_indices: true, rate: '0.01' },
		{ name: 'WetlandLoss', from: 'Water', to: null, index_lists: ['Radionuclides', 'Wetland'], rate: '0.02',
			entries: [{ index: { Radionuclides: 'I-129', Wetland: 'Mire' }, rate: '0.05' }] },
		{ name: 'Leach', from: 'Vault', to: 'Sediment', index_lists: ['Radionuclides'], rate: '0.001',
			availability: { scheme: 'limit', limit: 'limit' } },
		{ name: 'Sorb', from: 'Sediment', to: null, index_lists: ['Radionuclides'], rate: '0.002',
			availability: { scheme: 'langmuir', top: '10', bottom: '1000', unavailable: true } },
		{ name: 'Shared', from: 'Vault', to: null, index_lists: ['Radionuclides'], rate: '0.001',
			availability: { scheme: 'shared_limit', limit: 'limit', over: 'Radionuclides' } },
		{ name: 'ToPath', from: 'Vault', to: 'Path', index_lists: ['Radionuclides'], rate: '0.001' },
		{ name: 'FromPackages', from: 'Canisters', to: 'Sediment', index_lists: ['Radionuclides'], rate: '1', multiply_by_donor: false },
	],
	derived: [{ name: 'peak', kind: 'peak', of: 'Water' }],
	layout: { Water: { x: 10, y: 20 } },
};

/**
 * A model with some of its blocks taken out, and the endpoints that named
 * them: what an export that left those blocks out means, to run beside the
 * model it came back as.
 */
export function withoutBlocks(project, names) {
	const gone = new Set(names);
	const out = structuredClone(project);
	for (const [key, value] of Object.entries(out)) {
		if (!Array.isArray(value) || key === 'index_lists' || key === 'chains' || key === 'systems' || key === 'transports') continue;
		out[key] = value.filter((b) => !(b && typeof b === 'object' && !Array.isArray(b)
			&& gone.has(b.system ? `${b.system}.${b.name}` : b.name)));
	}
	if (Array.isArray(out.simulation?.endpoints)) {
		out.simulation.endpoints = out.simulation.endpoints.filter((n) => !gone.has(n));
	}
	return out;
}

/** A trigger whose direction is set per index: the file says so, and this tool's importer reads the block's own. */
export const PER_INDEX_DIRECTION = {
	name: 'Per-index direction',
	nuclides: ['Cs-137', 'Sr-90'],
	simulation: { start_time: 0, end_time: 10, output_points: 11, spacing: 'linear', solver: 'ndf', rtol: 1e-6, abstol: 1e-9, time_unit: 'year' },
	triggers: [{ name: 'Either', index_lists: ['Radionuclides'], first: 'time', second: '5', direction: 'rising',
		entries: [{ index: { Radionuclides: 'Sr-90' }, direction: 'both' }] }],
};

/** The made-up models, by name, for the tests and for the Python package's. */
export const EXPORT_MODELS = { EVERY_KIND, TRANSPORT, SWITCHES, SCENARIO_ONLY, NO_EQUIVALENT, PER_INDEX_DIRECTION };
