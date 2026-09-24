/**
 * Solving a model in its independent parts, at the same time.
 *
 * ./partition.js finds the parts of a model that cannot reach each other --
 * on an assessment, one per decay chain -- and INTERNALS.md (*Solving a large
 * model in sections*) measured what solving them one after another would buy:
 * nothing, because the algebra a derivative call runs does not shrink with the
 * part, so the parts together cost more arithmetic than the whole. That was
 * the right answer to the question it asked, which was about one core. On
 * several, what a run costs is the time until its *slowest* part is in, not
 * the sum of the parts: model A's largest chain is 18.5% of its states and
 * about 28% of a derivative call, so with a core per part the run waits for
 * roughly a quarter of the whole model's work, plus a build per part.
 *
 * This file decides whether that pays for the model in hand, and how. The
 * coordinator (../worker/sim-worker.js) builds the whole model -- it has to:
 * the parts are read off its Jacobian, and its system is what every series is
 * worked out from afterwards -- and hands each worker a *job*: the model with
 * every material switched off but the job's own, which builds into a system
 * whose derivative matches the whole model's on those states exactly (checked
 * in INTERNALS.md on a ten-nuclide chain of 4,230 states). The workers solve
 * on the model's output grid, each at its own steps, and the coordinator
 * files every state into the whole model's vector by name. What comes out is
 * an ordinary run of the whole model -- every series, the table, the exports,
 * the mass balance -- whose states were integrated in pieces.
 *
 * **Not bit for bit the whole model's.** Each part takes the steps its own
 * states need rather than the steps the stiffest state anywhere needs, which
 * is the point, and so agrees with the whole to within the tolerance rather
 * than to the last digit. The setting is therefore part of the model's
 * fingerprint, and a run says in the status line and the log when it was
 * split.
 *
 * **Refused, whatever the setting, where it would be wrong or cannot work:**
 * a model the partition declines (a delay, a snapshot or an event reaches
 * across parts without showing in the Jacobian); output at the solver's own
 * steps, which differ in every part; a SciPy solver, which each worker would
 * download a Python runtime for; a model with no materials to divide by; one
 * part holding everything; a browser that will not start a worker from a
 * worker; and one core.
 */

import { partitionOf } from './partition.js';
import { UNINDEXED } from '../domain/massbalance.js';

/** The setting, as the Simulation section offers it. */
export const SPLIT_MODES = [
	['auto', 'auto', 'Split the model into its independent parts when that is expected to '
		+ 'be clearly faster on this machine: a large model that falls apart into several '
		+ 'decay chains of comparable size, with the cores to run them side by side.'],
	['on', 'always', 'Split whenever the model can be split: every part that cannot reach '
		+ 'another is solved in a worker of its own, at its own steps.'],
	['off', 'never', 'Solve the whole model as one system, as it always was.'],
];

/**
 * The share of a derivative call that every part pays whatever its size: the
 * algebra that is not per material. Measured on model A (INTERNALS.md): its
 * largest part, 18.5% of the states, cost 28% of a whole call, which is
 * `0.12 + 0.88 x 0.185`.
 */
export const SHARED_WORK = 0.12;

/** Auto splits a model it has not timed only from this many states up. */
export const AUTO_STATES = 2000;

/** Auto splits a model it has timed only when a whole solve took this long. */
export const AUTO_SOLVE_MS = 1500;

/**
 * How much faster auto wants the split to be expected, or measured, to be.
 * Modest because the expectation is modest: it assumes the largest part needs
 * every step the whole model takes, where a part usually needs markedly fewer
 * -- it answers to its own states, not to the stiffest one anywhere -- so a
 * split runs faster than this predicts, not slower.
 */
export const AUTO_GAIN = 1.2;

/**
 * The same, for a model whose solve time is not known yet: a larger margin,
 * because the estimate is then of the shape of the model alone.
 */
export const AUTO_GAIN_UNTIMED = 1.6;

/** What starting a worker and loading the engine into it costs, per worker. */
export const START_MS = 250;

/**
 * A name for each state that is the same for the same state in any build of
 * the model, whichever materials that build has: the block, its index, and for
 * a far-field path the cell. The mass-balance budgets are named by the term and
 * the family they count, since their positions depend on how many families the
 * build has.
 *
 * @returns {string[]|null} null when two states come out with one name, which
 *   would make filing them back by name unsafe
 */
export function stateKeys(layout) {
	const keys = new Array(layout.nstate);
	const space = layout.indexSpace;
	for (const entry of layout.states ?? []) {
		if (entry.kind === 'farfield' && entry.farf) {
			const { nnuc, otherDims, otherWidth, ncells, listName } = entry.farf;
			const names = listName ? space.indexNames(listName) : [null];
			for (let o = 0; o < otherWidth; o++) {
				const others = otherDims.length ? space.tupleAt(otherDims, o) : [];
				const base = entry.base + o * ncells * nnuc;
				for (let m = 0; m < nnuc; m++) {
					const index = [];
					let k = 0;
					for (const dim of entry.dims) index.push(dim === listName ? names[m] : others[k++]);
					for (let cell = 0; cell < ncells; cell++) {
						keys[base + cell * nnuc + m] = `${entry.kind}:${entry.name}[${index.join(',')}]#${cell}`;
					}
				}
			}
			continue;
		}
		if (entry.kind === 'budget' && entry.budget) {
			const { nfam, families, terms } = entry.budget;
			terms.forEach((term, t) => {
				for (let f = 0; f < nfam; f++) keys[entry.base + t * nfam + f] = `budget:${term}:${families[f]}`;
			});
			continue;
		}
		const dims = entry.dims ?? [];
		for (let off = 0; off < entry.width; off++) {
			const index = dims.length ? space.tupleAt(dims, off) : [];
			keys[entry.base + off] = `${entry.kind}:${entry.name}[${index.join(',')}]`;
		}
	}
	const seen = new Set();
	for (let i = 0; i < keys.length; i++) {
		if (keys[i] == null || seen.has(keys[i])) return null;
		seen.add(keys[i]);
	}
	return keys;
}

/**
 * The material each state belongs to, or null for one that is not per
 * material -- a compartment of water, say, or the budget of the compartments
 * that are not indexed by one.
 */
export function stateMaterials(layout) {
	const out = new Array(layout.nstate).fill(null);
	const space = layout.indexSpace;
	const materialList = layout.materialList ? space.get(layout.materialList) : null;
	const root = materialList ? materialList.rootName : null;
	// The dimension of a block that is its material, as ./runner.js reads it:
	// a list whose root is the material catalogue and that is not a mapping
	// onto it.
	const materialDimOf = (dims) => (root ? dims.findIndex((d) => {
		if (!space.has(d)) return false;
		const l = space.get(d);
		return !l.mapping && l.rootName === root;
	}) : -1);
	for (const entry of layout.states ?? []) {
		if (entry.kind === 'farfield' && entry.farf) {
			const { nnuc, otherWidth, ncells, listName } = entry.farf;
			if (!listName) continue;
			const names = space.indexNames(listName);
			for (let o = 0; o < otherWidth; o++) {
				const base = entry.base + o * ncells * nnuc;
				for (let m = 0; m < nnuc; m++) {
					for (let cell = 0; cell < ncells; cell++) out[base + cell * nnuc + m] = names[m];
				}
			}
			continue;
		}
		if (entry.kind === 'budget' && entry.budget) {
			const { nfam, families, terms } = entry.budget;
			for (let t = 0; t < terms.length; t++) {
				for (let f = 0; f < nfam; f++) {
					out[entry.base + t * nfam + f] = families[f] === UNINDEXED ? null : families[f];
				}
			}
			continue;
		}
		const dims = entry.dims ?? [];
		const md = materialDimOf(dims);
		if (md < 0) continue;
		for (let off = 0; off < entry.width; off++) out[entry.base + off] = space.tupleAt(dims, off)[md];
	}
	return out;
}

/**
 * The jobs a model's parts make: sets of materials, each with the states it
 * owns.
 *
 * A job is built by switching every other material off, so parts that share a
 * material cannot be in different jobs and are merged. A part with no
 * material at all -- a water balance that nothing radioactive reads -- is in
 * every job's build, since switching materials off does not remove it, and is
 * taken from whichever job is smallest. Its values are the same in all of
 * them: nothing in it depends on the materials that are off.
 *
 * @returns {{ok: true, jobs: Array<{materials: string[], states: number}>,
 *   owner: Int32Array, keys: string[], parts: number}|{ok: false, why: string}}
 */
export function splitJobs(system) {
	const part = partitionOf(system);
	if (!part.ok) return { ok: false, why: part.refusal };
	const layout = system.layout;
	if (!layout.materialList) return { ok: false, why: 'the model has no materials to divide it by' };
	if (part.count < 2) return { ok: false, why: 'the model is one part: every state can reach every other' };
	const keys = stateKeys(layout);
	if (!keys) return { ok: false, why: 'two states of the model share a name, so a part could not be filed back by it' };
	const materials = stateMaterials(layout);

	// Parts that share a material are one job.
	const parent = Int32Array.from({ length: part.count }, (_, i) => i);
	const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
	const firstPart = new Map();
	for (let i = 0; i < layout.nstate; i++) {
		const m = materials[i];
		if (m == null) continue;
		const p = part.of[i];
		const was = firstPart.get(m);
		if (was === undefined) firstPart.set(m, p);
		else if (find(was) !== find(p)) parent[find(p)] = find(was);
	}
	// The groups with a material, numbered in the order they first appear.
	const jobOf = new Int32Array(part.count).fill(-1);
	const jobs = [];
	const carries = new Uint8Array(part.count);
	for (let i = 0; i < layout.nstate; i++) if (materials[i] != null) carries[part.of[i]] = 1;
	for (let p = 0; p < part.count; p++) {
		if (!carries[p]) continue;
		const r = find(p);
		if (jobOf[r] < 0) { jobOf[r] = jobs.length; jobs.push({ materials: new Set(), states: 0 }); }
		jobOf[p] = jobOf[r];
	}
	if (jobs.length < 2) {
		return { ok: false, why: 'every part shares a material with another, so the model builds as one job' };
	}
	const owner = new Int32Array(layout.nstate);
	for (let i = 0; i < layout.nstate; i++) {
		const j = jobOf[find(part.of[i])];
		owner[i] = j;
		if (j >= 0) {
			jobs[j].states++;
			if (materials[i] != null) jobs[j].materials.add(materials[i]);
		}
	}
	// The parts with no material go to the smallest job, which every build
	// holds them anyway.
	const smallest = jobs.reduce((k, j, i) => (j.states < jobs[k].states ? i : k), 0);
	for (let i = 0; i < layout.nstate; i++) {
		if (owner[i] < 0) { owner[i] = smallest; jobs[smallest].states++; }
	}
	// A material the model has but no state carries -- a nuclide nothing is
	// indexed by -- rides with the smallest job, so that every material is
	// switched on somewhere and the builds see what the whole model sees.
	const placed = new Set(jobs.flatMap((j) => [...j.materials]));
	for (const m of layout.indexSpace.indexNames(layout.materialList)) {
		if (!placed.has(m)) jobs[smallest].materials.add(m);
	}
	return {
		ok: true,
		jobs: jobs.map((j) => ({ materials: [...j.materials], states: j.states })),
		owner, keys, parts: part.count,
	};
}

/** A job's share of a whole derivative call, from its share of the states. */
export function jobCost(states, total) {
	return SHARED_WORK + (1 - SHARED_WORK) * (total > 0 ? states / total : 1);
}

/**
 * Jobs into `workers` bins, largest first into the least loaded: the classic
 * longest-processing-time rule, which is within a third of the best packing
 * and exact when there are no more jobs than workers.
 *
 * @param {number[]} costs
 * @returns {number[][]} the jobs of each bin, by index
 */
export function packJobs(costs, workers) {
	const n = Math.max(1, Math.min(workers, costs.length));
	const bins = Array.from({ length: n }, () => ({ load: 0, jobs: [] }));
	const order = costs.map((c, i) => i).sort((a, b) => costs[b] - costs[a] || a - b);
	for (const j of order) {
		let k = 0;
		for (let b = 1; b < n; b++) if (bins[b].load < bins[k].load) k = b;
		bins[k].load += costs[j];
		bins[k].jobs.push(j);
	}
	return bins.map((b) => b.jobs.sort((x, y) => x - y));
}

/**
 * Whether to split this run, and how.
 *
 * The prediction is the cost model above: each job costs its share of the
 * whole model's build and of its solve, the bins run side by side, and each
 * worker costs a start. The whole model's solve time comes from `known` -- a
 * previous run of this same layout on this worker -- and where there is none
 * the ratio is judged on the model's shape alone, with a larger margin and
 * only for a large model. The shape is the part that is certain; the step
 * counts are not, since a part may need fewer steps than the whole and never
 * more than the whole's worst part, which is what this assumes.
 *
 * @param {object} system  the whole model, built
 * @param {object} project the `Project`
 * @param {object} opts
 * @param {'auto'|'on'|'off'} [opts.mode]
 * @param {number} opts.workers  cores this run may use for parts
 * @param {boolean} opts.nest    whether a worker can be started from here
 * @param {boolean} [opts.scipy] the solver is one of the SciPy ones
 * @param {number} [opts.buildMs]  what building the whole model just took
 * @param {{solveMs: number, gain?: number}|null} [opts.known]  the whole
 *   model's solve time from an earlier run, and -- when that run was split --
 *   what the split was measured to gain
 * @returns {{use: boolean, mode: string, why: string, jobs?: Array, owner?: Int32Array,
 *   keys?: string[], bins?: number[][], parts?: number, predicted?: number|null}}
 */
export function planSplit(system, project, {
	mode = 'auto', workers = 1, nest = true, scipy = false, buildMs = 0, known = null,
} = {}) {
	const m = mode === 'on' || mode === 'off' ? mode : 'auto';
	const no = (why) => ({ use: false, mode: m, why });
	if (m === 'off') return no('switched off');
	if (!system?.layout?.nstate) return no('the model has nothing to integrate');
	if (project?.outputMode && project.outputMode !== 'grid') {
		return no('the results are reported at the solver’s own steps, which would be different in every part');
	}
	if (scipy) return no('the SciPy solvers run in a Python runtime every part would have to download');
	if (!nest) return no('this browser cannot start a worker from a worker');
	const found = splitJobs(system);
	if (!found.ok) return no(found.why);
	const n = system.layout.nstate;
	const costs = found.jobs.map((j) => jobCost(j.states, n));
	const cores = Math.max(1, Math.floor(workers));
	if (cores < 2) return no('there is one core to run on');
	const bins = packJobs(costs, cores);
	const load = Math.max(...bins.map((b) => b.reduce((s, j) => s + costs[j], 0)));
	const plan = {
		use: true, mode: m, jobs: found.jobs, owner: found.owner, keys: found.keys, bins,
		parts: found.parts, predicted: null,
		why: '',
	};
	const size = `${found.jobs.length} parts, the largest ${Math.round(100 * Math.max(...found.jobs.map((j) => j.states)) / n)}% of the states`;
	if (m === 'on') {
		plan.why = `asked for: ${size}, on ${bins.length} cores`;
		return plan;
	}
	// Auto. A split this model has had, measured, decides: it is the answer
	// the prediction is an estimate of.
	if (known?.gain != null) {
		if (known.gain < AUTO_GAIN) {
			return no(`split, it was measured at ${known.gain.toFixed(1)}×, which is not enough to be worth it`);
		}
		plan.predicted = known.gain;
		plan.why = `${size}; measured at ${known.gain.toFixed(1)}× the last time, on ${bins.length} cores`;
		return plan;
	}
	if (known?.solveMs != null && Number.isFinite(known.solveMs)) {
		const S = known.solveMs;
		const B = Math.max(0, buildMs);
		const predicted = S / (load * (B + S) + START_MS);
		if (S < AUTO_SOLVE_MS) {
			return { ...no(`a whole solve takes ${Math.round(S)} ms, too short to be worth dividing`), predicted };
		}
		if (predicted < AUTO_GAIN) {
			return { ...no(`${size}; expected ${predicted.toFixed(1)}× on ${bins.length} cores, not enough`), predicted };
		}
		plan.predicted = predicted;
		plan.why = `${size}; expected ${predicted.toFixed(1)}× faster on ${bins.length} cores`;
		return plan;
	}
	const shape = 1 / load;
	if (n < AUTO_STATES) {
		return { ...no(`${n.toLocaleString('en')} states, too few to be worth dividing before a run has been timed`), predicted: shape };
	}
	if (shape < AUTO_GAIN_UNTIMED) {
		return { ...no(`${size}; at most ${shape.toFixed(1)}× on ${bins.length} cores, not enough`), predicted: shape };
	}
	plan.predicted = shape;
	plan.why = `${size}; up to ${shape.toFixed(1)}× faster on ${bins.length} cores`;
	return plan;
}

/**
 * The model as one job builds it: every material switched off but its own.
 *
 * Switched off rather than removed, which is what the Index lists tab does and
 * what the builder already honours: an index that is off takes no part in the
 * run, every block indexed by its list is that much narrower, and the entries
 * that name it lie dormant. A sub-set of the catalogue follows it on its own.
 *
 * @param {object} json   the model, as `Project.toJSON` writes it
 * @param {Iterable<string>} keep  the job's materials
 * @param {{copy?: boolean}} [opts]  `copy: false` switches them off in `json`
 *   itself, for a worker that parsed its own copy of the model and has no use
 *   for a second
 */
export function partModel(json, keep, { copy: cloned = true } = {}) {
	const copy = cloned ? structuredClone(json) : json;
	const want = new Set(keep);
	for (const list of copy.index_lists ?? []) {
		if (!(list.for_contaminants || list.for_nuclides)) continue;
		list.indices = (list.indices ?? []).map((i) => {
			const idx = typeof i === 'string' ? { name: i, enabled: true } : { ...i };
			if (!want.has(idx.name)) idx.enabled = false;
			return idx;
		});
	}
	if (Array.isArray(copy.nuclides)) copy.nuclides = copy.nuclides.filter((n) => want.has(n));
	return copy;
}

/**
 * Where a job's states go in the whole model's vector: the pairs (index in the
 * job's build, index in the whole) for the states the job owns.
 *
 * @param {Map<string, number>} whole  the whole model's state keys, to index
 * @param {string[]} keys   the job's build's state keys
 * @param {Int32Array} owner  which job owns each of the whole model's states
 * @param {number} job
 * @returns {{from: Int32Array, to: Int32Array}}
 */
export function placeStates(whole, keys, owner, job) {
	const from = [];
	const to = [];
	for (let k = 0; k < keys.length; k++) {
		const i = whole.get(keys[k]);
		if (i === undefined || owner[i] !== job) continue;
		from.push(k);
		to.push(i);
	}
	return { from: Int32Array.from(from), to: Int32Array.from(to) };
}

/**
 * The parts, back into one run of the whole model.
 *
 * `outcomes[j]` is job `j`'s run: its times `t`, its states `y` flattened row
 * by row (`np` to a row), their names `keys`, the solver's `stats` and its
 * per-state held-at-zero tally `held`. Every state of the whole model is filed
 * from the job that owns it, by name.
 *
 * One time axis for the whole run, every part's and the same: a part that
 * took a corner the others did not -- a switch time only its blocks carry --
 * would leave a row the others have no state for. That, and a state no part
 * carried, throw; the caller solves the whole model instead.
 *
 * The counts are summed, since the parts' steps are all work the run did. The
 * held-at-zero tally is kept as a share of the state's *own* part's steps --
 * the footer divides it by the run's steps, and a state held in every step of
 * a short part is held throughout, not for a sliver of the sum.
 *
 * @param {{keys: string[], owner: Int32Array}} plan
 * @param {Array<{t: ArrayLike<number>, y: Float64Array, np: number, keys: string[],
 *   stats?: object, held?: ArrayLike<number>|null}>} outcomes
 * @returns {{t: Float64Array, rows: Float64Array[], stats: object}}
 */
export function assembleParts({ keys, owner }, outcomes) {
	const n = keys.length;
	const whole = new Map(keys.map((k, i) => [k, i]));
	const t = Float64Array.from(outcomes[0].t);
	for (const o of outcomes) {
		if (o.t.length !== t.length || Array.prototype.some.call(o.t, (v, i) => v !== t[i])) {
			throw new Error('the parts came back on different output times');
		}
	}
	const rows = Array.from({ length: t.length }, () => new Float64Array(n));
	const filled = new Uint8Array(n);
	const share = new Float64Array(n);
	let heldAny = false;
	const stats = { nsteps: 0, nfailed: 0, nfevals: 0 };
	outcomes.forEach((o, j) => {
		const { from, to } = placeStates(whole, o.keys, owner, j);
		for (let i = 0; i < t.length; i++) {
			const row = rows[i];
			const at = i * o.np;
			for (let k = 0; k < from.length; k++) row[to[k]] = o.y[at + from[k]];
		}
		for (let k = 0; k < to.length; k++) filled[to[k]] = 1;
		for (const key of ['nsteps', 'nfailed', 'nfevals', 'npds', 'ndecomps', 'restarts', 'breaks',
			'events', 'jumps', 'nbelowtol', 'negative']) {
			if (Number.isFinite(o.stats?.[key])) stats[key] = (stats[key] ?? 0) + o.stats[key];
		}
		if (!stats.solver && o.stats?.solver) stats.solver = o.stats.solver;
		if (o.stats?.sparse !== undefined) stats.sparse = o.stats.sparse;
		if (o.held) {
			const steps = Math.max(1, o.stats?.nsteps ?? 1);
			for (let k = 0; k < from.length; k++) {
				const v = o.held[from[k]];
				if (v) { share[to[k]] = v / steps; heldAny = true; }
			}
		}
	});
	for (let i = 0; i < n; i++) {
		if (!filled[i]) throw new Error(`no part carried the state '${keys[i]}'`);
	}
	if (heldAny) {
		const held = new Int32Array(n);
		for (let i = 0; i < n; i++) held[i] = Math.round(share[i] * stats.nsteps);
		stats.held = held;
	}
	return { t, rows, stats };
}

/**
 * A job's model, built -- switching back on any material its equations name
 * outright.
 *
 * An equation may pin one material by name: `k[C-14]`, a coefficient read at
 * carbon-14 for every nuclide. The builder refuses a
 * pin to an index that is off, and a job has every material but its own off.
 * The pin is safe to honour: what it reads cannot depend on a state, since a
 * state read that way would have put the two jobs' states in one part. So the
 * material is switched on in this job's build -- its states come along, are
 * integrated for nothing, and are not the ones kept, which come from the job
 * that owns them -- and the build is tried again.
 *
 * @param {object} json  the job's model, from `partModel`
 * @param {{Project: Function, buildSystem: Function}} engine  passed in so this
 *   module stays free of the builder
 * @returns {{project: object, system: object, pinned: string[]}}
 */
export function buildPart(json, { Project, buildSystem }) {
	let model = json;
	const pinned = [];
	for (;;) {
		try {
			const project = new Project(model);
			return { project, system: buildSystem(project), pinned };
		} catch (e) {
			const m = /'([^']+)' is disabled in '([^']+)'/.exec(e?.message ?? '');
			if (!m || pinned.includes(m[1]) || !isMaterialIndex(model, m[1])) throw e;
			pinned.push(m[1]);
			model = switchOn(model, m[1]);
		}
	}
}

/** Whether `name` is an index of the model's material lists, on or off. */
function isMaterialIndex(json, name) {
	return (json.index_lists ?? []).some((l) => (l.for_contaminants || l.for_nuclides)
		&& (l.indices ?? []).some((i) => (typeof i === 'string' ? i : i?.name) === name));
}

/** The model with material `name` switched back on. */
function switchOn(json, name) {
	const copy = structuredClone(json);
	for (const list of copy.index_lists ?? []) {
		if (!(list.for_contaminants || list.for_nuclides)) continue;
		for (const i of list.indices ?? []) if (i && typeof i === 'object' && i.name === name) i.enabled = true;
	}
	if (Array.isArray(copy.nuclides) && !copy.nuclides.includes(name)) {
		// In the catalogue's order, which is the order the shorthand keeps.
		const order = (copy.index_lists ?? []).find((l) => l.for_contaminants)?.indices ?? [];
		const on = new Set([...copy.nuclides, name]);
		copy.nuclides = order.map((i) => (typeof i === 'string' ? i : i.name)).filter((n) => on.has(n));
	}
	return copy;
}
