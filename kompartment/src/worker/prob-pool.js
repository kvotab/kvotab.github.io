/**
 * A probabilistic run shared out over the machine's cores.
 *
 * A thousand realisations are a thousand independent integrations, and a
 * browser tab was doing them one after another on one thread while the other
 * seven cores sat idle. A desktop tool runs them on a thread pool sized from
 * the processor count; this is that pool, in the one form a browser offers --
 * more Workers.
 *
 * **The answer does not depend on how many cores there are.** That is the
 * whole design constraint and everything below follows from it. Latin
 * hypercube sampling is a statement about the *entire* column of realisations,
 * so the design cannot be drawn per slice: each worker draws all of it, from
 * the same seed, and integrates only the realisations that are its own. Slices
 * come back and are written into place by realisation number, never by arrival
 * order. Run the same model with the same seed on one core and on sixteen and
 * the matrices are identical to the last bit -- there is a test.
 *
 * **What it costs.** Every worker builds the model for itself, because a built
 * system is compiled functions and typed arrays and cannot cross a
 * `postMessage`. So a run of `n` realisations over `w` workers costs `w` builds
 * instead of one, and pays for them only if the solving saved is worth more.
 * `workersFor` is where that judgement is made, and it declines to fan out
 * rather than pretending: a handful of realisations of a model that takes a
 * minute to build is slower on eight cores than on one.
 *
 * **Nested workers are not everywhere.** Safari refused them until 16.4, and
 * some embeddings still do. `new Worker` throwing here is not an error -- it
 * means this machine runs the job the way it always did, on this thread, and
 * says so in the statistics rather than failing.
 */

import { runProbabilistic } from '../sim/probabilistic.js';

/** Never more than this, whatever the machine claims. */
export const MOST_WORKERS = 16;

/**
 * What one worker costs to have, before it does anything.
 *
 * It has to be created, and it has to load and compile the whole module graph
 * of the simulator for itself. Measured in Chrome on a warm module cache: 55 ms
 * each, and nine started together took 406 ms, so they overlap but not much --
 * it is compilation, not waiting. Rounded up, and used to keep a pool away
 * from runs too small to earn it: forty realisations of a model that solves in
 * two milliseconds is eighty milliseconds of work and half a second of
 * starting workers up.
 */
export const STARTUP_MS = 60;

/**
 * How many workers a run of this shape should use.
 *
 * Three things bound it, and each of them has bitten:
 *
 *   - **the cores.** `hardwareConcurrency` is what the browser will admit to,
 *     and it is a hint rather than a promise. One is left for the page, so a
 *     run does not take the interface down with it -- an eight-core machine
 *     runs seven and stays usable.
 *   - **the realisations.** Never more workers than there is work: a run of
 *     three realisations on eight workers is five builds for nothing.
 *   - **the build.** Every worker rebuilds the model, so fanning out only pays
 *     when the solving it saves is worth more than the builds it adds. With a
 *     measured build and solve time this is arithmetic; with neither it is a
 *     guess, and the guess is to fan out, because the common case is a model
 *     that builds in milliseconds.
 *
 * @param {object} o
 * @param {number} o.iterations
 * @param {number|null} [o.cores] what the machine reports; null where it does not say
 * @param {number} [o.buildMs]    what one build took, if a run has happened
 * @param {number} [o.solveMs]    what one integration took, if a run has happened
 * @param {number} [o.want]       a ceiling, from `?workers=`: the arithmetic
 *   below still applies under it
 * @param {number} [o.exact]      the number the reader chose in the dialog:
 *   that many, bounded only by the machine's cores and by the realisations
 * @returns {number} 1 means "do it here", which is always allowed
 */
export function workersFor({ iterations, cores, buildMs = null, solveMs = null, want = null, exact = null }) {
	// Chosen, not worked out: someone who asks for eight cores on a model that
	// builds slowly has been told what that costs. Never more than the cores
	// the machine reports, which is as far as the dialog counts -- all of
	// them, the one auto leaves for the page included, and past MOST_WORKERS
	// on a machine that has more -- nor more workers than realisations, since
	// a worker with nothing to integrate is a build for nothing. Where the
	// machine does not say, MOST_WORKERS stands in for it.
	if (exact != null && Number.isFinite(Number(exact))) {
		const most = Number(cores) >= 1 ? Math.floor(Number(cores)) : MOST_WORKERS;
		return Math.max(1, Math.min(most, Math.floor(Number(exact)), Math.floor(iterations)));
	}
	const machine = Math.max(1, Math.floor(Number(cores) || 1));
	// One core for the page. On a single-core machine that leaves one, which
	// is the serial path and correct.
	let n = Math.max(1, Math.min(MOST_WORKERS, machine - 1));
	if (want != null) n = Math.max(1, Math.min(MOST_WORKERS, Math.floor(want)));
	n = Math.min(n, Math.max(1, Math.floor(iterations / 2)));
	if (n <= 1) return 1;

	// Would it pay? Serial is `build + n*solve`. Parallel is the same build --
	// they all build at once -- plus the longest slice, plus what it costs to
	// have the workers at all. Fan out only where the difference is worth
	// having: a fifth, which is comfortably past the noise in either
	// measurement.
	if (buildMs != null && solveMs != null && solveMs > 0) {
		const serial = buildMs + iterations * solveMs;
		for (; n > 1; n--) {
			const parallel = STARTUP_MS * n + buildMs + Math.ceil(iterations / n) * solveMs;
			if (parallel < serial * 0.8) break;
		}
	}
	return n;
}

/** `[from, to)` per worker, as evenly as they divide. */
export function slices(iterations, workers) {
	const n = Math.max(1, Math.min(workers, iterations));
	const out = [];
	let at = 0;
	for (let w = 0; w < n; w++) {
		// The remainder goes to the first few rather than all to the last, so
		// the longest slice is one realisation longer than the shortest.
		const span = Math.floor(iterations / n) + (w < iterations % n ? 1 : 0);
		out.push({ from: at, to: at + span });
		at += span;
	}
	return out;
}

/**
 * Puts the slices back together.
 *
 * By realisation number, never by arrival: the fourth worker may well answer
 * first, and a matrix assembled in that order would be a run whose realisations
 * are shuffled -- which every statistic over it would accept without complaint,
 * because a quantile does not care what order it reads. The bands would be
 * right and the sensitivity, which pairs the i-th sample with the i-th output,
 * would be quietly wrong.
 *
 * @param {Array} parts    one result per slice, each carrying `from`/`to`
 * @param {number} iterations
 * @returns {object} the result a single run would have produced
 */
export function stitch(parts, iterations) {
	const ordered = [...parts].sort((a, b) => a.from - b.from);
	const first = ordered[0];
	const times = first.t.length;
	const series = first.values.length;

	// In the type the slices held -- float32 for a sample too large for double,
	// see `holdPrecision` -- and each slice's array let go the moment it has
	// been copied, so that a sample of a gigabyte is never held twice: the
	// slices of a series are garbage as soon as its whole exists.
	const values = [];
	for (let w = 0; w < series; w++) {
		const Held = first.values[w].constructor;
		const whole = new Held(iterations * times);
		for (const part of ordered) {
			whole.set(part.values[w], part.from * times);
			part.values[w] = null;
		}
		values.push(whole);
	}
	const samples = [];
	for (let k = 0; k < first.samples.length; k++) {
		const whole = new Float64Array(iterations);
		for (const part of ordered) whole.set(part.samples[k], part.from);
		samples.push(whole);
	}
	// Which realisations integrated. A part that does not say is taken to
	// have run all of its own.
	const ran = new Uint8Array(iterations).fill(1);
	for (const part of ordered) if (part.ran) ran.set(part.ran, part.from);

	let failed = 0;
	const trouble = [];
	let ms = 0;
	for (const part of ordered) {
		failed += part.stats.failed;
		// The first few, in realisation order -- they are sorted already,
		// because the slices are.
		for (const t of part.stats.trouble) if (trouble.length < 5) trouble.push(t);
		// The wall clock, which is the slowest worker and not the sum: the
		// whole point is that they ran at the same time.
		ms = Math.max(ms, part.stats.ms);
	}

	return {
		t: first.t,
		outputs: first.outputs,
		values,
		plan: first.plan,
		samples,
		// The same in every slice: which outputs the varied parameters are is a
		// fact about the model, not about the realisations a slice ran.
		inputs: first.inputs ?? [],
		ran,
		iterations,
		precision: first.precision ?? 'double',
		stats: { ...first.stats, failed, trouble, ms, workers: ordered.length },
	};
}

/**
 * Runs the realisations over a pool, or here when a pool is not worth it.
 *
 * @param {object} msg     the run: project, iterations, seed, latin, blocks
 * @param {object} deps
 * @param {(slice: {from: number, to: number}, on: object) => Promise<object>} deps.runSlice
 *   starts one worker on one slice; `on.progress(done, span)` as it goes
 * @param {number} deps.workers   how many to use, from `workersFor`
 * @param {(done: number, of: number) => void} [deps.onProgress]
 * @param {{aborted: boolean}} [deps.signal]
 * @param {(here: object) => object} [deps.here]  the serial path, for w === 1
 */
export async function runPool(msg, { runSlice, workers, onProgress, signal, here }) {
	const iterations = Math.max(1, Math.round(msg.iterations ?? 100));
	if (workers <= 1) {
		return here({
			...msg,
			onProgress,
			signal,
		});
	}

	const cut = slices(iterations, workers);
	// Progress is the sum of what the workers have done, which is the only
	// honest single number: they run at once and finish at different times, so
	// "realisation 400 of 1,000" means 400 have been integrated somewhere, not
	// that the run is at its 400th.
	const done = new Array(cut.length).fill(0);
	const report = () => {
		let total = 0;
		for (const d of done) total += d;
		onProgress?.(total, iterations);
	};

	const parts = await Promise.all(cut.map((slice, w) => runSlice(slice, {
		progress: (n) => { done[w] = n; report(); },
	})));
	if (signal?.aborted) return null;
	return stitch(parts, iterations);
}

/** The serial path, kept here so both routes are one call apart. */
export function runHere(msg) {
	return runProbabilistic(msg.project, {
		iterations: msg.iterations,
		seed: msg.seed,
		latin: msg.latin !== false,
		large: msg.large === true,
		keep: msg.keep,
		signal: msg.signal,
		onProgress: msg.onProgress,
	});
}
