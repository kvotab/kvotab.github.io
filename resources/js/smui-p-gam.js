/* ==========================================================================
   SMUI.HTML: ANALYZE > SPECIALIZED MODELING > GENERALIZED ADDITIVE MODEL

   statsmodels' GLMGam in JMP's working style (JMP itself has no GAM; its
   Fit Spline smooths one column at a time). The response's mean, through a
   link, is a sum of smooth functions of the Smooth Terms and a linear part
   from the Linear Terms (JMP's coding and names):

     Smooth Terms         one partial effect plot per term: the fitted smooth
                          with its pointwise confidence band, the partial
                          residuals (linked to the rows) and a rug; the
                          term's red triangle changes its basis (B-spline or
                          cyclic cubic), size and degree, and a slider sets
                          its penalty weight alpha on a log scale, refitting
                          as it moves
     Model Summary        family, link, N, deviance, AIC, BIC, GCV, EDF and
                          the penalty weights
     Smooth Term Tests    statsmodels' test_significance (Wald, on the EDF)
     Parameter Estimates  the linear part
     diagnostics          actual and residual by predicted, a normal
                          quantile plot of the deviance residuals
     Prediction Profiler  every term, on the response scale
     Surface Plot         the sum of two smooth terms' partial effects
     Compare with Linear  the smooth columns as linear terms (a GLM)

   The statistics are resources/py/smui/gam.py (gam.*). Every choice is an
   option of the report (ctx.set), a term's scoped by its column, so Redo
   and projects keep them. Penalty weights set by hand are kept per By
   group in the option pen:<group>, { column id: alpha }, with the model
   they were set for (a new basis or family chooses them again).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt, qnorm } = SM.util;

  const FAMILIES = [['normal', 'Normal'], ['binomial', 'Binomial'], ['poisson', 'Poisson'], ['gamma', 'Gamma']];
  const FAMILY_LABEL = Object.fromEntries(FAMILIES);
  const LINKS = {
    normal: [['identity', 'Identity'], ['log', 'Log'], ['reciprocal', 'Reciprocal']],
    binomial: [['logit', 'Logit'], ['probit', 'Probit'], ['cloglog', 'Comp LogLog'], ['log', 'Log']],
    poisson: [['log', 'Log'], ['identity', 'Identity'], ['sqrt', 'Square Root']],
    gamma: [['log', 'Log'], ['reciprocal', 'Reciprocal'], ['identity', 'Identity']],
  };
  const SMOOTHING = [['aic', 'AIC'], ['bic', 'BIC'], ['gcv', 'GCV'], ['kfold', 'K-Fold Cross-Validation'], ['fixed', 'Fixed Penalty α']];
  const SMOOTHING_LABEL = Object.fromEntries(SMOOTHING);
  const BASES = [['bs', 'B-Spline'], ['cc', 'Cyclic Cubic']];
  const BASIS_LABEL = Object.fromEntries(BASES);
  const DEGREES = [2, 3, 4, 5];

  /* ---- small parts ------------------------------------------------------------ */
  function pal() {
    const c = SM.util.themeColors();
    return {
      point: SM.report.BASE, fit: c.dark ? '#ff7a6b' : '#c0392b', band: c.dark ? 'rgba(255,122,107,0.18)' : 'rgba(192,57,43,0.13)',
      mean: c.dark ? '#8fb6e0' : '#2f6690', muted: c.muted, text: c.text, grid: c.grid, dark: c.dark,
    };
  }
  // A plot's width: as asked, but inside the window with room for the outlines' indentation.
  const W = (w) => Math.max(250, Math.min(w, (root.innerWidth || 1200) - 110));
  function extent(...arrs) {
    let lo = Infinity, hi = -Infinity;
    for (const a of arrs) if (a) for (const v of a) if (v != null && Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (!(lo <= hi)) return [0, 1];
    if (lo === hi) return [lo - 0.5, hi + 0.5];
    return [lo, hi];
  }
  const lineTrace = (x, y, color, dash = 'solid', width = 1.3) => ({ type: 'scatter', mode: 'lines', x, y, line: { color, dash, width }, hoverinfo: 'skip', showlegend: false });
  const fmtA = (a) => (a == null || !Number.isFinite(a) ? '.' : a === 0 ? '0' : fmt(a, { sig: 4 }));
  const penKey = (ctx) => `pen:${ctx.byLabel || ''}`;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  /* ---- the model of a report ------------------------------------------------------
     The payload every gam.* call gets. A term's options (basis, df, degree)
     are scoped by its column; the launch dialog's are the defaults. */
  function linkOf(ctx) {
    const family = ctx.opt('family', 'normal');
    const link = ctx.opt('link', null);
    return (LINKS[family] || LINKS.normal).some(([k]) => k === link) ? link : (LINKS[family] || LINKS.normal)[0][0];
  }
  function termsOf(ctx) {
    return ctx.roles('smooth').map((c) => {
      const basis = ctx.opt('basis', 'bs', c.id) === 'cc' ? 'cc' : 'bs';
      return { basis, df: Math.round(Number(ctx.opt('df', 10, c.id)) || 10), degree: Math.round(Number(ctx.opt('degree', 3, c.id)) || 3) };
    });
  }
  // What a set of penalty weights was chosen for: when this changes, they are chosen again.
  const penSig = (ctx) => JSON.stringify([ctx.opt('family', 'normal'), linkOf(ctx), ctx.opt('target', null), termsOf(ctx).map((t) => [t.basis, t.df, t.basis === 'bs' ? t.degree : 0])]);
  function penaltyOf(ctx) {
    const smooth = ctx.roles('smooth');
    const ov = ctx.opt(penKey(ctx), null);
    if (ov && ov.sig === penSig(ctx) && ov.alpha && smooth.every((c) => Number.isFinite(ov.alpha[c.id]))) return { alpha: smooth.map((c) => ov.alpha[c.id]), byHand: true };
    if (ctx.opt('smoothing', 'aic') === 'fixed') {
      const a = Number(ctx.opt('penalty', 1));
      return { alpha: smooth.map(() => (Number.isFinite(a) && a >= 0 ? a : 1)), byHand: false };
    }
    return { alpha: null, byHand: false };
  }
  function modelOf(ctx) {
    const pen = penaltyOf(ctx);
    return {
      y: ctx.name('y'), smooth: ctx.names('smooth'), linear: ctx.names('linear'), weight: ctx.name('weight'), freq: ctx.name('freq'),
      family: ctx.opt('family', 'normal'), link: linkOf(ctx), smoothing: ctx.opt('smoothing', 'aic'), penalty: pen.alpha, terms: termsOf(ctx),
      target: ctx.opt('target', null), folds: Math.round(Number(ctx.opt('folds', 5)) || 5),
    };
  }
  function clearPenalties(ctx) {
    for (const k of Object.keys(ctx.spec.options)) if (k.startsWith('pen:')) delete ctx.spec.options[k];
  }
  function setPenalty(ctx, res, index, value, { rerun = true } = {}) {
    const smooth = ctx.roles('smooth');
    const alpha = Object.fromEntries(smooth.map((c, k) => [c.id, k === index ? value : res.terms[k].alpha]));
    ctx.set(penKey(ctx), { sig: penSig(ctx), alpha }, null, { rerun });
  }
  // A term's basis, size or degree: its scale for alpha changes, so every penalty is chosen again.
  function setTerm(ctx, col, key, value) {
    clearPenalties(ctx);
    ctx.set(key, value, col.id);
  }

  /* ---- the graphs' code -------------------------------------------------------------
     Under each graph, Python that draws it with matplotlib from a CSV export of
     the table: gam.plot_code writes it, the model fitted as the report fits it
     (its penalty search included), from what the page chose (a term's band,
     residuals, rug and intercept, the surface's terms). The Prediction
     Profiler is interactive and has none; a headless run (Bootstrap) draws
     no graphs and asks for none. */
  const withCode = (ctx, graph, code) => (code ? el('div', { class: 'sm-gam-plotcode' }, graph, ctx.code(code)) : graph);
  async function plotCode(ctx, payload, kind, plot) {
    if (ctx.headless) return null;
    const r = await ctx.call('gam.plot_code', { ...payload, alpha: ctx.alpha, kind, plot });
    return r && !r.error ? r.plot_code : null;
  }

  /* A scatter of rows (linked to the table) with reference lines. */
  function rowPlot(ctx, { x, y, rows, xTitle, yTitle, lines = [], hlines = [], width = 380, height = 300, title }) {
    const P = pal();
    const traces = [{ type: x.length > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x, y, rows, marker: { size: x.length > 500 ? 4 : 6 }, name: 'Rows' }, ...lines];
    const shapes = hlines.map((h) => ({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: h.y, y1: h.y, line: { color: h.color || P.muted, width: h.width || 1, dash: h.dash || 'solid' } }));
    return ctx.plot(traces, { xaxis: { title: { text: xTitle } }, yaxis: { title: { text: yTitle } }, shapes, margin: { l: 58, r: 12, t: 8, b: 46 } }, { width: W(width), height, title });
  }

  /* ---- Smooth Terms: one partial effect plot per term ----------------------------------- */
  // The traces of a term's plot, and where each one is (the slider restyles them in place).
  function termTraces(ctx, t, intercept, o) {
    const P = pal();
    const c = o.constant ? intercept : 0;
    const f = t.curve.f.map((v) => v + c);
    const se = o.constant ? t.curve.se_c : t.curve.se;
    const z = qnorm(1 - ctx.alpha / 2);
    const traces = [];
    const at = {};
    if (o.band) {
      at.lower = traces.length;
      traces.push({ type: 'scatter', mode: 'lines', x: t.curve.x, y: f.map((v, i) => v - z * se[i]), line: { width: 0, color: P.band }, hoverinfo: 'skip', showlegend: false });
      at.upper = traces.length;
      traces.push({ type: 'scatter', mode: 'lines', x: t.curve.x, y: f.map((v, i) => v + z * se[i]), line: { width: 0, color: P.band }, fill: 'tonexty', fillcolor: P.band, hoverinfo: 'skip', showlegend: false });
    }
    if (o.resid) {
      at.resid = traces.length;
      const pts = t.points;
      traces.push({ type: pts.x.length > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: pts.x, y: pts.partial.map((v) => v + c), rows: pts.rows,
        marker: { size: pts.x.length > 500 ? 4 : 5, opacity: 0.75 }, name: 'Partial residuals' });
    }
    at.curve = traces.length;
    traces.push({ type: 'scatter', mode: 'lines', x: t.curve.x, y: f, line: { color: P.fit, width: 2 }, name: `s(${t.name})`,
      hovertemplate: `${SM.report.plotlyText(t.name)} %{x:.4g}<br>s = %{y:.4g}<extra></extra>` });
    if (o.rug) {
      at.rug = traces.length;
      traces.push({ type: 'scatter', mode: 'markers', x: t.points.x, y: t.points.x.map(() => 0.035), yaxis: 'y2', rows: t.points.rows,
        marker: { symbol: 'line-ns-open', size: 9, color: P.muted, line: { width: 1, color: P.muted } }, name: 'Rug', hoverinfo: 'skip' });
    }
    return { traces, at, f, se, z, c };
  }

  // A term's display options and their defaults: no partial residuals for a 0/1 response (their working
  // residuals lie far off the curve), no rug above 4000 rows (it is a solid bar by then).
  const termDefaults = (res) => ({ band: true, resid: res.model.family !== 'binomial', rug: res.diag.rows.length <= 4000, constant: false });
  function termOptions(ctx, col, res) {
    const sc = col.id, d = termDefaults(res);
    return { band: ctx.opt('band', d.band, sc), resid: ctx.opt('resid', d.resid, sc), rug: ctx.opt('rug', d.rug, sc), constant: ctx.opt('constant', d.constant, sc) };
  }

  function termMenu(ctx, col, t, res) {
    const sc = col.id;
    const dflt = termDefaults(res);
    const byHand = penaltyOf(ctx).byHand;
    return [
      { label: 'Basis', submenu: () => BASES.map(([k, l]) => ({ label: l, checked: t.basis === k, action: () => setTerm(ctx, col, 'basis', k) })) },
      { label: 'Basis Size (df)…', action: async () => {
        const lo = t.basis === 'cc' ? 3 : (t.degree || 3) + 1;
        const v = await SM.ui.form({ title: `Basis Size: s(${col.name})`, lead: `The number of basis functions; the term has one parameter fewer (it is centred). At least ${lo}, at most 60.`,
          fields: [{ key: 'df', label: 'Basis size (df)', type: 'number', value: t.df,
            help: `The number of basis functions of s(${col.name}), ${lo} to 60: a larger basis lets the curve bend more, the penalty then deciding how much. Every term's penalty is chosen again afterwards, since the scale of α changes with the basis.` }], validate: (x) => (Number.isInteger(x.df) && x.df >= lo && x.df <= 60 ? null : `a whole number from ${lo} to 60`) });
        if (v) setTerm(ctx, col, 'df', v.df);
      } },
      { label: 'Degree', disabled: t.basis === 'cc', submenu: () => DEGREES.map((dg) => ({ label: String(dg), checked: t.degree === dg, action: () => setTerm(ctx, col, 'degree', dg) })) },
      { separator: true },
      { label: 'Penalty α…', action: async () => {
        const v = await SM.ui.form({ title: `Penalty α: s(${col.name})`, lead: 'The weight of the roughness penalty α·∫s″². Larger is smoother (EDF towards 1 for a B-spline, 0 for a cyclic term); 0 is an unpenalized regression spline. The other terms keep their penalties.',
          fields: [{ key: 'a', label: 'Penalty α', type: 'number', value: +t.alpha.toPrecision(6),
            help: 'This term\'s penalty weight, zero or above; it starts at the one in use. The penalties are then set by hand, the others kept where they are, until Choose Penalties Automatically lets the smoothing criterion choose them again.' }], validate: (x) => (x.a != null && x.a >= 0 ? null : 'α is zero or above') });
        if (v) setPenalty(ctx, res, t.index, v.a);
      } },
      { label: 'Choose Penalties Automatically', disabled: !byHand && ctx.opt('smoothing', 'aic') !== 'fixed', action: () => { clearPenalties(ctx); if (ctx.opt('smoothing', 'aic') === 'fixed') ctx.set('smoothing', 'aic'); else ctx.report.run(); } },
      { separator: true },
      ctx.check('Partial Residuals', 'resid', sc, dflt.resid),
      ctx.check('Confidence Band', 'band', sc, dflt.band),
      ctx.check('Rug', 'rug', sc, dflt.rug),
      ctx.check('Include Intercept', 'constant', sc, dflt.constant),
      { separator: true },
      { label: 'Save Partial Effect', action: () => savePartial(ctx, res, t) },
    ];
  }

  async function termOutline(ctx, parent, t, res, payload, col) {
    const P = pal();
    const o = termOptions(ctx, col, res);
    const title = `s(${t.name})${t.basis === 'cc' ? ', cyclic' : ''}`;
    const ob = ctx.outline(title, { parent, level: 2, key: `term:${col.id}`, menu: () => termMenu(ctx, col, t, res) });
    const tr = termTraces(ctx, t, res.intercept, o);
    const layout = {
      xaxis: { title: { text: t.name } }, yaxis: { title: { text: o.constant ? `Intercept + s(${t.name})` : `s(${t.name})` }, zeroline: true },
      yaxis2: { overlaying: 'y', range: [0, 1], visible: false, fixedrange: true, showgrid: false, zeroline: false },
      margin: { l: 56, r: 10, t: 8, b: 42 }, showlegend: false,
    };
    const box = ctx.plot(tr.traces, layout, { width: W(380), height: 280, title: `${t.name} partial effect` });
    const code = await plotCode(ctx, payload, 'term', { index: t.index, band: o.band, resid: o.resid, rug: o.rug, constant: o.constant });
    // the penalty slider: log10(alpha) about the term's scale
    const a0 = Math.log10(t.a0 > 0 ? t.a0 : 1);
    const cur = t.alpha > 0 ? Math.log10(t.alpha) : a0 - 4;
    const lo = Math.floor(Math.min(a0 - 4, cur - 0.5)), hi = Math.ceil(Math.max(a0 + 5, cur + 0.5));
    const slider = el('input', { type: 'range', min: String(lo), max: String(hi), step: '0.02', value: String(cur), class: 'sm-gam-slider', 'aria-label': `Penalty α of ${t.name}, log scale` });
    const aText = el('span', { class: 'sm-gam-aval', text: fmtA(t.alpha) });
    const edfText = el('span', { class: 'sm-gam-edf', text: fmt(t.edf, { digits: 2 }) });
    const critText = el('span', { class: 'sm-gam-crit', text: '' });
    const info = el('div', { class: 'sm-gam-terminfo' },
      el('span', null, el('b', { text: 'EDF ' }), edfText),
      el('span', null, el('b', { text: 'Penalty α ' }), aText),
      el('span', { class: 'sm-gam-basis', text: `${BASIS_LABEL[t.basis]}, ${t.df} basis functions${t.basis === 'bs' ? `, degree ${t.degree}` : ''}` }));
    const sliderRow = el('label', { class: 'sm-gam-sliderrow', dataset: { noexport: '' } }, el('span', { text: 'rougher' }), slider, el('span', { text: 'smoother' }));
    // a preview while the slider moves (one call at a time, the latest wins); the report is redrawn when it is let go
    const vec = () => res.terms.map((u, k) => (k === t.index ? 10 ** Number(slider.value) : u.alpha));
    let busy = false, again = false, alive = true;
    const update = (r) => {
      const u = r.term;
      const nt = termTraces(ctx, u, r.intercept, o);
      edfText.textContent = fmt(u.edf, { digits: 2 });
      critText.textContent = `AIC ${fmt(r.aic, { digits: 2 })} · GCV ${fmt(r.gcv, { sig: 5 })} · total EDF ${fmt(r.edf, { digits: 2 })}`;
      const p = box._plot;
      if (!p || !p.drawn) return;
      const idx = [], ys = [];
      for (const k of ['lower', 'upper', 'resid', 'curve']) if (tr.at[k] != null) { idx.push(tr.at[k]); ys.push(nt.traces[nt.at[k]].y); }
      try { Plotly.restyle(box, { y: ys }, idx); } catch (e) { console.warn('SM: restyle failed', e); }
      if (tr.at.resid != null && p.base[tr.at.resid]) p.base[tr.at.resid].y = nt.traces[nt.at.resid].y.slice();
    };
    const preview = async () => {
      if (busy) { again = true; return; }
      busy = true;
      try {
        do {
          again = false;
          const r = await ctx.call('gam.term', { ...payload, penalty: vec(), index: t.index });
          if (alive) update(r);
        } while (again && alive);
      } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); } finally { busy = false; }
    };
    const schedule = SM.util.debounce(preview, 110);
    slider.addEventListener('input', () => { aText.textContent = fmtA(10 ** Number(slider.value)); schedule(); });
    slider.addEventListener('change', () => { alive = false; setPenalty(ctx, res, t.index, +(10 ** Number(slider.value)).toPrecision(6)); });
    ob.add(box, code ? ctx.code(code) : null, info, sliderRow, critText);
    return ob;
  }

  /* ---- Model Summary, tests, estimates ----------------------------------------------------- */
  function modelSummary(ctx, res, byHand) {
    const s = res.summary;
    const ob = ctx.outline('Model Summary', { key: 'summary', info: 'p:gam:summary' });
    const smoothing = byHand ? 'Penalties set by hand' : s.smoothing_label;
    ob.add(ctx.kv([
      ['Smoothing', smoothing, 'text'],
      [res.summary.sum_weights != null ? 'Observations (Sum Wgts)' : 'Observations', res.summary.sum_weights != null ? `${fmt(s.n)} (${fmt(s.sum_weights, { sig: 6 })})` : s.n, res.summary.sum_weights != null ? 'text' : 'num'],
      ['-LogLikelihood', -s.llf], ['Deviance', s.deviance], ['Pearson ChiSquare', s.pearson],
      ['Scale (dispersion)', s.scale], ['Deviance Explained', s.dev_explained, 'pct'],
      ['AIC', s.aic], ['BIC', s.bic], ['GCV', s.gcv],
      ['Total EDF', s.edf], ['Residual DF', s.df_resid],
      ['Converged', s.converged ? `yes, ${s.iterations} PIRLS iterations` : 'no', 'text'],
    ]));
    ob.add(ctx.rt({
      columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'basis', label: 'Basis', fmt: 'text' }, { key: 'df', label: 'Basis Size', fmt: 'int' }, { key: 'degree', label: 'Degree', fmt: 'int' },
        { key: 'nparm', label: 'Nparm', fmt: 'int' }, { key: 'alpha', label: 'Penalty α' }, { key: 'edf', label: 'EDF', digits: 3 }],
      rows: res.terms.map((t) => ({ term: `s(${t.name})`, basis: BASIS_LABEL[t.basis], df: t.df, degree: t.degree, nparm: t.nparm, alpha: t.alpha, edf: t.edf })),
    }, { caption: 'Smooth Terms', key: 'smoothterms', sortable: false }));
    for (const n of res.notes || []) ob.add(ctx.note(n));
    return ob;
  }

  function testsOutline(ctx, res) {
    const ob = ctx.outline('Smooth Term Tests', { key: 'tests', info: 'p:gam:tests' });
    const how = (res.tests[0] || {}).how === 'test_significance' ? 'statsmodels\' test_significance' : 'a Wald test on the term\'s coefficients';
    ob.add(ctx.rt({
      columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'edf', label: 'EDF', digits: 3 }, { key: 'nparm', label: 'Nparm', fmt: 'int' }, { key: 'chisq', label: 'Wald ChiSquare' },
        { key: 'p', label: 'Prob>ChiSq (EDF)', fmt: 'p' }, { key: 'p_nparm', label: 'Prob>ChiSq (Nparm)', fmt: 'p' }],
      rows: res.tests,
    }, { key: 'tests' }),
    ctx.note(`That the smooth is zero: ${how}, the Wald χ² of all the term's coefficients with their penalized (Bayesian) covariance, referred to χ² on the term's EDF; beside it the same statistic on Nparm degrees of freedom. Both are approximate: on simulated data where a term had no effect, the EDF version rejected at the 5% level in 4 to 8% of the fits and the Nparm version in at most 1.3%. mgcv's summary.gam uses Wood's (2013) test on a reference df instead, which statsmodels does not have.`));
    return ob;
  }

  function estimatesOutline(ctx, res) {
    const ob = ctx.outline('Parameter Estimates', { key: 'estimates' });
    const cols = res.estimates.columns.map((c) => ({ ...c, hidden: (c.key === 'lower' || c.key === 'upper') && !ctx.opt('showCI', true) }));
    ob.add(ctx.rt({ columns: cols, rows: res.estimates.rows }, { key: 'estimates' }));
    const coded = res.estimates.rows.find((r) => /\[/.test(r.term));
    ob.add(ctx.note(`The linear part, with the smooth terms in the model. ${coded ? `A term like ${coded.term} is +1 at that level and −1 at the last one (effect coding). ` : ''}Wald tests with the penalized covariance.`));
    if ((res.effect_tests || []).some((e) => e.nparm > 1)) {
      ob.add(ctx.rt({ columns: [{ key: 'source', label: 'Source', fmt: 'text' }, { key: 'nparm', label: 'Nparm', fmt: 'int' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'chisq', label: 'Wald ChiSquare' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: res.effect_tests },
        { caption: 'Linear Effect Tests', key: 'effecttests' }));
    }
    return ob;
  }

  /* ---- diagnostics -------------------------------------------------------------------------------- */
  async function diagnostics(ctx, res, payload) {
    const P = pal();
    const d = res.diag;
    const y = res.model.response;
    const plots = [];
    if (ctx.opt('actual', true)) {
      const ob = ctx.outline('Actual by Predicted Plot', { key: 'actpred' });
      const [lo, hi] = extent(d.predicted, d.actual);
      const code = await plotCode(ctx, payload, 'actual', {});
      ob.add(withCode(ctx, rowPlot(ctx, { x: d.predicted, y: d.actual, rows: d.rows, xTitle: `${y} Predicted`, yTitle: res.model.event != null ? `${y} (${res.model.event} = 1)` : `${y} Actual`, lines: [lineTrace([lo, hi], [lo, hi], P.fit, 'solid', 1.4)], width: 380, height: 300, title: `${y} actual by predicted` }), code));
      plots.push(ob.el);
    }
    if (ctx.opt('residual', true)) {
      const ob = ctx.outline('Residual by Predicted Plot', { key: 'residpred' });
      const code = await plotCode(ctx, payload, 'residual', {});
      ob.add(withCode(ctx, rowPlot(ctx, { x: d.predicted, y: d.residual, rows: d.rows, xTitle: `${y} Predicted`, yTitle: `${y} Residual`, hlines: [{ y: 0, color: P.mean }], width: 380, height: 300, title: `${y} residual by predicted` }), code));
      plots.push(ob.el);
    }
    if (plots.length > 1) ctx.container.append(ctx.row(...plots));
    if (ctx.opt('devqq', true)) {
      const r = d.resid_dev;
      const n = r.length;
      const order = r.map((_, k) => k).sort((a, b) => r[a] - r[b]);
      const rk = SM.util.ranks(r);
      const z = order.map((k) => qnorm(rk[k] / (n + 1)));
      const yv = order.map((k) => r[k]);
      const m = yv.reduce((a, b) => a + b, 0) / n;
      const sd = Math.sqrt(yv.reduce((a, b) => a + (b - m) ** 2, 0) / Math.max(1, n - 1));
      const [zl, zh] = extent(z);
      const ob = ctx.outline('Deviance Residual Normal Quantile Plot', { key: 'devqq' });
      const code = await plotCode(ctx, payload, 'devqq', {});
      ob.add(
        withCode(ctx, rowPlot(ctx, { x: z, y: yv, rows: order.map((k) => d.rows[k]), xTitle: 'Normal Quantile', yTitle: 'Deviance Residual', lines: [lineTrace([zl, zh], [m + sd * zl, m + sd * zh], P.fit)], width: 360, height: 290, title: `${y} deviance residual normal quantile plot` }), code),
        ctx.note('Each deviance residual against Φ⁻¹(r/(n+1)), r its rank; the line has the residuals\' mean and standard deviation.'));
    }
  }

  /* ---- the Prediction Profiler --------------------------------------------------------------------
     The shared profiler (SM.profiler, gam.profile from profile.expose):
     the prediction on the response scale as each term varies, the others
     at their current values, with its confidence band; desirability,
     Maximize Desirability and variable importance in its red triangle. */
  async function profiler(ctx, payload) {
    const bounded = payload.family === 'binomial';
    return SM.profiler.render(ctx, null, {
      sources: [{ fn: 'gam.profile', payload }], option: 'profiler', info: 'p:gam:profiler', stateKey: `prof:${ctx.byLabel || ''}`,
      note: `The prediction of the mean on the response scale${bounded ? ' (a probability)' : ''}, with its ${fmt(100 * (1 - ctx.alpha))}% confidence interval (statsmodels' get_prediction). Drag a red dashed line, click in a plot, or type a value.`,
    });
  }

  /* ---- Surface Plot: two smooth terms together ---------------------------------------------------- */
  async function surface(ctx, res, payload) {
    const k = res.terms.length;
    const ob = ctx.outline('Surface Plot', { key: 'surface', info: 'p:gam:smooth', menu: () => [{ label: 'Remove', action: () => ctx.set('surface', false) }] });
    if (k < 2) { ob.add(ctx.note('The surface needs two smooth terms.')); return; }
    const key = `surfaceTerms:${ctx.byLabel || ''}`;
    const names = res.terms.map((t) => t.name);
    const st = ctx.opt(key, null) || {};
    let a = names.indexOf(st.x), b = names.indexOf(st.y);
    if (a < 0) a = 0;
    if (b < 0 || b === a) b = a === 0 ? 1 : 0;
    const r = await ctx.call('gam.surface', { ...payload, first: a, second: b, n: 40 });
    const mkSel = (label, value, fn) => { const s = el('select', { 'aria-label': label }, ...names.map((nm, i) => el('option', { value: String(i), text: nm }))); s.value = String(value); s.addEventListener('change', () => fn(Number(s.value))); return el('label', { class: 'sm-gam-opt' }, el('span', { text: label }), s); };
    const setSt = (x, y) => ctx.set(key, { x: names[x], y: names[y] });
    ob.add(el('div', { class: 'sm-gam-controls', dataset: { noexport: '' } },
      mkSel('Horizontal', a, (v) => setSt(v, v === b ? a : b)), mkSel('Vertical', b, (v) => setSt(v === a ? b : a, v))));
    const traces = [
      { type: 'contour', x: r.x, y: r.y, z: r.z, colorscale: 'Viridis', contours: { coloring: 'heatmap', showlabels: true, labelfont: { size: 9, color: '#fff' } }, colorbar: { thickness: 10, len: 0.9, title: { text: `s(${SM.report.plotlyText(r.xname)}) + s(${SM.report.plotlyText(r.yname)})`, side: 'right', font: { size: 10 } } },
        hovertemplate: `${SM.report.plotlyText(r.xname)} %{x:.4g}<br>${SM.report.plotlyText(r.yname)} %{y:.4g}<br>sum %{z:.4g}<extra></extra>` },
      { type: 'scatter', mode: 'markers', x: r.points.x, y: r.points.y, rows: r.points.rows, marker: { size: 5, color: 'rgba(255,255,255,0.85)', line: { width: 1, color: '#222' } }, name: 'Rows' },
    ];
    ob.setTitle(`Surface Plot: s(${r.xname}) + s(${r.yname})`);
    const code = await plotCode(ctx, payload, 'surface', { first: a, second: b, n: 40 });
    ob.add(withCode(ctx, ctx.plot(traces, { xaxis: { title: { text: r.xname } }, yaxis: { title: { text: r.yname } }, margin: { l: 58, r: 12, t: 8, b: 46 } }, { width: W(470), height: 380, title: `${r.xname} and ${r.yname} surface` }), code),
      ctx.note('The sum of the two partial effects on the scale of the linear predictor (an additive model has no interaction: the contours are the two curves added). The points are the rows (linked).'));
  }

  /* ---- Compare with the linear model -------------------------------------------------------------- */
  async function compareOutline(ctx, payload) {
    const r = await ctx.call('gam.compare', { ...payload, alpha: ctx.alpha });
    const ob = ctx.outline('Compare with Linear Model', { key: 'compare', info: 'p:gam:summary', menu: () => [{ label: 'Remove', action: () => ctx.set('compare', false) }] });
    ob.add(ctx.rt({ columns: [{ key: 'model', label: 'Model', fmt: 'text' }, { key: 'df', label: 'DF (EDF)', digits: 3 }, { key: 'deviance', label: 'Deviance' }, { key: 'aic', label: 'AIC' }, { key: 'bic', label: 'BIC' }], rows: r.models }, { key: 'comparemodels', sortable: false }));
    const t = r.test;
    if (t.stat != null) {
      ob.add(ctx.rt({ columns: [{ key: 'ddev', label: 'Deviance Difference' }, { key: 'ddf', label: 'DF Difference', digits: 3 }, { key: 'stat', label: t.label }, { key: 'p', label: t.label === 'F Ratio' ? 'Prob > F' : 'Prob>ChiSq', fmt: 'p' }], rows: [t] }, { caption: 'Test of the smooths against straight lines', key: 'comparetest', sortable: false }));
    } else ob.add(ctx.note('The additive model has no more degrees of freedom than the linear one: there is nothing to test.'));
    ob.add(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }], rows: r.linear }, { caption: 'Linear model estimates', key: 'comparelinear' }));
    for (const n of r.notes || []) ob.add(ctx.note(n));
    ob.add(ctx.code(r.code));
  }

  /* ---- Save Columns ------------------------------------------------------------------------------ */
  function savePartial(ctx, res, t) {
    const pts = t.points;
    const o = termOptions(ctx, ctx.roles('smooth')[t.index], res);
    const c = o.constant ? res.intercept : 0;
    return ctx.saveColumn(`s(${t.name}) ${res.model.response}`, { rows: pts.rows, values: pts.f.map((v) => v + c) },
      { notes: `The partial effect of ${t.name} (on the scale of the linear predictor${o.constant ? ', with the intercept' : ', centred'}) from ${ctx.report.title}` });
  }

  function saveMenu(ctx, res) {
    const d = res.diag;
    const y = res.model.response;
    const pct = fmt(100 * (1 - ctx.alpha));
    const sv = (name, v) => () => ctx.saveColumn(name, { rows: d.rows, values: v });
    return [
      { label: 'Predicted Values', action: sv(`Pred ${y}`, d.predicted) },
      { label: 'Residuals', action: sv(`Residual ${y}`, d.residual) },
      { label: 'Deviance Residuals', action: sv(`Deviance Residual ${y}`, d.resid_dev) },
      { label: 'Pearson Residuals', action: sv(`Pearson Residual ${y}`, d.resid_pearson) },
      { label: 'Linear Predictor', action: sv(`Linear Predictor ${y}`, d.linpred) },
      { label: 'Mean Confidence Interval', action: () => { sv(`Lower ${pct}% Mean ${y}`, d.lower_mean)(); sv(`Upper ${pct}% Mean ${y}`, d.upper_mean)(); } },
      { separator: true },
      { label: 'Partial Effects', submenu: () => [
        ...res.terms.map((t) => ({ label: `s(${t.name})`, action: () => savePartial(ctx, res, t) })),
        { separator: true },
        { label: 'All Smooth Terms', action: () => { for (const t of res.terms) savePartial(ctx, res, t); } },
      ] },
    ];
  }

  /* ---- the top red triangle ------------------------------------------------------------------------ */
  function topMenu(ctx) {
    const st = ctx.gam || {};
    const res = st.res;
    const family = ctx.opt('family', 'normal');
    const link = linkOf(ctx);
    const smoothing = ctx.opt('smoothing', 'aic');
    const byHand = penaltyOf(ctx).byHand;
    const allBs = termsOf(ctx).every((t) => t.basis === 'bs');
    const kfoldOk = family === 'normal' && link === 'identity' && !ctx.name('weight') && !ctx.name('freq') && allBs;
    const setMode = (m) => { clearPenalties(ctx); ctx.set('smoothing', m); };
    const items = [
      { label: 'Distribution', submenu: () => FAMILIES.map(([k, l]) => ({ label: l, checked: family === k, action: () => { clearPenalties(ctx); ctx.spec.options.link = null; ctx.spec.options.target = null; if (ctx.opt('smoothing', 'aic') === 'gcv' && (k === 'binomial' || k === 'poisson')) ctx.spec.options.smoothing = 'aic'; if (k !== 'normal' && ctx.opt('smoothing', 'aic') === 'kfold') ctx.spec.options.smoothing = 'aic'; ctx.set('family', k); } })) },
      { label: 'Link Function', submenu: () => LINKS[family].map(([k, l]) => ({ label: l, checked: link === k, action: () => { clearPenalties(ctx); if (k !== 'identity' && ctx.opt('smoothing', 'aic') === 'kfold') ctx.spec.options.smoothing = 'aic'; ctx.set('link', k); } })) },
      { label: 'Smoothing', submenu: () => [
        { label: 'AIC', checked: !byHand && smoothing === 'aic', action: () => setMode('aic') },
        { label: 'BIC', checked: !byHand && smoothing === 'bic', action: () => setMode('bic') },
        { label: 'GCV', checked: !byHand && smoothing === 'gcv', disabled: family === 'binomial' || family === 'poisson', action: () => setMode('gcv') },
        { label: 'K-Fold Cross-Validation', checked: !byHand && smoothing === 'kfold', disabled: !kfoldOk, action: () => setMode('kfold') },
        { label: 'Number of Folds…', disabled: smoothing !== 'kfold', action: async () => { const v = await SM.ui.form({ title: 'Number of Folds', fields: [{ key: 'k', label: 'Folds (2 to 20)', type: 'number', value: ctx.opt('folds', 5), helpLabel: 'Folds',
          help: 'How many parts K-Fold Cross-Validation splits the rows into, 2 to 20 (5 by default): each part is left out in turn, the model fitted to the rest at every penalty of the grid, and the penalties with the smallest prediction error win. The rows are shuffled once, with a fixed seed.' }], validate: (x) => (Number.isInteger(x.k) && x.k >= 2 && x.k <= 20 ? null : 'a whole number from 2 to 20') }); if (v) ctx.set('folds', v.k); } },
        { separator: true },
        { label: 'Fixed Penalty α…', checked: !byHand && smoothing === 'fixed', action: async () => { const v = await SM.ui.form({ title: 'Fixed Penalty α', lead: 'One penalty weight for every smooth term (statsmodels\' alpha). Its size depends on the units of each column; each term\'s red triangle and slider set its own.', fields: [{ key: 'a', label: 'Penalty α', type: 'number', value: ctx.opt('penalty', 1),
          help: 'The one penalty weight of every smooth term, zero or above (1 at first): larger is smoother, 0 an unpenalized regression spline. OK sets Smoothing to Fixed Penalty α and drops penalties set by hand.' }], validate: (x) => (x.a != null && x.a >= 0 ? null : 'α is zero or above') }); if (v) { clearPenalties(ctx); ctx.spec.options.penalty = v.a; ctx.set('smoothing', 'fixed'); } } },
        { label: 'Penalties Set by Hand', checked: byHand, disabled: true, action: () => {} },
      ] },
      { label: 'Basis for All Terms', submenu: () => [
        ...BASES.map(([k, l]) => ({ label: l, action: () => { clearPenalties(ctx); ctx.set('basis', k); } })),
        { separator: true },
        { label: 'Basis Size (df)…', action: async () => { const v = await SM.ui.form({ title: 'Basis Size for All Terms', fields: [{ key: 'df', label: 'Basis size (df)', type: 'number', value: ctx.opt('df', 10),
          help: 'The number of basis functions of every smooth term, 3 to 60, except a term whose own red triangle has set its own; each term has one parameter fewer. The penalties are chosen again.' }], validate: (x) => (Number.isInteger(x.df) && x.df >= 3 && x.df <= 60 ? null : 'a whole number from 3 to 60') }); if (v) { clearPenalties(ctx); ctx.set('df', v.df); } } },
        { label: 'Degree', submenu: () => DEGREES.map((dg) => ({ label: String(dg), checked: ctx.opt('degree', 3) === dg, action: () => { clearPenalties(ctx); ctx.set('degree', dg); } })) },
      ] },
      { separator: true },
      { label: 'Regression Reports', submenu: () => [ctx.check('Model Summary', 'summary', null, true), ctx.check('Smooth Term Tests', 'tests', null, true), ctx.check('Parameter Estimates', 'estimates', null, true), ctx.check('Show Confidence Intervals', 'showCI', null, true)] },
      { label: 'Diagnostic Plots', submenu: () => [ctx.check('Actual by Predicted', 'actual', null, true), ctx.check('Residual by Predicted', 'residual', null, true), ctx.check('Deviance Residual Normal Quantile Plot', 'devqq', null, true)] },
      ctx.check('Profiler', 'profiler', null, true),
      ctx.check('Surface Plot', 'surface', null, false, { disabled: ctx.roles('smooth').length < 2 }),
      ctx.check('Compare with Linear Model', 'compare', null, false),
      res ? { label: 'Save Columns', submenu: () => saveMenu(ctx, res) } : null,
    ];
    if (res && res.model.levels) {
      items.push({ label: 'Target Level', submenu: () => res.model.levels.map((lv) => ({ label: lv, checked: res.model.event === lv, action: () => { clearPenalties(ctx); ctx.set('target', lv); } })) });
    }
    items.push({ separator: true }, { label: 'Model Dialog', action: () => ctx.report.relaunch() });
    return items.filter(Boolean);
  }

  /* ---- the launch dialog's own part: family, link, smoothing, the basis --------------------------- */
  function launchPart(api, spec) {
    const o0 = (spec && spec.options) || {};
    const mkSel = (label, choices, value) => { const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: v, text: l }))); s.value = value; return s; };
    const fam = mkSel('Distribution', FAMILIES, FAMILY_LABEL[o0.family] ? o0.family : 'normal');
    const link = el('select', { 'aria-label': 'Link Function' });
    const fillLink = (keep) => { const list = LINKS[fam.value]; link.replaceChildren(...list.map(([v, l]) => el('option', { value: v, text: l }))); link.value = list.some(([v]) => v === keep) ? keep : list[0][0]; };
    fillLink(o0.link);
    const smooth = mkSel('Smoothing', SMOOTHING, SMOOTHING_LABEL[o0.smoothing] ? o0.smoothing : 'aic');
    const num = (label, value, size = 5) => { const i = el('input', { type: 'text', inputmode: 'decimal', size, 'aria-label': label }); i.value = String(value); return i; };
    const pen = num('Penalty α', o0.penalty ?? 1, 8);
    const df = num('Basis Size', o0.df ?? 10, 3);
    const deg = mkSel('Degree', DEGREES.map((d) => [String(d), String(d)]), String(o0.degree ?? 3));
    const folds = num('Folds', o0.folds ?? 5, 3);
    const lab = (text, input) => el('label', { class: 'sm-gam-opt' }, el('span', { text }), input);
    const lPen = lab('Penalty α', pen), lFolds = lab('Folds', folds);
    const sync = () => {
      const kf = [...smooth.options].find((x) => x.value === 'kfold');
      const gcv = [...smooth.options].find((x) => x.value === 'gcv');
      kf.disabled = !(fam.value === 'normal' && link.value === 'identity');
      gcv.disabled = fam.value === 'binomial' || fam.value === 'poisson';
      if (smooth.selectedOptions[0] && smooth.selectedOptions[0].disabled) smooth.value = 'aic';
      lPen.hidden = smooth.value !== 'fixed';
      lFolds.hidden = smooth.value !== 'kfold';
    };
    fam.addEventListener('change', () => { fillLink(null); sync(); });
    link.addEventListener('change', sync);
    smooth.addEventListener('change', sync);
    sync();
    const rootEl = el('div', { class: 'sm-gam-launch' },
      el('h4', null, 'Model', typeof KvotInfo !== 'undefined' ? KvotInfo.slot('p:gam:launch') : null),
      el('div', { class: 'sm-gam-launchopts' }, lab('Distribution', fam), lab('Link Function', link), lab('Smoothing', smooth), lPen, lFolds, lab('Basis Size (df)', df), lab('Degree', deg)));
    const toNum = (s) => { const v = Number(String(s).trim().replace(',', '.')); return String(s).trim() === '' || !Number.isFinite(v) ? null : v; };
    return {
      el: rootEl,
      // Penalty α and Folds show only for their choice of Smoothing.
      help: () => [
        ['Distribution', 'The distribution of Y given the terms: Normal (the default), Binomial for a 0/1 or two-level Y, Poisson for counts, Gamma for a positive, right-skewed Y. A categorical Y takes the Binomial only. It sets the links offered.'],
        ['Link Function', 'How the sum of the terms turns into the mean. The first of each list is the usual one: Identity for the Normal, Logit for the Binomial, Log for the Poisson and the Gamma. The partial effects are drawn on the scale of the link.'],
        ['Smoothing', 'How the terms\' penalty weights α are chosen. AIC (the default) or BIC: the penalties with the smallest criterion (BIC smooths more). GCV: generalized cross-validation, not for the Binomial and Poisson. K-Fold Cross-Validation: the smallest prediction error over folds, for the Normal with the identity link and no Weight or Freq. Fixed Penalty α: one α for every term, typed in the box it shows.'],
        ...(smooth.value === 'fixed' ? [['Penalty α', 'The penalty weight of every smooth term, zero or above: larger is smoother, 0 an unpenalized regression spline. Its size depends on each column\'s units, so a value that suits one term may not suit another; the terms\' sliders set their own later.']] : []),
        ...(smooth.value === 'kfold' ? [['Folds', 'The number of folds, 2 to 20 (5 by default): the rows are shuffled once, with a fixed seed, and split into that many parts, each left out in turn while the others fit.']] : []),
        ['Basis Size (df)', 'The number of basis functions of each smooth term, 3 to 60 (10 by default, as mgcv\'s k); a term has one parameter fewer, being centred. A larger basis lets a curve bend more, and the penalty decides how much of it is used. At most the column\'s number of distinct values.'],
        ['Degree', 'The degree of the B-spline pieces, 2 to 5 (3, cubic, by default). The penalty is on the second derivative, so at least 2; a cyclic cubic term (its red triangle, Basis) has no degree to set.'],
      ],
      read() {
        return { options: { family: fam.value, link: link.value, smoothing: smooth.value, penalty: toNum(pen.value), df: toNum(df.value), degree: Number(deg.value), folds: toNum(folds.value) } };
      },
      recall(saved) {
        const o = (saved && saved.options) || {};
        if (FAMILY_LABEL[o.family]) fam.value = o.family;
        fillLink(o.link);
        if (SMOOTHING_LABEL[o.smoothing]) smooth.value = o.smoothing;
        if (o.penalty != null) pen.value = String(o.penalty);
        if (o.df != null) df.value = String(o.df);
        if (o.degree != null) deg.value = String(o.degree);
        if (o.folds != null) folds.value = String(o.folds);
        sync();
      },
    };
  }

  function validate(spec, table) {
    const o = spec.options || {};
    const ids = (k) => (spec.roles[k] || []);
    const y = table.col(ids('y')[0]);
    const seen = new Map();
    for (const k of ['y', 'smooth', 'linear']) for (const id of ids(k)) { if (seen.has(id)) return `${table.col(id).name} is in two roles: each column once (Y, Smooth Terms or Linear Terms).`; seen.set(id, k); }
    if (y && y.isCategorical && o.family !== 'binomial') return `${y.name} is ${y.modelingType}: a categorical Y takes the Binomial distribution (two levels).`;
    if (!Number.isInteger(o.df) || o.df < 3 || o.df > 60) return 'Basis Size: a whole number from 3 to 60.';
    if (o.smoothing === 'fixed' && !(o.penalty >= 0)) return 'Penalty α: a number, zero or above.';
    if (o.smoothing === 'kfold' && (!Number.isInteger(o.folds) || o.folds < 2 || o.folds > 20)) return 'Folds: a whole number from 2 to 20.';
    if (o.smoothing === 'kfold' && ids('weight').length) return 'K-fold cross-validation refits without weights: take the Weight out, or choose AIC, BIC or GCV.';
    if (o.smoothing === 'kfold' && ids('freq').length) return 'K-fold cross-validation would put copies of a row (Freq) into different folds: choose AIC, BIC or GCV.';
    return null;
  }

  /* ---- Help ---------------------------------------------------------------------------------------- */
  const MORE = { label: 'Generalized Additive Model', id: 'help-p-gam' };
  const TOPICS = {
    'p:gam': {
      kicker: 'Analyze', title: 'Generalized Additive Model',
      lead: 'A generalized linear model in which some columns enter as smooth curves, fitted by penalized regression splines: the mean of Y, through the link, is s₁(x₁) + s₂(x₂) + … plus a linear part. statsmodels\' GLMGam; JMP has no such platform (its Fit Spline smooths one X at a time).',
      sections: [
        { heading: 'Roles', choices: [['Y, Response', 'Continuous (Normal, Gamma), 0/1 or two levels (Binomial), counts (Poisson).'], ['Smooth Terms', 'Continuous columns, one smooth curve each.'], ['Linear Terms', 'The parametric part: continuous columns as straight lines, nominal and ordinal ones effect coded, with JMP\'s names.'], ['Weight', 'Variance weights (statsmodels\' var_weights).'], ['Freq', 'Each row counts that many times.'], ['By', 'A separate model for each level.']] },
        { heading: 'Reading the report', text: 'Each smooth term has a partial effect plot: the curve s(x) with its confidence band, the partial residuals (the curve plus the working residual of each row) and a rug of the data. The EDF (effective degrees of freedom) says how wiggly a term is: 1 is a straight line.' },
      ],
      more: MORE,
    },
    'p:gam:launch': {
      kicker: 'Generalized Additive Model', title: 'The model',
      lead: 'The distribution and link of Y, how the penalty weights are chosen, and the basis every smooth term starts with (each term\'s red triangle changes its own).',
      sections: [{ choices: [['AIC, BIC', 'the penalties that give the smallest criterion (statsmodels\' select_penweight)'], ['GCV', 'generalized cross-validation; not for the Binomial and Poisson, whose scale is fixed'], ['K-Fold Cross-Validation', 'the penalties on a grid with the smallest prediction error over the folds (Normal with the identity link, B-spline terms, no weights)'], ['Fixed Penalty α', 'one weight for every term'], ['Basis Size', 'the number of basis functions of a term (mgcv\'s k); the term has one parameter fewer. 10 is mgcv\'s default'], ['Degree', 'of the B-spline; the penalty is on the second derivative, so at least 2']] }],
      more: MORE,
    },
    'p:gam:smooth': {
      kicker: 'Generalized Additive Model', title: 'Smooth terms',
      lead: 'A smooth term is a spline: a sum of basis functions whose coefficients are penalized by α times the integrated squared second derivative, so that a larger α gives a smoother curve.',
      sections: [
        { choices: [['B-Spline', 'statsmodels\' BSplines: knots at the quantiles of the column'], ['Cyclic Cubic', 'CyclicCubicSplines (patsy\'s cc): the curve joins up at the ends, for day of year, hour or angle. The smallest and largest values are the same point of the cycle'], ['Penalty α slider', 'moves α on a log scale, rougher to the left and smoother to the right; the curve refits as it moves, and the report when you let go. The other terms keep their penalties, which are then set by hand (Choose Penalties Automatically, in a term\'s red triangle, goes back)'],
          ['EDF, Penalty α', 'under each plot: the term\'s effective degrees of freedom and its α. While the slider moves, the line below it shows the AIC, GCV and total EDF the new α would give'], ['Partial residuals', 's(x) plus each row\'s working residual: rows far from the curve fit badly'], ['Include Intercept', 'the curve with the intercept added (statsmodels\' include_constant), its band then includes the intercept\'s uncertainty']] },
        { heading: 'Identifiability', text: 'Each term is centred to sum to zero over the rows (mgcv\'s constraint), so the curves are about the intercept and a term has one parameter fewer than its basis size.' },
        { heading: 'Surface Plot', text: 'The sum of two terms\' partial effects over a grid: with no interaction its contours are the two curves added.' },
        { choices: [['Horizontal, Vertical', 'the two smooth terms of the Surface Plot, the first two at first; choosing the one the other axis has swaps them. The points are the rows, linked to the table']] },
      ],
      more: MORE,
    },
    'p:gam:summary': {
      kicker: 'Generalized Additive Model', title: 'Model Summary',
      lead: 'The fit as statsmodels\' GLMGamResults reports it: deviance, Pearson χ², the scale, AIC and BIC (the total EDF counted as the number of parameters), GCV = scale/(1 − EDF/n)², and the EDF of each term.',
      sections: [{ heading: 'Compare with Linear Model', text: 'The same model with each smooth column as a straight line (a GLM): the deviance difference on the difference in degrees of freedom, as an F test when the scale is estimated and a χ² test when it is fixed. Approximate: the additive model is penalized and its degrees of freedom are not whole numbers.' }],
      more: MORE,
    },
    'p:gam:tests': {
      kicker: 'Generalized Additive Model', title: 'Smooth Term Tests',
      lead: 'Whether each smooth term is zero: the Wald χ² of all its coefficients (statsmodels\' test_significance), on the term\'s EDF, and the same statistic on as many degrees of freedom as it has parameters (Nparm). The first is a little too ready to reject, the second too slow; treat both as approximate, and a p-value near the α level as undecided.',
      more: MORE,
    },
    'p:gam:profiler': {
      kicker: 'Generalized Additive Model', title: 'Prediction Profiler',
      lead: 'The predicted mean on the response scale as each term varies, the others held at their current values, with the confidence interval of the mean. Drag a red dashed line, click a plot or type a value; the settings are kept by Redo.',
      sections: [{ heading: 'In the report', choices: [['The value box under a plot', 'the factor\'s current value: type one (Enter), or pick a level for a categorical factor; every plot is drawn again at the new setting'],
        ['The slider', 'moves a continuous factor over the range of its data; the plots follow when you let go'], ['The red dashed line', 'drag it along the plot, or click in the plot, to move that factor there'],
        ['A desirability plot', 'with Desirability Functions on (red triangle), the small plot at the right of a response: click it to set that response\'s goal and desirability'],
        ['Remembered Settings', 'a table of the settings Remember Settings kept; click a line to go back to it']] }],
      more: MORE,
    },
    'p:gam:mgcv': {
      kicker: 'Generalized Additive Model', title: 'statsmodels and mgcv',
      lead: 'The report\'s numbers are statsmodels\' GLMGam, which is not R\'s mgcv.',
      sections: [{ choices: [['Penalty selection', 'statsmodels searches AIC, BIC or GCV by Nelder-Mead over log α (a local search, here kept within 10⁻⁶ to 10⁷ times each term\'s scale: beyond, rounding lets the penalty reach a B-spline\'s straight line and an unbounded search walks off there), or a k-fold grid; mgcv optimizes GCV, UBRE, REML or ML by Newton\'s method, and REML is not in statsmodels'], ['GCV', 'statsmodels\' is scale/(1 − EDF/n)² with the scale already divided by n − EDF, stricter than mgcv\'s nD/(n − EDF)²'], ['EDF', 'both are the trace of the influence of a term\'s coefficients; mgcv also gives a reference df for its tests'], ['Tests', 'statsmodels\' Wald test on the EDF rejects a term with no effect somewhat too often; mgcv\'s Wood (2013) test on a reference df holds its level better'], ['Bases', 'mgcv\'s default is a thin plate regression spline; here B-splines and cyclic cubic splines'], ['α and λ', 'the penalty is α·bᵀSb here and λ·bᵀSb in mgcv: λ = 2α on the same basis']] }],
      more: MORE,
    },
  };

  /* ---- the example: simulated ozone ------------------------------------------------------------------ */
  SM.io.addExample('ozone', {
    label: 'Ozone (365 days): temperature, wind, season',
    about: 'Simulated daily data, not a real series. ozone (ppb) = 30 + 30/(1 + exp(−(T − 20)/3)) + 25·exp(−W/3) + 8·sin(2π(day − 80)/365) − 4 on weekends + normal noise (SD 5), T the temperature (°C) and W the wind (m/s); alert is 0/1 with logit (η − 40)/6, clinic visits Poisson with log mean 0.2 + 0.03η, η the sum of the three smooth parts. For the Generalized Additive Model.',
    make() {
      const r = SM.util.rng('ozone');
      const n = 365;
      const c = { date: [], day: [], weekend: [], temp: [], wind: [], ozone: [], alert: [], visits: [] };
      const t0 = Date.UTC(2025, 0, 1);
      for (let i = 0; i < n; i++) {
        const day = i + 1;
        const date = t0 + i * 86400000;
        const dow = new Date(date).getUTCDay();
        const weekend = dow === 0 || dow === 6;
        const temp = 12 - 10 * Math.cos((2 * Math.PI * (day - 15)) / 365) + r.normal(0, 3);
        const wind = -2 * (Math.log(1 - r.u()) + Math.log(1 - r.u()));   // gamma, shape 2 and scale 2
        const eta = 30 / (1 + Math.exp(-(temp - 20) / 3)) + 25 * Math.exp(-wind / 3) + 8 * Math.sin((2 * Math.PI * (day - 80)) / 365);
        const oz = 30 + eta - (weekend ? 4 : 0) + r.normal(0, 5);
        const alert = r.u() < 1 / (1 + Math.exp(-(eta - 40) / 6)) ? 1 : 0;
        const mu = Math.exp(0.2 + 0.03 * eta);
        let k = 0, p = Math.exp(-mu), s = p;
        const u = r.u();
        while (u > s && k < 200) { k++; p *= mu / k; s += p; }
        c.date.push(date); c.day.push(day); c.weekend.push(weekend ? 'yes' : 'no');
        c.temp.push(+temp.toFixed(1)); c.wind.push(+wind.toFixed(2)); c.ozone.push(+oz.toFixed(1)); c.alert.push(alert); c.visits.push(k);
      }
      return new SM.Table({ name: 'Ozone', source: 'simulated', columns: [
        { name: 'date', dataType: 'numeric', format: { kind: 'date' }, values: c.date },
        { name: 'day of year', dataType: 'numeric', values: c.day },
        { name: 'weekend', dataType: 'character', values: c.weekend, valueOrder: ['no', 'yes'] },
        { name: 'temperature (°C)', dataType: 'numeric', values: c.temp },
        { name: 'wind (m/s)', dataType: 'numeric', values: c.wind },
        { name: 'ozone (ppb)', dataType: 'numeric', values: c.ozone },
        { name: 'alert', dataType: 'numeric', values: c.alert },
        { name: 'clinic visits', dataType: 'numeric', values: c.visits },
      ] });
    },
  });

  /* ---- the platform ---------------------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'gam', label: 'Generalized Additive Model', menu: 'Analyze/Specialized Modeling', order: 45, info: 'p:gam', topics: TOPICS,
    about: 'Generalized additive models by statsmodels\' GLMGam: smooth terms (penalized B-splines or cyclic cubic splines) and a linear part, for a Normal, Binomial, Poisson or Gamma response with a link. The penalty weights are chosen by AIC, BIC, GCV or k-fold cross-validation, or set by hand with a slider per term that refits as it moves. Partial effect plots with bands and linked partial residuals, EDF and Wald tests, the linear estimates, residual plots, the Prediction Profiler, a surface of two smooths, and a comparison with the linear model.',
    uses: ['statsmodels.gam.api.GLMGam', 'statsmodels.gam.smooth_basis.BSplines, CyclicCubicSplines, GenericSmoothers', 'GLMGam.select_penweight, select_penweight_kfold', 'GLMGamResults.partial_values, test_significance, edf, gcv, get_prediction', 'statsmodels.genmod.generalized_linear_model.GLM', 'scipy.optimize.fmin (Nelder-Mead)', 'patsy'],
    launch: {
      lead: 'Choose the Y, the columns to enter as smooth curves and those to enter as straight lines (or levels), and the distribution. The penalty weights are chosen by AIC unless you say otherwise.',
      roles: [
        { key: 'y', label: 'Y, Response', min: 1, max: 1, hint: 'required: continuous, 0/1, counts',
          help: 'The response, whose mean (through the link) is the sum of the terms. Continuous for the Normal, above zero for the Gamma, 0/1 or two levels for the Binomial (the event is 1, or the first level unless Target Level says otherwise), counts of zero or more for the Poisson.' },
        { key: 'smooth', label: 'Smooth Terms', min: 1, numeric: true, types: ['continuous'], hint: 'required: continuous',
          help: 'The columns that enter as smooth curves, a penalized spline each (at least four distinct values). They start with the basis size and degree below; each term\'s red triangle and slider change its own.' },
        { key: 'linear', label: 'Linear Terms', hint: 'optional: the parametric part',
          help: 'Optional: the parametric part, main effects. A continuous column enters as a straight line, a nominal or ordinal one effect coded with JMP\'s names; a column whose effect may bend belongs in Smooth Terms instead.' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'Optional variance weights (statsmodels\' var_weights): a row of weight 2 has half the variance of a row of weight 1, so it counts twice as much in the fit. Not with K-Fold Cross-Validation.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'Optional: each row counts that many times (its whole part; 0 leaves it out), as that many copies of it. Not with K-Fold Cross-Validation, which would put a row\'s copies into different folds.' },
        { key: 'by', label: 'By', hint: 'optional',
          help: 'A separate model of the rows of each level (each combination of levels, with several By columns). Rows with a missing By value are left out.' },
      ],
      extra: launchPart,
      validate,
    },
    title(spec, table) {
      const id = ((spec.roles || {}).y || [])[0];
      const c = id && table ? table.col(id) : null;
      return c ? `Generalized Additive Model for ${c.name}` : 'Generalized Additive Model';
    },
    triangle: (ctx) => topMenu(ctx),
    async render(ctx) {
      const yc = ctx.role('y');
      if (yc && yc.isCategorical && ctx.opt('family', 'normal') !== 'binomial') {
        ctx.gam = { res: null };
        ctx.container.append(ctx.warn(`${yc.name} is ${yc.modelingType}: the ${FAMILY_LABEL[ctx.opt('family', 'normal')]} distribution needs a continuous Y. A two-level Y takes the Binomial (the top red triangle: Distribution).`));
        return;
      }
      const payload = modelOf(ctx);
      const pen = penaltyOf(ctx);
      const res = await ctx.call('gam.fit', { ...payload, alpha: ctx.alpha });
      ctx.gam = { res, payload };
      const m = res.model;
      const s = res.summary;
      ctx.container.append(el('p', { class: 'sm-gam-modelline' }, ...[
        ['Response', `${m.response}${m.event != null ? ` (event: ${m.event})` : ''}`], ['Distribution', m.distribution], ['Link', m.link],
        ['Smoothing', pen.byHand ? 'penalties set by hand' : s.smoothing_label], ['Observations', fmt(s.n)], ['Total EDF', fmt(s.edf, { digits: 2 })],
      ].map(([k, v]) => el('span', null, el('b', { text: `${k}: ` }), v))));
      const smooth = ctx.roles('smooth');
      const terms = ctx.outline('Smooth Terms', { key: 'smooth', info: 'p:gam:smooth' });
      const wrap = el('div', { class: 'sm-gam-terms' });
      terms.add(wrap);
      for (const [j, t] of res.terms.entries()) await termOutline(ctx, wrap, t, res, payload, smooth[j]);
      terms.add(ctx.note(`Each curve is the term's partial effect on the scale of the linear predictor (${m.link.toLowerCase()} link), centred to sum to zero over the rows, with a pointwise ${fmt(100 * (1 - ctx.alpha))}% band from the penalized (Bayesian) covariance, as mgcv draws it. Points: partial residuals (the curve plus the working residual), linked to the rows. The slider sets the term's penalty α.`));
      if (ctx.opt('summary', true)) modelSummary(ctx, res, pen.byHand);
      if (ctx.opt('tests', true)) testsOutline(ctx, res);
      if (ctx.opt('estimates', true)) estimatesOutline(ctx, res);
      await diagnostics(ctx, res, payload);
      if (ctx.opt('profiler', true)) await profiler(ctx, payload);
      if (ctx.opt('surface', false)) await surface(ctx, res, payload);
      if (ctx.opt('compare', false)) await compareOutline(ctx, payload);
      ctx.container.append(el('p', { class: 'sm-ob-note' }, 'statsmodels\' GAM is not mgcv: the penalties are found by a local search over AIC, BIC or GCV (no REML), its GCV is stricter than mgcv\'s, and its smooth term tests are approximate (see Smooth Term Tests). ',
        typeof KvotInfo !== 'undefined' ? KvotInfo.slot('p:gam:mgcv') : null));
      ctx.container.append(ctx.code(res.code));
    },
  });
}(typeof self !== 'undefined' ? self : this));
