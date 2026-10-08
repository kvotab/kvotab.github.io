/**
 * A model and the run it produced, in one file.
 *
 * Saving a model saves what will be computed. This saves what *was*: the
 * trajectory, so that a result can be closed and opened again -- sent to
 * somebody, attached to a report, kept beside the model it came from -- without
 * the half-hour of solver that made it. On the largest assessment here a run is
 * sixteen minutes in the solver and forty-three end to end, which is the whole
 * argument for the format.
 *
 * **What is kept is the state vector, not the series.** Every other series this
 * tool shows is worked out from `(t, y)` on demand -- see `Results.seriesMany`
 * -- and that is the difference between a file of 80 MB and one of 2.8 GB for
 * the same information. It is also the difference between a picture of a run
 * and the run itself: a dataset opened this way answers every question a fresh
 * one does, because it *is* one. The chart, the table, the CSV and the HDF5
 * export all come off the same accessor and none of them knows where the
 * numbers came from.
 *
 * ## The archive
 *
 * A ZIP, and deliberately the same ZIP that Save writes -- the model sits at
 * the root as `<name>.json`, exactly where it does in a compressed save, with
 * the run beside it under `results/`:
 *
 *     <name>.json          the model
 *     results/meta.json    the run report, the run log, the layout signature, the lengths
 *     results/t.f64        the output times
 *     results/y.f64        the state vector at each of them, time-major
 *     results/held.i32     per state, how many steps the zero-floor moved it
 *     results/mem.f64      the histories of the blocks that remember
 *
 * So a reader that knows nothing about results opens the model and ignores the
 * rest, which is what `readModelFile` did before this file existed and still
 * does. Nothing had to be versioned to make that true.
 *
 * ## Why the layout signature
 *
 * A trajectory is a list of numbers whose meaning is entirely in the layout the
 * model builds: `y[i][2117]` is an inventory of one nuclide in one compartment
 * only because `buildSystem` put it there. Handing a stored `y` to a system
 * built from a *different* model is not an error anything downstream would
 * catch -- it is a chart of plausible numbers against the wrong labels.
 *
 * ../domain/fingerprint.js refuses exactly this across an edit, and its note is
 * worth repeating here: on `examples/recorders.json` a system handed somebody
 * else's trajectory reported the peak dose as 6.35 where the run recorded
 * 0.00057. Both are numbers and neither looks wrong.
 *
 * Here the model travels *in the same file* as the run, so the layouts agree by
 * construction -- and the signature is checked anyway, because "by
 * construction" stops being true the moment somebody edits the archive or opens
 * it against a build of this tool whose layout differs. It is cheap, it is
 * exact, and when it fails the model still opens: the results are what is
 * dropped, with the reason said out loud.
 *
 * ## And the histories
 *
 * The fingerprint's other refusal is the blocks that remember -- a peak, a
 * running mean, a snapshot, a delay. Their values are accumulated *during* the
 * integration, into histories the system carries, and a system built fresh has
 * none. That is why reuse-across-an-edit gives up on them.
 *
 * It is not a reason to give up here. Across an edit, carrying the histories
 * over would mean proving the new memory layout matches the old one; in one
 * archive there is nothing to prove, because the model that built the layout is
 * the model in the file. So the histories travel too, under the same signature
 * -- which covers the memory layout as well as the state layout -- and a
 * reopened dataset reports the peak the run recorded.
 *
 * ## And a probabilistic run
 *
 * A sample can go in beside the run, when it is a sample of the same model at
 * its own values -- every realisation of the series it kept, the value every
 * sampled input took, and which realisations integrated:
 *
 *     results/sample/meta.json    how many realisations and times, what each
 *                                 series is, the design, the run's statistics
 *     results/sample/t.f64        the times every realisation is reported at
 *     results/sample/series.f64   the kept series one after another, each one
 *                                 realisation after realisation (`series.f32`
 *                                 for a sample held in single precision)
 *     results/sample/draws.f64    the value each sampled input took, input
 *                                 after input
 *     results/sample/ran.u8       1 for a realisation that integrated, 0 for
 *                                 one that failed
 *
 * In the precision the run held it in, so the bands, the histograms and *What
 * drove it* come out of a reopened file exactly as they came out of the run. A
 * varied parameter is not written as a series: its values are its draws, which
 * are written, and it is put back from them as the run put it there (see
 * `sampleResult`).
 *
 * A sample is not checked against a layout. What its numbers are -- which
 * series, which realisation, which input -- it says itself, and it was made
 * from the model in the same file. It is opened only with the run beside it,
 * which is checked.
 */

/** Bumped only for a change that an older reader could not make sense of. */
export const FORMAT = 1;

/** Where the run lives inside the archive. */
export const DIR = 'results/';
export const META = `${DIR}meta.json`;
const T = `${DIR}t.f64`;
const Y = `${DIR}y.f64`;
const HELD = `${DIR}held.i32`;
const MEM = `${DIR}mem.f64`;

/** Where a probabilistic run lives inside the archive, when it carries one. */
export const SAMPLE_DIR = `${DIR}sample/`;
const SAMPLE_META = `${SAMPLE_DIR}meta.json`;
const SAMPLE_T = `${SAMPLE_DIR}t.f64`;
const SAMPLE_DRAWS = `${SAMPLE_DIR}draws.f64`;
const SAMPLE_RAN = `${SAMPLE_DIR}ran.u8`;
const sampleSeries = (precision) => `${SAMPLE_DIR}series.${precision === 'float32' ? 'f32' : 'f64'}`;

/** The sample's own format, bumped only as `FORMAT` is. */
export const SAMPLE_FORMAT = 1;

/**
 * What the numbers mean, as one string.
 *
 * Every entry of the state vector and every recorder slot, by the name and
 * offset the builder gave it. Two models that produce this string produce the
 * same `y`, and two that do not cannot share one.
 *
 * Built from the layout rather than from the project so that it is a statement
 * about the vector itself: a model edit that does not move anything -- a
 * comment, a colour, a rate constant -- leaves it alone, and one that does
 * changes it.
 */
export function layoutSignature(system) {
	const L = system?.layout ?? {};
	const states = (L.states ?? [])
		.map((s) => `${s.kind}:${s.name}@${s.base}+${s.width}`)
		.join(',');
	const mem = (system?.recorders ?? [])
		.map((r) => `${r.kind}:${r.entry?.name ?? '?'}@${r.mem}+${r.width}`)
		.join(',');
	return `v${FORMAT}|n=${L.nstate ?? 0},${L.nalg ?? 0},${L.nparam ?? 0}`
		+ `|s=${states}|m=${mem}`;
}

/** A Float64Array of everything in `rows`, one row after another. */
function flatten(rows, width) {
	const out = new Float64Array(rows.length * width);
	for (let i = 0; i < rows.length; i++) out.set(rows[i], i * width);
	return out;
}

/** The bytes of a typed array, exactly its own bytes and no more. */
const bytesOf = (a) => new Uint8Array(a.buffer, a.byteOffset, a.byteLength);

/**
 * Reads a typed array back out of bytes that may not be aligned.
 *
 * A ZIP entry starts wherever the entry before it ended, so the eight-byte
 * alignment a `Float64Array` view needs is not something the archive can be
 * asked for. Copied when it is not aligned, which is the normal case, and
 * viewed in place when it happens to be.
 */
function readFloats(bytes, Kind = Float64Array) {
	if (!bytes) return new Kind(0);
	const per = Kind.BYTES_PER_ELEMENT;
	const n = Math.floor(bytes.byteLength / per);
	if (bytes.byteOffset % per === 0) {
		return new Kind(bytes.buffer, bytes.byteOffset, n);
	}
	const copy = bytes.slice(0, n * per);
	return new Kind(copy.buffer, copy.byteOffset, n);
}

/**
 * The entries a results archive holds, ready for `zip`.
 *
 * `inner` is what the model is called inside the archive, so that this writes
 * the same model entry a plain compressed save does.
 *
 * @param {object} opts
 * @param {object} opts.project    the model, as it will be saved
 * @param {object} opts.results    a `Results` from ../sim/runner.js
 * @param {string} opts.inner      the model entry's name, e.g. `biosphere.json`
 * @param {string} [opts.stamp]    when the run was made, ISO; the caller's clock
 * @returns {Array<{name: string, bytes: Uint8Array}>}
 */
export function datasetEntries({ project, results, inner, stamp = null, log = null }) {
	const enc = new TextEncoder();
	const t = Float64Array.from(results.t);
	const nstate = results.y[0]?.length ?? 0;
	const y = flatten(results.y, nstate);
	const held = Int32Array.from(results.stats?.held ?? []);

	// Every recorder's history end to end: its times, then its values. The
	// lengths are in the meta, so this is one entry rather than two per block.
	const memory = results.system?.memory ?? [];
	const lengths = memory.map((m) => m.history.t.length);
	const total = lengths.reduce((a, b) => a + b, 0);
	const mem = new Float64Array(total * 2);
	let at = 0;
	for (const m of memory) {
		mem.set(m.history.t, at);
		mem.set(m.history.v, at + m.history.t.length);
		at += m.history.t.length * 2;
	}

	// The scalars a recorder carries beside its history. A running mean's
	// integral is a state the solver holds, so what it needs back is where it
	// was told to measure from -- see `Recorder.mean`.
	const recorders = memory.map((m, i) => ({
		kind: m.kind,
		n: lengths[i],
		recording: !!m.recording,
		totalTime: m.totalTime,
		lastTime: m.lastTime,
		resetSum: m.resetSum,
	}));

	// Everything but the big arrays, so that a reader can say what the file
	// holds without decompressing megabytes of it.
	const { held: _held, ...stats } = results.stats ?? {};
	const meta = {
		format: FORMAT,
		kind: 'ecolego-results',
		model: inner,
		name: project?.name ?? '',
		stamp,
		times: t.length,
		states: nstate,
		outputs: results.outputs?.().length ?? null,
		signature: layoutSignature(results.system),
		stats,
		timing: results.timing ?? null,
		recorders,
		// The run log, as lines: the account of the run in words, so the
		// archive answers "which solver, which tolerance, what was held" on
		// its own. See ../domain/runlog.js.
		log: Array.isArray(log) ? log : null,
	};

	const out = [
		{ name: META, bytes: enc.encode(JSON.stringify(meta, null, 2)) },
		{ name: T, bytes: bytesOf(t) },
		{ name: Y, bytes: bytesOf(y) },
	];
	if (held.length) out.push({ name: HELD, bytes: bytesOf(held) });
	if (total) out.push({ name: MEM, bytes: bytesOf(mem) });
	return out;
}

/** Whether an unzipped archive carries a run as well as a model. */
export function isDataset(entries) {
	return entries instanceof Map ? entries.has(META) : false;
}

/**
 * The run out of an archive, as plain arrays.
 *
 * Nothing is checked against a model here -- that is `restoreResults`, which
 * has one to check against. This only turns bytes back into numbers.
 *
 * @param {Map<string, Uint8Array>} entries  from `unzip`
 * @returns {object|null}
 */
export function readDataset(entries) {
	if (!isDataset(entries)) return null;
	const meta = JSON.parse(new TextDecoder().decode(entries.get(META)));
	if (meta.format > FORMAT) {
		throw new Error(`These results were written by a newer version of this `
			+ `editor (format ${meta.format}; this one reads ${FORMAT}). The model `
			+ 'in the file opens either way.');
	}
	const t = readFloats(entries.get(T));
	const flat = readFloats(entries.get(Y));
	const nstate = meta.states ?? 0;
	const want = t.length * nstate;
	if (flat.length !== want) {
		throw new Error(`The trajectory is ${flat.length.toLocaleString()} numbers `
			+ `and the file says it should be ${want.toLocaleString()} `
			+ `(${t.length.toLocaleString()} times × ${nstate.toLocaleString()} `
			+ 'states). The archive is damaged.');
	}
	const held = entries.has(HELD) ? readFloats(entries.get(HELD), Int32Array) : null;

	const memBytes = entries.has(MEM) ? readFloats(entries.get(MEM)) : new Float64Array(0);
	const memory = [];
	let at = 0;
	for (const r of meta.recorders ?? []) {
		memory.push({
			...r,
			t: Array.from(memBytes.subarray(at, at + r.n)),
			v: Array.from(memBytes.subarray(at + r.n, at + r.n * 2)),
		});
		at += r.n * 2;
	}
	// A sample that will not read costs the run nothing: it is said, and the
	// run opens without it -- as a run that will not read costs the model
	// nothing.
	let sample = null;
	let sampleProblem = null;
	try {
		sample = readSample(entries);
	} catch (e) {
		sampleProblem = e.message ?? String(e);
	}
	// The trajectory stays flat. It crosses to the worker from here, and one
	// array of eighty megabytes clones as one thing; four hundred views into it
	// rely on the structured-clone memory map to stay one thing, which is true
	// and is not something worth depending on for the largest allocation the
	// program makes. `rowsOf` cuts it up on the other side.
	return { meta, t: Array.from(t), flat, held, memory, sample, sampleProblem };
}

/** The flat trajectory as one row per output time. */
export function rowsOf(flat, times, states) {
	const y = [];
	for (let i = 0; i < times; i++) y.push(flat.subarray(i * states, (i + 1) * states));
	return y;
}

/**
 * Puts a stored run back onto a freshly built system.
 *
 * The signature is the gate, and it is checked against the system built from
 * the model *in the same archive* -- so a mismatch means the file has been
 * edited or this build lays models out differently, not that somebody opened
 * the wrong pair. Either way the numbers no longer mean what they say, and a
 * chart of them would be the failure this whole file exists to prevent.
 *
 * @param {object} opts
 * @param {object} opts.project
 * @param {object} opts.system   from `buildSystem(project)`
 * @param {object} opts.data     from `readDataset`
 * @param {Function} opts.Results  the class, passed in so this module stays
 *   free of the runner -- which imports the solvers, the far-field and the
 *   whole of the builder.
 * @returns {object} a `Results`
 */
export function restoreResults({ project, system, data, Results }) {
	const now = layoutSignature(system);
	if (now !== data.meta.signature) {
		throw new Error('The stored run does not describe this model’s state '
			+ 'vector, so the numbers in it cannot be read against it.');
	}
	const stats = { ...data.meta.stats };
	if (data.held) stats.held = data.held;

	// Back into the histories the blocks read. `History` holds plain arrays and
	// pushes onto them, so plain arrays are what go back -- a typed array here
	// would work until something recorded one more point.
	const memory = system.memory ?? [];
	for (let i = 0; i < memory.length; i++) {
		const saved = data.memory[i];
		if (!saved) continue;
		const m = memory[i];
		m.history.t = saved.t;
		m.history.v = saved.v;
		m.recording = saved.recording;
		m.totalTime = saved.totalTime;
		m.lastTime = saved.lastTime;
		m.resetSum = saved.resetSum;
	}

	// The rows share the one buffer: `Results` reads them and never writes
	// them, and copying the trajectory to hand back the same numbers would be
	// the most expensive thing opening a file does.
	const y = rowsOf(data.flat, data.t.length, data.meta.states ?? 0);
	return new Results({
		project,
		system,
		solution: { t: data.t, y, stats },
		timing: data.meta.timing ?? null,
	});
}

/**
 * One line saying what is in the file, for the notice after opening it. It
 * began with a space, with a stamp or without, from the join of its two parts.
 */
export function describeDataset(meta) {
	if (!meta) return '';
	const when = meta.stamp ? new Date(meta.stamp) : null;
	const ran = when && !Number.isNaN(when.getTime())
		? `run ${when.toLocaleString()}, `
		: '';
	return `${ran}${meta.times.toLocaleString()} output time`
		+ `${meta.times === 1 ? '' : 's'} over `
		+ `${meta.states.toLocaleString()} state${meta.states === 1 ? '' : 's'}`
		+ (meta.stats?.solver ? `, ${meta.stats.solver}` : '');
}

// --- a probabilistic run ---------------------------------------------------------

/**
 * The most a sample may come to and still go into an archive.
 *
 * The archive is put together in one piece before it is written, so a sample
 * is held twice while it is saved -- once by the run, once in the file -- and
 * opening the file holds it twice again, the file and the numbers read out of
 * it. A gigabyte is what every machine can be relied on to give a tab (see
 * `MOST_BYTES` in ../sim/probabilistic.js), and past it a sample is better
 * written as HDF5 with Save → Realisations.
 */
export const MOST_SAMPLE_BYTES = 1073741824;

/**
 * What a sample comes to in an archive: its kept series in the precision they
 * are held in, and the draws, which are always double.
 *
 * @param {{kept: number, times: number, iterations: number, inputs: number, precision?: string}} shape
 *   `kept` series over `times`; `inputs` sampled inputs (the draws)
 */
export function sampleBytes({ kept, times, iterations, inputs, precision = 'double' }) {
	const per = precision === 'float32' ? 4 : 8;
	return kept * times * iterations * per + inputs * iterations * 8 + times * 8 + iterations;
}

/** Plain data only: nothing a typed array or a function could hide in the meta. */
const plainOnly = (key, v) => (typeof v === 'function' || ArrayBuffer.isView(v) ? undefined : v);

/**
 * A probabilistic run as the entries of `results/sample/`.
 *
 * `result` is what the worker keeps of a sample (`lastProb.result` in
 * ../worker/sim-worker.js): every series it kept, realisation-major, with the
 * varied parameters after them as their draws (`flat`). Only the kept series
 * are written as series; the varied ones come back from `draws`.
 *
 * Every entry is a new buffer, so the caller may hand them over to another
 * thread without taking the run's own arrays with them.
 *
 * @param {object} result
 * @param {{stamp?: string}} [opts]
 * @returns {Array<{name: string, bytes: Uint8Array}>}
 */
export function sampleEntries(result, { stamp = null } = {}) {
	const n = result.iterations;
	const times = result.t.length;
	const each = n * times;
	const flat = result.flat ?? new Uint8Array(result.values.length);
	const kept = [];
	for (let k = 0; k < result.values.length; k++) if (!flat[k]) kept.push(k);
	const precision = result.precision === 'float32' ? 'float32' : 'double';
	const Held = precision === 'float32' ? Float32Array : Float64Array;
	const series = new Held(kept.length * each);
	kept.forEach((k, j) => series.set(result.values[k].subarray(0, each), j * each));
	const draws = new Float64Array(result.samples.length * n);
	result.samples.forEach((s, k) => draws.set(s.subarray(0, n), k * n));
	const ran = result.ran ? Uint8Array.from(result.ran) : new Uint8Array(n).fill(1);
	const meta = {
		format: SAMPLE_FORMAT,
		kind: 'kompartment-sample',
		stamp,
		iterations: n,
		times,
		precision,
		kept: kept.length,
		outputs: result.outputs,
		flat: Array.from(flat),
		drawnFrom: Array.from(result.drawnFrom ?? new Array(flat.length).fill(-1)),
		plan: result.plan,
		stats: result.stats ?? {},
	};
	return [
		{ name: SAMPLE_META, bytes: new TextEncoder().encode(JSON.stringify(meta, plainOnly, 1)) },
		{ name: SAMPLE_T, bytes: bytesOf(Float64Array.from(result.t)) },
		{ name: sampleSeries(precision), bytes: bytesOf(series) },
		{ name: SAMPLE_DRAWS, bytes: bytesOf(draws) },
		{ name: SAMPLE_RAN, bytes: ran },
	];
}

/** A typed array of the bytes, always a copy of its own: see `readSample`. */
function ownFloats(bytes, Kind = Float64Array) {
	const per = Kind.BYTES_PER_ELEMENT;
	const n = bytes ? Math.floor(bytes.byteLength / per) : 0;
	const out = new Kind(n);
	if (n) new Uint8Array(out.buffer).set(bytes.subarray(0, n * per));
	return out;
}

/**
 * The probabilistic run out of an archive, or null when it carries none.
 *
 * Everything read into arrays of its own, never views into the file: they go
 * to the worker handed over rather than copied (`sampleBuffers`), and handing
 * over a view would take the whole file's buffer with it.
 *
 * @param {Map<string, Uint8Array>} entries  from `unzip`
 * @returns {{meta: object, t: Float64Array, series: Float64Array|Float32Array,
 *   draws: Float64Array, ran: Uint8Array}|null}
 */
export function readSample(entries) {
	if (!(entries instanceof Map) || !entries.has(SAMPLE_META)) return null;
	const meta = JSON.parse(new TextDecoder().decode(entries.get(SAMPLE_META)));
	if (meta.format > SAMPLE_FORMAT) {
		throw new Error(`the probabilistic run was written by a newer version of this editor `
			+ `(format ${meta.format}; this one reads ${SAMPLE_FORMAT})`);
	}
	const n = Math.round(Number(meta.iterations));
	const times = Math.round(Number(meta.times));
	const outputs = Array.isArray(meta.outputs) ? meta.outputs : [];
	const flat = Array.isArray(meta.flat) ? meta.flat : [];
	const plan = Array.isArray(meta.plan) ? meta.plan : [];
	if (!(n >= 1) || !(times >= 1) || flat.length !== outputs.length) {
		throw new Error('the probabilistic run does not say what it holds');
	}
	const precision = meta.precision === 'float32' ? 'float32' : 'double';
	const Held = precision === 'float32' ? Float32Array : Float64Array;
	const named = sampleSeries(precision);
	for (const name of [SAMPLE_T, named, SAMPLE_DRAWS, SAMPLE_RAN]) {
		if (!entries.has(name)) throw new Error(`the probabilistic run has no ${name.slice(SAMPLE_DIR.length)}`);
	}
	const t = ownFloats(entries.get(SAMPLE_T));
	const series = ownFloats(entries.get(named), Held);
	const draws = ownFloats(entries.get(SAMPLE_DRAWS));
	const ran = Uint8Array.from(entries.get(SAMPLE_RAN));
	const kept = flat.filter((f) => !f).length;
	const sizes = [
		[t.length, times, 'times'],
		[series.length, kept * n * times, 'numbers in its series'],
		[draws.length, plan.length * n, 'draws'],
		[ran.length, n, 'realisations'],
	];
	for (const [got, want, what] of sizes) {
		if (got !== want) {
			throw new Error(`the probabilistic run has ${got.toLocaleString()} ${what} where it says `
				+ `${want.toLocaleString()}; the archive is damaged`);
		}
	}
	return { meta: { ...meta, iterations: n, times, precision, kept }, t, series, draws, ran };
}

/** The buffers of a sample read by `readSample`, to hand over rather than copy. */
export function sampleBuffers(sample) {
	if (!sample) return [];
	return [sample.t, sample.series, sample.draws, sample.ran].map((a) => a.buffer);
}

/**
 * A sample read from an archive, as the result a probabilistic run hands
 * back: the kept series as views into the one array they came in, and each
 * varied parameter put back from its draws, NaN where a realisation failed --
 * which is what the run did with them (`withInputs` in ../worker/sim-worker.js).
 */
export function sampleResult(sample) {
	const { meta } = sample;
	const n = meta.iterations;
	const each = n * meta.times;
	const flat = Uint8Array.from(meta.flat);
	const drawnFrom = Int32Array.from(meta.drawnFrom ?? []);
	const plan = meta.plan ?? [];
	const samples = plan.map((_, k) => sample.draws.subarray(k * n, (k + 1) * n));
	const failed = sample.ran.includes(0);
	const values = [];
	let j = 0;
	for (let k = 0; k < meta.outputs.length; k++) {
		if (!flat[k]) {
			values.push(sample.series.subarray(j * each, (j + 1) * each));
			j++;
			continue;
		}
		const from = samples[drawnFrom[k]];
		const drawn = from ? Float64Array.from(from) : new Float64Array(n).fill(NaN);
		if (failed) for (let i = 0; i < n; i++) if (!sample.ran[i]) drawn[i] = NaN;
		values.push(drawn);
	}
	return {
		t: sample.t,
		outputs: meta.outputs,
		values,
		plan,
		samples,
		inputs: [],
		ran: sample.ran,
		iterations: n,
		precision: meta.precision,
		stats: meta.stats ?? {},
		flat,
		drawnFrom,
	};
}

/** What a sample in a file is, in a few words: `1,000 realisations of 12 series`. */
export function describeSampleMeta(meta) {
	if (!meta) return '';
	const n = meta.iterations ?? 0;
	const k = meta.kept ?? 0;
	return `${n.toLocaleString()} realisation${n === 1 ? '' : 's'} of ${k.toLocaleString()} `
		+ `series${meta.stats?.failed ? `, ${meta.stats.failed} of them failed` : ''}`;
}
