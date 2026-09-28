/* ==========================================================================
   THE HDF5 READER IN THE EXTENSION HOST

   A worker thread that answers the four questions rb-lazy-worker.js answers
   in the page -- open, group, values, close -- with the same answers, for a
   file the webview cannot read a piece at a time itself. It has to live out
   here: a worker in a VS Code webview cannot fetch the webview's resources
   at all (VS Code's service worker finds no webview for the request and it
   times out after 30 s, measured in 1.135), and the page's own thread cannot
   block on a read without stopping the frame that would deliver it.

   h5wasm's Node build reads the file straight from disk (Emscripten's
   NODERAWFS), so a file of any size opens at once and only what is looked at
   is read. The compression plugins are the page's own .so files, from the
   folder the webview is served them from.

   The answers must stay the answers rb-lazy-worker.js gives: attrValues,
   entityOf and groupOf below are its functions, and build.mjs refuses to
   build when rb-lazy-worker.js has changed since they were last compared
   (test/test-reader.py compares them).
   ========================================================================== */

import { parentPort, workerData } from 'node:worker_threads';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { encode } = require('./codec.js');

const h5wasm = await import(pathToFileURL(path.join(workerData.h5wasmDir, 'hdf5_hl.js')).href);
await h5wasm.ready;
const Module = h5wasm.Module;
// An HDF5 error is an exception here, not a log line and a buffer of
// whatever was in memory -- which is what a read with a missing filter gives.
Module.activate_throwing_error_handler();
Module.insert_plugin_search_path(workerData.pluginDir, 0);

const files = new Map();   // fid -> { file: h5wasm.File }
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

function held(fid) {
  const entry = files.get(fid);
  if (!entry) throw new Error('that file is not open here any more');
  return entry.file;
}

const handlers = {
  open({ file }) {
    const fid = ++nextFid;
    const f = new h5wasm.File(file, 'r');
    files.set(fid, { file: f });
    const paths = Module.get_names(f.file_id, '/', true).map(p => `/${p}`);
    return { fid, paths, root: groupOf(f, '/') };
  },

  group({ fid, path }) {
    return groupOf(held(fid), path);
  },

  values({ fid, paths }) {
    const f = held(fid);
    const values = {};
    const errors = {};
    for (const path of paths) {
      try {
        const obj = f.get(path);
        if (!obj || obj.type !== 'Dataset') { errors[path] = 'not a dataset'; continue; }
        values[path] = obj.value;
      } catch (e) {
        errors[path] = String(e && e.message || e);
      }
    }
    return { values, errors };
  },

  close({ fid }) {
    const entry = files.get(fid);
    if (!entry) return true;
    files.delete(fid);
    try { entry.file.close(); } catch (_) { /* closed already */ }
    return true;
  }
};

/*
  The buffers under an encoded answer's typed arrays, so they move rather than
  copy. Never h5wasm's own memory: h5wasm hands out copies, and encode() copies
  any view onto part of a buffer, but moving the heap would detach it and take
  every open file down with it, so it is checked for all the same -- at the
  time, since the heap is a new buffer each time the memory grows.
*/
function transferables(value, out = [], heap = Module.HEAPU8 ? Module.HEAPU8.buffer : null) {
  if (ArrayBuffer.isView(value)) {
    if (value.buffer !== heap && !out.includes(value.buffer)) out.push(value.buffer);
  } else if (Array.isArray(value)) {
    for (const v of value) transferables(v, out, heap);
  } else if (value && typeof value === 'object' && !(value instanceof ArrayBuffer)) {
    for (const v of Object.values(value)) transferables(v, out, heap);
  }
  return out;
}

parentPort.on('message', ({ id, cmd, args }) => {
  try {
    const handler = handlers[cmd];
    if (!handler) throw new Error(`unknown command ${cmd}`);
    const ok = encode(handler(args || {}));
    parentPort.postMessage({ id, ok }, transferables(ok));
  } catch (e) {
    parentPort.postMessage({ id, err: String(e && e.message || e) });
  }
});

parentPort.postMessage({ ready: true });
