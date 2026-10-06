/* ==========================================================================
   ENSDF.HTML: THE PAGE

   Wiring only. The reading is ensdf-parse.js, the shared logic
   ensdf-core.js, the chart ensdf-chart.js and the chain drawing
   ensdf-chain.js. This file keeps the state, loads and switches databases,
   and fills the panel.

   Databases. The page starts on the newest release built into the site. A
   visitor can open another -- a release zip from the NNDC archive, or ENSDF
   text files -- which is read in a worker, never uploaded, and kept in this
   browser so the database menu can switch back to it later. NNDC's server
   sends no CORS header, so the page cannot fetch a release from there by
   itself. The menu lists every release in NNDC's archive anyway, and
   choosing one that is not to hand says which file to download and opens it
   once it is here. Where each of those comes from is ensdf-sources.js,
   which Radionuclide Decay Chains (rdc.html) uses as well.

   One global: ENSDFPage, a read-only window on the state for the browser
   test. Everything else is inside the IIFE and reached through the
   data-on-* actions registered at the bottom.
   ========================================================================== */
/* global KVOT_ENSDF, KVOT_ENSDF_CORE, KVOT_ENSDF_CHART, KVOT_ENSDF_CHAIN, KVOT_ENSDF_INVENTORY, KVOT_ENSDF_SOURCES, registerActions, reportFailure, notifyUser, kvotEscapeHtml, kvotCsvCell, kvotFileTooLarge */
(function () {
  'use strict';

  const C = KVOT_ENSDF_CORE;
  const P = KVOT_ENSDF;
  const CH = KVOT_ENSDF_CHAIN;
  const SRC = KVOT_ENSDF_SOURCES;
  const IDB = SRC.IDB;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => kvotEscapeHtml(s);
  const STORAGE_KEY = 'kvot-ensdf-v1';
  const LEVEL_PAGE = 150;
  const LINE_PAGE = 80;

  /* ---------------------------------------------------------------------
     State
     --------------------------------------------------------------------- */
  const state = {
    releases: [],          // built-in, newest first
    stored: [],            // remembered opened databases: {key, label, names, size, opened}
    archive: null,         // the NNDC archive: {page, base, releases: [{id, label, files, parts?, missing?}]}
    source: null,          // {key, label, kind, summary, detail(a)}
    idx: null,
    details: new Map(),    // a -> detail, for the current source
    sel: null,             // {z, a, k}
    root: null,            // start of the chain on show
    chain: null,
    view: 'chart',
    tab: 'nuclide',
    colour: 'halflife',
    chainOpt: { minBranch: 0, life: 'iso', overlay: true, dir: 'down', style: 'grid' },   // dir: 'down' to the daughters, 'up' to the parents; style: how the chain is drawn, 'grid' (Z across, A down) or 'series' (circles as rdc.html draws them)
    inv: { from: 0, end: 0, unit: 'y', qty: 'Bq', sum: false, xLog: true, yLog: true, for: '', cursor: null },   // sum: an energy integrated over time
    inventories: {},       // chain start key ('up:' first for the parents) -> {member key: [value, unit]}
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
        inv: { from: state.inv.from, end: state.inv.end, unit: state.inv.unit, qty: state.inv.qty, sum: state.inv.sum, xLog: state.inv.xLog, yLog: state.inv.yLog, for: state.inv.for },
        inventories: Object.fromEntries(Object.entries(state.inventories).slice(-20)),
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
        if (s.chainOpt.dir === 'up' || s.chainOpt.dir === 'down') state.chainOpt.dir = s.chainOpt.dir;
        if (s.chainOpt.style === 'grid' || s.chainOpt.style === 'series') state.chainOpt.style = s.chainOpt.style;
      }
      if (['nuclide', 'levels', 'radiation', 'datasets', 'inventory', 'about'].includes(s.tab)) state.tab = s.tab;
      if (s.inv && typeof s.inv === 'object') {
        if (s.inv.end > 0) state.inv.end = s.inv.end;
        if (s.inv.from > 0) state.inv.from = s.inv.from;
        if (['s', 'min', 'h', 'd', 'y'].includes(s.inv.unit)) state.inv.unit = s.inv.unit;
        if (typeof s.inv.qty === 'string') state.inv.qty = s.inv.qty;
        if (typeof s.inv.sum === 'boolean') state.inv.sum = s.inv.sum;
        if (typeof s.inv.xLog === 'boolean') state.inv.xLog = s.inv.xLog;
        if (typeof s.inv.yLog === 'boolean') state.inv.yLog = s.inv.yLog;
        if (typeof s.inv.for === 'string') state.inv.for = s.inv.for;
      }
      if (s.inventories && typeof s.inventories === 'object') {
        for (const [k, v] of Object.entries(s.inventories)) {
          if (!/^(up:)?\d+,\d+,\d+$/.test(k) || !v || typeof v !== 'object') continue;
          const clean = {};
          for (const [mk, e] of Object.entries(v)) if (/^\d+,\d+,\d+$/.test(mk) && Array.isArray(e) && Number.isFinite(+e[0]) && ['Bq', 'mol', 'g'].includes(e[1])) clean[mk] = [+e[0], e[1]];
          state.inventories[k] = clean;
        }
      }
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
    if (key.startsWith('n:')) {
      /* Not to hand: say where to get it, and stay on the database in use. */
      renderDbMenu();
      showGet(key.slice(2));
      return;
    }
    state.loading = true;
    try {
      if (key.startsWith('b:')) {
        const rel = state.releases.find((r) => `b:${r.id}` === key);
        if (!rel) throw new Error('that release is not on this site');
        status(`Loading ${rel.label}…`);
        await useSource(await SRC.builtinSource(rel));
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
    /* Kept for next time, if the browser lets us. */
    const { src, key, stored } = await SRC.read(files, rec, (p) => status(`Reading ${names}: ${p.done} of ${p.total} files`));
    const r = src.summary.release;
    if (!rec) {
      if (stored) state.stored = stored;
      else {
        state.stored = state.stored.filter((x) => x.key !== key);
        state.transient = { key: src.key, label: r.label };
      }
    }
    await useSource(src);
    notifyUser(`${src.label}: ${r.nuclides.toLocaleString('en')} nuclides read in ${((performance.now() - t0) / 1000).toFixed(1)} s.`, { tone: 'success' });
  }

  function renderDbMenu() {
    const sel = $('nzDb');
    const here = [];
    const opened = [];
    const nndc = [];
    for (const r of state.releases) here.push(`<option value="b:${esc(r.id)}">${esc(r.label)} (on this site)</option>`);
    for (const s of state.stored.slice().sort((p, q) => q.opened - p.opened)) {
      opened.push(`<option value="s:${esc(s.key)}">${esc(s.label)} (opened ${esc(new Date(s.opened).toISOString().slice(0, 10))})</option>`);
    }
    if (state.transient) opened.push(`<option value="${esc(state.transient.key)}">${esc(state.transient.label)} (opened)</option>`);
    /* The rest of NNDC's archive, less what is already to hand. */
    const have = new Set(state.releases.concat(state.stored, state.transient ? [state.transient] : []).map((r) => r.label));
    for (const r of (state.archive && state.archive.releases) || []) {
      if (have.has(r.label)) continue;
      /* No longer than "(on this site)": a menu is as wide as its widest entry. */
      nndc.push(`<option value="n:${esc(r.id)}">${esc(r.label)}${r.missing ? ' (incomplete)' : r.files.length > 1 ? ` (${r.files.length} parts)` : ''}</option>`);
    }
    const group = (label, opts) => (opts.length ? `<optgroup label="${esc(label)}">${opts.join('')}</optgroup>` : '');
    sel.innerHTML = group('On this site', here) + group('Opened in this browser', opened) + group('At NNDC: download, then open', nndc);
    if (state.source) sel.value = state.source.key;
    $('nzForget').hidden = !(state.source && state.source.key.startsWith('s:'));
  }

  /*
    A release in NNDC's archive that is not to hand: which file or files to
    download -- before 2022 a release came in parts by mass number -- and
    the way to open them once they are here.
  */
  function showGet(id) {
    const a = state.archive;
    const rel = a && a.releases.find((r) => r.id === id);
    if (!rel) return;
    const many = rel.files.length > 1;
    const dash = (range) => range.replace('-', '–');
    const link = (f, i) => `<a href="${esc(a.base + f)}" target="_blank" rel="noopener noreferrer" download>${esc(f.split('/').pop())}</a>`
      + (rel.parts ? ` <span class="nz-dim">A = ${esc(dash(rel.parts[i]))}</span>` : '');
    const files = many ? `<ul class="nz-files">${rel.files.map((f, i) => `<li>${link(f, i)}</li>`).join('')}</ul>` : link(rel.files[0], 0);
    $('nzGetTitle').textContent = `${rel.label} from NNDC`;
    $('nzGetBody').innerHTML = `
      <p>This release is not on this site. Download it from NNDC’s archive and open it here: the page reads it in your browser, in a few seconds, and uploads nothing. It cannot fetch the release for you, as NNDC’s server does not let other sites read its files.</p>
      <ol>
        <li>Download ${many ? `its ${rel.files.length} parts, one for each range of mass numbers:${files}` : `${files}.`}</li>
        <li>Choose <b>Open the downloaded ${many ? 'files' : 'file'}…</b>${many ? ' and pick the parts together' : ''}, or drop ${many ? 'them' : 'it'} on the page.</li>
      </ol>
      ${rel.missing ? `<p class="nz-note-warn">NNDC lists no part of this release for A = ${esc(rel.missing.map(dash).join(', '))}, so the chart will have no nuclides there.</p>` : ''}
      <p class="nz-dim">It is then kept in this browser, in the menu, until you choose Forget.</p>`;
    $('nzGetOpen').textContent = `Open the downloaded ${many ? 'files' : 'file'}…`;
    const dlg = $('nzGet');
    if (typeof dlg.showModal === 'function') { if (!dlg.open) dlg.showModal(); } else dlg.setAttribute('open', '');
  }

  function closeGet() {
    const dlg = $('nzGet');
    if (!dlg.open) return;
    if (typeof dlg.close === 'function') dlg.close();
    else dlg.removeAttribute('open');
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

  /* The database, start and settings the chain on show was built for: the
     same again give the same chain, which is kept -- and with it the
     drawing's layout, so that a click on a box among a few hundred parents
     does not lay them all out again. */
  let chainFor = null;
  function computeChain() {
    if (!state.root || !state.idx) { state.chain = null; chainFor = null; chart.setChain(null); return; }
    const r = state.root;
    const life = lifeOption();
    const sig = [r.z, r.a, r.k, state.chainOpt.minBranch, life.id, state.chainOpt.dir].join('|');
    if (!state.chain || !chainFor || chainFor.idx !== state.idx || chainFor.sig !== sig) {
      state.chain = C.buildChain(state.idx, r.z, r.a, r.k, { minBranch: state.chainOpt.minBranch, minHalfLifeS: life.life, minIsomerS: life.iso, up: state.chainOpt.dir === 'up' });
      chainFor = { idx: state.idx, sig };
    }
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
    else if (state.tab === 'inventory') renderInventory();
    if (state.tab !== 'inventory') { invStop(); invBuckets(); }
  }

  function welcomeHtml() {
    const r = state.source ? state.source.summary.release : null;
    return `<div class="nz-welcome">
      <h2>Chart of nuclides</h2>
      <p>Every nuclide in the Evaluated Nuclear Structure Data File, placed by its neutron number <i>N</i> and proton number <i>Z</i> and coloured by half-life. Click one — or type its name above — for its states, decay modes, Q-values and evaluation, its level scheme and radiation, and the whole decay chain that follows from it, or every parent that leads to it.</p>
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
    html.push(`<dt>Parents</dt><dd>${parentsHtml(z, a, k)}</dd>`);
    if (st.mu) html.push(`<dt>Magnetic moment</dt><dd>${esc(st.mu.replace(/\s*\(.*\)$/, ''))} μ<sub>N</sub></dd>`);
    if (st.qm) html.push(`<dt>Quadrupole moment</dt><dd>${esc(st.qm.replace(/\s*\(.*\)$/, ''))} b</dd>`);
    html.push('</dl>');

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
  }

  /*
    The states that decay straight to this one, by mode, each with the share
    of its decays that lands here -- the file's own branches, as Daughters
    gives them on the parent. The longest-lived come first, mode by mode:
    they are the parents that matter in the long run (230Th before 226Fr).
    Their own parents are in the chain, set to run up.
  */
  function parentsHtml(z, a, k) {
    const list = C.parentsOf(state.idx, z, a, k).map((p) => ({ ...p, st: state.idx.get(p.z, p.a).s[p.k] }));
    if (!list.length) return '<span class="nz-dim">none: nothing in this database decays to it</span>';
    /* A stable one (136Ce, by a double electron capture never seen) goes last. */
    const life = (p) => (p.st.st ? -2 : p.st.ts > 0 ? p.st.ts : -1);
    list.sort((p, q) => (life(q) - life(p)) || (p.a - q.a) || (p.z - q.z) || (p.k - q.k));
    const byMode = new Map();
    for (const p of list) {
      if (!byMode.has(p.mode)) byMode.set(p.mode, []);
      byMode.get(p.mode).push(p);
    }
    const items = [...byMode].map(([m, ps]) => {
      const parts = ps.map((p) => {
        const pct = p.pct === null ? '?' : C.sharePct(p.pct * p.f, C.isLimit(p.op) ? p.op : '');
        const why = p.inferred ? (m === 'IT' ? ' Assumed: an excited state with no decay given decays by gamma emission.' : ' Inferred from the Q-values; not stated in ENSDF.') : '';
        const title = `${C.plainName(p.z, p.a, p.k, state.idx.get(p.z, p.a))}: ${p.st.st ? 'stable' : `T½ ${C.halfLifeText(p.st)}`}; ${p.pct === null ? 'a share not given' : pct} of its decays come here.${why}`;
        return `${nucLink(p.z, p.a, p.k)} <span class="nz-dim" title="${esc(C.asciiText(title))}">${supHtml(pct)}${p.inferred ? '*' : ''}${p.st.st ? ' (stable)' : ''}</span>`;
      });
      return `<li><span class="nz-mode">${supHtml(C.modeText(m))}</span> ← ${parts.join(', ')}</li>`;
    });
    return `<ul class="nz-modes">${items.join('')}</ul>`;
  }

  /* A member's share of its decays that reaches the start of a chain built
     going up: "100 %", or "81.5 % or more" where part of the way has no
     percentage. */
  const reachText = (n) => `${n.cumUnknown && !n.cum ? '?' : C.pctText(n.cum * 100)}${n.cumUnknown && n.cum ? ' or more' : ''}`;

  /* The colour a drawing stands on: the first background, going out from
     it, that is not transparent. A series takes it for its own, so that it
     has no edge in the chain view. */
  function backdrop(el) {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const c = getComputedStyle(e).backgroundColor;
      if (c && c !== 'transparent' && !/^rgba\(.*,\s*0\)$/.test(c)) return c;
    }
    return '';
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
    const up = state.chainOpt.dir === 'up';
    $('nzChainTabLabel').textContent = up ? 'Parents of' : 'Decay chain';
    $('nzChainStateLabel').textContent = up ? 'Parents of' : 'Start from';
    if (!state.root || !state.idx || !state.chain) {
      nameEl.textContent = '';
      if (state.view === 'chain') {
        $('nzChainSvg').replaceChildren();
        $('nzChainTable').innerHTML = '';
        $('nzChainNote').innerHTML = `<p class="nz-dim">Choose a nuclide on the chart to see its ${up ? 'parents' : 'decay chain'}.</p>`;
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
    const series = state.chainOpt.style === 'series';
    svg.setAttribute('aria-label', `${up ? 'Parents' : 'Decay chain'}: ${series ? 'alpha decay straight down, beta decay across' : 'atomic number across, mass number down'}`);
    /* A series runs to the view's edges, on the view's own colour (ensdf.css). */
    svg.parentElement.dataset.style = state.chainOpt.style;
    const size = CH.render(svg, ch, {
      style: state.chainOpt.style,
      bg: series ? backdrop(svg.parentElement) : undefined,
      selected: sel,
      onPick: (n) => { if (n.kind === 'state') select({ z: n.z, a: n.a, k: n.k }, { from: 'chain' }); },
      onHover: (n, ev) => {
        if (n) showTip(chainTip(n), ev.clientX, ev.clientY); else hideTip();
        invPointAt(n ? n.key : null);
      },
    });
    fitChain(size, ch);
    invBuckets();
    const notes = [];
    const rootName = supHtml(C.plainName(r.z, r.a, r.k, nuc));
    if (ch.up) {
      if (ch.nodes.length === 1) notes.push(`Nothing in this database decays to ${rootName}${state.chainOpt.minBranch ? ' by a branch as large as the setting keeps' : ''}.`);
      else notes.push(`Every nuclide and state whose decays come to ${rootName}, directly or through others. Only the branches that lead to it are drawn: the share on an arrow is of the decays of the nuclide it leaves, and the table gives the share of each member’s decays that reaches ${rootName}.`);
    } else if (nuc.s[r.k] && nuc.s[r.k].st) notes.push(`${rootName} is stable: there is no chain to follow.`);
    if (ch.truncated) notes.push(ch.up ? 'There are more parents than the drawing allows; the farthest have been cut off.' : 'The chain is larger than the drawing allows; it has been cut off.');
    if (ch.edges.some((e) => e.inferred)) notes.push('A dashed arrow marked * is a branch ENSDF does not state: an excited state assumed to decay by gamma emission, or a beta or electron-capture branch inferred from the Q-values.');
    if (ch.edges.some((e) => e.pct === null)) notes.push('A dashed arrow marked ? is a mode the evaluators list without a percentage.');
    /* What the half-life setting left out, heaviest first as the chain runs;
       going up, also those that nothing drawn decays through, and the
       nearest the start first: the lightest, and of one mass number those
       nearest it in Z. */
    const left = new Map();
    for (const e of ch.edges) for (const x of e.skipped) if (!left.has(x.key)) left.set(x.key, x);
    for (const x of ch.leftOut || []) if (!left.has(x.key)) left.set(x.key, x);
    if (left.size) {
      const order = (x) => x.key.split(',').map(Number);
      const near = (z) => Math.abs(z - r.z);
      const names = [...left.values()].sort((p, q) => {
        const [z1, a1, k1] = order(p), [z2, a2, k2] = order(q);
        return (ch.up ? (a1 - a2) || (near(z1) - near(z2)) : a2 - a1) || (z1 - z2) || (k2 - k1);
      }).map((x) => supHtml(x.name));
      const life = lifeOption();
      const how = ch.up
        ? 'The arrows go straight on through them to where they decay, each share the product of the branches on the way: an arrow marked “via” jumps over them, and what went through an isomer’s IT joins the arrow to the same nuclide. One that nothing drawn decays to is not drawn at all.'
        : 'The chain goes straight on to where they decay, each share the product of the branches on the way. An arrow marked “via” jumps over them; what went through an isomer’s IT joins the arrow to the same nuclide.';
      notes.push(`Left out, as ${life.life ? 'members' : 'isomers'} that live less than ${esc(life.span)}: ${names.slice(0, 30).join(', ')}${names.length > 30 ? `, and ${names.length - 30} more` : ''}. ${how}`);
    }
    $('nzChainNote').innerHTML = notes.length ? `<ul>${notes.map((n) => `<li>${n}</li>`).join('')}</ul>` : '';
    renderChainTable(ch);
  }

  /* The drawing shrinks to the width it has, down to 70 %; below that it
     scrolls -- unless the reader has zoomed it (zoomChain()), and then it
     keeps that scale while the same chain is drawn again: a box clicked,
     the theme switched, the window resized. Another start, the other way or
     the other layout is fitted to the width again. */
  let fittedFor = '';
  let chainScale = null;   // the scale zoomed to, or null while fitted to the width
  function fitChain(size, ch) {
    const svg = $('nzChainSvg');
    const box = document.querySelector('.nz-chain-scroll');
    /* The room is the drawing's own box: inside the scroll box's padding,
       or, for a series, out to its edges. */
    const draw = svg.parentElement;
    const room = draw.clientWidth - 2;
    if (!size || !(room > 0)) return;
    const sig = ch ? `${ch.up ? 'up' : 'down'}|${ch.root.key}|${state.chainOpt.style}` : '';
    const fresh = !!(size.root && ch && sig !== fittedFor);
    if (fresh) chainScale = null;
    const scale = chainScale || Math.max(0.7, Math.min(1.25, room / size.width));
    svg.setAttribute('width', Math.round(size.width * scale));
    svg.setAttribute('height', Math.round(size.height * scale));
    /* Only for a chain that is new -- another start, the other way or the
       other drawing -- not each time a box in it is clicked: a chain wider
       than the view opens scrolled to where it starts -- usually its top
       right, the heaviest member -- with as much of where that decays to
       beside it as fits; going up, with the parents it comes from, which
       stand on both sides of it. Going up, the start stands at the foot of
       the drawing, so a chain taller than the view opens scrolled down to it
       and its parents; going down, it opens at the top, where the start is. */
    if (!fresh) return;
    fittedFor = sig;
    const f = size.focus || size.root;
    if (size.width * scale > draw.clientWidth) {
      const right = (f.x + f.w) * scale + 24;
      const left = Math.max(0, (ch.up ? f.x : size.root.x) * scale - 24);
      draw.scrollLeft = Math.min(left, Math.max(0, right - draw.clientWidth));
    }
    if (ch.up) {
      const top = svg.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
      box.scrollTop = Math.max(0, Math.min(top + f.y * scale - 12, top + (f.y + f.h) * scale + 24 - box.clientHeight));
    } else box.scrollTop = 0;
  }

  /* Zooming the chain, as the chart zooms: by the buttons on the chain's
     bar, + and − and 0, or a pinch (the wheel with Ctrl, as browsers report
     a pinch) about the pointer. A step is a quarter; the drawing goes from
     a quarter of its size, or less where that is what shows all of it, to
     four times. */
  const CHAIN_ZOOM = 1.25;
  const CHAIN_MAX = 4;

  /* The scale at which the whole drawing is in view, at most the 125 % a
     small chain is fitted to. */
  function wholeChainScale() {
    const svg = $('nzChainSvg');
    const vb = (svg.getAttribute('viewBox') || '').split(' ').map(Number);
    if (vb.length !== 4) return 1;
    const box = document.querySelector('.nz-chain-scroll');
    const top = svg.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
    return Math.max(0.01, Math.min(1.25, (svg.parentElement.clientWidth - 2) / vb[2], (box.clientHeight - top - 2) / vb[3]));
  }

  function setChainScale(scale) {
    const svg = $('nzChainSvg');
    const vb = svg.getAttribute('viewBox').split(' ').map(Number);
    chainScale = scale;
    svg.setAttribute('width', Math.round(vb[2] * scale));
    svg.setAttribute('height', Math.round(vb[3] * scale));
  }

  /*
    Zoom the drawing by `factor`, keeping the point under (x, y) -- client
    coordinates; by default the middle of what is in view -- where it is.
    The drawing scrolls across in its own box and down with the view, so
    the two scroll positions are set apart.
  */
  function zoomChain(factor, x, y) {
    const svg = $('nzChainSvg');
    const vb = (svg.getAttribute('viewBox') || '').split(' ').map(Number);
    if (vb.length !== 4 || !svg.firstChild || state.view !== 'chain') return;
    const box = document.querySelector('.nz-chain-scroll');
    const draw = svg.parentElement;
    const r = svg.getBoundingClientRect(), b = box.getBoundingClientRect(), d = draw.getBoundingClientRect();
    const cur = r.width / vb[2];
    if (!(cur > 0)) return;
    if (x === undefined) {
      x = (Math.max(r.left, d.left) + Math.min(r.right, d.right)) / 2;
      y = (Math.max(r.top, b.top) + Math.min(r.bottom, b.bottom)) / 2;
    }
    const u = (x - r.left) / cur, v = (y - r.top) / cur;
    const top = r.top - b.top + box.scrollTop;
    setChainScale(Math.max(Math.min(0.25, wholeChainScale()), Math.min(CHAIN_MAX, (chainScale || cur) * factor)));
    const now = +svg.getAttribute('width') / vb[2];
    draw.scrollLeft = u * now - (x - d.left);
    box.scrollTop = top + v * now - (y - b.top);
  }

  /* The whole chain in view, from its top left. */
  function showWholeChain() {
    const svg = $('nzChainSvg');
    if (!svg.firstChild || state.view !== 'chain') return;
    setChainScale(wholeChainScale());
    svg.parentElement.scrollLeft = 0;
    document.querySelector('.nz-chain-scroll').scrollTop = 0;
  }

  /* How long a member must live to be drawn in a chain, and the smallest
     branch: the settings ensdf-core.js keeps for every page that draws one. */
  const LIFE_OPTIONS = C.LIFE_OPTIONS;

  function lifeOption() {
    return LIFE_OPTIONS.find((o) => o.id === state.chainOpt.life) || LIFE_OPTIONS.find((o) => o.id === C.DEFAULT_LIFE);
  }

  /* The chain settings sit beside the view tabs, and serve both views. */
  function renderChainControls() {
    const life = $('nzMinLife');
    if (!life.options.length) life.innerHTML = LIFE_OPTIONS.map((o) => `<option value="${o.id}">${esc(o.text)}</option>`).join('');
    state.chainOpt.life = lifeOption().id;
    life.value = state.chainOpt.life;
    const br = $('nzMinBranch');
    if (!br.options.length) br.innerHTML = C.BRANCH_OPTIONS.map((o) => `<option value="${o.value}">${esc(o.text)}</option>`).join('');
    if (![...br.options].some((o) => +o.value === state.chainOpt.minBranch)) state.chainOpt.minBranch = 0;
    br.value = [...br.options].find((o) => +o.value === state.chainOpt.minBranch).value;
    $('nzOverlay').checked = state.chainOpt.overlay;
    $('nzChainDir').value = state.chainOpt.dir;
    $('nzChainStyle').value = state.chainOpt.style;
  }

  /* How the chain is drawn, from the menu on the chain view's bar: on the
     grid, Z across and A down, or as a series, the way Radionuclide Decay
     Chains draws it. The chain itself does not change, nor the table; the
     panel follows (the Inventory tab's words for it). */
  function setChainStyle(style) {
    if (style !== 'grid' && style !== 'series') return;
    state.chainOpt.style = style;
    $('nzChainStyle').value = style;
    renderChainView();
    renderPanel();
    saveState();
  }

  /* Which way the chain runs, from the setting beside the view tabs: the
     drawing, the chart, the table and the inventory all follow. */
  function setChainDir(dir) {
    if (dir !== 'up' && dir !== 'down') return;
    state.chainOpt.dir = dir;
    $('nzChainDir').value = dir;
    computeChain();
    renderChainView();
    renderPanel();
    saveState();
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
    if (n !== state.chain.root) {
      line(state.chain.up ? `${reachText(n)} of its decays reach ${CH.nodeName(state.chain.root)}` : `${n.cumUnknown && !n.cum ? '?' : C.pctText(n.cum * 100)} of the decays pass through here`);
    }
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
    /* Going up, a member's row has only its branches toward the start, and
       the last column the share of its decays that gets there. */
    const start = nameHtml(ch.root.z, ch.root.a, ch.root.k, ch.root.nuc);
    const heads = ch.up ? [`Decays toward ${start} by`, `Reaches ${start} (% of its decays)`] : ['Decays by', 'Reached by (% of the first nuclide’s decays)'];
    const html = [`<table class="nz-table nz-chain-tab"><thead><tr><th class="text">Member</th><th class="text">T½</th><th class="text">${heads[0]}</th><th>${heads[1]}</th></tr></thead><tbody>`];
    for (const n of chainRows(ch)) {
      const who = n.kind === 'missing' ? `${nameHtml(n.z, n.a, 0, null)} <span class="nz-dim">not in ENSDF</span>` : nucLink(n.z, n.a, n.k);
      const life = n.kind === 'missing' ? '' : supHtml(C.halfLifeText(n.st, true));
      const outs = n.out.map((e) => `${supHtml(C.modeText(e.mode))} ${supHtml(CH.shareText(e))}${e.inferred ? '*' : ''} → ${e.to.kind === 'fission' ? 'fission' : e.to.kind === 'missing' ? nameHtml(e.to.z, e.to.a, 0, null) : nameHtml(e.to.z, e.to.a, e.to.k, e.to.nuc)}${viaSuffix(e) ? ` <span class="nz-dim" title="${esc(C.asciiText(CH.edgeAbout(e)))}">${supHtml(viaSuffix(e).trim())}</span>` : ''}`).join('<br>');
      const reached = n === ch.root ? (ch.up ? '—' : '100 %') : (n.cumUnknown && !n.cum ? '?' : C.pctText(n.cum * 100)) + (n.cumUnknown && n.cum ? ' or more' : '') + (n.bounded ? ' †' : '');
      const none = n.st && n.st.st && !ch.up ? '<span class="nz-dim">stable</span>' : '<span class="nz-dim">—</span>';
      html.push(`<tr class="${n === ch.root ? 'current' : ''}"><td class="text">${who}</td><td class="text">${life}</td><td class="text">${outs || none}</td><td>${supHtml(reached)}</td></tr>`);
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

  /* What the chain's files are called: decay-chain-238U, or parents-238U for one built going up. */
  const chainFileName = (ch, ext) => `${ch.up ? 'parents' : 'decay-chain'}-${C.name(ch.root.z, ch.root.a, ch.root.k, ch.root.nuc).key}.${ext}`;

  function chainCsv() {
    const ch = state.chain;
    if (!ch) return;
    const start = C.name(ch.root.z, ch.root.a, ch.root.k, ch.root.nuc).text;
    const heads = ch.up ? [`decay toward ${start}`, `reaches ${start} (% of its decays)`] : ['decay', 'reached (% of first nuclide decays)'];
    const rows = [['member', 'Z', 'A', 'state', 'level energy keV', 'half-life', 'half-life (s)', ...heads].map(cell).join(',')];
    for (const n of chainRows(ch)) {
      const outs = n.out.map((e) => `${e.mode} ${e.limit || (e.more ? '>=' : '')}${e.pct === null ? '?' : e.pct}% -> ${e.to.kind === 'fission' ? 'fission' : C.name(e.to.z, e.to.a, e.to.k, e.to.nuc).text}${C.asciiText(viaSuffix(e))}${e.inferred ? ' (inferred)' : ''}`).join('; ');
      const reached = n === ch.root ? (ch.up ? '' : 100) : (n.cumUnknown && !n.cum ? '' : +(n.cum * 100).toPrecision(8));
      rows.push([n.kind === 'missing' ? `${n.a}${C.ELEMENTS[n.z] ? C.ELEMENTS[n.z][0] : n.z}` : C.name(n.z, n.a, n.k, n.nuc).text, n.z, n.a, n.k, n.st ? n.st.e : '', n.st ? (n.st.st ? 'stable' : n.st.t) : '', n.st && n.st.ts !== undefined ? n.st.ts : '', outs, reached].map(cell).join(','));
    }
    download(chainFileName(ch, 'csv'), rows.join('\r\n'), 'text/csv');
  }

  function chainSvg() {
    const svg = $('nzChainSvg');
    if (!state.chain || !svg.firstChild) return;
    download(chainFileName(state.chain, 'svg'), CH.svgFile(svg), 'image/svg+xml');
  }

  function chainPng() {
    const svg = $('nzChainSvg');
    if (!state.chain || !svg.firstChild) return;
    /* The drawing's own size, however it is zoomed on screen (svgFile() writes the same). */
    const vb = svg.getAttribute('viewBox').split(' ').map(Number);
    const w = Math.ceil(vb[2]), h = Math.ceil(vb[3]);
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
      c.toBlob((b) => download(chainFileName(state.chain, 'png'), b), 'image/png');
    };
    img.onerror = () => { URL.revokeObjectURL(url); reportFailure('ensdf:chainPng', new Error('the drawing could not be turned into an image'), { userMessage: 'The PNG could not be made.' }); };
    img.src = url;
  }

  /* ---------------------------------------------------------------------
     The Inventory tab: the chain's inventory over time
     --------------------------------------------------------------------- */
  /*
    An initial amount for any drawn member of the chain -- an activity, an
    amount in moles or a mass -- and what becomes of the whole inventory:
    each member's activity, amount, mass or emitted energy over a span of
    time, worked by ensdf-core's decayAt() on the chain as it is drawn. The
    half-life setting counts: a member left out decays as fast as it is made,
    and what it gives off is counted with the member it is carried by
    (secular equilibrium). The chain drawing fills each box, as a bucket, to
    its share of the whole at the time under the cursor, and pointing at a
    line, a box or a row of the table picks out the same member in all three.
  */
  const TIME_UNITS = [['s', 1], ['min', 60], ['h', 3600], ['d', 86400], ['y', C.YEAR_S]];
  const TIME_WORDS = { s: 'seconds', min: 'minutes', h: 'hours', d: 'days', y: 'years' };
  /* e: which energy, for the quantities that are energies given off; sum:
     the label and unit of that energy integrated over time. */
  const QUANTITIES = [
    { id: 'Bq', label: 'Activity (Bq)', unit: 'Bq' },
    { id: 'mol', label: 'Amount (mol)', unit: 'mol' },
    { id: 'g', label: 'Mass (g)', unit: 'g' },
    { id: 'alpha', label: 'Alpha energy (MeV/s)', unit: 'MeV/s', e: 0, sum: ['Alpha energy, integrated (MeV)', 'MeV'] },
    { id: 'electron', label: 'Electron energy, beta included (MeV/s)', unit: 'MeV/s', e: 1, sum: ['Electron energy, beta included, integrated (MeV)', 'MeV'] },
    { id: 'photon', label: 'Photon energy (MeV/s)', unit: 'MeV/s', e: 2, sum: ['Photon energy, integrated (MeV)', 'MeV'] },
    { id: 'total', label: 'Total emitted energy (MeV/s)', unit: 'MeV/s', e: 3, sum: ['Total emitted energy, integrated (MeV)', 'MeV'] },
    { id: 'W', label: 'Total emitted power (W)', unit: 'W', e: 3, scale: 1.602176634e-13, sum: ['Total emitted energy, integrated (J)', 'J'] },
  ];
  /* A number for an input: plain, or with an exponent when it is long. */
  const inputNum = (v) => (!(v > 0) ? '' : v >= 1e5 || v < 1e-3 ? v.toExponential().replace(/\.?0+e/, 'e').replace('e+', 'e') : String(+v.toPrecision(10)));
  const INV_POINTS = 240;
  let invChart = null;
  let inv = null;          // the last calculation: for the chart, the buckets, the table and the files
  let invFrame = 0;        // requestAnimationFrame id while running through the times
  let invHotKey = null;    // the member picked out, by node key

  /* The chain on show, for its inventory: its start, with 'up:' before it for the parents. */
  const invRootKey = () => (state.root ? `${state.chainOpt.dir === 'up' ? 'up:' : ''}${state.root.z},${state.root.a},${state.root.k}` : '');
  const decaysAway = (nd) => !!(nd && nd.kind === 'state' && nd.st && !nd.st.st && nd.st.ts > 0);

  /* The initial inventory of the chain on show, member key -> [value, unit].
     Going down, its start holds 1 Bq until something is set; going up,
     nothing does until the reader gives one of the parents an amount. */
  function invEntries() {
    const k = invRootKey();
    if (!k) return {};
    if (!state.inventories[k]) {
      const r = state.chain && state.chain.root;
      state.inventories[k] = !r || state.chain.up ? {} : { [r.key]: decaysAway(r) ? [1, 'Bq'] : [1, 'mol'] };
    }
    return state.inventories[k];
  }

  const invFileName = (ext) => `inventory-${state.chain.up ? 'parents-' : ''}${C.name(state.chain.root.z, state.chain.root.a, state.chain.root.k, state.chain.root.nuc).key}-${inv.q.id}${inv.q.summed ? '-integrated' : ''}.${ext}`;

  /* The time the table and the boxes show when no cursor is set: the start,
     or for an integrated energy, which is nothing at the start, the end. */
  const invRestTime = () => state.inv.cursor ?? (inv && inv.q.summed ? inv.times.length - 1 : 0);

  /* Atoms in an amount given in Bq, mol or g. A mass takes the mass number for
     the molar mass, which is right to 0.1 % above A = 20. */
  function atomsOf(nd, value, unit) {
    const v = +value;
    if (!(v > 0) || !Number.isFinite(v)) return 0;
    if (unit === 'Bq') return decaysAway(nd) ? (v * nd.st.ts) / Math.LN2 : 0;
    if (unit === 'mol') return v * C.AVOGADRO;
    if (unit === 'g') return (v / nd.a) * C.AVOGADRO;
    return 0;
  }

  /* The span a new chain opens with, as rdc.html chooses it: a power of ten
     past ten half-lives of its start, in the largest unit it is one of. */
  function defaultSpan() {
    const ch = state.chain;
    let ts = ch && ch.root.st && ch.root.st.ts;
    /* A stable start of the parents: the time its own parents take. */
    if (!(ts > 0) && ch && ch.up) ts = Math.max(0, ...ch.root.in.map((e) => (e.from.st && e.from.st.ts > 0 ? e.from.st.ts : 0)));
    if (!(ts > 0)) return { end: 1, unit: 'y' };
    for (let i = TIME_UNITS.length - 1; i >= 0; i--) {
      const v = ts / TIME_UNITS[i][1];
      if (v >= 1 || i === 0) return { end: Math.pow(10, 1 + Math.ceil(Math.log10(v))), unit: TIME_UNITS[i][0] };
    }
    return { end: 1, unit: 'y' };
  }

  function computeInventory() {
    inv = null;
    const ch = state.chain;
    if (!ch || !state.idx) return;
    const rk = invRootKey();
    if (state.inv.for !== rk) {
      const d = defaultSpan();
      state.inv.end = d.end;
      state.inv.from = 0;
      state.inv.unit = d.unit;
      state.inv.for = rk;
      state.inv.cursor = null;
    }
    const sys = C.decaySystem(ch);
    const entries = invEntries();
    const n0 = new Float64Array(sys.members.length);
    let any = false;
    sys.members.forEach((nd, i) => {
      const e = entries[nd.key];
      if (!e || nd.kind !== 'state') return;
      n0[i] = atomsOf(nd, e[0], e[1]);
      if (n0[i] > 0) any = true;
    });
    const unit = TIME_UNITS.find((u) => u[0] === state.inv.unit) || TIME_UNITS[4];
    const end = (state.inv.end > 0 ? state.inv.end : 1) * unit[1];
    /* A log axis starts where it is told to, or six decades before the end. */
    let from = state.inv.from > 0 ? state.inv.from * unit[1] : end * 1e-6;
    if (!(from < end)) from = end * 1e-6;
    const times = [0];
    if (state.inv.xLog) for (let i = 0; i < INV_POINTS; i++) times.push(from * Math.pow(end / from, i / (INV_POINTS - 1)));
    else for (let i = 1; i <= INV_POINTS; i++) times.push((end * i) / INV_POINTS);
    const q0 = QUANTITIES.find((x) => x.id === state.inv.qty) || QUANTITIES[0];
    /* An energy integrated over time: each member's decays since t = 0 times what it gives off per decay. */
    const q = q0.sum && state.inv.sum ? { ...q0, label: q0.sum[0], unit: q0.sum[1], summed: true } : q0;
    const res = any ? C.decayAt(sys, n0, times, { decays: !!q.summed }) : null;
    const em = sys.members.map((nd) => (nd.kind === 'state' && nd.st && !nd.st.st ? C.chainEmission(state.idx, nd) : null));
    const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    /* Every drawn member keeps its colour whatever is shown: its place in the chain. */
    const series = [];
    let slot = 0;
    sys.members.forEach((nd, i) => {
      if (nd.kind === 'fission') return;
      const values = new Float64Array(times.length);
      let peak = 0;
      const e = em[i];
      const per = e ? (q.e === 3 ? e.v[0] + e.v[1] + e.v[2] : e.v[q.e]) : 0;
      if (res) {
        for (let t = 0; t < times.length; t++) {
          const A = res.A[t][i], N = res.N[t][i];
          let v;
          if (q.id === 'Bq') v = A;
          else if (q.id === 'mol') v = N / C.AVOGADRO;
          else if (q.id === 'g') v = (N / C.AVOGADRO) * nd.a;
          else v = (q.summed ? res.D[t][i] : A) * per * (q.scale || 1);
          values[t] = v;
          if (v > peak) peak = v;
        }
      }
      const style = KVOT_ENSDF_INVENTORY.lineStyle(slot++, theme);
      series.push({ i, nd, key: nd.key, label: CH.nodeName(nd), values, peak, color: style.color, dash: style.dash });
    });
    const shown = series.filter((x) => x.peak > 0);
    const total = new Float64Array(times.length);
    for (const x of shown) for (let t = 0; t < times.length; t++) total[t] += x.values[t];
    inv = { sys, times, res, q, unit, series, shown, total, em, any, root: rk };
  }

  function renderInventory() {
    const pane = $('nzPaneInventory');
    invStop();
    if (!state.chain || !state.idx || !state.root) {
      pane.innerHTML = '<p class="nz-dim">Choose a radionuclide on the chart: its decay chain can be given an initial inventory here, and followed over time.</p>';
      invBuckets();
      return;
    }
    const ch = state.chain;
    const r = ch.root;
    if (!ch.up && r.st && r.st.st) {
      pane.innerHTML = `<p class="nz-dim">${nameHtml(r.z, r.a, r.k, r.nuc)} is stable: it has no decay chain to follow.</p>`;
      invBuckets();
      return;
    }
    if (ch.up && ch.nodes.length === 1) {
      pane.innerHTML = `<p class="nz-dim">Nothing in this database decays to ${nameHtml(r.z, r.a, r.k, r.nuc)}: it has no parents to follow.</p>`;
      invBuckets();
      return;
    }
    computeInventory();
    const unitOpts = TIME_UNITS.map(([u]) => `<option value="${u}"${u === state.inv.unit ? ' selected' : ''}>${TIME_WORDS[u]}</option>`).join('');
    const qOpts = QUANTITIES.map((x) => `<option value="${x.id}"${x.id === inv.q.id ? ' selected' : ''}>${esc(x.label)}</option>`).join('');
    const axisBtn = (axis, on) => `<button type="button" class="nz-btn secondary small" data-on-click="nz:invAxis" data-axis="${axis}" aria-pressed="${on}" title="Logarithmic or linear ${axis === 'x' ? 'time' : 'value'} axis">${axis === 'x' ? 'time' : 'value'}: ${on ? 'log' : 'linear'}</button>`;
    const rows = chainRows(ch).filter((n) => n.kind === 'state').map((n) => {
      const e = invEntries()[n.key];
      const units = decaysAway(n) ? ['Bq', 'mol', 'g'] : ['mol', 'g'];
      const u = e && units.includes(e[1]) ? e[1] : units[0];
      const opts = units.map((x) => `<option value="${x}"${x === u ? ' selected' : ''}>${x}</option>`).join('');
      const plain = C.asciiText(CH.nodeName(n));
      return `<tr data-key="${n.key}" class="${n === ch.root ? 'current' : ''}">
        <td class="nz-inv-swcell"><span class="nz-inv-sw" data-key="${n.key}"></span></td>
        <td class="text">${nucLink(n.z, n.a, n.k)}</td>
        <td class="text nz-dim">${supHtml(n.st.st ? 'stable' : C.halfLifeShort(n.st) || '?')}</td>
        <td class="text nz-inv-in"><input type="number" min="0" step="any" inputmode="decimal" value="${e && e[0] ? esc(inputNum(e[0])) : ''}" placeholder="0" data-on-input="nz:invValue" data-key="${n.key}" aria-label="Initial amount of ${esc(plain)}"><select data-on-change="nz:invValueUnit" data-key="${n.key}" aria-label="Unit of the initial amount of ${esc(plain)}">${opts}</select></td>
        <td class="nz-inv-now" data-key="${n.key}"></td>
      </tr>`;
    }).join('');
    const rName = nameHtml(r.z, r.a, r.k, r.nuc);
    /* What a member is drawn as: a box on the grid, a circle in the series. */
    const shape = state.chainOpt.style === 'series' ? ['circle', 'circles'] : ['box', 'boxes'];
    pane.innerHTML = `
      <div class="nz-pane-head"><h3>${ch.up ? `Inventory of the parents of ${rName}` : `Inventory of the ${rName} chain`}</h3></div>
      <p class="nz-dim nz-inv-lead">${ch.up ? `Give any of the parents an initial amount below, and follow how ${rName} and every member between grow in from it.` : 'Give any member an initial amount below, and follow each one over time.'} Point at a line, a ${shape[0]} in the chain or a row to find a member in all three; the ${shape[1]} fill to their share at the time under the cursor.</p>
      <div class="nz-inv-bar">
        <label class="nz-field">${state.inv.xLog ? 'From' : 'Up to'}${state.inv.xLog ? ` <input type="text" inputmode="decimal" id="nzInvFrom" value="${esc(inputNum(state.inv.from > 0 ? state.inv.from : state.inv.end * 1e-6))}" data-on-change="nz:invFrom" aria-label="Start of the time span"> to` : ''} <input type="text" inputmode="decimal" id="nzInvEnd" value="${esc(inputNum(state.inv.end))}" data-on-change="nz:invEnd" aria-label="End of the time span"> <select id="nzInvUnit" data-on-change="nz:invUnit" aria-label="Unit of the time span">${unitOpts}</select></label>
        <label class="nz-field">Show <select id="nzInvQty" data-on-change="nz:invQty">${qOpts}</select></label>
        ${inv.q.sum ? `<label class="nz-check" title="The energy given off from the start up to each time, instead of the rate at that time"><input type="checkbox" id="nzInvSum" data-on-change="nz:invSum"${inv.q.summed ? ' checked' : ''}> integrated over time</label>` : ''}
      </div>
      <div class="nz-inv-tools">
        <button type="button" class="nz-btn small" id="nzInvPlay" data-on-click="nz:invPlay" title="Move the cursor from the start to the end, filling the ${shape[1]} as it goes">Run through</button>
        ${axisBtn('x', state.inv.xLog)} ${axisBtn('y', state.inv.yLog)}
        <span class="nz-dialog-gap"></span>
        <button type="button" class="nz-btn secondary small" data-on-click="nz:invCsv" title="The values drawn, as a table">CSV</button>
        <button type="button" class="nz-btn secondary small" data-on-click="nz:invSvg">SVG</button>
        <button type="button" class="nz-btn secondary small" data-on-click="nz:invPng">PNG</button>
      </div>
      <div class="nz-inv-chart" id="nzInvChart"></div>
      <p class="nz-inv-at" id="nzInvAt"></p>
      <div class="nz-table-wrap"><table class="nz-table nz-inv-table">
        <colgroup><col class="nz-inv-c-sw"><col><col class="nz-inv-c-life"><col class="nz-inv-c-in"><col class="nz-inv-c-now"></colgroup>
        <thead><tr><th></th><th class="text">Member</th><th class="text">T½</th><th class="text">Initial amount</th><th>${esc(inv.q.unit)}</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <p><button type="button" class="nz-btn secondary small" data-on-click="nz:invClear">Clear every amount</button></p>
      <div id="nzInvNotes"></div>`;
    for (const sw of pane.querySelectorAll('.nz-inv-sw')) {
      const x = inv.series.find((y) => y.key === sw.dataset.key);
      if (x && x.peak > 0) { sw.style.borderTopColor = x.color; sw.style.borderTopStyle = x.dash ? 'dashed' : 'solid'; } else sw.classList.add('none');
    }
    for (const tr of pane.querySelectorAll('.nz-inv-table tbody tr')) {
      tr.addEventListener('pointerenter', () => invPointAt(tr.dataset.key));
      tr.addEventListener('pointerleave', () => invPointAt(null));
    }
    $('nzInvNotes').innerHTML = invNotes();
    invChart = KVOT_ENSDF_INVENTORY.createInventoryChart($('nzInvChart'), { onHover: invHover, onPick: invPick });
    drawInvChart();
  }

  function drawInvChart() {
    if (!invChart || !inv) return;
    if (!inv.any) {
      invChart.render(null, state.chain && state.chain.up ? 'No initial inventory: give one of the parents an amount below.' : 'No initial inventory: give a member an amount below.');
    } else if (!inv.shown.length) {
      invChart.render(null, `Nothing in this chain has ${inv.q.id === 'Bq' ? 'an activity' : 'emitted energy'} to draw.`);
    } else {
      invChart.render({
        times: inv.times, tScale: { factor: inv.unit[1], unit: inv.unit[0] },
        series: inv.shown.map((x) => ({ label: x.label, values: x.values, color: x.color, dash: x.dash })),
        total: inv.shown.length > 1 ? inv.total : null, yTitle: inv.q.label, xLog: state.inv.xLog, yLog: state.inv.yLog,
      });
      if (state.inv.cursor !== null && state.inv.cursor < inv.times.length) invChart.setCursor(state.inv.cursor);
    }
    invShowTime(invRestTime());
  }

  /* The notes under the table: how the energies are got, what is carried, what is not known. */
  function invNotes() {
    const notes = [];
    const energy = inv.q.e !== undefined;
    const carried = inv.sys.members.filter((nd) => nd.carried && nd.carried.length && nd.st && !nd.st.st);
    if (carried.length) {
      const list = carried.slice(0, 8).map((nd) => `${nameHtml(nd.z, nd.a, nd.k, nd.nuc)} (${nd.carried.slice(0, 5).map((c) => supHtml(C.plainName(c.z, c.a, c.k, state.idx.get(c.z, c.a)))).join(', ')}${nd.carried.length > 5 ? ', …' : ''})`);
      notes.push(`Members left out by the half-life setting decay as fast as they are made, in secular equilibrium with the member that feeds them: what they give off is counted with it — ${list.join('; ')}${carried.length > 8 ? '; …' : ''}. Their own activity is not drawn.`);
    }
    if (inv.q.summed) notes.push('Integrated over time, each value is the energy given off from the start (t = 0) up to that time: each member’s decays are counted as the chain decays, by the same calculation, so the sum is exact and does not depend on the points drawn.');
    if (energy) {
      notes.push('Energy per decay is worked out from the ENSDF decay data sets: alpha particles with the recoil of the nucleus, the mean beta and positron energies, gamma rays, annihilation radiation, and the de-excitation energy the gamma rays do not carry (conversion electrons, with the X-rays and Auger electrons that follow them). X-rays and Auger electrons after electron capture, which ENSDF does not list, are estimated from the K-shell binding energy. Neutrinos and fission fragments are not counted.');
      const unknown = inv.sys.members.filter((nd, i) => decaysAway(nd) && inv.em[i] && !inv.em[i].known);
      const est = inv.sys.members.filter((nd, i) => decaysAway(nd) && inv.em[i] && inv.em[i].estimated);
      if (unknown.length) notes.push(`Not all of what these give off is known — the database has no decay data set for some of their decays, or no percentage: ${unknown.map((nd) => nameHtml(nd.z, nd.a, nd.k, nd.nuc)).join(', ')}.`);
      if (est.length) notes.push(`Estimated in part (from a Q-value, or from gamma intensities the data set gives only relative to each other): ${est.map((nd) => nameHtml(nd.z, nd.a, nd.k, nd.nuc)).join(', ')}.`);
    }
    if (inv.q.id === 'g' || Object.values(invEntries()).some((e) => e[1] === 'g')) notes.push('A mass is converted with the mass number as the molar mass (g/mol), which is right to within 0.1 % above A = 20.');
    const noLife = inv.sys.members.filter((nd) => nd.kind === 'state' && nd.st && !nd.st.st && !(nd.st.ts > 0));
    if (noLife.length) notes.push(`With no half-life in the database these are held, not decayed: ${noLife.map((nd) => nameHtml(nd.z, nd.a, nd.k, nd.nuc)).join(', ')}.`);
    notes.push('Worked by the Chebyshev rational approximation of the matrix exponential (CRAM, order 16), exact for any span; values more than twelve decades below the largest are not drawn.');
    return `<ul class="nz-note">${notes.map((n) => `<li>${n}</li>`).join('')}</ul>`;
  }

  /* Shares of the whole at time index t, by member key. */
  function invLevels(t) {
    if (!inv || !inv.any || !inv.shown.length) return null;
    const tot = inv.total[t];
    const out = new Map();
    for (const x of inv.shown) out.set(x.key, tot > 0 ? x.values[t] / tot : 0);
    return out;
  }

  /* The boxes of the chain drawing as buckets, while the Inventory tab is open. */
  function invBuckets(t) {
    const svg = $('nzChainSvg');
    if (!svg || !svg.firstChild) return;
    const on = state.tab === 'inventory' && inv && inv.root === invRootKey();
    CH.setLevels(svg, on ? invLevels(t ?? invRestTime()) : null);
    CH.setHot(svg, on ? invHotKey : null);
  }

  /* The time shown: the table's last column and the boxes. */
  function invShowTime(t) {
    if (!inv) return;
    const pane = $('nzPaneInventory');
    const at = $('nzInvAt');
    const when = `${supHtml(KVOT_ENSDF_INVENTORY.numText(inv.times[t] / inv.unit[1]))} ${esc(TIME_WORDS[inv.unit[0]])}`;
    if (at) at.innerHTML = !t ? 'At the start:' : inv.q.summed ? `In the first ${when}:` : `At ${when}:`;
    for (const td of pane.querySelectorAll('.nz-inv-now')) {
      const x = inv.series.find((y) => y.key === td.dataset.key);
      td.innerHTML = x && inv.any ? supHtml(KVOT_ENSDF_INVENTORY.numText(x.values[t])) : '';
    }
    invBuckets(t);
  }

  /* A member picked out from anywhere: its line, its box and its row. */
  function invPointAt(key) {
    if (state.tab !== 'inventory' || !inv) return;
    invHotKey = key;
    if (invChart) invChart.setHot(key ? inv.shown.findIndex((x) => x.key === key) : null);
    const svg = $('nzChainSvg');
    if (svg && svg.firstChild) CH.setHot(svg, key);
    for (const tr of $('nzPaneInventory').querySelectorAll('.nz-inv-table tbody tr')) tr.classList.toggle('hot', tr.dataset.key === key);
  }

  function invHover(k, t) {
    const key = k === null || k === undefined ? null : inv.shown[k].key;
    invHotKey = key;
    const svg = $('nzChainSvg');
    if (svg && svg.firstChild) CH.setHot(svg, key);
    for (const tr of $('nzPaneInventory').querySelectorAll('.nz-inv-table tbody tr')) tr.classList.toggle('hot', tr.dataset.key === key);
    invShowTime(t ?? invRestTime());
  }

  function invPick(t) {
    state.inv.cursor = t;
    invShowTime(t);
  }

  /* Run the cursor from the first time to the last, in about seven seconds. */
  function invPlayToggle() {
    if (invFrame) { invStop(); return; }
    if (!inv || !inv.any || !invChart) return;
    const btn = $('nzInvPlay');
    if (btn) btn.textContent = 'Stop';
    const n = inv.times.length;
    let start = null;
    const from = state.inv.cursor !== null && state.inv.cursor < n - 1 ? state.inv.cursor : 0;
    const step = (now) => {
      if (start === null) start = now - (from / (n - 1)) * 7000;
      const t = Math.min(n - 1, Math.round(((now - start) / 7000) * (n - 1)));
      state.inv.cursor = t;
      invChart.setCursor(t);
      invShowTime(t);
      if (t >= n - 1) { invStop(); return; }
      invFrame = requestAnimationFrame(step);
    };
    invFrame = requestAnimationFrame(step);
  }

  function invStop() {
    if (invFrame) cancelAnimationFrame(invFrame);
    invFrame = 0;
    const btn = $('nzInvPlay');
    if (btn) btn.textContent = 'Run through';
  }

  /* A recalculation shortly after the last keystroke, keeping the pane as it is. */
  let invTimer = 0;
  function invRecalc() {
    clearTimeout(invTimer);
    invTimer = setTimeout(() => {
      const focus = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.key : null;
      renderInventory();
      if (focus) {
        const input = $('nzPaneInventory').querySelector(`input[data-key="${focus}"]`);
        if (input) { input.focus(); const v = input.value; input.value = ''; input.value = v; }
      }
      saveState();
    }, 250);
  }

  function invCsv() {
    if (!inv || !inv.any) return;
    const head = [`time (${inv.unit[0]})`].concat(inv.shown.map((x) => `${C.asciiText(x.label)} ${inv.q.label}`), inv.shown.length > 1 ? [`total ${inv.q.label}`] : []);
    const rows = [
      ['ENSDF decay chain inventory'].map(cell).join(','),
      ['release', state.source ? state.source.label : ''].map(cell).join(','),
      ['chain start', C.name(state.chain.root.z, state.chain.root.a, state.chain.root.k, state.chain.root.nuc).text].map(cell).join(','),
      ['chain runs', state.chain.up ? 'up, to the parents' : 'down, to the daughters'].map(cell).join(','),
      ['isomer and half-life setting', lifeOption().text].map(cell).join(','),
      ['initial amounts', ...Object.entries(invEntries()).filter((e) => +e[1][0] > 0).map(([k, e]) => { const nd = state.chain.nodes.find((n) => n.key === k); return nd ? `${C.asciiText(CH.nodeName(nd))} ${e[0]} ${e[1]}` : ''; })].map(cell).join(','),
      '',
      head.map(cell).join(','),
    ];
    inv.times.forEach((t, i) => {
      rows.push([+(t / inv.unit[1]).toPrecision(8)].concat(inv.shown.map((x) => +x.values[i].toPrecision(8)), inv.shown.length > 1 ? [+inv.total[i].toPrecision(8)] : []).map(cell).join(','));
    });
    download(invFileName('csv'), '﻿' + rows.join('\r\n'), 'text/csv');
  }

  function invSvg() {
    if (!invChart || !inv || !inv.any) return;
    download(invFileName('svg'), invChart.svgFile(), 'image/svg+xml');
  }

  function invPng() {
    if (!invChart || !inv || !inv.any) return;
    const svg = invChart.svg;
    const w = +svg.getAttribute('width'), h = +svg.getAttribute('height');
    const img = new Image();
    const url = URL.createObjectURL(new Blob([invChart.svgFile()], { type: 'image/svg+xml' }));
    img.onload = () => {
      const c = document.createElement('canvas');
      c.width = w * 2; c.height = h * 2;
      const g = c.getContext('2d');
      g.scale(2, 2);
      g.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      c.toBlob((b) => download(invFileName('png'), b), 'image/png');
    };
    img.onerror = () => { URL.revokeObjectURL(url); reportFailure('ensdf:invPng', new Error('the chart could not be turned into an image'), { userMessage: 'The PNG could not be made.' }); };
    img.src = url;
  }

  /* ---------------------------------------------------------------------
     Opening files
     --------------------------------------------------------------------- */
  async function openChosen(files) {
    files = [...files].filter((f) => f && f.size);
    if (!files.length) return;
    closeGet();
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
      state.panelWidth = Math.round(Math.max(330, Math.min(max, start.w - (ev.clientX - start.x))));
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
      state.panelWidth = Math.round(Math.max(330, ($('nzPanel').getBoundingClientRect().width) + d));
      applyPanelWidth();
      saveState();
    });
  }

  /* ---------------------------------------------------------------------
     The full window
     --------------------------------------------------------------------- */
  /* The page without the site's header and footer (ensdf.css :root.nz-full),
     by the button at the right end of the toolbar; kept for the next visit,
     which the page's head puts in it before the first paint. The chart and
     the chain fit themselves to their new room: they watch their boxes. */
  const FULL_KEY = 'kvot.ensdf.full';

  function setFull(on) {
    document.documentElement.classList.toggle('nz-full', !!on);
    try { localStorage.setItem(FULL_KEY, on ? '1' : '0'); } catch (e) { /* storage unavailable: for this visit only */ }
    fullState();
  }

  function fullState() {
    const on = document.documentElement.classList.contains('nz-full');
    const b = $('nzFull');
    b.setAttribute('aria-pressed', String(on));
    b.title = on ? 'Show the site’s header and footer again' : 'Full window: the chart without the site’s header and footer';
  }

  /* ---------------------------------------------------------------------
     Start
     --------------------------------------------------------------------- */
  let chart = null;

  async function start() {
    const saved = loadState();
    applyPanelWidth();
    fullState();
    $('nzColour').value = state.colour;
    renderChainControls();
    chart = KVOT_ENSDF_CHART.createChart($('nzChart'), {
      onSelect: (s) => select(s, { from: 'chart', centre: s.via !== 'chart' }),
      onHover: (n, x, y) => { if (n) showTip(chartTip(n), x, y); else hideTip(); },
    });
    chart.setMode(state.colour);
    document.documentElement.addEventListener('kvot-theme-change', () => { renderLegend(); if (state.view === 'chain') renderChainView(); if (state.tab === 'inventory') renderInventory(); });
    /* The inventory chart is drawn to the width of its pane, in the next
       frame: its height follows its width, and a pane that changed size
       inside the observer's own call would set off a resize loop. */
    let invWidth = 0, invFit = 0;
    new ResizeObserver(() => {
      if (invFit) return;
      invFit = requestAnimationFrame(() => {
        invFit = 0;
        const w = $('nzPaneInventory').clientWidth;
        if (state.tab !== 'inventory' || !w || Math.abs(w - invWidth) < 8) return;
        invWidth = w;
        drawInvChart();
      });
    }).observe($('nzPaneInventory'));
    setupResize();
    setupDrop();
    /* The panel's row of tabs stands as tall as the main area's, which holds
       the chain settings too and puts them above its tabs where they do not
       fit beside them: so the lines under the two rows meet (ensdf.css). */
    const viewRow = document.querySelector('.nz-views');
    /* Set in the next frame: set inside the observer's own call, it would
       change the size of the Inventory pane, which is observed as well, and
       set off a resize loop. */
    let tabRow = 0;
    new ResizeObserver(() => {
      if (tabRow) return;
      tabRow = requestAnimationFrame(() => { tabRow = 0; $('nzPanel').style.setProperty('--nz-tabrow', `${viewRow.getBoundingClientRect().height}px`); });
    }).observe(viewRow);
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
    /* + and − zoom the chain and 0 shows all of it, as on the chart, from
       anywhere in the chain view or from nowhere in particular -- not from a
       field, and not with Ctrl or Cmd, which zoom the page. */
    document.addEventListener('keydown', (ev) => {
      if (state.view !== 'chain' || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      const t = ev.target;
      if (t !== document.body && !(t.closest && t.closest('.nz-chainview'))) return;
      if (t.matches && t.matches('input, select, textarea, [contenteditable]')) return;
      const k = ev.key;
      if (k === '+' || k === '=') zoomChain(CHAIN_ZOOM);
      else if (k === '-' || k === '_') zoomChain(1 / CHAIN_ZOOM);
      else if (k === '0') showWholeChain();
      else return;
      ev.preventDefault();
    });
    /* A pinch zooms the drawing about the pointer; the wheel alone scrolls. */
    $('nzChainSvg').parentElement.addEventListener('wheel', (ev) => {
      if (!ev.ctrlKey) return;
      ev.preventDefault();
      const dy = ev.deltaMode === 1 ? ev.deltaY * 16 : ev.deltaY;
      zoomChain(Math.exp(-dy * 0.01), ev.clientX, ev.clientY);
    }, { passive: false });
    setView(state.view);
    renderPanel();

    /* The NNDC archive only adds to the menu, and may come after the rest;
       the menu is drawn again with it once the rest of it is known. */
    let menuReady = false;
    SRC.archive().then((archive) => { state.archive = archive; if (menuReady) renderDbMenu(); }, () => {});
    try {
      state.releases = await SRC.releases();
    } catch (e) {
      state.releases = [];
    }
    try { state.stored = await IDB.list(); } catch (e) { state.stored = []; }
    menuReady = true;
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
    'nz:getOpen': () => { closeGet(); $('nzFile').click(); },
    'nz:getClose': () => closeGet(),
    'nz:fileChosen': (ev, el) => { const f = [...el.files]; el.value = ''; openChosen(f); },
    'nz:forget': async () => {
      if (!state.source || !state.source.key.startsWith('s:')) return;
      const key = state.source.key.slice(2);
      try { await IDB.remove(key); state.stored = await IDB.list(); } catch (e) { reportFailure('ensdf:forget', e); }
      if (state.releases.length) await switchDb(`b:${state.releases[0].id}`);
      renderDbMenu();
      notifyUser('The opened database is no longer kept in this browser.');
    },
    'nz:full': () => setFull(!document.documentElement.classList.contains('nz-full')),
    'nz:view': (ev, el) => setView(el.dataset.view),
    'nz:tab': (ev, el) => { state.tab = el.dataset.tab; renderPanel(); saveState(); },
    'nz:invValue': (ev, el) => {
      const e = invEntries();
      const v = el.value.trim();
      const unit = el.parentNode.querySelector('select').value;
      if (v === '' || !(+v > 0)) delete e[el.dataset.key]; else e[el.dataset.key] = [+v, unit];
      invRecalc();
    },
    'nz:invValueUnit': (ev, el) => {
      const e = invEntries();
      const input = el.parentNode.querySelector('input');
      if (+input.value > 0) e[el.dataset.key] = [+input.value, el.value];
      invRecalc();
    },
    'nz:invEnd': (ev, el) => { const v = +el.value.replace(',', '.'); if (v > 0) { state.inv.end = v; state.inv.cursor = null; } renderInventory(); saveState(); },
    'nz:invFrom': (ev, el) => { const v = +el.value.replace(',', '.'); if (v > 0) { state.inv.from = v; state.inv.cursor = null; } renderInventory(); saveState(); },
    'nz:invUnit': (ev, el) => {
      /* The same span in the new unit. */
      const f0 = (TIME_UNITS.find((u) => u[0] === state.inv.unit) || TIME_UNITS[4])[1], f1 = (TIME_UNITS.find((u) => u[0] === el.value) || TIME_UNITS[4])[1];
      state.inv.end = +(state.inv.end * f0 / f1).toPrecision(6);
      if (state.inv.from > 0) state.inv.from = +(state.inv.from * f0 / f1).toPrecision(6);
      state.inv.unit = el.value;
      state.inv.cursor = null;
      renderInventory();
      saveState();
    },
    'nz:invQty': (ev, el) => { state.inv.qty = el.value; renderInventory(); saveState(); },
    'nz:invSum': (ev, el) => { state.inv.sum = el.checked; renderInventory(); saveState(); },
    'nz:invAxis': (ev, el) => {
      if (el.dataset.axis === 'x') { state.inv.xLog = !state.inv.xLog; state.inv.cursor = null; } else state.inv.yLog = !state.inv.yLog;
      renderInventory();
      saveState();
    },
    'nz:invPlay': () => invPlayToggle(),
    'nz:invClear': () => { state.inventories[invRootKey()] = {}; state.inv.cursor = null; renderInventory(); saveState(); },
    'nz:invCsv': () => invCsv(),
    'nz:invSvg': () => invSvg(),
    'nz:invPng': () => invPng(),
    'nz:go': (ev, el) => { ev.preventDefault(); select({ z: +el.dataset.z, a: +el.dataset.a, k: +el.dataset.k }, { from: state.view === 'chain' ? 'chain' : 'panel' }); },
    'nz:state': (ev, el) => { ev.preventDefault(); if (state.sel) select({ z: state.sel.z, a: state.sel.a, k: +el.dataset.k }, { from: 'panel' }); },
    'nz:chainState': (ev, el) => { if (state.root) select({ z: state.root.z, a: state.root.a, k: +el.value }, { from: 'panel' }); },
    'nz:minBranch': (ev, el) => { state.chainOpt.minBranch = +el.value; computeChain(); renderChainView(); renderPanel(); saveState(); },
    'nz:minLife': (ev, el) => { state.chainOpt.life = el.value; computeChain(); renderChainView(); renderPanel(); saveState(); },
    'nz:overlay': (ev, el) => { state.chainOpt.overlay = el.checked; computeChain(); saveState(); },
    'nz:chainDir': (ev, el) => setChainDir(el.value),
    'nz:chainStyle': (ev, el) => setChainStyle(el.value),
    'nz:chainZoomIn': () => zoomChain(CHAIN_ZOOM),
    'nz:chainZoomOut': () => zoomChain(1 / CHAIN_ZOOM),
    'nz:chainWhole': () => showWholeChain(),
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
