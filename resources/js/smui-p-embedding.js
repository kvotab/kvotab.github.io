/* ==========================================================================
   SMUI.HTML: ANALYZE > MULTIVARIATE METHODS > MULTIVARIATE EMBEDDING

   t-SNE of continuous columns (scikit-learn's TSNE, the Barnes-Hut method):
   every row a point in two or three dimensions, placed near the rows it is
   near in all the columns.

     t-SNE           the map: points are rows (linked), coloured by the
                     Color column or else by the rows' colours; in three
                     dimensions a Plotly scatter3d to turn with the mouse
     Fit Details     the final Kullback-Leibler divergence, the iterations,
                     the perplexity and the learning rate used
     Save Embedding  the map's coordinates as new columns

   t-SNE is slow in the browser (about 7 s for 1000 rows, 20 s for 2000 and
   90 s for 5000): progress shows while it runs, above 3000 rows the report
   asks first, and the backend refuses more than 10 000. UMAP, JMP's other
   method, needs numba, which Pyodide lacks. The numbers are
   resources/py/smui/embedding.py's.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt, PALETTE } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const MORE = { label: 'Multivariate Embedding', id: 'help-p-embedding' };
  const ASK_ROWS = 3000;
  const MAX_ROWS = 10000;
  const SYM3D = ['circle', 'square', 'diamond', 'cross', 'x', 'circle-open', 'square-open', 'diamond-open'];

  /* Seconds t-SNE takes here, from timings in Pyodide 314 (10 columns,
     1000 iterations): 7 s for 1000 rows, 19 s for 2000, 92 s for 5000. */
  function estimate(n, iters, dim) {
    const s = 7.3 * (n / 1000) ** 1.55 * (iters / 1000) * (dim === 3 ? 2 : 1);
    return Math.max(1, s);
  }
  const duration = (s) => (s < 50 ? `about ${Math.max(5, Math.round(s / 5) * 5)} seconds` : s < 90 ? 'about a minute' : `about ${Math.round(s / 60)} minutes`);

  function rowLabels(ctx, rows) {
    const lab = ctx.table ? ctx.table.labelColumn() : null;
    return rows.map((r) => (lab && !SM.table.isMissing(lab.values[r]) ? `${T(SM.grid.cellText(lab, lab.values[r]))} (row ${r + 1})` : `row ${r + 1}`));
  }

  /* A colour with an alpha, from #rrggbb or rgb(r, g, b). */
  function fade(c, a) {
    let m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(c || '');
    if (m) return `rgba(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)}, ${a})`;
    m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(c || '');
    return m ? `rgba(${m[1]}, ${m[2]}, ${m[3]}, ${a})` : c;
  }

  function roomOf(ctx, dflt = 760) {
    const b = ctx.report && ctx.report.body;
    const w = b && b.clientWidth ? b.clientWidth - 70 : dflt;
    return Math.max(280, Math.min(w, 1100));
  }

  /* The column that colours the map: the option (Color By in the red
     triangle), else the Color role. */
  function colorColumn(ctx) {
    const id = ctx.opt('colorCol', undefined);
    if (id === null) return null;
    if (id !== undefined) return ctx.table.col(id);
    return ctx.role('color');
  }

  /* The colours a column gives its rows: the palette by level, or the
     blue-grey-red ramp over its range. */
  function colorer(ctx, c, rows) {
    if (!c) return null;
    const grey = SM.util.themeColors().dark ? '#777777' : '#aaaaaa';
    if (c.isCategorical) {
      const present = new Set(rows.map((r) => c.values[r]).filter((v) => !SM.table.isMissing(v)));
      const lv = ctx.table.levels(c).filter((v) => present.has(v));
      const idx = new Map(lv.map((v, i) => [v, i]));
      return { cat: true, col: c, labels: lv.map((v) => SM.grid.cellText(c, v)), color: (r) => (idx.has(c.values[r]) ? PALETTE[idx.get(c.values[r]) % PALETTE.length] : grey), text: (r) => (SM.table.isMissing(c.values[r]) ? '.' : SM.grid.cellText(c, c.values[r])) };
    }
    let lo = Infinity, hi = -Infinity;
    for (const r of rows) { const v = c.values[r]; if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } }
    const range = lo <= hi ? [lo, hi] : null;
    return { cat: false, col: c, range, color: (r) => { const v = c.values[r]; if (!Number.isFinite(v) || !range) return grey; return SM.util.ramp(range[1] > range[0] ? (v - range[0]) / (range[1] - range[0]) : 0.5); }, text: (r) => (Number.isFinite(c.values[r]) ? fmt(c.values[r]) : '.') };
  }

  /* ---- the payload: every option that changes the map -------------------------------- */
  function payloadOf(ctx) {
    const o = (k, d) => ctx.opt(k, d);
    const lr = o('learningRate', 'auto');
    return {
      columns: ctx.names('y'), dimension: Number(o('dimension', 2)) === 3 ? 3 : 2, perplexity: Number(o('perplexity', 30)) || 30,
      max_iter: Math.round(Number(o('iterations', 1000)) || 1000), learning_rate: lr === '' || lr == null ? 'auto' : String(lr),
      init: o('init', 'pca'), standardize: !!o('standardize', true), seed: SM.predict.seed(ctx),
    };
  }

  /* The rows with a value in every column: what the backend maps. */
  function usable(ctx, cols) {
    let n = 0;
    for (const r of ctx.rows) if (cols.every((c) => Number.isFinite(c.values[r]))) n++;
    return n;
  }

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx) {
    const cols = ctx.roles('y');
    const base = payloadOf(ctx);
    const n = usable(ctx, cols);
    if (n > ASK_ROWS && n <= MAX_ROWS && !ctx.opt('runLarge', false)) { askOutline(ctx, n, base); return; }
    const status = el('p', { class: 'sm-ob-note sm-emb-progress', role: 'status', text: `t-SNE of ${fmt(n)} rows: finding the nearest neighbours…` });
    const bar = el('progress', { class: 'sm-emb-bar', max: String(base.max_iter), value: '0', 'aria-label': 't-SNE iterations' });
    if (!ctx.headless) ctx.container.append(el('div', { class: 'sm-emb-running' }, status, bar));
    const off = ctx.headless ? () => {} : SM.engine.on('progress', (p) => {
      if (!p || p.what !== 'tsne') return;
      const text = p.done === 0 ? `t-SNE of ${fmt(n)} rows${ctx.byLabel ? ` (${ctx.byLabel})` : ''}: finding the nearest neighbours…` : `t-SNE${ctx.byLabel ? ` (${ctx.byLabel})` : ''}: iteration ${p.done} of ${p.total}…`;
      status.textContent = text;
      bar.value = p.done;
      ctx.report.noteEl.textContent = text;
    });
    let res;
    try { res = await ctx.call('embedding.fit', base); } finally { off(); status.parentElement?.remove(); }
    if (res.error) { ctx.container.append(ctx.warn(res.error)); return; }
    ctx.container.append(ctx.note(`${fmt(res.n)} rows over ${res.columns.length} column${res.columns.length === 1 ? '' : 's'}${res.standardize ? ', each standardized' : ''}; perplexity ${fmt(res.perplexity)}, ${fmt(res.iterations)} iterations, ${res.init === 'pca' ? 'the PCA start' : `a random start from the seed ${res.seed}`}.${res.notes.length ? ` ${res.notes.join(' ')}` : ''}`));
    mapOutline(ctx, res);
    if (ctx.opt('details', true)) detailsOutline(ctx, res);
  }

  /* Above ASK_ROWS rows: say how long it takes, and run on request. */
  function askOutline(ctx, n, base) {
    const ob = ctx.outline('t-SNE', { key: 'map', info: 'emb:large' });
    const s = estimate(n, base.max_iter, base.dimension);
    const run = el('button', { type: 'button', class: 'sm-btn small primary', text: `Run t-SNE on ${fmt(n)} rows` });
    run.addEventListener('click', () => ctx.set('runLarge', true));
    ob.add(ctx.warn(`${fmt(n)} rows: t-SNE takes ${duration(s)} in the browser (${fmt(base.max_iter)} iterations${base.dimension === 3 ? ', three dimensions' : ''}). The page stays usable meanwhile; progress shows here.`),
      el('div', { class: 'sm-emb-ask' }, run),
      ctx.note(`A Local Data Filter (red triangle) or fewer iterations make it quicker. More than ${fmt(MAX_ROWS)} rows are refused.`));
  }

  /* ---- the map ------------------------------------------------------------------------------ */
  function mapOutline(ctx, res) {
    const rows = res.rows;
    const C = colorer(ctx, colorColumn(ctx), rows);
    const labels = rowLabels(ctx, rows);
    const hover = rows.map((r, i) => `${labels[i]}${C ? `<br>${T(C.col.name)}: ${T(C.text(r))}` : ''}`);
    const ob = ctx.outline('t-SNE', { key: 'map', info: 'emb:map', menu: () => mapMenu(ctx, res) });
    const n = rows.length;
    const size = n > 3000 ? 3 : n > 1000 ? 4 : 5.5;
    const colors = C ? rows.map((r) => C.color(r)) : null;
    const room = roomOf(ctx);
    let box;
    const view = view3d(ctx);
    if (res.dimension === 3 && view === 'pairs') {
      box = pairsPlot(ctx, res, { rows, colors, hover, size, C, room });
    } else if (res.dimension === 3) {
      const tc = SM.util.themeColors();
      const X = res.coords.map((c) => c[0]), Y = res.coords.map((c) => c[1]), Z = res.coords.map((c) => c[2]);
      const base = colors || SM.report.BASE;
      const ax = (name) => ({ title: { text: name }, gridcolor: tc.grid, zerolinecolor: tc.grid, linecolor: tc.muted, color: tc.text, showbackground: false, backgroundcolor: 'rgba(0,0,0,0)' });
      const w = Math.min(720, room);
      box = ctx.plot([{ type: 'scatter3d', mode: 'markers', x: X, y: Y, z: Z, rows, marker: { size: size - 1, color: base, line: { width: 0 } }, hovertext: hover, hovertemplate: '%{hovertext}<extra></extra>', showlegend: false }],
        { scene: { xaxis: ax(res.names[0]), yaxis: ax(res.names[1]), zaxis: ax(res.names[2]), bgcolor: 'rgba(0,0,0,0)', aspectmode: 'cube' }, margin: { l: 0, r: 0, t: 6, b: 0 }, xaxis: { visible: false }, yaxis: { visible: false } },
        { width: w, height: Math.round(Math.min(600, w * 0.85)), title: 't-SNE map, three dimensions', rowColors: !C });
      states3d(box, { rows, coords: { x: X, y: Y, z: Z }, color: base, size: size - 1, rowColors: !C });
    } else {
      const type = n > 3000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter';
      const traces = [{ type, mode: 'markers', x: res.coords.map((c) => c[0]), y: res.coords.map((c) => c[1]), rows, marker: { size, ...(colors ? { color: colors } : {}) }, hovertext: hover, hovertemplate: '%{hovertext}<extra></extra>', showlegend: false, name: 'rows' }];
      traces.push(...legendTraces(C));
      const legendRight = C && C.cat && room >= 560;
      const w = Math.min(640, room);
      box = ctx.plot(traces, {
        showlegend: !!(C && C.cat), legend: legendRight ? { orientation: 'v', x: 1.02, y: 1, title: { text: T(C.col.name) } } : { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' },
        xaxis: { title: { text: res.names[0] }, zeroline: false }, yaxis: { title: { text: res.names[1] }, zeroline: false },
        margin: { l: 52, r: legendRight ? 130 : (C && !C.cat ? 70 : 12), t: C && C.cat && !legendRight ? 34 : 8, b: 42 },
      }, { width: w, height: Math.round(Math.min(520, Math.max(300, w * 0.85))), title: 't-SNE map', rowColors: !C });
    }
    ob.add(ctx.row(box));
    if (res.dimension === 3 && view !== 'pairs' && C) ob.add(htmlLegend(C));
    if (res.dimension === 3 && view === 'pairs' && ctx.opt('view3d', null) == null) ob.add(ctx.note('This browser has no WebGL, which a turning 3-D plot needs: the three dimensions are drawn in pairs.'));
    const how = C ? `coloured by ${C.col.name}${C.cat ? '' : ' (blue low, red high)'}` : 'in the rows\' colours (Rows > Color or Mark by Column, or Color By in the red triangle)';
    ob.add(ctx.note(`Each point is a row, ${how}. ${res.dimension === 3 && view !== 'pairs' ? 'Drag to turn the map, scroll to zoom; a click selects a row.' : 'Drag over points to select their rows; rows selected elsewhere are highlighted.'} Near points are near in the columns; the distances between far clusters and the clusters' sizes mean little in t-SNE.`),
      ctx.code(res.code));
  }

  /* How a 3-D map is drawn: 'rotate' (Plotly's scatter3d, which needs
     WebGL) or 'pairs' (its three pairs of axes, 2-D and linked); by default
     the first where the browser has WebGL. */
  function view3d(ctx) {
    const v = ctx.opt('view3d', null);
    if (v === 'rotate' || v === 'pairs') return v;
    return SM.report.hasWebGL() ? 'rotate' : 'pairs';
  }

  /* The three pairs of a 3-D map as a lower-triangular matrix of 2-D plots. */
  function pairsPlot(ctx, res, { rows, colors, hover, size, C, room }) {
    const cells = [[1, 0], [2, 0], [2, 1]];         // (y, x) dimensions
    const at = { '1,0': [0, 0], '2,0': [1, 0], '2,1': [1, 1] };
    const g = 2, gap = 0.02;
    const traces = [], layout = { margin: { l: 58, r: 12, t: 8, b: 50 }, dragmode: 'select', showlegend: !!(C && C.cat), legend: { x: 0.56, y: 0.98, title: C && C.cat ? { text: T(C.col.name) } : undefined } };
    cells.forEach(([i, j], q) => {
      const a = q + 1, xa = a === 1 ? 'x' : `x${a}`, ya = a === 1 ? 'y' : `y${a}`;
      const [gi, gj] = at[`${i},${j}`];
      const bottom = gi === g - 1, left = gj === 0;
      layout[`xaxis${a === 1 ? '' : a}`] = { domain: [gj / g + gap, (gj + 1) / g - gap], anchor: ya, zeroline: false, showticklabels: bottom, title: bottom ? { text: res.names[j], standoff: 4 } : undefined, mirror: true };
      layout[`yaxis${a === 1 ? '' : a}`] = { domain: [1 - (gi + 1) / g + gap, 1 - gi / g - gap], anchor: xa, zeroline: false, showticklabels: left, title: left ? { text: res.names[i], standoff: 4 } : undefined, mirror: true };
      traces.push({ type: rows.length > 3000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter', mode: 'markers', x: res.coords.map((c) => c[j]), y: res.coords.map((c) => c[i]), rows, xaxis: xa, yaxis: ya,
        marker: { size: Math.max(2.5, size - 1), ...(colors ? { color: colors } : {}) }, hovertext: hover, hovertemplate: '%{hovertext}<extra></extra>', showlegend: false, name: `${res.names[i]} by ${res.names[j]}` });
    });
    if (C && C.cat) traces.push(...legendTraces(C));
    const w = Math.min(620, room);
    return ctx.plot(traces, layout, { width: w, height: w, title: 't-SNE map, three dimensions in pairs', rowColors: !C });
  }

  function legendTraces(C) {
    if (!C) return [];
    if (C.cat) return C.labels.slice(0, 40).map((lab, i) => ({ type: 'scatter', mode: 'markers', x: [null], y: [null], name: T(lab), marker: { color: PALETTE[i % PALETTE.length], size: 8 }, showlegend: true, hoverinfo: 'skip' }));
    if (!C.range) return [];
    return [{ type: 'scatter', mode: 'markers', x: [null], y: [null], hoverinfo: 'skip', showlegend: false,
      marker: { color: C.range, cmin: C.range[0], cmax: C.range[1], colorscale: [[0, 'rgb(47, 110, 199)'], [0.5, 'rgb(176, 176, 176)'], [1, 'rgb(192, 57, 43)']], showscale: true, colorbar: { title: { text: T(C.col.name), side: 'right' }, thickness: 12, len: 0.7, outlinewidth: 0 } } }];
  }

  function htmlLegend(C) {
    if (!C.cat) return el('p', { class: 'sm-ob-note', text: `Colours: ${C.col.name}, blue (low) to red (high)${C.range ? `, ${fmt(C.range[0])} to ${fmt(C.range[1])}` : ''}.` });
    return el('div', { class: 'sm-emb-legend', role: 'list', 'aria-label': `${C.col.name} colours` }, el('strong', { text: C.col.name }),
      ...C.labels.slice(0, 40).map((lab, i) => el('span', { role: 'listitem' }, el('span', { class: 'sm-emb-swatch', style: { background: PALETTE[i % PALETTE.length] } }), lab)));
  }

  /* Row states onto the 3-D map (the core links 2-D traces only): the
     selection, colours, markers, labels and hidden rows. */
  function states3d(box, L) {
    const p = box._plot;
    if (!p || !p.table) return;
    const t = p.table;
    const core = p.applyStates.bind(p);
    p.applyStates = (kind) => {
      core(kind);
      if (!p.drawn) return;
      const st = t.state;
      let sel = false;
      for (let i = 0; i < t.nrows; i++) if (st[i] & 1) { sel = true; break; }
      const lab = t.labelColumn();
      const upd = {};
      for (const [attr, vals] of Object.entries(L.coords)) upd[attr] = [vals.map((v, k) => ((st[L.rows[k]] & 4) ? null : v))];
      upd['marker.color'] = [L.rows.map((r, k) => {
        const own = L.rowColors && t.color[r] >= 0 ? SM.util.colorOf(t.color[r]) : (Array.isArray(L.color) ? L.color[k] : L.color);
        if (!sel) return own;
        return (st[r] & 1) ? SM.report.SELECTED : fade(own, 0.22);
      })];
      upd['marker.size'] = [L.rows.map((r) => (sel && (st[r] & 1) ? L.size * 1.7 : L.size))];
      upd['marker.symbol'] = [L.rows.map((r) => (t.marker[r] >= 0 ? SYM3D[t.marker[r] % SYM3D.length] : 'circle'))];
      const anyLabel = L.rows.some((r) => st[r] & 8);
      upd.text = [anyLabel ? L.rows.map((r) => ((st[r] & 8) ? T(lab && !SM.table.isMissing(lab.values[r]) ? SM.grid.cellText(lab, lab.values[r]) : r + 1) : '')) : null];
      upd.mode = [anyLabel ? 'markers+text' : 'markers'];
      try { Plotly.restyle(p.box, upd, [0]); } catch (e) { console.warn('SM embedding: restyle failed', e); }
    };
  }

  /* ---- Fit Details ---------------------------------------------------------------------------- */
  function detailsOutline(ctx, res) {
    const ob = ctx.outline('Fit Details', { key: 'details', info: 'emb:details' });
    ob.add(ctx.kv([
      ['Final KL Divergence', res.kl], ['Iterations', res.iterations, 'int'], ['Perplexity', res.perplexity],
      ['Learning Rate', res.learning_rate], ['Early Exaggeration', res.early_exaggeration], ['Dimensions', res.dimension, 'int'], ['Rows', res.n, 'int'], ['Columns', res.columns.length, 'int'],
      ['Initialization', res.init === 'pca' ? 'PCA' : 'Random', 'text'], res.init === 'random' ? ['Random Seed', res.seed, 'int'] : null,
    ]), ctx.note(`The final Kullback-Leibler divergence of the map's Student t neighbourhoods from the data's Gaussian ones (scikit-learn's kl_divergence_, from the Barnes-Hut approximation at the last check); smaller is closer, but only maps of the same rows and perplexity compare. ${res.learning_rate_asked === 'auto' ? `The learning rate "auto" is max(N / early exaggeration / 4, 50) = ${fmt(res.learning_rate)}.` : ''} It took ${fmt(res.seconds, { digits: 1 })} s here.`));
  }

  /* ---- red triangles ------------------------------------------------------------------------ */
  function mapMenu(ctx, res) {
    return [
      { label: 'Color By', submenu: () => colorItems(ctx) },
      ...(res.dimension === 3 ? [{ label: '3-D View', submenu: () => [['rotate', 'Turning Plot (needs WebGL)'], ['pairs', 'Pairs of Axes']].map(([v, l]) => ({ label: l, checked: view3d(ctx) === v, action: () => ctx.set('view3d', v) })) }] : []),
      { label: 'Save Embedding', action: () => saveEmbedding(ctx, res) },
    ];
  }

  function colorItems(ctx) {
    const cur = colorColumn(ctx);
    const items = [{ label: 'Row Colors', checked: !cur, action: () => ctx.set('colorCol', null) }];
    for (const c of ctx.table.columns.slice(0, 60)) items.push({ label: c.name, checked: !!cur && cur.id === c.id, action: () => ctx.set('colorCol', c.id) });
    return items;
  }

  function saveEmbedding(ctx, res) {
    res.names.forEach((nm, j) => ctx.saveColumn(nm, { rows: res.rows, values: res.coords.map((c) => c[j]) }, {
      notes: `t-SNE coordinate ${j + 1} of ${res.dimension} over ${res.columns.join(', ')} (perplexity ${fmt(res.perplexity)}, ${res.iterations} iterations, seed ${res.seed}), from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`,
    }));
  }

  async function askNumber(ctx, title, key, label, dflt, check, info = null) {
    const v = await SM.ui.form({ title, info, fields: [{ key: 'v', label, type: key === 'learningRate' ? 'text' : 'number', value: ctx.opt(key, dflt) }], validate: (x) => check(x.v) });
    if (v) ctx.set(key, key === 'learningRate' ? (String(v.v).trim() || 'auto') : v.v);
  }

  function topMenu(ctx) {
    const o = (k, d) => ctx.opt(k, d);
    return [
      { label: 'Dimensions', submenu: () => [2, 3].map((d) => ({ label: String(d), checked: Number(o('dimension', 2)) === d, action: () => ctx.set('dimension', d) })) },
      { label: 'Perplexity…', action: () => askNumber(ctx, 'Perplexity', 'perplexity', 'Perplexity (about the number of neighbours of each row)', 30, (x) => (x > 0 ? null : 'The perplexity is a positive number'), 'emb:details') },
      { label: 'Iterations…', action: () => askNumber(ctx, 'Iterations', 'iterations', 'Iterations (at least 250)', 1000, (x) => (Number.isInteger(x) && x >= 250 && x <= 100000 ? null : 'A whole number from 250 to 100 000')) },
      { label: 'Learning Rate…', action: () => askNumber(ctx, 'Learning Rate', 'learningRate', 'Learning rate (a positive number, or auto)', 'auto', (x) => (String(x).trim() === '' || String(x).trim().toLowerCase() === 'auto' || Number(x) > 0 ? null : 'A positive number, or auto')) },
      { label: 'Initialization', submenu: () => [['pca', 'PCA'], ['random', 'Random']].map(([v, l]) => ({ label: l, checked: o('init', 'pca') === v, action: () => ctx.set('init', v) })) },
      ctx.check('Standardize Columns', 'standardize', null, true),
      { label: 'Random Seed…', action: async () => { const v = await SM.ui.form({ title: 'Random Seed', fields: [{ key: 's', label: 'Seed (empty: the report\'s own)', type: 'text', value: o('seed', '') }], validate: (x) => (String(x.s).trim() === '' || Number.isInteger(Number(x.s)) ? null : 'A whole number, or empty') }); if (v) ctx.set('seed', String(v.s).trim() === '' ? '' : Math.trunc(Number(v.s))); } },
      { separator: true },
      ctx.check('Fit Details', 'details', null, true),
      { label: 'Color By', submenu: () => colorItems(ctx) },
      { label: 'Save Embedding', action: async () => {
        const n = usable(ctx, ctx.roles('y'));
        if (n > ASK_ROWS && !ctx.opt('runLarge', false)) { SM.ui.toast('Run t-SNE first (the button in the report)', { error: true }); return; }
        try { const r = await ctx.call('embedding.fit', payloadOf(ctx)); if (r.error) SM.ui.toast(r.error, { error: true }); else saveEmbedding(ctx, r); } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
      } },
    ];
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:embedding': {
      kicker: 'Analyze > Multivariate Methods', title: 'Multivariate Embedding',
      lead: 'A map of the rows in two or three dimensions that keeps their neighbours: t-SNE (scikit-learn\'s TSNE) gives each row a Gaussian neighbourhood over all the columns, with a width set so that every row has the same perplexity (about how many neighbours it has), and places the rows so that Student t neighbourhoods in the map match them, by gradient descent on the Kullback-Leibler divergence.',
      sections: [
        { heading: 'Roles', choices: [['Y, Columns', 'Two or more continuous columns; rows with a missing value are left out, a column with one value too.'], ['Color', 'Optional: a column whose levels (or values, blue to red) colour the points. Without it the points take the rows\' colours.'], ['By', 'A separate map for each level.']] },
        { heading: 'Options', choices: [['Perplexity', '30 (scikit-learn\'s default); lowered when it is not below the number of rows.'], ['Dimensions', '2 or 3.'], ['Iterations', '1000, the first 250 with early exaggeration 12.'], ['Learning Rate', 'auto: max(N / 12 / 4, 50).'], ['Initialization', 'PCA (the first components, scaled small) or random.'], ['Standardize Columns', 'On by default: each column to mean 0 and standard deviation 1, so that no column dominates by its units.'], ['Random Seed', 'The random start\'s: kept with the report, so that Redo, a project and the Python code give the same map. The PCA start is not random: with it scikit-learn gives the same map for every seed.']] },
        { heading: 'Reading the map', text: 'Rows close together are similar; clusters show groups. The distances between clusters, their sizes and densities are not to be read: t-SNE keeps neighbourhoods, not distances. Another seed or perplexity gives another map; structure that stays is real.' },
        { heading: 'UMAP', text: 'JMP also offers UMAP. It is not here: umap-learn needs numba, a compiler that Pyodide (the browser\'s Python) does not have.' },
        { heading: 'Time', text: 'Barnes-Hut t-SNE in the browser takes about 7 s for 1000 rows, 20 s for 2000 and 90 s for 5000 (10 columns, measured in Pyodide 314). Progress shows while it runs; above 3000 rows the report asks first, and more than 10 000 rows are refused.' },
        { heading: 'Differences from JMP', text: 'JMP\'s own defaults (its learning rate, initialization and iterations) are not known here; this page uses scikit-learn\'s. JMP\'s KL divergence may be computed differently from scikit-learn\'s Barnes-Hut estimate.' },
      ],
      more: MORE,
    },
    'emb:map': { kicker: 'Multivariate Embedding', title: 't-SNE map', lead: 'Each point is a row. Drag over points (or click one in 3-D) to select rows in the table and every other graph; rows selected elsewhere are highlighted here. Color By (red triangle) colours the points by a column; Save Embedding writes the coordinates as columns t-SNE 1, t-SNE 2 (and t-SNE 3).', more: MORE },
    'emb:details': { kicker: 'Multivariate Embedding', title: 'Fit Details', lead: 'The final Kullback-Leibler divergence KL(P‖Q) of the map (scikit-learn\'s kl_divergence_), the iterations run, and the perplexity, learning rate and early exaggeration used. The perplexity is 2 to the entropy of each row\'s neighbourhood, about the number of its neighbours: small values show local structure, large ones more of the global.', more: MORE },
    'emb:large': { kicker: 'Multivariate Embedding', title: 'Many rows', lead: 't-SNE\'s time grows faster than the number of rows: in the browser about 20 s for 2000 rows and 90 s for 5000. Above 3000 rows the report shows the estimate and runs when asked; the answer is kept with the report. More than 10 000 rows are refused: a Local Data Filter or a subset makes them fewer.', more: MORE },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'embedding', label: 'Multivariate Embedding', menu: 'Analyze/Multivariate Methods', order: 55, info: 'p:embedding', topics: TOPICS,
    about: 't-SNE maps of the rows in two or three dimensions over continuous columns (standardized by default): points linked to the rows, coloured by a column or by the rows\' colours, the final Kullback-Leibler divergence, and the coordinates saved as columns. Progress shows while it runs; above 3000 rows it asks first. UMAP is not available (it needs numba).',
    uses: ['sklearn.manifold.TSNE (Barnes-Hut)'],
    launch: {
      lead: 'Choose two or more continuous columns. Each row becomes a point of a map in which near rows are near; a Color column colours the points.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 2, numeric: true, types: ['continuous'], hint: 'required: two or more continuous' },
        { key: 'color', label: 'Color', max: 1, hint: 'optional: colours the points' },
        { key: 'by', label: 'By', hint: 'optional' },
      ],
      options: [
        { key: 'method', label: 'Method', type: 'select', value: 'tsne', choices: [['tsne', 't-SNE']], hint: 'UMAP needs numba, which the browser\'s Python does not have' },
        { key: 'dimension', label: 'Dimensions', type: 'select', value: '2', choices: [['2', '2'], ['3', '3']] },
        { key: 'perplexity', label: 'Perplexity', type: 'number', value: 30 },
        { key: 'iterations', label: 'Iterations', type: 'number', value: 1000 },
        { key: 'learningRate', label: 'Learning Rate', type: 'text', value: 'auto', hint: 'a positive number, or auto: max(N / 48, 50)' },
        { key: 'init', label: 'Initialization', type: 'select', value: 'pca', choices: [['pca', 'PCA'], ['random', 'Random']] },
        { key: 'standardize', label: 'Standardize Columns', type: 'check', value: true },
        { key: 'seed', label: 'Random Seed', type: 'text', value: '', hint: 'empty: a seed drawn now and kept with the report' },
      ],
      validate: (spec) => {
        const o = spec.options || {};
        if (o.perplexity != null && !(o.perplexity > 0)) return 'Perplexity: a positive number';
        if (o.iterations != null && !(Number.isInteger(o.iterations) && o.iterations >= 250 && o.iterations <= 100000)) return 'Iterations: a whole number from 250 to 100 000';
        const lr = String(o.learningRate ?? 'auto').trim().toLowerCase();
        if (lr !== '' && lr !== 'auto' && !(Number(lr) > 0)) return 'Learning Rate: a positive number, or auto';
        if (o.seed != null && String(o.seed).trim() !== '' && !Number.isFinite(Number(o.seed))) return 'Random Seed: a whole number, or empty';
        return null;
      },
    },
    title: () => 'Multivariate Embedding',
    triangle: topMenu,
    render,
  });

  /* ---- the example: cell profiles, simulated ------------------------------------------------ */
  SM.io.addExample('cellprofiles', {
    label: 'Cell profiles (900 rows): 12 markers, 5 types',
    about: 'Simulated: 900 cells from two donors, each measured on 12 markers (m01 to m12). They are of five types, in the shares 0.3, 0.25, 0.2, 0.15 and 0.1, each with its own mean profile (normal, standard deviation 2.5 per marker) and noise of standard deviation 1; type 4\'s profile is type 3\'s moved a little (so the two lie side by side), and type 2 spreads along a line (a continuum, drawn uniformly over ±2.5 along a random direction). Donor (A or B) is assigned at random and changes nothing. Type (true) holds each cell\'s type. For Multivariate Embedding (Analyze > Multivariate Methods): the map should show the five types, 3 and 4 next to each other, 2 drawn out.',
    make() {
      const r = SM.util.rng('embedding-cell-profiles');
      const p = 12, n = 900;
      const shares = [0.3, 0.25, 0.2, 0.15, 0.1];
      const means = shares.map(() => Array.from({ length: p }, () => 2.5 * r.normal()));
      means[3] = means[2].map((v) => v + 1.2 * r.normal());
      const dir = Array.from({ length: p }, () => r.normal());
      const len = Math.sqrt(dir.reduce((a, b) => a + b * b, 0));
      const cols = Array.from({ length: p }, () => []);
      const type = [], donor = [];
      for (let i = 0; i < n; i++) {
        const u = r.u();
        let t = 0, acc = shares[0];
        while (u > acc && t < shares.length - 1) { t++; acc += shares[t]; }
        const along = t === 1 ? -2.5 + 5 * r.u() : 0;
        for (let j = 0; j < p; j++) cols[j].push(+(means[t][j] + (along * dir[j]) / len * 2 + r.normal()).toFixed(3));
        type.push(`type ${t + 1}`);
        donor.push(r.u() < 0.5 ? 'A' : 'B');
      }
      return new SM.Table({ name: 'Cell profiles', source: 'simulated', columns: [
        { name: 'donor', dataType: 'character', values: donor },
        { name: 'type (true)', dataType: 'character', values: type },
        ...cols.map((v, j) => ({ name: `m${String(j + 1).padStart(2, '0')}`, dataType: 'numeric', values: v })),
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
