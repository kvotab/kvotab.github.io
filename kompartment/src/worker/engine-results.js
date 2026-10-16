/**
 * A run an engine on this machine holds (see serve.py).
 *
 * The largest assessment's states over its output times are a hundred and
 * sixty megabytes, and a chart of it shows a dozen series. So an engine keeps
 * the run it made, and this is everything the page needs of it but the states:
 * the times, the run report, what the zero floor held, the mass-balance audit
 * the engine worked out, and this worker's own build of the model, which the
 * run was checked against (`checkLayout` in ../io/dataset.js) and which answers
 * for its outputs, its parameters and its Jacobian as a run made here does.
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
	 */
	constructor({ handle, massBalance = null, ...rest }) {
		super(rest);
		this.handle = handle;
		this.audit = massBalance;
	}

	/** Whether the states are with an engine rather than here. */
	get onEngine() { return true; }

	massBalance() { return this.audit; }

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
			if (o.source === 'P') cols[k].fill(this.constantOf(o));
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
