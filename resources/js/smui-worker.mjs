/* ==========================================================================
   SMUI.HTML: THE PYTHON ENGINE (a module worker)

   Pyodide with numpy, scipy, pandas and statsmodels, and the page's own
   analysis package (resources/py/smui). A module worker, because Chrome
   refuses Pyodide's classic-script loader through importScripts (the
   response is blocked as opaque); an ES module import is a CORS request
   and loads.

   Messages in:
     { type: 'init', base, version }        load everything, then 'ready'
     { type: 'table', id, version, meta, arrays }   a table, new or changed
     { type: 'call', id, fn, payload }      run smui.registry.dispatch
     { type: 'callb', id, fn, payload, bytes }   the same with a file's bytes
     { type: 'nbrun', id, nb, code, files, info }   a notebook cell (smui.notebook.run_cell):
                                            files [{name, text}] are written first (the
                                            tables' CSV), then the packages its imports need
   Messages out:
     { type: 'status', stage, text }        while loading
     { type: 'ready', versions, names, failed }
     { type: 'loading', text }              a package a call needs, on its first use
     { type: 'loaded', versions }           ... and when it is in (versions of what came)
     { type: 'result', id, json }  or  { type: 'error', id, message, traceback }
     { type: 'log', stream, text }          Python's stdout and stderr

   Messages are handled one at a time, in order: Python is single-threaded
   and a call must see the table sent before it. A function that needs a
   package beyond the four (scikit-learn) says so in the registry; the
   package is loaded before the first such call runs.
   ========================================================================== */
import { loadPyodide } from 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs';

const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';
const PACKAGES = ['numpy', 'scipy', 'pandas', 'statsmodels'];
let py = null;
let dispatch = null;
let dispatchBytes = null;
let setTable = null;
let packagesFor = null;
let runCell = null;
const extra = new Set();     // the packages loaded after the start
let queue = Promise.resolve();

const post = (m) => self.postMessage(m);

async function boot(base, version) {
  post({ type: 'status', stage: 'runtime', text: 'Loading the Python runtime (Pyodide)…' });
  py = await loadPyodide({
    indexURL: PYODIDE,
    stdout: (text) => post({ type: 'log', stream: 'stdout', text }),
    stderr: (text) => post({ type: 'log', stream: 'stderr', text }),
  });
  post({ type: 'status', stage: 'packages', text: 'Loading numpy, scipy, pandas and statsmodels…' });
  await py.loadPackage(PACKAGES, {
    messageCallback: (text) => post({ type: 'status', stage: 'packages', text }),
    errorCallback: (text) => post({ type: 'log', stream: 'stderr', text }),
  });
  post({ type: 'status', stage: 'backend', text: 'Loading the analyses…' });
  const url = (f) => `${base}resources/py/smui/${f}?v=${encodeURIComponent(version)}`;
  // Revalidated on every start: the files are small, and a stale module
  // next to a new page would fail in ways that are hard to see.
  const manifest = await (await fetch(url('manifest.json'), { cache: 'no-cache' })).json();
  py.FS.mkdirTree('/home/pyodide/smui');
  const missing = new Set();
  const status = {};
  await Promise.all(manifest.files.map(async (f) => {
    const r = await fetch(url(f), { cache: 'no-cache' });
    if (!r.ok) { missing.add(f); status[f] = r.status; return; }
    py.FS.writeFile(`/home/pyodide/smui/${f}`, await r.text());
  }));
  // Without these the package cannot start. (A site built by Jekyll, as
  // GitHub Pages does without a .nojekyll file, leaves out __init__.py:
  // Python then took smui for an empty namespace package, and the page
  // said only "module 'smui' has no attribute 'names'".)
  const core = ['__init__.py', 'registry.py', 'util.py', 'data.py'].filter((f) => missing.has(f));
  if (core.length) throw new Error(`the analysis package did not load: ${core.map((f) => `resources/py/smui/${f} (HTTP ${status[f]})`).join(', ')}`);
  py.runPython("import sys\nif '/home/pyodide' not in sys.path: sys.path.insert(0, '/home/pyodide')\nimport smui");
  const failed = [];
  for (const m of manifest.modules) {
    if (missing.has(`${m}.py`)) { failed.push({ module: m, error: 'not written yet' }); continue; }
    try {
      py.runPython(`import importlib; importlib.import_module('smui.${m}')`);
    } catch (e) {
      failed.push({ module: m, error: lastLine(e) });
    }
  }
  post({ type: 'status', stage: 'warm', text: 'Importing statsmodels…' });
  py.runPython('import statsmodels.api, statsmodels.formula.api, statsmodels.stats.api');
  dispatch = py.pyimport('smui.registry').dispatch;
  dispatchBytes = py.pyimport('smui.registry').dispatch_bytes;
  setTable = py.pyimport('smui.data').set_table;
  packagesFor = py.pyimport('smui.registry').packages_for;
  try { runCell = py.pyimport('smui.notebook').run_cell; } catch (e) { runCell = null; }   // the analyses run without it
  const versions = JSON.parse(py.runPython(
    "import json, sys, numpy, scipy, pandas, statsmodels, patsy\n" +
    "json.dumps({'python': sys.version.split()[0], 'numpy': numpy.__version__, 'scipy': scipy.__version__, " +
    "'pandas': pandas.__version__, 'statsmodels': statsmodels.__version__, 'patsy': patsy.__version__})"));
  versions.pyodide = '314.0.7';
  const names = JSON.parse(py.runPython('import json, smui\njson.dumps(smui.names())'));
  post({ type: 'ready', versions, names, failed });
}

/* The packages a call needs that are not in yet: load them (from the same
   Pyodide release, so they match), and tell the page which versions came. */
async function ensurePackages(fn) {
  const need = JSON.parse(packagesFor(fn)).filter((p) => !extra.has(p));
  if (!need.length) return;
  post({ type: 'loading', text: `Loading ${need.join(', ')} (first use)…` });
  const errors = [];
  let versions = {};
  try {
    await py.loadPackage(need, {
      messageCallback: (text) => post({ type: 'loading', text }),
      errorCallback: (text) => { errors.push(text); post({ type: 'log', stream: 'stderr', text }); },
    });
    versions = JSON.parse(py.runPython(
      `import json, importlib.metadata as md\nout = {}\nfor p in ${JSON.stringify(need)}:\n    try: out[p] = md.version(p)\n    except Exception: pass\njson.dumps(out)`));
  } finally {
    post({ type: 'loaded', versions });
  }
  const missing = need.filter((p) => !versions[p]);
  if (missing.length) throw new Error(`${missing.join(', ')} could not be loaded${errors.length ? `: ${errors[errors.length - 1]}` : ' (is the network there?)'}`);
  for (const p of need) extra.add(p);
}

function lastLine(e) {
  const s = String((e && e.message) || e);
  const lines = s.trim().split('\n').filter((l) => l.trim());
  return lines[lines.length - 1] || s;
}

async function handle(msg) {
  if (msg.type === 'init') {
    return boot(msg.base, msg.version).catch((e) => post({ type: 'fatal', message: lastLine(e), traceback: String(e && e.message || e) }));
  }
  if (msg.type === 'table') {
    if (!setTable) return null;
    // A Float64Array reaches Python as a memoryview of doubles, which numpy
    // takes without a copy through a list; text columns go as lists.
    // A JS null would arrive as Pyodide's jsnull, not None: undefined does.
    const arrays = msg.arrays.map((a) => py.toPy(a instanceof Float64Array ? a : a.map((v) => (v === null ? undefined : v))));
    try {
      setTable(msg.id, msg.version, py.toPy(msg.meta), arrays);
    } finally {
      for (const a of arrays) if (a && a.destroy) a.destroy();
    }
    return null;
  }
  if (msg.type === 'nbrun') return notebookCell(msg);
  if (msg.type === 'call' || msg.type === 'callb') {
    if (!dispatch) { post({ type: 'error', id: msg.id, message: 'the engine is not ready' }); return null; }
    try {
      await ensurePackages(msg.fn);
      let json;
      if (msg.type === 'callb') {
        const bytes = py.toPy(new Uint8Array(msg.bytes));
        try { json = dispatchBytes(msg.fn, JSON.stringify(msg.payload || {}), bytes); } finally { if (bytes && bytes.destroy) bytes.destroy(); }
      } else json = dispatch(msg.fn, JSON.stringify(msg.payload || {}));
      post({ type: 'result', id: msg.id, json });
    } catch (e) {
      const text = String((e && e.message) || e);
      post({ type: 'error', id: msg.id, message: lastLine(e), traceback: text.length > 6000 ? text.slice(-6000) : text });
    }
  }
  return null;
}

/* A notebook cell. The packages its imports name come from the same Pyodide
   release as the rest (matplotlib the first time, say); one that is not
   there fails in the cell, with Python's own message. */
async function notebookCell(msg) {
  if (!runCell) { post({ type: 'error', id: msg.id, message: 'the notebook is not in this engine (reload the page)' }); return; }
  try {
    for (const f of msg.files || []) py.FS.writeFile(`/home/pyodide/${f.name}`, f.text);
    let loading = false;
    try {
      await py.loadPackagesFromImports(msg.code, {
        messageCallback: (text) => { loading = true; post({ type: 'loading', text }); },
        errorCallback: (text) => post({ type: 'log', stream: 'stderr', text }),
      });
    } catch (e) {
      post({ type: 'log', stream: 'stderr', text: `packages for a cell: ${lastLine(e)}` });
    } finally {
      if (loading) post({ type: 'loaded', versions: {} });
    }
    const json = await runCell(msg.nb, msg.code, JSON.stringify(msg.info || {}));
    post({ type: 'result', id: msg.id, json });
  } catch (e) {
    const text = String((e && e.message) || e);
    post({ type: 'error', id: msg.id, message: lastLine(e), traceback: text.length > 6000 ? text.slice(-6000) : text });
  }
}

self.onmessage = (ev) => {
  queue = queue.then(() => handle(ev.data)).catch((e) => post({ type: 'log', stream: 'stderr', text: String(e) }));
};
