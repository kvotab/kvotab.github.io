/* ==========================================================================
   SMUI.HTML: WHAT THE PREDICTIVE PLATFORMS SHARE

   Partition, Decision Forest, Boosted Tree, Neural, K Nearest Neighbors,
   Naive Bayes, Support Vector Machines, Gaussian Process and Fit Many
   Models share their launch roles and options and parts of their
   reports. The backend side is resources/py/smui/predictive.py
   (prepare(), report(), saved(), threshold()).

     launch: { roles: [yRole, xRole, ...SM.predict.roles()],
               options: SM.predict.options() }
     const base = { y, x, ...SM.predict.payload(ctx) };  // weight, freq, validation, portion, seed, missing
     const r = await ctx.call('partition.fit', base);   // r.fit = predictive.report(P, fitted)
     SM.predict.measures(ctx, parent, r.fit);
     SM.predict.classification(ctx, parent, r.fit, scope, prefix, { save: { fn: 'partition.save', payload: base } });
                             // confusion, ROC, lift, and (options) Decision Threshold, Group Metrics
     SM.predict.actualByPredicted(ctx, parent, r.fit);
     SM.predict.contributions(ctx, parent, r.contributions);
     ...SM.predict.classificationItems(ctx, r.fit, scope)   // red-triangle items
     ...SM.predict.saveItems(ctx, 'partition.save', base, r.fit)

   A platform that draws confusion, ROC and lift itself (Decision Forest)
   calls SM.predict.decisionParts(ctx, parent, fit, scope, prefix, opts)
   after them for the Decision Threshold and Group Metrics.

   DECISION THRESHOLD, for any platform with probabilities of two levels
   (Fit Model's and Bivariate Analysis's logistic fits, Discriminant, Penalized
   Regression, Model Comparison, Uplift):

     Python: r['threshold'] = predictive.threshold(y, prob, levels, sets, w, rows, head=code_head_lines)
             (docstring there: y the level index 0/1, prob n x 2 or {key: (label, probs)})
     page:   SM.predict.threshold(ctx, parent, r.threshold, { scope, prefix, probName, save, yCol, title })
             -> the outline, or null; shown when the platform's option is on
             (SM.predict.thresholdItem(ctx, scope) is the red-triangle check,
             option 'threshold').

   It shows, per set, the fitted probability of the target level by the
   actual level with the threshold (drag it, type it, or use the slider),
   the counts and rates at the threshold, the measures (accuracy,
   sensitivity, specificity, precision, F1, FPR, FNR, MCC, ...), their
   curves against the threshold, and with a Profit Matrix (the Y column's
   property) the profit; Save Threshold Formula makes an If on the Prob[]
   column. Everything at the threshold is worked out here from each row's
   probability (cutTable, countsAt, ratesAt, as predictive.cut_table,
   counts_at and rates_at do), so a new threshold needs no call. As in
   JMP each By group has its own threshold, target level and true event
   rate: SM.predict.thresholdOption(ctx, 'dtLevel', dflt, scope) reads
   the group's (a group without its own takes the report's), and
   setThresholdOption sets it for the group only.
   GROUP METRICS of the same data: SM.predict.groupMetrics(ctx, parent, D,
   opts), shown with the option 'groupMetrics' (the column's id, set by
   SM.predict.groupMetricsItem(ctx, scope) in a red triangle); of named
   models (Fit Many Models' methods) a line per model and group.
   SCORE ROWS, for a platform without a Save Prediction Formula (K Nearest
   Neighbors, Support Vector Machines, Decision Forest, Boosted Tree):
     SM.predict.scoreRows(ctx, { fn: 'knn.score', payload: { ...base, keep }, fit, yName, info })
   the dialog, the engine's scores of the rows of an open table by the
   model it kept, and those written to that table.

   The seed: the launch's Random Seed, or one drawn at the first run and
   kept with the report (so a redraw, Redo and a project give the same
   holdback and the same model).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const SETS = ['Training', 'Validation', 'Test'];
  const CV = 'Crossvalidation';

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

  /* The light theme's colours in the graphs' code (the page's PALETTE, BASE, MUTED, the profiler's red). */
  const PY = { muted: '#786b5d', text: '#352921', surface: '#fcf7f2', fit: '#c0392b' };
  const J = (v) => JSON.stringify(v);
  const pyNum = (x) => (x == null || !Number.isFinite(x) ? 'None' : String(x).replace(/^(-?)(\d+)e/, '$1$2.0e').replace(/^(-?\d+)$/, '$1.0'));
  const pyLit = (v) => (typeof v === 'number' ? pyNum(v) : J(String(v)));
  const pyCall = (lines) => lines.filter((l) => l != null).join('\n');

  /* The roles after Y and X. */
  function roles({ weight = true, freq = true, validation = true, by = true } = {}) {
    return [
      weight ? { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional: case weights', info: 'p:predict:weight', help: 'A case weight per row: a row of weight 2 counts twice as much in the fit, the measures, the confusion matrices and the curves as a row of weight 1 (so a weight that undoes oversampling undoes it there too). With a Freq column too, the two are multiplied. Rows with a missing, zero or negative weight are left out.' } : null,
      freq ? { key: 'freq', label: 'Freq', max: 1, numeric: true, hint: 'optional: row counts', info: 'p:predict:weight', help: 'How many observations each row stands for, as if it were repeated that many times: in the fit, in the measures of fit and in the confusion matrices. Rows with a missing, zero or negative count are left out.' } : null,
      validation ? { key: 'validation', label: 'Validation', max: 1, hint: 'optional: 0/1/2 or Training/Validation/Test, or K folds', info: 'p:predict:validation', help: 'Which rows the model learns from: 0 or Training (fits the model), 1 or Validation (chooses its size, such as when to stop splitting or adding trees, and measures it), 2 or Test (kept out of both, an honest measure of the chosen model). A column with more than three values holds K folds (Make Validation Column, K Fold): every row trains, and the platforms that crossvalidate use those folds. Rows with no value are left out. Without a Validation column, Validation Portion holds rows back at random.' } : null,
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

  /* ---- formula text (Save Threshold Formula, Save Profit Columns), written
     as util.formula_ref, formula_str and formula_num write it in Python ---- */
  const REF_OK = /^[\p{L}_][\p{L}\p{N}_]*$/u;
  const esc = (s) => String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const fRef = (name) => (REF_OK.test(String(name)) ? `:${name}` : `:"${esc(name)}"`);
  const fStr = (s) => `"${esc(s)}"`;
  const fNum = (x) => (typeof x === 'number' && Number.isFinite(x) ? (x < 0 ? `(${x})` : String(x)) : '.');
  const fVal = (v) => (typeof v === 'number' ? fNum(v) : fStr(v));
  /* The rows of the report's By group in formula text (:by == value & ...), or null without By groups,
     as models.where_condition writes it; a formula of the group is missing for the other rows. */
  function groupCondition(ctx) {
    const where = ctx.where || [];
    return where.length ? where.map((w) => `${fRef(w.column)} == ${fVal(w.value)}`).join(' & ') : null;
  }
  const inGroup = (ctx, expr) => { const c = groupCondition(ctx); return c ? `If(${c}, ${expr}, .)` : expr; };

  /* ---- the Decision Threshold's own settings, each By group's ------------------------------------
     JMP gives each By group's report its own Decision Threshold: the threshold, the target level, the
     true event rate (and Group Metrics' typed thresholds) set in one group are that group's. They are
     options under the group, the report's path as it keys the group's closed outlines, after the
     platform's scope: 'scope~group|key' (remapSpec rewrites a column id in the scope and leaves the
     group alone). A group without its own value takes the report's, which is where a report without By
     groups keeps it, and where an older report saved with one threshold for every group has it. */
  const BY_ESC = { '%': '%25', '|': '%7C', '~': '%7E' };
  const groupScope = (ctx, scope) => (ctx.path ? `${scope == null ? '' : scope}~${String(ctx.path).replace(/[%|~]/g, (c) => BY_ESC[c])}` : scope);
  function dtOpt(ctx, key, dflt, scope = null) {
    const gs = groupScope(ctx, scope);
    if (gs !== scope) { const o = ctx.spec.options || {}; if (`${gs}|${key}` in o) return o[`${gs}|${key}`]; }
    return ctx.opt(key, dflt, scope);
  }
  const dtSet = (ctx, key, value, scope = null) => ctx.set(key, value, groupScope(ctx, scope));

  /* The Measures of Fit of predictive.report(): a row per set; Naive Model
     (red triangle, beyond JMP) adds those of the training mean or shares. */
  function measures(ctx, parent, fit, { title = 'Measures of Fit', key = 'measures' } = {}) {
    const naiveOn = !!ctx.opt('naive', false) && Array.isArray(fit.naive) && fit.naive.length;
    const ob = ctx.outline(title, { parent, key, info: 'p:predict:measures', menu: Array.isArray(fit.naive) && fit.naive.length ? () => [ctx.check('Naive Model', 'naive', null, false)] : null });
    const cols = fit.measure_columns.filter((c) => c.key !== 'auc' || fit.measures.some((m) => m.auc != null));
    const rows = naiveOn ? [...fit.measures, ...fit.naive.map((m) => ({ ...m, set: `${m.set} (Naive)` }))] : fit.measures;
    ob.add(ctx.rt({ columns: cols, rows }, { key, sortable: false, cellClass: naiveOn ? (r) => (/\(Naive\)$/.test(r.set) ? 'sm-pred-naive' : '') : null }));
    const lines = [];
    if (fit.sets.length > 1) lines.push(`${fit.sets.map((s) => `${s} ${fit.n[s]} rows`).join(', ')}.`);
    if (fit.notes && fit.notes.length) lines.push(...fit.notes);
    if (naiveOn) lines.push(fit.kind === 'continuous' ? 'Naive: every row predicted by the training rows\' mean, the yardstick a model must beat (not in JMP).' : 'Naive: every row given the training rows\' shares of the levels, so the most likely level is the majority\'s: the yardstick a model must beat (not in JMP).');
    if (lines.length) ob.add(ctx.note(lines.join(' ')));
    return ob;
  }

  /* Confusion matrices, ROC and lift curves of a categorical response, each
     shown when its option is on (keys confusion, roc, lift in scope); then
     the Decision Threshold (two levels) and Group Metrics when theirs are.
     extra: { save: { fn, payload } } (the platform's Save Predicteds, which
     Save Threshold Formula runs first when the Prob[] column is not there),
     probName, title. */
  function classification(ctx, parent, fit, scope = null, prefix = '', extra = {}) {
    if (fit.kind !== 'categorical') return;
    if (ctx.opt('confusion', true, scope)) confusion(ctx, parent, fit, prefix);
    if (ctx.opt('roc', false, scope)) rocCurves(ctx, parent, fit, prefix, scope);
    if (ctx.opt('lift', false, scope)) liftCurves(ctx, parent, fit, prefix, scope);
    return decisionParts(ctx, parent, fit, scope, prefix, extra);
  }

  /* The Decision Threshold (two levels) and Group Metrics of a fit, when their options are on. */
  function decisionParts(ctx, parent, fit, scope = null, prefix = '', extra = {}) {
    if (!fit || fit.kind !== 'categorical') return;
    if (fit.threshold && ctx.opt('threshold', false, scope)) {
      threshold(ctx, parent, fit.threshold, { scope, prefix, save: extra.save || null, probName: extra.probName, yCol: extra.yCol });
    }
    if (fit.threshold && ctx.opt('groupMetrics', null, scope)) return groupMetrics(ctx, parent, fit.threshold, { scope, prefix, save: extra.save || null, probName: extra.probName, yCol: extra.yCol });
    return null;
  }

  /* The red-triangle items that turn those on and off. */
  function classificationItems(ctx, fit, scope = null) {
    if (fit.kind !== 'categorical') return [];
    const items = [ctx.check('Confusion Matrix', 'confusion', scope, true), ctx.check('ROC Curve', 'roc', scope, false), ctx.check('Lift Curve', 'lift', scope, false)];
    if (fit.threshold) items.push(thresholdItem(ctx, scope), groupItem(ctx, fit.threshold, scope));
    return items;
  }

  /* Decision Threshold in a red triangle (option 'threshold'). */
  const thresholdItem = (ctx, scope = null) => ctx.check('Decision Threshold', 'threshold', scope, false);

  /* Group Metrics… in a red triangle: the column the metrics are grouped by (SM.predict.groupMetricsItem(ctx, scope)
     for a platform that draws Group Metrics itself, as Fit Many Models). */
  function groupItem(ctx, data, scope = null) {
    const cur = ctx.opt('groupMetrics', null, scope);
    return { label: 'Group Metrics…', checked: !!cur, action: () => (cur ? ctx.set('groupMetrics', null, scope) : pickGroup(ctx, scope)) };
  }

  async function pickGroup(ctx, scope) {
    const t = ctx.table;
    if (!t) return;
    const cols = t.columns.filter((c) => c.isCategorical);
    if (!cols.length) { SM.ui.toast('Group Metrics needs a nominal or ordinal column to group the rows by', { error: true }); return; }
    const v = await SM.ui.form({ title: 'Group Metrics', info: 'p:predict:groups', fields: [{ key: 'col', label: 'Group the rows by', type: 'select', value: cols[0].id, choices: cols.map((c) => [c.id, c.name]), help: 'A nominal or ordinal column whose groups are compared: a protected attribute (sex, age group), a region, a product. It need not be a factor of the model: the rows keep their probabilities, and the measures are computed within each group.' }] });
    if (v && v.col) ctx.set('groupMetrics', v.col, scope);
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
    ob.add(ctx.row(...boxes), ctx.note('Rows are the actual levels, columns the most likely level the model predicts; each row counts by its Weight × Freq.'));
    return ob;
  }

  /* The level whose probability the ROC Table, the decile table and the
     profit curve sort by: the Decision Threshold's target (the second of
     two levels), or the first of more. */
  function sortLevel(ctx, fit, scope, key = 'dtLevel') {
    const n = (fit.levels || []).length;
    const v = dtOpt(ctx, key, null, scope);
    return Number.isInteger(v) && v >= 0 && v < n ? v : (n === 2 ? 1 : 0);
  }

  function rocCurves(ctx, parent, fit, prefix = '', scope = null) {
    const tableOn = !!fit.threshold && !!ctx.opt('rocTable', false, scope);
    const ob = ctx.outline('ROC Curve', { parent, key: `${prefix}roc`, info: 'p:predict:roc', menu: fit.threshold ? () => [ctx.check('ROC Table', 'rocTable', scope, false)] : null });
    const muted = SM.util.themeColors().muted;
    const pc = fit.plots || {};
    const plots = fit.sets.map((set) => {
      const cur = fit.roc.filter((r) => r.set === set);
      const traces = cur.map((r, i) => ({ type: 'scatter', mode: 'lines', x: r.fpr, y: r.tpr, name: `${SM.report.plotlyText(r.level)} (${r.auc == null ? '.' : r.auc.toFixed(4)})`, line: { color: SM.util.PALETTE[i % SM.util.PALETTE.length], width: 1.8 } }));
      traces.push({ type: 'scatter', mode: 'lines', x: [0, 1], y: [0, 1], line: { color: muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false });
      // the best cut of each level: the largest Sensitivity - (1 - Specificity), as JMP's ROC Table stars it
      cur.forEach((r, i) => {
        if (!r.best) return;
        traces.push({ type: 'scatter', mode: 'markers', x: [r.best.fpr], y: [r.best.tpr], marker: { color: SM.util.PALETTE[i % SM.util.PALETTE.length], size: 8, line: { color: SM.util.themeColors().surface, width: 1 } }, showlegend: false,
          hovertemplate: `${T(r.level)}: best cut Prob ≥ ${fmt(r.best.cut, { sig: 5 })}<br>1 - Specificity %{x:.4f}, Sensitivity %{y:.4f}<extra></extra>` });
      });
      return plotWithCode(ctx, traces, { showlegend: true, legend: { x: 0.35, y: 0.08 }, title: { text: set, font: { size: 12 } }, margin: { l: 50, r: 12, t: 28, b: 40 }, xaxis: { title: { text: '1 - Specificity' }, range: [0, 1] }, yaxis: { title: { text: 'Sensitivity' }, range: [0, 1.01] } }, { width: W(330), height: 320, title: `ROC ${set}`, select: false },
        pc.head_code, pc.roc && pc.roc[set]);
    });
    ob.add(ctx.row(...plots), ctx.rt({ columns: [{ key: 'set', label: 'Set', fmt: 'text' }, { key: 'level', label: 'Level', fmt: 'text' }, { key: 'auc', label: 'AUC' }, { key: 'cut', label: 'Best Cut', hidden: true }, { key: 'j', label: 'Sens-(1-Spec)', hidden: true }],
      rows: fit.roc.map((r) => ({ set: r.set, level: r.level, auc: r.auc, cut: r.best ? r.best.cut : null, j: r.best ? r.best.j : null })) }, { key: `${prefix}auc`, sortable: false }),
    ctx.note('Each level against all the others, by its predicted probability; the AUC is the area under the curve (0.5: no better than chance). The dot on each curve is its best cut, the largest Sensitivity - (1 - Specificity) (right click the table, Columns, for the cut).'));
    if (tableOn) rocTables(ctx, ob, fit, prefix, scope);
    return ob;
  }

  /* JMP's ROC Table (two levels): a line per cut on the target level's
     probability, the best starred; from the rows' probabilities. */
  function rocTables(ctx, parent, fit, prefix, scope) {
    const D = fit.threshold;
    const lv = sortLevel(ctx, fit, scope);
    const S = thresholdState(D, lv, null);
    const ob = ctx.outline('ROC Table', { parent, key: `${prefix}roctable`, info: 'p:predict:roctable', menu: () => [{ label: 'Remove', action: () => ctx.set('rocTable', false, scope) }] });
    const cols = [{ key: 'star', label: '', fmt: 'text' }, { key: 'prob', label: 'Prob', sig: 6 }, { key: 'fpr', label: '1-Specificity', digits: 4 }, { key: 'sens', label: 'Sensitivity', digits: 4 }, { key: 'j', label: 'Sens-(1-Spec)', digits: 4 },
      { key: 'tp', label: 'True Pos' }, { key: 'tn', label: 'True Neg' }, { key: 'fp', label: 'False Pos' }, { key: 'fn', label: 'False Neg' }];
    const boxes = D.sets.filter((s) => s !== CV).map((set) => {
      const rows = rocTableRows(S.cut(D.models[0], set)).map((r) => ({ ...r, star: r.best ? '*' : '' }));
      return el('div', { class: 'sm-pred-scroll' }, ctx.rt({ columns: cols, rows }, { caption: `${set}: ${D.levels[lv]}`, sortable: false, key: `${prefix}roctable-${set}`, maxRows: 600, cellClass: (r) => (r.best ? 'sm-pred-best' : '') }));
    });
    ob.add(ctx.row(...boxes));
    const code = thresholdCode(D, 'roc', { lv, sets: D.sets.filter((s) => s !== CV), model: D.models[0] });
    if (code) ob.add(ctx.code(code));
    ob.add(ctx.note(`A line per cut: a row is called ${D.levels[lv]} when its probability of ${D.levels[lv]} is at least Prob. The star marks the line with the largest Sens-(1-Spec) (Youden's J), the dot on the curve; the counts are by Weight × Freq.`));
  }

  /* The rows of the ROC Table of a cut table, as predictive.roc_table gives them. */
  function rocTableRows(c) {
    let best = -1, bj = -Infinity;
    const out = [];
    for (let k = 0; k < c.p.length; k++) {
      const tp = c.tp[k], fp = c.fp[k];
      const sens = c.pos > 0 ? tp / c.pos : null;
      const fpr = c.neg > 0 ? fp / c.neg : null;
      const j = sens == null || fpr == null ? null : sens - fpr;
      if (j != null && j > bj) { bj = j; best = k; }
      out.push({ prob: c.p[k], fpr, sens, j, tp, tn: c.neg - fp, fp, fn: c.pos - tp, best: false });
    }
    if (best >= 0 && c.pos > 0 && c.neg > 0) out[best].best = true;
    return out;
  }

  function liftCurves(ctx, parent, fit, prefix = '', scope = null) {
    const gainsOn = !!ctx.opt('gains', false, scope);
    const tableOn = !!ctx.opt('liftTable', false, scope);
    const profit = fit.threshold ? profitOf(ctx, yColOf(ctx, scope), fit.threshold.values || fit.values || fit.threshold.levels) : null;
    const lv = sortLevel(ctx, fit, scope);
    const ob = ctx.outline('Lift Curve', { parent, key: `${prefix}lift`, info: 'p:predict:lift', menu: () => [
      ctx.check('Cumulative Gains', 'gains', scope, false), ctx.check('Decile Lift Table', 'liftTable', scope, false),
      fit.levels && fit.levels.length > 2 ? { label: 'Table Level', submenu: () => fit.levels.map((l, i) => ({ label: l, checked: i === lv, action: () => dtSet(ctx, 'dtLevel', i, scope) })) } : null,
    ].filter(Boolean) });
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
    if (gainsOn) gainsCurves(ctx, ob, fit, prefix);
    if (tableOn) decileTables(ctx, ob, fit, prefix, lv);
    if (profit && fit.threshold) profitCurves(ctx, ob, fit, prefix, lv, profit);
    return ob;
  }

  /* Cumulative gains (beyond JMP): the share of the level's rows among the rows taken. */
  function gainsCurves(ctx, parent, fit, prefix) {
    const ob = ctx.outline('Cumulative Gains', { parent, key: `${prefix}gains`, info: 'p:predict:gains' });
    const muted = SM.util.themeColors().muted;
    const pc = fit.plots || {};
    const plots = fit.sets.map((set) => {
      const cur = fit.lift.filter((r) => r.set === set && r.gains);
      const traces = cur.map((r, i) => ({ type: 'scatter', mode: 'lines', x: r.portion, y: r.gains, name: T(r.level), line: { color: SM.util.PALETTE[i % SM.util.PALETTE.length], width: 1.8 } }));
      traces.push({ type: 'scatter', mode: 'lines', x: [0, 1], y: [0, 1], line: { color: muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false });
      return plotWithCode(ctx, traces, { showlegend: true, legend: { x: 0.45, y: 0.08 }, title: { text: set, font: { size: 12 } }, margin: { l: 50, r: 12, t: 28, b: 40 }, xaxis: { title: { text: 'Portion' }, range: [0, 1] }, yaxis: { title: { text: 'Gains' }, range: [0, 1.01] } },
        { width: W(330), height: 300, title: `Gains ${set}`, select: false }, pc.head_code, pc.gains && pc.gains[set]);
    });
    ob.add(ctx.row(...plots), ctx.note('The rows taken in order of the level\'s predicted probability: the share of all the level\'s rows found among them. The diagonal is a random order; a model that finds most of them in the first rows bows up and to the left. Not in JMP.'));
  }

  /* The decile lift table of one level per set (beyond JMP). */
  function decileTables(ctx, parent, fit, prefix, lv) {
    const level = fit.levels[lv];
    const ob = ctx.outline('Decile Lift Table', { parent, key: `${prefix}deciles`, info: 'p:predict:gains' });
    const cols = [{ key: 'bin', label: 'Decile', fmt: 'int' }, { key: 'n', label: 'N' }, { key: 'hits', label: `N ${level}` }, { key: 'rate', label: `Rate of ${level}`, digits: 4 }, { key: 'lift', label: 'Lift', digits: 4 },
      { key: 'cum_rate', label: 'Cumulative Rate', digits: 4, hidden: true }, { key: 'cum_lift', label: 'Cumulative Lift', digits: 4 }, { key: 'gains', label: 'Cumulative Gains', digits: 4 },
      { key: 'p_max', label: 'Highest Prob', sig: 5, hidden: true }, { key: 'p_min', label: 'Lowest Prob', sig: 5, hidden: true }];
    const boxes = fit.sets.map((set) => {
      const r = fit.lift.find((x) => x.set === set && x.level === level);
      return r && r.deciles && r.deciles.length ? el('div', { class: 'sm-pred-scroll' }, ctx.rt({ columns: cols, rows: r.deciles }, { caption: `${set}: ${level}`, sortable: false, key: `${prefix}deciles-${set}` })) : null;
    }).filter(Boolean);
    ob.add(ctx.row(...boxes));
    const code = (fit.plots || {}).deciles;
    if (code) ob.add(ctx.code(`${(fit.plots || {}).head_code}${SEP}${code.replace(/^lv = \d+/m, `lv = ${lv}`)}`));
    ob.add(ctx.note(`The rows taken highest probability of ${level} first and cut into ten parts of equal Weight × Freq (a row in the part its middle falls in; rows with the same probability taken in the table's order, as the lift curve takes them). Lift: the part's rate of ${level} over the set's; cumulative: of every part so far. Table Level (red triangle) picks another level. Not in JMP.`));
  }

  /* The profit of calling the rows taken the target level (a Profit Matrix, two levels). */
  function profitCurves(ctx, parent, fit, prefix, lv, profit) {
    const D = fit.threshold;
    const level = D.levels[lv];
    const S = thresholdState(D, lv, null);
    const ob = ctx.outline('Profit Curve', { parent, key: `${prefix}profitcurve`, info: 'p:predict:profit' });
    const muted = SM.util.themeColors().muted;
    const plots = D.sets.filter((s) => s !== CV).map((set) => {
      const pts = S.profitCurve(D.models[0], set, profit.matrix);
      const traces = [{ type: 'scatter', mode: 'lines', x: pts.portion, y: pts.profit, name: T(level), line: { color: SM.util.PALETTE[0], width: 1.8 }, hovertemplate: `portion %{x:.3f}: average profit %{y:.4g}<extra></extra>` },
        { type: 'scatter', mode: 'lines', x: [0, 1], y: [pts.profit[0], pts.profit[pts.profit.length - 1]], line: { color: muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false }];
      return plotWithCode(ctx, traces, { title: { text: set, font: { size: 12 } }, margin: { l: 58, r: 12, t: 28, b: 40 }, xaxis: { title: { text: `Portion called ${T(level)}` }, range: [0, 1] }, yaxis: { title: { text: 'Average Profit' } } },
        { width: W(330), height: 300, title: `Profit ${set}`, select: false }, D.plots && D.plots.head_code, thresholdCode(D, 'profitcurve', { lv, set, model: D.models[0], matrix: profit.matrix }));
    });
    ob.add(ctx.row(...plots), ctx.note(`The rows taken highest probability of ${level} first and called ${level}, the rest the other level: the average profit per row by the Profit Matrix of ${D.levels.join(' and ')} (the Y column's property). The dotted line joins calling none and calling all; the peak is the most profitable portion.`));
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
      later.then((res) => { const code = res && penregCode(res, set, k); if (code) box.lastChild.replaceWith(ctx.code(code)); else box.lastChild.remove(); });
      return box;
    });
    ob.add(ctx.row(...plots));
    return ob;
  }

  /* A fit of another platform that comes without its graphs' code: Fit
     Model's Penalized Regression hands over its rows, actual and
     predicted values (smui-p-fitmodel.js). Its block is made from the code
     of the call those arrays came from (fitmodel.penreg), found in the
     report's cache by the very arrays; that code fits the chosen model and
     ends its fit with e, every row's linear predictor. The call has
     returned already, so the block is in place when the report is done. */
  function fromCall(ctx, fit) {
    const want = fit.residuals && fit.residuals.predicted;
    const cache = ctx.report && ctx.report.cache;
    if (!want || !cache || typeof cache.entries !== 'function') return null;
    const calls = [...cache.entries()].filter(([k]) => String(k).startsWith('fitmodel.penreg\u0001')).map(([, p]) => Promise.resolve(p).catch(() => null));
    if (!calls.length) return null;
    return Promise.all(calls).then((rs) => rs.find((x) => x && x.diag && x.diag.predicted === want) || null);
  }

  /* Penalized Regression's Actual by Predicted Plot as code: its own code
     up to e (the linear predictor of the chosen model), then the prediction
     (the mean: e, or exp(e) for the Poisson's log link) against the actual
     values of the set's rows (train, valid and sets as that code names them). */
  function penregCode(res, set, k) {
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
     predictive.saved(); payload what it needs to find the model. With a
     Profit Matrix on a categorical Y, Save Profit Columns too. */
  function saveItems(ctx, fn, payload, fit, { yCol = null, probName = null } = {}) {
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
    const y = yCol || ctx.role('y');
    if (fit.kind === 'categorical' && y && y.profitMatrix && Array.isArray(fit.levels)) {
      items.push({ label: 'Save Profit Columns', action: () => saveProfit(ctx, { fit, yCol: y, save: { fn, payload }, probName }) });
    }
    return [{ label: 'Save Columns', submenu: () => items }];
  }

  /* ======================================================================
     THE COUNTS AT A THRESHOLD (as predictive.cut_table, counts_at, rates_at)
     ====================================================================== */
  /* Every cut on p (a row is called the level when its p is at least the
     cut): the distinct values highest first and the weight of the level's
     rows (tp) and of the others (fp) at or above each; pos and neg the
     totals. The rows in their order, equal values kept together. */
  function cutTable(p, pos, w) {
    const idx = [];
    for (let i = 0; i < p.length; i++) if (Number.isFinite(p[i])) idx.push(i);
    idx.sort((a, b) => p[b] - p[a]);
    const out = { p: [], tp: [], fp: [], pos: 0, neg: 0 };
    let tp = 0, fp = 0;
    for (let k = 0; k < idx.length; k++) {
      const i = idx[k], wi = w ? w[i] : 1;
      if (pos[i]) tp += wi; else fp += wi;
      if (k === idx.length - 1 || p[idx[k + 1]] !== p[i]) { out.p.push(p[i]); out.tp.push(tp); out.fp.push(fp); }
    }
    out.pos = tp;
    out.neg = fp;
    return out;
  }

  /* [tp, fp, fn, tn] at the threshold t. */
  function countsAt(c, t) {
    let lo = 0, hi = c.p.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (c.p[mid] >= t) lo = mid + 1; else hi = mid; }
    const tp = lo ? c.tp[lo - 1] : 0, fp = lo ? c.fp[lo - 1] : 0;
    return [tp, fp, c.pos - tp, c.neg - fp];
  }

  const div = (a, b) => (b > 0 ? a / b : null);
  function ratesAt([tp, fp, fn, tn]) {
    const n = tp + fp + fn + tn;
    const den = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn);
    return { tp, fp, fn, tn, n, accuracy: div(tp + tn, n), misclassification: div(fp + fn, n), sensitivity: div(tp, tp + fn), specificity: div(tn, tn + fp),
      fpr: div(fp, fp + tn), fnr: div(fn, fn + tp), precision: div(tp, tp + fp), npv: div(tn, tn + fn), f1: div(2 * tp, 2 * tp + fp + fn),
      mcc: den > 0 ? (tp * tn - fp * fn) / Math.sqrt(den) : null, portion: div(tp + fp, n) };
  }

  const METRICS = [['accuracy', 'Accuracy'], ['misclassification', 'Misclassification Rate'], ['sensitivity', 'Sensitivity'], ['specificity', 'Specificity'],
    ['fpr', 'False Positive Rate'], ['fnr', 'False Negative Rate'], ['precision', 'Precision'], ['npv', 'Negative Predictive Value'], ['f1', 'F1 Score'], ['mcc', 'MCC'], ['portion', 'Portion Called']];
  const METRIC_LABEL = Object.fromEntries(METRICS);
  const METRIC_HIDDEN = new Set(['npv', 'portion']);
  const CURVES = ['accuracy', 'sensitivity', 'specificity', 'precision', 'f1', 'mcc'];
  const CURVE_STYLE = { accuracy: [0, 'solid'], misclassification: [0, 'dash'], sensitivity: [1, 'solid'], specificity: [2, 'solid'], fpr: [2, 'dash'], fnr: [1, 'dash'],
    precision: [3, 'solid'], npv: [3, 'dash'], f1: [4, 'solid'], mcc: [5, 'solid'], portion: [9, 'dot'] };
  const MPL_DASH = { solid: '-', dash: '--', dot: ':' };
  const BEST = [['accuracy', 'Best Accuracy'], ['f1', 'Best F1 Score'], ['mcc', 'Best MCC'], ['youden', 'Best Sensitivity + Specificity (Youden)']];

  /* The Y column a fit belongs to: the scope's (a response's id) or the Y role's. */
  const yColOf = (ctx, scope) => (scope != null && ctx.col(scope)) || ctx.role('y');

  /* The Y column's Profit Matrix for these levels (values as the table holds
     them): { decisions, matrix } with the matrix's rows the levels in this
     order and its columns the same levels then Undecided when used; null
     when there is none or it lacks a level. */
  function profitOf(ctx, yCol, values) {
    if (!yCol || !yCol.profitMatrix || !ctx.table || !SM.table || !SM.table.profitAligned) return null;
    const pm = SM.table.profitAligned(ctx.table, yCol.id);
    if (!pm) return null;
    const key = (v) => (typeof v === 'number' ? `n${v}` : `s${v}`);
    const at = new Map(pm.levels.map((v, i) => [key(v), i]));
    const idx = values.map((v) => at.get(key(v)));
    if (idx.some((i) => i == null)) return null;
    const und = pm.decisions.length > pm.levels.length;
    const cols = [...idx, ...(und ? [pm.levels.length] : [])];
    return { decisions: [...values.map(String), ...(und ? [pm.decisions[pm.levels.length]] : [])], matrix: idx.map((i) => cols.map((j) => pm.matrix[i][j])), undecided: und };
  }

  /* What a threshold report needs of its data for one target level: each
     model's cut table per set (the probabilities rescaled by a true event
     rate when one is given), and the per-row pieces for the plots and the
     profit. rate: the true event rate of the target level, or null. */
  function thresholdState(D, lv, rate) {
    const P = D.points;
    const n = P.actual.length;
    const w = P.w || null;
    // the training share of the target level (sequentially summed, as the code's np.cumsum)
    let tw = 0, tl = 0;
    for (let i = 0; i < n; i++) if (P.set[i] === 0) { const wi = w ? w[i] : 1; tw += wi; if (P.actual[i] === lv) tl += wi; }
    const rho = tw > 0 ? tl / tw : null;
    const on = rate != null && rate > 0 && rate < 1 && rho > 0 && rho < 1;
    const A = on ? rate / rho : 1, B = on ? (1 - rate) / (1 - rho) : 1;
    const adj = on ? (p) => (p * A) / (p * A + (1 - p) * B) : (p) => p;
    const memo = new Map();
    const rowsOf = (set) => { const k = SETS.indexOf(set); const out = []; for (let i = 0; i < n; i++) if (k < 0 || P.set[i] === k) out.push(i); return out; };
    const probOf = (m, set, j) => {
      const cv = set === CV;
      const p1 = cv ? m.p_cv : m.p, p0 = cv ? m.p0_cv : m.p0;
      return j === 1 ? (i) => p1[i] : (p0 ? (i) => p0[i] : (i) => 1 - p1[i]);
    };
    const get = (m, set) => {
      const k = `${m.key}\u0001${set}`;
      if (!memo.has(k)) {
        const rr = rowsOf(set);
        const pf = probOf(m, set, lv);
        const q = rr.map((i) => adj(pf(i)));
        memo.set(k, { rows: rr, q, cut: cutTable(q, rr.map((i) => P.actual[i] === lv), w ? rr.map((i) => w[i]) : null) });
      }
      return memo.get(k);
    };
    return {
      lv, rho, rate: on ? rate : null, A, B, adj,
      rows: (m, set) => get(m, set).rows,
      q: (m, set) => get(m, set).q,
      cut: (m, set) => get(m, set).cut,
      at: (m, set, t) => ratesAt(countsAt(get(m, set).cut, t)),
      /* The average profit of each rule on a set: at the threshold t (the
         target or the other level), the best threshold of the set, and the
         most profitable decision of each row (Undecided too). M: the
         Profit Matrix in the levels' order. */
      profit(m, set, t, M) {
        const g = get(m, set), c = g.cut, o = 1 - lv;
        const val = ([tp, fp, fn, tn]) => tp * M[lv][lv] + fn * M[lv][o] + fp * M[o][lv] + tn * M[o][o];
        const N = c.pos + c.neg;
        const atT = val(countsAt(c, t)) / N;
        // the best cut of the set: each distinct probability, and calling none
        let best = val([0, 0, c.pos, c.neg]) / N, bestT = null;
        for (let k = 0; k < c.p.length; k++) {
          const v = val([c.tp[k], c.fp[k], c.pos - c.tp[k], c.neg - c.fp[k]]) / N;
          if (v > best) { best = v; bestT = c.p[k]; }
        }
        // the most profitable decision of each row, by its probabilities
        let tot = 0, wsum = 0;
        for (let k = 0; k < g.rows.length; k++) {
          const i = g.rows[k], ql = g.q[k], wi = w ? w[i] : 1;
          const pr = lv === 1 ? [1 - ql, ql] : [ql, 1 - ql];
          let bd = 0, be = -Infinity;
          for (let d = 0; d < M[0].length; d++) { const e = pr[0] * M[0][d] + pr[1] * M[1][d]; if (e > be) { be = e; bd = d; } }
          tot += wi * M[P.actual[i]][bd];
          wsum += wi;
        }
        const d1 = M[lv][lv] - M[lv][o], d0 = M[o][o] - M[o][lv];
        return { atT, total: atT * N, best, bestT, bayes: wsum > 0 ? tot / wsum : null, theory: d1 + d0 > 0 ? d0 / (d1 + d0) : null, n: N };
      },
      /* The profit curve of a set: the rows taken highest probability first
         (equal ones in the rows' order, as the lift curve takes them). */
      profitCurve(m, set, M) {
        const g = get(m, set), o = 1 - lv;
        const idx = g.rows.map((_, k) => k).sort((a, b) => g.q[b] - g.q[a]);
        let pos = 0, neg = 0;
        for (const k of idx) { const wi = w ? w[g.rows[k]] : 1; if (P.actual[g.rows[k]] === lv) pos += wi; else neg += wi; }
        const N = pos + neg;
        let tp = 0, fp = 0;
        const portion = [0], profit = [(pos * M[lv][o] + neg * M[o][o]) / N];
        for (const k of idx) {
          const i = g.rows[k], wi = w ? w[i] : 1;
          if (P.actual[i] === lv) tp += wi; else fp += wi;
          portion.push((tp + fp) / N);
          profit.push((tp * M[lv][lv] + (pos - tp) * M[lv][o] + fp * M[o][lv] + (neg - fp) * M[o][o]) / N);
        }
        return thinCurve(portion, profit, 400);
      },
    };
  }

  function thinCurve(x, y, most) {
    if (x.length <= most) return { portion: x, profit: y };
    const keep = new Set();
    for (let i = 0; i < most; i++) keep.add(Math.round((i * (x.length - 1)) / (most - 1)));
    const k = [...keep].sort((a, b) => a - b);
    return { portion: k.map((i) => x[i]), profit: k.map((i) => y[i]) };
  }

  /* The jitter of a row's point in the fitted-probability plot, from its row number (the code writes the same). */
  const jitter = (row) => ((row * 0.6180339887498949) % 1) - 0.5;
  const GRID = Array.from({ length: 101 }, (_, i) => i / 100);

  /* ======================================================================
     DECISION THRESHOLD (two levels)
     ====================================================================== */
  function threshold(ctx, parent, D, opts = {}) {
    if (!D || !Array.isArray(D.models) || !D.models.length || !Array.isArray(D.sets) || !D.sets.length) return null;
    const { scope = null, prefix = '', title = 'Decision Threshold', option = 'threshold', keys = {}, info = 'p:predict:threshold', save = null } = opts;
    const K = { cut: keys.cut || 'dtCut', level: keys.level || 'dtLevel', curves: keys.curves || 'dtCurves', metric: keys.metric || 'dtMetric', rate: keys.rate || 'dtTrueRate', showCurves: keys.showCurves || 'dtCurvesOn' };
    const yCol = opts.yCol || yColOf(ctx, scope);
    const yName = yCol ? yCol.name : 'Y';
    const levels = D.levels, values = D.values || D.levels;
    const multi = D.models.length > 1;
    // the threshold, the target level and the true event rate: this By group's (dtOpt)
    let lv = dtOpt(ctx, K.level, D.target ?? 1, scope);
    lv = lv === 0 || lv === 1 ? lv : 1;
    const o = 1 - lv;
    let cut = Number(dtOpt(ctx, K.cut, 0.5, scope));
    if (!(cut >= 0 && cut <= 1)) cut = 0.5;
    const rate0 = dtOpt(ctx, K.rate, null, scope);
    const S = thresholdState(D, lv, rate0 == null ? null : Number(rate0));
    const profit = profitOf(ctx, yCol, values);
    const probName = opts.probName || ((label) => `Prob[${label}]`);
    const tune = D.sets.includes('Validation') ? 'Validation' : D.sets.includes(CV) ? CV : D.sets[0];
    const setCut = (v) => { if (Number.isFinite(v)) dtSet(ctx, K.cut, Math.max(0, Math.min(1, +Number(v).toPrecision(12))), scope); };
    const curvesOn = !!ctx.opt(K.showCurves, true, scope);
    let curveKeys = ctx.opt(K.curves, null, scope);
    curveKeys = Array.isArray(curveKeys) ? curveKeys.filter((k) => METRIC_LABEL[k]) : CURVES;
    let metric = ctx.opt(K.metric, 'misclassification', scope);
    if (!METRIC_LABEL[metric]) metric = 'misclassification';
    const modelsOf = () => D.models;
    const labelOfModel = (m) => m.label || '';
    // each model's colour in the page (the theme's) and in the code (the light theme's)
    const colorOf = opts.colorOf || ((m) => SM.util.PALETTE[Math.max(0, D.models.indexOf(m)) % SM.util.PALETTE.length]);
    const pyColorOf = opts.pyColorOf || ((m) => SM.util.PALETTE[Math.max(0, D.models.indexOf(m)) % SM.util.PALETTE.length]);

    const best = (what) => {
      const m = D.models[0];
      const c = S.cut(m, tune);
      let bt = null, bv = -Infinity;
      for (let k = 0; k < c.p.length; k++) {
        const r = ratesAt([c.tp[k], c.fp[k], c.pos - c.tp[k], c.neg - c.fp[k]]);
        const v = what === 'youden' ? (r.sensitivity == null || r.specificity == null ? null : r.sensitivity + r.specificity - 1)
          : what === 'profit' ? (profit ? S.profit(m, tune, c.p[k], profit.matrix).atT : null) : r[what];
        if (v != null && v > bv) { bv = v; bt = c.p[k]; }
      }
      if (bt == null) { SM.ui.toast('No threshold of these rows gives that measure', { error: true }); return; }
      setCut(bt);
      SM.ui.toast(`Threshold ${fmt(bt, { sig: 6 })}: the ${what === 'youden' ? 'largest Sensitivity + Specificity' : what === 'profit' ? 'largest average profit' : `best ${METRIC_LABEL[what]}`} of the ${tune.toLowerCase()} rows${multi ? ` (${labelOfModel(D.models[0])})` : ''}`);
    };
    const menu = () => [
      { label: 'Target Level', submenu: () => levels.map((l, i) => ({ label: l, checked: i === lv, action: () => dtSet(ctx, K.level, i, scope) })) },
      { label: 'Set Probability Threshold…', action: async () => {
        const v = await SM.ui.form({ title: 'Probability Threshold', info, fields: [{ key: 't', label: `Probability of ${levels[lv]} at or above which a row is called ${levels[lv]}`, type: 'number', value: cut, help: 'A probability from 0 to 1 (0.5): a row whose predicted probability of the target level is at least this is called that level. Lower it to catch more of the level\'s rows (a higher sensitivity) at the cost of more false positives; raise it for the opposite.' }], validate: (x) => (x.t >= 0 && x.t <= 1 ? null : 'The threshold is a probability, from 0 to 1') });
        if (v) setCut(v.t);
      } },
      { label: 'Set Threshold to', submenu: () => [...BEST, ...(profit ? [['profit', 'Most Profit']] : [])].map(([k, l]) => ({ label: l, action: () => best(k) })) },
      { separator: true },
      ctx.check('Metric Curves', K.showCurves, scope, true),
      multi ? { label: 'Curve Metric', submenu: () => METRICS.map(([k, l]) => ({ label: l, checked: k === metric, action: () => ctx.set(K.metric, k, scope) })) }
        : { label: 'Curves', submenu: () => METRICS.map(([k, l]) => ({ label: l, checked: curveKeys.includes(k), action: () => ctx.set(K.curves, curveKeys.includes(k) ? curveKeys.filter((x) => x !== k) : [...curveKeys, k], scope) })) },
      { label: 'True Event Rate…', checked: S.rate != null, action: () => trueRateDialog() },
      { label: 'Profit Matrix…', disabled: !yCol || !SM.colprops || !SM.colprops.openOne, action: () => editProfit() },
      { separator: true },
      multi ? { label: 'Save Threshold Formula', submenu: () => D.models.map((m) => ({ label: labelOfModel(m), action: () => saveFormula(m) })) } : { label: 'Save Threshold Formula', action: () => saveFormula(D.models[0]) },
      profit ? { label: 'Save Profit Columns', submenu: multi ? () => D.models.map((m) => ({ label: labelOfModel(m), action: () => saveProfit(ctx, { data: D, model: m, yCol, save: save && typeof save === 'function' ? null : save, saveFn: typeof save === 'function' ? save : null, probName, S }) })) : undefined,
        action: multi ? undefined : () => saveProfit(ctx, { data: D, model: D.models[0], yCol, save: save && typeof save === 'function' ? null : save, saveFn: typeof save === 'function' ? save : null, probName, S }) } : null,
      { label: 'Remove', action: () => ctx.set(option, false, scope) },
    ].filter(Boolean);
    const ob = ctx.outline(title, { parent, key: `${prefix}threshold`, info, menu });

    async function trueRateDialog() {
      const v = await SM.ui.form({ title: 'True Event Rate', info, fields: [{ key: 'r', label: `The share of ${levels[lv]} in the population (empty: none)`, type: 'number', value: S.rate, help: `When the training rows were oversampled (more ${levels[lv]} rows than the population has, to learn it better), the model's probabilities are too high. With the true share of ${levels[lv]}, every probability p is rescaled as p·a / (p·a + (1 − p)·b), a = true share / training share and b = (1 − true share) / (1 − training share), before the threshold is applied: the counts, the measures, the profit and the saved formulas then use the rescaled probabilities. Empty: the model's own.` }], validate: (x) => (x.r == null || (x.r > 0 && x.r < 1) ? null : 'The true event rate is a share between 0 and 1') });
      if (v) dtSet(ctx, K.rate, v.r == null ? null : v.r, scope);
    }
    function editProfit() {
      if (!yCol || !SM.colprops) return;
      const off = ctx.table.on('schema', (e) => { if (e && e.info === yCol.id) { off(); ctx.report.run(); } });
      SM.colprops.openOne(SM.app, 'profit', yCol);
    }
    // Save Threshold Formula: If(Prob[target] ≥ threshold, target, other) on the Prob[] column, in a By group
    // this group's own column and threshold, the other groups' rows missing
    async function saveFormula(m) {
      const cols = await probColumns(ctx, save, m, [probName(levels[lv], m)]);
      if (!cols) return;
      const name = cols[0];
      const p = S.rate != null ? `(${fRef(name)} * ${S.A}) / (${fRef(name)} * ${S.A} + (1 - ${fRef(name)}) * ${S.B})` : fRef(name);
      const expr = inGroup(ctx, `If(${p} >= ${fNum(cut)}, ${fVal(values[lv])}, ${fVal(values[o])})`);
      try {
        ctx.saveFormula(`Called ${yName}${multi ? ` ${labelOfModel(m)}` : ''}${ctx.byLabel ? ` ${ctx.byLabel}` : ''} (${name} ≥ ${fmt(cut, { sig: 6 })})`, expr, {
          modelingType: yCol && yCol.modelingType === 'ordinal' ? 'ordinal' : 'nominal', valueOrder: values.slice(),
          notes: `${levels[lv]} when ${name}${S.rate != null ? ` (rescaled to a true event rate of ${S.rate})` : ''} is at least ${cut}, else ${levels[o]}${ctx.byLabel ? `, for the rows of ${ctx.byLabel} (the other rows missing)` : ''}: the Decision Threshold of ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`,
        });
      } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
    }

    // ---- the controls
    const input = el('input', { type: 'text', inputmode: 'decimal', size: 7, class: 'sm-pred-input', 'aria-label': 'Probability threshold' });
    input.value = String(cut);
    const apply = () => { const v = SM.table.toNumber(input.value.replace(',', '.')); if (v >= 0 && v <= 1) setCut(v); else SM.ui.toast('The threshold is a probability, from 0 to 1', { error: true }); };
    input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); apply(); } });
    const go = el('button', { type: 'button', class: 'sm-btn small', text: 'Apply' });
    go.addEventListener('click', apply);
    const slider = el('input', { type: 'range', min: '0', max: '1', step: '0.01', value: String(cut), class: 'sm-pred-slider', 'aria-label': 'Probability threshold slider' });
    slider.addEventListener('input', () => { input.value = slider.value; });
    slider.addEventListener('change', () => setCut(Number(slider.value)));
    ob.add(el('div', { class: 'sm-pred-cut', 'data-noexport': '' },
      el('label', null, el('span', { text: `Probability threshold for ${levels[lv]}` }), input), go, slider));
    ob.add(ctx.note(`A row is called ${levels[lv]} when its probability of ${levels[lv]}${S.rate != null ? ` (rescaled to a true event rate of ${fmt(S.rate)})` : ''} is at least ${fmt(cut, { sig: 6 })}, else ${levels[o]}. Drag the dashed line, type a threshold, or move the slider${ctx.byLabel ? `: the threshold and the target level are ${ctx.byLabel}'s own, as each By group's in JMP` : ''}.`));

    // ---- the fitted probabilities, per set (of several models: the set that compares them)
    const plotSets = multi ? [tune] : D.sets;
    const head = D.plots ? D.plots.head_code : null;
    const fittedPlot = (m, set) => {
      const P = D.points;
      const rr = S.rows(m, set), q = S.q(m, set);
      const big = rr.length > 2000 && SM.report.hasWebGL();
      const traces = [0, 1].map((j) => {
        const kk = []; for (let k = 0; k < rr.length; k++) if (P.actual[rr[k]] === j) kk.push(k);
        return { type: big ? 'scattergl' : 'scatter', mode: 'markers', x: kk.map((k) => q[k]), y: kk.map((k) => j + 0.7 * jitter(P.rows[rr[k]])), rows: kk.map((k) => P.rows[rr[k]]), name: T(levels[j]),
          marker: { color: SM.util.PALETTE[j], size: rr.length > 1500 ? 3.5 : 5.5 }, hovertemplate: `row %{customdata}: ${T(levels[j])}, Prob[${T(levels[lv])}] %{x:.4f}<extra></extra>`, customdata: kk.map((k) => P.rows[rr[k]] + 1) };
      });
      const title2 = `Fitted probabilities ${set}${multi ? ` ${labelOfModel(m)}` : ''}`;
      return plotWithCode(ctx, traces, {
        showlegend: false, margin: { l: 64, r: 10, t: 26, b: 40 }, title: { text: multi ? T(labelOfModel(m)) : set, font: { size: 11.5 } },
        xaxis: { title: { text: `Prob[${T(levels[lv])}]` }, range: [0, 1] }, yaxis: { title: { text: 'Actual' }, tickvals: [0, 1], ticktext: levels.map(T), range: [-0.6, 1.6], zeroline: false },
        shapes: [{ type: 'line', x0: cut, x1: cut, yref: 'paper', y0: 0, y1: 1, line: { color: SM.util.themeColors().dark ? '#ff7a6b' : PY.fit, width: 1.8, dash: 'dash' } }],
      }, { width: W(multi ? 280 : 340), height: multi ? 220 : 250, title: title2, config: { edits: { shapePosition: true } },
        onDraw: (gd) => gd.on('plotly_relayout', (ev) => { if (!ev) return; const x = ev['shapes[0].x0'] ?? ev['shapes[0].x1']; if (x != null) setCut(Math.round(Number(x) * 10000) / 10000); }) },
      head, thresholdCode(D, 'fitted', { lv, set, model: m, cut, S, title: title2 }));
    };

    // ---- JMP's stacked bars of the classifications: each actual level's rows by the level called (by Weight × Freq)
    const barPlot = (m, set) => {
      const r = S.at(m, set, cut);
      const cell = (a, c) => (a === lv ? (c === lv ? r.tp : r.fn) : (c === lv ? r.fp : r.tn));
      const tot = [0, 1].map((a) => cell(a, 0) + cell(a, 1));
      const share = (a, c) => (tot[a] > 0 ? cell(a, c) / tot[a] : 0);
      const title2 = `Classification at the threshold ${set}`;
      const traces = [0, 1].map((c) => ({ type: 'bar', orientation: 'h', y: levels.map(T), x: [0, 1].map((a) => share(a, c)), name: `called ${T(levels[c])}`,
        marker: { color: SM.util.PALETTE[c] }, customdata: [0, 1].map((a) => cell(a, c)), hovertemplate: `actual %{y}, called ${T(levels[c])}: %{x:.1%} (%{customdata:.6g})<extra></extra>` }));
      return plotWithCode(ctx, traces, {
        barmode: 'stack', showlegend: true, legend: { orientation: 'h', traceorder: 'normal', x: 0, y: 1.02, yanchor: 'bottom', font: { size: 10 } }, margin: { l: 64, r: 10, t: 30, b: 40 },
        xaxis: { title: { text: 'Portion of the actual level' }, range: [0, 1] }, yaxis: { title: { text: 'Actual' }, type: 'category' },
      }, { width: W(300), height: 200, title: title2, select: false }, head, thresholdCode(D, 'bars', { lv, set, model: m, cut, S, title: title2 }));
    };

    // ---- the confusion matrix and the measures at the threshold
    const cmTables = (m, set) => {
      const r = S.at(m, set, cut);
      const cell = (a, c) => (a === lv ? (c === lv ? r.tp : r.fn) : (c === lv ? r.fp : r.tn));
      const cols = [{ key: 'actual', label: 'Actual', fmt: 'text' }, ...levels.map((l, j) => ({ key: `c${j}`, label: l }))];
      const rows = [0, 1].map((a) => ({ actual: levels[a], c0: cell(a, 0), c1: cell(a, 1) }));
      const rates = [0, 1].map((a) => { const tot = cell(a, 0) + cell(a, 1); return { actual: levels[a], c0: div(cell(a, 0), tot), c1: div(cell(a, 1), tot) }; });
      return el('div', { class: 'sm-pred-cm' },
        ctx.rt({ columns: cols, rows }, { caption: `${set}: count at the threshold`, sortable: false, key: `${prefix}dtcm-${set}` }),
        ctx.rt({ columns: cols.map((c) => (c.key === 'actual' ? c : { ...c, digits: 4 })), rows: rates }, { caption: `${set}: rate at the threshold`, sortable: false, key: `${prefix}dtrate-${set}` }));
    };
    const metricCols = (lead) => [lead, ...METRICS.map(([k, l]) => ({ key: k, label: l, digits: 4, hidden: METRIC_HIDDEN.has(k) })),
      { key: 'tp', label: 'True Positive', hidden: !multi }, { key: 'fp', label: 'False Positive', hidden: !multi }, { key: 'fn', label: 'False Negative', hidden: !multi }, { key: 'tn', label: 'True Negative', hidden: !multi }, { key: 'n', label: 'N', hidden: true }];

    if (!multi) {
      const m = D.models[0];
      for (const set of D.sets) {
        const pl = ctx.headless ? null : fittedPlot(m, set);
        const bars = ctx.headless ? null : barPlot(m, set);
        ob.add(ctx.row(...[pl, bars, cmTables(m, set)].filter(Boolean)));
      }
      ob.add(el('div', { class: 'sm-pred-scroll' }, ctx.rt({ columns: metricCols({ key: 'set', label: 'Set', fmt: 'text' }), rows: D.sets.map((set) => ({ set, ...S.at(m, set, cut) })) }, { key: `${prefix}dtmetrics`, sortable: false, caption: `${levels[lv]} called when Prob[${levels[lv]}] ≥ ${fmt(cut, { sig: 6 })}` })));
    } else {
      if (!ctx.headless) ob.add(ctx.row(...modelsOf().map((m) => fittedPlot(m, tune))));
      for (const set of D.sets) {
        ob.add(el('div', { class: 'sm-pred-scroll' }, ctx.rt({ columns: metricCols({ key: 'model', label: 'Method', fmt: 'text' }), rows: modelsOf().map((m) => ({ model: labelOfModel(m), ...S.at(m, set, cut) })) }, { key: `${prefix}dtmetrics-${set}`, caption: `${set}: ${levels[lv]} when its probability ≥ ${fmt(cut, { sig: 6 })}` })));
      }
    }
    const tcode = thresholdCode(D, 'tables', { lv, cut, S, models: modelsOf() });
    if (tcode) ob.add(ctx.code(tcode));
    const counted = D.weighted ? 'by Weight × Freq' : 'a row each';
    ob.add(ctx.note(`Sensitivity is the share of the ${levels[lv]} rows called ${levels[lv]}, Specificity the share of the others called ${levels[o]}, Precision the share of the rows called ${levels[lv]} that are, F1 their harmonic mean with Sensitivity, MCC the correlation of actual and called; the False Positive Rate is 1 − Specificity and the False Negative Rate 1 − Sensitivity. Counts ${counted}; right click a table, Columns, for the others.`));

    // ---- the measures against the threshold
    if (curvesOn && !ctx.headless) {
      const co = ctx.outline('Metrics by Threshold', { parent: ob, key: `${prefix}dtcurves`, info });
      const plots = D.sets.map((set) => {
        const series = multi ? modelsOf().map((m) => ({ name: labelOfModel(m), y: GRID.map((t) => S.at(m, set, t)[metric]), color: colorOf(m), dash: 'solid' }))
          : curveKeys.map((k) => ({ name: METRIC_LABEL[k], key: k, y: GRID.map((t) => S.at(D.models[0], set, t)[k]), color: SM.util.PALETTE[CURVE_STYLE[k][0]], dash: CURVE_STYLE[k][1] }));
        let lo = 0;
        for (const s of series) for (const v of s.y) if (v != null && v < lo) lo = v;
        const range = [lo - 0.03, 1.03];
        const traces = series.map((s) => ({ type: 'scatter', mode: 'lines', x: GRID, y: s.y, name: T(s.name), line: { color: s.color, width: 1.6, dash: s.dash }, hovertemplate: `${T(s.name)}: threshold %{x:.2f}, %{y:.4f}<extra></extra>` }));
        const t2 = `${multi ? METRIC_LABEL[metric] : 'Measures'} by threshold ${set}`;
        return plotWithCode(ctx, traces, { showlegend: true, legend: { font: { size: 9.5 } }, hovermode: 'closest', margin: { l: 50, r: 8, t: 26, b: 40 }, title: { text: set, font: { size: 12 } },
          xaxis: { title: { text: `Threshold on Prob[${T(levels[lv])}]` }, range: [0, 1] }, yaxis: { title: { text: multi ? METRIC_LABEL[metric] : 'Measure' }, range },
          shapes: [{ type: 'line', x0: cut, x1: cut, yref: 'paper', y0: 0, y1: 1, line: { color: SM.util.themeColors().muted, width: 1.2, dash: 'dash' } }] },
        { width: W(multi ? 520 : 440), height: 300, title: t2, select: false, onDraw: (gd) => gd.on('plotly_click', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt && Number.isFinite(pt.x)) setCut(pt.x); }) },
        head, thresholdCode(D, 'curves', { lv, set, cut, S, models: modelsOf(), series: multi ? null : curveKeys, metric, range, title: t2, colors: modelsOf().map(pyColorOf) }));
      });
      co.add(ctx.row(...plots), ctx.note(`Each measure of the rows of a set at every threshold from 0 to 1 by 0.01; the dashed line is the threshold in use. Click a curve to move the threshold there. ${multi ? 'Curve Metric' : 'Curves'} (red triangle) picks what is drawn.`));
    }

    // ---- profit
    if (profit) {
      const po = ctx.outline('Profit', { parent: ob, key: `${prefix}dtprofit`, info: 'p:predict:profit' });
      const pm = profit.matrix;
      po.add(ctx.rt({ columns: [{ key: 'actual', label: 'Actual', fmt: 'text' }, ...profit.decisions.map((d, j) => ({ key: `d${j}`, label: `Decide ${d}` }))], rows: levels.map((l, i) => ({ actual: l, ...Object.fromEntries(profit.decisions.map((_, j) => [`d${j}`, pm[i][j]])) })) }, { key: `${prefix}dtpm`, caption: `Profit Matrix of ${yName}`, sortable: false }));
      const rows = [];
      for (const m of modelsOf()) for (const set of D.sets) rows.push({ model: labelOfModel(m), set, ...S.profit(m, set, cut, pm) });
      const cols = [...(multi ? [{ key: 'model', label: 'Method', fmt: 'text' }] : []), { key: 'set', label: 'Set', fmt: 'text' }, { key: 'atT', label: 'Average Profit' }, { key: 'total', label: 'Total Profit' },
        { key: 'bestT', label: 'Best Threshold', sig: 6 }, { key: 'best', label: 'Best Average Profit' }, { key: 'theory', label: 'Threshold from the Matrix', sig: 6 }, { key: 'bayes', label: 'Most Profitable Decisions' }];
      po.add(el('div', { class: 'sm-pred-scroll' }, ctx.rt({ columns: cols, rows }, { key: `${prefix}dtprofitrows`, sortable: false })));
      const pcode = thresholdCode(D, 'profit', { lv, cut, S, models: modelsOf(), matrix: pm });
      if (pcode) po.add(ctx.code(pcode));
      if (!ctx.headless && !multi) {
        const m = D.models[0];
        const plots = D.sets.map((set) => {
          const y = GRID.map((t) => S.profit(m, set, t, pm).atT);
          const t2 = `Profit by threshold ${set}`;
          return plotWithCode(ctx, [{ type: 'scatter', mode: 'lines', x: GRID, y, name: 'Average Profit', line: { color: SM.util.PALETTE[0], width: 1.8 }, hovertemplate: 'threshold %{x:.2f}: %{y:.4g}<extra></extra>' }],
            { margin: { l: 58, r: 8, t: 26, b: 40 }, title: { text: set, font: { size: 12 } }, xaxis: { title: { text: `Threshold on Prob[${T(levels[lv])}]` }, range: [0, 1] }, yaxis: { title: { text: 'Average Profit' } },
              shapes: [{ type: 'line', x0: cut, x1: cut, yref: 'paper', y0: 0, y1: 1, line: { color: SM.util.themeColors().muted, width: 1.2, dash: 'dash' } }] },
            { width: W(360), height: 280, title: t2, select: false, onDraw: (gd) => gd.on('plotly_click', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt && Number.isFinite(pt.x)) setCut(pt.x); }) },
            head, thresholdCode(D, 'profitplot', { lv, set, cut, S, model: m, matrix: pm, title: t2 }));
        });
        po.add(ctx.row(...plots));
      }
      po.add(ctx.note(`The profit of each decision for each actual level is the Y column's Profit Matrix (Profit Matrix… in the red triangle edits it). Average Profit: per row (by Weight × Freq) when the rows at or above the threshold are called ${levels[lv]} and the others ${levels[o]}; Best Threshold: the one of the set's probabilities with the most; Threshold from the Matrix: where calling ${levels[lv]} starts to pay if the probabilities are right; Most Profitable Decisions: each row given the decision whose expected profit by its probabilities is largest${profit.undecided ? ', Undecided among them' : ''}.`));
    }
    return ob;
  }

  /* ======================================================================
     GROUP METRICS (beyond JMP): a fairness audit of a two-level classifier
     ====================================================================== */
  const GM_COLS = [['n', 'N'], ['base_rate', 'Base Rate'], ['selection_rate', 'Selection Rate'], ['accuracy', 'Accuracy'], ['auc', 'AUC'], ['fpr', 'False Positive Rate'],
    ['fnr', 'False Negative Rate'], ['precision', 'Precision'], ['tpr', 'True Positive Rate'], ['cut', 'Threshold']];
  const GM_LABEL = Object.fromEntries(GM_COLS);

  /* Group Metrics of a Decision Threshold's data D: of its one model, or, when its models are named (Fit Many
     Models' methods, several or one), of each alike, a row per method and group. opts: scope, prefix, keys
     (the Decision Threshold's option keys: cut, level, rate), save and probName (Save Decision Column, as the
     Decision Threshold's), colorOf and pyColorOf (each model's colour in the page and in the code). */
  async function groupMetrics(ctx, parent, D, opts = {}) {
    const { scope = null, prefix = '', keys = {} } = opts;
    if (!D || !D.models || !D.models.length) return null;
    const gid = ctx.opt('groupMetrics', null, scope);
    const gcol = gid ? ctx.col(gid) : null;
    if (!gcol) return null;
    const K = { cut: keys.cut || 'dtCut', level: keys.level || 'dtLevel', rate: keys.rate || 'dtTrueRate' };
    const m0 = D.models[0];
    const named = D.models.length > 1 || !!(m0.code && m0.code[0] !== 'fitted');
    const labelOf = (m) => m.label || '';
    const colorOf = opts.colorOf || ((m) => SM.util.PALETTE[Math.max(0, D.models.indexOf(m)) % SM.util.PALETTE.length]);
    const pyColorOf = opts.pyColorOf || ((m) => SM.util.PALETTE[Math.max(0, D.models.indexOf(m)) % SM.util.PALETTE.length]);
    // the Decision Threshold's threshold, target level and true event rate, and the thresholds typed per group: this By group's
    let lv = dtOpt(ctx, K.level, D.target ?? 1, scope);
    lv = lv === 0 || lv === 1 ? lv : 1;
    let cut = Number(dtOpt(ctx, K.cut, 0.5, scope));
    if (!(cut >= 0 && cut <= 1)) cut = 0.5;
    const rate0 = dtOpt(ctx, K.rate, null, scope);
    const S = thresholdState(D, lv, rate0 == null ? null : Number(rate0));
    const mode = ['common', 'typed', 'fpr'].includes(ctx.opt('gmMode', 'common', scope)) ? ctx.opt('gmMode', 'common', scope) : 'common';
    const typed = dtOpt(ctx, 'gmCuts', null, scope) || {};
    const setWanted = ctx.opt('gmSet', null, scope);
    const refWanted = ctx.opt('gmRef', null, scope);
    const levels = D.levels, values = D.values || D.levels, o = 1 - lv;
    const probName = opts.probName || ((label) => `Prob[${label}]`);
    const probOf = (m, cv) => { const p1 = cv ? m.p_cv : m.p, p0 = cv ? m.p0_cv : m.p0; return lv === 1 ? p1 : (p0 || p1.map((q) => 1 - q)); };
    const head = D.plots && D.plots.head_code ? `${D.plots.head_code}${D.plots.select ? `\n${D.plots.select}` : ''}` : null;
    let r = null, per = [];
    const ob = ctx.outline(`Group Metrics: ${gcol.name}`, { parent, key: `${prefix}groups`, info: 'p:predict:groups', menu: () => [
      { label: 'Group Column…', action: () => pickGroup(ctx, scope) },
      { label: 'Thresholds', submenu: () => [['common', 'The Decision Threshold\'s, for Every Group'], ['typed', 'Typed per Group'], ['fpr', 'Equal False Positive Rates']].map(([k, l]) => ({ label: l, checked: k === mode, action: () => ctx.set('gmMode', k, scope) })) },
      named ? { label: 'Save Decision Column', disabled: !r, submenu: () => D.models.map((m, i) => ({ label: labelOf(m), action: () => saveDecision(m, i) })) }
        : { label: 'Save Decision Column', disabled: !r, action: () => saveDecision(m0, 0) },
      { label: 'Remove', action: () => ctx.set('groupMetrics', null, scope) },
    ] });
    const pay = { group: gcol.name, at: D.points.rows, actual: D.points.actual, sets: D.points.set, w: D.points.w, cut, cuts: mode === 'typed' ? typed : null, equal: mode === 'fpr' ? 'fpr' : mode === 'typed' ? 'typed' : 'none',
      reference: refWanted, set_name: setWanted, target: lv, adjust: S.rate != null ? { a: S.A, b: S.B } : null };
    if (named) {
      const cvAll = D.models.every((m) => Array.isArray(m.p_cv));
      Object.assign(pay, { head, models: D.models.map((m) => ({ label: labelOf(m), prob: probOf(m, false), prob_cv: cvAll ? probOf(m, true) : null, expr: (m.code && m.code[0]) || null, expr_cv: (m.code && m.code[1]) || null })) });
    } else Object.assign(pay, { prob: probOf(m0, false), head });
    try { r = await ctx.call('predict.groups', pay); } catch (e) { ob.add(ctx.error(e)); return ob; }
    per = r.models ? r.models.map((q, i) => ({ ...q, model: D.models[i] })) : [{ label: null, rows: r.rows, thresholds: r.thresholds, target_fpr: r.target_fpr, model: m0 }];
    // the controls: the set, the reference group, typed thresholds (every method's)
    const sel = (label, choices, cur, key) => {
      const x = el('select', { 'aria-label': label }, ...choices.map((c) => el('option', { value: c, text: c })));
      x.value = cur;
      x.addEventListener('change', () => ctx.set(key, x.value, scope));
      return el('label', null, el('span', { text: label }), x);
    };
    const ctl = el('div', { class: 'sm-pred-groups', 'data-noexport': '' }, sel('Set', r.sets, r.set, 'gmSet'), sel('Reference group', r.labels, r.reference, 'gmRef'));
    if (mode === 'typed') {
      for (const lab of r.labels) {
        const inp = el('input', { type: 'text', inputmode: 'decimal', size: 6, class: 'sm-pred-input', 'aria-label': `Threshold of ${lab}` });
        inp.value = String(typed[lab] ?? cut);
        const apply = () => { const v = SM.table.toNumber(inp.value.replace(',', '.')); if (v >= 0 && v <= 1) dtSet(ctx, 'gmCuts', { ...typed, [lab]: v }, scope); else SM.ui.toast('A threshold is a probability, from 0 to 1', { error: true }); };
        inp.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); apply(); } });
        inp.addEventListener('change', apply);
        ctl.append(el('label', null, el('span', { text: lab }), inp));
      }
    }
    ob.add(ctl);
    const rows = per.flatMap((q) => q.rows.map((row) => (named ? { method: q.label, ...row } : row)));
    const lead = named ? [{ key: 'method', label: 'Method', fmt: 'text' }] : [];
    const refCell = (row, c) => (row.reference && c.key === 'group' ? 'sm-pred-ref' : '');
    ob.add(el('div', { class: 'sm-pred-scroll' }, ctx.rt({ columns: [...lead, { key: 'group', label: gcol.name, fmt: 'text' }, ...GM_COLS.map(([k, l]) => ({ key: k, label: l, digits: k === 'n' ? null : 4, hidden: k === 'tpr' }))], rows },
      { key: `${prefix}groups`, sortable: false, caption: `${r.set}: ${levels[lv]} when its probability ≥ the group's threshold${named ? ', each method' : ''}`, cellClass: refCell })));
    const dcols = [...lead, { key: 'group', label: gcol.name, fmt: 'text' }];
    for (const k of ['selection_rate', 'accuracy', 'auc', 'fpr', 'fnr', 'precision']) dcols.push({ key: `d_${k}`, label: `${GM_LABEL[k]} Difference`, digits: 4 }, { key: `r_${k}`, label: `${GM_LABEL[k]} Ratio`, digits: 4, hidden: !['selection_rate', 'fpr', 'fnr'].includes(k) });
    ob.add(el('div', { class: 'sm-pred-scroll' }, ctx.rt({ columns: dcols, rows }, { key: `${prefix}groupdiff`, sortable: false, caption: `Against the reference group, ${r.reference}: the difference (group − reference) and the ratio (group / reference)${named ? ', within each method' : ''}`, cellClass: refCell })));
    const labs = r.labels.map(T);
    if (!ctx.headless && !named) {
      const traces = [
        { type: 'bar', x: labs, y: per[0].rows.map((q) => q.fpr), name: 'False Positive Rate', marker: { color: SM.util.PALETTE[0] }, hovertemplate: '%{x}: FPR %{y:.4f}<extra></extra>' },
        { type: 'bar', x: labs, y: per[0].rows.map((q) => q.fnr), name: 'False Negative Rate', marker: { color: SM.util.PALETTE[1] }, hovertemplate: '%{x}: FNR %{y:.4f}<extra></extra>' },
      ];
      const w = W(Math.max(300, 90 * r.labels.length + 160));
      const code = r.code ? `${r.code}\n${[
        'import matplotlib.pyplot as plt',
        'res = pd.DataFrame(rows)',
        `fig, ax = plt.subplots(figsize=(${pyNum(w / 100)}, 2.8), layout="constrained")`,
        'at = np.arange(len(res))',
        `ax.bar(at - 0.2, res["fpr"], 0.4, color="${SM.util.PALETTE[0]}", label="False Positive Rate")`,
        `ax.bar(at + 0.2, res["fnr"], 0.4, color="${SM.util.PALETTE[1]}", label="False Negative Rate")`,
        'ax.set_xticks(at, res["group"])', `ax.set_xlabel(${J(gcol.name)})`, 'ax.set_ylabel("Rate")', `ax.set_title(${J(`False positive and negative rates by ${gcol.name}`)}, fontsize=10, wrap=True)`,
        'ax.legend(frameon=False, fontsize=8)', 'plt.show()'].join('\n')}` : null;
      ob.add(ctx.row(withCode(ctx.plot(traces, { barmode: 'group', showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, margin: { l: 50, r: 10, t: 30, b: 44 },
        xaxis: { title: { text: T(gcol.name) }, type: 'category' }, yaxis: { title: { text: 'Rate' }, rangemode: 'tozero' } }, { width: w, height: 280, title: `False positive and negative rates by ${gcol.name}`, select: false }), code ? ctx.code(code) : null)));
    } else if (!ctx.headless) {
      // each method's false positive rates, and its false negative rates, by group: a bar per method in each group
      const w = W(Math.max(300, (40 + 22 * per.length) * r.labels.length + 170));
      const chart = (key, label) => {
        const title2 = `${key === 'fpr' ? 'False positive' : 'False negative'} rates by ${gcol.name}`;
        const traces = per.map((q) => ({ type: 'bar', x: labs, y: q.rows.map((row) => row[key]), name: T(q.label), marker: { color: colorOf(q.model) }, hovertemplate: `${T(q.label)}, %{x}: ${label} %{y:.4f}<extra></extra>` }));
        const code = r.code ? `${r.code}\n${[
          'import matplotlib.pyplot as plt',
          'res = pd.DataFrame(rows)',
          `colors = ${J(per.map((q) => pyColorOf(q.model)))}   # each method's colour, as the page draws it`,
          `fig, ax = plt.subplots(figsize=(${pyNum(w / 100)}, 2.8), layout="constrained")`,
          'at = np.arange(len(names))',
          'width = 0.8 / len(models)',
          'for i, method in enumerate(models):',
          `    v = res[res["method"] == method].set_index("group")[${J(key)}].reindex(names).astype(float)`,
          '    ax.bar(at - 0.4 + width * (i + 0.5), v, width, color=colors[i], label=method)',
          'ax.set_xticks(at, names)', `ax.set_xlabel(${J(gcol.name)})`, `ax.set_ylabel(${J(label)})`, `ax.set_title(${J(title2)}, fontsize=10, wrap=True)`,
          'ax.legend(frameon=False, fontsize=8)', 'plt.show()'].join('\n')}` : null;
        return withCode(ctx.plot(traces, { barmode: 'group', showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, margin: { l: 50, r: 10, t: 30, b: 44 },
          xaxis: { title: { text: T(gcol.name) }, type: 'category' }, yaxis: { title: { text: label }, rangemode: 'tozero' } }, { width: w, height: 280, title: title2, select: false }), code ? ctx.code(code) : null);
      };
      ob.add(ctx.row(chart('fpr', 'False Positive Rate'), chart('fnr', 'False Negative Rate')));
    }
    if (ctx.headless && r.code) ob.add(ctx.code(r.code));
    const how = mode === 'fpr' ? `each group's threshold solved${named ? ' for each method' : ''} so that its false positive rate is nearest the reference group's${named ? '' : ` (${fmt(r.target_fpr, { sig: 4 })})`} at the Decision Threshold's ${fmt(cut, { sig: 6 })}`
      : mode === 'typed' ? 'the thresholds typed for each group (the Decision Threshold\'s where none is)' : `the Decision Threshold's ${fmt(cut, { sig: 6 })} for every group`;
    ob.add(ctx.note(`The ${r.set.toLowerCase()} rows of each group of ${gcol.name} (a column that need not be a factor), called ${levels[lv]} by ${how}${named ? ', each method by its own probabilities' : ''}. Base rate: the group's share of ${levels[lv]}; selection rate: its share called ${levels[lv]}. A false positive rate much higher in one group, or a false negative rate much lower, is the unequal treatment an audit looks for. Counts by Weight × Freq. Not in JMP.`));

    async function saveDecision(m, i) {
      const q = per[i];
      const cols = await probColumns(ctx, opts.save || null, m, [probName(levels[lv], m)]);
      if (!cols) return;
      const name = cols[0];
      const pr = S.rate != null ? `(${fRef(name)} * ${S.A}) / (${fRef(name)} * ${S.A} + (1 - ${fRef(name)}) * ${S.B})` : fRef(name);
      const arms = r.labels.map((lab, j) => { const v = r.values[j]; const tq = q.thresholds[lab]; return v == null ? null : `${fVal(v)}, ${fNum(tq == null ? 2 : tq)}`; }).filter(Boolean);
      const expr = inGroup(ctx, `If(${pr} >= Match(${fRef(gcol.name)}, ${arms.join(', ')}, ${fNum(cut)}), ${fVal(values[lv])}, ${fVal(values[o])})`);
      try {
        ctx.saveFormula(`Decision ${ctx.name('y') || 'Y'} by ${gcol.name}${named ? ` ${labelOf(m)}` : ''}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`, expr, { modelingType: 'nominal', valueOrder: values.slice(),
          notes: `${levels[lv]} when ${name} is at least the threshold of the row's ${gcol.name} (${r.labels.map((lab) => `${lab} ${q.thresholds[lab] == null ? 'none' : fmt(q.thresholds[lab], { sig: 6 })}`).join(', ')}; others ${fmt(cut, { sig: 6 })}), else ${levels[o]}${ctx.byLabel ? `, for the rows of ${ctx.byLabel} (the other rows missing)` : ''}: Group Metrics of ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}` });
      } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
    }
    return ob;
  }

  /* Save Profit Columns: Profit[d] for each decision (the expected profit of
     deciding d by the row's Prob[] columns), Expected Profit (the largest)
     and Most Profitable <y> (its decision), as formulas. */
  async function saveProfit(ctx, { fit = null, data = null, model = null, yCol, save = null, saveFn = null, probName = null, S = null }) {
    const t = ctx.table;
    const levels = data ? data.levels : fit.levels;
    const values = data ? (data.values || data.levels) : (fit.values || (fit.threshold && fit.threshold.values) || fit.levels);
    const profit = profitOf(ctx, yCol, values);
    if (!profit) { SM.ui.toast(`${yCol ? yCol.name : 'The Y column'} has no Profit Matrix for these levels`, { error: true }); return; }
    const pn = probName || ((label) => `Prob[${label}]`);
    const names = await probColumns(ctx, save, model, levels.map((l) => pn(l, model)), saveFn);
    if (!names) return;
    // with a true event rate (two levels), the probabilities rescaled as the report does
    const adjusted = S && S.rate != null && levels.length === 2;
    const prob = (i) => {
      if (!adjusted) return fRef(names[i]);
      const q = `(${fRef(names[S.lv])} * ${S.A}) / (${fRef(names[S.lv])} * ${S.A} + (1 - ${fRef(names[S.lv])}) * ${S.B})`;
      return i === S.lv ? q : `(1 - ${q})`;
    };
    const suffix = `${model && model.label ? ` ${model.label}` : ''}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`;
    const from = `the Profit Matrix of ${yCol.name}, from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}${adjusted ? ` (the probabilities rescaled to a true event rate of ${S.rate})` : ''}${ctx.byLabel ? `, for the rows of ${ctx.byLabel} (the other rows missing)` : ''}`;
    try {
      // each later formula reads the Profit[] columns by the names the table gave them (a name it had gets a number)
      const made = profit.decisions.map((d, j) => {
        const expr = inGroup(ctx, levels.map((_, i) => `${prob(i)} * ${fNum(profit.matrix[i][j])}`).join(' + '));
        const c = ctx.saveFormula(`Profit[${d}]${suffix}`, expr, { notes: `the expected profit of deciding ${d}: the sum over the levels of Prob[level] times the profit of ${d} when the actual is that level, by ${from}` });
        return c ? c.name : `Profit[${d}]${suffix}`;
      });
      ctx.saveFormula(`Expected Profit${suffix}`, inGroup(ctx, `Max(${made.map(fRef).join(', ')})`), { notes: `the largest of the Profit[] columns: the expected profit of the most profitable decision, by ${from}` });
      const arms = [];
      for (let j = 0; j < made.length - 1; j++) arms.push(`${made.slice(j + 1).map((q) => `${fRef(made[j])} >= ${fRef(q)}`).join(' & ')}, ${fVal(j < values.length ? values[j] : profit.decisions[j])}`);
      const lastD = profit.decisions.length - 1;
      const expr = inGroup(ctx, `If(${arms.join(', ')}, ${fVal(lastD < values.length ? values[lastD] : profit.decisions[lastD])})`);
      ctx.saveFormula(`Most Profitable ${yCol.name}${suffix}`, expr, { modelingType: 'nominal', notes: `the decision with the largest expected profit (of equal ones the first), by ${from}` });
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  /* The Prob[] columns a formula of this report reads (names: those probName gives, one per level wanted), as
     the table names them now. Without By groups: the table's columns of those names, the platform's Save
     Predicteds (save, or saveFn) run first when one is not there. In a By group every group has its own model,
     and Save Predicteds of another group makes columns of the same names: the group's own are saved (once
     for the session while the model is the same) and read by the names the table gave them. null when there
     are none (a toast says why). */
  async function probColumns(ctx, save, model, names, saveFn = null) {
    const t = ctx.table;
    const has = (nm) => t.columns.some((c) => c.name === nm);
    const fail = (e) => { SM.ui.toast(e.message || String(e), { error: true }); return null; };
    if ((ctx.where || []).length && save && !saveFn) {
      const fn = typeof save.fn === 'function' ? save.fn(model) : save.fn;
      const pay = typeof save.payload === 'function' ? save.payload(model) : save.payload;
      const memo = ctx.report._dtProb || (ctx.report._dtProb = new Map());
      const key = `${ctx.path}\u0001${fn}\u0001${JSON.stringify(pay)}\u0001${ctx.rows.join(',')}`;
      // the group's save: each of its columns' id by the name it asked for
      const pick = (ids) => names.map((nm) => (ids && ids[nm] ? t.col(ids[nm]) : null));
      const kept = pick(memo.get(key));
      if (kept.every(Boolean)) return kept.map((c) => c.name);
      let r;
      try { r = await runSave(ctx, save, model); } catch (e) { return fail(e); }
      const ids = Object.fromEntries((r.names || []).map((nm, j) => [nm, r.made[j] ? r.made[j].id : null]));
      memo.set(key, ids);
      const made = pick(ids);
      if (made.every(Boolean)) return made.map((c) => c.name);
    } else if (names.some((nm) => !has(nm)) && (save || saveFn)) {
      try { if (saveFn) await saveFn(model); else await runSave(ctx, save, model); } catch (e) { return fail(e); }
    }
    const missing = names.filter((nm) => !has(nm));
    if (missing.length) { SM.ui.toast(`Save the probabilities first (Save Columns > Save Predicteds): the formula${names.length > 1 ? 's read' : ' reads'} ${missing.join(', ')}`, { error: true }); return null; }
    return names;
  }

  /* The platform's Save Predicteds (the Prob[] columns), run before a formula that reads them. */
  async function runSave(ctx, save, model) {
    const fn = typeof save.fn === 'function' ? save.fn(model) : save.fn;
    const r = await ctx.call(fn, typeof save.payload === 'function' ? save.payload(model) : save.payload);
    const from = { notes: `from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}` };
    const made = r.names.map((nm, j) => ctx.saveColumn(nm, { rows: r.rows, values: r.prob.map((p) => p[j]) }, from));
    return { ...r, made };
  }

  /* ======================================================================
     SCORE ROWS: the model as the report fitted it, on rows it did not see
     ====================================================================== */
  /* For the platforms without a Save Prediction Formula (K Nearest Neighbors, Support Vector Machines, Decision
     Forest, Boosted Tree): the engine keeps the report's model (under the key its fit got), and this scores the
     rows of an open table with it: the report's own rows added since (those without a prediction yet), or every
     row of another table with the same columns. The predictions go to that table as columns.
       fn, payload  the platform's engine call and what it needs to find the kept model (its keep key); the call
                    gets source (the report's table) and target_rows (the rows to score, null: every row) too,
                    and is sent the table scored
       fit          predictive.report()'s (kind, levels): the names of the prediction columns
       yName        the Y column's name (Predicted <y>); info: the dialog's (i) topic */
  async function scoreRows(ctx, { fn, payload, fit, yName = null, info = null }) {
    const app = SM.app;
    const tables = (app && app.tables) || [ctx.table];
    const v = await SM.ui.form({ title: 'Score Rows', info, fields: [
      { key: 't', label: 'The table to score', type: 'select', value: ctx.table.id, choices: tables.map((t) => [t.id, t.name]), help: 'An open table: this report\'s own (its rows added since the report fitted, or all its rows), or another with the X columns the model was fitted to, found by name. The model is the report\'s as it was fitted: it is not fitted again to the rows scored.' },
      { key: 'which', label: 'Rows', type: 'select', value: 'new', choices: [['new', 'Rows without a prediction yet'], ['all', 'Every row']], help: 'Rows without a prediction yet: the rows whose prediction column (Predicted, or Prob[] of the first level) is empty or missing, such as rows added after the report fitted; in another table without those columns, every row. Every row: all of them, into new columns.' },
    ] });
    if (!v) return;
    const target = tables.find((t) => t.id === v.t) || ctx.table;
    const names = fit.kind === 'categorical' ? fit.levels.map((l) => `Prob[${l}]`) : [`Predicted ${yName || ctx.name('y')}`];
    let rows = null;
    const first = target.columns.find((c) => c.name === names[0]);
    if (v.which === 'new' && first) {
      rows = [];
      for (let i = 0; i < target.nrows; i++) { const x = first.values[i]; if (x == null || x === '' || Number.isNaN(x)) rows.push(i); }
      if (!rows.length) { SM.ui.toast(`Every row of ${target.name} has a prediction in ${first.name}`); return; }
    }
    try {
      const r = await SM.engine.call(fn, { ...payload, source: ctx.table.id, target_rows: rows }, target);
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

  /* What a Validation column gives, by predictive.validation_codes' rule: 'folds' for 4 to 50 distinct values
     (whole numbers in a numeric column; in a character one, none of them a set's name), 'sets' for 0, 1 and 2
     or Training, Validation and Test, 'bad' for anything else (the engine refuses it); null without a column. */
  const MAX_FOLDS = 50;
  const SET_NAMES = ['training', 'train', 'validation', 'valid', 'test'];
  function validationKind(c) {
    if (!c) return null;
    const seen = new Set();
    for (const v of c.values) { if (v != null && v !== '' && !(typeof v === 'number' && Number.isNaN(v))) { seen.add(c.isNumeric ? Number(v) : String(v)); if (seen.size > MAX_FOLDS) break; } }
    const vals = [...seen];
    if (c.isNumeric) {
      if (seen.size > 3 && seen.size <= MAX_FOLDS && vals.every((v) => Number.isInteger(v))) return 'folds';
      return vals.every((v) => v === 0 || v === 1 || v === 2) ? 'sets' : 'bad';
    }
    const named = vals.some((v) => SET_NAMES.includes(v.trim().toLowerCase()));
    if (!named && seen.size > 3 && seen.size <= MAX_FOLDS) return 'folds';
    return vals.every((v) => SET_NAMES.includes(v.trim().toLowerCase())) ? 'sets' : 'bad';
  }

  /* ---- the code under the Decision Threshold's parts ---------------------------------------- */
  /* The lines that pick a model's probabilities (n x 2) of a set's rows, and the rows (m). */
  function probLines(D, model, set, lv, S) {
    const expr = (model.code && model.code[set === CV ? 1 : 0]) || (set === CV ? 'oof' : 'fitted');
    const L = [set === CV ? 'm = np.ones(len(y), dtype=bool)   # every row, each predicted by the model fitted without its fold' : `m = sets == ${SETS.indexOf(set)}   # the ${set.toLowerCase()} rows`,
      `p = ${expr}[m][:, lv]   # each row's probability of ${D.levels[lv]}`];
    if (S && S.rate != null) L.push('p = p * a / (p * a + (1 - p) * b)   # rescaled to the true event rate');
    return L;
  }

  function rateLines(D, S, lv) {
    if (!S || S.rate == null) return [];
    return [`tr = sets == 0`, `rho = np.cumsum(wt[tr & (y == lv)])[-1] / np.cumsum(wt[tr])[-1]   # the training share of ${D.levels[lv]}`,
      `rate = ${pyNum(S.rate)}   # the true event rate (True Event Rate in the red triangle)`, 'a, b = rate / rho, (1 - rate) / (1 - rho)'];
  }

  /* The Python of one part: head, then the part's own lines (null without a head). */
  function thresholdCode(D, part, a) {
    const pc = D.plots;
    if (!pc || !pc.head_code) return null;
    const lv = a.lv;
    const pre = pc.select ? [pc.select] : [];
    const wline = 'wt = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)   # each row\'s Weight x Freq';
    const lvline = `lv = ${lv}   # the target level, ${D.levels[lv]} (Target Level in the red triangle)`;
    const cutline = a.cut != null ? `cut = ${pyNum(a.cut)}   # the probability threshold` : null;
    const modelsLine = (ms) => `models = {${ms.map((m) => `${J(m.label || 'model')}: ${(m.code && m.code[0]) || 'fitted'}`).join(', ')}}   # each model's probabilities of the two levels`;
    const cvLine = (ms) => (D.sets.includes(CV) ? `crossvalidated = {${ms.map((m) => `${J(m.label || 'model')}: ${(m.code && m.code[1]) || 'oof'}`).join(', ')}}   # each row predicted without its fold` : null);
    const setsList = D.sets.filter((s) => s !== CV).map((s) => [SETS.indexOf(s), s]);
    let L;
    if (part === 'fitted') {
      const { set, model } = a;
      L = [...pre, 'import numpy as np', 'import matplotlib.pyplot as plt', lvline, cutline, wline, ...rateLines(D, a.S, lv), `names = ${J(D.levels)}`, `colors = ${J(SM.util.PALETTE.slice(0, 2))}   # each actual level's colour`,
        ...probLines(D, model, set, lv, a.S),
        'jit = np.mod(d.index.to_numpy()[m] * 0.6180339887498949, 1.0) - 0.5   # the page\'s jitter, from each row\'s number',
        figure(W(D.models.length > 1 ? 280 : 340), D.models.length > 1 ? 220 : 250),
        'for j in (0, 1):', '    r = y[m] == j', '    ax.scatter(p[r], j + 0.7 * jit[r], s=12, color=colors[j], label=names[j])',
        `ax.axvline(cut, color="${PY.fit}", linewidth=1.8, linestyle="--")   # the threshold`,
        'ax.set_xlim(0, 1)', 'ax.set_ylim(-0.6, 1.6)', 'ax.set_yticks([0, 1], names)', `ax.set_xlabel(${J(`Prob[${D.levels[lv]}]`)})`, 'ax.set_ylabel("Actual")', `ax.set_title(${J(a.title)}, fontsize=9, wrap=True)`, 'plt.show()'];
    } else if (part === 'bars') {
      const { set, model } = a;
      L = [...pre, 'import numpy as np', 'import matplotlib.pyplot as plt', pc.lib, '', '', lvline, cutline, wline, ...rateLines(D, a.S, lv), `names = ${J(D.levels)}`,
        `colors = ${J(SM.util.PALETTE.slice(0, 2))}   # each called level's colour`,
        ...probLines(D, model, set, lv, a.S),
        'tp, fp, fn, tn = counts_at(cut_table(p, y[m] == lv, wt[m]), cut)   # the counts at the threshold, by Weight x Freq',
        'o = 1 - lv',
        'count = np.zeros((2, 2))   # its rows the actual levels, its columns the levels called',
        'count[lv, lv], count[lv, o], count[o, lv], count[o, o] = tp, fn, fp, tn',
        'tot = count.sum(axis=1, keepdims=True)',
        'share = np.divide(count, tot, out=np.zeros_like(count), where=tot > 0)   # of each actual level\'s rows',
        figure(W(300), 200),
        'left = np.zeros(2)',
        'for j in (0, 1):',
        '    ax.barh([0, 1], share[:, j], left=left, color=colors[j], label="called " + names[j])',
        '    left += share[:, j]',
        'ax.set_yticks([0, 1], names)', 'ax.set_xlim(0, 1)', 'ax.set_xlabel("Portion of the actual level")', 'ax.set_ylabel("Actual")',
        `ax.set_title(${J(a.title)}, fontsize=9, wrap=True)`, 'fig.legend(loc="outside upper center", ncols=2, frameon=False, fontsize=8)', 'plt.show()'];
    } else if (part === 'tables') {
      const ms = a.models;
      const one = ms.length === 1;
      L = [...pre, 'import json', 'import numpy as np', 'import pandas as pd', pc.lib, '', '', lvline, cutline, wline, ...rateLines(D, a.S, lv), modelsLine(ms), cvLine(ms),
        `sets_shown = ${J([...setsList, ...(D.sets.includes(CV) ? [[-1, CV]] : [])])}`,
        'results = []',
        'for name, fitted_ in models.items():',
        '    for k, set_name in sets_shown:',
        '        m = sets == k if k >= 0 else np.ones(len(y), dtype=bool)',
        `        p = (fitted_ if k >= 0 else ${D.sets.includes(CV) ? 'crossvalidated[name]' : 'fitted_'})[m][:, lv]`,
        ...(a.S && a.S.rate != null ? ['        p = p * a / (p * a + (1 - p) * b)   # rescaled to the true event rate'] : []),
        '        c = cut_table(p, y[m] == lv, wt[m])',
        `        results.append({${one ? '' : '"model": name, '}"set": set_name, **rates_at(*counts_at(c, cut))})`,
        `print(pd.DataFrame(results).to_string(index=False))   # the counts (by Weight x Freq) and the measures at the threshold`].filter((l) => l != null);
    } else if (part === 'curves') {
      const { set } = a;
      const ms = a.models;
      const one = !!a.series;
      const series = one ? a.series.map((k) => [k, METRIC_LABEL[k], SM.util.PALETTE[CURVE_STYLE[k][0]], MPL_DASH[CURVE_STYLE[k][1]]]) : null;
      L = [...pre, 'import numpy as np', 'import matplotlib.pyplot as plt', pc.lib, '', '', lvline, cutline, wline, ...rateLines(D, a.S, lv),
        'grid = np.arange(101) / 100   # the thresholds 0, 0.01, ..., 1'];
      if (one) {
        L.push(...probLines(D, ms[0], set, lv, a.S), 'c = cut_table(p, y[m] == lv, wt[m])', 'at = [rates_at(*counts_at(c, t)) for t in grid]',
          figure(W(440), 300),
          `for key, label, color, style in ${pyList(series)}:`,
          '    ax.plot(grid, [np.nan if r[key] is None else r[key] for r in at], color=color, linestyle=style, linewidth=1.6, label=label)');
      } else {
        L.push(modelsLine(ms), cvLine(ms), `metric = ${J(a.metric)}   # ${METRIC_LABEL[a.metric]} (Curve Metric in the red triangle)`, `colors = ${J(a.colors)}   # each model's colour, as the page draws it`,
          figure(W(520), 300),
          'for i, (name, fitted_) in enumerate(models.items()):',
          set === CV ? '    m = np.ones(len(y), dtype=bool)' : `    m = sets == ${SETS.indexOf(set)}   # the ${set.toLowerCase()} rows`,
          `    p = ${set === CV ? 'crossvalidated[name]' : 'fitted_'}[m][:, lv]`,
          ...(a.S && a.S.rate != null ? ['    p = p * a / (p * a + (1 - p) * b)   # rescaled to the true event rate'] : []),
          '    c = cut_table(p, y[m] == lv, wt[m])',
          '    ax.plot(grid, [np.nan if r[metric] is None else r[metric] for r in (rates_at(*counts_at(c, t)) for t in grid)], color=colors[i % len(colors)], linewidth=1.6, label=name)');
      }
      L.push(`ax.axvline(cut, color="${PY.muted}", linewidth=1.2, linestyle="--")   # the threshold in use`, 'ax.set_xlim(0, 1)', `ax.set_ylim(${pyNum(a.range[0])}, ${pyNum(a.range[1])})`,
        `ax.set_xlabel(${J(`Threshold on Prob[${D.levels[lv]}]`)})`, `ax.set_ylabel(${J(one ? 'Measure' : METRIC_LABEL[a.metric])})`, `ax.set_title(${J(a.title)}, fontsize=10, wrap=True)`,
        'fig.legend(loc="outside right upper", frameon=False, fontsize=7.5)', 'plt.show()');
    } else if (part === 'roc') {
      L = [...pre, 'import json', 'import numpy as np', 'import pandas as pd', pc.lib, '', '', lvline, wline,
        `sets_shown = ${J(setsList)}`,
        'roc_tables = {}',
        'for k, set_name in sets_shown:',
        '    m = sets == k',
        `    roc_tables[set_name] = pd.DataFrame(roc_table(cut_table(${(a.model.code && a.model.code[0]) || 'fitted'}[m][:, lv], y[m] == lv, wt[m])))`,
        '    print(set_name)',
        '    print(roc_tables[set_name].to_string(index=False, max_rows=40))   # a line per cut; best marks the largest Sens-(1-Spec)'];
    } else if (part === 'profit' || part === 'profitplot') {
      const ms = part === 'profit' ? a.models : [a.model];
      L = [...pre, 'import json', 'import numpy as np', 'import pandas as pd', part === 'profitplot' ? 'import matplotlib.pyplot as plt' : null, pc.lib, '', '', lvline, cutline, wline, ...rateLines(D, a.S, lv),
        `M = np.array(${J(a.matrix)}, dtype=float)   # the Profit Matrix: its rows the actual levels, its columns the decisions${a.matrix[0].length > 2 ? ' (the last Undecided)' : ''}`,
        'o = 1 - lv', '', '',
        'def profit(c):', '    """The average profit of counts (tp, fp, fn, tn): the rows called the target level decided so, the others the other level."""',
        '    tp, fp, fn, tn = c', '    return (tp * M[lv, lv] + fn * M[lv, o] + fp * M[o, lv] + tn * M[o, o]) / (tp + fp + fn + tn)', '', ''];
      if (part === 'profit') {
        L.push(modelsLine(ms), cvLine(ms), `sets_shown = ${J([...setsList, ...(D.sets.includes(CV) ? [[-1, CV]] : [])])}`,
          'results = []', 'for name, fitted_ in models.items():', '    for k, set_name in sets_shown:',
          '        m = sets == k if k >= 0 else np.ones(len(y), dtype=bool)',
          `        p = (fitted_ if k >= 0 else ${D.sets.includes(CV) ? 'crossvalidated[name]' : 'fitted_'})[m][:, lv]`,
          ...(a.S && a.S.rate != null ? ['        p = p * a / (p * a + (1 - p) * b)'] : []),
          '        c = cut_table(p, y[m] == lv, wt[m])',
          '        at = profit(counts_at(c, cut))',
          '        cands = [(profit((0.0, 0.0, c["pos"], c["neg"])), None)] + [(profit((tp, fp, c["pos"] - tp, c["neg"] - fp)), q) for q, tp, fp in zip(c["p"], c["tp"], c["fp"])]',
          '        best = max(cands, key=lambda z: z[0])   # the first of the largest (calling none first, then the cuts from the highest)',
          '        pr = np.column_stack([1 - p, p]) if lv == 1 else np.column_stack([p, 1 - p])   # both levels\' probabilities',
          '        decide = (pr @ M).argmax(1)   # each row\'s most profitable decision (of equal ones the first)',
          '        bayes = np.cumsum(wt[m] * M[y[m], decide])[-1] / np.cumsum(wt[m])[-1]',
          '        d1, d0 = M[lv, lv] - M[lv, o], M[o, o] - M[o, lv]',
          `        results.append({${ms.length > 1 ? '"model": name, ' : ''}"set": set_name, "average profit": at, "total profit": at * (c["pos"] + c["neg"]), "best threshold": best[1], "best average profit": best[0], "threshold from the matrix": d0 / (d1 + d0) if d1 + d0 > 0 else None, "most profitable decisions": bayes})`,
          'print(pd.DataFrame(results).to_string(index=False))');
      } else {
        L.push(...probLines(D, a.model, a.set, lv, a.S), 'c = cut_table(p, y[m] == lv, wt[m])', 'grid = np.arange(101) / 100', figure(W(360), 280),
          `ax.plot(grid, [profit(counts_at(c, t)) for t in grid], color="${SM.util.PALETTE[0]}", linewidth=1.8)`,
          `ax.axvline(cut, color="${PY.muted}", linewidth=1.2, linestyle="--")`, 'ax.set_xlim(0, 1)',
          `ax.set_xlabel(${J(`Threshold on Prob[${D.levels[lv]}]`)})`, 'ax.set_ylabel("Average Profit")', `ax.set_title(${J(a.title)})`, 'plt.show()');
      }
    } else if (part === 'profitcurve') {
      const { set, model } = a;
      L = [...pre, 'import numpy as np', 'import matplotlib.pyplot as plt', lvline, wline,
        `M = np.array(${J(a.matrix)}, dtype=float)   # the Profit Matrix: its rows the actual levels, its columns the decisions`, 'o = 1 - lv',
        ...probLines(D, model, set, lv, null),
        'order = np.argsort(-p, kind="mergesort")   # highest first; equal ones in the rows\' order, as the lift curve takes them',
        'hit = y[m][order] == lv', 'ww = wt[m][order]',
        'tp, fp = np.r_[0.0, np.cumsum(np.where(hit, ww, 0.0))], np.r_[0.0, np.cumsum(np.where(hit, 0.0, ww))]',
        'pos, neg = tp[-1], fp[-1]', 'N = pos + neg',
        'portion = (tp + fp) / N', 'avg = (tp * M[lv, lv] + (pos - tp) * M[lv, o] + fp * M[o, lv] + (neg - fp) * M[o, o]) / N   # the rows taken called the level, the rest the other',
        figure(W(330), 300),
        `ax.plot(portion, avg, color="${SM.util.PALETTE[0]}", linewidth=1.8, label=${J(D.levels[lv])})`,
        `ax.plot([0, 1], [avg[0], avg[-1]], color="${PY.muted}", linewidth=1, linestyle=":")   # calling none to calling all`,
        'ax.set_xlim(0, 1)', `ax.set_xlabel(${J(`Portion called ${D.levels[lv]}`)})`, 'ax.set_ylabel("Average Profit")', `ax.set_title(${J(`Profit ${set}`)})`, 'plt.show()'];
    }
    if (!L) return null;
    return `${pc.head_code}${SEP}${L.filter((l) => l != null).join('\n')}`;
  }

  const pyList = (rows) => `[${rows.map((r) => `(${r.map(pyLit).join(', ')})`).join(', ')}]`;
  const figure = (w, h) => `fig, ax = plt.subplots(figsize=(${pyNum(w / 100)}, ${pyNum(h / 100)}), layout="constrained")`;

  SM.predict = Object.freeze({ roles, options, payload, seed, measures, classification, decisionParts, classificationItems, thresholdItem, confusion, rocCurves, liftCurves, actualByPredicted, contributions, saveItems,
    threshold, groupMetrics, cutTable, countsAt, ratesAt, rocTableRows, profitOf, thresholdState, fRef, fStr, fNum, fVal, METRICS,
    SEP, graphCode, withCode, plotWithCode,
    // the Decision Threshold's settings (dtCut, dtLevel, dtTrueRate) as the By group has them, and set for it only
    thresholdOption: dtOpt, setThresholdOption: dtSet, groupCondition,
    // Group Metrics… for a platform's own red triangle; Score Rows…; what a Validation column holds
    groupMetricsItem: (ctx, scope = null) => groupItem(ctx, null, scope), scoreRows, validationKind, MAX_FOLDS });

  SM.info.add({
    'p:predict:validation': {
      kicker: 'Predictive modeling', title: 'Validation',
      lead: 'A model that fits its training rows well may predict new rows badly. The rows can be split: the model learns from the training rows, the validation rows choose among models (how big a tree, how many trees or layers), and test rows, kept out of both, show how well the chosen model predicts.',
      sections: [{ choices: [['Validation column', 'a column with 0 (Training), 1 (Validation) and 2 (Test), or those words; rows with no value are left out. A column with more than three values holds K folds of crossvalidation (Make Validation Column, K Fold): every row trains, and the platforms that crossvalidate use those folds'], ['Validation Portion', 'with no Validation column, that share of the rows is held back for validation, drawn at random from the seed'], ['Random Seed', 'the seed of every random draw: the holdback and the model\'s own; empty draws one at the first run and keeps it with the report']] }],
    },
    'p:predict:weight': { kicker: 'Predictive modeling', title: 'Weight and Freq', lead: 'Freq: how many times a row counts. Weight: a case weight in the fit. Both count in the measures, the confusion matrices, the ROC and lift curves and the Decision Threshold, multiplied, as JMP counts them: a weight that undoes oversampling undoes it there too. A row with a missing or non-positive weight or frequency is left out.' },
    'p:predict:measures': {
      kicker: 'Predictive modeling', title: 'Measures of Fit',
      lead: 'How well the model predicts, for each set of rows. A training value much better than the validation value means the model fits noise. Right click the table, Columns, for more; Naive Model (red triangle) adds the yardstick of predicting from the training rows alone.',
      sections: [
        { heading: 'Continuous response', choices: [['RSquare', '1 - SSE/SST, SST about the set\'s own mean'], ['RASE', 'the root average squared error'], ['Mean Abs Dev', 'the mean absolute error'], ['-LogLikelihood', 'of a normal error with variance SSE/N'], ['Mean Error', 'the mean of actual less predicted: a bias (an optional column, beyond JMP)'], ['MAPE, MPE', 'the mean absolute and the mean percentage error, 100 (actual − predicted)/actual, over the rows whose actual value is not 0 (optional, beyond JMP)'], ['Median Abs Error', 'the median of the absolute errors, weighted (optional, beyond JMP)']] },
        { heading: 'Categorical response', choices: [['Entropy RSquare', '1 - LL/LL0: the log-likelihood against that of the training shares of the levels'], ['Generalized RSquare', 'Nagelkerke\'s version, which reaches 1'], ['Mean -Log p', 'the average of -log of the probability of the actual level'], ['RASE, Mean Abs Dev', 'of 1 - the probability of the actual level'], ['Misclassification Rate', 'the share of rows whose most likely level is not the actual one'], ['AUC', 'for two levels, the area under the ROC curve']] },
        { heading: 'Naive Model', text: 'Beyond JMP: a line per set for the prediction that uses no factor at all, the training rows\' mean (a continuous response) or their shares of the levels (a categorical one, whose most likely level is then the majority\'s). A model worth having beats it on the validation rows.' },
      ],
    },
    'p:predict:confusion': { kicker: 'Predictive modeling', title: 'Confusion Matrix', lead: 'For each set, the rows counted by their actual level (rows) and the most likely level the model gives them (columns), each by its Weight × Freq; the rates divide each row by its total.' },
    'p:predict:roc': {
      kicker: 'Predictive modeling', title: 'ROC Curve',
      lead: 'For each level against the others: as the cut-off on its predicted probability falls, the share of its rows caught (sensitivity) against the share of the other rows caught (1 - specificity). The area under the curve is the chance that a random row of the level scores higher than a random other row. The dot is the best cut, where Sensitivity - (1 - Specificity) is largest (JMP draws a tangent line there).',
      sections: [{ heading: 'The red triangle', choices: [['ROC Table', 'two levels: JMP\'s ROC Table, a line per cut on the target level\'s probability with 1-Specificity, Sensitivity, Sens-(1-Spec) and the counts; the best line starred']] }],
    },
    'p:predict:roctable': { kicker: 'Predictive modeling', title: 'ROC Table', lead: 'A line per distinct probability of the target level (the second level, or the Decision Threshold\'s Target Level): a row is called that level when its probability is at least Prob. 1-Specificity and Sensitivity are the point of the ROC curve there, Sens-(1-Spec) is Youden\'s J, and the counts True Pos, True Neg, False Pos and False Neg are by Weight × Freq. The star marks the line with the largest Sens-(1-Spec), the dot on the curve.' },
    'p:predict:lift': {
      kicker: 'Predictive modeling', title: 'Lift Curve',
      lead: 'The rows sorted by the predicted probability of a level, highest first: at each portion of the rows, how many times more common the level is among them than in the whole set.',
      sections: [{ heading: 'The red triangle', choices: [['Cumulative Gains', 'the share of all the level\'s rows found among the rows taken, against the portion taken (beyond JMP)'], ['Decile Lift Table', 'the rows in ten parts of equal weight, highest probability first: each part\'s rate of the level and lift, and cumulatively (beyond JMP)'], ['Table Level', 'more than two levels: the level of the decile table']] },
        { heading: 'Profit Curve', text: 'With a Profit Matrix on the Y column (two levels): the average profit per row when the rows taken are called the target level and the rest the other, against the portion taken.' }],
    },
    'p:predict:gains': { kicker: 'Predictive modeling', title: 'Cumulative Gains and the Decile Lift Table', lead: 'The rows taken highest probability of a level first. Gains: the share of all the level\'s rows among those taken (the diagonal is a random order). The decile table cuts the rows into ten parts of equal Weight × Freq (a row in the part its middle falls in; equal probabilities in the table\'s order, as the lift curve takes them): each part\'s count, the level\'s count, its rate and lift, and the cumulative rate, lift and gains. Not in JMP.' },
    'p:predict:contrib': { kicker: 'Predictive modeling', title: 'Column Contributions', lead: 'How much each factor contributes to the model, as a share of the total. A categorical factor\'s level columns are added together.' },
    'p:predict:threshold': {
      kicker: 'Predictive modeling', title: 'Decision Threshold',
      lead: 'For a response with two levels: a row is called the target level when its predicted probability of it is at least the threshold, else the other level. For each set: the rows\' probabilities by their actual level with the threshold, a bar per actual level cut by the shares called each level, the counts and rates of the confusion matrix at the threshold, and the measures, as JMP Pro\'s Decision Threshold report has them; their curves against the threshold; with a Profit Matrix, the profit. With By groups each group\'s report has its own threshold, target level and true event rate, as in JMP: moving the threshold in one group leaves the others alone.',
      sections: [
        { heading: 'The controls', choices: [['The dashed line', 'Drag it in a fitted-probability plot to move the threshold.'], ['Probability threshold', 'Type a probability from 0 to 1 (0.5) and press Enter or Apply.'], ['The slider', 'Moves the threshold by 0.01.'], ['A click on a curve', 'Moves the threshold there (Metrics by Threshold, Profit).']] },
        { heading: 'Classification at the threshold', text: 'Beside each set\'s fitted probabilities: a bar per actual level, cut into the shares of its rows (by Weight × Freq) called each level at the threshold. The target level\'s bar called the target is the sensitivity, the other level\'s bar called the other is the specificity; hover a part for its count.' },
        { heading: 'The measures', choices: [['Accuracy, Misclassification Rate', 'the share of rows called right, or wrong'], ['Sensitivity, Specificity', 'the share of the target level\'s rows called it (the true positive rate, recall), and of the others called the other level'], ['False Positive Rate, False Negative Rate', '1 − Specificity and 1 − Sensitivity'], ['Precision', 'the share of the rows called the target level that are it'], ['Negative Predictive Value', 'the share of the rows called the other level that are it (an optional column)'], ['F1 Score', '2 Precision Sensitivity / (Precision + Sensitivity)'], ['MCC', 'Matthews\' correlation coefficient: the Pearson correlation of actual and called as 0/1 variables'], ['Portion Called', 'the share of rows called the target level (an optional column)']] },
        { heading: 'The red triangle', choices: [['Target Level', 'the level whose probability is cut (the second at first)'], ['Set Probability Threshold…', 'the threshold in a dialog'], ['Set Threshold to', 'the threshold with the best accuracy, F1, MCC, Sensitivity + Specificity or profit on the validation rows (the crossvalidated ones with K Fold, else the training rows); beyond JMP'], ['Metric Curves, Curves', 'the measures against the threshold, and which'], ['True Event Rate…', 'the share of the target level in the population: the probabilities of a model fitted on oversampled rows are rescaled to it before the threshold'], ['Profit Matrix…', 'the Y column\'s Profit Matrix (its column property)'], ['Save Threshold Formula', 'a formula column: If(Prob[level] ≥ threshold, level, other level); the platform\'s probabilities are saved first when the Prob[] column is not in the table'], ['Save Profit Columns', 'with a Profit Matrix: Profit[decision], Expected Profit and Most Profitable, as formulas of the Prob[] columns']] },
        { heading: 'By groups', text: 'Each By group has its own threshold, target level and true event rate (and Group Metrics\' typed thresholds), kept with the report and in a saved project; a group not yet given its own takes the report\'s, so a project saved with one threshold for every group opens with it in each. Save Threshold Formula in a group reads that group\'s Prob[] column (the group\'s probabilities are saved first, once, since every group has its own model) and gives the other groups\' rows no value: If(:by == group, If(Prob ≥ threshold, …), .). Save Profit Columns and Group Metrics\' Save Decision Column do the same.' },
        { heading: 'Differences from JMP', text: 'The measures by portion are the lift outline\'s. Set Threshold to, the True Event Rate and Save Threshold Formula are this page\'s. Counts are by Weight × Freq, as JMP counts them.' },
      ],
    },
    'p:predict:profit': { kicker: 'Predictive modeling', title: 'Profit', lead: 'The Y column\'s Profit Matrix (Cols > Column Properties > Profit Matrix, or Profit Matrix… in the Decision Threshold) gives the profit of each decision for each actual level. Average Profit is per row, by Weight × Freq, at the threshold; Best Threshold the probability of the set with the most; Threshold from the Matrix, (M[o,o] − M[o,t]) / ((M[t,t] − M[t,o]) + (M[o,o] − M[o,t])) for the target t and the other level o, where calling t starts to pay if the probabilities are right; Most Profitable Decisions each row decided by its largest expected profit, Σ p(level) M[level, decision] (Undecided too). The Profit Curve is the average profit against the portion of rows called the target level, highest probability first.' },
    'p:predict:groups': { kicker: 'Predictive modeling', title: 'Group Metrics', lead: 'A fairness audit of a two-level classifier: the measures of each group of a column (that need not be a factor), and their differences and ratios to a reference group. In Fit Many Models, each method the Decision Threshold compares, alike: a line per method and group, and a bar per method in the charts. Beyond JMP.' },
  });
}(typeof self !== 'undefined' ? self : this));
