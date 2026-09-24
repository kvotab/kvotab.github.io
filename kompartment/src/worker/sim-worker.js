/**
 * Simulation worker.
 *
 * A desktop application runs simulations on a pool of background threads. A
 * browser tab has one UI thread, so the equivalent move is to push the solve
 * into a Worker: the
 * page stays responsive and a long run can be cancelled.
 *
 * Protocol
 *   in   { type: 'run', id, project }
 *        { type: 'cancel' }
 *        { type: 'columns', id, indices }     the series of these outputs, please
 *   out  { type: 'loading', id, stage, detail }
 *        { type: 'progress', id, fraction }
 *        { type: 'done', id, payload }         every output described, no series
 *        { type: 'columns', id, indices, columns }
 *        { type: 'error', id, message, name, blockName }
 *
 * The results stay here. A run keeps only its states, and every other series is
 * worked out from them when a chart or a table asks -- so what crosses to the
 * page on `done` is the list of outputs and nothing of their values, and the
 * values the page is showing come across on request, a handful at a time. The
 * alternative, a column for every output, was 800 MB on a landscape model
 * before the page had drawn a line.
 */

import { run, Results } from '../sim/runner.js';
import { buildSystem } from '../sim/builder.js';
import { Project } from '../domain/project.js';
import { runProbabilistic, runRealization, designFor, quantiles, meanOf, medianSpread, timeMajor } from '../sim/probabilistic.js';
import { runPool, workersFor } from './prob-pool.js';
import { ranked, overTime, regressionMeasures, firstOrderIndex } from '../domain/sensitivity.js';
import { categoriesOf, classify, includeMask, statisticOf } from '../domain/categories.js';
import {
	gsaTable, gsaMain, easi, deltaMoment, mutualInformation, rsa, normalScores, averageRanks,
} from '../domain/gsa.js';
import { streamFor, uniforms } from '../domain/sample.js';
import { sortedColumn, describeSample, histogram } from '../domain/distribution.js';
import { calibrate, variablesOf } from '../sim/calibrate.js';
import { runSensitivity, elasticity } from '../sim/localsens.js';
import { checkJacobian, jacobianPattern } from '../sim/jaccheck.js';
import { isScipySolver, loadScipy, scipyReady } from '../ode/scipy.js';
import { SolverError } from '../ode/solvers/dormand-prince.js';
import { layoutSignature, datasetEntries, restoreResults } from '../io/dataset.js';

let cancelled = false;

/** The last run, kept to answer for its series. */
let last = null;

/**
 * A built system kept for the Jacobian views, keyed by the page's edit counter.
 *
 * Building one is seconds on a real assessment -- eight of them on
 * model F, which is 55,728 states -- and the two Jacobian messages
 * both want one for a model that has not changed. `rev` is the page's own
 * counter: it bumps on every edit and on nothing else, which is exactly when
 * the system stops being the model's.
 */
let lastJacobian = null;

function systemForJacobian(project, rev) {
	if (rev != null && lastJacobian?.rev === rev) return lastJacobian.system;
	// A run of the same model has already built one; there is no reason to
	// build a second.
	if (rev != null && last?.rev === rev && last.results?.system) {
		lastJacobian = { rev, system: last.results.system };
		return lastJacobian.system;
	}
	const system = buildSystem(project instanceof Project ? project : new Project(project));
	if (rev != null) lastJacobian = { rev, system };
	return system;
}

/** The last probabilistic run, so its sample can be asked about later. */
let lastProb = null;

/** The last tornado, so its table can be read for another output. */
let lastTornado = null;

/** The last sensitivity design and its runs, likewise. */
let lastGsa = null;

/**
 * The tornado read for one output: what each swung input did to it.
 *
 * Point 0 is everything at the model's values; point 2s+1 is input s at its
 * low, 2s+2 at its high. Sorted by the size of the swing, the way the chart
 * is drawn, with the inputs that moved nothing at the bottom rather than
 * dropped -- "this input does not reach this output" is an answer too.
 */
function tornadoTable(result, index, stat, at) {
	const k = Math.min(result.values.length - 1, Math.max(0, Number(index) || 0));
	const values = result.values[k];
	const times = result.t.length;
	const central = statisticOf(values, times, 0, stat, at);
	const swung = result.stats.tornado?.swung ?? [];
	const rows = swung.map((plan, s2) => {
		const e = result.plan[plan];
		return {
			k: plan,
			name: e.name,
			where: Object.values(e.index ?? {}),
			low: statisticOf(values, times, 2 * s2 + 1, stat, at),
			high: statisticOf(values, times, 2 * s2 + 2, stat, at),
			lowInput: result.samples[plan][2 * s2 + 1],
			highInput: result.samples[plan][2 * s2 + 2],
		};
	});
	for (const r of rows) {
		r.swing = Number.isFinite(r.low) && Number.isFinite(r.high) ? Math.abs(r.high - r.low) : NaN;
	}
	rows.sort((a, b) => (Number.isNaN(b.swing) ? -1 : b.swing) - (Number.isNaN(a.swing) ? -1 : a.swing));
	return { index: k, stat, at, central, rows };
}

/**
 * The workers this one has started, so a Stop can reach them.
 *
 * A message cannot: a solve is one long synchronous call, so a `cancel` sits in
 * a worker's queue until the realisation it was meant to stop has finished
 * anyway. The page terminates this worker for exactly that reason, and the
 * same applies one level down -- except that a terminated coordinator leaves
 * its children running, holding a core each and a matrix each, with nothing
 * left that can talk to them. So they are held here and killed first.
 */
const pool = new Set();

/** Thrown into the slices when a Stop arrives, so the run stops waiting. */
const STOPPED = Symbol('stopped');

function closePool() {
	for (const member of pool) {
		try { member.worker.terminate(); } catch { /* already gone, which is the aim */ }
		// Terminating a worker does not settle the promise that was waiting on
		// it -- nothing arrives, ever -- so the run would sit on a
		// `Promise.all` that can no longer be answered.
		member.abort(STOPPED);
	}
	pool.clear();
}

/**
 * What the last build and the last realisation cost, for sizing the pool.
 *
 * Every worker rebuilds the model, so fanning out pays only when the solving
 * saved is worth more than the builds added. A previous run on this worker is
 * where those two numbers come from; with none, `workersFor` guesses, and the
 * guess is right for every model that builds in milliseconds.
 */
let lastCost = { buildMs: null, solveMs: null };

/**
 * Whether this browser lets a worker start a worker.
 *
 * Safari refused until 16.4 and some embeddings still do, so this is asked
 * once, by trying it: the answer is not something to infer from a version
 * string. A machine that says no runs the job the way it always did.
 */
let nesting = null;

function canNest() {
	if (nesting != null) return nesting;
	try {
		const probe = new Worker(new URL('./sim-worker.js', import.meta.url), { type: 'module' });
		probe.terminate();
		nesting = true;
	} catch {
		nesting = false;
	}
	return nesting;
}

/**
 * How many workers this run should use, and why when it is fewer than asked.
 *
 * `msg.cores` is the reader's number from the dialog, `msg.workers` the
 * address's ceiling; with neither, the arithmetic in `workersFor` decides.
 */
function poolSize(msg) {
	const iterations = Math.max(1, Math.round(msg.iterations ?? 100));
	const asked = msg.cores ?? null;
	if (msg.workers === 1) return { workers: 1, asked, why: 'address' };
	if (!canNest()) return { workers: 1, asked, why: 'nesting' };
	const workers = workersFor({
		iterations,
		cores: (typeof navigator !== 'undefined' && navigator.hardwareConcurrency) || 1,
		buildMs: lastCost.buildMs,
		solveMs: lastCost.solveMs,
		want: msg.workers ?? null,
		exact: asked,
	});
	const why = asked == null ? 'auto'
		: workers < asked ? (workers >= iterations ? 'work' : 'cap') : null;
	return { workers, asked, why };
}

/**
 * Starts one worker on one slice and resolves with what it produced.
 *
 * This file is its own child: the slice handler above is in the same module, so
 * there is one build of the model's code and no second file to keep in step.
 * A browser that will not nest workers throws here, and the caller falls back
 * to running the whole job on this thread.
 */
function startSlice(msg, keep, slice, on) {
	return new Promise((resolve, reject) => {
		let worker;
		try {
			worker = new Worker(new URL('./sim-worker.js', import.meta.url), { type: 'module' });
		} catch (e) {
			reject(e);
			return;
		}
		const member = { worker, abort: reject };
		pool.add(member);
		const done = (fn, arg) => {
			pool.delete(member);
			try { worker.terminate(); } catch { /* it has answered; this is tidying */ }
			fn(arg);
		};
		worker.onmessage = (ev) => {
			const m = ev.data;
			if (m.type === 'prob-slice-progress') { on.progress?.(m.done, m.of); return; }
			if (m.type === 'prob-slice-done') { done(resolve, m.part); return; }
			if (m.type === 'prob-slice-error') {
				done(reject, Object.assign(new Error(m.message), { name: m.name }));
			}
		};
		worker.onerror = (e) => done(reject, new Error(e.message ?? 'a worker failed'));
		worker.postMessage({
			type: 'prob-slice',
			id: msg.id,
			project: msg.project,
			iterations: msg.iterations,
			seed: msg.seed,
			latin: msg.latin,
			blocks: keep ? [...keep] : null,
			varied: msg.varied ?? null,
			tornado: msg.tornado ?? null,
			gsa: msg.gsa ?? null,
			from: slice.from,
			to: slice.to,
		});
	});
}

// Async only because of the one thing that is: a SciPy run needs a Python
// runtime downloaded before it can start. `run()` and every solver stay
// synchronous -- solve_ivp is an ordinary blocking call once the interpreter is
// up -- so the wait happens here, outside the solve, and nothing else in the
// simulation stack had to learn about promises.
//
// The whole body is inside one try/catch for the same reason: in an async
// handler a rejection that escapes is not caught by the caller, so it would
// leave the page running with no error and no results.
/**
 * What the state vector is, as one string.
 *
 * Two systems with the same signature lay their states out identically, so a
 * solution of one is a solution of the other's shape. Compared rather than
 * trusted: the page's own test is over the model text, and this is over what
 * the model actually built into.
 *
 * The same question a saved dataset asks of the model it travels with, so it
 * is the same function -- see ../io/dataset.js. It covers the memory layout as
 * well, which this caller does not need (a model that remembers is refused for
 * reuse a few lines further down) and which costs nothing to carry.
 */
function stateSignature(system) {
	return layoutSignature(system);
}

/**
 * The `done` payload, which is the same three ways a run can arrive: solved,
 * re-evaluated from kept states, or read out of a saved dataset.
 *
 * No series in it. A run keeps only its states and every other value is worked
 * out when a chart or a table asks, so what crosses to the page is the list of
 * outputs and nothing of their values.
 */
function donePayload(results, outputs) {
	return {
		t: results.t,
		outputs: outputs.map((o) => ({
			kind: o.kind, block: o.block, nuclide: o.nuclide,
			dims: o.dims ?? [], index: o.index ?? null,
			label: o.label, unit: o.unit,
			constant: results.constantOf(o),
		})),
		columns: [],
		stats: results.stats,
		timing: results.timing,
		nuclides: results.nuclides,
		generatedSource: results.system.source,
		stateCount: results.system.layout.nstate,
		jacobian: results.jacobian,
		heldAtZero: results.heldAtZero(),
		massBalance: results.massBalance(),
	};
}

/** The band a probabilistic result is drawn as, unless the model says otherwise. */
const QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95];

/**
 * The percentiles a run's bands are drawn at.
 *
 * The model's own list where it has one -- GoldSim keeps the percentile pairs
 * with the model, and so does this -- else the default. Always with the median,
 * because the line through the band is the median and a band with no line is
 * a cloud. Sorted and deduplicated, so a pair typed twice is one pair.
 */
function percentilesFor(list) {
	const want = new Set([0.5]);
	for (const p of Array.isArray(list) ? list : QUANTILES) {
		const v = Number(p);
		if (Number.isFinite(v) && v > 0 && v < 1) want.add(v);
	}
	return [...want].sort((a, b) => a - b);
}

/**
 * The bands, the mean and the two spreads for every kept series, over the
 * realisations in `mask` -- all of them when it is null.
 *
 * Both lines the chart offers carry their own pair of intervals, because
 * neither's can be made out of the other's: `sd` is about the mean and
 * `med` about the median, and the chart draws whichever the reader's line is.
 */
function bandsOf(result, percentiles, mask) {
	const times = result.t.length;
	return result.values.map((v) => {
		const qs = quantiles(v, times, result.iterations, percentiles, mask);
		const mean = meanOf(v, times, result.iterations, mask);
		return {
			q: qs.map((b) => b.y),
			mean,
			sd: sdOf(v, times, result.iterations, mean, mask),
			// The same two intervals for the median, which cannot be made out of
			// the mean's: see `medianSpread`. The counts are not sent twice --
			// `sd.n` is the same set of realisations.
			med: medianSpread(v, times, result.iterations, 1.959964, mask),
		};
	});
}

/**
 * The spread of the realisations about their mean, at each time.
 *
 * Sent with the band because the two intervals a reader may want around a mean
 * are made of it: one standard deviation, which is where the realisations are,
 * and the standard error `sd/√n`, which is how well the mean itself is known.
 * They answer different questions and are easy to confuse, so the chart names
 * whichever it is drawing.
 *
 * The sample standard deviation, over the realisations the mask keeps and the
 * ones that are finite -- the same set `meanOf` averaged, or the two would not
 * belong to each other.
 */
function sdOf(values, times, iterations, mean, mask) {
	const out = new Float64Array(times);
	const n = new Int32Array(times);
	for (let i = 0; i < iterations; i++) {
		if (mask && !mask[i]) continue;
		const base = i * times;
		for (let j = 0; j < times; j++) {
			const v = values[base + j];
			if (!Number.isFinite(v)) continue;
			const d = v - mean[j];
			out[j] += d * d;
			n[j] += 1;
		}
	}
	for (let j = 0; j < times; j++) {
		out[j] = n[j] > 1 ? Math.sqrt(out[j] / (n[j] - 1)) : NaN;
	}
	// The count goes with it: the page turns a deviation into an error with
	// `sd/√n`, and n is not the same at every time when realisations failed.
	return { sd: out, n };
}

/** What a regression may be fitted to. Anything else is read as `none`. */
const TRANSLATIONS = new Set(['none', 'rank', 'log']);

/**
 * The output time where this series is largest on average.
 *
 * "At the peak" is the time a reader means and the one they cannot pick out of
 * a list of four hundred -- and it is not the same as the peak of any single
 * realisation, which is why it is the mean over them rather than the maximum
 * of anything. Realisations the categories have screened out are left out, as
 * they are everywhere else; a time where every realisation failed has no mean
 * and cannot be the answer.
 *
 * @param {Float64Array} values  `iterations * times`, realisation-major
 * @returns {number} an index into the output grid
 */
function peakTime(values, times, iterations, mask) {
	let best = 0;
	let most = -Infinity;
	for (let j = 0; j < times; j++) {
		let sum = 0;
		let n = 0;
		for (let i = 0; i < iterations; i++) {
			if (mask && !mask[i]) continue;
			const v = values[i * times + j];
			if (!Number.isFinite(v)) continue;
			sum += v;
			n++;
		}
		if (!n) continue;
		const mean = sum / n;
		if (mean > most) { most = mean; best = j; }
	}
	return best;
}

/** How many realisations a mask keeps. */
function kept(mask, iterations) {
	if (!mask) return iterations;
	let n = 0;
	for (let i = 0; i < mask.length; i++) if (mask[i]) n++;
	return n;
}

/**
 * Runs a design -- a sample or a tornado -- over the pool, or here.
 *
 * The one launch for both, so a tornado gets the same cores, the same progress
 * reports and the same Stop as a probabilistic run: it is the same shape of
 * job, a set of independent integrations of one built model.
 */
async function runDesign(msg) {
	const { id, project } = msg;
	const keep = Array.isArray(msg.blocks) && msg.blocks.length ? new Set(msg.blocks) : null;
	let lastPost = 0;
	const onProgress = (done, total) => {
		const now = Date.now();
		if (now - lastPost > 80 || done === total) {
			lastPost = now;
			self.postMessage({
				type: 'progress', id, fraction: done / total, at: null,
				realisation: done, of: total,
			});
		}
	};
	// A tornado's size is decided by the plan, not by a count the page
	// could know, so the pool is sized for it once the plan is known: one
	// build here tells us how many points there are. A sensitivity design
	// likewise, and its design is kept: the analysis reads it, and it is the
	// one every slice draws for itself from the same seed.
	let iterations = msg.iterations;
	let gsaDesign = null;
	if (msg.tornado || msg.gsa) {
		const p = new Project(project);
		const d = designFor(p, buildSystem(p), {
			tornado: msg.tornado ?? null, gsa: msg.gsa ?? null, varied: msg.varied ?? null, seed: msg.seed,
		});
		iterations = d.iterations;
		gsaDesign = d.gsaDesign ?? null;
	}
	const shaped = { ...msg, iterations, keep: keep ? (name) => keep.has(name) : null };
	// Said before anything is built, so the footer can say how many cores the
	// run is on from its first moment rather than only once it has finished.
	const pool = poolSize(shaped);
	self.postMessage({ type: 'pool', id, ...pool, iterations });
	return runPool(shaped, {
		workers: pool.workers,
		onProgress,
		signal: { get aborted() { return cancelled; } },
		runSlice: (slice, on) => startSlice(shaped, keep, slice, on),
		here: (only) => runProbabilistic(project, {
			iterations: only.iterations,
			seed: only.seed,
			latin: only.latin !== false,
			varied: only.varied ?? null,
			tornado: only.tornado ?? null,
			gsa: only.gsa ?? null,
			keep: only.keep,
			signal: only.signal,
			onProgress: only.onProgress,
		}),
	}).then((result) => {
		if (result && gsaDesign) result.gsaDesign = gsaDesign;
		return result;
	});
}

/**
 * One sensitivity method's table for one output, and the ranking index over
 * time for the inputs that lead it.
 *
 * The output at a design point is the same statistic a tornado reads -- the
 * peak, the final value, the lowest, or the value at a time -- and the table is
 * of that; the curves are of the value at every output time, which is what
 * says that an input governs the first century and not the rest.
 */
function gsaAnswer(result, index, stat, at) {
	const k = Math.min(result.values.length - 1, Math.max(0, Number(index) || 0));
	const values = result.values[k];
	const times = result.t.length;
	const n = result.iterations;
	const design = result.gsaDesign;
	const y = new Float64Array(n);
	for (let i = 0; i < n; i++) y[i] = statisticOf(values, times, i, stat, at);
	const table = gsaTable(design, y);
	const factors = result.stats.gsa?.factors ?? [];
	const name = (f) => {
		const e = result.plan[factors[f]?.members?.[0]];
		const group = factors[f]?.group;
		return group
			? { name: group, where: [], members: factors[f].members.map((m) => result.plan[m]?.name) }
			: { name: e?.name ?? `input ${f + 1}`, where: Object.values(e?.index ?? {}) };
	};
	const rows = table.rows.map((r) => ({ ...r, ...name(r.k) }));
	const lead = rows.filter((r) => Number.isFinite(r.values[table.rank])).slice(0, 6).map((r) => r.k);
	let curves = [];
	if (!table.failed && !table.flat && lead.length) {
		const series = lead.map(() => new Float64Array(times).fill(NaN));
		const yt = new Float64Array(n);
		for (let j = 0; j < times; j++) {
			let spread = false;
			for (let i = 0; i < n; i++) {
				yt[i] = values[i * times + j];
				if (i && yt[i] !== yt[0]) spread = true;
			}
			// A time at which nothing has reached the output yet has nothing
			// to attribute, and every index there would be 0/0.
			if (!spread) continue;
			const main = gsaMain(design, yt);
			lead.forEach((f, s) => { series[s][j] = main[f]; });
		}
		curves = lead.map((f, s) => ({ k: f, y: series[s] }));
	}
	return {
		index: k, stat, at,
		method: table.method, columns: table.columns, rank: table.rank,
		rows, pairs: table.pairs?.slice(0, 20).map((p) => ({ ...p, a: name(p.a), b: name(p.b) })) ?? null,
		failed: table.failed, flat: table.flat, curves,
	};
}

/**
 * The measures from GlobalSensitivity.jl that read any sample, for the inputs
 * a *What drove it* table lists: EASI's first-order index, Borgonovo's δ,
 * mutual information and RSA's Kolmogorov-Smirnov distance, with ten dummy
 * inputs for how large a distance chance alone gives. The same realisations as
 * the rest of the table -- the categories shown, the ones that ran.
 *
 * **δ and mutual information are read on scores, not values.** Neither
 * changes under a strictly monotone transformation -- δ of the output, mutual
 * information of either side -- so they are estimated where their estimators
 * work: δ on the output's normal scores, mutual information on ranks. On the
 * values themselves they do not: a dose that spans thirty decades across the
 * realisations has no kernel density estimate on a linear grid of 2048 points
 * (one class of them was a spike a millionth of the grid's spacing wide, and
 * δ came out at 449,816), and equal-width bins put nearly all of it in the
 * first. GlobalSensitivity.jl reads the values, and gives those numbers. EASI
 * is a share of the variance, which is not invariant, and reads the values;
 * RSA reads only the inputs' order.
 *
 * Their random numbers -- δ's bootstrap, the shuffles behind the chance level
 * of mutual information, the dummies -- come from streams of the run's seed,
 * so asking twice gives the same answer.
 */
function distributionMeasures(r, values, times, at, rows, mask) {
	const use = [];
	for (let i = 0; i < r.iterations; i++) {
		if (mask && !mask[i]) continue;
		if (Number.isFinite(values[i * times + at])) use.push(i);
	}
	const y = Float64Array.from(use, (i) => values[i * times + at]);
	const n = y.length;
	if (n < 20) return { ok: false, used: n, rows: [] };
	let flat = true;
	for (let i = 1; i < n && flat; i++) if (y[i] !== y[0]) flat = false;
	if (flat) return { ok: false, used: n, flat: true, rows: [] };
	const seed = r.stats?.seed ?? 1;
	const dummies = Array.from({ length: 10 }, (_, d) => uniforms(n, streamFor(seed, `#rsa#dummy#${d}`)));
	const columns = rows.map((row) => Float64Array.from(use, (i) => r.samples[row.k][i]));
	const split = rsa(columns, y, { dummies });
	const scores = normalScores(y);
	const yRanks = averageRanks(y);
	const out = rows.map((row, j) => {
		const x = columns[j];
		let varies = false;
		for (let i = 1; i < n && !varies; i++) if (x[i] !== x[0]) varies = true;
		if (!varies) return null;
		const name = r.plan[row.k] ? `${r.plan[row.k].name}#${row.k}` : String(row.k);
		const d = deltaMoment(x, scores, { boots: 100, next: streamFor(seed, `${name}#delta`) });
		const m = mutualInformation(averageRanks(x), yRanks, { boots: 100, next: streamFor(seed, `${name}#mi`) });
		return {
			easi: easi(x, y).s1c,
			delta: d.adjusted, deltaLow: d.low, deltaHigh: d.high,
			mi: m.mi, miBound: m.bound, miS: m.s,
			ks: split.scores[j],
		};
	});
	return {
		ok: true, used: n, rows: out,
		threshold: split.threshold, behavioural: split.behavioural,
		ksDummyMean: split.dummyMean, ksDummySd: split.dummySd,
	};
}

/** The outputs of a design result, as the page wants them described. */
function describeOutputs(result) {
	return result.outputs.map((o) => ({
		kind: o.kind, block: o.block, nuclide: o.nuclide,
		dims: o.dims ?? [], index: o.index ?? null,
		label: o.label, unit: o.unit,
	}));
}

self.onmessage = async (ev) => {
	const msg = ev.data;

	if (msg.type === 'cancel') {
		cancelled = true;
		// The workers this one started, if any. A `cancel` reaches *this*
		// worker while a pool is running -- it is awaiting messages, not
		// solving -- which is the one moment it can do something about them.
		// Left alone they would keep a core each and a matrix each with
		// nothing able to talk to them, because the page's next move is to
		// terminate this worker.
		closePool();
		// Said so the page knows the children are gone and it is safe to
		// terminate. A deterministic run never answers this, because it is one
		// long synchronous call -- which is why terminating exists.
		self.postMessage({ type: 'cancelled' });
		return;
	}

	if (msg.type === 'columns') {
		// For the run the page is looking at, and no other: a request that
		// outlived its run is answered with nothing, and the page ignores it.
		if (!last || last.id !== msg.id) return;
		// Inside a try, like the run itself: an index past the outputs, or a
		// series that will not evaluate, used to escape as `worker.onerror`
		// and put the page into its failed-run state with no run in flight.
		try {
			const indices = (Array.isArray(msg.indices) ? msg.indices : [])
				.filter((i) => Number.isInteger(i) && i >= 0 && i < last.outputs.length);
			const outputs = indices.map((i) => last.outputs[i]);
			const columns = last.results.seriesMany(outputs);
			self.postMessage({ type: 'columns', id: msg.id, indices, columns },
				columns.map((c) => c.buffer));
		} catch (e) {
			self.postMessage({ type: 'error', id: msg.id, name: e.name, message: e.message });
		}
		return;
	}

	// A probabilistic run: the same solve, many times over the model's
	// distributions. It lives here for the reason every run does -- a thousand
	// integrations on the page's own thread is a page that has stopped
	// answering -- and it reports realisations rather than a fraction of one,
	// because that is the thing that is happening.
	// One slice of a probabilistic run, for a worker this worker started.
	//
	// The same runner, told which realisations are its own. It draws the whole
	// design from the seed and integrates only its range, so what comes back is
	// bit for bit what a serial run would have put at those positions -- see
	// ./prob-pool.js.
	if (msg.type === 'prob-slice') {
		cancelled = false;
		const { id } = msg;
		try {
			const keep = Array.isArray(msg.blocks) && msg.blocks.length
				? new Set(msg.blocks) : null;
			let lastPost = 0;
			const r = runProbabilistic(msg.project, {
				iterations: msg.iterations,
				seed: msg.seed,
				latin: msg.latin !== false,
				varied: msg.varied ?? null,
				tornado: msg.tornado ?? null,
				gsa: msg.gsa ?? null,
				keep: keep ? (name) => keep.has(name) : null,
				range: { from: msg.from, to: msg.to },
				signal: { get aborted() { return cancelled; } },
				onProgress: (done, total) => {
					const now = Date.now();
					if (now - lastPost > 80 || done === total) {
						lastPost = now;
						self.postMessage({ type: 'prob-slice-progress', id, done, of: total });
					}
				},
			});
			// Transferred, not copied: a slice is the matrix this worker holds
			// and there is no reason for two of it to exist while it crosses.
			const buffers = [...r.values, ...r.samples].map((a) => a.buffer);
			self.postMessage({
				type: 'prob-slice-done',
				id,
				part: {
					t: r.t,
					outputs: r.outputs,
					values: r.values,
					samples: r.samples,
					plan: r.plan,
					from: r.from,
					to: r.to,
					stats: r.stats,
				},
			}, buffers);
		} catch (e) {
			self.postMessage({
				type: 'prob-slice-error', id,
				name: e.name ?? 'Error', message: e.message ?? String(e),
			});
		}
		return;
	}

	if (msg.type === 'probabilistic') {
		cancelled = false;
		const { id, project } = msg;
		try {
			self.postMessage({ type: 'loading', id, stage: 'building' });
			const result = await runDesign(msg);
			if (!result) return;

			// The bands, not the matrix: a thousand realisations of a hundred
			// series is 280 MB and the page draws five curves from it. The
			// matrix stays here, and `prob-matrix` fetches what an export or
			// a sensitivity needs out of it -- transposed, and narrowed to
			// float32, so what crosses is the answer rather than the sample.
			//
			// The categories the model carries are applied at once, so a run
			// lands already sorted; the mask they make is what every later
			// question -- bands, sensitivity, summary -- is asked over.
			const percentiles = percentilesFor(project?.simulation?.percentiles);
			const categories = categoriesOf(project);
			const sorted = categories.length ? classify(categories, result) : null;
			const mask = sorted ? includeMask(categories, sorted.member) : null;
			lastProb = { id, result, percentiles, categories, member: sorted?.member ?? null, mask };
			self.postMessage({
				type: 'probabilistic-done',
				id,
				payload: {
					t: result.t,
					quantiles: percentiles,
					outputs: describeOutputs(result),
					bands: bandsOf(result, percentiles, mask),
					iterations: result.iterations,
					stats: result.stats,
					plan: result.plan.map((e) => ({
						name: e.name, index: e.index, kind: e.spec.kind,
					})),
					screen: sorted ? {
						counts: sorted.counts, missing: sorted.missing,
						kept: kept(mask, result.iterations),
					} : null,
				},
			});
		} catch (e) {
			// A Stop is not a fault. `closePool` rejects the slices that are
			// still waiting so the run stops waiting on workers that are gone,
			// and what arrives here is that rejection rather than anything
			// wrong with the model.
			if (e === STOPPED || cancelled) return;
			self.postMessage({
				type: 'error', id, name: e.name ?? 'Error',
				message: e.message ?? String(e), hint: e.hint ?? null,
			});
		}
		return;
	}

	// The bands again, at other percentiles or over other categories. Cheap:
	// a sort per time per series over a matrix that is already here.
	if (msg.type === 'prob-bands') {
		if (!lastProb || lastProb.id !== msg.id) {
			self.postMessage({ type: 'prob-bands', id: msg.id, gone: true });
			return;
		}
		try {
			if (msg.percentiles) lastProb.percentiles = percentilesFor(msg.percentiles);
			self.postMessage({
				type: 'prob-bands', id: msg.id,
				quantiles: lastProb.percentiles,
				bands: bandsOf(lastProb.result, lastProb.percentiles, lastProb.mask),
			});
		} catch (e) {
			self.postMessage({ type: 'error', id: msg.id, name: e.name, message: e.message });
		}
		return;
	}

	// Done with them. The reader has said so, and a sample is the one large
	// thing this worker keeps between runs: dropping the reference here is
	// what actually returns the memory, since the page's own copy is only the
	// bands and every question about the realisations is answered from here.
	if (msg.type === 'prob-forget') {
		lastProb = null;
		return;
	}

	// The realisations sorted into categories, and everything redrawn over
	// the ones that are kept. See ../domain/categories.js.
	if (msg.type === 'prob-categories') {
		if (!lastProb || lastProb.id !== msg.id) {
			self.postMessage({ type: 'prob-categories', id: msg.id, gone: true });
			return;
		}
		try {
			const categories = categoriesOf({ simulation: { categories: msg.categories } });
			const { result } = lastProb;
			const sorted = categories.length ? classify(categories, result) : null;
			lastProb.categories = categories;
			lastProb.member = sorted?.member ?? null;
			lastProb.mask = sorted ? includeMask(categories, sorted.member) : null;
			self.postMessage({
				type: 'prob-categories', id: msg.id,
				screen: sorted ? {
					counts: sorted.counts, missing: sorted.missing,
					kept: kept(lastProb.mask, result.iterations),
				} : null,
				quantiles: lastProb.percentiles,
				bands: bandsOf(result, lastProb.percentiles, lastProb.mask),
			});
		} catch (e) {
			self.postMessage({ type: 'error', id: msg.id, name: e.name, message: e.message });
		}
		return;
	}

	// One output at one time, as a distribution: the sorted column, so the
	// page can answer value-to-probability and back without asking again, and
	// the summary statistics over it. See ../domain/distribution.js.
	if (msg.type === 'prob-summary') {
		if (!lastProb || lastProb.id !== msg.id) {
			self.postMessage({ type: 'prob-summary', id: msg.id, gone: true });
			return;
		}
		try {
			const { result, mask } = lastProb;
			const k = Number(msg.index);
			const values = result.values[k];
			if (!values) return;
			const times = result.t.length;
			const at = Math.min(times - 1, Math.max(0, Number(msg.at ?? times - 1)));
			const sorted = sortedColumn(values, times, result.iterations, at, mask);
			const column = Float64Array.from(sorted);
			// Which category each kept realisation is in, in the column's
			// order, so the page can colour a histogram by it.
			self.postMessage({
				type: 'prob-summary', id: msg.id, index: k, at, t: result.t,
				summary: describeSample(sorted),
				histogram: histogram(sorted),
				column,
				of: result.iterations,
			}, [column.buffer]);
		} catch (e) {
			self.postMessage({ type: 'error', id: msg.id, name: e.name, message: e.message });
		}
		return;
	}

	// Several outputs at one time, each as a histogram: what the Chart tab
	// draws in its distribution mode.
	//
	// `prob-summary` above answers the same question for *one* output and
	// carries the sorted column with it, because that dialog answers
	// value-to-probability from it without asking again. This one is for a
	// picture of several at once, so it sends the bins and not the column --
	// twelve columns of a thousand realisations is 96 kB of numbers nothing on
	// the page would read.
	if (msg.type === 'prob-hist') {
		if (!lastProb || lastProb.id !== msg.id) {
			self.postMessage({ type: 'prob-hist', id: msg.id, gone: true });
			return;
		}
		try {
			const { result, mask } = lastProb;
			const times = result.t.length;
			const at = msg.at === 'peak'
				? peakTime(result.values[Number(msg.indices?.[0] ?? 0)] ?? new Float64Array(0),
					times, result.iterations, mask)
				: Math.min(times - 1, Math.max(0, Number(msg.at ?? times - 1)));
			const items = [];
			for (const raw of msg.indices ?? []) {
				const k = Number(raw);
				const values = result.values[k];
				if (!values) continue;
				const sorted = sortedColumn(values, times, result.iterations, at, mask);
				items.push({
					index: k,
					summary: describeSample(sorted),
					// How many bins and what they are spaced by are the
					// reader's, not this function's: the shape a sample
					// appears to have depends on both, and neither can be
					// guessed well for every output at once.
					histogram: histogram(sorted, msg.bins ?? null, msg.scale ?? 'auto'),
				});
			}
			self.postMessage({
				type: 'prob-hist', id: msg.id, at, t: result.t, items, of: result.iterations,
			});
		} catch (e) {
			self.postMessage({ type: 'error', id: msg.id, name: e.name, message: e.message });
		}
		return;
	}

	// The realisations themselves, paired: what a scatter plot is made of.
	//
	// `prob-summary` and `prob-hist` both answer with the column *sorted*,
	// because a distribution is a shape and the order is not part of it. A
	// scatter is the opposite: a point is one realisation's x against the same
	// realisation's y, and sorting either column destroys exactly the thing
	// being looked at. So this sends them in realisation order, screened the
	// same way everything else is, and the page pairs them by position.
	if (msg.type === 'prob-points') {
		if (!lastProb || lastProb.id !== msg.id) {
			self.postMessage({ type: 'prob-points', id: msg.id, gone: true });
			return;
		}
		try {
			const { result, mask } = lastProb;
			const times = result.t.length;
			const at = Math.min(times - 1, Math.max(0, Number(msg.at ?? times - 1)));
			// Which realisations every column agrees on, once: a point needs
			// both halves, so a realisation missing either is missing from all
			// of the series rather than from some.
			const rows = [];
			for (let i = 0; i < result.iterations; i++) {
				if (mask && !mask[i]) continue;
				rows.push(i);
			}
			const take = (k) => {
				const values = result.values[Number(k)];
				if (!values) return null;
				const out = new Float64Array(rows.length);
				for (let j = 0; j < rows.length; j++) out[j] = values[rows[j] * times + at];
				return out;
			};
			const x = take(msg.x);
			if (!x) { self.postMessage({ type: 'prob-points', id: msg.id, gone: true }); return; }
			const ys = [];
			const move = [x.buffer];
			for (const k of msg.ys ?? []) {
				const v = take(k);
				if (!v) continue;
				ys.push({ index: Number(k), values: v });
				move.push(v.buffer);
			}
			self.postMessage({
				type: 'prob-points', id: msg.id, at, t: result.t,
				x: { index: Number(msg.x), values: x }, ys, of: result.iterations,
			}, move);
		} catch (e) {
			self.postMessage({ type: 'error', id: msg.id, name: e.name, message: e.message });
		}
		return;
	}

	// One realisation, run again as an ordinary run -- every series of it,
	// not only the ones the band kept. See `runRealization`.
	if (msg.type === 'replay') {
		cancelled = false;
		const { id, project } = msg;
		try {
			self.postMessage({ type: 'loading', id, stage: 'building' });
			const started = Date.now();
			const r = runRealization(project, {
				seed: msg.seed, iterations: msg.iterations, latin: msg.latin !== false,
				varied: msg.varied ?? null, tornado: msg.tornado ?? null,
				signal: { get aborted() { return cancelled; } },
			}, msg.index);
			const { results } = r;
			results.timing = { ...results.timing, totalMs: Date.now() - started };
			const outputs = results.outputs();
			last = { id, results, outputs, rev: msg.rev ?? null };
			self.postMessage({
				type: 'done', id,
				replayed: {
					index: r.index, iterations: r.iterations, seed: msg.seed,
					tornado: !!msg.tornado,
					values: r.values,
				},
				payload: donePayload(results, outputs),
			});
		} catch (e) {
			if (cancelled) return;
			self.postMessage({
				type: 'error', id, name: e.name ?? 'Error',
				message: e.message ?? String(e), hint: e.hint ?? null,
			});
		}
		return;
	}

	// A tornado: every varying input swung on its own, low and high, with the
	// rest held. The same pool, the same Stop, and the table is read out of
	// the result the way a category reads a series -- so it can be asked again
	// for another output or another time without running anything.
	if (msg.type === 'tornado') {
		cancelled = false;
		const { id } = msg;
		try {
			self.postMessage({ type: 'loading', id, stage: 'building' });
			const result = await runDesign({ ...msg, tornado: msg.tornado ?? { low: 0.05, high: 0.95 } });
			if (!result) return;
			lastTornado = { id, result };
			self.postMessage({
				type: 'tornado', id,
				outputs: describeOutputs(result),
				t: result.t,
				points: result.iterations,
				stats: result.stats,
				table: tornadoTable(result, msg.index ?? 0, msg.stat ?? 'max', msg.at ?? 0),
			});
		} catch (e) {
			if (e === STOPPED || cancelled) return;
			self.postMessage({
				type: 'error', id, name: e.name ?? 'Error',
				message: e.message ?? String(e), hint: e.hint ?? null,
			});
		}
		return;
	}

	// A global sensitivity design: the same pool and the same Stop as a
	// tornado, and a table read out of the runs, which can be asked again for
	// another output or another reading without running anything.
	if (msg.type === 'gsa') {
		cancelled = false;
		const { id } = msg;
		try {
			self.postMessage({ type: 'loading', id, stage: 'building' });
			const result = await runDesign({ ...msg });
			if (!result) return;
			lastGsa = { id, result };
			// Opened on the line the chart shows, when the design kept it, so
			// the dialog does not arrive on one output and move to another.
			const wanted = msg.wantLabel ? result.outputs.findIndex((o) => o.label === msg.wantLabel) : -1;
			self.postMessage({
				type: 'gsa', id,
				outputs: describeOutputs(result),
				t: result.t,
				points: result.iterations,
				stats: result.stats,
				answer: gsaAnswer(result, wanted >= 0 ? wanted : (msg.index ?? 0), msg.stat ?? 'max', msg.at ?? 0),
			});
		} catch (e) {
			if (e === STOPPED || cancelled) return;
			self.postMessage({
				type: 'error', id, name: e.name ?? 'Error',
				message: e.message ?? String(e), hint: e.hint ?? null,
			});
		}
		return;
	}

	if (msg.type === 'gsa-table') {
		if (!lastGsa || lastGsa.id !== msg.id) {
			self.postMessage({ type: 'gsa-table', id: msg.id, gone: true });
			return;
		}
		try {
			self.postMessage({
				type: 'gsa-table', id: msg.id,
				answer: gsaAnswer(lastGsa.result, msg.index ?? 0, msg.stat ?? 'max', msg.at ?? 0),
			});
		} catch (e) {
			self.postMessage({ type: 'error', id: msg.id, name: e.name, message: e.message });
		}
		return;
	}

	if (msg.type === 'tornado-table') {
		if (!lastTornado || lastTornado.id !== msg.id) {
			self.postMessage({ type: 'tornado-table', id: msg.id, gone: true });
			return;
		}
		try {
			self.postMessage({
				type: 'tornado-table', id: msg.id,
				table: tornadoTable(lastTornado.result, msg.index ?? 0, msg.stat ?? 'max', msg.at ?? 0),
			});
		} catch (e) {
			self.postMessage({ type: 'error', id: msg.id, name: e.name, message: e.message });
		}
		return;
	}

	// dy/dp: the states and their sensitivities in one solve. Here rather than
	// on the page for the reason every solve is -- it augments the state vector
	// by one copy per parameter, so it is the largest integration the model
	// ever does.
	// The generated Jacobian against finite differences of the generated
	// derivative. Here rather than on the page because it is two evaluations of
	// the whole model per column: nothing on a bundled example, and minutes on
	// an assessment, which is exactly the model somebody wants to check.
	// The picture: the sparsity pattern, which is structural and costs the
	// build and nothing else. Separate from the check below because it is the
	// half somebody opening the view wants immediately.
	if (msg.type === 'jacobian-pattern') {
		const { id, project } = msg;
		try {
			self.postMessage({ type: 'loading', id, stage: 'building' });
			const system = systemForJacobian(project, msg.rev);
			self.postMessage({ type: 'jacobian-pattern', id, report: jacobianPattern(project, { system }) });
		} catch (e) {
			self.postMessage({
				type: 'error', id, name: e.name ?? 'Error',
				message: e.message ?? String(e), hint: e.hint ?? null,
			});
		}
		return;
	}

	// The check: an evaluation of the whole model per colour group and per
	// sampled column, at four states. Seconds on an assessment, so it reports
	// how far along it is.
	if (msg.type === 'jacobian-check') {
		const { id, project } = msg;
		try {
			self.postMessage({ type: 'loading', id, stage: 'building' });
			const system = systemForJacobian(project, msg.rev);
			let lastPost = 0;
			const report = checkJacobian(project, {
				system,
				onProgress: (done, total) => {
					const now = Date.now();
					if (now - lastPost > 100) {
						lastPost = now;
						self.postMessage({ type: 'progress', id, fraction: done / total, at: null });
					}
				},
			});
			self.postMessage({ type: 'jacobian-check', id, report });
		} catch (e) {
			self.postMessage({
				type: 'error', id, name: e.name ?? 'Error',
				message: e.message ?? String(e), hint: e.hint ?? null,
			});
		}
		return;
	}

	// Solving for the parameter values that put the endpoints where somebody
	// says they should be. Every evaluation is a whole integration, so this is
	// the one question that can take minutes -- it reports after each one and
	// stops on the same flag every run does.
	if (msg.type === 'optimise') {
		cancelled = false;
		const { id, project } = msg;
		try {
			self.postMessage({ type: 'loading', id, stage: 'building' });
			let lastPost = 0;
			const result = calibrate(project, {
				targets: msg.targets,
				variables: msg.variables,
				method: msg.method,
				maxEvals: msg.maxEvals,
				seed: msg.seed,
				signal: { get aborted() { return cancelled; } },
				onProgress: (p) => {
					const now = Date.now();
					// Every evaluation is reported, but not every one is sent:
					// a fast model is thousands a second and the page can draw
					// twelve. The *best* is carried on each one that goes, so
					// nothing that matters is thinned away.
					if (now - lastPost < 80) return;
					lastPost = now;
					self.postMessage({ type: 'optimise-progress', id, ...p });
				},
			});
			self.postMessage({ type: 'optimise', id, ok: true, result });
		} catch (e) {
			self.postMessage({
				type: 'optimise', id, ok: false,
				name: e.name ?? 'Error', message: e.message ?? String(e),
			});
		}
		return;
	}

	// What a model can be asked to vary: every parameter slot, whether or not
	// it carries a distribution.
	if (msg.type === 'variables') {
		try {
			self.postMessage({ type: 'variables', id: msg.id, ok: true,
				variables: variablesOf(msg.project) });
		} catch (e) {
			self.postMessage({ type: 'variables', id: msg.id, ok: false,
				name: e.name ?? 'Error', message: e.message ?? String(e) });
		}
		return;
	}

	if (msg.type === 'local-sensitivity') {
		cancelled = false;
		const { id, project } = msg;
		try {
			self.postMessage({ type: 'loading', id, stage: 'building' });
			let lastPost = 0;
			const r = runSensitivity(project, {
				parameters: msg.parameters,
				signal: { get aborted() { return cancelled; } },
				onProgress: (fraction) => {
					const now = Date.now();
					if (now - lastPost > 80) {
						lastPost = now;
						self.postMessage({ type: 'progress', id, fraction, at: null });
					}
				},
			});
			// Elasticities rather than raw derivatives: `dy/dp` carries the
			// units of both and cannot be compared between two parameters, and
			// comparing them is the whole question.
			const which = msg.states && msg.states.length
				? r.states.map((s, k) => k).filter((k) => msg.states.includes(r.states[k].name))
				: r.states.map((s, k) => k);
			self.postMessage({
				type: 'local-sensitivity',
				id,
				t: r.t,
				chosen: r.chosen,
				stats: r.stats,
				states: which.map((k) => ({
					name: r.states[k].name,
					y: r.y[k],
					sens: r.sens.map((block) => block[k]),
					elasticity: r.sens.map((block, j) => elasticity(r.y[k], block[k], r.chosen[j].value)),
				})),
			});
		} catch (e) {
			self.postMessage({
				type: 'error', id, name: e.name ?? 'Error',
				message: e.message ?? String(e), hint: e.hint ?? null,
			});
		}
		return;
	}

	// Which inputs drove one output, from the sample the last probabilistic run
	// drew. Computed here and on request rather than with the run: it is a pass
	// per output time over every input, and the page asks about one series at a
	// time.
	if (msg.type === 'sensitivity') {
		// Answered, even when the answer is "that sample is gone". A silent
		// `return` here left the page waiting for a reply it had no way to
		// know would never come, and the button that asked did nothing at
		// all -- the same shape as the export that used to sit on a
		// `columns` batch nobody was going to send.
		if (!lastProb || lastProb.id !== msg.id) {
			self.postMessage({ type: 'sensitivity', id: msg.id, gone: true });
			return;
		}
		try {
			const r = lastProb.result;
			const k = Number(msg.index);
			const values = r.values[k];
			if (!values) return;
			const times = r.t.length;
			const { mask } = lastProb;
			// `at: 'peak'` is "wherever this output is largest on average",
			// which is the time a reader means by "at the peak" and could not
			// pick out of a list of four hundred. Worked out here because the
			// matrix is here: the mean over the realisations at each time, and
			// the time that maximises it.
			const at = msg.at === 'peak'
				? peakTime(values, times, r.iterations, mask)
				: Math.min(times - 1, Math.max(0, Number(msg.at ?? times - 1)));
			const rows = ranked(r.samples, values, times, r.iterations, at,
				{ most: msg.most ?? 20, mask });
			// The over-time shape for the few that matter, which is the chart
			// Ecolego draws: an input that governs the first century and not
			// the next ten thousand years is a thing one number cannot say.
			const curves = rows.slice(0, 6).map((row) => ({
				k: row.k,
				y: overTime(r.samples[row.k], values, times, r.iterations, { mask }),
			}));
			// The regression family and the first-order index, at this time.
			// One inverse of a (K+1)-wide matrix; on the largest sample here
			// (617 inputs) that is under a second, and it is done for the time
			// on screen rather than for all of them. Past a few thousand
			// inputs it is declined rather than attempted.
			let measures = null;
			if (r.samples.length <= 3000) {
				const y = new Float64Array(r.iterations);
				for (let i = 0; i < r.iterations; i++) y[i] = values[i * times + at];
				const translate = TRANSLATIONS.has(msg.translate) ? msg.translate : 'none';
				const reg = regressionMeasures(r.samples, y, { translate, mask });
				measures = {
					ok: reg.ok, used: reg.used, r2: reg.r2, translate,
					dropped: reg.dropped ?? 0,
					src: rows.map((row) => reg.src[row.k]),
					b: rows.map((row) => reg.b[row.k]),
					pcc: rows.map((row) => reg.pcc[row.k]),
					s1: rows.map((row) => firstOrderIndex(r.samples[row.k], y, { mask })),
				};
			}
			const distribution = msg.family === 'distribution'
				? distributionMeasures(r, values, times, at, rows, mask) : null;
			self.postMessage({
				type: 'sensitivity',
				id: msg.id,
				index: k,
				at,
				t: r.t,
				rows: rows.map((row) => ({
					...row,
					name: r.plan[row.k].name,
					where: Object.values(r.plan[row.k].index ?? {}),
				})),
				curves,
				measures,
				distribution,
				kept: kept(mask, r.iterations),
			});
		} catch (e) {
			self.postMessage({ type: 'error', id: msg.id, name: e.name, message: e.message });
		}
		return;
	}

	// What a probabilistic result holds, for several series at once, in the
	// shape a result file wants: every run of them, their mean, or one named
	// run.
	//
	// Answered here rather than on the page because of what it saves. The mean
	// of fifty series over a thousand realisations is fifty columns of four
	// hundred numbers; the matrix those came from is fifty thousand of them.
	// Sending the matrix so the page could average it would move a thousand
	// times what the answer weighs.
	//
	// For the matrix itself there are two changes, both also about size. It is
	// stored one iteration at a time -- `v[i * times + j]` -- and a result file
	// stores it one *time* at a time, realisations fastest, so it is
	// transposed; and it is narrowed to float32, which halves what crosses and
	// what is then held while the file is built. Doing either after the copy
	// would mean holding both.
	if (msg.type === 'prob-matrix') {
		if (!lastProb || lastProb.id !== msg.id) {
			self.postMessage({ type: 'prob-matrix', id: msg.id, indices: [], matrices: [],
				gone: true });
			return;
		}
		try {
			const { result } = lastProb;
			const times = result.t.length;
			const iterations = result.iterations;
			const indices = (Array.isArray(msg.indices) ? msg.indices : [])
				.filter((k) => Number.isInteger(k) && k >= 0 && k < result.values.length);
			const want = msg.want ?? 'all';
			// Clamped rather than refused: a realisation number is a thing
			// somebody typed, and the run it names either exists or the nearest
			// one that does is what they meant.
			const one = want === 'all' || want === 'mean'
				? -1
				: Math.min(iterations - 1, Math.max(0, Math.round(Number(want)) || 0));
			let matrices;
			if (want === 'all') {
				matrices = indices.map((k) => timeMajor(result.values[k], times, iterations));
			} else if (want === 'mean') {
				matrices = indices.map((k) => meanOf(result.values[k], times, iterations));
			} else {
				matrices = indices.map(
					(k) => Float64Array.from(result.values[k].subarray(one * times, (one + 1) * times)));
			}
			self.postMessage(
				{ type: 'prob-matrix', id: msg.id, indices, matrices, times, iterations,
					want, realisation: one },
				matrices.map((m) => m.buffer),
			);
		} catch (e) {
			self.postMessage({ type: 'error', id: msg.id, name: e.name, message: e.message });
		}
		return;
	}

	// The same model solved again, when the part of it that decides the states
	// has not changed.
	//
	// `Results` keeps the trajectory and nothing else: every expression, flux
	// and parameter series is worked out from `(t, y)` when the page asks for
	// it. So an edit that cannot move `y(t)` -- a dose read off a well
	// concentration, a parameter only that dose reads -- needs the system
	// rebuilt, because the generated code has changed, and does not need a
	// single step taken. The page decides whether that holds; see
	// `integrationFingerprint`. Here the check is structural and hard: if the
	// state layout has moved at all, the old rows are not rows of this system
	// and the answer is a full run.
	// --- saving a run to a file, and reading one back ----------------------
	//
	// The states live here, not on the page: a run keeps `(t, y)` and the page
	// holds only the columns it has asked for. So the file is written from
	// here, and opening one restores it here -- which is also what makes the
	// reopened run a *live* one, answering for any series later, exactly as a
	// fresh solve does.

	if (msg.type === 'dataset') {
		// For the run the page is looking at, and no other -- the same rule
		// `columns` follows, and for the same reason.
		if (!last || last.id !== msg.id) {
			self.postMessage({ type: 'dataset', id: msg.id, ok: false, why: 'that run is gone' });
			return;
		}
		try {
			// The page sends the model, and refuses to ask at all unless it is
			// the model this run was made from -- so what goes into the archive
			// is the editor's own text, layout and colours included, rather
			// than the normalised `Project` this worker happens to hold.
			const parts = datasetEntries({
				project: msg.project,
				results: last.results,
				inner: msg.inner ?? 'model.json',
				stamp: msg.stamp ?? null,
				log: Array.isArray(msg.log) ? msg.log : null,
			});
			// Handed over rather than copied: the trajectory of a large model
			// is eighty megabytes, and structured-cloning it to the page only
			// to write it into a file would double that for no reason. The
			// buffers are this worker's own -- built a line ago by
			// `datasetEntries` -- so nothing here is left detached.
			self.postMessage({ type: 'dataset', id: msg.id, ok: true, parts },
				parts.map((e) => e.bytes.buffer));
		} catch (e) {
			self.postMessage({
				type: 'dataset', id: msg.id, ok: false,
				why: e.message ?? String(e),
			});
		}
		return;
	}

	if (msg.type === 'open-dataset') {
		cancelled = false;
		const { id, project, data } = msg;
		try {
			self.postMessage({ type: 'loading', id, stage: 'building' });
			const started = Date.now();
			// Built from the model in the archive, then checked against what
			// the archive says its numbers mean. `restoreResults` is where the
			// refusal lives; see ../io/dataset.js for why it is not optional.
			const system = buildSystem(new Project(project));
			const results = restoreResults({
				project: new Project(project), system, data, Results,
			});
			results.timing = {
				...(data.meta.timing ?? {}), buildMs: Date.now() - started, opened: true,
			};
			const outputs = results.outputs();
			last = { id, results, outputs, rev: msg.rev ?? null };
			self.postMessage({
				type: 'done', id, opened: true, payload: donePayload(results, outputs),
				// The account the archive carries of the run that made it.
				log: Array.isArray(data.meta.log) ? data.meta.log : null,
			});
		} catch (e) {
			self.postMessage({
				type: 'error', id, name: e.name ?? 'Results',
				message: e.message ?? String(e), blockName: null,
				hint: 'The model in the file opens on its own — press Open again '
					+ 'and it will load without the stored run.',
			});
		}
		return;
	}

	if (msg.type === 're-evaluate') {
		cancelled = false;
		const { id, project } = msg;
		try {
			if (!last) { self.postMessage({ type: 'reused', id, ok: false, why: 'nothing kept' }); return; }
			self.postMessage({ type: 'loading', id, stage: 'building' });
			const started = Date.now();
			const kept = last.results;
			const system = buildSystem(new Project(project));
			// The same refusal the page makes, from the other side. A block that
			// remembers accumulates its history *during* the integration, and a
			// system built fresh has none -- so its peak, its mean-from-a-year
			// and its value-a-century-ago would all be answered from an empty
			// history. Checked against what was built rather than what the
			// model said, which is the point of doing it again here.
			if (system.memory?.length || kept.system.memory?.length) {
				self.postMessage({ type: 'reused', id, ok: false, why: 'the model remembers' });
				return;
			}
			const was = stateSignature(kept.system);
			const now = stateSignature(system);
			if (was !== now) {
				// Not an error: the page's test is over the model and this one
				// is over what the model built into, and the second is the one
				// that decides. Reported so the page can run properly instead.
				self.postMessage({ type: 'reused', id, ok: false, why: 'the states moved' });
				return;
			}
			const results = new Results({
				project: new Project(project),
				system,
				solution: { t: kept.t, y: kept.y, stats: kept.stats },
				timing: { ...kept.timing, buildMs: Date.now() - started, reused: true },
			});
			const outputs = results.outputs();
			last = { id, results, outputs, rev: msg.rev ?? null };
			self.postMessage({
				type: 'done', id, reused: true, payload: donePayload(results, outputs),
			});
		} catch (e) {
			// A model that will not build is a model that will not build --
			// reported as it would be from a run, since that is what the page
			// would have got had it not tried to save the solve.
			self.postMessage({
				type: 'error', id, name: e.name ?? 'Error',
				message: e.message ?? String(e), blockName: e.blockName ?? null,
				hint: e.hint ?? null,
			});
		}
		return;
	}

	if (msg.type !== 'run') return;

	cancelled = false;
	const { id, project } = msg;

	try {
		if (isScipySolver(project?.simulation?.solver) && !scipyReady()) {
			await loadScipy({
				onProgress: (stage, detail) => self.postMessage({
					type: 'loading', id, stage, detail,
				}),
			});
			// Cancelling during a 22 MB download should not then run the model.
			// Reported in the solvers' own words, so that Stop reads the same
			// whether it was pressed during the download or during the solve.
			if (cancelled) throw new SolverError('Simulation aborted', 0);
		}

		// Building the system -- generating the derivative, the tangent
		// function and the sparsity pattern -- happens inside `run` before a
		// single step is taken, and on a large model that is seconds. Said,
		// because a bar at 0% and a page that has gone quiet look the same
		// from the outside. The first progress report clears it.
		self.postMessage({ type: 'loading', id, stage: 'building' });
		let lastPost = 0;
		const results = run(project, {
			signal: { get aborted() { return cancelled; } },
			// The build is over and the solver has begun. Until the first step
			// lands there is still nothing to put a number on -- on a stiff
			// model of ten thousand states that can be another few seconds --
			// so the bar stays indeterminate and only the word changes.
			onStage: (stage) => self.postMessage({ type: 'loading', id, stage }),
			onProgress: (fraction, at) => {
				const now = Date.now();
				if (now - lastPost > 80) {
					lastPost = now;
					self.postMessage({ type: 'progress', id, fraction, at });
				}
			},
		});

		// What crosses to the page is the list of outputs, not their series:
		// those are worked out here when the page asks for the ones it is
		// showing (`columns`, above). A constant -- a parameter -- travels
		// as its one value, and the page fills a column from it if and when
		// it charts it.
		const outputs = results.outputs();
		last = { id, results, outputs, rev: msg.rev ?? null };

		const payload = {
			t: results.t,
			outputs: outputs.map((o) => ({
				kind: o.kind, block: o.block, nuclide: o.nuclide,
				// dims and index carry which index combination this line is,
				// which is what the chart's filters select on.
				dims: o.dims ?? [], index: o.index ?? null,
				label: o.label, unit: o.unit,
				constant: results.constantOf(o),
			})),
			columns: [],
			stats: results.stats,
			timing: results.timing,
			nuclides: results.nuclides,
			generatedSource: results.system.source,
			stateCount: results.system.layout.nstate,
			jacobian: results.jacobian,
			heldAtZero: results.heldAtZero(),
			massBalance: results.massBalance(),
		};

		// What that run cost, for sizing a pool later. Every worker in a pool
		// rebuilds the model, so whether fanning out pays is arithmetic over
		// these two -- and a deterministic run has just measured both. See
		// `workersFor`.
		lastCost = {
			buildMs: results.timing?.buildMs ?? null,
			solveMs: results.timing?.solveMs ?? null,
		};

		self.postMessage({ type: 'done', id, payload });
	} catch (e) {
		self.postMessage({
			type: 'error',
			id,
			name: e.name ?? 'Error',
			message: e.message ?? String(e),
			blockName: e.blockName ?? null,
			hint: e.hint ?? null,
		});
	}
};
