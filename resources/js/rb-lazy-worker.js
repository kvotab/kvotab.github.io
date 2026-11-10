/* ==========================================================================
   RB LAZY WORKER — a large local HDF5 file read from disk a piece at a time
   --------------------------------------------------------------------------
   The Data Browser reads a file it is given into memory whole, twice over
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

   A file can also be read over the network, a piece at a time, as the Data
   Browser reads a large file from the reader's Google Drive (rb-drive.js):
   the page gives its address, its size and the headers that carry the
   reader's access to it, and each block is a request for that range of its
   bytes. The request is synchronous, as a read from disk is here -- HDF5
   reads synchronously, and a worker may wait -- and the headers are sent to
   that address and to no other.
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
/** As many blocks as fit in this, least recently used dropped first. */
const KEEP_BYTES = 64 * BLOCK;
/** A read larger than this -- a dataset's values -- goes straight to the file. */
const DIRECT = 4 * BLOCK;

/*
  A file read over the network. A request that fails is an I/O error to HDF5
  (EIO, WASI's number for it, which is Emscripten's): HDF5 then fails the read
  as it would one from a damaged disk, and unwinds as it should, where a
  JavaScript exception thrown through it would leave it half way. Why the
  request failed is kept here and is what the page is told.
*/
const EIO = 29;
let remoteFailure = null;

/*
  Over the network every block missed is a round trip, so blocks are fetched
  differently there. Opening a file lists all its paths, and HDF5 reads every
  object's header to do it: in a file written a group at a time those headers
  are spread through the file, between the data, and HDF5 goes back and forth
  between a group's own records and its members' headers.

    REMOTE_BLOCK  smaller blocks: a header is a few hundred bytes, and with the
                  datasets large, a block of a megabyte is mostly their data.
    REMOTE_RUNS   the runs of misses followed at once. A miss on the block
                  just after a run fetched doubles how many blocks its next
                  request brings, up to REMOTE_AHEAD; any other miss asks for
                  one block and starts a run of its own.
    REMOTE_DIRECT a read larger than this -- a dataset's values -- is one
                  request of its own, past the cache.

  Measured on two files, 100 ms added to every request. 103 MB of 2000
  datasets of 50 KB, its headers every 50 KB: opening it fetched all of it
  whatever the blocks (102 requests one megabyte at a time, 571 with blocks of
  128 KB and one run, 52 with eight runs). 404 MB of 100 datasets of 4 MB:
  18 MB in 103 requests with these settings, against 111 MB in 105 with
  blocks of a megabyte, and then each dataset's values in one request. So the
  bytes are what the file's layout makes them, and the requests are kept to
  about one per stretch of headers.
*/
const REMOTE_BLOCK = 1 << 17;
const REMOTE_AHEAD = 64;
const REMOTE_RUNS = 8;
const REMOTE_DIRECT = 1 << 20;

/** Why a request failed, in a few words: its status and, from a JSON error body, its reason. */
function remoteReason(xhr) {
  let reason = '';
  try {
    const body = JSON.parse(new TextDecoder().decode(xhr.response).slice(0, 20000));
    const error = body && body.error;
    if (error && Array.isArray(error.errors) && error.errors[0]) reason = String(error.errors[0].reason || '');
  } catch (_) { /* not JSON: the status says it */ }
  return `HTTP ${xhr.status}${reason ? ` (${reason})` : ''}`;
}

/**
 * Bytes [start, end) of a file read over the network, in one request for
 * that range, sent with the headers the page gave for this file and no other.
 */
function readRemote(remote, start, end) {
  const xhr = new XMLHttpRequest();
  xhr.open('GET', remote.url, false);
  xhr.responseType = 'arraybuffer';
  for (const [name, value] of Object.entries(remote.headers || {})) xhr.setRequestHeader(name, value);
  xhr.setRequestHeader('Range', `bytes=${start}-${end - 1}`);
  try {
    xhr.send();
  } catch (e) {
    remoteFailure = 'the connection failed';
    throw new FS.ErrnoError(EIO);
  }
  // 206 for the range; a 200 only when the range was the whole file.
  if (xhr.status === 206 || (xhr.status === 200 && start === 0 && end >= remote.size)) {
    const bytes = new Uint8Array(xhr.response);
    if (bytes.length === end - start) return bytes;
    remoteFailure = `${bytes.length} bytes came where ${end - start} were asked for`;
    throw new FS.ErrnoError(EIO);
  }
  remoteFailure = remoteReason(xhr);
  throw new FS.ErrnoError(EIO);
}

/** What the page is told of a failure: the request's, when one failed under it. */
function failureMessage(e) {
  return remoteFailure ? `could not be read over the network: ${remoteFailure}` : String(e && e.message || e);
}

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
  // A node's contents are the File picked, or { size, remote } for a file
  // read over the network.
  const bytesOf = (node, start, end) => (node.contents.remote
    ? readRemote(node.contents.remote, start, end)
    : new Uint8Array(reader.readAsArrayBuffer(node.contents.slice(start, end))));
  const blocks = new Map();   // `${node.id}:${index}` -> Uint8Array, least recently used first
  let kept = 0;
  const keep = (key, b) => {
    blocks.set(key, b);
    kept += b.length;
    while (kept > KEEP_BYTES && blocks.size > 1) {
      const [oldest, old] = blocks.entries().next().value;
      blocks.delete(oldest);
      kept -= old.length;
    }
  };
  const ahead = new Map();    // node.id -> [{ next, span }]: a file over the network's runs of misses, latest last
  const blockOf = (node, index) => {
    const key = `${node.id}:${index}`;
    let b = blocks.get(key);
    if (b) {
      blocks.delete(key);
      blocks.set(key, b);
      return b;
    }
    if (node.contents.remote) {
      const start = index * REMOTE_BLOCK;
      let runs = ahead.get(node.id);
      if (!runs) ahead.set(node.id, runs = []);
      let run = runs.find(r => r.next === index);
      if (run) {
        runs.splice(runs.indexOf(run), 1);
        run.span = Math.min(2 * run.span, REMOTE_AHEAD);
      } else {
        run = { next: index, span: 1 };
        if (runs.length >= REMOTE_RUNS) runs.shift();
      }
      runs.push(run);
      // As many as the run asks for, up to the end of the file or a block held already.
      const last = Math.min(index + run.span, Math.ceil(node.size / REMOTE_BLOCK));
      let count = 1;
      while (index + count < last && !blocks.has(`${node.id}:${index + count}`)) count++;
      const bytes = bytesOf(node, start, Math.min(node.size, start + count * REMOTE_BLOCK));
      // Each block its own copy, so that one kept does not keep the others' bytes.
      for (let k = count - 1; k >= 0; k--) {
        const piece = bytes.slice(k * REMOTE_BLOCK, Math.min(bytes.length, (k + 1) * REMOTE_BLOCK));
        if (k === 0) b = piece;
        else keep(`${node.id}:${index + k}`, piece);
      }
      keep(key, b);
      // The run goes on past any blocks held already.
      let next = index + count;
      while (next < last && blocks.has(`${node.id}:${next}`)) next++;
      run.next = next;
      return b;
    }
    const start = index * BLOCK;
    b = bytesOf(node, start, Math.min(node.size, start + BLOCK));
    keep(key, b);
    return b;
  };
  W.stream_ops.read = (stream, buffer, offset, length, position) => {
    const node = stream.node;
    if (position >= node.size) return 0;
    const end = Math.min(node.size, position + length);
    if (end - position > (node.contents.remote ? REMOTE_DIRECT : DIRECT)) {
      buffer.set(bytesOf(node, position, end), offset);
      return end - position;
    }
    const size = node.contents.remote ? REMOTE_BLOCK : BLOCK;
    for (let at = position; at < end;) {
      const index = Math.floor(at / size);
      const b = blockOf(node, index);
      const from = at - index * size;
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
  /**
   * A File picked from disk, or `remote`: { url, headers, size } of a file
   * read over the network.
   */
  async open({ file, remote }) {
    const fid = ++nextFid;
    const name = `f${fid}`;
    const contents = remote
      ? { size: remote.size, remote: { url: remote.url, headers: remote.headers || {}, size: remote.size } }
      : file;
    FS.filesystems.WORKERFS.createNode(mountRoot, name, FS.filesystems.WORKERFS.FILE_MODE, 0, contents);
    try {
      const f = new self.h5wasm.File(`/work/${name}`, 'r');
      files.set(fid, { file: f, name, remote: contents.remote || null });
      const paths = Module.get_names(f.file_id, '/', true).map(p => `/${p}`);
      return { fid, paths, root: groupOf(f, '/') };
    } catch (e) {
      const held = files.get(fid);
      files.delete(fid);
      try { if (held) held.file.close(); } catch (_) { /* never opened */ }
      try { FS.unlink(`/work/${name}`); } catch (_) { /* gone already */ }
      throw e;
    }
  },

  /** New headers for a file read over the network: the reader's access, renewed. */
  async headers({ fid, headers }) {
    const held = files.get(fid);
    if (!held || !held.remote) throw new Error('no such file read over the network');
    held.remote.headers = headers || {};
    return true;
  },

  async group({ fid, path }) {
    return groupOf(files.get(fid).file, path);
  },

  async values({ fid, paths }) {
    const f = files.get(fid).file;
    const values = {};
    const errors = {};
    for (const path of paths) {
      // Once a request has failed the rest would too, each asking again.
      if (remoteFailure) { errors[path] = failureMessage(); continue; }
      try {
        await ensurePlugins(f, path);
        const obj = f.get(path);
        if (!obj || obj.type !== 'Dataset') { errors[path] = 'not a dataset'; continue; }
        values[path] = obj.value;
      } catch (e) {
        errors[path] = failureMessage(e);
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
    remoteFailure = null;
    const handler = handlers[cmd];
    if (!handler) throw new Error(`unknown command ${cmd}`);
    const answer = await handler(event.data);
    if (answer && answer.transfer) self.postMessage({ id, ok: answer.result }, answer.transfer);
    else self.postMessage({ id, ok: answer });
  } catch (e) {
    self.postMessage({ id, err: failureMessage(e) });
  }
};
