/* ==========================================================================
   SMUI.HTML: ANALYZE > SPECIALIZED MODELING > COUNT REGRESSION

   Regression models for counts, several at once, compared: Poisson,
   negative binomial (NB2, NB1), generalized Poisson, zero-inflated Poisson,
   negative binomial and generalized Poisson, hurdle Poisson and negative
   binomial. The report, top down:

     Model Comparison      k, -2LL, AIC, AICc (and its weights), BIC,
                           observed and predicted zeros, Pearson chi2/DF;
                           likelihood-ratio tests of the nested pairs
                           (chi-bar-squared at alpha = 0), Vuong tests of
                           the others
     Rootogram             Kleiber and Zeileis's hanging rootogram per model
                           (standing, suspended, or the models overlaid);
                           a bar selects the rows with that count
     Count Distribution    observed and expected frequency of each count
     one outline a model   parameter estimates by part, rate and odds
                           ratios, Wald or likelihood-ratio effect tests,
                           the Poisson's dispersion and zero tests, P(0) by
                           the predicted mean, Pearson and randomized
                           quantile residuals, marginal effects, the
                           Prediction Profiler, Save Columns

   The statistics are resources/py/smui/counts.py (counts.*). Every choice
   is an option of the report (ctx.set): the top red triangle's are the
   report's, a model's red triangle scopes them to that response and model
   (scope 'yid~model'), so Redo and saved projects keep both.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt, qnorm } = SM.util;

  const MODELS = [['poisson', 'Poisson'], ['nb2', 'Negative Binomial (NB2)'], ['nb1', 'Negative Binomial (NB1)'], ['gp', 'Generalized Poisson'],
    ['zip', 'Zero-Inflated Poisson'], ['zinb', 'Zero-Inflated Negative Binomial'], ['zigp', 'Zero-Inflated Generalized Poisson'],
    ['hp', 'Hurdle Poisson'], ['hnb', 'Hurdle Negative Binomial']];
  const LABEL = Object.fromEntries(MODELS);
  const ORDER = MODELS.map((m) => m[0]);
  const SHORT = { poisson: 'Poisson', nb2: 'NB2', nb1: 'NB1', gp: 'GP', zip: 'ZIP', zinb: 'ZINB', zigp: 'ZIGP', hp: 'Hurdle P', hnb: 'Hurdle NB' };
  const ZERO = { zip: 'zi', zinb: 'zi', zigp: 'zi', hp: 'hurdle', hnb: 'hurdle' };
  const DEFAULT = ['poisson', 'nb2', 'zip', 'zinb'];
  // The launch dialog's names: JMP's Generalized Regression writes 'ZI Poisson'.
  const PICK = { poisson: 'Poisson', nb2: 'Negative Binomial (NB2)', nb1: 'Negative Binomial (NB1)', gp: 'Generalized Poisson', zip: 'ZI Poisson',
    zinb: 'ZI Negative Binomial', zigp: 'ZI Generalized Poisson', hp: 'Hurdle Poisson', hnb: 'Hurdle Negative Binomial' };
  const DEGREES = [['1', 'Main effects'], ['2', 'Full factorial to degree 2'], ['99', 'Full factorial']];
  const STYLES = [['hanging', 'Hanging'], ['standing', 'Standing'], ['suspended', 'Suspended']];
  const MORE = { label: 'Count Regression', id: 'help-p-counts' };
  // One colour a model, the same in every graph; lighter ones in the dark theme.
  const LIGHT = ['#b0413e', '#2f6690', '#3a7d44', '#6c5b7b', '#1f8a78', '#9c8200', '#8c564b', '#b8408f', '#12808f'];
  const DARK = ['#ff7a6b', '#8fb6e0', '#7fc98a', '#b9a5d6', '#4fd1b9', '#e0c341', '#d6a08b', '#f08cc8', '#5fd4e6'];

  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));
  const colorOf = (key) => (SM.util.themeColors().dark ? DARK : LIGHT)[Math.max(0, ORDER.indexOf(key)) % LIGHT.length];
  function pal() {
    const c = SM.util.themeColors();
    return { point: SM.report.BASE, ref: c.dark ? '#ff7a6b' : '#c0392b', mean: c.dark ? '#8fb6e0' : '#2f6690', muted: c.muted, text: c.text, surface: c.surface, dark: c.dark };
  }
  const lineTrace = (x, y, color, dash = 'solid', width = 1.3) => ({ type: 'scatter', mode: 'lines', x, y, line: { color, dash, width }, hoverinfo: 'skip', showlegend: false });
  const scroll = (node) => el('div', { class: 'sm-cr-scroll' }, node);
  const hline = (y, color, dash = 'solid') => ({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: y, y1: y, line: { color, width: 1, dash } });
  function extent(...arrs) {
    let lo = Infinity, hi = -Infinity;
    for (const a of arrs) if (a) for (const v of a) if (v != null && Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (!(lo <= hi)) return [0, 1];
    return lo === hi ? [lo - 0.5, hi + 0.5] : [lo, hi];
  }

  /* ---- the models of a report, the payload of every call ------------------------------------- */
  function modelsOf(ctx) {
    const m = ctx.opt('models', DEFAULT) || DEFAULT;
    const out = ORDER.filter((k) => m.includes(k));
    return out.length ? out : ['poisson'];
  }

  function basePayload(ctx, y) {
    return {
      y: y.name, x: ctx.names('x'), degree: Number(ctx.opt('degree', 1)) || 1, zx: ctx.names('zx'), zero_same: ctx.opt('zeroSame', true) !== false,
      exposure: ctx.name('exposure'), offset: ctx.name('offset'), freq: ctx.name('freq'),
    };
  }

  /* The rows with each count, for the bars (the last bin holds the rest when
     the counts run past the table's range). */
  function members(f) {
    const K = f.dist.k.length - 1;
    const m = Array.from({ length: K + 1 }, () => []);
    f.y.forEach((v, i) => { const k = f.dist.tail && v >= K ? K : v; if (k >= 0 && k <= K) m[k].push(f.rows[i]); });
    return m;
  }

  function countLabels(d) {
    const K = d.k.length - 1;
    return d.k.map((v, i) => (i === K && d.tail ? `≥${v}` : String(v)));
  }

  /* ---- one response --------------------------------------------------------------------------- */
  async function countY(ctx, y, parent) {
    const base = basePayload(ctx, y);
    const keys = modelsOf(ctx);
    const seed = Number(ctx.opt('seed', 1)) || 1;
    const fits = {};
    for (const k of keys) fits[k] = await ctx.call('counts.fit', { ...base, model: k, alpha: ctx.alpha, seed });
    const ok = keys.filter((k) => !fits[k].error);
    ctx.cr.responses.push({ y, keys, fits });
    parent.add(modelLine(y, base, ok.length ? fits[ok[0]] : null));
    if (!ok.length) {
      for (const k of keys) parent.add(ctx.warn(`${LABEL[k]}: ${fits[k].error}`));
      return;
    }
    if (ctx.opt('comparison', true)) await comparison(ctx, parent, base, keys);
    if (ctx.opt('rootogram', true)) rootograms(ctx, parent, y, ok, fits);
    if (ctx.opt('countTable', true)) countTable(ctx, parent, y, ok, fits);
    for (const k of keys) await modelOutline(ctx, parent, y, base, k, fits[k]);
  }

  function modelLine(y, base, f) {
    const items = [['Response', y.name]];
    if (base.exposure) items.push(['Exposure', `${base.exposure} (its log is the offset)`]);
    if (base.offset) items.push(['Offset', base.offset]);
    if (base.freq) items.push(['Freq', base.freq]);
    if (f) {
      const w = f.freq || f.y.map(() => 1);
      let n = 0, s = 0, ss = 0;
      f.y.forEach((v, i) => { n += w[i]; s += w[i] * v; ss += w[i] * v * v; });
      const mean = s / n, v = n > 1 ? (ss - n * mean * mean) / (n - 1) : NaN;
      items.push(['Observations (or Sum Freq)', fmt(n)], ['Zeros', `${fmt(f.zeros.observed)} (${(100 * f.zeros.observed / n).toFixed(1)}%)`],
        ['Mean', fmt(mean, { sig: 5 })], ['Variance', fmt(v, { sig: 5 })]);
    }
    return el('p', { class: 'sm-cr-modelline' }, ...items.map(([k, v]) => el('span', null, el('b', { text: `${k}: ` }), v)));
  }

  /* ---- Model Comparison ------------------------------------------------------------------------ */
  async function comparison(ctx, parent, base, keys) {
    const ob = ctx.outline('Model Comparison', { parent, key: 'comparison', info: 'p:counts:compare', menu: () => [{ label: 'Remove', action: () => ctx.set('comparison', false) }] });
    let r;
    try { r = await ctx.call('counts.compare', { ...base, which: keys, alpha: ctx.alpha }); } catch (e) { ob.add(ctx.error(e)); return; }
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    for (const f of r.failed) ob.add(ctx.warn(`${f.label} is left out: ${f.error}`));
    const rows = r.models.map((m) => ({ ...m, label: `${m.label}${m.converged ? '' : ' (did not converge)'}${m.boundary ? ' (α at 0)' : ''}` }));
    ob.add(scroll(ctx.rt({ columns: [
      { key: 'label', label: 'Model', fmt: 'text' }, { key: 'k', label: 'k', fmt: 'int' }, { key: 'm2ll', label: '−2LogLikelihood' }, { key: 'aic', label: 'AIC' },
      { key: 'aicc', label: 'AICc' }, { key: 'weight', label: 'AICc Weight', digits: 4 }, { key: 'bic', label: 'BIC' },
      { key: 'zeros_obs', label: 'Zeros Observed' }, { key: 'zeros_pred', label: 'Zeros Predicted', sig: 6 }, { key: 'dispersion', label: 'Pearson χ²/DF', sig: 5 },
    ], rows }, { key: 'cr-compare' })));
    const best = (k) => { const fin = r.models.filter((m) => Number.isFinite(m[k])); return fin.length ? fin.reduce((a, b) => (b[k] < a[k] ? b : a)).label : null; };
    if (r.models.length > 1) ob.add(ctx.note(`Smallest AICc: ${best('aicc')}; smallest BIC: ${best('bic')}.`));
    if (r.lr.length) {
      ob.add(scroll(ctx.rt({ caption: 'Likelihood Ratio Tests (nested models)', columns: [
        { key: 'restricted', label: 'Restricted', fmt: 'text' }, { key: 'full', label: 'Full', fmt: 'text' }, { key: 'lr', label: 'L-R ChiSquare' },
        { key: 'df', label: 'DF', fmt: 'int' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }, { key: 'mixture', label: 'Distribution', fmt: 'text' },
      ], rows: r.lr }, { key: 'cr-lr' })));
    }
    if (r.vuong.length) {
      ob.add(scroll(ctx.rt({ caption: 'Vuong Tests (non-nested models)', columns: [
        { key: 'm1', label: 'Model 1', fmt: 'text' }, { key: 'm2', label: 'Model 2', fmt: 'text' }, { key: 'z', label: 'Vuong z' }, { key: 'p', label: 'Prob', fmt: 'p' },
        { key: 'z_aic', label: 'AIC-corrected z' }, { key: 'p_aic', label: 'Prob', fmt: 'p' }, { key: 'z_bic', label: 'BIC-corrected z' }, { key: 'p_bic', label: 'Prob', fmt: 'p' },
        { key: 'favours', label: 'Favours (AIC-corrected)', fmt: 'text' },
      ], rows: r.vuong.map((v) => (v.note ? { ...v, favours: v.note } : v)) }, { key: 'cr-vuong' })));
    }
    for (const n of r.notes) ob.add(ctx.note(n));
    ob.add(ctx.code(r.code));
  }

  /* ---- Rootograms ------------------------------------------------------------------------------ */
  function rootMenu(ctx) {
    const st = ctx.opt('rootStyle', 'hanging');
    return [
      ...STYLES.map(([k, l]) => ({ label: l, checked: st === k, action: () => ctx.set('rootStyle', k) })),
      { separator: true },
      ctx.check('Overlay Models', 'rootOverlay', null, false),
      { label: 'Remove', action: () => ctx.set('rootogram', false) },
    ];
  }

  function rootBars(f, style, mem) {
    const O = f.dist.observed, E = f.dist.expected;
    const sO = O.map((v) => Math.sqrt(v)), sE = E.map((v) => Math.sqrt(Math.max(v, 0)));
    const height = style === 'suspended' ? sE.map((e, i) => e - sO[i]) : sO;
    const baseV = style === 'hanging' ? sE.map((e, i) => e - sO[i]) : sO.map(() => 0);
    return {
      type: 'bar', x: f.dist.k, y: height, base: baseV, width: 0.8, rows: mem, rowsScale: height.map((h, i) => (mem[i].length ? h / mem[i].length : 0)),
      marker: { color: SM.report.BAR, line: { color: SM.util.themeColors().surface, width: 0.6 } },
      customdata: O.map((o, i) => [o, E[i]]), hovertemplate: '%{x}: observed %{customdata[0]:.4~g}, expected %{customdata[1]:.4~g}<extra></extra>', name: 'Observed',
    };
  }

  function rootCurve(f, key, legend) {
    const c = colorOf(key);
    return { type: 'scatter', mode: 'lines+markers', x: f.dist.k, y: f.dist.expected.map((v) => Math.sqrt(Math.max(v, 0))), line: { color: c, width: 1.8 }, marker: { size: 5, color: c },
      customdata: f.dist.expected, hovertemplate: `${SHORT[key]}: expected %{customdata:.4~g}<extra></extra>`, name: SHORT[key], showlegend: !!legend };
  }

  function rootograms(ctx, parent, y, keys, fits) {
    const P = pal();
    const style = ctx.opt('rootStyle', 'hanging');
    const overlay = ctx.opt('rootOverlay', false);
    const ob = ctx.outline('Rootogram', { parent, key: 'rootogram', info: 'p:counts:rootogram', menu: () => rootMenu(ctx) });
    const f0 = fits[keys[0]];
    const mem = members(f0);
    const lab = countLabels(f0.dist);
    // about a dozen ticks at round steps, the last one the tail's '≥K' when there is one
    const K = f0.dist.k.length - 1;
    const step = [1, 2, 5, 10, 20, 25, 50].find((s) => (K + 1) / s <= 12) || 50;
    const tv = f0.dist.k.filter((v) => v % step === 0 && (!f0.dist.tail || K - v >= step / 2));
    if (f0.dist.tail) tv.push(K);
    const xaxis = { title: { text: y.name }, tickmode: 'array', tickvals: tv, ticktext: tv.map((v) => lab[v]), zeroline: false };
    const shapes = [hline(0, P.muted)];
    if (overlay) {
      const traces = [rootBars(f0, 'standing', mem), ...keys.map((k) => rootCurve(fits[k], k, true))];
      ob.add(ctx.plot(traces, { xaxis, yaxis: { title: { text: '√Frequency' } }, shapes, showlegend: true, legend: { orientation: 'h', y: -0.25 }, bargap: 0.1, margin: { l: 52, r: 12, t: 8, b: 70 } },
        { width: W(520), height: 320, title: `${y.name} rootogram, the models overlaid` }),
      ctx.note('Standing bars: √(observed frequency) of each count; lines: √(expected frequency) under each model.'));
    } else {
      const plots = keys.map((k) => {
        const traces = [rootBars(fits[k], style, mem)];
        if (style !== 'suspended') traces.push(rootCurve(fits[k], k, false));
        return ctx.plot(traces, { title: { text: LABEL[k], font: { size: 11.5 } }, xaxis, yaxis: { title: { text: style === 'suspended' ? '√Expected − √Observed' : '√Frequency' } }, shapes, bargap: 0.1, margin: { l: 52, r: 10, t: 28, b: 42 } },
          { width: W(keys.length > 1 ? 340 : 440), height: 270, title: `${y.name} ${STYLES.find((s) => s[0] === style)[1].toLowerCase()} rootogram, ${SHORT[k]}` });
      });
      ob.add(ctx.row(...plots));
      ob.add(ctx.note({
        hanging: 'Hanging rootograms (Kleiber and Zeileis 2016): each bar is √(observed frequency) hanging from the curve of √(expected frequency), the sum of the predicted probabilities of that count over the rows. A bar that stops above zero: the model expects more of that count than there are; below zero: fewer. The square root makes the discrepancies of small and large frequencies comparable. Click a bar to select its rows.',
        standing: 'Standing rootograms: bars of √(observed frequency) from zero and the curve of √(expected frequency); compare the tops of the bars with the curve. Click a bar to select its rows.',
        suspended: 'Suspended rootograms: bars of √(expected) − √(observed) frequency from zero: above zero the model expects too many of that count, below too few. Click a bar to select its rows.',
      }[style]));
    }
  }

  /* ---- the table of the count distribution ------------------------------------------------------ */
  function countTable(ctx, parent, y, keys, fits) {
    const ob = ctx.outline('Count Distribution', { parent, key: 'countdist', info: 'p:counts:rootogram', menu: () => [{ label: 'Remove', action: () => ctx.set('countTable', false) }] });
    const f0 = fits[keys[0]];
    const d0 = f0.dist;
    const mem = members(f0);
    const lab = countLabels(d0);
    const rows = d0.k.map((_, i) => {
      const r = { k: lab[i], obs: d0.observed[i], pct: d0.observed[i] / d0.n, _rows: mem[i] };
      for (const k of keys) r[k] = fits[k].dist.expected[i];
      return r;
    });
    if (!d0.tail) {
      const r = { k: `>${d0.k[d0.k.length - 1]}`, obs: 0, pct: 0, _rows: [] };
      for (const k of keys) r[k] = Math.max(0, d0.n - fits[k].dist.expected.reduce((a, b) => a + b, 0));
      rows.push(r);
    }
    const total = { k: 'Total', obs: d0.n, pct: 1, _rows: [] };
    for (const k of keys) total[k] = d0.n;
    rows.push(total);
    ob.add(scroll(ctx.rt({ columns: [{ key: 'k', label: y.name, fmt: 'text' }, { key: 'obs', label: 'Observed' }, { key: 'pct', label: 'Observed %', fmt: 'pct' },
      ...keys.map((k) => ({ key: k, label: `${SHORT[k]} Expected`, sig: 6 }))], rows }, { sortable: false, key: 'cr-countdist', maxRows: 120, onRow: (r, ev) => { if (r._rows.length && ctx.table) ctx.table.select(r._rows, ev.shiftKey ? 'add' : 'replace'); } })),
    ctx.note('The frequency of each count, observed and expected: the expected frequency of a count is the sum over the rows of its predicted probability. Click a line to select its rows.'));
  }

  /* ---- one model ----------------------------------------------------------------------------------- */
  function modelMenu(ctx, y, base, key, f, sc) {
    const o = (k, d) => ctx.opt(k, d, sc);
    const c = (label, k, d, extra) => ctx.check(label, k, sc, d, extra);
    const me = o('margeff', null);
    const eff = o('effectMethod', 'wald');
    return [
      c('Parameter Estimates', 'estimates', true), c('Rate Ratios', 'ratios', false),
      { label: 'Effect Tests', submenu: () => [c('Show Effect Tests', 'effectTests', true), { separator: true },
        { label: 'Wald', checked: eff === 'wald', action: () => ctx.set('effectMethod', 'wald', sc) },
        { label: 'Likelihood Ratio (refit)', checked: eff === 'lr', action: () => ctx.set('effectMethod', 'lr', sc) }] },
      c('Zero Probability Plot', 'zeroPlot', true), c('Residual Plots', 'residPlots', true),
      { label: 'Marginal Effects', disabled: !(f && f.margeff), submenu: () => [[null, 'None'], ['overall', 'Average Marginal Effects'], ['mean', 'At Means']].map(([v, l]) => ({ label: l, checked: me === v, action: () => ctx.set('margeff', v, sc) })) },
      c('Prediction Profiler', 'profiler', false),
      { separator: true },
      { label: 'Save Columns', disabled: !f || !!f.error, submenu: () => saveItems(ctx, y, key, f) },
      { label: 'Remove Model', action: () => { const cur = modelsOf(ctx).filter((k) => k !== key); ctx.set('models', cur.length ? cur : ['poisson']); } },
    ];
  }

  async function modelOutline(ctx, parent, y, base, key, f) {
    const sc = `${y.id}~${key}`;
    const o = (k, d) => ctx.opt(k, d, sc);
    const ob = ctx.outline(LABEL[key], { parent, key: `model:${key}`, info: 'p:counts:models', menu: () => modelMenu(ctx, y, base, key, f, sc) });
    ob.el.classList.add('sm-cr-model-ob');
    ob.el.style.setProperty('--cr-color', colorOf(key));
    if (f.error) { ob.add(ctx.warn(`${LABEL[key]}: ${f.error}`)); return; }
    for (const w of f.warn || []) ob.add(ctx.warn(w));
    ob.add(ctx.kv([['k (parameters)', f.k, 'int'], ['−2LogLikelihood', f.m2ll], ['AICc', f.aicc], ['BIC', f.bic], ['Pearson χ²/DF', f.pearson.ratio, 'num', { sig: 5 }],
      ['Zeros observed, predicted', `${fmt(f.zeros.observed)}, ${fmt(f.zeros.predicted, { sig: 6 })}`, 'text']]));
    if (o('estimates', true)) estimatesOutline(ctx, ob, key, f);
    if (o('ratios', false)) ratiosOutline(ctx, ob, key, f, sc);
    if (o('effectTests', true)) await effectsOutline(ctx, ob, base, key, f, sc);
    if (key === 'poisson' && f.poisson_tests) overdispersion(ctx, ob, f);
    if (o('zeroPlot', true)) zeroPlot(ctx, ob, y, key, f);
    if (o('residPlots', true)) residPlots(ctx, ob, y, key, f);
    const me = o('margeff', null);
    if (me && f.margeff) await margeffOutline(ctx, ob, base, key, me, sc);
    if (o('profiler', false)) await profiler(ctx, ob, base, key, sc);
    for (const n of f.notes || []) ob.add(ctx.note(n));
    ob.add(ctx.code(f.code));
  }

  function estimatesOutline(ctx, parent, key, f) {
    const ob = ctx.outline('Parameter Estimates', { parent, key: 'estimates', info: 'p:counts:models' });
    const e = f.estimates;
    ob.add(scroll(ctx.rt(e.count, { caption: f.caption.count, key: 'cr-est-count' })));
    if (e.zero) ob.add(scroll(ctx.rt(e.zero, { caption: f.caption.zero, key: 'cr-est-zero' })));
    if (e.alpha) ob.add(scroll(ctx.rt(e.alpha, { caption: f.caption.alpha, key: 'cr-est-alpha', sortable: false })));
    const notes = [];
    const v = { poisson: 'Var(Y) = μ.', nb2: 'Var(Y) = μ + αμ²: α is the dispersion σ of JMP\'s negative binomial.', nb1: 'Var(Y) = μ(1 + α), a constant ratio of variance to mean (JMP has no NB1).',
      gp: 'statsmodels\' generalized Poisson with p = 1: Var(Y) = μ(1 + α)²; α below 0 is underdispersion.',
      zip: 'Y is 0 with probability π (the zero-inflation part, a logit model), otherwise Poisson with mean λ (the count part): E[Y] = (1 − π)λ.',
      zinb: 'Y is 0 with probability π (the zero-inflation part, a logit model), otherwise NB2 with mean λ and Var = λ + αλ²: E[Y] = (1 − π)λ.',
      zigp: 'Y is 0 with probability π (the zero-inflation part, a logit model), otherwise generalized Poisson (p = 1) with mean λ: E[Y] = (1 − π)λ.',
      hp: 'P(Y > 0) = 1 − exp(−exp(z′γ)) (the zero hurdle, statsmodels\' censored Poisson), and above zero a Poisson truncated at zero with mean parameter λ.',
      hnb: 'P(Y > 0) = 1 − exp(−exp(z′γ)) (the zero hurdle, statsmodels\' censored Poisson), and above zero an NB2 (Var = λ + αλ² before truncation) truncated at zero.' }[key];
    notes.push(v);
    if (ZERO[key] === 'zi') notes.push('JMP Pro\'s Generalized Regression has a single, constant Zero Inflation probability; here the inflation part has effects of its own (with Intercept only its π = 1/(1 + e^−Intercept) is JMP\'s).');
    notes.push('Nominal factors are effect coded as in JMP (the last level is minus the sum of the others). Confidence limits are Wald limits, from the inverse Hessian (statsmodels\' cov_params); JMP\'s Generalized Linear Model gives profile-likelihood limits by default.');
    if (f.estimates.alpha && ['nb2', 'nb1', 'zinb', 'hnb'].includes(key)) notes.push('α = 0 lies on the boundary of the negative binomial: its test is the likelihood ratio test in Model Comparison, not a z test.');
    for (const n of notes) ob.add(ctx.note(n));
  }

  function ratioTables(ctx, ob, R, part, alphaLv) {
    const kind = R.kind === 'odds' ? 'Odds Ratio' : 'Rate Ratio';
    if (R.unit.length) {
      ob.add(scroll(ctx.rt({ caption: `${part}: unit ${kind.toLowerCase()}s`, columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'ratio', label: `Unit ${kind}` }, { key: 'lower', label: `Lower ${alphaLv}` },
        { key: 'upper', label: `Upper ${alphaLv}` }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }, { key: 'range', label: `Range ${kind}` }, { key: 'range_lower', label: `Lower ${alphaLv}` },
        { key: 'range_upper', label: `Upper ${alphaLv}` }], rows: R.unit }, { key: `cr-unit-${part}` })));
    }
    if (R.levels.length) {
      ob.add(scroll(ctx.rt({ caption: `${part}: ${kind.toLowerCase()}s of the levels`, columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'level1', label: 'Level1', fmt: 'text' },
        { key: 'level2', label: '/Level2', fmt: 'text' }, { key: 'ratio', label: kind }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }, { key: 'lower', label: `Lower ${alphaLv}` },
        { key: 'upper', label: `Upper ${alphaLv}` }], rows: R.levels }, { key: `cr-levels-${part}` })));
    }
    if (R.skipped.length) ob.add(ctx.note(`${[...new Set(R.skipped)].join(', ')}: in a crossing, so its ratio depends on the other factor; not shown.`));
  }

  function ratiosOutline(ctx, parent, key, f, sc) {
    const ob = ctx.outline('Rate Ratios', { parent, key: 'ratios', info: 'p:counts:models', menu: () => [{ label: 'Remove', action: () => ctx.set('ratios', false, sc) }] });
    const lv = `${fmt(100 * (1 - ctx.alpha))}%`;
    ratioTables(ctx, ob, f.ratios.count, 'Count part', lv);
    if (f.ratios.zero) ratioTables(ctx, ob, f.ratios.zero, ZERO[key] === 'zi' ? 'Zero inflation' : 'Zero hurdle', lv);
    const notes = ['A rate ratio is the factor by which the mean count of the count part changes: per unit of a continuous term (and over its range), or from one level of a nominal factor to another.'];
    if (ZERO[key] === 'zi') notes.push('The zero-inflation part has odds ratios: of a structural zero.');
    if (ZERO[key] === 'hurdle') notes.push('The zero hurdle\'s ratios multiply the rate λ₀ of its censored Poisson, P(Y > 0) = 1 − exp(−λ₀).');
    for (const n of notes) ob.add(ctx.note(n));
  }

  async function effectsOutline(ctx, parent, base, key, f, sc) {
    const lr = ctx.opt('effectMethod', 'wald', sc) === 'lr';
    const ob = ctx.outline('Effect Tests', { parent, key: 'efftests', info: 'p:counts:models' });
    let E = f.effects, notes = ['Wald χ² of each effect\'s terms, from the estimates and their covariance. JMP\'s Generalized Linear Model tests effects by likelihood ratio: Effect Tests > Likelihood Ratio (a red triangle) refits without each effect.'];
    if (lr) {
      const r = await ctx.call('counts.lr_effects', { ...base, model: key });
      if (r.error) { ob.add(ctx.warn(r.error)); return; }
      E = r.effects;
      notes = r.notes;
    }
    const anyRows = (t) => t && t.rows && t.rows.length;
    if (!anyRows(E.count) && !anyRows(E.zero)) { ob.add(ctx.note('The model has no effects to test (Intercept only).')); return; }
    if (anyRows(E.count)) ob.add(scroll(ctx.rt(E.count, { caption: 'Count part', key: 'cr-eff-count' })));
    if (anyRows(E.zero)) ob.add(scroll(ctx.rt(E.zero, { caption: ZERO[key] === 'zi' ? 'Zero inflation' : 'Zero hurdle', key: 'cr-eff-zero' })));
    for (const n of notes) ob.add(ctx.note(n));
  }

  function overdispersion(ctx, parent, f) {
    const T = f.poisson_tests;
    const ob = ctx.outline('Overdispersion', { parent, key: 'overdisp', info: 'p:counts:compare' });
    ob.add(ctx.kv([['Pearson χ²', f.pearson.chi2], ['DF', f.pearson.df], ['Pearson χ²/DF', f.pearson.ratio]]));
    if (T.error) { ob.add(ctx.warn(T.error)); return; }
    ob.add(scroll(ctx.rt(T.dispersion, { caption: 'Dispersion tests', key: 'cr-disp' })), scroll(ctx.rt(T.zero, { caption: 'Excess zeros', key: 'cr-zerotest' })),
      ctx.note('statsmodels\' tests of the Poisson against more variance: Dean\'s score tests and Cameron and Trivedi\'s regressions, against μ(1 + αμ) (as NB2) and μ(1 + α) (as NB1); and score tests of more zeros than the Poisson predicts. Small p-values: the Poisson does not fit, see the negative binomial or the zero-inflated models.'));
  }

  /* P(Y = 0) of each row by its predicted mean, the observed share of zeros in
     ten groups of rows by predicted mean, and a Poisson's exp(−μ). */
  function zeroPlot(ctx, parent, y, key, f) {
    const P = pal();
    const ob = ctx.outline('Zero Probability', { parent, key: 'zeroplot', closed: true, info: 'p:counts:residuals' });
    const n = f.rows.length;
    const w = f.freq || f.rows.map(() => 1);
    const order = f.mean.map((_, i) => i).sort((a, b) => f.mean[a] - f.mean[b]);
    const g = Math.max(1, Math.min(10, Math.floor(n / 15)));
    const gx = [], gy = [], grows = [], gtxt = [];
    for (let j = 0; j < g; j++) {
      const idx = order.slice(Math.floor((j * n) / g), Math.floor(((j + 1) * n) / g));
      let sw = 0, sm = 0, sz = 0;
      for (const i of idx) { sw += w[i]; sm += w[i] * f.mean[i]; sz += w[i] * (f.y[i] === 0 ? 1 : 0); }
      if (!sw) continue;
      gx.push(sm / sw); gy.push(sz / sw); grows.push(idx.map((i) => f.rows[i])); gtxt.push(`${idx.length} rows: ${(100 * sz / sw).toFixed(1)}% zeros`);
    }
    const [lo, hi] = extent(f.mean);
    const cx = Array.from({ length: 80 }, (_, i) => lo + ((hi - lo) * i) / 79);
    const traces = [
      { type: n > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: f.mean, y: f.p0, rows: f.rows, marker: { size: n > 500 ? 4 : 6, color: colorOf(key) }, name: 'Rows' },
      { type: 'scatter', mode: 'markers', x: gx, y: gy, rows: grows, marker: { size: 10, symbol: 'square-open', color: P.text, line: { width: 1.6, color: P.text } }, text: gtxt, hovertemplate: '%{text}<br>mean %{x:.3g}<extra></extra>', name: 'Observed share of zeros' },
      { ...lineTrace(cx, cx.map((m) => Math.exp(-m)), P.muted, 'dash', 1.2), name: 'Poisson exp(−μ)' },
    ];
    ob.add(ctx.plot(traces, { xaxis: { title: { text: `Predicted mean of ${y.name}` } }, yaxis: { title: { text: `P(${y.name} = 0)` }, range: [-0.02, 1.02] }, margin: { l: 58, r: 12, t: 8, b: 46 } },
      { width: W(440), height: 310, title: `${y.name} zero probability, ${SHORT[key]}` }),
    ctx.note('Each row\'s predicted probability of a zero by its predicted mean; squares: the share of zeros observed in ten groups of rows by predicted mean (click one to select the group); dashed: exp(−μ), the zeros a Poisson with the same mean would have. Points above the dashed line are zeros the model adds to a Poisson\'s.'));
  }

  function residPlots(ctx, parent, y, key, f) {
    const P = pal();
    const ob = ctx.outline('Residual Plots', { parent, key: 'resid', closed: true, info: 'p:counts:residuals' });
    const n = f.rows.length;
    const kind = n > 4000 ? 'scattergl' : 'scatter';
    const p1 = ctx.plot([{ type: kind, mode: 'markers', x: f.mean, y: f.resid_pearson, rows: f.rows, marker: { size: n > 500 ? 4 : 6 }, name: 'Rows' }],
      { xaxis: { title: { text: `Predicted mean of ${y.name}` } }, yaxis: { title: { text: 'Pearson Residual' } }, shapes: [hline(0, P.mean)], margin: { l: 58, r: 12, t: 8, b: 46 } },
      { width: W(380), height: 300, title: `${y.name} Pearson residuals by predicted, ${SHORT[key]}` });
    const r = f.resid_quantile;
    const order = r.map((_, i) => i).filter((i) => r[i] != null && Number.isFinite(r[i])).sort((a, b) => r[a] - r[b]);
    const m = order.length;
    const z = order.map((_, j) => qnorm((j + 1) / (m + 1)));
    const [zl, zh] = extent(z);
    const p2 = ctx.plot([{ type: kind, mode: 'markers', x: z, y: order.map((i) => r[i]), rows: order.map((i) => f.rows[i]), marker: { size: n > 500 ? 4 : 6 }, name: 'Rows' },
      lineTrace([zl, zh], [zl, zh], P.ref)],
    { xaxis: { title: { text: 'Normal Quantile' } }, yaxis: { title: { text: 'Randomized Quantile Residual' } }, margin: { l: 58, r: 12, t: 8, b: 46 } },
    { width: W(360), height: 300, title: `${y.name} quantile residuals normal quantile plot, ${SHORT[key]}` });
    ob.add(ctx.row(p1, p2), ctx.note(`Left: (y − E[Y])/√Var(Y) from the model's own mean and variance. Right: randomized quantile residuals (Dunn and Smyth 1996): u uniform between F(y − 1) and F(y), then Φ⁻¹(u); if the model is right they are standard normal and lie on the line. The randomness is numpy's generator with seed ${f.seed} (the top red triangle's Quantile Residual Seed), so Save Columns gives the same values.`));
  }

  async function margeffOutline(ctx, parent, base, key, at, sc) {
    const ob = ctx.outline(at === 'overall' ? 'Average Marginal Effects' : 'Marginal Effects at Means', { parent, key: 'margeff', info: 'p:counts:profiler', menu: () => [{ label: 'Remove', action: () => ctx.set('margeff', null, sc) }] });
    const r = await ctx.call('counts.margeff', { ...base, model: key, at, method: 'dydx', alpha: ctx.alpha });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    ob.add(scroll(ctx.rt(r.table, { key: 'cr-margeff' })));
    for (const n of r.notes) ob.add(ctx.note(n));
    ob.add(ctx.code(r.code));
  }

  /* ---- the Prediction Profiler: E[Y] and P(Y = 0) over each factor -----------------------------------
     The shared profiler (SM.profiler, counts.profile from profile.expose):
     one small plot per factor and response, the others at their current
     values, with the delta-method intervals; the exposure (or offset) is a
     factor too. Desirability and variable importance in its red triangle. */
  async function profiler(ctx, parent, base, key, sc) {
    return SM.profiler.render(ctx, parent, { sources: [{ fn: 'counts.profile', payload: { ...base, model: key } }], scope: sc, option: 'profiler', info: 'p:counts:profiler', stateKey: `prof:${ctx.byLabel || ''}` });
  }

  /* ---- Save Columns ------------------------------------------------------------------------------------ */
  function saveItems(ctx, y, key, f) {
    if (!f || f.error) return [{ label: '(the model did not fit)', disabled: true }];
    const s = SHORT[key];
    const sv = (name, values, notes) => () => ctx.saveColumn(name, { rows: f.rows, values }, { notes: `${notes}, from ${ctx.report.title}` });
    return [
      { label: 'Predicted Mean', action: sv(`Pred ${y.name} ${s}`, f.mean, `E[${y.name}] under the ${LABEL[key]}`) },
      { label: 'P(Y = 0)', action: sv(`P(${y.name}=0) ${s}`, f.p0, `P(${y.name} = 0) under the ${LABEL[key]}`) },
      { label: 'Pearson Residuals', action: sv(`Pearson Residual ${y.name} ${s}`, f.resid_pearson, `(y − E[Y])/√Var(Y) under the ${LABEL[key]}`) },
      { label: 'Randomized Quantile Residuals', action: sv(`Quantile Residual ${y.name} ${s}`, f.resid_quantile, `randomized quantile residuals (Dunn and Smyth), seed ${f.seed}, under the ${LABEL[key]}`) },
    ];
  }

  /* ---- the launch dialog's own part: the models, the effects, the zero part --------------------------------- */
  function launchExtra(api, spec) {
    const o0 = (spec && spec.options) || {};
    const chosen = new Set(o0.models || DEFAULT);
    const boxes = MODELS.map(([k, l]) => {
      const c = el('input', { type: 'checkbox', value: k, 'aria-label': l });
      c.checked = chosen.has(k);
      return el('label', { class: 'sm-cr-modelpick', title: l }, c, el('span', { text: PICK[k] }));
    });
    const mkSel = (choices, value, label) => { const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: v, text: l }))); s.value = value; return s; };
    const degree = mkSel(DEGREES, String(o0.degree || 1), 'Model effects');
    const zero = mkSel([['same', 'Same as the model effects'], ['intercept', 'Intercept only']], o0.zeroSame === false ? 'intercept' : 'same', 'Zero part');
    const lab = (text, input) => el('label', { class: 'sm-cr-opt' }, el('span', { text }), input);
    const rootEl = el('div', { class: 'sm-cr-launch' },
      el('h4', null, 'Models', typeof KvotInfo !== 'undefined' ? KvotInfo.slot('p:counts:models') : null),
      el('div', { class: 'sm-cr-models' }, ...boxes),
      el('div', { class: 'sm-cr-launchopts' }, lab('X, Model Effects', degree), lab('Zero part when no Zero-Inflation Effects are cast', zero)));
    const inputs = () => boxes.map((b) => b.querySelector('input'));
    return {
      el: rootEl,
      help: [
        ['Models', 'The models fitted and compared, at least one: Poisson, NB2, ZI Poisson and ZI Negative Binomial at first. Fit Model, in the report\'s red triangle, adds or removes them later.'],
        [PICK.poisson, 'The variance equals the mean. The reference: its overdispersion and excess-zero tests say whether the others are needed.'],
        [PICK.nb2, 'Var = μ + αμ²: more variation than a Poisson, growing with the mean (a gamma mixture of Poissons). The usual first alternative; α is JMP\'s dispersion.'],
        [PICK.nb1, 'Var = μ(1 + α): more variation than a Poisson, by a constant factor.'],
        [PICK.gp, 'Var = μ(1 + α)²: more variation (α above 0) or less (α below 0) than a Poisson; the negative binomials allow only more.'],
        [PICK.zip, 'A structural zero with probability π (a logit model on the zero effects), otherwise a Poisson count: for more zeros than the Poisson predicts.'],
        [PICK.zinb, 'The same with NB2 counts: excess zeros and overdispersion together.'],
        [PICK.zigp, 'The same with generalized Poisson counts.'],
        [PICK.hp, 'Two parts: whether the count is above zero (the hurdle, complementary log-log on the zero effects), then the positive counts from a Poisson truncated at zero. Every zero comes from the hurdle.'],
        [PICK.hnb, 'The hurdle with NB2 counts above it.'],
        ['X, Model Effects', 'How the X, Model Effects enter the count part (and a zero part that takes them): Main effects (the default); Full factorial to degree 2, the main effects and every two-way crossing; Full factorial, every crossing.'],
        ['Zero part when no Zero-Inflation Effects are cast', 'Same as the model effects (the default): the zero part takes the count part\'s effects. Intercept only: one zero probability for every row, as JMP Pro\'s Generalized Regression has it.'],
      ],
      read() { return { options: { models: inputs().filter((i) => i.checked).map((i) => i.value), degree: Number(degree.value), zeroSame: zero.value === 'same' } }; },
      recall(saved) {
        const o = (saved && saved.options) || {};
        if (Array.isArray(o.models)) inputs().forEach((i) => { i.checked = o.models.includes(i.value); });
        if (o.degree) degree.value = String(o.degree);
        if (o.zeroSame != null) zero.value = o.zeroSame ? 'same' : 'intercept';
      },
    };
  }

  function validate(spec, table) {
    const o = spec.options || {};
    if (!(o.models || []).length) return 'Choose at least one model.';
    const r = spec.roles || {};
    if ((r.exposure || []).length && (r.offset || []).length) return 'Give an Exposure or an Offset, not both (an exposure is logged into an offset).';
    const ys = new Set(r.y || []);
    if ([...(r.x || []), ...(r.zx || [])].some((id) => ys.has(id))) return 'A Y column is also an effect: take it out of the effects.';
    for (const id of r.y || []) {
      const c = table.col(id);
      if (!c) continue;
      const bad = c.values.findIndex((v) => typeof v === 'number' && Number.isFinite(v) && (v < 0 || Math.abs(v - Math.round(v)) > 1e-9));
      if (bad >= 0) return `${c.name} must hold counts, whole numbers of zero or more: row ${bad + 1} has ${fmt(c.values[bad])}.`;
    }
    for (const id of r.exposure || []) {
      const c = table.col(id);
      const bad = c ? c.values.findIndex((v) => typeof v === 'number' && Number.isFinite(v) && v <= 0) : -1;
      if (bad >= 0) return `The exposure ${c.name} must be above zero (it is logged): row ${bad + 1} has ${fmt(c.values[bad])}.`;
    }
    return null;
  }

  /* ---- the example: doctor visits with excess zeros and overdispersion --------------------------------------
     Simulated from a zero-inflated negative binomial with known parameters
     (seeded; nothing here is real data). */
  function gammaVariate(r, shape) {
    if (shape < 1) return gammaVariate(r, shape + 1) * Math.pow(r.u(), 1 / shape);
    const d = shape - 1 / 3, c = 1 / Math.sqrt(9 * d);
    for (;;) {
      let x, v;
      do { x = r.normal(); v = 1 + c * x; } while (v <= 0);
      v = v * v * v;
      const u = r.u();
      if (u < 1 - 0.0331 * x * x * x * x || Math.log(u) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v;
    }
  }

  function poissonVariate(r, lam) {
    if (lam > 500) return Math.max(0, Math.round(r.normal(lam, Math.sqrt(lam))));
    const L = Math.exp(-lam);
    let k = 0, p = r.u();
    while (p > L) { k++; p *= r.u(); }
    return k;
  }

  SM.io.addExample('visits', {
    label: 'Doctor visits (500 people): excess zeros, overdispersion',
    about: 'Simulated from a zero-inflated negative binomial: a person never sees a doctor with probability π, logit π = −1.4 + 1.2·[insurance none] − 0.02·(age − 50); '
      + 'otherwise visits are NB2 with mean years·exp(0.2 + 0.012·(age − 50) + 0.25·[F] + 0.55·[chronic yes] − 0.3·[none] + 0.15·[private]) and α = 0.5. For Count Regression: '
      + 'Y visits, X age, sex, chronic, insurance, Exposure years.',
    make() {
      const r = SM.util.rng('visits');
      const n = 500, c = { id: [], age: [], sex: [], chronic: [], insurance: [], years: [], visits: [] };
      for (let i = 0; i < n; i++) {
        const age = r.int(18, 84), sex = r.u() < 0.52 ? 'F' : 'M';
        const chronic = r.u() < 0.18 + 0.006 * (age - 18) ? 'yes' : 'no';
        const u = r.u(), ins = u < 0.2 ? 'none' : u < 0.7 ? 'public' : 'private';
        const years = Math.round((0.5 + 2.5 * r.u()) * 10) / 10;
        const pi = 1 / (1 + Math.exp(-(-1.4 + 1.2 * (ins === 'none') - 0.02 * (age - 50))));
        const mu = years * Math.exp(0.2 + 0.012 * (age - 50) + 0.25 * (sex === 'F') + 0.55 * (chronic === 'yes') - 0.3 * (ins === 'none') + 0.15 * (ins === 'private'));
        const alpha = 0.5;
        const lam = gammaVariate(r, 1 / alpha) * alpha * mu;
        const y = r.u() < pi ? 0 : poissonVariate(r, lam);
        c.id.push(`P${String(i + 1).padStart(3, '0')}`); c.age.push(age); c.sex.push(sex); c.chronic.push(chronic); c.insurance.push(ins); c.years.push(years); c.visits.push(y);
      }
      return new SM.Table({ name: 'Doctor visits', source: 'simulated', columns: [
        { name: 'id', dataType: 'character', values: c.id, role: 'label' },
        { name: 'age', dataType: 'numeric', values: c.age },
        { name: 'sex', dataType: 'character', values: c.sex },
        { name: 'chronic', dataType: 'character', values: c.chronic, valueOrder: ['no', 'yes'] },
        { name: 'insurance', dataType: 'character', values: c.insurance, valueOrder: ['none', 'public', 'private'] },
        { name: 'years', dataType: 'numeric', values: c.years, notes: 'years followed: the exposure' },
        { name: 'visits', dataType: 'numeric', values: c.visits, notes: 'doctor visits in the years followed' },
      ] });
    },
  });

  /* ---- the (i) topics ------------------------------------------------------------------------------------- */
  const TOPICS = {
    'p:counts': {
      kicker: 'Analyze', title: 'Count Regression',
      lead: 'Regression models for counts (whole numbers of zero or more), several at once, compared: the Poisson, the negative binomial and generalized Poisson for counts that vary more than a Poisson allows, and zero-inflated and hurdle models for more zeros than those predict. statsmodels fits them; the report puts their fit side by side and draws a rootogram of each.',
      sections: [
        { heading: 'Roles', choices: [['Y, Count', 'the counts; one report for each Y'], ['X, Model Effects', 'the regressors of the count part (main effects, or crossings with the launch\'s Full Factorial)'], ['Zero-Inflation Effects', 'the regressors of the zero part (inflation or hurdle); none: the model effects, or Intercept only'], ['Exposure', 'the time or size at risk: its log is an offset, the mean is per unit of it'], ['Offset', 'added to the linear predictor as it is'], ['Freq', 'a whole number of times each row counts'], ['By', 'a report for each level']] },
        { heading: 'Red triangles', text: 'The top one adds or removes models (Fit Model), chooses the rootogram and the tests, and saves columns; each model\'s own sets its outlines.' },
        { heading: 'Not in JMP', text: 'JMP fits zero-inflated models only in JMP Pro\'s Generalized Regression (with a constant zero-inflation probability) and has no hurdle, NB1 or generalized Poisson models, Vuong tests or rootograms.' },
      ],
      more: MORE,
    },
    'p:counts:models': {
      kicker: 'Count Regression', title: 'The count models',
      lead: 'All model the log of the mean count as a linear function of the effects (the count part). They differ in the variance and in the zeros.',
      sections: [{ choices: [['Poisson', 'variance = mean'], ['Negative Binomial (NB2)', 'Var = μ + αμ²: a gamma mixture of Poissons; α is JMP\'s dispersion σ'], ['Negative Binomial (NB1)', 'Var = μ(1 + α)'],
        ['Generalized Poisson', 'Var = μ(1 + α)²; α < 0 for underdispersion'], ['Zero-inflated', 'a structural zero with probability π (a logit model of its own), otherwise the count distribution'],
        ['Hurdle', 'whether Y is above zero (complementary log-log, statsmodels\' censored Poisson), then the positive counts by the distribution truncated at zero']] },
      { heading: 'Estimates', text: 'By part: the count part (log scale), the zero part (logit for inflation, complementary log-log for the hurdle) and α. Rate Ratios exponentiate them; Effect Tests test each effect by Wald χ², or by refitting without it.' }],
      more: MORE,
    },
    'p:counts:compare': {
      kicker: 'Count Regression', title: 'Model Comparison',
      lead: 'The fitted models side by side: k, −2LogLikelihood, AIC, AICc (smaller is better) and its weights, BIC, the zeros observed and predicted, and Pearson χ²/DF (near 1 when the variance is right).',
      sections: [{ choices: [['Likelihood ratio tests', 'for nested pairs: Poisson in NB2, NB1 and GP; ZIP in ZINB and ZIGP; hurdle Poisson in hurdle NB. At α = 0 (a boundary) the p-value is half the χ²₁ one'],
        ['Vuong tests', 'for the other pairs: whether one model predicts the rows better than the other, raw and with AIC and BIC corrections; positive z favours Model 1. For a zero-inflated model against its count model the test is questionable (the models meet at a boundary)']] },
      { heading: 'Overdispersion', text: 'Under the Poisson: statsmodels\' dispersion tests (Dean, Cameron and Trivedi) and score tests of excess zeros.' }],
      more: MORE,
    },
    'p:counts:rootogram': {
      kicker: 'Count Regression', title: 'Rootograms',
      lead: 'The observed frequency of each count against the frequency each model expects (the sum of the predicted probabilities over the rows), on a square-root scale (Kleiber and Zeileis 2016).',
      sections: [{ choices: [['Hanging', 'bars of √observed hang from the curve of √expected: a bar ending above the zero line is a count the model expects too often, below too rarely'], ['Standing', 'bars from zero, the curve over them'], ['Suspended', 'bars of √expected − √observed from zero'], ['Overlay Models', 'one graph, standing bars, a curve for each model']] },
      { heading: 'In the report', choices: [['A bar of a rootogram', 'click it to select the rows with that count (the last bar, ≥K, the rows at or above it); rows selected elsewhere are marked in the bars'],
        ['A line of Count Distribution', 'click it to select the rows with that count; shift adds them to the selection']] }],
      more: MORE,
    },
    'p:counts:residuals': {
      kicker: 'Count Regression', title: 'Zero probabilities and residuals',
      lead: 'Zero Probability shows each row\'s predicted P(Y = 0) by its predicted mean, the observed share of zeros in ten groups of rows, and the zeros a Poisson would have. Residual Plots show Pearson residuals by the prediction and a normal quantile plot of randomized quantile residuals.',
      sections: [{ heading: 'Randomized quantile residuals', text: 'Dunn and Smyth (1996): for a count y, a uniform u between F(y − 1) and F(y) of the fitted distribution, and Φ⁻¹(u). If the model is right they are standard normal whatever the counts; the random part is seeded (the top red triangle\'s Quantile Residual Seed), so they can be saved and reproduced.' },
        { heading: 'In the report', choices: [['A point', 'a row: click or drag over points to select their rows, in any of these plots'], ['A square of Zero Probability', 'one of up to ten groups of rows by predicted mean: click it to select the group']] }],
      more: MORE,
    },
    'p:counts:profiler': {
      kicker: 'Count Regression', title: 'Prediction Profiler and marginal effects',
      lead: 'The profiler shows the expected count and the probability of a zero as each factor moves, the others at their current values; the exposure is a factor too. Drag the red dashed lines, click in a plot, or type a value.',
      sections: [{ heading: 'Marginal Effects', text: 'statsmodels\' get_margeff, for the Poisson, the negative binomials and the generalized Poisson: the change of the mean count with each design column, averaged over the rows or at the means. statsmodels has none for zero-inflated and hurdle models; use the profiler for them.' },
        { heading: 'In the profiler', choices: [['The value box under a plot', 'the factor\'s current value: type one (Enter), or pick a level for a categorical factor; every plot is drawn again at the new setting'],
          ['The slider', 'moves a continuous factor over the range of its data; the plots follow when you let go'], ['The red dashed line', 'drag it along the plot, or click in the plot, to move that factor there'],
          ['A desirability plot', 'with Desirability Functions on (the profiler\'s red triangle), the small plot at the right of a response: click it to set that response\'s goal and desirability'],
          ['Remembered Settings', 'a table of the settings Remember Settings kept; click a line to go back to it']] }],
      more: MORE,
    },
  };

  /* ---- the platform ---------------------------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'counts', label: 'Count Regression', menu: 'Analyze/Specialized Modeling', order: 50, info: 'p:counts', topics: TOPICS,
    about: 'Regression models for counts: Poisson, negative binomial (NB2 and NB1), generalized Poisson, and zero-inflated and hurdle versions, several at once, compared by AICc, BIC, likelihood ratio tests (nested) and Vuong tests (non-nested), with hanging rootograms, observed and expected count frequencies, zero probabilities, Pearson and randomized quantile residuals, rate ratios, marginal effects and a prediction profiler. JMP has zero-inflated models only in JMP Pro\'s Generalized Regression, and no rootograms.',
    uses: ['statsmodels.discrete.discrete_model.Poisson, NegativeBinomial, GeneralizedPoisson', 'statsmodels.discrete.count_model.ZeroInflatedPoisson, ZeroInflatedNegativeBinomialP, ZeroInflatedGeneralizedPoisson',
      'statsmodels.discrete.truncated_model.TruncatedLFPoisson, TruncatedLFNegativeBinomialP (the parts of HurdleCountModel)', 'statsmodels.genmod.generalized_linear_model.GLM (binomial, complementary log-log: the hurdle)',
      'statsmodels.discrete.discrete_model.CountResults.get_margeff, get_diagnostic', 'scipy.stats (count distributions, the Vuong test)', 'patsy'],
    launch: {
      lead: 'Choose the count, the effects of the count part and, if they differ, of the zero part, and the models to fit. An exposure (the time or size at risk) is logged into an offset.',
      roles: [
        { key: 'y', label: 'Y, Count', min: 1, numeric: true, hint: 'required: whole numbers ≥ 0',
          help: 'The counts to model, whole numbers of zero or more; each Y gets its own models and outlines. Rows with a missing value in any role are left out.' },
        { key: 'x', label: 'X, Model Effects', hint: 'optional: main effects',
          help: 'The regressors of the count part, the log of the mean count: a continuous column as it is, a nominal one effect coded. X, Model Effects under the roles makes them main effects or crosses them. Empty: the intercept only.' },
        { key: 'zx', label: 'Zero-Inflation Effects', hint: 'optional: the zero part',
          help: 'The regressors of the zero part of the zero-inflated models (the logit of a structural zero) and the hurdle models (the probability of a count above zero), as main effects. Empty: as Zero part, under the roles, says. The Poisson, negative binomial and generalized Poisson models have no zero part.' },
        { key: 'exposure', label: 'Exposure', max: 1, numeric: true, types: ['continuous'], hint: 'optional: logged',
          help: 'The time or size at risk of each row (years followed, area, population), above zero: its log is an offset, so the mean is per unit of exposure and the rate ratios compare rates. Not together with an Offset.' },
        { key: 'offset', label: 'Offset', max: 1, numeric: true, types: ['continuous'], hint: 'optional',
          help: 'A known part of the linear predictor (the log scale), added with a coefficient of 1: a log exposure already taken, say. Not together with an Exposure.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional: whole numbers',
          help: 'A whole number per row: the row counts that many times, in the fits and in the count distribution.' },
        { key: 'by', label: 'By', hint: 'optional',
          help: 'A separate report of the rows of each level (each combination of levels, with several By columns). Rows with a missing By value are left out.' },
      ],
      extra: launchExtra,
      validate,
    },
    title(spec, table) {
      const ys = ((spec.roles || {}).y || []).map((id) => (table ? table.col(id) : null)).filter(Boolean);
      return ys.length === 1 ? `Count Regression for ${ys[0].name}` : 'Count Regression';
    },
    triangle(ctx) {
      const cur = modelsOf(ctx);
      const eff = ctx.opt('effectMethod', 'wald');
      const me = ctx.opt('margeff', null);
      const st = ctx.opt('rootStyle', 'hanging');
      const saves = (ctx.cr && ctx.cr.responses) || [];
      return [
        { label: 'Fit Model', submenu: () => MODELS.map(([k, l]) => ({ label: l, checked: cur.includes(k), action: () => {
          const next = cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k];
          if (!next.length) { SM.ui.toast('Keep at least one model'); return; }
          ctx.set('models', ORDER.filter((x) => next.includes(x)));
        } })) },
        { separator: true },
        ctx.check('Model Comparison', 'comparison', null, true),
        { label: 'Rootogram', submenu: () => [ctx.check('Show Rootograms', 'rootogram', null, true), { separator: true },
          ...STYLES.map(([k, l]) => ({ label: l, checked: st === k, action: () => ctx.set('rootStyle', k) })), { separator: true }, ctx.check('Overlay Models', 'rootOverlay', null, false)] },
        ctx.check('Count Distribution', 'countTable', null, true),
        { separator: true },
        ctx.check('Parameter Estimates', 'estimates', null, true),
        ctx.check('Rate Ratios', 'ratios', null, false),
        { label: 'Effect Tests', submenu: () => [ctx.check('Show Effect Tests', 'effectTests', null, true), { separator: true },
          { label: 'Wald', checked: eff === 'wald', action: () => ctx.set('effectMethod', 'wald') },
          { label: 'Likelihood Ratio (refit)', checked: eff === 'lr', action: () => ctx.set('effectMethod', 'lr') }] },
        ctx.check('Zero Probability Plots', 'zeroPlot', null, true),
        ctx.check('Residual Plots', 'residPlots', null, true),
        { label: 'Marginal Effects', submenu: () => [[null, 'None'], ['overall', 'Average Marginal Effects'], ['mean', 'At Means']].map(([v, l]) => ({ label: l, checked: me === v, action: () => ctx.set('margeff', v) })) },
        ctx.check('Prediction Profilers', 'profiler', null, false),
        { separator: true },
        { label: 'Save Columns', disabled: !saves.length, submenu: () => saves.flatMap(({ y, keys, fits }) => keys.map((k) => ({
          label: saves.length > 1 ? `${y.name}: ${LABEL[k]}` : LABEL[k], disabled: !!fits[k].error, submenu: () => saveItems(ctx, y, k, fits[k]),
        }))) },
        { label: 'Quantile Residual Seed…', action: async () => {
          const v = await SM.ui.form({ title: 'Quantile Residual Seed', lead: 'The seed of numpy\'s random generator for the randomized quantile residuals: the same seed gives the same residuals.', fields: [{ key: 's', label: 'Seed (a whole number)', type: 'number', value: Number(ctx.opt('seed', 1)) || 1, helpLabel: 'Seed',
            help: 'A whole number from 0 (1 at first). A randomized quantile residual draws a uniform value between F(y − 1) and F(y) for each count; the seed fixes those draws, so the residual plots, Save Columns and the Python shown agree. Another seed shows how much the plots move by chance; the fits do not change.' }] });
          if (v && Number.isFinite(v.s)) ctx.set('seed', Math.max(0, Math.round(v.s)));
        } },
        { label: 'Model Dialog', action: () => ctx.report.relaunch() },
      ];
    },
    async render(ctx) {
      ctx.cr = { responses: [] };
      const ys = ctx.roles('y');
      const multi = ys.length > 1;
      for (const y of ys) {
        const parent = multi ? ctx.outline(`Count Regression for ${y.name}`, { key: `resp:${y.id}` }) : ctx.top;
        await countY(ctx, y, parent);
      }
    },
  });
}(typeof self !== 'undefined' ? self : this));
