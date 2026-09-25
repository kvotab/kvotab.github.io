/**
 * The project model.
 *
 * The block types a compartment model is made of -- compartment, transfer,
 * parameter, expression and source/sink -- together with the simulation
 * settings and the index-list model. What is here is the part that determines
 * the equations, plus the one piece of unit management that is not decoration:
 * a flux unit follows from its donor, so it is derived rather than stored.
 * See ./units.js.
 *
 * Every block is indexed by an ordered array of index lists -- its dimension --
 * and holds one value per combination of indices. A block-level value is the
 * default; `entries` override it for particular index combinations, with the
 * most specific match winning.
 */

import {
	HALF_LIVES,
	defaultChains,
	buildDecayModel,
	TIME_UNITS,
	DECAY_UNITS,
} from './nuclides.js';
import { NAME_RE, RESERVED } from './names.js';
import { DEFAULT_SOLVER } from '../ode/solvers.js';
import { derivedUnit, DERIVED_UNIT_KINDS, dimensionUnit } from './units.js';
import { SPACINGS, combineSeries } from './timeseries.js';
import {
	IndexSpace,
	IndexError,
	desugarNuclides,
	deriveElements,
	deriveBlockLists,
	listApplies,
	listAppliesWhy,
	clashingDimensions,
	clashingDimensionsWhy,
	NUCLIDE_LIST,
	sharedDims,
	summedDims,
	summedDimsWhy,
} from './indexlists.js';
import { migrateKeys } from './keys.js';
import {
	qualifiedName,
	systemOf,
	systemPaths,
	resolveReference,
	isValidPath,
	COLLECTIONS,
	isWithin,
} from './systems.js';
import { INTERPOLATIONS, interpolationFromEco } from './lookup.js';
import {
	FARF_DEFAULTS,
	FARF_EQUATION_KEYS,
	FARF_NUCLIDE_KEYS,
	FARF_STRUCTURE_KEYS,
	structureProblem,
	geometryProblem,
} from './farfield.js';
import {
	WASTE_EQUATION_KEYS, WASTE_NUCLIDE_KEYS, WASTE_DEFAULTS, wasteProblems,
} from './wastepackage.js';
import {
	DIS_EQUATION_KEYS, DIS_DEFAULTS, normaliseActions, disruptionProblems,
} from './disruption.js';
import { OPERATIONS, AGGREGATE_OPERATIONS, operationFromEco } from './reduce.js';
import {
	EXTREMES,
	extremeFromEco,
	DIRECTIONS,
	directionFromEco,
} from './recorders.js';

export class ValidationError extends Error {
	constructor(message, blockName) {
		super(blockName ? `${blockName}: ${message}` : message);
		this.name = 'ValidationError';
		this.blockName = blockName;
	}
}

/**
 * The most output times one run may be asked for.
 *
 * Not a limit on the solve, on the model or on the span -- only on how many
 * instants are *reported*, which is what the results are made of: one row of
 * every state per point. Past this the answer is a different way of asking
 * (the solver's own points, or a series over the part that matters), not a
 * bigger array.
 */
export const MAX_OUTPUT_POINTS = 100000;

export const DEFAULT_SIMULATION = {
	start_time: 0,
	end_time: 1e5,
	output_points: 250,
	spacing: 'log',
	solver: DEFAULT_SOLVER,
	// The tolerances a new model starts with, and the fallback for a file that
	// states none. These are the conventional defaults -- the same pair the
	// published methods and every other suite start from -- and they are what
	// a model should be *judged* against rather than what it must be run at:
	// tighten them on a model whose answer still moves when you do.
	rtol: 1e-3,
	abstol: 1e-6,
	time_unit: 'year',
	// The master switch over every compartment's *cannot go negative*, which a
	// project file spells `saturation-enabled` and which is read before any
	// compartment is looked at: off, and no state is held whatever its own
	// flag says; on, and each state's own flag decides. A file defaults it to
	// false and this tool to true, which is the difference between a setting
	// that was added for a saturation band this tool does not carry and one
	// that is the only constraint here -- see *A global switch over the floor*
	// in INTERNALS.md.
	non_negative: true,
	// What a probabilistic run would do, from the file's own probabilistic
	// settings: `no-simulations`, `sampling` and `seed`. All three corpus
	// models that carry them say 1000, "Latin Hypercube" and a seed.
	//
	// These are read and kept and they do *not* make Run probabilistic. A file
	// says 1000, and pressing Run on an imported assessment of 23,436 states
	// would then be a thousand integrations nobody asked for. A probabilistic
	// run is started on purpose, from its own dialog, which is where these
	// numbers appear as the defaults. See ../sim/probabilistic.js.
	iterations: 1000,
	seed: 1,
	// 'latin' or 'random'. Latin hypercube covers each parameter's range
	// evenly instead of leaving the clumps independent draws leave, which is
	// why it is what an assessment uses.
	sampling: 'latin',
};

// The two rules a name has to pass, shared with the editor and the importer
// so that the gates cannot drift apart. See ./names.js.

/** Which value keys each kind of block carries, block-level and per entry. */
const VALUE_KEYS = {
	// `initial` first: it is the block's value, the one the per-index grid
	// edits and the one an older file's `default` becomes. `abstol` rides
	// along with it, so a tolerance can be set for one nuclide of one
	// compartment -- and
	// `non_negative` for the same reason: the constraint is applied per state,
	// and one nuclide of one compartment is one state. A daughter that really
	// does go slightly negative while its parent is being integrated hard is
	// exactly the case for turning it off in one cell and nowhere else.
	// `dydt` is an extra
	// term added to the compartment's rate of change beside what its
	// transfers and its decay give. Per entry for the same reason the
	// initial condition is -- a predator and its prey in one indexed
	// compartment each have their own.
	compartment: ['initial', 'abstol', 'non_negative', 'dydt'],
	// A function has one value key like an expression, and no entries: its
	// body is one equation whatever it is called with, and what varies
	// between calls is the arguments, not the index.
	function: ['equation'],
	transfer: ['rate', 'multiply_by_donor'],
	expression: ['equation'],
	// `value` first, because the first key is *the* value: a parameter's number.
	// `pdf` beside it is the distribution that number was drawn from, per index
	// for the same reason the number is -- a sorption coefficient has one per
	// nuclide, and so does its spread. Kept and shown; nothing samples it yet.
	// See ./pdf.js.
	parameter: ['value', 'pdf'],
	inflow: ['rate'],
	lookup: ['points'],
	index_reduction: ['target'],
	block_reduction: ['targets'],
	min_max: ['target', 'reset_trigger', 'start_trigger', 'stop_trigger'],
	running_mean: ['target', 'reset_trigger', 'start_trigger', 'stop_trigger'],
	snapshot: ['target', 'trigger', 'initial'],
	delay: ['target', 'delay'],
	trigger: ['first', 'second', 'direction'],
	// Every FARFCOMP setting that is an equation. Sorption, diffusion and the
	// porosity a nuclide sees are properties of the nuclide and hold a value
	// per nuclide; the ones that describe the path -- its travel time, its
	// flow-wetted surface, its Peclet number -- hold one value however many
	// nuclides travel along it, but a block indexed by something *else* is
	// that many paths side by side, and those are exactly the numbers that
	// differ between them. So both are entry-able, and the dimension each is
	// read over is what keeps them apart: see the setting slots in
	// ../sim/builder.js. The cell counts are not here -- they decide how many
	// states there are before any equation is evaluated. See ./farfield.js.
	farfield: FARF_EQUATION_KEYS,
	// Waste packages: the inventory, the instant-release fraction and the
	// degradation rate are per index; how the packages fail holds one value
	// each. See ./wastepackage.js.
	waste_package: WASTE_EQUATION_KEYS,
	// Disruptive events: when, as equations. What they do is a list of
	// actions, normalised in `_block`. See ./disruption.js.
	event: DIS_EQUATION_KEYS,
};

/** Every collection of blocks a project holds, in the order they are built. */
const BLOCK_COLLECTIONS = [
	'parameters', 'compartments', 'expressions', 'transfers', 'inflows',
	'lookups', 'index_reductions', 'block_reductions', 'functions',
	'min_maxes', 'running_means', 'snapshots', 'delays', 'triggers',
	'farfields', 'waste_packages', 'events',
];

export class Project {
	constructor(raw = {}) {
		// Keys are snake_case; a file written in the older camelCase spelling
		// is renamed rather than half-read. See ./keys.js.
		raw = migrateKeys(raw);
		this.name = raw.name ?? 'Untitled project';
		this.description = raw.description ?? '';

		this.simulation = { ...DEFAULT_SIMULATION, ...(raw.simulation ?? {}) };
		// The five numbers, as numbers. A file may spell any of them as a
		// string -- plenty of hand-written ones do -- and every comparison
		// below is numeric except the one that decides whether the run has a
		// span at all: `"100" > "20"` is false, so a model with the ends
		// written as strings was accepted and its time grid came out NaN.
		for (const key of ['start_time', 'end_time', 'output_points', 'rtol', 'abstol']) {
			const v = this.simulation[key];
			if (v == null || typeof v === 'number') continue;
			const n = Number(v);
			if (!Number.isFinite(n)) {
				throw new ValidationError(
					`'${v}' is not a number, and ${key.replace(/_/g, ' ')} has to be one`,
				);
			}
			this.simulation[key] = n;
		}
		// The solver's own settings, each read only by the solvers that have
		// one -- see SOLVER_OPTIONS in ../ode/solvers.js, which is where what
		// they mean is written down. Normalised here whatever the solver, so
		// that changing the solver never silently changes what a setting says.
		//
		// Out of range is refused rather than clamped: a step budget of -1 or
		// an order of 9 is a mistake, and a run that quietly used something
		// else would be a number nobody could account for.
		for (const [key, least, most] of [
			['max_step', 0, Infinity], ['initial_step', 0, Infinity],
			['max_steps', 1, Infinity], ['max_order', 1, 5], ['min_order', 1, 5],
			['newton_kappa', 0, 1], ['max_jac_age', 1, Infinity], ['below_tol_run', 0, Infinity],
			['stagnation_tol', 0, 1],
		]) {
			const v = this.simulation[key];
			if (v == null || v === '') { delete this.simulation[key]; continue; }
			const n = Number(v);
			if (!Number.isFinite(n) || n < least || n > most) {
				throw new ValidationError(
					`'${v}' is not a ${key.replace(/_/g, ' ')}: a number `
					+ `${most === Infinity ? `of at least ${least}` : `between ${least} and ${most}`}`,
				);
			}
			this.simulation[key] = n;
		}
		if (Number(this.simulation.min_order) > Number(this.simulation.max_order ?? 5)) {
			throw new ValidationError(
				`The lowest order (${this.simulation.min_order}) is above the highest `
				+ `(${this.simulation.max_order ?? 5})`,
			);
		}
		for (const [key, allowed] of [
			['error_norm', ['rms', 'max']], ['matrix', ['auto', 'refactor', 'sparse', 'dense']],
			['jacobian', ['analytic', 'numeric']],
		]) {
			const v = this.simulation[key];
			if (v == null || v === '') { delete this.simulation[key]; continue; }
			if (!allowed.includes(v)) {
				throw new ValidationError(
					`'${v}' is not a ${key.replace(/_/g, ' ')} (${allowed.join(', ')})`,
				);
			}
		}
		{
			const v = this.simulation.norm_control;
			this.simulation.norm_control = v === true || v === 'true' || v === 1;
		}
		// The NDF's and QNDF's BDF switch: every κ zero, the plain backward
		// differentiation formulas. Off unless the file says so.
		{
			const v = this.simulation.bdf;
			this.simulation.bdf = v === true || v === 'true' || v === 1;
		}
		// The master switch, as a boolean. A file may spell it `"false"` or
		// `0`, which are both true as they stand -- the same coercion the
		// per-compartment flag gets, for the same reason.
		{
			const v = this.simulation.non_negative;
			this.simulation.non_negative = v !== false && v !== 'false' && v !== 0;
		}
		// The mass-balance audit is opt-in: it adds states to the vector and
		// declines the analytic Jacobian, which is a price to pay on purpose.
		{
			const v = this.simulation.mass_balance;
			this.simulation.mass_balance = v === true || v === 'true' || v === 1;
		}
		// The floating absolute tolerance is opt-in for the same reason: it
		// trades accuracy in a decayed tail for steps, and which of those a
		// model wants is the modeller's to say. See ../ode/solvers/ndf.js.
		{
			const v = this.simulation.auto_abstol;
			this.simulation.auto_abstol = v === true || v === 'true' || v === 1;
		}
		{
			// Whole, positive, and at least one: a fractional or negative
			// realisation count is a typo, and zero is a run that does nothing.
			const n = Math.round(Number(this.simulation.iterations));
			this.simulation.iterations = Number.isFinite(n) && n > 0 ? n : 1000;
			const s = Math.round(Number(this.simulation.seed));
			this.simulation.seed = Number.isFinite(s) ? s : 1;
			if (this.simulation.sampling !== 'random') this.simulation.sampling = 'latin';
		}
		if (!TIME_UNITS[this.simulation.time_unit]) {
			throw new ValidationError(`Unknown time unit '${this.simulation.time_unit}'`);
		}
		if (!SPACINGS.includes(this.simulation.spacing)) {
			throw new ValidationError(
				`'${this.simulation.spacing}' is not a way of choosing output times `
				+ `(${SPACINGS.join(', ')})`,
			);
		}
		// The series the output grid is built from, when it is built from a
		// list of them. Normalised here so nothing downstream has to cope with
		// a number written as a string or a series with no kind.
		this.outputTimes = normaliseSeries(this.simulation.output_times);
		this.simulation.output_times = this.outputTimes;
		/**
		 * Where the output times come from: a grid, the solver's own steps, or
		 * both. Ecolego's `EOutputMode`, and only the runner acts on it.
		 */
		this.outputMode = this.simulation.spacing === 'solver' ? 'solver'
			: this.simulation.spacing === 'both' ? 'both' : 'grid';
		/** Whether the solver's own steps are part of the output. */
		this.solverPoints = this.outputMode !== 'grid';

		this.nuclides = Array.from(raw.nuclides ?? []);
		// What a radionuclide inventory is measured in: an activity, or an
		// amount. It decides the ingrowth coefficient and nothing else -- see
		// DECAY_UNITS -- and `Bq` is Ecolego's default, which is what every
		// model in the corpus carries.
		this.decayUnit = String(raw.decay_unit ?? 'Bq').trim();
		// The half-life above which an un-modelled daughter is a sink rather
		// than passed through when the decay pairs are collapsed -- see
		// `collapse` in ./decaydb.js. Absent means never: the chains are walked
		// to their stable ends, which is what every model did before this.
		const ceiling = Number(this.simulation.decay_ceiling);
		this.decayCeiling = Number.isFinite(ceiling) && ceiling > 0 ? ceiling : Infinity;
		if (!DECAY_UNITS.includes(this.decayUnit)) {
			throw new ValidationError(
				`Unknown decay unit '${this.decayUnit}' (${DECAY_UNITS.join(' or ')})`,
			);
		}
		// A half-life may be written as a number of years or as the word
		// `stable`, which is how a non-decaying nuclide survives JSON --
		// Infinity does not. Everything below this line sees numbers.
		// Checked, not merely converted. A half-life is the one number in a
		// radioecological model that cannot be sanity-checked by looking at the
		// result: `Number('banana')` is NaN, which reads downstream as "no
		// decay", and a *negative* half-life gives a negative decay constant --
		// an inventory that grows without bound. Both used to run and report a
		// number a reader would have trusted; one of them grew a hundred
		// becquerels into 10^8.
		this.halfLivesOverride = { ...(raw.half_lives ?? {}) };
		// Prototype-free, because it is keyed by a nuclide's name and a
		// nuclide called `constructor` or `toString` would otherwise find a
		// function on `Object.prototype` instead of nothing -- read as a
		// half-life that is not a number, which `lambda` quietly treats as
		// stable. An unknown nuclide should look unknown.
		this.halfLives = Object.assign(Object.create(null), HALF_LIVES);
		for (const [nuc, v] of Object.entries(this.halfLivesOverride)) {
			if (v == null) continue;
			if (/^(stable|inf(inity)?)$/i.test(String(v).trim())) {
				this.halfLives[nuc] = Infinity;
				continue;
			}
			const years = Number(v);
			if (!Number.isFinite(years) || years <= 0) {
				throw new ValidationError(
					// Always years: half-lives are stored in years whatever the
					// simulation counts time in, and `lambda` converts.
					`The half-life of '${nuc}' must be a number of years greater than `
					+ `zero, or 'stable' -- '${v}' is neither.`, nuc,
				);
			}
			this.halfLives[nuc] = years;
		}

		// A decay pair is [parent, daughter, branching]. A malformed one used
		// to change the decay model silently: a two-element pair made the
		// branching `undefined`, so the ingrowth coefficient became NaN and
		// the daughter's whole curve with it.
		this.chainsOverride = raw.chains ? raw.chains.map((c) => [...c]) : null;
		// Kept only so a flux can ask what the blocks at its ends are indexed
		// by: compartments are built before transfers and paths after them, so
		// neither is reliably there to ask. See `_endpointDims`.
		this._raw = raw;
		for (const pair of this.chainsOverride ?? []) {
			const [parent, daughter, ratio] = pair;
			const named = `[${pair.map((x) => JSON.stringify(x)).join(', ')}]`;
			if (typeof parent !== 'string' || !parent.trim()
				|| typeof daughter !== 'string' || !daughter.trim()) {
				throw new ValidationError(
					`A decay pair is [parent, daughter, branching]; ${named} does not `
					+ `name two nuclides.`,
				);
			}
			const r = ratio === undefined ? 1 : Number(ratio);
			if (!Number.isFinite(r) || r <= 0 || r > 1) {
				throw new ValidationError(
					`The branching from '${parent}' to '${daughter}' must be greater `
					+ `than zero and at most 1; ${named} gives `
					+ `${ratio === undefined ? 'none' : JSON.stringify(ratio)}.`,
				);
			}
			// A pair that left the branching out means all of it, which is
			// what a single-branch chain is; written down so the decay model
			// never sees an undefined.
			if (pair.length < 3) pair[2] = 1;
		}

		// The `nuclides` shorthand becomes a real index list, so there is only
		// one indexing mechanism below this line -- and the element dimension
		// that goes with it is derived rather than stored, so it cannot fall
		// out of step with the nuclides. See deriveElements.
		const declared = desugarNuclides(raw);
		// ...and the two dimensions the model's own contents make: one index
		// per compartment and one per transfer. Derived from `raw` rather than
		// from the blocks below, which do not exist yet: their dimensions are
		// resolved against these lists.
		const lists = deriveBlockLists(deriveElements(declared), raw);
		this._derivedLists = new Set(lists.filter((l) => l.derived).map((l) => l.name));
		this.index_lists = normaliseIndexLists(lists);
		try {
			this.indexSpace = new IndexSpace(this.index_lists);
		} catch (e) {
			if (e instanceof IndexError) throw new ValidationError(e.message, e.detail);
			throw e;
		}

		const materials = this.indexSpace.materialList();
		this.materialListName = materials ? materials.name : null;
		// The two material roles. The catalogue above is the root decay runs
		// along; this is the sub-set of it that has half-lives, and it is what
		// "per nuclide" means -- the dimension a block falls back to, and the
		// one the two per-nuclide shorthands are keyed by. A file that states
		// only one list has both roles on it, which is what the fallback says.
		this.nuclideListName = this.indexSpace.nuclideList()?.name
			?? this.materialListName;

		// The pairs the model states, or the ones that follow from what it
		// carries. Worked out here rather than read from a table, so a model
		// never has to write down a chain it did not choose -- and so the
		// branching is the one that actually reaches each nuclide, through
		// however many short-lived members were left out.
		this.chains = this.chainsOverride ?? defaultChains(this.materialNames);

		// Which scenario is live. Ecolego runs one simulation per scenario;
		// this tool runs the one that is selected, and every block indexed by
		// the scenario list is read at that index -- which is what
		// `ScenarioIndexWrapper` does inside a single run. A saved choice that
		// no longer names a scenario falls back to the first rather than to
		// none, so a model always has one selected while it has any.
		if (raw.scenario != null && this.indexSpace.setScenario(raw.scenario) == null) {
			this.indexSpace.setScenario(this.indexSpace.scenarios()[0] ?? null);
		}
		this.scenario = this.indexSpace.scenario;
		this.scenarios = this.indexSpace.scenarios();

		this.parameters = (raw.parameters ?? []).map(
			(p) => this._block(p, 'parameter'),
		);
		this.compartments = (raw.compartments ?? []).map(
			(c) => this._block(c, 'compartment'),
		);
		this.expressions = (raw.expressions ?? []).map(
			(e) => this._block(e, 'expression'),
		);
		this.transfers = (raw.transfers ?? []).map(
			(t) => this._block(t, 'transfer'),
		);
		this.inflows = (raw.inflows ?? []).map(
			(s) => this._block(s, 'inflow'),
		);
		this.lookups = (raw.lookups ?? []).map(
			(l) => this._block(l, 'lookup'),
		);
		this.index_reductions = (raw.index_reductions ?? []).map(
			(o) => this._block(o, 'index_reduction'),
		);
		this.block_reductions = (raw.block_reductions ?? []).map(
			(a) => this._block(a, 'block_reduction'),
		);
		// The functions an equation may call. Global, as Ecolego's
		// the file has it: one flat list on the model rather than one per
		// sub-system.
		this.functions = (raw.functions ?? []).map(
			(f) => this._block(f, 'function'),
		);
		// The five blocks that depend on what has already happened rather than
		// only on the state as it stands. See ../sim/history.js.
		this.min_maxes = (raw.min_maxes ?? []).map(
			(m) => this._block(m, 'min_max'),
		);
		this.running_means = (raw.running_means ?? []).map(
			(m) => this._block(m, 'running_mean'),
		);
		this.snapshots = (raw.snapshots ?? []).map(
			(m) => this._block(m, 'snapshot'),
		);
		this.delays = (raw.delays ?? []).map(
			(m) => this._block(m, 'delay'),
		);
		this.triggers = (raw.triggers ?? []).map(
			(m) => this._block(m, 'trigger'),
		);
		// Far-field paths: a whole dual-porosity transport model behind one
		// block, with several hundred states of its own. See ./farfield.js.
		this.farfields = (raw.farfields ?? []).map(
			(m) => this._block(m, 'farfield'),
		);
		// Waste packages: two inventories per nuclide behind one block, and a
		// release out of it. See ./wastepackage.js.
		this.waste_packages = (raw.waste_packages ?? []).map(
			(m) => this._block(m, 'waste_package'),
		);
		// Disruptive events: something happens at an instant. See ./disruption.js.
		this.events = (raw.events ?? []).map(
			(m) => this._block(m, 'event'),
		);

		// A disabled block takes no part in the run. Ecolego's `enabled` on
		// every block: the block stays in the model, keeps its equations
		// and its values, and is left out when the model is built -- which is
		// how a model with a broken block in it still runs, as long as nothing
		// that is enabled reads the broken one. The names are kept so that a
		// reference to one can be answered with "that is disabled" rather than
		// "unknown name".
		this.disabled = new Set();
		// Kept aside rather than thrown away: everything below this line works
		// on the model as it runs, and `toJSON` puts them back, so that a
		// project round-tripped through this class is the project that went
		// in. Dropped outright, a save of a re-read model lost every switched
		// off block in it.
		// Whole sub-systems switched off, as paths: a sub-system block
		// is a block with a block's switch, and off, it takes everything in it
		// out of the run. A block inside keeps its own switch untouched, so
		// turning the sub-system back on returns it to exactly what it was.
		// Why each block went is remembered for `implicitlyDisabled`, which is
		// built once the connections have been resolved below.
		this.disabledSystems = new Set(
			(Array.isArray(raw.disabled_systems) ? raw.disabled_systems : [])
				.map((p) => String(p ?? '').trim()).filter(Boolean),
		);
		const offBySystem = (block) => {
			const home = block.system ?? '';
			if (!home) return null;
			const by = [...this.disabledSystems].filter((p) => isWithin(home, p))
				.sort((a, b) => a.length - b.length)[0];
			return by ?? null;
		};
		this._offReasons = new Map();
		this._switchedOff = new Map();
		for (const key of BLOCK_COLLECTIONS) {
			const kept = [];
			const off = [];
			for (const block of this[key]) {
				const by = block.enabled === false ? null : offBySystem(block);
				if (block.enabled === false || by) {
					this.disabled.add(block.qname);
					off.push(block);
					if (by) this._offReasons.set(block.qname, `it is in '${by}', which is disabled`);
				} else kept.push(block);
			}
			this[key] = kept;
			if (off.length) this._switchedOff.set(key, off);
		}

		// The sub-systems the model is organised into, as dotted paths. A
		// declared one survives even when empty: it is where the next block
		// goes. See ./systems.js.
		this.systems = systemPaths(raw);
		// Which of them are transports: a sub-system that stands for a chain
		// of N identical compartments, drawn as its first and its last. The
		// blocks inside carry their parts (`transport: 'begin'` and so on);
		// the sub-system itself is only a path, so its kind is kept here. See
		// ./transport.js and ../sim/transport.js.
		this.transports = new Set(
			(Array.isArray(raw.transports) ? raw.transports : [])
				.map((p) => String(p ?? '').trim()).filter(Boolean),
		);
		// A switched-off sub-system has to be one the model has. A stale path
		// in a hand-edited file would otherwise switch nothing off and say
		// nothing, and the modeller would run a model with more in it than
		// they meant.
		for (const p of this.disabledSystems) {
			if (!this.systems.includes(p)) {
				throw new ValidationError(
					`'${p}' is listed as a disabled sub-system, but there is no sub-system `
					+ 'of that name', p,
				);
			}
		}
		// A connection's endpoints are names like any other reference, so they
		// are resolved in the connection's own sub-system and stored qualified.
		this._resolveEndpoints();

		this.layout = { ...(raw.layout ?? {}) };
		// Shapes drawn on the canvas: annotation, and the only thing in a
		// project file this class carries without reading. A group box round
		// four compartments, a tree, an arrow -- see `shapes` in ./edit.js.
		// Nothing here validates them because nothing here uses them: they are
		// kept so that a model round-tripped through this class comes out with
		// its drawing intact.
		this.shapes = Array.isArray(raw.shapes) ? structuredClone(raw.shapes) : [];
		// Numbers read off the finished curves -- a peak, the year it peaked,
		// a total. Carried rather than validated here: they are not blocks and
		// they take no part in the integration, so a mis-typed one costs one
		// output and is reported by `derivedProblems`. See ./derived.js.
		this.derived = Array.isArray(raw.derived) ? structuredClone(raw.derived) : [];
		// Diagram view state: which kinds of block are drawn. Presentation
		// only -- it takes no part in validation or in the equations.
		this.view = raw.view ? { ...raw.view } : null;

		this.validate();
	}

	/** Normalises one block: defaults, dimensions, entries. */
	_block(raw, kind) {
		const base = { ...DEFAULTS[kind], ...raw };
		base.kind = kind;

		// The part a block plays in a transport sub-system, when it has one:
		// a compartment is its `begin` or its `end`, an expression is its
		// `number` (how many compartments the chain has), its `counter` (which
		// of them an equation is being evaluated for) or an `operation` over
		// all of them. Ecolego has a class for each -- TransportBegin extends
		// Compartment, TransportNumber extends Expression -- and this tool has
		// a flag, so that everything that treats a compartment as a
		// compartment goes on doing so. See ./transport.js.
		const role = (TRANSPORT_ROLES[kind] ?? []).includes(raw.transport) ? raw.transport : null;
		if (role) base.transport = role;
		else delete base.transport;
		if (role === 'counter') {
			// It has no equation of its own: the run substitutes the element
			// number, and outside the chain it is 1, which is what Ecolego's
			// `getCurrentElement` answers when no element is current.
			base.equation = '1';
		}
		if (role === 'operation') {
			// What it works out over the chain's compartments, and how it is
			// read: as a value (`all`), or called with a position along the
			// chain (`point`) or with two (`range`). TransportOperation's
			// Operation and OptionArgument, by this tool's names or Ecolego's.
			base.operation = transportOperationFromEco(raw.operation) ?? 'mean';
			base.argument = transportArgumentFromEco(raw.argument) ?? 'all';
		}

		// The only constraint any solver here
		// applies. On unless a model turns it off, because an inventory cannot
		// be negative -- but turning it off is worth being able to do, since a
		// compartment held at zero by the constraint looks like a result and is
		// usually a modelling error being hidden.
		//
		// Ecolego's lower/upper saturation band is not carried: only ros23
		// could honour it, so a model that set one meant something different
		// under each solver. `src/io/eco.js` maps the band a file does set onto
		// this flag and reports whatever it could not.
		if (kind === 'compartment') base.non_negative = base.non_negative !== false;
		// Off unless a model asks for it by name: a flux whose dimensions its
		// end has not got is added up on the way in, and a model should say so
		// rather than have it happen. See `summedDims` and the check in
		// `validate`, and the desktop tool, which refuses the shape
		// outright.
		// Written only when it is on, so that the overwhelming majority of
		// fluxes -- every one whose ends correspond -- carry nothing about it
		// in the file or the JSON view.
		if (kind === 'transfer' || kind === 'inflow') {
			if (base.sum_extra_indices === true || base.sum_extra_indices === 'true') {
				base.sum_extra_indices = true;
			} else delete base.sum_extra_indices;
		}
		base.comment = raw.comment ?? '';

		if (kind === 'lookup') {
			// The interpolation rule, accepted either by this tool's short name
			// or by the spelling an Ecolego project uses. An unrecognised one
			// is kept as written so that `validate` can name it: quietly
			// falling back to straight lines would change what a file means
			// without saying so.
			base.interpolation = raw.interpolation == null || raw.interpolation === ''
				? 'linear'
				: interpolationFromEco(raw.interpolation) ?? raw.interpolation;
			base.cyclic = !!raw.cyclic;
			// A table is read at the simulation clock unless it declares an
			// argument, in which case it is called -- `Table(x)` -- and reads
			// whatever the caller passes. Ecolego's LookupTable.OptionArgument.
			base.argument = raw.argument ? String(raw.argument) : null;
			base.points = normalisePoints(raw.points, raw.name);
		}

		if (kind === 'index_reduction' || kind === 'block_reduction') {
			// The reduction, accepted either by this tool's short name or by
			// the spelling an Ecolego project uses. An unrecognised one is kept
			// as written so that `validate` can name it.
			base.operation = raw.operation == null || raw.operation === ''
				? 'sum'
				: operationFromEco(raw.operation) ?? raw.operation;
		}
		if (kind === 'index_reduction') {
			base.target = raw.target == null ? null : String(raw.target);
			base.percentile = raw.percentile == null ? null : Number(raw.percentile);
		}
		if (kind === 'block_reduction') {
			base.targets = normaliseTargets(raw.targets, raw.name);
		}
		if (kind === 'function') {
			// The names its body uses for the values passed in, in order.
			// Written down rather than derived from the body, because the
			// order is what a call site matches against and a body that
			// mentions two of three parameters still takes three.
			base.parameters = (Array.isArray(raw.parameters) ? raw.parameters : [])
				.map((p) => String(p ?? '').trim()).filter(Boolean);
			base.equation = raw.equation == null ? '' : String(raw.equation);
			// A function is not indexed and holds no value per index: it is
			// called, and the index it is worked out at is the caller's.
			// Ecolego's argumented expressions do declare a dimension --
			// `RegoLow_eq` says Radionuclides -- but the generated method
			// takes the caller's indices, so the declaration says only what
			// the values it reads are per. Said here rather than left to
			// whatever the file happened to carry.
			base.system = raw.system ?? '';
			base.index_lists = [];
			base.entries = [];
			base.qname = qualifiedName(base);
			return base;
		}
		if (kind === 'min_max') {
			// Which extreme, by this tool's name or the file's. An
			// unrecognised one is kept as written so `validate` can name it.
			base.operation = raw.operation == null || raw.operation === ''
				? 'max'
				: extremeFromEco(raw.operation) ?? raw.operation;
		}
		if (kind === 'farfield') {
			// The cell counts and the outflow condition are whole numbers, not
			// equations: the state vector is laid out from them before any
			// equation is evaluated, so a value that moved with the clock
			// could not mean anything. Kept as written when it is not a
			// number, so that `validate` can name it.
			for (const key of FARF_STRUCTURE_KEYS) {
				const v = Number(raw[key] ?? DEFAULTS.farfield[key]);
				base[key] = Number.isFinite(v) ? Math.round(v) : raw[key];
			}
			// Where the release goes is a transfer drawn out of the block, not
			// a field on it: see `migrateFarfieldTargets` in ./keys.js.
			delete base.to;
		}
		if (kind === 'waste_package') {
			// How the packages fail is a choice, not an equation; kept as
			// written when it is not one of the ways, so `validate` can name it.
			base.failure = raw.failure == null || raw.failure === '' ? 'never' : raw.failure;
			// A count, for the reader and for a sampled failure later: whole
			// and at least one when it is a number at all.
			const n = Number(raw.packages ?? DEFAULTS.waste_package.packages);
			base.packages = Number.isFinite(n) ? Math.round(n) : raw.packages;
			const v = raw.handle_decay;
			base.handle_decay = v !== false && v !== 'false' && v !== 0;
			// The release leaves through a transfer drawn out of the block.
			delete base.to;
		}
		if (kind === 'event') {
			base.timing = raw.timing == null || raw.timing === '' ? 'at' : raw.timing;
			const v = raw.sampled;
			base.sampled = v !== false && v !== 'false' && v !== 0;
			base.actions = normaliseActions(raw.actions);
		}
		if (kind === 'trigger') {
			base.direction = raw.direction == null || raw.direction === ''
				? 'rising'
				: directionFromEco(raw.direction) ?? raw.direction;
		}
		// A flux's unit follows from its donor and the model's time unit, so a
		// file that never passed through the editor still gets the right label
		// instead of the '1/year' constant.
		//
		// A compartment's follows from the model too: it holds an inventory,
		// and an inventory is measured in whichever unit this model's
		// radionuclides are in. DEFAULTS says `Bq` because that is Ecolego's
		// default *choice*, not because a model that counts atoms holds
		// becquerels. See syncInventoryUnits in ./units.js, which is the same
		// rule on the editor's side of the model.
		//
		// An explicit unit is left alone in every case.
		// Before the unit, because a compartment's follows from which material
		// dimension it is on -- and whether the materials there agree.
		base.index_lists = this._dimensionsFor(raw, kind);
		// An event has no index: it acts on whole blocks, and its own value is
		// a count of occurrences.
		if (kind === 'event') base.index_lists = [];

		base.unit = raw.unit
			?? (DERIVED_UNIT_KINDS.includes(kind) ? derivedUnit(this, base, kind) : null)
			?? (kind === 'compartment' ? this._inventoryUnit(base) : null)
			// A path's own value is what leaves its far end per unit time.
			?? (kind === 'farfield' || kind === 'waste_package'
				? `${this.decayUnit}/${this.simulation.time_unit}`
				: null)
			?? DEFAULTS[kind].unit ?? '';
		// A transport's number and counter are counts of compartments, which
		// have no unit: `TransportNumber.getUnit` and
		// `TransportElementCounter.getUnit` both answer unitless whatever was
		// typed in.
		if (base.transport === 'number' || base.transport === 'counter') base.unit = '';

		// Where the block sits in the hierarchy, and the one name the rest of
		// the application addresses it by. For a model with no sub-systems the
		// qualified name is the name, which is why nothing else had to change.
		base.system = raw.system ?? '';
		base.qname = qualifiedName(base);

		base.entries = normaliseEntries(raw, kind, this.nuclideListName, base.index_lists);

		// The legacy shorthands have been folded into entries; drop them so
		// nothing downstream has two places to look.
		if (base.initial && typeof base.initial === 'object') base.initial = '0';
		// The explicit dy/dt term is optional, and blank is the same as
		// absent: Ecolego writes an empty `<differential-equation>` on every
		// entry it saves, and nothing downstream should have to ask twice.
		// A number typed in is an equation like any other.
		if (kind === 'compartment') {
			for (const holder of [base, ...base.entries]) {
				if (!Object.prototype.hasOwnProperty.call(holder, 'dydt')) continue;
				if (holder.dydt == null || String(holder.dydt).trim() === '') delete holder.dydt;
				else holder.dydt = String(holder.dydt);
			}
		}
		// `default` is an older name for the block-level value, kept because
		// files in the wild use it -- examples/biosphere.json does. It used to
		// be dropped unread, which silently turned a stated default into zero;
		// harmless while every index has an entry, wrong the moment one does
		// not. An explicit value still wins.
		const valueKey = VALUE_KEYS[kind]?.[0];
		if (valueKey && raw.default !== undefined && raw[valueKey] === undefined) {
			base[valueKey] = raw.default;
		}
		delete base.values_by_nuclide;
		delete base.default;
		delete base.per_nuclide;

		return base;
	}

	/**
	 * Turns each connection's endpoints into qualified names.
	 *
	 * A transfer inside a sub-system names its compartments the way its
	 * equations name anything else -- `Water` for one of its own, a longer path
	 * for one further off -- so the endpoints are resolved in the connection's
	 * own scope. An endpoint that resolves to nothing is left alone for
	 * `validate` to report by the name the file actually used.
	 */
	_resolveEndpoints() {
		// A far-field path is both ends of a connection: somewhere a flux can
		// be delivered -- into its first fracture cell -- and somewhere a
		// release comes from. So its name resolves as an endpoint exactly as a
		// compartment's does.
		const compartments = new Set([
			...this.compartments.map((c) => c.qname),
			...this.farfields.map((f) => f.qname),
			...this.waste_packages.map((w) => w.qname),
		]);
		const known = (n) => compartments.has(n);
		for (const conn of [...this.transfers, ...this.inflows]) {
			for (const end of ['from', 'to']) {
				const ref = conn[end];
				if (ref == null) continue;
				// An endpoint is an id -- Ecolego stores connections by id --
				// so a name that already names a compartment is that
				// compartment. Only otherwise is it read as a relative name,
				// which is what a hand-written file is likely to use. Without
				// the exact match first, a connection inside a sub-system
				// could not reach a top-level compartment whose name the
				// sub-system also uses.
				conn[end] = known(ref)
					? ref
					: resolveReference(ref, systemOf(conn), known) ?? ref;
			}
		}
		this._followDisabledEnds();
	}

	/**
	 * What a connection does when one of its compartments is switched off --
	 * Ecolego's rule, as its models behave: a transfer is on when its own
	 * switch is on and its donor is on.
	 *
	 * A transfer whose *donor* is disabled is disabled with it: there is no
	 * inventory for it to move. Its target is not consulted, so a transfer into
	 * a disabled compartment stays on -- its flux still leaves the donor and,
	 * with nothing integrating the receiving end, leaves the model, exactly as
	 * a flux to `outside` does. A source term is a transfer from the boundary
	 * whose only compartment is its target, so one into a disabled compartment
	 * has nothing left to feed and is switched off too.
	 *
	 * Recorded rather than only done: the diagram fades what is off and the
	 * Information view says why, and both read `implicitlyDisabled`.
	 */
	_followDisabledEnds() {
		// Starting from the blocks a disabled sub-system took with it, so
		// that one map answers "why is this off" for both kinds of reason.
		this.implicitlyDisabled = new Map(this._offReasons ?? []);
		const keep = (conn, end) => {
			const off = this.disabled.has(conn[end]);
			return off;
		};
		this.transfers = this.transfers.filter((t) => {
			if (t.from != null && keep(t, 'from')) {
				this.implicitlyDisabled.set(t.qname,
					`its donor '${t.from}' is disabled, so there is no inventory for it to move`);
				this.disabled.add(t.qname);
				return false;
			}
			if (t.to != null && keep(t, 'to')) {
				// Kept, and aimed at the boundary. Said in the note, since a
				// flux that quietly leaves the model is the sort of thing you
				// discover from a mass balance.
				this.implicitlyDisabled.set(`${t.qname}#to`,
					`it flows into '${t.to}', which is disabled, so what it moves leaves the model`);
				t.to = null;
			}
			return true;
		});
		this.inflows = this.inflows.filter((s) => {
			if (s.to != null && keep(s, 'to')) {
				this.implicitlyDisabled.set(s.qname,
					`it flows into '${s.to}', which is disabled, so there is nothing for it to feed`);
				this.disabled.add(s.qname);
				return false;
			}
			return true;
		});
	}

	/**
	 * What the block at one end of a flux is indexed by, read off the raw
	 * model rather than the built one.
	 *
	 * Compartments are built before transfers and far-field paths after them,
	 * so neither is reliably there to ask when a transfer needs its answer.
	 * The raw block says the same thing -- its own `index_lists`, or the
	 * implicit material dimension -- and an end that names nothing here is the
	 * model boundary, which contributes no dimensions at all.
	 */
	_endpointDims(name) {
		if (name == null) return null;
		if (!this._endsByName) {
			this._endsByName = new Map();
			for (const key of ['compartments', 'farfields', 'waste_packages']) {
				for (const b of this._raw[key] ?? []) {
					if (!b?.name) continue;
					this._endsByName.set(qualifiedName(b), b);
				}
			}
		}
		const block = resolveReference(name, '', (n) => this._endsByName.has(n)) ?? name;
		const end = this._endsByName.get(block);
		if (!end) return null;
		if (Array.isArray(end.index_lists)) return IndexSpace.normaliseDims(end.index_lists);
		const implied = this.nuclideListName && this.indexSpace.size(this.nuclideListName)
			? this.nuclideListName
			: this.materialListName;
		return implied && end.per_nuclide !== false ? [implied] : [];
	}

	/**
	 * A block's dimension: an explicit `index_lists`, or the material list when
	 * the model has one and the block has not opted out with per_nuclide:false.
	 */
	_dimensionsFor(raw, kind) {
		// A function has no dimensions: it is called, and what it is called
		// with is an equation the caller writes at whatever index the caller
		// is being evaluated at.
		if (kind === 'function') return [];
		if (Array.isArray(raw.index_lists)) {
			const dims = IndexSpace.normaliseDims(raw.index_lists);
			for (const d of dims) {
				if (!this.indexSpace.has(d)) {
					throw new ValidationError(
						`Unknown index list '${d}'`, raw.name,
					);
				}
				// The two dimensions made of the model's own blocks are for
				// the blocks that hold a value, not for the blocks they are
				// made of: see AUTO_DIM_KINDS.
				const list = this.index_lists.find((l) => l.name === d);
				if (!listApplies(list, kind)) {
					throw new ValidationError(listAppliesWhy(list, kind), raw.name);
				}
			}
			// ...and no two of them may be one dimension twice: a block
			// indexed by both `Nuclide` and `Element` has nothing to say
			// which cell of which it means.
			const clash = clashingDimensions(this.index_lists, dims);
			if (clash) {
				throw new ValidationError(clashingDimensionsWhy(clash), raw.name);
			}
			return dims;
		}
		// A flux is indexed by the indices its two ends have in common, which
		// is not a choice -- see `sharedDims`. A transfer that says nothing
		// takes them, rather than the radionuclides: a transfer between two
		// compartments on the catalogue is per material, and reading it as per
		// radionuclide is a model that will not build.
		if (kind === 'transfer' || kind === 'inflow') {
			const shared = sharedDims(
				this.index_lists,
				this._endpointDims(raw.from ?? null),
				this._endpointDims(raw.to ?? null),
			);
			if (shared) return shared.dims;
		}
		// The radionuclides, or the catalogue when there are none. A model of
		// materials that do not decay -- Lotka-Volterra's rabbits and foxes,
		// a lake's stable carbon -- has an empty radionuclide list and a
		// catalogue that holds everything, and a block in it that says nothing
		// about its dimensions is per material.
		const implied = this.nuclideListName && this.indexSpace.size(this.nuclideListName)
			? this.nuclideListName
			: this.materialListName;
		if (implied && raw.per_nuclide !== false) {
			return [implied];
		}
		return [];
	}

	/**
	 * Every block, keyed by qualified name.
	 *
	 * Over the one list of collections rather than a hand-written sequence of
	 * thirteen `forEach`es -- which is how it came to be missing the far-field
	 * paths, the collection added last.
	 */
	blocksByName() {
		const map = new Map();
		for (const kind of COLLECTIONS) {
			for (const b of this[kind] ?? []) {
				if (map.has(b.qname)) {
					throw new ValidationError(`Duplicate block name '${b.qname}'`, b.qname);
				}
				map.set(b.qname, b);
			}
		}
		return map;
	}

	/** The material names of the catalogue index list, in order. */
	get materialNames() {
		return this.materialListName
			? this.indexSpace.indexNames(this.materialListName)
			: [];
	}

	/** The radionuclides among them, in order: the ones that have a half-life. */
	get nuclideNames() {
		return this.nuclideListName
			? this.indexSpace.indexNames(this.nuclideListName)
			: [];
	}

	/**
	 * What a compartment with no unit of its own holds.
	 *
	 * An inventory, measured in whichever unit this model's radionuclides are
	 * in -- unless the compartment is on the catalogue of a model that carries
	 * materials which are not radionuclides, where there is no single answer:
	 * stable carbon is in kgC at one index and C-14 in Bq at the next, and a
	 * label true of one is false of the other. Then the block carries none and
	 * each series takes its material's own -- which is what Ecolego's
	 * auto-managed unit does, reading `IMaterial.getUnit()` at the index.
	 *
	 * The same rule as `syncInventoryUnits` on the editor's side of the model.
	 */
	_inventoryUnit(base) {
		const dims = base.index_lists ?? [];
		const material = dims.find((d) => {
			const list = this.index_lists.find((l) => l.name === d);
			return !!list && (list.for_contaminants || list.for_nuclides
				|| (list.sub_set_of && list.sub_set_of === this.materialListName));
		});
		if (!material) return this.decayUnit;
		return dimensionUnit(this, material);
	}

	decayModel() {
		return this.decayModelFor(this.materialListName);
	}

	/**
	 * The decay model over one index list's own indices.
	 *
	 * A model may hold more than one nuclide list -- Ecolego keeps a catalogue
	 * and the radionuclide sub-set of it -- and index different compartments by
	 * different ones. Decay is then computed per list, since a parent's
	 * position is a position *in that list*.
	 */
	decayModelFor(listName) {
		const names = listName && this.indexSpace.has(listName)
			? this.indexSpace.indexNames(listName)
			: [];
		return buildDecayModel(names, this.simulation.time_unit, {
			halfLives: this.halfLives,
			decayUnit: this.decayUnit,
			// Per list, not per model: Ecolego keeps a catalogue and a
			// radionuclide sub-set of it, and different compartments may be
			// indexed by different ones. A parent's position is a position in
			// *that* list, so the pairs are collapsed onto its own names --
			// which a single table of chains could never have got right.
			chains: this.chainsOverride ?? defaultChains(names, this.decayCeiling),
		});
	}

	validate() {
		const names = new Set();
		const all = [
			...this.parameters, ...this.compartments, ...this.expressions,
			...this.transfers, ...this.inflows, ...this.lookups,
			...this.index_reductions, ...this.block_reductions,
			...this.min_maxes, ...this.running_means, ...this.snapshots,
			...this.delays, ...this.triggers, ...this.farfields, ...this.waste_packages,
			...this.events,
			// Functions share the one name space: `Dose(x)` and a compartment
			// called `Dose` cannot both be in a model, since an equation
			// naming `Dose` would have two things to mean.
			...this.functions,
		];
		// A dimension with nothing enabled in it has width zero, so a block
		// indexed by it has no slots at all. That used to be refused, because
		// the code generator walked an empty array and threw `Cannot read
		// properties of undefined` from inside itself, naming nothing a
		// reader could act on.
		//
		// It is not an error. A real calculation case leaves a list empty on
		// purpose -- model B has four blocks indexed by waste
		// types its variant does not have -- and Ecolego runs those models.
		// A block with no values holds nothing, contributes nothing and
		// reports nothing, which is what the file says it should do; the
		// generator now emits nothing for it (see `emitLoop`), and reading
		// one is caught where it is read, by the rule that already governs
		// reaching an index you do not carry. `modelWarnings` says so in
		// amber, because a block that quietly holds nothing is worth knowing
		// about even when it is meant.


		for (const b of all) {
			if (!b.name || !NAME_RE.test(b.name)) {
				throw new ValidationError(
					`'${b.name}' is not a valid name (letters, digits and underscore; ` +
					`must not start with a digit)`, b.name,
				);
			}
			if (RESERVED.has(b.name)) {
				throw new ValidationError(`'${b.name}' is a reserved name`, b.name);
			}
			if (!isValidPath(b.system)) {
				throw new ValidationError(
					`'${b.system}' is not a valid sub-system path`, b.qname,
				);
			}
			// A sub-system is the other thing that can wear an id, and the two
			// share one namespace -- the rule for which blocks a sub-system may hold
			// refuses the clash in Ecolego, and the editor refuses it in both
			// directions. A file can still carry one, and it makes a selection
			// ambiguous: everything that sorts a name into "block or
			// sub-system" tries sub-systems first.
			if (this.systems.includes(b.qname)) {
				throw new ValidationError(
					`'${b.qname}' is both a block and a sub-system, and the two cannot `
					+ 'share a name', b.qname,
				);
			}
			// Uniqueness is per sub-system: two compartments called Water in
			// different sub-systems are two different compartments, which is
			// the whole point of having them.
			if (names.has(b.qname)) {
				throw new ValidationError(
					`Duplicate block name '${b.qname}'`
					+ (b.system ? ` in sub-system '${b.system}'` : ''), b.qname,
				);
			}
			names.add(b.qname);
		}

		// A compartment may set its own absolute tolerance, per index or for
		// the whole block, and anything the solver cannot use has to be
		// refused here: `atol = 0` asks for a relative-only error test that
		// none of these solvers implements, and a negative one inverts the
		// test. Absent is the normal case and means "use the simulation's".
		for (const c of this.compartments) {
			for (const [holder, where] of [
				[c, null],
				...c.entries.map((e) => [e, e.index]),
			]) {
				if (!Object.prototype.hasOwnProperty.call(holder, 'abstol')) continue;
				if (holder.abstol == null || holder.abstol === '') continue;
				const v = Number(holder.abstol);
				if (Number.isFinite(v) && v > 0) continue;
				const at = where && Object.keys(where).length
					? ` for ${Object.values(where).join(', ')}`
					: '';
				throw new ValidationError(
					`Absolute tolerance${at} must be a number greater than zero `
					+ `(got ${holder.abstol})`, c.qname,
				);
			}
		}

		const compartments = new Set(this.compartments.map((c) => c.qname));
		// A far-field path is a legal endpoint at either end: a flux can be
		// delivered into its first fracture cell, and its release can be drawn
		// out of it as a line to a compartment. A transfer out of a path is
		// not an ordinary flux -- the mass has already left, taken off the
		// last cell by the outflow condition -- so it carries the release and
		// takes nothing from the path. See `releaseTransfers` in ./edit.js.
		const paths = new Set([
			...this.farfields.map((f) => f.qname),
			...this.waste_packages.map((w) => w.qname),
		]);
		// A path has one release, and so has a set of waste packages. Two
		// lines carrying it would each deliver the whole flux, so the model
		// would release twice what the block let go -- silently, and with
		// neither line looking wrong. The editor refuses the second one; this
		// is the same rule for a file, which may say anything.
		const releasing = new Map();
		for (const t of this.transfers) {
			if (t.from == null || !paths.has(t.from)) continue;
			const held = releasing.get(t.from);
			if (held) {
				throw new ValidationError(
					`'${t.from}' has two releases, '${held}' and '${t.name}'. A `
					+ `block has one -- for a path the flux out of the far end, for `
					+ `waste packages what leaves them -- and each of these would `
					+ `deliver the whole of it, so the model would release twice what `
					+ `the block let go.`, t.name,
				);
			}
			releasing.set(t.from, t.name);
		}
		for (const t of this.transfers) {
			if (t.from != null && !compartments.has(t.from) && !paths.has(t.from)) {
				throw new ValidationError(`Unknown source compartment '${t.from}'`, t.name);
			}
			if (t.to != null && !compartments.has(t.to) && !paths.has(t.to)) {
				throw new ValidationError(`Unknown target compartment '${t.to}'`, t.name);
			}
			if (t.from != null && paths.has(t.from)) {
				if (t.multiply_by_donor !== false) {
					throw new ValidationError(
						`'${t.from}' is a far-field path, so there is no single donor `
						+ `inventory to multiply by: a release carries the flux out of `
						+ `the path itself.`, t.name,
					);
				}
				if (t.to != null && paths.has(t.to)) {
					throw new ValidationError(
						'A release from one far-field path cannot be delivered straight '
						+ 'into another: give it a compartment in between.', t.name,
					);
				}
			}
			if (t.from == null && t.to == null) {
				throw new ValidationError(
					'A transfer must have a source, a target, or both', t.name,
				);
			}
			if (t.from === t.to) {
				throw new ValidationError(`Source and target are both '${t.from}'`, t.name);
			}
		}
		for (const s of this.inflows) {
			if (!compartments.has(s.to) && !paths.has(s.to)) {
				throw new ValidationError(`Unknown target compartment '${s.to}'`, s.name);
			}
		}

		// A flux reaches both of its ends one cell at a time, or it says that
		// it does not. Where it carries a dimension an end has not got, every
		// index of that dimension lands in the one cell -- a total delivered
		// into a target, or a donor drawn down once per index -- and the model
		// runs on with a number nobody asked for. Ecolego cannot express it:
		// The desktop tool refuses a pair of ends whose dimensions do
		// not correspond, before the connection is made. This tool allows it,
		// because a flux into a block of fewer dimensions is a reduction and a
		// real thing to want, but only where the flux says so. See
		// `summedDims`.
		const holdsInventory = new Map(
			[...this.compartments, ...this.farfields, ...this.waste_packages].map((b) => [b.qname, b]),
		);
		const sizeOf = (name) => (this.indexSpace.has(name)
			? this.indexSpace.size(name) : null);
		for (const flux of [...this.transfers, ...this.inflows]) {
			if (flux.sum_extra_indices) continue;
			for (const end of ['from', 'to']) {
				const at = flux[end] == null ? null : holdsInventory.get(flux[end]);
				if (!at) continue;
				const summed = summedDims(this.index_lists, flux.index_lists, at.index_lists);
				if (!summed.length) continue;
				throw new ValidationError(summedDimsWhy({
					flux: flux.qname, end, endName: at.qname, dims: summed, sizeOf,
				}), flux.qname);
			}
		}

		// A far-field path: its cell counts have to describe a path that can
		// be built, and its release has to have somewhere to go -- or nowhere,
		// which is a path whose release is only read.
		// The same one-chain rule holds for waste packages, whose two inventories
		// decay along the model's chain exactly as a path's cells do.
		for (const p of wasteProblems(this)) throw new ValidationError(p.message, p.name);
		for (const p of disruptionProblems(this)) throw new ValidationError(p.message, p.name);
		for (const f of [...this.farfields, ...this.waste_packages]) {
			const problem = f.kind === 'farfield' ? structureProblem(f) ?? geometryProblem(f) : null;
			if (problem) throw new ValidationError(problem, f.qname);
			// A path may be indexed by whatever a compartment may be indexed
			// by. It used to be the radionuclides or nothing, on the grounds
			// that one block is one migration path -- but a path per landscape
			// object, or per climate, or per waste type, is exactly what these
			// models are made of, and writing it as twenty blocks that differ
			// only in one number is the thing an index list is for. What it
			// costs is honest and worth saying: the block's several hundred
			// states are multiplied by the width of every dimension added.
			//
			// The one dimension that cannot be doubled is the radionuclides:
			// the decay chain runs along exactly one of them, and two would be
			// two chains along one path. The general rule already refuses a
			// pair like that -- they share a root list -- so this only has to
			// refuse what that rule allows through, which is nothing at all.
			//
			// Indexed by nothing it transports one quantity with no decay and
			// no ingrowth -- a tracer, or a stable species.
			const root = this.materialListName
				? this.indexSpace.get(this.materialListName).rootName
				: null;
			const chains = f.index_lists.filter((d) => {
				const list = this.indexSpace.has(d) ? this.indexSpace.get(d) : null;
				return !!root && !!list && !list.mapping && list.rootName === root;
			});
			if (chains.length > 1) {
				throw new ValidationError(
					`${f.kind === 'farfield' ? 'A far-field path runs' : 'Waste packages run'} `
					+ `one decay chain along one dimension, and `
					+ `'${f.name}' is indexed by ${chains.length} of them `
					+ `(${chains.join(' \u00d7 ')}). A sub-set of the radionuclides is `
					+ `a second set of the same nuclides: pick the one the path `
					+ `carries.`, f.qname,
				);
			}
		}

		for (const l of this.lookups) {
			if (!INTERPOLATIONS.includes(l.interpolation)) {
				throw new ValidationError(
					`'${l.interpolation}' is not an interpolation rule `
					+ `(${INTERPOLATIONS.join(', ')})`, l.qname,
				);
			}
			if (l.argument != null && !NAME_RE.test(l.argument)) {
				throw new ValidationError(
					`'${l.argument}' is not a valid argument name`, l.qname,
				);
			}
		}

		// A function's parameters: the names its body calls the values passed
		// in. They have to be names the parser can read, and they have to
		// differ from each other.
		//
		// They may shadow a block, which is the one place in this tool where a
		// name means two things. Ecolego's argumented expressions do it --
		// `ADV(position, kd)` has a `kd` of its own in a model full of Kd
		// values -- and a rule against it would refuse real files. What this
		// tool owes in return is that every walker over a body knows the
		// parameters and leaves them alone: see `functionLocals` in ./edit.js.
		for (const f of this.functions) {
			const seen = new Set();
			for (const p of f.parameters) {
				if (!NAME_RE.test(p)) {
					throw new ValidationError(
						`'${p}' is not a valid parameter name (letters, digits and `
						+ `underscore; must not start with a digit)`, f.qname,
					);
				}
				if (RESERVED.has(p)) {
					throw new ValidationError(
						`'${p}' is a reserved name, so it cannot be a parameter`, f.qname,
					);
				}
				if (seen.has(p)) {
					throw new ValidationError(
						`'${p}' is named twice in the parameters of '${f.name}'`, f.qname,
					);
				}
				seen.add(p);
			}
		}

		for (const o of this.index_reductions) {
			if (!OPERATIONS.includes(o.operation)) {
				throw new ValidationError(
					`'${o.operation}' is not a reduction (${OPERATIONS.join(', ')})`, o.qname,
				);
			}
			if (o.operation === 'percentile'
				&& !(o.percentile >= 0 && o.percentile <= 100)) {
				throw new ValidationError(
					`A percentile must be between 0 and 100; '${o.percentile}' is not`,
					o.qname,
				);
			}
			if (!o.target) {
				throw new ValidationError(
					'An index operation needs a block to reduce', o.qname,
				);
			}
		}
		for (const m of this.min_maxes) {
			if (!EXTREMES.includes(m.operation)) {
				throw new ValidationError(
					`'${m.operation}' is not a min/max operation `
					+ `(${EXTREMES.join(', ')})`, m.qname,
				);
			}
		}
		for (const e of this.triggers) {
			if (!DIRECTIONS.includes(e.direction)) {
				throw new ValidationError(
					`'${e.direction}' is not a crossing direction `
					+ `(${DIRECTIONS.join(', ')})`, e.qname,
				);
			}
		}
		for (const a of this.block_reductions) {
			if (!AGGREGATE_OPERATIONS.includes(a.operation)) {
				throw new ValidationError(
					`'${a.operation}' is not a reduction an aggregate can do `
					+ `(${AGGREGATE_OPERATIONS.join(', ')})`, a.qname,
				);
			}
			if (!a.targets.length && !a.entries.some((e) => e.targets?.length)) {
				throw new ValidationError(
					'An aggregate needs at least one block to reduce', a.qname,
				);
			}
		}

		// Every index of the *radionuclide* list must have a half-life, since
		// decay is computed from it.
		// A stable isotope carries an infinite half-life, which buildDecayModel
		// reads as "does not decay"; only a genuinely missing one is an error.
		// The catalogue around it is not held to this: a material that is not a
		// radionuclide has no half-life because it is not one -- stable carbon
		// beside C-14, or Lotka-Volterra's rabbits -- and `lambda` reads a name
		// it has never heard of as not decaying, which is the right answer for
		// exactly these.
		const unknown = this.nuclideNames.filter((n) => this.halfLives[n] == null);
		if (unknown.length) {
			throw new ValidationError(
				`No half-life for ${unknown.join(', ')}. Set one on the Decay tab -- `
				+ `or type "stable" there for a nuclide that does not decay -- or give `
				+ `it under "half_lives" in the project file.`,
			);
		}

		// Entry index keys must name real lists and real indices.
		for (const b of all) {
			for (const entry of b.entries) {
				for (const [listName, indexName] of Object.entries(entry.index)) {
					if (!this.indexSpace.has(listName)) {
						throw new ValidationError(
							`Entry refers to unknown index list '${listName}'`, b.name,
						);
					}
					if (!b.index_lists.includes(listName)) {
						throw new ValidationError(
							`Entry is keyed by '${listName}', which '${b.name}' is not ` +
							`indexed by`, b.name,
						);
					}
					// Membership, not enabled-ness: disabling an index must leave
					// its entries dormant rather than invalid, so that
					// re-enabling it restores the data. Only enabled indices
					// produce tuples, so a dormant entry can never match.
					const known = this.indexSpace.get(listName).indices
						.some((i) => i.name === indexName);
					if (!known) {
						throw new ValidationError(
							`'${indexName}' is not an index of '${listName}'`, b.name,
						);
					}
				}
			}
		}

		const {
			start_time: startTime, end_time: endTime,
			output_points: outputPoints, spacing,
		} = this.simulation;
		if (!(endTime > startTime)) {
			throw new ValidationError('End time must be greater than start time');
		}
		if (spacing === 'log' && startTime < 0) {
			throw new ValidationError('Logarithmic output needs a non-negative start time');
		}
		// A series that contributes nothing -- a `from` past the end of the
		// run, two ends the wrong way round -- is not a model that cannot be
		// run: the combined grid still has the start and the end in it, and
		// four of the projects on this machine are written that way. So it is
		// *reported* rather than refused, by `simulationProblems` in the strip
		// and by the import report. Refusing here would mean a file Ecolego
		// opens and this tool will not.
		if (spacing !== 'series' && spacing !== 'both' && !(outputPoints >= 2)) {
			throw new ValidationError('At least 2 output points are required');
		}
		// ...and an upper bound, which nothing had. The results are one row of
		// `nstate` doubles per output point, so the grid multiplies the whole
		// model: ten million points of a thousand-state model is eighty
		// gigabytes, asked for by one number in a file. The worker dies without
		// an error anything can catch -- the page sees a silent
		// `WorkerError` -- so the number is refused here, where it can be
		// explained. A hundred thousand points is already far past what any
		// chart or table can show.
		if (outputPoints > MAX_OUTPUT_POINTS) {
			throw new ValidationError(
				`${outputPoints} output points is more than this can report `
				+ `(${MAX_OUTPUT_POINTS}). Every point is a row of every state, so the `
				+ `results would be larger than the memory available. Use the solver's `
				+ `own points, or a list of series, if you need detail somewhere `
				+ `particular.`,
			);
		}
		// Nothing checked these, and nothing downstream does either: a zero
		// relative tolerance makes the step-size factor `(0 / err) ** p` zero,
		// so every solver here halves its step forever and fails thousands of
		// steps later with a stall that names neither the setting nor the
		// value. See simulationProblems in ./edit.js, which says the same
		// thing about the field before a run is ever attempted.
		for (const [key, label] of [['rtol', 'Relative'], ['abstol', 'Absolute']]) {
			const v = Number(this.simulation[key]);
			if (!(v > 0)) {
				throw new ValidationError(
					`${label} tolerance must be greater than zero (got ${this.simulation[key]})`,
				);
			}
		}
		return this;
	}

	/**
	 * The output time grid.
	 *
	 * Three shapes, and the first two are the same one written two ways:
	 *
	 *   `log` / `linear`   one series over the whole run, from
	 *                      `output_points` -- the shorthand every file uses.
	 *                      Its arithmetic is left exactly as it was, so no
	 *                      existing model's grid moves by a single point.
	 *   `series`           a list of series in `output_times`, combined --
	 *                      Ecolego's own `TimeSeriesList`. See ./timeseries.js.
	 *   `solver`           the solver's own steps. There is no grid to build,
	 *                      so this returns the shorthand one: it is what a
	 *                      model with nothing to integrate falls back to, and
	 *                      the runner is what decides to ignore it. See
	 *                      `solverPoints`.
	 */
	timeGrid() {
		const {
			start_time: startTime, end_time: endTime,
			output_points: outputPoints, spacing,
		} = this.simulation;
		// `both` keeps its series as well as the steps; without any it falls
		// back to the shorthand, which is a grid all the same.
		if (spacing === 'series' || (spacing === 'both' && this.outputTimes.length)) {
			return combineSeries(this.outputTimes, startTime, endTime);
		}
		const n = Math.max(2, Math.round(outputPoints));
		const t = new Float64Array(n);
		if (spacing === 'log' || spacing === 'solver' || spacing === 'both') {
			const lo = startTime > 0 ? startTime : Math.max(endTime, 1) * 1e-6;
			const a = Math.log(lo), b = Math.log(endTime);
			t[0] = startTime;
			for (let i = 1; i < n; i++) t[i] = Math.exp(a + ((b - a) * i) / (n - 1));
			t[n - 1] = endTime;
		} else {
			for (let i = 0; i < n; i++) {
				t[i] = startTime + ((endTime - startTime) * i) / (n - 1);
			}
		}
		return t;
	}

	toJSON() {
		// A collection as the file holds it: the blocks that run, and the ones
		// switched off that the constructor set aside. See `_switchedOff`.
		const all = (key) => {
			const off = this._switchedOff.get(key);
			return off ? [...this[key], ...off] : this[key];
		};
		return {
			name: this.name,
			description: this.description,
			simulation: this.simulation,
			nuclides: this.nuclides,
			half_lives: this.halfLivesOverride,
			// Written whichever it is: a file that leaves it out is read as Bq,
			// so a model meaning amounts must say so to go on meaning them.
			decay_unit: this.decayUnit,
			...(this.chainsOverride ? { chains: this.chainsOverride } : {}),
			// The derived element list is left out: it follows from the nuclide
			// list, and writing it down would let the two disagree.
			index_lists: this.index_lists.filter((l) => !this._derivedLists.has(l.name)),
			...(this.scenario ? { scenario: this.scenario } : {}),
			parameters: all('parameters'),
			compartments: all('compartments'),
			expressions: all('expressions'),
			transfers: all('transfers'),
			inflows: all('inflows'),
			...(all('lookups').length ? { lookups: all('lookups') } : {}),
			...(this.index_reductions.length
				? { index_reductions: all('index_reductions') } : {}),
			...(all('block_reductions').length ? { block_reductions: all('block_reductions') } : {}),
			...(all('functions').length ? { functions: all('functions') } : {}),
			...(all('min_maxes').length ? { min_maxes: all('min_maxes') } : {}),
			...(all('running_means').length ? { running_means: all('running_means') } : {}),
			...(all('snapshots').length ? { snapshots: all('snapshots') } : {}),
			...(all('delays').length ? { delays: all('delays') } : {}),
			...(this.triggers.length
				? { triggers: all('triggers') } : {}),
			...(all('farfields').length ? { farfields: all('farfields') } : {}),
			...(all('waste_packages').length ? { waste_packages: all('waste_packages') } : {}),
			...(all('events').length ? { events: all('events') } : {}),
			...(this.transports.size ? { transports: [...this.transports] } : {}),
			...(this.disabledSystems.size ? { disabled_systems: [...this.disabledSystems] } : {}),
			// Declared sub-systems, the empty ones included: `systemPaths`
			// derives the rest from the blocks, so only an empty one would be
			// lost -- and an empty sub-system is where the next block goes.
			...(this.systems.length ? { systems: this.systems } : {}),
			layout: this.layout,
			...(this.shapes.length ? { shapes: this.shapes } : {}),
			...(this.derived.length ? { derived: this.derived } : {}),
			...(this.view ? { view: this.view } : {}),
		};
	}
}

// --- normalisation --------------------------------------------------------

/**
 * Which parts of a transport sub-system each kind of block can be. Ecolego's
 * TransportBegin and TransportEnd are compartments; TransportNumber is an
 * expression; TransportElementCounter and TransportOperation are entry blocks
 * of their own, carried here as expressions whose equation the run writes.
 */
export const TRANSPORT_ROLES = {
	compartment: ['begin', 'end'],
	expression: ['number', 'counter', 'operation'],
};

/** A transport operation, by this tool's name or Ecolego's. */
function transportOperationFromEco(op) {
	const v = String(op ?? '').trim().toLowerCase();
	if (!v) return null;
	if (v === 'sum' || v === 'mean') return v;
	// `POINT` is an operation in the format's enumeration, and the generated code treats
	// anything that is not MEAN as a sum -- the transport code generator
	// only ever tests `== Operation.MEAN`.
	if (v === 'point') return 'sum';
	return null;
}

/** A transport operation's option argument, by this tool's name or Ecolego's. */
function transportArgumentFromEco(arg) {
	const v = String(arg ?? '').trim().toLowerCase();
	if (!v) return null;
	return ['all', 'point', 'range'].includes(v) ? v : null;
}

const DEFAULTS = {
	compartment: {
		initial: '0', non_negative: true, handle_decay: true,
		color: null, unit: 'Bq',
	},
	transfer: { from: null, to: null, rate: '0', multiply_by_donor: true, unit: '1/year' },
	expression: { equation: '0', unit: '' },
	parameter: { value: 0, unit: '' },
	inflow: { to: null, rate: '0', unit: 'Bq/year' },
	lookup: { points: [], interpolation: 'linear', cyclic: false, argument: null, unit: '' },
	index_reduction: { target: null, operation: 'sum', percentile: null, unit: '' },
	block_reduction: { targets: [], operation: 'sum', unit: '' },
	// A user-defined function: a body, and the names its body calls the
	// values passed in. In a project file it is compiled code (
	// `double function(double... params)`); this tool's is an equation, for
	// the reason given in INTERNALS.md.
	function: { parameters: [], equation: '', unit: '' },
	// The blocks that remember. `target` is an equation like any other, so a
	// min/max may follow an expression rather than only a single block.
	min_max: {
		target: '0', operation: 'max',
		reset_trigger: null, start_trigger: null, stop_trigger: null, unit: '',
	},
	running_mean: {
		target: '0',
		reset_trigger: null, start_trigger: null, stop_trigger: null, unit: '',
	},
	snapshot: { target: '0', trigger: null, initial: '0', unit: '' },
	delay: { target: '0', delay: '0', unit: '' },
	trigger: { first: '0', second: '0', direction: 'rising', unit: '' },
	// A far-field path. Its own value is the release out of the far end, so
	// its unit is an inventory per unit time like a source's -- derived, since
	// it follows from what the model holds and how it counts time.
	farfield: { ...FARF_DEFAULTS, unit: '' },
	// Waste packages: the release out of them per unit time, like a path's.
	waste_package: { ...WASTE_DEFAULTS, unit: '' },
	// A disruptive event's own value is a count of occurrences: no unit.
	event: { ...DIS_DEFAULTS, unit: '' },
};

/**
 * The output series, as everything downstream can rely on reading them.
 *
 * A hand-written file may say `{ "spacing": "log", "points": "50" }` or leave
 * the ends out altogether; a series with no points and no times is not a
 * series and is dropped rather than carried as a hole in the list.
 */
function normaliseSeries(raw) {
	const out = [];
	for (const spec of Array.isArray(raw) ? raw : []) {
		if (!spec || typeof spec !== 'object') continue;
		const kind = seriesKindOf(spec);
		if (kind === 'times') {
			const times = (spec.times ?? [])
				.map((v) => Number(v))
				.filter((v) => Number.isFinite(v))
				.sort((a, b) => a - b);
			if (times.length) out.push({ kind: 'times', times });
			continue;
		}
		const points = Math.round(Number(spec.points ?? 0));
		if (!(points >= 2)) continue;
		const num = (v) => (v == null || v === '' ? null : Number(v));
		const from = num(spec.from);
		const to = num(spec.to);
		out.push({
			kind,
			points,
			// `null` is Ecolego's D_AUTO: the simulation's own start or end.
			from: Number.isFinite(from) ? from : null,
			to: Number.isFinite(to) ? to : null,
		});
	}
	return out;
}

/** Which sort a series spec is; `spacing` is accepted as a synonym of `kind`. */
function seriesKindOf(spec) {
	if (Array.isArray(spec.times)) return 'times';
	const named = String(spec.kind ?? spec.spacing ?? 'log');
	return named === 'linear' ? 'linear' : named === 'times' ? 'times' : 'log';
}

/**
 * What an index list, and an index in it, may be called.
 *
 * A list name is an identifier: it is written in a block's `index_lists` and
 * read back as a dimension, so it obeys the same rule a block name does.
 *
 * An index name cannot be an identifier -- `Cs-137`, `C-14 organic` and
 * `Object 11` are all real ones -- so what it may not contain is spelled out
 * instead. Line terminators are the ones that matter: index names reach the
 * *generated derivative* as comments, where a newline ends the comment and
 * whatever follows is compiled as JavaScript. That is arbitrary code from a
 * file somebody was sent, so it is refused here, at the gate every load comes
 * through, rather than in the editor -- which had the rule all along, and
 * which a file does not pass through.
 *
 * `<` and `>` go too: they cannot appear in a real index name and they are
 * what an injection into a label would need.
 */
const INDEX_NAME_BAD = /[\r\n\u2028\u2029<>]/;
// The same set, global, for putting a name in a message. Two constants rather
// than one, because `.test()` on a global regex carries `lastIndex` between
// calls and would then answer differently the second time it is asked.
const INDEX_NAME_BAD_ALL = /[\r\n\u2028\u2029<>]/g;

/** A name with its unusable characters shown, so a message stays one line. */
const shown = (text) => String(text).replace(INDEX_NAME_BAD_ALL, '?');

function checkIndexName(name, listName) {
	const text = String(name ?? '');
	if (!text.trim()) {
		throw new ValidationError(`An index of '${listName}' has no name`, listName);
	}
	if (INDEX_NAME_BAD.test(text)) {
		throw new ValidationError(
			`'${shown(text)}' is not a usable index name: an index may not contain a `
			+ `line break or angle brackets`, listName,
		);
	}
	return text;
}

function normaliseIndexLists(rawLists) {
	for (const l of rawLists ?? []) {
		// A derived list -- `Compartments`, `Transfers`, `Element` -- is made
		// from the model's own contents, not written in the file, so there is
		// nothing here for a modeller to have got wrong. Two indices of one
		// name in `Compartments` means two *blocks* of one name, and
		// `validate` says that in the words the reader needs; complaining
		// about the derived list first would name something nobody wrote.
		if (l?.derived) continue;
		if (!NAME_RE.test(String(l?.name ?? ''))) {
			throw new ValidationError(
				`'${shown(l?.name)}' is not a valid index list name (letters, digits `
				+ `and underscore; must not start with a digit)`, shown(l?.name),
			);
		}
		// A list's name keys every entry's index map, so the names that are
		// not really names are refused here as they are for a block. A list
		// called `__proto__` left every per-index value keyed on nothing.
		if (RESERVED.has(l.name)) {
			throw new ValidationError(`'${l.name}' is a reserved name`, l.name);
		}
		const seen = new Set();
		for (const i of l.indices ?? []) {
			const name = checkIndexName(typeof i === 'string' ? i : i?.name, l.name);
			// Two indices of one name are two states with one address. The
			// second is unreachable -- `positionOf` keeps the last -- so an
			// inventory written once was integrated twice and every total over
			// the list counted it twice, with nothing to say so.
			if (seen.has(name)) {
				throw new ValidationError(
					`'${name}' appears twice in index list '${l.name}'. Two indices of `
					+ `the same name are one address for two positions: everything `
					+ `indexed by the list would carry a slot nothing can reach.`,
					l.name,
				);
			}
			seen.add(name);
		}
	}
	// A mapping's pairs name indices on both sides, and a pair naming one
	// that is not there was skipped by the tables it feeds
	// (`_mappedUp`/`_mappedDown`), so the error surfaced later as "does not
	// cover every index" about a list the modeller had not touched.
	const indexNames = (l) => new Set((l?.indices ?? []).map((i) => (typeof i === 'string' ? i : i?.name)));
	for (const l of rawLists ?? []) {
		if (l?.derived || !l?.mapping || typeof l.mapping !== 'object') continue;
		const target = (rawLists ?? []).find((x) => x?.name === l.mapping.to);
		if (!target) continue; // IndexSpace reports the missing list itself
		const own = indexNames(l);
		const theirs = indexNames(target);
		for (const pair of l.mapping.pairs ?? []) {
			if (!own.has(pair?.from)) {
				throw new ValidationError(
					`Index list '${l.name}' maps '${shown(pair?.from)}', which is not one of `
					+ `its indices`, l.name,
				);
			}
			if (!theirs.has(pair?.to)) {
				throw new ValidationError(
					`Index list '${l.name}' maps '${pair.from}' onto '${shown(pair?.to)}', which `
					+ `is not an index of '${target.name}'`, l.name,
				);
			}
		}
	}
	return (rawLists ?? []).map((l) => ({
		name: l.name,
		for_contaminants: !!l.for_contaminants,
		...(l.for_nuclides ? { for_nuclides: true } : {}),
		...(l.for_scenarios ? { for_scenarios: true } : {}),
		...(l.for_elements ? { for_elements: true } : {}),
		...(l.sub_set_of ? { sub_set_of: l.sub_set_of } : {}),
		...(l.mapping ? { mapping: l.mapping } : {}),
		...(l.comment ? { comment: l.comment } : {}),
		// Which lists are worked out rather than written down, and what from.
		// Dropped here once, which quietly let a compartment be indexed by the
		// compartments: the rule that refuses it is keyed on `auto`.
		...(l.derived ? { derived: true } : {}),
		...(l.auto ? { auto: l.auto } : {}),
		...(l.note ? { note: l.note } : {}),
		indices: (l.indices ?? []).map((i) => (
			typeof i === 'string'
				? { name: i, enabled: true }
				// A material's own unit rides on its index of the catalogue:
				// Ecolego holds one per material -- Bq for a radionuclide,
				// kgC for stable carbon beside it -- and a compartment on
				// that dimension is labelled per index from them.
				: {
					name: i.name,
					enabled: i.enabled !== false,
					...(String(i.unit ?? '').trim() ? { unit: String(i.unit).trim() } : {}),
				}
		)),
	}));
}

/**
 * Builds the entry list for a block, folding in the two legacy shorthands:
 * a compartment's `initial: { "Cs-137": "1e10" }` map, and a parameter's
 * `values_by_nuclide`. Both are keyed by nuclide, so both become entries on the
 * material index list.
 */
function normaliseEntries(raw, kind, materialListName, dims) {
	const out = [];
	const keys = VALUE_KEYS[kind];

	for (const e of raw.entries ?? []) {
		const index = normaliseEntryIndex(e.index, materialListName, dims);
		const values = {};
		for (const k of keys) {
			if (Object.prototype.hasOwnProperty.call(e, k)) values[k] = e[k];
		}
		if (kind === 'lookup' && values.points !== undefined) {
			values.points = normalisePoints(values.points, raw.name);
		}
		if (kind === 'block_reduction' && values.targets !== undefined) {
			values.targets = normaliseTargets(values.targets, raw.name);
		}
		// A far-field setting that is not per nuclide still holds a value per
		// everything *else* the path is indexed by -- one travel time for each
		// object it runs through -- but not one per nuclide: the same water
		// takes the same time whatever is dissolved in it. An entry that says
		// otherwise is dropped rather than kept and quietly ignored, which is
		// what it would be: the slot it would be read from is not indexed by
		// the nuclides at all.
		if (values.non_negative !== undefined) {
			values.non_negative = values.non_negative !== false
				&& values.non_negative !== 'false' && values.non_negative !== 0;
		}
		if (kind === 'farfield' && materialListName
			&& index[materialListName] !== undefined) {
			for (const k of Object.keys(values)) {
				if (!FARF_NUCLIDE_KEYS.includes(k)) delete values[k];
			}
		}
		if (kind === 'waste_package' && materialListName
			&& index[materialListName] !== undefined) {
			for (const k of Object.keys(values)) {
				if (!WASTE_NUCLIDE_KEYS.includes(k)) delete values[k];
			}
		}
		out.push({ index, ...values });
	}

	// initial: { "<nuclide>": value }
	if (kind === 'compartment' && raw.initial && typeof raw.initial === 'object'
		&& !Array.isArray(raw.initial) && materialListName) {
		for (const [nuc, v] of Object.entries(raw.initial)) {
			out.push({ index: { [materialListName]: nuc }, initial: String(v) });
		}
	}

	// values_by_nuclide: { "<nuclide>": number }
	if (kind === 'parameter' && raw.values_by_nuclide && materialListName) {
		for (const [nuc, v] of Object.entries(raw.values_by_nuclide)) {
			out.push({ index: { [materialListName]: nuc }, value: Number(v) });
		}
	}

	return out;
}

/**
 * A lookup table's points, as [[x, y], ...] or [[x, y, pdf], ...] with numbers.
 *
 * **A point may carry its own distribution**, as a third element. A table is a
 * curve, not a number, and a data set that knows how uncertain a release
 * fraction is knows it at the years it was measured -- so the spread belongs
 * where the number is. It is passed through rather than read here; the builder
 * gives each one a slot and ../domain/sample.js draws it.
 *
 * The pair form is what the project file writes. The parallel form -- [xs, ys]
 * -- is what the .eco file stores and what a hand-written file is likely to
 * copy from it, so it is accepted here rather than only in the importer. The
 * points are left in the order given; ../domain/lookup.js sorts them, which is
 * the one place that has to know they are sorted.
 */
function normalisePoints(points, blockName) {
	if (points == null) return [];
	if (!Array.isArray(points)) {
		throw new ValidationError('Lookup points must be a list of [x, y] pairs', blockName);
	}
	let pairs = points;
	// [xs, ys]: two equally long lists of numbers. Ambiguous only against a
	// two-point table, which is why a pair of *numbers* is never read this way.
	if (points.length === 2 && Array.isArray(points[0]) && Array.isArray(points[1])
		&& points[0].length === points[1].length
		&& points[0].every((v) => typeof v === 'number' || typeof v === 'string')
		&& points[0].length !== 2) {
		pairs = points[0].map((x, i) => [x, points[1][i]]);
	}
	return pairs.map((pt, i) => {
		const [x, y, pdf] = Array.isArray(pt) ? pt : [pt?.x, pt?.y, pt?.pdf];
		const nx = Number(x);
		const ny = Number(y);
		if (!Number.isFinite(nx) || !Number.isFinite(ny)) {
			throw new ValidationError(
				`Lookup point ${i + 1} is (${x}, ${y}); both parts must be numbers`,
				blockName,
			);
		}
		// Kept only where there is one, so an ordinary table is still pairs
		// and a file written from one is unchanged.
		return pdf ? [nx, ny, pdf] : [nx, ny];
	});
}

/**
 * An aggregate's targets: the block names it reduces over.
 *
 * The .eco file joins them with `+` in one string, which is also how a
 * hand-written file is likely to copy them, so both that and a list are
 * accepted here rather than only in the importer.
 */
function normaliseTargets(targets, blockName) {
	if (targets == null) return [];
	const list = typeof targets === 'string'
		? targets.split('+')
		: Array.isArray(targets) ? targets : null;
	if (!list) {
		throw new ValidationError(
			'Aggregate targets must be a list of block names', blockName,
		);
	}
	return list.map((t) => String(t).trim()).filter((t) => t !== '');
}

/**
 * An entry index may be written as an object keyed by list name, or -- when
 * the block has exactly one dimension -- as a bare index name.
 */
function normaliseEntryIndex(index, materialListName, dims) {
	if (index == null) return {};
	if (typeof index === 'string') {
		const list = dims.length === 1 ? dims[0] : materialListName;
		if (!list) {
			throw new ValidationError(
				`Entry index '${index}' is ambiguous: name the index list explicitly, ` +
				`as { "ListName": "${index}" }`,
			);
		}
		return { [list]: index };
	}
	if (Array.isArray(index)) {
		// Positional form: one index per dimension, in declared order.
		if (index.length !== dims.length) {
			throw new ValidationError(
				`Entry index has ${index.length} component(s) but the block has ` +
				`${dims.length} dimension(s)`,
			);
		}
		const obj = {};
		index.forEach((v, i) => { if (v != null) obj[dims[i]] = v; });
		return obj;
	}
	// Anything else is not an index. `{ ...7 }` is `{}`, which reads as "no
	// index at all" -- so a malformed per-index value silently became the
	// block's default and overrode every index instead of one.
	if (typeof index !== 'object') {
		throw new ValidationError(
			`Entry index '${index}' is not an index: write it as a name, a list of `
			+ 'names, or an object keyed by index list.',
		);
	}
	return { ...index };
}

/**
 * The value of `key` for a block at one index tuple.
 *
 * Entries are matched on the components they specify; the entry naming the
 * most components wins, so a value set for (Cs-137, Lake) beats one set for
 * Cs-137 alone, which beats the block-level default. This is this tool of
 * the value store's lookup with its fall-back to the empty index key.
 */
/**
 * Whether a compartment carries an explicit dy/dt term anywhere -- at the
 * block level or for any one index. What decides whether the engine gives it
 * a slot, and whether the panels have anything to show for it.
 */
export function hasDydt(block) {
	const set = (v) => typeof v === 'string' && v.trim() !== '';
	return set(block?.dydt) || (block?.entries ?? []).some((e) => set(e?.dydt));
}

export function valueAt(block, key, tupleByList) {
	let best;
	let bestScore = -1;
	for (const entry of block.entries) {
		if (!Object.prototype.hasOwnProperty.call(entry, key)) continue;
		let score = 0;
		let ok = true;
		for (const [listName, indexName] of Object.entries(entry.index)) {
			if (tupleByList[listName] !== indexName) { ok = false; break; }
			score++;
		}
		if (ok && score > bestScore) { bestScore = score; best = entry[key]; }
	}
	if (bestScore >= 0) return best;
	return block[key];
}

export { NUCLIDE_LIST };
