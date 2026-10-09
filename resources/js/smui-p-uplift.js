/* ==========================================================================
   SMUI.HTML: ANALYZE > CONSUMER RESEARCH > UPLIFT

   JMP Pro's Uplift platform: a decision tree that finds where a treatment
   (an offer, a mailing, a message) changes the response most. It grows as
   Partition's tree grows (Split, Prune, Go, a node's own splits: the same
   steps, replayed from the root by resources/py/smui/uplift.py), each split
   the column and cut whose split x treatment interaction is the most
   significant. The report, in JMP's layout:

     the model graph      each leaf's training rows, the treatment's and the
                          control's, each group's mean (or rate) as a line
     Split, Prune, Go     as Partition's; Go keeps the tree with the best
                          validation RSquare
     the summary          RSquare, RMSE, N, Number of Splits, AICc
     the tree             node boxes: each group's mean (rate) and count,
                          the t Ratio, Trt Diff (the uplift), the LogWorth
     Candidates           each column's best split of a node: F Ratio (or
                          ChiSquare), LogWorth, Gamma, the condition
     from the red triangle Leaf Report, Uplift Graph, Split History, Column
                          Uplift Contributions, the Qini curve (not in JMP),
                          Decision Threshold, Save Columns (the Difference
                          and prediction formulas, leaf numbers and labels)

   The tree's drawing, its steps and node menus are Partition's
   (SM.partition, smui-p-partition.js); the boxes are this platform's.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, svg, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const PT = () => SM.partition;
  const MORE = { label: 'Uplift', id: 'help-p-uplift' };
  const SETS = ['Training', 'Validation', 'Test'];
  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));
  const sig = (v, n = 6) => fmt(v, { sig: n });

  /* What each field of the launch dialog and the forms is for: the (i). */
  const HELP = {
    y: 'The response whose change the treatment brings about. Continuous: the uplift of a leaf is the treatment rows\' mean less the control rows\'. Nominal or ordinal: the rate of its first level (in its value order; Response Level in the red triangle picks another), the other levels together as not it; the uplift is the difference of the two groups\' rates.',
    treatment: 'Which rows had the treatment: a nominal or ordinal column. Its first level (in the value order: Column Info sets it) is the treatment and every other level the control, as JMP takes them; Treatment Level in the red triangle picks another level. The training rows need both groups, and every side of a split needs rows of both.',
    x: 'The columns a split may use, of any modeling type: a continuous column cut at a value, an ordinal one between neighbouring levels, a nominal one into two groups of its levels. A split is the column and cut whose split x treatment interaction is the most significant, so a column that changes the response but not the treatment\'s effect is not used.',
    minsize: 'The fewest rows a split may leave on either side, counted by Freq. Empty: JMP\'s default, 25 or the training rows over 2000, whichever is more. Below 1 it is a share of the training rows. Each side also needs rows of the treatment and of the control, so that its uplift can be worked out.',
    ordinalOrder: 'On (the default, as in JMP): an ordinal X is cut between neighbouring levels. Off: its levels are grouped freely, as a nominal X\'s are.',
    missing: 'On (JMP\'s default): rows missing a factor are kept: a missing value of a continuous X goes to the side of each split where it fits better, and a missing level of a categorical X is a level of its own. Off: rows missing any factor are left out. Rows with no treatment are always left out.',
    splits: 'How many splits to make in one step, from 1 to 500, each the best one at that point: the same as pressing Split that many times.',
  };

  /* ---- the steps (per By group) and the payload --------------------------------------------------------- */
  const scopeOf = (ctx) => (ctx.byLabel ? `by:${ctx.byLabel}` : null);
  const stepsOf = (ctx) => ctx.opt('steps', [], scopeOf(ctx)) || [];

  function payloadOf(ctx) {
    // a step names its column by id (so a project remaps it); the backend takes names
    const steps = stepsOf(ctx).map((s) => (s.col ? { ...s, col: (ctx.col(s.col) || { name: s.col }).name } : s));
    const ms = Number(ctx.opt('minsize', null));
    const tr = ctx.role('treatment');
    return { y: ctx.name('y'), treatment: tr ? tr.name : null, x: ctx.names('x'), ...SM.predict.payload(ctx), minsize: ms > 0 ? ms : null,
      ordinal_order: ctx.opt('ordinalOrder', true) !== false, steps, treat_level: ctx.opt('treatLevel', null), response_level: ctx.opt('responseLevel', null), group: ctx.byLabel || null };
  }

  /* ---- the render's state: rows by leaf and group -------------------------------------------------------- */
  function state(ctx, res, base) {
    const a = res.assign;
    const nl = res.leaves.length;
    const S = { ctx, res, base, cat: false, cart: false, binary: res.binary, by: new Map(res.nodes.map((nd) => [nd.path, nd])), plots: res.plots || {}, look: LOOK };
    S.leafAll = Array.from({ length: nl }, () => []);
    S.leafTrain = Array.from({ length: nl }, () => []);
    S.leafIdx = Array.from({ length: nl }, () => []);
    for (let i = 0; i < a.rows.length; i++) {
      S.leafAll[a.leaf[i]].push(a.rows[i]);
      if (a.set[i] === 0) { S.leafTrain[a.leaf[i]].push(a.rows[i]); S.leafIdx[a.leaf[i]].push(i); }
    }
    S.rowsOf = (nd, train = false) => { const out = []; for (let l = nd.lo; l <= nd.hi; l++) out.push(...(train ? S.leafTrain[l] : S.leafAll[l])); return out; };
    const picked = ctx.opt('candNode', null, scopeOf(ctx));
    S.cand = picked != null && S.by.has(picked) ? picked : nextLeaf(res);
    S.groupNames = [res.treat, res.control_label];   // the treatment, the control
    return S;
  }

  function nextLeaf(res) {
    let best = null;
    for (const nd of res.nodes) {
      if (!nd.leaf) continue;
      const c = (nd.cands || []).find((x) => x.best);
      if (c && (best == null || c.logworth > best.lw || (c.logworth === best.lw && c.stat > best.stat))) best = { path: nd.path, lw: c.logworth, stat: c.stat };
    }
    return best ? best.path : '';
  }

  /* A mean, a rate or an uplift as the boxes and tables write it: a rate to 4 decimals, else 6 digits. */
  const val = (S, v) => (S.binary ? fmt(v, { digits: 4 }) : sig(v));
  const treatColor = () => (SM.util.themeColors().dark ? '#ff7a6b' : '#c0392b');   // JMP's red line: the treatment
  const controlColor = () => SM.report.BASE;                                      // ... and its blue: the control
  const groupColor = (g) => (g === 1 ? treatColor() : controlColor());

  /* ======================================================================
     RENDER
     ====================================================================== */
  function plotOpts(ctx) {
    const o = (k, d) => ctx.opt(k, d) !== false;
    return { points: o('showPoints', true), stats: o('splitStats', true), count: o('splitCount', true) };
  }

  const blockOf = (ctx, S, key) => SM.predict.graphCode(ctx, S.plots.head_code, S.plots[key]);

  async function render(ctx) {
    const base = payloadOf(ctx);
    if (!base.treatment) { ctx.container.append(ctx.warn('Choose a Treatment column (Model Dialog in the red triangle).')); return; }
    const res = await ctx.call('uplift.fit', { ...base, plot: plotOpts(ctx) });
    const S = state(ctx, res, base);
    ctx._uplift = S;
    const box = ctx.container;
    const o = (k, d) => ctx.opt(k, d);
    box.append(ctx.note(groupsNote(res)));
    if (o('showGraph', true)) box.append(ctx.row(SM.predict.withCode(modelGraph(ctx, S), blockOf(ctx, S, 'graph'))));
    box.append(buttons(ctx, S));
    box.append(summaryTable(ctx, S));
    const notes = res.notes || [];
    if (notes.length) box.append(...notes.map((t) => (/was not done/.test(t) ? ctx.warn(t) : ctx.note(t))));
    if (o('showTree', true)) box.append(PT().treeBox(ctx, S, false), blockOf(ctx, S, 'tree') || '');
    box.append(ctx.note(treeNote(S)));
    box.append(ctx.code(res.script));
    if (!ctx.headless) PT().watchSelection(ctx, S);
    if (o('cands', true)) candidatesOutline(ctx, S);
    if (o('leafReport', false)) leafOutline(ctx, S);
    if (o('upliftGraph', false)) upliftGraphOutline(ctx, S);
    if (o('qini', false)) qiniOutline(ctx, S);
    if (o('history', false)) PT().historyOutline(ctx, S, 'RSquare', 'p:uplift:history');
    if (o('contrib', false)) contributionsOutline(ctx, S);
    if (res.threshold && ctx.opt('threshold', false)) {
      SM.predict.threshold(ctx, null, res.threshold, { yCol: ctx.role('y'), save: { fn: 'uplift.save', payload: { ...base, what: 'predicteds' } }, title: 'Decision Threshold' });
    }
  }

  function groupsNote(res) {
    const what = res.binary ? `the rate of ${res.y} = ${res.interest}` : `the mean of ${res.y}`;
    return `Treatment: ${res.treatment} = ${res.treat}; control: ${res.control.length > 1 ? `the other levels (${res.control.join(', ')})` : res.control[0]}. The uplift (Trt Diff) is ${what} of the treatment rows less that of the control rows.`;
  }

  function treeNote(S) {
    const { res } = S;
    const n = res.leaves.length;
    return `${res.splits} split${res.splits === 1 ? '' : 's'}, ${n} lea${n === 1 ? 'f' : 'ves'}; each split's side with the larger uplift is on the left. Each split is the one whose split x treatment interaction has the largest LogWorth (${res.binary ? 'its likelihood-ratio ChiSquare in the logistic model' : 'its F Ratio in the linear model'} of the response on the split, the treatment and the interaction). Click a node to select its rows; its red triangle has Split Here, Split Best, Split Specific and Prune Below.`;
  }

  /* ---- Split, Prune, Go ----------------------------------------------------------------------------------- */
  function buttons(ctx, S) {
    const b = (text, title, fn, disabled = false) => {
      const x = el('button', { type: 'button', class: 'sm-btn small', text, title, disabled });
      x.addEventListener('click', fn);
      return x;
    };
    const add = (step) => PT().addStep(ctx, step);
    const split = b('Split', 'Split the leaf and column with the largest LogWorth (Shift-click: several splits)', async (ev) => {
      if (ev.shiftKey) {
        const v = await SM.ui.form({ title: 'Split', info: 'p:uplift:tree', fields: [{ key: 'n', label: 'Number of splits', type: 'number', value: 5, help: HELP.splits }], validate: (x) => (x.n >= 1 && x.n <= 500 ? null : 'From 1 to 500 splits') });
        if (v) add({ op: 'split', n: Math.round(v.n) });
      } else add({ op: 'split' });
    });
    const prune = b('Prune', 'Take back the split with two leaves and the smallest LogWorth', () => add({ op: 'prune' }), !S.res.splits);
    const go = S.res.has_validation ? b('Go', 'Split until the validation RSquare has not improved for 10 splits, then keep the best tree', () => add({ op: 'go' }))
      : S.res.folds ? b('Go', `Split until the RSquare crossvalidated by the ${S.res.folds.k} folds of ${S.res.folds.column} has not improved for 10 splits, then keep the best tree`, () => add({ op: 'go' })) : null;
    const info = typeof KvotInfo !== 'undefined' ? KvotInfo.slot('p:uplift:tree') : null;
    return el('div', { class: 'sm-part-buttons', 'data-noexport': '' }, split, prune, go, info);
  }

  /* ---- the summary line --------------------------------------------------------------------------------- */
  function summaryTable(ctx, S) {
    const { res } = S;
    const sets = res.summary.length > 1;
    const cols = [sets ? { key: 'set', label: '', fmt: 'text' } : null, { key: 'rsquare', label: 'RSquare', digits: 3 }, { key: 'rmse', label: 'RMSE' },
      { key: 'n', label: 'N', fmt: 'int' }, { key: 'splits', label: 'Number of Splits', fmt: 'int' }, { key: 'aicc', label: 'AICc' }].filter(Boolean);
    return el('div', { class: 'sm-part-summary' }, ctx.rt({ columns: cols, rows: res.summary }, { key: 'summary', sortable: false, name: 'Uplift Summary' }));
  }

  /* ======================================================================
     THE MODEL GRAPH: each leaf's treatment rows, then its control rows
     ====================================================================== */
  function modelGraph(ctx, S) {
    const { res } = S;
    const a = res.assign;
    const parts = [];   // [leaf, group, the indices of its training rows]
    S.leafIdx.forEach((m, l) => { for (const g of [1, 0]) parts.push([l, g, m.filter((i) => a.trt[i] === g)]); });
    const total = parts.reduce((s, p) => s + p[2].length, 0) || 1;
    const edges = [0];
    let run = 0;
    for (const p of parts) { run += p[2].length; edges.push(run / total); }   // the rows taken so far over all of them, as the code divides
    const showPoints = ctx.opt('showPoints', true);
    const traces = [];
    const rng = SM.util.rng('uplift graph');
    const hoverOf = (i, l, g) => `row ${a.rows[i] + 1}<br>leaf ${l + 1}: ${T(res.leaves[l].label)}<br>${T(S.groupNames[g === 1 ? 0 : 1])}`;
    const means = (l, g) => res.leaves[l].means[g];
    for (const g of [1, 0]) {
      const xs = [], ys = [], rows = [], hov = [];
      const lx = [], ly = [], lt = [];
      const bx = [], by = [], bw = [], brows = [], bt = [];
      parts.forEach(([l, gg, idx], k) => {
        if (gg !== g) return;
        const lo = edges[k], hi = edges[k + 1];
        const m = means(l, g);
        if (!S.binary) {
          idx.forEach((i, q) => { xs.push(lo + ((q + 0.5) / idx.length) * (hi - lo)); ys.push(a.y[i]); rows.push(a.rows[i]); hov.push(`${hoverOf(i, l, g)}<br>${T(res.y)} ${sig(a.y[i])}`); });
        } else {
          // the bar is the part's rows of the level of interest (their share of the part is the rate): a selection of them shows over it
          bx.push((lo + hi) / 2); by.push(m); bw.push(Math.max(1e-6, hi - lo)); brows.push(idx.filter((i) => a.y[i] === 1).map((i) => a.rows[i])); bt.push(`leaf ${l + 1}, ${T(S.groupNames[g === 1 ? 0 : 1])}: rate ${val(S, m)}`);
          idx.forEach((i) => {
            const yes = a.y[i] === 1;
            xs.push(lo + (0.08 + 0.84 * rng.u()) * (hi - lo));
            ys.push(yes ? (0.1 + 0.8 * rng.u()) * m : m + (0.1 + 0.8 * rng.u()) * (1 - m));
            rows.push(a.rows[i]);
            hov.push(`${hoverOf(i, l, g)}<br>${T(res.y)} ${yes ? T(res.interest) : 'other'}`);
          });
        }
        lx.push(lo, hi, null); ly.push(m, m, null); lt.push(`leaf ${l + 1}: ${val(S, m)}`, `leaf ${l + 1}: ${val(S, m)}`, '');
      });
      const name = T(S.groupNames[g === 1 ? 0 : 1]);
      const partN = parts.filter((p) => p[1] === g).map((p) => p[2].length);
      if (S.binary) traces.push({ type: 'bar', x: bx, y: by, base: bx.map(() => 0), width: bw, rows: brows, rowsScale: partN.map((k) => (k ? 1 / k : 0)), marker: { color: groupColor(g), opacity: showPoints ? 0.28 : 0.8, line: { width: 0 } }, name, hovertext: bt, hovertemplate: '%{hovertext}<extra></extra>', showlegend: true });
      if (showPoints) traces.push({ type: rows.length > 4000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter', mode: 'markers', x: xs, y: ys, rows, marker: { size: rows.length > 1500 ? (S.binary ? 3 : 3.5) : (S.binary ? 4.5 : 5), color: groupColor(g) }, hovertext: hov, hovertemplate: '%{hovertext}<extra></extra>', name, showlegend: !S.binary });
      traces.push({ type: 'scatter', mode: 'lines', x: lx, y: ly, line: { color: groupColor(g), width: 2.2 }, hovertext: lt, hovertemplate: '%{hovertext}<extra></extra>', name: `${name}: ${S.binary ? 'rate' : 'mean'}`, showlegend: !S.binary && !showPoints });
    }
    const nl = res.leaves.length;
    const centers = res.leaves.map((_, l) => (edges[2 * l] + edges[2 * l + 2]) / 2);
    const shapes = res.leaves.slice(1).map((_, k) => ({ type: 'line', xref: 'x', yref: 'paper', x0: edges[2 * (k + 1)], x1: edges[2 * (k + 1)], y0: 0, y1: 1, line: { color: SM.util.themeColors().muted, width: 1, dash: 'dot' } }));
    const ticks = nl <= 40 ? { tickvals: centers, ticktext: res.leaves.map((lf) => String(lf.number)) } : { showticklabels: false };
    return ctx.plot(traces, {
      showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, shapes, bargap: 0, barmode: 'overlay',
      margin: { l: 56, r: 10, t: 26, b: 40 },
      xaxis: { range: [0, 1], showgrid: false, zeroline: false, title: { text: 'Leaves: the treatment, then the control' }, ...ticks },
      yaxis: S.binary ? { range: [0, 1], title: { text: `${res.y}: rate of ${res.interest}` } } : { title: { text: res.y }, zeroline: false },
    }, { width: W(560), height: 300, title: `Uplift model of ${res.y}` });
  }

  /* ======================================================================
     THE NODE BOXES (drawn in Partition's tree): a line per group, the
     t Ratio, Trt Diff and LogWorth
     ====================================================================== */
  function geometry(ctx, S, small) {
    const o = (k, d) => ctx.opt(k, d);
    const G = { small: false, stats: o('splitStats', true) !== false, count: o('splitCount', true) !== false, TITLE: 20, ROW: 14, GAP: 14, VGAP: 28, PAD: 6 };
    const longest = Math.max(9, ...S.groupNames.map((g) => String(g).length));
    G.levelW = Math.max(60, Math.min(110, Math.round(6.3 * longest) + 8));
    G.numW = 58;
    G.cntW = G.count ? 46 : 0;
    G.BW = Math.max(184, 10 + G.levelW + G.numW + G.cntW);
    G.height = (nd) => G.TITLE + G.PAD + G.ROW * 3 + G.ROW * (G.stats ? (nd.split ? 3 : 2) : 1) + 6;
    return G;
  }

  function nodeBox(S, G, nd) {
    const P = PT();
    const g = P.nodeFrame(S, G, nd, 'sm-upl-node', `${nd.label}: count ${fmt(nd.count)}, Trt Diff ${val(S, nd.diff)}${nd.split ? `, split by ${nd.split.column}` : ''}`);
    let y = G.TITLE + G.PAD + G.ROW - 3;
    const xNum = 7 + G.levelW + G.numW - 4, xCnt = 7 + G.levelW + G.numW + G.cntW - 4;
    g.append(P.txt('sm-part-h', 7, y, 'Treatment'), P.txt('sm-part-h', xNum, y, S.binary ? 'Rate' : 'Mean', 'end'));
    if (G.count) g.append(P.txt('sm-part-h', xCnt, y, 'Count', 'end'));
    y += G.ROW;
    for (const [grp, name] of [[1, S.groupNames[0]], [0, S.groupNames[1]]]) {   // the treatment first
      g.append(svg('rect', { class: 'sm-upl-swatch', x: 7, y: y - 8, width: 3, height: 8, fill: groupColor(grp) }));
      g.append(P.txt('sm-part-k', 13, y, P.clip(name, G.levelW - 8)), P.txt('sm-part-v', xNum, y, val(S, nd.means[grp]), 'end'));
      if (G.count) g.append(P.txt('sm-part-v', xCnt, y, fmt(nd.counts[grp]), 'end'));
      y += G.ROW;
    }
    const kv = (k, v) => { g.append(P.txt('sm-part-k', 7, y, k), P.txt('sm-part-v', G.BW - 7, y, v, 'end')); y += G.ROW; };
    if (G.stats) kv('t Ratio', fmt(nd.t, { sig: 4 }));
    kv('Trt Diff', val(S, nd.diff));
    if (G.stats && nd.split) kv('LogWorth', sig(nd.split.logworth));
    g.append(P.selBar(G, nd));
    return g;
  }

  const LOOK = { geometry, node: nodeBox, label: 'Uplift tree' };

  /* ======================================================================
     CANDIDATES
     ====================================================================== */
  function candidatesOutline(ctx, S) {
    const ob = ctx.outline('Candidates', { key: 'cands', info: 'p:uplift:cands', menu: () => [
      ctx.check('Sort Split Candidates', 'sortCands', null, false),
      { label: 'Remove', action: () => ctx.set('cands', false) },
    ] });
    S.candOutline = ob;
    const host = el('div');
    ob.add(host);
    const stat = S.binary ? 'ChiSquare' : 'F Ratio';
    S.fillCands = () => {
      const nd = S.by.get(S.cand) || S.by.get('');
      const rows = (nd.cands || []).map((c) => ({ ...c, mark: nd.split ? (c.column === nd.split.column ? '✓' : '') : (c.best ? '✓' : '') }));
      if (ctx.opt('sortCands', false)) rows.sort((a, b) => (b.logworth ?? -1) - (a.logworth ?? -1));
      const what = nd.split ? `split by ${nd.split.column} (✓)` : S.cand === nextLeaf(S.res) && (nd.cands || []).some((c) => c.best) ? 'the leaf the next Split takes; ✓ its best column' : 'a leaf; ✓ its best column';
      host.replaceChildren(
        PT().wide(ctx.rt({ columns: [{ key: 'mark', label: '', fmt: 'cond', left: true }, { key: 'column', label: 'Term', fmt: 'text' }, { key: 'stat', label: stat }, { key: 'logworth', label: 'LogWorth', digits: 4 }, { key: 'gamma', label: 'Gamma' },
          { key: 'split', label: 'Split', fmt: 'cond', left: true }, { key: 'other', label: 'Other Side', fmt: 'cond', left: true, hidden: true }], rows },
        { key: 'cands', caption: `${nd.label} (${fmt(nd.count)} rows): ${what}`, sortable: true, cellClass: (r) => (r.mark ? 'sm-part-best' : '') })),
        ctx.note(`For each column its best split of this node (a click on a node shows its candidates): the ${stat} of the split x treatment interaction ${S.binary ? 'in the logistic model (likelihood ratio)' : 'in the linear model'} of the response on the split, the treatment and the interaction; LogWorth, −log10 of its p-value adjusted for the number of ways the column can be cut; Gamma, the interaction's coefficient: the Split side's ${S.binary ? 'log odds ratio of the treatment less the other side\'s' : 'uplift less the other side\'s'}. A column with no split has none that leaves ${fmt(S.res.minsize)} rows, and rows of both groups, on each side.`));
    };
    S.fillCands();
  }

  /* ======================================================================
     LEAF REPORT
     ====================================================================== */
  function leafOutline(ctx, S) {
    const { res } = S;
    const ob = ctx.outline('Leaf Report', { key: 'leaves', info: 'p:uplift:leaves', menu: () => [{ label: 'Remove', action: () => ctx.set('leafReport', false) }] });
    const what = S.binary ? 'Rate' : 'Mean';
    const [tn, cn] = S.groupNames;
    const valid = res.sets.includes('Validation'), test = res.sets.includes('Test');
    const cols = [{ key: 'leaf', label: 'Leaf', fmt: 'int' }, { key: 'label', label: 'Leaf Label', fmt: 'text' }, { key: 'rule', label: 'Rule', fmt: 'text' },
      { key: 'm1', label: `${tn} ${what}`, digits: S.binary ? 4 : undefined }, { key: 'n1', label: `${tn} Count`, fmt: 'int' },
      { key: 'm0', label: `${cn} ${what}`, digits: S.binary ? 4 : undefined }, { key: 'n0', label: `${cn} Count`, fmt: 'int' },
      { key: 'diff', label: 'Trt Diff', digits: S.binary ? 4 : undefined }, { key: 't', label: 't Ratio', hidden: true },
      valid ? { key: 'vdiff', label: 'Validation Trt Diff', digits: S.binary ? 4 : undefined } : null, test ? { key: 'tdiff', label: 'Test Trt Diff', digits: S.binary ? 4 : undefined, hidden: true } : null].filter(Boolean);
    const rows = res.leaves.map((lf) => ({ leaf: lf.number, label: lf.label, rule: lf.rule, m1: lf.means[1], n1: lf.counts[1], m0: lf.means[0], n0: lf.counts[0], diff: lf.diff, t: lf.t,
      vdiff: lf.validation ? lf.validation.diff : null, tdiff: lf.test ? lf.test.diff : null }));
    ob.add(PT().wide(ctx.rt({ columns: cols, rows }, { key: 'leafreport', caption: 'Uplift by Leaf' })),
      ctx.note(`The leaves from left to right, numbered as Save Leaf Numbers numbers them: the label is the path of conditions from the root, the rule the same conditions with those on one column merged; each group's ${what.toLowerCase()} and count of the training rows, and Trt Diff, the uplift: the ${tn} rows' ${what.toLowerCase()} less the ${cn} rows'.${valid ? ' Validation Trt Diff is the same of the leaf\'s validation rows (empty when a group has none there).' : ''}`));
  }

  /* ======================================================================
     THE UPLIFT GRAPH: each leaf's uplift, the largest first
     ====================================================================== */
  function upliftGraphOutline(ctx, S) {
    const { res } = S;
    const ob = ctx.outline('Uplift Graph', { key: 'upliftgraph', info: 'p:uplift:graph', menu: () => [{ label: 'Remove', action: () => ctx.set('upliftGraph', false) }] });
    const order = res.leaves.map((_, l) => l).sort((p, q) => res.leaves[q].diff - res.leaves[p].diff || p - q);
    const tot = res.leaves.reduce((s, lf) => s + lf.count, 0) || 1;
    const share = order.map((l) => res.leaves[l].count / tot);
    const left = [];
    share.reduce((s, v) => { left.push(s); return s + v; }, 0);
    const traces = [{ type: 'bar', x: order.map((_, i) => left[i] + share[i] / 2), y: order.map((l) => res.leaves[l].diff), width: share, rows: order.map((l) => S.leafTrain[l]),
      rowsScale: order.map((l) => (S.leafTrain[l].length ? res.leaves[l].diff / S.leafTrain[l].length : 0)),
      marker: { color: SM.report.BAR, line: { width: 1, color: SM.util.themeColors().surface } }, hovertext: order.map((l) => `leaf ${l + 1}: ${T(res.leaves[l].label)}<br>Trt Diff ${val(S, res.leaves[l].diff)}, ${fmt(share[order.indexOf(l)] * 100, { digits: 1 })}% of the rows`), hovertemplate: '%{hovertext}<extra></extra>', name: 'Training' }];
    const valid = res.sets.includes('Validation');
    if (valid) {
      const vx = [], vy = [], vt = [];
      order.forEach((l, i) => {
        const v = res.leaves[l].validation && res.leaves[l].validation.diff;
        if (v == null || !Number.isFinite(v)) return;
        vx.push(left[i], left[i] + share[i], null); vy.push(v, v, null); vt.push(`leaf ${l + 1}, validation rows: Trt Diff ${val(S, v)}`, '', '');
      });
      traces.push({ type: 'scatter', mode: 'lines', x: vx, y: vy, line: { color: SM.util.themeColors().text, width: 2 }, hovertext: vt, hovertemplate: '%{hovertext}<extra></extra>', name: 'Validation' });
    }
    ob.add(ctx.row(SM.predict.withCode(ctx.plot(traces, { showlegend: valid, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, bargap: 0, margin: { l: 60, r: 12, t: valid ? 26 : 8, b: 42 },
      xaxis: { range: [0, 1], title: { text: 'Leaves by uplift (width: the share of the rows)' }, tickvals: order.map((_, i) => left[i] + share[i] / 2), ticktext: order.map((l) => String(l + 1)), zeroline: false },
      yaxis: { title: { text: 'Uplift (Trt Diff)' }, zeroline: true } }, { width: W(460), height: 300, title: 'Uplift graph', select: false }), blockOf(ctx, S, 'upliftgraph'))),
    ctx.note(`Each leaf's uplift, the largest first, as wide as its share of the training rows${valid ? '; the black line is the leaf\'s uplift on the validation rows, which shows whether the ordering holds on new rows' : ''}. A bar selects the leaf's training rows.`));
  }

  /* ======================================================================
     THE QINI CURVE (not in JMP)
     ====================================================================== */
  function qiniOutline(ctx, S) {
    const { res } = S;
    const ob = ctx.outline('Qini Curve', { key: 'qini', info: 'p:uplift:qini', menu: () => [{ label: 'Remove', action: () => ctx.set('qini', false) }] });
    const color = (s) => PT().setColor(s);
    const traces = [];
    for (const q of res.qini) {
      traces.push({ type: 'scatter', mode: 'lines+markers', x: q.x, y: q.q, name: `${q.set} (Qini ${q.coef == null ? '.' : fmt(q.coef, { sig: 4 })})`, line: { color: color(q.set), width: 1.8 }, marker: { size: 5, color: color(q.set) }, hovertemplate: `${q.set}: %{x:.3f} of the rows, Qini %{y:.4g}<extra></extra>` });
      traces.push({ type: 'scatter', mode: 'lines', x: [0, 1], y: [0, q.q[q.q.length - 1]], line: { color: color(q.set), width: 1, dash: 'dot' }, hoverinfo: 'skip', showlegend: false });
    }
    ob.add(ctx.row(SM.predict.withCode(ctx.plot(traces, { showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, margin: { l: 64, r: 12, t: 46, b: 42 }, xaxis: { range: [0, 1], title: { text: 'Portion of the rows (the highest predicted uplift first)' } }, yaxis: { title: { text: 'Qini: incremental response per row' }, zeroline: true } },
      { width: W(420), height: 320, title: 'Qini curve', select: false }), blockOf(ctx, S, 'qini'))),
    PT().wide(ctx.rt({ columns: [{ key: 'set', label: 'Set', fmt: 'text' }, { key: 'coef', label: 'Qini Coefficient' }, { key: 'end', label: 'Qini at 1' }], rows: res.qini.map((q) => ({ set: q.set, coef: q.coef, end: q.q[q.q.length - 1] })) }, { key: 'qini', sortable: false })),
    ctx.note(`Each set's rows taken in the order of the uplift the tree predicts for them, highest first (a leaf's rows together): after each leaf, the treatment rows' response less the control rows' scaled to as many rows as the treatment's, per row of the set (Radcliffe's Qini). The dotted line is the same taken at random; the Qini coefficient is the area between the two, larger when the tree ranks the rows better. On the ${res.sets.includes('Validation') ? 'validation' : 'training'} rows it says how well the uplift ranks new rows.`));
  }

  /* ======================================================================
     COLUMN UPLIFT CONTRIBUTIONS
     ====================================================================== */
  function contributionsOutline(ctx, S) {
    const c = S.res.contributions;
    const splits = c.rows.map((r) => `${r.column} ${r.splits}`).join(', ');
    SM.predict.contributions(ctx, null, c, { title: 'Column Uplift Contributions', head: S.plots.head_code,
      note: `Number of Splits: ${splits}. A column's contribution is the sum of the ${S.binary ? 'ChiSquare' : 'F Ratio'} values of its splits (JMP's), the significance of the split x treatment interaction; the portion is its share of the total.` });
  }

  /* ======================================================================
     SAVE COLUMNS, MINIMUM SIZE SPLIT, THE RED TRIANGLE
     ====================================================================== */
  function saveItems(ctx, S) {
    if (!S) return [];
    const base = S.base;
    const from = { notes: `from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}` };
    const run = async (fn, payload, then) => { try { const r = await ctx.call(fn, payload); if (r.error) throw new Error(r.error); then(r); } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); } };
    const formula = (which) => run('uplift.formula', base, (r) => { const f = r[which]; ctx.saveFormula(f.name, f.expr, { ...from, notes: `a formula from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}: ${which === 'difference' ? 'the uplift of each row\'s leaf' : 'each row\'s group\'s mean (or rate) in its leaf'}` }); });
    return [{ label: 'Save Columns', submenu: () => [
      { label: 'Save Difference', action: () => run('uplift.save', { ...base, what: 'difference' }, (r) => ctx.saveColumn(r.name, { rows: r.rows, values: r.values }, { ...from, notes: `${from.notes}: the uplift of each row's leaf` })) },
      { label: 'Save Difference Formula', action: () => formula('difference') },
      { label: 'Save Predicteds', action: () => run('uplift.save', { ...base, what: 'predicteds' }, (r) => savePredicteds(ctx, r, from)) },
      { label: 'Save Prediction Formula', action: () => formula('prediction') },
      { separator: true },
      { label: 'Save Leaf Numbers', action: () => run('uplift.leaves', base, (r) => ctx.saveColumn('Leaf Number', { rows: r.rows, values: r.numbers }, { ...from, modelingType: 'nominal' })) },
      { label: 'Save Leaf Labels', action: () => run('uplift.leaves', base, (r) => ctx.saveColumn('Leaf Label', { rows: r.rows, values: r.labels }, { ...from, dataType: 'character' })) },
    ] }];
  }

  function savePredicteds(ctx, r, from) {
    if (r.values) { ctx.saveColumn(r.name, { rows: r.rows, values: r.values }, from); return; }
    r.names.forEach((nm, j) => ctx.saveColumn(nm, { rows: r.rows, values: r.prob.map((p) => p[j]) }, from));
    if (r.most_likely) ctx.saveColumn(r.most_name, { rows: r.rows, values: r.most_likely }, { ...from, dataType: 'character', modelingType: r.ordinal ? 'ordinal' : 'nominal', valueOrder: r.levels });
  }

  async function minSizeDialog(ctx) {
    const v = await SM.ui.form({ title: 'Minimum Size Split', lead: 'The fewest rows (by Freq) either side of a split may have: a number of rows, or below 1 a share of the training rows; empty: JMP\'s default, 25 or the training rows over 2000.', fields: [{ key: 'm', label: 'Minimum size', type: 'number', value: ctx.opt('minsize', null), help: HELP.minsize }], validate: (x) => (x.m == null || x.m > 0 ? null : 'A positive number, or empty') });
    if (v) ctx.set('minsize', v.m == null ? null : v.m);
  }

  function topMenu(ctx) {
    const S = ctx._uplift;
    const res = S ? S.res : null;
    const pick = (key, keys, names, cur) => keys.map((k, i) => ({ label: names[i], checked: k === cur, action: () => ctx.set(key, k) }));
    return [
      { label: 'Display Options', submenu: () => [
        ctx.check('Show Points', 'showPoints', null, true), ctx.check('Show Tree', 'showTree', null, true), ctx.check('Show Graph', 'showGraph', null, true),
        ctx.check('Show Split Stats', 'splitStats', null, true), ctx.check('Show Split Count', 'splitCount', null, true),
        ctx.check('Show Split Candidates', 'cands', null, true), ctx.check('Sort Split Candidates', 'sortCands', null, false),
      ] },
      { label: 'Split Best', action: () => PT().addStep(ctx, { op: 'split' }) },
      { label: 'Prune Worst', disabled: !res || !res.splits, action: () => PT().addStep(ctx, { op: 'prune' }) },
      { label: 'Minimum Size Split…', action: () => minSizeDialog(ctx) },
      { separator: true },
      ctx.check('Leaf Report', 'leafReport', null, false),
      ctx.check('Uplift Graph', 'upliftGraph', null, false),
      ctx.check('Split History', 'history', null, false),
      ctx.check('Column Uplift Contributions', 'contrib', null, false),
      ctx.check('Qini Curve', 'qini', null, false),
      res && res.threshold ? SM.predict.thresholdItem(ctx, null) : null,
      { separator: true },
      res ? { label: 'Treatment Level', submenu: () => pick('treatLevel', res.treatment_keys, res.treatment_levels, res.treat_key) } : null,
      res && res.binary ? { label: 'Response Level', submenu: () => pick('responseLevel', res.response_keys, res.response_names, res.interest_key) } : null,
      { label: 'Start Over', disabled: !stepsOf(ctx).length, action: () => ctx.set('steps', [], scopeOf(ctx)) },
      ...saveItems(ctx, S),
    ].filter(Boolean);
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:uplift': {
      kicker: 'Analyze > Consumer Research', title: 'Uplift',
      lead: 'Where does a treatment help? An uplift model (JMP Pro\'s) is a decision tree grown on the rows of an experiment, some treated (an offer, a mailing) and some not, that splits the rows where the treatment\'s effect differs most. Each leaf has its uplift: the treated rows\' mean response (or rate) less the control rows\'. Treat the rows of the leaves with the largest uplift; leave alone those where it is 0, or below it.',
      sections: [
        { heading: 'Roles', choices: [['Y, Response', 'Continuous (the uplift is a difference of means) or nominal or ordinal (of rates of its first level, the others together).'], ['Treatment', 'A nominal or ordinal column: its first level is the treatment, the other levels the control (JMP\'s rule); set the value order, or use Treatment Level in the red triangle.'], ['X, Factor', 'The columns a split may use.'], ['Weight, Freq', 'Freq counts a row that many times; Weight weighs it in the means and the tests.'], ['Validation', '0 or Training grows the tree, 1 or Validation chooses its size (Go) and shows on the Uplift Graph and the Qini curve, 2 or Test is kept out of both.'], ['By', 'A tree for each level, each with its own splits.']] },
        { heading: 'Options', choices: [['Minimum Size Split', 'The fewest rows either side of a split: JMP\'s default is 25 or the training rows over 2000, whichever is more.'], ['Informative Missing', 'A missing value of a continuous X goes to the side of each split that fits better; a missing level is a level of its own. Off: rows missing a factor are left out.'], ['Ordinal Restricts Order', 'An ordinal X is cut between neighbouring levels only.'], ['Validation Portion, Random Seed', 'A share of the rows held back for validation, drawn from the seed.']] },
        { heading: 'How a split is chosen', text: 'For every leaf, column and cut, a model of the response on the split (the two sides), the treatment and their interaction, as JMP documents: a linear model for a continuous response, whose interaction F Ratio is tested; a logistic model for a categorical one, whose interaction ChiSquare is tested (here the likelihood ratio). The interaction is how much the treatment\'s effect differs between the two sides. The split made has the largest LogWorth: −log10 of the p-value adjusted for the number of ways the column can be cut. A nominal X of up to 12 levels tries every grouping of its levels; one of more is ordered by the uplift of each level and cut between neighbours.' },
        { heading: 'The summary', text: 'The tree as a regression model, each leaf and group with its own mean (or rate): its RSquare, its RMSE (the training rows: over the error degrees of freedom; the validation and test rows: the root mean squared error of the predictions), N, the Number of Splits and the AICc of the training rows. Go splits until the validation RSquare has not improved for 10 splits and keeps the best tree, as JMP\'s Go does.' },
        { heading: 'Differences from JMP', text: 'JMP adjusts its LogWorths by a Monte Carlo calibration it has not published; here the adjustment is Partition\'s bound (the expected upcrossings for ordered cuts, Bonferroni over the groupings of a nominal X), so LogWorths differ and where two columns are close the split chosen can too. The bound is a little conservative: with no uplift at all an adjusted p-value falls below 0.05 in about 2% of samples, not 5% (the tests check it by Monte Carlo). JMP does not say which ChiSquare it tests for a categorical response; here it is the likelihood ratio. The Qini curve, the leaf rules, the validation line of the Leaf Report, Treatment Level and Response Level (JMP takes the first levels) and the Decision Threshold are not in JMP\'s Uplift; Publish Difference Formula (the Formula Depot) is not here.' },
      ],
      more: MORE,
    },
    'p:uplift:tree': {
      kicker: 'Uplift', title: 'The Tree and the Buttons',
      lead: 'Split splits the leaf whose best split has the largest LogWorth; Prune takes back the split with two leaves and the smallest LogWorth; Go (with validation rows) splits until the validation RSquare has not improved for 10 splits and keeps the tree with the best one. Shift-click Split for several splits. Redo, a project and By keep the splits; Start Over (red triangle) takes them all back.',
      sections: [
        { heading: 'The buttons', choices: [
          ['Split', 'Makes the best split there is: of every leaf and every column, the cut with the largest LogWorth of its split x treatment interaction. Shift-click it to make several in one step.'],
          ['Prune', 'Takes back the weakest of the splits whose two children are both leaves. Dimmed while the tree has no split.'],
          ['Go', 'Only with validation rows (a Validation column or a Validation Portion), or the folds of a K-fold Validation column. Splits until 10 splits in a row have not improved the validation RSquare, then keeps the tree that had the best one. With K folds the RSquare is crossvalidated: a tree per fold grows on the other folds split for split, and every row is predicted by the one that did not see its fold (not in JMP, whose Uplift takes training, validation and test rows).'],
        ] },
        { heading: 'The graph', text: 'Each leaf\'s training rows side by side, numbered as in the Leaf Report: the treatment\'s rows (red) and then the control\'s (blue), each as wide as its rows, with the group\'s mean across its part; for a categorical response the rate of the level of interest, the rows of that level under it and the others above. Where the red line is above the blue one the treatment raises the response. Drag over points to select rows.' },
        { heading: 'A node', choices: [['Treatment, Rate or Mean, Count', 'each group\'s mean (or rate of the level of interest) and count of the node\'s training rows, the treatment first'], ['t Ratio', 'of the difference between the two groups, the pooled two-sample t'], ['Trt Diff', 'the uplift: the treatment\'s mean (or rate) less the control\'s'], ['LogWorth', 'of the split made at the node']] },
        { heading: 'Clicking a node', choices: [
          ['A click', 'Selects the node\'s rows (every set) and shows its Candidates; Shift adds, Ctrl or ⌘ toggles.'],
          ['Split Here, Split Best, Split Specific…', 'In the node\'s red triangle (or a right click): its best split, the best split at or below it, or a split by a column (and a cut) of your choice.'],
          ['Prune Below, Prune Worst', 'Take back every split below the node, or its weakest last split.'],
          ['Select Rows, Show Candidates', 'Select the node\'s rows; or show its Candidates without selecting.'],
        ] },
      ],
      more: MORE,
    },
    'p:uplift:cands': {
      kicker: 'Uplift', title: 'Candidates',
      lead: 'For the node picked (by a click; at first the leaf the next Split takes), every column\'s best split: the F Ratio (continuous response) or ChiSquare (categorical) of its split x treatment interaction, its LogWorth, Gamma (the interaction\'s coefficient: the Split side\'s uplift, or log odds ratio of the treatment, less the other side\'s) and the condition of the Split side (right click, Columns, shows the Other Side). ✓ marks the column split there, or a leaf\'s best.',
      more: MORE,
    },
    'p:uplift:leaves': {
      kicker: 'Uplift', title: 'Leaf Report',
      lead: 'Each leaf, left to right: its label (the conditions from the root), its rule (the same with the conditions on one column merged), each group\'s rate (or mean) and count, and its Trt Diff, the uplift; with validation rows, the uplift on them too, which should keep the leaves\' order if the tree holds on new rows.',
      more: MORE,
    },
    'p:uplift:graph': {
      kicker: 'Uplift', title: 'Uplift Graph',
      lead: 'The leaves\' uplifts, the largest first, each bar as wide as the leaf\'s share of the training rows, as JMP draws it; with validation rows a black line across each bar at the leaf\'s uplift on them. Target the leaves on the left: the treatment helps them most.',
      more: MORE,
    },
    'p:uplift:qini': {
      kicker: 'Uplift', title: 'Qini Curve',
      lead: 'How well the tree ranks rows by uplift (not in JMP): the rows taken highest predicted uplift first, and after each leaf the treatment rows\' response less the control rows\', the control\'s scaled to as many rows as the treatment\'s, per row of the set (Radcliffe\'s Qini). The dotted line takes the rows at random. A curve well above its line, on the validation or test rows, means the ranking holds on new rows; the Qini coefficient is the area between them.',
      more: MORE,
    },
    'p:uplift:history': {
      kicker: 'Uplift', title: 'Split History',
      lead: 'The RSquare of each set (of the regression model the tree is: a mean for each leaf and group) after each split, in the order the splits were made, and the training rows\' AICc. After Go the splits it looked at past the tree it kept are dotted. Split History Details has the numbers.',
      more: MORE,
    },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'uplift', label: 'Uplift', menu: 'Analyze/Consumer Research', order: 10, info: 'p:uplift', topics: TOPICS,
    about: 'A decision tree on the rows of an experiment (a Treatment column, its first level the treatment) that splits where the treatment\'s effect on the response differs most, each split the column and cut whose split x treatment interaction has the largest LogWorth (the F Ratio in the linear model, or the likelihood-ratio ChiSquare in the logistic model, of the response on the split, the treatment and their interaction), grown with Split, Prune and Go as Partition\'s tree. The report: the model graph (each leaf\'s treatment and control rows, linked), the summary (RSquare, RMSE, N, Number of Splits, AICc), node boxes with each group\'s rate or mean, the t Ratio and Trt Diff, the uplift; Candidates with Gamma, the Leaf Report with merged rules, the Uplift Graph with the validation uplifts, the Split History, Column Uplift Contributions, the Qini curve, the Decision Threshold, and Save Columns (the Difference and its formula, the predictions and their formula, leaf numbers and labels).',
    uses: ['numpy (the splitter: partition.py\'s tree, the interaction statistic)', 'scipy.stats (f, chi2, chi), scipy.special (xlogy, gammaln, betaln)'],
    launch: {
      lead: 'Choose a response, the treatment and the factors. The tree starts with every row in one node: press Split to grow it, or Go with validation rows.',
      roles: [
        { key: 'y', label: 'Y, Response', min: 1, max: 1, hint: 'required: one, continuous or categorical', help: HELP.y },
        { key: 'treatment', label: 'Treatment', min: 1, max: 1, types: ['nominal', 'ordinal'], hint: 'required: its first level is the treatment', help: HELP.treatment },
        { key: 'x', label: 'X, Factor', min: 1, hint: 'required: one or more', help: HELP.x },
        ...SM.predict.roles(),
      ],
      options: [
        ...SM.predict.options().map((o) => (o.key === 'missing' ? { ...o, help: HELP.missing } : o)),
        { key: 'minsize', label: 'Minimum Size Split', type: 'number', value: null, hint: 'empty: JMP\'s 25, or the training rows over 2000 (below 1: a share of them)', help: HELP.minsize },
        { key: 'ordinalOrder', label: 'Ordinal Restricts Order', type: 'check', value: true, hint: 'an ordinal X is cut between neighbouring levels only', help: HELP.ordinalOrder },
      ],
      validate: (spec) => {
        const m = spec.options && spec.options.minsize;
        const r = spec.roles || {};
        const t = (r.treatment || [])[0];
        if (t && [...(r.y || []), ...(r.x || [])].includes(t)) return 'The Treatment cannot be the response or a factor too';
        return m != null && m !== '' && !(m > 0) ? 'Minimum Size Split: a positive number, or empty' : null;
      },
    },
    title: (spec, table) => {
      const id = ((spec.roles && spec.roles.y) || [])[0];
      const c = id && table ? table.col(id) : null;
      return c ? `Uplift Model for ${c.name}` : 'Uplift Model';
    },
    triangle: topMenu,
    render,
  });

  /* ---- the example: a simulated promotion, its true uplifts in the notes -------------------------------- */
  SM.io.addExample('offer', {
    label: 'Offer (4000 customers): who a promotion persuades',
    about: 'Simulated: 4000 customers of a shop, half of them sent a discount offer at random. Whether a customer bought within a month (bought) is 12% plus 1.5 points per visit last quarter (at most 10 visits) plus 8 points for members. The offer adds 22 points for members under 35, 8 points for other customers under 50, nothing from 50 to 64, and takes 10 points away from customers aged 65 or more who are not members (they dislike the mailing). Region and email opt-in change nothing. Spend (the next month, in €) is 40 + 4 per visit + 25 for members, plus 18 € with the offer for customers under 50, plus noise (sd 12). The validation column splits the rows 60/25/15 at random. For Uplift (Analyze > Consumer Research).',
    make() {
      const r = SM.util.rng('uplift-offer');
      const n = 4000;
      const c = { customer: [], age: [], member: [], visits: [], region: [], email: [], offer: [], bought: [], spend: [], validation: [] };
      for (let i = 0; i < n; i++) {
        const age = Math.round(18 + 62 * r.u());
        const member = r.u() < 0.35 ? 'Yes' : 'No';
        const visits = Math.min(10, Math.floor(-Math.log(1 - r.u()) * 2.2));
        const offer = r.u() < 0.5 ? 'Offer' : 'No offer';
        let p = 0.12 + 0.015 * visits + (member === 'Yes' ? 0.08 : 0);
        let lift = 0;
        if (age < 35 && member === 'Yes') lift = 0.22;
        else if (age < 50) lift = 0.08;
        else if (age >= 65 && member === 'No') lift = -0.10;
        if (offer === 'Offer') p += lift;
        const spend = 40 + 4 * visits + (member === 'Yes' ? 25 : 0) + (offer === 'Offer' && age < 50 ? 18 : 0) + r.normal(0, 12);
        const v = r.u();
        c.customer.push(`K${String(i + 1).padStart(4, '0')}`);
        c.age.push(age);
        c.member.push(member);
        c.visits.push(visits);
        c.region.push(r.pick(['North', 'South', 'East', 'West']));
        c.email.push(r.u() < 0.6 ? 'Yes' : 'No');
        c.offer.push(offer);
        c.bought.push(r.u() < Math.max(0.01, Math.min(0.99, p)) ? 'Yes' : 'No');
        c.spend.push(+Math.max(0, spend).toFixed(2));
        c.validation.push(v < 0.6 ? 'Training' : v < 0.85 ? 'Validation' : 'Test');
      }
      return new SM.Table({ name: 'Offer', source: 'simulated', columns: [
        { name: 'customer', dataType: 'character', values: c.customer, role: 'label' },
        { name: 'age', dataType: 'numeric', values: c.age },
        { name: 'member', dataType: 'character', values: c.member, valueOrder: ['Yes', 'No'] },
        { name: 'visits last quarter', dataType: 'numeric', values: c.visits },
        { name: 'region', dataType: 'character', values: c.region },
        { name: 'email opt-in', dataType: 'character', values: c.email, valueOrder: ['Yes', 'No'] },
        { name: 'offer', dataType: 'character', values: c.offer, valueOrder: ['Offer', 'No offer'] },
        { name: 'bought', dataType: 'character', values: c.bought, valueOrder: ['Yes', 'No'] },
        { name: 'spend (€)', dataType: 'numeric', values: c.spend },
        { name: 'validation', dataType: 'character', values: c.validation, valueOrder: ['Training', 'Validation', 'Test'] },
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
