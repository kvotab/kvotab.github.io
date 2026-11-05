/* ==========================================================================
   CANISTER_INVENTORY.HTML: THE PAGE

   Files in (the inventory read off the page by inventory-worker.js, PSAR's
   workbook by SheetJS and its report by inventory-psar.js), the
   settings in the bar (time, unit, half-lives, which canisters), and six
   views. Every view is drawn from the same few things, kept until a setting
   changes them: the inventory at the time chosen (inventory-model.js), and
   PSAR's values brought to that time.

   Text from a file -- canister and element names, reactors, fuel types,
   sheet names -- is the visitor's own and goes into the page as text only,
   never as markup; into a chart, escaped.
   ========================================================================== */
/* global KVOT_INV_JSON, KVOT_INV_MODEL, KVOT_INV_PSAR, KvotInfo, Plotly, registerActions, decaydata, kvotEscapeHtml, kvotFileTooLarge, kvotFormatBytes, KVOT_FILE_SIZE_LIMITS */
(function () {
  'use strict';

  const J = window.KVOT_INV_JSON, M = window.KVOT_INV_MODEL, PS = window.KVOT_INV_PSAR;
  const $ = (id) => document.getElementById(id);
  const ND = M.nuclearData(typeof decaydata !== 'undefined' ? decaydata : []);
  const STORE = 'kvot.inventory';
  const LIMIT_W = 1700;      // the decay heat a canister may have when deposited

  /* ---------------------------------------------------------------------
     State
     --------------------------------------------------------------------- */
  const state = {
    inv: null,                      // M.Inventory
    invFile: null,                  // {name, size}
    reading: null,                  // {name, share, worker}
    psar: { workbook: null, report: null },
    raw: null,                      // the Raw data view's choices, for one inventory
    busy: new Map(),                // file name -> what is being done
    settings: { at: 'packed', year: '', unit: 'mol', half: 'icrp', type: -1, fuel: 'all' },
    tab: 'overview',
    view: {
      nucShow: 'average', nucCan: '', nucSet: 'all', nucOrder: 'chain',
      level: 'can', qty: 'heat', against: 'date',
      timeOf: 'average', timeCan: '', timeQty: 'Bq', timeTo: '1e6', timeRef: '',
      ref: '', catNuc: 'activity',
    },
    detail: null,                   // the canister picked, an index
    canShown: 200,
    sort: { can: null },
    systems: new Map(),
  };

  function load() {
    try {
      const s = JSON.parse(localStorage.getItem(STORE) || '{}');
      if (s.unit && M.UNITS[s.unit]) state.settings.unit = s.unit;
      if (s.view && typeof s.view === 'object') {
        for (const k of ['nucShow', 'nucSet', 'nucOrder', 'level', 'timeQty', 'timeTo']) if (typeof s.view[k] === 'string') state.view[k] = s.view[k];
        if (!['all', 'actinides', 'products'].includes(state.view.nucSet)) state.view.nucSet = 'all';
      }
      if (typeof s.tab === 'string') state.tab = s.tab;
    } catch (e) { /* storage unavailable: defaults */ }
  }
  function save() {
    try {
      const v = state.view;
      localStorage.setItem(STORE, JSON.stringify({ unit: state.settings.unit, tab: state.tab,
        view: { nucShow: v.nucShow === 'one' ? 'average' : v.nucShow, nucSet: v.nucSet, nucOrder: v.nucOrder, level: v.level, timeQty: v.timeQty, timeTo: v.timeTo } }));
    } catch (e) { /* storage unavailable */ }
  }

  /* ---------------------------------------------------------------------
     Formatting
     --------------------------------------------------------------------- */
  const NNBSP = ' ';
  const intText = (n) => (Number.isFinite(n) ? Math.round(n).toLocaleString('en').replace(/,/g, NNBSP) : '–');
  const esc = (s) => kvotEscapeHtml(String(s ?? ''));
  const SUP = { '-': '⁻', 0: '⁰', 1: '¹', 2: '²', 3: '³', 4: '⁴', 5: '⁵', 6: '⁶', 7: '⁷', 8: '⁸', 9: '⁹' };

  /** A number to three (or d) figures: 1 642, 0.0123, 3.27×10^19 (HTML). */
  function numHtml(v, d = 3) {
    if (v === null || v === undefined || Number.isNaN(v)) return '–';
    if (!Number.isFinite(v)) return v > 0 ? '∞' : '−∞';
    if (v === 0) return '0';
    const a = Math.abs(v);
    if (a >= 0.01 && a < 1e5) {
      const s = Number(v.toPrecision(d));
      const digits = Math.max(0, d - 1 - Math.floor(Math.log10(a)));
      return (s < 0 ? '−' : '') + Math.abs(s).toLocaleString('en', { maximumFractionDigits: digits }).replace(/,/g, NNBSP);
    }
    const [m, e] = v.toExponential(d - 1).split('e');
    return `${m.replace('-', '−')}×10<sup>${Number(e) < 0 ? '−' : ''}${Math.abs(Number(e))}</sup>`;
  }
  /** The same as plain text, with superscript figures. */
  function numText(v, d = 3) {
    return numHtml(v, d).replace(/<sup>([^<]*)<\/sup>/g, (m, e) => [...e.replace('−', '-')].map((ch) => SUP[ch] || ch).join(''));
  }
  const pctText = (x, d = 1) => (Number.isFinite(x) ? `${(x * 100).toFixed(d)} %` : '–');
  const dateText = (ms) => (Number.isFinite(ms) ? new Date(ms).toISOString().slice(0, 10) : '–');

  /* ---------------------------------------------------------------------
     Half-lives, the time, the decay system
     --------------------------------------------------------------------- */

  /* ---- ENSDF: a release on the site, for half-lives, chains and energies (inventory-ensdf.js) ---- */
  const ensdf = new Map();          // release id -> {rel, db, nd, loading}

  /** The ENSDF releases on the site, offered under Half-lives once their list has come. */
  function offerEnsdf() {
    if (!window.KVOT_ENSDF_SOURCES || !window.KVOT_INV_ENSDF || !window.KVOT_RDC_ENSDF) return;
    window.KVOT_ENSDF_SOURCES.releases().then((list) => {
      for (const rel of list || []) {
        if (ensdf.has(rel.id)) continue;
        ensdf.set(rel.id, { rel, db: null, nd: null, loading: null });
        $('invHalf').append(h('option', { value: `ensdf:${rel.id}` }, `${rel.label}: half-lives and chains`));
      }
      renderBar();
    }).catch(() => { /* no release on the site: ICRP 107 and PSAR's only */ });
  }

  /** A release's database, read once, when it is first chosen. */
  function ensdfDb(id) {
    const e = ensdf.get(id);
    if (!e) return Promise.reject(new Error('there is no such release on the site'));
    if (!e.loading) {
      e.loading = withBusy(e.rel.label, 'Reading', async () => {
        const src = await window.KVOT_ENSDF_SOURCES.builtinSource(e.rel);
        e.db = window.KVOT_RDC_ENSDF.database(src.summary, typeof decaydata !== 'undefined' ? decaydata : []);
      }).catch((err) => { e.loading = null; throw err; });
    }
    return e.loading;
  }
  const ensdfInUse = () => {
    const h = state.settings.half;
    const e = h.startsWith('ensdf:') ? ensdf.get(h.slice(6)) : null;
    return e && e.db ? e : null;
  };

  /**
   * The decay data in use: ICRP 107's, or a release's for every nuclide the
   * inventory and PSAR's tables give, and every member below them.
   */
  function nd() {
    const e = ensdfInUse();
    if (!e) return ND;
    const names = [...new Set([...(state.inv ? state.inv.names() : []), ...refs().flatMap((r) => [...r.values.keys()])])].sort();
    const key = names.join(',');
    if (!e.nd || e.nd.key !== key) {
      const made = window.KVOT_INV_ENSDF.recordsFor(e.db, names, ND, typeof decaydata !== 'undefined' ? decaydata : []);
      e.nd = { key, map: M.nuclearData(made.records), made };
    }
    return e.nd.map;
  }

  /** What the decay data are, for the About sheets. */
  function decayWords() {
    const e = ensdfInUse();
    return e ? `${e.rel.label}: half-lives, branches and energies (ICRP Publication 107’s atomic masses), every chain to its end; CRAM of order 16`
      : 'ICRP Publication 107: half-lives, branches and energies, every chain to its end; CRAM of order 16';
  }
  const halfWords = () => `${$('invHalf').selectedOptions[0].textContent}${state.settings.half === 'report' ? '; ICRP 107 for the nuclides it does not list' : ''}`;

  /** The half-lives chosen, by nuclide (years); null for those of the decay data alone. */
  function halfLives() {
    const h = state.settings.half;
    if (h === 'report' && state.psar.report && state.psar.report.halfLives) return state.psar.report.halfLives.values;
    return null;
  }
  const halfKey = () => state.settings.half;

  function system() {
    const key = `${halfKey()}|${state.inv ? state.inv.names().join(',') : ''}`;
    if (!state.systems.has(key)) state.systems.set(key, M.decaySystem(nd(), state.inv.names(), halfLives()));
    return state.systems.get(key);
  }

  /**
   * The year the inventory is shown at, or null as packed. settings.year
   * holds only a year that can be shown; text typed in the field that is no
   * such year leaves it as it was, and the field is marked.
   */
  function year() {
    if (state.settings.at !== 'year' || !state.inv) return null;
    const y = Number(state.settings.year);
    return Number.isInteger(y) && y >= minYear() ? y : minYear();
  }
  const minYear = () => (state.inv && state.inv.minYear) || 2000;
  const MAX_YEAR = 100000000;
  const validYear = (t) => /^\d+$/.test(String(t).trim()) && Number(t) >= minYear() && Number(t) <= MAX_YEAR;
  const targetMs = () => (year() === null ? null : M.yearMs(year()));
  const timeWords = () => (year() === null ? 'as packed' : `in ${year()}`);

  /** Each canister at the time chosen. */
  function canAt() { return state.inv.canistersAt(system(), targetMs(), halfKey()); }
  /** Each canister at a given year (for views that need one). */
  function canAtYear(y) { return state.inv.canistersAt(system(), M.yearMs(y), halfKey()); }

  /** Moles to the unit, for a nuclide of the inventory. */
  function factorOf(name, unit = state.settings.unit, sys = system()) {
    const i = sys.index.has(name) ? sys.index.get(name) : -1;
    return M.perMole(sys, i, unit);
  }

  /** The canisters chosen in the bar. */
  function selection() { return state.inv.select(Number(state.settings.type)); }
  const typeName = (t) => (t >= 0 && state.inv ? state.inv.typeNames[t] : null);
  const selType = () => typeName(Number(state.settings.type));
  /** Which elements count (the bar's Fuel): 'all', 'discharged' or 'planned'. */
  const fuel = () => (state.inv ? state.inv.pick : 'all');
  const FUEL_WORDS = { all: '', discharged: 'discharged elements only', planned: 'planned elements only (the reactors’ forecast)' };
  const fuelWords = () => FUEL_WORDS[fuel()] || '';
  /** A share as a percentage, for the planned part of a whole. */
  const shareText = (part, whole) => (whole > 0 ? pctText(part / whole) : '–');

  /* ---------------------------------------------------------------------
     PSAR: what is open, merged
     --------------------------------------------------------------------- */

  /** Every reference open, the workbook's first. */
  function refs() {
    const out = [];
    for (const src of [state.psar.workbook, state.psar.report]) if (src) out.push(...src.refs);
    return out;
  }
  /** The best reference of a kind and scope: the workbook's, else the report's. */
  function refOf(kind, scope) {
    return refs().find((r) => r.kind === kind && r.scope === scope) || null;
  }
  const havePsar = () => !!(state.psar.workbook || state.psar.report);
  function psarCounts() {
    const c = { canisters: {}, elements: {} };
    for (const src of [state.psar.report, state.psar.workbook]) {
      if (!src) continue;
      Object.assign(c.canisters, src.counts.canisters);
      Object.assign(c.elements, src.counts.elements);
    }
    return c;
  }
  const simulation = () => (state.psar.workbook && state.psar.workbook.canisters) || null;

  /**
   * The half-lives PSAR worked its activities out with, its report's Table
   * D-1 (the workbook's are the same calculation), or null without the report.
   */
  const psarHalfLives = () => (state.psar.report && state.psar.report.halfLives ? state.psar.report.halfLives.values : null);
  /** How PSAR's becquerels became moles, in a sentence. */
  const psarMolesWords = () => (psarHalfLives()
    ? 'PSAR’s becquerels are turned into moles with its own half-lives (its report’s Table D-1), as it worked them out, and decay from there with the half-lives chosen above.'
    : 'PSAR’s becquerels are turned into moles with the half-lives chosen above; open its report for those it worked them out with (Table D-1).');

  /**
   * A reference's values (by nuclide) in the unit and at the time shown:
   * {values: Map, year, ok}. As packed, at the reference's own year. A year
   * before its own cannot be reached; ok is then false. Its becquerels are
   * moles first, by PSAR's own half-lives where its report is open.
   */
  function refValues(ref, y = year(), unit = state.settings.unit, values = ref.values) {
    const at = M.referenceAt(ref, nd(), halfLives(), y, values, psarHalfLives());
    const out = new Map();
    for (const [name, mol] of at.mol) {
      const i = at.sys.index.get(name);
      out.set(name, mol * M.perMole(at.sys, i, unit));
    }
    return { values: out, year: y === null ? ref.year : y, ok: at.ok, mol: at.mol, sys: at.sys, all: at.all };
  }

  /* ---------------------------------------------------------------------
     Charts
     --------------------------------------------------------------------- */
  const CONFIG = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d', 'toggleSpikelines'] };

  function theme() {
    const root = $('inv');
    const cs = getComputedStyle(root);
    const v = (n, d) => cs.getPropertyValue(n).trim() || d;
    return {
      text: v('--text-primary', '#161b22'), muted: v('--text-muted', '#5d6773'), secondary: v('--text-secondary', '#454e59'),
      grid: v('--border-color', '#dbe0e6'), surface: v('--bg-surface', '#f8f9fb'), bg: v('--bg-primary', '#fff'),
      bwr: v('--inv-bwr', '#2a78d6'), pwr: v('--inv-pwr', '#eb6834'),
      fuel: v('--inv-fuel', '#1baf7a'), structural: v('--inv-structural', '#6250d6'), crud: v('--inv-crud', '#eda100'), rods: v('--inv-rods', '#e87ba4'),
      s: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--inv-s${i}`, '#2a78d6')),
      ref: v('--inv-ref', '#161b22'), band: v('--inv-band', 'rgba(22,27,34,0.12)'), limit: v('--inv-limit', '#b4533f'),
    };
  }
  const typeColour = (t, th = theme()) => (/pwr/i.test(t || '') ? th.pwr : th.bwr);
  /* Planned fuel is the colour of its kind, hatched: one direction, the
     page's only texture, so that no colour stands for planned alone. */
  const hatched = (color, th = theme()) => ({ color, pattern: { shape: '/', fillmode: 'overlay', fgcolor: th.bg, size: 7, solidity: 0.4 } });
  const partColour = (key, th = theme()) => ({ fuel: th.fuel, crud: th.crud, structural_material: th.structural, structural: th.structural, control_rods: th.rods }[key] || th.muted);

  function base(th = theme()) {
    return {
      margin: { l: 64, r: 18, t: 10, b: 48 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: th.text, size: 11 },
      showlegend: true,
      legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom', font: { size: 11 }, bgcolor: 'rgba(0,0,0,0)' },
      xaxis: { gridcolor: th.grid, linecolor: th.grid, zeroline: false, exponentformat: 'power', automargin: true, tickfont: { color: th.secondary } },
      yaxis: { gridcolor: th.grid, linecolor: th.grid, zeroline: false, exponentformat: 'power', automargin: true, tickfont: { color: th.secondary } },
      hovermode: 'closest',
      hoverlabel: { bgcolor: th.surface, bordercolor: th.grid, font: { color: th.text, size: 11 } },
      bargap: 0.18,
    };
  }
  function deep(a, b) {
    for (const [k, v] of Object.entries(b || {})) {
      if (v && typeof v === 'object' && !Array.isArray(v) && a[k] && typeof a[k] === 'object' && !Array.isArray(a[k])) deep(a[k], v);
      else a[k] = v;
    }
    return a;
  }
  function plot(id, traces, layout = {}) {
    const el = $(id);
    if (!el) return;
    if (typeof Plotly === 'undefined') { el.textContent = 'The chart library (Plotly) did not load.'; return; }
    Plotly.react(el, traces, deep(base(), layout), CONFIG);
  }
  const plain = (s) => esc(s);   // text from a file, into a chart

  /* ---------------------------------------------------------------------
     DOM helpers
     --------------------------------------------------------------------- */
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'text') el.textContent = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const c of children) if (c !== null && c !== undefined && c !== false) el.append(c);
    return el;
  }
  function show(el, on) { if (el) el.hidden = !on; }

  /**
   * A table from columns {label, text?, html?, cls?, sort?} and rows.
   * html is for numbers the page makes; text for anything else.
   */
  function buildTable(cols, rows, opt = {}) {
    const t = h('table', { class: 'inv-table' });
    const tr = h('tr');
    cols.forEach((c, i) => {
      const th = h('th', { class: [c.cls, opt.sortable && c.sort ? 'sortable' : '', opt.sorted && opt.sorted.i === i ? `sorted${opt.sorted.asc ? ' asc' : ''}` : ''].filter(Boolean).join(' ') || null, scope: 'col' });
      if (c.labelHtml) th.innerHTML = c.labelHtml; else th.textContent = c.label;
      if (opt.sortable && c.sort) th.addEventListener('click', () => opt.onSort(i));
      tr.append(th);
    });
    t.append(h('thead', null, tr));
    const tb = h('tbody');
    for (const r of rows) {
      const row = h('tr', { class: [opt.pick ? 'pick' : '', opt.picked && opt.picked(r) ? 'picked' : ''].filter(Boolean).join(' ') || null });
      for (const c of cols) {
        const td = h('td', { class: typeof c.cls === 'function' ? c.cls(r) : c.cls });
        if (c.html) td.innerHTML = c.html(r); else td.textContent = c.text ? c.text(r) : '';
        row.append(td);
      }
      if (opt.pick) row.addEventListener('click', () => opt.pick(r));
      tb.append(row);
    }
    t.append(tb);
    if (opt.foot) {
      const tf = h('tfoot');
      const fr = h('tr');
      for (const c of cols) {
        const td = h('td', { class: c.cls });
        if (c.footHtml) td.innerHTML = c.footHtml(opt.foot); else td.textContent = c.footText ? c.footText(opt.foot) : '';
        fr.append(td);
      }
      tf.append(fr);
      t.append(tf);
    }
    return t;
  }

  function csvField(v) {
    const s = typeof v === 'number' ? (Number.isFinite(v) ? String(v) : '') : String(v ?? '');
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }
  function saveFile(name, bytes, type) {
    const blob = bytes instanceof Blob ? bytes : new Blob([bytes], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  function saveCsv(name, head, rows) {
    const text = [...head.map((l) => `# ${l}`), ...rows.map((r) => r.map(csvField).join(','))].join('\r\n');
    saveFile(name, `﻿${text}\r\n`, 'text/csv;charset=utf-8');
  }
  /* ---- Excel: written by SheetJS in a worker (inventory-excel.js), on the page where none can start ---- */
  function excelInWorker(sheets) {
    return new Promise((resolve, reject) => {
      let w;
      try { w = new Worker('./resources/js/inventory-excel-worker.js?v=20261102b'); } catch (e) { reject(Object.assign(new Error('no worker'), { noWorker: true })); return; }
      w.onmessage = (ev) => { w.terminate(); const m = ev.data || {}; if (m.error) reject(new Error(m.error)); else resolve(m.buf); };
      w.onerror = (ev) => { ev.preventDefault(); w.terminate(); reject(Object.assign(new Error('no worker'), { noWorker: true })); };
      w.postMessage({ sheets });
    });
  }
  async function buildExcel(sheets) {
    try {
      return await excelInWorker(sheets);
    } catch (err) {
      if (!err.noWorker) throw err;
      const XLSX = await loadScript('./vendors/js/xlsx-0.20.3.full.min.js?v=20261009', 'XLSX');
      await loadScript('./resources/js/inventory-excel.js?v=20261102b', 'KVOT_INV_EXCEL');
      return window.KVOT_INV_EXCEL.build(XLSX, sheets);
    }
  }

  /** What the numbers are: the settings, the files, when. Every workbook ends with it. */
  function aboutSheet(extra = []) {
    const p = state.psar;
    const rows = [
      ['Saved from', 'Canister Inventory, kvotab.se/canister_inventory.html'],
      ['Saved', `${new Date().toISOString().slice(0, 16).replace('T', ' ')} UTC`],
      ['Inventory', state.invFile ? state.invFile.name : '–'],
      ...extra,
      ['Time', year() === null ? 'as packed: each canister at its own packing date' : `1 January ${year()}: every canister decayed to it from its packing date`],
      ['Unit', state.settings.unit],
      ['Half-lives', halfWords()],
      ['Canisters', selType() ? `${selType()} only` : 'all'],
      ['Fuel', fuelWords() || (state.inv && state.inv.nPlanned ? 'all elements, discharged and planned (PLAN…)' : 'all elements')],
      ['Decay', decayWords()],
    ];
    if (p.workbook) rows.push(['PSAR workbook', p.workbook.source]);
    if (p.report) rows.push(['PSAR report', p.report.source]);
    if (p.workbook || p.report) rows.push(['PSAR’s moles', psarHalfLives() ? 'its becquerels with its own half-lives (Table D-1), then decayed with those above' : 'its becquerels with the half-lives above (its report, with Table D-1, not open)']);
    return { name: 'About', columns: [{ label: 'What', width: 16 }, { label: 'Value', width: 100 }], rows };
  }

  async function saveExcel(name, sheets, button, extra = []) {
    const was = button ? button.textContent : '';
    if (button) { button.disabled = true; button.textContent = 'Preparing…'; }
    try {
      const buf = await buildExcel([...sheets, aboutSheet(extra)]);
      saveFile(name, new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }));
    } catch (err) {
      showError([`The Excel file could not be written: ${err.message}`]);
    } finally {
      if (button) { button.disabled = false; button.textContent = was; }
    }
  }

  /* The inventory's own name, out of an archive and without .json or .gz. */
  const baseName = () => {
    if (!state.invFile) return 'inventory';
    const name = state.invFile.name.split('›').pop().trim().split('/').pop();
    return name.replace(/\.(gz|gzip)$/i, '').replace(/\.[^.]+$/, '').replace(/[^\w.() -]+/g, '_') || 'inventory';
  };

  /* ---------------------------------------------------------------------
     Nuclides: which, in what order
     --------------------------------------------------------------------- */
  const isActinide = (u) => u.z >= 81;

  /** The inventory's nuclides (indices) of a set, in an order. */
  function nuclideList(set = state.view.nucSet, order = state.view.nucOrder, amounts = null) {
    const inv = state.inv;
    let list = inv.nuclides.slice();
    if (set === 'actinides') list = list.filter(isActinide);
    else if (set === 'products') list = list.filter((u) => !isActinide(u));
    if (order === 'name') {
      list.sort((a, b) => (J.SYMBOLS[a.z] || a.name).localeCompare(J.SYMBOLS[b.z] || b.name) || a.a - b.a || a.name.localeCompare(b.name));
    } else if (order === 'amount' && amounts) {
      list.sort((a, b) => (amounts[b.k] || 0) - (amounts[a.k] || 0));
    } else {
      /* Decay chains: the actinides chain by chain (4n, 4n+1, 4n+2,
         4n+3), each from its top down; then the rest by element and mass. */
      const sys = system();
      const rank = (u) => (sys.index.has(u.name) ? sys.index.get(u.name) : 1e9);
      list.sort((a, b) => {
        const aa = isActinide(a), ba = isActinide(b);
        if (aa !== ba) return aa ? -1 : 1;
        if (aa) return (a.a % 4) - (b.a % 4) || rank(a) - rank(b);
        return a.z - b.z || a.a - b.a;
      });
    }
    return list.map((u) => u.k);
  }

  /* ---------------------------------------------------------------------
     The bar: files and settings
     --------------------------------------------------------------------- */
  function renderBar() {
    const box = $('invFiles');
    box.querySelectorAll('.inv-chip').forEach((c) => c.remove());
    const slot = box.querySelector('.kvot-info-slot');
    const chip = (role, name, what, onClose, busy) => {
      const c = h('span', { class: `inv-chip${busy ? ' busy' : ''}` },
        h('span', { class: 'inv-chip-role', text: role }),
        h('span', { class: 'inv-chip-name', text: name, title: name }));
      if (what !== null && what !== undefined) c.append(typeof what === 'string' ? h('span', { class: 'inv-chip-what', text: what }) : what);
      if (onClose) c.append(h('button', { type: 'button', 'aria-label': `Close ${name}`, title: 'Close', onclick: onClose, text: '×' }));
      box.insertBefore(c, slot);
    };
    if (state.reading) {
      const p = h('progress', { max: '1', value: String(state.reading.share || 0) });
      chip('Reading', state.reading.name, p, () => stopReading(), true);
    }
    if (state.inv) {
      chip('Inventory', state.invFile.name, `${intText(state.inv.nCan)} canisters`, () => closeInventory());
    }
    const p = state.psar;
    if (p.workbook) chip('PSAR workbook', p.workbook.source, `${p.workbook.refs.length} tables${p.workbook.canisters ? `, ${intText(p.workbook.canisters.length)} canisters` : ''}`, () => { p.workbook = null; changed('psar'); });
    if (p.report) chip('PSAR report', p.report.source, `${p.report.refs.length} tables${p.report.halfLives ? ', half-lives' : ''}`, () => { p.report = null; changed('psar'); });
    for (const [name, what] of state.busy) chip(what, name, null, null, true);

    /* Settings that depend on what is open. */
    const s = state.settings;
    const half = $('invHalf');
    half.querySelector('option[value="report"]').disabled = !(p.report && p.report.halfLives);
    if (half.selectedOptions[0] && half.selectedOptions[0].disabled) s.half = 'icrp';
    half.value = s.half;
    $('invUnit').value = s.unit;
    $('invAt').value = s.at;
    const yearBox = $('invYear');
    show(yearBox, s.at === 'year');
    show($('invYearHint'), s.at === 'year');
    /* Never written back while the visitor types in it. */
    if (s.at === 'year' && document.activeElement !== yearBox && yearBox.getAttribute('aria-invalid') !== 'true') yearBox.value = String(year() ?? s.year);
    $('invYearHint').textContent = state.inv ? `from ${minYear()}` : '';
    const type = $('invType');
    const want = String(s.type);
    fillSelect(type, [{ id: '-1', label: 'all' }, ...(state.inv ? state.inv.typeNames.map((t, i) => ({ id: String(i), label: t })) : [])], [...type.options].some((o) => o.value === want) || !state.inv ? want : '-1');
    if (!type.value) type.value = '-1';
    s.type = Number(type.value);
    type.disabled = !state.inv || state.inv.typeNames.length < 2;
    /* Fuel: only where the inventory holds planned elements and others. */
    const fuelBox = $('invFuel');
    const mixes = !!state.inv && state.inv.nPlanned > 0 && state.inv.nPlanned < state.inv.nEl;
    fuelBox.disabled = !mixes;
    fuelBox.value = mixes ? fuel() : 'all';
    fuelBox.title = state.inv && !mixes ? 'No element of this inventory is named PLAN…' : '';
  }

  /* ---------------------------------------------------------------------
     Tabs and redrawing
     --------------------------------------------------------------------- */
  const TABS = ['overview', 'nuclides', 'canisters', 'time', 'psar', 'raw', 'help'];

  function showTab(tab) {
    if (!TABS.includes(tab)) tab = 'overview';
    state.tab = tab;
    for (const t of TABS) {
      $(`invTab-${t}`).setAttribute('aria-selected', String(t === tab));
      $(`invPane-${t}`).hidden = t !== tab;
    }
    save();
    renderTab();
  }

  let renderQueued = false;
  function renderSoon() {
    if (renderQueued) return;
    renderQueued = true;
    requestAnimationFrame(() => { renderQueued = false; renderTab(); });
  }

  function renderTab() {
    renderBar();
    const has = !!state.inv;
    document.querySelectorAll('[data-needs="inventory"]').forEach((el) => show(el, !has));
    document.querySelectorAll('[data-has="inventory"]').forEach((el) => show(el, has));
    show($('invStart'), !has);
    show($('invOverview'), has);
    try {
      if (state.tab === 'overview' && has) renderOverview();
      else if (state.tab === 'nuclides' && has) renderNuclides();
      else if (state.tab === 'canisters' && has) renderCanisters();
      else if (state.tab === 'time' && has) renderTime();
      else if (state.tab === 'psar') renderPsar();
      else if (state.tab === 'raw' && has) renderRaw();
    } finally {
      KvotInfo.refresh();
    }
    /* A chart drawn while its tab was hidden, or the window another size,
       keeps that size until told: Plotly resizes only the charts in view. */
    if (typeof Plotly !== 'undefined') {
      const pane = $(`invPane-${state.tab}`);
      requestAnimationFrame(() => {
        for (const el of pane.querySelectorAll('.js-plotly-plot')) if (el.offsetParent !== null) Plotly.Plots.resize(el);
      });
    }
  }

  /* The full window: the page without the site's header and footer, kept in
     localStorage apart from the views' settings, so that the head can set it
     before the first paint. */
  const FULL_KEY = 'kvot.inventory.full';
  function setFull(on) {
    document.documentElement.classList.toggle('inv-full', !!on);
    try { localStorage.setItem(FULL_KEY, on ? '1' : '0'); } catch (e) { /* storage unavailable: for this visit only */ }
    fullState();
    /* The charts follow their boxes only when told. */
    if (typeof Plotly !== 'undefined') {
      requestAnimationFrame(() => {
        for (const el of $(`invPane-${state.tab}`).querySelectorAll('.js-plotly-plot')) if (el.offsetParent !== null) Plotly.Plots.resize(el);
      });
    }
  }
  function fullState() {
    const on = document.documentElement.classList.contains('inv-full');
    const b = $('invFull');
    b.setAttribute('aria-pressed', String(on));
    b.title = on ? 'Show the site’s header and footer again' : 'Full window: the page without the site’s header and footer';
    b.setAttribute('aria-label', on ? 'Leave the full window' : 'Full window');
  }

  /** Something changed: drop what was kept for it, and redraw. */
  function changed(what) {
    if (what === 'psar') {
      state.systems.clear();
      if (state.inv) state.inv.cache.clear();
    }
    if (what === 'half') {
      state.systems.clear();
      if (state.inv) state.inv.cache.clear();
    }
    renderSoon();
  }

  /* ---------------------------------------------------------------------
     Overview
     --------------------------------------------------------------------- */
  function renderOverview() {
    const inv = state.inv, d = inv.data, th = theme();
    const sel = selection();
    const at = canAt();
    const sim = simulation();
    const pc = psarCounts();
    const st = selType();

    /* Notes from reading. */
    const n = d.notes, notes = [];
    if (n.lenient) notes.push(`${intText(n.lenient)} canisters held NaN or Infinity, read as missing values`);
    if (n.nulls || n.notFinite) notes.push(`${intText(n.nulls + n.notFinite)} amounts were missing and count as none`);
    if (n.negative) notes.push(`${intText(n.negative)} amounts are negative`);
    if (n.missing) notes.push(`${intText(n.missing)} amounts are not given (a nuclide or part some elements lack) and count as none`);
    if (n.badDates) notes.push(`${intText(n.badDates)} packing dates could not be read`);
    if (inv.undated) notes.push(`${intText(inv.undated)} canisters have no packing date; they are left as given in every year`);
    if (n.notCanister.length) notes.push(`${intText(n.notCanister.length)} members of the file are not canisters and were passed over`);
    if (inv.unknown.length) notes.push(`no decay data for ${inv.unknown.join(', ')}: kept as given at every time, with no becquerels`);
    const nw = $('invNotes');
    nw.textContent = notes.length ? `Read with notes: ${notes.join('; ')}.` : '';
    show(nw, notes.length > 0);

    $('invOverviewSub').textContent = `${state.invFile.name}: ${intText(inv.nCan)} canisters with ${intText(inv.nEl)} fuel elements, ${inv.N} nuclides in ${inv.P} parts (${inv.parts.map((p) => p.label.toLowerCase()).join(', ')}). Shown ${timeWords()}${st ? `, ${st} canisters only` : ''}${fuelWords() ? `, ${fuelWords()}; PSAR’s numbers beside them are of all its fuel` : ''}.`;

    /* Tiles. */
    const typeCounts = new Map();
    for (const c of sel) { const t = typeName(inv.canType[c]) || 'other'; typeCounts.set(t, (typeCounts.get(t) || 0) + 1); }
    const elCount = sel.reduce((s, c) => s + inv.nIn(c), 0);
    const planned = plannedCount(sel);
    /* What is planned, beside the whole, when the whole is shown. */
    const split = fuel() === 'all' && planned > 0;
    const atP = split ? inv.canistersAt(system(), targetMs(), halfKey(), 'planned') : null;
    let withPlanned = 0, onlyPlanned = 0;
    if (split) for (const c of sel) { const k = inv.nIn(c, 'planned'); if (k) { withPlanned++; if (k === d.canisters.nEl[c]) onlyPlanned++; } }
    const elTypes = inv.fields.type ? inv.countBy(inv.fields.type, sel) : new Map();
    const first = Math.min(...Array.from(sel, (c) => d.canisters.date[c]).filter(Number.isFinite));
    const last = Math.max(...Array.from(sel, (c) => d.canisters.date[c]).filter(Number.isFinite));
    const sys = system();
    const full = inv.fullSum(at, sel);
    const fullP = atP ? inv.fullSum(atP, sel) : null;
    const massIn = (f, sym) => {
      let g = 0;
      sys.members.forEach((name, i) => { if (name.split('-')[0] === sym) g += f[i] * sys.mass[i]; });
      return g;
    };
    const mass = (sym) => massIn(full, sym);
    let act = 0, heat = 0, heatFile = 0, decl = 0, maxHeat = 0, maxFile = 0, maxDecl = 0;
    let actP = 0, heatP = 0, heatFileP = 0;
    const fileHeat = inv.canNum('decay_heat_W'), declared = inv.canNum('declared_heat_W');
    const fileHeatP = split ? inv.canNum('decay_heat_W', 'planned') : null;
    for (const c of sel) {
      if (atP) { actP += atP.activity[c]; heatP += atP.heat[c]; if (fileHeatP && Number.isFinite(fileHeatP[c])) heatFileP += fileHeatP[c]; }
      act += at.activity[c];
      heat += at.heat[c];
      maxHeat = Math.max(maxHeat, at.heat[c]);
      if (fileHeat) { heatFile += fileHeat[c] || 0; maxFile = Math.max(maxFile, fileHeat[c] || 0); }
      if (declared) { decl += declared[c] || 0; maxDecl = Math.max(maxDecl, declared[c] || 0); }
    }
    const typesLine = (m) => [...m].sort((a, b) => b[1] - a[1]).map(([t, k]) => `${intText(k)} ${t}`).join(' · ');
    const tiles = [];
    const scope = st ? `${st} ` : '';
    tiles.push({
      label: `${scope}Canisters`, value: intText(sel.length),
      sub: [typeCounts.size > 1 ? typesLine(typeCounts) : '', split ? `${intText(withPlanned)} with planned elements${onlyPlanned ? ` (${intText(onlyPlanned)} only planned)` : ''}` : ''].filter(Boolean).join(' · '),
      ref: Number.isFinite(pc.canisters.all) ? `PSAR: ${intText(st ? pc.canisters[st] : pc.canisters.all)}${!st && Number.isFinite(pc.canisters.BWR) ? ` (${intText(pc.canisters.BWR)} BWR · ${intText(pc.canisters.PWR)} PWR)` : ''}` : '',
    });
    const simEls = sim ? sim.filter((c) => !st || c.type === st).reduce((s, c) => s + c.n, 0) : null;
    tiles.push({
      label: 'Fuel elements', value: intText(elCount),
      sub: [elTypes.size > 1 ? typesLine(elTypes) : '', split ? `${intText(planned)} planned (${shareText(planned, elCount)})` : fuel() === 'planned' ? 'all planned' : ''].filter(Boolean).join(' · '),
      ref: simEls ? `PSAR’s simulation: ${intText(simEls)}` : '',
    });
    const simYears = sim ? sim.filter((c) => !st || c.type === st).map((c) => c.year).filter(Number.isFinite) : [];
    tiles.push({
      label: 'Packed', value: Number.isFinite(first) ? `${new Date(first).getUTCFullYear()}–${new Date(last).getUTCFullYear()}` : '–',
      sub: Number.isFinite(first) ? `first ${dateText(first)}, last ${dateText(last)}` : 'no packing dates',
      ref: simYears.length ? `PSAR deposited ${Math.min(...simYears)}–${Math.max(...simYears)}` : '',
    });
    const u = mass('U'), pu = mass('Pu');
    const uP = fullP ? massIn(fullP, 'U') : 0;
    tiles.push({ label: 'Uranium', value: `${numHtml(u / 1e6)} <small>t</small>`, sub: `plutonium ${numHtml(pu / 1e6)} t, americium ${numHtml(mass('Am') / 1e3)} kg; ${timeWords()}${split ? `; ${shareText(uP, u)} of the uranium in planned elements` : ''}`, html: true });
    const psarAct = psarActivity(st);
    tiles.push({
      label: `Activity, ${timeWords()}`, value: `${numHtml(act)} <small>Bq</small>`, html: true,
      sub: `the ${inv.N} nuclides listed; ${numHtml(act / sel.length)} Bq per canister${split ? `; ${shareText(actP, act)} in planned elements` : ''}`,
      ref: psarAct ? `PSAR: ${numHtml(psarAct.total)} Bq ${psarAct.when}` : '',
    });
    const heatTile = year() === null && fileHeat
      ? { label: 'Decay heat when packed', value: `${numHtml(heatFile / 1e6)} <small>MW</small>`, html: true,
          sub: `${intText(heatFile / sel.length)} W per canister, at most ${intText(maxFile)} W${split ? `; ${shareText(heatFileP, heatFile)} in planned elements` : ''}`,
          ref: declared ? `declared: ${intText(decl / sel.length)} W per canister, at most ${intText(maxDecl)} W` : '' }
      : { label: `Decay heat, ${timeWords()}`, value: `${numHtml(heat / 1e6)} <small>MW</small>`, html: true,
          sub: `${numHtml(heat / sel.length)} W per canister, at most ${numHtml(maxHeat)} W; from the nuclides listed${split ? `; ${shareText(heatP, heat)} in planned elements` : ''}`, ref: '' };
    if (sim && year() === null) {
      const sh = sim.filter((c) => !st || c.type === st).map((c) => c.heat);
      heatTile.ref += `${heatTile.ref ? '<br>' : ''}PSAR’s simulation: ${intText(sh.reduce((a, b) => a + b, 0) / sh.length)} W per canister, at most ${intText(Math.max(...sh))} W`;
    }
    heatTile.htmlRef = true;
    tiles.push(heatTile);

    /* The same numbers, whole, for the Excel file: quantity, this inventory, unit, PSAR, note. */
    const w = timeWords();
    const simHeat = sim ? sim.filter((c) => !st || c.type === st).map((c) => c.heat) : [];
    const summary = [
      [`${scope}Canisters`, sel.length, '', Number.isFinite(st ? pc.canisters[st] : pc.canisters.all) ? (st ? pc.canisters[st] : pc.canisters.all) : null, ''],
      ...[...typeCounts].map(([t, k]) => [`Canisters, ${t}`, k, '', Number.isFinite(pc.canisters[t]) ? pc.canisters[t] : null, '']),
      ['Fuel elements', elCount, '', simEls, simEls ? 'PSAR: its encapsulation simulation' : ''],
      ...[...elTypes].map(([t, k]) => [`Fuel elements, ${t}`, k, '', null, '']),
      ['Fuel elements, planned', planned, '', null, 'named PLAN…: the reactors’ forecast'],
      ...(split ? [['Canisters with planned elements', withPlanned, '', null, ''], ['Canisters with only planned elements', onlyPlanned, '', null, '']] : []),
      ['First packed', Number.isFinite(first) ? dateText(first) : '', '', simYears.length ? String(Math.min(...simYears)) : null, simYears.length ? 'PSAR: first year deposited' : ''],
      ['Last packed', Number.isFinite(last) ? dateText(last) : '', '', simYears.length ? String(Math.max(...simYears)) : null, simYears.length ? 'PSAR: last year deposited' : ''],
      [`Uranium, ${w}`, u / 1e6, 't', null, ''],
      [`Plutonium, ${w}`, pu / 1e6, 't', null, ''],
      [`Americium, ${w}`, mass('Am') / 1e3, 'kg', null, ''],
      [`Activity of the ${inv.N} nuclides, ${w}`, act, 'Bq', psarAct ? psarAct.total : null, psarAct ? `PSAR ${psarAct.when}` : ''],
      [`Activity per canister, ${w}`, act / sel.length, 'Bq', null, ''],
      ...(split ? [[`Uranium in planned elements, ${w}`, uP / 1e6, 't', null, ''], [`Activity in planned elements, ${w}`, actP, 'Bq', null, ''], [`Decay heat from the nuclides in planned elements, ${w}`, heatP, 'W', null, '']] : []),
    ];
    if (fileHeat) summary.push(['Decay heat when packed (file), all canisters', heatFile, 'W', null, ''], ['Decay heat when packed (file), per canister', heatFile / sel.length, 'W', simHeat.length ? simHeat.reduce((a, b) => a + b, 0) / simHeat.length : null, simHeat.length ? 'PSAR: its simulation, when deposited' : ''], ['Decay heat when packed (file), largest', maxFile, 'W', simHeat.length ? Math.max(...simHeat) : null, '']);
    if (declared) summary.push(['Declared heat, per canister', decl / sel.length, 'W', null, ''], ['Declared heat, largest', maxDecl, 'W', null, '']);
    summary.push([`Decay heat from the nuclides, ${w}, all canisters`, heat, 'W', null, ''], [`Decay heat from the nuclides, ${w}, per canister`, heat / sel.length, 'W', null, ''], [`Decay heat from the nuclides, ${w}, largest`, maxHeat, 'W', null, '']);
    state.ovExport = { summary };
    const box = $('invTiles');
    box.replaceChildren(...tiles.map((t) => {
      const el = h('div', { class: 'inv-tile' }, h('div', { class: 'inv-tile-label', text: t.label }));
      el.append(h('div', { class: 'inv-tile-value', html: t.html ? t.value : esc(t.value) }));
      if (t.sub) el.append(h('div', { class: 'inv-tile-sub', html: t.html ? t.sub : esc(t.sub) }));
      if (t.ref) el.append(h('div', { class: 'inv-tile-ref', html: t.htmlRef || t.html ? t.ref : esc(t.ref) }));
      return el;
    }));

    /* Canisters packed each year: of each type, those holding planned elements hatched. */
    const years = new Map(), yearsP = new Map();
    for (const c of sel) {
      const ms = d.canisters.date[c];
      if (!Number.isFinite(ms)) continue;
      const y = new Date(ms).getUTCFullYear();
      const t = typeName(inv.canType[c]) || 'other';
      for (const [m, on] of [[years, true], [yearsP, split && inv.nIn(c, 'planned') > 0]]) {
        if (!on) continue;
        if (!m.has(t)) m.set(t, new Map());
        m.get(t).set(y, (m.get(t).get(y) || 0) + 1);
      }
    }
    const traces = [];
    for (const [t, m] of [...years].sort((a, b) => a[0].localeCompare(b[0]))) {
      const mp = yearsP.get(t) || new Map();
      const xs = [...m.keys()];
      traces.push({
        type: 'bar', name: split ? `${plain(t)}, discharged only` : plain(t), x: xs, y: xs.map((y) => m.get(y) - (mp.get(y) || 0)), marker: { color: typeColour(t, th) },
        hovertemplate: `%{y} ${plain(t)} canisters${split ? ' of discharged fuel only' : ''} packed in %{x}<extra></extra>`,
      });
      if (mp.size) {
        traces.push({
          type: 'bar', name: `${plain(t)}, with planned elements`, x: [...mp.keys()], y: [...mp.values()], marker: hatched(typeColour(t, th), th),
          hovertemplate: `%{y} ${plain(t)} canisters holding planned elements packed in %{x}<extra></extra>`,
        });
      }
    }
    const dep = new Map();
    if (sim) {
      for (const c of sim) if (!st || c.type === st) dep.set(c.year, (dep.get(c.year) || 0) + 1);
      const xs = [...dep.keys()].sort((a, b) => a - b);
      traces.push({ type: 'scatter', mode: 'lines+markers', name: 'PSAR, deposited', x: xs, y: xs.map((y) => dep.get(y)), line: { color: th.ref, width: 2, shape: 'hvh' }, marker: { size: 5, color: th.ref }, hovertemplate: '%{y} canisters deposited in %{x} (PSAR)<extra></extra>' });
    }
    state.ovExport.years = { types: [...years.keys()].sort(), byType: years, withPlanned: split ? yearsP : null, dep: sim ? dep : null };
    plot('invChartYears', traces, { barmode: 'stack', xaxis: { title: { text: 'year packed' }, dtick: 5 }, yaxis: { title: { text: 'canisters' } } });
    $('invYearsNote').textContent = [split ? `Hatched: the canisters holding planned elements (named PLAN…, the reactors’ forecast), ${intText(withPlanned)} of ${intText(sel.length)}; solid: those of discharged fuel only.` : '',
      sim ? 'PSAR’s line is its encapsulation simulation: the canisters deposited each year.' : ''].filter(Boolean).join(' ');

    /* Fuel elements by reactor. */
    renderReactorChart(sel, th);

    /* Decay heat per canister when packed. */
    renderHeatChart(sel, th);
  }

  /** The planned elements among those that count, in a set of canisters. */
  function plannedCount(sel) {
    const inv = state.inv, can = inv.data.canisters;
    let n = 0;
    for (const c of sel) for (let e = can.el0[c], end = e + can.nEl[c]; e < end; e++) if (inv.planned[e] && inv.picks(e)) n++;
    return n;
  }

  /** PSAR's total activity, at the time shown when it can be. */
  function psarActivity(st) {
    const parts = refs().filter((r) => r.kind === 'total' && r.source === (state.psar.workbook || state.psar.report || {}).source);
    if (!parts.length) return null;
    const wanted = st ? parts.filter((r) => r.scope === st) : parts;
    if (!wanted.length) return null;
    let total = 0, when = '';
    for (const r of wanted) {
      const y = year() !== null && year() >= r.year ? year() : null;
      const v = refValues(r, y, 'Bq');
      for (const x of v.values.values()) total += x;
      when = y === null ? `in ${r.year}` : `in ${y}`;
    }
    return { total, when: st ? `${when}, its ${st} fuel` : when };
  }

  function renderReactorChart(sel, th) {
    const inv = state.inv;
    const f = inv.fields.reactor;
    const el = $('invChartReactors');
    if (!f) { el.textContent = 'The elements name no reactor.'; return; }
    const counts = inv.countBy(f, sel);
    /* Of each reactor, the planned elements hatched, when the whole is shown. */
    const split = fuel() === 'all' && inv.nPlanned > 0;
    const planned = split ? inv.countBy(f, sel, 'planned') : new Map();
    /* Each reactor's type: that of most of its elements. */
    const tf = inv.fields.type ? inv.data.elements.text[inv.fields.type] : null;
    const rf = inv.data.elements.text[f];
    const typeOf = new Map();
    if (tf) for (let e = 0; e < inv.nEl; e++) { const r = rf.values[rf.codes[e]]; if (!typeOf.has(r)) typeOf.set(r, tf.values[tf.codes[e]]); }
    const rows = [...counts].sort((a, b) => a[1] - b[1]);
    const sim = simulation();
    const simCounts = new Map();
    if (sim) for (const c of sim) if (!selType() || c.type === selType()) for (const e of c.elements) simCounts.set(e.reactor, (simCounts.get(e.reactor) || 0) + 1);
    const names = rows.map(([r]) => r);
    for (const r of simCounts.keys()) if (!counts.has(r)) names.unshift(r);
    const traces = [{
      type: 'bar', orientation: 'h', name: split ? 'discharged' : 'this inventory', y: names.map(plain), x: names.map((r) => (counts.get(r) || 0) - (planned.get(r) || 0)),
      marker: { color: names.map((r) => typeColour(typeOf.get(r), th)) },
      hovertemplate: `%{x}${split ? ' discharged' : ''} elements from %{y}<extra></extra>`, showlegend: split,
    }];
    if (split && planned.size) {
      traces.push({
        type: 'bar', orientation: 'h', name: 'planned', y: names.map(plain), x: names.map((r) => planned.get(r) || 0),
        marker: hatched(names.map((r) => typeColour(typeOf.get(r), th)), th), hovertemplate: '%{x} planned elements from %{y}<extra></extra>',
      });
    }
    if (sim) {
      traces.push({ type: 'scatter', mode: 'markers', name: 'PSAR’s simulation', y: names.map(plain), x: names.map((r) => simCounts.get(r) ?? null), marker: { symbol: 'circle-open', size: 9, color: th.ref, line: { width: 2 } }, hovertemplate: '%{x} elements from %{y} in PSAR’s simulation<extra></extra>' });
    }
    plot('invChartReactors', traces, { barmode: 'stack', margin: { l: 150, t: 22 }, height: Math.max(300, names.length * 21 + 70), xaxis: { title: { text: 'fuel elements' } }, yaxis: { automargin: true, tickfont: { size: 11 } }, showlegend: !!sim || split });
    el.style.height = `${Math.max(300, names.length * 21 + 70)}px`;
    $('invReactorsNote').textContent = `Blue: BWR, orange: PWR.${split ? ' Hatched: the planned elements, the reactors’ forecast of fuel not yet discharged.' : ''}${sim ? ' Rings: the elements of each reactor in PSAR’s encapsulation simulation.' : ''}`;
    if (state.ovExport) state.ovExport.reactors = names.slice().reverse().map((r) => [r, typeOf.get(r) || '', counts.get(r) || 0, split ? planned.get(r) || 0 : null, sim ? simCounts.get(r) || 0 : null]);
  }

  /** The Overview's numbers, its canisters each year and its reactors, as sheets. */
  function overviewExcel(button) {
    const x = state.ovExport;
    if (!x) return;
    const sheets = [{
      name: 'Summary',
      columns: [{ label: 'Quantity', width: 46 }, { label: 'This inventory', width: 16 }, { label: 'Unit', width: 6 }, { label: 'PSAR', width: 16 }, { label: 'Note', width: 40 }],
      rows: x.summary,
    }];
    if (x.years) {
      const ys = new Set();
      for (const m of x.years.byType.values()) for (const y of m.keys()) ys.add(y);
      if (x.years.dep) for (const y of x.years.dep.keys()) ys.add(y);
      const list = [...ys].sort((a, b) => a - b);
      sheets.push({
        name: 'Canisters each year',
        columns: [{ label: 'Year', width: 8 }, ...x.years.types.map((t) => ({ label: `${t}, packed`, fmt: 'int', width: 12 })), { label: 'All, packed', fmt: 'int', width: 12 },
          ...(x.years.withPlanned ? x.years.types.map((t) => ({ label: `${t}, with planned elements`, fmt: 'int', width: 16 })) : []),
          ...(x.years.dep ? [{ label: 'PSAR, deposited', fmt: 'int', width: 16 }] : [])],
        rows: list.map((y) => {
          const per = x.years.types.map((t) => x.years.byType.get(t).get(y) || 0);
          const planned = x.years.withPlanned ? x.years.types.map((t) => (x.years.withPlanned.get(t) || new Map()).get(y) || 0) : [];
          return [y, ...per, per.reduce((a, b) => a + b, 0), ...planned, ...(x.years.dep ? [x.years.dep.get(y) || 0] : [])];
        }),
      });
    }
    if (x.reactors) {
      sheets.push({
        name: 'Elements by reactor',
        columns: [{ label: 'Reactor', width: 28 }, { label: 'Type', width: 7 }, { label: 'Fuel elements', fmt: 'int', width: 14 }, { label: 'Of them planned', fmt: 'int', width: 15 }, { label: 'PSAR’s simulation', fmt: 'int', width: 18 }],
        rows: x.reactors,
      });
    }
    saveExcel(`${fileTag()}-overview.xlsx`, sheets, button);
  }

  function renderHeatChart(sel, th) {
    const inv = state.inv;
    const fileHeat = inv.canNum('decay_heat_W'), declared = inv.canNum('declared_heat_W');
    const split = fuel() === 'all' && inv.nPlanned > 0;
    const traces = [];
    const packed = inv.canistersAt(system(), null, halfKey());
    /* One set of 25 W bins for all: the types stack, the declared heat is a
       step line over them. */
    const BIN = 25;
    const all = [];
    for (const c of sel) { const x = fileHeat ? fileHeat[c] : packed.heat[c]; if (Number.isFinite(x)) all.push(x); if (declared && Number.isFinite(declared[c])) all.push(declared[c]); }
    const start = Math.floor(Math.min(...all) / BIN) * BIN, end = Math.ceil(Math.max(...all) / BIN + 1e-9) * BIN;
    const nb = Math.max(1, Math.round((end - start) / BIN));
    const centres = Array.from({ length: nb }, (_, i) => start + (i + 0.5) * BIN);
    const count = (vals) => { const n = new Array(nb).fill(0); for (const x of vals) if (Number.isFinite(x)) n[Math.min(nb - 1, Math.max(0, Math.floor((x - start) / BIN)))]++; return n; };
    /* Of each type, the canisters holding planned elements hatched, when the whole is shown. */
    const byType = new Map();
    for (const c of sel) {
      const t = typeName(inv.canType[c]) || 'other';
      const key = `${t}|${split && inv.nIn(c, 'planned') > 0 ? 'p' : ''}`;
      if (!byType.has(key)) byType.set(key, []);
      byType.get(key).push(fileHeat ? fileHeat[c] : packed.heat[c]);
    }
    const rangeText = centres.map((x) => `${intText(x - BIN / 2)}–${intText(x + BIN / 2)}`);
    for (const [key, v] of [...byType].sort((a, b) => a[0].localeCompare(b[0]))) {
      const [t, p] = key.split('|');
      const what = p ? `${plain(t)} canisters holding planned elements` : `${plain(t)} canisters${split ? ' of discharged fuel only' : ''}`;
      traces.push({ type: 'bar', name: `${plain(t)}${p ? ', with planned elements' : split ? ', discharged only' : ''}${fileHeat ? '' : ', from the nuclides'}`, x: centres, y: count(v), width: BIN * 0.92, marker: p ? hatched(typeColour(t, th), th) : { color: typeColour(t, th) }, customdata: rangeText, hovertemplate: `%{y} ${what} at %{customdata} W<extra></extra>` });
    }
    if (declared) {
      const n = count(Array.from(sel, (c) => declared[c]));
      traces.push({ type: 'scatter', mode: 'lines', name: 'declared heat', x: [start, ...centres.map((x) => x + BIN / 2)], y: [n[0], ...n], line: { color: th.ref, width: 1.5, shape: 'vh' }, customdata: ['', ...rangeText], hovertemplate: '%{y} canisters declared at %{customdata} W<extra></extra>' });
    }
    plot('invChartHeat', traces, {
      barmode: 'stack', bargap: 0,
      xaxis: { title: { text: 'decay heat (W)' } }, yaxis: { title: { text: 'canisters' } },
      shapes: [{ type: 'line', x0: LIMIT_W, x1: LIMIT_W, y0: 0, y1: 1, yref: 'paper', line: { color: th.limit, width: 1.5, dash: 'dash' } }],
      annotations: [{ x: LIMIT_W, y: 1, yref: 'paper', text: '1 700 W', showarrow: false, xanchor: 'left', yanchor: 'top', xshift: 4, font: { size: 10, color: th.limit } }],
    });
    if (fileHeat) {
      const over = Array.from(sel).filter((c) => fileHeat[c] > LIMIT_W).length;
      const overD = declared ? Array.from(sel).filter((c) => declared[c] > LIMIT_W).length : 0;
      const of = fuel() === 'all' ? '' : ` A canister’s heat is that of its ${fuel()} elements alone, the sum of theirs in the file, and is no canister’s whole heat.`;
      $('invHeatNote').innerHTML = esc(`The bars are the decay heat the file gives each canister, the line the heat declared for it.${split ? ' Hatched: the canisters holding planned elements.' : ''}${of} `)
        + esc(`${intText(over)} canisters (${pctText(over / sel.length)}) are over 1 700 W by the first${declared ? `, ${intText(overD)} by the second` : ''}. `)
        + esc('From the nuclides listed the page works out ') + numHtml(median(Array.from(sel, (c) => packed.heat[c] / fileHeat[c])), 4)
        + esc(' of the file’s decay heat for the median canister; fuel packed soon after discharge still has heat from nuclides the file does not list.');
    } else {
      $('invHeatNote').textContent = 'The file gives no decay heat; the bars are worked out from the nuclides listed.';
    }
  }
  function median(values) {
    const v = Float64Array.from(values).filter(Number.isFinite).sort();
    return M.quantileSorted(v, 0.5);
  }

  /* ---------------------------------------------------------------------
     Nuclides
     --------------------------------------------------------------------- */

  /** Which canisters the Nuclides and Over time views are of. */
  function subject(show, canText) {
    const inv = state.inv;
    if (show === 'one') {
      const id = String(canText || '').trim();
      const c = inv.data.canisters.id.indexOf(id);
      if (c < 0) return { sel: Int32Array.of(), label: id ? `canister ${id}` : 'one canister', error: id ? `There is no canister ${id}.` : 'Type the name of a canister.', per: 1 };
      return { sel: Int32Array.of(c), label: `canister ${id}`, per: 1, one: c };
    }
    const sel = selection();
    const st = selType();
    return show === 'total'
      ? { sel, label: `all ${st ? `${st} ` : ''}canisters together`, per: 1, total: true }
      : { sel, label: `the average ${st ? `${st} ` : ''}canister`, per: sel.length || 1 };
  }

  /**
   * PSAR's values of the same kind as a subject, each document's: average
   * canisters of its type (all canisters', or one canister's type), or, for
   * canisters together, PSAR's totals (all its fuel, or a type's).
   */
  function refsForSubject(sub) {
    const st = sub.one !== undefined ? typeName(state.inv.canType[sub.one]) : selType();
    if (!sub.total) return refs().filter((r) => r.kind === 'average' && r.scope === (st || 'all'));
    if (st) return refs().filter((r) => r.kind === 'total' && r.scope === st);
    const out = [];
    for (const src of [state.psar.workbook, state.psar.report]) {
      const totals = src ? src.refs.filter((r) => r.kind === 'total') : [];
      if (!totals.length) continue;
      const values = new Map();
      for (const r of totals) for (const [n, v] of r.values) values.set(n, (values.get(n) || 0) + v);
      out.push({ ...totals[0], id: `${totals[0].id.split(':')[0]}:total:sum`, label: 'PSAR, all its fuel', scope: 'all', values });
    }
    return out;
  }
  /** PSAR's value to set beside a subject: the workbook's, else the report's. */
  function refForSubject(sub) {
    if (sub.total && selType()) return null;
    return refsForSubject(sub)[0] || null;
  }
  /** A reference as a choice: what it is, which document it is from, its year. */
  function refName(r) {
    const doc = { workbook: 'workbook', report: 'report' }[r.id.split(':')[0]];
    return `${r.label} — ${doc ? `${doc}, ` : ''}${r.where} (${r.year})`;
  }

  function renderNuclides() {
    const inv = state.inv, th = theme(), v = state.view;
    $('invNucShow').value = v.nucShow;
    $('invNucSet').value = v.nucSet;
    $('invNucOrder').value = v.nucOrder;
    show($('invNucCanBox'), v.nucShow === 'one');
    if (v.nucShow === 'one' && $('invNucCan') !== document.activeElement) $('invNucCan').value = v.nucCan;
    const sub = subject(v.nucShow, v.nucCan);
    $('invNucTitle').textContent = `Nuclides of ${sub.label}`;
    if (sub.error) {
      $('invNucSub').textContent = sub.error;
      Plotly.purge($('invChartNuc'));
      $('invNucTable').replaceChildren();
      $('invNucKey').replaceChildren();
      $('invNucNote').textContent = '';
      return;
    }
    const unit = state.settings.unit;
    const at = canAt();
    const sums = inv.sumOver(at.amounts, sub.sel);
    const per = sub.per;
    const f = inv.nuclides.map((u) => factorOf(u.name));
    const value = (k) => sums.total[k] / per * f[k];
    const ks = nuclideList(v.nucSet, v.nucOrder, Float64Array.from(inv.nuclides, (u, k) => value(k)));
    /* The spread among canisters (an average of several). */
    const spread = new Map();
    if (!sub.total && sub.sel.length > 1) {
      for (const k of ks) {
        const s = M.summary(inv.perCanister(at.amounts, sub.sel, k));
        spread.set(k, { p5: s.p5 * f[k], p50: s.p50 * f[k], p95: s.p95 * f[k], max: s.max * f[k], min: s.min * f[k] });
      }
    }
    const ref = havePsar() ? refForSubject(sub) : null;
    const rv = ref ? refValues(ref) : null;
    const refOk = rv && rv.ok;
    $('invNucSub').textContent = `${unit}${sub.total ? '' : ' per canister'}, ${timeWords()}${sub.sel.length > 1 && !sub.total ? `; ${intText(sub.sel.length)} canisters` : ''}${fuelWords() ? `; ${fuelWords()}` : ''}`;
    /* The planned elements' part of each nuclide, when the whole is shown. */
    const sumsP = fuel() === 'all' && inv.nPlanned > 0 ? inv.sumOver(inv.canistersAt(system(), targetMs(), halfKey(), 'planned').amounts, sub.sel) : null;

    /* The chart: values on the left, the parts' shares on the right. */
    const names = ks.map((k) => inv.nuclides[k].name);
    const yCat = names.slice().reverse();
    const rev = (arr) => arr.slice().reverse();
    const traces = [];
    if (spread.size) {
      const xs = [], ys = [];
      for (const k of ks) { const s = spread.get(k); if (s && s.p95 > 0) { xs.push(Math.max(s.p5, 1e-300), s.p95, null); ys.push(inv.nuclides[k].name, inv.nuclides[k].name, null); } }
      traces.push({ type: 'scatter', mode: 'lines', name: '5th to 95th percentile of the canisters', x: xs, y: ys, line: { color: th.s[0], width: 2 }, opacity: 0.45, hoverinfo: 'skip', xaxis: 'x', yaxis: 'y' });
    }
    traces.push({
      type: 'scatter', mode: 'markers', name: 'this inventory', x: rev(ks.map(value)), y: yCat,
      marker: { size: 8, color: th.s[0], line: { color: th.bg, width: 1.5 } },
      customdata: rev(ks.map((k) => { const s = spread.get(k); return s ? [numText(s.p5), numText(s.p50), numText(s.p95), numText(s.max)] : ['', '', '', '']; })),
      hovertemplate: `<b>%{x:.3e} ${unit}</b> %{y}${spread.size ? '<br>canisters: 5th %{customdata[0]}, median %{customdata[1]}, 95th %{customdata[2]}, largest %{customdata[3]}' : ''}<extra></extra>`,
      xaxis: 'x', yaxis: 'y',
    });
    if (refOk) {
      traces.push({
        type: 'scatter', mode: 'markers', name: `${ref.label}, ${rv.year}`, x: rev(ks.map((k) => rv.values.get(inv.nuclides[k].name) ?? null)), y: yCat,
        marker: { symbol: 'circle-open', size: 11, color: th.ref, line: { width: 2 } },
        hovertemplate: `<b>%{x:.3e} ${unit}</b> %{y}<br>${plain(ref.label)}, ${rv.year}<extra></extra>`, xaxis: 'x', yaxis: 'y',
      });
    }
    /* Parts. */
    inv.parts.forEach((p, pi) => {
      traces.push({
        type: 'bar', orientation: 'h', name: p.label, y: yCat,
        x: rev(ks.map((k) => { const t = sums.total[k]; return t > 0 ? sums.parts[pi][k] / t * 100 : 0; })),
        marker: { color: partColour(p.key, th), line: { color: th.bg, width: 1 } },
        hovertemplate: `%{x:.1f} % in ${plain(p.label.toLowerCase())}<extra>%{y}</extra>`, xaxis: 'x2', yaxis: 'y', legendgroup: 'parts',
      });
    });
    const positive = ks.map(value).filter((x) => x > 0);
    const lo = positive.length ? Math.floor(Math.log10(Math.min(...positive, ...(refOk ? [...rv.values.values()].filter((x) => x > 0) : [])))) : -10;
    const hi = positive.length ? Math.ceil(Math.log10(Math.max(...positive, ...(spread.size ? [...spread.values()].map((s) => s.p95) : [])))) : 0;
    /* Tall: the axes go on top, where the key is, and every row gets room. */
    const height = Math.max(340, ks.length * 17 + 80);
    $('invChartNuc').style.height = `${height}px`;
    plot('invChartNuc', traces, {
      margin: { l: 70, r: 12, t: 58, b: 10 }, barmode: 'stack', bargap: 0.25, showlegend: false,
      xaxis: { type: 'log', domain: [0, 0.72], range: [Math.max(lo, hi - 30), hi + 0.3], title: { text: `${unit}${sub.total ? '' : ' per canister'}`, standoff: 6 }, side: 'top' },
      xaxis2: { domain: [0.76, 1], range: [0, 100], side: 'top', title: { text: 'share by part (%)', standoff: 6 }, gridcolor: th.grid, linecolor: th.grid, zeroline: false, tickfont: { color: th.secondary } },
      yaxis: { type: 'category', categoryorder: 'array', categoryarray: yCat, tickfont: { size: 11 }, automargin: true, dtick: 1 },
    });
    const notes = [];
    if (ref && !refOk) notes.push(`${ref.label} holds for ${ref.year}; choose a year from ${ref.year} to see it here.`);
    if (ref && refOk && year() === null) notes.push(`PSAR’s values hold for ${rv.year}, the inventory’s for each canister’s packing date: choose a year under Time for the same time.`);
    if (ref && refOk) notes.push(psarMolesWords());
    if (!ref && havePsar()) notes.push(sub.total && selType() ? 'PSAR’s totals are by kind of fuel, not by canister type: see Compare with PSAR.' : 'No PSAR value of this kind is open.');
    $('invNucNote').textContent = notes.join(' ');
    const key = [h('span', null, h('i', { class: 'dot', style: `background:${th.s[0]}` }), 'this inventory')];
    if (spread.size) key.push(h('span', null, h('i', { class: 'line', style: `border-color:${th.s[0]};opacity:.55` }), '5th to 95th percentile of the canisters'));
    if (refOk) key.push(h('span', null, h('i', { class: 'ring' }), `${ref.label}, ${rv.year}`));
    key.push(...inv.parts.map((p) => h('span', null, h('i', { style: `background:${partColour(p.key, th)}` }), `${p.label} (share, right)`)));
    $('invNucKey').replaceChildren(...key);

    /* The table. */
    const sp = (k, f2) => { const sv = spread.get(k); return sv ? numHtml(sv[f2]) : '–'; };
    const cols = [
      { label: 'Nuclide', cls: 'text', text: (k) => inv.nuclides[k].name },
      { label: 'Half-life (y)', html: (k) => { const sys = system(); const i = sys.index.get(inv.nuclides[k].name); return i === undefined ? '–' : numHtml(sys.T[i]); } },
      { label: `${unit}${sub.total ? '' : ' per canister'}`, html: (k) => numHtml(value(k)) },
      ...inv.parts.map((p, pi) => ({ label: p.label, html: (k) => (sums.total[k] > 0 ? numHtml(sums.parts[pi][k] / sums.total[k] * 100, 3) + NNBSP + '%' : '–') })),
    ];
    if (spread.size) cols.push({ label: '5th pct', html: (k) => sp(k, 'p5') }, { label: 'median', html: (k) => sp(k, 'p50') }, { label: '95th pct', html: (k) => sp(k, 'p95') }, { label: 'largest', html: (k) => sp(k, 'max') });
    if (sumsP) cols.push({ label: 'Planned', html: (k) => (sums.total[k] > 0 ? numHtml(sumsP.total[k] / sums.total[k] * 100, 3) + NNBSP + '%' : '–') });
    if (refOk) {
      cols.push({ label: `PSAR, ${rv.year}`, html: (k) => numHtml(rv.values.get(inv.nuclides[k].name)) });
      cols.push({ label: 'this / PSAR', html: (k) => { const r = rv.values.get(inv.nuclides[k].name); return r > 0 ? numHtml(value(k) / r) : '–'; } });
    }
    $('invNucTable').replaceChildren(buildTable(cols, ks));
    if (sumsP) notes.unshift('Planned: the share of each nuclide in the planned elements (named PLAN…, the reactors’ forecast).');
    $('invNucNote').textContent = notes.join(' ');
    state.nucExport = { ks, value, sub, unit, spread, ref: refOk ? { label: ref.label, year: rv.year, values: rv.values } : null, parts: sums, planned: sumsP, at };
  }

  /** The Nuclides table with every digit, for CSV and Excel alike. */
  function nucTable() {
    const x = state.nucExport;
    if (!x) return null;
    const inv = state.inv, sys = system();
    const per = `${x.unit}${x.sub.total ? '' : ' per canister'}`;
    const columns = [{ label: 'Nuclide', width: 10 }, { label: 'Half-life (y)', fmt: 'sci', width: 13 }, { label: per, fmt: 'sci', width: 17 },
      ...inv.parts.map((p) => ({ label: `${p.label} (${x.unit})`, fmt: 'sci', width: 18 }))];
    if (x.spread.size) columns.push(...['5th percentile', 'median', '95th percentile', 'largest'].map((label) => ({ label: `${label} (${x.unit})`, fmt: 'sci', width: 16 })));
    if (x.planned) columns.push({ label: `In planned elements (${per})`, fmt: 'sci', width: 22 }, { label: 'Planned share', fmt: 'pct', width: 13 });
    if (x.ref) columns.push({ label: `${x.ref.label}, ${x.ref.year} (${x.unit})`, fmt: 'sci', width: 24 }, { label: 'this / PSAR', width: 12 });
    const rows = x.ks.map((k) => {
      const u = inv.nuclides[k];
      const i = sys.index.get(u.name);
      const f = factorOf(u.name);
      const r = [u.name, i === undefined ? null : sys.T[i], x.value(k), ...inv.parts.map((p, pi) => x.parts.parts[pi][k] / x.sub.per * f)];
      if (x.spread.size) { const s = x.spread.get(k); r.push(s.p5, s.p50, s.p95, s.max); }
      if (x.planned) r.push(x.planned.total[k] / x.sub.per * f, x.parts.total[k] > 0 ? x.planned.total[k] / x.parts.total[k] : null);
      if (x.ref) { const v = x.ref.values.get(u.name); r.push(v ?? null, v > 0 ? x.value(k) / v : null); }
      return r;
    });
    return { title: `Nuclides of ${x.sub.label}, ${timeWords()}, ${per}${fuelWords() ? `, ${fuelWords()}` : ''}`, columns, rows };
  }
  const csvHead = (title) => [title, `From ${state.invFile.name}; half-lives: ${$('invHalf').selectedOptions[0].textContent}`];
  const fileTag = () => `${baseName()}-${year() ?? 'packed'}`;

  function nucCsv() {
    const t = nucTable();
    if (t) saveCsv(`${baseName()}-nuclides-${year() ?? 'packed'}.csv`, csvHead(t.title), [t.columns.map((c) => c.label), ...t.rows]);
  }
  function nucExcel(button) {
    const t = nucTable();
    if (t) saveExcel(`${baseName()}-nuclides-${year() ?? 'packed'}.xlsx`, [{ name: 'Nuclides', columns: t.columns, rows: t.rows }], button, [['Table', t.title]]);
  }

  /* ---------------------------------------------------------------------
     Canisters (and elements)
     --------------------------------------------------------------------- */

  /** The quantities a canister or element can be shown by. */
  function quantities(level) {
    const inv = state.inv, d = inv.data;
    const rec = level === 'el' ? d.elements : d.canisters;
    const unit = state.settings.unit;
    const list = [];
    const packedWords = year() === null ? '' : ', as packed';
    if (rec.num.decay_heat_W) list.push({ id: 'heatFile', label: `decay heat${packedWords} (file)`, unit: 'W' });
    if (rec.num.declared_heat_W) list.push({ id: 'declared', label: `declared heat${packedWords}`, unit: 'W' });
    list.push({ id: 'heatCalc', label: `decay heat ${timeWords()}, from the nuclides`, unit: 'W' });
    list.push({ id: 'activity', label: `activity ${timeWords()}`, unit: 'Bq' });
    if (level === 'can') list.push({ id: 'elements', label: 'fuel elements', unit: '' });
    for (const [k] of Object.entries(rec.num)) if (!/^(decay_heat_W|declared_heat_W)$/.test(k)) list.push({ id: `num:${k}`, label: k.replace(/_/g, ' '), unit: '' });
    for (const k of nuclideList('all', 'chain')) list.push({ id: `n:${k}`, label: `${inv.nuclides[k].name} ${timeWords()}`, unit, k });
    return list;
  }

  /** Values of a quantity for each canister (or element) of the selection. */
  function quantityValues(q, level, sel) {
    const inv = state.inv, d = inv.data;
    if (level === 'can') {
      const at = canAt();
      if (q.id === 'heatFile') { const a = inv.canNum('decay_heat_W'); return Float64Array.from(sel, (c) => a[c]); }
      if (q.id === 'declared') { const a = inv.canNum('declared_heat_W'); return Float64Array.from(sel, (c) => a[c]); }
      if (q.id === 'heatCalc') return Float64Array.from(sel, (c) => at.heat[c]);
      if (q.id === 'activity') return Float64Array.from(sel, (c) => at.activity[c]);
      if (q.id === 'elements') return Float64Array.from(sel, (c) => inv.nIn(c));
      if (q.id === 'date') return Float64Array.from(sel, (c) => d.canisters.date[c]);
      if (q.id.startsWith('num:')) { const a = inv.canNum(q.id.slice(4)); return Float64Array.from(sel, (c) => a[c]); }
      const k = q.k;
      const f = factorOf(inv.nuclides[k].name);
      return Float64Array.from(inv.perCanister(at.amounts, sel, k), (x) => x * f);
    }
    /* Elements of the canisters chosen. */
    const els = elementsOf(sel);
    if (q.id === 'heatFile') return Float64Array.from(els, (e) => d.elements.num.decay_heat_W[e]);
    if (q.id === 'declared') return Float64Array.from(els, (e) => d.elements.num.declared_heat_W[e]);
    if (q.id === 'date') return Float64Array.from(els, (e) => d.canisters.date[d.elements.can[e]]);
    if (q.id.startsWith('num:')) { const a = d.elements.num[q.id.slice(4)]; return Float64Array.from(els, (e) => a[e]); }
    const at = inv.elementsAt(system(), targetMs(), halfKey());
    if (q.id === 'heatCalc') return Float64Array.from(els, (e) => at.heat[e]);
    if (q.id === 'activity') return Float64Array.from(els, (e) => at.activity[e]);
    const k = q.k;
    const f = factorOf(inv.nuclides[k].name);
    return Float64Array.from(els, (e) => at.amounts[e * inv.N + k] * f);
  }
  /** The elements that count, of a set of canisters. */
  function elementsOf(sel) {
    const inv = state.inv, can = inv.data.canisters;
    const out = [];
    for (const c of sel) for (let e = can.el0[c], end = e + can.nEl[c]; e < end; e++) if (inv.picks(e)) out.push(e);
    return Int32Array.from(out);
  }

  function renderCanisters() {
    const inv = state.inv, d = inv.data, v = state.view, th = theme();
    const level = v.level === 'el' ? 'el' : 'can';
    $('invLevel').value = level;
    const qs = quantities(level);
    if (!qs.some((q) => q.id === v.qty)) v.qty = qs[0].id;
    const againstList = [{ id: 'date', label: 'packing date' }, ...qs.filter((q) => q.id !== v.qty)];
    if (!againstList.some((q) => q.id === v.against)) v.against = 'date';
    fillSelect($('invQty'), qs, v.qty);
    fillSelect($('invAgainst'), againstList, v.against);
    const q = qs.find((x) => x.id === v.qty);
    const qa = againstList.find((x) => x.id === v.against);
    const sel = selection();
    const ids = level === 'el' ? elementsOf(sel) : sel;
    const yv = quantityValues(q, level, sel);
    const xv = qa.id === 'date' ? quantityValues({ id: 'date' }, level, sel) : quantityValues(qa, level, sel);
    const types = Int32Array.from(ids, (i) => (level === 'el' ? elType(i) : inv.canType[i]));
    const what = level === 'el' ? 'fuel element' : 'canister';
    const unitText = (x) => (x.unit ? ` (${x.unit})` : '');
    $('invScatterTitle').textContent = `Each ${what}: ${q.label} against ${qa.label}`;
    $('invHistTitle').textContent = `How the ${what}s spread`;

    /* Scatter, one trace per type; planned elements (or canisters holding
       them) as rings of the same colour, when the whole is shown. */
    const many = ids.length > 6000;
    const traces = [];
    const label = (i) => (level === 'el' ? `${d.elements.id[i]} (canister ${d.canisters.id[d.elements.can[i]]})` : `canister ${d.canisters.id[i]}`);
    const typesPresent = [...new Set(types)].sort((a, b) => a - b);
    const split = fuel() === 'all' && inv.nPlanned > 0;
    const isP = (i) => (level === 'el' ? inv.planned[ids[i]] === 1 : inv.nIn(ids[i], 'planned') > 0);
    for (const t of typesPresent) {
      for (const p of split ? [false, true] : [false]) {
        const idx = [];
        for (let i = 0; i < ids.length; i++) if (types[i] === t && Number.isFinite(yv[i]) && Number.isFinite(xv[i]) && (!split || isP(i) === p)) idx.push(i);
        if (!idx.length) continue;
        const tn = typeName(t) || 'other';
        const name = !split ? plain(tn) : p ? `${plain(tn)}, ${level === 'el' ? 'planned' : 'with planned elements'}` : `${plain(tn)}, discharged${level === 'el' ? '' : ' only'}`;
        traces.push({
          type: many ? 'scattergl' : 'scatter', mode: 'markers', name,
          x: idx.map((i) => (qa.id === 'date' ? new Date(xv[i]).toISOString().slice(0, 10) : xv[i])), y: idx.map((i) => yv[i]),
          text: idx.map((i) => plain(label(ids[i]))), customdata: idx.map((i) => ids[i]),
          marker: p
            ? { size: many ? 5 : 7, symbol: 'circle-open', color: typeColour(tn, th), opacity: many ? 0.6 : 0.85, line: { width: 1.5 } }
            : { size: many ? 4 : 6, color: typeColour(tn, th), opacity: many ? 0.5 : 0.75, line: { width: 0 } },
          hovertemplate: `%{text}${p ? (level === 'el' ? ', planned' : ', holding planned elements') : ''}<br>${plain(q.label)}: <b>%{y:.4g}</b>${esc(q.unit ? ` ${q.unit}` : '')}<br>${plain(qa.label)}: %{x${qa.id === 'date' ? '' : ':.4g'}}<extra></extra>`,
        });
      }
    }
    const logY = wantsLog(yv), logX = qa.id !== 'date' && wantsLog(xv);
    const shapes = [], ann = [];
    const ref = level === 'can' && q.k !== undefined ? refLine(q.k) : null;
    if (ref) {
      shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: ref.value, y1: ref.value, line: { color: th.ref, width: 1.5, dash: 'dash' } });
      ann.push({ xref: 'paper', x: 1, y: ref.value, text: plain(ref.label), showarrow: false, xanchor: 'right', yanchor: 'bottom', font: { size: 10, color: th.ref } });
    }
    if ((q.id === 'heatFile' || q.id === 'declared' || q.id === 'heatCalc') && level === 'can') {
      shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: LIMIT_W, y1: LIMIT_W, line: { color: th.limit, width: 1.5, dash: 'dot' } });
    }
    plot('invChartScatter', traces, {
      xaxis: { title: { text: `${qa.label}${unitText(qa)}` }, type: qa.id === 'date' ? 'date' : logX ? 'log' : 'linear' },
      yaxis: { title: { text: `${q.label}${unitText(q)}` }, type: logY ? 'log' : 'linear' },
      shapes, annotations: ann,
    });
    const el = $('invChartScatter');
    el.removeAllListeners && el.removeAllListeners('plotly_click');
    el.on && el.on('plotly_click', (ev) => {
      const pt = ev && ev.points && ev.points[0];
      if (!pt) return;
      const i = pt.customdata;
      pick(level === 'el' ? d.elements.can[i] : i);
    });
    const nP = split ? Array.from(ids.keys()).filter(isP).length : 0;
    $('invScatterNote').textContent = `${intText(ids.length)} ${what}s${many ? ' (drawn with WebGL)' : ''}${fuelWords() ? `, ${fuelWords()}` : ''}. ${split ? `Rings: the ${intText(nP)} ${level === 'el' ? 'planned elements (named PLAN…, the reactors’ forecast)' : 'canisters holding planned elements (named PLAN…, the reactors’ forecast)'}. ` : ''}Click one for its ${level === 'el' ? 'canister' : 'elements and nuclides'}.${ref ? ` Dashed: ${ref.label}.` : ''}`;

    /* How they spread: a histogram per type, with the means and PSAR. */
    renderHistogram(q, level, ids, yv, types, typesPresent, th);

    /* The table, largest first. */
    renderCanTable(q, qa, level, ids, yv, xv);
    renderDetail();
  }

  function elType(e) {
    const inv = state.inv;
    const f = inv.fields.type;
    if (!f) return -1;
    const col = inv.data.elements.text[f];
    const name = col.codes[e] >= 0 ? col.values[col.codes[e]] : null;
    return name === null ? -1 : inv.typeNames.indexOf(name);
  }

  function fillSelect(el, list, value) {
    const sig = list.map((q) => `${q.id}=${q.label}`).join('|');
    if (el.dataset.sig !== sig) {
      el.replaceChildren(...list.map((q) => h('option', { value: q.id, text: q.label })));
      el.dataset.sig = sig;
    }
    el.value = value;
  }

  function wantsLog(values) {
    let lo = Infinity, hi = 0;
    for (const x of values) if (x > 0) { lo = Math.min(lo, x); hi = Math.max(hi, x); }
    return hi > 0 && hi / lo > 300;
  }

  /** PSAR's average canister of the type shown, for one nuclide, in the unit and at the time shown. */
  function refLine(k) {
    if (!havePsar()) return null;
    const ref = refForSubject({ sel: selection() });
    if (!ref) return null;
    const rv = refValues(ref);
    if (!rv.ok) return null;
    const v = rv.values.get(state.inv.nuclides[k].name);
    if (!(v > 0)) return null;
    return { value: v, label: `${ref.label}, ${rv.year}`, ref, rv };
  }

  function renderHistogram(q, level, ids, yv, types, typesPresent, th) {
    const traces = [];
    const logX = wantsLog(yv);
    const vals = (t) => { const out = []; for (let i = 0; i < ids.length; i++) if (types[i] === t && Number.isFinite(yv[i]) && (!logX || yv[i] > 0)) out.push(logX ? Math.log10(yv[i]) : yv[i]); return out; };
    const shapes = [], ann = [], key = [];
    for (const t of typesPresent) {
      const tn = typeName(t) || 'other';
      const v = vals(t);
      traces.push({ type: 'histogram', name: plain(tn), x: v, nbinsx: 60, marker: { color: typeColour(tn, th), line: { color: th.bg, width: 0.5 } }, opacity: 0.85, hovertemplate: `%{y} ${plain(tn)} ${level === 'el' ? 'elements' : 'canisters'}<extra></extra>` });
      if (v.length) {
        const mean = v.reduce((a, b) => a + b, 0) / v.length;
        void mean;
      }
    }
    /* The average of the canisters shown, and PSAR's average with its spread. */
    let all = [];
    for (let i = 0; i < ids.length; i++) if (Number.isFinite(yv[i])) all.push(yv[i]);
    const mean = all.length ? all.reduce((a, b) => a + b, 0) / all.length : NaN;
    const X = (x) => (logX ? Math.log10(x) : x);
    if (Number.isFinite(mean) && (!logX || mean > 0)) {
      shapes.push({ type: 'line', x0: X(mean), x1: X(mean), y0: 0, y1: 1, yref: 'paper', line: { color: th.s[0], width: 2 } });
      key.push(h('span', null, h('i', { class: 'line', style: `border-color:${th.s[0]}` }), `mean of the ${level === 'el' ? 'elements' : 'canisters'}`));
    }
    const ref = level === 'can' && q.k !== undefined ? refLine(q.k) : null;
    if (ref) {
      const name = state.inv.nuclides[q.k].name;
      const lo = ref.ref.low && ref.ref.low.get(name), hi = ref.ref.high && ref.ref.high.get(name);
      if (Number.isFinite(lo) && Number.isFinite(hi)) {
        const a = ref.value * (1 + Math.min(lo, hi)), b = ref.value * (1 + Math.max(lo, hi));
        if (!logX || a > 0) {
          shapes.push({ type: 'rect', x0: X(Math.max(a, logX ? 1e-300 : -Infinity)), x1: X(b), y0: 0, y1: 1, yref: 'paper', fillcolor: th.band, line: { width: 0 }, layer: 'below' });
          key.push(h('span', null, h('i', { class: 'band' }), 'PSAR’s low to high burnup canister'));
        }
      }
      shapes.push({ type: 'line', x0: X(ref.value), x1: X(ref.value), y0: 0, y1: 1, yref: 'paper', line: { color: th.ref, width: 2, dash: 'dash' } });
      key.push(h('span', null, h('i', { class: 'dash', style: `border-color:${th.ref}` }), ref.label));
    }
    if ((q.id === 'heatFile' || q.id === 'declared' || q.id === 'heatCalc') && level === 'can') {
      shapes.push({ type: 'line', x0: X(LIMIT_W), x1: X(LIMIT_W), y0: 0, y1: 1, yref: 'paper', line: { color: th.limit, width: 1.5, dash: 'dot' } });
      key.push(h('span', null, h('i', { class: 'dash', style: `border-color:${th.limit}` }), '1 700 W'));
    }
    const tickvals = [], ticktext = [];
    if (logX && all.length) {
      const lo = Math.floor(Math.log10(Math.min(...all.filter((x) => x > 0)))), hi = Math.ceil(Math.log10(Math.max(...all)));
      for (let e = lo; e <= hi; e++) { tickvals.push(e); ticktext.push(`10<sup>${e}</sup>`); }
    }
    plot('invChartHist', traces, {
      barmode: 'stack', bargap: 0.02,
      xaxis: { title: { text: `${q.label}${q.unit ? ` (${q.unit})` : ''}${logX ? ', powers of ten' : ''}` }, ...(logX ? { tickvals, ticktext } : {}) },
      yaxis: { title: { text: level === 'el' ? 'elements' : 'canisters' } },
      shapes, annotations: ann,
    });
    $('invHistKey').replaceChildren(...key);
    const s = M.summary(all);
    $('invHistNote').innerHTML = all.length
      ? `${esc(`${intText(s.n)} ${level === 'el' ? 'elements' : 'canisters'}: mean `)}${numHtml(s.mean)}${esc(', median ')}${numHtml(s.p50)}${esc(', 5th to 95th percentile ')}${numHtml(s.p5)}${esc('–')}${numHtml(s.p95)}${esc(', smallest ')}${numHtml(s.min)}${esc(', largest ')}${numHtml(s.max)}${esc(q.unit ? ` ${q.unit}` : '')}.`
      : 'Nothing to show.';
  }

  function renderCanTable(q, qa, level, ids, yv, xv) {
    const inv = state.inv, d = inv.data;
    const order = Array.from(ids.keys());
    const sort = state.sort.can;
    const fileHeat = level === 'el' ? d.elements.num.decay_heat_W : inv.canNum('decay_heat_W');
    const declared = level === 'el' ? d.elements.num.declared_heat_W : inv.canNum('declared_heat_W');
    const hasPlanned = inv.nPlanned > 0 && fuel() === 'all';
    const rf = inv.fields.reactor ? d.elements.text[inv.fields.reactor] : null;
    const ff = inv.fields.fuel ? d.elements.text[inv.fields.fuel] : null;
    const txt = (col, e) => (col && col.codes[e] >= 0 ? col.values[col.codes[e]] : '');
    const cols = level === 'el'
      ? [
        { label: 'Element', cls: 'text', text: (i) => d.elements.id[ids[i]], sort: (i) => d.elements.id[ids[i]] },
        { label: 'Canister', cls: 'text', text: (i) => d.canisters.id[d.elements.can[ids[i]]], sort: (i) => Number(d.canisters.id[d.elements.can[ids[i]]]) || d.canisters.id[d.elements.can[ids[i]]] },
        { label: 'Reactor', cls: 'text', text: (i) => txt(rf, ids[i]), sort: (i) => txt(rf, ids[i]) },
        { label: 'Fuel type', cls: 'text', text: (i) => txt(ff, ids[i]), sort: (i) => txt(ff, ids[i]) },
        { label: 'Packed', cls: 'text', text: (i) => dateText(d.canisters.date[d.elements.can[ids[i]]]), sort: (i) => d.canisters.date[d.elements.can[ids[i]]] },
        ...(hasPlanned ? [{ label: 'Planned', cls: 'text', text: (i) => (inv.planned[ids[i]] ? 'yes' : ''), sort: (i) => inv.planned[ids[i]] }] : []),
      ]
      : [
        { label: 'Canister', cls: 'text', text: (i) => d.canisters.id[ids[i]], sort: (i) => Number(d.canisters.id[ids[i]]) || d.canisters.id[ids[i]] },
        { label: 'Type', cls: 'text', text: (i) => typeName(inv.canType[ids[i]]) || '', sort: (i) => inv.canType[ids[i]] },
        { label: 'Packed', cls: 'text', text: (i) => dateText(d.canisters.date[ids[i]]), sort: (i) => d.canisters.date[ids[i]] },
        { label: 'Elements', html: (i) => String(inv.nIn(ids[i])), sort: (i) => inv.nIn(ids[i]) },
        ...(hasPlanned ? [{ label: 'Planned', html: (i) => String(inv.nIn(ids[i], 'planned')), sort: (i) => inv.nIn(ids[i], 'planned') }] : []),
        { label: 'Reactors', cls: 'text', text: (i) => reactorsOf(ids[i]), sort: (i) => reactorsOf(ids[i]) },
      ];
    const qCol = cols.length;
    cols.push({ label: `${q.label}${q.unit ? ` (${q.unit})` : ''}`, html: (i) => numHtml(yv[i], 4), sort: (i) => yv[i] });
    if (qa.id !== 'date') cols.push({ label: `${qa.label}${qa.unit ? ` (${qa.unit})` : ''}`, html: (i) => numHtml(xv[i], 4), sort: (i) => xv[i] });
    if (fileHeat && q.id !== 'heatFile' && qa.id !== 'heatFile') cols.push({ label: 'Decay heat (W)', html: (i) => numHtml(fileHeat[ids[i]], 4), sort: (i) => fileHeat[ids[i]] });
    if (declared && q.id !== 'declared' && qa.id !== 'declared') cols.push({ label: 'Declared (W)', html: (i) => numHtml(declared[ids[i]], 4), sort: (i) => declared[ids[i]] });
    /* Sorted by the quantity shown, largest first, until a heading is clicked. */
    const si = sort && sort.level === level && sort.q === q.id && sort.i < cols.length ? sort.i : qCol;
    const asc = sort && sort.level === level && sort.q === q.id ? sort.asc : false;
    const keyOf = cols[si].sort;
    order.sort((a, b) => {
      const x = keyOf(a), y = keyOf(b);
      const nx = typeof x === 'number' && !Number.isFinite(x), ny = typeof y === 'number' && !Number.isFinite(y);
      if (nx || ny) return nx - ny;
      return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1);
    });
    const shown = order.slice(0, state.canShown);
    $('invCanTableTitle').textContent = `${level === 'el' ? 'Fuel elements' : 'Canisters'}, by ${cols[si].label || q.label} ${asc ? 'smallest' : 'largest'} first`;
    $('invCanTable').replaceChildren(buildTable(cols, shown, {
      sortable: true, sorted: { i: si, asc },
      onSort: (i) => { const same = state.sort.can && state.sort.can.level === level && state.sort.can.q === q.id && state.sort.can.i === i; state.sort.can = { level, q: q.id, i, asc: same ? !state.sort.can.asc : false }; renderCanisters(); },
      pick: (i) => pick(level === 'el' ? d.elements.can[ids[i]] : ids[i]),
      picked: (i) => state.detail !== null && (level === 'el' ? d.elements.can[ids[i]] : ids[i]) === state.detail,
    }));
    show($('invCanMore'), order.length > shown.length);
    $('invCanMoreNote').textContent = `${intText(shown.length)} of ${intText(order.length)} shown; the CSV and Excel files have them all, with every nuclide.`;
    state.canExport = { cols, order, level, q, ids };
  }

  function reactorsOf(c) {
    const inv = state.inv, d = inv.data;
    if (!inv.fields.reactor) return '';
    const col = d.elements.text[inv.fields.reactor];
    const m = new Map();
    for (let e = d.canisters.el0[c], end = e + d.canisters.nEl[c]; e < end; e++) { if (!inv.picks(e)) continue; const r = col.values[col.codes[e]]; m.set(r, (m.get(r) || 0) + 1); }
    return [...m].sort((a, b) => b[1] - a[1]).map(([r, n]) => (n > 1 ? `${r} ×${n}` : r)).join(', ');
  }

  /* A field of the file as a heading: decay_heat_W -> Decay heat (W). */
  const fieldLabel = (k) => { const s = String(k).replace(/_W$/, ' (W)').replace(/_/g, ' ').trim(); return s.charAt(0).toUpperCase() + s.slice(1); };

  /**
   * Every canister (or fuel element) of the canisters chosen, in the
   * table's order, with all it is: the file's fields, its decay heat and
   * activity, and every nuclide in the unit and at the time shown.
   */
  function canTable() {
    const x = state.canExport;
    if (!x) return null;
    const inv = state.inv, d = inv.data, unit = state.settings.unit, w = timeWords();
    const ids = x.order.map((i) => x.ids[i]);
    const nuc = nuclideList('all', 'chain');
    const f = nuc.map((k) => factorOf(inv.nuclides[k].name));
    const tail = [{ label: `Decay heat from the nuclides, ${w} (W)`, fmt: 'fixed', width: 20 }, { label: `Activity, ${w} (Bq)`, fmt: 'sci', width: 16 },
      ...nuc.map((k) => ({ label: `${inv.nuclides[k].name} (${unit})`, fmt: 'sci', width: 13 }))];
    const columns = [], rows = [];
    if (x.level === 'el') {
      const at = inv.elementsAt(system(), targetMs(), halfKey());
      const text = Object.entries(d.elements.text), num = Object.entries(d.elements.num);
      columns.push({ label: 'Element', width: 26 }, { label: 'Canister', width: 10 }, ...text.map(([k]) => ({ label: fieldLabel(k), width: 18 })),
        { label: 'Planned', width: 9 }, { label: 'Packed', fmt: 'date', width: 11 }, ...num.map(([k]) => ({ label: fieldLabel(k), fmt: 'fixed', width: 15 })), ...tail);
      for (const e of ids) {
        const c = d.elements.can[e];
        rows.push([d.elements.id[e], d.canisters.id[c], ...text.map(([, col]) => (col.codes[e] >= 0 ? col.values[col.codes[e]] : null)),
          /^plan/i.test(d.elements.id[e]) ? 'yes' : '', d.canisters.date[c], ...num.map(([, a]) => a[e]), at.heat[e], at.activity[e],
          ...nuc.map((k, j) => at.amounts[e * inv.N + k] * f[j])]);
      }
    } else {
      const at = canAt();
      const text = Object.entries(d.canisters.text), num = Object.keys(d.canisters.num).map((k) => [k, inv.canNum(k)]);
      columns.push({ label: 'Canister', width: 10 }, { label: 'Type', width: 7 }, { label: 'Packed', fmt: 'date', width: 11 }, { label: 'Fuel elements', fmt: 'int', width: 9 },
        ...(inv.nPlanned ? [{ label: 'Of them planned', fmt: 'int', width: 10 }] : []),
        { label: 'Reactors', width: 44 }, ...text.map(([k]) => ({ label: fieldLabel(k), width: 16 })), ...num.map(([k]) => ({ label: fieldLabel(k), fmt: 'fixed', width: 15 })), ...tail);
      for (const c of ids) {
        const amounts = nuc.map((k, j) => { let s = 0; for (let p = 0; p < inv.P; p++) s += at.amounts[(c * inv.P + p) * inv.N + k]; return s * f[j]; });
        rows.push([d.canisters.id[c], typeName(inv.canType[c]) || '', d.canisters.date[c], inv.nIn(c), ...(inv.nPlanned ? [inv.nIn(c, 'planned') * (fuel() === 'discharged' ? 0 : 1)] : []), reactorsOf(c),
          ...text.map(([, col]) => (col.codes[c] >= 0 ? col.values[col.codes[c]] : null)), ...num.map(([, a]) => a[c]), at.heat[c], at.activity[c], ...amounts]);
      }
    }
    return { level: x.level, title: `${x.level === 'el' ? 'Fuel elements' : 'Canisters'}${selType() ? ` (${selType()})` : ''}, ${w}; amounts in ${unit}${fuelWords() ? `; ${fuelWords()}` : ''}`, columns, rows };
  }

  /** A table's rows for a CSV file: dates as text. */
  const tableCsv = (t) => [t.columns.map((c) => c.label), ...t.rows.map((r) => r.map((v, j) => (t.columns[j].fmt === 'date' ? (Number.isFinite(v) ? dateText(v) : '') : v)))];

  function canCsv() {
    const t = canTable();
    if (t) saveCsv(`${baseName()}-${t.level === 'el' ? 'elements' : 'canisters'}-${year() ?? 'packed'}.csv`, csvHead(t.title), tableCsv(t));
  }
  function canExcel(button) {
    const t = canTable();
    if (t) saveExcel(`${baseName()}-${t.level === 'el' ? 'elements' : 'canisters'}-${year() ?? 'packed'}.xlsx`, [{ name: t.level === 'el' ? 'Fuel elements' : 'Canisters', columns: t.columns, rows: t.rows }], button, [['Table', t.title]]);
  }

  /* ---- the canister picked ---- */
  function pick(c) {
    state.detail = c;
    renderCanisters();
    const card = $('invDetail');
    if (card && !card.hidden) card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function renderDetail() {
    const card = $('invDetail');
    const c = state.detail;
    if (c === null || !state.inv || c >= state.inv.nCan) { show(card, false); return; }
    show(card, true);
    const inv = state.inv, d = inv.data, th = theme();
    const at = canAt();
    const type = typeName(inv.canType[c]);
    $('invDetailTitle').textContent = `Canister ${d.canisters.id[c]}`;
    const facts = [
      ['Type', type || '–'], ['Packed', d.canisters.dateText[c] || '–'], ['Fuel elements', String(d.canisters.nEl[c])],
    ];
    const nPl = inv.nIn(c, 'planned');
    if (inv.nPlanned) facts.push(['Planned', `${nPl} of them`]);
    if (fuel() !== 'all') facts.push(['Shown', `its ${inv.nIn(c)} ${fuel()} elements`]);
    if (d.canisters.num.decay_heat_W) facts.push(['Decay heat when packed', `${numText(d.canisters.num.decay_heat_W[c], 4)} W`]);
    if (d.canisters.num.declared_heat_W) facts.push(['Declared', `${numText(d.canisters.num.declared_heat_W[c], 4)} W`]);
    facts.push([`From the nuclides, ${timeWords()}`, `${numText(at.heat[c], 4)} W`], [`Activity, ${timeWords()}`, `${numText(at.activity[c])} Bq`]);
    for (const [k, val] of Object.entries(d.canisters.num)) if (!/^(decay_heat_W|declared_heat_W)$/.test(k)) facts.push([k.replace(/_/g, ' '), numText(val[c], 4)]);
    for (const [k, col] of Object.entries(d.canisters.text)) facts.push([k.replace(/_/g, ' '), col.codes[c] >= 0 ? col.values[col.codes[c]] : '–']);
    $('invDetailFacts').replaceChildren(...facts.map(([a, b]) => h('div', null, h('dt', { text: a }), h('dd', { text: b }))));

    /* Its elements, every one, the planned ones said. */
    const els = inv.elementsOf(c, 'all');
    const textCols = Object.entries(d.elements.text);
    const numCols = Object.entries(d.elements.num);
    const cols = [{ label: 'Element', cls: 'text', text: (e) => d.elements.id[e] },
      ...(inv.nPlanned ? [{ label: 'planned', cls: 'text', text: (e) => (inv.planned[e] ? 'yes' : '') }] : []),
      ...textCols.map(([k, col]) => ({ label: k.replace(/_/g, ' '), cls: 'text', text: (e) => (col.codes[e] >= 0 ? col.values[col.codes[e]] : '') })),
      ...numCols.map(([k, a]) => ({ label: k.replace(/_W$/, ' (W)').replace(/_/g, ' '), html: (e) => numHtml(a[e], 4) }))];
    $('invDetailElements').replaceChildren(buildTable(cols, els));

    /* Its nuclides against the average canister of its type. */
    const same = inv.select(inv.canType[c]);
    const avg = inv.sumOver(at.amounts, same);
    const mine = inv.sumOver(at.amounts, [c]);
    const ks = nuclideList('all', 'chain');
    const ratio = ks.map((k) => (avg.total[k] > 0 ? mine.total[k] / (avg.total[k] / same.length) : null));
    plot('invChartDetail', [
      { type: 'scatter', mode: 'markers', name: 'this canister / the average', x: ks.map((k) => inv.nuclides[k].name), y: ratio, marker: { size: 7, color: typeColour(type, th) }, hovertemplate: '%{x}: <b>%{y:.3f}</b> of the average<extra></extra>', showlegend: false },
    ], {
      margin: { l: 56, r: 10, t: 10, b: 70 },
      xaxis: { type: 'category', tickangle: -60, tickfont: { size: 10 } },
      yaxis: { type: 'log', title: { text: `of the average ${type || ''} canister` } },
      shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 1, y1: 1, line: { color: th.ref, width: 1 } }],
    });
    $('invDetailNote').textContent = `Each nuclide of canister ${d.canisters.id[c]} over the average of the ${intText(same.length)} ${type || ''} canisters, ${timeWords()}. Above 1: more than the average.`;
  }

  function stepDetail(by) {
    if (state.detail === null) return;
    const ex = state.canExport;
    if (!ex) return;
    const d = state.inv.data;
    const cans = ex.level === 'el' ? [...new Set(ex.order.map((i) => d.elements.can[elementsOf(selection())[i]]))] : ex.order.map((i) => selection()[i]);
    const at = cans.indexOf(state.detail);
    const next = cans[Math.min(cans.length - 1, Math.max(0, (at < 0 ? 0 : at + by)))];
    if (next !== undefined) pick(next);
  }

  /* ---------------------------------------------------------------------
     Over time
     --------------------------------------------------------------------- */
  function renderTime() {
    const inv = state.inv, th = theme(), v = state.view;
    $('invTimeOf').value = v.timeOf;
    $('invTimeQty').value = v.timeQty;
    $('invTimeTo').value = v.timeTo;
    show($('invTimeCanBox'), v.timeOf === 'one');
    if (v.timeOf === 'one' && $('invTimeCan') !== document.activeElement) $('invTimeCan').value = v.timeCan;
    const sub = subject(v.timeOf, v.timeCan);
    const y0 = year() ?? minYear();
    if (!['Bq', 'mol', 'g', 'heat'].includes(v.timeQty)) v.timeQty = 'Bq';
    $('invTimeQty').value = v.timeQty;
    const unit = v.timeQty === 'heat' ? 'W' : v.timeQty;
    const QWORD = { Bq: 'Activity', mol: 'Amount', g: 'Mass', heat: 'Decay heat' };
    $('invTimeTitle').textContent = `${QWORD[v.timeQty]} of ${sub.label}, from ${y0}`;
    if (sub.error) { $('invTimeSub').textContent = sub.error; Plotly.purge($('invChartTime')); $('invTimeNote').textContent = ''; return; }
    const sys = system();
    const at = canAtYear(y0);
    const n0 = inv.fullSum(at, sub.sel);
    for (let i = 0; i < n0.length; i++) n0[i] /= sub.per;
    const tEnd = Number(v.timeTo) || 1e6;
    const times = [];
    for (let e = 0; e <= Math.log10(tEnd) + 1e-9; e += 1 / 24) times.push(10 ** e);
    const res = M.decayTimes(sys, n0, times.map((t) => t * M.YEAR_S));
    const N = res.N;
    const eff = M.effectiveEnergy(sys);
    const listed = inv.nuclides.filter((u) => sys.index.has(u.name));
    const curve = (u, Nt) => {
      const i = sys.index.get(u.name);
      if (v.timeQty === 'heat') return Nt[i] * sys.lambda[i] * eff[i] * M.NA * M.MEV_J;
      return Nt[i] * M.perMole(sys, i, unit);
    };
    const series = listed.map((u) => ({ u, y: N.map((Nt) => curve(u, Nt)) }));
    const total = v.timeQty === 'heat' ? N.map((Nt) => M.heatOf(sys, Nt)) : N.map((_, j) => series.reduce((s, x) => s + x.y[j], 0));
    /* The eight that matter most: each one's largest share of the total over the span. */
    const top = series.map((s) => ({ s, w: Math.max(...s.y.map((x, j) => (total[j] > 0 ? x / total[j] : 0))) }))
      .sort((a, b) => b.w - a.w).slice(0, 8).map((x) => x.s);
    /* What has decayed away comes out of the solver as a remnant of about
       1e-13 of the largest value: not drawn. */
    const floor = 1e-12 * Math.max(...total, ...top.flatMap((s) => s.y));
    const shown = (x) => (x > floor ? x : null);
    const traces = top.map((s, i) => ({
      type: 'scatter', mode: 'lines', name: s.u.name, x: times, y: s.y.map(shown),
      line: { color: th.s[i], width: 2 }, legendgroup: s.u.name,
      hovertemplate: `${s.u.name}: <b>%{y:.3e} ${unit}</b> after %{x:.3g} years<extra></extra>`,
    }));
    traces.push({ type: 'scatter', mode: 'lines', name: v.timeQty === 'heat' ? 'all of it' : `all ${listed.length}`, x: times, y: total.map(shown), line: { color: th.ref, width: 2.5 }, hovertemplate: `all: <b>%{y:.3e} ${unit}</b> after %{x:.3g} years<extra></extra>` });
    /* The planned elements' part of the total, dotted, when the whole is shown. */
    let totalP = null;
    if (fuel() === 'all' && inv.nPlanned > 0) {
      const n0P = inv.fullSum(inv.canistersAt(sys, M.yearMs(y0), halfKey(), 'planned'), sub.sel);
      for (let i = 0; i < n0P.length; i++) n0P[i] /= sub.per;
      const NP = M.decayTimes(sys, n0P, times.map((t) => t * M.YEAR_S)).N;
      totalP = v.timeQty === 'heat' ? NP.map((Nt) => M.heatOf(sys, Nt)) : NP.map((Nt) => listed.reduce((s2, u) => s2 + curve(u, Nt), 0));
      if (totalP.some((x) => x > 0)) {
        traces.push({ type: 'scatter', mode: 'lines', name: 'of it in planned elements', x: times, y: totalP.map(shown), line: { color: th.ref, width: 2, dash: 'dot' }, hovertemplate: `planned elements: <b>%{y:.3e} ${unit}</b> after %{x:.3g} years<extra></extra>` });
      } else totalP = null;
    }

    /* PSAR beside it: only its values of the same kind as the line drawn.
       Another kind drawn takes the same document's of that kind. */
    const choices = refsForSubject(sub);
    show($('invTimeRefBox'), havePsar());
    if (v.timeRef && !choices.some((r) => r.id === v.timeRef)) {
      const doc = v.timeRef.split(':')[0];
      v.timeRef = (choices.find((r) => r.id.split(':')[0] === doc) || {}).id || '';
    }
    const opts = [{ id: '', label: choices.length ? 'nothing' : `nothing: PSAR has none of ${sub.label}` }, ...choices.map((r) => ({ id: r.id, label: refName(r) }))];
    fillSelect($('invTimeRef'), opts, v.timeRef);
    const ref = choices.find((r) => r.id === v.timeRef);
    const notes = [];
    let refExport = null;
    if (ref) {
      const ry = Math.max(ref.year, y0);
      const rv = refValues(ref, ry, 'mol');
      const rsys = rv.sys;
      const tStart = ry - y0;
      const rtimes = times.filter((t) => t >= tStart);
      const rres = M.decayTimes(rsys, rv.all, rtimes.map((t) => (t - tStart) * M.YEAR_S));
      const reff = M.effectiveEnergy(rsys);
      const rcurve = (name, Nt) => {
        const i = rsys.index.get(name);
        if (i === undefined) return null;
        if (v.timeQty === 'heat') return Nt[i] * rsys.lambda[i] * reff[i] * M.NA * M.MEV_J;
        return Nt[i] * M.perMole(rsys, i, unit);
      };
      top.forEach((s, i) => {
        if (!ref.values.has(s.u.name)) return;
        traces.push({ type: 'scatter', mode: 'lines', name: `${s.u.name}, PSAR`, x: rtimes, y: rres.N.map((Nt) => shown(rcurve(s.u.name, Nt))), line: { color: th.s[i], width: 1.5, dash: 'dash' }, legendgroup: s.u.name, showlegend: false, hovertemplate: `${s.u.name}, PSAR: <b>%{y:.3e} ${unit}</b> after %{x:.3g} years<extra></extra>` });
      });
      const rtotal = v.timeQty === 'heat' ? rres.N.map((Nt) => M.heatOf(rsys, Nt)) : rres.N.map((Nt) => [...ref.values.keys()].reduce((s, name) => s + (rcurve(name, Nt) || 0), 0));
      traces.push({ type: 'scatter', mode: 'lines', name: `${ref.label}`, x: rtimes, y: rtotal.map(shown), line: { color: th.ref, width: 2, dash: 'dash' }, hovertemplate: `PSAR, all: <b>%{y:.3e} ${unit}</b> after %{x:.3g} years<extra></extra>` });
      const from = ref.year < y0 ? `given for 1 January ${ref.year} and brought to ${y0} by decay and ingrowth through the whole chains`
        : ref.year > y0 ? `given for ${ref.year}, so its line begins ${ref.year - y0} years in` : `given for ${ref.year}`;
      notes.push(`Dashed: ${refName(ref)}, ${from}, with the same half-lives as this inventory, its becquerels made moles with ${psarHalfLives() ? 'its own half-lives (Table D-1)' : 'those half-lives'}; from there both decay alike${ref.values.size < listed.length ? `. PSAR’s total is of its ${ref.values.size} nuclides` : ''}.`);
      refExport = { label: `${ref.label} (${ref.where}, ${ref.year})`, times: rtimes, total: rtotal, series: [...ref.values.keys()].map((name) => ({ name, y: rres.N.map((Nt) => rcurve(name, Nt)) })) };
    }
    $('invTimeSub').textContent = `${unit}${sub.total ? '' : ' per canister'}; years after 1 January ${y0}`;
    plot('invChartTime', traces, {
      xaxis: { type: 'log', title: { text: `years after 1 January ${y0}` } },
      yaxis: { type: 'log', title: { text: `${QWORD[v.timeQty].toLowerCase()} (${unit})` } },
      legend: { orientation: 'v', x: 1.01, y: 1, yanchor: 'top', xanchor: 'left' },
      margin: { r: 10, t: 12 },
    });
    if (v.timeQty === 'heat') notes.unshift('A nuclide’s line counts its short-lived daughters with it; the black line is the heat of everything, from ICRP 107’s energies.');
    else notes.unshift(`The eight nuclides that make the largest share of the total at some time in the span, and the total of all ${listed.length}.`);
    if (totalP) notes.splice(1, 0, `Dotted: the part of the total in the planned elements (named PLAN…, the reactors’ forecast), ${shareText(totalP[0], total[0])} of it at the start.`);
    if (fuelWords()) notes.splice(1, 0, `Of the ${fuelWords()}.`);
    $('invTimeNote').textContent = notes.join(' ');
    state.timeExport = { times, top, series, total, totalP, unit, sub, y0, what: QWORD[v.timeQty], ref: refExport };
  }

  /** Every nuclide over time, not only the eight drawn. */
  function timeTable() {
    const x = state.timeExport;
    if (!x) return null;
    const per = `${x.unit}${x.sub.total ? '' : ' per canister'}`;
    const columns = [{ label: `Years after 1 January ${x.y0}`, width: 14 }, { label: 'Year', width: 10 }, { label: `Total (${per})`, fmt: 'sci', width: 18 },
      ...(x.totalP ? [{ label: `Of it in planned elements (${per})`, fmt: 'sci', width: 22 }] : []),
      ...x.series.map((s) => ({ label: `${s.u.name} (${x.unit})`, fmt: 'sci', width: 13 }))];
    const rows = x.times.map((t, j) => [t, x.y0 + t, x.total[j], ...(x.totalP ? [x.totalP[j]] : []), ...x.series.map((s) => s.y[j])]);
    return { title: `${x.what} of ${x.sub.label}, from 1 January ${x.y0}, ${per}${fuelWords() ? `, ${fuelWords()}` : ''}`, columns, rows };
  }
  function timeCsv() {
    const t = timeTable();
    if (t) saveCsv(`${baseName()}-over-time-${state.timeExport.y0}.csv`, csvHead(t.title), tableCsv(t));
  }
  function timeExcel(button) {
    const t = timeTable();
    if (!t) return;
    const x = state.timeExport;
    const sheets = [{ name: 'Over time', columns: t.columns, rows: t.rows }];
    if (x.ref) {
      sheets.push({
        name: 'PSAR beside it',
        columns: [{ label: `Years after 1 January ${x.y0}`, width: 14 }, { label: 'Year', width: 10 }, { label: `Total (${x.unit})`, fmt: 'sci', width: 16 },
          ...x.ref.series.map((s) => ({ label: `${s.name} (${x.unit})`, fmt: 'sci', width: 13 }))],
        rows: x.ref.times.map((tt, j) => [tt, x.y0 + tt, x.ref.total[j], ...x.ref.series.map((s) => s.y[j])]),
      });
    }
    saveExcel(`${baseName()}-over-time-${x.y0}.xlsx`, sheets, button, [['Table', t.title], ...(x.ref ? [['PSAR beside it', x.ref.label]] : [])]);
  }

  /* ---------------------------------------------------------------------
     Compare with PSAR
     --------------------------------------------------------------------- */
  function renderPsar() {
    /* What each table shows, kept for the Excel file. */
    state.psarExport = {};
    const has = havePsar();
    show($('invPsarEmpty'), !has);
    show($('invPsar'), has);
    if (!has) return;
    $('invPsarHow').textContent = `This inventory${fuelWords() ? `, ${fuelWords()},` : ''} beside PSAR’s${fuelWords() ? ', all of its fuel' : ''}, at one time and in one unit. ${psarMolesWords()}`;
    const th = theme();
    const inv = state.inv;
    /* The comparison needs one time for both. Until a reference is chosen,
       the best one open is taken: one that can be brought to the year shown,
       the workbook's before the report's, all canisters before one type. */
    const averages = refs().filter((r) => r.kind === 'average');
    const v = state.view;
    const rank = (r) => (year() !== null && year() >= r.year ? 0 : 100) + ({ workbook: 0, report: 10 }[r.id.split(':')[0]] ?? 20) + (r.scope === 'all' ? 0 : 1);
    if (!v.refChosen || !averages.some((r) => r.id === v.ref)) v.ref = (averages.slice().sort((a, b) => rank(a) - rank(b))[0] || {}).id || '';
    fillSelect($('invRef'), averages.map((r) => ({ id: r.id, label: refName(r) })), v.ref);
    const ref = averages.find((r) => r.id === v.ref) || null;
    const warn = $('invPsarTime');
    const needYear = inv && ref ? Math.max(minYear(), ref.year) : null;
    const sameTime = !!(inv && ref && year() !== null && year() >= ref.year);
    if (inv && year() === null && ref) {
      warn.replaceChildren(document.createTextNode(`The inventory is shown as packed, each canister at its own date, and ${ref.label} holds for ${ref.year}: they can only be compared at one time. `),
        h('button', { type: 'button', class: 'inv-btn small', onclick: () => setYear(needYear), text: `Show both in ${needYear}` }),
        document.createTextNode(needYear !== ref.year ? ` (the first 1 January every canister has been packed by${ref.year > minYear() ? ', and PSAR’s own year' : ''}).` : '.'));
      show(warn, true);
    } else if (inv && ref && !sameTime) {
      warn.replaceChildren(document.createTextNode(`${ref.label} holds for ${ref.year}, after ${year()}, and decay does not run backwards: `),
        h('button', { type: 'button', class: 'inv-btn small', onclick: () => setYear(ref.year), text: `Show both in ${ref.year}` }),
        document.createTextNode(' or compare with another of PSAR’s canisters.'));
      show(warn, true);
    } else show(warn, false);
    show($('invRatioCard'), !!(inv && ref));
    for (const id of ['invRatioSub', 'invRatioKey', 'invChartRatio', 'invRatioNote', 'invRatioTable']) show($(id), sameTime);
    if (sameTime) renderRatio(ref, th);
    show($('invCatCard'), !!inv && refs().some((r) => r.kind === 'total'));
    if (inv && refs().some((r) => r.kind === 'total')) renderCategories(th);
    const sim = simulation();
    show($('invReactorCard'), !!(inv && sim));
    show($('invCanCmpCard'), !!inv);
    show($('invDepCard'), !!(inv && sim));
    show($('invHeatCmpCard'), !!(inv && sim));
    if (inv) renderCanCmp(sim, th);
  }

  function setYear(y) {
    state.settings.at = 'year';
    state.settings.year = String(y);
    renderSoon();
  }

  function renderRatio(ref, th) {
    const inv = state.inv;
    const scope = ref.scope === 'all' ? -1 : inv.typeNames.indexOf(ref.scope);
    const sel = inv.select(scope);
    const y = year();
    const unit = state.settings.unit;
    const rv = refValues(ref, y);
    const at = canAt();
    const sums = inv.sumOver(at.amounts, sel);
    const ks = nuclideList('all', 'chain').filter((k) => ref.values.has(inv.nuclides[k].name));
    const rows = ks.map((k) => {
      const name = inv.nuclides[k].name;
      const f = factorOf(name);
      const mine = sums.total[k] / sel.length * f;
      const theirs = rv.values.get(name);
      const s = M.summary(inv.perCanister(at.amounts, sel, k));
      return { k, name, mine, theirs, r: theirs > 0 ? mine / theirs : NaN, p5: theirs > 0 ? s.p5 * f / theirs : NaN, p95: theirs > 0 ? s.p95 * f / theirs : NaN, low: ref.low ? ref.low.get(name) : undefined, high: ref.high ? ref.high.get(name) : undefined };
    });
    $('invRatioSub').textContent = `${intText(sel.length)} ${ref.scope === 'all' ? '' : `${ref.scope} `}canisters of this inventory, averaged, over ${ref.label} (${ref.where}), both in ${y}; in ${unit}, half-lives ${$('invHalf').selectedOptions[0].textContent}.`;
    state.psarExport.ratio = { rows, unit, title: $('invRatioSub').textContent };
    const yCat = rows.map((r) => r.name).reverse();
    const R = (arr) => arr.slice().reverse();
    const traces = [];
    /* The scale runs from a tenth to ten times PSAR's; a ratio beyond it is
       an arrow at the edge, its value in the hover and the table. */
    const LO = 0.1, HI = 10;
    const clip = (x) => Math.min(HI, Math.max(LO, x));
    const key = [];
    /* PSAR's spread, low to high burnup. */
    const bx = [], by = [];
    for (const r of rows) if (Number.isFinite(r.low) && Number.isFinite(r.high)) { bx.push(clip(1 + Math.min(r.low, r.high)), clip(1 + Math.max(r.low, r.high)), null); by.push(r.name, r.name, null); }
    if (bx.length) {
      traces.push({ type: 'scatter', mode: 'lines', x: bx, y: by, line: { color: th.band, width: 10 }, hoverinfo: 'skip' });
      key.push(h('span', null, h('i', { class: 'band' }), 'PSAR’s low to high burnup canister'));
    }
    const wx = [], wy = [];
    for (const r of rows) if (r.p95 > 0) { wx.push(clip(Math.max(r.p5, 1e-9)), clip(r.p95), null); wy.push(r.name, r.name, null); }
    traces.push({ type: 'scatter', mode: 'lines', x: wx, y: wy, line: { color: th.s[0], width: 2 }, opacity: 0.55, hoverinfo: 'skip' });
    key.push(h('span', null, h('i', { class: 'line', style: `border-color:${th.s[0]};opacity:.55` }), 'this inventory’s canisters, 5th to 95th percentile'));
    const symbol = (r) => (r.r > HI ? 'triangle-right' : r.r < LO ? 'triangle-left' : 'circle');
    traces.push({
      type: 'scatter', mode: 'markers', x: R(rows.map((r) => (r.r > 0 ? clip(r.r) : null))), y: yCat,
      marker: { size: 10, color: th.s[0], symbol: R(rows.map(symbol)), line: { color: th.bg, width: 1.5 } },
      customdata: R(rows.map((r) => [numText(r.r), numText(r.mine), numText(r.theirs), Number.isFinite(r.low) ? `${(r.low * 100).toFixed(1)} % to +${(r.high * 100).toFixed(1)} %` : '–'])),
      hovertemplate: `%{y}: <b>%{customdata[0]}</b> of PSAR’s<br>this inventory %{customdata[1]} ${unit}<br>PSAR %{customdata[2]} ${unit}<br>PSAR’s spread %{customdata[3]}<extra></extra>`,
    });
    key.push(h('span', null, h('i', { class: 'dot', style: `background:${th.s[0]}` }), 'this inventory’s average over PSAR’s'));
    if (rows.some((r) => r.r > HI || (r.r > 0 && r.r < LO))) key.push(h('span', null, h('b', { text: '◀ ▶' }), 'beyond the scale: the value is in the table'));
    const height = Math.max(360, rows.length * 18 + 80);
    $('invChartRatio').style.height = `${height}px`;
    plot('invChartRatio', traces, {
      margin: { l: 70, r: 14, t: 50, b: 10 }, showlegend: false,
      xaxis: { type: 'log', range: [Math.log10(LO) - 0.04, Math.log10(HI) + 0.04], side: 'top', title: { text: 'this inventory / PSAR', standoff: 6 },
        tickvals: [0.1, 0.2, 0.5, 1, 2, 5, 10], ticktext: ['0.1', '0.2', '0.5', '1', '2', '5', '10'] },
      yaxis: { type: 'category', categoryorder: 'array', categoryarray: yCat, dtick: 1, tickfont: { size: 11 } },
      shapes: [{ type: 'line', x0: 1, x1: 1, y0: 0, y1: 1, yref: 'paper', line: { color: th.ref, width: 1.2 } }],
    });
    $('invRatioKey').replaceChildren(...key);
    const within = rows.filter((r) => Number.isFinite(r.low) && r.r >= 1 + Math.min(r.low, r.high) && r.r <= 1 + Math.max(r.low, r.high)).length;
    const withBand = rows.filter((r) => Number.isFinite(r.low)).length;
    const far = rows.filter((r) => r.r > 0 && (r.r > 2 || r.r < 0.5)).map((r) => `${r.name} ${numText(r.r)}`);
    const notes = [];
    if (withBand) notes.push(`${within} of ${withBand} nuclides lie within PSAR’s own spread.`);
    if (far.length) notes.push(`More than twice apart: ${far.join(', ')}.`);
    const zero = rows.filter((r) => !(r.theirs > 0)).map((r) => r.name);
    if (zero.length) notes.push(`PSAR has none of ${zero.join(', ')}.`);
    if (ref.parts && ref.parts.has('control_rods')) notes.push('PSAR’s PWR canister counts its control rods, which this inventory does not list as a part.');
    $('invRatioNote').textContent = notes.join(' ');
    $('invRatioTable').replaceChildren(buildTable([
      { label: 'Nuclide', cls: 'text', text: (r) => r.name },
      { label: `this inventory (${unit})`, html: (r) => numHtml(r.mine) },
      { label: `PSAR (${unit})`, html: (r) => numHtml(r.theirs) },
      { label: 'ratio', html: (r) => numHtml(r.r), cls: (r) => (r.r > 2 || r.r < 0.5 ? 'hi' : null) },
      { label: '5th pct / PSAR', html: (r) => numHtml(r.p5) },
      { label: '95th pct / PSAR', html: (r) => numHtml(r.p95) },
      { label: 'PSAR low BU', html: (r) => (Number.isFinite(r.low) ? `${(r.low * 100).toFixed(1)}${NNBSP}%` : '–') },
      { label: 'PSAR high BU', html: (r) => (Number.isFinite(r.high) ? `${(r.high * 100).toFixed(1)}${NNBSP}%` : '–') },
    ], rows));
  }

  /** Each element's amounts by kind of fuel, as PSAR's tables count them. */
  function renderCategories(th) {
    const inv = state.inv;
    const src = state.psar.workbook || state.psar.report;
    const totals = (src ? src.refs : refs()).filter((r) => r.kind === 'total');
    const reportTotals = state.psar.report ? state.psar.report.refs.filter((r) => r.kind === 'total') : [];
    const y = year();
    const v = state.view;
    const unit = state.settings.unit;
    const choices = [{ id: 'activity', label: 'all nuclides (Bq)' }, ...nuclideList('all', 'chain').map((k) => ({ id: inv.nuclides[k].name, label: inv.nuclides[k].name }))];
    if (!choices.some((c) => c.id === v.catNuc)) v.catNuc = 'activity';
    fillSelect($('invCatNuc'), choices, v.catNuc);
    const isAct = v.catNuc === 'activity';
    const u = isAct ? 'Bq' : unit;
    const sys = system();
    /* This inventory, element by element. */
    const at = inv.elementsAt(sys, targetMs(), halfKey());
    const cat = new Map();
    const elCount = new Map();
    const kSel = isAct ? -1 : inv.nuclides.findIndex((x) => x.name === v.catNuc);
    const fk = kSel >= 0 ? factorOf(v.catNuc, u) : 1;
    let nCounted = 0;
    for (let e = 0; e < inv.nEl; e++) {
      if (!inv.picks(e)) continue;
      nCounted++;
      const name = inv.categoryNames[inv.elCategory[e]];
      const x = isAct ? at.activity[e] : at.amounts[e * inv.N + kSel] * fk;
      cat.set(name, (cat.get(name) || 0) + x);
      elCount.set(name, (elCount.get(name) || 0) + 1);
    }
    /* PSAR, at the same time where it can be. */
    const psar = new Map();
    let pYear = null;
    for (const r of totals) {
      const ry = y !== null && y >= r.year ? y : null;
      const rv = refValues(r, ry, u);
      pYear = rv.year;
      const x = isAct ? [...rv.values.values()].reduce((s, a) => s + a, 0) : rv.values.get(v.catNuc);
      psar.set(r.scope, (psar.get(r.scope) || 0) + (x || 0));
    }
    const pCounts = psarCounts().elements;
    for (const r of reportTotals) if (Number.isFinite(r.count)) pCounts[r.scope] = r.count;
    const order = ['BWR', 'PWR', 'Ågesta', 'Swap MOX', 'Studsvik', 'Rod skeletons'];
    const names = [...new Set([...order.filter((n) => cat.has(n) || psar.has(n)), ...cat.keys(), ...psar.keys()])];
    const rows = names.map((n) => ({ n, el: elCount.get(n), pel: pCounts[n], mine: cat.get(n), theirs: psar.get(n) }));
    const foot = { n: 'All', el: nCounted, pel: Object.values(pCounts).reduce((s, a) => s + (a || 0), 0) || NaN, mine: [...cat.values()].reduce((s, a) => s + a, 0), theirs: [...psar.values()].reduce((s, a) => s + a, 0) };
    state.psarExport.cats = { rows, foot, u, what: isAct ? 'the activity of the nuclides each lists' : v.catNuc, mineWhen: timeWords(), psarWhen: pYear };
    const maxV = Math.max(...rows.map((r) => Math.max(r.mine || 0, r.theirs || 0)));
    const bar = (x) => (x > 0 ? `<span style="width:${Math.max(1, x / maxV * 80)}px"></span>` : '');
    $('invCatTable').replaceChildren(buildTable([
      { label: 'Kind of fuel', cls: 'text', text: (r) => r.n, footText: (r) => r.n },
      { label: 'Elements', html: (r) => (r.el ? intText(r.el) : '–'), footHtml: (r) => intText(r.el) },
      { label: 'PSAR', html: (r) => (r.pel ? intText(r.pel) : '–'), footHtml: (r) => (Number.isFinite(r.pel) ? intText(r.pel) : '–') },
      { label: `this inventory (${u})`, html: (r) => numHtml(r.mine), footHtml: (r) => numHtml(r.mine) },
      { label: '', cls: 'inv-bar-cell', html: (r) => bar(r.mine) },
      { label: `PSAR (${u})`, html: (r) => numHtml(r.theirs), footHtml: (r) => numHtml(r.theirs) },
      { label: 'ratio', html: (r) => (r.mine > 0 && r.theirs > 0 ? numHtml(r.mine / r.theirs) : '–'), footHtml: (r) => (r.theirs > 0 ? numHtml(r.mine / r.theirs) : '–') },
    ], rows, { foot }));
    $('invCatSub').textContent = `Each fuel element in the kind of fuel PSAR’s tables count it in, whichever canister it is in; ${isAct ? 'the activity of the nuclides each lists' : v.catNuc} in ${u}, this inventory ${timeWords()}, PSAR in ${pYear ?? '–'}.`;
    const notes = [];
    if (y === null) notes.push('Choose a year under Time to have both at one time.');
    if (cat.has('Studsvik')) notes.push('PSAR counts Studsvik’s fuel remains apart from its inventory.');
    if (psar.has('Rod skeletons')) notes.push('PSAR’s rod skeletons are BWR fuel left in skeletons and magazines; this inventory counts such fuel with its reactor.');
    $('invCatNote').textContent = notes.join(' ');
  }

  function renderCanCmp(sim, th) {
    const inv = state.inv, d = inv.data;
    const pc = psarCounts();
    const fileHeat = inv.canNum('decay_heat_W'), declared = inv.canNum('declared_heat_W');
    const types = ['all', ...inv.typeNames];
    const row = (t) => {
      const sel = t === 'all' ? inv.select(-1) : inv.select(inv.typeNames.indexOf(t));
      const sc = sim ? sim.filter((c) => t === 'all' || c.type === t) : null;
      const mean = (a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : NaN);
      const years = Array.from(sel, (c) => d.canisters.date[c]).filter(Number.isFinite);
      return {
        t, n: sel.length, pn: t === 'all' ? pc.canisters.all : pc.canisters[t],
        el: sel.reduce((s, c) => s + inv.nIn(c), 0), pel: sc ? sc.reduce((s, c) => s + c.n, 0) : NaN,
        heat: fileHeat ? mean(Array.from(sel, (c) => fileHeat[c])) : NaN, decl: declared ? mean(Array.from(sel, (c) => declared[c])) : NaN,
        pheat: sc ? mean(sc.map((c) => c.heat)) : NaN,
        span: years.length ? `${new Date(Math.min(...years)).getUTCFullYear()}–${new Date(Math.max(...years)).getUTCFullYear()}` : '–',
        pspan: sc && sc.length ? `${Math.min(...sc.map((c) => c.year))}–${Math.max(...sc.map((c) => c.year))}` : '–',
      };
    };
    const rows = types.map(row);
    state.psarExport.canisters = rows;
    $('invCanCmp').replaceChildren(buildTable([
      { label: '', cls: 'text', text: (r) => r.t },
      { label: 'Canisters', html: (r) => intText(r.n) },
      { label: 'PSAR', html: (r) => (Number.isFinite(r.pn) ? intText(r.pn) : '–') },
      { label: 'Elements', html: (r) => intText(r.el) },
      { label: 'PSAR', html: (r) => (Number.isFinite(r.pel) ? intText(r.pel) : '–') },
      { label: 'Heat (W)', html: (r) => (Number.isFinite(r.heat) ? intText(r.heat) : '–') },
      { label: 'Declared', html: (r) => (Number.isFinite(r.decl) ? intText(r.decl) : '–') },
      { label: 'PSAR', html: (r) => (Number.isFinite(r.pheat) ? intText(r.pheat) : '–') },
      { label: 'Packed', cls: 'text', text: (r) => r.span },
      { label: 'PSAR', cls: 'text', text: (r) => r.pspan },
    ], rows));
    $('invCanCmpNote').textContent = `Heat: the mean decay heat per canister when packed (this inventory, as the file gives it, and declared) or deposited (PSAR’s simulation).${sim ? '' : ' Open PSAR’s workbook for its simulation.'}`;
    if (!sim) return;

    /* Elements by reactor. */
    const rf = inv.fields.reactor;
    const mine = rf ? inv.countBy(rf, inv.select(-1)) : new Map();
    const theirs = new Map();
    for (const c of sim) for (const e of c.elements) theirs.set(e.reactor, (theirs.get(e.reactor) || 0) + 1);
    const names = [...new Set([...mine.keys(), ...theirs.keys()])].sort((a, b) => (theirs.get(b) || mine.get(b) || 0) - (theirs.get(a) || mine.get(a) || 0));
    const rrows = names.map((n) => ({ n, a: mine.get(n) || 0, b: theirs.get(n) || 0 }));
    state.psarExport.reactors = rrows;
    $('invReactorTable').replaceChildren(buildTable([
      { label: 'Reactor', cls: 'text', text: (r) => r.n, footText: () => 'All' },
      { label: 'This inventory', html: (r) => intText(r.a), footHtml: () => intText(rrows.reduce((s, r) => s + r.a, 0)) },
      { label: 'PSAR', html: (r) => intText(r.b), footHtml: () => intText(rrows.reduce((s, r) => s + r.b, 0)) },
      { label: 'Difference', html: (r) => `${r.a - r.b > 0 ? '+' : r.a - r.b < 0 ? '−' : ''}${intText(Math.abs(r.a - r.b))}`, cls: (r) => (Math.abs(r.a - r.b) > 0.1 * Math.max(r.a, r.b) ? 'hi' : null), footHtml: () => { const x = rrows.reduce((s, r) => s + r.a - r.b, 0); return `${x > 0 ? '+' : x < 0 ? '−' : ''}${intText(Math.abs(x))}`; } },
    ], rrows, { foot: {} }));
    $('invReactorNote').textContent = 'PSAR’s count is its encapsulation simulation’s; its reactor codes (R4, F3, KWO …) are read as the reactors’ names.';

    /* Canisters each year: packed (this) against deposited (PSAR). */
    const traces = [];
    const perYear = [];
    for (const t of inv.typeNames) {
      const m = new Map();
      for (const c of inv.select(inv.typeNames.indexOf(t))) { const ms = d.canisters.date[c]; if (Number.isFinite(ms)) { const yy = new Date(ms).getUTCFullYear(); m.set(yy, (m.get(yy) || 0) + 1); } }
      const xs = [...m.keys()].sort((a, b) => a - b);
      traces.push({ type: 'scatter', mode: 'lines', name: `${plain(t)}, packed`, x: xs, y: xs.map((x) => m.get(x)), line: { color: typeColour(t, th), width: 2, shape: 'hvh' }, legendgroup: t });
      const p = new Map();
      for (const c of sim) if (c.type === t) p.set(c.year, (p.get(c.year) || 0) + 1);
      const px = [...p.keys()].sort((a, b) => a - b);
      traces.push({ type: 'scatter', mode: 'lines', name: `${plain(t)}, PSAR deposited`, x: px, y: px.map((x) => p.get(x)), line: { color: typeColour(t, th), width: 2, dash: 'dash', shape: 'hvh' }, legendgroup: t });
      perYear.push({ t, packed: m, deposited: p });
    }
    state.psarExport.years = perYear;
    plot('invChartDep', traces, { xaxis: { title: { text: 'year' }, dtick: 5 }, yaxis: { title: { text: 'canisters' }, rangemode: 'tozero' }, hovermode: 'x unified' });
    $('invDepNote').textContent = 'Solid: this inventory’s canisters packed each year; dashed: PSAR’s deposited each year in its simulation.';

    /* Decay heat per canister: the share of canisters at or below each heat. */
    const ecdf = (vals) => { const v = Float64Array.from(vals).filter(Number.isFinite).sort(); return { x: Array.from(v), y: Array.from(v, (_, i) => (i + 1) / v.length) }; };
    const ht = [];
    if (fileHeat) { const e = ecdf(Array.from(inv.select(-1), (c) => fileHeat[c])); ht.push({ type: 'scatter', mode: 'lines', name: 'decay heat in the file', x: e.x, y: e.y, line: { color: th.s[0], width: 2, shape: 'hv' } }); }
    if (declared) { const e = ecdf(Array.from(inv.select(-1), (c) => declared[c])); ht.push({ type: 'scatter', mode: 'lines', name: 'declared heat', x: e.x, y: e.y, line: { color: th.s[0], width: 2, dash: 'dash', shape: 'hv' } }); }
    { const e = ecdf(sim.map((c) => c.heat)); ht.push({ type: 'scatter', mode: 'lines', name: 'PSAR’s simulation', x: e.x, y: e.y, line: { color: th.ref, width: 2, shape: 'hv' } }); }
    plot('invChartHeatCmp', ht, {
      xaxis: { title: { text: 'decay heat per canister (W)' } }, yaxis: { title: { text: 'share of the canisters at or below' }, range: [0, 1.02], tickformat: '.0%' },
      shapes: [{ type: 'line', x0: LIMIT_W, x1: LIMIT_W, y0: 0, y1: 1, yref: 'paper', line: { color: th.limit, width: 1.5, dash: 'dot' } }],
      hovermode: 'closest',
    });
    $('invHeatCmpNote').textContent = 'Each line rises by one canister at each canister’s heat; a steep rise near 1 700 W means canisters filled close to the limit.';
  }

  /** The comparison's tables as sheets: only those shown. */
  function psarExcel(button) {
    const x = state.psarExport || {};
    const sheets = [];
    const pct = (v) => (Number.isFinite(v) ? v : null);
    if (x.ratio) {
      const u = x.ratio.unit;
      sheets.push({
        name: 'Average canister',
        columns: [{ label: 'Nuclide', width: 10 }, { label: `This inventory (${u})`, fmt: 'sci', width: 18 }, { label: `PSAR (${u})`, fmt: 'sci', width: 14 },
          { label: 'This / PSAR', width: 12 }, { label: '5th percentile / PSAR', width: 20 }, { label: '95th percentile / PSAR', width: 21 },
          { label: 'PSAR, low burnup', fmt: 'pct', width: 16 }, { label: 'PSAR, high burnup', fmt: 'pct', width: 17 }],
        rows: x.ratio.rows.map((r) => [r.name, r.mine, r.theirs, pct(r.r), pct(r.p5), pct(r.p95), pct(r.low), pct(r.high)]),
      });
    }
    if (x.cats) {
      const u = x.cats.u, row = (r) => [r.n, r.el ?? null, Number.isFinite(r.pel) ? r.pel : null, r.mine ?? null, r.theirs ?? null, r.mine > 0 && r.theirs > 0 ? r.mine / r.theirs : null];
      sheets.push({
        name: 'By kind of fuel',
        columns: [{ label: 'Kind of fuel', width: 16 }, { label: 'Elements', fmt: 'int', width: 10 }, { label: 'PSAR elements', fmt: 'int', width: 14 },
          { label: `This inventory, ${x.cats.mineWhen} (${u})`, fmt: 'sci', width: 24 }, { label: `PSAR, ${x.cats.psarWhen} (${u})`, fmt: 'sci', width: 20 }, { label: 'This / PSAR', width: 12 }],
        rows: [...x.cats.rows.map(row), row(x.cats.foot)],
      });
    }
    if (x.reactors) {
      sheets.push({
        name: 'By reactor',
        columns: [{ label: 'Reactor', width: 28 }, { label: 'This inventory', fmt: 'int', width: 14 }, { label: 'PSAR’s simulation', fmt: 'int', width: 18 }, { label: 'Difference', fmt: 'int', width: 12 }],
        rows: x.reactors.map((r) => [r.n, r.a, r.b, r.a - r.b]),
      });
    }
    if (x.canisters) {
      sheets.push({
        name: 'Canisters',
        columns: [{ label: '', width: 6 }, { label: 'Canisters', fmt: 'int', width: 10 }, { label: 'PSAR canisters', fmt: 'int', width: 14 }, { label: 'Elements', fmt: 'int', width: 10 },
          { label: 'PSAR elements', fmt: 'int', width: 14 }, { label: 'Mean decay heat, file (W)', fmt: 'fixed', width: 22 }, { label: 'Mean declared heat (W)', fmt: 'fixed', width: 21 },
          { label: 'PSAR mean decay heat (W)', fmt: 'fixed', width: 23 }, { label: 'Packed', width: 11 }, { label: 'PSAR deposited', width: 14 }],
        rows: x.canisters.map((r) => [r.t, r.n, Number.isFinite(r.pn) ? r.pn : null, r.el, Number.isFinite(r.pel) ? r.pel : null, r.heat, r.decl, r.pheat, r.span, r.pspan]),
      });
    }
    if (x.years && x.years.length) {
      const ys = new Set();
      for (const yv of x.years) { for (const y of yv.packed.keys()) ys.add(y); for (const y of yv.deposited.keys()) ys.add(y); }
      sheets.push({
        name: 'Canisters each year',
        columns: [{ label: 'Year', width: 8 }, ...x.years.flatMap((yv) => [{ label: `${yv.t}, packed`, fmt: 'int', width: 12 }, { label: `${yv.t}, PSAR deposited`, fmt: 'int', width: 20 }])],
        rows: [...ys].sort((a, b) => a - b).map((y) => [y, ...x.years.flatMap((yv) => [yv.packed.get(y) || 0, yv.deposited.get(y) || 0])]),
      });
    }
    if (!sheets.length) { showError(['Nothing to save yet: open an inventory beside PSAR’s files.']); return; }
    saveExcel(`${fileTag()}-psar.xlsx`, sheets, button, x.ratio ? [['Compared', x.ratio.title]] : []);
  }

  /* ---------------------------------------------------------------------
     Raw data: every element or canister chosen, each part and nuclide
     --------------------------------------------------------------------- */
  const RAW_WHAT = { mol: 'moles', Bq: 'becquerels', g: 'grams', W: 'decay heat (W), each nuclide’s with its short-lived daughters’' };
  const PREVIEW_ROWS = 10;
  const isPlanned = (id) => /^plan/i.test(id);

  /** The choices of the Raw data view, kept for each inventory. */
  function rawState() {
    const inv = state.inv;
    if (!state.raw || state.raw.inv !== inv) {
      state.raw = {
        inv, built: false, level: 'el', qty: state.settings.unit, parts: inv.parts.map(() => true), apart: true,
        nucSet: 'all', picked: inv.nuclides.map(() => true), from: null, to: null, reactors: null, fuels: null,
      };
    }
    return state.raw;
  }

  /** The checkboxes that follow the inventory: its parts, nuclides, reactors and fuel types. */
  function buildRawForm(r) {
    const inv = state.inv, d = inv.data;
    const box = (value, label, count, on) => {
      const input = h('input', { type: 'checkbox', value: String(value), 'data-on-change': 'inv:raw' });
      input.checked = on;
      return h('label', null, input, ` ${label}`, count === undefined ? null : h('small', null, ` ${intText(count)}`));
    };
    $('invRawParts').replaceChildren(...inv.parts.map((p, i) => box(i, p.label.toLowerCase(), undefined, r.parts[i])));
    $('invRawNucList').replaceChildren(...nuclideList('all', 'name').map((k) => box(k, inv.nuclides[k].name, undefined, r.picked[k])));
    for (const [field, key, list, pick] of [[inv.fields.reactor, 'reactors', 'invRawReactorList', 'invRawReactorPick'], [inv.fields.fuel, 'fuels', 'invRawFuelList', 'invRawFuelPick']]) {
      const col = field ? d.elements.text[field] : null;
      show($(pick), !!col);
      if (!col) { r[key] = null; continue; }
      const counts = new Int32Array(col.values.length);
      for (let e = 0; e < inv.nEl; e++) if (col.codes[e] >= 0) counts[col.codes[e]]++;
      r[key] = col.values.map(() => true);
      const order = col.values.map((_, i) => i).sort((a, b) => String(col.values[a]).localeCompare(String(col.values[b]), 'sv'));
      $(list).replaceChildren(...order.map((i) => box(i, col.values[i], counts[i], true)));
    }
    document.querySelectorAll('input[name="invRawLevel"]').forEach((el) => { el.checked = el.value === r.level; });
    $('invRawQty').value = r.qty;
    $('invRawApart').value = r.apart ? 'apart' : 'sum';
    $('invRawNuc').value = r.nucSet;
    $('invRawFrom').value = '';
    $('invRawTo').value = '';
    r.built = true;
  }

  function readRaw() {
    if (!state.inv) return;
    const r = rawState();
    r.level = (document.querySelector('input[name="invRawLevel"]:checked') || { value: 'el' }).value;
    r.qty = $('invRawQty').value;
    r.apart = $('invRawApart').value === 'apart';
    r.nucSet = $('invRawNuc').value;
    for (const [key, list] of [['parts', 'invRawParts'], ['picked', 'invRawNucList'], ['reactors', 'invRawReactorList'], ['fuels', 'invRawFuelList']]) {
      if (r[key]) for (const el of $(list).querySelectorAll('input')) r[key][Number(el.value)] = el.checked;
    }
    /* A year, or nothing; anything else is marked and leaves the one before. */
    for (const [key, id] of [['from', 'invRawFrom'], ['to', 'invRawTo']]) {
      const el = $(id), t = el.value.trim();
      const ok = t === '' || /^\d{4}$/.test(t);
      el.setAttribute('aria-invalid', String(!ok));
      if (ok) r[key] = t === '' ? null : Number(t);
    }
    renderSoon();
  }

  function rawToggle(list, on) {
    for (const el of $(list).querySelectorAll('input')) el.checked = on;
    readRaw();
  }

  /** The elements chosen: in the canisters of the type in the bar, packed in the years, of the reactors and fuel types, planned or not. */
  function rawChosen(r) {
    const inv = state.inv, d = inv.data, can = d.canisters;
    const chosen = new Uint8Array(inv.nEl);
    const rc = r.reactors && !r.reactors.every(Boolean) ? d.elements.text[inv.fields.reactor] : null;
    const fc = r.fuels && !r.fuels.every(Boolean) ? d.elements.text[inv.fields.fuel] : null;
    for (const c of selection()) {
      if (r.from !== null || r.to !== null) {
        const y = new Date(can.date[c]).getUTCFullYear();
        if ((r.from !== null && !(y >= r.from)) || (r.to !== null && !(y <= r.to))) continue;
      }
      for (let e = can.el0[c], end = e + can.nEl[c]; e < end; e++) {
        if (!inv.picks(e)) continue;
        if (rc && !(rc.codes[e] >= 0 && r.reactors[rc.codes[e]])) continue;
        if (fc && !(fc.codes[e] >= 0 && r.fuels[fc.codes[e]])) continue;
        chosen[e] = 1;
      }
    }
    return chosen;
  }

  function rawPlan(r) {
    const inv = state.inv;
    const parts = r.parts.map((on, p) => (on ? p : -1)).filter((p) => p >= 0);
    const nuclides = r.nucSet === 'picked' ? nuclideList('all', 'name').filter((k) => r.picked[k]) : nuclideList(r.nucSet, 'name');
    const chosen = rawChosen(r);
    const plan = inv.raw(system(), { chosen, level: r.level, parts, apart: r.apart, nuclides, ms: targetMs(), qty: r.qty });
    let nEl = 0;
    for (let e = 0; e < chosen.length; e++) nEl += chosen[e];
    return { plan, parts, nuclides, chosen, nEl };
  }

  /** A canister's chosen elements by reactor: "Forsmark 1 ×10, Ringhals 1 ×2". */
  function rawReactors(c, chosen) {
    const inv = state.inv, d = inv.data;
    if (!inv.fields.reactor) return '';
    const col = d.elements.text[inv.fields.reactor];
    const m = new Map();
    for (let e = d.canisters.el0[c], end = e + d.canisters.nEl[c]; e < end; e++) if (chosen[e]) { const name = col.values[col.codes[e]]; m.set(name, (m.get(name) || 0) + 1); }
    return [...m].sort((a, b) => b[1] - a[1]).map(([name, n]) => (n > 1 ? `${name} ×${n}` : name)).join(', ');
  }

  /** The table to write: the rows' own fields, then the values (inventory-raw.js's form). */
  function rawTable(r, x, matrix) {
    const inv = state.inv, d = inv.data, rows = x.plan.rows, n = rows.length;
    const col = (label, fmt, width, get) => ({ label, fmt, width, values: Array.from(rows, get) });
    const fields = [];
    if (r.level === 'el') {
      const can = d.elements.can;
      fields.push(col('Element', 'text', 26, (e) => d.elements.id[e]), col('Canister', 'text', 10, (e) => d.canisters.id[can[e]]),
        col('Packed', 'date', 11, (e) => d.canisters.date[can[e]]));
      for (const [k, c] of Object.entries(d.elements.text)) fields.push(col(fieldLabel(k), 'text', 16, (e) => (c.codes[e] >= 0 ? c.values[c.codes[e]] : null)));
      fields.push(col('Planned', 'text', 8, (e) => (isPlanned(d.elements.id[e]) ? 'yes' : '')));
      for (const [k, a] of Object.entries(d.elements.num)) fields.push(col(`${fieldLabel(k)}, in the file`, 'fixed', 15, (e) => a[e]));
    } else {
      const chosenIn = (c) => { let s = 0; for (let e = d.canisters.el0[c], end = e + d.canisters.nEl[c]; e < end; e++) s += x.chosen[e]; return s; };
      fields.push(col('Canister', 'text', 10, (c) => d.canisters.id[c]), col('Type', 'text', 7, (c) => typeName(inv.canType[c]) || ''),
        col('Packed', 'date', 11, (c) => d.canisters.date[c]), col('Elements chosen', 'int', 9, chosenIn),
        ...(inv.nPlanned ? [col('Planned among them', 'int', 9, (c) => { let n = 0; for (let e = d.canisters.el0[c], end = e + d.canisters.nEl[c]; e < end; e++) n += x.chosen[e] & inv.planned[e]; return n; })] : []),
        col('Elements', 'int', 9, (c) => d.canisters.nEl[c]),
        col('Reactors of those chosen', 'text', 40, (c) => rawReactors(c, x.chosen)));
      for (const [k, c] of Object.entries(d.canisters.text)) fields.push(col(fieldLabel(k), 'text', 16, (i) => (c.codes[i] >= 0 ? c.values[c.codes[i]] : null)));
      for (const [k, a] of Object.entries(d.canisters.num)) fields.push(col(`${fieldLabel(k)}, in the file`, 'fixed', 15, (i) => a[i]));
    }
    const labels = x.plan.cols.map((c) => `${inv.nuclides[c.k].name}${c.p >= 0 ? ` ${inv.parts[c.p].label.toLowerCase()}` : ''} (${r.qty})`);
    return { sheet: r.level === 'el' ? 'Fuel elements' : 'Canisters', nRows: n, fields, values: { labels, fmt: 'sci', width: 13, matrix } };
  }

  /** What the values are, for the About sheet and the CSV file's head. */
  function rawAbout(r, x) {
    const inv = state.inv, d = inv.data;
    const listed = (key, field) => {
      if (!r[key] || r[key].every(Boolean)) return 'all';
      const values = d.elements.text[field].values;
      return r[key].map((on, i) => (on ? values[i] : null)).filter((v) => v !== null).join(', ') || 'none';
    };
    const nuc = { all: 'all in the file', actinides: 'actinides and their daughters', products: 'fission and activation products' }[r.nucSet];
    return [
      ['Saved from', 'Canister Inventory, kvotab.se/canister_inventory.html'],
      ['Saved', `${new Date().toISOString().slice(0, 16).replace('T', ' ')} UTC`],
      ['Inventory', state.invFile ? state.invFile.name : '–'],
      ['Rows', r.level === 'el' ? `each fuel element chosen: ${x.plan.rows.length}` : `each canister holding any element chosen: ${x.plan.rows.length}, with the ${x.nEl} elements chosen in them summed`],
      ['Values', `${RAW_WHAT[r.qty]}; a column for each ${r.apart ? 'part and nuclide' : 'nuclide, the parts summed'}`],
      ['Parts', x.parts.map((p) => inv.parts[p].label.toLowerCase()).join(', ')],
      ['Nuclides', nuc || x.nuclides.map((k) => inv.nuclides[k].name).join(', ')],
      ['Time', year() === null ? 'as packed: the file’s own values, each canister at its own packing date' : `1 January ${year()}: every canister decayed to it from its packing date`],
      ['Half-lives', halfWords()],
      ['Canisters', selType() ? `${selType()} only` : 'all'],
      ['Packed', r.from === null && r.to === null ? 'any year' : `${r.from ?? 'the first'} to ${r.to ?? 'the last'}`],
      ['Fuel', fuelWords() || (inv.nPlanned ? 'all elements, discharged and planned (PLAN…)' : 'all elements')],
      ['Reactors', inv.fields.reactor ? listed('reactors', inv.fields.reactor) : '–'],
      ['Fuel types', inv.fields.fuel ? listed('fuels', inv.fields.fuel) : '–'],
      ['Fields', 'as the file gives them; its heats are at packing'],
      ['Decay', decayWords()],
    ];
  }

  function renderRaw() {
    const r = rawState(), inv = state.inv;
    if (!r.built) buildRawForm(r);
    show($('invRawNucPick'), r.nucSet === 'picked');
    const count = (key) => (!r[key] ? '' : r[key].every(Boolean) ? `all ${r[key].length}` : `${r[key].filter(Boolean).length} of ${r[key].length}`);
    $('invRawNucSum').textContent = `Nuclides picked: ${count('picked')}`;
    $('invRawReactorSum').textContent = `Reactors: ${count('reactors')}`;
    $('invRawFuelSum').textContent = `Fuel types: ${count('fuels')}`;
    $('invRawSub').textContent = `${year() === null ? 'As packed: the file’s own values, each canister at its packing date' : `In ${year()}: each canister decayed to 1 January ${year()} from its packing date`}; half-lives ${$('invHalf').selectedOptions[0].textContent}; ${selType() ? `${selType()} canisters only` : 'all canisters'}${fuelWords() ? `, ${fuelWords()}` : ''}. Time, half-lives, canisters and fuel are chosen above.`;
    const x = rawPlan(r);
    const n = x.plan.rows.length, nv = x.plan.cols.length;
    const sample = new Float64Array(Math.min(PREVIEW_ROWS, n) * nv);
    x.plan.fill(sample, 0, Math.min(PREVIEW_ROWS, n));
    const t = rawTable(r, { ...x, plan: { ...x.plan, rows: x.plan.rows.subarray(0, PREVIEW_ROWS) } }, sample);
    const cols = t.fields.length + nv;
    const what = r.level === 'el' ? 'fuel elements' : `canisters (${intText(x.nEl)} elements)`;
    $('invRawCount').textContent = n ? `${intText(n)} ${what} × ${intText(cols)} columns: ${intText(n * nv)} values` : 'No element is chosen.';
    document.querySelectorAll('[data-on-click="inv:rawCsv"], [data-on-click="inv:rawExcel"]').forEach((b) => { if (!b.dataset.busy) b.disabled = !n || !nv; });
    const shown = [
      ...t.fields.map((f) => ({ label: f.label, cls: f.fmt === 'text' ? 'text' : null, text: (i) => (f.fmt === 'date' ? dateText(f.values[i]) : f.values[i] === null || f.values[i] === undefined ? '' : String(f.values[i])) })),
      ...t.values.labels.map((label, j) => ({ label, html: (i) => numHtml(sample[i * nv + j]) })),
    ];
    $('invRawPreview').replaceChildren(buildTable(shown, Array.from({ length: Math.min(PREVIEW_ROWS, n) }, (_, i) => i)));
    $('invRawNote').textContent = n > PREVIEW_ROWS ? `The first ${PREVIEW_ROWS} of ${intText(n)} rows. The file holds them all, every digit.` : '';
  }

  const yieldToPage = () => new Promise((resolve) => { const ch = new MessageChannel(); ch.port1.onmessage = () => resolve(); ch.port2.postMessage(0); });

  /** The file written off the page (inventory-raw-worker.js), or on it where no worker can start. */
  function rawWrite(format, table, about, head, progress) {
    const type = format === 'csv' ? 'text/csv;charset=utf-8' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    const onPage = async () => {
      const W = await loadScript('./resources/js/inventory-raw.js?v=20261102a', 'KVOT_INV_RAW');
      return new Blob(format === 'csv' ? W.csv(table, head, { progress }) : await W.xlsx(table, about, { progress }), { type });
    };
    return new Promise((resolve, reject) => {
      let w;
      try { w = new Worker('./resources/js/inventory-raw-worker.js?v=20261102a'); } catch (e) { onPage().then(resolve, reject); return; }
      w.onmessage = (ev) => {
        const m = ev.data || {};
        if ('share' in m) { progress(m.share); return; }
        w.terminate();
        if (m.error) reject(new Error(m.error)); else resolve(m.blob);
      };
      w.onerror = (ev) => { ev.preventDefault(); w.terminate(); onPage().then(resolve, reject); };
      w.postMessage({ format, table, about, head });
    });
  }

  async function rawSave(format, button) {
    if (!state.inv) return;
    const r = rawState();
    const x = rawPlan(r);
    const n = x.plan.rows.length, nv = x.plan.cols.length;
    if (!n || !nv) { showError(['Nothing to save: no element, part or nuclide is chosen.']); return; }
    const buttons = [...document.querySelectorAll('[data-on-click="inv:rawCsv"], [data-on-click="inv:rawExcel"]')];
    const was = button.textContent;
    const say = (share) => { button.textContent = `${Math.min(99, Math.round(share * 100))} %`; };
    buttons.forEach((b) => { b.disabled = true; b.dataset.busy = '1'; });
    try {
      /* The values a piece at a time, the page answering between pieces: half the way. */
      const matrix = new Float64Array(n * nv);
      for (let i = 0; i < n; i += 400) {
        x.plan.fill(matrix, i, Math.min(n, i + 400));
        say(0.5 * Math.min(1, (i + 400) / n));
        await yieldToPage();
      }
      const about = rawAbout(r, x);
      const blob = await rawWrite(format, rawTable(r, x, matrix), about, about.map(([k, v]) => `${k}: ${v}`), (s) => say(0.5 + 0.5 * s));
      saveFile(`${baseName()}-raw-${r.level === 'el' ? 'elements' : 'canisters'}-${year() ?? 'packed'}-${r.qty}.${format === 'csv' ? 'csv' : 'xlsx'}`, blob);
    } catch (err) {
      showError([`The ${format === 'csv' ? 'CSV' : 'Excel'} file could not be written: ${err.message}`]);
    } finally {
      buttons.forEach((b) => { delete b.dataset.busy; b.disabled = false; });
      button.textContent = was;
    }
  }

  /* ---------------------------------------------------------------------
     Opening files
     --------------------------------------------------------------------- */
  /*
    Files are told by their names, else by their first bytes. A zip archive
    or a gzip file is opened and what is in it is read as if it had been
    opened on its own: an inventory in one is unpacked as it is read, in the
    worker, never whole; anything else is unpacked first. An archive in an
    archive is opened too, two deep.
  */
  const KIND_ORDER = ['json', 'xlsx', 'docx', 'zip', 'gz', null];

  async function kindOf(f) {
    const n = f.name.toLowerCase();
    if (/\.json$/.test(n)) return 'json';
    if (/\.(xlsx|xlsm)$/.test(n)) return 'xlsx';
    if (/\.docx$/.test(n)) return 'docx';
    if (/\.zip$/.test(n)) return 'zip';
    if (/\.(gz|gzip)$/.test(n)) return 'gz';
    const head = new Uint8Array(await f.slice(0, 128).arrayBuffer());
    if (head[0] === 0x7b || head[0] === 0x5b || (head[0] === 0xef && head[3] === 0x7b)) return 'json';
    if (head[0] === 0x1f && head[1] === 0x8b) return 'gz';
    if (head[0] === 0x50 && head[1] === 0x4b) {
      /* A Word document and a workbook are zip archives too: told by what they hold. */
      try {
        const names = (await J.zipDirectory(f)).map((e) => e.name);
        if (names.includes('word/document.xml')) return 'docx';
        if (names.includes('xl/workbook.xml')) return 'xlsx';
      } catch (e) { /* not a zip archive after all */ }
      return 'zip';
    }
    return null;
  }

  async function openFiles(files, depth = 0) {
    const list = [...files];
    if (depth === 0) showError([]);
    const kinds = await Promise.all(list.map(kindOf));
    const jobs = list.map((f, i) => ({ f, kind: kinds[i] }));
    jobs.sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind));
    const errors = [];
    const tasks = [];
    const fail = (f) => (e) => { errors.push(`${f.name}: ${e.message}`); };
    for (const { f, kind } of jobs) {
      const too = kvotFileTooLarge(f, kind === 'json' || kind === 'zip' || kind === 'gz' ? Infinity : KVOT_FILE_SIZE_LIMITS.document);
      if (too.tooLarge) { errors.push(too.reason); continue; }
      if (kind === 'json') tasks.push(readInventoryFile(f).catch(fail(f)));
      else if (kind === 'xlsx') tasks.push(readWorkbookFile(f).catch(fail(f)));
      else if (kind === 'docx') tasks.push(readReportFile(f).catch(fail(f)));
      else if ((kind === 'zip' || kind === 'gz') && depth >= 2) errors.push(`${f.name}: an archive three deep is not opened`);
      else if (kind === 'zip') tasks.push(openArchive(f, depth).then((e) => errors.push(...e), fail(f)));
      else if (kind === 'gz') tasks.push(openGzip(f, depth).then((e) => errors.push(...e), fail(f)));
      else errors.push(`${f.name}: not a file this page reads (an inventory .json, PSAR’s .xlsx or .docx, or a .zip or .gz of them)`);
    }
    await Promise.all(tasks);
    if (depth === 0 && errors.length) showError(errors);
    return errors;
  }

  const baseOf = (path) => String(path).split('/').pop();
  const KNOWN = /\.(json|xlsx|xlsm|docx|zip|gz|gzip)$/i;

  /** A zip archive's files: an inventory in it streamed, the others unpacked and opened. */
  async function openArchive(file, depth) {
    const errors = [];
    const entries = await withBusy(file.name, 'Opening', () => J.zipDirectory(file));
    const usable = entries.filter(J.zipUsable);
    const inventories = usable.filter((e) => /\.json$/i.test(e.name));
    const others = usable.filter((e) => !/\.json$/i.test(e.name) && KNOWN.test(e.name));
    const skipped = usable.length - inventories.length - others.length;
    if (!inventories.length && !others.length) return [`${file.name}: nothing in it this page reads${skipped ? ` (${skipped} other files)` : ''}`];
    if (inventories.length > 1) errors.push(`${file.name}: ${inventories.length} inventories in it; ${inventories[0].name} is the one opened`);
    const tasks = [];
    if (inventories.length) {
      const e = inventories[0];
      tasks.push(readInventoryFile(file, { entry: e, label: `${file.name} › ${e.name}`, size: e.usize }).catch((err) => errors.push(`${file.name} › ${e.name}: ${err.message}`)));
    }
    if (others.length) {
      tasks.push((async () => {
        const inner = [];
        for (const e of others) {
          if (e.usize > KVOT_FILE_SIZE_LIMITS.document) { errors.push(`${file.name} › ${e.name}: ${kvotFormatBytes(e.usize)} unpacked, more than this page reads`); continue; }
          try {
            const bytes = await withBusy(`${file.name} › ${e.name}`, 'Unpacking', async () => new Response(await J.zipEntryStream(file, e)).arrayBuffer());
            inner.push(new File([bytes], baseOf(e.name)));
          } catch (err) {
            errors.push(`${file.name} › ${e.name}: ${err.message}`);
          }
        }
        errors.push(...(await openFiles(inner, depth + 1)).map((m) => `${file.name} › ${m}`));
      })());
    }
    await Promise.all(tasks);
    return errors;
  }

  /** A gzip file: an inventory streamed, anything else unpacked and opened by its name less .gz. */
  async function openGzip(file, depth) {
    const inner = file.name.replace(/\.(gz|gzip)$/i, '');
    if (/\.json$/i.test(inner) || !KNOWN.test(inner)) {
      await readInventoryFile(file, { gzip: true, label: file.name });
      return [];
    }
    const bytes = await withBusy(file.name, 'Unpacking', async () => {
      try { return await new Response(J.unpack(file, 'gzip')).arrayBuffer(); } catch (err) { throw new Error('the packed file is damaged'); }
    });
    return openFiles([new File([bytes], inner)], depth + 1);
  }

  /* What could not be read, in the bar: a file's fault, not the page's. */
  function showError(lines) {
    $('invMsgText').textContent = lines.join('\n');
    show($('invMsg'), lines.length > 0);
  }

  let worker = null;
  /**
   * Read an inventory: a JSON file, an entry of a zip archive (opt.entry) or
   * a gzip file (opt.gzip), named opt.label in the bar.
   */
  function readInventoryFile(file, opt = {}) {
    const label = opt.label || file.name;
    return new Promise((resolve, reject) => {
      stopReading();
      state.reading = { name: label, share: 0 };
      renderBar();
      const done = (data) => {
        state.reading = null;
        state.inv = new M.Inventory(data, ND, { name: label, size: opt.size || file.size });
        state.inv.setPick(state.inv.nPlanned && state.inv.nPlanned < state.inv.nEl ? state.settings.fuel : 'all');
        state.invFile = { name: label, size: opt.size || file.size };
        state.systems.clear();
        state.detail = null;
        state.canShown = 200;
        if (!validYear(state.settings.year)) state.settings.year = String(minYear());
        renderSoon();
        resolve();
      };
      const fail = (msg) => { state.reading = null; renderBar(); reject(new Error(msg)); };
      const progress = (s) => { if (state.reading) { state.reading.share = s; updateProgress(); } };
      /* On the page, where no worker can start (a page opened from the file system). */
      const onPage = async () => {
        const stop = { shouldStop: () => !state.reading };
        if (!opt.entry && !opt.gzip) return J.readInventory(J.blobSource(file), progress, stop);
        const total = opt.entry ? opt.entry.csize : file.size;
        let seen = 0;
        const onBytes = (n) => { seen += n; progress(total ? Math.min(1, seen / total) : 0); };
        const stream = opt.entry ? await J.zipEntryStream(file, opt.entry, onBytes) : J.unpack(file, 'gzip', onBytes);
        return J.readInventoryStream(stream, stop);
      };
      try {
        worker = new Worker('./resources/js/inventory-worker.js?v=20261102b');
      } catch (e) {
        worker = null;
      }
      if (!worker) {
        onPage().then(done, (e) => fail(e.message));
        return;
      }
      const w = worker;
      w.onmessage = (ev) => {
        const m = ev.data || {};
        if (m.progress !== undefined) { progress(m.progress); return; }
        w.terminate();
        if (worker === w) worker = null;
        if (m.error) fail(m.error === 'stopped' ? 'stopped' : m.error);
        else done(m.data);
      };
      w.onerror = (ev) => {
        ev.preventDefault();
        w.terminate();
        if (worker === w) worker = null;
        /* A worker that cannot load its script: read on the page instead. */
        onPage().then(done, (e) => fail(e.message));
      };
      w.postMessage({ file, entry: opt.entry || null, gzip: !!opt.gzip });
    });
  }
  function updateProgress() {
    const p = $('invFiles').querySelector('.inv-chip.busy progress');
    if (p && state.reading) p.value = state.reading.share;
  }
  function stopReading() {
    if (worker) { worker.terminate(); worker = null; }
    if (state.reading) { state.reading = null; renderBar(); }
  }
  function closeInventory() {
    state.inv = null;
    state.invFile = null;
    state.detail = null;
    state.systems.clear();
    renderSoon();
  }

  /* A library loaded once, however many files ask for it at the same time
     (a script's top-level constants cannot be declared twice). */
  const loading = new Map();
  function loadScript(src, global) {
    if (window[global]) return Promise.resolve(window[global]);
    if (!loading.has(src)) {
      loading.set(src, new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src;
        s.onload = () => (window[global] ? resolve(window[global]) : reject(new Error(`${src} did not load`)));
        s.onerror = () => { loading.delete(src); reject(new Error(`${src} could not be loaded`)); };
        document.head.append(s);
      }));
    }
    return loading.get(src);
  }

  async function withBusy(name, what, fn) {
    state.busy.set(name, what);
    renderBar();
    try { return await fn(); } finally { state.busy.delete(name); renderBar(); }
  }

  async function readWorkbookFile(file) {
    await withBusy(file.name, 'Reading', async () => {
      const XLSX = await loadScript('./vendors/js/xlsx-0.20.3.full.min.js?v=20261009', 'XLSX');
      const buf = await file.arrayBuffer();
      await new Promise((r) => setTimeout(r, 20));
      const wb = XLSX.read(buf, { type: 'array', cellFormula: false, cellHTML: false, cellText: false });
      const year = state.psar.report ? state.psar.report.year : 2045;
      state.psar.workbook = PS.readWorkbook(wb, XLSX, file.name, year);
    });
    afterPsar();
  }

  async function readReportFile(file) {
    await withBusy(file.name, 'Reading', async () => {
      const bytes = new Uint8Array(await file.arrayBuffer());
      state.psar.report = await PS.readReport(bytes, file.name);
      /* The workbook does not say its year; the report does. */
      if (state.psar.workbook && state.psar.report.year && state.psar.workbook.year !== state.psar.report.year) {
        state.psar.workbook.year = state.psar.report.year;
        for (const r of state.psar.workbook.refs) r.year = state.psar.report.year;
      }
    });
    afterPsar();
  }

  function afterPsar() {
    changed('psar');
  }

  /* ---------------------------------------------------------------------
     Actions
     --------------------------------------------------------------------- */
  function readSettings() {
    const s = state.settings;
    const prevHalf = s.half;
    s.at = $('invAt').value;
    s.unit = $('invUnit').value;
    const half = $('invHalf').value;
    if (half.startsWith('ensdf:') && !(ensdf.get(half.slice(6)) || {}).db) {
      /* A release is read when first chosen; the half-lives in use stay till then. */
      ensdfDb(half.slice(6)).then(() => { state.settings.half = half; changed('half'); save(); },
        (err) => { showError([`ENSDF could not be read: ${err.message}`]); renderBar(); });
    } else s.half = half;
    s.type = Number($('invType').value);
    s.fuel = $('invFuel').value || 'all';
    if (state.inv) state.inv.setPick(state.inv.nPlanned ? s.fuel : 'all');
    if (s.at === 'year') {
      const field = $('invYear');
      const t = field.value.trim();
      if (validYear(t)) s.year = String(Number(t));
      if (!validYear(s.year) && state.inv) s.year = String(minYear());
      const bad = t !== '' && !validYear(t);
      field.setAttribute('aria-invalid', String(bad));
      field.title = bad ? `A whole year, from ${minYear()}; ${s.year} is shown` : '';
    }
    if (s.half !== prevHalf) changed('half');
    save();
  }

  function readView(el) {
    const v = state.view;
    /* A reference picked by hand stays; until then the best one open is shown. */
    if (el && el.id === 'invRef') v.refChosen = true;
    v.nucShow = $('invNucShow').value;
    v.nucCan = $('invNucCan').value.trim();
    v.nucSet = $('invNucSet').value;
    v.nucOrder = $('invNucOrder').value;
    const level = $('invLevel').value;
    if (level !== v.level) { v.level = level; state.canShown = 200; }
    v.qty = $('invQty').value || v.qty;
    v.against = $('invAgainst').value || v.against;
    v.timeOf = $('invTimeOf').value;
    v.timeCan = $('invTimeCan').value.trim();
    v.timeQty = $('invTimeQty').value;
    v.timeTo = $('invTimeTo').value;
    v.timeRef = $('invTimeRef').value;
    v.ref = $('invRef').value || v.ref;
    v.catNuc = $('invCatNuc').value || v.catNuc;
    save();
  }

  registerActions({
    'inv:open': () => $('invFile').click(),
    'inv:filesChosen': (ev, el) => { const files = [...el.files]; el.value = ''; if (files.length) openFiles(files); },
    'inv:tab': (ev, el) => showTab(el.dataset.tab),
    'inv:settings': () => { readSettings(); renderSoon(); },
    'inv:yearTyped': (ev, el) => {
      /* Marked while typing; taken on Enter or when the field is left. */
      const t = el.value.trim();
      const bad = t !== '' && !validYear(t);
      el.setAttribute('aria-invalid', String(bad));
      el.title = bad ? `A whole year, from ${minYear()}` : '';
    },
    'inv:msgClose': () => showError([]),
    'inv:view': (ev, el) => { readView(el); renderSoon(); },
    'inv:nucCsv': () => nucCsv(),
    'inv:nucExcel': (ev, el) => nucExcel(el),
    'inv:canCsv': () => canCsv(),
    'inv:canExcel': (ev, el) => canExcel(el),
    'inv:timeExcel': (ev, el) => timeExcel(el),
    'inv:overviewExcel': (ev, el) => overviewExcel(el),
    'inv:psarExcel': (ev, el) => psarExcel(el),
    'inv:canMore': () => { state.canShown += 500; renderCanisters(); },
    'inv:timeCsv': () => timeCsv(),
    'inv:detailClose': () => { state.detail = null; renderCanisters(); },
    'inv:detailPrev': () => stepDetail(-1),
    'inv:detailNext': () => stepDetail(1),
    'inv:full': () => setFull(!document.documentElement.classList.contains('inv-full')),
    'inv:raw': () => readRaw(),
    'inv:rawAll': (ev, el) => rawToggle(el.dataset.list, true),
    'inv:rawNone': (ev, el) => rawToggle(el.dataset.list, false),
    'inv:rawCsv': (ev, el) => rawSave('csv', el),
    'inv:rawExcel': (ev, el) => rawSave('xlsx', el),
  });

  /* The whole page takes a drop. */
  let dragDepth = 0;
  const hasFiles = (ev) => ev.dataTransfer && [...(ev.dataTransfer.types || [])].includes('Files');
  document.addEventListener('dragenter', (ev) => { if (!hasFiles(ev)) return; ev.preventDefault(); dragDepth++; $('inv').classList.add('inv-dropping'); });
  document.addEventListener('dragover', (ev) => { if (!hasFiles(ev)) return; ev.preventDefault(); ev.dataTransfer.dropEffect = 'copy'; });
  document.addEventListener('dragleave', (ev) => { if (!hasFiles(ev)) return; dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('inv').classList.remove('inv-dropping'); });
  document.addEventListener('drop', (ev) => {
    if (!hasFiles(ev)) return;
    ev.preventDefault();
    dragDepth = 0;
    $('inv').classList.remove('inv-dropping');
    const files = [...ev.dataTransfer.files];
    if (files.length) openFiles(files);
  });
  $('invDrop').addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); $('invFile').click(); } });

  document.documentElement.addEventListener('kvot-theme-change', () => renderSoon());

  /* ---------------------------------------------------------------------
     (i) topics
     --------------------------------------------------------------------- */
  const more = (id, label) => ({ id, label });
  KvotInfo.setup({
    onMore: (m) => { showTab('help'); const t = document.getElementById(m.id); if (t) t.scrollIntoView({ block: 'start' }); },
    topics: {
      'set:files': () => ({
        kicker: 'Files', title: 'What the page reads',
        lead: 'Drop files on the page, or choose them. Each is told by what it holds; several can be opened at once.',
        facts: [['Inventory', '.json: canisters, their elements, moles per nuclide and part'], ['PSAR workbook', '.xlsx: SKBdoc 1668003'], ['PSAR report', '.docx: SKBdoc 1380282'], ['Zipped', '.zip of any of them (one or several), or .gz; an inventory in one is unpacked as it is read']],
        sections: [{ heading: 'Open now', list: [state.invFile ? `inventory: ${state.invFile.name}` : 'no inventory', ...(state.psar.workbook ? [`workbook: ${state.psar.workbook.source}`] : []), ...(state.psar.report ? [`report: ${state.psar.report.source}`] : [])] }],
        more: more('help-files', 'Opening files'),
      }),
      'set:time': () => ({
        kicker: 'Setting', title: 'Time',
        lead: 'As packed, each canister is shown as the file gives it, at its own packing date. In a year, every canister is brought to 1 January of that year by decay, so that all of them, and PSAR’s values, hold for one time.',
        sections: [
          { heading: 'How it decays', list: ['ICRP Publication 107’s half-lives, branches and energies, every chain to its end', 'solved by CRAM of order 16, exact to about 1e-13 at any time', 'short-lived daughters the file does not list held in equilibrium, for the decay heat'] },
          { heading: 'Which years', text: state.inv ? `From ${minYear()}, the first 1 January after the last canister was packed: decay does not run backwards.` : 'From the first 1 January after the last canister was packed.' },
        ],
        more: more('help-time', 'Time'),
      }),
      'set:unit': () => ({
        kicker: 'Setting', title: 'Unit',
        lead: 'Moles as the file gives them, becquerels (A = λN), or grams (by ICRP 107’s atomic masses).',
        sections: [{ heading: 'Good to know', list: ['moles and becquerels are turned into each other by the half-life, so the half-lives chosen change them', 'sums of activity are of the nuclides the file lists, not their short-lived daughters'] }],
        more: more('help-unit', 'Unit'),
      }),
      'set:half': () => ({
        kicker: 'Setting', title: 'Half-lives',
        lead: 'What everything decays with and turns moles into becquerels with: ICRP Publication 107’s by default; PSAR’s own, once its report (Table D-1) is open, for the nuclides they list (the chains stay ICRP 107’s); or an ENSDF release on the site, with its own branches, chains and energies (the atomic masses stay ICRP 107’s). PSAR’s becquerels become moles with its own half-lives whatever is chosen, once its report is open.',
        facts: [['Ni-59', 'ICRP 107: 101 000 y; PSAR and ENSDF 2026: 76 000 y'], ['Se-79', 'ICRP 107 and PSAR: 295 000 y; ENSDF 2026: 327 000 y']],
        more: more('help-half', 'Half-lives'),
      }),
      'set:fuel': () => ({
        kicker: 'Setting', title: 'Fuel',
        lead: 'All fuel elements, the discharged only, or the planned only: those named PLAN…, the reactors’ forecast of fuel not yet discharged. Every view counts only the elements chosen; a canister’s sums are of its elements of that kind, and a canister holding none is left out.',
        facts: state.inv && state.inv.nPlanned ? [['Planned', `${intText(state.inv.nPlanned)} of ${intText(state.inv.nEl)} elements`], ['Canisters holding them', intText(state.inv.select(-1, 'planned').length)]] : [],
        sections: [{ heading: 'With all of them shown', list: ['Overview: the planned share of the elements, uranium, activity and heat; planned fuel hatched in the charts', 'Canisters: planned elements, or canisters holding them, as rings', 'Nuclides: each nuclide’s planned share', 'Over time: the planned part of the total, dotted'] }],
        more: more('help-fuel', 'Fuel'),
      }),
      'set:type': () => ({
        kicker: 'Setting', title: 'Canisters',
        lead: 'All canisters, or those of one reactor type (that of most of a canister’s elements). Every view shows these, except the comparison of the average canister with PSAR’s, which takes the type of PSAR’s canister chosen there.',
        more: more('help-type', 'Canisters'),
      }),
      'pane:overview': {
        kicker: 'View', title: 'Overview',
        lead: 'The inventory in a few numbers and three charts, with PSAR’s numbers below where its files are open.',
        sections: [{ heading: 'The charts', list: ['canisters packed each year, by type; PSAR’s deposited each year as a line', 'fuel elements from each reactor; PSAR’s simulation as rings', 'the decay heat of each canister when packed, with the declared heat and the 1 700 W limit'] }],
        more: more('help-overview', 'Overview'),
      },
      'pane:nuclides': {
        kicker: 'View', title: 'Nuclides',
        lead: 'Each nuclide of the average canister, of all of them together or of one, on a scale of powers of ten, with how it is shared between fuel, crud and structural material.',
        sections: [{ heading: 'The marks', list: ['dot: the value', 'line: the 5th to the 95th percentile of the canisters (nine in ten lie between)', 'ring: PSAR’s value of the same kind, at the same time where it can be'] }, { heading: 'Saving', list: ['CSV and Excel: the table, every digit; the Excel file with a sheet saying what the numbers are for'] }],
        more: more('help-nuclides', 'Nuclides'),
      },
      'pane:canisters': {
        kicker: 'View', title: 'Canisters',
        lead: 'One quantity for every canister or fuel element: set against the packing date or another quantity, and how it spreads. Click a point or a row for that canister.',
        sections: [{ heading: 'Marks', list: ['dashed black line: PSAR’s average canister of the same type, same time and unit', 'grey band: PSAR’s low to high burnup canister', 'dotted: the 1 700 W limit'] }, { heading: 'Saving', list: ['CSV and Excel: every canister (or element) chosen, not only the rows shown, with its fields, decay heat, activity and every nuclide'] }],
        more: more('help-canisters', 'Canisters'),
      },
      'pane:raw': {
        kicker: 'View', title: 'Raw data',
        lead: 'The inventory’s values for every fuel element or canister chosen, a column for each part and nuclide, saved as Excel or CSV.',
        sections: [{ heading: 'Choices', list: ['rows: each fuel element, or each canister with its chosen elements summed', 'values: moles, becquerels, grams or decay heat', 'parts: any of them, a column each or summed', 'nuclides: all, the actinides, the products, or those picked', 'elements by packing year, planned or not, reactor and fuel type', 'time, half-lives and canister type: as chosen above'] }, { heading: 'As packed', list: ['with Time as packed, the values are the file’s own, unchanged'] }],
        more: more('help-raw', 'Raw data'),
      },
      'pane:time': {
        kicker: 'View', title: 'Over time',
        lead: 'The average canister, all of them, or one, decaying from the year shown up to a million years: the eight nuclides that matter most over the span and the total. PSAR’s values of the same kind can be drawn beside it, dashed.',
        sections: [{ heading: 'Beside it', list: ['the average canister: PSAR’s average canister of the type chosen under Canisters (all, BWR or PWR)', 'one canister: PSAR’s average canister of its type', 'all canisters together: PSAR’s totals', 'PSAR’s values hold for 1 January 2045 and are brought to the year shown by decay and ingrowth, with the same half-lives'] }],
        more: more('help-time-view', 'Over time'),
      },
      'pane:ratio': {
        kicker: 'Comparison', title: 'The average canister against PSAR’s',
        lead: 'For each nuclide, this inventory’s average canister over PSAR’s, at one time and in one unit. 1 is the same.',
        sections: [{ heading: 'The marks', list: ['dot: the ratio of the averages', 'line: this inventory’s canisters from the 5th to the 95th percentile, over the same PSAR value', 'grey band: PSAR’s own spread, from its low to its high burnup canister'] }, { heading: 'PSAR’s averages', list: ['all: its total over all fuel, over its 5 689 canisters', 'BWR: 12 elements of 40 MWd/kgU', 'PWR: 4 elements of 45 MWd/kgU and 0.0863 control rods per element'] }],
        more: more('help-psar', 'Compare with PSAR'),
      },
      'pane:categories': {
        kicker: 'Comparison', title: 'Totals by kind of fuel',
        lead: 'Each fuel element counted in the kind of fuel PSAR’s tables count it in, whichever canister it is in: BWR, PWR, Ågesta, swap MOX, Studsvik.',
        sections: [{ heading: 'How an element’s kind is told', list: ['Ågesta, Studsvik and the four German reactors of the swap MOX (Gundremmingen, Kahl, Obrigheim, Mehrzweckforschungsreaktor) by the reactor’s name', 'the others by their reactor type'] }],
        more: more('help-psar', 'Compare with PSAR'),
      },
    },
  });

  /* ---------------------------------------------------------------------
     Start
     --------------------------------------------------------------------- */
  load();
  KvotInfo.mount(document);
  fullState();
  showTab(state.tab);
  offerEnsdf();

  /* For tests and the console. */
  window.InventoryPage = { state, openFiles, render: renderTab, system, canAt, refs, refValues, setYear, showTab };
})();
