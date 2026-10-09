/* ==========================================================================
   SMUI.HTML: ANALYZE > QUALITY AND PROCESS

   Control Chart   XBar & R, XBar & S, Individual & Moving Range,
                           Run, P, NP, C, U, EWMA and CUSUM charts; phases,
                           the Western Electric / Nelson tests, limit
                           summaries, a short capability analysis, saved
                           limits
   Process Capability      several columns against their spec limits: goal
                           plot, capability box plots, summary report, and
                           per column the histogram, within and overall
                           indices with intervals, nonconformance; normal or
                           a fitted lognormal, Weibull or gamma
   Pareto Plot             causes by count, the cumulative percent, combined
                           causes, grouped cells and a test of equal rates
   Variability / Attribute Gauge Chart
                           the variability chart of nested groups with its
                           standard deviation chart, variance components
                           (EMS or REML), Gauge R&R; for a categorical
                           response, agreement and kappa statistics

   The numbers are resources/py/smui/quality.py's. A point that stands for
   a subgroup (a cell, a part) carries the rows of that subgroup: a click
   selects them, and a selection anywhere rings the subgroups that hold a
   selected row.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;

  /* ---- colours that read on both themes ------------------------------------------ */
  function colors() {
    const t = SM.util.themeColors();
    const d = t.dark;
    return {
      text: t.text, muted: t.muted, grid: t.grid, surface: t.surface,
      point: d ? '#7fb2ff' : SM.report.BASE,
      line: d ? 'rgba(127,178,255,0.55)' : 'rgba(47,102,144,0.55)',
      limit: d ? '#ff7a6b' : '#c0392b',
      center: d ? '#7bd88f' : '#2e7d32',
      flag: d ? '#ff5c4d' : '#d62728',
      zone: d ? 'rgba(255,255,255,0.32)' : 'rgba(60,40,30,0.30)',
      spec: d ? '#ffb454' : '#b35900',
      target: d ? '#c9a0ff' : '#6c5b7b',
      within: d ? '#7bd88f' : '#2e7d32',
      overall: d ? '#ff9e7a' : '#b0413e',
      mean: d ? '#ffd166' : '#8c6d00',
      shadeA: 'rgba(214,39,40,0.12)', shadeB: 'rgba(230,170,0,0.13)', shadeC: 'rgba(46,125,50,0.12)',
    };
  }

  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  // Plotly reads a few HTML tags in its text; table values are shown as text.
  const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const pct = (x) => (x == null ? null : 100 * x);

  function span(values, frac = 0.08) {
    let lo = Infinity, hi = -Infinity;
    for (const v of values) if (v != null && Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (!Number.isFinite(lo)) return [0, 1];
    if (lo === hi) { const d = Math.abs(lo) * 0.05 || 1; return [lo - d, hi + d]; }
    const d = (hi - lo) * frac;
    return [lo - d, hi + d];
  }

  /* A graph no wider than the report (phones): the report's width, less
     the outlines' indentation. */
  function roomOf(ctx) {
    const b = ctx.report && ctx.report.body;
    return b ? b.clientWidth - 72 : 0;
  }
  function fitWidth(ctx, w, min = 300) {
    const avail = roomOf(ctx);
    return avail > min ? Math.min(w, avail) : w;
  }

  /* Under each graph, Python that draws it with matplotlib from a CSV export
     of the table (res.plot_code from quality.py, which makes the graph's
     numbers): the report's rows, the light theme's colours, the graph's size
     at 100 pixels an inch. The graph's display options go with the call
     (plot), with the room the report has, so that the code sizes the figure
     as the page sizes the graph. A graph in a row takes its code with it. */
  const withCode = (graph, code) => (code ? el('div', { class: 'sm-q-plotcode' }, graph, code) : graph);
  const where = (ctx) => ctx.where || [];

  /* JMP's quantile of sorted values: the (n + 1)p-th value, interpolated
     between its neighbours (numpy's method="weibull"); before the first
     value or after the last, that value. */
  function jmpQuantile(sorted, p) {
    const n = sorted.length;
    if (!n) return NaN;
    const h = (n + 1) * p;
    if (h <= 1) return sorted[0];
    if (h >= n) return sorted[n - 1];
    const k = Math.floor(h);
    return sorted[k - 1] + (h - k) * (sorted[k] - sorted[k - 1]);
  }

  /* A box plot as JMP draws it (Distribution's outlier box plot): the
     quartiles by the (n + 1)p rule, the whiskers to the furthest values
     within 1.5 IQR of the box. Plotly gets these numbers, not the values. */
  function boxStats(values) {
    const s = values.filter((v) => typeof v === 'number' && Number.isFinite(v)).sort((a, b) => a - b);
    const q1 = jmpQuantile(s, 0.25), med = jmpQuantile(s, 0.5), q3 = jmpQuantile(s, 0.75);
    const iqr = q3 - q1;
    let lf = Infinity, uf = -Infinity;
    for (const v of s) { if (v >= q1 - 1.5 * iqr && v < lf) lf = v; if (v <= q3 + 1.5 * iqr && v > uf) uf = v; }
    return { q1, med, q3, lf, uf };
  }

  function tickAxis(labels, max = 30) {
    const n = labels.length;
    if (labels.every((l, i) => l === String(i + 1))) return {};
    const step = Math.max(1, Math.ceil(n / max));
    const tickvals = [], ticktext = [];
    for (let i = 0; i < n; i += step) { tickvals.push(i + 1); ticktext.push(esc(labels[i])); }
    return { tickvals, ticktext, tickmode: 'array' };
  }

  /* A limit drawn as steps: each point's value over [x − ½, x + ½], broken
     where the phase changes or the value is missing. */
  function stepLine(xs, ys, breaks) {
    const X = [], Y = [];
    for (let i = 0; i < xs.length; i++) {
      const y = num(ys[i]);
      if (y == null) continue;
      const fresh = i === 0 || breaks.has(i) || num(ys[i - 1]) == null;
      if (fresh && X.length) { X.push(null); Y.push(null); }
      X.push(xs[i] - 0.5); Y.push(y);
      const end = i === xs.length - 1 || breaks.has(i + 1) || num(ys[i + 1]) == null;
      if (end) { X.push(xs[i] + 0.5); Y.push(y); }
    }
    return { x: X, y: Y };
  }

  /* Points that stand for groups of rows. The core links a trace whose rows
     are arrays as bars (a companion bar shows the selected share), so the
     companion is made invisible (tiny, on axes of fixed range) and the
     selection is shown here: a ring over each point holding a selected row. */
  function groupPlot(ctx, traces, layout, opts, groups) {
    const all = traces.slice();
    const rings = [];
    for (const g of groups) {
      const t = all[g.trace] = { ...all[g.trace], rows: g.rows, rowsScale: 1e-12 };
      rings.push(all.length);
      all.push({ type: 'scatter', mode: 'markers', x: [], y: [], xaxis: t.xaxis, yaxis: t.yaxis, hoverinfo: 'skip', showlegend: false, name: 'selected',
        marker: { size: 13, color: 'rgba(0,0,0,0)', line: { color: SM.report.SELECTED, width: 2.4 } } });
    }
    const own = opts.onDraw;
    return ctx.plot(all, { dragmode: 'select', ...layout }, { ...opts, onDraw: (gd) => {
      const t = ctx.table;
      let off = () => {};
      const update = () => {
        if (!gd.isConnected) { off(); return; }
        const st = t.state;
        const xs = [], ys = [];
        for (const g of groups) {
          const X = [], Y = [];
          g.rows.forEach((rs, k) => { if (rs && num(g.ys[k]) != null && rs.some((r) => st[r] & 1)) { X.push(g.xs[k]); Y.push(g.ys[k]); } });
          xs.push(X); ys.push(Y);
        }
        try { SM.report.restyle(gd, { x: xs, y: ys }, rings); } catch (e) { off(); }
      };
      if (t) { off = t.on('rowstate', update); update(); }
      if (own) own(gd);
    } });
  }

  /* The spec limits of a column: set in this report, else the launch's,
     else the column's Spec Limits property. */
  function specOf(ctx, col) {
    const own = ctx.opt('spec', undefined, col.id);
    if (own !== undefined) return own;
    const launch = (ctx.opt('specs', {}) || {})[col.name];
    if (launch && (launch.lsl != null || launch.usl != null)) return launch;
    const s = col.specLimits;
    return s && (s.lsl != null || s.usl != null) ? s : null;
  }

  /* What the spec limit fields are for (the report's Spec Limits… and the
     launch's). */
  const SPEC_HELP = {
    lsl: 'The lower specification limit: values below it are nonconforming. Empty when there is none; with one limit only the one-sided indices are given (Cpk is then Cpl or Cpu), and no Cp, Pp or goal plot point.',
    target: 'The target value, for Cpm (with both limits). Empty: no Cpm, and the middle of the limits centres the goal plot and the capability box plots.',
    usl: 'The upper specification limit: values above it are nonconforming. Empty when there is none; it must be above the lower one.',
  };

  async function specDialog(ctx, cols, { title = 'Spec Limits', store = true } = {}) {
    const fields = cols.flatMap((c) => {
      const s = specOf(ctx, c) || {};
      return [
        { key: `${c.id}|lsl`, label: `${c.name}: lower spec limit`, type: 'number', value: s.lsl ?? null, help: SPEC_HELP.lsl, helpLabel: 'Lower spec limit' },
        { key: `${c.id}|target`, label: `${c.name}: target`, type: 'number', value: s.target ?? null, help: SPEC_HELP.target, helpLabel: 'Target' },
        { key: `${c.id}|usl`, label: `${c.name}: upper spec limit`, type: 'number', value: s.usl ?? null, help: SPEC_HELP.usl, helpLabel: 'Upper spec limit' },
      ];
    });
    const v = await SM.ui.form({ title, lead: 'Leave a limit empty when there is none. The column\'s Spec Limits property (Cols > Column Info) gives the defaults.', fields,
      validate: (x) => { for (const c of cols) { const lo = x[`${c.id}|lsl`], hi = x[`${c.id}|usl`]; if (lo != null && hi != null && !(lo < hi)) return `${c.name}: the lower limit must be below the upper`; } return null; } });
    if (!v) return null;
    const out = {};
    for (const c of cols) {
      const s = { lsl: v[`${c.id}|lsl`], target: v[`${c.id}|target`], usl: v[`${c.id}|usl`] };
      out[c.id] = s.lsl == null && s.usl == null ? null : s;
    }
    if (store) {
      for (const c of cols) ctx.set('spec', out[c.id], c.id, { rerun: false });
      ctx.report.run();
    }
    return out;
  }

  /* Select columns in the table's grid (the Goal Plot's points are columns). */
  function selectColumns(table, ids, add) {
    const app = SM.app;
    const g = app && app.grids ? app.grids.get(table.id) : null;
    if (!g) return;
    if (!add) g.colSel.clear();
    for (const id of ids) { if (add && g.colSel.has(id)) g.colSel.delete(id); else g.colSel.add(id); }
    g.refresh();
    app.emit('columnselection', g.selectedColumns());
  }

  function selectedColumnIds(table) {
    const g = SM.app && SM.app.grids ? SM.app.grids.get(table.id) : null;
    return g ? new Set(g.colSel) : new Set();
  }

  /* ==================================================================================
     Control Chart
     ================================================================================== */
  const CHARTS = [
    ['auto', 'Automatic'], ['xbar_r', 'XBar & R'], ['xbar_s', 'XBar & S'], ['ir', 'Individual & Moving Range'], ['lj', 'Levey Jennings'],
    ['run', 'Run Chart'], ['p', 'P'], ['np', 'NP'], ['c', 'C'], ['u', 'U'], ['ewma', 'EWMA'], ['cusum', 'CUSUM'],
  ];
  const SIGMAS = [['range', 'Range'], ['std', 'Standard Deviation'], ['pooled', 'Pooled Standard Deviation'], ['mr', 'Moving Range'], ['mmr', 'Median Moving Range'], ['lj', 'Levey Jennings (overall)']];

  function chartType(ctx) {
    const c = ctx.opt('chart', 'auto');
    if (c !== 'auto') return c;
    // a subgroup size of 1 is every row a point, as no size is (XBar & R has no range then)
    return ctx.role('subgroup') || ctx.opt('subgroupSize', null) >= 2 ? 'xbar_r' : 'ir';
  }

  const chartTitle = (res, name) => `${res.chart_label}${/Chart$/.test(res.chart_label) ? '' : ' chart'} of ${name}`;

  function hoverText(res, pn, u, i, xTitle) {
    const v = pn.values[i];
    let s = `${esc(xTitle)} ${esc(u.label)}: ${pn.key === 'cusum' ? 'C+ ' : ''}${fmt(v)}${u.n > 1 ? ` (n ${u.n})` : ''}`;
    if (pn.lower) s += `, C− ${fmt(pn.lower[i])}`;
    const t = pn.tests && pn.tests[i];
    if (t && t.length) s += t.map((k) => `<br>Test ${k}: ${esc(res.test_text[String(k)])}`).join('');
    return s;
  }

  function chartFigure(ctx, res, o, xTitle) {
    const c = colors();
    const units = res.units;
    const N = units.length;
    const xs = units.map((_, i) => i + 1);
    const breaks = new Set();
    for (let i = 1; i < N; i++) if (units[i].phase !== units[i - 1].phase) breaks.add(i);
    const panels = res.panels;
    const P = panels.length;
    const traces = [], groups = [], shapes = [], annotations = [];
    const domains = P === 1 ? [[0, 1]] : [[0.43, 1], [0, 0.33]];
    const layout = { margin: { l: 64, r: 96, t: breaks.size ? 24 : 10, b: 48 }, showlegend: false };
    panels.forEach((pn, p) => {
      const yref = p === 0 ? 'y' : `y${p + 1}`;
      const on = { xaxis: 'x', yaxis: yref };
      const vals = pn.values.map(num);
      const lower = pn.lower ? pn.lower.map(num) : null;
      const kz = (pn.k || res.k) / 3;
      const inRange = vals.concat(lower || []);
      const band = (m, s) => pn.cl.map((cl, i) => (num(cl) != null && num(pn.sd[i]) != null ? cl + s * m * kz * pn.sd[i] : null));
      if (o.shade && pn.zones) {
        // A, B and C zones, filled between the lines from the bottom up
        const levels = [-3, -2, -1, 1, 2, 3];
        const fills = [c.shadeA, c.shadeB, c.shadeC, c.shadeB, c.shadeA];
        levels.forEach((m, j) => {
          const L = stepLine(xs, band(Math.abs(m), Math.sign(m)), breaks);
          traces.push({ type: 'scatter', mode: 'lines', ...L, line: { width: 0, shape: 'hv' }, fill: j === 0 ? 'none' : 'tonexty', fillcolor: j === 0 ? undefined : fills[j - 1], hoverinfo: 'skip', ...on });
        });
      }
      if ((o.zones || o.shade) && pn.zones) {
        for (const m of [1, 2]) for (const s of [-1, 1]) {
          const ys = band(m, s);
          traces.push({ type: 'scatter', mode: 'lines', ...stepLine(xs, ys, breaks), line: { color: c.zone, width: 1, dash: 'dot', shape: 'hv' }, hoverinfo: 'skip', ...on });
          inRange.push(...ys);
        }
      }
      if (o.limits && pn.key !== 'run') {
        for (const key of ['ucl', 'lcl']) {
          const ys = pn[key].map(num);
          if (!ys.some((v) => v != null)) continue;
          traces.push({ type: 'scatter', mode: 'lines', ...stepLine(xs, ys, breaks), line: { color: c.limit, width: 1.4, shape: 'hv' }, hoverinfo: 'skip', ...on });
          inRange.push(...ys);
        }
      }
      if (o.center) {
        const ys = pn.cl.map(num);
        traces.push({ type: 'scatter', mode: 'lines', ...stepLine(xs, ys, breaks), line: { color: c.center, width: 1.4, shape: 'hv' }, hoverinfo: 'skip', ...on });
        inRange.push(...ys);
      }
      if (pn.data) {
        const ys = pn.data.map(num);
        traces.push({ type: 'scatter', mode: 'markers', x: xs, y: ys, marker: { size: 5, symbol: 'circle-open', color: c.muted }, hovertemplate: 'mean %{y}<extra></extra>', ...on });
        inRange.push(...ys);
      }
      const flagged = (pn.tests || []).map((t) => !!(t && t.length));
      // the CUSUM's two sums alarm on their own
      const flagUp = pn.key === 'cusum' ? vals.map((v, i) => flagged[i] && v != null && num(pn.ucl[i]) != null && v > pn.ucl[i]) : flagged;
      const flagDn = lower ? lower.map((v, i) => flagged[i] && v != null && num(pn.lcl[i]) != null && v < pn.lcl[i]) : null;
      // the connecting line, broken between phases (the points keep one entry per subgroup)
      const joined = (ys) => { const X = [], Y = []; ys.forEach((v, i) => { if (breaks.has(i)) { X.push(null); Y.push(null); } X.push(xs[i]); Y.push(v); }); return { x: X, y: Y }; };
      traces.push({ type: 'scatter', mode: 'lines', ...joined(vals), connectgaps: false, line: { color: c.line, width: 1 }, hoverinfo: 'skip', ...on });
      if (lower) traces.push({ type: 'scatter', mode: 'lines', ...joined(lower), connectgaps: false, line: { color: c.line, width: 1, dash: 'dash' }, hoverinfo: 'skip', ...on });
      const at = traces.length;
      traces.push({
        type: 'scatter', mode: 'markers', x: xs, y: vals,
        marker: { size: N > 160 ? 4 : 6, color: vals.map((_, i) => (flagUp[i] ? c.flag : c.point)) },
        hovertext: units.map((u, i) => hoverText(res, pn, u, i, xTitle)), hovertemplate: '%{hovertext}<extra></extra>', ...on, name: pn.title,
      });
      groups.push({ trace: at, xs, ys: vals, rows: units.map((u) => u.rows) });
      if (lower) {
        const at2 = traces.length;
        traces.push({ type: 'scatter', mode: 'markers', x: xs, y: lower, marker: { size: N > 160 ? 4 : 6, color: lower.map((_, i) => (flagDn[i] ? c.flag : c.point)), symbol: 'diamond' },
          hovertext: units.map((u, i) => hoverText(res, pn, u, i, xTitle)), hovertemplate: '%{hovertext}<extra></extra>', ...on, name: 'lower CUSUM' });
        groups.push({ trace: at2, xs, ys: lower, rows: units.map((u) => u.rows) });
      }
      // the test numbers over the points that fail
      const tx = [], ty = [], tt = [];
      (pn.tests || []).forEach((t, i) => {
        if (!t || !t.length) return;
        const y = vals[i] != null ? vals[i] : (lower ? lower[i] : null);
        if (y == null) return;
        tx.push(xs[i]); ty.push(pn.key === 'cusum' && lower && lower[i] != null && Math.abs(lower[i]) > Math.abs(vals[i] || 0) ? lower[i] : y); tt.push(t.join(','));
      });
      if (tx.length) traces.push({ type: 'scatter', mode: 'text', x: tx, y: ty, text: tt, textposition: 'top center', textfont: { color: c.flag, size: 10 }, hoverinfo: 'skip', ...on, cliponaxis: false });
      // the limits' values at the right, as JMP writes them
      const last = (a) => { for (let i = a.length - 1; i >= 0; i--) if (num(a[i]) != null) return a[i]; return null; };
      const labs = [];
      if (o.limits && pn.key !== 'run') { const u = last(pn.ucl), l = last(pn.lcl); if (u != null) labs.push(['UCL', u, c.limit]); if (l != null) labs.push(['LCL', l, c.limit]); }
      if (o.center) { const a = last(pn.cl); if (a != null) labs.push([pn.key === 'cusum' ? 'Target' : 'Avg', a, c.center]); }
      for (const [name, v, col] of labs) annotations.push({ xref: 'paper', x: 1.004, xanchor: 'left', yref, y: v, text: `${name}=${fmt(v, { sig: 5 })}`, showarrow: false, font: { size: 10, color: col } });
      const [lo, hi] = span(inRange, 0.1);
      const ax = { domain: domains[p], anchor: 'x', title: { text: esc(pn.ylabel), font: { size: 11 } }, range: [lo, hi], zeroline: false };
      layout[p === 0 ? 'yaxis' : `yaxis${p + 1}`] = ax;
    });
    // phases: a line between them, their names above
    const bounds = [0, ...breaks, N];
    for (const b of breaks) shapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: b + 0.5, x1: b + 0.5, y0: 0, y1: 1, line: { color: c.muted, width: 1, dash: 'dash' } });
    if (breaks.size) {
      for (let k = 0; k + 1 < bounds.length; k++) {
        const a = bounds[k], b = bounds[k + 1];
        const ph = res.phases.find((x) => x.code === units[a].phase);
        annotations.push({ xref: 'x', x: (a + b + 1) / 2, yref: 'paper', y: 1, yanchor: 'bottom', text: esc(ph ? ph.label : ''), showarrow: false, font: { size: 10.5, color: c.muted } });
      }
    }
    layout.xaxis = { range: [0.5, N + 0.5], anchor: P > 1 ? 'y2' : 'y', title: { text: esc(xTitle), font: { size: 11 } }, zeroline: false, showgrid: false, ...tickAxis(units.map((u) => u.label)) };
    layout.shapes = shapes;
    layout.annotations = annotations;
    const width = fitWidth(ctx, Math.max(520, Math.min(820, 170 + 18 * N)));
    return groupPlot(ctx, traces, layout, { width, height: P > 1 ? 440 : 300, title: chartTitle(res, res.y) }, groups);
  }

  function limitSummaries(ctx, res) {
    return ctx.rt(res.limits, { sortable: false, caption: null });
  }

  /* Capability tables, shared by the Control Chart and Process
     Capability. */
  function capabilityParts(ctx, cap, ppm) {
    const lv = fmt(100 * (1 - ctx.alpha));
    const idxCols = [{ key: 'index', label: 'Index', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'lower', label: `Lower ${lv}% CI` }, { key: 'upper', label: `Upper ${lv}% CI` }];
    const parts = [];
    if (cap.within && cap.within.length) parts.push(ctx.rt({ columns: idxCols, rows: cap.within }, { sortable: false, caption: 'Within Sigma Capability', key: 'cap-within' }));
    if (cap.overall && cap.overall.length) parts.push(ctx.rt({ columns: idxCols, rows: cap.overall }, { sortable: false, caption: 'Overall Sigma Capability', key: 'cap-overall' }));
    const f = ppm ? (x) => (x == null ? null : 1e6 * x) : pct;
    const unit = ppm ? 'PPM' : '%';
    const e = cap.expected_within || {}, eo = cap.expected_overall || {};
    const rows = [
      { where: 'Below LSL', obs: f(cap.observed.below), exo: cap.lsl != null ? f(eo.below) : null, exw: cap.lsl != null ? f(e.below) : null },
      { where: 'Above USL', obs: f(cap.observed.above), exo: cap.usl != null ? f(eo.above) : null, exw: cap.usl != null ? f(e.above) : null },
      { where: 'Total Outside', obs: f(cap.observed.total), exo: f(eo.total), exw: f(e.total) },
    ];
    const cols = [{ key: 'where', label: 'Portion', fmt: 'text' }, { key: 'obs', label: `Observed ${unit}` }, { key: 'exo', label: `Expected Overall ${unit}` }];
    if (cap.expected_within) cols.push({ key: 'exw', label: `Expected Within ${unit}` });
    parts.push(ctx.rt({ columns: cols, rows }, { sortable: false, caption: 'Nonconformance', key: 'cap-noncon' }));
    return parts;
  }

  function capabilityNote(cap) {
    if (cap.dist && cap.dist !== 'normal') {
      return `Nonnormal: a ${cap.fit.label} fitted by maximum likelihood (scipy, threshold 0); Pp = (USL − LSL)/(P99.865 − P0.135), Ppk = min((P50 − LSL)/(P50 − P0.135), (USL − P50)/(P99.865 − P50)), the percentile method of ISO 22514, and the expected nonconformance from the fitted distribution. There are no within-sigma indices for a nonnormal fit.`;
    }
    return `Within sigma: ${cap.within_method || 'the chart\'s'}. Intervals: Cp and Pp from χ², Cpk and Ppk by Bissell's normal approximation, the one-sided indices from the noncentral t (exact for normal data), Cpm by Boyles' approximation; the within-sigma intervals use the effective degrees of freedom of the within σ (${fmt(cap.nu_within, { sig: 4 })}). JMP computes some of its intervals by other formulas, so they can differ in the last digits. Expected nonconformance assumes a normal distribution.`;
  }

  async function controlRender(ctx) {
    const ys = ctx.roles('y');
    const chart = chartType(ctx);
    const o = {
      zones: ctx.opt('zones', false), shade: ctx.opt('shade', false), limits: ctx.opt('showLimits', true), center: ctx.opt('showCenter', true),
    };
    const tests = ctx.opt('tests', [1]);
    const known = ctx.opt('known', null);
    const ew = ctx.opt('ewma', {}) || {};
    const cu = ctx.opt('cusum', {}) || {};
    const xTitle = ctx.name('subgroup') || 'Sample';
    const results = [];
    for (const col of ys) {
      const spec = specOf(ctx, col);
      const payload = {
        y: col.name, chart, subgroup: ctx.name('subgroup'), phase: ctx.name('phase'), n_trials: ctx.name('ntrials'),
        subgroup_size: ctx.role('subgroup') ? null : ctx.opt('subgroupSize', null), sigma: ctx.opt('sigma', null), k: ctx.opt('k', 3),
        mr_span: ctx.opt('mrSpan', 2), known_mean: known ? known.mean ?? null : null, known_sigma: known ? known.sigma ?? null : null,
        lam: ew.lam ?? 0.2, ewma_l: ew.L ?? 3, target: chart === 'cusum' ? (cu.target ?? null) : (ew.target ?? null),
        cusum_h: cu.h ?? 4, cusum_k: cu.k ?? 0.5, head_start: !!cu.headStart,
        tests, test_n: ctx.opt('testN', {}), dispersion_tests: ctx.opt('dispTests', false), alarm: !!ctx.opt('alarmReport', false),
        spec: ctx.opt('capability', true) && spec ? spec : null, alpha: ctx.alpha, where: where(ctx),
        plot: { zones: o.zones, shade: o.shade, limits: o.limits, center: o.center, x_title: xTitle, room: roomOf(ctx) },
      };
      const res = await ctx.call('quality.control_chart', payload);
      const outline = ctx.outline(res.error ? col.name : chartTitle(res, col.name), { key: `y:${col.id}`, menu: () => columnMenu(ctx, col, res) });
      if (res.error) { outline.add(ctx.warn(`${col.name}: ${res.error}`)); continue; }
      results.push({ col, res });
      outline.add(chartFigure(ctx, res, o, xTitle), ctx.code(res.plot_code));
      const s = res.summary;
      const sig = s.sigma.filter((x) => x.sigma != null);
      const notes = [];
      if (res.method) notes.push(`Sigma: ${s.sigma_method}${sig.length === 1 ? ` = ${fmt(sig[0].sigma)}` : ''}; ${res.k}σ limits. Overall standard deviation ${fmt(s.overall_sd)} over ${s.n_values} values in ${s.n_points} ${ctx.role('subgroup') || payload.subgroup_size ? 'subgroups' : 'points'}.`);
      if (['xbar_r', 'xbar_s'].includes(chart) && res.method === 'range') notes.push('σ is the average of Rᵢ/d₂(nᵢ), JMP\'s formula for unequal subgroups; with equal sizes it is R̄/d₂. The constants d₂, d₃, c₄ are computed exactly (quadrature), not rounded from a table.');
      if (chart === 'ewma') notes.push(`EWMA with λ = ${fmt(payload.lam)} and ${fmt(payload.ewma_l)}σ limits from the exact variance of the statistic at each point; the center is ${payload.target != null ? 'the target' : 'the grand mean'}.`);
      if (chart === 'cusum') {
        const pn = res.panels[0];
        notes.push(`Tabular CUSUM about ${payload.target != null ? `the target ${fmt(payload.target)}` : `the mean ${fmt(s.mean)}`}: h = ${fmt(payload.cusum_h)} and k = ${fmt(payload.cusum_k)} in standard errors of the subgroup mean${pn.units === 'data' ? ', drawn in data units' : ', drawn standardized (the subgroup sizes differ)'}. Average run length (Siegmund's approximation): ${fmt(pn.arl.in_control, { sig: 4 })} in control, ${fmt(pn.arl.at_shift, { sig: 3 })} at a shift of ${fmt(pn.arl.shift)} standard errors.`);
      }
      for (const n of res.notes) notes.push(n);
      if (ctx.opt('limitSummaries', true)) {
        const ls = ctx.outline('Limit Summaries', { parent: outline, key: `limits:${col.id}` });
        ls.add(limitSummaries(ctx, res), ...notes.map((n) => ctx.note(n)), ctx.code(res.code));
      } else outline.add(ctx.code(res.code));
      if (tests.length) {
        const rows = res.tests_table.rows;
        const to = ctx.outline(`Tests${rows.length ? ` (${rows.length} point${rows.length > 1 ? 's' : ''})` : ''}`, { parent: outline, key: `tests:${col.id}`, closed: !rows.length });
        to.add(ctx.note(`Tests chosen: ${tests.join(', ')}. ${tests.map((t) => `${t}: ${res.test_text[String(t)]}`).join('; ')}. Zones are thirds of the distance from the center line to the limits.`));
        if (rows.length) {
          to.add(ctx.rt(res.tests_table, { onRow: (r, ev) => ctx.table.select(res.units[r.index].rows, ev && ev.shiftKey ? 'add' : 'replace'), key: 'tests' }),
            ctx.note('Click a line to select the rows of that subgroup.'));
        } else to.add(ctx.note('No point fails a chosen test.'));
      }
      if (res.capability) {
        const cap = res.capability;
        const co = ctx.outline(`Process Capability Analysis of ${col.name}`, { parent: outline, key: `cap:${col.id}`, info: 'p:capability', menu: () => [
          { label: 'Spec Limits…', action: () => specDialog(ctx, [col]) },
          ctx.check('Show PPM', 'ppm', null, false),
          { label: 'Remove', action: () => ctx.set('capability', false) },
        ] });
        if (cap.error) co.add(ctx.warn(cap.error));
        else {
          co.add(ctx.kv([['Lower Spec Limit', cap.lsl], ['Target', cap.target], ['Upper Spec Limit', cap.usl], ['Mean', cap.mean], ['Std Dev (Within)', cap.sd_within], ['Std Dev (Overall)', cap.sd_overall], ['Stability Index', cap.stability]].filter((x) => x[1] != null)));
          co.add(ctx.row(...capabilityParts(ctx, cap, ctx.opt('ppm', false))), ctx.note(`${capabilityNote(cap)} ${cap.note || ''}`));
        }
      }
      if (chart === 'run') {
        const rt = await ctx.call('quality.runs_test', { y: col.name, subgroup: ctx.name('subgroup'), where: where(ctx) });
        const ro = ctx.outline('Runs Test', { parent: outline, key: `runs:${col.id}` });
        if (rt.error) ro.add(ctx.note(rt.error));
        else ro.add(ctx.kv([['Median', rt.median], ['Points above / below', `${rt.n_above} / ${rt.n_below}`, 'text'], ['Runs about the median', rt.runs, 'int'], ['Expected runs', rt.expected], ['Z', rt.z], ['Prob > |Z|', rt.p, 'p'], ['Prob < Z (clustering, trends)', rt.p_clustering, 'p'], ['Prob > Z (mixtures, oscillation)', rt.p_mixtures, 'p']]),
          ctx.note('Wald–Wolfowitz runs test about the median (statsmodels runstest_1samp, with the continuity correction).'), ctx.code(rt.code));
      }
    }
    ctx.results = results;
    if (ctx.opt('alarmReport', false)) alarmReport(ctx, results, tests);
  }

  /* Show Alarm Report (JMP's): for each chart from the top of the report (a
     process's XBar and R are two), its samples out of control (failing at
     least one chosen test) and the alarm rate, the proportion of its samples
     with a value that are; the tests each chart runs; and the samples out of
     control with the tests they fail. Excluded rows are not in the charts, so
     they are never counted (JMP counts excluded samples only with Test
     Excluded Subgroups and Show Excluded Region). */
  const ALARM_FIRST = "first = 1   # the place of this process's first chart in the report, from the top";
  function alarmReport(ctx, results, tests) {
    const ob = ctx.outline('Alarm Report', { key: 'alarm', info: 'cc:alarm', menu: () => [{ label: 'Hide', action: () => ctx.set('alarmReport', false) }] });
    if (!tests.length) { ob.add(ctx.note('No test is chosen: choose them in the red triangle\'s Tests, and the report lists the samples that fail them.')); return; }
    if (!results.length) { ob.add(ctx.note('No chart to report on.')); return; }
    const chosen = [...new Set(tests)].sort((a, b) => a - b);
    const summary = [], enabled = [], alarms = [], codes = [];
    let pos = 0;
    for (const { col, res } of results) {
      const first = pos + 1;
      res.panels.forEach((pn) => {
        pos++;
        const chart = `${pn.title} of ${col.name}`;
        const vals = pn.values.map(num);
        const has = vals.map((v, i) => v != null || (pn.lower && num(pn.lower[i]) != null));
        const out = (pn.tests || []).map((t, i) => !!(t && t.length) && has[i]);
        const nS = has.filter(Boolean).length, nOut = out.filter(Boolean).length;
        const row = { pos, chart, n: nS, out: nOut, rate: nS ? nOut / nS : null };
        for (const t of chosen) row[`t${t}`] = (pn.tests_used || []).includes(t) ? (pn.tests || []).filter((x, i) => out[i] && x.includes(t)).length : null;
        summary.push(row);
        for (const t of pn.tests_used || []) enabled.push({ pos, chart, test: t, what: res.test_text[String(t)] });
        (pn.tests || []).forEach((t, i) => { if (out[i]) alarms.push({ pos, chart, sample: res.units[i].label, value: vals[i] != null ? vals[i] : num(pn.lower && pn.lower[i]), tests: t.join(', '), rows: res.units[i].rows, n: res.units[i].rows.length }); });
      });
      if (res.alarm_code) codes.push(res.alarm_code.replace(ALARM_FIRST, `first = ${first}   # the place of ${col.name}'s first chart in the report, from the top`));
    }
    const testCols = chosen.map((t) => ({ key: `t${t}`, label: `Test ${t}`, fmt: 'int' }));
    ob.add(ctx.rt({ columns: [{ key: 'pos', label: 'Position', fmt: 'int' }, { key: 'chart', label: 'Chart', fmt: 'text' }, { key: 'n', label: 'Samples', fmt: 'int' }, { key: 'out', label: 'Total Samples Out of Control', fmt: 'int' }, { key: 'rate', label: 'Alarm Rate', digits: 4 }, ...testCols], rows: summary, caption: 'Alarms' }, { sortable: false, key: 'alarm:summary' }),
      ctx.rt({ columns: [{ key: 'pos', label: 'Position', fmt: 'int' }, { key: 'chart', label: 'Chart', fmt: 'text' }, { key: 'test', label: 'Test', fmt: 'int' }, { key: 'what', label: 'Description', fmt: 'text' }], rows: enabled, caption: 'Enabled Tests' }, { sortable: false, key: 'alarm:tests' }));
    if (alarms.length) {
      ob.add(ctx.rt({ columns: [{ key: 'pos', label: 'Position', fmt: 'int' }, { key: 'chart', label: 'Chart', fmt: 'text' }, { key: 'sample', label: ctx.name('subgroup') || 'Sample', fmt: 'text' }, { key: 'value', label: 'Value' }, { key: 'tests', label: 'Tests Failed', fmt: 'text' }, { key: 'n', label: 'Rows', fmt: 'int', hidden: true }], rows: alarms, caption: 'Samples Out of Control' },
        { key: 'alarm:samples', maxRows: 500, onRow: (r, ev) => ctx.table.select(r.rows, ev && ev.shiftKey ? 'add' : 'replace') }));
    }
    ob.add(ctx.note(`The charts are numbered from the top of the report. A sample is out of control when it fails at least one of the tests its chart runs (the Enabled Tests: every chosen test on the charts of the process; test 1 only on the range, standard deviation and moving range charts unless Test the Range, Std Dev and Moving Range Charts too is on; EWMA and CUSUM take test 1, a run chart 2 to 4); the alarm rate is those samples over the chart's samples with a value.${alarms.length ? ' Click a line of Samples Out of Control to select its rows.' : ' No sample is out of control.'}`),
      ...(codes.length ? [ctx.code(codes.join('\n\n# ----\n'))] : []));
  }

  function columnMenu(ctx, col, res) {
    return [
      { label: 'Spec Limits…', action: () => specDialog(ctx, [col]) },
      { label: 'Save Limits', submenu: () => [
        { label: 'in New Table', action: () => saveLimitsTable(ctx, [{ col, res }]) },
        { label: 'in Table Notes', action: () => saveLimitsNotes(ctx, [{ col, res }]) },
      ] },
      { label: 'Save Summaries', action: () => saveSummaries(ctx, col, res), disabled: !!res.error },
      { separator: true },
      { label: 'Remove', action: () => { const ids = (ctx.spec.roles.y || []).filter((id) => id !== col.id); if (!ids.length) ctx.report.app.closeReport(ctx.report); else { ctx.spec.roles.y = ids; ctx.report.run(); } } },
    ];
  }

  /* JMP's Save Limits > in New Table: a row per statistic (_Mean, _LCL,
     _UCL, _AvgR, ...), a column per process, and a Phase column with phases. */
  function saveLimitsTable(ctx, items) {
    items = items.filter((x) => x.res && !x.res.error);
    if (!items.length) return;
    const keysOf = (res) => {
      const out = [];
      const disp = { r: 'R', s: 'S', mr: 'MR' };
      res.panels.forEach((pn, i) => {
        const tag = i === 0 ? '' : disp[pn.key] || pn.key.toUpperCase();
        out.push([i === 0 ? '_Mean' : `_Avg${tag}`, 'avg', i], [`_LCL${tag}`, 'lcl', i], [`_UCL${tag}`, 'ucl', i]);
      });
      return out;
    };
    const phases = items[0].res.phases.length ? items[0].res.phases.map((p) => p.label) : [null];
    const keys = keysOf(items[0].res);
    const rows = [];
    for (const ph of phases) {
      for (const [name, field, i] of keys) rows.push({ key: name, phase: ph, field, i });
      rows.push({ key: '_Std Dev', phase: ph, field: 'sigma' });
      rows.push({ key: '_Sample Size', phase: ph, field: 'n' });
    }
    const valueOf = (res, r) => {
      if (r.field === 'sigma') { const s = res.summary.sigma.find((x) => (x.phase ?? null) === r.phase); return s ? s.sigma : null; }
      const lim = res.limits.rows.filter((x) => (x.phase ?? null) === r.phase);
      if (r.field === 'n') { const n = lim[0] ? Number(String(lim[0].n).split(' ')[0]) : NaN; return Number.isFinite(n) ? n : null; }
      const row = lim.filter((x) => x.points === res.panels[r.i].ylabel)[0];
      return row ? row[r.field] : null;
    };
    const columns = [{ name: '_LimitsKey', dataType: 'character', values: rows.map((r) => r.key) }];
    if (phases[0] != null) columns.push({ name: ctx.name('phase') || 'Phase', dataType: 'character', values: rows.map((r) => r.phase) });
    for (const { col, res } of items) columns.push({ name: col.name, dataType: 'numeric', values: rows.map((r) => { const v = valueOf(res, r); return v == null ? NaN : v; }) });
    const t = new SM.Table({ name: SM.app.uniqueTableName(`${ctx.table.name} Limits`), columns, source: `Save Limits from ${ctx.report.title}`, notes: `Control limits (${items[0].res.chart_label}, ${items[0].res.summary.sigma_method || ''} sigma, ${items[0].res.k}σ) of ${items.map((x) => x.col.name).join(', ')}.` });
    SM.app.addTable(t);
  }

  function saveLimitsNotes(ctx, items) {
    const t = ctx.table;
    const lines = [];
    for (const { col, res } of items) {
      if (!res || res.error) continue;
      const parts = res.limits.rows.map((r) => `${r.points}${r.phase ? ` [${r.phase}]` : ''}: LCL ${fmt(r.lcl)}, Avg ${fmt(r.avg)}, UCL ${fmt(r.ucl)}`);
      lines.push(`Control limits of ${col.name} (${res.chart_label}, ${res.summary.sigma_method || ''}, ${res.k}σ), ${new Date().toISOString().slice(0, 10)}: ${parts.join('; ')}.`);
    }
    if (!lines.length) return;
    t.notes = [t.notes, ...lines].filter(Boolean).join('\n');
    if (SM.app && SM.app.panels) SM.app.panels.renderTable();
    SM.ui.toast(`Saved the limits to the notes of ${t.name}`);
  }

  function saveSummaries(ctx, col, res) {
    const u = res.units;
    const columns = [{ name: ctx.name('subgroup') || 'Sample', dataType: 'character', values: u.map((x) => x.label) }, { name: 'N', dataType: 'numeric', values: u.map((x) => x.n) }];
    if (res.phases.length) columns.push({ name: ctx.name('phase') || 'Phase', dataType: 'character', values: u.map((x) => (res.phases.find((p) => p.code === x.phase) || {}).label ?? null) });
    for (const pn of res.panels) {
      columns.push({ name: pn.ylabel, dataType: 'numeric', values: pn.values.map((v) => (v == null ? NaN : v)) });
      if (pn.key !== 'run') {
        columns.push({ name: `LCL ${pn.title}`, dataType: 'numeric', values: pn.lcl.map((v) => (v == null ? NaN : v)) });
        columns.push({ name: `UCL ${pn.title}`, dataType: 'numeric', values: pn.ucl.map((v) => (v == null ? NaN : v)) });
      }
      columns.push({ name: `Tests ${pn.title}`, dataType: 'character', values: pn.tests.map((t) => (t && t.length ? t.join(', ') : null)) });
    }
    SM.app.addTable(new SM.Table({ name: SM.app.uniqueTableName(`${col.name} ${res.chart_label} summaries`), columns, source: `Save Summaries from ${ctx.report.title}` }));
  }

  function controlTriangle(ctx) {
    const cur = chartType(ctx);
    const tests = ctx.opt('tests', [1]);
    const setTests = (t) => ctx.set('tests', [...new Set(t)].sort((a, b) => a - b));
    const ask = async (title, fields, key, map) => { const v = await SM.ui.form({ title, fields }); if (v) ctx.set(key, map ? map(v) : v); };
    const ew = ctx.opt('ewma', {}) || {}, cu = ctx.opt('cusum', {}) || {};
    return [
      { label: 'Chart Type', submenu: () => CHARTS.map(([k, l]) => ({ label: l, checked: ctx.opt('chart', 'auto') === k, action: () => ctx.set('chart', k) })) },
      { label: 'Sigma', submenu: () => [{ label: 'Default for the chart', checked: !ctx.opt('sigma', null), action: () => ctx.set('sigma', null) }, ...SIGMAS.map(([k, l]) => ({ label: l, checked: ctx.opt('sigma', null) === k, action: () => ctx.set('sigma', k) }))] },
      { label: 'K Sigma…', action: () => ask('K Sigma', [{ key: 'k', label: 'Limits at k sigma', type: 'number', value: ctx.opt('k', 3),
        help: 'The control limits lie k standard errors of the plotted statistic either side of the center line: 3, the default, gives about 3 false alarms in 1000 points of a stable normal process. The zones of the tests are thirds of this distance.' }], 'k', (v) => (v.k > 0 ? v.k : 3)) },
      { label: 'Specify Stats…', action: () => ask('Specify Stats', [
        { key: 'mean', label: 'Mean (center line); empty: estimated', type: 'number', value: (ctx.opt('known', null) || {}).mean ?? null,
          help: 'A known or historical process mean for the center line, instead of the grand mean of each phase. Not for the P, NP, C and U charts.' },
        { key: 'sigma', label: 'Sigma; empty: estimated', type: 'number', value: (ctx.opt('known', null) || {}).sigma ?? null,
          help: 'A known process standard deviation for the limits, instead of the estimate from the subgroups or moving ranges. Not for the P, NP, C and U charts.' }], 'known', (v) => (v.mean == null && v.sigma == null ? null : v)) },
      ctx.role('subgroup') ? null : { label: 'Subgroup Size…', action: () => ask('Subgroup Size', [{ key: 'n', label: 'Consecutive rows per subgroup (empty: none)', type: 'number', value: ctx.opt('subgroupSize', null),
        help: 'Without a Subgroup column: consecutive rows form subgroups of this many, 2 or more; a new subgroup also starts where the phase changes. Empty: each row is a point. The individual charts ignore it.' }], 'subgroupSize', (v) => (v.n >= 2 ? Math.round(v.n) : null)) },
      { label: 'Moving Range Span…', action: () => ask('Moving Range Span', [{ key: 'w', label: 'Points in each moving range', type: 'number', value: ctx.opt('mrSpan', 2),
        help: 'How many consecutive points each moving range spans, 2 or more (2, the default, is the difference of neighbours). The moving-range sigma is their average over d₂(span), and the Moving Range chart plots them.' }], 'mrSpan', (v) => (v.w >= 2 ? Math.round(v.w) : 2)) },
      { separator: true },
      { label: 'Tests', submenu: () => [
        ...[1, 2, 3, 4, 5, 6, 7, 8].map((t) => ({ label: `Test ${t}`, checked: tests.includes(t), action: () => setTests(tests.includes(t) ? tests.filter((x) => x !== t) : [...tests, t]) })),
        { separator: true },
        { label: 'All Tests', action: () => setTests([1, 2, 3, 4, 5, 6, 7, 8]) },
        { label: 'No Tests', action: () => setTests([]) },
        { label: 'Customize Tests…', action: () => customizeTests(ctx) },
        ctx.check('Test the Range, Std Dev and Moving Range Charts too', 'dispTests', null, false),
      ] },
      ctx.check('Show Zones', 'zones', null, false),
      ctx.check('Shade Zones', 'shade', null, false),
      ctx.check('Show Control Limits', 'showLimits', null, true),
      ctx.check('Show Center Line', 'showCenter', null, true),
      ctx.check('Show Limit Summaries', 'limitSummaries', null, true),
      ctx.check('Show Alarm Report', 'alarmReport', null, false),
      { separator: true },
      cur === 'ewma' ? { label: 'EWMA Parameters…', action: () => ask('EWMA Parameters', [
        { key: 'lam', label: 'λ (weight of the newest mean)', type: 'number', value: ew.lam ?? 0.2,
          help: 'Each point is λ·(the subgroup mean) + (1 − λ)·(the point before), 0 < λ ≤ 1: a small λ remembers far back and finds small shifts; λ = 1 is the XBar chart. 0.2 by default.' },
        { key: 'L', label: 'Limits at L sigma', type: 'number', value: ew.L ?? 3,
          help: 'The limits lie L standard errors of the EWMA statistic either side of the center, from its exact variance at each point (narrower at the start). 3 by default.' },
        { key: 'target', label: 'Target (empty: the mean)', type: 'number', value: ew.target ?? null,
          help: 'The center line and the value the average starts from; empty takes the grand mean of each phase.' }], 'ewma') } : null,
      cur === 'cusum' ? { label: 'CUSUM Parameters…', action: () => ask('CUSUM Parameters', [
        { key: 'h', label: 'h, decision interval (standard errors)', type: 'number', value: cu.h ?? 4,
          help: 'A sum beyond h, in standard errors of the subgroup mean, signals a shift. 4 by default; a larger h gives fewer false alarms and slower detection (the average run lengths are in the notes).' },
        { key: 'k', label: 'k, reference value (standard errors)', type: 'number', value: cu.k ?? 0.5,
          help: 'The slack taken off at every step, usually half the shift to detect: 0.5, the default, is tuned to a shift of one standard error.' },
        { key: 'target', label: 'Target (empty: the mean)', type: 'number', value: cu.target ?? null,
          help: 'The in-control mean the deviations are summed from; empty takes the grand mean of each phase.' },
        { key: 'headStart', label: 'Head start at h/2 (FIR)', type: 'check', value: !!cu.headStart,
          help: 'Start both sums at h/2 instead of 0 (the fast initial response of Lucas and Crosier), so that a process off target from the start signals sooner.' }], 'cusum') } : null,
      ctx.check('Show Capability', 'capability', null, true),
      { label: 'Spec Limits…', action: () => specDialog(ctx, ctx.roles('y')) },
      { label: 'Save Limits', submenu: () => [
        { label: 'in New Table', action: () => saveLimitsTable(ctx, ctx.results || []) },
        { label: 'in Table Notes', action: () => saveLimitsNotes(ctx, ctx.results || []) },
      ] },
    ].filter(Boolean);
  }

  async function customizeTests(ctx) {
    const n = { 2: 9, 3: 6, 4: 14, 5: [2, 3], 6: [4, 5], 7: 15, 8: 8, ...(ctx.opt('testN', {}) || {}) };
    const v = await SM.ui.form({
      title: 'Customize Tests', lead: 'The number of points in each pattern. JMP\'s defaults are shown; the Western Electric rules use 8 for test 2.',
      fields: [
        { key: 't2', label: 'Test 2: points in a row on one side', type: 'number', value: n[2], help: 'Test 2 fails at this many points in a row on one side of the center line: a shift in the mean. 9 by default (Western Electric: 8).' },
        { key: 't3', label: 'Test 3: points steadily increasing or decreasing', type: 'number', value: n[3], help: 'Test 3 fails at this many points in a row each higher (or each lower) than the one before: a trend. 6 by default.' },
        { key: 't4', label: 'Test 4: points alternating up and down', type: 'number', value: n[4], help: 'Test 4 fails at this many points in a row going up and down in turn: two alternating sources, such as two machines. 14 by default.' },
        { key: 't5m', label: 'Test 5: m points in zone A or beyond…', type: 'number', value: n[5][0], help: 'Test 5 fails when m of n points in a row lie in zone A or beyond (more than two thirds of the way to a limit), on the same side. m, 2 by default.' },
        { key: 't5n', label: '…out of n in a row', type: 'number', value: n[5][1], help: 'n of test 5, 3 by default; m must not be larger.' },
        { key: 't6m', label: 'Test 6: m points in zone B or beyond…', type: 'number', value: n[6][0], help: 'Test 6 fails when m of n points in a row lie in zone B or beyond (more than a third of the way to a limit), on the same side. m, 4 by default.' },
        { key: 't6n', label: '…out of n in a row', type: 'number', value: n[6][1], help: 'n of test 6, 5 by default; m must not be larger.' },
        { key: 't7', label: 'Test 7: points in a row in zone C', type: 'number', value: n[7], help: 'Test 7 fails at this many points in a row within zone C (the third next to the center line), on either side: less variation than the limits allow, often stratified subgroups. 15 by default.' },
        { key: 't8', label: 'Test 8: points in a row outside zone C', type: 'number', value: n[8], help: 'Test 8 fails at this many points in a row with none in zone C, on both sides of the center line: a mixture of two processes. 8 by default.' },
      ],
      validate: (x) => (x.t5m > x.t5n || x.t6m > x.t6n ? 'm must not be larger than n' : null),
    });
    if (v) ctx.set('testN', { 2: v.t2, 3: v.t3, 4: v.t4, 5: [v.t5m, v.t5n], 6: [v.t6m, v.t6n], 7: v.t7, 8: v.t8 });
  }

  SM.platforms.register({
    id: 'controlchart', label: 'Control Chart', menu: 'Analyze/Quality and Process', order: 10, info: 'p:controlchart',
    about: 'Shewhart control charts for variables (XBar & R, XBar & S, Individual & Moving Range, Levey Jennings, Run) and attributes (P, NP, C, U), EWMA and tabular CUSUM charts, with phases, the Western Electric / Nelson tests and JMP\'s Alarm Report (the samples out of control and the alarm rate of each chart), limit summaries, a capability analysis from the spec limits, and saved limits.',
    uses: ['numpy, scipy (the constants d2, d3, c4 by quadrature)', 'statsmodels.sandbox.stats.runs.runstest_1samp', 'scipy.stats.norm'],
    topics: {
      'p:controlchart': {
        kicker: 'Analyze > Quality and Process', title: 'Control Chart',
        lead: 'A control chart plots a statistic of each subgroup in time order with its center line and control limits, k sigma (3 unless set) either side. Points outside the limits, or patterns inside them, say the process has changed.',
        sections: [
          { heading: 'Roles', choices: [['Y, Process', 'The measurements (or counts, for attribute charts). One chart per column.'], ['Subgroup', 'The subgroup (sample) each row belongs to; without it every row is a point, or consecutive rows form subgroups of a given size.'], ['Phase', 'Separate limits for each phase (before and after a change).'], ['n Trials', 'P, NP and U charts: the number inspected; without it every row is one unit.'], ['By', 'A report for each level.']] },
          { heading: 'Charts', choices: [['XBar & R, XBar & S', 'Means of subgroups; sigma from the ranges (R̄/d₂) or standard deviations (S̄/c₄).'], ['Individual & Moving Range', 'Single values; sigma = average moving range/1.128. Levey Jennings uses the overall standard deviation.'], ['P, NP, C, U', 'Proportion or number defective (binomial), defects or defects per unit (Poisson).'], ['EWMA, CUSUM', 'Small sustained shifts: an exponentially weighted mean, or cumulative sums with a decision interval h and reference k.']] },
          { heading: 'Tests', text: 'Tests 1–8 of Western Electric and Nelson: beyond the limits, runs on one side, trends, oscillation, and points in the zones A, B and C (thirds of the distance to the limits). A failing point is red with its test number; the Tests outline lists them.' },
          { heading: 'Show Alarm Report', text: 'JMP\'s Alarm Report, from the red triangle: for each chart, numbered from the top, the samples out of control (failing a chosen test) and the alarm rate, their share of the chart\'s samples; the tests each chart runs; and the samples out of control with the tests they fail.' },
        ],
        more: { label: 'Control Chart', id: 'help-p-controlchart' },
      },
      'cc:alarm': {
        kicker: 'Control Chart', title: 'Alarm Report',
        lead: 'Which samples are out of control, chart by chart. A sample is out of control when it fails at least one of the tests its chart runs; the Alarm Rate (JMP\'s Proportion Out of Control) is the number of such samples over the chart\'s samples with a value. The charts are numbered by their Position from the top of the report: a process\'s XBar chart and its R chart are two.',
        sections: [
          { heading: 'The tables', choices: [['Alarms', 'Each chart: its samples, those out of control, the alarm rate and how many fail each chosen test (beyond JMP\'s table).'], ['Enabled Tests', 'The tests each chart runs, with what they look for.'], ['Samples Out of Control', 'Each sample out of control, its value and the tests it fails; click a line to select its rows.']] },
          { heading: 'Differences from JMP', text: 'Excluded rows are not in the charts, so they are never counted; JMP counts excluded samples only with Test Excluded Subgroups and Show Excluded Region, which are not here. The Samples column, the counts by test and the list of samples are beyond JMP\'s report.' },
        ],
        more: { label: 'Control Chart', id: 'help-p-controlchart' },
      },
      'p:capability': {
        kicker: 'Analyze > Quality and Process', title: 'Process Capability',
        lead: 'How well a process fits its specification limits. Cp = (USL − LSL)/6σ compares the spread with the tolerance; Cpk = min(USL − μ, μ − LSL)/3σ also counts how far the mean is off center; Cpm adds the distance from the target.',
        sections: [
          { heading: 'Within and overall', text: 'The within sigma is the short-term variation: inside subgroups (ranges or standard deviations) or between neighbouring values (the moving range, in row order); it gives Cp and Cpk. The overall sigma is the sample standard deviation; it gives Pp and Ppk. Their ratio is the stability index.' },
          { heading: 'Nonconformance', text: 'The observed share outside the limits, and the share a normal distribution with each sigma expects (or a fitted lognormal, Weibull or gamma, with the percentile method).' },
          { heading: 'Graphs', text: 'The goal plot puts each column at its spec-normalised mean shift and standard deviation; inside the triangle Ppk is above the goal. Capability box plots show every column on the same spec-normalised scale.' },
        ],
        more: { label: 'Process Capability', id: 'help-p-capability' },
      },
    },
    launch: {
      lead: 'Choose the process columns and, for subgrouped data, the subgroup column. Without a subgroup the chart is of individual values.',
      roles: [
        { key: 'y', label: 'Y, Process', min: 1, numeric: true, hint: 'required numeric',
          help: 'The measurements to chart, one chart per column; for P and NP charts the number of defective units in each row, for C and U charts the number of defects.' },
        { key: 'subgroup', label: 'Subgroup', max: 1, hint: 'optional',
          help: 'The subgroup (sample) of each row, any modeling type: the rows with the same value make one point, in the order of its levels. Without it every row is a point, or consecutive rows form subgroups of the size given below. The individual charts keep a point per row, ordered and labelled by it.' },
        { key: 'phase', label: 'Phase', max: 1, hint: 'optional',
          help: 'A column of phases (before and after a change): each phase gets its own center line and limits, with a line where the phase changes.' },
        { key: 'ntrials', label: 'n Trials', max: 1, numeric: true, types: ['continuous'], hint: 'optional: P, NP, U',
          help: 'P, NP and U charts: how many units were inspected in each row (for U, the size of the area of opportunity), summed over a subgroup. Without it every row counts as one unit.' },
        { key: 'by', label: 'By', hint: 'optional',
          help: 'A separate report for each level of the By column (with several columns, each combination of their levels). Rows with a missing By value are left out.' },
      ],
      options: [
        { key: 'chart', label: 'Chart', type: 'select', value: 'auto', choices: CHARTS,
          help: 'Automatic: XBar & R with a Subgroup column or a subgroup size of 2 or more, else Individual & Moving Range. XBar & R and XBar & S plot the subgroup means with their ranges or standard deviations; Levey Jennings takes the overall standard deviation; a Run Chart has no limits. P and NP (proportion or number defective) need n Trials or a Subgroup column; C and U count defects. EWMA and CUSUM find small sustained shifts. The red triangle changes it later.' },
        { key: 'subgroupSize', label: 'Subgroup size (no Subgroup column)', type: 'number', value: null,
          help: 'Without a Subgroup column: consecutive rows form subgroups of this many, 2 or more; a new subgroup also starts where the phase changes. Empty: every row is a point. The individual charts ignore it.' },
      ],
      validate: (s, t) => {
        const ch = s.options.chart;
        if (['p', 'np', 'u'].includes(ch) && !(s.roles.ntrials || []).length && !(s.roles.subgroup || []).length) return 'P, NP and U charts need n Trials, or a Subgroup column whose rows are the units inspected';
        if (['xbar_r', 'xbar_s'].includes(ch) && !(s.roles.subgroup || []).length && !(s.options.subgroupSize >= 2)) return 'XBar charts need a Subgroup column or a subgroup size of 2 or more';
        return null;
      },
    },
    title: () => 'Control Chart',
    triangle: controlTriangle,
    render: controlRender,
  });

  /* ==================================================================================
     Process Capability
     ================================================================================== */
  const DISTS = [['normal', 'Normal'], ['lognormal', 'Lognormal'], ['weibull', 'Weibull'], ['gamma', 'Gamma'], ['best', 'Best Fit']];
  const WITHIN = [[null, 'Automatic'], ['range', 'Average of Ranges'], ['std', 'Average of Unbiased Standard Deviations'], ['pooled', 'Pooled Unbiased Standard Deviation'], ['mr', 'Average of Moving Ranges'], ['mmr', 'Median of Moving Ranges']];

  function valuesOf(ctx, col) {
    const vals = [], rows = [];
    for (const r of ctx.rows) { const v = col.values[r]; if (typeof v === 'number' && Number.isFinite(v)) { vals.push(v); rows.push(r); } }
    return { vals, rows };
  }

  function normPdf(x, m, s) { const z = (x - m) / s; return Math.exp(-0.5 * z * z) / (s * Math.sqrt(2 * Math.PI)); }

  function capHistogram(ctx, col, cap, o) {
    const c = colors();
    const { vals, rows } = valuesOf(ctx, col);
    const bins = SM.report.niceBins(vals);
    const nb = Math.max(1, Math.round((bins.end - bins.start) / bins.size));
    const counts = new Array(nb).fill(0), members = Array.from({ length: nb }, () => []);
    vals.forEach((v, k) => { const j = Math.min(nb - 1, Math.max(0, Math.floor((v - bins.start) / bins.size + 1e-9))); counts[j]++; members[j].push(rows[k]); });
    const centers = counts.map((_, j) => bins.start + (j + 0.5) * bins.size);
    const traces = [{ type: 'bar', x: centers, y: counts, width: bins.size, rows: members, marker: { color: SM.report.BAR, line: { color: c.surface, width: 0.8 } }, hovertemplate: '%{x}: %{y}<extra></extra>', name: 'Histogram' }];
    const lims = [cap.lsl, cap.usl, cap.target].filter((v) => v != null);
    const lo = Math.min(bins.start, ...lims), hi = Math.max(bins.end, ...lims);
    const pad = 0.04 * (hi - lo || 1);
    const grid = Array.from({ length: 160 }, (_, i) => lo - pad + (i / 159) * (hi - lo + 2 * pad));
    const scale = vals.length * bins.size;
    if (cap.dist === 'normal' || !cap.dist) {
      if (o.overall && cap.sd_overall > 0) traces.push({ type: 'scatter', mode: 'lines', x: grid, y: grid.map((x) => scale * normPdf(x, cap.mean, cap.sd_overall)), line: { color: c.overall, width: 2 }, hoverinfo: 'skip', name: 'Overall' });
      if (o.within && cap.sd_within > 0) traces.push({ type: 'scatter', mode: 'lines', x: grid, y: grid.map((x) => scale * normPdf(x, cap.mean, cap.sd_within)), line: { color: c.within, width: 2, dash: 'dash' }, hoverinfo: 'skip', name: 'Within' });
    } else if (cap.curve) {
      traces.push({ type: 'scatter', mode: 'lines', x: cap.curve.x, y: cap.curve.pdf.map((d) => scale * d), line: { color: c.overall, width: 2 }, hoverinfo: 'skip', name: cap.fit.label });
    }
    const shapes = [], annotations = [];
    for (const [key, label, dash, colr] of [['lsl', 'LSL', 'solid', c.spec], ['target', 'Target', 'dot', c.target], ['usl', 'USL', 'solid', c.spec]]) {
      if (cap[key] == null) continue;
      shapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: cap[key], x1: cap[key], y0: 0, y1: 1, line: { color: colr, width: 1.6, dash } });
      annotations.push({ xref: 'x', x: cap[key], yref: 'paper', y: 1, yanchor: 'bottom', text: label, showarrow: false, font: { size: 10, color: colr } });
    }
    return ctx.plot(traces, { xaxis: { title: { text: esc(col.name) }, range: [lo - pad, hi + pad] }, yaxis: { title: { text: 'Count' }, rangemode: 'tozero' }, shapes, annotations, margin: { l: 50, r: 12, t: 20, b: 40 }, bargap: 0, showlegend: traces.length > 2, legend: { orientation: 'h', y: -0.25 } },
      { width: fitWidth(ctx, 420), height: 290, title: `${col.name} capability histogram` });
  }

  function goalPlot(ctx, cols, res, code) {
    const c = colors();
    const within = ctx.opt('goalWithin', false);
    const K = ctx.opt('goalPpk', 1);
    const pts = [];
    res.columns.forEach((r, i) => { if (r.goal && !r.error) pts.push({ col: cols[i], x: r.goal.x, y: within ? r.goal.y_within : r.goal.y_overall }); });
    if (!pts.length) return null;
    const ymax = Math.max(1 / (6 * K) * 1.4, ...pts.map((p) => (p.y || 0) * 1.15));
    const xmax = Math.max(0.55, ...pts.map((p) => Math.abs(p.x) * 1.15));
    const sel = selectedColumnIds(ctx.table);
    const traces = [
      { type: 'scatter', mode: 'lines', x: [-0.5, 0, 0.5], y: [0, 1 / (6 * K), 0], line: { color: c.limit, width: 1.4 }, fill: 'toself', fillcolor: 'rgba(46,125,50,0.07)', hoverinfo: 'skip', name: `Ppk = ${fmt(K)}` },
      { type: 'scatter', mode: 'markers+text', x: pts.map((p) => p.x), y: pts.map((p) => p.y), text: pts.map((p) => esc(p.col.name)), textposition: 'top right', textfont: { size: 10, color: c.text },
        marker: { size: pts.map((p) => (sel.has(p.col.id) ? 12 : 8)), color: pts.map((p) => (sel.has(p.col.id) ? SM.report.SELECTED : c.point)), line: { color: c.surface, width: 1 } },
        hovertext: pts.map((p) => `${esc(p.col.name)}<br>mean shift ${fmt(p.x, { sig: 4 })}, std dev ${fmt(p.y, { sig: 4 })}`), hovertemplate: '%{hovertext}<extra></extra>', name: 'Columns' },
    ];
    const box = ctx.plot(traces, {
      xaxis: { title: { text: 'Spec-Normalized Mean Shift' }, range: [-xmax, xmax], zeroline: true },
      yaxis: { title: { text: `Spec-Normalized ${within ? 'Within' : 'Overall'} Std Dev` }, range: [0, ymax], zeroline: false },
      margin: { l: 58, r: 16, t: 10, b: 44 }, dragmode: 'zoom',
    }, { width: fitWidth(ctx, 400), height: 320, title: 'Goal plot', select: false, onDraw: (gd) => {
      gd.on('plotly_click', (ev) => { const p = ev && ev.points && ev.points.find((q) => q.curveNumber === 1); if (p) selectColumns(ctx.table, [pts[p.pointNumber].col.id], ev.event && (ev.event.shiftKey || ev.event.metaKey || ev.event.ctrlKey)); });
      const off = SM.app.on('columnselection', () => {
        if (!gd.isConnected) { off(); return; }
        const s = selectedColumnIds(ctx.table);
        try { Plotly.restyle(gd, { 'marker.size': [pts.map((p) => (s.has(p.col.id) ? 12 : 8))], 'marker.color': [pts.map((p) => (s.has(p.col.id) ? SM.report.SELECTED : c.point))] }, [1]); } catch (e) { off(); }
      });
    } });
    const slider = el('input', { type: 'range', min: '0.5', max: '2.5', step: '0.05', 'aria-label': 'Ppk of the goal triangle' });
    slider.value = String(K);
    const out = el('output', { text: `Ppk ${fmt(K)}` });
    slider.addEventListener('input', () => { out.textContent = `Ppk ${fmt(Number(slider.value))}`; });
    slider.addEventListener('change', () => ctx.set('goalPpk', Number(slider.value)));
    return el('div', null, box, code, el('label', { class: 'sm-slider' }, 'Goal', slider, out));
  }

  function capBoxPlots(ctx, cols, res) {
    const c = colors();
    const traces = [], all = [];
    let boxes = 0;
    res.columns.forEach((r, i) => {
      if (r.error || r.lsl == null || r.usl == null) return;
      const t = r.target != null ? r.target : (r.lsl + r.usl) / 2;
      const w = r.usl - r.lsl;
      const { vals, rows } = valuesOf(ctx, cols[i]);
      const y = vals.map((v) => (v - t) / w);
      const b = boxStats(y);
      const name = esc(cols[i].name);
      boxes++;
      all.push(...y);
      // the box as JMP draws it, and the values beyond the whiskers as points (linked to their rows)
      traces.push({ type: 'box', x: [name], q1: [b.q1], median: [b.med], q3: [b.q3], lowerfence: [b.lf], upperfence: [b.uf], name, boxpoints: false,
        line: { color: c.text, width: 1 }, fillcolor: 'rgba(143,169,194,0.28)', hoverinfo: 'y' });
      const ox = [], oy = [], orows = [];
      y.forEach((v, k) => { if (v < b.lf || v > b.uf) { ox.push(name); oy.push(v); orows.push(rows[k]); } });
      if (oy.length) traces.push({ type: 'scatter', mode: 'markers', x: ox, y: oy, rows: orows, name: `${name} outliers`, marker: { color: c.point, size: 5 } });
    });
    if (!boxes) return null;
    // the limits of the first column with both (the same for every column whose target is the middle)
    const first = res.columns.find((r) => !r.error && r.lsl != null && r.usl != null);
    const tt = first.target != null ? first.target : (first.lsl + first.usl) / 2;
    const lo = (first.lsl - tt) / (first.usl - first.lsl), hi = (first.usl - tt) / (first.usl - first.lsl);
    const shapes = [lo, hi].map((y) => ({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: y, y1: y, line: { color: c.spec, width: 1.3 } }));
    shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: 0, y1: 0, line: { color: c.target, width: 1, dash: 'dot' } });
    const annotations = [[lo, 'LSL'], [hi, 'USL']].map(([y, t]) => ({ xref: 'paper', x: 1, xanchor: 'left', yref: 'y', y, text: t, showarrow: false, font: { size: 10, color: c.spec } }));
    all.push(lo, hi);
    return ctx.plot(traces, { yaxis: { title: { text: '(X − Target)/(USL − LSL)' }, zeroline: false, range: span(all, 0.08) }, xaxis: { type: 'category' }, shapes, annotations, margin: { l: 58, r: 36, t: 10, b: 60 } },
      { width: fitWidth(ctx, Math.max(300, Math.min(760, 140 + 70 * boxes))), height: 300, title: 'Capability box plots' });
  }

  async function capabilityRender(ctx) {
    const cols = ctx.roles('y');
    const specs = {}, dist = {}, historical = {};
    for (const c of cols) {
      const s = specOf(ctx, c);
      if (s) specs[c.name] = s;
      dist[c.name] = ctx.opt('dist', 'normal', c.id);
      const h = ctx.opt('historical', null, c.id);
      if (h) historical[c.name] = h;
    }
    // the graphs' code: each histogram's bins and curves as the page draws them, the goal's Ppk and sigma
    const bins = {}, curves = {};
    for (const c of cols) {
      const { vals } = valuesOf(ctx, c);
      if (vals.length) { const b = SM.report.niceBins(vals); bins[c.name] = { start: b.start, size: b.size, end: b.end, nb: Math.max(1, Math.round((b.end - b.start) / b.size)) }; }
      curves[c.name] = { within: ctx.opt('curveWithin', true, c.id), overall: ctx.opt('curveOverall', true, c.id) };
    }
    const plot = { bins, curves, room: roomOf(ctx), goal: { ppk: ctx.opt('goalPpk', 1), within: ctx.opt('goalWithin', false) } };
    const res = await ctx.call('quality.capability', { columns: cols.map((c) => c.name), specs, subgroup: ctx.name('subgroup'), within: ctx.opt('within', null), dist, historical, alpha: ctx.alpha, where: where(ctx), plot });
    const pc = res.plot_code || {};
    const ppm = ctx.opt('ppm', false);
    const missing = cols.filter((c) => !specs[c.name]);
    if (missing.length) ctx.container.append(ctx.warn(`No spec limits for ${missing.map((c) => c.name).join(', ')}: set them with Spec Limits… in the red triangle, or as the column's Spec Limits property.`));
    const graphs = [];
    if (ctx.opt('goal', true)) {
      const g = goalPlot(ctx, cols, res, ctx.code(pc.goal));
      if (g) { const ob = ctx.outline('Goal Plot', { key: 'goal', info: 'cap:goal', menu: () => [ctx.check('Within Sigma (Cpk) instead of Overall', 'goalWithin', null, false), { label: 'Goal Ppk…', action: async () => { const v = await SM.ui.form({ title: 'Goal Plot', fields: [{ key: 'k', label: 'Ppk of the triangle', type: 'number', value: ctx.opt('goalPpk', 1),
        help: 'The Ppk the triangle stands for: a column inside it has a larger Ppk (with the target at the middle of the limits). 1 by default; the Goal slider under the plot sets it too, from 0.5 to 2.5. Positive.' }] }); if (v && v.k > 0) ctx.set('goalPpk', v.k); } }] }); ob.add(g, ctx.note('Each column at (mean − target)/(USL − LSL) and standard deviation/(USL − LSL); inside the triangle its Ppk is above the goal (with the target at the middle of the limits). Click a point to select the column.')); graphs.push(ob.el); }
    }
    if (ctx.opt('boxplots', true)) {
      const b = capBoxPlots(ctx, cols, res);
      if (b) { const ob = ctx.outline('Capability Box Plots', { key: 'boxes' }); ob.add(b, ctx.code(pc.boxes), ctx.note('The values centred at the target and scaled by the tolerance: the limits are at ±½ when the target is the middle.')); graphs.push(ob.el); }
    }
    if (graphs.length) ctx.container.append(ctx.row(...graphs));
    if (ctx.opt('indexPlot', false)) {
      const c = colors();
      const ok = res.columns.map((r, i) => ({ r, col: cols[i] })).filter((x) => !x.r.error);
      const idx = (r, name) => { const a = (r.within || []).concat(r.overall || []).find((x) => x.index === name); return a ? a.estimate : null; };
      const ob = ctx.outline('Capability Index Plot', { key: 'indexplot' });
      ob.add(ctx.plot([
        { type: 'bar', x: ok.map((x) => esc(x.col.name)), y: ok.map((x) => idx(x.r, 'Ppk')), name: 'Ppk', marker: { color: c.overall } },
        { type: 'bar', x: ok.map((x) => esc(x.col.name)), y: ok.map((x) => idx(x.r, 'Cpk')), name: 'Cpk', marker: { color: c.within } },
      ], { barmode: 'group', showlegend: true, yaxis: { title: { text: 'Index' } }, shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 1, y1: 1, line: { color: c.limit, dash: 'dot' } }] }, { width: Math.max(320, 120 + 60 * ok.length), height: 260, title: 'Capability index plot', select: false }),
      ctx.code(pc.index));
    }
    if (ctx.opt('summary', true)) {
      const ob = ctx.outline('Capability Summary Report', { key: 'summary' });
      const idx = (r, name) => { const a = (r.within || []).concat(r.overall || []).find((x) => x.index === name); return a ? a.estimate : null; };
      const rows = res.columns.map((r, i) => (r.error ? { process: cols[i].name, note: r.error } : {
        process: cols[i].name, lsl: r.lsl, target: r.target, usl: r.usl, mean: r.mean, sd: r.sd_overall, sdw: r.sd_within, stab: r.stability,
        ppk: idx(r, 'Ppk'), cpk: idx(r, 'Cpk'), pp: idx(r, 'Pp'), cp: idx(r, 'Cp'),
        out: r.expected_overall ? (ppm ? 1e6 * r.expected_overall.total : 100 * r.expected_overall.total) : null, dist: r.dist && r.dist !== 'normal' ? r.fit.label : 'Normal',
      }));
      ob.add(ctx.rt({ columns: [
        { key: 'process', label: 'Process', fmt: 'text' }, { key: 'lsl', label: 'LSL' }, { key: 'target', label: 'Target' }, { key: 'usl', label: 'USL' },
        { key: 'mean', label: 'Sample Mean' }, { key: 'sd', label: 'Sample Std Dev' }, { key: 'sdw', label: 'Within Sigma', hidden: true }, { key: 'stab', label: 'Stability Index' },
        { key: 'ppk', label: 'Ppk' }, { key: 'cpk', label: 'Cpk' }, { key: 'pp', label: 'Pp' }, { key: 'cp', label: 'Cp' },
        { key: 'out', label: `Expected ${ppm ? 'PPM' : '%'} Outside (Overall)` }, { key: 'dist', label: 'Distribution', fmt: 'text', hidden: true },
      ], rows }, { key: 'capsummary' }), ctx.note('Right click the table for more columns (the within sigma, the distribution).'), ctx.code(res.code));
    }
    if (ctx.opt('detail', true)) {
      const det = ctx.outline('Individual Detail Reports', { key: 'detail' });
      res.columns.forEach((r, i) => {
        const col = cols[i];
        const o = (k, d) => ctx.opt(k, d, col.id);
        const ob = ctx.outline(`${col.name} Capability`, { parent: det, key: `col:${col.id}`, info: 'p:capability', menu: () => detailMenu(ctx, col) });
        if (r.error) { ob.add(ctx.warn(`${col.name}: ${r.error}`)); return; }
        const summ = ctx.kv([['Lower Spec Limit', r.lsl], ['Target', r.target], ['Upper Spec Limit', r.usl], ['Sample Mean', r.mean], ['Sample N', r.n, 'int'],
          r.dist === 'normal' ? ['Std Dev (Within)', r.sd_within] : null, ['Std Dev (Overall)', r.sd_overall], r.dist === 'normal' ? ['Stability Index', r.stability] : null,
          r.dist === 'normal' ? ['Within Sigma', r.within_method, 'text'] : ['Distribution', r.fit.label, 'text'],
          r.n_subgroups ? ['Subgroups', r.n_subgroups, 'int'] : null].filter((x) => x && x[1] != null), { caption: 'Process Summary' });
        ob.add(ctx.row(withCode(capHistogram(ctx, col, r, { within: o('curveWithin', true), overall: o('curveOverall', true) }), ctx.code((pc.hist || {})[col.name])), summ));
        if (r.dist !== 'normal' && r.fit) {
          ob.add(ctx.kv(Object.entries(r.fit.params).map(([k, v]) => [k, v]).concat([['−2 log(Likelihood)', -2 * r.fit.loglik], ['AICc', r.fit.aicc], ['P0.135', r.percentiles.p00135], ['P50', r.percentiles.p50], ['P99.865', r.percentiles.p99865]]), { caption: `Fitted ${r.fit.label}` }));
          if (r.fit.compared) ob.add(ctx.rt({ columns: [{ key: 'label', label: 'Distribution', fmt: 'text' }, { key: 'aicc', label: 'AICc' }], rows: r.fit.compared }, { caption: 'Compare Distributions', sortable: false, key: 'compare' }));
        }
        ob.add(ctx.row(...capabilityParts(ctx, r, ppm)), ctx.note(capabilityNote(r)));
      });
    }
  }

  function detailMenu(ctx, col) {
    const d = ctx.opt('dist', 'normal', col.id);
    return [
      { label: 'Distribution', submenu: () => DISTS.map(([k, l]) => ({ label: l, checked: d === k, action: () => ctx.set('dist', k, col.id) })) },
      { label: 'Spec Limits…', action: () => specDialog(ctx, [col]) },
      { label: 'Save Spec Limits as Column Property', action: () => { const s = specOf(ctx, col); if (!s) { SM.ui.toast('No spec limits to save'); return; } col.specLimits = { lsl: s.lsl ?? null, target: s.target ?? null, usl: s.usl ?? null }; ctx.table._changed('schema', { info: col.id }); SM.ui.toast(`Saved the spec limits of ${col.name} as its Spec Limits property`); } },
      { label: 'Historical Sigma…', action: async () => { const v = await SM.ui.form({ title: `Historical Sigma: ${col.name}`, fields: [{ key: 's', label: 'Within sigma (empty: estimated)', type: 'number', value: ctx.opt('historical', null, col.id),
        help: 'A known within (short-term) standard deviation of this column, used for Cp, Cpk and the expected within nonconformance instead of the estimate from the subgroups or moving ranges. Empty: estimated.' }] }); if (v) ctx.set('historical', v.s > 0 ? v.s : null, col.id); } },
      ctx.check('Within Sigma Density', 'curveWithin', col.id, true),
      ctx.check('Overall Sigma Density', 'curveOverall', col.id, true),
      { separator: true },
      { label: 'Remove', action: () => { const ids = (ctx.spec.roles.y || []).filter((id) => id !== col.id); if (!ids.length) ctx.report.app.closeReport(ctx.report); else { ctx.spec.roles.y = ids; ctx.report.run(); } } },
    ];
  }

  function capabilityTriangle(ctx) {
    return [
      ctx.check('Goal Plot', 'goal', null, true),
      ctx.check('Capability Box Plots', 'boxplots', null, true),
      ctx.check('Capability Index Plot', 'indexPlot', null, false),
      ctx.check('Summary Report', 'summary', null, true),
      ctx.check('Individual Detail Reports', 'detail', null, true),
      { separator: true },
      { label: 'Within Sigma', submenu: () => WITHIN.map(([k, l]) => ({ label: l, checked: ctx.opt('within', null) === k, action: () => ctx.set('within', k) })) },
      { label: 'Distribution for All', submenu: () => DISTS.map(([k, l]) => ({ label: l, action: () => { for (const c of ctx.roles('y')) ctx.set('dist', k, c.id, { rerun: false }); ctx.report.run(); } })) },
      { label: 'Spec Limits…', action: () => specDialog(ctx, ctx.roles('y')) },
      ctx.check('Show PPM', 'ppm', null, false),
    ];
  }

  /* The launch's own part: the spec limits of the Y columns. */
  function specExtra(api, spec) {
    let specs = JSON.parse(JSON.stringify((spec && spec.options && spec.options.specs) || {}));
    const list = el('div', { class: 'sm-q-speclist' });
    const btn = el('button', { type: 'button', class: 'sm-btn', text: 'Spec Limits…' });
    const cols = () => (api.state.y || []).map((id) => api.table.col(id)).filter(Boolean);
    const show = () => {
      const cs = cols();
      list.replaceChildren(...(cs.length ? cs.map((c) => { const s = specs[c.name] || c.specLimits; return el('div', { text: `${c.name}: ${s && (s.lsl != null || s.usl != null) ? `LSL ${s.lsl ?? '·'}, Target ${s.target ?? '·'}, USL ${s.usl ?? '·'}` : 'no spec limits'}` }); }) : [el('div', { class: 'sm-ob-note', text: 'Cast the process columns into Y first.' })]));
    };
    btn.addEventListener('click', async () => {
      const cs = cols();
      if (!cs.length) { api.message('Cast the process columns into Y, Process first.'); return; }
      const v = await SM.ui.form({
        title: 'Spec Limits', lead: 'The columns\' Spec Limits property gives the defaults. Leave a limit empty when there is none.',
        fields: cs.flatMap((c) => { const s = specs[c.name] || c.specLimits || {}; return [{ key: `${c.id}|lsl`, label: `${c.name}: LSL`, type: 'number', value: s.lsl ?? null, help: SPEC_HELP.lsl, helpLabel: 'LSL' }, { key: `${c.id}|target`, label: `${c.name}: Target`, type: 'number', value: s.target ?? null, help: SPEC_HELP.target, helpLabel: 'Target' }, { key: `${c.id}|usl`, label: `${c.name}: USL`, type: 'number', value: s.usl ?? null, help: SPEC_HELP.usl, helpLabel: 'USL' }]; }),
      });
      if (!v) return;
      for (const c of cs) specs[c.name] = { lsl: v[`${c.id}|lsl`], target: v[`${c.id}|target`], usl: v[`${c.id}|usl`] };
      show();
    });
    const box = el('div', { class: 'sm-q-launch' }, el('h4', { text: 'Spec Limits' }), btn, list);
    requestAnimationFrame(() => {
      show();
      const roles = box.closest('.sm-dialog')?.querySelector('.sm-roles');
      if (roles && typeof MutationObserver !== 'undefined') new MutationObserver(show).observe(roles, { childList: true, subtree: true });
    });
    return {
      el: box,
      read: () => {
        const out = {};
        for (const c of cols()) { const s = specs[c.name]; if (s) out[c.name] = s; }
        return { options: { specs: out } };
      },
      recall: (s) => { specs = JSON.parse(JSON.stringify((s && s.options && s.options.specs) || {})); show(); },
      helpHeading: 'Spec Limits',
      help: [['Spec Limits…', 'A form with the lower spec limit, the target and the upper spec limit of each Y, Process column; the list under the button shows them. A column\'s Spec Limits property (Cols > Column Info) gives the defaults, and a limit left empty means none. At least one column needs a limit; the report\'s red triangle changes them later.']],
    };
  }

  SM.platforms.register({
    id: 'capability', label: 'Process Capability', menu: 'Analyze/Quality and Process', order: 20, info: 'p:capability',
    about: 'Capability of one or more process columns against their spec limits: within and overall indices (Cp, Cpk, Cpl, Cpu, Pp, Ppk, Ppl, Ppu, Cpm) with confidence intervals, nonconformance observed and expected, histograms with the normal curves, the goal plot and capability box plots; lognormal, Weibull or gamma fits with the percentile method.',
    uses: ['scipy.stats (norm, chi2, nct, lognorm, weibull_min, gamma)', 'numpy'],
    topics: {
      'cap:goal': {
        kicker: 'Process Capability', title: 'Goal Plot',
        lead: 'Each column with both spec limits as a point: across, its mean shift (mean − target)/(USL − LSL); up, its standard deviation over USL − LSL, overall or within. Inside the triangle a column\'s Ppk is above the goal, for a target at the middle of the limits.',
        sections: [{ heading: 'In the report', choices: [
          ['Goal', 'The slider sets the Ppk of the triangle, from 0.5 to 2.5 (1 by default); the plot follows when you let go. Goal Ppk… in the red triangle takes any value.'],
          ['A point', 'Click it to select that column in the table (with shift, ⌘ or ctrl, add it); selected columns are drawn larger.']] }],
        more: { label: 'Process Capability', id: 'help-p-capability' },
      },
    },
    launch: {
      lead: 'Choose the process columns and give their spec limits (the Spec Limits column property is the default). With a subgroup column the within sigma comes from the subgroups, else from the moving range in row order.',
      roles: [
        { key: 'y', label: 'Y, Process', min: 1, numeric: true, types: ['continuous'], hint: 'required continuous',
          help: 'The process columns, each against its own spec limits (below). A column\'s missing values are left out of its own analysis only.' },
        { key: 'subgroup', label: 'Subgroup', max: 1, hint: 'optional',
          help: 'The subgroup of each row: the within sigma then comes from the variation inside the subgroups (the average range unless Within Sigma says otherwise). Without it, from the moving ranges of neighbouring rows, in row order.' },
        { key: 'by', label: 'By', hint: 'optional',
          help: 'A separate report for each level of the By column (with several columns, each combination of their levels). Rows with a missing By value are left out.' },
      ],
      extra: specExtra,
      validate: (s, t) => {
        const specs = s.options.specs || {};
        const cols = (s.roles.y || []).map((id) => t.col(id)).filter(Boolean);
        const none = cols.filter((c) => { const x = specs[c.name] || c.specLimits; return !(x && (x.lsl != null || x.usl != null)); });
        if (none.length === cols.length) return 'Give spec limits (Spec Limits…) for at least one process column';
        for (const c of cols) { const x = specs[c.name]; if (x && x.lsl != null && x.usl != null && !(x.lsl < x.usl)) return `${c.name}: the lower spec limit must be below the upper`; }
        return null;
      },
    },
    title: () => 'Process Capability',
    triangle: capabilityTriangle,
    render: capabilityRender,
  });

  /* ==================================================================================
     Pareto Plot
     ================================================================================== */
  function paretoChart(ctx, causes, counts, rows, total, o, title, small) {
    const c = colors();
    const pctScale = o.percent;
    const names = causes.map((x) => esc(x.cause));
    const heights = counts.map((n) => (pctScale ? 100 * n / total : n));
    const traces = [];
    if (o.legend) {
      causes.forEach((x, i) => traces.push({ type: 'bar', x: [names[i]], y: [heights[i]], rows: [rows[i]], rowsScale: pctScale ? 100 / total : 1, name: names[i], marker: { color: SM.util.PALETTE[i % SM.util.PALETTE.length] }, hovertemplate: `${names[i]}: %{y}<extra></extra>` }));
    } else {
      traces.push({ type: 'bar', x: names, y: heights, rows, rowsScale: pctScale ? 100 / total : 1, marker: { color: SM.report.BAR }, hovertemplate: '%{x}: %{y}<extra></extra>', name: 'Count' });
    }
    let cum = 0;
    const cumY = counts.map((n) => { cum += n; return 100 * cum / total; });
    if (o.cumCurve) {
      traces.push({ type: 'scatter', mode: o.cumPoints ? 'lines+markers' : 'lines', x: names, y: cumY, yaxis: o.cumAxis ? 'y2' : 'y', line: { color: c.limit, width: 1.6 }, marker: { size: 6, color: c.limit },
        text: o.cumLabels ? cumY.map((v) => `${v.toFixed(1)}%`) : undefined, textposition: 'top left', textfont: { size: 9.5, color: c.limit }, hovertemplate: 'cum %{y:.1f}%<extra></extra>', name: 'Cum Percent' });
      if (o.cumLabels) traces[traces.length - 1].mode += '+text';
    }
    const ymax = pctScale ? 100 : Math.max(...heights, 1);
    const angled = names.length > (small ? 3 : 6);
    const layout = {
      xaxis: { type: 'category', categoryorder: 'array', categoryarray: names, tickangle: names.length > (small ? 3 : 6) ? -35 : 0 },
      yaxis: { title: { text: pctScale ? 'Percent' : 'Count' }, range: [0, ymax * 1.05], rangemode: 'tozero' },
      bargap: 0.18, margin: { l: 54, r: o.cumCurve && o.cumAxis ? 50 : 14, t: title ? 26 : 10, b: angled ? 80 : 46 }, showlegend: false,
    };
    if (o.cumCurve && o.cumAxis) layout.yaxis2 = { overlaying: 'y', side: 'right', range: [0, 105], title: { text: 'Cum Percent' }, ticksuffix: '%', showgrid: false };
    if (o.cumCurve && !o.cumAxis && !pctScale) traces[traces.length - 1].y = cumY.map((v) => v / 100 * ymax);
    if (title) layout.title = { text: esc(title), font: { size: 11.5 }, x: 0.02 };
    if (o.nLegend) layout.annotations = [{ xref: 'paper', yref: 'paper', x: 1, y: 1, xanchor: 'right', yanchor: 'top', text: `N = ${fmt(total)}`, showarrow: false, font: { size: 10.5, color: c.muted } }];
    const w = fitWidth(ctx, small ? Math.max(260, Math.min(420, 90 + 34 * names.length)) : Math.max(380, Math.min(760, 140 + 52 * names.length)), 240);
    // Axis Settings (smui-axis.js): in the code the bars are ax, the Cum Percent axis the twin that pareto() makes on it
    const axisCode = (name) => (name === 'xaxis' || name === 'yaxis' ? 'ax' : name === 'yaxis2' && o.cumCurve && o.cumAxis ? 'plt.gcf().axes[1]' : null);
    return ctx.plot(traces, layout, { width: w, height: small ? 260 : 330, title: title ? `Pareto plot ${title}` : 'Pareto plot', select: false, axisCode });
  }

  async function paretoRender(ctx) {
    const cause = ctx.role('y');
    const combine = ctx.opt('combine', null);
    const groups = ctx.names('x');
    const o = {
      percent: ctx.opt('percent', false), legend: ctx.opt('legend', false), nLegend: ctx.opt('nLegend', false), cumCurve: ctx.opt('cumCurve', true),
      cumAxis: ctx.opt('cumAxis', true), cumPoints: ctx.opt('cumPoints', true), cumLabels: ctx.opt('cumLabels', false),
    };
    const res = await ctx.call('quality.pareto', { cause: cause.name, freq: ctx.name('freq'), groups, combine, where: where(ctx), plot: { ...o, ungroup: ctx.opt('ungroup', false), room: roomOf(ctx) } });
    if (res.error) { ctx.container.append(ctx.warn(res.error)); return; }
    const pc = res.plot_code || {};
    const causes = res.causes;
    if (o.legend) {
      // the Category Legend, once for every chart
      ctx.container.append(el('div', { class: 'sm-q-legend', role: 'list', 'aria-label': 'Causes' }, ...causes.map((x, i) => el('span', { class: 'sm-q-legend-item', role: 'listitem' },
        el('span', { class: 'sm-q-swatch', style: { background: SM.util.PALETTE[i % SM.util.PALETTE.length] } }), x.cause))));
    }
    if (!res.groups || ctx.opt('ungroup', false) === 'overall') {
      ctx.container.append(...[paretoChart(ctx, causes, causes.map((x) => x.count), causes.map((x) => x.rows), res.total, o, null, false), ctx.code(pc.overall)].filter(Boolean));
    } else {
      const wrap = el('div', { class: 'sm-q-cells' });
      res.groups.forEach((g, i) => wrap.append(withCode(paretoChart(ctx, causes, g.counts, g.rows, g.total || 1, o, `${groups.join(', ')} = ${g.label} (N ${fmt(g.total)})`, true), ctx.code((pc.cells || [])[i]))));
      ctx.container.append(wrap);
    }
    if (causes.some((x) => x.combined)) {
      const other = causes.find((x) => x.combined);
      ctx.container.append(ctx.note(`Other combines ${other.combined.join(', ')}.`));
    }
    if (ctx.opt('table', true)) {
      const ob = ctx.outline('Frequencies', { key: 'freq' });
      ob.add(ctx.rt(res.table, { onRow: (r, ev) => { const cc = causes.find((x) => x.cause === r.cause); if (cc) ctx.table.select(cc.rows, ev && ev.shiftKey ? 'add' : 'replace'); }, key: 'pareto' }),
        ctx.kv([['Total', res.total], ['Rows', res.n_rows, 'int']]), ctx.note('Click a line or a bar to select the rows of that cause.'), ctx.code(res.code));
    }
    if (res.test && ctx.opt('testRates', false)) {
      const t = res.test;
      const ob = ctx.outline('Test Rates Across Groups', { key: 'rates' });
      ob.add(ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'chi', label: 'ChiSquare' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }],
        rows: [{ test: 'Likelihood Ratio', chi: t.lr, df: t.df, p: t.p_lr }, { test: 'Pearson', chi: t.pearson, df: t.df, p: t.p_pearson }] }, { sortable: false, key: 'rates' }),
      ctx.note('Are the causes\' rates the same in every group? The likelihood ratio is the deviance of a Poisson log-linear model of the counts on cause and group (statsmodels GLM), against the model with their interaction.'));
      if (t.min_expected < 5) ob.add(ctx.warn(`The smallest expected count is ${fmt(t.min_expected)}: with counts below 5 the χ² p-values are approximate.`));
    }
  }

  function paretoTriangle(ctx) {
    const hasGroups = ctx.roles('x').length > 0;
    return [
      ctx.check('Percent Scale', 'percent', null, false),
      ctx.check('N Legend', 'nLegend', null, false),
      ctx.check('Category Legend', 'legend', null, false),
      ctx.check('Show Cum Percent Curve', 'cumCurve', null, true),
      ctx.check('Show Cum Percent Axis', 'cumAxis', null, true),
      ctx.check('Show Cum Percent Points', 'cumPoints', null, true),
      ctx.check('Label Cum Percent Points', 'cumLabels', null, false),
      ctx.check('Frequency Table', 'table', null, true),
      { separator: true },
      { label: 'Causes', submenu: () => [
        { label: 'Combine Causes…', action: async () => { const cur = ctx.opt('combine', null) || {}; const v = await SM.ui.form({ title: 'Combine Causes', lead: 'Combine the smallest causes into Other: those below a share of the total, or all but the largest few.', fields: [{ key: 'below', label: 'Combine causes below this percent', type: 'number', value: cur.below ?? 5,
          help: 'The causes whose share of the total count is below this percent become one bar, Other (when at least two are that small). 5 by default.' },
        { key: 'top', label: 'or keep only the largest (number of causes)', type: 'number', value: cur.top ?? null,
          help: 'Keep this many of the largest causes and combine the rest into Other; when given, it is used instead of the percent.' }] }); if (v) ctx.set('combine', v.top ? { top: v.top } : v.below != null ? { below: v.below } : null); } },
        { label: 'Separate Causes', disabled: !ctx.opt('combine', null), action: () => ctx.set('combine', null) },
      ] },
      hasGroups ? { label: 'Count Analysis', submenu: () => [ctx.check('Test Rates Across Groups', 'testRates', null, false)] } : null,
      hasGroups ? { label: 'Ungroup Plots', checked: ctx.opt('ungroup', false) === 'overall', action: () => ctx.set('ungroup', ctx.opt('ungroup', false) === 'overall' ? false : 'overall') } : null,
    ].filter(Boolean);
  }

  SM.platforms.register({
    id: 'pareto', label: 'Pareto Plot', menu: 'Analyze/Quality and Process', order: 60, info: 'p:pareto',
    about: 'Bars of the counts of each cause, largest first, with the cumulative percent curve on its own axis; frequencies, combined causes, a cell per level of up to two grouping columns, and a test that the causes\' rates are the same across the groups.',
    uses: ['pandas (counts)', 'statsmodels.genmod.GLM (Poisson log-linear test)', 'scipy.stats.chi2'],
    topics: {
      'p:pareto': {
        kicker: 'Analyze > Quality and Process', title: 'Pareto Plot',
        lead: 'The causes of problems ordered by how often they occur, with the cumulative percent: the few causes on the left usually account for most of the problems.',
        sections: [
          { heading: 'Roles', choices: [['Y, Cause', 'The cause (defect type) of each row, any modeling type.'], ['X, Grouping', 'One or two columns: a Pareto plot for each combination of their levels, the causes in the overall order.'], ['Freq', 'A count per row; without it each row counts once.'], ['By', 'A report for each level.']] },
          { heading: 'Options', text: 'Percent Scale shows percents instead of counts; Combine Causes puts the smallest causes into Other; Test Rates Across Groups compares the groups with a Poisson log-linear model. Click a bar to select its rows.' },
        ],
        more: { label: 'Pareto Plot', id: 'help-p-pareto' },
      },
    },
    launch: {
      lead: 'Choose the cause column; optionally a frequency column and one or two grouping columns.',
      roles: [
        { key: 'y', label: 'Y, Cause', min: 1, max: 1, hint: 'required',
          help: 'The cause (defect type, complaint) of each row, any modeling type: a bar per cause, largest first.' },
        { key: 'x', label: 'X, Grouping', max: 2, hint: 'optional, up to two',
          help: 'One or two columns: a Pareto plot for each of their levels (or combinations of levels), with the causes in the overall order, and Test Rates Across Groups in the red triangle.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'A count per row, such as the number of defects of that cause; without it every row counts once. Rows with a missing, zero or negative count are left out.' },
        { key: 'by', label: 'By', hint: 'optional',
          help: 'A separate report for each level of the By column (with several columns, each combination of their levels). Rows with a missing By value are left out.' },
      ],
    },
    title: () => 'Pareto Plot',
    triangle: paretoTriangle,
    render: paretoRender,
  });

  /* ==================================================================================
     Variability / Attribute Gauge Chart
     ================================================================================== */
  const MODELS = [['crossed', 'Crossed'], ['nested', 'Nested'], ['main', 'Main Effect'], ['crossed_nested', 'Crossed then Nested (3 factors)'], ['nested_crossed', 'Nested then Crossed (3 factors)']];

  function nestedAxis(res, c) {
    // positions 1..m; the innermost level as ticks, the outer levels written below
    const cells = res.cells;
    const m = cells.length;
    const k = res.factors.length;
    const ticks = tickAxis(cells.map((x) => x.levels[k - 1]), 60);
    const annotations = [], shapes = [];
    for (let d = k - 2; d >= 0; d--) {
      let start = 0;
      for (let i = 1; i <= m; i++) {
        const same = i < m && cells[i].levels.slice(0, d + 1).join('\u0001') === cells[start].levels.slice(0, d + 1).join('\u0001');
        if (same) continue;
        annotations.push({ xref: 'x', x: (start + i + 1) / 2, yref: 'paper', y: 0, yanchor: 'top', yshift: -30 - 16 * (k - 2 - d), text: esc(cells[start].levels[d]), showarrow: false, font: { size: 10.5, color: c.text } });
        if (i < m) shapes.push({ type: 'line', xref: 'x', x0: i + 0.5, x1: i + 0.5, yref: 'paper', y0: 0, y1: 1, line: { color: c.grid, width: d === 0 ? 1.4 : 0.8 } });
        start = i;
      }
    }
    if (!ticks.tickvals) { ticks.tickvals = cells.map((_, i) => i + 1); ticks.ticktext = cells.map((x) => esc(x.levels[k - 1])); ticks.tickmode = 'array'; }
    return { ticks, annotations, shapes, extra: 16 * Math.max(0, k - 1) };
  }

  function variabilityChart(ctx, y, res, o) {
    const c = colors();
    const cells = res.cells;
    const m = cells.length;
    const pos = cells.map((_, i) => i + 1);
    const ax = nestedAxis(res, c);
    const traces = [], groups = [];
    const showSd = o.sdChart;
    const r = SM.util.rng(`jitter:${y.name}`);
    if (o.points) {
      const X = [], Y = [], R = [];
      cells.forEach((cl, i) => cl.rows.forEach((row) => { const v = y.values[row]; if (Number.isFinite(v)) { X.push(pos[i] + (o.jitter ? (r.u() - 0.5) * 0.36 : 0)); Y.push(v); R.push(row); } }));
      traces.push({ type: 'scatter', mode: 'markers', x: X, y: Y, rows: R, marker: { size: 5.5, color: c.point }, name: y.name, xaxis: 'x', yaxis: 'y' });
    }
    if (o.boxes) {
      // each cell's box as JMP draws it: the (n + 1)p quartiles, the whiskers to the furthest values within 1.5 IQR
      const st = cells.map((cl) => boxStats(cl.rows.map((row) => y.values[row])));
      traces.push({ type: 'box', x: pos, q1: st.map((b) => b.q1), median: st.map((b) => b.med), q3: st.map((b) => b.q3), lowerfence: st.map((b) => b.lf), upperfence: st.map((b) => b.uf),
        boxpoints: false, line: { color: c.muted, width: 1 }, fillcolor: 'rgba(143,169,194,0.18)', hoverinfo: 'skip', width: 0.5, xaxis: 'x', yaxis: 'y' });
    }
    if (o.rangeBars) {
      const X = [], Y = [];
      cells.forEach((cl, i) => { if (cl.n > 1) { X.push(pos[i], pos[i], null); Y.push(cl.min, cl.max, null); } });
      traces.push({ type: 'scatter', mode: 'lines', x: X, y: Y, line: { color: c.muted, width: 1.4 }, hoverinfo: 'skip', xaxis: 'x', yaxis: 'y' });
    }
    if (o.cellMeans) {
      traces.push({ type: 'scatter', mode: o.connect ? 'lines+markers' : 'markers', x: pos, y: cells.map((x) => x.mean), marker: { symbol: 'line-ew', size: 14, line: { width: 2, color: c.overall } }, line: { color: c.overall, width: 1 },
        hovertext: cells.map((x) => `${x.levels.map(esc).join(' / ')}: mean ${fmt(x.mean)} (n ${x.n})`), hovertemplate: '%{hovertext}<extra></extra>', xaxis: 'x', yaxis: 'y' });
    }
    if (o.groupMeans) {
      const X = [], Y = [];
      for (const g of res.group_means) { X.push(g.first + 1 - 0.4, g.last + 1 + 0.4, null); Y.push(g.mean, g.mean, null); }
      traces.push({ type: 'scatter', mode: 'lines', x: X, y: Y, line: { color: c.mean, width: 1.6 }, hoverinfo: 'skip', xaxis: 'x', yaxis: 'y' });
    }
    const shapes = ax.shapes.slice();
    if (o.grandMean) shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: res.grand_mean, y1: res.grand_mean, line: { color: c.center, width: 1.2 } });
    if (o.grandMedian) shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: res.grand_median, y1: res.grand_median, line: { color: c.center, width: 1.2, dash: 'dash' } });
    const vals = cells.flatMap((x) => [x.min, x.max]);
    const layout = {
      xaxis: { range: [0.5, m + 0.5], ...ax.ticks, anchor: showSd ? 'y2' : 'y', title: { text: esc(res.factors.join(' / ')), standoff: 18 + ax.extra }, showgrid: false, zeroline: false, tickangle: m > 16 ? -45 : 0 },
      yaxis: { domain: showSd ? [0.42, 1] : [0, 1], title: { text: esc(y.name) }, range: span(vals, 0.06), zeroline: false },
      shapes, annotations: ax.annotations, margin: { l: 58, r: 14, t: 10, b: 58 + ax.extra }, showlegend: false,
    };
    if (showSd) {
      const sds = cells.map((x) => x.sd);
      const at = traces.length;
      traces.push({ type: 'scatter', mode: 'lines+markers', x: pos, y: sds, marker: { size: 6, color: c.point }, line: { color: c.line, width: 1 }, connectgaps: false,
        hovertext: cells.map((x) => `${x.levels.map(esc).join(' / ')}: std dev ${fmt(x.sd)}`), hovertemplate: '%{hovertext}<extra></extra>', xaxis: 'x', yaxis: 'y2' });
      groups.push({ trace: at, xs: pos, ys: sds, rows: cells.map((x) => x.rows) });
      const lines = [];
      if (o.meanSd && res.mean_sd != null) { traces.push({ type: 'scatter', mode: 'lines', x: [0.5, m + 0.5], y: [res.mean_sd, res.mean_sd], line: { color: c.center, width: 1.2 }, hoverinfo: 'skip', xaxis: 'x', yaxis: 'y2' }); lines.push(res.mean_sd); }
      if (o.sLimits && res.s_limits) {
        for (const key of ['ucl', 'lcl']) {
          const ysl = res.s_limits.map((s) => (s ? s[key] : null));
          traces.push({ type: 'scatter', mode: 'lines', ...stepLine(pos, ysl, new Set()), line: { color: c.limit, width: 1.2, shape: 'hv' }, hoverinfo: 'skip', xaxis: 'x', yaxis: 'y2' });
          lines.push(...ysl);
        }
      }
      layout.yaxis2 = { domain: [0, 0.32], anchor: 'x', title: { text: 'Std Dev' }, range: [0, span(sds.concat(lines), 0.12)[1]], zeroline: false };
    }
    const width = fitWidth(ctx, Math.max(460, Math.min(820, 140 + 22 * m)));
    return groupPlot(ctx, traces, layout, { width, height: showSd ? 470 : 330, title: `Variability chart for ${y.name}` }, groups);
  }

  async function variabilityRender(ctx) {
    const ys = ctx.roles('y');
    const kind = ctx.opt('kind', 'auto');
    for (const y of ys) {
      const attr = kind === 'attribute' || (kind === 'auto' && y.isCategorical);
      if (attr) await attributeRender(ctx, y);
      else await continuousVariability(ctx, y);
    }
  }

  async function continuousVariability(ctx, y) {
    const o = (k, d) => ctx.opt(k, d);
    const gauge = o('gauge', null);
    const vc = o('varcomp', false) || !!gauge;
    const xs = ctx.names('x');
    const part = ctx.name('part');
    const spec = y.specLimits || {};
    const show = {
      points: o('points', true), rangeBars: o('rangeBars', true), cellMeans: o('cellMeans', true), connect: o('connect', false), groupMeans: o('groupMeans', false),
      grandMean: o('grandMean', false), grandMedian: o('grandMedian', false), boxes: o('boxes', false), jitter: o('jitter', false),
      sdChart: o('sdChart', true), meanSd: o('meanSd', true), sLimits: o('sLimits', false),
    };
    const res = await ctx.call('quality.variability', {
      y: y.name, xs, part, model: o('model', null), method: o('method', 'best'), gauge: !!gauge, components: vc,
      k_mult: gauge ? gauge.k ?? 6 : 6, tolerance: gauge ? gauge.tolerance ?? null : null,
      lsl: gauge ? (gauge.lsl ?? spec.lsl ?? null) : null, usl: gauge ? (gauge.usl ?? spec.usl ?? null) : null, historical_sigma: gauge ? gauge.historical ?? null : null,
      where: where(ctx), plot: o('chart', true) ? { ...show, room: roomOf(ctx) } : null,
    });
    const outline = ctx.outline(`Variability Chart for ${y.name}`, { key: `y:${y.id}`, info: 'p:variability' });
    if (res.error) { outline.add(ctx.warn(res.error)); return; }
    if (o('chart', true)) outline.add(variabilityChart(ctx, y, res, show), ctx.code(res.plot_code));
    if (o('summaryReport', false)) {
      const ob = ctx.outline('Variability Summary Report', { parent: outline, key: `sum:${y.id}` });
      const cols = res.factors.map((f, j) => ({ key: `f${j}`, label: f, fmt: 'text' })).concat([{ key: 'n', label: 'N', fmt: 'int' }, { key: 'mean', label: 'Mean' }, { key: 'sd', label: 'Std Dev' }, { key: 'range', label: 'Range' }, { key: 'min', label: 'Min' }, { key: 'max', label: 'Max' }]);
      ob.add(ctx.rt({ columns: cols, rows: res.cells.map((cl) => ({ ...Object.fromEntries(cl.levels.map((l, j) => [`f${j}`, l])), n: cl.n, mean: cl.mean, sd: cl.sd, range: cl.range, min: cl.min, max: cl.max, _rows: cl.rows })) },
        { onRow: (r, ev) => ctx.table.select(r._rows, ev && ev.shiftKey ? 'add' : 'replace'), key: 'varsummary' }));
    }
    if (vc) {
      const ob = ctx.outline('Variance Components', { parent: outline, key: `vc:${y.id}`, menu: () => [
        { label: 'Model', submenu: () => MODELS.map(([k, l]) => ({ label: l, checked: (o('model', null) || (xs.length + (part && !xs.includes(part) ? 1 : 0) > 1 ? 'crossed' : 'main')) === k, action: () => ctx.set('model', k) })) },
        { label: 'Method', submenu: () => [['best', 'Choose Best (EMS if balanced, else REML)'], ['ems', 'EMS (ANOVA)'], ['reml', 'REML']].map(([k, l]) => ({ label: l, checked: o('method', 'best') === k, action: () => ctx.set('method', k) })) },
        { label: 'Remove', action: () => ctx.set('varcomp', false) },
      ] });
      if (res.components_error) ob.add(ctx.warn(res.components_error));
      else if (res.components) {
        const comp = res.components;
        ob.add(ctx.rt(comp.table, { sortable: false, key: 'varcomp' }));
        ob.add(ctx.note(comp.method === 'EMS'
          ? `ANOVA (expected mean squares) estimates for a balanced ${comp.model.replace('_', ' ')} random-effects model: sums of squares from statsmodels OLS and anova_lm, E[MS] solved from the largest terms down.`
          : `REML estimates from statsmodels MixedLM (one group, every term a variance component; ${comp.balanced ? 'balanced' : 'unbalanced'} data). The standard errors are the Wald ones from the likelihood.`));
        for (const n of res.notes || []) ob.add(ctx.note(n));
        if (comp.anova) {
          const an = ctx.outline('Analysis of Variance', { parent: ob, key: `anova:${y.id}`, closed: true });
          an.add(ctx.rt(comp.anova, { sortable: false, key: 'varanova' }), ctx.note('F tests of the random effects: each mean square over the one whose expectation differs only by that term (the interaction for the main effects of a crossed design).'));
        }
      }
      ob.add(ctx.code(res.code));
    }
    if (gauge && res.gauge) {
      const g = res.gauge;
      const ob = ctx.outline('Gauge R&R', { parent: outline, key: `grr:${y.id}`, menu: () => [{ label: 'Gauge R&R Settings…', action: () => gaugeDialog(ctx, y) }, { label: 'Remove', action: () => ctx.set('gauge', null) }] });
      ob.add(ctx.rt(g.table, { sortable: false, key: 'gauge' }));
      const verdict = g.pct_grr == null ? '' : g.pct_grr < 10 ? 'acceptable' : g.pct_grr <= 30 ? 'marginal' : 'not acceptable';
      ob.add(ctx.kv([['Part', g.part, 'text'], ['Operators', g.operators.join(', ') || '(none)', 'text'], ['% Gauge R&R', g.pct_grr], ['Precision to Part Variation', g.p_to_pv], ['Number of Distinct Categories (NDC)', g.ndc, 'int'],
        ['Discrimination Ratio', g.discrimination], g.tolerance ? ['Tolerance', g.tolerance] : null, g.p_to_t != null ? ['Precision to Tolerance Ratio (P/T)', g.p_to_t] : null].filter(Boolean)));
      ob.add(ctx.rt(g.components, { caption: 'Variance Components for Gauge R&R', sortable: false, key: 'gaugevc' }));
      ob.add(ctx.note(`Variation is ${fmt(g.k)} standard deviations. Repeatability is the within (equipment) variation; reproducibility the operator terms; % Gauge R&R = 100·RR/TV (AIAG: under 10% acceptable, 10–30% marginal: here ${verdict}). NDC = ⌊1.41·PV/RR⌋. The part is ${part ? 'the Part, Sample ID column' : 'the last X, Grouping column'}.${g.note ? ` ${g.note}` : ''}`));
    }
  }

  async function gaugeDialog(ctx, y) {
    const cur = ctx.opt('gauge', null) || {};
    const s = y ? y.specLimits || {} : {};
    const v = await SM.ui.form({
      title: 'Gauge R&R', lead: 'The measurement variation as k standard deviations, and optionally a tolerance (USL − LSL) for the P/T ratio. JMP\'s default k is 6; older AIAG manuals use 5.15.',
      fields: [
        { key: 'k', label: 'K, sigma multiplier', type: 'number', value: cur.k ?? 6,
          help: 'The variation of each source is shown as K standard deviations: 6 by default, as JMP; older AIAG manuals use 5.15. It changes the Variation column, % of Tolerance and P/T, not the shares of the total.' },
        { key: 'tolerance', label: 'Tolerance (USL − LSL)', type: 'number', value: cur.tolerance ?? (s.lsl != null && s.usl != null ? s.usl - s.lsl : null),
          help: 'The width of the specification, for % of Tolerance and the precision to tolerance ratio P/T = K·σ(Gauge R&R)/tolerance. Empty takes the width of the response\'s Spec Limits property, when it has both limits; else there is no P/T.' },
        { key: 'historical', label: 'Historical sigma of the process (optional)', type: 'number', value: cur.historical ?? null,
          help: 'A known standard deviation of the whole process: the total variation becomes its square, and the part variation what is left after the gauge, instead of both coming from the parts in this study.' },
      ],
    });
    if (v) ctx.set('gauge', { k: v.k > 0 ? v.k : 6, tolerance: v.tolerance > 0 ? v.tolerance : null, historical: v.historical > 0 ? v.historical : null });
  }

  async function attributeRender(ctx, y) {
    const raters = ctx.roles('x');
    const part = ctx.role('part') || (raters.length > 1 ? raters[raters.length - 1] : null);
    const rater = raters.find((c) => !part || c.id !== part.id);
    const ob = ctx.outline(`Attribute Gauge for ${y.name}`, { key: `ag:${y.id}`, info: 'p:variability' });
    if (!rater || !part) { ob.add(ctx.warn('An attribute gauge needs the raters (X, Grouping) and the parts (Part, Sample ID, or a second X column).')); return; }
    const res = await ctx.call('quality.attribute_gauge', { y: y.name, rater: rater.name, part: part.name, standard: ctx.name('standard'), where: where(ctx), plot: { room: roomOf(ctx) } });
    const pc = res.plot_code || {};
    if (res.error) { ob.add(ctx.warn(res.error)); return; }
    const c = colors();
    const parts = res.parts;
    const px = parts.map((_, i) => i + 1);
    const pa = parts.map((p) => pct(p.agree));
    const fig1 = groupPlot(ctx, [{ type: 'scatter', mode: 'lines+markers', x: px, y: pa, marker: { size: 7, color: c.point }, line: { color: c.line }, hovertext: parts.map((p) => `${esc(part.name)} ${esc(p.part)}: ${fmt(pct(p.agree), { sig: 4 })}% agreement`), hovertemplate: '%{hovertext}<extra></extra>' }],
      { xaxis: { range: [0.5, parts.length + 0.5], title: { text: esc(part.name) }, ...tickAxis(parts.map((p) => p.part)), tickmode: 'array', tickvals: px, ticktext: parts.map((p) => esc(p.part)) }, yaxis: { title: { text: '% Agreement' }, range: [-5, 105] }, margin: { l: 56, r: 12, t: 10, b: 46 } },
      { width: fitWidth(ctx, Math.max(360, Math.min(760, 120 + 22 * parts.length))), height: 260, title: 'Agreement by part' }, [{ trace: 0, xs: px, ys: pa, rows: parts.map((p) => p.rows) }]);
    const rt = res.rater_table;
    const rx = rt.map((_, i) => i + 1);
    const ra = rt.map((r) => pct(r.agree));
    const fig2 = groupPlot(ctx, [{ type: 'scatter', mode: 'markers', x: rx, y: ra, marker: { size: 9, color: c.overall }, hovertext: rt.map((r) => `${esc(r.rater)}: ${fmt(pct(r.agree), { sig: 4 })}%`), hovertemplate: '%{hovertext}<extra></extra>' }],
      { xaxis: { range: [0.5, rt.length + 0.5], title: { text: esc(rater.name) }, tickmode: 'array', tickvals: rx, ticktext: rt.map((r) => esc(r.rater)) }, yaxis: { title: { text: '% Agreement' }, range: [-5, 105] }, margin: { l: 56, r: 12, t: 10, b: 46 } },
      { width: Math.max(260, 120 + 50 * rt.length), height: 260, title: 'Agreement by rater' }, [{ trace: 0, xs: rx, ys: ra, rows: rt.map((r) => r.rows) }]);
    ob.add(ctx.row(withCode(fig1, ctx.code(pc.parts)), withCode(fig2, ctx.code(pc.raters))));
    const ar = ctx.outline('Agreement Report', { parent: ob, key: 'agree' });
    const cols = [{ key: 'rater', label: rater.name, fmt: 'text' }, { key: 'agree', label: '% Agreement', fmt: 'pct' }, { key: 'within', label: 'Within Rater Agreement', fmt: 'pct' }];
    if (ctx.name('standard')) cols.push({ key: 'effectiveness', label: 'Effectiveness', fmt: 'pct' });
    ar.add(ctx.rt({ columns: cols, rows: rt }, { onRow: (r, ev) => ctx.table.select(r.rows, ev && ev.shiftKey ? 'add' : 'replace'), key: 'agreement' }),
      ctx.note('% Agreement of a rater: of the pairs formed by one of the rater\'s ratings of a part and any other rating of that part, the share that agree. Within rater: the share of parts the rater rated the same every time.'));
    if (res.pairs.rows.length) ar.add(ctx.rt(res.pairs, { caption: 'Agreement Comparisons (Cohen\'s kappa, matched by part and trial)', key: 'kappa' }));
    if (res.fleiss) ar.add(ctx.rt(res.fleiss, { caption: 'Agreement across Categories (Fleiss\' kappa)', sortable: false, key: 'fleiss' }));
    else if (res.fleiss_note) ar.add(ctx.note(res.fleiss_note));
    if (res.effectiveness) {
      const ef = ctx.outline('Effectiveness Report', { parent: ob, key: 'eff' });
      ef.add(ctx.rt(res.effectiveness, { sortable: false, key: 'effectiveness' }));
      const m = res.misclassification;
      ef.add(ctx.rt({ columns: [{ key: 'std', label: 'Standard', fmt: 'text' }, ...m.rated.map((r, j) => ({ key: `c${j}`, label: `Rated ${r}`, fmt: 'int' }))], rows: m.standard.map((s, i) => ({ std: s, ...Object.fromEntries(m.counts[i].map((v, j) => [`c${j}`, v])) })) }, { caption: 'Misclassifications', sortable: false, key: 'misclass' }));
    }
    ob.add(ctx.code(res.code));
  }

  function variabilityTriangle(ctx) {
    const y = ctx.role('y');
    return [
      { label: 'Variability Chart', submenu: () => [
        ctx.check('Variability Chart', 'chart', null, true), ctx.check('Show Points', 'points', null, true), ctx.check('Show Range Bars', 'rangeBars', null, true),
        ctx.check('Show Cell Means', 'cellMeans', null, true), ctx.check('Connect Cell Means', 'connect', null, false), ctx.check('Show Group Means', 'groupMeans', null, false),
        ctx.check('Show Grand Mean', 'grandMean', null, false), ctx.check('Show Grand Median', 'grandMedian', null, false), ctx.check('Show Box Plots', 'boxes', null, false),
        ctx.check('Points Jittered', 'jitter', null, false),
      ] },
      ctx.check('Std Dev Chart', 'sdChart', null, true),
      ctx.check('Mean of Std Dev', 'meanSd', null, true),
      ctx.check('S Control Limits', 'sLimits', null, false),
      ctx.check('Variability Summary Report', 'summaryReport', null, false),
      { separator: true },
      ctx.check('Variance Components', 'varcomp', null, false),
      { label: 'Gauge Studies', submenu: () => [{ label: 'Gauge RR…', action: () => gaugeDialog(ctx, y) }, { label: 'Remove Gauge RR', disabled: !ctx.opt('gauge', null), action: () => ctx.set('gauge', null) }] },
      { label: 'Chart Kind', submenu: () => [['auto', 'By the response\'s modeling type'], ['variability', 'Variability (continuous)'], ['attribute', 'Attribute Gauge (categorical)']].map(([k, l]) => ({ label: l, checked: ctx.opt('kind', 'auto') === k, action: () => ctx.set('kind', k) })) },
    ];
  }

  SM.platforms.register({
    id: 'variability', label: 'Variability / Attribute Gauge Chart', menu: 'Analyze/Quality and Process', order: 40, info: 'p:variability',
    about: 'The variability chart of measurements grouped by nested or crossed factors (operators, parts), with the standard deviation chart, variance components by ANOVA (EMS) or REML, and a Gauge R&R study; for a categorical response the attribute gauge: agreement within and between raters, Cohen\'s and Fleiss\' kappa, effectiveness against a standard.',
    uses: ['statsmodels.formula.api.ols, statsmodels.stats.anova.anova_lm', 'statsmodels.regression.mixed_linear_model.MixedLM', 'statsmodels.stats.inter_rater.fleiss_kappa, cohens_kappa'],
    topics: {
      'p:variability': {
        kicker: 'Analyze > Quality and Process', title: 'Variability / Attribute Gauge Chart',
        lead: 'Measurements grouped by factors, the outer ones first: each cell (an operator measuring a part) shows its points, range and mean, and below it the cell standard deviations. Where the variation comes from is estimated as variance components.',
        sections: [
          { heading: 'Roles', choices: [['Y, Response', 'The measurement; a nominal or ordinal response gives the attribute gauge.'], ['X, Grouping', 'The grouping factors, outer to inner (for example Operator, Part); for an attribute gauge the raters.'], ['Part, Sample ID', 'The parts of a Gauge R&R (else the last X).'], ['Standard', 'Attribute gauge: the true rating of each part.']] },
          { heading: 'Variance components', text: 'Crossed, nested or main-effect random models. For balanced data the ANOVA (expected mean squares) estimates, from statsmodels OLS and anova_lm; otherwise REML from statsmodels MixedLM. Negative ANOVA estimates are set to zero.' },
          { heading: 'Gauge R&R', text: 'Repeatability (within), reproducibility (the operator terms), their sum Gauge R&R, the part variation and the total; % Gauge R&R, the number of distinct categories, the discrimination ratio and, with a tolerance, P/T.' },
        ],
        more: { label: 'Variability / Attribute Gauge Chart', id: 'help-p-variability' },
      },
    },
    launch: {
      lead: 'Choose the response and the grouping columns, outer first. For a Gauge R&R: X = Operator, Part (or Part in Part, Sample ID).',
      roles: [
        { key: 'y', label: 'Y, Response', min: 1, hint: 'required',
          help: 'The measurement; a nominal or ordinal response gives the attribute gauge (the agreement of raters) instead of the variability chart. With several, a report for each.' },
        { key: 'x', label: 'X, Grouping', min: 1, hint: 'required: outer first',
          help: 'The grouping factors, outermost first (for example Operator, then Part): the chart nests the cells in this order, and the variance components are of these factors. For an attribute gauge: the raters, and the parts if there is no Part column.' },
        { key: 'part', label: 'Part, Sample ID', max: 1, hint: 'optional',
          help: 'The parts measured in a Gauge R&R (without it, the last X column is the part); it joins the grouping factors as the innermost one. For an attribute gauge: the parts rated.' },
        { key: 'standard', label: 'Standard', max: 1, hint: 'optional: attribute gauge',
          help: 'Attribute gauge only: the true rating of each part, for the Effectiveness report and the misclassifications.' },
        { key: 'by', label: 'By', hint: 'optional',
          help: 'A separate report for each level of the By column (with several columns, each combination of their levels). Rows with a missing By value are left out.' },
      ],
      options: [
        { key: 'model', label: 'Model', type: 'select', value: 'crossed', choices: MODELS,
          help: 'The random-effects model of the variance components and the Gauge R&R. Crossed, the default: every factor and every interaction. Nested: each factor within the ones before it (each part measured by one operator only). Main Effect: no interactions. The last two mix the two for three factors. The red triangle of Variance Components changes it later.' },
      ],
    },
    title: (spec, table) => {
      const y = (spec.roles.y || []).map((id) => table && table.col(id)).filter(Boolean);
      return y.length && y.every((c) => c.isCategorical) ? 'Attribute Gauge' : 'Variability Gauge';
    },
    triangle: variabilityTriangle,
    render: variabilityRender,
  });

  SM.quality = Object.freeze({ groupPlot, stepLine, colors, specOf, esc, fitWidth });
}(typeof self !== 'undefined' ? self : this));
