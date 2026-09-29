/* ==========================================================================
   SMUI.HTML: ANALYZE > RELIABILITY AND SURVIVAL, AND
   ANALYZE > SPECIALIZED MODELING > FIT CURVE AND NONLINEAR

   Reliability and Survival:
     Life Distribution          one time column, with right censoring: the
                                nonparametric estimate on probability paper,
                                nine distributions fitted, compared, and a
                                probability and quantile calculator
     Survival                   Kaplan-Meier curves per group, their summaries,
                                the tests between groups, linearizing plots
                                and Exponential, Weibull and Lognormal fits
     Fit Parametric Survival    accelerated failure time regression
     Fit Proportional Hazards   Cox regression with risk ratios
   Specialized Modeling:
     Fit Curve                  a library of named nonlinear models, per group
     Nonlinear                  a typed model, least squares

   The statistics are resources/py/smui/survival.py and nonlinear.py.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt, qnorm, PALETTE } = SM.util;

  const FIT_COLORS = ['#b0413e', '#3a7d44', '#6c5b7b', '#c0a000', '#1f9e89', '#8c564b', '#e377c2', '#17becf', '#7f7f7f', '#2f6690'];
  const pct = (a) => `${fmt(100 * (1 - a))}%`;

  /* A number from Python: null for missing, ±Infinity from their names. */
  const num = (v) => (v == null ? null : v === 'Infinity' ? Infinity : v === '-Infinity' ? -Infinity : v);
  const nums = (a) => (a || []).map(num);
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);

  function rgba(hex, a) {
    const h = String(hex).replace('#', '');
    const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  }

  /* Numbers typed as a list: "1, 2.5; 10" */
  function parseList(text) {
    return String(text ?? '').split(/[\s,;]+/).map((s) => s.trim().replace(/−/g, '-')).filter(Boolean).map(Number).filter(Number.isFinite);
  }

  const levelLabel = (col, v) => (v == null ? '' : col ? SM.grid.cellText(col, v) : String(v));

  /* A plot's width: w, or less in a narrow report (a phone). */
  function fitWidth(ctx, w) {
    const cw = ctx.report && ctx.report.body ? ctx.report.body.clientWidth : 0;
    return cw > 200 ? Math.max(290, Math.min(w, cw - 48)) : w;
  }

  /* ---- the graphs as matplotlib code -------------------------------------------------
     Under each graph, Python that draws it with matplotlib from a CSV export
     of the table (the notebook runs it): the report's rows, the light theme's
     colours, the graph's size at 100 pixels an inch. The graphs whose numbers
     one call makes get their code from it (plot_code, from survival.py and
     nonlinear.py, with the graph's options and size in the call's plot);
     Fit Curve's plots, which show several fits, are put together here from
     each fit's fragment (res.plot: the model, and the function that fits it
     to a group's rows). */
  const J = JSON.stringify;
  const pyNum = (v) => (Number.isFinite(v) ? String(v) : Number.isNaN(v) ? 'float("nan")' : v > 0 ? 'float("inf")' : '-float("inf")');
  const pyLit = (v) => (typeof v === 'number' ? pyNum(v) : J(String(v)));
  const inches = (px) => String(Math.round(px) / 100);
  const LIGHT_BASE = '#2f6690';   // the points' colour of the light theme (SM.report.BASE is the theme's)
  const MPL_DASH = ['-', '--', ':', '-.'];
  const withCode = (graph, code) => (code ? el('div', { class: 'sm-sv-plotcode' }, graph, code) : graph);
  const whereOf = (ctx) => ctx.where || [];

  // The By group's rows (as the backend's code has them), and those of it the report leaves out.
  function whereLines(ctx) {
    const t = ctx.table, where = ctx.where || [];
    const L = where.map((w) => `df = df[df[${J(w.column)}] == ${pyLit(w.value)}]   # only the rows where ${w.column} is ${levelLabel(t.col(w.column), w.value)}`);
    const cols = where.map((w) => t.col(w.column));
    const keep = new Set(ctx.rows), drop = [];
    for (let r = 0; r < t.nrows; r++) if (!keep.has(r) && where.every((w, k) => cols[k] && cols[k].values[r] === w.value)) drop.push(r);
    if (drop.length) L.push(`df = df.drop(index=[${drop.join(', ')}])   # the rows the report leaves out`);
    return L;
  }

  // A group column's levels with their names as the page writes them, [[value, name], ...], for the backend's code.
  function levelPairs(ctx, col) {
    return col ? ctx.table.levels(col).map((v) => [v, levelLabel(col, v)]) : null;
  }

  /* The censor role and its code, as every survival call sends them. */
  function censorOf(ctx) {
    const code = String(ctx.opt('censorCode', '1') ?? '1').trim() || '1';
    return { censor: ctx.name('censor'), censor_code: code };
  }

  /* Save a column from { rows, values } that came from Python. */
  function saveFrom(ctx, name, r, spec) {
    if (!r || !r.rows) return;
    ctx.saveColumn(name, { rows: r.rows, values: nums(r.values).map((v) => (finite(v) ? v : null)) }, spec);
  }

  const censorRole = { key: 'censor', label: 'Censor', max: 1, hint: 'optional: the value in Censor Code marks a censored row',
    help: 'Marks the right-censored rows: a row whose value equals the Censor Code (1 unless set) had not failed yet at its time; any other value is a failure. Without a Censor column every time is a failure. Rows with a missing censor value are left out.' };
  const freqRole = { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
    help: 'A whole-number count per row, rounded down: the product-limit estimate and the tests take the row that many times, the parametric fits weight its log-likelihood by it. Rows with a count below 1 are left out.' };
  const byRole = { key: 'by', label: 'By', hint: 'optional',
    help: 'A separate report for each level of the By column (each combination of levels, with several By columns). Rows with a missing By value are left out.' };
  const censorCodeOpt = { key: 'censorCode', label: 'Censor Code', type: 'text', value: '1', size: 5, hint: 'the value of the Censor column that marks a censored row',
    help: 'The value of the Censor column that marks a censored row, 1 by default (JMP\'s): a number for a numeric Censor column, the exact text for a character one (such as censored). Every other value is a failure.' };
  // The Freq of the other platforms: what they do with it
  const FREQ_HELP = {
    parametric: 'A count per row that weights its log-likelihood: a row of Freq 3 counts as three rows. Rows with a missing, zero or negative count are left out.',
    phreg: 'A whole-number count per row, rounded down: the row enters the partial likelihood that many times. Rows with a count below 1 are left out.',
    curve: 'How many observations each row stands for: its squared residual counts that many times (multiplied with the Weight), and N and the degrees of freedom are the sum of the counts. Rows with a missing, zero or negative count are left out.',
  };
  const timeHelp = (fits) => `The time to the event (a failure) or to the censoring of each row: numeric and continuous. Rows without a time are left out${fits ? '; the log-time distributions (Weibull, Lognormal, Exponential, Fréchet, Loglogistic) need times above 0' : ''}.`;
  const effectsHelp = (ph) => `The effects, each a main effect: a continuous column as it is, a nominal or ordinal one effect coded (a level's estimate is its difference from the average of the levels).${ph ? ' There is no intercept: the baseline hazard takes its place.' : ' Empty: the distribution with the intercept alone.'}`;
  const DISTS = [['weibull', 'Weibull'], ['lognormal', 'Lognormal'], ['exponential', 'Exponential'], ['frechet', 'Fréchet'], ['loglogistic', 'Loglogistic'],
    ['normal', 'Normal'], ['sev', 'SEV'], ['logistic', 'Logistic'], ['lev', 'LEV']];
  const DIST_LABEL = Object.fromEntries(DISTS);
  const LOG_FAMILY = new Set(['weibull', 'lognormal', 'exponential', 'frechet', 'loglogistic']);

  /* ========================================================================
     SURVIVAL
     ======================================================================== */
  function survPayload(ctx) {
    return { time: ctx.name('y'), ...censorOf(ctx), group: ctx.name('group'), freq: ctx.name('freq'), alpha: ctx.alpha, where: whereOf(ctx) };
  }

  /* The Kaplan-Meier plot: steps per group, censored rows as ticks (linked),
     failures as points on request, bands, the combined curve. */
  function kmPlot(ctx, groups, combined, failure) {
    const T = SM.util.themeColors();
    const tr = (v) => (v == null ? null : failure ? 1 - v : v);
    const showCI = ctx.opt('showCI', false), showPts = ctx.opt('showPoints', false), showComb = ctx.opt('showCombined', false), sim = ctx.opt('simCI', false);
    const multi = groups.length > 1;
    const traces = [];
    for (const g of groups) {
      const p = g.plot;
      if (!p) continue;
      const x = nums(p.x), y = nums(p.y), lo = nums(p.lower), hi = nums(p.upper);
      if (showCI) {
        const a = failure ? hi.map(tr) : lo, b = failure ? lo.map(tr) : hi;
        traces.push({ type: 'scatter', mode: 'lines', x, y: a, line: { shape: 'hv', width: 0, color: g.color }, hoverinfo: 'skip', showlegend: false });
        traces.push({ type: 'scatter', mode: 'lines', x, y: b, line: { shape: 'hv', width: 0, color: g.color }, fill: 'tonexty', fillcolor: rgba(g.color, 0.15), hoverinfo: 'skip', showlegend: false });
      }
      if (sim && p.lcb) {
        for (const band of [p.lcb, p.ucb]) traces.push({ type: 'scatter', mode: 'lines', x, y: nums(band).map(tr), line: { shape: 'hv', width: 1, dash: 'dot', color: g.color }, hoverinfo: 'skip', showlegend: false });
      }
      traces.push({ type: 'scatter', mode: 'lines', x, y: y.map(tr), line: { shape: 'hv', color: g.color, width: 1.8 }, name: g.label || ctx.name('y'), showlegend: multi,
        hovertemplate: `${g.label ? `${g.label}<br>` : ''}%{x}: %{y:.4f}<extra></extra>` });
    }
    if (showComb && combined && combined.plot) {
      traces.push({ type: 'scatter', mode: 'lines', x: nums(combined.plot.x), y: nums(combined.plot.y).map(tr), line: { shape: 'hv', color: T.muted, width: 1.5, dash: 'dash' }, name: 'Combined', showlegend: true,
        hovertemplate: 'Combined<br>%{x}: %{y:.4f}<extra></extra>' });
    }
    // the rows: censored as ticks, failures as points; linked to the table
    for (const g of groups) {
      const P = g.points;
      if (!P) continue;
      const cx = [], cy = [], cr = [], fx = [], fy = [], fr = [];
      P.rows.forEach((r, k) => {
        if (P.event[k] > 0) { fx.push(num(P.time[k])); fy.push(tr(num(P.surv[k]))); fr.push(r); } else { cx.push(num(P.time[k])); cy.push(tr(num(P.surv[k]))); cr.push(r); }
      });
      if (cx.length) traces.push({ type: 'scatter', mode: 'markers', x: cx, y: cy, rows: cr, name: `${g.label ? `${g.label} ` : ''}censored`, showlegend: false, marker: { symbol: 'line-ns-open', size: 9, color: g.color, line: { width: 1.6, color: g.color } } });
      if (showPts && fx.length) traces.push({ type: 'scatter', mode: 'markers', x: fx, y: fy, rows: fr, name: `${g.label ? `${g.label} ` : ''}failed`, showlegend: false, marker: { symbol: 'circle', size: 5, color: g.color } });
    }
    const legend = failure ? { x: 1, xanchor: 'right', y: 0.02, yanchor: 'bottom' } : { x: 1, xanchor: 'right', y: 1, yanchor: 'top' };
    return ctx.plot(traces, {
      xaxis: { title: { text: ctx.name('y') }, zeroline: false },
      yaxis: { title: { text: failure ? 'Failure' : 'Surviving' }, range: [-0.02, 1.02] },
      showlegend: multi || (showComb && !!combined), legend: { ...legend, bgcolor: 'rgba(0,0,0,0)', traceorder: 'normal' },
      margin: { l: 56, r: 12, t: 8, b: 42 },
    }, { width: fitWidth(ctx, 560), height: 350, title: `${ctx.name('y')} ${failure ? 'failure' : 'survival'} plot` });
  }

  /* Exponential, Weibull and Lognormal plots: straight lines when the
     distribution fits; one point per failed row. */
  const LINPLOTS = {
    exponential: { title: 'Exponential Plot', xl: (n) => n, yl: '−Log(Surviving)', x: (t) => t, y: (s) => -Math.log(s) },
    weibull: { title: 'Weibull Plot', xl: (n) => `Log(${n})`, yl: 'Log(−Log(Surviving))', x: (t) => Math.log(t), y: (s) => Math.log(-Math.log(s)) },
    lognormal: { title: 'Lognormal Plot', xl: (n) => `Log(${n})`, yl: 'Normal Quantile of Failure', x: (t) => Math.log(t), y: (s) => qnorm(1 - s) },
  };

  function linPlot(ctx, groups, kind, fit) {
    const L = LINPLOTS[kind];
    const traces = [];
    let xmin = Infinity, xmax = -Infinity;
    for (const g of groups) {
      const P = g.points;
      if (!P) continue;
      const x = [], y = [], rows = [];
      P.rows.forEach((r, k) => {
        const t = num(P.time[k]), s = num(P.surv[k]);
        if (!(P.event[k] > 0) || !(s > 0 && s < 1) || (kind !== 'exponential' && !(t > 0))) return;
        const xv = L.x(t), yv = L.y(s);
        if (!finite(xv) || !finite(yv)) return;
        x.push(xv); y.push(yv); rows.push(r);
        if (xv < xmin) xmin = xv;
        if (xv > xmax) xmax = xv;
      });
      traces.push({ type: 'scatter', mode: 'markers', x, y, rows, name: g.label || ctx.name('y'), showlegend: groups.length > 1, marker: { color: g.color, size: 6 } });
    }
    // the fitted lines: on these axes a fit is a straight line
    if (fit && Number.isFinite(xmin)) {
      fit.fit.forEach((f, i) => {
        if (f.error || f.mu == null) return;
        const g = groups[i];
        const lo = kind === 'exponential' ? 0 : xmin - 0.1 * (xmax - xmin), hi = xmax + 0.1 * (xmax - xmin);
        const line = (xv) => (kind === 'exponential' ? xv / Math.exp(f.mu) : (xv - f.mu) / f.sigma);
        traces.push({ type: 'scatter', mode: 'lines', x: [lo, hi], y: [line(lo), line(hi)], line: { color: g ? g.color : SM.report.BASE, width: 1.3, dash: 'dash' }, hoverinfo: 'skip', showlegend: false });
      });
    }
    return ctx.plot(traces, { xaxis: { title: { text: L.xl(ctx.name('y')) } }, yaxis: { title: { text: L.yl } }, showlegend: groups.length > 1, legend: { x: 0, y: 1, bgcolor: 'rgba(0,0,0,0)', traceorder: 'normal' } },
      { width: fitWidth(ctx, 420), height: 300, title: `${ctx.name('y')} ${L.title}` });
  }

  function productLimitTable(ctx, g) {
    const t = g.table;
    if (!t) return null;
    const rows = t.time.map((v, i) => ({ time: num(v), surv: num(t.surv[i]), fail: num(t.fail[i]), se: num(t.se[i]), lower: num(t.lower[i]), upper: num(t.upper[i]), failed: t.failed[i], censored: t.censored[i], at_risk: t.at_risk[i] }));
    return ctx.rt({ columns: [{ key: 'time', label: ctx.name('y') }, { key: 'surv', label: 'Survival' }, { key: 'fail', label: 'Failure' }, { key: 'se', label: 'SurvStdErr' },
      { key: 'lower', label: `Lower ${pct(ctx.alpha)}` }, { key: 'upper', label: `Upper ${pct(ctx.alpha)}` }, { key: 'failed', label: 'Number failed', fmt: 'int' },
      { key: 'censored', label: 'Number censored', fmt: 'int' }, { key: 'at_risk', label: 'At Risk', fmt: 'int' }], rows }, { caption: g.label || null, maxRows: 400, sortable: false, name: `Product-Limit Survival Estimates${g.label ? ` ${g.label}` : ''}` });
  }

  function saveEstimates(ctx) {
    const res = ctx.survRes;
    if (!res) return;
    const gcol = ctx.role('group');
    const cols = { group: [], time: [], surv: [], fail: [], se: [], lower: [], upper: [], failed: [], censored: [], at_risk: [] };
    for (const g of res.groups) {
      const t = g.table;
      if (!t) continue;
      for (let i = 0; i < t.time.length; i++) {
        cols.group.push(g.level);
        for (const k of ['time', 'surv', 'fail', 'se', 'lower', 'upper', 'failed', 'censored', 'at_risk']) cols[k].push(num(t[k][i]));
      }
    }
    const fix = (a) => a.map((v) => (finite(v) ? v : NaN));
    const columns = [];
    if (res.grouped && gcol) columns.push({ name: gcol.name, dataType: gcol.isNumeric ? 'numeric' : 'character', modelingType: 'nominal', values: cols.group.map((v) => (v == null ? (gcol.isNumeric ? NaN : null) : v)) });
    columns.push({ name: ctx.name('y'), dataType: 'numeric', values: fix(cols.time) });
    const names = { surv: 'Survival', fail: 'Failure', se: 'SurvStdErr', lower: `Lower ${pct(ctx.alpha)}`, upper: `Upper ${pct(ctx.alpha)}`, failed: 'Number failed', censored: 'Number censored', at_risk: 'At Risk' };
    for (const [k, name] of Object.entries(names)) columns.push({ name, dataType: 'numeric', values: fix(cols[k]) });
    const name = SM.app.uniqueTableName(`${ctx.table.name} survival estimates${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`);
    SM.app.addTable(new SM.Table({ name, source: `saved from ${ctx.report.title}`, notes: 'Product-limit (Kaplan-Meier) estimates, from statsmodels SurvfuncRight.', columns }));
  }

  async function askList(ctx, title, label, key, value, check, help) {
    const v = await SM.ui.form({ title, fields: [{ key: 'v', label, value: (ctx.opt(key, null) || value || []).join(', '), full: true, help }] });
    if (!v) return;
    const list = parseList(v.v).filter(check || (() => true));
    ctx.set(key, list.length ? list.slice(0, 20) : null);
  }

  async function renderSurvival(ctx) {
    const gcol = ctx.role('group');
    const estTimes = ctx.opt('estTimes', null), estProbs = ctx.opt('estProbs', null);
    // the graphs' options and sizes, for their code
    const plot = { showCI: ctx.opt('showCI', false), showPoints: ctx.opt('showPoints', false), showCombined: ctx.opt('showCombined', false), simCI: ctx.opt('simCI', false),
      labels: levelPairs(ctx, gcol), size: [fitWidth(ctx, 560), 350], lin_size: [fitWidth(ctx, 420), 300],
      lin: Object.fromEntries(['exponential', 'weibull', 'lognormal'].map((k) => [k, ctx.opt(`fit:${k}`, false)])) };
    const res = await ctx.call('survival.km', { ...survPayload(ctx), times: estTimes, probs: estProbs, simultaneous: ctx.opt('simCI', false), plot });
    if (res.error) { ctx.container.append(ctx.warn(res.error)); return; }
    const pc = res.plot_code || {};
    const multi = res.groups.length > 1;
    const groups = res.groups.map((g, i) => ({ ...g, label: res.grouped ? levelLabel(gcol, g.level) : '', color: multi ? PALETTE[i % PALETTE.length] : SM.report.BASE }));
    ctx.survRes = { ...res, groups };
    const failureMain = ctx.opt('failure', false);
    if (ctx.opt('survPlot', true)) {
      const ob = ctx.outline(failureMain ? 'Failure Plot' : 'Survival Plot', { key: 'survplot' });
      ob.add(kmPlot(ctx, groups, res.combined, failureMain), ctx.code(failureMain ? pc.failure : pc.survival));
      const notes = [];
      if (ctx.opt('showCI', false)) notes.push(`Shaded: pointwise ${pct(ctx.alpha)} limits (Greenwood, on the log(−log) scale).`);
      if (ctx.opt('simCI', false)) notes.push(Math.abs(ctx.alpha - 0.05) > 1e-12 ? 'Simultaneous bands are Hall-Wellner bands at 95% only (statsmodels simultaneous_cb): set α to 0.05 to see them.'
        : 'Dotted: Hall-Wellner 95% simultaneous bands (statsmodels simultaneous_cb, log transform), left out near the first failures, where they span nearly 0 to 1.');
      notes.push('Ticks mark the censored rows; click or drag over them to select the rows.');
      ob.add(ctx.note(notes.join(' ')));
    }
    if (ctx.opt('failPlot', false) && !failureMain) ctx.outline('Failure Plot', { key: 'failplot' }).add(kmPlot(ctx, groups, res.combined, true), ctx.code(pc.failure));

    // ---- Summary: counts and means, then the quantiles
    const all = res.combined ? [{ ...res.combined, label: 'Combined' }, ...groups] : groups;
    const sum = ctx.outline('Summary', { key: 'summary' });
    const label = (g) => (g.label || ctx.name('y'));
    sum.add(ctx.rt({ columns: [{ key: 'group', label: 'Group', fmt: 'text' }, { key: 'failed', label: 'Number failed', fmt: 'int' }, { key: 'censored', label: 'Number censored', fmt: 'int' },
      { key: 'mean', label: 'Mean' }, { key: 'se', label: 'Std Error' }], rows: all.map((g) => ({ group: label(g), failed: g.failed, censored: g.censored, mean: num(g.mean), se: num(g.mean_se) })) }, { sortable: false }));
    sum.add(ctx.rt({ caption: 'Quantiles', columns: [{ key: 'group', label: 'Group', fmt: 'text' }, { key: 'median', label: 'Median Time' }, { key: 'lo', label: `Lower ${pct(ctx.alpha)}` },
      { key: 'hi', label: `Upper ${pct(ctx.alpha)}` }, { key: 'q25', label: '25% Failures' }, { key: 'q75', label: '75% Failures' }],
    rows: all.map((g) => ({ group: label(g), median: num(g.median), lo: num(g.median_lower), hi: num(g.median_upper), q25: num(g.q25), q75: num(g.q75) })) }, { sortable: false }));
    const biased = all.filter((g) => g.mean_biased).map(label);
    sum.add(ctx.note(`Mean: the area under the survival curve up to the largest time, a restricted mean${biased.length ? `; biased low where the largest time is censored (${biased.join(', ')})` : ''}. Its standard error is the Kaplan-Meier (Klein and Moeschberger) formula. Median and quartiles: the first time the estimate falls below 1 − p; the median's interval inverts log(−log) tests (statsmodels quantile_ci, SAS's method).`));

    if (res.tests) {
      const ob = ctx.outline('Tests Between Groups', { key: 'tests', info: 'p:survival-tests' });
      ob.add(ctx.rt(res.tests, { sortable: false }),
        ctx.note('statsmodels survdiff: Log-Rank weighs every failure time alike; Wilcoxon (Gehan-Breslow) by the number at risk, so early differences count more; Tarone-Ware by its square root; Fleming-Harrington by the pooled survival just before each time. JMP reports Log-Rank and Wilcoxon.'));
    }
    const pl = ctx.outline('Product-Limit Survival Estimates', { key: 'pl', closed: true });
    for (const g of groups) pl.add(productLimitTable(ctx, g));
    pl.add(ctx.note(`Greenwood's standard errors; the ${pct(ctx.alpha)} limits are pointwise, on the log(−log) scale.`));

    // ---- linearizing plots and parametric fits
    const fitKeys = ['exponential', 'weibull', 'lognormal'].filter((k) => ctx.opt(`fit:${k}`, false));
    const fits = fitKeys.length ? await ctx.call('survival.fit_groups', { ...survPayload(ctx), dists: fitKeys }) : null;
    const fitOf = (k) => (fits ? fits.fits.find((f) => f.dist === k) : null);
    for (const k of ['exponential', 'weibull', 'lognormal']) {
      if (!ctx.opt(`plot:${k}`, false)) continue;
      const ob = ctx.outline(LINPLOTS[k].title, { key: `plot:${k}` });
      ob.add(linPlot(ctx, groups, k, ctx.opt(`fit:${k}`, false) ? fitOf(k) : null), ctx.code((pc.lin || {})[k]),
        ctx.note({ exponential: 'Straight through the origin when the times are exponential.', weibull: 'Straight when the times are Weibull; the slope is the shape β.', lognormal: 'Straight when the times are lognormal; the slope is 1/σ.' }[k] + (ctx.opt(`fit:${k}`, false) ? ' The dashed lines are the fits.' : '')));
    }
    for (const k of fitKeys) {
      const f = fitOf(k);
      if (!f) continue;
      const ob = ctx.outline(`${DIST_LABEL[k]} Fit`, { key: `fit:${k}`, menu: () => [{ label: 'Remove Fit', action: () => ctx.set(`fit:${k}`, false) }] });
      const errs = f.fit.filter((x) => x.error);
      for (const e of errs) ob.add(ctx.warn(`${res.grouped ? `${levelLabel(gcol, e.level)}: ` : ''}${e.error}`));
      const lvl = (v) => (res.grouped ? levelLabel(gcol, v) : ctx.name('y'));
      ob.add(ctx.rt({ caption: 'Parameter Estimates', columns: [{ key: 'group', label: 'Group', fmt: 'text' }, { key: 'parameter', label: 'Parameter', fmt: 'text' }, { key: 'estimate', label: 'Estimate' },
        { key: 'se', label: 'Std Error' }, { key: 'lower', label: `Lower ${pct(ctx.alpha)}` }, { key: 'upper', label: `Upper ${pct(ctx.alpha)}` }], rows: f.params.map((p) => ({ ...p, group: lvl(p.level) })) }, { sortable: false }),
      ctx.rt({ caption: 'Fit', columns: [{ key: 'group', label: 'Group', fmt: 'text' }, { key: 'n', label: 'N', fmt: 'int' }, { key: 'events', label: 'Failures', fmt: 'int' }, { key: 'm2ll', label: '−2LogLikelihood' },
        { key: 'aicc', label: 'AICc' }, { key: 'bic', label: 'BIC' }], rows: f.fit.filter((x) => !x.error).map((x) => ({ ...x, group: lvl(x.level) })) }, { sortable: false }),
      ctx.note('Maximum likelihood with right censoring (failures by their density, censored rows by their survival), statsmodels GenericLikelihoodModel; standard errors from the Hessian; intervals of positive parameters are Wald intervals on the log scale.'),
      ctx.code(fits.code));
    }

    // ---- estimates at times and probabilities
    if (estTimes && estTimes.length) {
      const ob = ctx.outline('Survival Probability Estimates', { key: 'esttimes', menu: () => [{ label: 'Remove', action: () => ctx.set('estTimes', null) }] });
      const rows = [];
      for (const g of all) for (const e of g.est_times || []) rows.push({ group: label(g), ...e });
      ob.add(ctx.rt({ columns: [{ key: 'group', label: 'Group', fmt: 'text' }, { key: 'time', label: ctx.name('y') }, { key: 'surv', label: 'Survival' }, { key: 'lower', label: `Lower ${pct(ctx.alpha)}` },
        { key: 'upper', label: `Upper ${pct(ctx.alpha)}` }, { key: 'fail', label: 'Failure' }], rows }, { sortable: false }), ctx.note('The product-limit estimate at each time, with the log(−log) interval.'));
    }
    if (estProbs && estProbs.length) {
      const ob = ctx.outline('Time Quantile Estimates', { key: 'estprobs', menu: () => [{ label: 'Remove', action: () => ctx.set('estProbs', null) }] });
      const rows = [];
      for (const g of all) for (const e of g.est_probs || []) rows.push({ group: label(g), ...e, time: num(e.time), lower: num(e.lower), upper: num(e.upper) });
      ob.add(ctx.rt({ columns: [{ key: 'group', label: 'Group', fmt: 'text' }, { key: 'p', label: 'Failure Probability' }, { key: 'time', label: ctx.name('y') },
        { key: 'lower', label: `Lower ${pct(ctx.alpha)}` }, { key: 'upper', label: `Upper ${pct(ctx.alpha)}` }], rows }, { sortable: false }), ctx.note('The time by which that fraction has failed (statsmodels quantile and quantile_ci); ∞ where the estimate never gets there.'));
    }
    ctx.container.append(ctx.code(res.code));
  }

  function survivalMenu(ctx) {
    const ask = (title, label, key, dflt, check, help) => askList(ctx, title, label, key, dflt, check, help);
    return [
      ctx.check('Survival Plot', 'survPlot', null, true),
      ctx.check('Failure Plot', 'failPlot', null, false),
      { label: 'Plot Options', submenu: () => [
        ctx.check('Show Points', 'showPoints', null, false),
        ctx.check('Show Combined', 'showCombined', null, false),
        ctx.check('Show Confid Interval', 'showCI', null, false),
        ctx.check('Show Simultaneous CI', 'simCI', null, false),
        ctx.check('Plot Failure instead of Survival', 'failure', null, false),
      ] },
      { separator: true },
      ctx.check('Exponential Plot', 'plot:exponential', null, false),
      ctx.check('Weibull Plot', 'plot:weibull', null, false),
      ctx.check('Lognormal Plot', 'plot:lognormal', null, false),
      ctx.check('Exponential Fit', 'fit:exponential', null, false),
      ctx.check('Weibull Fit', 'fit:weibull', null, false),
      ctx.check('Lognormal Fit', 'fit:lognormal', null, false),
      { separator: true },
      { label: 'Estimate Survival Probability…', action: () => ask('Estimate Survival Probability', `Times (${ctx.name('y')}), separated by commas`, 'estTimes', [], null,
        'Up to 20 times, separated by commas or spaces: the product-limit estimate of surviving past each time, with its log(−log) interval, for each group. Empty: the outline is removed.') },
      { label: 'Estimate Time Quantile…', action: () => ask('Estimate Time Quantile', 'Failure probabilities between 0 and 1, separated by commas', 'estProbs', [0.1, 0.5, 0.9], (p) => p > 0 && p < 1,
        'Up to 20 fractions failed, strictly between 0 and 1 (0.5 is the median; others are dropped): the time by which each fraction has failed, with its interval (statsmodels\' quantile and quantile_ci). Empty: the outline is removed.') },
      { label: 'Save Estimates', action: () => saveEstimates(ctx) },
    ];
  }

  /* ========================================================================
     FIT PROPORTIONAL HAZARDS
     ======================================================================== */
  async function renderPH(ctx) {
    const res = await ctx.call('phreg.fit', { time: ctx.name('y'), effects: ctx.names('x'), ...censorOf(ctx), freq: ctx.name('freq'), ties: ctx.opt('ties', 'breslow'), alpha: ctx.alpha,
      where: whereOf(ctx), plot: { size: [fitWidth(ctx, 460), 300] } });
    if (res.error) { ctx.container.append(ctx.warn(res.error)); return; }
    ctx.phRes = res;
    const wm = ctx.outline('Whole Model', { key: 'whole' });
    wm.add(ctx.rt(res.whole, { sortable: false }), ctx.kv([['Number of failures', res.summary.events, 'int'], ['Number censored', res.summary.censored, 'int'], ['Total', res.summary.n, 'int'],
      ['Ties', res.ties === 'efron' ? 'Efron' : 'Breslow', 'text']]), ctx.note('Likelihood ratio χ² of the model against no effects, from the partial likelihood (statsmodels PHReg).'));
    ctx.outline('Parameter Estimates', { key: 'est' }).add(ctx.rt(res.estimates, { sortable: false }),
      ctx.note('Log hazard ratios: a positive estimate raises the hazard. Nominal effects are effect coded (the last level is minus the sum of the others); the limits and the ChiSquare are Wald\'s. JMP\'s limits are profile likelihood limits.'));
    if (res.lr && res.lr.rows.length) ctx.outline('Effect Likelihood Ratio Tests', { key: 'lr' }).add(ctx.rt(res.lr, { sortable: false }), ctx.note('Each effect: the model refitted without it.'));
    if (ctx.opt('riskRatios', true)) {
      const ob = ctx.outline('Risk Ratios', { key: 'rr', menu: () => [{ label: 'Remove', action: () => ctx.set('riskRatios', false) }] });
      if (res.unit) ob.add(ctx.rt(res.unit, { caption: 'Unit Risk Ratios', sortable: false }));
      if (res.range) ob.add(ctx.rt(res.range, { caption: 'Range Risk Ratios', sortable: false }));
      for (const n of res.nominal || []) ob.add(ctx.rt(n.table, { caption: `Risk Ratios for ${n.effect}`, sortable: false }));
      ob.add(ctx.note('Unit: the hazard ratio for one unit more; range: for the whole range of the column in the data; nominal effects: the hazard of Level1 over Level2.'));
    }
    if (ctx.opt('baseline', true) && res.baseline) {
      const ob = ctx.outline('Baseline Survival', { key: 'baseline', menu: () => [{ label: 'Remove', action: () => ctx.set('baseline', false) }] });
      ob.add(ctx.plot([{ type: 'scatter', mode: 'lines', x: nums(res.baseline.time), y: nums(res.baseline.surv), line: { shape: 'hv', color: SM.report.BASE, width: 1.8 }, name: 'Baseline', hovertemplate: '%{x}: %{y:.4f}<extra></extra>' }],
        { xaxis: { title: { text: ctx.name('y') } }, yaxis: { title: { text: 'Surviving' }, range: [-0.02, 1.02] } }, { width: fitWidth(ctx, 460), height: 300, title: 'Baseline survival' }),
      ctx.code(res.plot_code), ctx.note('The survival curve of a subject at the means of the model\'s design columns: Breslow\'s estimate of the baseline cumulative hazard.'));
    }
    ctx.container.append(ctx.code(res.code));
  }

  function phMenu(ctx) {
    const y = ctx.name('y');
    return [
      ctx.check('Risk Ratios', 'riskRatios', null, true),
      ctx.check('Baseline Survival', 'baseline', null, true),
      { label: 'Ties', submenu: () => [['breslow', 'Breslow'], ['efron', 'Efron']].map(([k, l]) => ({ label: l, checked: ctx.opt('ties', 'breslow') === k, action: () => ctx.set('ties', k) })) },
      { separator: true },
      { label: 'Save Risk Scores', action: () => { const r = ctx.phRes; if (r) saveFrom(ctx, `Risk Score ${y}`, { rows: r.scores.rows, values: r.scores.risk }, { notes: 'exp((x − mean)·β): the hazard relative to a subject at the means' }); } },
      { label: 'Save Linear Predictor', action: () => { const r = ctx.phRes; if (r) saveFrom(ctx, `Linear Predictor ${y}`, { rows: r.scores.rows, values: r.scores.lp }, { notes: 'x·β of the proportional hazards fit' }); } },
    ];
  }

  /* ========================================================================
     LIFE DISTRIBUTION
     ======================================================================== */
  const SCALES = {
    nonparametric: { label: 'Nonparametric', log: false, q: (p) => p },
    weibull: { label: 'Weibull', log: true, q: (p) => Math.log(-Math.log(1 - p)) },
    lognormal: { label: 'Lognormal', log: true, q: qnorm },
    exponential: { label: 'Exponential', log: false, q: (p) => -Math.log(1 - p) },
    frechet: { label: 'Fréchet', log: true, q: (p) => -Math.log(-Math.log(p)) },
    loglogistic: { label: 'Loglogistic', log: true, q: (p) => Math.log(p / (1 - p)) },
    normal: { label: 'Normal', log: false, q: qnorm },
    sev: { label: 'SEV', log: false, q: (p) => Math.log(-Math.log(1 - p)) },
    logistic: { label: 'Logistic', log: false, q: (p) => Math.log(p / (1 - p)) },
    lev: { label: 'LEV', log: false, q: (p) => -Math.log(-Math.log(p)) },
  };
  const PROB_TICKS = [0.0001, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995, 0.999, 0.9999];

  /* Probability ticks at least a twelfth of the axis apart. */
  function thinTicks(ticks, q, lo, hi) {
    const gap = (hi - lo) / 12;
    const out = [];
    let last = -Infinity;
    for (const p of ticks) {
      const v = q(p);
      if (v < lo || v > hi || v - last < gap) continue;
      out.push(p);
      last = v;
    }
    return out;
  }

  /* Ticks at 1, 2 and 5 times the powers of ten on a log axis (only the
     powers when the axis spans many decades). */
  function logTicks(lo, hi) {
    const e0 = Math.floor(Math.log10(lo)), e1 = Math.ceil(Math.log10(hi));
    const mult = e1 - e0 > 5 ? [1] : [1, 2, 5];
    const out = [];
    for (let e = e0; e <= e1; e++) for (const m of mult) { const v = m * 10 ** e; if (v >= lo && v <= hi) out.push(+v.toPrecision(6)); }
    return out;
  }

  function probPlot(ctx, res, dists, scale) {
    const S = SCALES[scale] || SCALES.weibull;
    const T = SM.util.themeColors();
    const traces = [];
    const pts = res.points;
    const t = nums(pts.time), pr = nums(pts.prob);
    const px = [], py = [], prow = [];
    t.forEach((tv, k) => {
      const q = S.q(pr[k]);
      if (!finite(q) || (S.log && !(tv > 0))) return;
      px.push(tv); py.push(q); prow.push(pts.rows[k]);
    });
    let ylo = Math.min(...py), yhi = Math.max(...py);
    if (!Number.isFinite(ylo)) { ylo = S.q(0.05); yhi = S.q(0.95); }
    const pad = 0.15 * (yhi - ylo || 1) + 0.15;
    ylo = Math.max(S.q(0.0001), ylo - pad); yhi = Math.min(S.q(0.9999), yhi + pad);
    if (scale === 'nonparametric') { ylo = -0.02; yhi = 1.02; }
    const tp = px.length ? px : t.filter((v) => (S.log ? v > 0 : true));
    let xlo = Math.min(...tp), xhi = Math.max(...tp);
    if (!Number.isFinite(xlo) || !Number.isFinite(xhi) || (S.log && !(xlo > 0))) { xlo = 1; xhi = 10; }
    const xr = S.log ? [Math.log10(xlo / 1.6), Math.log10(xhi * 1.6)] : [xlo - 0.12 * (xhi - xlo || 1), xhi + 0.12 * (xhi - xlo || 1)];
    const grid = res.grids ? nums(res.grids[S.log ? 'log' : 'lin'] || res.grids.lin) : [];
    const within = (x) => (S.log ? x > 0 && Math.log10(x) >= xr[0] && Math.log10(x) <= xr[1] : x >= xr[0] && x <= xr[1]);
    res.fits.forEach((f, i) => {
      if (f.error || !dists.includes(f.dist)) return;
      const c = FIT_COLORS[DISTS.findIndex(([k]) => k === f.dist) % FIT_COLORS.length];
      const cv = f.curves && f.curves[S.log ? 'log' : 'lin'];
      if (!cv) return;
      const F = nums(cv.F), lo = nums(cv.lower), hi = nums(cv.upper);
      const X = [], Y = [], L = [], U = [], FF = [];
      grid.forEach((x, k) => {
        if (!within(x)) return;
        const y = S.q(F[k]);
        if (!finite(y) || y < ylo - 1 || y > yhi + 1) return;
        X.push(x); Y.push(y); FF.push(F[k]); L.push(finite(S.q(lo[k])) ? S.q(lo[k]) : null); U.push(finite(S.q(hi[k])) ? S.q(hi[k]) : null);
      });
      if (ctx.opt('bands', true) && f.dist === scale) {
        traces.push({ type: 'scatter', mode: 'lines', x: X, y: L, line: { width: 0.8, color: c, dash: 'dot' }, hoverinfo: 'skip', showlegend: false });
        traces.push({ type: 'scatter', mode: 'lines', x: X, y: U, line: { width: 0.8, color: c, dash: 'dot' }, fill: 'tonexty', fillcolor: rgba(c, 0.1), hoverinfo: 'skip', showlegend: false });
      }
      traces.push({ type: 'scatter', mode: 'lines', x: X, y: Y, line: { color: c, width: 1.8 }, name: f.label, customdata: FF,
        hovertemplate: `${f.label}<br>%{x}: F = %{customdata:.4f}<extra></extra>` });
    });
    if (ctx.opt('showNP', true)) traces.push({ type: 'scatter', mode: 'markers', x: px, y: py, rows: prow, name: 'Nonparametric', marker: { color: T.text, size: 6, symbol: 'circle' } });
    const ticks = scale === 'nonparametric' ? [0, 0.2, 0.4, 0.6, 0.8, 1] : thinTicks(PROB_TICKS, S.q, ylo, yhi);
    const xt = S.log ? logTicks(10 ** xr[0], 10 ** xr[1]) : null;
    const width = fitWidth(ctx, 640);
    const side = width >= 560;   // the legend beside the plot when there is room
    return ctx.plot(traces, {
      xaxis: { title: { text: ctx.name('y') }, type: S.log ? 'log' : 'linear', range: xr, ...(xt ? { tickvals: xt, ticktext: xt.map((v) => fmt(v)) } : {}) },
      yaxis: { title: { text: 'Probability' }, range: [ylo, yhi], tickvals: ticks.map(S.q), ticktext: ticks.map((p) => String(p)), zeroline: false },
      showlegend: true, legend: side ? { x: 1.02, xanchor: 'left', y: 1, yanchor: 'top', bgcolor: 'rgba(0,0,0,0)', traceorder: 'normal' } : { x: 0, xanchor: 'left', y: 1, bgcolor: 'rgba(0,0,0,0)', traceorder: 'normal' },
      margin: { l: 56, r: side ? 8 : 12, t: 8, b: 42 },
    }, { width, height: 380, title: `${ctx.name('y')} ${S.label} probability plot` });
  }

  /* A fit's CDF with its pointwise limits, over the nonparametric estimate. */
  function cdfPlot(ctx, res, f, color) {
    const N = res.nonparametric;
    const t = nums(N.time), F = nums(N.fail);
    const tmax = Math.max(...t), tmin = Math.min(...t);
    const lo = f.logt ? 0 : tmin - 0.1 * (tmax - tmin || 1), hi = tmax + 0.1 * (tmax - tmin || 1);
    const grid = nums(res.grids.lin), cv = f.curves.lin;
    const X = [], Y = [], L = [], U = [];
    grid.forEach((x, k) => {
      if (x < lo || x > hi || (f.logt && !(x > 0))) return;
      X.push(x); Y.push(num(cv.F[k])); L.push(num(cv.lower[k])); U.push(num(cv.upper[k]));
    });
    const T = SM.util.themeColors();
    const traces = [
      { type: 'scatter', mode: 'lines', x: X, y: L, line: { width: 0, color }, hoverinfo: 'skip', showlegend: false },
      { type: 'scatter', mode: 'lines', x: X, y: U, line: { width: 0, color }, fill: 'tonexty', fillcolor: rgba(color, 0.15), hoverinfo: 'skip', showlegend: false },
      { type: 'scatter', mode: 'lines', x: [Math.min(0, tmin), ...t], y: [0, ...F], line: { shape: 'hv', color: T.text, width: 1.2 }, name: 'Nonparametric', hovertemplate: 'Nonparametric<br>%{x}: %{y:.4f}<extra></extra>' },
      { type: 'scatter', mode: 'lines', x: X, y: Y, line: { color, width: 2 }, name: f.label, hovertemplate: `${f.label}<br>%{x}: %{y:.4f}<extra></extra>` },
    ];
    return ctx.plot(traces, { xaxis: { title: { text: ctx.name('y') }, range: [lo, hi] }, yaxis: { title: { text: 'Probability' }, range: [-0.02, 1.02] },
      showlegend: true, legend: { x: 1, xanchor: 'right', y: 0.02, yanchor: 'bottom', bgcolor: 'rgba(0,0,0,0)', traceorder: 'normal' } },
    { width: fitWidth(ctx, 400), height: 250, title: `${ctx.name('y')} ${f.label} distribution` });
  }

  async function renderLife(ctx) {
    const dists = ctx.opt('dists', ['weibull', 'lognormal']);
    const scale = ctx.opt('scale', dists[0] || 'weibull');
    const calcT = ctx.opt('calcTimes', null), calcP = ctx.opt('calcProbs', [0.1, 0.5]);
    const plot = { scale, bands: ctx.opt('bands', true), showNP: ctx.opt('showNP', true), prob_size: [fitWidth(ctx, 640), 380], cdf_size: [fitWidth(ctx, 400), 250] };
    const res = await ctx.call('lifedist.fit', { time: ctx.name('y'), ...censorOf(ctx), freq: ctx.name('freq'), dists, alpha: ctx.alpha, times: calcT, probs: calcP, where: whereOf(ctx), plot });
    if (res.error) { ctx.container.append(ctx.warn(res.error)); return; }
    const pc = res.plot_code || {};
    // ---- Compare Distributions: the check boxes, the scale, the plot
    const cmp = ctx.outline('Compare Distributions', { key: 'compare', info: 'p:lifedist-scale' });
    const grp = SM.util.uid('scale');
    const body = el('tbody');
    const rowFor = (key, label, checked, onCheck) => {
      const cb = el('input', { type: 'checkbox', 'aria-label': `Show ${label}` });
      cb.checked = checked;
      cb.addEventListener('change', () => onCheck(cb.checked));
      const rb = el('input', { type: 'radio', name: grp, 'aria-label': `${label} scale` });
      rb.checked = scale === key;
      rb.addEventListener('change', () => { if (rb.checked) ctx.set('scale', key); });
      const i = DISTS.findIndex(([k]) => k === key);
      const sw = i >= 0 ? el('span', { class: 'sm-life-swatch', style: { background: FIT_COLORS[i % FIT_COLORS.length] } }) : el('span', { class: 'sm-life-swatch is-np' });
      body.append(el('tr', null, el('td', { class: 'sm-l' }, sw, label), el('td', null, cb), el('td', null, rb)));
    };
    rowFor('nonparametric', 'Nonparametric', ctx.opt('showNP', true), (on) => ctx.set('showNP', on));
    for (const [k, label] of DISTS) rowFor(k, label, dists.includes(k), (on) => ctx.set('dists', on ? DISTS.map(([x]) => x).filter((x) => x === k || dists.includes(x)) : dists.filter((x) => x !== k)));
    const chooser = el('table', { class: 'sm-rt sm-life-dists' }, el('thead', null, el('tr', null, el('th', { class: 'sm-l', text: 'Distribution' }), el('th', { text: 'Show' }), el('th', { text: 'Scale' }))), body);
    cmp.add(ctx.row(chooser, withCode(probPlot(ctx, res, dists, scale), ctx.code(pc.prob))));
    cmp.add(ctx.note(`Points: the nonparametric (Kaplan-Meier) estimate of the failure probability at each failure, plotted at the middle of its jump. Lines: the fitted distributions${ctx.opt('bands', true) && dists.includes(scale) ? `, with pointwise ${pct(ctx.alpha)} limits for the one whose scale is shown` : ''}. On a distribution's own scale its fit is a straight line.`));

    // ---- Statistics
    const st = ctx.outline('Statistics', { key: 'stats' });
    ctx.outline('Summary of Data', { parent: st, key: 'sumdata' }).add(ctx.kv([['Number of observations', res.n, 'int'], ['Uncensored', res.failed, 'int'], ['Right Censored', res.censored, 'int']]));
    const np = ctx.outline('Nonparametric Estimate', { parent: st, key: 'np', closed: true });
    const N = res.nonparametric;
    np.add(ctx.rt({ columns: [{ key: 'time', label: ctx.name('y') }, { key: 'fail', label: 'Probability' }, { key: 'se', label: 'Std Error' }, { key: 'lower', label: `Lower ${pct(ctx.alpha)}` },
      { key: 'upper', label: `Upper ${pct(ctx.alpha)}` }, { key: 'failed', label: 'Failures', fmt: 'int' }, { key: 'censored', label: 'Censored', fmt: 'int' }, { key: 'at_risk', label: 'At Risk', fmt: 'int' }],
    rows: N.time.map((v, i) => ({ time: num(v), fail: num(N.fail[i]), se: num(N.se[i]), lower: num(N.lower[i]), upper: num(N.upper[i]), failed: N.failed[i], censored: N.censored[i], at_risk: N.at_risk[i] })) }, { maxRows: 400, sortable: false }),
    ctx.note('1 − the Kaplan-Meier estimate, with Greenwood\'s standard error and log(−log) limits.'));
    for (const f of res.fits) {
      const ob = ctx.outline(`Parametric Estimate - ${f.label}`, { parent: st, key: `pe:${f.dist}`, menu: () => [
        ctx.check('Distribution Plot', `cdf:${f.dist}`, null, true),
        { label: 'Show Its Scale', action: () => ctx.set('scale', f.dist) },
        { separator: true },
        { label: 'Remove Fit', action: () => ctx.set('dists', dists.filter((x) => x !== f.dist)) }] });
      if (f.error) { ob.add(ctx.warn(`${f.label}: ${f.error}`)); continue; }
      const color = FIT_COLORS[DISTS.findIndex(([k]) => k === f.dist) % FIT_COLORS.length];
      ob.head.style.setProperty('--fit-color', color);
      ob.el.classList.add('sm-life-fit');
      if (ctx.opt(`cdf:${f.dist}`, true)) ob.add(cdfPlot(ctx, res, f, color), ctx.code((pc.cdf || {})[f.dist]));
      ob.add(ctx.rt(f.params, { sortable: false }));
      if (f.alt) ob.add(ctx.rt(f.alt, { caption: f.dist === 'exponential' ? 'Mean' : 'Weibull α and β', sortable: false }));
      ob.add(ctx.kv([['−2LogLikelihood', num(f.m2ll)], ['AICc', num(f.aicc)], ['BIC', num(f.bic)]]));
      ctx.outline('Covariance Matrix', { parent: ob, key: `cov:${f.dist}`, closed: true }).add(ctx.rt(f.cov, { sortable: false }), ctx.note('Of the location μ and log σ, from the Hessian.'));
    }
    if (res.comparison.rows.length) {
      ctx.outline('Model Comparisons', { parent: st, key: 'models' }).add(ctx.rt(res.comparison, { onRow: (row) => ctx.set('scale', row.dist) }),
        ctx.note('Best first by AICc (k the number of parameters, n the number of observations, censored or not). −2 log L is that of the times themselves, so it compares across families. Click a line for that distribution\'s scale.'));
    }
    // ---- the calculator
    const fitted = res.fits.filter((f) => !f.error);
    if (fitted.length && ctx.opt('calc', true)) {
      const ob = ctx.outline('Distribution Calculator', { key: 'calc', info: 'p:lifedist-calc', menu: () => [{ label: 'Remove', action: () => ctx.set('calc', false) }] });
      const tIn = el('input', { type: 'text', inputmode: 'decimal', size: 18, 'aria-label': 'Times', placeholder: 'e.g. 10, 20' });
      tIn.value = (calcT || []).join(', ');
      const pIn = el('input', { type: 'text', inputmode: 'decimal', size: 18, 'aria-label': 'Failure probabilities', placeholder: 'e.g. 0.1, 0.5' });
      pIn.value = (calcP || []).join(', ');
      tIn.addEventListener('change', () => { const v = parseList(tIn.value); ctx.set('calcTimes', v.length ? v.slice(0, 20) : null); });
      pIn.addEventListener('change', () => { const v = parseList(pIn.value).filter((p) => p > 0 && p < 1); ctx.set('calcProbs', v.length ? v.slice(0, 20) : null); });
      ob.add(el('div', { class: 'sm-life-calc' }, el('label', null, `Probability of failure by ${ctx.name('y')}`, tIn), el('label', null, 'Time by which a fraction has failed', pIn)));
      const rowsT = [], rowsP = [];
      for (const f of fitted) {
        for (const a of f.at_times || []) rowsT.push({ dist: f.label, ...a });
        for (const a of f.at_probs || []) rowsP.push({ dist: f.label, ...a });
      }
      if (rowsT.length) ob.add(ctx.rt({ caption: 'Failure Probability', columns: [{ key: 'dist', label: 'Distribution', fmt: 'text' }, { key: 'time', label: ctx.name('y') }, { key: 'F', label: 'Probability' },
        { key: 'lower', label: `Lower ${pct(ctx.alpha)}` }, { key: 'upper', label: `Upper ${pct(ctx.alpha)}` }, { key: 'S', label: 'Survival' }], rows: rowsT }, { sortable: false }));
      if (rowsP.length) ob.add(ctx.rt({ caption: 'Quantile', columns: [{ key: 'dist', label: 'Distribution', fmt: 'text' }, { key: 'p', label: 'Probability' }, { key: 'time', label: ctx.name('y') },
        { key: 'lower', label: `Lower ${pct(ctx.alpha)}` }, { key: 'upper', label: `Upper ${pct(ctx.alpha)}` }], rows: rowsP }, { sortable: false }));
      ob.add(ctx.note('Wald limits by the delta method: for the probability on the standardized scale z = (g(t) − μ)/σ, for the quantile on g(t), with g the log for the log-time families.'));
    }
    ctx.container.append(ctx.code(res.code));
  }

  function lifeMenu(ctx) {
    const dists = ctx.opt('dists', ['weibull', 'lognormal']);
    return [
      { label: 'Fit All Distributions', action: () => ctx.set('dists', DISTS.map(([k]) => k)) },
      { label: 'Fit All Non-negative', action: () => ctx.set('dists', DISTS.map(([k]) => k).filter((k) => LOG_FAMILY.has(k))) },
      { label: 'Distributions', submenu: () => DISTS.map(([k, l]) => ({ label: l, checked: dists.includes(k), action: () => ctx.set('dists', dists.includes(k) ? dists.filter((x) => x !== k) : DISTS.map(([x]) => x).filter((x) => x === k || dists.includes(x))) })) },
      { label: 'Scale', submenu: () => Object.entries(SCALES).map(([k, s]) => ({ label: s.label, checked: ctx.opt('scale', dists[0] || 'weibull') === k, action: () => ctx.set('scale', k) })) },
      ctx.check('Show Confidence Bands', 'bands', null, true),
      ctx.check('Distribution Calculator', 'calc', null, true),
    ];
  }

  /* ========================================================================
     FIT PARAMETRIC SURVIVAL
     ======================================================================== */
  function parametricPayload(ctx) {
    return { time: ctx.name('y'), effects: ctx.names('x'), ...censorOf(ctx), freq: ctx.name('freq'), dist: ctx.opt('dist', 'weibull') };
  }

  async function renderParametric(ctx) {
    const res = await ctx.call('parametric.fit', { ...parametricPayload(ctx), alpha: ctx.alpha, corr: ctx.opt('corr', false), where: whereOf(ctx) });
    if (res.error) { ctx.container.append(ctx.warn(res.error)); return; }
    ctx.top.setTitle(`${ctx.top.titleEl.textContent.replace(/^Parametric Survival Fit/, `Parametric Survival Fit: ${res.label}`)}`);
    const s = res.summary;
    const wm = ctx.outline('Whole Model Test', { key: 'whole' });
    wm.add(ctx.rt(res.whole, { sortable: false }));
    wm.add(ctx.kv([['Distribution', res.label, 'text'], ['Observations', s.n, 'int'], ['Uncensored', s.events, 'int'], ['Right Censored', s.censored, 'int'], ['−2LogLikelihood', num(s.m2ll)], ['AICc', num(s.aicc)], ['BIC', num(s.bic)]]),
      ctx.note('The model against one with the intercept only, by the likelihood ratio.'));
    const pe = ctx.outline('Parameter Estimates', { key: 'est' });
    pe.add(ctx.rt(res.estimates, { sortable: false }));
    if (res.shape) pe.add(ctx.kv([['Weibull shape β = 1/σ', res.shape.estimate], [`Lower ${pct(ctx.alpha)}`, res.shape.lower], [`Upper ${pct(ctx.alpha)}`, res.shape.upper]]));
    pe.add(ctx.note(`${res.logt ? 'log(time)' : 'time'} = x·β + σ·ε, ε a standard ${{ weibull: 'smallest extreme value', exponential: 'smallest extreme value (σ = 1)', lognormal: 'normal', loglogistic: 'logistic', frechet: 'largest extreme value', normal: 'normal', logistic: 'logistic', sev: 'smallest extreme value', lev: 'largest extreme value' }[res.dist]} variable: a positive estimate means longer times. Wald limits; nominal effects effect coded.`));
    if (res.lr && res.lr.rows.length) ctx.outline('Effect Likelihood Ratio Tests', { key: 'lr' }).add(ctx.rt(res.lr, { sortable: false }), ctx.note('Each effect: the model refitted without it.'));
    if (res.corr) ctx.outline('Correlation of Estimates', { key: 'corr', menu: () => [{ label: 'Remove', action: () => ctx.set('corr', false) }] }).add(ctx.rt(res.corr, { sortable: false }));
    ctx.container.append(ctx.code(res.code));
  }

  function parametricMenu(ctx) {
    const y = ctx.name('y');
    const save = async (what) => {
      const v = await SM.ui.form({ title: what === 'quantile' ? 'Save Quantiles' : 'Save Survival Probabilities', fields: [what === 'quantile'
        ? { key: 'v', label: 'Failure probability (0 to 1)', type: 'number', value: 0.5, help: 'A fraction failed, strictly between 0 and 1 (0.5 for the median): the new column holds, for each row, the time by which that fraction of units with its effects has failed, from the fitted model.' }
        : { key: 'v', label: `Time (${y})`, type: 'number', value: null, help: 'A time: the new column holds, for each row, the probability that a unit with its effects survives past it, S(t | x), from the fitted model.' }] });
      if (!v || v.v == null || (what === 'quantile' && !(v.v > 0 && v.v < 1))) return;
      const r = await ctx.call('parametric.save', { ...parametricPayload(ctx), what, value: v.v });
      if (r.error) { SM.ui.toast(r.error, { error: true }); return; }
      saveFrom(ctx, what === 'quantile' ? `${fmt(v.v)} Quantile ${y}` : `Survival at ${fmt(v.v)} ${y}`, r, { notes: `${DIST_LABEL[ctx.opt('dist', 'weibull')]} regression` });
    };
    return [
      { label: 'Distribution', submenu: () => DISTS.map(([k, l]) => ({ label: l, checked: ctx.opt('dist', 'weibull') === k, action: () => ctx.set('dist', k) })) },
      ctx.check('Correlation of Estimates', 'corr', null, false),
      { separator: true },
      { label: 'Save Quantiles…', action: () => save('quantile') },
      { label: 'Save Survival Probabilities…', action: () => save('survival') },
    ];
  }

  /* ========================================================================
     FIT CURVE
     ======================================================================== */
  const CURVES = [
    ['Polynomials', [['linear', 'Fit Linear'], ['quadratic', 'Fit Quadratic'], ['cubic', 'Fit Cubic'], ['quartic', 'Fit Quartic'], ['quintic', 'Fit Quintic']]],
    ['Sigmoid Curves', [['logistic2', 'Logistic 2P'], ['logistic3', 'Logistic 3P'], ['logistic4', 'Logistic 4P'], ['logistic5', 'Logistic 5P'], null,
      ['probit2', 'Probit 2P'], ['probit4', 'Probit 4P'], null, ['gompertz3', 'Gompertz 3P'], ['gompertz4', 'Gompertz 4P'], null, ['weibullgrowth', 'Weibull Growth']]],
    ['Exponential Growth and Decay', [['exp2', 'Exponential 2P'], ['exp3', 'Exponential 3P'], ['biexp4', 'Biexponential 4P'], ['biexp5', 'Biexponential 5P'], ['mechanistic', 'Mechanistic Growth']]],
    ['Peak Models', [['gaussian', 'Gaussian Peak'], ['lorentzian', 'Lorentzian Peak']]],
    ['Pharmacokinetic Models', [['onecomp', 'One Compartment Oral Dose']]],
    ['Other', [['michaelis', 'Michaelis-Menten'], ['power', 'Power'], ['log', 'Logarithmic']]],
  ];
  const CURVE_LABEL = Object.fromEntries(CURVES.flatMap(([, items]) => items.filter(Boolean)));
  // models whose curves can be parallel: a shift parameter (inflection or critical point, or the intercept)
  const HAS_SHIFT = new Set(['linear', 'quadratic', 'cubic', 'quartic', 'quintic', 'logistic2', 'logistic3', 'logistic4', 'logistic5', 'probit2', 'probit4', 'gompertz3', 'gompertz4', 'gaussian', 'lorentzian']);

  /* The rows of the plot: x and y present, weight and freq positive, per group. */
  function curvePoints(ctx) {
    const x = ctx.role('x'), y = ctx.role('y'), g = ctx.role('group'), w = ctx.role('weight'), f = ctx.role('freq');
    const levels = g ? ctx.table.levels(g) : [null];
    const idx = new Map(levels.map((v, i) => [v, i]));
    const out = levels.map((v) => ({ level: v, label: g ? levelLabel(g, v) : '', x: [], y: [], rows: [] }));
    for (const r of ctx.rows) {
      const xv = x.values[r], yv = y.values[r];
      if (!finite(xv) || !finite(yv)) continue;
      if (w && !(w.values[r] > 0)) continue;
      if (f && !(f.values[r] > 0)) continue;
      const k = g ? idx.get(g.values[r]) : 0;
      if (k == null) continue;
      out[k].x.push(xv); out[k].y.push(yv); out[k].rows.push(r);
    }
    return out.filter((o) => o.rows.length);
  }

  function curvePlot(ctx, pts, fitted, { ci = false, single = null, color: own = null } = {}) {
    const grouped = !!ctx.role('group');
    const traces = [];
    const gColor = (i) => (grouped ? PALETTE[i % PALETTE.length] : SM.report.BASE);
    const levelIndex = new Map(pts.map((p, i) => [p.level, i]));
    fitted.forEach((m, mi) => {
      if (!m.res || m.res.error) return;
      const mc = FIT_COLORS[mi % FIT_COLORS.length];
      for (const g of m.res.groups) {
        if (!g.curve) continue;
        const gi = levelIndex.get(g.level) ?? 0;
        const color = grouped ? gColor(gi) : (own || mc);
        const x = nums(g.curve.x);
        if (ci && g.curve.lower) {
          traces.push({ type: 'scatter', mode: 'lines', x, y: nums(g.curve.lower), line: { width: 0, color }, hoverinfo: 'skip', showlegend: false });
          traces.push({ type: 'scatter', mode: 'lines', x, y: nums(g.curve.upper), line: { width: 0, color }, fill: 'tonexty', fillcolor: rgba(color, 0.14), hoverinfo: 'skip', showlegend: false });
        }
        traces.push({ type: 'scatter', mode: 'lines', x, y: nums(g.curve.y), line: { color, width: 2, dash: grouped && !single ? ['solid', 'dash', 'dot', 'dashdot'][mi % 4] : 'solid' },
          name: grouped ? `${m.label} ${levelLabel(ctx.role('group'), g.level)}` : m.label, showlegend: !grouped && !single, hovertemplate: `${m.label}${grouped ? ` ${levelLabel(ctx.role('group'), g.level)}` : ''}<br>%{x}: %{y:.5g}<extra></extra>` });
      }
    });
    pts.forEach((p, i) => traces.push({ type: 'scatter', mode: 'markers', x: p.x, y: p.y, rows: p.rows, name: p.label || ctx.name('y'), showlegend: grouped, marker: { color: gColor(i), size: 6 } }));
    const legend = { x: 0, xanchor: 'left', y: 1, bgcolor: 'rgba(0,0,0,0)', traceorder: 'normal' };
    const width = fitWidth(ctx, single ? 440 : 540), height = single ? 300 : 360;
    const graph = ctx.plot(traces, { xaxis: { title: { text: ctx.name('x') } }, yaxis: { title: { text: ctx.name('y') } }, showlegend: grouped || (!single && fitted.length > 0), legend },
      { width, height, title: `${ctx.name('y')} by ${ctx.name('x')}${single ? ` ${single}` : ''}` });
    return [graph, ctx.code(curveCode(ctx, pts, fitted, { ci, single, color: own, width, height }))];
  }

  /* Fit Curve's plot as code (curvePlot): the rows, each model's fragment
     (res.plot: the model and the function that fits it, as the report's code
     fits it, to a group's rows), each group's fit from the report's
     estimates, the curves and the points in the page's colours. */
  function curveCode(ctx, pts, fitted, { ci = false, single = null, color: own = null, width, height }) {
    const grouped = !!ctx.role('group');
    const gcol = ctx.role('group');
    const x = ctx.name('x'), y = ctx.name('y'), w = ctx.name('weight'), f = ctx.name('freq');
    const ok = fitted.filter((m) => m.res && !m.res.error && m.res.plot);
    const imports = ['import matplotlib.pyplot as plt', ...new Set(ok.flatMap((m) => m.res.plot.imports))];
    const L = [SM.report.codeHead(ctx.table.name, imports), ...whereLines(ctx), `X, Y = ${J(x)}, ${J(y)}`,
      `d = df.dropna(subset=${J([...new Set([x, y, gcol && gcol.name, w, f].filter(Boolean))])})   # the rows with every value`];
    if (w || f) L.push(`d = d[${[w, f].filter(Boolean).map((c) => `d[${J(c)}]`).join(' * ')} > 0]   # the rows with a positive weight`);
    for (const m of ok) L.push('', ...m.res.plot.lines);
    const levelIndex = new Map(pts.map((p, i) => [p.level, i]));
    const gColor = (i) => (grouped ? PALETTE[i % PALETTE.length] : LIGHT_BASE);
    const legendCurves = !grouped && !single;
    const rowsOf = (level) => (grouped ? `d[d[${J(gcol.name)}] == ${pyLit(level)}]` : 'd');
    L.push('', `fig, ax = plt.subplots(figsize=(${inches(width)}, ${inches(height)}), layout="constrained")`);
    ok.forEach((m) => {
      const mi = fitted.indexOf(m);
      for (const g of m.res.groups) {
        if (!g.curve || g.error || !g.params) continue;
        const gi = levelIndex.get(g.level) ?? 0;
        const color = grouped ? gColor(gi) : (own || FIT_COLORS[mi % FIT_COLORS.length]);
        const ls = grouped && !single ? MPL_DASH[mi % 4] : '-';
        L.push(`s = ${rowsOf(g.level)}${grouped ? `   # ${gcol.name} ${levelLabel(gcol, g.level)}` : ''}`,
          `gx, fy, lo, hi = ${m.res.plot.fit}(s, [${g.params.map((v) => pyNum(num(v))).join(', ')}])   # ${m.label}, from the report's estimates`);
        if (ci && g.curve.lower) L.push(`ax.fill_between(gx, lo, hi, color="${color}", alpha=0.14, linewidth=0)   # Confidence Curves`);
        L.push(`ax.plot(gx, fy, color="${color}", linewidth=2${ls !== '-' ? `, linestyle="${ls}"` : ''}${legendCurves ? `, label=${J(m.label)}` : ''})`);
      }
    });
    pts.forEach((p, i) => L.push(`s = ${rowsOf(p.level)}`, `ax.scatter(s[X], s[Y], s=24, color="${gColor(i)}", zorder=3${grouped ? `, label=${J(p.label)}` : ''})   # the rows`));
    L.push('ax.set_xlabel(X)', 'ax.set_ylabel(Y)');
    if (grouped || (!single && fitted.length > 0)) L.push('ax.legend(loc="upper left", frameon=False, fontsize=8)');
    L.push(`fig.suptitle(${J(`${y} by ${x}${single ? ` ${single}` : ''}`)}, fontsize=10)`, 'plt.show()');
    return L.join('\n');
  }

  async function renderCurve(ctx) {
    const first = ctx.opt('first', '');
    const models = ctx.opt('models', first ? [first] : []);
    const grouped = !!ctx.role('group');
    const glabel = (v) => levelLabel(ctx.role('group'), v);
    const pts = curvePoints(ctx);
    const fitted = [];
    for (const m of models) {
      const payload = { y: ctx.name('y'), x: ctx.name('x'), group: ctx.name('group'), weight: ctx.name('weight'), freq: ctx.name('freq'), model: m, alpha: ctx.alpha,
        ci: ctx.opt(`ci:${m}`, false), parallel: grouped && ctx.opt(`par:${m}`, false), equal: grouped && ctx.opt(`eq:${m}`, false), inverse: ctx.opt(`inv:${m}`, null), where: whereOf(ctx) };
      let res;
      try { res = await ctx.call('fitcurve.fit', payload); } catch (e) { res = { error: e.message }; }
      fitted.push({ key: m, label: CURVE_LABEL[m] || m, res });
    }
    ctx.curveFits = fitted;
    const plotOb = ctx.outline('Plot', { key: 'plot' });
    plotOb.add(curvePlot(ctx, pts, fitted));
    if (!models.length) plotOb.add(ctx.note('Choose a model from the red triangle of Fit Curve: polynomials, sigmoid curves, exponential growth and decay, peaks, a pharmacokinetic model, and more. Each gets automatic starting values.'));
    else if (grouped && models.length > 1) plotOb.add(ctx.note(`Curves in the colour of their group: ${fitted.map((m, i) => `${m.label} ${['solid', 'dashed', 'dotted', 'dash-dotted'][i % 4]}`).join(', ')}.`));
    // ---- Model Comparison
    const ok = fitted.filter((m) => m.res && !m.res.error && m.res.summary);
    if (ok.length) {
      const best = Math.min(...ok.map((m) => num(m.res.summary.aicc)).filter(finite));
      const wsum = ok.reduce((a, m) => a + (finite(num(m.res.summary.aicc)) ? Math.exp(-0.5 * (num(m.res.summary.aicc) - best)) : 0), 0);
      const rows = ok.map((m) => { const s = m.res.summary; const a = num(s.aicc); return { model: m.label, key: m.key, aicc: a, w: finite(a) && wsum > 0 ? Math.exp(-0.5 * (a - best)) / wsum : null, bic: num(s.bic), sse: s.sse, mse: num(s.mse), rmse: num(s.rmse), r2: num(s.rsquare) }; })
        .sort((a, b) => (finite(a.aicc) ? a.aicc : Infinity) - (finite(b.aicc) ? b.aicc : Infinity));
      ctx.outline('Model Comparison', { key: 'compare' }).add(ctx.rt({ columns: [{ key: 'model', label: 'Model', fmt: 'text' }, { key: 'aicc', label: 'AICc' }, { key: 'w', label: 'AICc Weight' }, { key: 'bic', label: 'BIC' },
        { key: 'sse', label: 'SSE' }, { key: 'mse', label: 'MSE' }, { key: 'rmse', label: 'RMSE' }, { key: 'r2', label: 'R-Square' }], rows }),
      ctx.note('Best first by AICc. The error variance counts as a parameter; with a Group, a model has its parameters once per group.'));
    }
    // ---- one outline per model
    fitted.forEach((m, mi) => {
      const res = m.res;
      const ob = ctx.outline(m.label, { key: `m:${m.key}`, menu: () => curveModelMenu(ctx, m, models) });
      if (!grouped) {   // without groups, the model's colour marks its outline and its curves
        ob.head.style.setProperty('--fit-color', FIT_COLORS[mi % FIT_COLORS.length]);
        ob.el.classList.add('sm-curve-fit');
      }
      if (!res || res.error) { ob.add(ctx.warn(`${m.label}: ${(res && res.error) || 'no fit'}`)); return; }
      ob.add(curvePlot(ctx, pts, [m], { ci: ctx.opt(`ci:${m.key}`, false), single: m.label, color: FIT_COLORS[mi % FIT_COLORS.length] }));
      ctx.outline('Prediction Model', { parent: ob, key: `pm:${m.key}` }).add(el('p', { class: 'sm-curve-formula', text: `${ctx.name('y')} = ${res.formula}` }), ctx.note(res.letters.join(', ')));
      const errs = res.groups.filter((g) => g.error);
      for (const g of errs) ob.add(ctx.warn(`${grouped ? `${glabel(g.level)}: ` : ''}${g.error}`));
      const good = res.groups.filter((g) => !g.error);
      const sm = ctx.outline('Summary', { parent: ob, key: `sum:${m.key}` });
      if (grouped) {
        sm.add(ctx.rt({ columns: [{ key: 'group', label: 'Group', fmt: 'text' }, { key: 'n', label: 'N', fmt: 'int' }, { key: 'aicc', label: 'AICc' }, { key: 'bic', label: 'BIC' }, { key: 'sse', label: 'SSE' },
          { key: 'mse', label: 'MSE' }, { key: 'rmse', label: 'RMSE' }, { key: 'r2', label: 'R-Square' }],
        rows: [...good.map((g) => ({ group: glabel(g.level), n: g.summary.n, aicc: num(g.summary.aicc), bic: num(g.summary.bic), sse: g.summary.sse, mse: num(g.summary.mse), rmse: num(g.summary.rmse), r2: num(g.summary.rsquare) })),
          { group: 'All groups', n: res.summary.n, aicc: num(res.summary.aicc), bic: num(res.summary.bic), sse: res.summary.sse, mse: num(res.summary.mse), rmse: num(res.summary.rmse), r2: num(res.summary.rsquare) }] }, { sortable: false }));
      } else {
        const s = res.summary;
        sm.add(ctx.kv([['AICc', num(s.aicc)], ['BIC', num(s.bic)], ['SSE', s.sse], ['MSE', num(s.mse)], ['RMSE', num(s.rmse)], ['R-Square', num(s.rsquare)], ['N', s.n, 'int']]));
      }
      const est = [];
      for (const g of good) for (const e of g.estimates) est.push({ group: glabel(g.level), ...e });
      const cols = [{ key: 'parameter', label: 'Parameter', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'lower', label: `Lower ${pct(ctx.alpha)}` },
        { key: 'upper', label: `Upper ${pct(ctx.alpha)}` }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }];
      ctx.outline('Parameter Estimates', { parent: ob, key: `pe:${m.key}` }).add(ctx.rt({ columns: grouped ? [{ key: 'group', label: 'Group', fmt: 'text' }, ...cols] : cols, rows: est }, { sortable: false }),
        ctx.note('Least squares (scipy least_squares, Levenberg-Marquardt); standard errors from MSE·(J′J)⁻¹, Wald limits on the t distribution.'));
      if (res.parallel) {
        const P = res.parallel;
        const po = ctx.outline('Test Parallelism', { parent: ob, key: `par:${m.key}`, menu: () => [{ label: 'Remove', action: () => ctx.set(`par:${m.key}`, false) }] });
        if (P.error) po.add(ctx.warn(P.error));
        else {
          po.add(ctx.kv([['F Ratio', num(P.F)], ['DF Num', P.df1, 'int'], ['DF Den', P.df2, 'int'], ['Prob > F', num(P.p), 'p'], ['SSE parallel', P.sse_parallel], ['SSE separate', P.sse_separate]]),
            ctx.rt({ caption: 'Parallel Model', columns: cols, rows: P.estimates }, { sortable: false }),
            ctx.note(`The parallel model shares every parameter but ${P.shift}, which each group has its own; the F test compares it with separate curves. A small p-value says the curves are not parallel.`));
        }
      }
      if (res.equal) {
        const E = res.equal;
        const eo = ctx.outline('Test Equal Parameters', { parent: ob, key: `eq:${m.key}`, menu: () => [{ label: 'Remove', action: () => ctx.set(`eq:${m.key}`, false) }] });
        if (E.error) eo.add(ctx.warn(E.error));
        else eo.add(ctx.kv([['F Ratio', num(E.F)], ['DF Num', E.df1, 'int'], ['DF Den', E.df2, 'int'], ['Prob > F', num(E.p), 'p'], ['SSE one curve', E.sse_common], ['SSE separate', E.sse_separate]]),
          ctx.note('One curve for every group against a curve per group. A small p-value says the groups differ.'));
      }
      const inv = ctx.opt(`inv:${m.key}`, null);
      if (inv && inv.length) {
        const io = ctx.outline('Inverse Prediction', { parent: ob, key: `inv:${m.key}`, menu: () => [{ label: 'Remove', action: () => ctx.set(`inv:${m.key}`, null) }] });
        const rows = [];
        for (const g of good) for (const r of g.inverse || []) rows.push({ group: glabel(g.level), y: r.y, x: num(r.x), lower: num(r.lower), upper: num(r.upper), note: r.note || '' });
        io.add(ctx.rt({ columns: [...(grouped ? [{ key: 'group', label: 'Group', fmt: 'text' }] : []), { key: 'y', label: ctx.name('y') }, { key: 'x', label: `Predicted ${ctx.name('x')}` },
          { key: 'lower', label: `Lower ${pct(ctx.alpha)}` }, { key: 'upper', label: `Upper ${pct(ctx.alpha)}` }, { key: 'note', label: '', fmt: 'text' }], rows }, { sortable: false }),
        ctx.note('Where the fitted curve reaches each value (up to three crossings within the data\'s range and a quarter beyond), with delta-method limits from the parameters\' uncertainty.'));
      }
      ob.add(ctx.code(res.code));
    });
  }

  function curveModelMenu(ctx, m, models) {
    const grouped = !!ctx.role('group');
    const y = ctx.name('y');
    return [
      ctx.check('Confidence Curves', `ci:${m.key}`, null, false),
      grouped ? ctx.check('Test Parallelism', `par:${m.key}`, null, false, { disabled: !HAS_SHIFT.has(m.key) }) : null,
      grouped ? ctx.check('Test Equal Parameters', `eq:${m.key}`, null, false) : null,
      { label: 'Custom Inverse Prediction…', action: () => askList(ctx, `Inverse Prediction: ${m.label}`, `Values of ${y}, separated by commas`, `inv:${m.key}`, [], null,
        `Up to 20 values of ${y}: the ${ctx.name('x')} at which the fitted curve reaches each (up to three crossings within the data's range and a quarter of it beyond), with delta-method limits from the uncertainty of the parameters. Empty: the outline is removed.`) },
      { separator: true },
      { label: 'Save Prediction', action: () => { if (m.res && m.res.pred) saveFrom(ctx, `Predicted ${y} (${m.label})`, m.res.pred, { notes: `Fit Curve ${m.label}` }); } },
      { label: 'Save Residuals', action: () => { if (m.res && m.res.resid) saveFrom(ctx, `Residual ${y} (${m.label})`, m.res.resid, { notes: `Fit Curve ${m.label}` }); } },
      { separator: true },
      { label: 'Remove Fit', action: () => ctx.set('models', models.filter((k) => k !== m.key)) },
    ].filter(Boolean);
  }

  function curveMenu(ctx) {
    const first = ctx.opt('first', '');
    const models = ctx.opt('models', first ? [first] : []);
    const toggle = (k) => ctx.set('models', models.includes(k) ? models.filter((x) => x !== k) : [...models, k]);
    return CURVES.map(([family, items]) => ({ label: family, submenu: () => items.map((it) => (it ? { label: it[1], checked: models.includes(it[0]), action: () => toggle(it[0]) } : { separator: true })) }))
      .concat([{ separator: true }, { label: 'Remove All Fits', disabled: !models.length, action: () => ctx.set('models', []) }]);
  }

  /* ========================================================================
     NONLINEAR
     ======================================================================== */
  /* "a = 1, b = 0.1; c = 0" to { a: 1, b: 0.1, c: 0 } */
  function parseStart(text) {
    const out = {};
    for (const part of String(text || '').split(/[,;\n]+/)) {
      const m = /^\s*([^\s=:]+)\s*[=:]\s*(\S+)\s*$/.exec(part);
      if (m) { const v = Number(m[2].replace(/−/g, '-')); if (Number.isFinite(v)) out[m[1]] = v; }
    }
    return out;
  }
  const startText = (obj) => Object.entries(obj).map(([k, v]) => `${k} = ${fmt(v, { sig: 10 })}`).join(', ');
  const NL_HELP = {
    model: 'The model of Y: an expression in parameters, columns and numbers, for example a * exp(-b * :dose) + c. A column is written :name, or :"name with spaces"; every other name is a parameter (a plain name that is a column and has no starting value is the column). + − * / and ^ for powers, comparisons inside where(condition, a, b), and the functions listed; anything else is refused, and nothing is run as code.',
    start: 'A starting value for each parameter, as name = value, separated by commas (a = 1, b = 0.1). A parameter without one starts at 1. Least squares iterates from these values: from a poor start it can stop at a local minimum, or fail to converge.',
    find: 'Reads the model and lists its parameters and columns; each parameter keeps the starting value already typed, or gets 1. Set the values before OK.',
  };

  function nonlinearExtra(api, spec) {
    const model = el('textarea', { class: 'sm-nl-model', rows: 3, spellcheck: 'false', 'aria-label': 'Model', placeholder: 'a * exp(-b * :dose) + c' });
    const start = el('input', { type: 'text', class: 'sm-nl-start', spellcheck: 'false', 'aria-label': 'Parameters and starting values', placeholder: 'a = 1, b = 0.1, c = 0' });
    const o = (spec && spec.options) || {};
    model.value = o.model || '';
    start.value = o.start || '';
    const find = el('button', { type: 'button', class: 'sm-btn small', text: 'Find Parameters' });
    const found = el('p', { class: 'sm-nl-found', 'aria-live': 'polite' });
    find.addEventListener('click', async () => {
      found.textContent = '';
      api.message('');
      if (!model.value.trim()) { api.message('Type the model first.'); return; }
      try {
        const r = await SM.engine.call('nonlinear.parse', { model: model.value, declared: Object.keys(parseStart(start.value)) }, api.table);
        if (r.error) { api.message(r.error); return; }
        const cur = parseStart(start.value);
        const next = {};
        for (const p of r.params) next[p] = cur[p] ?? 1;
        start.value = startText(next);
        found.textContent = `Parameters: ${r.params.join(', ')}; columns: ${r.columns.join(', ') || 'none'}. Set the starting values before OK.`;
      } catch (e) { api.message(e.message); }
    });
    const box = el('div', { class: 'sm-nl-extra' },
      el('label', { class: 'sm-nl-label' }, 'Model: parameters, columns (:name, or :"name with spaces"), numbers, + − * / ^ and exp, log, log10, sqrt, abs, sin, cos, tan, arctan, tanh, minimum, maximum, where', model),
      el('label', { class: 'sm-nl-label' }, 'Parameters and starting values', el('div', { class: 'sm-nl-startrow' }, start, find)), found);
    return {
      el: box,
      help: [['Model', NL_HELP.model], ['Parameters and starting values', NL_HELP.start], ['Find Parameters', NL_HELP.find]],
      helpHeading: 'The model',
      read: () => ({ options: { model: model.value, start: start.value } }),
      recall: (s) => { if (s && s.options) { model.value = s.options.model || ''; start.value = s.options.start || ''; } },
    };
  }

  function nonlinearPayload(ctx) {
    return { y: ctx.name('y'), model: ctx.opt('model', ''), start: parseStart(ctx.opt('start', '')), weight: ctx.name('weight'), freq: ctx.name('freq'),
      method: ctx.opt('method', 'lm'), max_nfev: ctx.opt('maxEval', null), alpha: ctx.alpha, ci: ctx.opt('ci', false), where: whereOf(ctx), plot: { size: [fitWidth(ctx, 480), 320] } };
  }

  async function renderNonlinear(ctx) {
    const res = await ctx.call('nonlinear.fit', nonlinearPayload(ctx));
    ctx.nlRes = res;
    const mo = ctx.outline('Model', { key: 'model', info: 'p:nonlinear-model' });
    mo.add(el('pre', { class: 'sm-curve-formula', text: `${ctx.name('y')} = ${ctx.opt('model', '')}` }));
    if (res.error) { mo.add(ctx.warn(res.error)); return; }
    const st = res.status;
    mo.add(ctx.rt({ caption: 'Starting Values', columns: [{ key: 'p', label: 'Parameter', fmt: 'text' }, { key: 'v', label: 'Start' }, { key: 'e', label: 'Estimate' }],
      rows: res.params.map((p, i) => ({ p, v: res.start[i], e: num(res.estimates_raw[i]) })) }, { sortable: false }));
    if (res.missing_start.length) mo.add(ctx.warn(`No starting value for ${res.missing_start.join(', ')}: started at 1. Edit Model… sets them.`));
    mo.add(el('p', { class: `sm-nl-status${st.converged ? '' : ' is-bad'}`, text: `${st.converged ? 'Converged' : 'Did not converge'}: ${st.message} ${st.nfev} function evaluations (${st.method === 'lm' ? 'Levenberg-Marquardt' : st.method === 'trf' ? 'trust region reflective' : 'dogbox'}), first-order optimality ${fmt(num(st.optimality))}.` }));
    if (res.curve) {
      const xc = ctx.table.col(res.x), yc = ctx.role('y');
      const px = [], py = [], pr = [];
      for (const r of res.resid.rows) { px.push(xc.values[r]); py.push(yc.values[r]); pr.push(r); }
      const traces = [];
      if (res.curve.lower) {
        traces.push({ type: 'scatter', mode: 'lines', x: nums(res.curve.x), y: nums(res.curve.lower), line: { width: 0, color: FIT_COLORS[0] }, hoverinfo: 'skip', showlegend: false });
        traces.push({ type: 'scatter', mode: 'lines', x: nums(res.curve.x), y: nums(res.curve.upper), line: { width: 0, color: FIT_COLORS[0] }, fill: 'tonexty', fillcolor: rgba(FIT_COLORS[0], 0.14), hoverinfo: 'skip', showlegend: false });
      }
      traces.push({ type: 'scatter', mode: 'lines', x: nums(res.curve.x), y: nums(res.curve.y), line: { color: FIT_COLORS[0], width: 2 }, name: 'Fit', hovertemplate: '%{x}: %{y:.5g}<extra></extra>' });
      traces.push({ type: 'scatter', mode: 'markers', x: px, y: py, rows: pr, name: ctx.name('y'), marker: { size: 6 } });
      ctx.outline('Plot', { key: 'plot' }).add(ctx.plot(traces, { xaxis: { title: { text: res.x } }, yaxis: { title: { text: ctx.name('y') } } }, { width: fitWidth(ctx, 480), height: 320, title: `${ctx.name('y')} by ${res.x}` }),
        ctx.code(res.plot_code));
    }
    const s = res.solution;
    ctx.outline('Solution', { key: 'solution' }).add(ctx.kv([['SSE', s.sse], ['DFE', s.dfe, 'int'], ['MSE', num(s.mse)], ['RMSE', num(s.rmse)], ['R-Square', num(s.rsquare)], ['AICc', num(s.aicc)], ['N', s.n, 'int']]));
    ctx.outline('Parameter Estimates', { key: 'est' }).add(ctx.rt(res.estimates, { sortable: false }),
      ctx.note('Approximate standard errors from MSE·(J′J)⁻¹, J the Jacobian at the estimates (central differences); Wald limits on the t distribution. JMP\'s Nonlinear limits are profile likelihood limits by default; for nearly linear parameters the two agree.'));
    if (ctx.opt('corr', true)) ctx.outline('Correlation of Estimates', { key: 'corr', menu: () => [{ label: 'Remove', action: () => ctx.set('corr', false) }] }).add(ctx.rt(res.corr, { sortable: false }));
    ctx.container.append(ctx.code(res.code));
  }

  function nonlinearMenu(ctx) {
    const y = ctx.name('y');
    return [
      { label: 'Edit Model…', action: async () => {
        const v = await SM.ui.form({ title: 'Edit Model', info: 'p:nonlinear-model', fields: [{ key: 'model', label: 'Model', type: 'textarea', value: ctx.opt('model', ''), help: NL_HELP.model },
          { key: 'start', label: 'Parameters and starting values', value: ctx.opt('start', ''), full: true, help: NL_HELP.start }] });
        if (v) { ctx.set('model', v.model, null, { rerun: false }); ctx.set('start', v.start); }
      } },
      { label: 'Use Estimates as Starting Values', disabled: !(ctx.nlRes && ctx.nlRes.estimates_raw), action: () => { const r = ctx.nlRes; ctx.set('start', startText(Object.fromEntries(r.params.map((p, i) => [p, num(r.estimates_raw[i])])))); } },
      { label: 'Fit Options…', action: async () => {
        const v = await SM.ui.form({ title: 'Fit Options', fields: [
          { key: 'method', label: 'Method', type: 'select', value: ctx.opt('method', 'lm'), choices: [['lm', 'Levenberg-Marquardt'], ['trf', 'Trust region reflective'], ['dogbox', 'Dogbox']],
            help: 'The algorithm of scipy\'s least_squares: Levenberg-Marquardt (MINPACK\'s, the default: usually the fastest for a small problem), Trust region reflective (scipy\'s general method) or Dogbox. Another method can converge where one does not.' },
          { key: 'maxEval', label: 'Maximum function evaluations (empty: automatic)', type: 'number', value: ctx.opt('maxEval', null),
            help: 'The most evaluations of the model the fit may make before it stops and says that it did not converge. Empty: 400 × (the number of parameters + 1).' }] });
        if (v) { ctx.set('method', v.method, null, { rerun: false }); ctx.set('maxEval', v.maxEval > 0 ? Math.round(v.maxEval) : null); }
      } },
      ctx.check('Confidence Curves', 'ci', null, false),
      ctx.check('Correlation of Estimates', 'corr', null, true),
      { separator: true },
      { label: 'Save Prediction', action: () => { const r = ctx.nlRes; if (r && r.pred) saveFrom(ctx, `Predicted ${y}`, r.pred, { notes: `Nonlinear: ${ctx.opt('model', '')}` }); } },
      { label: 'Save Residuals', action: () => { const r = ctx.nlRes; if (r && r.resid) saveFrom(ctx, `Residual ${y}`, r.resid, { notes: `Nonlinear: ${ctx.opt('model', '')}` }); } },
    ];
  }

  /* ========================================================================
     THE (i) TOPICS
     ======================================================================== */
  const topics = {
    'p:survival': {
      kicker: 'Analyze', title: 'Survival',
      lead: 'Kaplan-Meier (product-limit) estimates of the survival function from times to an event, some of them right censored: the event had not happened by that time.',
      sections: [
        { heading: 'Roles', choices: [['Y, Time to Event', 'The time: of the failure, or of the censoring.'], ['Grouping', 'One curve per level, and tests of whether they differ.'], ['Censor', 'A column whose value equals the Censor Code (1 unless set) on censored rows; without it every time is a failure.'], ['Freq', 'A whole-number count per row.'], ['By', 'A separate analysis for each level.']] },
        { heading: 'The report', text: 'The survival plot (censored rows are ticks; click or drag to select them), the Summary with the restricted mean and the median with its interval, Tests Between Groups (log-rank and weighted tests), the product-limit estimates. The red triangle adds the failure plot, confidence bands, the exponential, Weibull and lognormal plots and fits, estimates at chosen times or probabilities, and Save Estimates, a new table of the estimates.' },
        { heading: 'Against JMP', text: 'Pointwise intervals are Greenwood\'s on the log(−log) scale; the median\'s interval inverts log(−log) tests (SAS\'s method); the Wilcoxon test is Gehan-Breslow\'s. JMP\'s may differ in these; the Python under each result says how these are computed.' },
      ],
      more: { label: 'Survival', id: 'help-p-survival' },
    },
    'p:survival-tests': {
      kicker: 'Survival', title: 'Tests Between Groups',
      lead: 'Whether the survival curves of the groups differ, from the observed and expected failures of each group at each failure time (statsmodels survdiff), a χ² with groups − 1 degrees of freedom.',
      sections: [{ heading: 'The weights', choices: [['Log-Rank', 'Every failure time counts alike: strongest when the hazards are proportional.'], ['Wilcoxon', 'Gehan-Breslow: weighted by the number at risk, so early differences count more.'], ['Tarone-Ware', 'Weighted by the square root of the number at risk: in between.'], ['Fleming-Harrington (ρ = 1)', 'Weighted by the pooled survival just before each time, like Peto-Prentice\'s Wilcoxon.']] }],
    },
    'p:phreg': {
      kicker: 'Analyze', title: 'Fit Proportional Hazards',
      lead: 'Cox regression: the hazard of each subject is a common baseline hazard times exp(x·β), estimated from the partial likelihood without assuming a distribution for the times (statsmodels PHReg).',
      sections: [
        { heading: 'Roles', choices: [['Time to Event', 'The failure or censoring time.'], ['Censor', 'The censored rows carry the Censor Code.'], ['Model Effects', 'Continuous columns enter as they are; nominal and ordinal ones are effect coded.'], ['Freq', 'Whole-number counts: each row counts that many times.']] },
        { heading: 'The report', text: 'Whole Model (likelihood ratio against no effects), Parameter Estimates (log hazard ratios, Wald limits), Effect Likelihood Ratio Tests (each effect refitted out), Risk Ratios (per unit, per range, and between levels), the baseline survival at the means. Ties: Breslow (default) or Efron.' },
      ],
      more: { label: 'Fit Proportional Hazards', id: 'help-p-phreg' },
    },
    'p:lifedist': {
      kicker: 'Analyze', title: 'Life Distribution',
      lead: 'Fits distributions to times to failure, with right censoring, and shows them on probability paper against the nonparametric estimate.',
      sections: [
        { heading: 'Distributions', text: 'Weibull, Lognormal, Exponential, Fréchet and Loglogistic are location-scale models for log(time); Normal, SEV (smallest extreme value), Logistic and LEV (largest) for the time itself. Each is fitted by maximum likelihood (failures by their density, censored rows by their survival) with statsmodels GenericLikelihoodModel.' },
        { heading: 'The report', text: 'Compare Distributions: tick the distributions, pick the probability scale. Statistics: the data, the nonparametric estimate, each fit\'s parameters with Wald limits (log scale for σ), −2 log L, AICc and BIC, and the Model Comparisons. The Distribution Calculator gives the failure probability at a time and the time at a probability, with limits.' },
      ],
      more: { label: 'Life Distribution', id: 'help-p-lifedist' },
    },
    'p:lifedist-scale': {
      kicker: 'Life Distribution', title: 'Probability scales',
      lead: 'On a distribution\'s probability paper its CDF is a straight line: the vertical axis is Φ⁻¹(F) of the distribution\'s standard form, the horizontal axis log(time) for the log-time families.',
      sections: [
        { heading: 'The table beside the plot', choices: [['Show', 'Fits the distribution and draws its curve (its Parametric Estimate outline appears under Statistics); unticked, the fit is dropped. Nonparametric: the Kaplan-Meier points.'], ['Scale', 'The probability paper: the vertical axis on that distribution\'s scale, the horizontal one log(time) for the log-time families; Nonparametric is a plain probability axis. The pointwise bands are drawn for the fitted distribution whose scale is shown.']] },
        { heading: 'Reading it', list: ['Points close to a straight line on a scale: that distribution describes the data.', 'The points are the nonparametric estimate of the failure probability at each failure, at the middle of its jump (Meeker and Escobar\'s plotting position).', 'The Exponential scale plots −log(1 − F) against the time: an exponential fit is a line through the origin.', 'Click a line of Model Comparisons to show that distribution\'s scale.'] },
      ],
    },
    'p:lifedist-calc': {
      kicker: 'Life Distribution', title: 'Distribution Calculator',
      lead: 'Failure probabilities and quantiles of every fitted distribution, with Wald limits by the delta method at the report\'s 1 − α.',
      sections: [{ choices: [['Probability of failure by the time', 'Up to 20 times, separated by commas: for each, the probability F(t) of failing by then, its limits and the survival 1 − F(t).'], ['Time by which a fraction has failed', 'Up to 20 fractions strictly between 0 and 1 (0.1, 0.5 for the median): the time by which that fraction has failed, the quantile, with its limits. Others are dropped.']] },
        { text: 'A changed box redraws the report when it loses the focus (Enter or Tab); empty, it lists nothing. The red triangle\'s Distribution Calculator hides the outline.' }],
    },
    'p:parametric': {
      kicker: 'Analyze', title: 'Fit Parametric Survival',
      lead: 'Regression for times to failure with right censoring: an accelerated failure time model, log(time) (or the time) = x·β + σ·ε, ε from the chosen distribution.',
      sections: [
        { heading: 'The report', text: 'Whole Model Test (likelihood ratio against the intercept only), Parameter Estimates with Wald limits, Effect Likelihood Ratio Tests, and on request the Correlation of Estimates. Distribution switches the family; Save Quantiles and Save Survival Probabilities add columns from the fitted model.' },
        { heading: 'Reading the estimates', text: 'For the log-time families a positive estimate lengthens the times: exp(β) is the factor by which one unit of the effect multiplies them. The Weibull shape is 1/σ.' },
      ],
      more: { label: 'Fit Parametric Survival', id: 'help-p-parametric' },
    },
    'p:fitcurve': {
      kicker: 'Analyze', title: 'Fit Curve',
      lead: 'Fits named nonlinear models of Y against X: polynomials, sigmoid curves (logistic, probit, Gompertz, Weibull growth), exponential growth and decay, peaks, a one-compartment pharmacokinetic model, Michaelis-Menten, power and logarithmic curves, each with automatic starting values.',
      sections: [
        { heading: 'Roles', choices: [['Y, Response', 'The continuous response.'], ['X, Regressor', 'The continuous regressor.'], ['Group', 'A separate curve per level, and tests of parallel or equal curves.'], ['Weight', 'Weights in the sum of squares.'], ['Freq', 'Counts.']] },
        { heading: 'Per model', text: 'Its plot, the prediction model, Summary (AICc, BIC, SSE, MSE, RMSE, R-Square), Parameter Estimates with standard errors and limits, and from its red triangle Confidence Curves, Test Parallelism and Test Equal Parameters (F tests against separate curves), Custom Inverse Prediction, Save Prediction and Save Residuals. Model Comparison ranks the fitted models by AICc.' },
      ],
      more: { label: 'Fit Curve', id: 'help-p-fitcurve' },
    },
    'p:nonlinear': {
      kicker: 'Analyze', title: 'Nonlinear',
      lead: 'Least squares for a model you type: an expression in parameters and columns, with starting values for the parameters.',
      sections: [
        { heading: 'The report', text: 'The model with its starting values and the iterations\' outcome, the fitted curve when the model uses one column, Solution (SSE, DFE, MSE, RMSE), Parameter Estimates with approximate standard errors and limits, Correlation of Estimates. Edit Model changes the model; Use Estimates as Starting Values starts again from the solution.' },
      ],
      more: { label: 'Nonlinear', id: 'help-p-nonlinear' },
    },
    'p:nonlinear-model': {
      kicker: 'Nonlinear', title: 'The model language',
      lead: 'A model is an arithmetic expression. Column names are written :name, or :"name with spaces" (or :Name("…")); a plain name that is a column and not given a starting value is the column too. Every other name is a parameter.',
      sections: [
        { heading: 'What it may contain', list: ['Numbers, parameters, columns, and pi.', '+ − * / and ^ or ** for powers; unary minus; parentheses.', 'Comparisons < <= > >= == != , for where(condition, a, b).', 'The functions exp, log, log10, sqrt, abs, sin, cos, tan, arctan, tanh, minimum(a, b), maximum(a, b), where(c, a, b).'] },
        { heading: 'Safety', text: 'The model is parsed into a small expression tree and evaluated by walking it; anything else (attributes, strings, other functions) is refused, and nothing is run as Python. A model in a saved project or in someone else\'s table cannot run code.' },
      ],
    },
  };

  /* ========================================================================
     REGISTRATION
     ======================================================================== */
  const yName = (spec, t) => { const id = spec.roles && spec.roles.y && spec.roles.y[0]; const c = id && t ? t.col(id) : null; return c ? c.name : ''; };

  SM.platforms.register({
    id: 'lifedist', label: 'Life Distribution', menu: 'Analyze/Reliability and Survival', order: 10, info: 'p:lifedist', topics,
    about: 'Times to failure with right censoring: the nonparametric (Kaplan-Meier) estimate on probability paper, Weibull, lognormal, exponential, Fréchet, loglogistic, normal, SEV, logistic and LEV fits by maximum likelihood with standard errors, their comparison by AICc, and a calculator of failure probabilities and quantiles with limits.',
    uses: ['statsmodels.base.model.GenericLikelihoodModel (censored likelihood)', 'statsmodels.duration.survfunc.SurvfuncRight', 'scipy.special (log_ndtr, ndtri)'],
    launch: {
      lead: 'Choose the time to failure and, if some times are censored, the censor column.',
      roles: [{ key: 'y', label: 'Y, Time to Event', min: 1, max: 1, numeric: true, types: ['continuous'], hint: 'required numeric', help: timeHelp(true) }, censorRole,
        { ...freqRole, help: 'A whole-number count per row, rounded down: the nonparametric estimate takes the row that many times, and the fitted distributions weight its log-likelihood by it. Rows with a count below 1 are left out.' }, byRole],
      options: [censorCodeOpt],
    },
    title: (spec, t) => `Life Distribution${yName(spec, t) ? ` - ${yName(spec, t)}` : ''}`,
    triangle: lifeMenu,
    render: renderLife,
  });

  SM.platforms.register({
    id: 'survival', label: 'Survival', menu: 'Analyze/Reliability and Survival', order: 110, info: 'p:survival',
    about: 'Kaplan-Meier survival curves per group with Greenwood standard errors, restricted means and medians with limits, the log-rank, Wilcoxon, Tarone-Ware and Fleming-Harrington tests between groups, exponential, Weibull and lognormal plots and censored fits, estimates at times and probabilities, and the estimates saved as a table.',
    uses: ['statsmodels.duration.survfunc.SurvfuncRight', 'statsmodels.duration.survfunc.survdiff', 'SurvfuncRight.quantile_ci, simultaneous_cb', 'statsmodels.base.model.GenericLikelihoodModel'],
    launch: {
      lead: 'Choose the time to event, and the censor column if some times are censored (the event had not happened yet). A grouping column gives one curve per level.',
      roles: [{ key: 'y', label: 'Y, Time to Event', min: 1, max: 1, numeric: true, types: ['continuous'], hint: 'required numeric', help: timeHelp(false) },
        { key: 'group', label: 'Grouping', max: 1, hint: 'optional', help: 'One product-limit curve per level, and Tests Between Groups of whether the curves differ (log-rank and the weighted tests). Rows with a missing value are left out; without a Grouping, one curve of all the rows.' },
        censorRole, freqRole, byRole],
      options: [censorCodeOpt, { key: 'failure', label: 'Plot Failure instead of Survival', type: 'check', value: false,
        help: 'The main plot shows the estimated failure probability, 1 − S(t), rising from 0, instead of the survival S(t). The red triangle\'s Plot Options change it later.' }],
    },
    title: () => 'Product-Limit Survival Fit',
    triangle: survivalMenu,
    render: renderSurvival,
  });

  SM.platforms.register({
    id: 'parametric', label: 'Fit Parametric Survival', menu: 'Analyze/Reliability and Survival', order: 140, info: 'p:parametric',
    about: 'Accelerated failure time regression with right censoring: Weibull, lognormal, loglogistic, exponential, Fréchet, normal, logistic, SEV or LEV errors, by maximum likelihood; the whole-model and effect likelihood ratio tests, estimates with limits, and saved quantiles or survival probabilities.',
    uses: ['statsmodels.base.model.GenericLikelihoodModel (censored location-scale regression)', 'patsy (effect coding)'],
    launch: {
      lead: 'Choose the time to event, the censor column and the effects; the distribution is set below or later from the red triangle.',
      roles: [{ key: 'y', label: 'Time to Event', min: 1, max: 1, numeric: true, types: ['continuous'], hint: 'required numeric', help: timeHelp(true) }, censorRole,
        { key: 'x', label: 'Model Effects', hint: 'optional: continuous or nominal columns', help: effectsHelp(false) }, { ...freqRole, help: FREQ_HELP.parametric }, byRole],
      options: [censorCodeOpt, { key: 'dist', label: 'Distribution', type: 'select', value: 'weibull', choices: DISTS,
        help: 'The distribution of the errors ε of the accelerated failure time model log(time) = x·β + σ·ε: Weibull (smallest extreme value errors, the default), Lognormal (normal), Exponential (a Weibull with σ = 1), Fréchet (largest extreme value) or Loglogistic (logistic); Normal, SEV, Logistic and LEV model the time itself. The red triangle\'s Distribution changes it later.' }],
    },
    title: () => 'Parametric Survival Fit',
    triangle: parametricMenu,
    render: renderParametric,
  });

  SM.platforms.register({
    id: 'phreg', label: 'Fit Proportional Hazards', menu: 'Analyze/Reliability and Survival', order: 150, info: 'p:phreg',
    about: 'Cox proportional hazards regression: the likelihood ratio test of the model, log hazard ratios with limits, effect likelihood ratio tests, risk ratios per unit, per range and between levels, the baseline survival, and saved risk scores.',
    uses: ['statsmodels.duration.hazard_regression.PHReg', 'PHReg.loglike (partial likelihood)'],
    launch: {
      lead: 'Choose the time to event, the censor column and the effects.',
      roles: [{ key: 'y', label: 'Time to Event', min: 1, max: 1, numeric: true, types: ['continuous'], hint: 'required numeric', help: timeHelp(false) }, censorRole,
        { key: 'x', label: 'Model Effects', min: 1, hint: 'required: continuous or nominal columns', help: effectsHelp(true) }, { ...freqRole, help: FREQ_HELP.phreg }, byRole],
      options: [censorCodeOpt, { key: 'ties', label: 'Ties', type: 'select', value: 'breslow', choices: [['breslow', 'Breslow'], ['efron', 'Efron']],
        help: 'How tied failure times enter the partial likelihood (statsmodels\' PHReg): Breslow\'s approximation, the default, or Efron\'s, closer to the exact likelihood when many times are tied; without ties the two agree. The red triangle\'s Ties changes it later.' }],
    },
    title: () => 'Proportional Hazards Fit',
    triangle: phMenu,
    render: renderPH,
  });

  SM.platforms.register({
    id: 'fitcurve', label: 'Fit Curve', menu: 'Analyze/Specialized Modeling', order: 10, info: 'p:fitcurve',
    about: 'A library of nonlinear models of Y by X with automatic starting values: polynomials, logistic, probit, Gompertz and Weibull growth curves, exponential and biexponential curves, Gaussian and Lorentzian peaks, a one-compartment oral dose model, Michaelis-Menten, power and logarithmic curves; per group, with model comparison by AICc, tests of parallel and equal curves, inverse prediction and saved predictions.',
    uses: ['scipy.optimize.least_squares', 'scipy.optimize.curve_fit (in the code shown)', 'statsmodels.tools.numdiff.approx_fprime'],
    launch: {
      lead: 'Choose Y and X; a group column gives a curve per level. Pick a model now, or later from the red triangle.',
      roles: [{ key: 'y', label: 'Y, Response', min: 1, max: 1, numeric: true, types: ['continuous'], hint: 'required numeric', help: 'The continuous response the curves are fitted to, by least squares.' },
        { key: 'x', label: 'X, Regressor', min: 1, max: 1, numeric: true, types: ['continuous'], hint: 'required numeric', help: 'The continuous regressor, the x of the curve. Weibull Growth, Power and Logarithmic need every x above 0.' },
        { key: 'group', label: 'Group', max: 1, hint: 'optional', help: 'A separate curve, with parameters of its own, for each level; a model\'s red triangle then tests parallel and equal curves (Test Parallelism, Test Equal Parameters). Rows with a missing value are left out.' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric', help: 'A weight per row in the sum of squares, Σw(y − f(x))², multiplied with Freq: a row of weight 2 counts twice (its variance taken as half). Rows with a missing, zero or negative weight are left out.' },
        { ...freqRole, help: FREQ_HELP.curve }, byRole],
      options: [{ key: 'first', label: 'Fit', type: 'select', value: '', choices: [['', '(choose later)'], ...CURVES.flatMap(([, items]) => items.filter(Boolean))],
        help: 'A model to fit at once, from the library, with its automatic starting values; (choose later) opens the report with the plot alone. The red triangle adds and removes models.' }],
    },
    title: () => 'Fit Curve',
    triangle: curveMenu,
    render: renderCurve,
  });

  SM.platforms.register({
    id: 'nonlinear', label: 'Nonlinear', menu: 'Analyze/Specialized Modeling', order: 30, info: 'p:nonlinear',
    about: 'Least squares for a model typed as an expression in parameters and columns, with starting values: estimates with approximate standard errors and limits, the solution, the correlation of estimates, the fitted curve and saved predictions. The expression is parsed into a whitelisted tree and never run as code.',
    uses: ['scipy.optimize.least_squares', 'ast (the model parser)', 'statsmodels.tools.numdiff.approx_fprime'],
    launch: {
      lead: 'Choose the response and type the model: parameters, columns and numbers, for example a * exp(-b * :dose) + c, with a starting value for each parameter.',
      roles: [{ key: 'y', label: 'Y, Response', min: 1, max: 1, numeric: true, types: ['continuous'], hint: 'required numeric', help: 'The continuous response the model predicts; the model may not use it.' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric', help: 'A weight per row: the fit minimises Σw(y − model)² (the residuals times √w), multiplied with Freq. Rows with a missing, zero or negative weight are left out.' },
        { ...freqRole, help: FREQ_HELP.curve }, byRole],
      extra: nonlinearExtra,
      validate: (spec) => (spec.options && String(spec.options.model || '').trim() ? null : 'Type the model: an expression in parameters and columns, for example a * exp(-b * :dose) + c'),
    },
    title: () => 'Nonlinear Fit',
    triangle: nonlinearMenu,
    render: renderNonlinear,
  });
}(typeof self !== 'undefined' ? self : this));
