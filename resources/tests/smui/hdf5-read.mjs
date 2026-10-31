/* The page's HDF5 reader (resources/js/smui-hdf5-read.js) outside the
   browser: h5wasm's Node build opens the file, and the same inspect(),
   defaults(), plan() and read() the worker runs make its tables.

     node hdf5-read.mjs <h5wasm dir> read <file> [state.json]
     node hdf5-read.mjs <h5wasm dir> read-hdf5 <file> [state.json]
     node hdf5-read.mjs <h5wasm dir> sniff <file>
     node hdf5-read.mjs <h5wasm dir> unpickle <file>

   read opens a file as the page does: a MAT-file (SM.h5.matFormat) is
   written as an HDF5 file first, by smui-mat.js with the HDF5 Browser's
   reader, as the worker writes it; read-hdf5 opens it as the HDF5 file it
   is (a -v7.3 file too large to read whole opens so). read prints { mat,
   nodes, info, defaults, plan, tables, failed } as JSON, mat being { format,
   header, variables, unread } or { error }, a
   Float64Array as a list (NaN null, infinities 'inf' and '-inf');
   state.json { "picked": [paths] | "all", "transposed": [paths],
   "together": true } picks the tables (without it, the ones the open
   dialog ticks). sniff prints what the first bytes say; unpickle the
   pickle's value (a Map as { "$map": [[k, v] …] }, bytes as { "$bytes":
   [...] }). test_hdf5.py drives it. */
import { mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync } from 'node:fs';
import os from 'node:os';
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

/* A MAT-file written as an HDF5 file in dir, as the worker writes it:
   { target, mat } or { mat: { error } }. rb-mat.js keeps a -v7.3 file's
   bytes among h5wasm's files at /, which are in memory in the browser and
   on disk here: here they go into dir. */
async function writeMat(h5wasm, bytes, name, dir) {
  const at = (p) => path.join(dir, p.replace(/^\/+/, ''));
  globalThis.window = { h5wasm: { FS: { writeFile: (p, d) => writeFileSync(at(p), d), unlink: (p) => unlinkSync(at(p)) },
    File: class extends h5wasm.File { constructor(p, m) { super(at(p), m); } } } };
  for (const js of ['kvot-safe.js', 'rb-mat.js', 'smui-mat.js']) vm.runInThisContext(readFileSync(path.join(here, '..', '..', 'js', js), 'utf8'), { filename: js });
  const target = path.join(dir, 'mat.h5');
  try {
    return { target, mat: await globalThis.SM.mat.write(h5wasm, bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length), target, { fileName: name }) };
  } catch (e) {
    return { mat: { error: String(e && e.message || e) } };
  }
}

if (mode === 'sniff') {
  const head = new Uint8Array(readFileSync(file).subarray(0, 65544));
  process.stdout.write(JSON.stringify({ kind: H.sniff(head), mat: H.matFormat(head, path.basename(file)) }));
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
  const name = path.basename(file);
  const bytes = readFileSync(file);
  const tmp = mode === 'read' && H.matFormat(new Uint8Array(bytes.subarray(0, 65544)), name) ? mkdtempSync(path.join(os.tmpdir(), 'smui-mat-')) : null;
  try {
    const { target, mat } = tmp ? await writeMat(h5wasm, bytes, name, tmp) : { target: path.resolve(file), mat: null };
    if (target) await readFile(h5wasm, Module, target, name, mat);
    else process.stdout.write(JSON.stringify({ mat }));
  } finally {
    if (tmp) rmSync(tmp, { recursive: true, force: true });
  }
}

async function readFile(h5wasm, Module, target, name, mat) {
  const f = new h5wasm.File(target, 'r');
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
  const planned = H.plan(nodes, state, { fileName: name });
  let tables = [], failed = [], error = null;
  try {
    ({ tables, failed } = await H.read(io, nodes, info, planned, { fileName: name }));
  } catch (e) {
    error = String(e && e.message || e);
  }
  f.close();
  process.stdout.write(JSON.stringify({
    mat,
    info,
    nodes: nodes.map((n) => ({ path: n.path, kind: n.kind, form: n.form || null, rows: n.rows ?? null, cols: n.cols ?? null, readable: !!n.readable, why: n.why || null,
      hidden: n.hidden || null, key: !!n.key, meta: n.meta || null, transposed: !!n.transposed, typeText: n.typeText || null, target: n.target || null,
      matlab: n.matlab || null, mixed: !!n.mixed, header: n.header || null, note: (n.attrs && n.attrs.MATLAB_note) ?? null })),
    defaults: { picked: [...def.picked].map((id) => nodes[id].path).sort(), transposed: [...def.transposed].map((id) => nodes[id].path).sort(), direct: !!def.direct },
    plan: { ...planned, tables: planned.tables.map((t) => ({ ...t, items: t.items.map((it) => ({ path: nodes[it.id].path, transposed: it.transposed })), key: t.key == null ? null : nodes[t.key].path })) },
    tables: tables.map((t) => ({ ...t, columns: t.columns.map((c) => ({ ...c, values: plain(c.values) })) })),
    failed,
    error,
  }));
}
