/*
  dose_coefficients.html: batch calculations, the Batch tab.

  One system and one route; radionuclides typed, pasted or picked from a list
  (picker.js; in the field an element's symbol stands for all its nuclides in
  the system), each with all its forms for the route or only its default one,
  for inhalation at each aerosol size chosen (a gas or vapour has none), at
  each age at intake chosen, with the tab's own decay chain cut-off and
  tolerance. Every combination at every age is one request to the page's
  pool of workers (ui.js), at the lowest rank, so that a single calculation
  started meanwhile goes first. The results fill one table as they come.

  The workers return the effective dose and every equivalent dose of each
  age, so what the table shows -- the results, the ages as columns or a row
  for each age, the digits -- is set apart, under the progress bar, and
  changing it calculates nothing. The table saves as CSV or as an Excel
  workbook (xlsxwrite.js and JSZip, loaded when first needed).

  Everything that comes from data or from the field is put in the page as
  text nodes.
*/
import { openPicker } from './picker.js';

export const AGES = [100, 365, 1825, 3650, 5475, 7300];
const MAX_SHOWN = 1000; // rows drawn in the page; the files hold them all
const JSZIP = {
  src: 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js',
  integrity: 'sha384-+mbV2IY1Zk/X1p/nWllGySJSUN8uMs+gUAN10Or95UBH0fpj6GfKgPmgC5EXieXG',
};
const ROUTES = [['ingestion', 'Ingestion'], ['inhalation', 'Inhalation'], ['injection', 'Injection']];
// As the settings' Calculation section has them.
const CUTOFFS = [['0', 'none: the whole chain'], ['1e-5', '0.001 %'], ['1e-4', '0.01 %'], ['1e-3', '0.1 %']];
const RTOLS = [['1e-4', '1E-4 (faster)'], ['1e-6', '1E-6'], ['1e-8', '1E-8 (slower)']];
const QUANTITIES = [
  ['e', 'Effective dose, e'],
  ['weighted', 'Equivalent doses of the tissues weighted in e, and the remainder'],
  ['remainder', 'Equivalent doses of the remainder’s tissues'],
  ['other', 'Other equivalent doses'],
  ['sexes', 'Male and female as well (ICRP 103 system)'],
];
const DOSES = ['weighted', 'remainder', 'other']; // what "male and female as well" applies to
const textOf = (list, v) => list.find(([k]) => k === v)?.[1].replace(/ \(.*\)$/, '') || v;

/**
 * @param {object} ctx  from ui.js: {h, $, ask, stopRank, RANK, POOL_SIZE, sci, halfLife, AGE_LABEL,
 *   TISSUES: {60, 103} (the tissue lists of the Coefficients tab), SIZES: {60, 103} (aerosol sizes),
 *   catalog(system), system() (the settings' system), defaults() ({cutoff, rtol} of the settings),
 *   saved (the stored settings of the tab), onSave(), onProgress(text|null), visible()}
 */
export function setupBatch(ctx) {
  const { h, $, ask, stopRank, RANK, sci, halfLife, AGE_LABEL, TISSUES, SIZES } = ctx;
  const saved = ctx.saved || {};
  const side = ctx.defaults();
  const B = {
    system: saved.system === '60' || saved.system === '103' ? saved.system : ctx.system(),
    route: ROUTES.some(([r]) => r === saved.route) ? saved.route : 'ingestion',
    text: typeof saved.text === 'string' ? saved.text : 'Cs-137, Sr-90, I-131',
    forms: saved.forms === 'default' ? 'default' : 'all',
    sizes: new Set(Array.isArray(saved.sizes) ? saved.sizes.map(String) : ['1']),
    ages: new Set(Array.isArray(saved.ages) ? saved.ages.map(Number).filter((a) => AGES.includes(a)) : AGES),
    cutoff: CUTOFFS.some(([v]) => v === saved.cutoff) ? saved.cutoff : CUTOFFS.some(([v]) => v === side.cutoff) ? side.cutoff : '1e-4',
    rtol: RTOLS.some(([v]) => v === saved.rtol) ? saved.rtol : RTOLS.some(([v]) => v === side.rtol) ? side.rtol : '1e-6',
    shown: new Set(Array.isArray(saved.shown) ? saved.shown : ['e']),
    layout: saved.layout === 'rows' ? 'rows' : 'ages',
    digits: [2, 3, 4].includes(saved.digits) ? saved.digits : 2,
    run: null, // the batch being calculated, or the last one
    built: false,
    parsed: null,
  };
  const settings = () => ({
    system: B.system, route: B.route, text: B.text, forms: B.forms, sizes: [...B.sizes], ages: [...B.ages],
    cutoff: B.cutoff, rtol: B.rtol, shown: [...B.shown], layout: B.layout, digits: B.digits,
  });

  /* ---- the nuclides in the field ------------------------------------------------ */
  // Names as the nuclide field takes them (cs137, Cs-137, Tc-99m), or an
  // element's symbol for all its nuclides in the system.
  function parse(text, cat) {
    const byName = new Map(cat.nuclides.map((n) => [n.name.toLowerCase(), n]));
    const byElement = new Map();
    for (const n of cat.nuclides) {
      const el = n.name.split('-')[0].toLowerCase();
      if (!byElement.has(el)) byElement.set(el, []);
      byElement.get(el).push(n);
    }
    const found = [], unknown = [], elements = [], seen = new Set();
    const add = (n) => { if (!seen.has(n.name)) { seen.add(n.name); found.push(n); } };
    for (const t of String(text).split(/[\s,;]+/).filter(Boolean)) {
      const name = t.replace(/^([a-z]{1,2})-?(\d+)([a-z]*)$/i, (_, s, a, m) => `${s}-${a}${m}`).toLowerCase();
      if (byName.has(name)) add(byName.get(name));
      else if (/^[a-z]{1,2}$/i.test(t) && byElement.has(t.toLowerCase())) {
        const list = byElement.get(t.toLowerCase());
        list.forEach(add);
        elements.push([list[0].name.split('-')[0], list.length]);
      } else unknown.push(t);
    }
    return { found, unknown, elements };
  }

  const aerosolOf = (system, route, f) => route === 'inhalation' && (system === '103' ? f.aerosol !== false : /^[FMS]\|/.test(f.key));
  /** The table's rows -- a nuclide in a form at an aerosol size -- and the ages, for the settings as they are. */
  function plan(cat) {
    const p = parse(B.text, cat);
    const ages = AGES.filter((a) => B.ages.has(a));
    const sizes = SIZES[B.system].map(([v]) => v).filter((v) => B.sizes.has(v));
    const rows = [], none = [];
    for (const n of p.found) {
      const forms = n[B.route] || [];
      if (!forms.length) { none.push(n.name); continue; }
      for (const f of B.forms === 'all' ? forms : [forms.find((x) => x.default) || forms[0]]) {
        for (const size of aerosolOf(B.system, B.route, f) ? sizes : [null]) rows.push({ nuclide: n, form: f, size, out: {}, error: null });
      }
    }
    return { ...p, ages, sizes, rows, none, jobs: rows.length * ages.length };
  }
  const cutoffNow = () => (B.system === '103' ? B.cutoff : '1e-4'); // the ICRP 60 system cuts chains as DCAL did
  const planKey = (p) => JSON.stringify([B.system, B.route, B.forms, p.found.map((n) => n.name), p.sizes, p.ages, cutoffNow(), B.rtol]);

  /* ---- the columns ------------------------------------------------------------------ */
  function columns(system, shown) {
    const T = TISSUES[system];
    const cols = [];
    if (shown.has('e')) cols.push({ label: 'e', get: (o) => o.E });
    const names = [];
    if (shown.has('weighted')) names.push(...T.weighted.map(([n]) => n), 'Remainder');
    if (shown.has('remainder')) names.push(...T.remainder);
    if (shown.has('other')) names.push(...T.other);
    for (const n of names) {
      if (system === '103') {
        cols.push({ label: `H ${n}`, get: (o) => o.H.avg?.[n] });
        if (shown.has('sexes')) {
          cols.push({ label: `H ${n}, male`, get: (o) => o.H.M?.[n] });
          cols.push({ label: `H ${n}, female`, get: (o) => o.H.F?.[n] });
        }
      } else cols.push({ label: `H ${n}`, get: (o) => o.H?.[n] });
    }
    return cols;
  }
  const sizeLabel = (system, size) => (size == null ? '–' : (SIZES[system].find(([v]) => v === size)?.[1] || `${size} µm`).replace(/ \(.*\)$/, ''));

  /* ---- the settings ---------------------------------------------------------------- */
  const radio = (name, value, label, checked, extra = {}) => h('label', {}, h('input', { type: 'radio', name, value, checked, ...extra }), h('span', {}, label));
  const check = (name, value, label, checked, extra = {}) => h('label', { class: 'dc-check' }, h('input', { type: 'checkbox', name, value, checked, ...extra }), h('span', {}, label));
  const choose = (id, list, value) => h('select', { id }, ...list.map(([v, l]) => h('option', { value: v, selected: v === value }, l)));
  // What is calculated: the form above the button.
  function buildForm() {
    const form = $('dcBatchForm');
    form.replaceChildren(
      h('div', { class: 'dc-batch-row' },
        h('fieldset', {}, h('legend', {}, 'System'),
          h('div', { class: 'dc-seg', role: 'radiogroup', 'aria-label': 'System' },
            radio('dcBatchSystem', '60', 'ICRP 60', B.system === '60'), radio('dcBatchSystem', '103', 'ICRP 103', B.system === '103'))),
        h('fieldset', {}, h('legend', {}, 'Route'),
          h('div', { class: 'dc-seg', role: 'radiogroup', 'aria-label': 'Route' },
            ...ROUTES.map(([r, l]) => radio('dcBatchRoute', r, l, B.route === r, { disabled: B.system === '60' && r === 'injection' })))),
        h('fieldset', {}, h('legend', {}, 'Forms'),
          h('div', { class: 'dc-seg', role: 'radiogroup', 'aria-label': 'Forms' },
            radio('dcBatchForms', 'all', 'All forms of each', B.forms === 'all'), radio('dcBatchForms', 'default', 'The default form', B.forms === 'default')))),
      h('div', { class: 'dc-batch-nuclides' },
        h('div', { class: 'dc-batch-label-row' },
          h('label', { class: 'dc-batch-label', for: 'dcBatchText' }, 'Radionuclides'),
          h('button', { type: 'button', class: 'dc-btn secondary small', id: 'dcBatchPick' }, 'Choose from the list…')),
        h('textarea', { id: 'dcBatchText', rows: 2, spellcheck: 'false', autocomplete: 'off', placeholder: 'Cs-137, Sr-90, I-131 — names separated by commas, spaces or lines; an element’s symbol, such as Cs, for all its nuclides' })),
      h('p', { class: 'dc-muted dc-batch-parsed', id: 'dcBatchParsed', 'aria-live': 'polite' }),
      h('fieldset', { id: 'dcBatchSizes', hidden: B.route !== 'inhalation' }, h('legend', {}, 'Aerosol sizes (a gas or vapour has none)'),
        h('div', { class: 'dc-batch-checks' }, ...SIZES[B.system].map(([v, l]) => check('dcBatchSize', v, l, B.sizes.has(v))))),
      h('fieldset', {}, h('legend', {}, 'Ages at intake'),
        h('div', { class: 'dc-batch-checks' }, ...AGES.map((a) => check('dcBatchAge', String(a), AGE_LABEL[a], B.ages.has(a))))),
      h('div', { class: 'dc-batch-row' },
        B.system === '103'
          ? h('label', { class: 'dc-batch-select' }, h('span', { class: 'dc-batch-label' }, 'Decay chain cut-off'), choose('dcBatchCutoff', CUTOFFS, B.cutoff),
            h('span', { class: 'dc-muted' }, 'progeny carrying less of the energy emitted in 100 years are left out'))
          : h('p', { class: 'dc-muted dc-batch-select' }, 'Decay chains as DCAL cut them for Publication 72.'),
        h('label', { class: 'dc-batch-select' }, h('span', { class: 'dc-batch-label' }, 'Relative tolerance'), choose('dcBatchRtol', RTOLS, B.rtol))),
      h('div', { class: 'dc-batch-go' },
        h('p', { class: 'dc-batch-count', id: 'dcBatchCount', 'aria-live': 'polite' }),
        h('div', { class: 'dc-actions' },
          h('button', { type: 'button', class: 'dc-btn', id: 'dcBatchRun' }, 'Calculate the batch'),
          h('button', { type: 'button', class: 'dc-btn secondary', id: 'dcBatchStop', hidden: true }, 'Stop')),
        h('div', { class: 'dc-batch-progress', id: 'dcBatchProgress', hidden: true },
          h('div', { class: 'dc-progress', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-label': 'Batch progress' }, h('div')),
          h('span', { id: 'dcBatchProgressText' }))));
    $('dcBatchText').value = B.text;
    $('dcBatchRun').addEventListener('click', run);
    $('dcBatchStop').addEventListener('click', stop);
    $('dcBatchPick').addEventListener('click', pick);
    $('dcBatchStop').hidden = !B.run?.running;
    if (B.run) renderProgress();
    if (!B.built) {
      form.addEventListener('submit', (e) => e.preventDefault());
      form.addEventListener('input', (e) => { if (e.target.id === 'dcBatchText') { B.text = e.target.value; refresh(); ctx.onSave(); } });
      form.addEventListener('change', onChange);
    }
    B.built = true;
  }
  // What the table shows: apart, under the progress bar; changing it calculates nothing.
  function buildShow() {
    const box = $('dcBatchShow');
    const doses = DOSES.some((k) => B.shown.has(k));
    box.replaceChildren(
      h('div', { class: 'dc-batch-show-head' }, h('b', {}, 'In the table'),
        h('span', { class: 'dc-muted' }, ' · nothing is calculated again when these change: every dose of every age is kept')),
      h('div', { class: 'dc-batch-checks dc-batch-results', role: 'group', 'aria-label': 'Results, Sv per Bq' },
        ...QUANTITIES.map(([k, l]) => (k === 'sexes'
          ? (B.system === '60' ? null : check('dcBatchShown', k, l, B.shown.has(k), { disabled: !doses }))
          : check('dcBatchShown', k, l, B.shown.has(k))))),
      h('div', { class: 'dc-batch-view' },
        h('label', {}, 'Layout ', h('select', { id: 'dcBatchLayout' },
          h('option', { value: 'ages', selected: B.layout === 'ages' }, 'ages as columns'), h('option', { value: 'rows', selected: B.layout === 'rows' }, 'a row for each age'))),
        h('label', {}, 'Digits ', choose('dcBatchDigits', [['2', '2, as ICRP'], ['3', '3'], ['4', '4']], String(B.digits)))));
    const sexes = box.querySelector('input[value="sexes"]');
    if (sexes && !doses) sexes.closest('label').setAttribute('data-tip', 'For the equivalent doses: tick one of them first');
    if (!box.dataset.wired) {
      box.dataset.wired = '1';
      box.addEventListener('change', onShowChange);
    }
  }
  function onChange(e) {
    const t = e.target;
    if (t.name === 'dcBatchSystem') {
      B.system = t.value;
      if (B.system === '60' && B.route === 'injection') B.route = 'ingestion';
      B.parsed = null;
      buildForm();
      buildShow();
    } else if (t.name === 'dcBatchRoute') { B.route = t.value; $('dcBatchSizes').hidden = B.route !== 'inhalation'; }
    else if (t.name === 'dcBatchForms') B.forms = t.value;
    else if (t.name === 'dcBatchSize') { if (t.checked) B.sizes.add(t.value); else B.sizes.delete(t.value); }
    else if (t.name === 'dcBatchAge') { const a = Number(t.value); if (t.checked) B.ages.add(a); else B.ages.delete(a); }
    else if (t.id === 'dcBatchCutoff') B.cutoff = t.value;
    else if (t.id === 'dcBatchRtol') B.rtol = t.value;
    else return;
    refresh();
    ctx.onSave();
  }
  function onShowChange(e) {
    const t = e.target;
    if (t.name === 'dcBatchShown') {
      if (t.checked) B.shown.add(t.value); else B.shown.delete(t.value);
      if (DOSES.includes(t.value)) buildShow(); // male and female follow the equivalent doses
    } else if (t.id === 'dcBatchLayout') B.layout = t.value;
    else if (t.id === 'dcBatchDigits') B.digits = Number(t.value);
    else return;
    renderTable();
    ctx.onSave();
  }
  async function pick() {
    let cat;
    try { cat = await ctx.catalog(B.system); } catch (err) { $('dcBatchParsed').textContent = `The list of radionuclides did not load: ${err.message}`; return; }
    const p = parse(B.text, cat);
    openPicker({
      h, halfLife, nuclides: cat.nuclides, system: B.system, route: B.route, chosen: p.found.map((n) => n.name), left: p.unknown,
      onUse: (names) => {
        B.text = names.join(', ');
        $('dcBatchText').value = B.text;
        refresh();
        ctx.onSave();
        $('dcBatchPick').focus();
      },
    });
  }

  /** The parsed nuclides and the count of calculations, for the settings as they are. */
  async function refresh() {
    let cat;
    try { cat = await ctx.catalog(B.system); } catch (err) { $('dcBatchParsed').textContent = `The list of radionuclides did not load: ${err.message}`; return; }
    if (!B.built) return;
    const p = plan(cat);
    B.parsed = p;
    const names = p.found.map((n) => n.name);
    const parts = [];
    if (names.length) parts.push(`${names.length} ${names.length === 1 ? 'radionuclide' : 'radionuclides'}: ${names.slice(0, 24).join(', ')}${names.length > 24 ? ` and ${names.length - 24} more` : ''}.`);
    for (const [el, k] of p.elements) parts.push(`${el}: all ${k} of its nuclides.`);
    if (p.unknown.length) parts.push(`Not in the ICRP ${B.system} system: ${p.unknown.slice(0, 12).join(', ')}${p.unknown.length > 12 ? '…' : ''}.`);
    if (p.none.length) parts.push(`No ${B.route} in this system for ${p.none.join(', ')}.`);
    $('dcBatchParsed').textContent = parts.join(' ') || 'Type or paste the radionuclides, or choose them from the list.';
    const what = B.route === 'inhalation' ? 'radionuclide, form and aerosol size' : 'radionuclide and form';
    let count;
    if (!p.found.length) count = 'No radionuclide yet.';
    else if (!p.ages.length) count = 'Tick at least one age at intake.';
    else if (!p.rows.length) count = B.route === 'inhalation' && !p.sizes.length ? 'Tick at least one aerosol size.' : `Nothing to calculate by ${B.route}.`;
    else {
      count = `${p.rows.length} ${p.rows.length === 1 ? 'combination' : 'combinations'} of ${what} × ${p.ages.length} ${p.ages.length === 1 ? 'age' : 'ages'} = ${p.jobs.toLocaleString('en')} ${p.jobs === 1 ? 'calculation' : 'calculations'}, ${ctx.POOL_SIZE} at a time.`
        + (p.jobs > 2000 ? ' That is many: it can be stopped at any time, and what is done stays in the table.' : '');
    }
    $('dcBatchCount').textContent = count;
    $('dcBatchRun').disabled = !!B.run?.running || !p.jobs;
    renderNotice();
  }

  /* ---- running ------------------------------------------------------------------------ */
  let drawTimer = 0;
  function progressSoon() {
    if (drawTimer) return;
    drawTimer = setTimeout(() => { drawTimer = 0; renderProgress(); if (ctx.visible()) renderTable(); }, 300);
  }
  async function run() {
    if (B.run?.running) return;
    const cat = await ctx.catalog(B.system);
    const p = plan(cat);
    if (!p.jobs) { refresh(); return; }
    const R = {
      system: B.system, route: B.route, forms: B.forms, ages: p.ages, sizes: p.sizes, rows: p.rows, nuclides: p.found.length,
      cutoff: Number(cutoffNow()), rtol: Number(B.rtol), cutoffText: textOf(CUTOFFS, cutoffNow()), rtolText: textOf(RTOLS, B.rtol), key: planKey(p),
      total: p.jobs, done: 0, failed: 0, when: new Date(), t0: performance.now(), ms: 0, running: true, stopped: false,
    };
    B.run = R;
    $('dcBatchStop').hidden = false;
    refresh();
    renderProgress();
    renderTable();
    const tasks = [];
    for (const row of R.rows) {
      const spec = { nuclide: row.nuclide.name, route: R.route, ...row.form.spec, cutoff: R.cutoff, ...(row.size != null ? { amad: Number(row.size) } : {}) };
      for (const age of R.ages) {
        tasks.push(ask({ type: 'run', system: R.system, spec, ages: [age], rtol: R.rtol, withSystem: false, lean: true }, null, RANK.batch)
          .then(([o]) => { row.out[age] = o; R.done++; }, (err) => {
            if (err.message === 'stopped') return;
            row.error ||= err.message;
            R.done++;
            R.failed++;
          })
          .finally(progressSoon));
      }
    }
    await Promise.all(tasks);
    R.running = false;
    R.ms = performance.now() - R.t0;
    clearTimeout(drawTimer);
    drawTimer = 0;
    $('dcBatchStop').hidden = true;
    refresh();
    renderProgress();
    renderTable();
  }
  function stop() {
    if (!B.run?.running) return;
    B.run.stopped = true;
    stopRank(RANK.batch);
  }

  const duration = (ms) => {
    const s = Math.round(ms / 1000);
    if (s < 60) return ms < 10000 ? `${(ms / 1000).toFixed(1)} s` : `${s} s`;
    const m = Math.floor(s / 60);
    return m < 60 ? `${m} min ${s % 60} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
  };
  function renderProgress() {
    const R = B.run;
    const box = $('dcBatchProgress');
    if (!R) { box.hidden = true; ctx.onProgress(null); return; }
    box.hidden = false;
    const frac = R.total ? R.done / R.total : 0;
    const bar = box.querySelector('.dc-progress');
    bar.firstChild.style.width = `${Math.round(100 * frac)}%`;
    bar.setAttribute('aria-valuenow', String(Math.round(100 * frac)));
    const failed = R.failed ? `, ${R.failed} failed` : '';
    let text;
    if (R.running) {
      const elapsed = performance.now() - R.t0;
      const left = R.done ? (R.total - R.done) * elapsed / R.done : null;
      text = `${R.done.toLocaleString('en')} of ${R.total.toLocaleString('en')} calculations done${failed}`
        + (left != null && R.done < R.total ? ` · about ${duration(left)} left` : ' · starting');
    } else if (R.stopped) text = `Stopped after ${R.done.toLocaleString('en')} of ${R.total.toLocaleString('en')} calculations${failed}, in ${duration(R.ms)}: the table holds what was done.`;
    else text = `${R.total.toLocaleString('en')} calculations${failed} in ${duration(R.ms)}.`;
    $('dcBatchProgressText').textContent = text;
    ctx.onProgress(R.running ? `${Math.floor(100 * frac)} %` : null);
  }

  /* ---- the table ---------------------------------------------------------------------- */
  // The values of a row of the table: per column, per age (the 'ages'
  // layout), or the row's ages one by one ('rows').
  function tableRows(R, cols, layout) {
    const out = [];
    for (const row of R.rows) {
      const base = { row, nuclide: row.nuclide, form: row.form, size: row.size };
      if (layout === 'ages') out.push({ ...base, cells: cols.flatMap((c) => R.ages.map((a) => (row.out[a] ? c.get(row.out[a]) : undefined))) });
      else for (const a of R.ages) out.push({ ...base, age: a, cells: cols.map((c) => (row.out[a] ? c.get(row.out[a]) : undefined)) });
    }
    return out;
  }
  function header(R, layout) {
    const lead = ['Nuclide', 'Half-life', 'Form'];
    if (R.route === 'inhalation') lead.push('Aerosol');
    if (layout === 'rows') lead.push('Age at intake');
    return lead;
  }
  function renderTable() {
    const R = B.run;
    const table = $('dcBatchTable');
    $('dcBatchTools').hidden = !R;
    if (!R) { table.replaceChildren(); $('dcBatchCaption').textContent = ''; return; }
    const cols = columns(R.system, B.shown);
    $('dcBatchCaption').textContent = caption(R);
    if (!cols.length) {
      table.replaceChildren(h('tbody', {}, h('tr', {}, h('td', { class: 'dim' }, 'Tick a result above to show it.'))));
      renderNotice();
      return;
    }
    const lead = header(R, B.layout);
    const rows = tableRows(R, cols, B.layout);
    const d = B.digits;
    const pending = R.running && !R.stopped;
    const value = (v, row) => (v != null && Number.isFinite(v) ? sci(v, d) : row.error ? '–' : pending ? '…' : '–');
    const head = B.layout === 'ages'
      ? [h('tr', {}, ...lead.map((l) => h('th', { rowspan: 2, class: l === 'Form' ? 'text' : null }, l)), ...cols.map((c) => h('th', { colspan: R.ages.length, class: 'group' }, c.label)), h('th', { rowspan: 2, class: 'text' }, 'Note')),
        h('tr', {}, ...cols.flatMap(() => R.ages.map((a) => h('th', {}, AGE_LABEL[a]))))]
      : [h('tr', {}, ...lead.map((l) => h('th', { class: l === 'Form' ? 'text' : null }, l)), ...cols.map((c) => h('th', {}, c.label)), h('th', { class: 'text' }, 'Note'))];
    const body = rows.slice(0, MAX_SHOWN).map((r) => h('tr', {},
      h('td', {}, r.nuclide.name), h('td', {}, r.nuclide.T ? halfLife(r.nuclide.T) : ''), h('td', { class: 'text' }, r.form.label),
      R.route === 'inhalation' ? h('td', {}, sizeLabel(R.system, r.size)) : null,
      B.layout === 'rows' ? h('td', {}, AGE_LABEL[r.age]) : null,
      ...r.cells.map((v) => h('td', {}, value(v, r.row))),
      h('td', { class: 'text dim' }, r.row.error || '')));
    if (rows.length > MAX_SHOWN) {
      body.push(h('tr', {}, h('td', { colspan: lead.length + rows[0].cells.length + 1, class: 'dim' }, `The first ${MAX_SHOWN.toLocaleString('en')} of ${rows.length.toLocaleString('en')} rows; the CSV and Excel files hold them all.`)));
    }
    table.replaceChildren(h('thead', {}, ...head), h('tbody', {}, ...body));
    renderNotice();
  }
  function caption(R) {
    const forms = R.forms === 'all' ? 'all their forms' : 'the default form of each';
    const sizes = R.route === 'inhalation' ? `, ${R.sizes.map((s) => sizeLabel(R.system, s)).join(', ')}` : '';
    return `ICRP ${R.system} system, ${R.route}: ${R.nuclides} ${R.nuclides === 1 ? 'radionuclide' : 'radionuclides'}, ${forms}${sizes}; `
      + `${R.ages.length} ${R.ages.length === 1 ? 'age' : 'ages'} at intake; ${R.system === '103' ? `decay chain cut-off ${R.cutoffText}, ` : ''}tolerance ${R.rtolText}. Sv per Bq.`;
  }
  // The settings above, changed since the table was calculated.
  function renderNotice() {
    const R = B.run, box = $('dcBatchNotice');
    const changed = R && B.parsed && planKey(B.parsed) !== R.key && !R.running;
    box.hidden = !changed;
    if (changed) box.replaceChildren(h('b', {}, 'Not for the current settings. '), 'The table is of the settings in its caption; those above it have changed since it was calculated.');
  }

  /* ---- files ------------------------------------------------------------------------------ */
  // One header row and the values in full (six figures in CSV, as they are in Excel).
  function fileTable(R) {
    const cols = columns(R.system, B.shown);
    const lead = ['System', 'Route', ...header(R, B.layout)];
    const units = B.layout === 'ages' ? cols.flatMap((c) => R.ages.map((a) => `${c.label}, ${AGE_LABEL[a]} (Sv/Bq)`)) : cols.map((c) => `${c.label} (Sv/Bq)`);
    const rows = tableRows(R, cols, B.layout).map((r) => [
      `ICRP ${R.system}`, R.route, r.nuclide.name, r.nuclide.T ? halfLife(r.nuclide.T) : '', r.form.label,
      ...(R.route === 'inhalation' ? [sizeLabel(R.system, r.size)] : []),
      ...(B.layout === 'rows' ? [AGE_LABEL[r.age]] : []),
      ...r.cells.map((v) => (v != null && Number.isFinite(v) ? v : null)),
      r.row.error || '',
    ]);
    return { head: [...lead, ...units, 'Note'], rows, lead };
  }
  const fileName = (R, ext) => `dose-batch-icrp${R.system}-${R.route}.${ext}`;
  function download(blob, name) {
    const a = h('a', { href: URL.createObjectURL(blob), download: name });
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }
  function saveCsv() {
    const R = B.run;
    if (!R) return;
    const cell = (v) => (typeof kvotCsvCell === 'function' ? kvotCsvCell(v) : String(v));
    const { head, rows } = fileTable(R);
    const lines = [head.map(cell).join(','), ...rows.map((r) => r.map((v) => cell(v == null ? '' : typeof v === 'number' ? v.toPrecision(6) : v)).join(','))];
    download(new Blob([`${lines.join('\r\n')}\r\n`], { type: 'text/csv' }), fileName(R, 'csv'));
  }
  const loadScript = (src, integrity) => new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    if (integrity) { s.integrity = integrity; s.crossOrigin = 'anonymous'; }
    s.onload = resolve;
    s.onerror = () => reject(new Error(`${src.split('/').pop()} did not load`));
    document.head.append(s);
  });
  async function saveExcel() {
    const R = B.run;
    if (!R) return;
    const note = $('dcBatchFileNote');
    note.textContent = '';
    try {
      if (typeof window.JSZip === 'undefined') await loadScript(JSZIP.src, JSZIP.integrity);
      if (typeof window.XlsxWriter === 'undefined') await loadScript(new URL('../xlsxwrite.js?v=20261004', import.meta.url).href);
    } catch (err) {
      note.textContent = `The Excel writer could not be loaded (${err.message}); the CSV file has the same table.`;
      return;
    }
    const { head, rows, lead } = fileTable(R);
    // A text that begins with = would be read as a formula.
    const text = (v) => (typeof v === 'string' && /^[=+\-@]/.test(v) ? ` ${v}` : v);
    // A bold header; the values in full, shown with the table's digits.
    const x = new window.XlsxWriter(fileName(R, 'xlsx'));
    const bold = x.addFormat({ bold: true });
    const num = x.addFormat({ numFormat: `0.${'0'.repeat(B.digits - 1)}E+00` });
    x.writeRow(0, 0, head.map(text), bold, 'Results');
    rows.forEach((r, i) => r.forEach((v, j) => x.write(i + 1, j, typeof v === 'number' ? v : text(v ?? ''), typeof v === 'number' ? num : undefined, 'Results')));
    // The header and the nuclide stay in view; System, Route, Nuclide, Half-life, Form, then the rest.
    x.freezePanes('Results', 1, 3);
    x.setColumn(0, 3, 10, undefined, {}, 'Results');
    x.setColumn(4, 4, 44, undefined, {}, 'Results');
    if (lead.length > 5) x.setColumn(5, lead.length - 1, 14, undefined, {}, 'Results');
    x.setColumn(lead.length, head.length - 2, 13, undefined, {}, 'Results');
    x.setColumn(head.length - 1, head.length - 1, 40, undefined, {}, 'Results');
    const calc = [
      ['Calculated', `${R.when.toISOString().slice(0, 16).replace('T', ' ')} UTC, in a web browser, by https://kvotab.se/dose_coefficients.html`],
      ['System', R.system === '60' ? 'ICRP 60: the models of Publications 56–71 and the dosimetry of Publication 60, as DCAL holds them (the coefficients of Publication 72)'
        : 'ICRP 103: Publication 158 and the consultation drafts of its Parts 2 and 3, with the specific absorbed fractions of Publications 133 and 155'],
      ['Route', R.route],
      ['Forms', R.forms === 'all' ? 'all forms of each radionuclide' : 'the default form of each radionuclide'],
      ...(R.route === 'inhalation' ? [['Aerosol sizes', R.sizes.map((s) => sizeLabel(R.system, s)).join(', ')]] : []),
      ['Ages at intake', R.ages.map((a) => AGE_LABEL[a]).join(', ')],
      ['Commitment period', '50 years for adults, to age 70 for children'],
      R.system === '103' ? ['Decay chain cut-off', R.cutoffText] : ['Decay chains', 'as DCAL cut them for Publication 72'],
      ['Relative tolerance', R.rtolText],
      ['Calculations', `${R.done} of ${R.total}${R.failed ? `, ${R.failed} failed` : ''}${R.stopped ? ' (stopped)' : ''}`],
      ['Unit', 'Sv per Bq taken in'],
    ];
    calc.forEach(([k, v], i) => { x.write(i, 0, k, bold, 'Settings'); x.write(i, 1, text(v), undefined, 'Settings'); });
    x.setColumn(0, 0, 22, undefined, {}, 'Settings');
    x.setColumn(1, 1, 110, undefined, {}, 'Settings');
    download(await x.save(), fileName(R, 'xlsx'));
  }

  return {
    settings,
    render() {
      if (!B.built) { buildForm(); buildShow(); }
      refresh();
      renderProgress();
      renderTable();
    },
    refresh() { if (B.built) refresh(); },
    saveCsv, saveExcel, run, stop,
    get running() { return !!B.run?.running; },
  };
}
