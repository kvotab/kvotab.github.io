/* tree-worker.js
   Web Worker to perform expensive HDF5 tree traversal and intersection
   without blocking the main thread. Expects messages:
     { cmd: 'computeIntersect', id, files: [{ name, buffer (ArrayBuffer) }, ...] }
     { cmd: 'cancel' }
   Replies with:
     { cmd: 'progress', id, fileIndex, totalFiles }
     { cmd: 'result', id, intersectedPaths: [...] }
     { cmd: 'error', id, message }
     { cmd: 'cancelled', id }
*/

self._cancelWorker = false;

// indicate worker thread start (main thread can observe immediately)
try { self.postMessage({ cmd: 'started' }); } catch (e) { /* ignore */ }

// load h5wasm inside the worker (IIFE build)
try {
  importScripts('https://cdn.jsdelivr.net/npm/h5wasm@latest/dist/iife/h5wasm.min.js');
} catch (e) {
  // importScripts may throw in restricted environments; we'll surface an error on compute requests
  console.warn('tree-worker: failed to import h5wasm via importScripts', e);
}

async function waitForH5Wasm() {
  let attempts = 0;
  while (typeof self.h5wasm === 'undefined' && attempts < 50) {
    await new Promise(r => setTimeout(r, 100));
    attempts++;
  }
  if (typeof self.h5wasm === 'undefined') throw new Error('h5wasm not available in worker');
  if (self.h5wasm.ready instanceof Promise) await self.h5wasm.ready;
  return self.h5wasm;
}

// notify main thread when h5wasm becomes available inside the worker
(async function notifyH5Ready(){
  try {
    await waitForH5Wasm();
    try { self.postMessage({ cmd: 'h5ready' }); } catch (e) { /* ignore */ }
  } catch (e) {
    /* no-op */
  }
})();

function collectAllPathsSync(group, prefix = '') {
  const paths = new Set();
  try {
    const keys = (typeof group.keys === 'function') ? Array.from(group.keys()).sort() : [];
    for (const key of keys) {
      if (self._cancelWorker) throw new Error('cancelled');
      const path = prefix ? `${prefix}/${key}` : `/${key}`;
      paths.add(path);
      try {
        const obj = group.get(key);
        if (obj && String(obj.type).toLowerCase() === 'group') {
          for (const sp of collectAllPathsSync(obj, path)) paths.add(sp);
        }
      } catch (e) {
        // skip unreadable members
      }
    }
  } catch (e) {
    if (String(e && e.message || '').toLowerCase().includes('cancel')) throw e;
  }
  return paths;
}

self.onmessage = async function (ev) {
  const msg = ev.data || {};
  try {
    if (msg.cmd === 'cancel') {
      self._cancelWorker = true;
      // ack
      self.postMessage({ cmd: 'cancelled', id: msg.id || null });
      return;
    }

    if (msg.cmd === 'computeIntersect') {
      self._cancelWorker = false;
      const id = msg.id || null;
      const files = Array.isArray(msg.files) ? msg.files : [];

      // ensure h5wasm available
      try {
        await waitForH5Wasm();
      } catch (err) {
        self.postMessage({ cmd: 'error', id, message: err.message || String(err) });
        return;
      }

      const { FS, File } = self.h5wasm;
      if (!FS || !File) {
        self.postMessage({ cmd: 'error', id, message: 'h5wasm FS/File not available in worker' });
        return;
      }

      try {
        const pathSets = [];
        for (let i = 0; i < files.length; ++i) {
          if (self._cancelWorker) throw new Error('cancelled');
          const fobj = files[i];
          const buf = fobj && fobj.buffer;
          if (!buf || !(buf instanceof ArrayBuffer)) {
            // skip this file (not provided); report progress
            self.postMessage({ cmd: 'progress', id, fileIndex: i + 1, totalFiles: files.length });
            pathSets.push(new Set());
            continue;
          }

          const fname = `/worker_file_${Date.now()}_${i}.h5`;
          try {
            FS.writeFile(fname, new Uint8Array(buf));
            const hf = new File(fname, 'r');
            const pset = collectAllPathsSync(hf, '');
            pathSets.push(pset);
            // cleanup file from worker FS
            try { FS.unlink(fname); } catch (e) { /* ignore */ }
          } catch (fileErr) {
            // if one file fails, continue but include empty set
            pathSets.push(new Set());
          }

          self.postMessage({ cmd: 'progress', id, fileIndex: i + 1, totalFiles: files.length });
        }

        if (self._cancelWorker) throw new Error('cancelled');

        // compute intersection
        let intersection = null;
        for (const s of pathSets) {
          if (intersection === null) intersection = new Set(s);
          else {
            for (const p of Array.from(intersection)) {
              if (!s.has(p)) intersection.delete(p);
            }
          }
        }
        intersection = intersection || new Set();

        self.postMessage({ cmd: 'result', id, intersectedPaths: Array.from(intersection) });
      } catch (err) {
        if (String(err && err.message || '').toLowerCase().includes('cancel')) {
          self.postMessage({ cmd: 'cancelled', id });
        } else {
          self.postMessage({ cmd: 'error', id, message: err.message || String(err) });
        }
      }
    }
  } catch (outerErr) {
    self.postMessage({ cmd: 'error', id: (msg && msg.id) || null, message: outerErr.message || String(outerErr) });
  }
};
