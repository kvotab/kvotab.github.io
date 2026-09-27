/* ==========================================================================
   SMUI.HTML: ANALYZE > SCREENING > MULTIPLE IMPUTATION

   The companion of Explore Missing Values: the missing values filled in m
   times, an analysis model fitted to each completed table and the fits
   pooled by Rubin's rules, by statsmodels' MICE (chained equations with
   predictive mean matching) or BayesGaussMI (a multivariate normal)
   (resources/py/smui/mi.py). The report: the Missing Data summary (JMP's
   Missing Columns and Missing Value reports, linked to the rows), the
   Imputation Diagnostics (observed and imputed values overlaid, the trace
   of the imputed means over the cycles), the Pooled Estimates with the
   fraction of missing information and the complete-case fit beside them,
   and Save: one imputed table, all of them stacked, or the average of the
   imputations as new columns. Standard JMP imputes once and pools nothing.

   It brings its own example table, File > Examples > Health survey: 400
   simulated people, values missing at random, known true coefficients.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const { isMissing } = SM.table;

  const MORE = { label: 'Multiple Imputation', id: 'help-p-mi' };
  const METHODS = [['mice', 'MICE (chained equations)'], ['bayes', 'Bayesian Gaussian (multivariate normal)']];
  const METHOD_TEXT = { mice: 'MICE: chained equations, predictive mean matching', bayes: 'Bayesian Gaussian: a multivariate normal, Gibbs sampler' };
  const DEFAULTS = { mice: [10, 3], bayes: [100, 10] };   // statsmodels' burn-in and skip
  const MODELS = [['ols', 'Least Squares'], ['logit', 'Logistic'], ['probit', 'Probit'], ['poisson', 'Poisson']];
  const MODEL_LABEL = Object.fromEntries(MODELS);
  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));
  const esc = (s) => SM.report.plotlyText(s);
  const slot = (key) => (typeof KvotInfo !== 'undefined' ? KvotInfo.slot(key) : null);

  /* Observed and imputed: blue and rose, apart from each other, from the
     selection's orange and from the surfaces in both themes (checked with
     the dataviz skill's validator). */
  function colors() {
    const T = SM.util.themeColors();
    return T.dark ? { obs: '#4d8ad6', imp: '#d1528f', text: T.text, muted: T.muted, surface: T.surface }
      : { obs: '#2e6fba', imp: '#b8406e', text: T.text, muted: T.muted, surface: T.surface };
  }

  /* ---- effects: lists of columns, a crossing when longer than one ------------------- */
  const effectLabel = (cols) => cols.map((c) => c.name).join('*');
  const effectKey = (cols) => cols.map((c) => c.id).sort().join('|');
  const serialize = (cols) => ({ cols: cols.map((c) => c.id), names: cols.map((c) => c.name) });

  function findCol(t, id, name) {
    const byId = t.columns.find((c) => c.id === id) || null;
    if (byId && (!name || byId.name === name)) return byId;
    const byName = name ? t.columns.find((c) => c.name === name) : null;
    return byName || byId;
  }

  function effectsFrom(list, t, byName = false) {
    const out = [];
    for (const e of list || []) {
      const names = e.names || [];
      const cols = (e.cols || names).map((id, i) => (byName ? t.col(names[i] || id) : findCol(t, id, names[i])));
      if (cols.length && cols.every(Boolean)) out.push(cols);
    }
    return out;
  }

  function effectNames(ctx) {
    return effectsFrom(ctx.spec.effects, ctx.table).map((cols) => cols.map((c) => c.name));
  }

  function payloadOf(ctx) {
    const response = ctx.name('response');
    return {
      columns: ctx.names('y'), response, effects: response ? effectNames(ctx) : [], model: response ? ctx.opt('model', null) : null,
      method: ctx.opt('method', 'mice'), m: ctx.opt('m', 20), burnin: ctx.opt('burnin', null), skip: ctx.opt('skip', null), seed: ctx.opt('seed', 1), alpha: ctx.alpha,
    };
  }

  const missingRows = (ctx, cols, fn) => ctx.rows.filter((r) => fn(cols.map((c) => isMissing(c.values[r]))));

  /* ---- the summary ----------------------------------------------------------------------- */
  function summary(ctx, res) {
    const secs = res.cached ? '' : `, ${fmt(res.seconds, { sig: 2 })} s`;
    const pairs = [
      ['Method', METHOD_TEXT[res.method], 'text'],
      ['Columns', res.columns.join(', '), 'text'],
      ['Imputations', `${res.m}: after ${res.burnin} cycles of burn-in, one every ${res.skip + 1} cycles${secs}`, 'text'],
      ['Seed', res.seed, 'int'],
      ['Rows', res.dropped.length ? `${res.n} (${res.dropped.length} with no value in any column left out)` : String(res.n), 'text'],
    ];
    ctx.container.append(el('div', { class: 'sm-mi-summary' }, ctx.kv(pairs)));
    for (const n of res.notes || []) ctx.container.append(ctx.note(n));
  }

  /* ---- Missing Data: JMP's Missing Columns and Missing Value reports -------------------------- */
  function missingOutline(ctx, res) {
    const t = ctx.table;
    const cols = res.columns.map((n) => t.col(n)).filter(Boolean);
    const mr = res.missing;
    const any = (m) => m.some(Boolean);
    const ob = ctx.outline('Missing Data', { key: 'missing', info: 'p:mi:missing', menu: () => [
      { label: 'Select Rows with Missing', action: () => t.select(missingRows(ctx, cols, any)) },
      { label: 'Select Complete Rows', action: () => t.select(missingRows(ctx, cols, (m) => !any(m))) },
    ] });
    ob.add(ctx.kv([['Rows', mr.n, 'int'], ['Rows with a missing value', mr.rows_with_missing, 'int'], ['Complete rows', mr.complete, 'int'], ['Missing cells', mr.cells_missing, 'int']]));
    const cOb = ctx.outline('Missing Columns Report', { parent: ob, key: 'missing:cols' });
    cOb.add(ctx.rt({ columns: [{ key: 'column', label: 'Column', fmt: 'text' }, { key: 'n_missing', label: 'Number Missing', fmt: 'int' }, { key: 'pct', label: 'Percent Missing', digits: 2 }], rows: mr.columns },
      { key: 'micols', onRow: (r) => { const c = t.col(r.column); if (c) t.select(ctx.rows.filter((i) => isMissing(c.values[i]))); } }),
    ctx.note('Click a line to select the rows where that column is missing.'));
    const pOb = ctx.outline('Missing Value Report', { parent: ob, key: 'missing:patterns' });
    pOb.add(ctx.rt({ columns: [{ key: 'count', label: 'Count', fmt: 'int' }, { key: 'n_missing', label: 'Number of Columns Missing', fmt: 'int' }, { key: 'pattern', label: 'Pattern', fmt: 'text' }, { key: 'names', label: 'Columns Missing', fmt: 'text' }],
      rows: mr.patterns.map((p) => ({ ...p, names: p.columns.join(', ') || '(none)' })) },
    { key: 'mipatterns', onRow: (r) => t.select(missingRows(ctx, cols, (m) => m.map((x) => (x ? '1' : '0')).join('') === r.pattern)) }),
    ctx.note(`A pattern has a 1 for each missing column, in the order ${cols.map((c) => c.name).join(', ')}. Click a line to select its rows.`));
    ob.add(ctx.row(cOb.el, pOb.el));
  }

  /* ---- Pooled Estimates ------------------------------------------------------------------------ */
  function comparePlot(ctx, res) {
    const C = colors();
    const A = res.analysis;
    const pooled = A.pooled.rows;
    const cc = new Map(A.cc.rows.map((r) => [r.name, r]));
    const terms = pooled.slice(0, 12);
    const k = terms.length;
    const h = 64 + 56 * k;
    const gap = 26 / h;
    const lv = fmt(100 * (1 - ctx.alpha));
    const layout = { showlegend: true, legend: { orientation: 'h', x: 0, y: 1, yanchor: 'bottom' }, margin: { l: 150, r: 14, t: 34, b: 10 }, annotations: [] };
    const traces = [];
    const bottom = 10 / h;
    const band = (1 - bottom - 0.02) / k;
    terms.forEach((r, i) => {
      const ax = i ? String(i + 1) : '';
      const top = 1 - i * band, lo = top - band + gap;
      layout[`yaxis${ax}`] = { domain: [Math.max(0, lo), top - 0.004], range: [-0.7, 1.7], showticklabels: false, showgrid: false, zeroline: false, fixedrange: true, ticks: '' };
      layout[`xaxis${ax}`] = { anchor: `y${ax}`, zeroline: false, automargin: true, tickfont: { size: 10 } };
      layout.annotations.push({ xref: 'paper', yref: `y${ax}`, x: -0.02, y: 0.5, xanchor: 'right', showarrow: false, text: esc(r.term), font: { size: 11, color: C.text } });
      const c = cc.get(r.name);
      const pt = (e, y, name, color, symbol, show) => ({
        type: 'scatter', mode: 'markers', x: [e.estimate], y: [y], xaxis: `x${ax}`, yaxis: `y${ax}`, name, legendgroup: name, showlegend: show,
        marker: { symbol, size: 9, color, line: { color: C.surface, width: 2 } },
        error_x: { type: 'data', symmetric: false, array: [e.upper - e.estimate], arrayminus: [e.estimate - e.lower], color, thickness: 2, width: 4 },
        hovertemplate: `${esc(r.term)}, ${name}: %{x:.5g}<br>${lv}% interval ${fmt(e.lower, { sig: 5 })} to ${fmt(e.upper, { sig: 5 })}<extra></extra>`,
      });
      traces.push(pt(r, 1, `Pooled (${res.m} imputations)`, C.obs, 'circle', i === 0));
      if (c) traces.push(pt(c, 0, 'Complete cases', C.imp, 'square', i === 0));
    });
    return ctx.plot(traces, layout, { width: W(520), height: h, title: 'pooled and complete-case estimates', select: false });
  }

  function pooledOutline(ctx, res) {
    const A = res.analysis;
    const showCC = ctx.opt('cc', true) && A.cc;
    const ob = ctx.outline('Pooled Estimates', { key: 'pooled', info: 'p:mi:pooled', menu: () => [ctx.check('Complete-Case Fit', 'cc', null, true), ctx.check('Comparison Plot', 'compare', null, true)] });
    const effects = effectNames(ctx).map((e) => e.join('*'));
    ob.add(el('div', { class: 'sm-mi-summary' }, ctx.kv([['Model', `${A.label}: ${A.response_label} on ${effects.length ? effects.join(', ') : 'the intercept alone (the pooled mean)'}`, 'text'],
      ['Imputations', String(res.m), 'text'], ['Rows', String(res.n), 'text'], ['Complete cases', String(A.n_cc), 'text']])));
    const pooled = ctx.rt(A.pooled, { caption: `Pooled over ${res.m} imputations (Rubin's rules)`, sortable: false, key: 'pooled', name: 'Pooled Estimates' });
    const cc = showCC ? ctx.rt(A.cc, { caption: `Complete cases only (${A.n_cc} rows)`, sortable: false, key: 'cc', name: 'Complete-Case Fit' }) : null;
    ob.add(ctx.row(el('div', { class: 'sm-mi-table' }, pooled), cc ? el('div', { class: 'sm-mi-table' }, cc) : null));
    if (showCC && ctx.opt('compare', true)) ob.add(el('div', { class: 'sm-mi-scroll' }, comparePlot(ctx, res)));
    const notes = [
      `Rubin's rules: the estimate is the mean of the ${res.m} imputations' estimates; its variance is W + (1 + 1/m) B, W the mean of their variances (within) and B the variance of their estimates (between). FMI, the fraction of missing information, is statsmodels' (1 + 1/m) B / T (R's mice calls it lambda). z tests and normal intervals, as statsmodels pools; the right-click Columns menu adds W, B and T, the relative increase in variance, the Barnard–Rubin degrees of freedom with their t test and R mice's FMI.`,
      A.cc ? `The complete-case fit uses only the ${A.n_cc} rows with every model column observed. It is unbiased when missingness depends on the covariates alone; when it depends on the response (or on anything else that the imputation uses), the complete cases are a skewed sample and the two fits part.` : null,
    ].filter(Boolean);
    ob.add(...notes.map((s) => ctx.note(s)), ctx.code(res.code));
  }

  /* ---- Imputation Diagnostics ------------------------------------------------------------------------- */
  function densityPlot(ctx, res, imp, c) {
    const C = colors();
    const obs = [], obsRows = [];
    const missing = new Set(imp.rows);
    for (const r of res.rows) { if (missing.has(r)) continue; const v = c.values[r]; if (typeof v === 'number' && Number.isFinite(v)) { obs.push(v); obsRows.push(r); } }
    const drawn = [], drawnRows = [];
    for (const d of imp.draws) d.forEach((v, k) => { drawn.push(v); drawnRows.push(imp.rows[k]); });
    const b = SM.report.niceBins(obs.concat(drawn));
    const nb = Math.max(1, Math.round((b.end - b.start) / b.size));
    const bars = (vals, rows) => {
      const counts = new Array(nb).fill(0), members = Array.from({ length: nb }, () => []);
      vals.forEach((v, k) => { const j = Math.min(nb - 1, Math.max(0, Math.floor((v - b.start) / b.size + 1e-9))); counts[j]++; members[j].push(rows[k]); });
      return { counts, members };
    };
    const O = bars(obs, obsRows), I = bars(drawn, drawnRows);
    const x = Array.from({ length: nb }, (_, j) => b.start + (j + 0.5) * b.size);
    const so = 1 / (Math.max(1, obs.length) * b.size), si = 1 / (Math.max(1, drawn.length) * b.size);
    const range = (j) => `${fmt(b.start + j * b.size, { sig: 4 })} to ${fmt(b.start + (j + 1) * b.size, { sig: 4 })}`;
    const trace = (B, s, name, color, n) => ({
      type: 'bar', x, y: B.counts.map((v) => v * s), width: b.size, rows: B.members, rowsScale: s, name: `${name} (${n})`,
      marker: { color, opacity: 0.55, line: { color: C.surface, width: 1 } },
      hovertext: B.counts.map((v, j) => `${name}: ${v} value${v === 1 ? '' : 's'}, ${range(j)}`), hovertemplate: '%{hovertext}<extra></extra>',
    });
    return ctx.plot([trace(O, so, 'Observed', C.obs, obs.length), trace(I, si, 'Imputed', C.imp, drawn.length)], {
      barmode: 'overlay', bargap: 0, showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' },
      xaxis: { title: { text: esc(c.name) }, range: [b.start, b.end] }, yaxis: { title: { text: 'Density' }, rangemode: 'tozero' }, margin: { l: 56, r: 10, t: 30, b: 42 },
    }, { width: W(400), height: 270, title: `${c.name} observed and imputed` });
  }

  function levelPlot(ctx, res, imp, c) {
    const C = colors();
    const lv = res.levels[imp.column] || [];
    const labels = lv.map((v) => SM.grid.cellText(c, v));
    const missing = new Set(imp.rows);
    const obsM = lv.map(() => []), impM = lv.map(() => []);
    for (const r of res.rows) { if (missing.has(r)) continue; const k = lv.findIndex((v) => String(v) === String(c.values[r])); if (k >= 0) obsM[k].push(r); }
    for (const d of imp.draws) d.forEach((v, k) => { const j = Math.round(v); if (impM[j]) impM[j].push(imp.rows[k]); });
    const no = obsM.reduce((a, m) => a + m.length, 0), ni = impM.reduce((a, m) => a + m.length, 0);
    const trace = (M, n, name, color, offset) => ({
      type: 'bar', x: labels, y: M.map((m) => m.length / Math.max(1, n)), rows: M, rowsScale: 1 / Math.max(1, n), offset, width: 0.38, name: `${name} (${n})`,
      marker: { color, line: { color: C.surface, width: 1 } }, hovertemplate: `${name} %{x}: %{y:.3f}<extra></extra>`,
    });
    return ctx.plot([trace(obsM, no, 'Observed', C.obs, -0.4), trace(impM, ni, 'Imputed', C.imp, 0.02)], {
      showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, xaxis: { type: 'category', title: { text: esc(c.name) } },
      yaxis: { title: { text: 'Proportion' }, rangemode: 'tozero' }, margin: { l: 56, r: 10, t: 30, b: 42 },
    }, { width: W(340), height: 270, title: `${c.name} observed and imputed levels` });
  }

  function tracePlot(ctx, res, imp, c) {
    const C = colors();
    const means = res.trace.means[imp.column] || [];
    const x = means.map((_, i) => i + 1);
    const takes = [];
    for (let k = 1; k <= res.m; k++) takes.push(res.trace.burnin + k * res.trace.step);
    const cat = res.kinds[imp.column] === 'categorical';
    const om = res.observed_mean[imp.column];
    const traces = [
      { type: 'scatter', mode: 'lines', x, y: means, name: 'Mean of the imputed values', line: { color: C.obs, width: 2 }, hovertemplate: 'cycle %{x}: %{y:.5g}<extra></extra>' },
      { type: 'scatter', mode: 'markers', x: takes, y: takes.map((t) => means[t - 1]), name: 'An imputation', marker: { color: C.imp, size: 8, line: { color: C.surface, width: 2 } }, hovertemplate: 'imputation at cycle %{x}: %{y:.5g}<extra></extra>' },
    ];
    const shapes = [{ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: om, y1: om, line: { color: C.muted, width: 1.2, dash: 'dot' } }];
    if (res.trace.burnin > 0) shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: 0.5, x1: res.trace.burnin + 0.5, y0: 0, y1: 1, fillcolor: C.muted, opacity: 0.1, line: { width: 0 }, layer: 'below' });
    return ctx.plot(traces, {
      showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, shapes,
      annotations: [{ xref: 'paper', yref: 'y', x: 1, y: om, xanchor: 'right', yanchor: 'bottom', showarrow: false, text: `observed mean ${fmt(om, { sig: 4 })}`, font: { size: 10, color: C.muted } },
        ...(res.trace.burnin > 0 ? [{ xref: 'x', yref: 'paper', x: 1, y: 1, xanchor: 'left', yanchor: 'top', showarrow: false, text: 'burn-in', font: { size: 10, color: C.muted } }] : [])],
      xaxis: { title: { text: 'Cycle' }, range: [0.5, Math.max(2, means.length) + 0.5] }, yaxis: { title: { text: `Mean of imputed ${esc(c.name)}${cat ? ' (codes)' : ''}` } }, margin: { l: 60, r: 10, t: 30, b: 42 },
    }, { width: W(430), height: 270, title: `${c.name} trace`, select: false });
  }

  function diagnosticsOutline(ctx, res) {
    const ob = ctx.outline('Imputation Diagnostics', { key: 'diag', info: 'p:mi:diagnostics' });
    if (!res.imputed.length) { ob.add(ctx.note('No missing values in these columns: nothing was imputed.')); return; }
    for (const imp of res.imputed) {
      const c = ctx.table.col(imp.column);
      if (!c) continue;
      const sc = c.id;
      const sub = ctx.outline(`${imp.column}: ${imp.rows.length} missing, ${res.m} imputations`, { parent: ob, key: `diag:${sc}`, menu: () => [
        ctx.check('Observed and Imputed', 'miDist', sc, true), ctx.check('Trace', 'miTrace', sc, true),
        { label: 'Select Rows Imputed', action: () => ctx.table.select(imp.rows) },
      ] });
      const plots = [];
      if (ctx.opt('miDist', true, sc)) plots.push(res.kinds[imp.column] === 'categorical' ? levelPlot(ctx, res, imp, c) : densityPlot(ctx, res, imp, c));
      if (ctx.opt('miTrace', true, sc)) plots.push(tracePlot(ctx, res, imp, c));
      if (plots.length) sub.add(ctx.row(...plots));
    }
    ob.add(ctx.note(`Left, the observed values of each column and its imputed ones (all ${res.m} imputations together), as densities (proportions of the levels for a categorical column); click a bar to select its rows. Imputed values that sit where the observed are rare can be right (the data are missing at random, not completely at random) or a sign of a poor imputation model. Right, the mean of the imputed values after every cycle of the imputer: after the shaded burn-in it should wander around a level with no trend; the dots are the cycles whose values became the imputations.`));
  }

  /* ---- Method and Assumptions ------------------------------------------------------------------------------ */
  function aboutOutline(ctx) {
    const ob = ctx.outline('Method and Assumptions', { key: 'about', info: 'p:mi:about', menu: () => [{ label: 'Remove', action: () => ctx.set('about', false) }] });
    const para = (head, text) => el('p', null, el('strong', { text: `${head}. ` }), text);
    ob.add(el('div', { class: 'sm-mi-about' },
      para('Missing at random', 'Multiple imputation is right when the values are missing at random: whether a value is missing may depend on what is observed (here, on the other columns), but not, beyond that, on the missing value itself. Put into the imputation every column that predicts the missing values or their missingness, and the analysis model\'s response and effects, or the pooled fit is biased toward no relation. Nothing in the data can show that values are missing at random rather than not.'),
      para('MICE in statsmodels', 'MICEData fills each column with the observed value nearest its mean, then cycles: each column with missing values in turn is regressed by least squares on all the others, the regression\'s coefficients are drawn from their approximate normal sampling distribution, and each missing value becomes the observed value of one of the 20 rows whose predicted values are nearest its own (predictive mean matching, so imputed values are always values that occur). It runs one chain: the burn-in cycles, then an imputation every n_skip + 1 cycles. MICE.fit fits the analysis model to each imputation and pools the fits.'),
      para('The multivariate normal', 'BayesGaussMI is a Gibbs sampler: the missing values given the mean and covariance, then the mean, then the covariance, in turn; after the burn-in an imputation every skip + 1 cycles. Its priors in statsmodels 0.14.6 are fixed (the mean N(0, I), the covariance inverse Wishart with scale I and one degree of freedom), right only for data on a unit scale: the page standardizes every column, imputes, and turns the values back, so the imputations do not depend on the units. It imputes numbers, not levels, and assumes the columns are jointly normal.'),
      para('Pooling', 'Rubin\'s rules, as statsmodels pools: the mean of the m estimates, and the total variance W + (1 + 1/m) B from the within-imputation variance W and the between-imputation variance B. statsmodels tests with the normal distribution and reports (1 + 1/m) B / T as the fraction of missing information; the optional columns add the Barnard–Rubin degrees of freedom (the complete-data degrees of freedom n − p) with a t test, and the fraction of missing information that uses them, as R\'s mice pool() reports them. More imputations make B, and so the pooled standard errors, steadier.'),
      para('Against R\'s mice', 'R\'s mice runs m parallel chains (m = 5, maxit = 5 iterations each, by default) where statsmodels runs one chain with a burn-in; its predictive mean matching draws among 5 donors (statsmodels 20), matches the donors\' predictions with the estimated coefficients and the recipients\' with drawn ones (statsmodels draws both), and draws the residual variance as well as the coefficients (Bayesian linear regression; statsmodels draws only the coefficients, from their normal approximation). mice imputes a binary or categorical column by logistic, multinomial or ordered models (statsmodels has predictive mean matching only, so here a nominal column with more than two levels and missing values is refused), and pool() tests with t on the Barnard–Rubin degrees of freedom.'),
      para('JMP', 'Explore Missing Values (Analyze > Screening), here as in JMP, imputes once, which understates the uncertainty: an analysis of one imputed table treats invented values as data. Standard JMP has no multiple imputation pooled by Rubin\'s rules; this platform adds it.'),
    ));
  }

  /* ---- Save: the imputed tables, the average of the imputations ------------------------------------------- */
  function levelValue(res, name, code) {
    const lv = res.levels[name];
    return lv ? lv[Math.round(code)] : code;
  }

  function fillImputed(res, nt, rowsInNew, which) {
    for (const imp of res.imputed) {
      const c = nt.col(imp.column);
      if (!c) continue;
      imp.rows.forEach((r, k) => { const at = rowsInNew.get(r); if (at != null) c.values[at] = levelValue(res, imp.column, imp.draws[which][k]); });
    }
  }

  function saveOne(ctx, which) {
    const res = ctx.mi.res;
    const t = ctx.table;
    const nt = t.subset(res.rows, null, `${t.name} imputed ${which + 1} of ${res.m}`);
    fillImputed(res, nt, new Map(res.rows.map((r, k) => [r, k])), which);
    nt.source = `Multiple Imputation of ${t.name}: imputation ${which + 1} of ${res.m} (${res.method === 'mice' ? 'MICE' : 'Bayesian Gaussian'}, seed ${res.seed})`;
    nt.notes = `${nt.source}. The rows of the report${ctx.byLabel ? ` (${ctx.byLabel})` : ''} with a value in any of ${res.columns.join(', ')}; the missing values of those columns imputed.`;
    SM.app.addTable(nt);
  }

  function saveStacked(ctx) {
    const res = ctx.mi.res;
    const t = ctx.table;
    const n = res.rows.length;
    const imps = [], ids = [];
    for (let j = 0; j < res.m; j++) for (const r of res.rows) { imps.push(j + 1); ids.push(r + 1); }
    const columns = [{ name: '.imp', dataType: 'numeric', modelingType: 'ordinal', values: imps, notes: 'the imputation, 1 to m' },
      { name: '.id', dataType: 'numeric', modelingType: 'nominal', values: ids, notes: `the row of ${t.name}` }];
    for (const c of t.columns) {
      const vals = [];
      for (let j = 0; j < res.m; j++) for (const r of res.rows) vals.push(c.values[r]);
      columns.push({ name: c.name, dataType: c.dataType, modelingType: c.modelingType, valueOrder: c.valueOrder, format: c.format, notes: c.notes, role: c.role, values: vals });
    }
    const nt = new SM.Table({ name: `${t.name} imputed (${res.m} stacked)`, source: `Multiple Imputation of ${t.name}: all ${res.m} imputations stacked`, columns });
    for (let j = 0; j < res.m; j++) {
      const at = new Map(res.rows.map((r, k) => [r, j * n + k]));
      fillImputed(res, nt, at, j);
    }
    nt.notes = `${nt.source}, ${res.method === 'mice' ? 'MICE' : 'Bayesian Gaussian'}, seed ${res.seed}. .imp is the imputation and .id the row of ${t.name}, as R's mice::complete(action = "long") lays them out.`;
    SM.app.addTable(nt);
  }

  function saveAverage(ctx) {
    const res = ctx.mi.res;
    const t = ctx.table;
    for (const imp of res.imputed) {
      const c = t.col(imp.column);
      if (!c) continue;
      const pos = new Map(imp.rows.map((r, k) => [r, k]));
      const cat = res.kinds[imp.column] === 'categorical';
      const values = res.rows.map((r) => {
        const k = pos.get(r);
        if (k == null) return c.values[r];
        const draws = imp.draws.map((d) => d[k]);
        if (!cat) return draws.reduce((a, b) => a + b, 0) / draws.length;
        const counts = new Map();
        for (const v of draws) counts.set(Math.round(v), (counts.get(Math.round(v)) || 0) + 1);
        const best = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0][0];
        return levelValue(res, imp.column, best);
      });
      ctx.saveColumn(`${cat ? 'Mode' : 'Mean'} Imputed[${c.name}]`, { rows: res.rows, values }, {
        dataType: c.dataType, modelingType: c.modelingType, valueOrder: c.valueOrder,
        notes: `${c.name} with each missing value replaced by the ${cat ? 'most frequent level' : 'mean'} of its ${res.m} imputations (${res.method === 'mice' ? 'MICE' : 'Bayesian Gaussian'}, seed ${res.seed})`,
      });
    }
  }

  async function chooseImputation(ctx) {
    const res = ctx.mi.res;
    const v = await SM.ui.form({ title: 'Save Imputed Table', info: 'p:mi:save', lead: `A new table with the missing values of ${res.imputed.map((x) => x.column).join(', ') || 'no column'} filled in from one of the ${res.m} imputations.`,
      fields: [{ key: 'j', label: `Imputation (1 to ${res.m})`, type: 'number', value: 1, helpLabel: 'Imputation',
        help: 'Which of the imputations fills in the new table, a whole number from 1 to m. Each is one plausible completion; an analysis of a single imputed table understates the uncertainty, which the pooled fit (or all the imputations stacked) takes into account.' }],
      validate: (x) => (Number.isInteger(x.j) && x.j >= 1 && x.j <= res.m ? null : `Give a whole number from 1 to ${res.m}.`) });
    if (v) saveOne(ctx, v.j - 1);
  }

  /* ---- the launch dialog's own part: the analysis model and the imputer ------------------------------------------- */
  function launchExtra(api, spec) {
    const t = api.table;
    let effects = spec ? effectsFrom(spec.effects, t) : [];
    const sel = new Set();
    const o0 = (spec && spec.options) || {};
    const st = { model: o0.model || null };
    const msg = (s) => api.message(s);
    const list = el('ul', { class: 'sm-role-list sm-mi-effects', role: 'listbox', 'aria-label': 'Analysis model effects', 'aria-multiselectable': 'true', tabindex: '0',
      dataset: { hint: 'Select columns on the left, then Add or Cross' } });
    const renderList = () => {
      list.replaceChildren();
      list.classList.toggle('is-empty', !effects.length);
      effects.forEach((e, i) => {
        const li = el('li', { role: 'option', dataset: { i: String(i) }, 'aria-selected': String(sel.has(i)) }, el('span', { class: 'sm-colname', text: effectLabel(e) }));
        if (sel.has(i)) li.classList.add('is-selected');
        list.append(li);
      });
    };
    const mark = { anchor: null };
    list.addEventListener('click', (ev) => {
      const li = ev.target.closest('li');
      if (!li) return;
      // a click, ctrl/⌘ for one more, shift for a sweep (the list's order)
      SM.util.listClick(ev, +li.dataset.i, effects.map((_, k) => k), sel, mark);
      renderList();
    });
    list.addEventListener('dblclick', (ev) => { const li = ev.target.closest('li'); if (!li) return; effects.splice(+li.dataset.i, 1); sel.clear(); renderList(); });
    const add = (more) => {
      let n = 0;
      for (const e of more) if (!effects.some((x) => effectKey(x) === effectKey(e))) { effects.push(e); n++; }
      if (!n && more.length) msg('Those effects are in the model already.');
      sel.clear();
      renderList();
    };
    const btn = (label, fn) => { const b = el('button', { type: 'button', class: 'sm-btn', text: label }); b.addEventListener('click', () => { msg(''); fn(); }); return b; };
    const bAdd = btn('Add', () => { const c = api.selectedColumns(); if (!c.length) { msg('Select columns in the list on the left first.'); return; } add(c.map((x) => [x])); });
    const bCross = btn('Cross', () => {
      const c = api.selectedColumns();
      const es = effects.filter((_, i) => sel.has(i));
      if (es.length && c.length) add(es.flatMap((e) => c.map((x) => [...e, x])));
      else if (c.length > 1) add([c]);
      else if (es.length > 1) add([es.flat()]);
      else msg('Cross: select two or more columns, or columns and effects of the model.');
    });
    const bRemove = btn('Remove', () => { if (!sel.size) { msg('Select effects in the model list to remove.'); return; } effects = effects.filter((_, i) => !sel.has(i)); sel.clear(); renderList(); });
    const mkSel = (choices, value, label) => { const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: v, text: l }))); if (value != null) s.value = value; return s; };
    const numIn = (label, value, size = 5) => { const i = el('input', { type: 'text', inputmode: 'numeric', size, 'aria-label': label }); i.value = value == null ? '' : String(value); return i; };
    const lab = (text, input) => el('label', { class: 'sm-mi-opt' }, el('span', { text }), input);
    const modelSel = mkSel(MODELS, st.model, 'Analysis model');
    modelSel.addEventListener('change', () => { st.model = modelSel.value; });
    const methodSel = mkSel(METHODS, o0.method || 'mice', 'Imputation method');
    const mIn = numIn('Imputations', o0.m ?? 20), burnIn = numIn('Burn-in cycles', o0.burnin), skipIn = numIn('Cycles skipped between imputations', o0.skip), seedIn = numIn('Seed', o0.seed ?? 1);
    const syncMethod = () => { const [b, s] = DEFAULTS[methodSel.value]; burnIn.placeholder = String(b); skipIn.placeholder = String(s); };
    methodSel.addEventListener('change', syncMethod);
    const syncModel = () => {
      const id = (api.state.response || [])[0];
      const c = id ? t.col(id) : null;
      if (!st.model) modelSel.value = c && c.isCategorical ? 'logit' : 'ols';
    };
    api.onRolesChange(syncModel);
    syncMethod();
    syncModel();
    renderList();
    const box = el('div', { class: 'sm-mi-launch' },
      el('h4', null, 'Analysis Model', slot('p:mi:model')),
      el('div', { class: 'sm-mi-effbox' }, el('div', { class: 'sm-mi-tools' }, bAdd, bCross, bRemove, lab('Model', modelSel)), list),
      el('p', { class: 'sm-mi-hint', text: 'The Model Response and these effects are fitted to every imputation and pooled; leave the response empty to impute only. Their columns join the imputation.' }),
      el('h4', null, 'Imputation', slot('p:mi:method')),
      el('div', { class: 'sm-mi-row' }, lab('Method', methodSel), lab('Imputations m', mIn), lab('Burn-in', burnIn), lab('Skip', skipIn), lab('Seed', seedIn)));
    const intOf = (i) => { const s = String(i.value).trim(); return s === '' ? null : Number(s); };
    return {
      el: box,
      help: [
        ['Add', 'Adds the columns selected in the list on the left to the analysis model, each as a main effect.'],
        ['Cross', 'Adds an interaction: the crossing of two or more columns selected on the left; with effects selected in the model list as well, each of them crossed with each selected column; with only effects selected, their crossing.'],
        ['Remove', 'Takes the effects selected in the model list out (a double click removes one too).'],
        ['Effects', 'The analysis model\'s effects: click to select one, ctrl/⌘ for one more, shift for a range. Their columns join the imputation. With none the model is the response\'s mean, pooled.'],
        ['Model', 'The analysis model: Least Squares (the default for a continuous response), Logistic or Probit for a two-level one (Logistic by default for a categorical response), Poisson for counts.'],
        ['Method', 'MICE (chained equations, the default): each column in turn regressed on the others and its missing values drawn by predictive mean matching, so every imputed value is one that occurs; for continuous, two-level and ordinal columns. Bayesian Gaussian: a Gibbs sampler of a multivariate normal; numbers only, no categorical column with missing values.'],
        ['Imputations m', 'How many completed tables are made, analysed and pooled: 2 to 200, 20 by default. More make the between-imputation variance, and so the pooled standard errors, steadier; the time grows with m.'],
        ['Burn-in', 'The imputer\'s cycles before the first imputation is taken, so that it forgets its start. Empty: statsmodels\' default, 10 for MICE and 100 for the normal. Raise it when the trace still drifts after the shaded burn-in.'],
        ['Skip', 'The cycles run and not used between two imputations, so that they are less alike. Empty: statsmodels\' default, 3 for MICE and 10 for the normal. All the cycles together, burn-in + m × (skip + 1), may be at most 20 000.'],
        ['Seed', 'The seed of the imputer\'s draws, a whole number from 0: the same seed gives the same imputations, here and in the Python shown.'],
      ],
      read() {
        const m = intOf(mIn), seed = intOf(seedIn);
        return { effects: effects.map(serialize), options: { model: modelSel.value, method: methodSel.value, m: m == null ? 20 : m, burnin: intOf(burnIn), skip: intOf(skipIn), seed: seed == null ? 1 : seed } };
      },
      recall(saved) {
        const x = (saved && saved.extra) || {};
        effects = effectsFrom(x.effects, t, true);
        const o = (saved && saved.options) || {};
        st.model = o.model || null;
        if (st.model) modelSel.value = st.model;
        methodSel.value = o.method || 'mice';
        mIn.value = String(o.m ?? 20); burnIn.value = o.burnin == null ? '' : String(o.burnin); skipIn.value = o.skip == null ? '' : String(o.skip); seedIn.value = String(o.seed ?? 1);
        sel.clear();
        syncMethod();
        syncModel();
        renderList();
      },
    };
  }

  function validate(spec, table) {
    const cols = (k) => ((spec.roles || {})[k] || []).map((id) => table.col(id)).filter(Boolean);
    const ys = cols('y'), [resp] = cols('response');
    const effects = effectsFrom(spec.effects, table);
    const o = spec.options || {};
    if (effects.length && !resp) return 'The analysis model needs a Model Response: cast one, or remove the effects to impute only.';
    if (resp && effects.some((e) => e.includes(resp))) return `${resp.name} is the Model Response: take it out of the effects.`;
    const used = [...new Set([...ys, ...(resp ? [resp] : []), ...effects.flat()])];
    if (used.length < 2) return 'Multiple imputation needs two columns or more: each column is imputed from the others.';
    for (const c of used) if (!c.isCategorical && !c.isNumeric) return `${c.name} is a character column: make it nominal or ordinal (right click it).`;
    for (const c of used) if (c.isCategorical && table.levels(c).length > 30) return `${c.name} has ${table.levels(c).length} levels: too many to impute or to impute from (at most 30); take it out, or make it continuous.`;
    if (resp && resp.isCategorical) {
      if (table.levels(resp).length !== 2) return `${resp.name} (the Model Response) has ${table.levels(resp).length} levels: a categorical response takes two (a logistic or probit model).`;
      if (o.model === 'ols' || o.model === 'poisson') return `${resp.name} is categorical: choose a logistic or probit model.`;
    }
    const hasMissing = (c) => c.values.some((v) => isMissing(v));
    for (const c of used) {
      if (!c.isCategorical || !hasMissing(c)) continue;
      if (o.method === 'bayes') return `${c.name} is categorical and has missing values: the multivariate normal imputes numbers, not levels. Use MICE.`;
      if (c.modelingType === 'nominal' && table.levels(c).length > 2) return `${c.name} is nominal with ${table.levels(c).length} levels and missing values: statsmodels' MICE imputes numeric, two-level and ordinal columns only.`;
    }
    if (!(Number.isInteger(o.m) && o.m >= 2 && o.m <= 200)) return 'Imputations m: a whole number from 2 to 200.';
    for (const [k, label] of [['burnin', 'Burn-in'], ['skip', 'Skip']]) if (o[k] != null && !(Number.isInteger(o[k]) && o[k] >= 0)) return `${label}: a whole number, zero or more (empty: statsmodels' default).`;
    if (!(Number.isInteger(o.seed) && o.seed >= 0)) return 'Seed: a whole number, zero or more.';
    return null;
  }

  /* ---- the red triangle ------------------------------------------------------------------------------------ */
  async function imputationsDialog(ctx) {
    const method = ctx.opt('method', 'mice');
    const [b0, s0] = DEFAULTS[method];
    const name = method === 'mice' ? 'MICE' : 'the normal';
    const v = await SM.ui.form({ title: 'Imputations', info: 'p:mi:method', fields: [
      { key: 'm', label: 'Imputations m', type: 'number', value: ctx.opt('m', 20), help: 'How many completed tables are made and pooled, 2 to 200 (20 by default): more make the pooled standard errors steadier, and take longer.' },
      { key: 'burnin', label: `Burn-in cycles (empty: ${b0})`, type: 'number', value: ctx.opt('burnin', null), helpLabel: 'Burn-in cycles',
        help: `The cycles before the first imputation, so that the imputer forgets its start; empty: statsmodels' ${b0} for ${name}. Raise it when a trace still drifts after the shaded burn-in.` },
      { key: 'skip', label: `Cycles skipped between imputations (empty: ${s0})`, type: 'number', value: ctx.opt('skip', null), helpLabel: 'Cycles skipped',
        help: `The cycles run and not used between two imputations, so that they are less alike; empty: statsmodels' ${s0} for ${name}. Burn-in + m × (skip + 1) may be at most 20 000 cycles.` },
      { key: 'seed', label: 'Seed', type: 'number', value: ctx.opt('seed', 1), help: 'A whole number from 0: the same seed gives the same imputations, here and in the Python shown.' }],
    validate: (x) => (!(Number.isInteger(x.m) && x.m >= 2 && x.m <= 200) ? 'Imputations: a whole number from 2 to 200.'
      : [x.burnin, x.skip].some((y) => y != null && !(Number.isInteger(y) && y >= 0)) ? 'Burn-in and skip: whole numbers, zero or more.'
        : !(Number.isInteger(x.seed) && x.seed >= 0) ? 'Seed: a whole number, zero or more.' : null) });
    if (!v) return;
    ctx.set('m', v.m, null, { rerun: false });
    ctx.set('burnin', v.burnin, null, { rerun: false });
    ctx.set('skip', v.skip, null, { rerun: false });
    ctx.set('seed', v.seed);
  }

  function triangle(ctx) {
    const res = ctx.mi && ctx.mi.res;
    const hasModel = !!(res && res.analysis);
    return [
      ctx.check('Missing Data', 'missingData', null, true),
      ctx.check('Pooled Estimates', 'pooled', null, true, { disabled: !hasModel }),
      ctx.check('Imputation Diagnostics', 'diagnostics', null, true),
      ctx.check('Method and Assumptions', 'about', null, true),
      { separator: true },
      { label: 'Method', submenu: () => METHODS.map(([k, l]) => ({ label: l, checked: ctx.opt('method', 'mice') === k, action: () => { ctx.set('burnin', null, null, { rerun: false }); ctx.set('skip', null, null, { rerun: false }); ctx.set('method', k); } })) },
      { label: 'Analysis Model Type', disabled: !hasModel, submenu: () => MODELS.map(([k, l]) => ({ label: l, checked: (res && res.model) === k, action: () => ctx.set('model', k) })) },
      { label: 'Imputations…', action: () => imputationsDialog(ctx) },
      { separator: true },
      { label: 'Save', disabled: !res || !res.imputed.length, submenu: () => [
        { label: 'Imputed Table…', action: () => chooseImputation(ctx) },
        { label: `All ${res ? res.m : ''} Imputations Stacked`.replace('  ', ' '), action: () => saveStacked(ctx) },
        { label: 'Average of the Imputations as New Columns', action: () => saveAverage(ctx) },
      ] },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
  }

  /* ---- the report ---------------------------------------------------------------------------------------------- */
  async function render(ctx) {
    ctx.mi = null;
    const base = payloadOf(ctx);
    const note = el('p', { class: 'sm-ob-note sm-mi-progress', text: 'Imputing…', role: 'status' });
    ctx.container.append(note);
    const off = SM.engine.on('log', (m) => {
      const k = /^smui:progress mi (\d+) (\d+)/.exec((m && m.text) || '');
      if (!k) return;
      const text = `Multiple imputation${ctx.byLabel ? ` (${ctx.byLabel})` : ''}: cycle ${k[1]} of ${k[2]}…`;
      note.textContent = text;
      ctx.report.noteEl.textContent = text;
    });
    let res;
    try { res = await ctx.call('mi.fit', base); } finally { off(); note.remove(); }
    if (res.error) { ctx.container.append(ctx.warn(res.error)); return; }
    ctx.mi = { res };
    summary(ctx, res);
    if (ctx.opt('missingData', true)) missingOutline(ctx, res);
    if (res.analysis && ctx.opt('pooled', true)) pooledOutline(ctx, res);
    if (ctx.opt('diagnostics', true)) diagnosticsOutline(ctx, res);
    if (!res.analysis || !ctx.opt('pooled', true)) ctx.container.append(ctx.code(res.code));
    if (ctx.opt('about', true)) aboutOutline(ctx);
  }

  /* ---- the example table: a simulated health survey with missing values ------------------------------------------ */
  /* 400 people. Systolic blood pressure depends on age, BMI, cholesterol and
     activity: sbp = 60 + 0.45 age + 1.1 bmi + 3.5 cholesterol − 1.2 activity
     + e, e ~ N(0, 9²). BMI, cholesterol and activity are missing at random,
     more often the higher the blood pressure (and, for activity, the age):
     the complete cases have too few people with high blood pressure, and
     their regression is biased; multiple imputation with blood pressure in
     the imputation recovers the coefficients. resources/tests/smui/test_mi.py
     makes the same table. */
  function makeHealth() {
    const r = SM.util.rng('incomplete-health-3');
    const L = (z) => 1 / (1 + Math.exp(-z));
    const c = { id: [], age: [], bmi: [], activity: [], cholesterol: [], sbp: [] };
    for (let i = 0; i < 400; i++) {
      const age = 25 + Math.floor(r.u() * 51);
      const bmi = +(20 + 0.08 * age + r.normal(0, 3.2)).toFixed(1);
      const act = +Math.max(0, 7 - 0.06 * age - 0.12 * (bmi - 25) + r.normal(0, 2)).toFixed(1);
      const chol = +(3.6 + 0.03 * age + 0.04 * (bmi - 25) + r.normal(0, 0.8)).toFixed(2);
      const sbp = Math.round(60 + 0.45 * age + 1.1 * bmi + 3.5 * chol - 1.2 * act + r.normal(0, 9));
      const mb = r.u() < L(-1.0 + 0.12 * (sbp - 130));
      const mc = r.u() < L(-1.0 + 0.12 * (sbp - 130));
      const ma = r.u() < L(-1.3 + 0.03 * (age - 50) + 0.1 * (sbp - 130));
      c.id.push(`H${String(i + 1).padStart(3, '0')}`); c.age.push(age); c.bmi.push(mb ? NaN : bmi); c.activity.push(ma ? NaN : act);
      c.cholesterol.push(mc ? NaN : chol); c.sbp.push(sbp);
    }
    return new SM.Table({ name: 'Health survey', source: 'simulated', columns: [
      { name: 'id', dataType: 'character', values: c.id, role: 'label' },
      { name: 'age', dataType: 'numeric', values: c.age, notes: 'years' },
      { name: 'bmi', dataType: 'numeric', values: c.bmi, notes: 'body mass index, kg/m²; missing more often when the blood pressure is high' },
      { name: 'activity', dataType: 'numeric', values: c.activity, notes: 'exercise, hours a week; missing more often for the old and when the blood pressure is high' },
      { name: 'cholesterol', dataType: 'numeric', values: c.cholesterol, notes: 'mmol/L; missing more often when the blood pressure is high' },
      { name: 'sbp', dataType: 'numeric', values: c.sbp, notes: 'systolic blood pressure, mmHg: 60 + 0.45 age + 1.1 bmi + 3.5 cholesterol − 1.2 activity + noise (sd 9)' },
    ] });
  }
  SM.io.addExample('incomplete', {
    label: 'Health survey (400 people, missing values): blood pressure, age, BMI, cholesterol, activity',
    about: 'Simulated survey with values missing at random: BMI, cholesterol and activity are missing for a fifth to a quarter of the 400 people, more often the higher their blood pressure. The true regression is sbp = 60 + 0.45 age + 1.1 bmi + 3.5 cholesterol − 1.2 activity + noise: the complete cases (232 people) get the intercept, age, BMI and cholesterol wrong, multiple imputation with blood pressure in the imputation gets them right. For Multiple Imputation and Explore Missing Values.',
    truth: { Intercept: 60, age: 0.45, bmi: 1.1, cholesterol: 3.5, activity: -1.2 },
    make: makeHealth,
  });

  /* ---- Help -------------------------------------------------------------------------------------------------------- */
  const TOPICS = {
    'p:mi': {
      kicker: 'Analyze > Screening', title: 'Multiple Imputation',
      lead: 'The missing values filled in several times, an analysis model fitted to each completed table, and the fits pooled by Rubin\'s rules: statsmodels\' MICE (chained equations) or BayesGaussMI (a multivariate normal). The companion of Explore Missing Values, which imputes once.',
      sections: [
        { heading: 'Roles', choices: [['Y, Columns to Impute', 'The columns to fill in; each is imputed from all the others, and used to impute them. Continuous columns, and (MICE) two-level or ordinal ones.'],
          ['Model Response', 'The analysis model\'s Y (optional). Empty: impute only, and save the imputed tables.'], ['By', 'A separate imputation for each level.']] },
        { heading: 'Analysis Model', text: 'Add the effects of the model from the selected columns (Cross for an interaction) and choose its type. Its columns join the imputation. Nominal effects are effect coded and continuous columns centred in crossings, as JMP does.' },
        { heading: 'In the red triangle', text: 'Method, Analysis Model Type and Imputations… (m, the burn-in, the cycles skipped and the seed) change the report without relaunching it; a new method goes back to its own default burn-in and skip.' },
        { heading: 'Report and Save', text: 'Missing Data, the Pooled Estimates beside the complete-case fit, the Imputation Diagnostics. Save (red triangle) writes one imputed table, all m stacked with .imp and .id columns, or the average of the imputations as new columns.' },
      ],
      more: MORE,
    },
    'p:mi:missing': {
      kicker: 'Multiple Imputation', title: 'Missing Data',
      lead: 'How many values each column misses (Missing Columns Report) and which combinations are missing together (Missing Value Report), over the report\'s rows, as Explore Missing Values shows them. Click a line to select its rows.',
      sections: [{ heading: 'In the report', choices: [['A line of Missing Columns Report', 'click it to select the rows where that column is missing.'],
        ['A line of Missing Value Report', 'click it to select the rows with that pattern: missing exactly in the columns with a 1.'],
        ['The red triangle', 'Select Rows with Missing selects every row that misses a value in these columns, Select Complete Rows the others.']] }],
      more: MORE,
    },
    'p:mi:pooled': {
      kicker: 'Multiple Imputation', title: 'Pooled Estimates',
      lead: 'The analysis model\'s estimates pooled over the imputations by Rubin\'s rules, statsmodels\' MICE.fit or MI.fit, with the complete-case fit beside them.',
      sections: [{ choices: [['Estimate', 'the mean of the m estimates'], ['Std Error', '√T, T = W + (1 + 1/m) B'], ['z Ratio, Prob>|z|', 'statsmodels pools with the normal distribution'],
        ['FMI', 'the fraction of missing information, (1 + 1/m) B / T: how much of the estimate\'s uncertainty comes from the missing values'],
        ['Optional columns', 'right click the table: W, B, T, RIV (the relative increase in variance), DF (Barnard–Rubin), Prob>|t| on that DF and FMI (mice)'],
        ['Complete cases', 'the same model on the rows with every model column observed']] }],
      more: MORE,
    },
    'p:mi:diagnostics': {
      kicker: 'Multiple Imputation', title: 'Imputation Diagnostics',
      lead: 'For each imputed column: its observed and imputed values overlaid, and the trace of the imputed values\' mean over the imputer\'s cycles (the burn-in shaded, the imputations dotted). A trace with a trend after the burn-in asks for a longer burn-in.',
      sections: [{ heading: 'In the report', choices: [['A bar', 'click an Observed bar to select the rows whose value falls in it, an Imputed bar the rows with an imputed value there in any of the imputations (a bin, or a level for a categorical column).'],
        ['A column\'s red triangle', 'shows or hides its Observed and Imputed graph and its Trace; Select Rows Imputed selects the rows whose value was missing.']] }],
      more: MORE,
    },
    'p:mi:model': { kicker: 'Multiple Imputation', title: 'Analysis Model', lead: 'The model fitted to every imputed table: the Model Response on these effects (Add a column, Cross columns for an interaction, Remove). Least Squares for a continuous response, Logistic or Probit for a two-level one, Poisson for counts. No effects: the pooled mean of the response.', more: MORE },
    'p:mi:method': {
      kicker: 'Multiple Imputation', title: 'Imputation',
      lead: 'How the missing values are drawn.',
      sections: [{ choices: [['MICE', 'chained equations: each column in turn regressed on the others, its missing values drawn by predictive mean matching (observed values of the 20 nearest rows); for mixed data'],
        ['Bayesian Gaussian', 'a Gibbs sampler of a multivariate normal; continuous columns (the page standardizes them for statsmodels\' priors)']] },
      { text: 'Both run one chain: the burn-in cycles, then an imputation every skip + 1 cycles, m in all. More imputations make the pooled standard errors steadier; the seed makes the imputations repeatable, here and in the Python shown.' }],
      more: MORE,
    },
    'p:mi:save': { kicker: 'Multiple Imputation', title: 'Save', lead: 'Imputed Table: a new table with the missing values filled in from one imputation. All Imputations Stacked: the m tables one after another, with .imp (the imputation) and .id (the row). Average of the Imputations: new columns in this table, each missing value replaced by the mean (or most frequent level) of its imputations; a single filled-in column understates the uncertainty, which is why the pooled fit is the one to report.', more: MORE },
    'p:mi:about': { kicker: 'Multiple Imputation', title: 'Method and Assumptions', lead: 'What multiple imputation assumes (values missing at random), how statsmodels\' two imputers work and pool, and how they differ from R\'s mice.', more: MORE },
  };

  /* ---- the platform ------------------------------------------------------------------------------------------------ */
  SM.platforms.register({
    id: 'mi', label: 'Multiple Imputation', menu: 'Analyze/Screening', order: 25, info: 'p:mi', topics: TOPICS,
    about: 'Multiple imputation of missing values with statsmodels\' MICE (chained equations with predictive mean matching) or BayesGaussMI (a multivariate normal Gibbs sampler), an analysis model (least squares, logistic, probit, Poisson; effect-coded factors and crossings) fitted to each imputed table and pooled by Rubin\'s rules, with the fraction of missing information, the within, between and total variances, the Barnard–Rubin degrees of freedom and the complete-case fit for contrast; missing-data reports linked to the rows, the observed and imputed distributions and the trace of the imputations; saved imputed tables (one, or all stacked) and averaged columns. Standard JMP has no pooled multiple imputation.',
    uses: ['statsmodels.imputation.mice.MICEData, MICE, MICEResults', 'statsmodels.imputation.bayes_mi.BayesGaussMI, MI, MIResults', 'statsmodels.regression.linear_model.OLS', 'statsmodels.genmod.generalized_linear_model.GLM (Binomial, Poisson)', 'scipy.stats.t (the Barnard–Rubin tests)', 'patsy'],
    launch: {
      lead: 'Fill in the missing values of the columns several times, fit an analysis model to each completed table and pool the fits (Rubin\'s rules). The imputation uses every column cast here and in the model.',
      roles: [
        { key: 'y', label: 'Y, Columns to Impute', min: 1, hint: 'required: impute these, and impute from them',
          help: 'The columns whose missing values are filled in; each is imputed from all the other columns of the imputation and helps to impute them. Continuous columns, and with MICE two-level and ordinal ones too (a nominal column of more levels may help but not be imputed). Include every column that predicts the missing values, or whether they are missing.' },
        { key: 'response', label: 'Model Response', max: 1, hint: 'optional: the analysis model\'s Y; empty: impute only',
          help: 'The Y of the analysis model that is fitted to every completed table and pooled. It joins the imputation, as it must, and may have missing values itself; a categorical one takes two levels (Logistic or Probit). Empty: the report imputes only, for Save.' },
        { key: 'by', label: 'By', hint: 'optional',
          help: 'A separate imputation, and analysis, of the rows of each level (each combination of levels, with several By columns). Rows with a missing By value are left out.' },
      ],
      extra: launchExtra,
      validate,
    },
    title(spec, table) {
      const id = ((spec.roles || {}).response || [])[0];
      const c = id && table ? table.col(id) : null;
      return c ? `Multiple Imputation: ${c.name}` : 'Multiple Imputation';
    },
    triangle,
    render,
  });
}(typeof self !== 'undefined' ? self : this));
