/* ==========================================================================
   SMUI.HTML: ANALYZE > SPECIALIZED MODELING > MULTIVARIATE TIME SERIES

   Vector autoregressions and cointegration on statsmodels.tsa.vector_ar,
   which JMP does not have, laid out as JMP lays out its Time Series
   platform. One report per By group: the series on one time axis (or as
   small multiples) with their stationarity tests; the Lag Order Selection
   table (AIC, BIC, FPE, HQIC) whose chosen lag fits the VAR(p): Model
   Summary, Parameter Estimates by equation, residual correlations,
   stability, whiteness and normality; Granger causality as a matrix of
   p-values; impulse responses as a grid of graphs with their bands; the
   forecast error variance decomposition; forecasts that continue the dates;
   and from the red triangle the cointegration part: Johansen's test, the
   VECM of the chosen rank and the Engle-Granger test.

   The series are read as the Time Series platform reads one: in time
   order, excluded rows as missing values in their place, dates missing
   from the calendar inserted (resources/py/smui/multits.py fills them by
   interpolation, because a VAR needs every time point, and says so).

   Options are the report's own, not per column: every part works on all
   the series. The Cholesky ordering is stored as column ids, which a saved
   project maps back.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt, PALETTE } = SM.util;

  const MORE = { label: 'Multivariate Time Series', id: 'help-p-multits' };
  const DATE_KINDS = new Set(['date', 'datetime']);
  const CRITERIA = [['aic', 'AIC'], ['bic', 'BIC'], ['fpe', 'FPE'], ['hqic', 'HQIC']];   // statsmodels' order
  const CRIT_LABEL = Object.fromEntries(CRITERIA);
  const TRENDS = [['c', 'Constant'], ['ct', 'Constant and Linear Trend'], ['n', 'None']];
  const TREND_LABEL = Object.fromEntries(TRENDS);
  const DETS = [['n', 'None'], ['co', 'Constant (unrestricted)'], ['ci', 'Constant in the cointegrating relation'],
    ['colo', 'Constant and linear trend (unrestricted)'], ['cili', 'Constant, linear trend in the cointegrating relation']];
  const DET_ORDERS = [['-1', 'None'], ['0', 'Constant (unrestricted)'], ['1', 'Constant and linear trend (unrestricted)']];
  const DET_FOR = { '-1': 'n', 0: 'co', 1: 'colo' };
  const BAND = [['asym', 'Asymptotic'], ['mc', 'Monte Carlo'], ['none', 'None']];

  const int = (v, d = 0) => (v == null || v === '' || !Number.isFinite(Number(v)) ? d : Math.round(Number(v)));
  const colorOf = (i) => PALETTE[((i % PALETTE.length) + PALETTE.length) % PALETTE.length];
  const dark = () => SM.util.themeColors().dark;
  /* The response lines and the eigenvalues: the report's blue, lighter on the dark theme. */
  const lineColor = () => (dark() ? '#7fa6cf' : SM.report.BASE);
  /* Text from the table inside Plotly: its little HTML escaped, and %{ kept out of hover templates. */
  const esc = (s) => SM.report.plotlyText(s).replace(/%\{/g, '%\u200b{');
  const nan = (a) => (a || []).map((v) => (v == null ? NaN : v));
  function rgba(hex, a) {
    const h = hex.replace('#', '');
    return `rgba(${parseInt(h.slice(0, 2), 16)}, ${parseInt(h.slice(2, 4), 16)}, ${parseInt(h.slice(4, 6), 16)}, ${a})`;
  }
  const divergingScale = () => (dark() ? [[0, '#5b9cf0'], [0.5, '#3a3431'], [1, '#e8604f']] : [[0, '#2f6ec7'], [0.5, '#f6f3f0'], [1, '#c0392b']]);
  /* p-values: red below α, the deeper the smaller; neutral just above α, pale
     blue toward 1. A linear scale would paint p = 0.06 almost as red as 0. */
  function pScale(alpha) {
    const a = Math.min(0.5, Math.max(1e-4, alpha));
    return dark() ? [[0, '#e8604f'], [a / 10, '#d4594a'], [a, '#9a4c41'], [a + 1e-6, '#3a3431'], [1, '#3f5f8c']]
      : [[0, '#c0392b'], [a / 10, '#cf5747'], [a, '#ebb3a6'], [a + 1e-6, '#f6f3f0'], [1, '#bccfe6']];
  }

  /* ---- the options ---------------------------------------------------------- */
  const maxLags = (ctx) => Math.max(1, Math.min(48, int(ctx.opt('maxlags', 8), 8)));
  const horizon = (ctx) => Math.max(1, Math.min(100, int(ctx.opt('horizon', 10), 10)));
  const periods = (ctx) => Math.max(1, Math.min(500, int(ctx.opt('forecast', 12), 12)));
  const replOf = (ctx) => Math.max(50, Math.min(10000, int(ctx.opt('mcRepl', 1000), 1000)));
  const trendOf = (ctx) => { const t = ctx.opt('trend', 'c'); return TREND_LABEL[t] ? t : 'c'; };
  const lagBy = (ctx) => { const b = ctx.opt('lagBy', 'aic'); return CRIT_LABEL[b] ? b : 'aic'; };

  /* The Cholesky ordering as names, when it is a reordering of Y (null otherwise). */
  function orderNames(ctx) {
    const ids = ctx.opt('order', null);
    const ys = ctx.roles('y');
    if (!Array.isArray(ids) || ids.length !== ys.length) return null;
    const names = ids.map((id) => { const c = ctx.col(id); return c ? c.name : null; });
    const set = new Set(ys.map((c) => c.name));
    if (names.some((n) => !n || !set.has(n)) || new Set(names).size !== names.length) return null;
    return names.every((n, i) => n === ys[i].name) ? null : names;
  }

  /* All the rows of this report's By group, excluded ones too: they go to
     Python as missing values, so that the spacing of the series is kept, as
     the Time Series platform sends them. The Local Data Filter still drops
     rows. */
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

  function basePayload(ctx) {
    const { rows, excluded } = groupRows(ctx);
    return {
      y: ctx.names('y'), time: ctx.name('time'), exog: ctx.names('exog'), rows, excluded,
      log: !!ctx.opt('log', false), diff: !!ctx.opt('diff', false),
      where: (ctx.where || []).map((w) => ({ column: w.column, value: w.value })),
    };
  }

  /* ---- the time axis ----------------------------------------------------------
     Dates go to Plotly as ISO text (see the Time Series platform: restyling
     x for row states makes Plotly guess the axis type again). */
  const isDate = (S) => DATE_KINDS.has(S.kind);
  function timeKind(S) { return isDate(S) && (S.t || []).some((v) => v != null && v % 86400000 !== 0) ? 'datetime' : 'date'; }
  const xOf = (S, t) => (isDate(S) ? t.map((v) => (v == null ? null : SM.io.formatDate(v, S.tkind))) : t);
  const tLabel = (S, v) => (isDate(S) ? SM.io.formatDate(v, S.tkind) : fmt(v));
  const xAxis = (S, extra = {}) => ({ title: { text: esc(S.time || 'Row') }, ...(isDate(S) ? { type: 'date' } : {}), ...extra });
  const linked = (rows) => rows.map((r) => (r == null ? -1 : r));

  function plotWidth(ctx, want) {
    const w = ctx.report && ctx.report.body ? ctx.report.body.clientWidth : 0;
    return w > 0 ? Math.max(290, Math.min(want, w - 70)) : want;
  }

  /* Domains of k graphs stacked top to bottom. */
  function stackDomains(k, gap = 0.05) {
    const h = (1 - gap * (k - 1)) / k;
    return Array.from({ length: k }, (_, i) => [Math.max(0, 1 - (i + 1) * h - i * gap), 1 - i * (h + gap)]);
  }
  const axisName = (kind, i) => (i ? `${kind}${i + 1}` : kind);

  /* ---- the series and their stationarity ----------------------------------------- */
  function seriesPart(ctx, S, box) {
    const k = S.names.length;
    const rows = linked(S.rows);
    const x = xOf(S, S.t);
    if (ctx.opt('graph', true)) {
      const multiples = ctx.opt('multiples', false);
      const traces = S.labels.map((lab, i) => ({
        type: S.t.length > 4000 ? 'scattergl' : 'scatter', mode: 'lines+markers', x, y: S.values[i], rows, name: lab, connectgaps: false,
        line: { color: colorOf(i), width: 1.2 }, marker: { size: 4, color: colorOf(i) },
        hovertext: rows.map((r) => (r >= 0 ? `row ${r + 1}` : 'no row')), hovertemplate: `${esc(lab)}<br>%{hovertext}<br>%{x}: %{y:.5g}<extra></extra>`,
        ...(multiples ? { xaxis: 'x', yaxis: axisName('y', i) } : {}),
      }));
      let layout, height;
      if (multiples) {
        height = Math.max(260, 60 + 118 * k);
        layout = { xaxis: xAxis(S, { anchor: `y${k}` }), margin: { l: 64, r: 12, t: 8, b: 40 } };
        stackDomains(k).forEach((d, i) => { layout[`yaxis${i ? i + 1 : ''}`] = { domain: d, title: { text: esc(S.labels[i]), font: { size: 10.5 } } }; });
      } else {
        height = 300;
        layout = { xaxis: xAxis(S), yaxis: { title: { text: S.log || S.diff ? 'Series as analysed' : 'Value' } }, showlegend: true, legend: { orientation: 'h', y: -0.24 } };
      }
      box.add(ctx.plot(traces, layout, { width: plotWidth(ctx, 660), height, title: 'Time Series Graph' }));
    }
    const what = [S.freq_label ? `${S.freq_label[0].toUpperCase()}${S.freq_label.slice(1)} data` : null, `${S.n} time points`,
      S.log && S.diff ? 'the first differences of the logarithms' : S.log ? 'the logarithms' : S.diff ? 'the first differences' : null].filter(Boolean);
    box.add(ctx.note(`${what.join(', ')}.`));
    if (!ctx.opt('stationarity', true)) return;
    const ob = ctx.outline('Stationarity Summary', { parent: box, key: 'stationarity', info: 'p:multits:stationarity', menu: () => [{ label: 'Remove', action: () => ctx.set('stationarity', false) }] });
    const rowsT = S.stationarity.map((r) => ({
      series: r.series, n: r.n, mean: r.mean, sd: r.sd, adf: r.adf, adf_p: r.adf_error ? r.adf_error : r.adf_p, kpss: r.kpss,
      kpss_p: r.kpss_error ? r.kpss_error : r.kpss_bound ? `${r.kpss_bound}${fmt(r.kpss_p)}` : r.kpss_p, verdict: r.verdict,
    }));
    ob.add(ctx.rt({ columns: [{ key: 'series', label: 'Series', fmt: 'text' }, { key: 'n', label: 'N', fmt: 'int' }, { key: 'mean', label: 'Mean' }, { key: 'sd', label: 'Std Dev' },
      { key: 'adf', label: 'ADF τ' }, { key: 'adf_p', label: 'ADF Prob', fmt: 'p' }, { key: 'kpss', label: 'KPSS' }, { key: 'kpss_p', label: 'KPSS Prob', fmt: 'p' },
      { key: 'verdict', label: 'Reading', fmt: 'text' }], rows: rowsT }, { sortable: false, name: 'Stationarity Summary' }));
    const det = S.trend === 'ct' ? 'a constant and a trend' : S.trend === 'n' ? 'no constant' : 'a constant';
    ob.add(ctx.note(`ADF (adfuller, lags by AIC) tests a unit root: a small p-value speaks for stationarity. KPSS (kpss) tests the opposite null, stationarity: a small p-value speaks against it; its p-value is interpolated between 0.01 and 0.1 and shown as a bound outside. Both with ${det}, as the VAR's trend.`));
    const bad = S.stationarity.filter((r) => r.verdict === 'unit root: difference').map((r) => r.series);
    if (bad.length && !S.diff) ob.add(ctx.warn(`${bad.join(', ')} ${bad.length === 1 ? 'looks' : 'look'} nonstationary: a VAR in levels is then a spurious regression. Consider Transform > Difference (d = 1) in the red triangle, or, if the series move together, the Cointegration part (a VECM).`));
    else if (bad.length) ob.add(ctx.warn(`${bad.join(', ')} still ${bad.length === 1 ? 'looks' : 'look'} nonstationary after differencing.`));
  }

  /* ---- Lag Order Selection -------------------------------------------------------------- */
  function lagItems(ctx) {
    const fixed = ctx.opt('lagFixed', null);
    return [
      ...CRITERIA.map(([k, lab]) => ({ label: lab, checked: !fixed && lagBy(ctx) === k, action: () => { ctx.set('lagFixed', null, null, { rerun: false }); ctx.set('lagBy', k); } })),
      { separator: true },
      { label: 'Fixed Lag Order…', checked: !!fixed, action: async () => {
        const v = await SM.ui.form({ title: 'Fixed Lag Order', info: 'p:multits:lags', fields: [{ key: 'p', label: 'Lag order p of the VAR (empty: by the criterion)', type: 'number', value: fixed, helpLabel: 'Lag order p',
          help: 'The lag of the VAR, 1 to 48, in place of the one the criterion chooses; every part of the report after Lag Order Selection uses it. Empty goes back to the criterion. A click on a line of the selection table fixes that lag too.' }], validate: (x) => (x.p == null || (Number.isInteger(x.p) && x.p >= 1 && x.p <= 48) ? null : 'a whole number from 1 to 48, or empty') });
        if (v) ctx.set('lagFixed', v.p || null);
      } },
    ];
  }

  /* What the number each red-triangle item asks for does: its dialog's (i). */
  const ASK_HELP = {
    maxlags: 'The largest lag of the Lag Order Selection table, 1 to 48: VARs of every lag from 0 (1 with neither a trend nor an exogenous column) up to it are fitted on the same observations, those after it, and the criterion picks one. A larger maximum leaves out more observations at the start.',
    wLags: 'The lags h the Portmanteau test looks at, from p + 1 to 200 (at first the larger of 10 and p + 4): its χ² has k²(h − p) degrees of freedom. A larger h looks for dynamics further back, at some cost in power for the near ones.',
    mcRepl: 'How many times the fitted VAR is simulated and refitted for Monte Carlo bands, 50 to 10 000 (1000 by default); used when Confidence Bands is Monte Carlo. More give steadier band edges, and take longer.',
    horizon: 'How many periods after a shock the impulse responses run, and how many steps ahead the variance decomposition goes: 1 to 100 (10 by default), one setting for both.',
    forecast: 'How many periods after the last observation the VAR forecasts, and the VECM too: 1 to 500 (12 by default).',
    rank: 'The number of cointegrating relations of the VECM, 1 to k − 1 for k series, in place of the rank the Johansen test chose; Rank from the Test (the red triangle) goes back to the test\'s.',
  };

  async function askNumber(ctx, { title, label, key, value, min, max, info, help = ASK_HELP[key] }) {
    const v = await SM.ui.form({ title, info, fields: [{ key: 'n', label, type: 'number', value, help }], validate: (x) => (Number.isInteger(x.n) && x.n >= min && x.n <= max ? null : `a whole number from ${min} to ${max}`) });
    if (v) ctx.set(key, v.n);
  }

  function lagMenu(ctx) {
    return [
      { label: 'Choose Lag By', submenu: () => lagItems(ctx) },
      { label: 'Maximum Lag…', action: () => askNumber(ctx, { title: 'Maximum Lag', label: 'Largest lag in the selection table', key: 'maxlags', value: maxLags(ctx), min: 1, max: 48, info: 'p:multits:lags' }) },
      { label: 'Trend', submenu: () => TRENDS.map(([k, lab]) => ({ label: lab, checked: trendOf(ctx) === k, action: () => ctx.set('trend', k) })) },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('lagsel', false) },
    ];
  }

  async function lagPart(ctx, base, box) {
    const fixed = int(ctx.opt('lagFixed', null), 0) || null;
    const by = lagBy(ctx);
    const L = await ctx.call('multits.select_order', { ...base, maxlags: maxLags(ctx), trend: trendOf(ctx) });
    let p = fixed;
    const notes = [];
    if (L.error && !fixed) { box.add(ctx.warn(`Lag Order Selection: ${L.error}`)); return null; }
    if (!fixed) {
      p = L.selected[by];
      if (p < 1) { notes.push(`${CRIT_LABEL[by]} is smallest at lag 0: the series look like white noise to it. The report fits a VAR(1); fix another lag in the red triangle.`); p = 1; }
    }
    if (ctx.opt('lagsel', true)) {
      const ob = ctx.outline('Lag Order Selection', { parent: box, key: 'lags', info: 'p:multits:lags', menu: () => lagMenu(ctx) });
      if (L.error) ob.add(ctx.warn(L.error));
      else {
        const tbl = ctx.rt({ columns: [{ key: 'lag', label: 'Lag', fmt: 'int' }, ...CRITERIA.map(([k, lab]) => ({ key: k, label: lab }))], rows: L.rows },
          { sortable: false, name: 'Lag Order Selection', className: 'mts-lags', onRow: (row) => { if (row.lag >= 1) ctx.set('lagFixed', row.lag); } });
        tbl.querySelectorAll('tbody tr').forEach((tr, i) => {
          const r = L.rows[i];
          if (!r) return;
          CRITERIA.forEach(([k], j) => { if (L.selected[k] === r.lag) { tr.children[j + 1].classList.add('mts-min'); tr.children[j + 1].title = `the smallest ${CRIT_LABEL[k]}`; } });
          if (r.lag === p) tr.classList.add('mts-chosen');
        });
        ob.add(ctx.row(tbl, ctx.kv([['Lag Order Used', p, 'int'], ['Chosen By', fixed ? 'fixed' : CRIT_LABEL[by], 'text'], ['Maximum Lag', L.maxlags, 'int'], ['Observations Used', L.nobs, 'int'], ['Trend', TREND_LABEL[L.trend], 'text']])));
        ob.add(ctx.note(`Every lag from ${L.rows.length ? L.rows[0].lag : 0} to ${L.maxlags} is fitted on the same ${L.nobs} observations, so the criteria compare (statsmodels' select_order${L.rows.length && L.rows[0].lag ? '; with no trend a VAR(0) has nothing to fit' : ''}); * marks the smallest of each. The lag chosen by ${fixed ? 'you' : CRIT_LABEL[by]} fits the VAR below: pick the criterion in the red triangle, or click a line to fix that lag.`));
        for (const n of [...(L.notes || []), ...notes]) ob.add(ctx.note(n));
        ob.add(ctx.code(L.code));
      }
    } else for (const n of notes) box.add(ctx.note(n));
    return p;
  }

  /* ---- the VAR(p) --------------------------------------------------------------------- */
  const PE_COLS = [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 't Ratio' },
    { key: 'p', label: 'Prob>|t|', fmt: 'p' }, { key: 'sm', label: 'statsmodels', fmt: 'text', hidden: true }];

  function varPayload(ctx, base, p) {
    return { ...base, p, trend: trendOf(ctx), alpha: ctx.alpha, whiteness_lags: ctx.opt('wLags', null), adjusted: !!ctx.opt('wAdjusted', false) };
  }

  function varMenu(ctx, base, p) {
    return [
      ctx.check('Residual Correlation', 'residCorr', null, true),
      ctx.check('Stability', 'stability', null, true),
      ctx.check('Whiteness Test', 'whiteness', null, true),
      ctx.check('Normality Test', 'normality', null, true),
      { label: 'Whiteness Test Lags…', action: () => askNumber(ctx, { title: 'Whiteness Test Lags', label: 'Residual autocorrelations up to lag h (more than p)', key: 'wLags', value: ctx.opt('wLags', null) || Math.max(10, p + 4), min: p + 1, max: 200, info: 'p:multits:diagnostics' }) },
      ctx.check('Adjusted Portmanteau (small-sample)', 'wAdjusted', null, false),
      { separator: true },
      { label: 'Save Residuals', action: () => saveResiduals(ctx, base, p) },
    ];
  }

  async function varPart(ctx, base, p, box) {
    const V = await ctx.call('multits.var', varPayload(ctx, base, p));
    const ob = ctx.outline(`Vector Autoregression VAR(${p})`, { parent: box, key: 'var', info: 'p:multits:var', menu: () => varMenu(ctx, base, p) });
    if (V.error) { ob.add(ctx.warn(V.error)); return null; }
    const S = V.summary;
    const sum = ctx.outline('Model Summary', { parent: ob, key: 'var:sum' });
    sum.add(ctx.kv([['Lag Order (p)', V.p, 'int'], ['Trend', V.trend_label, 'text'], ['Equations', V.k, 'int'], ['Exogenous', V.exog.length ? V.exog.join(', ') : 'none', 'text'],
      ['Observations Used', V.nobs, 'int'], ['Coefficients per Equation', V.per_eq, 'int'], ['Log Likelihood', S.llf], ['AIC', S.aic], ['BIC', S.bic], ['HQIC', S.hqic], ['FPE', S.fpe], ['det Ω (ML)', S.detomega]]));
    const pe = ctx.outline('Parameter Estimates', { parent: ob, key: 'var:pe' });
    V.equations.forEach((e, i) => {
      const eo = ctx.outline(`Equation ${e.label}`, { parent: pe, key: `var:eq:${e.name}`, closed: i > 0 });
      eo.add(ctx.rt({ columns: PE_COLS, rows: e.rows }, { sortable: false, name: `${e.name} equation`, key: `var-equation:${e.name}` }));
    });
    pe.add(ctx.note(`Least squares, equation by equation (statsmodels' VAR). The standard errors use the residual covariance with ${V.df_resid} degrees of freedom (n − ${V.per_eq}); the p-values are from the normal distribution, as statsmodels gives them. ${V.names[0]}(t−1) is ${V.names[0]} one period before. Right click a table for the statsmodels names.`));
    ob.add(ctx.row(sum.el, pe.el));
    ob.add(ctx.note('AIC, BIC and HQIC are Lütkepohl\'s, per observation: ln det Ω + penalty/n (statsmodels); they rank lags of the same data, and are not the Time Series platform\'s −2 log L + 2k.'));
    if (ctx.opt('residCorr', true)) residCorr(ctx, V, ob);
    if (ctx.opt('stability', true)) stability(ctx, V, ob);
    if (ctx.opt('whiteness', true)) {
      const w = V.whiteness;
      const wo = ctx.outline('Whiteness Test (Portmanteau)', { parent: ob, key: 'var:white', info: 'p:multits:diagnostics' });
      if (w.error) wo.add(ctx.warn(`Portmanteau test up to lag ${w.nlags}: ${w.error}`));
      else {
        wo.add(ctx.kv([['Lags (h)', w.nlags, 'int'], ['ChiSquare', w.stat], ['DF', w.df, 'int'], [`Critical Value (${fmt(ctx.alpha)})`, w.crit], ['Prob > ChiSq', w.p, 'p']]),
          ctx.note(`H0: no residual autocorrelation up to lag ${w.nlags}; χ² with k²(h − p) degrees of freedom${w.adjusted ? ', the small-sample adjusted statistic' : ''} (test_whiteness). A small p-value says the VAR leaves dynamics in the residuals: try more lags.`));
      }
    }
    if (ctx.opt('normality', true)) {
      const nt = V.normality;
      const no = ctx.outline('Normality Test (Jarque-Bera)', { parent: ob, key: 'var:norm', info: 'p:multits:diagnostics' });
      if (nt.error) no.add(ctx.warn(nt.error));
      else no.add(ctx.kv([['ChiSquare', nt.stat], ['DF', nt.df, 'int'], [`Critical Value (${fmt(ctx.alpha)})`, nt.crit], ['Prob > ChiSq', nt.p, 'p']]),
        ctx.note('H0: the orthogonalized residuals have the skewness and kurtosis of a normal distribution (test_normality, Lütkepohl\'s multivariate Jarque-Bera, 2k degrees of freedom). The forecast intervals assume normal errors.'));
    }
    ob.add(ctx.code(V.code));
    return V;
  }

  function heatmap(ctx, z, labels, { zmin, zmax, scale, text, title, height, rowLabels = null }) {
    const rl = rowLabels || labels;
    const sz = Math.max(220, Math.min(560, 70 + 58 * labels.length));
    return ctx.plot([{ type: 'heatmap', z, x: labels.map(esc), y: rl.map(esc), zmin, zmax, colorscale: scale, text, texttemplate: labels.length <= 10 ? '%{text}' : '', hovertemplate: '%{y} × %{x}: %{text}<extra></extra>', xgap: 2, ygap: 2, colorbar: { thickness: 10, len: 0.85 } }],
      { xaxis: { type: 'category', side: 'bottom', showgrid: false, showline: false, ticks: '', tickangle: labels.length > 4 ? -35 : 0 }, yaxis: { type: 'category', autorange: 'reversed', showgrid: false, showline: false, ticks: '' }, margin: { l: 40, r: 10, t: 8, b: 30 } },
      { width: plotWidth(ctx, sz + 90), height: height || Math.max(200, sz - 20 + 26 * (rl.length - labels.length)), title, select: false });
  }

  function residCorr(ctx, V, parent) {
    const ob = ctx.outline('Residual Correlation', { parent, key: 'var:corr', info: 'p:multits:diagnostics' });
    const labs = V.labels;
    const text = V.resid_corr.map((row) => row.map((v) => (v == null ? '' : v.toFixed(3).replace('-', '−'))));
    const rows = V.names.map((n, i) => ({ variable: labs[i], ...Object.fromEntries(V.names.map((m, j) => [`c${j}`, V.resid_corr[i][j]])), sd: V.resid_sd[i] }));
    ob.add(ctx.row(heatmap(ctx, V.resid_corr, labs, { zmin: -1, zmax: 1, scale: divergingScale(), text, title: 'Residual correlation colour map' }),
      ctx.rt({ columns: [{ key: 'variable', label: '', fmt: 'text' }, ...labs.map((l, j) => ({ key: `c${j}`, label: l, digits: 4 })), { key: 'sd', label: 'Residual Std Dev' }], rows }, { sortable: false, name: 'Residual correlation' })),
    ctx.note('Correlations of the residuals of the equations (res.resid_corr), red for +1 and blue for −1. Large ones mean shocks hit the series together: the orthogonalized impulse responses then depend on the ordering, and Instantaneous Causality tests them.'));
  }

  function stability(ctx, V, parent) {
    const st = V.stability;
    const ob = ctx.outline('Stability', { parent, key: 'var:stab', info: 'p:multits:diagnostics' });
    const tc = SM.util.themeColors();
    const th = Array.from({ length: 121 }, (_, i) => (2 * Math.PI * i) / 120);
    const ev = st.eigenvalues;
    const traces = [
      { type: 'scatter', mode: 'lines', x: th.map(Math.cos), y: th.map(Math.sin), line: { color: tc.muted, width: 1 }, hoverinfo: 'skip', name: 'unit circle' },
      { type: 'scatter', mode: 'markers', x: ev.map((e) => e.real), y: ev.map((e) => e.imag), name: 'eigenvalues',
        marker: { size: 8, color: ev.map((e) => (e.modulus < 1 ? lineColor() : '#c0392b')), line: { color: tc.surface, width: 1 } },
        text: ev.map((e) => `${fmt(e.real)} ${e.imag < 0 ? '−' : '+'} ${fmt(Math.abs(e.imag))}i, modulus ${fmt(e.modulus)}`), hovertemplate: '%{text}<extra></extra>' },
    ];
    const lim = Math.max(1.15, ...ev.map((e) => e.modulus + 0.1));
    const plot = ctx.plot(traces, { xaxis: { title: { text: 'Real' }, range: [-lim, lim], zeroline: true }, yaxis: { title: { text: 'Imaginary' }, range: [-lim, lim], scaleanchor: 'x', zeroline: true }, margin: { l: 50, r: 10, t: 8, b: 40 } },
      { width: 280, height: 270, title: 'Companion matrix eigenvalues', select: false });
    const tbl = ctx.rt({ columns: [{ key: 'i', label: '#', fmt: 'int' }, { key: 'real', label: 'Real' }, { key: 'imag', label: 'Imaginary' }, { key: 'modulus', label: 'Modulus' }, { key: 'period', label: 'Period' }],
      rows: ev.map((e, i) => ({ i: i + 1, ...e })) }, { sortable: false, maxRows: 24, name: 'Companion eigenvalues' });
    ob.add(ctx.kv([['Stable', st.stable ? 'Yes' : 'No', 'text'], ['Largest Modulus', st.max_modulus], ['Eigenvalues', ev.length, 'int']]),
      ctx.row(plot, tbl),
      st.stable ? ctx.note('Every eigenvalue of the companion matrix lies inside the unit circle: the VAR is stable (statsmodels\' is_stable: the roots of det(I − A₁z − … − Aₚzᵖ) lie outside it). A complex pair gives a cycle of the period shown, in time points.')
        : ctx.warn('An eigenvalue lies on or outside the unit circle: the VAR is not stable, and its impulse responses and forecasts explode. Difference the series, or fit a VECM (Cointegration).'));
  }

  async function saveResiduals(ctx, base, p) {
    const V = await ctx.call('multits.var', varPayload(ctx, base, p));
    if (V.error) { SM.ui.toast(V.error, { error: true }); return; }
    V.names.forEach((n, i) => {
      const rows = [], values = [];
      V.resid.rows.forEach((r, k) => { if (r != null) { rows.push(r); values.push(V.resid.values[i][k] == null ? NaN : V.resid.values[i][k]); } });
      ctx.saveColumn(`Residual ${V.labels[i]}`, { rows, values }, { notes: `residuals of the ${V.labels[i]} equation of the VAR(${V.p}), saved from ${ctx.report.title}` });
    });
  }

  /* ---- Granger causality ------------------------------------------------------------------ */
  async function grangerPart(ctx, base, p, box) {
    const kind = ctx.opt('grangerKind', 'f') === 'wald' ? 'wald' : 'f';
    const G = await ctx.call('multits.granger', { ...base, p, trend: trendOf(ctx), kind, alpha: ctx.alpha });
    const ob = ctx.outline('Granger Causality', { parent: box, key: 'granger', info: 'p:multits:granger', menu: () => [
      { label: 'F Test', checked: kind === 'f', action: () => ctx.set('grangerKind', 'f') },
      { label: 'Wald ChiSquare Test', checked: kind === 'wald', action: () => ctx.set('grangerKind', 'wald') },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('granger', false) },
    ] });
    if (G.error) { ob.add(ctx.warn(G.error)); return; }
    const names = G.names;
    const rowNames = G.others.length ? [...names, 'all the others'] : names;
    const z = G.others.length ? [...G.matrix, names.map((_, j) => G.others[j])] : G.matrix;
    const text = z.map((row) => row.map((v) => (v == null ? '' : SM.util.fmtP(v, ctx.alpha))));
    const stat = kind === 'f' ? 'F Ratio' : 'ChiSquare';
    const tests = G.tests;
    const cols = [{ key: 'causing', label: 'Causing', fmt: 'text' }, { key: 'caused', label: 'Caused', fmt: 'text' }, { key: 'stat', label: stat }, { key: 'df', label: kind === 'f' ? 'DF Num' : 'DF', fmt: 'int' }];
    if (kind === 'f') cols.push({ key: 'df_den', label: 'DF Den', fmt: 'int' });
    cols.push({ key: 'crit', label: `Critical Value (${fmt(ctx.alpha)})` }, { key: 'p', label: kind === 'f' ? 'Prob > F' : 'Prob > ChiSq', fmt: 'p' });
    ob.add(ctx.row(heatmap(ctx, z, names, { zmin: 0, zmax: 1, scale: pScale(ctx.alpha), text, title: 'Granger causality p-values', rowLabels: rowNames }),
      ctx.rt({ columns: cols, rows: tests }, { sortable: true, name: 'Granger causality tests', maxRows: 60 })));
    ob.add(ctx.note(`Row causes column: each cell tests H0 "the row's lags add nothing to the column's equation" (test_causality, ${kind === 'f' ? 'an F test' : 'a Wald χ² test'} of the ${p} lag coefficients${G.others.length ? '; the last row tests all the other series together' : ''}). Red is a p-value below α: the row helps to forecast the column. It is predictive causality in this VAR, not cause and effect.`));
    const io = ctx.outline('Instantaneous Causality', { parent: ob, key: 'granger:inst', info: 'p:multits:granger' });
    io.add(ctx.rt({ columns: [{ key: 'variable', label: 'Series', fmt: 'text' }, { key: 'stat', label: 'Wald ChiSquare' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'crit', label: `Critical Value (${fmt(ctx.alpha)})` }, { key: 'p', label: 'Prob > ChiSq', fmt: 'p' }], rows: G.inst }, { sortable: false, name: 'Instantaneous causality' }),
      ctx.note('H0: the series\' residual is uncorrelated with the other residuals (test_inst_causality): a shock to it does not come with shocks to the others in the same period. A small p-value means the ordering of an orthogonalized impulse response matters.'));
    ob.add(ctx.code(G.code));
  }

  /* ---- impulse responses ------------------------------------------------------------------------ */
  function gridCells(nr, nc, { gapX = 0.07, gapY = 0.1 } = {}) {
    const w = (1 - gapX * (nc - 1)) / nc, h = (1 - gapY * (nr - 1)) / nr;
    const cells = [];
    for (let i = 0; i < nr; i++) for (let j = 0; j < nc; j++) {
      const n = i * nc + j;
      const x0 = j * (w + gapX), y1 = 1 - i * (h + gapY);
      cells.push({ i, j, n, xa: axisName('x', n), ya: axisName('y', n), xd: [x0, Math.min(1, x0 + w)], yd: [Math.max(0, y1 - h), y1] });
    }
    return cells;
  }

  async function orderDialog(ctx) {
    const ys = ctx.roles('y');
    const cur = orderNames(ctx) || ys.map((c) => c.name);
    const ords = ['1st', '2nd', '3rd'];
    const v = await SM.ui.form({
      title: 'Cholesky Ordering', info: 'p:multits:irf',
      lead: 'The order of the series in the Cholesky factor of the residual covariance, for the orthogonalized impulse responses and the variance decomposition: a series responds at once to shocks of the series before it, never to those after it. Put the most exogenous first.',
      fields: cur.map((n, i) => ({ key: `o${i}`, label: `${ords[i] || `${i + 1}th`}`, type: 'select', value: n, choices: ys.map((c) => [c.name, c.name]), helpLabel: '1st, 2nd, …',
        help: 'The series at that place in the ordering, each series once. A shock to a series moves the series after it in the same period, never those before it: put first the series least moved by the others within a period. It starts at the order of Y.' })),
      validate: (x) => (new Set(cur.map((_, i) => x[`o${i}`])).size === cur.length ? null : 'each series once'),
    });
    if (!v) return;
    const ids = cur.map((_, i) => ys.find((c) => c.name === v[`o${i}`]).id);
    ctx.set('order', ids.every((id, i) => id === ys[i].id) ? null : ids);
  }

  function irfMenu(ctx) {
    const bands = ctx.opt('irfBands', 'asym');
    return [
      ctx.check('Orthogonalized (Cholesky)', 'irfOrth', null, true),
      ctx.check('Cumulative', 'irfCum', null, false),
      { label: 'Confidence Bands', submenu: () => BAND.map(([k, lab]) => ({ label: lab, checked: bands === k, action: () => ctx.set('irfBands', k) })) },
      { label: 'Monte Carlo Replications…', action: () => askNumber(ctx, { title: 'Monte Carlo Replications', label: 'Simulated samples for the Monte Carlo bands', key: 'mcRepl', value: replOf(ctx), min: 50, max: 10000, info: 'p:multits:irf' }) },
      { label: 'Cholesky Ordering…', action: () => orderDialog(ctx) },
      { label: 'Horizon…', action: () => askNumber(ctx, { title: 'Impulse Response Horizon', label: 'Periods after the shock', key: 'horizon', value: horizon(ctx), min: 1, max: 100, info: 'p:multits:irf' }) },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('irf', false) },
    ];
  }

  async function irfPart(ctx, base, p, box) {
    const orth = !!ctx.opt('irfOrth', true), cum = !!ctx.opt('irfCum', false);
    const bands = BAND.some(([k]) => k === ctx.opt('irfBands', 'asym')) ? ctx.opt('irfBands', 'asym') : 'asym';
    const I = await ctx.call('multits.irf', { ...base, p, trend: trendOf(ctx), horizon: horizon(ctx), orth, cumulative: cum, bands, repl: replOf(ctx), alpha: ctx.alpha, order: orderNames(ctx) });
    const ob = ctx.outline('Impulse Response', { parent: box, key: 'irf', info: 'p:multits:irf', menu: () => irfMenu(ctx) });
    if (I.error) { ob.add(ctx.warn(I.error)); return; }
    const k = I.names.length, H = I.horizon;
    const hs = Array.from({ length: H + 1 }, (_, h) => h);
    // Narrow cells (a phone) get their titles on two lines, in a smaller font.
    const cw = Math.max(96, Math.min(210, Math.floor((plotWidth(ctx, 60 + 210 * k) - 60) / k)));
    const narrow = cw < 150;
    const cells = gridCells(k, k, narrow ? { gapX: 0.08, gapY: 0.2 } : {});
    const tc = SM.util.themeColors();
    const lc = lineColor();
    const traces = [], layout = { margin: { l: 44, r: 10, t: narrow ? 32 : 22, b: 36 }, annotations: [], shapes: [] };
    for (const c of cells) {
      const resp = c.i, imp = c.j;
      const y = hs.map((h) => I.values[h][resp][imp]);
      if (I.lower) {
        traces.push({ type: 'scatter', mode: 'lines', x: hs, y: hs.map((h) => I.upper[h][resp][imp]), xaxis: c.xa, yaxis: c.ya, line: { color: rgba(lc, 0.4), width: 0.8 }, hoverinfo: 'skip', showlegend: false, name: 'upper' },
          { type: 'scatter', mode: 'lines', x: hs, y: hs.map((h) => I.lower[h][resp][imp]), xaxis: c.xa, yaxis: c.ya, line: { color: rgba(lc, 0.4), width: 0.8 }, fill: 'tonexty', fillcolor: rgba(lc, dark() ? 0.22 : 0.14), hoverinfo: 'skip', showlegend: false, name: 'lower' });
      }
      traces.push({ type: 'scatter', mode: 'lines+markers', x: hs, y, xaxis: c.xa, yaxis: c.ya, line: { color: lc, width: 1.6 }, marker: { size: 3.5, color: lc }, showlegend: false, name: `${I.names[imp]} → ${I.names[resp]}`,
        hovertemplate: `${esc(I.names[imp])} → ${esc(I.names[resp])}<br>h = %{x}: %{y:.4g}<extra></extra>` });
      const xk = c.n ? `xaxis${c.n + 1}` : 'xaxis', yk = c.n ? `yaxis${c.n + 1}` : 'yaxis';
      layout[xk] = { domain: c.xd, anchor: c.ya, showticklabels: c.i === k - 1, title: c.i === k - 1 ? { text: 'h', font: { size: 10 } } : undefined, tickfont: { size: 9.5 }, range: [-0.3, H + 0.3], zeroline: false };
      layout[yk] = { domain: c.yd, anchor: c.xa, tickfont: { size: 9.5 }, zeroline: false };
      layout.shapes.push({ type: 'line', xref: c.xa, yref: c.ya, x0: 0, x1: H, y0: 0, y1: 0, line: { color: tc.muted, width: 0.8, dash: 'dot' } });
      layout.annotations.push({ text: `${esc(I.names[imp])}${narrow ? '<br>' : ' '}→ ${esc(I.names[resp])}`, xref: 'paper', yref: 'paper', x: (c.xd[0] + c.xd[1]) / 2, y: c.yd[1], xanchor: 'center', yanchor: 'bottom', showarrow: false, font: { size: narrow ? 8.5 : 10 } });
    }
    ob.add(ctx.plot(traces, layout, { width: 60 + cw * k, height: (narrow ? 70 : 50) + Math.round(cw * (narrow ? 0.98 : 0.78)) * k, title: 'Impulse responses', select: false }));
    ob.add(ctx.note(`${cum ? 'Cumulative responses (the sums from 0 to h). ' : ''}Row: the responding series; column: the shock (impulse → response). ${I.shock_note} ${I.band_note}`));
    for (const n of I.notes || []) ob.add(ctx.note(n));
    const rowsT = [];
    for (let i = 0; i < k; i++) for (let j = 0; j < k; j++) for (const h of hs) rowsT.push({ response: I.names[i], impulse: I.names[j], h, value: I.values[h][i][j], lower: I.lower ? I.lower[h][i][j] : null, upper: I.upper ? I.upper[h][i][j] : null });
    const tb = ctx.outline('Impulse Response Table', { parent: ob, key: 'irf:table', closed: true });
    tb.add(ctx.rt({ columns: [{ key: 'response', label: 'Response', fmt: 'text' }, { key: 'impulse', label: 'Impulse', fmt: 'text' }, { key: 'h', label: 'h', fmt: 'int' }, { key: 'value', label: 'Response Value' },
      ...(I.lower ? [{ key: 'lower', label: `Lower ${fmt(100 * (1 - ctx.alpha))}%` }, { key: 'upper', label: `Upper ${fmt(100 * (1 - ctx.alpha))}%` }] : [])], rows: rowsT }, { sortable: true, maxRows: 40, name: 'Impulse responses' }));
    ob.add(ctx.code(I.code));
  }

  /* ---- the forecast error variance decomposition ------------------------------------------------------ */
  async function fevdPart(ctx, base, p, box) {
    const F = await ctx.call('multits.fevd', { ...base, p, trend: trendOf(ctx), horizon: horizon(ctx), order: orderNames(ctx) });
    const ob = ctx.outline('Forecast Error Variance Decomposition', { parent: box, key: 'fevd', info: 'p:multits:fevd', menu: () => [
      { label: 'Horizon…', action: () => askNumber(ctx, { title: 'Horizon', label: 'Forecast steps', key: 'horizon', value: horizon(ctx), min: 1, max: 100, info: 'p:multits:fevd' }) },
      { label: 'Cholesky Ordering…', action: () => orderDialog(ctx) },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('fevd', false) },
    ] });
    if (F.error) { ob.add(ctx.warn(F.error)); return; }
    const k = F.names.length, H = F.horizon;
    const hs = Array.from({ length: H }, (_, h) => h + 1);
    const dom = stackDomains(k, 0.07);
    const traces = [];
    const layout = { barmode: 'stack', bargap: 0.18, showlegend: true, legend: { orientation: 'h', y: -0.08 - 0.16 / k, traceorder: 'normal' }, margin: { l: 56, r: 12, t: 20, b: 40 }, annotations: [], xaxis: { anchor: `y${k}`, title: { text: 'Steps ahead' }, dtick: H > 20 ? 5 : 1 } };
    for (let i = 0; i < k; i++) {
      const ya = axisName('y', i);
      for (let j = 0; j < k; j++) {
        traces.push({ type: 'bar', x: hs, y: hs.map((h) => F.decomp[i][h - 1][j]), xaxis: 'x', yaxis: ya, name: F.names[j], legendgroup: F.names[j], showlegend: i === 0, marker: { color: colorOf(j) },
          hovertemplate: `${esc(F.names[i])}, ${esc(F.names[j])} shock, h = %{x}: %{y:.3f}<extra></extra>` });
      }
      layout[`yaxis${i ? i + 1 : ''}`] = { domain: dom[i], range: [0, 1], tickformat: '.0%', title: { text: esc(F.labels[i]), font: { size: 10.5 } } };
    }
    ob.add(ctx.plot(traces, layout, { width: plotWidth(ctx, 560), height: Math.max(260, 80 + 120 * k), title: 'Variance decomposition', select: false }));
    ob.add(ctx.note(`The share of each series' h-step forecast error variance that comes from each orthogonalized shock (res.fevd; the Cholesky ordering ${F.names.join(', ')}, as the impulse responses). The shares of a row add to 1.`));
    F.names.forEach((n, i) => {
      const sub = ctx.outline(`FEVD for ${F.labels[i]}`, { parent: ob, key: `fevd:${n}`, closed: true });
      sub.add(ctx.rt({ columns: [{ key: 'h', label: 'Steps Ahead', fmt: 'int' }, ...F.names.map((m, j) => ({ key: `s${j}`, label: m, digits: 4 }))], rows: hs.map((h) => ({ h, ...Object.fromEntries(F.names.map((m, j) => [`s${j}`, F.decomp[i][h - 1][j]])) })) }, { sortable: false, name: `FEVD for ${n}`, key: `fevd:${n}` }));
    });
    ob.add(ctx.code(F.code));
  }

  /* ---- forecasts ------------------------------------------------------------------------------------ */
  function forecastPlot(ctx, S, names, U, fc, { title, level }) {
    const k = names.length;
    const dom = stackDomains(k, 0.06);
    const xo = xOf(S, U.t_obs), xf = xOf(S, fc.t);
    const rows = linked(U.rows);
    const traces = [];
    const layout = { xaxis: xAxis(S, { anchor: `y${k}` }), margin: { l: 64, r: 12, t: 8, b: 40 }, shapes: [] };
    for (let i = 0; i < k; i++) {
      const ya = axisName('y', i), c = colorOf(i);
      const last = U.observed[i].length - 1;
      traces.push({ type: 'scatter', mode: 'lines+markers', x: xo, y: U.observed[i], rows, xaxis: 'x', yaxis: ya, name: names[i], connectgaps: false, line: { color: rgba(c, 0.7), width: 1 }, marker: { size: 3.5, color: c },
        hovertext: rows.map((r) => (r >= 0 ? `row ${r + 1}` : 'no row')), hovertemplate: `${esc(names[i])}<br>%{hovertext}<br>%{x}: %{y:.5g}<extra></extra>` });
      if (U.fitted) traces.push({ type: 'scatter', mode: 'lines', x: xo, y: U.fitted[i], xaxis: 'x', yaxis: ya, line: { color: c, width: 1, dash: 'dot' }, name: `${names[i]} one step ahead`, hovertemplate: `one step ahead: %{y:.5g}<extra></extra>` });
      const x0 = xo[last], y0 = U.observed[i][last];
      traces.push({ type: 'scatter', mode: 'lines', x: [x0, ...xf], y: [y0, ...fc.upper[i]], xaxis: 'x', yaxis: ya, line: { color: rgba(c, 0.55), width: 0.8 }, hoverinfo: 'skip', name: `${names[i]} upper` },
        { type: 'scatter', mode: 'lines', x: [x0, ...xf], y: [y0, ...fc.lower[i]], xaxis: 'x', yaxis: ya, line: { color: rgba(c, 0.55), width: 0.8 }, fill: 'tonexty', fillcolor: rgba(c, 0.14), hoverinfo: 'skip', name: `${names[i]} lower` },
        { type: 'scatter', mode: 'lines+markers', x: [x0, ...xf], y: [y0, ...fc.mean[i]], xaxis: 'x', yaxis: ya, line: { color: c, width: 2 }, marker: { size: 3, color: c }, name: `${names[i]} forecast`,
          hovertemplate: `${esc(names[i])} forecast %{x}: %{y:.5g}<extra></extra>` });
      layout[`yaxis${i ? i + 1 : ''}`] = { domain: dom[i], title: { text: esc(names[i]), font: { size: 10.5 } } };
      if (x0 != null) layout.shapes.push({ type: 'line', xref: 'x', yref: `${ya} domain`, x0, x1: x0, y0: 0, y1: 1, line: { color: SM.util.themeColors().muted, width: 1, dash: 'dot' } });
    }
    const plot = ctx.plot(traces, layout, { width: plotWidth(ctx, 660), height: Math.max(260, 60 + 130 * k), title });
    return [plot, ctx.note(`${fc.t.length} periods ahead, from ${tLabel(S, fc.t[0])} to ${tLabel(S, fc.t[fc.t.length - 1])}, with ${fmt(100 * level)}% intervals; to the left of the dotted line the data${U.fitted ? ' and the one-step-ahead predictions' : ''}.`)];
  }

  function forecastRows(S, names, fc) {
    return fc.t.map((t, h) => ({ t: tLabel(S, t), ...Object.fromEntries(names.flatMap((n, i) => [[`m${i}`, fc.mean[i][h]], [`l${i}`, fc.lower[i][h]], [`u${i}`, fc.upper[i][h]]])) }));
  }
  const forecastCols = (names, level) => [{ key: 't', label: 'Time', fmt: 'text' }, ...names.flatMap((n, i) => [{ key: `m${i}`, label: `${n}` }, { key: `l${i}`, label: `Lower ${fmt(100 * level)}%` }, { key: `u${i}`, label: `Upper ${fmt(100 * level)}%` }])];

  function forecastPayload(ctx, base, p) {
    return { ...base, p, trend: trendOf(ctx), h: periods(ctx), alpha: ctx.alpha, original: !ctx.opt('fcTransformed', false) };
  }

  async function forecastPart(ctx, base, S, p, box) {
    const F = await ctx.call('multits.forecast', forecastPayload(ctx, base, p));
    const transformed = S.log || S.diff;
    const ob = ctx.outline('Forecast', { parent: box, key: 'forecast', info: 'p:multits:forecast', menu: () => [
      { label: 'Number of Forecast Periods…', action: () => askNumber(ctx, { title: 'Number of Forecast Periods', label: 'Periods to forecast', key: 'forecast', value: periods(ctx), min: 1, max: 500, info: 'p:multits:forecast' }) },
      transformed ? ctx.check('Show the Series as Analysed', 'fcTransformed', null, false) : null,
      { label: 'Save Forecasts', disabled: !!F.error, action: () => saveForecasts(ctx, S, F) },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('fc', false) },
    ].filter(Boolean) });
    if (F.error) { ob.add(ctx.warn(F.error)); return; }
    const U = F.original || F.transformed;
    const names = F.original ? F.names : F.labels;
    const fc = { t: F.t, mean: U.mean, lower: U.lower, upper: U.upper };
    ob.add(...forecastPlot(ctx, S, names, U, fc, { title: 'VAR forecasts', level: F.level }));
    if (F.original) ob.add(ctx.note(F.original_note));
    else ob.add(ctx.note(`forecast_interval: ± z standard errors from the forecast MSE of the VAR (Σ Φⱼ Σᵤ Φⱼ'), which leaves out the uncertainty of the estimated coefficients${transformed ? '; the series as analysed, not in the units of the table' : ''}.`));
    for (const n of F.notes || []) ob.add(ctx.note(n));
    const tb = ctx.outline('Forecast Table', { parent: ob, key: 'forecast:table', closed: true });
    tb.add(ctx.rt({ columns: forecastCols(names, F.level), rows: forecastRows(S, names, fc) }, { sortable: false, name: 'Forecasts', maxRows: 60 }));
    ob.add(ctx.code(F.code));
  }

  function timeColumn(ctx, S, t) {
    return { name: ctx.name('time') || 'Row', dataType: 'numeric', values: t, format: isDate(S) ? { kind: S.tkind === 'datetime' ? 'datetime' : 'date' } : null };
  }

  function saveForecasts(ctx, S, F) {
    if (!F || F.error) return;
    const U = F.original || F.transformed;
    const names = F.original ? F.names : F.labels;
    const n = U.t_obs.length, h = F.t.length;
    const lv = fmt(F.level);
    const pad = (m) => new Array(m).fill(NaN);
    const columns = [timeColumn(ctx, S, [...U.t_obs, ...F.t])];
    names.forEach((nm, i) => {
      columns.push({ name: `Actual ${nm}`, dataType: 'numeric', values: [...nan(U.observed[i]), ...pad(h)] },
        { name: `Predicted ${nm}`, dataType: 'numeric', values: [...(U.fitted ? nan(U.fitted[i]) : pad(n)), ...nan(U.mean[i])] },
        { name: `Lower CL (${lv}) ${nm}`, dataType: 'numeric', values: [...pad(n), ...nan(U.lower[i])] },
        { name: `Upper CL (${lv}) ${nm}`, dataType: 'numeric', values: [...pad(n), ...nan(U.upper[i])] });
    });
    SM.app.addTable(new SM.Table({ name: `VAR(${F.p}) forecasts`, source: `saved from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`,
      notes: `One-step-ahead predictions, then ${h} forecasts of the VAR(${F.p}) with ${fmt(100 * F.level)}% limits${F.original ? ', in the units of the table' : ''}.`, columns }));
  }

  /* ---- cointegration: Johansen, VECM, Engle-Granger ------------------------------------------------------- */
  function kArDiff(ctx, S, p) {
    const v = ctx.opt('kArDiff', null);
    if (v != null && Number.isInteger(v) && v >= 0) return v;
    return S.diff ? p : Math.max(0, p - 1);
  }
  const detOrder = (ctx) => { const d = int(ctx.opt('detOrder', 0), 0); return [-1, 0, 1].includes(d) ? d : 0; };

  async function johansenDialog(ctx, S, p) {
    const v = await SM.ui.form({
      title: 'Johansen Test Options', info: 'p:multits:coint',
      lead: 'The deterministic terms and the number of lagged differences of the test (coint_johansen). With a VAR(p) in levels a VECM has p − 1 lagged differences.',
      fields: [
        { key: 'det', label: 'Deterministic terms (det_order)', type: 'select', value: String(detOrder(ctx)), choices: DET_ORDERS,
          help: 'The test\'s deterministic terms: None (−1); Constant, unrestricted (0, the default), which lets the levels drift in a linear trend; Constant and linear trend, unrestricted (1). The VECM takes the same unless VECM Deterministic Terms picks others.' },
        { key: 'kd', label: 'Lagged differences (k_ar_diff)', type: 'number', value: kArDiff(ctx, S, p),
          help: `The lagged differences in the test's regression, and in the VECM, 0 to 24: at first p − 1, the short-run dynamics of the VAR(${p}) in levels (p when Difference is on).` },
        { key: 'method', label: 'Choose the rank by', type: 'select', value: ctx.opt('rankMethod', 'trace'), choices: [['trace', 'Trace test'], ['maxeig', 'Maximum eigenvalue test']],
          help: 'The test that picks the rank, from r = 0 up, the first r not rejected: the trace test (the default) of rank ≤ r against k, or the maximum eigenvalue test of r against r + 1. At the tabulated level (10, 5 or 1%) nearest α.' },
      ],
      validate: (x) => (Number.isInteger(x.kd) && x.kd >= 0 && x.kd <= 24 ? null : 'Lagged differences: a whole number from 0 to 24'),
    });
    if (!v) return;
    ctx.set('detOrder', Number(v.det), null, { rerun: false });
    ctx.set('rankMethod', v.method, null, { rerun: false });
    ctx.set('kArDiff', v.kd);
  }

  function cointMenu(ctx, S, p, E) {
    const k = S.names.length;
    const det = ctx.opt('deterministic', null);
    return [
      { label: 'Johansen Test Options…', action: () => johansenDialog(ctx, S, p) },
      { label: 'Cointegration Rank…', action: () => askNumber(ctx, { title: 'Cointegration Rank', label: `Rank of the VECM (1 to ${k - 1})`, key: 'rank', value: E && !E.error ? E.rank : 1, min: 1, max: k - 1, info: 'p:multits:vecm' }) },
      { label: 'Rank from the Test', checked: ctx.opt('rank', null) == null, action: () => ctx.set('rank', null) },
      { label: 'VECM Deterministic Terms', submenu: () => DETS.map(([key, lab]) => ({ label: lab, checked: (det || DET_FOR[detOrder(ctx)]) === key, action: () => ctx.set('deterministic', key) })) },
      { separator: true },
      ctx.check('Engle-Granger Test', 'eg', null, true),
      { label: 'Save VECM Forecasts', disabled: !E || !!E.error, action: () => saveVecm(ctx, S, E) },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('coint', false) },
    ];
  }

  async function cointPart(ctx, base, S, p, box) {
    const k = S.names.length;
    const kd = kArDiff(ctx, S, p);
    const J = await ctx.call('multits.johansen', { ...base, det_order: detOrder(ctx), k_ar_diff: kd, method: ctx.opt('rankMethod', 'trace') === 'maxeig' ? 'maxeig' : 'trace', alpha: ctx.alpha });
    const want = ctx.opt('rank', null);
    const rank = want != null ? int(want, 1) : (J.error ? 1 : J.rank);
    const clamped = Math.max(1, Math.min(k - 1, rank));
    const det = ctx.opt('deterministic', null) || DET_FOR[detOrder(ctx)];
    const E = await ctx.call('multits.vecm', { ...base, rank: clamped, k_ar_diff: kd, deterministic: det, h: periods(ctx), alpha: ctx.alpha });
    const ob = ctx.outline('Cointegration', { parent: box, key: 'coint', info: 'p:multits:coint', menu: () => cointMenu(ctx, S, p, E) });
    if (S.diff) ob.add(ctx.note('Difference is on for the VAR; cointegration is a property of the levels, so the tests and the VECM below take the series before differencing' + (S.log ? ' (their logarithms).' : '.')));
    // Johansen
    const jo = ctx.outline('Johansen Cointegration Test', { parent: ob, key: 'coint:joh', info: 'p:multits:coint' });
    if (J.error) jo.add(ctx.warn(J.error));
    else {
      const cols = [{ key: 'h0', label: 'H0: Rank', fmt: 'text' }, { key: 'eig', label: 'Eigenvalue' }, { key: 'trace', label: 'Trace' }, { key: 'trace90', label: '90%' }, { key: 'trace95', label: '95%' }, { key: 'trace99', label: '99%' },
        { key: 'maxeig', label: 'Max-Eigen' }, { key: 'max90', label: '90%' }, { key: 'max95', label: '95%' }, { key: 'max99', label: '99%' }];
      const tbl = ctx.rt({ columns: cols, rows: J.rows }, { sortable: false, name: 'Johansen test', className: 'mts-joh' });
      const crit = J.signif === 0.1 ? 3 : J.signif === 0.01 ? 5 : 4;
      tbl.querySelectorAll('tbody tr').forEach((tr, i) => {
        const r = J.rows[i];
        const tr95 = r[['trace90', 'trace95', 'trace99'][crit - 3]], mx = r[['max90', 'max95', 'max99'][crit - 3]];
        if (r.trace > tr95) tr.children[2].classList.add('mts-reject');
        if (r.maxeig > mx) tr.children[6].classList.add('mts-reject');
        if (r.rank === J.rank) tr.classList.add('mts-chosen');
      });
      jo.add(el('div', { class: 'mts-scroll' }, tbl));
      jo.add(ctx.kv([['Selected Rank', J.rank, 'int'], ['Chosen By', `${J.method === 'maxeig' ? 'maximum eigenvalue' : 'trace'} test at ${fmt(100 * J.signif)}%`, 'text'], ['Deterministic Terms', J.det_label, 'text'], ['Lagged Differences', J.k_ar_diff, 'int'], ['Observations', J.nobs, 'int']]));
      jo.add(ctx.note(`H0: the cointegration rank is at most r, tested from r = 0 up; the selected rank is the first r not rejected (select_coint_rank). The trace statistic tests r against k = ${k}, the maximum eigenvalue r against r + 1; bold statistics exceed their ${fmt(100 * (1 - J.signif))}% critical value. The critical values are MacKinnon, Haug and Michelis's (1999), for up to 12 series.`));
      for (const n of J.notes || []) jo.add(ctx.note(n));
      if (J.rank === 0) jo.add(ctx.warn('No cointegration at this level: the series share no long-run relation, and a VAR in differences (Transform > Difference) is the model. The VECM below uses rank 1 to show the fit; set the rank in the red triangle.'));
      else if (J.rank === k) jo.add(ctx.warn(`Full rank: every combination is stationary, so the levels are, and a VAR in levels is the model. The VECM below uses rank ${k - 1}.`));
      jo.add(ctx.code(J.code));
    }
    // VECM
    const vo = ctx.outline(`VECM (rank ${clamped})`, { parent: ob, key: 'coint:vecm', info: 'p:multits:vecm' });
    if (E.error) vo.add(ctx.warn(E.error));
    else {
      const zcols = (first) => [...first, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'z', label: 'z Ratio' }, { key: 'p', label: 'Prob>|z|', fmt: 'p' }];
      vo.add(ctx.kv([['Cointegration Rank', E.rank, 'int'], ['Lagged Differences', E.k_ar_diff, 'int'], ['Deterministic Terms', E.det_label, 'text'], ['Observations Used', E.nobs, 'int'], ['Log Likelihood', E.llf]]));
      const a = ctx.outline('Loading Coefficients (α)', { parent: vo, key: 'vecm:alpha' });
      a.add(ctx.rt({ columns: zcols([{ key: 'equation', label: 'Equation', fmt: 'text' }, { key: 'term', label: 'Term', fmt: 'text' }]), rows: E.alpha }, { sortable: false, name: 'VECM loadings' }),
        ctx.note('How fast each series moves back toward the long-run relations: Δy_t = α β\'y_{t−1} + Σ Γᵢ Δy_{t−i} + deterministic terms + u_t. A negative α on a series whose own β is positive pulls it back.'));
      const b = ctx.outline('Cointegrating Vectors (β)', { parent: vo, key: 'vecm:beta' });
      b.add(ctx.rt({ columns: zcols([{ key: 'relation', label: 'Relation', fmt: 'text' }, { key: 'variable', label: 'Series', fmt: 'text' }]), rows: E.beta }, { sortable: false, name: 'VECM cointegrating vectors' }),
        ctx.note(`Normalised as statsmodels does (Johansen's): the first ${E.rank === 1 ? 'coefficient is 1' : `${E.rank} rows are the identity`}, fixed rather than estimated.${E.rank === 1 ? ` ${relationText(E)} is the stationary combination.` : ''}`));
      const g = ctx.outline('Short-Run Coefficients (Γ)', { parent: vo, key: 'vecm:gamma', closed: !E.k_ar_diff });
      if (!E.k_ar_diff) g.add(ctx.note('No lagged differences in this VECM.'));
      E.gamma.forEach((eq, i) => {
        const go = ctx.outline(`Equation Δ${eq.equation}`, { parent: g, key: `vecm:gamma:${eq.equation}`, closed: i > 0 });
        go.add(ctx.rt({ columns: zcols([{ key: 'term', label: 'Term', fmt: 'text' }]), rows: eq.rows }, { sortable: false, name: `VECM short-run ${eq.equation}`, key: `vecm-gamma:${eq.equation}` }));
      });
      if (E.det.length) {
        const d = ctx.outline('Deterministic Terms', { parent: vo, key: 'vecm:det', closed: true });
        d.add(ctx.rt({ columns: zcols([{ key: 'equation', label: 'Equation', fmt: 'text' }, { key: 'term', label: 'Term', fmt: 'text' }]), rows: E.det }, { sortable: false, name: 'VECM deterministic terms' }));
      }
      for (const n of E.notes || []) vo.add(ctx.note(n));
      const fo = ctx.outline('VECM Forecast', { parent: vo, key: 'vecm:fc' });
      const U = { t_obs: E.observed.t, observed: E.observed.values, rows: E.observed.rows, fitted: null };
      fo.add(...forecastPlot(ctx, S, E.names, U, { t: E.forecast.t, mean: E.forecast.mean, lower: E.forecast.lower, upper: E.forecast.upper }, { title: 'VECM forecasts', level: E.forecast.level }));
      fo.add(ctx.note('The forecasts of the levels (statsmodels\' VECMResults.predict, the VECM as a VAR in levels), in the units of the table.'));
      vo.add(ctx.code(E.code));
    }
    // Engle-Granger
    if (ctx.opt('eg', true)) {
      const G = await ctx.call('multits.engle_granger', { ...base, trend: trendOf(ctx) === 'ct' ? 'ct' : trendOf(ctx) === 'n' ? 'n' : 'c' });
      const eo = ctx.outline('Engle-Granger Test', { parent: ob, key: 'coint:eg', info: 'p:multits:coint' });
      if (G.error) eo.add(ctx.warn(G.error));
      else {
        eo.add(ctx.rt({ columns: [{ key: 'dependent', label: 'Dependent', fmt: 'text' }, { key: 'regressors', label: 'Regressed On', fmt: 'text' }, { key: 'stat', label: 't Ratio (ADF)' }, { key: 'p', label: 'Prob', fmt: 'p' },
          { key: 'c1', label: '1%' }, { key: 'c5', label: '5%' }, { key: 'c10', label: '10%' }], rows: G.rows }, { sortable: false, name: 'Engle-Granger test' }),
        ctx.note(`Each series regressed by least squares on the other${k > 2 ? 's' : ''}${G.trend === 'ct' ? ' and a trend' : G.trend === 'n' ? ' (no constant)' : ''}, then an ADF test of the residuals (statsmodels' coint): H0 is no cointegration, so a small p-value says the series are cointegrated. MacKinnon's (2010) p-values and critical values for ${k} series.`));
        eo.add(ctx.code(G.code));
      }
    }
  }

  /* ec1 = x − 1.7 y + 0.65 z: the first cointegrating relation as text. */
  function relationText(E) {
    const terms = E.beta.filter((r) => r.relation === 'ec1' && E.names.includes(r.variable));
    return `ec1 = ${terms.map((r, i) => (i === 0 ? r.variable : `${r.estimate < 0 ? '−' : '+'} ${fmt(Math.abs(r.estimate))} ${r.variable}`)).join(' ')}`;
  }

  function saveVecm(ctx, S, E) {
    if (!E || E.error) return;
    const n = E.observed.t.length, h = E.forecast.t.length;
    const lv = fmt(E.forecast.level);
    const pad = (m) => new Array(m).fill(NaN);
    const columns = [timeColumn(ctx, S, [...E.observed.t, ...E.forecast.t])];
    E.names.forEach((nm, i) => {
      columns.push({ name: `Actual ${nm}`, dataType: 'numeric', values: [...nan(E.observed.values[i]), ...pad(h)] },
        { name: `Forecast ${nm}`, dataType: 'numeric', values: [...pad(n), ...nan(E.forecast.mean[i])] },
        { name: `Lower CL (${lv}) ${nm}`, dataType: 'numeric', values: [...pad(n), ...nan(E.forecast.lower[i])] },
        { name: `Upper CL (${lv}) ${nm}`, dataType: 'numeric', values: [...pad(n), ...nan(E.forecast.upper[i])] });
    });
    SM.app.addTable(new SM.Table({ name: `VECM (rank ${E.rank}) forecasts`, source: `saved from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`, columns }));
  }

  /* ---- the red triangle of the report ---------------------------------------------------------------------- */
  function topMenu(ctx) {
    const withP = (fn) => async () => {
      const base = basePayload(ctx);
      const p = await lagOf(ctx, base);
      if (p == null) { SM.ui.toast('No VAR to take it from: see the report', { error: true }); return; }
      return fn(base, p);
    };
    return [
      { label: 'Time Series Graph', submenu: () => [ctx.check('Show Graph', 'graph', null, true), ctx.check('Small Multiples', 'multiples', null, false)] },
      ctx.check('Stationarity Summary', 'stationarity', null, true),
      { label: 'Transform', submenu: () => [ctx.check('Log Transform', 'log', null, false), ctx.check('Difference (d = 1)', 'diff', null, false)] },
      { separator: true },
      ctx.check('Lag Order Selection', 'lagsel', null, true),
      { label: 'Choose Lag By', submenu: () => lagItems(ctx) },
      { label: 'Maximum Lag…', action: () => askNumber(ctx, { title: 'Maximum Lag', label: 'Largest lag in the selection table', key: 'maxlags', value: maxLags(ctx), min: 1, max: 48, info: 'p:multits:lags' }) },
      { label: 'Trend', submenu: () => TRENDS.map(([k, lab]) => ({ label: lab, checked: trendOf(ctx) === k, action: () => ctx.set('trend', k) })) },
      { separator: true },
      ctx.check('Granger Causality', 'granger', null, true),
      ctx.check('Impulse Response', 'irf', null, true),
      ctx.check('Forecast Error Variance Decomposition', 'fevd', null, true),
      ctx.check('Forecast', 'fc', null, true),
      ctx.check('Cointegration', 'coint', null, false),
      { separator: true },
      { label: 'Cholesky Ordering…', action: () => orderDialog(ctx) },
      { label: 'IRF Horizon…', action: () => askNumber(ctx, { title: 'Impulse Response Horizon', label: 'Periods after the shock', key: 'horizon', value: horizon(ctx), min: 1, max: 100, info: 'p:multits:irf' }) },
      { label: 'Number of Forecast Periods…', action: () => askNumber(ctx, { title: 'Number of Forecast Periods', label: 'Periods to forecast', key: 'forecast', value: periods(ctx), min: 1, max: 500, info: 'p:multits:forecast' }) },
      { separator: true },
      { label: 'Save Forecasts', action: withP(async (base, p) => {
        const S = await ctx.call('multits.series', { ...base, trend: trendOf(ctx), alpha: ctx.alpha });
        S.tkind = timeKind(S);
        const F = await ctx.call('multits.forecast', forecastPayload(ctx, base, p));
        if (F.error) SM.ui.toast(F.error, { error: true }); else saveForecasts(ctx, S, F);
      }) },
      { label: 'Save Residuals', action: withP((base, p) => saveResiduals(ctx, base, p)) },
    ];
  }

  /* The lag the report uses, for the menu items that need the VAR. */
  async function lagOf(ctx, base) {
    const fixed = int(ctx.opt('lagFixed', null), 0) || null;
    if (fixed) return fixed;
    const L = await ctx.call('multits.select_order', { ...base, maxlags: maxLags(ctx), trend: trendOf(ctx) });
    return L.error ? null : Math.max(1, L.selected[lagBy(ctx)]);
  }

  /* ---- topics for the (i) ------------------------------------------------------------------------------------ */
  const topics = {
    'p:multits': {
      kicker: 'Analyze > Specialized Modeling', title: 'Multivariate Time Series',
      lead: 'Two or more series observed at the same times, modelled together: each series is regressed on the recent past of all of them (a vector autoregression, VAR). From it come the tests of which series help to forecast which (Granger causality), the responses of every series to a shock in one (impulse responses), the variance decomposition and joint forecasts; and for series that wander but move together, the cointegration tests and the vector error correction model (VECM). statsmodels.tsa.vector_ar; JMP has no such platform.',
      sections: [
        { heading: 'Roles', choices: [['Y, Time Series', 'Two or more continuous series, in the order the orthogonalized impulse responses take them (Cholesky Ordering… changes it).'], ['X, Time ID', 'Orders the rows and labels the time axis; a date column gives the calendar frequency and the dates of the forecasts.'], ['Exogenous', 'Continuous columns that enter every equation as regressors, not modelled themselves; forecasts take their future values from the rows after the series.'], ['By', 'A report for each level.']] },
        { heading: 'Options', choices: [['Maximum Lag for Selection', 'The largest lag of the Lag Order Selection table (default 8).'], ['Forecast Periods', 'How far the forecasts go (default 12).'], ['IRF Horizon', 'How many periods the impulse responses and the variance decomposition cover (default 10).'], ['Trend', 'Constant (c), constant and linear trend (ct) or none (n) in every equation.']] },
        { heading: 'Missing and excluded rows', text: 'The series are taken where every one has a value. Inside that span a VAR needs every time point: excluded rows, missing cells and dates missing from the calendar are filled by linear interpolation, and the report says how many. The graphs show them as gaps.' },
        { heading: 'Differences from what JMP users expect', list: ['JMP has no VAR: its Time Series platform models one series at a time (with inputs as transfer functions).', 'AIC, BIC and HQIC are Lütkepohl\'s per-observation criteria of the whole system (ln det Ω + penalty/n), not −2 log L + 2k.', 'The p-values of the coefficients are from the normal distribution, as statsmodels gives them, not t.', 'Impulse response bands are asymptotic (the delta method) by default; Monte Carlo bands simulate the fitted VAR (statsmodels\' errband_mc, a fixed seed). Neither is a bootstrap.', 'Forecast intervals leave out the uncertainty of the estimated coefficients (statsmodels\' forecast_interval).'] },
      ],
      more: MORE,
    },
    'p:multits:timeid': { kicker: 'Multivariate Time Series', title: 'X, Time ID', lead: 'The column that orders the rows and labels the time axis. A date column (Column Info > Format: Date) gives a date axis; its calendar frequency is found with pandas.infer_freq, also when a few dates have no row (they are inserted and filled), and the forecasts continue the calendar. A numeric Time ID continues its step; without one the row number is the time.', more: MORE },
    'p:multits:exog': { kicker: 'Multivariate Time Series', title: 'Exogenous', lead: 'Continuous columns that enter every equation of the VAR as regressors (VAR(endog, exog=…)): their coefficients are estimated, their own dynamics are not modelled. The forecasts need their future values: they come from the rows after the series in the table (the Y columns empty there), and the last value is held beyond them. Not differenced by Transform > Difference.', more: MORE },
    'p:multits:stationarity': {
      kicker: 'Multivariate Time Series', title: 'Stationarity Summary',
      lead: 'A VAR in levels needs stationary series. For each series as analysed: the augmented Dickey-Fuller test (adfuller, lags by AIC), whose null is a unit root, and the KPSS test (kpss), whose null is stationarity, both with the deterministic terms of the VAR\'s trend.',
      sections: [{ heading: 'Reading', choices: [['stationary', 'ADF rejects a unit root and KPSS does not reject stationarity.'], ['unit root: difference', 'ADF does not reject and KPSS rejects: take Transform > Difference, or look for cointegration.'], ['unclear', 'The two tests disagree; look at the graph.']] }],
      more: MORE,
    },
    'p:multits:lags': {
      kicker: 'Multivariate Time Series', title: 'Lag Order Selection',
      lead: 'VARs of every lag from 0 to the maximum, all fitted on the same observations (those after the maximum lag), with Akaike\'s (AIC), Schwarz\'s (BIC), Hannan-Quinn\'s (HQIC) criteria and the final prediction error (FPE), as statsmodels\' select_order computes them. The smallest of each is marked.',
      sections: [{ heading: 'Choosing', text: 'The lag the chosen criterion prefers (AIC by default) fits the VAR; Choose Lag By in the red triangle picks another criterion, and a click on a line fixes that lag. BIC and HQIC choose shorter lags than AIC and FPE; the Whiteness Test says whether the residuals are left with autocorrelation.' },
        { heading: 'In the report', choices: [['A line of the table', 'click it to fix that lag (from 1 up): the VAR and every part after it use it, as Fixed Lag Order… does. The line in use is marked, and so is the smallest value of each criterion. Choose Lag By, in the red triangle, goes back to a criterion']] }],
      more: MORE,
    },
    'p:multits:var': {
      kicker: 'Multivariate Time Series', title: 'Vector Autoregression',
      lead: 'y_t = ν + A₁y_{t−1} + … + A_p y_{t−p} + B x_t + u_t: every series regressed on p lags of all of them (and the trend and the exogenous columns), by least squares equation by equation (statsmodels\' VAR.fit). The residual covariance Σᵤ has n − (kp + trend terms + exogenous) degrees of freedom.',
      sections: [
        { heading: 'The report', text: 'Model Summary: the lag, the log likelihood, AIC, BIC, HQIC, FPE and det Ω (the ML residual covariance). Parameter Estimates: one table per equation, the others closed; x(t−2) is x two periods before. Right click a table for statsmodels\' names (L2.x).' },
        { heading: 'Save', text: 'Save Residuals writes the residuals of each equation to the table; the first p rows (and one more after a difference) have none.' },
      ],
      more: MORE,
    },
    'p:multits:diagnostics': {
      kicker: 'Multivariate Time Series', title: 'Residual diagnostics',
      lead: 'Residual Correlation: the correlations of the equations\' residuals (large ones: shocks come together, and the Cholesky ordering matters). Stability: the eigenvalues of the companion matrix, all inside the unit circle for a stable VAR, whose responses die out.',
      sections: [
        { heading: 'Whiteness Test', text: 'The Portmanteau test of no residual autocorrelation up to lag h (test_whiteness): Q = n Σ tr(C_j\' C₀⁻¹ C_j C₀⁻¹), χ² with k²(h − p) degrees of freedom; Adjusted is the small-sample version. A small p-value asks for more lags.' },
        { heading: 'Normality Test', text: 'Lütkepohl\'s multivariate Jarque-Bera test of the skewness and kurtosis of the orthogonalized residuals (test_normality), χ² with 2k degrees of freedom.' },
      ],
      more: MORE,
    },
    'p:multits:granger': {
      kicker: 'Multivariate Time Series', title: 'Granger Causality',
      lead: 'x Granger-causes y when the lags of x help to forecast y beyond the lags of y and of the other series: the test that the p coefficients of x in y\'s equation are all zero (test_causality, an F test by default, or Wald χ²). The matrix shows the p-value of each ordered pair, row causes column, and of all the other series together.',
      sections: [{ heading: 'Instantaneous causality', text: 'Whether a series\' residual is correlated with the others\' in the same period (test_inst_causality, Wald χ²): the part of the relation a VAR cannot order in time.' }],
      more: MORE,
    },
    'p:multits:irf': {
      kicker: 'Multivariate Time Series', title: 'Impulse Response',
      lead: 'How every series responds, h = 0, 1, … periods later, to a shock in one of them: the moving average coefficients of the VAR (irf). Orthogonalized: a one-standard-deviation shock through the Cholesky factor of Σᵤ, so that the shocks are uncorrelated; a series then responds at once only to the shocks of the series before it in the ordering (the order of Y, or Cholesky Ordering…). Cumulative: the sums of the responses from 0 to h.',
      sections: [{ heading: 'Bands', choices: [['Asymptotic', 'Response ± z standard errors from the delta method (Lütkepohl 2005, 3.7; statsmodels\' stderr and cum_effect_stderr). The default.'], ['Monte Carlo', 'The fitted VAR simulated many times and refitted each time; the band is between the α/2 and 1 − α/2 points of the simulated responses (statsmodels\' errband_mc). A fixed seed, passed as a bit generator: statsmodels 0.14 given an integer seed repeats the same simulated sample in every replication.'], ['None', 'The responses only.']] }],
      more: MORE,
    },
    'p:multits:fevd': { kicker: 'Multivariate Time Series', title: 'Forecast Error Variance Decomposition', lead: 'For each series and each horizon h, the share of its h-step forecast error variance that comes from each orthogonalized shock (res.fevd), with the Cholesky ordering of the impulse responses. At h = 1 the first series in the ordering is explained by its own shock alone.', more: MORE },
    'p:multits:forecast': {
      kicker: 'Multivariate Time Series', title: 'Forecast',
      lead: 'The VAR run forward from the last p observations (forecast_interval), with intervals of ± z standard errors of the forecast MSE Σ Φⱼ Σᵤ Φⱼ\', which leaves out the uncertainty of the estimated coefficients. The dates continue the Time ID; exogenous columns take their future values from the rows after the series.',
      sections: [
        { heading: 'Transformed series', text: 'After Difference the forecast differences are summed onto the last level, and the intervals use the variance of the sums (the cumulated moving average coefficients); after Log exp() undoes the logarithm, so the forecast is the median. Show the Series as Analysed shows the forecasts of the transformed series instead.' },
        { heading: 'Save Forecasts', text: 'A new table with the time, and for each series the data, the one-step-ahead predictions then the forecasts, and the limits.' },
      ],
      more: MORE,
    },
    'p:multits:coint': {
      kicker: 'Multivariate Time Series', title: 'Cointegration',
      lead: 'Nonstationary series are cointegrated when a combination of them is stationary: they wander, but together. Johansen\'s test (coint_johansen) finds how many such combinations there are, the rank r, from the eigenvalues of a reduced-rank regression of the differences on the lagged levels: the trace test of rank ≤ r against k, and the maximum eigenvalue test against r + 1, tested from r = 0 up (select_coint_rank). It takes the levels (the logarithms after Log Transform).',
      sections: [
        { heading: 'Options', text: 'Deterministic terms: none (−1), an unrestricted constant (0, a linear trend in the levels) or an unrestricted linear trend (1), with the critical values of MacKinnon, Haug and Michelis (1999) for up to 12 series. Lagged differences: p − 1 for a VAR(p) in levels.' },
        { heading: 'Engle-Granger', text: 'Each series regressed on the others by least squares, and an ADF test of the residuals with MacKinnon\'s (2010) p-values for that many series (statsmodels\' coint). It finds one relation at most. statsmodels 0.14.6 has β₂ = −33.527 where MacKinnon (2010, Table 2) prints −22.527 for two series at 1%, which moves that critical value by 11/T².' },
      ],
      more: MORE,
    },
    'p:multits:vecm': {
      kicker: 'Multivariate Time Series', title: 'VECM',
      lead: 'The vector error correction model Δy_t = αβ\'y_{t−1} + Σ Γᵢ Δy_{t−i} + deterministic terms + u_t of the chosen rank, by maximum likelihood (statsmodels\' VECM). β holds the cointegrating vectors (β\'y is stationary), normalised so that the first r rows are the identity; α the loadings, how each series corrects toward the relations; Γ the short-run dynamics.',
      sections: [{ heading: 'Rank and terms', text: 'The rank comes from the Johansen test unless Cointegration Rank… sets it; the deterministic terms follow the test\'s unless VECM Deterministic Terms picks others (a constant or a trend inside the cointegrating relation is possible here, not in the test). The forecasts are of the levels, in the units of the table.' }],
      more: MORE,
    },
  };

  /* ---- the example: simulated, never real data --------------------------------------------------------------------- */
  SM.io.addExample('macro', {
    label: 'Quarterly macro (160 quarters): a VAR(2) and a cointegrated pair',
    about: 'Simulated quarters 1986–2025: growth, inflation and interest rate follow a stable VAR(2) with known coefficients (growth raises inflation, inflation raises the rate, the rate lowers growth) and correlated shocks; income is a random walk with drift and consumption = 10 + 0.8 income + a stationary error, so the two are cointegrated. For Multivariate Time Series.',
    make() {
      const r = SM.util.rng('macro');
      const A1 = [[0.35, 0, -0.5], [0.25, 0.45, 0], [0.1, 0.55, 0.5]];
      const A2 = [[0.2, 0, 0], [0, 0.25, 0], [0, 0, 0.15]];
      const C = [[0.8, 0, 0], [0.12, 0.3816, 0], [0, 0.2516, 0.5447]];   // Cholesky factor of the shocks' covariance
      const mu = [2.5, 2, 4];
      const n = 160, burn = 60;
      const mv = (M, v) => M.map((row) => row.reduce((s, a, j) => s + a * v[j], 0));
      let x1 = [0, 0, 0], x2 = [0, 0, 0];
      const quarter = [], g = [], inf = [], rate = [], inc = [], cons = [];
      let level = 100, w = 0;
      for (let t = -burn; t < n; t++) {
        const z = [r.normal(), r.normal(), r.normal()];
        const a = mv(A1, x1), b = mv(A2, x2), e = mv(C, z);
        const x = [a[0] + b[0] + e[0], a[1] + b[1] + e[1], a[2] + b[2] + e[2]];
        x2 = x1; x1 = x;
        const di = 0.5 + r.normal(0, 1);
        w = 0.7 * w + r.normal(0, 0.8);
        if (t < 0) continue;
        level += di;
        quarter.push(Date.UTC(1986, 3 * t, 1));
        g.push(+(mu[0] + x[0]).toFixed(3)); inf.push(+(mu[1] + x[1]).toFixed(3)); rate.push(+(mu[2] + x[2]).toFixed(3));
        inc.push(+level.toFixed(2)); cons.push(+(10 + 0.8 * level + w).toFixed(2));
      }
      return new SM.Table({ name: 'Quarterly macro', source: 'simulated', columns: [
        { name: 'quarter', dataType: 'numeric', format: { kind: 'date' }, values: quarter },
        { name: 'growth', dataType: 'numeric', values: g },
        { name: 'inflation', dataType: 'numeric', values: inf },
        { name: 'interest rate', dataType: 'numeric', values: rate },
        { name: 'income', dataType: 'numeric', values: inc },
        { name: 'consumption', dataType: 'numeric', values: cons },
      ] });
    },
  });

  /* ---- the platform --------------------------------------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'multits', label: 'Multivariate Time Series', menu: 'Analyze/Specialized Modeling', order: 25, info: 'p:multits', topics,
    about: 'Two or more series modelled together, which JMP does not do: the series on one time axis with ADF and KPSS tests, log and difference; the lag order by AIC, BIC, FPE or HQIC; the VAR(p) with its coefficients by equation, residual correlations, stability, whiteness and normality tests; Granger and instantaneous causality; impulse responses (orthogonalized in any Cholesky ordering, cumulative, with asymptotic or Monte Carlo bands); the forecast error variance decomposition; forecasts that continue the dates, also in the units of the table; and cointegration: Johansen\'s trace and maximum eigenvalue tests, the VECM of the chosen rank with α, β and Γ and its forecasts, and the Engle-Granger test.',
    uses: ['statsmodels.tsa.vector_ar.var_model.VAR (select_order, fit, test_causality, test_inst_causality, test_whiteness, test_normality, irf, fevd, forecast_interval)',
      'statsmodels.tsa.vector_ar.irf.IRAnalysis (stderr, cum_effect_stderr, errband_mc)', 'statsmodels.tsa.vector_ar.vecm.coint_johansen, select_coint_rank, VECM',
      'statsmodels.tsa.stattools.adfuller, kpss, coint', 'pandas.infer_freq'],
    launch: {
      lead: 'Two or more series observed at the same times. A date column as X, Time ID gives a date axis and the dates of the forecasts; Exogenous columns enter every equation as regressors. The order of Y is the Cholesky ordering of the orthogonalized impulse responses.',
      roles: [
        { key: 'y', label: 'Y, Time Series', min: 2, types: ['continuous'], hint: 'required: two or more continuous',
          help: 'The series modelled together, observed at the same times. Their order is the Cholesky ordering of the orthogonalized impulse responses and the variance decomposition (Cholesky Ordering… changes it). The analysis runs over the span where every series has a value; a missing value inside it is filled by linear interpolation.' },
        { key: 'time', label: 'X, Time ID', max: 1, numeric: true, hint: 'optional: a date or a time step', info: 'p:multits:timeid',
          help: 'Orders the rows and labels the time axis. A date column gives the calendar frequency and the dates of the forecasts; dates missing from the calendar are inserted and filled. A numeric Time ID continues its step; without one the row number is the time.' },
        { key: 'exog', label: 'Exogenous', numeric: true, types: ['continuous'], hint: 'optional continuous: regressors', info: 'p:multits:exog',
          help: 'Continuous columns that enter every equation as regressors, not modelled themselves. The forecasts take their future values from the rows after the series (the Y columns empty there), holding the last one beyond them. Transform > Difference leaves them as they are.' },
        { key: 'by', label: 'By', hint: 'optional',
          help: 'A separate report of the rows of each level (each combination of levels, with several By columns). Rows with a missing By value are left out.' },
      ],
      options: [
        { key: 'maxlags', label: 'Maximum Lag for Selection', type: 'number', value: 8,
          help: 'The largest lag of the Lag Order Selection table, 1 to 48 (8 by default): VARs of every lag up to it are fitted on the same observations and the criterion picks one. Lowered when the series are too short for it; Maximum Lag…, in the red triangle, changes it later.' },
        { key: 'forecast', label: 'Forecast Periods', type: 'number', value: 12,
          help: 'How many periods after the last observation the VAR (and the VECM) forecasts, 1 to 500; 12 by default.' },
        { key: 'horizon', label: 'IRF Horizon', type: 'number', value: 10,
          help: 'How many periods after a shock the impulse responses, and the variance decomposition, run: 1 to 100, 10 by default.' },
        { key: 'trend', label: 'Trend', type: 'select', value: 'c', choices: TRENDS,
          help: 'The deterministic terms of every equation: Constant (the default, for series that vary about a level), Constant and Linear Trend (for series that drift), or None. The stationarity tests and the Engle-Granger test take the same terms.' },
      ],
      validate: (spec) => {
        const o = spec.options || {};
        const y = new Set(spec.roles.y || []);
        if ((spec.roles.exog || []).some((id) => y.has(id))) return 'A column cannot be both Y and Exogenous';
        if ((spec.roles.time || []).some((id) => y.has(id))) return 'The Time ID cannot also be a Y';
        if (o.maxlags != null && !(Number.isInteger(o.maxlags) && o.maxlags >= 1 && o.maxlags <= 48)) return 'Maximum Lag for Selection: a whole number from 1 to 48';
        if (o.forecast != null && !(Number.isInteger(o.forecast) && o.forecast >= 1 && o.forecast <= 500)) return 'Forecast Periods: a whole number from 1 to 500';
        if (o.horizon != null && !(Number.isInteger(o.horizon) && o.horizon >= 1 && o.horizon <= 100)) return 'IRF Horizon: a whole number from 1 to 100';
        return null;
      },
    },
    title: () => 'Multivariate Time Series',
    triangle: (ctx) => topMenu(ctx),
    async render(ctx) {
      if (ctx.roles('y').length < 2) { ctx.container.append(ctx.warn('Multivariate Time Series needs two or more Y columns: relaunch the analysis.')); return; }
      const base = basePayload(ctx);
      const box = ctx.top;
      const S = await ctx.call('multits.series', { ...base, trend: trendOf(ctx), alpha: ctx.alpha });
      if (S.error) { box.add(ctx.warn(S.error)); return; }
      S.tkind = timeKind(S);
      for (const n of S.notes || []) box.add(ctx.note(n));
      // Each part on its own: an error in one shows there, the rest still draws.
      const part = async (fn) => { try { return await fn(); } catch (e) { console.error(e); box.add(ctx.error(e)); return null; } };
      await part(() => seriesPart(ctx, S, box));
      const p = await part(() => lagPart(ctx, base, box));
      if (p == null) return;
      await part(() => varPart(ctx, base, p, box));
      if (ctx.opt('granger', true)) await part(() => grangerPart(ctx, base, p, box));
      if (ctx.opt('irf', true)) await part(() => irfPart(ctx, base, p, box));
      if (ctx.opt('fevd', true)) await part(() => fevdPart(ctx, base, p, box));
      if (ctx.opt('fc', true)) await part(() => forecastPart(ctx, base, S, p, box));
      if (ctx.opt('coint', false)) await part(() => cointPart(ctx, base, S, p, box));
    },
  });

  // For the tests.
  SM.multits = Object.freeze({ groupRows, gridCells, stackDomains, orderNames });
}(typeof self !== 'undefined' ? self : this));
