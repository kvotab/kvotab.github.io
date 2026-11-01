/* ==========================================================================
   PYLAB.HTML: THE PYTHON ENGINE (a module worker)

   Pyodide with numpy and scipy, and the interpreter package
   (resources/py/plab), which compiles the programs to Python and runs them.
   The user's files live in /home/user, kept in the browser's IndexedDB
   between visits.

   Messages in (queued: one runs at a time):
     { type: 'init', base, version }              load everything, then 'ready'
     { type: 'run', id, code, opts }              a command line (opts.silent)
   Messages in (answered at once, also while a program runs, between steps):
     { type: 'interrupt' }                        Ctrl+C
     { type: 'reply', id, value }                 an answer to 'input' or 'request'
     { type: 'call', id, fn, args }               a worker_api function that
                                                  returns JSON (complete, var_view,
                                                  lint, python_of, file_info, ...)
     { type: 'fs', id, op, ... }                  files: ls, read, write, mkdir,
                                                  rename, remove, upload, download
   Messages out:
     { type: 'status', text }                     while loading
     { type: 'ready', info, versions }
     { type: 'py', msg }                          from Python: out, figures, input,
                                                  request, dbg, dbgwait, cwd, files,
                                                  edit, clc, raise, web
     { type: 'done', id, result }                 a run ended
     { type: 'answer', id, result | error }       a call or fs answered
     { type: 'fatal', message }
   ========================================================================== */
import { loadPyodide } from 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs';

const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';
const HOME = '/home/user';
let py = null;
let api = null;
let queue = Promise.resolve();
let persistent = false;
let syncTimer = 0;

const post = (m) => self.postMessage(m);

function lastLine(e) {
  const s = String((e && e.message) || e);
  const lines = s.trim().split('\n').filter((l) => l.trim());
  return lines[lines.length - 1] || s;
}

/* The home folder goes back to IndexedDB a moment after it changes. */
function scheduleSync() {
  if (!persistent) return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => {
    py.FS.syncfs(false, (err) => { if (err) post({ type: 'py', msg: { type: 'out', kind: 'warn', text: `Warning: the files could not be saved in the browser (${err}).\n` } }); });
  }, 300);
}

async function boot(base, version) {
  post({ type: 'status', text: 'Loading Python (Pyodide)…' });
  py = await loadPyodide({ indexURL: PYODIDE });
  post({ type: 'status', text: 'Loading NumPy and SciPy…' });
  await py.loadPackage(['numpy', 'scipy'], {
    messageCallback: () => {},
    errorCallback: (text) => post({ type: 'py', msg: { type: 'out', kind: 'internal', text: text + '\n' } }),
  });
  post({ type: 'status', text: 'Loading the interpreter…' });
  const url = (f) => `${base}resources/py/plab/${f}?v=${encodeURIComponent(version)}`;
  const manifest = await (await fetch(url('manifest.json'), { cache: 'no-cache' })).json();
  py.FS.mkdirTree('/home/pyodide/plab/builtins');
  const missing = [];
  await Promise.all(manifest.files.map(async (f) => {
    const r = await fetch(url(f), { cache: 'no-cache' });
    if (!r.ok) { missing.push(`${f} (HTTP ${r.status})`); return; }
    py.FS.writeFile(`/home/pyodide/plab/${f}`, await r.text());
  }));
  if (missing.length) throw new Error(`the interpreter did not load: resources/py/plab/${missing.join(', ')}`);

  // the user's folder, kept in IndexedDB
  py.FS.mkdirTree(HOME);
  try {
    py.FS.mount(py.FS.filesystems.IDBFS, {}, HOME);
    await new Promise((resolve, reject) => py.FS.syncfs(true, (err) => (err ? reject(err) : resolve())));
    persistent = true;
  } catch (e) {
    persistent = false;
    post({ type: 'py', msg: { type: 'out', kind: 'warn', text: 'Warning: this browser does not keep files between visits here (no IndexedDB); they last until the tab closes.\n' } });
  }
  let fresh = false;
  try { py.FS.stat(`${HOME}/.pylab`); } catch (e) { fresh = true; }
  if (fresh) {
    post({ type: 'status', text: 'Writing the examples…' });
    py.FS.mkdirTree(`${HOME}/examples`);
    await Promise.all((manifest.examples || []).map(async (f) => {
      const r = await fetch(url(`examples/${f}`), { cache: 'no-cache' });
      if (r.ok) py.FS.writeFile(`${HOME}/examples/${f}`, await r.text());
    }));
    py.FS.writeFile(`${HOME}/.pylab`, `examples written ${new Date().toISOString()}\n`);
    scheduleSync();
  }
  post({ type: 'status', text: 'Starting…' });
  py.runPython("import sys\nif '/home/pyodide' not in sys.path: sys.path.insert(0, '/home/pyodide')");
  api = py.pyimport('plab.worker_api');
  const info = JSON.parse(api.setup((s) => post({ type: 'py', msg: JSON.parse(s) }), HOME));
  const versions = JSON.parse(py.runPython(
    "import json, sys, numpy, scipy\njson.dumps({'python': sys.version.split()[0], 'numpy': numpy.__version__, 'scipy': scipy.__version__})"));
  versions.pyodide = '314.0.7';
  info.persistent = persistent;
  info.fresh = fresh;
  post({ type: 'ready', info, versions });
}

async function run(msg) {
  let result = null;
  try {
    const r = await api.run(msg.code, JSON.stringify(msg.opts || {}));
    result = JSON.parse(r);
  } catch (e) {
    post({ type: 'py', msg: { type: 'out', kind: 'err', text: `Internal error: ${lastLine(e)}\n` } });
  }
  scheduleSync();
  post({ type: 'done', id: msg.id, result });
}

/* Calls to worker_api functions that return JSON text. */
const CALLS = new Set(['complete', 'var_view', 'lint', 'python_of', 'file_info', 'list_dir', 'workspace_json', 'help_text',
  'all_figures', 'figure_event', 'set_format', 'set_cwd', 'set_breakpoints', 'debug_command', 'files_changed']);

/* A call may answer { need: package } first (h5py, for MAT-files of version
   7.3): the package is loaded and the call made again. */
const NEEDS = new Set(['h5py']);

async function call(msg) {
  if (!api) return post({ type: 'answer', id: msg.id, error: 'the engine is not ready' });
  if (!CALLS.has(msg.fn)) return post({ type: 'answer', id: msg.id, error: `unknown call ${msg.fn}` });
  const once = () => {
    const r = api[msg.fn](...(msg.args || []));
    if (typeof r !== 'string') return r;
    try { return JSON.parse(r); } catch (e) { return r; }
  };
  try {
    let result = once();
    if (result && NEEDS.has(result.need)) {
      await py.loadPackage(result.need, { messageCallback: () => {} });
      result = once();
    }
    if (msg.fn === 'set_cwd' || msg.fn === 'files_changed') scheduleSync();
    post({ type: 'answer', id: msg.id, result });
  } catch (e) {
    post({ type: 'answer', id: msg.id, error: lastLine(e) });
  }
}

/* Files, through Emscripten's file system (the same one Python sees). */
function fsOp(msg) {
  const FS = py && py.FS;
  if (!FS) return post({ type: 'answer', id: msg.id, error: 'the engine is not ready' });
  try {
    let result = null;
    switch (msg.op) {
      case 'read': {
        const data = FS.readFile(msg.path, { encoding: msg.binary ? 'binary' : 'utf8' });
        result = msg.binary ? data.slice().buffer : data;
        if (msg.binary) { post({ type: 'answer', id: msg.id, result }, [result]); return; }
        break;
      }
      case 'write': {
        const dir = msg.path.slice(0, msg.path.lastIndexOf('/')) || '/';
        FS.mkdirTree(dir);
        FS.writeFile(msg.path, msg.binary ? new Uint8Array(msg.data) : msg.data);
        result = true;
        break;
      }
      case 'mkdir': FS.mkdirTree(msg.path); result = true; break;
      case 'rename': FS.rename(msg.from, msg.to); result = true; break;
      case 'remove': {
        const rm = (p) => {
          const st = FS.stat(p);
          if (FS.isDir(st.mode)) {
            for (const n of FS.readdir(p)) if (n !== '.' && n !== '..') rm(`${p}/${n}`);
            FS.rmdir(p);
          } else FS.unlink(p);
        };
        rm(msg.path);
        result = true;
        break;
      }
      case 'exists': {
        try { const st = FS.stat(msg.path); result = FS.isDir(st.mode) ? 'dir' : 'file'; } catch (e) { result = false; }
        break;
      }
      default: throw new Error(`unknown file operation ${msg.op}`);
    }
    if (msg.op !== 'read' && msg.op !== 'exists') {
      if (api) api.files_changed();
      scheduleSync();
    }
    post({ type: 'answer', id: msg.id, result });
  } catch (e) {
    const code = e && e.errno ? ` (${e.code || e.errno})` : '';
    post({ type: 'answer', id: msg.id, error: `${lastLine(e)}${code}` });
  }
}

self.onmessage = (ev) => {
  const msg = ev.data;
  switch (msg.type) {
    case 'init':
      queue = queue.then(() => boot(msg.base, msg.version)).catch((e) => post({ type: 'fatal', message: lastLine(e) }));
      break;
    case 'run':
      queue = queue.then(() => run(msg)).catch((e) => post({ type: 'done', id: msg.id, result: null, error: lastLine(e) }));
      break;
    case 'interrupt':
      if (api) api.interrupt();
      break;
    case 'reply':
      if (api) api.reply(msg.id, JSON.stringify(msg.value === undefined ? null : msg.value));
      break;
    case 'call':
      call(msg);
      break;
    case 'fs':
      fsOp(msg);
      break;
    default:
      break;
  }
};
