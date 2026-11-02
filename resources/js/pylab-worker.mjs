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

   The same file runs the workers of the parallel pool (parfor), which this
   engine starts as workers of its own (init with role 'pool'): see `pool`.
   A pool worker takes { type: 'job' } (a loop's module, values and files),
   { type: 'chunk' } (a block of its passes) and { type: 'jobend' } (send
   the files the passes wrote), and answers jobready, chunkdone or chunkerr,
   and jobfiles; what its passes print goes up as { type: 'py' }.
   ========================================================================== */
import { loadPyodide } from 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs';

const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';
const HOME = '/home/user';
let py = null;
let api = null;
let queue = Promise.resolve();
let persistent = false;
let syncTimer = 0;
let BASE = '';
let VERSION = '';

const post = (m, transfer) => self.postMessage(m, transfer || []);

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

async function boot(base, version, role, index) {
  BASE = base;
  VERSION = version;
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

  if (role === 'pool') {
    // a worker of the parallel pool: no folder of its own to keep; the files come with each loop
    py.FS.mkdirTree(HOME);
    py.runPython("import sys\nif '/home/pyodide' not in sys.path: sys.path.insert(0, '/home/pyodide')");
    api = py.pyimport('plab.worker_api');
    api.pool_setup((t) => post({ type: 'py', msg: JSON.parse(t) }), HOME, index);
    post({ type: 'ready' });
    return;
  }
  py.registerJsModule('plabpool', {
    unavailable: () => pool.unavailable(),
    cores: () => pool.cores(),
    size: () => pool.size(),
    start: (n) => pool.start(n),
    stop: () => pool.stop(),
    run: (meta, ins, files, remove, use) => pool.run(meta, ins, files, remove, use),
  });

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
  let marker = '';
  try { marker = py.FS.readFile(`${HOME}/.pylab`, { encoding: 'utf8' }); } catch (e) { fresh = true; }
  // the examples: all of them in a new home folder; in one made before, those
  // added since, once each (never over a file there, never again once deleted)
  const known = new Set(marker.split('\n').filter((l) => l.startsWith('example ')).map((l) => l.slice(8)));
  const toWrite = (manifest.examples || []).filter((f) => !known.has(f));
  if (toWrite.length) {
    post({ type: 'status', text: 'Writing the examples…' });
    py.FS.mkdirTree(`${HOME}/examples`);
    await Promise.all(toWrite.map(async (f) => {
      const path = `${HOME}/examples/${f}`;
      let there = true;
      try { py.FS.stat(path); } catch (e) { there = false; }
      if (there && !fresh) return;
      const r = await fetch(url(`examples/${f}`), { cache: 'no-cache' });
      if (r.ok) py.FS.writeFile(path, await r.text());
    }));
    py.FS.writeFile(`${HOME}/.pylab`, `${marker || `examples written ${new Date().toISOString()}\n`}${toWrite.map((f) => `example ${f}\n`).join('')}`);
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
const CALLS = new Set(['complete', 'ui_event', 'var_view', 'lint', 'python_of', 'file_info', 'list_dir', 'workspace_json', 'help_text',
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

/* A file's text: UTF-8, or for a file of an older release that is not UTF-8,
   Windows-1252 (as the engine reads program files). */
function textOf(bytes) {
  try { return new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
  catch (e) { return new TextDecoder('windows-1252').decode(bytes); }
}

/* Files, through Emscripten's file system (the same one Python sees). */
function fsOp(msg) {
  const FS = py && py.FS;
  if (!FS) return post({ type: 'answer', id: msg.id, error: 'the engine is not ready' });
  try {
    let result = null;
    switch (msg.op) {
      case 'read': {
        const data = FS.readFile(msg.path, { encoding: 'binary' });
        if (msg.binary) { result = data.slice().buffer; post({ type: 'answer', id: msg.id, result }, [result]); return; }
        result = textOf(data);
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

/* ---- the parallel pool ------------------------------------------------------------------
   parfor's workers: engines of their own, started by this one as workers of
   its own. Every worker gets each loop (its files keep them up to date);
   the workers that run it (as many as the loop may use) get its blocks of
   passes as they come free; the results come back in the blocks' order. */
const pool = {
  workers: [],          // { w, index, ready, busy, settle }
  starting: null,
  job: null,

  unavailable() {
    return typeof Worker === 'undefined' ? 'this browser cannot start workers from a worker' : '';
  },

  cores() { return (self.navigator && self.navigator.hardwareConcurrency) || 2; },

  size() { return this.workers.filter((r) => r.ready).length; },

  start(n) {
    if (this.starting) return this.starting;
    this.starting = new Promise((resolve) => {
      let settled = 0;
      const settle = () => {
        settled += 1;
        if (settled < n) return;
        this.starting = null;
        this.workers = this.workers.filter((r) => r.ready);
        resolve(this.workers.length);
      };
      for (let i = 1; i <= n; i += 1) {
        let w;
        try { w = new Worker(import.meta.url, { type: 'module' }); } catch (e) { settle(); continue; }
        const rec = { w, index: i, ready: false, busy: false, settle };
        w.onmessage = (ev) => this.message(rec, ev.data);
        w.onerror = (ev) => this.failed(rec, ev.message || 'it stopped');
        w.postMessage({ type: 'init', base: BASE, version: VERSION, role: 'pool', index: i });
        this.workers.push(rec);
      }
    });
    return this.starting;
  },

  stop() {
    const job = this.job;
    for (const r of this.workers) r.w.terminate();
    this.workers = [];
    if (job) this.finish({ error: { identifier: 'parallel:pool:Stopped', message: 'The parallel pool was stopped.' } });
  },

  ready(rec) {
    if (rec.settle) { const s = rec.settle; rec.settle = null; s(); }
  },

  message(rec, m) {
    const job = this.job;
    switch (m.type) {
      case 'ready': rec.ready = true; this.ready(rec); break;
      case 'fatal': rec.ready = false; rec.w.terminate(); this.workers = this.workers.filter((r) => r !== rec); this.ready(rec); break;
      case 'py': post(m); break;                 // what a pass printed, for the Command Window
      case 'jobready': if (job && m.job === job.id) this.next(rec); break;
      case 'chunkdone':
        if (!job || m.job !== job.id) break;
        job.results[m.i] = m.data;
        job.doneBlocks += 1;
        job.donePasses += job.blocks[m.i][1];
        rec.busy = false;
        this.progress(job);
        this.next(rec);
        break;
      case 'chunkerr': {
        if (!job || m.job !== job.id) break;
        rec.busy = false;
        const e = JSON.parse(m.error);
        if (e.interrupted) job.interrupted = true;
        else if (!job.error) {
          job.error = e;
          for (const r of job.runners) if (r.busy) r.w.postMessage({ type: 'interrupt' });
        }
        this.maybeEnd(job);
        break;
      }
      case 'jobfiles':
        if (!job || m.job !== job.id) break;
        job.files.push(...m.files);
        job.waiting -= 1;
        if (job.waiting === 0) this.finish({ chunks: job.results, files: job.files });
        break;
      default: break;
    }
  },

  run(meta, ins, files, remove, use) {
    const m = JSON.parse(meta);
    return new Promise((resolve) => {
      const all = this.workers.filter((r) => r.ready);
      const job = {
        id: m.job, blocks: m.blocks, total: m.total, results: new Array(m.blocks.length).fill(null),
        next: 0, doneBlocks: 0, donePasses: 0, error: null, interrupted: false, files: [], waiting: 0,
        runners: all.slice(0, Math.max(1, use)), resolve, shown: 0,
      };
      this.job = job;
      if (!all.length) { this.finish({ error: { identifier: 'parallel:pool:NoWorkers', message: 'The parallel pool has no workers.' } }); return; }
      const filesJs = Array.from(files, (f) => [String(f[0]), f[1]]);
      for (const r of all) {
        const insCopy = ins.slice();
        const fileCopies = filesJs.map((f) => [f[0], f[1].slice()]);
        r.busy = false;
        r.w.postMessage({ type: 'job', job: job.id, meta, ins: insCopy, files: fileCopies, remove: Array.from(remove, String) },
          [insCopy.buffer, ...fileCopies.map((f) => f[1].buffer)]);
      }
      this.progress(job);
    });
  },

  /* A worker that runs the job came free: its next block, or the end of the job. */
  next(rec) {
    const job = this.job;
    if (!job || !job.runners.includes(rec) || rec.busy) return;
    if (job.error || job.interrupted || job.next >= job.blocks.length) { this.maybeEnd(job); return; }
    const i = job.next;
    job.next += 1;
    rec.busy = true;
    rec.w.postMessage({ type: 'chunk', job: job.id, i, first: job.blocks[i][0], count: job.blocks[i][1] });
  },

  maybeEnd(job) {
    if (job !== this.job || job.runners.some((r) => r.busy) || job.waiting) return;
    if (job.error || job.interrupted) { this.finish({ error: job.error, interrupted: !job.error }); return; }
    if (job.doneBlocks < job.blocks.length) return;
    // every block is in: the files the passes wrote
    job.waiting = job.runners.length;
    for (const r of job.runners) r.w.postMessage({ type: 'jobend', job: job.id });
  },

  finish(res) {
    const job = this.job;
    if (!job) return;
    this.job = null;
    post({ type: 'py', msg: { type: 'pool', end: true } });
    job.resolve(Object.assign({ interrupted: false, error: undefined, chunks: [], files: [] }, res, { error: res.error || undefined }));
  },

  progress(job) {
    const now = Date.now();
    if (now - job.shown < 250 && job.doneBlocks < job.blocks.length) return;
    job.shown = now;
    post({ type: 'py', msg: { type: 'pool', done: job.donePasses, total: job.total, workers: job.runners.length } });
  },

  /* Ctrl+C: the passes that run stop, and the loop with them. */
  interrupt() {
    const job = this.job;
    if (!job) return;
    job.interrupted = true;
    for (const r of job.runners) if (r.busy) r.w.postMessage({ type: 'interrupt' });
    this.maybeEnd(job);
  },

  /* A worker stopped (it ran out of memory, or failed to start). */
  failed(rec, why) {
    rec.w.terminate();
    rec.ready = false;
    rec.busy = false;
    this.workers = this.workers.filter((r) => r !== rec);
    this.ready(rec);
    const job = this.job;
    if (!job || !job.runners.includes(rec)) return;
    job.runners = job.runners.filter((r) => r !== rec);
    if (!job.error) {
      job.error = { identifier: 'parallel:pool:WorkerFailed', message: `A worker of the parallel pool stopped (${why}).` };
      for (const r of job.runners) if (r.busy) r.w.postMessage({ type: 'interrupt' });
    }
    this.maybeEnd(job);
  },
};

/* A pool worker's side: a loop, its blocks of passes, the files they wrote. */
function poolJob(msg) {
  try {
    api.pool_job(msg.meta, msg.ins, msg.files, msg.remove);
    post({ type: 'jobready', job: msg.job });
  } catch (e) {
    post({ type: 'chunkerr', job: msg.job, i: -1, error: JSON.stringify({ identifier: 'parallel:pool:JobFailed', message: lastLine(e) }) });
  }
}

async function poolChunk(msg) {
  let r;
  try {
    r = await api.pool_chunk(msg.job, msg.first, msg.count);
  } catch (e) {
    post({ type: 'chunkerr', job: msg.job, i: msg.i, error: JSON.stringify({ identifier: 'parallel:pool:Failed', message: lastLine(e) }) });
    return;
  }
  if (typeof r === 'string') { post({ type: 'chunkerr', job: msg.job, i: msg.i, error: r }); return; }
  const data = r.toJs();
  r.destroy();
  post({ type: 'chunkdone', job: msg.job, i: msg.i, data }, [data.buffer]);
}

function poolEnd(msg) {
  const r = api.pool_written(msg.job);
  const files = r.toJs();
  r.destroy();
  post({ type: 'jobfiles', job: msg.job, files }, files.map((f) => f[1].buffer));
}

self.onmessage = (ev) => {
  const msg = ev.data;
  switch (msg.type) {
    case 'init':
      queue = queue.then(() => boot(msg.base, msg.version, msg.role || 'main', msg.index || 0)).catch((e) => post({ type: 'fatal', message: lastLine(e) }));
      break;
    case 'job':
      queue = queue.then(() => poolJob(msg));
      break;
    case 'chunk':
      queue = queue.then(() => poolChunk(msg));
      break;
    case 'jobend':
      queue = queue.then(() => poolEnd(msg));
      break;
    case 'run':
      queue = queue.then(() => run(msg)).catch((e) => post({ type: 'done', id: msg.id, result: null, error: lastLine(e) }));
      break;
    case 'interrupt':
      if (api) api.interrupt();
      pool.interrupt();
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
