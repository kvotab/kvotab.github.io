/* ==========================================================================
   SMUI.HTML: ANALYZE > PREDICTIVE MODELING > NEURAL

   JMP's Neural platform, fitted as JMP documents it by a network of our own
   (numpy, and scipy's L-BFGS; resources/py/smui/neural.py). The report
   opens with JMP's Model Launch; each Go adds a model, kept in the report's
   options (so Redo and projects keep them), each in its own outline named
   as JMP names it (Model NTanH(3)):

     Model Launch         Validation Method (Holdback, KFold, Excluded Rows
                          Holdback; or the Validation column, whose K folds
                          make KFold), Hidden Layer Structure (the TanH,
                          Linear and Gaussian nodes of the first and second
                          layer), Boosting (Number of Models, Learning Rate),
                          Fitting Options (Transform Covariates, Robust Fit,
                          Penalty Method, Number of Tours)
     Model NTanH(3)       the Measures of Fit per set and response, and the
                          confusion matrices; from its red triangle the
                          Diagram, Estimates, Profiler, ROC and Lift Curves,
                          Actual and Residual by Predicted, Fitting Details,
                          Save Columns and Remove Fit
     Model Comparison     every model's measures, when there are several
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, svg, fmt } = SM.util;
  const MORE = { label: 'Neural', id: 'help-p-neural' };
  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));

  const ACTS = [['tanh', 'TanH'], ['linear', 'Linear'], ['gauss', 'Gaussian']];
  const ACT_NAME = { tanh: 'TanH', linear: 'Linear', gauss: 'Gaussian' };
  const LAYER_KEYS = [['t1', 'l1', 'g1'], ['t2', 'l2', 'g2']];   // each activation's nodes, the first layer (next to the responses) and the second
  const METHODS = [['holdback', 'Holdback'], ['kfold', 'KFold'], ['excluded', 'Excluded Rows Holdback']];
  const PENALTIES = [['squared', 'Squared'], ['absolute', 'Absolute'], ['weight_decay', 'Weight Decay'], ['none', 'No Penalty']];
  // JMP's Model Launch defaults (Maximum Iterations is ours: JMP stops each fit early, by the validation likelihood)
  const DEFAULTS = { method: 'holdback', portion: 0.3333, folds: 5, t1: 3, l1: 0, g1: 0, t2: 0, l2: 0, g2: 0, boost: 0, rate: 0.1, transform: false, robust: false, penalty: 'squared', tours: 1, max_iter: 200 };
  const KEYS = Object.keys(DEFAULTS);

  /* A model saved before a layer could mix activations (activation, n1, n2) as its nodes of that activation
     (scikit-learn's Logistic and ReLU as TanH, which the backend says in a note). */
  function normalize(m) {
    if (!m || LAYER_KEYS[0].some((k) => Number.isInteger(m[k])) || !Number.isInteger(m.n1)) return m;
    const k = { identity: 'l', linear: 'l', gauss: 'g' }[m.activation] || 't';
    const out = { ...m, t1: 0, l1: 0, g1: 0, t2: 0, l2: 0, g2: 0 };
    out[`${k}1`] = m.n1;
    out[`${k}2`] = m.n2 || 0;
    return out;
  }

  /* JMP's name of a model: NTanH(3), NTanH(2)NLinear(1), NTanH(3)NTanH2(2), NGaussian(2)NBoost(10). */
  function modelName(m) {
    m = normalize(m);
    let s = '';
    LAYER_KEYS.forEach((keys, li) => keys.forEach((k, j) => { if (m[k] && !(li && m.boost)) s += `N${ACTS[j][1]}${li ? '2' : ''}(${m[k]})`; }));
    if (m.boost) s += `NBoost(${m.boost})`;
    return s;
  }

  const modelsOf = (ctx) => (ctx.opt('models', []) || []).map(normalize).filter((m) => m && m.id && LAYER_KEYS[0].every((k) => Number.isInteger(m[k])));

  /* The excluded rows of this By group (and of the Local Data Filter): the
     validation rows of Excluded Rows Holdback. */
  function excludedRows(ctx) {
    const t = ctx.table;
    let rows = ctx.report.filterRows(t.rowsWith('excluded', true));
    for (const w of ctx.where || []) {
      const c = t.col(w.column);
      if (c) rows = rows.filter((r) => c.values[r] === w.value);
    }
    return rows;
  }

  /* What the backend needs to find (or fit) a model. */
  function payloadOf(ctx, m) {
    const base = SM.predict.payload(ctx);
    const validation = base.validation;
    const model = Object.fromEntries(KEYS.map((k) => [k, m[k] ?? DEFAULTS[k]]));
    if (validation) model.method = 'column';
    const p = { y: ctx.names('y'), x: ctx.names('x'), freq: base.freq, validation, seed: base.seed, missing: base.missing, model };
    if (model.method === 'excluded') {
      const ex = excludedRows(ctx);
      p.rows = ctx.rows.concat(ex).sort((a, b) => a - b);
      p.holdback = ex;
    }
    return p;
  }

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx) {
    const models = modelsOf(ctx);
    const v = ctx.role('validation');
    if (v) ctx.container.append(el('p', { class: 'sm-nn-vline', text: `Validation Column: ${v.name}` }));
    launchOutline(ctx, models);
    if (!models.length) {
      ctx.container.append(ctx.note('Set the network in the Model Launch and press Go: each Go fits a model, and the models of one report are compared.'));
      return;
    }
    const cmp = models.length > 1 && ctx.opt('comparison', true) ? ctx.outline('Model Comparison', { key: 'comparison', info: 'p:neural:compare', menu: () => [{ label: 'Remove', action: () => ctx.set('comparison', false) }] }) : null;
    const results = [];
    for (const m of models) results.push({ m, res: await modelOutline(ctx, m) });
    if (cmp) comparison(ctx, cmp, results);
  }

  /* ======================================================================
     THE MODEL LAUNCH
     ====================================================================== */
  function launchOutline(ctx, models) {
    const vcol = ctx.role('validation');
    const st = { ...DEFAULTS, ...(ctx.opt('launch', null) || {}) };
    const ob = ctx.outline('Model Launch', { key: 'launch', info: 'p:neural:launch', closed: models.length > 0 });
    const inputs = {};
    const num = (key, label, size = 5) => {
      const i = el('input', { type: 'text', inputmode: 'decimal', size, 'aria-label': label, class: 'sm-nn-num' });
      i.value = String(st[key]);
      i.addEventListener('change', keep);
      inputs[key] = i;
      return i;
    };
    const pick = (key, items, label) => {
      const s = el('select', { 'aria-label': label }, ...items.map(([v, l, off]) => el('option', { value: v, text: l, disabled: off || null })));
      s.value = st[key];
      if (s.selectedIndex < 0 || (s.options[s.selectedIndex] && s.options[s.selectedIndex].disabled)) s.value = DEFAULTS[key];
      s.addEventListener('change', () => { keep(); shown(); });
      inputs[key] = s;
      return s;
    };
    const check = (key, label, disabled = false) => {
      const i = el('input', { type: 'checkbox', 'aria-label': label, disabled: disabled || null });
      i.checked = !disabled && !!st[key];
      if (!disabled) { i.addEventListener('change', keep); inputs[key] = i; }
      return el('label', { class: `sm-nn-check${disabled ? ' is-off' : ''}` }, i, el('span', { text: label }));
    };
    const field = (label, input, cls) => el('label', { class: `sm-nn-field${cls ? ` ${cls}` : ''}` }, el('span', { text: label }), input);
    const box = (legend, ...kids) => el('fieldset', { class: 'sm-nn-box' }, el('legend', { text: legend }), ...kids);

    // Validation Method
    let vbox;
    const kf = vcol ? foldsOf(vcol) : 0;
    if (vcol) vbox = box('Validation Method', el('p', { class: 'sm-nn-line', text: `Validation Column: ${vcol.name}` }), el('p', { class: 'sm-nn-hint', text: kf ? `Its ${kf} values are ${kf} folds: KFold by them, each fold validating the model of the others.` : 'The column\'s 0 (Training), 1 (Validation) and 2 (Test) rows.' }));
    else {
      const method = pick('method', METHODS, 'Validation Method');
      vbox = box('Validation Method', el('div', { class: 'sm-nn-fields' }, field('Method', method),
        field('Holdback Proportion', num('portion', 'Holdback Proportion'), 'sm-nn-portion'), field('Number of Folds', num('folds', 'Number of Folds', 4), 'sm-nn-folds')));
    }
    // Hidden Layer Structure: the nodes of each activation in each layer, as JMP's table has them
    const hbox = box('Hidden Layer Structure',
      el('p', { class: 'sm-nn-hint', text: 'Number of nodes of each activation type in each layer.' }),
      el('table', { class: 'sm-nn-layers' },
        el('thead', null, el('tr', null, el('th', { text: 'Layer' }), ...ACTS.map(([, lab]) => el('th', { text: lab })))),
        el('tbody', null, ...['First', 'Second'].map((lab, li) => el('tr', null, el('td', { text: lab }),
          ...LAYER_KEYS[li].map((k, j) => el('td', null, num(k, `${lab} layer ${ACTS[j][1]} nodes`, 3))))))),
      el('p', { class: 'sm-nn-hint', text: 'Second layer is closer to X\'s in two layer models.' }));
    // Boosting
    const bbox = box('Boosting', el('p', { class: 'sm-nn-hint', text: 'Fit an additive sequence of models scaled by the learning rate.' }),
      el('div', { class: 'sm-nn-fields' }, field('Number of Models', num('boost', 'Number of Models', 4)), field('Learning Rate', num('rate', 'Learning Rate'))));
    // Fitting Options
    const fbox = box('Fitting Options',
      el('div', { class: 'sm-nn-checks' }, check('transform', 'Transform Covariates'), check('robust', 'Robust Fit')),
      el('div', { class: 'sm-nn-fields' }, field('Penalty Method', pick('penalty', PENALTIES, 'Penalty Method')), field('Number of Tours', num('tours', 'Number of Tours', 4)),
        field('Maximum Iterations', num('max_iter', 'Maximum Iterations', 6))));
    const msg = el('p', { class: 'sm-nn-msg', role: 'status' });
    const go = el('button', { type: 'button', class: 'sm-btn primary sm-nn-go', text: 'Go' });
    go.addEventListener('click', () => {
      const spec = read();
      const err = checkSpec(spec, ctx);
      msg.textContent = err || '';
      if (err) return;
      addModel(ctx, spec);
    });
    function read() {
      const out = { ...st };
      for (const [k, i] of Object.entries(inputs)) {
        if (i.type === 'checkbox') out[k] = i.checked;
        else if (i.tagName === 'SELECT') out[k] = i.value;
        else { const t = i.value.trim().replace(',', '.').replace('−', '-'); out[k] = t === '' ? DEFAULTS[k] : SM.table.toNumber(t); }
      }
      return out;
    }
    function keep() { ctx.set('launch', read(), null, { rerun: false }); }
    function shown() {
      const m = inputs.method ? inputs.method.value : null;
      ob.body.querySelectorAll('.sm-nn-portion').forEach((e) => { e.hidden = m !== 'holdback'; });
      ob.body.querySelectorAll('.sm-nn-folds').forEach((e) => { e.hidden = m !== 'kfold'; });
    }
    const seed = SM.predict.payload(ctx).seed;
    ob.add(el('div', { class: 'sm-nn-launch' }, vbox, hbox, bbox, fbox),
      el('div', { class: 'sm-nn-actions' }, go, el('span', { class: 'sm-nn-seed', text: `Random Seed ${seed}${ctx.opt('seed', '') === '' ? ' (drawn for this report)' : ''}` })), msg);
    shown();
    return ob;
  }

  /* The folds of a Validation column (its distinct values when more than three: whole numbers, or texts none
     of which is Training, Validation or Test), or 0: predictive.prepare reads such a column as K folds. */
  function foldsOf(col) {
    const seen = new Set();
    for (const v of col.values) if (v != null && v !== '' && !(typeof v === 'number' && Number.isNaN(v))) seen.add(v);
    if (seen.size <= 3 || seen.size > 50) return 0;
    const vals = [...seen];
    if (col.isNumeric) return vals.every((v) => Number.isInteger(v)) ? vals.length : 0;
    return vals.some((v) => ['training', 'train', 'validation', 'valid', 'test'].includes(String(v).trim().toLowerCase())) ? 0 : vals.length;
  }

  function checkSpec(s, ctx) {
    const int = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;
    for (const [li, keys] of LAYER_KEYS.entries()) for (const [j, k] of keys.entries()) if (!int(s[k], 0, 500)) return `The ${li ? 'second' : 'first'} layer's ${ACTS[j][1]} nodes are a whole number from 0 to 500.`;
    if (s.t1 + s.l1 + s.g1 < 1) return 'The first layer needs at least one node.';
    if (!int(s.boost, 0, 1000)) return 'The Number of Models is a whole number from 0 to 1000.';
    if (!(s.rate > 0 && s.rate <= 1)) return 'The Learning Rate is above 0 and at most 1.';
    if (!int(s.tours, 1, 100)) return 'The Number of Tours is a whole number from 1 to 100.';
    if (!int(s.max_iter, 1, 100000)) return 'The Maximum Iterations is a whole number from 1 to 100000.';
    if (!ctx.role('validation')) {
      if (s.method === 'holdback' && !(s.portion > 0 && s.portion < 1)) return 'The Holdback Proportion is between 0 and 1.';
      if (s.method === 'kfold' && !int(s.folds, 2, Math.min(50, ctx.rows.length))) return `The Number of Folds is a whole number from 2 to ${Math.min(50, ctx.rows.length)}.`;
    }
    return null;
  }

  function addModel(ctx, spec) {
    const seq = (Number(ctx.opt('modelSeq', 0)) || 0) + 1;
    const m = { id: `m${seq}`, ...Object.fromEntries(KEYS.map((k) => [k, spec[k]])) };
    if (m.boost && (m.t2 || m.l2 || m.g2)) { m.t2 = m.l2 = m.g2 = 0; SM.ui.toast('Boosting takes one hidden layer: the second layer is ignored, as in JMP'); }
    ctx.set('launch', spec, null, { rerun: false });
    ctx.set('modelSeq', seq, null, { rerun: false });
    ctx.set('models', [...modelsOf(ctx), m]);
  }

  /* ======================================================================
     A MODEL
     ====================================================================== */
  async function modelOutline(ctx, m) {
    const sc = m.id;
    let res = null;
    const ob = ctx.outline(`Model ${modelName(m)}`, { key: `model:${m.id}`, info: 'p:neural:model', menu: () => modelMenu(ctx, m, res) });
    ob.el.dataset.model = m.id;
    const payload = payloadOf(ctx, m);
    const wait = ctx.headless ? null : el('p', { class: 'sm-ob-note sm-nn-progress', role: 'status', text: 'Fitting…' });
    if (wait) ob.add(wait);
    const off = ctx.headless ? null : SM.engine.on('progress', (p) => {
      if (!p || p.what !== 'neural') return;
      const text = `Model ${modelName(m)}${ctx.byLabel ? ` (${ctx.byLabel})` : ''}: ${p.done} of ${p.total} fits…`;
      wait.textContent = text;
      ctx.report.noteEl.textContent = text;
    });
    try { res = await ctx.call('neural.fit', payload); } catch (e) { ob.add(ctx.error(e)); return null; } finally { if (off) off(); if (wait) wait.remove(); }
    if (res.error) { ob.add(ctx.warn(res.error)); return null; }
    ob.add(ctx.note(summaryText(res)));
    if (res.notes && res.notes.length) ob.add(ctx.note(res.notes.join(' ')));
    const ycols = ctx.roles('y');
    const multi = res.responses.length > 1;
    for (const r of res.responses) {
      const yc = ycols.find((c) => c.name === r.y);
      const yk = yc ? yc.id : r.y;
      const parent = multi ? ctx.outline(r.y, { parent: ob, key: `resp:${m.id}:${yk}` }) : ob;
      scrollTables(SM.predict.measures(ctx, parent, r.fit, { title: multi ? 'Measures of Fit' : `Measures of Fit for ${r.y}`, key: `measures:${m.id}:${yk}` }));
      // the Decision Threshold's save: this response's probabilities (named with it among several)
      if (r.kind === 'categorical') SM.predict.classification(ctx, parent, r.fit, sc, `${m.id}:${yk}:`, { save: { fn: 'neural.save', payload: { ...payload, response: r.y } }, probName: (label) => (multi ? `${r.y} Prob[${label}]` : `Prob[${label}]`), yCol: yc });
      else {
        if (ctx.opt('abp', false, sc)) SM.predict.actualByPredicted(ctx, parent, r.fit, { key: `abp:${m.id}:${yk}` });
        if (ctx.opt('rbp', false, sc)) residualByPredicted(ctx, parent, r.fit, `rbp:${m.id}:${yk}`);
      }
    }
    if (ctx.opt('diagram', false, sc)) diagramOutline(ctx, ob, m, res);
    if (ctx.opt('estimates', false, sc)) estimatesOutline(ctx, ob, m, res);
    if (ctx.opt('profiler', false, sc)) {
      await SM.profiler.render(ctx, ob, { sources: [{ fn: 'neural.profile', payload }], scope: sc, option: 'profiler', key: `profiler:${m.id}`,
        note: 'Drag the red dashed line of a factor, click in its plot, or type its value. The network has no confidence limits (JMP\'s Neural profiler has none either).' });
    }
    if (ctx.opt('details', false, sc)) detailsOutline(ctx, ob, m, res);
    ob.add(ctx.code(res.script));
    return res;
  }

  /* The shared blocks' tables in a box of their own, which scrolls on a
     phone instead of widening the report. */
  function scrollTables(ob) {
    if (!ob || !ob.body) return;
    for (const t of ob.body.querySelectorAll(':scope > table.sm-rt')) {
      const w = el('div', { class: 'sm-nn-scroll' });
      t.replaceWith(w);
      w.append(t);
    }
  }

  function summaryText(res) {
    const v = res.validation;
    const parts = [];
    if (v.method === 'holdback') parts.push(`Validation: Random Holdback, ${fmt(v.portion)} of the rows (seed ${res.seed}).`);
    else if (v.method === 'kfold') parts.push(`Validation: KFold, ${v.folds} folds (seed ${res.seed}): the model shown is the one fitted without fold ${v.fold}, whose network fits every row best, and fold ${v.fold} is its validation set.`);
    else if (v.method === 'folds') parts.push(`Validation: KFold by the ${v.folds} folds of ${v.column}: the model shown is the one fitted without fold ${v.fold}, whose network fits every row best, and that fold is its validation set.`);
    else if (v.method === 'excluded') parts.push('Validation: Excluded Rows Holdback: the excluded rows validate.');
    else parts.push(`Validation Column: ${v.column}.`);
    const validates = (res.n.Validation || 0) > 0;
    for (const net of res.nets) {
      const who = res.nets.length > 1 ? `${net.responses.join(', ')}: ` : '';
      const penName = { squared: 'Squared', absolute: 'Absolute', weight_decay: 'Weight Decay' }[net.penalty];
      const pen = net.penalty === 'none' ? 'No Penalty' : `${penName} penalty λ ${fmt(net.lambda)}${validates ? ', chosen by the validation likelihood' : ''}`;
      const its = Array.isArray(net.iterations) ? net.iterations : [net.iterations];
      const it = net.boosted ? `${net.components} of ${res.spec.boost} base model${res.spec.boost > 1 ? 's' : ''} kept` : `${its[0]} L-BFGS iterations${its[0] >= net.max_iter ? ' (the maximum)' : ''}`;
      parts.push(`${who}${pen}; ${it}${net.robust ? '; Robust Fit: least absolute deviations' : ''}.`);
    }
    if (res.tours.length > 1) parts.push(`Tour ${res.tour} of ${res.tours.length} had the best validation likelihood.`);
    return parts.join(' ');
  }

  function modelMenu(ctx, m, res) {
    const sc = m.id;
    const kinds = new Set(res ? res.responses.map((r) => r.kind) : []);
    const items = [ctx.check('Diagram', 'diagram', sc, false), ctx.check('Show Estimates', 'estimates', sc, false), ctx.check('Profiler', 'profiler', sc, false)];
    if (kinds.has('categorical')) items.push(ctx.check('Confusion Matrix', 'confusion', sc, true), ctx.check('ROC Curve', 'roc', sc, false), ctx.check('Lift Curve', 'lift', sc, false));
    if (kinds.has('continuous')) items.push(ctx.check('Plot Actual by Predicted', 'abp', sc, false), ctx.check('Plot Residual by Predicted', 'rbp', sc, false));
    items.push(ctx.check('Fitting Details', 'details', sc, false), { separator: true },
      { label: 'Save Columns', disabled: !res, submenu: () => saveMenu(ctx, m, res) },
      { separator: true },
      { label: 'Remove Fit', action: () => ctx.set('models', modelsOf(ctx).filter((x) => x.id !== m.id)) });
    return items;
  }

  /* Residual by Predicted, one plot per set, linked to the rows. */
  function residualByPredicted(ctx, parent, fit, key) {
    const r = fit.residuals;
    if (!r) return;
    const ob = ctx.outline('Residual by Predicted Plot', { parent, key, info: 'p:neural:residual' });
    const muted = SM.util.themeColors().muted;
    const pc = fit.plots || {};
    const plots = fit.sets.map((set) => {
      const k = ['Training', 'Validation', 'Test'].indexOf(set);
      const idx = r.set.map((s, i) => (s === k ? i : -1)).filter((i) => i >= 0);
      const xs = idx.map((i) => r.predicted[i]), ys = idx.map((i) => r.actual[i] - r.predicted[i]);
      let lo = Infinity, hi = -Infinity;
      for (const v of xs) if (Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      return SM.predict.plotWithCode(ctx, [
        { type: 'scatter', mode: 'markers', x: xs, y: ys, rows: idx.map((i) => r.rows[i]), marker: { size: 5 }, name: set },
        { type: 'scatter', mode: 'lines', x: [lo, hi], y: [0, 0], line: { color: muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false },
      ], { title: { text: set, font: { size: 12 } }, margin: { l: 56, r: 12, t: 28, b: 42 }, xaxis: { title: { text: 'Predicted' } }, yaxis: { title: { text: 'Residual' }, zeroline: false } }, { width: W(320), height: 280, title: `Residual by predicted ${set}` },
      pc.head_code, pc.rbp && pc.rbp[set]);
    });
    ob.add(ctx.row(...plots), ctx.note('The actual value less the prediction, against the prediction: a pattern means the network misses a shape in the data; a funnel, a spread that changes with the level.'));
  }

  /* ---- Estimates: every weight and bias ---------------------------------------------------- */
  function estimatesOutline(ctx, parent, m, res) {
    const ob = ctx.outline('Estimates', { parent, key: `est:${m.id}`, info: 'p:neural:estimates', menu: () => [{ label: 'Remove', action: () => ctx.set('estimates', false, m.id) }] });
    const several = res.nets.length > 1;
    res.nets.forEach((net, k) => {
      ob.add(el('div', { class: 'sm-nn-scroll' }, ctx.rt({ columns: [{ key: 'parameter', label: 'Parameter', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }], rows: net.estimates },
        { key: `est:${m.id}:${k}`, caption: several ? `The network of ${net.responses.join(', ')}` : null, sortable: false, name: `Estimates ${modelName(m)}` })));
    });
    const tf = res.nets.some((n) => n.transformed.length);
    const cat = res.nets.some((n) => n.kind === 'categorical');
    ob.add(ctx.note(`Hn_k is node k of hidden layer n (H1 next to the responses; H2, of a two-layer network, next to the X's); A:B is the weight on B in node A's sum, A:Intercept its constant. The weights are on the design's own scale (JMP's design: a categorical factor's effect coding, x[level] for each level but the last, the last −1; a missing value's column x Missing): the centring and scaling the network is fitted on is folded into them${tf ? ', and T(x) is a covariate after Transform Covariates, its Johnson transform' : ''}. A continuous response's output is on its own scale${cat ? '; a categorical response has the log odds of each level against the last (y[level]:H1_1), as JMP writes them' : ''}. ${res.nets.some((n) => n.boosted) ? 'A boosted network is written as the one network it is: every base model\'s nodes side by side, their outputs weighted by the learning rate (the last by 1).' : ''}`));
  }

  /* ---- Fitting Details: the penalty path, tours, folds, boosting ---------------------------- */
  function detailsOutline(ctx, parent, m, res) {
    const ob = ctx.outline('Fitting Details', { parent, key: `details:${m.id}`, info: 'p:neural:details', menu: () => [{ label: 'Remove', action: () => ctx.set('details', false, m.id) }] });
    const kfold = res.validation.method === 'kfold' || res.validation.method === 'folds';
    const chosen = (r) => (r.chosen ? 'sm-nn-chosen' : '');
    res.nets.forEach((net, k) => {
      const who = res.nets.length > 1 ? ` (${net.responses.join(', ')})` : '';
      ob.add(el('div', { class: 'sm-nn-scroll' }, ctx.rt({
        columns: [{ key: 'lambda', label: 'Penalty λ' }, { key: 'iterations', label: kfold ? 'Mean Iterations' : 'Iterations' }, { key: 'train', label: 'Training -LogLikelihood' }, { key: 'valid', label: 'Validation -LogLikelihood' }, { key: 'mark', label: '', fmt: 'text' }],
        rows: net.path.map((r) => ({ ...r, mark: r.chosen ? 'chosen' : '' })),
      }, { key: `path:${m.id}:${k}`, caption: `Penalty Path${who}${kfold ? ', summed over the folds' : ''}`, sortable: false, cellClass: chosen })));
      if (net.boosted && net.boost) {
        ob.add(el('div', { class: 'sm-nn-scroll' }, ctx.rt({
          columns: [{ key: 'model', label: 'Base Model', fmt: 'int' }, { key: 'iterations', label: 'Iterations', fmt: 'int' }, { key: 'train', label: 'Training -LogLikelihood' }, { key: 'valid', label: 'Validation -LogLikelihood' }, { key: 'mark', label: '', fmt: 'text' }],
          rows: net.boost.map((r) => ({ ...r, mark: r.kept ? 'kept' : 'not kept: the validation likelihood got worse' })),
        }, { key: `boost:${m.id}:${k}`, caption: `Boosting${who}`, sortable: false })));
      }
    });
    if (res.tours.length > 1) {
      ob.add(ctx.rt({ columns: [{ key: 'tour', label: 'Tour', fmt: 'int' }, { key: 'criterion', label: 'Validation -LogLikelihood' }, { key: 'mark', label: '', fmt: 'text' }],
        rows: res.tours.map((r) => ({ ...r, mark: r.chosen ? 'chosen' : '' })) }, { key: `tours:${m.id}`, caption: 'Tours', sortable: false, cellClass: chosen }));
    }
    if (kfold && res.folds.length) {
      ob.add(ctx.rt({ columns: [{ key: 'fold', label: 'Fold', fmt: 'int' }, { key: 'rows', label: 'Rows', fmt: 'int' }, { key: 'valid', label: 'Validation -LogLikelihood' }, { key: 'all', label: '-LogLikelihood, Every Row' }, { key: 'mark', label: '', fmt: 'text' }],
        rows: res.folds.map((r) => ({ ...r, mark: r.chosen ? 'chosen' : '' })) }, { key: `folds:${m.id}`, caption: 'Folds, at the Chosen Penalty', sortable: false, cellClass: chosen }));
    }
    const lines = [];
    if (res.spec.penalty !== 'none') lines.push(`The penalty λ (times the ${{ squared: 'sum of the squared weights', absolute: 'sum of the absolute weights', weight_decay: 'sum of b²/(1 + b²) over the weights' }[res.spec.penalty]} of the hidden layers, added to the -log likelihood per row) runs up from none, each fit starting where the one before ended, until two penalties in a row do not improve the validation likelihood${kfold ? ' summed over the folds' : ''}; the λ with the best one is kept, as JMP searches its penalty. Each L-BFGS fit keeps its iterate with the best validation likelihood and stops 10 iterations after it (JMP's early stopping), or at the Maximum Iterations.`);
    if (res.nets.some((n) => n.boosted)) lines.push('Boosting: the first base model runs up the penalty path; the others are fitted at its penalty, each to the likelihood with the learning-rate-scaled sum of those before as an offset (on the log-odds scale for a categorical response), while the validation likelihood improves. The last one kept enters unscaled, as JMP describes.');
    if (res.tours.length > 1) lines.push('Each tour starts from new normal random weights (from the report\'s seed); the tour with the best validation likelihood is kept.');
    if (kfold) lines.push('KFold, as JMP does it: for each penalty the model of every fold; the penalty with the best validation likelihood summed over the folds; then the fold whose model fits every row best is the model shown, with that fold as its validation set.');
    ob.add(ctx.note(lines.join(' ')));
  }

  /* ======================================================================
     THE DIAGRAM
     ====================================================================== */
  const GLYPHS = {   // each activation's curve in its node (neural.draw_network draws the same)
    tanh: 'M -6 4 C -1.5 4 1.5 -4 6 -4',
    linear: 'M -6 5 L 6 -5',
    gauss: 'M -6 4 C -2.5 4 -1.5 -4.5 0 -4.5 C 1.5 -4.5 2.5 4 6 4',
  };

  function shortName(s, n = 22) { s = String(s); return s.length > n ? `${s.slice(0, n - 1)}…` : s; }

  /* The network drawn as JMP draws it: the X columns (boxes) on the left,
     the hidden nodes (circles, with their activation) in the middle, the
     responses (boxes) on the right; every weight is a line (hover it). */
  function diagramSVG(d) {
    const nIn = d.inputs.length;
    const layers = d.hidden.map((h) => h.n);
    const nOut = d.outputs.length;
    const most = Math.max(nIn, nOut, ...layers);
    const sp = most <= 12 ? 34 : most <= 30 ? 24 : 16;
    const r = sp >= 30 ? 11 : sp >= 24 ? 9 : 6;
    const pad = 16, top = 28;
    const inW = Math.min(170, Math.max(56, 7 * Math.max(...d.inputs.map((c) => shortName(c.name).length)) + 16));
    const outW = Math.min(170, Math.max(56, 7 * Math.max(...d.outputs.map((c) => shortName(c.name).length)) + 16));
    const gap = 120;
    const cols = [pad + inW / 2];
    for (let i = 0; i < layers.length; i++) cols.push(pad + inW + gap * (i + 1));
    cols.push(pad + inW + gap * (layers.length + 1) + outW / 2);
    const width = Math.ceil(cols[cols.length - 1] + outW / 2 + pad);
    const height = Math.ceil(top + most * sp + pad);
    const yOf = (i, n) => top + (most * sp) / 2 + (i - (n - 1) / 2) * sp;
    const s = svg('svg', { class: 'sm-nn-svg', width, height, viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': `Network diagram: ${nIn} inputs, ${layers.join(' and ')} hidden nodes, ${nOut} output${nOut > 1 ? 's' : ''}` });
    const edges = svg('g', { class: 'sm-nn-edges' });
    const nodes = svg('g');
    s.append(edges, nodes);
    const wtext = (v) => fmt(v, { sig: 4 });
    const line = (x1, y1, x2, y2, title) => svg('line', { x1, y1, x2, y2, class: 'sm-nn-edge' }, svg('title', null, title));
    // layer captions
    const caps = ['Inputs', ...d.hidden.map((h) => h.name), 'Outputs'];
    caps.forEach((c, i) => nodes.append(svg('text', { x: cols[i], y: 14, class: 'sm-nn-layer', 'text-anchor': 'middle' }, c)));
    // edges: inputs to the first hidden layer
    const W = d.weights;
    const hName = (li, k) => `${d.hidden[li].name}_${k + 1}`;
    const n0 = layers[0];
    d.inputs.forEach((c, j) => {
      for (let k = 0; k < n0; k++) {
        const ws = c.columns.map((q, qi) => `${c.features[qi]} ${wtext(W[0][q][k])}`).join(', ');
        edges.append(line(cols[0] + inW / 2, yOf(j, nIn), cols[1] - r, yOf(k, n0), `${c.name} → ${hName(0, k)}: ${ws}`));
      }
    });
    // hidden to hidden
    for (let li = 1; li < layers.length; li++) {
      for (let a = 0; a < layers[li - 1]; a++) for (let b = 0; b < layers[li]; b++) edges.append(line(cols[li] + r, yOf(a, layers[li - 1]), cols[li + 1] - r, yOf(b, layers[li]), `${hName(li - 1, a)} → ${hName(li, b)}: ${wtext(W[li][a][b])}`));
    }
    // the last hidden layer to the outputs
    const L = layers.length;
    const Wl = W[L];
    // each response's outputs: a continuous one's one, a categorical one's log odds of each level but the last
    const outCols = d.outputs.map((o, i) => { const [a, bb] = d.blocks ? d.blocks[i] : [i, i + 1]; return Array.from({ length: bb - a }, (_, q) => a + q); });
    for (let a = 0; a < layers[L - 1]; a++) {
      d.outputs.forEach((o, i) => {
        const ws = outCols[i].map((q) => `${d.out_names[q]} ${wtext(Wl[a][q])}`).join(', ');
        edges.append(line(cols[L] + r, yOf(a, layers[L - 1]), cols[L + 1] - outW / 2, yOf(i, nOut), `${hName(L - 1, a)} → ${o.name}: ${ws}`));
      });
    }
    // the nodes
    d.inputs.forEach((c, j) => {
      const y = yOf(j, nIn);
      nodes.append(svg('g', { class: 'sm-nn-in' }, svg('rect', { x: cols[0] - inW / 2, y: y - 10, width: inW, height: 20, rx: 3 }),
        svg('text', { x: cols[0], y: y + 4, class: 'sm-nn-label', 'text-anchor': 'middle' }, shortName(c.name)), svg('title', null, `${c.name}${c.features.length > 1 ? ` (${c.features.length} columns: ${c.features.join(', ')})` : ''}`)));
    });
    const b = d.biases;
    layers.forEach((n, li) => {
      for (let k = 0; k < n; k++) {
        const y = yOf(k, n);
        const act = (d.hidden[li].acts || [])[k] || 'tanh';
        nodes.append(svg('g', { class: 'sm-nn-hid' }, svg('circle', { cx: cols[li + 1], cy: y, r }),
          r >= 9 ? svg('path', { class: 'sm-nn-glyph', d: GLYPHS[act] || GLYPHS.tanh, transform: `translate(${cols[li + 1]} ${y}) scale(${(r / 11).toFixed(3)})` }) : null,
          svg('title', null, `${hName(li, k)} (${ACT_NAME[act] || act}): intercept ${wtext(b[li][k])}`)));
      }
    });
    d.outputs.forEach((o, i) => {
      const y = yOf(i, nOut);
      const bs = outCols[i].map((q) => `${d.out_names[q]} ${wtext(b[L][q])}`).join(', ');
      nodes.append(svg('g', { class: 'sm-nn-out' }, svg('rect', { x: cols[L + 1] - outW / 2, y: y - 10, width: outW, height: 20, rx: 3 }),
        svg('text', { x: cols[L + 1], y: y + 4, class: 'sm-nn-label', 'text-anchor': 'middle' }, shortName(o.name)), svg('title', null, `${o.name}: intercept ${bs}`)));
    });
    return s;
  }

  function diagramOutline(ctx, parent, m, res) {
    const ob = ctx.outline('Diagram', { parent, key: `diagram:${m.id}`, info: 'p:neural:diagram', menu: () => [{ label: 'Remove', action: () => ctx.set('diagram', false, m.id) }] });
    for (const net of res.nets) {
      if (res.nets.length > 1) ob.add(el('p', { class: 'sm-nn-caption', text: `The network of ${net.responses.join(', ')}` }));
      // the diagram with its code block right under it: the networks fitted (the model's head), then drawn
      ob.add(el('div', { class: 'sm-nn-scroll sm-nn-diagram' }, diagramSVG(net.diagram)), SM.predict.graphCode(ctx, res.plots && res.plots.head_code, net.diagram_code) || '');
    }
    ob.add(ctx.note(`The X columns on the left (a categorical one is one box for its effect-coded columns), the hidden nodes in the middle, each with its activation's curve (TanH an S, Linear a line, Gaussian a bell), the response${res.responses.length > 1 ? 's, every one in the one network,' : ''} on the right; every line is a weight: hover it for its value, or a node for its intercept.`));
  }

  /* ======================================================================
     THE MODEL COMPARISON
     ====================================================================== */
  function comparison(ctx, ob, results) {
    const ok = results.filter((x) => x.res && !x.res.error);
    if (!ok.length) { ob.add(ctx.note('No model could be fitted.')); return; }
    for (const yc of ctx.roles('y')) {
      const rows = [];
      let mcols = null;
      for (const { m, res } of ok) {
        const r = res.responses.find((q) => q.y === yc.name);
        if (!r) continue;
        mcols = mcols || r.fit.measure_columns;
        const v = res.validation;
        const how = v.method === 'holdback' ? `Holdback ${fmt(v.portion)}` : v.method === 'kfold' ? `KFold ${v.folds}` : v.method === 'excluded' ? 'Excluded Rows' : 'Column';
        for (const mm of r.fit.measures) rows.push({ model: `Model ${res.name}`, how, id: m.id, ...mm });
      }
      if (!rows.length) continue;
      const sets = new Set(rows.map((r) => r.set));
      const judge = sets.has('Validation') ? 'Validation' : 'Training';
      const pool = rows.filter((r) => r.set === judge && r.neg_loglik != null);
      const best = pool.length ? pool.reduce((a, b) => (b.neg_loglik < a.neg_loglik ? b : a)) : null;
      const cols = [{ key: 'model', label: 'Model', fmt: 'text' }, { key: 'how', label: 'Validation', fmt: 'text', hidden: new Set(rows.map((r) => r.how)).size < 2 },
        ...mcols.filter((c) => c.key !== 'auc' || rows.some((r) => r.auc != null))];
      ob.add(el('div', { class: 'sm-nn-scroll' }, ctx.rt({ columns: cols, rows }, {
        key: `cmp:${yc.id}`, caption: `Measures of Fit for ${yc.name}`, sortable: true,
        cellClass: (r, c) => (best && r.id === best.id && r.set === judge && c.key === 'model' ? 'sm-nn-chosen' : ''),
        onRow: (r) => { const box = ctx.report.body.querySelector(`.sm-ob[data-model="${r.id}"]`); if (box) box.scrollIntoView({ block: 'start', behavior: 'smooth' }); },
      })));
    }
    ob.add(ctx.note('Every model on every set of rows; the model marked has the smallest validation -LogLikelihood (training, without validation rows). Models with other validation methods are judged on other rows. Click a line to go to its model.'));
  }

  /* ======================================================================
     SAVE COLUMNS
     ====================================================================== */
  function saveMenu(ctx, m, res) {
    if (!res) return [];
    const kinds = new Set(res.responses.map((r) => r.kind));
    return [
      { label: 'Save Predicteds', action: () => saveCols(ctx, m, 'predicteds') },
      kinds.has('continuous') ? { label: 'Save Residuals', action: () => saveCols(ctx, m, 'residuals') } : null,
      { label: 'Save Hidden Layer Values', action: () => saveCols(ctx, m, 'hidden') },
      { separator: true },
      { label: 'Save Formulas', action: () => saveFormulas(ctx, m, res, 'formulas') },
      { label: 'Save Profile Formulas', action: () => saveFormulas(ctx, m, res, 'profile') },
      res.nets.some((n) => n.transformed.length) ? { label: 'Save Transformed Covariates', action: () => saveFormulas(ctx, m, res, 'transformed') } : null,
      res.validation.method !== 'column' && res.validation.method !== 'folds' ? { label: 'Save Validation', action: () => saveCols(ctx, m, 'validation') } : null,
    ].filter(Boolean);
  }

  /* JMP's formula columns of a model: Save Formulas (each hidden node a formula column of its own, H1_1, ..., and
     the predictions from them), Save Profile Formulas (the predictions alone, the hidden nodes written into
     them) and Save Transformed Covariates (the Johnson transforms). The hidden columns' names are taken before
     any is made, so the predictions' formulas refer to them; a categorical response's Most Likely column comes
     from its Prob[] columns. */
  async function saveFormulas(ctx, m, res, what) {
    const from = { notes: `a formula from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}, Model ${modelName(m)}` };
    try {
      const t = ctx.table;
      let names = null;
      if (what === 'formulas') {
        names = {};
        for (const h of res.nets[0].diagram.hidden) for (let i = 0; i < h.n; i++) names[`${h.name}_${i + 1}`] = t.uniqueName(`${h.name}_${i + 1}`);
      }
      const r = await ctx.call('neural.formula', { ...payloadOf(ctx, m), what, names });
      if (r.error) throw new Error(r.error);
      const made = {};
      for (const c of r.columns) {
        const col = ctx.saveFormula(c.hidden && names ? names[c.name] : c.name, c.expr, from);
        if (col) made[c.name] = col.name;
      }
      for (const mo of r.most || []) {
        const cols = mo.names.map((nm) => made[nm]);
        if (cols.every(Boolean)) ctx.saveFormula(mo.most_name, SM.partition.mostLikelyExpr(cols, mo.levels), { ...from, modelingType: mo.ordinal ? 'ordinal' : 'nominal', valueOrder: mo.levels.slice() });
      }
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  async function saveCols(ctx, m, what) {
    const from = { notes: `from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}, Model ${modelName(m)}` };
    try {
      const r = await ctx.call('neural.save', { ...payloadOf(ctx, m), what: what === 'residuals' ? 'predicteds' : what });
      if (r.error) { SM.ui.toast(r.error, { error: true }); return; }
      if (what === 'predicteds' || what === 'residuals') {
        for (const s of r.responses) {
          if (s.values) {
            if (what === 'residuals') ctx.saveColumn(`Residual ${s.y}`, { rows: s.rows, values: s.residuals }, from);
            else ctx.saveColumn(s.name, { rows: s.rows, values: s.values }, from);
          } else if (what === 'predicteds') {
            s.names.forEach((nm, j) => ctx.saveColumn(nm, { rows: s.rows, values: s.prob.map((p) => p[j]) }, from));
            ctx.saveColumn(s.most_name, { rows: s.rows, values: s.most_likely }, { ...from, dataType: 'character', modelingType: s.ordinal ? 'ordinal' : 'nominal', valueOrder: s.levels });
          }
        }
      } else if (what === 'validation') {
        ctx.saveColumn(r.name, { rows: r.rows, values: r.values }, { ...from, modelingType: 'nominal', notes: `${from.notes}: 0 training, 1 validation` });
      } else {
        for (const c of r.columns) ctx.saveColumn(c.name, { rows: r.rows, values: c.values }, from);
      }
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:neural': {
      kicker: 'Analyze > Predictive Modeling', title: 'Neural',
      lead: 'A neural network with one or two hidden layers predicts one or more responses from the factors, as JMP\'s Neural platform does and as JMP documents its numerics: every response in one network, fitted by maximizing the likelihood with a penalty, by L-BFGS (a quasi-Newton method like JMP\'s BFGS), stopping each fit early by the validation likelihood. The network is our own (numpy and scipy). The report opens with the Model Launch; each Go fits a model with its settings, so several can be fitted and compared in one report.',
      sections: [
        { heading: 'Roles', choices: [['Y, Response', 'One or more, continuous or categorical, all in one network: their log-likelihoods are summed, as JMP sums them.'], ['X, Factor', 'Continuous and categorical factors; a categorical one enters by JMP\'s effect coding, a column per level but the last.'], ['Freq', 'Row counts: a row with Freq 2 counts as two rows in the likelihood and in the design\'s centring. JMP\'s Neural has no Weight role, and neither has this one.'], ['Validation', 'A column of 0 (Training), 1 (Validation) and 2 (Test); one of more than three values is K folds, and the model is chosen by KFold on them. Without one, the Model Launch holds rows back.'], ['By', 'A separate analysis for each level. Go adds the model to every group.']] },
        { heading: 'The design and the network', text: 'A continuous factor enters as its value; with Informative Missing a missing value is the training mean with a 0/1 missing column. A categorical factor is effect coded (1 for the level, −1 for the last level, 0 otherwise), a missing level being the last. Every design column is centred and scaled by the training rows\' mean and standard deviation (JMP does this behind the scenes; the Estimates are on the design\'s own scale). Each hidden node is TanH, Linear or Gaussian, exp(−x²); a continuous response is a linear output of the last hidden layer, a categorical one the log odds of each level against the last.' },
        { heading: 'The fit', text: 'The negative log likelihood of the training rows: Gaussian, with the variance profiled out, (N/2)(log(SSE/N) + 1 + log 2π); Laplacian with Robust Fit, least absolute deviations; multinomial for a categorical response. Plus λ times the penalty of the hidden layers\' weights (not the intercepts, not the weights into the outputs). λ is searched from none upward, each fit starting where the one before ended, and chosen by the validation likelihood; each fit keeps its iterate with the best validation likelihood (JMP\'s early stopping).' },
        { heading: 'Random numbers', text: 'The holdback, the folds and every tour\'s normal random starting values come from the report\'s Random Seed, so a redraw, Redo, a project and the Python code give the same model.' },
        { heading: 'Differences from JMP', text: 'The penalty is searched over a fixed ladder of λ (Fitting Details), where JMP runs a line search; the Absolute penalty and Robust Fit smooth |x| as √(x² + 10⁻⁸) − 10⁻⁴ so that L-BFGS can take them; Transform Covariates fits each Johnson distribution by scipy\'s maximum likelihood, where JMP takes 10 Newton steps; rows missing a response are left out, where JMP keeps the other responses\' likelihood. Maximum Iterations and Fitting Details are ours. Save Fast Formulas, Make SAS Data Step and the Formula Depot are not here.' },
      ],
      more: MORE,
    },
    'p:neural:launch': {
      kicker: 'Neural', title: 'Model Launch',
      lead: 'The settings of the next model; Go fits it and adds it to the report, so that several networks can be fitted and compared (Model Comparison). JMP\'s defaults: Holdback 0.3333, three TanH nodes in one layer, no boosting, the Squared penalty and one tour. The settings are kept with the report for the next Go.',
      sections: [
        { heading: 'Validation Method', choices: [
          ['Method', 'How the rows are split to choose the penalty, the tour and the boosting steps. Holdback: a random share of the rows validates the model. KFold: for each penalty a model on every fold (fitted on the other folds, validated on it), the penalty with the best validation likelihood summed over the folds, and then the fold whose model fits every row best is the model shown, with that fold as its validation set (JMP\'s way). Excluded Rows Holdback: the rows excluded in the table validate and the included ones train (the model sees excluded rows only here).'],
          ['Holdback Proportion', 'With Holdback: the share of the rows held back for validation, above 0 and below 1 (JMP\'s 0.3333), drawn at random from the report\'s seed.'],
          ['Number of Folds', 'With KFold: the number of folds, from 2 to 50 (5), each row put in one of them at random from the report\'s seed.'],
          ['Validation Column', 'With a Validation column in the launch, its rows decide instead: 0 training, 1 validation, 2 test; a column of more than three values (Make Validation Column\'s K Fold) is K folds, and the model is chosen by KFold on them.'],
        ] },
        { heading: 'Hidden Layer Structure', choices: [
          ['First layer', 'Its TanH, Linear and Gaussian nodes: the nodes of each activation in the first hidden layer, the one next to the responses (JMP\'s default: 3 TanH). TanH is an S-curve from −1 to 1, Linear the sum itself (a network of Linear nodes alone is a linear model), Gaussian exp(−x²), a bump. At least one node; more can follow more complicated shapes, and noise too: compare the models on their validation rows (Model Comparison).'],
          ['Second layer', 'Its TanH, Linear and Gaussian nodes: the nodes of a second hidden layer, the one next to the X\'s: none (the default) for one layer, up to 500 of each. A boosted model has one layer, and a second is ignored, as in JMP.'],
        ] },
        { heading: 'Boosting', choices: [
          ['Number of Models', 'Above 0: base networks of the first layer\'s nodes are fitted in turn, each to the likelihood with the sum of those before (scaled by the Learning Rate) as an offset, on the log-odds scale for a categorical response, while the validation likelihood improves; the last one kept enters unscaled, as JMP describes. 0 (the default) fits one network.'],
          ['Learning Rate', 'With boosting: the scale of each base model in the sum, above 0 and at most 1 (0.1). A smaller rate needs more models, and often predicts new rows better.'],
        ] },
        { heading: 'Fitting Options', choices: [
          ['Transform Covariates', 'Makes each continuous factor near normal before the fit, as JMP does: the Johnson Su or Sb distribution (the one of the larger likelihood) fitted to the training rows, and the factor replaced by its Johnson transform. It tames skewed factors and outliers; Save Transformed Covariates saves the transforms as formula columns.'],
          ['Robust Fit', 'A continuous response is fitted by least absolute deviations (its likelihood Laplacian, |x| smoothed for the optimizer), so that outliers of the response pull the fit less. A categorical response\'s likelihood is multinomial either way.'],
          ['Penalty Method', 'Squared (the default): λ times the sum of the squared weights, for when most factors help; Absolute: the sum of their absolute values, for when a few factors matter more; Weight Decay: b²/(1 + b²) summed, another sparse choice; No Penalty. The hidden layers\' weights are penalized, not the intercepts and not the weights into the outputs. λ is chosen by the validation likelihood (Fitting Details shows the path); without validation rows it is 0.0001.'],
          ['Number of Tours', 'How many times the fit starts again from new normal random weights, from 1 to 100 (1); the tour with the best validation likelihood is kept. More tours guard against a poor start (a local optimum), and take longer.'],
          ['Maximum Iterations', 'The most L-BFGS iterations of each fit, from 1 to 100000 (200; not in JMP, whose fits stop early by the validation likelihood, as they do here). A fit that reaches it says so in the model\'s summary: raise it to see whether the validation measures change.'],
        ] },
        { heading: 'Go', choices: [
          ['Go', 'Fits a model with these settings and adds it to the report, named as JMP names it (NTanH(3), NTanH(2)NLinear(1), NTanH(3)NTanH2(2)). The report keeps every model: Remove Fit (a model\'s red triangle) takes one away.'],
          ['Random Seed', 'The report\'s seed, shown beside Go (the launch\'s Random Seed, or one drawn for the report): the holdback, the folds and every network\'s starting weights come from it, so the same settings give the same model.'],
        ] },
      ],
      more: MORE,
    },
    'p:neural:model': {
      kicker: 'Neural', title: 'A Model',
      lead: 'One fitted network, named as JMP names it: NTanH(3) is three TanH nodes, NTanH(2)NLinear(1) two TanH and one Linear node, NTanH(3)NTanH2(2) two more in a second layer, NBoost(10) ten boosted models. Its Measures of Fit per set of rows and response, and for a categorical response the confusion matrices.',
      sections: [
        { heading: 'The red triangle', choices: [['Diagram', 'The network drawn: inputs, hidden nodes with their activations, outputs.'], ['Show Estimates', 'Every weight and intercept.'], ['Profiler', 'The prediction as each factor moves.'], ['ROC Curve, Lift Curve, Decision Threshold', 'For a categorical response.'], ['Plot Actual by Predicted, Plot Residual by Predicted', 'For a continuous response, linked to the rows.'], ['Fitting Details', 'The penalty path, tours, folds and boosting steps (not in JMP).'], ['Save Columns', 'Predicteds (or probabilities and the most likely level), residuals, the hidden nodes\' values; Save Formulas (the hidden nodes and the predictions as formula columns, JMP\'s), Save Profile Formulas (the predictions alone, the hidden nodes written into them), Save Transformed Covariates (their formulas); the validation sets.'], ['Remove Fit', 'Removes the model from the report.']] },
        { heading: 'Messages', text: 'The model\'s summary says how it was validated, the penalty chosen and the iterations of its fit; when that fit reached the Maximum Iterations it says so, and a larger maximum may change the validation measures.' },
      ],
      more: MORE,
    },
    'p:neural:estimates': {
      kicker: 'Neural', title: 'Estimates',
      lead: 'Every weight and intercept of the network, with JMP\'s names: H1_2:x1 is the weight on x1 in node 2 of the first hidden layer, H1_2:Intercept its constant, y:H1_2 the weight of that node in the prediction of y. H2 is a two-layer network\'s layer next to the X\'s. A categorical response has the log odds of each level against the last, y[level]:H1_1; a categorical factor its effect-coded columns, x[level].',
      sections: [{ heading: 'Scale', text: 'The network is fitted on the design centred and scaled (as JMP fits it); the weights shown have that folded back in, so a node\'s sum works on the design as it is (T(x) after Transform Covariates). A continuous response\'s outputs are on its own scale. In the Python code, fitted_model.layers are the weights on the centred and scaled design.' }],
      more: MORE,
    },
    'p:neural:diagram': {
      kicker: 'Neural', title: 'Diagram',
      lead: 'The network as JMP draws it: the X columns on the left, the hidden layers in the middle (the second layer, when there is one, next to the X\'s), each node with its activation\'s curve, the responses on the right, a line for every connection. Hover a line for its weight, a node for its intercept. On a narrow screen the diagram scrolls inside its box.',
      more: MORE,
    },
    'p:neural:details': {
      kicker: 'Neural', title: 'Fitting Details',
      lead: 'How the model was chosen (not in JMP\'s report): each penalty λ of the path with the training and validation -LogLikelihood of its fit, the tours, the folds of KFold and the base models of boosting, the chosen ones marked.',
      sections: [{ heading: 'The penalty path', text: 'JMP starts with no penalty and searches its size by the validation likelihood, each fit starting from the last. Here λ runs up 0, 0.0001, 0.0003, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1, 3, each fit warm-started, and stops after two that do not improve the validation likelihood. Without validation rows the penalty cannot be chosen, and λ is 0.0001.' }],
      more: MORE,
    },
    'p:neural:residual': {
      kicker: 'Neural', title: 'Residual by Predicted',
      lead: 'For each set of rows, the actual value less the prediction against the prediction. Points scattered evenly about zero are what a good model leaves; a curve means a shape the network missed, a funnel a spread that grows with the level. Click or drag to select rows.',
      more: MORE,
    },
    'p:neural:compare': {
      kicker: 'Neural', title: 'Model Comparison',
      lead: 'The Measures of Fit of every model of the report, per response and set of rows, the model with the smallest validation -LogLikelihood marked. Compare models on their validation (or test) rows: the training measures improve with every node, the validation ones stop improving when the network starts to fit noise.',
      sections: [{ choices: [['A click on a line', 'Scrolls the report to that model\'s outline.'], ['Validation', 'The column that says how each model held rows back, shown when the models differ in it (Holdback, KFold, Excluded Rows): they are then judged on different rows.']] }],
      more: MORE,
    },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'neural', label: 'Neural', menu: 'Analyze/Predictive Modeling', order: 40, info: 'p:neural', topics: TOPICS,
    about: 'JMP\'s Neural platform, fitted by a network of our own as JMP documents its numerics: one or two hidden layers of TanH, Linear and Gaussian nodes, every response (continuous or categorical) in one network, JMP\'s design (effect coding, centred and scaled), the likelihood (Gaussian, Laplacian with Robust Fit, multinomial) plus a Squared, Absolute or Weight Decay penalty chosen by the validation likelihood, L-BFGS with early stopping, tours, boosting and Transform Covariates (Johnson Su or Sb). The Model Launch sets the validation (Holdback, KFold, Excluded Rows Holdback, or a Validation column, its K folds too); each Go adds a model to the report, with its Measures of Fit per set, confusion matrices, ROC and lift curves, the Decision Threshold, actual and residual by predicted, Estimates, a Diagram of the network, the Prediction Profiler, Save Columns (predicteds, hidden values, and JMP\'s Save Formulas, Save Profile Formulas and Save Transformed Covariates as live formula columns) and a comparison of the models.',
    uses: ['numpy (the network, its gradient, the design)', 'scipy.optimize.minimize (L-BFGS-B, with early stopping in its callback)', 'scipy.stats.johnsonsu, johnsonsb (Transform Covariates)'],
    launch: {
      lead: 'Choose one or more responses and the factors. The report opens with the Model Launch: set the network there and press Go.',
      roles: [
        { key: 'y', label: 'Y, Response', min: 1, hint: 'required: continuous or categorical',
          help: 'One or more responses, continuous, nominal or ordinal, all in one network whose log-likelihoods are summed, as JMP fits them. Rows missing a response are left out.' },
        { key: 'x', label: 'X, Factor', min: 1, hint: 'required',
          help: 'The factors, continuous or categorical: a categorical one enters by JMP\'s effect coding (a column per level but the last), and every design column is centred and scaled by the training rows before the fit, as JMP does behind the scenes. A column that is also a Y is left out of the factors.' },
        // the shared Validation role, told as this platform splits the rows without one (it has no Validation Portion)
        ...SM.predict.roles({ weight: false }).map((r) => (r.key === 'validation' ? { ...r, help: 'Which rows do what: 0 or Training fit the network, 1 or Validation choose the penalty, the tour and the boosting steps and measure the model, 2 or Test are only measured; a column of more than three values holds K folds, and KFold on them chooses the model. With one, the Model Launch shows it in place of its Validation Method; without one, the Model Launch holds rows back (Holdback, KFold or Excluded Rows Holdback).' } : r)),
      ],
      options: SM.predict.options().filter((o) => o.key !== 'portion'),
      validate: (spec) => {
        const ys = new Set((spec.roles && spec.roles.y) || []);
        const xs = ((spec.roles && spec.roles.x) || []).filter((id) => !ys.has(id));
        return xs.length ? null : 'X, Factor: choose a column that is not a response';
      },
    },
    title: () => 'Neural',
    triangle: (ctx) => [
      ctx.check('Model Comparison', 'comparison', null, true),
      { label: 'Remove All Fits', disabled: !modelsOf(ctx).length, action: () => ctx.set('models', []) },
    ],
    render,
  });

  /* ---- the example: a simulated reactor, with its true surface in the notes ------------------- */
  SM.io.addExample('reactor', {
    label: 'Reactor (600 rows): six settings, yield, purity, grade',
    about: 'Simulated: 600 runs of a reactor. Yield (%) = 50 + 14 exp(−((temperature − 205)/28)²) + 7 log(time/10) + 4 catalyst × pressure/10, plus 2.5 for supplier B and −3 for C, plus normal noise with SD 2: a hump in temperature, a curve in time and an interaction. Purity (%) = 99 − 0.04 (temperature − 180)₊ − 0.8 catalyst + noise (SD 0.4): it falls above 180 °C. Grade is Low, Medium or High by the yield (below 58, below 66, above) with noise. Feed rate changes nothing. For Neural (Analyze > Predictive Modeling).',
    make() {
      const r = SM.util.rng('neural-reactor');
      const n = 600;
      const c = { run: [], temperature: [], pressure: [], time: [], catalyst: [], feed: [], supplier: [], yield: [], purity: [], grade: [] };
      for (let i = 0; i < n; i++) {
        const T0 = 150 + 100 * r.u(), P = 1 + 9 * r.u(), t = 10 + 50 * r.u(), cat = 0.5 + 2.5 * r.u(), feed = r.normal(50, 10);
        const sup = r.pick(['A', 'B', 'C']);
        const y = 50 + 14 * Math.exp(-(((T0 - 205) / 28) ** 2)) + 7 * Math.log(t / 10) + 4 * cat * (P / 10) + (sup === 'B' ? 2.5 : sup === 'C' ? -3 : 0) + r.normal(0, 2);
        const pur = 99 - 0.04 * Math.max(0, T0 - 180) - 0.8 * cat + r.normal(0, 0.4);
        const gy = y + r.normal(0, 1.5);
        c.run.push(i + 1); c.temperature.push(+T0.toFixed(1)); c.pressure.push(+P.toFixed(2)); c.time.push(+t.toFixed(1)); c.catalyst.push(+cat.toFixed(2));
        c.feed.push(+feed.toFixed(1)); c.supplier.push(sup); c.yield.push(+y.toFixed(2)); c.purity.push(+pur.toFixed(2)); c.grade.push(gy < 58 ? 'Low' : gy < 66 ? 'Medium' : 'High');
      }
      return new SM.Table({ name: 'Reactor', source: 'simulated', columns: [
        { name: 'run', dataType: 'numeric', values: c.run },
        { name: 'temperature (°C)', dataType: 'numeric', values: c.temperature },
        { name: 'pressure (bar)', dataType: 'numeric', values: c.pressure },
        { name: 'time (min)', dataType: 'numeric', values: c.time },
        { name: 'catalyst (%)', dataType: 'numeric', values: c.catalyst },
        { name: 'feed rate', dataType: 'numeric', values: c.feed },
        { name: 'supplier', dataType: 'character', values: c.supplier },
        { name: 'yield (%)', dataType: 'numeric', values: c.yield },
        { name: 'purity (%)', dataType: 'numeric', values: c.purity },
        { name: 'grade', dataType: 'character', modelingType: 'ordinal', values: c.grade, valueOrder: ['Low', 'Medium', 'High'] },
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
