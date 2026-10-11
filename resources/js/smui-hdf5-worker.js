/* ==========================================================================
   SMUI.HTML: THE HDF5 WORKER

   Opens an HDF5 file the page hands over (a File) with h5wasm and reads
   tables out of it with smui-hdf5-read.js, off the page's thread: a large
   file does not freeze the page, and Cancel ends the worker.

   The file is not read into memory. h5wasm opens it through Emscripten's
   WORKERFS, which reads the File where HDF5 asks (FileReaderSync, only in a
   worker), through a cache of 1 MB blocks: HDF5 reads its metadata a few
   hundred bytes at a time. This is the HDF5 Browser's way (rb-lazy-worker.js),
   learnt from the HDF Group's myHDF5, and its h5wasm build and compression
   plugins are the ones pinned here.

   Messages in:   { id, cmd: 'open', file }       -> { fid, nodes, info, defaults }
                  { id, cmd: 'read', fid, plan }  -> { tables, failed }
                  { id, cmd: 'close', fid }
   Messages out:  { id, ok } or { id, err }; { id, progress: { done, total, text } }
   ========================================================================== */
'use strict';

/*
  h5wasm, pinned as rb.html pins it. importScripts cannot check a hash, so
  the bytes are fetched with `integrity` -- the browser refuses anything but
  this build -- and run from those bytes.
*/
const H5WASM_URL = 'https://cdn.jsdelivr.net/npm/h5wasm@0.10.3/dist/iife/h5wasm.min.js';
const H5WASM_INTEGRITY = 'sha384-ddY2IJ7uyvBrG5FPTk2LGWBUTJBV+MchV38zJwXMPuFYM9YwIH4iN9RxvDe01UEW';

/*
  Compression filters h5wasm has no decoder for, and the plugin that has
  one (h5wasm-plugins, as rb-lazy-worker.js has them); deflate, shuffle,
  fletcher32, szip, nbit and scale-offset are built in. A plugin is
  compiled code that runs here, so it is taken only as these bytes.
*/
const PLUGIN_BY_FILTER = {
  307: 'bz2', 32000: 'lzf', 32001: 'blosc', 32004: 'lz4', 32008: 'bshuf', 32013: 'zfp',
  32015: 'zstd', 32019: 'jpeg', 32022: 'bitgroom', 32023: 'bitround', 32026: 'blosc2',
};
const PLUGIN_BASE = 'https://cdn.jsdelivr.net/npm/h5wasm-plugins@0.3.0/plugins/';
const PLUGIN_DIR = '/plugins';
const PLUGIN_INTEGRITY = {
  bitgroom: 'sha384-gNVA0b4+QaFu+OqRBa6z9MSwYKsg+8aE2to15a+f6kmegamiV/gEJ3GyQXFf3P4Q',
  bitround: 'sha384-jOdazp5y+urUPmu+cRMJI+AxtCaJOH/A53ifSZe7h2SM7jPn9z+DCQjn7pczLOfq',
  blosc: 'sha384-wStCBpJ6TXigvLRdS025mvqHzK/bWK0+I/xVf1YY+/DOZGvYHmKsEZext0ZmTIrd',
  blosc2: 'sha384-Qk31oU1SEUrFCOuzUfD3xMxQTBGb0Rob7AYOZItYgaiBVJO5ShQripoqu/NySi1N',
  bshuf: 'sha384-ujAH1xIbo/qv/A10zkYe1rCobTu2vAxLGG9hLxxmhCSV5NZkOcF+SHuyBNZd48TN',
  bz2: 'sha384-4fmIBQ1G5JPoReqrAkX4brSLR7JfRsL1G1GWYkVQojVCAYdi2G08VquHo4E+Kpff',
  jpeg: 'sha384-5MaIx7yJfKrt2qIC6lTrwQpM7qJeO9wXu0AKwI3z1E2L/DFnnX6pW9EsnUuXL6cX',
  lz4: 'sha384-LA4TWzTbFqq/OCPETk+C/hoAzE323YWP3qYhVWkg7WTwn5zLqGvPQZH/IqOOQy+q',
  lzf: 'sha384-o9C1ZWqHrVZCHNETc8YTW7D/9J2vSpUXkiBBGsU6nznl4qNYXk6gr9mnyFEz+PTQ',
  zfp: 'sha384-A7oBFcSbwTKy3wdnMAEyHSNy1/gEjXOYL/8Sgj6Bwjvlx+LgeGmtc7XHan0ARdpR',
  zstd: 'sha384-lATu8NneZ295vv50ikKrsmgFwKFv+xy+H3BlMk4HZU6x+uwhk5OudWcavmXFuUQD',
};

// the reading itself, same origin and the same build stamp as this file
importScripts(`smui-hdf5-read.js${self.location.search}`);
const H = self.SM.h5;

/** The block cache: HDF5's reads are served from these. */
const BLOCK = 1 << 20;
const KEEP_BLOCKS = 64;
/** A read larger than this (a dataset's values) goes straight to the file. */
const DIRECT = 4 * BLOCK;

let Module = null;
let FS = null;
let mountRoot = null;

const ready = (async () => {
  const response = await fetch(H5WASM_URL, { integrity: H5WASM_INTEGRITY });
  if (!response.ok) throw new Error(`the HDF5 reader (h5wasm) did not load: HTTP ${response.status}`);
  const url = URL.createObjectURL(await response.blob());
  try { importScripts(url); } finally { URL.revokeObjectURL(url); }
  const lib = self.h5wasm;
  const m = await lib.ready;
  Module = m.Module || m;
  FS = lib.FS;
  // an HDF5 error is an exception here, not a log line and a buffer of
  // whatever was in memory (which is what a read with a missing filter gives)
  Module.activate_throwing_error_handler();
  FS.mkdirTree(PLUGIN_DIR);
  Module.insert_plugin_search_path(PLUGIN_DIR, 0);
  const W = FS.filesystems.WORKERFS;
  const reader = new FileReaderSync();
  const blocks = new Map();   // `${node.id}:${index}` -> Uint8Array, least recently used first
  const blockOf = (node, index) => {
    const key = `${node.id}:${index}`;
    let b = blocks.get(key);
    if (b) { blocks.delete(key); blocks.set(key, b); return b; }
    const start = index * BLOCK;
    b = new Uint8Array(reader.readAsArrayBuffer(node.contents.slice(start, Math.min(node.size, start + BLOCK))));
    blocks.set(key, b);
    if (blocks.size > KEEP_BLOCKS) blocks.delete(blocks.keys().next().value);
    return b;
  };
  W.stream_ops.read = (stream, buffer, offset, length, position) => {
    const node = stream.node;
    if (position >= node.size) return 0;
    const end = Math.min(node.size, position + length);
    if (end - position > DIRECT) {
      buffer.set(new Uint8Array(reader.readAsArrayBuffer(node.contents.slice(position, end))), offset);
      return end - position;
    }
    for (let at = position; at < end;) {
      const index = Math.floor(at / BLOCK);
      const b = blockOf(node, index);
      const from = at - index * BLOCK;
      const n = Math.min(end - at, b.length - from);
      buffer.set(b.subarray(from, from + n), offset + (at - position));
      at += n;
    }
    return end - position;
  };
  FS.mkdir('/work');
  mountRoot = FS.mount(W, {}, '/work');
  return lib;
})();

const pluginLoads = new Map();
/** The plugins a dataset's filters need, fetched and installed once each. */
async function ensurePlugins(fileId, path) {
  let ids = [];
  try { ids = Module.get_dataset_filters(fileId, path).map((x) => x.id); } catch (_) { return; }
  const wanted = ids.map((id) => PLUGIN_BY_FILTER[id]).filter(Boolean);
  await Promise.all(wanted.map((name) => {
    if (!pluginLoads.has(name)) {
      pluginLoads.set(name, (async () => {
        const integrity = PLUGIN_INTEGRITY[name];
        if (!integrity) throw new Error(`compression plugin ${name} is not on the pinned list`);
        const res = await fetch(`${PLUGIN_BASE}libH5Z${name}.so`, { integrity });
        if (!res.ok) throw new Error(`compression plugin ${name}: HTTP ${res.status}`);
        FS.writeFile(`${PLUGIN_DIR}/libH5Z${name}.so`, new Uint8Array(await res.arrayBuffer()));
      })().catch((e) => { pluginLoads.delete(name); throw e; }));
    }
    return pluginLoads.get(name);
  }));
}

const files = new Map();   // fid -> { file, name, io, nodes, info }
let nextFid = 0;

/* What the page needs of a node: plan() and the dialog's lines, not the
   datatype's insides. Attribute values are cut short for the dialog. */
function forPage(n) {
  const attrs = {};
  for (const [k, v] of Object.entries(n.attrs || {})) {
    if (v == null) continue;
    attrs[k] = typeof v === 'string' ? v.slice(0, 300) : Array.isArray(v) ? v.slice(0, 20).map((x) => (typeof x === 'string' ? x.slice(0, 120) : x)) : v;
  }
  const out = {
    id: n.id, path: n.path, name: n.name, parent: n.parent, depth: n.depth, children: n.children, order: n.order, kind: n.kind, attrs,
    attrCount: (n.attrNames || []).length,
  };
  for (const k of ['target', 'shape', 'dims', 'kept', 'scales', 'form', 'rows', 'cols', 'readable', 'why', 'hidden', 'key', 'meta', 'transposed',
    'typeText', 'numeric', 'isScale', 'scaleName', 'matlab', 'chars', 'filters']) if (n[k] !== undefined) out[k] = n[k];
  if (n.pandas) out.pandas = { type: n.pandas.type };
  return out;
}

/** Typed arrays' buffers, to move to the page rather than copy. */
function transferables(tables) {
  const out = [];
  for (const t of tables) for (const c of t.columns) if (ArrayBuffer.isView(c.values) && !out.includes(c.values.buffer)) out.push(c.values.buffer);
  return out;
}

const handlers = {
  async open({ id, file }) {
    const lib = await ready;
    const fid = ++nextFid;
    const name = `f${fid}`;
    FS.filesystems.WORKERFS.createNode(mountRoot, name, FS.filesystems.WORKERFS.FILE_MODE, 0, file);
    let f;
    try {
      f = new lib.File(`/work/${name}`, 'r');
    } catch (e) {
      try { FS.unlink(`/work/${name}`); } catch (_) { /* gone already */ }
      throw new Error(`not an HDF5 file this reader can open (${String(e && e.message || e).split('\n').filter(Boolean).pop()})`);
    }
    const io = H.ioFor(lib, Module, f, { ensurePlugins: (path) => ensurePlugins(f.file_id, path) });
    const progress = (done, total) => self.postMessage({ id, progress: { done, total, text: `Listing the file: ${done.toLocaleString('en-US')} of ${total.toLocaleString('en-US')} objects` } });
    const { nodes, info } = await H.inspect(io, { onProgress: progress });
    files.set(fid, { file: f, name, io, nodes, info });
    const d = H.defaults(nodes, info);
    return { fid, info, nodes: nodes.map(forPage), defaults: { picked: [...d.picked], transposed: [...d.transposed], together: d.together, direct: !!d.direct } };
  },

  async read({ id, fid, plan, fileName }) {
    const held = files.get(fid);
    if (!held) throw new Error('the file is closed');
    const progress = (done, total, path) => self.postMessage({ id, progress: { done, total, text: `Reading ${path}` } });
    const result = await H.read(held.io, held.nodes, held.info, plan, { fileName, onProgress: progress });
    return { result, transfer: transferables(result.tables) };
  },

  async close({ fid }) {
    const held = files.get(fid);
    if (!held) return true;
    files.delete(fid);
    try { held.file.close(); } catch (_) { /* closed already */ }
    try { FS.unlink(`/work/${held.name}`); } catch (_) { /* gone already */ }
    return true;
  },
};

self.onmessage = async (event) => {
  const msg = event.data || {};
  const { id, cmd } = msg;
  try {
    const handler = handlers[cmd];
    if (!handler) throw new Error(`unknown command ${cmd}`);
    const answer = await handler(msg);
    if (answer && answer.transfer) self.postMessage({ id, ok: answer.result }, answer.transfer);
    else self.postMessage({ id, ok: answer });
  } catch (e) {
    self.postMessage({ id, err: String((e && e.message) || e) });
  }
};
