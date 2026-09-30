/* ==========================================================================
   SMUI.HTML: ANALYZE > SPECIALIZED MODELING > TIME SERIES

   JMP's Time Series platform on statsmodels.tsa. One report per Y column
   (and By group): the time series graph with its summary and ADF tests,
   the Time Series Basic Diagnostics (autocorrelations with Ljung-Box Q,
   partial autocorrelations, variogram, AR coefficients) and the
   stationarity tests. From the red triangle: differencing, decomposition
   (linear trend, cycle, seasonal_decompose, STL), the spectral density
   with the white noise tests, the lag plot, cross correlations with the
   inputs, and the models: ARIMA, seasonal ARIMA, ARIMA model groups,
   transfer functions, the smoothing models and state space smoothing.
   Every model goes into the Model Comparison table, whose Report and
   Graph boxes choose the model reports and the overlaid forecasts.

   The series is the rows of the report in time order. Excluded rows count
   as missing values, as in JMP, so the spacing of the series is kept; a
   date Time ID gives the frequency, the seasonal period and the dates of
   the forecasts (resources/py/smui/timeseries.py).

   Options live in the report's spec, scoped by the Y column's name (ids
   change when a project is opened again): the toggles of the red
   triangle, and the lists of differences, decompositions and models (with
   their Report, Graph, Show Points ... flags), so they survive Redo and a
   saved project.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, svg, fmt } = SM.util;

  const COLORS = ['#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#17becf', '#9467bd', '#7f7f7f'];
  const DATE_KINDS = new Set(['date', 'datetime']);
  const MORE = { label: 'Time Series', id: 'help-p-timeseries' };
  /* The options of a series are scoped by its column's name, not its id:
     a saved project gives the columns new ids and maps the roles back by
     name, but not the scoped option keys. */
  const scopeOf = (col) => `ts:${col.name}`;
  const int = (v, d = 0) => (v == null || v === '' || !Number.isFinite(Number(v)) ? d : Math.round(Number(v)));
  const colorOf = (id) => COLORS[(Math.max(1, id) - 1) % COLORS.length];
  /* The regimes of a Markov switching model: three categorical slots in a
     fixed order, stepped for each theme (checked for colour-vision
     separation and contrast on both report backgrounds). */
  const REGIME_LIGHT = ['#2a78d6', '#eb6834', '#1baf7a'];
  const REGIME_DARK = ['#3987e5', '#d95926', '#199e70'];
  const regimeColor = (j) => (SM.util.themeColors().dark ? REGIME_DARK : REGIME_LIGHT)[j % 3];
  // Column names are the table's text: escaped for Plotly's titles, names and hover text.
  const ptext = (s) => SM.report.plotlyText(String(s));
  /* The models JMP does not have. Their specs keep their own fields, so they
     are told apart by all of them. */
  const NEW_KINDS = new Set(['uc', 'markov', 'theta', 'ardl', 'bench', 'sma', 'avg']);
  const UI_FLAGS = new Set(['id', 'group', 'report', 'graph', 'points', 'pi', 'racf', 'rpacf', 'rvario', 'rar', 'rruns', 'comps', 'fprob', 'smpi', 'smoothed']);

  function rgba(hex, a) {
    const h = hex.replace('#', '');
    return `rgba(${parseInt(h.slice(0, 2), 16)}, ${parseInt(h.slice(2, 4), 16)}, ${parseInt(h.slice(4, 6), 16)}, ${a})`;
  }

  /* ---- the graphs as matplotlib code ----------------------------------------------
     Under each graph (and each diagnostics chart), Python that draws it with
     matplotlib from a CSV export of the table, as the notebook runs it. The
     function that makes a graph's numbers writes its code as a recipe
     (plot_code in its result, resources/py/smui/timeseries.py): lines, the
     places for the graph's size and a model's colour, and parts that the
     report's display options keep or leave out (Show Points, Show Prediction
     Interval ...), so that neither those options nor the room there is fit a
     model again. recipe() puts one together. Model Comparison's plots, of the
     models whose Graph box is checked, and the lag plot, whose pairs are made
     here, are put together here from the backend's fragments (plot_frag). */
  const J = JSON.stringify;
  // a string as Python's json.dumps writes it (the backend's code): non-ASCII as \uXXXX
  const pyJ = (v) => JSON.stringify(v).replace(/[\u007f-\uffff]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);
  const inches = (px) => String(Math.round(px) / 100);
  function recipe(parts, { flags = {}, size = null, color = null } = {}) {
    const on = (f) => (f.startsWith('!') ? !flags[f.slice(1)] : !!flags[f]);
    const out = [];
    for (const p of parts || []) {
      if (typeof p === 'string') out.push(p);
      else if (p && p.set === 'size') out.push(`size = (${inches(size[0])}, ${inches(size[1])})   # the graph's size in the report, in inches (100 pixels an inch)`);
      else if (p && p.set === 'color') out.push(`color = "${color}"   # the model's colour in the report`);
      else if (p && (p.if || []).every(on) && p.lines && p.lines.length) out.push(recipe(p.lines, { flags, size, color }));
    }
    return out.join('\n');
  }
  /* Axis Settings on a graph of n stacked panels (a decomposition, a filter,
     a structural model's components), for smui-axis.js: in the code, panel
     i (Plotly's yaxis, yaxis2 …) is the figure's axes[i] (plt.subplots(n,
     1, sharex=True)), and the shared x axis is the bottom panel's, where
     Plotly anchors it, so its limits reach every panel (opts.axisCode). The
     x axis serves the panels above too: its reference lines cross them, on
     the graph and in the code (opts.axisAlso). */
  const stackedAxes = (n) => (name) => {
    if (name === 'xaxis') return `plt.gcf().axes[${n - 1}]`;
    const m = /^yaxis(\d*)$/.exec(name);
    const i = m ? (m[1] ? Number(m[1]) - 1 : 0) : -1;
    return i >= 0 && i < n ? `plt.gcf().axes[${i}]` : null;
  };
  const stackedAlso = (n) => (name) => (name === 'xaxis' && n > 1
    ? { plotly: Array.from({ length: n - 1 }, (_, i) => (i ? `y${i + 1}` : 'y')), code: Array.from({ length: n - 1 }, (_, i) => `plt.gcf().axes[${i}]`) } : null);
  const stacked = (n) => ({ axisCode: stackedAxes(n), axisAlso: stackedAlso(n) });
  // A recipe as a code block (none when the result has no graph code).
  const graphCode = (ctx, parts, opts) => (parts && parts.length ? ctx.code(recipe(parts, opts)) : null);
  // A graph with its code block under it, as one item of a row.
  const withCode = (graph, code) => (code ? el('div', { class: 'sm-ts-plotcode' }, graph, code) : graph);

  /* ---- the launch options -------------------------------------------------- */
  const nlags = (ctx) => Math.max(2, int(ctx.opt('nlags', 25), 25));
  const horizon = (ctx) => Math.max(0, Math.min(1000, int(ctx.opt('forecast', 25), 25)));
  const maxiter = (ctx) => Math.max(5, int(ctx.opt('maxiter', 200), 200));
  /* Forecast on Holdback (JMP's launch option, also in the red triangle): the
     last Forecast Periods values are held back, every model is fitted on the
     rest and forecasts them. Refit on All Rows fits every model again on all
     the values, for the forecasts after the end. */
  const holdbackOn = (ctx) => !!ctx.opt('holdback', false) && horizon(ctx) >= 1;
  const refitOn = (ctx) => holdbackOn(ctx) && !!ctx.opt('refit', false);
  // The shading of the held-back values, in both themes.
  const shadeFill = () => (SM.util.themeColors().dark ? 'rgba(200, 190, 178, 0.14)' : 'rgba(120, 107, 93, 0.12)');
  /* A model's plots' end-of-fit line, and with values held back the shading
     from the last value the model is fitted to to the last value. */
  function fitShapes(S, nFit) {
    const end = S.x[nFit - 1];
    const out = [{ type: 'line', x0: end, x1: end, yref: 'paper', y0: 0, y1: 1, line: { color: SM.util.themeColors().muted, width: 1, dash: 'dot' } }];
    if (nFit < S.n) out.push({ type: 'rect', xref: 'x', yref: 'paper', x0: end, x1: S.x[S.n - 1], y0: 0, y1: 1, fillcolor: shadeFill(), line: { width: 0 }, layer: 'below' });
    return out;
  }
  function periodOf(ctx, S) {
    return knownPeriod(ctx, S) || 12;
  }
  /* The seasonal period when one is known (the launch's, or the Time ID's
     calendar's); null otherwise, when periodOf() guesses 12. */
  function knownPeriod(ctx, S) {
    const p = int(ctx.opt('period', null), 0);
    if (p >= 2) return p;
    return S && S.period_auto >= 2 ? S.period_auto : null;
  }
  /* Observations per year of the Time ID's calendar frequency (pandas'
     frequency string: MS, QS-OCT, YS-JAN, W-SUN, 3MS ...), as the backend
     reads it from the offset; null when there is none. */
  function perYear(S) {
    const m = /^(\d*)([A-Z]+)/.exec((S && S.freq) || '');
    if (!m) return null;
    const n = m[1] ? +m[1] : 1;
    const c = m[2].replace(/^B(?=[AYQM])/, '');
    const base = c.startsWith('SM') ? 24 : /^[AY]/.test(c) ? 1 : c.startsWith('Q') ? 4 : c.startsWith('M') ? 12 : c.startsWith('W') ? 52 : null;
    return base ? base / n : null;
  }

  /* All the rows of this report's By group, excluded ones too: they go to
     Python as missing values, so that the spacing of the series is kept.
     The Local Data Filter still drops rows. */
  function groupRows(ctx) {
    const t = ctx.table;
    const where = ctx.where || [];
    const cols = where.map((w) => t.col(w.column));
    let all = [];
    for (let r = 0; r < t.nrows; r++) {
      let ok = true;
      for (let k = 0; k < where.length; k++) if (!cols[k] || cols[k].values[r] !== where[k].value) { ok = false; break; }
      if (ok) all.push(r);
    }
    if (ctx.report && typeof ctx.report.filterRows === 'function') all = ctx.report.filterRows(all);
    const inc = new Set(ctx.rows);
    const excluded = all.filter((r) => !inc.has(r));
    return { rows: all.length === t.nrows ? null : all, excluded };
  }

  function basePayload(ctx, col) {
    const { rows, excluded } = groupRows(ctx);
    return { y: col.name, time: ctx.name('time'), rows, excluded, nlags: nlags(ctx), where: (ctx.where || []).map((w) => ({ column: w.column, value: w.value })) };
  }

  const isDate = (S) => DATE_KINDS.has(S.kind);
  const timeTitle = (S) => S.time || 'Row';
  function xAxis(S, extra = {}) {
    return { title: { text: ptext(timeTitle(S)) }, ...(isDate(S) ? { type: 'date' } : {}), ...extra };
  }
  function plotWidth(ctx, want) {
    const w = ctx.report && ctx.report.body ? ctx.report.body.clientWidth : 0;
    return w > 0 ? Math.max(300, Math.min(want, w - 70)) : want;
  }
  const tLabel = (S, t) => (isDate(S) ? SM.io.formatDate(t, S.withTime ? 'datetime' : 'date') : fmt(t));

  /* The x values of a plot. Dates go to Plotly as ISO text, not as epoch
     milliseconds: the report restyles x when row states change, and Plotly
     then guesses the axis type again, which makes numbers a linear axis. */
  function withX(S) {
    S.withTime = isDate(S) && S.t.some((v) => v != null && v % 86400000 !== 0);
    S.x = isDate(S) ? S.t.map((v) => tLabel(S, v)) : S.t;
    return S;
  }
  const fx = (S, t) => (isDate(S) ? t.map((v) => tLabel(S, v)) : t);

  /* ---- JMP's diagnostics chart: a table with a bar per row ------------------------
     The bars run from -1 to 1 (or over the values' range); the ticks mark ±2
     standard errors. */
  function barSvg(v, se, lo, hi) {
    const W = 132, H = 12;
    const x = (u) => ((Math.max(lo, Math.min(hi, u)) - lo) / (hi - lo)) * W;
    const s = svg('svg', { class: 'sm-ts-bar', width: W, height: H, viewBox: `0 0 ${W} ${H}`, 'aria-hidden': 'true' });
    const x0 = x(Math.max(lo, Math.min(hi, 0)));
    s.append(svg('line', { class: 'axis', x1: x0, x2: x0, y1: 0, y2: H }));
    if (Number.isFinite(v)) {
      const a = x(v);
      s.append(svg('rect', { class: 'bar', x: Math.min(a, x0), y: 2, width: Math.max(0.8, Math.abs(a - x0)), height: H - 4 }));
    }
    if (Number.isFinite(se) && se > 0) for (const b of [-2 * se, 2 * se]) { const xb = x(b); if (b >= lo && b <= hi) s.append(svg('line', { class: 'band', x1: xb, x2: xb, y1: 0, y2: H })); }
    return s;
  }

  function barTable(ctx, { columns, rows, value, se = null, range = [-1, 1], after = 1, caption, name }) {
    const cols = columns.slice();
    cols.splice(after + 1, 0, { key: '_bar', label: '', fmt: 'text' });
    const tbl = ctx.rt({ columns: cols, rows }, { sortable: false, caption, className: 'sm-ts-corr', name });
    let [lo, hi] = range;
    if (range === 'auto') {
      const vals = rows.map(value).filter(Number.isFinite);
      const m = Math.max(1e-12, ...vals.map(Math.abs));
      [lo, hi] = vals.some((v) => v < 0) ? [-m, m] : [0, m];
    }
    tbl.querySelectorAll('tbody tr').forEach((tr, i) => {
      const td = tr.children[after + 1];
      if (!td || !rows[i]) return;
      td.classList.add('sm-ts-barcell');
      td.append(barSvg(value(rows[i]), se ? se(rows[i]) : null, lo, hi));
    });
    return tbl;
  }

  function acfTable(ctx, D, { residual = false } = {}) {
    const a = D.acf;
    const rows = a.lag.map((lag, i) => ({ lag, r: a.r[i], se: a.se[i], q: a.q[i], p: a.p[i] }));
    return barTable(ctx, {
      caption: residual ? 'Residual Autocorrelation' : 'Autocorrelation',
      columns: [{ key: 'lag', label: 'Lag', fmt: 'int' }, { key: 'r', label: 'AutoCorr', digits: 4 }, { key: 'q', label: 'Ljung-Box Q' }, { key: 'p', label: 'p-Value', fmt: 'p' }],
      rows, value: (r) => r.r, se: (r) => (r.lag ? r.se : null), name: 'Autocorrelation',
    });
  }

  function pacfTable(ctx, D, { residual = false } = {}) {
    const a = D.pacf;
    const rows = a.lag.map((lag, i) => ({ lag, r: a.r[i], se: a.se[i] }));
    return barTable(ctx, {
      caption: residual ? 'Residual Partial Autocorrelation' : 'Partial Autocorrelation',
      columns: [{ key: 'lag', label: 'Lag', fmt: 'int' }, { key: 'r', label: 'Partial', digits: 4 }],
      rows, value: (r) => r.r, se: (r) => (r.lag ? r.se : null), name: 'Partial Autocorrelation',
    });
  }

  function variogramTable(ctx, D) {
    const rows = D.variogram.lag.map((lag, i) => ({ lag, v: D.variogram.v[i] }));
    return barTable(ctx, { caption: 'Variogram', columns: [{ key: 'lag', label: 'Lag', fmt: 'int' }, { key: 'v', label: 'Variogram', digits: 4 }], rows, value: (r) => r.v, range: 'auto', name: 'Variogram' });
  }

  function arTable(ctx, D) {
    const rows = D.ar.lag.map((lag, i) => ({ lag, c: D.ar.coef[i] }));
    return barTable(ctx, { caption: 'AR Coefficients', columns: [{ key: 'lag', label: 'Lag', fmt: 'int' }, { key: 'c', label: 'AR Coef', digits: 4 }], rows, value: (r) => r.c, range: 'auto', name: 'AR Coefficients' });
  }

  /* The diagnostics of a series (the original, a difference, residuals), each
     chart with its code under it (codes: the result's plot_code). */
  function diagnosticsBlock(ctx, D, { acf = true, pacf = true, variogram = false, ar = false, residual = false, codes = null } = {}) {
    if (!D || D.error) return D && D.error ? ctx.note(D.error) : null;
    const left = [], right = [];
    const code = (key) => graphCode(ctx, codes && codes[key]);
    if (acf) left.push(acfTable(ctx, D, { residual }), code('acf'));
    if (pacf) right.push(pacfTable(ctx, D, { residual }), code('pacf'));
    if (variogram) left.push(variogramTable(ctx, D), code('variogram'));
    if (ar) right.push(arTable(ctx, D), code('ar'));
    if (!left.length && !right.length) return null;
    const box = ctx.row(left.length ? el('div', { class: 'sm-ts-col' }, ...left) : null, right.length ? el('div', { class: 'sm-ts-col' }, ...right) : null);
    const notes = [];
    if (D.missing) notes.push(ctx.note(`${D.n_missing} missing value${D.n_missing > 1 ? 's' : ''} inside the series: the correlations use the pairs that are present.`));
    return [box, ...notes];
  }

  /* ---- the time series graph -------------------------------------------------- */
  function seriesTrace(S, values, name, { points = true, lines = true, color = SM.report.BASE } = {}) {
    const mode = points && lines ? 'lines+markers' : points ? 'markers' : 'lines';
    // WebGL for long series: SVG slows down beyond a few thousand points.
    return { type: S.t.length > 5000 ? 'scattergl' : 'scatter', mode, x: S.x, y: values, rows: S.rowsLinked, name: ptext(name), connectgaps: false, line: { color, width: 1.2 }, marker: { size: 5, color } };
  }

  /* A series graph, with its code under it when the result has one (code: its recipe). */
  function seriesPlot(ctx, S, values, name, { points = true, lines = true, meanLine = null, extra = [], height = 260, width = 560, title, code = null } = {}) {
    const shapes = [];
    const mean = meanLine != null && Number.isFinite(meanLine);
    if (mean) shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: meanLine, y1: meanLine, line: { color: '#b0413e', width: 1, dash: 'dot' } });
    const traces = [];
    if (points || lines) traces.push(seriesTrace(S, values, name, { points, lines }));
    traces.push(...extra);
    const w = plotWidth(ctx, width);
    const plot = ctx.plot(traces, { xaxis: xAxis(S), yaxis: { title: { text: ptext(name) } }, shapes }, { width: w, height, title: title || `${name} time series` });
    return withCode(plot, graphCode(ctx, code, { flags: { points, lines, mean }, size: [w, height] }));
  }

  function summaryPairs(D, st) {
    const pairs = [['Mean', D.mean], ['SD', D.sd], ['N', D.n, 'int']];
    if (D.n_missing) pairs.push(['N Missing', D.n_missing, 'int']);
    for (const a of (st && st.adf) || []) pairs.push([a.test, a.error ? '.' : a.stat, a.error ? 'text' : 'num']);
    return pairs;
  }

  function stationarityTable(ctx, st) {
    if (!st || st.error) return ctx.note(st ? st.error : 'no stationarity tests');
    const rows = [];
    for (const a of st.adf || []) rows.push({ test: a.test, h0: 'a unit root (a random walk)', stat: a.stat, p: a.error ? a.error : a.p, lags: a.lags, c1: a.c1, c5: a.c5, c10: a.c10 });
    for (const k of st.kpss || []) rows.push({ test: k.test, h0: k.regression === 'c' ? 'level stationary' : 'trend stationary', stat: k.stat, p: k.error ? k.error : k.p_bound ? `${k.p_bound} ${fmt(k.p)}` : k.p, lags: k.lags, c1: k.c1, c5: k.c5, c10: k.c10 });
    return ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'h0', label: 'Null hypothesis', fmt: 'text' }, { key: 'stat', label: 'Statistic' }, { key: 'p', label: 'Prob', fmt: 'p' },
      { key: 'lags', label: 'Lags', fmt: 'int' }, { key: 'c1', label: '1%' }, { key: 'c5', label: '5%' }, { key: 'c10', label: '10%' }], rows }, { sortable: false, name: 'Stationarity Tests' });
  }

  /* ---- the report of one series ---------------------------------------------------- */
  async function renderSeries(ctx, col, box) {
    const sc = scopeOf(col);
    const o = (k, d) => ctx.opt(k, d, sc);
    const base = basePayload(ctx, col);
    const S = await ctx.call('timeseries.series', base);
    if (S.error) { box.add(ctx.warn(`${col.name}: ${S.error}`)); return; }
    S.rowsLinked = S.rows.map((r) => (r == null ? -1 : r));
    withX(S);
    const period = periodOf(ctx, S);
    const h = horizon(ctx);
    const inputs = ctx.roles('inputs').filter((c) => c.id !== col.id);
    for (const n of S.notes || []) box.add(ctx.note(n));

    if (o('graph', true)) {
      const plot = seriesPlot(ctx, S, S.values, col.name, { points: o('points', true), lines: o('lines', true), meanLine: o('meanLine', false) ? S.diag.mean : null, code: S.plot_code && S.plot_code.series });
      box.add(ctx.row(plot, el('div', null, ctx.kv(summaryPairs(S.diag, S.stationarity)), S.freq_label ? ctx.note(`${S.freq_label[0].toUpperCase()}${S.freq_label.slice(1)} data; seasonal period ${period}.`) : null)));
    } else box.add(ctx.kv(summaryPairs(S.diag, S.stationarity)));

    const flags = { acf: o('acf', true), pacf: o('pacf', true), variogram: o('variogram', false), ar: o('arcoef', false) };
    if (flags.acf || flags.pacf || flags.variogram || flags.ar) {
      const ob = ctx.outline('Time Series Basic Diagnostics', { parent: box, key: `${sc}:diag`, info: 'p:timeseries:diagnostics' });
      ob.add(diagnosticsBlock(ctx, S.diag, { ...flags, codes: S.plot_code }));
      ob.add(ctx.code(S.code));
    }
    // Each part on its own: an error in one shows there, the rest still draws.
    const part = async (fn, where = box) => { try { await fn(); } catch (e) { console.error(e); where.add(ctx.error(e)); } };
    if (!seriesLength.has(ctx.report)) seriesLength.set(ctx.report, {});
    seriesLength.get(ctx.report)[sc] = S.n;
    if (o('stationarity', true)) {
      const ob = ctx.outline('Stationarity Tests', { parent: box, key: `${sc}:stat`, info: 'p:timeseries:stationarity', menu: () => [
        { label: 'Zivot-Andrews Test', checked: zivotOn(ctx, col), action: () => ctx.set('zivot', !zivotOn(ctx, col), sc) },
        { label: 'Zivot-Andrews Options…', action: () => zivotDialog(ctx, col) },
        { separator: true },
        { label: 'Remove', action: () => ctx.set('stationarity', false, sc) },
      ] });
      ob.add(stationarityTable(ctx, S.stationarity), ctx.note('ADF: augmented Dickey-Fuller tests of a unit root, with the lags chosen by AIC and MacKinnon\'s p-values and critical values; a small p-value speaks for stationarity. KPSS tests the opposite null, stationarity; statsmodels interpolates its p-value between 0.01 and 0.1 and gives a bound outside.'));
      if (zivotOn(ctx, col)) await part(() => zivotReport(ctx, col, S, base, ob), ob);
      else if (ctx.opt('zivot', null, sc) == null) ob.add(ctx.note(`The Zivot-Andrews test is left out for a series of more than ${ZA_AUTO} values (it takes a while): Zivot-Andrews Test in the red triangle adds it.`));
    }
    if (o('runs', null)) await part(() => runsReport(ctx, col, S, box));
    if (o('spectral', false)) await part(() => spectralReport(ctx, col, S, base, box));
    if (o('lagPlot', null) != null) await part(() => lagPlot(ctx, col, S, box));
    if (o('subseries', false)) await part(() => subseriesReport(ctx, col, S, base, box, period));
    if (inputs.length && o('ccf', false)) await part(() => ccfReport(ctx, col, S, base, inputs, box));
    if (inputs.length && o('inputPanel', true)) await part(() => inputPanel(ctx, col, inputs, base, box));
    for (const spec of o('diffs', [])) await part(() => differenceReport(ctx, col, S, base, spec, box));
    for (const spec of o('decomps', [])) await part(() => decompReport(ctx, col, S, base, spec, box));
    for (const spec of o('filters', [])) await part(() => filterReport(ctx, col, S, base, spec, box));
    await part(() => modelsReport(ctx, col, S, base, box, { period, h }));
  }

  /* ---- Difference -------------------------------------------------------------------- */
  const diffTitle = (d) => `Difference: ${d.d ? `(1 − B)${d.d > 1 ? `^${d.d}` : ''}` : ''}${d.D ? `(1 − B^${d.s})${d.D > 1 ? `^${d.D}` : ''}` : ''}${!d.d && !d.D ? 'none' : ''}`;

  async function differenceReport(ctx, col, S, base, spec, box) {
    const sc = scopeOf(col);
    const flag = (k, dflt) => (spec[k] == null ? dflt : !!spec[k]);
    const up = (patch) => ctx.set('diffs', ctx.opt('diffs', [], sc).map((x) => (x.id === spec.id ? { ...x, ...patch } : x)), sc);
    const r = await ctx.call('timeseries.difference', { ...base, d: spec.d, D: spec.D, s: spec.s });
    const ob = ctx.outline(diffTitle(spec), { parent: box, key: `${sc}:diff:${spec.id}`, info: 'p:timeseries:difference', menu: () => [
      { label: 'Graph', submenu: () => [
        { label: 'Time Series Graph', checked: flag('graph', true), action: () => up({ graph: !flag('graph', true) }) },
        { label: 'Show Points', checked: flag('points', true), action: () => up({ points: !flag('points', true) }) },
        { label: 'Connecting Lines', checked: flag('lines', true), action: () => up({ lines: !flag('lines', true) }) },
        { label: 'Mean Line', checked: flag('meanLine', false), action: () => up({ meanLine: !flag('meanLine', false) }) },
      ] },
      { label: 'Autocorrelation', checked: flag('acf', true), action: () => up({ acf: !flag('acf', true) }) },
      { label: 'Partial Autocorrelation', checked: flag('pacf', true), action: () => up({ pacf: !flag('pacf', true) }) },
      { label: 'Variogram', checked: flag('variogram', false), action: () => up({ variogram: !flag('variogram', false) }) },
      { separator: true },
      { label: 'Save', disabled: !!r.error, action: () => saveSlots(ctx, S, `${col.name} ${diffTitle(spec).replace('Difference: ', '')}`, r.values) },
      { label: 'Remove Fit', action: () => ctx.set('diffs', ctx.opt('diffs', [], sc).filter((x) => x.id !== spec.id), sc) },
    ] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const name = `${col.name} differenced`;
    const pc = r.plot_code || {};
    if (flag('graph', true)) ob.add(ctx.row(seriesPlot(ctx, S, r.values, name, { points: flag('points', true), lines: flag('lines', true), meanLine: flag('meanLine', false) ? r.diag.mean : null, title: `${name} time series`, code: pc.series }), ctx.kv(summaryPairs(r.diag, r.stationarity))));
    else ob.add(ctx.kv(summaryPairs(r.diag, r.stationarity)));
    ob.add(diagnosticsBlock(ctx, r.diag, { acf: flag('acf', true), pacf: flag('pacf', true), variogram: flag('variogram', false), codes: pc }));
    ob.add(ctx.note(`w_t = (1 − B)^${spec.d} (1 − B^${spec.s})^${spec.D} y_t: ${r.start} observation${r.start === 1 ? '' : 's'} at the start are lost to the differencing.`), ctx.code(r.code));
  }

  /* A column for the slots of the series (differenced, detrended ...), saved to the table. */
  function saveSlots(ctx, S, name, values) {
    const rows = [], vals = [];
    S.rows.forEach((r, k) => { if (r != null) { rows.push(r); vals.push(values[k] == null ? NaN : values[k]); } });
    ctx.saveColumn(name, { rows, values: vals });
  }

  /* ---- Decomposition ----------------------------------------------------------------- */
  async function decompReport(ctx, col, S, base, spec, box) {
    const sc = scopeOf(col);
    const remove = () => ctx.set('decomps', ctx.opt('decomps', [], sc).filter((x) => x.id !== spec.id), sc);
    if (spec.kind === 'trend' || spec.kind === 'cycle') {
      const r = spec.kind === 'trend' ? await ctx.call('timeseries.detrend', base) : await ctx.call('timeseries.decycle', { ...base, units: spec.units, constant: spec.constant !== false });
      const label = spec.kind === 'trend' ? 'Linear Trend' : 'Cycle';
      const dname = spec.kind === 'trend' ? `Detrended ${col.name}` : `Decycled ${col.name}`;
      const ob = ctx.outline(label, { parent: box, key: `${sc}:dec:${spec.id}`, info: 'p:timeseries:decomposition', menu: () => [
        { label: 'Save', disabled: !!r.error, action: () => saveSlots(ctx, S, dname, r.values) },
        { label: 'Remove Fit', action: remove },
      ] });
      if (r.error) { ob.add(ctx.warn(r.error)); return; }
      if (spec.kind === 'trend') {
        ob.add(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }], rows: r.params }, { sortable: false }),
          ctx.note('Trend_t = β0 + β1 t by least squares, t = 1, 2, … the observation number; the detrended series is y_t − Trend_t.'));
      } else {
        ob.add(ctx.kv(r.params.map((p) => [p.term, p.estimate])), ctx.note('Cycle_t = C + A cos(2π t/U + P) by least squares on a cosine and a sine, t = 0, 1, … (one less than the observation number); the decycled series is y_t − Cycle_t.'));
      }
      const fit = spec.kind === 'trend' ? r.trend : r.cycle;
      const pc = r.plot_code || {};
      ob.add(seriesPlot(ctx, S, S.values, col.name, { extra: [{ type: 'scatter', mode: 'lines', x: S.x, y: fit, line: { color: '#b0413e', width: 1.6 }, name: label, hoverinfo: 'skip' }], title: `${col.name} ${label.toLowerCase()}`, height: 230, code: pc.fit }));
      const sub = ctx.outline(`Time Series ${dname}`, { parent: ob, key: `${sc}:dec:${spec.id}:series` });
      sub.add(ctx.row(seriesPlot(ctx, S, r.values, dname, { title: `${dname} time series`, height: 230, code: pc.series }), ctx.kv(summaryPairs(r.diag, r.stationarity))));
      sub.add(diagnosticsBlock(ctx, r.diag, { acf: true, pacf: true, codes: pc }), ctx.code(r.code));
      return;
    }
    const r = await ctx.call('timeseries.decompose', { ...base, method: spec.kind === 'stl' ? 'stl' : 'classical', period: spec.period, model: spec.model || 'additive', robust: !!spec.robust });
    const label = spec.kind === 'stl' ? `STL Decomposition (period ${spec.period}${spec.robust ? ', robust' : ''})` : `Seasonal Decomposition (${spec.model || 'additive'}, period ${spec.period})`;
    const ob = ctx.outline(label, { parent: box, key: `${sc}:dec:${spec.id}`, info: 'p:timeseries:decomposition', menu: () => [
      { label: 'Save Columns', disabled: !!r.error, action: () => {
        saveSlots(ctx, S, `Seasonally Adjusted ${col.name}`, r.adjusted);
        saveSlots(ctx, S, `Trend ${col.name}`, r.trend);
        saveSlots(ctx, S, `Seasonal ${col.name}`, r.seasonal);
        saveSlots(ctx, S, `Irregular ${col.name}`, r.resid);
      } },
      { label: 'Remove Fit', action: remove },
    ] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const x = S.x;
    const panel = (y, name, axis) => ({ type: 'scatter', mode: 'lines', x, y, name, xaxis: 'x', yaxis: axis, line: { color: SM.report.BASE, width: 1.2 }, hovertemplate: `${name}: %{y:.5g}<extra></extra>` });
    const traces = [
      { ...seriesTrace(S, S.values, col.name, { points: true, lines: true }), xaxis: 'x', yaxis: 'y' },
      { type: 'scatter', mode: 'lines', x, y: r.adjusted, name: 'Seasonally adjusted', xaxis: 'x', yaxis: 'y', line: { color: '#b0413e', width: 1.2 }, hoverinfo: 'skip' },
      panel(r.trend, 'Trend', 'y2'), panel(r.seasonal, 'Seasonal', 'y3'), panel(r.resid, 'Irregular', 'y4'),
    ];
    const dom = [[0.73, 1], [0.49, 0.69], [0.25, 0.45], [0, 0.21]];
    const titles = ['Original and adjusted', 'Trend', 'Seasonal', 'Irregular'];
    const layout = { xaxis: xAxis(S, { anchor: 'y4' }), height: 520, margin: { l: 60, r: 12, t: 8, b: 40 },
      annotations: titles.map((t, i) => ({ text: t, xref: 'paper', yref: 'paper', x: 0, y: dom[i][1], xanchor: 'left', yanchor: 'bottom', showarrow: false, font: { size: 10.5 } })) };
    dom.forEach((d, i) => { layout[`yaxis${i ? i + 1 : ''}`] = { domain: d, title: { text: '' } }; });
    const w = plotWidth(ctx, 620);
    ob.add(ctx.plot(traces, layout, { width: w, height: 520, title: label, ...stacked(4) }), graphCode(ctx, r.plot_code && r.plot_code.decomp, { size: [w, 520] }));
    ob.add(ctx.note(spec.kind === 'stl' ? 'STL: seasonal and trend by loess (statsmodels\' STL). The seasonally adjusted series is y − seasonal.' : `Moving averages (statsmodels' seasonal_decompose): the trend is a centred moving average over the period, so it is missing at the ends. The adjusted series is ${spec.model === 'multiplicative' ? 'y / seasonal' : 'y − seasonal'}. JMP's X11 needs the Census Bureau's program, which does not run in the browser.`));
    for (const n of r.notes || []) ob.add(ctx.note(n));
    ob.add(ctx.code(r.code));
  }

  /* ---- Runs Test ------------------------------------------------------------------------------ */
  const RUNS_ABOUT = { mean: 'About the Mean', median: 'About the Median', zero: 'About Zero' };

  function runsReport(ctx, col, S, box) {
    const sc = scopeOf(col);
    const cut = ctx.opt('runs', 'mean', sc);
    const ob = ctx.outline('Runs Test', { parent: box, key: `${sc}:runs`, info: 'p:timeseries:runs', menu: () => [
      ...Object.entries(RUNS_ABOUT).map(([k, label]) => ({ label, checked: cut === k, action: () => ctx.set('runs', k, sc) })),
      { separator: true }, { label: 'Remove', action: () => ctx.set('runs', null, sc) }] });
    ob.add(runsBlock(ctx, (S.runs || {})[cut], `Runs about ${{ mean: 'the mean', median: 'the median', zero: 'zero' }[cut]}`, 'the values of the series', S.runs_code ? S.runs_code[cut].join('\n') : null));
  }

  /* ---- Spectral Density ------------------------------------------------------------------- */
  async function spectralReport(ctx, col, S, base, box) {
    const sc = scopeOf(col);
    const r = await ctx.call('timeseries.spectral', base);
    const ob = ctx.outline('Spectral Density', { parent: box, key: `${sc}:spec`, info: 'p:timeseries:spectral', menu: () => [
      { label: 'Save Spectral Density', disabled: !!r.error, action: () => saveSpectral(col, r) },
      { label: 'Remove', action: () => ctx.set('spectral', false, sc) },
    ] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const pg = { type: 'scatter', mode: 'markers', marker: { size: 4, color: rgba('#2f6690', 0.5) }, name: 'Periodogram', hovertemplate: 'periodogram %{y:.4g}<extra></extra>' };
    const dn = { type: 'scatter', mode: 'lines', line: { color: '#b0413e', width: 1.8 }, name: 'Spectral density', hovertemplate: 'density %{y:.4g}<extra></extra>' };
    const w = plotWidth(ctx, 420);
    const yl = { title: { text: 'Spectral density' } };
    const pc = r.plot_code || {};
    const byPeriod = ctx.plot([{ ...dn, x: r.period, y: r.density }], { xaxis: { title: { text: 'Period' }, type: 'log' }, yaxis: yl }, { width: w, height: 250, title: `${col.name} spectral density by period` });
    const byFreq = ctx.plot([{ ...pg, x: r.frequency, y: r.periodogram.map((v) => v / (4 * Math.PI)) }, { ...dn, x: r.frequency, y: r.density }],
      { xaxis: { title: { text: 'Frequency' } }, yaxis: yl, showlegend: true, legend: { orientation: 'h', y: -0.3 } }, { width: w, height: 270, title: `${col.name} spectral density by frequency` });
    ob.add(ctx.row(withCode(byPeriod, graphCode(ctx, pc.period, { size: [w, 250] })), withCode(byFreq, graphCode(ctx, pc.frequency, { size: [w, 270] }))));
    const wn = ctx.outline('White Noise Test', { parent: ob, key: `${sc}:spec:wn` });
    wn.add(ctx.kv([["Fisher's Kappa", r.kappa], ['Prob > Kappa', r.p_kappa, 'p'], ["Bartlett's Kolmogorov-Smirnov", r.bartlett], ['Prob > KS (asymptotic)', r.p_bartlett, 'p'],
      ['5% critical value (1.36/√q)', r.crit5], ['1% critical value (1.63/√q)', r.crit1]]),
    ctx.note(`The periodogram I(f) = (N/2)(a² + b²) at the ${r.q} Fourier frequencies i/N; the spectral density is the periodogram smoothed with triangular weights over ${2 * r.m + 1} frequencies and scaled by 1/(4π) (JMP does not document its smoothing weights, so its curve can differ in detail). Fisher's kappa is q·max I/ΣI with its exact p-value; Bartlett's statistic is the largest gap between the cumulative periodogram and the uniform distribution.${r.dropped ? ` ${r.dropped} missing values were left out.` : ''}`), ctx.code(r.code));
  }

  function saveSpectral(col, r) {
    const f = [0, ...r.frequency];
    const t = new SM.Table({ name: `${col.name} spectral density`, source: 'saved by Time Series > Save Spectral Density', columns: [
      { name: 'Period', dataType: 'numeric', values: f.map((x) => (x > 0 ? 1 / x : NaN)) },
      { name: 'Frequency', dataType: 'numeric', values: f },
      { name: 'Angular Frequency', dataType: 'numeric', values: f.map((x) => 2 * Math.PI * x) },
      { name: 'Sine', dataType: 'numeric', values: r.sine.map((x) => (x == null ? NaN : x)) },
      { name: 'Cosine', dataType: 'numeric', values: r.cosine.map((x) => (x == null ? NaN : x)) },
      { name: 'Periodogram', dataType: 'numeric', values: [r.periodogram0 ?? NaN, ...r.periodogram] },
      { name: 'Spectral Density', dataType: 'numeric', values: [NaN, ...r.density] },
    ] });
    SM.app.addTable(t);
  }

  /* ---- Lag Plot ------------------------------------------------------------------------------- */
  function lagPlot(ctx, col, S, box) {
    const sc = scopeOf(col);
    const lag = Math.max(1, Math.min(Math.max(1, S.n - 2), int(ctx.opt('lagPlot', 1, sc), 1)));
    const ob = ctx.outline(`Lag Plot (lag ${lag})`, { parent: box, key: `${sc}:lag`, info: 'p:timeseries:lag', menu: () => [{ label: 'Remove', action: () => ctx.set('lagPlot', null, sc) }] });
    const x = [], y = [], rows = [];
    for (let k = lag; k < S.n; k++) {
      const a = S.values[k - lag], b = S.values[k];
      if (a == null || b == null) continue;
      x.push(a); y.push(b); rows.push(S.rowsLinked[k]);
    }
    const n = x.length;
    let r = NaN;
    if (n > 2) {
      const mx = x.reduce((s, v) => s + v, 0) / n, my = y.reduce((s, v) => s + v, 0) / n;
      let sxy = 0, sxx = 0, syy = 0;
      for (let k = 0; k < n; k++) { sxy += (x[k] - mx) * (y[k] - my); sxx += (x[k] - mx) ** 2; syy += (y[k] - my) ** 2; }
      r = sxy / Math.sqrt(sxx * syy);
    }
    const input = el('input', { type: 'text', inputmode: 'numeric', size: 3, value: String(lag), 'aria-label': 'Lag' });
    const go = (v) => ctx.set('lagPlot', Math.max(1, int(v, lag)), sc);
    input.addEventListener('change', () => go(input.value));
    input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); go(input.value); } });
    const btn = (label, d) => { const b = el('button', { type: 'button', class: 'sm-btn small', text: label, 'aria-label': d < 0 ? 'Previous lag' : 'Next lag' }); b.addEventListener('click', () => go(lag + d)); return b; };
    ob.add(el('div', { class: 'sm-ts-lagctl' }, el('label', null, 'Lag p ', input), btn('−', -1), btn('+', 1)));
    const w = plotWidth(ctx, 360);
    const plot = ctx.plot([{ type: 'scatter', mode: 'markers', x, y, rows, name: ptext(`${col.name} at t and t − ${lag}`) }],
      { xaxis: { title: { text: ptext(`${col.name}(t − ${lag})`) } }, yaxis: { title: { text: ptext(`${col.name}(t)`) } } }, { width: w, height: 320, title: `${col.name} lag plot` });
    ob.add(ctx.row(withCode(plot, lagCode(ctx, S, col, lag, [w, 320])), ctx.kv([['Lag', lag, 'int'], ['Pairs', n, 'int'], ['Correlation', r]])),
      ctx.note('Each point is an observation (y axis) against the one p periods before it; clicking selects the later row.'));
  }

  /* The lag plot's code: its pairs are made here, from the series as the
     backend's lines build it (plot_frag of timeseries.series). */
  function lagCode(ctx, S, col, lag, size) {
    const frag = S.plot_frag;
    if (!frag || !frag.series) return null;
    return ctx.code([SM.report.codeHead(ctx.table.name, ['import matplotlib.pyplot as plt']), ...frag.series,
      `lag = ${lag}   # the report's lag (Lag p)`,
      'x, v = y.to_numpy()[:-lag], y.to_numpy()[lag:]   # each value (v) and the one lag periods before it (x)',
      'ok = np.isfinite(x) & np.isfinite(v)   # the pairs with both values',
      '', recipe([{ set: 'size' }], { size }), 'fig, ax = plt.subplots(figsize=size, layout="constrained")',
      'ax.plot(x[ok], v[ok], color="#2f6690", linestyle="", marker="o", markersize=4.32)',
      `ax.set_xlabel(${J(`${col.name}(t − ${lag})`)})`, `ax.set_ylabel(${J(`${col.name}(t)`)})`, `ax.set_title(${J(`${col.name} lag plot`)})`, 'plt.show()'].join('\n'));
  }

  /* ---- Cross Correlation ---------------------------------------------------------------------------- */
  async function ccfReport(ctx, col, S, base, inputs, box) {
    const sc = scopeOf(col);
    const r = await ctx.call('timeseries.ccf', { ...base, inputs: inputs.map((c) => c.name) });
    const ob = ctx.outline('Cross Correlation', { parent: box, key: `${sc}:ccf`, info: 'p:timeseries:ccf', menu: () => [{ label: 'Remove', action: () => ctx.set('ccf', false, sc) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const tables = r.inputs.map((c) => {
      if (c.error) return ctx.note(c.error);
      const rows = c.lag.map((lag, i) => ({ lag, r: c.r[i], se: c.se[i] }));
      return barTable(ctx, { caption: `${col.name} with ${c.input}`, columns: [{ key: 'lag', label: 'Lag', fmt: 'int' }, { key: 'r', label: 'Cross Corr', digits: 4 }], rows, value: (x) => x.r, se: (x) => x.se, name: `Cross correlation ${c.input}` });
    });
    ob.add(ctx.row(...tables), graphCode(ctx, r.plot_code && r.plot_code.ccf),
      ctx.note(`Lag k is the correlation of ${col.name} at t + k with the input at t, so positive lags are the input leading. Ticks: ±2 standard errors, 1/√(n − |k|).`), ctx.code(r.code));
  }

  /* ---- Input Time Series Panel ------------------------------------------------------------------------- */
  async function inputPanel(ctx, col, inputs, base, box) {
    const sc = scopeOf(col);
    const ob = ctx.outline('Input Time Series Panel', { parent: box, key: `${sc}:inputs`, closed: true, menu: () => [{ label: 'Remove', action: () => ctx.set('inputPanel', false, sc) }] });
    for (const c of inputs) {
      const r = await ctx.call('timeseries.input', { y: c.name, time: base.time, rows: base.rows, nlags: base.nlags, where: base.where });
      const sub = ctx.outline(`Input Series ${c.name}`, { parent: ob, key: `${sc}:input:${c.name}` });
      if (r.error) { sub.add(ctx.warn(r.error)); continue; }
      r.rowsLinked = r.rows.map((x) => (x == null ? -1 : x));
      const R = withX({ ...r, time: base.time });
      const pc = r.plot_code || {};
      sub.add(ctx.row(seriesPlot(ctx, R, r.values, c.name, { height: 220, width: 480, code: pc.series }), ctx.kv(summaryPairs(r.diag, r.stationarity))));
      sub.add(diagnosticsBlock(ctx, r.diag, { acf: true, pacf: false, codes: pc }));
    }
  }

  /* ---- Zivot-Andrews ------------------------------------------------------------------------------------------- */
  /* On by default up to 5000 values: its regressions at every break date
     grow with the square of the length (3 s at 5000 in the browser). The
     length of each series of a report is kept for the menus' check marks. */
  const ZA_AUTO = 5000;
  const seriesLength = new WeakMap();
  const zivotOn = (ctx, col) => !!ctx.opt('zivot', ((seriesLength.get(ctx.report) || {})[scopeOf(col)] ?? 0) <= ZA_AUTO, scopeOf(col));
  const ZA_DASH = ['dot', 'dash', 'dashdot'];
  const ZA_SHORT = { c: 'intercept', t: 'trend', ct: 'both' };
  const zivotOpts = (ctx, col) => {
    const sc = scopeOf(col);
    return { trim: ctx.opt('zaTrim', 0.15, sc), maxlag: ctx.opt('zaMaxlag', null, sc), autolag: ctx.opt('zaAutolag', 'AIC', sc) };
  };

  async function zivotReport(ctx, col, S, base, parent) {
    const sc = scopeOf(col);
    const r = await ctx.call('timeseries.zivot', { ...base, ...zivotOpts(ctx, col) });
    const ob = ctx.outline('Zivot-Andrews Test', { parent, key: `${sc}:za`, info: 'p:timeseries:zivot', menu: () => [
      { label: 'Zivot-Andrews Options…', action: () => zivotDialog(ctx, col) },
      { label: 'Remove', action: () => ctx.set('zivot', false, sc) },
    ] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const rows = r.tests.map((t) => (t.error ? { test: t.test, stat: null, p: t.error }
      : { test: t.test, stat: t.stat, p: t.p, lags: t.lags, brk: tLabel(S, t.break), c1: t.c1, c5: t.c5, c10: t.c10 }));
    ob.add(ctx.rt({ columns: [{ key: 'test', label: 'Model', fmt: 'text' }, { key: 'stat', label: 'Statistic' }, { key: 'p', label: 'Prob', fmt: 'p' }, { key: 'lags', label: 'Lags', fmt: 'int' },
      { key: 'brk', label: 'Break', fmt: 'text' }, { key: 'c1', label: '1%' }, { key: 'c5', label: '5%' }, { key: 'c10', label: '10%' }], rows }, { sortable: false, name: 'Zivot-Andrews Test' }));
    const ok = r.tests.filter((t) => !t.error);
    if (ok.length) {
      const muted = SM.util.themeColors().muted;
      // one line for each break date, labelled with the models that put the break there
      const at = new Map();
      for (const t of ok) { const k = String(t.break); if (!at.has(k)) at.set(k, []); at.get(k).push(ZA_SHORT[t.regression]); }
      const dates = [...at.keys()];
      const shapes = dates.map((k, i) => { const x = fx(S, [Number(k)])[0]; return { type: 'line', x0: x, x1: x, yref: 'paper', y0: 0, y1: 1, line: { color: '#b0413e', width: 1.3, dash: ZA_DASH[i % 3] } }; });
      const annotations = dates.map((k, i) => ({ x: fx(S, [Number(k)])[0], y: 1 - 0.1 * i, yref: 'paper', xanchor: 'left', yanchor: 'top', showarrow: false, text: ` ${at.get(k).join(', ')}`, font: { size: 10, color: muted } }));
      const w = plotWidth(ctx, 560);
      ob.add(ctx.plot([seriesTrace(S, S.values, col.name)], { xaxis: xAxis(S), yaxis: { title: { text: ptext(col.name) } }, shapes, annotations },
        { width: w, height: 220, title: `${col.name} Zivot-Andrews breaks` }), graphCode(ctx, r.plot_code && r.plot_code.breaks, { size: [w, 220] }));
    }
    for (const n of r.notes || []) ob.add(ctx.note(n));
    ob.add(ctx.code(r.code));
  }

  async function zivotDialog(ctx, col) {
    const sc = scopeOf(col);
    const o = zivotOpts(ctx, col);
    const v = await SM.ui.form({
      title: `Zivot-Andrews Test: ${col.name}`, info: 'p:timeseries:zivot',
      lead: 'The break is searched for between the trimmed ends of the series. The lags of the test regression are chosen once by the criterion, up to the largest lag (empty: 12(n/100)^¼, Schwert\'s rule).',
      fields: [
        { key: 'trim', label: 'Trimming at each end (0 to 1/3)', type: 'number', value: o.trim, helpLabel: 'Trimming at each end',
          help: 'The share of the series at each end where no break is looked for, from 0 up to below 1/3: 0.15 by default, Zivot and Andrews\' own. A break needs enough data on both sides; less trimming looks nearer the ends.' },
        { key: 'maxlag', label: 'Largest lag (empty: automatic)', type: 'number', value: o.maxlag ?? '', helpLabel: 'Largest lag',
          help: 'The most lagged differences in the test regression, a whole number from 0. Empty (the default): 12(n/100)^¼, Schwert\'s rule, as statsmodels takes it.' },
        { key: 'autolag', label: 'Lags chosen by', type: 'select', value: o.autolag || 'none', choices: [['AIC', 'AIC'], ['BIC', 'BIC'], ['t-stat', 't statistic of the last lag'], ['none', 'none: the largest lag']],
          help: 'How many of those lags the test keeps, chosen once for the regression without a break (Baum\'s approximation): AIC (the default) or BIC, the smallest criterion; the t statistic, dropping the last lag while it is not significant at 5%; none, all of them.' },
      ],
      validate: (x) => (!(x.trim >= 0 && x.trim < 1 / 3) ? 'Trimming: from 0 up to below 1/3' : x.maxlag != null && !(Number.isInteger(x.maxlag) && x.maxlag >= 0) ? 'Largest lag: a whole number from 0' : null),
    });
    if (!v) return;
    ctx.set('zaTrim', v.trim, sc, { rerun: false });
    ctx.set('zaMaxlag', v.maxlag, sc, { rerun: false });
    ctx.set('zaAutolag', v.autolag === 'none' ? null : v.autolag, sc, { rerun: false });
    ctx.set('zivot', true, sc);
  }

  /* ---- Seasonal Subseries Plot --------------------------------------------------------------------------------- */
  const SUB_BY = { month: ['calendar month', 'month_plot'], quarter: ['quarter', 'quarter_plot'], weekday: ['weekday', 'seasonal_plot'], position: ['position in the period', 'seasonal_plot'] };

  async function subseriesReport(ctx, col, S, base, box, period) {
    const sc = scopeOf(col);
    const r = await ctx.call('timeseries.subseries', { ...base, period });
    const ob = ctx.outline('Seasonal Subseries Plot', { parent: box, key: `${sc}:subseries`, info: 'p:timeseries:subseries', menu: () => [{ label: 'Remove', action: () => ctx.set('subseries', false, sc) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const traces = r.seasons.map((s) => ({ type: 'scatter', mode: 'lines+markers', x: s.x, y: s.values, rows: s.rows.map((x) => (x == null ? -1 : x)), name: s.label, connectgaps: false,
      line: { color: SM.report.BASE, width: 1.2 }, marker: { size: 5, color: SM.report.BASE }, hovertext: s.t.map((t) => tLabel(S, t)), hovertemplate: `${s.label}, %{hovertext}: %{y:.5g}<extra></extra>` }));
    const shapes = r.seasons.filter((s) => s.mean != null).map((s) => ({ type: 'line', x0: s.x[0] - 0.35, x1: s.x[s.x.length - 1] + 0.35, y0: s.mean, y1: s.mean, line: { color: '#b0413e', width: 2.5 } }));
    const [what, fn] = SUB_BY[r.by] || SUB_BY.position;
    const w = plotWidth(ctx, 720);
    ob.add(ctx.plot(traces, {
      xaxis: { tickvals: r.seasons.map((s) => (s.x[0] + s.x[s.x.length - 1]) / 2), ticktext: r.seasons.map((s) => s.label), showgrid: false, zeroline: false,
        title: { text: r.by === 'position' ? `Position in the period of ${r.period}` : '' } },
      yaxis: { title: { text: ptext(col.name) } }, shapes,
    }, { width: w, height: 300, title: `${col.name} seasonal subseries` }), graphCode(ctx, r.plot_code && r.plot_code.subseries, { size: [w, 300] }));
    ob.add(ctx.note(`Each small series is one ${what} over the years, in time order, and the red line is its mean (statsmodels' ${fn}). Points are linked to the rows.`));
    for (const n of r.notes || []) ob.add(ctx.note(n));
    const tb = ctx.outline('Season Means', { parent: ob, key: `${sc}:subseries:means`, closed: true });
    tb.add(ctx.rt({ columns: [{ key: 'label', label: 'Season', fmt: 'text' }, { key: 'n', label: 'N', fmt: 'int' }, { key: 'mean', label: 'Mean' }, { key: 'sd', label: 'Std Dev' }], rows: r.seasons }, { sortable: false, name: 'Season means' }));
    ob.add(ctx.code(r.code));
  }

  /* ---- Filters: Hodrick-Prescott, Baxter-King, Christiano-Fitzgerald ------------------------------------------ */
  const FILTERS = [['hp', 'Hodrick-Prescott Filter'], ['bk', 'Baxter-King Filter'], ['cf', 'Christiano-Fitzgerald Filter']];
  const FILTER_LABEL = Object.fromEntries(FILTERS);

  /* The defaults for the frequency, as the backend has them: λ = 1600 (s/4)^4
     (Ravn and Uhlig), the band of 1.5 to 8 years, K of 3 years; statsmodels'
     own (1600; 6, 32, 12) with no calendar frequency. */
  function filterDefaults(S) {
    const f = perYear(S);
    if (!f) return { f: null, lamb: 1600, low: 6, high: 32, K: 12 };
    return { f, lamb: 1600 * (f / 4) ** 4, low: Math.max(2, 1.5 * f), high: 8 * f, K: Math.max(1, Math.round(3 * f)) };
  }

  async function filterReport(ctx, col, S, base, spec, box) {
    const sc = scopeOf(col);
    const remove = () => ctx.set('filters', ctx.opt('filters', [], sc).filter((x) => x.id !== spec.id), sc);
    const r = await ctx.call('timeseries.filter', { ...base, method: spec.kind, lamb: spec.lamb ?? null, low: spec.low ?? null, high: spec.high ?? null, K: spec.K ?? null, drift: spec.drift !== false });
    const tag = spec.kind.toUpperCase();
    const ob = ctx.outline(r.label || FILTER_LABEL[spec.kind], { parent: box, key: `${sc}:flt:${spec.id}`, info: 'p:timeseries:filters', menu: () => [
      { label: 'Save Columns', disabled: !!r.error, action: () => { saveSlots(ctx, S, `${col.name} ${tag} trend`, r.trend); saveSlots(ctx, S, `${col.name} ${tag} cycle`, r.cycle); } },
      { label: 'Remove Fit', action: remove },
    ] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const name = ptext(col.name);
    const traces = [
      { ...seriesTrace(S, S.values, col.name, { points: true, lines: false }), xaxis: 'x', yaxis: 'y' },
      { type: 'scatter', mode: 'lines', x: S.x, y: r.trend, xaxis: 'x', yaxis: 'y', name: spec.kind === 'bk' ? 'y − cycle' : 'Trend', line: { color: '#b0413e', width: 1.8 }, hovertemplate: 'trend %{y:.5g}<extra></extra>' },
      { type: 'scatter', mode: 'lines', x: S.x, y: r.cycle, xaxis: 'x', yaxis: 'y2', name: 'Cycle', line: { color: SM.report.BASE, width: 1.4 }, hovertemplate: 'cycle %{y:.5g}<extra></extra>' },
    ];
    const titles = [[spec.kind === 'bk' ? `${col.name} and y − cycle` : `${col.name} and trend`, 1], ['Cycle', 0.37]];
    const layout = { xaxis: xAxis(S, { anchor: 'y2' }), yaxis: { domain: [0.47, 1], title: { text: name } }, yaxis2: { domain: [0, 0.37], title: { text: 'Cycle' }, zeroline: true },
      margin: { l: 60, r: 12, t: 16, b: 40 },
      annotations: titles.map(([t, y]) => ({ text: ptext(t), xref: 'paper', yref: 'paper', x: 0, y, xanchor: 'left', yanchor: 'bottom', showarrow: false, font: { size: 10.5 } })) };
    const w = plotWidth(ctx, 620);
    ob.add(ctx.row(withCode(ctx.plot(traces, layout, { width: w, height: 400, title: r.label, ...stacked(2) }), graphCode(ctx, r.plot_code && r.plot_code.filter, { size: [w, 400] })),
      ctx.kv([spec.kind === 'hp' ? ['λ', r.lamb] : ['Band (periods)', `${fmt(r.low)} to ${fmt(r.high)}`, 'text'], spec.kind === 'bk' ? ['K', r.K, 'int'] : null,
        spec.kind === 'cf' ? ['Drift removed', r.drift ? 'Yes' : 'No', 'text'] : null, ['Std Dev of the cycle', r.cycle_sd], ['N (cycle)', r.cycle_n, 'int']])));
    for (const n of r.notes || []) ob.add(ctx.note(n));
    ob.add(ctx.code(r.code));
  }

  async function filterDialog(ctx, col, S, kind) {
    const sc = scopeOf(col);
    const D = filterDefaults(S);
    const freq = D.f ? `${fmt(D.f)} observations a year` : 'no calendar frequency: statsmodels\' defaults, meant for quarterly data';
    const fields = kind === 'hp'
      ? [{ key: 'lamb', label: 'λ, Smoothing', type: 'number', value: D.lamb,
        help: 'The penalty on the trend\'s squared second differences, above 0: a larger λ gives a smoother trend and leaves more in the cycle. It starts at Ravn and Uhlig\'s 1600 (s/4)⁴ for s observations a year, or at 1600 when the Time ID has no calendar frequency.' }]
      : [{ key: 'low', label: 'Shortest period in the band', type: 'number', value: D.low,
        help: 'The shortest cycle kept, in observations, at least 2: movements faster than it stay out of the cycle. It starts at 1.5 years of observations (6 quarters), or 6 with no calendar frequency.' },
      { key: 'high', label: 'Longest period in the band', type: 'number', value: D.high,
        help: 'The longest cycle kept, in observations, above the shortest: slower movements count as trend. It starts at 8 years of observations (32 quarters), or 32 with no calendar frequency.' }];
    if (kind === 'bk') fields.push({ key: 'K', label: 'K, Lead-lag length (values lost at each end)', type: 'number', value: D.K, helpLabel: 'K, Lead-lag length',
      help: 'The half-length of the moving average, a whole number from 1: it has 2K + 1 terms, comes closer to the ideal band pass as K grows, and loses K values of the cycle at each end. It starts at 3 years of observations (12 quarters).' });
    if (kind === 'cf') fields.push({ key: 'drift', label: 'Remove the drift first', type: 'check', value: true,
      help: 'Takes out the line through the first and the last value (the drift of a random walk) before filtering, as Christiano and Fitzgerald do. On by default.' });
    const lead = kind === 'hp' ? `The trend minimises the squared deviations plus λ times the squared second differences of the trend. λ follows Ravn and Uhlig's rule 1600 (s/4)⁴ for s observations a year (${freq}): 6.25 yearly, 1600 quarterly, 129600 monthly.`
      : `A band-pass filter keeps the cycles whose period lies in the band, by default the business cycle of 1.5 to 8 years (${freq}).`;
    const v = await SM.ui.form({ title: `${FILTER_LABEL[kind]}: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:filters', lead, fields,
      validate: (x) => {
        if (kind === 'hp') return x.lamb > 0 ? null : 'λ: above 0';
        if (!(x.low >= 2 && x.high > x.low)) return 'The band: periods from 2 up, the shortest below the longest';
        if (kind === 'bk' && !(Number.isInteger(x.K) && x.K >= 1)) return 'K: a whole number from 1';
        return null;
      } });
    if (!v) return;
    const list = ctx.opt('filters', [], sc).slice();
    const spec = { id: list.reduce((m, x) => Math.max(m, x.id || 0), 0) + 1, kind };
    if (kind === 'hp') spec.lamb = v.lamb; else { spec.low = v.low; spec.high = v.high; }
    if (kind === 'bk') spec.K = v.K;
    if (kind === 'cf') spec.drift = !!v.drift;
    list.push(spec);
    ctx.set('filters', list, sc);
  }

  /* ---- models: the fits ---------------------------------------------------------------------------------- */
  /* The backend function of a model and its own arguments (the series' come
     with the call): { fn, args }, or { error }. An averaged model names its
     members by their ids in the list. */
  function callOf(ctx, spec, h, list = []) {
    const level = spec.level || 0.95;
    if (spec.kind === 'arima') {
      return { fn: 'timeseries.arima', args: { p: spec.p, d: spec.d, q: spec.q, P: spec.P || 0, D: spec.D || 0, Q: spec.Q || 0, s: spec.s || 0,
        intercept: spec.intercept !== false, constrain: spec.constrain !== false, level, h, maxiter: maxiter(ctx), inputs: spec.inputs || null } };
    }
    if (spec.kind === 'smooth') {
      return { fn: 'timeseries.smooth', args: { method: spec.method, s: spec.s || 0, level, h, multiplicative: !!spec.multiplicative,
        ...(spec.weights ? { weights: spec.weights } : {}), ...(spec.boxcox != null ? { boxcox: spec.boxcox } : {}) } };
    }
    if (spec.kind === 'ets') return { fn: 'timeseries.ets', args: { error: spec.error, trend: spec.trend, seasonal: spec.seasonal, s: spec.s || 0, level, h, maxiter: Math.max(200, maxiter(ctx)) } };
    if (spec.kind === 'uc') {
      return { fn: 'timeseries.structural', args: { trend: spec.trend, seasonal: spec.seasonal || 0, stoch_seasonal: spec.stochSeasonal !== false,
        freq_period: spec.freqPeriod || 0, freq_harmonics: spec.freqHarmonics || 0, stoch_freq: spec.stochFreq !== false, cycle: !!spec.cycle,
        stoch_cycle: spec.stochCycle !== false, damped_cycle: spec.damped !== false, cycle_lo: spec.cycleLo ?? null, cycle_hi: spec.cycleHi ?? null,
        ar: spec.ar || 0, inputs: spec.inputs || null, exact: !!spec.exact, level, h, maxiter: maxiter(ctx) } };
    }
    if (spec.kind === 'markov') {
      return { fn: 'timeseries.markov', args: { k: spec.k || 2, order: spec.order || 0, trend: spec.trend || 'c', switching_trend: spec.swTrend !== false,
        switching_variance: !!spec.swVar, switching_ar: !!spec.swAr, starts: spec.starts ?? 5, maxiter: Math.min(500, maxiter(ctx)), level } };
    }
    if (spec.kind === 'theta') {
      return { fn: 'timeseries.theta', args: { period: spec.period || 0, deseasonalize: spec.deseasonalize !== false, use_test: spec.useTest !== false,
        method: spec.method || 'auto', theta: spec.theta || 2, use_mle: !!spec.mle, level, h } };
    }
    if (spec.kind === 'ardl') {
      return { fn: 'timeseries.ardl', args: { inputs: spec.inputs || [], maxlag: spec.maxlag || 4, maxorder: spec.maxorder ?? 4, order: spec.order || null,
        trend: spec.trend || 'c', ic: spec.ic || 'aic', glob: !!spec.glob, causal: !!spec.causal, seasonal: !!spec.seasonal, period: spec.period || 0,
        case: spec.case || null, level, h } };
    }
    if (spec.kind === 'bench') return { fn: 'timeseries.benchmark', args: { method: spec.method, s: spec.s || 0, level, h } };
    if (spec.kind === 'sma') return { fn: 'timeseries.sma', args: { width: spec.width || 3, centering: spec.centering || 'none', level, h } };
    if (spec.kind === 'avg') {
      const members = [];
      for (const id of spec.members || []) {
        const m = list.find((x) => x.id === id);
        if (!m) return { error: 'a model it averages has been removed: Fit New… or Remove Fit' };
        const c = callOf(ctx, m, h, list);
        if (c.error) return c;
        members.push({ ...c, args: { ...c.args, level }, name: specName(m) });   // the members' limits at the average's level
      }
      return { fn: 'timeseries.average', args: { members, level, h } };
    }
    return { error: `unknown model ${spec.kind}` };
  }

  /* A model fitted on the series: with values held back (holdback), on the
     rest; season, the lag of MASE's naive forecast. */
  function fitCall(ctx, base, spec, h, { holdback = 0, season = 1, list = [] } = {}) {
    const c = callOf(ctx, spec, h, list);
    if (c.error) return Promise.resolve({ error: c.error });
    return ctx.call(c.fn, { ...base, ...c.args, ...(holdback ? { holdback, season } : {}) });
  }

  const fitKey = (s) => (NEW_KINDS.has(s.kind) ? JSON.stringify(Object.keys(s).filter((k) => !UI_FLAGS.has(k)).sort().map((k) => [k, s[k]]))
    : JSON.stringify([s.kind, s.p, s.d, s.q, s.P, s.D, s.Q, s.s, s.intercept, s.constrain, s.level, s.inputs, s.method, s.multiplicative, s.error, s.trend, s.seasonal,
      ...(s.weights ? [s.weights] : []), ...(s.boxcox != null ? [s.boxcox] : [])]));

  function addModels(ctx, col, specs, { quiet = false } = {}) {
    const list = ctx.opt('models', [], scopeOf(col)).slice();
    let next = list.reduce((m, x) => Math.max(m, x.id || 0), 0) + 1;
    const seen = new Set(list.map(fitKey));
    let added = 0;
    for (const s of specs) {
      const k = fitKey(s);
      if (seen.has(k)) continue;
      seen.add(k);
      list.push({ ...s, id: next++ });
      added++;
    }
    if (!added) { if (!quiet) SM.ui.toast('That model is in the report already'); return; }
    ctx.set('models', list, scopeOf(col));
  }

  function updateModels(ctx, col, fn) {
    ctx.set('models', ctx.opt('models', [], scopeOf(col)).map((m) => fn(m) || m), scopeOf(col));
  }

  const nextGroup = (ctx, col) => ctx.opt('models', [], scopeOf(col)).reduce((m, x) => Math.max(m, x.group || 0), 0) + 1;

  /* A group's own model (ARIMA Model Group, State Space Smoothing): only the
     best by AIC (AICc for state space models) shows its report and graph
     until the boxes say otherwise. */
  function effective(list, results, held = false) {
    const best = new Map();
    list.forEach((s, i) => {
      if (!s.group) return;
      const r = results[i];
      // with values held back, the best forecasts of them (JMP sorts by the holdback RMSE)
      const v = r && !r.error ? (held ? (r.holdback || {}).rmse : s.kind === 'ets' ? r.stats.aicc : r.stats.aic) : null;
      if (v == null) return;
      const cur = best.get(s.group);
      if (!cur || v < cur.v) best.set(s.group, { v, id: s.id });
    });
    return list.map((s) => {
      const auto = s.group ? (best.get(s.group) || {}).id === s.id : true;
      return { report: s.report == null ? auto : !!s.report, graph: s.graph == null ? auto : !!s.graph };
    });
  }

  /* Every model of the series, fitted; with Forecast on Holdback on the
     values before the last h (and with Refit on All Rows again on all). */
  async function fitAll(ctx, base, list, h, holdback, season) {
    const out = await Promise.all(list.map((spec) => fitCall(ctx, base, spec, h, { holdback, season, list }).catch((e) => ({ error: e.message || String(e) }))));
    return out.map((r, i) => withOwnBand(list[i], r));
  }

  async function modelsReport(ctx, col, S, base, box, { period, h }) {
    const sc = scopeOf(col);
    const list = ctx.opt('models', [], sc);
    if (!list.length) return;
    const held = holdbackOn(ctx) && S.n - h >= 8 ? h : 0;
    const season = knownPeriod(ctx, S) || 1;
    if (holdbackOn(ctx) && !held) box.add(ctx.warn(`Forecast on Holdback: the series has ${S.n} values, too few to hold back ${h} (Number of Forecast Periods… in the red triangle); the models are fitted on every value.`));
    const results = await fitAll(ctx, base, list, h, held, season);
    const refits = held && refitOn(ctx) ? await fitAll(ctx, base, list, h, 0, season) : null;
    const M = { held, h, season, refits };
    const eff = effective(list, results, !!held);
    comparison(ctx, col, S, list, results, eff, box, M);
    // the cross-validation's outline under Model Comparison, filled last (it refits every model at every origin)
    const cv = ctx.opt('cv', null, sc);
    const cvBox = cv ? cvOutline(ctx, col, S, box) : null;
    const groups = [...new Set(list.filter((s) => s.kind === 'ets' && s.group).map((s) => s.group))];
    for (const g of groups) etsSelection(ctx, col, list, results, eff, g, box, M);
    list.forEach((spec, i) => { if (eff[i].report) modelReport(ctx, col, S, spec, results[i], box, { ...M, refit: refits ? refits[i] : null }); });
    if (cvBox) await cvReport(ctx, col, S, base, list, cvBox, { ...cv, season });
  }

  /* ---- Model Comparison -------------------------------------------------------------------------------------- */
  const CMP_COLS = [['df', 'DF', 'int'], ['variance', 'Variance'], ['aic', 'AIC'], ['sbc', 'SBC'], ['aicc', 'AICc'], ['rsquare', 'RSquare'], ['m2ll', '−2LogLH'], ['weight', 'Weights'], ['mape', 'MAPE'], ['mae', 'MAE']];
  // With Forecast on Holdback, JMP's table has the statistics of the forecasts of the held-back values (and not the training fit's)
  const HB_COLS = [['hb_rmse', 'RMSE'], ['hb_mse', 'MSE'], ['hb_mape', 'MAPE'], ['hb_mae', 'MAE'], ['hb_me', 'Mean Error'], ['hb_mase', 'MASE'], ['hb_n', 'N', 'int']];
  const HB_KEYS = { hb_rmse: 'rmse', hb_mse: 'mse', hb_mape: 'mape', hb_mae: 'mae', hb_me: 'me', hb_mase: 'mase', hb_n: 'n' };

  function comparison(ctx, col, S, list, results, eff, box, M = {}) {
    const sc = scopeOf(col);
    const held = M.held || 0;
    const cols = held ? HB_COLS : CMP_COLS;
    const setAll = (patch) => updateModels(ctx, col, (m) => ({ ...m, ...patch }));
    const fitted = list.filter((spec, i) => results[i] && !results[i].error);
    const ob = ctx.outline('Model Comparison', { parent: box, key: `${sc}:cmp`, info: 'p:timeseries:comparison', menu: () => [
      { label: 'Remove All Models', action: () => ctx.set('models', [], sc) },
      { label: 'Remove Unselected', action: () => ctx.set('models', list.filter((m, i) => eff[i].report), sc) },
      { label: 'Remove Selected', action: () => ctx.set('models', list.filter((m, i) => !eff[i].report), sc) },
      { separator: true },
      { label: 'Show All Reports', action: () => setAll({ report: true }) },
      { label: 'Hide All Reports', action: () => setAll({ report: false }) },
      { label: 'Show All Graphs', action: () => setAll({ graph: true }) },
      { label: 'Hide All Graphs', action: () => setAll({ graph: false }) },
      { separator: true },
      { label: 'Forecast on Holdback', checked: holdbackOn(ctx), action: () => ctx.set('holdback', !holdbackOn(ctx)) },
      { label: 'Refit on All Rows', checked: refitOn(ctx), disabled: !holdbackOn(ctx), title: 'With Forecast on Holdback: every model fitted again on all the values, for the forecasts after the end',
        action: () => ctx.set('refit', !ctx.opt('refit', false)) },
      { label: 'Averaged Forecast…', disabled: averageable(list).length < 2, action: () => averageDialog(ctx, col, S, list) },
      { label: 'Rolling-Origin Cross-Validation…', disabled: !fitted.length, action: () => cvDialog(ctx, col, S) },
      { separator: true },
      { label: 'Combine and Save Forecasts from Models', action: () => combineForecasts(ctx, col, S, list, results, M) },
    ] });
    const aics = results.map((r) => (r && !r.error ? r.stats.aic : null)).filter(Number.isFinite);
    const best = aics.length ? Math.min(...aics) : null;
    const tot = aics.reduce((s, a) => s + Math.exp(-0.5 * (a - best)), 0);
    const rows = list.map((spec, i) => {
      const r = results[i];
      const st = r && !r.error ? r.stats : {};
      const hb = r && !r.error && r.holdback ? r.holdback : {};
      return { spec, i, name: r && r.name ? r.name : specName(spec), error: r && r.error, ...st, weight: Number.isFinite(st.aic) && tot > 0 ? Math.exp(-0.5 * (st.aic - best)) / tot : null,
        ...Object.fromEntries(Object.entries(HB_KEYS).map(([k, v]) => [k, hb[v] ?? null])) };
    });
    let sortKey = held ? 'hb_rmse' : 'aic', dir = 1;
    const tbody = el('tbody');
    const head = el('tr', null, el('th', { class: 'sm-l', text: 'Report' }), el('th', { class: 'sm-l', text: 'Graph' }), el('th', { class: 'sm-l', text: 'Model' }));
    const fill = () => {
      const sorted = rows.slice().sort((a, b) => {
        const x = a[sortKey], y = b[sortKey];
        if (x == null || !Number.isFinite(x)) return 1;
        if (y == null || !Number.isFinite(y)) return -1;
        return (x - y) * dir;
      });
      tbody.replaceChildren(...sorted.map((row) => {
        const box1 = el('input', { type: 'checkbox', 'aria-label': `Report: ${row.name}` });
        box1.checked = eff[row.i].report;
        box1.addEventListener('change', () => updateModels(ctx, col, (m) => (m.id === row.spec.id ? { ...m, report: box1.checked } : null)));
        const box2 = el('input', { type: 'checkbox', 'aria-label': `Graph: ${row.name}` });
        box2.checked = eff[row.i].graph;
        box2.addEventListener('change', () => updateModels(ctx, col, (m) => (m.id === row.spec.id ? { ...m, graph: box2.checked } : null)));
        const tr = el('tr', { dataset: { model: String(row.spec.id) } },
          el('td', { class: 'sm-l' }, box1), el('td', { class: 'sm-l' }, box2),
          el('td', { class: 'sm-l sm-ts-name' }, el('span', { class: 'sm-ts-swatch', style: { background: colorOf(row.spec.id) } }), row.name));
        for (const [key, , f] of cols) tr.append(el('td', { text: row.error && (key === 'df' || key === 'hb_n') ? '' : SM.report.cellText(row[key], f || 'num') }));
        if (row.error) tr.append(el('td', { class: 'sm-l sm-ts-err', text: row.error }));
        return tr;
      }));
    };
    for (const [key, label] of cols) {
      const th = el('th', { text: label, scope: 'col', class: 'sm-ts-sort' });
      if (key === sortKey) th.setAttribute('aria-sort', 'ascending');
      th.addEventListener('click', () => { if (sortKey === key) dir = -dir; else { sortKey = key; dir = 1; } head.querySelectorAll('th').forEach((x) => x.removeAttribute('aria-sort')); th.setAttribute('aria-sort', dir > 0 ? 'ascending' : 'descending'); fill(); });
      head.append(th);
    }
    fill();
    const tbl = el('table', { class: 'sm-rt sm-ts-cmp' }, el('thead', null, head), tbody);
    tbl._rt = { columns: [{ key: 'name', label: 'Model', fmt: 'text' }, ...cols.map(([key, label, f]) => ({ key, label, fmt: f || 'num' }))], rows };
    tbl.addEventListener('contextmenu', (ev) => {
      ev.preventDefault();
      SM.ui.menu([
        { label: 'Copy Table', action: () => SM.report.copyText(SM.report.rtText(tbl._rt)) },
        { label: 'Make into Data Table', action: () => SM.app.addTable(SM.report.tableFromRT(tbl._rt, `${col.name} model comparison`)) },
      ], { x: ev.clientX, y: ev.clientY });
    });
    ob.add(el('div', { class: 'sm-ts-scroll' }, tbl));
    const kinds = new Set(list.map((s) => s.kind));
    if (held) {
      const nFit = S.n - held;
      ob.add(ctx.note(`Forecast on Holdback: every model is fitted on the first ${nFit} values and forecasts the last ${held}, from ${tLabel(S, S.t[nFit])} to ${tLabel(S, S.t[S.n - 1])}. `
        + 'The statistics are those of these forecast errors (actual − forecast): RMSE, MSE, MAPE, MAE, the mean error, and MASE, the MAE over the training values\' in-sample MAE of the '
        + `${M.season > 1 ? `seasonal naive forecast (lag ${M.season})` : 'naive forecast'} (Hyndman and Koehler 2006). They compare across model classes, which the AICs do not; `
        + 'sorted by RMSE, as JMP sorts them; click a heading to sort. Each model\'s report keeps its training fit statistics.'));
      ob.add(holdbackCode(ctx, col, list, results));
    } else {
      if (kinds.has('ets') && kinds.size > 1) ob.add(ctx.warn('Caution: the state space smoothing models\' likelihood is not that of the ARIMA and smoothing models, so their AIC and SBC do not compare; compare on MAPE and MAE, or within each class (as JMP cautions), or with Forecast on Holdback.'));
      else if (kinds.has('smooth') && kinds.has('arima')) ob.add(ctx.note('The smoothing models\' likelihood is that of their one-step errors given the estimated starting states; the ARIMA models\' is the exact likelihood. Their AICs are close relatives, not the same quantity.'));
      const own = [kinds.has('uc') && 'the structural models\' leaves out the diffuse start', kinds.has('markov') && 'the regime-switching models\' is a mixture over the regimes (with an AR part, conditional on its first observations)',
        kinds.has('ardl') && 'the ARDL models\' is conditional on the lags\' starting values', kinds.has('theta') && 'the Theta model\'s is that of its one-step errors',
        (kinds.has('bench') || kinds.has('sma')) && 'the benchmarks\' and moving averages\' are those of their one-step errors, with nothing (Drift: the drift) estimated'].filter(Boolean);
      if (own.length && kinds.size > 1) ob.add(ctx.note(`Across classes the likelihoods differ in detail: ${own.join('; ')}. Their AICs are close relatives, not the same quantity; MAPE and MAE compare directly.`));
      if (kinds.has('avg')) ob.add(ctx.note('An averaged forecast has no likelihood, so no AIC: compare it on MAPE and MAE, or with Forecast on Holdback.'));
      ob.add(ctx.note('Sorted by AIC; click a heading to sort. Weights are AIC weights, exp(−ΔAIC/2) normalised. Report shows a model\'s report, Graph puts it on the plots below. AIC, SBC and AICc count the fitted parameters as JMP does (not the variance).'));
    }
    // the model plots: forecasts, and the residual autocorrelations
    const shown = list.map((s, i) => ({ s, r: results[i], on: eff[i].graph })).filter((x) => x.on && x.r && !x.r.error);
    if (!shown.length) return;
    const title = `${col.name} model comparison forecasts${held ? ' on the holdback' : ''}`;
    ob.add(...comparisonPlot(ctx, col, S, shown, title, held));
    if (M.refits) {
      const again = list.map((s, i) => ({ s, r: M.refits[i], on: eff[i].graph })).filter((x) => x.on && x.r && !x.r.error);
      if (again.length) {
        const rf = ctx.outline('Refit on All Rows', { parent: ob, key: `${sc}:cmp:refit`, info: 'p:timeseries:holdback' });
        rf.add(...comparisonPlot(ctx, col, S, again, `${col.name} model comparison forecasts, refit on all rows`, 0),
          ctx.note(`Every model fitted again on all ${S.n} values, and its forecasts of the ${M.h} periods after the end, with ${fmt(100 * (again[0].s.level || 0.95))}% prediction intervals.`));
      }
    }
    const acfOver = (key, label) => {
      const tr = [], used = [];
      let n = 0;
      for (const x of shown) {
        const { s, r } = x;
        const D = r.resid_diag;
        if (!D || D.error) continue;
        n = Math.max(n, D.n);
        used.push(x);
        tr.push({ type: 'scatter', mode: 'lines+markers', x: D[key].lag.slice(1), y: D[key].r.slice(1), name: ptext(r.name), line: { color: colorOf(s.id), width: 1.2 }, marker: { size: 4, color: colorOf(s.id) }, hovertemplate: `${ptext(r.name)}: lag %{x}, %{y:.4f}<extra></extra>` });
      }
      if (!tr.length) return null;
      const b = 2 / Math.sqrt(n);
      const t = `${col.name} residual ${label.toLowerCase()}`;
      const w = plotWidth(ctx, 320);
      return withCode(ctx.plot(tr, { xaxis: { title: { text: 'Lag' } }, yaxis: { title: { text: label }, range: [-1, 1] },
        shapes: [b, -b].map((v) => ({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: v, y1: v, line: { color: '#2f6ec7', width: 1, dash: 'dash' } })) },
      { width: w, height: 220, title: t }), comparisonCode(ctx, col, used, [w, 220], key === 'acf' ? 'racf' : 'rpacf', { label, title: t }));
    };
    ob.add(ctx.row(acfOver('acf', 'Autocorrelation'), acfOver('pacf', 'Partial Autocorrelation')));
  }

  /* Model Comparison's forecast plot of the models shown (their Graph box),
     with its code: with values held back, the held-back span shaded. */
  function comparisonPlot(ctx, col, S, shown, title, held) {
    const traces = [{ ...seriesTrace(S, S.values, col.name, { points: true, lines: false }), showlegend: false }];
    for (const { s, r } of shown) traces.push(...forecastTraces(S, r, colorOf(s.id), { pi: true, name: r.name, legend: true, oneStepPI: false }));
    const size = [plotWidth(ctx, 640), 320 + 18 * Math.ceil(shown.length / 2)];
    const plot = ctx.plot(traces, { xaxis: xAxis(S), yaxis: { title: { text: ptext(col.name) } }, showlegend: true, legend: { orientation: 'h', y: -0.22 },
      shapes: fitShapes(S, S.n - held) }, { width: size[0], height: size[1], title });
    return [plot, comparisonCode(ctx, col, shown, size, 'forecast', { title, held })];
  }

  /* Model Comparison's plots as code: the series once, then each model whose
     Graph box is checked, fitted as in its report and drawn in its colour
     (its fragment, plot_frag: the fit, the draw and the residual
     correlations), then the lines and labels of the plot. */
  function comparisonCode(ctx, col, shown, size, kind, { label = null, title, held = 0 }) {
    if (!shown.length || shown.some((x) => !x.r.plot_frag)) return null;
    const imports = new Set(['import matplotlib.pyplot as plt']);
    for (const { r } of shown) for (const i of r.plot_frag.imports || []) imports.add(i);
    if (kind !== 'forecast') imports.add('from statsmodels.tsa.stattools import acf, levinson_durbin');
    const forecast = kind === 'forecast';
    const data = held ? 'ax.plot(t_all, y_all, color="#2f6690", linestyle="", marker="o", markersize=3.6)   # the data, the held-back values too'
      : 'ax.plot(t, y, color="#2f6690", linestyle="", marker="o", markersize=3.6)   # the data';
    const L = [SM.report.codeHead(ctx.table.name, [...imports]), ...shown[0].r.plot_frag.series, '', recipe([{ set: 'size' }], { size }),
      'fig, ax = plt.subplots(figsize=size, layout="constrained")',
      forecast ? data : 'nmax = 0   # the most residuals of any model, for the ±2/√n lines'];
    for (const { s, r } of shown) {
      const flags = { pi: true, onestep: false, legend: true, smpi: s.kind === 'theta' && !!s.smpi };
      L.push('', `# ${r.name}, fitted as in its report`, recipe(r.plot_frag.fit, { flags }), recipe([{ set: 'color' }], { color: colorOf(s.id) }),
        recipe(forecast ? r.plot_frag.draw : r.plot_frag[kind], { flags }));
    }
    L.push('');
    if (forecast) {
      L.push(`ax.axvline(t[-1], color="#786b5d", linewidth=0.72, linestyle=":")   # the end of the ${held ? 'values the models are fitted to' : 'data'}`);
      if (held) L.push('ax.axvspan(t[-1], t_hold[-1], color="#786b5d", alpha=0.12, linewidth=0)   # the held-back values');
      L.push(`ax.set_xlabel(${J(ctx.name('time') || 'Row')})`, `ax.set_ylabel(${J(col.name)})`, `ax.set_title(${J(title)})`,
        'fig.legend(loc="outside lower center", ncols=2, frameon=False, fontsize=8)   # the models');
    } else {
      L.push('b = 2 / np.sqrt(nmax)', 'for v in (b, -b):   # ±2/√n', '    ax.axhline(v, color="#2f6ec7", linewidth=0.72, linestyle="--")',
        'ax.set_ylim(-1, 1)', 'ax.set_xlabel("Lag")', `ax.set_ylabel(${J(label)})`, `ax.set_title(${J(title)})`);
    }
    L.push('plt.show()');
    return ctx.code(L.join('\n'));
  }

  /* The holdback statistics of Model Comparison as code: each model fitted
     on the training values as in its report, its forecasts of the held-back
     ones, and their errors' statistics (the fragments' hb_def and hb). */
  function holdbackCode(ctx, col, list, results) {
    const ok = list.map((s, i) => results[i]).filter((r) => r && !r.error && r.plot_frag && r.plot_frag.hb);
    if (!ok.length) return null;
    const imports = new Set();
    for (const r of ok) for (const i of r.plot_frag.imports || []) imports.add(i);
    const L = [SM.report.codeHead(ctx.table.name, [...imports]), ...ok[0].plot_frag.series, ...ok[0].plot_frag.hb_def, 'holdback = {}   # each model\'s forecasts of the held-back values'];
    for (const r of ok) L.push('', `# ${r.name}, fitted as in its report`, recipe(r.plot_frag.fit, { flags: {} }), `holdback[${J(r.name)}] = ${r.plot_frag.hb}`);
    L.push('', 'print(pd.DataFrame(holdback).T.sort_values("RMSE").to_string())   # Model Comparison, sorted by RMSE');
    return ctx.code(L.join('\n'));
  }

  /* JMP's model names, as the backend gives them (for a model whose fit failed). */
  function specName(s) {
    if (s.kind === 'arima') {
      const { p = 0, d = 0, q = 0, P = 0, D = 0, Q = 0 } = s;
      let base;
      if (P || D || Q) base = `Seasonal ARIMA(${p}, ${d}, ${q})(${P}, ${D}, ${Q})${s.s}`;
      else if (!d) base = p && !q ? `AR(${p})` : q && !p ? `MA(${q})` : p && q ? `ARMA(${p}, ${q})` : 'ARIMA(0, 0, 0)';
      else base = !p && !q ? `I(${d})` : p && !q ? `ARI(${p}, ${d})` : q && !p ? `IMA(${d}, ${q})` : `ARIMA(${p}, ${d}, ${q})`;
      if (s.inputs && s.inputs.length) base = `Transfer Function ${base} with ${s.inputs.map((x) => x.name).join(', ')}`;
      return s.intercept === false ? `${base} No Intercept` : base;
    }
    if (s.kind === 'smooth') {
      const label = s.method === 'winters' && s.multiplicative ? 'Winters Method (Multiplicative)' : s.method === 'winters' ? 'Winters Method (Additive)' : SMOOTH_LABEL[s.method] || s.method;
      const base = s.method === 'seasonal' || s.method === 'winters' ? `${label}(${s.s})` : label;
      const extra = Object.entries(s.weights || {}).map(([k, w]) => (w.fix != null ? `${WEIGHT_SYM[k]} = ${fmt(w.fix)}` : `${WEIGHT_SYM[k]} in [${fmt(w.lo ?? 0)}, ${fmt(w.hi ?? 1)}]`));
      if (s.boxcox != null) extra.push(`Box-Cox λ = ${fmt(s.boxcox)}`);
      return extra.length ? `${base}, ${extra.join(', ')}` : base;
    }
    if (s.kind === 'bench') return s.method === 'snaive' ? `Seasonal Naive(${s.s})` : s.method === 'drift' ? 'Drift' : 'Naive';
    if (s.kind === 'sma') return `Simple Moving Average(${s.width}${s.centering === 'centered' ? ', centered' : s.centering === 'double' ? ', centered and double smoothed' : ''})`;
    if (s.kind === 'avg') return `Averaged Forecast of ${(s.members || []).length} models`;
    if (s.kind === 'ets') return `ETS(${s.error === 'mul' ? 'M' : 'A'},${s.trend || 'N'},${s.seasonal || 'N'})`;
    if (s.kind === 'uc') return `Structural: ${s.trend === 'irregular' ? 'no trend' : s.trend}${s.seasonal ? ` + seasonal(${s.seasonal})` : ''}${s.freqPeriod ? ` + trigonometric seasonal(${s.freqPeriod})` : ''}${s.cycle ? ' + cycle' : ''}${s.ar ? ` + AR(${s.ar})` : ''}${(s.inputs || []).map((x) => ` + ${x}`).join('')}`;
    if (s.kind === 'markov') return `Regime Switching: ${s.k || 2} regimes${s.order ? `, AR(${s.order})` : ''}`;
    if (s.kind === 'theta') return `Theta Model (θ = ${fmt(s.theta || 2)})`;
    if (s.kind === 'ardl') return `ARDL with ${(s.inputs || []).join(', ')}`;
    return s.kind;
  }

  /* One model's forecast traces: the one-step-ahead predictions, the
     forecasts, and the prediction interval, in-sample lines that go on into
     a band over the forecast periods. */
  function forecastTraces(S, r, color, { pi = true, name: raw, legend = false, oneStepPI = true } = {}) {
    const name = ptext(raw);
    // the slots the model is fitted to: all of them, or those before the held-back values
    const n = Math.min(r.n || S.t.length, S.t.length);
    const xs = S.x.slice(0, n);
    const fc = r.forecast || { t: [] };
    const last = n - 1;
    const ft = fx(S, fc.t);
    const tr = [{ type: 'scatter', mode: 'lines', x: xs, y: r.fitted, name: legend ? name : 'Predicted', legendgroup: name, showlegend: legend, line: { color, width: 1.3 }, hovertemplate: `${name}: %{y:.5g}<extra></extra>` }];
    if (fc.t.length) {
      const x0 = S.x[last], y0 = r.fitted[last] != null ? r.fitted[last] : S.values[last];
      if (pi) {
        const lo0 = r.fit_lo[last] != null ? r.fit_lo[last] : fc.lower[0], hi0 = r.fit_hi[last] != null ? r.fit_hi[last] : fc.upper[0];
        tr.push({ type: 'scatter', mode: 'lines', x: [x0, ...ft], y: [hi0, ...fc.upper], line: { color: rgba(color, 0.6), width: 1 }, legendgroup: name, showlegend: false, hoverinfo: 'skip', name: `${name} upper` },
          { type: 'scatter', mode: 'lines', x: [x0, ...ft], y: [lo0, ...fc.lower], line: { color: rgba(color, 0.6), width: 1 }, fill: 'tonexty', fillcolor: rgba(color, 0.13), legendgroup: name, showlegend: false, hoverinfo: 'skip', name: `${name} lower` });
      }
      tr.push({ type: 'scatter', mode: 'lines+markers', x: [x0, ...ft], y: [y0, ...fc.mean], line: { color, width: 2 }, marker: { size: 3, color }, legendgroup: name, showlegend: false, name: `${name} forecast`,
        hovertemplate: `${name} forecast: %{y:.5g}<extra></extra>` });
    }
    if (pi && oneStepPI) {
      tr.push({ type: 'scatter', mode: 'lines', x: xs, y: r.fit_hi, line: { color: rgba(color, 0.45), width: 0.8, dash: 'dot' }, legendgroup: name, showlegend: false, hoverinfo: 'skip', name: `${name} upper (one step)` },
        { type: 'scatter', mode: 'lines', x: xs, y: r.fit_lo, line: { color: rgba(color, 0.45), width: 0.8, dash: 'dot' }, legendgroup: name, showlegend: false, hoverinfo: 'skip', name: `${name} lower (one step)` });
    }
    return tr;
  }

  /* ---- State Space Smoothing model selection ------------------------------------------------------------------------ */
  function etsSelection(ctx, col, list, results, eff, group, box, M = {}) {
    const sc = scopeOf(col);
    const held = M.held || 0;
    const rows = [];
    list.forEach((s, i) => {
      if (s.group !== group || s.kind !== 'ets') return;
      const r = results[i];
      const hb = r && !r.error && r.holdback ? r.holdback : {};
      rows.push({ id: s.id, i, name: r && r.name ? r.name.replace('State Space Smoothing ', '') : specName(s), error: r && r.error, nparm: r && r.nparm, m2ll: r && r.stats ? r.stats.m2ll : null,
        aic: r && r.stats ? r.stats.aic : null, aicc: r && r.stats ? r.stats.aicc : null, bic: r && r.stats ? r.stats.sbc : null, mape: r && r.stats ? r.stats.mape : null,
        hb_rmse: hb.rmse ?? null, hb_mape: hb.mape ?? null });
    });
    // the best: by AICc, or with values held back by the RMSE of their forecasts (as the Report boxes pick it)
    const key = held ? 'hb_rmse' : 'aicc';
    const ok = rows.filter((r) => Number.isFinite(r.aicc));
    const best = ok.length ? Math.min(...ok.map((r) => r.aicc)) : null;
    const tot = ok.reduce((s, r) => s + Math.exp(-0.5 * (r.aicc - best)), 0);
    const bestKey = Math.min(...rows.map((r) => (Number.isFinite(r[key]) ? r[key] : Infinity)));
    for (const r of rows) { r.delta = Number.isFinite(r.aicc) ? r.aicc - best : null; r.weight = Number.isFinite(r.aicc) && tot ? Math.exp(-0.5 * r.delta) / tot : null; r.mark = r[key] === bestKey && Number.isFinite(bestKey) ? '★ best' : r.error ? r.error : ''; }
    rows.sort((a, b) => (a[key] ?? Infinity) - (b[key] ?? Infinity));
    const ob = ctx.outline(`State Space Smoothing Model Selection ${group}`, { parent: box, key: `${sc}:etsgroup:${group}`, info: 'p:timeseries:ets', menu: () => [
      { label: 'Remove These Models', action: () => ctx.set('models', ctx.opt('models', [], sc).filter((m) => m.group !== group), sc) },
    ] });
    const hbCols = held ? [{ key: 'hb_rmse', label: 'Holdback RMSE' }, { key: 'hb_mape', label: 'Holdback MAPE' }] : [];
    ob.add(ctx.rt({ columns: [{ key: 'name', label: 'Model', fmt: 'text' }, { key: 'nparm', label: 'Nparm', fmt: 'int' }, { key: 'm2ll', label: '−2LogLikelihood' }, { key: 'aic', label: 'AIC' },
      { key: 'aicc', label: 'AICc' }, { key: 'delta', label: 'ΔAICc' }, { key: 'weight', label: 'AICc Weight' }, { key: 'bic', label: 'BIC' }, { key: 'mape', label: 'MAPE' }, ...hbCols, { key: 'mark', label: '', fmt: 'text' }], rows },
    { sortable: false, name: 'State space smoothing models', onRow: (row) => updateModels(ctx, col, (m) => (m.id === row.id ? { ...m, report: true, graph: true } : null)) }),
    ctx.note(`ETS(error, trend, seasonal) models of Hyndman et al. (2008) fitted by maximum likelihood (statsmodels' ETSModel), best first by ${held ? 'the RMSE of their forecasts of the held-back values (Forecast on Holdback); AIC, AICc and BIC are those of the training values' : 'AICc'}. The best one shows its report; click a line to show another.`));
  }

  /* ---- a model's report ---------------------------------------------------------------------------------------------- */
  const PARAM_COLS = {
    arima: (seasonal) => [{ key: 'term', label: 'Term', fmt: 'text' }, ...(seasonal ? [{ key: 'factor', label: 'Factor', fmt: 'text' }] : []), { key: 'lag', label: 'Lag', fmt: 'int' },
      { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }],
    smooth: () => [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }],
    ets: () => [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'lower', label: 'Lower 95%' }, { key: 'upper', label: 'Upper 95%' }],
    uc: () => [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'z', label: 'z Ratio' }, { key: 'p', label: 'Prob>|z|', fmt: 'p' }],
    markov: () => [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'regime', label: 'Regime', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'z', label: 'z Ratio' }, { key: 'p', label: 'Prob>|z|', fmt: 'p' }],
    theta: () => [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }],
    ardl: () => [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }],
  };
  const MODEL_INFO = { ets: 'p:timeseries:ets', smooth: 'p:timeseries:smoothing', uc: 'p:timeseries:structural', markov: 'p:timeseries:regime', theta: 'p:timeseries:theta',
    ardl: 'p:timeseries:ardl', bench: 'p:timeseries:benchmarks', sma: 'p:timeseries:sma', avg: 'p:timeseries:average' };
  // what a model without parameters says under Parameter Estimates
  const NO_PARAMS = { sma: 'No parameters: the width of the moving average is chosen, not estimated.', avg: 'No parameters of its own: the mean of the models it averages.',
    bench: 'No parameters besides the variance: the benchmark is the data itself.' };

  function modelMenu(ctx, col, S, spec, r, M = {}) {
    const flag = (k, d = true) => (spec[k] == null ? d : !!spec[k]);
    const up = (patch) => updateModels(ctx, col, (m) => (m.id === spec.id ? { ...m, ...patch } : null));
    const own = [];
    if (spec.kind === 'uc') {
      own.push({ label: 'Components', checked: flag('comps'), action: () => up({ comps: !flag('comps') }) },
        { label: 'Save Components', disabled: !r || !!r.error, action: () => saveComponents(ctx, col, S, r) });
    } else if (spec.kind === 'markov') {
      own.push({ label: 'Filtered Probabilities', checked: flag('fprob', false), action: () => up({ fprob: !flag('fprob', false) }) },
        { label: 'Save Regime Probabilities', disabled: !r || !!r.error, action: () => saveRegimes(ctx, col, S, r) });
    } else if (spec.kind === 'theta') {
      own.push({ label: 'statsmodels\' Prediction Intervals', checked: flag('smpi', false), action: () => up({ smpi: !flag('smpi', false) }) });
    } else if (spec.kind === 'sma') {
      own.push({ label: 'Smoothed Series', checked: flag('smoothed'), action: () => up({ smoothed: !flag('smoothed') }) },
        { label: 'Save Moving Average', disabled: !r || !!r.error, action: () => saveSlots(ctx, S, `${col.name} ${r.name}`, r.smoothed) });
    }
    const pf = predictionFormula(ctx, col, S, spec, r);
    return [
      { label: 'Show Points', checked: flag('points'), action: () => up({ points: !flag('points') }) },
      { label: 'Show Prediction Interval', checked: flag('pi'), action: () => up({ pi: !flag('pi') }) },
      { label: 'Save Columns', disabled: !r || !!r.error, action: () => saveModelTable(ctx, col, S, r, M.refit) },
      ...(pf ? [{ label: 'Save Prediction Formula', disabled: !!pf.why, title: pf.why || undefined, action: () => {
        try { ctx.saveFormula(`Pred Formula ${col.name} ${r.name}`, pf.expr, { notes: `${r.name}: the one-step-ahead prediction of ${col.name}, from the rows before (${pf.what})` }); } catch (e) { SM.ui.toast(e.message, { error: true }); }
      } }] : []),
      ...own,
      { label: 'Residual Statistics', submenu: () => [
        { label: 'Autocorrelation', checked: flag('racf'), action: () => up({ racf: !flag('racf') }) },
        { label: 'Partial Autocorrelation', checked: flag('rpacf'), action: () => up({ rpacf: !flag('rpacf') }) },
        { label: 'Variogram', checked: flag('rvario', false), action: () => up({ rvario: !flag('rvario', false) }) },
        { label: 'AR Coefficients', checked: flag('rar', false), action: () => up({ rar: !flag('rar', false) }) },
        { label: 'Runs Test', checked: flag('rruns', false), action: () => up({ rruns: !flag('rruns', false) }) },
      ] },
      { separator: true },
      { label: 'Fit New…', action: () => fitNew(ctx, col, S, spec) },
      { label: 'Remove Fit', action: () => ctx.set('models', ctx.opt('models', [], scopeOf(col)).filter((m) => m.id !== spec.id), scopeOf(col)) },
    ];
  }

  /* The one-step-ahead prediction of a benchmark or a moving average as a
     formula (Save Prediction Formula): Lag() of the rows before, so the
     table's rows must be the series' slots one after another (sorted by the
     Time ID, no time point without its row, no By group across the table). */
  function predictionFormula(ctx, col, S, spec, r) {
    if (!r || r.error || !(spec.kind === 'bench' || spec.kind === 'sma')) return null;
    const ref = SM.formula.refText(col.name);
    const lag = (k) => `Lag(${ref}, ${k})`;
    let expr, what;
    if (spec.kind === 'bench' && spec.method === 'naive') { expr = lag(1); what = 'the value before'; }
    else if (spec.kind === 'bench' && spec.method === 'snaive') { expr = lag(spec.s); what = `the value ${spec.s} rows before`; }
    else if (spec.kind === 'bench') { const b = r.drift; expr = `${lag(1)} ${b < 0 ? '-' : '+'} ${String(Math.abs(b))}`; what = 'the value before plus the drift'; }
    else { const w = spec.width || 1; expr = w === 1 ? lag(1) : `(${Array.from({ length: w }, (_, j) => lag(j + 1)).join(' + ')}) / ${w}`; what = `the mean of the ${w} values before`; }
    const rows = S.rows || [];
    let why = null;
    if ((ctx.where || []).length) why = 'Lag() takes the rows before in the whole table, across the By groups';
    else if (rows.some((x, i) => x == null || (i && x !== rows[i - 1] + 1))) why = 'the table\'s rows are not the series\' time points one after another (sort the table by its Time ID, and give every time point a row)';
    return { expr, what, why };
  }

  /* A model's forecast graph: the data, its one-step-ahead predictions and
     forecasts; with values held back, their span shaded. */
  function forecastPlot(ctx, col, S, spec, r, name, title, code) {
    const flag = (k, d = true) => (spec[k] == null ? d : !!spec[k]);
    const color = colorOf(spec.id);
    const traces = [];
    if (flag('points')) traces.push({ ...seriesTrace(S, S.values, col.name, { points: true, lines: false }), showlegend: false });
    traces.push(...forecastTraces(S, r, color, { pi: flag('pi'), name }));
    const wide = plotWidth(ctx, 620);
    const plot = ctx.plot(traces, { xaxis: xAxis(S), yaxis: { title: { text: ptext(col.name) } }, shapes: fitShapes(S, Math.min(r.n || S.n, S.n)) }, { width: wide, height: 300, title });
    if (!code || !code.length) return [plot, null];
    // the recipe titles the graph "<name> forecast"; the refit's graph has a title of its own
    const text = recipe(code, { flags: { points: flag('points'), pi: flag('pi'), onestep: true, smpi: flag('smpi', false) }, size: [wide, 300], color })
      .replace(`ax.set_title(${pyJ(`${name} forecast`)})`, `ax.set_title(${J(title)})`);
    return [plot, ctx.code(text)];
  }

  function modelReport(ctx, col, S, spec, r, box, M = {}) {
    const sc = scopeOf(col);
    const color = colorOf(spec.id);
    const name = r && r.name ? r.name : specName(spec);
    const info = MODEL_INFO[spec.kind] || (spec.inputs ? 'p:timeseries:transfer' : 'p:timeseries:arima');
    const ob = ctx.outline(`Model: ${name}`, { parent: box, key: `${sc}:model:${spec.id}`, info, menu: () => modelMenu(ctx, col, S, spec, r, M) });
    ob.el.classList.add('sm-ts-model');
    ob.el.style.setProperty('--ts-model-color', color);
    if (!r || r.error) { ob.add(ctx.warn(`${name}: ${r ? r.error : 'no result'}`)); return; }
    const flag = (k, d = true) => (spec[k] == null ? d : !!spec[k]);
    const nFit = Math.min(r.n || S.n, S.n);
    const xs = S.x.slice(0, nFit);
    const sum = ctx.outline('Model Summary', { parent: ob, key: `${sc}:model:${spec.id}:sum` });
    sum.add(ctx.kv(r.summary.map(([label, v, f]) => [label, v, f || 'num'])));
    const pe = ctx.outline('Parameter Estimates', { parent: ob, key: `${sc}:model:${spec.id}:pe` });
    const seasonal = spec.kind === 'arima' && (spec.P || spec.D || spec.Q);
    let pcols = PARAM_COLS[r.params.columns](seasonal);
    if (spec.kind === 'smooth' && spec.weights) pcols = [...pcols, { key: 'constraint', label: 'Constraint', fmt: 'text' }];
    if (r.params.rows.length) pe.add(ctx.rt({ columns: pcols, rows: r.params.rows }, { sortable: false, name: `${name} parameter estimates` }));
    else pe.add(ctx.note(NO_PARAMS[spec.kind] || 'No parameters besides the variance.'));
    if (r.constant) pe.add(ctx.kv([['Constant Estimate', r.constant.estimate], ['Mu', r.constant.mu]]));
    ob.add(ctx.row(sum.el, pe.el));
    for (const n of r.notes || []) ob.add(ctx.note(n));
    // the forecast (a Markov switching model has none: its one-step-ahead predictions)
    const pc = r.plot_code || {};
    const opts = (size) => ({ flags: { points: flag('points'), pi: flag('pi'), onestep: true, smpi: flag('smpi', false) }, size, color });
    const wide = plotWidth(ctx, 620);
    const fcOb = ctx.outline(spec.kind === 'markov' ? 'One-Step-Ahead Predictions' : 'Forecast', { parent: ob, key: `${sc}:model:${spec.id}:fc` });
    fcOb.add(...forecastPlot(ctx, col, S, spec, r, name, `${name} forecast`, pc.forecast));
    const fc = r.forecast;
    const hb = r.holdback;
    if (hb && fc && fc.t.length) {
      fcOb.add(ctx.note(`Forecast on Holdback: the model is fitted on the first ${nFit} values and forecasts the last ${fc.t.length}, from ${tLabel(S, fc.t[0])} to ${tLabel(S, fc.t[fc.t.length - 1])} (shaded), with ${fmt(100 * r.level)}% prediction intervals; to the left of the dotted line the one-step-ahead forecasts of the values it is fitted to.`));
      const hs = ctx.outline('Holdback Statistics', { parent: fcOb, key: `${sc}:model:${spec.id}:hb`, info: 'p:timeseries:holdback' });
      hs.add(ctx.kv([['RMSE', hb.rmse], ['MSE', hb.mse], ['MAPE', hb.mape], ['MAE', hb.mae], ['Mean Error', hb.me], ['MASE', hb.mase], ['N', hb.n, 'int']]),
        ctx.note(`The errors actual − forecast of the ${hb.n} held-back values present; MASE divides the MAE by ${fmt(hb.scale)}, the training values' in-sample MAE of the ${hb.lag > 1 ? `seasonal naive forecast (lag ${hb.lag})` : 'naive forecast'}.`));
    } else if (fc && fc.t.length) fcOb.add(ctx.note(`${fc.t.length} periods ahead, from ${tLabel(S, fc.t[0])} to ${tLabel(S, fc.t[fc.t.length - 1])}, with ${fmt(100 * r.level)}% prediction intervals; to the left of the dotted line the one-step-ahead forecasts.`));
    else if (hb) fcOb.add(ctx.note('This model makes no forecasts: no holdback statistics.'));
    // Refit on All Rows: the model fitted again on every value, and its forecasts after the end
    const rf = M.refit;
    if (rf) {
      const ro = ctx.outline('Forecast, Refit on All Rows', { parent: ob, key: `${sc}:model:${spec.id}:refit`, info: 'p:timeseries:holdback' });
      if (rf.error) ro.add(ctx.warn(rf.error));
      else {
        ro.add(...forecastPlot(ctx, col, S, spec, rf, name, `${name} forecast, refit on all rows`, (rf.plot_code || {}).forecast));
        const f2 = rf.forecast;
        if (f2 && f2.t.length) ro.add(ctx.note(`The model fitted again on all ${S.n} values: its forecasts of the ${f2.t.length} periods after the end, from ${tLabel(S, f2.t[0])} to ${tLabel(S, f2.t[f2.t.length - 1])}, with ${fmt(100 * rf.level)}% prediction intervals. Save Columns adds them after the held-back rows.`));
        ro.add(ctx.code(rf.code));
      }
    }
    // the moving average's smoothed series
    if (spec.kind === 'sma' && flag('smoothed') && r.smoothed) {
      const so = ctx.outline('Smoothed Series', { parent: ob, key: `${sc}:model:${spec.id}:smoothed`, info: 'p:timeseries:sma' });
      so.add(ctx.plot([{ ...seriesTrace(S, S.values.slice(0, nFit), col.name, { points: true, lines: false }), x: xs, rows: S.rowsLinked.slice(0, nFit), showlegend: false },
        { type: 'scatter', mode: 'lines', x: xs, y: r.smoothed, name: ptext(name), line: { color, width: 1.6 }, hovertemplate: `moving average %{y:.5g}<extra></extra>` }],
      { xaxis: xAxis(S), yaxis: { title: { text: ptext(col.name) } } }, { width: wide, height: 280, title: `${name} smoothed series` }), graphCode(ctx, pc.smoothed, opts([wide, 280])));
    }
    // the residuals
    const resOb = ctx.outline(spec.kind === 'ets' ? 'One-Step-Ahead Forecasting Errors' : 'Residuals', { parent: ob, key: `${sc}:model:${spec.id}:res` });
    resOb.add(ctx.plot([{ type: 'scatter', mode: 'markers', x: xs, y: r.resid, rows: S.rowsLinked.slice(0, nFit), name: 'Residual', marker: { size: 5, color } }],
      { xaxis: xAxis(S), yaxis: { title: { text: 'Residual' }, zeroline: true }, shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: SM.util.themeColors().muted, width: 1 } }] },
    { width: wide, height: 220, title: `${name} residuals` }), graphCode(ctx, pc.resid, opts([wide, 220])));
    resOb.add(diagnosticsBlock(ctx, r.resid_diag, { acf: flag('racf'), pacf: flag('rpacf'), variogram: flag('rvario', false), ar: flag('rar', false), residual: true, codes: pc }));
    if (r.resid_diag && r.resid_diag.model_df) resOb.add(ctx.note(`Ljung-Box on the residuals: degrees of freedom are the lag less the ${r.resid_diag.model_df} ${spec.kind === 'smooth' || spec.kind === 'theta' ? `smoothing weight${r.resid_diag.model_df > 1 ? 's' : ''}` : spec.kind === 'ardl' ? `lag${r.resid_diag.model_df > 1 ? 's' : ''} of the series` : 'ARMA parameters'}.`));
    if (flag('rruns', false)) resOb.add(runsBlock(ctx, r.resid_runs, 'Residual Runs Test', 'the residuals', pc.runs ? recipe(pc.runs) : null));
    if (spec.kind === 'uc' && flag('comps')) componentsReport(ctx, col, S, spec, r, ob);
    if (spec.kind === 'markov') regimeReport(ctx, col, S, spec, r, ob);
    if (spec.kind === 'ardl') ardlReport(ctx, col, S, spec, r, ob);
    if (spec.kind === 'ets' && r.states && Object.keys(r.states).length) {
      const cs = ctx.outline('Component States', { parent: ob, key: `${sc}:model:${spec.id}:states`, closed: true });
      const ws = plotWidth(ctx, 520);
      for (const [k, v] of Object.entries(r.states)) {
        cs.add(ctx.plot([{ type: 'scatter', mode: 'lines', x: xs, y: v, name: k, line: { color, width: 1.4 } }], { xaxis: xAxis(S), yaxis: { title: { text: k[0].toUpperCase() + k.slice(1) } } }, { width: ws, height: 180, title: `${name} ${k}` }),
          graphCode(ctx, pc.states && pc.states[k], opts([ws, 180])));
      }
    }
    if (Array.isArray(r.iterations) && r.iterations.length) {
      const it = ctx.outline('Iteration History', { parent: ob, key: `${sc}:model:${spec.id}:iter`, closed: true });
      it.add(ctx.rt({ columns: [{ key: 'iter', label: 'Iter', fmt: 'int' }, { key: 'm2ll', label: '−2LogLikelihood' }], rows: r.iterations }, { sortable: false, maxRows: 60 }),
        ctx.note(r.converged ? `Converged after ${r.n_iter} iterations (L-BFGS on the exact likelihood).` : `Did not converge within ${maxiter(ctx)} iterations: raise them with Maximum Iterations in the red triangle.`));
    } else if (spec.kind === 'arima' && r.converged === false) ob.add(ctx.warn('The fit did not converge: raise Maximum Iterations in the red triangle.'));
    ob.add(ctx.code(r.code));
  }

  /* The runs test (about the mean, the median or zero) as a table, a note and its code. */
  function runsBlock(ctx, R, caption, what, code) {
    if (!R) return null;
    if (R.error) return ctx.note(`${caption}: ${R.error}.`);
    const about = { mean: 'the mean', median: 'the median', zero: 'zero' }[R.cutoff] || R.cutoff;
    const box = el('div', { class: 'sm-ts-col' },
      ctx.kv([['Runs', R.runs, 'int'], ['Expected Runs', R.expected], ['Std Dev of Runs', R.sd], [`N At or Above ${R.cutoff === 'zero' ? 'Zero' : R.cutoff === 'median' ? 'the Median' : 'the Mean'}`, R.n_above, 'int'],
        ['N Below', R.n_below, 'int'], ['z', R.z], ['Prob > |z|', R.p, 'p']], { caption }),
      ctx.note(`The Wald-Wolfowitz runs test of randomness about ${about} (${fmt(R.value)}): ${what} in time order, each at or above it or below it; too few runs mean runs of highs and lows (positive autocorrelation), too many an alternation. z = (R − E)/SD with E = 2n₁n₂/N + 1${R.corrected ? '; below N = 50, |R − E| less 1/2 (the continuity correction of the SAS manual that statsmodels\' runstest_1samp follows)' : ''}.`));
    if (code) box.append(ctx.code(code));
    return box;
  }

  /* The Theta model's forecasts carry two bands: the IMA(1, 1) one (the
     default) and statsmodels' prediction_intervals, chosen in its red triangle. */
  function withOwnBand(spec, r) {
    if (!r || r.error || spec.kind !== 'theta' || !spec.smpi || !r.forecast || !r.forecast.sm_lower) return r;
    return { ...r, forecast: { ...r.forecast, lower: r.forecast.sm_lower, upper: r.forecast.sm_upper } };
  }

  /* ---- Structural Model: the Components ------------------------------------------------------------------------------------ */
  function componentsReport(ctx, col, S, spec, r, ob) {
    const comps = r.components || [];
    if (!comps.length) return;
    const sc = scopeOf(col);
    const color = colorOf(spec.id);
    const cp = ctx.outline('Components', { parent: ob, key: `${sc}:model:${spec.id}:comps`, info: 'p:timeseries:structural' });
    const n = comps.length;
    const gap = 0.06, hh = (1 - gap * (n - 1)) / n;
    const traces = [];
    const layout = { xaxis: xAxis(S, { anchor: n > 1 ? `y${n}` : 'y' }), margin: { l: 60, r: 12, t: 16, b: 40 }, annotations: [] };
    comps.forEach((c, i) => {
      const ax = i ? `y${i + 1}` : 'y';
      const top = 1 - i * (hh + gap);
      layout[`yaxis${i ? i + 1 : ''}`] = { domain: [Math.max(0, top - hh), top], title: { text: '' }, zeroline: !['level'].includes(c.key) };
      layout.annotations.push({ text: c.label, xref: 'paper', yref: 'paper', x: 0, y: top, xanchor: 'left', yanchor: 'bottom', showarrow: false, font: { size: 10.5 } });
      if (c.key === 'level') traces.push({ ...seriesTrace(S, S.values, col.name, { points: true, lines: false, color: SM.util.themeColors().muted }), xaxis: 'x', yaxis: ax, marker: { size: 4, color: SM.util.themeColors().muted } });
      if (c.lower) {
        traces.push({ type: 'scatter', mode: 'lines', x: S.x, y: c.upper, xaxis: 'x', yaxis: ax, line: { width: 0, color: rgba(color, 0.3) }, hoverinfo: 'skip', name: `${c.label} upper` },
          { type: 'scatter', mode: 'lines', x: S.x, y: c.lower, xaxis: 'x', yaxis: ax, line: { width: 0, color: rgba(color, 0.3) }, fill: 'tonexty', fillcolor: rgba(color, 0.18), hoverinfo: 'skip', name: `${c.label} lower` });
      }
      traces.push({ type: 'scatter', mode: 'lines', x: S.x, y: c.mean, xaxis: 'x', yaxis: ax, line: { color, width: 1.5 }, name: c.label, hovertemplate: `${c.label}: %{y:.5g}<extra></extra>` });
    });
    const size = [plotWidth(ctx, 640), Math.max(260, 125 * n + 60)];
    cp.add(ctx.plot(traces, layout, { width: size[0], height: size[1], title: `${r.name} components`, ...stacked(n) }),
      graphCode(ctx, r.plot_code && r.plot_code.components, { size, color, flags: { smpi: false } }));
    cp.add(ctx.note(`The smoothed components (Kalman smoother: each uses all the data) with ${fmt(100 * r.level)}% bands from their smoothed variances, as statsmodels' plot_components draws them; the level panel also shows the data, linked to the rows. They add up to the series: level + seasonal + cycle + autoregressive + regression effect + irregular.${r.burn ? ` The first ${r.burn} one-step predictions are diffuse and left out of the fit.` : ''}`));
  }

  function saveComponents(ctx, col, S, r) {
    for (const c of r.components || []) saveSlots(ctx, S, `${c.label} ${col.name}`, c.mean);
  }

  /* ---- Regime Switching: regimes, transitions, probabilities ------------------------------------------------------------ */
  function regimeReport(ctx, col, S, spec, r, ob) {
    const sc = scopeOf(col);
    const k = r.k;
    const rc = Array.from({ length: k }, (_, j) => ({ key: `r${j}`, label: `Regime ${j}` }));
    const rg = ctx.outline('Regimes', { parent: ob, key: `${sc}:model:${spec.id}:regimes`, info: 'p:timeseries:regime' });
    rg.add(ctx.row(
      ctx.rt({ columns: [{ key: 'regime', label: 'Regime', fmt: 'text' }, { key: 'stay', label: 'P(Stay)' }, { key: 'duration', label: 'Expected Duration' }, { key: 'periods', label: 'Periods Most Likely', fmt: 'int' }, { key: 'share', label: 'Mean Probability' }], rows: r.regimes },
        { sortable: false, caption: 'Regimes', name: `${r.name} regimes` }),
      ctx.rt({ columns: [{ key: 'from', label: 'From \\ To', fmt: 'text' }, ...rc], rows: r.transition }, { sortable: false, caption: 'Transition Probabilities', name: `${r.name} transition probabilities` })));
    rg.add(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'switching', label: 'Switching', fmt: 'text' }, ...rc], rows: r.per_regime }, { sortable: false, caption: 'Parameters by Regime', name: `${r.name} parameters by regime` }));
    rg.add(ctx.note('P(Stay) is the probability of staying in the regime from one period to the next, and the expected duration 1/(1 − P(Stay)) periods. A row of Transition Probabilities is the regime now, a column the regime next period.'));
    // the series, shaded by the regime that is most likely, and the probabilities
    const pr = ctx.outline('Regime Probabilities', { parent: ob, key: `${sc}:model:${spec.id}:prob` });
    const step = S.n > 1 ? (S.t[S.n - 1] - S.t[0]) / (S.n - 1) : 1;
    const edge = (i) => (i <= 0 ? S.t[0] - step / 2 : i >= S.n ? S.t[S.n - 1] + step / 2 : (S.t[i - 1] + S.t[i]) / 2);
    const shapes = [];
    for (let i = 0; i < S.n;) {
      const m = r.most[i];
      let j = i + 1;
      while (j < S.n && r.most[j] === m) j++;
      if (m != null) shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: edge(i), x1: edge(j), y0: 0, y1: 1, fillcolor: rgba(regimeColor(m), 0.16), line: { width: 0 }, layer: 'below' });
      i = j;
    }
    const legend = rc.map((c, j) => ({ type: 'scatter', mode: 'markers', x: [null], y: [null], name: `${c.label} most likely`, marker: { symbol: 'square', size: 11, color: rgba(regimeColor(j), 0.45) }, hoverinfo: 'skip' }));
    // the series in the theme's ink, which reads on either shading; the regime is the shading's
    const ink = SM.util.themeColors().text;
    const pc = r.plot_code || {};
    const w = plotWidth(ctx, 620);
    pr.add(ctx.plot([seriesTrace(S, S.values, col.name, { color: ink }), ...legend], { xaxis: xAxis(S), yaxis: { title: { text: ptext(col.name) } }, shapes, showlegend: true, legend: { orientation: 'h', y: -0.25 } },
      { width: w, height: 290, title: `${r.name} regimes`, rowColors: false }), graphCode(ctx, pc.regimes, { size: [w, 290] }));
    const flag = spec.fprob === true;
    const ptr = r.prob.map((p, j) => ({ type: 'scatter', mode: 'lines+markers', x: S.x, y: p, rows: S.rowsLinked, name: `Regime ${j}`, line: { color: regimeColor(j), width: 1.5 },
      marker: { size: 3, color: regimeColor(j) }, hovertemplate: `P(regime ${j}) %{y:.3f}<extra></extra>` }));
    if (flag) r.fprob.forEach((p, j) => ptr.push({ type: 'scatter', mode: 'lines', x: S.x, y: p, name: `Regime ${j} filtered`, line: { color: regimeColor(j), width: 1, dash: 'dot' }, hovertemplate: `filtered P(regime ${j}) %{y:.3f}<extra></extra>` }));
    pr.add(ctx.plot(ptr, { xaxis: xAxis(S), yaxis: { title: { text: 'Smoothed probability' }, range: [-0.03, 1.03] }, showlegend: true, legend: { orientation: 'h', y: -0.25 } },
      { width: w, height: 260, title: `${r.name} smoothed probabilities`, rowColors: false }), graphCode(ctx, pc.prob, { flags: { fprob: flag }, size: [w, 260] }));
    pr.add(ctx.note(`Shaded: the regime with the highest smoothed probability, P(regime at t | all the data)${flag ? '; dotted: the filtered probabilities, P(regime at t | the data up to t)' : ''}. Points are linked to the rows.`));
    const st = ctx.outline('Starts', { parent: ob, key: `${sc}:model:${spec.id}:starts`, closed: true });
    st.add(ctx.rt({ columns: [{ key: 'start', label: 'Start', fmt: 'text' }, { key: 'm2ll', label: '−2LogLikelihood' }, { key: 'converged', label: 'Converged', fmt: 'text' }, { key: 'best', label: '', fmt: 'text' }, { key: 'note', label: 'Note', fmt: 'text' }], rows: r.starts },
      { sortable: false, name: `${r.name} starts` }), ctx.note('Each start ends at a local maximum of the likelihood, or fails; the report is the best. Starts that end far apart mean the likelihood has several maxima: more starts make it likelier that the best is found.'));
  }

  function saveRegimes(ctx, col, S, r) {
    r.prob.forEach((p, j) => saveSlots(ctx, S, `P(Regime ${j}) ${col.name}`, p));
    saveSlots(ctx, S, `Most Likely Regime ${col.name}`, r.most);
  }

  /* ---- ARDL: the orders, the long run, the bounds test --------------------------------------------------------------------- */
  const VERDICT = {
    reject: (b) => `At 5%, F = ${fmt(b.stat)} is above the I(1) bound ${fmt(b.crit5.upper)}: the bounds test rejects the null of no level relationship, whether the inputs are I(0) or I(1). The series and the inputs move together in the long run.`,
    accept: (b) => `At 5%, F = ${fmt(b.stat)} is below the I(0) bound ${fmt(b.crit5.lower)}: no level relationship can be claimed, whether the inputs are I(0) or I(1).`,
    inconclusive: (b) => `At 5%, F = ${fmt(b.stat)} lies between the bounds ${fmt(b.crit5.lower)} and ${fmt(b.crit5.upper)}: inconclusive; the verdict depends on whether the inputs are I(0) or I(1) (their ADF and KPSS tests tell).`,
  };

  function ardlReport(ctx, col, S, spec, r, ob) {
    const sc = scopeOf(col);
    const key = `${sc}:model:${spec.id}`;
    if (r.selection && r.selection.length) {
      const sel = ctx.outline('Lag Order Selection', { parent: ob, key: `${key}:sel`, closed: true });
      const inputs = spec.inputs || [];
      sel.add(ctx.rt({ columns: [{ key: 'rank', label: 'Rank', fmt: 'int' }, { key: 'ic', label: (r.spec.ic || 'aic').toUpperCase() }, { key: 'ar', label: `${col.name} lags`, fmt: 'text' },
        ...inputs.map((c) => ({ key: `q_${c}`, label: `${c} lags`, fmt: 'text' }))], rows: r.selection }, { sortable: false, name: 'ARDL lag order selection' }),
      ctx.note(`The ten best of the orders searched by statsmodels' ardl_select_order, on the same sample (after the largest lag); "none" leaves the series out.`));
    }
    const lr = ctx.outline('Long-Run Coefficients', { parent: ob, key: `${key}:lr`, info: 'p:timeseries:ardl' });
    lr.add(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 'z Ratio' }, { key: 'p', label: 'Prob>|z|', fmt: 'p' }], rows: r.long_run },
      { sortable: false, name: `${r.name} long-run coefficients` }),
    ctx.note(`The level relation ${col.name} = θ₀ + Σ θ x that the model settles to: θ = Σβ/(1 − Σφ) over the lags of each input (β) and of ${col.name} (φ), with delta-method standard errors and normal p-values; these are minus statsmodels' UECM ci_params, with its ci_bse and ci_pvalues.${r.speed != null ? ` The speed of adjustment, the coefficient of ${col.name}(t−1) in the error correction form, is ${fmt(r.speed)}: that share of a gap from the level relation is closed each period.` : ''}`));
    const b = r.bounds;
    if (b) {
      b.crit5 = b.crit.find((x) => x.pct === 95) || b.crit[1];
      const bt = ctx.outline('Bounds Test', { parent: ob, key: `${key}:bounds`, info: 'p:timeseries:ardl' });
      bt.add(ctx.row(
        ctx.kv([['F Statistic', b.stat], ['Case', b.case, 'int'], ['Inputs (k)', b.k, 'int'], ['Restrictions', b.n_restrictions, 'int'], ['Prob, inputs I(0)', b.p_lower, 'p'], ['Prob, inputs I(1)', b.p_upper, 'p']]),
        ctx.rt({ columns: [{ key: 'level', label: 'Level', fmt: 'text' }, { key: 'lower', label: 'I(0) Bound' }, { key: 'upper', label: 'I(1) Bound' }], rows: b.crit },
          { sortable: false, caption: 'Critical Values (Pesaran, Shin and Smith 2001)', name: 'Bounds test critical values', cellClass: (row) => (row.pct === 95 ? 'sm-ts-crit5' : '') })));
      bt.add(el('p', { class: `sm-ts-verdict sm-ts-${b.verdict}`, text: VERDICT[b.verdict](b) }));
      const sm5 = (b.sm_crit || []).find((x) => x.level === '5%');
      bt.add(ctx.note(`Case ${b.case}: ${b.case_label}. The F test that the lagged levels of ${col.name} and the inputs${b.case === 2 ? ' and the intercept' : b.case === 4 ? ' and the trend' : ''} all have zero coefficients in the error correction form (statsmodels' bounds_test). Its distribution depends on whether the inputs are I(0) or I(1): the I(0) and I(1) bounds bracket every mix. The critical values and p-values are statsmodels' own simulated tables at k = ${b.k} inputs.${sm5 ? ` statsmodels 0.14.6's bounds_test reads them at k + 1 = ${b.k + 1} (5%: ${fmt(sm5.lower)} and ${fmt(sm5.upper)}), the bounds of one input more; the ones shown are those of the model's ${b.k}.` : ''}`));
    }
    if (r.ecm && r.ecm.length) {
      const ecm = ctx.outline('Error Correction Form', { parent: ob, key: `${key}:ecm`, closed: true });
      ecm.add(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }], rows: r.ecm },
        { sortable: false, name: `${r.name} error correction form` }),
      ctx.note(`The unrestricted error correction model (statsmodels' UECM) the bounds test uses: Δ${col.name} on the lagged levels (L1) and the lagged differences (D.), with every lag up to the model's longest.`));
    }
  }

  /* ---- saving ---------------------------------------------------------------------------------------------------------------- */
  const nanOf = (a) => (a || []).map((v) => (v == null ? NaN : v));

  function timeColumn(ctx, S, t) {
    return { name: ctx.name('time') || 'Row', dataType: 'numeric', values: t, format: isDate(S) ? { kind: S.kind } : null };
  }

  /* A model's rows for a saved table: the time, the predictions, their
     standard errors and limits, the residuals, and the set. The fitted slots
     get the one-step-ahead predictions; values held back their forecasts
     (the residuals are then the forecast errors); after the end the
     forecasts (with values held back, those of the refit on all rows). */
  function modelRows(S, r, refit) {
    const nFit = Math.min(r.n || S.n, S.n);
    const fc = r.forecast || { t: [], mean: [], se: [], lower: [], upper: [] };
    const held = nFit < S.n;
    const nh = S.n - nFit;
    const hb = r.holdback || { error: [] };
    const fut = held ? (refit && !refit.error && refit.forecast ? refit.forecast : null) : fc;
    const hf = fut ? fut.t.length : 0;
    const take = (a, k) => { const v = nanOf(a).slice(0, k); while (v.length < k) v.push(NaN); return v; };
    const part = (fit, hold, future) => [...take(fit, nFit), ...(held ? take(hold, nh) : []), ...take(future, hf)];
    return {
      held, nFit, nh, hf,
      t: [...S.t, ...(fut ? fut.t : [])],
      actual: [...nanOf(S.values), ...new Array(hf).fill(NaN)],
      // the one-step predictions wherever the model gives one, a missing value's too (pred); the residuals only where there is a value
      predicted: part(r.pred || r.fitted, fc.mean, fut && fut.mean),
      se: part(r.pred_se || r.fit_se, fc.se, fut && fut.se),
      resid: [...take(r.resid, nFit), ...(held ? take(hb.error, nh) : []), ...new Array(hf).fill(NaN)],
      upper: part(r.pred_hi || r.fit_hi, fc.upper, fut && fut.upper),
      lower: part(r.pred_lo || r.fit_lo, fc.lower, fut && fut.lower),
      set: [...new Array(nFit).fill('Training'), ...new Array(held ? nh : 0).fill('Holdback'), ...new Array(hf).fill('Forecast')],
    };
  }

  function saveModelTable(ctx, col, S, r, refit = null) {
    const R = modelRows(S, r, refit);
    const lv = fmt(r.level);
    const notes = R.held
      ? `${r.name}: fitted on the first ${R.nFit} values (Set Training, one-step-ahead predictions), its forecasts of the ${R.nh} held back (Set Holdback: the residuals are the forecast errors)${R.hf ? `, and ${R.hf} forecasts after the end from the model refit on all rows (Set Forecast)` : ''}, with ${fmt(100 * r.level)}% prediction limits.`
      : `${r.name}: one-step-ahead predictions, then ${R.hf} forecasts with ${fmt(100 * r.level)}% prediction limits.`;
    const columns = [
      timeColumn(ctx, S, R.t),
      { name: `Actual ${col.name}`, dataType: 'numeric', values: R.actual },
      { name: `Predicted ${col.name}`, dataType: 'numeric', values: R.predicted },
      { name: `Std Err Pred ${col.name}`, dataType: 'numeric', values: R.se },
      { name: `Residual ${col.name}`, dataType: 'numeric', values: R.resid },
      { name: `Upper CL (${lv}) ${col.name}`, dataType: 'numeric', values: R.upper },
      { name: `Lower CL (${lv}) ${col.name}`, dataType: 'numeric', values: R.lower },
    ];
    if (R.held) columns.push({ name: 'Set', dataType: 'character', values: R.set });
    SM.app.addTable(new SM.Table({ name: `${col.name} ${r.name}`, source: `saved from ${ctx.report.title}`, notes, columns }));
  }

  function combineForecasts(ctx, col, S, list, results, M = {}) {
    const ok = list.map((s, i) => ({ s, r: results[i], rf: M.refits ? M.refits[i] : null })).filter((x) => x.r && !x.r.error);
    if (!ok.length) { SM.ui.toast('No fitted models to save'); return; }
    const rows = ok.map((x) => ({ ...x, R: modelRows(S, x.r, x.rf) }));
    const hf = Math.max(...rows.map((x) => x.R.hf));
    const longest = rows.find((x) => x.R.hf === hf).R;
    const held = rows.some((x) => x.R.held);
    const pad = (a, k) => [...a, ...new Array(Math.max(0, k - a.length)).fill(NaN)];
    const nAll = S.n + hf;
    const columns = [timeColumn(ctx, S, longest.t), { name: `Actual ${col.name}`, dataType: 'numeric', values: pad(nanOf(S.values), nAll) }];
    for (const { r, R } of rows) {
      columns.push({ name: `Predicted ${r.name}`, dataType: 'numeric', values: pad(R.predicted, nAll) },
        { name: `Lower CL ${r.name}`, dataType: 'numeric', values: pad(R.lower, nAll) },
        { name: `Upper CL ${r.name}`, dataType: 'numeric', values: pad(R.upper, nAll) });
      if (held) columns.push({ name: `Residual ${r.name}`, dataType: 'numeric', values: pad(R.resid, nAll) });
    }
    if (held) columns.push({ name: 'Set', dataType: 'character', values: [...longest.set, ...new Array(Math.max(0, nAll - longest.set.length)).fill('Forecast')] });
    SM.app.addTable(new SM.Table({ name: `${col.name} forecasts`, source: `saved from ${ctx.report.title}`, columns,
      notes: held ? 'Each model\'s one-step-ahead predictions of the training values, its forecasts of the held-back ones (the residuals there are the forecast errors) and, refit on all rows, of the periods after the end; Set says which.' : undefined }));
  }

  /* ---- the dialogs ---------------------------------------------------------------------------------------------------------------- */
  /* What the fields the model dialogs share are for: their (i). */
  const H = {
    level: 'The coverage of the prediction intervals, of the forecasts and of the one-step-ahead predictions: 0.95 by default, a number between 0 and 1.',
    intercept: 'Estimates μ, the mean of the differenced series (with d = 1 a drift, a steady rise or fall); off fixes it at 0. On by default, as in JMP.',
    constrain: 'Keeps the AR part stationary and the MA part invertible during the fit (statsmodels\' enforce_stationarity and enforce_invertibility). On by default; off lets the estimates go anywhere, which can fit a little better and forecast strangely.',
    p: 'The number of autoregressive terms, 0 to 12: the differenced series depends on its own p previous values. A partial autocorrelation that cuts off after lag p suggests p.',
    d: 'How many times the series is differenced before the ARMA part, 0 to 2: 1 for a series that wanders (a unit root: the ADF tests, or an autocorrelation that dies out slowly), 2 rarely.',
    q: 'The number of moving average terms, 0 to 12: the series depends on the q previous shocks. An autocorrelation that cuts off after lag q suggests q.',
    P: 'Autoregressive terms at the seasonal lags s, 2s, …: 0 to 4.',
    D: 'Seasonal differences (1 − B^s), 0 to 2: 1 for a seasonal pattern that persists from one period to the next.',
    Q: 'Moving average terms at the seasonal lags, 0 to 4. The airline model, a classic for monthly data, is (0, 1, 1)(0, 1, 1)12.',
    s: 'The seasonal period s: 12 for monthly data, 4 for quarterly, 7 for daily data with a weekly pattern. At least 2; it starts at the Seasonal Period of the launch, or the Time ID\'s.',
  };
  const LEVEL = (v = 0.95) => ({ key: 'level', label: 'Prediction Interval', type: 'number', value: v, help: H.level });
  const levelOk = (x) => (x.level > 0 && x.level < 1 ? null : 'Prediction Interval: a level between 0 and 1, such as 0.95');
  const orderOk = (x, keys, max) => {
    for (const k of keys) if (x[k] != null && (!Number.isInteger(x[k]) || x[k] < 0 || x[k] > max[k])) return `${k}: a whole number from 0 to ${max[k]}`;
    return null;
  };
  const MAXO = { p: 12, d: 2, q: 12, P: 4, D: 2, Q: 4 };

  async function arimaDialog(ctx, col, S, { seasonal = false, preset = null } = {}) {
    const P0 = preset || {};
    const period = P0.s || periodOf(ctx, S);
    const fields = [
      { key: 'p', label: 'p, Autoregressive Order', type: 'number', value: P0.p ?? 0, help: H.p },
      { key: 'd', label: 'd, Differencing Order', type: 'number', value: P0.d ?? 0, help: H.d },
      { key: 'q', label: 'q, Moving Average Order', type: 'number', value: P0.q ?? 0, help: H.q },
    ];
    if (seasonal) fields.push(
      { key: 'P', label: 'P, Seasonal Autoregressive Order', type: 'number', value: P0.P ?? 0, help: H.P },
      { key: 'D', label: 'D, Seasonal Differencing Order', type: 'number', value: P0.D ?? 1, help: H.D },
      { key: 'Q', label: 'Q, Seasonal Moving Average Order', type: 'number', value: P0.Q ?? 1, help: H.Q },
      { key: 's', label: 'Observations per Period', type: 'number', value: period, help: H.s });
    fields.push(LEVEL(P0.level), { key: 'intercept', label: 'Intercept', type: 'check', value: P0.intercept ?? true, help: H.intercept }, { key: 'constrain', label: 'Constrain fit', type: 'check', value: P0.constrain ?? true, help: H.constrain });
    const v = await SM.ui.form({
      title: `${seasonal ? 'Seasonal ARIMA' : 'ARIMA'} Specification: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:arima',
      lead: seasonal ? 'Seasonal ARIMA(p, d, q)(P, D, Q)s by exact maximum likelihood. The intercept is the mean of the differenced series; Constrain fit keeps the AR part stable and the MA part invertible.' : 'ARIMA(p, d, q) by exact maximum likelihood. The intercept is the mean of the differenced series; Constrain fit keeps the AR part stable and the MA part invertible.',
      fields, validate: (x) => orderOk(x, seasonal ? ['p', 'd', 'q', 'P', 'D', 'Q'] : ['p', 'd', 'q'], MAXO) || levelOk(x) || (seasonal && !(x.s >= 2) ? 'Observations per Period: at least 2' : null),
    });
    if (!v) return;
    addModels(ctx, col, [{ kind: 'arima', p: v.p || 0, d: v.d || 0, q: v.q || 0, P: seasonal ? v.P || 0 : 0, D: seasonal ? v.D || 0 : 0, Q: seasonal ? v.Q || 0 : 0, s: seasonal ? Math.round(v.s) : 0,
      intercept: !!v.intercept, constrain: !!v.constrain, level: v.level, inputs: P0.inputs || undefined }]);
  }

  function parseRange(text, max) {
    const m = /^\s*(\d+)\s*(?:(?:-|–|to|\.\.)\s*(\d+))?\s*$/.exec(String(text ?? ''));
    if (!m) return null;
    const a = +m[1], b = m[2] != null ? +m[2] : a;
    if (a > b || b > max) return null;
    return [a, b];
  }

  async function groupDialog(ctx, col, S) {
    const period = periodOf(ctx, S);
    const keys = ['p', 'd', 'q', 'P', 'D', 'Q'];
    const labels = { p: 'p, Autoregressive Order', d: 'd, Differencing Order', q: 'q, Moving Average Order', P: 'P, Seasonal Autoregressive Order', D: 'D, Seasonal Differencing Order', Q: 'Q, Seasonal Moving Average Order' };
    const start = { p: '0-1', d: '0', q: '0-1', P: '0', D: '0', Q: '0' };
    const count = (x) => keys.reduce((n, k) => { const r = parseRange(x[k], MAXO[k]); return r ? n * (r[1] - r[0] + 1) : NaN; }, 1);
    const v = await SM.ui.form({
      title: `ARIMA Model Group: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:group',
      lead: 'A range for each order, such as 0-2; every combination is fitted (at most 64 models) and goes into the Model Comparison table. The report of the best one by AIC shows; the Report boxes show others.',
      fields: [...keys.map((k) => ({ key: k, label: `${labels[k]} (range)`, value: start[k], helpLabel: 'p, d, q, P, D, Q (ranges)',
        help: 'For each order a whole number or a range such as 0-2 (also 0–2, 0 to 2, 0..2): every combination is fitted. p and q go to 12, d and D to 2, P and Q to 4, and at most 64 models in all. The first ranges, p 0-1 and q 0-1, make four models.' })),
      { key: 's', label: 'Observations per Period', type: 'number', value: period, help: `${H.s} Used by the models whose P, D or Q is above 0.` }, LEVEL(),
        { key: 'intercept', label: 'Intercept', type: 'check', value: true, help: `${H.intercept} For every model of the group.` }, { key: 'constrain', label: 'Constrain fit', type: 'check', value: true, help: H.constrain }],
      validate: (x) => {
        for (const k of keys) if (!parseRange(x[k], MAXO[k])) return `${labels[k]}: a whole number or a range such as 0-2 (at most ${MAXO[k]})`;
        const n = count(x);
        if (n > 64) return `Total Number of Models: ${n}; at most 64`;
        if (['P', 'D', 'Q'].some((k) => parseRange(x[k], 9)[1] > 0) && !(x.s >= 2)) return 'Observations per Period: at least 2';
        return levelOk(x);
      },
    });
    if (!v) return;
    const R = Object.fromEntries(keys.map((k) => [k, parseRange(v[k], MAXO[k])]));
    const g = nextGroup(ctx, col);
    const specs = [];
    for (let p = R.p[0]; p <= R.p[1]; p++) for (let d = R.d[0]; d <= R.d[1]; d++) for (let q = R.q[0]; q <= R.q[1]; q++)
      for (let P = R.P[0]; P <= R.P[1]; P++) for (let D = R.D[0]; D <= R.D[1]; D++) for (let Q = R.Q[0]; Q <= R.Q[1]; Q++) {
        const seas = P || D || Q;
        specs.push({ kind: 'arima', p, d, q, P, D, Q, s: seas ? Math.round(v.s) : 0, intercept: !!v.intercept, constrain: !!v.constrain, level: v.level, group: g });
      }
    addModels(ctx, col, specs);
  }

  async function transferDialog(ctx, col, S, preset = null) {
    const inputs = ctx.roles('inputs').filter((c) => c.id !== col.id);
    if (!inputs.length) { SM.ui.toast('Transfer functions need Input List columns: relaunch with inputs'); return; }
    const P0 = preset || {};
    const period = P0.s || periodOf(ctx, S);
    const pre = new Map((P0.inputs || []).map((x) => [x.name, x]));
    const noise = 'The ARIMA orders of the noise N_t, the part of Y the inputs leave: p and q 0 to 12, d and D 0 to 2, P and Q 0 to 4, read as in ARIMA… (an AR(1) noise at first). Choose them from the residual correlations of the fit.';
    const fields = [
      { key: 'p', label: 'Noise p, Autoregressive Order', type: 'number', value: P0.p ?? 1, helpLabel: 'Noise p, d, q, P, D, Q', help: noise },
      { key: 'd', label: 'Noise d, Differencing Order', type: 'number', value: P0.d ?? 0, helpLabel: 'Noise p, d, q, P, D, Q', help: noise },
      { key: 'q', label: 'Noise q, Moving Average Order', type: 'number', value: P0.q ?? 0, helpLabel: 'Noise p, d, q, P, D, Q', help: noise },
      { key: 'P', label: 'Noise P, Seasonal Autoregressive Order', type: 'number', value: P0.P ?? 0, helpLabel: 'Noise p, d, q, P, D, Q', help: noise },
      { key: 'D', label: 'Noise D, Seasonal Differencing Order', type: 'number', value: P0.D ?? 0, helpLabel: 'Noise p, d, q, P, D, Q', help: noise },
      { key: 'Q', label: 'Noise Q, Seasonal Moving Average Order', type: 'number', value: P0.Q ?? 0, helpLabel: 'Noise p, d, q, P, D, Q', help: noise },
      { key: 's', label: 'Observations per Period', type: 'number', value: period, help: `${H.s} Used when the noise has a seasonal order.` },
    ];
    inputs.forEach((c, i) => {
      const p = pre.get(c.name);
      fields.push({ key: `use${i}`, label: `Input ${c.name}`, type: 'check', value: preset ? !!p : true, helpLabel: 'Input (each column)', help: 'Whether that Input List column enters the model, at least one; all of them at first.' },
        { key: `lag${i}`, label: `${c.name}: input lag (dead time)`, type: 'number', value: p ? p.lag || 0 : 0, helpLabel: 'Input lag (dead time)',
          help: 'The delay b before the input acts: it enters as x(t − b), 0 by default. The first positive lag where Cross Correlation peaks is a good guess.' },
        { key: `num${i}`, label: `${c.name}: numerator order (more lags)`, type: 'number', value: p ? p.num || 0 : 0, helpLabel: 'Numerator order (more lags)',
          help: 'How many more lags of the input enter after b: x(t − b) to x(t − b − r), each with a coefficient of its own. 0 by default; b + r at most 24. The first b + r observations are left out of the fit.' });
    });
    fields.push(LEVEL(P0.level), { key: 'intercept', label: 'Intercept', type: 'check', value: P0.intercept ?? true, help: H.intercept }, { key: 'constrain', label: 'Constrain fit', type: 'check', value: P0.constrain ?? true, help: H.constrain });
    const v = await SM.ui.form({
      title: `Transfer Function Model Specification: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:transfer',
      lead: 'Regression on the inputs with ARIMA errors (statsmodels\' ARIMA with exog). Each input enters at its lag and, with a numerator order r, at the r lags after it. Forecasts take the inputs\' future values from the rows after the series; beyond them the last value is held.',
      fields,
      validate: (x) => {
        const e = orderOk(x, ['p', 'd', 'q', 'P', 'D', 'Q'], MAXO);
        if (e) return e;
        if (!inputs.some((c, i) => x[`use${i}`])) return 'Choose at least one input';
        for (let i = 0; i < inputs.length; i++) if (x[`use${i}`] && (!(x[`lag${i}`] >= 0) || !(x[`num${i}`] >= 0) || x[`lag${i}`] + x[`num${i}`] > 24)) return `${inputs[i].name}: lags from 0, at most 24 in all`;
        if ((x.P || x.D || x.Q) && !(x.s >= 2)) return 'Observations per Period: at least 2';
        return levelOk(x);
      },
    });
    if (!v) return;
    const chosen = inputs.map((c, i) => (v[`use${i}`] ? { name: c.name, lag: Math.round(v[`lag${i}`] || 0), num: Math.round(v[`num${i}`] || 0) } : null)).filter(Boolean);
    const seas = v.P || v.D || v.Q;
    addModels(ctx, col, [{ kind: 'arima', p: v.p || 0, d: v.d || 0, q: v.q || 0, P: v.P || 0, D: v.D || 0, Q: v.Q || 0, s: seas ? Math.round(v.s) : 0, intercept: !!v.intercept, constrain: !!v.constrain, level: v.level, inputs: chosen }]);
  }

  const SMOOTH = [['simple', 'Simple Exponential Smoothing'], ['double', 'Double (Brown) Exponential Smoothing'], ['linear', 'Linear (Holt) Exponential Smoothing'],
    ['damped', 'Damped-Trend Linear Exponential Smoothing'], ['seasonal', 'Seasonal Exponential Smoothing'], ['winters', 'Winters Method']];
  const SMOOTH_LABEL = Object.fromEntries(SMOOTH);
  // JMP's smoothing weights: their symbols and names, per method
  const WEIGHT_SYM = { alpha: 'α', gamma: 'γ', phi: 'φ', delta: 'δ' };
  const WEIGHT_LABEL = { alpha: 'Level Smoothing Weight', gamma: 'Trend Smoothing Weight', phi: 'Damping Smoothing Weight', delta: 'Seasonal Smoothing Weight' };
  const WEIGHTS_OF = { simple: ['alpha'], double: ['alpha'], linear: ['alpha', 'gamma'], damped: ['alpha', 'gamma', 'phi'], seasonal: ['alpha', 'delta'], winters: ['alpha', 'gamma', 'delta'] };

  async function smoothDialog(ctx, col, S, method, preset = null) {
    const P0 = preset || {};
    const seasonal = method === 'seasonal' || method === 'winters';
    const pos = S.values.every((v) => v == null || v > 0);
    const fields = [LEVEL(P0.level)];
    if (seasonal) fields.push({ key: 's', label: 'Observations per Period', type: 'number', value: P0.s || periodOf(ctx, S), help: `${H.s} The series needs two periods and two values more.` });
    if (method === 'winters') fields.push({ key: 'mult', label: 'Seasonality', type: 'select', value: P0.multiplicative ? 'mul' : 'add', choices: [['add', 'Additive (JMP\'s Winters Method)'], ['mul', 'Multiplicative']],
      help: 'Additive (JMP\'s Winters Method): the seasonal effects are added to the level, a swing of the same size every period. Multiplicative: they scale the level, a swing that grows with the series; every value must be above zero.' });
    fields.push({ key: 'constraints', label: 'Constraints', type: 'select', value: P0.weights ? 'custom' : 'zero', choices: [['zero', 'Zero To One'], ['custom', 'Custom']],
      help: 'Zero To One (the default, as in JMP): every smoothing weight is estimated within 0 and 1. Custom: each weight fixed at a value or bounded within limits of your own, in a second dialog after OK.' },
    { key: 'bc', label: 'Box-Cox transformation', type: 'check', value: P0.boxcox != null,
      help: 'Fits the model to the Box-Cox transform of the series, (y^λ − 1)/λ, or log y at λ = 0, and transforms the predictions, the forecasts and their limits back: a series whose swings grow with its level gets forecasts and limits that grow with it. Every value must be above zero. Off by default.' },
    { key: 'lambda', label: 'λ, Box-Cox', type: 'number', value: P0.boxcox ?? 0,
      help: 'The λ of the Box-Cox transformation, with Box-Cox transformation checked: 0 (the default) is the log, 0.5 about a square root, 1 no change beyond a shift. Values from −2 to 2.' });
    const v = await SM.ui.form({
      title: `${SMOOTH_LABEL[method]}: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:smoothing',
      lead: 'The smoothing weights and the starting states that minimise the one-step-ahead squared errors (statsmodels\' holtwinters), with prediction intervals from the model\'s moving-average weights.',
      fields, validate: (x) => levelOk(x) || (seasonal && !(x.s >= 2) ? 'Observations per Period: at least 2' : null)
        || (x.bc && !(x.lambda >= -2 && x.lambda <= 2) ? 'λ, Box-Cox: a value from −2 to 2' : null) || (x.bc && !pos ? 'The Box-Cox transformation needs every value above zero' : null),
    });
    if (!v) return;
    let weights = null;
    if (v.constraints === 'custom') {
      weights = await customWeights(ctx, col, method, P0.weights || {});
      if (!weights) return;
    }
    addModels(ctx, col, [{ kind: 'smooth', method, s: seasonal ? Math.round(v.s) : 0, level: v.level, multiplicative: method === 'winters' && v.mult === 'mul',
      ...(weights && Object.keys(weights).length ? { weights } : {}), ...(v.bc ? { boxcox: v.lambda } : {}) }]);
  }

  /* JMP's Custom constraints: each smoothing weight estimated within 0 and 1,
     fixed at a value, or bounded within limits of your own. */
  async function customWeights(ctx, col, method, pre) {
    const keys = WEIGHTS_OF[method];
    const fields = [];
    for (const k of keys) {
      const w = pre[k] || {};
      const lab = method === 'double' ? 'Level and Trend Smoothing Weight' : WEIGHT_LABEL[k];
      fields.push({ key: `${k}_mode`, label: `${WEIGHT_SYM[k]}, ${lab}`, type: 'select', value: w.fix != null ? 'fix' : (w.lo != null || w.hi != null) ? 'bound' : 'free',
        choices: [['free', 'Estimated within 0 and 1'], ['fix', 'Fixed'], ['bound', 'Bounded']], helpLabel: 'Each weight',
        help: 'Estimated within 0 and 1 (Zero To One), Fixed at the value (not estimated, so no standard error), or Bounded: estimated within the lower and upper bounds. statsmodels takes weights within 0 and 1 only, and keeps the trend weight at or below the level weight.' },
      { key: `${k}_value`, label: `${WEIGHT_SYM[k]}: fixed value`, type: 'number', value: w.fix ?? '', helpLabel: 'Fixed value', help: 'The value of a Fixed weight, within 0 and 1 (the level weight above 0).' },
      { key: `${k}_lo`, label: `${WEIGHT_SYM[k]}: lower bound`, type: 'number', value: w.lo ?? 0, helpLabel: 'Lower and upper bound', help: 'The bounds of a Bounded weight, from 0 to 1, the lower below the upper.' },
      { key: `${k}_hi`, label: `${WEIGHT_SYM[k]}: upper bound`, type: 'number', value: w.hi ?? 1, helpLabel: 'Lower and upper bound', help: 'The bounds of a Bounded weight, from 0 to 1, the lower below the upper.' });
    }
    const v = await SM.ui.form({
      title: `Custom Constraints: ${SMOOTH_LABEL[method]}`, okLabel: 'Estimate', info: 'p:timeseries:smoothing',
      lead: 'Each smoothing weight: estimated within 0 and 1, fixed at a value, or bounded. The seasonal weight δ is statsmodels\' smoothing_seasonal / (1 − α): with δ fixed or bounded and α estimated, α is searched for and the rest estimated at each α.',
      fields,
      validate: (x) => {
        for (const k of keys) {
          const m = x[`${k}_mode`];
          if (m === 'fix' && !(x[`${k}_value`] >= 0 && x[`${k}_value`] <= 1 && (k !== 'alpha' || x[`${k}_value`] > 0))) return `${WEIGHT_SYM[k]}: a fixed value within 0 and 1${k === 'alpha' ? ', above 0' : ''}`;
          if (m === 'bound' && !(x[`${k}_lo`] >= 0 && x[`${k}_hi`] <= 1 && x[`${k}_lo`] < x[`${k}_hi`])) return `${WEIGHT_SYM[k]}: bounds within 0 and 1, the lower below the upper`;
        }
        return null;
      },
    });
    if (!v) return null;
    const out = {};
    for (const k of keys) {
      const m = v[`${k}_mode`];
      if (m === 'fix') out[k] = { fix: v[`${k}_value`] };
      else if (m === 'bound' && !(v[`${k}_lo`] === 0 && v[`${k}_hi`] === 1)) out[k] = { lo: v[`${k}_lo`], hi: v[`${k}_hi`] };
    }
    return out;
  }

  async function etsDialog(ctx, col, S) {
    const pos = S.values.every((v) => v == null || v > 0);
    const period = periodOf(ctx, S);
    const v = await SM.ui.form({
      title: `Specify State Space Smoothing Models: ${col.name}`, okLabel: 'OK', info: 'p:timeseries:ets',
      lead: 'ETS(error, trend, seasonal) models of Hyndman et al. (2008): every combination of the boxes checked is fitted by maximum likelihood (statsmodels\' ETSModel) and compared by AICc; up to 30, as JMP fits them. Multiplicative parts, the multiplicative trends too, need every value above zero.',
      fields: [
        { key: 'eA', label: 'Error: Additive (A)', type: 'check', value: true, help: 'Fit models whose errors add to the prediction, of the same size at every level.' },
        { key: 'eM', label: 'Error: Multiplicative (M)', type: 'check', value: pos, help: 'Fit models whose errors are relative, growing with the level; for values above zero (checked at first when every value is). Their prediction intervals are simulated.' },
        { key: 'tN', label: 'Trend: None (N)', type: 'check', value: true, help: 'Fit models without a trend: the level wanders, and the forecasts are flat.' },
        { key: 'tA', label: 'Trend: Additive (A)', type: 'check', value: true, help: 'Fit models with a trend that may change over time; the forecasts go on in a straight line.' },
        { key: 'tAd', label: 'Trend: Additive damped (Ad)', type: 'check', value: true, help: 'Fit models whose trend flattens out over the forecasts (a damping φ below 1 is estimated); they often forecast best.' },
        { key: 'tM', label: 'Trend: Multiplicative (M)', type: 'check', value: false,
          help: 'Fit models whose level grows by a factor each period, a growth rate that may change over time; the forecasts go on exponentially. For values above zero; off at first, because such trends can forecast too far (Hyndman et al. 2008 leave them out of their automatic choice). Their prediction intervals are simulated.' },
        { key: 'tMd', label: 'Trend: Multiplicative damped (Md)', type: 'check', value: false, help: 'Fit models whose growth factor shrinks towards 1 over the forecasts (a damping φ below 1). For values above zero; off at first. Their prediction intervals are simulated.' },
        { key: 'sN', label: 'Seasonal: None (N)', type: 'check', value: true, help: 'Fit models without a seasonal part.' },
        { key: 'sA', label: 'Seasonal: Additive (A)', type: 'check', value: knownPeriod(ctx, S) != null, help: 'Fit models whose seasonal effects add to the level: a swing of the same size every period. Checked at first when the period is known (the launch\'s Seasonal Period, or the Time ID\'s calendar), not when it is only guessed.' },
        { key: 'sM', label: 'Seasonal: Multiplicative (M)', type: 'check', value: pos && knownPeriod(ctx, S) != null, help: 'Fit models whose seasonal effects scale the level, a swing that grows with the series; for values above zero (checked at first when every value is and the period is known). Their prediction intervals are simulated.' },
        { key: 'period', label: 'Period', type: 'number', value: period, help: 'The seasonal period of the seasonal models, at least 2 (12 for monthly data); the series needs two periods and four values more.' },
        { key: 'stable', label: 'Leave out additive errors with multiplicative seasonality (unstable)', type: 'check', value: true, helpLabel: 'Leave out additive errors with multiplicative seasonality',
          help: 'Skips ETS(A, ·, M), whose likelihood is numerically unstable (Hyndman et al. 2008 leave these models out too). On by default.' },
        LEVEL(),
      ],
      validate: (x) => {
        if (!x.eA && !x.eM) return 'Check an error type';
        if (!x.tN && !x.tA && !x.tAd && !x.tM && !x.tMd) return 'Check a trend';
        if (!x.sN && !x.sA && !x.sM) return 'Check a seasonal component';
        if ((x.eM || x.sM || x.tM || x.tMd) && !pos) return 'Multiplicative errors, trends and seasonality need every value above zero';
        if ((x.sA || x.sM) && !(x.period >= 2)) return 'Period: at least 2 for seasonal models';
        return levelOk(x);
      },
    });
    if (!v) return;
    const g = nextGroup(ctx, col);
    const specs = [];
    for (const [ek, e] of [['eA', 'add'], ['eM', 'mul']]) for (const [tk, t] of [['tN', 'N'], ['tA', 'A'], ['tAd', 'Ad'], ['tM', 'M'], ['tMd', 'Md']]) for (const [sk, s] of [['sN', 'N'], ['sA', 'A'], ['sM', 'M']]) {
      if (!v[ek] || !v[tk] || !v[sk]) continue;
      if (v.stable && e === 'add' && s === 'M') continue;
      specs.push({ kind: 'ets', error: e, trend: t, seasonal: s, s: s !== 'N' ? Math.round(v.period) : 0, level: v.level, group: g });
    }
    if (!specs.length) { SM.ui.toast('No models left to fit'); return; }
    addModels(ctx, col, specs);
  }

  /* ---- Benchmark Models: Naive, Seasonal Naive, Drift ------------------------------------------------------------------------ */
  const BENCH = [['naive', 'Naive'], ['snaive', 'Seasonal Naive'], ['drift', 'Drift']];

  async function benchDialog(ctx, col, S, methods, preset = null) {
    const P0 = preset || {};
    const seasonal = methods.includes('snaive');
    const fields = [LEVEL(P0.level)];
    if (seasonal) fields.push({ key: 's', label: 'Observations per Period', type: 'number', value: P0.s || periodOf(ctx, S), help: `${H.s} Seasonal Naive forecasts each period by the value of the same season one period before.` });
    const v = await SM.ui.form({
      title: `${methods.length > 1 ? 'Benchmark Models' : BENCH.find(([k]) => k === methods[0])[1]}: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:benchmarks',
      lead: 'The forecasts a model should beat: Naive, every forecast the last value; Seasonal Naive, the value of the same season one period before; Drift, the last value plus the average change per period. Compare them with Forecast on Holdback.',
      fields, validate: (x) => levelOk(x) || (seasonal && !(x.s >= 2) ? 'Observations per Period: at least 2' : null),
    });
    if (!v) return;
    addModels(ctx, col, methods.map((m) => ({ kind: 'bench', method: m, s: m === 'snaive' ? Math.round(v.s) : 0, level: v.level })));
  }

  /* ---- Simple Moving Average ---------------------------------------------------------------------------------------------------- */
  async function smaDialog(ctx, col, S, preset = null) {
    const P0 = preset || {};
    const v = await SM.ui.form({
      title: `Simple Moving Average: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:sma',
      lead: 'The mean of w consecutive values, as JMP\'s Simple Moving Average smooths the series. As a forecast the average trails: every forecast is the mean of the last w values, and the one-step-ahead prediction of each value the mean of the w before it.',
      fields: [
        { key: 'width', label: 'Smoothing window width', type: 'number', value: P0.width || knownPeriod(ctx, S) || 3,
          help: 'w, the number of consecutive values averaged, a whole number from 1: a wider window smooths more and follows changes later. It starts at the seasonal period when one is known (a period\'s mean has no seasonal swing), else at 3.' },
        { key: 'centering', label: 'Centering', type: 'select', value: P0.centering || 'none',
          choices: [['none', 'No Centering'], ['centered', 'Centered'], ['double', 'Centered and Double Smoothed (even width)']],
          help: 'Where the window of the smoothed series sits. No Centering (the default): the value and the w − 1 before it, the average a forecast uses. Centered: around the value, a smoothed series that does not lag (an even width takes one value more before it than after). Centered and Double Smoothed, for an even width: the mean of the two nearly centered windows. The forecasts trail whichever you choose.' },
        LEVEL(P0.level),
      ],
      validate: (x) => (!(Number.isInteger(x.width) && x.width >= 1) ? 'Smoothing window width: a whole number from 1'
        : x.centering === 'double' && x.width % 2 ? 'Centered and Double Smoothed is for an even width' : x.width + 3 > S.n ? `Smoothing window width: the series has ${S.n} values` : levelOk(x)),
    });
    if (!v) return;
    addModels(ctx, col, [{ kind: 'sma', width: v.width, centering: v.centering, level: v.level }]);
  }

  /* ---- Averaged Forecast… ------------------------------------------------------------------------------------------------------ */
  // the models that can be averaged: those with forecasts, not an average itself
  const averageable = (list) => list.filter((m) => m.kind !== 'markov' && m.kind !== 'avg');

  async function averageDialog(ctx, col, S, list = null, preset = null) {
    const models = averageable(list || ctx.opt('models', [], scopeOf(col)));
    if (models.length < 2) { SM.ui.toast('An averaged forecast needs two models with forecasts: fit them first'); return; }
    const P0 = preset || {};
    const pre = new Set(P0.members || models.map((m) => m.id));
    const fields = models.map((m) => ({ key: `m${m.id}`, label: specName(m), type: 'check', value: pre.has(m.id), helpLabel: 'Each model',
      help: 'Whether this model is one of the averaged ones, at least two; all at first.' }));
    fields.push(LEVEL(P0.level));
    const v = await SM.ui.form({
      title: `Averaged Forecast: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:average',
      lead: 'A model whose forecasts are the mean of the chosen models\' forecasts, and its limits the mean of their limits (at this level): forecasts combined this way are often better than any one of them. It goes into Model Comparison with the others.',
      fields, validate: (x) => (models.filter((m) => x[`m${m.id}`]).length < 2 ? 'Choose at least two models' : levelOk(x)),
    });
    if (!v) return;
    addModels(ctx, col, [{ kind: 'avg', members: models.filter((m) => v[`m${m.id}`]).map((m) => m.id), level: v.level }]);
  }

  /* ---- Rolling-Origin Cross-Validation… ------------------------------------------------------------------------------------------ */
  async function cvDialog(ctx, col, S) {
    const sc = scopeOf(col);
    const pre = ctx.opt('cv', null, sc) || {};
    const h0 = Math.max(1, Math.min(horizon(ctx) || 12, 12));
    const v = await SM.ui.form({
      title: `Rolling-Origin Cross-Validation: ${col.name}`, okLabel: 'OK', info: 'p:timeseries:cv',
      lead: 'Every model of Model Comparison is fitted again on the series up to each origin (a window that grows by the step) and forecasts the next values; the forecast errors of every origin give its RMSE, MAE and MAPE, and their means say how well each model forecasts. The last origin ends one horizon before the end of the series.',
      fields: [
        { key: 'origins', label: 'Number of origins', type: 'number', value: pre.origins || 5, help: 'How many forecast origins, a whole number from 2 to 50 (5 by default): more origins, a steadier comparison, and a longer wait (every model is fitted once per origin).' },
        { key: 'horizon', label: 'Horizon (values forecast from each origin)', type: 'number', value: pre.horizon || h0, helpLabel: 'Horizon',
          help: 'How many values each origin forecasts, a whole number from 1: the Forecast Periods, at most 12, at first. The errors of all of them count.' },
        { key: 'step', label: 'Step between origins (empty: the horizon)', type: 'number', value: pre.step ?? '', helpLabel: 'Step between origins',
          help: 'How many values apart the origins are. Empty (the default): the horizon, so that the forecast windows follow one another without overlapping; 1 uses every origin.' },
      ],
      validate: (x) => {
        if (!(Number.isInteger(x.origins) && x.origins >= 2 && x.origins <= 50)) return 'Number of origins: a whole number from 2 to 50';
        if (!(Number.isInteger(x.horizon) && x.horizon >= 1)) return 'Horizon: a whole number from 1';
        if (x.step != null && !(Number.isInteger(x.step) && x.step >= 1)) return 'Step between origins: a whole number from 1, or empty';
        const need = (x.origins - 1) * (x.step || x.horizon) + x.horizon + 8;
        return need > S.n ? `The series has ${S.n} values: that needs at least ${need}` : null;
      },
    });
    if (!v) return;
    ctx.set('cv', { origins: v.origins, horizon: v.horizon, step: v.step || null }, sc);
  }

  function cvOutline(ctx, col, S, box) {
    const sc = scopeOf(col);
    return ctx.outline('Rolling-Origin Cross-Validation', { parent: box, key: `${sc}:cv`, info: 'p:timeseries:cv', menu: () => [
      { label: 'Cross-Validation Options…', action: () => cvDialog(ctx, col, S) },
      { label: 'Remove', action: () => ctx.set('cv', null, sc) },
    ] });
  }

  async function cvReport(ctx, col, S, base, list, ob, { origins, horizon: H, step, season }) {
    const models = list.filter((m) => m.kind !== 'markov');
    if (!models.length) { ob.add(ctx.note('No models with forecasts to cross-validate.')); return; }
    const calls = [];
    for (const m of models) {
      const c = callOf(ctx, m, H, list);
      if (!c.error) calls.push({ id: m.id, name: specName(m), ...c });
    }
    const payload = { ...base, models: calls, origins, horizon: H, step, season };
    let r;
    if (ctx.headless) r = await ctx.call('timeseries.cv', payload);
    else {
      const who = `Cross-validation${ctx.byLabel ? ` (${ctx.byLabel})` : ''}`;
      const note = el('p', { class: 'sm-ob-note', role: 'status', text: `${who}: fitting…` });
      ob.add(note);
      const off = SM.engine.on('progress', (p) => {
        if (!p || p.what !== 'tscv') return;
        const text = `${who}: ${p.done} of ${p.total} fits…`;
        note.textContent = text;
        if (ctx.report && ctx.report.noteEl) ctx.report.noteEl.textContent = text;
      });
      try { r = await ctx.call('timeseries.cv', payload); } finally { off(); note.remove(); }
    }
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const idOf = new Map(calls.map((c) => [c.id, c]));
    const rows = r.models.map((m) => ({ id: m.id, name: m.name, rmse: m.rmse, mae: m.mae, mape: m.mape, ok: m.n_ok, of: r.origins })).sort((a, b) => (a.rmse ?? Infinity) - (b.rmse ?? Infinity));
    const t0 = r.t_origins[0], t1 = r.t_origins[r.t_origins.length - 1];
    ob.add(ctx.row(ctx.rt({ columns: [{ key: 'name', label: 'Model', fmt: 'text' }, { key: 'rmse', label: 'RMSE' }, { key: 'mae', label: 'MAE' }, { key: 'mape', label: 'MAPE' },
      { key: 'ok', label: 'Origins', fmt: 'int' }], rows }, { sortable: true, caption: 'Means over the Origins', name: 'Cross-validation means' }),
    ctx.kv([['Origins', r.origins, 'int'], ['Horizon', r.horizon, 'int'], ['Step', r.step, 'int'], ['First Origin', tLabel(S, t0), 'text'], ['Last Origin', tLabel(S, t1), 'text']])));
    ob.add(ctx.note(`Each model fitted on the values up to each of ${r.origins} origins, ${r.step} apart (the first ${tLabel(S, t0)}, the last ${tLabel(S, t1)}, ${r.horizon} before the end), and its forecasts of the next ${r.horizon} values; RMSE, MAE and MAPE of their errors at each origin, then their means. The models' settings are those of their reports; each is fitted again at every origin (ARDL's orders chosen again too).`));
    const bad = r.models.filter((m) => m.n_ok < r.origins);
    if (bad.length) ob.add(ctx.warn(`Not every origin could be fitted: ${bad.map((m) => `${m.name} (${m.origins.filter((p) => p.error).map((p) => p.error)[0]})`).join('; ')}. Their means are over the origins that could.`));
    ob.add(ctx.code(r.code));
    // RMSE by origin, a line per model in its colour
    const xs = r.t_origins.map((t) => (isDate(S) ? tLabel(S, t) : t));
    const traces = r.models.map((m) => ({ type: 'scatter', mode: 'lines+markers', x: xs, y: m.origins.map((p) => p.rmse ?? null), name: ptext(m.name),
      line: { color: colorOf(m.id), width: 1.4 }, marker: { size: 5, color: colorOf(m.id) }, hovertemplate: `${ptext(m.name)}: %{y:.5g}<extra></extra>` }));
    const w = plotWidth(ctx, 560);
    const title = `${col.name} cross-validation RMSE by origin`;
    const colors = Object.fromEntries(r.models.map((m) => [m.name, colorOf(m.id)]));
    const code = [r.code, '', 'import matplotlib.pyplot as plt', recipe([{ set: 'size' }], { size: [w, 280] }),
      `colors = ${J(colors)}   # the models' colours in the report`, 'fig, ax = plt.subplots(figsize=size, layout="constrained")',
      'for name, g in cv.groupby("Model", sort=False):   # RMSE at each origin, a line per model',
      '    ax.plot(g["Origin"], g["RMSE"], color=colors[name], linewidth=1.01, marker="o", markersize=3.6, label=name)',
      `ax.set_xlabel(${J(`Origin (${timeTitle(S)})`)})`, 'ax.set_ylabel("RMSE")', `ax.set_title(${J(title)})`,
      'fig.legend(loc="outside lower center", ncols=2, frameon=False, fontsize=8)', 'plt.show()'].join('\n');
    ob.add(ctx.plot(traces, { xaxis: xAxis(S, { title: { text: ptext(`Origin (${timeTitle(S)})`) } }), yaxis: { title: { text: 'RMSE' } }, showlegend: true, legend: { orientation: 'h', y: -0.3 } },
      { width: w, height: 280, title, rowColors: false }), ctx.code(code));
    const per = ctx.outline('Per Origin', { parent: ob, key: `${scopeOf(col)}:cv:per`, closed: true });
    const prow = [];
    for (const m of r.models) for (const p of m.origins) prow.push({ name: m.name, origin: tLabel(S, p.t), n_train: p.n_train, n: p.n ?? null, rmse: p.rmse ?? null, mae: p.mae ?? null, mape: p.mape ?? null, error: p.error || '' });
    per.add(ctx.rt({ columns: [{ key: 'name', label: 'Model', fmt: 'text' }, { key: 'origin', label: 'Origin', fmt: 'text' }, { key: 'n_train', label: 'N Fitted', fmt: 'int' },
      { key: 'n', label: 'N Forecast', fmt: 'int' }, { key: 'rmse', label: 'RMSE' }, { key: 'mae', label: 'MAE' }, { key: 'mape', label: 'MAPE' }, { key: 'error', label: '', fmt: 'text' }], rows: prow },
    { sortable: true, name: 'Cross-validation per origin' }));
    if (idOf.size < models.length) ob.add(ctx.note('A model whose averaged members are gone is left out.'));
  }

  /* ---- Structural Model… ---------------------------------------------------------------------------------------------------- */
  const UC_TRENDS = [['irregular', 'No trend: y = ε'], ['fixed intercept', 'Fixed intercept'], ['deterministic constant', 'Deterministic constant: μ + ε'],
    ['local level', 'Local level: a random walk level + ε'], ['random walk', 'Random walk'], ['fixed slope', 'Fixed slope'], ['deterministic trend', 'Deterministic trend: a line + ε'],
    ['local linear deterministic trend', 'Local linear deterministic trend: random level, fixed slope'], ['random walk with drift', 'Random walk with drift'],
    ['local linear trend', 'Local linear trend: random level and slope'], ['smooth trend', 'Smooth trend: a random slope only'], ['random trend', 'Random trend']];

  async function structuralDialog(ctx, col, S, preset = null) {
    const P0 = preset || {};
    const inputs = ctx.roles('inputs').filter((c) => c.id !== col.id);
    const period = P0.seasonal || P0.freqPeriod || periodOf(ctx, S);
    const seasonalDefault = P0.kind ? (P0.seasonal ? 'dummy' : P0.freqPeriod ? 'trig' : 'none') : (S.period_auto >= 2 ? 'dummy' : 'none');
    const pre = new Set(P0.inputs || []);
    const fields = [
      { key: 'trend', label: 'Level and Trend', type: 'select', value: P0.trend || 'local linear trend', choices: UC_TRENDS,
        help: 'The trend part, one of statsmodels\' twelve: from no trend (y = ε) and a fixed intercept, through the local level (a random-walk level plus noise), to the local linear trend (the default: a level and a slope that both follow random walks) and the smooth trend (a random slope only). A variance estimated at 0 fixes that part.' },
      { key: 'seas', label: 'Seasonal', type: 'select', value: seasonalDefault, choices: [['none', 'None'], ['dummy', 'Seasonal dummies (time domain)'], ['trig', 'Trigonometric (frequency domain)']],
        help: 'None; seasonal dummies, one effect per season summing to zero over the period; or a trigonometric seasonal of sines and cosines, which with fewer harmonics gives a smoother pattern. Seasonal dummies at first when the Time ID has a seasonal period.' },
      { key: 'period', label: 'Seasonal Period', type: 'number', value: period, help: 'The observations per period of the seasonal part, a whole number from 2 (12 for monthly data). Not used with Seasonal None.' },
      { key: 'harmonics', label: 'Harmonics, trigonometric (empty: all)', type: 'number', value: P0.freqHarmonics || '', helpLabel: 'Harmonics',
        help: 'For a trigonometric seasonal: how many sine-cosine pairs, 1 to period/2; empty takes them all. Fewer harmonics, fewer parameters and a smoother seasonal pattern.' },
      { key: 'stochSeasonal', label: 'Stochastic seasonal (it may change over time)', type: 'check', value: P0.kind ? (P0.seasonal ? P0.stochSeasonal !== false : P0.stochFreq !== false) : true, helpLabel: 'Stochastic seasonal',
        help: 'On (the default): the seasonal pattern may change slowly over time, with a variance of its own. Off: the same pattern in every period.' },
      { key: 'cycle', label: 'Cycle', type: 'check', value: !!P0.cycle, help: 'Adds a cycle whose period (its frequency) is estimated within bounds, such as a business cycle. Off by default.' },
      { key: 'stochCycle', label: 'Stochastic cycle', type: 'check', value: P0.stochCycle !== false, help: 'With a cycle: its amplitude and phase may change over time (on, the default); off, a fixed wave.' },
      { key: 'damped', label: 'Damped cycle', type: 'check', value: P0.damped !== false, help: 'With a cycle: a damping factor below 1 is estimated, so the cycle dies out unless new shocks renew it (on, the default); off, undamped.' },
      { key: 'cycleLo', label: 'Cycle period from (empty: statsmodels\' default)', type: 'number', value: P0.cycleLo ?? '', helpLabel: 'Cycle period from',
        help: 'The shortest period the cycle may take, in observations, at least 2. With both bounds empty statsmodels bounds the period to 1.5 to 12 years for yearly, quarterly and monthly data; with only the upper bound given, this one is 2. Try other bounds when cycle models end at different maxima.' },
      { key: 'cycleHi', label: 'Cycle period to (empty: statsmodels\' default)', type: 'number', value: P0.cycleHi ?? '', helpLabel: 'Cycle period to',
        help: 'The longest period the cycle may take, above the lower bound; empty with a lower bound given: no upper bound.' },
      { key: 'ar', label: 'Autoregressive Order', type: 'number', value: P0.ar || 0, help: 'An AR(p) part, 0 to 12 (0 by default), beside the irregular: short-run dynamics the other parts leave in the residuals.' },
    ];
    inputs.forEach((c, i) => fields.push({ key: `use${i}`, label: `Input ${c.name}`, type: 'check', value: preset ? pre.has(c.name) : true, helpLabel: 'Input (each column)',
      help: 'Whether that Input List column enters as a regressor, its coefficient estimated with the rest; all of them at first. The forecasts take its future values from the rows after the series.' }));
    fields.push({ key: 'exact', label: 'Exact diffuse initialization', type: 'check', value: !!P0.exact,
      help: 'Durbin and Koopman\'s exact likelihood for the nonstationary states (the published Nile estimates need it). Off (the default): statsmodels\' approximate diffuse start, which leaves the first observations out of the likelihood.' }, LEVEL(P0.level));
    const v = await SM.ui.form({
      title: `Structural Model Specification: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:structural',
      lead: 'y = level + seasonal + cycle + autoregressive + regression on the inputs + irregular, each part a small state space model (statsmodels\' UnobservedComponents), fitted by maximum likelihood with the Kalman filter. Missing values are skipped. The cycle\'s period is bounded; statsmodels\' default is 1.5 to 12 years for yearly, quarterly and monthly data.',
      fields,
      validate: (x) => {
        if (x.seas !== 'none' && !(Number.isInteger(x.period) && x.period >= 2)) return 'Seasonal Period: a whole number from 2';
        if (x.seas === 'trig' && x.harmonics != null && !(Number.isInteger(x.harmonics) && x.harmonics >= 1 && x.harmonics <= Math.floor(x.period / 2))) return `Harmonics: from 1 to ${Math.floor(x.period / 2)}`;
        if (x.cycle && x.cycleLo != null && !(x.cycleLo >= 2)) return 'Cycle period from: at least 2';
        if (x.cycle && x.cycleLo != null && x.cycleHi != null && !(x.cycleHi > x.cycleLo)) return 'Cycle period to: above the lower bound';
        if (!(Number.isInteger(x.ar) && x.ar >= 0 && x.ar <= 12)) return 'Autoregressive Order: a whole number from 0 to 12';
        return levelOk(x);
      },
    });
    if (!v) return;
    const chosen = inputs.filter((c, i) => v[`use${i}`]).map((c) => c.name);
    const spec = { kind: 'uc', trend: v.trend, level: v.level, exact: !!v.exact };
    if (v.seas === 'dummy') { spec.seasonal = Math.round(v.period); spec.stochSeasonal = !!v.stochSeasonal; }
    if (v.seas === 'trig') { spec.freqPeriod = Math.round(v.period); if (v.harmonics) spec.freqHarmonics = v.harmonics; spec.stochFreq = !!v.stochSeasonal; }
    if (v.cycle) { spec.cycle = true; spec.stochCycle = !!v.stochCycle; spec.damped = !!v.damped; if (v.cycleLo != null) spec.cycleLo = v.cycleLo; if (v.cycleHi != null) spec.cycleHi = v.cycleHi; }
    if (v.ar) spec.ar = v.ar;
    if (chosen.length) spec.inputs = chosen;
    addModels(ctx, col, [spec]);
  }

  /* ---- Regime Switching… ------------------------------------------------------------------------------------------------------- */
  async function regimeDialog(ctx, col, S, preset = null) {
    const P0 = preset || {};
    const v = await SM.ui.form({
      title: `Regime Switching Specification: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:regime',
      lead: 'k regimes, each with its own mean (and trend), variance or AR coefficients, and a Markov chain that moves between them (Hamilton 1989; statsmodels\' MarkovRegression, or MarkovAutoregression with an AR part). The likelihood has local maxima: the fit starts from statsmodels\' default and from random starts (a fixed seed) and keeps the best.',
      fields: [
        { key: 'k', label: 'Number of Regimes', type: 'select', value: String(P0.k || 2), choices: [['2', '2'], ['3', '3']],
          help: '2 (the default: expansion and recession, calm and turbulent) or 3. More regimes need more data (ten values per regime at least) and have more local maxima.' },
        { key: 'order', label: 'Autoregressive Order (0: switching regression)', type: 'number', value: P0.order || 0, helpLabel: 'Autoregressive Order',
          help: '0 (the default): statsmodels\' MarkovRegression, the series about the regime\'s mean with no dynamics of its own. 1 to 8: MarkovAutoregression, an AR(p) about the regime\'s mean.' },
        { key: 'trend', label: 'Mean', type: 'select', value: P0.trend || 'c', choices: [['c', 'Intercept'], ['ct', 'Intercept and linear trend'], ['n', 'None (only the variance switches)']],
          help: 'What each regime\'s mean is made of: an intercept (the default), an intercept and a linear trend, or none, when only the variance (or the AR part) can switch.' },
        { key: 'swTrend', label: 'Switching mean (and trend)', type: 'check', value: P0.swTrend !== false, help: 'Each regime has its own intercept (and trend); off, they share one. On by default.' },
        { key: 'swVar', label: 'Switching variance', type: 'check', value: !!P0.swVar, help: 'Each regime has its own variance, for calm and turbulent periods. Off by default.' },
        { key: 'swAr', label: 'Switching AR coefficients', type: 'check', value: !!P0.swAr, help: 'With an Autoregressive Order above 0: each regime has its own AR coefficients; off, they share them.' },
        { key: 'starts', label: 'Random Starts', type: 'number', value: P0.starts ?? 5,
          help: 'How many random starting points, 0 to 50 (5 by default), beside statsmodels\' default start and one with the regimes at the quantiles of the series: each is fitted and the highest likelihood kept (the Starts table shows them all). The draws have a fixed seed, so the report is the same every time; more starts find the best maximum more surely, and take longer.' },
      ],
      validate: (x) => {
        if (!(Number.isInteger(x.order) && x.order >= 0 && x.order <= 8)) return 'Autoregressive Order: a whole number from 0 to 8';
        if (!(Number.isInteger(x.starts) && x.starts >= 0 && x.starts <= 50)) return 'Random Starts: a whole number from 0 to 50';
        const sw = (x.swTrend && x.trend !== 'n') || x.swVar || (x.order > 0 && x.swAr);
        return sw ? null : 'Nothing switches: check a switching mean, variance or AR part';
      },
    });
    if (!v) return;
    const spec = { kind: 'markov', k: +v.k, order: v.order, trend: v.trend, swTrend: !!v.swTrend && v.trend !== 'n', swVar: !!v.swVar, swAr: !!v.swAr && v.order > 0, starts: v.starts };
    addModels(ctx, col, [spec]);
  }

  /* ---- Theta Model… ------------------------------------------------------------------------------------------------------------ */
  async function thetaDialog(ctx, col, S, preset = null) {
    const P0 = preset || {};
    const period = P0.period || periodOf(ctx, S);
    const v = await SM.ui.form({
      title: `Theta Model: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:theta',
      lead: 'The theta method (Assimakopoulos and Nikolopoulos 2000) with statsmodels\' ThetaModel: the series is deseasonalized if it tests seasonal, simple exponential smoothing gives α and a linear trend b0, and the forecast weights the trend line by (θ − 1)/θ. θ = 2 is the classic method, simple exponential smoothing with drift.',
      fields: [
        { key: 'theta', label: 'θ, Theta (at least 1)', type: 'number', value: P0.theta || 2, helpLabel: 'θ, Theta',
          help: 'How much the forecasts follow the trend line: it is weighted by (θ − 1)/θ. 2 (the default) is the classic method, simple exponential smoothing with drift; 1 is simple exponential smoothing alone; a larger θ follows the trend more closely.' },
        { key: 'deseasonalize', label: 'Deseasonalize', type: 'check', value: P0.deseasonalize ?? period >= 2,
          help: 'Takes the seasonal pattern out before the fit (seasonal_decompose) and puts it back into the forecasts. On at first; a series shorter than two periods is left as it is.' },
        { key: 'period', label: 'Seasonal Period', type: 'number', value: period, help: 'The observations per period used to deseasonalize, a whole number from 2.' },
        { key: 'useTest', label: 'Test for seasonality first (10%)', type: 'check', value: P0.useTest !== false, helpLabel: 'Test for seasonality first',
          help: 'On (the default): the series is deseasonalized only when its autocorrelation at the seasonal lag is significant at 10%, as statsmodels tests it. Off: always, when Deseasonalize is on.' },
        { key: 'method', label: 'Deseasonalizing', type: 'select', value: P0.method || 'auto', choices: [['auto', 'Automatic: multiplicative if every value is above zero'], ['multiplicative', 'Multiplicative'], ['additive', 'Additive']],
          help: 'How the seasonal pattern is taken out: Automatic (multiplicative when every value is above zero, else additive), Multiplicative (a swing that grows with the level) or Additive (a swing of one size).' },
        { key: 'mle', label: 'Estimate by maximum likelihood (an IMA(1, 1) with drift)', type: 'check', value: !!P0.mle, helpLabel: 'Estimate by maximum likelihood',
          help: 'Estimates α and the drift together, by maximum likelihood of the IMA(1, 1) with drift that the method is. Off (the default): α from simple exponential smoothing and the drift from a linear trend, the original method.' },
        LEVEL(P0.level),
      ],
      validate: (x) => (!(x.theta >= 1) ? 'θ: at least 1' : x.deseasonalize && !(Number.isInteger(x.period) && x.period >= 2) ? 'Seasonal Period: a whole number from 2' : levelOk(x)),
    });
    if (!v) return;
    addModels(ctx, col, [{ kind: 'theta', theta: v.theta, deseasonalize: !!v.deseasonalize, period: v.deseasonalize ? Math.round(v.period) : 0, useTest: !!v.useTest, method: v.method, mle: !!v.mle, level: v.level }]);
  }

  /* ---- ARDL… ---------------------------------------------------------------------------------------------------------------------- */
  const ARDL_CASES = { n: [['1', '1: no intercept, no trend']], c: [['3', '3: unrestricted intercept'], ['2', '2: restricted intercept (in the level relation)']], ct: [['4', '4: restricted trend (in the level relation)'], ['5', '5: unrestricted intercept and trend']] };

  function parseOrders(text, n) {
    const t = String(text ?? '').trim();
    if (!t) return null;
    const parts = t.split(/[\s,;]+/).filter(Boolean);
    if (parts.length !== n + 1 || !parts.every((p) => /^\d+$/.test(p) || p === '-')) return undefined;
    return parts.map((p) => (p === '-' ? null : +p));
  }

  async function ardlDialog(ctx, col, S, preset = null) {
    const inputs = ctx.roles('inputs').filter((c) => c.id !== col.id);
    if (!inputs.length) { SM.ui.toast('ARDL models need Input List columns: relaunch with inputs'); return; }
    const P0 = preset || {};
    const pre = new Set(P0.inputs || []);
    const fields = [];
    inputs.forEach((c, i) => fields.push({ key: `use${i}`, label: `Input ${c.name}`, type: 'check', value: preset ? pre.has(c.name) : true, helpLabel: 'Input (each column)',
      help: 'Whether that Input List column enters the model, at least one and at most nine; all of them at first.' }));
    const ordersText = P0.order ? [P0.order.p || 0, ...(P0.inputs || []).map((c) => (P0.order.q && P0.order.q[c] != null ? P0.order.q[c] : '-'))].join(', ') : '';
    fields.push(
      { key: 'maxlag', label: `Largest lag of ${col.name}, p`, type: 'number', value: P0.maxlag || 4, helpLabel: 'Largest lag of the series, p',
        help: 'The most lags of the series itself that the order search tries, 1 to 24 (4 by default).' },
      { key: 'maxorder', label: 'Largest lag of the inputs, q', type: 'number', value: P0.maxorder ?? 4, help: 'The most lags of each input the search tries, 0 to 24 (4 by default); 0 keeps each input\'s current value only.' },
      { key: 'ic', label: 'Choose the orders by', type: 'select', value: P0.ic || 'aic', choices: [['aic', 'AIC'], ['bic', 'BIC']],
        help: 'The criterion of the order search (statsmodels\' ardl_select_order), every candidate fitted on the same sample: AIC (the default), or BIC, which chooses shorter lags.' },
      { key: 'glob', label: 'Search every subset of lags (slow)', type: 'check', value: !!P0.glob, helpLabel: 'Search every subset of lags',
        help: 'Tries every subset of the lags up to the largest, skipping lags in between, instead of the orders 1 to p only; at most 4096 models, so keep the largest lags small. Off by default.' },
      { key: 'orders', label: 'Or fixed orders p, q1, q2 … (- leaves an input out)', type: 'text', value: ordersText, placeholder: 'empty: choose them', helpLabel: 'Fixed orders',
        help: 'Orders to use instead of a search: p for the series, then a q for each input checked, in their order, apart by commas or spaces (such as 2, 1, 0); - leaves that input out. Empty (the default): the search chooses them.' },
      { key: 'trend', label: 'Deterministic Terms', type: 'select', value: P0.trend || 'c', choices: [['c', 'Intercept'], ['ct', 'Intercept and trend'], ['n', 'None']],
        help: 'The regression\'s deterministic terms: an intercept (the default), an intercept and a linear trend, or none. They decide which bounds test cases apply.' },
      { key: 'case', label: 'Bounds Test Case', type: 'select', value: String(P0.case || ''), choices: [['', 'Automatic: 3 with an intercept, 4 with a trend, 1 with neither'], ['1', '1: no intercept, no trend'], ['2', '2: restricted intercept'], ['3', '3: unrestricted intercept'], ['4', '4: restricted trend'], ['5', '5: unrestricted trend']],
        help: 'Where Pesaran, Shin and Smith\'s bounds test puts the deterministic terms: in the level relation (restricted) or outside it. Automatic takes the usual one, 3 with an intercept and 4 with a trend (1 with neither); 2 goes with an intercept and 5 with a trend.' },
      { key: 'causal', label: 'Causal: the inputs from lag 1 on', type: 'check', value: !!P0.causal, helpLabel: 'Causal',
        help: 'Leaves out the inputs\' current values (lag 0), so that the model uses only their past. Off by default.' },
      { key: 'seasonal', label: 'Seasonal dummies', type: 'check', value: !!P0.seasonal,
        help: 'Adds a dummy for each season of the seasonal period (the launch\'s Seasonal Period, else the Time ID\'s, else 12). Off by default; the bounds test refits without them.' },
      LEVEL(P0.level));
    const v = await SM.ui.form({
      title: `ARDL Specification: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:ardl',
      lead: 'The series on its own lags and on the inputs\' current and lagged values, by least squares (statsmodels\' ARDL), with the orders chosen by AIC or BIC; then the long-run coefficients and the bounds test of Pesaran, Shin and Smith (2001) for a level relationship. Forecasts take the inputs\' future values from the rows after the series.',
      fields,
      validate: (x) => {
        const use = inputs.filter((c, i) => x[`use${i}`]);
        if (!use.length) return 'Choose at least one input';
        if (use.length > 9) return 'At most 9 inputs';
        if (!(Number.isInteger(x.maxlag) && x.maxlag >= 1 && x.maxlag <= 24)) return 'Largest lag p: a whole number from 1 to 24';
        if (!(Number.isInteger(x.maxorder) && x.maxorder >= 0 && x.maxorder <= 24)) return 'Largest lag q: a whole number from 0 to 24';
        const ord = parseOrders(x.orders, use.length);
        if (ord === undefined) return `Fixed orders: ${use.length + 1} whole numbers (p, then one for each input), or empty`;
        if (x.glob && 2 ** (x.maxlag + use.length * (x.maxorder + 1)) > 4096) return 'Every subset: that many lags make more than 4096 models; lower p or q';
        if (x.case && !(ARDL_CASES[x.trend] || []).some(([k]) => k === x.case)) return `Bounds Test Case ${x.case} does not go with these deterministic terms: ${ARDL_CASES[x.trend].map(([, l]) => l).join('; ')}`;
        if (x.seasonal && !(periodOf(ctx, S) >= 2)) return 'Seasonal dummies need a seasonal period';
        return levelOk(x);
      },
    });
    if (!v) return;
    const use = inputs.filter((c, i) => v[`use${i}`]).map((c) => c.name);
    const ord = parseOrders(v.orders, use.length);
    const spec = { kind: 'ardl', inputs: use, maxlag: v.maxlag, maxorder: v.maxorder, ic: v.ic, trend: v.trend, level: v.level };
    if (v.glob) spec.glob = true;
    if (ord) spec.order = { p: ord[0], q: Object.fromEntries(use.map((c, i) => [c, ord[i + 1]])) };
    if (v.case) spec.case = +v.case;
    if (v.causal) spec.causal = true;
    if (v.seasonal) { spec.seasonal = true; spec.period = periodOf(ctx, S); }
    addModels(ctx, col, [spec]);
  }

  function fitNew(ctx, col, S, spec) {
    if (spec.kind === 'arima' && spec.inputs) return transferDialog(ctx, col, S, spec);
    if (spec.kind === 'arima') return arimaDialog(ctx, col, S, { seasonal: !!(spec.P || spec.D || spec.Q), preset: spec });
    if (spec.kind === 'smooth') return smoothDialog(ctx, col, S, spec.method, spec);
    if (spec.kind === 'uc') return structuralDialog(ctx, col, S, spec);
    if (spec.kind === 'markov') return regimeDialog(ctx, col, S, spec);
    if (spec.kind === 'theta') return thetaDialog(ctx, col, S, spec);
    if (spec.kind === 'ardl') return ardlDialog(ctx, col, S, spec);
    if (spec.kind === 'bench') return benchDialog(ctx, col, S, [spec.method], spec);
    if (spec.kind === 'sma') return smaDialog(ctx, col, S, spec);
    if (spec.kind === 'avg') return averageDialog(ctx, col, S, null, spec);
    return etsDialog(ctx, col, S);
  }

  async function differenceDialog(ctx, col, S) {
    const v = await SM.ui.form({
      title: `Differencing Specification: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:difference',
      lead: 'w_t = (1 − B)^d (1 − B^s)^D y_t. Each Estimate adds a Difference report.',
      fields: [
        { key: 'd', label: 'Nonseasonal Differencing Order, d', type: 'select', value: '1', choices: [['0', '0'], ['1', '1'], ['2', '2']],
          help: 'How many times the series is differenced, (1 − B)^d: 1 (the default) turns a series that wanders, with a unit root, into its changes; 2 rarely helps. Its ADF tests and autocorrelations then say whether that was enough.' },
        { key: 'D', label: 'Seasonal Differencing Order, D', type: 'select', value: '0', choices: [['0', '0'], ['1', '1'], ['2', '2']],
          help: 'Seasonal differences (1 − B^s)^D, each value less the one a period before: 1 takes out a seasonal pattern that repeats from period to period. 0 by default.' },
        { key: 's', label: 'Observations per Period, s', type: 'number', value: periodOf(ctx, S), help: 'The seasonal period of the seasonal differences, at least 2 when D is above 0; it starts at the Seasonal Period of the launch, or the Time ID\'s.' },
      ],
      validate: (x) => (+x.D > 0 && !(x.s >= 2) ? 'Observations per Period: at least 2' : null),
    });
    if (!v) return;
    const list = ctx.opt('diffs', [], scopeOf(col)).slice();
    list.push({ id: list.reduce((m, x) => Math.max(m, x.id || 0), 0) + 1, d: +v.d, D: +v.D, s: Math.round(v.s || 0) });
    ctx.set('diffs', list, scopeOf(col));
  }

  async function addDecomp(ctx, col, S, kind) {
    const period = periodOf(ctx, S);
    let spec = { kind };
    if (kind === 'cycle') {
      const v = await SM.ui.form({ title: `Define Cycle: ${col.name}`, info: 'p:timeseries:decomposition', fields: [
        { key: 'units', label: 'Units per Cycle', type: 'number', value: period, help: 'The length U of the cycle in observations, above 1 (12 for a yearly cycle of monthly data); it starts at the seasonal period. The amplitude and the phase of C + A cos(2πt/U + P) are fitted by least squares.' },
        { key: 'constant', label: 'Subtract a constant', type: 'check', value: true, help: 'On (the default): the cycle has a constant C, fitted with it and removed with it, so the decycled series is centred near zero. Off: the cosine alone, and the series keeps its level.' }],
      validate: (x) => (x.units > 1 ? null : 'Units per Cycle: above 1') });
      if (!v) return;
      spec = { kind, units: v.units, constant: !!v.constant };
    } else if (kind === 'classical') {
      const v = await SM.ui.form({ title: `Seasonal Decomposition: ${col.name}`, info: 'p:timeseries:decomposition', fields: [
        { key: 'period', label: 'Period', type: 'number', value: period, help: 'The seasonal period, at least 2: the moving average of the trend runs over one period. The series needs two full periods and one value more.' },
        { key: 'model', label: 'Decomposition Type', type: 'select', value: 'additive', choices: [['additive', 'Additive'], ['multiplicative', 'Multiplicative']],
          help: 'Additive (the default): y = trend + seasonal + irregular, a seasonal swing of one size. Multiplicative: y = trend × seasonal × irregular, a swing that grows with the level; every value must be above zero.' }],
      validate: (x) => (x.period >= 2 ? null : 'Period: at least 2') });
      if (!v) return;
      spec = { kind, period: Math.round(v.period), model: v.model };
    } else if (kind === 'stl') {
      const v = await SM.ui.form({ title: `STL Decomposition: ${col.name}`, info: 'p:timeseries:decomposition', fields: [
        { key: 'period', label: 'Period', type: 'number', value: period, help: 'The seasonal period, at least 2 (12 for monthly data); the series needs two full periods and one value more.' },
        { key: 'robust', label: 'Robust (downweights outliers)', type: 'check', value: false, helpLabel: 'Robust',
          help: 'STL\'s robust fit: values far from the fit get less weight, so an outlier ends in the irregular part instead of bending the trend and the seasonal. Off by default.' }],
      validate: (x) => (x.period >= 2 ? null : 'Period: at least 2') });
      if (!v) return;
      spec = { kind, period: Math.round(v.period), robust: !!v.robust };
    }
    const list = ctx.opt('decomps', [], scopeOf(col)).slice();
    spec.id = list.reduce((m, x) => Math.max(m, x.id || 0), 0) + 1;
    list.push(spec);
    ctx.set('decomps', list, scopeOf(col));
  }

  /* The series behind a red triangle item: the dialogs want the period and the values. */
  async function seriesOf(ctx, col) {
    try { return await ctx.call('timeseries.series', basePayload(ctx, col)); } catch (e) { return { values: [], period_auto: null }; }
  }

  /* ---- the red triangle of a series ------------------------------------------------------------------------------------------------------ */
  function seriesMenu(ctx, col) {
    const sc = scopeOf(col);
    const o = (k, d) => ctx.opt(k, d, sc);
    const hasInputs = ctx.roles('inputs').some((c) => c.id !== col.id);
    const withS = (fn) => async () => { const S = await seriesOf(ctx, col); if (S.error) { SM.ui.toast(S.error, { error: true }); return; } return fn(S); };
    return [
      { label: 'Graph', submenu: () => [
        ctx.check('Time Series Graph', 'graph', sc, true), ctx.check('Show Points', 'points', sc, true),
        ctx.check('Connecting Lines', 'lines', sc, true), ctx.check('Mean Line', 'meanLine', sc, false),
      ] },
      ctx.check('Autocorrelation', 'acf', sc, true),
      ctx.check('Partial Autocorrelation', 'pacf', sc, true),
      ctx.check('Variogram', 'variogram', sc, false),
      ctx.check('AR Coefficients', 'arcoef', sc, false),
      ctx.check('Spectral Density', 'spectral', sc, false),
      ctx.check('Stationarity Tests (ADF, KPSS)', 'stationarity', sc, true),
      { label: 'Zivot-Andrews Test', checked: !!o('stationarity', true) && zivotOn(ctx, col), action: () => { if (!o('stationarity', true)) { ctx.set('zivot', true, sc, { rerun: false }); ctx.set('stationarity', true, sc); } else ctx.set('zivot', !zivotOn(ctx, col), sc); } },
      { label: 'Runs Test', submenu: () => [...Object.entries(RUNS_ABOUT).map(([k, label]) => ({ label, checked: o('runs', null) === k, action: () => ctx.set('runs', o('runs', null) === k ? null : k, sc) })),
        { separator: true }, { label: 'Remove', disabled: o('runs', null) == null, action: () => ctx.set('runs', null, sc) }] },
      { separator: true },
      { label: 'Difference…', action: withS((S) => differenceDialog(ctx, col, S)) },
      { label: 'Decomposition', submenu: () => [
        { label: 'Remove Linear Trend', action: withS((S) => addDecomp(ctx, col, S, 'trend')) },
        { label: 'Remove Cycle…', action: withS((S) => addDecomp(ctx, col, S, 'cycle')) },
        { label: 'Seasonal Decomposition…', action: withS((S) => addDecomp(ctx, col, S, 'classical')) },
        { label: 'STL Decomposition…', action: withS((S) => addDecomp(ctx, col, S, 'stl')) },
        { label: 'X11', disabled: true, title: 'X-11 needs the Census Bureau\'s X-13ARIMA-SEATS program, which does not run in the browser' },
      ] },
      { label: 'Filters', submenu: () => FILTERS.map(([k, label]) => ({ label: `${label}…`, action: withS((S) => filterDialog(ctx, col, S, k)) })) },
      { label: 'Show Lag Plot', checked: o('lagPlot', null) != null, action: () => ctx.set('lagPlot', o('lagPlot', null) != null ? null : 1, sc) },
      ctx.check('Seasonal Subseries Plot', 'subseries', sc, false),
      { label: 'Cross Correlation', checked: !!o('ccf', false), disabled: !hasInputs, action: () => ctx.set('ccf', !o('ccf', false), sc) },
      hasInputs ? ctx.check('Input Time Series Panel', 'inputPanel', sc, true) : null,
      { separator: true },
      { label: 'ARIMA…', action: withS((S) => arimaDialog(ctx, col, S)) },
      { label: 'Seasonal ARIMA…', action: withS((S) => arimaDialog(ctx, col, S, { seasonal: true })) },
      { label: 'ARIMA Model Group…', action: withS((S) => groupDialog(ctx, col, S)) },
      { label: 'Transfer Function…', disabled: !hasInputs, action: withS((S) => transferDialog(ctx, col, S)) },
      { label: 'Smoothing Models', submenu: () => [{ label: 'Simple Moving Average…', action: withS((S) => smaDialog(ctx, col, S)) },
        ...SMOOTH.map(([k, label]) => ({ label: `${label}…`, action: withS((S) => smoothDialog(ctx, col, S, k)) }))] },
      { label: 'State Space Smoothing Models…', action: withS((S) => etsDialog(ctx, col, S)) },
      { label: 'Benchmark Models', submenu: () => [
        { label: 'Naive…', action: withS((S) => benchDialog(ctx, col, S, ['naive'])) },
        { label: 'Seasonal Naive…', action: withS((S) => benchDialog(ctx, col, S, ['snaive'])) },
        { label: 'Drift…', action: withS((S) => benchDialog(ctx, col, S, ['drift'])) },
        { separator: true },
        { label: 'All Three…', action: withS((S) => benchDialog(ctx, col, S, ['naive', 'snaive', 'drift'])) },
      ] },
      { label: 'Structural Model…', action: withS((S) => structuralDialog(ctx, col, S)) },
      { label: 'Regime Switching…', action: withS((S) => regimeDialog(ctx, col, S)) },
      { label: 'Theta Model…', action: withS((S) => thetaDialog(ctx, col, S)) },
      { label: 'ARDL…', disabled: !hasInputs, action: withS((S) => ardlDialog(ctx, col, S)) },
      { label: 'Averaged Forecast…', disabled: averageable(o('models', [])).length < 2, action: withS((S) => averageDialog(ctx, col, S)) },
      { label: 'Rolling-Origin Cross-Validation…', disabled: !o('models', []).length, action: withS((S) => cvDialog(ctx, col, S)) },
      { separator: true },
      { label: 'Combine and Save Forecasts from Models', disabled: !o('models', []).length, action: withS(async (S) => {
        const list = o('models', []);
        const base = basePayload(ctx, col);
        const h = horizon(ctx);
        const held = holdbackOn(ctx) && S.n - h >= 8 ? h : 0;
        const season = knownPeriod(ctx, S) || 1;
        const results = await fitAll(ctx, base, list, h, held, season);
        const refits = held && refitOn(ctx) ? await fitAll(ctx, base, list, h, 0, season) : null;
        combineForecasts(ctx, col, { ...S, x: fx(S, S.t) }, list, results, { held, refits });
      }) },
      { label: 'Save Spectral Density', action: async () => { const r = await ctx.call('timeseries.spectral', basePayload(ctx, col)); if (r.error) SM.ui.toast(r.error, { error: true }); else saveSpectral(col, r); } },
    ].filter(Boolean);
  }

  function globalItems(ctx) {
    return [
      { label: 'Forecast on Holdback', checked: holdbackOn(ctx), action: () => ctx.set('holdback', !holdbackOn(ctx)) },
      { label: 'Refit on All Rows', checked: refitOn(ctx), disabled: !holdbackOn(ctx), title: 'With Forecast on Holdback: every model fitted again on all the values, for the forecasts after the end',
        action: () => ctx.set('refit', !ctx.opt('refit', false)) },
      { label: 'Number of Forecast Periods…', action: async () => { const v = await SM.ui.form({ title: 'Number of Forecast Periods', fields: [{ key: 'n', label: 'Forecast periods for every model', type: 'number', value: horizon(ctx),
        help: 'How many periods after the end of the series every model forecasts, with its prediction interval: 0 to 1000 (0: none). With Forecast on Holdback, how many values at the end are held back and forecast instead. It starts at the launch\'s Forecast Periods, 25 by default.' }], validate: (x) => (x.n >= 0 && x.n <= 1000 ? null : 'from 0 to 1000') }); if (v) ctx.set('forecast', Math.round(v.n)); } },
      { label: 'Maximum Iterations…', action: async () => { const v = await SM.ui.form({ title: 'Maximum Iterations', lead: 'For the ARIMA and state space fits from now on.', fields: [{ key: 'n', label: 'Maximum iterations', type: 'number', value: maxiter(ctx),
        help: 'The most iterations of the optimizer, 5 to 10 000 (200 by default), for the ARIMA, transfer function and structural model fits; the state space smoothing fits take at least 200 and the regime-switching fits at most 500. Raise it when a model reports that its fit did not converge.' }], validate: (x) => (x.n >= 5 && x.n <= 10000 ? null : 'from 5 to 10000') }); if (v) ctx.set('maxiter', Math.round(v.n)); } },
    ];
  }

  /* ---- topics for the (i) --------------------------------------------------------------------------------------------------------------------------- */
  const topics = {
    'p:timeseries': {
      kicker: 'Analyze > Specialized Modeling', title: 'Time Series',
      lead: 'One series in time order: its graph, autocorrelations and stationarity tests; differencing, decomposition and filters; the spectral density and the seasonal subseries plot; and ARIMA, seasonal ARIMA, transfer function, smoothing, moving average and state space smoothing models with forecasts, compared in one table, also on forecasts of held-back values (Forecast on Holdback). Beyond JMP: benchmarks, averaged forecasts, rolling-origin cross-validation, runs tests, structural models, regime switching, the Theta model, ARDL models with the bounds test, and the Zivot-Andrews test.',
      sections: [
        { heading: 'Roles', choices: [['Y, Time Series', 'The series, one report each (continuous columns).'], ['Input List', 'Numeric input series for cross correlations, transfer functions, structural and ARDL models; indicators such as a promotion flag work.'], ['X, Time ID', 'Orders the rows and labels the time axis; a date column gives the calendar frequency, the seasonal period and the forecast dates.'], ['By', 'A report for each level.']] },
        { heading: 'Options', choices: [['Forecast Periods', 'How many periods each model forecasts (default 25); with Forecast on Holdback, how many values at the end are held back.'], ['Forecast on Holdback', 'Every model fitted without the last values and compared on its forecasts of them.'], ['Autocorrelation Lags', 'How many lags the correlations go to (default 25; n/4 is a common choice).'], ['Seasonal Period', 'The default observations per period in the dialogs; empty takes it from the Time ID (12 for monthly data).']] },
        { heading: 'Missing and excluded rows', text: 'Excluded rows count as missing values, as in JMP, so the spacing of the series is kept; dates missing from a regular calendar are inserted as missing too. ARIMA models skip missing values in the likelihood; the smoothing and decomposition methods fill them by interpolation, and say so. A model\'s Save Columns gives a missing value its one-step-ahead prediction too, wherever the model gives one (the Kalman filter of the ARIMA and structural models predicts through it; the smoothing models, the benchmarks and the moving average from the values before it), with its limits; its residual stays empty.' },
        { heading: 'Differences from JMP', list: ['ARIMA: statsmodels\' exact likelihood; AIC and SBC count the parameters as JMP does (statsmodels also counts σ², shown in the notes). MA coefficients have statsmodels\' sign, the opposite of JMP\'s.', 'Smoothing models: weights and starting states by least squares (holtwinters), not JMP\'s ARIMA-equivalent fit; prediction intervals from the same moving-average weights JMP uses. Constraints: Zero To One and Custom (each weight fixed or bounded, within 0 and 1: statsmodels takes no weights outside them, and keeps the trend weight at or below the level weight); JMP\'s Unconstrained and Stable Invertible are not available.', 'Box-Cox: JMP\'s is a launch option for the whole platform; here it is an option of each smoothing model, whose predictions, forecasts and limits are transformed back.', 'Forecast on Holdback also works for the Simple Moving Average (JMP leaves it out), and adds the mean error and MASE to JMP\'s RMSE, MSE, MAPE and MAE; Refit on All Rows gives the forecasts after the end.', 'ADF lags by AIC; KPSS, STL and state space model selection by AICc are additions. X-11 is not available.'] },
        { heading: 'Beyond JMP', choices: [['Benchmark Models', 'Naive, Seasonal Naive and Drift forecasts, the ones a model should beat.'], ['Averaged Forecast…', 'The mean of several models\' forecasts and limits, as a model of its own.'], ['Rolling-Origin Cross-Validation…', 'Every model refitted at several origins, and the RMSE, MAE and MAPE of its forecasts from each.'], ['Runs Test', 'Randomness about the mean, the median or zero, of the series and of each model\'s residuals.'], ['Structural Model…', 'Level, trend, seasonal, cycle and AR parts with their smoothed components (UnobservedComponents).'], ['Regime Switching…', 'Markov switching means, variances and AR parts, with regime probabilities.'], ['Filters', 'Hodrick-Prescott, Baxter-King and Christiano-Fitzgerald trend and cycle.'], ['Seasonal Subseries Plot', 'Each season\'s values over the years with their mean.'], ['Theta Model…', 'The theta method\'s forecasts.'], ['ARDL…', 'Distributed lags of the inputs, the long run and the bounds test for cointegration.'], ['Zivot-Andrews Test', 'A unit root test that allows one break, with its date, in Stationarity Tests.']] },
      ],
      more: MORE,
    },
    'p:timeseries:timeid': { kicker: 'Time Series', title: 'X, Time ID', lead: 'The column that orders the series and labels the time axis. A date column (Column Info > Format: Date) gives a date axis; its calendar frequency is found with pandas.infer_freq, also when a few dates have no row, and sets the seasonal period (12 for monthly, 4 for quarterly, 52 for weekly …) and the dates of the forecasts. A numeric Time ID continues its step; without one the row number is the time.', more: MORE },
    'p:timeseries:diagnostics': {
      kicker: 'Time Series', title: 'Time Series Basic Diagnostics',
      lead: 'The autocorrelation r_k = c_k/c_0 with c_k = (1/N) Σ (y_t − ȳ)(y_t−k − ȳ) (statsmodels\' acf), its ±2 large-lag standard errors √((1 + 2Σ r_i²)/N) (Bartlett), and the Ljung-Box Q of lags 1 to k with its p-value (acorr_ljungbox).',
      sections: [
        { heading: 'Partial autocorrelation', text: 'By the Levinson-Durbin recursion on the autocorrelations (pacf method "ldb"), with ±2/√N bands.' },
        { heading: 'Variogram and AR coefficients', text: 'The variogram (1 − r_k)/(1 − r_1) is the variance of differences k apart over that of differences one apart: it levels off for a stationary series and keeps climbing for a nonstationary one. The AR coefficients are those of the AR(K) fit by Yule-Walker.' },
        { heading: 'Reading them', text: 'A slowly decaying ACF says difference the series; an ACF that cuts off after lag q suggests MA(q); a PACF that cuts off after lag p suggests AR(p).' },
      ],
      more: MORE,
    },
    'p:timeseries:stationarity': {
      kicker: 'Time Series', title: 'Stationarity tests',
      lead: 'The augmented Dickey-Fuller test (adfuller) against a random walk with zero mean, a single mean or a trend, as JMP\'s Zero Mean, Single Mean and Trend ADF; the lags are chosen by AIC and the p-values are MacKinnon\'s. A small p-value rejects the unit root.',
      sections: [{ heading: 'KPSS', text: 'kpss tests the reverse null, stationarity around a level or a trend; a small p-value speaks against stationarity. Its p-values are interpolated in a table from 0.01 to 0.1 and shown as bounds outside it.' }],
      more: MORE,
    },
    'p:timeseries:difference': { kicker: 'Time Series', title: 'Difference', lead: 'The differenced series w_t = (1 − B)^d (1 − B^s)^D y_t (statsmodels.tsa.statespace.tools.diff) with its own graph, ADF tests and correlations, to choose the d and D of an ARIMA model. Save writes it to the table; the first d + sD values are missing.', more: MORE },
    'p:timeseries:decomposition': {
      kicker: 'Time Series', title: 'Decomposition',
      lead: 'Remove Linear Trend fits b0 + b1 t by least squares; Remove Cycle fits C + A cos(2πt/U + P). Each adds the report of the series with the trend or cycle removed; Save writes that series to the table.',
      sections: [{ heading: 'Seasonal', text: 'Seasonal Decomposition is statsmodels\' seasonal_decompose (a centred moving average for the trend, averages by season, additive or multiplicative); STL decomposes by loess and can downweight outliers. Save Columns writes the adjusted series, trend, seasonal and irregular parts, as JMP\'s X11 does. X11 itself needs a program that does not run in the browser.' }],
      more: MORE,
    },
    'p:timeseries:spectral': { kicker: 'Time Series', title: 'Spectral Density', lead: 'The periodogram I(f_i) = (N/2)(a_i² + b_i²) at the frequencies i/N, from the least squares Fourier coefficients, and the spectral density: the periodogram smoothed (triangular weights) and scaled by 1/(4π), against frequency and period. The White Noise Test gives Fisher\'s kappa (the largest periodogram value over the mean) with its exact p-value and Bartlett\'s Kolmogorov-Smirnov statistic of the cumulative periodogram.', more: MORE },
    'p:timeseries:lag': {
      kicker: 'Time Series', title: 'Lag Plot',
      lead: 'Each observation against the one p periods earlier. A cloud with no shape says the observations are unrelated at that lag; a line or a curve says they are related. Change p in the box; points are linked to the rows.',
      sections: [{ heading: 'In the report', choices: [['Lag p', 'the lag of the plot, a whole number from 1 (1 at first): type it and press Enter, or leave the box; the plot, the number of pairs and their correlation follow'],
        ['− and +', 'one lag less or more, drawn at once; the lag stays between 1 and n − 2'], ['A point', 'an observation and the one p before it: clicking or dragging selects the later row']] }],
      more: MORE,
    },
    'p:timeseries:ccf': { kicker: 'Time Series', title: 'Cross Correlation', lead: 'The correlation of the series at t + k with an input at t, for k from −K to K (statsmodels\' ccf): peaks at positive lags mean the input leads. The ticks are ±2 standard errors 1/√(n − |k|). Used to choose the lags of a transfer function.', more: MORE },
    'p:timeseries:arima': {
      kicker: 'Time Series', title: 'ARIMA and Seasonal ARIMA',
      lead: 'φ(B)Φ(B^s)(w_t − μ) = θ(B)Θ(B^s)a_t for the differenced series w_t, fitted by exact maximum likelihood with the Kalman filter (statsmodels.tsa.arima.model.ARIMA), which also skips missing values. μ, the Intercept, is the mean of the differenced series; the Constant Estimate is μφ(1)Φ(1).',
      sections: [
        { heading: 'The report', text: 'Model Summary (DF = n − k, the sums of squares, the variance estimate, AIC = −2LL + 2k, SBC = −2LL + k ln n, AICc, RSquare of the one-step-ahead forecasts, MAPE, MAE, stable and invertible), Parameter Estimates with t ratios, the Forecast with its prediction interval, the Residuals with their autocorrelations, and the Iteration History.' },
        { heading: 'Signs and counts', text: 'statsmodels writes the MA polynomial 1 + θ₁B + …, JMP 1 − θ₁B − …, so the MA estimates have opposite signs. k does not count the variance, as in JMP; statsmodels\' own AIC, which does, is in the notes.' },
        { heading: 'Constrain fit', text: 'Keeps the AR polynomials stable and the MA polynomials invertible during the fit (enforce_stationarity, enforce_invertibility).' },
      ],
      more: MORE,
    },
    'p:timeseries:group': { kicker: 'Time Series', title: 'ARIMA Model Group', lead: 'Every ARIMA or seasonal ARIMA model with orders in the ranges given (such as p 0-2), up to 64 models, each added to the Model Comparison table. The report of the best by AIC shows; tick Report in the table for others.', more: MORE },
    'p:timeseries:transfer': { kicker: 'Time Series', title: 'Transfer Function', lead: 'Regression on the input series with ARIMA noise: y_t = μ + Σ ω x_{t−b} + N_t (statsmodels\' ARIMA with exog). Each input enters at its lag b (dead time) and, with numerator order r, at the lags b to b + r. Forecasts need the inputs\' future values: they come from the rows at the end of the table where Y is missing, as in JMP, and the last value is held beyond them. JMP\'s rational (denominator) transfer functions are not available.', more: MORE },
    'p:timeseries:smoothing': {
      kicker: 'Time Series', title: 'Smoothing Models',
      lead: 'Simple, Double (Brown), Linear (Holt), Damped-Trend Linear, Seasonal and Winters exponential smoothing with statsmodels\' holtwinters: the weights and starting states minimise the one-step-ahead squared errors, within JMP\'s constraints (Zero To One, or Custom: each weight fixed or bounded), optionally on the Box-Cox transform of the series. Prediction intervals use the moving-average weights ψ_j of each model\'s ARIMA form, as JMP documents them. Simple Moving Average is in the same menu.',
      sections: [
        { heading: 'Weights', text: 'Level α, trend γ, damping φ and seasonal δ in JMP\'s form; statsmodels\' smoothing_seasonal is δ(1 − α), and Brown\'s α is Holt\'s method with level α(2 − α) and trend α/(2 − α). statsmodels keeps the trend weight at or below the level weight.' },
        { heading: 'Constraints', text: 'Zero To One (the default, as in JMP) estimates every weight within 0 and 1. Custom fixes a weight at a value (it is then not estimated: k counts one weight less, and it has no standard error) or bounds it within limits of your own (holtwinters\' fix_params and bounds). A fixed or bounded δ with α estimated is fitted by a search over α (minimize_scalar), the other weights estimated at each α, as statsmodels\' seasonal weight depends on α.' },
        { heading: 'Box-Cox transformation', text: 'The model is fitted to (y^λ − 1)/λ, or log y at λ = 0, which steadies a swing that grows with the level; the predictions, the forecasts and their limits are transformed back, so the forecasts are medians. The fit statistics are those of the values themselves, and −2LogLikelihood includes the Jacobian −2(λ − 1)Σ log y, so that AIC compares with an untransformed fit. Every value must be above zero.' },
        { heading: 'Differences from JMP', text: 'JMP fits the equivalent ARIMA model, so its estimates and above all its starting values differ; the standard errors here come from the likelihood\'s Hessian with the starting states held. Missing values are filled by interpolation for the fit.' },
      ],
      more: MORE,
    },
    'p:timeseries:ets': {
      kicker: 'Time Series', title: 'State Space Smoothing',
      lead: 'ETS(error, trend, seasonal) models (Hyndman et al. 2008) with additive or multiplicative errors; no, additive (A), additive damped (Ad), multiplicative (M) or multiplicative damped (Md) trend; and no, additive or multiplicative seasonality: up to 30 models, as JMP fits them, by maximum likelihood with statsmodels\' ETSModel, ranked by AICc (with Forecast on Holdback by the RMSE of their forecasts of the held-back values). Their likelihood is not comparable with the ARIMA models\', as JMP also warns. Multiplicative parts need every value above zero and get simulated prediction intervals (a fixed seed). The multiplicative trends are off at first: they can forecast too far.',
      sections: [{ heading: 'In the report', choices: [['A line of the selection table', 'click it to show that model\'s report, and its forecasts in the Model Comparison plots; the best by AICc (★) shows at first. The Report and Graph boxes of Model Comparison hide them again']] }],
      more: MORE,
    },
    'p:timeseries:comparison': {
      kicker: 'Time Series', title: 'Model Comparison',
      lead: 'Every fitted model with DF, variance, AIC, SBC, AICc, RSquare, −2LogLikelihood, AIC weights, MAPE and MAE, sorted by AIC; with Forecast on Holdback instead the RMSE, MSE, MAPE, MAE, mean error and MASE of each model\'s forecasts of the held-back values, sorted by RMSE, as JMP shows them. Report shows the model\'s report; Graph overlays its forecasts, prediction interval and residual autocorrelations in the plots below. The red triangle removes or hides models, holds values back, averages models, cross-validates them, and saves all forecasts in one new table.',
      sections: [{ heading: 'In the report', choices: [['Report', 'the box of a model: checked, its report (Model Summary, Parameter Estimates, Forecast, Residuals) shows below the table. Every model\'s is checked at first, but only the best of a model group (by AIC, or AICc for state space smoothing)'],
        ['Graph', 'the box of a model: checked, its one-step-ahead predictions, forecasts and prediction interval join the forecast plot, and its residual autocorrelations the two small plots, in the model\'s colour'],
        ['A column heading', 'click it to sort the models by that statistic, again to reverse the order'], ['Right click the table', 'Copy Table, or Make into Data Table']] },
        { heading: 'Forecast on Holdback', text: 'With values held back (the launch option, or the red triangle), the columns are the statistics of each model\'s forecasts of them: RMSE, MSE, MAPE, MAE, the mean error, MASE and N, sorted by RMSE; the code under the table computes them. Refit on All Rows adds a plot of every model\'s forecasts after the end, fitted again on all the values.' }],
      more: MORE,
    },
    'p:timeseries:structural': {
      kicker: 'Time Series', title: 'Structural Model',
      lead: 'A structural (unobserved components) model writes the series as a sum of parts, each a small state space model: y = level + seasonal + cycle + autoregressive + β\'x + irregular. statsmodels\' UnobservedComponents fits the variances of their disturbances (and the cycle\'s frequency and damping, the AR coefficients, the input coefficients) by maximum likelihood with the Kalman filter, which also skips missing values.',
      sections: [
        { heading: 'The parts', choices: [['Level and trend', 'From a fixed intercept to a local linear trend, whose level and slope both follow random walks (statsmodels\' twelve specifications); a variance of 0 fixes that part.'], ['Seasonal', 'Seasonal dummies summing to zero over the period, or a trigonometric seasonal of sines and cosines (fewer harmonics give a smoother pattern); stochastic ones may change over time.'], ['Cycle', 'A (damped) stochastic cycle whose period is estimated within bounds; statsmodels bounds it to 1.5 to 12 years for yearly, quarterly and monthly data.'], ['Autoregressive', 'An AR(p) part in place of, or besides, the white-noise irregular.'], ['Inputs', 'Regression on the Input List columns; forecasts take their future values from the rows after the series.']] },
        { heading: 'The report', text: 'Parameter estimates, the fit statistics that join Model Comparison (k leaves one variance out, as JMP does for ARIMA models), the Components: each smoothed part with its band, forecasts with prediction intervals, and the residuals (one-step prediction errors). Save Components writes the smoothed parts to the table.' },
        { heading: 'What to watch', text: 'The nonstationary states start diffuse: by default statsmodels\' approximate diffuse initialization leaves the first observations out of the likelihood; Exact diffuse initialization gives Durbin and Koopman\'s exact likelihood (the published Nile estimates need it). Cycle models often have several local maxima: try other bounds on the period. A variance estimated at 0 is at the edge of its range, where its z test is conservative.' },
      ],
      more: MORE,
    },
    'p:timeseries:regime': {
      kicker: 'Time Series', title: 'Regime Switching',
      lead: 'A Markov switching model (Hamilton 1989): the series has k regimes, such as expansion and recession, each with its own mean (and trend), variance or AR coefficients, and a hidden Markov chain moves between them with fixed transition probabilities. statsmodels\' MarkovRegression (no AR part) and MarkovAutoregression fit it by maximum likelihood with the Hamilton filter; Kim\'s smoother gives the probability of each regime at each time.',
      sections: [
        { heading: 'The report', text: 'The parameters with their regime, the Regimes table (the probability of staying, the expected duration 1/(1 − P), how long each regime is the most likely), the transition matrix, the series shaded by the most likely regime, the smoothed (and filtered) probabilities, and the one-step-ahead predictions. Save Regime Probabilities writes them to the table. statsmodels does not forecast these models.' },
        { heading: 'Local maxima', text: 'The likelihood of a regime-switching model often has several maxima, and some starts fail. The fit starts from statsmodels\' default and from Random Starts drawn around it (uniform ±0.5 on the unconstrained parameters, a fixed seed, so the report is the same every time) and keeps the highest likelihood; the Starts table shows where each ended. The regimes are numbered as statsmodels numbers them, from 0: which is which can change with the data.' },
        { heading: 'Missing values', text: 'The Hamilton filter needs every value: missing and excluded values are filled by linear interpolation, and left out of the fit statistics.' },
      ],
      more: MORE,
    },
    'p:timeseries:filters': {
      kicker: 'Time Series', title: 'Filters',
      lead: 'Trend and cycle from a filter, as macroeconomists take the business cycle out of a series. Hodrick-Prescott (hpfilter): the trend τ minimises Σ(y − τ)² + λ Σ(Δ²τ)², with λ from Ravn and Uhlig\'s rule 1600 (s/4)⁴ for s observations a year (6.25 yearly, 1600 quarterly, 129600 monthly). Baxter-King (bkfilter): a symmetric moving average that keeps the cycles of a band of periods and loses K values at each end. Christiano-Fitzgerald (cffilter): an asymmetric band pass that uses the whole series at every time, so none is lost.',
      sections: [{ heading: 'Options', text: 'The band is given in periods (by default 1.5 to 8 years: 6 to 32 quarters). Save Columns writes the trend and the cycle to the table. Missing values are filled by interpolation for the filter, and the cycle is left missing there.' }],
      more: MORE,
    },
    'p:timeseries:subseries': { kicker: 'Time Series', title: 'Seasonal Subseries Plot', lead: 'statsmodels\' month_plot, quarter_plot and seasonal_plot: the values of each season (every January, every February …; every quarter; every weekday; or every k-th observation of the period) drawn side by side in time order, each with a line at its mean. Differences between the means show the seasonal pattern, and the slope within a season shows it changing over the years. Points are linked to the rows; Season Means gives the numbers.', more: MORE },
    'p:timeseries:theta': {
      kicker: 'Time Series', title: 'Theta Model',
      lead: 'The theta method of Assimakopoulos and Nikolopoulos (2000), which did well in the M3 forecasting competition, with statsmodels\' ThetaModel. The series is tested for seasonality at the seasonal lag and deseasonalized (seasonal_decompose); simple exponential smoothing gives α and a linear trend gives the slope b0; the forecast is ((θ − 1)/θ) b0 [h − 1 + 1/α − (1 − α)^T/α] plus the smoothing forecast, reseasonalized. θ = 2 is the original method, simple exponential smoothing with drift b0/2 (Hyndman and Billah 2003).',
      sections: [
        { heading: 'Prediction intervals', text: 'The method is an IMA(1, 1) with drift, whose h-step variance is σ²(1 + (h − 1)α²): the report uses it, with statsmodels\' σ². statsmodels 0.14.6\'s prediction_intervals use σ²(1 + (h − 1)(1 + (α − 1)²)), which is wider; the model\'s red triangle shows those instead.' },
        { heading: 'Fit statistics', text: 'The method has no likelihood of its own: Model Comparison gets the statistics of its one-step-ahead forecasts from each origin, with the parameters of the whole fit.' },
      ],
      more: MORE,
    },
    'p:timeseries:holdback': {
      kicker: 'Time Series', title: 'Forecast on Holdback',
      lead: 'The last Forecast Periods values are held back: every model is fitted on the values before them and forecasts them, and the forecasts are compared with what happened. JMP\'s launch option, also in the red triangle. The statistics of these forecast errors compare models of every class, which their AICs do not.',
      sections: [
        { heading: 'Model Comparison', choices: [['RMSE', 'the root mean squared forecast error, √(Σe²/N): the table is sorted by it, as JMP sorts it'], ['MSE', 'the mean squared error, RMSE²'],
          ['MAPE', 'the mean absolute percentage error, 100 Σ|e/y|/N (missing when a held-back value is 0)'], ['MAE', 'the mean absolute error'], ['Mean Error', 'the mean of the errors actual − forecast: above 0, forecasts too low on the whole'],
          ['MASE', 'the MAE over the in-sample MAE of the naive forecast of the training values (the seasonal naive, at the seasonal period, when one is known): below 1, better than that benchmark did one step ahead (Hyndman and Koehler 2006)'],
          ['N', 'the held-back values present (an excluded or missing one is left out)']] },
        { heading: 'In the report', choices: [['The graphs', 'the held-back values are shaded; the forecasts start from the last training value'],
          ['Holdback Statistics', 'under each model\'s Forecast: the same statistics, with MASE\'s scale'], ['Save Columns', 'the training rows\' one-step-ahead predictions and residuals, the held-back rows\' forecasts and forecast errors, and a Set column (Training, Holdback, Forecast)'],
          ['Refit on All Rows', 'in the red triangle: every model fitted again on all the values; its forecasts after the end in its report, in Model Comparison and in Save Columns']] },
        { heading: 'Why', text: 'A model chosen for its fit to the data it was fitted to can forecast worse than a simpler one: the held-back values are new to every model, as the future is. Once a model is chosen, Refit on All Rows fits it to the latest values for the forecasts that matter.' },
      ],
      more: MORE,
    },
    'p:timeseries:benchmarks': {
      kicker: 'Time Series', title: 'Benchmark Models',
      lead: 'The simplest forecasts, which a model should beat to be worth its trouble (Hyndman and Athanasopoulos, Forecasting: Principles and Practice): Naive, every forecast the last value; Seasonal Naive, the value of the same season one period before; Drift, the last value plus h times the average change (y_T − y_1)/(T − 1). Compare them with the models under Forecast on Holdback.',
      sections: [{ heading: 'Their prediction intervals', text: 'σ√h (Naive, a random walk), σ√(k + 1) with k the whole periods before the horizon (Seasonal Naive), and σ√(h(1 + h/(T − 1))) (Drift, the uncertainty of the drift included), σ² the mean squared one-step error (over n − 1 for Drift). Their one-step-ahead predictions are the value before, the value a period before, and the value before plus the drift.' },
        { heading: 'Save Prediction Formula', text: 'In the model\'s red triangle: a live column of the one-step-ahead prediction, `Lag(:y, 1)`, `Lag(:y, s)` or `Lag(:y, 1) + b`, worked out again when values change or rows are added. Lag takes the rows before in the table, so the rows must be the series\' time points one after another (sorted by the Time ID, every time point with its row), and not By groups of one table.' }],
      more: MORE,
    },
    'p:timeseries:sma': {
      kicker: 'Time Series', title: 'Simple Moving Average',
      lead: 'JMP\'s Simple Moving Average: the mean of w consecutive values. No Centering puts the window at the value and the w − 1 before it; Centered around the value (an even width one value more before than after); Centered and Double Smoothed, for an even width, the mean of the two nearly centered windows, the 2 × w average of classical decomposition. As a forecast the average trails, whatever the centering: every forecast is the mean of the last w values.',
      sections: [
        { heading: 'The report', text: 'The smoothed series over the data (Smoothed Series in its red triangle), the forecasts, the one-step-ahead predictions (the mean of the w values before each) and their residuals, which give MAPE and MAE in Model Comparison. The interval is ±z times the one-step errors\' standard deviation at every horizon, right when the level stays where it is. Save Moving Average writes the smoothed series to the table.' },
        { heading: 'Save Prediction Formula', text: 'The one-step-ahead prediction as a live column: the mean of `Lag(:y, 1)` to `Lag(:y, w)`, missing where one of them is. The rows must be the series\' time points one after another, as for the benchmarks.' },
        { heading: 'Differences from JMP', text: 'JMP leaves the moving average out of Forecast on Holdback; here it takes part, with the mean of the last w training values as its forecast.' },
      ],
      more: MORE,
    },
    'p:timeseries:average': {
      kicker: 'Time Series', title: 'Averaged Forecast',
      lead: 'A model of models: its forecasts are the mean of the chosen models\' forecasts, its one-step-ahead predictions the mean of theirs (where every one has one), and its limits the mean of their limits at its level. Combined forecasts are often better than any single model\'s, as the errors of different methods partly cancel.',
      sections: [{ heading: 'The limits', text: 'The members\' forecast errors are correlated, so the standard error of the mean forecast is at most the mean of their standard errors, exactly that when the errors move together: the interval errs on the wide side. An average has no likelihood: AIC and SBC are left out; compare it on MAPE and MAE, or with Forecast on Holdback. A member removed from the report leaves the average without it: Fit New… chooses again.' }],
      more: MORE,
    },
    'p:timeseries:cv': {
      kicker: 'Time Series', title: 'Rolling-Origin Cross-Validation',
      lead: 'Evaluation on a rolling forecasting origin (Tashman 2000; Hyndman and Athanasopoulos): every model is fitted on the series up to each origin, a window that grows by the step, and forecasts the next values; the errors at every origin give its RMSE, MAE and MAPE, and their means over the origins rank the models on many forecasts, not the one a single holdback gives.',
      sections: [
        { heading: 'Options', choices: [['Number of origins', '5 by default; the last origin ends one horizon before the end of the series'], ['Horizon', 'the values forecast from each origin: the Forecast Periods, at most 12, at first'],
          ['Step between origins', 'empty: the horizon, forecast windows that follow one another; 1: every origin']] },
        { heading: 'In the report', choices: [['Means over the Origins', 'each model\'s RMSE, MAE and MAPE averaged over its origins, best RMSE first'], ['RMSE by origin', 'a line per model, in its colour: whether one model is better at every origin or only on the whole'],
          ['Per Origin', 'every model at every origin: the values it was fitted to and forecast, and its RMSE, MAE and MAPE']] },
      ],
      more: MORE,
    },
    'p:timeseries:runs': {
      kicker: 'Time Series', title: 'Runs Test',
      lead: 'The Wald-Wolfowitz runs test of randomness: the values in time order, each at or above a cutoff (the mean, the median or zero) or below it; a run is a stretch on one side. Too few runs mean highs and lows come in stretches (a trend or positive autocorrelation), too many an alternation. The number of runs R is compared with E = 2n₁n₂/N + 1, its standard deviation √(2n₁n₂(2n₁n₂ − N)/(N²(N − 1))), by a normal z.',
      sections: [{ heading: 'Where it is', text: 'Runs Test in the series\' red triangle, about the mean, the median or zero; and in every model\'s red triangle under Residual Statistics, the residuals about zero, a check of the one-step errors besides Ljung-Box. Below N = 50 |R − E| is less 1/2, the continuity correction of the SAS manual that statsmodels\' runstest_1samp follows (statsmodels 0.14.6 moves a distance below 1/2 away from 0 instead; the report does not).' }],
      more: MORE,
    },
    'p:timeseries:zivot': { kicker: 'Time Series', title: 'Zivot-Andrews Test', lead: 'A unit root test that allows one structural break at an unknown date (Zivot and Andrews 1992, statsmodels\' zivot_andrews): H0 a unit root, H1 a stationary series with a break in the intercept, the trend or both. Where the ADF test mistakes a break for a unit root, this one can reject. The break date is where the test statistic is smallest: the last observation before the shift. P-values and critical values are interpolated in statsmodels\' simulated tables; the options set the trimming at the ends and the lag selection.', more: MORE },
    'p:timeseries:ardl': {
      kicker: 'Time Series', title: 'ARDL and the Bounds Test',
      lead: 'An autoregressive distributed lag model ARDL(p, q₁, …, q_k): the series on p of its own lags and on the inputs at lags 0 to q, by least squares (statsmodels\' ARDL), with the orders chosen by AIC or BIC among all orders up to the largest (ardl_select_order), or given.',
      sections: [
        { heading: 'The long run', text: 'If the model is stable it settles to a level relation y = θ₀ + Σ θx, with θ = Σβ/(1 − Σφ); the Long-Run Coefficients have delta-method standard errors (statsmodels\' UECM ci_params). The error correction form writes the same model as changes on the lagged levels; the coefficient of the lagged series is the speed of adjustment.' },
        { heading: 'The bounds test', text: 'Pesaran, Shin and Smith (2001) test whether there is a level relationship at all, without knowing whether the inputs are stationary: the F test of the lagged levels in the error correction form is compared with two bounds, all inputs I(0) and all I(1). Above the I(1) bound: a level relationship (cointegration); below the I(0) bound: none; in between: inconclusive. The case says where the intercept and trend go (3: unrestricted intercept, the usual one; 4: a trend in the level relation). The critical values and p-values are statsmodels\' simulated tables, read for the model\'s number of inputs.' },
        { heading: 'Forecasts', text: 'They need the inputs\' future values: from the rows after the series in the table (Y missing, the inputs present), as the Transfer Function takes them; beyond those the last value is held.' },
      ],
      more: MORE,
    },
  };

  /* ---- the example: simulated here, never real data ---------------------------------------------------------------------------------------------------- */
  SM.io.addExample('cycles', {
    label: 'Business cycle (184 quarters): regimes, a break, a cointegrated pair',
    about: 'Simulated quarters from 1980: growth switches between an expansion (mean 0.8, staying with probability 0.95) and a recession (mean −0.6, staying with probability 0.75) by a Markov chain, with AR(1) noise; output adds the growth up, a trend with a business cycle; unemployment is stationary around a level that jumps from 5 to 8 after 2005 Q1; cost is a random walk with drift and price follows it: price = 5 + 0.6 price(t−1) + 0.5 cost − 0.2 cost(t−1) + noise, a level relation price = 12.5 + 0.75 cost. The last 8 quarters have cost but no price, for ARDL forecasts. For Time Series: Regime Switching, Filters, the Zivot-Andrews test, Structural Model and ARDL.',
    make() {
      const r = SM.util.rng('cycles');
      const n = 184, future = 8, brk = 100;
      const mu = [0.8, -0.6], stay = [0.95, 0.75];
      const quarter = [], growth = [], output = [], unemp = [], cost = [], price = [];
      let s = 0, g0 = mu[0], out = 100, u = 5, c = 50, p = 12.5 + 0.75 * 50;
      for (let t = 0; t < n; t++) {
        if (t > 0 && r.u() > stay[s]) s = 1 - s;
        const g = mu[s] + 0.3 * (g0 - mu[s]) + r.normal(0, 0.6);
        g0 = g;
        out += g;
        const m = t <= brk ? 5 : 8;
        u = t === 0 ? m : m + 0.6 * (u - (t - 1 <= brk ? 5 : 8)) + r.normal(0, 0.35);
        const c1 = c;
        c = t === 0 ? c : c + 0.2 + r.normal(0, 0.8);
        p = t === 0 ? p : 5 + 0.6 * p + 0.5 * c - 0.2 * c1 + r.normal(0, 0.5);
        quarter.push(Date.UTC(1980, 3 * t, 1));
        growth.push(+g.toFixed(3)); output.push(+out.toFixed(3)); unemp.push(+u.toFixed(3)); cost.push(+c.toFixed(3));
        price.push(t < n - future ? +p.toFixed(3) : NaN);
      }
      return new SM.Table({ name: 'Business cycle', source: 'simulated', columns: [
        { name: 'quarter', dataType: 'numeric', format: { kind: 'date' }, values: quarter },
        { name: 'growth', dataType: 'numeric', values: growth },
        { name: 'output', dataType: 'numeric', values: output },
        { name: 'unemployment', dataType: 'numeric', values: unemp },
        { name: 'cost', dataType: 'numeric', values: cost },
        { name: 'price', dataType: 'numeric', values: price },
      ] });
    },
  });

  /* ---- the platform ------------------------------------------------------------------------------------------------------------------------------------ */
  SM.platforms.register({
    id: 'timeseries', label: 'Time Series', menu: 'Analyze/Specialized Modeling', order: 20, info: 'p:timeseries', topics,
    about: 'One series in time order: its graph with the ADF tests, autocorrelations with Ljung-Box, partial autocorrelations, variogram, KPSS and the Zivot-Andrews test with its break date; differencing, linear trend and cycle removal, seasonal decomposition and STL, the Hodrick-Prescott, Baxter-King and Christiano-Fitzgerald filters; the spectral density with the white noise tests; lag plots, seasonal subseries plots, runs tests and cross correlations; ARIMA, seasonal ARIMA and ARIMA model groups, transfer functions (ARIMAX), the smoothing models with JMP\'s Zero To One and Custom constraints and a Box-Cox option, the Simple Moving Average, and state space smoothing (all 30 ETS models, the multiplicative trends too); Forecast on Holdback, with the holdback RMSE, MAPE, MAE, mean error and MASE in Model Comparison and Refit on All Rows; and, beyond JMP, Naive, Seasonal Naive and Drift benchmarks, averaged forecasts, rolling-origin cross-validation, structural (unobserved components) models with their smoothed components, Markov regime-switching models with regime probabilities, the Theta model, and ARDL models with the long-run coefficients and the Pesaran-Shin-Smith bounds test; each with forecasts that continue the dates, compared in one table.',
    uses: ['statsmodels.tsa.stattools.acf, pacf, adfuller, kpss, ccf, levinson_durbin, zivot_andrews', 'statsmodels.stats.diagnostic.acorr_ljungbox', 'statsmodels.tsa.arima.model.ARIMA',
      'statsmodels.tsa.holtwinters.ExponentialSmoothing', 'statsmodels.tsa.exponential_smoothing.ets.ETSModel', 'statsmodels.tsa.seasonal.seasonal_decompose, STL',
      'statsmodels.tsa.statespace.structural.UnobservedComponents', 'statsmodels.tsa.regime_switching.markov_regression.MarkovRegression, markov_autoregression.MarkovAutoregression',
      'statsmodels.tsa.filters.hp_filter.hpfilter, bk_filter.bkfilter, cf_filter.cffilter', 'statsmodels.graphics.tsaplots.month_plot, quarter_plot, seasonal_plot (their data)',
      'statsmodels.tsa.forecasting.theta.ThetaModel', 'statsmodels.tsa.ardl.ARDL, UECM, ardl_select_order, pss_critical_values',
      'statsmodels.tsa.statespace.tools.diff', 'statsmodels.regression.linear_model.OLS', 'pandas.infer_freq', 'pandas.Series.rolling (the moving average)', 'scipy.special.boxcox, inv_boxcox',
      'scipy.optimize.minimize_scalar', 'numpy.fft'],
    launch: {
      lead: 'Choose the series. A date column as X, Time ID gives a date axis, the seasonal period and the dates of the forecasts; Input List columns are the inputs of transfer functions, structural and ARDL models.',
      roles: [
        { key: 'y', label: 'Y, Time Series', min: 1, types: ['continuous'], hint: 'required: one or more continuous',
          help: 'The series to analyse, in time order (the Time ID\'s, else the rows\'); each column gets its own outline, red triangle and models. It runs from its first value to its last; excluded rows inside count as missing values, as in JMP, so that the spacing is kept.' },
        { key: 'inputs', label: 'Input List', numeric: true, hint: 'optional numeric: inputs of transfer functions, structural and ARDL models',
          help: 'Input series, numeric (a price, a 0/1 promotion flag): Cross Correlation and the Input Time Series Panel show them beside each Y, and Transfer Function, Structural Model and ARDL take them as regressors. Forecasts use their values in the rows after the series (Y missing there), and hold the last one beyond them.' },
        { key: 'time', label: 'X, Time ID', max: 1, numeric: true, hint: 'optional: a date or a time step', info: 'p:timeseries:timeid',
          help: 'Orders the rows and labels the time axis. A date column gives the calendar frequency, the seasonal period (12 for monthly data, 4 for quarterly …) and the dates of the forecasts; dates missing from the calendar count as missing values. A numeric Time ID continues its step; without one the row number is the time.' },
        { key: 'by', label: 'By', hint: 'optional',
          help: 'A separate report of the rows of each level (each combination of levels, with several By columns). Rows with a missing By value are left out.' },
      ],
      options: [
        { key: 'forecast', label: 'Forecast Periods', type: 'number', value: 25,
          help: 'How many periods after the end of the series each model forecasts, with its prediction interval: 0 to 1000, 25 by default (0: none); with Forecast on Holdback, how many values at the end are held back and forecast instead. Number of Forecast Periods…, in the red triangle, changes it for every model.' },
        { key: 'holdback', label: 'Forecast on Holdback', type: 'check', value: false,
          help: 'Holds back the last Forecast Periods values: every model is fitted on the values before them and forecasts them, and Model Comparison compares the forecasts with what happened (RMSE, MAPE, MAE, MASE), which compares models of every kind. Off by default, as in JMP; the red triangle turns it on and off, and Refit on All Rows adds the forecasts after the end.' },
        { key: 'nlags', label: 'Autocorrelation Lags', type: 'number', value: 25,
          help: 'How many lags the autocorrelations, partial autocorrelations, variogram, AR coefficients and Ljung-Box tests go to, for the series, its differences and the models\' residuals (at most n − 1), and the lags either way of Cross Correlation. 25 by default, at least 2; about n/4 is a common choice.' },
        { key: 'period', label: 'Seasonal Period (empty: from the Time ID)', type: 'number', value: '',
          help: 'The observations per seasonal period: the one the model and decomposition dialogs start with, the Seasonal Subseries Plot uses and ARDL\'s seasonal dummies take. Empty (the default): from the Time ID\'s calendar frequency (12 for monthly data, 4 for quarterly), else 12. At least 2.' },
      ],
      validate: (spec) => {
        const o = spec.options || {};
        if (o.nlags != null && !(o.nlags >= 2)) return 'Autocorrelation Lags: at least 2';
        if (o.forecast != null && !(o.forecast >= 0 && o.forecast <= 1000)) return 'Forecast Periods: from 0 to 1000';
        if (o.period != null && o.period !== '' && !(o.period >= 2)) return 'Seasonal Period: at least 2, or empty';
        return null;
      },
    },
    title: (spec, table) => {
      const ys = (spec.roles && spec.roles.y) || [];
      const c = ys.length === 1 && table ? table.col(ys[0]) : null;
      return c ? `Time Series ${c.name}` : 'Time Series';
    },
    triangle(ctx) {
      const ys = ctx.roles('y');
      if (ys.length === 1) return [...seriesMenu(ctx, ys[0]), { separator: true }, ...globalItems(ctx)];
      return globalItems(ctx);
    },
    async render(ctx) {
      const ys = ctx.roles('y');
      if (ys.length === 1) { await renderSeries(ctx, ys[0], ctx.top); return; }
      for (const c of ys) {
        const ob = ctx.outline(`Time Series ${c.name}`, { menu: () => seriesMenu(ctx, c), key: `ts:${c.name}` });
        await renderSeries(ctx, c, ob);
      }
    },
  });

  // For the tests.
  SM.timeseries = Object.freeze({ groupRows, barSvg, parseRange, effective, specName, perYear, filterDefaults, parseOrders, fitKey, regimeColor, callOf, modelRows, averageable,
    // for Time Series Forecast (smui-p-tsforecast.js): a series' graphs drawn as here
    draw: Object.freeze({ withX, seriesTrace, forecastTraces, forecastPlot, fitShapes, xAxis, plotWidth, graphCode, withCode, recipe, tLabel, isDate, ptext, colorOf, fx, PARAM_COLS }) });
}(typeof self !== 'undefined' ? self : this));
