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
 * **`df/dp` is differenced, and that is the one approximation here.** The
 * tangent is seeded on the *state*; seeding it on the parameters instead would
 * give `df/dp` exactly, and needs a second sparsity pass over parameter columns
 * and a second generated function -- the largest refactor left in this tool. A
 * one-sided difference costs one extra evaluation of `f` per parameter per
 * call and is right to about eight figures, which is far inside the tolerance
 * anyone integrates to. It is also why this is offered for a handful of chosen
 * parameters rather than for all 617 of an assessment's.
 *
 * **The iteration matrix ignores the second derivatives.** The true Jacobian of
 * the augmented system has `d(J·S)/dy` terms in the sensitivity blocks, which
 * are second derivatives of `f`. Left out, exactly as CVODES leaves them out:
 * they affect how fast Newton converges and not what it converges *to*, so the
 * answer is the same and the matrix is the original `J` repeated down the
 * diagonal.
 */

import { Project } from '../domain/project.js';
import { buildSystem, tupleByList } from './builder.js';
import { variableOrder } from '../ode/variable-order.js';
import { effectiveValue } from '../domain/edit.js';
import { absoluteTolerance } from './runner.js';

/** A step that is small against the value and large against its rounding. */
const EPS = Math.sqrt(Number.EPSILON);
const stepFor = (p) => EPS * Math.max(Math.abs(p), 1);

/**
 * Every parameter slot a model has, by name and index.
 *
 * The same walk `distributedSlots` does, without the distribution: a
 * sensitivity is about a parameter the model holds, whether or not anybody has
 * said how uncertain it is.
 *
 * @returns {Array<{slot: number, name: string, index: object, value: number}>}
 */
export function parameterSlots(system) {
	const out = [];
	for (const entry of system.layout.parameters ?? []) {
		const { block, dims, base, width } = entry;
		for (let off = 0; off < width; off++) {
			const tuple = dims.length ? tupleByList(system.layout.indexSpace, dims, off) : {};
			out.push({
				slot: base + off,
				name: entry.name,
				index: tuple,
				value: Number(effectiveValue(block, 'value', tuple)),
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
 * Integrates the model and `dy/dp` for the parameters named.
 *
 * @param {object|Project} input
 * @param {object} opts
 * @param {string[]} opts.parameters  labels, as `slotLabel` spells them
 * @param {number} [opts.most]        refuse past this many, since each one
 *                                    costs another `n` states and another `f`
 * @param {boolean} [opts.differenced] difference `df/dp` even where it could be
 *                                    generated; for comparing the two
 * @param {(fraction: number) => void} [opts.onProgress]
 * @param {{aborted: boolean}} [opts.signal]
 * @returns {{t: Float64Array, y: Float64Array[], sens: Float64Array[][],
 *   chosen: Array, outputs: Array, stats: object}}
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
			system.dydt(t, yv, fp);
			P[slot] = p0;
			system.evaluateInvariant();

			for (let i = 0; i < n; i++) out[base + i] = jv[i] + (fp[i] - f0[i]) / h;
		}
		return out;
	};

	// --- the iteration matrix: J down the diagonal, (1 + m) times.
	const pat = system.jacobian.pattern;
	const blocks = 1 + m;
	const colPtr = new Int32Array(N + 1);
	const rowIdx = new Int32Array(pat.nnz * blocks);
	let at = 0;
	for (let b = 0; b < blocks; b++) {
		for (let j = 0; j < n; j++) {
			colPtr[b * n + j] = at;
			for (let k = pat.colPtr[j]; k < pat.colPtr[j + 1]; k++) {
				rowIdx[at++] = b * n + pat.rowIdx[k];
			}
		}
	}
	colPtr[N] = at;
	const bigPattern = { n: N, nnz: at, colPtr, rowIdx };
	const bigValues = new Float64Array(at);
	const bigJacobian = {
		pattern: bigPattern,
		constant: false,
		// The colouring is the original's, repeated -- which is what lets a
		// differenced fallback still cost one evaluation per colour.
		groups: (system.jacobian.groups ?? []).length
			? Array.from({ length: (system.jacobian.groups ?? []).length }, (_, g) => {
				const out = [];
				for (let b = 0; b < blocks; b++) {
					for (const j of system.jacobian.groups[g]) out.push(b * n + j);
				}
				return out;
			})
			: null,
		evaluate: (t, Y) => {
			for (let i = 0; i < n; i++) yv[i] = Y[i];
			const v = system.jacobian.evaluate(t, yv);
			if (!v) return null;
			for (let b = 0; b < blocks; b++) bigValues.set(v, b * pat.nnz);
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

	// --- and the solve. The floor is a fact about an inventory, not about a
	// derivative: a sensitivity may perfectly well be negative, so the clamp
	// applies to the states and to nothing after them.
	const nonNegative = new Array(N).fill(false);
	if (project.simulation.non_negative !== false) {
		for (const s of system.layout.states) {
			if (s.kind !== 'compartment' && s.kind !== 'waste_package') continue;
			for (let i = 0; i < s.width; i++) nonNegative[s.base + i] = true;
		}
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

	const grid = project.timeGrid();
	const sol = variableOrder(dydt, grid, Y0, {
		rtol: project.simulation.rtol,
		abstol: atol,
		jacobian: bigJacobian,
		nonNegative,
		signal: opts.signal,
		onProgress: opts.onProgress,
	});

	// --- unpack: the states, and one sensitivity block per parameter.
	const times = sol.t.length;
	const y = [];
	const sens = wanted.map(() => []);
	for (let i = 0; i < n; i++) {
		const row = new Float64Array(times);
		for (let j = 0; j < times; j++) row[j] = sol.y[j][i];
		y.push(row);
	}
	for (let k = 0; k < m; k++) {
		for (let i = 0; i < n; i++) {
			const row = new Float64Array(times);
			for (let j = 0; j < times; j++) row[j] = sol.y[j][n * (k + 1) + i];
			sens[k].push(row);
		}
	}

	return {
		t: sol.t,
		y,
		sens,
		chosen: wanted.map((e) => ({ label: slotLabel(e), name: e.name, index: e.index, value: e.value })),
		states: system.layout.states,
		stats: { ms: Date.now() - started, nsteps: sol.stats?.nsteps ?? 0, states: N },
	};
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
