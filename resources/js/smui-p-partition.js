/* ==========================================================================
   SMUI.HTML: ANALYZE > PREDICTIVE MODELING > PARTITION

   JMP's Partition platform: a decision tree for a continuous or categorical
   response, grown one split at a time. The report, in JMP's layout:

     the partition graph   the training rows in their leaves (linked), leaf
                           means or level rates; the Small Tree View beside it
     Split, Prune, Go      Split takes the leaf and column with the largest
                           LogWorth; Prune takes back the weakest last split;
                           Go (with validation) splits until the validation
                           RSquare has not improved for 10 splits and keeps
                           the best tree
     the summary           RSquare, RASE (or Entropy RSquare,
                           Misclassification Rate), N and Number of Splits
                           for each set
     the tree              JMP's node boxes: count, mean and std dev, or the
                           level rates and probabilities with bars; the
                           split's LogWorth. A click selects the node's rows;
                           each node has its red triangle (Split Here, Split
                           Best, Split Specific, Prune Below, Select Rows)
     Candidates            each column's best split of a node: SS or G²,
                           LogWorth, the condition
     from the red triangle Split History, Leaf Report, Column Contributions,
                           Fit Details, Confusion Matrix, ROC and Lift Curves,
                           Actual by Predicted, K Fold Crossvalidation, the
                           Prediction Profiler, Save Columns

   The splits the user makes are the report's steps (options), replayed from
   the root by resources/py/smui/partition.py, so Redo, By groups and
   projects give the same tree. CART (scikit-learn) is the second method.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, svg, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const MORE = { label: 'Partition', id: 'help-p-partition' };
  const SETS = ['Training', 'Validation', 'Test'];
  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));
  const f4 = (v) => (v == null || !Number.isFinite(v) ? '.' : v.toFixed(4));
  /* A report table in a box of its own that scrolls sideways on a phone. */
  const wide = (tbl) => el('div', { class: 'sm-part-scroll' }, tbl);
  function wrapTables(ob) {
    if (!ob || !ob.body) return ob;
    for (const t of ob.body.querySelectorAll(':scope > table.sm-rt, :scope > .sm-ob-row > table.sm-rt')) { const w = wide(null); t.replaceWith(w); w.append(t); }
    return ob;
  }
  const sig = (v, n = 6) => fmt(v, { sig: n });

  /* What each field of the launch dialog and the forms is for: the (i). */
  const HELP = {
    y: 'The column the tree predicts. Continuous: a regression tree, each leaf predicting the mean of its rows and each split chosen by the sum of squares it explains. Nominal or ordinal: a classification tree, each leaf giving a probability of every level and each split chosen by the likelihood-ratio G² (the order of an ordinal response is not used).',
    x: 'The columns a split may use, of any modeling type. A continuous column is cut at a value, an ordinal one between two neighbouring levels (see Ordinal Restricts Order), a nominal one into two groups of its levels. Each split takes the one column and cut with the largest LogWorth, so a column that does not help is simply never used.',
    minsize: 'The fewest rows a split may leave on either side, counted by Freq (CART counts rows): a cut that leaves fewer is not a candidate. 5 is JMP\'s default; raise it for a smaller, steadier tree, lower it to let small groups split off. Below 1 it is a share of the training rows: 0.05 is 5% of them.',
    ordinalOrder: 'On (the default, as in JMP): an ordinal X is cut between neighbouring levels, so each side of a split is a run of levels in their order. Off: its levels are grouped freely, as a nominal X\'s are. CART splits an ordinal X one level against the rest either way.',
    method: 'Decision Tree (the default) is JMP\'s: each split the column and cut with the largest LogWorth, a p-value adjusted for how many cuts the column offers, and leaf probabilities shrunk toward the parent\'s. CART is scikit-learn\'s tree, grown best first by the largest fall in squared error (or entropy), with no such adjustment; it splits a nominal X one level against the rest, its leaf rates can be 0, and it has no Candidates or splits of one node. Method (red triangle) switches between them.',
    missing: 'On (JMP\'s default): rows missing a factor are kept. The Decision Tree sends a missing value of a continuous X to the side of each split where it fits better, and makes a missing level of a categorical X a level of its own; CART takes the training mean plus a 0/1 Missing column. Off: rows missing any factor are left out.',
    splits: 'How many splits to make in one step, from 1 to 500, each the best one at that point: the same as pressing Split that many times. It stops early when no leaf can be split with Minimum Size Split rows on each side.',
    specificColumn: 'The X column to split this leaf by, whether or not it is the best one. A nominal or ordinal column (levels grouped) takes its best grouping of levels, or its best cut between levels.',
    specificCut: 'For a continuous column: the rows below this value go to one side and the others to the other (a missing value where it fits better); empty takes the column\'s best cut. The cut must leave Minimum Size Split rows on each side, and its LogWorth is not adjusted, as it was not chosen among cuts. Ignored for a nominal or ordinal column.',
    folds: 'The number of folds, from 2 to 100 (5 by default). The training rows are split at random, from the report\'s seed, into k folds of nearly equal size, and each fold is predicted by a tree grown on the other folds with as many best splits as this tree has. More folds grow each tree on more of the rows, and take longer.',
  };

  /* The colours of the sets (the same in the Split History and elsewhere). */
  function setColor(set) {
    const dark = SM.util.themeColors().dark;
    return { Training: SM.report.BASE, Validation: dark ? '#e0a050' : '#b8641d', Test: dark ? '#6cc38a' : '#3a7d44' }[set];
  }
  const fitColor = () => (SM.util.themeColors().dark ? '#ff7a6b' : '#c0392b');

  /* ---- the steps (per By group), the method, the payload ---------------------------------------------- */
  const scopeOf = (ctx) => (ctx.byLabel ? `by:${ctx.byLabel}` : null);
  const stepsOf = (ctx) => ctx.opt('steps', [], scopeOf(ctx)) || [];
  const isCart = (ctx) => ctx.opt('method', 'jmp') === 'cart';

  function fns(ctx) {
    return isCart(ctx)
      ? { fit: 'partition.cart_fit', save: 'partition.cart_save', leaves: 'partition.cart_leaves', kfold: 'partition.cart_kfold', profile: 'partition.cart.profile' }
      : { fit: 'partition.fit', save: 'partition.save', leaves: 'partition.leaves', kfold: 'partition.kfold', profile: 'partition.profile' };
  }

  function payloadOf(ctx) {
    // a step names its column by id (so a project remaps it); the backend takes names
    const steps = stepsOf(ctx).map((s) => (s.col ? { ...s, col: (ctx.col(s.col) || { name: s.col }).name } : s));
    const ms = Number(ctx.opt('minsize', 5));
    return { y: ctx.name('y'), x: ctx.names('x'), ...SM.predict.payload(ctx), minsize: ms > 0 ? ms : 5, ordinal_order: ctx.opt('ordinalOrder', true) !== false, steps, group: ctx.byLabel || null };
  }

  function addStep(ctx, step) {
    const steps = stepsOf(ctx).slice();
    const last = steps[steps.length - 1];
    if (step.op === 'split' && !step.node && last && last.op === 'split' && !last.node) steps[steps.length - 1] = { ...last, n: (last.n || 1) + (step.n || 1) };
    else steps.push(step);
    ctx.set('steps', steps, scopeOf(ctx));
  }

  /* ---- the render's state: rows by leaf and node ------------------------------------------------------ */
  function state(ctx, res, base) {
    const a = res.assign;
    const nl = res.leaves.length;
    const S = { ctx, res, base, F: fns(ctx), cat: res.kind === 'categorical', cart: res.method === 'cart', by: new Map(res.nodes.map((nd) => [nd.path, nd])), plots: (res.fit && res.fit.plots) || {} };
    S.leafAll = Array.from({ length: nl }, () => []);
    S.leafTrain = Array.from({ length: nl }, () => []);
    S.leafIdx = Array.from({ length: nl }, () => []);
    for (let i = 0; i < a.rows.length; i++) {
      S.leafAll[a.leaf[i]].push(a.rows[i]);
      if (a.set[i] === 0) { S.leafTrain[a.leaf[i]].push(a.rows[i]); S.leafIdx[a.leaf[i]].push(i); }
    }
    S.rowsOf = (nd, train = false) => { const out = []; for (let l = nd.lo; l <= nd.hi; l++) out.push(...(train ? S.leafTrain[l] : S.leafAll[l])); return out; };
    // the node Candidates shows: the one picked, else the leaf the next split takes
    const picked = ctx.opt('candNode', null, scopeOf(ctx));
    S.cand = picked != null && S.by.has(picked) ? picked : nextLeaf(res);
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

  /* ======================================================================
     RENDER
     ====================================================================== */
  /* The page's display choices the graphs' code draws with (partition.fit's plot). */
  function plotOpts(ctx) {
    const o = (k, d) => ctx.opt(k, d) !== false;
    return { points: o('showPoints', true), stats: o('splitStats', true), bar: o('splitBar', true), prob: o('splitProb', true), count: o('splitCount', true) };
  }

  /* A graph's code block: the head of the tree's graphs (the table and the tree grown) and its own lines. */
  const blockOf = (ctx, S, key) => SM.predict.graphCode(ctx, S.plots.head_code, S.plots[key]);

  async function render(ctx) {
    const base = payloadOf(ctx);
    const F = fns(ctx);
    const res = await ctx.call(F.fit, { ...base, plot: plotOpts(ctx) });
    const S = state(ctx, res, base);
    ctx._part = S;
    const box = ctx.container;
    const o = (k, d) => ctx.opt(k, d);
    // the graph and the small tree view
    const top = [];
    if (o('showGraph', true)) top.push(SM.predict.withCode(partitionGraph(ctx, S), blockOf(ctx, S, 'partition')));
    if (o('smallTree', false)) top.push(SM.predict.withCode(treeBox(ctx, S, true), blockOf(ctx, S, 'small')));
    if (top.length) box.append(ctx.row(...top));
    box.append(buttons(ctx, S));
    box.append(summaryTable(ctx, S));
    const notes = [...(res.notes || []), ...((res.fit && res.fit.notes) || [])];
    if (notes.length) box.append(...notes.map((t) => (/was not done/.test(t) ? ctx.warn(t) : ctx.note(t))));
    if (o('showTree', true)) box.append(treeBox(ctx, S, false), blockOf(ctx, S, 'tree') || '');
    box.append(ctx.note(treeNote(S)));
    box.append(ctx.code(res.script));
    if (!ctx.headless) watchSelection(ctx, S);
    if (o('cands', true) && !S.cart) candidatesOutline(ctx, S);
    if (o('history', false)) historyOutline(ctx, S);
    if (o('leafReport', false)) leafOutline(ctx, S);
    if (o('contrib', false)) contributionsOutline(ctx, S);
    if (o('fitDetails', false)) wrapTables(SM.predict.measures(ctx, null, res.fit, { title: 'Fit Details' }));
    SM.predict.classification(ctx, null, res.fit, null, '', { save: { fn: F.save, payload: base } });
    if (!S.cat && o('abp', false)) SM.predict.actualByPredicted(ctx, null, res.fit);
    if (o('kfold', res.folds ? res.folds.k : null)) await kfoldOutline(ctx, S);
    if (o('profiler', false)) await SM.profiler.render(ctx, null, { sources: [{ fn: F.profile, payload: base }], option: 'profiler', note: 'The tree\'s prediction is a step function: it changes only where a split cuts the factor. Drag the red dashed line of a factor, click in its plot, or type its value.' });
  }

  function treeNote(S) {
    const { res } = S;
    const n = res.leaves.length;
    const parts = [`${res.splits} split${res.splits === 1 ? '' : 's'}, ${n} lea${n === 1 ? 'f' : 'ves'}; each split's side with the larger ${S.cat ? `rate of ${res.levels[0]}` : 'mean'} is on the left.`];
    if (S.cart) parts.push('CART (scikit-learn): each split the one with the largest decrease of the impurity, one level against the rest for a nominal X, cut halfway between two values; there is no LogWorth.');
    else parts.push(`Click a node to select its rows (Shift adds, ${navigator.platform && /Mac/.test(navigator.platform) ? '⌘' : 'Ctrl'} toggles); its red triangle has Split Here, Split Best, Split Specific and Prune Below.${S.cat ? ' Prob is the rate shrunk toward the parent node\'s, as JMP does, so it is never 0.' : ''}`);
    return parts.join(' ');
  }

  /* ---- Split, Prune, Go, Color Points -------------------------------------------------------------------- */
  function buttons(ctx, S) {
    const b = (text, title, fn, disabled = false) => {
      const x = el('button', { type: 'button', class: 'sm-btn small', text, title, disabled });
      x.addEventListener('click', fn);
      return x;
    };
    const split = b('Split', 'Split the leaf and column with the largest LogWorth (Shift-click: several splits)', async (ev) => {
      if (ev.shiftKey) {
        const v = await SM.ui.form({ title: 'Split', info: 'p:partition:tree', fields: [{ key: 'n', label: 'Number of splits', type: 'number', value: 5, help: HELP.splits }], validate: (x) => (x.n >= 1 && x.n <= 500 ? null : 'From 1 to 500 splits') });
        if (v) addStep(ctx, { op: 'split', n: Math.round(v.n) });
      } else addStep(ctx, { op: 'split' });
    });
    const prune = b('Prune', 'Take back the split with two leaves and the smallest LogWorth', () => addStep(ctx, { op: 'prune' }), !S.res.splits);
    const go = S.res.has_validation ? b('Go', 'Split until the validation RSquare has not improved for 10 splits, then keep the best tree', () => addStep(ctx, { op: 'go' }))
      : S.res.folds ? b('Go', `Split until the RSquare crossvalidated by the ${S.res.folds.k} folds of ${S.res.folds.column} has not improved for 10 splits, then keep the best tree`, () => addStep(ctx, { op: 'go' })) : null;
    const color = S.cat ? b('Color Points', 'Colour the rows by the response level', () => colorPoints(ctx, S)) : null;
    const info = typeof KvotInfo !== 'undefined' ? KvotInfo.slot('p:partition:tree') : null;
    return el('div', { class: 'sm-part-buttons', 'data-noexport': '' }, split, prune, go, color, info);
  }

  function colorPoints(ctx, S) {
    const a = S.res.assign;
    const by = S.res.levels.map(() => []);
    a.rows.forEach((r, i) => by[a.y[i]].push(r));
    by.forEach((rows, j) => ctx.table.setColor(rows, j % SM.util.PALETTE.length));
    SM.ui.toast(`Coloured the rows by ${S.res.y}`);
  }

  /* ---- the summary line --------------------------------------------------------------------------------- */
  function summaryTable(ctx, S) {
    const { res } = S;
    const sets = res.summary.length > 1;
    const cols = [sets ? { key: 'set', label: '', fmt: 'text' } : null,
      ...(S.cat ? [{ key: 'entropy_rsquare', label: 'Entropy RSquare', digits: 3 }, { key: 'misclassification', label: 'Misclassification Rate', digits: 4 }]
        : [{ key: 'rsquare', label: 'RSquare', digits: 3 }, { key: 'rase', label: 'RASE' }]),
      { key: 'n', label: 'N', fmt: 'int' }, { key: 'splits', label: 'Number of Splits', fmt: 'int' }, { key: 'aicc', label: 'AICc' }].filter(Boolean);
    return el('div', { class: 'sm-part-summary' }, ctx.rt({ columns: cols, rows: res.summary }, { key: 'summary', sortable: false, name: 'Partition Summary' }));
  }

  /* ======================================================================
     THE PARTITION GRAPH
     ====================================================================== */
  function partitionGraph(ctx, S) {
    const { res } = S;
    const a = res.assign;
    const nl = res.leaves.length;
    const counts = S.leafIdx.map((m) => m.length);
    const total = counts.reduce((x, y) => x + y, 0) || 1;
    const bands = [];
    let at = 0;
    for (const c of counts) { bands.push([at / total, (at + c) / total]); at += c; }
    const centers = bands.map(([lo, hi]) => (lo + hi) / 2);
    const showPoints = ctx.opt('showPoints', true);
    const traces = [];
    const shapes = bands.slice(1).map(([lo]) => ({ type: 'line', xref: 'x', yref: 'paper', x0: lo, x1: lo, y0: 0, y1: 1, line: { color: SM.util.themeColors().muted, width: 1, dash: 'dot' } }));
    const rng = SM.util.rng('partition graph');
    const hoverOf = (i, l) => `row ${a.rows[i] + 1}<br>leaf ${l + 1}: ${T(res.leaves[l].label)}`;
    if (!S.cat) {
      const xs = [], ys = [], rows = [], hov = [];
      S.leafIdx.forEach((m, l) => {
        const [lo, hi] = bands[l];
        m.forEach((i, k) => { xs.push(lo + ((k + 0.5) / m.length) * (hi - lo)); ys.push(a.y[i]); rows.push(a.rows[i]); hov.push(`${hoverOf(i, l)}<br>${T(res.y)} ${sig(a.y[i])}`); });
      });
      if (showPoints) traces.push({ type: rows.length > 4000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter', mode: 'markers', x: xs, y: ys, rows, marker: { size: rows.length > 1500 ? 3.5 : 5 }, hovertext: hov, hovertemplate: '%{hovertext}<extra></extra>', name: res.y });
      const lx = [], ly = [], lt = [];
      res.leaves.forEach((lf, l) => { lx.push(bands[l][0], bands[l][1], null); ly.push(lf.mean, lf.mean, null); lt.push(`leaf ${l + 1}: mean ${sig(lf.mean)}`, `leaf ${l + 1}: mean ${sig(lf.mean)}`, ''); });
      traces.push({ type: 'scatter', mode: 'lines', x: lx, y: ly, line: { color: fitColor(), width: 2 }, hovertext: lt, hovertemplate: '%{hovertext}<extra></extra>', name: 'Leaf means' });
    } else {
      // each leaf a band, the level rates stacked in it; the points jittered in their level's part
      const L = res.levels.length;
      const cum = res.leaves.map((lf) => { const c = [0]; for (let j = 0; j < L; j++) c.push(c[j] + lf.rates[j]); return c; });
      for (let j = 0; j < L; j++) {
        const rowsJ = S.leafIdx.map((m) => m.filter((i) => a.y[i] === j).map((i) => a.rows[i]));
        traces.push({
          type: 'bar', x: centers, y: res.leaves.map((lf) => lf.rates[j]), base: cum.map((c) => c[j]), width: bands.map(([lo, hi]) => Math.max(1e-6, hi - lo)),
          rows: rowsJ, rowsScale: res.leaves.map((lf, l) => (counts[l] ? 1 / counts[l] : 0)),
          marker: { color: SM.util.PALETTE[j % SM.util.PALETTE.length], opacity: showPoints ? 0.28 : 0.8, line: { width: 0 } }, name: T(res.levels[j]),
          hovertext: res.leaves.map((lf, l) => `leaf ${l + 1}: ${T(res.levels[j])} ${f4(lf.rates[j])}`), hovertemplate: '%{hovertext}<extra></extra>', showlegend: true,
        });
      }
      if (showPoints) {
        const xs = [], ys = [], rows = [], hov = [];
        S.leafIdx.forEach((m, l) => {
          const [lo, hi] = bands[l];
          m.forEach((i) => {
            const j = a.y[i];
            xs.push(lo + (0.08 + 0.84 * rng.u()) * (hi - lo));
            ys.push(cum[l][j] + (0.1 + 0.8 * rng.u()) * (cum[l][j + 1] - cum[l][j]));
            rows.push(a.rows[i]);
            hov.push(`${hoverOf(i, l)}<br>${T(res.y)} ${T(res.levels[j])}`);
          });
        });
        traces.push({ type: rows.length > 4000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter', mode: 'markers', x: xs, y: ys, rows, marker: { size: rows.length > 1500 ? 3 : 4.5 }, hovertext: hov, hovertemplate: '%{hovertext}<extra></extra>', name: 'Rows', showlegend: false });
      }
    }
    const ticks = nl <= 40 ? { tickvals: centers, ticktext: res.leaves.map((lf) => String(lf.number)) } : { showticklabels: false };
    return ctx.plot(traces, {
      showlegend: S.cat, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, shapes, bargap: 0,
      margin: { l: 56, r: 10, t: S.cat ? 26 : 8, b: 40 },
      xaxis: { range: [0, 1], showgrid: false, zeroline: false, title: { text: 'Leaves (the Leaf Report\'s numbers)' }, ...ticks },
      yaxis: S.cat ? { range: [0, 1], title: { text: `${res.y}: rate` } } : { title: { text: res.y }, zeroline: false },
    }, { width: W(560), height: 300, title: `Partition of ${res.y}` });
  }

  /* ======================================================================
     THE TREE: JMP's node boxes, drawn in SVG
     ====================================================================== */
  /* The tree's geometry: a box's width and each node's height. S.look (the
     Uplift platform's) may give its own geometry and node boxes. */
  function geometry(ctx, S, small) {
    if (S.look && S.look.geometry) return S.look.geometry(ctx, S, small);
    const o = (k, d) => ctx.opt(k, d);
    const G = { small, stats: o('splitStats', true), bar: o('splitBar', true), prob: o('splitProb', true), count: o('splitCount', true) };
    G.TITLE = small ? 17 : 20; G.ROW = small ? 12 : 14; G.GAP = small ? 8 : 14; G.VGAP = small ? 18 : 28; G.PAD = 6;
    G.L = S.cat ? S.res.levels.length : 0;
    if (small) G.BW = 118;
    else if (S.cat) {
      const longest = Math.max(5, ...S.res.levels.map((l) => String(l).length));
      G.levelW = Math.max(38, Math.min(96, Math.round(6.3 * longest)));
      G.barW = G.bar ? 38 : 0;
      G.numW = 46;
      G.cntW = G.count ? 42 : 0;
      G.BW = Math.max(184, 10 + G.levelW + G.barW + G.numW * (G.prob ? 2 : 1) + G.cntW);
    } else G.BW = 184;
    G.height = (nd) => {
      if (small) return G.TITLE + G.ROW + 5;
      let h = G.TITLE + G.PAD;
      if (S.cat) h += (G.stats ? G.ROW * (nd.split ? 3 : 2) : 0) + G.ROW * (G.L + 1);
      else h += G.ROW * (G.stats ? 3 + (nd.split ? 2 : 0) : 1);
      return h + 6;
    };
    return G;
  }

  const clip = (s, px, cw = 6.4) => { const n = Math.max(3, Math.floor(px / cw)); s = String(s); return s.length > n ? `${s.slice(0, n - 1)}…` : s; };

  function treeBox(ctx, S, small) {
    const { res } = S;
    const G = geometry(ctx, S, small);
    const depth = (nd) => nd.path.length;
    const D = Math.max(0, ...res.nodes.map(depth));
    const rowH = new Array(D + 1).fill(0);
    for (const nd of res.nodes) rowH[depth(nd)] = Math.max(rowH[depth(nd)], G.height(nd));
    const ys = [];
    let y = G.PAD;
    for (let d = 0; d <= D; d++) { ys.push(y); y += rowH[d] + G.VGAP; }
    const H = Math.ceil(y - G.VGAP + G.PAD);
    const nl = res.leaves.length;
    const Wd = Math.ceil(G.GAP + nl * (G.BW + G.GAP));
    const cx = (nd) => G.GAP + ((nd.lo + nd.hi) / 2) * (G.BW + G.GAP) + G.BW / 2;
    const s = svg('svg', { class: `sm-part-tree${small ? ' is-small' : ''}`, width: Wd, height: H, viewBox: `0 0 ${Wd} ${H}`, role: 'group', 'aria-label': small ? 'Small tree view' : (S.look && S.look.label) || 'Decision tree' });
    // the lines between parents and children
    const lines = svg('g', { class: 'sm-part-links' });
    for (const nd of res.nodes) {
      if (!nd.split) continue;
      const d = depth(nd);
      const x0 = cx(nd), y0 = ys[d] + G.height(nd), ym = ys[d] + rowH[d] + G.VGAP / 2;
      for (const p of nd.split.children) {
        const ch = S.by.get(p);
        lines.append(svg('path', { d: `M${x0} ${y0} V${ym} H${cx(ch)} V${ys[d + 1]}` }));
      }
    }
    s.append(lines);
    const groups = new Map();
    for (const nd of res.nodes) {
      const g = small ? smallNode(S, G, nd) : S.look && S.look.node ? S.look.node(S, G, nd) : nodeBox(S, G, nd);
      g.setAttribute('transform', `translate(${Math.round(cx(nd) - G.BW / 2)},${ys[depth(nd)]})`);
      wireNode(ctx, S, g, nd);
      groups.set(nd.path, g);
      s.append(g);
    }
    (S.groups || (S.groups = [])).push(groups);
    const wrap = el('div', { class: `sm-part-treebox${small ? ' is-small' : ''}`, role: 'region', 'aria-label': small ? 'Small tree view' : 'The tree', tabindex: '-1' }, s);
    if (!small) wrap.style.setProperty('--sm-part-h', `${H}px`);
    if (!ctx.headless) centre(wrap, cx(res.nodes[0]));
    return wrap;
  }

  /* A tree wider than its box opens scrolled to its root, once the box has
     its size (the report is built aside and put in place when it is done). */
  function centre(wrap, x) {
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => {
      if (!wrap.clientWidth) return;
      ro.disconnect();
      if (wrap.scrollWidth > wrap.clientWidth) wrap.scrollLeft = Math.max(0, Math.round(x - wrap.clientWidth / 2));
    });
    ro.observe(wrap);
  }

  function txt(cls, x, y, s, anchor = null) {
    return svg('text', { class: cls, x, y, 'text-anchor': anchor }, String(s));
  }

  /* A node's group with its box, heading, red triangle and condition. */
  function nodeFrame(S, G, nd, cls, aria) {
    const h = G.height(nd);
    const g = svg('g', { class: `sm-part-node${cls ? ` ${cls}` : ''}${nd.leaf ? ' is-leaf' : ''}${S.cand === nd.path ? ' is-picked' : ''}`, tabindex: '0', role: 'button', 'data-path': nd.path, 'aria-label': aria });
    g.append(svg('title', null, `${nd.label}${nd.leaf ? ` (leaf ${nd.number})` : ''}`));
    g.append(svg('rect', { class: 'sm-part-box', x: 0.5, y: 0.5, width: G.BW - 1, height: h - 1, rx: 3 }));
    g.append(svg('path', { class: 'sm-part-head', d: `M0.5 ${G.TITLE} V3.5 Q0.5 0.5 3.5 0.5 H${G.BW - 3.5} Q${G.BW - 0.5} 0.5 ${G.BW - 0.5} 3.5 V${G.TITLE} Z` }));
    const tri = svg('g', { class: 'sm-part-menu', role: 'button', 'aria-label': `Options for ${nd.label}` }, svg('rect', { x: 2, y: 2, width: 15, height: G.TITLE - 4, fill: 'transparent' }), svg('path', { class: 'sm-part-tri', d: `M5 ${G.TITLE / 2 - 3} L13 ${G.TITLE / 2 - 3} L9 ${G.TITLE / 2 + 3} Z` }));
    g.append(tri);
    g.append(txt('sm-part-title', 18, G.TITLE - 6, clip(nd.label, G.BW - 24, 7.1)));
    return g;
  }

  /* The foot of a node's box: the share of its training rows selected. */
  const selBar = (G, nd) => svg('rect', { class: 'sm-part-sel', x: 1, y: G.height(nd) - 4, width: 0, height: 3 });

  function nodeBox(S, G, nd) {
    const { res } = S;
    const h = G.height(nd);
    const g = nodeFrame(S, G, nd, '', `${nd.label}: count ${fmt(nd.count)}${S.cat ? '' : `, mean ${sig(nd.mean)}`}${nd.split ? `, split by ${nd.split.column}` : ''}`);
    let y = G.TITLE + G.PAD + G.ROW - 3;
    const kv = (k, v) => { g.append(txt('sm-part-k', 7, y, k), txt('sm-part-v', G.BW - 7, y, v, 'end')); y += G.ROW; };
    if (!S.cat) {
      if (G.stats) {
        kv('Count', fmt(nd.count)); kv('Mean', sig(nd.mean)); kv('Std Dev', nd.sd == null ? '.' : sig(nd.sd));
        if (nd.split) { kv(S.cart ? 'SS' : 'LogWorth', S.cart ? sig(nd.split.stat) : sig(nd.split.logworth)); kv('Difference', sig(nd.split.difference)); }
      } else kv('Mean', sig(nd.mean));
    } else {
      if (G.stats) {
        kv('Count', fmt(nd.count)); kv('G^2', sig(nd.g2));
        if (nd.split) kv(S.cart ? 'Split G^2' : 'LogWorth', S.cart ? sig(nd.split.stat) : sig(nd.split.logworth));
      }
      // the level table: Level, a bar, Rate, Prob, Count
      let x = 7 + G.levelW;
      const xBar = x; if (G.bar) x += G.barW;
      const xRate = x + G.numW - 4; x += G.numW;
      const xProb = G.prob ? x + G.numW - 4 : null; if (G.prob) x += G.numW;
      const xCnt = G.count ? x + G.cntW - 4 : null;
      g.append(txt('sm-part-h', 7, y, 'Level'), txt('sm-part-h', xRate, y, 'Rate', 'end'));
      if (G.prob) g.append(txt('sm-part-h', xProb, y, 'Prob', 'end'));
      if (G.count) g.append(txt('sm-part-h', xCnt, y, 'Count', 'end'));
      y += G.ROW;
      res.levels.forEach((lv, j) => {
        g.append(txt('sm-part-k', 7, y, clip(lv, G.levelW - 4)));
        if (G.bar) {
          g.append(svg('rect', { class: 'sm-part-track', x: xBar, y: y - 8, width: G.barW - 6, height: 8 }));
          g.append(svg('rect', { class: 'sm-part-rate', x: xBar, y: y - 8, width: Math.max(0, (G.barW - 6) * nd.rates[j]), height: 8, fill: SM.util.PALETTE[j % SM.util.PALETTE.length] }));
        }
        g.append(txt('sm-part-v', xRate, y, f4(nd.rates[j]), 'end'));
        if (G.prob) g.append(txt('sm-part-v', xProb, y, f4(nd.probs[j]), 'end'));
        if (G.count) g.append(txt('sm-part-v', xCnt, y, fmt(Math.round(nd.counts[j] * 1000) / 1000), 'end'));
        y += G.ROW;
      });
    }
    g.append(svg('rect', { class: 'sm-part-sel', x: 1, y: h - 4, width: 0, height: 3 }));
    return g;
  }

  function smallNode(S, G, nd) {
    const h = G.height(nd);
    const g = svg('g', { class: `sm-part-node is-small${nd.leaf ? ' is-leaf' : ''}`, tabindex: '0', role: 'button', 'data-path': nd.path, 'aria-label': `${nd.label}: count ${fmt(nd.count)}` });
    g.append(svg('title', null, nd.label));
    g.append(svg('rect', { class: 'sm-part-box', x: 0.5, y: 0.5, width: G.BW - 1, height: h - 1, rx: 3 }));
    g.append(txt('sm-part-title', 5, G.TITLE - 5, clip(nd.label, G.BW - 8, 6.2)));
    // the most likely level and its probability, or the mean
    let right = sig(nd.mean, 4);
    if (S.cat) { const j = nd.probs.indexOf(Math.max(...nd.probs)); right = `${clip(S.res.levels[j], 36, 5.6)} ${nd.probs[j].toFixed(3)}`; }
    g.append(txt('sm-part-k', 5, G.TITLE + G.ROW - 2, `${fmt(nd.count)} rows`), txt('sm-part-v', G.BW - 5, G.TITLE + G.ROW - 2, right, 'end'));
    g.append(svg('rect', { class: 'sm-part-sel', x: 1, y: h - 4, width: 0, height: 3 }));
    return g;
  }

  /* A click on a node selects its rows; its red triangle (or a right click)
     opens its menu; Enter selects, the context-menu key opens the menu. */
  function wireNode(ctx, S, g, nd) {
    const select = (ev) => {
      if (ctx.headless) return;
      const rows = S.rowsOf(nd);
      const mode = ev && ev.shiftKey ? 'add' : ev && (ev.metaKey || ev.ctrlKey) ? 'toggle' : 'replace';
      ctx.table.select(rows, mode);
      pickNode(ctx, S, nd.path);
    };
    const menu = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const r = g.getBoundingClientRect();
      SM.ui.menu(nodeMenu(ctx, S, nd), ev.clientX != null && ev.type !== 'keydown' ? { x: ev.clientX, y: ev.clientY } : { x: r.left, y: r.bottom }, { returnFocus: g });
    };
    g.addEventListener('click', (ev) => { if (ev.target.closest && ev.target.closest('.sm-part-menu')) menu(ev); else select(ev); });
    g.addEventListener('contextmenu', menu);
    g.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); select(ev); } else if (ev.key === 'ContextMenu' || (ev.key === 'F10' && ev.shiftKey)) menu(ev);
    });
  }

  function nodeMenu(ctx, S, nd) {
    const items = [{ head: nd.label }];
    if (!S.cart) {
      const best = (nd.cands || []).find((c) => c.best);
      items.push(
        { label: 'Split Here', disabled: !nd.leaf || !best, action: () => addStep(ctx, { op: 'here', node: nd.path }) },
        { label: 'Split Best', disabled: !S.res.nodes.some((x) => x.leaf && x.lo >= nd.lo && x.hi <= nd.hi && (x.cands || []).some((c) => c.best)), action: () => addStep(ctx, { op: 'split', node: nd.path }) },
        { label: 'Split Specific…', disabled: !nd.leaf, action: () => splitSpecific(ctx, S, nd) },
        { label: 'Prune Below', disabled: nd.leaf, action: () => addStep(ctx, { op: 'below', node: nd.path }) },
        { label: 'Prune Worst', disabled: nd.leaf, action: () => addStep(ctx, { op: 'prune', node: nd.path }) },
        { separator: true },
      );
    }
    items.push({ label: 'Select Rows', action: () => { ctx.table.select(S.rowsOf(nd)); pickNode(ctx, S, nd.path); } });
    if (!S.cart) items.push({ label: 'Show Candidates', action: () => pickNode(ctx, S, nd.path, true) });
    return items;
  }

  async function splitSpecific(ctx, S, nd) {
    const xs = ctx.roles('x');
    const cont = new Set(S.res.columns.filter((c) => c.kind === 'continuous').map((c) => c.name));
    const best = (nd.cands || []).find((c) => c.best);
    const first = (best && xs.find((c) => c.name === best.column)) || xs[0];
    const v = await SM.ui.form({
      title: `Split Specific: ${nd.label}`, info: 'p:partition:tree',
      lead: 'Split this leaf by a column of your choice: at its best cut, or at a value you give (a continuous column). The other rows of the tree stay as they are.',
      fields: [
        { key: 'col', label: 'Column', type: 'select', value: first ? first.id : '', choices: xs.map((c) => [c.id, `${c.name}${cont.has(c.name) ? '' : ' (levels grouped)'}`]), help: HELP.specificColumn },
        { key: 'cut', label: 'Cut value (a continuous column; empty: the best cut)', type: 'number', value: null, help: HELP.specificCut },
      ],
      validate: (x) => (x.cut != null && !Number.isFinite(x.cut) ? 'The cut value is a number' : null),
    });
    if (!v) return;
    const col = ctx.col(v.col);
    const step = { op: 'specific', node: nd.path, col: v.col };
    if (v.cut != null && col && cont.has(col.name)) step.cut = v.cut;
    addStep(ctx, step);
  }

  /* The node Candidates shows (and the one drawn picked), without a redraw. */
  function pickNode(ctx, S, path, open = false) {
    if (ctx.headless) return;
    ctx.set('candNode', path, scopeOf(ctx), { rerun: false });
    S.cand = path;
    for (const groups of S.groups || []) for (const [p, g] of groups) g.classList.toggle('is-picked', p === path);
    if (S.fillCands) S.fillCands();
    if (open && S.candOutline) { S.candOutline.setOpen(true); S.candOutline.el.scrollIntoView({ block: 'nearest' }); }
  }

  /* Rows selected anywhere show as an orange bar along each node's foot: the
     share of its training rows selected. */
  function watchSelection(ctx, S) {
    const t = ctx.table;
    const apply = () => {
      const st = t.state;
      const sel = S.leafTrain.map((rows) => { let k = 0; for (const r of rows) if (st[r] & 1) k++; return k; });
      const tot = S.leafTrain.map((rows) => rows.length);
      for (const groups of S.groups || []) {
        for (const [p, g] of groups) {
          const nd = S.by.get(p);
          let a = 0, b = 0;
          for (let l = nd.lo; l <= nd.hi; l++) { a += sel[l]; b += tot[l]; }
          const bar = g.querySelector('.sm-part-sel');
          const box = g.querySelector('.sm-part-box');
          if (bar && box) bar.setAttribute('width', String(b ? Math.max(0, (Number(box.getAttribute('width')) - 1) * (a / b)) : 0));
        }
      }
    };
    let off = null;
    off = t.on('rowstate', () => {
      const alive = (S.groups || []).some((groups) => [...groups.values()].some((g) => g.isConnected));
      if (!alive && ctx.report.body && !ctx.report.body.classList.contains('is-running')) { off(); return; }
      apply();
    });
    requestAnimationFrame(apply);
  }

  /* ======================================================================
     CANDIDATES
     ====================================================================== */
  function candidatesOutline(ctx, S) {
    const ob = ctx.outline('Candidates', { key: 'cands', info: 'p:partition:cands', menu: () => [
      ctx.check('Sort Split Candidates', 'sortCands', null, false),
      { label: 'Remove', action: () => ctx.set('cands', false) },
    ] });
    S.candOutline = ob;
    const host = el('div');
    ob.add(host);
    S.fillCands = () => {
      const nd = S.by.get(S.cand) || S.by.get('');
      const rows = (nd.cands || []).map((c) => ({ ...c, mark: nd.split ? (c.column === nd.split.column ? '✓' : '') : (c.best ? '✓' : '') }));
      if (ctx.opt('sortCands', false)) rows.sort((a, b) => (b.logworth ?? -1) - (a.logworth ?? -1));
      const what = nd.split ? `split by ${nd.split.column} (✓)` : S.cand === nextLeaf(S.res) && (nd.cands || []).some((c) => c.best) ? 'the leaf the next Split takes; ✓ its best column' : 'a leaf; ✓ its best column';
      host.replaceChildren(
        // Term names a row (Bootstrap finds rows by their text columns); the conditions change with the rows
        wide(ctx.rt({ columns: [{ key: 'mark', label: '', fmt: 'cond', left: true }, { key: 'column', label: 'Term', fmt: 'text' }, { key: 'stat', label: S.cat ? 'Candidate G^2' : 'Candidate SS' }, { key: 'logworth', label: 'LogWorth', digits: 4 }, { key: 'split', label: 'Split', fmt: 'cond', left: true }, { key: 'other', label: 'Other Side', fmt: 'cond', left: true, hidden: true }], rows },
          { key: 'cands', caption: `${nd.label} (${fmt(nd.count)} rows): ${what}`, sortable: true, cellClass: (r) => (r.mark ? 'sm-part-best' : '') })),
        ctx.note(`For each column its best split of this node (a click on a node shows its candidates): ${S.cat ? 'G², the likelihood-ratio chi-square of the split' : 'SS, the sum of squares the split explains'}, and LogWorth, −log10 of its p-value adjusted for the number of ways the column can be cut. A column with no split has none that leaves ${fmt(S.res.minsize)} rows on each side.`));
    };
    S.fillCands();
  }

  /* ======================================================================
     SPLIT HISTORY
     ====================================================================== */
  /* yTitle: what the RSquare is called (the Uplift's is the regression's RSquare, whatever its response). */
  function historyOutline(ctx, S, yTitle = null, info = 'p:partition:history') {
    const { res } = S;
    const ob = ctx.outline('Split History', { key: 'history', info, menu: () => [{ label: 'Remove', action: () => ctx.set('history', false) }] });
    const sets = SETS.filter((s) => res.history.some((h) => h[s] != null));
    const traces = sets.map((s) => ({ type: 'scatter', mode: 'lines+markers', x: res.history.map((h) => h.splits), y: res.history.map((h) => h[s]), name: s, line: { color: setColor(s), width: 1.8 }, marker: { size: 5, color: setColor(s) }, hovertemplate: `${s}: %{x} splits, RSquare %{y:.4f}<extra></extra>` }));
    const shapes = [];
    const cv = res.go && res.go.trace.some((e) => e.Crossvalidation != null);
    if (cv) {
      // Go by the folds of a K-fold Validation column: the crossvalidated RSquare of each size it looked at
      const upto = res.go.trace.filter((e) => e.splits <= res.go.best), after = res.go.trace.filter((e) => e.splits >= res.go.best);
      traces.push({ type: 'scatter', mode: 'lines+markers', x: upto.map((e) => e.splits), y: upto.map((e) => e.Crossvalidation), name: 'Crossvalidation', line: { color: setColor('Validation'), width: 1.8 }, marker: { size: 5, color: setColor('Validation') }, hovertemplate: 'Crossvalidation: %{x} splits, RSquare %{y:.4f}<extra></extra>' });
      if (after.length > 1) traces.push({ type: 'scatter', mode: 'lines+markers', x: after.map((e) => e.splits), y: after.map((e) => e.Crossvalidation), line: { color: setColor('Validation'), width: 1.2, dash: 'dot' }, marker: { size: 4, color: setColor('Validation'), symbol: 'circle-open' }, showlegend: false, hovertemplate: 'Crossvalidation, looked at by Go: %{x} splits, RSquare %{y:.4f}<extra></extra>' });
    }
    if (res.go) {
      const after = res.go.trace.filter((e) => e.splits > res.go.best);
      for (const s of sets) if (after.length) traces.push({ type: 'scatter', mode: 'lines+markers', x: [res.go.best, ...after.map((e) => e.splits)], y: [res.go.trace.find((e) => e.splits === res.go.best)?.[s] ?? null, ...after.map((e) => e[s])], line: { color: setColor(s), width: 1.2, dash: 'dot' }, marker: { size: 4, color: setColor(s), symbol: 'circle-open' }, showlegend: false, hovertemplate: `${s}, looked at by Go: %{x} splits, RSquare %{y:.4f}<extra></extra>` });
      shapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: res.go.best, x1: res.go.best, y0: 0, y1: 1, line: { color: SM.util.themeColors().muted, width: 1, dash: 'dash' } });
    }
    const legend = sets.length > 1 || cv;
    const rsq = SM.predict.withCode(ctx.plot(traces, { showlegend: legend, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, shapes, margin: { l: 56, r: 12, t: legend ? 26 : 8, b: 42 }, xaxis: { title: { text: 'Number of Splits' }, rangemode: 'tozero' }, yaxis: { title: { text: yTitle || (S.cat ? 'Entropy RSquare' : 'RSquare') } } }, { width: W(460), height: 280, title: 'Split history', select: false }), blockOf(ctx, S, 'history'));
    ob.add(ctx.row(rsq, aiccGraph(ctx, S)),
      ctx.note(`${yTitle || (S.cat ? 'The entropy RSquare' : 'RSquare')} of each set after each split of the tree, in the order the splits were made, and the training rows' AICc (the smallest marked).${res.go ? ` Go looked ${res.go.trace.length - 1} splits past ${res.go.start} (dotted) and kept ${res.go.best}, the best ${cv ? `RSquare crossvalidated by the ${res.go.folds} folds (each fold predicted by a tree grown on the others, split for split)` : 'validation RSquare'}: the next 10 splits did not beat it.` : ''}${sets.length > 1 ? ' A validation curve that turns down while the training curve still rises is the tree learning noise.' : ' Without validation rows, the smallest AICc is one guide to how many splits the data support.'}`));
    // the numbers of the graphs: a line per number of splits
    const hcols = [{ key: 'splits', label: 'Number of Splits', fmt: 'int' }, ...sets.map((s) => ({ key: s, label: `${s} ${yTitle || (S.cat ? 'Entropy RSquare' : 'RSquare')}`, digits: 4 })), { key: 'aicc', label: 'AICc' }];
    const det = ctx.outline('Split History Details', { parent: ob, key: 'historyDetails', closed: true });
    det.add(wide(ctx.rt({ columns: hcols, rows: res.history }, { key: 'history', sortable: false, maxRows: 400, cellClass: (r, c) => (c.key === 'aicc' && r.aicc != null && r.aicc === minAicc(res.history) ? 'sm-part-best' : '') })));
  }

  const minAicc = (hist) => hist.reduce((m, h) => (h.aicc != null && Number.isFinite(h.aicc) && (m == null || h.aicc < m) ? h.aicc : m), null);

  /* AICc by the number of splits: the training rows', the smallest marked. */
  function aiccGraph(ctx, S) {
    const hist = S.res.history.filter((h) => h.aicc != null && Number.isFinite(h.aicc));
    if (!hist.length) return null;
    const best = minAicc(hist);
    const at = hist.find((h) => h.aicc === best);
    const traces = [{ type: 'scatter', mode: 'lines+markers', x: hist.map((h) => h.splits), y: hist.map((h) => h.aicc), name: 'AICc', line: { color: SM.report.BASE, width: 1.8 }, marker: { size: 5, color: SM.report.BASE }, hovertemplate: '%{x} splits: AICc %{y:.6g}<extra></extra>', showlegend: false },
      { type: 'scatter', mode: 'markers', x: [at.splits], y: [at.aicc], marker: { size: 10, symbol: 'diamond', color: fitColor() }, hovertemplate: `the smallest AICc: ${at.splits} splits<extra></extra>`, showlegend: false }];
    return SM.predict.withCode(ctx.plot(traces, { margin: { l: 64, r: 12, t: 8, b: 42 }, xaxis: { title: { text: 'Number of Splits' }, rangemode: 'tozero' }, yaxis: { title: { text: 'AICc' } } }, { width: W(460), height: 260, title: 'AICc by number of splits', select: false }), blockOf(ctx, S, 'aicc'));
  }

  /* ======================================================================
     LEAF REPORT
     ====================================================================== */
  function leafOutline(ctx, S) {
    const { res } = S;
    const ob = ctx.outline('Leaf Report', { key: 'leaves', info: 'p:partition:leaves', menu: () => [{ label: 'Remove', action: () => ctx.set('leafReport', false) }] });
    const nl = res.leaves.length;
    const labels = res.leaves.map((lf) => `${lf.number}`);
    const h = Math.max(160, Math.min(560, 48 + 22 * nl));
    if (!S.cat) {
      const rows = res.leaves.map((lf) => ({ leaf: lf.number, label: lf.label, rule: lf.rule || lf.label, mean: lf.mean, sd: lf.sd, count: lf.count }));
      const t = ctx.rt({ columns: [{ key: 'leaf', label: 'Leaf', fmt: 'int' }, { key: 'label', label: 'Leaf Label', fmt: 'text' }, RULE, { key: 'mean', label: 'Mean' }, { key: 'sd', label: 'Std Dev', hidden: true }, { key: 'count', label: 'Count', fmt: 'int' }], rows }, { key: 'leafreport', caption: 'Response Means' });
      const bars = ctx.plot([{ type: 'bar', orientation: 'h', y: labels, x: res.leaves.map((lf) => lf.mean), rows: S.leafTrain, rowsScale: res.leaves.map((lf, l) => (S.leafTrain[l].length ? lf.mean / S.leafTrain[l].length : 0)), marker: { color: SM.report.BAR }, hovertext: res.leaves.map((lf) => `leaf ${lf.number}: ${T(lf.label)}<br>mean ${sig(lf.mean)}, ${fmt(lf.count)} rows`), hovertemplate: '%{hovertext}<extra></extra>' }],
        { margin: { l: 44, r: 12, t: 6, b: 38 }, xaxis: { title: { text: `Mean ${res.y}` }, zeroline: true }, yaxis: { type: 'category', autorange: 'reversed', title: { text: 'Leaf' } }, bargap: 0.25 }, { width: W(320), height: h, title: 'Leaf means', select: false });
      ob.add(ctx.row(el('div', { class: 'sm-part-scroll' }, t), SM.predict.withCode(bars, blockOf(ctx, S, 'leaves'))));
    } else {
      const L = res.levels.length;
      const pcols = [{ key: 'leaf', label: 'Leaf', fmt: 'int' }, { key: 'label', label: 'Leaf Label', fmt: 'text' }, RULE, ...res.levels.map((lv, j) => ({ key: `p${j}`, label: `Prob(${lv})`, digits: 4 }))];
      const prows = res.leaves.map((lf) => ({ leaf: lf.number, label: lf.label, rule: lf.rule || lf.label, ...Object.fromEntries(lf.probs.map((p, j) => [`p${j}`, p])) }));
      const ccols = [{ key: 'leaf', label: 'Leaf', fmt: 'int' }, { key: 'label', label: 'Leaf Label', fmt: 'text' }, ...res.levels.map((lv, j) => ({ key: `c${j}`, label: String(lv) })), { key: 'count', label: 'Count' }];
      const crows = res.leaves.map((lf) => ({ leaf: lf.number, label: lf.label, count: lf.count, ...Object.fromEntries(lf.counts.map((c, j) => [`c${j}`, c])) }));
      const a = res.assign;
      const traces = [];
      for (let j = 0; j < L; j++) {
        const cum = res.leaves.map((lf) => lf.probs.slice(0, j).reduce((x, y) => x + y, 0));
        const rowsJ = S.leafIdx.map((m) => m.filter((i) => a.y[i] === j).map((i) => a.rows[i]));
        traces.push({ type: 'bar', orientation: 'h', y: labels, x: res.leaves.map((lf) => lf.probs[j]), base: cum, rows: rowsJ, rowsScale: res.leaves.map((lf, l) => (rowsJ[l].length ? lf.probs[j] / rowsJ[l].length : 0)), name: T(lv(res, j)), marker: { color: SM.util.PALETTE[j % SM.util.PALETTE.length] }, hovertext: res.leaves.map((lf) => `leaf ${lf.number}: ${T(lf.label)}<br>Prob(${T(lv(res, j))}) ${f4(lf.probs[j])}`), hovertemplate: '%{hovertext}<extra></extra>' });
      }
      const bars = ctx.plot(traces, { showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, margin: { l: 44, r: 12, t: 26, b: 38 }, xaxis: { title: { text: 'Prob' }, range: [0, 1] }, yaxis: { type: 'category', autorange: 'reversed', title: { text: 'Leaf' } }, bargap: 0.25 }, { width: W(340), height: h + 20, title: 'Leaf probabilities', select: false });
      ob.add(ctx.row(el('div', { class: 'sm-part-scroll' }, ctx.rt({ columns: pcols, rows: prows }, { key: 'leafprob', caption: 'Response Prob' })), SM.predict.withCode(bars, blockOf(ctx, S, 'leaves'))),
        el('div', { class: 'sm-part-scroll' }, ctx.rt({ columns: ccols, rows: crows }, { key: 'leafcount', caption: 'Response Counts' })));
    }
    ob.add(ctx.note(`The leaves from left to right, numbered as Save Leaf Numbers numbers them; the label is the path of conditions from the root (Save Leaf Labels), the rule the same conditions with those on one column merged (a range of a continuous column, the levels a categorical one's groups share). ${S.cat ? 'Prob is the smoothed probability the tree predicts; the counts are the training rows (by weight).' : 'The mean is the tree\'s prediction for the leaf\'s rows.'} A bar selects the leaf's training rows.`));
  }
  const lv = (res, j) => String(res.levels[j]);
  /* The Leaf Report's rule: the Leaf Label with the conditions on one column merged (not in JMP). */
  const RULE = { key: 'rule', label: 'Rule', fmt: 'text' };

  /* ======================================================================
     COLUMN CONTRIBUTIONS
     ====================================================================== */
  function contributionsOutline(ctx, S) {
    const c = S.res.contributions;
    const splits = c.rows.map((r) => `${r.column} ${r.splits}`).join(', ');
    SM.predict.contributions(ctx, null, c, { head: S.plots.head_code, note: `Number of Splits: ${splits}. ${S.cat ? 'G^2' : 'SS'} is the sum over the column's splits of what each explains; the portion is its share of the total.` });
  }

  /* ======================================================================
     K FOLD CROSSVALIDATION
     ====================================================================== */
  async function kfoldDialog(ctx, S = ctx._part) {
    // a K-fold Validation column gives the folds: nothing to ask, the outline goes on or off
    if (S && S.res && S.res.folds) { ctx.set('kfold', ctx.opt('kfold', S.res.folds.k) ? false : S.res.folds.k); return; }
    const v = await SM.ui.form({ title: 'K Fold Crossvalidation', info: 'p:partition:kfold', lead: 'The training rows are split into k folds drawn from the report\'s seed; each fold is predicted by a tree with as many best splits as this one, grown on the other folds.', fields: [{ key: 'k', label: 'Number of folds (k)', type: 'number', value: ctx.opt('kfold', null) || 5, help: HELP.folds }], validate: (x) => (Number.isInteger(x.k) && x.k >= 2 && x.k <= 100 ? null : 'k is a whole number from 2 to 100') });
    if (v) ctx.set('kfold', v.k);
  }

  async function kfoldOutline(ctx, S) {
    const byColumn = S.res.folds;
    const k = byColumn ? byColumn.k : ctx.opt('kfold', null);
    const ob = ctx.outline('Crossvalidation', { key: 'kfold', info: 'p:partition:kfold', menu: () => [byColumn ? null : { label: 'Number of Folds…', action: () => kfoldDialog(ctx, S) }, { label: 'Remove', action: () => ctx.set('kfold', false) }].filter(Boolean) });
    let r;
    try { r = await ctx.call(S.F.kfold, { ...S.base, k }); } catch (e) { ob.add(ctx.error(e)); return; }
    const src = (m, what) => (S.cat ? { source: what, k: what.startsWith('K') ? r.k : null, entropy_rsquare: m.entropy_rsquare, misclassification: m.misclassification, neg_loglik: m.neg_loglik, n: m.n }
      : { source: what, k: what.startsWith('K') ? r.k : null, rsquare: m.rsquare, rase: m.rase, sse: m.sse, n: m.n });
    const cols = [{ key: 'source', label: 'Source', fmt: 'text' }, { key: 'k', label: 'k', fmt: 'int' },
      ...(S.cat ? [{ key: 'entropy_rsquare', label: 'Entropy RSquare', digits: 4 }, { key: 'misclassification', label: 'Misclassification Rate', digits: 4 }, { key: 'neg_loglik', label: '-LogLikelihood' }]
        : [{ key: 'rsquare', label: 'RSquare', digits: 4 }, { key: 'rase', label: 'RASE' }, { key: 'sse', label: 'SSE' }]), { key: 'n', label: 'N' }];
    ob.add(wide(ctx.rt({ columns: cols, rows: [src(r.folded, 'K Fold'), src(r.overall, 'Overall')] }, { key: 'kfold', sortable: false })),
      wide(ctx.rt({ columns: [{ key: 'fold', label: 'Fold', fmt: 'int' }, ...(r.by_column ? [{ key: 'value', label: r.by_column, fmt: 'text' }] : []), { key: 'n', label: 'N', fmt: 'int' }, { key: 'splits', label: 'Splits', fmt: 'int' }, { key: 'rsquare', label: S.cat ? 'Entropy RSquare' : 'RSquare', digits: 4 }], rows: r.folds }, { key: 'folds', caption: 'Each Fold', sortable: false })),
      ctx.note(r.by_column ? `K Fold: each row predicted by the tree grown without its fold, the ${r.k} folds of the Validation column ${r.by_column} (${r.k} trees of the best ${r.splits} splits each${S.cart ? ', CART' : ''}); Overall: this tree, grown on every row. A K Fold RSquare well below the overall one means the tree is larger than the data support; Go chooses the size by it.`
        : `K Fold: each training row predicted by the tree grown without its fold (${r.k} trees of the best ${r.splits} splits each${S.cart ? ', CART' : ''}); Overall: this tree on its own training rows. A K Fold RSquare well below the overall one means the tree is larger than the data support.`),
      ctx.code(r.script));
  }

  /* ======================================================================
     SAVE COLUMNS, MINIMUM SIZE SPLIT, THE RED TRIANGLE
     ====================================================================== */
  function saveItems(ctx, S) {
    if (!S) return [];
    const base = SM.predict.saveItems(ctx, S.F.save, S.base, S.res.fit)[0];
    const leaves = async (what) => {
      try {
        const r = await ctx.call(S.F.leaves, S.base);
        const notes = `the leaf of each row in ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`;
        if (what === 'numbers') ctx.saveColumn('Leaf Number', { rows: r.rows, values: r.numbers }, { notes, modelingType: 'nominal' });
        else ctx.saveColumn('Leaf Label', { rows: r.rows, values: r.labels }, { notes, dataType: 'character' });
      } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
    };
    const noFormula = S.cart ? 'the Decision Tree method (CART\'s tree is scikit-learn\'s)' : null;
    const formula = (what) => ({ label: { prediction: 'Save Prediction Formula', leaf_number: 'Save Leaf Number Formula', leaf_label: 'Save Leaf Label Formula' }[what], disabled: !!noFormula,
      title: noFormula ? `Needs ${noFormula}` : null, action: () => saveFormulas(ctx, 'partition.formula', { ...S.base, what }) });
    return [{ label: 'Save Columns', submenu: () => [...(typeof base.submenu === 'function' ? base.submenu() : base.submenu), { label: 'Save Leaf Numbers', action: () => leaves('numbers') }, { label: 'Save Leaf Labels', action: () => leaves('labels') },
      { separator: true }, formula('prediction'), formula('leaf_number'), formula('leaf_label')] }];
  }

  /* A Most Likely column's formula from the probability columns' names (in
     the levels' order): the first level whose probability is at least every
     later one's, as the largest probability, the first of equal ones. */
  function mostLikelyExpr(names, levels) {
    const refs = names.map((n) => SM.formula.refText(n));
    const lit = (v) => `"${String(v).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
    const arms = [];
    for (let i = 0; i < refs.length - 1; i++) arms.push(refs.slice(i + 1).map((r) => `${refs[i]} >= ${r}`).join(' & '), lit(levels[i]));
    return `If(${[...arms, lit(levels[levels.length - 1])].join(', ')})`;
  }

  /* Save a platform's formula columns: fn returns { columns: [{ name, expr }], and for a categorical response
     levels, most_name, ordinal } (the Prob[] columns, then the Most Likely column made from them here). */
  async function saveFormulas(ctx, fn, payload) {
    const from = { notes: `a formula from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}` };
    try {
      const r = await ctx.call(fn, payload);
      if (r.error) throw new Error(r.error);
      const made = [];
      for (const c of r.columns) {
        const col = ctx.saveFormula(c.name, c.expr, { ...from, ...(c.kind === 'leaf_number' || r.kind === 'leaf_number' ? { modelingType: 'nominal' } : {}) });
        if (col) made.push(col.name);
      }
      if (r.kind === 'categorical' && made.length === r.columns.length && r.levels && r.levels.length > 1) {
        ctx.saveFormula(r.most_name, mostLikelyExpr(made, r.levels), { ...from, modelingType: r.ordinal ? 'ordinal' : 'nominal', valueOrder: r.levels.slice() });
      }
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  async function minSizeDialog(ctx) {
    // no info: the platform's topic already lists this option; the form's (i) is its field
    const v = await SM.ui.form({ title: 'Minimum Size Split', lead: 'The fewest rows (by Freq) either side of a split may have: a number of rows, or below 1 a share of the training rows. JMP\'s default is 5.', fields: [{ key: 'm', label: 'Minimum size', type: 'number', value: ctx.opt('minsize', 5), help: HELP.minsize }], validate: (x) => (x.m > 0 ? null : 'A positive number') });
    if (v) ctx.set('minsize', v.m);
  }

  function topMenu(ctx) {
    const S = ctx._part;
    const cat = S ? S.cat : ctx.roles('y').some((c) => c.isCategorical);
    const cart = isCart(ctx);
    return [
      { label: 'Display Options', submenu: () => [
        ctx.check('Show Points', 'showPoints', null, true), ctx.check('Show Tree', 'showTree', null, true), ctx.check('Show Graph', 'showGraph', null, true),
        cat ? ctx.check('Show Split Bar', 'splitBar', null, true) : null, ctx.check('Show Split Stats', 'splitStats', null, true),
        cat ? ctx.check('Show Split Prob', 'splitProb', null, true) : null, cat ? ctx.check('Show Split Count', 'splitCount', null, true) : null,
        ctx.check('Show Split Candidates', 'cands', null, true, { disabled: cart }), ctx.check('Sort Split Candidates', 'sortCands', null, false, { disabled: cart }),
      ].filter(Boolean) },
      { label: 'Split Best', action: () => addStep(ctx, { op: 'split' }) },
      { label: 'Prune Worst', disabled: !S || !S.res.splits, action: () => addStep(ctx, { op: 'prune' }) },
      { label: 'Minimum Size Split…', action: () => minSizeDialog(ctx) },
      { separator: true },
      cat ? null : ctx.check('Plot Actual by Predicted', 'abp', null, false),
      ctx.check('Small Tree View', 'smallTree', null, false),
      ctx.check('Leaf Report', 'leafReport', null, false),
      ctx.check('Column Contributions', 'contrib', null, false),
      ctx.check('Split History', 'history', null, false),
      S && S.res.folds ? { label: 'K Fold Crossvalidation', checked: !!ctx.opt('kfold', S.res.folds.k), action: () => kfoldDialog(ctx, S) }
        : { label: 'K Fold Crossvalidation…', checked: !!ctx.opt('kfold', null), action: () => kfoldDialog(ctx, S) },
      ...(cat && S ? SM.predict.classificationItems(ctx, S.res.fit) : []),
      ctx.check('Show Fit Details', 'fitDetails', null, false),
      ctx.check('Profiler', 'profiler', null, false),
      cat && S ? { label: 'Color Points', action: () => colorPoints(ctx, S) } : null,
      { separator: true },
      { label: 'Method', submenu: () => [['jmp', 'Decision Tree (LogWorth, JMP)'], ['cart', 'CART (scikit-learn)']].map(([k, l]) => ({ label: l, checked: ctx.opt('method', 'jmp') === k, action: () => ctx.set('method', k) })) },
      { label: 'Start Over', disabled: !stepsOf(ctx).length, action: () => ctx.set('steps', [], scopeOf(ctx)) },
      ...saveItems(ctx, S),
    ].filter(Boolean);
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:partition': {
      kicker: 'Analyze > Predictive Modeling', title: 'Partition',
      lead: 'A decision tree, grown one split at a time as JMP\'s Partition grows it. Each split cuts the rows of a leaf in two by one column: a continuous or ordinal column at a value, a nominal column into two groups of its levels. The leaves predict the mean of a continuous response, or the probability of each level of a categorical one.',
      sections: [
        { heading: 'Roles', choices: [['Y, Response', 'One column: continuous (a regression tree) or nominal or ordinal (a classification tree).'], ['X, Factor', 'The columns a split may use, of any type.'], ['Weight, Freq', 'Freq counts a row that many times (the minimum size counts it so); Weight weighs it in the means and rates.'], ['Validation', 'Rows marked 0 or Training grow the tree; 1 or Validation choose its size (Go); 2 or Test are kept out of both.'], ['By', 'A tree for each level, each with its own splits.']] },
        { heading: 'Options', choices: [['Minimum Size Split', 'The fewest rows either side of a split (JMP\'s default 5); below 1, a share of the training rows.'], ['Informative Missing', 'A missing value of a continuous X goes to the side of each split that fits better; a missing level of a categorical X is a level of its own. Off: rows missing a factor are left out (JMP keeps them).'], ['Ordinal Restricts Order', 'An ordinal X is cut between neighbouring levels only; off, its levels are grouped freely like a nominal X\'s.'], ['Validation Portion, Random Seed', 'A share of the rows held back for validation, drawn from the seed.'], ['Method', 'Decision Tree (JMP\'s LogWorth, the default), or CART: scikit-learn\'s trees, grown best first, for comparison. CART takes the split with the largest decrease of the impurity, not adjusted for how many cuts a column has; it splits a nominal X one level against the rest, cuts halfway between two values, and its leaf probabilities are the plain rates, which can be 0.']] },
        { heading: 'How a split is chosen', text: 'For every leaf and column the best cut: the one that explains the most, SS (the sum of squares between the two sides) for a continuous response, G² (the likelihood-ratio chi-square) for a categorical one. A nominal X\'s levels are ordered by the response mean or rate and cut between neighbours (the best grouping for a continuous or two-level response); for a response of three or more levels every grouping is tried, up to 12 levels. The split made is the one with the largest LogWorth: −log10 of the split\'s p-value (the two-group F test, or G² as a chi-square) adjusted for the number of ways the column can be cut, so a column with many values does not win just by having more cuts to choose from.' },
        { heading: 'The adjustment', text: 'JMP calibrates its adjustment by Monte Carlo and has not published it, so the LogWorths here are not JMP\'s numbers, and where two columns are close the split chosen can differ. Here: for ordered cuts (a continuous or ordinal X), 1 plus the expected number of times the statistic crosses its observed value between neighbouring cuts (Lausen, Sauerbrei and Schumacher 1994; Rice\'s formula for a chi process); for a nominal X the smaller of Bonferroni over its groupings and Scheffé\'s bound; never more than Bonferroni over the candidates. With no effect an adjusted p-value falls below 0.05 in at most about 5% of samples (2 to 4% for a column with many values, where the bound is a little conservative), where the best of 200 unadjusted cuts does in more than half (the tests check both).' },
        { heading: 'Probabilities', text: 'A leaf\'s probability of a level is (n + prior)/(N + 1): its count of the level plus a prior, over its count plus one. The root\'s prior is the training rates; a child\'s is 0.9 of its parent\'s prior plus 0.1 of its parent\'s probability (JMP\'s documented rule, λ = 0.9). So no probability is 0, and a small leaf leans toward its parent. Rate is the plain share.' },
        { heading: 'The summary', text: 'For each set: RSquare and RASE (a categorical response: the Entropy RSquare and the Misclassification Rate) and N; on the training line the Number of Splits and the AICc, −2 log L + 2k + 2k(k + 1)/(N − k − 1) of the training rows: for a continuous response the normal likelihood of the leaf means, k the leaves and the error variance (JMP\'s, the regression model the tree is); for a categorical one the likelihood of each row\'s Prob of its level, k the leaves\' probabilities (the levels less one each). The Split History shows it after every split, so the number of splits with the smallest AICc can be read off.' },
        { heading: 'Save Columns', choices: [['Save Predicteds, Save Residuals', 'The leaf\'s mean (or each level\'s Prob and the most likely level) of every row whose factors the tree can take, excluded ones too.'], ['Save Leaf Numbers, Save Leaf Labels', 'Each row\'s leaf, numbered as the Leaf Report numbers them, or its path of conditions.'], ['Save Prediction Formula', 'The tree as JMP writes it, nested If clauses of its conditions, as a live formula column: the leaf\'s mean, or a Prob[] column per level and a Most Likely column that takes the level with the largest one. A new or changed row is predicted at once. With Informative Missing a missing value goes where the tree sends it; without it, a row missing a factor gets no prediction, as Save Predicteds gives it none.'], ['Save Leaf Number Formula, Save Leaf Label Formula', 'The same nested If with the leaf\'s number or label.']] },
        { heading: 'Beyond and unlike JMP', text: 'A cut is written as the shortest decimal between the two neighbouring values (JMP writes a data value); the rows split the same way. The Leaf Report\'s Rule (the conditions on one column merged), the Split History\'s AICc and the AICc of a categorical response are not in JMP. CART, scikit-learn\'s trees, is a second method for comparison; its tree has no formulas here. Not here: Lock Columns, Tree 3D, Save Tolerant Prediction Formula, Specify Profit Matrix, and JMP Pro\'s Bootstrap Forest and Boosted Tree (their own platforms).' },
      ],
      more: MORE,
    },
    'p:partition:tree': {
      kicker: 'Partition', title: 'The Tree and the Buttons',
      lead: 'Split splits the leaf whose best split has the largest LogWorth; Prune takes back the split with two leaves and the smallest LogWorth; Go (with validation rows) splits until the validation RSquare has not improved for 10 splits and keeps the tree with the best one. Shift-click Split for several splits. The splits are the report\'s: Redo, a project and By keep them, and Start Over (red triangle) takes them all back.',
      sections: [
        { heading: 'The buttons', choices: [
          ['Split', 'Makes the best split there is: of every leaf and every column, the cut with the largest LogWorth (CART: the next split of scikit-learn\'s best-first tree). Shift-click it to make several in one step.'],
          ['Prune', 'Takes back the weakest of the splits whose two children are both leaves, the one with the smallest LogWorth (CART: the last split made). Dimmed while the tree has no split.'],
          ['Go', 'Only with validation rows (a Validation column or a Validation Portion), or the folds of a K-fold Validation column. Splits one leaf at a time until 10 splits in a row have not improved the validation RSquare (Entropy RSquare for a categorical response), then keeps the tree that had the best one; Split History shows the splits it looked at beyond it, dotted. With K folds the RSquare is crossvalidated: beside the tree, a tree per fold grows on the other folds split for split, and every row is predicted by the one that did not see its fold.'],
          ['Color Points', 'A categorical response: gives the rows in the table the colour of their response level, so that every graph shows the levels.'],
        ] },
        { heading: 'The graph', text: 'The training rows side by side in their leaves (numbered as in the Leaf Report), each leaf as wide as its rows: the response with the leaf\'s mean, or the leaf\'s rates of the levels stacked with the rows scattered in them. Drag over points to select rows.' },
        { heading: 'A node', choices: [['Count', 'its training rows (by Freq)'], ['Mean, Std Dev', 'of a continuous response'], ['G^2', 'its −2 log likelihood: 2 × the sum of −log(rate) over its rows'], ['Rate, Prob', 'the share of each level, and the probability the tree predicts (the rate shrunk toward the parent\'s)'], ['LogWorth', 'of the split made at the node'], ['Difference', 'the left child\'s mean minus the right child\'s']] },
        { heading: 'Clicking a node', choices: [
          ['A click', 'Selects the node\'s rows (every set) in the table and shows its Candidates; Shift adds, Ctrl or ⌘ toggles. The orange bar along its foot is the share of its training rows selected.'],
          ['Split Here', 'In the node\'s red triangle (or a right click), for a leaf: makes its best split.'],
          ['Split Best', 'Makes the best split of any leaf at or below the node.'],
          ['Split Specific…', 'Splits a leaf by a column of your choice, at its best cut or at a value you give.'],
          ['Prune Below', 'Takes back every split below the node, which becomes a leaf again.'],
          ['Prune Worst', 'Takes back the weakest split at or below the node whose two children are leaves.'],
          ['Select Rows, Show Candidates', 'Selects the node\'s rows; or opens Candidates at the node, the selection left alone. A CART node has Select Rows only.'],
        ] },
      ],
      more: MORE,
    },
    'p:partition:cands': {
      kicker: 'Partition', title: 'Candidates',
      lead: 'For the node picked (by a click; at first the leaf the next Split takes), every column\'s best split: its SS or G², its LogWorth and the condition of its left side (right click, Columns, shows the other side). ✓ marks the column split there, or a leaf\'s best.',
      more: MORE,
    },
    'p:partition:history': {
      kicker: 'Partition', title: 'Split History',
      lead: 'RSquare (the entropy RSquare for a categorical response) of each set after each split, in the order the splits were made, and beside it the training rows\' AICc, the smallest marked. With validation rows the validation curve shows where more splits stop helping; without them the smallest AICc is a guide. After Go the splits it looked at past the tree it kept are dotted. Split History Details has the numbers of both graphs.',
      more: MORE,
    },
    'p:partition:leaves': {
      kicker: 'Partition', title: 'Leaf Report',
      lead: 'Each leaf, left to right: its label (the conditions from the root, joined by &), its rule (the same conditions with those on one column merged: a continuous column\'s cuts as one range, 2<=x<5, and a categorical column\'s groups as the levels they share), its mean or level probabilities, and its count; a bar per leaf, which selects the leaf\'s training rows. For a categorical response also the counts of each level.',
      more: MORE,
    },
    'p:partition:kfold': {
      kicker: 'Partition', title: 'K Fold Crossvalidation',
      lead: 'The training rows split into k folds at random (from the report\'s seed). Each fold is predicted by a tree grown on the other folds with as many splits as this tree has, each the best there (manual splits are not copied). K Fold gives the measures of those out-of-fold predictions, Overall the tree\'s own on its training rows.',
      sections: [{ heading: 'A K-fold Validation column', text: 'A Validation column of more than three values (Make Validation Column\'s K Fold) holds the folds: every row trains the tree, the Crossvalidation report shows by itself with the column\'s folds (no number to choose; its red triangle item turns it off and on), and Go chooses the tree\'s size by the crossvalidated RSquare. JMP\'s Partition takes a Validation column of training, validation and test rows; the folds are this page\'s.' }],
      more: MORE,
    },
  };

  /* What the Uplift platform (smui-p-uplift.js) draws and grows with: the
     tree of node boxes (S.look gives its geometry and boxes), the steps, the
     selection bars, the Split History, the formula columns. */
  SM.partition = Object.freeze({ treeBox, addStep, stepsOf, scopeOf, pickNode, watchSelection, nodeFrame, selBar, txt, clip, wide, wrapTables, setColor, fitColor,
    historyOutline, mostLikelyExpr, saveFormulas, minSizeDialog, HELP });

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'partition', label: 'Partition', menu: 'Analyze/Predictive Modeling', order: 10, info: 'p:partition', topics: TOPICS,
    about: 'JMP\'s Partition platform: a decision tree for a continuous or categorical response, grown one split at a time (Split, Prune, and Go with validation rows), each split the column and cut with the largest LogWorth, the adjusted p-value of each column\'s best split (the F test of the two sides, or the likelihood-ratio G²); continuous and ordinal columns cut at a value, nominal ones into two groups of levels; Informative Missing; leaf probabilities smoothed by JMP\'s rule. The report: the partition graph (linked), JMP\'s node boxes (a click selects a node\'s rows; each node has its own red triangle), the summary with the AICc, candidates, the split history with the AICc of every split, the leaf report with each leaf\'s merged rule, column contributions, fit details, confusion matrix, ROC and lift curves, the Decision Threshold, actual by predicted, K-fold crossvalidation, the Prediction Profiler, and Save Columns (predicteds, residuals, leaf numbers and labels, and the prediction, leaf number and leaf label formulas: the tree as nested If, live formula columns). The splitter is written here in numpy after JMP\'s documented method; CART (scikit-learn) is a second method.',
    uses: ['numpy (the splitter, after JMP\'s documented method)', 'scipy.stats (f, chi2, chi), scipy.special (xlogy, gammaln, betaln)', 'sklearn.tree.DecisionTreeRegressor, DecisionTreeClassifier (the CART method)'],
    launch: {
      lead: 'Choose a response and the factors. The tree starts with every row in one node: press Split to grow it, or Go with validation rows.',
      roles: [
        { key: 'y', label: 'Y, Response', min: 1, max: 1, hint: 'required: one, continuous or categorical', help: HELP.y },
        { key: 'x', label: 'X, Factor', min: 1, hint: 'required: one or more', help: HELP.x },
        ...SM.predict.roles(),
      ],
      options: [
        // the shared Informative Missing, told as this engine handles a missing value
        ...SM.predict.options().map((o) => (o.key === 'missing' ? { ...o, help: HELP.missing } : o)),
        { key: 'minsize', label: 'Minimum Size Split', type: 'number', value: 5, hint: 'the fewest rows either side of a split (below 1: a share of the training rows)', help: HELP.minsize },
        { key: 'ordinalOrder', label: 'Ordinal Restricts Order', type: 'check', value: true, hint: 'an ordinal X is cut between neighbouring levels only', help: HELP.ordinalOrder },
        { key: 'method', label: 'Method', type: 'select', value: 'jmp', choices: [['jmp', 'Decision Tree'], ['cart', 'CART (scikit-learn)']], hint: 'Decision Tree: JMP\'s LogWorth; CART: scikit-learn\'s trees, for comparison', help: HELP.method },
      ],
      validate: (spec) => {
        const m = spec.options && spec.options.minsize;
        return m != null && !(m > 0) ? 'Minimum Size Split: a positive number' : null;
      },
    },
    title: (spec, table) => {
      const id = ((spec.roles && spec.roles.y) || [])[0];
      const c = id && table ? table.col(id) : null;
      return c ? `Partition for ${c.name}` : 'Partition';
    },
    triangle: topMenu,
    render,
  });

  /* ---- the example: simulated churn, with its true tree in the notes ------------------------------------ */
  SM.io.addExample('churn', {
    label: 'Churn (2000 customers): contract, tenure, support calls',
    about: 'Simulated: 2000 customers of a subscription service. Whether a customer left (churn) follows a tree. Month-to-month contracts: churn 50% in the first year (tenure under 12 months); after it 40% with 4 or more support calls, 15% with fewer. One-year contracts 8%, two-year 3%. On top: +10 points when the satisfaction score is missing (the 10% who did not answer) and +10 when it is 4 or below. Region changes nothing. Monthly charge is 20 € plus 25 for DSL or 50 for fiber, plus 8 per streaming channel, plus noise (sd 5). The validation column splits the rows 60/25/15 at random. For Partition (Analyze > Predictive Modeling).',
    make() {
      const r = SM.util.rng('partition-churn');
      const n = 2000;
      const c = { customer: [], region: [], contract: [], tenure: [], calls: [], internet: [], streaming: [], charge: [], satisfaction: [], churn: [], validation: [] };
      for (let i = 0; i < n; i++) {
        const u = r.u();
        const contract = u < 0.55 ? 'Month-to-month' : u < 0.8 ? 'One year' : 'Two year';
        const tenure = contract === 'Month-to-month' ? 1 + Math.floor(-Math.log(1 - r.u()) * 16) : 6 + Math.floor(r.u() * 66);
        const calls = Math.min(9, Math.floor(-Math.log(1 - r.u()) * 1.8));
        const net = r.u();
        const internet = net < 0.2 ? 'None' : net < 0.6 ? 'DSL' : 'Fiber';
        const streaming = internet === 'None' ? 0 : r.int(0, 3);
        const answered = r.u() >= 0.1;
        const sat = answered ? Math.max(1, Math.min(10, Math.round(r.normal(6.5, 2)))) : NaN;
        let p = contract === 'One year' ? 0.08 : contract === 'Two year' ? 0.03 : Math.min(72, tenure) < 12 ? 0.5 : calls >= 4 ? 0.4 : 0.15;
        if (!answered) p += 0.1; else if (sat <= 4) p += 0.1;
        const v = r.u();
        c.customer.push(`C${String(i + 1).padStart(4, '0')}`);
        c.region.push(r.pick(['North', 'South', 'East', 'West']));
        c.contract.push(contract);
        c.tenure.push(Math.min(72, tenure));
        c.calls.push(calls);
        c.internet.push(internet);
        c.streaming.push(streaming);
        c.charge.push(+(20 + (internet === 'DSL' ? 25 : internet === 'Fiber' ? 50 : 0) + 8 * streaming + r.normal(0, 5)).toFixed(2));
        c.satisfaction.push(sat);
        c.churn.push(r.u() < Math.min(0.95, p) ? 'Yes' : 'No');
        c.validation.push(v < 0.6 ? 'Training' : v < 0.85 ? 'Validation' : 'Test');
      }
      return new SM.Table({ name: 'Churn', source: 'simulated', columns: [
        { name: 'customer', dataType: 'character', values: c.customer, role: 'label' },
        { name: 'region', dataType: 'character', values: c.region },
        { name: 'contract', dataType: 'character', modelingType: 'ordinal', values: c.contract, valueOrder: ['Month-to-month', 'One year', 'Two year'] },
        { name: 'tenure (months)', dataType: 'numeric', values: c.tenure },
        { name: 'support calls', dataType: 'numeric', values: c.calls },
        { name: 'internet', dataType: 'character', values: c.internet, valueOrder: ['None', 'DSL', 'Fiber'] },
        { name: 'streaming channels', dataType: 'numeric', values: c.streaming },
        { name: 'monthly charge (€)', dataType: 'numeric', values: c.charge },
        { name: 'satisfaction', dataType: 'numeric', values: c.satisfaction },
        { name: 'churn', dataType: 'character', values: c.churn, valueOrder: ['No', 'Yes'] },
        { name: 'validation', dataType: 'character', values: c.validation, valueOrder: ['Training', 'Validation', 'Test'] },
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
