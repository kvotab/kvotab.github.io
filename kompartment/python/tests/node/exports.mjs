// The application's result and data exports, for the Python package's tests to compare with.
//
//   node exports.mjs <kompartment src directory> < request.json
//
// A request is { task, ... } -- or { task: 'batch', requests: [...] } for several
// at once -- and the answer one JSON object on stdout. Binary data travels as
// base64. Values that JSON cannot carry are tagged, both ways:
//
//   { "$num": "NaN" | "Infinity" | "-Infinity" | "-0" }    a number
//   { "$undef": true }                                      undefined
//   { "$typed": "Float32Array", "v": [...] }                a typed array
//
// A model given to a task is opened as the page opens one (migrateKeys,
// materialiseShorthand, syncDerivedUnits) unless the request says `opened: true`.
//
// Tasks:
//
//   normalise { model }                    -> { model, indexLists }
//   run       { model, overrides }         -> { t, outputs, columns, payload, signature }
//   result    { model, now, which, project, indexLists }
//                                           -> { data, tree, t, outputs, columns, project, indexLists }
//   tree      { t, outputs, columns, which, project, indexLists, now, realisations, sample }
//                                           -> { data, tree }   realisations = { iterations, matrices: {i: typed} }
//   html      { texts }                    -> { html }          descriptionHTML of each
//   dataset   { model, inner, stamp, log, store, overrides }
//                                           -> { archive, entries, labels, columns, model }
//   restore   { archive, project }         -> { labels, columns, stats, heldAtZero, timing, signature, meta, memory }
//                                           the archive's own model unless `project` is given
//   readdataset { entries: [[name, b64]] } -> what readDataset returns, or { error }
//   describedataset { metas }              -> { lines }
//   signature { model }                    -> { signature }
//   collect   { model }                    -> { rows, modelText }   the model after, as JSON.stringify(m, null, 2)
//   apply     { model, rows, create }      -> { report, describe, modelText }
//   resolve   { model, ids }               -> { hits }
//   legal     { segments }                 -> { names }
//   pdfs      { columns, specs, jsons, lists } -> { fromColumns, toColumns, toJSON, fromJSON, fromList, usable }
//   sheet     { rows | model }             -> { grid }            a model's rows are collected here
//   fromsheet { grid, sheet }              -> { rows, problems }
//   xlsxwrite { rows | model, name, store } -> { data }
//   xlsxread  { data }                     -> { rows, problems }
//   h5write   { rows | model, root }       -> { data, tree }
//   h5read    { data }                     -> { rows, problems }
//   runlog    { project, payload, build, at, replayed, prob, scenarios }
//                                           -> { lines, scenario, prob, text }
//   audit     { audit, timeUnit }          -> { lines }
//   scenarios { model, now, which }        -> { data, tree, project, indexLists, active, names }
//                                           every scenario run, written as the page writes a table of
//                                           several: scenarioColumns and ontoAxis copied from ui/app.js
//   realisations { model, iterations, seed, keep, want, now }
//                                           -> { data, tree, t, outputs, n, project, indexLists }
//                                           a probabilistic run written as Save → Realisations writes it,
//                                           the worker's matrices on the sample's own times
//   zip       { entries: [[name, b64]], inflateLimit, store } -> { data }
//   onto      { from, to, values }         -> { values }   ontoAxis, copied from ui/app.js
//
// A row's `block` goes out as the block's qualified name. A task that throws
// answers { error, name } instead.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
const load = (file) => import(pathToFileURL(path.join(src, file)).href);
const ed = await load('domain/edit.js');
const { Project } = await load('domain/project.js');
const { buildSystem } = await load('sim/builder.js');
const { run, Results } = await load('sim/runner.js');
const { qualifiedName } = await load('domain/systems.js');
const h5 = await load('io/hdf5.js');
const RF = await load('io/resultfile.js');
const D = await load('io/dataset.js');
const DT = await load('domain/datatable.js');
const DF = await load('io/datafile.js');
const L = await load('domain/runlog.js');
const { describeAudit } = await load('domain/massbalance.js');
const { zip, unzip } = await load('io/zip.js');
const P = await load('sim/probabilistic.js');
const { scenarioModel, scenarioLabel } = await load('ui/scenarios.js');

const b64 = (u8) => Buffer.from(u8.buffer, u8.byteOffset, u8.byteLength).toString('base64');
const unb64 = (s) => new Uint8Array(Buffer.from(s, 'base64'));

function dec(v) {
	if (Array.isArray(v)) return v.map(dec);
	if (v && typeof v === 'object') {
		if ('$num' in v) return v.$num === '-0' ? -0 : Number(v.$num);
		if ('$undef' in v) return undefined;
		if ('$typed' in v) return globalThis[v.$typed].from(dec(v.v));
		return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, dec(x)]));
	}
	return v;
}

function enc(v) {
	if (typeof v === 'number') {
		if (Number.isNaN(v)) return { $num: 'NaN' };
		if (v === Infinity) return { $num: 'Infinity' };
		if (v === -Infinity) return { $num: '-Infinity' };
		if (Object.is(v, -0)) return { $num: '-0' };
		return v;
	}
	if (v === undefined) return { $undef: true };
	if (ArrayBuffer.isView(v)) return { $typed: v.constructor.name, v: Array.from(v, enc) };
	if (Array.isArray(v)) return v.map(enc);
	if (v instanceof Map) return { $map: [...v].map(([k, x]) => [enc(k), enc(x)]) };
	if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, enc(x)]));
	return v;
}

const open = (raw) => {
	const m = ed.migrateKeys(raw);
	ed.materialiseShorthand(m);
	ed.syncDerivedUnits(m);
	return m;
};
const modelOf = (req) => (req.opened ? dec(req.model) : open(dec(req.model)));

function dtName(dt) {
	for (const k of ['F64', 'F32', 'I32', 'STR']) if (h5[k] === dt) return k;
	return '?';
}

/** A tree, depth first, as plain lists. */
function dump(root) {
	const out = [];
	const walk = (n, p) => {
		if (n.kind === 'group') {
			out.push({ path: p || '/', kind: 'group', attrs: enc(n.attrs ?? {}) });
			for (const [name, child] of n.children) walk(child, `${p}/${name}`);
			return;
		}
		out.push({
			path: p, kind: 'dataset', attrs: enc(n.attrs ?? {}), dt: dtName(n.dt),
			dims: n.dims ?? null, data: enc(Array.from(n.data)),
		});
	};
	walk(root, '');
	return out;
}

const rowOut = (r) => {
	const o = {};
	for (const [k, v] of Object.entries(r)) o[k] = k === 'block' ? (v ? qualifiedName(v) : v) : v;
	return enc(o);
};

const reportOut = (rep) => ({
	values: rep.values, pdfs: rep.pdfs, tables: rep.tables, created: rep.created,
	samples: rep.samples, sampleValues: rep.sampleValues,
	unmatched: rep.unmatched, problems: rep.problems, renamed: Object.fromEntries(rep.renamed),
});

const outputOut = (o) => {
	const { offsets, ...rest } = o;
	return enc(rest);
};

function runOf(model, overrides) {
	const m = structuredClone(model);
	if (overrides) m.simulation = { ...(m.simulation ?? {}), ...overrides };
	return run(new Project(m));
}

function payloadOf(r) {
	return {
		stats: r.stats, timing: r.timing, jacobian: r.jacobian, heldAtZero: r.heldAtZero(),
		stateCount: r.system.layout.nstate, outputs: r.outputs().map((o) => o.label), t: r.t,
		massBalance: r.massBalance(),
	};
}

async function withoutCompression(store, fn) {
	const saved = globalThis.CompressionStream;
	if (store) globalThis.CompressionStream = undefined;
	try {
		return await fn();
	} finally {
		globalThis.CompressionStream = saved;
	}
}

/** The rows a request gives, or the rows the application collects from its model. */
const rowsOf = (req) => (req.model ? DT.collect(modelOf(req)) : dec(req.rows));

/** The page's `sameTimes` and `ontoAxis` (src/ui/app.js), copied: app.js is the page. */
function sameTimes(a, b) {
	if (a === b) return true;
	if (!a || !b || a.length !== b.length) return false;
	for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
	return true;
}

function ontoAxis(from, to) {
	if (sameTimes(from, to)) return (v) => v;
	const idx = new Int32Array(to.length);
	const w = new Float64Array(to.length);
	let k = 0;
	for (let j = 0; j < to.length; j++) {
		const x = to[j];
		while (k + 1 < from.length && from[k + 1] < x) k++;
		idx[j] = k;
		const a = from[k];
		const b = from[Math.min(k + 1, from.length - 1)];
		w[j] = x < from[0] || x > from[from.length - 1] ? NaN : (b > a ? (x - a) / (b - a) : 0);
	}
	return (v) => {
		if (!v) return v;
		const out = new Float64Array(to.length);
		for (let j = 0; j < to.length; j++) {
			const i = idx[j];
			const a = v[i];
			const b = v[Math.min(i + 1, v.length - 1)];
			out[j] = a + (b - a) * w[j];
		}
		return out;
	};
}

const localDate = (a) => (a ? new Date(a[0], a[1] - 1, a[2], a[3] ?? 0, a[4] ?? 0, a[5] ?? 0) : new Date(0));

async function answer(req) {
	switch (req.task) {
		case 'normalise': {
			const m = modelOf(req);
			return { model: m, indexLists: ed.indexLists(m) };
		}
		case 'run': {
			const m = modelOf(req);
			const r = runOf(m, req.overrides);
			const outs = r.outputs();
			return {
				t: enc(r.t), outputs: outs.map(outputOut), columns: enc(r.seriesMany(outs)),
				payload: enc(payloadOf(r)), signature: D.layoutSignature(r.system),
			};
		}
		case 'result': {
			const m = modelOf(req);
			const r = runOf(m, req.overrides);
			const outs = r.outputs();
			const which = req.which ?? outs.map((_, i) => i);
			const cols = r.seriesMany(outs);
			const project = req.project ? dec(req.project) : m;
			const indexLists = req.indexLists ? dec(req.indexLists) : ed.indexLists(m);
			const tree = RF.resultTree({
				t: r.t, outputs: outs, column: (i) => cols[i], which, project, indexLists,
				now: localDate(req.now),
			});
			return {
				data: b64(h5.writeHDF5(tree)), tree: dump(tree), t: enc(r.t), outputs: outs.map(outputOut),
				columns: enc(cols), project, indexLists, which,
			};
		}
		case 'tree': {
			const t = dec(req.t);
			const columns = dec(req.columns);
			const matrices = req.realisations ? dec(req.realisations.matrices) : null;
			const tree = RF.resultTree({
				t, outputs: dec(req.outputs), column: (i) => columns[i], which: req.which,
				project: dec(req.project), indexLists: dec(req.indexLists ?? []), now: localDate(req.now),
				realisations: req.realisations
					? { iterations: req.realisations.iterations, matrixFor: (i) => matrices[i] ?? null }
					: null,
				sample: req.sample ?? null,
			});
			return { data: b64(h5.writeHDF5(tree)), tree: dump(tree) };
		}
		case 'html':
			return { html: req.texts.map((s) => RF.descriptionHTML(dec(s))) };
		case 'dataset': {
			const m = modelOf(req);
			const r = runOf(m, req.overrides);
			const entries = D.datasetEntries({
				project: m, results: r, inner: req.inner, stamp: req.stamp ?? null, log: req.log ?? null,
			});
			const archive = await withoutCompression(req.store, () => zip([
				{ name: req.inner, bytes: new TextEncoder().encode(JSON.stringify(m, null, 2)) },
				...entries,
			]));
			const outs = r.outputs();
			return {
				archive: b64(archive), entries: entries.map((e) => [e.name, b64(e.bytes)]),
				labels: outs.map((o) => o.label), columns: enc(r.seriesMany(outs)), model: m,
				heldAtZero: r.heldAtZero(), stats: enc(r.stats),
			};
		}
		case 'restore': {
			const entries = await unzip(unb64(req.archive));
			const jsonName = [...entries.keys()].filter((n) => !n.startsWith('results/')).find((n) => /\.json$/i.test(n));
			const project = req.project ? dec(req.project)
				: JSON.parse(new TextDecoder().decode(entries.get(jsonName)));
			const data = D.readDataset(entries);
			const system = buildSystem(new Project(project));
			const results = D.restoreResults({ project: new Project(project), system, data, Results });
			const outs = results.outputs();
			return {
				labels: outs.map((o) => o.label), columns: enc(results.seriesMany(outs)), stats: enc(results.stats),
				heldAtZero: results.heldAtZero(), timing: enc(results.timing), signature: D.layoutSignature(system),
				meta: data.meta, memory: enc(data.memory),
			};
		}
		case 'readdataset': {
			const entries = new Map(req.entries.map(([n, b]) => [n, unb64(b)]));
			const got = D.readDataset(entries);
			return got === null ? { none: true } : enc(got);
		}
		case 'describedataset':
			return { lines: req.metas.map((m) => D.describeDataset(dec(m))) };
		case 'signature': {
			const m = modelOf(req);
			return { signature: D.layoutSignature(buildSystem(new Project(m))) };
		}
		case 'collect': {
			const m = modelOf(req);
			const rows = DT.collect(m);
			return { rows: rows.map(rowOut), modelText: JSON.stringify(m, null, 2) };
		}
		case 'apply': {
			const m = modelOf(req);
			const rep = DT.apply(m, dec(req.rows), req.create === undefined ? undefined : { create: req.create });
			return { report: enc(reportOut(rep)), describe: DT.describe(rep), modelText: JSON.stringify(m, null, 2) };
		}
		case 'resolve': {
			const m = modelOf(req);
			return {
				hits: req.ids.map((id) => {
					const hit = DT.resolve(m, dec(id));
					return hit ? enc({ ...hit, block: qualifiedName(hit.block) }) : null;
				}),
			};
		}
		case 'legal':
			return { names: req.segments.map((s) => DT.legalName(dec(s))) };
		case 'pdfs': {
			const at = (row) => (name) => row[name];
			const safe = (fn) => { try { return enc(fn()); } catch (e) { return { error: e.message, name: e.name }; } };
			return {
				fromColumns: (req.columns ?? []).map((row) => safe(() => DF.pdfFromColumns(at(dec(row))))),
				toColumns: (req.specs ?? []).map((s) => safe(() => DF.columnsFromPDF(dec(s)))),
				toJSON: (req.specs ?? []).map((s) => safe(() => DF.pdfToJSON(dec(s)))),
				usable: (req.specs ?? []).map((s) => safe(() => DF.usable(dec(s)))),
				fromJSON: (req.jsons ?? []).map((s) => safe(() => DF.pdfFromJSON(dec(s)))),
				fromList: (req.lists ?? []).map((s) => safe(() => DF.pdfListFromJSON(dec(s)))),
			};
		}
		case 'sheet':
			return { grid: enc(DF.toSheet(rowsOf(req))) };
		case 'fromsheet': {
			const got = DF.fromSheet(dec(req.grid), req.sheet === undefined ? undefined : { sheet: dec(req.sheet) });
			return { rows: got.rows.map(rowOut), problems: got.problems };
		}
		case 'xlsxwrite': {
			const rows = rowsOf(req);
			const bytes = await withoutCompression(req.store,
				() => DF.writeDataWorkbook(rows, req.name === undefined ? undefined : { name: req.name }));
			return { data: b64(bytes) };
		}
		case 'xlsxread': {
			const got = await DF.readDataWorkbook(unb64(req.data));
			return { rows: got.rows.map(rowOut), problems: got.problems };
		}
		case 'h5write': {
			const opts = req.root === undefined ? undefined : { root: req.root };
			const rows = rowsOf(req);
			const tree = DF.toTree(rows, opts);
			return { data: b64(DF.writeDataHDF5(rows, opts)), tree: dump(tree) };
		}
		case 'h5read': {
			const got = await DF.readDataHDF5(unb64(req.data));
			return { rows: got.rows.map(rowOut), problems: got.problems };
		}
		case 'runlog': {
			const at = req.at ? new Date(req.at) : new Date(0);
			const lines = L.runLogLines({
				project: dec(req.project), payload: dec(req.payload), replayed: dec(req.replayed ?? null),
				build: req.build ?? '', at,
			});
			const scenario = L.scenarioLogLines(dec(req.active ?? null), dec(req.scenarios ?? null));
			const prob = L.probabilisticLogLines(dec(req.prob ?? null));
			return { lines, scenario, prob, text: L.runLogText([...lines, ...scenario, ...prob, null]) };
		}
		case 'audit':
			return { lines: describeAudit(dec(req.audit), { timeUnit: req.timeUnit }) };
		case 'scenarios': {
			// downloadHDF5 with scenarios beside the selected one: scenarioColumns
			// with nothing hidden, then the outputs given the scenario list as one
			// more index, and the other runs read onto the selected run's times.
			const m = modelOf(req);
			const names = ed.scenarioNames(m);
			const active = ed.activeScenario(m);
			const runs = new Map(names.map((n) => [n, run(new Project(scenarioModel(m, n)))]));
			const r = runs.get(active);
			const rOut = r.outputs();
			const beside = names.filter((n) => n !== active).map((n) => {
				const er = runs.get(n);
				const eo = er.outputs();
				return { name: n, r: er, outs: eo, byLabel: new Map(eo.map((o, j) => [o.label, j])), onto: ontoAxis(er.t, r.t) };
			});
			const cols = req.which ?? rOut.map((_, i) => i);
			const spec = [];
			for (const i of cols) {
				const o = rOut[i];
				spec.push({ label: scenarioLabel(o.label, active), output: o, scenario: active, values: () => r.series(o) });
				for (const e of beside) {
					const j = e.byLabel.get(o.label);
					if (j === undefined) continue;
					spec.push({ label: scenarioLabel(o.label, e.name), output: e.outs[j], scenario: e.name,
						values: () => e.onto(e.r.series(e.outs[j])) });
				}
			}
			const list = ed.scenarioList(m)?.name ?? 'Scenarios';
			const outputs = spec.map((c) => ({
				...c.output, dims: [...(c.output.dims ?? []), list], index: [...(c.output.index ?? []), c.scenario],
				label: c.label,
			}));
			const vals = spec.map((c) => c.values());
			const indexLists = ed.indexLists(m);
			const tree = RF.resultTree({
				t: r.t, outputs, column: (k) => vals[k], which: spec.map((_, k) => k), project: m, indexLists,
				now: localDate(req.now),
			});
			return { data: b64(h5.writeHDF5(tree)), tree: dump(tree), project: m, indexLists, active, names };
		}
		case 'realisations': {
			// downloadRealisations, with the worker's `prob-matrix` answers --
			// on the sample's own times, which are the grid every realisation
			// was reported on.
			const m = modelOf(req);
			const keep = req.keep ?? null;
			const r = P.runProbabilistic(m, {
				iterations: req.iterations, seed: req.seed ?? 1,
				...(keep ? { keep: (name, out) => keep.includes(name) || keep.includes(out.label) } : {}),
			});
			const times = r.t.length;
			const n = r.iterations;
			const still = (k) => r.outputs[k]?.timeDependent === false;
			const row = (k) => {
				const v = r.values[k];
				const out = new Float32Array(n);
				for (let i = 0; i < n; i++) out[i] = v[i * times];
				return out;
			};
			const want = req.want ?? 'all';
			let column = () => new Float64Array(times).fill(NaN);
			let realisations = null;
			let sample = null;
			if (want === 'all') {
				realisations = { iterations: n, matrixFor: (k) => (still(k) ? row(k) : P.timeMajor(r.values[k], times, n)) };
			} else if (want === 'mean') {
				column = (k) => P.meanOf(r.values[k], times, n);
				sample = { iterations: n, of: 'mean' };
			} else {
				const one = Math.min(n, Math.max(1, Math.round(Number(want)) || 1)) - 1;
				column = (k) => Float64Array.from(r.values[k].subarray(one * times, (one + 1) * times));
				sample = { iterations: n, of: one + 1 };
			}
			const indexLists = ed.indexLists(m);
			const tree = RF.resultTree({
				t: r.t, outputs: r.outputs, column, which: r.outputs.map((_, k) => k), project: m, indexLists,
				now: localDate(req.now), realisations, sample,
			});
			return {
				data: b64(h5.writeHDF5(tree)), tree: dump(tree), t: enc(r.t), outputs: r.outputs.map(outputOut), n,
				project: m, indexLists,
			};
		}
		case 'zip': {
			const entries = req.entries.map(([name, b]) => ({ name, bytes: unb64(b) }));
			const data = await withoutCompression(req.store, () => zip(entries,
				req.inflateLimit ? { inflateLimit: req.inflateLimit } : {}));
			return { data: b64(data) };
		}
		case 'onto':
			return { values: enc(ontoAxis(dec(req.from), dec(req.to))(dec(req.values))) };
		default:
			throw new Error(`No task '${req.task}'`);
	}
}

async function safely(req) {
	try {
		return await answer(req);
	} catch (e) {
		return { error: e.message, name: e.name };
	}
}

const req = JSON.parse(readFileSync(0, 'utf8'));
let out;
if (req.task === 'batch') {
	// One at a time: `store` takes CompressionStream away while it writes.
	out = { results: [] };
	for (const r of req.requests) out.results.push(await safely(r));
} else {
	out = await safely(req);
}
process.stdout.write(JSON.stringify(out));
