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
  const NEW_KINDS = new Set(['uc', 'markov', 'theta', 'ardl']);
  const UI_FLAGS = new Set(['id', 'group', 'report', 'graph', 'points', 'pi', 'racf', 'rpacf', 'rvario', 'rar', 'comps', 'fprob', 'smpi']);

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
    return { type: S.t.length > 5000 ? 'scattergl' : 'scatter', mode, x: S.x, y: values, rows: S.rowsLinked, name: ptext(name), connectgaps: false, line: { color, width: 1.2 }, marker: { size: 5, color } };
  }

  function seriesPlot(ctx, S, values, name, { points = true, lines = true, meanLine = null, extra = [], height = 260, width = 560, title } = {}) {
    const shapes = [];
    if (meanLine != null && Number.isFinite(meanLine)) shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: meanLine, y1: meanLine, line: { color: '#b0413e', width: 1, dash: 'dot' } });
    const traces = [];
    if (points || lines) traces.push(seriesTrace(S, values, name, { points, lines }));
    traces.push(...extra);
    return ctx.plot(traces, { xaxis: xAxis(S), yaxis: { title: { text: ptext(name) } }, shapes }, { width: plotWidth(ctx, width), height, title: title || `${name} time series` });
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
    const plot = ctx.plot([{ type: 'scatter', mode: 'markers', x, y, rows, name: ptext(`${col.name} at t and t − ${lag}`) }],
      { xaxis: { title: { text: ptext(`${col.name}(t − ${lag})`) } }, yaxis: { title: { text: ptext(`${col.name}(t)`) } } }, { width: plotWidth(ctx, 360), height: 320, title: `${col.name} lag plot` });
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
      ob.add(ctx.plot([seriesTrace(S, S.values, col.name)], { xaxis: xAxis(S), yaxis: { title: { text: ptext(col.name) } }, shapes, annotations },
        { width: plotWidth(ctx, 560), height: 220, title: `${col.name} Zivot-Andrews breaks` }));
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
        { key: 'trim', label: 'Trimming at each end (0 to 1/3)', type: 'number', value: o.trim },
        { key: 'maxlag', label: 'Largest lag (empty: automatic)', type: 'number', value: o.maxlag ?? '' },
        { key: 'autolag', label: 'Lags chosen by', type: 'select', value: o.autolag || 'none', choices: [['AIC', 'AIC'], ['BIC', 'BIC'], ['t-stat', 't statistic of the last lag'], ['none', 'none: the largest lag']] },
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
    ob.add(ctx.plot(traces, {
      xaxis: { tickvals: r.seasons.map((s) => (s.x[0] + s.x[s.x.length - 1]) / 2), ticktext: r.seasons.map((s) => s.label), showgrid: false, zeroline: false,
        title: { text: r.by === 'position' ? `Position in the period of ${r.period}` : '' } },
      yaxis: { title: { text: ptext(col.name) } }, shapes,
    }, { width: plotWidth(ctx, 720), height: 300, title: `${col.name} seasonal subseries` }));
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
    ob.add(ctx.row(ctx.plot(traces, layout, { width: plotWidth(ctx, 620), height: 400, title: r.label }),
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
      ? [{ key: 'lamb', label: 'λ, Smoothing', type: 'number', value: D.lamb }]
      : [{ key: 'low', label: 'Shortest period in the band', type: 'number', value: D.low }, { key: 'high', label: 'Longest period in the band', type: 'number', value: D.high }];
    if (kind === 'bk') fields.push({ key: 'K', label: 'K, Lead-lag length (values lost at each end)', type: 'number', value: D.K });
    if (kind === 'cf') fields.push({ key: 'drift', label: 'Remove the drift first', type: 'check', value: true });
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
  function fitCall(ctx, base, spec, h) {
    if (spec.kind === 'arima') {
      return ctx.call('timeseries.arima', { ...base, p: spec.p, d: spec.d, q: spec.q, P: spec.P || 0, D: spec.D || 0, Q: spec.Q || 0, s: spec.s || 0,
        intercept: spec.intercept !== false, constrain: spec.constrain !== false, level: spec.level || 0.95, h, maxiter: maxiter(ctx), inputs: spec.inputs || null });
    }
    if (spec.kind === 'smooth') return ctx.call('timeseries.smooth', { ...base, method: spec.method, s: spec.s || 0, level: spec.level || 0.95, h, multiplicative: !!spec.multiplicative });
    if (spec.kind === 'ets') return ctx.call('timeseries.ets', { ...base, error: spec.error, trend: spec.trend, seasonal: spec.seasonal, s: spec.s || 0, level: spec.level || 0.95, h, maxiter: Math.max(200, maxiter(ctx)) });
    if (spec.kind === 'uc') {
      return ctx.call('timeseries.structural', { ...base, trend: spec.trend, seasonal: spec.seasonal || 0, stoch_seasonal: spec.stochSeasonal !== false,
        freq_period: spec.freqPeriod || 0, freq_harmonics: spec.freqHarmonics || 0, stoch_freq: spec.stochFreq !== false, cycle: !!spec.cycle,
        stoch_cycle: spec.stochCycle !== false, damped_cycle: spec.damped !== false, cycle_lo: spec.cycleLo ?? null, cycle_hi: spec.cycleHi ?? null,
        ar: spec.ar || 0, inputs: spec.inputs || null, exact: !!spec.exact, level: spec.level || 0.95, h, maxiter: maxiter(ctx) });
    }
    if (spec.kind === 'markov') {
      return ctx.call('timeseries.markov', { ...base, k: spec.k || 2, order: spec.order || 0, trend: spec.trend || 'c', switching_trend: spec.swTrend !== false,
        switching_variance: !!spec.swVar, switching_ar: !!spec.swAr, starts: spec.starts ?? 5, maxiter: Math.min(500, maxiter(ctx)), level: spec.level || 0.95 });
    }
    if (spec.kind === 'theta') {
      return ctx.call('timeseries.theta', { ...base, period: spec.period || 0, deseasonalize: spec.deseasonalize !== false, use_test: spec.useTest !== false,
        method: spec.method || 'auto', theta: spec.theta || 2, use_mle: !!spec.mle, level: spec.level || 0.95, h });
    }
    if (spec.kind === 'ardl') {
      return ctx.call('timeseries.ardl', { ...base, inputs: spec.inputs || [], maxlag: spec.maxlag || 4, maxorder: spec.maxorder ?? 4, order: spec.order || null,
        trend: spec.trend || 'c', ic: spec.ic || 'aic', glob: !!spec.glob, causal: !!spec.causal, seasonal: !!spec.seasonal, period: spec.period || 0,
        case: spec.case || null, level: spec.level || 0.95, h });
    }
    return Promise.resolve({ error: `unknown model ${spec.kind}` });
  }

  const fitKey = (s) => (NEW_KINDS.has(s.kind) ? JSON.stringify(Object.keys(s).filter((k) => !UI_FLAGS.has(k)).sort().map((k) => [k, s[k]]))
    : JSON.stringify([s.kind, s.p, s.d, s.q, s.P, s.D, s.Q, s.s, s.intercept, s.constrain, s.level, s.inputs, s.method, s.multiplicative, s.error, s.trend, s.seasonal]));

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
    const results = (await Promise.all(list.map((spec) => fitCall(ctx, base, spec, h).catch((e) => ({ error: e.message || String(e) }))))).map((r, i) => withOwnBand(list[i], r));
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
    const own = [kinds.has('uc') && 'the structural models\' leaves out the diffuse start', kinds.has('markov') && 'the regime-switching models\' is a mixture over the regimes (with an AR part, conditional on its first observations)',
      kinds.has('ardl') && 'the ARDL models\' is conditional on the lags\' starting values', kinds.has('theta') && 'the Theta model\'s is that of its one-step errors'].filter(Boolean);
    if (own.length && kinds.size > 1) ob.add(ctx.note(`Across classes the likelihoods differ in detail: ${own.join('; ')}. Their AICs are close relatives, not the same quantity; MAPE and MAE compare directly.`));
    ob.add(ctx.note('Sorted by AIC; click a heading to sort. Weights are AIC weights, exp(−ΔAIC/2) normalised. Report shows a model\'s report, Graph puts it on the plots below. AIC, SBC and AICc count the fitted parameters as JMP does (not the variance).'));
    // the model plots: forecasts, and the residual autocorrelations
    const shown = list.map((s, i) => ({ s, r: results[i], on: eff[i].graph })).filter((x) => x.on && x.r && !x.r.error);
    if (!shown.length) return;
    const traces = [{ ...seriesTrace(S, S.values, col.name, { points: true, lines: false }), showlegend: false }];
    for (const { s, r } of shown) traces.push(...forecastTraces(S, r, colorOf(s.id), { pi: true, name: r.name, legend: true, oneStepPI: false }));
    const end = S.x[S.x.length - 1];
    const plot = ctx.plot(traces, { xaxis: xAxis(S), yaxis: { title: { text: ptext(col.name) } }, showlegend: true, legend: { orientation: 'h', y: -0.22 },
      shapes: [{ type: 'line', x0: end, x1: end, yref: 'paper', y0: 0, y1: 1, line: { color: SM.util.themeColors().muted, width: 1, dash: 'dot' } }] },
    { width: plotWidth(ctx, 640), height: 320 + 18 * Math.ceil(shown.length / 2), title: `${col.name} model comparison forecasts` });
    const acfOver = (key, label) => {
      const tr = [];
      let n = 0;
      for (const { s, r } of shown) {
        const D = r.resid_diag;
        if (!D || D.error) continue;
        n = Math.max(n, D.n);
        tr.push({ type: 'scatter', mode: 'lines+markers', x: D[key].lag.slice(1), y: D[key].r.slice(1), name: ptext(r.name), line: { color: colorOf(s.id), width: 1.2 }, marker: { size: 4, color: colorOf(s.id) }, hovertemplate: `${ptext(r.name)}: lag %{x}, %{y:.4f}<extra></extra>` });
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
    uc: () => [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'z', label: 'z Ratio' }, { key: 'p', label: 'Prob>|z|', fmt: 'p' }],
    markov: () => [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'regime', label: 'Regime', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'z', label: 'z Ratio' }, { key: 'p', label: 'Prob>|z|', fmt: 'p' }],
    theta: () => [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }],
    ardl: () => [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }],
  };
  const MODEL_INFO = { ets: 'p:timeseries:ets', smooth: 'p:timeseries:smoothing', uc: 'p:timeseries:structural', markov: 'p:timeseries:regime', theta: 'p:timeseries:theta', ardl: 'p:timeseries:ardl' };

  function modelMenu(ctx, col, S, spec, r) {
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
    }
    return [
      { label: 'Show Points', checked: flag('points'), action: () => up({ points: !flag('points') }) },
      { label: 'Show Prediction Interval', checked: flag('pi'), action: () => up({ pi: !flag('pi') }) },
      { label: 'Save Columns', disabled: !r || !!r.error, action: () => saveModelTable(ctx, col, S, r) },
      ...own,
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
    const info = MODEL_INFO[spec.kind] || (spec.inputs ? 'p:timeseries:transfer' : 'p:timeseries:arima');
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
    // the forecast (a Markov switching model has none: its one-step-ahead predictions)
    const fcOb = ctx.outline(spec.kind === 'markov' ? 'One-Step-Ahead Predictions' : 'Forecast', { parent: ob, key: `${sc}:model:${spec.id}:fc` });
    const traces = [];
    if (flag('points')) traces.push({ ...seriesTrace(S, S.values, col.name, { points: true, lines: false }), showlegend: false });
    traces.push(...forecastTraces(S, r, color, { pi: flag('pi'), name }));
    const end = S.x[S.x.length - 1];
    fcOb.add(ctx.plot(traces, { xaxis: xAxis(S), yaxis: { title: { text: ptext(col.name) } }, shapes: [{ type: 'line', x0: end, x1: end, yref: 'paper', y0: 0, y1: 1, line: { color: SM.util.themeColors().muted, width: 1, dash: 'dot' } }] },
      { width: plotWidth(ctx, 620), height: 300, title: `${name} forecast` }));
    const fc = r.forecast;
    if (fc && fc.t.length) fcOb.add(ctx.note(`${fc.t.length} periods ahead, from ${tLabel(S, fc.t[0])} to ${tLabel(S, fc.t[fc.t.length - 1])}, with ${fmt(100 * r.level)}% prediction intervals; to the left of the dotted line the one-step-ahead forecasts.`));
    // the residuals
    const resOb = ctx.outline(spec.kind === 'ets' ? 'One-Step-Ahead Forecasting Errors' : 'Residuals', { parent: ob, key: `${sc}:model:${spec.id}:res` });
    resOb.add(ctx.plot([{ type: 'scatter', mode: 'markers', x: S.x, y: r.resid, rows: S.rowsLinked, name: 'Residual', marker: { size: 5, color } }],
      { xaxis: xAxis(S), yaxis: { title: { text: 'Residual' }, zeroline: true }, shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: SM.util.themeColors().muted, width: 1 } }] },
    { width: plotWidth(ctx, 620), height: 220, title: `${name} residuals` }));
    resOb.add(diagnosticsBlock(ctx, r.resid_diag, { acf: flag('racf'), pacf: flag('rpacf'), variogram: flag('rvario', false), ar: flag('rar', false), residual: true }));
    if (r.resid_diag && r.resid_diag.model_df) resOb.add(ctx.note(`Ljung-Box on the residuals: degrees of freedom are the lag less the ${r.resid_diag.model_df} ${spec.kind === 'smooth' || spec.kind === 'theta' ? `smoothing weight${r.resid_diag.model_df > 1 ? 's' : ''}` : spec.kind === 'ardl' ? `lag${r.resid_diag.model_df > 1 ? 's' : ''} of the series` : 'ARMA parameters'}.`));
    if (spec.kind === 'uc' && flag('comps')) componentsReport(ctx, col, S, spec, r, ob);
    if (spec.kind === 'markov') regimeReport(ctx, col, S, spec, r, ob);
    if (spec.kind === 'ardl') ardlReport(ctx, col, S, spec, r, ob);
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
    cp.add(ctx.plot(traces, layout, { width: plotWidth(ctx, 640), height: Math.max(260, 125 * n + 60), title: `${r.name} components` }));
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
    pr.add(ctx.plot([seriesTrace(S, S.values, col.name, { color: ink }), ...legend], { xaxis: xAxis(S), yaxis: { title: { text: ptext(col.name) } }, shapes, showlegend: true, legend: { orientation: 'h', y: -0.25 } },
      { width: plotWidth(ctx, 620), height: 290, title: `${r.name} regimes`, rowColors: false }));
    const flag = spec.fprob === true;
    const ptr = r.prob.map((p, j) => ({ type: 'scatter', mode: 'lines+markers', x: S.x, y: p, rows: S.rowsLinked, name: `Regime ${j}`, line: { color: regimeColor(j), width: 1.5 },
      marker: { size: 3, color: regimeColor(j) }, hovertemplate: `P(regime ${j}) %{y:.3f}<extra></extra>` }));
    if (flag) r.fprob.forEach((p, j) => ptr.push({ type: 'scatter', mode: 'lines', x: S.x, y: p, name: `Regime ${j} filtered`, line: { color: regimeColor(j), width: 1, dash: 'dot' }, hovertemplate: `filtered P(regime ${j}) %{y:.3f}<extra></extra>` }));
    pr.add(ctx.plot(ptr, { xaxis: xAxis(S), yaxis: { title: { text: 'Smoothed probability' }, range: [-0.03, 1.03] }, showlegend: true, legend: { orientation: 'h', y: -0.25 } },
      { width: plotWidth(ctx, 620), height: 260, title: `${r.name} smoothed probabilities`, rowColors: false }));
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
      { key: 'trend', label: 'Level and Trend', type: 'select', value: P0.trend || 'local linear trend', choices: UC_TRENDS },
      { key: 'seas', label: 'Seasonal', type: 'select', value: seasonalDefault, choices: [['none', 'None'], ['dummy', 'Seasonal dummies (time domain)'], ['trig', 'Trigonometric (frequency domain)']] },
      { key: 'period', label: 'Seasonal Period', type: 'number', value: period },
      { key: 'harmonics', label: 'Harmonics, trigonometric (empty: all)', type: 'number', value: P0.freqHarmonics || '' },
      { key: 'stochSeasonal', label: 'Stochastic seasonal (it may change over time)', type: 'check', value: P0.kind ? (P0.seasonal ? P0.stochSeasonal !== false : P0.stochFreq !== false) : true },
      { key: 'cycle', label: 'Cycle', type: 'check', value: !!P0.cycle },
      { key: 'stochCycle', label: 'Stochastic cycle', type: 'check', value: P0.stochCycle !== false },
      { key: 'damped', label: 'Damped cycle', type: 'check', value: P0.damped !== false },
      { key: 'cycleLo', label: 'Cycle period from (empty: statsmodels\' default)', type: 'number', value: P0.cycleLo ?? '' },
      { key: 'cycleHi', label: 'Cycle period to (empty: statsmodels\' default)', type: 'number', value: P0.cycleHi ?? '' },
      { key: 'ar', label: 'Autoregressive Order', type: 'number', value: P0.ar || 0 },
    ];
    inputs.forEach((c, i) => fields.push({ key: `use${i}`, label: `Input ${c.name}`, type: 'check', value: preset ? pre.has(c.name) : true }));
    fields.push({ key: 'exact', label: 'Exact diffuse initialization', type: 'check', value: !!P0.exact }, LEVEL(P0.level));
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
        { key: 'k', label: 'Number of Regimes', type: 'select', value: String(P0.k || 2), choices: [['2', '2'], ['3', '3']] },
        { key: 'order', label: 'Autoregressive Order (0: switching regression)', type: 'number', value: P0.order || 0 },
        { key: 'trend', label: 'Mean', type: 'select', value: P0.trend || 'c', choices: [['c', 'Intercept'], ['ct', 'Intercept and linear trend'], ['n', 'None (only the variance switches)']] },
        { key: 'swTrend', label: 'Switching mean (and trend)', type: 'check', value: P0.swTrend !== false },
        { key: 'swVar', label: 'Switching variance', type: 'check', value: !!P0.swVar },
        { key: 'swAr', label: 'Switching AR coefficients', type: 'check', value: !!P0.swAr },
        { key: 'starts', label: 'Random Starts', type: 'number', value: P0.starts ?? 5 },
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
        { key: 'theta', label: 'θ, Theta (at least 1)', type: 'number', value: P0.theta || 2 },
        { key: 'deseasonalize', label: 'Deseasonalize', type: 'check', value: P0.deseasonalize ?? period >= 2 },
        { key: 'period', label: 'Seasonal Period', type: 'number', value: period },
        { key: 'useTest', label: 'Test for seasonality first (10%)', type: 'check', value: P0.useTest !== false },
        { key: 'method', label: 'Deseasonalizing', type: 'select', value: P0.method || 'auto', choices: [['auto', 'Automatic: multiplicative if every value is above zero'], ['multiplicative', 'Multiplicative'], ['additive', 'Additive']] },
        { key: 'mle', label: 'Estimate by maximum likelihood (an IMA(1, 1) with drift)', type: 'check', value: !!P0.mle },
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
    inputs.forEach((c, i) => fields.push({ key: `use${i}`, label: `Input ${c.name}`, type: 'check', value: preset ? pre.has(c.name) : true }));
    const ordersText = P0.order ? [P0.order.p || 0, ...(P0.inputs || []).map((c) => (P0.order.q && P0.order.q[c] != null ? P0.order.q[c] : '-'))].join(', ') : '';
    fields.push(
      { key: 'maxlag', label: `Largest lag of ${col.name}, p`, type: 'number', value: P0.maxlag || 4 },
      { key: 'maxorder', label: 'Largest lag of the inputs, q', type: 'number', value: P0.maxorder ?? 4 },
      { key: 'ic', label: 'Choose the orders by', type: 'select', value: P0.ic || 'aic', choices: [['aic', 'AIC'], ['bic', 'BIC']] },
      { key: 'glob', label: 'Search every subset of lags (slow)', type: 'check', value: !!P0.glob },
      { key: 'orders', label: 'Or fixed orders p, q1, q2 … (- leaves an input out)', type: 'text', value: ordersText, placeholder: 'empty: choose them' },
      { key: 'trend', label: 'Deterministic Terms', type: 'select', value: P0.trend || 'c', choices: [['c', 'Intercept'], ['ct', 'Intercept and trend'], ['n', 'None']] },
      { key: 'case', label: 'Bounds Test Case', type: 'select', value: String(P0.case || ''), choices: [['', 'Automatic: 3 with an intercept, 4 with a trend, 1 with neither'], ['1', '1: no intercept, no trend'], ['2', '2: restricted intercept'], ['3', '3: unrestricted intercept'], ['4', '4: restricted trend'], ['5', '5: unrestricted trend']] },
      { key: 'causal', label: 'Causal: the inputs from lag 1 on', type: 'check', value: !!P0.causal },
      { key: 'seasonal', label: 'Seasonal dummies', type: 'check', value: !!P0.seasonal },
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
      { label: 'Zivot-Andrews Test', checked: !!o('stationarity', true) && zivotOn(ctx, col), action: () => { if (!o('stationarity', true)) { ctx.set('zivot', true, sc, { rerun: false }); ctx.set('stationarity', true, sc); } else ctx.set('zivot', !zivotOn(ctx, col), sc); } },
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
      { label: 'Smoothing Models', submenu: () => SMOOTH.map(([k, label]) => ({ label: `${label}…`, action: withS((S) => smoothDialog(ctx, col, S, k)) })) },
      { label: 'State Space Smoothing Models…', action: withS((S) => etsDialog(ctx, col, S)) },
      { label: 'Structural Model…', action: withS((S) => structuralDialog(ctx, col, S)) },
      { label: 'Regime Switching…', action: withS((S) => regimeDialog(ctx, col, S)) },
      { label: 'Theta Model…', action: withS((S) => thetaDialog(ctx, col, S)) },
      { label: 'ARDL…', disabled: !hasInputs, action: withS((S) => ardlDialog(ctx, col, S)) },
      { separator: true },
      { label: 'Combine and Save Forecasts from Models', disabled: !o('models', []).length, action: withS(async (S) => {
        const list = o('models', []);
        const base = basePayload(ctx, col);
        const results = (await Promise.all(list.map((spec) => fitCall(ctx, base, spec, horizon(ctx)).catch((e) => ({ error: e.message }))))).map((r, i) => withOwnBand(list[i], r));
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
      lead: 'One series in time order: its graph, autocorrelations and stationarity tests; differencing, decomposition and filters; the spectral density and the seasonal subseries plot; and ARIMA, seasonal ARIMA, transfer function, smoothing and state space smoothing models with forecasts, compared in one table. Beyond JMP: structural models, regime switching, the Theta model, ARDL models with the bounds test, and the Zivot-Andrews test.',
      sections: [
        { heading: 'Roles', choices: [['Y, Time Series', 'The series, one report each (continuous columns).'], ['Input List', 'Numeric input series for cross correlations, transfer functions, structural and ARDL models; indicators such as a promotion flag work.'], ['X, Time ID', 'Orders the rows and labels the time axis; a date column gives the calendar frequency, the seasonal period and the forecast dates.'], ['By', 'A report for each level.']] },
        { heading: 'Options', choices: [['Forecast Periods', 'How many periods each model forecasts (default 25).'], ['Autocorrelation Lags', 'How many lags the correlations go to (default 25; n/4 is a common choice).'], ['Seasonal Period', 'The default observations per period in the dialogs; empty takes it from the Time ID (12 for monthly data).']] },
        { heading: 'Missing and excluded rows', text: 'Excluded rows count as missing values, as in JMP, so the spacing of the series is kept; dates missing from a regular calendar are inserted as missing too. ARIMA models skip missing values in the likelihood; the smoothing and decomposition methods fill them by interpolation, and say so.' },
        { heading: 'Differences from JMP', list: ['ARIMA: statsmodels\' exact likelihood; AIC and SBC count the parameters as JMP does (statsmodels also counts σ², shown in the notes). MA coefficients have statsmodels\' sign, the opposite of JMP\'s.', 'Smoothing models: weights and starting states by least squares (holtwinters), not JMP\'s ARIMA-equivalent fit; prediction intervals from the same moving-average weights JMP uses.', 'ADF lags by AIC; KPSS, STL and state space model selection by AICc are additions. X-11 is not available.'] },
        { heading: 'Beyond JMP', choices: [['Structural Model…', 'Level, trend, seasonal, cycle and AR parts with their smoothed components (UnobservedComponents).'], ['Regime Switching…', 'Markov switching means, variances and AR parts, with regime probabilities.'], ['Filters', 'Hodrick-Prescott, Baxter-King and Christiano-Fitzgerald trend and cycle.'], ['Seasonal Subseries Plot', 'Each season\'s values over the years with their mean.'], ['Theta Model…', 'The theta method\'s forecasts.'], ['ARDL…', 'Distributed lags of the inputs, the long run and the bounds test for cointegration.'], ['Zivot-Andrews Test', 'A unit root test that allows one break, with its date, in Stationarity Tests.']] },
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
    about: 'One series in time order: its graph with the ADF tests, autocorrelations with Ljung-Box, partial autocorrelations, variogram, KPSS and the Zivot-Andrews test with its break date; differencing, linear trend and cycle removal, seasonal decomposition and STL, the Hodrick-Prescott, Baxter-King and Christiano-Fitzgerald filters; the spectral density with the white noise tests; lag plots, seasonal subseries plots and cross correlations; ARIMA, seasonal ARIMA and ARIMA model groups, transfer functions (ARIMAX), the smoothing models and state space smoothing (ETS), and, beyond JMP, structural (unobserved components) models with their smoothed components, Markov regime-switching models with regime probabilities, the Theta model, and ARDL models with the long-run coefficients and the Pesaran-Shin-Smith bounds test; each with forecasts that continue the dates, compared in one table.',
    uses: ['statsmodels.tsa.stattools.acf, pacf, adfuller, kpss, ccf, levinson_durbin, zivot_andrews', 'statsmodels.stats.diagnostic.acorr_ljungbox', 'statsmodels.tsa.arima.model.ARIMA',
      'statsmodels.tsa.holtwinters.ExponentialSmoothing', 'statsmodels.tsa.exponential_smoothing.ets.ETSModel', 'statsmodels.tsa.seasonal.seasonal_decompose, STL',
      'statsmodels.tsa.statespace.structural.UnobservedComponents', 'statsmodels.tsa.regime_switching.markov_regression.MarkovRegression, markov_autoregression.MarkovAutoregression',
      'statsmodels.tsa.filters.hp_filter.hpfilter, bk_filter.bkfilter, cf_filter.cffilter', 'statsmodels.graphics.tsaplots.month_plot, quarter_plot, seasonal_plot (their data)',
      'statsmodels.tsa.forecasting.theta.ThetaModel', 'statsmodels.tsa.ardl.ARDL, UECM, ardl_select_order, pss_critical_values',
      'statsmodels.tsa.statespace.tools.diff', 'statsmodels.regression.linear_model.OLS', 'pandas.infer_freq', 'numpy.fft'],
    launch: {
      lead: 'Choose the series. A date column as X, Time ID gives a date axis, the seasonal period and the dates of the forecasts; Input List columns are the inputs of transfer functions, structural and ARDL models.',
      roles: [
        { key: 'y', label: 'Y, Time Series', min: 1, types: ['continuous'], hint: 'required: one or more continuous' },
        { key: 'inputs', label: 'Input List', numeric: true, hint: 'optional numeric: inputs of transfer functions, structural and ARDL models' },
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
  SM.timeseries = Object.freeze({ groupRows, barSvg, parseRange, effective, specName, perYear, filterDefaults, parseOrders, fitKey, regimeColor });
}(typeof self !== 'undefined' ? self : this));
