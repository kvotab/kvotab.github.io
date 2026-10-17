/**
 * How the answer moves when one parameter moves.
 *
 * The other sensitivity -- ../domain/sensitivity.js -- asks which inputs a
 * spread came from, over a sample. This one asks a sharper and narrower
 * question: at the values the model actually holds, what is `dy/dp`? It is a
 * derivative rather than a correlation, it needs no distributions, and it is
 * exact rather than sampled.
 *
 * **The forward sensitivity equations.** Differentiate `y' = f(t, y, p)` with
 * respect to a parameter and the sensitivity `S = dy/dp` satisfies
 *
 *     S' = J·S + df/dp,      S(0) = dy0/dp
 *
 * -- a linear system driven by `df/dp`, integrated alongside the states. So the
 * augmented vector is `[y, S_1, ..., S_m]` and one solve gives the states and
 * every sensitivity at once, each to the solver's own tolerance rather than to
 * whatever a difference of two whole runs would leave.
 *
 * **`J·S` is one tangent call, not a Jacobian.** The generated tangent computes
 * `J·v` for any direction in a single pass -- forming the whole matrix is only
 * that same call repeated once per colour group. Using the product directly is
 * the difference between 3 ms and 158 ms per step on model A,
 * which is what makes this affordable at all. `jacobian.jvp` exists for this.
 *
 * **`df/dp` is differentiated where the model allows it** (`paramTangent`,
 * built by ./jacobian.js), and differenced otherwise: one forward step per
 * parameter per call, which is right to about eight figures. It is also why
 * this is offered for a handful of chosen parameters rather than for all 617
 * of an assessment's. A solve that gives up with a difference in it says so
 * (`differencedFailure`): what a difference loses to rounding can be more
 * than the absolute tolerance dy/dp is held to.
 *
 * **The iteration matrix ignores the second derivatives.** The true Jacobian of
 * the augmented system has `d(J·S)/dy` terms in the sensitivity blocks, which
 * are second derivatives of `f`. Left out, exactly as CVODES leaves them out:
 * they affect how fast Newton converges and not what it converges *to*, so the
 * answer is the same and the matrix is the original `J` repeated down the
 * diagonal. It is also why the solve is the NDF whatever solver the model
 * names: a Rosenbrock method uses the Jacobian inside its formula and needs the
 * whole of it, where a Newton iteration only needs one good enough to converge.
 *
 * **It is a run of the model.** The augmented system is integrated by the
 * runner's own machinery (`equations` in ./runner.js): restarted at every
 * switch time, through the discrete events, with the blocks that remember
 * primed and fed, the model's solver settings, its floor on each compartment
 * as the compartment sets it, the clock interpolation, and progress and Stop.
 * It used to call the solver directly, with none of that -- so a model with a
 * switch time, a compartment allowed below zero or a step limit gave states
 * that were not the run's, and the dialog could be neither followed nor
 * stopped.
 *
 * **What the forward equations cannot carry is refused, by name** -- rather
 * than answered wrongly. A jump in the state (waste packages failing all at
 * once, a disruptive event at a time); a block that remembers the path of the
 * run (a min/max, a snapshot, a delay, or a running mean a discrete event
 * switches) where the derivative reads it; and a parameter that places a
 * corner of the run -- a switch time, a failure window -- since moving a corner
 * moves a discontinuity. Each of those puts a term into `dy/dp` that is not in
 * `J·S + df/dp`. See `uncarried`.
 */

import { Project, valueAt } from '../domain/project.js';
import { buildSystem, tupleByList } from './builder.js';
import { effectiveValue } from '../domain/edit.js';
import { switchTimes } from '../domain/switchtimes.js';
import { EVENT_FIELDS } from '../domain/recorders.js';
import {
	absoluteTolerance, describeEntry, jumpsOf, run,
} from './runner.js';
import { SolverError } from '../ode/one-step.js';
import { iterationMatrix } from '../ode/core/sparse.js';

/** A step that is small against the value and large against its rounding. */
const EPS = Math.sqrt(Number.EPSILON);
const stepFor = (p) => EPS * Math.max(Math.abs(p), 1);

/**
 * Every parameter slot a model has, by name and index.
 *
 * The same walk `distributedSlots` does, without the distribution: a
 * sensitivity is about a parameter the model holds, whether or not anybody has
 * said how uncertain it is. `unit` is the slot's as the chart labels its series
 * (`describeEntry` in ./runner.js): the block's own, or at an index of the
 * materials the material's.
 *
 * @returns {Array<{slot: number, name: string, index: object, value: number, unit: string}>}
 */
export function parameterSlots(system) {
	const out = [];
	for (const entry of system.layout.parameters ?? []) {
		const { block, dims, base, width } = entry;
		const described = describeEntry(system.layout, entry, 'parameter', 'P');
		for (let off = 0; off < width; off++) {
			const tuple = dims.length ? tupleByList(system.layout.indexSpace, dims, off) : {};
			out.push({
				slot: base + off,
				name: entry.name,
				index: tuple,
				value: Number(effectiveValue(block, 'value', tuple)),
				unit: described[off]?.unit ?? '',
			});
		}
	}
	return out;
}

/** `name` or `name[i][j]`, which is how a parameter is asked for. */
export function slotLabel(e) {
	const idx = Object.values(e.index ?? {});
	return idx.length ? `${e.name}[${idx.join('][')}]` : e.name;
}

/**
 * A name for every state the solve carries, as the chart names the same series.
 *
 * One entry per state, in the order of the state vector: `offset` is the state's
 * row in `y` and in each block of `sens`. A compartment, a waste package's two
 * inventories and a disruptive event's count are labelled exactly as a run
 * labels them (`describeEntry`); the rest is machinery -- a far-field path's
 * cells, a running mean's integral, the mass-balance budget, the inside of a
 * transport chain -- and is `hidden`, with a name only so that it can be told
 * apart.
 *
 * @returns {Array<{offset: number, label: string, block: string, kind: string, unit: string, hidden: boolean}>}
 */
export function stateSeries(system) {
	const { layout } = system;
	const out = [];
	for (const s of layout.states ?? []) {
		const kind = (s.kind === 'compartment' && !s.hidden) ? 'compartment'
			: s.kind === 'waste_package' ? 'waste_inventory'
				: s.kind === 'event' ? 'event' : null;
		if (kind) {
			for (const d of describeEntry(layout, s, kind, 'y')) {
				out.push({ offset: d.offset, label: d.label, block: s.name, kind, unit: d.unit, hidden: false });
			}
			continue;
		}
		for (let off = 0; off < s.width; off++) {
			out.push({
				offset: s.base + off,
				label: s.width > 1 ? `${s.name} #${off}` : s.name,
				block: s.name, kind: s.kind, unit: '', hidden: true,
			});
		}
	}
	return out;
}

/** The blocks that remember a path rather than a state: see `uncarried`. */
const PATH_KINDS = new Set(['min_max', 'snapshot', 'delay']);

/**
 * The algebraic blocks the derivative reads, directly or through others.
 *
 * Directly: every transfer and source rate, a compartment's dy/dt term, a
 * running mean's target (its integral's rate), and the settings and releases of
 * waste packages, disruptive events and far-field paths. Through others: by
 * `readsAlg`, which is the dependency list the builder orders and classifies
 * the slots by -- so it is complete, or the model would not run.
 */
function readByDerivative(system) {
	const algebraic = system.layout.algebraic ?? [];
	const byName = new Map(algebraic.map((a) => [a.name, a]));
	const direct = (a) => a.kind === 'transfer' || a.kind === 'inflow' || a.kind === 'compartment:dydt'
		|| a.kind === 'waste_package' || a.kind === 'farfield' || a.kind === 'running_mean:target'
		|| /^(waste_package|event|farfield):/.test(a.kind);
	const reached = new Set();
	const stack = algebraic.filter(direct).map((a) => a.name);
	while (stack.length) {
		const name = stack.pop();
		if (reached.has(name)) continue;
		reached.add(name);
		for (const d of byName.get(name)?.readsAlg ?? []) stack.push(d);
	}
	return algebraic.filter((a) => reached.has(a.name));
}

/** Whether a recording block is started, stopped or reset by a discrete event. */
function switchedByEvent(system, rec) {
	for (let off = 0; off < rec.width; off++) {
		const tuple = rec.dims.length ? tupleByList(system.layout.indexSpace, rec.dims, off) : {};
		for (const field of EVENT_FIELDS[rec.kind] ?? []) {
			const v = valueAt(rec.block, field, tuple);
			if (v != null && String(v).trim() !== '') return true;
		}
	}
	return false;
}

/**
 * `fn()` with every value of a parameter block moved a little, then put back.
 * What the switch-time list reads a parameter through (`constantValue`) is the
 * block itself, so that is what is moved.
 */
function withBlockMoved(block, fn) {
	const move = (v) => {
		const x = Number(v);
		return Number.isFinite(x) && String(v ?? '').trim() !== '' ? x * (1 + 1e-6) + 1e-9 : v;
	};
	const had = { value: block.value, entries: (block.entries ?? []).map((e) => e.value) };
	try {
		if (block.value !== undefined) block.value = move(block.value);
		for (const e of block.entries ?? []) if ('value' in e) e.value = move(e.value);
		return fn();
	} finally {
		block.value = had.value;
		(block.entries ?? []).forEach((e, i) => { if ('value' in e) e.value = had.entries[i]; });
	}
}

/**
 * What stands between the forward equations and the right answer, in words, or
 * null.
 *
 * `S' = J·S + df/dp` is the derivative of a smooth flow. Three things in a
 * model are not, and each adds a term to `dy/dp` that those equations do not
 * have -- so the run is refused rather than answered with a number that
 * silently leaves it out:
 *
 *   a jump        the state changes at an instant (waste packages failing all
 *                 at once, a disruptive event at a time). `dy/dp` after it
 *                 depends on how the jump moves with the parameters.
 *   a path        a min/max, a snapshot or a delay holds a value from earlier
 *                 in the run, and a running mean a discrete event switches
 *                 starts or stops at a crossing that moves; where the
 *                 derivative reads one, its dependence on the parameters
 *                 runs back through the whole history. Where nothing reads
 *                 it, it is a report and changes nothing here.
 *   a corner      a chosen parameter places a switch time, a failure window or
 *                 an event's window: moving it moves a discontinuity, whose
 *                 derivative is an impulse.
 */
export function uncarried(project, system, wanted) {
	const grid = project.timeGrid();
	const inside = (t) => t > grid[0] && t < grid[grid.length - 1];
	for (const j of jumpsOf(system)) {
		if (!inside(j.at)) continue;
		return `'${j.name}' makes the state jump at t=${j.at}, and dy/dp is not carried across `
			+ 'a jump: after it, it depends on how the jump moves with the parameters, which the '
			+ 'sensitivity equations do not have.';
	}
	// ...and so does an event a trigger sets off, at a time nobody knows until
	// the crossing is found -- which moves with the parameters too.
	for (const D of system.layout.events ?? []) {
		if (D.timing !== 'trigger') continue;
		return `'${D.name}' makes the state jump whenever its trigger fires, and dy/dp is not carried `
			+ 'across a jump: after it, it depends on how the jump and the crossing move with the '
			+ 'parameters, which the sensitivity equations do not have.';
	}
	// A semi-analytical path's release is read by its own held state, always,
	// and it is a convolution over the whole run's inflow.
	for (const p of system.layout.farfields ?? []) {
		if (!p.farf?.laplace) continue;
		return `'${p.local ?? p.name}' is worked out semi-analytically: its release is a convolution `
			+ 'over what flowed into it during the run, and dy/dp through a history is not carried by '
			+ 'the sensitivity equations, which see only the present. Work the path out on cells to '
			+ 'run a local sensitivity analysis.';
	}
	for (const a of readByDerivative(system)) {
		const rec = a.recorder;
		if (!rec) continue;
		if (PATH_KINDS.has(rec.kind) || (rec.kind === 'running_mean' && switchedByEvent(system, rec))) {
			return `'${a.local ?? a.name}' remembers the path of the run, and the model's rates read it: `
				+ 'dy/dp through a history is not carried by the sensitivity equations, which see only '
				+ 'the present.';
		}
	}
	const corners = switchTimes(project);
	for (const e of wanted) {
		const entry = (system.layout.parameters ?? []).find((p) => e.slot >= p.base && e.slot < p.base + p.width);
		if (!entry?.block) continue;
		const moved = withBlockMoved(entry.block, () => switchTimes(project));
		if (moved.length !== corners.length || moved.some((v, i) => v !== corners[i])) {
			return `'${slotLabel(e)}' places a corner of the run (a switch time, or when something `
				+ 'starts or stops): moving it moves a discontinuity, and dy/dp with respect to it is an '
				+ 'impulse the sensitivity equations do not have.';
		}
	}
	return null;
}

/**
 * Integrates the model and `dy/dp` for the parameters named.
 *
 * @param {object|Project} input
 * @param {object} opts
 * @param {string[]} opts.parameters  labels, as `slotLabel` spells them
 * @param {number} [opts.most]        refuse past this many, since each one
 *                                    costs another `n` states and another `f`
 * @param {boolean} [opts.differenced] difference `df/dp` even where it could be
 *                                    generated; for comparing the two
 * @param {(fraction: number, at: number) => void} [opts.onProgress]
 * @param {{aborted: boolean}} [opts.signal]
 * @returns {{t: Float64Array, y: Float64Array[], sens: Float64Array[][],
 *   chosen: Array, states: Array, series: Array, stats: object}}
 *   `y[i]` and `sens[k][i]` are per state, in the order of the state vector;
 *   `states` is the layout's blocks and `series` names each state (see
 *   `stateSeries`)
 */
export function runSensitivity(input, opts = {}) {
	const project = input instanceof Project ? input : new Project(input);
	const started = Date.now();
	const system = buildSystem(project);
	if (!system.jacobian?.available) {
		throw new Error('This model has no analytic Jacobian, and the sensitivity '
			+ 'equations are driven by it. ' + (system.jacobian?.reason ?? ''));
	}

	const all = parameterSlots(system);
	const byLabel = new Map(all.map((e) => [slotLabel(e), e]));
	const wanted = (opts.parameters ?? []).map((n) => byLabel.get(n)).filter(Boolean);
	if (!wanted.length) {
		throw new Error('Name at least one parameter to take the sensitivity to.');
	}
	const most = opts.most ?? 12;
	if (wanted.length > most) {
		throw new Error(`${wanted.length} parameters at once: each one adds a copy of `
			+ `the whole state vector to the solve and an evaluation of the derivative `
			+ `to every step. Choose at most ${most}.`);
	}
	const refusal = uncarried(project, system, wanted);
	if (refusal) throw new Error(refusal);

	const n = system.layout.nstate;
	const m = wanted.length;
	const N = n * (1 + m);
	const P = system.parameterValues;

	// --- the augmented right-hand side.
	const f0 = new Float64Array(n);
	const fp = new Float64Array(n);
	const yv = new Float64Array(n);
	const sv = new Float64Array(n);
	const jv = new Float64Array(n);

	// `df/dp`, generated when the model allows it. See `buildParamTangent` in
	// ./jacobian.js for the three block types that refuse; everything else
	// falls back to the difference below, which is what this always did.
	//
	// `opts.differenced` forces that fallback. It exists so the two can be run
	// against each other on a real model -- which is the only way to say that
	// the generated one is right on a model with no closed form -- and is not
	// something an interface offers.
	const tangent = opts.differenced
		? { available: false, reason: 'asked for the differenced df/dp' }
		: system.paramTangent?.() ?? { available: false, reason: 'not offered' };
	const dp = tangent.available ? new Float64Array(n) : null;
	const seedP = tangent.available
		? new Float64Array(system.layout.nparam) : null;

	// The clock-only algebra may be worked out on a coarser clock and
	// interpolated (`min_change_time`), anchored where each segment of the run
	// starts. The runner says where, and what the interval is: a perturbed
	// parameter has to reach those slots too, and the two ends the
	// interpolation holds were worked out from the old value -- so they are
	// dropped around each difference. And the tangent writes the clock slots
	// exactly at its instant, which the interpolation's cache would otherwise
	// go on taking for its own.
	let clockInterval = 0;
	let clockFrom = project.simulation.start_time;
	const onSegment = (from, interval) => { clockFrom = from; clockInterval = interval; };
	const forgetClock = () => {
		if (clockInterval > 0) system.useClockInterpolation?.(clockInterval, clockFrom);
	};

	const dydt = (t, Y, out) => {
		for (let i = 0; i < n; i++) yv[i] = Y[i];
		system.dydt(t, yv, f0);
		for (let i = 0; i < n; i++) out[i] = f0[i];

		for (let j = 0; j < m; j++) {
			const base = n * (j + 1);
			for (let i = 0; i < n; i++) sv[i] = Y[base + i];
			// J*S in one tangent pass.
			system.jacobian.jvp(t, yv, sv, jv);

			const { slot } = wanted[j];
			if (dp) {
				// df/dp in one more, seeded on the parameter instead of on the
				// state. Exact, and cheaper than the difference it replaced:
				// one tangent pass against a whole extra derivative evaluation
				// and two invariant passes.
				seedP.fill(0);
				seedP[slot] = 1;
				tangent.pvp(t, yv, seedP, dp);
				for (let i = 0; i < n; i++) out[base + i] = jv[i] + dp[i];
				continue;
			}

			// df/dp by one forward difference. `evaluateInvariant` is what
			// carries the new parameter into the algebra that was worked out
			// from the old one -- without it the perturbation reaches the
			// derivative only where a rate is recomputed every call, which on
			// these models is almost nowhere.
			const p0 = P[slot];
			const h = stepFor(p0);
			P[slot] = p0 + h;
			system.evaluateInvariant();
			forgetClock();
			system.dydt(t, yv, fp);
			P[slot] = p0;
			system.evaluateInvariant();
			forgetClock();

			for (let i = 0; i < n; i++) out[base + i] = jv[i] + (fp[i] - f0[i]) / h;
		}
		// The tangent left the clock slots at this instant's exact values.
		if (dp && clockInterval > 0) system.evaluateInvariant();
		return out;
	};

	// --- the iteration matrix: J down the diagonal, (1 + m) times, and under
	// it how each sensitivity's equations move with the state.
	//
	// S_j' = J(y)·S_j + df/dp_j(y), so d(S_j')/dy = (dJ/dy)·S_j + d(df/dp_j)/dy:
	// a block under the diagonal, on J's own pattern, since both terms are
	// derivatives of J's entries. Left out, as CVODES leaves it out, Newton
	// converges to the same answer, but each sensitivity's correction trails
	// the state's by one iteration, and the iteration's test reads the trailing
	// correction as one that has stopped converging: the far-field example with
	// its travel time a parameter failed a million steps' iterations at step
	// sizes no cut could mend. With it, 1,840 steps; the plain run takes 1,756.
	//
	// The block is J's own derivative along (S_j, e_j), both terms at once: J at
	// the state moved by ε·S_j and the parameter by ε, less J, over ε. One more
	// Jacobian per parameter, and Newton asks for a Jacobian only when it
	// stalls. The budget rows take none: df/dp writes them nothing (see
	// `buildParamTangent` in ./jacobian.js).
	const pat = system.jacobian.pattern;
	const blocks = 1 + m;
	const nnzJ = pat.nnz;
	const colPtr = new Int32Array(N + 1);
	const rowIdx = new Int32Array(nnzJ * (blocks + m));
	let at = 0;
	// A state's column: J's entries, then each sensitivity's under them.
	for (let j = 0; j < n; j++) {
		colPtr[j] = at;
		for (let b = 0; b < blocks; b++) {
			for (let k = pat.colPtr[j]; k < pat.colPtr[j + 1]; k++) rowIdx[at++] = b * n + pat.rowIdx[k];
		}
	}
	// A sensitivity's column: J's entries, in its own block.
	for (let b = 1; b < blocks; b++) {
		for (let j = 0; j < n; j++) {
			colPtr[b * n + j] = at;
			for (let k = pat.colPtr[j]; k < pat.colPtr[j + 1]; k++) rowIdx[at++] = b * n + pat.rowIdx[k];
		}
	}
	colPtr[N] = at;
	const bigPattern = { n: N, nnz: at, colPtr, rowIdx };
	const bigValues = new Float64Array(at);
	// Where J's entries, and each coupling's, sit among the big values: entry k
	// of a state's column c is at blocks·colPtr[c] + b·(its length) + its place.
	const stateAt = Array.from({ length: blocks }, () => new Int32Array(nnzJ));
	for (let c = 0; c < n; c++) {
		const lo = pat.colPtr[c];
		const len = pat.colPtr[c + 1] - lo;
		for (let k = lo; k < lo + len; k++) {
			for (let b = 0; b < blocks; b++) stateAt[b][k] = blocks * lo + b * len + (k - lo);
		}
	}
	const J0 = new Float64Array(nnzJ);
	const coupling = Array.from({ length: m }, () => new Float64Array(nnzJ));
	const yc = new Float64Array(n);
	const budget = system.layout.budget;
	const budgetFrom = budget ? budget.base : 0;
	const budgetTo = budget ? budget.base + budget.terms.length * budget.nfam : 0;
	/** d(S_j')/dy into `out`, on J's pattern, from J's values `J0` at (t, y). */
	const couplingOf = (t, Y, j, out) => {
		const { slot } = wanted[j];
		const p0 = P[slot];
		const e = EPS * (Math.abs(p0) || 1);
		for (let i = 0; i < n; i++) yc[i] = Y[i] + e * Y[n * (j + 1) + i];
		P[slot] = p0 + e;
		system.evaluateInvariant();
		forgetClock();
		let moved;
		try {
			moved = system.jacobian.evaluate(t, yc);
		} finally {
			P[slot] = p0;
			system.evaluateInvariant();
			forgetClock();
		}
		out.fill(0);
		if (!moved) return;
		for (let k = 0; k < nnzJ; k++) out[k] = (moved[k] - J0[k]) / e;
		for (let c = 0; c < n; c++) {
			for (let k = pat.colPtr[c]; k < pat.colPtr[c + 1]; k++) {
				const r = pat.rowIdx[k];
				if (r >= budgetFrom && r < budgetTo) out[k] = 0;
			}
		}
		// A coupling that is not a number is no coupling: the block is left out.
		for (let k = 0; k < nnzJ; k++) if (!Number.isFinite(out[k])) { out.fill(0); return; }
	};
	// Asked to difference its Jacobian (`Jacobian: finite differences`), the
	// model gets that here too: the pattern and its colouring, and no values.
	// `J·S` above is the tangent's either way -- the setting is about the
	// matrix Newton iterates with.
	const differencedMatrix = project.simulation.jacobian === 'numeric';
	const G = system.jacobian.groups ?? [];
	const bigJacobian = {
		pattern: bigPattern,
		constant: false,
		// The colouring is the original's, twice: a state's column now reaches
		// the sensitivities' rows as well, so it shares no group with theirs --
		// the states' groups, then the sensitivities', each across every block.
		// A differenced fallback then costs two evaluations per colour.
		groups: G.length
			? [
				...G.map((g) => Array.from(g)),
				...G.map((g) => {
					const out = [];
					for (let b = 1; b < blocks; b++) for (const j of g) out.push(b * n + j);
					return out;
				}),
			]
			: null,
		evaluate: (t, Y) => {
			if (differencedMatrix) return null;
			for (let i = 0; i < n; i++) yv[i] = Y[i];
			const v = system.jacobian.evaluate(t, yv);
			if (!v) return null;
			J0.set(v);
			for (let j = 0; j < m; j++) couplingOf(t, Y, j, coupling[j]);
			let w = 0;
			for (let c = 0; c < n; c++) {
				const lo = pat.colPtr[c];
				const hi = pat.colPtr[c + 1];
				for (let k = lo; k < hi; k++) bigValues[w++] = J0[k];
				for (let j = 0; j < m; j++) for (let k = lo; k < hi; k++) bigValues[w++] = coupling[j][k];
			}
			for (let b = 1; b < blocks; b++) for (let k = 0; k < nnzJ; k++) bigValues[w++] = J0[k];
			return bigValues;
		},
	};

	// --- initial conditions, the sensitivities included.
	const y0 = system.initialState();
	const Y0 = new Float64Array(N);
	Y0.set(y0, 0);
	for (let j = 0; j < m; j++) {
		// dy0/dp: an initial inventory may be an equation over parameters, and
		// where it is not this is exactly zero, which is the right answer.
		const { slot } = wanted[j];
		const p0 = P[slot];
		const h = stepFor(p0);
		P[slot] = p0 + h;
		system.evaluateInvariant();
		const yh = system.initialState();
		P[slot] = p0;
		system.evaluateInvariant();
		for (let i = 0; i < n; i++) Y0[n * (j + 1) + i] = (yh[i] - y0[i]) / h;
	}

	// --- tolerances. A sensitivity is not an inventory.
	//
	// `dy/dp` carries the units of y over the units of p, so the absolute
	// tolerance that is right for the state is wrong for the sensitivity by a
	// factor of p -- and `abstol` is an *absolute* floor, so it is the one
	// setting that cannot simply be carried across. On `four-compartment.json`
	// the rates are 1e-5 and the inventory 1e10, which makes dy/dp reach 1e13
	// while the model asks for 1e-9 absolute: the solver was being told to
	// resolve a quantity of order 1e13 to a part in 1e22 as it passed through
	// zero, and answered by rejecting 79% of its steps and running to the
	// million-step ceiling. Scaled, the same run takes 190 steps and agrees
	// with an independent dp45 integration to nine figures.
	//
	// `atol/|p|` is CVODES's rule for exactly this (`CVodeSensSStolerances`
	// sets the sensitivity tolerances from the state's over the parameter
	// scale), and it is the only scale in the problem: nothing else here knows
	// how large dy/dp will get. A parameter that is zero has no scale to read,
	// and takes the state's tolerance unchanged.
	//
	// The state block takes the run's own per-compartment tolerances rather
	// than the bare setting, so the states are integrated to what the plain
	// run integrates them to.
	const baseAtol = absoluteTolerance(project, system.layout);
	const atolAt = (i) => (typeof baseAtol === 'number' ? baseAtol : baseAtol[i]);
	const atol = new Float64Array(N);
	for (let i = 0; i < n; i++) atol[i] = atolAt(i);
	for (let j = 0; j < m; j++) {
		const scale = Math.abs(P[wanted[j].slot]) || 1;
		for (let i = 0; i < n; i++) atol[n * (j + 1) + i] = atolAt(i) / scale;
	}
	// ...and what each sensitivity is weighed against: itself, and its state
	// over |p| as well (`weightFloor` in ../ode/solvers/ndf.js). Weighed
	// against itself alone, a sensitivity negligible beside its state was
	// still asked for rtol of itself, which the rounding of the large terms its
	// equation cancels down to can deny it: on the far-field example's travel
	// time, a deep matrix cell's 4.6 came out of terms of 1e7, its Newton
	// corrections stalled at 2e-9 of it against a test of 3e-9, and the run
	// never finished. Against y/|p| too it is held to what it means for y --
	// an elasticity right to rtol, which is what the dialog shows.
	const weightFloor = { from: new Int32Array(N).fill(-1), factor: new Float64Array(N) };
	for (let j = 0; j < m; j++) {
		const scale = Math.abs(P[wanted[j].slot]) || 1;
		for (let i = 0; i < n; i++) {
			weightFloor.from[n * (j + 1) + i] = i;
			weightFloor.factor[n * (j + 1) + i] = 1 / scale;
		}
	}

	// --- and the solve, as a run of the model: see `equations` in ./runner.js.
	// The floor there is the run's -- each compartment as it sets it -- and
	// applies to the states and to nothing after them: a sensitivity may
	// perfectly well be negative. Progress and Stop are read through one hook,
	// so a caller with only a Stop to offer still has one read.
	let results;
	try {
		results = run(project, {
			system,
			onGrid: true,
			signal: opts.signal,
			onProgress: opts.onProgress ?? (opts.signal ? () => {} : undefined),
			equations: {
				dydt,
				y0: Y0,
				abstol: atol,
				jacobian: bigJacobian,
				solver: 'ndf',
				onSegment,
				weightFloor,
				iterationMatrix: blockMatrix(pat, n, m, stateAt),
			},
		});
	} catch (e) {
		throw differencedFailure(e, wanted, tangent, opts, project, P) ?? e;
	}

	// --- unpack: the states, and one sensitivity block per parameter.
	const times = results.t.length;
	const y = [];
	const sens = wanted.map(() => []);
	for (let i = 0; i < n; i++) {
		const row = new Float64Array(times);
		for (let j = 0; j < times; j++) row[j] = results.y[j][i];
		y.push(row);
	}
	for (let k = 0; k < m; k++) {
		for (let i = 0; i < n; i++) {
			const row = new Float64Array(times);
			for (let j = 0; j < times; j++) row[j] = results.y[j][n * (k + 1) + i];
			sens[k].push(row);
		}
	}

	return {
		t: results.t,
		y,
		sens,
		chosen: wanted.map((e) => ({ label: slotLabel(e), name: e.name, index: e.index, value: e.value })),
		states: system.layout.states,
		series: stateSeries(system),
		stats: {
			ms: Date.now() - started,
			nsteps: results.stats?.nsteps ?? 0,
			states: N,
			restarts: results.stats?.restarts ?? 0,
		},
	};
}

/**
 * The matrix Newton iterates with for [y, S_1, ..., S_m], a block at a time
 * (`iterationMatrix` in ../ode/solvers/ndf.js). It is block lower triangular,
 *
 *     [  A                 ]        A = I - a·J
 *     [ -a·C_1   A         ]        C_j = d(S_j')/dy
 *     [ -a·C_2        A    ]  ...
 *
 * so the states' block is solved first and each sensitivity's after it, the
 * coupling carried to its right-hand side: one factorisation of A -- two while
 * the floor holds a state, whose row is the identity in the states' block
 * alone -- where the whole matrix took 1 + m, and never a pivot taken across
 * blocks. An LU of the whole matrix pivots a state's column on a
 * sensitivity's row wherever the coupling is the larger entry, and mixes that
 * row's rounding into the state's correction, which for a state near zero is
 * all of it: on the far-field example the emptied vault's corrections came
 * out hundreds of times their size, and Newton stopped converging on them.
 *
 * @param {{n: number, nnz: number, colPtr: Int32Array, rowIdx: Int32Array}} base  J's pattern
 * @param {number} n  the states
 * @param {number} m  the sensitivities
 * @param {Int32Array[]} stateAt  where J's entries (block 0) and each coupling
 *   sit among the big values
 */
function blockMatrix(base, n, m, stateAt) {
	const nnzJ = base.nnz;
	const J = new Float64Array(nnzJ);
	const C = Array.from({ length: m }, () => new Float64Array(nnzJ));
	const ry = new Float64Array(n);
	const rs = new Float64Array(n);
	const cd = new Float64Array(n);
	const xs = new Float64Array(n);
	const heldY = new Uint8Array(n);
	const extract = (values) => {
		for (let b = 0; b <= m; b++) {
			const at = stateAt[b];
			const into = b === 0 ? J : C[b - 1];
			for (let k = 0; k < nnzJ; k++) into[k] = values[at[k]];
		}
	};
	return (pattern, values, opts) => {
		extract(values);
		const states = iterationMatrix(base, J, { ...opts, n });
		let apart = null; // the sensitivities' own, while the floor holds a state
		let sens = states;
		let a = 0;
		return {
			get info() { return states.info; },
			get sparse() { return states.sparse; },
			get lu() { return states.lu; },
			get fill() { return states.fill; },
			get repivots() { return states.repivots; },
			get fallbacks() { return states.fallbacks; },
			form(aNow, valuesNow, w, held) {
				if (w) throw new Error('the sensitivity equations are not solved in scaled variables');
				extract(valuesNow);
				a = aNow;
				let any = false;
				if (held) for (let i = 0; i < n; i++) { heldY[i] = held[i]; if (held[i]) any = true; }
				states.form(a, J, null, any ? heldY : null);
				if (any) {
					apart ??= iterationMatrix(base, J, { ...opts, n });
					apart.form(a, J, null, null);
					sens = apart;
				} else sens = states;
			},
			solve(rhs, out) {
				const x = out ?? new Float64Array(n * (1 + m));
				for (let i = 0; i < n; i++) ry[i] = rhs[i];
				const sy = states.solve(ry, xs);
				for (let i = 0; i < n; i++) x[i] = sy[i];
				for (let j = 0; j < m; j++) {
					// The coupling's part: C_j times the states' correction,
					// column by column.
					cd.fill(0);
					const c = C[j];
					for (let col = 0; col < n; col++) {
						const v = x[col];
						for (let k = base.colPtr[col]; k < base.colPtr[col + 1]; k++) cd[base.rowIdx[k]] += c[k] * v;
					}
					const off = n * (j + 1);
					for (let i = 0; i < n; i++) rs[i] = rhs[off + i] + a * cd[i];
					const sx = sens.solve(rs, xs);
					for (let i = 0; i < n; i++) x[off + i] = sx[i];
				}
				return x;
			},
		};
	};
}

/** The ways a solve gives up that a noisy driving term brings about. */
const NOISY = new Set(['tolerance', 'stalled', 'steps']);

/**
 * A solve of the sensitivity equations that gave up, said for what it most
 * likely is when df/dp is worked out by a difference, or null. A difference is
 * right to about eight figures of f·p, and dy/dp is held to rtol of the larger
 * of itself and its state over |p|: in a state that turns over many times a
 * unit of time, what the difference loses to rounding is more than that, and
 * the solver answers by shrinking its step until it gives up, saying something
 * about the model that is not so. The far-field example's travel time does,
 * differenced: its matrix cells exchange with the fracture hundreds of times
 * a year. The solver's own words become the hint.
 */
function differencedFailure(e, wanted, tangent, opts, project, P) {
	if (tangent.available || e?.name !== 'SolverError' || !NOISY.has(e.code)) return null;
	const names = wanted.map(slotLabel);
	const list = names.length === 1 ? names[0]
		: `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
	const why = opts.differenced ? 'as asked' : `since ${tangent.reason}`;
	const tol = Number(project.simulation.abstol) / (Math.abs(P[wanted[0].slot]) || 1);
	const where = Number.isFinite(e.t) ? ` past t=${e.t}` : '';
	return Object.assign(new SolverError(`The sensitivity equations could not be integrated${where}: df/dp along `
		+ `${list} is worked out by a difference, ${why}, which is right to about eight figures, and what it loses `
		+ 'to rounding may be more than dy/dp is held to: the run\'s relative tolerance of the larger of dy/dp and '
		+ 'the state over the parameter\'s value, and no less than the absolute tolerance over it, '
		+ `${tol.toPrecision(2)} for ${names[0]}. Looser tolerances are the first thing to try.`, e.t),
	{ code: e.code, hint: solverWords(e.message) });
}

/**
 * What the solver said, without the advice the run adds for a model's own
 * equations -- a compartment held at zero, a stiffer solver, tighter
 * tolerances -- which is about the wrong thing here.
 */
function solverWords(message) {
	let m = String(message);
	const held = m.indexOf(' Something is holding a state where it cannot go');
	if (held >= 0) m = m.slice(0, held);
	const prefix = 'variableOrder failed: ';
	const advice = m.indexOf('. If the model is not stiff, dormandPrince may do better');
	if (m.startsWith(prefix) && advice >= 0) m = m.slice(prefix.length, advice);
	return m;
}

/**
 * The sensitivity in the form anybody reads: a relative change for a relative
 * change.
 *
 * `dy/dp` carries the units of both and cannot be compared between parameters
 * -- one in years against one in m^3/kg says nothing. The elasticity
 * `(p/y)·(dy/dp)` is dimensionless: "a 1% change in this gives a 0.4% change in
 * that", which is comparable across a whole model.
 */
export function elasticity(yRow, sRow, p) {
	const out = new Float64Array(yRow.length);
	for (let i = 0; i < yRow.length; i++) {
		out[i] = yRow[i] === 0 ? NaN : (p / yRow[i]) * sRow[i];
	}
	return out;
}
