/* ==========================================================================
   SMUI.HTML: ANALYZE > PREDICTIVE MODELING > BOOTSTRAP FOREST, BOOSTED TREE

   JMP Pro's two tree ensembles on scikit-learn's decision trees (the backend
   is resources/py/smui/ensemble.py): a split on a nominal X takes two groups
   of its levels, as JMP's do. The launch dialog has JMP's roles, and
   under them the Specification panel JMP shows in a window of its own
   after OK. The report, in JMP's order:

     Model Validation-Set Summaries   every fit of Multiple Fits, the one
                                      shown marked (a click shows another)
     Specifications                   the settings used
     Overall Statistics               the measures of each set (Individual
                                      Trees and the out-of-bag estimate for
                                      a forest), the Confusion Matrix
     Cumulative Validation            each set's statistic against the
                                      number of trees or layers, the number
                                      kept marked; Cumulative Details
     Per-Tree Summaries               (a forest) each tree's splits and its
                                      in-bag and out-of-bag losses
     Column Contributions             the splits on each column, their SS or G²

   and from the red triangle Permutation Importance, Plot Actual by
   Predicted, ROC and Lift Curves, Show Trees, the Prediction Profiler,
   Save Columns (with Score Rows: the model as fitted on rows added since,
   or another open table) and the specification again.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));

  const KIND = {
    forest: { id: 'forest', label: 'Bootstrap Forest', what: 'trees', one: 'Tree', many: 'Trees', info: 'p:forest', more: { label: 'Bootstrap Forest', id: 'help-p-forest' } },
    boosted: { id: 'boosted', label: 'Boosted Tree', what: 'layers', one: 'Layer', many: 'Layers', info: 'p:boosted', more: { label: 'Boosted Tree', id: 'help-p-boosted' } },
  };
  const STAT_LABEL = { rsquare: 'RSquare', rase: 'RASE', mad: 'Mean Abs Dev', entropy_rsquare: 'Entropy RSquare', mean_neg_log_p: 'Mean -Log p', misclassification: 'Misclassification Rate' };

  /* JMP's default Number of Terms Sampled per Split (JMP 16 and later):
     p - floor(p/4), about three quarters of the X columns. */
  const defaultTerms = (p) => Math.max(1, p - Math.floor(p / 4));

  /* The specification, as JMP's windows lay it out. dflt: a value, or a
     function of the number of terms (p) and the other settings. */
  const FIELDS = {
    forest: [
      { panel: 'Forest', key: 'trees', label: 'Number of Trees in the Forest', type: 'int', dflt: 100, min: 1, max: 5000,
        help: 'How many trees are grown, from 1 to 5000 (fewer when Early Stopping stops them). More trees average away more of the noise of single trees and take longer; JMP\'s default is 100.' },
      { panel: 'Forest', key: 'terms', label: 'Number of Terms Sampled per Split', type: 'int', dflt: (p) => defaultTerms(p), min: 1,
        help: 'How many X columns each split may choose from, drawn at random for every split (scikit-learn\'s max_features); a categorical X is one column, as a continuous one is (a Missing column beside a continuous one with missing values counts too). Empty: JMP\'s default since JMP 16, p − floor(p/4) of the p X columns (13 terms: 10; the grey number in the box); earlier versions took floor(p/4). Fewer terms make the trees differ more from each other.' },
      { panel: 'Forest', key: 'rate', label: 'Bootstrap Sample Rate', type: 'num', dflt: 1, min: 0, max: 1, open: true,
        help: 'The share of the training rows drawn, with replacement, for each tree: 1 (the default) draws as many rows as there are, which leaves about 37% of them out of each tree (its out-of-bag rows). A smaller share gives each tree fewer rows and more out-of-bag ones. Above 0 and at most 1.' },
      { panel: 'Forest', key: 'minSplits', label: 'Minimum Splits per Tree', type: 'int', dflt: 10, min: 0,
        help: 'Each tree keeps at least this many splits (10), when it can grow them; beyond them a split stays only while it lowers the tree\'s out-of-bag loss, as JMP stops its trees. It does nothing with Tree Size set to Grow to Maximum Splits.' },
      { panel: 'Forest', key: 'maxSplits', label: 'Maximum Splits per Tree', type: 'int', dflt: 2000, min: 1, max: 100000,
        help: 'The most splits a tree may have (2000): scikit-learn grows each tree best first, the split that lowers the impurity most next, until it has this many or no split is left.' },
      { panel: 'Forest', key: 'minSize', label: 'Minimum Size Split', type: 'int', dflt: 5, min: 1,
        help: 'The fewest rows a split may leave on either side (scikit-learn\'s min_samples_leaf; JMP\'s default 5). Larger values give smaller trees that fit less noise.' },
      { panel: 'Forest', key: 'stop', label: 'Tree Size', type: 'select', dflt: 'oob', choices: [['oob', 'Stop by Out-of-Bag Loss (JMP)'], ['none', 'Grow to Maximum Splits (scikit-learn)']],
        help: 'Stop by Out-of-Bag Loss (the default, as JMP describes its trees): past Minimum Splits per Tree each tree is cut back at the first split that does not lower the loss of the rows it did not see. Grow to Maximum Splits: scikit-learn\'s trees are kept whole.' },
      { panel: 'Forest', key: 'early', label: 'Early Stopping', type: 'check', dflt: true,
        help: 'With validation rows: the trees are grown one at a time, growth stops when the last tenth of the trees asked for (at least 5) has not improved the validation RSquare (Entropy RSquare for a categorical response), and the best number of trees is kept (the first k trees do not depend on how many are grown, so that is the forest of that many trees). Without validation rows it does nothing, and a K-fold Validation column has none (every row trains).' },
      { panel: 'Multiple Fits', key: 'multi', label: 'Multiple Fits over Number of Terms', type: 'check', dflt: false,
        help: 'Fits a forest for each number of terms from Number of Terms Sampled per Split up to Max Number of Terms, each about 1.25 times the one before (JMP\'s example: 4, 5, 6, 8, 10), and shows the one with the best validation statistic (the out-of-bag one without validation rows); Model Validation-Set Summaries lists them all.' },
      { panel: 'Multiple Fits', key: 'maxTerms', label: 'Max Number of Terms', type: 'int', dflt: (p) => p, min: 1,
        help: 'The largest number of terms Multiple Fits tries; empty: every X column. Used only with Multiple Fits.' },
    ],
    boosted: [
      { panel: 'Boosting', key: 'layers', label: 'Number of Layers', type: 'int', dflt: 50, min: 1, max: 20000,
        help: 'How many small trees are fitted in turn, from 1 to 20000 (fewer when Early Stopping stops them), each to what the layers before it left; JMP\'s default is 50. A small Learning Rate needs more layers.' },
      { panel: 'Boosting', key: 'splits', label: 'Splits per Tree', type: 'int', dflt: 3, min: 1, max: 1000,
        help: 'The splits of each layer\'s tree (3), grown best first. 1 gives stumps, which add up the factors\' effects one at a time; more splits let a layer take up interactions.' },
      { panel: 'Boosting', key: 'learn', label: 'Learning Rate', type: 'num', dflt: 0.1, min: 0, max: 1, open: true,
        help: 'The share of each layer\'s fit that is added to the model (0.1), above 0 and at most 1. A small rate learns slowly and needs more layers, and usually predicts new rows better.' },
      { panel: 'Boosting', key: 'minSize', label: 'Minimum Size Split', type: 'int', dflt: 5, min: 1,
        help: 'The fewest rows a split may leave on either side (scikit-learn\'s min_samples_leaf; JMP\'s default 5).' },
      { panel: 'Multiple Fits', key: 'multi', label: 'Multiple Fits over Splits and Learning Rate', type: 'check', dflt: false,
        help: 'Fits a boosted tree for every Splits per Tree from the one above up to Max Splits per Tree, each with every learning rate from Learning Rate up to Max Learning Rate in steps of 0.1, and shows the one with the best validation statistic. It needs validation rows (without them one boosted tree is fitted), and at most 60 fits.' },
      { panel: 'Multiple Fits', key: 'maxSplits', label: 'Max Splits per Tree', type: 'int', dflt: (p, s) => s.splits ?? 3, min: 1, max: 1000,
        help: 'The largest Splits per Tree that Multiple Fits tries; empty: Splits per Tree.' },
      { panel: 'Multiple Fits', key: 'maxLearn', label: 'Max Learning Rate', type: 'num', dflt: (p, s) => s.learn ?? 0.1, min: 0, max: 1, open: true,
        help: 'The largest learning rate that Multiple Fits tries, in steps of 0.1 from Learning Rate; empty: Learning Rate.' },
      { panel: 'Stochastic Boosting', key: 'rowRate', label: 'Row Sampling Rate', type: 'num', dflt: 1, min: 0, max: 1, open: true,
        help: 'The share of the training rows drawn, without replacement, for each layer (scikit-learn\'s subsample); 1, the default, uses every row. Below 1 is stochastic boosting, which often predicts better. JMP stratifies the draw by a categorical response; scikit-learn does not.' },
      { panel: 'Stochastic Boosting', key: 'colRate', label: 'Column Sampling Rate', type: 'num', dflt: 1, min: 0, max: 1, open: true,
        help: 'The share of the columns tried at each split (scikit-learn\'s max_features; a categorical X is one column); 1, the default, tries every column. JMP draws its columns once per layer.' },
      { panel: 'Stochastic Boosting', key: 'early', label: 'Early Stopping', type: 'check', dflt: true,
        help: 'With validation rows (on by default): the fit stops at the first layer that does not improve the validation RSquare (Entropy RSquare for a categorical response) and keeps the layers before it, as JMP does. Without validation rows every layer is kept, and a K-fold Validation column has none (every row trains).' },
    ],
  };

  /* A settings object's error, or null. */
  function checkSettings(kind, s) {
    for (const f of FIELDS[kind]) {
      const v = s ? s[f.key] : null;
      if (v == null || f.type === 'check' || f.type === 'select') continue;
      if (typeof v !== 'number' || !Number.isFinite(v)) return `${f.label}: not a number`;
      if (f.type === 'int' && !Number.isInteger(v)) return `${f.label} is a whole number`;
      if (f.min != null && (f.open ? v <= f.min : v < f.min)) return `${f.label} is ${f.open ? 'more than' : 'at least'} ${f.min}`;
      if (f.max != null && v > f.max) return `${f.label} is at most ${f.max}`;
    }
    if (kind === 'forest' && s && s.minSplits != null && s.maxSplits != null && s.minSplits > s.maxSplits) return 'Minimum Splits per Tree is more than Maximum Splits per Tree';
    return null;
  }

  const numOf = (s) => { const t = String(s).trim().replace(',', '.').replace('−', '-'); return t === '' ? null : Number(t); };

  /* ---- the launch dialog's own part: the Specification panel ------------------------------ */
  function launchExtra(kind) {
    return (api, spec) => {
      const cur = { ...((spec && spec.options && spec.options.settings) || {}) };
      const inputs = {};
      const head = el('p', { class: 'sm-ens-head' });
      const panels = new Map();
      for (const f of FIELDS[kind]) {
        if (!panels.has(f.panel)) panels.set(f.panel, el('fieldset', { class: 'sm-ens-panel' }, el('legend', { text: f.panel })));
        let input;
        if (f.type === 'check') {
          input = el('input', { type: 'checkbox' });
          input.checked = cur[f.key] ?? f.dflt;
        } else if (f.type === 'select') {
          input = el('select', null, ...f.choices.map(([v, l]) => el('option', { value: v, text: l })));
          input.value = cur[f.key] ?? f.dflt;
        } else {
          input = el('input', { type: 'text', inputmode: 'decimal', size: 7, class: 'sm-ens-input' });
          input.value = cur[f.key] != null ? String(cur[f.key]) : typeof f.dflt === 'function' ? '' : String(f.dflt);
        }
        input.setAttribute('aria-label', f.label);
        inputs[f.key] = input;
        panels.get(f.panel).append(f.type === 'check'
          ? el('label', { class: 'sm-ens-check' }, input, el('span', { text: f.label }))
          : el('label', { class: 'sm-ens-field' }, el('span', { text: f.label }), input));
      }
      const hint = el('p', { class: 'sm-ens-hint' });
      const box = el('div', { class: 'sm-ens-spec' }, el('h4', { text: kind === 'boosted' ? 'Gradient-Boosted Trees Specification' : 'Bootstrap Forest Specification' }), head,
        el('div', { class: 'sm-ens-panels' }, ...panels.values()), hint);
      const read = () => {
        const out = {};
        for (const f of FIELDS[kind]) {
          const i = inputs[f.key];
          if (f.type === 'check') out[f.key] = i.checked;
          else if (f.type === 'select') out[f.key] = i.value;
          else { const v = numOf(i.value); if (v != null) out[f.key] = v; }
        }
        return out;
      };
      const update = (state) => {
        const p = ((state && state.x) || []).length;
        head.textContent = `Number of Rows: ${api.table.nrows}    Number of Terms: ${p}`;
        const s = read();
        for (const f of FIELDS[kind]) if (typeof f.dflt === 'function') inputs[f.key].placeholder = p ? String(f.dflt(p, s)) : '';
        const valid = !!(state && state.validation && state.validation.length);
        // a K-fold Validation column (more than three values): every row trains, so there are no validation rows to stop by
        const folds = valid && SM.predict.validationKind && SM.predict.validationKind(api.table.col(state.validation[0])) === 'folds';
        hint.textContent = folds ? (kind === 'boosted'
          ? 'The Validation column holds K folds: every row trains, so Early Stopping is off and Multiple Fits makes one fit. Each fold is predicted by the boosted tree of these settings grown on the other folds (the Crossvalidation line of Overall Statistics).'
          : 'The Validation column holds K folds: every row trains, so Early Stopping is off and Multiple Fits chooses by the out-of-bag statistics. Each fold is predicted by the forest of these settings grown on the other folds (the Crossvalidation line of Overall Statistics).')
          : valid ? '' : kind === 'boosted' ? 'Early Stopping and Multiple Fits need validation rows: a Validation column, or a Validation Portion below.'
            : 'Early Stopping needs validation rows: a Validation column, or a Validation Portion below. Without them Multiple Fits chooses by the out-of-bag statistics.';
      };
      api.onRolesChange(update);
      for (const i of Object.values(inputs)) i.addEventListener('input', () => update(api.state));
      update(api.state);
      return {
        el: box,
        helpHeading: kind === 'boosted' ? 'Gradient-Boosted Trees Specification' : 'Bootstrap Forest Specification',
        help: FIELDS[kind].map((f) => [f.label, f.help]),
        read: () => ({ options: { settings: read() } }),
        recall: (saved) => {
          const so = (saved && saved.options && saved.options.settings) || null;
          if (!so) return;
          for (const f of FIELDS[kind]) {
            const i = inputs[f.key], v = so[f.key];
            if (v === undefined) continue;
            if (f.type === 'check') i.checked = !!v; else i.value = v == null ? '' : String(v);
          }
        },
      };
    };
  }

  /* ---- the report's calls ---------------------------------------------------------------- */
  const settingsOf = (ctx) => ({ ...(ctx.opt('settings', null) || {}) });

  function payloadOf(ctx, kind) {
    const y = ctx.role('y');
    return { y: y ? y.name : null, x: ctx.names('x'), kind, ...SM.predict.payload(ctx), settings: settingsOf(ctx), shown: ctx.opt('shownFit', null) };
  }

  /* A call that prints 'smui:progress <what> ...' lines: its progress in the
     report while it runs (and in the report bar, which a redraw keeps). */
  async function withProgress(ctx, fn, payload, what, label, unit) {
    if (ctx.headless) return ctx.call(fn, payload);
    const who = `${label}${ctx.byLabel ? ` (${ctx.byLabel})` : ''}`;
    const note = el('p', { class: 'sm-ob-note sm-ens-progress', role: 'status', text: `${who}: fitting…` });
    ctx.container.append(note);
    const off = SM.engine.on('progress', (p) => {
      if (!p || p.what !== what) return;
      const text = `${who}: ${p.done} of ${p.total} ${unit}…`;
      note.textContent = text;
      if (ctx.report && ctx.report.noteEl) ctx.report.noteEl.textContent = text;
    });
    try { return await ctx.call(fn, payload); } finally { off(); note.remove(); }
  }

  // the key the engine keeps the report's fit under (Score Rows): the report and its By group
  const keepOf = (ctx) => `${ctx.report.id}|${ctx.byLabel || ''}`;

  /* Tables that may be wide scroll inside their own box (a phone). */
  const wide = (tbl) => el('div', { class: 'sm-ens-scroll' }, tbl);

  /* The same for the tables SM.predict builds into an outline. */
  function scrollTables(ob) {
    for (const t of ob.body.querySelectorAll('table.sm-rt, table.sm-kv')) {
      if (t.parentElement.classList.contains('sm-ens-scroll')) continue;
      const box = el('div', { class: 'sm-ens-scroll' });
      t.before(box);
      box.append(t);
    }
  }

  function setColors() {
    const dark = SM.util.themeColors().dark;
    return { Training: SM.report.BASE, Validation: dark ? '#f0a35e' : '#c0620f', Test: dark ? '#72c97f' : '#2e7d3a', 'Out of Bag': dark ? '#bba6dc' : '#6c5b7b' };
  }

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx, kind) {
    const K = KIND[kind];
    ctx.ens = null;
    const base = payloadOf(ctx, kind);
    if (!base.y || !base.x.length) { ctx.container.append(ctx.warn('Choose a Y, Response and at least one X, Factor (Model Dialog in the red triangle).')); return; }
    // the fit, with the page's choice the graphs' code draws with (the statistic Cumulative Validation shows)
    const r = await withProgress(ctx, 'ensemble.fit', { ...base, plot: { stat: ctx.opt('cumStat', null) }, keep: keepOf(ctx) }, kind, K.label, K.what);
    ctx.ens = { r, base, kind };
    const box = ctx.container;
    for (const t of r.notes || []) box.append(ctx.note(t));
    if (r.multi && r.summaries) summariesOutline(ctx, r, K);
    specOutline(ctx, r, K);
    overallOutline(ctx, r, K);
    if (ctx.opt('cumulative', true)) cumulativeOutline(ctx, r, K);
    if (kind === 'forest' && ctx.opt('pertree', true)) perTreeOutline(ctx, r);
    if (ctx.opt('contrib', true)) contribOutline(ctx, r, K);
    if (ctx.opt('permutation', false)) await permutationOutline(ctx, base, r, K);
    if (r.response === 'continuous' && ctx.opt('abp', false)) SM.predict.actualByPredicted(ctx, box, r.fit);
    if (r.response === 'categorical' && ctx.opt('roc', false)) SM.predict.rocCurves(ctx, box, r.fit);
    if (r.response === 'categorical' && ctx.opt('lift', false)) SM.predict.liftCurves(ctx, box, r.fit);
    if (r.response === 'categorical') SM.predict.decisionParts(ctx, box, r.fit, null, '', { save: { fn: 'ensemble.save', payload: base } });
    const tv = ctx.opt('trees', null);
    if (tv && !ctx.headless) await treeViews(ctx, base, r, K, tv);
    if (ctx.opt('profiler', false) && !ctx.headless) {
      await SM.profiler.render(ctx, box, { sources: [{ fn: 'ensemble.profile', payload: base }], scope: null, option: 'profiler',
        note: `Drag the red dashed line of a factor, click in its plot, or type its value. The ${kind === 'forest' ? 'forest\'s prediction is an average of step functions' : 'boosted tree\'s prediction is a sum of step functions'}, so the curves move in steps.` });
    }
  }

  /* ---- Model Validation-Set Summaries ------------------------------------------------------ */
  function summariesOutline(ctx, r, K) {
    const s = r.summaries;
    const ob = ctx.outline('Model Validation-Set Summaries', { key: 'summaries', info: 'p:ensemble:summaries' });
    const cols = K.id === 'forest'
      ? [{ key: 'n_terms', label: 'N Terms', fmt: 'int' }, { key: 'n_trees', label: 'N Trees', fmt: 'int' }]
      : [{ key: 'splits', label: 'Splits per Tree', fmt: 'int' }, { key: 'learn', label: 'Learning Rate' }, { key: 'n_layers', label: 'N Layers', fmt: 'int' }];
    for (const k of s.keys) cols.push({ key: k, label: STAT_LABEL[k], digits: 4 });
    const main = STAT_LABEL[s.keys[0]];
    const whose = s.by === 'oob' ? 'the out-of-bag statistics of the training rows (there are no validation rows)' : 'the validation set\'s statistics';
    const which = r.shown === r.best ? 'The fit below was the best of these models fit' : `The fit below is line ${r.shown + 1}; the best is line ${r.best + 1}`;
    ob.add(ctx.note(`${which}: the largest ${main}. Each line gives ${whose}. Click a line to show that fit.`),
      wide(ctx.rt({ columns: cols, rows: s.rows }, { key: 'summaries', sortable: false, onRow: (row) => ctx.set('shownFit', row.index), cellClass: (row) => (row.index === r.shown ? 'sm-ens-shown' : '') })));
  }

  /* ---- Specifications -------------------------------------------------------------------------- */
  function specOutline(ctx, r, K) {
    const ob = ctx.outline('Specifications', { key: 'spec', info: 'p:ensemble:spec', menu: () => [{ label: 'Change Specifications…', action: () => specDialog(ctx, K.id) }] });
    ob.add(ctx.row(wide(ctx.kv(r.spec.left)), wide(ctx.kv(r.spec.right))));
  }

  /* ---- Overall Statistics ------------------------------------------------------------------------ */
  function overallOutline(ctx, r, K) {
    const ob = SM.predict.measures(ctx, ctx.container, r.fit, { title: 'Overall Statistics', key: 'overall' });
    if (r.individual) {
      ob.body.prepend(ctx.rt({ columns: [{ key: 'what', label: 'Individual Trees', fmt: 'text' }, { key: 'rase', label: 'RASE' }], rows: r.individual }, { key: 'individual', sortable: false }));
    }
    const parts = [];
    if (K.id === 'forest') {
      parts.push('Out of Bag: each training row predicted by the kept trees that did not see it (a check on the training fit that needs no validation rows; not in JMP).');
      if (r.individual) parts.push('Individual Trees: the RASE of each tree on its in-bag rows (each as often as it was drawn) and on its out-of-bag rows, averaged over the trees.');
    }
    if (r.response === 'categorical') parts.push(K.id === 'forest' ? 'The probabilities are the mean of the trees\' JMP probabilities (a node\'s counts plus a prior worth one row), never exactly 0.' : 'The probabilities are the logistic (or softmax) of the summed layers.');
    if (parts.length) ob.add(ctx.note(parts.join(' ')));
    if (r.response === 'categorical' && ctx.opt('confusion', true)) SM.predict.confusion(ctx, ob, r.fit);
    scrollTables(ob);
    ob.add(ctx.code(r.code));
  }

  /* ---- Cumulative Validation ------------------------------------------------------------------------ */
  function cumulativeOutline(ctx, r, K) {
    const c = r.cumulative;
    const keys = c.keys;
    let stat = ctx.opt('cumStat', keys[0]);
    if (!keys.includes(stat)) stat = keys[0];
    const ob = ctx.outline('Cumulative Validation', { key: 'cumulative', info: 'p:ensemble:cumulative', menu: () => [
      { label: 'Statistic', submenu: () => keys.map((k) => ({ label: STAT_LABEL[k], checked: stat === k, action: () => ctx.set('cumStat', k) })) },
      { label: 'Save Cumulative Details', action: () => saveCumulative(ctx, r, K) },
    ] });
    const col = setColors();
    const tc = SM.util.themeColors();
    const traces = c.series.map((s) => ({
      type: 'scatter', mode: c.x.length > 1 ? 'lines' : 'markers', x: c.x, y: s.stats[stat], name: s.set,
      line: { color: col[s.set], width: s.set === 'Validation' ? 2.2 : 1.5, dash: s.set === 'Out of Bag' ? 'dot' : 'solid' }, marker: { color: col[s.set], size: 6 },
      hovertemplate: `${T(s.set)}: %{y:.4f}, ${K.what} %{x}<extra></extra>`,
    }));
    const on = c.series.find((s) => s.set === 'Validation') || c.series.find((s) => s.set === 'Out of Bag') || c.series[0];
    const at = on ? on.stats[stat][c.kept - 1] : null;
    if (at != null) traces.push({ type: 'scatter', mode: 'markers', x: [c.kept], y: [at], marker: { size: 10, color: col[on.set], symbol: 'diamond', line: { width: 1, color: tc.surface } }, showlegend: false, hovertemplate: `${c.kept} ${K.what} kept: %{y:.4f}<extra></extra>` });
    const layout = {
      showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, margin: { l: 60, r: 14, t: 30, b: 44 },
      xaxis: { title: { text: `Number of ${K.many}` }, range: [0.5, Math.max(1, c.grown) + 0.5] }, yaxis: { title: { text: STAT_LABEL[stat] } },
      shapes: [{ type: 'line', xref: 'x', yref: 'paper', x0: c.kept, x1: c.kept, y0: 0, y1: 1, line: { color: tc.muted, width: 1.2, dash: 'dash' } }],
    };
    const valid = c.series.some((s) => s.set === 'Validation');
    const words = [];
    if (K.id === 'forest') {
      words.push(`${c.kept} of the ${c.grown} trees grown are kept (the dashed line)`);
      words.push(c.stopped ? `: early stopping ended the growth after ${c.grown - c.kept} trees brought no better validation ${STAT_LABEL[keys[0]]} (the last tenth of the trees asked for, at least 5)` : valid ? `: the best validation ${STAT_LABEL[keys[0]]}` : '');
    } else {
      words.push(`${c.kept} of the ${c.grown} layers fitted are kept (the dashed line)`);
      words.push(c.stopped ? `: layer ${c.grown} did not improve the validation ${STAT_LABEL[keys[0]]}, so the fit stopped there and kept the layers before it` : '');
    }
    const tail = valid ? '' : ` JMP shows this report only with validation rows; here are the training${K.id === 'forest' ? ' and out-of-bag' : ''} curves.`;
    const pc = r.fit.plots || {};
    ob.add(ctx.row(SM.predict.plotWithCode(ctx, traces, layout, { width: W(540), height: 310, title: `Cumulative Validation of ${K.label}`, select: false }, pc.head_code, pc.cumulative)), ctx.note(`${words.join('')}.${tail}`));
    const det = ctx.outline('Cumulative Details', { parent: ob, key: 'cumdetails', closed: true });
    det.add(wide(ctx.rt(detailsTable(r, K), { key: 'cumdetails', sortable: false, maxRows: 300 })));
  }

  function detailsTable(r, K, all = false) {
    const c = r.cumulative;
    const cols = [{ key: 'k', label: `N ${K.many}`, fmt: 'int' }];
    for (const s of c.series) for (const k of c.keys) cols.push({ key: `${s.set}|${k}`, label: `${s.set} ${STAT_LABEL[k]}`, digits: 4, hidden: !all && k !== c.keys[0] });
    const rows = c.x.map((x, i) => {
      const row = { k: x };
      for (const s of c.series) for (const k of c.keys) row[`${s.set}|${k}`] = s.stats[k][i];
      return row;
    });
    return { columns: cols, rows };
  }

  function saveCumulative(ctx, r, K) {
    const t = detailsTable(r, K, true);
    const name = SM.app.uniqueTableName ? SM.app.uniqueTableName(`${ctx.table.name} cumulative details`) : `${ctx.table.name} cumulative details`;
    const tbl = SM.report.tableFromRT(t, name);
    tbl.notes = `The statistics of each set after 1, 2, … ${K.what}, from ${ctx.report.title}${ctx.byLabel ? ` (${ctx.byLabel})` : ''}; ${r.cumulative.kept} kept.`;
    SM.app.addTable(tbl);
    SM.ui.toast(`Made the table ${tbl.name}`);
  }

  /* ---- Per-Tree Summaries (a forest) ------------------------------------------------------------------ */
  function perTreeOutline(ctx, r) {
    const cat = r.response === 'categorical';
    const ob = ctx.outline('Per-Tree Summaries', { key: 'pertree', closed: true, info: 'p:ensemble:pertree' });
    const cols = [{ key: 'tree', label: 'Tree', fmt: 'int' }, { key: 'splits', label: 'Splits', fmt: 'int' }, { key: 'rank', label: 'Rank', fmt: 'int' },
      { key: 'oob_loss', label: 'OOB Loss' }, { key: 'oob_loss_n', label: 'OOB Loss/N' }];
    if (!cat) cols.push({ key: 'rsquare', label: 'RSquare' }, { key: 'ib_sse', label: 'IB SSE' }, { key: 'ib_sse_n', label: 'IB SSE/N' }, { key: 'oob_n', label: 'OOB N' }, { key: 'oob_sse', label: 'OOB SSE' }, { key: 'oob_sse_n', label: 'OOB SSE/N' });
    else cols.push({ key: 'oob_n', label: 'OOB N', hidden: true });
    ob.add(wide(ctx.rt({ columns: cols, rows: r.trees }, { key: 'pertree', maxRows: 200 })),
      ctx.note(`In bag: the rows of the tree's bootstrap sample, each as often as it was drawn; out of bag (OOB): the training rows it did not see. OOB Loss is the ${cat ? '-log likelihood' : 'sum of squared errors'} of the out-of-bag rows before the last split was taken back; ${cat ? 'Rank orders the trees by OOB Loss/N' : 'OOB SSE is that of the tree kept, and Rank orders the trees by OOB Loss/N'}.`));
  }

  /* ---- Column Contributions --------------------------------------------------------------------------- */
  function contribOutline(ctx, r, K) {
    const c = r.contributions;
    const rows = c.rows;
    const ob = ctx.outline('Column Contributions', { key: 'contrib', info: 'p:ensemble:contrib' });
    const tbl = ctx.rt({ columns: [{ key: 'column', label: 'Term', fmt: 'text' }, { key: 'splits', label: 'Number of Splits', fmt: 'int' }, { key: 'value', label: c.label }, { key: 'portion', label: 'Portion', digits: 4 }], rows }, { key: 'contrib' });
    const bars = SM.predict.plotWithCode(ctx, [{ type: 'bar', orientation: 'h', y: rows.map((x) => T(x.column)), x: rows.map((x) => x.portion), marker: { color: SM.report.BAR }, hovertemplate: '%{y}: %{x:.4f}<extra></extra>' }],
      { margin: { l: 110, r: 12, t: 6, b: 34 }, xaxis: { title: { text: 'Portion' }, range: [0, 1] }, yaxis: { autorange: 'reversed', type: 'category' } },
      { width: W(340), height: Math.max(120, 24 * rows.length + 50), title: 'Column Contributions', select: false }, (r.fit.plots || {}).head_code, c.plot_code);
    const what = K.id === 'forest' ? `the kept trees (as they were cut back)${r.response === 'categorical' ? '; G² is 2 × the change in entropy (natural log) of the in-bag counts' : '; SS is the fall in the in-bag sum of squares'}`
      : `every layer; SS is the fall in the sum of squares of the residuals the layer fits${r.response === 'categorical' ? ' (JMP reports G² for a categorical response)' : ''}`;
    ob.add(ctx.row(wide(tbl), bars), ctx.note(`The splits on each column over ${what}. A split on a categorical column takes two groups of its levels.`));
  }

  /* ---- Permutation Importance (not in JMP) ----------------------------------------------------------- */
  async function permutationOutline(ctx, base, r, K) {
    const res = await withProgress(ctx, 'ensemble.permutation', { ...base, repeats: ctx.opt('permRepeats', 5) }, 'permutation', 'Permutation Importance', 'shuffles');
    const ob = SM.predict.contributions(ctx, ctx.container, res.contributions, {
      title: 'Permutation Importance', key: 'permutation', head: (r.fit.plots || {}).head_code,
      note: `The fall in the ${res.set.toLowerCase()} rows' ${res.contributions.label.replace(/^Decrease in /, '')} (${fmt(res.base, { sig: 5 })} as fitted) when one column's values are shuffled over those rows, the model left as it is: the mean over ${res.repeats} shuffles, seeded by the report's seed. A categorical column is shuffled as one. Not in JMP (its profiler has Assess Variable Importance); scikit-learn's permutation_importance does the same.`,
    });
    scrollTables(ob);
    ob.add(ctx.code(res.code));
  }

  /* ---- Show Trees ------------------------------------------------------------------------------------------- */
  const TREE_ITEMS = [['names', 'Show names'], ['categories', 'Show names categories'], ['estimates', 'Show names categories estimates']];

  function showTreesItems(ctx) {
    const cur = ctx.opt('trees', null);
    return [...TREE_ITEMS.map(([v, l]) => ({ label: l, checked: cur === v, action: () => ctx.set('trees', v) })), { label: 'Hide Trees', disabled: !cur, action: () => ctx.set('trees', null) }];
  }

  async function treeViews(ctx, base, r, K, detail) {
    const count = r.cumulative.kept;
    const index = Math.max(1, Math.min(count, Number(ctx.opt('treeIndex', 1)) || 1));
    const res = await ctx.call('ensemble.tree', { ...base, index, detail });
    const ob = ctx.outline('Tree Views', { key: 'treeviews', info: 'p:ensemble:trees', menu: () => showTreesItems(ctx) });
    const go = (i) => { const v = Math.round(Number(i)); if (Number.isFinite(v)) ctx.set('treeIndex', Math.max(1, Math.min(count, v))); };
    const input = el('input', { type: 'text', inputmode: 'numeric', size: 4, class: 'sm-ens-input', 'aria-label': `${res.what} number` });
    input.value = String(res.index);
    input.addEventListener('change', () => go(numOf(input.value)));
    input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); go(numOf(input.value)); } });
    const prev = el('button', { type: 'button', class: 'sm-btn small', text: '‹', 'aria-label': `Previous ${res.what.toLowerCase()}` });
    const next = el('button', { type: 'button', class: 'sm-btn small', text: '›', 'aria-label': `Next ${res.what.toLowerCase()}` });
    prev.disabled = res.index <= 1;
    next.disabled = res.index >= count;
    prev.addEventListener('click', () => go(res.index - 1));
    next.addEventListener('click', () => go(res.index + 1));
    const bar = el('div', { class: 'sm-ens-treebar', 'data-noexport': '' }, prev, el('label', null, el('span', { text: res.what }), input, el('span', { text: `of ${count}` })), next);
    const list = el('div', { class: 'sm-ens-tree' });
    const est = (ln) => {
      const out = [];
      if (ln.count != null) out.push(el('span', { class: 'sm-ens-count', text: `Count ${fmt(ln.count, { sig: 6 })}` }));
      if (ln.estimate != null) out.push(el('span', { class: 'sm-ens-est', text: `${K.id === 'boosted' ? 'Estimate' : 'Mean'} ${fmt(ln.estimate, { sig: 5 })}` }));
      if (ln.probs) out.push(el('span', { class: 'sm-ens-est', text: `Prob ${ln.probs.map(([l, p]) => `${l} ${fmt(p, { digits: 4 })}`).join(', ')}` }));
      return out;
    };
    for (const ln of res.lines) {
      list.append(el('div', { class: `sm-ens-node${ln.leaf ? ' is-leaf' : ''}`, style: { paddingLeft: `${4 + 16 * ln.depth}px` } }, el('span', { class: 'sm-ens-cond', text: ln.text }), ...est(ln)));
    }
    const notes = [];
    if (res.truncated) notes.push(`The first ${res.lines.length} nodes of ${res.nodes}.`);
    if (res.note) notes.push(res.note);
    notes.push(K.id === 'forest' ? 'The tree as it was cut back. A split on a nominal column takes two groups of its levels (the tree orders them by the mean response of its bootstrap rows); an ordinal one keeps its order; Missing is on the side the tree sends missing values.'
      : 'A split on a nominal column takes two groups of its levels (the layer\'s tree orders them by their mean residual); an ordinal one keeps its order; Missing is on the side the tree sends missing values.');
    ob.add(bar, el('div', { class: 'sm-ens-treewrap' }, list), notes.length ? ctx.note(notes.join(' ')) : null);
  }

  /* ---- the specification again, from the red triangle ------------------------------------------------ */
  async function specDialog(ctx, kind) {
    const p = ctx.names('x').length;
    const cur = settingsOf(ctx);
    const fields = FIELDS[kind].map((f) => {
      const d = typeof f.dflt === 'function' ? f.dflt(p, cur) : f.dflt;
      if (f.type === 'check') return { key: f.key, label: f.label, type: 'check', value: cur[f.key] ?? d, help: f.help };
      if (f.type === 'select') return { key: f.key, label: f.label, type: 'select', value: cur[f.key] ?? d, choices: f.choices, help: f.help };
      return { key: f.key, label: f.label, type: 'number', value: cur[f.key] ?? d, help: f.help };
    });
    // the (i) of the form: what each field is for (the Specifications topic has both kinds' fields)
    const v = await SM.ui.form({ title: `${KIND[kind].label} Specification`, fields,
      lead: kind === 'forest' ? 'The forest\'s settings, as JMP\'s Bootstrap Forest Specification window has them. OK fits the forest again.' : 'The boosted tree\'s settings, as JMP\'s Gradient-Boosted Trees Specification window has them. OK fits it again.',
      validate: (x) => checkSettings(kind, x) });
    if (!v) return;
    const out = {};
    for (const f of FIELDS[kind]) if (v[f.key] != null) out[f.key] = v[f.key];
    ctx.set('shownFit', null, null, { rerun: false });
    ctx.set('settings', out);
  }

  /* ---- Score Rows: the model as the report fitted it on rows it did not see ------------------------- */
  /* JMP's Save Prediction Formula of a forest or a boosted tree is a formula of every tree (thousands of nested
     conditions), so here the engine keeps the report's fit and scores the rows of an open table with it: this
     table's rows added since (those without a prediction yet) or every row of another table with the same
     columns. The dialog is SM.predict.scoreRows, as K Nearest Neighbors' and Support Vector Machines'. */
  function scoreRows(ctx, E) {
    const own = ctx.rows.length === ctx.table.nrows ? null : ctx.rows;
    return SM.predict.scoreRows(ctx, { fn: 'ensemble.score', payload: { ...E.base, rows: own, keep: keepOf(ctx) }, fit: E.r.fit, yName: E.base.y, info: 'p:ensemble:score' });
  }

  /* ======================================================================
     THE RED TRIANGLE
     ====================================================================== */
  function triangle(ctx, kind) {
    const E = ctx.ens;
    const K = KIND[kind];
    const tail = [{ label: 'Specifications…', action: () => specDialog(ctx, kind) }, { label: 'Model Dialog', action: () => ctx.report.relaunch() }];
    if (!E) return tail;
    const { r, base } = E;
    const showTrees = { label: 'Show Trees', submenu: () => showTreesItems(ctx) };
    const items = [];
    if (kind === 'boosted') items.push(showTrees);
    if (r.response === 'continuous') items.push(ctx.check('Plot Actual by Predicted', 'abp', null, false));
    items.push(ctx.check('Column Contributions', 'contrib', null, true));
    if (kind === 'forest') items.push(showTrees);
    items.push(...SM.predict.classificationItems(ctx, r.fit));
    items.push(ctx.check('Profiler', 'profiler', null, false));
    items.push({ separator: true });
    items.push(ctx.check('Cumulative Validation', 'cumulative', null, true));
    if (kind === 'forest') items.push(ctx.check('Per-Tree Summaries', 'pertree', null, true));
    items.push(ctx.check('Permutation Importance', 'permutation', null, false));
    items.push({ separator: true });
    const save = SM.predict.saveItems(ctx, 'ensemble.save', base, r.fit)[0];
    items.push({ label: 'Save Columns', submenu: () => [...save.submenu(), { label: 'Score Rows…', action: () => scoreRows(ctx, E) }, { label: 'Save Cumulative Details', action: () => saveCumulative(ctx, r, K) }] });
    items.push(...tail);
    return items;
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const ROLES = { heading: 'Roles', choices: [['Y, Response', 'A continuous response (a regression forest or boosted tree), or a nominal or ordinal one (a classifier; an ordinal one\'s order is not used).'], ['X, Factor', 'The predictors: continuous ones as they are; a split on a nominal one takes two groups of its levels, as JMP\'s splits do, and one on an ordinal one keeps the level order. With Informative Missing a missing continuous value is the training mean plus a Missing column, and a missing level goes to the better side of each split.'], ['Weight, Freq', 'Case weights in the fit and the measures.'], ['Validation', 'Training, validation and test rows; or a Validation Portion. The validation rows choose the number of trees or layers and the best of Multiple Fits. A Validation column of more than three values holds K folds (not in JMP\'s platforms): every row trains, and Overall Statistics gets a Crossvalidation line, each fold predicted by the model of the same settings grown on the other folds.']] };
  const LEVELS = { heading: 'Categorical factors', text: 'A split on a nominal X takes two groups of its levels, as JMP\'s Partition splits them. Each tree puts the levels in the order of the mean response of its rows (a boosted layer\'s tree: of their mean residual); a cut in that order is a grouping of the levels, and for a continuous or two-level response the best cut is the best of all the groupings at the tree\'s root (Fisher\'s result; for more levels the order is that of the first principal component of the levels\' shares). A split on an ordinal X keeps its levels in order, as JMP\'s Ordinal Restricts Order does. A missing level, a level the tree\'s rows lack, and a level another table has that the model never saw go where the tree sends missing values: to the better side of each split (where a node had none, with the larger side). Show Trees words a split as JMP does, g(a, c) against g(b).' };
  const SCORE = { heading: 'Score Rows', text: 'Save Columns ▸ Score Rows… predicts rows the model did not see, with the model as the report fitted it (the engine keeps it): this table\'s rows added since, or another open table with the same X columns. JMP\'s Save Prediction Formula writes every tree into a formula; here that would run to thousands of nested conditions.' };
  const TOPICS = {
    'p:forest': {
      kicker: 'Analyze > Predictive Modeling', title: 'Bootstrap Forest',
      lead: 'The average of many decision trees, each grown on a bootstrap sample of the training rows with a random set of the X columns tried at each split (scikit-learn\'s decision trees, the samples and seeds drawn as its RandomForestRegressor and RandomForestClassifier draw them). A split on a nominal X takes two groups of its levels, each tree is then cut back as JMP describes its trees stopping, and a categorical response\'s probabilities are JMP\'s.',
      sections: [ROLES, LEVELS,
        { heading: 'Each tree', text: 'scikit-learn grows the tree best first up to Maximum Splits per Tree, with at least Minimum Size Split rows on each side of a split. JMP says its trees split until a stopping criterion stops improving and are then pruned back one split; here the criterion is the tree\'s out-of-bag loss: past Minimum Splits per Tree a split stays while it lowers the loss of the rows the tree did not see, and the first that does not is taken back. Tree Size ▸ Grow to Maximum Splits keeps scikit-learn\'s trees whole.' },
        { heading: 'Probabilities', text: 'As JMP\'s Partition: at each node Prob = (n + prior)/(N + 1), the node\'s counts n (N in all) plus a prior worth one row, the prior 0.9 of the parent\'s prior and 0.1 of the parent\'s Prob, at the root the root\'s shares. So no probability is 0 (scikit-learn\'s own leaves give 0 for a level missing from a leaf); the forest averages its trees\' probabilities.' },
        SCORE,
        { heading: 'Differences from JMP', text: 'The Out of Bag line of Overall Statistics, Permutation Importance and Score Rows are not in JMP; its Save Prediction Formula is not here. A tree orders a nominal X\'s levels once, by its bootstrap rows, where JMP\'s Partition orders them again at each node; below the root a split may miss a grouping JMP would find. A split is chosen by the fall in the sum of squares or the entropy (scikit-learn\'s), not by JMP\'s LogWorth. A missing continuous value is the training mean with a Missing column, where JMP sends it to the better side.' }],
      more: KIND.forest.more,
    },
    'p:boosted': {
      kicker: 'Analyze > Predictive Modeling', title: 'Boosted Tree',
      lead: 'A sum of small trees (layers), each fitted to the residuals of the layers before it and scaled by the learning rate: scikit-learn\'s gradient boosting written out layer by layer (without a nominal X it is GradientBoostingRegressor or GradientBoostingClassifier, the same draws), its trees grown best first to Splits per Tree splits, each reading a nominal X in the order of its levels\' mean residual so that a split takes two groups of levels.',
      sections: [ROLES, LEVELS,
        { heading: 'A categorical response', text: 'Each layer fits the gradient of the log likelihood (the log odds for two levels, a tree per level for more; JMP takes two levels only). JMP\'s Overfit Penalty has no scikit-learn counterpart and is not used: the leaf values are scikit-learn\'s Newton steps.' },
        SCORE,
        { heading: 'Differences from JMP', text: 'A layer\'s tree orders a nominal X\'s levels once, by their mean residual, where JMP\'s Partition orders them again at each node (a layer has few splits, so the difference is small). Row Sampling does not stratify by a categorical response, and Column Sampling draws at each split where JMP draws once per layer. Score Rows stands in for JMP\'s Save Prediction Formula.' }],
      more: KIND.boosted.more,
    },
    'p:ensemble:spec': {
      kicker: 'Bootstrap Forest, Boosted Tree', title: 'Specifications',
      lead: 'The settings of the fit, with JMP\'s defaults, and what came of them: the rows of each set, the Number of Trees Kept (or Layers Kept) after early stopping, a forest\'s Bootstrap Samples (the rows drawn for each tree), and whether Early Stopping was on. Change Specifications… (red triangle) fits again.',
      sections: [
        { heading: 'Bootstrap Forest', choices: FIELDS.forest.map((f) => [f.label, f.help]) },
        { heading: 'Boosted Tree', choices: FIELDS.boosted.map((f) => [f.label, f.help]) },
        { heading: 'Random Seed', text: 'The bootstrap samples, the columns tried and the row sampling follow the report\'s seed (scikit-learn\'s random_state), so a redraw, a project and the Python code give the same model.' },
      ],
    },
    'p:ensemble:summaries': {
      kicker: 'Bootstrap Forest, Boosted Tree', title: 'Model Validation-Set Summaries',
      lead: 'Every fit of Multiple Fits with its validation set\'s statistics (a forest without validation rows: the out-of-bag statistics). The report shows the fit with the largest RSquare, or Entropy RSquare for a categorical response; a click on another line shows that one.',
      sections: [{ choices: [['A click on a line', 'Shows that fit in the report below it (its Specifications, statistics, curves and contributions); the line shown is marked. Specifications… or a new launch goes back to the best one.']] }],
    },
    'p:ensemble:cumulative': {
      kicker: 'Bootstrap Forest, Boosted Tree', title: 'Cumulative Validation',
      lead: 'A statistic of each set after 1, 2, … trees or layers: the forest of the first k trees, or the first k layers. The dashed line marks the number kept. Statistic (red triangle) picks RSquare or RASE, or for a categorical response Entropy RSquare, Mean -Log p, RASE, Mean Abs Dev or the Misclassification Rate. Cumulative Details below the plot gives the values; Save Cumulative Details makes them a table.',
      sections: [{ heading: 'Out of Bag', text: 'For a forest, each training row predicted by the first k trees that did not see it.' }],
    },
    'p:ensemble:pertree': {
      kicker: 'Bootstrap Forest', title: 'Per-Tree Summaries',
      lead: 'Each kept tree: its splits, and its losses on its in-bag rows (the bootstrap sample, each row as often as drawn) and out-of-bag rows (the training rows it did not see).',
      sections: [{ choices: [['Splits', 'the splits of the tree kept'], ['Rank', 'of OOB Loss/N, smallest first'], ['OOB Loss', 'the out-of-bag loss (squared error, or -log p) before the last split was taken back'], ['RSquare', 'the tree\'s in-bag RSquare'], ['IB SSE, IB SSE/N', 'the in-bag sum of squared errors, and over the bootstrap sample\'s size'], ['OOB N, OOB SSE, OOB SSE/N', 'the out-of-bag rows and the kept tree\'s squared errors on them']] }],
    },
    'p:ensemble:contrib': { kicker: 'Bootstrap Forest, Boosted Tree', title: 'Column Contributions', lead: 'For each X column: how many splits use it over all the trees or layers, and the SS (continuous) or G² (categorical) those splits take away: the parent\'s minus its two children\'s, the SS a node\'s sum of squares about its mean and G² twice its entropy (natural log) from the counts. Portion is the column\'s share of the total.' },
    'p:ensemble:score': {
      kicker: 'Bootstrap Forest, Boosted Tree', title: 'Score Rows',
      lead: 'The forest or boosted tree as this report fitted it (the engine keeps it while the page is open) on rows it did not see: this table\'s rows added since the report fitted, or every row of another open table with the same X columns, found by name. The predictions go into that table: into its prediction columns for the rows that have none yet, or as new columns (Predicted, or Prob[] of each level and Most Likely). The model is not fitted again. After the engine starts again the model is fitted again from this table as it is now, and the page says so.',
      sections: [{ heading: 'Why', text: 'JMP\'s Save Prediction Formula writes all the trees into one formula column; a forest of 100 trees would be a formula of thousands of nested conditions, so here the model itself scores the rows.' },
        { heading: 'Levels the model never saw', text: 'A level of a categorical X that the training rows did not have is read as a missing value, and goes where each tree sends missing values.' }],
    },
    'p:ensemble:trees': {
      kicker: 'Bootstrap Forest, Boosted Tree', title: 'Tree Views',
      lead: 'One tree of the forest (as it was cut back) or one layer of the boosted tree, a line per node: the split that leads to it and, with estimates, its training rows (weighted, in bag) and its mean or JMP probabilities; a layer\'s estimate is what it adds to the prediction.',
      sections: [
        { heading: 'The controls', choices: [
          ['‹ and ›', 'Show the tree (or layer) before or after this one.'],
          ['Tree, Layer', 'Type the number of a tree (from 1 to the number kept) and press Enter, or leave the box, to show it.'],
        ] },
        { heading: 'Show Trees (red triangle)', choices: [
          ['Show names', 'Each node by the column its split uses.'],
          ['Show names categories', 'Each node by its condition: a value cut, or the levels on its side as JMP words them, g(a, c) (Missing where the tree sends missing values).'],
          ['Show names categories estimates', 'The conditions, and each node\'s training rows and its estimate.'],
          ['Hide Trees', 'Takes the Tree Views away.'],
        ] },
      ],
    },
  };

  /* ======================================================================
     THE PLATFORMS
     ====================================================================== */
  const ABOUT = {
    forest: 'JMP Pro\'s Bootstrap Forest: many decision trees, each grown on a bootstrap sample of the training rows with a random set of the X columns tried at each split, averaged; a split on a nominal X takes two groups of its levels, as JMP\'s do; each tree cut back by its out-of-bag loss past Minimum Splits per Tree, as JMP describes its trees stopping, and a categorical response\'s probabilities JMP\'s (never 0). Early stopping on the validation rows, Multiple Fits over the number of terms; Model Validation-Set Summaries, Specifications, Overall Statistics with Individual Trees and an out-of-bag estimate, Cumulative Validation with its details, Per-Tree Summaries, Column Contributions, and from the red triangle permutation importance, actual by predicted, ROC and lift curves, the Decision Threshold, tree views, the Prediction Profiler, Save Columns and Score Rows (the model as fitted, on new rows or another table).',
    boosted: 'JMP Pro\'s Boosted Tree: a sum of small trees, each fitted to the residuals of the ones before and scaled by the learning rate, for a continuous or categorical response; a split on a nominal X takes two groups of its levels, as JMP\'s do. Early stopping at the first layer that does not improve the validation statistic, Multiple Fits over splits per tree and learning rate, row and column sampling; Model Validation-Set Summaries, Specifications, Overall Statistics, Cumulative Validation with its details, Column Contributions, and from the red triangle permutation importance, actual by predicted, ROC and lift curves, the Decision Threshold, the layers\' trees, the Prediction Profiler, Save Columns and Score Rows (the model as fitted, on new rows or another table).',
  };
  const USES = {
    forest: ['sklearn.tree.DecisionTreeRegressor, DecisionTreeClassifier (their missing-value splits; apply, decision_path, compute_node_depths), drawn as sklearn.ensemble.RandomForestRegressor draws its trees', 'numpy'],
    boosted: ['sklearn.tree.DecisionTreeRegressor, layer by layer as sklearn.ensemble.GradientBoostingRegressor and GradientBoostingClassifier fit their stages', 'scipy.special expit, logit', 'numpy'],
  };

  for (const kind of ['forest', 'boosted']) {
    const K = KIND[kind];
    SM.platforms.register({
      id: kind, label: K.label, menu: 'Analyze/Predictive Modeling', order: kind === 'forest' ? 20 : 30, info: K.info, topics: TOPICS,
      about: ABOUT[kind], uses: USES[kind],
      launch: {
        lead: kind === 'forest' ? 'Choose a response and the factors. The forest averages many trees, each on a bootstrap sample of the training rows; the Specification below has JMP\'s settings.'
          : 'Choose a response and the factors. Each layer is a small tree fitted to what the layers before it left; the Specification below has JMP\'s settings.',
        roles: [
          { key: 'y', label: 'Y, Response', min: 1, max: 1, hint: 'required',
            help: kind === 'forest' ? 'The column the forest predicts. Continuous: each tree predicts a mean and the forest averages them. Nominal or ordinal: each tree gives a probability of every level (JMP\'s, never 0) and the forest averages them; the order of an ordinal response is not used.'
              : 'The column the boosted tree predicts. Continuous: the layers add up to the prediction, each fitted to the residuals of those before. Nominal or ordinal: the layers add up on the log-odds scale (a tree per level each layer, for more than two levels); the order of an ordinal response is not used.' },
          { key: 'x', label: 'X, Factor', min: 1, hint: 'required: one or more',
            help: 'The predictors, of any modeling type: a continuous one as it is; a split on a nominal one takes two groups of its levels, as JMP\'s splits do, and one on an ordinal one keeps the level order. Column Contributions shows how much each one is used.' },
          ...SM.predict.roles(),
        ],
        options: SM.predict.options(),
        extra: launchExtra(kind),
        validate: (spec) => checkSettings(kind, (spec.options && spec.options.settings) || {}),
      },
      title: (spec, table) => {
        const c = table && table.col(((spec.roles && spec.roles.y) || [])[0]);
        return c ? `${K.label} for ${c.name}` : K.label;
      },
      triangle: (ctx) => triangle(ctx, kind),
      render: (ctx) => render(ctx, kind),
    });
  }

  /* ---- the example: simulated subscribers, the truth in its notes --------------------------------------- */
  SM.io.addExample('subscribers', {
    label: 'Subscribers (1500 rows): churn and satisfaction',
    about: 'Simulated: 1500 subscribers with tenure (months), monthly charge, contract, support calls, age, region and data use (missing for 9%, more often for those who leave). Churned (Yes/No) is logistic in -1.0 + 2.0 [month-to-month] - 0.06 tenure + 0.04 (charge - 65) + 0.7 max(calls - 2, 0) + 1.5 [tenure < 12 and charge > 85] - 0.015 (age - 45) + 1.2 [data use missing]. Satisfaction (0-100) is 60 + 12 tanh((tenure - 24)/15) - 5 min(calls, 5) - 0.1 (charge - 65) + 6 [two year] + 4 sin(age/8) plus normal noise (SD 6). Region changes nothing. Validation: 60% Training, 20% Validation, 20% Test, at random. For Bootstrap Forest and Boosted Tree (Analyze > Predictive Modeling).',
    make() {
      const r = SM.util.rng('ensemble-subscribers');
      const n = 1500;
      const c = { id: [], tenure: [], charge: [], contract: [], calls: [], age: [], region: [], usage: [], churned: [], satisfaction: [], validation: [] };
      const pois = (lam) => { let k = 0, p = Math.exp(-lam), s = p; const u = r.u(); while (u > s && k < 20) { k++; p *= lam / k; s += p; } return k; };
      for (let i = 0; i < n; i++) {
        const tenure = r.int(1, 72);
        const cu = r.u();
        const contract = cu < 0.5 ? 'Month-to-month' : cu < 0.8 ? 'One year' : 'Two year';
        const charge = +(20 + 90 * r.u()).toFixed(2);
        const calls = pois(1.5);
        const age = r.int(18, 80);
        const region = r.pick(['North', 'South', 'East', 'West']);
        const usage = +Math.exp(r.normal(2.5, 0.6)).toFixed(2);
        const eta0 = -1.0 + 2.0 * (contract === 'Month-to-month') - 0.06 * tenure + 0.04 * (charge - 65) + 0.7 * Math.max(calls - 2, 0) + 1.5 * (tenure < 12 && charge > 85) - 0.015 * (age - 45);
        const missing = r.u() < 0.07 + 0.06 * (eta0 > 0);
        const eta = eta0 + 1.2 * missing;
        const churned = r.u() < 1 / (1 + Math.exp(-eta)) ? 'Yes' : 'No';
        const sat = 60 + 12 * Math.tanh((tenure - 24) / 15) - 5 * Math.min(calls, 5) - 0.1 * (charge - 65) + 6 * (contract === 'Two year') + 4 * Math.sin(age / 8) + r.normal(0, 6);
        const vu = r.u();
        c.id.push(`S${String(i + 1).padStart(4, '0')}`); c.tenure.push(tenure); c.charge.push(charge); c.contract.push(contract); c.calls.push(calls);
        c.age.push(age); c.region.push(region); c.usage.push(missing ? NaN : usage); c.churned.push(churned);
        c.satisfaction.push(+Math.max(0, Math.min(100, sat)).toFixed(1)); c.validation.push(vu < 0.6 ? 'Training' : vu < 0.8 ? 'Validation' : 'Test');
      }
      return new SM.Table({ name: 'Subscribers', source: 'simulated', columns: [
        { name: 'subscriber', dataType: 'character', values: c.id, role: 'label' },
        { name: 'tenure (months)', dataType: 'numeric', values: c.tenure },
        { name: 'monthly charge', dataType: 'numeric', values: c.charge },
        { name: 'contract', dataType: 'character', values: c.contract, valueOrder: ['Month-to-month', 'One year', 'Two year'] },
        { name: 'support calls', dataType: 'numeric', values: c.calls },
        { name: 'age', dataType: 'numeric', values: c.age },
        { name: 'region', dataType: 'character', values: c.region },
        { name: 'data use (GB)', dataType: 'numeric', values: c.usage },
        { name: 'churned', dataType: 'character', values: c.churned, valueOrder: ['No', 'Yes'] },
        { name: 'satisfaction', dataType: 'numeric', values: c.satisfaction },
        { name: 'Validation', dataType: 'character', values: c.validation, valueOrder: ['Training', 'Validation', 'Test'] },
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
