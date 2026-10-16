// The page's own worker against a running serve.py and one of its engines, for the
// Python package's tests: every kind of work the page hands an engine, asked of the
// engine and of the worker itself, and what each came to.
//
//   node worker_engine.mjs <kompartment src directory> <server> <token> <engine> <examples directory>
//
// The worker module is loaded as a worker is (`self` its global scope) and sent the
// messages the page sends it; `fetch` goes to the server. One JSON object on stdout,
// a finding a key, each saying what it measured.

import { readFileSync } from 'node:fs';

const [src, base, token, engineName, examples] = process.argv.slice(2);
const messages = [];
globalThis.self = globalThis;
globalThis.postMessage = (m) => { messages.push(m); };
const realFetch = globalThis.fetch;
globalThis.fetch = (url, opts) => realFetch(new URL(url, base), opts);
await import(`${src}/worker/sim-worker.js`);
const { variablesOf } = await import(`${src}/sim/calibrate.js`);
const send = async (data) => { messages.length = 0; await self.onmessage({ data }); return [...messages]; };
const engine = { name: engineName, token, client: `tests-${engineName}` };
const model = (name) => JSON.parse(readFileSync(`${examples}/${name}.json`, 'utf8'));
const close = (a, b, tol) => (Number.isNaN(a) && Number.isNaN(b)) || Math.abs(a - b) <= tol * Math.max(Math.abs(a), Math.abs(b));
// The largest difference between two lists of series, each relative to its own largest value.
const worstOf = (as, bs) => {
	let worst = 0;
	as.forEach((a, k) => {
		const b = bs[k];
		const scale = Math.max(...Array.from(b, Math.abs).filter(Number.isFinite), 1e-300);
		for (let i = 0; i < a.length; i++) if (Number.isFinite(b[i])) worst = Math.max(worst, Math.abs(a[i] - b[i]) / scale);
	});
	return worst;
};
const out = {};
const bio = model('biosphere');

// A run the engine holds: its series fetched, then the whole run brought here for a save.
let got = await send({ type: 'run', id: 1, project: bio, engine });
const done = got.find((m) => m.type === 'done');
const indices = done.payload.outputs.map((_, i) => i).slice(0, 24);
got = await send({ type: 'columns', id: 1, indices });
const fetched = got.find((m) => m.type === 'columns').columns;
got = await send({ type: 'dataset', id: 1, project: bio, inner: 'model.json' });
const saved = got.find((m) => m.type === 'dataset');
got = await send({ type: 'columns', id: 1, indices });
out.run = {
	engine: done.payload.engine,
	saved: !!saved?.ok && saved.parts.some((e) => e.name === 'results/y.f64'),
	worst: worstOf(fetched, got.find((m) => m.type === 'columns').columns),
};

// A tornado: its table on the engine and here.
const tor = { type: 'tornado', project: bio, tornado: { low: 0.05, high: 0.95 }, index: 0, stat: 'max', at: 0, workers: 1 };
got = await send({ ...tor, id: 2, engine });
const torThere = got.find((m) => m.type === 'tornado');
const torStages = got.filter((m) => m.type === 'loading').map((m) => m.stage);
got = await send({ ...tor, id: 3 });
const torHere = got.find((m) => m.type === 'tornado');
out.tornado = {
	onEngine: torStages.includes('engine-sending') && !torStages.includes('engine-elsewhere'),
	points: torThere?.points ?? null,
	same: !!torThere && torThere.table.rows.length === torHere.table.rows.length
		&& close(torThere.table.central, torHere.table.central, 1e-9)
		&& torThere.table.rows.every((r) => {
			const h = torHere.table.rows.find((x) => x.k === r.k);
			return h && close(r.low, h.low, 1e-9) && close(r.high, h.high, 1e-9) && r.lowInput === h.lowInput && r.highInput === h.highInput;
		}),
	outputs: [torThere?.outputs.length ?? null, torHere.outputs.length],
};

// A sensitivity design: on an engine that runs it, or here where it does not.
const gsa = { type: 'gsa', project: bio, gsa: { method: 'morris', options: { trajectories: 6, levels: 4 } }, seed: 7, index: 0, stat: 'max', at: 0, workers: 1 };
got = await send({ ...gsa, id: 4, engine });
const gsaThere = got.find((m) => m.type === 'gsa');
const gsaStages = got.filter((m) => m.type === 'loading').map((m) => m.stage);
got = await send({ ...gsa, id: 5 });
const gsaHere = got.find((m) => m.type === 'gsa');
const values = (x) => (Array.isArray(x) || ArrayBuffer.isView(x) ? Array.from(x) : Object.values(x ?? {}));
out.gsa = {
	onEngine: gsaStages.includes('engine-sending') && !gsaStages.includes('engine-elsewhere'),
	elsewhere: gsaStages.includes('engine-elsewhere'),
	same: !!gsaThere && gsaThere.answer.rows.length === gsaHere.answer.rows.length
		&& gsaThere.answer.rows.every((r) => {
			const h = gsaHere.answer.rows.find((x) => x.k === r.k);
			return h && values(r.values).every((v, j) => close(v, values(h.values)[j], 1e-9));
		}),
};

// One realisation replayed.
const replay = { type: 'replay', project: bio, index: 5, seed: 11, iterations: 20, latin: true, varied: null };
got = await send({ ...replay, id: 6, engine });
const rThere = got.find((m) => m.type === 'done');
got = await send({ type: 'columns', id: 6, indices });
const rColsThere = got.find((m) => m.type === 'columns')?.columns ?? [];
got = await send({ ...replay, id: 7 });
const rHere = got.find((m) => m.type === 'done');
got = await send({ type: 'columns', id: 7, indices });
out.replay = {
	engine: rThere?.payload?.engine ?? null,
	index: rThere?.replayed?.index ?? null,
	inputs: !!rThere && rThere.replayed.values.every((v, k) => v.name === rHere.replayed.values[k].name
		&& close(v.value, rHere.replayed.values[k].value, 1e-12)),
	worst: rColsThere.length ? worstOf(rColsThere, got.find((m) => m.type === 'columns').columns) : null,
};

// A calibration with a known answer.
const cal = {
	name: 'cal',
	simulation: { start_time: 0, end_time: 100, output_points: 101, spacing: 'linear', solver: 'ndf', rtol: 1e-8, abstol: 1e-12, time_unit: 'year' },
	parameters: [{ name: 'k', value: '0.05', unit: '1/year' }, { name: 'A0', value: '1', unit: 'Bq' }],
	compartments: [{ name: 'A', initial: 'A0', unit: 'Bq', dydt: '-k*A' }],
};
const opt = {
	type: 'optimise', project: cal, method: 'nelder', maxEvals: 400, seed: 1,
	targets: [20, 80].map((time) => ({ output: 'A', when: 'at', time, scale: 'log', weight: 1, value: 5 * Math.exp(-0.03 * time) })),
	variables: [{ key: 'k', lower: 1e-3, upper: 1, space: 'log' }, { key: 'A0', lower: 0.1, upper: 100, space: 'log' }],
};
got = await send({ ...opt, id: 8, engine });
const cThere = got.find((m) => m.type === 'optimise');
const cStages = got.filter((m) => m.type === 'loading').map((m) => m.stage);
got = await send({ ...opt, id: 9 });
const cHere = got.find((m) => m.type === 'optimise');
const fit = (r) => Object.fromEntries((r?.result?.values ?? []).map((x) => [x.key, x.value]));
out.calibrate = {
	onEngine: cStages.includes('engine-sending') && !cStages.includes('engine-elsewhere'),
	elsewhere: cStages.includes('engine-elsewhere'),
	matched: !!cThere?.ok && cThere.result.matched,
	k: fit(cThere).k ?? null,
	same: !!cThere?.ok && close(fit(cThere).k, fit(cHere).k, 1e-6) && close(fit(cThere).A0, fit(cHere).A0, 1e-6)
		&& cThere.result.evals === cHere.result.evals,
};

// dy/dp for two of the model's parameters.
const parameters = variablesOf(bio).map((x) => x.key).slice(0, 2);
got = await send({ type: 'local-sensitivity', id: 10, project: bio, parameters, engine });
const sThere = got.find((m) => m.type === 'local-sensitivity');
const sStages = got.filter((m) => m.type === 'loading').map((m) => m.stage);
got = await send({ type: 'local-sensitivity', id: 11, project: bio, parameters });
const sHere = got.find((m) => m.type === 'local-sensitivity');
const rows = (r) => r.states.flatMap((s) => [s.y, ...s.sens, ...s.elasticity]);
out.sensitivity = {
	onEngine: sStages.includes('engine-sending') && !sStages.includes('engine-elsewhere'),
	elsewhere: sStages.includes('engine-elsewhere'),
	states: sThere?.states.length ?? null,
	same: !!sThere && sThere.states.map((s) => s.name).join('|') === sHere.states.map((s) => s.name).join('|'),
	worst: sThere ? worstOf(rows(sThere), rows(sHere)) : null,
};
process.stdout.write(JSON.stringify(out));
process.exit(0);
