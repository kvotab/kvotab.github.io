/**
 * A run an engine on this machine holds (see serve.py).
 *
 * The largest assessment's states over its output times are a hundred and
 * sixty megabytes, and a chart of it shows a dozen series. So an engine keeps
 * the run it made, and this is everything the page needs of it but the states:
 * the times, the run report, what the zero floor held, the mass-balance audit
 * the engine worked out, and what the page reads of a run besides its series --
 * the outputs as it lists them, each parameter's one value, the nuclides, how
 * df/dy was had, what the zero floor held -- as the engine worked those out
 * (`page`), so that the model is not built here to hold the run. An engine that
 * sends no `page` has the run held against this worker's own build of the model,
 * which it was checked against (`checkLayout` in ../io/dataset.js).
 *
 * A series is asked of the engine when the page asks for it (`fetchSeries`),
 * by its label, and the engine works it out from its states as `seriesMany`
 * would here. What needs every state -- saving the run, keeping it beside,
 * working an edit out over it -- fetches the whole run first (`fetchArchive`),
 * and the engine is then told it may let go of it.
 */

import { Results } from '../sim/runner.js';

const engineName = (handle) => (handle.engine?.name === 'julia' ? 'Julia' : 'Python');

/** What the server said went wrong, as an error the page shows. */
async function refusal(res, handle) {
	const said = await res.json().catch(() => ({}));
	return Object.assign(new Error(said.error ?? `The ${engineName(handle)} engine's server answered ${res.status}.`), {
		name: 'Engine',
		hint: res.status === 404 || res.status === 410
			? 'Run the model again to have its results here.'
			: 'Is serve.py still running? Its window says what the engine printed.',
	});
}

export class EngineResults extends Results {
	/**
	 * @param {object} opts  as `Results` takes them, `solution.y` null
	 * @param {{engine: {name: string, token: string}, job: string}} opts.handle
	 *   the engine and the job whose run it holds
	 * @param {object|null} opts.massBalance  the audit the engine worked out
	 * @param {object|null} opts.page  what the page reads of the run, worked out
	 *   by the engine; null to read it off `opts.system`
	 * @param {object} opts.raw  the model, as the page sent it
	 */
	constructor({ handle, massBalance = null, page = null, raw = null, ...rest }) {
		super(rest);
		this.handle = handle;
		this.audit = massBalance;
		this.page = page;
		this.raw = raw;
	}

	/** Whether the states are with an engine rather than here. */
	get onEngine() { return true; }

	massBalance() { return this.audit; }

	outputs() { return this.page ? this.page.outputs : super.outputs(); }

	constantOf(output) { return this.page ? (output.constant ?? null) : super.constantOf(output); }

	heldAtZero() { return this.page ? this.page.heldAtZero : super.heldAtZero(); }

	get jacobian() { return this.page ? this.page.jacobian : super.jacobian; }

	get nuclides() { return this.page ? this.page.nuclides : super.nuclides; }

	/** The length of the state vector. */
	get stateCount() { return this.page ? this.page.stateCount : this.system.layout.nstate; }

	seriesMany() {
		throw new Error('The run is held by an engine: its series are fetched (fetchSeries), not worked out here.');
	}

	total() {
		throw new Error('The run is held by an engine: its states are not here to add up.');
	}

	get headers() { return { 'X-Kompartment-Token': this.handle.engine.token }; }

	/**
	 * The series for these outputs, in their order: a parameter's one value
	 * here, as `seriesMany` gives it; everything else from the engine, by
	 * label, in one request.
	 */
	async fetchSeries(outputs) {
		const n = this.t.length;
		const cols = outputs.map(() => new Float64Array(n));
		const asked = [];
		outputs.forEach((o, k) => {
			const value = this.constantOf(o);
			if (value !== null && value !== undefined) cols[k].fill(value);
			else asked.push(k);
		});
		if (!asked.length) return cols;
		let res;
		try {
			res = await fetch(`/engine/runs/${this.handle.job}/series`, {
				method: 'POST',
				headers: { ...this.headers, 'Content-Type': 'application/json' },
				body: JSON.stringify({ labels: asked.map((k) => outputs[k].label) }),
			});
		} catch (e) {
			throw Object.assign(new Error(`The ${engineName(this.handle)} engine could not be reached `
				+ `(${e.message ?? e}).`), { name: 'Engine', hint: 'Is serve.py still running?' });
		}
		if (!res.ok) throw await refusal(res, this.handle);
		const flat = new Float64Array(await res.arrayBuffer());
		if (flat.length !== asked.length * n) {
			throw Object.assign(new Error(`The ${engineName(this.handle)} engine sent ${flat.length} numbers for `
				+ `${asked.length} series of ${n} times.`), { name: 'Engine' });
		}
		asked.forEach((k, j) => cols[k].set(flat.subarray(j * n, (j + 1) * n)));
		return cols;
	}

	/** The whole run, as the archive *Save with results* writes it, from the engine. */
	async fetchArchive() {
		let res;
		try {
			res = await fetch(`/engine/runs/${this.handle.job}/archive`, { headers: this.headers });
		} catch (e) {
			throw Object.assign(new Error(`The ${engineName(this.handle)} engine could not be reached `
				+ `(${e.message ?? e}).`), { name: 'Engine', hint: 'Is serve.py still running?' });
		}
		if (!res.ok) throw await refusal(res, this.handle);
		return res.arrayBuffer();
	}

	/** Tells the engine it may let go of the run. Kept alive, since this worker may be ended next. */
	forget() {
		fetch(`/engine/runs/${this.handle.job}/forget`, {
			method: 'POST', headers: this.headers, keepalive: true,
		}).catch(() => {});
	}
}
