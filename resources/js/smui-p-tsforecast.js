/* ==========================================================================
   SMUI.HTML: ANALYZE > SPECIALIZED MODELING > TIME SERIES FORECAST

   JMP's Time Series Forecast for many series: several Y columns, or one
   stacked with grouping columns (each level a series). For every series
   the state space smoothing models ETS(error, trend, seasonal) of the
   model set are fitted (statsmodels' ETSModel), the best is chosen by AICc,
   AIC or BIC, or by its forecasts of held-back values (Holdback RMSE, MAE or
   MAPE), and it forecasts the next periods with prediction intervals.

   The report: Model Summary (the chosen model and its criteria, a row per
   series; a click opens the series' report), Forecasts (every series'
   forecasts and limits), and a report for each series opened: its Model
   Selection (every candidate's criteria), the chosen model's summary,
   parameters and graphs (drawn as the Time Series platform draws them,
   SM.timeseries.draw) with their code. Save Results makes a table of the
   actual values, the one-step-ahead predictions and the forecasts.

   The backend is resources/py/smui/tsforecast.py; a series' own report is
   timeseries.ets on the series' rows, so its numbers are the Time Series
   platform's State Space Smoothing.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const MORE = { label: 'Time Series Forecast', id: 'help-p-tsforecast' };
  const D = () => SM.timeseries.draw;
  const int = (v, d = 0) => (v == null || v === '' || !Number.isFinite(Number(v)) ? d : Math.round(Number(v)));

  const CRITERIA = [['aicc', 'AICc'], ['aic', 'AIC'], ['bic', 'BIC'], ['rmse', 'Holdback RMSE'], ['mae', 'Holdback MAE'], ['mape', 'Holdback MAPE']];
  const CRIT_LABEL = Object.fromEntries(CRITERIA);
  const HOLD = new Set(['rmse', 'mae', 'mape']);
  const SETS = [['recommended', 'Recommended: up to 15 models'], ['all', 'All 30 models'], ['additive', 'Additive only: up to 6 models']];
  const SET_NAME = { recommended: 'recommended (up to 15)', all: 'full (30)', additive: 'additive (up to 6)' };
  const DATE_KINDS = new Set(['date', 'datetime']);

  const horizon = (ctx) => Math.max(1, Math.min(1000, int(ctx.opt('forecast', 12), 12)));
  const criterionOf = (ctx) => (CRIT_LABEL[ctx.opt('criterion', 'aicc')] ? ctx.opt('criterion', 'aicc') : 'aicc');
  const holdOf = (ctx) => (HOLD.has(criterionOf(ctx)) ? Math.max(1, int(ctx.opt('holdback', null), horizon(ctx))) : 0);
  const levelOf = (ctx) => { const v = Number(ctx.opt('level', 0.95)); return v > 0 && v < 1 ? v : 0.95; };
  const setOf = (ctx) => (SETS.some(([k]) => k === ctx.opt('models', 'recommended')) ? ctx.opt('models', 'recommended') : 'recommended');
  const labelOf = (c, v) => (SM.grid && SM.grid.cellText ? SM.grid.cellText(c, v) : String(v));
  const isMissing = (v) => v == null || (typeof v === 'number' && Number.isNaN(v));

  /* The series: each Y column over the rows of the By group, or with grouping
     columns each combination of their levels (in their value order), with
     the excluded rows among them, which count as missing values in their
     place. where: the filters of the code (the By group's, the level's). */
  function seriesList(ctx) {
    const t = ctx.table;
    const { rows, excluded } = SM.timeseries.groupRows(ctx);
    const all = rows || Array.from({ length: t.nrows }, (_, i) => i);
    const exc = new Set(excluded);
    const ys = ctx.roles('y');
    const gs = ctx.roles('group');
    const byWhere = (ctx.where || []).map((w) => ({ column: w.column, value: w.value }));
    if (!gs.length) return ys.map((y) => ({ key: y.name, label: y.name, y: y.name, rows, excluded: excluded.slice(), where: byWhere }));
    const groups = new Map();
    for (const r of all) {
      const vals = gs.map((c) => c.values[r]);
      if (vals.some(isMissing)) continue;
      const k = JSON.stringify(vals);
      if (!groups.has(k)) groups.set(k, { vals, rows: [] });
      groups.get(k).rows.push(r);
    }
    const order = gs.map((c) => new Map(t.levels(c.id).map((v, i) => [v, i])));
    const sorted = [...groups.values()].sort((a, b) => {
      for (let j = 0; j < gs.length; j++) { const d = (order[j].get(a.vals[j]) ?? 0) - (order[j].get(b.vals[j]) ?? 0); if (d) return d; }
      return 0;
    });
    const out = [];
    for (const y of ys) {
      for (const g of sorted) {
        const lab = g.vals.map((v, j) => labelOf(gs[j], v)).join(', ');
        out.push({ key: ys.length > 1 ? `${y.name} ${JSON.stringify(g.vals)}` : JSON.stringify(g.vals), label: ys.length > 1 ? `${y.name}: ${lab}` : lab, y: y.name,
          rows: g.rows, excluded: g.rows.filter((r) => exc.has(r)), where: [...byWhere, ...gs.map((c, j) => ({ column: c.name, value: g.vals[j] }))] });
      }
    }
    return out;
  }

  /* The fit of every series, with its progress in the report. */
  async function fitAll(ctx, list) {
    const payload = { series: list, time: ctx.name('time'), h: horizon(ctx), holdback: holdOf(ctx), criterion: criterionOf(ctx), models: setOf(ctx),
      period: int(ctx.opt('period', null), 0), level: levelOf(ctx) };
    if (ctx.headless) return ctx.call('tsforecast.fit', payload);
    const who = `Time Series Forecast${ctx.byLabel ? ` (${ctx.byLabel})` : ''}`;
    const note = el('p', { class: 'sm-ob-note', role: 'status', text: `${who}: fitting ${list.length} series…` });
    ctx.container.append(note);
    const off = SM.engine.on('progress', (p) => {
      if (!p || p.what !== 'tsforecast') return;
      const text = `${who}: ${p.done} of ${p.total} fits (${list.length} series)…`;
      note.textContent = text;
      if (ctx.report && ctx.report.noteEl) ctx.report.noteEl.textContent = text;
    });
    try { return await ctx.call('tsforecast.fit', payload); } finally { off(); note.remove(); }
  }

  const tText = (s, t) => (DATE_KINDS.has(s.kind) ? SM.io.formatDate(t, s.t.some((v) => v != null && v % 86400000 !== 0) ? 'datetime' : 'date') : fmt(t));

  async function render(ctx) {
    const list = seriesList(ctx);
    if (!list.length) { ctx.container.append(ctx.warn('No series: cast one or more Y columns (and grouping columns for stacked data).')); return; }
    const R = await fitAll(ctx, list);
    if (R.error) { ctx.container.append(ctx.warn(R.error)); return; }
    ctx.tsf = R;   // for the red triangle's Save Results and Show All Series Reports
    const held = R.holdback > 0;
    const crit = R.criterion;
    // Model Summary: a row per series
    const open = new Set(ctx.opt('open', null) || (R.series[0] ? [R.series[0].key] : []));
    const ms = ctx.outline('Model Summary', { info: 'p:tsforecast' });
    const rows = R.series.map((s) => (s.error ? { key: s.key, series: s.label, error: s.error }
      : { key: s.key, series: s.label, n: s.n, model: s.name.replace('State Space Smoothing ', ''), crit: s.criterion_value, aicc: s.aicc, aic: s.aic, bic: s.bic, sigma: s.sigma, mape: s.mape, mae: s.mae,
        hb_rmse: s.hb_rmse, hb_mae: s.hb_mae, hb_mape: s.hb_mape, fitted: `${s.n_ok} of ${s.n_models}`, shown: open.has(s.key) ? '▸ report below' : '' }));
    const cols = [{ key: 'series', label: 'Series', fmt: 'text' }, { key: 'n', label: 'N', fmt: 'int' }, { key: 'model', label: 'Model', fmt: 'text' }, { key: 'crit', label: CRIT_LABEL[crit] },
      ...(HOLD.has(crit) ? [] : ['aicc', 'aic', 'bic'].filter((k) => k !== crit).map((k) => ({ key: k, label: CRIT_LABEL[k] }))),
      { key: 'sigma', label: 'Sigma' }, { key: 'mape', label: 'MAPE' }, { key: 'mae', label: 'MAE' },
      ...(held ? ['hb_rmse', 'hb_mae', 'hb_mape'].filter((k) => k !== `hb_${crit}`).map((k) => ({ key: k, label: CRIT_LABEL[k.slice(3)] })) : []),
      { key: 'fitted', label: 'Models Fitted', fmt: 'text' }, { key: 'error', label: '', fmt: 'text', hidden: !rows.some((r) => r.error) }, { key: 'shown', label: '', fmt: 'text' }];
    ms.add(ctx.rt({ columns: cols, rows }, { sortable: true, name: 'Model Summary', onRow: (row) => {
      const cur = new Set(ctx.opt('open', null) || (R.series[0] ? [R.series[0].key] : []));
      if (cur.has(row.key)) cur.delete(row.key); else cur.add(row.key);
      ctx.set('open', [...cur]);
    } }));
    ms.add(ctx.note(`${R.series.length} series. The candidates of each: the models of the ${SET_NAME[R.models]} set (${setDescription(R.models)}) that the series allows (multiplicative parts need every value above zero, a seasonal part two periods and four values more), fitted by maximum likelihood (statsmodels' ETSModel). The best: ${held ? `the one whose forecasts of the last ${R.holdback} values, fitted on the values before them, have the least ${CRIT_LABEL[crit].replace('Holdback ', '')}; it is then fitted again on every value for the forecasts` : `the one with the least ${CRIT_LABEL[crit]}, statsmodels' (Nparm counts the smoothing parameters, the starting states and σ)`}. Click a row to show or hide that series' report.`));
    ms.add(ctx.code(R.code));
    // Forecasts: every series
    const fo = ctx.outline('Forecasts', { info: 'p:tsforecast', closed: R.series.length > 8 });
    const frows = [];
    for (const s of R.series) {
      if (s.error || !s.forecast) continue;
      s.forecast.t.forEach((t, i) => frows.push({ series: s.label, time: tText(s, t), mean: s.forecast.mean[i], lower: s.forecast.lower[i], upper: s.forecast.upper[i] }));
    }
    const lv = fmt(100 * R.level);
    fo.add(ctx.rt({ columns: [{ key: 'series', label: 'Series', fmt: 'text' }, { key: 'time', label: ctx.name('time') || 'Row', fmt: 'text' }, { key: 'mean', label: 'Forecast' },
      { key: 'lower', label: `Lower ${lv}%` }, { key: 'upper', label: `Upper ${lv}%` }], rows: frows }, { sortable: false, name: 'Forecasts', maxRows: 300 }),
    ctx.note(`The next ${R.h} periods of every series from its chosen model fitted on every value, with ${lv}% prediction intervals (simulated for the multiplicative models, a fixed seed). The code under Model Summary prints them.`));
    // the series opened
    for (const [i, s] of R.series.entries()) if (open.has(s.key)) await seriesReport(ctx, s, list.find((x) => x.key === s.key), R, i);
  }

  function setDescription(k) {
    return { recommended: 'errors A or M, trends N, A or Ad, seasonality N, A or M, without additive errors with multiplicative seasonality: the forecast package\'s automatic set',
      all: 'errors A or M, trends N, A, Ad, M or Md, seasonality N, A or M', additive: 'additive errors, trends N, A or Ad, seasonality N or A' }[k];
  }

  /* A series' own report: its model selection, and the chosen model fitted
     as the Time Series platform fits it (timeseries.ets), with its graphs. */
  async function seriesReport(ctx, s, sp, R, i) {
    const ob = ctx.outline(`Series: ${s.label}`, { key: `tsf:${s.key}`, info: 'p:tsforecast:series', menu: () => [
      { label: 'Hide Series Report', action: () => { const cur = new Set(ctx.opt('open', null) || []); cur.delete(s.key); ctx.set('open', [...cur]); } },
      { label: 'Save Results for This Series', disabled: !!s.error, action: () => saveResults(ctx, R, [s]) },
    ] });
    if (s.error) { ob.add(ctx.warn(s.error)); return; }
    const d = D();
    const base = { y: s.y, time: ctx.name('time'), rows: sp.rows, excluded: sp.excluded, nlags: 25, where: sp.where };
    const S = await ctx.call('timeseries.series', base);
    if (S.error) { ob.add(ctx.warn(S.error)); return; }
    S.rowsLinked = S.rows.map((r) => (r == null ? -1 : r));
    d.withX(S);
    const spec = { ...s.spec, kind: 'ets', level: R.level, id: 1 + (i % 10) };
    const args = { error: s.spec.error, trend: s.spec.trend, seasonal: s.spec.seasonal, s: s.spec.s || 0, level: R.level, h: R.h, maxiter: 1000 };
    const r = await ctx.call('timeseries.ets', { ...base, ...args });
    const held = R.holdback > 0;
    const rh = held ? await ctx.call('timeseries.ets', { ...base, ...args, h: R.holdback, holdback: R.holdback, season: s.period || 1 }) : null;
    // the model selection
    const sel = ctx.outline('Model Selection', { parent: ob, key: `tsf:${s.key}:sel`, closed: true });
    const crow = s.candidates.map((c) => ({ model: c.model, nparm: c.nparm, m2ll: c.m2ll, aic: c.aic, aicc: c.aicc, bic: c.bic, hb_rmse: c.hb_rmse, hb_mae: c.hb_mae, hb_mape: c.hb_mape,
      mark: c.best ? '★ chosen' : c.fail || '' }));
    sel.add(ctx.rt({ columns: [{ key: 'model', label: 'Model', fmt: 'text' }, { key: 'nparm', label: 'Nparm', fmt: 'int' }, { key: 'm2ll', label: '−2LogLikelihood' },
      { key: 'aic', label: 'AIC' }, { key: 'aicc', label: 'AICc' }, { key: 'bic', label: 'BIC' },
      ...(held ? [{ key: 'hb_rmse', label: 'Holdback RMSE' }, { key: 'hb_mae', label: 'Holdback MAE' }, { key: 'hb_mape', label: 'Holdback MAPE' }] : []),
      { key: 'mark', label: '', fmt: 'text' }], rows: crow }, { sortable: false, name: `${s.label} model selection` }),
    ctx.note(held ? `Every candidate fitted on the first ${s.n_slots - R.holdback} values; best first by ${CRIT_LABEL[R.criterion]}, the forecasts of the last ${R.holdback}. AIC, AICc and BIC are those fits'.`
      : `Best first by ${CRIT_LABEL[R.criterion]}.`));
    if (!r || r.error) { ob.add(ctx.warn(r ? r.error : 'no result')); return; }
    const col = { name: s.y };
    const name = r.name.replace('State Space Smoothing ', '');
    const sum = ctx.outline('Model Summary', { parent: ob, key: `tsf:${s.key}:sum` });
    sum.add(ctx.kv([['Model', name, 'text'], ...r.summary.map(([label, v, f]) => [label, v, f || 'num'])]));
    const pe = ctx.outline('Parameter Estimates', { parent: ob, key: `tsf:${s.key}:pe` });
    pe.add(ctx.rt({ columns: d.PARAM_COLS.ets(), rows: r.params.rows }, { sortable: false, name: `${s.label} parameter estimates` }));
    ob.add(ctx.row(sum.el, pe.el));
    for (const n of r.notes || []) ob.add(ctx.note(n));
    const fc = ctx.outline('Forecast', { parent: ob, key: `tsf:${s.key}:fc` });
    fc.add(...d.forecastPlot(ctx, col, S, spec, r, r.name, `${s.label} forecast`, (r.plot_code || {}).forecast));
    if (r.forecast && r.forecast.t.length) fc.add(ctx.note(`${r.forecast.t.length} periods ahead, from ${d.tLabel(S, r.forecast.t[0])} to ${d.tLabel(S, r.forecast.t[r.forecast.t.length - 1])}, with ${fmt(100 * r.level)}% prediction intervals; to the left of the dotted line the one-step-ahead forecasts.`));
    if (rh && !rh.error) {
      const ho = ctx.outline('Forecast on Holdback', { parent: ob, key: `tsf:${s.key}:hb`, info: 'p:timeseries:holdback' });
      ho.add(...d.forecastPlot(ctx, col, S, spec, rh, rh.name, `${s.label} forecast on the holdback`, (rh.plot_code || {}).forecast));
      const hb = rh.holdback || {};
      ho.add(ctx.kv([['RMSE', hb.rmse], ['MSE', hb.mse], ['MAPE', hb.mape], ['MAE', hb.mae], ['Mean Error', hb.me], ['MASE', hb.mase], ['N', hb.n, 'int']], { caption: 'Holdback Statistics' }),
        ctx.note(`The chosen model fitted on the first ${rh.n} values and its forecasts of the last ${R.holdback} (shaded), from which it was chosen.`), ctx.code(rh.code));
    }
    const eo = ctx.outline('One-Step-Ahead Forecasting Errors', { parent: ob, key: `tsf:${s.key}:err` });
    const w = d.plotWidth(ctx, 620);
    eo.add(ctx.plot([{ type: 'scatter', mode: 'markers', x: S.x.slice(0, r.n), y: r.resid, rows: S.rowsLinked.slice(0, r.n), name: 'Residual', marker: { size: 5, color: d.colorOf(spec.id) } }],
      { xaxis: d.xAxis(S), yaxis: { title: { text: 'Residual' }, zeroline: true }, shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: SM.util.themeColors().muted, width: 1 } }] },
    { width: w, height: 220, title: `${r.name} residuals` }), d.graphCode(ctx, (r.plot_code || {}).resid, { size: [w, 220], color: d.colorOf(spec.id) }));
    ob.add(ctx.code(r.code));
  }

  /* Save Results: a table of every series' actual values, one-step-ahead
     predictions (a missing value's too, wherever the model gives one) and
     forecasts with their limits, stacked, with a Set column. */
  function saveResults(ctx, R, only = null) {
    const list = (only || R.series).filter((s) => !s.error && s.forecast);
    if (!list.length) { SM.ui.toast('No series with forecasts to save'); return; }
    const lv = fmt(R.level);
    const cols = { series: [], time: [], actual: [], pred: [], lower: [], upper: [], set: [] };
    const nan = (v) => (v == null ? NaN : v);
    for (const s of list) {
      s.t.forEach((t, i) => {
        cols.series.push(s.label); cols.time.push(t); cols.actual.push(nan(s.values[i])); cols.pred.push(nan(s.fitted[i]));
        cols.lower.push(nan(s.fit_lo[i])); cols.upper.push(nan(s.fit_hi[i])); cols.set.push('History');
      });
      s.forecast.t.forEach((t, i) => {
        cols.series.push(s.label); cols.time.push(t); cols.actual.push(NaN); cols.pred.push(nan(s.forecast.mean[i]));
        cols.lower.push(nan(s.forecast.lower[i])); cols.upper.push(nan(s.forecast.upper[i])); cols.set.push('Forecast');
      });
    }
    const tcol = ctx.role('time');
    const dated = tcol && tcol.format && DATE_KINDS.has(tcol.format.kind);
    const t = new SM.Table({ name: `${ctx.report.title} results`, source: `saved from ${ctx.report.title}`,
      notes: `Each series' values and its chosen model's one-step-ahead predictions (Set History), then its ${R.h} forecasts (Set Forecast), with ${fmt(100 * R.level)}% prediction limits.`,
      columns: [
        { name: 'Series', dataType: 'character', values: cols.series },
        { name: ctx.name('time') || 'Row', dataType: 'numeric', values: cols.time, format: dated ? { kind: tcol.format.kind } : null },
        { name: 'Actual', dataType: 'numeric', values: cols.actual },
        { name: 'Predicted', dataType: 'numeric', values: cols.pred },
        { name: `Lower CL (${lv})`, dataType: 'numeric', values: cols.lower },
        { name: `Upper CL (${lv})`, dataType: 'numeric', values: cols.upper },
        { name: 'Set', dataType: 'character', values: cols.set },
      ] });
    SM.app.addTable(t);
  }

  async function numberDialog(ctx, { title, label, key, value, min, max, help, lead }) {
    const v = await SM.ui.form({ title, lead, info: 'p:tsforecast', fields: [{ key: 'n', label, type: 'number', value, help }],
      validate: (x) => (x.n != null && x.n >= min && x.n <= max ? null : `${label}: from ${min} to ${max}`) });
    if (v) ctx.set(key, v.n);
  }

  /* ---- topics for the (i) ------------------------------------------------------------------------ */
  const topics = {
    'p:tsforecast': {
      kicker: 'Analyze > Specialized Modeling', title: 'Time Series Forecast',
      lead: 'Forecasts for many series at once, as JMP\'s Time Series Forecast makes them: for each series the state space smoothing models ETS(error, trend, seasonal) of Hyndman et al. (2008) are fitted by maximum likelihood (statsmodels\' ETSModel), the best is chosen by AICc, AIC or BIC or by its forecasts of held-back values, and it forecasts the next periods with prediction intervals.',
      sections: [
        { heading: 'Roles', choices: [['Y, Time Series', 'The series: each column is one, or one column stacked with Grouping.'], ['Grouping', 'Columns whose levels (each combination) identify the series of stacked data, one series per level, labelled with the columns\' value labels.'],
          ['Time', 'Orders the rows and labels the time axis; a date column gives the calendar frequency, the seasonal period and the forecast dates.'], ['By', 'A report for each level.']] },
        { heading: 'In the report', choices: [['Model Summary', 'a row per series: the chosen model, its criterion and fit statistics; click a row to show or hide that series\' report'],
          ['Forecasts', 'every series\' forecasts with their limits'], ['Series: …', 'a series\' Model Selection (every candidate), the chosen model\'s summary, parameters, forecast graph (and with a holdback criterion its forecasts of the held-back values) and one-step errors, with their code'],
          ['Save Results', 'in the red triangle: a table of every series\' values, one-step-ahead predictions and forecasts with their limits, and a Set column']] },
        { heading: 'Differences from JMP', list: ['JMP chooses by AIC or BIC, or by RMSE, MSE or MAE on a holdback; here AICc (the default, Hyndman et al.\'s choice and the Time Series platform\'s), AIC, BIC, or the holdback RMSE, MAE or MAPE.',
          'The model sets are the forecast package\'s recommended one (the default), all 30 models, or the additive ones; JMP chooses the components in its Modeling Specifications.',
          'Missing values are filled by linear interpolation for the fits, as in the Time Series platform, not by JMP\'s imputation choices.'] },
      ],
      more: MORE,
    },
    'p:tsforecast:series': {
      kicker: 'Time Series Forecast', title: 'A series\' report',
      lead: 'The chosen model of the series, fitted as the Time Series platform\'s State Space Smoothing fits it (timeseries.ets): Model Selection lists every candidate of the model set with its criteria, best first; then the chosen model\'s Model Summary and Parameter Estimates, its forecast graph, with a holdback criterion its forecasts of the held-back values (shaded) with their statistics, and its one-step-ahead forecasting errors, each with its Python code.',
      more: MORE,
    },
  };

  const HELP = {
    y: 'The series to forecast, continuous: each column is a series, or with Grouping one column holds every series stacked. Required, one or more.',
    group: 'Columns whose values say which series a row belongs to, for stacked data (a store, a product): each level, or each combination of levels, is a series of its own, forecast separately. Its value labels name the series. Optional.',
    time: 'Orders the rows and labels the time axis. A date column gives the calendar frequency, the seasonal period and the dates of the forecasts; with Grouping, each series\' dates must not repeat. Without one the row order is the time.',
    by: 'A separate report of the rows of each level (each combination, with several By columns).',
  };

  SM.platforms.register({
    id: 'tsforecast', label: 'Time Series Forecast', menu: 'Analyze/Specialized Modeling', order: 21, info: 'p:tsforecast', topics,
    about: 'Forecasts for many series at once (several Y columns, or one stacked with grouping columns): for each series the state space smoothing (ETS) models of a model set are fitted, the best is chosen by AICc, AIC or BIC or by the RMSE, MAE or MAPE of its forecasts of held-back values, and it forecasts the next periods with prediction intervals; a summary table of the chosen models and their criteria, a table of every forecast, a report for each series on demand (its candidates, the chosen model\'s parameters, graphs and code), and Save Results, a table of the values, predictions and forecasts with their limits.',
    uses: ['statsmodels.tsa.exponential_smoothing.ets.ETSModel', 'pandas.infer_freq'],
    launch: {
      lead: 'Choose the series: several Y columns, or one stacked with Grouping columns. A date column as Time gives the calendar, the seasonal period and the forecast dates.',
      roles: [
        { key: 'y', label: 'Y, Time Series', min: 1, types: ['continuous'], hint: 'required: one or more continuous', help: HELP.y },
        { key: 'group', label: 'Grouping', hint: 'optional: the series of stacked data', help: HELP.group },
        { key: 'time', label: 'Time', max: 1, numeric: true, hint: 'optional: a date or a time step', help: HELP.time },
        { key: 'by', label: 'By', hint: 'optional', help: HELP.by },
      ],
      options: [
        { key: 'forecast', label: 'Forecast Periods', type: 'number', value: 12, help: 'How many periods after the end of each series are forecast (NAhead), 1 to 1000; 12 by default.' },
        { key: 'criterion', label: 'Model Selection', type: 'select', value: 'aicc', choices: CRITERIA,
          help: 'How the best model of each series is chosen: AICc (the default), AIC or BIC, the information criteria of the fits to every value; or Holdback RMSE, MAE or MAPE, the errors of each candidate\'s forecasts of the last values, fitted on the values before them (JMP\'s Forecasting Performance).' },
        { key: 'holdback', label: 'Holdback (empty: the Forecast Periods)', type: 'number', value: '',
          help: 'With a holdback criterion: how many values at the end of each series are held back to compare the candidates\' forecasts (NHoldback); empty takes the Forecast Periods. Not used with AICc, AIC or BIC.' },
        { key: 'models', label: 'Models', type: 'select', value: 'recommended', choices: SETS,
          help: 'The candidates of each series: Recommended (the default: errors A or M, trends N, A or Ad, seasonality N, A or M, without additive errors with multiplicative seasonality, the forecast package\'s automatic set), All 30 (the multiplicative trends too), or the additive ones. A series gets those it allows: multiplicative parts need every value above zero.' },
        { key: 'period', label: 'Seasonal Period (empty: from the Time ID)', type: 'number', value: '',
          help: 'The observations per season of the seasonal candidates: empty takes the Time\'s calendar (12 for monthly data); without one only non-seasonal models are fitted. At least 2.' },
        { key: 'level', label: 'Forecast Interval Level', type: 'number', value: 0.95, help: 'The coverage of the prediction intervals, between 0 and 1; 0.95 by default.' },
      ],
      validate: (spec) => {
        const o = spec.options || {};
        if (o.forecast != null && !(o.forecast >= 1 && o.forecast <= 1000)) return 'Forecast Periods: from 1 to 1000';
        if (o.holdback != null && o.holdback !== '' && !(o.holdback >= 1)) return 'Holdback: at least 1, or empty';
        if (o.period != null && o.period !== '' && !(o.period >= 2)) return 'Seasonal Period: at least 2, or empty';
        if (o.level != null && !(o.level > 0 && o.level < 1)) return 'Forecast Interval Level: between 0 and 1';
        return null;
      },
    },
    title: () => 'Time Series Forecast',
    triangle(ctx) {
      return [
        { label: 'Model Selection', submenu: () => CRITERIA.map(([k, label]) => ({ label, checked: criterionOf(ctx) === k, action: () => ctx.set('criterion', k) })) },
        { label: 'Models', submenu: () => SETS.map(([k, label]) => ({ label, checked: setOf(ctx) === k, action: () => ctx.set('models', k) })) },
        { label: 'Set Forecast Periods…', action: () => numberDialog(ctx, { title: 'Set Forecast Periods', label: 'Forecast Periods', key: 'forecast', value: horizon(ctx), min: 1, max: 1000,
          help: 'How many periods after the end of each series are forecast (NAhead), 1 to 1000.' }) },
        { label: 'Set Holdback…', disabled: !HOLD.has(criterionOf(ctx)), action: () => numberDialog(ctx, { title: 'Set Holdback', label: 'Values held back', key: 'holdback', value: holdOf(ctx), min: 1, max: 1000,
          help: 'How many values at the end of each series are held back to compare the candidates\' forecasts (NHoldback), with a holdback criterion.' }) },
        { label: 'Set Forecast Interval Level…', action: async () => { const v = await SM.ui.form({ title: 'Set Forecast Interval Level', info: 'p:tsforecast', fields: [{ key: 'n', label: 'Level', type: 'number', value: levelOf(ctx),
          help: 'The coverage of the prediction intervals, between 0 and 1 (0.95 by default).' }], validate: (x) => (x.n > 0 && x.n < 1 ? null : 'Level: between 0 and 1') }); if (v) ctx.set('level', v.n); } },
        { separator: true },
        { label: 'Show All Series Reports', disabled: !ctx.tsf, action: () => ctx.set('open', ctx.tsf.series.map((s) => s.key)) },
        { label: 'Hide All Series Reports', action: () => ctx.set('open', []) },
        { label: 'Save Results', disabled: !ctx.tsf, action: () => saveResults(ctx, ctx.tsf) },
      ];
    },
    async render(ctx) {
      await render(ctx);
    },
  });

  /* ---- the example: simulated here, never real data ---------------------------------------------------------------- */
  SM.io.addExample('stores', {
    label: 'Store sales (4 stores × 72 months, stacked): many series to forecast',
    about: 'Simulated monthly sales of four stores from 2019, one column stacked with a store code (value labels North, South, East and West): North grows 0.5% a month with a seasonal swing that grows with it; South has an additive season and a damped trend; East wanders like a random walk; West is flat with noise. For Time Series Forecast (Grouping: store) and Time Series (By store).',
    make() {
      const r = SM.util.rng('stores');
      const n = 72;
      const store = [], month = [], sales = [];
      let east = 80, damp = 0;
      for (let s = 1; s <= 4; s++) {
        for (let t = 0; t < n; t++) {
          const season = Math.sin(2 * Math.PI * (t % 12) / 12);
          let v;
          if (s === 1) v = 120 * 1.005 ** t * (1 + 0.12 * season) * Math.exp(r.normal(0, 0.03));
          else if (s === 2) { damp = 0.9 * damp + 0.6; v = 90 + damp * (1 - 0.97 ** t) * 8 + 9 * season + r.normal(0, 2.5); }
          else if (s === 3) { east += r.normal(0.2, 2); v = east; }
          else v = 60 + r.normal(0, 3);
          store.push(s); month.push(Date.UTC(2019, t, 1)); sales.push(Math.round(100 * v) / 100);
        }
      }
      return new SM.Table({ name: 'Store sales', source: 'simulated', columns: [
        { name: 'store', dataType: 'numeric', modelingType: 'nominal', values: store, valueLabels: { 1: 'North', 2: 'South', 3: 'East', 4: 'West' } },
        { name: 'month', dataType: 'numeric', format: { kind: 'date' }, values: month },
        { name: 'sales', dataType: 'numeric', values: sales },
      ] });
    },
  });

  // For the tests.
  SM.tsforecast = Object.freeze({ seriesList });
}(typeof self !== 'undefined' ? self : this));
