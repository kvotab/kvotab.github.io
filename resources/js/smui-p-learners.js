/* ==========================================================================
   SMUI.HTML: ANALYZE > PREDICTIVE MODELING > K NEAREST NEIGHBORS, NAIVE
   BAYES AND SUPPORT VECTOR MACHINES

   Three of JMP Pro's predictive platforms on scikit-learn. They share the
   roles, options and report blocks of smui-predict.js (the sets, the
   Measures of Fit, confusion matrices, ROC and lift curves, Save Columns)
   and the Prediction Profiler of smui-profiler.js:

     K Nearest Neighbors      every K from 1 to K: the misclassification
                              rate (or RASE) of each set in a table and a
                              plot, the best K marked; the chosen K's fit;
                              Save Predicteds and Save Near Neighbor Rows
     Naive Bayes              Fit Details, confusion, ROC and lift, the
                              class parameters on request, the profiler
     Support Vector Machines  Model Summary, the tuning design of Cost and
                              Gamma, Fit Details, confusion, ROC and lift
                              or actual by predicted, the decision boundary
                              over two continuous factors (linked to the
                              rows), the profiler

   The numbers are resources/py/smui/learners.py's (knn.*, naivebayes.*,
   svm.*). The report's seed goes to everything random.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const MENU = 'Analyze/Predictive Modeling';
  const SETS = ['Training', 'Validation', 'Test'];
  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));
  /* A two-column list (ctx.kv) with long labels scrolls by itself on a
     narrow screen, as report tables do (smui.css). */
  const wide = (node) => el('div', { class: 'sm-lrn-scroll' }, node);

  /* The colours of the levels (and of the sets): blue, aqua and red first,
     which tell apart as a set of three under colour vision deficiencies,
     with the page's selection orange left out; every level has its own
     marker too, so that colour is never alone. */
  function hues() {
    return SM.util.themeColors().dark
      ? ['#3987e5', '#199e70', '#e66767', '#9085e9', '#c98500', '#d55181', '#6fb33f']
      : ['#2a78d6', '#1baf7a', '#e34948', '#4a3aa7', '#b07c00', '#d55181', '#3d8b1f'];
  }
  const SYMBOLS = ['circle', 'square', 'diamond', 'triangle-up', 'triangle-down', 'star', 'hexagon', 'pentagon'];
  const hueOf = (i) => { const h = hues(); return h[i % h.length]; };
  const symbolOf = (i) => SYMBOLS[i % SYMBOLS.length];
  /* A one-hue ramp for magnitudes (a surface of predictions, a criterion):
     light to dark on the light theme, dark to light on the dark one. */
  function ramp() {
    const steps = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
    const s = SM.util.themeColors().dark ? steps.slice().reverse() : steps;
    return s.map((c, i) => [i / (s.length - 1), c]);
  }

  const yName = (spec, table) => { const id = ((spec.roles || {}).y || [])[0]; const c = id && table ? table.col(id) : null; return c ? c.name : null; };
  const titled = (label) => (spec, table) => { const y = yName(spec, table); return y ? `${label} for ${y}` : label; };
  const xRole = { key: 'x', label: 'X, Factor', min: 1, hint: 'required: one or more' };
  const base = (ctx) => ({ y: ctx.name('y'), x: ctx.names('x'), ...SM.predict.payload(ctx) });
  const MORE = (id, label) => ({ label, id: `help-p-${id}` });

  /* A note that follows a long fit's 'smui:progress <what> <done> <total>'
     lines; returns the function that takes it away. */
  function progressNote(ctx, what, label) {
    if (ctx.headless) return () => {};
    const note = el('p', { class: 'sm-ob-note sm-lrn-progress', role: 'status', text: `${label}…` });
    ctx.container.append(note);
    const off = SM.engine.on('progress', (p) => {
      if (!p || p.what !== what) return;
      const text = `${label}${ctx.byLabel ? ` (${ctx.byLabel})` : ''}: ${p.done} of ${p.total}…`;
      note.textContent = text;
      ctx.report.noteEl.textContent = text;
    });
    return () => { off(); note.remove(); };
  }

  const profilerNote = (extra) => `Drag the red dashed line of a factor, click in its plot, or type its value.${extra ? ` ${extra}` : ''}`;

  /* What each field of the launch dialogs and the forms is for: the (i). */
  const HELP = {
    knnY: 'The column to predict: continuous (the mean response of the K nearest training rows) or nominal or ordinal (the level most of them have, its probability the share of their votes with a prior of one vote spread over the levels).',
    knnX: 'The factors the distance between rows is measured on: a continuous one standardized by the training rows\' mean and standard deviation, a categorical one as a 0/1 column per level, not scaled, so that a different level adds 2 to the squared distance (as √2 standard deviations of a continuous factor would).',
    k: 'The largest K fitted, from 1 to 1000 (10): every K from 1 up to it is fitted, and the best is the one with the smallest misclassification rate (RASE for a continuous Y) on the validation rows, or on the training rows, each left out of its own neighbours, when there are none. At most the training rows less one are used.',
    kPick: 'The K whose fit the report shows under Model Selection instead of the best one; the Measures of Fit and Save Columns follow it. Select K ▸ Best K goes back to the best.',
    standardize: 'On (the default): each continuous factor is centred and divided by its standard deviation over the training rows before the distances are measured, so that a factor in large units does not outweigh the others. Off: the factors as they are, when their units are comparable and their spread should count.',
    distance: 'Off (the default): each of the K neighbours has one vote. On: each vote is weighted by 1/distance, so that nearer rows count more (a neighbour at distance 0 takes all the weight, as scikit-learn\'s weights="distance"); a level\'s probability is then its share of the weights as K votes, with the prior of one vote. Beyond JMP.',
    nbY: 'The nominal or ordinal column whose levels the rows are classified into; every row gets a probability of each level (the order of an ordinal response is not used).',
    nbX: 'The factors, taken as independent within each level of Y: a continuous one by a normal density per level, a categorical one by its smoothed shares of levels per level.',
    nbMissing: 'On (the default): rows missing a factor are kept, the missing value is left out of its row\'s product, and that it is missing counts as a factor of its own (Missing values, above). Off: rows missing any factor are left out.',
    alpha: 'The count added to every level of a categorical factor within every level of Y (CategoricalNB\'s alpha, 1: Laplace smoothing), so that a combination the training rows lack does not give a probability of 0. A larger α pulls the shares toward equal ones.',
    varSmoothing: 'The share of the largest variance of a continuous factor that is added to every variance (GaussianNB\'s var_smoothing, 1e-9), so that no variance is 0. A larger share flattens the normal densities.',
    svmY: 'The column to predict: continuous (support vector regression, SVR) or nominal or ordinal (a support vector classifier, SVC, with Platt\'s probabilities; the order of an ordinal response is not used).',
    svmX: 'The factors, standardized by the training rows\' mean and standard deviation (a categorical one as a 0/1 column per level, not scaled): the kernel works on the distances between rows in them.',
    kernel: 'Radial Basis Function (the default): exp(−γ‖x − x′‖²), which lets the boundary (or the prediction) bend around groups of rows. Linear: a flat boundary, or a linear prediction, with Cost alone to set.',
    cost: 'What each training error costs against a wide, simple margin, above 0 (1): a large Cost follows the training rows closely and can overfit, a small one gives a smoother model. With Tuning Design on, the design chooses it instead.',
    gamma: 'How far a training row\'s influence reaches in the radial basis function exp(−γ‖x − x′‖²): a large Gamma gives a wiggly boundary that can overfit, a small one a smooth boundary. Empty: 1 over the number of columns of X (the 0/1 level columns counted). Not used by the Linear kernel; with Tuning Design on, the design chooses it.',
    tune: 'Fits a design of Cost (and Gamma) values, judges each by the misclassification rate or RASE of the validation rows (of 5-fold crossvalidation of the training rows when there are none), and keeps the best: the Cost and Gamma given are then not used. It takes a while on many rows.',
    points: 'The number of points of the tuning design, from 2 to 200 (20): with the radial basis function about that many pairs of Cost (0.1 to 1000) and Gamma (1/100 to 10 times its default), crossed evenly on the log scale; with the Linear kernel that many Costs from 0.01 to 100.',
    costForm: 'What each training error costs against a wide, simple margin, above 0: a large Cost follows the training rows closely and can overfit, a small one gives a smoother model. OK turns the tuning design off, so that this Cost and Gamma are the ones fitted.',
    gammaForm: 'How far a training row\'s influence reaches in the radial basis function exp(−γ‖x − x′‖²): a large Gamma gives a wiggly boundary that can overfit, a small one a smooth boundary. Empty: 1 over the number of columns of X (the 0/1 level columns counted). Not used by the Linear kernel.',
  };

  /* ======================================================================
     K NEAREST NEIGHBORS
     ====================================================================== */
  const kOf = (ctx) => { const k = Number(ctx.opt('k', 10)); return Number.isInteger(k) && k >= 1 ? k : 10; };
  // Standardize and Distance Weights go only when they are not the defaults, so that a report made before them keeps its calls
  const knnBase = (ctx) => ({ ...base(ctx), k: kOf(ctx), ...(ctx.opt('standardize', true) ? {} : { standardize: false }), ...(ctx.opt('distance', false) ? { weights: 'distance' } : {}) });
  // the key the engine keeps the report's model under (Score Rows): the report and its By group
  const keepOf = (ctx) => `${ctx.report.id}|${ctx.byLabel || ''}`;

  async function knnRender(ctx) {
    ctx.lrn = null;
    const b = knnBase(ctx);
    const r = await ctx.call('knn.fit', { ...b, chosen: ctx.opt('knnK', null), keep: keepOf(ctx) });
    if (r.error) { ctx.container.append(ctx.warn(r.error)); return; }
    ctx.lrn = { r, b: { ...b, chosen: r.chosen } };
    if (r.notes && r.notes.length) ctx.container.append(ctx.note(r.notes.join(' ')));
    if (ctx.opt('knnSelection', true)) knnSelection(ctx, r);
    const cat = r.kind === 'categorical';
    const ob = ctx.outline('Chosen Model', { key: 'knnfit', info: 'p:knn:fit', menu: () => knnKItems(ctx, r) });
    ob.add(ctx.kv([['K', r.chosen, 'int'], ['Best K', r.best, 'int'], ['Training Rows', r.n_train, 'int'],
      ['Distances', `${r.standardize ? 'standardized' : 'as they are'}${r.weights === 'distance' ? ', neighbours weighted by 1/distance' : ''}`, 'text']]));
    const mo = SM.predict.measures(ctx, ob, r.fit);
    if (r.cv && r.cv.measures) mo.add(ctx.rt({ columns: r.fit.measure_columns.filter((c) => c.key !== 'auc' || r.cv.measures.auc != null), rows: [r.cv.measures] }, { key: 'knncv', sortable: false, caption: `Crossvalidation: each row predicted from its ${r.chosen} nearest rows of the other folds (${r.folds} folds of the Validation column)` }));
    mo.add(ctx.note(`${r.chosen === r.best ? 'The best K' : `K = ${r.chosen}, chosen (the best is ${r.best})`}. A training row is predicted from its ${r.chosen} nearest other training rows, so its measures are those of leaving the row out; ${cat ? `a level's probability is its share of the ${r.chosen} votes${r.weights === 'distance' ? ' (each weighted by 1/distance)' : ''} with a prior of 1/${r.fit.levels.length} (one vote spread over the levels), so that none is 0 or 1, and a tied vote goes to one of the tied levels at random, from the report's seed (as JMP breaks ties)` : `the prediction is the ${r.weights === 'distance' ? 'distance-weighted ' : ''}mean response of the neighbours`}.`));
    await SM.predict.classification(ctx, ob, r.fit, null, '', { save: { fn: 'knn.save', payload: ctx.lrn.b } });
    if (cat && ctx.opt('mosaic', false)) mosaicOutline(ctx, ob, r);
    SM.predict.actualByPredicted(ctx, ob, r.fit);
    if (ctx.opt('profiler', false) && !ctx.headless) {
      await SM.profiler.render(ctx, ctx.container, { sources: [{ fn: 'knn.profile', payload: ctx.lrn.b }], option: 'profiler',
        note: profilerNote(`The prediction at a setting comes from its ${r.chosen} nearest training rows, so it moves in steps. (Not in JMP's K Nearest Neighbors.)`) });
    }
  }

  function knnSelection(ctx, r) {
    const cat = r.kind === 'categorical';
    const crit = cat ? 'Misclassification Rate' : 'RASE';
    const rows = r.path.rows;
    const muted = SM.util.themeColors().muted;
    const ob = ctx.outline('Model Selection', { key: 'knnsel', info: 'p:knn:selection', menu: () => [...knnKItems(ctx, r), { separator: true }, { label: 'Remove', action: () => ctx.set('knnSelection', false) }] });
    const tbl = ctx.rt(r.path, {
      key: 'knnsel', sortable: false, onRow: (row) => ctx.set('knnK', row.k === r.best ? null : row.k),
      cellClass: (row, c) => [row.k === r.chosen ? 'sm-lrn-chosen' : '', c.key === 'k' && row.k === r.best ? 'sm-lrn-best' : ''].filter(Boolean).join(' '),
    });
    const series = [...r.fit.sets.map((s) => [s, SETS.indexOf(s)]), ...(r.folds ? [['Crossvalidation', 'cv']] : [])];
    const traces = series.map(([s, k], i) => {
      const key = cat ? `rate${k}` : `rase${k}`;
      return { type: 'scatter', mode: 'lines+markers', x: rows.map((q) => q.k), y: rows.map((q) => q[key]), name: s,
        line: { color: hueOf(i), width: 2, dash: ['solid', 'dash', 'dot', 'dashdot'][i] }, marker: { color: hueOf(i), size: 8, symbol: symbolOf(i) },
        hovertemplate: `${s}: K = %{x}, ${crit} %{y:.4f}<extra></extra>` };
    });
    const shapes = [{ type: 'line', xref: 'x', yref: 'paper', x0: r.best, x1: r.best, y0: 0, y1: 1, line: { color: muted, width: 1.2, dash: 'dot' } }];
    const ann = [{ x: r.best, y: 1, xref: 'x', yref: 'paper', xanchor: 'left', yanchor: 'top', xshift: 3, text: `best K = ${r.best}`, showarrow: false, font: { size: 10, color: muted } }];
    if (r.chosen !== r.best) shapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: r.chosen, x1: r.chosen, y0: 0, y1: 1, line: { color: SM.util.themeColors().text, width: 1.2 } });
    const plot = ctx.plot(traces, {
      showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, margin: { l: 58, r: 12, t: 30, b: 42 },
      xaxis: { title: { text: 'K' }, dtick: r.k <= 20 ? 1 : undefined, range: [0.5, r.k + 0.5] }, yaxis: { title: { text: crit }, rangemode: 'tozero' }, shapes, annotations: ann,
    }, { width: W(430), height: 300, title: `${crit} by K`, select: false,
      onDraw: (gd) => gd.on('plotly_click', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt && Number.isInteger(pt.x)) ctx.set('knnK', pt.x === r.best ? null : pt.x); }) });
    const scaled = !r.standardize ? 'the factors as they are (Standardize off)' : r.scaled.length ? `${r.scaled.join(', ')} standardized by the training rows' mean and standard deviation` : 'no continuous factor to standardize';
    const pc = r.fit.plots || {};
    ob.add(ctx.row(tbl, SM.predict.withCode(plot, SM.predict.graphCode(ctx, pc.head_code, pc.selection))),
      ctx.note(`Every K from 1 to ${r.k}: each row is predicted from its K nearest training rows by Euclidean distance on the factors (${scaled}; a level of a categorical factor is a 0/1 column as it is, so a different level adds 2 to the squared distance)${r.weights === 'distance' ? ', each neighbour weighted by 1/distance' : ''}. A training row is not its own neighbour${r.folds ? `; Crossvalidation: each row from its neighbours in the other ${r.folds - 1} folds of the Validation column` : ''}. The best K (${r.best}, marked) has the smallest ${crit.toLowerCase()} on the ${r.by.toLowerCase()} rows (of equal ones the smallest K)${r.chosen !== r.best ? `; K = ${r.chosen} is shown below` : ''}. Click a line of the table or a point of the graph to see another K.`),
      ctx.code(r.code));
  }

  /* The Mosaic Plot of actual by called: a bar per actual level, as wide as its share of the set's rows, cut by the
     shares of the levels its rows are called; each part linked to its rows. */
  function mosaicOutline(ctx, parent, r) {
    const D = r.decided;
    const levels = r.fit.levels;
    const ob = ctx.outline('Mosaic Plot', { parent, key: 'knnmosaic', info: 'p:knn:mosaic', menu: () => [{ label: 'Remove', action: () => ctx.set('mosaic', false) }] });
    const pc = r.fit.plots || {};
    const plots = r.fit.sets.map((set) => {
      const k = SETS.indexOf(set);
      const L = levels.length;
      const cell = Array.from({ length: L }, () => Array.from({ length: L }, () => []));
      for (let i = 0; i < D.rows.length; i++) if (D.set[i] === k) cell[D.actual[i]][D.pred[i]].push(D.rows[i]);
      const tot = cell.reduce((a, row) => a + row.reduce((b, c) => b + c.length, 0), 0) || 1;
      const width = cell.map((row) => row.reduce((b, c) => b + c.length, 0) / tot);
      const left = width.map((_, i) => width.slice(0, i).reduce((a, b) => a + b, 0));
      const traces = levels.map((lv, j) => ({
        type: 'bar', name: T(lv), x: levels.map((_, a) => left[a] + width[a] / 2), width: width.map((w) => w * 0.98),
        y: levels.map((_, a) => { const n = cell[a].reduce((b, c) => b + c.length, 0); return n ? cell[a][j].length / n : 0; }),
        base: levels.map((_, a) => { const n = cell[a].reduce((b, c) => b + c.length, 0); let s = 0; for (let q = 0; q < j; q++) s += n ? cell[a][q].length / n : 0; return s; }),
        rows: levels.map((_, a) => cell[a][j]), marker: { color: hueOf(j) }, hovertemplate: `actual %{customdata}: called ${T(lv)} %{y:.3f}<extra></extra>`, customdata: levels.map(T),
      }));
      return SM.predict.withCode(ctx.plot(traces, { barmode: 'overlay', showlegend: true, legend: { x: 1.02, y: 1, xanchor: 'left' }, margin: { l: 50, r: 10, t: 28, b: 44 }, title: { text: set, font: { size: 12 } },
        xaxis: { title: { text: 'Actual' }, range: [0, 1], tickvals: left.map((l, a) => l + width[a] / 2), ticktext: levels.map(T) }, yaxis: { title: { text: 'Called' }, range: [0, 1] } },
      { width: W(360), height: 300, title: `Mosaic ${set}` }), SM.predict.graphCode(ctx, pc.head_code, pc.mosaic && pc.mosaic[set]));
    });
    ob.add(ctx.row(...plots), ctx.note('Each bar is an actual level, as wide as its share of the set\'s rows, cut by the shares of the levels its rows are called (the K chosen; a tie at random). Click or drag over a part to select its rows.'));
  }

  function knnKItems(ctx, r) {
    const cur = ctx.opt('knnK', null);
    const pick = async () => {
      const v = await SM.ui.form({ title: 'Select K', fields: [{ key: 'k', label: `K (1 to ${r.k})`, type: 'number', value: r.chosen, help: HELP.kPick }], validate: (x) => (Number.isInteger(x.k) && x.k >= 1 && x.k <= r.k ? null : `K is a whole number from 1 to ${r.k}`) });
      if (v) ctx.set('knnK', v.k === r.best ? null : v.k);
    };
    const each = r.k <= 30 ? Array.from({ length: r.k }, (_, i) => ({ label: `K = ${i + 1}`, checked: cur === i + 1, action: () => ctx.set('knnK', i + 1) })) : [{ label: 'Other K…', action: pick }];
    return [{ label: 'Select K', submenu: () => [{ label: `Best K (${r.best})`, checked: cur == null, action: () => ctx.set('knnK', null) }, { separator: true }, ...each] }];
  }

  async function knnNeighbors(ctx, payload) {
    try {
      const r = await ctx.call('knn.neighbors', payload);
      const from = ctx.report.title;
      r.names.forEach((nm, j) => ctx.saveColumn(nm, { rows: r.rows, values: r.near[j] }, { notes: `the row number of neighbour ${j + 1}: the ${j === 0 ? 'nearest' : `${j + 1}th nearest`} training row (a training row is not its own), from ${from}` }));
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  async function kDialog(ctx) {
    const v = await SM.ui.form({ title: 'Number of Neighbors', info: 'p:knn', fields: [{ key: 'k', label: 'Number of Neighbors, K (every K up to it is fitted)', type: 'number', value: kOf(ctx), help: HELP.k }], validate: (x) => (Number.isInteger(x.k) && x.k >= 1 && x.k <= 1000 ? null : 'K is a whole number from 1 to 1000') });
    if (v) { ctx.set('knnK', null, null, { rerun: false }); ctx.set('k', v.k); }
  }

  /* Score Rows (K Nearest Neighbors and Support Vector Machines, which have no formula): the model as this report
     fitted it (the engine keeps it) on the rows of an open table: this one's rows added since, or every row of
     another table with the same columns. The predictions go to that table as columns. */
  async function scoreRows(ctx, fn, s) {
    const app = SM.app;
    const tables = (app && app.tables) || [ctx.table];
    const v = await SM.ui.form({ title: 'Score Rows', info: 'p:learners:score', fields: [
      { key: 't', label: 'The table to score', type: 'select', value: ctx.table.id, choices: tables.map((t) => [t.id, t.name]), help: 'An open table: this report\'s own (its rows added since the report fitted, or all its rows), or another with the columns the model was fitted to, found by name. The model is the report\'s as it was fitted: not fitted again to the rows scored.' },
      { key: 'which', label: 'Rows', type: 'select', value: 'new', choices: [['new', 'Rows without a prediction yet'], ['all', 'Every row']], help: 'Rows without a prediction yet: the rows whose prediction column (Predicted, or Prob[] of the first level) is empty or missing, such as rows added after the report fitted; in another table without those columns, every row. Every row: all of them, into new columns.' },
    ] });
    if (!v) return;
    const target = tables.find((t) => t.id === v.t) || ctx.table;
    const r0 = s.r;
    const names = r0.kind === 'categorical' ? r0.fit.levels.map((l) => `Prob[${l}]`) : [`Predicted ${ctx.name('y')}`];
    let rows = null;
    const first = target.columns.find((c) => c.name === names[0]);
    if (v.which === 'new' && first) {
      rows = [];
      for (let i = 0; i < target.nrows; i++) { const x = first.values[i]; if (x == null || x === '' || Number.isNaN(x)) rows.push(i); }
      if (!rows.length) { SM.ui.toast(`Every row of ${target.name} has a prediction in ${first.name}`); return; }
    }
    try {
      const r = await SM.engine.call(fn, { ...s.b, keep: keepOf(ctx), source: ctx.table.id, target_rows: rows }, target);
      if (r.note) SM.ui.toast(r.note);
      writeScores(ctx, target, r, !!(v.which === 'new' && first));
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  /* The scores into a table: into its prediction columns when they are there (the rows scored only), else new ones. */
  function writeScores(ctx, t, r, into) {
    const from = `scored by ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''} (the model as it fitted)`;
    const cols = r.prob ? r.names.map((nm, j) => [nm, r.prob.map((p) => p[j]), 'numeric']) : [[r.name, r.values, 'numeric']];
    if (r.prob) cols.push([r.most_name, r.most_likely, 'character']);
    if (SM.app && SM.app.record) SM.app.record(t, 'Score Rows');
    for (const [name, values, type] of cols) {
      const c = into ? t.columns.find((x) => x.name === name) : null;
      if (c) {
        const next = c.values.slice();
        r.rows.forEach((row, k) => { next[row] = values[k] == null ? (c.isNumeric ? NaN : null) : values[k]; });
        t.setValues(c.id, next);
      } else {
        const full = new Array(t.nrows).fill(type === 'numeric' ? NaN : null);
        r.rows.forEach((row, k) => { full[row] = values[k] == null ? full[row] : values[k]; });
        t.addColumn({ name, dataType: type, values: full, notes: from, ...(type === 'character' && r.levels ? { modelingType: r.ordinal ? 'ordinal' : 'nominal', valueOrder: r.levels } : {}) });
      }
    }
    SM.ui.toast(`Scored ${r.rows.length} rows of ${t.name}`);
  }

  function knnTriangle(ctx) {
    const s = ctx.lrn;
    const items = [ctx.check('Model Selection', 'knnSelection', null, true)];
    if (s) items.push(...SM.predict.classificationItems(ctx, s.r.fit));
    if (s && s.r.kind === 'categorical') items.push(ctx.check('Mosaic Plot', 'mosaic', null, false));
    items.push(ctx.check('Profiler', 'profiler', null, false));
    if (s) items.push(...knnKItems(ctx, s.r));
    items.push({ label: 'Number of Neighbors…', action: () => kDialog(ctx) },
      ctx.check('Standardize', 'standardize', null, true), ctx.check('Distance Weights', 'distance', null, false));
    if (s) {
      const save = SM.predict.saveItems(ctx, 'knn.save', s.b, s.r.fit)[0].submenu();
      save.push({ label: 'Save Near Neighbor Rows', action: () => knnNeighbors(ctx, s.b) }, { label: 'Score Rows…', action: () => scoreRows(ctx, 'knn.score', s) });
      items.push({ separator: true }, { label: 'Save Columns', submenu: () => save });
    }
    return items;
  }

  /* ======================================================================
     NAIVE BAYES
     ====================================================================== */
  const nbBase = (ctx) => {
    const a = Number(ctx.opt('nbAlpha', 1));
    const v = Number(ctx.opt('nbVar', 1e-9));
    return { ...base(ctx), alpha: a > 0 ? a : 1, var_smoothing: v >= 0 ? v : 1e-9 };
  };

  async function nbRender(ctx) {
    ctx.lrn = null;
    const b = nbBase(ctx);
    const r = await ctx.call('naivebayes.fit', b);
    if (r.error) { ctx.container.append(ctx.warn(r.error)); return; }
    ctx.lrn = { r, b };
    const fd = SM.predict.measures(ctx, ctx.container, r.fit, { title: 'Fit Details', key: 'fitdetails' });
    if (r.cv && r.cv.measures) fd.add(ctx.rt({ columns: r.fit.measure_columns.filter((c) => c.key !== 'auc' || r.cv.measures.auc != null), rows: [r.cv.measures] }, { key: 'nbcv', sortable: false, caption: `Crossvalidation: each row predicted by the model fitted without its fold (${r.cv.k} folds of the Validation column)` }));
    fd.add(ctx.note(`Each row's level probabilities: the level's share of the training rows times, for every factor, the chance of the row's value in that level: a normal density for a continuous factor, the level's smoothed share of the factor's levels for a categorical one (α = ${fmt(r.alpha)}). A value the row lacks is left out of its product${b.missing === 'informative' ? '; with Informative Missing that it is missing counts as a factor of its own' : ''}.`),
      ...(r.notes || []).map((t) => ctx.note(t)), ctx.code(r.code));
    await SM.predict.classification(ctx, ctx.container, r.fit, null, '', { save: { fn: 'naivebayes.save', payload: b } });
    if (ctx.opt('nbParams', false)) nbParams(ctx, r);
    if (ctx.opt('profiler', false) && !ctx.headless) await SM.profiler.render(ctx, ctx.container, { sources: [{ fn: 'naivebayes.profile', payload: b }], option: 'profiler' });
  }

  function nbParams(ctx, r) {
    const ob = ctx.outline('Class Parameters', { key: 'nbparams', info: 'p:naivebayes:params', menu: () => [{ label: 'Remove', action: () => ctx.set('nbParams', false) }] });
    const tables = [ctx.rt({ caption: 'Class Shares', columns: [{ key: 'level', label: 'Level', fmt: 'text' }, { key: 'n', label: 'Training Count' }, { key: 'share', label: 'Share', digits: 4 }], rows: r.priors }, { key: 'nbprior', sortable: false })];
    for (const p of r.parameters) {
      if (!p.rows.length) { tables.push(ctx.note(`${p.factor}: ${p.note}; left out.`)); continue; }
      if (p.kind === 'normal') {
        tables.push(ctx.rt({ caption: `${p.factor}: normal density`, columns: [{ key: 'level', label: 'Level', fmt: 'text' }, { key: 'n', label: 'Count' }, { key: 'mean', label: 'Mean' }, { key: 'sd', label: 'Std Dev' }], rows: p.rows }, { key: `nbp:${p.factor}`, sortable: false }));
      } else {
        const cols = [{ key: 'level', label: 'Level', fmt: 'text' }, { key: 'n', label: 'Count' }, ...p.labels.map((l, j) => ({ key: `p${j}`, label: `P(${l})`, digits: 4 }))];
        tables.push(ctx.rt({ caption: `${p.factor}: level shares`, columns: cols, rows: p.rows }, { key: `nbp:${p.factor}`, sortable: false }));
      }
    }
    ob.add(ctx.row(...tables), ctx.note(`For each level of the response (a line): a continuous factor's weighted mean and standard deviation over the training rows that have it, the variance with ${fmt(r.eps, { sig: 3 })} added (scikit-learn GaussianNB's var_smoothing, ${String(r.var_smoothing)}, times the largest variance of a factor); a categorical factor's shares (count + α)/(total + α × levels) with α = ${fmt(r.alpha)} (CategoricalNB). Counts are sums of Weight × Freq.`));
  }

  async function nbSmoothing(ctx) {
    const v = await SM.ui.form({
      title: 'Smoothing', info: 'p:naivebayes',
      fields: [
        { key: 'alpha', label: 'α, added to every count of a categorical factor\'s levels', type: 'number', value: Number(ctx.opt('nbAlpha', 1)), help: HELP.alpha },
        { key: 'vs', label: 'Variance smoothing: the share of the largest variance added to each', type: 'number', value: Number(ctx.opt('nbVar', 1e-9)), help: HELP.varSmoothing },
      ],
      validate: (x) => (!(x.alpha > 0) ? 'α is positive' : !(x.vs >= 0) ? 'The variance smoothing is zero or more' : null),
    });
    if (v) { ctx.set('nbAlpha', v.alpha, null, { rerun: false }); ctx.set('nbVar', v.vs); }
  }

  function nbTriangle(ctx) {
    const s = ctx.lrn;
    const items = [];
    if (s) items.push(...SM.predict.classificationItems(ctx, s.r.fit));
    items.push(ctx.check('Class Parameters', 'nbParams', null, false), ctx.check('Profiler', 'profiler', null, false), { label: 'Smoothing…', action: () => nbSmoothing(ctx) });
    if (s) {
      const save = SM.predict.saveItems(ctx, 'naivebayes.save', s.b, s.r.fit)[0].submenu();
      save.push({ label: 'Save Prediction Formula', action: () => nbFormula(ctx, s.b) });
      items.push({ separator: true }, { label: 'Save Columns', submenu: () => save });
    }
    return items;
  }

  /* Save Prediction Formula: Log Score[level], Prob[level] and Most Likely as live formula columns (naivebayes.formula).
     A name the table has already gets a number (Prob[export] 2, as JMP names it), and the columns saved after it
     read it by that name. */
  const fRef = (name) => (/^[\p{L}_][\p{L}\p{N}_]*$/u.test(String(name)) ? `:${name}` : `:"${String(name).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`);
  async function nbFormula(ctx, payload) {
    try {
      const f = await ctx.call('naivebayes.formula', payload);
      const from = `the Naive Bayes model of ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`;
      const renamed = [];
      const put = (q, spec) => {
        const c = ctx.saveFormula(q.name, renamed.reduce((e, [a, b]) => e.split(a).join(b), q.expr), spec);
        if (c && c.name !== q.name) renamed.push([fRef(q.name), fRef(c.name)]);
        return c;
      };
      for (const q of f.scores) put(q, { notes: `the log of the level's class share plus each factor's log density (continuous) or log smoothed share (categorical), a factor the row lacks left out: ${from}` });
      for (const q of f.probs) put(q, { notes: `the level's probability from the Log Score columns, kept between 1e-15 and 1 − 1e-15: ${from}` });
      put(f.most, { modelingType: f.most.ordinal ? 'ordinal' : 'nominal', valueOrder: f.most.levels, notes: `the level with the largest probability (of equal ones the first): ${from}` });
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  /* ======================================================================
     SUPPORT VECTOR MACHINES
     ====================================================================== */
  const KERNELS = [['rbf', 'Radial Basis Function'], ['linear', 'Linear']];
  function svmBase(ctx) {
    const g = ctx.opt('gamma', '');
    const gamma = g === '' || g == null ? null : Number(String(g).replace(',', '.'));
    const cost = Number(ctx.opt('cost', 1));
    const pts = Number(ctx.opt('points', 20));
    return { ...base(ctx), kernel: ctx.opt('kernel', 'rbf') === 'linear' ? 'linear' : 'rbf', cost: cost > 0 ? cost : 1, gamma: Number.isFinite(gamma) && gamma > 0 ? gamma : null,
      tune: !!ctx.opt('tune', false), points: Number.isInteger(pts) && pts >= 2 ? pts : 20 };
  }

  async function svmRender(ctx) {
    ctx.lrn = null;
    const b = svmBase(ctx);
    const done = b.tune ? progressNote(ctx, 'svm', 'Tuning design') : null;
    let r;
    try { r = await ctx.call('svm.fit', { ...b, keep: keepOf(ctx) }); } finally { if (done) done(); }
    if (r.error) { ctx.container.append(ctx.warn(r.error)); return; }
    ctx.lrn = { r, b };
    if (ctx.opt('svmSummary', true)) svmSummary(ctx, r);
    if (r.tuning) svmTuning(ctx, r);
    const fd = SM.predict.measures(ctx, ctx.container, r.fit, { title: 'Fit Details', key: 'fitdetails' });
    fd.add(ctx.code(r.code));
    await SM.predict.classification(ctx, ctx.container, r.fit, null, '', { save: { fn: 'svm.save', payload: b } });
    SM.predict.actualByPredicted(ctx, ctx.container, r.fit);
    if (ctx.headless) return;   // Bootstrap: no graphs, and the boundary has no table
    if (r.continuous.length >= 2 && ctx.opt('boundary', true)) await svmBoundary(ctx, r, b);
    if (ctx.opt('profiler', false)) await SM.profiler.render(ctx, ctx.container, { sources: [{ fn: 'svm.profile', payload: b }], option: 'profiler' });
  }

  function svmSummary(ctx, r) {
    const s = r.summary;
    const cat = r.kind === 'categorical';
    const ob = ctx.outline('Model Summary', { key: 'svmsummary', info: 'p:svm:summary', menu: () => [{ label: 'Remove', action: () => ctx.set('svmSummary', false) }] });
    const tuned = r.tuning ? ' (tuned)' : '';
    const dflt = !r.tuning && s.kernel === 'rbf' && Math.abs(s.gamma - s.gamma0) <= 1e-12 * s.gamma0 ? ' (1/columns of X)' : '';
    const pairs = [
      ['Response', `${ctx.name('y')} (${cat ? `${r.fit.levels.length} levels: SVC` : 'continuous: SVR'})`, 'text'],
      ['Kernel Function', s.kernel_label, 'text'],
      [`Cost${tuned}`, s.cost, 'num', { sig: 6 }],
      s.kernel === 'rbf' ? [`Gamma${tuned}${dflt}`, s.gamma, 'num', { sig: 6 }] : null,
      ['Number of Support Vectors', s.n_sv, 'int'],
      ...(cat ? s.sv_per_level.map((q) => [`Support Vectors, ${q.level}`, q.n, 'int']) : []),
      ['Training Rows', s.n_train, 'int'],
      ['Columns of X', s.n_columns, 'int'],
      !cat ? ['Epsilon (standardized response)', s.epsilon] : null,
      cat ? ['Rows Where the Decision Function Differs', s.differs, 'int'] : null,
    ];
    ob.add(wide(ctx.kv(pairs)));
    const lines = [`The factors are standardized by the training rows' mean and standard deviation (a level's 0/1 column as it is).`];
    if (cat) lines.push(`The probabilities are Platt's: a logistic curve on the decision function, fitted by libsvm on 5-fold cross-validation of the training rows (SVC(probability=True), random_state ${s.seed}, the report's seed). The most likely level is the one with the largest probability; the decision function's own level (svm.predict) differs from it in ${s.differs} row${s.differs === 1 ? '' : 's'}${s.differs ? ', near the boundary' : ''}.`);
    else lines.push(`The response is standardized too (mean ${fmt(s.ym, { sig: 5 })}, standard deviation ${fmt(s.ys, { sig: 5 })}), so that epsilon, the width of the band without loss, is 0.1 of its standard deviation; the predictions are on the response's own scale.`);
    ob.add(ctx.note(lines.join(' ')));
  }

  function svmTuning(ctx, r) {
    const t = r.tuning;
    const rbf = r.summary.kernel === 'rbf';
    const H = SM.util.themeColors();
    const ob = ctx.outline('Tuning Design', { key: 'svmtune', info: 'p:svm:tuning', menu: () => [{ label: 'Tuning Design…', action: () => tuneDialog(ctx) }, { label: 'Remove', action: () => ctx.set('tune', false) }] });
    const judged = t.how === 'validation' ? 'Validation' : 'Cross-Validated';
    const cols = [{ key: 'cost', label: 'Cost', sig: 5 }, ...(rbf ? [{ key: 'gamma', label: 'Gamma', sig: 5 }] : []), { key: 'crit', label: `${judged} ${t.label}` }];
    const best = t.rows[t.best];
    const tbl = ctx.rt({ columns: cols, rows: t.rows }, { key: 'svmtune', cellClass: (row, c) => (row === best ? `sm-lrn-chosen${c.key === 'crit' ? ' sm-lrn-best' : ''}` : '') });
    const good = t.rows.filter((q) => q.crit != null);
    let plot;
    if (rbf) {
      plot = ctx.plot([
        { type: 'scatter', mode: 'markers', x: good.map((q) => q.cost), y: good.map((q) => q.gamma), marker: { size: 16, symbol: 'square', color: good.map((q) => q.crit), colorscale: ramp(), showscale: true, colorbar: { title: { text: t.label, side: 'right' }, thickness: 12, len: 0.9 }, line: { color: H.surface, width: 1 } },
          hovertemplate: `Cost %{x:.4g}<br>Gamma %{y:.4g}<br>${t.label} %{marker.color:.4f}<extra></extra>`, name: 'Design' },
        { type: 'scatter', mode: 'markers', x: [best.cost], y: [best.gamma], marker: { size: 24, symbol: 'square-open', color: H.text, line: { width: 2, color: H.text } }, hoverinfo: 'skip', name: 'Best' },
      ], { margin: { l: 62, r: 10, t: 8, b: 44 }, xaxis: { title: { text: 'Cost' }, type: 'log', dtick: 1 }, yaxis: { title: { text: 'Gamma' }, type: 'log', dtick: 1 } }, { width: W(400), height: 320, title: 'Tuning design', select: false });
    } else {
      plot = ctx.plot([
        { type: 'scatter', mode: 'lines+markers', x: good.map((q) => q.cost), y: good.map((q) => q.crit), line: { color: hueOf(0), width: 2 }, marker: { color: hueOf(0), size: 8 }, hovertemplate: `Cost %{x:.4g}: ${t.label} %{y:.4f}<extra></extra>`, name: 'Design' },
        { type: 'scatter', mode: 'markers', x: [best.cost], y: [best.crit], marker: { size: 16, symbol: 'circle-open', color: H.text, line: { width: 2, color: H.text } }, hoverinfo: 'skip', name: 'Best' },
      ], { margin: { l: 62, r: 10, t: 8, b: 44 }, xaxis: { title: { text: 'Cost' }, type: 'log', dtick: 1 }, yaxis: { title: { text: `${judged} ${t.label}` }, rangemode: 'tozero' } }, { width: W(400), height: 300, title: 'Tuning design', select: false });
    }
    const failed = t.rows.length - good.length;
    const pc = r.fit.plots || {};
    ob.add(ctx.row(tbl, SM.predict.withCode(plot, SM.predict.graphCode(ctx, pc.head_code, pc.tuning))), ctx.note(`${t.rows.length} points: ${rbf ? `Cost from 0.1 to 1000 and Gamma from 1/100 to 10 times ${fmt(t.gamma0, { sig: 4 })} (one over the columns of X), evenly on the log scale and crossed` : 'Cost from 0.01 to 100, evenly on the log scale'}. Each is fitted to the training rows and judged by ${t.how === 'validation' ? 'the validation rows' : `${t.how} of the training rows (no validation rows; the folds from the seed)`}; the smallest ${t.label.toLowerCase()} wins (of equal ones the smaller Cost, then the smaller Gamma), and the model is fitted again with it and with Platt's probabilities.${failed ? ` ${failed} point${failed === 1 ? '' : 's'} could not be fitted (a fold with one level).` : ''}`));
  }

  async function tuneDialog(ctx) {
    const v = await SM.ui.form({
      title: 'Tuning Design', info: 'p:svm:tuning',
      fields: [{ key: 'tune', label: 'Fit a tuning design of Cost and Gamma', type: 'check', value: !!ctx.opt('tune', false), help: HELP.tune }, { key: 'points', label: 'Number of design points', type: 'number', value: Number(ctx.opt('points', 20)) || 20, help: HELP.points }],
      validate: (x) => (Number.isInteger(x.points) && x.points >= 2 && x.points <= 200 ? null : 'The design has 2 to 200 points'),
    });
    if (v) { ctx.set('points', v.points, null, { rerun: false }); ctx.set('tune', v.tune); }
  }

  async function costDialog(ctx) {
    // no info: the platform's topic lists Cost and Gamma already; the form's (i) is its fields
    const v = await SM.ui.form({
      title: 'Cost and Gamma',
      fields: [{ key: 'cost', label: 'Cost', type: 'number', value: Number(ctx.opt('cost', 1)) || 1, help: HELP.costForm }, { key: 'gamma', label: 'Gamma (empty: one over the columns of X)', type: 'text', value: ctx.opt('gamma', '') ?? '', help: HELP.gammaForm }],
      validate: (x) => {
        if (!(x.cost > 0)) return 'Cost is a positive number';
        const g = String(x.gamma || '').trim();
        return g === '' || Number(g.replace(',', '.')) > 0 ? null : 'Gamma is a positive number, or empty';
      },
    });
    if (v) { ctx.set('cost', v.cost, null, { rerun: false }); ctx.set('tune', false, null, { rerun: false }); ctx.set('gamma', String(v.gamma || '').trim()); }
  }

  /* The pair of continuous factors the boundary is drawn over. */
  function boundaryPair(ctx, r) {
    const xs = ctx.roles('x');
    const want = (ctx.opt('svmPair', null) || []).map((id) => xs.find((c) => c.id === id)).filter(Boolean).map((c) => c.name).filter((n) => r.continuous.includes(n));
    return want.length === 2 && want[0] !== want[1] ? want : r.continuous.slice(0, 2);
  }

  async function svmBoundary(ctx, r, b) {
    const pair = boundaryPair(ctx, r);
    const xs = ctx.roles('x');
    const idOf = (name) => (xs.find((c) => c.name === name) || {}).id;
    const current = ctx.opt(`profilerAt:profiler:${ctx.byLabel || ''}`, null);
    const cat0 = r.kind === 'categorical';
    const ringsOn = ctx.opt('svmSV', cat0);   // for SVR nearly every row is a support vector
    const ob = ctx.outline(cat0 ? 'Decision Boundary' : 'Prediction Surface', { key: 'svmboundary', info: 'p:svm:boundary', menu: () => {
      const items = [];
      if (r.continuous.length > 2) {
        const pairs = [];
        for (let i = 0; i < r.continuous.length; i++) for (let j = i + 1; j < r.continuous.length; j++) pairs.push([r.continuous[i], r.continuous[j]]);
        items.push({ label: 'Factors', submenu: () => pairs.map((p) => ({ label: `${p[0]} and ${p[1]}`, checked: p[0] === pair[0] && p[1] === pair[1], action: () => ctx.set('svmPair', [idOf(p[0]), idOf(p[1])]) })) });
      }
      items.push(ctx.check('Support Vectors', 'svmSV', null, cat0), { separator: true }, { label: 'Remove', action: () => ctx.set('boundary', false) });
      return items;
    } });
    let g;
    // the page's choice the graph's code draws with: the support vectors ringed or not
    try { g = await ctx.call('svm.boundary', { ...b, pair, current, m: 61, plot: { sv: !!ringsOn } }); } catch (e) { ob.add(ctx.error(e)); return; }
    const C = SM.util.themeColors();
    const traces = [];
    const cat = g.kind === 'categorical';
    const levels = g.levels;
    const hover = `${T(g.pair[0])} %{x:.4g}<br>${T(g.pair[1])} %{y:.4g}`;
    if (cat && g.decision) {
      const neg = hueOf(levels.indexOf(g.negative)), pos = hueOf(levels.indexOf(g.positive));
      const zc = g.decision.map((row) => row.map((v) => Math.max(-2.5, Math.min(2.5, v))));
      traces.push({ type: 'heatmap', x: g.x, y: g.y, z: zc, zmin: -2.5, zmax: 2.5, zsmooth: 'best', colorscale: [[0, neg], [0.5, C.surface], [1, pos]], opacity: 0.24, showscale: false, hovertemplate: `${hover}<br>decision function %{z:.3f}<extra></extra>`, name: 'Decision function' });
      traces.push({ type: 'contour', x: g.x, y: g.y, z: g.decision, autocontour: false, contours: { start: 0, end: 0, size: 1, coloring: 'none' }, line: { color: C.text, width: 2 }, showscale: false, hoverinfo: 'skip', name: 'Boundary', showlegend: true });
      traces.push({ type: 'contour', x: g.x, y: g.y, z: g.decision, autocontour: false, contours: { start: -1, end: 1, size: 2, coloring: 'none' }, line: { color: C.muted, width: 1.2, dash: 'dash' }, showscale: false, hoverinfo: 'skip', name: 'Margins (±1)', showlegend: true });
    } else if (cat) {
      const L = levels.length;
      const cs = [];
      for (let i = 0; i < L; i++) cs.push([i / L, hueOf(i)], [(i + 1) / L, hueOf(i)]);
      traces.push({ type: 'heatmap', x: g.x, y: g.y, z: g.most, zmin: -0.5, zmax: L - 0.5, zsmooth: false, colorscale: cs, opacity: 0.24, showscale: false,
        text: g.most.map((row, i) => row.map((k, j) => `${T(levels[k])} (${g.pmax[i][j].toFixed(3)})`)), hovertemplate: `${hover}<br>most likely %{text}<extra></extra>`, name: 'Most likely level' });
    } else {
      traces.push({ type: 'contour', x: g.x, y: g.y, z: g.pred, colorscale: ramp(), opacity: 0.45, contours: { coloring: 'heatmap', showlabels: true, labelfont: { size: 9.5, color: C.text } }, line: { width: 0.6, color: C.surface },
        colorbar: { title: { text: T(ctx.name('y')), side: 'right' }, thickness: 12, len: 0.9 }, hovertemplate: `${hover}<br>predicted %{z:.4g}<extra></extra>`, name: 'Prediction' });
    }
    const P = g.points;
    const shape = (base, set) => (set === 0 ? base : `${base}-open`);
    if (cat) {
      levels.forEach((lv, j) => {
        // training rows first: the legend shows a trace's first marker
        const idx = P.value.map((v, i) => (v === j ? i : -1)).filter((i) => i >= 0).sort((a, b) => (P.set[a] === 0 ? 0 : 1) - (P.set[b] === 0 ? 0 : 1) || a - b);
        if (!idx.length) return;
        traces.push({ type: 'scatter', mode: 'markers', x: idx.map((i) => P.x[i]), y: idx.map((i) => P.y[i]), rows: idx.map((i) => P.rows[i]), name: T(lv), showlegend: true,
          marker: { color: hueOf(j), symbol: idx.map((i) => shape(symbolOf(j), P.set[i])), size: 7, line: { color: C.surface, width: 0.8 } } });
      });
    } else {
      traces.push({ type: 'scatter', mode: 'markers', x: P.x, y: P.y, rows: P.rows, name: 'Rows', showlegend: true, marker: { size: 6, color: C.text, symbol: P.set.map((s) => shape('circle', s)), line: { color: C.surface, width: 0.6 } } });
    }
    const nsv = P.sv.filter(Boolean).length;
    if (ringsOn && nsv) {
      const idx = P.sv.map((v, i) => (v ? i : -1)).filter((i) => i >= 0);
      traces.push({ type: 'scatter', mode: 'markers', x: idx.map((i) => P.x[i]), y: idx.map((i) => P.y[i]), marker: { symbol: 'circle-open', size: 12, color: C.muted, line: { width: 1, color: C.muted } }, hoverinfo: 'skip', name: 'Support vectors', showlegend: true });
    }
    const plot = ctx.plot(traces, {
      showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, margin: { l: 60, r: 12, t: 34, b: 46 },
      xaxis: { title: { text: T(g.pair[0]) }, range: [g.x[0], g.x[g.x.length - 1]], zeroline: false }, yaxis: { title: { text: T(g.pair[1]) }, range: [g.y[0], g.y[g.y.length - 1]], zeroline: false },
    }, { width: W(500), height: 440, title: `${cat0 ? 'Decision boundary' : 'Prediction surface'} over ${g.pair[0]} and ${g.pair[1]}`, rowColors: false });
    const held = g.held.length ? ` The other factors are held at ${g.held.map((h) => `${h.name} = ${typeof h.value === 'number' ? fmt(h.value, { sig: 5 }) : h.value}`).join(', ')} (the Prediction Profiler's current values: the means and first levels until you move them).` : '';
    const what = cat && g.decision ? `The shading is the decision function, toward ${g.positive} where positive and ${g.negative} where negative; the solid line is the boundary (0), the dashed lines the margins (−1 and 1).`
      : cat ? 'The shading is the most likely level at each point (the largest Platt probability).' : 'The shading and its contours are the predicted response.';
    ob.add(ctx.row(SM.predict.withCode(plot, SM.predict.graphCode(ctx, (r.fit.plots || {}).head_code, g.plot_code))), ctx.note(`${what} Each point is a row: filled for training rows, open for validation and test rows${nsv && ringsOn ? '; rings mark the support vectors' : ` (${nsv} of the ${r.summary.n_train} training rows are support vectors: Support Vectors in the red triangle rings them)`}. Click or drag to select rows.${held}${g.n_missing ? ` ${g.n_missing} rows missing one of the two are not drawn.` : ''}`), ctx.code(g.code));
  }

  function svmTriangle(ctx) {
    const s = ctx.lrn;
    const items = [ctx.check('Model Summary', 'svmSummary', null, true)];
    if (s) items.push(...SM.predict.classificationItems(ctx, s.r.fit));
    items.push(ctx.check(s && s.r.kind === 'continuous' ? 'Prediction Surface' : 'Decision Boundary', 'boundary', null, true, { disabled: !s || s.r.continuous.length < 2 }),
      ctx.check('Profiler', 'profiler', null, false),
      { separator: true },
      { label: 'Kernel Function', submenu: () => KERNELS.map(([k, l]) => ({ label: l, checked: (ctx.opt('kernel', 'rbf') === 'linear' ? 'linear' : 'rbf') === k, action: () => ctx.set('kernel', k) })) },
      { label: 'Cost and Gamma…', action: () => costDialog(ctx) },
      { label: 'Tuning Design…', checked: !!ctx.opt('tune', false), action: () => tuneDialog(ctx) });
    if (s) {
      const save = SM.predict.saveItems(ctx, 'svm.save', s.b, s.r.fit)[0].submenu();
      save.push({ label: 'Score Rows…', action: () => scoreRows(ctx, 'svm.score', s) });
      items.push({ separator: true }, { label: 'Save Columns', submenu: () => save });
    }
    return items;
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const DIFF_JMP = 'Where it differs from JMP';
  const TOPICS_KNN = {
    'p:knn': {
      kicker: 'Analyze > Predictive Modeling', title: 'K Nearest Neighbors',
      lead: 'Predicts each row from the K training rows nearest to it: the level most of them have (a categorical response) or their mean response (a continuous one). Every K from 1 to the Number of Neighbors is fitted, and the best is kept by the validation rows, or by the training rows when there are none. scikit-learn\'s KNeighborsClassifier and KNeighborsRegressor.',
      sections: [
        { heading: 'Roles', choices: [['Y, Response', 'continuous, nominal or ordinal'], ['X, Factor', 'one or more; continuous factors are standardized (the training rows\' mean and standard deviation), a categorical factor is a 0/1 column per level, not scaled: a different level adds 2 to the squared distance, as √2 standard deviations of a continuous factor'], ['Validation', 'a column of 0/1/2, or the Validation Portion'], ['By', 'a separate analysis for each level']] },
        { heading: 'Distances and ties', text: 'Euclidean distance, on the factors standardized by the training rows (Standardize, on by default), each neighbour one vote or, with Distance Weights, a vote of 1/distance. A training row is not its own neighbour (so K = 1 is not a perfect fit of the training rows). Rows at the same distance as the K-th are taken as scikit-learn\'s search for the largest K returns them (its documentation warns the result then depends on the order of the rows), and every smaller K takes the first of those. A tied vote goes to one of the tied levels at random, as JMP breaks ties: from the report\'s seed, a uniform number per row and level, the tied level with the largest wins (so Redo and the code give the same levels). The probabilities are the shares of the votes with a prior of one vote spread evenly over the levels, (votes + 1/L)/(K + 1), never 0 or 1.' },
        { heading: 'K-fold Validation column', text: 'With a Validation column of more than three values (Make Validation Column, K Fold) every row trains, each fold is predicted from its neighbours in the other folds, and the best K is the one with the smallest crossvalidated error (Model Selection\'s Crossvalidation line).' },
        { heading: 'Score Rows', text: 'Save Columns ▸ Score Rows… predicts rows the model did not see (rows added to the table since, or another open table with the same columns) with the model as the report fitted it: K Nearest Neighbors has no formula to save.' },
        { heading: 'Missing values', text: 'With Informative Missing a missing continuous value is the training mean plus a 0/1 Missing column, and a missing level is a level of its own; without it rows missing a factor are left out.' },
        { heading: DIFF_JMP, text: 'Weight and Freq are not offered: scikit-learn\'s neighbours take no case weights. Whether JMP counts a training row among its own neighbours is not known here; this platform\'s rule is stated above. Distance Weights, the Mosaic Plot\'s links, Score Rows and the Profiler are not in JMP\'s platform.' },
      ],
      more: MORE('knn', 'K Nearest Neighbors'),
    },
    'p:knn:selection': {
      kicker: 'K Nearest Neighbors', title: 'Model Selection',
      lead: 'For every K from 1 to the Number of Neighbors: the misclassification rate (and the number of rows misclassified) or the RASE, the root average squared error, of each set. The best K has the smallest value on the validation rows, or on the training rows when there are none; of equal values the smallest K. Click a line of the table or a point of the plot to see another K.',
      sections: [{ heading: 'Choosing K', choices: [
        ['A click on a line of the table or a point of the graph', 'Shows that K in Chosen Model below (the solid line in the plot); a click on the best K goes back to it. Save Columns saves the K shown.'],
        ['Select K (red triangle)', 'The same from a menu: Best K, or any K up to the Number of Neighbors (Other K… when there are more than 30).'],
        ['Number of Neighbors… (red triangle)', 'Fits every K up to a new largest one.'],
      ] }],
      more: MORE('knn', 'K Nearest Neighbors'),
    },
    'p:knn:fit': {
      kicker: 'K Nearest Neighbors', title: 'The Chosen K',
      lead: 'The Measures of Fit, confusion matrices, ROC and lift curves (a categorical response) or actual by predicted (a continuous one) of the chosen K: the best, or the one picked in Model Selection. A training row\'s prediction leaves the row out; Save Predicteds saves these predictions, and for rows outside the report their nearest training rows\'.',
      sections: [{ heading: 'Save Near Neighbor Rows', text: 'K columns RowNear 1, RowNear 2, …: the row numbers (as the table shows them) of each row\'s nearest training rows, nearest first.' },
        { heading: 'Mosaic Plot', text: 'In the red triangle: for each set, a bar per actual level as wide as its share of the rows, cut by the shares of the levels its rows are called; click or drag over a part to select its rows.' }],
      more: MORE('knn', 'K Nearest Neighbors'),
    },
    'p:knn:mosaic': {
      kicker: 'K Nearest Neighbors', title: 'Mosaic Plot',
      lead: 'Actual by called, for each set: a bar per actual level, as wide as its share of the set\'s rows, cut by the shares of the levels its rows are called (the chosen K, a tied vote at random). A model that calls every row right has one colour per bar; the parts are linked to their rows.',
      more: MORE('knn', 'K Nearest Neighbors'),
    },
    'p:learners:score': {
      kicker: 'Predictive modeling', title: 'Score Rows',
      lead: 'The model as this report fitted it (the engine keeps it while the page is open) on rows it did not see: this table\'s rows added since the report fitted, or every row of another open table with the same columns, found by name. The predictions go into that table: into its prediction columns for the rows that have none yet, or as new columns. The model is not fitted again. After the engine starts again the model is fitted again from this table as it is now, and the page says so.',
      sections: [{ heading: 'Why', text: 'K Nearest Neighbors and Support Vector Machines have no formula a column could hold (their predictions need the training rows or the support vectors), so new rows are scored by the model itself.' }],
    },
  };

  const TOPICS_NB = {
    'p:naivebayes': {
      kicker: 'Analyze > Predictive Modeling', title: 'Naive Bayes',
      lead: 'Classifies rows into the levels of a categorical response, taking the factors as independent within each level: a level\'s probability is proportional to its share of the training rows times, for every factor, the chance of the row\'s value in that level. The model of scikit-learn\'s GaussianNB (continuous factors) and CategoricalNB (categorical ones) combined, with the class shares counted once, computed here so that a missing value can be left out.',
      sections: [
        { heading: 'Continuous factors', text: 'A normal density per level with the weighted mean and variance (divided by the weight, not n − 1) of the training rows in the level that have the factor, plus a small share of the largest variance (GaussianNB\'s var_smoothing, 1e-9) so that no variance is 0.' },
        { heading: 'Categorical factors', text: 'The level\'s smoothed shares of the factor\'s levels, (count + α)/(total + α × levels) with α = 1 (CategoricalNB\'s Laplace smoothing), so that a combination the training rows lack does not force a probability of 0. Smoothing (red triangle) changes α and the variance smoothing.' },
        { heading: 'Missing values', text: 'A value a row lacks is left out of its product (in the fit as in the prediction). With Informative Missing, that a continuous value is missing is a two-level factor of its own, and a missing level a level of its own; without it rows missing a factor are left out.' },
        { heading: 'Save Prediction Formula', text: 'Save Columns ▸ Save Prediction Formula: the model as live formula columns, a Log Score[level] per level (the log class share plus each factor\'s log density or log share, a factor the row lacks left out), Prob[level] from them, and the Most Likely level: new and edited rows are scored as the table changes.' },
        { heading: 'K-fold Validation column', text: 'With a Validation column of more than three values every row trains, and Fit Details adds the crossvalidated measures: each fold predicted by the model fitted to the others.' },
        { heading: DIFF_JMP, text: 'JMP\'s smoothing constants and variance rule are not known here; these are scikit-learn\'s. The probabilities are kept between 1e-15 and 1 − 1e-15.' },
      ],
      more: MORE('naivebayes', 'Naive Bayes'),
    },
    'p:naivebayes:params': {
      kicker: 'Naive Bayes', title: 'Class Parameters',
      lead: 'The fitted model: each level\'s share of the training rows, and per factor and level the normal density\'s mean and standard deviation or the smoothed shares of the factor\'s levels. Not in JMP.',
      more: MORE('naivebayes', 'Naive Bayes'),
    },
  };

  const TOPICS_SVM = {
    'p:svm': {
      kicker: 'Analyze > Predictive Modeling', title: 'Support Vector Machines',
      lead: 'A support vector classifier (a categorical response: scikit-learn\'s SVC) or regression (a continuous one: SVR) on the standardized factors, with a radial basis function or linear kernel. Cost weighs the errors against a wide margin; Gamma sets how far a training row\'s influence reaches (the radial basis function exp(−γ‖x − x′‖²)).',
      sections: [
        { heading: 'Roles', choices: [['Y, Response', 'continuous (SVR) or categorical (SVC)'], ['X, Factor', 'standardized by the training rows\' mean and standard deviation; a level\'s 0/1 column as it is'], ['Weight, Freq', 'case weights of the fit (they scale each row\'s Cost)'], ['Validation', 'judges the tuning design']] },
        // the launch's options (Kernel Function, Cost and Gamma, Tuning Design are in the red triangle too)
        { heading: 'Options', choices: [['Kernel Function', HELP.kernel], ['Cost', HELP.cost], ['Gamma', HELP.gamma], ['Tuning Design', HELP.tune], ['Design Points', HELP.points]] },
        { heading: 'Epsilon', text: 'SVR\'s epsilon is fixed at 0.1 of the standardized response: errors smaller than a tenth of the response\'s standard deviation cost nothing.' },
        { heading: 'Probabilities', text: 'SVC(probability=True): Platt scaling, a logistic curve on the decision function fitted by 5-fold cross-validation inside libsvm, its folds from random_state (the report\'s seed). The most likely level is the one with the largest probability; the decision function\'s level can differ near the boundary (Model Summary counts the rows).' },
        { heading: 'Score Rows', text: 'Save Columns ▸ Score Rows… predicts rows added since, or another open table, with the model as the report fitted it (see its (i)).' },
        { heading: DIFF_JMP, text: 'JMP\'s exact tuning design, its default Gamma and how it scales the response for SVR are not known here; these are this platform\'s choices. Without validation rows the tuning design is judged by 5-fold cross-validation of the training rows, or by the folds of a K-fold Validation column.' },
      ],
      more: MORE('svm', 'Support Vector Machines'),
    },
    'p:svm:summary': {
      kicker: 'Support Vector Machines', title: 'Model Summary',
      lead: 'The kernel, Cost and Gamma of the fitted model (tuned or as given), the number of support vectors (the training rows on or inside the margin, which alone define the model), the training rows and the columns of X.',
      more: MORE('svm', 'Support Vector Machines'),
    },
    'p:svm:tuning': {
      kicker: 'Support Vector Machines', title: 'Tuning Design',
      lead: 'A design of Cost and Gamma values, each fitted to the training rows and judged by the misclassification rate or RASE of the validation rows (or of 5-fold cross-validation when there are none). The best is fitted again with the probabilities. With the radial basis function the design crosses Cost from 0.1 to 1000 with Gamma from 1/100 to 10 times its default, evenly on the log scale; the linear kernel has Cost alone. A design of many points on thousands of rows takes a while.',
      more: MORE('svm', 'Support Vector Machines'),
    },
    'p:svm:boundary': {
      kicker: 'Support Vector Machines', title: 'Decision Boundary',
      lead: 'The model over two continuous factors, the others at the Prediction Profiler\'s current values: for two levels the decision function (0 is the boundary, −1 and 1 the margins), for more the most likely level, for a continuous response the prediction. The rows are drawn on it (filled: training, open: validation and test; rings: the support vectors) and linked to the table.',
      sections: [{ heading: 'The red triangle', choices: [
        ['Factors', 'With three or more continuous factors: the pair the model is drawn over (the first two at first).'],
        ['Support Vectors', 'Rings the training rows that are support vectors, the rows on or inside the margin that alone define the model. On for a classifier; off for SVR, where nearly every row is one.'],
      ] }],
      more: MORE('svm', 'Support Vector Machines'),
    },
  };

  /* ======================================================================
     THE PLATFORMS
     ====================================================================== */
  SM.platforms.register({
    id: 'knn', label: 'K Nearest Neighbors', menu: MENU, order: 50, info: 'p:knn', topics: TOPICS_KNN,
    about: 'Predicts a response from the K nearest training rows on the standardized factors (the most common level, a tie at random from the seed as JMP breaks ties, or the mean): the misclassification rate or RASE of every K from 1 to K on the training, validation and test rows (and the folds of a K-fold Validation column), the best K by validation, its Measures of Fit, confusion matrices, ROC, lift and the Decision Threshold, or actual by predicted; Save Predicteds, Save Near Neighbor Rows; and beyond JMP distance weights, a linked mosaic plot of actual by called, Score Rows for new rows or another table with the report\'s model, and a Prediction Profiler.',
    uses: ['sklearn.neighbors.KNeighborsClassifier, KNeighborsRegressor (kneighbors)'],
    launch: {
      lead: 'Predicts each row from its K nearest training rows. Every K from 1 to K is fitted; the best is kept by the validation rows (a Validation column or the Validation Portion), or by the training rows.',
      roles: [{ key: 'y', label: 'Y, Response', min: 1, max: 1, hint: 'required: continuous or categorical', help: HELP.knnY }, { ...xRole, help: HELP.knnX }, ...SM.predict.roles({ weight: false, freq: false })],
      options: [{ key: 'k', label: 'Number of Neighbors, K', type: 'number', value: 10, hint: 'every K from 1 to this one is fitted', help: HELP.k },
        { key: 'standardize', label: 'Standardize', type: 'check', value: true, help: HELP.standardize },
        { key: 'distance', label: 'Distance Weights', type: 'check', value: false, help: HELP.distance }, ...SM.predict.options()],
      validate: (spec) => { const k = spec.options.k; return Number.isInteger(k) && k >= 1 && k <= 1000 ? null : 'Number of Neighbors, K: a whole number from 1 to 1000'; },
    },
    title: titled('K Nearest Neighbors'), triangle: knnTriangle, render: knnRender,
  });

  SM.platforms.register({
    id: 'naivebayes', label: 'Naive Bayes', menu: MENU, order: 60, info: 'p:naivebayes', topics: TOPICS_NB,
    about: 'Classifies rows by a categorical response from the class shares and, for each factor, a normal density (continuous) or smoothed level shares (categorical), taken as independent within each level: Fit Details on each set (and crossvalidated by a K-fold Validation column), confusion matrices, ROC and lift curves, the Decision Threshold, the Prediction Profiler, the class parameters, and the probabilities and most likely level saved to the table, as values or as a live Prediction Formula. A missing value is left out of its row\'s product.',
    uses: ['the model of sklearn.naive_bayes.GaussianNB and CategoricalNB, combined (numpy; checked against them)'],
    launch: {
      lead: 'Classifies the rows by a nominal or ordinal response from continuous and categorical factors, each taken as independent within a level.',
      roles: [{ key: 'y', label: 'Y, Response', min: 1, max: 1, types: ['nominal', 'ordinal'], hint: 'required: nominal or ordinal', help: HELP.nbY }, { ...xRole, help: HELP.nbX }, ...SM.predict.roles()],
      // the shared Informative Missing, told as this model handles a missing value
      options: SM.predict.options().map((o) => (o.key === 'missing' ? { ...o, help: HELP.nbMissing } : o)),
    },
    title: titled('Naive Bayes'), triangle: nbTriangle, render: nbRender,
  });

  SM.platforms.register({
    id: 'svm', label: 'Support Vector Machines', menu: MENU, order: 70, info: 'p:svm', topics: TOPICS_SVM,
    about: 'Support vector classification or regression on the standardized factors with a radial basis function or linear kernel: Model Summary, a tuning design of Cost and Gamma judged by validation (or cross-validation, by the folds of a K-fold Validation column too), Fit Details on each set, confusion matrices, ROC and lift curves (Platt probabilities), the Decision Threshold, or actual by predicted, the decision boundary over two continuous factors linked to the rows, the Prediction Profiler, Save Columns and Score Rows (new rows or another table, with the report\'s model).',
    uses: ['sklearn.svm.SVC (probability=True: Platt scaling), SVR', 'sklearn.model_selection.KFold, StratifiedKFold (the tuning design without validation rows)'],
    launch: {
      lead: 'A support vector machine for a continuous or categorical response. The factors are standardized; a tuning design picks Cost and Gamma by the validation rows.',
      roles: [{ key: 'y', label: 'Y, Response', min: 1, max: 1, hint: 'required: continuous or categorical', help: HELP.svmY }, { ...xRole, help: HELP.svmX }, ...SM.predict.roles()],
      options: [
        { key: 'kernel', label: 'Kernel Function', type: 'select', value: 'rbf', choices: KERNELS, help: HELP.kernel },
        { key: 'cost', label: 'Cost', type: 'number', value: 1, help: HELP.cost },
        { key: 'gamma', label: 'Gamma', type: 'text', value: '', hint: 'empty: one over the number of columns of X', help: HELP.gamma },
        { key: 'tune', label: 'Tuning Design', type: 'check', value: false, hint: 'fit a design of Cost and Gamma values and keep the best by validation', help: HELP.tune },
        { key: 'points', label: 'Design Points', type: 'number', value: 20, help: HELP.points },
        ...SM.predict.options(),
      ],
      validate: (spec) => {
        const o = spec.options;
        if (!(o.cost > 0)) return 'Cost: a positive number';
        const g = String(o.gamma ?? '').trim();
        if (g !== '' && !(Number(g.replace(',', '.')) > 0)) return 'Gamma: a positive number, or empty';
        if (!(Number.isInteger(o.points) && o.points >= 2 && o.points <= 200)) return 'Design Points: a whole number from 2 to 200';
        return null;
      },
    },
    title: titled('Support Vector Machines'), triangle: svmTriangle, render: svmRender,
  });

  /* ---- the example: a simulated orchard ------------------------------------------------------ */
  SM.io.addExample('orchard', {
    label: 'Orchard (600 rows): apple variety and grade by size, sugar, firmness and skin',
    about: 'Simulated: 600 apples of three varieties (Early 35%, Mid 40%, Late 25%). Weight (g) is normal by variety (means 140, 170 and 205; SDs 16, 18 and 22); sugar (°Bx) has means 11.2, 13.0 and 12.4 and rises with weight in Mid (0.035 per g) and falls in Late (0.03 per g), so the varieties part along curves; firmness (N) has means 72, 64 and 57 (SD 6); skin is green, yellow or red with shares 60/30/10% (Early), 25/50/25% (Mid) and 10/30/60% (Late). Shelf life (days) is 30 + 0.24 (firmness − 64) − 0.0015 (weight − 170)² + 2 sin(1.3 (sugar − 12)) plus normal noise with SD 2.5. Grade is export when 0.9 − ((weight − 175)/28)² − ((sugar − 12.8)/1.5)² plus normal noise with SD 0.35 is above 0 (weight and sugar near their best, an ellipse), else local. Validation is 0, 1 or 2 (training 60%, validation 25%, test 15%) at random; orchard (North, South) is random and changes nothing. For K Nearest Neighbors, Naive Bayes and Support Vector Machines (Analyze > Predictive Modeling).',
    make() {
      const r = SM.util.rng('learners-orchard');
      const pick = (p) => { const u = r.u(); let a = 0; for (let i = 0; i < p.length; i++) { a += p[i]; if (u < a) return i; } return p.length - 1; };
      const n = 600;
      const c = { variety: [], weight: [], sugar: [], firmness: [], skin: [], shelf: [], grade: [], orchard: [], validation: [] };
      const MEANW = [140, 170, 205], SDW = [16, 18, 22];
      for (let i = 0; i < n; i++) {
        const v = pick([0.35, 0.4, 0.25]);
        const w = MEANW[v] + SDW[v] * r.normal();
        const s = [11.2, 13.0, 12.4][v] + [0, 0.035, -0.03][v] * (w - MEANW[v]) + [1.0, 0.9, 1.1][v] * r.normal();
        const f = [72, 64, 57][v] + 6 * r.normal();
        const skin = ['green', 'yellow', 'red'][pick([[0.6, 0.3, 0.1], [0.25, 0.5, 0.25], [0.1, 0.3, 0.6]][v])];
        const life = 30 + 0.24 * (f - 64) - 0.0015 * (w - 170) ** 2 + 2 * Math.sin(1.3 * (s - 12)) + 2.5 * r.normal();
        c.variety.push(['Early', 'Mid', 'Late'][v]);
        c.weight.push(+w.toFixed(1));
        c.sugar.push(+s.toFixed(2));
        c.firmness.push(+f.toFixed(1));
        c.skin.push(skin);
        c.shelf.push(+life.toFixed(1));
        // export grade: weight and sugar near their best (an ellipse), with noise
        c.grade.push(0.9 - ((w - 175) / 28) ** 2 - ((s - 12.8) / 1.5) ** 2 + 0.35 * r.normal() > 0 ? 'export' : 'local');
        c.orchard.push(r.u() < 0.5 ? 'North' : 'South');
        c.validation.push(pick([0.6, 0.25, 0.15]));
      }
      return new SM.Table({ name: 'Orchard', source: 'simulated', columns: [
        { name: 'variety', dataType: 'character', values: c.variety, valueOrder: ['Early', 'Mid', 'Late'] },
        { name: 'weight (g)', dataType: 'numeric', values: c.weight },
        { name: 'sugar (°Bx)', dataType: 'numeric', values: c.sugar },
        { name: 'firmness (N)', dataType: 'numeric', values: c.firmness },
        { name: 'skin', dataType: 'character', values: c.skin, valueOrder: ['green', 'yellow', 'red'] },
        { name: 'shelf life (days)', dataType: 'numeric', values: c.shelf },
        { name: 'grade', dataType: 'character', values: c.grade, valueOrder: ['export', 'local'] },
        { name: 'orchard', dataType: 'character', values: c.orchard },
        { name: 'Validation', dataType: 'numeric', modelingType: 'nominal', values: c.validation },
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
