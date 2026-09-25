/**
 * Drawing values from the distributions on a model.
 *
 * ../domain/pdf.js holds the distributions -- what they are, what they mean and
 * how to draw them. This holds the other half: given one and a number between
 * 0 and 1, which value does it stand for. Everything here is an *inverse CDF*
 * rather than a sampler of its own, which buys three things at once:
 *
 *   - **Reproducibility.** A run is a seed and nothing else. The same seed and
 *     the same model give the same realisations on any machine, which is what
 *     makes a probabilistic result something to quote.
 *   - **Truncation for free.** A distribution truncated to `[lo, hi]` is the
 *     same inverse CDF fed a uniform confined to `[F(lo), F(hi)]`.
 *   - **Latin hypercube for free.** Stratifying is a statement about the
 *     uniforms, not about the shapes: one draw from each of N equal slices,
 *     shuffled per parameter.
 *
 * Latin hypercube is the default because it is what an assessment uses. Over N
 * realisations it covers each parameter's range evenly instead of leaving the
 * gaps and clumps that independent draws leave, so a tail is reached at
 * hundreds of runs rather than thousands. Ecolego offers the same choice
 * (`SamplingMethod`), and for the same reason.
 */

import { kindInfo, complete, cdfAt, quantile, phi, probabilityCuts } from './pdf.js';

// Re-exported because this is where a caller looks for them: they are about
// drawing from a distribution, and they live in ./pdf.js only because the
// shapes themselves need them.
export { cdfAt, quantile, phi };

/**
 * A small, fast, seeded generator.
 *
 * Not `Math.random`: a probabilistic result that cannot be reproduced is a
 * number nobody can check. This is mulberry32 -- thirty-two bits of state,
 * a period of 2^32, and good enough equidistribution for Monte Carlo over
 * parameters. It is not a cryptographic generator and nothing here wants one.
 */

/**
 * A stream of its own for one named thing.
 *
 * **Why every sampled parameter gets its own.** The realisations used to be
 * drawn from a single stream, split across the plan in order -- so `k` took
 * the first block of numbers, the next parameter the block after, and so on.
 * That makes a sample a fact about the *whole list*: adding a distribution to
 * one parameter shifted every parameter after it onto different numbers, and
 * the same seed on a model with one more sampled input gave a different answer
 * for every input it already had.
 *
 * Measured on a two-parameter model: adding an unrelated distribution moved
 * `k` from 0.18703, 0.16908, 0.12687 to 0.05209, 0.14484, 0.18309 -- same
 * seed, same parameter, same distribution.
 *
 * That matters because an assessment is re-run. It is reviewed, a parameter is
 * added, it is run again, and "the same seed gives the same sample for
 * everything that has not changed" is the property that lets the two runs be
 * compared at all. AMBER states it as a guarantee of its own -- *the sequence
 * of values for any sampled parameter will be the same regardless of which
 * other parameters are sampled* -- and it is what makes a partial run (see
 * `varied` in ../sim/probabilistic.js) a comparison rather than a new
 * experiment.
 *
 * So the seed for a parameter is the run's seed mixed with a hash of its name.
 * Two different names give unrelated streams, the same name gives the same
 * stream whatever else the model holds, and the run's seed still moves all of
 * them together.
 *
 * @param {number} seed  the run's seed
 * @param {string} name  what is being drawn for -- `slotLabel`, so `Kd[Tc-99]`
 *   and `Kd[I-129]` are separate streams, as they are separate quantities
 */
export function streamFor(seed, name) {
	return rng(mix(seed >>> 0, hash(String(name ?? ''))));
}

/** FNV-1a over a name. Small, stable, and not a cryptographic claim. */
export function hash(text) {
	let h = 2166136261;
	for (let i = 0; i < text.length; i++) {
		h ^= text.charCodeAt(i);
		h = Math.imul(h, 16777619);
	}
	return h >>> 0;
}

/** Two 32-bit values into one, well enough that neighbours do not collide. */
function mix(a, b) {
	let h = (a ^ Math.imul(b ^ (b >>> 16), 2246822507)) >>> 0;
	h = Math.imul(h ^ (h >>> 13), 3266489909) >>> 0;
	return (h ^ (h >>> 16)) >>> 0;
}

export function rng(seed = 1) {
	let a = (seed >>> 0) || 1;
	return () => {
		a = (a + 0x6D2B79F5) >>> 0;
		let t = a;
		t = Math.imul(t ^ (t >>> 15), t | 1);
		t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}



/**
 * One value from `spec` for the uniform `u`.
 *
 * A list is not a distribution and is not drawn from one: `pg(inorder=true)`
 * hands out its values in the order they were written, one per realisation,
 * which is how a model reproduces somebody else's run exactly. `at` is the
 * realisation's number, and only a list uses it.
 *
 * @param {object} spec  from ../domain/pdf.js
 * @param {number} u     a uniform in (0, 1)
 * @param {number} [at]  which realisation this is
 * @returns {number} NaN where the distribution is not filled in
 */
export function valueAtProbability(spec, u, at = 0) {
	if (!spec || !kindInfo(spec.kind) || !complete(spec)) return NaN;
	if (spec.kind === 'pg') {
		const v = spec.values ?? [];
		if (!v.length) return NaN;
		return spec.inorder === false
			? v[Math.min(v.length - 1, Math.floor(u * v.length))]
			: v[((spec.pos ?? 0) + at) % v.length];
	}
	// Truncation is the same curve read between two probabilities rather than
	// between 0 and 1. Done here rather than by rejection: rejection has no
	// bound on how many draws it takes, and on a distribution truncated to its
	// own tail -- which real files contain -- that is a run that never starts.
	//
	// A truncation written as a pair of percentiles needs no CDF at all: the
	// percentile *is* the probability this reads between, which is the whole
	// reason a data set quotes it that way. Both forms apply where both are
	// given, and the tighter one wins on each side. Ecolego writes
	// `trmin=6.5,trmax=0.0` to mean "no truncation": the two the wrong way
	// round. Taken as written it leaves nothing to draw from, so it is read as
	// what it means. `pdfProblems` says so in the editor. All of that is
	// `probabilityCuts`, which the density the Distribution summary draws
	// asks too, so the curve and the draws are cut in the same place.
	const { lo, hi, reversed } = probabilityCuts(spec);
	// Never exactly 0 or 1: the quantile of either is infinite for a curve
	// with unbounded tails, and one infinite parameter ruins a whole run.
	const q = Math.min(1 - 1e-12, Math.max(1e-12, lo + u * (hi - lo)));
	const v = quantile(spec, q);
	// The trip through the CDF and back is good to a billionth, not exactly
	// (see `probit`), and a truncation is a bound: a draw a billionth outside
	// it is outside it.
	if (reversed) return v;
	if (spec.trmin != null && v < spec.trmin) return spec.trmin;
	if (spec.trmax != null && v > spec.trmax) return spec.trmax;
	return v;
}

/**
 * `n` uniforms in (0, 1), stratified or not.
 *
 * Latin hypercube: one from each of `n` equal slices, in a shuffled order, so
 * the draws cover the range evenly instead of clumping. Independent uniforms
 * are the other option and are what "random" means everywhere else.
 */
export function uniforms(n, next, { latin = true } = {}) {
	const out = new Float64Array(n);
	if (!latin) {
		for (let i = 0; i < n; i++) out[i] = next();
		return out;
	}
	for (let i = 0; i < n; i++) out[i] = (i + next()) / n;
	// Fisher-Yates, so which slice a realisation gets is independent of which
	// slice every other parameter gave it -- otherwise every parameter would
	// rise together through the run and the sample would lie on a diagonal.
	for (let i = n - 1; i > 0; i--) {
		const j = Math.floor(next() * (i + 1));
		const t = out[i];
		out[i] = out[j];
		out[j] = t;
	}
	return out;
}

/**
 * Every distributed value in the model, and where it lives in `P`.
 *
 * A parameter's distribution is per index, exactly as its value is: the
 * entry's own, or the parameter's. So this walks the built layout rather than
 * the project -- the layout is what says which slot of `P` an index is.
 *
 * @param {object} layout  `system.layout`
 * @param {(block: object, key: string, tuple: object) => any} effective
 *        how a per-index value is read, handed in to keep the domain out of
 *        this file's business -- `ed.effectiveValue`
 * @param {(space: object, dims: string[], off: number) => object} tupleAt
 * @returns {Array<{slot: number, name: string, index: object, spec: object}>}
 */
export function distributedSlots(layout, effective, tupleAt) {
	const out = [];
	// A lookup table's point that carries its own spread is a distributed
	// value like any other: it has a slot, it has a spec, and a realisation
	// writes it. What is different is only where it ends up -- the builder
	// puts it back into the table's own array; see `refreshTables`.
	for (const pt of layout.lookupPoints ?? []) {
		if (!pt.spec || !complete(pt.spec)) continue;
		out.push({
			slot: pt.slot,
			// The time is part of the name, since a table has one per point
			// and `Table` on its own would name several inputs at once.
			name: `${pt.name}@${pt.at}`,
			index: pt.index ?? {},
			spec: pt.spec,
		});
	}
	for (const entry of layout.parameters ?? []) {
		const { block, dims, base, width } = entry;
		for (let off = 0; off < width; off++) {
			const tuple = dims.length ? tupleAt(layout.indexSpace, dims, off) : {};
			const spec = effective(block, 'pdf', tuple);
			if (!spec || !complete(spec)) continue;
			out.push({ slot: base + off, name: entry.name, index: tuple, spec });
		}
	}
	return out;
}
