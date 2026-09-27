/* ==========================================================================
   SMUI.HTML: ANALYZE > PREDICTIVE MODELING > MODEL SCREENING,
   AND MAKE VALIDATION COLUMN

   Model Screening (JMP Pro's) fits many kinds of predictive model to one
   response with the same rows, holdback and seed, and compares them:

     Summary Across the Models   the chosen measures of every method for
                                 every set, the best of each column marked;
                                 a click selects a method; Select Dominant,
                                 Run Selected (the method's own platform)
     Training, Validation, Test  every Measure of Fit per method and set
     Crossvalidation             K-fold: the means over the held-out folds,
                                 and the folds themselves
     Method Details              what each method chose, and the Python
     ROC Curve, Lift Curve       every method on one graph per set
     Actual by Predicted         a small graph per method, linked to rows
     Decision Threshold          two levels: the counts and rates at a cut
     Prediction Profiler         of one method

   The numbers are resources/py/smui/screening.py's (scikit-learn, and
   predictive.py's measures). Make Validation Column (Analyze > Predictive
   Modeling and Cols > Modeling Utilities) adds a Validation column.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const MORE = { label: 'Model Screening', id: 'help-p-screening' };
  const CV = 'Crossvalidation';

  const METHODS = [['tree', 'Decision Tree'], ['forest', 'Bootstrap Forest'], ['boosted', 'Boosted Tree'], ['knn', 'K Nearest Neighbors'],
    ['nb', 'Naive Bayes'], ['neural', 'Neural'], ['svm', 'Support Vector Machines'], ['lda', 'Discriminant'], ['linear', 'Fit Least Squares'],
    ['lasso', 'Generalized Regression Lasso'], ['enet', 'Generalized Regression Elastic Net'], ['stepwise', 'Fit Stepwise']];
  const KEYS = METHODS.map((m) => m[0]);
  const CAT_ONLY = new Set(['nb', 'lda']);
  const DEFAULT = KEYS.filter((k) => k !== 'stepwise');
  // the method's own platform, for Run Selected (present only when it is registered)
  const PLATFORM = { tree: 'partition', forest: 'forest', boosted: 'boosted', knn: 'knn', nb: 'naivebayes', neural: 'neural', svm: 'svm',
    lda: 'discriminant', linear: 'fitmodel', lasso: 'fitmodel', enet: 'fitmodel', stepwise: 'fitmodel' };
  const MEASURE_LABEL = { rsquare: 'RSquare', rase: 'RASE', mad: 'Mean Abs Dev', neg_loglik: '-LogLikelihood', sse: 'SSE', n: 'N',
    entropy_rsquare: 'Entropy RSquare', generalized_rsquare: 'Generalized RSquare', mean_neg_log_p: 'Mean -Log p', misclassification: 'Misclassification Rate', auc: 'AUC' };

  /* A colour per method, the same in every graph; lighter tints in the dark theme. */
  const LIGHT = ['#2f6690', '#c46a12', '#3a7d44', '#b0413e', '#6c5b7b', '#1a8a78', '#8f7600', '#8c564b', '#b8428f', '#666666', '#107f8f', '#7b5bb5'];
  const DARK = ['#6fa3d6', '#f0a050', '#6fbf73', '#e87c73', '#b39ddb', '#4fd1b8', '#e0c040', '#c9a084', '#f08fc8', '#b8b8b8', '#5fd4e8', '#a58ae6'];
  const colorOf = (key) => (SM.util.themeColors().dark ? DARK : LIGHT)[Math.max(0, KEYS.indexOf(key)) % LIGHT.length];
  const W = (w) => Math.max(240, Math.min(w, (root.innerWidth || 1200) - 110));
  const wide = (node) => el('div', { class: 'sm-scr-scroll' }, node);
  /* A legend of every method: beside the graph, or under it on a narrow screen (where one beside it would leave
     no room for the curves); the graph's width and height with it. */
  function legendFor(n) {
    const narrow = (root.innerWidth || 1200) < 760;
    return narrow
      ? { legend: { orientation: 'h', x: 0, y: -0.2, yanchor: 'top', font: { size: 9.5 } }, width: W(360), height: 330 + 17 * Math.ceil(n / 2), bottom: 40 }
      : { legend: { font: { size: 9.5 }, x: 1.02, y: 1, xanchor: 'left' }, width: W(560), height: 330, bottom: 40 };
  }
  const labelIn = (S, key) => { const m = S.r.methods.find((x) => x.key === key); return m ? m.label : (METHODS.find((x) => x[0] === key) || [key, key])[1]; };

  /* ---- the report's settings ------------------------------------------------------------ */
  function methodsOf(ctx, yc) {
    const chosen = ctx.opt('methods', DEFAULT);
    return KEYS.filter((k) => (Array.isArray(chosen) ? chosen : DEFAULT).includes(k) && (yc.isCategorical || !CAT_ONLY.has(k)));
  }

  function kfoldOf(ctx) {
    if (!ctx.opt('kfold', false) || ctx.roles('validation').length) return { kfold: 0, repeats: 1 };
    const k = Math.round(Number(ctx.opt('folds', 5)));
    const r = Math.round(Number(ctx.opt('repeats', 1)));
    return { kfold: Number.isFinite(k) ? Math.max(2, Math.min(20, k)) : 5, repeats: Number.isFinite(r) ? Math.max(1, Math.min(10, r)) : 1 };
  }

  const selectedOf = (ctx, S) => (ctx.opt('selected', []) || []).filter((k) => S.r.methods.some((m) => m.key === k && m.measures));

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx) {
    const yc = ctx.role('y');
    const xs = ctx.roles('x');
    const kf = kfoldOf(ctx);
    const spec = { y: yc.name, x: xs.map((c) => c.name), ...SM.predict.payload(ctx), kfold: kf.kfold };
    const pay = { ...spec, methods: methodsOf(ctx, yc), repeats: kf.repeats };
    let note = null, off = null;
    if (!ctx.headless) {
      note = el('p', { class: 'sm-ob-note sm-scr-progress', role: 'status', text: `Model Screening: fitting ${pay.methods.length} methods…` });
      ctx.container.append(note);
      off = SM.engine.on('progress', (p) => {
        if (!p || p.what !== 'screening') return;
        const text = `Model Screening${ctx.byLabel ? ` (${ctx.byLabel})` : ''}: ${p.done} of ${p.total} fits…`;
        note.textContent = text;
        ctx.report.noteEl.textContent = text;
      });
    }
    let r;
    try { r = await ctx.call('screening.fit', pay); } finally { if (off) off(); if (note) note.remove(); }
    const S = { r, spec, pay, yc, xs, binary: r.kind === 'categorical' && r.levels.length === 2 };
    ctx.scr = S;
    ctx.container.append(ctx.note(setsNote(ctx, S)));
    summaryOutline(ctx, S);
    setTables(ctx, S);
    if (r.kfold) cvOutline(ctx, S);
    if (ctx.opt('details', true)) detailsOutline(ctx, S);
    if (r.kind === 'categorical') {
      if (ctx.opt('roc', false)) curveOutline(ctx, S, 'roc');
      if (ctx.opt('lift', false)) curveOutline(ctx, S, 'lift');
      if (S.binary && ctx.opt('threshold', false)) await thresholdOutline(ctx, S);
    } else if (ctx.opt('abp', false)) abpOutline(ctx, S);
    const prof = ctx.opt('profiler', false);
    if (prof && r.methods.some((m) => m.key === prof && m.measures)) {
      await SM.profiler.render(ctx, null, { sources: [{ fn: 'screening.profile', payload: { ...spec, method: prof } }], option: 'profiler', title: `Prediction Profiler: ${labelIn(S, prof)}`,
        note: `The ${labelIn(S, prof)} model of the Summary, fitted to the training rows. Drag the red dashed line of a factor, click in its plot, or type its value.` });
    }
  }

  function setsNote(ctx, S) {
    const { r, spec } = S;
    const n = r.n;
    const parts = [];
    if (r.kfold) {
      parts.push(`${fmt(n.Training + n.Validation)} rows in ${r.kfold}-fold crossvalidation${r.repeats > 1 ? `, repeated ${r.repeats} times` : ''} (seed ${r.seed}): each method is fitted ${r.kfold * r.repeats} times more, each time on all folds but one, tuned without it, and measured on it; the Training columns are the methods fitted to every row.`);
    } else if (spec.validation) {
      parts.push(`Sets from the Validation column ${spec.validation}: ${r.sets.map((s) => `${s} ${fmt(n[s])}`).join(', ')} rows.`);
    } else if (r.sets.includes('Validation')) {
      parts.push(`Training ${fmt(n.Training)} rows, Validation ${fmt(n.Validation)}: a random holdback of ${fmt(100 * spec.portion)}% (seed ${r.seed}).`);
    } else {
      parts.push(`${fmt(n.Training)} training rows and no validation: the measures are on the rows each model learned from, and flexible methods look better than they predict. Give a Validation Portion, a Validation column or K-fold crossvalidation to compare them fairly.`);
    }
    parts.push(...(r.notes || []));
    return parts.join(' ');
  }

  /* ======================================================================
     SUMMARY ACROSS THE MODELS
     ====================================================================== */
  function measureCols(r, set, keys, hide = () => false) {
    return keys.map((k) => ({ key: `${set}|${k}`, label: `${set} ${MEASURE_LABEL[k] || k}`, fmt: 'num', digits: k === 'n' ? null : 4, hidden: hide(k) }));
  }

  function rowOf(m, sets, keys) {
    const row = { key: m.key, method: m.label };
    for (const s of sets) for (const k of keys) row[`${s}|${k}`] = m.measures && m.measures[s] ? m.measures[s][k] : null;
    return row;
  }

  function bestClass(S, sel) {
    return (row, c) => {
      const cls = [];
      const i = c.key.indexOf('|');
      if (i > 0) {
        const set = c.key.slice(0, i), k = c.key.slice(i + 1);
        if (k !== 'n' && ((S.r.best[set] || {})[k] || []).includes(row.key)) cls.push('sm-scr-best');
      }
      if (sel.includes(row.key)) cls.push('sm-scr-sel');
      return cls.join(' ');
    };
  }

  function summaryOutline(ctx, S) {
    const { r } = S;
    const sel = selectedOf(ctx, S);
    const ob = ctx.outline('Summary Across the Models', { key: 'summary', info: 'p:screening:summary', menu: () => selectionItems(ctx, S) });
    const all = r.measure_columns.map((c) => c.key).filter((k) => k !== 'set' && (k !== 'auc' || S.binary));
    const cols = [{ key: 'method', label: 'Method', fmt: 'text' }];
    for (const set of r.shown_sets) cols.push(...measureCols(r, set, all, (k) => !r.summary.includes(k)));
    const rows = r.order.map((key) => rowOf(r.methods.find((m) => m.key === key), r.shown_sets, all));
    const toggle = (row) => { const cur = selectedOf(ctx, S); ctx.set('selected', cur.includes(row.key) ? cur.filter((k) => k !== row.key) : [...cur, row.key]); };
    ob.add(wide(ctx.rt({ columns: cols, rows }, { key: 'summary', onRow: (row) => { if (r.methods.find((m) => m.key === row.key).measures) toggle(row); }, cellClass: bestClass(S, sel) })));
    const btn = (label, action, disabled = false) => { const b = el('button', { type: 'button', class: 'sm-btn small', text: label, 'data-noexport': '' }); b.disabled = disabled; b.addEventListener('click', action); return b; };
    ob.add(el('div', { class: 'sm-scr-actions', 'data-noexport': '' },
      btn('Select Dominant', () => ctx.set('selected', r.dominant.slice())),
      btn('Run Selected', () => runSelected(ctx, S), !sel.some((k) => runnable(ctx, S, k))),
      btn('Clear Selection', () => ctx.set('selected', []), !sel.length)));
    const lab = (k) => MEASURE_LABEL[k] || k;
    const dom = r.dominant.map((k) => labelIn(S, k));
    ob.add(ctx.note(`Best first by the ${r.compare} ${lab(r.summary[0])}; bold marks the best of each column. Dominant on ${r.compare} (no other method is as good on ${r.summary.map(lab).join(', ')} and better on one): ${dom.length ? dom.join(', ') : 'none'}. Click a method to select it; Run Selected opens the selected methods' own platforms with the same roles. Right click the table, Columns, for the other measures.`));
    const bad = r.methods.filter((m) => m.error);
    if (bad.length) ob.add(ctx.warn(`Not fitted: ${bad.map((m) => `${m.label} (${m.error})`).join('; ')}.`));
    const skipped = r.methods.filter((m) => m.cv_error);
    if (skipped.length) ob.add(ctx.warn(`Not crossvalidated: ${skipped.map((m) => `${m.label} (${m.cv_error})`).join('; ')}.`));
  }

  function selectionItems(ctx, S) {
    const sel = selectedOf(ctx, S);
    return [
      { label: 'Select Dominant', action: () => ctx.set('selected', S.r.dominant.slice()) },
      { label: 'Run Selected', disabled: !sel.some((k) => runnable(ctx, S, k)), action: () => runSelected(ctx, S) },
      { label: 'Clear Selection', disabled: !sel.length, action: () => ctx.set('selected', []) },
      { label: 'Select', submenu: () => S.r.order.filter((k) => S.r.methods.find((m) => m.key === k).measures).map((k) => ({ label: labelIn(S, k), checked: sel.includes(k), action: () => ctx.set('selected', sel.includes(k) ? sel.filter((x) => x !== k) : [...sel, k]) })) },
    ];
  }

  /* ---- the per-set tables --------------------------------------------------------------- */
  function setTables(ctx, S) {
    const { r } = S;
    const sel = selectedOf(ctx, S);
    const keys = r.measure_columns.map((c) => c.key).filter((k) => k !== 'set' && (k !== 'auc' || S.binary));
    for (const set of r.sets) {
      const ob = ctx.outline(set, { key: `set:${set}`, info: 'p:screening:sets', closed: set === 'Training' && r.sets.length > 1 });
      const cols = [{ key: 'method', label: 'Method', fmt: 'text' }, ...keys.map((k) => ({ key: `${set}|${k}`, label: MEASURE_LABEL[k] || k, digits: k === 'n' ? null : 4 }))];
      const rows = r.order.map((key) => rowOf(r.methods.find((m) => m.key === key), [set], keys)).filter((x) => r.methods.find((m) => m.key === x.key).measures);
      ob.add(wide(ctx.rt({ columns: cols, rows }, { key: `set:${set}`, cellClass: bestClass(S, sel) })));
    }
  }

  /* ---- K-fold crossvalidation ---------------------------------------------------------------- */
  function cvOutline(ctx, S) {
    const { r } = S;
    const keys = r.measure_columns.map((c) => c.key).filter((k) => k !== 'set' && k !== 'n' && (k !== 'auc' || S.binary));
    const ok = r.order.map((k) => r.methods.find((m) => m.key === k)).filter((m) => m.cv);
    const ob = ctx.outline(CV, { key: 'cv', info: 'p:screening:cv' });
    const cols = [{ key: 'method', label: 'Method', fmt: 'text' }];
    for (const k of keys) cols.push({ key: `m|${k}`, label: MEASURE_LABEL[k], digits: 4 }, { key: `s|${k}`, label: `Std Dev ${MEASURE_LABEL[k]}`, digits: 4, hidden: true });
    const rows = ok.map((m) => ({ key: m.key, method: m.label, ...Object.fromEntries(keys.flatMap((k) => [[`m|${k}`, m.measures[CV][k]], [`s|${k}`, m.cv.sd[k]]])) }));
    const sel = selectedOf(ctx, S);
    ob.add(wide(ctx.rt({ columns: cols, rows }, { key: 'cv', cellClass: (row, c) => {
      const cls = [];
      if (c.key.startsWith('m|') && ((r.best[CV] || {})[c.key.slice(2)] || []).includes(row.key)) cls.push('sm-scr-best');
      if (sel.includes(row.key)) cls.push('sm-scr-sel');
      return cls.join(' ');
    } })), ctx.note(`The mean over the ${r.kfold * r.repeats} held-out folds of each measure (right click, Columns, for their standard deviations). A fold is measured by a model that never saw it, not even to choose its size or penalty.`));
    const fo = ctx.outline('Crossvalidation Folds', { parent: ob, key: 'cvfolds', closed: true });
    const fcols = [{ key: 'method', label: 'Method', fmt: 'text' }, { key: 'repeat', label: 'Repeat', fmt: 'int' }, { key: 'fold', label: 'Fold', fmt: 'int' }, ...keys.map((k) => ({ key: k, label: MEASURE_LABEL[k], digits: 4 })), { key: 'n', label: 'N' }];
    const frows = ok.flatMap((m) => m.cv.folds.map((f) => ({ method: m.label, ...f, repeat: f.repeat + 1, fold: f.fold + 1 })));
    fo.add(wide(ctx.rt({ columns: fcols, rows: frows }, { key: 'cvfolds', maxRows: 400 })));
  }

  /* ---- Method Details ------------------------------------------------------------------------ */
  function detailsOutline(ctx, S) {
    const { r } = S;
    const ob = ctx.outline('Method Details', { key: 'details', info: 'p:screening:methods', closed: true, menu: () => [{ label: 'Remove', action: () => ctx.set('details', false) }] });
    const rows = r.methods.map((m) => ({ method: m.label, info: m.error ? `not fitted: ${m.error}` : m.info, uses: m.uses, seconds: m.seconds ?? null }));
    ob.add(wide(ctx.rt({ columns: [{ key: 'method', label: 'Method', fmt: 'text' }, { key: 'info', label: 'Settings', fmt: 'text' }, { key: 'uses', label: 'scikit-learn', fmt: 'text', hidden: true }, { key: 'seconds', label: 'Seconds', digits: 2, hidden: true }], rows }, { key: 'details', sortable: false })),
      ctx.note('What each method chose: the size of the tree, the number of trees or layers, K, the penalty, the factors. Tuning uses the validation rows when there are any, else each method\'s own rule (see the (i)). The Python below fits every method as the report does, from a CSV export of the table.'),
      ctx.code(r.code));
  }

  /* ======================================================================
     THE COMPARISONS
     ====================================================================== */
  function levelIndex(ctx, S, key) {
    const n = S.r.levels.length;
    const v = ctx.opt(key, null);
    return Number.isInteger(v) && v >= 0 && v < n ? v : (n === 2 ? 1 : 0);
  }

  function curveOutline(ctx, S, kind) {
    const { r } = S;
    const roc = kind === 'roc';
    const optLevel = roc ? 'rocLevel' : 'liftLevel';
    const lv = levelIndex(ctx, S, optLevel);
    const level = r.levels[lv];
    const ob = ctx.outline(roc ? 'ROC Curve' : 'Lift Curve', { key: kind, info: 'p:screening:curves', menu: () => [
      { label: 'Level', submenu: () => r.levels.map((l, i) => ({ label: l, checked: i === lv, action: () => ctx.set(optLevel, i) })) },
      { label: 'Remove', action: () => ctx.set(kind, false) },
    ] });
    const muted = SM.util.themeColors().muted;
    const keys = r.order.filter((k) => r[kind] && r[kind][k]);
    const lg = legendFor(keys.length);
    const plots = r.shown_sets.map((set, si) => {
      const last = si === r.shown_sets.length - 1;
      const traces = [];
      for (const key of keys) {
        const c = r[kind][key].find((x) => x.set === set && x.level === level);
        if (!c) continue;
        traces.push({ type: 'scatter', mode: 'lines', x: roc ? c.fpr : c.portion, y: roc ? c.tpr : c.lift, name: roc ? `${T(labelIn(S, key))} (${c.auc == null ? '.' : c.auc.toFixed(3)})` : T(labelIn(S, key)),
          line: { color: colorOf(key), width: 1.6 }, hovertemplate: `${T(labelIn(S, key))}<br>%{x:.3f}, %{y:.3f}<extra></extra>` });
      }
      traces.push({ type: 'scatter', mode: 'lines', x: [0, 1], y: roc ? [0, 1] : [1, 1], line: { color: muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false });
      // the legend once, on the last graph: the colours are the same in every graph
      return ctx.plot(traces, {
        showlegend: last, legend: lg.legend, title: { text: set, font: { size: 12 } }, margin: { l: 50, r: 8, t: 28, b: lg.bottom },
        xaxis: { title: { text: roc ? '1 - Specificity' : 'Portion' }, range: [0, 1] }, yaxis: roc ? { title: { text: 'Sensitivity' }, range: [0, 1.01] } : { title: { text: 'Lift' } },
      }, { width: last ? lg.width : W(360), height: last ? lg.height : 330, title: `${roc ? 'ROC' : 'Lift'} ${set} ${level}`, select: false });
    });
    ob.add(ctx.row(...plots));
    if (roc) {
      const cols = [{ key: 'method', label: 'Method', fmt: 'text' }, ...r.shown_sets.map((s) => ({ key: s, label: `${s} AUC`, digits: 4 }))];
      const rows = keys.map((key) => ({ method: labelIn(S, key), ...Object.fromEntries(r.shown_sets.map((s) => { const c = r.roc[key].find((x) => x.set === s && x.level === level); return [s, c ? c.auc : null]; })) }));
      ob.add(wide(ctx.rt({ columns: cols, rows }, { key: `auc:${level}` })));
    }
    ob.add(ctx.note(roc
      ? `${level} against the other level${r.levels.length > 2 ? 's' : ''}, every method on one graph per set${r.kfold ? ' (Crossvalidation: each row predicted by the model that did not see its fold, first repeat)' : ''}: the share of ${level} rows caught against the share of the others caught as the cut on the probability of ${level} falls. Level (red triangle) picks another level.`
      : `The rows taken highest probability of ${level} first: how many times more common ${level} is among them than in the whole set, for every method.`));
  }

  /* Actual by predicted, a small graph per method, the points linked to their rows. */
  function abpOutline(ctx, S) {
    const { r } = S;
    const res = r.residuals;
    let set = ctx.opt('abpSet', r.compare);
    if (!r.shown_sets.includes(set)) set = r.compare;
    const ob = ctx.outline('Actual by Predicted', { key: 'abp', info: 'p:screening:abp', menu: () => [
      { label: 'Set', submenu: () => r.shown_sets.map((s) => ({ label: s, checked: s === set, action: () => ctx.set('abpSet', s) })) },
      { label: 'Remove', action: () => ctx.set('abp', false) },
    ] });
    const k = ['Training', 'Validation', 'Test'].indexOf(set);
    const idx = res.set.map((s, i) => ((set === CV || s === k) ? i : -1)).filter((i) => i >= 0);
    const muted = SM.util.themeColors().muted;
    const keys = r.order.filter((key) => (set === CV ? res.oof[key] : res.predicted[key]));
    const n = idx.length;
    const type = n > 2000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter';
    const plots = keys.map((key) => {
      const pred = set === CV ? res.oof[key] : res.predicted[key];
      const xs = idx.map((i) => pred[i]), ys = idx.map((i) => res.actual[i]);
      let lo = Infinity, hi = -Infinity;
      for (const v of [...xs, ...ys]) if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
      return ctx.plot([
        { type, mode: 'markers', x: xs, y: ys, rows: idx.map((i) => res.rows[i]), marker: { size: n > 1500 ? 3 : 4.5 }, name: T(labelIn(S, key)) },
        { type: 'scatter', mode: 'lines', x: [lo, hi], y: [lo, hi], line: { color: muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false },
      ], { title: { text: T(labelIn(S, key)), font: { size: 11 } }, margin: { l: 46, r: 8, t: 26, b: 36 }, xaxis: { title: { text: 'Predicted', font: { size: 10 } } }, yaxis: { title: { text: 'Actual', font: { size: 10 } } } },
      { width: W(250), height: 235, title: `Actual by predicted ${labelIn(S, key)} ${set}` });
    });
    ob.add(ctx.row(...plots), ctx.note(`${set} rows${set === CV ? ', each predicted by the model fitted without its fold (first repeat)' : ''}: the actual ${S.yc.name} against each method's prediction; points on the dotted line are predicted exactly. Drag over points to select their rows; Set (red triangle) shows another set.`));
  }

  /* ---- Decision Threshold (two levels) ------------------------------------------------------ */
  async function thresholdOutline(ctx, S) {
    const { r } = S;
    const lv = levelIndex(ctx, S, 'cutLevel');
    let cut = Number(ctx.opt('cut', 0.5));
    if (!(cut >= 0 && cut <= 1)) cut = 0.5;
    const ob = ctx.outline('Decision Threshold', { key: 'threshold', info: 'p:screening:threshold', menu: () => [
      { label: 'Target Level', submenu: () => r.levels.map((l, i) => ({ label: l, checked: i === lv, action: () => ctx.set('cutLevel', i) })) },
      { label: 'Set Threshold…', action: async () => { const v = await SM.ui.form({ title: 'Decision Threshold', fields: [{ key: 't', label: `Probability of ${r.levels[lv]} at or above which a row is called ${r.levels[lv]}`, type: 'number', value: cut }], validate: (x) => (x.t >= 0 && x.t <= 1 ? null : 'The threshold is a probability, from 0 to 1') }); if (v) ctx.set('cut', v.t); } },
      { label: 'Remove', action: () => ctx.set('threshold', false) },
    ] });
    const t = await ctx.call('screening.threshold', { ...S.spec, methods: S.pay.methods, repeats: S.pay.repeats, cut, level: lv });
    const input = el('input', { type: 'text', inputmode: 'decimal', size: 6, class: 'sm-scr-input', 'aria-label': 'Probability threshold' });
    input.value = String(cut);
    const apply = () => { const v = SM.table.toNumber(input.value.replace(',', '.')); if (v >= 0 && v <= 1) ctx.set('cut', v); else SM.ui.toast('The threshold is a probability, from 0 to 1', { error: true }); };
    input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); apply(); } });
    const go = el('button', { type: 'button', class: 'sm-btn small', text: 'Apply' });
    go.addEventListener('click', apply);
    ob.add(el('div', { class: 'sm-scr-cut', 'data-noexport': '' }, el('label', null, el('span', { text: `Probability threshold for ${t.level}` }), input), go));
    const ok = r.order.map((k) => t.methods.find((m) => m.key === k)).filter((m) => m && !m.error);
    const sets = Object.keys(ok[0] ? ok[0].sets : {});
    const rate = [['sensitivity', 'Sensitivity'], ['specificity', 'Specificity'], ['precision', 'Precision'], ['misclassification', 'Misclassification Rate'], ['f1', 'F1 Score']];
    const counts = [['tp', 'True Positive'], ['fp', 'False Positive'], ['fn', 'False Negative'], ['tn', 'True Negative']];
    for (const set of sets) {
      const cols = [{ key: 'method', label: 'Method', fmt: 'text' }, ...rate.map(([k, l]) => ({ key: k, label: l, digits: 4 })), ...counts.map(([k, l]) => ({ key: k, label: l, hidden: true }))];
      ob.add(wide(ctx.rt({ columns: cols, rows: ok.map((m) => ({ method: m.label, ...m.sets[set] })) }, { key: `cut:${set}`, caption: `${set}: ${t.level} when its probability ≥ ${fmt(cut)}` })));
    }
    const muted = SM.util.themeColors().muted;
    const cmp = sets.includes(r.compare) ? r.compare : sets[0];
    const traces = ok.map((m) => ({ type: 'scatter', mode: 'lines', x: t.grid, y: m.curves[cmp], name: T(m.label), line: { color: colorOf(m.key), width: 1.5 }, hovertemplate: `${T(m.label)}<br>threshold %{x:.2f}: %{y:.4f}<extra></extra>` }));
    const vline = { type: 'line', x0: cut, x1: cut, yref: 'paper', y0: 0, y1: 1, line: { color: muted, width: 1.2, dash: 'dash' } };
    const pick = (gd) => gd.on('plotly_click', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt && Number.isFinite(pt.x)) ctx.set('cut', Math.round(pt.x * 100) / 100); });
    const lg = legendFor(ok.length);
    ob.add(ctx.row(ctx.plot(traces, { showlegend: true, legend: lg.legend, shapes: [vline], hovermode: 'closest', margin: { l: 54, r: 8, t: 26, b: lg.bottom + 2 },
      title: { text: `${cmp}: misclassification by threshold`, font: { size: 12 } }, xaxis: { title: { text: `Threshold on the probability of ${T(t.level)}` }, range: [0, 1] }, yaxis: { title: { text: 'Misclassification Rate' }, rangemode: 'tozero' } },
    { width: lg.width, height: lg.height, title: 'Misclassification by threshold', select: false, onDraw: pick })),
    ctx.note(`A row is called ${t.level} when its predicted probability of ${t.level} is at least the threshold. Sensitivity is the share of ${t.level} rows called ${t.level}, specificity the share of the others called the other level, precision the share of the rows called ${t.level} that are. Click the graph, or type a threshold, to move it; the counts are by the rows' frequencies (right click, Columns).`));
  }

  /* ======================================================================
     RUN SELECTED: each method's own platform, with the same roles
     ====================================================================== */
  function targetOf(ctx, S, key) {
    const id = PLATFORM[key];
    const p = id ? SM.platforms.get(id) : null;
    if (!p) return null;
    const cat = S.yc.isCategorical;
    if (id === 'fitmodel') {
      if (key === 'stepwise' && cat) return null;
      if ((key === 'lasso' || key === 'enet') && cat && S.r.levels.length > 2) return null;
    }
    if (id === 'discriminant' && !S.xs.some((c) => !c.isCategorical)) return null;
    return p;
  }

  const runnable = (ctx, S, key) => !!targetOf(ctx, S, key);

  function specFor(ctx, S, key, p) {
    const ids = (k) => (ctx.spec.roles[k] || []).slice();
    const { yc, xs, spec } = S;
    if (p.id === 'fitmodel') {
      const effects = xs.map((c) => ({ cols: [c.id], names: [c.name], nest: [], nestNames: [], random: false }));
      const pers = key === 'stepwise' ? 'stepwise' : (key === 'lasso' || key === 'enet') ? 'genreg' : !yc.isCategorical ? 'standard' : (yc.modelingType === 'ordinal' ? 'ordinal' : 'nominal');
      const options = { personality: pers };
      if (pers === 'genreg') Object.assign(options, { dist: yc.isCategorical ? 'binomial' : 'normal', 'gr:method': key === 'enet' ? 'enet' : 'lasso' });
      return { roles: { y: [yc.id], weight: ids('weight'), freq: ids('freq'), by: ids('by') }, effects, options };
    }
    if (p.id === 'discriminant') return { roles: { y: xs.filter((c) => !c.isCategorical).map((c) => c.id), x: [yc.id], weight: ids('weight'), freq: ids('freq'), by: ids('by') }, options: {} };
    return {
      roles: { y: [yc.id], x: xs.map((c) => c.id), weight: ids('weight'), freq: ids('freq'), validation: ids('validation'), by: ids('by') },
      options: { portion: spec.portion, missing: spec.missing === 'informative', seed: String(spec.seed) },
    };
  }

  function runSelected(ctx, S) {
    const sel = selectedOf(ctx, S);
    const opened = [], skipped = [];
    for (const key of sel) {
      const p = targetOf(ctx, S, key);
      if (!p) { skipped.push(labelIn(S, key)); continue; }
      SM.app.openReport(p, specFor(ctx, S, key, p), ctx.table);
      opened.push(labelIn(S, key));
    }
    if (!opened.length) SM.ui.toast(sel.length ? `No platform here runs ${skipped.join(', ')} yet` : 'Select methods first: click them in the Summary, or Select Dominant', { error: !!sel.length });
    else if (skipped.length) SM.ui.toast(`Opened ${opened.join(', ')}; no platform here runs ${skipped.join(', ')}`);
  }

  /* ======================================================================
     THE TOP RED TRIANGLE
     ====================================================================== */
  function topMenu(ctx) {
    const S = ctx.scr;
    if (!S) return [];
    const { r } = S;
    const ok = r.order.filter((k) => r.methods.find((m) => m.key === k).measures);
    const prof = ctx.opt('profiler', false);
    const items = [...selectionItems(ctx, S), { separator: true }];
    if (r.kind === 'categorical') {
      items.push(ctx.check('ROC Curve', 'roc', null, false), ctx.check('Lift Curve', 'lift', null, false));
      if (S.binary) items.push(ctx.check('Decision Threshold', 'threshold', null, false));
    } else items.push(ctx.check('Actual by Predicted', 'abp', null, false));
    items.push({ label: 'Profiler', submenu: () => ok.map((k) => ({ label: labelIn(S, k), checked: prof === k, action: () => ctx.set('profiler', prof === k ? false : k) })) });
    items.push(ctx.check('Method Details', 'details', null, true));
    items.push({ separator: true });
    items.push({ label: 'Save Columns', submenu: () => ok.map((k) => ({ label: labelIn(S, k), submenu: () => SM.predict.saveItems(ctx, 'screening.save', { ...S.spec, method: k }, { kind: r.kind })[0].submenu() })) });
    return items;
  }

  /* ======================================================================
     THE LAUNCH DIALOG'S OWN PART: the methods, and K-fold crossvalidation
     ====================================================================== */
  function launchExtra(api, spec) {
    const o = (spec && spec.options) || {};
    const want = new Set(Array.isArray(o.methods) ? o.methods : DEFAULT);
    const checks = METHODS.map(([key, label]) => {
      const i = el('input', { type: 'checkbox', value: key });
      i.checked = want.has(key);
      const span = el('span', { text: label });
      return { key, i, span, lab: el('label', { class: 'sm-scr-check' }, i, span) };
    });
    const kf = el('input', { type: 'checkbox' });
    kf.checked = !!o.kfold;
    const num = (v, aria) => { const i = el('input', { type: 'text', inputmode: 'numeric', size: 3, class: 'sm-scr-input', 'aria-label': aria }); i.value = String(v); return i; };
    const folds = num(o.folds ?? 5, 'Folds'), reps = num(o.repeats ?? 1, 'Repeated K Fold');
    const hint = el('p', { class: 'sm-scr-hint' });
    const box = el('div', { class: 'sm-scr-launch' },
      el('h4', { text: 'Method' }), el('div', { class: 'sm-scr-checks' }, ...checks.map((c) => c.lab)),
      el('div', { class: 'sm-scr-opts' },
        el('label', { class: 'sm-scr-check' }, kf, el('span', { text: 'K Fold Crossvalidation' })),
        el('label', { class: 'sm-scr-opt' }, el('span', { text: 'Folds' }), folds),
        el('label', { class: 'sm-scr-opt' }, el('span', { text: 'Repeated K Fold' }), reps)),
      hint);
    const update = (state) => {
      const id = ((state && state.y) || [])[0];
      const c = id ? api.table.col(id) : null;
      const cat = c ? c.isCategorical : null;
      for (const ch of checks) {
        ch.lab.classList.toggle('is-off', cat === false && CAT_ONLY.has(ch.key));
        if (ch.key === 'linear') ch.span.textContent = cat ? (c.modelingType === 'ordinal' ? 'Ordinal Logistic' : 'Logistic Regression') : 'Fit Least Squares';
      }
      const hasV = ((state && state.validation) || []).length > 0;
      kf.disabled = hasV;
      folds.disabled = reps.disabled = hasV || !kf.checked;
      hint.textContent = hasV ? 'The Validation column gives the sets; K-fold crossvalidation is not used with one.'
        : kf.checked ? 'Each method is fitted once to every row and once per fold to the others; the Validation Portion is not used.'
          : cat === false ? 'Naive Bayes and Discriminant are for a categorical Y.' : 'Without a Validation column or K-fold crossvalidation, the Validation Portion holds rows back.';
    };
    kf.addEventListener('change', () => update(api.state));
    api.onRolesChange(update);
    update(api.state);
    return {
      el: box,
      read: () => ({ options: { methods: checks.filter((c) => c.i.checked).map((c) => c.key), kfold: kf.checked, folds: Number(folds.value.trim()), repeats: Number(reps.value.trim()) } }),
      recall: (saved) => {
        const so = (saved && saved.options) || {};
        if (Array.isArray(so.methods)) for (const c of checks) c.i.checked = so.methods.includes(c.key);
        if (so.kfold != null) kf.checked = !!so.kfold;
        if (so.folds != null) folds.value = String(so.folds);
        if (so.repeats != null) reps.value = String(so.repeats);
        update(api.state);
      },
    };
  }

  function validate(spec, table) {
    const o = spec.options || {};
    const y = table.col((spec.roles.y || [])[0]);
    const m = (Array.isArray(o.methods) ? o.methods : DEFAULT).filter((k) => !y || y.isCategorical || !CAT_ONLY.has(k));
    if (!m.length) return 'Method: choose at least one that fits this Y';
    if (o.kfold && !(spec.roles.validation || []).length) {
      if (!(Number.isInteger(o.folds) && o.folds >= 2 && o.folds <= 20)) return 'Folds: a whole number from 2 to 20';
      if (!(Number.isInteger(o.repeats) && o.repeats >= 1 && o.repeats <= 10)) return 'Repeated K Fold: a whole number from 1 to 10';
    }
    const por = o.portion;
    if (por != null && !(por >= 0 && por < 1)) return 'Validation Portion: a share from 0 up to (not including) 1';
    return null;
  }

  /* ======================================================================
     MAKE VALIDATION COLUMN (Analyze > Predictive Modeling, Cols > Modeling Utilities)
     ====================================================================== */
  function makeValidationColumn(app) {
    const t = app.requireTable();
    if (!t) return;
    const platform = {
      id: 'screening-validation', label: 'Make Validation Column', info: 'cmd:makevalidation',
      launch: {
        lead: 'A new column that puts every row of the table in the training, validation or test set, for the Validation role of the predictive platforms. With no columns cast, the rows are assigned at random.',
        roles: [
          { key: 'strata', label: 'Stratification Columns', hint: 'optional: the proportions within each level' },
          { key: 'groups', label: 'Grouping Columns', hint: 'optional: all rows of a group in one set' },
          { key: 'time', label: 'Cutpoint Column', max: 1, numeric: true, hint: 'optional: a time column; the earliest rows train' },
        ],
        options: [
          { key: 'training', label: 'Training Set', type: 'number', value: 0.6 },
          { key: 'validation', label: 'Validation Set', type: 'number', value: 0.2 },
          { key: 'test', label: 'Test Set', type: 'number', value: 0.2 },
          { key: 'seed', label: 'Random Seed', type: 'text', value: '', size: 10, hint: 'empty: a seed drawn now (the column\'s notes keep it)' },
          { key: 'values', label: 'Values', type: 'select', value: 'text', choices: [['text', 'Training, Validation, Test'], ['numeric', '0, 1, 2']] },
          { key: 'name', label: 'New Column Name', type: 'text', value: 'Validation', size: 12 },
        ],
        extra: (api) => {
          const hint = el('p', { class: 'sm-scr-hint' });
          const upd = (st) => {
            const k = ['strata', 'groups', 'time'].filter((x) => ((st && st[x]) || []).length);
            hint.textContent = k.length > 1 ? 'Use one kind: stratification columns, grouping columns or a cutpoint column.'
              : k[0] === 'strata' ? 'Stratified random: the proportions hold within each combination of the stratification columns\' levels, and in total.'
                : k[0] === 'groups' ? 'Grouped random: the groups in random order, each wholly in one set, so the proportions of rows are near but not exact.'
                  : k[0] === 'time' ? 'Cutpoint: the rows in time order, the earliest to training, then validation, then test; rows at the same time stay together.'
                    : 'Random: exactly the proportions of the rows (rounded to whole rows), in random order.';
          };
          api.onRolesChange(upd);
          upd(api.state);
          return { el: hint, read: () => ({}) };
        },
        validate: (s) => {
          const o = s.options;
          const k = ['strata', 'groups', 'time'].filter((x) => (s.roles[x] || []).length);
          if (k.length > 1) return 'Use one kind: stratification columns, grouping columns or a cutpoint column';
          const p = [o.training, o.validation, o.test];
          if (p.some((v) => v != null && !(v >= 0))) return 'The proportions are 0 or more';
          if (!(o.training > 0)) return 'Training Set: a proportion above 0';
          if (!String(o.name || '').trim()) return 'New Column Name: give a name';
          if (String(o.seed || '').trim() && !Number.isFinite(Number(o.seed))) return 'Random Seed: a whole number, or empty';
          return null;
        },
      },
    };
    SM.launch.open({ platform, table: t, onOK: (s) => { runMakeValidation(app, t, s).catch((e) => SM.ui.toast(`Make Validation Column: ${e.message || e}`, { error: true })); } });
  }

  async function runMakeValidation(app, t, s) {
    const names = (k) => (s.roles[k] || []).map((id) => t.col(id)).filter(Boolean).map((c) => c.name);
    const o = s.options;
    if (SM.engine.state !== 'ready') SM.ui.toast('Waiting for the Python engine to load…');
    const r = await SM.engine.call('screening.validation_column', {
      training: o.training ?? 0, validation: o.validation ?? 0, test: o.test ?? 0, strata: names('strata'), groups: names('groups'), time: names('time')[0] || null,
      seed: String(o.seed || '').trim() || null, values: o.values, name: String(o.name).trim(),
    }, t);
    const text = o.values === 'text';
    if (app.record) app.record(t, 'Make Validation Column');
    const c = t.addColumn({
      name: String(o.name).trim(), dataType: text ? 'character' : 'numeric', modelingType: 'nominal',
      values: r.values.map((v) => (v == null ? (text ? null : NaN) : v)), valueOrder: text ? ['Training', 'Validation', 'Test'] : [0, 1, 2],
      notes: `${r.notes}\n\nThe same column from a CSV export of the table (Python):\n${r.code}`,
    });
    SM.ui.toast(`Made ${c.name}: ${r.counts[0]} training, ${r.counts[1]} validation, ${r.counts[2]} test rows (seed ${r.seed})`);
    return c;
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:screening': {
      kicker: 'Analyze > Predictive Modeling', title: 'Model Screening',
      lead: 'Fits many kinds of predictive model to one response, with the same rows, the same training, validation and test sets and the same seed, and puts their measures of fit side by side, as JMP Pro\'s Model Screening does. The models are scikit-learn\'s (and a few written here); the measures are those every predictive platform here reports.',
      sections: [
        { heading: 'Roles', choices: [['Y, Response', 'One column: continuous, or nominal or ordinal for a classification.'], ['X, Factor', 'The predictors; a categorical factor becomes a 0/1 column per level.'], ['Weight, Freq', 'Case weights and row counts, in every method that takes them (K Nearest Neighbors weights its neighbours).'], ['Validation', 'A column of Training/Validation/Test (or 0, 1, 2): its sets win over the portion and K-fold.'], ['By', 'A screening per level.']] },
        { heading: 'Validation', choices: [['Validation column', 'Its training rows fit, its validation rows tune and compare, its test rows only measure.'], ['Validation Portion', 'With no column, that random share of the rows is held back to tune and compare (0.2 here).'], ['K Fold Crossvalidation', 'The rows split into folds (5), each held out once from a fit to the others; Repeated K Fold draws new folds. The measures are the means over the held-out folds.']] },
        { heading: 'The methods', text: 'Decision Tree, Bootstrap Forest, Boosted Tree, K Nearest Neighbors, Naive Bayes and Discriminant (categorical Y), Neural, Support Vector Machines, Fit Least Squares or Nominal / Ordinal Logistic, Generalized Regression Lasso and Elastic Net, and Fit Stepwise (off by default). Method Details (i) says how each is fitted and where it differs from JMP.' },
      ],
      more: MORE,
    },
    'p:screening:summary': {
      kicker: 'Model Screening', title: 'Summary Across the Models',
      lead: 'A line per method: RSquare and RASE (continuous Y), or Entropy RSquare, the Misclassification Rate and for two levels the AUC, for each set. The methods are ranked by the validation measure (the crossvalidated one with K-fold, the training one with neither); bold marks the best of each column.',
      sections: [
        { heading: 'Selecting', choices: [['Click a line', 'Selects the method (or takes it out again).'], ['Select Dominant', 'Selects the methods that no other method matches or beats on every measure shown while beating on one.'], ['Run Selected', 'Opens each selected method\'s own platform (Partition, Bootstrap Forest, Neural, …, Fit Model for the linear ones) with the same Y, X, Weight, Freq, Validation and By, the same Validation Portion and seed; a method whose platform is not here is left out.']] },
        { heading: 'More measures', text: 'Right click the table, Columns: Generalized RSquare, Mean -Log p, Mean Abs Dev, -LogLikelihood, SSE and N of each set.' },
      ],
      more: MORE,
    },
    'p:screening:sets': { kicker: 'Model Screening', title: 'Training, Validation and Test', lead: 'Every Measure of Fit of every method for the rows of one set (see Measures of Fit). Training measures flatter flexible methods: compare them on validation or test rows.', more: MORE },
    'p:screening:cv': {
      kicker: 'Model Screening', title: 'K-fold Crossvalidation',
      lead: 'The training rows are split at random (from the seed) into K folds of nearly equal size. Each method is fitted K times, each time to all folds but one, and measured on the fold left out; the table gives the mean over the folds (and their standard deviation). Repeated K Fold does it again with new folds.',
      sections: [{ heading: 'Honest folds', text: 'Inside a fold a method tunes itself without the held-out rows: the tree by crossvalidation within the other folds, K Nearest Neighbors by leave-one-out, Neural by a holdback, Generalized Regression by AICc, Stepwise by BIC. The Training measures are of the methods fitted once to every row.' }],
      more: MORE,
    },
    'p:screening:methods': {
      kicker: 'Model Screening', title: 'How each method is fitted',
      lead: 'Each method as JMP\'s platform fits it by default, as far as scikit-learn allows. Tuning uses the validation rows when there are any; otherwise the rule named. Categorical factors are 0/1 columns (one level left out for the linear methods), missing values informative when that option is on.',
      sections: [{ choices: [
        ['Decision Tree', 'Splits made best first (squared error; entropy for a categorical Y), no leaf under 5 rows, up to 64 leaves; the number of splits by the validation rows or 5-fold crossvalidation. JMP splits by LogWorth; its leaf rates carry a prior, as here (one row spread as the training shares).'],
        ['Bootstrap Forest', '100 trees on bootstrap samples, a third of the columns tried at each split (the square root of their number for a categorical Y), leaves of 5 rows or more; with validation rows the best of 10, 20, …, 100 trees. JMP\'s default number of terms sampled may differ.'],
        ['Boosted Tree', '50 layers of trees with 3 splits, learning rate 0.1, leaves of 5 or more; with validation rows the number of layers with the best validation measure. JMP\'s overfit penalty is not here.'],
        ['K Nearest Neighbors', 'Standardized columns; K from 1 to 10 by the validation error (the misclassification rate for a categorical Y), else leave-one-out. The level rates carry a prior of one row, so no probability is 0 or 1.'],
        ['Naive Bayes', 'Normal continuous factors (scikit-learn GaussianNB), categorical ones by their level shares with one row added (CategoricalNB).'],
        ['Neural', 'One layer of 3 tanh nodes on standardized columns, L-BFGS, a squared penalty of 0.001, 0.01 or 0.1 chosen by the validation rows or a holdback of a third. JMP\'s tours and transforms are not here.'],
        ['Support Vector Machines', 'RBF kernel, cost 1, gamma 1/(number of columns), standardized columns; probabilities from Platt\'s sigmoid fitted to the training decision values (scikit-learn\'s own fits it on crossvalidated ones, five times slower).'],
        ['Discriminant', 'Linear: one covariance matrix pooled within the levels (n - levels degrees of freedom), priors the training shares.'],
        ['Fit Least Squares, Logistic', 'The main effects by least squares; a nominal Y by multinomial logistic regression, an ordinal one by the cumulative logit, both by maximum likelihood.'],
        ['Generalized Regression', 'The lasso and the elastic net (alpha 0.9, as Fit Model here) on centred and scaled columns, the penalty by the validation rows or the smallest AICc; JMP\'s adaptive versions are not here.'],
        ['Fit Stepwise', 'Forward selection of whole factors, the step with the smallest BIC or the best validation measure.'],
      ] }],
      more: MORE,
    },
    'p:screening:curves': { kicker: 'Model Screening', title: 'ROC and Lift Curves', lead: 'Every method\'s curve for one level on one graph per set, so that the methods can be compared where it matters: the ROC curve (the share of the level\'s rows caught against the share of the others as the cut on its probability falls; the AUC in the legend and the table) and the lift (how much more common the level is among the rows it scores highest). Level (red triangle) picks the level.', more: MORE },
    'p:screening:abp': { kicker: 'Model Screening', title: 'Actual by Predicted', lead: 'A small graph per method of the actual response against the prediction, for one set; the points are the rows (drag to select them). A good model keeps them near the dotted line on the validation rows, not only on the training rows.', more: MORE },
    'p:screening:threshold': {
      kicker: 'Model Screening', title: 'Decision Threshold',
      lead: 'For a response with two levels: a row is called the target level when its predicted probability of it is at least the threshold. At the threshold, each method\'s sensitivity, specificity, precision, misclassification rate and F1 score per set, and the counts (right click, Columns); the graph shows the misclassification rate of every threshold. JMP Pro 17\'s Decision Threshold report shows more (the counts as bars, a profit matrix); this is its core.',
      more: MORE,
    },
    'cmd:makevalidation': {
      kicker: 'Analyze > Predictive Modeling', title: 'Make Validation Column',
      lead: 'Adds a column that puts every row in the training, validation or test set, which the predictive platforms take in their Validation role. The proportions are rounded to whole rows by largest remainders (each set gets the floor of its share, the rows left over go to the largest fractions), so the counts are exact, not random; which rows go where is random, from the seed.',
      sections: [
        { heading: 'Methods', choices: [['Random', 'No columns cast: the rows in random order, the first ones training, then validation, then test.'], ['Stratified', 'Stratification Columns: the proportions within every combination of their levels (a missing value is a level), each stratum\'s counts rounded down or up so that the totals are still the random method\'s.'], ['Grouped', 'Grouping Columns: every row of a group in the same set; the groups in random order, each to the set its middle row falls in, so the shares of rows are close to the proportions.'], ['Cutpoint', 'A time column: no randomness, the earliest rows train, the next validate, the latest test; rows with the same time stay together, rows without one get no set.']] },
        { heading: 'The column', text: 'Training, Validation, Test (text, in that order) or 0, 1, 2 (numeric), nominal. JMP makes a numeric column with value labels, which this page\'s tables do not have. The column\'s notes keep the method, the seed, the counts and the Python (numpy) that makes the same column from a CSV export.' },
      ],
    },
  };

  /* ======================================================================
     THE PLATFORM AND THE COMMAND
     ====================================================================== */
  SM.platforms.register({
    id: 'screening', label: 'Model Screening', menu: 'Analyze/Predictive Modeling', order: 90, info: 'p:screening', topics: TOPICS,
    about: 'JMP Pro\'s Model Screening: Decision Tree, Bootstrap Forest, Boosted Tree, K Nearest Neighbors, Naive Bayes, Neural, Support Vector Machines, Discriminant, Fit Least Squares or Nominal / Ordinal Logistic, Generalized Regression (lasso and elastic net) and Fit Stepwise fitted to the same rows, sets and seed, with a holdback, a Validation column or repeated K-fold crossvalidation; the Summary Across the Models with the best of each measure marked, Select Dominant and Run Selected, the training, validation and test tables, ROC and lift curves and actual by predicted of every method, the Decision Threshold of two levels, the Prediction Profiler and Save Columns of any method, and the Python that fits them all.',
    uses: ['sklearn.tree.DecisionTreeClassifier, DecisionTreeRegressor', 'sklearn.ensemble.RandomForestClassifier, RandomForestRegressor, GradientBoostingClassifier, GradientBoostingRegressor', 'sklearn.neighbors.NearestNeighbors', 'sklearn.naive_bayes.GaussianNB, CategoricalNB', 'sklearn.neural_network.MLPClassifier, MLPRegressor', 'sklearn.svm.SVC, SVR, l1_min_c', 'sklearn.linear_model.LinearRegression, LogisticRegression, enet_path', 'scipy.optimize.minimize (the cumulative logit, Platt\'s sigmoid)', 'scipy.linalg.pinvh (the discriminant)'],
    launch: {
      lead: 'Choose one Y and the X factors, and the methods to compare. Each method is fitted to the same training rows and measured on the same validation and test rows.',
      roles: [
        { key: 'y', label: 'Y, Response', min: 1, max: 1, hint: 'required: continuous, nominal or ordinal' },
        { key: 'x', label: 'X, Factor', min: 1, hint: 'required' },
        ...SM.predict.roles(),
      ],
      options: SM.predict.options({ portion: 0.2 }),
      extra: launchExtra,
      validate,
    },
    title: (spec, table) => {
      const c = table && (spec.roles.y || [])[0] ? table.col(spec.roles.y[0]) : null;
      return c ? `Model Screening for ${c.name}` : 'Model Screening';
    },
    triangle: topMenu,
    render,
  });

  const hasTable = (app) => !!app.current;
  SM.commands.register({ menu: 'Analyze/Predictive Modeling', label: 'Make Validation Column…', order: 190, enabled: hasTable, action: makeValidationColumn, about: 'A column that puts every row in training, validation or test: random, stratified, grouped or by a time cutpoint, exact to the proportions', uses: ['numpy.random.default_rng'] });
  SM.commands.register({ menu: 'Cols/Modeling Utilities', label: 'Make Validation Column…', order: 10, enabled: hasTable, action: makeValidationColumn, about: 'The same as Analyze > Predictive Modeling > Make Validation Column' });

  SM.screening = Object.freeze({ METHODS, PLATFORM, makeValidationColumn, runMakeValidation, specFor });
}(typeof self !== 'undefined' ? self : this));
