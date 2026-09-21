/**
 * Making sampled inputs move together.
 *
 * A probabilistic run draws every distributed input on a stream of its own, so
 * two inputs are independent unless something says otherwise. In an assessment
 * they often are not: the sorption coefficients of one element in three
 * compartments were fitted from the same experiments, and a run that draws them
 * independently produces realisations -- high in the backfill, low in the rock
 * -- that nobody believes. GoldSim lets a Stochastic be correlated to another
 * by a rank correlation coefficient; Ecolego's desktop version does not, and
 * the assessment models tested here vary 600-odd inputs with no correlation between any
 * of them. This is the mechanism, so a model can say so where it is true.
 *
 * **Iman and Conover (1982)**, which is the standard way to do this on a Latin
 * hypercube sample and the one every risk tool uses, because of what it
 * preserves. It *permutes* each correlated column -- reorders the values a
 * parameter was going to take -- so that the columns' ranks correlate the way
 * the target matrix says. Nothing about any one column changes: the same
 * strata, the same values, the same marginal distribution; only which
 * realisation gets which. So the band of any single input is exactly what it
 * would have been, and the guarantee the sampler makes -- that an input's
 * draws do not depend on what else is sampled -- holds for every input that is
 * not itself in a correlated pair.
 *
 * The algorithm, for the `K` columns that appear in some pair:
 *
 *   1. Scores `S` (N × K): van der Waerden scores Φ⁻¹(i/(N+1)) in a seeded
 *      random order per column, so `S` is roughly uncorrelated and normal.
 *   2. `E = corr(S)`, the correlation the scores actually have, and its
 *      Cholesky factor `F`; the target `C` and its factor `P`.
 *   3. `T = S · (P F⁻¹)ᵀ`, whose sample rank correlation is `C` -- the
 *      `F⁻¹` takes out what `S` had, the `P` puts in what is wanted.
 *   4. Each input column is reordered so that its ranks are those of the
 *      matching column of `T`.
 *
 * **The target has to be a correlation matrix**, which pairwise coefficients
 * typed one at a time need not add up to: A–B at 0.9, B–C at 0.9 and A–C at
 * −0.9 is not achievable by any three variables. The nearest matrix that is
 * -- eigenvalues clipped, diagonal put back to one -- is used instead, and the
 * caller is told how far it moved, so a contradiction is a notice and not a
 * quiet different experiment.
 *
 * Coefficients are **rank** (Spearman) correlations, which is what a
 * permutation can promise. Pearson correlation of the values follows only as
 * closely as the two marginals allow, and for the log-triangular and
 * log-uniform shapes these models are made of that is close.
 */

import { probit } from './pdf.js';
import { streamFor } from './sample.js';

/**
 * The pairs a model asks for, read off its simulation settings.
 *
 * Two spellings, both kept because both are how a modeller thinks:
 *
 *     "correlations": [
 *       { "a": "Kd[Tc-99]", "b": "Kd[I-129]", "r": 0.8 },
 *       { "group": "Kd", "r": 0.9 }
 *     ]
 *
 * A *pair* names two sampled inputs as `slotName` spells them. A *group* names
 * a parameter and correlates every one of its sampled indices with every other
 * at `r` -- the Kd of one element across every compartment it is in, which is
 * the case that comes up, and which as pairs would be 1,176 lines for a list
 * of 49.
 *
 * @param {object} project
 * @param {string[]} names   every sampled input, as `slotName` spells them
 * @returns {{pairs: Array<{a: number, b: number, r: number}>, problems: string[]}}
 *   pairs by position in `names`; problems say what was ignored and why
 */
export function correlationPairs(project, names) {
	const at = new Map(names.map((n, k) => [n, k]));
	const pairs = [];
	const problems = [];
	const seen = new Map();
	const add = (i, j, r, where) => {
		if (i === j) { problems.push(`${where}: an input cannot be correlated with itself.`); return; }
		const key = i < j ? `${i}:${j}` : `${j}:${i}`;
		if (seen.has(key)) {
			problems.push(`${where}: ${names[i]} and ${names[j]} are correlated twice; `
				+ 'the first coefficient is kept.');
			return;
		}
		seen.set(key, true);
		pairs.push({ a: Math.min(i, j), b: Math.max(i, j), r });
	};
	for (const c of project?.simulation?.correlations ?? []) {
		const r = Number(c?.r);
		const where = c?.group ? `group ${c.group}` : `${c?.a ?? '?'} – ${c?.b ?? '?'}`;
		if (!Number.isFinite(r) || r < -1 || r > 1) {
			problems.push(`${where}: a correlation is a number between -1 and 1, not ${c?.r}.`);
			continue;
		}
		if (c.group != null) {
			// Every sampled index of the parameter: `Kd[...]`, and the bare
			// name for a parameter with no index -- which has one slot and so
			// nothing to correlate with, and is said.
			const prefix = `${c.group}[`;
			const members = names.map((n, k) => (n === c.group || n.startsWith(prefix) ? k : -1))
				.filter((k) => k >= 0);
			if (members.length < 2) {
				problems.push(`${where}: ${members.length === 1 ? 'only one' : 'no'} sampled `
					+ 'index carries that name, so there is nothing to correlate it with.');
				continue;
			}
			for (let x = 0; x < members.length; x++) {
				for (let y = x + 1; y < members.length; y++) add(members[x], members[y], r, where);
			}
			continue;
		}
		const i = at.get(String(c.a));
		const j = at.get(String(c.b));
		if (i == null || j == null) {
			const missing = [i == null ? c.a : null, j == null ? c.b : null].filter(Boolean);
			problems.push(`${where}: ${missing.join(' and ')} ${missing.length === 1 ? 'is' : 'are'} `
				+ 'not a sampled input of this model (spelled as in the sampling plan, '
				+ 'e.g. Kd[Tc-99]).');
			continue;
		}
		add(i, j, r, where);
	}
	return { pairs, problems };
}

/**
 * Reorders the correlated columns in place so their ranks correlate as asked.
 *
 * @param {Float64Array[]} columns  one per sampled input, `n` long each
 * @param {Array<{a: number, b: number, r: number}>} pairs  from `correlationPairs`
 * @param {string[]} names   what each column is called, for the score streams
 * @param {number} seed      the run's seed
 * @returns {{columns: number[], adjusted: number}} which columns moved, and how
 *   far the target matrix had to be moved to be one (0 when it already was)
 */
export function imanConover(columns, pairs, names, seed) {
	if (!pairs.length) return { columns: [], adjusted: 0 };
	const n = columns[0]?.length ?? 0;
	// Two realisations cannot carry a correlation, and one cannot be ranked.
	if (n < 3) return { columns: [], adjusted: 0 };

	// The columns that take part, in a fixed order, so the matrices below are
	// small: K correlated inputs rather than every sampled input in the model.
	const involved = [...new Set(pairs.flatMap((p) => [p.a, p.b]))].sort((x, y) => x - y);
	const K = involved.length;
	const pos = new Map(involved.map((k, i) => [k, i]));

	// The target, and the nearest correlation matrix to it when it is not one.
	const C = identity(K);
	for (const p of pairs) {
		const i = pos.get(p.a);
		const j = pos.get(p.b);
		C[i * K + j] = p.r;
		C[j * K + i] = p.r;
	}
	const adjusted = nearestCorrelation(C, K);
	const P = cholesky(C, K);

	// Scores: normal quantiles of evenly spaced probabilities, shuffled. One
	// stream per column, named for the input, so a column's shuffle does not
	// depend on which other inputs are in a pair.
	const S = new Float64Array(n * K);
	for (let j = 0; j < K; j++) {
		const next = streamFor(seed, `correlation:${names[involved[j]]}`);
		const col = new Float64Array(n);
		for (let i = 0; i < n; i++) col[i] = probit((i + 1) / (n + 1));
		for (let i = n - 1; i > 0; i--) {
			const k = Math.floor(next() * (i + 1));
			const t = col[i];
			col[i] = col[k];
			col[k] = t;
		}
		for (let i = 0; i < n; i++) S[i * K + j] = col[i];
	}

	// What the scores correlate to by accident, taken out; what is wanted,
	// put in: T = S · (P F⁻¹)ᵀ.
	const E = correlationOf(S, n, K);
	const F = cholesky(E, K);
	const Finv = invertLower(F, K);
	const M = new Float64Array(K * K); // P · F⁻¹
	for (let i = 0; i < K; i++) {
		for (let j = 0; j < K; j++) {
			let s = 0;
			for (let l = 0; l < K; l++) s += P[i * K + l] * Finv[l * K + j];
			M[i * K + j] = s;
		}
	}
	const T = new Float64Array(n * K);
	for (let r = 0; r < n; r++) {
		for (let i = 0; i < K; i++) {
			let s = 0;
			for (let j = 0; j < K; j++) s += S[r * K + j] * M[i * K + j];
			T[r * K + i] = s;
		}
	}

	// Each input takes the rank pattern of its column of T: the realisation
	// holding the largest score gets the input's largest value, and so on.
	const order = new Int32Array(n);
	for (let j = 0; j < K; j++) {
		const col = columns[involved[j]];
		const sorted = Float64Array.from(col).sort();
		for (let i = 0; i < n; i++) order[i] = i;
		Array.prototype.sort.call(order, (x, y) => T[x * K + j] - T[y * K + j]);
		// `order[rank]` is the realisation with that rank; give it the value of
		// that rank.
		for (let rank = 0; rank < n; rank++) col[order[rank]] = sorted[rank];
	}
	return { columns: involved, adjusted };
}

/** The I of size K, flat. */
function identity(K) {
	const out = new Float64Array(K * K);
	for (let i = 0; i < K; i++) out[i * K + i] = 1;
	return out;
}

/** The sample correlation matrix of the columns of `S` (n × K). */
function correlationOf(S, n, K) {
	const mean = new Float64Array(K);
	for (let r = 0; r < n; r++) for (let j = 0; j < K; j++) mean[j] += S[r * K + j];
	for (let j = 0; j < K; j++) mean[j] /= n;
	const cov = new Float64Array(K * K);
	for (let r = 0; r < n; r++) {
		for (let i = 0; i < K; i++) {
			const di = S[r * K + i] - mean[i];
			for (let j = i; j < K; j++) cov[i * K + j] += di * (S[r * K + j] - mean[j]);
		}
	}
	const out = new Float64Array(K * K);
	for (let i = 0; i < K; i++) {
		for (let j = i; j < K; j++) {
			const c = cov[i * K + j] / Math.sqrt(cov[i * K + i] * cov[j * K + j]);
			out[i * K + j] = c;
			out[j * K + i] = c;
		}
	}
	return out;
}

/**
 * Cholesky, lower triangular, of a symmetric positive-definite matrix.
 *
 * A pivot that is not positive means the matrix is not one, which after
 * `nearestCorrelation` cannot happen except by rounding; the small floor is
 * that rounding, not a repair.
 */
function cholesky(A, K) {
	const L = new Float64Array(K * K);
	for (let i = 0; i < K; i++) {
		for (let j = 0; j <= i; j++) {
			let s = A[i * K + j];
			for (let l = 0; l < j; l++) s -= L[i * K + l] * L[j * K + l];
			if (i === j) {
				L[i * K + i] = Math.sqrt(Math.max(s, 1e-12));
			} else {
				L[i * K + j] = s / L[j * K + j];
			}
		}
	}
	return L;
}

/** The inverse of a lower-triangular matrix, by forward substitution. */
function invertLower(L, K) {
	const out = new Float64Array(K * K);
	for (let col = 0; col < K; col++) {
		for (let i = 0; i < K; i++) {
			let s = i === col ? 1 : 0;
			for (let l = 0; l < i; l++) s -= L[i * K + l] * out[l * K + col];
			out[i * K + col] = s / L[i * K + i];
		}
	}
	return out;
}

/**
 * Moves a symmetric matrix with unit diagonal to the nearest one that is a
 * correlation matrix, in place.
 *
 * Eigenvalues below a small floor are lifted to it and the matrix rebuilt, then
 * the diagonal is scaled back to one. Higham's alternating projections do this
 * more exactly; one pass is enough for matrices typed by hand, and it is the
 * size of the change that matters to the reader, which is what is returned.
 *
 * @returns {number} the largest change to any coefficient
 */
function nearestCorrelation(C, K) {
	const { values, vectors } = jacobiEigen(C, K);
	const floor = 1e-6;
	if (values.every((v) => v >= floor)) return 0;
	const before = Float64Array.from(C);
	for (let i = 0; i < K; i++) {
		for (let j = 0; j < K; j++) {
			let s = 0;
			for (let l = 0; l < K; l++) {
				s += vectors[i * K + l] * Math.max(values[l], floor) * vectors[j * K + l];
			}
			C[i * K + j] = s;
		}
	}
	// Back to unit diagonal.
	const d = new Float64Array(K);
	for (let i = 0; i < K; i++) d[i] = Math.sqrt(C[i * K + i]);
	for (let i = 0; i < K; i++) {
		for (let j = 0; j < K; j++) C[i * K + j] /= d[i] * d[j];
	}
	let worst = 0;
	for (let i = 0; i < K * K; i++) worst = Math.max(worst, Math.abs(C[i] - before[i]));
	return worst;
}

/**
 * Eigenvalues and eigenvectors of a symmetric matrix, by cyclic Jacobi.
 *
 * Small matrices only -- the correlated inputs of a model, tens at most -- so
 * the simplest method that is exact for symmetric matrices is the right one.
 * Vectors are the columns of `vectors`.
 */
function jacobiEigen(A0, K) {
	const A = Float64Array.from(A0);
	const V = identity(K);
	for (let sweep = 0; sweep < 100; sweep++) {
		let off = 0;
		for (let i = 0; i < K; i++) for (let j = i + 1; j < K; j++) off += A[i * K + j] ** 2;
		if (off < 1e-22) break;
		for (let p = 0; p < K; p++) {
			for (let q = p + 1; q < K; q++) {
				const apq = A[p * K + q];
				if (Math.abs(apq) < 1e-300) continue;
				const theta = (A[q * K + q] - A[p * K + p]) / (2 * apq);
				const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
				const c = 1 / Math.sqrt(t * t + 1);
				const s = t * c;
				for (let k = 0; k < K; k++) {
					const akp = A[k * K + p];
					const akq = A[k * K + q];
					A[k * K + p] = c * akp - s * akq;
					A[k * K + q] = s * akp + c * akq;
				}
				for (let k = 0; k < K; k++) {
					const apk = A[p * K + k];
					const aqk = A[q * K + k];
					A[p * K + k] = c * apk - s * aqk;
					A[q * K + k] = s * apk + c * aqk;
				}
				for (let k = 0; k < K; k++) {
					const vkp = V[k * K + p];
					const vkq = V[k * K + q];
					V[k * K + p] = c * vkp - s * vkq;
					V[k * K + q] = s * vkp + c * vkq;
				}
			}
		}
	}
	const values = new Float64Array(K);
	for (let i = 0; i < K; i++) values[i] = A[i * K + i];
	return { values, vectors: V };
}

/** One line per correlation, for a dialog or a notice. */
export function describeCorrelation(c) {
	if (c?.group != null) return `every index of ${c.group}, pairwise, at ${c.r}`;
	return `${c?.a ?? '?'} with ${c?.b ?? '?'} at ${c?.r}`;
}
