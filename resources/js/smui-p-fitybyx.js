/* ==========================================================================
   SMUI.HTML: ANALYZE > FIT Y BY X, SPECIALIZED MODELING > MATCHED PAIRS

   Fit Y by X looks at each Y against each X; the modeling types choose the
   analysis, as in JMP:

     Y continuous,  X continuous    Bivariate    scatterplot and fits
     Y continuous,  X categorical   Oneway       points by level, ANOVA,
                                                 comparisons, rank tests
     Y categorical, X continuous    Logistic     logistic probability plot
     Y categorical, X categorical   Contingency  mosaic plot and crosstab

   Each pair has its red triangle; each fit of a Bivariate has its own.
   The options are stored per pair (scope y~x), so Redo, By and projects
   keep them. The numbers are resources/py/smui/fit_y_by_x.py's.

   Matched Pairs compares two paired responses: the Tukey mean-difference
   plot, the paired t test, Wilcoxon signed rank and the sign test; binary
   responses (two values in all) get Cochran's Q and McNemar's tests.

   Beyond JMP, from statsmodels: Brunner-Munzel and its equivalence test
   (Oneway ▸ Nonparametric), Compare Rates for counts with an exposure,
   the Two Sample Test for Proportions by every method statsmodels has
   (Contingency), and Breslow-Day beside Cochran Mantel Haenszel. From the
   published methods: Effect Size (d, g, η², ε², ω², d_z, d_av with exact
   or Bonett intervals), Bayes Factor (JZS t tests, the correlation's) and
   Games-Howell comparisons.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt, qnorm, PALETTE } = SM.util;
  const { isMissing } = SM.table;

  const FIT_COLORS = ['#b0413e', '#3a7d44', '#6c5b7b', '#c0a000', '#1f9e89', '#8c564b', '#d9822b', '#17becf', '#7f7f7f', '#e377c2'];
  const DASHES = ['solid', 'dash', 'dot', 'dashdot', 'longdash'];
  const TITLE = { bivariate: 'Bivariate Fit', oneway: 'Oneway Analysis', logistic: 'Logistic Fit', contingency: 'Contingency Analysis' };
  const GREEN = '#3a7d44', RED = '#b0413e', PURPLE = '#6c5b7b', GREY = '#8a8a8a';

  const kindOf = (y, x) => (y.isCategorical ? (x.isCategorical ? 'contingency' : 'logistic') : (x.isCategorical ? 'oneway' : 'bivariate'));
  const pairTitle = (kind, y, x) => `${TITLE[kind]} of ${y.name} By ${x.name}`;
  const scopeOf = (y, x) => `${y.id}~${x.id}`;
  const lvText = (col, v) => (col ? SM.grid.cellText(col, v) : String(v));
  const keyOf = (v) => (typeof v === 'number' ? v : String(v));
  const lvPct = (v) => (v == null || !Number.isFinite(v) ? '.' : v.toFixed(2));

  /* A stable pseudo-random number in [0, 1) for a row: the jitter of a point
     does not move when the report is redrawn. */
  function jit(r, salt = 0) {
    let h = Math.imul((r + 1) ^ Math.imul(salt + 1, 0x9e3779b1), 0x85ebca6b) >>> 0;
    h = (h ^ (h >>> 13)) >>> 0; h = Math.imul(h, 0xc2b2ae35) >>> 0; h = (h ^ (h >>> 16)) >>> 0;
    return (h % 1000003) / 1000003;
  }

  function rgba(hex, a) {
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
    return m ? `rgba(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)}, ${a})` : hex;
  }

  function pairsOf(spec, table) {
    if (!table) return [];
    const ys = ((spec.roles && spec.roles.y) || []).map((id) => table.col(id)).filter(Boolean);
    const xs = ((spec.roles && spec.roles.x) || []).map((id) => table.col(id)).filter(Boolean);
    const out = [];
    for (const y of ys) for (const x of xs) if (y.id !== x.id) out.push([y, x]);
    return out;
  }

  function basePayload(ctx, y, x) {
    return { y: y.name, x: x.name, weight: ctx.name('weight'), freq: ctx.name('freq'), alpha: ctx.alpha, where: ctx.where || [] };
  }

  /* The rows of the report with both values, a positive weight and
     frequency, and no missing value in the extra columns. */
  function pointsOf(ctx, y, x, extra = []) {
    const w = ctx.role('weight'), f = ctx.role('freq');
    const rows = [], xv = [], yv = [], wv = [];
    for (const r of ctx.rows) {
      const a = y.values[r], b = x.values[r];
      if (isMissing(a) || isMissing(b)) continue;
      if (!y.isCategorical && !Number.isFinite(a)) continue;
      if (!x.isCategorical && !Number.isFinite(b)) continue;
      if (extra.some((c) => isMissing(c.values[r]))) continue;
      let wt = 1;
      if (w) wt *= w.values[r];
      if (f) wt *= f.values[r];
      if (!(wt > 0) || !Number.isFinite(wt)) continue;
      rows.push(r); yv.push(a); xv.push(b); wv.push(wt);
    }
    return { rows, xv, yv, wv };
  }

  function availWidth(ctx, want) {
    const w = (ctx.report && ctx.report.body && ctx.report.body.clientWidth) || 0;
    return w > 240 ? Math.max(260, Math.min(want, w - 60)) : want;
  }

  /* How many rows a horizontal legend of these names takes at this width
     (verdana 10.5px is about 6.4px a character, plus the line sample). */
  function legendRows(names, width) {
    let rows = names.length ? 1 : 0, used = 0;
    for (const nm of names) {
      const w = 46 + 6.4 * String(nm).length;
      if (used > 0 && used + w > width - 24) { rows++; used = 0; }
      used += w;
    }
    return rows;
  }

  const notesOf = (ctx, arr) => (arr || []).map((t) => ctx.note(t));
  const kvOf = (ctx, t) => ctx.kv(t.rows.map((r) => [r.stat, r.value]));
  const rtFixed = (ctx, t, opts = {}) => ctx.rt(t, { sortable: false, ...opts });

  function equation(yname, terms) {
    if (!terms || !terms.length) return '';
    let s = `${yname} = ${fmt(terms[0].estimate)}`;
    for (const t of terms.slice(1)) s += `${t.estimate < 0 ? ' − ' : ' + '}${fmt(Math.abs(t.estimate))}*${t.term}`;
    return s;
  }

  async function safeCall(ctx, fn, payload) {
    try {
      const r = await ctx.call(fn, payload);
      return r && r.error ? { error: r.error, res: r } : { res: r };
    } catch (e) { return { error: e }; }
  }

  function problem(ctx, err) {
    return typeof err === 'string' ? ctx.warn(err) : ctx.error(err);
  }

  async function ask(title, fields, lead) {
    return SM.ui.form({ title, fields, lead });
  }

  function alphaMenu(ctx) {
    const cur = ctx.alpha;
    return [0.01, 0.05, 0.1].map((a) => ({ label: String(a), checked: Math.abs(cur - a) < 1e-12, action: () => ctx.set('alpha', a) })).concat([{
      label: 'Other…', action: async () => { const v = await ask('Set α Level', [{ key: 'a', label: 'α', type: 'number', value: cur }]); if (v && v.a > 0 && v.a < 1) ctx.set('alpha', v.a); },
    }]);
  }

  /* A report table whose positive numbers are marked (threshold matrices). */
  function markPositive(tbl) {
    tbl.querySelectorAll('tbody tr').forEach((tr) => tr.querySelectorAll('td').forEach((td, j) => {
      if (j === 0) return;
      const v = SM.table.toNumber(td.textContent.replace('−', '-'));
      if (v > 0) td.classList.add('p-sig');
    }));
    return tbl;
  }

  /* ---- effect sizes and Bayes factors, opt-in (not in JMP) ------------------
     Effect Size outlines: a standardized effect with its interval, exact from
     the noncentral t or F where it exists. Bayes Factor outlines: BF10 and
     BF01 for the two-sided and each one-sided alternative. */
  async function effectOutline(ctx, parent, key, fn, payload, note, remove) {
    const ob = ctx.outline('Effect Size', { parent, key, info: 'p:fitybyx:effect', menu: remove ? () => [{ label: 'Remove', action: remove }] : null });
    const { res: r, error } = await safeCall(ctx, fn, payload);
    if (error) { ob.add(problem(ctx, error)); return ob; }
    ob.add(ctx.rt(r.table, { sortable: false }), note ? ctx.note(note(r)) : null, notesOf(ctx, r.notes), ctx.code(r.code));
    return ob;
  }

  async function bayesOutline(ctx, parent, key, fn, payload, facts, note, menu) {
    const ob = ctx.outline('Bayes Factor', { parent, key, info: 'p:fitybyx:bayes', menu });
    const { res: r, error } = await safeCall(ctx, fn, payload);
    if (error) { ob.add(problem(ctx, error)); return ob; }
    ob.add(ctx.row(ctx.rt(r.table, { sortable: false }), ctx.kv(facts(r))), ctx.note(note(r)), notesOf(ctx, r.notes), ctx.code(r.code));
    return ob;
  }

  const BF_NOTE = 'BF10 is how many times more likely the data are under the alternative than under the null hypothesis; BF01 = 1/BF10 the other way round. Right click for log₁₀ BF10.';
  const JZS_R = Math.SQRT1_2;

  /* The scale r of the Cauchy prior on the standardized effect (Rouder et al. 2009). */
  async function priorDialog(ctx, sc, key, title) {
    const cur = ctx.opt(key, null, sc) || { r: JZS_R };
    const v = await SM.ui.form({
      title, info: 'p:fitybyx:bayes',
      lead: 'Under the alternative the standardized effect δ has a Cauchy prior centred at 0; its scale r is the effect size that is as likely to be exceeded as not. √2/2 ≈ 0.707 is the default of Rouder et al. (2009) and JASP; 1 is the original JZS prior, 0.5 expects smaller effects.',
      fields: [{ key: 'r', label: 'Scale r of the Cauchy prior on δ', type: 'number', value: cur.r }],
      validate: (x) => (x.r > 0 ? null : 'The scale must be positive.'),
    });
    if (v) ctx.set(key, { r: v.r }, sc);
  }

  /* The width κ of the stretched beta prior on ρ (Ly et al. 2016). */
  async function kappaDialog(ctx, sc) {
    const cur = ctx.opt('corrBf', null, sc) || { kappa: 1 };
    const v = await SM.ui.form({
      title: 'Bayes Factor for the Correlation', info: 'p:fitybyx:bayes',
      lead: 'Under the alternative the correlation ρ has a beta(1/κ, 1/κ) prior stretched to (−1, 1): κ = 1 is uniform (the default of Ly, Verhagen and Wagenmakers 2016 and JASP); a smaller κ expects correlations nearer 0.',
      fields: [{ key: 'kappa', label: 'Width κ of the prior on ρ', type: 'number', value: cur.kappa }],
      validate: (x) => (x.kappa > 0 ? null : 'κ must be positive.'),
    });
    if (v) ctx.set('corrBf', { kappa: v.kappa }, sc);
  }

  /* ======================================================================
     BIVARIATE
     ====================================================================== */
  const FIT_FN = {
    mean: 'fitybyx.fit_mean', line: 'fitybyx.fit_poly', poly: 'fitybyx.fit_poly', special: 'fitybyx.fit_special', spline: 'fitybyx.fit_spline',
    lowess: 'fitybyx.fit_lowess', each: 'fitybyx.fit_each', robust: 'fitybyx.fit_robust', orth: 'fitybyx.fit_orthogonal',
    ellipse: 'fitybyx.density_ellipse', kde: 'fitybyx.nonpar_density', quantile: 'fitybyx.fit_quantile',
  };
  const HAS_CI = new Set(['line', 'poly', 'special']);
  const HAS_ROWS = new Set(['mean', 'line', 'poly', 'special', 'spline', 'lowess', 'each', 'robust', 'quantile']);
  const TR_LABEL = { none: 'No Transformation', log: 'Natural Logarithm: log(y)', sqrt: 'Square Root: sqrt(y)', square: 'Square: y²', reciprocal: 'Reciprocal: 1/y', exp: 'Exponential: exp(y)' };
  const TR_TITLE = { log: 'Log', sqrt: 'Sqrt', square: 'Square', reciprocal: 'Recip', exp: 'Exp' };

  function fitArgs(f) {
    switch (f.kind) {
      case 'line': return { degree: 1 };
      case 'poly': return { degree: f.degree };
      case 'special': return { ytr: f.ytr || 'none', xtr: f.xtr || 'none', degree: f.degree || 1, intercept: f.intercept ?? null, slope: f.slope ?? null };
      case 'spline': return { lam: f.lam ?? null, standardize: !!f.standardize };
      case 'lowess': return { frac: f.frac ?? 0.667, it: f.it ?? 0 };
      case 'robust': return { method: f.method || 'huber' };
      case 'orth': return { mode: f.mode || 'univariate', ratio: f.ratio ?? null };
      case 'ellipse': return { levels: [f.p] };
      case 'quantile': return { tau: f.tau };
      default: return {};
    }
  }

  function specialTitle(f) {
    const yt = f.ytr || 'none', xt = f.xtr || 'none';
    if (yt === 'none' && xt === 'none') return f.intercept != null || f.slope != null ? 'Constrained Fit' : (f.degree > 1 ? `Polynomial Fit Degree=${f.degree}` : 'Linear Fit');
    return `Transformed Fit${yt !== 'none' ? ` ${TR_TITLE[yt]}` : ''}${xt !== 'none' ? ` to ${TR_TITLE[xt]}` : ''}`;
  }

  function fitTitle(f, res) {
    switch (f.kind) {
      case 'mean': return 'Fit Mean';
      case 'line': return 'Linear Fit';
      case 'poly': return `Polynomial Fit Degree=${f.degree}`;
      case 'special': return (res && res.title) || specialTitle(f);
      case 'spline': return f.lam == null ? 'Smoothing Spline Fit, lambda by GCV' : `Smoothing Spline Fit, lambda=${fmt(f.lam)}`;
      case 'lowess': return 'Local Smoother';
      case 'each': return 'Fit Each Value';
      case 'robust': return f.method === 'bisquare' ? 'Robust Fit (Bisquare)' : 'Robust Fit';
      case 'orth': return `Orthogonal Fit Ratio=${res && res.ratio != null ? res.ratio.toFixed(3) : { equal: '1.000', x_to_y: '0.000' }[f.mode] || (f.ratio != null ? Number(f.ratio).toFixed(3) : '…')}`;
      case 'ellipse': return `Bivariate Normal Ellipse P=${Number(f.p).toFixed(3)}`;
      case 'kde': return 'Quantile Density Contours';
      case 'quantile': return `Quantile Fit, τ=${fmt(f.tau)}`;
      default: return f.kind;
    }
  }

  function addFit(ctx, sc, fit) {
    const fits = ctx.opt('fits', [], sc);
    const next = 1 + Math.max(0, ...fits.map((f) => Number(String(f.id).slice(1)) || 0));
    ctx.set('fits', [...fits, { id: `f${next}`, ...fit }], sc);
  }

  function groupsOf(ctx, P, gcol, base) {
    if (!gcol) return [{ label: null, rows: null, where: base.where, color: null }];
    const lv = ctx.table.levels(gcol);
    const map = new Map(lv.map((v, i) => [keyOf(v), i]));
    const buckets = lv.map(() => []);
    P.rows.forEach((r) => { const v = gcol.values[r]; if (isMissing(v)) return; const i = map.get(keyOf(v)); if (i != null) buckets[i].push(r); });
    return lv.map((v, i) => ({ label: `${gcol.name}==${lvText(gcol, v)}`, rows: buckets[i], where: [...base.where, { column: gcol.name, value: v }], color: PALETTE[i % PALETTE.length] }))
      .filter((g) => g.rows.length >= 2);
  }

  function histBars(vals, rows, wts, horizontal, axes) {
    const b = SM.report.niceBins(vals);
    const nb = Math.max(1, Math.round((b.end - b.start) / b.size));
    const counts = new Array(nb).fill(0), members = Array.from({ length: nb }, () => []);
    vals.forEach((v, k) => { const j = Math.min(nb - 1, Math.max(0, Math.floor((v - b.start) / b.size + 1e-9))); counts[j] += wts[k]; members[j].push(rows[k]); });
    const centers = counts.map((_, j) => b.start + (j + 0.5) * b.size);
    const t = { type: 'bar', width: b.size, rows: members, marker: { color: SM.report.BAR, line: { color: SM.util.themeColors().surface, width: 0.6 } }, hoverinfo: 'skip', showlegend: false, ...axes };
    if (horizontal) { t.orientation = 'h'; t.y = centers; t.x = counts; } else { t.x = centers; t.y = counts; }
    return t;
  }

  async function bivariate(ctx, y, x, host, sc) {
    const o = (k, d) => ctx.opt(k, d, sc);
    const P = pointsOf(ctx, y, x);
    if (P.rows.length < 2) { host.add(ctx.warn(`${y.name} by ${x.name}: fewer than two rows with both values.`)); return; }
    const base = basePayload(ctx, y, x);
    const fits = o('fits', []);
    const gcol = o('groupBy', null) ? ctx.col(o('groupBy', null)) : null;
    const groups = groupsOf(ctx, P, gcol, base);
    const results = [];
    for (const f of fits) {
      for (const g of groups) {
        const payload = { ...base, ...fitArgs(f), where: g.where, alpha: f.alpha || ctx.alpha };
        if (g.rows) payload.rows = g.rows;
        const r = await safeCall(ctx, FIT_FN[f.kind], payload);
        results.push({ f, g, res: r.res, error: r.error, payload });
      }
    }
    // ---- the scatterplot
    const traces = [];
    const n = P.rows.length;
    if (o('points', true)) traces.push({ type: n > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: P.xv, y: P.yv, rows: P.rows, marker: { size: n > 3000 ? 4 : 6 }, name: 'Points', showlegend: false });
    const legendNames = [];
    results.forEach(({ f, g, res, error }) => {
      if (error || !res) return;
      const fi = fits.indexOf(f);
      const color = g.color || FIT_COLORS[fi % FIT_COLORS.length];
      const dash = gcol ? DASHES[fi % DASHES.length] : 'solid';
      const name = `${fitTitle(f, res)}${g.label ? ` ${g.label}` : ''}`;
      if (f.line === false) return;
      if (f.kind === 'ellipse') {
        for (const e of res.ellipses || []) traces.push({ type: 'scatter', mode: 'lines', x: e.x, y: e.y, line: { color, width: 1.6, dash }, name, hoverinfo: 'name', showlegend: true });
        legendNames.push(name);
        return;
      }
      if (f.kind === 'kde') {
        (res.levels || []).forEach((lv, i) => traces.push({
          type: 'contour', x: res.x, y: res.y, z: res.z, autocontour: false, contours: { start: lv.value, end: lv.value, size: 1, coloring: 'none' },
          line: { color, width: lv.q === 0.5 ? 1.8 : 0.9 }, showscale: false, hoverinfo: 'skip', name: i === 0 ? name : `${name} ${lv.q}`, showlegend: i === 0,
        }));
        legendNames.push(name);
        return;
      }
      const c = res.curve;
      if (!c) return;
      const shade = (lo, hi, a) => ({ type: 'scatter', mode: 'lines', x: [...c.x, ...c.x.slice().reverse()], y: [...lo, ...hi.slice().reverse()], fill: 'toself', fillcolor: rgba(color, a), line: { width: 0 }, hoverinfo: 'skip', showlegend: false });
      if (f.sind && c.lo_ind) traces.push(shade(c.lo_ind, c.hi_ind, 0.1));
      if (f.sfit && c.lo_fit) traces.push(shade(c.lo_fit, c.hi_fit, 0.2));
      traces.push({ type: 'scatter', mode: f.kind === 'each' ? 'lines+markers' : 'lines', x: c.x, y: c.fit, line: { color, width: 2, dash }, marker: { size: 4, color }, name, hovertemplate: `${name}<br>%{x}, %{y}<extra></extra>`, showlegend: true });
      legendNames.push(name);
      for (const [key, lo, hi, d] of [['cfit', 'lo_fit', 'hi_fit', 'dash'], ['cind', 'lo_ind', 'hi_ind', 'dot']]) {
        if (!f[key] || !c[lo]) continue;
        traces.push({ type: 'scatter', mode: 'lines', x: c.x, y: c[lo], line: { color, width: 1, dash: d }, hoverinfo: 'skip', showlegend: false });
        traces.push({ type: 'scatter', mode: 'lines', x: c.x, y: c[hi], line: { color, width: 1, dash: d }, hoverinfo: 'skip', showlegend: false });
      }
    });
    const hist = o('hist', false);
    const width = availWidth(ctx, 560);
    const lrows = legendRows(legendNames, width);
    const layout = {
      xaxis: { title: { text: x.name }, zeroline: false }, yaxis: { title: { text: y.name }, zeroline: false },
      showlegend: lrows > 0, legend: { orientation: 'h', x: 0, xanchor: 'left', yref: 'container', y: 0, yanchor: 'bottom' },
      margin: { l: 60, r: 14, t: 10, b: 48 + 20 * lrows },
    };
    if (hist) {
      layout.xaxis.domain = [0, 0.82];
      layout.yaxis.domain = [0, 0.82];
      layout.yaxis2 = { domain: [0.85, 1], anchor: 'x', showticklabels: false, showgrid: false, zeroline: false, showline: false, ticks: '', rangemode: 'tozero' };
      layout.xaxis2 = { domain: [0.85, 1], anchor: 'y', showticklabels: false, showgrid: false, zeroline: false, showline: false, ticks: '', rangemode: 'tozero' };
      traces.push(histBars(P.xv, P.rows, P.wv, false, { xaxis: 'x', yaxis: 'y2' }), histBars(P.yv, P.rows, P.wv, true, { xaxis: 'x2', yaxis: 'y' }));
    }
    const height = 400 + 20 * lrows;
    host.add(ctx.plot(traces, layout, { width, height, title: `${y.name} by ${x.name}` }));
    if (!o('points', true) && !fits.length) host.add(ctx.note('Show Points is off and there are no fits: choose a fit from the red triangle.'));
    if (o('summary', false)) {
      const ob = ctx.outline('Summary Statistics', { parent: host, key: `sum:${sc}` });
      const { res, error } = await safeCall(ctx, 'fitybyx.bivariate', base);
      if (error) ob.add(problem(ctx, error));
      else ob.add(ctx.kv([[`Mean of ${x.name}`, res.mean_x], [`Mean of ${y.name}`, res.mean_y], [`Std Dev of ${x.name}`, res.sd_x], [`Std Dev of ${y.name}`, res.sd_y],
        ['Correlation', res.r], ['Covariance', res.cov], ['N', res.n]]), ctx.code(res.code));
    }
    const cbf = o('corrBf', null);
    if (cbf) {
      await bayesOutline(ctx, host, `cbf:${sc}`, 'fitybyx.bivariate_bf', { ...base, kappa: cbf.kappa },
        (r) => [['Correlation r', r.r], ['N', r.n], ['Prior width κ', r.kappa]],
        (r) => `Whether ${y.name} and ${x.name} are correlated: the exact likelihood of ρ given r = ${fmt(r.r)} from ${fmt(r.n)} pairs, against a beta(1/κ, 1/κ) prior on ρ stretched to (−1, 1)${r.kappa === 1 ? ', uniform' : ''} (Ly, Verhagen and Wagenmakers 2016); a one-sided alternative keeps the prior's half on its side, doubled. ${BF_NOTE}`,
        () => [{ label: 'Change Prior…', action: () => kappaDialog(ctx, sc) }, { label: 'Remove', action: () => ctx.set('corrBf', null, sc) }]);
    }
    // ---- one outline per fit (and group)
    for (const item of results) await fitReport(ctx, item, host, sc, y, x, groups);
  }

  async function fitReport(ctx, item, host, sc, y, x, groups) {
    const { f, g, res, error } = item;
    const fi = ctx.opt('fits', [], sc).findIndex((z) => z.id === f.id);
    const title = `${fitTitle(f, res)}${g.label ? ` ${g.label}` : ''}`;
    const ob = ctx.outline(title, { parent: host, key: `fit:${sc}:${f.id}:${g.label || ''}`, closed: f.report === false, menu: () => fitMenu(ctx, sc, f, groups, res, y, x, g), info: fi === 0 && !g.label ? 'p:fitybyx:fits' : null });
    ob.head.style.setProperty('--fit-color', g.color || FIT_COLORS[fi % FIT_COLORS.length]);
    ob.el.classList.add('sm-fyx-fit');
    if (error) { ob.add(problem(ctx, error)); return; }
    const lv = `${fmt(100 * (1 - (f.alpha || ctx.alpha)))}%`;
    const sub = (t, key, closed = false, info = null) => ctx.outline(t, { parent: ob, key: `${key}:${sc}:${f.id}:${g.label || ''}`, closed, info });
    switch (f.kind) {
      case 'mean':
        ob.add(ctx.kv([['Mean', res.mean], ['Std Dev [RMSE]', res.sd], ['Std Error', res.se], ['SSE', res.sse]]));
        break;
      case 'line': case 'poly': case 'special': {
        ob.add(el('p', { class: 'sm-fyx-eq', text: equation(res.ylab || y.name, res.terms) }));
        if (res.summary) sub('Summary of Fit', 'sof').add(kvOf(ctx, res.summary));
        if (res.lack_of_fit) sub('Lack Of Fit', 'lof', true).add(rtFixed(ctx, res.lack_of_fit), ctx.kv([['Max RSq', res.lack_of_fit.max_rsq]]));
        if (res.anova) sub('Analysis of Variance', 'anova').add(rtFixed(ctx, res.anova));
        if (res.estimates) sub('Parameter Estimates', 'est').add(rtFixed(ctx, res.estimates));
        if (res.original) sub('Fit Measured on Original Scale', 'orig').add(kvOf(ctx, res.original));
        break;
      }
      case 'spline':
        ob.add(ctx.kv([['R-Square', res.rsquare], ['Sum of Squares Error', res.sse], ['Lambda', res.lam == null ? 'generalised cross-validation' : res.lam, res.lam == null ? 'text' : 'num'], ['Standardized X', res.standardize ? 'yes' : 'no', 'text']]),
          ctx.note('The cubic smoothing spline minimising Σ w (y − f(x))² + λ ∫ f″(x)² dx (scipy.interpolate.make_smoothing_spline); rows with the same X are combined. Smaller λ is more flexible.'));
        break;
      case 'lowess':
        ob.add(ctx.kv([['R-Square', res.rsquare], ['Sum of Squares Error', res.sse], ['Smoothness (α)', res.frac], ['Robustness iterations', res.it, 'int']]),
          ctx.note('statsmodels\' LOWESS: at each point a line fitted with tricube weights to the nearest α of the points; JMP\'s Kernel Smoother offers other local fits and weight functions.'));
        break;
      case 'each':
        ob.add(ctx.kv([['Number of Observations', res.n], ['Number of Unique Values', res.n_unique, 'int'], ['Degrees of Freedom', res.df], ['Sum of Squares', res.sse], ['Mean Square', res.ms], ['R-Square', res.rsquare]]));
        break;
      case 'robust':
        ob.add(el('p', { class: 'sm-fyx-eq', text: equation(y.name, res.terms) }), rtFixed(ctx, res.estimates, { caption: 'Parameter Estimates' }),
          ctx.kv([['M-estimator', res.norm, 'text'], ['Scale (MAD)', res.scale], ['Iterations', res.iterations, 'int'], ['N', res.n]]),
          ctx.note('statsmodels RLM: the standard errors are its H1 sandwich and the tests use the normal distribution.'));
        break;
      case 'quantile':
        ob.add(el('p', { class: 'sm-fyx-eq', text: equation(`Q${fmt(100 * res.tau)}[${y.name}]`, res.terms) }), rtFixed(ctx, res.estimates, { caption: 'Parameter Estimates' }),
          ctx.kv([['Pseudo RSquare (Koenker-Machado)', res.prsquared], ['N', res.n]]));
        break;
      case 'orth':
        ob.add(ctx.rt({ columns: [{ key: 'variable', label: 'Variable', fmt: 'text' }, { key: 'mean', label: 'Mean' }, { key: 'sd', label: 'Std Dev' }], rows: res.means }, { sortable: false }),
          ctx.kv([['Correlation', res.r], ['Variance Ratio (Y error / X error)', res.ratio], ['N', res.n]]),
          ctx.rt({ columns: [{ key: 'term', label: '', fmt: 'text' }, { key: 'est', label: 'Estimate' }, { key: 'se', label: 'Std Error (jackknife)' }, { key: 'lo', label: 'LowerCL' }, { key: 'hi', label: 'UpperCL' }, { key: 'a', label: 'Alpha' }],
            rows: [{ term: 'Intercept', est: res.intercept, se: res.se_intercept, lo: res.lower_intercept, hi: res.upper_intercept, a: res.alpha }, { term: 'Slope', est: res.slope, se: res.se_slope, lo: res.lower, hi: res.upper, a: res.alpha }] }, { sortable: false }),
          ctx.note('Deming regression with the variance ratio shown. The confidence limits are slope ± t(N−2)·SE with the jackknife standard error over the observations; JMP computes its limits by its own formula, which can differ.'));
        break;
      case 'ellipse':
        ob.add(ctx.rt({ columns: [{ key: 'variable', label: 'Variable', fmt: 'text' }, { key: 'mean', label: 'Mean' }, { key: 'sd', label: 'Std Dev' }], rows: res.means }, { sortable: false }),
          ctx.kv([['Correlation', res.r], ['Signif. Prob', res.p, 'p'], [`Lower ${lv} (Fisher z)`, res.lower], [`Upper ${lv} (Fisher z)`, res.upper], ['Number', res.n]]),
          ctx.note('The contour of the bivariate normal with the sample means and covariance that holds this probability: (x − m)′S⁻¹(x − m) = χ²₂(P).'));
        break;
      case 'kde':
        ob.add(ctx.kv([['Contours', 'hold about 90%, 75%, 50%, 25% and 10% of the points', 'text'], ['Bandwidth factor (Scott)', res.bw], ['N', res.n], res.subsample ? ['Estimated from a random subsample of', res.subsample, 'int'] : null]),
          ctx.note('A Gaussian kernel density of the standardised points (scipy.stats.gaussian_kde); JMP\'s Nonpar Density uses its own kernel and bandwidth.'));
        break;
      default: break;
    }
    ob.add(notesOf(ctx, res.notes), ctx.code(res.code));
    if (f.resid && HAS_ROWS.has(f.kind)) await residualPlots(ctx, ob, item, y, x, sc);
  }

  async function residualPlots(ctx, ob, item, y, x, sc) {
    const { res, error } = await safeCall(ctx, FIT_FN[item.f.kind], { ...item.payload, want_rows: true });
    const d = ctx.outline('Diagnostics Plots', { parent: ob, key: `diag:${sc}:${item.f.id}:${item.g.label || ''}` });
    if (error) { d.add(problem(ctx, error)); return; }
    const rv = res.row_values;
    const rows = rv.rows;
    const xs = rows.map((r) => x.values[r]);
    const ys = rows.map((r) => y.values[r]);
    const zero = (xa) => ({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: 0, y1: 0, line: { color: GREY, width: 1, dash: 'dot' } });
    const sm = (title, xv, yv, xt, yt, shapes = []) => ctx.plot([{ type: rows.length > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: xv, y: yv, rows, marker: { size: 5 } }],
      { xaxis: { title: { text: xt } }, yaxis: { title: { text: yt } }, shapes, margin: { l: 56, r: 10, t: 8, b: 40 } }, { width: 280, height: 230, title });
    const order = rv.residual.map((_, k) => k).sort((a, b) => rv.residual[a] - rv.residual[b]);
    const nq = new Array(order.length);
    order.forEach((k, i) => { nq[k] = qnorm((i + 1) / (order.length + 1)); });
    let lo = Infinity, hi = -Infinity;
    for (const v of rv.predicted) { if (v < lo) lo = v; if (v > hi) hi = v; }
    d.add(ctx.row(
      sm('Residual by Predicted', rv.predicted, rv.residual, `Predicted ${y.name}`, 'Residual', [zero()]),
      sm('Actual by Predicted', rv.predicted, ys, `Predicted ${y.name}`, y.name, [{ type: 'line', x0: lo, x1: hi, y0: lo, y1: hi, line: { color: GREY, width: 1, dash: 'dot' } }]),
      sm('Residual by Row', rows.map((r) => r + 1), rv.residual, 'Row Number', 'Residual', [zero()]),
      sm(`Residual by ${x.name}`, xs, rv.residual, x.name, 'Residual', [zero()]),
      sm('Residual Normal Quantile Plot', nq, rv.residual, 'Normal Quantile', 'Residual')));
  }

  async function saveFit(ctx, sc, f, groups, what, y, x) {
    const rows = [], vals = [];
    for (const g of groups) {
      const payload = { ...basePayload(ctx, y, x), ...fitArgs(f), where: g.where, alpha: f.alpha || ctx.alpha, want_rows: true };
      if (g.rows) payload.rows = g.rows;
      const r = await ctx.call(FIT_FN[f.kind], payload);
      if (r.error || !r.row_values) { SM.ui.toast(r.error || 'nothing to save', { error: true }); return; }
      const rv = r.row_values;
      const v = rv[what];
      if (!v) { SM.ui.toast('this fit has no such values', { error: true }); return; }
      rv.rows.forEach((row, k) => { rows.push(row); vals.push(v[k]); });
    }
    const a = `${fmt(100 * (1 - (f.alpha || ctx.alpha)))}%`;
    const name = { predicted: `Predicted ${y.name}`, residual: `Residuals ${y.name}`, studentized: `Studentized Resid ${y.name}`, lo_mean: `Lower ${a} Mean ${y.name}`, hi_mean: `Upper ${a} Mean ${y.name}`, lo_indiv: `Lower ${a} Indiv ${y.name}`, hi_indiv: `Upper ${a} Indiv ${y.name}` }[what];
    ctx.saveColumn(name, { rows, values: vals }, { notes: `${fitTitle(f)} of ${y.name}, saved from ${ctx.report.title}` });
  }

  function fitMenu(ctx, sc, f, groups, res, y, x, g) {
    const fits = () => ctx.opt('fits', [], sc);
    const upd = (patch) => ctx.set('fits', fits().map((z) => (z.id === f.id ? { ...z, ...patch } : z)), sc);
    const tog = (label, key, dflt) => ({ label, checked: f[key] ?? dflt, action: () => upd({ [key]: !(f[key] ?? dflt) }) });
    const items = [];
    items.push(tog(f.kind === 'ellipse' ? 'Show Ellipse' : f.kind === 'kde' ? 'Show Contours' : 'Line of Fit', 'line', true));
    const ci = HAS_CI.has(f.kind) && !(f.kind === 'special' && (f.intercept != null || f.slope != null));
    if (ci) items.push(tog('Confid Curves Fit', 'cfit', false), tog('Confid Curves Indiv', 'cind', false), tog('Confid Shaded Fit', 'sfit', false), tog('Confid Shaded Indiv', 'sind', false));
    items.push(tog('Report', 'report', true));
    if (HAS_ROWS.has(f.kind)) {
      items.push({ separator: true },
        { label: 'Save Predicteds', action: () => saveFit(ctx, sc, f, groups, 'predicted', y, x) },
        { label: 'Save Residuals', action: () => saveFit(ctx, sc, f, groups, 'residual', y, x) });
      if (f.kind === 'line' || f.kind === 'poly') {
        items.push({ label: 'Save Studentized Residuals', action: () => saveFit(ctx, sc, f, groups, 'studentized', y, x) },
          { label: 'Save Mean Confidence Limits', action: async () => { await saveFit(ctx, sc, f, groups, 'lo_mean', y, x); await saveFit(ctx, sc, f, groups, 'hi_mean', y, x); } },
          { label: 'Save Indiv Confidence Limits', action: async () => { await saveFit(ctx, sc, f, groups, 'lo_indiv', y, x); await saveFit(ctx, sc, f, groups, 'hi_indiv', y, x); } });
      }
      items.push(tog('Plot Residuals', 'resid', false));
    }
    if (f.kind === 'spline') {
      items.push({ label: 'Change Lambda…', action: async () => { const v = await ask('Fit Spline', [{ key: 'lam', label: 'λ (empty: generalised cross-validation)', type: 'number', value: f.lam }, { key: 'std', label: 'Standardize X', type: 'check', value: !!f.standardize }]); if (v) upd({ lam: v.lam > 0 ? v.lam : null, standardize: !!v.std }); } });
    }
    if (f.kind === 'lowess') {
      items.push({ label: 'Smoothness', submenu: () => [0.1, 0.2, 0.333, 0.5, 0.667, 0.8, 1].map((a) => ({ label: `α = ${a}`, checked: Math.abs((f.frac ?? 0.667) - a) < 1e-9, action: () => upd({ frac: a }) })) },
        { label: 'Robustness', submenu: () => [0, 1, 2, 3].map((k) => ({ label: `${k} iteration${k === 1 ? '' : 's'}`, checked: (f.it ?? 0) === k, action: () => upd({ it: k }) })) });
    }
    if (f.kind === 'quantile') items.push({ label: 'Change Quantile…', action: async () => { const v = await ask('Fit Quantile', [{ key: 'tau', label: 'Quantile τ (0 to 1)', type: 'number', value: f.tau }]); if (v && v.tau > 0 && v.tau < 1) upd({ tau: v.tau }); } });
    if (f.kind === 'ellipse' && res && res.means) {
      // the rows of this ellipse's group inside (or outside) its contour
      const inside = (want) => {
        const chi = -2 * Math.log(1 - f.p);
        const P = pointsOf(ctx, y, x);
        const set = g && g.rows ? new Set(g.rows) : null;
        const mx = res.means[0].mean, my = res.means[1].mean, sx = res.means[0].sd, sy = res.means[1].sd, rho = res.r;
        const sel = [];
        P.rows.forEach((row, k) => {
          if (set && !set.has(row)) return;
          const u = (P.xv[k] - mx) / sx, v = (P.yv[k] - my) / sy;
          const d2 = (u * u - 2 * rho * u * v + v * v) / (1 - rho * rho);
          if ((d2 <= chi) === want) sel.push(row);
        });
        ctx.table.select(sel);
      };
      items.push({ label: 'Select Points Inside', action: () => inside(true) }, { label: 'Select Points Outside', action: () => inside(false) });
    }
    if (ci) items.push({ label: 'Set Alpha Level', submenu: () => [0.01, 0.05, 0.1].map((a) => ({ label: String(a), checked: Math.abs((f.alpha || ctx.alpha) - a) < 1e-12, action: () => upd({ alpha: a }) })) });
    items.push({ separator: true }, { label: 'Remove Fit', action: () => ctx.set('fits', fits().filter((z) => z.id !== f.id), sc) });
    return items;
  }

  async function fitSpecialDialog(ctx, sc) {
    const tr = Object.entries(TR_LABEL);
    const v = await SM.ui.form({
      title: 'Fit Special', lead: 'Transform Y and X, fit a polynomial in the transformed X, or hold the intercept or the slope at a value. The curve is drawn on the original scale.',
      fields: [
        { key: 'ytr', label: 'Y Transformation', type: 'select', value: 'none', choices: tr },
        { key: 'xtr', label: 'X Transformation', type: 'select', value: 'none', choices: tr.map(([k, l]) => [k, l.replace(/y/g, 'x')]) },
        { key: 'degree', label: 'Degree', type: 'select', value: '1', choices: [['1', '1: Straight Line'], ['2', '2: Quadratic'], ['3', '3: Cubic'], ['4', '4: Quartic'], ['5', '5: Quintic']] },
        { key: 'intercept', label: 'Constrain Intercept to (empty: free)', type: 'number', value: null },
        { key: 'slope', label: 'Constrain Slope to (empty: free)', type: 'number', value: null },
      ],
      validate: (x) => ((x.intercept != null || x.slope != null) && x.degree !== '1' ? 'A constrained fit is a straight line (degree 1).' : null),
    });
    if (!v) return;
    addFit(ctx, sc, { kind: 'special', ytr: v.ytr, xtr: v.xtr, degree: Number(v.degree), intercept: v.intercept, slope: v.slope });
  }

  function bivMenu(ctx, sc) {
    const add = (fit) => addFit(ctx, sc, fit);
    const other = (title, label, key, map, dflt) => async () => { const v = await ask(title, [{ key: 'v', label, type: 'number', value: dflt }]); if (v && v.v != null) { const f = map(v.v); if (f) add(f); } };
    const gid = ctx.opt('groupBy', null, sc);
    return [
      ctx.check('Show Points', 'points', sc, true),
      ctx.check('Histogram Borders', 'hist', sc, false),
      ctx.check('Summary Statistics', 'summary', sc, false),
      { label: 'Bayes Factor for the Correlation…', checked: !!ctx.opt('corrBf', null, sc), action: () => kappaDialog(ctx, sc) },
      { separator: true },
      { label: 'Fit Mean', action: () => add({ kind: 'mean' }) },
      { label: 'Fit Line', action: () => add({ kind: 'line' }) },
      { label: 'Fit Polynomial', submenu: [[2, '2, quadratic'], [3, '3, cubic'], [4, '4, quartic'], [5, '5'], [6, '6']].map(([d, l]) => ({ label: l, action: () => add({ kind: 'poly', degree: d }) })) },
      { label: 'Fit Special…', action: () => fitSpecialDialog(ctx, sc) },
      { label: 'Flexible', submenu: [
        { label: 'Fit Spline', submenu: () => [[0.1, '0.1, flexible'], [1, '1'], [10, '10'], [100, '100'], [1000, '1000'], [10000, '10000, stiff']].map(([l, t]) => ({ label: t, action: () => add({ kind: 'spline', lam: l }) }))
          .concat([{ label: 'Automatic (generalised cross-validation)', action: () => add({ kind: 'spline', lam: null }) }, { label: 'Other…', action: async () => { const v = await ask('Fit Spline', [{ key: 'lam', label: 'λ', type: 'number', value: 1 }, { key: 'std', label: 'Standardize X', type: 'check', value: false }]); if (v && v.lam > 0) add({ kind: 'spline', lam: v.lam, standardize: !!v.std }); } }]) },
        { label: 'Kernel Smoother', action: () => add({ kind: 'lowess', frac: 0.667, it: 0 }) },
        { label: 'Fit Each Value', action: () => add({ kind: 'each' }) },
      ] },
      { label: 'Fit Orthogonal', submenu: [
        { label: 'Univariate Variances, Prin Comp', action: () => add({ kind: 'orth', mode: 'univariate' }) },
        { label: 'Equal Variances', action: () => add({ kind: 'orth', mode: 'equal' }) },
        { label: 'Fit X to Y', action: () => add({ kind: 'orth', mode: 'x_to_y' }) },
        { label: 'Specified Variance Ratio…', action: other('Fit Orthogonal', 'Variance ratio, var(Y error) / var(X error)', 'ratio', (r) => (r >= 0 ? { kind: 'orth', mode: 'ratio', ratio: r } : null), 1) },
      ] },
      { label: 'Robust', submenu: [
        { label: 'Fit Robust', action: () => add({ kind: 'robust', method: 'huber' }) },
        { label: 'Fit Robust Bisquare', action: () => add({ kind: 'robust', method: 'bisquare' }) },
      ] },
      { label: 'Fit Quantile', submenu: [0.1, 0.25, 0.5, 0.75, 0.9].map((t) => ({ label: String(t), action: () => add({ kind: 'quantile', tau: t }) })).concat([{ label: 'Other…', action: other('Fit Quantile', 'Quantile τ (0 to 1)', 'tau', (t) => (t > 0 && t < 1 ? { kind: 'quantile', tau: t } : null), 0.5) }]) },
      { label: 'Density Ellipse', submenu: [0.5, 0.9, 0.95, 0.99].map((p) => ({ label: p.toFixed(2), action: () => add({ kind: 'ellipse', p }) })).concat([{ label: 'Other…', action: other('Density Ellipse', 'Probability', 'p', (p) => (p > 0 && p < 1 ? { kind: 'ellipse', p } : null), 0.95) }]) },
      { label: 'Nonpar Density', action: () => add({ kind: 'kde' }) },
      { separator: true },
      { label: 'Group By…', checked: !!gid, action: () => groupByDialog(ctx, sc) },
    ];
  }

  async function groupByDialog(ctx, sc) {
    const cats = ctx.table.columns.filter((c) => c.isCategorical);
    if (!cats.length) { SM.ui.toast('Group By needs an ordinal or nominal column'); return; }
    const cur = ctx.opt('groupBy', null, sc);
    const v = await ask('Group By', [{ key: 'col', label: 'Fit separately for each level of', type: 'select', value: cur || '', choices: [['', '(none)'], ...cats.map((c) => [c.id, c.name])] }],
      'The fits chosen from the red triangle are then done for each level, drawn in the level\'s colour, each with its own report.');
    if (v) ctx.set('groupBy', v.col || null, sc);
  }

  /* ======================================================================
     ONEWAY
     ====================================================================== */
  const TH = Array.from({ length: 73 }, (_, i) => (2 * Math.PI * i) / 72);

  async function oneway(ctx, y, x, host, sc) {
    const o = (k, d) => ctx.opt(k, d, sc);
    const blockCol = ctx.role('block');
    const block = blockCol && blockCol.isCategorical && blockCol.id !== x.id && blockCol.id !== y.id ? blockCol : null;
    if (blockCol && !block) host.add(ctx.note(`The Block ${blockCol.name} is not used: a block is an ordinal or nominal column other than Y and X.`));
    const base = basePayload(ctx, y, x);
    const res = await ctx.call('fitybyx.oneway', { ...base, block: block ? block.name : null });
    if (res.error) { host.add(ctx.warn(`${y.name} by ${x.name}: ${res.error}`)); return; }
    const levels = res.levels;
    const k = levels.length;
    const names = levels.map((l) => lvText(x, l.level));
    const lmap = new Map(levels.map((l) => [keyOf(l.level), l.index]));
    const P = pointsOf(ctx, y, x, block ? [block] : []);
    const code = P.xv.map((v) => lmap.get(keyOf(v)));
    const cmp = [];
    for (const c of o('compare', [])) cmp.push({ c, ...(await safeCall(ctx, 'fitybyx.oneway_compare', { ...base, method: c.method, control: c.control ?? null })) });
    // ---- the plot
    const traces = [];
    const n = P.rows.length;
    const shapes = [];
    if (o('points', true)) {
      const jitter = o('jitter', true);
      const keep = P.rows.map((_, i) => i).filter((i) => code[i] != null);
      traces.push({ type: n > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: keep.map((i) => code[i] + (jitter ? (jit(P.rows[i]) - 0.5) * 0.46 : 0)), y: keep.map((i) => P.yv[i]), rows: keep.map((i) => P.rows[i]), marker: { size: n > 3000 ? 4 : 6 }, name: 'Points', showlegend: false });
    }
    const maxN = Math.max(...levels.map((l) => l.n));
    if (o('box', o('quantiles', false))) {
      levels.forEach((l, i) => traces.push({ type: 'box', x: [i], q1: [l.q25], median: [l.median], q3: [l.q75], lowerfence: [l.lo_fence], upperfence: [l.hi_fence], boxpoints: false, width: 0.28,
        fillcolor: 'rgba(143,169,194,0.18)', line: { color: SM.util.themeColors().text, width: 1 }, hoverinfo: 'skip', showlegend: false, name: names[i] }));
    }
    const pooled = (l) => (l.lower_pooled != null ? [l.lower_pooled, l.upper_pooled] : null);
    if (o('diamonds', o('anova', false)) && res.anova) {
      levels.forEach((l, i) => {
        const ci = block && l.lower_lsmean != null ? [l.lower_lsmean, l.upper_lsmean] : pooled(l);
        const m = block && l.lsmean != null ? l.lsmean : l.mean;
        if (!ci || m == null) return;
        const w = 0.08 + 0.3 * (l.n / maxN);
        const ov = (ci[1] - m) / Math.SQRT2;
        traces.push({ type: 'scatter', mode: 'lines', x: [i - w, i, i + w, i, i - w, null, i - w * 0.7, i + w * 0.7, null, i - w * 0.7, i + w * 0.7, null, i - w, i + w],
          y: [m, ci[1], m, ci[0], m, null, m + ov, m + ov, null, m - ov, m - ov, null, m, m], line: { color: GREEN, width: 1.4 },
          hovertemplate: `${names[i]}<br>mean ${fmt(m)}<br>${fmt(100 * (1 - ctx.alpha))}% CI ${fmt(ci[0])} to ${fmt(ci[1])}<extra></extra>`, showlegend: false });
      });
    }
    const seg = (i, v, w, color, dash = 'solid', width = 1.4) => ({ type: 'line', x0: i - w, x1: i + w, y0: v, y1: v, xref: 'x', yref: 'y', line: { color, width, dash } });
    if (o('meanLines', o('meansd', false))) levels.forEach((l, i) => shapes.push(seg(i, l.mean_raw, 0.3, RED)));
    if (o('errorBars', o('meansd', false))) levels.forEach((l, i) => { if (l.se != null) shapes.push({ type: 'line', x0: i + 0.18, x1: i + 0.18, y0: l.mean_raw - l.se, y1: l.mean_raw + l.se, line: { color: RED, width: 1.2 } }, seg(i + 0.18, l.mean_raw - l.se, 0.05, RED, 'solid', 1.2), seg(i + 0.18, l.mean_raw + l.se, 0.05, RED, 'solid', 1.2)); });
    if (o('sdLines', o('meansd', false))) levels.forEach((l, i) => { if (l.sd != null) shapes.push(seg(i, l.mean_raw - l.sd, 0.24, PURPLE, 'dash', 1.1), seg(i, l.mean_raw + l.sd, 0.24, PURPLE, 'dash', 1.1)); });
    if (o('ciLines', false)) levels.forEach((l, i) => { const ci = pooled(l); if (ci) shapes.push(seg(i, ci[0], 0.2, GREEN, 'dot', 1.1), seg(i, ci[1], 0.2, GREEN, 'dot', 1.1)); });
    if (o('grandMean', false)) shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: res.grand_mean, y1: res.grand_mean, line: { color: GREY, width: 1, dash: 'dot' } });
    if (o('connect', false)) traces.push({ type: 'scatter', mode: 'lines+markers', x: levels.map((_, i) => i), y: levels.map((l) => l.mean), line: { color: RED, width: 1.4 }, marker: { size: 5, color: RED }, hoverinfo: 'skip', showlegend: false });
    // comparison circles for the last comparison chosen
    const circ = o('circles', true) ? cmp.filter((c) => c.res && !c.error && c.res.quantile && c.res.quantile.value != null).slice(-1)[0] : null;
    const circles = [];
    const layout = {
      xaxis: { title: { text: x.name }, tickvals: levels.map((_, i) => i), ticktext: names, range: [-0.6, k - 0.4], zeroline: false, showgrid: false },
      yaxis: { title: { text: y.name }, zeroline: false }, shapes, margin: { l: 60, r: 14, t: 10, b: 44 },
    };
    if (circ) {
      const q = circ.res.quantile.value;
      const se = (i) => Math.sqrt(circ.res.mse / (circ.res.n[i] || 1));
      layout.xaxis.domain = [0, 0.78];
      layout.xaxis2 = { domain: [0.82, 1], range: [-1.05, 1.05], showticklabels: false, showgrid: false, zeroline: false, showline: false, ticks: '', title: { text: circ.c.method === 'tukey' ? 'Tukey' : circ.c.method === 'dunnett' ? 'Dunnett' : 'Student\'s t', font: { size: 10 } } };
      levels.forEach((l, i) => {
        const r = q * se(i);
        circles.push({ at: traces.length, r });
        traces.push({ type: 'scatter', mode: 'lines', xaxis: 'x2', yaxis: 'y', x: TH.map((t) => 0.3 * Math.cos(t)), y: TH.map((t) => circ.res.means[i] + r * Math.sin(t)), line: { color: PALETTE[i % PALETTE.length], width: 1.3 }, hovertemplate: `${names[i]}: mean ${fmt(circ.res.means[i])}, radius ${fmt(r)}<extra></extra>`, showlegend: false });
      });
    }
    const width = availWidth(ctx, Math.max(420, Math.min(760, 180 + 70 * k + (circ ? 120 : 0))));
    host.add(ctx.plot(traces, layout, {
      width, height: 380, title: `${y.name} by ${x.name}`,
      onDraw: circles.length ? (gd) => {
        const fl = gd._fullLayout;
        if (!fl || !fl._size || !fl.yaxis || !fl.yaxis.range) return;
        const yr = fl.yaxis.range;
        const ux = 2.1 / (fl._size.w * 0.18), uy = (yr[1] - yr[0]) / fl._size.h;
        try { Plotly.restyle(gd, { x: circles.map((c) => TH.map((t) => (c.r / uy) * ux * Math.cos(t))) }, circles.map((c) => c.at)); } catch (e) { /* the graph was redrawn */ }
      } : null,
    }));
    // ---- the reports, in JMP's order
    if (res.notes && res.notes.length) host.add(notesOf(ctx, res.notes));
    if (o('quantiles', false)) {
      const ob = ctx.outline('Quantiles', { parent: host, key: `q:${sc}` });
      ob.add(ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'min', label: 'Minimum' }, { key: 'q10', label: '10%' }, { key: 'q25', label: '25%' }, { key: 'median', label: 'Median' }, { key: 'q75', label: '75%' }, { key: 'q90', label: '90%' }, { key: 'max', label: 'Maximum' }],
        rows: levels.map((l, i) => ({ ...l, lv: names[i] })) }, { sortable: false }));
    }
    if (o('anova', false)) await owAnova(ctx, host, sc, res, names, block, y, x, base);
    if (o('meansd', false)) {
      const lvl = `${fmt(100 * (1 - ctx.alpha))}%`;
      const ob = ctx.outline('Means and Std Deviations', { parent: host, key: `msd:${sc}` });
      ob.add(ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'n', label: 'Number' }, { key: 'mean_raw', label: 'Mean' }, { key: 'sd', label: 'Std Dev' }, { key: 'se', label: 'Std Err Mean' }, { key: 'lower', label: `Lower ${lvl}` }, { key: 'upper', label: `Upper ${lvl}` }],
        rows: levels.map((l, i) => ({ ...l, lv: names[i] })) }, { sortable: false }));
      if (ctx.role('weight')) ob.add(ctx.note('Weight is not used here; Freq is.'));
    }
    if (o('ttest', false)) {
      const ob = ctx.outline('t Test', { parent: host, key: `tt:${sc}` });
      const { res: r, error } = await safeCall(ctx, 'fitybyx.oneway_ttest', base);
      if (error) ob.add(problem(ctx, error));
      else {
        ob.add(el('p', { class: 'sm-fyx-eq', text: `${names[1]}-${names[0]}` }), ctx.note('Assuming unequal variances'), tTestTable(ctx, r), notesOf(ctx, r.notes), ctx.code(r.code));
        if (o('effect', false)) {
          await effectOutline(ctx, ob, `tte:${sc}`, 'fitybyx.ttest_effect', { ...base, kind: 'welch' },
            (e) => `${names[1]} minus ${names[0]} over √((s₁² + s₂²)/2) = ${fmt(e.standardizer)}, the unweighted standardizer for unequal variances (Cohen 1988): d* and Hedges' g* = J·d* with J = ${fmt(e.j)}. The interval is Bonett's (2008), d* ± z·SE; no exact interval exists when the variances differ. Right click for the standard errors.`,
            () => ctx.set('effect', false, sc));
        }
      }
    }
    const bf = o('bf', null);
    if (bf && (k !== 2 || block)) host.add(ctx.note(`Bayes Factor: ${block ? 'the two-sample t test takes no Block' : 'the two-sample t test needs exactly two levels'}; it is not shown.`));
    else if (bf) {
      await bayesOutline(ctx, host, `bf:${sc}`, 'fitybyx.oneway_bf', { ...base, r: bf.r },
        (r) => [['t (pooled)', r.t], ['DF', r.df], [`N ${names[0]}`, r.n1], [`N ${names[1]}`, r.n2], ['Prior scale r', r.r]],
        (r) => `The JZS Bayes factor of the two-sample t test (Rouder et al. 2009): the pooled t of ${names[1]} minus ${names[0]}, equal variances, against a Cauchy(0, ${fmt(r.r)}) prior on δ = (μ₂ − μ₁)/σ under the alternative; a one-sided alternative keeps the prior's half on its side, doubled. ${BF_NOTE}`,
        () => [{ label: 'Change Prior…', action: () => priorDialog(ctx, sc, 'bf', 'Bayes Factor: two-sample t test') }, { label: 'Remove', action: () => ctx.set('bf', null, sc) }]);
    }
    if (o('anom', false)) await owAnom(ctx, host, sc, base, names);
    if (cmp.length) {
      const mc = ctx.outline('Means Comparisons', { parent: host, key: `mc:${sc}`, info: 'p:fitybyx:compare' });
      for (const c of cmp) compareReport(ctx, mc, sc, c, names);
    }
    for (const t of o('np', [])) await nonparReport(ctx, host, sc, base, t, names);
    if (o('bm', false)) await brunnerReport(ctx, host, sc, base, names);
    for (const m of o('npmc', [])) await npmcReport(ctx, host, sc, base, m, names);
    if (o('unequal', false)) await unequalReport(ctx, host, sc, base, names);
    if (o('equiv', null)) await equivReport(ctx, host, sc, base, o('equiv', null), names);
    if (o('bmTost', null)) await brunnerTostReport(ctx, host, sc, base, o('bmTost', null), names);
    if (o('rates', null)) await ratesReport(ctx, host, sc, base, o('rates', null), y, x);
    if (o('power', null)) await powerReport(ctx, host, sc, base, o('power', null));
    if (o('nqp', null)) owNormalQuantile(ctx, host, sc, P, code, names, o('nqp', null), levels);
    if (o('cdf', false)) owCdf(ctx, host, sc, P, code, names);
    if (o('densities', null)) await owDensities(ctx, host, sc, base, names, o('densities', null), y);
  }

  function tTestTable(ctx, r) {
    const lv = fmt(r.confidence);
    return ctx.row(ctx.kv([['Difference', r.diff], ['Std Err Dif', r.se], ['Upper CL Dif', r.upper], ['Lower CL Dif', r.lower], ['Confidence', lv, 'text']]),
      ctx.kv([['t Ratio', r.t], ['DF', r.df], ['Prob > |t|', r.p, 'p'], ['Prob > t', r.p_greater, 'p'], ['Prob < t', r.p_less, 'p']]));
  }

  async function owAnova(ctx, host, sc, res, names, block, y, x, base) {
    const ob = ctx.outline('Oneway Anova', { parent: host, key: `anova:${sc}`, info: 'p:fitybyx:anova' });
    if (res.error_anova) { ob.add(ctx.warn(res.error_anova)); return; }
    const effect = ctx.opt('effect', false, sc);
    const off = () => ctx.set('effect', false, sc);
    ctx.outline('Summary of Fit', { parent: ob, key: `sof:${sc}` }).add(kvOf(ctx, res.summary));
    if (res.pooled_t) {
      const t = ctx.outline('t Test', { parent: ob, key: `ptt:${sc}` });
      t.add(el('p', { class: 'sm-fyx-eq', text: `${names[1]}-${names[0]}` }), ctx.note('Assuming equal variances'), tTestTable(ctx, res.pooled_t));
      if (effect) {
        await effectOutline(ctx, t, `ptte:${sc}`, 'fitybyx.ttest_effect', { ...base, kind: 'pooled' },
          (e) => `${names[1]} minus ${names[0]} over the pooled standard deviation ${fmt(e.standardizer)}: Cohen's d, and Hedges' g = J·d with J = ${fmt(e.j)} (Hedges 1981). The interval of d is exact: the noncentral t distributions whose noncentrality λ puts the pooled t at their upper and lower α/2 points give δ = λ√(1/n₁ + 1/n₂) (Steiger and Fouladi 1997); g's is J times it.`, off);
      }
    }
    ctx.outline('Analysis of Variance', { parent: ob, key: `aov:${sc}` }).add(rtFixed(ctx, res.anova));
    if (effect) {
      await effectOutline(ctx, ob, `aove:${sc}`, 'fitybyx.oneway_effect', { ...base, block: block ? block.name : null },
        (e) => `${e.partial ? 'Partial η², ε² and ω²: the Block\'s sum of squares left out of the denominators. ' : ''}η² = SS(${x.name})/SS(total) overstates the population value; ε² (Kelley 1935) and ω² (Hays 1963) take the error mean square off, and are less biased. The interval is the exact one of the population proportion of variance, λ/(λ + df₁ + df₂ + 1) (N${e.partial ? ' in a one-way layout' : ''}) for the noncentral F whose λ puts F = ${fmt(e.F)} on (${fmt(e.df_num)}, ${fmt(e.df_den)}) DF at its upper and lower α/2 points (Steiger 2004): the same for the three estimates, which estimate the same proportion. The lower limit is 0 when the F test's p-value is above α/2.`, off);
    }
    const lvl = `${fmt(100 * (1 - ctx.alpha))}%`;
    const m = ctx.outline('Means for Oneway Anova', { parent: ob, key: `mfa:${sc}` });
    if (block) {
      m.add(ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'n', label: 'Number' }, { key: 'lsmean', label: 'Mean' }, { key: 'se_lsmean', label: 'Std Error' }, { key: 'lower_lsmean', label: `Lower ${lvl}` }, { key: 'upper_lsmean', label: `Upper ${lvl}` }],
        rows: res.levels.map((l, i) => ({ ...l, lv: names[i] })) }, { sortable: false }), ctx.note(`The means are least squares means: the ${block.name} effect averaged over its levels.`));
      const bm = ctx.outline('Block Means', { parent: ob, key: `bm:${sc}` });
      bm.add(ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'mean', label: 'Mean' }, { key: 'n', label: 'Number' }], rows: res.block_means.map((b) => ({ ...b, lv: lvText(block, b.level) })) }, { sortable: false }));
    } else {
      m.add(ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'n', label: 'Number' }, { key: 'mean', label: 'Mean' }, { key: 'se_pooled', label: 'Std Error' }, { key: 'lower_pooled', label: `Lower ${lvl}` }, { key: 'upper_pooled', label: `Upper ${lvl}` }],
        rows: res.levels.map((l, i) => ({ ...l, lv: names[i] })) }, { sortable: false }), ctx.note('Std Error uses a pooled estimate of error variance'));
    }
    ob.add(ctx.code(res.code));
  }

  const METHOD_TITLE = {
    student: 'Comparisons for each pair using Student\'s t', tukey: 'Comparisons for all pairs using Tukey-Kramer HSD', dunnett: 'Comparisons with a control using Dunnett\'s Method',
    gameshowell: 'Comparisons for all pairs using Games-Howell',
  };

  function compareReport(ctx, parent, sc, c, names) {
    const gh = c.c.method === 'gameshowell';
    const ob = ctx.outline(METHOD_TITLE[c.c.method], { parent, key: `cmp:${sc}:${c.c.method}`, menu: () => [{ label: 'Remove', action: () => ctx.set('compare', ctx.opt('compare', [], sc).filter((z) => z.method !== c.c.method), sc) }] });
    if (c.error) { ob.add(problem(ctx, c.error)); return; }
    const r = c.res;
    if (r.quantile.value != null) ob.add(ctx.rt({ columns: [{ key: 'q', label: r.quantile.label }, { key: 'a', label: 'Alpha' }], rows: [{ q: r.quantile.value, a: r.alpha }] }, { sortable: false, caption: 'Confidence Quantile' }));
    else ob.add(ctx.kv([['Alpha', r.alpha]]), ctx.note('Each pair has its own quantile q*, from its own degrees of freedom: see the Ordered Differences Report (right click it for q*). No comparison circles: they need one quantile and one standard error per level.'));
    if (r.matrix) {
      const cols = [{ key: 'lv', label: '', fmt: 'text' }, ...r.order.map((i) => ({ key: `c${i}`, label: names[i] }))];
      const rows = r.order.map((i, a) => { const row = { lv: names[i] }; r.order.forEach((j, b) => { row[`c${j}`] = r.matrix[a][b]; }); return row; });
      const what = c.c.method === 'tukey' ? 'HSD' : gh ? 'q*·SE' : 'LSD';
      const mt = ctx.outline(`${gh ? 'Games-Howell' : c.c.method === 'tukey' ? 'HSD' : 'LSD'} Threshold Matrix`, { parent: ob, key: `thr:${sc}:${c.c.method}` });
      mt.add(el('p', { class: 'sm-ob-note', text: `Abs(Dif)-${what}` }), markPositive(ctx.rt({ columns: cols, rows }, { sortable: false })), ctx.note(`Positive values show pairs of means that are significantly different.${gh ? ' Each pair with its own standard error and q*; the diagonal with twice the level\'s own variance.' : ''}`));
    }
    if (r.matrix_control) {
      const mt = ctx.outline('LSD Threshold Matrix', { parent: ob, key: `thr:${sc}:${c.c.method}` });
      mt.add(el('p', { class: 'sm-ob-note', text: `Abs(Dif)-LSD against the control ${names[r.control]}` }),
        markPositive(ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'v', label: `vs ${names[r.control]}` }], rows: r.matrix_control.map((m) => ({ lv: names[m.index], v: m.value })) }, { sortable: false })),
        ctx.note('Positive values show levels significantly different from the control.'));
    }
    if (r.letters) {
      const cl = ctx.outline('Connecting Letters Report', { parent: ob, key: `cl:${sc}:${c.c.method}` });
      const t = ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'letters', label: '', fmt: 'text' }, { key: 'mean', label: 'Mean' }], rows: r.letters.map((l) => ({ lv: names[l.index], letters: l.letters, mean: l.mean })) }, { sortable: false });
      t.classList.add('sm-fyx-letters');
      cl.add(t, ctx.note('Levels not connected by the same letter are significantly different.'));
    }
    const od = ctx.outline(r.control != null ? 'Comparisons with a control' : 'Ordered Differences Report', { parent: ob, key: `od:${sc}:${c.c.method}` });
    const ocols = [{ key: 'a', label: 'Level', fmt: 'text' }, { key: 'b', label: '- Level', fmt: 'text' }, { key: 'diff', label: 'Difference' }, { key: 'se', label: 'Std Err Dif' }, { key: 'lower', label: 'Lower CL' }, { key: 'upper', label: 'Upper CL' }, { key: 'p', label: 'p-Value', fmt: 'p' }];
    if (gh) { ocols.splice(4, 0, { key: 'df', label: 'DF' }); ocols.push({ key: 'q', label: 'q*', hidden: true }); }
    od.add(ctx.rt({ columns: ocols, rows: r.pairs.map((p) => ({ ...p, a: names[p.i], b: names[p.j] })) }, { sortable: true }));
    ob.add(notesOf(ctx, r.notes), ctx.code(r.code));
  }

  const NP_TITLE = { wilcoxon: 'Wilcoxon / Kruskal-Wallis Tests (Rank Sums)', median: 'Median Test (Number of Points above Median)', vdw: 'Van der Waerden Test (Normal Quantiles)', ks: 'Kolmogorov-Smirnov Two-Sample Test' };

  async function nonparReport(ctx, host, sc, base, t, names) {
    const rm = { label: 'Remove', action: () => ctx.set('np', ctx.opt('np', [], sc).filter((z) => z !== t), sc) };
    const ob = ctx.outline(NP_TITLE[t], { parent: host, key: `np:${sc}:${t}`, menu: () => [rm], info: 'p:fitybyx:nonpar' });
    if (t === 'ks') {
      const { res: r, error } = await safeCall(ctx, 'fitybyx.oneway_ks', base);
      if (error) { ob.add(problem(ctx, error)); return; }
      ob.add(ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'count', label: 'Count', fmt: 'int' }, { key: 'edf', label: 'EDF at Maximum' }, { key: 'dev', label: 'Deviation from Mean at Maximum' }], rows: r.levels.map((l) => ({ ...l, lv: names[l.index] })) }, { sortable: false }),
        ctx.kv([['KS', r.KS], ['KSa', r.KSa], ['D=max|F1-F2|', r.D], ['Prob > D', r.p, 'p'], ['D+ = max(F1-F2)', r.D_plus], ['Prob > D+', r.p_plus, 'p'], ['D- = max(F2-F1)', r.D_minus], ['Prob > D-', r.p_minus, 'p']]),
        r.method ? ctx.note(`scipy.stats.ks_2samp, the ${r.method} p-values.`) : null, notesOf(ctx, r.notes), ctx.code(r.code));
      return;
    }
    const { res: r, error } = await safeCall(ctx, 'fitybyx.oneway_nonpar', { ...base, test: t });
    if (error) { ob.add(problem(ctx, error)); return; }
    ob.add(ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'count', label: 'Count', fmt: 'int' }, { key: 'score_sum', label: 'Score Sum' }, { key: 'expected', label: 'Expected Score' }, { key: 'score_mean', label: 'Score Mean' }, { key: 'std0', label: '(Mean-Mean0)/Std0' }],
      rows: r.levels.map((l) => ({ ...l, lv: names[l.index] })) }, { sortable: false }));
    if (r.two_sample) {
      ctx.outline('2-Sample Test, Normal Approximation', { parent: ob, key: `np2:${sc}:${t}` }).add(ctx.rt({ columns: [{ key: 'S', label: 'S' }, { key: 'Z', label: 'Z' }, { key: 'p', label: 'Prob>|Z|', fmt: 'p' }], rows: [r.two_sample] }, { sortable: false }),
        ctx.note(`S is the score sum of ${names[r.two_sample.level]}, the level with fewer rows${t === 'wilcoxon' ? '; Z has a continuity correction of 0.5' : ''}.`));
    }
    ctx.outline('1-Way Test, ChiSquare Approximation', { parent: ob, key: `np1:${sc}:${t}` }).add(ctx.rt({ columns: [{ key: 'chisq', label: 'ChiSquare' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: [r] }, { sortable: false }));
    ob.add(notesOf(ctx, r.notes), ctx.code(r.code));
  }

  const NPMC_TITLE = {
    wilcoxon: 'Nonparametric Comparisons For Each Pair Using Wilcoxon Method', steel_dwass: 'Nonparametric Comparisons For All Pairs Using Steel-Dwass Method',
    steel_control: 'Nonparametric Comparisons With Control Using Steel Method', dunn_control: 'Nonparametric Comparisons With Control Using Dunn Method for Joint Ranking',
    dunn_all: 'Nonparametric Comparisons For All Pairs Using Dunn Method for Joint Ranking',
  };

  async function npmcReport(ctx, host, sc, base, m, names) {
    const rm = { label: 'Remove', action: () => ctx.set('npmc', ctx.opt('npmc', [], sc).filter((z) => z.method !== m.method), sc) };
    const ob = ctx.outline(NPMC_TITLE[m.method], { parent: host, key: `npmc:${sc}:${m.method}`, menu: () => [rm] });
    const { res: r, error } = await safeCall(ctx, 'fitybyx.oneway_nonpar_mc', { ...base, method: m.method, control: m.control ?? null });
    if (error) { ob.add(problem(ctx, error)); return; }
    if (r.quantile) ob.add(ctx.kv([['q*', r.quantile], ['Alpha', r.alpha]]));
    const hl = r.pairs.some((p) => p.hl != null);
    const cols = [{ key: 'a', label: 'Level', fmt: 'text' }, { key: 'b', label: '- Level', fmt: 'text' }, { key: 'diff', label: 'Score Mean Difference' }, { key: 'se', label: 'Std Err Dif' }, { key: 'z', label: 'Z' }, { key: 'p', label: 'p-Value', fmt: 'p' }];
    if (hl) cols.push({ key: 'hl', label: 'Hodges-Lehmann' }, { key: 'lower', label: 'Lower CL' }, { key: 'upper', label: 'Upper CL' });
    if (r.pairs.some((p) => p.p_raw != null)) cols.push({ key: 'p_raw', label: 'Unadjusted p', fmt: 'p', hidden: true });
    ob.add(ctx.rt({ columns: cols, rows: r.pairs.map((p) => ({ ...p, a: names[p.i], b: names[p.j] })) }), notesOf(ctx, r.notes), ctx.code(r.code));
  }

  async function unequalReport(ctx, host, sc, base, names) {
    const ob = ctx.outline('Tests that the Variances are Equal', { parent: host, key: `uv:${sc}`, info: 'p:fitybyx:variances' });
    const { res: r, error } = await safeCall(ctx, 'fitybyx.oneway_unequal_var', base);
    if (error) { ob.add(problem(ctx, error)); return; }
    ob.add(ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'count', label: 'Count', fmt: 'int' }, { key: 'sd', label: 'Std Dev' }, { key: 'mad_mean', label: 'MeanAbsDif to Mean' }, { key: 'mad_median', label: 'MeanAbsDif to Median' }], rows: r.levels.map((l) => ({ ...l, lv: names[l.index] })) }, { sortable: false }),
      ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'f', label: 'F Ratio' }, { key: 'dfn', label: 'DFNum' }, { key: 'dfd', label: 'DFDen' }, { key: 'p', label: 'p-Value', fmt: 'p' }], rows: r.tests }, { sortable: false }));
    const w = ctx.outline('Welch\'s Test', { parent: ob, key: `welch:${sc}` });
    w.add(ctx.note('Welch Anova testing Means Equal, allowing Std Devs Not Equal'),
      ctx.rt({ columns: [{ key: 'f', label: 'F Ratio' }, { key: 'dfn', label: 'DFNum' }, { key: 'dfd', label: 'DFDen' }, { key: 'p', label: 'Prob > F', fmt: 'p' }].concat(r.welch.t != null ? [{ key: 't', label: 't Test' }] : []), rows: [r.welch] }, { sortable: false }));
    ob.add(notesOf(ctx, r.notes), ctx.code(r.code));
  }

  async function equivReport(ctx, host, sc, base, eq, names) {
    const ob = ctx.outline('Equivalence Test', { parent: host, key: `eq:${sc}`, menu: () => [{ label: 'Remove', action: () => ctx.set('equiv', null, sc) }] });
    const { res: r, error } = await safeCall(ctx, 'fitybyx.oneway_equivalence', { ...base, delta: eq.delta });
    if (error) { ob.add(problem(ctx, error)); return; }
    ob.add(ctx.kv([['Difference considered practically zero', r.delta], ['Alpha', r.alpha]]),
      ctx.rt({ columns: [{ key: 'a', label: 'Level', fmt: 'text' }, { key: 'b', label: '- Level', fmt: 'text' }, { key: 'diff', label: 'Difference' }, { key: 'lower', label: `Lower ${fmt(100 * (1 - 2 * r.alpha))}% CL` }, { key: 'upper', label: `Upper ${fmt(100 * (1 - 2 * r.alpha))}% CL` },
        { key: 't_lower', label: 't Ratio (lower)' }, { key: 'p_lower', label: 'p (lower)', fmt: 'p' }, { key: 't_upper', label: 't Ratio (upper)' }, { key: 'p_upper', label: 'p (upper)', fmt: 'p' }, { key: 'p', label: 'Max p-Value', fmt: 'p' }],
      rows: r.pairs.map((p) => ({ ...p, a: names[p.i], b: names[p.j] })) }),
      ctx.note(`Two one-sided t tests: a pair is equivalent at α = ${r.alpha} when both reject, so when the Max p-Value is below α (the ${fmt(100 * (1 - 2 * r.alpha))}% interval lies inside ±${fmt(r.delta)}).`), notesOf(ctx, r.notes), ctx.code(r.code));
  }

  /* ---- Brunner-Munzel: the probability of superiority (statsmodels
     rank_compare_2indep; not in JMP) ------------------------------------ */
  async function brunnerReport(ctx, host, sc, base, names) {
    const ob = ctx.outline('Brunner-Munzel Test (Probability of Superiority)', { parent: host, key: `bm:${sc}`, info: 'p:fitybyx:brunner', menu: () => [
      { label: 'Equivalence Test…', checked: !!ctx.opt('bmTost', null, sc), action: () => brunnerTostDialog(ctx, sc) },
      { separator: true }, { label: 'Remove', action: () => ctx.set('bm', false, sc) }] });
    const { res: r, error } = await safeCall(ctx, 'fitybyx.oneway_brunner', base);
    if (error) { ob.add(problem(ctx, error)); return; }
    const lvl = `${fmt(100 * (1 - ctx.alpha))}%`;
    const cols = [{ key: 'a', label: 'Level', fmt: 'text' }, { key: 'b', label: 'vs Level', fmt: 'text' },
      { key: 'prob', label: 'P(Level>vs Level)', title: 'P(Y at Level > Y at vs Level) + P(equal)/2' }, { key: 'se', label: 'Std Err' },
      { key: 'lower', label: `Lower ${lvl}` }, { key: 'upper', label: `Upper ${lvl}` }, { key: 'stat', label: 'Brunner-Munzel t' }, { key: 'df', label: 'DF' },
      { key: 'p', label: 'Prob>|t|', fmt: 'p' }, { key: 'p_greater', label: 'Prob>t', fmt: 'p', hidden: true }, { key: 'p_less', label: 'Prob<t', fmt: 'p', hidden: true },
      { key: 'somersd', label: 'Somers\' D (2P − 1)', hidden: true }, { key: 'n1', label: 'N Level', fmt: 'int', hidden: true }, { key: 'n2', label: 'N vs Level', fmt: 'int', hidden: true }];
    if (r.pairs.some((p) => p.p_holm != null)) cols.push({ key: 'p_holm', label: 'Holm-adjusted p', fmt: 'p', hidden: true });
    ob.add(ctx.rt({ columns: cols, rows: r.pairs.map((p) => ({ ...p, a: names[p.i], b: names[p.j] })) }, { sortable: r.pairs.length > 2 }),
      ctx.note('P(Level>vs Level) is P(Y₁ > Y₂) + ½P(Y₁ = Y₂) from the ranks, the Mann-Whitney U/(n₁n₂). The Brunner-Munzel test of P = ½ does not assume, as the Wilcoxon test does, that the two distributions are the same under the null; t with Welch-Satterthwaite degrees of freedom. Not in JMP, whose closest is the Wilcoxon test (its null hypothesis: identical distributions). Right click for one-sided p-values, Somers\' D and Holm-adjusted p-values.'),
      notesOf(ctx, r.notes), ctx.code(r.code));
  }

  async function brunnerTostReport(ctx, host, sc, base, tost, names) {
    const ob = ctx.outline('Equivalence Test (Probability of Superiority)', { parent: host, key: `bmtost:${sc}`, info: 'p:fitybyx:brunner', menu: () => [
      { label: 'Change Bounds…', action: () => brunnerTostDialog(ctx, sc) }, { label: 'Remove', action: () => ctx.set('bmTost', null, sc) }] });
    const { res: r, error } = await safeCall(ctx, 'fitybyx.oneway_brunner', { ...base, tost: { low: tost.low, upp: tost.upp } });
    if (error) { ob.add(problem(ctx, error)); return; }
    const t = r.tost;
    const lv2 = `${fmt(100 * (1 - 2 * r.alpha))}%`;
    ob.add(ctx.kv([['Lower bound', t.low], ['Upper bound', t.upp], ['Alpha', r.alpha]]),
      ctx.rt({ columns: [{ key: 'a', label: 'Level', fmt: 'text' }, { key: 'b', label: 'vs Level', fmt: 'text' }, { key: 'prob', label: 'P(Level>vs Level)' },
        { key: 'lower', label: `Lower ${lv2}` }, { key: 'upper', label: `Upper ${lv2}` }, { key: 't_lower', label: 't (lower)' }, { key: 'p_lower', label: 'p (lower)', fmt: 'p' },
        { key: 't_upper', label: 't (upper)' }, { key: 'p_upper', label: 'p (upper)', fmt: 'p' }, { key: 'p', label: 'Max p-Value', fmt: 'p' }],
      rows: t.pairs.map((p) => ({ ...p, a: names[p.i], b: names[p.j] })) }),
      ctx.note(`Two one-sided Brunner-Munzel tests (statsmodels tost_prob_superior): the levels are stochastically equivalent at α = ${r.alpha} when both reject, so when the Max p-Value is below α (the ${lv2} interval lies inside ${fmt(t.low)} to ${fmt(t.upp)}). Not in JMP, whose Equivalence Test is for means (t tests).`),
      notesOf(ctx, r.notes), ctx.code(r.code));
  }

  async function brunnerTostDialog(ctx, sc) {
    const cur = ctx.opt('bmTost', null, sc) || { low: 0.4, upp: 0.6 };
    const v = await SM.ui.form({
      title: 'Equivalence Test: Probability of Superiority', info: 'p:fitybyx:brunner',
      lead: 'Two levels are stochastically equivalent when P(Y₁ > Y₂) + ½P(Y₁ = Y₂) lies between the bounds; ½ is no difference.',
      fields: [{ key: 'low', label: 'Lower bound', type: 'number', value: cur.low }, { key: 'upp', label: 'Upper bound', type: 'number', value: cur.upp }],
      validate: (x) => (x.low != null && x.upp != null && x.low >= 0 && x.low < x.upp && x.upp <= 1 ? null : 'The bounds must satisfy 0 ≤ lower < upper ≤ 1.'),
    });
    if (v) ctx.set('bmTost', { low: v.low, upp: v.upp }, sc);
  }

  /* ---- Compare Rates: Y counts events over an exposure (statsmodels
     test_poisson_2indep, confint_poisson_2indep; not in JMP) -------------- */
  const RATE_TESTS = [['score', 'Score', 'both'], ['wald', 'Wald', 'both'], ['score-log', 'Score, log ratio', 'ratio'], ['wald-log', 'Wald, log ratio', 'ratio'],
    ['sqrt', 'Square root', 'ratio'], ['exact-cond', 'Exact conditional (binomial)', 'ratio'], ['cond-midp', 'Mid-p conditional', 'ratio'],
    ['waldccv', 'Wald, 0.5 added to the variance', 'diff'], ['etest-score', 'E-test (score)', 'both'], ['etest-wald', 'E-test (Wald)', 'both']];
  const RATE_CIS = [['score', 'Score', 'both'], ['score-log', 'Score, log ratio', 'ratio'], ['wald-log', 'Wald, log ratio', 'ratio'], ['waldcc', 'Wald, log ratio, 0.5 added', 'ratio'],
    ['sqrtcc', 'Square root, 0.5 added', 'ratio'], ['exact-cond', 'Exact conditional (Clopper-Pearson)', 'ratio'], ['wald', 'Wald', 'diff'],
    ['waldccv', 'Wald, 0.5 added to the variance', 'diff'], ['mover', 'MOVER (from each rate\'s score interval)', 'both']];
  const rateLabel = (list, key) => (list.find((m) => m[0] === key) || [key, key])[1];
  const forCompare = (list, cmp) => list.filter((m) => m[2] === 'both' || m[2] === cmp);

  function isCountColumn(ctx, y, x) {
    let any = false;
    for (const r of ctx.rows) {
      const v = y.values[r];
      if (!Number.isFinite(v) || isMissing(x.values[r])) continue;
      if (v < 0 || Math.abs(v - Math.round(v)) > 1e-9) return false;
      any = true;
    }
    return any;
  }

  async function ratesDialog(ctx, sc, y, x) {
    const cur = ctx.opt('rates', null, sc) || { exposure: null, compare: 'ratio', method: 'score', ci: 'score', control: null };
    const nums = ctx.table.columns.filter((c) => c.isNumeric && !c.isCategorical && c.id !== y.id && c.id !== x.id);
    const levels = ctx.table.levels(x);
    const tag = (m) => (m[2] === 'both' ? m[1] : `${m[1]} (${m[2] === 'ratio' ? 'ratio' : 'difference'} only)`);
    const ctlIndex = cur.control == null ? '' : String(levels.findIndex((l) => keyOf(l) === keyOf(cur.control)));
    const v = await SM.ui.form({
      title: `Compare Rates: ${y.name} by ${x.name}`, info: 'p:fitybyx:rates',
      lead: `${y.name} counts events; each row is one unit, observed for its exposure (time, person-years, area). Each level's rate is its total count over its total exposure.`,
      fields: [
        { key: 'exposure', label: 'Exposure', type: 'select', value: cur.exposure || '', choices: [['', '(none: every row is one unit)'], ...nums.map((c) => [c.id, c.name])] },
        { key: 'compare', label: 'Compare the rates by their', type: 'select', value: cur.compare, choices: [['ratio', 'Ratio'], ['diff', 'Difference']] },
        { key: 'method', label: 'Test', type: 'select', value: cur.method, choices: RATE_TESTS.map((m) => [m[0], tag(m)]) },
        { key: 'ci', label: 'Confidence interval', type: 'select', value: cur.ci, choices: RATE_CIS.map((m) => [m[0], tag(m)]) },
        { key: 'control', label: 'Levels compared', type: 'select', value: ctlIndex === '-1' ? '' : ctlIndex, choices: [['', 'Each pair (later level against earlier)'], ...levels.map((l, i) => [String(i), `Each level against ${lvText(x, l)}`])] },
      ],
      validate: (f) => {
        const ok = (list, key) => forCompare(list, f.compare).some((m) => m[0] === key);
        if (!ok(RATE_TESTS, f.method)) return `The ${rateLabel(RATE_TESTS, f.method)} test is for a ${f.compare === 'ratio' ? 'difference' : 'ratio'} of rates.`;
        if (!ok(RATE_CIS, f.ci)) return `The ${rateLabel(RATE_CIS, f.ci)} interval is for a ${f.compare === 'ratio' ? 'difference' : 'ratio'} of rates.`;
        return null;
      },
    });
    if (!v) return;
    ctx.set('rates', { exposure: v.exposure || null, compare: v.compare, method: v.method, ci: v.ci, control: v.control === '' ? null : levels[Number(v.control)] }, sc);
  }

  async function ratesReport(ctx, host, sc, base, spec, y, x) {
    const ob = ctx.outline('Compare Rates', { parent: host, key: `rates:${sc}`, info: 'p:fitybyx:rates', menu: () => [
      { label: 'Change…', action: () => ratesDialog(ctx, sc, y, x) }, { label: 'Remove', action: () => ctx.set('rates', null, sc) }] });
    const ex = spec.exposure ? ctx.col(spec.exposure) : null;
    if (spec.exposure && !ex) { ob.add(ctx.warn('The exposure column is no longer in the table.')); return; }
    const { res: r, error } = await safeCall(ctx, 'fitybyx.oneway_rates', { ...base, exposure: ex ? ex.name : null, compare: spec.compare || 'ratio', method: spec.method || 'score', ci_method: spec.ci || 'score', control: spec.control ?? null });
    if (error) { ob.add(problem(ctx, error)); return; }
    const lvl = `${fmt(100 * (1 - ctx.alpha))}%`;
    const nm = (i) => lvText(x, r.level_values[i]);
    ob.add(ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'n', label: 'Units' }, { key: 'count', label: `Total ${y.name}` }, { key: 'exposure', label: ex ? `Total ${ex.name}` : 'Exposure (units)' },
      { key: 'rate', label: 'Rate' }, { key: 'lower', label: `Lower ${lvl}` }, { key: 'upper', label: `Upper ${lvl}` }], rows: r.levels.map((l) => ({ ...l, lv: nm(l.index) })) }, { sortable: false, caption: 'Rates' }),
    ctx.note(`Rate = total ${y.name} / total ${ex ? ex.name : 'units'}, with the exact (Garwood) interval (statsmodels confint_poisson). Not in JMP, whose closest is a Poisson Generalized Linear Model with an offset in Fit Model: its Wald and likelihood-ratio tests, not these exact, score and E-tests of two rates.`));
    const ratio = r.compare === 'ratio';
    const pr = ctx.outline(ratio ? 'Rate Ratios' : 'Rate Differences', { parent: ob, key: `ratep:${sc}` });
    const cols = [{ key: 'a', label: 'Level', fmt: 'text' }, { key: 'b', label: ratio ? '/ Level' : '- Level', fmt: 'text' }, { key: 'estimate', label: ratio ? 'Ratio' : 'Difference' },
      { key: 'lower', label: `Lower ${lvl}` }, { key: 'upper', label: `Upper ${lvl}` }, { key: 'stat', label: 'Z' }, { key: 'p', label: 'Prob>|Z|', fmt: 'p' },
      { key: 'p_greater', label: 'Prob>Z', fmt: 'p', hidden: true }, { key: 'p_less', label: 'Prob<Z', fmt: 'p', hidden: true }];
    if (r.pairs.some((p) => p.p_holm != null)) cols.push({ key: 'p_holm', label: 'Holm-adjusted p', fmt: 'p', hidden: true });
    pr.add(ctx.rt({ columns: cols, rows: r.pairs.map((p) => ({ ...p, a: nm(p.i), b: nm(p.j) })) }, { sortable: r.pairs.length > 2 }),
      ctx.note(`Test: ${rateLabel(RATE_TESTS, r.method)}; interval: ${rateLabel(RATE_CIS, r.ci_method)} (statsmodels test_poisson_2indep and confint_poisson_2indep; the exact conditional test has no Z). Prob>Z is for ${ratio ? 'a ratio above 1' : 'a difference above 0'}; right click for it and the other one-sided p-value.`));
    if (r.lr) {
      const lo = ctx.outline('Likelihood Ratio Test', { parent: ob, key: `ratel:${sc}` });
      lo.add(ctx.rt({ columns: [{ key: 'source', label: 'Source', fmt: 'text' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'chisq', label: 'L-R ChiSquare' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }],
        rows: [{ ...r.lr, source: x.name }] }, { sortable: false }), ctx.kv([['Pearson χ²/DF (dispersion)', r.lr.dispersion]]),
      ctx.note(`A Poisson GLM with the log ${ex ? ex.name : 'exposure'} as offset: a rate for each level against one rate for all. A dispersion well above 1 means the counts vary more than a Poisson allows.`));
    }
    ob.add(notesOf(ctx, r.notes), ctx.code(r.code));
  }

  async function powerReport(ctx, host, sc, base, pw) {
    const ob = ctx.outline('Power Details', { parent: host, key: `pw:${sc}`, menu: () => [{ label: 'Remove', action: () => ctx.set('power', null, sc) }, { label: 'Change…', action: () => powerDialog(ctx, sc, pw) }] });
    const { res: r, error } = await safeCall(ctx, 'fitybyx.oneway_power', { ...base, alpha: pw.alpha ?? ctx.alpha, sigma: pw.sigma ?? null, delta: pw.delta ?? null, nobs: pw.nobs && pw.nobs.length ? pw.nobs : null });
    if (error) { ob.add(problem(ctx, error)); return; }
    ob.add(ctx.rt({ columns: [{ key: 'alpha', label: 'Alpha' }, { key: 'sigma', label: 'Sigma' }, { key: 'delta', label: 'Delta' }, { key: 'n', label: 'Number' }, { key: 'power', label: 'Power' }], rows: r.rows }, { sortable: false }),
      ctx.kv([['Least Significant Number (LSN)', r.lsn], ['Least Significant Value (LSV)', r.lsv], ['Number for power 0.8', r.n80]]),
      ctx.note('Power of the one-way F test from the noncentral F with λ = N·δ²/σ² (statsmodels FTestAnovaPower, effect size δ/σ). δ defaults to the standard deviation of the level effects, √(Σ nᵢ(meanᵢ − mean)²/N), σ to the RMSE. LSN is the number of observations at which the F test with this δ and σ would just be significant.'),
      ctx.code(r.code));
  }

  async function powerDialog(ctx, sc, cur = {}) {
    const v = await ask('Power Details', [
      { key: 'alpha', label: 'Alpha', type: 'number', value: cur.alpha ?? ctx.alpha },
      { key: 'sigma', label: 'Sigma (empty: the RMSE)', type: 'number', value: cur.sigma ?? null },
      { key: 'delta', label: 'Delta (empty: the observed effect size)', type: 'number', value: cur.delta ?? null },
      { key: 'nobs', label: 'Numbers of observations, separated by commas (empty: the observed N)', value: (cur.nobs || []).join(', ') },
    ], 'The power of the one-way ANOVA F test for an effect of size δ with error standard deviation σ.');
    if (!v) return;
    const nobs = String(v.nobs || '').split(/[,;\s]+/).map(Number).filter((z) => z > 0);
    ctx.set('power', { alpha: v.alpha > 0 && v.alpha < 1 ? v.alpha : null, sigma: v.sigma > 0 ? v.sigma : null, delta: v.delta > 0 ? v.delta : null, nobs }, sc);
  }

  async function owAnom(ctx, host, sc, base, names) {
    const ob = ctx.outline('Analysis of Means', { parent: host, key: `anom:${sc}` });
    const { res: r, error } = await safeCall(ctx, 'fitybyx.oneway_anom', base);
    if (error) { ob.add(problem(ctx, error)); return; }
    const L = r.levels;
    const xs = L.map((_, i) => i);
    const step = (key) => { const X = [], Y = []; L.forEach((l, i) => { X.push(i - 0.5, i + 0.5, null); Y.push(l[key], l[key], null); }); return { X, Y }; };
    const lo = step('ldl'), hi = step('udl');
    ob.add(ctx.plot([
      { type: 'scatter', mode: 'lines', x: lo.X, y: lo.Y, line: { color: RED, width: 1.2 }, hoverinfo: 'skip', name: 'LDL' },
      { type: 'scatter', mode: 'lines', x: hi.X, y: hi.Y, line: { color: RED, width: 1.2 }, hoverinfo: 'skip', name: 'UDL' },
      { type: 'scatter', mode: 'lines+markers', x: xs, y: L.map((l) => l.mean), marker: { size: 8, color: L.map((l) => (l.out ? RED : SM.report.BASE)) }, line: { color: GREY, width: 1 }, text: names, hovertemplate: '%{text}: %{y}<extra></extra>', name: 'Means' },
    ], { xaxis: { tickvals: xs, ticktext: names, range: [-0.6, L.length - 0.4] }, yaxis: { title: { text: 'Mean' } }, shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: r.grand_mean, y1: r.grand_mean, line: { color: GREY, width: 1 } }] }, { width: availWidth(ctx, Math.max(360, 120 + 60 * L.length)), height: 280, title: 'Analysis of Means' }));
    ob.add(ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'n', label: 'Number' }, { key: 'mean', label: 'Mean' }, { key: 'ldl', label: 'Lower Decision Limit' }, { key: 'udl', label: 'Upper Decision Limit' }, { key: 'flag', label: 'Outside', fmt: 'text' }],
      rows: L.map((l) => ({ ...l, lv: names[l.index], flag: l.out ? 'yes' : '' })) }, { sortable: false }),
    ctx.kv([['Grand Mean', r.grand_mean], ['h (exact)', r.h], ['Alpha', r.alpha], ['Std Dev (pooled)', r.s], ['DF', r.df]]),
    ctx.note('Decision limits: grand mean ± h·s·√((N − nᵢ)/(N nᵢ)). h is exact: the 1 − α point of the largest |Tᵢ| of the multivariate t of the ANOM statistics (scipy.stats.multivariate_t, quasi-Monte Carlo with a fixed seed).'),
    notesOf(ctx, r.notes), ctx.code(r.code));
  }

  function owNormalQuantile(ctx, host, sc, P, code, names, mode, levels) {
    const ob = ctx.outline('Normal Quantile Plot', { parent: host, key: `nqp:${sc}`, menu: () => [
      { label: 'Plot Actual by Quantile', checked: mode.orient !== 'qa', action: () => ctx.set('nqp', { ...mode, orient: 'aq' }, sc) },
      { label: 'Plot Quantile by Actual', checked: mode.orient === 'qa', action: () => ctx.set('nqp', { ...mode, orient: 'qa' }, sc) },
      { label: 'Line of Fit', checked: mode.line !== false, action: () => ctx.set('nqp', { ...mode, line: mode.line === false }, sc) },
      { separator: true }, { label: 'Remove', action: () => ctx.set('nqp', null, sc) }] });
    const traces = [];
    const qa = mode.orient === 'qa';
    names.forEach((nm, i) => {
      const idx = P.rows.map((_, kk) => kk).filter((kk) => code[kk] === i).sort((a, b) => P.yv[a] - P.yv[b]);
      const nn = idx.length;
      if (!nn) return;
      const z = idx.map((_, j) => qnorm((j + 1) / (nn + 1)));
      const v = idx.map((kk) => P.yv[kk]);
      const color = PALETTE[i % PALETTE.length];
      traces.push({ type: 'scatter', mode: 'markers', x: qa ? v : z, y: qa ? z : v, rows: idx.map((kk) => P.rows[kk]), marker: { color, size: 5 }, name: nm, showlegend: true });
      if (mode.line !== false && nn > 1) {
        const m = v.reduce((a, b) => a + b, 0) / nn;
        const s = Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / (nn - 1));
        const z0 = z[0], z1 = z[nn - 1];
        traces.push({ type: 'scatter', mode: 'lines', x: qa ? [m + s * z0, m + s * z1] : [z0, z1], y: qa ? [z0, z1] : [m + s * z0, m + s * z1], line: { color, width: 1.2 }, hoverinfo: 'skip', showlegend: false });
      }
    });
    ob.add(ctx.plot(traces, { xaxis: { title: { text: qa ? 'Actual' : 'Normal Quantile' } }, yaxis: { title: { text: qa ? 'Normal Quantile' : 'Actual' } }, showlegend: true, legend: { orientation: 'h', y: -0.25 } }, { width: availWidth(ctx, 460), height: 340, title: 'Normal Quantile Plot' }),
      ctx.note('Each level\'s values against Φ⁻¹(r/(n+1)); the lines are the normal with the level\'s mean and standard deviation.'));
  }

  function owCdf(ctx, host, sc, P, code, names) {
    const ob = ctx.outline('CDF Plot', { parent: host, key: `cdf:${sc}`, menu: () => [{ label: 'Remove', action: () => ctx.set('cdf', false, sc) }] });
    const traces = names.map((nm, i) => {
      const idx = P.rows.map((_, kk) => kk).filter((kk) => code[kk] === i).sort((a, b) => P.yv[a] - P.yv[b]);
      const tot = idx.reduce((a, kk) => a + P.wv[kk], 0);
      let acc = 0;
      return { type: 'scatter', mode: 'lines+markers', x: idx.map((kk) => P.yv[kk]), y: idx.map((kk) => { acc += P.wv[kk]; return acc / tot; }), rows: idx.map((kk) => P.rows[kk]), line: { shape: 'hv', color: PALETTE[i % PALETTE.length], width: 1.4 }, marker: { size: 4, color: PALETTE[i % PALETTE.length] }, name: nm, showlegend: true };
    });
    ob.add(ctx.plot(traces, { xaxis: { title: { text: ctx.name('y') || '' } }, yaxis: { title: { text: 'Cumulative Probability' }, range: [0, 1.02] }, showlegend: true, legend: { orientation: 'h', y: -0.25 } }, { width: availWidth(ctx, 460), height: 320, title: 'CDF Plot' }));
  }

  async function owDensities(ctx, host, sc, base, names, mode, y) {
    const ob = ctx.outline('Densities', { parent: host, key: `dens:${sc}`, menu: () => [
      ...[['compare', 'Compare Densities'], ['composition', 'Composition of Densities'], ['proportion', 'Proportion of Densities']].map(([k, l]) => ({ label: l, checked: mode === k, action: () => ctx.set('densities', k, sc) })),
      { separator: true }, { label: 'Remove', action: () => ctx.set('densities', null, sc) }] });
    const { res: r, error } = await safeCall(ctx, 'fitybyx.oneway_densities', base);
    if (error) { ob.add(problem(ctx, error)); return; }
    const L = r.levels.filter((l) => l.density);
    const traces = [];
    if (mode === 'compare') L.forEach((l) => traces.push({ type: 'scatter', mode: 'lines', x: r.x, y: l.density, line: { color: PALETTE[l.index % PALETTE.length], width: 1.6 }, name: names[l.index] }));
    else {
      const tot = r.x.map((_, j) => L.reduce((a, l) => a + l.share * l.density[j], 0));
      L.forEach((l) => traces.push({ type: 'scatter', mode: 'lines', stackgroup: 'd', x: r.x, y: l.density.map((d, j) => (mode === 'proportion' ? (tot[j] > 0 ? l.share * d / tot[j] : 0) : l.share * d)), line: { color: PALETTE[l.index % PALETTE.length], width: 1 }, name: names[l.index] }));
    }
    ob.add(ctx.plot(traces, { xaxis: { title: { text: y.name } }, yaxis: { title: { text: mode === 'proportion' ? 'Proportion' : 'Density' }, rangemode: 'tozero' }, showlegend: true, legend: { orientation: 'h', y: -0.25 } }, { width: availWidth(ctx, 480), height: 320, title: 'Densities', select: false }),
      ctx.note('Gaussian kernel densities of each level (scipy.stats.gaussian_kde); Composition stacks them weighted by the levels\' shares, Proportion shows each level\'s share at each value.'), ctx.code(r.code));
  }

  function owMenu(ctx, sc, y, x) {
    const k = (() => { const lv = new Set(); for (const r of ctx.rows) { const v = x.values[r]; if (!isMissing(v) && !isMissing(y.values[r])) lv.add(keyOf(v)); } return lv.size; })();
    const levels = ctx.table.levels(x);
    const listToggle = (key, item, eq = (a, b) => a === b) => {
      const cur = ctx.opt(key, [], sc);
      return cur.some((z) => eq(z, item)) ? cur.filter((z) => !eq(z, item)) : [...cur, item];
    };
    const has = (key, pred) => ctx.opt(key, [], sc).some(pred);
    const askControl = async (title) => {
      const v = await ask(title, [{ key: 'c', label: 'Control level', type: 'select', value: 0, choices: levels.map((l, i) => [String(i), lvText(x, l)]) }]);
      return v ? levels[Number(v.c)] : undefined;
    };
    const cmpItem = (label, method, control) => ({
      label, checked: has('compare', (z) => z.method === method),
      action: async () => {
        if (has('compare', (z) => z.method === method)) { ctx.set('compare', ctx.opt('compare', [], sc).filter((z) => z.method !== method), sc); return; }
        let c = null;
        if (control) { c = await askControl('With Control, Dunnett\'s'); if (c === undefined) return; }
        ctx.set('compare', [...ctx.opt('compare', [], sc), { method, control: c }], sc);
      },
    });
    const npmcItem = (label, method, control) => ({
      label, checked: has('npmc', (z) => z.method === method),
      action: async () => {
        if (has('npmc', (z) => z.method === method)) { ctx.set('npmc', ctx.opt('npmc', [], sc).filter((z) => z.method !== method), sc); return; }
        let c = null;
        if (control) { c = await askControl(label); if (c === undefined) return; }
        ctx.set('npmc', [...ctx.opt('npmc', [], sc), { method, control: c }], sc);
      },
    });
    const withAnova = () => { ctx.set('diamonds', !ctx.opt('anova', false, sc), sc, { rerun: false }); ctx.toggle('anova', sc, false); };
    const withMeansd = () => { const on = !ctx.opt('meansd', false, sc); for (const key of ['meanLines', 'errorBars', 'sdLines']) ctx.set(key, on, sc, { rerun: false }); ctx.set('meansd', on, sc); };
    const withQuantiles = () => { const on = !ctx.opt('quantiles', false, sc); ctx.set('box', on, sc, { rerun: false }); ctx.set('quantiles', on, sc); };
    const np = (label, t, dis) => ({ label, checked: ctx.opt('np', [], sc).includes(t), disabled: dis, action: () => ctx.set('np', listToggle('np', t), sc) });
    const saveCol = (kind) => oneSave(ctx, sc, y, x, kind);
    // Effect Size goes with Means/Anova and the t tests: on its own it turns Means/Anova on
    const withEffect = () => {
      const on = !ctx.opt('effect', false, sc);
      if (on && !ctx.opt('anova', false, sc) && !ctx.opt('ttest', false, sc)) { ctx.set('diamonds', true, sc, { rerun: false }); ctx.set('anova', true, sc, { rerun: false }); }
      ctx.set('effect', on, sc);
    };
    return [
      { label: 'Quantiles', checked: ctx.opt('quantiles', false, sc), action: withQuantiles },
      { label: k === 2 ? 'Means/Anova/Pooled t' : 'Means/Anova', checked: ctx.opt('anova', false, sc), action: withAnova },
      { label: 'Means and Std Dev', checked: ctx.opt('meansd', false, sc), action: withMeansd },
      ctx.check('t Test', 'ttest', sc, false, { disabled: k !== 2 }),
      { label: 'Effect Size', checked: ctx.opt('effect', false, sc), action: withEffect },
      { label: 'Bayes Factor…', checked: !!ctx.opt('bf', null, sc), disabled: k !== 2 || !!(ctx.role('block') && ctx.role('block').isCategorical), action: () => priorDialog(ctx, sc, 'bf', 'Bayes Factor: two-sample t test') },
      { label: 'Analysis of Means Methods', submenu: [ctx.check('ANOM', 'anom', sc, false)] },
      { label: 'Compare Means', submenu: () => [cmpItem('Each Pair, Student\'s t', 'student'), cmpItem('All Pairs, Tukey HSD', 'tukey'), cmpItem('All Pairs, Games-Howell', 'gameshowell'), cmpItem('With Control, Dunnett\'s…', 'dunnett', true)] },
      { label: 'Nonparametric', submenu: () => [
        np('Wilcoxon / Kruskal-Wallis Tests', 'wilcoxon'), np('Median Test', 'median'), np('van der Waerden Test', 'vdw'), np('Kolmogorov-Smirnov Test', 'ks', k !== 2),
        ctx.check('Brunner-Munzel Test', 'bm', sc, false),
        { label: 'Nonparametric Multiple Comparisons', submenu: () => [npmcItem('Wilcoxon Each Pair', 'wilcoxon'), npmcItem('Steel-Dwass All Pairs', 'steel_dwass'), npmcItem('Steel With Control…', 'steel_control', true),
          npmcItem('Dunn With Control for Joint Ranks…', 'dunn_control', true), npmcItem('Dunn All Pairs for Joint Ranks', 'dunn_all')] },
      ] },
      ctx.check('Unequal Variances', 'unequal', sc, false),
      { label: 'Compare Rates…', checked: !!ctx.opt('rates', null, sc), disabled: !isCountColumn(ctx, y, x), action: () => ratesDialog(ctx, sc, y, x) },
      { label: 'Equivalence Test', submenu: [{ label: 'Means…', checked: !!ctx.opt('equiv', null, sc), action: async () => { const v = await ask('Equivalence Test', [{ key: 'd', label: 'Difference considered practically zero', type: 'number', value: (ctx.opt('equiv', null, sc) || {}).delta ?? null }]); if (v && v.d > 0) ctx.set('equiv', { delta: v.d }, sc); } },
        { label: 'Probability of Superiority…', checked: !!ctx.opt('bmTost', null, sc), action: () => brunnerTostDialog(ctx, sc) }] },
      { label: 'Power…', checked: !!ctx.opt('power', null, sc), action: () => powerDialog(ctx, sc, ctx.opt('power', null, sc) || {}) },
      { label: 'Set α Level', submenu: () => alphaMenu(ctx) },
      { separator: true },
      { label: 'Normal Quantile Plot', submenu: () => [{ label: 'Plot Actual by Quantile', checked: !!ctx.opt('nqp', null, sc) && ctx.opt('nqp', {}, sc).orient !== 'qa', action: () => ctx.set('nqp', { orient: 'aq' }, sc) },
        { label: 'Plot Quantile by Actual', checked: !!ctx.opt('nqp', null, sc) && ctx.opt('nqp', {}, sc).orient === 'qa', action: () => ctx.set('nqp', { orient: 'qa' }, sc) }] },
      ctx.check('CDF Plot', 'cdf', sc, false),
      { label: 'Densities', submenu: () => [['compare', 'Compare Densities'], ['composition', 'Composition of Densities'], ['proportion', 'Proportion of Densities']].map(([kk, l]) => ({ label: l, checked: ctx.opt('densities', null, sc) === kk, action: () => ctx.set('densities', ctx.opt('densities', null, sc) === kk ? null : kk, sc) })) },
      { label: 'Save', submenu: [{ label: 'Save Centered', action: () => saveCol('centered') }, { label: 'Save Normal Quantiles', action: () => saveCol('nquantile') }, { label: 'Save Standardized', action: () => saveCol('standardized') }, { label: 'Save Predicted', action: () => saveCol('predicted') }] },
      { label: 'Display Options', submenu: () => [
        ctx.check('Points', 'points', sc, true), ctx.check('Box Plots', 'box', sc, ctx.opt('quantiles', false, sc)), ctx.check('Mean Diamonds', 'diamonds', sc, ctx.opt('anova', false, sc)),
        ctx.check('Mean Lines', 'meanLines', sc, ctx.opt('meansd', false, sc)), ctx.check('Mean CI Lines', 'ciLines', sc, false), ctx.check('Mean Error Bars', 'errorBars', sc, ctx.opt('meansd', false, sc)),
        ctx.check('Grand Mean', 'grandMean', sc, false), ctx.check('Std Dev Lines', 'sdLines', sc, ctx.opt('meansd', false, sc)), ctx.check('Comparison Circles', 'circles', sc, true),
        ctx.check('Connect Means', 'connect', sc, false), ctx.check('Points Jittered', 'jitter', sc, true),
      ] },
    ];
  }

  /* Oneway's Save: from the values in the page (the level means and
     standard deviations of the rows used, Freq counted). */
  function oneSave(ctx, sc, y, x, kind) {
    const blockCol = ctx.role('block');
    const P = pointsOf(ctx, y, x, blockCol && blockCol.isCategorical ? [blockCol] : []);
    const f = ctx.role('freq');
    const groups = new Map();
    P.rows.forEach((r, i) => { const key = keyOf(P.xv[i]); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(i); });
    const vals = new Array(P.rows.length);
    for (const idx of groups.values()) {
      const fw = idx.map((i) => (f ? f.values[P.rows[i]] : 1));
      const nn = fw.reduce((a, b) => a + b, 0);
      const m = idx.reduce((a, i, j) => a + fw[j] * P.yv[i], 0) / nn;
      const s = Math.sqrt(idx.reduce((a, i, j) => a + fw[j] * (P.yv[i] - m) ** 2, 0) / (nn - 1));
      const order = idx.slice().sort((a, b) => P.yv[a] - P.yv[b]);
      const rk = new Map(order.map((i, j) => [i, j + 1]));
      for (const i of idx) {
        if (kind === 'centered') vals[i] = P.yv[i] - m;
        else if (kind === 'standardized') vals[i] = (P.yv[i] - m) / s;
        else if (kind === 'predicted') vals[i] = m;
        else vals[i] = qnorm(rk.get(i) / (idx.length + 1));
      }
    }
    const name = { centered: `${y.name} centered by ${x.name}`, standardized: `${y.name} std by ${x.name}`, predicted: `${y.name} mean by ${x.name}`, nquantile: `N-Quantile ${y.name} by ${x.name}` }[kind];
    ctx.saveColumn(name, { rows: P.rows, values: vals });
  }

  /* ======================================================================
     LOGISTIC
     ====================================================================== */
  function probsAt(model, xv) {
    if (model.kind === 'binary') { const p0 = 1 / (1 + Math.exp(-(model.coef[0] + model.coef[1] * xv))); return [p0, 1 - p0]; }
    if (model.kind === 'nominal') {
      const eta = model.coef.map(([a, b]) => a + b * xv).concat([0]);
      const mx = Math.max(...eta);
      const e = eta.map((v) => Math.exp(v - mx));
      const s = e.reduce((a, b) => a + b, 0);
      return e.map((v) => v / s);
    }
    const cum = model.alpha.map((a) => 1 / (1 + Math.exp(-(a + model.beta * xv)))).concat([1]);
    return cum.map((c, j) => c - (j ? cum[j - 1] : 0));
  }

  async function logistic(ctx, y, x, host, sc) {
    const o = (k, d) => ctx.opt(k, d, sc);
    const base = basePayload(ctx, y, x);
    const { res, error } = await safeCall(ctx, 'fitybyx.logistic', { ...base, target: o('target', null) });
    if (error) { host.add(problem(ctx, error)); return; }
    const k = res.k;
    const names = res.levels.map((l) => lvText(y, l));
    const lmap = new Map(res.levels.map((l, i) => [keyOf(l), i]));
    const P = pointsOf(ctx, y, x);
    if (o('lplot', true)) {
      const traces = [];
      const n = P.rows.length;
      const py = P.rows.map((r, i) => {
        const j = lmap.get(keyOf(P.yv[i]));
        if (j == null) return null;
        const p = probsAt(res.model, P.xv[i]);
        let lo = 0;
        for (let m = 0; m < j; m++) lo += p[m];
        const hi = lo + p[j];
        return lo + (0.06 + 0.88 * jit(r, 3)) * (hi - lo);
      });
      traces.push({ type: n > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: P.xv, y: py, rows: P.rows, marker: { size: n > 3000 ? 4 : 6, color: P.yv.map((v) => { const j = lmap.get(keyOf(v)); return PALETTE[(j ?? 0) % PALETTE.length]; }) }, name: 'Points', showlegend: false });
      res.curve.cum.forEach((c, j) => traces.push({ type: 'scatter', mode: 'lines', x: res.curve.x, y: c, line: { color: SM.util.themeColors().text, width: 1.6 }, hovertemplate: `P(${y.name} ≤ ${names[j]}) = %{y:.3f} at %{x}<extra></extra>`, showlegend: false }));
      // the level names at the right, in their bands
      const xr = res.x_range[1];
      const pr = probsAt(res.model, xr);
      let acc = 0;
      // each level's name beside its band, at least a line apart
      const mids = names.map((_, j) => { const m = acc + pr[j] / 2; acc += pr[j]; return m; });
      const gapY = 0.045;
      for (let j = 1; j < mids.length; j++) mids[j] = Math.max(mids[j], mids[j - 1] + gapY);
      const over = mids.length ? mids[mids.length - 1] - (1 - gapY / 2) : 0;
      if (over > 0) for (let j = mids.length - 1; j >= 0; j--) mids[j] = Math.min(mids[j] - (j === mids.length - 1 ? over : 0), j < mids.length - 1 ? mids[j + 1] - gapY : 1);
      const ann = names.map((nm, j) => ({ x: 1.01, xref: 'paper', y: Math.max(0.01, mids[j]), yref: 'y', text: nm, showarrow: false, xanchor: 'left', font: { size: 10.5, color: PALETTE[j % PALETTE.length] } }));
      host.add(ctx.plot(traces, { xaxis: { title: { text: x.name } }, yaxis: { title: { text: y.name }, range: [0, 1] }, annotations: ann, margin: { l: 60, r: 80, t: 10, b: 44 } }, { width: availWidth(ctx, 560), height: 380, title: `${y.name} by ${x.name} logistic plot` }));
    }
    const wm = ctx.outline('Whole Model Test', { parent: host, key: `wm:${sc}`, info: 'p:fitybyx:logistic' });
    wm.add(ctx.rt({ columns: [{ key: 'model', label: 'Model', fmt: 'text' }, { key: 'nll', label: '-LogLikelihood' }, { key: 'df', label: 'DF' }, { key: 'chisq', label: 'ChiSquare' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: res.whole }, { sortable: false }),
      ctx.kv([['RSquare (U)', res.rsquare_u], ['AICc', res.aicc], ['BIC', res.bic], ['Observations (or Sum Wgts)', res.n]]));
    ctx.outline('Fit Details', { parent: host, key: `fd:${sc}`, closed: true }).add(ctx.rt({ columns: [{ key: 'measure', label: 'Measure', fmt: 'text' }, { key: 'value', label: 'Training' }], rows: res.details }, { sortable: false }));
    const pe = ctx.outline('Parameter Estimates', { parent: host, key: `pe:${sc}` });
    const odds = (j) => (res.kind === 'binary' ? `For log odds of ${names[0]}/${names[1]}` : res.kind === 'nominal' ? `For log odds of ${names[j]}/${names[k - 1]}` : `For the cumulative logits, logit P(${y.name} ≤ level) = Intercept[level] + b·${x.name}`);
    const lvl = `${fmt(100 * (1 - ctx.alpha))}%`;
    const cols = [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'chisq', label: 'ChiSquare' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }, { key: 'lower', label: `Lower ${lvl}`, hidden: true }, { key: 'upper', label: `Upper ${lvl}`, hidden: true }];
    if (res.kind === 'nominal') {
      for (let j = 0; j < k - 1; j++) pe.add(ctx.rt({ columns: cols, rows: res.estimates.filter((e) => e.group === j) }, { sortable: false, caption: odds(j) }));
    } else {
      pe.add(ctx.rt({ columns: cols, rows: res.estimates }, { sortable: false }), ctx.note(res.kind === 'binary' ? `For log odds of ${names[res.target]}/${names[1 - res.target]}` : odds(0)));
    }
    pe.add(ctx.note('ChiSquare is the Wald statistic (estimate/SE)²; the Whole Model Test is the likelihood ratio test.'), notesOf(ctx, res.notes), ctx.code(res.code));
    if (o('odds', false)) {
      const ob = ctx.outline('Odds Ratios', { parent: host, key: `or:${sc}` });
      const grp = (g) => (g == null ? '' : res.kind === 'binary' ? `${names[res.target]}/${names[1 - res.target]}` : `${names[g]}/${names[k - 1]}`);
      ob.add(ctx.rt({ columns: [{ key: 'g', label: 'Log odds of', fmt: 'text' }, { key: 'unit', label: 'Odds Ratio' }, { key: 'unit_lower', label: `Lower ${lvl}` }, { key: 'unit_upper', label: `Upper ${lvl}` }, { key: 'recip', label: 'Reciprocal' }],
        rows: res.odds.map((q) => ({ ...q, g: grp(q.group), recip: 1 / q.unit })) }, { sortable: false, caption: `Unit Odds Ratios: per unit change in ${x.name}` }),
      ctx.rt({ columns: [{ key: 'g', label: 'Log odds of', fmt: 'text' }, { key: 'range', label: 'Odds Ratio' }, { key: 'range_lower', label: `Lower ${lvl}` }, { key: 'range_upper', label: `Upper ${lvl}` }, { key: 'recip', label: 'Reciprocal' }],
        rows: res.odds.map((q) => ({ ...q, g: grp(q.group), recip: 1 / q.range })) }, { sortable: false, caption: `Range Odds Ratios: per change of ${fmt(res.odds[0] ? res.odds[0].range_width : null)} in ${x.name} (its range)` }),
      ctx.note('Wald intervals: exp(b ± z·SE).'));
    }
    const inv = o('inverse', null);
    if (inv && res.kind === 'binary') {
      const ob = ctx.outline('Inverse Prediction', { parent: host, key: `ip:${sc}`, menu: () => [{ label: 'Remove', action: () => ctx.set('inverse', null, sc) }] });
      const { res: r, error: e2 } = await safeCall(ctx, 'fitybyx.logistic_inverse', { ...base, probs: inv, target: o('target', null) });
      if (e2) ob.add(problem(ctx, e2));
      else ob.add(ctx.rt({ columns: [{ key: 'p', label: 'Probability' }, { key: 'x', label: `Predicted ${x.name}` }, { key: 'lower', label: `Lower ${lvl}` }, { key: 'upper', label: `Upper ${lvl}` }], rows: r.rows }, { sortable: false }),
        ctx.note(`The ${x.name} at which P(${names[r.target]}) is the given probability; Fieller's confidence limits (missing where the slope is not significantly different from zero).`), ctx.code(r.code));
    }
    if (o('roc', false)) {
      const ob = ctx.outline('ROC Curve', { parent: host, key: `roc:${sc}` });
      const traces = res.roc.map((r) => ({ type: 'scatter', mode: 'lines', x: r.fpr, y: r.tpr, line: { color: PALETTE[r.level % PALETTE.length], width: 1.8, shape: 'linear' }, name: `${names[r.level]} (AUC ${r.auc.toFixed(4)})` }));
      traces.push({ type: 'scatter', mode: 'lines', x: [0, 1], y: [0, 1], line: { color: GREY, width: 1, dash: 'dot' }, hoverinfo: 'skip', showlegend: false });
      ob.add(ctx.row(ctx.plot(traces, { xaxis: { title: { text: '1-Specificity (False Positive Rate)' }, range: [0, 1] }, yaxis: { title: { text: 'Sensitivity (True Positive Rate)' }, range: [0, 1] }, showlegend: true, legend: { orientation: 'h', y: -0.28 } }, { width: availWidth(ctx, 360), height: 360, title: 'ROC Curve', select: false }),
        ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'auc', label: 'Area Under Curve' }], rows: res.roc.map((r) => ({ lv: names[r.level], auc: r.auc })) }, { sortable: false })),
      ctx.note(k === 2 ? `Sensitivity and 1 − specificity of classifying ${names[res.target]} by its fitted probability, over every cutoff.` : 'Each level against the rest, by its fitted probability.'));
    }
    if (o('lift', false)) {
      const ob = ctx.outline('Lift Curve', { parent: host, key: `lift:${sc}` });
      ob.add(ctx.plot(res.lift.map((l) => ({ type: 'scatter', mode: 'lines', x: l.portion, y: l.lift, line: { color: PALETTE[l.level % PALETTE.length], width: 1.6 }, name: names[l.level] }))
        .concat([{ type: 'scatter', mode: 'lines', x: [0, 1], y: [1, 1], line: { color: GREY, width: 1, dash: 'dot' }, hoverinfo: 'skip', showlegend: false }]),
      { xaxis: { title: { text: 'Portion' }, range: [0, 1] }, yaxis: { title: { text: 'Lift' }, rangemode: 'tozero' }, showlegend: true, legend: { orientation: 'h', y: -0.28 } }, { width: availWidth(ctx, 420), height: 320, title: 'Lift Curve', select: false }),
      ctx.note('The rate of the level among the rows with the highest fitted probabilities, divided by its overall rate.'));
    }
    if (o('confusion', false)) {
      const ob = ctx.outline('Confusion Matrix', { parent: host, key: `cm:${sc}` });
      const cols2 = [{ key: 'actual', label: 'Actual \\ Predicted', fmt: 'text' }, ...names.map((nm, j) => ({ key: `p${j}`, label: nm }))];
      ob.add(ctx.rt({ columns: cols2, rows: res.confusion.map((row, i) => { const r = { actual: names[i] }; row.forEach((v, j) => { r[`p${j}`] = v; }); return r; }) }, { sortable: false }),
        ctx.note('Each row\'s most likely level against its actual level.'));
    }
  }

  function logMenu(ctx, sc, y, x) {
    const levels = (() => { const set = new Set(); for (const r of ctx.rows) { const v = y.values[r]; if (!isMissing(v) && !isMissing(x.values[r])) set.add(keyOf(v)); } return ctx.table.levels(y).filter((v) => set.has(keyOf(v))); })();
    const binary = levels.length === 2;
    return [
      ctx.check('Logistic Plot', 'lplot', sc, true),
      ctx.check('Odds Ratios', 'odds', sc, false),
      { label: 'Inverse Prediction…', disabled: !binary, checked: !!ctx.opt('inverse', null, sc), action: async () => { const v = await ask('Inverse Prediction', [{ key: 'p', label: 'Probabilities, separated by commas', value: (ctx.opt('inverse', null, sc) || [0.5]).join(', ') }]); if (v) { const ps = String(v.p).split(/[,;\s]+/).map(Number).filter((p) => p > 0 && p < 1); ctx.set('inverse', ps.length ? ps : null, sc); } } },
      ctx.check('ROC Curve', 'roc', sc, false),
      ctx.check('Lift Curve', 'lift', sc, false),
      ctx.check('Confusion Matrix', 'confusion', sc, false),
      { label: 'Target Level', disabled: !binary, submenu: () => levels.map((l, i) => ({ label: lvText(y, l), checked: (ctx.opt('target', null, sc) == null ? i === 0 : keyOf(ctx.opt('target', null, sc)) === keyOf(l)), action: () => ctx.set('target', i === 0 ? null : l, sc) })) },
      { label: 'Set α Level', submenu: () => alphaMenu(ctx) },
      { separator: true },
      { label: 'Save Probability Formula', action: async () => {
        const r = await ctx.call('fitybyx.logistic_rows', { ...basePayload(ctx, y, x), target: ctx.opt('target', null, sc) });
        if (r.error) { SM.ui.toast(r.error, { error: true }); return; }
        r.levels.forEach((l, j) => ctx.saveColumn(`Prob[${lvText(y, l)}]`, { rows: r.rows, values: r.probs[j] }));
        ctx.saveColumn(`Most Likely ${y.name}`, { rows: r.rows, values: r.most_likely.map((j) => lvText(y, r.levels[j])) }, { dataType: 'character', modelingType: 'nominal' });
      } },
    ];
  }

  /* ======================================================================
     CONTINGENCY
     ====================================================================== */
  const CELLS = [['count', 'Count'], ['total', 'Total %'], ['col', 'Col %'], ['row', 'Row %'], ['expected', 'Expected'], ['deviation', 'Deviation'], ['cellchi', 'Cell Chi^2']];

  function mosaic(ctx, res, y, x, P) {
    const xl = res.x_levels, yl = res.y_levels;
    const R = xl.length, C = yl.length;
    const n = res.counts;
    const rowT = n.map((r) => r.reduce((a, b) => a + b, 0));
    const N = res.n;
    const xi = new Map(xl.map((v, i) => [keyOf(v), i]));
    const yi = new Map(yl.map((v, j) => [keyOf(v), j]));
    const cellRows = xl.map(() => yl.map(() => []));
    const colRows = yl.map(() => []);
    P.rows.forEach((r, k) => { const i = xi.get(keyOf(P.xv[k])), j = yi.get(keyOf(P.yv[k])); if (i == null || j == null) return; cellRows[i][j].push(r); colRows[j].push(r); });
    const gap = 0.012;
    const avail = 1 - gap * (R - 1);
    const traces = [];
    let start = 0;
    const centers = [];
    xl.forEach((xv, i) => {
      const w = avail * rowT[i] / N;
      const cx = start + w / 2;
      centers.push(cx);
      let base = 0;
      yl.forEach((yv, j) => {
        const h = rowT[i] > 0 ? n[i][j] / rowT[i] : 0;
        const rs = cellRows[i][j];
        traces.push({ type: 'bar', x: [cx], y: [h], base: [base], width: w, rows: [rs], rowsScale: rs.length ? h / rs.length : 1, marker: { color: PALETTE[j % PALETTE.length], line: { color: SM.util.themeColors().surface, width: 1 } },
          hovertemplate: `${lvText(x, xv)}, ${lvText(y, yv)}: ${fmt(n[i][j])} (${(100 * h).toFixed(1)}%)<extra></extra>`, name: lvText(y, yv), legendgroup: `y${j}`, showlegend: i === 0 });
        base += h;
      });
      start += w + gap;
    });
    // the marginal distribution of Y, a narrow bar on the right
    let base = 0;
    const colT = yl.map((_, j) => n.reduce((a, r) => a + r[j], 0));
    yl.forEach((yv, j) => {
      const h = colT[j] / N;
      const rs = colRows[j];
      traces.push({ type: 'bar', x: [1.07], y: [h], base: [base], width: 0.06, rows: [rs], rowsScale: rs.length ? h / rs.length : 1, marker: { color: PALETTE[j % PALETTE.length], line: { color: SM.util.themeColors().surface, width: 1 } },
        hovertemplate: `${lvText(y, yv)}: ${fmt(colT[j])} (${(100 * h).toFixed(1)}%)<extra></extra>`, legendgroup: `y${j}`, showlegend: false });
      base += h;
    });
    const box = ctx.plot(traces, {
      barmode: 'overlay', bargap: 0, xaxis: { range: [0, 1.11], tickvals: [...centers, 1.07], ticktext: [...xl.map((v) => lvText(x, v)), 'all'], title: { text: x.name }, showgrid: false, zeroline: false },
      yaxis: { range: [0, 1], title: { text: y.name }, zeroline: false }, showlegend: true, legend: { traceorder: 'reversed', x: 1.02, xanchor: 'left', y: 1 }, margin: { l: 56, r: 110, t: 10, b: 44 },
    }, { width: availWidth(ctx, 560), height: 360, title: `${y.name} by ${x.name} mosaic`, select: false });
    // the selected part of a cell sits in the cell: give the companion bars their base
    const plot = box._plot;
    if (plot) for (const c of plot.companions) { const t = plot.traces[c.of]; if (t.base) plot.traces[c.at].base = t.base; plot.traces[c.at].width = t.width; }
    return box;
  }

  function crossTable(ctx, res, y, x, cells) {
    const n = res.counts, E = res.expected;
    const R = res.x_levels.length, C = res.y_levels.length, N = res.n;
    const rowT = n.map((r) => r.reduce((a, b) => a + b, 0));
    const colT = res.y_levels.map((_, j) => n.reduce((a, r) => a + r[j], 0));
    const val = {
      count: (i, j) => fmt(n[i][j]), total: (i, j) => lvPct(100 * n[i][j] / N), col: (i, j) => lvPct(colT[j] ? 100 * n[i][j] / colT[j] : NaN), row: (i, j) => lvPct(rowT[i] ? 100 * n[i][j] / rowT[i] : NaN),
      expected: (i, j) => fmt(E[i][j], { sig: 6 }), deviation: (i, j) => fmt(n[i][j] - E[i][j], { sig: 6 }), cellchi: (i, j) => fmt(res.cellchi[i][j], { sig: 5 }),
    };
    const shown = CELLS.filter(([k]) => cells.includes(k));
    const stack = (arr) => el('div', { class: 'sm-fyx-stack' }, ...arr.map((t) => el('div', { text: t })));
    const head = el('tr', null, el('th', { class: 'sm-l sm-fyx-corner', scope: 'col' }, stack(shown.map(([, l]) => l))), ...res.y_levels.map((v) => el('th', { scope: 'col', text: lvText(y, v) })), el('th', { scope: 'col', text: 'Total' }));
    const body = el('tbody');
    for (let i = 0; i < R; i++) {
      body.append(el('tr', null, el('th', { class: 'sm-l', scope: 'row', text: lvText(x, res.x_levels[i]) }),
        ...res.y_levels.map((_, j) => el('td', null, stack(shown.map(([k]) => val[k](i, j))))),
        el('td', { class: 'sm-fyx-margin' }, stack([fmt(rowT[i]), lvPct(100 * rowT[i] / N)]))));
    }
    body.append(el('tr', { class: 'sm-fyx-margin' }, el('th', { class: 'sm-l', scope: 'row', text: 'Total' }), ...colT.map((c) => el('td', null, stack([fmt(c), lvPct(100 * c / N)]))), el('td', null, stack([fmt(N), '']))));
    const cap = el('caption', { text: `${x.name} by ${y.name}` });
    return el('div', { class: 'sm-fyx-scroll' }, el('table', { class: 'sm-rt sm-fyx-ct' }, cap, el('thead', null, head), body));
  }

  async function contingency(ctx, y, x, host, sc) {
    const o = (k, d) => ctx.opt(k, d, sc);
    const base = basePayload(ctx, y, x);
    const { res, error } = await safeCall(ctx, 'fitybyx.contingency', base);
    if (error) { host.add(problem(ctx, error)); return; }
    const R = res.x_levels.length, C = res.y_levels.length;
    const P = pointsOf(ctx, y, x);
    if (o('mosaic', true)) {
      const ob = ctx.outline('Mosaic Plot', { parent: host, key: `mosaic:${sc}` });
      ob.add(mosaic(ctx, res, y, x, P));
    }
    if (o('ctable', true)) {
      const cells = o('cells', ['count', 'total', 'col', 'row']);
      const tog = (key, label) => ({ label, checked: cells.includes(key), action: () => ctx.set('cells', cells.includes(key) ? cells.filter((z) => z !== key) : CELLS.map(([kk]) => kk).filter((kk) => kk === key || cells.includes(kk)), sc) });
      const ob = ctx.outline('Contingency Table', { parent: host, key: `ct:${sc}`, menu: () => CELLS.map(([k, l]) => tog(k, l)) });
      ob.add(crossTable(ctx, res, y, x, cells));
    }
    if (o('tests', true)) {
      const ob = ctx.outline('Tests', { parent: host, key: `tests:${sc}`, info: 'p:fitybyx:contingency' });
      if (!res.tests) ob.add(ctx.warn('The tests need two levels of each variable.'));
      else {
        ob.add(ctx.rt({ columns: [{ key: 'n', label: 'N' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'nll', label: '-LogLike' }, { key: 'rsq', label: 'RSquare (U)' }], rows: [res.loglike] }, { sortable: false }),
          ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'chisq', label: 'ChiSquare' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: res.tests }, { sortable: false }));
        if (res.fisher) {
          const fe = ctx.outline('Fisher\'s Exact Test', { parent: ob, key: `fisher:${sc}` });
          if (res.fisher.left != null) {
            fe.add(ctx.rt({ columns: [{ key: 't', label: 'Test', fmt: 'text' }, { key: 'p', label: 'Prob', fmt: 'p' }, { key: 'h', label: 'Alternative Hypothesis', fmt: 'text' }], rows: [
              { t: 'Left', p: res.fisher.left, h: `Prob(${lvText(y, res.y_levels[0])}) is greater for ${lvText(x, res.x_levels[1])} than ${lvText(x, res.x_levels[0])}` },
              { t: 'Right', p: res.fisher.right, h: `Prob(${lvText(y, res.y_levels[0])}) is greater for ${lvText(x, res.x_levels[0])} than ${lvText(x, res.x_levels[1])}` },
              { t: '2-Tail', p: res.fisher.two, h: `Prob(${lvText(y, res.y_levels[0])}) is different across ${x.name}` }] }, { sortable: false }));
          } else fe.add(ctx.kv([['Two-sided Prob', res.fisher.two, 'p']]), ctx.note('scipy\'s exact test of independence of the r×c table given its margins.'));
        }
        ob.add(notesOf(ctx, res.notes).map((node) => { node.classList.add('sm-fyx-warnnote'); return node; }), ctx.code(res.code));
      }
    }
    if (o('anomp', false)) await anomProportions(ctx, host, sc, base, y, x);
    if (o('ca', false)) await caReport(ctx, host, sc, base, y, x);
    if (o('cmh', null)) await cmhReport(ctx, host, sc, base, ctx.col(o('cmh', null)));
    if (o('agree', false)) await agreeReport(ctx, host, sc, base);
    const need22 = (label) => (R === 2 && C === 2 ? null : ctx.warn(`${label} needs a 2×2 table.`));
    if (o('rr', false) || o('or', false) || o('rd', false)) {
      const bad = need22('Relative Risk, Odds Ratio and Risk Difference');
      const { res: r, error: e2 } = bad ? { res: null } : await safeCall(ctx, 'fitybyx.contingency_2x2', base);
      const lvl = `${fmt(100 * (1 - ctx.alpha))}%`;
      const yx = (j) => `P(${lvText(y, res.y_levels[j])}|${lvText(x, res.x_levels[0])})/P(${lvText(y, res.y_levels[j])}|${lvText(x, res.x_levels[1])})`;
      if (o('rr', false)) {
        const ob = ctx.outline('Relative Risk', { parent: host, key: `rr:${sc}` });
        if (bad) ob.add(bad); else if (e2) ob.add(problem(ctx, e2));
        else ob.add(ctx.rt({ columns: [{ key: 'desc', label: 'Description', fmt: 'text' }, { key: 'rr', label: 'Relative Risk' }, { key: 'lower', label: `Lower ${lvl}` }, { key: 'upper', label: `Upper ${lvl}` }], rows: r.risks.map((q) => ({ ...q, desc: yx(q.response) })) }, { sortable: false }), ctx.note('Log-scale Wald intervals (statsmodels Table2x2.riskratio_confint).'), ctx.code(r.code));
      }
      if (o('or', false)) {
        const ob = ctx.outline('Odds Ratio', { parent: host, key: `or:${sc}` });
        if (bad) ob.add(bad); else if (e2) ob.add(problem(ctx, e2));
        else ob.add(ctx.rt({ columns: [{ key: 'or', label: 'Odds Ratio' }, { key: 'lower', label: `Lower ${lvl}` }, { key: 'upper', label: `Upper ${lvl}` }], rows: [r.odds] }, { sortable: false }),
          ctx.note(`The odds of ${lvText(y, res.y_levels[0])} for ${lvText(x, res.x_levels[0])} over its odds for ${lvText(x, res.x_levels[1])}; log-scale Wald interval.`));
      }
      if (o('rd', false)) {
        const ob = ctx.outline('Risk Difference', { parent: host, key: `rd:${sc}` });
        if (bad) ob.add(bad); else if (e2) ob.add(problem(ctx, e2));
        else ob.add(ctx.rt({ columns: [{ key: 'desc', label: 'Description', fmt: 'text' }, { key: 'p1', label: 'Prob 1' }, { key: 'p2', label: 'Prob 2' }, { key: 'diff', label: 'Difference' }, { key: 'diff_lower', label: `Lower ${lvl}` }, { key: 'diff_upper', label: `Upper ${lvl}` }],
          rows: r.risks.map((q) => ({ ...q, desc: `P(${lvText(y, res.y_levels[q.response])}|${lvText(x, res.x_levels[0])}) − P(${lvText(y, res.y_levels[q.response])}|${lvText(x, res.x_levels[1])})` })) }, { sortable: false }), ctx.note('Wald intervals (statsmodels confint_proportions_2indep).'));
      }
      if (r && r.mcnemar && o('rr', false)) host.add(ctx.note(`McNemar's test of the 2×2 table as paired data: χ² = ${fmt(r.mcnemar.chisq)}, p = ${SM.util.fmtP(r.mcnemar.p, ctx.alpha)} (exact binomial p = ${SM.util.fmtP(r.mcnemar.p_exact, ctx.alpha)}).`));
    }
    if (o('twoProp', false)) await twoPropReport(ctx, host, sc, base, res, y, x);
    if (o('measures', false)) {
      const ob = ctx.outline('Measures of Association', { parent: host, key: `ma:${sc}`, info: 'p:fitybyx:measures' });
      const { res: r, error: e2 } = await safeCall(ctx, 'fitybyx.contingency_measures', base);
      if (e2) ob.add(problem(ctx, e2));
      else {
        const lvl = `${fmt(100 * (1 - ctx.alpha))}%`;
        ob.add(ctx.rt({ columns: [{ key: 'measure', label: 'Measure', fmt: 'text' }, { key: 'value', label: 'Value' }, { key: 'se', label: 'Std Err' }, { key: 'lower', label: `Lower ${lvl}` }, { key: 'upper', label: `Upper ${lvl}` }], rows: r.measures }, { sortable: false }),
          r.other.length ? ctx.kv(r.other.map((m) => [m.measure, m.value])) : null, notesOf(ctx, r.notes), ctx.code(r.code));
      }
    }
    if (o('trend', false)) {
      const ob = ctx.outline('Cochran Armitage Trend Test', { parent: host, key: `trend:${sc}` });
      const { res: r, error: e2 } = await safeCall(ctx, 'fitybyx.contingency_trend', base);
      if (e2) ob.add(problem(ctx, e2));
      else ob.add(ctx.rt({ columns: [{ key: 'w', label: '', fmt: 'text' }, { key: 'z', label: 'Z' }, { key: 'p2', label: 'Prob>|Z|', fmt: 'p' }, { key: 'pg', label: 'Prob>Z', fmt: 'p' }, { key: 'pl', label: 'Prob<Z', fmt: 'p' }], rows: [
        { w: 'Cochran-Armitage (binomial variance)', z: r.z, p2: r.p_two, pg: r.p_greater, pl: r.p_less },
        { w: 'statsmodels linear-by-linear (permutation variance)', z: r.z_perm, p2: r.p_perm, pg: null, pl: null }] }, { sortable: false }), notesOf(ctx, r.notes), ctx.code(r.code));
    }
  }

  async function anomProportions(ctx, host, sc, base, y, x) {
    const ob = ctx.outline('Analysis of Means for Proportions', { parent: host, key: `anomp:${sc}`, menu: () => [{ label: 'Remove', action: () => ctx.set('anomp', false, sc) }] });
    const { res: r, error } = await safeCall(ctx, 'fitybyx.contingency_anomp', { ...base, event: ctx.opt('target', null, sc) });
    if (error) { ob.add(problem(ctx, error)); return; }
    const L = r.levels;
    const xs = L.map((_, i) => i);
    const names = L.map((l) => lvText(x, l.level));
    const step = (key) => { const X = [], Y = []; L.forEach((l, i) => { X.push(i - 0.5, i + 0.5, null); Y.push(l[key], l[key], null); }); return { X, Y }; };
    const lo = step('ldl'), hi = step('udl');
    const ev = lvText(y, r.y_levels[r.event]);
    ob.add(ctx.plot([
      { type: 'scatter', mode: 'lines', x: lo.X, y: lo.Y, line: { color: RED, width: 1.2 }, hoverinfo: 'skip', name: 'LDL' },
      { type: 'scatter', mode: 'lines', x: hi.X, y: hi.Y, line: { color: RED, width: 1.2 }, hoverinfo: 'skip', name: 'UDL' },
      { type: 'scatter', mode: 'lines+markers', x: xs, y: L.map((l) => l.p), marker: { size: 8, color: L.map((l) => (l.out ? RED : SM.report.BASE)) }, line: { color: GREY, width: 1 }, text: names, hovertemplate: '%{text}: %{y:.4f}<extra></extra>', name: 'Proportions' },
    ], { xaxis: { tickvals: xs, ticktext: names, range: [-0.6, L.length - 0.4], title: { text: x.name } }, yaxis: { title: { text: `Proportion of ${ev}` } }, shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: r.pbar, y1: r.pbar, line: { color: GREY, width: 1 } }] }, { width: availWidth(ctx, Math.max(360, 120 + 60 * L.length)), height: 280, title: 'Analysis of Means for Proportions', select: false }),
    ctx.rt({ columns: [{ key: 'lv', label: 'Level', fmt: 'text' }, { key: 'n', label: 'N' }, { key: 'p', label: `Proportion ${ev}` }, { key: 'ldl', label: 'Lower Decision Limit' }, { key: 'udl', label: 'Upper Decision Limit' }, { key: 'flag', label: 'Outside', fmt: 'text' }],
      rows: L.map((l, i) => ({ ...l, lv: names[i], flag: l.out ? 'yes' : '' })) }, { sortable: false }),
    ctx.kv([['Overall proportion', r.pbar], ['h (exact, normal)', r.h], ['Alpha', r.alpha]]),
    ctx.note('Decision limits p̄ ± h·√(p̄(1 − p̄)(N − nᵢ)/(N nᵢ)): the normal approximation to the binomial; h is the exact ANOM critical value for infinite degrees of freedom.'), ctx.code(r.code));
  }

  async function caReport(ctx, host, sc, base, y, x) {
    const ob = ctx.outline('Correspondence Analysis', { parent: host, key: `ca:${sc}` });
    const { res: r, error } = await safeCall(ctx, 'fitybyx.contingency_ca', base);
    if (error) { ob.add(problem(ctx, error)); return; }
    const two = r.details.length > 1;
    const pts = [
      { type: 'scatter', mode: 'markers+text', x: r.rows.map((v) => v.c1), y: r.rows.map((v) => (two ? v.c2 : 0)), text: r.rows.map((v) => lvText(x, v.level)), textposition: 'top center', marker: { color: SM.report.BASE, size: 8, symbol: 'circle' }, name: x.name, hoverinfo: 'text' },
      { type: 'scatter', mode: 'markers+text', x: r.cols.map((v) => v.c1), y: r.cols.map((v) => (two ? v.c2 : 0)), text: r.cols.map((v) => lvText(y, v.level)), textposition: 'bottom center', marker: { color: RED, size: 8, symbol: 'square' }, name: y.name, hoverinfo: 'text' },
    ];
    ob.add(ctx.plot(pts, { xaxis: { title: { text: `c1 (${(100 * r.details[0].portion).toFixed(1)}%)` }, zeroline: true }, yaxis: { title: { text: two ? `c2 (${(100 * r.details[1].portion).toFixed(1)}%)` : '' }, zeroline: true }, showlegend: true, legend: { orientation: 'h', y: -0.22 } }, { width: availWidth(ctx, 460), height: 380, title: 'Correspondence Analysis', select: false }));
    const det = ctx.outline('Details', { parent: ob, key: `cad:${sc}` });
    det.add(ctx.rt({ columns: [{ key: 'sv', label: 'Singular Value' }, { key: 'inertia', label: 'Inertia' }, { key: 'portion', label: 'Portion' }, { key: 'cum', label: 'Cumulative' }], rows: r.details }, { sortable: false }),
      ctx.rt({ columns: [{ key: 'lv', label: x.name, fmt: 'text' }, { key: 'c1', label: 'c1' }, { key: 'c2', label: 'c2' }], rows: r.rows.map((v) => ({ ...v, lv: lvText(x, v.level) })) }, { sortable: false }),
      ctx.rt({ columns: [{ key: 'lv', label: y.name, fmt: 'text' }, { key: 'c1', label: 'c1' }, { key: 'c2', label: 'c2' }], rows: r.cols.map((v) => ({ ...v, lv: lvText(y, v.level) })) }, { sortable: false }),
      ctx.note(`Principal coordinates from the SVD of the standardised residuals; N × total inertia = ${fmt(r.chisq)}, the Pearson χ². The signs of the dimensions are arbitrary.`), ctx.code(r.code));
  }

  async function cmhReport(ctx, host, sc, base, strata) {
    const ob = ctx.outline('Cochran Mantel Haenszel', { parent: host, key: `cmh:${sc}`, info: 'p:fitybyx:strata', menu: () => [{ label: 'Remove', action: () => ctx.set('cmh', null, sc) }] });
    if (!strata) { ob.add(ctx.warn('The grouping column is no longer in the table.')); return; }
    const { res: r, error } = await safeCall(ctx, 'fitybyx.contingency_cmh', { ...base, strata: strata.name });
    if (error) { ob.add(problem(ctx, error)); return; }
    const lvl = `${fmt(100 * (1 - ctx.alpha))}%`;
    ob.add(ctx.note(`Grouped by ${strata.name}: ${r.strata} strata with both levels of each variable.`),
      ctx.rt({ columns: [{ key: 't', label: 'Test', fmt: 'text' }, { key: 'chisq', label: 'ChiSquare' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }],
        rows: [{ t: 'Cochran Mantel Haenszel (odds ratio is 1)', ...r.cmh }, r.cmh_cc ? { t: 'Cochran Mantel Haenszel, continuity corrected', ...r.cmh_cc } : null,
          r.breslow_day ? { t: 'Breslow-Day (odds ratios are equal)', ...r.breslow_day } : null,
          r.breslow_day_tarone ? { t: 'Breslow-Day-Tarone (odds ratios are equal)', ...r.breslow_day_tarone } : null].filter(Boolean) }, { sortable: false }),
      ctx.kv([['Mantel-Haenszel odds ratio', r.or_mh], [`Lower ${lvl}`, r.lower], [`Upper ${lvl}`, r.upper], ['Mantel-Haenszel relative risk', r.rr_mh]]));
    if (r.by_stratum && r.by_stratum.length) {
      const bs = ctx.outline('Odds Ratios by Stratum', { parent: ob, key: `cmhs:${sc}` });
      bs.add(ctx.rt({ columns: [{ key: 'lv', label: strata.name, fmt: 'text' }, { key: 'n', label: 'N' }, { key: 'or', label: 'Odds Ratio' }, { key: 'lower', label: `Lower ${lvl}` }, { key: 'upper', label: `Upper ${lvl}` },
        { key: 'a', label: 'a', hidden: true }, { key: 'b', label: 'b', hidden: true }, { key: 'c', label: 'c', hidden: true }, { key: 'd', label: 'd', hidden: true }],
      rows: r.by_stratum.map((s) => ({ ...s, lv: lvText(strata, s.level) })) }), ctx.note('Each stratum\'s own odds ratio with its log-scale Wald interval (statsmodels Table2x2): the Breslow-Day test asks whether they differ more than chance allows.'));
    }
    ob.add(notesOf(ctx, r.notes),
      ctx.note('statsmodels StratifiedTable, 2×2 tables in each stratum. The Breslow-Day test of equal odds ratios (with Tarone\'s adjustment), the continuity-corrected test and the relative risk are not in JMP, whose Cochran Mantel Haenszel report gives SAS\'s general-association statistics instead, which statsmodels does not compute.'), ctx.code(r.code));
  }

  /* ---- Two Sample Test for Proportions: JMP's adjusted Wald difference,
     and statsmodels' other methods, for a difference, ratio or odds ratio -- */
  const TWOPROP = [['diff', 'Proportion Difference'], ['ratio', 'Relative Risk'], ['odds-ratio', 'Odds Ratio']];

  async function twoPropReport(ctx, host, sc, base, res, y, x) {
    const cmp = ctx.opt('twoPropCompare', 'diff', sc);
    const lv0 = ctx.opt('twoPropLevel', null, sc);
    const yl = res.y_levels, xl = res.x_levels;
    const ob = ctx.outline('Two Sample Test for Proportions', { parent: host, key: `tp:${sc}`, info: 'p:fitybyx:twoprop', menu: () => [
      ...TWOPROP.map(([k, l]) => ({ label: l, checked: cmp === k, action: () => ctx.set('twoPropCompare', k, sc) })),
      { separator: true },
      { label: 'Response Level', submenu: () => yl.map((v, j) => ({ label: lvText(y, v), checked: lv0 == null ? j === 0 : keyOf(lv0) === keyOf(v), action: () => ctx.set('twoPropLevel', j === 0 ? null : v, sc) })) },
      { label: 'Remove', action: () => ctx.set('twoProp', false, sc) }] });
    if (yl.length !== 2 || xl.length !== 2) { ob.add(ctx.warn('The Two Sample Test for Proportions needs a 2×2 table.')); return; }
    const { res: r, error } = await safeCall(ctx, 'fitybyx.contingency_twoprop', { ...base, compare: cmp, response: lv0 });
    if (error) { ob.add(problem(ctx, error)); return; }
    const lvl = `${fmt(100 * (1 - ctx.alpha))}%`;
    const yt = lvText(y, yl[r.response]), x1 = lvText(x, xl[0]), x2 = lvText(x, xl[1]);
    const desc = { diff: `P(${yt}|${x1}) − P(${yt}|${x2})`, ratio: `P(${yt}|${x1}) / P(${yt}|${x2})`, 'odds-ratio': `Odds(${yt}|${x1}) / Odds(${yt}|${x2})` }[cmp];
    const estLabel = TWOPROP.find((t) => t[0] === cmp)[1];
    ob.add(ctx.kv([['Description', desc, 'text'], [`P(${yt}|${x1})`, r.p1], [`P(${yt}|${x2})`, r.p2], [estLabel, r.estimate]]));
    if (cmp === 'diff') {
      const ac = r.methods.find((m) => m.key === 'agresti-caffo');
      if (ac) {
        ob.add(ctx.rt({ columns: [{ key: 'h', label: 'Adjusted Wald Test (Null Hypothesis)', fmt: 'text' }, { key: 'p', label: 'Prob', fmt: 'p' }], rows: [
          { h: `${desc} ≥ 0`, p: ac.p_less }, { h: `${desc} ≤ 0`, p: ac.p_greater }, { h: `${desc} = 0`, p: ac.p }] }, { sortable: false, caption: `Lower ${lvl} ${fmt(ac.lower)}, Upper ${lvl} ${fmt(ac.upper)} (adjusted Wald, as JMP)` }));
      }
    }
    const mrows = r.methods.map((m) => ({ ...m, note: m.note || (m.p == null && m.key === 'newcomb' ? 'interval only' : '') }));
    ob.add(ctx.rt({ columns: [{ key: 'method', label: 'Method', fmt: 'text' }, { key: 'lower', label: `Lower ${lvl}` }, { key: 'upper', label: `Upper ${lvl}` }, { key: 'z', label: 'Z' },
      { key: 'p', label: 'Prob>|Z|', fmt: 'p' }, { key: 'p_greater', label: 'Prob>Z', fmt: 'p', hidden: true }, { key: 'p_less', label: 'Prob<Z', fmt: 'p', hidden: true },
      ...(mrows.some((m) => m.note) ? [{ key: 'note', label: '', fmt: 'text' }] : [])],
    rows: mrows }, { sortable: false, caption: `${estLabel}: every method statsmodels has` }),
    ctx.note(`Each method's interval (statsmodels confint_proportions_2indep) and its test of ${cmp === 'diff' ? 'no difference' : 'a ratio of 1'} (test_proportions_2indep). JMP reports only the adjusted Wald (Agresti-Caffo) difference; the score methods are Miettinen and Nurminen's, with their n/(n − 1) factor, and Koopman's for the ratio without it.`),
    notesOf(ctx, r.notes), ctx.code(r.code));
  }

  async function agreeReport(ctx, host, sc, base) {
    const ob = ctx.outline('Agreement Statistic', { parent: host, key: `agree:${sc}` });
    const { res: r, error } = await safeCall(ctx, 'fitybyx.contingency_agreement', base);
    if (error) { ob.add(problem(ctx, error)); return; }
    const lvl = `${fmt(100 * (1 - ctx.alpha))}%`;
    ob.add(ctx.rt({ columns: [{ key: 'kappa', label: 'Kappa' }, { key: 'se', label: 'Std Err' }, { key: 'lower', label: `Lower ${lvl}` }, { key: 'upper', label: `Upper ${lvl}` }, { key: 'p_greater', label: 'Prob>Z', fmt: 'p' }, { key: 'p_two', label: 'Prob>|Z|', fmt: 'p' }], rows: [r] }, { sortable: false }));
    if (r.bowker) ctx.outline('Bowker\'s Test', { parent: ob, key: `bowker:${sc}` }).add(ctx.rt({ columns: [{ key: 'chisq', label: 'ChiSquare' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: [r.bowker] }, { sortable: false }),
      ctx.note('The test of symmetry, n_ij = n_ji (for a 2×2 table it is McNemar\'s test).'));
    ob.add(notesOf(ctx, r.notes), ctx.code(r.code));
  }

  function ctMenu(ctx, sc, y, x) {
    return [
      ctx.check('Mosaic Plot', 'mosaic', sc, true),
      ctx.check('Contingency Table', 'ctable', sc, true),
      ctx.check('Tests', 'tests', sc, true),
      { label: 'Set α Level', submenu: () => alphaMenu(ctx) },
      { separator: true },
      ctx.check('Analysis of Means for Proportions', 'anomp', sc, false),
      ctx.check('Correspondence Analysis', 'ca', sc, false),
      { label: 'Cochran Mantel Haenszel…', checked: !!ctx.opt('cmh', null, sc), action: async () => {
        const cats = ctx.table.columns.filter((c) => c.isCategorical && c.id !== x.id && c.id !== y.id);
        if (!cats.length) { SM.ui.toast('Cochran Mantel Haenszel needs a third ordinal or nominal column to group by'); return; }
        const v = await ask('Cochran Mantel Haenszel', [{ key: 'c', label: 'Grouping column (strata)', type: 'select', value: ctx.opt('cmh', null, sc) || cats[0].id, choices: cats.map((c) => [c.id, c.name]) }]);
        if (v) ctx.set('cmh', v.c, sc);
      } },
      ctx.check('Agreement Statistic', 'agree', sc, false),
      ctx.check('Relative Risk', 'rr', sc, false),
      ctx.check('Odds Ratio', 'or', sc, false),
      ctx.check('Risk Difference', 'rd', sc, false),
      ctx.check('Two Sample Test for Proportions', 'twoProp', sc, false),
      ctx.check('Measures of Association', 'measures', sc, false),
      ctx.check('Cochran Armitage Trend Test', 'trend', sc, false),
    ];
  }

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */

  /* Options are scoped by column ids (y~x), and a few hold one (Group By,
     Cochran Mantel Haenszel). A project gives its columns new ids and remaps
     only the roles, so the report records the name of every column it uses
     and, when an id has gone or now names another column, moves the
     options to the column that carries the recorded name. */
  const ID_VALUED = /\|(groupBy|cmh)$/;
  function healScopes(ctx) {
    const o = ctx.spec.options;
    const t = ctx.table;
    if (!o || !t) return;
    const byId = (id) => t.columns.find((c) => c.id === id) || null;
    const remap = {};
    for (const [id, name] of Object.entries(o.__colNames || {})) {
      const c = byId(id);
      if (c && c.name === name) continue;
      const now = t.columns.find((x) => x.name === name);
      if (now && now.id !== id) remap[id] = now.id;
    }
    if (Object.keys(remap).length) {
      for (const key of Object.keys(o)) {
        const bar = key.indexOf('|');
        if (bar < 0) continue;
        const parts = key.slice(0, bar).split('~');
        if (!parts.some((q) => remap[q])) continue;
        const nk = `${parts.map((q) => remap[q] || q).join('~')}${key.slice(bar)}`;
        o[nk] = o[key];
        delete o[key];
      }
      for (const key of Object.keys(o)) if (ID_VALUED.test(key) && remap[o[key]]) o[key] = remap[o[key]];
    }
    const rec = {};
    for (const ids of Object.values(ctx.spec.roles || {})) for (const id of ids || []) { const c = byId(id); if (c) rec[id] = c.name; }
    for (const key of Object.keys(o)) if (ID_VALUED.test(key)) { const c = byId(o[key]); if (c) rec[c.id] = c.name; }
    o.__colNames = rec;
  }
  const RENDER = { bivariate, oneway, logistic, contingency };
  const MENU = { bivariate: bivMenu, oneway: owMenu, logistic: logMenu, contingency: ctMenu };

  function pairMenu(ctx, kind, y, x) {
    const sc = scopeOf(y, x);
    return kind === 'bivariate' ? bivMenu(ctx, sc) : MENU[kind](ctx, sc, y, x);
  }

  function allPairsMenu(ctx) {
    const pairs = pairsOf(ctx.spec, ctx.table);
    const of = (kind) => pairs.filter(([y, x]) => kindOf(y, x) === kind);
    const each = (kind, fn) => () => { for (const [y, x] of of(kind)) fn(scopeOf(y, x)); ctx.report.run(); };
    const setAll = (kind, key, value) => each(kind, (sc) => ctx.set(key, value, sc, { rerun: false }));
    const addAll = (fit) => each('bivariate', (sc) => { const fits = ctx.opt('fits', [], sc); const next = 1 + Math.max(0, ...fits.map((f) => Number(String(f.id).slice(1)) || 0)); ctx.set('fits', [...fits, { id: `f${next}`, ...fit }], sc, { rerun: false }); });
    const items = [];
    if (of('bivariate').length) items.push({ label: 'Bivariate', submenu: [{ label: 'Fit Mean', action: addAll({ kind: 'mean' }) }, { label: 'Fit Line', action: addAll({ kind: 'line' }) }, { label: 'Density Ellipse 0.95', action: addAll({ kind: 'ellipse', p: 0.95 }) }] });
    if (of('oneway').length) items.push({ label: 'Oneway', submenu: [{ label: 'Means/Anova', action: each('oneway', (sc) => { ctx.set('anova', true, sc, { rerun: false }); ctx.set('diamonds', true, sc, { rerun: false }); }) },
      { label: 'Quantiles', action: each('oneway', (sc) => { ctx.set('quantiles', true, sc, { rerun: false }); ctx.set('box', true, sc, { rerun: false }); }) },
      { label: 'All Pairs, Tukey HSD', action: each('oneway', (sc) => { const c = ctx.opt('compare', [], sc); if (!c.some((z) => z.method === 'tukey')) ctx.set('compare', [...c, { method: 'tukey', control: null }], sc, { rerun: false }); }) },
      { label: 'Wilcoxon / Kruskal-Wallis Tests', action: each('oneway', (sc) => { const c = ctx.opt('np', [], sc); if (!c.includes('wilcoxon')) ctx.set('np', [...c, 'wilcoxon'], sc, { rerun: false }); }) },
      { label: 'Brunner-Munzel Test', action: setAll('oneway', 'bm', true) },
      { label: 'Unequal Variances', action: setAll('oneway', 'unequal', true) }] });
    if (of('logistic').length) items.push({ label: 'Logistic', submenu: [{ label: 'Odds Ratios', action: setAll('logistic', 'odds', true) }, { label: 'ROC Curve', action: setAll('logistic', 'roc', true) }] });
    if (of('contingency').length) items.push({ label: 'Contingency', submenu: [{ label: 'Measures of Association', action: setAll('contingency', 'measures', true) }, { label: 'Correspondence Analysis', action: setAll('contingency', 'ca', true) }, { label: 'Two Sample Test for Proportions', action: setAll('contingency', 'twoProp', true) }] });
    return [
      { head: 'For every analysis of a kind' }, ...items,
      { separator: true },
      { label: 'Arrange in Rows…', action: async () => { const v = await ask('Arrange in Rows', [{ key: 'n', label: 'Analyses per row (0: one under the other)', type: 'number', value: ctx.opt('perRow', 0) }]); if (v) ctx.set('perRow', Math.max(0, Math.round(v.n || 0))); } },
    ];
  }

  const TOPICS = {
    'p:fitybyx': {
      kicker: 'Analyze', title: 'Fit Y by X',
      lead: 'Each Y against each X. The modeling types choose the analysis: continuous by continuous is a Bivariate fit, continuous by categorical a Oneway analysis, categorical by continuous a Logistic fit, categorical by categorical a Contingency analysis.',
      sections: [
        { heading: 'Roles', choices: [['Y, Response', 'One or more responses.'], ['X, Factor', 'One or more factors; every Y is paired with every X.'], ['Block', 'Oneway only: an ordinal or nominal column whose levels are blocks (a randomized block ANOVA).'], ['Weight', 'Weighted least squares; weights the logistic likelihood.'], ['Freq', 'A count per row: the row stands for that many observations.'], ['By', 'A separate analysis for each level.']] },
        { heading: 'The red triangles', text: 'Each analysis has its own: fits for a Bivariate, tests and comparisons for a Oneway, odds ratios and ROC curves for a Logistic, measures and tests for a Contingency. Each fit of a Bivariate has its red triangle too: confidence curves, saved predictions and residuals, residual plots, Remove Fit.' },
        { heading: 'Beyond JMP', text: 'From statsmodels: Nonparametric ▸ Brunner-Munzel Test and Equivalence Test ▸ Probability of Superiority, Compare Rates for counts with an exposure (Oneway); the Two Sample Test for Proportions by every method statsmodels has and Breslow-Day beside Cochran Mantel Haenszel (Contingency). From the published methods: Effect Size (Cohen\'s d, Hedges\' g, η², ε², ω² with exact intervals), Bayes Factor (the JZS t test; the correlation\'s in Bivariate) and Compare Means ▸ All Pairs, Games-Howell (Oneway). Each (i) says how they differ from JMP\'s closest.' },
        { heading: 'Weight and Freq', text: 'The least-squares fits use both, with the residual degrees of freedom counted from Freq. Where statsmodels or scipy takes no weights (rank tests, robust, quantile and LOWESS fits, MNLogit, OrderedModel) whole-number frequencies are counted by repeating rows and Weight is not used; the report says so.' },
        { heading: 'Linking', text: 'Points, bars and mosaic cells select their rows; selected rows are highlighted in every graph.' },
      ],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:fits': {
      kicker: 'Bivariate', title: 'Fits on a scatterplot',
      lead: 'Each fit adds its curve to the scatterplot and its report below it, with a red triangle of its own.',
      sections: [
        { heading: 'The fits', choices: [['Fit Line, Fit Polynomial', 'Least squares (statsmodels OLS/WLS) with the powers above one centred at the mean of X, as JMP does; Summary of Fit, Lack Of Fit (when X values repeat), Analysis of Variance, Parameter Estimates.'],
          ['Fit Special', 'Log, square root, square, reciprocal or exponential of Y and X, a polynomial in the transformed X, or the intercept or slope held fixed; the fit is also measured on the original scale.'],
          ['Fit Spline', 'The cubic smoothing spline with penalty λ (scipy make_smoothing_spline).'], ['Kernel Smoother', 'statsmodels LOWESS.'], ['Fit Each Value', 'The mean at each X: the pure error.'],
          ['Fit Orthogonal', 'Deming regression for a ratio of error variances; jackknife standard errors.'], ['Robust', 'M-estimation (statsmodels RLM), Huber or bisquare.'], ['Fit Quantile', 'statsmodels QuantReg.'],
          ['Density Ellipse', 'The bivariate normal contour and the correlation with its Fisher-z interval.'], ['Nonpar Density', 'Contours of a Gaussian kernel density.']] },
        { heading: 'The fit\'s red triangle', text: 'Confidence curves for the fitted mean and for individuals, shaded or as lines; Save Predicteds, Residuals and Studentized Residuals; Plot Residuals; Remove Fit.' },
      ],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:anova': {
      kicker: 'Oneway', title: 'Means/Anova',
      lead: 'The one-way analysis of variance: whether the means of the levels differ, with the pooled error. The mean diamonds show each mean and its confidence interval; their overlap marks, at mean ± half-width/√2, overlap for means that do not differ significantly (roughly, for equal sizes).',
      sections: [{ heading: 'With a Block', text: 'The block is an additive effect (a randomized block ANOVA); the tests are Type III and the means are least squares means, the block averaged.' }, { heading: 'Two levels', text: 'The pooled t test of the second level minus the first; t Test from the red triangle does it without assuming equal variances.' }],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:compare': {
      kicker: 'Oneway', title: 'Compare Means',
      lead: 'Which pairs of means differ. Student\'s t does each pair at level α; Tukey-Kramer HSD holds α over all pairs; Dunnett\'s compares each level with a control.',
      sections: [
        { heading: 'Reading the reports', list: ['The threshold matrix shows |difference| minus the least significant difference: positive for pairs that differ.', 'Levels that do not share a letter in the connecting letters report differ.', 'The comparison circles have radius quantile × standard error; circles of means that differ barely overlap or not at all.'] },
        { heading: 'The numbers', text: 'Student\'s t: statsmodels contrasts of the cell-means model. Tukey: the differences from statsmodels\' pairwise_tukeyhsd; q* and the p-values from scipy\'s studentized range distribution, which is exact where pairwise_tukeyhsd\'s approximation stops at p = 0.001. Dunnett: scipy.stats.dunnett.' },
        { heading: 'Games-Howell', text: 'All pairs without assuming equal variances (Games and Howell 1976): each difference over its own standard error √(s²ᵢ/nᵢ + s²ⱼ/nⱼ), with the Welch-Satterthwaite degrees of freedom of the pair, and p-values and intervals from the studentized range of k levels on those degrees of freedom. Use it where Unequal Variances rejects equal variances and Tukey\'s pooled error would mislead. Each pair has its own q*, so there are no comparison circles. Not in JMP; Weight is not used.' },
      ],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:effect': {
      kicker: 'Fit Y by X, Matched Pairs', title: 'Effect Size',
      lead: 'How large the difference is, in standard deviations or as a share of the variance, with a confidence interval: from the red triangle (Effect Size), for Means/Anova, the t tests and Matched Pairs. Not in JMP.',
      sections: [
        { heading: 'Two levels', choices: [['Cohen\'s d', 'the difference of the means (second level minus first) over the pooled standard deviation, beside the pooled t test'], ['Hedges\' g', 'J·d with Hedges\' (1981) exact J = Γ(ν/2)/(√(ν/2)Γ((ν−1)/2)), ν = n₁ + n₂ − 2: unbiased for δ under normality'], ['d* and g*', 'beside the unequal-variance t test: the difference over √((s₁² + s₂²)/2), Cohen\'s (1988) standardizer when the variances differ, which does not depend on the group sizes']] },
        { heading: 'Several levels', choices: [['η²', 'SS(X)/SS(total), the share of the variation that X explains in the sample; biased upward'], ['ε²', '(SS(X) − df(X)·MSE)/SS(total) (Kelley 1935)'], ['ω²', '(SS(X) − df(X)·MSE)/(SS(total) + MSE) (Hays 1963), the least biased'], ['With a Block', 'their partial forms, the block\'s sum of squares left out']] },
        { heading: 'Matched Pairs', choices: [['d_z', 'the mean difference over the standard deviation of the differences: the paired t over √n'], ['g_z', 'J(n − 1)·d_z'], ['d_av', 'the mean difference over √((s₁² + s₂²)/2), comparable with a two-group d (Cumming 2012; Lakens 2013): d_z grows with the correlation of the pair, d_av does not']] },
        { heading: 'The intervals', text: 'Exact where an exact interval exists: d and d_z from the noncentral t, whose noncentrality λ is found where the observed t is the upper and the lower α/2 point (Steiger and Fouladi 1997; Cumming and Finch 2001); η², ε² and ω² from the noncentral F in the same way, λ/(λ + df₁ + df₂ + 1) being the population proportion of variance that all three estimate (Smithson 2003; Steiger 2004). g\'s interval is J times d\'s. d*, g* and d_av have no exact interval: theirs are Bonett\'s (2008), estimate ± z·SE, which do not assume equal variances. Steiger (2004) suggests a 90% interval for η², which matches the one-sided F test at α = 0.05: set α to 0.1.' },
        { heading: 'Weight and Freq', text: 'Freq counts rows. The t tests\' effect sizes, like the t tests, do not use Weight; η², ε² and ω² use the weighted sums of squares of the Analysis of Variance.' },
      ],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:bayes': {
      kicker: 'Fit Y by X, Matched Pairs', title: 'Bayes Factor',
      lead: 'How much more likely the data are under the alternative than under the null hypothesis (BF10), or the other way round (BF01 = 1/BF10), for a prior on the effect under the alternative. BF10 above 1 favours the alternative, below 1 the null; unlike a p-value it can show evidence for no effect. Not in JMP.',
      sections: [
        { heading: 'The t tests', text: 'JZS Bayes factors (Rouder et al. 2009): under the alternative the standardized effect δ has a Cauchy(0, r) prior (r = √2/2 by default, adjustable), the variance Jeffreys\' prior. Two samples: the pooled t, equal variances, with n = n₁n₂/(n₁ + n₂); paired: the differences as one sample. BF10 = ∫ p(t | δ) p(δ) dδ / p(t | δ = 0), computed as Rouder et al.\'s integral over g on a log scale.' },
        { heading: 'The correlation', text: 'Bivariate ▸ Bayes Factor for the Correlation: the exact likelihood of ρ given r (from the distribution of r) against a beta(1/κ, 1/κ) prior stretched to (−1, 1), κ = 1 uniform by default (Ly, Verhagen and Wagenmakers 2016). Two-sided it equals their closed form with the hypergeometric function.' },
        { heading: 'One-sided', text: 'δ > 0 (or ρ > 0) keeps the half of the prior on that side, doubled: BF+0 = 2·BF10·P(δ > 0 | data) (Morey and Wagenmakers 2014), the posterior probability from the noncentral t (or the correlation\'s) likelihood.' },
        { heading: 'Reading them', text: 'The numbers are shown as they are, without verbal labels. They depend on the prior: a wider prior (larger r or κ) expects larger effects and favours the null more when the effect is small. Right click a table for log₁₀ BF10, which is easier to read when BF10 is very large or small.' },
      ],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:nonpar': {
      kicker: 'Oneway', title: 'Nonparametric tests',
      lead: 'Rank tests of whether the levels come from the same distribution: Wilcoxon (Kruskal-Wallis), the median test and van der Waerden\'s normal scores, as linear rank tests; Kolmogorov-Smirnov for two levels.',
      sections: [{ heading: 'Forms', text: 'The chi-square is (N−1)Σ nᵢ(meanᵢ − mean)²/Σ(a − mean)² of the scores a, which for Wilcoxon scores is Kruskal-Wallis\' H with ties corrected, and for median scores (N−1)/N times the Pearson chi-square of scipy\'s median_test. The two-sample Z of the Wilcoxon test has a continuity correction of 0.5.' },
        { heading: 'Multiple comparisons', text: 'Wilcoxon each pair (no adjustment), Steel-Dwass (all pairs, studentized range), Steel with a control, and Dunn\'s joint-rank comparisons with Bonferroni adjustment (statsmodels multipletests).' },
        { heading: 'Brunner-Munzel', text: 'The probability that a value of one level exceeds one of another, with its interval and a test that does not assume equal distributions; see its own (i).' }],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:brunner': {
      kicker: 'Oneway', title: 'Brunner-Munzel and the probability of superiority',
      lead: 'P = P(Y₁ > Y₂) + ½P(Y₁ = Y₂): the chance that a random value of one level exceeds a random value of the other, ties counted half. It is the Mann-Whitney U over n₁n₂, estimated from the ranks, and ½ means neither level tends to be larger.',
      sections: [
        { heading: 'The test', text: 'The Brunner-Munzel test of P = ½ estimates the variance of P̂ from the placements of each level without assuming, as the Wilcoxon test does, that the two distributions are the same when there is no effect: it stays valid when the levels differ in spread or shape and with ties. The p-value uses the t distribution with Welch-Satterthwaite type degrees of freedom (Brunner and Munzel 2000), which they recommend for up to 50 values per level; statsmodels rank_compare_2indep.' },
        { heading: 'Several levels', text: 'Each pair, a later level against an earlier one; the Holm-adjusted p-values are among the optional columns (right click).' },
        { heading: 'Equivalence Test', text: 'Two one-sided tests that P lies between two bounds, such as 0.4 and 0.6 (statsmodels tost_prob_superior): the levels are stochastically equivalent when both reject.' },
        { heading: 'Not in JMP', text: 'JMP\'s closest are the Wilcoxon test, whose null hypothesis is identical distributions, and the Hodges-Lehmann estimate of a shift.' },
      ],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:rates': {
      kicker: 'Oneway', title: 'Compare Rates',
      lead: 'Y counts events (whole numbers of zero or more), each row a unit observed for its Exposure: time, person-years, area. A level\'s rate is its total count over its total exposure; without an exposure every row is one unit.',
      sections: [
        { heading: 'The comparisons', choices: [['Ratio', 'rate₁/rate₂; 1 is no difference. Score (the default), Wald, log-ratio, square-root, exact conditional (binomial, given the total count), mid-p and E-tests (Gu et al. 2008).'], ['Difference', 'rate₁ − rate₂; 0 is no difference. Score, Wald and E-tests (Ng et al. 2007).']] },
        { heading: 'Intervals', text: 'The score interval inverts the score test; the exact conditional interval is the Clopper-Pearson interval of the binomial count₁ out of count₁ + count₂, turned into a ratio; MOVER combines each rate\'s own interval. With a zero count some intervals are not defined, and the score interval is found by root finding here when statsmodels\' own search fails.' },
        { heading: 'Every level together', text: 'The likelihood-ratio test of a Poisson GLM with the log exposure as offset: a rate for each level against one for all. Its Pearson χ²/DF well above 1 means overdispersion: the counts vary more than a Poisson allows and every test here is too optimistic; Count Regression fits a negative binomial.' },
        { heading: 'Not in JMP', text: 'JMP compares counts with a Poisson Generalized Linear Model in Fit Model; it has no exact, score or E-test comparison of two rates.' },
      ],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:twoprop': {
      kicker: 'Contingency', title: 'Two Sample Test for Proportions',
      lead: 'The proportion of one response level in the first X level against the second: their difference, their ratio (the relative risk) or their odds ratio, with a confidence interval and a test that they are equal. The Response Level item chooses the response level.',
      sections: [
        { heading: 'The methods', choices: [['Wald', 'estimate ± z·SE: poor with small counts or proportions near 0 or 1'], ['Agresti-Caffo (adjusted Wald)', 'one success and one failure added to each group: JMP\'s interval and test'], ['Newcombe (hybrid score)', 'from the two Wilson intervals; an interval only'], ['Miettinen-Nurminen (score)', 'inverts the score test, with the n/(n − 1) factor; recommended by Fagerland, Lydersen and Laake (2015)'], ['Katz, Woolf', 'log and logit Wald intervals; not defined with a zero cell'], ['Adjusted log, Gart', '0.5 added to the counts'], ['Koopman (score)', 'the score interval of the ratio'], ['Independence-smoothed logit', 'the counts shrunk toward independence']] },
        { heading: 'Differences from JMP', text: 'JMP reports only the adjusted Wald difference, with its one- and two-sided tests (the first table here). The ratio and odds ratio, and the other methods, are statsmodels\' confint_proportions_2indep and test_proportions_2indep.' },
      ],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:strata': {
      kicker: 'Contingency', title: 'Cochran Mantel Haenszel and Breslow-Day',
      lead: 'A 2×2 table of X by Y in each level of a grouping column (the strata). The Mantel-Haenszel estimate pools the strata\'s odds ratios; its test asks whether the common odds ratio is 1, the association within strata.',
      sections: [
        { heading: 'Breslow-Day', text: 'Whether the strata share one odds ratio: each stratum\'s first cell against what the pooled odds ratio predicts, a χ² with (strata − 1) DF. Tarone\'s adjustment makes it a proper χ² when the pooled estimate is the Mantel-Haenszel one; it is usually tiny. A small p-value means the association differs between strata, and one pooled odds ratio does not describe them.' },
        { heading: 'The rest', text: 'The Mantel-Haenszel test with and without the continuity correction (R\'s mantelhaen.test uses it), the pooled odds ratio with its Robins-Breslow-Greenland interval, the pooled relative risk, and each stratum\'s own odds ratio.' },
        { heading: 'Not in JMP', text: 'JMP\'s Cochran Mantel Haenszel report gives the general-association statistics of SAS\'s PROC FREQ (correlation of scores, row and column scores, general association), not the Breslow-Day test; statsmodels does not compute those.' },
      ],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:variances': {
      kicker: 'Oneway', title: 'Unequal Variances',
      lead: 'Tests that the levels have the same variance: O\'Brien\'s, Brown-Forsythe (absolute deviations from the median), Levene (from the mean) and Bartlett\'s (sensitive to non-normality), and for two levels the F test. Welch\'s ANOVA then tests the means without assuming equal variances.',
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:logistic': {
      kicker: 'Logistic', title: 'Logistic fits',
      lead: 'The probability of each level of Y as a function of X. Two levels: the log odds of the first level (the target) are a line in X (statsmodels Logit, or GLM with frequency weights). More levels: nominal, the log odds of each level against the last (MNLogit); ordinal, cumulative logits with one slope (OrderedModel).',
      sections: [{ heading: 'The plot', text: 'The curves are the cumulative probabilities; each point sits at a random height within the band of its level at its X, so the density of points follows the probabilities.' },
        { heading: 'The tests', text: 'The Whole Model Test is the likelihood ratio chi-square against the model without X; RSquare (U) is the fraction of the -LogLikelihood it removes. The parameter tests are Wald chi-squares.' }],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:contingency': {
      kicker: 'Contingency', title: 'Contingency tests',
      lead: 'Whether Y depends on X: the likelihood ratio (G²) and Pearson chi-squares of the table (scipy chi2_contingency), and Fisher\'s exact test for small tables. -LogLike is half of G², RSquare (U) its share of the entropy of Y.',
      sections: [{ heading: 'Warnings', text: 'With many expected counts below 5 the chi-square p-values are approximate; Fisher\'s exact test does not have that problem.' }],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:measures': {
      kicker: 'Contingency', title: 'Measures of Association',
      lead: 'Gamma, Kendall\'s tau-b, Stuart\'s tau-c and Somers\' D measure an ordered association; lambda and the uncertainty coefficients the reduction in the error of predicting one variable from the other; Cramér\'s V a general association.',
      sections: [{ heading: 'The numbers', text: 'Computed from the table by the formulas of SAS PROC FREQ, which JMP follows, with their asymptotic standard errors; tau-b, tau-c and Somers\' D agree with scipy\'s kendalltau and somersd, Cramér\'s V is scipy\'s.' }],
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:fitybyx:weights': {
      kicker: 'Fit Y by X', title: 'Weight and Freq',
      lead: 'Freq counts a row that many times; Weight weights it. Least squares uses both, with the degrees of freedom from Freq. Tests whose statsmodels or scipy function takes no weights count whole-number frequencies by repeating rows and do not use Weight; the report says so.',
      more: { label: 'Fit Y by X', id: 'help-p-fitybyx' },
    },
    'p:matchedpairs': {
      kicker: 'Specialized Modeling', title: 'Matched Pairs',
      lead: 'Two measurements of each unit (before and after, left and right): the difference, second minus first, against zero. The Tukey mean-difference plot shows each pair\'s difference against its mean, with the mean difference and its confidence interval.',
      sections: [
        { heading: 'Roles', choices: [['Y, Paired Response', 'Two columns, or more: then every pair of them. Binary columns (0/1, yes/no) also get Cochran\'s Q and McNemar\'s tests.'], ['X, Grouping', 'Optional: the differences and the means compared across its levels.'], ['By', 'A separate analysis for each level.']] },
        { heading: 'Tests', text: 'The paired t test (statsmodels DescrStatsW of the differences); from the red triangle Wilcoxon\'s signed-rank test (scipy; S is the signed-rank sum over two, as JMP shows it) and the sign test (statsmodels sign_test).' },
      ],
      more: { label: 'Matched Pairs', id: 'help-p-matchedpairs' },
    },
    'p:matchedpairs:binary': {
      kicker: 'Matched Pairs', title: 'Cochran\'s Q and McNemar',
      lead: 'Binary responses of the same subjects: two or more ratings, tests or conditions, each a success or not (0/1, yes/no). Cochran\'s Q tests whether every response has the same probability of success; McNemar\'s test compares two of them.',
      sections: [
        { heading: 'Cochran\'s Q', text: 'Q = (k − 1)(kΣC²ⱼ − N²)/(kN − ΣR²ᵢ), with Cⱼ the successes of response j, Rᵢ those of row i and N all of them, against χ² with k − 1 DF (statsmodels cochrans_q). Only rows with both outcomes carry information; it uses the rows with every response.' },
        { heading: 'McNemar', text: 'For a pair only the discordant rows count: b with a success in the first response only, c in the second only; χ² = (b − c)²/(b + c), or (|b − c| − 1)² with the continuity correction, and the exact binomial test of b out of b + c (statsmodels mcnemar). With several pairs the Holm-adjusted p-values are among the optional columns.' },
        { heading: 'Success Level', text: 'The tests are the same whichever value counts as the success; the proportions shown are of the success level (by default the second value, 1 or yes).' },
        { heading: 'Not in JMP', text: 'JMP has no Cochran\'s Q; for one pair its closest is Fit Y by X ▸ Contingency ▸ Agreement Statistic, whose Bowker test of a 2×2 table is McNemar\'s χ² without the correction.' },
      ],
      more: { label: 'Matched Pairs', id: 'help-p-matchedpairs' },
    },
  };

  function launchMap() {
    const cell = (label, yt, xt) => el('div', { class: 'sm-fyx-map-cell' }, el('strong', { text: label }), el('span', null, SM.util.typeIcon(yt), ' by ', SM.util.typeIcon(xt)));
    return el('div', { class: 'sm-fyx-map', role: 'note', 'aria-label': 'The analysis for each pair of modeling types' },
      el('div', { class: 'sm-fyx-map-head' }, 'Y continuous'), cell('Bivariate', 'continuous', 'continuous'), cell('Oneway', 'continuous', 'nominal'),
      el('div', { class: 'sm-fyx-map-head' }, 'Y categorical'), cell('Logistic', 'nominal', 'continuous'), cell('Contingency', 'nominal', 'nominal'),
      el('div'), el('div', { class: 'sm-fyx-map-foot', text: 'X continuous' }), el('div', { class: 'sm-fyx-map-foot', text: 'X categorical' }));
  }

  SM.platforms.register({
    id: 'fitybyx', label: 'Fit Y by X', menu: 'Analyze', order: 20, info: 'p:fitybyx', topics: TOPICS,
    about: 'Each Y against each X, the analysis chosen by their modeling types: Bivariate (scatterplot with line, polynomial, special, spline, smoother, robust, orthogonal and quantile fits, density ellipses), Oneway (ANOVA, t tests, Student\'s, Tukey\'s and Dunnett\'s comparisons, rank tests and their comparisons, unequal variances, equivalence, power, ANOM, blocks), Logistic (binary, nominal and ordinal, odds ratios, ROC and lift curves, inverse prediction) and Contingency (mosaic plot, crosstab, chi-square and exact tests, measures of association, kappa, relative risk, Cochran-Mantel-Haenszel, trend test, correspondence analysis). Beyond JMP: the Brunner-Munzel test of the probability of superiority and its equivalence test, the comparison of Poisson rates (with an exposure) by score, exact, Wald and E-tests with a Poisson GLM test of every level, statsmodels\' methods for two proportions (difference, relative risk, odds ratio), the Breslow-Day test of equal odds ratios across strata, effect sizes with intervals (Cohen\'s d and Hedges\' g, exact from the noncentral t; d* for unequal variances; η², ε² and ω², exact from the noncentral F), JZS Bayes factors of the two-sample t test and Bayes factors of the correlation (two- and one-sided), and Games-Howell comparisons for unequal variances.',
    uses: ['statsmodels OLS, WLS, RLM, QuantReg (fits); lowess', 'statsmodels.stats.multicomp.pairwise_tukeyhsd; weightstats (CompareMeans, ttost_ind)', 'statsmodels.stats.oneway.anova_oneway; power.FTestAnovaPower; multitest.multipletests',
      'statsmodels.stats.nonparametric.rank_compare_2indep (Brunner-Munzel, tost_prob_superior)', 'statsmodels.stats.rates (test_poisson_2indep, confint_poisson_2indep, confint_poisson); GLM Poisson',
      'statsmodels Logit, GLM Binomial, MNLogit, OrderedModel', 'statsmodels.stats.contingency_tables (Table, Table2x2, SquareTable, StratifiedTable, mcnemar); inter_rater.cohens_kappa',
      'statsmodels.stats.proportion (test_proportions_2indep, confint_proportions_2indep)',
      'scipy.stats (dunnett, studentized_range, kruskal, ks_2samp, levene, bartlett, chi2_contingency, fisher_exact, multivariate_t, gaussian_kde)', 'scipy.interpolate.make_smoothing_spline',
      'scipy.stats.nct, ncf (exact effect-size intervals); scipy.integrate.quad, scipy.special.hyp2f1 (Bayes factors)'],
    launch: {
      lead: 'Cast one or more columns into each role; every Y is analysed against every X. The modeling types of the pair choose the analysis:',
      roles: [
        { key: 'y', label: 'Y, Response', min: 1, hint: 'required: one or more' },
        { key: 'x', label: 'X, Factor', min: 1, hint: 'required: one or more' },
        { key: 'block', label: 'Block', max: 1, types: ['ordinal', 'nominal'], hint: 'optional (Oneway)' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric', info: 'p:fitybyx:weights' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric', info: 'p:fitybyx:weights' },
        { key: 'by', label: 'By', hint: 'optional' },
      ],
      extra: () => ({ el: launchMap(), read: () => null }),
      validate(spec, table) {
        const pairs = pairsOf(spec, table);
        if (!pairs.length) return 'Y and X are the same column: choose different columns.';
        if ((spec.roles.block || []).length && !pairs.some(([y, x]) => kindOf(y, x) === 'oneway')) return 'Block is for a continuous Y by a categorical X (Oneway).';
        return null;
      },
    },
    title(spec, table) {
      const pairs = pairsOf(spec, table);
      if (pairs.length === 1) return pairTitle(kindOf(pairs[0][0], pairs[0][1]), pairs[0][0], pairs[0][1]);
      return 'Fit Y by X';
    },
    triangle(ctx) {
      const pairs = pairsOf(ctx.spec, ctx.table);
      if (pairs.length === 1) return pairMenu(ctx, kindOf(pairs[0][0], pairs[0][1]), pairs[0][0], pairs[0][1]);
      return allPairsMenu(ctx);
    },
    async render(ctx) {
      healScopes(ctx);
      const pairs = pairsOf(ctx.spec, ctx.table);
      if (!pairs.length) { ctx.container.append(ctx.warn('No pair of different columns in Y and X.')); return; }
      if (pairs.length === 1) {
        const [y, x] = pairs[0];
        await RENDER[kindOf(y, x)](ctx, y, x, ctx.top, scopeOf(y, x));
        return;
      }
      const per = ctx.opt('perRow', 0);
      const wrap = el('div', { class: `sm-fyx-group${per > 0 ? ' is-rows' : ''}` });
      if (per > 0) wrap.style.setProperty('--per-row', String(per));
      ctx.container.append(wrap);
      for (const [y, x] of pairs) {
        const kind = kindOf(y, x);
        const ob = ctx.outline(pairTitle(kind, y, x), { parent: wrap, level: 1, key: `pair:${scopeOf(y, x)}`, menu: () => pairMenu(ctx, kind, y, x) });
        try { await RENDER[kind](ctx, y, x, ob, scopeOf(y, x)); } catch (e) { console.error(e); ob.add(ctx.error(e)); }
      }
    },
  });

  /* ======================================================================
     MATCHED PAIRS
     ====================================================================== */
  async function matchedPair(ctx, y1, y2, host, sc, group) {
    const o = (k, d) => ctx.opt(k, d, sc);
    const { res: r, error } = await safeCall(ctx, 'matchedpairs.analyze', { y1: y1.name, y2: y2.name, group: group ? group.name : null, alpha: ctx.alpha, where: ctx.where || [] });
    const ob = ctx.outline(`Difference: ${y2.name}-${y1.name}`, { parent: host, key: `mp:${sc}`, menu: () => mpMenu(ctx, sc), info: 'p:matchedpairs' });
    if (error) { ob.add(problem(ctx, error)); return; }
    const lvl = `${fmt(100 * (1 - ctx.alpha))}%`;
    const plots = [];
    if (o('plotMean', true)) {
      const colors = group && r.group_code ? r.group_code.map((g) => PALETTE[g % PALETTE.length]) : undefined;
      const lines = [
        { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: GREY, width: 1 } },
        { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: r.diff, y1: r.diff, line: { color: RED, width: 1.6 } },
        { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: r.lower, y1: r.lower, line: { color: RED, width: 1, dash: 'dash' } },
        { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: r.upper, y1: r.upper, line: { color: RED, width: 1, dash: 'dash' } },
      ];
      plots.push(ctx.plot([{ type: r.n > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: r.m, y: r.d, rows: r.rows, marker: colors ? { color: colors, size: 6 } : { size: 6 }, name: 'Pairs' }],
        { xaxis: { title: { text: `Mean: (${y1.name}+${y2.name})/2` }, zeroline: false }, yaxis: { title: { text: `Difference: ${y2.name}-${y1.name}` }, zeroline: false }, shapes: lines }, { width: availWidth(ctx, 480), height: 360, title: `${y2.name}-${y1.name} by mean` }));
    }
    if (o('plotRow', false)) {
      plots.push(ctx.plot([{ type: 'scatter', mode: 'markers', x: r.rows.map((x) => x + 1), y: r.d, rows: r.rows, marker: { size: 6 } }],
        { xaxis: { title: { text: 'Row' } }, yaxis: { title: { text: `Difference: ${y2.name}-${y1.name}` } }, shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: r.diff, y1: r.diff, line: { color: RED, width: 1.4 } }] }, { width: availWidth(ctx, 420), height: 300, title: `${y2.name}-${y1.name} by row` }));
    }
    if (plots.length) ob.add(ctx.row(...plots));
    ob.add(ctx.row(ctx.kv([[y2.name, r.mean2], [y1.name, r.mean1], ['Mean Difference', r.diff], ['Std Error', r.se], [`Upper ${lvl}`, r.upper], [`Lower ${lvl}`, r.lower], ['N', r.n, 'int'], ['Correlation', r.r]]),
      ctx.kv([['t-Ratio', r.t], ['DF', r.df], ['Prob > |t|', r.p, 'p'], ['Prob > t', r.p_greater, 'p'], ['Prob < t', r.p_less, 'p']])));
    if (o('wilcoxon', false)) {
      const w = ctx.outline('Wilcoxon Signed Rank', { parent: ob, key: `mpw:${sc}` });
      if (r.wilcoxon) w.add(ctx.kv([['S', r.wilcoxon.S], ['Prob>|S|', r.wilcoxon.p_two, 'p'], ['Prob>S', r.wilcoxon.p_greater, 'p'], ['Prob<S', r.wilcoxon.p_less, 'p'], ['Nonzero differences', r.wilcoxon.n, 'int']]),
        ctx.note('S = Σ sign(d)·rank(|d|)/2 over the nonzero differences; the p-values are scipy.stats.wilcoxon\'s.'));
      else w.add(ctx.warn('Every difference is zero.'));
    }
    if (o('sign', false)) {
      const s = ctx.outline('Sign Test', { parent: ob, key: `mps:${sc}` });
      if (r.sign) s.add(ctx.kv([['M (positive − negative)/2', r.sign.M], ['Prob>=|M|', r.sign.p_two, 'p'], ['Prob>=M', r.sign.p_greater, 'p'], ['Prob<=M', r.sign.p_less, 'p'], ['Positive', r.sign.n_pos, 'int'], ['Negative', r.sign.n_neg, 'int']]),
        ctx.note('statsmodels sign_test; the one-sided p-values are the binomial test of the positive differences.'));
      else s.add(ctx.warn('Every difference is zero.'));
    }
    const mpay = { y1: y1.name, y2: y2.name, alpha: ctx.alpha, where: ctx.where || [] };
    if (o('mpEffect', false)) {
      await effectOutline(ctx, ob, `mpe:${sc}`, 'matchedpairs.effect', mpay,
        (e) => `The mean difference ${y2.name} − ${y1.name} standardized two ways. d_z divides by the standard deviation of the differences (${fmt(e.sd_diff)}): the paired t is d_z√n, and the interval is exact, from the noncentral t (δ_z = λ/√n; Steiger and Fouladi 1997); Hedges' g_z = J(n − 1)·d_z. d_av divides by √((s₁² + s₂²)/2) and does not grow with the correlation of the pair (r = ${fmt(e.r)}), so it compares with a two-group d (Cumming 2012; Lakens 2013); its interval is Bonett's (2008). Right click for the standard error.`,
        () => ctx.set('mpEffect', false, sc));
    }
    const mbf = o('mpBf', null);
    if (mbf) {
      await bayesOutline(ctx, ob, `mpbf:${sc}`, 'matchedpairs.bayes', { ...mpay, r: mbf.r },
        (b) => [['t (paired)', b.t], ['DF', b.df], ['N', b.n], ['Prior scale r', b.r]],
        (b) => `The JZS Bayes factor of the paired t test (Rouder et al. 2009): the differences ${y2.name} − ${y1.name} as one sample, a Cauchy(0, ${fmt(b.r)}) prior on δ = mean difference/SD under the alternative; a one-sided alternative keeps the prior's half on its side, doubled. ${BF_NOTE}`,
        () => [{ label: 'Change Prior…', action: () => priorDialog(ctx, sc, 'mpBf', 'Bayes Factor: paired t test') }, { label: 'Remove', action: () => ctx.set('mpBf', null, sc) }]);
    }
    if (r.across) {
      const a = ctx.outline('Across Groups', { parent: ob, key: `mpa:${sc}` });
      a.add(ctx.rt({ columns: [{ key: 'lv', label: group.name, fmt: 'text' }, { key: 'count', label: 'Count', fmt: 'int' }, { key: 'diff', label: 'Mean Difference' }, { key: 'mean', label: 'Mean Mean' }], rows: r.across.map((g) => ({ ...g, lv: lvText(group, g.level) })) }, { sortable: false }));
      if (r.across_tests) a.add(ctx.rt({ columns: [{ key: 'what', label: 'Test Across Groups', fmt: 'text' }, { key: 'f', label: 'F Ratio' }, { key: 'dfn', label: 'DFNum', fmt: 'int' }, { key: 'dfd', label: 'DFDen', fmt: 'int' }, { key: 'p', label: 'Prob > F', fmt: 'p' }], rows: r.across_tests }, { sortable: false }),
        ctx.note('One-way ANOVAs (scipy f_oneway) of the differences and of the pair means across the groups.'));
    }
    ob.add(ctx.code(r.code));
  }

  function mpMenu(ctx, sc) {
    return [
      ctx.check('Plot Dif by Mean', 'plotMean', sc, true),
      ctx.check('Plot Dif by Row', 'plotRow', sc, false),
      ctx.check('Wilcoxon Signed Rank', 'wilcoxon', sc, false),
      ctx.check('Sign Test', 'sign', sc, false),
      ctx.check('Effect Size', 'mpEffect', sc, false),
      { label: 'Bayes Factor…', checked: !!ctx.opt('mpBf', null, sc), action: () => priorDialog(ctx, sc, 'mpBf', 'Bayes Factor: paired t test') },
      { label: 'Set α Level', submenu: () => alphaMenu(ctx) },
    ];
  }

  function mpPairs(spec, table) {
    const ys = ((spec.roles && spec.roles.y) || []).map((id) => table.col(id)).filter(Boolean);
    const out = [];
    for (let i = 0; i < ys.length; i++) for (let j = i + 1; j < ys.length; j++) out.push([ys[i], ys[j]]);
    return out;
  }

  /* Binary responses: the Y columns hold two values in all (0/1, yes/no).
     Returns the values as text, or null. */
  function mpBinaryValues(cols, rows) {
    const vals = new Set();
    for (const c of cols) for (const r of rows) { const v = c.values[r]; if (isMissing(v)) continue; vals.add(String(v)); if (vals.size > 2) return null; }
    return vals.size === 2 ? [...vals] : null;
  }

  /* Cochran's Q and McNemar's test of each pair (statsmodels cochrans_q and
     mcnemar; not in JMP, whose closest is Contingency's Agreement
     Statistic, Bowker's test, for one pair). */
  async function mpBinaryReport(ctx, ys) {
    const o = (k, d) => ctx.opt(k, d);
    const exact = o('mcExact', true), correction = o('mcCorrection', false);
    const { res: r, error } = await safeCall(ctx, 'matchedpairs.binary', { columns: ys.map((c) => c.name), success: o('success', null), exact, correction, alpha: ctx.alpha, where: ctx.where || [] });
    const successMenu = () => (r && r.values ? [{ label: 'Success Level', submenu: () => r.values.map((v) => ({ label: v, checked: r.success === v, action: () => ctx.set('success', v) })) }] : []);
    if (o('cochranQ', true)) {
      const ob = ctx.outline('Cochran\'s Q Test', { key: 'cochranq', info: 'p:matchedpairs:binary', menu: () => [...successMenu(), { separator: true }, { label: 'Remove', action: () => ctx.set('cochranQ', false) }] });
      if (error) ob.add(problem(ctx, error));
      else {
        ob.add(ctx.rt({ columns: [{ key: 'column', label: 'Column', fmt: 'text' }, { key: 'n', label: 'N', fmt: 'int' }, { key: 'count', label: `Count ${r.success}`, fmt: 'int' }, { key: 'prop', label: `Proportion ${r.success}` }], rows: r.columns }, { sortable: false }));
        if (r.cochran) ob.add(ctx.kv([['Cochran\'s Q', r.cochran.q], ['DF', r.cochran.df, 'int'], ['Prob>ChiSq', r.cochran.p, 'p'], ['Rows with every response', r.cochran.n, 'int'], ['Rows with both outcomes', r.cochran.discordant, 'int']]));
        ob.add(ctx.note(`Whether the ${ys.length} responses have the same probability of ${r.success}: Q = (k − 1)(kΣC²ⱼ − N²)/(kN − ΣR²ᵢ) from the column counts C and row counts R of ${r.success}, against χ² with k − 1 DF, on the rows with every response. For two responses it is McNemar's χ² without the continuity correction. Not in JMP.`),
          notesOf(ctx, r.notes.filter((t) => !/discordant pair/.test(t))));
      }
    }
    if (o('mcnemar', true)) {
      const ob = ctx.outline('McNemar Tests', { key: 'mcnemar', info: 'p:matchedpairs:binary', menu: () => [
        ctx.check('Exact Test', 'mcExact', null, true), ctx.check('Continuity Correction', 'mcCorrection', null, false), ...successMenu(),
        { separator: true }, { label: 'Remove', action: () => ctx.set('mcnemar', false) }] });
      if (error) ob.add(problem(ctx, error));
      else {
        const s = r.success, f = r.failure;
        const cols = [{ key: 'a', label: 'Y1', fmt: 'text' }, { key: 'b', label: 'Y2', fmt: 'text' }, { key: 'n', label: 'N', fmt: 'int' },
          { key: 'n11', label: `Both ${s}`, fmt: 'int', hidden: true }, { key: 'n10', label: `Y1 ${s}, Y2 ${f}`, fmt: 'int' }, { key: 'n01', label: `Y1 ${f}, Y2 ${s}`, fmt: 'int' }, { key: 'n00', label: `Both ${f}`, fmt: 'int', hidden: true },
          { key: 'p1', label: `Prop ${s} Y1` }, { key: 'p2', label: `Prop ${s} Y2` }, { key: 'diff', label: 'Difference Y2 − Y1' },
          { key: 'chisq', label: 'ChiSquare' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }];
        if (exact) cols.push({ key: 'p_exact', label: 'Exact Prob', fmt: 'p' });
        if (r.pairs.some((p) => p.p_holm != null)) cols.push({ key: 'p_holm', label: 'Holm-adjusted p', fmt: 'p', hidden: true });
        ob.add(ctx.rt({ columns: cols, rows: r.pairs.map((p) => ({ ...p, a: r.names[p.i], b: r.names[p.j] })) }, { sortable: r.pairs.length > 2 }),
          ctx.note(`McNemar's test that the two responses have the same proportion of ${s}: only the discordant pairs count, χ² = ${correction ? '(|b − c| − 1)²' : '(b − c)²'}/(b + c) on 1 DF${exact ? '; the exact test is the binomial test of b out of b + c with p = ½' : ''}. Each pair on the rows where both responses are present. JMP's closest is Fit Y by X ▸ Contingency ▸ Agreement Statistic, whose Bowker test is this χ² without the correction; it has no exact McNemar test. Right click for the concordant counts${r.pairs.length > 1 ? ' and Holm-adjusted p-values' : ''}.`),
          notesOf(ctx, r.notes.filter((t) => /discordant pair/.test(t))));
      }
    }
    if (r && !error) ctx.container.append(ctx.code(r.code));
  }

  SM.platforms.register({
    id: 'matchedpairs', label: 'Matched Pairs', menu: 'Analyze/Specialized Modeling', order: 40, info: 'p:matchedpairs',
    about: 'Two paired responses (with more, every pair): the difference against zero by the paired t test, Wilcoxon\'s signed rank and the sign test, the Tukey mean-difference plot, and with a grouping column the differences and means compared across its levels. Binary responses (two or more, such as yes/no ratings of the same subjects): Cochran\'s Q test and McNemar\'s test of each pair, exact or with a continuity correction, which JMP does not have. Also beyond JMP: the effect sizes d_z (exact interval), g_z and d_av (Bonett\'s interval), and the JZS Bayes factor of the paired t test.',
    uses: ['statsmodels.stats.weightstats.DescrStatsW', 'statsmodels.stats.descriptivestats.sign_test', 'statsmodels.stats.contingency_tables.cochrans_q, mcnemar', 'statsmodels.stats.multitest.multipletests (Holm)', 'scipy.stats.wilcoxon, pearsonr, f_oneway, binomtest', 'scipy.stats.nct, scipy.integrate.quad (effect sizes, Bayes factors)'],
    launch: {
      lead: 'Cast the two paired measurements (or more: every pair is analysed) into Y; the difference is the second minus the first. Binary responses (0/1, yes/no) get Cochran\'s Q and McNemar\'s tests.',
      roles: [
        { key: 'y', label: 'Y, Paired Response', min: 2, types: ['continuous', 'ordinal', 'nominal'], hint: 'required: two or more continuous, or binary' },
        { key: 'x', label: 'X, Grouping', max: 1, types: ['ordinal', 'nominal'], hint: 'optional' },
        { key: 'by', label: 'By', hint: 'optional' },
      ],
      validate(spec, table) {
        const ys = ((spec.roles && spec.roles.y) || []).map((id) => table.col(id)).filter(Boolean);
        if (!ys.some((c) => c.isCategorical)) return null;
        if (!mpBinaryValues(ys, Array.from({ length: table.nrows }, (_, i) => i))) return 'Ordinal and nominal responses must be binary, with two values in all (yes/no): Matched Pairs then tests them with Cochran\'s Q and McNemar\'s test.';
        return null;
      },
    },
    title: (spec) => ((spec.roles.y || []).length > 2 ? 'Matched Pairs (every pair)' : 'Matched Pairs'),
    triangle(ctx) {
      const ys = ctx.roles('y');
      const binary = ys.length >= 2 && mpBinaryValues(ys, ctx.rows);
      const numeric = ys.every((c) => c.isNumeric && !c.isCategorical);
      const bin = binary ? [ctx.check('Cochran\'s Q Test', 'cochranQ', null, true), ctx.check('McNemar Tests', 'mcnemar', null, true), numeric ? ctx.check('Paired Differences', 'mpDiffs', null, true) : null, { separator: true }] : [];
      const pairs = mpPairs(ctx.spec, ctx.table);
      if (pairs.length === 1 && numeric) return [...bin, ...mpMenu(ctx, `${pairs[0][0].id}~${pairs[0][1].id}`)].filter(Boolean);
      return [...bin, { label: 'Set α Level', submenu: () => alphaMenu(ctx) }].filter(Boolean);
    },
    async render(ctx) {
      healScopes(ctx);
      const ys = ctx.roles('y');
      const binary = ys.length >= 2 && mpBinaryValues(ys, ctx.rows);
      const numeric = ys.every((c) => c.isNumeric && !c.isCategorical);
      if (binary && (ctx.opt('cochranQ', true) || ctx.opt('mcnemar', true))) await mpBinaryReport(ctx, ys);
      if (!numeric) {
        const one = !binary && (() => { const v = new Set(); for (const c of ys) for (const r of ctx.rows) if (!isMissing(c.values[r])) v.add(String(c.values[r])); return v.size < 2; })();
        ctx.container.append(binary ? ctx.note('The paired t test, Wilcoxon\'s signed rank and the sign test need numeric responses; these binary responses get Cochran\'s Q and McNemar\'s tests.')
          : one ? ctx.warn('Every response here has the same value: there is nothing to compare.')
            : ctx.warn('Ordinal and nominal responses must be binary (two values in all) for Cochran\'s Q and McNemar\'s tests.'));
        return;
      }
      if (binary && !ctx.opt('mpDiffs', true)) return;
      const pairs = mpPairs(ctx.spec, ctx.table);
      const group = ctx.role('x');
      for (const [a, b] of pairs) await matchedPair(ctx, a, b, ctx.top, `${a.id}~${b.id}`, group);
    },
  });

  SM.fitybyx = Object.freeze({ kindOf, pairTitle, probsAt, pairsOf });
}(typeof self !== 'undefined' ? self : this));
