/* ==========================================================================
   RB LAZY WORKER — a large local HDF5 file read from disk a piece at a time
   --------------------------------------------------------------------------
   The HDF5 Browser reads a file it is given into memory whole, twice over
   (its own bytes, and h5wasm's copy), which is why it stopped at 1 GB. A file
   the reader picks from disk does not have to be read that way. Here h5wasm
   opens it through Emscripten's WORKERFS, which reads the File object with
   FileReaderSync -- only possible in a worker -- at the offsets HDF5 asks for,
   so a 2.4 GB file opens in milliseconds and only what is looked at is read.
   This is how the HDF Group's myHDF5 (H5Web's H5WasmLocalFileProvider) reads
   local files; see rb-lazy.js for the page's side.

   One thing is added to that. HDF5 reads its metadata a few hundred bytes at
   a time, and through WORKERFS every read is a FileReaderSync call of its own:
   listing the 52 000 objects of a file of small datasets took 21 s. Reads go
   through a cache of 1 MB blocks instead, and the same listing takes 0.3 s,
   about what it takes with the whole file in memory.

   The answers are h5wasm's own: every entity is got with File.get, every
   attribute value with Attribute.value, every dataset value with
   Dataset.value, exactly as the page does for a file in memory.
   ========================================================================== */

'use strict';

/*
  h5wasm, pinned as the page's <script> tag pins it. importScripts cannot
  check a hash, so the bytes are fetched with `integrity` -- the browser
  refuses anything but this build -- and run from those bytes.
*/
const H5WASM_URL = 'https://cdn.jsdelivr.net/npm/h5wasm@0.10.3/dist/iife/h5wasm.min.js';
const H5WASM_INTEGRITY = 'sha384-ddY2IJ7uyvBrG5FPTk2LGWBUTJBV+MchV38zJwXMPuFYM9YwIH4iN9RxvDe01UEW';

async function loadH5wasm() {
  const response = await fetch(H5WASM_URL, { integrity: H5WASM_INTEGRITY });
  if (!response.ok) throw new Error(`h5wasm: HTTP ${response.status}`);
  const url = URL.createObjectURL(await response.blob());
  try {
    importScripts(url);
  } finally {
    URL.revokeObjectURL(url);
  }
  return self.h5wasm;
}

/** The block cache: HDF5's reads are served from these, a few thousand to a block. */
const BLOCK = 1 << 20;
const KEEP_BLOCKS = 64;
/** A read larger than this -- a dataset's values -- goes straight to the file. */
const DIRECT = 4 * BLOCK;

/*
  Compression filters h5wasm has no decoder for, and the plugin that has one.
  The same table as rb-lazy.js (a worker cannot share the page's scripts); the
  plugins are h5wasm-plugins, the set myHDF5 loads. deflate, shuffle,
  fletcher32, szip, nbit and scale-offset are built in.
*/
const PLUGIN_BY_FILTER = {
  307: 'bz2', 32000: 'lzf', 32001: 'blosc', 32004: 'lz4', 32008: 'bshuf', 32013: 'zfp',
  32015: 'zstd', 32019: 'jpeg', 32022: 'bitgroom', 32023: 'bitround', 32026: 'blosc2'
};
const PLUGIN_BASE = 'https://cdn.jsdelivr.net/npm/h5wasm-plugins@0.3.0/plugins/';
const PLUGIN_DIR = '/plugins';

/* Compiled code that runs here, so taken only as these bytes: see rb-lazy.js. */
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
  zstd: 'sha384-lATu8NneZ295vv50ikKrsmgFwKFv+xy+H3BlMk4HZU6x+uwhk5OudWcavmXFuUQD'
};

let Module = null;
let FS = null;
let mountRoot = null;

const ready = (async () => {
  const lib = await loadH5wasm();
  const m = await lib.ready;
  Module = m.Module || m;
  FS = lib.FS;
  // An HDF5 error is an exception here, not a log line and a buffer of
  // whatever was in memory -- which is what a read with a missing filter gives.
  Module.activate_throwing_error_handler();
  FS.mkdirTree(PLUGIN_DIR);
  Module.insert_plugin_search_path(PLUGIN_DIR, 0);

  const W = FS.filesystems.WORKERFS;
  const reader = new FileReaderSync();
  const blocks = new Map();   // `${node.id}:${index}` -> Uint8Array, least recently used first
  const blockOf = (node, index) => {
    const key = `${node.id}:${index}`;
    let b = blocks.get(key);
    if (b) {
      blocks.delete(key);
      blocks.set(key, b);
      return b;
    }
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
})();

const files = new Map();   // fid -> { file: h5wasm.File, node name }
let nextFid = 0;

/** An attribute holder's values, as the page reads them: name -> Attribute.value. */
function attrValues(obj) {
  const out = {};
  if (!obj || !obj.attrs) return out;
  const attrs = obj.attrs;
  for (const name of Object.keys(attrs)) {
    try {
      out[name] = attrs[name].value;
    } catch (e) {
      out[name] = `(unreadable: ${e && e.message ? e.message : e})`;
    }
  }
  return out;
}

/** What the page needs to know of one entity without reading its values. */
function entityOf(f, path, name) {
  let obj = null;
  try { obj = f.get(path); } catch (e) { return { name, type: null, error: String(e && e.message || e) }; }
  if (!obj) return { name, type: null };
  const e = { name, type: obj.type };
  if (obj.type === 'Dataset') {
    e.shape = obj.shape;
    e.dtype = obj.dtype;
    try { e.filters = Module.get_dataset_filters(f.file_id, path).map(x => x.id); } catch (_) { e.filters = []; }
  } else if (obj.type === 'BrokenSoftLink') {
    e.target = obj.target;
  } else if (obj.type === 'ExternalLink') {
    e.filename = obj.filename;
    e.obj_path = obj.obj_path;
  }
  if (obj.attrs) e.attrs = attrValues(obj);
  return e;
}

/** A group, and its children one level down. */
function groupOf(f, path) {
  const group = path === '/' ? f : f.get(path);
  if (!group || group.type !== 'Group') return { path, missing: true };
  const children = [];
  for (const name of group.keys()) {
    children.push(entityOf(f, path === '/' ? `/${name}` : `${path}/${name}`, name));
  }
  return { path, attrs: attrValues(group), children };
}

const pluginLoads = new Map();

/** The plugins a dataset's filters need, fetched and installed once each. */
async function ensurePlugins(f, path) {
  let ids = [];
  try { ids = Module.get_dataset_filters(f.file_id, path).map(x => x.id); } catch (_) { return; }
  const wanted = ids.map(id => PLUGIN_BY_FILTER[id]).filter(Boolean);
  await Promise.all(wanted.map((name) => {
    if (!pluginLoads.has(name)) {
      pluginLoads.set(name, (async () => {
        const integrity = PLUGIN_INTEGRITY[name];
        if (!integrity) throw new Error(`compression plugin ${name} is not on the pinned list`);
        const res = await fetch(`${PLUGIN_BASE}libH5Z${name}.so`, { integrity });
        if (!res.ok) throw new Error(`compression plugin ${name}: HTTP ${res.status}`);
        FS.writeFile(`${PLUGIN_DIR}/libH5Z${name}.so`, new Uint8Array(await res.arrayBuffer()));
      })());
    }
    return pluginLoads.get(name);
  }));
}

/** Everything the page's structured clone should not copy: typed arrays' buffers. */
function transferables(values) {
  const out = [];
  for (const v of Object.values(values)) {
    if (ArrayBuffer.isView(v) && !out.includes(v.buffer)) out.push(v.buffer);
  }
  return out;
}

const handlers = {
  async open({ file }) {
    const fid = ++nextFid;
    const name = `f${fid}`;
    FS.filesystems.WORKERFS.createNode(mountRoot, name, FS.filesystems.WORKERFS.FILE_MODE, 0, file);
    const f = new self.h5wasm.File(`/work/${name}`, 'r');
    files.set(fid, { file: f, name });
    const paths = Module.get_names(f.file_id, '/', true).map(p => `/${p}`);
    return { fid, paths, root: groupOf(f, '/') };
  },

  async group({ fid, path }) {
    return groupOf(files.get(fid).file, path);
  },

  async values({ fid, paths }) {
    const f = files.get(fid).file;
    const values = {};
    const errors = {};
    for (const path of paths) {
      try {
        await ensurePlugins(f, path);
        const obj = f.get(path);
        if (!obj || obj.type !== 'Dataset') { errors[path] = 'not a dataset'; continue; }
        values[path] = obj.value;
      } catch (e) {
        errors[path] = String(e && e.message || e);
      }
    }
    return { result: { values, errors }, transfer: transferables(values) };
  },

  async close({ fid }) {
    const held = files.get(fid);
    if (!held) return true;
    files.delete(fid);
    try { held.file.close(); } catch (_) { /* closed already */ }
    try { FS.unlink(`/work/${held.name}`); } catch (_) { /* gone already */ }
    return true;
  }
};

self.onmessage = async (event) => {
  const { id, cmd } = event.data || {};
  try {
    await ready;
    const handler = handlers[cmd];
    if (!handler) throw new Error(`unknown command ${cmd}`);
    const answer = await handler(event.data);
    if (answer && answer.transfer) self.postMessage({ id, ok: answer.result }, answer.transfer);
    else self.postMessage({ id, ok: answer });
  } catch (e) {
    self.postMessage({ id, err: String(e && e.message || e) });
  }
};
