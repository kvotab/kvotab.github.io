// The application's own file formats, for the Python package's tests to compare with.
//
//   node io_formats.mjs <kompartment src directory> < request.json
//
// A request is { task, ... } -- or { task: 'batch', requests: [...] } for several
// at once -- and the answer one JSON object on stdout. Binary data travels as
// base64. Values that JSON cannot carry are tagged, both ways:
//
//   { "$num": "NaN" | "Infinity" | "-Infinity" | "-0" }    a number
//   { "$undef": true }                                      undefined
//   { "$typed": "Float32Array", "v": [...] }                a typed array
//   { "$gen": "strings", "n": 60001, "prefix": "s" }       a long list, made on the spot
//   { "$gen": "numbers", "n": 100000 }                     (i * 7919 % 1000) / 7 - 50
//
// Tasks:
//
//   h5write   { tree }            -> { data }        tree = { attrs, puts: [[path, node], ...] },
//                                                      node = { kind: 'group', attrs } or
//                                                      { kind: 'dataset', data, dt, attrs, dims, array }
//   h5read    { data }            -> { datasets, problems }
//   lookup3   { data, from, length } -> { value }
//   xlsxwrite { book, modified, store } -> { data }  modified = [y, month 1-12, d, h, mi, s] or null;
//                                                      store: as on a platform with no CompressionStream
//   xlsxread  { data }            -> { sheets }
//   xlsxhelp  { escapes, refs, columns } -> { escaped, columnOf, columnName }
//   csvcells  { values }          -> { cells }       csvCell of each
//   csvrows   { rows }            -> { lines }       row.join(','), as the page joins its rows
//   csvtable  { t, labels, columns } -> { text }     Results.prototype.toCSV on these columns
//
// A task that throws answers { error, name } instead.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
const load = (file) => import(pathToFileURL(path.join(src, file)).href);
const h5 = await load('io/hdf5.js');
const { readHDF5 } = await load('io/hdf5read.js');
const xlsx = await load('io/xlsx.js');
const { csvCell } = await load('io/csv.js');
const { Results } = await load('sim/runner.js');

const b64 = (u8) => Buffer.from(u8.buffer, u8.byteOffset, u8.byteLength).toString('base64');
const unb64 = (s) => new Uint8Array(Buffer.from(s, 'base64'));

function generate(g) {
	const out = [];
	for (let i = 0; i < g.n; i++) out.push(g.$gen === 'strings' ? `${g.prefix ?? ''}${i}` : ((i * 7919) % 1000) / 7 - 50);
	return out;
}

function dec(v) {
	if (Array.isArray(v)) return v.map(dec);
	if (v && typeof v === 'object') {
		if ('$num' in v) return v.$num === '-0' ? -0 : Number(v.$num);
		if ('$undef' in v) return undefined;
		if ('$typed' in v) return globalThis[v.$typed].from(dec(v.v));
		if ('$gen' in v) return generate(v);
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
	if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, enc(x)]));
	return v;
}

function node(n) {
	if (n.kind === 'group') return h5.group(dec(n.attrs ?? {}));
	let data = dec(n.data);
	if (n.array) data = globalThis[n.array].from(data);
	return h5.dataset(data, h5[n.dt ?? 'F64'], dec(n.attrs ?? {}), n.dims ?? null);
}

function tree(spec) {
	const root = h5.group(dec(spec.attrs ?? {}));
	for (const [where, n] of spec.puts ?? []) h5.put(root, where, node(n));
	return root;
}

async function answer(req) {
	switch (req.task) {
		case 'h5write':
			return { data: b64(h5.writeHDF5(tree(req.tree))) };
		case 'h5read': {
			const { datasets, problems } = await readHDF5(unb64(req.data));
			return {
				datasets: datasets.map((d) => ({ path: d.path, values: enc(d.values), dims: enc(d.dims), attrs: enc(d.attrs) })),
				problems,
			};
		}
		case 'lookup3': {
			const u8 = unb64(req.data);
			return { value: h5.lookup3(u8, req.from ?? 0, req.length ?? u8.length - (req.from ?? 0)) };
		}
		case 'xlsxwrite': {
			const opts = req.modified ? { modified: new Date(req.modified[0], req.modified[1] - 1, ...req.modified.slice(2)) } : {};
			const saved = globalThis.CompressionStream;
			if (req.store) globalThis.CompressionStream = undefined;
			try {
				return { data: b64(await xlsx.writeWorkbook(dec(req.book), opts)) };
			} finally {
				globalThis.CompressionStream = saved;
			}
		}
		case 'xlsxread':
			return enc(await xlsx.readWorkbook(unb64(req.data)));
		case 'xlsxhelp':
			return {
				escaped: (req.escapes ?? []).map(([s, attr]) => xlsx.xmlEscape(dec(s), attr)),
				columnOf: (req.refs ?? []).map((r) => xlsx.columnOf(r)),
				columnName: (req.columns ?? []).map((i) => xlsx.columnName(dec(i))),
			};
		case 'csvcells':
			return { cells: dec(req.values).map((v) => csvCell(v)) };
		case 'csvrows':
			return { lines: dec(req.rows).map((r) => r.join(',')) };
		case 'csvtable': {
			const outputs = req.labels.map((label) => ({ label: dec(label) }));
			const columns = dec(req.columns);
			const self = Object.assign(Object.create(Results.prototype), {
				t: dec(req.t), seriesMany: () => columns,
			});
			return { text: Results.prototype.toCSV.call(self, outputs) };
		}
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
