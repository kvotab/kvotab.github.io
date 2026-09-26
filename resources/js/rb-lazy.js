/* ==========================================================================
   LAZY FILES AND COMPRESSION PLUGINS
   --------------------------------------------------------------------------
   Two things learnt from the HDF Group's myHDF5 (H5Web), which opens files
   this page could not.

   Large files. A file picked from disk, 256 MB or larger, is not read into
   memory: rb-lazy-worker.js opens it through WORKERFS and reads what is asked
   for. The rest of the page reads HDF5 synchronously -- file.get(path),
   group.keys(), node.attrs, dataset.value -- and it goes on doing so: what it
   is handed is an object that answers those from what has been fetched.
     * the file's paths, all of them, when it is opened: enough for keys(), the
       search, and intersect and union;
     * a group's children, with their types, shapes and attributes, when the
       group is opened in the tree or selected (RbLazyState.ensureGroup);
     * a dataset's values when a selection is about to read them
       (rbPrepareSelection, called by the selection handler before it draws).
   Something read before it was fetched is a warning on the console, never a
   silent gap, so a path this misses shows up in the tests.

   Compression. HDF5 decodes lzf, blosc, zstd, lz4, bitshuffle and the rest
   with plugins, which h5wasm does not have built in. Without one, a read of
   such a dataset does not fail: it returns a buffer of whatever was in
   memory, and the chart draws that. The plugins are fetched when a selection
   needs one (h5wasm-plugins, the set myHDF5 loads), for a file in memory here
   and for a lazy file in the worker.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why

/** A file this size or larger, picked from disk, is read lazily. */
const RB_LAZY_MIN_BYTES = 256 * 1024 * 1024;

/** How much of a lazy file's values are kept, least recently used dropped first. */
const RB_LAZY_VALUE_BUDGET = 1024 * 1024 * 1024;

/*
  Compression filters h5wasm has no decoder for, and the plugin that has one.
  deflate, shuffle, fletcher32, szip, nbit and scale-offset are built in. The
  worker keeps the same table.
*/
const RB_PLUGIN_BY_FILTER = Object.freeze({
  307: 'bz2', 32000: 'lzf', 32001: 'blosc', 32004: 'lz4', 32008: 'bshuf', 32013: 'zfp',
  32015: 'zstd', 32019: 'jpeg', 32022: 'bitgroom', 32023: 'bitround', 32026: 'blosc2'
});
const RB_PLUGIN_BASE = 'https://cdn.jsdelivr.net/npm/h5wasm-plugins@0.3.0/plugins/';

/*
  A plugin is compiled code that runs in this page, so it is taken only if it
  is byte for byte the one this list names: the browser checks each fetch
  against its hash (`integrity`) and refuses anything else, the same way the
  <script> tag for h5wasm is pinned. Hashed from h5wasm-plugins 0.3.0 as npm
  has it, which is what jsDelivr serves. The worker keeps the same list.
*/
const RB_PLUGIN_INTEGRITY = Object.freeze({
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
});

/**
 * Whether a file picked from disk is read lazily. `localStorage['kvot-rb-lazy']`
 * overrides the size rule: 'always' (which the tests use) or 'never'.
 *
 * @param {File} file
 * @returns {boolean}
 */
function wantsLazyFile(file) {
  let pref = null;
  try { pref = localStorage.getItem('kvot-rb-lazy'); } catch (_) { /* no storage: the size rule */ }
  if (pref === 'always') return true;
  if (pref === 'never') return false;
  return !!file && typeof file.size === 'number' && file.size >= RB_LAZY_MIN_BYTES;
}

/* ── the worker ─────────────────────────────────────────────────────────── */

let _rbLazyWorker = null;
let _rbLazySeq = 0;
const _rbLazyPending = new Map();

function rbLazyWorker() {
  if (_rbLazyWorker) return _rbLazyWorker;
  _rbLazyWorker = new Worker('./resources/js/rb-lazy-worker.js?v=20260926');
  _rbLazyWorker.onmessage = (event) => {
    const { id, ok, err } = event.data || {};
    const pending = _rbLazyPending.get(id);
    if (!pending) return;
    _rbLazyPending.delete(id);
    if (err) pending.reject(new Error(err));
    else pending.resolve(ok);
  };
  _rbLazyWorker.onerror = (event) => {
    const error = new Error(event && event.message ? event.message : 'the file reader stopped');
    for (const pending of _rbLazyPending.values()) pending.reject(error);
    _rbLazyPending.clear();
  };
  return _rbLazyWorker;
}

function rbLazyCall(cmd, args) {
  return new Promise((resolve, reject) => {
    const id = ++_rbLazySeq;
    _rbLazyPending.set(id, { resolve, reject });
    rbLazyWorker().postMessage({ id, cmd, ...args });
  });
}

/* ── paths ──────────────────────────────────────────────────────────────── */

function rbLazyJoin(parent, name) {
  if (name.startsWith('/')) return rbLazyNormal(name);
  return rbLazyNormal(parent === '/' ? `/${name}` : `${parent}/${name}`);
}

function rbLazyNormal(path) {
  const parts = String(path).split('/').filter(p => p && p !== '.');
  return '/' + parts.join('/');
}

function rbLazyDirname(path) {
  const at = path.lastIndexOf('/');
  return at <= 0 ? '/' : path.slice(0, at);
}

function rbLazyBasename(path) {
  return path.slice(path.lastIndexOf('/') + 1);
}

/** Attribute values in the shape the page reads them: `attrs[name].value`. */
function rbLazyAttrs(values) {
  const out = {};
  for (const [name, value] of Object.entries(values || {})) out[name] = { value };
  return out;
}

function rbLazySize(value) {
  if (ArrayBuffer.isView(value)) return value.byteLength;
  if (Array.isArray(value)) return value.length * 16;
  return 64;
}

/* ── what the page is handed ────────────────────────────────────────────── */

/** A group of a lazy file, answering as an h5wasm Group does. */
class RbLazyGroup {
  constructor(state, path, attrs) {
    this.__lazy = state;
    this.path = path;
    this.type = 'Group';
    this.attrs = rbLazyAttrs(attrs);
  }

  keys() {
    return this.__lazy.childNames(this.path);
  }

  get(name) {
    return this.__lazy.entity(rbLazyJoin(this.path, String(name)));
  }

  /** The file's own close, on its root; nothing on any other group. */
  close() {
    if (this.path === '/') this.__lazy.close();
  }
}

/** A dataset of a lazy file: its shape and type now, its values once fetched. */
class RbLazyDataset {
  constructor(state, path, entity) {
    this.__lazy = state;
    this.path = path;
    this.type = 'Dataset';
    this.shape = entity.shape;
    this.dtype = entity.dtype;
    this.attrs = rbLazyAttrs(entity.attrs);
  }

  get value() {
    return this.__lazy.value(this.path);
  }
}

/**
 * One lazy file: what has been fetched of it, and the fetching.
 */
class RbLazyState {
  constructor(name, opened) {
    this.name = name;
    this.fid = opened.fid;
    this.paths = opened.paths;
    this.pathSet = new Set(opened.paths);
    this.childIndex = null;
    this.groups = new Map();      // path -> { attrs, order: [names], children: Map(name -> entity) }
    this.notGroups = new Set();
    this.loading = new Map();     // path -> Promise
    this.values = new Map();      // path -> value, least recently used first
    this.valueBytes = 0;
    this.warned = new Set();
    this.closed = false;
    this.addGroup(opened.root);
    this.root = new RbLazyGroup(this, '/', opened.root.attrs);
  }

  addGroup(snapshot) {
    const children = new Map();
    const order = [];
    for (const e of snapshot.children || []) {
      children.set(e.name, e);
      order.push(e.name);
    }
    this.groups.set(snapshot.path, { attrs: snapshot.attrs || {}, order, children });
  }

  /** Something the page read before it was fetched: said once, never silent. */
  miss(what) {
    if (this.warned.has(what)) return;
    this.warned.add(what);
    kvotWarn(`${this.name}: ${what} was read before it was loaded`);
  }

  childNames(path) {
    const g = this.groups.get(path);
    if (g) return g.order.slice();
    if (!this.childIndex) {
      this.childIndex = new Map();
      for (const p of this.paths) {
        const parent = rbLazyDirname(p);
        if (!this.childIndex.has(parent)) this.childIndex.set(parent, []);
        this.childIndex.get(parent).push(rbLazyBasename(p));
      }
    }
    return (this.childIndex.get(path) || []).slice();
  }

  /** The entities of a loaded group, in the file's order. */
  childEntities(path) {
    const g = this.groups.get(path);
    return g ? g.order.map(name => g.children.get(name)) : [];
  }

  entity(path) {
    if (path === '/') return this.root;
    const g = this.groups.get(rbLazyDirname(path));
    if (!g) {
      if (this.pathSet.has(path)) this.miss(`${path} (its group)`);
      return null;
    }
    const e = g.children.get(rbLazyBasename(path));
    if (!e || !e.type) return null;
    if (e.type === 'Group') return new RbLazyGroup(this, path, e.attrs);
    if (e.type === 'Dataset') return new RbLazyDataset(this, path, e);
    if (e.type === 'BrokenSoftLink') return { type: 'BrokenSoftLink', target: e.target };
    if (e.type === 'ExternalLink') return { type: 'ExternalLink', filename: e.filename, obj_path: e.obj_path };
    return { type: e.type, path, attrs: rbLazyAttrs(e.attrs) };
  }

  isDataset(path) {
    const g = this.groups.get(rbLazyDirname(path));
    const e = g && g.children.get(rbLazyBasename(path));
    return !!e && e.type === 'Dataset';
  }

  value(path) {
    if (!this.values.has(path)) {
      this.miss(`the values of ${path}`);
      return undefined;
    }
    const v = this.values.get(path);
    this.values.delete(path);
    this.values.set(path, v);
    return v;
  }

  /** A group and every group above it, fetched unless they are here already. */
  async ensureGroup(path) {
    const parts = rbLazyNormal(path).split('/').filter(Boolean);
    for (let i = 0; i <= parts.length; i++) {
      await this.loadGroup(i === 0 ? '/' : '/' + parts.slice(0, i).join('/'));
    }
  }

  loadGroup(path) {
    if (this.groups.has(path) || this.notGroups.has(path) || this.closed) return Promise.resolve();
    if (!this.loading.has(path)) {
      this.loading.set(path, rbLazyCall('group', { fid: this.fid, path }).then((snapshot) => {
        this.loading.delete(path);
        if (snapshot.missing) this.notGroups.add(path);
        else this.addGroup(snapshot);
      }, (e) => {
        this.loading.delete(path);
        throw e;
      }));
    }
    return this.loading.get(path);
  }

  /** Datasets' values, fetched unless they are here already. */
  async ensureValues(paths) {
    const wanted = [...new Set(paths)].filter(p => !this.values.has(p));
    if (!wanted.length || this.closed) return;
    const { values, errors } = await rbLazyCall('values', { fid: this.fid, paths: wanted });
    for (const [path, value] of Object.entries(values)) this.remember(path, value);
    for (const [path, message] of Object.entries(errors)) {
      kvotWarn(`${this.name}: could not read ${path}: ${message}`);
    }
  }

  remember(path, value) {
    this.values.set(path, value);
    this.valueBytes += rbLazySize(value);
    while (this.valueBytes > RB_LAZY_VALUE_BUDGET && this.values.size > 1) {
      const [oldest, old] = this.values.entries().next().value;
      this.values.delete(oldest);
      this.valueBytes -= rbLazySize(old);
    }
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    this.values.clear();
    rbLazyCall('close', { fid: this.fid }).catch(e => ignoreFailure('RbLazyState.close', e));
  }
}

/**
 * Open a file from disk lazily and register it as the page registers a file.
 * Only its first megabyte is read here, for the HDF5 signature.
 *
 * @param {File} file
 * @param {string} [context] - Label for failure reporting
 * @returns {Promise<string>} The name the file was registered under
 */
async function ingestHdf5Lazy(file, context = 'ingestHdf5Lazy') {
  const head = await file.slice(0, 1024 * 1024 + 8).arrayBuffer();
  const check = validateHdf5Buffer(head);
  if (!check.ok) throw new Error(`${file.name}: ${check.reason}`);

  const state = new RbLazyState(file.name, await rbLazyCall('open', { file }));
  // What nearly every chart reads, fetched with the file rather than per click.
  const always = ['/time'].filter(p => state.isDataset(p));
  await state.ensureValues(always);

  if (loadedFiles[file.name]) {
    try { loadedFiles[file.name].close(); } catch (_) { ignoreFailure(context, _); }
  }
  delete loadedFileBuffers[file.name];
  loadedFiles[file.name] = state.root;
  fileStates[file.name] = true;
  if (!fileOrder.includes(file.name)) fileOrder.push(file.name);
  return file.name;
}

/** Whether a node, or the file it is from, is a lazy one; its state if so. */
function lazyStateOf(node) {
  return node && node.__lazy instanceof RbLazyState ? node.__lazy : null;
}

/* ── before a selection is drawn ────────────────────────────────────────── */

/** Which files and paths a selection's info panel and chart will read. */
function rbSelectionTargets(payload) {
  const out = [];
  const add = (files, path, isGroup) => { for (const fileKey of files) out.push({ fileKey, path, isGroup }); };
  if (!payload) return out;
  if (payload.mode === 'single') add(getEffectiveFiles(), payload.path, false);
  else if (payload.mode === 'group') add(getEffectiveFiles(), payload.path, true);
  else if (payload.mode === 'multi' || payload.mode === 'groups') {
    for (const it of payload.items || []) add(it.fileKey ? [it.fileKey] : getEnabledFiles(), it.path, payload.mode === 'groups');
  }
  return out;
}

/** The datasets a group's own chart reads: its members. */
function rbChartDatasets(group, path) {
  const out = [];
  let keys = [];
  try { keys = Array.from(group.keys()); } catch (_) { return out; }
  for (const k of keys) {
    const p = rbLazyJoin(path, k);
    let obj = null;
    try { obj = group.get(k); } catch (_) { continue; }
    if (obj && obj.type === 'Dataset') out.push(p);
  }
  return out;
}

/** A lazy file's part of a selection: its groups, then the values it reads. */
async function rbPrepareLazy(state, path, isGroup) {
  const groupPath = isGroup ? path : rbLazyDirname(path);
  await state.ensureGroup(groupPath);
  const reads = [];
  if (isGroup) {
    const group = state.entity(path);
    if (group && group.type === 'Group' && checkGroupForRadionuclides(state.root, path)) {
      reads.push(...rbChartDatasets(group, path));
    }
  } else if (state.isDataset(path)) {
    reads.push(path);
  }
  // The background choices of a chart: the "_" datasets of the group, of its
  // IndexLists, and of the file's (collectBackgroundSourceOptions).
  for (const g of [groupPath, rbLazyJoin(groupPath, 'IndexLists'), '/IndexLists']) {
    if (g !== '/' && !state.pathSet.has(g)) continue;
    await state.ensureGroup(g);
    for (const e of state.childEntities(g)) {
      if (e && e.type === 'Dataset' && e.name.startsWith('_')) reads.push(rbLazyJoin(g, e.name));
    }
  }
  if (state.isDataset('/time')) reads.push('/time');
  await state.ensureValues(reads);
}

/**
 * Fetch what a selection will read before it is drawn: for a lazy file its
 * groups and values, for a file in memory the compression plugins its
 * datasets need. Null when there is nothing to fetch, so that the selection is
 * drawn at once, exactly as it was before any of this.
 *
 * @param {Object} payload - A 'selection:changed' payload
 * @returns {Promise|null}
 */
function rbPrepareSelection(payload) {
  const jobs = [];
  for (const { fileKey, path, isGroup } of rbSelectionTargets(payload)) {
    const file = loadedFiles[fileKey];
    if (!file || !path) continue;
    const state = lazyStateOf(file);
    if (state) {
      jobs.push(rbPrepareLazy(state, path, isGroup));
    } else {
      const plugins = rbPluginsFor(file, path, isGroup);
      if (plugins) jobs.push(plugins);
    }
  }
  return jobs.length ? Promise.all(jobs) : null;
}

/* ── compression plugins, for a file in memory ──────────────────────────── */

const _rbPluginLoads = new Map();
const _rbPluginsInstalled = new Set();
let _rbPluginPathReady = null;

/** The folder HDF5 looks for plugins in, made once. */
function rbPluginPath() {
  if (!_rbPluginPathReady) {
    _rbPluginPathReady = (async () => {
      const lib = await waitForH5Wasm();
      const m = await lib.ready;
      const Module = m.Module || m;
      lib.FS.mkdirTree('/plugins');
      Module.insert_plugin_search_path('/plugins', 0);
      return lib;
    })();
  }
  return _rbPluginPathReady;
}

/** A plugin fetched and installed, once however often it is asked for. */
function rbInstallPlugin(name) {
  if (!_rbPluginLoads.has(name)) {
    _rbPluginLoads.set(name, (async () => {
      const lib = await rbPluginPath();
      const integrity = RB_PLUGIN_INTEGRITY[name];
      if (!integrity) throw new Error(`compression plugin ${name} is not on the pinned list`);
      const response = await fetch(`${RB_PLUGIN_BASE}libH5Z${name}.so`, { integrity });
      if (!response.ok) throw new Error(`compression plugin ${name}: HTTP ${response.status}`);
      lib.FS.writeFile(`/plugins/libH5Z${name}.so`, new Uint8Array(await response.arrayBuffer()));
      _rbPluginsInstalled.add(name);
    })().catch((e) => {
      _rbPluginLoads.delete(name);
      reportFailure('rbInstallPlugin', e, { userMessage: `The ${name} decompressor could not be loaded, so data compressed with it cannot be read.` });
    }));
  }
  return _rbPluginLoads.get(name);
}

/**
 * The plugins a selection in a file in memory needs and does not have yet,
 * being installed; null when it needs none, which is nearly always.
 */
function rbPluginsFor(file, path, isGroup) {
  let node = null;
  try { node = FileService.get(file, path); } catch (_) { return null; }
  if (!node) return null;
  const datasets = isGroup && node.type === 'Group' ? rbChartDatasets(node, path).map(p => FileService.get(file, p)) : [node];
  const needed = new Set();
  for (const ds of datasets) {
    if (!ds || ds.type !== 'Dataset') continue;
    let filters = [];
    try { filters = ds.filters || []; } catch (_) { continue; }
    for (const f of filters) {
      const plugin = RB_PLUGIN_BY_FILTER[f.id];
      // Waited for until it is in place, not just asked for: a second
      // selection while it downloads would otherwise read undecoded data.
      if (plugin && !_rbPluginsInstalled.has(plugin)) needed.add(plugin);
    }
  }
  return needed.size ? Promise.all([...needed].map(rbInstallPlugin)) : null;
}
