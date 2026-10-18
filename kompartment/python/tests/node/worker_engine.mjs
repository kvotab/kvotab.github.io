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
const D = await import(`${src}/io/dataset.js`);
const { zip, unzip } = await import(`${src}/io/zip.js`);
const { quantiles, meanOf } = await import(`${src}/sim/spread.js`);
const { medianSpread } = await import(`${src}/sim/probabilistic.js`);
const { categoriesOf, classify, includeMask } = await import(`${src}/domain/categories.js`);
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

// The browser's own run, for what the engine says of its run to be compared with.
let got = await send({ type: 'run', id: 100, project: bio });
const own = got.find((m) => m.type === 'done').payload;

// A run the engine holds: its series fetched, then the whole run brought here for a save.
got = await send({ type: 'run', id: 1, project: bio, engine });
const done = got.find((m) => m.type === 'done');
const indices = done.payload.outputs.map((_, i) => i).slice(0, 24);
got = await send({ type: 'columns', id: 1, indices });
const fetched = got.find((m) => m.type === 'columns').columns;
got = await send({ type: 'dataset', id: 1, project: bio, inner: 'model.json' });
const saved = got.find((m) => m.type === 'dataset');
got = await send({ type: 'columns', id: 1, indices });
// What the page reads of the run besides its series, as the engine said it,
// against what the browser's own run of the model says.
const pick = (p) => JSON.stringify({
	outputs: p.outputs.map((o) => [o.kind, o.block, o.nuclide, o.dims, o.index, o.label, o.unit, o.constant, o.timeDependent ?? true]),
	nuclides: p.nuclides, stateCount: p.stateCount, heldAtZero: p.heldAtZero,
	jacobian: p.jacobian && [p.jacobian.available, p.jacobian.colours, p.jacobian.nnz, p.jacobian.constant ?? null],
});
const differ = [];
for (const key of ['outputs', 'nuclides', 'stateCount', 'heldAtZero', 'jacobian']) {
	if (JSON.stringify(JSON.parse(pick(done.payload))[key]) !== JSON.stringify(JSON.parse(pick(own))[key])) differ.push(key);
}
out.summary = { differ, code: done.payload.generatedSource === null };
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

// A probabilistic run the engine holds: the bands the engine worked out, against
// the page's own formulas over the same realisations, and every question asked of
// it against the same sample held here.
const identical = (a, b) => a?.length === b?.length && Array.from(a).every((v, i) => Object.is(v, b[i]));
const sameDeep = (a, b) => {
	if (ArrayBuffer.isView(a) || ArrayBuffer.isView(b)) return identical(a, b);
	if (Array.isArray(a)) return Array.isArray(b) && a.length === b.length && a.every((v, i) => sameDeep(v, b[i]));
	if (a && typeof a === 'object') {
		const ka = Object.keys(a).filter((k) => k !== 'id');
		return ka.length === Object.keys(b ?? {}).filter((k) => k !== 'id').length && ka.every((k) => sameDeep(a[k], b[k]));
	}
	return Object.is(a, b);
};
const sdOf = (v, times, n, mean, mask) => {
	const sd = new Float64Array(times);
	const count = new Int32Array(times);
	for (let i = 0; i < n; i++) {
		if (mask && !mask[i]) continue;
		for (let j = 0; j < times; j++) {
			const x = v[i * times + j];
			if (!Number.isFinite(x)) continue;
			sd[j] += (x - mean[j]) ** 2;
			count[j] += 1;
		}
	}
	for (let j = 0; j < times; j++) sd[j] = count[j] > 1 ? Math.sqrt(sd[j] / (count[j] - 1)) : NaN;
	return { sd, n: count };
};
const bandsHere = (r, percentiles, mask) => r.values.map((v, k) => {
	const s = r.flat[k] ? 1 : r.t.length;
	const mean = meanOf(v, s, r.iterations, mask);
	const band = {
		q: quantiles(v, s, r.iterations, percentiles, mask).map((b) => b.y), mean,
		sd: sdOf(v, s, r.iterations, mean, mask), med: medianSpread(v, s, r.iterations, 1.959964, mask),
	};
	if (r.flat[k]) band.flat = true;
	return band;
});
got = await send({ type: 'probabilistic', id: 12, project: bio, iterations: 20, seed: 3, engine });
const held = got.find((m) => m.type === 'probabilistic-done');
out.sample = { engine: held?.payload.engine ?? null, error: got.find((m) => m.type === 'error')?.message ?? null };
if (held) {
	const p = held.payload;
	const ks = p.outputs.map((o, k) => (o.varied ? -1 : k)).filter((k) => k >= 0);
	const varied = p.outputs.findIndex((o) => o.varied);
	const [a, b, c] = ks;
	const saved = (await send({ type: 'sample-entries', id: 12, stamp: 'S' })).find((m) => m.type === 'sample-entries');
	const r = D.sampleResult(D.readSample(new Map(saved.parts.map((e) => [e.name, e.bytes]))));
	const finals = Array.from({ length: r.iterations }, (_, i) => r.values[a][(i + 1) * r.t.length - 1])
		.filter(Number.isFinite).sort((x, y) => x - y);
	const categories = [{ label: 'High', output: p.outputs[a].label, stat: 'final', op: '>',
		value: finals[Math.floor(finals.length / 2)], include: false }];
	const cats = categoriesOf({ simulation: { categories } });
	const mask = includeMask(cats, classify(cats, r).member);
	const questions = async (id) => {
		const one = async (msg) => (await send({ ...msg, id })).find((m) => m.type === msg.type || m.type === 'error');
		return {
			bands: await one({ type: 'prob-bands', percentiles: [0.1, 0.5, 0.9] }),
			atTime: await one({ type: 'prob-summary', index: a, at: 3 }),
			ownPeak: await one({ type: 'prob-summary', index: a, at: 'max' }),
			hist: await one({ type: 'prob-hist', indices: [b, a, varied], at: 'peak' }),
			points: await one({ type: 'prob-points', x: varied, ys: [a, b], at: 4 }),
			drove: await one({ type: 'sensitivity', index: a, at: 'peak' }),
			one: await one({ type: 'prob-matrix', indices: [c, varied], want: '7' }),
			mean: await one({ type: 'prob-matrix', indices: [b, varied], want: 'mean' }),
			screened: await one({ type: 'prob-categories', categories }),
		};
	};
	const there = await questions(12);
	// The same sample held here: the archive Save with results writes, opened.
	got = await send({ type: 'run', id: 13, project: bio });
	const runParts = (await send({ type: 'dataset', id: 13, project: bio, inner: 'model.json' }))
		.find((m) => m.type === 'dataset').parts;
	const data = D.readDataset(await unzip(await zip([
		{ name: 'model.json', bytes: new TextEncoder().encode(JSON.stringify(bio)) }, ...runParts, ...saved.parts,
	])));
	got = await send({ type: 'open-dataset', id: 14, project: bio, data });
	const opened = got.find((m) => m.type === 'probabilistic-done');
	const here = await questions(14);
	const differ = Object.keys(there).filter((k) => !there[k] || there[k].gone || there[k].type === 'error'
		|| !sameDeep(there[k], here[k]));
	out.sample = {
		...out.sample,
		bands: sameDeep(p.bands, bandsHere(r, p.quantiles, null)),
		screenedBands: !!there.screened?.bands && sameDeep(there.screened.bands, bandsHere(r, there.screened.quantiles, mask)),
		payload: !!opened && sameDeep({ ...p, engine: undefined }, { ...opened.payload, engine: undefined }),
		kept: there.screened?.screen?.kept ?? null,
		iterations: p.iterations,
		differ,
	};
}
process.stdout.write(JSON.stringify(out));
process.exit(0);
