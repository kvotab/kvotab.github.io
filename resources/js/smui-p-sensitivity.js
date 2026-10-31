/* ==========================================================================
   SMUI.HTML: ANALYZE > SCREENING > SENSITIVITY ANALYSIS

   Which inputs of a Monte Carlo sample an output depends on, from the sample
   as it is (resources/py/smui/sensitivity.py): a row per realisation, the
   inputs drawn for it (X) and the outputs it gave (Y). Nothing is run again.

     Measures                   Pearson, Spearman, SRC, PCC, SRRC, PRCC and
                                S1 of each input, the R² of the regression
                                and of the regression on ranks, and a chart
                                of one of them
     Distribution-Based         EASI, δ, PAWN, mutual information and the
     Measures                   discrepancy (from the red triangle: δ's
                                bootstrap takes seconds)
     Regional Sensitivity       the realisations above a threshold against
                                the rest: each input's two distributions and
                                the Kolmogorov-Smirnov distance between them
     Scatterplots               the output against each input, linked to rows

   They are the measures of Kompartment's What drove it, computed as there.
   With one Y the outlines are under the report's own; with several, each Y
   has its outline. The options apply to every Y.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const J = (v) => JSON.stringify(v);
  const MORE = { label: 'Sensitivity Analysis', id: 'help-p-sensitivity' };
  const W = (w) => Math.max(240, Math.min(w, (root.innerWidth || 1200) - 110));
  const MOST_PLOTS = 24;      // scatterplots and distributions drawn, at most
  // the measures a chart can show: the key, and the column of the code's table
  const CHART = [['prcc', 'PRCC'], ['srrc', 'SRRC'], ['spearman', 'Spearman'], ['pearson', 'Pearson'], ['pcc', 'PCC'], ['src', 'SRC'], ['s1', 'S1']];
  const SPLITS = [['mean', 'Mean'], ['median', 'Median'], ['quantile', 'Quantile…'], ['value', 'Value…']];

  const scatterType = (n) => (n > 4000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter');
  const markerSize = (n) => (n > 2000 ? 3 : n > 600 ? 4 : 5.5);
  const intOr = (v, d, lo, hi) => { const x = Math.round(Number(v)); return Number.isFinite(x) && x >= lo && x <= hi ? x : d; };

  /* The realisations at or below a threshold: not the selection's orange, readable on both themes. */
  const other = () => (SM.util.themeColors().dark ? '#5fb36b' : '#3a7d44');

  /* What every call of the report sends. */
  function base(ctx, y) {
    return { y: y.name, x: ctx.names('x'), log_y: !!ctx.opt('logY', false) };
  }

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx) {
    const ys = ctx.roles('y');
    const multi = ys.length > 1;
    for (const y of ys) {
      const parent = multi ? ctx.outline(y.name, { key: `out:${y.id}` }) : ctx.top;
      await output(ctx, y, parent);
    }
  }

  async function output(ctx, y, parent) {
    const b = base(ctx, y);
    const wants = { measures: ctx.opt('measures', true), scatter: ctx.opt('scatter', true) && !ctx.headless };
    let m = null;
    if (wants.measures || wants.scatter) {
      try { m = await ctx.call('sensitivity.measures', b); } catch (e) { parent.add(ctx.error(e)); return; }
      if (m.error) { parent.add(ctx.warn(`${y.name}: ${m.error}`)); return; }
    }
    if (wants.measures) measures(ctx, parent, y, m);
    if (ctx.opt('distribution', false)) await distribution(ctx, parent, y, b);
    if (ctx.opt('regional', false)) await regional(ctx, parent, y, b);
    if (wants.scatter) scatterplots(ctx, parent, y, m);
  }

  const constants = (rows) => rows.filter((r) => r.constant).map((r) => r.input);
  const onRows = (r) => `${fmt(r.n)} realisation${r.n === 1 ? '' : 's'} with the output and every input present${r.log_y ? ' and the output above zero' : ''}${r.left_out ? `; left out: ${r.left_out}` : ''}.`;

  /* ---- Measures: correlations, regressions, S1 ---------------------------------------------- */
  function measures(ctx, parent, y, m) {
    const ob = ctx.outline('Measures', { parent, key: `measures:${y.id}`, info: 'p:sens:measures' });
    const cols = [
      { key: 'input', label: 'Input', fmt: 'text' },
      { key: 'pearson', label: 'Pearson', digits: 4 }, { key: 'pearson_p', label: 'Prob>|r|', fmt: 'p', hidden: true },
      { key: 'spearman', label: 'Spearman', digits: 4 }, { key: 'spearman_p', label: 'Prob>|ρ|', fmt: 'p', hidden: true },
      { key: 'src', label: 'SRC', digits: 4 }, { key: 'pcc', label: 'PCC', digits: 4 },
      { key: 'srrc', label: 'SRRC', digits: 4 }, { key: 'prcc', label: 'PRCC', digits: 4 },
      { key: 's1', label: 'S1', digits: 4 },
    ];
    ob.add(ctx.rt({ columns: cols, rows: m.rows }, { key: `measures-${y.id}` }));
    ob.add(ctx.kv([['R²', m.r2], ['R² on Ranks', m.r2_rank], ['Realisations', m.n, 'int']]));
    const notes = [onRows(m)];
    if (m.log_y) notes.push(`On the logarithm of ${y.name} (Log Output): Pearson, SRC, PCC and S1 read log ${y.name}; Spearman, SRRC and PRCC depend on order alone and are as on ${y.name}.`);
    const flat = constants(m.rows);
    if (flat.length) notes.push(`${flat.join(', ')} ${flat.length === 1 ? 'has' : 'have'} one value in every realisation analysed, and no measures.`);
    ob.add(ctx.note(notes.join(' ')));
    if (Number.isFinite(m.r2) && m.r2 < 0.7) {
      ob.add(ctx.warn(`The regression explains ${fmt(m.r2, { digits: 2 })} of the variance of ${m.log_y ? 'log ' : ''}${y.name} (R²): SRC and PCC describe a linear model that fits it poorly.${Number.isFinite(m.r2_rank) && m.r2_rank >= 0.7 ? ` On ranks it explains ${fmt(m.r2_rank, { digits: 2 })}: SRRC and PRCC say more.` : ' S1 and the distribution-based measures assume no shape.'}`));
    } else if (Number.isFinite(m.r2_rank) && m.r2_rank < 0.7) {
      ob.add(ctx.warn(`The regression on ranks explains ${fmt(m.r2_rank, { digits: 2 })} of the variance of the ranks of ${y.name}: the output is not monotone in the inputs, or they act together, and SRRC and PRCC say less than S1 and the distribution-based measures.`));
    }
    ob.add(ctx.code(m.code));
    chart(ctx, ob, y, m);
  }

  /* The measure a chart shows unless one is chosen: PRCC, or S1 when the
     regression on ranks fits poorly (an output that is not monotone in its
     inputs, whose PRCCs say little). */
  const chartOf = (ctx, m) => ctx.opt('chart', null) || (m && m.r2_rank < 0.7 ? 's1' : 'prcc');

  /* One measure of each input as bars, the largest at the top. */
  function chart(ctx, ob, y, m) {
    if (ctx.headless) return;
    const key = chartOf(ctx, m);
    const label = (CHART.find(([k]) => k === key) || CHART[0])[1];
    const rows = m.rows.filter((r) => Number.isFinite(r[key])).sort((a, b) => Math.abs(a[key]) - Math.abs(b[key]));
    if (!rows.length) return;
    const title = `${label} of each input on ${y.name}`;
    const traces = [{ type: 'bar', orientation: 'h', y: rows.map((r) => T(r.input)), x: rows.map((r) => r[key]), marker: { color: SM.report.BASE },
      hovertemplate: `%{y}: ${label} %{x:.4f}<extra></extra>` }];
    const layout = { xaxis: { title: { text: label }, range: key === 's1' ? [0, 1] : [-1, 1], zeroline: true }, yaxis: { automargin: true, type: 'category' }, margin: { l: 12, r: 16, t: 8, b: 44 }, bargap: 0.25 };
    const tail = [
      'import matplotlib.pyplot as plt',
      '',
      `t = table.dropna(subset=[${J(label)}])`,
      `t = t.iloc[np.argsort(np.abs(t[${J(label)}].to_numpy()), kind="stable")]   # the largest at the top`,
      'fig, ax = plt.subplots(figsize=(5.2, 0.7 + 0.26 * len(t)), layout="constrained")',
      `ax.barh(t["Input"], t[${J(label)}], color="#2f6690")`,
      `ax.set_xlim(${key === 's1' ? '0, 1' : '-1, 1'})`,
      `ax.set_xlabel(${J(label)})`,
      `ax.set_title(${J(title)}, wrap=True)`,
      'plt.show()',
    ].join('\n');
    const plot = SM.predict.plotWithCode(ctx, traces, layout, { width: W(520), height: 70 + 26 * rows.length, title, select: false }, m.code, tail);
    const sub = ctx.outline(`${label} Chart`, { parent: ob, key: `chart:${y.id}`, info: 'p:sens:measures',
      menu: () => CHART.map(([k, l]) => ({ label: l, checked: key === k, action: () => ctx.set('chart', k) })) });
    sub.add(plot);
  }

  /* ---- Distribution-based measures ------------------------------------------------------------ */
  async function distribution(ctx, parent, y, b) {
    const ob = ctx.outline('Distribution-Based Measures', { parent, key: `dist:${y.id}`, info: 'p:sens:distribution' });
    let d;
    try {
      d = await ctx.call('sensitivity.distribution', { ...b, boots: intOr(ctx.opt('boots', 100), 100, 10, 2000), seed: intOr(ctx.opt('seed', 1), 1, 0, 2 ** 31 - 1) });
    } catch (e) { ob.add(ctx.error(e)); return; }
    if (d.error) { ob.add(ctx.warn(`${y.name}: ${d.error}`)); return; }
    const cols = [
      { key: 'input', label: 'Input', fmt: 'text' },
      { key: 'easi', label: 'S1 (EASI)', digits: 4 },
      { key: 'delta', label: 'δ', digits: 4 }, { key: 'delta_low', label: 'δ Lower', digits: 4 }, { key: 'delta_high', label: 'δ Upper', digits: 4 },
      { key: 'pawn', label: 'PAWN', digits: 4 }, { key: 'pawn_max', label: 'PAWN Max', digits: 4, hidden: true },
      { key: 'mi_above', label: 'MI Above Chance', digits: 4 }, { key: 'mi', label: 'MI', digits: 4, hidden: true }, { key: 'mi_bound', label: 'MI Chance', digits: 4, hidden: true },
      { key: 'discrepancy', label: 'Discrepancy', digits: 4, hidden: !d.discrepancy },
    ];
    ob.add(ctx.rt({ columns: cols, rows: d.rows }, { key: `dist-${y.id}` }));
    const notes = [`${fmt(d.n)} realisations${d.left_out ? ` (left out: ${d.left_out})` : ''}.`,
      `δ is read on the normal scores of ${y.name} and mutual information on the ranks of both, which leaves each as it is (they depend on order alone) and lets their estimators resolve an output over decades; S1 (EASI) reads ${b.log_y ? `log ${y.name}` : y.name}.`,
      `δ's interval is from ${fmt(d.boots)} bootstrap resamples and the chance level of mutual information from ${fmt(d.boots)} shuffles of the output, each input's drawn from the seed ${d.seed} and its place (Settings…).`];
    if (!d.discrepancy) notes.push('The discrepancy is not computed: it costs the square of the realisations for every input, more than this sample allows here.');
    const flat = constants(d.rows);
    if (flat.length) notes.push(`${flat.join(', ')} ${flat.length === 1 ? 'is' : 'are'} constant: no measures.`);
    ob.add(ctx.note(notes.join(' ')), ctx.code(d.code));
  }

  /* ---- Regional sensitivity: Monte Carlo filtering ------------------------------------------------ */
  async function regional(ctx, parent, y, b) {
    // the output's own threshold (its outline's red triangle), else the report's
    const split = ctx.opt('split', 'mean', y.id);
    const ob = ctx.outline('Regional Sensitivity', { parent, key: `regional:${y.id}`, info: 'p:sens:regional',
      menu: () => splitItems(ctx, y.id) });
    let g;
    try { g = await ctx.call('sensitivity.regional', { ...b, split, value: ctx.opt('splitValue', null, y.id), seed: intOr(ctx.opt('seed', 1), 1, 0, 2 ** 31 - 1) }); } catch (e) { ob.add(ctx.error(e)); return; }
    if (g.error) { ob.add(ctx.warn(`${y.name}: ${g.error}`)); return; }
    ob.add(ctx.rt({ columns: [{ key: 'input', label: 'Input', fmt: 'text' }, { key: 'ks', label: 'KS', digits: 4 }, { key: 'p', label: 'Prob > KS', fmt: 'p' }], rows: g.rows }, { key: `regional-${y.id}` }));
    ob.add(ctx.kv([['Threshold', g.threshold], ['Above', g.above, 'int'], ['At or Below', g.below, 'int'], ['Dummy Inputs\' KS', g.dummy_mean], ['… Std Dev', g.dummy_sd]]));
    ob.add(ctx.note(`The ${fmt(g.above)} realisations with ${y.name} above ${g.how} (${fmt(g.threshold, { sig: 6 })}) against the ${fmt(g.below)} at or below it. KS is the greatest distance between an input's cumulative distributions in the two groups, with the two-sample test's p-value. Ten dummy inputs, uniform draws ${y.name} does not depend on (from the seed ${g.seed}), are ${fmt(g.dummy_mean, { digits: 3 })} ± ${fmt(g.dummy_sd, { digits: 3 })} apart: an input near that does not tell the groups apart.${g.left_out ? ` Left out: ${g.left_out}.` : ''}`),
    ctx.code(g.code));
    if (ctx.headless) return;
    const xs = ctx.roles('x');
    const shown = xs.slice(0, MOST_PLOTS);
    const plots = shown.map((c, j) => {
      const part = (rows) => rows.map((r) => c.values[r]).filter((v) => Number.isFinite(v)).sort((a, z) => a - z);
      const cdf = (s, name, color) => ({ type: 'scatter', mode: 'lines', x: s, y: s.map((_, i) => (i + 1) / s.length), line: { shape: 'hv', color, width: 1.5 }, name,
        hovertemplate: `${T(c.name)} %{x:.5g}: %{y:.3f}<extra>${name}</extra>`, showlegend: j === 0 });
      return ctx.plot([cdf(part(g.above_rows), 'above', SM.report.BASE), cdf(part(g.below_rows), 'at or below', other())],
        { xaxis: { title: { text: T(c.name) } }, yaxis: { title: { text: 'Cumulative probability' }, range: [0, 1.02] }, margin: { l: 52, r: 8, t: j === 0 ? 24 : 8, b: 42 },
          legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' } },
        { width: W(xs.length > 3 ? 250 : 300), height: 220, title: `${y.name} above and at or below the threshold: ${c.name}`, select: false });
    });
    const sub = ctx.outline('Distributions', { parent: ob, key: `cdf:${y.id}`, info: 'p:sens:regional' });
    sub.add(ctx.row(...plots));
    if (xs.length > shown.length) sub.add(ctx.note(`The first ${MOST_PLOTS} inputs of ${xs.length}.`));
    sub.add(ctx.code(g.plots_code));
  }

  /* The threshold's choices: for one output (scope, its column's id), or the
     report's for every output (scope null: ctx.set drops the outputs' own). */
  function splitItems(ctx, scope) {
    const split = ctx.opt('split', 'mean', scope);
    return SPLITS.map(([k, l]) => ({
      label: k === 'mean' && ctx.opt('logY', false) ? 'Geometric Mean' : l, checked: split === k,
      action: () => (k === 'quantile' || k === 'value' ? splitDialog(ctx, k, scope) : ctx.set('split', k, scope)),
    }));
  }

  async function splitDialog(ctx, kind, scope) {
    const q = kind === 'quantile';
    const now = ctx.opt('split', 'mean', scope) === kind ? ctx.opt('splitValue', null, scope) : null;
    const v = await SM.ui.form({
      title: q ? 'Regional Threshold: Quantile' : 'Regional Threshold: Value',
      lead: `${q ? 'The realisations above this quantile of the output (0.9: the highest tenth) against the rest' : 'The realisations whose output is above this value, in the output\'s own units, against the rest'}${scope ? ', for this output' : ', for every output'}.`,
      fields: [{ key: 'value', label: q ? 'Probability (between 0 and 1)' : 'Threshold', type: 'number', value: now ?? (q ? 0.9 : null),
        help: q ? 'A probability between 0 and 1: 0.5 is the median, 0.9 puts the highest tenth of the realisations above the threshold.' : 'A value of the output, in its own units (with Log Output too): realisations above it are one group, the others the second.' }],
      validate: (x) => (!Number.isFinite(x.value) ? 'A number, please' : q && !(x.value > 0 && x.value < 1) ? 'A probability between 0 and 1' : null),
    });
    if (!v) return;
    ctx.set('splitValue', v.value, scope, { rerun: false });
    ctx.set('split', kind, scope);
  }

  /* ---- Scatterplots: the output against each input ----------------------------------------------- */
  function scatterplots(ctx, parent, y, m) {
    const ob = ctx.outline('Scatterplots', { parent, key: `scatter:${y.id}`, info: 'p:sens:scatter' });
    const xs = ctx.roles('x');
    const shown = xs.slice(0, MOST_PLOTS);
    const n = m.index.length;
    const ys = m.index.map((r) => y.values[r]);
    const plots = shown.map((c) => ctx.plot([{ type: scatterType(n), mode: 'markers', x: m.index.map((r) => c.values[r]), y: ys, rows: m.index, marker: { size: markerSize(n) },
      hovertemplate: `${T(c.name)} %{x:.5g}<br>${T(y.name)} %{y:.5g}<extra></extra>` }],
    { xaxis: { title: { text: T(c.name) } }, yaxis: { title: { text: T(y.name) }, type: m.log_y ? 'log' : 'linear' }, margin: { l: 58, r: 8, t: 8, b: 42 } },
    { width: W(xs.length > 3 ? 250 : 300), height: 220, title: `${y.name} by ${c.name}` }));
    ob.add(ctx.row(...plots));
    const notes = [`Each point a realisation; drag over points to select their rows.${m.log_y ? ` ${y.name} on a logarithmic axis (Log Output).` : ''}`];
    if (xs.length > shown.length) notes.push(`The first ${MOST_PLOTS} inputs of ${xs.length}.`);
    ob.add(ctx.note(notes.join(' ')), ctx.code(m.plots_code));
  }

  /* ======================================================================
     MENUS
     ====================================================================== */
  function items(ctx) {
    return [
      ctx.check('Measures', 'measures', null, true),
      ctx.check('Distribution-Based Measures', 'distribution', null, false),
      ctx.check('Regional Sensitivity', 'regional', null, false),
      ctx.check('Scatterplots', 'scatter', null, true),
      { separator: true },
      ctx.check('Log Output', 'logY', null, false),
      { label: 'Chart', submenu: () => [{ label: 'By the Fit (PRCC, or S1)', checked: ctx.opt('chart', null) == null, action: () => ctx.set('chart', null) },
        ...CHART.map(([k, l]) => ({ label: l, checked: ctx.opt('chart', null) === k, action: () => ctx.set('chart', k) }))] },
      { label: 'Regional Threshold', submenu: () => splitItems(ctx, null) },
      { label: 'Settings…', action: () => settingsDialog(ctx) },
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
  }

  async function settingsDialog(ctx) {
    const v = await SM.ui.form({
      title: 'Sensitivity Settings',
      lead: 'The random draws of the distribution-based measures and the regional analysis.',
      fields: [
        { key: 'boots', label: 'Bootstrap Resamples (and shuffles)', type: 'number', value: intOr(ctx.opt('boots', 100), 100, 10, 2000), help: HELP.boots },
        { key: 'seed', label: 'Random Seed', type: 'number', value: intOr(ctx.opt('seed', 1), 1, 0, 2 ** 31 - 1), help: HELP.seed },
      ],
      validate: (x) => (!(Number.isInteger(x.boots) && x.boots >= 10 && x.boots <= 2000) ? 'Bootstrap Resamples is a whole number from 10 to 2000'
        : !(Number.isInteger(x.seed) && x.seed >= 0) ? 'The seed is a whole number, 0 or more' : null),
    });
    if (!v) return;
    ctx.set('boots', v.boots, null, { rerun: false });
    ctx.set('seed', v.seed, null);
  }

  /* ======================================================================
     THE LAUNCH'S ROLES AND OPTIONS, with what each is for (the (i))
     ====================================================================== */
  const HELP = {
    logY: 'Read the output on logarithms: Pearson, SRC, PCC, S1 and EASI then measure log y, and the regional analysis splits at the geometric mean. For an output over several decades (a dose), whose largest realisations otherwise decide the values-based measures. The rank measures, δ, PAWN, mutual information and the discrepancy depend on order alone and do not change. Realisations whose output is not above zero have no logarithm and are left out.',
    distribution: 'Also compute the distribution-based measures: EASI\'s first-order index, Borgonovo\'s δ, PAWN, mutual information and the discrepancy. δ\'s bootstrap takes a few seconds per input on a large sample, which is why they are not computed unless asked (also the red triangle).',
    boots: 'The bootstrap resamples behind δ\'s bias adjustment and interval, and the shuffles of the output behind the chance level of mutual information (100, as Kompartment\'s What drove it). More is steadier and slower.',
    seed: 'The seed of those draws and of the regional analysis\'s dummy inputs: each input\'s draws are numpy\'s default_rng([seed, k]), k its place, so an input\'s numbers do not depend on the inputs after it, and the code under each result gives the same numbers.',
  };
  const ROLES = [
    { key: 'y', label: 'Y, Output', min: 1, numeric: true, types: ['continuous'], hint: 'required: continuous, each analysed on its own',
      help: 'The outputs of the sample: a column per output, a row per realisation. Each output is analysed on its own, against every input (with several, each has an outline).' },
    { key: 'x', label: 'X, Input', min: 1, numeric: true, types: ['continuous', 'ordinal'], hint: 'required: the inputs sampled',
      help: 'The inputs drawn for each realisation, in their own units (a log-uniform one need not be logged first: the rank measures, δ, PAWN, mutual information and the discrepancy do not depend on the scale). Realisations missing an input or the output are left out.' },
    { key: 'by', label: 'By', hint: 'optional', help: 'A separate analysis for each level of the By column (each combination of levels, with several). Rows with a missing By value are left out.' },
  ];
  const OPTIONS = [
    { key: 'logY', label: 'Log Output', type: 'check', value: false, hint: 'read the outputs on logarithms (an output over decades)', help: HELP.logY },
    { key: 'distribution', label: 'Distribution-Based Measures', type: 'check', value: false, hint: 'EASI, δ, PAWN, mutual information and the discrepancy (seconds)', help: HELP.distribution },
  ];

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:sensitivity': {
      kicker: 'Analyze > Screening', title: 'Sensitivity Analysis',
      lead: 'Which inputs of a Monte Carlo sample an output depends on, from the sample itself: a row per realisation, the inputs drawn for it (X) and the outputs it gave (Y). Nothing is run again. The measures are those of Kompartment\'s What drove it, computed the same way.',
      sections: [
        { heading: 'Roles', choices: [['Y, Output', 'One or more continuous outputs, each analysed on its own.'], ['X, Input', 'The inputs sampled.'], ['By', 'A separate analysis for each level.']] },
        { heading: 'Options', choices: [...OPTIONS.map((o) => [o.label, o.help]), ['Settings…', `${HELP.boots} ${HELP.seed}`]] },
        { heading: 'Which measure', list: [
          'Spearman and PRCC find a monotone relation of any curvature, the usual first look at a sample. Pearson, SRC and PCC find a straight line, and say little when R² is low.',
          'SRC and SRRC are shares of the variance when the inputs are independent: SRC² sums to R². PCC and PRCC take the other inputs out of both sides, and stay large for an input that matters little to the spread but is not confounded.',
          'S1, the first-order index, assumes no shape: an output that rises and falls with an input has a correlation near zero and a large S1.',
          'δ, PAWN and mutual information say how far an input moves the output\'s whole distribution, not only its mean; the regional analysis which inputs lead to the highest (or lowest) outputs.',
          'The scatterplots show what no single number does: a threshold, two branches, a peak.',
        ] },
        { heading: 'Realisations', text: 'Those with the output and every input present (with Log Output, the output above zero), at least 10; 20 for the distribution-based measures. A constant input has no measures.' },
      ],
      more: MORE,
    },
    'p:sens:measures': {
      kicker: 'Sensitivity Analysis', title: 'Measures',
      lead: 'For each input, measures that need nothing but the sample: two correlations, the coefficients of the regression of the output on every input, on the values and on ranks, and a first-order index.',
      sections: [
        { choices: [
          ['Pearson', 'The correlation of the input and the output: a straight line.'],
          ['Spearman', 'The correlation of their ranks: any monotone relation.'],
          ['SRC', 'The standardized regression coefficient: the input\'s coefficient in the least-squares regression of the output on every input, all standardized. With independent inputs SRC² is the input\'s share of the variance, the shares summing to R².'],
          ['PCC', 'The partial correlation coefficient: the correlation of the input and the output once the other inputs\' linear effects are taken out of both, from the same regression: β/√(β² + (1 − R²)(R⁻¹)ₖₖ), R the inputs\' correlation matrix.'],
          ['SRRC, PRCC', 'SRC and PCC on the ranks of every column: for a monotone relation that is not a straight line.'],
          ['S1', 'The first-order index Var(E[y | x]) / Var(y), the share of the variance the input explains alone, of any shape: the realisations sorted by the input and cut into √n bins of equal count (4 to 50), the variance of the bins\' means over the variance of y, less the bins/n that the noise in those means adds; within 0 and 1.'],
          ['R², R² on Ranks', 'How well the two regressions fit. Below about 0.7 the coefficients describe a model that does not fit the output, and the report says so.'],
          ['Prob>|r|, Prob>|ρ|', 'The p-values of the two correlations (scipy\'s pearsonr and spearmanr): right-click the table, Columns.'],
        ] },
        { heading: 'Chart', text: 'One measure of each input as bars, the largest at the top: PRCC, or S1 where the regression on ranks fits poorly (R² on ranks below 0.7, an output that is not monotone in its inputs); another from the chart\'s red triangle or the report\'s Chart.' },
      ],
      more: MORE,
    },
    'p:sens:distribution': {
      kicker: 'Sensitivity Analysis', title: 'Distribution-Based Measures',
      lead: 'Measures that compare distributions rather than fit a model, each of an input on its own. δ, mutual information, PAWN and the discrepancy depend only on the order of the values, so a logarithm changes none of them.',
      sections: [
        { choices: [
          ['S1 (EASI)', 'The first-order index from the sample\'s spectrum (Plischke 2010): the outputs in the order of the input, folded so they are periodic in it, and the share of their power in the first four harmonics, less the bias a random sample leaves (Tissot and Prieur 2012). For an input that does nothing it is near 0, and can be a little below.'],
          ['δ', 'Borgonovo\'s moment-independent measure: half the expected area between the output\'s density and its density given the input, 0 when the input changes nothing and at most 1. Estimated with the input cut into classes by its ranks (Plischke, Borgonovo and Smith 2013) and kernel density estimates, on the output\'s normal scores; less the bias a bootstrap measures, with an interval (δ Lower, δ Upper).'],
          ['PAWN', 'The median, over ten slices of the input of equal count, of the Kolmogorov-Smirnov distance between the output\'s distribution in the slice and overall (Pianosi and Wagener 2015, 2018); PAWN Max the greatest.'],
          ['MI Above Chance', 'Mutual information in bits, from histograms of the ranks with √n bins a side, less its 95th percentile with the output shuffled: what chance alone gives. MI and MI Chance are the two (right-click, Columns).'],
          ['Discrepancy', 'The input\'s share, over every input, of the discrepancy of the points (input, output) on their ranks (Puy, Roy and Saltelli 2022): an input the output does not depend on spreads them evenly. It costs the square of the realisations: past inputs × realisations² of 4×10⁸ it is not computed.'],
        ] },
        { heading: 'Random draws', text: 'δ\'s bootstrap and the shuffles come from the seed (Settings…), each input\'s from numpy\'s default_rng([seed, k]), k its place: the numbers do not move when an input is added after it, and the code under the table gives them again.' },
      ],
      more: MORE,
    },
    'p:sens:regional': {
      kicker: 'Sensitivity Analysis', title: 'Regional Sensitivity',
      lead: 'Monte Carlo filtering (Hornberger and Spear 1981): the realisations whose output is above a threshold against the rest, and for each input how differently it is distributed in the two groups. Which inputs lead to the highest outputs.',
      sections: [
        { heading: 'KS', text: 'The Kolmogorov-Smirnov distance between the input\'s cumulative distributions in the two groups: 0 when they are the same, 1 when they do not overlap; Prob > KS the two-sample test\'s p-value (scipy\'s ks_2samp).' },
        { heading: 'Dummy inputs', text: 'Ten uniform draws the output does not depend on, split the same way: their mean ± standard deviation is how far apart chance alone puts the two groups. An input near that does not tell them apart.' },
        { heading: 'Threshold', text: 'From the outline\'s red triangle for that output alone (outputs on different scales want their own value), or from the report\'s Regional Threshold for every output, their own set aside.', choices: [['Mean', 'The mean of the output (the geometric mean with Log Output); the default.'], ['Median', 'Half the realisations in each group.'], ['Quantile…', 'A probability: 0.9 puts the highest tenth above the threshold.'], ['Value…', 'A value of the output in its own units, a dose limit say.']] },
        { heading: 'Distributions', text: 'Each input\'s two cumulative distributions, the realisations above the threshold in blue, the others in green: the further apart, the more the input decides which group a realisation falls in.' },
      ],
      more: MORE,
    },
    'p:sens:scatter': {
      kicker: 'Sensitivity Analysis', title: 'Scatterplots',
      lead: 'The output against each input, a point per realisation, linked to the rows: drag over points to select their rows. With Log Output the output\'s axis is logarithmic. A pattern no single measure describes (a threshold, two branches, a peak) shows here.',
      more: MORE,
    },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'sensitivity', label: 'Sensitivity Analysis', menu: 'Analyze/Screening', order: 50, info: 'p:sensitivity', topics: TOPICS,
    about: 'Which inputs of a Monte Carlo sample an output depends on, from the sample itself, as Kompartment\'s What drove it computes it: Pearson\'s and Spearman\'s correlations, the standardized regression and partial correlation coefficients (SRC, PCC) and their rank forms (SRRC, PRCC) with the R² of each regression, a first-order index S1 by binning; EASI\'s first-order index, Borgonovo\'s δ with a bootstrap interval, PAWN, mutual information above chance and the discrepancy; regional sensitivity (Monte Carlo filtering) with the Kolmogorov-Smirnov distances, their p-values and dummy inputs; scatterplots linked to the rows, and Log Output for an output over decades. Not in JMP.',
    uses: ['numpy, scipy.linalg.cho_solve (SRC, PCC and their rank forms)', 'scipy.stats: pearsonr, spearmanr, rankdata, ks_2samp, norm', 'scipy.stats.qmc.discrepancy', 'numpy.fft (EASI; the kernel density estimates of δ)', 'scipy.linalg.solve_banded (the density\'s spline)'],
    launch: {
      lead: 'Choose the outputs of a Monte Carlo sample and the inputs drawn for it, a row per realisation. Each output is analysed against every input, from the sample as it is.',
      roles: ROLES,
      options: OPTIONS,
      validate: (spec) => {
        const ys = (spec.roles && spec.roles.y) || [], xs = (spec.roles && spec.roles.x) || [];
        if (ys.some((id) => xs.includes(id))) return 'A column cannot be both an output and an input';
        return null;
      },
    },
    title: (spec, table) => {
      const ys = ((spec.roles && spec.roles.y) || []).map((id) => (table && table.col(id) ? table.col(id).name : null)).filter(Boolean);
      return ys.length === 1 ? `Sensitivity Analysis of ${ys[0]}` : 'Sensitivity Analysis';
    },
    triangle: items,
    render,
  });

  /* ---- the example: a simulated Monte Carlo sample ------------------------------------------------- */
  SM.io.addExample('sensitivity', {
    label: 'Monte Carlo sample (1000 realisations)',
    about: 'Simulated: 1000 realisations of six independent inputs and two outputs, for Sensitivity Analysis (Analyze > Screening). x1, x2 and x3 are uniform on (−π, π); Kd is log-uniform from 0.0001 to 0.1 and v from 0.1 to 10; d is uniform on (0, 1) and nothing depends on it. Ishigami is the Ishigami function, sin x1 + 7 sin² x2 + 0.1 x3⁴ sin x1 (Ishigami and Homma 1990), whose first-order indices are 0.314, 0.442 and 0 for x1, x2 and x3: x2 matters most, and no correlation sees it, for the output rises and falls with it. Dose is 10⁻⁶ v^1.5 / (1 + 1000 Kd), over five decades: monotone in Kd and v, the case for Spearman, PRCC and Log Output.',
    make() {
      const r = SM.util.rng('sensitivity-sample');
      const n = 1000;
      const sig = (v, d) => Number(v.toPrecision(d));
      const u = (lo, hi) => lo + (hi - lo) * r.u();
      const cols = { x1: [], x2: [], x3: [], Kd: [], v: [], d: [], Ishigami: [], Dose: [] };
      for (let i = 0; i < n; i++) {
        const x1 = sig(u(-Math.PI, Math.PI), 7), x2 = sig(u(-Math.PI, Math.PI), 7), x3 = sig(u(-Math.PI, Math.PI), 7);
        const kd = sig(10 ** u(-4, -1), 7), v = sig(10 ** u(-1, 1), 7), d = sig(r.u(), 7);
        cols.x1.push(x1); cols.x2.push(x2); cols.x3.push(x3); cols.Kd.push(kd); cols.v.push(v); cols.d.push(d);
        cols.Ishigami.push(sig(Math.sin(x1) + 7 * Math.sin(x2) ** 2 + 0.1 * x3 ** 4 * Math.sin(x1), 9));
        cols.Dose.push(sig(1e-6 * v ** 1.5 / (1 + 1000 * kd), 7));
      }
      return new SM.Table({ name: 'Monte Carlo sample', source: 'simulated', columns: Object.entries(cols).map(([name, values]) => ({ name, dataType: 'numeric', values })) });
    },
  });
}(typeof self !== 'undefined' ? self : this));
