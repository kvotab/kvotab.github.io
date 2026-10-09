/* ==========================================================================
   SMUI.HTML: ANALYZE > PREDICTIVE MODELING > MODEL COMPARISON

   JMP Pro's Model Comparison: the predictions that models saved to the
   table, compared on the same rows. A model is a column of predicted
   values (a continuous Y), or its probability columns, Prob[level] (a
   categorical Y; the one level without a column is 1 minus the others),
   or a column of the levels it predicts. The columns cast into Y,
   Predictors are grouped into models here, by their names and by the
   report their notes say they were saved from ("from Partition for y"):

     Prob[no], Prob[yes]            from Partition for cls  -> Partition
     Prob[no] 2, Prob[yes] 2        from Decision Forest   -> Decision Forest
     Prob[yes] Discriminant         from Fit Many Models    -> Discriminant
     LR_Prob[0], LR_Prob[1]                                 -> LR

   The report:

     Predictors               each model, its columns and the report that made them
     Measures of Fit          every measure of every model in every group of the
                              Group column (the validation column), the best of
                              each marked as Fit Many Models marks it
     ROC, Lift, Cum Gains     every model on one graph per group, for one level
     AUC Comparison           DeLong's comparison of the areas under the curves
     Confusion Matrix         each model's
     Decision Threshold       two levels: SM.predict.threshold, every model
     Actual by Predicted,     every model on one graph per group
     Residual by Row
     Model Averaging          the mean of the models as one more model; Save
                              Model Average writes it as live formula columns

   The numbers are resources/py/smui/compare.py's (predictive.py's
   measures, roc, lift and confusion).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const MORE = { label: 'Model Comparison', id: 'help-p-compare' };
  const AVERAGE = 'Model Average';
  const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

  /* A colour per model, the same in every graph (compare.py's COLORS in the code); the Model Average in the text's colour. */
  const LIGHT = ['#2f6690', '#c46a12', '#3a7d44', '#b0413e', '#6c5b7b', '#1a8a78', '#8f7600', '#8c564b', '#b8428f', '#666666', '#107f8f', '#7b5bb5'];
  const DARK = ['#6fa3d6', '#f0a050', '#6fbf73', '#e87c73', '#b39ddb', '#4fd1b8', '#e0c040', '#c9a084', '#f08fc8', '#b8b8b8', '#5fd4e8', '#a58ae6'];
  const W = (w) => Math.max(240, Math.min(w, (root.innerWidth || 1200) - 110));
  const wide = (node) => el('div', { class: 'sm-mc-scroll' }, node);

  function colorsOf(models) {
    const dark = SM.util.themeColors().dark;
    const pal = dark ? DARK : LIGHT;
    const out = {};
    let i = 0;
    for (const m of models) {
      if (m.key === AVERAGE) out[m.key] = dark ? '#f2ece6' : '#352921';
      else out[m.key] = pal[i++ % pal.length];
    }
    return out;
  }

  /* A legend of every model: beside the graph, or under it on a narrow screen; the graph's size with it. */
  function legendFor(n) {
    const narrow = (root.innerWidth || 1200) < 760;
    return narrow
      ? { legend: { orientation: 'h', x: 0, y: -0.22, yanchor: 'top', font: { size: 9.5 } }, width: W(360), height: 330 + 17 * Math.ceil(n / 2), bottom: 44 }
      : { legend: { font: { size: 9.5 }, x: 1.02, y: 1, xanchor: 'left' }, width: W(480), height: 330, bottom: 42 };
  }

  /* ======================================================================
     THE MODELS: the columns of Y, Predictors grouped by name and source
     ====================================================================== */
  const isMissing = (v) => v == null || v === '' || (typeof v === 'number' && Number.isNaN(v));
  const labelOf = (c, v) => (SM.table && SM.table.labelOf ? SM.table.labelOf(c, v) : (c && c.valueLabels && !isMissing(v) && hasOwn(c.valueLabels, String(v)) ? c.valueLabels[String(v)] : null));

  /* The report a column was saved from, as its notes name it ("... from Partition for y", "saved from ..."), or ''. */
  function sourceOf(col) {
    const line = String((col && col.notes) || '').split('\n')[0].trim();
    const i = line.lastIndexOf(' from ');
    const s = i >= 0 ? line.slice(i + 6) : (line.startsWith('from ') ? line.slice(5) : '');
    return s.replace(/[.\s]+$/, '').trim();
  }

  /* The platform that made a model, from its source report's title ("Partition for y" -> "Partition"). */
  function creatorOf(source, y) {
    if (!source) return '';
    const tail = ` for ${y.name}`;
    return source.endsWith(tail) ? source.slice(0, -tail.length) : source;
  }

  /* A categorical Y's levels as the table holds them, with the texts a probability column's name may use for each. */
  function levelsOf(t, y) {
    return t.levels(y).map((v, i) => ({ i, value: v, texts: [String(v), labelOf(y, v)].filter((x, k, a) => x && a.indexOf(x) === k) }));
  }

  /* Which level a column's name is the probability of: the longest Prob[level] (this page's name, JMP's
     regression platforms') or Prob(Y==level) (JMP's Partition, Bootstrap Forest, Neural) it holds. */
  function probLevel(name, levels, y) {
    let best = null;
    for (const lv of levels) {
      for (const tx of lv.texts) {
        for (const key of [`Prob[${tx}]`, `Prob(${y.name}==${tx})`, `Prob(${y.name} == ${tx})`]) {
          const at = name.indexOf(key);
          if (at >= 0 && (!best || key.length > best.key.length)) best = { lv, key, at };
        }
      }
    }
    return best ? { level: best.lv, prefix: name.slice(0, best.at), suffix: name.slice(best.at + best.key.length) } : null;
  }

  const affixName = (prefix, suffix) => `${prefix} ${suffix}`.replace(/[\s_\-:.,;()[\]]+/g, ' ').trim();

  /* The models of the columns cast (or found): [{ key, label, creator, kind, columns: [{ name, level }] }] and errors. */
  function modelsOf(t, y, cols) {
    const models = [], errors = [];
    if (!y) return { models, errors };
    if (!y.isCategorical) {
      for (const c of cols) {
        if (!c.isNumeric || c.isCategorical) { errors.push(`${c.name}: a continuous Y takes continuous columns of predicted values`); continue; }
        models.push({ key: c.id, label: c.name, creator: creatorOf(sourceOf(c), y), kind: 'pred', columns: [{ name: c.name }] });
      }
      return { models, errors };
    }
    const levels = levelsOf(t, y);
    const groups = new Map();
    let seq = 0;
    for (const c of cols) {
      if (c.isCategorical) {   // the levels a model predicts (Most Likely y)
        models.push({ key: c.id, label: c.name, creator: creatorOf(sourceOf(c), y), kind: 'level', columns: [{ name: c.name }], order: seq++ });
        continue;
      }
      const p = probLevel(c.name, levels, y);
      if (!p) { errors.push(`${c.name}: not named as the probability of a level of ${y.name} (Prob[level]), nor a column of predicted levels`); continue; }
      const src = sourceOf(c);
      let key = `${src}\u0001${p.prefix}\u0001${p.suffix}`;
      let g = groups.get(key);
      if (g && g.columns.some((x) => x.level === p.level.i)) {   // the same level twice: a model of its own
        let k = 2;
        while (groups.has(`${key}\u0001${k}`) && groups.get(`${key}\u0001${k}`).columns.some((x) => x.level === p.level.i)) k++;
        key = `${key}\u0001${k}`;
        g = groups.get(key);
      }
      if (!g) {
        g = { key: c.id, affix: affixName(p.prefix, p.suffix), source: src, kind: 'prob', columns: [], order: seq++ };
        groups.set(key, g);
      }
      g.columns.push({ name: c.name, level: p.level.i, text: p.level.texts[0] });
    }
    for (const g of groups.values()) {
      const creator = creatorOf(g.source, y);
      const affix = /^\d*$/.test(g.affix) ? '' : g.affix;
      const label = affix || creator || g.columns.map((x) => x.name).join(', ');
      g.columns.sort((a, b) => a.level - b.level);
      models.push({ key: g.key, label, creator, kind: 'prob', columns: g.columns.map(({ name, level }) => ({ name, level })), order: g.order });
    }
    models.sort((a, b) => a.order - b.order);
    const seen = new Map();
    for (const m of models) {   // every model its own name
      const n = (seen.get(m.label) || 0) + 1;
      seen.set(m.label, n);
      if (n > 1) m.label = `${m.label} (${n})`;
      delete m.order;
    }
    return { models, errors };
  }

  /* With Y, Predictors empty, the columns of saved predictions of Y, as JMP finds its prediction formula columns. */
  function findPredictors(t, y, skip) {
    if (!y) return [];
    const esc = y.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const names = new RegExp(`(^|\\s)${esc}(\\s|$)`);
    const out = [];
    for (const c of t.columns) {
      if (c === y || skip.has(c.id)) continue;
      if (!y.isCategorical) {
        if (c.isNumeric && !c.isCategorical && /^(Predicted|Pred)\s/.test(c.name) && names.test(c.name.replace(/^(Predicted|Pred)\s/, ' '))) out.push(c);
      } else if (c.isNumeric && !c.isCategorical && probLevel(c.name, levelsOf(t, y), y)) out.push(c);
      else if (c.isCategorical && /^Most Likely\s/.test(c.name) && names.test(c.name.replace(/^Most Likely\s/, ' '))) out.push(c);
    }
    return out;
  }

  function castOrFound(t, spec) {
    const col = (k) => (spec.roles[k] || []).map((id) => t.col(id)).filter(Boolean);
    const y = col('y')[0] || null;
    const cast = col('pred');
    if (cast.length || !y) return { y, cols: cast, found: false };
    const skip = new Set([...(spec.roles.group || []), ...(spec.roles.freq || []), ...(spec.roles.by || [])]);
    return { y, cols: findPredictors(t, y, skip), found: true };
  }

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx) {
    const t = ctx.table;
    const { y, cols, found } = castOrFound(t, ctx.spec);
    if (!y) { ctx.container.append(ctx.warn('The response column is not in the table: launch the comparison again with Y, Response.')); return; }
    const G = modelsOf(t, y, cols);
    const gcol = ctx.role('group');
    const pay = {
      y: y.name, models: G.models, group: gcol ? gcol.name : null, freq: ctx.name('freq'), average: !!ctx.opt('average', false),
      alpha: ctx.alpha, plot: { level: ctx.opt('level', null) },
    };
    // the Decision Threshold's data only while it is shown (every row's probability of every model)
    if (y.isCategorical && ctx.opt('threshold', false) && typeof SM.predict.threshold === 'function') pay.threshold = true;
    if (found) ctx.container.append(ctx.note(cols.length ? `Y, Predictors was left empty: the saved predictions of ${y.name} in the table are compared (${cols.map((c) => c.name).join(', ')}).` : `Y, Predictors was left empty and the table has no saved predictions of ${y.name}.`));
    for (const e of G.errors) ctx.container.append(ctx.warn(`Left out: ${e}.`));
    if (!G.models.length) { ctx.container.append(ctx.warn(`No models to compare: cast the columns of their predictions of ${y.name} in Y, Predictors.`)); return; }
    const r = await ctx.call('compare.fit', pay);
    const S = { r, y, G, gcol, pay, colors: colorsOf(r.models), binary: r.kind === 'categorical' && r.levels.length === 2 };
    ctx.mc = S;
    if (r.notes && r.notes.length) ctx.container.append(ctx.note(r.notes.join(' ')));
    predictorsOutline(ctx, S);
    measuresOutline(ctx, S);
    if (r.kind === 'categorical') {
      if (ctx.opt('roc', false)) curveOutline(ctx, S, 'roc');
      if (ctx.opt('aucc', false)) aucOutline(ctx, S);
      if (ctx.opt('pr', false) && r.pr) curveOutline(ctx, S, 'pr');
      if (ctx.opt('lift', false)) curveOutline(ctx, S, 'lift');
      if (ctx.opt('gains', false) && hasGains(r)) curveOutline(ctx, S, 'gains');
      if (ctx.opt('confusion', false)) confusionOutline(ctx, S);
      if (S.binary && pay.threshold) thresholdOutline(ctx, S);
    } else {
      if (ctx.opt('abp', false)) pointsOutline(ctx, S, 'abp');
      if (ctx.opt('resid', false)) pointsOutline(ctx, S, 'resid');
    }
  }

  const hasGains = (r) => Object.values(r.lift || {}).some((cs) => cs.some((c) => Array.isArray(c.gains)));
  const groupName = (S, gi) => { const g = S.r.groups[gi]; return g == null ? 'All rows' : g; };
  const groupIdx = (S) => S.r.groups.map((_, i) => i);
  const modelOf = (S, key) => S.r.models.find((m) => m.key === key);

  /* ---- Predictors ---------------------------------------------------------------------------- */
  function predictorsOutline(ctx, S) {
    const { r } = S;
    const ob = ctx.outline('Predictors', { key: 'predictors', info: 'p:compare:predictors' });
    const kindText = { pred: 'predicted values', prob: 'probabilities', level: 'predicted level' };
    const rows = r.models.map((m) => ({
      model: m.label, creator: m.creator || '', kind: kindText[m.kind] || m.kind,
      columns: m.key === AVERAGE ? `the mean of ${m.of.map((k) => modelOf(S, k).label).join(', ')}` : `${m.columns.map((c) => c.name).join(', ')}${m.complement ? ` (the probability of ${m.complement}: 1 − the others)` : ''}`,
    }));
    ob.add(wide(ctx.rt({ columns: [{ key: 'model', label: 'Predictor', fmt: 'text' }, { key: 'creator', label: 'Creator', fmt: 'text' }, { key: 'kind', label: 'Gives', fmt: 'text' }, { key: 'columns', label: 'Columns', fmt: 'text' }], rows }, { key: 'predictors', sortable: false })));
    ob.add(ctx.note(`Response ${S.y.name}. The Creator is the report the columns' notes say they were saved from.`));
  }

  /* ---- Measures of Fit ----------------------------------------------------------------------- */
  function measuresOutline(ctx, S) {
    const { r } = S;
    const ob = ctx.outline(`Measures of Fit for ${S.y.name}`, { key: 'measures', info: 'p:compare:measures' });
    const grouped = !!S.gcol;
    const cols = [
      ...(grouped ? [{ key: 'group', label: S.gcol.name, fmt: 'text' }] : []),
      { key: 'label', label: 'Predictor', fmt: 'text' }, { key: 'creator', label: 'Creator', fmt: 'text' },
      ...r.measure_columns.map((c) => ({ ...c })),
    ];
    const gidx = new Map(r.groups.map((g, i) => [String(g), i]));
    const rows = r.measures.map((m) => ({ ...m, group: m.group == null ? '' : m.group, _g: m.group == null ? 0 : gidx.get(String(m.group)) }));
    ob.add(wide(ctx.rt({ columns: cols, rows }, { key: 'measures', cellClass: (row, c) => (((r.best[String(row._g)] || {})[c.key] || []).includes(row.model) ? 'sm-mc-best' : '') })));
    const parts = [];
    if (grouped) parts.push(`${r.groups.map((g, i) => `${g} ${fmt(r.n[String(i)])}`).join(', ')} rows, each group measured on its own.`);
    else parts.push(`${fmt(r.n_rows)} rows. Cast the validation column as Group to measure the models on the rows they did not learn from.`);
    parts.push('Bold marks the best value of each measure within its group; right click the table, Columns, for more measures.');
    ob.add(ctx.note(parts.join(' ')), ctx.code(r.code));
  }

  /* ---- ROC, Lift and Cum Gains curves: every model, one graph per group ----------------------- */
  function levelIndex(ctx, S) {
    const n = S.r.levels.length;
    const v = ctx.opt('level', null);
    return Number.isInteger(v) && v >= 0 && v < n ? v : (n === 2 ? 1 : 0);
  }

  const levelItems = (ctx, S) => ({ label: 'Level', submenu: () => S.r.levels.map((l, i) => ({ label: l, checked: i === levelIndex(ctx, S), action: () => ctx.set('level', i) })) });

  function curveOutline(ctx, S, kind) {
    const { r } = S;
    const lv = levelIndex(ctx, S);
    const level = r.levels[lv];
    const title = { roc: 'ROC Curve', lift: 'Lift Curve', gains: 'Cum Gains Curve', pr: 'Precision Recall Curve' }[kind];
    const ob = ctx.outline(title, { key: kind, info: 'p:compare:curves', menu: () => [levelItems(ctx, S), { label: 'Remove', action: () => ctx.set(kind, false) }] });
    const muted = SM.util.themeColors().muted;
    const probs = r.models.filter((m) => m.kind === 'prob');
    const lg = legendFor(probs.length);
    const src = kind === 'roc' ? r.roc : kind === 'pr' ? r.pr : r.lift;
    const plots = groupIdx(S).map((gi) => {
      const g = r.groups[gi];
      const traces = [];
      let base = null;
      for (const m of probs) {
        const c = (src[m.key] || []).find((x) => x.set === g && x.level === level);
        if (!c) continue;
        if (kind === 'pr') base = c.base;
        const name = kind === 'roc' ? `${T(m.label)} (${c.auc == null ? '.' : c.auc.toFixed(3)})` : kind === 'pr' ? `${T(m.label)} (AP ${c.ap.toFixed(3)})` : T(m.label);
        const xs = kind === 'roc' ? c.fpr : kind === 'pr' ? c.recall : c.portion;
        const ys = kind === 'roc' ? c.tpr : kind === 'pr' ? c.precision : kind === 'lift' ? c.lift : c.gains;
        traces.push({ type: 'scatter', mode: 'lines', x: xs, y: ys, name, line: { color: S.colors[m.key], width: m.key === AVERAGE ? 2.2 : 1.6, dash: m.key === AVERAGE ? 'dash' : 'solid' },
          hovertemplate: `${T(m.label)}<br>%{x:.3f}, %{y:.3f}<extra></extra>` });
      }
      if (kind !== 'pr') traces.push({ type: 'scatter', mode: 'lines', x: [0, 1], y: kind === 'lift' ? [1, 1] : [0, 1], line: { color: muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false });
      const gl = g == null ? '' : `${g} `;
      const axes = kind === 'roc' ? [{ title: { text: '1 - Specificity' }, range: [0, 1] }, { title: { text: 'Sensitivity' }, range: [0, 1.01] }]
        : kind === 'pr' ? [{ title: { text: 'Recall' }, range: [0, 1] }, { title: { text: 'Precision' }, range: [0, 1.01] }]
          : kind === 'lift' ? [{ title: { text: 'Portion' }, range: [0, 1] }, { title: { text: 'Lift' } }] : [{ title: { text: 'Portion' }, range: [0, 1] }, { title: { text: 'Gains' }, range: [0, 1.01] }];
      const pre = { roc: 'ROC', lift: 'Lift', gains: 'Cum Gains', pr: 'Precision Recall' }[kind];
      // Precision Recall: the level's rate in the group, the precision of a model that knows nothing
      const shapes = kind === 'pr' && base != null ? [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: base, y1: base, line: { color: muted, width: 1, dash: 'dot' } }] : [];
      return SM.predict.plotWithCode(ctx, traces, {
        showlegend: true, legend: lg.legend, title: { text: g == null ? level : `${g}: ${level}`, font: { size: 12 } }, margin: { l: 50, r: 8, t: 28, b: lg.bottom },
        xaxis: axes[0], yaxis: axes[1], shapes,
      }, { width: lg.width, height: lg.height, title: `${pre} ${gl}${level}`, select: false }, (r.plots || {}).head_code, ((r.plots || {})[kind] || {})[String(gi)]);
    });
    ob.add(ctx.row(...plots));
    if (kind === 'roc') {
      const cols = [{ key: 'model', label: 'Predictor', fmt: 'text' }, ...groupIdx(S).map((gi) => ({ key: `g${gi}`, label: `${r.groups[gi] == null ? '' : `${r.groups[gi]} `}AUC`, digits: 4 }))];
      const rows = probs.map((m) => ({ model: m.label, ...Object.fromEntries(groupIdx(S).map((gi) => { const c = (r.roc[m.key] || []).find((x) => x.set === r.groups[gi] && x.level === level); return [`g${gi}`, c ? c.auc : null]; })) }));
      ob.add(wide(ctx.rt({ columns: cols, rows }, { key: `auc:${level}` })));
    }
    const what = { roc: `the share of ${level} rows caught against the share of the others caught as the cut on the probability of ${level} falls; the AUC in the legend`,
      lift: `the rows taken highest probability of ${level} first: how many times more common ${level} is among them than in the group`,
      gains: `the rows taken highest probability of ${level} first: the share of all the ${level} rows they hold (the diagonal: rows taken at random)`,
      pr: `as the cut on the probability of ${level} falls, the share of the ${level} rows caught (recall) against the share of the rows called ${level} that are (precision); AP, the average precision, in the legend; the dotted line is ${level}'s rate, a model that knows nothing` }[kind];
    ob.add(ctx.note(`${level} against the other level${r.levels.length > 2 ? 's' : ''}, every model on one graph per group: ${what}. Level (red triangle) picks another level.`));
  }

  /* ---- AUC Comparison (DeLong, DeLong and Clarke-Pearson 1988) ------------------------------------ */
  function aucOutline(ctx, S) {
    const { r } = S;
    const lv = levelIndex(ctx, S);
    const level = r.levels[lv];
    const ob = ctx.outline('AUC Comparison', { key: 'aucc', info: 'p:compare:auc', menu: () => [levelItems(ctx, S), { label: 'Remove', action: () => ctx.set('aucc', false) }] });
    const pct = `${fmt(100 * (1 - r.alpha))}%`;
    for (const a of r.auc || []) {
      const res = a.levels[lv];
      const gl = a.group == null ? '' : `${a.group}: `;
      if (!res) { ob.add(ctx.note(`${gl}the rows lack ${level} or the other levels: no AUC.`)); continue; }
      const each = ctx.rt({ columns: [{ key: 'model', label: 'Predictor', fmt: 'text' }, { key: 'auc', label: 'AUC', digits: 4 }, { key: 'se', label: 'Std Error', digits: 4 }, { key: 'lower', label: `Lower ${pct}`, digits: 4 }, { key: 'upper', label: `Upper ${pct}`, digits: 4 }], rows: res.each },
        { key: `aucc-each:${a.group}`, caption: `${gl}AUC of ${level}`, sortable: false });
      const parts = [each];
      if (res.pairs.length) {
        parts.push(ctx.rt({ columns: [{ key: 'model1', label: 'Predictor', fmt: 'text' }, { key: 'model2', label: '- Predictor', fmt: 'text' }, { key: 'diff', label: 'AUC Difference', digits: 4 }, { key: 'se', label: 'Std Error', digits: 4 },
          { key: 'lower', label: `Lower ${pct}`, digits: 4 }, { key: 'upper', label: `Upper ${pct}`, digits: 4 }, { key: 'chisq', label: 'ChiSquare', digits: 4 }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: res.pairs },
        { key: `aucc-pairs:${a.group}`, caption: `${gl}each pair`, sortable: false }));
      }
      if (res.overall) parts.push(ctx.kv([['Test that the AUCs are equal', ''], ['ChiSquare', res.overall.chisq], ['DF', res.overall.df, 'int'], ['Prob>ChiSq', res.overall.p, 'p']]));
      ob.add(el('div', { class: 'sm-mc-auc' }, ...parts.map(wide)));
    }
    ob.add(ctx.note(`The area under each model's ROC curve of ${level}, its standard error by DeLong, DeLong and Clarke-Pearson's (1988) method, and a ${pct} interval; for each pair the difference, whose standard error takes into account that the models are measured on the same rows, and its chi-square test; and the test that every AUC is equal (a chi-square on the differences of each AUC with the next). Level (red triangle) picks another level.`),
      ctx.code(r.auc_code && r.auc_code[String(lv)]));
  }

  /* ---- Confusion Matrix: each model's -------------------------------------------------------- */
  function confusionOutline(ctx, S) {
    const { r } = S;
    const ob = ctx.outline('Confusion Matrix', { key: 'confusion', info: 'p:compare:confusion', menu: () => [{ label: 'Remove', action: () => ctx.set('confusion', false) }] });
    r.models.forEach((m, i) => {
      const cms = (r.confusion[m.key] || []).map((c) => ({ ...c, set: c.set == null ? 'All rows' : c.set }));
      if (!cms.length) return;
      const sub = SM.predict.confusion(ctx, ob, { confusion: cms }, `mc${i}:`);
      if (sub && sub.setTitle) sub.setTitle(m.label);
    });
  }

  /* ---- Decision Threshold: SM.predict.threshold, every model with probabilities ------------------- */
  function thresholdOutline(ctx, S) {
    const { r, y } = S;
    if (!r.threshold) {
      const ob = ctx.outline('Decision Threshold', { key: 'threshold', info: 'p:predict:threshold', menu: () => [{ label: 'Remove', action: () => ctx.set('threshold', false) }] });
      ob.add(ctx.warn(`Not shown: ${r.threshold_note || 'it needs a response with two levels and a model with probabilities'}.`));
      return;
    }
    const levels = levelsOf(ctx.table, y);
    // Save Threshold Formula reads the model's column of the target level's probability
    const probName = (label, m) => {
      const lv = levels.find((l) => l.texts.includes(String(label)));
      const mm = m && S.G.models.find((x) => x.key === m.key);
      const c = mm && lv && mm.columns.find((x) => x.level === lv.i);
      if (c) return c.name;
      return m && m.key === AVERAGE && lv ? `Prob[${lv.texts[0]}] ${AVERAGE}` : `Prob[${label}]`;
    };
    SM.predict.threshold(ctx, null, r.threshold, { yCol: y, probName, prefix: 'mc:', title: 'Decision Threshold' });
    if (r.threshold_note) ctx.container.append(ctx.note(r.threshold_note));
  }

  /* ---- Actual by Predicted and Residual by Row: every model, one graph per group ------------------ */
  function pointsOutline(ctx, S, kind) {
    const { r } = S;
    const res = r.residuals;
    const abp = kind === 'abp';
    const ob = ctx.outline(abp ? 'Actual by Predicted Plot' : 'Residual by Row Plot', { key: kind, info: 'p:compare:points', menu: () => [{ label: 'Remove', action: () => ctx.set(kind, false) }] });
    const muted = SM.util.themeColors().muted;
    const lg = legendFor(r.models.length);
    const n = res.rows.length;
    const type = n * r.models.length > 3000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter';
    const plots = groupIdx(S).map((gi) => {
      const g = r.groups[gi];
      const idx = res.group.map((s, i) => (s === gi ? i : -1)).filter((i) => i >= 0);
      const rowsOf = idx.map((i) => res.rows[i]);
      const traces = [];
      let lo = Infinity, hi = -Infinity;
      for (const m of r.models) {
        const pred = res.predicted[m.key];
        const xs = abp ? idx.map((i) => pred[i]) : idx.map((i) => res.rows[i] + 1);
        const ys = abp ? idx.map((i) => res.actual[i]) : idx.map((i) => res.actual[i] - pred[i]);
        if (abp) for (const v of [...xs, ...ys]) if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
        traces.push({ type, mode: 'markers', x: xs, y: ys, rows: rowsOf, name: T(m.label), marker: { size: n > 1500 ? 3.5 : 5, color: S.colors[m.key], opacity: 0.8 },
          hovertemplate: `${T(m.label)}<br>row %{customdata}: (%{x:.4g}, %{y:.4g})<extra></extra>`, customdata: rowsOf.map((x) => x + 1) });
      }
      if (abp) traces.push({ type: 'scatter', mode: 'lines', x: [lo, hi], y: [lo, hi], line: { color: muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false });
      const gl = g == null ? '' : ` ${g}`;
      return SM.predict.plotWithCode(ctx, traces, {
        showlegend: true, legend: lg.legend, title: { text: g == null ? '' : g, font: { size: 12 } }, margin: { l: 56, r: 8, t: 28, b: lg.bottom },
        xaxis: { title: { text: abp ? 'Predicted' : 'Row' } }, yaxis: { title: { text: abp ? S.y.name : 'Residual' }, zeroline: !abp },
        shapes: abp ? [] : [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: muted, width: 1, dash: 'dot' } }],
      }, { width: lg.width, height: lg.height, title: `${abp ? 'Actual by predicted' : 'Residual by row'}${gl}`, rowColors: false }, (r.plots || {}).head_code, ((r.plots || {})[kind] || {})[String(gi)]);
    });
    ob.add(ctx.row(...plots), ctx.note(abp
      ? `The actual ${S.y.name} against each model's prediction, every model on one graph per group; points on the dotted line are predicted exactly. Drag over points to select their rows.`
      : `Each model's residual (the actual ${S.y.name} less its prediction) against the row number, every model on one graph per group: a pattern along the rows (a trend, a jump) shows what a model misses. Drag over points to select their rows.`));
  }

  /* ======================================================================
     MODEL AVERAGING: save the mean of the models as live formula columns
     ====================================================================== */
  function saveAverage(ctx, S) {
    const { y, r } = S;
    const kept = new Set(r.models.map((m) => m.key));
    const G = { models: S.G.models.filter((m) => kept.has(m.key)) };
    const ref = SM.formula.refText;
    const title = ctx.report.title;
    try {
      if (r.kind === 'continuous') {
        const ms = G.models.filter((m) => m.kind === 'pred');
        if (ms.length < 2) { SM.ui.toast('Model Averaging needs two models', { error: true }); return; }
        const expr = `Mean(${ms.map((m) => ref(m.columns[0].name)).join(', ')})`;
        ctx.saveFormula(`Predicted ${y.name} ${AVERAGE}`, expr, { notes: `the mean of the predictions of ${ms.map((m) => m.label).join(', ')} (Model Averaging), from ${title}` });
        return;
      }
      const ms = G.models.filter((m) => m.kind === 'prob');
      if (ms.length < 2) { SM.ui.toast('Model Averaging needs two models with probabilities', { error: true }); return; }
      const levels = levelsOf(ctx.table, y);
      const used = levels.filter((lv) => ms.some((m) => m.columns.some((c) => c.level === lv.i)) || y.values.some((v) => v === lv.value));
      const probOf = (m, lv) => {   // a model's probability of a level: its column, or 1 minus its others
        const c = m.columns.find((x) => x.level === lv.i);
        if (c) return ref(c.name);
        const others = m.columns.filter((x) => used.some((u) => u.i === x.level)).map((x) => ref(x.name));
        return `Max(0, Min(1, 1 - (${others.join(' + ')})))`;
      };
      const made = [];
      for (const lv of used) {
        const c = ctx.saveFormula(`Prob[${lv.texts[0]}] ${AVERAGE}`, `Mean(${ms.map((m) => probOf(m, lv)).join(', ')})`,
          { notes: `the mean probability of ${lv.texts[0]} of ${ms.map((m) => m.label).join(', ')} (Model Averaging), from ${title}` });
        made.push({ lv, c });
      }
      // the most likely level: the first of the largest probabilities, as the measures take it
      const lit = (v) => (typeof v === 'number' ? String(v) : `"${String(v).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`);
      const parts = [];
      for (let i = 0; i < made.length - 1; i++) {
        const me = ref(made[i].c.name);
        parts.push(made.slice(i + 1).map((o) => `${me} >= ${ref(o.c.name)}`).join(' & '), lit(made[i].lv.value));
      }
      parts.push(lit(made[made.length - 1].lv.value));
      ctx.saveFormula(`Most Likely ${y.name} ${AVERAGE}`, `If(${parts.join(', ')})`,
        { notes: `the level of the largest mean probability (Model Averaging), from ${title}`, modelingType: y.modelingType === 'ordinal' ? 'ordinal' : 'nominal', valueOrder: used.map((u) => u.value) });
    } catch (e) { SM.ui.toast(`Save Model Average: ${e.message || e}`, { error: true }); }
  }

  /* ======================================================================
     THE TOP RED TRIANGLE
     ====================================================================== */
  function topMenu(ctx) {
    const S = ctx.mc;
    if (!S) return [];
    const { r } = S;
    const n = r.models.filter((m) => m.key !== AVERAGE && m.kind !== 'level').length;
    const items = [ctx.check('Model Averaging', 'average', null, false), { label: 'Save Model Average', disabled: n < 2, action: () => saveAverage(ctx, S) }, { separator: true }];
    if (r.kind === 'continuous') items.push(ctx.check('Plot Actual by Predicted', 'abp', null, false), ctx.check('Plot Residual by Row', 'resid', null, false));
    else {
      items.push(ctx.check('ROC Curve', 'roc', null, false), ctx.check('AUC Comparison', 'aucc', null, false), ctx.check('Precision Recall Curve', 'pr', null, false), ctx.check('Lift Curve', 'lift', null, false));
      if (hasGains(r)) items.push(ctx.check('Cum Gains Curve', 'gains', null, false));
      items.push(ctx.check('Confusion Matrix', 'confusion', null, false));
      if (S.binary && typeof SM.predict.threshold === 'function') items.push(SM.predict.thresholdItem ? SM.predict.thresholdItem(ctx, null) : ctx.check('Decision Threshold', 'threshold', null, false));
      items.push(levelItems(ctx, S));
    }
    return items;
  }

  /* ======================================================================
     THE LAUNCH DIALOG'S OWN PART: the models the columns make
     ====================================================================== */
  function launchExtra(api) {
    const box = el('div', { class: 'sm-mc-launch' }, el('h4', { text: 'Models' }));
    const list = el('ul', { class: 'sm-mc-models' });
    const hint = el('p', { class: 'sm-mc-hint' });
    box.append(list, hint);
    const update = (state) => {
      const spec = { roles: state || {} };
      const t = api.table;
      const { y, cols, found } = castOrFound(t, spec);
      list.replaceChildren();
      if (!y) { hint.textContent = 'Cast the response in Y, Response and the models\' saved predictions in Y, Predictors.'; return; }
      const G = modelsOf(t, y, cols);
      for (const m of G.models) list.append(el('li', null, el('b', { text: m.label }), el('span', { text: ` ${m.columns.map((c) => c.name).join(', ')}` })));
      // as JMP offers the validation column when Group is empty
      const vcol = !(spec.roles.group || []).length ? t.columns.find((c) => c !== y && /^valid/i.test(c.name)) : null;
      hint.textContent = [
        found ? (cols.length ? `Y, Predictors is empty: the saved predictions of ${y.name} found in the table.` : `Y, Predictors is empty and the table has no saved predictions of ${y.name} (Predicted ${y.name}, Prob[level]).`) : '',
        G.errors.length ? `Left out: ${G.errors.join('; ')}.` : '',
        y.isCategorical ? 'A model\'s probability columns go together by their names and the report they were saved from.' : '',
        vcol ? `Cast ${vcol.name} as Group to measure the models on the rows they did not learn from.` : '',
      ].filter(Boolean).join(' ');
    };
    api.onRolesChange(update);
    update(api.state);
    return { el: box, read: () => ({}), recall: () => update(api.state) };
  }

  function validate(spec, table) {
    const { y, cols } = castOrFound(table, spec);
    if (!y) return 'Y, Response: choose the response the models predict';
    if (!cols.length) return `Y, Predictors: none cast, and no saved predictions of ${y.name} were found (columns named Predicted ${y.name}, or Prob[level] for a categorical Y)`;
    const G = modelsOf(table, y, cols);
    if (!G.models.length) return G.errors[0] || 'Y, Predictors: no models';
    return null;
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:compare': {
      kicker: 'Analyze > Predictive Modeling', title: 'Model Comparison',
      lead: 'Compares models by the predictions they saved to the table, whichever platform made them, on the same rows: the Measures of Fit of every model in every group of the Group column (the validation column), the best of each marked, and ROC, lift and gains curves, the AUC comparison, confusion matrices and actual by predicted of every model together, as JMP Pro\'s Model Comparison does.',
      sections: [
        { heading: 'Roles', choices: [
          ['Y, Response', 'The response the models predict: continuous, or nominal or ordinal.'],
          ['Y, Predictors', 'The models\' saved predictions: a column of predicted values each (a continuous Y); for a categorical Y each model\'s probability columns, Prob[level] (one level may be left out: it is 1 minus the others), or its column of predicted levels (Most Likely). Empty: the saved predictions of Y in the table.'],
          ['Group', 'The validation column: each of its groups (Training, Validation, Test) is measured on its own. Any column works.'],
          ['Freq', 'How many observations each row stands for.'], ['By', 'A comparison for each level.']] },
        { heading: 'Which columns make a model', text: 'Probability columns go together when their names differ only in the level (Prob[no], Prob[yes]; LR_Prob[0], LR_Prob[1]; Prob[yes] Discriminant) and their notes name the same report ("from Partition for y"), as every Save of this page writes them. A model is named by what its names add (LR, Discriminant), else by the report it came from.' },
        { heading: 'The rows', text: 'Every model is measured on the same rows: those with the response, the group, the frequency and every model\'s prediction. Excluded rows are left out, as in every report; the rows a model did not learn from are the ones that say how well it predicts.' },
        { heading: 'Differences from JMP', text: 'JMP finds the response from a Predicting column property; here it is cast as Y, Response. The ROC, lift and gains graphs show one level at a time (Level, red triangle), where JMP shows every level. The measures beyond JMP\'s (MSE, MAPE, the correlation of actual and predicted, and the hidden Mean Error, MPE, Median Abs Error) are Klimberg\'s and Shmueli et al.\'s. The Profiler and Formula Depot models are not here.' },
      ],
      more: MORE,
    },
    'p:compare:predictors': { kicker: 'Model Comparison', title: 'Predictors', lead: 'Each model compared: its name, the report its columns were saved from (Creator), what it gives (predicted values, probabilities or a predicted level) and its columns. A probability the model has no column for is 1 minus its others.', more: MORE },
    'p:compare:measures': {
      kicker: 'Model Comparison', title: 'Measures of Fit',
      lead: 'Every measure of every model in every group, each group measured on its own; bold marks the best value of each measure in its group (the largest RSquare, AUC and correlation, the smallest error). Compare the models on the validation or test rows: training rows flatter the flexible ones.',
      sections: [
        { heading: 'Continuous response', choices: [['RSquare', '1 − SSE/SST, SST about the group\'s own mean: below 0 when the model predicts worse than that mean'], ['RASE', 'the root average squared error, √(SSE/N)'], ['AAE', 'the average absolute error'], ['MSE', 'the mean squared error, RASE squared'], ['MAPE', 'the mean absolute percentage error, 100 |actual − predicted| / |actual|, over the rows whose actual value is not 0'], ['Correlation', 'of the actual and the predicted values'], ['Freq', 'the rows, counted by their frequencies'], ['Hidden (Columns)', 'Mean Error (a bias), MPE, Median Abs Error, -LogLikelihood, SSE']] },
        { heading: 'Categorical response', choices: [['Entropy RSquare', '1 − LL/LL0: the log-likelihood against that of the group\'s own shares of the levels'], ['Generalized RSquare', 'Nagelkerke\'s version, which reaches 1'], ['Mean -Log p', 'the average of −log of the probability of the actual level'], ['RASE, Mean Abs Dev', 'of 1 − the probability of the actual level'], ['Misclassification Rate', 'the share of rows whose most likely level is not the actual one: the only measure of a model that gives a predicted level'], ['AUC', 'two levels: the area under the ROC curve of the second level'], ['N', 'the rows, counted by their frequencies']] },
      ],
      more: MORE,
    },
    'p:compare:curves': { kicker: 'Model Comparison', title: 'ROC, Precision Recall, Lift and Cum Gains Curves', lead: 'Every model\'s curve for one level on one graph per group. ROC: the share of the level\'s rows caught against the share of the others as the cut on its probability falls (the AUC in the legend and the table). Precision Recall: the share of the level\'s rows caught (recall) against the share of the rows called the level that are (precision), from recall 0 at precision 1 as scikit-learn draws it; the average precision (AP) in the legend; for a rare level it says more than the ROC curve. Lift: how many times more common the level is among the rows the model scores highest. Cum Gains: the share of all the level\'s rows among those. Level (red triangle) picks the level; the Model Average is dashed.', more: MORE },
    'p:compare:auc': {
      kicker: 'Model Comparison', title: 'AUC Comparison',
      lead: 'Whether the models\' areas under the ROC curve differ by more than chance. The standard errors are DeLong, DeLong and Clarke-Pearson\'s (1988): each positive row\'s share of negative rows it outscores, and each negative row\'s share of positive rows that outscore it, give the variances and, because every model is measured on the same rows, the covariances of the AUCs.',
      sections: [{ choices: [['AUC, Std Error, Lower, Upper', 'each model\'s area, its standard error and an interval at the report\'s α (Set α Level)'], ['AUC Difference', 'the first model\'s AUC less the second\'s, with its standard error, interval and chi-square test (the difference over its standard error, squared)'], ['Test that the AUCs are equal', 'the chi-square of the differences of each AUC with the next, on as many degrees of freedom as they are independent']] }],
      more: MORE,
    },
    'p:compare:confusion': { kicker: 'Model Comparison', title: 'Confusion Matrix', lead: 'For each model and group, the rows counted by their actual level (rows) and the level the model predicts: the most likely one, or the column of predicted levels; the rates divide each row by its total.', more: MORE },
    'p:compare:points': { kicker: 'Model Comparison', title: 'Actual by Predicted and Residual by Row', lead: 'Every model\'s predictions of a continuous response on one graph per group, each in its own colour (the Model Average in the text\'s): the actual value against the prediction, or the residual against the row number. The points are the rows: drag over them to select the rows.', more: MORE },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'compare', label: 'Model Comparison', menu: 'Analyze/Predictive Modeling', order: 80, info: 'p:compare', topics: TOPICS,
    about: 'The predictions that models saved to the table (predicted values, or each model\'s probability columns grouped by their names and the reports they came from, or its predicted levels) compared on the same rows: the Measures of Fit of every model in every group of the validation column with the best of each marked (RSquare, RASE, AAE, MSE, MAPE and the correlation; Entropy and Generalized RSquare, Mean -Log p, RASE, Mean Abs Dev, the misclassification rate and the AUC), ROC, precision-recall, lift and cumulative gains curves of every model overlaid, DeLong\'s AUC Comparison, confusion matrices, the Decision Threshold of two levels, actual by predicted and residual by row, and Model Averaging, whose mean of the models is one more model and can be saved as formula columns.',
    uses: ['numpy', 'scipy.stats (chi2, norm)', 'the predictive platforms\' measures (predictive.py)'],
    launch: {
      lead: 'Choose the response and the columns of the models\' saved predictions; cast the validation column as Group to compare the models on the rows they did not learn from.',
      roles: [
        { key: 'y', label: 'Y, Response', min: 1, max: 1, hint: 'required: the response the models predict',
          help: 'The actual response the models predict: continuous, or nominal or ordinal for a classification. Its modeling type says which predictions the models give and which measures they get.' },
        { key: 'pred', label: 'Y, Predictors', hint: 'optional: empty finds the saved predictions of Y',
          help: 'The models\' saved predictions. A continuous Y: a column of predicted values per model (Save Predicteds, Save Prediction Formula). A categorical Y: each model\'s probability columns, Prob[level], which go together by their names and the report they were saved from (one level may be left out), or a column of the levels a model predicts. Empty: the columns named Predicted Y, Prob[level] or Most Likely Y in the table.' },
        { key: 'group', label: 'Group', max: 1, hint: 'optional: the validation column',
          help: 'A column whose groups are measured each on its own: the Validation column (Training, Validation, Test) to see how the models do on the rows they did not learn from. Rows with no value are left out. Without it every row is in one group.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, hint: 'optional: row counts',
          help: 'How many observations each row stands for, in every measure, curve and confusion matrix. Rows with a missing, zero or negative count are left out.' },
        { key: 'by', label: 'By', hint: 'optional', help: 'A separate comparison for each level of the By column. Rows with a missing By value are left out.' },
      ],
      options: [],
      extra: launchExtra,
      validate,
    },
    title: (spec, table) => {
      const c = table && (spec.roles.y || [])[0] ? table.col(spec.roles.y[0]) : null;
      return c ? `Model Comparison for ${c.name}` : 'Model Comparison';
    },
    triangle: topMenu,
    render,
  });

  SM.compare = Object.freeze({ modelsOf, findPredictors, sourceOf, creatorOf });
}(typeof self !== 'undefined' ? self : this));
