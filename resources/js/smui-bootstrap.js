/* ==========================================================================
   SMUI.HTML: BOOTSTRAP (JMP Pro's, on any report table)

   Right-click a numeric column of a report table and choose Bootstrap: the
   report's rows (its By group, after the Local Data Filter) are resampled
   with replacement, the platform runs again on each sample without drawing
   anything (a headless Ctx: no plots, no cache, no saved columns), and the
   numbers of the same table are collected. The result is a data table,
   Bootstrap Results, with a row per sample (BootID 0 is the report itself)
   and a column per row of the table holding the statistic clicked, and a
   Bootstrap report of it: the percentile, bias-corrected and (with the
   jackknife) BCa limits from bootstrap.py.

   The table is found again in each run by the titles of its outlines and
   its place among the tables of its outline; its rows by their text
   columns (a term, a level).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el, fmt } = SM.util;

  const titleOf = (ob) => { const h = ob.querySelector(':scope > .sm-ob-head h2, :scope > .sm-ob-head h3, :scope > .sm-ob-head h4'); return h ? h.textContent : ''; };
  const parentOb = (ob) => (ob.parentElement ? ob.parentElement.closest('.sm-ob') : null);
  const tablesIn = (ob) => [...ob.querySelectorAll('table.sm-rt, table.sm-kv')].filter((t) => t.closest('.sm-ob') === ob);

  /* Where a table is: its report, the titles of its outlines (outermost first) and its index. */
  function locate(tbl) {
    const report = SM.app && SM.app.reports.find((r) => r.body.contains(tbl));
    if (!report || !report.table || !report.platform || report.platform.id === 'bootstrap') return null;
    const obs = [];
    for (let o = tbl.closest('.sm-ob'); o; o = parentOb(o)) obs.unshift(o);
    if (!obs.length) return null;
    return { report, titles: obs.map(titleOf), index: tablesIn(obs[obs.length - 1]).indexOf(tbl) };
  }

  function find(container, titles, index) {
    let parent = null;
    for (const t of titles) {
      const hit = [...container.querySelectorAll('.sm-ob')].find((x) => titleOf(x) === t && parentOb(x) === parent);
      if (!hit) return null;
      parent = hit;
    }
    return parent ? tablesIn(parent)[index] || null : null;
  }

  function groupOf(L) {
    const r = L.report;
    return r.groups().find((g) => (g.label ? `${r.title} ${g.label}` : r.title) === L.titles[0]) || null;
  }

  /* The rows of a report table by name: its text columns joined (a term, a
     level, a method and its settings), or the row number. */
  function labelsOf(rt) {
    const text = (rt.all || rt.columns).filter((c) => (c.fmt || 'num') === 'text');
    const seen = new Map();
    return rt.rows.map((r, i) => {
      let lab = text.length ? text.map((c) => String(r[c.key] ?? '')).join(' ').trim() : `Row ${i + 1}`;
      if (!lab) lab = `Row ${i + 1}`;
      const k = (seen.get(lab) || 0) + 1;
      seen.set(lab, k);
      return k > 1 ? `${lab} (${k})` : lab;
    });
  }

  const num = (v) => (v == null ? NaN : typeof v === 'number' ? v : v === 'Infinity' ? Infinity : v === '-Infinity' ? -Infinity : Number(v));

  function valuesOf(rt, key, labels) {
    const got = new Map(labelsOf(rt).map((lab, i) => [lab, num(rt.rows[i][key])]));
    return labels.map((lab) => (got.has(lab) ? got.get(lab) : NaN));
  }

  /* The resamples: n draws with replacement from the rows, from the seed. */
  function sampler(rows, seed) {
    const R = SM.util.rng(`bootstrap:${seed}`);
    const n = rows.length;
    return () => {
      const s = new Array(n);
      for (let i = 0; i < n; i++) s[i] = rows[Math.floor(R.u() * n)];
      return s.sort((a, b) => a - b);
    };
  }

  // The table as a rerun sees it: every read, no change (Color Clusters and
  // the like must not act on a resample).
  const CHANGES = new Set(['addColumn', 'removeColumn', 'renameColumn', 'moveColumn', 'setType', 'setCell', 'setValues', 'addRows', 'deleteRows', 'sortBy', 'setState', 'toggleState', 'select', 'setColor', 'setMarker', 'clearRowStates', 'restore']);
  const readOnly = (table) => new Proxy(table, {
    get(t, prop) {
      if (CHANGES.has(prop)) return () => undefined;
      const v = t[prop];
      return typeof v === 'function' ? v.bind(t) : v;
    },
    set() { return true; },
  });

  /* The platform once more on these rows, drawing nothing; the table found again. */
  async function rerun(L, g, rows) {
    const box = el('div');
    const ctx = new SM.report.Ctx(L.report, { ...g, rows }, box, g.label || '');
    ctx.headless = true;
    ctx.resampled = true;
    ctx.table = readOnly(L.report.table);
    const top = ctx.outline(L.titles[0], { level: 0 });
    ctx.container = top.body;
    ctx.top = top;
    await L.report.platform.render(ctx);
    const t = find(box, L.titles, L.index);
    return t && t._rt ? t._rt : null;
  }

  // What was collected: the column's heading, or the table's (a two-column table's values).
  const statName = (L, column) => (column.label && column.label !== 'Value' ? column.label : L.titles[L.titles.length - 1] || 'Value');

  /* The right-click item of a report table (column: the column clicked). */
  function item(tbl, column) {
    const L = locate(tbl);
    const ok = L && column && (column.fmt || 'num') !== 'text' && (tbl._rt.rows || []).some((r) => Number.isFinite(num(r[column.key])));
    const named = column && column.label && column.label !== 'Value';
    return { label: named ? `Bootstrap ${column.label}…` : 'Bootstrap…', disabled: !ok, action: () => ask(tbl, column) };
  }

  async function ask(tbl, column) {
    const L = locate(tbl);
    const g = L && groupOf(L);
    if (!g) { SM.ui.toast('This table cannot be found again in its report', { error: true }); return; }
    const v = await SM.ui.form({
      title: 'Bootstrap', info: 'p:bootstrap',
      lead: `Resample the ${g.rows.length} rows of the report with replacement, run ${L.report.platform.label} again on each sample, and collect ${statName(L, column)} of every row of this table.`,
      fields: [
        { key: 'B', label: 'Number of Bootstrap Samples', type: 'number', value: 500, help: 'How many times the rows are drawn again (2 to 100,000), each draw analysed like the report. More samples give steadier limits: 500 is enough for a standard error and 95% limits, a few thousand for 99% limits.' },
        { key: 'seed', label: 'Random Seed', type: 'text', value: '', placeholder: 'empty: drawn now', help: 'The seed of the resampling: the same seed draws the same samples and gives the same results. Empty: one is drawn now; the results show it.' },
        { key: 'bca', label: `BCa limits (the jackknife: ${g.rows.length} more runs)`, type: 'check', value: false, helpLabel: 'BCa limits', help: 'Adds bias-corrected and accelerated limits, which correct the percentile limits for skewness as well as bias. The acceleration comes from the jackknife: the analysis is run once more without each row in turn, so this costs a run per row (at most 3,000 rows).' },
      ],
      validate: (x) => (!(x.B >= 2 && x.B <= 100000) ? 'Number of Bootstrap Samples: 2 or more' : (x.bca && g.rows.length > 3000 ? 'BCa needs a run per row: at most 3,000 rows' : null)),
    });
    if (!v) return;
    const seed = v.seed.trim() === '' ? 1 + Math.floor(Math.random() * 2147483646) : Math.trunc(Number(v.seed)) || 1;
    return run(tbl, column, { B: Math.round(v.B), seed, bca: !!v.bca });
  }

  /* Run it: returns the Bootstrap Results table (and opens the Bootstrap report). */
  async function run(tbl, column, { B = 500, seed = 1, bca = false, show = true } = {}) {
    const L = locate(tbl);
    const g = L && groupOf(L);
    if (!g) throw new Error('the table is not in a report');
    const labels = labelsOf(tbl._rt);
    const original = valuesOf(tbl._rt, column.key, labels);
    const bar = el('progress', { max: String(B + (bca ? g.rows.length : 0)), value: '0' });
    const text = el('p', { class: 'sm-dialog-lead', text: `Sample 0 of ${B}` });
    let stop = false;
    const dlg = SM.ui.dialog({ title: 'Bootstrap', narrow: true, body: el('div', { class: 'sm-boot-progress' }, text, bar),
      buttons: [{ label: 'Stop', action: () => { stop = true; return false; } }], onClose: () => { stop = true; } });
    const next = sampler(g.rows, seed);
    const samples = [];
    let failed = 0;
    const t0 = performance.now();
    try {
      for (let b = 1; b <= B && !stop; b++) {
        const rows = next();
        let vals = null;
        try { const rt = await rerun(L, g, rows); if (rt) vals = valuesOf(rt, column.key, labels); } catch (e) { failed++; }
        samples.push(vals || labels.map(() => NaN));
        if (b % 5 === 0 || b === B) {
          bar.value = b;
          const rate = (performance.now() - t0) / b;
          text.textContent = `Sample ${b} of ${B}${b < B ? `, about ${Math.max(1, Math.round((B - b) * rate / 1000))} s left` : ''}`;
          await new Promise((r) => setTimeout(r, 0));
        }
      }
      let jack = null;
      if (bca && !stop) {
        jack = [];
        for (let i = 0; i < g.rows.length && !stop; i++) {
          const rows = g.rows.filter((_, j) => j !== i);
          let vals = null;
          try { const rt = await rerun(L, g, rows); if (rt) vals = valuesOf(rt, column.key, labels); } catch (e) { /* a row the fit cannot do without */ }
          jack.push(vals || labels.map(() => NaN));
          if (i % 5 === 0) { bar.value = B + i; text.textContent = `Jackknife: row ${i + 1} of ${g.rows.length}`; await new Promise((r) => setTimeout(r, 0)); }
        }
        if (stop) jack = null;
      }
      dlg.close();
      if (!samples.length) return null;
      // the new table: BootID, then a column per row of the report table
      const names = new Set(['BootID']);
      const colName = (lab) => { let nm = lab, k = 2; while (names.has(nm)) nm = `${lab} ${k++}`; names.add(nm); return nm; };
      const cols = labels.map((lab, j) => ({ name: colName(lab), dataType: 'numeric', values: [original[j], ...samples.map((s) => s[j])] }));
      const stat = statName(L, column);
      const where = L.titles.slice(1).join(' > ') || L.titles[0];
      const t = new SM.Table({
        name: `Bootstrap Results of ${L.report.title}`,
        columns: [{ name: 'BootID', dataType: 'numeric', values: [0, ...samples.map((_, i) => i + 1)] }, ...cols],
        notes: `${stat} of every row of ${where} (${L.report.title}${g.label ? `, ${g.label}` : ''}): BootID 0 is the report itself, 1 to ${samples.length} the bootstrap samples (${g.rows.length} rows drawn with replacement, seed ${seed}).`,
        source: 'Bootstrap',
      });
      if (failed) t.notes += ` ${failed} samples failed and are missing.`;
      if (SM.app) {
        SM.app.addTable(t, { show: false });
        const options = { statistic: stat, source: `${L.report.title}${g.label ? ` ${g.label}` : ''}`, where, seed, samples: samples.length };
        if (jack) options.jackknife = Object.fromEntries(cols.map((c, j) => [c.name, jack.map((r) => (Number.isFinite(r[j]) ? r[j] : null))]));
        if (show) SM.app.openReport(SM.platforms.get('bootstrap'), { roles: { y: t.columns.slice(1).filter((c) => c.values.some((x) => Number.isFinite(x))).map((c) => c.id) }, options }, t);
      }
      return t;
    } finally {
      dlg.close();
    }
  }

  /* ---- the Bootstrap report ------------------------------------------------ */
  async function render(ctx) {
    const o = ctx.spec.options || {};
    const ys = ctx.roles('y');
    if (!ctx.table.col('BootID')) { ctx.top.add(ctx.warn('A Bootstrap report needs the BootID column of a Bootstrap Results table.')); return; }
    const r = await ctx.call('bootstrap.report', { columns: ys.map((c) => c.name), jackknife: o.jackknife || null });
    ctx.top.add(ctx.note(`${o.statistic || 'The statistic'} of ${o.where || 'a report table'} in ${o.source || 'a report'}: ${o.samples || '?'} bootstrap samples (seed ${o.seed ?? '?'}). The original estimate is BootID 0.`));
    const bca = !!o.jackknife;
    const P = SM.util.themeColors();
    const red = P.dark ? '#ff7a6b' : '#c0392b';
    for (const s of r.stats) {
      const ob = ctx.outline(s.column, { key: `boot:${s.column}`, info: 'p:bootstrap:limits' });
      if (s.error) { ob.add(ctx.warn(`${s.column}: ${s.error}`)); continue; }
      const col = ctx.table.col(s.column);
      const vals = s.rows.map((i) => col.values[i]).filter((v) => Number.isFinite(v));
      const bins = SM.report.niceBins(vals);
      const L95 = s.limits.find((l) => Math.abs(l.coverage - 0.95) < 1e-9) || s.limits[0];
      const lines = [[s.original, 'solid'], [L95.pct_lower, 'dash'], [L95.pct_upper, 'dash']].filter(([x]) => Number.isFinite(x))
        .map(([x, dash]) => ({ type: 'line', x0: x, x1: x, yref: 'paper', y0: 0, y1: 1, line: { color: red, width: dash === 'solid' ? 1.8 : 1.2, dash } }));
      const plot = ctx.plot([{ type: 'histogram', x: s.rows.map((i) => col.values[i]), rows: s.rows, xbins: { start: bins.start, end: bins.end, size: bins.size }, name: s.column }],
        { xaxis: { title: { text: SM.report.plotlyText(s.column) } }, yaxis: { title: { text: 'Samples' } }, shapes: lines, bargap: 0.02 }, { width: 380, height: 240, title: `${s.column} bootstrap values` });
      const summary = ctx.kv([['Original Estimate', s.original], ['Bootstrap Mean', s.mean], ['Bias', s.bias], ['Bootstrap Std Error', s.std_error], ['Samples', s.n_samples, 'int'], s.n_missing ? ['Missing', s.n_missing, 'int'] : null]);
      const cols = [{ key: 'coverage', label: 'Coverage' }, { key: 'pct_lower', label: 'Pct Lower' }, { key: 'pct_upper', label: 'Pct Upper' }, { key: 'bc_lower', label: 'BC Lower' }, { key: 'bc_upper', label: 'BC Upper' }];
      if (bca) cols.push({ key: 'bca_lower', label: 'BCa Lower' }, { key: 'bca_upper', label: 'BCa Upper' });
      ob.add(ctx.row(plot, summary), ctx.rt({ columns: cols, rows: s.limits }, { caption: 'Bootstrap Confidence Limits', key: 'limits', sortable: false }));
    }
    ctx.top.add(ctx.note('Solid: the original estimate; dashed: the 95% percentile limits. BC: bias-corrected (for the share of samples below the original)' + (bca ? '; BCa: also for the acceleration, from the jackknife.' : '.')), ctx.code(r.code));
  }

  const TOPICS = {
    'p:bootstrap': {
      kicker: 'Bootstrap', title: 'Bootstrap',
      lead: 'How much a statistic of a report would vary in new samples like this one: the rows are drawn again with replacement, as many as there are, the analysis is run on each such sample, and the statistic is collected. Their spread is its bootstrap standard error; their quantiles give confidence limits that need no formula.',
      sections: [{ text: 'Bootstrap Results, a new data table, has a row per sample (BootID 0 is the report itself) and a column per row of the table: analyse it like any table. The rows are resampled independently, which suits rows that are independent (not a time series).' }],
    },
    'p:bootstrap:limits': {
      kicker: 'Bootstrap', title: 'Bootstrap Confidence Limits',
      lead: 'Pct: the percentile limits, the quantiles of the bootstrap values. BC: bias-corrected, the quantiles moved by how far the original estimate is from the middle of the bootstrap values. BCa: also corrected for the acceleration, from the jackknife. The quantiles are JMP\'s ((n + 1)p).',
    },
  };

  SM.bootstrap = Object.freeze({ item, run, locate, find, labelsOf, sampler });
  SM.platforms.register({
    id: 'bootstrap', label: 'Bootstrap', info: 'p:bootstrap', topics: TOPICS,
    about: 'The bootstrap distribution of a report table\'s statistics: made from a report table\'s right-click menu (Bootstrap), on the Bootstrap Results table it creates.',
    uses: ['numpy.quantile (JMP\'s quantiles)', 'scipy.stats.norm (the bias-corrected and BCa limits)'],
    launch: { roles: [{ key: 'y', label: 'Y, Columns', min: 1, numeric: true, types: ['continuous'], hint: 'the bootstrap values' }] },
    title: (spec) => `Bootstrap of ${(spec && spec.options && spec.options.statistic) || 'a Statistic'}`,
    render,
  });
}(typeof self !== 'undefined' ? self : this));
