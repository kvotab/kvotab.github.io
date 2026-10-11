/* The page's HDF5 reader (resources/js/smui-hdf5-read.js) outside the
   browser: h5wasm's Node build opens the file, and the same inspect(),
   defaults(), plan() and read() the worker runs make its tables.

     node hdf5-read.mjs <h5wasm dir> read <file> [state.json]
     node hdf5-read.mjs <h5wasm dir> sniff <file>
     node hdf5-read.mjs <h5wasm dir> unpickle <file>

   read prints { nodes, info, defaults, plan, tables, failed } as JSON, a
   Float64Array as a list (NaN null, infinities 'inf' and '-inf');
   state.json { "picked": [paths] | "all", "transposed": [paths],
   "together": true } picks the tables (without it, the ones the open
   dialog ticks). sniff prints what the first bytes say; unpickle the
   pickle's value (a Map as { "$map": [[k, v] …] }, bytes as { "$bytes":
   [...] }). test_hdf5.py drives it. */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const [dir, mode, file, stateFile] = process.argv.slice(2);
globalThis.self = globalThis;
vm.runInThisContext(readFileSync(path.join(here, '..', '..', 'js', 'smui-hdf5-read.js'), 'utf8'), { filename: 'smui-hdf5-read.js' });
const H = globalThis.SM.h5;

const plain = (v) => {
  if (v instanceof Map) return { $map: [...v].map(([k, x]) => [plain(k), plain(x)]) };
  if (v instanceof Uint8Array) return { $bytes: Array.from(v) };
  if (ArrayBuffer.isView(v)) return Array.from(v, (x) => (Number.isNaN(x) ? null : x === Infinity ? 'inf' : x === -Infinity ? '-inf' : x));
  if (Array.isArray(v)) return v.map(plain);
  if (typeof v === 'number') return Number.isNaN(v) ? null : v === Infinity ? 'inf' : v === -Infinity ? '-inf' : v;
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, plain(x)]));
  return v;
};

if (mode === 'sniff') {
  process.stdout.write(JSON.stringify({ kind: H.sniff(new Uint8Array(readFileSync(file).subarray(0, 65544))) }));
} else if (mode === 'unpickle') {
  let out;
  try {
    const v = H.unpickle(new Uint8Array(readFileSync(file)));
    out = { value: plain(v), array: plain(H.numpyArray(v)) };
  } catch (e) {
    out = { error: String(e && e.message || e) };
  }
  process.stdout.write(JSON.stringify(out));
} else {
  const h5wasm = await import(pathToFileURL(path.join(dir, 'hdf5_hl.js')).href);
  const Module = await h5wasm.ready;
  Module.activate_throwing_error_handler();
  const f = new h5wasm.File(path.resolve(file), 'r');
  const io = H.ioFor(h5wasm, Module, f);
  const { nodes, info } = await H.inspect(io);
  const def = H.defaults(nodes, info);
  let state = def;
  if (stateFile) {
    const s = JSON.parse(readFileSync(stateFile, 'utf8'));
    const byPath = new Map(nodes.map((n) => [n.path, n.id]));
    const ids = (list) => new Set((list || []).map((p) => { if (!byPath.has(p)) throw new Error(`no ${p}`); return byPath.get(p); }));
    state = {
      picked: s.picked === 'all' ? new Set(nodes.filter((n) => n.readable && !n.hidden && n.form).map((n) => n.id)) : ids(s.picked),
      transposed: s.transposed ? ids(s.transposed) : def.transposed,
      together: s.together !== false,
    };
  }
  const name = path.basename(file);
  const planned = H.plan(nodes, state, { fileName: name });
  let tables = [], failed = [], error = null;
  try {
    ({ tables, failed } = await H.read(io, nodes, info, planned, { fileName: name }));
  } catch (e) {
    error = String(e && e.message || e);
  }
  f.close();
  process.stdout.write(JSON.stringify({
    info,
    nodes: nodes.map((n) => ({ path: n.path, kind: n.kind, form: n.form || null, rows: n.rows ?? null, cols: n.cols ?? null, readable: !!n.readable, why: n.why || null,
      hidden: n.hidden || null, key: !!n.key, meta: n.meta || null, transposed: !!n.transposed, typeText: n.typeText || null, target: n.target || null })),
    defaults: { picked: [...def.picked].map((id) => nodes[id].path).sort(), transposed: [...def.transposed].map((id) => nodes[id].path).sort(), direct: !!def.direct },
    plan: { ...planned, tables: planned.tables.map((t) => ({ ...t, items: t.items.map((it) => ({ path: nodes[it.id].path, transposed: it.transposed })), key: t.key == null ? null : nodes[t.key].path })) },
    tables: tables.map((t) => ({ ...t, columns: t.columns.map((c) => ({ ...c, values: plain(c.values) })) })),
    failed,
    error,
  }));
}
