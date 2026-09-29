/* ==========================================================================
   SMUI.HTML: ANALYZE > SPECIALIZED MODELING > GAUSSIAN PROCESS

   JMP's Gaussian Process on scikit-learn's GaussianProcessRegressor
   (resources/py/smui/gaussproc.py): a model per continuous Y over
   continuous X's, fitted by maximum likelihood.

     Actual by Predicted Plot   the actual values against the jackknife
                                (leave-one-out) predictions, linked to rows
     Model Report               JMP's Theta per factor and the functional
                                ANOVA of the fitted surface (Total
                                Sensitivity, Main Effect, the interactions);
                                Mu, Sigma², the nugget, -2 LogLikelihood
     Marginal Model Plots       each factor's main effect E[f | x]
     Prediction Profiler        with the band of the process's standard
                                deviation
     Save Columns               Prediction, Std Error, Jackknife Predicted

   With one Y its items are on the top red triangle; with several, each Y
   has its outline (Response Y) and red triangle. The launch's Rows to Fit
   caps the rows the model is fitted to (a random subset from the seed):
   the fit grows as the cube of the rows.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const MORE = { label: 'Gaussian Process', id: 'help-p-gaussproc' };
  const CORR = [['gaussian', 'Gaussian'], ['matern52', 'Matérn ν = 5/2'], ['matern32', 'Matérn ν = 3/2']];
  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));

  /* The not-fitted rows' colour (not the selection's orange), readable on both themes. */
  function colors() {
    const c = SM.util.themeColors();
    return { ...c, other: c.dark ? '#5fb36b' : '#3a7d44', point: SM.report.BASE };
  }

  const scatterType = (n) => (n > 4000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter');
  const markerSize = (n) => (n > 2000 ? 3.5 : n > 600 ? 4.5 : 6);
  const wide = (tbl) => el('div', { class: 'sm-gp-scroll' }, tbl);
  const intOr = (v, d, lo) => { const x = Math.round(Number(v)); return Number.isFinite(x) && x >= lo ? x : d; };
  // Optimizer Restarts left empty: the backend's rule (2 for at most 150 rows fitted, else none)
  const restartsOf = (v) => (v == null || String(v).trim() === '' ? null : intOr(v, null, 0));

  /* What every call of the report sends: the factors and the fit's settings. */
  function base(ctx) {
    return {
      x: ctx.names('x'), correlation: ctx.opt('correlation', 'gaussian'), nugget: !!ctx.opt('nugget', false),
      max_rows: intOr(ctx.opt('maxRows', 400), 400, 3), restarts: restartsOf(ctx.opt('restarts', null)), seed: SM.predict.seed(ctx),
    };
  }

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx) {
    const ys = ctx.roles('y');
    const b = base(ctx);
    const multi = ys.length > 1;
    for (const y of ys) {
      const parent = multi ? ctx.outline(`Response ${y.name}`, { key: `resp:${y.id}`, menu: () => yItems(ctx, y) }) : ctx.top;
      await response(ctx, y, parent, b);
    }
  }

  async function response(ctx, y, parent, b) {
    const sc = y.id;
    const payload = { ...b, y: y.name };
    // a line of progress while the optimizer runs (a large fit takes seconds)
    const note = ctx.headless ? null : el('p', { class: 'sm-ob-note sm-gp-progress', role: 'status', text: `Fitting the Gaussian process of ${y.name}…` });
    if (note) parent.add(note);
    const off = note ? SM.engine.on('progress', (p) => {
      if (!p || p.what !== 'gaussproc') return;
      const t = `Fitting the Gaussian process of ${y.name}${ctx.byLabel ? ` (${ctx.byLabel})` : ''}: ${p.done} of ${p.total} optimizer starts done…`;
      note.textContent = t;
      ctx.report.noteEl.textContent = t;
    }) : null;
    let res;
    try { res = await ctx.call('gaussproc.fit', payload); } catch (e) { parent.add(ctx.error(e)); return; } finally { if (off) off(); if (note) note.remove(); }
    if (res.error) { parent.add(ctx.warn(`${y.name}: ${res.error}`)); return; }
    const lines = [`${fmt(res.n)} rows with ${y.name} and every factor${res.capped ? `: the model is fitted to ${fmt(res.n_fit)} of them, drawn at random with the seed ${res.seed} (Rows to Fit, ${fmt(res.max_rows)}); the others are predicted by it` : ''}.`,
      `${res.correlation_label} correlation${res.nugget != null ? ' with a nugget' : ''}, by maximum likelihood (L-BFGS-B${res.restarts ? `, from 1 + ${res.restarts} starts` : ''}).`, ...res.notes];
    parent.add(ctx.note(lines.join(' ')));
    if (ctx.opt('abp', true, sc)) actualByPredicted(ctx, parent, y, res);
    if (ctx.opt('modelReport', true, sc)) modelReport(ctx, parent, y, res);
    if (ctx.opt('marginal', true, sc)) marginalPlots(ctx, parent, y, res);
    if (ctx.opt('profiler', false, sc) && !ctx.headless) {
      await SM.profiler.render(ctx, parent, { sources: [{ fn: 'gaussproc.profile', payload }], scope: sc, option: 'profiler',
        note: `Drag the red dashed line of a factor, click in its plot, or type its value. The dotted band is the prediction ± ${fmt(SM.util.qnorm(1 - ctx.alpha / 2), { sig: 4 })} standard deviations of the process (scikit-learn's predict with return_std${res.nugget != null ? ', which includes the nugget\'s noise' : ''}).` });
    }
  }

  /* ---- Actual by Predicted: the jackknife predictions -------------------------------- */
  function actualByPredicted(ctx, parent, y, res) {
    const ob = ctx.outline('Actual by Predicted Plot', { parent, key: 'abp', info: 'p:gaussproc:abp' });
    const col = colors();
    let lo = Infinity, hi = -Infinity;
    for (const v of [...res.jackknife, ...res.actual, ...res.other_pred, ...res.other_actual]) if (Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    const n = res.n;
    const traces = [{ type: scatterType(res.n_fit), mode: 'markers', x: res.jackknife, y: res.actual, rows: res.fit_rows, marker: { size: markerSize(n) }, name: 'Jackknife (rows fitted)' }];
    if (res.other_rows.length) traces.push({ type: scatterType(res.other_rows.length), mode: 'markers', x: res.other_pred, y: res.other_actual, rows: res.other_rows, marker: { size: markerSize(n), color: col.other, symbol: 'diamond' }, name: 'Predicted (not fitted)' });
    traces.push({ type: 'scatter', mode: 'lines', x: [lo, hi], y: [lo, hi], line: { color: col.muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false });
    const two = res.other_rows.length > 0;
    const pc = res.plots || {};
    ob.add(ctx.row(SM.predict.plotWithCode(ctx, traces, {
      xaxis: { title: { text: `${T(y.name)} Jackknife Predicted` } }, yaxis: { title: { text: T(y.name) } }, margin: { l: 58, r: 12, t: two ? 26 : 8, b: 44 },
      showlegend: two, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' },
    }, { width: W(430), height: 380, title: `${y.name} actual by jackknife predicted` }, pc.head_code, pc.abp),
    ctx.kv([['Jackknife RSquare', res.jack_rsquare], ['Jackknife RASE', res.jack_rase], ['N (rows fitted)', res.n_fit, 'int']])));
    ob.add(ctx.note(`Each row the model is fitted to, against its jackknife prediction: the prediction of the model without that row, the kernel and the mean and scale held (in closed form, y − [K⁻¹y]ᵢ/[K⁻¹]ᵢᵢ: Rasmussen and Williams 2006, eq. 5.12)${two ? '; the diamonds are the rows not fitted, predicted by the whole model' : ''}. JMP's Gaussian Process has no validation rows: this plot is its check. The RSquare and RASE of the jackknife predictions are not in JMP's report. Drag over points to select rows.`));
  }

  /* ---- Model Report: theta and the functional ANOVA ------------------------------------ */
  function modelReport(ctx, parent, y, res) {
    const ob = ctx.outline('Model Report', { parent, key: 'modelreport', info: 'p:gaussproc:report' });
    const gauss = res.correlation === 'gaussian';
    const cols = [{ key: 'column', label: 'Column', fmt: 'text' }];
    if (gauss) cols.push({ key: 'theta', label: 'Theta' });
    cols.push({ key: 'length', label: 'Length Scale', hidden: gauss });
    cols.push({ key: 'total', label: 'Total Sensitivity', digits: 4 }, { key: 'main', label: 'Main Effect', digits: 4 });
    if (res.x.length > 1) res.x.forEach((nm, j) => cols.push({ key: `i${j}`, label: `${nm} Interaction`, digits: 4 }));
    ob.add(wide(ctx.rt({ caption: `${res.correlation_label} Correlation`, columns: cols, rows: res.report }, { key: 'gpreport', sortable: false })));
    ob.add(ctx.kv([['Mu', res.mu], ['Sigma²', res.sigma2], res.nugget != null ? ['Nugget', res.nugget] : null, ['−2 LogLikelihood', res.m2ll]], { caption: 'Parameters' }));
    const how = res.fanova === 'quadrature'
      ? `Each main effect E[f | x] and each pair's E[f | x, x′] are integrated over the other factors in closed form (the Gaussian correlation is a product over the factors) and over their own ranges by Gauss–Legendre quadrature${res.x.length > 2 ? '; the total variance over 2¹⁴ scrambled Sobol points (seed)' : ''}.`
      : `Matérn is not a product over the factors: the variances are pick-freeze quasi-Monte Carlo estimates over 2¹² scrambled Sobol points (Saltelli 2010, seed ${res.seed}); their last digits move with the seed.`;
    ob.add(ctx.note(`${gauss ? 'Theta is JMP\'s θ in the correlation exp(−Σ θₖ (xₖ − x′ₖ)²). scikit-learn\'s RBF kernel is exp(−Σ (xₖ − x′ₖ)²/(2ℓₖ²)), so θ = 1/(2ℓ²), ℓ the length scale in the column\'s own units (right click, Columns, shows it). ' : 'Matérn has no θ: its length scale ℓ is per factor, in the column\'s units, and its smoothness ν is fixed. '}The sensitivities are JMP's functional ANOVA of the fitted surface with each factor uniform over its range in the rows fitted: the Main Effect is the variance of E[f | x] over the total variance, an Interaction the share of a pair beyond their main effects, and the Total Sensitivity a factor's main effect plus its interactions. ${how}`),
    ctx.note(`Mu is the mean of ${y.name} (scikit-learn's normalize_y; JMP estimates μ by generalized least squares), Sigma² the constant kernel times the variance of ${y.name}${res.nugget != null ? `, the Nugget the white-noise level over Sigma² (a ridge on the correlation matrix, as JMP adds it; the noise variance is ${fmt(res.noise_var, { sig: 5 })})` : ''}. −2 LogLikelihood is scikit-learn's log marginal likelihood on the scale of ${y.name}: −2 (log L − n log sd). Kernel: ${res.kernel}.`),
    ctx.code(res.code));
  }

  /* ---- Marginal Model Plots: the main effect curves ------------------------------------ */
  function marginalPlots(ctx, parent, y, res) {
    const ob = ctx.outline('Marginal Model Plots', { parent, key: 'marginal', info: 'p:gaussproc:marginal' });
    const col = colors();
    let lo = Infinity, hi = -Infinity;
    for (const m of res.marginal) for (const v of m.f) if (Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    const pad = 0.06 * ((hi - lo) || Math.abs(hi) || 1);
    const k = res.marginal.length;
    const pc = res.plots || {};
    const plots = res.marginal.map((m, j) => SM.predict.plotWithCode(ctx, [{ type: 'scatter', mode: 'lines', x: m.t, y: m.f, line: { color: col.point, width: 2 }, hovertemplate: `${T(m.x)} %{x:.5g}<br>${T(y.name)} %{y:.5g}<extra></extra>`, name: T(m.x) }],
      { xaxis: { title: { text: T(m.x) } }, yaxis: { title: { text: T(y.name) }, range: [lo - pad, hi + pad] }, margin: { l: 58, r: 8, t: 8, b: 42 } },
      { width: W(k > 3 ? 240 : 300), height: 230, title: `${y.name} marginal model plot of ${m.x}`, select: false }, pc.head_code, (pc.marginal || [])[j]));
    ob.add(ctx.row(...plots), ctx.note(`Each factor's main effect: the prediction averaged over the other factors, each uniform over its range (${res.fanova === 'quadrature' ? 'in closed form' : 'by quasi-Monte Carlo, 256 points'}). The plots share the ${y.name} scale, so a flat one is a factor with little effect.`));
  }

  /* ======================================================================
     MENUS
     ====================================================================== */
  function yItems(ctx, y) {
    const sc = y.id;
    return [
      ctx.check('Actual by Predicted Plot', 'abp', sc, true),
      ctx.check('Model Report', 'modelReport', sc, true),
      ctx.check('Marginal Model Plots', 'marginal', sc, true),
      ctx.check('Profiler', 'profiler', sc, false),
      { separator: true },
      { label: 'Save Columns', submenu: () => [
        { label: 'Save Prediction', action: () => save(ctx, y, 'pred') },
        { label: 'Save Std Error', action: () => save(ctx, y, 'std') },
        { label: 'Save Jackknife Predicted Values', action: () => save(ctx, y, 'jack') },
      ] },
    ];
  }

  function globalItems(ctx) {
    const cur = ctx.opt('correlation', 'gaussian');
    return [
      { label: 'Correlation Type', submenu: () => CORR.map(([k, l]) => ({ label: k === 'gaussian' ? l : `${l} (not JMP's Cubic)`, checked: cur === k, action: () => ctx.set('correlation', k) })) },
      ctx.check('Estimate Nugget Parameter', 'nugget', null, false),
      { label: 'Fit Settings…', action: () => settingsDialog(ctx) },
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
  }

  async function settingsDialog(ctx) {
    // no info: the platform's topic lists these options already; the form's (i) is its fields
    const v = await SM.ui.form({
      title: 'Fit Settings',
      lead: 'The rows the model is fitted to and the optimizer\'s restarts. Both change the model; the seed draws the rows (above Rows to Fit) and the restarts.',
      fields: [
        { key: 'maxRows', label: 'Rows to Fit, at most', type: 'number', value: intOr(ctx.opt('maxRows', 400), 400, 3), help: HELP.maxRows },
        { key: 'restarts', label: 'Optimizer Restarts (empty: 2 for at most 150 rows fitted)', type: 'number', value: restartsOf(ctx.opt('restarts', null)), help: HELP.restarts },
        { key: 'seed', label: 'Random Seed (empty: the one drawn)', type: 'text', value: ctx.opt('seed', '') ?? '', help: 'The seed of the rows drawn above Rows to Fit, of the optimizer\'s restarts and of the Sobol points of the sensitivities: a whole number. Empty keeps the seed drawn for this report.' },
      ],
      validate: (x) => (!(Number.isInteger(x.maxRows) && x.maxRows >= 3) ? 'Rows to Fit is a whole number, 3 or more'
        : !(x.restarts == null || (Number.isInteger(x.restarts) && x.restarts >= 0 && x.restarts <= 50)) ? 'Optimizer Restarts is a whole number from 0 to 50, or empty'
          : (x.seed.trim() !== '' && !Number.isInteger(Number(x.seed))) ? 'The seed is a whole number' : null),
    });
    if (!v) return;
    ctx.set('maxRows', v.maxRows, null, { rerun: false });
    ctx.set('restarts', v.restarts, null, { rerun: false });
    ctx.set('seed', v.seed.trim(), null);
  }

  async function save(ctx, y, what) {
    try {
      const b = base(ctx);
      const r = await ctx.call('gaussproc.save', { ...b, y: y.name });
      const from = `from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`;
      if (what === 'pred') ctx.saveColumn(`Predicted ${y.name}`, { rows: r.rows, values: r.pred }, { notes: `the Gaussian process's prediction, ${from}` });
      else if (what === 'std') ctx.saveColumn(`StdErr Pred ${y.name}`, { rows: r.rows, values: r.std }, { notes: `the Gaussian process's standard deviation (scikit-learn predict with return_std${b.nugget ? ', the nugget\'s noise included' : ''}), ${from}` });
      else ctx.saveColumn(`Jackknife Predicted ${y.name}`, { rows: r.jack_rows, values: r.jack }, { notes: `the leave-one-out prediction of each row fitted, the kernel held, ${from}` });
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  /* ======================================================================
     THE LAUNCH'S ROLES AND OPTIONS, with what each is for (the (i))
     ====================================================================== */
  const HELP = {
    maxRows: 'JMP fits every row; the fit grows as the cube of the rows, so with more rows than this (400) the model is fitted to that many rows drawn at random with the seed, and the other rows are predicted by it (the diamonds of Actual by Predicted). A whole number, 3 or more: raise it for a better model at the cost of time.',
    restarts: 'The optimizer of the likelihood (L-BFGS-B) starts from length scales equal to the columns\' standard deviations; each restart starts it again from a random point (scikit-learn\'s n_restarts_optimizer, drawn from the seed) and the best likelihood is kept: slower, and safer against a local maximum. Empty: 2 restarts when at most 150 rows are fitted (cheap), none above; from 0 to 50.',
    seed: 'The seed of the rows drawn above Rows to Fit, of the optimizer\'s restarts and of the Sobol points of the sensitivities. Empty: a seed drawn at the first run and kept with the report, so that Redo, a project and the Python code give the same model.',
  };
  const ROLES = [
    { key: 'y', label: 'Y', min: 1, numeric: true, types: ['continuous'], hint: 'required: continuous, a model each',
      help: 'One or more continuous responses: a Gaussian process is fitted to each by maximum likelihood, with the same factors and settings (with several, each has an outline of its own). It suits a smooth response, most of all a deterministic computer experiment.' },
    { key: 'x', label: 'X', min: 1, numeric: true, types: ['continuous'], hint: 'required: continuous factors',
      help: 'The continuous factors, in their own units (they are not rescaled): the correlation of two runs falls with their distance in each factor, at a rate fitted per factor (Theta, or a length scale). Rows missing a factor are left out.' },
    { key: 'by', label: 'By', hint: 'optional', help: 'A separate model and report for each level of the By column (each combination of levels, with several). Rows with a missing By value are left out.' },
  ];
  const OPTIONS = [
    { key: 'correlation', label: 'Correlation Type', type: 'select', value: 'gaussian', choices: CORR.map(([k, l]) => [k, k === 'gaussian' ? l : `${l} (not JMP's Cubic)`]),
      help: 'How the correlation of two runs falls with their distance. Gaussian (JMP\'s default): exp(−Σ θₖ (xₖ − x′ₖ)²), scikit-learn\'s RBF with a length scale ℓ per factor (θ = 1/(2ℓ²)), an infinitely smooth surface. Matérn ν = 5/2 or 3/2: scikit-learn\'s Matérn, a surface twice or once differentiable, for a response that changes more abruptly. JMP\'s other choice, Cubic, is not in scikit-learn; Matérn is offered in its place, not as it.' },
    { key: 'nugget', label: 'Estimate Nugget Parameter', type: 'check', value: false, hint: 'smooth over noise (WhiteKernel) instead of going through every row',
      help: 'Adds scikit-learn\'s WhiteKernel, a noise level fitted with the rest: the model no longer goes through every row but smooths over noise. Turn it on for a noisy response or replicated settings; off (the default), the fit interpolates the rows, as it should for a deterministic computer experiment.' },
    { key: 'maxRows', label: 'Rows to Fit, at Most', type: 'number', value: 400, hint: 'more rows than this: the model is fitted to a random subset of this size (from the seed), the rest predicted', help: HELP.maxRows },
    { key: 'restarts', label: 'Optimizer Restarts', type: 'number', value: null, hint: 'extra optimizer starts from random points (from the seed), the best likelihood kept; empty: 2 when at most 150 rows are fitted, else none', help: HELP.restarts },
    { key: 'seed', label: 'Random Seed', type: 'text', value: '', hint: 'empty: a seed drawn now and kept with the report', help: HELP.seed },
  ];

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:gaussproc': {
      kicker: 'Analyze > Specialized Modeling', title: 'Gaussian Process',
      lead: 'A smooth surface through the responses of an experiment, most of all a deterministic computer experiment: the response is a Gaussian process over the factors, whose correlation falls with the distance between two settings, fitted by maximum likelihood. It predicts between the runs and says how much each factor, and each pair of factors, moves the response. The numbers are scikit-learn\'s GaussianProcessRegressor (normalize_y), one model per Y.',
      sections: [
        { heading: 'Roles', choices: [['Y', 'One or more continuous responses: a model each.'], ['X', 'Continuous factors.'], ['By', 'A separate analysis for each level.']] },
        // the launch's options (Correlation Type and the nugget are in the red triangle too, the others in Fit Settings…)
        { heading: 'Options', choices: OPTIONS.map((o) => [o.label, o.help]) },
        { heading: 'Validation', text: 'JMP\'s Gaussian Process has no validation rows; the jackknife predictions of Actual by Predicted are its check.' },
      ],
      more: MORE,
    },
    'p:gaussproc:abp': {
      kicker: 'Gaussian Process', title: 'Actual by Predicted Plot',
      lead: 'The actual values against the jackknife predictions: each row predicted by the model fitted without it, the kernel (and normalize_y\'s mean and scale) held, which for a Gaussian process has the closed form y − [K⁻¹y]ᵢ/[K⁻¹]ᵢᵢ (Rasmussen and Williams 2006, eq. 5.12). Points far from the diagonal are rows the others do not predict. Rows beyond Rows to Fit are predicted by the whole model (diamonds).',
      more: MORE,
    },
    'p:gaussproc:report': {
      kicker: 'Gaussian Process', title: 'Model Report',
      lead: 'The fitted parameters and a functional ANOVA of the fitted surface f.',
      sections: [
        { heading: 'Theta', text: 'JMP\'s θₖ in exp(−Σ θₖ (xₖ − x′ₖ)²): scikit-learn\'s length scale ℓₖ gives θₖ = 1/(2ℓₖ²), in the units of the column. A large θ is a factor along which the response changes fast; θ near 0 a factor with no effect.' },
        { heading: 'Main Effect, Interaction, Total Sensitivity', text: 'With each factor uniform over its range in the rows fitted: Main Effect = Var E[f | xₖ] / Var f; the Interaction of a pair = (Var E[f | xₖ, xₗ] − the two main effects' + '’' + ' variances) / Var f; Total Sensitivity = the main effect plus its interactions, as JMP defines it (Sobol\'s total index would add the higher-order terms). For the Gaussian correlation the conditional means are integrated in closed form and by Gauss–Legendre quadrature, the total variance over scrambled Sobol points; for Matérn all of it by pick-freeze quasi-Monte Carlo.' },
        { heading: 'Mu, Sigma², Nugget, −2 LogLikelihood', text: 'Mu is the mean of Y (normalize_y; JMP estimates μ by generalized least squares, which moves it a little); Sigma² the process variance, the constant kernel times the variance of Y; the Nugget the white-noise level over Sigma² (a ridge on the correlation matrix). −2 LogLikelihood is on the scale of Y.' },
      ],
      more: MORE,
    },
    'p:gaussproc:marginal': {
      kicker: 'Gaussian Process', title: 'Marginal Model Plots',
      lead: 'For each factor, the prediction averaged over the other factors, each uniform over its range: the main effect whose variance the Model Report\'s Main Effect measures. The plots share one scale.',
      more: MORE,
    },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'gaussproc', label: 'Gaussian Process', menu: 'Analyze/Specialized Modeling', order: 90, info: 'p:gaussproc', topics: TOPICS,
    about: 'Gaussian process models of continuous responses over continuous factors, as JMP\'s Gaussian Process: the Gaussian correlation (a length scale per factor; JMP\'s θ = 1/(2ℓ²)) or Matérn, an optional nugget, maximum likelihood with optimizer restarts from the seed; actual by the jackknife predictions (in closed form), the Model Report with the functional ANOVA of the fitted surface (main effects, interactions, total sensitivities), −2 LogLikelihood, Mu, Sigma² and the nugget, marginal model plots, the Prediction Profiler with the process\'s standard deviation, and Save Prediction, Std Error and Jackknife Predicted Values. Beyond JMP: Matérn in place of its Cubic correlation.',
    uses: ['sklearn.gaussian_process.GaussianProcessRegressor', 'sklearn.gaussian_process.kernels (RBF, Matern, ConstantKernel, WhiteKernel)', 'scipy.linalg.cho_solve', 'scipy.special.erf', 'scipy.stats.qmc.Sobol', 'numpy.polynomial.legendre.leggauss'],
    launch: {
      lead: 'Choose one or more continuous responses and the continuous factors. A Gaussian process is fitted to each response by maximum likelihood (scikit-learn\'s GaussianProcessRegressor).',
      roles: ROLES,
      options: OPTIONS,
      validate: (spec) => {
        const o = spec.options || {};
        if (o.maxRows != null && !(Number.isInteger(o.maxRows) && o.maxRows >= 3)) return 'Rows to Fit is a whole number, 3 or more';
        if (o.restarts != null && !(Number.isInteger(o.restarts) && o.restarts >= 0 && o.restarts <= 50)) return 'Optimizer Restarts is a whole number from 0 to 50, or empty';
        if (o.seed != null && String(o.seed).trim() !== '' && !Number.isInteger(Number(o.seed))) return 'The Random Seed is a whole number';
        const ys = (spec.roles && spec.roles.y) || [], xs = (spec.roles && spec.roles.x) || [];
        if (ys.some((id) => xs.includes(id))) return 'A column cannot be both a Y and an X';
        return null;
      },
    },
    title: (spec, table) => {
      const ys = ((spec.roles && spec.roles.y) || []).map((id) => (table && table.col(id) ? table.col(id).name : null)).filter(Boolean);
      return ys.length === 1 ? `Gaussian Process of ${ys[0]}` : 'Gaussian Process';
    },
    triangle(ctx) {
      const ys = ctx.roles('y');
      return ys.length === 1 ? [...yItems(ctx, ys[0]), { separator: true }, ...globalItems(ctx)] : globalItems(ctx);
    },
    render,
  });

  /* ---- the example: a simulated computer experiment ------------------------------------------ */
  SM.io.addExample('borehole', {
    label: 'Borehole (40 runs): a computer experiment',
    about: 'Simulated: 40 runs of a Latin hypercube over the eight inputs of the borehole function (Worley 1987; Morris, Mitchell and Ylvisaker 1993), the water flow (m³/yr) through a borehole between two aquifers: rw the radius of the borehole (m, 0.05–0.15), r the radius of influence (m, 100–50000), Tu and Tl the transmissivities of the upper and lower aquifers (m²/yr, 63070–115600 and 63.1–116), Hu and Hl their potentiometric heads (m, 990–1110 and 700–820), L the length of the borehole (m, 1120–1680) and Kw its hydraulic conductivity (m/yr, 9855–12045). The flow is 2π Tu (Hu − Hl) / (ln(r/rw) (1 + 2 L Tu/(ln(r/rw) rw² Kw) + Tu/Tl)), computed without noise, as the deterministic computer experiments JMP\'s Gaussian Process is made for; log10 flow is its logarithm. rw matters most, then Hu, Hl and L; r, Tu, Tl and Kw hardly at all. For Gaussian Process (Analyze > Specialized Modeling).',
    make() {
      const r = SM.util.rng('gaussproc-borehole');
      const n = 40;
      const ranges = [['rw', 0.05, 0.15], ['r', 100, 50000], ['Tu', 63070, 115600], ['Hu', 990, 1110], ['Tl', 63.1, 116], ['Hl', 700, 820], ['L', 1120, 1680], ['Kw', 9855, 12045]];
      // a Latin hypercube: each factor's range cut into n strata, one run in each, the strata shuffled per factor
      const cols = ranges.map(([, lo, hi]) => {
        const perm = Array.from({ length: n }, (_, i) => i);
        for (let i = n - 1; i > 0; i--) { const j = Math.floor(r.u() * (i + 1)); [perm[i], perm[j]] = [perm[j], perm[i]]; }
        return perm.map((k) => lo + (hi - lo) * (k + r.u()) / n);
      });
      const sig = (v, d) => Number(v.toPrecision(d));
      const X = cols.map((c) => c.map((v) => sig(v, 5)));
      const flow = [];
      for (let i = 0; i < n; i++) {
        const [rw, rr, Tu, Hu, Tl, Hl, L, Kw] = X.map((c) => c[i]);
        const lr = Math.log(rr / rw);
        flow.push(2 * Math.PI * Tu * (Hu - Hl) / (lr * (1 + 2 * L * Tu / (lr * rw * rw * Kw) + Tu / Tl)));
      }
      return new SM.Table({ name: 'Borehole', source: 'simulated', columns: [
        ...ranges.map(([name], k) => ({ name, dataType: 'numeric', values: X[k] })),
        { name: 'flow', dataType: 'numeric', values: flow.map((v) => sig(v, 7)) },
        { name: 'log10 flow', dataType: 'numeric', values: flow.map((v) => sig(Math.log10(v), 7)) },
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
