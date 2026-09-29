/* ==========================================================================
   SMUI.HTML: WHAT THE PREDICTIVE PLATFORMS SHARE

   Partition, Bootstrap Forest, Boosted Tree, Neural, K Nearest Neighbors,
   Naive Bayes, Support Vector Machines, Gaussian Process and Model
   Screening share their launch roles and options and parts of their
   reports. The backend side is resources/py/smui/predictive.py
   (prepare(), report(), saved()).

     launch: { roles: [yRole, xRole, ...SM.predict.roles()],
               options: SM.predict.options() }
     const base = { y, x, ...SM.predict.payload(ctx) };  // weight, freq, validation, portion, seed, missing
     const r = await ctx.call('partition.fit', base);   // r.fit = predictive.report(P, fitted)
     SM.predict.measures(ctx, parent, r.fit);
     SM.predict.classification(ctx, parent, r.fit, scope);   // confusion, ROC, lift (options)
     SM.predict.actualByPredicted(ctx, parent, r.fit);
     SM.predict.contributions(ctx, parent, r.contributions);
     ...SM.predict.saveItems(ctx, 'partition.save', base, r.fit)   // red-triangle items

   The seed: the launch's Random Seed, or one drawn at the first run and
   kept with the report (so a redraw, Redo and a project give the same
   holdback and the same model).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el } = SM.util;

  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));

  /* ---- the graphs' matplotlib code ---------------------------------------------------
     Under each graph, Python that draws it with matplotlib from a CSV export of
     the table (the backend writes it: predictive.graph_codes and the platforms'
     own). A graph's code is a head (the table, the rows, the sets, the model
     fitted as the platform fits it) and the graph's own lines, joined as
     predictive.SEP joins parts: Save Python Script takes a head shared by
     several graphs once. */
  const SEP = '\n\n# ----\n';
  function graphCode(ctx, head, tail) {
    if (!tail) return null;
    return ctx.code(head ? `${head}${SEP}${tail}` : tail);
  }

  /* A graph with its code block right under it, as one item of a row. */
  function withCode(graph, code) {
    return code ? el('div', { class: 'sm-pred-plotcode', style: { display: 'flex', flexDirection: 'column', alignItems: 'flex-start', minWidth: '0', maxWidth: '100%' } }, graph, code) : graph;
  }

  /* A graph and its block: ctx.plot's arguments, and the head and tail of its code. */
  function plotWithCode(ctx, traces, layout, opts, head, tail) {
    return withCode(ctx.plot(traces, layout, opts), graphCode(ctx, head, tail));
  }

  /* The roles after Y and X. */
  function roles({ weight = true, freq = true, validation = true, by = true } = {}) {
    return [
      weight ? { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional: case weights', info: 'p:predict:weight', help: 'A case weight per row: a row of weight 2 counts twice as much in the fit as a row of weight 1. With a Freq column too, the two are multiplied. Rows with a missing, zero or negative weight are left out.' } : null,
      freq ? { key: 'freq', label: 'Freq', max: 1, numeric: true, hint: 'optional: row counts', info: 'p:predict:weight', help: 'How many observations each row stands for, as if it were repeated that many times: in the fit, in the measures of fit and in the confusion matrices. Rows with a missing, zero or negative count are left out.' } : null,
      validation ? { key: 'validation', label: 'Validation', max: 1, hint: 'optional: 0/1/2 or Training/Validation/Test', info: 'p:predict:validation', help: 'Which rows the model learns from: 0 or Training (fits the model), 1 or Validation (chooses its size, such as when to stop splitting or adding trees, and measures it), 2 or Test (kept out of both, an honest measure of the chosen model). Rows with no value are left out. Without a Validation column, Validation Portion holds rows back at random.' } : null,
      by ? { key: 'by', label: 'By', hint: 'optional', help: 'A separate model and report for each level of the By column (each combination of levels with several By columns). Rows with a missing By value are left out.' } : null,
    ].filter(Boolean);
  }

  /* The launch options: the validation portion, Informative Missing and the seed. */
  function options({ portion = 0, missing = true } = {}) {
    return [
      { key: 'portion', label: 'Validation Portion', type: 'number', value: portion, hint: 'a share of the rows held back for validation when there is no Validation column (0: none)', help: 'When there is no Validation column: the share of the rows, between 0 and 1, held back at random as validation rows (0.3 holds back 30%, rounded to whole rows), drawn from the Random Seed. 0 fits on every row, with no validation.' },
      { key: 'missing', label: 'Informative Missing', type: 'check', value: missing, hint: 'a missing value of a factor is informative: the mean plus a Missing column, or a level of its own', help: 'On: rows with a missing factor are kept and the missing value can carry information. A missing continuous value is replaced by the mean of the training rows and a 0/1 column that marks it is added; a missing level becomes a level of its own. Off: rows missing any factor are left out.' },
      { key: 'seed', label: 'Random Seed', type: 'text', value: '', hint: 'empty: a seed drawn now and kept with the report', help: 'The seed of every random draw: the validation holdback and the model\'s own draws (bootstrap samples, starting weights, folds). Empty: a seed is drawn at the first run and kept with the report, so Redo and a saved project give the same model; type a number to get the same model again in a new launch.' },
    ];
  }

  function seed(ctx) {
    const given = ctx.opt('seed', '');
    if (given !== '' && given != null && Number.isFinite(Number(given))) return Math.trunc(Number(given));
    let s = ctx.opt('seedDrawn', null);
    if (s == null) {
      s = 1 + Math.floor(Math.random() * 2147483646);
      ctx.set('seedDrawn', s, null, { rerun: false });
    }
    return s;
  }

  /* weight, freq, validation, portion, seed and missing for the backend. */
  function payload(ctx) {
    const one = (k) => { const c = ctx.roles(k)[0]; return c ? c.name : null; };
    const portion = Number(ctx.opt('portion', 0)) || 0;
    return { weight: one('weight'), freq: one('freq'), validation: one('validation'), portion, seed: seed(ctx), missing: ctx.opt('missing', true) ? 'informative' : 'drop' };
  }

  /* The Measures of Fit of predictive.report(): a row per set. */
  function measures(ctx, parent, fit, { title = 'Measures of Fit', key = 'measures' } = {}) {
    const ob = ctx.outline(title, { parent, key, info: 'p:predict:measures' });
    const cols = fit.measure_columns.filter((c) => c.key !== 'auc' || fit.measures.some((m) => m.auc != null));
    ob.add(ctx.rt({ columns: cols, rows: fit.measures }, { key, sortable: false }));
    const lines = [];
    if (fit.sets.length > 1) lines.push(`${fit.sets.map((s) => `${s} ${fit.n[s]} rows`).join(', ')}.`);
    if (fit.notes && fit.notes.length) lines.push(...fit.notes);
    if (lines.length) ob.add(ctx.note(lines.join(' ')));
    return ob;
  }

  /* Confusion matrices, ROC and lift curves of a categorical response, each
     shown when its option is on (keys confusion, roc, lift in scope). */
  function classification(ctx, parent, fit, scope = null, prefix = '') {
    if (fit.kind !== 'categorical') return;
    if (ctx.opt('confusion', true, scope)) confusion(ctx, parent, fit, prefix);
    if (ctx.opt('roc', false, scope)) rocCurves(ctx, parent, fit, prefix);
    if (ctx.opt('lift', false, scope)) liftCurves(ctx, parent, fit, prefix);
  }

  /* The red-triangle items that turn those on and off. */
  function classificationItems(ctx, fit, scope = null) {
    if (fit.kind !== 'categorical') return [];
    return [ctx.check('Confusion Matrix', 'confusion', scope, true), ctx.check('ROC Curve', 'roc', scope, false), ctx.check('Lift Curve', 'lift', scope, false)];
  }

  function confusion(ctx, parent, fit, prefix = '') {
    const ob = ctx.outline('Confusion Matrix', { parent, key: `${prefix}confusion`, info: 'p:predict:confusion' });
    const boxes = fit.confusion.map((cm) => {
      const cols = [{ key: 'actual', label: 'Actual', fmt: 'text' }, ...cm.levels.map((lv, j) => ({ key: `c${j}`, label: lv }))];
      const rows = cm.levels.map((lv, i) => ({ actual: lv, ...Object.fromEntries(cm.levels.map((_, j) => [`c${j}`, cm.matrix[i][j]])) }));
      const rates = cm.levels.map((lv, i) => { const tot = cm.matrix[i].reduce((a, b) => a + b, 0); return { actual: lv, ...Object.fromEntries(cm.levels.map((_, j) => [`c${j}`, tot ? cm.matrix[i][j] / tot : null])) }; });
      return el('div', { class: 'sm-pred-cm' },
        ctx.rt({ columns: cols, rows }, { caption: `${cm.set}: predicted count`, sortable: false, key: `${prefix}cm-${cm.set}` }),
        ctx.rt({ columns: cols.map((c) => (c.key === 'actual' ? c : { ...c, digits: 4 })), rows: rates }, { caption: `${cm.set}: predicted rate`, sortable: false, key: `${prefix}cmrate-${cm.set}` }));
    });
    ob.add(ctx.row(...boxes), ctx.note('Rows are the actual levels, columns the most likely level the model predicts.'));
    return ob;
  }

  function rocCurves(ctx, parent, fit, prefix = '') {
    const ob = ctx.outline('ROC Curve', { parent, key: `${prefix}roc`, info: 'p:predict:roc' });
    const muted = SM.util.themeColors().muted;
    const pc = fit.plots || {};
    const plots = fit.sets.map((set) => {
      const cur = fit.roc.filter((r) => r.set === set);
      const traces = cur.map((r, i) => ({ type: 'scatter', mode: 'lines', x: r.fpr, y: r.tpr, name: `${SM.report.plotlyText(r.level)} (${r.auc == null ? '.' : r.auc.toFixed(4)})`, line: { color: SM.util.PALETTE[i % SM.util.PALETTE.length], width: 1.8 } }));
      traces.push({ type: 'scatter', mode: 'lines', x: [0, 1], y: [0, 1], line: { color: muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false });
      return plotWithCode(ctx, traces, { showlegend: true, legend: { x: 0.35, y: 0.08 }, title: { text: set, font: { size: 12 } }, margin: { l: 50, r: 12, t: 28, b: 40 }, xaxis: { title: { text: '1 - Specificity' }, range: [0, 1] }, yaxis: { title: { text: 'Sensitivity' }, range: [0, 1.01] } }, { width: W(330), height: 320, title: `ROC ${set}`, select: false },
        pc.head_code, pc.roc && pc.roc[set]);
    });
    ob.add(ctx.row(...plots), ctx.rt({ columns: [{ key: 'set', label: 'Set', fmt: 'text' }, { key: 'level', label: 'Level', fmt: 'text' }, { key: 'auc', label: 'AUC' }], rows: fit.roc.map((r) => ({ set: r.set, level: r.level, auc: r.auc })) }, { key: `${prefix}auc`, sortable: false }),
      ctx.note('Each level against all the others, by its predicted probability; the AUC is the area under the curve (0.5: no better than chance).'));
    return ob;
  }

  function liftCurves(ctx, parent, fit, prefix = '') {
    const ob = ctx.outline('Lift Curve', { parent, key: `${prefix}lift`, info: 'p:predict:lift' });
    const muted = SM.util.themeColors().muted;
    const pc = fit.plots || {};
    const plots = fit.sets.map((set) => {
      const cur = fit.lift.filter((r) => r.set === set);
      const traces = cur.map((r, i) => ({ type: 'scatter', mode: 'lines', x: r.portion, y: r.lift, name: SM.report.plotlyText(r.level), line: { color: SM.util.PALETTE[i % SM.util.PALETTE.length], width: 1.8 } }));
      traces.push({ type: 'scatter', mode: 'lines', x: [0, 1], y: [1, 1], line: { color: muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false });
      return plotWithCode(ctx, traces, { showlegend: true, title: { text: set, font: { size: 12 } }, margin: { l: 50, r: 12, t: 28, b: 40 }, xaxis: { title: { text: 'Portion' }, range: [0, 1] }, yaxis: { title: { text: 'Lift' } } }, { width: W(330), height: 300, title: `Lift ${set}`, select: false },
        pc.head_code, pc.lift && pc.lift[set]);
    });
    ob.add(ctx.row(...plots), ctx.note('The rows taken in order of the level\'s predicted probability: the lift is the level\'s rate among them over its rate in the set.'));
    return ob;
  }

  /* Actual by Predicted of a continuous response, one plot per set, linked to the rows. */
  function actualByPredicted(ctx, parent, fit, { key = 'abp' } = {}) {
    if (fit.kind !== 'continuous' || !fit.residuals) return;
    const r = fit.residuals;
    const ob = ctx.outline('Actual by Predicted Plot', { parent, key, info: 'p:predict:measures' });
    const muted = SM.util.themeColors().muted;
    const pc = fit.plots || null;
    const later = pc || ctx.headless ? null : fromCall(ctx, fit);
    const plots = fit.sets.map((set) => {
      const k = ['Training', 'Validation', 'Test'].indexOf(set);
      const idx = r.set.map((s, i) => (s === k ? i : -1)).filter((i) => i >= 0);
      const xs = idx.map((i) => r.predicted[i]), ys = idx.map((i) => r.actual[i]);
      let lo = Infinity, hi = -Infinity;
      for (const v of [...xs, ...ys]) if (Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      const graph = ctx.plot([
        { type: 'scatter', mode: 'markers', x: xs, y: ys, rows: idx.map((i) => r.rows[i]), marker: { size: 5 }, name: set },
        { type: 'scatter', mode: 'lines', x: [lo, hi], y: [lo, hi], line: { color: muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false },
      ], { title: { text: set, font: { size: 12 } }, margin: { l: 56, r: 12, t: 28, b: 42 }, xaxis: { title: { text: 'Predicted' } }, yaxis: { title: { text: 'Actual' } } }, { width: W(320), height: 300, title: `Actual by predicted ${set}` });
      if (pc) return withCode(graph, graphCode(ctx, pc.head_code, pc.abp && pc.abp[set]));
      if (!later) return graph;
      // the block of a fit that came without its code, once its call's result is found
      const box = withCode(graph, el('span', { hidden: true }));
      later.then((res) => { const code = res && genregCode(res, set, k); if (code) box.lastChild.replaceWith(ctx.code(code)); else box.lastChild.remove(); });
      return box;
    });
    ob.add(ctx.row(...plots));
    return ob;
  }

  /* A fit of another platform that comes without its graphs' code: Fit
     Model's Generalized Regression hands over its rows, actual and
     predicted values (smui-p-fitmodel.js). Its block is made from the code
     of the call those arrays came from (fitmodel.genreg), found in the
     report's cache by the very arrays; that code fits the chosen model and
     ends its fit with e, every row's linear predictor. The call has
     returned already, so the block is in place when the report is done. */
  function fromCall(ctx, fit) {
    const want = fit.residuals && fit.residuals.predicted;
    const cache = ctx.report && ctx.report.cache;
    if (!want || !cache || typeof cache.entries !== 'function') return null;
    const calls = [...cache.entries()].filter(([k]) => String(k).startsWith('fitmodel.genreg\u0001')).map(([, p]) => Promise.resolve(p).catch(() => null));
    if (!calls.length) return null;
    return Promise.all(calls).then((rs) => rs.find((x) => x && x.diag && x.diag.predicted === want) || null);
  }

  /* Generalized Regression's Actual by Predicted Plot as code: its own code
     up to e (the linear predictor of the chosen model), then the prediction
     (the mean: e, or exp(e) for the Poisson's log link) against the actual
     values of the set's rows (train, valid and sets as that code names them). */
  function genregCode(res, set, k) {
    const lines = String(res.code || '').split('\n');
    const read = lines.findIndex((l) => /^df = pd\.read_csv\(/.test(l));
    const at = lines.findIndex((l) => /^e = /.test(l));
    if (read < 0 || at < read || !res.model || k < 0) return null;
    const head = [...lines.slice(0, read), 'import matplotlib.pyplot as plt', ...lines.slice(read, at + 1)];
    const log = res.model.distribution === 'Poisson';
    const muted = '#786b5d', base = '#2f6690';
    const tail = [
      log ? 'mu = np.exp(e)   # the prediction: the mean at the linear predictor (log link)' : 'mu = e   # the prediction (identity link)',
      `m = ${['train', 'valid', 'sets == 2'][k]}   # the ${set.toLowerCase()} rows`,
      'fig, ax = plt.subplots(figsize=(3.2, 3), layout="constrained")',
      `ax.scatter(mu[m], y[m], s=14, color="${base}")`,
      'v = np.r_[mu[m], y[m]]',
      'v = v[np.isfinite(v)]',
      `ax.plot([v.min(), v.max()], [v.min(), v.max()], color="${muted}", linewidth=1, linestyle=":")   # actual = predicted`,
      'ax.set_xlabel("Predicted")', 'ax.set_ylabel("Actual")', `ax.set_title(${JSON.stringify(`Actual by predicted ${set}`)})`, 'plt.show()'];
    return `${head.join('\n')}${SEP}${tail.join('\n')}`;
  }

  /* Column Contributions: predictive.contributions() as a table and bars.
     head: the code the bars' code (c.plot_code) follows, the model's. */
  function contributions(ctx, parent, c, { title = 'Column Contributions', key = 'contrib', note = null, head = null } = {}) {
    const ob = ctx.outline(title, { parent, key, info: 'p:predict:contrib' });
    const rows = c.rows;
    const bars = plotWithCode(ctx, [{ type: 'bar', orientation: 'h', y: rows.map((r) => SM.report.plotlyText(r.column)), x: rows.map((r) => r.portion), marker: { color: SM.report.BAR }, hovertemplate: '%{y}: %{x:.4f}<extra></extra>' }],
      { margin: { l: 110, r: 12, t: 6, b: 34 }, xaxis: { title: { text: 'Portion' }, range: [0, 1] }, yaxis: { autorange: 'reversed' } }, { width: W(340), height: Math.max(120, 24 * rows.length + 50), title: title, select: false },
      head || c.head_code, c.plot_code);
    const extra = (c.extra || []).map((lab, i) => ({ key: `extra${i}`, label: lab }));
    ob.add(ctx.row(ctx.rt({ columns: [{ key: 'column', label: 'Term', fmt: 'text' }, ...extra, { key: 'value', label: c.label }, { key: 'portion', label: 'Portion' }], rows }, { key: 'contrib' }), bars));
    if (note) ob.add(ctx.note(note));
    return ob;
  }

  /* Save Columns: fn is the platform's backend function returning
     predictive.saved(); payload what it needs to find the model. */
  function saveItems(ctx, fn, payload, fit) {
    const from = { notes: `from ${ctx.report.title}` };
    const go = async (what) => {
      try {
        const r = await ctx.call(fn, payload);
        if (fit.kind === 'continuous') {
          if (what === 'residuals') ctx.saveColumn(`Residual ${r.name.replace(/^Predicted /, '')}`, { rows: r.rows, values: r.residuals }, from);
          else ctx.saveColumn(r.name, { rows: r.rows, values: r.values }, from);
        } else {
          r.names.forEach((nm, j) => ctx.saveColumn(nm, { rows: r.rows, values: r.prob.map((p) => p[j]) }, from));
          ctx.saveColumn(r.most_name, { rows: r.rows, values: r.most_likely }, { ...from, dataType: 'character', modelingType: r.ordinal ? 'ordinal' : 'nominal', valueOrder: r.levels });
        }
      } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
    };
    const items = fit.kind === 'continuous'
      ? [{ label: 'Save Predicteds', action: () => go('pred') }, { label: 'Save Residuals', action: () => go('residuals') }]
      : [{ label: 'Save Predicteds', action: () => go('prob') }];
    return [{ label: 'Save Columns', submenu: () => items }];
  }

  SM.predict = Object.freeze({ roles, options, payload, seed, measures, classification, classificationItems, confusion, rocCurves, liftCurves, actualByPredicted, contributions, saveItems,
    SEP, graphCode, withCode, plotWithCode });

  SM.info.add({
    'p:predict:validation': {
      kicker: 'Predictive modeling', title: 'Validation',
      lead: 'A model that fits its training rows well may predict new rows badly. The rows can be split: the model learns from the training rows, the validation rows choose among models (how big a tree, how many trees or layers), and test rows, kept out of both, show how well the chosen model predicts.',
      sections: [{ choices: [['Validation column', 'a column with 0 (Training), 1 (Validation) and 2 (Test), or those words; rows with no value are left out'], ['Validation Portion', 'with no Validation column, that share of the rows is held back for validation, drawn at random from the seed'], ['Random Seed', 'the seed of every random draw: the holdback and the model\'s own; empty draws one at the first run and keeps it with the report']] }],
    },
    'p:predict:weight': { kicker: 'Predictive modeling', title: 'Weight and Freq', lead: 'Freq: how many times a row counts (confusion matrices count by it). Weight: a case weight in the fit. A row with a missing or non-positive weight or frequency is left out.' },
    'p:predict:measures': {
      kicker: 'Predictive modeling', title: 'Measures of Fit',
      lead: 'How well the model predicts, for each set of rows. A training value much better than the validation value means the model fits noise.',
      sections: [
        { heading: 'Continuous response', choices: [['RSquare', '1 - SSE/SST, SST about the set\'s own mean'], ['RASE', 'the root average squared error'], ['Mean Abs Dev', 'the mean absolute error'], ['-LogLikelihood', 'of a normal error with variance SSE/N']] },
        { heading: 'Categorical response', choices: [['Entropy RSquare', '1 - LL/LL0: the log-likelihood against that of the training shares of the levels'], ['Generalized RSquare', 'Nagelkerke\'s version, which reaches 1'], ['Mean -Log p', 'the average of -log of the probability of the actual level'], ['RASE, Mean Abs Dev', 'of 1 - the probability of the actual level'], ['Misclassification Rate', 'the share of rows whose most likely level is not the actual one'], ['AUC', 'for two levels, the area under the ROC curve']] },
      ],
    },
    'p:predict:confusion': { kicker: 'Predictive modeling', title: 'Confusion Matrix', lead: 'For each set, the rows counted by their actual level (rows) and the most likely level the model gives them (columns); the rates divide each row by its total.' },
    'p:predict:roc': { kicker: 'Predictive modeling', title: 'ROC Curve', lead: 'For each level against the others: as the cut-off on its predicted probability falls, the share of its rows caught (sensitivity) against the share of the other rows caught (1 - specificity). The area under the curve is the chance that a random row of the level scores higher than a random other row.' },
    'p:predict:lift': { kicker: 'Predictive modeling', title: 'Lift Curve', lead: 'The rows sorted by the predicted probability of a level, highest first: at each portion of the rows, how many times more common the level is among them than in the whole set.' },
    'p:predict:contrib': { kicker: 'Predictive modeling', title: 'Column Contributions', lead: 'How much each factor contributes to the model, as a share of the total. A categorical factor\'s level columns are added together.' },
  });
}(typeof self !== 'undefined' ? self : this));
