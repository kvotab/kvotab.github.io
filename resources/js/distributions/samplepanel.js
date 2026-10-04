/* ==========================================================================
   distributions.html: THE SAMPLE TAB

   n draws of each chosen distribution by a scheme (sampling.js), with a
   seed: drawn in the page's worker, summarised against the distribution
   (mean, SD, percentiles, the ends, Kolmogorov-Smirnov's D), shown as
   histograms in the chart when asked, and saved as CSV or Excel, copied, or
   handed to the Fit tab.

   A sample is a function of its distribution, n, the scheme, the seed and
   the distribution's letter, so it is not stored: it is drawn again when
   the page opens. Draws are taken only while this tab is open or the chart
   shows them, by themselves up to 200,000 values in all and with Draw
   above that; a sample whose distribution or settings have changed since is
   not shown.
   ========================================================================== */

import { SCHEMES, SAMPLE_MAX, SAMPLE_TOTAL_MAX, SEQUENCE_DIMENSIONS, SAMPLE_PERCENTILES } from './sampling.js';
import { fmt, parseNum, csvText, download } from './format.js';
import { theme, slotStyle } from './chart.js';

const AUTO_MAX = 200000;
const PREVIEW_ROWS = 12;

/* ---- signatures ------------------------------------------------------------------------------- */

/* FNV-1a over the bits of the numbers: data are compared by content, not by
   writing a million numbers into a string */
const bits = new Float64Array(1);
const words = new Uint32Array(bits.buffer);
function digest(values) {
  let h = 0x811c9dc5;
  for (let i = 0; i < values.length; i++) {
    bits[0] = values[i];
    h = Math.imul(h ^ words[0], 0x01000193);
    h = Math.imul(h ^ words[1], 0x01000193);
  }
  return `${values.length}:${h >>> 0}`;
}

function specKey(spec) {
  const { data, ...rest } = spec;
  return JSON.stringify(rest) + (data ? `|${digest(data)}` : '');
}

/* ---- the panel ------------------------------------------------------------------------------- */

export function setupSample(app) {
  const $ = (id) => document.getElementById(id);
  const st = () => app.state.sample;
  const runs = new Map();     // key -> { sig, status, values, summary, ks, ksP, sorted, error }
  let job = null;             // the job in the worker: { id, keys }
  let timer = null;
  let jobCounter = 0;

  /* the settings in the boxes, read and checked */
  function settings() {
    const s = st();
    const n = parseNum(s.n);
    const seed = parseNum(s.seed);
    const scheme = SCHEMES.some(([k]) => k === s.scheme) ? s.scheme : 'random';
    return { n, seed, scheme, nOk: Number.isInteger(n) && n >= 1 && n <= SAMPLE_MAX, seedOk: Number.isInteger(seed) };
  }

  /** The distributions to draw: chosen, and with no error. */
  function chosen() {
    const skip = new Set(st().skip || []);
    return app.items().filter((it) => !skip.has(it.key));
  }

  function sigOf(it, set) {
    const r = app.derived(it.key);
    if (!r.spec) return null;
    return `${specKey(r.spec)}|${set.n}|${set.scheme}|${set.seed}|${it.letter}`;
  }

  /** Each chosen distribution with the signature its sample must have now. */
  function wanted() {
    const set = settings();
    if (!set.nOk || !set.seedOk) return { set, list: [] };
    return { set, list: chosen().filter((it) => it.D).map((it) => ({ it, sig: sigOf(it, set) })).filter((w) => w.sig) };
  }

  const active = () => app.state.tab === 'sample' || !!app.state.chart.showSamples;

  /* After any change: what is already drawn stays, what is not is drawn
     after a pause, by itself while the whole is small. */
  function update() {
    clearTimeout(timer);
    const keys = new Set(app.items().map((it) => it.key));
    for (const key of [...runs.keys()]) if (!keys.has(key)) runs.delete(key);
    if (!active()) return;
    const { set, list } = wanted();
    const missing = list.filter((w) => { const r = runs.get(w.it.key); return !r || r.sig !== w.sig; });
    if (!missing.length) return;
    if (set.n * list.length > AUTO_MAX) return;
    timer = setTimeout(() => draw(false), 250);
  }

  async function draw(manual) {
    clearTimeout(timer);
    const { set, list } = wanted();
    if (!set.nOk || !set.seedOk) { render(); return; }
    if (set.n * list.length > SAMPLE_TOTAL_MAX) {
      app.status(`At most ${SAMPLE_TOTAL_MAX.toLocaleString('en')} draws in all: ${list.length} distributions take at most ${Math.floor(SAMPLE_TOTAL_MAX / list.length).toLocaleString('en')} each.`, 'error');
      return;
    }
    if ((set.scheme === 'sobol' || set.scheme === 'halton') && list.some((w) => w.it.slot >= SEQUENCE_DIMENSIONS)) return;
    const todo = list.filter((w) => { const r = runs.get(w.it.key); return manual || !r || r.sig !== w.sig || r.status === 'error'; })
      .filter((w) => { const r = runs.get(w.it.key); return !(r && r.sig === w.sig && r.status === 'running'); });
    if (!todo.length) { render(); return; }
    const id = ++jobCounter;
    job = { id };
    for (const w of todo) runs.set(w.it.key, { sig: w.sig, status: 'running' });
    render();
    const payload = {
      items: todo.map((w) => ({ key: w.it.key, letter: w.it.letter, spec: app.derived(w.it.key).spec })),
      n: set.n, scheme: set.scheme, seed: set.seed,
    };
    const t0 = performance.now();
    try {
      const out = await app.runJob('sample', payload, (done, total, label) => {
        if (!job || job.id !== id) return;
        const bar = $('dsSampleProgress');
        bar.hidden = false;
        bar.firstElementChild.style.width = `${Math.round(100 * done / Math.max(total, 1))}%`;
        $('dsSampleState').textContent = `Drawing ${label} (${done + 1} of ${total})…`;
      });
      for (const col of out.columns) {
        const w = todo.find((x) => x.it.key === col.key);
        const r = runs.get(col.key);
        if (!w || !r || r.sig !== w.sig) continue;
        runs.set(col.key, { sig: w.sig, status: col.error ? 'error' : 'done', values: col.values || null, summary: col.summary || null, error: col.error || '', sorted: null });
      }
      if (job && job.id === id) {
        const ms = performance.now() - t0;
        const k = out.columns.filter((c) => c.values).length;
        $('dsSampleState').textContent = `${set.n.toLocaleString('en')} draws of ${k === 1 ? 'one distribution' : `each of ${k} distributions`} in ${ms < 1000 ? `${Math.max(1, Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`}.`;
      }
    } catch (e) {
      for (const w of todo) {
        const r = runs.get(w.it.key);
        if (r && r.sig === w.sig && r.status === 'running') runs.set(w.it.key, { sig: w.sig, status: 'error', error: e.message === 'stopped' ? 'stopped' : e.message });
      }
      if (job && job.id === id) $('dsSampleState').textContent = e.message === 'stopped' ? 'Stopped.' : `The draws failed: ${e.message}`;
    } finally {
      if (job && job.id === id) { job = null; $('dsSampleProgress').hidden = true; }
    }
    app.redraw();
  }

  /** The current sample of a distribution, or null. */
  function current(it, set = settings()) {
    const r = runs.get(it.key);
    if (!r || r.status !== 'done' || !r.values) return null;
    return r.sig === sigOf(it, set) ? r : null;
  }

  /** The summary of a distribution's current draws while the chart shows them, for the numbers under it. */
  function summaryFor(key, letter) {
    if (!app.state.chart.showSamples || (st().skip || []).includes(key)) return null;
    const r = current({ key, letter });
    return r ? r.summary : null;
  }

  /** A distribution's current draws, sorted, for the chart (items() asks, so nothing here asks items()). */
  function sortedSample(key, letter) {
    if (!app.state.chart.showSamples || (st().skip || []).includes(key)) return null;
    const r = current({ key, letter });
    if (!r) return null;
    if (!r.sorted) r.sorted = Float64Array.from(r.values).sort();
    return r.sorted;
  }

  /* ---- the tab ---- */

  function restore() {
    const s = st();
    $('dsSampleN').value = s.n;
    $('dsSampleSeed').value = s.seed;
    const sel = $('dsSampleScheme');
    if (!sel.options.length) for (const [k, label] of SCHEMES) sel.append(new Option(label, k));
    sel.value = SCHEMES.some(([k]) => k === s.scheme) ? s.scheme : 'random';
    $('dsSampleShow').checked = !!app.state.chart.showSamples;
  }

  function renderWhich() {
    const box = $('dsSampleWhich');
    box.replaceChildren();
    const skip = new Set(st().skip || []);
    const th = theme();
    for (const it of app.items()) {
      const label = document.createElement('label');
      label.className = 'ds-check';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = !skip.has(it.key);
      cb.dataset.key = it.key;
      cb.dataset.onChange = 'ds:sampleWhich';
      const key = document.createElement('span');
      const { colour, dash } = slotStyle(it.slot, th);
      key.className = 'ds-key' + (dash === 'dash' ? ' dashed' : '');
      key.style.setProperty('--ds-colour', colour);
      label.append(cb, key, document.createTextNode(it.name));
      box.append(label);
    }
  }

  function render() {
    if (app.state.tab !== 'sample') return;
    const set = settings();
    $('dsSampleN').setAttribute('aria-invalid', String(!set.nOk));
    $('dsSampleSeed').setAttribute('aria-invalid', String(!set.seedOk));
    renderWhich();
    const its = chosen();
    const msgs = [];
    if (!set.nOk) msgs.push(`The number of draws must be a whole number from 1 to ${SAMPLE_MAX.toLocaleString('en')}.`);
    if (!set.seedOk) msgs.push('The seed must be a whole number.');
    const total = set.nOk ? set.n * its.filter((it) => it.D).length : 0;
    if (total > SAMPLE_TOTAL_MAX) msgs.push(`At most ${SAMPLE_TOTAL_MAX.toLocaleString('en')} draws in all.`);
    if ((set.scheme === 'sobol' || set.scheme === 'halton') && its.some((it) => it.slot >= SEQUENCE_DIMENSIONS)) msgs.push(`The sequences have ${SEQUENCE_DIMENSIONS} dimensions, for the letters A to P.`);
    if (set.scheme === 'sobol' && set.nOk && (set.n & (set.n - 1)) !== 0) msgs.push('A Sobol sample is balanced when n is a power of two (512, 1024, 2048, …).');
    const missing = its.some((it) => it.D && !current(it, set) && !(runs.get(it.key) || {}).status?.startsWith('run'));
    if (set.nOk && set.seedOk && missing && total > AUTO_MAX && total <= SAMPLE_TOTAL_MAX) msgs.push(`${total.toLocaleString('en')} draws: press Draw to take them.`);
    const note = $('dsSampleNote');
    note.textContent = msgs.join(' ');
    note.hidden = !msgs.length;
    renderTable(its, set);
    renderPreview(its, set);
    const any = its.some((it) => current(it, set));
    for (const id of ['dsSampleCsv', 'dsSampleExcel', 'dsSampleCopy', 'dsSampleFit']) $(id).disabled = !any;
    const fitSel = $('dsSampleFitWhich');
    const keep = fitSel.value;
    fitSel.replaceChildren(...its.filter((it) => current(it, set)).map((it) => new Option(it.name, it.key)));
    if ([...fitSel.options].some((o) => o.value === keep)) fitSel.value = keep;
    $('dsSampleStop').hidden = !job;
  }

  function renderTable(its, set) {
    const table = $('dsSampleTable');
    table.replaceChildren();
    if (!its.length) return;
    const th = theme();
    const digits = Number(app.state.stats.digits) || 5;
    const head = table.createTHead().insertRow();
    const corner = document.createElement('th');
    corner.textContent = 'Drawn (exact)';
    head.append(corner);
    for (const it of its) {
      const c = document.createElement('th');
      const { colour, dash } = slotStyle(it.slot, th);
      const key = document.createElement('span');
      key.className = 'ds-key' + (dash === 'dash' ? ' dashed' : '');
      key.style.setProperty('--ds-colour', colour);
      c.append(key, document.createTextNode(it.name));
      head.append(c);
    }
    const body = table.createTBody();
    const cells = its.map((it) => {
      const r = runs.get(it.key);
      const cur = current(it, set);
      if (!it.D) return { text: it.pending ? 'waiting for its draws' : (it.error || 'not defined') };
      if (!cur) return { text: r && r.status === 'running' && r.sig === sigOf(it, set) ? 'drawing…' : r && r.status === 'error' && r.sig === sigOf(it, set) ? (r.error === 'stopped' ? 'stopped' : r.error) : 'not drawn' };
      return { r: cur, D: it.D };
    });
    const row = (label, f) => {
      const tr = body.insertRow();
      tr.insertCell().textContent = label;
      for (const c of cells) {
        const td = tr.insertCell();
        if (!c.r) { td.className = 'dim text'; td.textContent = label === 'Draws' ? c.text : ''; continue; }
        const [drawn, exact] = f(c.r.summary, c.D);
        const a = document.createElement('span');
        a.textContent = drawn;
        td.append(a);
        if (exact !== undefined) {
          const b = document.createElement('span');
          b.className = 'ds-exact';
          b.textContent = exact;
          td.append(b);
        }
      }
    };
    const stat = (D) => D.stats();
    row('Draws', (s) => [s.n.toLocaleString('en')]);
    row('Mean', (s, D) => [fmt(s.mean, digits), fmt(stat(D).mean, digits)]);
    row('Standard deviation', (s, D) => [fmt(s.sd, digits), fmt(stat(D).sd, digits)]);
    row('Minimum', (s, D) => [fmt(s.min, digits), fmt(D.support[0], digits)]);
    SAMPLE_PERCENTILES.forEach((p, i) => row(p === 50 ? 'Median' : `${p}th percentile`.replace('1th', '1st'), (s, D) => [fmt(s.q[i], digits), fmt(D.quantile(p / 100), digits)]));
    row('Maximum', (s, D) => [fmt(s.max, digits), fmt(D.support[1], digits)]);
    row('K–S D (p)', (s) => [`${fmt(s.ks, 3)} (${fmt(s.ksP, 2)})`]);
  }

  function renderPreview(its, set) {
    const table = $('dsSamplePreview');
    table.replaceChildren();
    const cols = its.map((it) => ({ it, r: current(it, set) })).filter((c) => c.r);
    if (!cols.length) return;
    const head = table.createTHead().insertRow();
    const corner = document.createElement('th');
    corner.textContent = 'Draw';
    head.append(corner);
    for (const c of cols) { const h = document.createElement('th'); h.textContent = c.it.letter; h.title = c.it.name; head.append(h); }
    const body = table.createTBody();
    const n = Math.min(PREVIEW_ROWS, cols[0].r.values.length);
    for (let i = 0; i < n; i++) {
      const tr = body.insertRow();
      tr.insertCell().textContent = String(i + 1);
      for (const c of cols) tr.insertCell().textContent = fmt(c.r.values[i], 8);
    }
  }

  /* ---- what is saved ---- */

  function columns() {
    const set = settings();
    return chosen().map((it) => ({ it, r: current(it, set) })).filter((c) => c.r);
  }
  function tableRows() {
    const cols = columns();
    const n = cols.length ? cols[0].r.values.length : 0;
    const rows = [cols.map((c) => c.it.name)];
    for (let i = 0; i < n; i++) rows.push(cols.map((c) => String(c.r.values[i])));
    return rows;
  }
  function fileStem() {
    const set = settings();
    return `samples-${set.scheme}-n${set.n}-seed${set.seed}`;
  }

  registerActions({
    'ds:sampleSetting': () => {
      const s = st();
      s.n = $('dsSampleN').value;
      s.seed = $('dsSampleSeed').value;
      s.scheme = $('dsSampleScheme').value;
      app.saveSoon();
      render();
      update();
    },
    'ds:sampleWhich': (ev, cb) => {
      const skip = new Set(st().skip || []);
      if (cb.checked) skip.delete(cb.dataset.key); else skip.add(cb.dataset.key);
      st().skip = [...skip];
      app.saveSoon();
      render();
      update();
      if (app.state.chart.showSamples) app.redraw();
    },
    'ds:sampleAll': () => { st().skip = []; app.saveSoon(); render(); update(); },
    'ds:sampleNone': () => { st().skip = app.items().map((it) => it.key); app.saveSoon(); render(); },
    'ds:sampleDraw': () => draw(true),
    'ds:sampleStop': () => { job = null; app.stopJobs(); },
    'ds:sampleShow': (ev, cb) => { app.setShowSamples(cb.checked); },
    'ds:sampleCsv': () => { if (columns().length) download(`${fileStem()}.csv`, csvText(tableRows())); },
    'ds:sampleCopy': async () => {
      const text = tableRows().map((r) => r.join('\t')).join('\n');
      try { await navigator.clipboard.writeText(text); app.status('The draws are copied, a column for each distribution.'); } catch (e) { app.status('The browser did not let the page copy; save them as CSV instead.', 'error'); }
    },
    'ds:sampleExcel': () => saveExcel(),
    'ds:sampleToFit': () => {
      const key = $('dsSampleFitWhich').value;
      const c = columns().find((x) => x.it.key === key);
      if (!c || !app.fitPanel) return;
      const set = settings();
      const scheme = SCHEMES.find(([k]) => k === set.scheme)[1].toLowerCase();
      app.fitPanel.setData(Array.from(c.r.values), `${set.n.toLocaleString('en')} draws of ${c.it.name} (${scheme}, seed ${set.seed})`);
      app.state.tab = 'fit';
      app.refresh();
    },
  });

  /* ---- Excel: the writer and JSZip are loaded the first time they are asked for ---- */

  let excelReady = null;
  function loadScript(src, integrity) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      if (integrity) { s.integrity = integrity; s.crossOrigin = 'anonymous'; }
      s.onload = () => resolve();
      s.onerror = () => reject(new Error(`${src} could not be loaded`));
      document.head.append(s);
    });
  }
  async function saveExcel() {
    const cols = columns();
    if (!cols.length) return;
    try {
      if (!excelReady) {
        excelReady = (async () => {
          if (!window.JSZip) await loadScript(JSZIP.src, JSZIP.integrity);
          /* the writer takes JSZip from the page as it loads, so JSZip first */
          if (!window.XlsxWriter) await loadScript('./resources/js/xlsxwrite.js?v=20261004');
        })();
      }
      await excelReady;
    } catch (e) {
      excelReady = null;
      app.status(`Excel could not be written: ${e.message}. Save as CSV instead.`, 'error');
      return;
    }
    const set = settings();
    const n = cols[0].r.values.length;
    const data = [];
    for (let i = 0; i < n; i++) data.push(cols.map((c) => c.r.values[i]));
    const scheme = SCHEMES.find(([k]) => k === set.scheme)[1];
    const about = [['Scheme', scheme, ''], ['Draws of each', n, ''], ['Seed', set.seed, '']];
    for (const c of cols) { const s = c.it.D.stats(); about.push([c.it.name, s.mean, s.sd]); }
    try {
      const xlsx = new window.XlsxWriter(`${fileStem()}.xlsx`);
      xlsx.writeData(data, 'Samples', { header: cols.map((c) => c.it.name) });
      xlsx.writeData(about, 'Settings', { header: ['', 'Exact mean (or the setting)', 'Exact SD'] });
      /* save() builds the file; handing it over is the page's to do */
      const blob = await xlsx.save();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${fileStem()}.xlsx`;
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      app.status(`Excel could not be written: ${e.message}. Save as CSV instead.`, 'error');
    }
  }

  restore();

  return {
    update,
    render,
    sortedSample,
    summaryFor,
    reset() { runs.clear(); restore(); render(); },
    syncShow() { $('dsSampleShow').checked = !!app.state.chart.showSamples; },
  };
}

/* The JSZip the site's other pages pin (rb.html, facsimile.html), for the Excel writer. */
const JSZIP = {
  src: 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js',
  integrity: 'sha384-+mbV2IY1Zk/X1p/nWllGySJSUN8uMs+gUAN10Or95UBH0fpj6GfKgPmgC5EXieXG',
};
