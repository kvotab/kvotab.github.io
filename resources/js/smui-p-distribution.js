/* ==========================================================================
   SMUI.HTML: ANALYZE > DISTRIBUTION

   One outline per column. Continuous: histogram and outlier box plot,
   quantiles, summary statistics, and from the red triangle the normal
   quantile plot, CDF plot, stem and leaf, tests of the mean and the
   standard deviation, equivalence, confidence, prediction and tolerance
   intervals, capability and fitted distributions, and for counts the test
   of a Poisson rate (with an exposure); Test Mean's effect size and Bayes
   factor. Ordinal and nominal: bar chart, frequencies, confidence intervals
   by a choice of method, mosaic, test of probabilities (and its binomial
   Bayes factor for two levels).

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
  // Confidence Interval Method of the level probabilities (statsmodels proportion_confint)
  const CI_METHODS = [['wilson', 'Wilson Score'], ['agresti_coull', 'Agresti-Coull'], ['jeffreys', 'Jeffreys'], ['beta', 'Clopper-Pearson (exact)'], ['normal', 'Wald']];
  // Test Rate (statsmodels test_poisson and confint_poisson)
  const RATE_TESTS = [['exact-c', 'Exact (central)'], ['midp-c', 'Mid-p (central)'], ['score', 'Score'], ['wald', 'Wald'], ['waldccv', 'Wald, 0.5 added to the variance'], ['sqrt-a', 'Anscombe square root'], ['sqrt-v', 'Vandenbroucke square root'], ['sqrt', 'Square root']];
  const RATE_CIS = [['exact-c', 'Exact (Garwood)'], ['midp-c', 'Mid-p'], ['score', 'Score'], ['jeff', 'Jeffreys'], ['wald', 'Wald'], ['waldccv', 'Wald, 0.5 added to the variance'], ['sqrt-a', 'Anscombe square root']];
  const labelOf = (list, key) => (list.find((m) => m[0] === key) || [key, key])[1];

  /* Whole numbers of zero or more: a column of counts. */
  function isCounts(vals) {
    return vals.length > 0 && vals.every((v) => v >= 0 && Math.abs(v - Math.round(v)) < 1e-9);
  }

  function ciMethodItems(ctx, col) {
    const sc = col.id;
    const cur = ctx.opt('ciMethod', 'wilson', sc);
    return CI_METHODS.map(([k, l]) => ({ label: k === 'wilson' ? `${l} (JMP)` : l, checked: cur === k, action: () => { if (!ctx.opt('ciCat', null, sc)) ctx.set('ciCat', 0.95, sc, { rerun: false }); ctx.set('ciMethod', k, sc); } }));
  }

  async function testRateDialog(ctx, col) {
    const sc = col.id;
    const cur = ctx.opt('testRate', null, sc) || { rate: 1, exposure: null, method: 'exact-c', ci: 'exact-c' };
    const nums = ctx.table.columns.filter((c) => c.isNumeric && !c.isCategorical && c.id !== col.id);
    const v = await SM.ui.form({
      title: `Test Rate: ${col.name}`, info: 'p:distribution:rate',
      lead: `${col.name} counts events; each row is one unit, observed for its exposure (time, person-years, area). The rate is the total count over the total exposure.`,
      fields: [
        { key: 'rate', label: 'Hypothesized rate (events per unit of exposure)', type: 'number', value: cur.rate,
          help: 'The rate the observed one is tested against, in events per unit of exposure (per row when there is no exposure column); it must be above 0.' },
        { key: 'exposure', label: 'Exposure', type: 'select', value: cur.exposure || '', choices: [['', '(none: every row is one unit)'], ...nums.map((c) => [c.id, c.name])],
          help: 'A continuous column with each row\'s exposure (a time, person-years, an area): the rate is the total count over the total exposure, and rows without a positive exposure are left out. None: every row is one unit (Freq counts a row as that many units).' },
        { key: 'method', label: 'Test', type: 'select', value: cur.method || 'exact-c', choices: RATE_TESTS,
          help: 'The test of the total count against the hypothesized rate (statsmodels\' test_poisson). Exact, the default, uses the Poisson tails, the two-sided p-value twice the smaller one; mid-p takes half the probability of the count seen off them; score and Wald are normal approximations, with the variance at the hypothesized or at the estimated rate; the square-root tests transform the count to steady its variance.' },
        { key: 'ci', label: 'Confidence interval', type: 'select', value: cur.ci || 'exact-c', choices: RATE_CIS,
          help: 'The interval of the rate at 1 − α (statsmodels\' confint_poisson). Exact, the default, is Garwood\'s from the gamma distribution: its coverage is at least 1 − α. The mid-p, score, Jeffreys, Wald and Anscombe intervals are approximations, most of them narrower.' },
      ],
      validate: (x) => (x.rate > 0 ? null : 'The hypothesized rate must be positive.'),
    });
    if (v) ctx.set('testRate', { rate: v.rate, exposure: v.exposure || null, method: v.method, ci: v.ci }, sc);
  }

  async function testRateReport(ctx, col, parent, tr) {
    const sc = col.id;
    const ob = ctx.outline('Test Rate', { parent, key: 'testrate', info: 'p:distribution:rate', menu: () => [{ label: 'Change…', action: () => testRateDialog(ctx, col) }, { label: 'Remove Test', action: () => ctx.set('testRate', null, sc) }] });
    const ex = tr.exposure ? ctx.col(tr.exposure) : null;
    if (tr.exposure && !ex) { ob.add(ctx.warn('The exposure column is no longer in the table.')); return; }
    const r = await ctx.call('distribution.test_rate', { column: col.name, rate: tr.rate, exposure: ex ? ex.name : null, method: tr.method || 'exact-c', ci_method: tr.ci || 'exact-c', weight: ctx.name('weight'), freq: ctx.name('freq'), alpha: ctx.alpha });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const lvl = fmt(100 * (1 - ctx.alpha));
    ob.add(ctx.row(
      ctx.kv([['Hypothesized Rate', r.rate0], [`Total ${col.name}`, r.count], [ex ? `Total ${ex.name}` : 'Units', r.exposure], ex ? ['Units', r.units] : null, ['Rate Estimate', r.rate], [`Lower ${lvl}%`, r.lower], [`Upper ${lvl}%`, r.upper]]),
      ctx.kv([['Test Statistic', r.statistic], ['Prob, rate ≠ hypothesized', r.p_two, 'p'], ['Prob, rate > hypothesized', r.p_greater, 'p'], ['Prob, rate < hypothesized', r.p_less, 'p'], ['Pearson χ²/DF', r.dispersion]])),
    ctx.note(`Test: ${labelOf(RATE_TESTS, r.method)} (statsmodels test_poisson${r.method === 'exact-c' ? '; the two-sided p-value doubles the smaller tail' : ''}); interval: ${labelOf(RATE_CIS, r.ci_method)} (confint_poisson). The Pearson χ²/DF of the counts about the rate is near 1 for Poisson counts. Not in JMP, whose closest is Discrete Fit ▸ Poisson: the λ of the fitted distribution, without an exposure or a test.`),
    ...(r.notes || []).map((t) => ctx.note(t)), ctx.code(r.code));
  }

  /* ---- Test Mean's effect size and Bayes factor, Test Probabilities' Bayes
     factor: opt-in, not in JMP ------------------------------------------------ */
  const BF_NOTE = 'BF10 is how many times more likely the data are under the alternative than under the null hypothesis; BF01 = 1/BF10 the other way round. Right click for log₁₀ BF10.';

  async function meanEffect(ctx, col, parent, tm) {
    const ob = ctx.outline('Effect Size', { parent, key: 'tmeffect', info: 'p:distribution:effect', menu: () => [{ label: 'Remove', action: () => ctx.set('tmEffect', false, col.id) }] });
    const r = await ctx.call('distribution.effect', { column: col.name, mu: tm.mu, weight: ctx.name('weight'), freq: ctx.name('freq'), alpha: ctx.alpha });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    ob.add(ctx.rt(r.table, { sortable: false }),
      ctx.note(`(mean − ${fmt(r.mu)})/s with s = ${fmt(r.sd)}: Cohen's d, and Hedges' g = J·d with J = ${fmt(r.j)} (Hedges 1981). The interval of d is exact: the noncentral t distributions whose noncentrality λ puts the t of Test Mean at their upper and lower α/2 points give δ = λ/√n (Steiger and Fouladi 1997); g's is J times it.`),
      ctx.code(r.code));
  }

  async function meanBayes(ctx, col, parent, tm, bf) {
    const ob = ctx.outline('Bayes Factor', { parent, key: 'tmbf', info: 'p:distribution:bayes', menu: () => [{ label: 'Change Prior…', action: () => jzsDialog(ctx, col) }, { label: 'Remove', action: () => ctx.set('tmBf', null, col.id) }] });
    const r = await ctx.call('distribution.bayes_t', { column: col.name, mu: tm.mu, r: bf.r, weight: ctx.name('weight'), freq: ctx.name('freq') });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    ob.add(ctx.row(ctx.rt(r.table, { sortable: false }), ctx.kv([['t', r.t], ['DF', r.df], ['N', r.n], ['Prior scale r', r.r]])),
      ctx.note(`The JZS Bayes factor of the one-sample t test (Rouder et al. 2009): a Cauchy(0, ${fmt(r.r)}) prior on δ = (μ − ${fmt(r.mu)})/σ under the alternative; a one-sided alternative keeps the prior's half on its side, doubled. ${BF_NOTE}`),
      ctx.code(r.code));
  }

  async function jzsDialog(ctx, col) {
    const cur = ctx.opt('tmBf', null, col.id) || { r: Math.SQRT1_2 };
    const v = await SM.ui.form({
      title: `Bayes Factor: ${col.name}`, info: 'p:distribution:bayes',
      lead: 'Under the alternative the standardized effect δ = (μ − μ₀)/σ has a Cauchy prior centred at 0; its scale r is the effect as likely to be exceeded as not. √2/2 ≈ 0.707 is the default of Rouder et al. (2009) and JASP.',
      fields: [{ key: 'r', label: 'Scale r of the Cauchy prior on δ', type: 'number', value: cur.r,
        help: 'Above 0. Half of the prior\'s weight lies on effects |δ| below r: √2/2 ≈ 0.707 (the default, JASP\'s) expects medium effects, 1 wider ones, a smaller r small ones. A wider prior favours the null hypothesis more when the effect is small.' }],
      validate: (x) => (x.r > 0 ? null : 'The scale must be positive.'),
    });
    if (v) ctx.set('tmBf', { r: v.r }, col.id);
  }

  async function probsBayes(ctx, col, parent, tp, bf) {
    const ob = ctx.outline('Bayes Factor', { parent, key: 'tpbf', info: 'p:distribution:bayes', menu: () => [{ label: 'Change Prior…', action: () => betaDialog(ctx, col) }, { label: 'Remove', action: () => ctx.set('tpBf', null, col.id) }] });
    const r = await ctx.call('distribution.bayes_binom', { column: col.name, probs: tp, a: bf.a, b: bf.b, weight: ctx.name('weight'), freq: ctx.name('freq') });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const lv = SM.grid.cellText(col, r.level);
    ob.add(ctx.row(ctx.rt(r.table, { sortable: false }), ctx.kv([[`Count ${lv}`, r.k], ['N', r.n], [`Hypothesized P(${lv})`, r.p0], ['Prior a', r.a], ['Prior b', r.b]])),
      ctx.note(`The binomial Bayes factor of the count of ${lv}: a beta(${fmt(r.a)}, ${fmt(r.b)}) prior on its probability under the alternative${r.a === 1 && r.b === 1 ? ' (uniform, as Jeffreys 1961 took it)' : ''}, BF10 = B(k + a, n − k + b)/(B(a, b)·p₀ᵏ(1 − p₀)ⁿ⁻ᵏ); a one-sided alternative keeps the prior on its side of p₀, renormalized. ${BF_NOTE}`),
      ...(r.notes || []).map((t) => ctx.note(t)), ctx.code(r.code));
  }

  async function betaDialog(ctx, col) {
    const cur = ctx.opt('tpBf', null, col.id) || { a: 1, b: 1 };
    const lv = ctx.table.levels(col);
    const v = await SM.ui.form({
      title: `Bayes Factor: ${col.name}`, info: 'p:distribution:bayes',
      lead: `Under the alternative the probability of ${lv.length ? SM.grid.cellText(col, lv[0]) : 'the first level'} has a beta(a, b) prior; a = b = 1 is uniform, the default. Larger a and b concentrate it at a/(a + b).`,
      fields: [{ key: 'a', label: 'Prior a', type: 'number', value: cur.a, help: 'The first shape of the beta prior, above 0. With b it sets the prior\'s mean, a/(a + b); a = b = 1 is the uniform prior, the default.' },
        { key: 'b', label: 'Prior b', type: 'number', value: cur.b, help: 'The second shape, above 0. The larger a + b, the more the prior is concentrated around a/(a + b), as if a + b − 2 earlier observations had been made.' }],
      validate: (x) => (x.a > 0 && x.b > 0 ? null : 'a and b must be positive.'),
    });
    if (v) ctx.set('tpBf', { a: v.a, b: v.b }, col.id);
  }

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

  /* ---- the graphs as matplotlib code ---------------------------------------------
     Under each graph, Python that draws it with matplotlib from a CSV export of
     the table, as the notebook runs it: the report's rows, the light theme's
     colours, the graph's size at 100 pixels an inch. The graphs whose numbers
     the backend makes get their code from it (plot_code, mosaic_code); the
     histogram with its box plots and the CDF plot, whose bins and sums the
     page works out, get theirs here. */
  const PAPER = { text: '#352921', muted: '#786b5d', base: '#2f6690' };
  const J = JSON.stringify;
  const pyNum = (v) => (Number.isFinite(v) ? String(v) : Number.isNaN(v) ? 'float("nan")' : v > 0 ? 'float("inf")' : '-float("inf")');
  const inches = (px) => String(Math.round(px) / 100);

  // The line that keeps the report's rows of the table as exported (a By
  // group, rows excluded or filtered out), as the backend's code does.
  function rowsLines(ctx) {
    const t = ctx.table, keep = ctx.rows;
    if (!t || keep.length === t.nrows) return [];
    if (keep.length > t.nrows / 2) {
      const set = new Set(keep), drop = [];
      for (let r = 0; r < t.nrows; r++) if (!set.has(r)) drop.push(r);
      return drop.length ? [`df = df.drop(index=[${drop.join(', ')}])   # the rows the report leaves out`] : [];
    }
    return [`df = df.loc[[${keep.join(', ')}]]   # the rows of the report`];
  }

  // x and its weights w as valuesOf takes them: a value, Weight times Freq above zero.
  function valueLines(ctx, col) {
    const w = ctx.name('weight'), f = ctx.name('freq');
    if (!w && !f) return [`x = df[${J(col.name)}].dropna().to_numpy()`, 'w = np.ones(len(x))'];
    const cols = [...new Set([col.name, w, f].filter(Boolean))];
    return [`d = df[${J(cols)}].dropna()`, `wt = ${[w, f].filter(Boolean).map((c) => `d[${J(c)}]`).join(' * ')}   # ${w && f ? 'Weight times Freq' : w ? 'Weight' : 'Freq'}`,
      'd, wt = d[wt > 0], wt[wt > 0]   # the rows with a positive weight', `x, w = d[${J(col.name)}].to_numpy(), wt.to_numpy()`];
  }

  // A graph with its code block under it, as one item of a row.
  const withCode = (graph, code) => (code ? el('div', { class: 'sm-dist-plotcode', style: { display: 'flex', flexDirection: 'column', alignItems: 'flex-start', minWidth: '0', maxWidth: '100%' } }, graph, code) : graph);

  /* The histogram beside (or above) the outlier box plot, as the page draws it. */
  function histogramCode(ctx, col, g) {
    const hz = g.horizontal;
    const fits = g.fits;
    const imports = ['from statsmodels.stats.weightstats import DescrStatsW'];
    if (fits.length) imports.push('from scipy import stats, optimize');
    const L = [SM.report.codeHead(ctx.table.name, ['import matplotlib.pyplot as plt', ...imports]), ...rowsLines(ctx), ...valueLines(ctx, col)];
    L.push(`start, size, nb = ${pyNum(g.bins.start)}, ${pyNum(g.bins.size)}, ${g.nb}   # the page's bins${g.binWidth ? ' (Set Bin Width)' : ''}${g.range ? ', over the range of every column (Uniform Scaling)' : ''}`,
      'k = np.clip(np.floor((x - start) / size + 1e-9), 0, nb - 1).astype(int)   # each value\'s bin, as the page counts',
      'counts = np.bincount(k, weights=w, minlength=nb)', 'mids = start + (np.arange(nb) + 0.5) * size', 'total = counts.sum()');
    L.push(g.probAxis === 'prob' ? 'scale = 1 / total   # Prob Axis' : g.probAxis === 'density' ? 'scale = 1 / (total * size)   # Density Axis' : 'scale = 1   # Count Axis');
    const box = g.showBox && !g.histOnly, qbox = g.qbox && !g.histOnly;
    if (box || qbox) {
      L.push(g.weighted ? 'q1, med, q3 = DescrStatsW(x, weights=w).quantile([0.25, 0.5, 0.75], return_pandas=False)   # the weighted quartiles'
        : 'q1, med, q3 = np.quantile(x, [0.25, 0.5, 0.75], method="weibull")   # JMP\'s quartiles, the (n + 1)p-th values');
    }
    if (box) {
      L.push('iqr = q3 - q1', 'lo, hi = x[x >= q1 - 1.5 * iqr].min(), x[x <= q3 + 1.5 * iqr].max()   # the whiskers: the furthest values within 1.5 IQR of the box');
      if (g.meanCI) L.push(`ds = DescrStatsW(x, weights=w, ddof=1)`, `mean, (lower, upper) = ds.mean, ds.tconfint_mean(alpha=${pyNum(g.alpha)})   # the mean diamond: the mean and its ${fmt(100 * (1 - g.alpha))}% interval`);
      if (g.shortest) L.push('xs = np.sort(x); h = len(xs) // 2 + 1', 'i = np.argmin(xs[h - 1:] - xs[:len(xs) - h + 1])   # the shortest half: the densest half of the values');
    }
    if (qbox) {
      L.push(g.weighted ? 'qs = DescrStatsW(x, weights=w).quantile([0.005, 0.025, 0.1, 0.9, 0.975, 0.995], return_pandas=False)   # the quantile box\'s marks'
        : 'qs = np.quantile(x, [0.005, 0.025, 0.1, 0.9, 0.975, 0.995], method="weibull")   # the quantile box\'s marks');
    }
    if (fits.length) L.push(g.weighted ? `xf = df[${J(col.name)}].dropna().to_numpy()   # the fits take each row once, without the weights` : 'xf = x   # the values the fits take');
    const W = inches(g.width), H = inches(g.height);
    if (g.histOnly) L.push(`fig, ax = plt.subplots(figsize=(${W}, ${H}), layout="constrained")`);
    else if (hz) L.push(`fig, (ax, bx) = plt.subplots(2, 1, sharex=True, figsize=(${W}, ${H}), layout="constrained", gridspec_kw={"height_ratios": [70, 22]})`);
    else L.push(`fig, (ax, bx) = plt.subplots(1, 2, sharey=True, figsize=(${W}, ${H}), layout="constrained", gridspec_kw={"width_ratios": [70, 24]})`);
    if (g.showHist) {
      L.push(hz ? `bars = ax.bar(mids, counts * scale, width=size, color="${SM.report.BAR}", edgecolor="white", linewidth=0.6)`
        : `bars = ax.barh(mids, counts * scale, height=size, color="${SM.report.BAR}", edgecolor="white", linewidth=0.6)`);
      if (g.showCounts && g.showPct) L.push('ax.bar_label(bars, labels=[f"{c:.7g} {100 * c / total:.1f}%" for c in counts], fontsize=8)   # Show Counts and Show Percents');
      else if (g.showCounts) L.push('ax.bar_label(bars, labels=[f"{c:.7g}" for c in counts], fontsize=8)   # Show Counts');
      else if (g.showPct) L.push('ax.bar_label(bars, labels=[f"{100 * c / total:.1f}%" for c in counts], fontsize=8)   # Show Percents');
    }
    if (!g.histOnly) {
      for (const f of fits) {
        L.push(`# ${f.label}: fitted as in the report (${f.dist === 'kde' ? 'Smooth Curve' : `Fitted ${f.label} Distribution`} below)`, ...f.curve_code);
        const ys = f.curve.discrete ? 'f * total * scale' : 'f * total * size * scale';
        const args = hz ? `g, ${ys}` : `${ys}, g`;
        L.push(f.curve.discrete ? `ax.plot(${args}, color="${f.color}", linewidth=1.4, marker="o", markersize=3, drawstyle="steps-mid", label=${J(f.label)})`
          : `ax.plot(${args}, color="${f.color}", linewidth=1.4, label=${J(f.label)})`);
      }
    }
    const cnt = g.probAxis === 'prob' ? 'Probability' : g.probAxis === 'density' ? 'Density' : 'Count';
    L.push(hz ? `ax.set_xlabel(${J(col.name)})` : `ax.set_ylabel(${J(col.name)})`, hz ? `ax.set_ylabel("${cnt}")` : `ax.set_xlabel("${cnt}")`);
    if (g.valRange) L.push(`ax.set_${hz ? 'x' : 'y'}lim(${pyNum(g.valRange[0])}, ${pyNum(g.valRange[1])})   # Uniform Scaling: the range of every column`);
    if (!g.histOnly) {
      const orient = hz ? ', orientation="horizontal"' : '';
      const edge = `{"color": "${PAPER.text}", "linewidth": 0.7}`;
      if (box) {
        L.push(`bx.bxp([{"q1": q1, "med": med, "q3": q3, "whislo": lo, "whishi": hi, "fliers": x[(x < lo) | (x > hi)]}], positions=[0], widths=0.55${orient}, patch_artist=True,`,
          `        boxprops={"facecolor": "#8fa9c240", "edgecolor": "${PAPER.text}", "linewidth": 0.7}, medianprops=${edge}, whiskerprops=${edge}, capprops=${edge},`,
          `        flierprops={"marker": "o", "markersize": 4, "markerfacecolor": "${PAPER.base}", "markeredgecolor": "none"})   # the outlier box plot`);
        if (g.meanCI) L.push(hz ? `bx.plot([lower, mean, upper, mean, lower], [0, 0.26, 0, -0.26, 0], color="#b0413e", linewidth=1)   # the mean diamond`
          : `bx.plot([0, 0.26, 0, -0.26, 0], [lower, mean, upper, mean, lower], color="#b0413e", linewidth=1)   # the mean diamond`);
        if (g.shortest) L.push(hz ? 'bx.plot([xs[i], xs[i], xs[i + h - 1], xs[i + h - 1]], [0.42, 0.48, 0.48, 0.42], color="#c0392b", linewidth=1.2)   # the shortest half'
          : 'bx.plot([0.42, 0.48, 0.48, 0.42], [xs[i], xs[i], xs[i + h - 1], xs[i + h - 1]], color="#c0392b", linewidth=1.2)   # the shortest half');
      }
      if (qbox) {
        const mute = `{"color": "${PAPER.muted}", "linewidth": 0.7}`;
        L.push(`bx.bxp([{"q1": q1, "med": med, "q3": q3, "whislo": x.min(), "whishi": x.max()}], positions=[0.75], widths=0.3${orient}, showfliers=False,`,
          `        boxprops=${mute}, medianprops=${mute}, whiskerprops=${mute}, capprops=${mute})   # the quantile box plot`,
          hz ? `bx.plot(qs, np.full(6, 0.75), linestyle="none", marker="|", markersize=9, color="${PAPER.muted}")   # 0.5%, 2.5%, 10%, 90%, 97.5%, 99.5%`
            : `bx.plot(np.full(6, 0.75), qs, linestyle="none", marker="_", markersize=9, color="${PAPER.muted}")   # 0.5%, 2.5%, 10%, 90%, 97.5%, 99.5%`);
      }
      L.push(`bx.set_${hz ? 'y' : 'x'}lim(-0.6, ${qbox ? '1.1' : '0.6'})`, 'bx.axis("off")');
    }
    if (g.cap) {
      for (const [key, label, dash] of [['lsl', 'LSL', '-'], ['target', 'Target', ':'], ['usl', 'USL', '-']]) {
        const v = g.cap[key];
        if (v == null) continue;
        L.push(`for a in ${g.histOnly ? '(ax,)' : '(ax, bx)'}:`, `    a.ax${hz ? 'v' : 'h'}line(${pyNum(v)}, color="#c0392b", linewidth=1, linestyle="${dash}")   # ${label}`);
        L.push(hz ? `ax.text(${pyNum(v)}, 1, " ${label}", transform=ax.get_xaxis_transform(), va="top", fontsize=8, color="#c0392b")`
          : `${g.histOnly ? 'ax' : 'bx'}.text(1, ${pyNum(v)}, "${label}", transform=${g.histOnly ? 'ax' : 'bx'}.get_yaxis_transform(), ha="right", va="bottom", fontsize=8, color="#c0392b")`);
      }
    }
    L.push(`fig.suptitle(${J(g.title)}, fontsize=10)`, 'plt.show()');
    return L.join('\n');
  }

  /* The CDF plot: the weighted share of the values up to each value. */
  function cdfCode(ctx, col, title) {
    return [SM.report.codeHead(ctx.table.name, ['import matplotlib.pyplot as plt']), ...rowsLines(ctx), ...valueLines(ctx, col),
      'order = np.argsort(x, kind="stable")', 'xs, cum = x[order], np.cumsum(w[order]) / w.sum()',
      'fig, ax = plt.subplots(figsize=(4.2, 2.8), layout="constrained")',
      `ax.plot(xs, cum, drawstyle="steps-post", marker="o", markersize=3, color="${PAPER.base}", linewidth=1.1)`,
      'ax.set_ylim(0, 1.02)', `ax.set_xlabel(${J(col.name)})`, 'ax.set_ylabel("Cumulative Probability")', `ax.set_title(${J(title)})`, 'plt.show()'].join('\n');
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
    const size = { width: horizontal ? 470 : 330, height: horizontal ? 290 : 330, title: `${col.name} histogram` };
    const graph = ctx.plot(shared.histOnly ? traces.slice(0, 1) : traces, layout, size);
    // the fits drawn on the histogram, in their colours
    const drawn = fits.map((f, i) => ({ ...f, color: FIT_COLORS[i % FIT_COLORS.length] })).filter((f) => f.curve && !f.error && f.curve_code && o(`curve:${f.dist}`, true));
    const histCode = ctx.code(histogramCode(ctx, col, { ...size, bins, nb: hb.nb, horizontal, probAxis, showHist: o('histogram', true), showBox: o('box', true), qbox: o('qbox', false),
      fits: drawn, cap, valRange, range, binWidth: o('binWidth', null), showCounts, showPct, histOnly: !!shared.histOnly, weighted, alpha: ctx.alpha,
      meanCI: Number.isFinite(m.lower), shortest: !!m.shortest_half }));

    if (shared.histOnly) { outline.add(graph, histCode); return; }

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
    outline.add(horizontal ? [graph, histCode, ctx.row(quant.el, sum.el)] : ctx.row(withCode(graph, histCode), side));
    sum.add(ctx.code(res.code));
    if (res.normality && o('normality', false)) {
      const nt = ctx.outline('Normality Tests', { parent: outline, key: 'normality' });
      nt.add(ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'stat', label: 'Statistic' }, { key: 'p', label: 'p-Value', fmt: 'p' }], rows: res.normality }),
        ctx.note('A small p-value is evidence against normality. Shapiro-Wilk is scipy\'s; Anderson-Darling, Lilliefors and Jarque-Bera are statsmodels\'.'));
    }

    // ---- the optional outlines, in JMP's order
    if (o('qq', false)) {
      const qq = await ctx.call('distribution.qq', { column: col.name, prob_axis: !!o('qqProb', false) });
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
      }, { width: 380, height: 300, title: `${col.name} normal quantile plot` }), ctx.code(qq.plot_code),
      ctx.note('Each value against Φ⁻¹(r/(n+1)), r its rank. Points near the line are consistent with a normal distribution with the sample mean and standard deviation.'));
    }
    if (o('cdf', false)) {
      const order = vals.map((_, k) => k).sort((a, b) => vals[a] - vals[b]);
      const x = order.map((k) => vals[k]);
      const cum = []; let acc = 0; const wsum = wts.reduce((a, b) => a + b, 0);
      for (const k of order) { acc += wts[k]; cum.push(acc / wsum); }
      const ob = ctx.outline('CDF Plot', { parent: outline, key: 'cdf' });
      ob.add(ctx.plot([{ type: 'scatter', mode: 'lines+markers', x, y: cum, rows: order.map((k) => rows[k]), line: { shape: 'hv', color: SM.report.BASE, width: 1.5 }, marker: { size: 4 }, name: 'CDF' }],
        { xaxis: { title: { text: col.name } }, yaxis: { title: { text: 'Cumulative Probability' }, range: [0, 1.02] } }, { width: 420, height: 280, title: `${col.name} CDF` }),
      ctx.code(cdfCode(ctx, col, `${col.name} CDF`)));
    }
    if (o('stem', false)) stemLeaf(ctx, vals, col.name, outline);
    const tm = o('testMean', null);
    if (tm) {
      const r = await ctx.call('distribution.test_mean', { column: col.name, mu: tm.mu, sigma: tm.sigma || null, wilcoxon: true, weight: ctx.name('weight'), freq: ctx.name('freq') });
      const ob = ctx.outline(`Test Mean`, { parent: outline, key: 'testmean', menu: () => [
        ctx.check('Effect Size', 'tmEffect', sc, false),
        { label: 'Bayes Factor…', checked: !!o('tmBf', null), action: () => jzsDialog(ctx, col) },
        { separator: true }, { label: 'Remove Test', action: () => ctx.set('testMean', null, sc) }] });
      if (r.error) ob.add(ctx.warn(r.error));
      else {
        ob.add(ctx.kv([['Hypothesized Value', r.mu], ['Actual Estimate', r.mean], ['DF', r.df], ['Std Dev', r.sd], r.z ? ['Sigma given', r.z.sigma] : null]));
        const cols = [{ key: 'row', label: '', fmt: 'text' }, { key: 't', label: 't Test' }];
        if (r.z) cols.push({ key: 'z', label: 'z Test' });
        if (r.wilcoxon) cols.push({ key: 'w', label: 'Signed-Rank' });
        const rowsT = [['Test Statistic', 'stat', 'num'], ['Prob > |t|', 'p_two', 'p'], ['Prob > t', 'p_greater', 'p'], ['Prob < t', 'p_less', 'p']].map(([label, key]) => ({ row: label, t: r.t[key], z: r.z ? r.z[key] : null, w: r.wilcoxon ? r.wilcoxon[key] : null, _p: key !== 'stat' }));
        ob.add(pTable(ctx, cols, rowsT), ctx.code(r.code));
        if (o('tmEffect', false)) await meanEffect(ctx, col, ob, tm);
        const bf = o('tmBf', null);
        if (bf) await meanBayes(ctx, col, ob, tm, bf);
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
    const trate = o('testRate', null);
    if (trate) await testRateReport(ctx, col, outline, trate);
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
      // the tolerance interval at its own confidence level when the prediction interval's is another
      const rt = pi && ti && ti.level !== pi.level && !r.error ? await ctx.call('distribution.intervals', { column: col.name, alpha: 1 - ti.level, k_future: 1, coverage: ti.coverage }) : r;
      if (r.error) outline.add(ctx.warn(r.error));
      else {
        if (pi) {
          const ob = ctx.outline('Prediction Intervals', { parent: outline, key: 'pi', menu: () => [{ label: 'Remove', action: () => ctx.set('pi', null, sc) }] });
          const rowsP = [{ what: `Individual (${r.k} future value${r.k > 1 ? 's' : ''})`, lower: r.prediction.lower, upper: r.prediction.upper }, { what: `Mean of ${r.k} future`, lower: r.prediction_mean.lower, upper: r.prediction_mean.upper }];
          if (r.k > 1) rowsP.push({ what: `Std Dev of ${r.k} future`, lower: r.prediction_sd.lower, upper: r.prediction_sd.upper });
          ob.add(ctx.rt({ columns: [{ key: 'what', label: '', fmt: 'text' }, { key: 'lower', label: 'Lower PI' }, { key: 'upper', label: 'Upper PI' }], rows: rowsP }), ctx.note(`${fmt(100 * pi.level)}% prediction intervals from the normal model (Bonferroni over the future values), mean ${fmt(r.mean)}, s ${fmt(r.sd)}, n ${r.n}.`));
          if (!ti || rt !== r) ob.add(ctx.code(r.code));
        }
        if (ti) {
          const ob = ctx.outline('Tolerance Intervals', { parent: outline, key: 'ti', menu: () => [{ label: 'Remove', action: () => ctx.set('ti', null, sc) }] });
          ob.add(ctx.rt({ columns: [{ key: 'what', label: 'Proportion', fmt: 'text' }, { key: 'lower', label: 'Lower TI' }, { key: 'upper', label: 'Upper TI' }, { key: 'k', label: 'k' }], rows: [{ what: pctLabel(rt.coverage), lower: rt.tolerance.lower, upper: rt.tolerance.upper, k: rt.tolerance.k }] }),
            ctx.note(`Covers ${pctLabel(rt.coverage)} of a normal population with ${fmt(100 * ti.level)}% confidence (Howe's k), two-sided.`), ctx.code(rt.code));
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
      if (f.exact) ob.add(ctx.kv([[`λ, exact ${fmt(100 * (1 - ctx.alpha))}% interval (Garwood)`, `${fmt(f.exact.lower)} to ${fmt(f.exact.upper)}`, 'text']]));
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

  /* What each field of the red triangles' dialogs does: the dialog's (i) lists them. */
  const FIELD_HELP = {
    binWidth: 'The width of the histogram\'s bars, in the column\'s units; the bins start at a multiple of it below the smallest value (of every column, with Uniform Scaling). Empty or 0: the automatic bins.',
    mu: 'The mean μ₀ the column\'s mean is tested against: Student\'s t test (statsmodels\' DescrStatsW.ttest_mean, with the Weight and Freq) and, without a Weight or Freq, the Wilcoxon signed-rank test of the differences from μ₀ (scipy); each two-sided and one-sided.',
    sigma: 'A known standard deviation σ adds a z test, (mean − μ₀)/(σ/√n), beside the t test. Empty: the t test alone, with the sample standard deviation.',
    sd0: 'The standard deviation σ₀ tested against: (n − 1)s²/σ₀² on χ² with n − 1 degrees of freedom, two-sided (Min PValue, twice the smaller tail) and one-sided. It assumes normal data and takes each row once, without the Weight or Freq.',
    low: 'The lower end of the range of means that count as equivalent. The first of the two one-sided t tests (TOST, statsmodels\' ttost_mean) is that the mean is above it.',
    upp: 'The upper end, above the lower one. The second test is that the mean is below it; equivalence is shown when both reject at the report\'s α (the larger of their p-values). Each row counts once.',
    ciLevel: 'The confidence level, strictly between 0 and 1 (0.95 for 95%; any other value gives 0.95): the t interval of the mean and the χ² intervals of the standard deviation and the variance, which assume normal data. Each row counts once.',
    piLevel: 'The confidence level of the prediction intervals, between 0 and 1 (0.95 for 95%).',
    k: 'How many future values the intervals are for: the interval of an individual value is Bonferroni-adjusted over them (t at α/2k), and the report adds the interval of their mean and, from 2 on, of their standard deviation (F). All from the normal model with the sample mean and standard deviation.',
    tiLevel: 'The confidence, between 0 and 1, that the interval holds at least the proportion covered of the population.',
    coverage: 'The share of the population the interval is to hold, between 0 and 1 (0.9 for 90%): mean ± k·s with Howe\'s k, two-sided, for normal data.',
    lsl: 'The lower specification limit; empty for an upper limit only. Cpl = (mean − LSL)/3σ, and the observed and expected shares below it.',
    target: 'The target value. Only Cpm uses it, and Cpm needs both limits; empty: no Cpm.',
    usl: 'The upper specification limit; empty for a lower limit only. Cpu = (USL − mean)/3σ. The dialog starts from the column\'s Spec Limits (Column Info); with both limits empty the analysis is removed.',
    perRow: 'How many columns\' outlines go side by side before a new row starts; 0 lets them flow to the width of the window.',
    ciCat: 'The confidence level of each level\'s probability interval, strictly between 0 and 1 (0.95 for 95%). Its method is the red triangle\'s Confidence Interval Method (Wilson score, JMP\'s, by default).',
    probs: 'The probability of each level under the hypothesis: they are scaled to sum to one, and a level given 0 is left out of the test. The likelihood-ratio and Pearson χ² tests (scipy) compare the counts with them; with a Weight or Freq the counts are sums of weights.',
  };

  // Customize Summary Statistics: what each statistic is
  const STAT_HELP = {
    mean: 'The mean, weighted by Weight and Freq.',
    sd: 'The standard deviation, with n − 1 in the denominator.',
    se: 'The standard error of the mean, s/√n.',
    upper: 'The upper limit of the t confidence interval of the mean, at the report\'s 1 − α.',
    lower: 'The lower limit of that interval.',
    n: 'The number of values; with a Weight or Freq, the sum of the weights.',
    sumw: 'The sum of the weights (Weight times Freq); the number of values without them.',
    sum: 'The sum of the values, weighted.',
    var: 'The variance, s².',
    skewness: 'The sample skewness, bias corrected (scipy\'s skew, bias=False): 0 for a symmetric distribution. Not with a Weight or Freq.',
    kurtosis: 'The excess kurtosis, bias corrected: 0 for the normal distribution. Not with a Weight or Freq.',
    cv: 'The coefficient of variation, 100·s/mean, in per cent.',
    nmiss: 'The rows of the report with no value in the column.',
    nzero: 'The values equal to 0.',
    nunique: 'The number of distinct values.',
    uss: 'The uncorrected sum of squares, Σx², weighted.',
    css: 'The corrected sum of squares, Σ(x − mean)², weighted.',
    autocorr: 'The correlation of each value with the next one in row order (lag 1). Not with a Weight or Freq.',
    min: 'The smallest value.',
    max: 'The largest value.',
    median: 'The 50% quantile, by the same definition as the Quantiles table.',
    mode: 'The most frequent value (the smallest of those tied). Not with a Weight or Freq.',
    trimmed: 'The mean of the values with 5% cut off each end (scipy\'s trim_mean). Not with a Weight or Freq.',
    geomean: 'The geometric mean, exp of the mean log; only when every value is above 0. Not with a Weight or Freq.',
    range: 'The largest value minus the smallest.',
    iqr: 'The 75% quantile minus the 25% quantile.',
    mad: 'The median of the absolute deviations from the median, unscaled. Not with a Weight or Freq.',
    robust_mean: 'Huber\'s M-estimate of location, computed jointly with the scale (statsmodels\' Huber), from 5 values on. Not with a Weight or Freq.',
    robust_sd: 'Huber\'s M-estimate of scale, from the same fit. Not with a Weight or Freq.',
  };

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
        { label: 'Set Bin Width…', action: () => ask('Set Bin Width', [{ key: 'w', label: 'Bin width (empty: automatic)', type: 'number', value: o('binWidth', null), help: FIELD_HELP.binWidth }], 'binWidth', (v) => (v.w > 0 ? v.w : null)) },
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
      { label: 'Test Mean…', action: () => ask('Test Mean', [{ key: 'mu', label: 'Specify hypothesized mean', type: 'number', value: 0, help: FIELD_HELP.mu }, { key: 'sigma', label: 'True standard deviation, for a z test (optional)', type: 'number', value: null, help: FIELD_HELP.sigma }], 'testMean') },
      { label: 'Test Std Dev…', action: () => ask('Test Std Dev', [{ key: 'sigma', label: 'Specify hypothesized standard deviation', type: 'number', value: 1, help: FIELD_HELP.sd0 }], 'testSd') },
      { label: 'Test Rate…', checked: !!o('testRate', null), disabled: !isCounts(valuesOf(ctx, col).vals), action: () => testRateDialog(ctx, col) },
      { label: 'Test Equivalence…', action: () => ask('Test Equivalence', [{ key: 'low', label: 'Lower bound', type: 'number', value: null, help: FIELD_HELP.low }, { key: 'upp', label: 'Upper bound', type: 'number', value: null, help: FIELD_HELP.upp }], 'equiv') },
      { label: 'Confidence Interval', submenu: () => [0.9, 0.95, 0.99].map((l) => ({ label: String(l), checked: o('ci', null) === l, action: () => ctx.set('ci', l, sc) })).concat([{ label: 'Other…', action: () => ask('Confidence Interval', [{ key: 'l', label: '1 − α', type: 'number', value: 0.95, help: FIELD_HELP.ciLevel }], 'ci', (v) => (v.l > 0 && v.l < 1 ? v.l : 0.95)) }]) },
      { label: 'Prediction Interval…', action: () => ask('Prediction Interval', [{ key: 'level', label: '1 − α', type: 'number', value: 0.95, help: FIELD_HELP.piLevel }, { key: 'k', label: 'Number of future values', type: 'number', value: 1, help: FIELD_HELP.k }], 'pi') },
      { label: 'Tolerance Interval…', action: () => ask('Tolerance Interval', [{ key: 'level', label: 'Confidence, 1 − α', type: 'number', value: 0.95, help: FIELD_HELP.tiLevel }, { key: 'coverage', label: 'Proportion covered', type: 'number', value: 0.9, help: FIELD_HELP.coverage }], 'ti') },
      { label: 'Capability Analysis…', action: () => { const cur = o('cap', null) || col.specLimits || {}; ask('Capability Analysis', [{ key: 'lsl', label: 'Lower spec limit', type: 'number', value: cur.lsl ?? null, help: FIELD_HELP.lsl }, { key: 'target', label: 'Target', type: 'number', value: cur.target ?? null, help: FIELD_HELP.target }, { key: 'usl', label: 'Upper spec limit', type: 'number', value: cur.usl ?? null, help: FIELD_HELP.usl }], 'cap', (v) => (v.lsl == null && v.usl == null ? null : v)); } },
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
    const v = await SM.ui.form({ title: `Customize Summary Statistics: ${col.name}`, fields: all.map(([k, label]) => ({ key: k, label, type: 'check', value: cur.includes(k), help: STAT_HELP[k] })) });
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
    const ciMethod = o('ciMethod', 'wilson');
    // the page's choices for the bar chart's and the mosaic's code
    const plot = { order: o('order', null), prob: o('axis', 'count') === 'prob', horizontal: o('horizontal', !!shared.stack), counts: !!o('showCounts', false), percents: !!o('showPercents', false),
      labels: ctx.table.levels(col).map((v) => SM.grid.cellText(col, v)) };
    const res = await ctx.call('distribution.categorical', { column: col.name, weight: ctx.name('weight'), freq: ctx.name('freq'), alpha: ciLevel ? 1 - ciLevel : ctx.alpha, ci_method: ciMethod, plot });
    if (res.error) { outline.add(ctx.warn(`${col.name}: ${res.error}`)); return; }
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
    const barCode = ctx.code(res.plot_code);
    if (shared.histOnly) { outline.add(graph, barCode); return; }
    const freq = ctx.outline('Frequencies', { parent: outline, key: 'freq', closed: !o('frequencies', true) });
    const cols = [{ key: 'label', label: 'Level', fmt: 'text' }, { key: 'count', label: 'Count' }, { key: 'prob', label: 'Prob' }];
    if (o('stderr', false)) cols.push({ key: 'se', label: 'StdErr Prob' });
    cols.push({ key: 'cum', label: 'Cum Prob' });
    let cum = 0;
    const rowsF = levels.map((l, i) => { cum += l.prob; return { label: labels[i], count: l.count, prob: l.prob, se: l.se, cum }; });
    freq.add(ctx.rt({ columns: cols, rows: [...rowsF, { label: 'Total', count: total, prob: 1, se: null, cum: null }] }, { sortable: false }),
      ctx.kv([['N Missing', res.n_missing, 'int'], [`${res.n_levels} Levels`, '', 'text']]), ctx.code(res.code));
    outline.add(horizontal ? [graph, barCode, freq.el] : ctx.row(withCode(graph, barCode), freq.el));
    if (ciLevel) {
      const ob = ctx.outline('Confidence Intervals', { parent: outline, key: 'cicat', info: 'p:distribution:ci', menu: () => [
        { label: 'Confidence Interval Method', submenu: () => ciMethodItems(ctx, col) }, { separator: true }, { label: 'Remove', action: () => ctx.set('ciCat', null, sc) }] });
      ob.add(ctx.rt({ columns: [{ key: 'label', label: 'Level', fmt: 'text' }, { key: 'count', label: 'Count' }, { key: 'prob', label: 'Prob' }, { key: 'lower', label: 'Lower CI' }, { key: 'upper', label: 'Upper CI' }, { key: 'lv', label: '1−Alpha' }], rows: levels.map((l, i) => ({ ...l, label: labels[i], lv: ciLevel })) }),
        ctx.note(ciMethod === 'wilson' ? 'Score (Wilson) confidence intervals, as JMP computes them, from statsmodels\' proportion_confint.'
          : `${CI_METHODS.find((m) => m[0] === ciMethod)[1]} confidence intervals, from statsmodels' proportion_confint; JMP's are Wilson score intervals.`));
    }
    if (o('mosaic', false)) {
      const ob = ctx.outline('Mosaic Plot', { parent: outline, key: 'mosaic' });
      const traces = levels.map((l, i) => ({ type: 'bar', x: [''], y: [l.prob], name: labels[i], rows: [members.get(key(l.level))], rowsScale: 1 / total, marker: { color: SM.util.PALETTE[i % SM.util.PALETTE.length] }, hovertemplate: `${labels[i]}: %{y:.3f}<extra></extra>` }));
      ob.add(ctx.plot(traces, { barmode: 'stack', showlegend: true, yaxis: { range: [0, 1], title: { text: 'Probability' } }, xaxis: { showticklabels: false } }, { width: 240, height: 300, title: `${col.name} mosaic`, select: false }),
        ctx.code(res.mosaic_code));
    }
    const tp = o('testProbs', null);
    if (tp) {
      const r = await ctx.call('distribution.test_probs', { column: col.name, probs: tp, weight: ctx.name('weight'), freq: ctx.name('freq') });
      const two = res.levels.length === 2;
      const ob = ctx.outline('Test Probabilities', { parent: outline, key: 'testprobs', menu: () => [
        { label: 'Bayes Factor…', checked: !!o('tpBf', null), disabled: !two, action: () => betaDialog(ctx, col) },
        { separator: true }, { label: 'Remove', action: () => ctx.set('testProbs', null, sc) }] });
      if (r.error) ob.add(ctx.warn(r.error));
      else {
        ob.add(ctx.rt({ columns: [{ key: 'level', label: 'Level', fmt: 'text' }, { key: 'observed', label: 'Estim Prob' }, { key: 'hypothesized', label: 'Hypoth Prob' }], rows: r.levels.map((l) => ({ ...l, level: SM.grid.cellText(col, l.level) })) }),
          ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'stat', label: 'ChiSquare' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'p', label: 'Prob>Chisq', fmt: 'p' }], rows: r.tests }));
        if (r.min_expected < 5) ob.add(ctx.warn(`The smallest expected count is ${fmt(r.min_expected)}; with counts below 5 the χ² p-values are approximate.`));
        const bf = o('tpBf', null);
        if (bf && two) await probsBayes(ctx, col, ob, tp, bf);
        else if (bf) ob.add(ctx.note('Bayes Factor: the binomial Bayes factor is for a column of two levels; it is not shown.'));
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
      { label: 'Confidence Interval', submenu: () => [0.9, 0.95, 0.99].map((l) => ({ label: String(l), checked: o('ciCat', null) === l, action: () => ctx.set('ciCat', l, sc) }))
        .concat([{ label: 'Other…', action: async () => { const v = await SM.ui.form({ title: `Confidence Interval: ${col.name}`, fields: [{ key: 'l', label: '1 − α', type: 'number', value: o('ciCat', null) || 0.95, help: FIELD_HELP.ciCat }], validate: (x) => (x.l > 0 && x.l < 1 ? null : '1 − α must be between 0 and 1') }); if (v) ctx.set('ciCat', v.l, sc); } },
          { separator: true }, { label: 'Confidence Interval Method', submenu: () => ciMethodItems(ctx, col) }]) },
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
      fields: lv.map((l, i) => ({ key: `p${i}`, label: SM.grid.cellText(col, l), type: 'number', value: cur[String(l)] ?? +(1 / lv.length).toFixed(6), helpLabel: 'Each level', help: FIELD_HELP.probs })),
    });
    if (!v) return;
    const probs = {};
    lv.forEach((l, i) => { probs[String(l)] = v[`p${i}`] ?? 0; });
    ctx.set('testProbs', probs, col.id);
  }

  /* ---- the platform ------------------------------------------------------------------ */
  const TOPICS = {
    'p:distribution:ci': {
      kicker: 'Distribution', title: 'Confidence Interval Method',
      lead: 'The interval for the probability of each level, from its count out of the total (statsmodels proportion_confint). JMP computes the Wilson score interval; the others are statsmodels\'.',
      sections: [{ choices: [['Wilson Score', 'inverts the score test; good coverage in general, and JMP\'s'], ['Agresti-Coull', 'the Wald interval about the Wilson centre, z²/2 successes and failures added'], ['Jeffreys', 'the central interval of the Beta(x + ½, n − x + ½) posterior'], ['Clopper-Pearson (exact)', 'from the binomial tails: coverage at least 1 − α, and wider for it'], ['Wald', 'p ± z√(p(1 − p)/n): poor for small counts and near 0 or 1, and no width when a count is 0']] },
        { heading: 'Weights', text: 'With Weight or Freq the counts are sums of weights; the formulas take them as they are.' }],
      more: { label: 'Distribution', id: 'help-p-distribution' },
    },
    'p:distribution:rate': {
      kicker: 'Distribution', title: 'Test Rate',
      lead: 'For a column that counts events (whole numbers of zero or more): the rate, the total count over the total exposure, and its test against a hypothesized rate, as for Poisson counts. Without an exposure column each row is one unit; Freq counts a row as that many units.',
      sections: [
        { heading: 'The test', choices: [['Exact (central)', 'the Poisson tails of the total count; the two-sided p-value doubles the smaller one (R\'s poisson.test uses the sum of the outcomes no more likely than the one seen)'], ['Mid-p', 'the exact tails with half the probability of the count seen'], ['Score', '(rate − rate₀)/√(rate₀/exposure)'], ['Wald', 'the same with the estimated rate in the variance'], ['Square root', 'variance-stabilizing transforms of the count']] },
        { heading: 'The interval', text: 'Exact (Garwood) from the gamma distribution by default, or the score, mid-p, Jeffreys, Wald and Anscombe intervals (statsmodels confint_poisson).' },
        { heading: 'Overdispersion', text: 'The Pearson χ²/DF of the counts about the rate is near 1 for Poisson counts; well above 1 the counts vary more than a Poisson allows and the test is too optimistic.' },
        { heading: 'Not in JMP', text: 'JMP\'s closest is Discrete Fit ▸ Poisson, the λ of the fitted distribution; it takes no exposure and has no test of a rate.' },
      ],
      more: { label: 'Distribution', id: 'help-p-distribution' },
    },
    'p:distribution:effect': {
      kicker: 'Distribution', title: 'Effect Size of Test Mean',
      lead: 'How far the mean is from the hypothesized value, in standard deviations: Test Mean ▸ Effect Size. Not in JMP.',
      sections: [
        { choices: [['Cohen\'s d', '(mean − μ₀)/s, the t of Test Mean over √n'], ['Hedges\' g', 'J·d with Hedges\' (1981) exact J = Γ(ν/2)/(√(ν/2)Γ((ν−1)/2)), ν = n − 1: unbiased for δ under normality']] },
        { heading: 'The interval', text: 'Exact: the noncentral t distributions (n − 1 DF) whose noncentrality λ puts the observed t at their upper and lower α/2 points give δ = λ/√n (Steiger and Fouladi 1997; Cumming and Finch 2001). g\'s interval is J times d\'s.' },
        { heading: 'Weight and Freq', text: 'As in the t test: the weighted mean and standard deviation, n the sum of the weights.' },
      ],
      more: { label: 'Distribution', id: 'help-p-distribution' },
    },
    'p:distribution:bayes': {
      kicker: 'Distribution', title: 'Bayes Factor',
      lead: 'How much more likely the data are under the alternative than under the null hypothesis (BF10), or the other way round (BF01 = 1/BF10), for a prior on the effect under the alternative. Not in JMP.',
      sections: [
        { heading: 'Test Mean', text: 'The JZS Bayes factor of the one-sample t test (Rouder et al. 2009): under the alternative δ = (μ − μ₀)/σ has a Cauchy(0, r) prior, r = √2/2 by default, the variance Jeffreys\' prior; computed as their integral over g. A one-sided alternative (mean above or below μ₀) keeps the prior\'s half on its side, doubled: BF+0 = 2·BF10·P(δ > 0 | data) (Morey and Wagenmakers 2014).' },
        { heading: 'Test Probabilities', text: 'For a column of two levels: the count k of the first level out of n, its hypothesized probability p₀ against a beta(a, b) prior (uniform by default): BF10 = B(k + a, n − k + b)/(B(a, b)·p₀ᵏ(1 − p₀)ⁿ⁻ᵏ). One-sided, the prior is cut at p₀ and renormalized: BF+0 = BF10·P(p > p₀ | data)/P(p > p₀). With Weight the counts are sums of weights.' },
        { heading: 'Reading them', text: 'BF10 above 1 favours the alternative, below 1 the null; unlike a p-value it can show evidence for no effect. The numbers are shown as they are, without verbal labels, and depend on the prior. Right click a table for log₁₀ BF10.' },
      ],
      more: { label: 'Distribution', id: 'help-p-distribution' },
    },
  };

  SM.platforms.register({
    id: 'distribution', label: 'Distribution', menu: 'Analyze', order: 10, info: 'p:distribution', topics: TOPICS,
    about: 'Describes one column at a time: histogram, box plot, quantiles and moments for continuous columns; bar chart and frequencies for ordinal and nominal ones; tests, intervals, capability and fitted distributions from the red triangles. Beyond JMP: a choice of interval method for the level probabilities (Wilson, JMP\'s, Agresti-Coull, Jeffreys, Clopper-Pearson, Wald), Test Rate for counts, with an optional exposure column, by exact, mid-p, score and Wald tests and intervals, and for Test Mean the effect size (Cohen\'s d, Hedges\' g, exact intervals from the noncentral t) and the JZS Bayes factor, for Test Probabilities of two levels the binomial Bayes factor (two- and one-sided).',
    uses: ['statsmodels.stats.weightstats.DescrStatsW', 'statsmodels.stats.diagnostic.normal_ad, lilliefors', 'statsmodels.stats.stattools.jarque_bera', 'statsmodels.base.model.GenericLikelihoodModel', 'statsmodels.stats.proportion.proportion_confint', 'statsmodels.stats.rates.test_poisson, confint_poisson', 'statsmodels.robust.scale.Huber', 'scipy.stats', 'scipy.stats.nct (effect size intervals), scipy.integrate.quad and scipy.special.betaln (Bayes factors)'],
    launch: {
      lead: 'Choose the columns to describe. Continuous columns get a histogram, a box plot, quantiles and moments; ordinal and nominal columns a bar chart and frequencies.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 1, hint: 'required: one or more',
          help: 'The columns to describe, each in an outline of its own. Its modeling type decides what it gets: a continuous column a histogram, an outlier box plot, Quantiles and Summary Statistics; an ordinal or nominal one a bar chart and Frequencies. Right click a column in the list to change its type.' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'A weight per row, multiplied with Freq: the histogram, the moments and quantiles, Test Mean and the counts of a categorical column weigh each row by it, and N is the sum of the weights (statsmodels\' DescrStatsW). Rows with a missing, zero or negative weight are left out. With a weight the report leaves out the skewness, the kurtosis, the robust and trimmed statistics and the normality tests; Test Std Dev, the other intervals, capability and the fitted distributions take each row once.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'How many observations each row stands for: the histogram, the moments and quantiles, Test Mean, Test Rate and the counts of a categorical column take the row that many times, so N is the sum of the counts. It multiplies the Weight; rows with a missing, zero or negative count are left out. Test Std Dev, the other intervals, capability and the fitted distributions take each row once.' },
        { key: 'by', label: 'By', hint: 'optional',
          help: 'A separate set of outlines for each level of the By column (each combination of levels, with several By columns). Rows with a missing By value are left out.' },
      ],
      options: [{ key: 'histOnly', label: 'Histograms Only', type: 'check', value: false,
        help: 'Only the histogram or bar chart of each column, without the box plot, Quantiles, Summary Statistics and the rest: a compact view of many columns. The top red triangle turns it off again.' }],
    },
    title: (spec) => ((spec.roles.y || []).length === 1 ? 'Distribution' : 'Distributions'),
    triangle(ctx) {
      return [
        ctx.check('Uniform Scaling', 'uniform', null, false),
        ctx.check('Stack', 'stack', null, false),
        ctx.check('Histograms Only', 'histOnly', null, false),
        { label: 'Arrange in Rows…', action: async () => { const v = await SM.ui.form({ title: 'Arrange in Rows', fields: [{ key: 'n', label: 'Plots per row (0: as many as fit)', type: 'number', value: ctx.opt('perRow', 0), help: FIELD_HELP.perRow }] }); if (v) ctx.set('perRow', Math.max(0, Math.round(v.n || 0))); } },
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
