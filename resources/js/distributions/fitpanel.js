/* ==========================================================================
   distributions.html: THE FIT TAB

   Data in (pasted, opened or dropped; a column chosen when there are
   several), families fitted in the page's worker, the fits ranked, drawn
   against the data, and added to the list of distributions, alone or as an
   empirical distribution of the data themselves.

   A fit is redone by itself when the data or the settings change (after a
   pause, and for up to 20,000 values; above that, Fit and rank starts it),
   and an answer that arrives after the data have changed again is dropped.
   Results that no longer match the data and settings are dimmed and inert
   until the next fit replaces them, and cleared when no fit comes by itself.
   ========================================================================== */

import { CRITERIA, rankFits, whyNot, fittable, FIT_MIN_SAMPLE } from './fit.js';
import { familyById, parameterisationsOf } from './families.js';
import { describeSample, symbolOf } from './kit.js';
import { makeDistribution } from './dist.js';
import { fmt, parseNum, parseNumberList, parseColumns, csvText, download } from './format.js';
import { fitFigure, theme, PLOT_CONFIG, fillBins, syncBinsField } from './chart.js';

const AUTO_MAX = 20000;

export function setupFit(app) {
  const $ = (id) => document.getElementById(id);
  const st = () => app.state.fit;
  let parsed = { values: [], skipped: 0, columns: null, label: '' };
  let sample = null;
  let last = null;        // { sig, kind, results }
  let ranked = [];
  let chosen = [];        // result keys drawn in the diagnostics, in the order chosen
  let running = null;
  let autoTimer = null;
  let fileLabel = '';
  let sigNow = '';        // the signature of the data and settings in the boxes

  /* ---- the controls, from the stored settings ---- */
  const crit = $('dsFitCriterion');
  function fillCriteria(kind) {
    const keep = crit.value || st().criterion;
    crit.replaceChildren();
    for (const [key, label] of CRITERIA) {
      if (key === 'chi2p' && kind !== 'discrete') continue;
      if (['ad', 'cvm'].includes(key) && kind === 'discrete') continue;
      const o = document.createElement('option');
      o.value = key;
      o.textContent = label;
      crit.append(o);
    }
    crit.value = [...crit.options].some((o) => o.value === keep) ? keep : 'aic';
  }
  function restore() {
    const f = st();
    $('dsFitText').value = f.text || '';
    $('dsFitComma').checked = !!f.comma;
    for (const r of document.querySelectorAll('input[name="dsFitKind"]')) r.checked = r.value === f.kind;
    $('dsFitMle').checked = f.mle !== false;
    $('dsFitMom').checked = !!f.mom;
    $('dsFitTrials').value = f.trials || '';
    for (const r of document.querySelectorAll('input[name="dsFitPlot"]')) r.checked = r.value === (f.plot || 'pdf');
    $('dsFitPlotLogX').checked = !!f.plotLogx;
    fillBins($('dsFitBins'), $('dsFitBinsValue'), f.bins || { rule: 'fd', value: '' });
    fileLabel = f.fileLabel || '';
  }

  /* ---- the data ---- */
  function readData() {
    const f = st();
    const text = $('dsFitText').value;
    const comma = $('dsFitComma').checked;
    const cols = parseColumns(text, comma);
    const wrap = $('dsFitColumnWrap');
    const sel = $('dsFitColumn');
    if (cols && cols.columns.length > 1) {
      const keep = Math.min(Number(f.column) || 0, cols.columns.length - 1);
      sel.replaceChildren();
      cols.columns.forEach((c, i) => {
        const o = document.createElement('option');
        o.value = String(i);
        o.textContent = `${c.name} (${c.values.length})`;
        sel.append(o);
      });
      sel.value = String(keep);
      wrap.hidden = false;
      const c = cols.columns[keep];
      parsed = { values: c.values, skipped: c.skipped, columns: cols, label: `${fileLabel || 'the pasted table'}, column ${c.name}` };
    } else {
      wrap.hidden = true;
      const { values, skipped } = parseNumberList(text, comma);
      parsed = { values, skipped, columns: null, label: fileLabel || 'the fit data' };
    }
    sample = parsed.values.length ? describeSample(parsed.values) : null;
    const hint = $('dsFitParse');
    if (!text.trim()) hint.textContent = 'No data yet.';
    else hint.textContent = `${parsed.values.length.toLocaleString('en')} value${parsed.values.length === 1 ? '' : 's'} read` + (parsed.skipped ? `; ${parsed.skipped.toLocaleString('en')} entr${parsed.skipped === 1 ? 'y' : 'ies'} that ${parsed.skipped === 1 ? 'is' : 'are'} not a number skipped` : '') + '.';
    renderSummary();
  }

  function renderSummary() {
    const box = $('dsFitSummary');
    box.replaceChildren();
    if (!sample) return;
    const s = sample;
    const q = (p) => { const h = (s.n - 1) * p; const i = Math.floor(h); return s.x[i] + (h - i) * (s.x[Math.min(i + 1, s.n - 1)] - s.x[i]); };
    const chip = (label, v) => {
      const d = document.createElement('div');
      const b = document.createElement('b');
      b.textContent = v;
      const sp = document.createElement('span');
      sp.textContent = label;
      d.append(b, sp);
      box.append(d);
    };
    chip('n', s.n.toLocaleString('en'));
    chip('mean', fmt(s.mean));
    chip('SD (n − 1)', fmt(s.sd1));
    chip('minimum', fmt(s.min));
    chip('median', fmt(q(0.5)));
    chip('maximum', fmt(s.max));
    chip('skewness', fmt(s.skew, 4));
    chip('excess kurtosis', fmt(s.kurt, 4));
    chip('values', s.allInteger ? (s.nonneg ? 'counts' : 'whole numbers') : s.positive ? 'positive' : 'real');
  }

  /* ---- the settings ---- */
  function effectiveKind() {
    const k = (document.querySelector('input[name="dsFitKind"]:checked') || {}).value || 'auto';
    if (k !== 'auto') return k;
    return sample && sample.allInteger && sample.nonneg ? 'discrete' : 'continuous';
  }
  function trials() {
    const t = parseNum($('dsFitTrials').value);
    return Number.isInteger(t) && t > 0 ? t : null;
  }
  /* the choice of families is kept for each kind apart: null is all of them */
  function picks() {
    const f = st().families;
    return f && typeof f === 'object' && !Array.isArray(f) ? f : { continuous: null, discrete: null };
  }
  function chosenFamilies(kind) {
    const all = fittable(kind).map((f) => f.id);
    const pick = picks()[kind];
    return Array.isArray(pick) ? all.filter((id) => pick.includes(id)) : all;
  }
  function setPick(kind, ids) {
    const all = fittable(kind).map((f) => f.id);
    st().families = { ...picks(), [kind]: !ids || (ids.length === all.length && all.every((id) => ids.includes(id))) ? null : ids };
  }
  function options() {
    const kind = effectiveKind();
    const methods = [];
    if ($('dsFitMle').checked) methods.push('mle');
    if ($('dsFitMom').checked) methods.push('mom');
    return { kind, methods, families: chosenFamilies(kind), trials: trials() ?? undefined };
  }
  function saveSettings() {
    const f = st();
    f.text = $('dsFitText').value.length <= 2e6 ? $('dsFitText').value : '';
    f.comma = $('dsFitComma').checked;
    f.column = Number($('dsFitColumn').value) || 0;
    f.kind = (document.querySelector('input[name="dsFitKind"]:checked') || {}).value || 'auto';
    f.mle = $('dsFitMle').checked;
    f.mom = $('dsFitMom').checked;
    f.trials = $('dsFitTrials').value;
    f.criterion = crit.value;
    f.plot = (document.querySelector('input[name="dsFitPlot"]:checked') || {}).value || 'pdf';
    f.plotLogx = $('dsFitPlotLogX').checked;
    f.bins = { rule: $('dsFitBins').value, value: $('dsFitBinsValue').value };
    f.fileLabel = fileLabel;
    app.saveSoon();
  }

  function renderFamilies() {
    const kind = effectiveKind();
    const box = $('dsFitFamilies');
    box.replaceChildren();
    const fams = fittable(kind);
    const pick = new Set(chosenFamilies(kind));
    const opts = options();
    for (const fam of fams) {
      const why = sample ? whyNot(fam, sample, opts) : '';
      const label = document.createElement('label');
      if (why) label.className = 'unavailable';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = pick.has(fam.id);
      cb.dataset.family = fam.id;
      cb.dataset.onChange = 'ds:fitFamily';
      label.append(cb, document.createTextNode(fam.label + (why ? ` (${why})` : '')));
      box.append(label);
    }
    $('dsFitFamiliesCount').textContent = `${pick.size} of ${fams.length}`;
    $('dsFitTrialsRow').hidden = kind !== 'discrete';
    fillCriteria(kind);
  }

  /* ---- running ---- */
  function signature(opts) {
    let h = 0x811c9dc5;
    for (const v of parsed.values) { const t = String(v); for (let i = 0; i < t.length; i++) { h ^= t.charCodeAt(i); h = Math.imul(h, 0x01000193); } h ^= 44; }
    return `${h >>> 0}|${parsed.values.length}|${JSON.stringify(opts)}`;
  }

  const fitsByItself = () => !!(sample && sample.distinct && sample.n >= FIT_MIN_SAMPLE && sample.n <= AUTO_MAX);

  /* After a change: the next fit after a pause, or the old results cleared
     and the reason no fit comes. */
  function scheduleAuto() {
    clearTimeout(autoTimer);
    sigNow = signature(options());
    const current = !!(last && last.sig === sigNow);
    if (!current && !fitsByItself()) {
      last = null;
      chosen = [];
      if (!running) {
        $('dsFitState').textContent = !sample ? ''
          : sample.n < FIT_MIN_SAMPLE ? `Needs at least ${FIT_MIN_SAMPLE} values.`
            : !sample.distinct ? 'Every value is the same; there is nothing to fit.'
              : `${sample.n.toLocaleString('en')} values: press Fit and rank to fit them.`;
      }
    }
    renderResults();
    if (!current && fitsByItself()) autoTimer = setTimeout(() => run(false), 450);
  }

  async function run(manual) {
    clearTimeout(autoTimer);
    const state = $('dsFitState');
    if (!sample || sample.n < FIT_MIN_SAMPLE) {
      state.textContent = `Needs at least ${FIT_MIN_SAMPLE} values.`;
      last = null;
      renderResults();
      return;
    }
    if (!sample.distinct) { state.textContent = 'Every value is the same; there is nothing to fit.'; last = null; renderResults(); return; }
    const opts = options();
    const sig = signature(opts);
    sigNow = sig;
    if (!opts.methods.length || !opts.families.length) {
      state.textContent = opts.methods.length ? 'Choose at least one family.' : 'Choose a method.';
      last = null;
      chosen = [];
      renderResults();
      return;
    }
    if (last && last.sig === sig && !manual) { renderResults(); return; }
    /* what is fitted, kept as it was when the fit started */
    const values = parsed.values.slice();
    const label = parsed.label;
    const me = { sig };
    running = me;
    const bar = $('dsFitProgress');
    bar.hidden = false;
    bar.firstElementChild.style.width = '0%';
    $('dsFitRun').disabled = true;
    $('dsFitStop').hidden = false;
    state.textContent = 'Fitting…';
    const t0 = performance.now();
    let outdated = false;
    try {
      const out = await app.runJob('fit', { values, opts }, (done, total, what) => {
        if (running !== me) return;
        bar.firstElementChild.style.width = `${Math.round(100 * done / Math.max(total, 1))}%`;
        state.textContent = what ? `Fitting the ${what.toLowerCase()} (${done + 1} of ${total})…` : 'Ranking…';
      });
      if (running !== me) return;
      /* the data or the settings changed while it ran: this answer is dropped */
      if (signature(options()) !== sig) outdated = true;
      else {
        last = { sig, kind: out.kind, results: out.results, values: Float64Array.from(values).sort(), label };
        const ok = out.results.filter((r) => !r.why).length;
        state.textContent = `${ok} fit${ok === 1 ? '' : 's'} in ${((performance.now() - t0) / 1000).toFixed(1)} s.`;
        chosen = [];
      }
    } catch (e) {
      if (running !== me) return;
      state.textContent = e.message === 'stopped' ? 'Stopped.' : `The fit failed: ${e.message}`;
    } finally {
      if (running === me) {
        running = null;
        bar.hidden = true;
        $('dsFitRun').disabled = false;
        $('dsFitStop').hidden = true;
      }
    }
    if (outdated) { scheduleAuto(); return; }
    renderResults();
  }

  /* ---- the results ---- */
  const keyOf = (r) => `${r.family}|${r.method}`;

  function paramText(r, sig = 5) {
    const fam = familyById(r.family);
    return fam.params.map((p) => {
      const v = r.params[p.key];
      const se = r.se && r.se[p.key];
      return `${symbolOf(p)} = ${fmt(v, sig)}${se ? ` ± ${fmt(se, 2)}` : ''}`;
    }).join(', ');
  }

  function renderResults() {
    const box = $('dsFitResults');
    const table = $('dsFitTable');
    if (!last) { box.hidden = true; table.replaceChildren(); return; }
    box.hidden = false;
    const stale = last.sig !== sigNow;
    box.inert = stale;
    box.classList.toggle('stale', stale);
    const criterion = crit.value;
    ranked = rankFits(last.results, criterion);
    if (!chosen.length) chosen = ranked.filter((r) => !r.why).slice(0, 3).map(keyOf);
    const discrete = last.kind === 'discrete';
    const info = ['aic', 'aicc', 'bic'].includes(criterion);
    const cols = [
      ['plot', 'Draw'], ['rank', '#'], ['name', 'Distribution'], ['params', 'Parameters'], ['logL', 'Log L', 'logL'],
      ['aic', 'AIC', 'aic'], ['aicc', 'AICc', 'aicc'], ['bic', 'BIC', 'bic'], ['delta', 'Δ'], ['weight', 'Weight'],
      ['ks', 'K–S D (p)', 'ks'],
      ...(discrete ? [['chi2', 'χ² (df) p', 'chi2p']] : [['ad', 'A² (p)', 'ad'], ['cvm', 'W²', 'cvm']]),
      ['note', 'Note'], ['add', ''],
    ];
    table.replaceChildren();
    const head = table.createTHead().insertRow();
    for (const [key, label, sortKey] of cols) {
      const th = document.createElement('th');
      th.textContent = label;
      if (sortKey) {
        th.classList.add('sortable');
        th.dataset.criterion = sortKey;
        th.dataset.onClick = 'ds:fitSortBy';
        th.tabIndex = 0;
        if (sortKey === criterion) th.classList.add('sorted');
      }
      if (key === 'params' || key === 'name' || key === 'note') th.classList.add('text');
      head.append(th);
    }
    const body = table.createTBody();
    const tm = theme();
    for (const r of ranked) {
      const tr = body.insertRow();
      if (r.why) tr.classList.add('failed');
      else if (r.rank === 1) tr.classList.add('best');
      for (const [key] of cols) {
        const td = tr.insertCell();
        if (key === 'plot') {
          if (!r.why) {
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = chosen.includes(keyOf(r));
            cb.dataset.key = keyOf(r);
            cb.dataset.onChange = 'ds:fitToggle';
            cb.setAttribute('aria-label', `Draw ${r.label} (${r.method === 'mle' ? 'maximum likelihood' : 'moments'})`);
            const at = chosen.indexOf(keyOf(r));
            if (at >= 0 && at < 8) { cb.style.setProperty('--check-fill', tm.series[at]); }
            td.append(cb);
          }
          continue;
        }
        if (key === 'rank') { td.textContent = r.why ? '' : String(r.rank); continue; }
        if (key === 'name') { td.className = 'text'; td.textContent = `${r.label} (${r.method === 'mle' ? 'MLE' : 'MOM'})`; continue; }
        if (key === 'params') { td.className = 'text'; td.textContent = r.why ? '' : paramText(r); continue; }
        if (key === 'note') { td.className = 'text wrap'; td.textContent = r.why ? `Not fitted: ${r.why}` : (r.note || '') + (r.outside ? `${r.note ? '; ' : ''}${r.outside} value${r.outside === 1 ? '' : 's'} outside its support` : ''); continue; }
        if (key === 'add') {
          if (!r.why) {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'ds-btn small secondary';
            b.textContent = 'Add';
            b.dataset.key = keyOf(r);
            b.dataset.onClick = 'ds:fitAdd';
            b.setAttribute('aria-label', `Add ${r.label} (${r.method.toUpperCase()}) to the distributions`);
            td.append(b);
          }
          continue;
        }
        if (r.why) { td.textContent = ''; continue; }
        if (key === 'logL') td.textContent = fmt(r.logL, 6);
        else if (key === 'aic' || key === 'aicc' || key === 'bic') td.textContent = fmt(r[key], 6);
        else if (key === 'delta') td.textContent = Number.isFinite(r.delta) ? fmt(r.delta, 4) : '—';
        else if (key === 'weight') td.textContent = info && Number.isFinite(r.weight) ? fmt(r.weight, 3) : '—';
        else if (key === 'ks') td.textContent = `${fmt(r.ks, 4)}${Number.isFinite(r.ksP) ? ` (${fmt(r.ksP, 2)})` : ''}`;
        else if (key === 'ad') td.textContent = `${fmt(r.ad, 4)}${Number.isFinite(r.adP) ? ` (${fmt(r.adP, 2)})` : ''}`;
        else if (key === 'cvm') td.textContent = fmt(r.cvm, 4);
        else if (key === 'chi2') td.textContent = Number.isFinite(r.chi2) ? `${fmt(r.chi2, 4)} (${r.chi2df}) ${Number.isFinite(r.chi2p) ? fmt(r.chi2p, 3) : '—'}` : '—';
      }
    }
    drawPlot();
  }

  function drawPlot() {
    const div = $('dsFitPlot');
    if (!last || $('dsFitResults').hidden) return;
    const kind = (document.querySelector('input[name="dsFitPlot"]:checked') || {}).value || 'pdf';
    const th = theme();
    const fits = [];
    chosen.forEach((key, i) => {
      const r = ranked.find((x) => keyOf(x) === key);
      if (!r || r.why || i >= 8) return;
      try {
        fits.push({ key, name: `${r.label} (${r.method.toUpperCase()})`, colour: th.series[i], D: makeDistribution({ family: r.family, params: r.params }) });
      } catch (e) { /* not drawable */ }
    });
    const bins = { rule: $('dsFitBins').value, value: $('dsFitBinsValue').value };
    syncBinsField($('dsFitBins'), $('dsFitBinsValue'), bins);
    /* the bins matter to the density plot only */
    $('dsFitBinsWrap').hidden = kind !== 'pdf';
    if (kind !== 'pdf') $('dsFitBinsValue').hidden = true;
    const fig = fitFigure(last.values, fits, kind, th, $('dsFitPlotLogX').checked, bins);
    Plotly.react(div, fig.data, fig.layout, PLOT_CONFIG);
  }

  /* ---- adding ---- */
  function addResult(r) {
    const fam = familyById(r.family);
    const par = parameterisationsOf(fam)[0];
    let v;
    try { v = par.from(r.params); } catch (e) { v = r.params; }
    const values = {};
    for (const f of par.fields) values[f.key] = String(v[f.key]);
    const d = app.addFromPanel((x) => {
      x.kind = 'family';
      x.family = r.family;
      x.param = par.id;
      x.values = { [par.id]: values };
      x.data = Array.from(last.values);
      x.dataLabel = last.label;
      x.name = `${r.label} (${r.method.toUpperCase()})`;
      x.fitInfo = { method: r.method, n: last.values.length, logL: r.logL, aic: r.aic, se: r.se || null };
    });
    if (d) app.status(`Added as ${app.fullName(d)}.`);
  }

  function addEmpirical(method) {
    if (!sample || sample.n < 2) { app.status('Enter at least two values first.', 'error'); return; }
    const d = app.addFromPanel((x) => {
      x.kind = 'empirical';
      x.emp.method = method;
      x.data = Array.from(parsed.values);
      x.dataLabel = parsed.label;
      x.name = '';
    });
    if (d) app.status(`Added as ${app.fullName(d)}.`);
  }

  /* ---- files ---- */
  async function readFile(file) {
    if (!file) return;
    if (file.size > 50 * 1024 * 1024) { app.status(`${file.name} is larger than 50 MB.`, 'error'); return; }
    const text = await file.text();
    fileLabel = file.name;
    $('dsFitText').value = text;
    st().column = 0;
    changed();
  }

  function changed() {
    readData();
    renderFamilies();
    saveSettings();
    scheduleAuto();
  }

  const drop = $('dsFitDrop');
  drop.addEventListener('dragover', (ev) => {
    if (ev.dataTransfer && [...ev.dataTransfer.types].includes('Files')) { ev.preventDefault(); drop.classList.add('dragover'); }
  });
  drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
  drop.addEventListener('drop', (ev) => {
    drop.classList.remove('dragover');
    const file = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
    if (!file) return;
    ev.preventDefault();
    readFile(file);
  });

  registerActions({
    'ds:fitData': () => { fileLabel = ''; changed(); },
    'ds:fitOpen': () => $('dsFitFile').click(),
    'ds:fitFile': (ev, input) => { const f = input.files && input.files[0]; input.value = ''; readFile(f); },
    'ds:fitClear': () => { $('dsFitText').value = ''; fileLabel = ''; changed(); },
    'ds:fitSetting': () => { changed(); },
    'ds:fitRank': () => { saveSettings(); renderResults(); KvotInfo.refresh(); },
    'ds:fitSortBy': (ev, th) => { if ([...crit.options].some((o) => o.value === th.dataset.criterion)) { crit.value = th.dataset.criterion; saveSettings(); renderResults(); } },
    'ds:fitFamily': (ev, cb) => {
      const kind = effectiveKind();
      const cur = new Set(chosenFamilies(kind));
      if (cb.checked) cur.add(cb.dataset.family); else cur.delete(cb.dataset.family);
      setPick(kind, [...cur]);
      renderFamilies();
      saveSettings();
      scheduleAuto();
    },
    'ds:fitAllFamilies': () => { setPick(effectiveKind(), null); renderFamilies(); saveSettings(); scheduleAuto(); },
    'ds:fitNoFamilies': () => { setPick(effectiveKind(), []); renderFamilies(); saveSettings(); scheduleAuto(); },
    'ds:fitRun': () => run(true),
    'ds:fitStop': () => { running = null; app.stopJobs(); $('dsFitState').textContent = 'Stopped.'; $('dsFitProgress').hidden = true; $('dsFitRun').disabled = false; $('dsFitStop').hidden = true; },
    'ds:fitAdd': (ev, b) => { const r = ranked.find((x) => keyOf(x) === b.dataset.key); if (r) addResult(r); },
    'ds:fitAddBest': () => { const r = ranked.find((x) => !x.why); if (r) addResult(r); },
    'ds:fitToggle': (ev, cb) => {
      const key = cb.dataset.key;
      if (cb.checked) { if (!chosen.includes(key)) chosen.push(key); } else chosen = chosen.filter((k) => k !== key);
      if (chosen.length > 8) { chosen = chosen.slice(0, 8); app.status('At most eight fits are drawn at once.'); }
      renderResults();
    },
    'ds:fitPlot': () => { saveSettings(); drawPlot(); },
    'ds:fitEmpirical': (ev, b) => addEmpirical(b.dataset.method),
    'ds:fitCsv': () => {
      if (!ranked.length) return;
      const rows = [['Rank', 'Family', 'Method', 'Parameters', 'Standard errors', 'Log L', 'AIC', 'AICc', 'BIC', 'Delta', 'Weight', 'K-S D', 'K-S p', 'A2', 'A2 p', 'W2', 'Chi2', 'Chi2 df', 'Chi2 p', 'Note']];
      for (const r of ranked) {
        if (r.why) { rows.push(['', r.label, r.method, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', `not fitted: ${r.why}`]); continue; }
        const fam = familyById(r.family);
        rows.push([r.rank, r.label, r.method,
          fam.params.map((p) => `${p.key}=${r.params[p.key]}`).join('; '),
          r.se ? Object.entries(r.se).map(([k, v]) => `${k}=${v}`).join('; ') : '',
          r.logL, r.aic, r.aicc, r.bic, r.delta, r.weight, r.ks, r.ksP, r.ad, r.adP, r.cvm, r.chi2, r.chi2df, r.chi2p, r.note || ''].map((v) => (typeof v === 'number' ? (Number.isFinite(v) ? String(v) : '') : v)));
      }
      download('distribution-fits.csv', csvText(rows));
    },
  });

  restore();
  readData();
  renderFamilies();
  sigNow = signature(options());

  return {
    render() {
      if (fitsByItself() && !running && !(last && last.sig === sigNow)) run(false);
      else renderResults();
    },
    reset() {
      restore();
      last = null;
      chosen = [];
      readData();
      renderFamilies();
      sigNow = signature(options());
      $('dsFitState').textContent = '';
      renderResults();
    },
    /** Data handed over by another panel (a random sample). */
    setData(values, label) {
      $('dsFitText').value = values.join('\n');
      fileLabel = label;
      $('dsFitComma').checked = false;
      changed();
    },
  };
}
