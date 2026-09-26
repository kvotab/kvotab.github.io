/* ==========================================================================
   EROSION_CORROSION.HTML: THE PAGE

   Wiring only. The arithmetic is ec-model.js, the file readers are
   ec-hydro.js and the sulphide tables ec-hsdata.js. This file keeps the
   state, builds the parameter panel from the model's own catalogue, runs
   the calculation whenever something changes, and draws the tables and
   charts.

   The calculation is small enough to run on the main thread: 7000 holes
   against a 50-point sulphide table is a few milliseconds, and against a
   10,000-point generated table well under a second, so there is no worker.

   One global: ECPage, a read-only window on the state for the browser test.
   Everything else is inside the IIFE and reached through the data-on-*
   actions registered at the bottom.
   ========================================================================== */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (s) => (typeof kvotEscapeHtml === 'function' ? kvotEscapeHtml(s) : String(s ?? ''));
  const STORAGE_KEY = 'kvot-ec-v1';
  const DEFAULT_WIDTH = 340;
  const NEVER = ECModel.NEVER;

  /* ---------------------------------------------------------------------
     State
     --------------------------------------------------------------------- */
  const state = {
    params: ECModel.defaults(),
    hs: { table: 'HSForsmark', generic: { ...ECHS.GENERIC_DEFAULTS }, customText: '' },
    hydro: [],                 // [{name, table, source}] -- not persisted
    totalHoles: '',
    inflow: null,              // {name, set}
    tab: 'summary',
    sideWidth: null,
    sections: {},
    autoRun: true,
    dist: { which: 'qeq', real: 'all' },
    holes: { filter: 'all', search: '', real: 0, limit: 300 },
    sort: { failures: { key: 'index', asc: true }, holes: { key: 'id', asc: true } },
    result: null,              // {results, table, summary}
    lastError: null,
  };

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        params: state.params, hs: state.hs, totalHoles: state.totalHoles, tab: state.tab,
        sideWidth: state.sideWidth, sections: state.sections, autoRun: state.autoRun,
        dist: state.dist, holes: { filter: state.holes.filter, real: state.holes.real },
      }));
    } catch (e) { /* storage unavailable */ }
  }

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const s = JSON.parse(raw);
      if (s.params) state.params = ECModel.normalise(s.params).params;
      if (s.hs && typeof s.hs === 'object') {
        if (typeof s.hs.table === 'string') state.hs.table = s.hs.table;
        if (s.hs.generic) Object.assign(state.hs.generic, s.hs.generic);
        if (typeof s.hs.customText === 'string') state.hs.customText = s.hs.customText;
      }
      if (typeof s.totalHoles === 'string') state.totalHoles = s.totalHoles;
      if (typeof s.tab === 'string') state.tab = s.tab;
      if (Number.isFinite(s.sideWidth)) state.sideWidth = s.sideWidth;
      if (s.sections && typeof s.sections === 'object') state.sections = s.sections;
      if (typeof s.autoRun === 'boolean') state.autoRun = s.autoRun;
      if (s.dist && typeof s.dist === 'object') Object.assign(state.dist, s.dist);
      if (s.holes && typeof s.holes === 'object') Object.assign(state.holes, s.holes);
    } catch (e) { /* a corrupt entry: start fresh */ }
  }

  /* ---------------------------------------------------------------------
     Formatting
     --------------------------------------------------------------------- */
  const trimZeros = (s) => s.replace(/(\.\d*?[1-9])0+$/, '$1').replace(/\.0+$/, '');
  const trimExp = (s) => s.replace(/(\.\d*?[1-9])0+e/, '$1e').replace(/\.0+e/, 'e');

  function fmt(x, sig = 4) {
    if (x === null || x === undefined) return '–';
    if (typeof x === 'boolean') return x ? 'yes' : 'no';
    if (typeof x !== 'number') return String(x);
    if (Number.isNaN(x)) return '–';
    if (x >= 1e98) return 'never';
    if (x === 0) return '0';
    if (Number.isInteger(x) && Math.abs(x) < 1e15) return x.toLocaleString('en');
    const a = Math.abs(x);
    if (a >= 1e7 || a < 1e-4) return trimExp(x.toExponential(sig - 1));
    return trimZeros(x.toPrecision(sig));
  }
  /** Years: whole numbers with thousands separators. */
  const fmtYears = (x) => (x === null || x === undefined || Number.isNaN(x) ? '–' : (x >= 1e98 ? 'never' : Math.round(x).toLocaleString('en')));
  /** A value for a CSV cell: full precision, no locale. */
  const raw = (x) => (x === null || x === undefined ? '' : (typeof x === 'number' ? (Number.isNaN(x) ? '' : String(x)) : (typeof kvotCsvCell === 'function' ? kvotCsvCell(x) : `"${String(x).replace(/"/g, '""')}"`)));

  function download(name, text, type = 'text/csv') {
    const blob = new Blob([text], { type: `${type};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function setStatus(text, tone) {
    const el = $('ecStatus');
    el.textContent = text;
    el.className = `ec-status${tone ? ` ${tone}` : ''}`;
  }

  /* ---------------------------------------------------------------------
     The parameter panel, built from the catalogue
     --------------------------------------------------------------------- */
  function buildParamSections() {
    const host = $('ecParamSections');
    const html = [];
    for (const g of ECModel.GROUPS) {
      const items = ECModel.PARAMS.filter((d) => d.group === g.id);
      if (!items.length) continue;
      html.push(`<details class="ec-sec" id="sec-${g.id}"><summary><span class="ec-sec-title">${esc(g.label)}</span><span class="ec-count" id="ecChanged-${g.id}"></span>`
        + `<span class="kvot-info-slot" data-info-key="sec:${g.id}"></span></summary>`);
      if (g.about) html.push(`<p class="ec-about">${esc(g.about)}</p>`);
      for (const d of items) html.push(paramControl(d));
      html.push('</details>');
    }
    host.innerHTML = html.join('');
  }

  function traceName(d) {
    const parts = [];
    if (d.xl) parts.push(`Excel ${d.xl}`);
    if (d.py) parts.push(`py ${d.py}`);
    return parts.join(' · ');
  }

  /**
   * One row of the panel. The (i) sits at the right-hand end of the label
   * line (of the checkbox line for a switch); its topic is paramTopic().
   */
  function paramControl(d) {
    const name = traceName(d);
    const slot = `<span class="kvot-info-slot" data-info-key="p:${d.key}"></span>`;
    const desc = d.desc ? `<span class="ec-desc">${esc(d.desc)}</span>` : '';
    const trace = name ? `<span class="ec-name">${esc(name)}</span>` : '';
    if (d.type === 'bool') {
      return `<div class="ec-check-line"><label class="ec-check" data-key="${d.key}"><input type="checkbox" data-key="${d.key}" data-on-change="ec:paramChanged">`
        + `<span>${esc(d.label)}${desc}${trace}</span></label>${slot}</div>`;
    }
    const id = `ecp-${d.key}`;
    const unit = d.type !== 'select' && d.unit ? `<span class="ec-unit">${esc(d.unit)}</span>` : '';
    const head = `<div class="kvot-info-line ec-label-line"><label for="${id}">${esc(d.label)}${unit}</label>${slot}</div>${desc}${trace}`;
    if (d.type === 'select') {
      const opts = d.options.map((o) => `<option value="${esc(o[0])}">${esc(o[1])}</option>`).join('');
      return `<div class="ec-row" data-key="${d.key}">${head}<select id="${id}" data-key="${d.key}" data-on-change="ec:paramChanged">${opts}</select></div>`;
    }
    return `<div class="ec-row" data-key="${d.key}">${head}`
      + `<input id="${id}" type="text" inputmode="decimal" data-key="${d.key}" data-on-change="ec:paramChanged" spellcheck="false"></div>`;
  }

  /** Put the state's values into the controls and mark what differs from the defaults. */
  function writeParamControls() {
    const changedPerGroup = {};
    for (const d of ECModel.PARAMS) {
      const el = document.querySelector(`[data-key="${d.key}"]:not(label):not(div)`);
      if (!el) continue;
      const v = state.params[d.key];
      if (d.type === 'bool') el.checked = !!v;
      else if (d.type === 'select') el.value = v;
      else el.value = numberText(v);
      const changed = v !== d.def;
      const wrap = el.closest('.ec-row, .ec-check');
      if (wrap) wrap.classList.toggle('changed', changed);
      el.classList.toggle('changed', changed);
      if (changed) changedPerGroup[d.group] = (changedPerGroup[d.group] || 0) + 1;
    }
    for (const g of ECModel.GROUPS) {
      const c = $(`ecChanged-${g.id}`);
      if (c) c.textContent = changedPerGroup[g.id] ? `${changedPerGroup[g.id]} changed` : '';
    }
    infoRefresh();
  }

  /** A value as a field shows it: 15 digits, which is every digit of a default such as the workbook's AdvConst. */
  function numberText(v) {
    if (typeof v !== 'number') return String(v);
    if (Number.isInteger(v) && Math.abs(v) < 1e15) return String(v);
    const a = Math.abs(v);
    if (a >= 1e6 || a < 1e-3) return trimExp(v.toExponential(14));
    return trimZeros(v.toPrecision(15));
  }

  function readParam(el) {
    const key = el.dataset.key;
    const d = ECModel.PARAM_BY_KEY[key];
    if (!d) return;
    if (d.type === 'bool') { state.params[key] = el.checked; return; }
    if (d.type === 'select') { state.params[key] = el.value; return; }
    const x = parseFloat(String(el.value).trim().replace(',', '.'));
    if (!Number.isFinite(x)) {
      el.setCustomValidity('Not a number');
      el.reportValidity();
      return;
    }
    el.setCustomValidity('');
    state.params[key] = d.type === 'int' ? Math.round(x) : x;
  }

  /* ---------------------------------------------------------------------
     Sulphide
     --------------------------------------------------------------------- */
  function hsValues() {
    const h = state.hs;
    if (ECHS.TABLES[h.table]) return { values: ECHS.TABLES[h.table].values, note: '' };
    if (h.table === 'generic') {
      const g = h.generic;
      const values = ECHS.generic(g);
      const kind = g.kind === 'log10-normal' ? `log10-normal, μ = ${g.mu10}, σ = ${g.sigma10}` : `shifted lognormal, mean ${fmt(g.mean, 3)}, s.d. ${fmt(g.std, 3)}, shift ${fmt(g.shift, 3)} M`;
      return { values, note: `${kind}; ${values.length} midpoint quantiles.` };
    }
    const c = ECHS.parseCustom(h.customText);
    return { values: c.values, note: c.dropped ? `${c.dropped} token${c.dropped > 1 ? 's' : ''} in the text were not positive numbers and were ignored.` : '' };
  }

  function writeHsControls() {
    $('ecHsTable').value = state.hs.table;
    const g = state.hs.generic;
    $('ecHsKind').value = g.kind;
    $('ecHsMean').value = numberText(g.mean);
    $('ecHsStd').value = numberText(g.std);
    $('ecHsShift').value = numberText(g.shift);
    $('ecHsMu').value = numberText(g.mu10);
    $('ecHsSigma').value = numberText(g.sigma10);
    $('ecHsN').value = String(g.n);
    $('ecHsText').value = state.hs.customText;
    $('ecHsGeneric').hidden = state.hs.table !== 'generic';
    $('ecHsShifted').hidden = g.kind !== 'shifted-lognormal';
    $('ecHsLog10').hidden = g.kind !== 'log10-normal';
    $('ecHsCustom').hidden = state.hs.table !== 'custom';
    describeHs();
    infoRefresh();
  }

  function describeHs() {
    let text;
    try {
      const { values, note } = hsValues();
      const d = ECHS.describe(values);
      text = d.n ? `${d.n} values: highest ${fmt(d.max, 3)} M, mean ${fmt(d.mean, 3)} M, lowest ${fmt(d.min, 3)} M.` : 'No positive values.';
      if (note) text += ` ${note}`;
    } catch (e) { text = e.message; }
    $('ecHsNote').textContent = text;
  }

  function readHsControls() {
    state.hs.table = $('ecHsTable').value;
    const g = state.hs.generic;
    g.kind = $('ecHsKind').value;
    const num = (id, cur) => { const x = parseFloat(String($(id).value).replace(',', '.')); return Number.isFinite(x) ? x : cur; };
    g.mean = num('ecHsMean', g.mean);
    g.std = num('ecHsStd', g.std);
    g.shift = num('ecHsShift', g.shift);
    g.mu10 = num('ecHsMu', g.mu10);
    g.sigma10 = num('ecHsSigma', g.sigma10);
    g.n = Math.max(1, Math.min(200000, Math.round(num('ecHsN', g.n))));
    state.hs.customText = $('ecHsText').value;
    writeHsControls();
  }

  /* ---------------------------------------------------------------------
     Hydro data
     --------------------------------------------------------------------- */
  function hydroOptions() {
    const t = parseInt(state.totalHoles, 10);
    return { totalHoles: Number.isFinite(t) && t > 0 ? t : 0, w: state.params.w };
  }

  async function addHydroFiles(files) {
    const list = Array.from(files || []);
    if (!list.length) return;
    let added = 0;
    const errors = [];
    for (const file of list) {
      // kvotFileTooLarge answers with {tooLarge, reason}, never a bare boolean.
      const size = typeof kvotFileTooLarge === 'function' ? kvotFileTooLarge(file) : null;
      if (size && size.tooLarge) { errors.push(size.reason); continue; }
      if (/\.json$/i.test(file.name)) { await openCaseFile(file); continue; }
      try {
        const table = await ECHydro.load(file, hydroOptions());
        applyInflow(table);
        state.hydro.push({ name: file.name, table, source: file });
        added++;
      } catch (e) {
        errors.push(`${file.name}: ${e.message}`);
      }
    }
    renderHydroList();
    if (errors.length) {
      setStatus(errors.join(' '), 'error');
      if (typeof notifyUser === 'function') notifyUser(errors[0], { tone: 'error' });
    }
    if (added) scheduleRun(0);
    saveState();
  }

  function applyInflow(table) {
    if (state.inflow) ECHydro.applyInflowList(table, state.inflow.set);
    else table.inflowReject = new Float64Array(table.n);
  }

  /** Re-read every table whose parsing depends on the options (the DarcyTools ones). */
  async function reparseHydro() {
    for (const h of state.hydro) {
      if (!/DarcyTools/.test(h.table.format)) continue;
      try {
        h.table = typeof h.source === 'string'
          ? ECHydro.parseText(h.source, h.name, hydroOptions())
          : await ECHydro.load(h.source, hydroOptions());
        applyInflow(h.table);
      } catch (e) { setStatus(`${h.name}: ${e.message}`, 'error'); }
    }
    renderHydroList();
    scheduleRun(0);
  }

  function renderHydroList() {
    const ul = $('ecFiles');
    ul.innerHTML = state.hydro.map((h, i) => {
      const t = h.table;
      const meta = [`${t.format}`, `${t.n.toLocaleString('en')} holes`, `${t.meta.flowing.toLocaleString('en')} with a flowing fracture`];
      if (t.meta.padded) meta.push(`${t.meta.padded} padded`);
      const warns = t.warnings.map((w) => `<span class="ec-file-warn">${esc(w)}</span>`).join('');
      // The name's title shows the whole of a name cut short; the ×'s
      // accessible name is its aria-label.
      return `<li><span class="ec-file-name" title="${esc(h.name)}">${i + 1}. ${esc(h.name)}</span>`
        + `<button type="button" aria-label="Remove ${esc(h.name)}" data-on-click="ec:removeHydro" data-index="${i}">×</button>`
        + `<span class="ec-file-meta">${esc(meta.join(' · '))}</span>${warns}</li>`;
    }).join('');
    $('ecHydroCount').textContent = state.hydro.length ? `${state.hydro.length} realisation${state.hydro.length > 1 ? 's' : ''}` : '';
    infoRefresh();
  }

  /* ---------------------------------------------------------------------
     Running
     --------------------------------------------------------------------- */
  let runTimer = null;
  function scheduleRun(delay = 200) {
    if (!state.autoRun && delay > 0) { setStatus('Changed. Press Run.', 'warn'); return; }
    clearTimeout(runTimer);
    runTimer = setTimeout(run, delay);
  }

  function run() {
    clearTimeout(runTimer);
    state.lastError = null;
    if (!state.hydro.length) {
      state.result = null;
      setStatus('Load hydro data: open a file, or drop one on the panel.');
      renderTab();
      return;
    }
    let hs;
    try { hs = hsValues().values; } catch (e) { state.lastError = e.message; setStatus(e.message, 'error'); return; }
    const t0 = performance.now();
    try {
      state.result = ECModel.evaluateMany(state.hydro.map((h) => ({ ...h.table, name: h.name })), hs, state.params);
    } catch (e) {
      state.result = null;
      state.lastError = e.message;
      setStatus(`The calculation failed: ${e.message}`, 'error');
      if (typeof reportFailure === 'function') reportFailure('ec:run', e);
      renderTab();
      return;
    }
    const ms = performance.now() - t0;
    const s = state.result.summary;
    const r0 = state.result.results[0];
    const nHoles = state.result.results.reduce((a, r) => a + r.n, 0);
    const lim = r0.params.tFailFilteringLim.toLocaleString('en');
    const many = state.result.results.length > 1;
    setStatus(`Done in ${ms < 1 ? '<1' : Math.round(ms)} ms: ${state.result.results.length} realisation${many ? 's' : ''}, ${nHoles.toLocaleString('en')} holes, `
      + `${s.nReject.mean.toLocaleString('en', { maximumFractionDigits: 1 })} rejected${many ? ' on average' : ''}. `
      + `Mean number of failed canisters at ${lim} years, corrected: ${fmt(s.meanFailedCorrected.mean, 4)}`
      + `${many ? ` (min ${fmt(s.meanFailedCorrected.min, 3)}, max ${fmt(s.meanFailedCorrected.max, 3)})` : ''}; `
      + `${s.nFailRowsTotal.toLocaleString('en')} failure time${s.nFailRowsTotal === 1 ? '' : 's'} in the table.`, 'ok');
    renderTab();
  }

  /* ---------------------------------------------------------------------
     The summary tab
     --------------------------------------------------------------------- */
  const KEY_ROWS = [
    { key: 'meanFailed', label: (lim) => `Mean number of failed canisters at ${lim} years`, f: (x) => fmt(x, 5), desc: 'Failure times divided by the number of sulphide values: each hole contributes the fraction of the distribution that fails it in time.' },
    { key: 'meanFailedCorrected', label: (lim) => `Mean number of failed canisters at ${lim} years, corrected`, f: (x) => fmt(x, 5), desc: 'Scaled by the canisters to normalise to over the accepted positions.' },
    { key: 'nFailedHighestHs', label: (lim) => `Failed canisters at ${lim} years at the highest sulphide concentration`, f: fmt, desc: 'Holes that fail in time when every hole sees the highest value of the distribution.' },
    { key: 'meanFailed1e5Corrected', label: () => 'Mean number of failed canisters at 100,000 years, corrected', f: (x) => fmt(x, 5) },
    { key: 'earliestFailure', label: () => 'Earliest failure time (years)', f: fmtYears },
    { key: 'nTot', label: () => 'Total number of positions', f: fmt },
    { key: 'nReject', label: () => 'Rejected positions', f: fmt, desc: 'By the criteria selected (FPC, EFPC, fracture length, T/L, Darcy flux, inflow).' },
    { key: 'nSkip', label: () => 'Positions left out of the failure table', f: fmt, desc: 'Rejected, or unable to fail in time, or OKFLAG ≠ 0.' },
    { key: 'nAdvAtLim', label: (lim) => `Advective positions at ${lim} years`, f: fmt },
    { key: 'nAdv1e5', label: () => 'Advective positions at 100,000 years', f: fmt },
    { key: 'earliestAdvection', label: () => 'Earliest advective time (years)', f: (x) => (x !== null && x < 1e-3 ? '0' : fmtYears(x)) },
    { key: 'anyEdge', label: () => 'Any EFPC edge positions among the failed?', f: fmt },
    { key: 'checkSum', label: () => 'Check sum (rows − counted failures; 0 when consistent)', f: fmt },
    { key: 'nHs', label: () => 'Sulphide values in the distribution', f: fmt },
    { key: 'hsMax', label: () => 'Highest sulphide concentration (M)', f: (x) => fmt(x, 4) },
    { key: 'qLim', label: () => 'qlim: flow above which Qeq goes as √q (m³/yr)', f: (x) => fmt(x, 4) },
    { key: 'corrHoleFact', label: () => 'CorrHoleFact: copper capacity of the corroded height (kmol)', f: (x) => fmt(x, 5) },
  ];

  function renderSummary() {
    const host = $('ecSummary');
    if (!state.result) {
      host.innerHTML = `<p class="ec-empty">${state.lastError ? esc(state.lastError) : 'No results yet: load hydro data on the left.'}</p>`;
      return;
    }
    const { results, summary } = state.result;
    const lim = results[0].params.tFailFilteringLim.toLocaleString('en');
    const many = results.length > 1;
    const parts = [];

    // Cards
    const cards = [
      [fmt(summary.meanFailedCorrected.mean, 4), `Mean number of failed canisters at ${lim} years, corrected${many ? ' (mean over realisations)' : ''}`],
      [fmt(summary.meanFailed1e5Corrected.mean, 4), 'at 100,000 years, corrected'],
      [summary.earliestFailure.min === null ? 'none' : fmtYears(summary.earliestFailure.min), 'Earliest failure time, years'],
      [fmt(many ? summary.nAdvAtLim.mean : results[0].key.nAdvAtLim, 4), `Advective positions at ${lim} years${many ? ', mean' : ''}`],
      [fmt(many ? summary.nReject.mean : results[0].key.nReject, 4), `Rejected positions${many ? ', mean' : ''} of ${results[0].n.toLocaleString('en')}`],
      [summary.nFailRowsTotal.toLocaleString('en'), 'Rows in the failure table'],
    ];
    parts.push(`<div class="ec-cards">${cards.map((c) => `<div class="ec-card"><div class="ec-card-value">${esc(c[0])}</div><div class="ec-card-label">${esc(c[1])}</div></div>`).join('')}</div>`);

    // Key outputs per realisation
    parts.push('<h3>Key outputs</h3>');
    const head = ['<tr><th>Quantity</th>'];
    results.forEach((r, i) => head.push(`<th title="${esc(state.hydro[i]?.name || '')}">${many ? `r${i + 1}` : 'value'}</th>`));
    if (many) head.push('<th>min</th><th>mean</th><th>max</th>');
    head.push('</tr>');
    const rows = [];
    for (const kr of KEY_ROWS) {
      const cells = [`<th>${esc(kr.label(lim))}${kr.desc ? `<div class="ec-desc">${esc(kr.desc)}</div>` : ''}</th>`];
      results.forEach((r) => cells.push(`<td>${esc(kr.f(r.key[kr.key]))}</td>`));
      if (many) {
        const st = summary[kr.key];
        if (st && typeof st === 'object') cells.push(`<td>${esc(kr.f(st.min))}</td><td>${esc(kr.f(st.mean))}</td><td>${esc(kr.f(st.max))}</td>`);
        else cells.push('<td></td><td></td><td></td>');
      }
      rows.push(`<tr>${cells.join('')}</tr>`);
    }
    parts.push(`<div class="ec-table-wrap"><table class="ec-key"><thead>${head.join('')}</thead><tbody>${rows.join('')}</tbody></table></div>`);
    if (many) parts.push(`<p class="ec-muted">Failed canisters at the highest sulphide, summed over realisations: ${summary.nFailedHighestHsTotal}. The Python port reports the mean over realisations of the corrected mean; that is the "mean" column.</p>`);

    // Settings that differ from the defaults
    const changed = ECModel.PARAMS.filter((d) => state.params[d.key] !== d.def);
    parts.push('<h3>Case settings</h3>');
    const hsDesc = ECHS.TABLES[state.hs.table] ? state.hs.table : (state.hs.table === 'generic' ? 'generated distribution' : 'custom list');
    parts.push(`<ul class="ec-settings-list"><li>Hydro data: ${state.hydro.map((h) => esc(h.name)).join(', ')}</li><li>Sulphide distribution: ${esc(hsDesc)} (${results[0].key.nHs} values, highest ${fmt(results[0].key.hsMax, 3)} M)</li>`
      + `<li>Buffer model: ${esc(state.params.buffModel)}${state.params.initialAdvection ? ', initial advection' : ''}</li>`
      + (changed.length ? changed.map((d) => `<li>${esc(d.label)}: <b>${esc(fmt(state.params[d.key], 6))}</b>${d.unit ? ` ${esc(d.unit)}` : ''} <code>(default ${esc(fmt(d.def, 6))})</code></li>`).join('') : '<li>Every other parameter at its default.</li>')
      + '</ul>');

    // Hydro warnings
    const warns = state.hydro.flatMap((h) => h.table.warnings.map((w) => `${h.name}: ${w}`));
    if (warns.length) parts.push(`<h3>Notes on the hydro data</h3>${warns.map((w) => `<p class="ec-warn">${esc(w)}</p>`).join('')}`);
    host.innerHTML = parts.join('');
  }

  /* ---------------------------------------------------------------------
     The failure table
     --------------------------------------------------------------------- */
  const FAIL_COLS = [
    { key: 'index', label: 'Index', f: fmt },
    { key: 'dfn', label: 'Real.', f: fmt, many: true },
    { key: 'id', label: 'ID', f: (x) => String(x), text: true },
    { key: 'tFail', label: 'tFail (yr)', f: fmtYears },
    { key: 'tAdv', label: 'tAdv (yr)', f: (x) => (x < 1e-3 ? '0' : fmtYears(x)) },
    { key: 'tCorr', label: 'tCorr (yr)', f: fmtYears },
    { key: 'hs', label: '[HS⁻] (M)', f: (x) => fmt(x, 4) },
    { key: 'hsIndex', label: 'HS #', f: fmt },
    { key: 'f', label: 'F (yr/m)', f: (x) => fmt(x, 4) },
    { key: 'tw', label: 'tw (yr)', f: (x) => fmt(x, 4) },
    { key: 'q', label: 'q (m³/yr)', f: (x) => fmt(x, 4) },
    { key: 'edge', label: 'Edge', f: (x) => (x ? 'yes' : '') },
  ];

  function sortedRows(rows, sort) {
    const { key, asc } = sort;
    const out = rows.slice();
    out.sort((a, b) => {
      const x = a[key]; const y = b[key];
      let c;
      if (typeof x === 'number' && typeof y === 'number') c = x - y;
      else c = String(x).localeCompare(String(y), 'en', { numeric: true });
      return asc ? c : -c;
    });
    return out;
  }

  function renderFailures() {
    const host = $('ecFailTable');
    const empty = $('ecFailEmpty');
    if (!state.result) { host.innerHTML = ''; empty.hidden = false; empty.textContent = 'Run the model to get the table of failure times.'; return; }
    const rows = state.result.table;
    if (!rows.length) { host.innerHTML = ''; empty.hidden = false; empty.textContent = 'No canister fails within the assessment time with these settings.'; return; }
    empty.hidden = true;
    const many = state.result.results.length > 1;
    const cols = FAIL_COLS.filter((c) => !c.many || many);
    const sort = state.sort.failures;
    const head = cols.map((c) => `<th class="${c.text ? 'text ' : ''}${sort.key === c.key ? `sorted${sort.asc ? ' asc' : ''}` : ''}" data-on-click="ec:sortFailures" data-key="${c.key}">${esc(c.label)}</th>`).join('');
    const body = sortedRows(rows, sort).map((r) => `<tr>${cols.map((c) => `<td${c.text ? ' class="text"' : ''}>${esc(c.f(r[c.key]))}</td>`).join('')}</tr>`).join('');
    host.innerHTML = `<table class="ec-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }

  /** The failure table as the workbook's sheet "InputTrptCalcs", with the realisation added. */
  function failuresCsv() {
    const rows = state.result ? state.result.table : [];
    const lines = ['Index,Realisation,IDProb,tFailProb,FProb,twProb,qProb,tAdv,tCorr,HS,HSIndex,Edge'];
    for (const r of rows) lines.push([r.index, r.dfn, raw(r.id), r.tFail, r.f, r.tw, r.q, r.tAdv, r.tCorr, r.hs, r.hsIndex, r.edge ? 1 : 0].join(','));
    return lines.join('\n');
  }

  /* ---------------------------------------------------------------------
     The per-hole table (sheet "Calc")
     --------------------------------------------------------------------- */
  const HOLE_COLS = [
    { key: 'id', label: 'ID', get: (r, i) => r.id[i], f: (x) => String(x), text: true },
    { key: 'okflag', label: 'OKFLAG', get: (r, i) => r.columns.okflag[i], f: fmt },
    { key: 'u0', label: 'U0 (m/yr)', get: (r, i) => r.columns.u0[i], f: (x) => fmt(x, 4) },
    { key: 'trapp', label: 'δ (m)', get: (r, i) => r.columns.trapp[i], f: (x) => fmt(x, 4) },
    { key: 'flen', label: 'FLEN (m)', get: (r, i) => r.columns.flen[i], f: (x) => fmt(x, 4) },
    { key: 'fpc', label: 'FPC', get: (r, i) => r.columns.fpc[i], f: fmt },
    { key: 'efpc', label: 'EFPC', get: (r, i) => r.columns.efpc[i], f: fmt },
    { key: 'T', label: 'T (m²/s)', get: (r, i) => r.columns.transmissivity[i], f: (x) => fmt(x, 3) },
    { key: 'v', label: 'v (m/yr)', get: (r, i) => r.columns.v[i], f: (x) => fmt(x, 4) },
    { key: 'i', label: 'i (m/m)', get: (r, i) => r.columns.gradient[i], f: (x) => fmt(x, 3) },
    { key: 'q', label: 'q (m³/yr)', get: (r, i) => r.columns.qEb[i], f: (x) => fmt(x, 4) },
    { key: 'qeq', label: 'Qeq eroded (m³/yr)', get: (r, i) => r.columns.qeqEb[i], f: (x) => fmt(x, 4) },
    { key: 'qeqHydro', label: 'QEQ hydro (m³/yr)', get: (r, i) => r.columns.qeqHydro[i], f: (x) => fmt(x, 4) },
    { key: 'loss', label: 'Loss rate (kg/yr)', get: (r, i) => r.columns.lossRate[i], f: (x) => fmt(x, 4) },
    { key: 'tAdv', label: 'tAdv (yr)', get: (r, i) => r.columns.tAdv[i], f: (x) => (x < 1e-3 ? '0' : fmtYears(x)) },
    { key: 'hsMin', label: 'HSmin (M)', get: (r, i) => r.columns.hsMin[i], f: (x) => fmt(x, 3) },
    { key: 'tFailMin', label: 'tFailMin (yr)', get: (r, i) => r.columns.tFailMin[i], f: fmtYears },
    { key: 'nHs', label: '# HS', get: (r, i) => r.columns.nHsPoints[i], f: fmt },
    { key: 'reject', label: 'Rejected by', get: (r, i) => ECModel.rejectReasons(r.columns.rejectBits[i]).join(', '), f: (x) => x, text: true, cls: 'flag' },
    { key: 'skip', label: 'Skipped', get: (r, i) => (r.columns.skip[i] ? 'yes' : ''), f: (x) => x, text: true, cls: 'dim' },
    { key: 'edge', label: 'Edge', get: (r, i) => (r.columns.edge[i] ? 'yes' : ''), f: (x) => x, text: true, cls: 'dim' },
    { key: 'tw', label: 'tw (yr)', get: (r, i) => r.columns.tw[i], f: (x) => fmt(x, 4) },
    { key: 'F', label: 'F (yr/m)', get: (r, i) => r.columns.f[i], f: (x) => fmt(x, 4) },
    { key: 'tFresh', label: 'tFreshWater (yr)', get: (r, i) => r.columns.tFresh[i], f: (x) => (Number.isNaN(x) ? '' : fmtYears(x)) },
  ];

  const HOLE_FILTERS = {
    all: () => true,
    accepted: (r, i) => !r.columns.reject[i],
    rejected: (r, i) => !!r.columns.reject[i],
    advective: (r, i) => r.columns.tAdv[i] < r.key.tLim,
    failing: (r, i) => !r.columns.skip[i] && r.columns.nHsPoints[i] > 0,
    skipped: (r, i) => !!r.columns.skip[i],
    edge: (r, i) => !!r.columns.edge[i],
    flowing: (r, i) => r.columns.v[i] > 0,
  };

  function holeRows() {
    const res = state.result.results[Math.min(state.holes.real, state.result.results.length - 1)];
    const filter = HOLE_FILTERS[state.holes.filter] || HOLE_FILTERS.all;
    const search = state.holes.search.trim().toLowerCase();
    const rows = [];
    for (let i = 0; i < res.n; i++) {
      if (!filter(res, i)) continue;
      if (search && !String(res.id[i]).toLowerCase().includes(search)) continue;
      const row = { _i: i };
      for (const c of HOLE_COLS) row[c.key] = c.get(res, i);
      rows.push(row);
    }
    return { res, rows };
  }

  function renderHoles() {
    const host = $('ecHoleTable');
    const empty = $('ecHoleEmpty');
    const note = $('ecHoleNote');
    const realSel = $('ecHoleReal');
    if (!state.result) { host.innerHTML = ''; empty.hidden = false; note.textContent = ''; realSel.hidden = true; return; }
    empty.hidden = true;
    const many = state.result.results.length > 1;
    realSel.hidden = !many;
    if (many) {
      const sel = $('ecHoleRealSelect');
      sel.innerHTML = state.result.results.map((r, i) => `<option value="${i}">r${i + 1}: ${esc(state.hydro[i]?.name || '')}</option>`).join('');
      sel.value = String(Math.min(state.holes.real, state.result.results.length - 1));
    }
    const { rows } = holeRows();
    const sort = state.sort.holes;
    const sorted = sortedRows(rows, sort);
    const shown = sorted.slice(0, state.holes.limit);
    const head = HOLE_COLS.map((c) => `<th class="${c.text ? 'text ' : ''}${sort.key === c.key ? `sorted${sort.asc ? ' asc' : ''}` : ''}" data-on-click="ec:sortHoles" data-key="${c.key}">${esc(c.label)}</th>`).join('');
    const body = shown.map((r) => `<tr>${HOLE_COLS.map((c) => `<td class="${c.text ? 'text' : ''}${c.cls && r[c.key] ? ` ${c.cls}` : ''}">${esc(c.f(r[c.key]))}</td>`).join('')}</tr>`).join('');
    host.innerHTML = `<table class="ec-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    note.textContent = rows.length > shown.length
      ? `Showing ${shown.length.toLocaleString('en')} of ${rows.length.toLocaleString('en')} holes; the CSV has them all.`
      : `${rows.length.toLocaleString('en')} hole${rows.length === 1 ? '' : 's'}.`;
    $('ecHoleMore').hidden = rows.length <= shown.length;
  }

  function holesCsv() {
    const { rows } = holeRows();
    const lines = [HOLE_COLS.map((c) => c.label.replace(/ \(.*\)$/, '')).join(',')];
    for (const r of sortedRows(rows, state.sort.holes)) {
      lines.push(HOLE_COLS.map((c) => (c.text ? raw(r[c.key]) : raw(r[c.key]))).join(','));
    }
    return lines.join('\n');
  }

  /* ---------------------------------------------------------------------
     Charts
     --------------------------------------------------------------------- */
  const PLOT_CONFIG = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'] };
  const SERIES_COLORS = ['#bb6c5d', '#4e79a7', '#e0a458', '#59a14f', '#8e6c8a', '#76b7b2', '#d37295', '#9c755f'];

  function themeColors() {
    const cs = getComputedStyle(document.documentElement);
    return {
      text: cs.getPropertyValue('--text-primary').trim() || '#333',
      grid: cs.getPropertyValue('--border-color').trim() || '#ddd',
      surface: cs.getPropertyValue('--bg-surface').trim() || '#fff',
      muted: cs.getPropertyValue('--text-muted').trim() || '#888',
    };
  }

  function baseLayout() {
    const c = themeColors();
    return {
      margin: { l: 70, r: 70, t: 30, b: 60 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: c.text, size: 11 },
      legend: { orientation: 'h', y: -0.2, font: { size: 10 } },
      xaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid, exponentformat: 'power' },
      yaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid },
      hovermode: 'closest',
      hoverlabel: { bgcolor: c.surface, bordercolor: c.grid, font: { color: c.text, size: 11 } },
    };
  }

  function havePlotly() {
    if (typeof Plotly !== 'undefined') return true;
    return false;
  }

  function renderTime() {
    const plot = $('ecChartTime');
    const empty = $('ecTimeEmpty');
    if (!state.result || !havePlotly()) {
      plot.hidden = true; empty.hidden = false;
      empty.textContent = !havePlotly() ? 'The chart library (Plotly) did not load.' : 'Run the model to see the counts against time.';
      return;
    }
    empty.hidden = true;
    plot.hidden = false;
    const th = ECModel.timeHistory(state.result.results, 161, 100);
    const lim = state.result.results[0].params.tFailFilteringLim;
    const many = state.result.results.length > 1;
    const traces = [
      { x: th.t, y: th.nFail, name: `Mean number of failed canisters, corrected${many ? ' (mean over realisations)' : ''}`, mode: 'lines', line: { color: SERIES_COLORS[0], width: 2.2 }, hovertemplate: '%{y:.4g} at %{x:,.0f} yr<extra>failed, corrected</extra>' },
      { x: th.t, y: th.nFailHighestHs, name: 'Failed canisters at the highest sulphide concentration', mode: 'lines', line: { color: SERIES_COLORS[2], width: 1.6, dash: 'dot' }, hovertemplate: '%{y:.4g} at %{x:,.0f} yr<extra>failed at highest [HS⁻]</extra>' },
      { x: th.t, y: th.nAdv, name: 'Advective positions', mode: 'lines', yaxis: 'y2', line: { color: SERIES_COLORS[1], width: 2 }, hovertemplate: '%{y:.4g} at %{x:,.0f} yr<extra>advective</extra>' },
    ];
    const layout = baseLayout();
    const c = themeColors();
    layout.xaxis.type = 'log';
    layout.xaxis.title = { text: 'time after closure (years)', font: { size: 11 } };
    layout.xaxis.range = [2, Math.log10(lim)];
    layout.yaxis.title = { text: 'failed canisters', font: { size: 11 } };
    layout.yaxis.rangemode = 'tozero';
    layout.yaxis2 = { title: { text: 'advective positions', font: { size: 11 } }, overlaying: 'y', side: 'right', rangemode: 'tozero', gridcolor: 'rgba(0,0,0,0)', linecolor: c.grid, zeroline: false };
    layout.hovermode = 'x unified';
    layout.shapes = [{ type: 'line', x0: 1e5, x1: 1e5, y0: 0, y1: 1, yref: 'paper', line: { color: c.muted, width: 1, dash: 'dash' } }];
    layout.annotations = [{ x: 5, y: 1, yref: 'paper', text: '100,000 yr', showarrow: false, font: { size: 10, color: c.muted }, xanchor: 'left', yanchor: 'top' }];
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
  }

  function renderDistributions() {
    const plot = $('ecChartDist');
    const empty = $('ecDistEmpty');
    const realSel = $('ecDistReal');
    if (!state.result || !havePlotly()) {
      plot.hidden = true; empty.hidden = false; realSel.hidden = true;
      empty.textContent = !havePlotly() ? 'The chart library (Plotly) did not load.' : 'Run the model to see the distributions over the deposition holes.';
      return;
    }
    empty.hidden = true;
    plot.hidden = false;
    const results = state.result.results;
    const many = results.length > 1;
    realSel.hidden = !many;
    if (many) {
      const sel = $('ecDistRealSelect');
      sel.innerHTML = '<option value="all">all realisations pooled</option>' + results.map((r, i) => `<option value="${i}">r${i + 1}: ${esc(state.hydro[i]?.name || '')}</option>`).join('');
      sel.value = state.dist.real;
    }
    const which = state.dist.which;
    const chosen = many && state.dist.real !== 'all' ? [results[Number(state.dist.real)]] : results;
    const dists = chosen.map((r) => ECModel.distributions(r));
    const d0 = dists[0][which];
    if (!d0) return;
    const traces = [];
    d0.series.forEach((s, si) => {
      // Pool the same series over the chosen realisations.
      let values = s.values;
      if (dists.length > 1) {
        const total = dists.reduce((a, d) => a + d[which].series[si].values.length, 0);
        values = new Float64Array(total);
        let off = 0;
        for (const d of dists) { values.set(d[which].series[si].values, off); off += d[which].series[si].values.length; }
      }
      const e = ECModel.ecdf(values, 800);
      if (!e.x.length) return;
      traces.push({ x: e.x, y: e.y, name: s.name, mode: 'lines', line: { color: SERIES_COLORS[si % SERIES_COLORS.length], width: 2, shape: 'hv' },
        hovertemplate: '%{x:.3g}: %{y:.3f}<extra>' + esc(s.name) + '</extra>' });
    });
    const c = themeColors();
    d0.lines.forEach((l, li) => {
      if (!(l.x > 0)) return;
      traces.push({ x: [l.x, l.x], y: [0, 1], name: l.label, mode: 'lines', line: { color: c.muted, width: 1.2, dash: l.dash || 'solid' }, hoverinfo: 'name' });
    });
    const layout = baseLayout();
    layout.xaxis.type = 'log';
    layout.xaxis.title = { text: d0.xLabel, font: { size: 11 } };
    layout.yaxis.title = { text: 'cumulative probability over the deposition holes', font: { size: 11 } };
    layout.yaxis.range = [0, 1.02];
    layout.yaxis.dtick = 0.1;
    layout.title = { text: d0.title + (dists.length > 1 ? ` (${dists.length} realisations pooled)` : ''), font: { size: 12 }, x: 0.02, xanchor: 'left' };
    layout.margin.t = 34;
    layout.legend.y = -0.22;
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    $('ecDistNote').textContent = 'A curve starts where the holes with a non-zero value begin: the gap below it is the share of holes at zero (no flowing fracture, or set to zero after rejection). Holes in deformation zones (FPC = 2) are zero in every series.';
  }

  function resizePlots() {
    if (!havePlotly()) return;
    ['ecChartTime', 'ecChartDist'].forEach((id) => { const el = $(id); if (el && !el.hidden && el.data) Plotly.Plots.resize(el); });
  }

  /* ---------------------------------------------------------------------
     Excel and case files
     --------------------------------------------------------------------- */
  async function exportExcel() {
    if (!state.result) { setStatus('Nothing to export yet.', 'warn'); return; }
    if (typeof XlsxWriter === 'undefined' || typeof JSZip === 'undefined') {
      setStatus('The Excel writer did not load (JSZip or xlsxwrite.js); the CSV buttons still work.', 'error');
      return;
    }
    const { results, table, summary } = state.result;
    const lim = results[0].params.tFailFilteringLim;
    const xlsx = new XlsxWriter('erosion_corrosion.xlsx');
    // Case settings: every parameter, with the names it has elsewhere.
    const settings = [['Parameter', 'Value', 'Unit', 'Workbook name', 'Python name', 'Default', 'Description']];
    settings.push(['Hydro data', state.hydro.map((h) => h.name).join('; '), '', 'HydroFileName', 'hydro_file_name', '', '']);
    settings.push(['Sulphide distribution', ECHS.TABLES[state.hs.table] ? state.hs.table : state.hs.table, '', 'HSTabName', 'hs_tab_name', 'HSForsmark', `${results[0].key.nHs} values, highest ${results[0].key.hsMax}`]);
    for (const d of ECModel.PARAMS) settings.push([d.label, state.params[d.key], d.unit || '', d.xl || '', d.py || '', d.def, d.desc || '']);
    xlsx.writeData(settings, 'Case Settings');
    // Key outputs
    const key = [['Quantity', ...results.map((r, i) => `r${i + 1}`), ...(results.length > 1 ? ['min', 'mean', 'max'] : [])]];
    for (const kr of KEY_ROWS) {
      const row = [kr.label(lim.toLocaleString('en'))];
      results.forEach((r) => row.push(cellValue(r.key[kr.key])));
      if (results.length > 1) { const st = summary[kr.key]; row.push(...(st && typeof st === 'object' ? [cellValue(st.min), cellValue(st.mean), cellValue(st.max)] : ['', '', ''])); }
      key.push(row);
    }
    xlsx.writeData(key, 'Key Outputs');
    // Failure data: the InputTrptCalcs layout
    const fail = [['Index', 'Realisation', 'IDProb', 'tFailProb', 'FProb', 'twProb', 'qProb', 'tAdv', 'tCorr', 'HS', 'HSIndex', 'Edge']];
    for (const r of table) fail.push([r.index, r.dfn, r.id, r.tFail, r.f, r.tw, r.q, r.tAdv, r.tCorr, r.hs, r.hsIndex, r.edge ? 1 : 0]);
    xlsx.writeData(fail, 'Failure Data');
    // The per-hole sheet, one per realisation (the workbook's "Calc")
    results.forEach((res, ri) => {
      const rows = [HOLE_COLS.map((c) => c.label)];
      for (let i = 0; i < res.n; i++) rows.push(HOLE_COLS.map((c) => cellValue(c.get(res, i))));
      xlsx.writeData(rows, `Calc r${ri + 1}`.slice(0, 31));
    });
    // The sulphide table used
    xlsx.writeData([['[HS-] (mol/L), descending'], ...Array.from(results[0].hs, (x) => [x])], 'HSData');
    await xlsx.saveAs('erosion_corrosion.xlsx');
    setStatus('Excel workbook written.', 'ok');
  }

  function cellValue(x) {
    if (x === null || x === undefined) return '';
    if (typeof x === 'number') { if (Number.isNaN(x)) return ''; if (x >= 1e98) return 1e99; return x; }
    if (typeof x === 'boolean') return x ? 'yes' : 'no';
    return x;
  }

  function saveCase() {
    const doc = {
      app: 'kvot-erosion-corrosion', version: 1, saved: new Date().toISOString(),
      params: state.params, hs: state.hs, totalHoles: state.totalHoles,
      hydroFiles: state.hydro.map((h) => h.name), inflowList: state.inflow ? state.inflow.name : null,
    };
    download('erosion_corrosion_case.json', JSON.stringify(doc, null, 2), 'application/json');
  }

  async function openCaseFile(file) {
    let doc;
    try { doc = JSON.parse(await file.text()); } catch (e) { setStatus(`${file.name}: not a JSON case file.`, 'error'); return; }
    if (!doc || doc.app !== 'kvot-erosion-corrosion') { setStatus(`${file.name}: not a case file written by this page.`, 'error'); return; }
    const { params, unknown } = ECModel.normalise(doc.params || {});
    state.params = params;
    if (doc.hs && typeof doc.hs === 'object') {
      if (typeof doc.hs.table === 'string') state.hs.table = doc.hs.table;
      if (doc.hs.generic) Object.assign(state.hs.generic, doc.hs.generic);
      if (typeof doc.hs.customText === 'string') state.hs.customText = doc.hs.customText;
    }
    if (typeof doc.totalHoles === 'string') state.totalHoles = doc.totalHoles;
    $('ecTotalHoles').value = state.totalHoles;
    writeParamControls();
    writeHsControls();
    saveState();
    const missing = (doc.hydroFiles || []).filter((n) => !state.hydro.some((h) => h.name === n));
    let msg = `Case ${file.name} applied.`;
    if (unknown.length) msg += ` Unknown settings ignored: ${unknown.join(', ')}.`;
    if (missing.length) msg += ` It was made with hydro data not loaded here: ${missing.join(', ')}.`;
    // Run first, then put the case message in front of the run's own line:
    // a scheduled run would overwrite it a moment later.
    run();
    setStatus(`${msg} ${$('ecStatus').textContent}`, missing.length || unknown.length ? 'warn' : 'ok');
  }

  /* ---------------------------------------------------------------------
     The panel, the tabs and the drag handle
     --------------------------------------------------------------------- */
  function showTab(name) {
    state.tab = name;
    document.querySelectorAll('.ec-tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.ec-pane').forEach((p) => { p.hidden = p.dataset.pane !== name; });
    saveState();
    renderTab();
  }

  function renderTab() {
    switch (state.tab) {
      case 'summary': renderSummary(); break;
      case 'failures': renderFailures(); break;
      case 'time': renderTime(); resizePlots(); break;
      case 'distributions': renderDistributions(); resizePlots(); break;
      case 'holes': renderHoles(); break;
      default: break;
    }
    infoRefresh();
  }

  function initSideResize() {
    const handle = $('ecResize');
    const root = document.querySelector('.ec');
    if (state.sideWidth) root.style.setProperty('--ec-side-width', `${state.sideWidth}px`);
    let dragging = false;
    handle.addEventListener('pointerdown', (ev) => { dragging = true; handle.classList.add('active'); handle.setPointerCapture(ev.pointerId); });
    handle.addEventListener('pointermove', (ev) => {
      if (!dragging) return;
      const left = root.getBoundingClientRect().left;
      const w = Math.max(260, Math.min(680, ev.clientX - left));
      state.sideWidth = Math.round(w);
      root.style.setProperty('--ec-side-width', `${state.sideWidth}px`);
      resizePlots();
    });
    const end = () => { if (!dragging) return; dragging = false; handle.classList.remove('active'); saveState(); resizePlots(); };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    handle.addEventListener('dblclick', () => {
      state.sideWidth = DEFAULT_WIDTH;
      root.style.setProperty('--ec-side-width', `${DEFAULT_WIDTH}px`);
      saveState();
      resizePlots();
    });
  }

  function initSections() {
    document.querySelectorAll('details.ec-sec').forEach((sec) => {
      if (Object.prototype.hasOwnProperty.call(state.sections, sec.id)) sec.open = !!state.sections[sec.id];
      sec.addEventListener('toggle', () => { state.sections[sec.id] = sec.open; saveState(); });
    });
  }

  function initDrop() {
    const zone = $('ecDrop');
    const root = document.querySelector('.ec');
    let depth = 0;
    root.addEventListener('dragenter', (ev) => { ev.preventDefault(); depth++; zone.classList.add('over'); });
    root.addEventListener('dragover', (ev) => { ev.preventDefault(); });
    root.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) zone.classList.remove('over'); });
    root.addEventListener('drop', (ev) => {
      ev.preventDefault();
      depth = 0;
      zone.classList.remove('over');
      if (ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files.length) addHydroFiles(ev.dataTransfer.files);
    });
  }

  /** The parameter reference table on the Help tab, from the catalogue. */
  function renderParamReference() {
    const host = $('ecParamRef');
    if (!host) return;
    const rows = [];
    for (const g of ECModel.GROUPS) {
      const items = ECModel.PARAMS.filter((d) => d.group === g.id);
      if (!items.length) continue;
      rows.push(`<tr><th colspan="5">${esc(g.label)}</th></tr>`);
      for (const d of items) {
        const def = d.type === 'bool' ? (d.def ? 'on' : 'off') : (d.type === 'select' ? d.def : fmt(d.def, 6));
        rows.push(`<tr><td>${esc(d.label)}</td><td>${esc(def)}${d.unit ? ` ${esc(d.unit)}` : ''}</td><td><code>${esc(d.xl || '–')}</code></td><td><code>${esc(d.py || '–')}</code></td><td>${esc(d.desc || '')}</td></tr>`);
      }
    }
    host.innerHTML = `<table class="ec-ref"><thead><tr><th>Parameter</th><th>Default</th><th>Workbook name</th><th>Python attribute</th><th></th></tr></thead><tbody>${rows.join('')}</tbody></table>`;
  }

  /* ---------------------------------------------------------------------
     The (i) next to each setting, section heading and tab toolbar

     kvot-info.js draws the button and the panel; this is what they say.
     The parameters' topics come from the catalogue in ec-model.js (label,
     desc, info, optionInfo, unit, default, workbook and Python names), so a
     parameter added there gets its (i) with no change here. Topics that
     show a current value or choice are functions, read each time the
     panel is drawn; infoRefresh() redraws an open one after a change.
     --------------------------------------------------------------------- */
  const more = (label, id) => ({ label, id });
  const paras = (x) => [].concat(x ?? []).filter(Boolean);

  /** The Help heading a group's parameters link to, and the exceptions. */
  const HELP_FOR_GROUP = {
    rejection: more('Rejection', 'help-rejection'),
    buffer: more('Time to advective conditions', 'help-advective'),
    corrosion: more('Corrosion and the failure table', 'help-corrosion'),
    diffusive: more('The distribution plots', 'help-plots'),
    freshwater: more('Parameters', 'help-params'),
    misc: more('Parameters', 'help-params'),
  };
  const HELP_FOR_PARAM = {
    okFlagFiltering: more('Corrosion and the failure table', 'help-corrosion'),
    pessAperture: more('Parameters', 'help-params'),
    rDepHole: more('Flow at the hole', 'help-flow'),
    dWater: more('Flow at the hole', 'help-flow'),
    w: more('Flow at the hole', 'help-flow'),
    flowConcFact: more('Flow at the hole', 'help-flow'),
    hCan: more('The distribution plots', 'help-plots'),
    averageFlow: more('Parameters', 'help-params'),
    averageFlowFactor: more('Parameters', 'help-params'),
    nCanisters: more('Rejection', 'help-rejection'),
  };

  function infoRefresh() {
    if (typeof KvotInfo !== 'undefined') KvotInfo.refresh();
  }

  const unitText = (u) => (u === '−' ? '− (dimensionless)' : u);
  function valueText(d, v) {
    if (d.type === 'bool') return v ? 'on' : 'off';
    if (d.type === 'select') return String(v);
    return numberText(v);
  }

  function paramTopic(d) {
    const g = ECModel.GROUPS.find((x) => x.id === d.group);
    const v = state.params[d.key];
    const extra = paras(d.info);
    const lead = d.desc || extra.shift() || '';
    const sections = extra.length ? [{ text: extra }] : [];
    if (d.type === 'select') {
      const what = d.optionInfo || {};
      sections.push({ heading: 'Choices', choices: d.options.map(([val, label]) => [label, what[val] || '', v === val]) });
    }
    return {
      kicker: g ? g.label : 'Parameter',
      title: d.label,
      lead,
      facts: [
        ['Unit', d.type === 'number' || d.type === 'int' ? unitText(d.unit || '') : ''],
        ['Default', valueText(d, d.def)],
        ['Current value', `${valueText(d, v)}${v !== d.def ? ' (changed)' : ''}`],
        ['Workbook name', d.xl ? `\`${d.xl}\`` : 'none'],
        ['Python name', d.py ? `\`${d.py}\`` : 'none'],
      ],
      sections,
      more: HELP_FOR_PARAM[d.key] || HELP_FOR_GROUP[d.group] || more('Parameters', 'help-params'),
    };
  }

  function groupTopic(g) {
    const items = ECModel.PARAMS.filter((d) => d.group === g.id);
    const changed = items.filter((d) => state.params[d.key] !== d.def).length;
    const extra = paras(g.info);
    const lead = g.about || extra.shift() || '';
    return {
      kicker: 'Section',
      title: g.label,
      lead,
      facts: [['Parameters', String(items.length)], ['Changed from the default', changed ? String(changed) : 'none']],
      sections: extra.length ? [{ text: extra }] : [],
      more: HELP_FOR_GROUP[g.id] || more('Parameters', 'help-params'),
    };
  }

  /** A select's options as choices, the chosen one marked; `what` explains each by value. */
  function optionChoices(id, what, current) {
    const sel = $(id);
    return Array.from(sel ? sel.options : []).map((o) => [o.textContent, what[o.value] || '', o.value === current]);
  }

  function hsName() {
    const t = state.hs.table;
    if (ECHS.TABLES[t]) return t;
    return t === 'generic' ? 'generated' : 'custom list';
  }

  /** The topic of one parameter of the generated sulphide distribution. */
  function genTopic(title, key, unit, lead, source, text) {
    return {
      kicker: 'Sulphide',
      title,
      lead,
      facts: [
        ['Unit', unit],
        ['Default', numberText(ECHS.GENERIC_DEFAULTS[key])],
        ['Current value', numberText(state.hs.generic[key])],
        ['In the sources', source],
      ],
      sections: text ? [{ text }] : [],
      more: more('Sulphide', 'help-sulphide'),
    };
  }

  const HS_TABLE_WHAT = {
    HSForsmark: 'Forsmark groundwater, 46 values: 40 sulphide analyses and 6 below the detection limit, set to 10^−6.9 M. The PSAR base case, to the workbook’s digits.',
    HSLaxemar: 'Laxemar groundwater, 51 values: the distribution of the review version of the sulphide report, as the workbook holds it.',
    HSTest: 'The workbook’s table of ten values for the code test.',
    generic: 'A lognormal distribution drawn as midpoint quantiles, in place of the workbook’s one-point HSGeneric table. Its form and parameters appear under the list.',
    custom: 'Your own list of concentrations, typed or pasted under the list.',
  };
  const DIST_WHAT = {
    qeq: 'The hydro model’s equivalent flow rate for an intact buffer, with and without the addition for a thermally spalled zone (TR-10-66, equations 4-9 to 4-12), in m³/yr. The line is qlim.',
    corrDiff: 'Through an intact buffer at the fixed sulphide concentration, with and without spalling (TR-10-66, equation 4-19a), in µm/yr. The lines: the rate limited by diffusion in the buffer alone, and the copper thickness in 1,000,000 years.',
    erosion: 'The rate of the chosen buffer loss model, in kg/yr. The lines: the buffer loss for advection over the assessment time, and over the dilute fraction of it.',
    corrAdv: 'With the buffer eroded, at the fixed sulphide concentration, in µm/yr. The lines: the copper thickness in 1,000,000 and in 100,000 years.',
    gradient: 'The hydraulic gradient i = v·δ/T in the intersecting fracture, with T from the transmissivity law chosen.',
    aperture: 'TRAPP as read from the hydro file, in m.',
    velocity: 'v = U0·w/δ in the intersecting fracture, in m/yr.',
    tAdv: 'The time to advective conditions of the accepted holes with a flowing fracture, in years. The line is the assessment time.',
  };
  const HOLE_FILTER_WHAT = {
    all: 'Every hole of the realisation.',
    flowing: 'A fracture crosses the hole and the water in it moves: v > 0.',
    accepted: 'Not rejected by any criterion.',
    rejected: 'Rejected by at least one criterion; the column Rejected by names them.',
    advective: 'tAdv before the assessment time.',
    failing: 'The holes with rows in the failure table: not skipped, and at least one sulphide value fails the canister in time.',
    skipped: 'Left out of the failure table: rejected, unable to fail in time with failure time filtering on, or OKFLAG ≠ 0 with OKFLAG filtering on.',
    edge: 'Not rejected by EFPC, two rows from a hole that is, on a fracture of the same length and aperture.',
  };

  function infoTopics() {
    const t = {
      'sec:hydro': () => {
        const n = state.hydro.length;
        const holes = state.hydro.reduce((a, h) => a + h.table.n, 0);
        return {
          kicker: 'Section',
          title: 'Hydro data',
          lead: 'The deposition-hole tables of the hydrogeological modelling, one file per DFN realisation. Several files are several realisations of one case, evaluated with the same settings.',
          facts: [['Realisations', n ? String(n) : 'none loaded'], ['Holes', n ? holes.toLocaleString('en') : '']],
          sections: [
            { heading: 'What is read', text: 'Ten columns per hole: the position ID, OKFLAG, U0, QEQ, TW, F, TRAPP, FPC, EFPC and FLEN; other columns are ignored. The shape is recognised from the content, not the extension: ConnectFlow CSV or PTB, an Excel sheet of such a table, or a DarcyTools performance-measure table.' },
            { heading: 'The buttons', list: [
              '**Open…**, or a drop on the panel, adds files. A case file (`.json`) opened or dropped this way is applied instead.',
              'The × on a file removes that realisation; **Remove all** removes them all.',
              '**Save as CSV** saves what was read from each file as a CSV of the ten columns (POINT, OKFLAG, U0, QEQ, TW, F, TRAPP, FPC, EFPC, FLEN), one file per realisation.',
            ] },
            { heading: 'Keep in mind', text: 'The lines under a file say what was doubtful in it: a missing column, padding to the layout size, a value that would not parse. The files stay in the browser and are not kept after the visit; the settings are.' },
          ],
          more: more('Hydro files', 'help-hydro'),
        };
      },
      'set:totalHoles': () => ({
        kicker: 'Hydro data',
        title: 'Layout size for DarcyTools tables',
        lead: 'The number of deposition holes in the whole layout. A DarcyTools table lists only the holes with particles, and the normalisation counts every hole.',
        facts: [['Current value', state.totalHoles || 'blank'], ['Applies to', 'DarcyTools .dtpm and CSV tables']],
        sections: [{ text: [
          'The table is padded with empty holes to this size. Blank takes the `Total DHs:` line of a .dtpm file, and otherwise the number of holes in the file, which the note under the file then points out. A number here takes precedence over the file’s line; one smaller than the number of holes in the file is ignored.',
          'ConnectFlow tables are not affected: they list every hole.',
        ] }],
        more: more('Hydro files', 'help-hydro'),
      }),
      'set:inflow': () => ({
        kicker: 'Hydro data',
        title: 'Inflow-rejection list',
        lead: 'Hole IDs to reject for high inflow to the open repository (R-09-19). They are rejected only with **High inflow filtering** on, under Rejection of deposition holes.',
        facts: [
          ['Loaded', state.inflow ? `${state.inflow.name}, ${state.inflow.set.size.toLocaleString('en')} IDs` : 'none'],
          ['High inflow filtering', state.params.highFlowFiltering ? 'on' : 'off'],
        ],
        sections: [{ text: [
          'A text file of IDs, one per line or separated by commas, semicolons or spaces; lines that start with `#` are skipped. A line with a numeric ID and then 0 or 1 is read as a flag: 1 rejects the hole, 0 does not.',
          'The IDs are matched as text with the hole IDs of every realisation, loaded before or after the list, and the note under the buttons says how many matched. **Clear** removes the list. It is not kept after the visit.',
        ] }],
        more: more('Rejection', 'help-rejection'),
      }),

      'sec:hs': () => {
        let d = null;
        try { d = ECHS.describe(hsValues().values); } catch (e) { d = null; }
        const has = d && d.n;
        return {
          kicker: 'Section',
          title: 'Sulphide',
          lead: 'The distribution of sulphide concentration in the fracture water. Every accepted hole meets every value, and each value that fails the canister within the assessment time is one row of the failure table.',
          facts: [
            ['Distribution', hsName()],
            ['Values', has ? d.n.toLocaleString('en') : 'none'],
            ['Highest', has ? `${fmt(d.max, 3)} M` : ''],
            ['Mean', has ? `${fmt(d.mean, 3)} M` : ''],
            ['Lowest', has ? `${fmt(d.min, 3)} M` : ''],
          ],
          sections: [{ text: 'The mean number of failed canisters is the number of rows over the number of values: a hole contributes the fraction of the distribution that fails it in time. Only the values above a hole’s HSmin fail it, so the high end of the distribution decides the result.' }],
          more: more('Sulphide', 'help-sulphide'),
        };
      },
      'set:hsTable': () => ({
        kicker: 'Sulphide',
        title: 'Distribution [HS⁻]',
        lead: 'Which table of sulphide concentrations the holes meet.',
        facts: [['Default', 'HSForsmark'], ['Current value', hsName()], ['Workbook name', '`HSTabName`'], ['Python name', '`hs_tab_name`']],
        sections: [
          { heading: 'Choices', choices: optionChoices('ecHsTable', HS_TABLE_WHAT, state.hs.table) },
          { text: 'The table is sorted in descending order, and the j-th failure time of a hole uses the j-th highest value, as the workbook and the Python port read it. The Python port’s HSForsmark is rounded to six digits, which moves its failure times by about one part in a million from the workbook’s.' },
        ],
        more: more('Sulphide', 'help-sulphide'),
      }),
      'set:hsKind': () => ({
        kicker: 'Sulphide',
        title: 'Form',
        lead: 'Which kind of lognormal distribution is generated.',
        facts: [['Default', 'shifted lognormal'], ['Current value', state.hs.generic.kind === 'log10-normal' ? 'log10-normal' : 'shifted lognormal']],
        sections: [
          { heading: 'Choices', choices: optionChoices('ecHsKind', {
            'shifted-lognormal': 'The 2.4 Python port’s `_gen_hs_generic`: a lognormal with the given arithmetic mean and standard deviation, plus the shift.',
            'log10-normal': 'The @Risk workbook’s `10^RiskNormal(−5.79757, 0.63849)`: log10 [HS⁻] is normal with mean μ and standard deviation σ.',
          }, state.hs.generic.kind) },
          { text: 'Both are drawn as the midpoint quantiles (k − ½)/n, k = 1 … n, so the same parameters always give the same table. The 2.4 port draws random numbers with a fixed seed and the @Risk workbook samples a Latin hypercube; both approximate these quantiles.' },
        ],
        more: more('Sulphide', 'help-sulphide'),
      }),
      'set:hsMean': () => genTopic('Mean', 'mean', 'M', 'The arithmetic mean of the lognormal part, before the shift is added.', '`hs_generic_mean` of the 2.4 port',
        'With the standard deviation it gives the parameters of the underlying normal: σ² = ln(1 + (s.d./mean)²) and μ = ln(mean) − σ²/2.'),
      'set:hsStd': () => genTopic('Std. dev.', 'std', 'M', 'The standard deviation of the lognormal part, before the shift is added.', '`hs_generic_std` of the 2.4 port',
        'With the mean it gives the parameters of the underlying normal: σ² = ln(1 + (s.d./mean)²) and μ = ln(mean) − σ²/2.'),
      'set:hsShift': () => genTopic('Shift', 'shift', 'M', 'A concentration added to every value of the lognormal.', '`hs_generic_shift` of the 2.4 port',
        'It is also the lowest value the distribution can take.'),
      'set:hsMu': () => genTopic('μ', 'mu10', 'log10 M', 'The mean of log10 [HS⁻], with [HS⁻] in mol/L.', 'the first argument of `RiskNormal` in the @Risk workbook', ''),
      'set:hsSigma': () => genTopic('σ', 'sigma10', 'log10 units', 'The standard deviation of log10 [HS⁻].', 'the second argument of `RiskNormal` in the @Risk workbook', ''),
      'set:hsN': () => genTopic('Number of values', 'n', '', 'How many midpoint quantiles are drawn: the size of the generated table.', '`hs_generic_n` of the 2.4 port, 10,000 there',
        'Rounded, and kept between 1 and 200,000. More values resolve the high end of the distribution, where the failures come from, more finely; with 7000 holes a table of 10,000 values still takes well under a second.'),
      'set:hsCustom': () => {
        const c = ECHS.parseCustom(state.hs.customText);
        return {
          kicker: 'Sulphide',
          title: 'Concentrations, mol/L',
          lead: 'Your own table of sulphide concentrations, in mol/L.',
          facts: [['Values read', c.values.length.toLocaleString('en')], ['Dropped', c.dropped ? String(c.dropped) : 'none']],
          sections: [{ text: 'Separate the values with spaces, new lines, commas or semicolons. A comma inside a single number written without a dot, such as `1,2e-5`, is a decimal comma. Anything that is not a positive number is dropped, and the note under the box says how many were. The values are sorted highest first, as the model reads them.' }],
          more: more('Sulphide', 'help-sulphide'),
        };
      },

      'set:autoRun': () => ({
        kicker: 'Run',
        title: 'Run on every change',
        lead: 'On, the calculation runs again a moment after a setting changes. Off, a changed parameter or sulphide setting waits for **Run**, and the status says “Changed. Press Run.”',
        facts: [['Default', 'on'], ['Current value', state.autoRun ? 'on' : 'off']],
        sections: [
          { text: 'Loading or removing hydro files, the layout size, the inflow list, the fracture width w, Reset parameters and opening a case run the calculation at once either way.' },
          { heading: 'The buttons', list: [
            '**Run** calculates now.',
            '**Reset parameters** puts every parameter back to the PSAR workbook’s default. The sulphide choice and the hydro data stay as they are.',
            '**Save case** writes every parameter, the sulphide choice and the layout size as a JSON file, with the names of the hydro files and of the inflow list but not their data. **Open case…** reads such a file back, as does a drop on the panel, and the status names what in it could not be matched: settings it does not know, hydro files that are not loaded.',
          ] },
        ],
        more: more('Parameters', 'help-params'),
      }),

      'pane:failures': () => ({
        kicker: 'Tab',
        title: 'Failure times',
        lead: 'One row per hole and sulphide value that fails the canister within the assessment time: the workbook’s sheet “InputTrptCalcs”, the input to the radionuclide transport calculations.',
        facts: [['Rows', state.result ? state.result.table.length.toLocaleString('en') : 'not run yet']],
        sections: [
          { heading: 'Columns', list: [
            '`Index`: the row, in hole order and then by descending sulphide, as the workbook and the Python port write them.',
            '`Real.`: the realisation the row comes from, when more than one file is loaded.',
            '`tFail` = `tAdv` + `tCorr`, in years: the time to advective conditions and the time to corrode through, CorrHoleFact / (Qeq·[HS⁻]).',
            '`[HS⁻]` and `HS #`: the sulphide value and its rank in the table, highest first.',
            '`F`, `tw` and `q`: the transport resistance and the travel time from the hydro file, and the flow through the eroded hole.',
            '`Edge`: the hole is an EFPC edge position.',
          ] },
          { text: 'Click a heading to sort by it, and again to reverse the order.' },
          { heading: 'Saving', list: [
            '**CSV**: every row in Index order, whatever the sort on screen, at full precision: Index, Realisation, the workbook’s IDProb, tFailProb, FProb, twProb and qProb, then tAdv, tCorr, HS, HSIndex and Edge.',
            '**Excel**: one workbook with the case settings, the key outputs, this table, the per-hole sheet of each realisation and the sulphide table used.',
          ] },
        ],
        more: more('Corrosion and the failure table', 'help-corrosion'),
      }),
      'pane:time': {
        kicker: 'Tab',
        title: 'Against time',
        lead: 'How the counts build up after closure, on a log time axis from 100 years to the assessment time.',
        sections: [
          { heading: 'Curves', list: [
            '**Mean number of failed canisters, corrected**: the failure times before t, over the number of sulphide values, scaled to the canisters to normalise to over the accepted holes. At the assessment time it is the corrected mean of the Summary.',
            '**Failed canisters at the highest sulphide concentration**: the holes that would have failed by t if every hole met the highest value of the distribution; not corrected.',
            '**Advective positions**, on the right-hand axis: the holes whose buffer is advective by t.',
          ] },
          { text: 'With several realisations each curve is the mean over them. The dashed line marks 100,000 years.' },
        ],
        more: more('Corrosion and the failure table', 'help-corrosion'),
      },
      'pane:distributions': () => ({
        kicker: 'Tab',
        title: 'Distributions',
        lead: 'Cumulative distributions over the deposition holes, one quantity at a time, as the plot sheets of the workbook draw them.',
        sections: [
          { heading: 'Quantity', choices: optionChoices('ecDistWhich', DIST_WHAT, state.dist.which) },
          { heading: 'Realisation', text: 'With more than one file loaded: every realisation pooled into one distribution, or one of them.' },
          { heading: 'Reading the curves', text: [
            'Each quantity is drawn for all holes and again after rejection, where the rejected holes count as zero; the time to advective conditions is drawn once. A curve starts where the holes with a non-zero value begin, so the gap below it is the share of holes at zero. Holes in deformation zones (FPC = 2) are zero in both series.',
            'The workbook takes the percentiles 1 to 100 % and blanks the zeros; the page uses the sorted values themselves, which is the same picture without interpolation.',
          ] },
        ],
        more: more('The distribution plots', 'help-plots'),
      }),
      'pane:holes': () => ({
        kicker: 'Tab',
        title: 'Deposition holes',
        lead: 'Every hole of one realisation with every per-hole quantity of the calculation: the workbook’s sheet “Calc”.',
        sections: [
          { heading: 'Show', choices: optionChoices('ecHoleFilter', HOLE_FILTER_WHAT, state.holes.filter) },
          { text: '**ID** keeps the holes whose ID contains the text. **Realisation** picks the file, when more than one is loaded.' },
          { heading: 'Columns', list: [
            'OKFLAG, U0, δ (TRAPP), FLEN, FPC, EFPC, tw and F, as read from the hydro file.',
            'T, the transmissivity from TRAPP by the law chosen, and i, the hydraulic gradient.',
            'v, the water velocity in the fracture, and q, the flow through the eroded hole.',
            'Qeq eroded, the equivalent flow rate through the eroded buffer, and QEQ hydro, the hydro model’s own for an intact buffer.',
            'Loss rate, of the chosen buffer model, and tAdv, the time to advective conditions: never, or 1e+99 in the files, when the buffer does not become advective.',
            'HSmin, the sulphide concentration that fails the canister exactly at the assessment time; tFailMin, the failure time at the highest value of the table; # HS, how many values are above HSmin.',
            'Rejected by, Skipped and Edge: the criteria that reject the hole, whether it is left out of the failure table, and whether it is an EFPC edge position.',
            'tFreshWater, the time for dilute water to reach the hole, for the holes not skipped.',
          ] },
          { heading: 'Saving', text: 'The table shows 300 holes at first, and **Show more** adds 1000. **CSV** saves every hole that passes the filter and the ID search, sorted as shown, at full precision. The Excel export of the Failure times tab has every hole of every realisation.' },
        ],
        more: more('What happens to each hole', 'help-holes'),
      }),
    };
    for (const g of ECModel.GROUPS) t[`sec:${g.id}`] = () => groupTopic(g);
    for (const d of ECModel.PARAMS) t[`p:${d.key}`] = () => paramTopic(d);
    return t;
  }

  function setupInfo() {
    if (typeof KvotInfo === 'undefined') return;
    KvotInfo.setup({ topics: infoTopics(), onMore: () => showTab('help') });
  }

  /* ---------------------------------------------------------------------
     Actions
     --------------------------------------------------------------------- */
  registerActions({
    'ec:tab': (ev, el) => showTab(el.dataset.tab),
    'ec:run': () => run(),
    'ec:autoRunChanged': (ev, el) => { state.autoRun = el.checked; saveState(); infoRefresh(); if (state.autoRun) scheduleRun(0); },
    'ec:paramChanged': (ev, el) => { readParam(el); writeParamControls(); saveState(); scheduleRun(); if (el.dataset.key === 'w') reparseHydro(); },
    'ec:resetParams': () => { state.params = ECModel.defaults(); writeParamControls(); saveState(); scheduleRun(0); },
    'ec:hsChanged': () => { readHsControls(); saveState(); scheduleRun(); },
    'ec:openFiles': () => $('ecFile').click(),
    'ec:filesChosen': (ev, el) => { addHydroFiles(el.files); el.value = ''; },
    'ec:removeHydro': (ev, el) => {
      state.hydro.splice(Number(el.dataset.index), 1);
      renderHydroList();
      saveState();
      run();
    },
    'ec:clearHydro': () => { state.hydro = []; renderHydroList(); saveState(); run(); },
    'ec:hydroOptionChanged': (ev, el) => { state.totalHoles = el.value.trim(); saveState(); reparseHydro(); },
    'ec:openInflow': () => $('ecInflowFile').click(),
    'ec:inflowChosen': async (ev, el) => {
      const file = el.files && el.files[0];
      el.value = '';
      if (!file) return;
      const set = ECHydro.parseInflowList(await file.text());
      state.inflow = { name: file.name, set };
      let matched = 0;
      for (const h of state.hydro) matched += ECHydro.applyInflowList(h.table, set);
      $('ecInflowNote').textContent = `${file.name}: ${set.size} IDs, ${matched} matched in the loaded data.`;
      if (!state.params.highFlowFiltering) $('ecInflowNote').textContent += ' Turn on "High inflow filtering" to use it.';
      scheduleRun(0);
    },
    'ec:clearInflow': () => { state.inflow = null; for (const h of state.hydro) h.table.inflowReject = new Float64Array(h.table.n); $('ecInflowNote').textContent = 'none'; scheduleRun(0); },
    'ec:sortFailures': (ev, el) => {
      const key = el.dataset.key;
      const s = state.sort.failures;
      if (s.key === key) s.asc = !s.asc; else { s.key = key; s.asc = true; }
      renderFailures();
    },
    'ec:sortHoles': (ev, el) => {
      const key = el.dataset.key;
      const s = state.sort.holes;
      if (s.key === key) s.asc = !s.asc; else { s.key = key; s.asc = true; }
      renderHoles();
    },
    'ec:failuresCsv': () => { if (state.result) download('erosion_corrosion_failures.csv', failuresCsv()); },
    'ec:holesCsv': () => { if (state.result) download('erosion_corrosion_holes.csv', holesCsv()); },
    'ec:hydroCsv': () => { for (const h of state.hydro) download(h.name.replace(/\.[^.]+$/, '') + '_hydro.csv', ECHydro.toCsv(h.table)); },
    'ec:excel': () => exportExcel(),
    'ec:saveCase': () => saveCase(),
    'ec:openCase': () => $('ecCaseFile').click(),
    'ec:caseChosen': (ev, el) => { const f = el.files && el.files[0]; el.value = ''; if (f) openCaseFile(f); },
    'ec:distChanged': (ev, el) => {
      if (el.id === 'ecDistWhich') state.dist.which = el.value;
      if (el.id === 'ecDistRealSelect') state.dist.real = el.value;
      saveState();
      renderDistributions();
      infoRefresh();
    },
    'ec:holesChanged': (ev, el) => {
      if (el.id === 'ecHoleFilter') state.holes.filter = el.value;
      if (el.id === 'ecHoleSearch') state.holes.search = el.value;
      if (el.id === 'ecHoleRealSelect') state.holes.real = Number(el.value);
      state.holes.limit = 300;
      saveState();
      renderHoles();
      infoRefresh();
    },
    'ec:holesMore': () => { state.holes.limit += 1000; renderHoles(); },
  });

  /* ---------------------------------------------------------------------
     Boot
     --------------------------------------------------------------------- */
  loadState();
  buildParamSections();
  writeParamControls();
  writeHsControls();
  $('ecTotalHoles').value = state.totalHoles;
  $('ecAutoRun').checked = state.autoRun;
  $('ecDistWhich').value = state.dist.which;
  $('ecHoleFilter').value = state.holes.filter;
  setupInfo();
  initSideResize();
  initSections();
  initDrop();
  renderParamReference();
  renderHydroList();
  showTab(['failures', 'time', 'distributions', 'holes', 'help'].includes(state.tab) ? state.tab : 'summary');
  window.addEventListener('resize', resizePlots);
  document.documentElement.addEventListener('kvot-theme-change', () => renderTab());
  run();

  window.ECPage = Object.freeze({
    getState: () => state,
    run,
    fmt,
  });
}());
