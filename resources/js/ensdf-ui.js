/* ==========================================================================
   ENSDF.HTML: THE PAGE

   Wiring only. The reading is ensdf-parse.js, the shared logic
   ensdf-core.js, the chart ensdf-chart.js and the chain drawing
   ensdf-chain.js. This file keeps the state, loads and switches databases,
   and fills the panel.

   Databases. The page starts on the newest release listed in
   resources/data/ensdf/releases.js (built by scripts/gen-ensdf.mjs). A
   visitor can open another -- a release zip from the NNDC archive, or ENSDF
   text files -- which is read in a worker, never uploaded, and kept in this
   browser (IndexedDB) so the database menu can switch back to it later.
   NNDC's server sends no CORS header, so the page cannot fetch a release
   from there by itself; the About tab says how to get one.

   Built-in data arrive as scripts calling KVOT_ENSDF_DATA(id, part, data),
   not as JSON: a page opened from the file system may load a script but not
   fetch a file.

   One global besides that callback: ENSDFPage, a read-only window on the
   state for the browser test. Everything else is inside the IIFE and reached
   through the data-on-* actions registered at the bottom.
   ========================================================================== */
/* global KVOT_ENSDF, KVOT_ENSDF_CORE, KVOT_ENSDF_CHART, KVOT_ENSDF_CHAIN, KVOT_ENSDF_OPEN, registerActions, reportFailure, notifyUser, kvotEscapeHtml, kvotCsvCell, kvotFileTooLarge */
(function () {
  'use strict';

  const C = KVOT_ENSDF_CORE;
  const P = KVOT_ENSDF;
  const CH = KVOT_ENSDF_CHAIN;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => kvotEscapeHtml(s);
  const DATA_DIR = './resources/data/ensdf/';
  const WORKER_URL = './resources/js/ensdf-worker.js?v=20260922b';
  const STORAGE_KEY = 'kvot-ensdf-v1';
  const LEVEL_PAGE = 150;
  const LINE_PAGE = 80;

  /* ---------------------------------------------------------------------
     Built-in data, delivered by <script>
     --------------------------------------------------------------------- */
  const waiting = new Map();
  window.KVOT_ENSDF_DATA = (id, part, payload) => {
    const k = `${id}|${part}`;
    const w = waiting.get(k);
    if (w) { waiting.delete(k); w.resolve(payload); }
  };

  function loadScriptData(id, part, url) {
    return new Promise((resolve, reject) => {
      const k = `${id}|${part}`;
      waiting.set(k, { resolve, reject });
      const s = document.createElement('script');
      s.src = url;
      s.async = true;
      s.onload = () => {
        s.remove();
        /* A script that loaded but never called back is not the data file. */
        if (waiting.has(k)) { waiting.delete(k); reject(new Error(`${url} did not contain the expected data`)); }
      };
      s.onerror = () => { s.remove(); waiting.delete(k); reject(new Error(`could not load ${url}`)); };
      document.head.appendChild(s);
    });
  }

  /* ---------------------------------------------------------------------
     Opened databases: worker, or the page itself where there is none
     --------------------------------------------------------------------- */
  let worker = null;
  let workerFailed = false;
  let msgId = 0;
  const replies = new Map();

  function getWorker() {
    if (worker || workerFailed) return worker;
    try {
      worker = new Worker(WORKER_URL);
      worker.onmessage = (ev) => {
        const m = ev.data || {};
        const r = replies.get(m.id);
        if (!r) return;
        if (m.type === 'progress') { if (r.progress) r.progress(m); return; }
        replies.delete(m.id);
        if (m.type === 'error') r.reject(new Error(m.message));
        else r.resolve(m);
      };
      worker.onerror = (ev) => {
        /* A worker that cannot start (file://) fails here; fall back. */
        ev.preventDefault();
        workerFailed = true;
        worker = null;
        for (const [id, r] of replies) { replies.delete(id); r.reject(Object.assign(new Error('worker unavailable'), { retry: true })); }
      };
    } catch (e) {
      workerFailed = true;
      worker = null;
    }
    return worker;
  }

  function ask(msg, progress) {
    const w = getWorker();
    if (!w) return Promise.reject(Object.assign(new Error('worker unavailable'), { retry: true }));
    const id = ++msgId;
    return new Promise((resolve, reject) => {
      replies.set(id, { resolve, reject, progress });
      w.postMessage({ ...msg, id });
    });
  }

  /** Read files into a database, in the worker when there is one. */
  async function openFiles(files, progress) {
    try {
      const m = await ask({ type: 'open', files }, progress);
      return {
        summary: m.summary,
        detail: (a) => ask({ type: 'detail', a }).then((r) => r.detail),
      };
    } catch (e) {
      if (!e.retry) throw e;
      await ensureInlineReader();
      const res = await KVOT_ENSDF_OPEN.readFiles(files, progress);
      return { summary: res.summary, detail: (a) => Promise.resolve(res.details.get(a) || null) };
    }
  }

  function ensureInlineReader() {
    if (window.KVOT_ENSDF_OPEN) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = './resources/js/ensdf-open.js?v=20260922b';
      s.onload = resolve;
      s.onerror = () => reject(new Error('could not load ensdf-open.js'));
      document.head.appendChild(s);
    });
  }

  /* ---------------------------------------------------------------------
     Remembered databases (IndexedDB)
     --------------------------------------------------------------------- */
  const IDB = {
    db: null,
    open() {
      if (this.db) return Promise.resolve(this.db);
      return new Promise((resolve, reject) => {
        let req;
        try { req = indexedDB.open('kvot-ensdf', 1); } catch (e) { reject(e); return; }
        req.onupgradeneeded = () => req.result.createObjectStore('files', { keyPath: 'key' });
        req.onsuccess = () => { this.db = req.result; resolve(this.db); };
        req.onerror = () => reject(req.error || new Error('IndexedDB unavailable'));
      });
    },
    async tx(mode, fn) {
      const db = await this.open();
      return new Promise((resolve, reject) => {
        const t = db.transaction('files', mode);
        const store = t.objectStore('files');
        const out = fn(store);
        t.oncomplete = () => resolve(out && out.result !== undefined ? out.result : out);
        t.onerror = () => reject(t.error);
        t.onabort = () => reject(t.error || new Error('aborted'));
      });
    },
    list() { return this.tx('readonly', (s) => s.getAll()); },
    put(rec) { return this.tx('readwrite', (s) => s.put(rec)); },
    remove(key) { return this.tx('readwrite', (s) => s.delete(key)); },
  };

  /* ---------------------------------------------------------------------
     State
     --------------------------------------------------------------------- */
  const state = {
    releases: [],          // built-in, newest first
    stored: [],            // remembered opened databases: {key, label, names, size, opened}
    source: null,          // {key, label, kind, summary, detail(a)}
    idx: null,
    details: new Map(),    // a -> detail, for the current source
    sel: null,             // {z, a, k}
    root: null,            // start of the chain on show
    chain: null,
    view: 'chart',
    tab: 'nuclide',
    colour: 'halflife',
    chainOpt: { minBranch: 0, life: 'iso', overlay: true },
    levelsAll: false,
    radSort: 'energy',
    radAll: false,
    panelWidth: null,
    dbKey: '',
    loading: false,
  };

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        colour: state.colour, chainOpt: state.chainOpt, tab: state.tab, view: state.view, panelWidth: state.panelWidth,
        dbKey: state.dbKey, sel: state.sel, radSort: state.radSort,
      }));
    } catch (e) { /* storage unavailable */ }
  }

  function loadState() {
    try {
      const s = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
      if (!s) return null;
      if (C.COLOUR_MODES[s.colour]) state.colour = s.colour;
      if (s.chainOpt && typeof s.chainOpt === 'object') {
        if (Number.isFinite(s.chainOpt.minBranch)) state.chainOpt.minBranch = s.chainOpt.minBranch;
        if (typeof s.chainOpt.life === 'string') state.chainOpt.life = s.chainOpt.life;
        if (typeof s.chainOpt.overlay === 'boolean') state.chainOpt.overlay = s.chainOpt.overlay;
      }
      if (['nuclide', 'levels', 'radiation', 'datasets', 'about'].includes(s.tab)) state.tab = s.tab;
      if (['chart', 'chain'].includes(s.view)) state.view = s.view;
      if (Number.isFinite(s.panelWidth)) state.panelWidth = s.panelWidth;
      if (typeof s.dbKey === 'string') state.dbKey = s.dbKey;
      if (s.radSort === 'intensity') state.radSort = 'intensity';
      return s;
    } catch (e) { return null; }
  }

  /* ---------------------------------------------------------------------
     Status line
     --------------------------------------------------------------------- */
  function status(text, tone) {
    const el = $('nzStatus');
    el.textContent = text;
    el.title = text;
    el.className = 'nz-status' + (tone ? ' ' + tone : '');
  }

  function sourceStatus() {
    if (!state.source) return;
    const r = state.source.summary.release;
    status(`${state.source.label} · ${r.nuclides.toLocaleString('en')} nuclides · ${r.datasets.toLocaleString('en')} data sets`);
  }

  /* ---------------------------------------------------------------------
     Databases
     --------------------------------------------------------------------- */
  function builtinSource(rel) {
    return loadScriptData(rel.id, 'summary', `${DATA_DIR}${rel.id}/summary.js`).then((summary) => ({
      key: `b:${rel.id}`, label: rel.label, kind: 'builtin', summary,
      detail: (a) => loadScriptData(rel.id, `a${a}`, `${DATA_DIR}${rel.id}/a/${String(a).padStart(3, '0')}.js`).catch(() => null),
    }));
  }

  async function useSource(src) {
    state.source = src;
    state.idx = C.index(src.summary);
    state.details = new Map();
    state.dbKey = src.key;
    chart.setIndex(state.idx);
    renderDbMenu();
    sourceStatus();
    renderLegend();
    /* Keep the nuclide the reader was on, if the new database has it. */
    if (state.sel && state.idx.get(state.sel.z, state.sel.a)) {
      const n = state.idx.get(state.sel.z, state.sel.a);
      select({ z: state.sel.z, a: state.sel.a, k: Math.min(state.sel.k, n.s.length - 1) }, { from: 'db', keepView: true });
    } else if (state.sel) {
      state.sel = null;
      state.root = null;
      state.chain = null;
      chart.select(null);
      chart.setChain(null);
      renderPanel();
      renderChainView();
    } else {
      renderPanel();
    }
    saveState();
  }

  async function switchDb(key) {
    if (!key || (state.source && state.source.key === key)) return;
    state.loading = true;
    try {
      if (key.startsWith('b:')) {
        const rel = state.releases.find((r) => `b:${r.id}` === key);
        if (!rel) throw new Error('that release is not on this site');
        status(`Loading ${rel.label}…`);
        await useSource(await builtinSource(rel));
      } else if (key.startsWith('s:')) {
        const rec = (await IDB.list()).find((r) => r.key === key.slice(2));
        if (!rec) throw new Error('that database is no longer stored in this browser');
        await readAndUse(rec.files, rec);
      }
    } catch (e) {
      reportFailure('ensdf:switchDb', e, { userMessage: 'The database could not be opened.' });
      renderDbMenu();
      sourceStatus();
    } finally {
      state.loading = false;
    }
  }

  async function readAndUse(files, rec) {
    const names = files.map((f) => f.name || 'file').join(', ');
    status(`Reading ${names}…`);
    const t0 = performance.now();
    const res = await openFiles(files, (p) => status(`Reading ${names}: ${p.done} of ${p.total} files`));
    const r = res.summary.release;
    const key = rec ? rec.key : `${r.label}|${files.map((f) => `${f.name}:${f.size}`).join('|')}`;
    const src = { key: `s:${key}`, label: rec ? rec.label : r.label, kind: 'opened', summary: res.summary, detail: res.detail };
    if (!rec) {
      /* Remember it for next time, if the browser lets us. */
      const size = files.reduce((t, f) => t + (f.size || 0), 0);
      try {
        await IDB.put({ key, label: r.label, names: files.map((f) => f.name), size, opened: Date.now(), files });
        state.stored = await IDB.list();
      } catch (e) {
        src.key = `o:${key}`;
        state.stored = state.stored.filter((x) => x.key !== key);
        state.transient = { key: src.key, label: r.label };
      }
    }
    await useSource(src);
    notifyUser(`${src.label}: ${r.nuclides.toLocaleString('en')} nuclides read in ${((performance.now() - t0) / 1000).toFixed(1)} s.`, { tone: 'success' });
  }

  function renderDbMenu() {
    const sel = $('nzDb');
    const opts = [];
    for (const r of state.releases) opts.push(`<option value="b:${esc(r.id)}">${esc(r.label)} (on this site)</option>`);
    for (const s of state.stored.slice().sort((p, q) => q.opened - p.opened)) {
      opts.push(`<option value="s:${esc(s.key)}">${esc(s.label)} (opened ${esc(new Date(s.opened).toISOString().slice(0, 10))})</option>`);
    }
    if (state.transient) opts.push(`<option value="${esc(state.transient.key)}">${esc(state.transient.label)} (opened)</option>`);
    sel.innerHTML = opts.join('');
    if (state.source) sel.value = state.source.key;
    $('nzForget').hidden = !(state.source && state.source.key.startsWith('s:'));
  }

  /* ---------------------------------------------------------------------
     Selection
     --------------------------------------------------------------------- */
  function hashFor(sel) {
    const n = state.idx && state.idx.get(sel.z, sel.a);
    return n ? C.name(sel.z, sel.a, sel.k, n).key : '';
  }

  /**
   * @param {{z, a, k}} sel
   * @param {{from?: string, keepView?: boolean, centre?: boolean}} [how]
   *   from 'chain' keeps the chain where it starts; everything else moves
   *   the start of the chain to the new selection.
   */
  function select(sel, how = {}) {
    if (!state.idx) return;
    const n = state.idx.get(sel.z, sel.a);
    if (!n) return;
    const k = Math.max(0, Math.min(sel.k || 0, Math.max(0, n.s.length - 1)));
    state.sel = { z: sel.z, a: sel.a, k };
    if (how.from !== 'chain') state.root = { ...state.sel };
    state.levelsAll = false;
    state.radAll = false;
    if (['search', 'hash', 'start'].includes(how.from)) chart.centreOn(sel.z, sel.a, 30);
    chart.select(state.sel, how.centre !== false && how.from !== 'chart');
    computeChain();
    renderPanel();
    renderChainView();
    const h = '#' + hashFor(state.sel);
    if (location.hash !== h) {
      try { history.replaceState(null, '', h); } catch (e) { /* file:// in some browsers */ }
    }
    saveState();
  }

  function computeChain() {
    if (!state.root || !state.idx) { state.chain = null; chart.setChain(null); return; }
    const r = state.root;
    const life = lifeOption();
    state.chain = C.buildChain(state.idx, r.z, r.a, r.k, { minBranch: state.chainOpt.minBranch, minHalfLifeS: life.life, minIsomerS: life.iso });
    if (!state.chainOpt.overlay) { chart.setChain(null); return; }
    const cells = new Set();
    const arrows = [];
    for (const nd of state.chain.nodes) if (nd.kind !== 'fission') cells.add(nd.z * 1000 + nd.a);
    const drawn = new Set();
    for (const e of state.chain.edges) {
      if (e.to.kind === 'fission' || (e.from.z === e.to.z && e.from.a === e.to.a)) continue;
      /* A direct arrow and one through a left-out isomer join the same two cells. */
      const pair = `${e.from.z},${e.from.a}>${e.to.z},${e.to.a}`;
      if (drawn.has(pair)) continue;
      drawn.add(pair);
      arrows.push({ z0: e.from.z, n0: e.from.a - e.from.z, z1: e.to.z, n1: e.to.a - e.to.z, faint: e.pct === null || e.inferred });
    }
    chart.setChain({ cells, arrows, dim: false });
  }

  function pickFromQuery(q) {
    const p = C.parseQuery(q);
    if (!p || !state.idx) return null;
    if (p.a === undefined) {
      /* An element alone: a stable isotope if it has one -- the best studied,
         by number of data sets, standing in for the most abundant, which ENSDF
         does not record -- otherwise its longest-lived isotope. */
      const iso = state.idx.list.filter((n) => n.z === p.z && n.s.length && !n.hidden);
      if (!iso.length) return null;
      const rank = (n) => (n.s[0].st ? [1, n.nd || 0] : [0, n.s[0].ts || 0]);
      iso.sort((x, y) => { const rx = rank(x), ry = rank(y); return (ry[0] - rx[0]) || (ry[1] - rx[1]); });
      return { z: p.z, a: iso[0].a, k: 0 };
    }
    const n = state.idx.get(p.z, p.a);
    if (!n) return null;
    const k = C.stateForLabel(n, p.iso);
    return { z: p.z, a: p.a, k: k < 0 ? 0 : k };
  }

  /* ---------------------------------------------------------------------
     Small renderers
     --------------------------------------------------------------------- */
  function nameHtml(z, a, k, nuc) {
    const n = C.name(z, a, k, nuc);
    return n.mass ? `<sup>${esc(n.mass)}</sup>${esc(n.sym)}` : esc(n.sym);
  }

  function nucLink(z, a, k) {
    const nuc = state.idx.get(z, a);
    if (!nuc) return `<span class="nz-missing" title="Not in this database">${nameHtml(z, a, 0, null)}</span>`;
    return `<a href="#${esc(C.name(z, a, k, nuc).key)}" class="nz-nuc" data-on-click="nz:go" data-z="${z}" data-a="${a}" data-k="${k}">${nameHtml(z, a, k, nuc)}</a>`;
  }

  /*
    Superscript characters (β⁻, ×10⁻⁵, ¹⁴C) come from ensdf-core as Unicode
    so they work on a canvas and in a title. In markup they are set as <sup>:
    Verdana has no glyphs for them and the fallback ones are tiny.
  */
  const supHtml = (text) => C.supRuns(text).map((r) => (r.sup ? `<sup>${esc(r.t)}</sup>` : esc(r.t))).join('');
  /* The same as nodes, for the hover cards, which are built without markup. */
  function supNode(text) {
    const frag = document.createDocumentFragment();
    for (const r of C.supRuns(text)) {
      if (r.sup) { const e = document.createElement('sup'); e.textContent = r.t; frag.appendChild(e); }
      else frag.appendChild(document.createTextNode(r.t));
    }
    return frag;
  }

  /** A value with its uncertainty the NDS way: 2822.81 <small>21</small>. */
  function valUnc(value, unc, unit) {
    if (!value) return '<span class="nz-dim">—</span>';
    const p = C.valueParts(value, unc);
    const title = C.uncertaintyText(value, unc);
    let u = '';
    if (p.unc) u = `<span class="nz-unc">${esc(p.unc)}</span>`;
    else if (p.plus) u = `<span class="nz-unc nz-asym"><sup>+${esc(p.plus)}</sup><sub>−${esc(p.minus)}</sub></span>`;
    const q = p.q ? `${esc(p.q)} ` : '';
    const note = p.note ? ` <span class="nz-dim">(${esc(p.note)})</span>` : '';
    /* The unit goes before the uncertainty, as the Nuclear Data Sheets set it: 1925.28 d 14. */
    return `<span class="nz-val"${title ? ` title="${esc(title)}${unit ? ' ' + esc(unit) : ''}"` : ''}>${q}${supHtml(p.value)}${unit ? ' ' + esc(unit) : ''}${u ? ' ' + u : ''}</span>${note}`;
  }

  function halfLifeHtml(st) {
    if (!st) return '<span class="nz-dim">—</span>';
    if (st.st) return '<b>stable</b>';
    const p = C.halfLifeParts(st);
    if (p.unknown) return p.value ? esc(p.value) : '<span class="nz-dim">not known</span>';
    const num = String(st.t).trim().split(/\s+/)[0].replace(/^[<>~]/, '');
    let html = valUnc(num, st.dt, p.unit);
    if (p.q && !/^(<|>|≈)/.test(C.valueParts(num, st.dt).q)) html = `${esc(p.q)} ${html}`;
    if (p.doubtful) html += ' <span class="nz-dim" title="The evaluator marks the assignment as uncertain">?</span>';
    const alt = C.halfLifeAlt(st);
    if (alt && !(p.unit === 'y' && /\by$/.test(alt) && !st.w)) html += ` <span class="nz-alt">= ${esc(alt)}</span>`;
    if (st.w) html += ' <span class="nz-dim">(given as a level width)</span>';
    return html;
  }

  function modeStatedHtml(dm) {
    const m = C.modeStated(dm);
    const meaning = C.modeMeaning(dm[0]);
    const val = m.value === '?' ? '<span class="nz-dim">percentage not known</span>'
      : `${m.rel ? esc(m.rel) + ' ' : ''}${supHtml(m.value)} %${m.unc ? ` <span class="nz-unc">${esc(m.unc)}</span>` : ''}`;
    return `<span class="nz-mode"${meaning ? ` title="${esc(meaning)}"` : ''}>${supHtml(m.mode)}</span> ${val}`;
  }

  function fmtDate(yyyymm) {
    if (!/^\d{6}$/.test(yyyymm || '')) return yyyymm || '';
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const m = +yyyymm.slice(4, 6);
    return m >= 1 && m <= 12 ? `${months[m - 1]} ${yyyymm.slice(0, 4)}` : yyyymm.slice(0, 4);
  }

  function fmtPub(pub) {
    const m = /^(\d{2})(NDS|NP)\b(.*)$/i.exec(pub || '');
    if (!m) return pub || '';
    const year = (+m[1] > 50 ? '19' : '20') + m[1];
    return `${m[2].toUpperCase() === 'NDS' ? 'Nuclear Data Sheets' : 'Nuclear Physics A'} (${year})${m[3] ? ' ' + m[3].replace(/^,/, '').trim() : ''}`;
  }

  /* ---------------------------------------------------------------------
     The panel
     --------------------------------------------------------------------- */
  function renderPanel() {
    document.querySelectorAll('.nz-tabs button').forEach((b) => {
      const on = b.dataset.tab === state.tab;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    document.querySelectorAll('.nz-pane').forEach((p) => { p.hidden = p.dataset.pane !== state.tab; });
    if (state.tab === 'nuclide') renderNuclide();
    else if (state.tab === 'levels') renderLevels();
    else if (state.tab === 'radiation') renderRadiation();
    else if (state.tab === 'datasets') renderDatasets();
  }

  function welcomeHtml() {
    const r = state.source ? state.source.summary.release : null;
    return `<div class="nz-welcome">
      <h2>Chart of nuclides</h2>
      <p>Every nuclide in the Evaluated Nuclear Structure Data File, placed by its neutron number <i>N</i> and proton number <i>Z</i> and coloured by half-life. Click one — or type its name above — for its states, decay modes, Q-values and evaluation, its level scheme and radiation, and the whole decay chain that follows from it.</p>
      ${r ? `<p class="nz-dim">${esc(state.source.label)}: ${r.nuclides.toLocaleString('en')} nuclides with adopted data${r.unobserved ? ` (and ${r.unobserved} searched for but not observed, which are not drawn)` : ''}, ${r.states.toLocaleString('en')} ground states and isomers, ${r.datasets.toLocaleString('en')} data sets; newest evaluation ${esc(fmtDate(r.newest))}.</p>` : ''}
      <p class="nz-dim">Drag to pan, scroll or pinch to zoom, arrow keys to step from one nuclide to the next. The notch in a cell’s corner marks a nuclide with isomers.</p>
    </div>`;
  }

  function renderNuclide() {
    const pane = $('nzPaneNuclide');
    if (!state.sel || !state.idx) { pane.innerHTML = welcomeHtml(); return; }
    const { z, a, k } = state.sel;
    const nuc = state.idx.get(z, a);
    const st = nuc.s[k];
    const nm = C.name(z, a, k, nuc);
    const html = [];
    html.push(`<div class="nz-head">
      <div class="nz-title"><span class="nz-big">${nameHtml(z, a, k, nuc)}</span><span class="nz-long">${esc(nm.long)}</span></div>
      <div class="nz-zna">Z ${z} · N ${a - z} · A ${a}</div>
    </div>`);
    const aq = nuc.aq || '';
    if (/OBSERVED/.test(aq)) {
      html.push('<p class="nz-inferred">Searched for and not observed: the adopted data set is marked “' + esc(aq.toLowerCase()) + '”, so the nuclide is not drawn on the chart.</p>');
    } else if (aq) {
      html.push(`<p class="nz-inferred">The adopted data set is marked “${esc(aq.toLowerCase())}”: ${aq === 'TENTATIVE' ? 'the identification of this nuclide is not yet firm' : aq === 'INFERRED' ? 'the nuclide is inferred rather than observed directly' : 'see the data set for what that means'}.</p>`);
    }
    if (!st) {
      html.push(`<p class="nz-dim">${nuc.x ? 'This nuclide appears in ENSDF only in data sets other than an adopted one, so there is no evaluated ground state to show.' : 'The adopted data set has no levels.'}</p>`);
      pane.innerHTML = html.join('');
      return;
    }
    if (nuc.s.length > 1) {
      html.push('<div class="nz-states" role="tablist" aria-label="States">');
      nuc.s.forEach((s, i) => {
        const label = i === 0 ? 'ground state' : `${esc(C.isomerLabel(nuc, i))} · ${esc(s.e)} keV`;
        html.push(`<button type="button" role="tab" class="${i === k ? 'active' : ''}" aria-selected="${i === k}" data-on-click="nz:state" data-k="${i}">${label}<span>${supHtml(s.st ? 'stable' : C.halfLifeShort(s) || '—')}</span></button>`);
      });
      html.push('</div>');
    }
    html.push('<dl class="nz-facts">');
    html.push(`<dt>Half-life</dt><dd>${halfLifeHtml(st)}</dd>`);
    if (k > 0) html.push(`<dt>Level energy</dt><dd>${valUnc(st.e, st.de, 'keV')}</dd>`);
    html.push(`<dt>Spin and parity</dt><dd>${st.j ? esc(st.j) : '<span class="nz-dim">not assigned</span>'}</dd>`);
    const inferred = (st.br || []).filter((b) => b[3]);
    if ((st.dm && st.dm.length) || inferred.length) {
      const items = (st.dm || []).map((dm) => `<li>${modeStatedHtml(dm)}</li>`);
      for (const b of inferred) {
        items.push(`<li><span class="nz-mode">${supHtml(C.modeText(b[0]))}</span> ${supHtml(C.pctText(b[1]))} <span class="nz-inferred" title="ENSDF gives no percentage for this mode. It is taken from the Q-values: this is the only beta or electron-capture branch that is energetically open${b[0] === 'IT' ? '' : ''}.">${b[0] === 'IT' ? 'assumed: an excited state with no decay given decays by gamma emission' : 'inferred from the Q-values; not stated in ENSDF'}</span></li>`);
      }
      html.push(`<dt>Decay</dt><dd><ul class="nz-modes">${items.join('')}</ul></dd>`);
    } else if (!st.st) {
      html.push('<dt>Decay</dt><dd><span class="nz-dim">no decay mode in this database</span></dd>');
    }
    const daughters = [];
    for (const b of st.br || []) {
      if (!b[2].length) { daughters.push(`<li><span class="nz-mode">${supHtml(C.modeText(b[0]))}</span> → fission fragments</li>`); continue; }
      const parts = b[2].map(([dz, da, dk, f]) => {
        const share = b[1] === null ? '' : ` <span class="nz-dim">${supHtml(C.sharePct(b[1] * f, C.isLimit(b[4]) ? b[4] : ''))}</span>`;
        return dk < 0 ? `<span class="nz-missing" title="Not in this database">${nameHtml(dz, da, 0, null)}</span>${share}` : `${nucLink(dz, da, dk)}${share}`;
      });
      daughters.push(`<li><span class="nz-mode">${supHtml(C.modeText(b[0]))}</span> → ${parts.join(', ')}</li>`);
    }
    if (daughters.length) html.push(`<dt>Daughters</dt><dd><ul class="nz-modes">${daughters.join('')}</ul></dd>`);
    if (st.mu) html.push(`<dt>Magnetic moment</dt><dd>${esc(st.mu.replace(/\s*\(.*\)$/, ''))} μ<sub>N</sub></dd>`);
    if (st.qm) html.push(`<dt>Quadrupole moment</dt><dd>${esc(st.qm.replace(/\s*\(.*\)$/, ''))} b</dd>`);
    html.push('</dl>');

    /* The chain in brief, with the way into the full drawing. */
    if (state.chain && !st.st && state.root && state.root.z === z && state.root.a === a && state.root.k === k) {
      const ch = state.chain;
      const ends = ch.nodes.filter((n) => n.kind === 'fission' || n.kind === 'missing' || (n.st && (n.st.st || !(n.st.br || []).length)));
      const endList = ends.sort((p, q) => q.cum - p.cum).slice(0, 6).map((n) => {
        const what = n.kind === 'fission' ? 'fission' : n.kind === 'missing' ? `${nameHtml(n.z, n.a, 0, null)} (not in ENSDF)` : `${nucLink(n.z, n.a, n.k)}${n.st.st ? ' (stable)' : ' (decay unknown)'}`;
        return `<li>${what} <span class="nz-dim">${supHtml(n.cumUnknown && !n.cum ? '?' : C.pctText(n.cum * 100))}${n.cumUnknown && n.cum ? ' or more' : ''}</span></li>`;
      });
      const members = ch.nodes.filter((n) => n !== ch.root && n.kind !== 'fission');
      const what = members.some((n) => n.k > 0) ? ['state', 'nuclides and states'] : ['nuclide', 'nuclides'];
      const count = members.length === 1 ? `1 ${what[0]} follows` : `${members.length} ${what[1]} follow`;
      html.push(`<section class="nz-card">
        <h3>Decay chain</h3>
        <div class="nz-chain-mini" data-on-click="nz:showChain" title="Open the decay chain"><svg id="nzChainMini" role="img" aria-label="The decay chain in small; click to open it"></svg></div>
        <p>${count} from ${nameHtml(z, a, k, nuc)}${ch.truncated ? ' (cut off: the chain is too large to draw whole)' : ''}. Where it ends:</p>
        <ul class="nz-ends">${endList.join('')}</ul>
        <button type="button" class="nz-btn" data-on-click="nz:showChain">Show the decay chain</button>
      </section>`);
    }

    if (nuc.s.length > 1) {
      html.push('<h3>States</h3><div class="nz-table-wrap"><table class="nz-table"><thead><tr><th class="text">State</th><th>E (keV)</th><th class="text">Jπ</th><th class="text">T½</th><th class="text">Decay</th></tr></thead><tbody>');
      nuc.s.forEach((s, i) => {
        const modes = (s.dm || []).map((dm) => { const m = C.modeStated(dm); return `${m.mode} ${m.value === '?' ? '?' : (m.rel ? m.rel + ' ' : '') + m.value + ' %'}`; }).join(', ');
        html.push(`<tr class="${i === k ? 'current' : ''}"><td class="text"><a href="#${esc(C.name(z, a, i, nuc).key)}" data-on-click="nz:state" data-k="${i}">${nameHtml(z, a, i, nuc)}</a></td><td>${esc(s.e)}</td><td class="text">${esc(s.j || '')}</td><td class="text">${supHtml(C.halfLifeText(s, true))}</td><td class="text">${supHtml(modes || (s.st ? '' : i > 0 ? 'IT' : ''))}</td></tr>`);
      });
      html.push('</tbody></table></div>');
      html.push('<p class="nz-note">States are the ground state and every level the evaluators flag as metastable or that lives at least 1 µs.</p>');
    }

    if (nuc.q) {
      const [qb, dqb, sn, dsn, sp, dsp, qa, dqa, qref] = nuc.q;
      const lower = state.idx.get(z - 1, a);
      const qecRow = lower && lower.q && lower.q[0] && Number.isFinite(P.num(lower.q[0]))
        ? `<tr><th>Q(ε)</th><td>${valUnc(String(-P.num(lower.q[0])).replace(/^--/, ''), lower.q[1], 'keV')}</td><td class="nz-dim">minus Q(β⁻) of ${nameHtml(z - 1, a, 0, lower)}</td></tr>` : '';
      html.push(`<h3>Q-values and separation energies</h3>
        <table class="nz-kv"><tbody>
          <tr><th>Q(β⁻)</th><td>${valUnc(qb, dqb, 'keV')}</td><td class="nz-dim">beta-minus decay of the ground state</td></tr>
          ${qecRow}
          <tr><th>Q(α)</th><td>${valUnc(qa, dqa, 'keV')}</td><td class="nz-dim">alpha decay</td></tr>
          <tr><th>S(n)</th><td>${valUnc(sn, dsn, 'keV')}</td><td class="nz-dim">neutron separation energy</td></tr>
          <tr><th>S(p)</th><td>${valUnc(sp, dsp, 'keV')}</td><td class="nz-dim">proton separation energy</td></tr>
        </tbody></table>
        ${qref ? `<p class="nz-note">Source: ${esc(qref)}${/WA\d\d/i.test(qref) ? ' (Atomic Mass Evaluation)' : ''}.</p>` : ''}`);
    }

    if (nuc.ev) {
      const [pub, date, typ, aut, cit, cut] = nuc.ev;
      html.push(`<h3>Evaluation</h3><dl class="nz-facts nz-small">
        ${cit ? `<dt>Published</dt><dd>${esc(cit)}${fmtPub(pub) ? ` <span class="nz-dim">· ${esc(fmtPub(pub))}</span>` : ''}</dd>` : (pub ? `<dt>Published</dt><dd>${esc(fmtPub(pub))}</dd>` : '')}
        ${aut ? `<dt>Evaluators</dt><dd>${esc(aut)}</dd>` : ''}
        ${cut ? `<dt>Literature cut-off</dt><dd>${esc(cut)}</dd>` : ''}
        ${date ? `<dt>In ENSDF since</dt><dd>${esc(fmtDate(date))}${typ ? ` <span class="nz-dim">(${esc({ FUL: 'full evaluation', UPD: 'update', MOD: 'modified', ERR: 'erratum', FMT: 'format change', EXP: 'experimental data' }[typ] || typ)})</span>` : ''}</dd>` : ''}
        <dt>Adopted data</dt><dd>${(nuc.nl || 0).toLocaleString('en')} levels, ${(nuc.ng || 0).toLocaleString('en')} γ rays, from ${(nuc.nd || 0).toLocaleString('en')} data sets</dd>
      </dl>`);
    }
    pane.innerHTML = html.join('');
    drawMiniChain();
  }

  /* The chain in small, in the panel: the whole drawing scaled to the panel's
     width, so the reader sees its shape the moment a nuclide is chosen. */
  function drawMiniChain() {
    const svg = $('nzChainMini');
    if (!svg || !state.chain) return;
    const size = CH.render(svg, state.chain, {});
    const room = svg.parentElement.clientWidth || 400;
    const scale = Math.min(1, room / size.width);
    svg.setAttribute('width', Math.round(size.width * scale));
    svg.setAttribute('height', Math.round(size.height * scale));
  }

  /** The detail file for the selected mass number, from cache or loaded. */
  async function detailFor(a) {
    if (state.details.has(a)) return state.details.get(a);
    const src = state.source;
    const d = await src.detail(a);
    if (state.source === src) state.details.set(a, d);
    return d;
  }

  function withDetail(pane, render) {
    if (!state.sel) { pane.innerHTML = welcomeHtml(); return; }
    const { z, a } = state.sel;
    const cached = state.details.get(a);
    if (cached !== undefined) { render(cached && cached.nuc[z]); return; }
    pane.innerHTML = '<p class="nz-dim">Loading…</p>';
    const want = { ...state.sel };
    detailFor(a).then((d) => {
      if (!state.sel || state.sel.z !== want.z || state.sel.a !== want.a) return;
      render(d && d.nuc[z]);
    }).catch((e) => {
      pane.innerHTML = '<p class="nz-dim">The detailed data could not be loaded.</p>';
      reportFailure('ensdf:detail', e);
    });
  }

  function renderLevels() {
    const pane = $('nzPaneLevels');
    withDetail(pane, (det) => {
      if (!det || !det.lv) { pane.innerHTML = '<p class="nz-dim">No adopted levels for this nuclide.</p>'; return; }
      const { z, a } = state.sel;
      const nuc = state.idx.get(z, a);
      const gam = new Map();
      for (const g of det.gm || []) {
        if (!gam.has(g[0])) gam.set(g[0], []);
        gam.get(g[0]).push(g);
      }
      const rows = det.lv;
      const show = state.levelsAll ? rows.length : Math.min(rows.length, LEVEL_PAGE);
      const html = [`<div class="nz-pane-head"><h3>Adopted levels of ${nameHtml(z, a, 0, nuc)}</h3><span class="nz-dim">${rows.length.toLocaleString('en')} levels, ${(det.gm || []).length.toLocaleString('en')} γ rays</span></div>`];
      html.push('<div class="nz-table-wrap"><table class="nz-table nz-levels"><thead><tr><th>E (keV)</th><th class="text">Jπ</th><th class="text">T½</th></tr></thead><tbody>');
      for (let i = 0; i < show; i++) {
        const [e, de, j, t, dt, ms, q, modes, k] = rows[i];
        const isState = k !== undefined && k !== '' && k >= 0;
        const stateMark = isState ? ` <a class="nz-state-mark" href="#${esc(C.name(z, a, k, nuc).key)}" data-on-click="nz:state" data-k="${k}" title="One of the states on the Nuclide tab">${k === 0 ? 'g.s.' : esc(C.isomerLabel(nuc, k))}</a>` : '';
        const tt = t ? `${supHtml(C.halfLifeText({ t, dt }, true))}` : '';
        const dec = Array.isArray(modes) ? modes.map((m) => modeStatedHtml(m)).join(', ') : '';
        const gs = (gam.get(i) || []).map((g) => {
          const [, ge, gde, ri, dri, mult, , , , , lf] = g;
          const fin = lf !== undefined && lf !== '' && lf >= 0 && rows[lf] ? rows[lf][0] : '?';
          return `<span class="nz-gamma" title="γ ray of ${esc(ge)} keV to the level at ${esc(fin)} keV">γ ${esc(ge)}${gde ? `<span class="nz-unc">${esc(gde)}</span>` : ''}${ri ? ` <span class="nz-dim">(${esc(ri)}${dri ? ' ' + esc(dri) : ''})</span>` : ''}${mult ? ` ${esc(mult)}` : ''} → ${esc(fin)}</span>`;
        });
        html.push(`<tr class="nz-level${isState ? ' nz-isomer-row' : ''}"><td>${esc(e)}${de ? `<span class="nz-unc">${esc(de)}</span>` : ''}${q === '?' ? ' <span class="nz-dim" title="Uncertain level">?</span>' : ''}${stateMark}</td><td class="text">${esc(j || '')}</td><td class="text">${tt}${ms ? ` <span class="nz-dim" title="Metastable flag">${esc(ms)}</span>` : ''}</td></tr>`);
        if (dec || gs.length) html.push(`<tr class="nz-level-out"><td colspan="3" class="text">${dec ? `<div class="nz-level-dec">${dec}</div>` : ''}${gs.join(' ')}</td></tr>`);
      }
      html.push('</tbody></table></div>');
      if (show < rows.length) html.push(`<button type="button" class="nz-btn secondary" data-on-click="nz:levelsAll">Show all ${rows.length.toLocaleString('en')} levels</button>`);
      pane.innerHTML = html.join('');
    });
  }

  function renderRadiation() {
    const pane = $('nzPaneRadiation');
    withDetail(pane, (det) => {
      const { z, a, k } = state.sel;
      const nuc = state.idx.get(z, a);
      const list = ((det && det.rad) || []).filter((r) => r.s === k);
      const title = `<div class="nz-pane-head"><h3>Radiation from the decay of ${nameHtml(z, a, k, nuc)}</h3>
        <span class="nz-sort">Sort <button type="button" class="${state.radSort === 'energy' ? 'active' : ''}" data-on-click="nz:radSort" data-sort="energy">by energy</button><button type="button" class="${state.radSort === 'intensity' ? 'active' : ''}" data-on-click="nz:radSort" data-sort="intensity">by intensity</button></span></div>`;
      if (!list.length) {
        pane.innerHTML = title + `<p class="nz-dim">${nuc.s[k] && nuc.s[k].st ? 'A stable state does not decay.' : 'This database has no decay data set with this state as its parent.'}</p>`;
        return;
      }
      const html = [title];
      const numOf = (s) => { const v = P.num(s); return Number.isFinite(v) ? v : -1; };
      const sortRows = (rows, iCol) => (state.radSort === 'intensity' ? rows.slice().sort((p, q) => numOf(q[iCol]) - numOf(p[iCol])) : rows);
      const unit = (r) => (r.grel ? 'relative' : '% per decay');
      /* Spontaneous fission is filed fragment by fragment: one data set per
         fission product, each with that fragment's gamma rays. They are
         folded into one group so the rest of the radiation stays in view. */
      const sf = list.filter((r) => r.mode === 'SF');
      const others = list.filter((r) => r.mode !== 'SF');
      let sfOpen = false;
      for (const r of others.concat(sf)) {
        if (r.mode === 'SF' && !sfOpen) {
          sfOpen = true;
          html.push(`<details class="nz-sf"><summary>Spontaneous fission: γ rays of ${sf.length} fission fragment${sf.length > 1 ? 's' : ''}</summary>`);
        }
        const under = state.idx.get(r.under[0], r.under[1]);
        html.push(`<section class="nz-rad"><h4>${supHtml(C.modeText(r.mode))} decay <span class="nz-dim">· data set “${esc(r.dsid)}”, under ${under ? nameHtml(r.under[0], r.under[1], 0, under) : esc(r.under.join(','))}${r.br ? ` · branching ${esc(r.br)}${r.dbr ? ' ' + esc(r.dbr) : ''}` : ''}${r.qp ? ` · Q = ${esc(r.qp)}${r.dqp ? ' ' + esc(r.dqp) : ''} keV` : ''}</span></h4>`);
        const block = (label, head, rows, iCol, cellsOf) => {
          if (!rows || !rows.length) return;
          const sorted = sortRows(rows, iCol);
          const n = state.radAll ? sorted.length : Math.min(sorted.length, LINE_PAGE);
          html.push(`<div class="nz-table-wrap"><table class="nz-table"><caption>${label} <span class="nz-dim">(${rows.length})</span></caption><thead><tr>${head}</tr></thead><tbody>`);
          for (let i = 0; i < n; i++) html.push(`<tr>${cellsOf(sorted[i])}</tr>`);
          html.push('</tbody></table></div>');
          if (n < sorted.length) html.push(`<p class="nz-note">${sorted.length - n} more — <button type="button" class="nz-link" data-on-click="nz:radAll">show all</button></p>`);
        };
        const vu = (v, u) => `${supHtml(C.expText(v || ''))}${u ? `<span class="nz-unc">${esc(u)}</span>` : ''}`;
        block('γ rays', `<th>E<sub>γ</sub> (keV)</th><th>I<sub>γ</sub> (${unit(r)})</th><th class="text">Mult.</th><th>From level (keV)</th>`, r.g, 2,
          (g) => `<td>${vu(g[0], g[1])}</td><td>${vu(g[2], g[3])}</td><td class="text">${esc(g[4] || '')}</td><td>${esc(g[5] || '')}</td>`);
        block('α particles', '<th>E<sub>α</sub> (keV)</th><th>I<sub>α</sub> (% per decay)</th><th>To level (keV)</th><th>HF</th>', r.al, 2,
          (x) => `<td>${vu(x[0], x[1])}</td><td>${vu(x[2], x[3])}</td><td>${esc(x[4] || '')}</td><td>${esc(x[5] || '')}</td>`);
        block('β⁻ branches', '<th>E<sub>max</sub> (keV)</th><th>E<sub>mean</sub> (keV)</th><th>I<sub>β</sub> (% per decay)</th><th>To level (keV)</th><th>log ft</th>', r.b, 3,
          (x) => `<td>${vu(x[0], x[1])}</td><td>${esc(x[2] || '')}</td><td>${vu(x[3], x[4])}</td><td>${esc(x[5] || '')}</td><td>${esc(x[6] || '')}</td>`);
        block('ε and β⁺ branches', '<th>I<sub>β⁺</sub> (%)</th><th>I<sub>ε</sub> (%)</th><th>E<sub>mean</sub>(β⁺) (keV)</th><th>To level (keV)</th><th>log ft</th>', r.ec, 3,
          (x) => `<td>${vu(x[1], x[2])}</td><td>${vu(x[3], x[4])}</td><td>${esc(x[5] || '')}</td><td>${esc(x[6] || '')}</td><td>${esc(x[7] || '')}</td>`);
        block('Particles', '<th class="text">Particle</th><th>E (keV)</th><th>I</th><th>To level (keV)</th>', r.p, 3,
          (x) => `<td class="text">${esc({ N: 'n', P: 'p', A: 'α', D: 'd', T: 't' }[x[0]] || x[0])}</td><td>${vu(x[1], x[2])}</td><td>${vu(x[3], x[4])}</td><td>${esc(x[5] || '')}</td>`);
        if (r.grel) html.push('<p class="nz-note">The data set gives no normalisation for its γ rays, so their intensities are relative.</p>');
        html.push('</section>');
      }
      if (sfOpen) html.push('</details>');
      html.push('<p class="nz-note">Per 100 decays of the parent where the data set’s normalisation allows it. X-rays and conversion electrons are not in ENSDF as records and are not listed.</p>');
      pane.innerHTML = html.join('');
    });
  }

  function renderDatasets() {
    const pane = $('nzPaneDatasets');
    withDetail(pane, (det) => {
      const { z, a } = state.sel;
      const nuc = state.idx.get(z, a);
      if (!det) { pane.innerHTML = '<p class="nz-dim">No data sets.</p>'; return; }
      const kinds = { adopted: 'adopted', decay: 'decay', reaction: 'reaction', comments: 'comments', references: 'references' };
      const html = [`<div class="nz-pane-head"><h3>Data sets for ${nameHtml(z, a, 0, nuc)}</h3><span class="nz-dim">${det.ds.length}</span></div>`];
      html.push('<div class="nz-table-wrap"><table class="nz-table"><thead><tr><th class="text">Kind</th><th class="text">Data set</th><th class="text">References</th><th class="text">Publication</th><th class="text">Entered</th></tr></thead><tbody>');
      for (const [kind, dsid, ref, pub, date] of det.ds) {
        html.push(`<tr><td class="text"><span class="nz-kind nz-kind-${esc(kinds[kind] || 'reaction')}">${esc(kinds[kind] || kind)}</span></td><td class="text">${esc(dsid)}</td><td class="text nz-dim">${esc(ref || '')}</td><td class="text">${esc(pub || '')}</td><td class="text">${esc(fmtDate(date || ''))}</td></tr>`);
      }
      html.push('</tbody></table></div>');
      if (det.hist && det.hist.length) {
        html.push('<h3>History of the adopted data set</h3><ul class="nz-hist">');
        for (const [typ, aut, cit, cut, dat, com] of det.hist) {
          html.push(`<li><b>${esc({ FUL: 'Full evaluation', UPD: 'Update', MOD: 'Modification', ERR: 'Erratum', FMT: 'Format change', EXP: 'Experimental' }[typ] || typ || 'Entry')}</b>${aut ? ` by ${esc(aut)}` : ''}${cit ? `, ${esc(cit)}` : ''}${cut ? `; literature cut-off ${esc(cut)}` : ''}${dat ? `; ${esc(dat)}` : ''}${com ? ` <span class="nz-dim">— ${esc(com)}</span>` : ''}</li>`);
        }
        html.push('</ul>');
      }
      pane.innerHTML = html.join('');
    });
  }

  /* ---------------------------------------------------------------------
     The decay-chain view
     --------------------------------------------------------------------- */
  function renderChainView() {
    const nameEl = $('nzChainTabName');
    if (!state.root || !state.idx || !state.chain) {
      nameEl.textContent = '';
      if (state.view === 'chain') {
        $('nzChainSvg').replaceChildren();
        $('nzChainTable').innerHTML = '';
        $('nzChainNote').innerHTML = '<p class="nz-dim">Choose a nuclide on the chart to see its decay chain.</p>';
        $('nzChainState').innerHTML = '';
      }
      return;
    }
    const r = state.root;
    const nuc = state.idx.get(r.z, r.a);
    nameEl.replaceChildren(supNode(C.plainName(r.z, r.a, r.k, nuc)));
    if (state.view !== 'chain') return;
    const ch = state.chain;
    /* Which state of the first nuclide the chain starts from. */
    const stSel = $('nzChainState');
    if (nuc.s.length > 1) {
      /* An option cannot hold markup, so no superscripts at all: 234mPa, 4.5E9 y. */
      stSel.innerHTML = nuc.s.map((s, i) => `<option value="${i}">${esc(C.name(r.z, r.a, i, nuc).text)}${i ? ` (${esc(s.e)} keV)` : ''} · ${esc(C.asciiText(s.st ? 'stable' : C.halfLifeShort(s)))}</option>`).join('');
      stSel.value = String(r.k);
      stSel.closest('label').hidden = false;
    } else {
      stSel.innerHTML = '';
      stSel.closest('label').hidden = true;
    }
    const svg = $('nzChainSvg');
    const sel = state.sel ? `${state.sel.z},${state.sel.a},${state.sel.k}` : '';
    const size = CH.render(svg, ch, {
      selected: sel,
      onPick: (n) => { if (n.kind === 'state') select({ z: n.z, a: n.a, k: n.k }, { from: 'chain' }); },
      onHover: (n, ev) => { if (n) showTip(chainTip(n), ev.clientX, ev.clientY); else hideTip(); },
    });
    fitChain(size);
    const notes = [];
    if (nuc.s[r.k] && nuc.s[r.k].st) notes.push(`${supHtml(C.plainName(r.z, r.a, r.k, nuc))} is stable: there is no chain to follow.`);
    if (ch.truncated) notes.push('The chain is larger than the drawing allows; it has been cut off.');
    if (ch.edges.some((e) => e.inferred)) notes.push('A dashed arrow marked * is a branch ENSDF does not state: an excited state assumed to decay by gamma emission, or a beta or electron-capture branch inferred from the Q-values.');
    if (ch.edges.some((e) => e.pct === null)) notes.push('A dashed arrow marked ? is a mode the evaluators list without a percentage.');
    /* What the half-life setting left out, heaviest first as the chain runs. */
    const left = new Map();
    for (const e of ch.edges) for (const x of e.skipped) if (!left.has(x.key)) left.set(x.key, x);
    if (left.size) {
      const order = (x) => x.key.split(',').map(Number);
      const names = [...left.values()].sort((p, q) => { const [z1, a1, k1] = order(p), [z2, a2, k2] = order(q); return (a2 - a1) || (z1 - z2) || (k2 - k1); })
        .map((x) => supHtml(x.name));
      const life = lifeOption();
      notes.push(`Left out, as ${life.life ? 'members' : 'isomers'} that live less than ${esc(life.span)}: ${names.slice(0, 30).join(', ')}${names.length > 30 ? `, and ${names.length - 30} more` : ''}. The chain goes straight on to where they decay, each share the product of the branches on the way. An arrow marked “via” jumps over them; what went through an isomer’s IT joins the arrow to the same nuclide.`);
    }
    $('nzChainNote').innerHTML = notes.length ? `<ul>${notes.map((n) => `<li>${n}</li>`).join('')}</ul>` : '';
    renderChainTable(ch);
  }

  /* The drawing shrinks to the width it has, down to 70 %; below that it scrolls. */
  function fitChain(size) {
    const svg = $('nzChainSvg');
    const box = document.querySelector('.nz-chain-scroll');
    const cs = getComputedStyle(box);
    const room = box.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 2;
    if (!size || !(room > 0)) return;
    const scale = Math.max(0.7, Math.min(1.25, room / size.width));
    svg.setAttribute('width', Math.round(size.width * scale));
    svg.setAttribute('height', Math.round(size.height * scale));
    /* A chain wider than the view opens scrolled to where it starts -- usually
       its top right, the heaviest member -- with as much of where that decays
       to beside it as fits. */
    const draw = svg.parentElement;
    if (size.root && size.width * scale > draw.clientWidth) {
      const f = size.focus || size.root;
      const right = (f.x + f.w) * scale + 24;
      const left = Math.max(0, size.root.x * scale - 24);
      draw.scrollLeft = Math.min(left, Math.max(0, right - draw.clientWidth));
    }
  }

  /*
    How long a member must live to be drawn in a chain. The first two keep
    every nuclide: every state, or all but the isomers under a second, which
    are many and seldom matter (the default). The rest leave out every
    member, nuclide or isomer, that lives less -- but never the one the chain
    starts from.
  */
  const LIFE_OPTIONS = [
    { id: 'all', text: 'all members', life: 0, iso: 0, span: '' },
    { id: 'iso', text: 'all but isomers < 1 s', life: 0, iso: 1, span: '1 s' },
    ...[[1e-3, '1 ms'], [1, '1 s'], [60, '1 min'], [3600, '1 h'], [86400, '1 d'],
      [C.YEAR_S, '1 y'], [10 * C.YEAR_S, '10 y'], [100 * C.YEAR_S, '100 y'], [1000 * C.YEAR_S, '1000 y']]
      .map(([v, span]) => ({ id: span.replace(' ', ''), text: `T½ ≥ ${span}`, life: v, iso: 0, span })),
  ];

  function lifeOption() {
    return LIFE_OPTIONS.find((o) => o.id === state.chainOpt.life) || LIFE_OPTIONS[1];
  }

  /* The chain settings sit beside the view tabs, and serve both views. */
  function renderChainControls() {
    const life = $('nzMinLife');
    if (!life.options.length) life.innerHTML = LIFE_OPTIONS.map((o) => `<option value="${o.id}">${esc(o.text)}</option>`).join('');
    state.chainOpt.life = lifeOption().id;
    life.value = state.chainOpt.life;
    const br = $('nzMinBranch');
    if (![...br.options].some((o) => +o.value === state.chainOpt.minBranch)) state.chainOpt.minBranch = 0;
    br.value = [...br.options].find((o) => +o.value === state.chainOpt.minBranch).value;
    $('nzOverlay').checked = state.chainOpt.overlay;
  }

  function chainTip(n) {
    const box = document.createElement('div');
    const head = document.createElement('div');
    head.className = 'nz-tip-head';
    head.appendChild(supNode(CH.nodeName(n)));
    box.appendChild(head);
    const line = (text) => { const d = document.createElement('div'); d.appendChild(supNode(text)); box.appendChild(d); };
    if (n.kind === 'fission') line('Spontaneous fission');
    else if (n.kind === 'missing') line('Not in this database');
    else {
      line(n.st.st ? 'stable' : `T½ ${C.halfLifeText(n.st, true)}`);
      if (n.k > 0) line(`${n.st.e} keV`);
    }
    if (n !== state.chain.root) line(`${n.cumUnknown && !n.cum ? '?' : C.pctText(n.cum * 100)} of the decays pass through here`);
    for (const e of n.out) line(`${C.modeText(e.mode)} ${CH.shareText(e)} → ${CH.nodeName(e.to)}${viaSuffix(e)}`);
    return box;
  }

  /* After an arrow in words: "via 234mPa" for one of its own, "(94.7 % via
     137mBa)" for the part of an ordinary one that went through an isomer's IT. */
  function viaSuffix(e) {
    const v = CH.viaText(e);
    return !v ? '' : e.via.length ? ` ${v}` : ` (${v})`;
  }

  function chainRows(ch) {
    return ch.nodes.filter((n) => n.kind !== 'fission').sort((p, q) => (p.depth - q.depth) || (q.a - p.a) || (q.z - p.z));
  }

  function renderChainTable(ch) {
    const html = ['<table class="nz-table nz-chain-tab"><thead><tr><th class="text">Member</th><th class="text">T½</th><th class="text">Decays by</th><th>Reached by (% of the first nuclide’s decays)</th></tr></thead><tbody>'];
    for (const n of chainRows(ch)) {
      const who = n.kind === 'missing' ? `${nameHtml(n.z, n.a, 0, null)} <span class="nz-dim">not in ENSDF</span>` : nucLink(n.z, n.a, n.k);
      const life = n.kind === 'missing' ? '' : supHtml(C.halfLifeText(n.st, true));
      const outs = n.out.map((e) => `${supHtml(C.modeText(e.mode))} ${supHtml(CH.shareText(e))}${e.inferred ? '*' : ''} → ${e.to.kind === 'fission' ? 'fission' : e.to.kind === 'missing' ? nameHtml(e.to.z, e.to.a, 0, null) : nameHtml(e.to.z, e.to.a, e.to.k, e.to.nuc)}${viaSuffix(e) ? ` <span class="nz-dim" title="${esc(C.asciiText(CH.edgeAbout(e)))}">${supHtml(viaSuffix(e).trim())}</span>` : ''}`).join('<br>');
      const reached = n === ch.root ? '100 %' : (n.cumUnknown && !n.cum ? '?' : C.pctText(n.cum * 100)) + (n.cumUnknown && n.cum ? ' or more' : '') + (n.bounded ? ' †' : '');
      html.push(`<tr class="${n === ch.root ? 'current' : ''}"><td class="text">${who}</td><td class="text">${life}</td><td class="text">${outs || (n.st && n.st.st ? '<span class="nz-dim">stable</span>' : '<span class="nz-dim">—</span>')}</td><td>${supHtml(reached)}</td></tr>`);
    }
    html.push('</tbody></table>');
    if (ch.nodes.some((n) => n.bounded)) html.push('<p class="nz-note">† Reached through a branch the evaluators give only as a limit (&lt;, ≤, &gt;, ≥); the share uses the limit’s value.</p>');
    $('nzChainTable').innerHTML = html.join('');
  }

  /* ---------------------------------------------------------------------
     Views, tabs and the legend
     --------------------------------------------------------------------- */
  function setView(view) {
    state.view = view;
    document.querySelectorAll('.nz-views [data-view]').forEach((b) => {
      const on = b.dataset.view === view;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    document.querySelectorAll('[data-viewpane]').forEach((p) => { p.hidden = p.dataset.viewpane !== view; });
    $('nzChartTools').hidden = view !== 'chart';
    if (view === 'chart') chart.resize();
    renderChainView();
    saveState();
  }

  function renderLegend() {
    const box = $('nzLegend');
    const mode = state.colour;
    const spec = C.COLOUR_MODES[mode];
    const theme = chart.theme;
    const pal = C.PALETTE[theme];
    const items = [];
    const sw = (colour) => `<span class="nz-sw" style="background:${esc(colour)}"></span>`;
    if (mode === 'halflife') {
      items.push(`<li data-cls="-2">${sw(pal.stable)}<span>stable</span></li>`);
      C.HALF_LIFE_CLASSES.forEach((c, i) => items.push(`<li data-cls="${i}">${sw(pal.halfLife[i])}<span>${supHtml(c.label)}</span></li>`));
      items.push(`<li data-cls="-1">${sw(pal.unknown)}<span>not known</span></li>`);
      box.innerHTML = `<div class="nz-legend-head">Half-life of the ground state</div><ul class="nz-legend-list">${items.join('')}</ul>`;
    } else if (mode === 'mode') {
      for (const [k, label] of C.MODE_LEGEND) items.push(`<li data-cls="${k}">${sw(pal.mode[k])}<span>${supHtml(label)}</span></li>`);
      box.innerHTML = `<div class="nz-legend-head">Main decay mode</div><ul class="nz-legend-list">${items.join('')}</ul>`;
    } else {
      const d = chart.domain;
      if (!d) { box.innerHTML = `<div class="nz-legend-head">${supHtml(spec.label)}</div><p class="nz-dim">No values.</p>`; return; }
      const stops = [];
      for (let i = 0; i <= 12; i++) {
        const t = i / 12;
        const v = d.kind === 'diverging' ? d.lo + (d.hi - d.lo) * t : (d.kind === 'log' ? Math.pow(10, d.lo + (d.hi - d.lo) * t) : d.lo + (d.hi - d.lo) * t);
        stops.push(C.scaleColour(d, v, theme));
      }
      const fmt = (x) => (mode === 'year' ? String(Math.floor(x)) : Math.abs(x) >= 1000 ? `${String(+(x / 1000).toPrecision(3))} MeV` : `${String(+x.toPrecision(3))} keV`).replace(/^-/, '−');
      const lo = d.kind === 'log' ? Math.pow(10, d.lo) : d.lo, hi = d.kind === 'log' ? Math.pow(10, d.hi) : d.hi;
      box.innerHTML = `<div class="nz-legend-head">${supHtml(spec.label)}</div>
        <div class="nz-ramp" style="background:linear-gradient(90deg,${stops.map(esc).join(',')})"></div>
        <div class="nz-ramp-ticks"><span>${esc(fmt(lo))}</span>${d.kind === 'diverging' ? '<span>0</span>' : ''}<span>${esc(fmt(hi))}${mode === 'year' ? '' : ' or more'}</span></div>
        <ul class="nz-legend-list"><li>${sw(pal.unknown)}<span>no value</span></li></ul>
        <p class="nz-legend-note">${esc(spec.note || '')}</p>`;
    }
  }

  /* ---------------------------------------------------------------------
     Tooltip
     --------------------------------------------------------------------- */
  const tip = () => $('nzTip');
  function showTip(content, x, y) {
    const t = tip();
    t.replaceChildren(content);
    t.hidden = false;
    const r = t.getBoundingClientRect();
    let left = x + 14, top = y + 16;
    if (left + r.width > window.innerWidth - 8) left = x - r.width - 14;
    if (top + r.height > window.innerHeight - 8) top = y - r.height - 12;
    t.style.left = `${Math.max(8, left)}px`;
    t.style.top = `${Math.max(8, top)}px`;
  }
  function hideTip() { tip().hidden = true; }

  function chartTip(n) {
    const box = document.createElement('div');
    const g = n.s && n.s[0];
    const head = document.createElement('div');
    head.className = 'nz-tip-head';
    head.appendChild(supNode(C.plainName(n.z, n.a, 0, n)));
    const long = document.createElement('span');
    long.className = 'nz-tip-long';
    long.textContent = C.name(n.z, n.a, 0, n).long;
    head.appendChild(long);
    box.appendChild(head);
    const line = (text, cls) => { const d = document.createElement('div'); if (cls) d.className = cls; d.appendChild(supNode(text)); box.appendChild(d); };
    if (!g) { line('no adopted data'); return box; }
    line(g.st ? 'stable' : `T½ ${C.halfLifeText(g, true)}${C.halfLifeAlt(g) && !/ y$/.test(C.halfLifeText(g)) ? ` (${C.halfLifeAlt(g)})` : ''}`);
    const modes = (g.dm || []).map((dm) => { const m = C.modeStated(dm); return `${m.mode} ${m.value === '?' ? '?' : (m.rel ? m.rel + ' ' : '') + m.value + ' %'}`; });
    const inf = (g.br || []).filter((b) => b[3]).map((b) => `${C.modeText(b[0])} ${C.pctText(b[1])} (inferred)`);
    if (modes.length || inf.length) line(modes.concat(inf).join(', '));
    const bits = [];
    if (g.j) bits.push(`Jπ ${g.j}`);
    if (n.s.length > 1) bits.push(`${n.s.length - 1} isomer${n.s.length > 2 ? 's' : ''}`);
    if (bits.length) line(bits.join(' · '), 'nz-tip-dim');
    if (n.aq) line(`adopted data set: ${n.aq.toLowerCase()}`, 'nz-tip-dim');
    const mode = state.colour;
    if (mode !== 'halflife' && mode !== 'mode') {
      const v = C.COLOUR_MODES[mode].get(n);
      line(`${C.COLOUR_MODES[mode].label} ${Number.isFinite(v) ? (mode === 'year' ? fmtDate(n.ev[1]) : `${v} keV`) : '—'}`, 'nz-tip-dim');
    }
    return box;
  }

  /* ---------------------------------------------------------------------
     Downloads
     --------------------------------------------------------------------- */
  function download(name, blobOrText, type) {
    const blob = blobOrText instanceof Blob ? blobOrText : new Blob([blobOrText], { type: `${type};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  const cell = (v) => kvotCsvCell(v === undefined || v === null ? '' : String(v));
  const releaseTag = () => (state.source ? state.source.summary.release.id || 'ensdf' : 'ensdf');

  function chartCsv() {
    const head = ['Z', 'N', 'A', 'nuclide', 'element', 'half-life', 'half-life unc', 'half-life (s)', 'J pi', 'decay modes', 'Q(beta-) keV', 'dQ', 'S(n) keV', 'dS(n)', 'S(p) keV', 'dS(p)', 'Q(alpha) keV', 'dQ(alpha)', 'E(2+) keV', 'isomers', 'evaluated', 'citation'];
    const rows = [head.map(cell).join(',')];
    for (const n of state.idx.list) {
      const g = n.s && n.s[0];
      const q = n.q || [];
      const modes = g ? (g.dm || []).map((d) => `${d[0]}${d[1] === '=' ? '=' : ' ' + d[1] + ' '}${d[2]}${d[3] ? ' ' + d[3] : ''}`).join('; ') : '';
      rows.push([n.z, n.a - n.z, n.a, C.name(n.z, n.a, 0, n).text, C.ELEMENTS[n.z] ? C.ELEMENTS[n.z][1] : '', g ? (g.st ? 'stable' : g.t) : '', g ? g.dt || '' : '', g && g.ts !== undefined ? g.ts : (g && g.st ? 'Infinity' : ''), g ? g.j : '', modes,
        q[0], q[1], q[2], q[3], q[4], q[5], q[6], q[7], n.e2 || '', Math.max(0, (n.s || []).length - 1), n.ev ? n.ev[1] : '', n.ev ? n.ev[4] : ''].map(cell).join(','));
    }
    download(`ensdf-${releaseTag()}-ground-states.csv`, rows.join('\r\n'), 'text/csv');
  }

  function chainCsv() {
    const ch = state.chain;
    if (!ch) return;
    const rows = [['member', 'Z', 'A', 'state', 'level energy keV', 'half-life', 'half-life (s)', 'decay', 'reached (% of first nuclide decays)'].map(cell).join(',')];
    for (const n of chainRows(ch)) {
      const outs = n.out.map((e) => `${e.mode} ${e.limit || (e.more ? '>=' : '')}${e.pct === null ? '?' : e.pct}% -> ${e.to.kind === 'fission' ? 'fission' : C.name(e.to.z, e.to.a, e.to.k, e.to.nuc).text}${C.asciiText(viaSuffix(e))}${e.inferred ? ' (inferred)' : ''}`).join('; ');
      rows.push([n.kind === 'missing' ? `${n.a}${C.ELEMENTS[n.z] ? C.ELEMENTS[n.z][0] : n.z}` : C.name(n.z, n.a, n.k, n.nuc).text, n.z, n.a, n.k, n.st ? n.st.e : '', n.st ? (n.st.st ? 'stable' : n.st.t) : '', n.st && n.st.ts !== undefined ? n.st.ts : '', outs, n === ch.root ? 100 : (n.cumUnknown && !n.cum ? '' : +(n.cum * 100).toPrecision(8))].map(cell).join(','));
    }
    download(`decay-chain-${C.name(ch.root.z, ch.root.a, ch.root.k, ch.root.nuc).key}.csv`, rows.join('\r\n'), 'text/csv');
  }

  function chainSvg() {
    const svg = $('nzChainSvg');
    if (!state.chain || !svg.firstChild) return;
    download(`decay-chain-${C.name(state.chain.root.z, state.chain.root.a, state.chain.root.k, state.chain.root.nuc).key}.svg`, CH.svgFile(svg), 'image/svg+xml');
  }

  function chainPng() {
    const svg = $('nzChainSvg');
    if (!state.chain || !svg.firstChild) return;
    const w = +svg.getAttribute('width'), h = +svg.getAttribute('height');
    const img = new Image();
    const url = URL.createObjectURL(new Blob([CH.svgFile(svg)], { type: 'image/svg+xml' }));
    img.onload = () => {
      const scale = 2;
      const c = document.createElement('canvas');
      c.width = w * scale; c.height = h * scale;
      const g = c.getContext('2d');
      g.scale(scale, scale);
      g.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      c.toBlob((b) => download(`decay-chain-${C.name(state.chain.root.z, state.chain.root.a, state.chain.root.k, state.chain.root.nuc).key}.png`, b), 'image/png');
    };
    img.onerror = () => { URL.revokeObjectURL(url); reportFailure('ensdf:chainPng', new Error('the drawing could not be turned into an image'), { userMessage: 'The PNG could not be made.' }); };
    img.src = url;
  }

  /* ---------------------------------------------------------------------
     Opening files
     --------------------------------------------------------------------- */
  async function openChosen(files) {
    files = [...files].filter((f) => f && f.size);
    if (!files.length) return;
    const total = files.reduce((t, f) => t + f.size, 0);
    const limit = kvotFileTooLarge({ name: files.length === 1 ? files[0].name : 'The selection', size: total }, 1024 * 1024 * 1024);
    if (limit.tooLarge) { notifyUser(limit.reason); return; }
    try {
      await readAndUse(files, null);
    } catch (e) {
      reportFailure('ensdf:open', e, { userMessage: 'The ENSDF file could not be read.' });
      sourceStatus();
    }
  }

  function setupDrop() {
    const target = document.body;
    let depth = 0;
    target.addEventListener('dragenter', (ev) => { if ([...(ev.dataTransfer.types || [])].includes('Files')) { depth++; $('nz').classList.add('dropping'); ev.preventDefault(); } });
    target.addEventListener('dragover', (ev) => { if ([...(ev.dataTransfer.types || [])].includes('Files')) ev.preventDefault(); });
    target.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) $('nz').classList.remove('dropping'); });
    target.addEventListener('drop', (ev) => {
      if (!ev.dataTransfer || !ev.dataTransfer.files.length) return;
      ev.preventDefault();
      depth = 0;
      $('nz').classList.remove('dropping');
      openChosen(ev.dataTransfer.files);
    });
  }

  /* ---------------------------------------------------------------------
     The panel's width
     --------------------------------------------------------------------- */
  function applyPanelWidth() {
    if (state.panelWidth) $('nz').style.setProperty('--nz-panel-width', `${state.panelWidth}px`);
    else $('nz').style.removeProperty('--nz-panel-width');
  }

  function setupResize() {
    const handle = $('nzResize');
    let start = null;
    handle.addEventListener('pointerdown', (ev) => {
      start = { x: ev.clientX, w: $('nzPanel').getBoundingClientRect().width };
      handle.setPointerCapture(ev.pointerId);
      handle.classList.add('active');
    });
    handle.addEventListener('pointermove', (ev) => {
      if (!start) return;
      const max = Math.max(320, window.innerWidth - 360);
      state.panelWidth = Math.round(Math.max(300, Math.min(max, start.w - (ev.clientX - start.x))));
      applyPanelWidth();
    });
    const end = () => { if (start) { start = null; handle.classList.remove('active'); saveState(); } };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    handle.addEventListener('dblclick', () => { state.panelWidth = null; applyPanelWidth(); saveState(); });
    handle.addEventListener('keydown', (ev) => {
      const d = ev.key === 'ArrowLeft' ? 24 : ev.key === 'ArrowRight' ? -24 : 0;
      if (!d) return;
      ev.preventDefault();
      state.panelWidth = Math.round(Math.max(300, ($('nzPanel').getBoundingClientRect().width) + d));
      applyPanelWidth();
      saveState();
    });
  }

  /* ---------------------------------------------------------------------
     Start
     --------------------------------------------------------------------- */
  let chart = null;

  async function start() {
    const saved = loadState();
    applyPanelWidth();
    $('nzColour').value = state.colour;
    renderChainControls();
    chart = KVOT_ENSDF_CHART.createChart($('nzChart'), {
      onSelect: (s) => select(s, { from: 'chart', centre: s.via !== 'chart' }),
      onHover: (n, x, y) => { if (n) showTip(chartTip(n), x, y); else hideTip(); },
    });
    chart.setMode(state.colour);
    document.documentElement.addEventListener('kvot-theme-change', () => { renderLegend(); drawMiniChain(); if (state.view === 'chain') renderChainView(); });
    setupResize();
    setupDrop();
    /* Refit the chain when its container changes width. The scroll box is
       observed, not the drawing's own box, whose size follows the drawing
       and would set off a resize loop. */
    let refit = 0;
    new ResizeObserver(() => {
      if (refit) return;
      refit = requestAnimationFrame(() => {
        refit = 0;
        if (state.view !== 'chain' || !state.chain) return;
        const vb = ($('nzChainSvg').getAttribute('viewBox') || '').split(' ').map(Number);
        if (vb.length === 4) fitChain({ width: vb[2], height: vb[3] });
      });
    }).observe(document.querySelector('.nz-chain-scroll'));
    setView(state.view);
    renderPanel();

    try {
      state.releases = await loadScriptData('*', 'releases', `${DATA_DIR}releases.js`);
    } catch (e) {
      state.releases = [];
    }
    try { state.stored = await IDB.list(); } catch (e) { state.stored = []; }
    let key = state.dbKey;
    const known = (k) => (k.startsWith('b:') && state.releases.some((r) => `b:${r.id}` === k)) || (k.startsWith('s:') && state.stored.some((s) => `s:${s.key}` === k));
    if (!key || !known(key)) key = state.releases.length ? `b:${state.releases[0].id}` : (state.stored[0] ? `s:${state.stored[0].key}` : '');
    if (!key) {
      status('No ENSDF release is installed on this site. Open one with “Open ENSDF…”.', 'warn');
      renderDbMenu();
      return;
    }
    await switchDb(key);
    if (!state.source && state.releases.length) await switchDb(`b:${state.releases[0].id}`);
    const fromHash = decodeURIComponent(location.hash.slice(1));
    const pick = (fromHash && pickFromQuery(fromHash)) || (saved && saved.sel && state.idx && state.idx.get(saved.sel.z, saved.sel.a) ? saved.sel : null);
    if (pick) select(pick, { from: 'start' });
    window.addEventListener('hashchange', () => {
      const p = pickFromQuery(decodeURIComponent(location.hash.slice(1)));
      if (p && (!state.sel || p.z !== state.sel.z || p.a !== state.sel.a || p.k !== state.sel.k)) select(p, { from: 'hash' });
    });
  }

  /* ---------------------------------------------------------------------
     Actions
     --------------------------------------------------------------------- */
  registerActions({
    'nz:searchKey': (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); runSearch(); } },
    'nz:search': () => runSearch(),
    'nz:colour': (ev, el) => { state.colour = el.value; chart.setMode(state.colour); renderLegend(); saveState(); },
    'nz:db': (ev, el) => switchDb(el.value),
    'nz:open': () => $('nzFile').click(),
    'nz:fileChosen': (ev, el) => { const f = [...el.files]; el.value = ''; openChosen(f); },
    'nz:forget': async () => {
      if (!state.source || !state.source.key.startsWith('s:')) return;
      const key = state.source.key.slice(2);
      try { await IDB.remove(key); state.stored = await IDB.list(); } catch (e) { reportFailure('ensdf:forget', e); }
      if (state.releases.length) await switchDb(`b:${state.releases[0].id}`);
      renderDbMenu();
      notifyUser('The opened database is no longer kept in this browser.');
    },
    'nz:view': (ev, el) => setView(el.dataset.view),
    'nz:tab': (ev, el) => { state.tab = el.dataset.tab; renderPanel(); saveState(); },
    'nz:go': (ev, el) => { ev.preventDefault(); select({ z: +el.dataset.z, a: +el.dataset.a, k: +el.dataset.k }, { from: state.view === 'chain' ? 'chain' : 'panel' }); },
    'nz:state': (ev, el) => { ev.preventDefault(); if (state.sel) select({ z: state.sel.z, a: state.sel.a, k: +el.dataset.k }, { from: 'panel' }); },
    'nz:showChain': () => { if (state.sel) { state.root = { ...state.sel }; computeChain(); } setView('chain'); },
    'nz:chainState': (ev, el) => { if (state.root) select({ z: state.root.z, a: state.root.a, k: +el.value }, { from: 'panel' }); },
    'nz:minBranch': (ev, el) => { state.chainOpt.minBranch = +el.value; computeChain(); renderChainView(); renderPanel(); saveState(); },
    'nz:minLife': (ev, el) => { state.chainOpt.life = el.value; computeChain(); renderChainView(); renderPanel(); saveState(); },
    'nz:overlay': (ev, el) => { state.chainOpt.overlay = el.checked; computeChain(); saveState(); },
    'nz:chainSvg': () => chainSvg(),
    'nz:chainPng': () => chainPng(),
    'nz:chainCsv': () => chainCsv(),
    'nz:chainFrame': () => { if (!state.chain) return; setView('chart'); chart.frame([...new Set(state.chain.nodes.filter((n) => n.kind !== 'fission').map((n) => n.z * 1000 + n.a))]); },
    'nz:zoomIn': () => chart.zoom(1.5),
    'nz:zoomOut': () => chart.zoom(1 / 1.5),
    'nz:fit': () => chart.fit(),
    'nz:chartPng': () => chart.toBlob((b) => download(`chart-of-nuclides-${releaseTag()}.png`, b)),
    'nz:chartCsv': () => { if (state.idx) chartCsv(); },
    'nz:levelsAll': () => { state.levelsAll = true; renderLevels(); },
    'nz:radSort': (ev, el) => { state.radSort = el.dataset.sort; renderRadiation(); saveState(); },
    'nz:radAll': () => { state.radAll = true; renderRadiation(); },
  });

  function runSearch() {
    const q = $('nzSearch').value;
    const p = pickFromQuery(q);
    if (!p) {
      notifyUser(state.idx ? `No nuclide called “${q.trim()}” in ${state.source.label}. Try 60Co, U-238, Tc-99m or an element name.` : 'The database is still loading.');
      return;
    }
    select(p, { from: 'search' });
  }

  /* Legend hover: light up one class, dim the rest. */
  function setupLegendHover() {
    const box = $('nzLegend');
    box.addEventListener('pointerover', (ev) => {
      const li = ev.target.closest('li[data-cls]');
      if (!li) return;
      const cls = li.dataset.cls;
      const want = state.colour === 'halflife' ? +cls : cls;
      chart.setHighlight((n, c) => c === want);
    });
    box.addEventListener('pointerleave', () => chart.setHighlight(null));
  }

  window.ENSDFPage = {
    get state() { return state; },
    get chart() { return chart; },
    select: (q) => { const p = typeof q === 'string' ? pickFromQuery(q) : q; if (p) select(p, { from: 'test' }); return p; },
    openFiles: (files) => openChosen(files),
    switchDb,
  };

  function boot() {
    setupLegendHover();
    start().catch((e) => reportFailure('ensdf:start', e, { userMessage: 'The chart could not be loaded.' }));
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
