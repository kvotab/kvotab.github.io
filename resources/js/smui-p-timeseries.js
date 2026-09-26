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

  function rgba(hex, a) {
    const h = hex.replace('#', '');
    return `rgba(${parseInt(h.slice(0, 2), 16)}, ${parseInt(h.slice(2, 4), 16)}, ${parseInt(h.slice(4, 6), 16)}, ${a})`;
  }

  /* ---- the launch options -------------------------------------------------- */
  const nlags = (ctx) => Math.max(2, int(ctx.opt('nlags', 25), 25));
  const horizon = (ctx) => Math.max(0, Math.min(1000, int(ctx.opt('forecast', 25), 25)));
  const maxiter = (ctx) => Math.max(5, int(ctx.opt('maxiter', 200), 200));
  function periodOf(ctx, S) {
    const p = int(ctx.opt('period', null), 0);
    if (p >= 2) return p;
    return S && S.period_auto >= 2 ? S.period_auto : 12;
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
    return { title: { text: timeTitle(S) }, ...(isDate(S) ? { type: 'date' } : {}), ...extra };
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

  /* The diagnostics of a series (the original, a difference, residuals). */
  function diagnosticsBlock(ctx, D, { acf = true, pacf = true, variogram = false, ar = false, residual = false } = {}) {
    if (!D || D.error) return D && D.error ? ctx.note(D.error) : null;
    const left = [], right = [];
    if (acf) left.push(acfTable(ctx, D, { residual }));
    if (pacf) right.push(pacfTable(ctx, D, { residual }));
    if (variogram) left.push(variogramTable(ctx, D));
    if (ar) right.push(arTable(ctx, D));
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
    return { type: S.t.length > 5000 ? 'scattergl' : 'scatter', mode, x: S.x, y: values, rows: S.rowsLinked, name, connectgaps: false, line: { color, width: 1.2 }, marker: { size: 5, color } };
  }

  function seriesPlot(ctx, S, values, name, { points = true, lines = true, meanLine = null, extra = [], height = 260, width = 560, title } = {}) {
    const shapes = [];
    if (meanLine != null && Number.isFinite(meanLine)) shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: meanLine, y1: meanLine, line: { color: '#b0413e', width: 1, dash: 'dot' } });
    const traces = [];
    if (points || lines) traces.push(seriesTrace(S, values, name, { points, lines }));
    traces.push(...extra);
    return ctx.plot(traces, { xaxis: xAxis(S), yaxis: { title: { text: name } }, shapes }, { width: plotWidth(ctx, width), height, title: title || `${name} time series` });
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
      const plot = seriesPlot(ctx, S, S.values, col.name, { points: o('points', true), lines: o('lines', true), meanLine: o('meanLine', false) ? S.diag.mean : null });
      box.add(ctx.row(plot, el('div', null, ctx.kv(summaryPairs(S.diag, S.stationarity)), S.freq_label ? ctx.note(`${S.freq_label[0].toUpperCase()}${S.freq_label.slice(1)} data; seasonal period ${period}.`) : null)));
    } else box.add(ctx.kv(summaryPairs(S.diag, S.stationarity)));

    const flags = { acf: o('acf', true), pacf: o('pacf', true), variogram: o('variogram', false), ar: o('arcoef', false) };
    if (flags.acf || flags.pacf || flags.variogram || flags.ar) {
      const ob = ctx.outline('Time Series Basic Diagnostics', { parent: box, key: `${sc}:diag`, info: 'p:timeseries:diagnostics' });
      ob.add(diagnosticsBlock(ctx, S.diag, flags));
      ob.add(ctx.code(S.code));
    }
    if (o('stationarity', true)) {
      const ob = ctx.outline('Stationarity Tests', { parent: box, key: `${sc}:stat`, info: 'p:timeseries:stationarity', menu: () => [{ label: 'Remove', action: () => ctx.set('stationarity', false, sc) }] });
      ob.add(stationarityTable(ctx, S.stationarity), ctx.note('ADF: augmented Dickey-Fuller tests of a unit root, with the lags chosen by AIC and MacKinnon\'s p-values and critical values; a small p-value speaks for stationarity. KPSS tests the opposite null, stationarity; statsmodels interpolates its p-value between 0.01 and 0.1 and gives a bound outside.'));
    }
    // Each part on its own: an error in one shows there, the rest still draws.
    const part = async (fn) => { try { await fn(); } catch (e) { console.error(e); box.add(ctx.error(e)); } };
    if (o('spectral', false)) await part(() => spectralReport(ctx, col, S, base, box));
    if (o('lagPlot', null) != null) await part(() => lagPlot(ctx, col, S, box));
    if (inputs.length && o('ccf', false)) await part(() => ccfReport(ctx, col, S, base, inputs, box));
    if (inputs.length && o('inputPanel', true)) await part(() => inputPanel(ctx, col, inputs, base, box));
    for (const spec of o('diffs', [])) await part(() => differenceReport(ctx, col, S, base, spec, box));
    for (const spec of o('decomps', [])) await part(() => decompReport(ctx, col, S, base, spec, box));
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
    if (flag('graph', true)) ob.add(ctx.row(seriesPlot(ctx, S, r.values, name, { points: flag('points', true), lines: flag('lines', true), meanLine: flag('meanLine', false) ? r.diag.mean : null, title: `${name} time series` }), ctx.kv(summaryPairs(r.diag, r.stationarity))));
    else ob.add(ctx.kv(summaryPairs(r.diag, r.stationarity)));
    ob.add(diagnosticsBlock(ctx, r.diag, { acf: flag('acf', true), pacf: flag('pacf', true), variogram: flag('variogram', false) }));
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
      ob.add(seriesPlot(ctx, S, S.values, col.name, { extra: [{ type: 'scatter', mode: 'lines', x: S.x, y: fit, line: { color: '#b0413e', width: 1.6 }, name: label, hoverinfo: 'skip' }], title: `${col.name} ${label.toLowerCase()}`, height: 230 }));
      const sub = ctx.outline(`Time Series ${dname}`, { parent: ob, key: `${sc}:dec:${spec.id}:series` });
      sub.add(ctx.row(seriesPlot(ctx, S, r.values, dname, { title: `${dname} time series`, height: 230 }), ctx.kv(summaryPairs(r.diag, r.stationarity))));
      sub.add(diagnosticsBlock(ctx, r.diag, { acf: true, pacf: true }), ctx.code(r.code));
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
    ob.add(ctx.plot(traces, layout, { width: plotWidth(ctx, 620), height: 520, title: label }));
    ob.add(ctx.note(spec.kind === 'stl' ? 'STL: seasonal and trend by loess (statsmodels\' STL). The seasonally adjusted series is y − seasonal.' : `Moving averages (statsmodels' seasonal_decompose): the trend is a centred moving average over the period, so it is missing at the ends. The adjusted series is ${spec.model === 'multiplicative' ? 'y / seasonal' : 'y − seasonal'}. JMP's X11 needs the Census Bureau's program, which does not run in the browser.`));
    for (const n of r.notes || []) ob.add(ctx.note(n));
    ob.add(ctx.code(r.code));
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
    const byPeriod = ctx.plot([{ ...dn, x: r.period, y: r.density }], { xaxis: { title: { text: 'Period' }, type: 'log' }, yaxis: yl }, { width: w, height: 250, title: `${col.name} spectral density by period` });
    const byFreq = ctx.plot([{ ...pg, x: r.frequency, y: r.periodogram.map((v) => v / (4 * Math.PI)) }, { ...dn, x: r.frequency, y: r.density }],
      { xaxis: { title: { text: 'Frequency' } }, yaxis: yl, showlegend: true, legend: { orientation: 'h', y: -0.3 } }, { width: w, height: 270, title: `${col.name} spectral density by frequency` });
    ob.add(ctx.row(byPeriod, byFreq));
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
    const plot = ctx.plot([{ type: 'scatter', mode: 'markers', x, y, rows, name: `${col.name} at t and t − ${lag}` }],
      { xaxis: { title: { text: `${col.name}(t − ${lag})` } }, yaxis: { title: { text: `${col.name}(t)` } } }, { width: plotWidth(ctx, 360), height: 320, title: `${col.name} lag plot` });
    ob.add(ctx.row(plot, ctx.kv([['Lag', lag, 'int'], ['Pairs', n, 'int'], ['Correlation', r]])), ctx.note('Each point is an observation (y axis) against the one p periods before it; clicking selects the later row.'));
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
    ob.add(ctx.row(...tables), ctx.note(`Lag k is the correlation of ${col.name} at t + k with the input at t, so positive lags are the input leading. Ticks: ±2 standard errors, 1/√(n − |k|).`), ctx.code(r.code));
  }

  /* ---- Input Time Series Panel ------------------------------------------------------------------------- */
  async function inputPanel(ctx, col, inputs, base, box) {
    const sc = scopeOf(col);
    const ob = ctx.outline('Input Time Series Panel', { parent: box, key: `${sc}:inputs`, closed: true, menu: () => [{ label: 'Remove', action: () => ctx.set('inputPanel', false, sc) }] });
    for (const c of inputs) {
      const r = await ctx.call('timeseries.input', { y: c.name, time: base.time, rows: base.rows, nlags: base.nlags });
      const sub = ctx.outline(`Input Series ${c.name}`, { parent: ob, key: `${sc}:input:${c.name}` });
      if (r.error) { sub.add(ctx.warn(r.error)); continue; }
      r.rowsLinked = r.rows.map((x) => (x == null ? -1 : x));
      const R = withX({ ...r, time: base.time });
      sub.add(ctx.row(seriesPlot(ctx, R, r.values, c.name, { height: 220, width: 480 }), ctx.kv(summaryPairs(r.diag, r.stationarity))));
      sub.add(diagnosticsBlock(ctx, r.diag, { acf: true, pacf: false }));
    }
  }

  /* ---- models: the fits ---------------------------------------------------------------------------------- */
  function fitCall(ctx, base, spec, h) {
    if (spec.kind === 'arima') {
      return ctx.call('timeseries.arima', { ...base, p: spec.p, d: spec.d, q: spec.q, P: spec.P || 0, D: spec.D || 0, Q: spec.Q || 0, s: spec.s || 0,
        intercept: spec.intercept !== false, constrain: spec.constrain !== false, level: spec.level || 0.95, h, maxiter: maxiter(ctx), inputs: spec.inputs || null });
    }
    if (spec.kind === 'smooth') return ctx.call('timeseries.smooth', { ...base, method: spec.method, s: spec.s || 0, level: spec.level || 0.95, h, multiplicative: !!spec.multiplicative });
    if (spec.kind === 'ets') return ctx.call('timeseries.ets', { ...base, error: spec.error, trend: spec.trend, seasonal: spec.seasonal, s: spec.s || 0, level: spec.level || 0.95, h, maxiter: Math.max(200, maxiter(ctx)) });
    return Promise.resolve({ error: `unknown model ${spec.kind}` });
  }

  const fitKey = (s) => JSON.stringify([s.kind, s.p, s.d, s.q, s.P, s.D, s.Q, s.s, s.intercept, s.constrain, s.level, s.inputs, s.method, s.multiplicative, s.error, s.trend, s.seasonal]);

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
  function effective(list, results) {
    const best = new Map();
    list.forEach((s, i) => {
      if (!s.group) return;
      const r = results[i];
      const v = r && !r.error ? (s.kind === 'ets' ? r.stats.aicc : r.stats.aic) : null;
      if (v == null) return;
      const cur = best.get(s.group);
      if (!cur || v < cur.v) best.set(s.group, { v, id: s.id });
    });
    return list.map((s) => {
      const auto = s.group ? (best.get(s.group) || {}).id === s.id : true;
      return { report: s.report == null ? auto : !!s.report, graph: s.graph == null ? auto : !!s.graph };
    });
  }

  async function modelsReport(ctx, col, S, base, box, { period, h }) {
    const sc = scopeOf(col);
    const list = ctx.opt('models', [], sc);
    if (!list.length) return;
    const results = await Promise.all(list.map((spec) => fitCall(ctx, base, spec, h).catch((e) => ({ error: e.message || String(e) }))));
    const eff = effective(list, results);
    comparison(ctx, col, S, list, results, eff, box);
    const groups = [...new Set(list.filter((s) => s.kind === 'ets' && s.group).map((s) => s.group))];
    for (const g of groups) etsSelection(ctx, col, list, results, eff, g, box);
    list.forEach((spec, i) => { if (eff[i].report) modelReport(ctx, col, S, spec, results[i], box); });
  }

  /* ---- Model Comparison -------------------------------------------------------------------------------------- */
  const CMP_COLS = [['df', 'DF', 'int'], ['variance', 'Variance'], ['aic', 'AIC'], ['sbc', 'SBC'], ['aicc', 'AICc'], ['rsquare', 'RSquare'], ['m2ll', '−2LogLH'], ['weight', 'Weights'], ['mape', 'MAPE'], ['mae', 'MAE']];

  function comparison(ctx, col, S, list, results, eff, box) {
    const sc = scopeOf(col);
    const setAll = (patch) => updateModels(ctx, col, (m) => ({ ...m, ...patch }));
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
      { label: 'Combine and Save Forecasts from Models', action: () => combineForecasts(ctx, col, S, list, results) },
    ] });
    const aics = results.map((r) => (r && !r.error ? r.stats.aic : null)).filter(Number.isFinite);
    const best = aics.length ? Math.min(...aics) : null;
    const tot = aics.reduce((s, a) => s + Math.exp(-0.5 * (a - best)), 0);
    const rows = list.map((spec, i) => {
      const r = results[i];
      const st = r && !r.error ? r.stats : {};
      return { spec, i, name: r && r.name ? r.name : specName(spec), error: r && r.error, ...st, weight: Number.isFinite(st.aic) && tot > 0 ? Math.exp(-0.5 * (st.aic - best)) / tot : null };
    });
    let sortKey = 'aic', dir = 1;
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
        for (const [key, , f] of CMP_COLS) tr.append(el('td', { text: row.error && key === 'df' ? '' : SM.report.cellText(row[key], f || 'num') }));
        if (row.error) tr.append(el('td', { class: 'sm-l sm-ts-err', text: row.error }));
        return tr;
      }));
    };
    for (const [key, label] of CMP_COLS) {
      const th = el('th', { text: label, scope: 'col', class: 'sm-ts-sort' });
      th.addEventListener('click', () => { if (sortKey === key) dir = -dir; else { sortKey = key; dir = 1; } head.querySelectorAll('th').forEach((x) => x.removeAttribute('aria-sort')); th.setAttribute('aria-sort', dir > 0 ? 'ascending' : 'descending'); fill(); });
      head.append(th);
    }
    fill();
    const tbl = el('table', { class: 'sm-rt sm-ts-cmp' }, el('thead', null, head), tbody);
    tbl._rt = { columns: [{ key: 'name', label: 'Model', fmt: 'text' }, ...CMP_COLS.map(([key, label, f]) => ({ key, label, fmt: f || 'num' }))], rows };
    tbl.addEventListener('contextmenu', (ev) => {
      ev.preventDefault();
      SM.ui.menu([
        { label: 'Copy Table', action: () => SM.report.copyText(SM.report.rtText(tbl._rt)) },
        { label: 'Make into Data Table', action: () => SM.app.addTable(SM.report.tableFromRT(tbl._rt, `${col.name} model comparison`)) },
      ], { x: ev.clientX, y: ev.clientY });
    });
    ob.add(el('div', { class: 'sm-ts-scroll' }, tbl));
    const kinds = new Set(list.map((s) => s.kind));
    if (kinds.has('ets') && kinds.size > 1) ob.add(ctx.warn('Caution: the state space smoothing models\' likelihood is not that of the ARIMA and smoothing models, so their AIC and SBC do not compare; compare on MAPE and MAE, or within each class (as JMP cautions).'));
    else if (kinds.has('smooth') && kinds.has('arima')) ob.add(ctx.note('The smoothing models\' likelihood is that of their one-step errors given the estimated starting states; the ARIMA models\' is the exact likelihood. Their AICs are close relatives, not the same quantity.'));
    ob.add(ctx.note('Sorted by AIC; click a heading to sort. Weights are AIC weights, exp(−ΔAIC/2) normalised. Report shows a model\'s report, Graph puts it on the plots below. AIC, SBC and AICc count the fitted parameters as JMP does (not the variance).'));
    // the model plots: forecasts, and the residual autocorrelations
    const shown = list.map((s, i) => ({ s, r: results[i], on: eff[i].graph })).filter((x) => x.on && x.r && !x.r.error);
    if (!shown.length) return;
    const traces = [{ ...seriesTrace(S, S.values, col.name, { points: true, lines: false }), showlegend: false }];
    for (const { s, r } of shown) traces.push(...forecastTraces(S, r, colorOf(s.id), { pi: true, name: r.name, legend: true, oneStepPI: false }));
    const end = S.x[S.x.length - 1];
    const plot = ctx.plot(traces, { xaxis: xAxis(S), yaxis: { title: { text: col.name } }, showlegend: true, legend: { orientation: 'h', y: -0.22 },
      shapes: [{ type: 'line', x0: end, x1: end, yref: 'paper', y0: 0, y1: 1, line: { color: SM.util.themeColors().muted, width: 1, dash: 'dot' } }] },
    { width: plotWidth(ctx, 640), height: 320 + 18 * Math.ceil(shown.length / 2), title: `${col.name} model comparison forecasts` });
    const acfOver = (key, label) => {
      const tr = [];
      let n = 0;
      for (const { s, r } of shown) {
        const D = r.resid_diag;
        if (!D || D.error) continue;
        n = Math.max(n, D.n);
        tr.push({ type: 'scatter', mode: 'lines+markers', x: D[key].lag.slice(1), y: D[key].r.slice(1), name: r.name, line: { color: colorOf(s.id), width: 1.2 }, marker: { size: 4, color: colorOf(s.id) }, hovertemplate: `${r.name}: lag %{x}, %{y:.4f}<extra></extra>` });
      }
      if (!tr.length) return null;
      const b = 2 / Math.sqrt(n);
      return ctx.plot(tr, { xaxis: { title: { text: 'Lag' } }, yaxis: { title: { text: label }, range: [-1, 1] },
        shapes: [b, -b].map((v) => ({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: v, y1: v, line: { color: '#2f6ec7', width: 1, dash: 'dash' } })) },
      { width: plotWidth(ctx, 320), height: 220, title: `${col.name} residual ${label.toLowerCase()}` });
    };
    ob.add(plot, ctx.row(acfOver('acf', 'Autocorrelation'), acfOver('pacf', 'Partial Autocorrelation')));
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
      return s.method === 'seasonal' || s.method === 'winters' ? `${label}(${s.s})` : label;
    }
    if (s.kind === 'ets') return `ETS(${s.error === 'mul' ? 'M' : 'A'},${s.trend || 'N'},${s.seasonal || 'N'})`;
    return s.kind;
  }

  /* One model's forecast traces: the one-step-ahead predictions, the
     forecasts, and the prediction interval, in-sample lines that go on into
     a band over the forecast periods. */
  function forecastTraces(S, r, color, { pi = true, name, legend = false, oneStepPI = true } = {}) {
    const n = S.t.length;
    const fc = r.forecast || { t: [] };
    const last = n - 1;
    const ft = fx(S, fc.t);
    const tr = [{ type: 'scatter', mode: 'lines', x: S.x, y: r.fitted, name: legend ? name : 'Predicted', legendgroup: name, showlegend: legend, line: { color, width: 1.3 }, hovertemplate: `${name}: %{y:.5g}<extra></extra>` }];
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
      tr.push({ type: 'scatter', mode: 'lines', x: S.x, y: r.fit_hi, line: { color: rgba(color, 0.45), width: 0.8, dash: 'dot' }, legendgroup: name, showlegend: false, hoverinfo: 'skip', name: `${name} upper (one step)` },
        { type: 'scatter', mode: 'lines', x: S.x, y: r.fit_lo, line: { color: rgba(color, 0.45), width: 0.8, dash: 'dot' }, legendgroup: name, showlegend: false, hoverinfo: 'skip', name: `${name} lower (one step)` });
    }
    return tr;
  }

  /* ---- State Space Smoothing model selection ------------------------------------------------------------------------ */
  function etsSelection(ctx, col, list, results, eff, group, box) {
    const sc = scopeOf(col);
    const rows = [];
    list.forEach((s, i) => {
      if (s.group !== group || s.kind !== 'ets') return;
      const r = results[i];
      rows.push({ id: s.id, i, name: r && r.name ? r.name.replace('State Space Smoothing ', '') : specName(s), error: r && r.error, nparm: r && r.nparm, m2ll: r && r.stats ? r.stats.m2ll : null,
        aic: r && r.stats ? r.stats.aic : null, aicc: r && r.stats ? r.stats.aicc : null, bic: r && r.stats ? r.stats.sbc : null, mape: r && r.stats ? r.stats.mape : null });
    });
    const ok = rows.filter((r) => Number.isFinite(r.aicc));
    const best = ok.length ? Math.min(...ok.map((r) => r.aicc)) : null;
    const tot = ok.reduce((s, r) => s + Math.exp(-0.5 * (r.aicc - best)), 0);
    for (const r of rows) { r.delta = Number.isFinite(r.aicc) ? r.aicc - best : null; r.weight = Number.isFinite(r.aicc) && tot ? Math.exp(-0.5 * r.delta) / tot : null; r.mark = r.delta === 0 ? '★ best' : r.error ? r.error : ''; }
    rows.sort((a, b) => (a.aicc ?? Infinity) - (b.aicc ?? Infinity));
    const ob = ctx.outline(`State Space Smoothing Model Selection ${group}`, { parent: box, key: `${sc}:etsgroup:${group}`, info: 'p:timeseries:ets', menu: () => [
      { label: 'Remove These Models', action: () => ctx.set('models', ctx.opt('models', [], sc).filter((m) => m.group !== group), sc) },
    ] });
    ob.add(ctx.rt({ columns: [{ key: 'name', label: 'Model', fmt: 'text' }, { key: 'nparm', label: 'Nparm', fmt: 'int' }, { key: 'm2ll', label: '−2LogLikelihood' }, { key: 'aic', label: 'AIC' },
      { key: 'aicc', label: 'AICc' }, { key: 'delta', label: 'ΔAICc' }, { key: 'weight', label: 'AICc Weight' }, { key: 'bic', label: 'BIC' }, { key: 'mape', label: 'MAPE' }, { key: 'mark', label: '', fmt: 'text' }], rows },
    { sortable: false, name: 'State space smoothing models', onRow: (row) => updateModels(ctx, col, (m) => (m.id === row.id ? { ...m, report: true, graph: true } : null)) }),
    ctx.note('ETS(error, trend, seasonal) models of Hyndman et al. (2008) fitted by maximum likelihood (statsmodels\' ETSModel), best first by AICc. The best one shows its report; click a line to show another.'));
  }

  /* ---- a model's report ---------------------------------------------------------------------------------------------- */
  const PARAM_COLS = {
    arima: (seasonal) => [{ key: 'term', label: 'Term', fmt: 'text' }, ...(seasonal ? [{ key: 'factor', label: 'Factor', fmt: 'text' }] : []), { key: 'lag', label: 'Lag', fmt: 'int' },
      { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }],
    smooth: () => [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }],
    ets: () => [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'lower', label: 'Lower 95%' }, { key: 'upper', label: 'Upper 95%' }],
  };

  function modelMenu(ctx, col, S, spec, r) {
    const flag = (k, d = true) => (spec[k] == null ? d : !!spec[k]);
    const up = (patch) => updateModels(ctx, col, (m) => (m.id === spec.id ? { ...m, ...patch } : null));
    return [
      { label: 'Show Points', checked: flag('points'), action: () => up({ points: !flag('points') }) },
      { label: 'Show Prediction Interval', checked: flag('pi'), action: () => up({ pi: !flag('pi') }) },
      { label: 'Save Columns', disabled: !r || !!r.error, action: () => saveModelTable(ctx, col, S, r) },
      { label: 'Residual Statistics', submenu: () => [
        { label: 'Autocorrelation', checked: flag('racf'), action: () => up({ racf: !flag('racf') }) },
        { label: 'Partial Autocorrelation', checked: flag('rpacf'), action: () => up({ rpacf: !flag('rpacf') }) },
        { label: 'Variogram', checked: flag('rvario', false), action: () => up({ rvario: !flag('rvario', false) }) },
        { label: 'AR Coefficients', checked: flag('rar', false), action: () => up({ rar: !flag('rar', false) }) },
      ] },
      { separator: true },
      { label: 'Fit New…', action: () => fitNew(ctx, col, S, spec) },
      { label: 'Remove Fit', action: () => ctx.set('models', ctx.opt('models', [], scopeOf(col)).filter((m) => m.id !== spec.id), scopeOf(col)) },
    ];
  }

  function modelReport(ctx, col, S, spec, r, box) {
    const sc = scopeOf(col);
    const color = colorOf(spec.id);
    const name = r && r.name ? r.name : specName(spec);
    const info = spec.kind === 'ets' ? 'p:timeseries:ets' : spec.kind === 'smooth' ? 'p:timeseries:smoothing' : spec.inputs ? 'p:timeseries:transfer' : 'p:timeseries:arima';
    const ob = ctx.outline(`Model: ${name}`, { parent: box, key: `${sc}:model:${spec.id}`, info, menu: () => modelMenu(ctx, col, S, spec, r) });
    ob.el.classList.add('sm-ts-model');
    ob.el.style.setProperty('--ts-model-color', color);
    if (!r || r.error) { ob.add(ctx.warn(`${name}: ${r ? r.error : 'no result'}`)); return; }
    const flag = (k, d = true) => (spec[k] == null ? d : !!spec[k]);
    const sum = ctx.outline(spec.kind === 'ets' ? 'Model Summary' : 'Model Summary', { parent: ob, key: `${sc}:model:${spec.id}:sum` });
    sum.add(ctx.kv(r.summary.map(([label, v, f]) => [label, v, f || 'num'])));
    const pe = ctx.outline('Parameter Estimates', { parent: ob, key: `${sc}:model:${spec.id}:pe` });
    const seasonal = spec.kind === 'arima' && (spec.P || spec.D || spec.Q);
    if (r.params.rows.length) pe.add(ctx.rt({ columns: PARAM_COLS[r.params.columns](seasonal), rows: r.params.rows }, { sortable: false, name: `${name} parameter estimates` }));
    else pe.add(ctx.note('No parameters besides the variance.'));
    if (r.constant) pe.add(ctx.kv([['Constant Estimate', r.constant.estimate], ['Mu', r.constant.mu]]));
    ob.add(ctx.row(sum.el, pe.el));
    for (const n of r.notes || []) ob.add(ctx.note(n));
    // the forecast
    const fcOb = ctx.outline('Forecast', { parent: ob, key: `${sc}:model:${spec.id}:fc` });
    const traces = [];
    if (flag('points')) traces.push({ ...seriesTrace(S, S.values, col.name, { points: true, lines: false }), showlegend: false });
    traces.push(...forecastTraces(S, r, color, { pi: flag('pi'), name }));
    const end = S.x[S.x.length - 1];
    fcOb.add(ctx.plot(traces, { xaxis: xAxis(S), yaxis: { title: { text: col.name } }, shapes: [{ type: 'line', x0: end, x1: end, yref: 'paper', y0: 0, y1: 1, line: { color: SM.util.themeColors().muted, width: 1, dash: 'dot' } }] },
      { width: plotWidth(ctx, 620), height: 300, title: `${name} forecast` }));
    const fc = r.forecast;
    if (fc && fc.t.length) fcOb.add(ctx.note(`${fc.t.length} periods ahead, from ${tLabel(S, fc.t[0])} to ${tLabel(S, fc.t[fc.t.length - 1])}, with ${fmt(100 * r.level)}% prediction intervals; to the left of the dotted line the one-step-ahead forecasts.`));
    // the residuals
    const resOb = ctx.outline(spec.kind === 'ets' ? 'One-Step-Ahead Forecasting Errors' : 'Residuals', { parent: ob, key: `${sc}:model:${spec.id}:res` });
    resOb.add(ctx.plot([{ type: 'scatter', mode: 'markers', x: S.x, y: r.resid, rows: S.rowsLinked, name: 'Residual', marker: { size: 5, color } }],
      { xaxis: xAxis(S), yaxis: { title: { text: 'Residual' }, zeroline: true }, shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: SM.util.themeColors().muted, width: 1 } }] },
    { width: plotWidth(ctx, 620), height: 220, title: `${name} residuals` }));
    resOb.add(diagnosticsBlock(ctx, r.resid_diag, { acf: flag('racf'), pacf: flag('rpacf'), variogram: flag('rvario', false), ar: flag('rar', false), residual: true }));
    if (r.resid_diag && r.resid_diag.model_df) resOb.add(ctx.note(`Ljung-Box on the residuals: degrees of freedom are the lag less the ${r.resid_diag.model_df} ${spec.kind === 'smooth' ? 'smoothing weights' : 'ARMA parameters'}.`));
    if (spec.kind === 'ets' && r.states && Object.keys(r.states).length) {
      const cs = ctx.outline('Component States', { parent: ob, key: `${sc}:model:${spec.id}:states`, closed: true });
      for (const [k, v] of Object.entries(r.states)) {
        cs.add(ctx.plot([{ type: 'scatter', mode: 'lines', x: S.x, y: v, name: k, line: { color, width: 1.4 } }], { xaxis: xAxis(S), yaxis: { title: { text: k[0].toUpperCase() + k.slice(1) } } }, { width: plotWidth(ctx, 520), height: 180, title: `${name} ${k}` }));
      }
    }
    if (Array.isArray(r.iterations) && r.iterations.length) {
      const it = ctx.outline('Iteration History', { parent: ob, key: `${sc}:model:${spec.id}:iter`, closed: true });
      it.add(ctx.rt({ columns: [{ key: 'iter', label: 'Iter', fmt: 'int' }, { key: 'm2ll', label: '−2LogLikelihood' }], rows: r.iterations }, { sortable: false, maxRows: 60 }),
        ctx.note(r.converged ? `Converged after ${r.n_iter} iterations (L-BFGS on the exact likelihood).` : `Did not converge within ${maxiter(ctx)} iterations: raise them with Maximum Iterations in the red triangle.`));
    } else if (spec.kind === 'arima' && r.converged === false) ob.add(ctx.warn('The fit did not converge: raise Maximum Iterations in the red triangle.'));
    ob.add(ctx.code(r.code));
  }

  /* ---- saving ---------------------------------------------------------------------------------------------------------------- */
  const nanOf = (a) => (a || []).map((v) => (v == null ? NaN : v));

  function timeColumn(ctx, S, t) {
    return { name: ctx.name('time') || 'Row', dataType: 'numeric', values: t, format: isDate(S) ? { kind: S.kind } : null };
  }

  function saveModelTable(ctx, col, S, r) {
    const fc = r.forecast || { t: [], mean: [], se: [], lower: [], upper: [] };
    const h = fc.t.length;
    const lv = fmt(r.level);
    const pad = new Array(h).fill(NaN);
    const t = new SM.Table({
      name: `${col.name} ${r.name}`, source: `saved from ${ctx.report.title}`, notes: `${r.name}: one-step-ahead predictions, then ${h} forecasts with ${fmt(100 * r.level)}% prediction limits.`,
      columns: [
        timeColumn(ctx, S, [...S.t, ...fc.t]),
        { name: `Actual ${col.name}`, dataType: 'numeric', values: [...nanOf(S.values), ...pad] },
        { name: `Predicted ${col.name}`, dataType: 'numeric', values: [...nanOf(r.fitted), ...nanOf(fc.mean)] },
        { name: `Std Err Pred ${col.name}`, dataType: 'numeric', values: [...nanOf(r.fit_se), ...nanOf(fc.se)] },
        { name: `Residual ${col.name}`, dataType: 'numeric', values: [...nanOf(r.resid), ...pad] },
        { name: `Upper CL (${lv}) ${col.name}`, dataType: 'numeric', values: [...nanOf(r.fit_hi), ...nanOf(fc.upper)] },
        { name: `Lower CL (${lv}) ${col.name}`, dataType: 'numeric', values: [...nanOf(r.fit_lo), ...nanOf(fc.lower)] },
      ],
    });
    SM.app.addTable(t);
  }

  function combineForecasts(ctx, col, S, list, results) {
    const ok = list.map((s, i) => ({ s, r: results[i] })).filter((x) => x.r && !x.r.error);
    if (!ok.length) { SM.ui.toast('No fitted models to save'); return; }
    const h = Math.max(...ok.map((x) => x.r.forecast.t.length));
    const future = ok.find((x) => x.r.forecast.t.length === h).r.forecast.t;
    const columns = [timeColumn(ctx, S, [...S.t, ...future]), { name: `Actual ${col.name}`, dataType: 'numeric', values: [...nanOf(S.values), ...new Array(h).fill(NaN)] }];
    for (const { r } of ok) {
      const fc = r.forecast;
      const padTo = (a) => [...nanOf(a), ...new Array(h - fc.t.length).fill(NaN)];
      columns.push({ name: `Predicted ${r.name}`, dataType: 'numeric', values: [...nanOf(r.fitted), ...padTo(fc.mean)] },
        { name: `Lower CL ${r.name}`, dataType: 'numeric', values: [...nanOf(r.fit_lo), ...padTo(fc.lower)] },
        { name: `Upper CL ${r.name}`, dataType: 'numeric', values: [...nanOf(r.fit_hi), ...padTo(fc.upper)] });
    }
    SM.app.addTable(new SM.Table({ name: `${col.name} forecasts`, source: `saved from ${ctx.report.title}`, columns }));
  }

  /* ---- the dialogs ---------------------------------------------------------------------------------------------------------------- */
  const LEVEL = (v = 0.95) => ({ key: 'level', label: 'Prediction Interval', type: 'number', value: v });
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
      { key: 'p', label: 'p, Autoregressive Order', type: 'number', value: P0.p ?? 0 },
      { key: 'd', label: 'd, Differencing Order', type: 'number', value: P0.d ?? 0 },
      { key: 'q', label: 'q, Moving Average Order', type: 'number', value: P0.q ?? 0 },
    ];
    if (seasonal) fields.push(
      { key: 'P', label: 'P, Seasonal Autoregressive Order', type: 'number', value: P0.P ?? 0 },
      { key: 'D', label: 'D, Seasonal Differencing Order', type: 'number', value: P0.D ?? 1 },
      { key: 'Q', label: 'Q, Seasonal Moving Average Order', type: 'number', value: P0.Q ?? 1 },
      { key: 's', label: 'Observations per Period', type: 'number', value: period });
    fields.push(LEVEL(P0.level), { key: 'intercept', label: 'Intercept', type: 'check', value: P0.intercept ?? true }, { key: 'constrain', label: 'Constrain fit', type: 'check', value: P0.constrain ?? true });
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
      fields: [...keys.map((k) => ({ key: k, label: `${labels[k]} (range)`, value: start[k] })), { key: 's', label: 'Observations per Period', type: 'number', value: period }, LEVEL(),
        { key: 'intercept', label: 'Intercept', type: 'check', value: true }, { key: 'constrain', label: 'Constrain fit', type: 'check', value: true }],
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
    const fields = [
      { key: 'p', label: 'Noise p, Autoregressive Order', type: 'number', value: P0.p ?? 1 },
      { key: 'd', label: 'Noise d, Differencing Order', type: 'number', value: P0.d ?? 0 },
      { key: 'q', label: 'Noise q, Moving Average Order', type: 'number', value: P0.q ?? 0 },
      { key: 'P', label: 'Noise P, Seasonal Autoregressive Order', type: 'number', value: P0.P ?? 0 },
      { key: 'D', label: 'Noise D, Seasonal Differencing Order', type: 'number', value: P0.D ?? 0 },
      { key: 'Q', label: 'Noise Q, Seasonal Moving Average Order', type: 'number', value: P0.Q ?? 0 },
      { key: 's', label: 'Observations per Period', type: 'number', value: period },
    ];
    inputs.forEach((c, i) => {
      const p = pre.get(c.name);
      fields.push({ key: `use${i}`, label: `Input ${c.name}`, type: 'check', value: preset ? !!p : true },
        { key: `lag${i}`, label: `${c.name}: input lag (dead time)`, type: 'number', value: p ? p.lag || 0 : 0 },
        { key: `num${i}`, label: `${c.name}: numerator order (more lags)`, type: 'number', value: p ? p.num || 0 : 0 });
    });
    fields.push(LEVEL(P0.level), { key: 'intercept', label: 'Intercept', type: 'check', value: P0.intercept ?? true }, { key: 'constrain', label: 'Constrain fit', type: 'check', value: P0.constrain ?? true });
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

  async function smoothDialog(ctx, col, S, method, preset = null) {
    const P0 = preset || {};
    const seasonal = method === 'seasonal' || method === 'winters';
    const fields = [LEVEL(P0.level)];
    if (seasonal) fields.push({ key: 's', label: 'Observations per Period', type: 'number', value: P0.s || periodOf(ctx, S) });
    if (method === 'winters') fields.push({ key: 'mult', label: 'Seasonality', type: 'select', value: P0.multiplicative ? 'mul' : 'add', choices: [['add', 'Additive (JMP\'s Winters Method)'], ['mul', 'Multiplicative']] });
    const v = await SM.ui.form({
      title: `${SMOOTH_LABEL[method]}: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:smoothing',
      lead: 'The smoothing weights and the starting states that minimise the one-step-ahead squared errors (statsmodels\' holtwinters), with prediction intervals from the model\'s moving-average weights.',
      fields, validate: (x) => levelOk(x) || (seasonal && !(x.s >= 2) ? 'Observations per Period: at least 2' : null),
    });
    if (!v) return;
    addModels(ctx, col, [{ kind: 'smooth', method, s: seasonal ? Math.round(v.s) : 0, level: v.level, multiplicative: method === 'winters' && v.mult === 'mul' }]);
  }

  async function etsDialog(ctx, col, S) {
    const pos = S.values.every((v) => v == null || v > 0);
    const period = periodOf(ctx, S);
    const v = await SM.ui.form({
      title: `Specify State Space Smoothing Models: ${col.name}`, okLabel: 'OK', info: 'p:timeseries:ets',
      lead: 'ETS(error, trend, seasonal) models of Hyndman et al. (2008): every combination of the boxes checked is fitted by maximum likelihood and compared by AICc. statsmodels has no multiplicative trend. Multiplicative parts need values above zero.',
      fields: [
        { key: 'eA', label: 'Error: Additive (A)', type: 'check', value: true }, { key: 'eM', label: 'Error: Multiplicative (M)', type: 'check', value: pos },
        { key: 'tN', label: 'Trend: None (N)', type: 'check', value: true }, { key: 'tA', label: 'Trend: Additive (A)', type: 'check', value: true }, { key: 'tAd', label: 'Trend: Additive damped (Ad)', type: 'check', value: true },
        { key: 'sN', label: 'Seasonal: None (N)', type: 'check', value: true }, { key: 'sA', label: 'Seasonal: Additive (A)', type: 'check', value: period >= 2 }, { key: 'sM', label: 'Seasonal: Multiplicative (M)', type: 'check', value: pos && period >= 2 },
        { key: 'period', label: 'Period', type: 'number', value: period },
        { key: 'stable', label: 'Leave out additive errors with multiplicative seasonality (unstable)', type: 'check', value: true },
        LEVEL(),
      ],
      validate: (x) => {
        if (!x.eA && !x.eM) return 'Check an error type';
        if (!x.tN && !x.tA && !x.tAd) return 'Check a trend';
        if (!x.sN && !x.sA && !x.sM) return 'Check a seasonal component';
        if ((x.eM || x.sM) && !pos) return 'Multiplicative errors and seasonality need every value above zero';
        if ((x.sA || x.sM) && !(x.period >= 2)) return 'Period: at least 2 for seasonal models';
        return levelOk(x);
      },
    });
    if (!v) return;
    const g = nextGroup(ctx, col);
    const specs = [];
    for (const [ek, e] of [['eA', 'add'], ['eM', 'mul']]) for (const [tk, t] of [['tN', 'N'], ['tA', 'A'], ['tAd', 'Ad']]) for (const [sk, s] of [['sN', 'N'], ['sA', 'A'], ['sM', 'M']]) {
      if (!v[ek] || !v[tk] || !v[sk]) continue;
      if (v.stable && e === 'add' && s === 'M') continue;
      specs.push({ kind: 'ets', error: e, trend: t, seasonal: s, s: s !== 'N' ? Math.round(v.period) : 0, level: v.level, group: g });
    }
    if (!specs.length) { SM.ui.toast('No models left to fit'); return; }
    addModels(ctx, col, specs);
  }

  function fitNew(ctx, col, S, spec) {
    if (spec.kind === 'arima' && spec.inputs) return transferDialog(ctx, col, S, spec);
    if (spec.kind === 'arima') return arimaDialog(ctx, col, S, { seasonal: !!(spec.P || spec.D || spec.Q), preset: spec });
    if (spec.kind === 'smooth') return smoothDialog(ctx, col, S, spec.method, spec);
    return etsDialog(ctx, col, S);
  }

  async function differenceDialog(ctx, col, S) {
    const v = await SM.ui.form({
      title: `Differencing Specification: ${col.name}`, okLabel: 'Estimate', info: 'p:timeseries:difference',
      lead: 'w_t = (1 − B)^d (1 − B^s)^D y_t. Each Estimate adds a Difference report.',
      fields: [
        { key: 'd', label: 'Nonseasonal Differencing Order, d', type: 'select', value: '1', choices: [['0', '0'], ['1', '1'], ['2', '2']] },
        { key: 'D', label: 'Seasonal Differencing Order, D', type: 'select', value: '0', choices: [['0', '0'], ['1', '1'], ['2', '2']] },
        { key: 's', label: 'Observations per Period, s', type: 'number', value: periodOf(ctx, S) },
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
      const v = await SM.ui.form({ title: `Define Cycle: ${col.name}`, info: 'p:timeseries:decomposition', fields: [{ key: 'units', label: 'Units per Cycle', type: 'number', value: period }, { key: 'constant', label: 'Subtract a constant', type: 'check', value: true }], validate: (x) => (x.units > 1 ? null : 'Units per Cycle: above 1') });
      if (!v) return;
      spec = { kind, units: v.units, constant: !!v.constant };
    } else if (kind === 'classical') {
      const v = await SM.ui.form({ title: `Seasonal Decomposition: ${col.name}`, info: 'p:timeseries:decomposition', fields: [{ key: 'period', label: 'Period', type: 'number', value: period }, { key: 'model', label: 'Decomposition Type', type: 'select', value: 'additive', choices: [['additive', 'Additive'], ['multiplicative', 'Multiplicative']] }], validate: (x) => (x.period >= 2 ? null : 'Period: at least 2') });
      if (!v) return;
      spec = { kind, period: Math.round(v.period), model: v.model };
    } else if (kind === 'stl') {
      const v = await SM.ui.form({ title: `STL Decomposition: ${col.name}`, info: 'p:timeseries:decomposition', fields: [{ key: 'period', label: 'Period', type: 'number', value: period }, { key: 'robust', label: 'Robust (downweights outliers)', type: 'check', value: false }], validate: (x) => (x.period >= 2 ? null : 'Period: at least 2') });
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
      { separator: true },
      { label: 'Difference…', action: withS((S) => differenceDialog(ctx, col, S)) },
      { label: 'Decomposition', submenu: () => [
        { label: 'Remove Linear Trend', action: withS((S) => addDecomp(ctx, col, S, 'trend')) },
        { label: 'Remove Cycle…', action: withS((S) => addDecomp(ctx, col, S, 'cycle')) },
        { label: 'Seasonal Decomposition…', action: withS((S) => addDecomp(ctx, col, S, 'classical')) },
        { label: 'STL Decomposition…', action: withS((S) => addDecomp(ctx, col, S, 'stl')) },
        { label: 'X11', disabled: true, title: 'X-11 needs the Census Bureau\'s X-13ARIMA-SEATS program, which does not run in the browser' },
      ] },
      { label: 'Show Lag Plot', checked: o('lagPlot', null) != null, action: () => ctx.set('lagPlot', o('lagPlot', null) != null ? null : 1, sc) },
      { label: 'Cross Correlation', checked: !!o('ccf', false), disabled: !hasInputs, action: () => ctx.set('ccf', !o('ccf', false), sc) },
      hasInputs ? ctx.check('Input Time Series Panel', 'inputPanel', sc, true) : null,
      { separator: true },
      { label: 'ARIMA…', action: withS((S) => arimaDialog(ctx, col, S)) },
      { label: 'Seasonal ARIMA…', action: withS((S) => arimaDialog(ctx, col, S, { seasonal: true })) },
      { label: 'ARIMA Model Group…', action: withS((S) => groupDialog(ctx, col, S)) },
      { label: 'Transfer Function…', disabled: !hasInputs, action: withS((S) => transferDialog(ctx, col, S)) },
      { label: 'Smoothing Models', submenu: () => SMOOTH.map(([k, label]) => ({ label: `${label}…`, action: withS((S) => smoothDialog(ctx, col, S, k)) })) },
      { label: 'State Space Smoothing Models…', action: withS((S) => etsDialog(ctx, col, S)) },
      { separator: true },
      { label: 'Combine and Save Forecasts from Models', disabled: !o('models', []).length, action: withS(async (S) => {
        const list = o('models', []);
        const base = basePayload(ctx, col);
        const results = await Promise.all(list.map((spec) => fitCall(ctx, base, spec, horizon(ctx)).catch((e) => ({ error: e.message }))));
        combineForecasts(ctx, col, S, list, results);
      }) },
      { label: 'Save Spectral Density', action: async () => { const r = await ctx.call('timeseries.spectral', basePayload(ctx, col)); if (r.error) SM.ui.toast(r.error, { error: true }); else saveSpectral(col, r); } },
    ].filter(Boolean);
  }

  function globalItems(ctx) {
    return [
      { label: 'Number of Forecast Periods…', action: async () => { const v = await SM.ui.form({ title: 'Number of Forecast Periods', fields: [{ key: 'n', label: 'Forecast periods for every model', type: 'number', value: horizon(ctx) }], validate: (x) => (x.n >= 0 && x.n <= 1000 ? null : 'from 0 to 1000') }); if (v) ctx.set('forecast', Math.round(v.n)); } },
      { label: 'Maximum Iterations…', action: async () => { const v = await SM.ui.form({ title: 'Maximum Iterations', lead: 'For the ARIMA and state space fits from now on.', fields: [{ key: 'n', label: 'Maximum iterations', type: 'number', value: maxiter(ctx) }], validate: (x) => (x.n >= 5 && x.n <= 10000 ? null : 'from 5 to 10000') }); if (v) ctx.set('maxiter', Math.round(v.n)); } },
    ];
  }

  /* ---- topics for the (i) --------------------------------------------------------------------------------------------------------------------------- */
  const topics = {
    'p:timeseries': {
      kicker: 'Analyze > Specialized Modeling', title: 'Time Series',
      lead: 'One series in time order: its graph, autocorrelations and stationarity tests; differencing and decomposition; the spectral density; and ARIMA, seasonal ARIMA, transfer function, smoothing and state space smoothing models with forecasts, compared in one table.',
      sections: [
        { heading: 'Roles', choices: [['Y, Time Series', 'The series, one report each (continuous columns).'], ['Input List', 'Numeric input series for cross correlations and transfer functions; indicators such as a promotion flag work.'], ['X, Time ID', 'Orders the rows and labels the time axis; a date column gives the calendar frequency, the seasonal period and the forecast dates.'], ['By', 'A report for each level.']] },
        { heading: 'Options', choices: [['Forecast Periods', 'How many periods each model forecasts (default 25).'], ['Autocorrelation Lags', 'How many lags the correlations go to (default 25; n/4 is a common choice).'], ['Seasonal Period', 'The default observations per period in the dialogs; empty takes it from the Time ID (12 for monthly data).']] },
        { heading: 'Missing and excluded rows', text: 'Excluded rows count as missing values, as in JMP, so the spacing of the series is kept; dates missing from a regular calendar are inserted as missing too. ARIMA models skip missing values in the likelihood; the smoothing and decomposition methods fill them by interpolation, and say so.' },
        { heading: 'Differences from JMP', list: ['ARIMA: statsmodels\' exact likelihood; AIC and SBC count the parameters as JMP does (statsmodels also counts σ², shown in the notes). MA coefficients have statsmodels\' sign, the opposite of JMP\'s.', 'Smoothing models: weights and starting states by least squares (holtwinters), not JMP\'s ARIMA-equivalent fit; prediction intervals from the same moving-average weights JMP uses.', 'ADF lags by AIC; KPSS, STL and state space model selection by AICc are additions. X-11 is not available.'] },
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
    'p:timeseries:lag': { kicker: 'Time Series', title: 'Lag Plot', lead: 'Each observation against the one p periods earlier. A cloud with no shape says the observations are unrelated at that lag; a line or a curve says they are related. Change p in the box; points are linked to the rows.', more: MORE },
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
      lead: 'Simple, Double (Brown), Linear (Holt), Damped-Trend Linear, Seasonal and Winters exponential smoothing with statsmodels\' holtwinters: the weights and starting states minimise the one-step-ahead squared errors. Prediction intervals use the moving-average weights ψ_j of each model\'s ARIMA form, as JMP documents them.',
      sections: [
        { heading: 'Weights', text: 'Level α, trend γ, damping φ and seasonal δ in JMP\'s form; statsmodels\' smoothing_seasonal is δ(1 − α), and Brown\'s α is Holt\'s method with level α(2 − α) and trend α/(2 − α). statsmodels keeps the trend weight at or below the level weight.' },
        { heading: 'Differences from JMP', text: 'JMP fits the equivalent ARIMA model, so its estimates and above all its starting values differ; the standard errors here come from the likelihood\'s Hessian with the starting states held. Missing values are filled by interpolation for the fit.' },
      ],
      more: MORE,
    },
    'p:timeseries:ets': { kicker: 'Time Series', title: 'State Space Smoothing', lead: 'ETS(error, trend, seasonal) models (Hyndman et al. 2008) with additive or multiplicative errors, no, additive or damped trend, and no, additive or multiplicative seasonality, fitted by maximum likelihood with statsmodels\' ETSModel and ranked by AICc. Their likelihood is not comparable with the ARIMA models\', as JMP also warns. Multiplicative models get simulated prediction intervals (a fixed seed).', more: MORE },
    'p:timeseries:comparison': { kicker: 'Time Series', title: 'Model Comparison', lead: 'Every fitted model with DF, variance, AIC, SBC, AICc, RSquare, −2LogLikelihood, AIC weights, MAPE and MAE, sorted by AIC. Report shows the model\'s report; Graph overlays its forecasts, prediction interval and residual autocorrelations in the plots below. The red triangle removes or hides models, and saves all forecasts in one new table.', more: MORE },
  };

  /* ---- the platform ------------------------------------------------------------------------------------------------------------------------------------ */
  SM.platforms.register({
    id: 'timeseries', label: 'Time Series', menu: 'Analyze/Specialized Modeling', order: 20, info: 'p:timeseries', topics,
    about: 'One series in time order: its graph with the ADF tests, autocorrelations with Ljung-Box, partial autocorrelations, variogram, KPSS; differencing, linear trend and cycle removal, seasonal decomposition and STL; the spectral density with the white noise tests; lag plots and cross correlations; ARIMA, seasonal ARIMA and ARIMA model groups, transfer functions (ARIMAX), the smoothing models and state space smoothing (ETS), each with forecasts that continue the dates, compared in one table.',
    uses: ['statsmodels.tsa.stattools.acf, pacf, adfuller, kpss, ccf, levinson_durbin', 'statsmodels.stats.diagnostic.acorr_ljungbox', 'statsmodels.tsa.arima.model.ARIMA',
      'statsmodels.tsa.holtwinters.ExponentialSmoothing', 'statsmodels.tsa.exponential_smoothing.ets.ETSModel', 'statsmodels.tsa.seasonal.seasonal_decompose, STL',
      'statsmodels.tsa.statespace.tools.diff', 'statsmodels.regression.linear_model.OLS', 'pandas.infer_freq', 'numpy.fft'],
    launch: {
      lead: 'Choose the series. A date column as X, Time ID gives a date axis, the seasonal period and the dates of the forecasts; Input List columns are the inputs of transfer functions.',
      roles: [
        { key: 'y', label: 'Y, Time Series', min: 1, types: ['continuous'], hint: 'required: one or more continuous' },
        { key: 'inputs', label: 'Input List', numeric: true, hint: 'optional numeric: inputs of transfer functions' },
        { key: 'time', label: 'X, Time ID', max: 1, numeric: true, hint: 'optional: a date or a time step', info: 'p:timeseries:timeid' },
        { key: 'by', label: 'By', hint: 'optional' },
      ],
      options: [
        { key: 'forecast', label: 'Forecast Periods', type: 'number', value: 25 },
        { key: 'nlags', label: 'Autocorrelation Lags', type: 'number', value: 25 },
        { key: 'period', label: 'Seasonal Period (empty: from the Time ID)', type: 'number', value: '' },
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
  SM.timeseries = Object.freeze({ groupRows, barSvg, parseRange, effective, specName });
}(typeof self !== 'undefined' ? self : this));
