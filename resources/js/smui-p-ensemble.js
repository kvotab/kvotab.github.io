/* ==========================================================================
   SMUI.HTML: ANALYZE > PREDICTIVE MODELING > BOOTSTRAP FOREST, BOOSTED TREE

   JMP Pro's two tree ensembles, fitted by scikit-learn (the backend is
   resources/py/smui/ensemble.py). The launch dialog has JMP's roles, and
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
   Save Columns and the specification again.
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
      { panel: 'Forest', key: 'trees', label: 'Number of Trees in the Forest', type: 'int', dflt: 100, min: 1, max: 5000 },
      { panel: 'Forest', key: 'terms', label: 'Number of Terms Sampled per Split', type: 'int', dflt: (p) => defaultTerms(p), min: 1 },
      { panel: 'Forest', key: 'rate', label: 'Bootstrap Sample Rate', type: 'num', dflt: 1, min: 0, max: 1, open: true },
      { panel: 'Forest', key: 'minSplits', label: 'Minimum Splits per Tree', type: 'int', dflt: 10, min: 0 },
      { panel: 'Forest', key: 'maxSplits', label: 'Maximum Splits per Tree', type: 'int', dflt: 2000, min: 1, max: 100000 },
      { panel: 'Forest', key: 'minSize', label: 'Minimum Size Split', type: 'int', dflt: 5, min: 1 },
      { panel: 'Forest', key: 'stop', label: 'Tree Size', type: 'select', dflt: 'oob', choices: [['oob', 'Stop by Out-of-Bag Loss (JMP)'], ['none', 'Grow to Maximum Splits (scikit-learn)']] },
      { panel: 'Forest', key: 'early', label: 'Early Stopping', type: 'check', dflt: true },
      { panel: 'Multiple Fits', key: 'multi', label: 'Multiple Fits over Number of Terms', type: 'check', dflt: false },
      { panel: 'Multiple Fits', key: 'maxTerms', label: 'Max Number of Terms', type: 'int', dflt: (p) => p, min: 1 },
    ],
    boosted: [
      { panel: 'Boosting', key: 'layers', label: 'Number of Layers', type: 'int', dflt: 50, min: 1, max: 20000 },
      { panel: 'Boosting', key: 'splits', label: 'Splits per Tree', type: 'int', dflt: 3, min: 1, max: 1000 },
      { panel: 'Boosting', key: 'learn', label: 'Learning Rate', type: 'num', dflt: 0.1, min: 0, max: 1, open: true },
      { panel: 'Boosting', key: 'minSize', label: 'Minimum Size Split', type: 'int', dflt: 5, min: 1 },
      { panel: 'Multiple Fits', key: 'multi', label: 'Multiple Fits over Splits and Learning Rate', type: 'check', dflt: false },
      { panel: 'Multiple Fits', key: 'maxSplits', label: 'Max Splits per Tree', type: 'int', dflt: (p, s) => s.splits ?? 3, min: 1, max: 1000 },
      { panel: 'Multiple Fits', key: 'maxLearn', label: 'Max Learning Rate', type: 'num', dflt: (p, s) => s.learn ?? 0.1, min: 0, max: 1, open: true },
      { panel: 'Stochastic Boosting', key: 'rowRate', label: 'Row Sampling Rate', type: 'num', dflt: 1, min: 0, max: 1, open: true },
      { panel: 'Stochastic Boosting', key: 'colRate', label: 'Column Sampling Rate', type: 'num', dflt: 1, min: 0, max: 1, open: true },
      { panel: 'Stochastic Boosting', key: 'early', label: 'Early Stopping', type: 'check', dflt: true },
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
        hint.textContent = valid ? '' : 'Early Stopping and Multiple Fits need validation rows: a Validation column, or a Validation Portion below.';
      };
      api.onRolesChange(update);
      for (const i of Object.values(inputs)) i.addEventListener('input', () => update(api.state));
      update(api.state);
      return {
        el: box,
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
    const r = await withProgress(ctx, 'ensemble.fit', base, kind, K.label, K.what);
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
    ob.add(ctx.row(ctx.plot(traces, layout, { width: W(540), height: 310, title: `Cumulative Validation of ${K.label}`, select: false })), ctx.note(`${words.join('')}.${tail}`));
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
    const bars = ctx.plot([{ type: 'bar', orientation: 'h', y: rows.map((x) => T(x.column)), x: rows.map((x) => x.portion), marker: { color: SM.report.BAR }, hovertemplate: '%{y}: %{x:.4f}<extra></extra>' }],
      { margin: { l: 110, r: 12, t: 6, b: 34 }, xaxis: { title: { text: 'Portion' }, range: [0, 1] }, yaxis: { autorange: 'reversed', type: 'category' } },
      { width: W(340), height: Math.max(120, 24 * rows.length + 50), title: 'Column Contributions', select: false });
    const what = K.id === 'forest' ? `the kept trees (as they were cut back)${r.response === 'categorical' ? '; G² is 2 × the change in entropy (natural log) of the in-bag counts' : '; SS is the fall in the in-bag sum of squares'}`
      : `every layer; SS is the fall in the sum of squares of the residuals the layer fits${r.response === 'categorical' ? ' (JMP reports G² for a categorical response)' : ''}`;
    ob.add(ctx.row(wide(tbl), bars), ctx.note(`The splits on each column over ${what}. A categorical column's levels are its 0/1 columns added together.`));
  }

  /* ---- Permutation Importance (not in JMP) ----------------------------------------------------------- */
  async function permutationOutline(ctx, base, r, K) {
    const res = await withProgress(ctx, 'ensemble.permutation', { ...base, repeats: ctx.opt('permRepeats', 5) }, 'permutation', 'Permutation Importance', 'shuffles');
    const ob = SM.predict.contributions(ctx, ctx.container, res.contributions, {
      title: 'Permutation Importance', key: 'permutation',
      note: `The fall in the ${res.set.toLowerCase()} rows' ${res.contributions.label.replace(/^Decrease in /, '')} (${fmt(res.base, { sig: 5 })} as fitted) when one column's values are shuffled over those rows, the model left as it is: the mean over ${res.repeats} shuffles, seeded by the report's seed. A categorical column's 0/1 columns move together. Not in JMP (its profiler has Assess Variable Importance); scikit-learn's permutation_importance does the same one column of X at a time.`,
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
    if (K.id === 'forest') notes.push('The tree as it was cut back; scikit-learn splits a categorical column one level against the others (JMP splits its levels into two groups).');
    ob.add(bar, el('div', { class: 'sm-ens-treewrap' }, list), notes.length ? ctx.note(notes.join(' ')) : null);
  }

  /* ---- the specification again, from the red triangle ------------------------------------------------ */
  async function specDialog(ctx, kind) {
    const p = ctx.names('x').length;
    const cur = settingsOf(ctx);
    const fields = FIELDS[kind].map((f) => {
      const d = typeof f.dflt === 'function' ? f.dflt(p, cur) : f.dflt;
      if (f.type === 'check') return { key: f.key, label: f.label, type: 'check', value: cur[f.key] ?? d };
      if (f.type === 'select') return { key: f.key, label: f.label, type: 'select', value: cur[f.key] ?? d, choices: f.choices };
      return { key: f.key, label: f.label, type: 'number', value: cur[f.key] ?? d };
    });
    const v = await SM.ui.form({ title: `${KIND[kind].label} Specification`, info: 'p:ensemble:spec', fields,
      lead: kind === 'forest' ? 'The forest\'s settings, as JMP\'s Bootstrap Forest Specification window has them. OK fits the forest again.' : 'The boosted tree\'s settings, as JMP\'s Gradient-Boosted Trees Specification window has them. OK fits it again.',
      validate: (x) => checkSettings(kind, x) });
    if (!v) return;
    const out = {};
    for (const f of FIELDS[kind]) if (v[f.key] != null) out[f.key] = v[f.key];
    ctx.set('shownFit', null, null, { rerun: false });
    ctx.set('settings', out);
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
    items.push({ label: 'Save Columns', submenu: () => [...save.submenu(), { label: 'Save Cumulative Details', action: () => saveCumulative(ctx, r, K) }] });
    items.push(...tail);
    return items;
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const ROLES = { heading: 'Roles', choices: [['Y, Response', 'A continuous response (a regression forest or boosted tree), or a nominal or ordinal one (a classifier; an ordinal one\'s order is not used).'], ['X, Factor', 'The predictors: continuous ones as they are, a categorical one as a 0/1 column per level. With Informative Missing a missing value is the training mean plus a Missing column, or a level of its own.'], ['Weight, Freq', 'Case weights in the fit and the measures.'], ['Validation', 'Training, validation and test rows; or a Validation Portion. The validation rows choose the number of trees or layers and the best of Multiple Fits.']] };
  const TOPICS = {
    'p:forest': {
      kicker: 'Analyze > Predictive Modeling', title: 'Bootstrap Forest',
      lead: 'The average of many decision trees, each grown on a bootstrap sample of the training rows with a random set of the X columns tried at each split (scikit-learn\'s RandomForestRegressor and RandomForestClassifier). Each tree is then cut back as JMP describes its trees stopping, and a categorical response\'s probabilities are JMP\'s.',
      sections: [ROLES,
        { heading: 'Each tree', text: 'scikit-learn grows the tree best first up to Maximum Splits per Tree, with at least Minimum Size Split rows on each side of a split. JMP says its trees split until a stopping criterion stops improving and are then pruned back one split; here the criterion is the tree\'s out-of-bag loss: past Minimum Splits per Tree a split stays while it lowers the loss of the rows the tree did not see, and the first that does not is taken back. Tree Size ▸ Grow to Maximum Splits keeps scikit-learn\'s trees whole.' },
        { heading: 'Probabilities', text: 'As JMP\'s Partition: at each node Prob = (n + prior)/(N + 1), the node\'s counts n (N in all) plus a prior worth one row, the prior 0.9 of the parent\'s prior and 0.1 of the parent\'s Prob, at the root the root\'s shares. So no probability is 0 (scikit-learn\'s own leaves give 0 for a level missing from a leaf); the forest averages its trees\' probabilities.' },
        { heading: 'Early Stopping', text: 'With validation rows: the trees are grown one at a time, and when the last tenth of the trees asked for (at least 5) has not improved the validation RSquare (Entropy RSquare for a categorical response), growth stops and the best number is kept. The first k trees of a forest do not depend on how many are grown, so the kept forest is the forest of that many trees.' },
        { heading: 'Beyond and short of JMP', text: 'The Out of Bag line of Overall Statistics and Permutation Importance are not in JMP. A categorical X is split one level against the others (JMP splits its levels into two groups); Ordinal Restricts Order, Profit Matrix, Decision Threshold and the prediction formula are not here.' }],
      more: KIND.forest.more,
    },
    'p:boosted': {
      kicker: 'Analyze > Predictive Modeling', title: 'Boosted Tree',
      lead: 'A sum of small trees (layers), each fitted to the residuals of the layers before it and scaled by the learning rate (scikit-learn\'s GradientBoostingRegressor and GradientBoostingClassifier, their trees grown best first to Splits per Tree splits).',
      sections: [ROLES,
        { heading: 'Early Stopping', text: 'With validation rows, as JMP: the fit stops at the first layer that does not improve the validation RSquare (Entropy RSquare for a categorical response) and keeps the layers before it.' },
        { heading: 'A categorical response', text: 'Each layer fits the gradient of the log likelihood (the log odds for two levels, a tree per level for more; JMP takes two levels only). JMP\'s Overfit Penalty has no scikit-learn counterpart and is not used: the leaf values are scikit-learn\'s Newton steps.' },
        { heading: 'Sampling', text: 'Row Sampling Rate draws that share of the training rows for each layer (scikit-learn\'s subsample; JMP stratifies a categorical response). Column Sampling Rate tries that share of the columns at each split (scikit-learn\'s max_features); JMP draws the columns once per layer.' }],
      more: KIND.boosted.more,
    },
    'p:ensemble:spec': {
      kicker: 'Bootstrap Forest, Boosted Tree', title: 'Specifications',
      lead: 'The settings of the fit, with JMP\'s defaults. Change Specifications… (red triangle) fits again.',
      sections: [
        { heading: 'Bootstrap Forest', choices: [['Number of Trees in the Forest', '100'], ['Number of Terms Sampled per Split', 'the X columns tried at each split; JMP 16 and later default to p - floor(p/4) (13 terms: 10), earlier versions to floor(p/4). A categorical X takes its share of the 0/1 columns.'], ['Bootstrap Sample Rate', 'the share of the training rows drawn, with replacement, for each tree (1)'], ['Minimum and Maximum Splits per Tree', '10 and 2000'], ['Minimum Size Split', 'the fewest rows on each side of a split (5)'], ['Early Stopping', 'with validation rows (on)'], ['Multiple Fits over Number of Terms', 'forests from the number of terms up to Max Number of Terms, each about 1.25 times the one before (JMP\'s example: 4, 5, 6, 8, 10)']] },
        { heading: 'Boosted Tree', choices: [['Number of Layers', '50'], ['Splits per Tree', '3'], ['Learning Rate', '0.1, between 0 and 1'], ['Minimum Size Split', '5'], ['Row and Column Sampling Rates', '1'], ['Multiple Fits over Splits and Learning Rate', 'every splits per tree up to Max Splits per Tree and every learning rate up to Max Learning Rate in steps of 0.1']] },
        { heading: 'Random Seed', text: 'The bootstrap samples, the columns tried and the row sampling follow the report\'s seed (scikit-learn\'s random_state), so a redraw, a project and the Python code give the same model.' },
      ],
    },
    'p:ensemble:summaries': { kicker: 'Bootstrap Forest, Boosted Tree', title: 'Model Validation-Set Summaries', lead: 'Every fit of Multiple Fits with its validation set\'s statistics (a forest without validation rows: the out-of-bag statistics). The report shows the fit with the largest RSquare, or Entropy RSquare for a categorical response; a click on another line shows that one.' },
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
    'p:ensemble:trees': { kicker: 'Bootstrap Forest, Boosted Tree', title: 'Tree Views', lead: 'One tree of the forest (as it was cut back) or one layer of the boosted tree, a line per node: the split that leads to it and, with estimates, its training rows (weighted, in bag) and its mean or JMP probabilities; a layer\'s estimate is what it adds to the prediction.' },
  };

  /* ======================================================================
     THE PLATFORMS
     ====================================================================== */
  const ABOUT = {
    forest: 'JMP Pro\'s Bootstrap Forest: many decision trees, each grown on a bootstrap sample of the training rows with a random set of the X columns tried at each split, averaged; each tree cut back by its out-of-bag loss past Minimum Splits per Tree, as JMP describes its trees stopping, and a categorical response\'s probabilities JMP\'s (never 0). Early stopping on the validation rows, Multiple Fits over the number of terms; Model Validation-Set Summaries, Specifications, Overall Statistics with Individual Trees and an out-of-bag estimate, Cumulative Validation with its details, Per-Tree Summaries, Column Contributions, and from the red triangle permutation importance, actual by predicted, ROC and lift curves, tree views, the Prediction Profiler and Save Columns.',
    boosted: 'JMP Pro\'s Boosted Tree: a sum of small trees, each fitted to the residuals of the ones before and scaled by the learning rate, for a continuous or categorical response. Early stopping at the first layer that does not improve the validation statistic, Multiple Fits over splits per tree and learning rate, row and column sampling; Model Validation-Set Summaries, Specifications, Overall Statistics, Cumulative Validation with its details, Column Contributions, and from the red triangle permutation importance, actual by predicted, ROC and lift curves, the layers\' trees, the Prediction Profiler and Save Columns.',
  };
  const USES = {
    forest: ['sklearn.ensemble.RandomForestRegressor, RandomForestClassifier (warm_start, estimators_samples_)', 'sklearn.tree trees: apply, decision_path, compute_node_depths', 'numpy'],
    boosted: ['sklearn.ensemble.GradientBoostingRegressor, GradientBoostingClassifier (monitor, staged_predict, staged_predict_proba)', 'numpy'],
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
          { key: 'y', label: 'Y, Response', min: 1, max: 1, hint: 'required' },
          { key: 'x', label: 'X, Factor', min: 1, hint: 'required: one or more' },
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
