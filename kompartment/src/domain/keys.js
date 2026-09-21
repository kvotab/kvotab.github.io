/**
 * Legacy key names in the project file.
 *
 * Keys in a model file are snake_case -- `multiply_by_donor`, `index_lists`,
 * `start_time`. Files written before that change spell the same keys in
 * camelCase, and an unknown key is *ignored* rather than reported: a stale
 * `multiplyByDonor: false` would quietly become the default `true`, turning an
 * absolute flux into a rate coefficient and changing what the model computes.
 * So a file is migrated when it is loaded, and written back in the new
 * spelling.
 *
 * The rename is structural, not a walk over every key in the document. A
 * model's own names appear as keys too -- `layout` is keyed by block name,
 * `half_lives` and an object `initial` by nuclide, a mapping's pairs by index
 * -- and any of those may legitimately be camelCase. Only the positions where
 * the format itself defines a key are touched.
 */

import { renameBuiltInLists, splitMaterialRoles } from './indexlists.js';
import { COLLECTIONS } from './systems.js';

const PROJECT = {
	halfLives: 'half_lives',
	indexLists: 'index_lists',
};

const SIMULATION = {
	startTime: 'start_time',
	endTime: 'end_time',
	outputPoints: 'output_points',
	timeUnit: 'time_unit',
};

/**
 * Solver ids that changed name.
 *
 * The ids used to be borrowed from another suite's routine names, which said
 * nothing about the method to anyone who did not already know that suite. They
 * are now named for what they are -- `ndf` for the numerical differentiation
 * formulas, `bdf` for the same with those terms off, `ros23` for the
 * Rosenbrock (2,3) pair, `dp45` for Dormand-Prince (4,5). A file written under
 * the old names still names a solver this project has, so it is migrated
 * rather than rejected: the alternative is `Unknown solver` on a model that
 * ran yesterday.
 */
const SOLVER_IDS = {
	ode15s: 'ndf',
	ode15s_bdf: 'bdf',
	ode23s: 'ros23',
	ode45: 'dp45',
};

const VIEW = {
	showExpressions: 'show_expressions',
	showParameters: 'show_parameters',
	showLookups: 'show_lookups',
	showReductions: 'show_reductions',
	showInfluences: 'show_influences',
	showSinks: 'show_sinks',
	connectionLabel: 'connection_label',
};

const INDEX_LIST = {
	forMaterials: 'for_contaminants',
	// The flag was `for_materials` while the catalogue was called `Materials`.
	// See MATERIAL_LIST in ./indexlists.js for why it is contaminants now.
	for_materials: 'for_contaminants',
	forNuclides: 'for_nuclides',
	subSetOf: 'sub_set_of',
};

/**
 * Collections renamed when the blocks were.
 *
 * The names on the left are what every file written before this spells them,
 * and what the .eco importer used to produce. The right-hand side is what the
 * interface now calls them -- see KIND_LABEL in ./edit.js. A file is migrated
 * as it is read and written back under the new names, exactly as the camelCase
 * keys above are.
 */
const COLLECTION = {
	sources: 'inflows',
	discrete_events: 'triggers',
	disruptions: 'events',
	index_operations: 'index_reductions',
	aggregates: 'block_reductions',
};

const BLOCK = {
	indexLists: 'index_lists',
	handleDecay: 'handle_decay',
	multiplyByDonor: 'multiply_by_donor',
	// A discrete event is a Trigger now, and the fields that name one say so.
	// `event` is a snapshot's: the trigger it is taken at.
	reset_event: 'reset_trigger',
	start_event: 'start_trigger',
	stop_event: 'stop_trigger',
	event: 'trigger',
	resetEvent: 'reset_trigger',
	startEvent: 'start_trigger',
	stopEvent: 'stop_trigger',
	// The two per-nuclide shorthands are legacy in their own right, but a file
	// using them is exactly the kind of file that spells them camelCase.
	perNuclide: 'per_nuclide',
	valuesByNuclide: 'values_by_nuclide',
};

const ENTRY = {
	multiplyByDonor: 'multiply_by_donor',
	reset_event: 'reset_trigger',
	start_event: 'start_trigger',
	stop_event: 'stop_trigger',
	event: 'trigger',
};

/** The block arrays, which all take the same key set. */
// Every collection a block can live in, from the one list -- this used to be a
// copy and the copy went stale: the blocks that remember were never in it, so
// a camelCase key on one of them was read as an unknown and dropped.
const BLOCK_ARRAYS = COLLECTIONS;

/** Every legacy spelling, for documentation and tests. */
export const LEGACY_KEYS = {
	...PROJECT, ...SIMULATION, ...VIEW, ...INDEX_LIST, ...BLOCK,
};

/**
 * A far-field path's `to` field, as a release transfer.
 *
 * The first version of the block carried the compartment its release went to
 * as a field on the block. A drawn line says the same thing better: it is
 * visible on the diagram, it appears in the transfer grid and the block tree,
 * and there is one mechanism for "this flux goes there" instead of two. A file
 * written the old way is converted rather than half-read -- a `to` nothing
 * looks at would silence the release without saying so.
 *
 * The transfer carries the path's own name as its rate, which *is* the
 * release, and no donor to multiply by: the mass has already left the path,
 * taken off the last cell by the outflow condition.
 */
export function migrateFarfieldTargets(raw) {
	if (!Array.isArray(raw.farfields)) return raw;
	const made = [];
	const farfields = raw.farfields.map((f) => {
		const to = f?.to;
		if (to == null || to === '') return f;
		const { to: _dropped, ...rest } = f;
		const name = f.name ? `${f.name}_release` : 'release';
		made.push({
			...(f.system ? { system: f.system } : {}),
			name, from: f.name ?? null, to: String(to),
			rate: f.name ?? '0', multiply_by_donor: false,
		});
		return rest;
	});
	if (!made.length) return raw;
	return {
		...raw,
		farfields,
		transfers: [...(raw.transfers ?? []), ...made],
	};
}

function isObject(v) {
	return !!v && typeof v === 'object' && !Array.isArray(v);
}

/**
 * A copy of `obj` with the keys in `map` renamed, each keeping its position so
 * a hand-written file comes back in the order it was typed. A file carrying
 * both spellings keeps the new one.
 */
function rename(obj, map) {
	if (!isObject(obj)) return obj;
	const out = {};
	for (const [k, v] of Object.entries(obj)) {
		const to = map[k];
		if (to === undefined) { out[k] = v; continue; }
		if (Object.prototype.hasOwnProperty.call(obj, to)) continue;
		out[to] = v;
	}
	return out;
}

/**
 * A copy of a raw project with legacy camelCase keys renamed. Values are
 * shared with the original, which the caller is expected to discard.
 */
export function migrateKeys(raw) {
	if (!isObject(raw)) return raw;
	// The two lists this tool builds in were called `Nuclide` and `Element`
	// and are now called what Ecolego calls them. A file written under the old
	// names is renamed here, with every reference to them, for the same reason
	// the camelCase keys are: one spelling in front of the reader.
	// And the material role, which used to be one list and is now two: a
	// catalogue of materials and the radionuclides among them. See
	// `splitMaterialRoles`. It runs after the rename so that it sees the two
	// built-in lists under the names everything else spells them.
	// Key spellings first, and the index lists' among them: the structural
	// renames below read `for_contaminants` off a list to find the catalogue,
	// and a file that still says `for_materials` would hide it from them.
	let out = rename(rename(raw, PROJECT), COLLECTION);
	if (Array.isArray(out.index_lists)) {
		out.index_lists = out.index_lists.map((l) => rename(l, INDEX_LIST));
	}
	out = splitMaterialRoles(renameBuiltInLists(migrateFarfieldTargets(out)));

	if (isObject(out.simulation)) {
		out.simulation = rename(out.simulation, SIMULATION);
		const renamed = SOLVER_IDS[out.simulation.solver];
		if (renamed) out.simulation = { ...out.simulation, solver: renamed };
	}
	if (isObject(out.view)) out.view = rename(out.view, VIEW);

	for (const key of BLOCK_ARRAYS) {
		if (!Array.isArray(out[key])) continue;
		out[key] = out[key].map((raw_block) => {
			const block = rename(raw_block, BLOCK);
			if (Array.isArray(block.entries)) {
				block.entries = block.entries.map((e) => rename(e, ENTRY));
			}
			return block;
		});
	}

	return out;
}
