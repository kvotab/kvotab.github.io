/* ==========================================================================
   SMUI.HTML: ANALYZE > DISTRIBUTION

   One outline per column. Continuous: histogram and outlier box plot,
   quantiles, summary statistics, and from the red triangle the normal
   quantile plot, CDF plot, stem and leaf, tests of the mean and the
   standard deviation, equivalence, confidence, prediction and tolerance
   intervals, capability and fitted distributions. Ordinal and nominal:
   bar chart, frequencies, confidence intervals, mosaic, test of
   probabilities.

   This is the reference platform: it uses every part of the report
   context (see smui-report.js) and is the one to copy.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt, qnorm, ranks } = SM.util;
  const { isMissing } = SM.table;

  const FITS = [['normal', 'Normal'], ['cauchy', 'Cauchy'], ['t', "Student's t"], ['lognormal', 'Lognormal'], ['weibull', 'Weibull'], ['exponential', 'Exponential'], ['gamma', 'Gamma'], ['beta', 'Beta'],
    ['logistic', 'Logistic'], ['normal2', 'Normal 2 Mixture'], ['normal3', 'Normal 3 Mixture'], ['johnsonsu', 'Johnson Su'], ['johnsonsb', 'Johnson Sb'], ['kde', 'Smooth Curve']];
  const DISCRETE = [['poisson', 'Poisson'], ['negbin', 'Gamma Poisson']];
  const FIT_COLORS = ['#b0413e', '#3a7d44', '#6c5b7b', '#c0a000', '#1f9e89', '#8c564b', '#e377c2', '#17becf', '#7f7f7f'];
  const pctLabel = (p) => `${(100 * p).toFixed(1)}%`;

  /* ---- the values of one column for the rows of the report ------------------- */
  function valuesOf(ctx, col) {
    const w = ctx.role('weight'), f = ctx.role('freq');
    const vals = [], rows = [], wts = [];
    for (const r of ctx.rows) {
      const v = col.values[r];
      if (typeof v !== 'number' || !Number.isFinite(v)) continue;
      let wt = 1;
      if (w) wt *= w.values[r];
      if (f) wt *= f.values[r];
      if (!(wt > 0) || !Number.isFinite(wt)) continue;
      vals.push(v); rows.push(r); wts.push(wt);
    }
    return { vals, rows, wts, weighted: !!(w || f) };
  }

  /* Histogram bins as bars: the rows in each bin, for linking. */
  function histBars(vals, rows, wts, bins) {
    const nb = Math.max(1, Math.round((bins.end - bins.start) / bins.size));
    const counts = new Array(nb).fill(0), members = Array.from({ length: nb }, () => []);
    for (let k = 0; k < vals.length; k++) {
      const j = Math.min(nb - 1, Math.max(0, Math.floor((vals[k] - bins.start) / bins.size + 1e-9)));
      counts[j] += wts[k];
      members[j].push(rows[k]);
    }
    const centers = counts.map((_, j) => bins.start + (j + 0.5) * bins.size);
    return { centers, counts, members, nb };
  }

  function quantileOf(res, p) {
    const q = res.quantiles.find((x) => Math.abs(x.p - p) < 1e-9);
    return q ? q.value : NaN;
  }

  /* ---- continuous ------------------------------------------------------------ */
  async function continuous(ctx, col, parent, shared) {
    const sc = col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const outline = ctx.outline(col.name, { parent, menu: () => contMenu(ctx, col), key: `col:${col.id}` });
    const payload = { column: col.name, weight: ctx.name('weight'), freq: ctx.name('freq'), alpha: ctx.alpha };
    const res = await ctx.call('distribution.continuous', payload);
    if (res.error) { outline.add(ctx.warn(`${col.name}: ${res.error}`)); return; }
    const { vals, rows, wts, weighted } = valuesOf(ctx, col);
    const horizontal = o('horizontal', !!shared.stack);
    const probAxis = o('axis', 'count');
    const m = res.moments;

    // Fitted distributions first: their curves go on the histogram.
    const fits = [];
    for (const key of o('fits', [])) {
      try { fits.push(await ctx.call('distribution.fit', { column: col.name, dist: key, alpha: ctx.alpha })); } catch (e) { fits.push({ dist: key, label: key, error: e.message }); }
    }
    const cap = o('cap', null);
    let capRes = null;
    if (cap) capRes = await ctx.call('distribution.capability', { column: col.name, lsl: cap.lsl, usl: cap.usl, target: cap.target, alpha: ctx.alpha });

    // ---- the graph: histogram beside (or above) the outlier box plot
    const range = shared.uniform || null;
    const lo = range ? range[0] : m.min, hi = range ? range[1] : m.max;
    const bins = o('binWidth', null) ? (() => { const size = o('binWidth'); const start = Math.floor(lo / size) * size; let end = Math.ceil(hi / size) * size; if (end <= hi) end += size; return { start, end, size }; })() : SM.report.niceBins(range ? [lo, hi, ...vals] : vals);
    const hb = histBars(vals, rows, wts, bins);
    const total = hb.counts.reduce((a, b) => a + b, 0);
    const scale = probAxis === 'prob' ? 1 / total : probAxis === 'density' ? 1 / (total * bins.size) : 1;
    const heights = hb.counts.map((c) => c * scale);
    const showCounts = o('showCounts', false), showPct = o('showPercents', false);
    const barText = showCounts || showPct ? hb.counts.map((c) => [showCounts ? fmt(c) : '', showPct ? `${(100 * c / total).toFixed(1)}%` : ''].filter(Boolean).join(' ')) : undefined;
    const traces = [];
    const valAxis = horizontal ? 'x' : 'y';
    const cntAxis = horizontal ? 'y' : 'x';
    const bar = {
      type: 'bar', orientation: horizontal ? 'v' : 'h', width: bins.size, rows: hb.members, rowsScale: scale,
      marker: { color: SM.report.BAR, line: { color: SM.util.themeColors().surface, width: 0.8 } },
      text: barText, textposition: barText ? 'outside' : undefined, cliponaxis: false,
      hovertemplate: `${horizontal ? '%{x}' : '%{y}'}: %{${horizontal ? 'y' : 'x'}}<extra></extra>`, name: 'Histogram',
    };
    bar[valAxis] = hb.centers;
    bar[cntAxis] = heights;
    if (o('histogram', true)) traces.push(bar);
    // Fitted curves, scaled to the histogram's axis.
    fits.forEach((f, i) => {
      if (!f.curve || f.error || !o(`curve:${f.dist}`, true)) return;
      const k = f.curve.discrete ? 1 : bins.size;
      const ys = (f.curve.pdf || f.curve.pmf).map((d) => d * total * k * scale);
      const tr = { type: 'scatter', mode: f.curve.discrete ? 'lines+markers' : 'lines', line: { color: FIT_COLORS[i % FIT_COLORS.length], width: 2, shape: f.curve.discrete ? 'hvh' : 'spline' }, hoverinfo: 'skip', name: f.label };
      tr[valAxis] = f.curve.x;
      tr[cntAxis] = ys;
      traces.push(tr);
    });
    // Outlier box plot from JMP's quartiles, on a small axis of its own.
    const q1 = quantileOf(res, 0.25), q3 = quantileOf(res, 0.75), med = quantileOf(res, 0.5);
    const iqr = q3 - q1;
    let lf = Infinity, uf = -Infinity;
    for (const v of vals) { if (v >= q1 - 1.5 * iqr && v < lf) lf = v; if (v <= q3 + 1.5 * iqr && v > uf) uf = v; }
    const box2 = horizontal ? { x: 'x', y: 'y2' } : { x: 'x2', y: 'y' };
    const inBox = (a, b) => (horizontal ? { x: b, y: a } : { x: a, y: b });
    if (o('box', true)) {
      const bx = { type: 'box', name: '', q1: [q1], median: [med], q3: [q3], lowerfence: [lf], upperfence: [uf], boxpoints: false, fillcolor: 'rgba(143,169,194,0.25)', line: { color: SM.util.themeColors().text, width: 1 }, hoverinfo: 'skip', xaxis: box2.x, yaxis: box2.y, orientation: horizontal ? 'h' : 'v', width: 0.55 };
      if (horizontal) bx.y = [0]; else bx.x = [0];
      traces.push(bx);
      const out = [], outRows = [];
      vals.forEach((v, k) => { if (v < lf || v > uf) { out.push(v); outRows.push(rows[k]); } });
      if (out.length) traces.push({ type: 'scatter', mode: 'markers', ...inBox(out.map(() => 0), out), rows: outRows, marker: { size: 6, color: SM.report.BASE }, xaxis: box2.x, yaxis: box2.y, name: 'Outliers' });
      // Mean diamond: the mean and its confidence interval.
      if (Number.isFinite(m.lower)) {
        const d = [[0, m.lower], [0.26, m.mean], [0, m.upper], [-0.26, m.mean], [0, m.lower]];
        traces.push({ type: 'scatter', mode: 'lines', ...inBox(d.map((p) => p[0]), d.map((p) => p[1])), line: { color: '#b0413e', width: 1.3 }, hovertemplate: `mean ${fmt(m.mean)}<br>${fmt(100 * (1 - ctx.alpha))}% CI ${fmt(m.lower)} to ${fmt(m.upper)}<extra></extra>`, xaxis: box2.x, yaxis: box2.y, name: 'Mean' });
      }
      // Shortest half: the densest half of the values, as a bracket.
      if (m.shortest_half) {
        const [a, b] = m.shortest_half;
        traces.push({ type: 'scatter', mode: 'lines', ...inBox([0.42, 0.48, 0.48, 0.42], [a, a, b, b]), line: { color: '#c0392b', width: 1.6 }, hovertemplate: `shortest half ${fmt(a)} to ${fmt(b)}<extra></extra>`, xaxis: box2.x, yaxis: box2.y, name: 'Shortest half' });
      }
    }
    if (o('qbox', false)) {
      const qs = [0.005, 0.025, 0.1, 0.9, 0.975, 0.995].map((p) => quantileOf(res, p));
      const pos = 0.75;
      traces.push({ type: 'box', q1: [q1], median: [med], q3: [q3], lowerfence: [m.min], upperfence: [m.max], boxpoints: false, fillcolor: 'rgba(0,0,0,0)', line: { color: SM.util.themeColors().muted, width: 1 }, hoverinfo: 'skip', xaxis: box2.x, yaxis: box2.y, orientation: horizontal ? 'h' : 'v', width: 0.3, ...(horizontal ? { y: [pos] } : { x: [pos] }) });
      traces.push({ type: 'scatter', mode: 'markers', ...inBox(qs.map(() => pos), qs), marker: { symbol: horizontal ? 'line-ns' : 'line-ew', size: 12, line: { width: 1.5, color: SM.util.themeColors().muted } }, hovertemplate: '%{text}<extra></extra>', text: ['0.5%', '2.5%', '10%', '90%', '97.5%', '99.5%'].map((l, i) => `${l}: ${fmt(qs[i])}`), xaxis: box2.x, yaxis: box2.y, name: 'Quantile box' });
    }
    const shapes = [];
    if (cap) {
      for (const [key, label, dash] of [['lsl', 'LSL', 'solid'], ['target', 'Target', 'dot'], ['usl', 'USL', 'solid']]) {
        if (cap[key] == null) continue;
        const line = horizontal ? { type: 'line', xref: 'x', yref: 'paper', x0: cap[key], x1: cap[key], y0: 0, y1: 1 } : { type: 'line', yref: 'y', xref: 'paper', y0: cap[key], y1: cap[key], x0: 0, x1: 1 };
        shapes.push({ ...line, line: { color: '#c0392b', width: 1.3, dash }, label: { text: label, font: { size: 10, color: '#c0392b' }, textposition: 'end' } });
      }
    }
    const cntTitle = probAxis === 'prob' ? 'Probability' : probAxis === 'density' ? 'Density' : 'Count';
    const valRange = range ? [range[0] - 0.02 * (range[1] - range[0]), range[1] + 0.02 * (range[1] - range[0])] : undefined;
    const layout = horizontal ? {
      xaxis: { title: { text: col.name }, range: valRange }, yaxis: { title: { text: cntTitle }, domain: [0.3, 1], rangemode: 'tozero' },
      yaxis2: { domain: [0, 0.22], showticklabels: false, showgrid: false, zeroline: false, showline: false, ticks: '', range: [-0.6, o('qbox', false) ? 1.1 : 0.6] },
      margin: { l: 56, r: 12, t: 8, b: 40 }, shapes,
    } : {
      yaxis: { title: { text: col.name }, range: valRange }, xaxis: { title: { text: cntTitle }, domain: [0, 0.7], rangemode: 'tozero' },
      xaxis2: { domain: [0.76, 1], showticklabels: false, showgrid: false, zeroline: false, showline: false, ticks: '', range: [-0.6, o('qbox', false) ? 1.1 : 0.6] },
      margin: { l: 56, r: 8, t: 8, b: 40 }, shapes,
    };
    if (shared.histOnly) { delete layout.xaxis2; delete layout.yaxis2; }
    const graph = ctx.plot(shared.histOnly ? traces.slice(0, 1) : traces, layout, { width: horizontal ? 470 : 330, height: horizontal ? 290 : 330, title: `${col.name} histogram` });

    if (shared.histOnly) { outline.add(graph); return; }

    // ---- quantiles and summary statistics
    const quant = ctx.outline('Quantiles', { parent: outline, closed: !o('quantiles', true), key: 'quantiles' });
    quant.add(ctx.rt({
      columns: [{ key: 'pct', label: '', fmt: 'text' }, { key: 'label', label: '', fmt: 'text' }, { key: 'value', label: 'Value' }],
      rows: res.quantiles.map((q) => ({ pct: pctLabel(q.p), label: q.label, value: q.value })),
    }, { sortable: false }));
    const sum = ctx.outline('Summary Statistics', { parent: outline, closed: !o('summary', true), key: 'summary' });
    const level = fmt(100 * (1 - ctx.alpha));
    const chosen = o('stats', ['mean', 'sd', 'se', 'upper', 'lower', 'n']);
    const STAT_ROWS = statRows(m, res, level, weighted);
    sum.add(ctx.kv(STAT_ROWS.filter((s) => chosen.includes(s[0])).map((s) => [s[1], s[2]])));

    const side = el('div', { class: 'sm-dist-tables' }, quant.el, sum.el);
    outline.add(horizontal ? [graph, ctx.row(quant.el, sum.el)] : ctx.row(graph, side));
    sum.add(ctx.code(res.code));
    if (res.normality && o('normality', false)) {
      const nt = ctx.outline('Normality Tests', { parent: outline, key: 'normality' });
      nt.add(ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'stat', label: 'Statistic' }, { key: 'p', label: 'p-Value', fmt: 'p' }], rows: res.normality }),
        ctx.note('A small p-value is evidence against normality. Shapiro-Wilk is scipy\'s; Anderson-Darling, Lilliefors and Jarque-Bera are statsmodels\'.'));
    }

    // ---- the optional outlines, in JMP's order
    if (o('qq', false)) {
      const qq = await ctx.call('distribution.qq', { column: col.name });
      const zmin = Math.min(...qq.z), zmax = Math.max(...qq.z);
      const ob = ctx.outline('Normal Quantile Plot', { parent: outline, key: 'qq', menu: () => [ctx.check('Show Probability Axis', 'qqProb', sc, false)] });
      const traces2 = [
        { type: 'scatter', mode: 'markers', x: qq.z, y: qq.x, rows: qq.rows, name: col.name },
        { type: 'scatter', mode: 'lines', x: [zmin, zmax], y: [qq.mean + qq.sd * zmin, qq.mean + qq.sd * zmax], line: { color: '#b0413e', width: 1.3 }, hoverinfo: 'skip', name: 'Normal line' },
      ];
      const probTicks = [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99];
      ob.add(ctx.plot(traces2, {
        xaxis: o('qqProb', false) ? { title: { text: 'Normal Quantile Plot (probability)' }, tickvals: probTicks.map(qnorm), ticktext: probTicks.map(String) } : { title: { text: 'Normal Quantile' } },
        yaxis: { title: { text: col.name } },
      }, { width: 380, height: 300, title: `${col.name} normal quantile plot` }),
      ctx.note('Each value against Φ⁻¹(r/(n+1)), r its rank. Points near the line are consistent with a normal distribution with the sample mean and standard deviation.'));
    }
    if (o('cdf', false)) {
      const order = vals.map((_, k) => k).sort((a, b) => vals[a] - vals[b]);
      const x = order.map((k) => vals[k]);
      const cum = []; let acc = 0; const wsum = wts.reduce((a, b) => a + b, 0);
      for (const k of order) { acc += wts[k]; cum.push(acc / wsum); }
      const ob = ctx.outline('CDF Plot', { parent: outline, key: 'cdf' });
      ob.add(ctx.plot([{ type: 'scatter', mode: 'lines+markers', x, y: cum, rows: order.map((k) => rows[k]), line: { shape: 'hv', color: SM.report.BASE, width: 1.5 }, marker: { size: 4 }, name: 'CDF' }],
        { xaxis: { title: { text: col.name } }, yaxis: { title: { text: 'Cumulative Probability' }, range: [0, 1.02] } }, { width: 420, height: 280, title: `${col.name} CDF` }));
    }
    if (o('stem', false)) stemLeaf(ctx, vals, col.name, outline);
    const tm = o('testMean', null);
    if (tm) {
      const r = await ctx.call('distribution.test_mean', { column: col.name, mu: tm.mu, sigma: tm.sigma || null, wilcoxon: true, weight: ctx.name('weight'), freq: ctx.name('freq') });
      const ob = ctx.outline(`Test Mean`, { parent: outline, key: 'testmean', menu: () => [{ label: 'Remove Test', action: () => ctx.set('testMean', null, sc) }] });
      if (r.error) ob.add(ctx.warn(r.error));
      else {
        ob.add(ctx.kv([['Hypothesized Value', r.mu], ['Actual Estimate', r.mean], ['DF', r.df], ['Std Dev', r.sd], r.z ? ['Sigma given', r.z.sigma] : null]));
        const cols = [{ key: 'row', label: '', fmt: 'text' }, { key: 't', label: 't Test' }];
        if (r.z) cols.push({ key: 'z', label: 'z Test' });
        if (r.wilcoxon) cols.push({ key: 'w', label: 'Signed-Rank' });
        const rowsT = [['Test Statistic', 'stat', 'num'], ['Prob > |t|', 'p_two', 'p'], ['Prob > t', 'p_greater', 'p'], ['Prob < t', 'p_less', 'p']].map(([label, key]) => ({ row: label, t: r.t[key], z: r.z ? r.z[key] : null, w: r.wilcoxon ? r.wilcoxon[key] : null, _p: key !== 'stat' }));
        ob.add(pTable(ctx, cols, rowsT), ctx.code(r.code));
      }
    }
    const tsd = o('testSd', null);
    if (tsd) {
      const r = await ctx.call('distribution.test_sd', { column: col.name, sigma: tsd.sigma });
      const ob = ctx.outline('Test Standard Deviation', { parent: outline, key: 'testsd', menu: () => [{ label: 'Remove Test', action: () => ctx.set('testSd', null, sc) }] });
      if (r.error) ob.add(ctx.warn(r.error));
      else ob.add(ctx.kv([['Hypothesized Value', r.sigma], ['Actual Estimate', r.sd], ['DF', r.df], ['ChiSquare', r.chi2], ['Min PValue', r.p_two, 'p'], ['Prob < ChiSq', r.p_less, 'p'], ['Prob > ChiSq', r.p_greater, 'p']]),
        ctx.note('(n−1)s²/σ² against χ² with n−1 degrees of freedom; it assumes normal data.'));
    }
    const eq = o('equiv', null);
    if (eq) {
      const r = await ctx.call('distribution.equivalence', { column: col.name, low: eq.low, upp: eq.upp, alpha: ctx.alpha });
      const ob = ctx.outline('Test Equivalence (TOST)', { parent: outline, key: 'equiv', menu: () => [{ label: 'Remove Test', action: () => ctx.set('equiv', null, sc) }] });
      if (r.error) ob.add(ctx.warn(r.error));
      else {
        ob.add(ctx.kv([['Lower bound', r.low], ['Upper bound', r.upp], ['Mean', r.mean], [`${fmt(100 * (1 - 2 * ctx.alpha))}% CI of the mean`, `${fmt(r.ci[0])} to ${fmt(r.ci[1])}`, 'text']]));
        ob.add(ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 't', label: 't Ratio' }, { key: 'df', label: 'DF' }, { key: 'p', label: 'p-Value', fmt: 'p' }], rows: [{ test: `Lower: mean > ${fmt(r.low)}`, ...r.lower }, { test: `Upper: mean < ${fmt(r.upp)}`, ...r.upper }, { test: 'Max over both', t: null, df: null, p: r.p }] }),
          ctx.note(r.p < ctx.alpha ? `The mean is equivalent to the range at α = ${ctx.alpha}: both one-sided tests reject.` : `Equivalence is not shown at α = ${ctx.alpha}.`), ctx.code(r.code));
      }
    }
    const ci = o('ci', null);
    if (ci) {
      const r = await ctx.call('distribution.ci', { column: col.name, alpha: 1 - ci });
      const ob = ctx.outline('Confidence Intervals', { parent: outline, key: 'ci', menu: () => [{ label: 'Remove', action: () => ctx.set('ci', null, sc) }] });
      if (r.error) ob.add(ctx.warn(r.error));
      else ob.add(ctx.rt({ columns: [{ key: 'parameter', label: 'Parameter', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'lower', label: 'Lower CI' }, { key: 'upper', label: 'Upper CI' }, { key: 'level', label: '1−Alpha' }], rows: r.rows.map((x) => ({ ...x, level: ci })) }));
    }
    const pi = o('pi', null), ti = o('ti', null);
    if (pi || ti) {
      const r = await ctx.call('distribution.intervals', { column: col.name, alpha: pi ? 1 - pi.level : 1 - ti.level, k_future: pi ? pi.k : 1, coverage: ti ? ti.coverage : 0.9 });
      if (r.error) outline.add(ctx.warn(r.error));
      else {
        if (pi) {
          const ob = ctx.outline('Prediction Intervals', { parent: outline, key: 'pi', menu: () => [{ label: 'Remove', action: () => ctx.set('pi', null, sc) }] });
          const rowsP = [{ what: `Individual (${r.k} future value${r.k > 1 ? 's' : ''})`, lower: r.prediction.lower, upper: r.prediction.upper }, { what: `Mean of ${r.k} future`, lower: r.prediction_mean.lower, upper: r.prediction_mean.upper }];
          if (r.k > 1) rowsP.push({ what: `Std Dev of ${r.k} future`, lower: r.prediction_sd.lower, upper: r.prediction_sd.upper });
          ob.add(ctx.rt({ columns: [{ key: 'what', label: '', fmt: 'text' }, { key: 'lower', label: 'Lower PI' }, { key: 'upper', label: 'Upper PI' }], rows: rowsP }), ctx.note(`${fmt(100 * pi.level)}% prediction intervals from the normal model (Bonferroni over the future values), mean ${fmt(r.mean)}, s ${fmt(r.sd)}, n ${r.n}.`));
        }
        if (ti) {
          const ob = ctx.outline('Tolerance Intervals', { parent: outline, key: 'ti', menu: () => [{ label: 'Remove', action: () => ctx.set('ti', null, sc) }] });
          ob.add(ctx.rt({ columns: [{ key: 'what', label: 'Proportion', fmt: 'text' }, { key: 'lower', label: 'Lower TI' }, { key: 'upper', label: 'Upper TI' }, { key: 'k', label: 'k' }], rows: [{ what: pctLabel(r.coverage), lower: r.tolerance.lower, upper: r.tolerance.upper, k: r.tolerance.k }] }),
            ctx.note(`Covers ${pctLabel(r.coverage)} of a normal population with ${fmt(100 * ti.level)}% confidence (Howe's k), two-sided.`), ctx.code(r.code));
        }
      }
    }
    if (capRes) capability(ctx, outline, capRes, sc);
    // ---- fitted distributions
    fits.forEach((f, i) => {
      const ob = ctx.outline(f.dist === 'kde' ? 'Smooth Curve' : `Fitted ${f.label} Distribution`, { parent: outline, key: `fit:${f.dist}`, menu: () => [
        ctx.check('Density Curve', `curve:${f.dist}`, sc, true),
        ctx.check('Goodness of Fit', `gof:${f.dist}`, sc, true),
        { label: 'Remove Fit', action: () => ctx.set('fits', o('fits', []).filter((k) => k !== f.dist), sc) },
      ] });
      if (f.error) { ob.add(ctx.warn(typeof f.error === 'string' ? `${f.label}: ${f.error}` : f.error)); return; }
      ob.head.style.setProperty('--fit-color', FIT_COLORS[i % FIT_COLORS.length]);
      if (f.dist === 'kde') { ob.add(ctx.kv([['Bandwidth', f.bandwidth], ['N', f.n]]), ctx.note(f.note), ctx.code(f.code)); return; }
      if (f.note) ob.add(ctx.note(f.note));
      ob.add(ctx.rt({ caption: 'Parameter Estimates', columns: [{ key: 'name', label: 'Parameter', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'lower', label: `Lower ${fmt(100 * (1 - ctx.alpha))}%` }, { key: 'upper', label: `Upper ${fmt(100 * (1 - ctx.alpha))}%` }], rows: f.params }));
      ob.add(ctx.kv([['−2 log(Likelihood)', -2 * f.loglik], ['AICc', f.aicc], ['BIC', f.bic]]));
      if (o(`gof:${f.dist}`, true) && f.gof && f.gof.length) ob.add(ctx.rt({ caption: 'Goodness-of-Fit Test', columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'stat', label: 'Statistic' }, { key: 'p', label: 'p-Value', fmt: 'p' }], rows: f.gof }));
      ob.add(ctx.code(f.code));
    });
    if (o('fitAll', false)) {
      const r = await ctx.call('distribution.fit_all', { column: col.name });
      const ob = ctx.outline('Compare Distributions', { parent: outline, key: 'fitall', menu: () => [{ label: 'Remove', action: () => ctx.set('fitAll', false, sc) }] });
      if (r.error) ob.add(ctx.warn(r.error));
      else ob.add(ctx.rt({ columns: [{ key: 'label', label: 'Distribution', fmt: 'text' }, { key: 'k', label: 'Parameters', fmt: 'int' }, { key: 'm2ll', label: '−2 log L' }, { key: 'aicc', label: 'AICc' }, { key: 'weight', label: 'AICc Weight' }, { key: 'bic', label: 'BIC' }], rows: r.fits.map((x) => ({ ...x, m2ll: -2 * x.loglik })) },
        { onRow: (row) => { const cur = o('fits', []); if (!cur.includes(row.dist)) ctx.set('fits', [...cur, row.dist], sc); } }),
        ctx.note('Maximum likelihood fits, best first by AICc. Click a line to show that fit.'));
    }
  }

  function statRows(m, res, level, weighted) {
    return [
      ['mean', 'Mean', m.mean], ['sd', 'Std Dev', m.sd], ['se', 'Std Err Mean', m.se],
      ['upper', `Upper ${level}% Mean`, m.upper], ['lower', `Lower ${level}% Mean`, m.lower], ['n', 'N', m.n],
      ['sumw', 'Sum Weight', m.sum_w], ['sum', 'Sum', m.sum], ['var', 'Variance', m.var],
      ['skewness', 'Skewness', m.skewness], ['kurtosis', 'Kurtosis', m.kurtosis], ['cv', 'CV', m.cv],
      ['nmiss', 'N Missing', res.n_missing], ['nzero', 'N Zero', m.n_zero], ['nunique', 'N Unique', m.n_unique],
      ['uss', 'Uncorrected SS', m.uss], ['css', 'Corrected SS', m.css], ['autocorr', 'Autocorrelation', m.autocorr],
      ['min', 'Minimum', m.min], ['max', 'Maximum', m.max], ['median', 'Median', m.median],
      ['mode', 'Mode', m.mode], ['trimmed', 'Trimmed Mean (5%)', m.trimmed], ['geomean', 'Geometric Mean', m.geomean],
      ['range', 'Range', m.range], ['iqr', 'Interquartile Range', m.iqr], ['mad', 'Median Absolute Deviation', m.mad],
      ['robust_mean', 'Robust Mean (Huber)', m.robust_mean], ['robust_sd', 'Robust Std Dev (Huber)', m.robust_sd],
    ].filter((r) => !(weighted && ['skewness', 'kurtosis', 'geomean', 'trimmed', 'mad', 'mode', 'robust_mean', 'robust_sd', 'autocorr'].includes(r[0])));
  }

  function pTable(ctx, cols, rows) {
    const t = ctx.rt({ columns: cols.map((c) => ({ ...c, fmt: c.fmt || 'num' })), rows }, { sortable: false });
    // Rows 2-4 are p-values: format them so.
    t.querySelectorAll('tbody tr').forEach((tr, i) => {
      if (!rows[i]._p) return;
      tr.querySelectorAll('td').forEach((td, j) => {
        if (j === 0) return;
        const v = rows[i][cols[j].key];
        td.textContent = SM.util.fmtP(v, ctx.alpha);
        td.classList.toggle('p-sig', typeof v === 'number' && v < ctx.alpha);
      });
    });
    return t;
  }

  function capability(ctx, outline, r, sc) {
    const ob = ctx.outline('Process Capability', { parent: outline, key: 'cap', info: 'p:capability', menu: () => [{ label: 'Remove', action: () => ctx.set('cap', null, sc) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    ob.add(ctx.kv([['Lower Spec Limit', r.lsl], ['Target', r.target], ['Upper Spec Limit', r.usl], ['Mean', r.mean], ['N', r.n]].filter((x) => x[1] != null)));
    const rows = [];
    const label = { cp: 'Cp', cpk: 'Cpk', cpl: 'Cpl', cpu: 'Cpu', cpm: 'Cpm' };
    for (const key of ['cp', 'cpk', 'cpl', 'cpu', 'cpm']) {
      const w = r.sigma.within[key], ov = r.sigma.overall[key];
      if (w == null && ov == null) continue;
      const ciW = key === 'cpk' ? r.sigma.within.cpk_ci : key === 'cp' ? r.sigma.within.cp_ci : null;
      const ciO = key === 'cpk' ? r.sigma.overall.cpk_ci : key === 'cp' ? r.sigma.overall.cp_ci : null;
      rows.push({ index: label[key], within: w, wlo: ciW ? ciW[0] : null, whi: ciW ? ciW[1] : null, overall: ov, olo: ciO ? ciO[0] : null, ohi: ciO ? ciO[1] : null });
    }
    const lv = fmt(100 * (1 - ctx.alpha));
    ob.add(ctx.rt({ caption: 'Capability Indices', columns: [{ key: 'index', label: 'Index', fmt: 'text' }, { key: 'within', label: 'Within' }, { key: 'wlo', label: `Lower ${lv}%` }, { key: 'whi', label: `Upper ${lv}%` }, { key: 'overall', label: 'Overall' }, { key: 'olo', label: `Lower ${lv}%` }, { key: 'ohi', label: `Upper ${lv}%` }], rows }, { sortable: false }));
    ob.add(ctx.kv([['Sigma, within (moving range)', r.sigma.within.sigma], ['Sigma, overall', r.sigma.overall.sigma]]));
    const pct = (x) => (x == null ? null : 100 * x);
    ob.add(ctx.rt({ caption: 'Nonconformance', columns: [{ key: 'where', label: 'Portion', fmt: 'text' }, { key: 'obs', label: 'Observed %' }, { key: 'exw', label: 'Expected % (within)' }, { key: 'exo', label: 'Expected % (overall)' }], rows: [
      { where: 'Below LSL', obs: pct(r.observed.below), exw: pct(r.sigma.within.expected.below), exo: pct(r.sigma.overall.expected.below) },
      { where: 'Above USL', obs: pct(r.observed.above), exw: pct(r.sigma.within.expected.above), exo: pct(r.sigma.overall.expected.above) },
      { where: 'Total Outside', obs: pct(r.observed.total), exw: pct(r.sigma.within.expected.total), exo: pct(r.sigma.overall.expected.total) },
    ] }, { sortable: false }), ctx.note('Within sigma is the average moving range over d₂ = 1.128, in the order of the rows; overall sigma is the sample standard deviation. Expected fractions assume a normal distribution; the Cpk interval is Bissell\'s, the Cp interval χ².'));
  }

  /* Stem and leaf, in JS: the leaf unit is chosen for about 10 stems. */
  function stemLeaf(ctx, vals, name, parent) {
    const ob = ctx.outline('Stem and Leaf', { key: 'stem', parent });
    const n = vals.length;
    if (n < 2) { ob.add(ctx.note('Too few values.')); return ob.el; }
    const s = vals.slice().sort((a, b) => a - b);
    const range = s[n - 1] - s[0] || Math.abs(s[0]) || 1;
    const unit = 10 ** Math.floor(Math.log10(range / 10));   // the leaf unit
    const stems = new Map();
    for (const v of s) {
      const scaled = Math.round(v / unit);
      const stem = Math.floor(scaled / 10), leaf = Math.abs(scaled - stem * 10);
      if (!stems.has(stem)) stems.set(stem, []);
      stems.get(stem).push(leaf);
    }
    const keys = [...stems.keys()];
    const lo = Math.min(...keys), hi = Math.max(...keys);
    const lines = [];
    for (let k = hi; k >= lo; k--) {
      const leaves = stems.get(k) || [];
      lines.push(`${String(k).padStart(6)} | ${leaves.join('')}${leaves.length ? `   (${leaves.length})` : ''}`);
    }
    ob.add(el('pre', { class: 'sm-stem', text: lines.join('\n') }), ctx.note(`${name}: stem | leaf, leaf unit ${fmt(unit)}; for example ${String(Math.floor(Math.round(s[0] / unit) / 10))} | ${Math.abs(Math.round(s[0] / unit) % 10)} is ${fmt(Math.round(s[0] / unit) * unit)}.`));
    return ob.el;
  }

  /* ---- the red triangle of a continuous column --------------------------------- */
  function contMenu(ctx, col) {
    const sc = col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const ask = async (title, fields, key, map) => {
      const v = await SM.ui.form({ title: `${title}: ${col.name}`, fields });
      if (v) ctx.set(key, map ? map(v) : v, sc);
    };
    const m = ctx.opt('fits', [], sc);
    return [
      { label: 'Display Options', submenu: () => [
        ctx.check('Quantiles', 'quantiles', sc, true), ctx.check('Summary Statistics', 'summary', sc, true),
        { label: 'Customize Summary Statistics…', action: () => customizeStats(ctx, col) },
        ctx.check('Normality Tests', 'normality', sc, false),
        ctx.check('Horizontal Layout', 'horizontal', sc, false),
      ] },
      { label: 'Histogram Options', submenu: () => [
        ctx.check('Histogram', 'histogram', sc, true),
        { label: 'Set Bin Width…', action: () => ask('Set Bin Width', [{ key: 'w', label: 'Bin width (empty: automatic)', type: 'number', value: o('binWidth', null) }], 'binWidth', (v) => (v.w > 0 ? v.w : null)) },
        { label: 'Count Axis', checked: o('axis', 'count') === 'count', action: () => ctx.set('axis', 'count', sc) },
        { label: 'Prob Axis', checked: o('axis', 'count') === 'prob', action: () => ctx.set('axis', 'prob', sc) },
        { label: 'Density Axis', checked: o('axis', 'count') === 'density', action: () => ctx.set('axis', 'density', sc) },
        ctx.check('Show Counts', 'showCounts', sc, false), ctx.check('Show Percents', 'showPercents', sc, false),
      ] },
      ctx.check('Normal Quantile Plot', 'qq', sc, false),
      ctx.check('Outlier Box Plot', 'box', sc, true),
      ctx.check('Quantile Box Plot', 'qbox', sc, false),
      ctx.check('Stem and Leaf', 'stem', sc, false),
      ctx.check('CDF Plot', 'cdf', sc, false),
      { separator: true },
      { label: 'Test Mean…', action: () => ask('Test Mean', [{ key: 'mu', label: 'Specify hypothesized mean', type: 'number', value: 0 }, { key: 'sigma', label: 'True standard deviation, for a z test (optional)', type: 'number', value: null }], 'testMean') },
      { label: 'Test Std Dev…', action: () => ask('Test Std Dev', [{ key: 'sigma', label: 'Specify hypothesized standard deviation', type: 'number', value: 1 }], 'testSd') },
      { label: 'Test Equivalence…', action: () => ask('Test Equivalence', [{ key: 'low', label: 'Lower bound', type: 'number', value: null }, { key: 'upp', label: 'Upper bound', type: 'number', value: null }], 'equiv') },
      { label: 'Confidence Interval', submenu: () => [0.9, 0.95, 0.99].map((l) => ({ label: String(l), checked: o('ci', null) === l, action: () => ctx.set('ci', l, sc) })).concat([{ label: 'Other…', action: () => ask('Confidence Interval', [{ key: 'l', label: '1 − α', type: 'number', value: 0.95 }], 'ci', (v) => (v.l > 0 && v.l < 1 ? v.l : 0.95)) }]) },
      { label: 'Prediction Interval…', action: () => ask('Prediction Interval', [{ key: 'level', label: '1 − α', type: 'number', value: 0.95 }, { key: 'k', label: 'Number of future values', type: 'number', value: 1 }], 'pi') },
      { label: 'Tolerance Interval…', action: () => ask('Tolerance Interval', [{ key: 'level', label: 'Confidence, 1 − α', type: 'number', value: 0.95 }, { key: 'coverage', label: 'Proportion covered', type: 'number', value: 0.9 }], 'ti') },
      { label: 'Capability Analysis…', action: () => { const cur = o('cap', null) || col.specLimits || {}; ask('Capability Analysis', [{ key: 'lsl', label: 'Lower spec limit', type: 'number', value: cur.lsl ?? null }, { key: 'target', label: 'Target', type: 'number', value: cur.target ?? null }, { key: 'usl', label: 'Upper spec limit', type: 'number', value: cur.usl ?? null }], 'cap', (v) => (v.lsl == null && v.usl == null ? null : v)); } },
      { separator: true },
      { label: 'Continuous Fit', submenu: () => FITS.map(([k, label]) => ({ label, checked: m.includes(k), action: () => ctx.set('fits', m.includes(k) ? m.filter((x) => x !== k) : [...m, k], sc) })).concat([{ separator: true }, ctx.check('All (Compare Distributions)', 'fitAll', sc, false)]) },
      { label: 'Discrete Fit', submenu: () => DISCRETE.map(([k, label]) => ({ label, checked: m.includes(k), action: () => ctx.set('fits', m.includes(k) ? m.filter((x) => x !== k) : [...m, k], sc) })) },
      { separator: true },
      { label: 'Save', submenu: () => saveMenu(ctx, col) },
      { label: 'Remove', action: () => removeColumn(ctx, col) },
    ];
  }

  async function customizeStats(ctx, col) {
    const sc = col.id;
    const cur = ctx.opt('stats', ['mean', 'sd', 'se', 'upper', 'lower', 'n'], sc);
    const all = statRows({}, { quantiles: [] }, fmt(100 * (1 - ctx.alpha)), false);
    const v = await SM.ui.form({ title: `Customize Summary Statistics: ${col.name}`, fields: all.map(([k, label]) => ({ key: k, label, type: 'check', value: cur.includes(k) })) });
    if (v) ctx.set('stats', all.map((s) => s[0]).filter((k) => v[k]), sc);
  }

  function saveMenu(ctx, col) {
    const { vals, rows } = valuesOf(ctx, col);
    const n = vals.length;
    const mean = vals.reduce((a, b) => a + b, 0) / n;
    const sd = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1));
    const rk = () => ranks(vals);
    return [
      { label: 'Ranks', action: () => ctx.saveColumn(`Rank[${col.name}]`, { rows, values: (() => { const order = vals.map((_, k) => k).sort((a, b) => vals[a] - vals[b] || rows[a] - rows[b]); const r = new Array(n); order.forEach((k, i) => { r[k] = i + 1; }); return r; })() }) },
      { label: 'Ranks Averaged', action: () => ctx.saveColumn(`Rank Avgd[${col.name}]`, { rows, values: rk() }) },
      { label: 'Prob Scores', action: () => ctx.saveColumn(`Prob[${col.name}]`, { rows, values: rk().map((r) => r / (n + 1)) }) },
      { label: 'Normal Quantiles', action: () => ctx.saveColumn(`N-Quantile[${col.name}]`, { rows, values: rk().map((r) => qnorm(r / (n + 1))) }) },
      { label: 'Standardized', action: () => ctx.saveColumn(`Std[${col.name}]`, { rows, values: vals.map((v) => (v - mean) / sd) }) },
      { label: 'Centered', action: () => ctx.saveColumn(`Centered[${col.name}]`, { rows, values: vals.map((v) => v - mean) }) },
      { label: 'Level Midpoints', action: () => { const b = SM.report.niceBins(vals); ctx.saveColumn(`Midpoint[${col.name}]`, { rows, values: vals.map((v) => b.start + (Math.min(Math.floor((v - b.start) / b.size), Math.round((b.end - b.start) / b.size) - 1) + 0.5) * b.size) }); } },
    ];
  }

  function removeColumn(ctx, col) {
    const ids = (ctx.spec.roles.y || []).filter((id) => id !== col.id);
    if (!ids.length) { ctx.report.app.closeReport(ctx.report); return; }
    ctx.spec.roles.y = ids;
    ctx.report.run();
  }

  /* ---- ordinal and nominal ------------------------------------------------------ */
  async function categorical(ctx, col, parent, shared) {
    const sc = col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const outline = ctx.outline(col.name, { parent, menu: () => catMenu(ctx, col), key: `col:${col.id}` });
    const ciLevel = o('ciCat', null);
    const res = await ctx.call('distribution.categorical', { column: col.name, weight: ctx.name('weight'), freq: ctx.name('freq'), alpha: ciLevel ? 1 - ciLevel : ctx.alpha });
    const t = ctx.table;
    const levels = res.levels.slice();
    const order = o('order', null);
    if (order === 'desc') levels.sort((a, b) => b.count - a.count);
    else if (order === 'asc') levels.sort((a, b) => a.count - b.count);
    const key = (v) => (typeof v === 'number' ? v : String(v));
    const members = new Map(levels.map((l) => [key(l.level), []]));
    for (const r of ctx.rows) { const v = col.values[r]; if (!isMissing(v) && members.has(key(v))) members.get(key(v)).push(r); }
    const labels = levels.map((l) => SM.grid.cellText(col, l.level));
    const horizontal = o('horizontal', !!shared.stack);
    const prob = o('axis', 'count') === 'prob';
    const total = res.n;
    const heights = levels.map((l) => (prob ? l.prob : l.count));
    const txt = o('showCounts', false) || o('showPercents', false) ? levels.map((l) => [o('showCounts', false) ? fmt(l.count) : '', o('showPercents', false) ? `${(100 * l.prob).toFixed(1)}%` : ''].filter(Boolean).join(' ')) : undefined;
    const bar = { type: 'bar', orientation: horizontal ? 'v' : 'h', rows: levels.map((l) => members.get(key(l.level))), rowsScale: prob ? 1 / total : 1, marker: { color: SM.report.BAR }, text: txt, textposition: txt ? 'outside' : undefined, cliponaxis: false, hovertemplate: `%{${horizontal ? 'x' : 'y'}}: %{${horizontal ? 'y' : 'x'}}<extra></extra>`, name: col.name };
    if (horizontal) { bar.x = labels; bar.y = heights; } else { bar.y = labels; bar.x = heights; }
    const cat = { type: 'category', categoryorder: 'array', categoryarray: labels, title: { text: col.name } };
    const num = { title: { text: prob ? 'Probability' : 'Count' }, rangemode: 'tozero' };
    const h = Math.max(200, Math.min(520, 60 + 26 * labels.length));
    const graph = ctx.plot([bar], horizontal ? { xaxis: cat, yaxis: num, bargap: 0.15 } : { yaxis: { ...cat, autorange: 'reversed' }, xaxis: num, bargap: 0.15 }, { width: horizontal ? Math.max(320, Math.min(760, 80 + 40 * labels.length)) : 330, height: horizontal ? 280 : h, title: `${col.name} bar chart`, select: false });
    if (shared.histOnly) { outline.add(graph); return; }
    const freq = ctx.outline('Frequencies', { parent: outline, key: 'freq', closed: !o('frequencies', true) });
    const cols = [{ key: 'label', label: 'Level', fmt: 'text' }, { key: 'count', label: 'Count' }, { key: 'prob', label: 'Prob' }];
    if (o('stderr', false)) cols.push({ key: 'se', label: 'StdErr Prob' });
    cols.push({ key: 'cum', label: 'Cum Prob' });
    let cum = 0;
    const rowsF = levels.map((l, i) => { cum += l.prob; return { label: labels[i], count: l.count, prob: l.prob, se: l.se, cum }; });
    freq.add(ctx.rt({ columns: cols, rows: [...rowsF, { label: 'Total', count: total, prob: 1, se: null, cum: null }] }, { sortable: false }),
      ctx.kv([['N Missing', res.n_missing, 'int'], [`${res.n_levels} Levels`, '', 'text']]), ctx.code(res.code));
    outline.add(horizontal ? [graph, freq.el] : ctx.row(graph, freq.el));
    if (ciLevel) {
      const ob = ctx.outline('Confidence Intervals', { parent: outline, key: 'cicat', menu: () => [{ label: 'Remove', action: () => ctx.set('ciCat', null, sc) }] });
      ob.add(ctx.rt({ columns: [{ key: 'label', label: 'Level', fmt: 'text' }, { key: 'count', label: 'Count' }, { key: 'prob', label: 'Prob' }, { key: 'lower', label: 'Lower CI' }, { key: 'upper', label: 'Upper CI' }, { key: 'lv', label: '1−Alpha' }], rows: levels.map((l, i) => ({ ...l, label: labels[i], lv: ciLevel })) }),
        ctx.note('Score (Wilson) confidence intervals, from statsmodels\' proportion_confint.'));
    }
    if (o('mosaic', false)) {
      const ob = ctx.outline('Mosaic Plot', { parent: outline, key: 'mosaic' });
      const traces = levels.map((l, i) => ({ type: 'bar', x: [''], y: [l.prob], name: labels[i], rows: [members.get(key(l.level))], rowsScale: 1 / total, marker: { color: SM.util.PALETTE[i % SM.util.PALETTE.length] }, hovertemplate: `${labels[i]}: %{y:.3f}<extra></extra>` }));
      ob.add(ctx.plot(traces, { barmode: 'stack', showlegend: true, yaxis: { range: [0, 1], title: { text: 'Probability' } }, xaxis: { showticklabels: false } }, { width: 240, height: 300, title: `${col.name} mosaic`, select: false }));
    }
    const tp = o('testProbs', null);
    if (tp) {
      const r = await ctx.call('distribution.test_probs', { column: col.name, probs: tp, weight: ctx.name('weight'), freq: ctx.name('freq') });
      const ob = ctx.outline('Test Probabilities', { parent: outline, key: 'testprobs', menu: () => [{ label: 'Remove', action: () => ctx.set('testProbs', null, sc) }] });
      if (r.error) ob.add(ctx.warn(r.error));
      else {
        ob.add(ctx.rt({ columns: [{ key: 'level', label: 'Level', fmt: 'text' }, { key: 'observed', label: 'Estim Prob' }, { key: 'hypothesized', label: 'Hypoth Prob' }], rows: r.levels.map((l) => ({ ...l, level: SM.grid.cellText(col, l.level) })) }),
          ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'stat', label: 'ChiSquare' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'p', label: 'Prob>Chisq', fmt: 'p' }], rows: r.tests }));
        if (r.min_expected < 5) ob.add(ctx.warn(`The smallest expected count is ${fmt(r.min_expected)}; with counts below 5 the χ² p-values are approximate.`));
      }
    }
  }

  function catMenu(ctx, col) {
    const sc = col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    return [
      { label: 'Display Options', submenu: () => [ctx.check('Frequencies', 'frequencies', sc, true), ctx.check('Std Err Prob', 'stderr', sc, false), ctx.check('Horizontal Layout', 'horizontal', sc, false)] },
      { label: 'Histogram Options', submenu: () => [
        { label: 'Count Axis', checked: o('axis', 'count') === 'count', action: () => ctx.set('axis', 'count', sc) },
        { label: 'Prob Axis', checked: o('axis', 'count') === 'prob', action: () => ctx.set('axis', 'prob', sc) },
        ctx.check('Show Counts', 'showCounts', sc, false), ctx.check('Show Percents', 'showPercents', sc, false),
      ] },
      ctx.check('Mosaic Plot', 'mosaic', sc, false),
      { label: 'Order By', submenu: () => [[null, 'Original (value order)'], ['desc', 'Count Descending'], ['asc', 'Count Ascending']].map(([v, l]) => ({ label: l, checked: o('order', null) === v, action: () => ctx.set('order', v, sc) })) },
      { label: 'Test Probabilities…', action: () => testProbsDialog(ctx, col) },
      { label: 'Confidence Interval', submenu: () => [0.9, 0.95, 0.99].map((l) => ({ label: String(l), checked: o('ciCat', null) === l, action: () => ctx.set('ciCat', l, sc) })) },
      { separator: true },
      { label: 'Save', submenu: () => [{ label: 'Level Numbers', action: () => {
        const lv = ctx.table.levels(col);
        const m = new Map(lv.map((v, i) => [v, i + 1]));
        const rows = ctx.rows.filter((r) => !isMissing(col.values[r]));
        ctx.saveColumn(`Level[${col.name}]`, { rows, values: rows.map((r) => m.get(col.values[r])) }, { modelingType: 'ordinal' });
      } }] },
      { label: 'Remove', action: () => removeColumn(ctx, col) },
    ];
  }

  async function testProbsDialog(ctx, col) {
    const lv = ctx.table.levels(col);
    if (lv.length > 40) { SM.ui.toast('Test Probabilities takes at most 40 levels'); return; }
    const cur = ctx.opt('testProbs', null, col.id) || {};
    const v = await SM.ui.form({
      title: `Test Probabilities: ${col.name}`, lead: 'The hypothesized probability of each level; they are scaled to sum to one. Leave all equal for a test of a uniform distribution.',
      fields: lv.map((l, i) => ({ key: `p${i}`, label: SM.grid.cellText(col, l), type: 'number', value: cur[String(l)] ?? +(1 / lv.length).toFixed(6) })),
    });
    if (!v) return;
    const probs = {};
    lv.forEach((l, i) => { probs[String(l)] = v[`p${i}`] ?? 0; });
    ctx.set('testProbs', probs, col.id);
  }

  /* ---- the platform ------------------------------------------------------------------ */
  SM.platforms.register({
    id: 'distribution', label: 'Distribution', menu: 'Analyze', order: 10, info: 'p:distribution',
    about: 'Describes one column at a time: histogram, box plot, quantiles and moments for continuous columns; bar chart and frequencies for ordinal and nominal ones; tests, intervals, capability and fitted distributions from the red triangles.',
    uses: ['statsmodels.stats.weightstats.DescrStatsW', 'statsmodels.stats.diagnostic.normal_ad, lilliefors', 'statsmodels.stats.stattools.jarque_bera', 'statsmodels.base.model.GenericLikelihoodModel', 'statsmodels.stats.proportion.proportion_confint', 'statsmodels.robust.scale.Huber', 'scipy.stats'],
    launch: {
      lead: 'Choose the columns to describe. Continuous columns get a histogram, a box plot, quantiles and moments; ordinal and nominal columns a bar chart and frequencies.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 1, hint: 'required: one or more' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric' },
        { key: 'by', label: 'By', hint: 'optional' },
      ],
      options: [{ key: 'histOnly', label: 'Histograms Only', type: 'check', value: false }],
    },
    title: (spec) => ((spec.roles.y || []).length === 1 ? 'Distribution' : 'Distributions'),
    triangle(ctx) {
      return [
        ctx.check('Uniform Scaling', 'uniform', null, false),
        ctx.check('Stack', 'stack', null, false),
        ctx.check('Histograms Only', 'histOnly', null, false),
        { label: 'Arrange in Rows…', action: async () => { const v = await SM.ui.form({ title: 'Arrange in Rows', fields: [{ key: 'n', label: 'Plots per row (0: as many as fit)', type: 'number', value: ctx.opt('perRow', 0) }] }); if (v) ctx.set('perRow', Math.max(0, Math.round(v.n || 0))); } },
        { separator: true },
        { label: 'Normal Quantile Plots for All', action: () => ctx.set('qq', !ctx.opt('qq', false)) },
        { label: 'Normality Tests for All', action: () => ctx.set('normality', !ctx.opt('normality', false)) },
      ];
    },
    async render(ctx) {
      const cols = ctx.roles('y');
      const shared = { stack: ctx.opt('stack', false), histOnly: ctx.opt('histOnly', false) };
      if (ctx.opt('uniform', false)) {
        let lo = Infinity, hi = -Infinity;
        for (const c of cols) if (!c.isCategorical) for (const r of ctx.rows) { const v = c.values[r]; if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } }
        if (lo < hi) shared.uniform = [lo, hi];
      }
      const per = ctx.opt('perRow', 0);
      const wrap = el('div', { class: `sm-dist-wrap${shared.stack ? ' is-stacked' : ''}` });
      if (per > 0) wrap.style.setProperty('--per-row', String(per));
      ctx.container.append(wrap);
      for (const c of cols) {
        if (c.isCategorical) await categorical(ctx, c, wrap, shared);
        else await continuous(ctx, c, wrap, shared);
      }
    },
  });
}(typeof self !== 'undefined' ? self : this));
