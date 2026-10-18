/**
 * A probabilistic run an engine on this machine holds (see serve.py).
 *
 * A sample is every realisation of every series the run kept -- a thousand
 * realisations of a hundred series over four hundred times is 320 MB -- and
 * the page draws its bands. So an engine keeps the sample it made, and this
 * worker holds what every analysis reads whole and what costs little: the
 * times, the value each input was drawn at, which realisations ran, and what
 * each series is. The rest is asked of the engine as a question needs it
 * (serve.py's `/engine/runs/<id>/...`):
 *
 * - `bands`: every series' bands, over the realisations a screen keeps, worked
 *   out there to the same formulas as `bandsOf` here;
 * - `realisations`: every realisation of a series, for what reads a curve per
 *   realisation (a peak, an input's influence over time, a category's test);
 * - `column`: one time across every realisation, for a distribution or a scatter;
 * - `realisation`: one realisation of several series, for the table.
 *
 * Saving the sample fetches every realisation, a batch of series at a time, and
 * writes them as a sample held here is written (`sampleEntries`). A varied
 * parameter's values are its draws, which are here, and are never asked for.
 * The last few series fetched whole are kept (`MOST_CACHED`), since a dialog
 * asks about the same series again and again.
 *
 * The same questions as `LocalSample` in ./sim-worker.js answers of a sample
 * held here, so every handler there is written once for both.
 */

import { refusal, engineName } from './engine-results.js';
import { sampleEntries } from '../io/dataset.js';

/** What the series fetched whole may come to before the oldest is let go of. */
export const MOST_CACHED = 128 * 1048576;

/** What one request for a save's realisations may come to, as doubles. */
const SAVE_BATCH = 64 * 1048576;

/** One time of a realisation-major series, across the realisations: `values[i * stride + a]`. */
export function columnOf(values, stride, iterations, a) {
	const out = new Float64Array(iterations);
	for (let i = 0; i < iterations; i++) out[i] = values[i * stride + a];
	return out;
}

/** One realisation of a realisation-major series: its `stride` values. */
export function rowOf(values, stride, i) {
	return Float64Array.from(values.subarray(i * stride, (i + 1) * stride));
}

/**
 * The arrays asked for, in order: those already worked out here, and the rest
 * from what was fetched -- a copy of it where a series was asked for twice, so
 * that every array in the answer can be handed over on its own.
 */
function fill(out, ks, fetched) {
	const given = new Set();
	return ks.map((k, j) => {
		if (out[j]) return out[j];
		const v = fetched.get(k);
		if (given.has(k)) return v.slice();
		given.add(k);
		return v;
	});
}

/** How many runs of doubles follow each series' percentiles in its bands: see `bands`. */
const BAND_PARTS = 7;

export class EngineSample {
	/**
	 * @param {object} result  what `sampleResult` makes of the archive the engine
	 *   sent: a kept series' values null, a varied parameter's its draws
	 * @param {{engine: {name: string, token: string}, job: string}} handle
	 *   the engine and the job whose sample it holds
	 */
	constructor(result, handle) {
		this.result = result;
		this.handle = handle;
		/** Series fetched whole, by index, oldest first. */
		this.cache = new Map();
		this.cached = 0;
	}

	/** Whether the realisations are with an engine rather than here. */
	get onEngine() { return true; }

	get headers() { return { 'X-Kompartment-Token': this.handle.engine.token }; }

	/** How far apart one realisation's values are in series `k`. */
	strideOf(k) { return this.result.flat?.[k] ? 1 : this.result.t.length; }

	/** A question about the sample, answered as little-endian doubles. */
	async ask(op, body) {
		let res;
		try {
			res = await fetch(`/engine/runs/${this.handle.job}/${op}`, {
				method: 'POST',
				headers: { ...this.headers, 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
			});
		} catch (e) {
			throw Object.assign(new Error(`The ${engineName(this.handle)} engine could not be reached `
				+ `(${e.message ?? e}).`), { name: 'Engine', hint: 'Is serve.py still running?' });
		}
		if (!res.ok) throw await refusal(res, this.handle);
		return new Float64Array(await res.arrayBuffer());
	}

	/** Checks an answer is as long as the question says, or says what came instead. */
	expect(got, want, what) {
		if (got.length === want) return;
		throw Object.assign(new Error(`The ${engineName(this.handle)} engine sent ${got.length.toLocaleString()} `
			+ `numbers for ${what}, where ${want.toLocaleString()} were expected.`), { name: 'Engine' });
	}

	/** A series fetched whole, kept while the rest fit beside it. */
	remember(k, values) {
		if (values.byteLength > MOST_CACHED) return;
		this.cache.set(k, values);
		this.cached += values.byteLength;
		for (const [old, v] of this.cache) {
			if (this.cached <= MOST_CACHED) break;
			this.cache.delete(old);
			this.cached -= v.byteLength;
		}
	}

	/** Series `k` whole, if it is here: a varied parameter's draws, or one fetched lately. */
	here(k) {
		const own = this.result.values[k];
		if (own) return own;
		const v = this.cache.get(k);
		if (v) {
			// The most recently asked about goes to the back of the line.
			this.cache.delete(k);
			this.cache.set(k, v);
		}
		return v ?? null;
	}

	/** Every realisation of each series, realisation-major, in the order asked. */
	async series(ks) {
		const out = ks.map((k) => this.here(k));
		const missing = [...new Set(ks.filter((k, j) => !out[j]))];
		if (!missing.length) return out;
		const n = this.result.iterations;
		const each = n * this.result.t.length;
		const got = await this.ask('realisations', { series: missing });
		this.expect(got, missing.length * each, `${missing.length} series of ${n.toLocaleString()} realisations`);
		const fetched = new Map(missing.map((k, j) => [k,
			missing.length === 1 ? got : got.slice(j * each, (j + 1) * each)]));
		for (const [k, v] of fetched) this.remember(k, v);
		return ks.map((k, j) => out[j] ?? fetched.get(k));
	}

	/** Each series at one output time (`at`, from 0) in every realisation; a varied parameter's draws. */
	async columns(ks, at) {
		const n = this.result.iterations;
		const out = ks.map((k) => {
			const v = this.here(k);
			return v ? columnOf(v, this.strideOf(k), n, this.result.flat?.[k] ? 0 : at) : null;
		});
		const missing = [...new Set(ks.filter((k, j) => !out[j]))];
		if (!missing.length) return out;
		const got = await this.ask('column', { series: missing, at });
		this.expect(got, missing.length * n, `${missing.length} series at one time`);
		return fill(out, ks, new Map(missing.map((k, j) => [k, got.slice(j * n, (j + 1) * n)])));
	}

	/** One realisation (`i`, from 0) of each series: its values over the times, or its one value. */
	async realisation(ks, i) {
		const out = ks.map((k) => {
			const v = this.here(k);
			return v ? rowOf(v, this.strideOf(k), i) : null;
		});
		const missing = [...new Set(ks.filter((k, j) => !out[j]))];
		if (!missing.length) return out;
		const times = this.result.t.length;
		const got = await this.ask('realisation', { series: missing, index: i });
		this.expect(got, missing.length * times, `one realisation of ${missing.length} series`);
		return fill(out, ks, new Map(missing.map((k, j) => [k, got.slice(j * times, (j + 1) * times)])));
	}

	/**
	 * Every series' bands over the realisations `mask` keeps (all of them when
	 * it is null), at `percentiles` -- which have the median among them, as
	 * `percentilesFor` leaves them -- in the shape `bandsOf` gives them.
	 */
	async bands(percentiles, mask) {
		const r = this.result;
		const got = await this.ask('bands', { percentiles, mask: mask ? Array.from(mask) : null });
		const per = percentiles.length + BAND_PARTS;
		let want = 0;
		for (let k = 0; k < r.outputs.length; k++) want += per * this.strideOf(k);
		this.expect(got, want, `the bands of ${r.outputs.length} series`);
		let at = 0;
		const take = (s) => got.slice(at, (at += s));
		return r.outputs.map((_, k) => {
			const s = this.strideOf(k);
			const q = percentiles.map(() => take(s));
			const mean = take(s);
			const sd = { sd: take(s), n: Int32Array.from(take(s)) };
			const med = { errLo: take(s), errHi: take(s), bodyLo: take(s), bodyHi: take(s) };
			const band = { q, mean, sd, med };
			if (r.flat?.[k]) band.flat = true;
			return band;
		});
	}

	/**
	 * The sample as the entries of `results/sample/`, for Save → Model with
	 * results: every realisation fetched, a batch of series at a time, into one
	 * array in the precision the engine holds them in, and written as a sample
	 * held here is written.
	 */
	async entries({ stamp = null } = {}) {
		const r = this.result;
		const each = r.iterations * r.t.length;
		const kept = [];
		r.outputs.forEach((_, k) => { if (!r.flat?.[k]) kept.push(k); });
		const whole = new (r.precision === 'float32' ? Float32Array : Float64Array)(kept.length * each);
		const per = Math.max(1, Math.floor(SAVE_BATCH / (each * 8)));
		for (let j = 0; j < kept.length; j += per) {
			const ks = kept.slice(j, j + per);
			const got = await this.ask('realisations', { series: ks });
			this.expect(got, ks.length * each, `${ks.length} series of ${r.iterations.toLocaleString()} realisations`);
			whole.set(got, j * each);
		}
		const values = r.values.slice();
		kept.forEach((k, j) => { values[k] = whole.subarray(j * each, (j + 1) * each); });
		return sampleEntries({ ...r, values }, { stamp });
	}

	/** Tells the engine it may let go of the sample. Kept alive, since this worker may be ended next. */
	forget() {
		this.cache.clear();
		this.cached = 0;
		fetch(`/engine/runs/${this.handle.job}/forget`, {
			method: 'POST', headers: this.headers, keepalive: true,
		}).catch(() => {});
	}
}
