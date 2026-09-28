/* ==========================================================================
   SMUI.HTML: GRAPH

   Graph Builder (a report that is its own launch: columns dropped on zones,
   elements picked from a palette, among them statsmodels' Bean), Scatterplot
   Matrix, Scatterplot 3D, Contour Plot, Surface Plot, Bubble Plot, Parallel
   Plot, Cell Plot, Ternary Plot, Treemap, the Functional Data Plot
   (statsmodels' functional boxplot, HDR boxplot and rainbow plot, which JMP
   does not have), and under Legacy the Chart and the Overlay Plot.

   The statistics (smoothers, fit lines, ellipses, densities, the summary
   statistics of bars, lines and boxes, interpolation) are graph.py's,
   through ctx.call; counts and sums are counted here. Every graph is
   linked to the table: traces of points through the core (smui-report.js,
   rows per point), and the traces that stand for groups of rows -- bars,
   boxes, histogram bins, heatmap cells, pie slices, summary points -- through
   link() below, which selects a group's rows on a click and draws the
   selected share over it.

   Table-derived text (column names, levels, labels) goes into Plotly only
   through esc(): Plotly reads a few HTML tags in its text.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, svg, fmt, typeIcon, TYPE_LABEL, PALETTE } = SM.util;
  const { isMissing } = SM.table;
  const MIME = SM.launch.MIME;

  /* ---- small helpers ----------------------------------------------------- */
  const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const isCat = (c) => !!c && (c.isCategorical || !c.isNumeric);
  const isDate = (c) => !!c && c.isNumeric && !!c.format && /date/.test(c.format.kind || '');
  const clone = (x) => (x == null ? x : JSON.parse(JSON.stringify(x)));
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const cellText = (c, v) => SM.grid.cellText(c, v);
  const GL_POINTS = 2500;           // more points than this in a graph: WebGL traces

  /* WebGL is there in most browsers; without it, SVG traces (slower, but drawn). */
  let GL_OK = null;
  function webgl() {
    if (GL_OK == null) {
      try { const c = document.createElement('canvas'); GL_OK = !!(c.getContext('webgl') || c.getContext('experimental-webgl')); } catch (e) { GL_OK = false; }
    }
    return GL_OK;
  }

  function rgbOf(c) {
    if (typeof c !== 'string') return [128, 128, 128];
    if (c[0] === '#') { const n = parseInt(c.length === 4 ? c.slice(1).replace(/./g, (h) => h + h) : c.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
    const m = /rgba?\(([^)]+)\)/.exec(c);
    return m ? m[1].split(',').slice(0, 3).map((v) => Number(v)) : [128, 128, 128];
  }
  const rgba = (c, a) => { const [r, g, b] = rgbOf(c); return `rgba(${r}, ${g}, ${b}, ${a})`; };
  const dark = () => SM.util.themeColors().dark;
  const inkColor = () => (dark() ? '#9cc3e6' : '#1f4e79');          // a fit line with no group
  const pointColor = () => (dark() ? '#6fa3d6' : SM.report.BASE);  // points with no colour
  const barColor = () => (dark() ? '#7d97b3' : SM.report.BAR);
  const RAMP = [[0, SM.util.ramp(0)], [0.5, SM.util.ramp(0.5)], [1, SM.util.ramp(1)]];
  const seqScale = () => (dark() ? [[0, '#23313f'], [0.5, '#4f7fae'], [1, '#bfe0ff']] : [[0, '#eef3f8'], [0.5, '#7aa3c8'], [1, '#1f4e79']]);

  /* A pseudo-random number in [0, 1) that belongs to a row: jitter that
     stays put when the graph is redrawn. */
  function hash01(r, salt) {
    let h = Math.imul((r + 1) ^ Math.imul(salt + 7, 0x9e3779b1), 0x85ebca6b);
    h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae35); h ^= h >>> 16;
    return (h >>> 0) / 4294967296;
  }

  function extent(vals) {
    let lo = Infinity, hi = -Infinity;
    for (const v of vals) if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
    return lo <= hi ? [lo, hi] : null;
  }

  /* The levels of a categorical column among some rows, in the table's order. */
  function levelsAmong(t, c, rows) {
    const seen = new Set();
    for (const r of rows) { const v = c.values[r]; if (!isMissing(v)) seen.add(v); }
    return t.levels(c).filter((v) => seen.has(v));
  }

  /* Nice round numbers for axis steps and bins. */
  function niceStep(raw) {
    const p = 10 ** Math.floor(Math.log10(raw));
    return [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw * 0.999) || 10 * p;
  }

  /* The share (0..1) of a list of rows that is selected. */
  function selShare(st, rows) {
    if (!rows || !rows.length) return 0;
    let n = 0;
    for (const r of rows) if (st[r] & 1) n++;
    return n / rows.length;
  }

  function anySelected(t) {
    const st = t.state;
    for (let i = 0; i < t.nrows; i++) if (st[i] & 1) return true;
    return false;
  }

  /* ---- linking the traces that stand for groups of rows -------------------
     specs, each for one trace of a plot made with ctx.plot:
       { trace, kind: 'bar', rows: [[r, ...], ...], len: [...], horiz, overlay }
            bars, histogram bins, mosaic cells; the overlay bar trace (same
            positions, bases and widths) shows the selected share of each
       { trace, kind: 'mark', rows, x, y, overlay }
            summary points, line vertices, bubbles; the overlay rings the
            items that hold a selected row
       { trace, kind: 'box', rows, pos, vals, horiz, overlay }
            boxes; the overlay draws the selected rows' values
       { trace, kind: 'cell', rows: [[[r, ...]]] (row iy, column ix), overlay }
            heatmap cells; the overlay heatmap tints the selected share
       { trace, kind: 'slice', rows }     pie slices, pulled out when selected
       { trace, kind: 'path', rows: [r, ...] (per vertex), paths: { r: [xs, ys] }, overlay }
            one line per row (parallel coordinates); the overlay redraws the
            selected rows' lines
     opts.maskColors: the table's row colours are not applied (a Color zone
     gives the colours); opts.after(plot, anySel): more restyling. */
  const NO_COLORS = { n: -1, a: null };
  function noColors(n) {
    if (NO_COLORS.n !== n) { NO_COLORS.n = n; NO_COLORS.a = new Int16Array(n).fill(-1); }
    return NO_COLORS.a;
  }

  function link(box, specs, opts = {}) {
    const p = box._plot;
    if (!p) return box;
    const t = p.table;
    const byTrace = new Map();
    for (const s of specs) { byTrace.set(s.trace, s); if (s.overlay != null) byTrace.set(s.overlay, s); }
    const coreApply = p.applyStates.bind(p);
    p.applyStates = (kind) => {
      if (!p.drawn || !t) return;
      if (opts.maskColors) {
        const saved = t.color;
        t.color = noColors(t.nrows);
        try { coreApply(kind); } finally { t.color = saved; }
      } else coreApply(kind);
      const sel = anySelected(t);
      if (specs.length) highlight(p, specs, sel);
      if (opts.after) opts.after(p, sel);
    };
    const rowsAt = (s, pt) => {
      if (s.kind === 'cell') {
        const pn = Array.isArray(pt.pointNumber) ? pt.pointNumber : null;
        return pn ? (((s.rows[pn[0]] || [])[pn[1]]) || []) : [];
      }
      if (pt.curveNumber === s.overlay && s._ovRows) return s._ovRows[pt.pointNumber] || [];
      if (s.kind === 'box') {
        const at = s.horiz ? pt.y : pt.x;
        let best = -1, d = Infinity;
        s.pos.forEach((q, k) => { const e = Math.abs(q - at); if (e < d) { d = e; best = k; } });
        return best >= 0 ? s.rows[best] : [];
      }
      if (s.kind === 'path') return s.rows[pt.pointNumber] != null ? [s.rows[pt.pointNumber]] : [];
      const k = pt.pointNumber != null ? pt.pointNumber : (Array.isArray(pt.pointNumbers) ? pt.pointNumbers[0] : null);
      return k != null ? (s.rows[k] || []) : [];
    };
    const prev = p.opts.onDraw;
    p.opts.onDraw = (gd) => {
      gd.on('plotly_click', (ev) => {
        if (!t || !ev || !ev.points || !ev.points.length) return;
        const pt = ev.points[0];
        const s = byTrace.get(pt.curveNumber);
        if (!s) return;
        const rows = rowsAt(s, pt);
        if (!rows.length) return;
        const e = ev.event || {};
        t.select(rows, e.shiftKey ? 'add' : (e.metaKey || e.ctrlKey) ? 'toggle' : 'replace');
      });
      gd.on('plotly_selected', (ev) => {
        if (!t || !ev || !ev.points || p.quiet) return;    // not an announcement of a redraw (SM.report's refreshStates)
        const rows = new Set();
        for (const pt of ev.points) { const s = byTrace.get(pt.curveNumber); if (s) for (const r of rowsAt(s, pt)) rows.add(r); }
        if (rows.size) p.own(() => t.select([...rows], 'add'));
      });
      if (prev) prev(gd);
    };
    return box;
  }

  function highlight(p, specs, sel) {
    const gd = p.box;
    const st = p.table.state;
    const groups = new Map();      // an attribute signature -> { idx: [], upd: { attr: [] } }
    const put = (sig, idx, upd) => {
      let g = groups.get(sig);
      if (!g) { g = { idx: [], upd: {} }; groups.set(sig, g); }
      g.idx.push(idx);
      for (const [k, v] of Object.entries(upd)) (g.upd[k] || (g.upd[k] = [])).push(v);
    };
    for (const s of specs) {
      if (s.overlay == null && s.kind !== 'slice') continue;
      if (s.kind === 'bar') {
        const v = s.rows.map((rs, k) => (sel ? s.len[k] * selShare(st, rs) : 0));
        put(s.horiz ? 'x' : 'y', s.overlay, s.horiz ? { x: v } : { y: v });
      } else if (s.kind === 'mark') {
        const on = s.rows.map((rs) => sel && rs.some((r) => st[r] & 1));
        put('xy', s.overlay, { x: s.x.map((v, k) => (on[k] ? v : null)), y: s.y.map((v, k) => (on[k] ? v : null)) });
      } else if (s.kind === 'box') {
        const xs = [], ys = [], ov = [];
        if (sel) s.rows.forEach((rs, k) => rs.forEach((r, j) => { if (st[r] & 1) { const q = s.pos[k] + (hash01(r, 5) - 0.5) * (s.jitter || 0); const v = s.vals[k][j]; if (s.horiz) { xs.push(v); ys.push(q); } else { xs.push(q); ys.push(v); } ov.push([r]); } }));
        s._ovRows = ov;
        put('xy', s.overlay, { x: xs, y: ys });
      } else if (s.kind === 'cell') {
        const z = s.rows.map((row) => row.map((rs) => { const f = sel ? selShare(st, rs) : 0; return f > 0 ? f : null; }));
        put('z', s.overlay, { z });
      } else if (s.kind === 'slice') {
        put('pull', s.trace, { pull: s.rows.map((rs) => (sel && rs.some((r) => st[r] & 1) ? 0.08 : 0)) });
      } else if (s.kind === 'path') {
        const xs = [], ys = [], ov = [];
        if (sel) for (const r of s.list) if (st[r] & 1) { const q = s.paths.get(r); if (!q) continue; for (let j = 0; j < q[0].length; j++) { xs.push(q[0][j]); ys.push(q[1][j]); ov.push([r]); } xs.push(null); ys.push(null); ov.push([]); }
        s._ovRows = ov;
        put('xy', s.overlay, { x: xs, y: ys });
      }
    }
    for (const g of groups.values()) {
      try { Plotly.restyle(gd, g.upd, g.idx); } catch (e) { console.warn('SM graph: restyle failed', e); }
    }
    // Plotly's own box selection dims unselected bars; the table's selection is what shows.
    const barIdx = specs.filter((s) => s.kind === 'bar' || s.kind === 'mark').map((s) => s.trace);
    if (barIdx.length) { try { Plotly.restyle(gd, { selectedpoints: barIdx.map(() => null) }, barIdx); } catch (e) { /* not selectable */ } }
  }

  /* An overlay trace for a linked group trace: drawn over it, never hovered. */
  function overlayBar(tr) {
    const o = { type: 'bar', x: tr.x, y: tr.y, orientation: tr.orientation, width: tr.width, base: tr.base, offset: tr.offset, xaxis: tr.xaxis, yaxis: tr.yaxis, marker: { color: SM.report.SELECTED, line: { width: 0 } }, hoverinfo: 'skip', showlegend: false };
    if (tr.orientation === 'h') o.x = tr.x.map(() => 0); else o.y = tr.y.map(() => 0);
    return o;
  }
  function overlayMarks(tr, size = 11) {
    return { type: 'scatter', mode: 'markers', x: tr.x.map(() => null), y: tr.y.map(() => null), xaxis: tr.xaxis, yaxis: tr.yaxis, marker: { symbol: 'circle-open', size, color: SM.report.SELECTED, line: { width: 2.2, color: SM.report.SELECTED } }, hoverinfo: 'skip', showlegend: false };
  }

  /* Row states onto scatter traces the core does not link (3-D, ternary):
     selection, colours, markers, labels, hidden rows. idx: the trace; xyz:
     the coordinate arrays by attribute; base: the trace's own colour. */
  function pointStates(box, list) {
    const p = box._plot;
    if (!p) return box;
    const t = p.table;
    const coreApply = p.applyStates.bind(p);
    p.applyStates = (kind) => {
      coreApply(kind);
      if (!p.drawn || !t) return;
      const st = t.state;
      const sel = anySelected(t);
      const lab = t.labelColumn();
      for (const L of list) {
        const upd = {};
        for (const [attr, vals] of Object.entries(L.coords)) upd[attr] = [vals.map((v, k) => ((st[L.rows[k]] & 4) ? null : v))];
        const colors = L.rows.map((r, k) => {
          const own = t.color[r] >= 0 && !L.mask ? SM.util.colorOf(t.color[r]) : (Array.isArray(L.color) ? L.color[k] : L.color);
          if (!sel) return own;
          return (st[r] & 1) ? SM.report.SELECTED : rgba(own, L.fade ?? 0.25);
        });
        upd['marker.color'] = [colors];
        if (L.sizes !== false) upd['marker.size'] = [L.rows.map((r, k) => { const s0 = Array.isArray(L.size) ? L.size[k] : (L.size || 4); return sel && (st[r] & 1) ? s0 * 1.6 : s0; })];
        if (L.symbols) upd['marker.symbol'] = [L.rows.map((r) => (t.marker[r] >= 0 ? L.symbols[t.marker[r] % L.symbols.length] : L.symbols[0]))];
        const anyLabel = L.rows.some((r) => st[r] & 8);
        upd.text = [anyLabel ? L.rows.map((r) => ((st[r] & 8) ? esc(lab ? (lab.values[r] ?? '') : r + 1) : '')) : null];
        upd.mode = [anyLabel ? 'markers+text' : 'markers'];
        try { Plotly.restyle(p.box, upd, [L.trace]); } catch (e) { console.warn('SM graph: restyle failed', e); }
      }
    };
    return box;
  }

  /* The hover line of a row: its number and label, then the values. */
  function rowHover(t, r, parts) {
    const lab = t.labelColumn();
    const head = `row ${r + 1}${lab && !isMissing(lab.values[r]) ? `: ${esc(cellText(lab, lab.values[r]))}` : ''}`;
    return [head, ...parts.filter(Boolean).map((c) => `${esc(c.name)}: ${isMissing(c.values[r]) ? '.' : esc(cellText(c, c.values[r]))}`)].join('<br>');
  }

  /* ---- Graph Builder: zones and elements ------------------------------------------------- */
  const ZONES = [
    { key: 'x', label: 'X', max: 4, place: 'x' },
    { key: 'y', label: 'Y', max: 6, place: 'y' },
    { key: 'groupX', label: 'Group X', max: 1, place: 'gx' },
    { key: 'groupY', label: 'Group Y', max: 1, place: 'gy' },
    { key: 'wrap', label: 'Wrap', max: 1, place: 'wrap' },
    { key: 'overlay', label: 'Overlay', max: 1, place: 'side', cat: true },
    { key: 'color', label: 'Color', max: 1, place: 'side' },
    { key: 'size', label: 'Size', max: 1, place: 'side', numeric: true },
    { key: 'freq', label: 'Freq', max: 1, place: 'side', numeric: true },
  ];
  const ZONE = Object.fromEntries(ZONES.map((z) => [z.key, z]));

  function zoneRefuses(z, c) {
    if (z.numeric && !c.isNumeric) return `${z.label} takes a numeric column; ${c.name} is character`;
    if (z.key === 'size' && isCat(c)) return `Size takes a continuous column; ${c.name} is ${TYPE_LABEL[c.modelingType].toLowerCase()}`;
    return null;
  }

  const STATS = [['n', 'N'], ['mean', 'Mean'], ['median', 'Median'], ['sum', 'Sum'], ['min', 'Min'], ['max', 'Max'], ['range', 'Range'], ['sd', 'Std Dev'], ['se', 'Std Err'], ['var', 'Variance'], ['pct', '% of Total'], ['q1', 'First Quartile'], ['q3', 'Third Quartile']];
  const STAT_LABEL = Object.fromEntries(STATS);
  const PY_STATS = new Set(['mean', 'median', 'min', 'max', 'range', 'sd', 'se', 'var', 'q1', 'q3']);
  const INTERVALS = [['none', 'None'], ['range', 'Range'], ['se', 'Standard Error'], ['sd', 'Standard Deviation'], ['ci', 'Confidence Interval'], ['iqr', 'Interquartile Range']];
  const LABELS = [['none', 'None'], ['value', 'Label by Value'], ['percent', 'Label by Percent of Total Values']];
  const spline = (e) => e.method !== 'lowess';
  const lowessM = (e) => e.method === 'lowess';

  /* What the help says of the statistics, the error intervals and the labels,
     for the properties that offer them. */
  const STATS_HELP = 'N (the count, Freq counted), Mean, Median, Sum, Min, Max, Range, Std Dev, Std Err, Variance, % of Total (the share of the panel\'s sum, or of its count without a continuous variable), First and Third Quartile (JMP\'s (n+1)p quantiles)';
  const INTERVAL_HELP = '**Range** runs from the minimum to the maximum, **Standard Error** and **Standard Deviation** one of them either side of the mean, **Confidence Interval** the t interval of the mean at 1 − α (α from Set Alpha Level in the red triangle), **Interquartile Range** from the first to the third quartile. Standard Error, Standard Deviation and Confidence Interval go with the Mean only; without a continuous variable there is no interval.';
  const CONNECT_HELP = 'How the vertices are joined: **Line** (the default) with straight segments, **Curve** with a smooth curve through them, **Step** with a flat run to each next vertex and then a jump to its value.';

  /* needs: which X/Y combinations an element draws. z: its drawing order,
     low first (areas and bars under points and lines). about and each
     property's help are what Graph Builder's (i) says; shows says when a
     property that comes and goes is there. */
  const ELEMENTS = [
    { type: 'points', label: 'Points', z: 60, needs: 'any', about: 'A marker for each row, jittered across a categorical axis; with a Summary Statistic, one marker for each level (or value) of the other axis. Takes any columns on X or Y.', props: [
      { key: 'summary', label: 'Summary Statistic', type: 'select', choices: [['none', 'None'], ...STATS], dflt: 'none', help: `**None** (the default) draws every row. A statistic draws one marker for each level (or distinct value) of the other axis instead, the statistic of the continuous variable over its rows: ${STATS_HELP}. Without a continuous variable only N and % of Total can be drawn (Mean and the others fall back to N). A summary marker is linked to its rows: click it to select them.` },
      { key: 'interval', label: 'Error Interval', type: 'select', choices: INTERVALS, dflt: 'none', when: (e) => e.summary !== 'none', shows: 'with a Summary Statistic', help: `Error bars on each summary marker. ${INTERVAL_HELP}` },
      { key: 'jitter', label: 'Jitter', type: 'select', choices: [['auto', 'Auto'], ['none', 'None'], ['uniform', 'Random Uniform'], ['normal', 'Random Normal'], ['grid', 'Centered Grid'], ['packed', 'Packed']], dflt: 'auto', when: (e) => e.summary === 'none', shows: 'with Summary Statistic None', help: 'Spreads the points across a categorical axis (or an axis with no column), so that rows with the same level do not hide one another; a continuous axis is never jittered. **Auto** (the default) and **Random Uniform**: random offsets, any place across the level\'s room as likely as another; **Random Normal**: offsets from a normal distribution, most near the middle; **Centered Grid**: the points of a level with about the same value (the same fortieth of the range) set side by side in a row; **Packed**: a beeswarm, each point as near the middle as it can go without covering another; **None**: every point on its level. Centered Grid and Packed need a continuous variable on the other axis; otherwise they are uniform. The offsets belong to the rows, so a redraw leaves each point where it was.' },
      { key: 'jitterLimit', label: 'Jitter Limit', type: 'number', dflt: 1, min: 0, max: 2, step: 0.1, when: (e) => e.summary === 'none' && e.jitter !== 'none', shows: 'with a Jitter other than None', help: 'How far the jitter may spread the points, from 0 to 2, as a share of a level\'s room: 1 (the default) spreads them over about 80% of it (Packed may use all of it), 0 puts them back on the level, above 1 spreads them wider.' },
    ] },
    { type: 'smoother', label: 'Smoother', z: 80, needs: 'xy-cont', about: 'A smooth curve through the points, one for each group of Overlay (or of a categorical Color). Needs continuous X and Y.', props: [
      { key: 'method', label: 'Method', type: 'select', choices: [['spline', 'Spline'], ['lowess', 'Local Kernel']], dflt: 'spline', help: '**Spline** (the default): JMP\'s smoother, a cubic smoothing spline fitted on standardized X (scipy\'s make_smoothing_spline; rows with the same X are fitted through their mean); it needs 5 distinct X values. **Local Kernel**: statsmodels\' lowess, a straight line fitted to the nearest points around each X, weighted towards the nearest and refitted so that outliers pull it less; not JMP\'s own kernel smoother. It needs 3 distinct X values.' },
      { key: 'lambda', label: 'Lambda', type: 'log', dflt: 0.05, min: 1e-4, max: 1e4, when: spline, shows: 'with the Spline method', help: 'The spline\'s smoothing penalty λ, from 0.0001 to 10,000 (JMP\'s default 0.05): larger is smoother and tends to the least squares line, smaller follows the points more closely. X is standardized first, so a λ smooths alike whatever X\'s units. Drag the slider (on a log scale) or type a value in the box beside it.' },
      { key: 'width', label: 'Local Width', type: 'number', dflt: 0.667, min: 0.05, max: 1, step: 0.05, when: lowessM, shows: 'with the Local Kernel method', help: 'The share of the points each local fit uses, 0.05 to 1 (lowess\'s frac; the default 0.667 is its 2/3). Larger is smoother.' },
      { key: 'robust', label: 'Local Robustness', type: 'number', dflt: 3, min: 0, max: 6, step: 1, when: lowessM, shows: 'with the Local Kernel method', help: 'How many times lowess refits with the points of large residuals down-weighted (its it), 0 to 6 (default 3): more makes the curve less sensitive to outliers, 0 is a plain local fit.' },
      { key: 'conf', label: 'Confidence of Fit', type: 'check', dflt: false, when: spline, shows: 'with the Spline method', help: 'A band around the spline from 100 bootstrap resamples of the rows (fewer above 2000 rows): the fit plus and minus z(1 − α/2) times their standard deviation, α from Set Alpha Level. The resamples come from a fixed seed, so the band is the same at every redraw.' },
    ] },
    { type: 'fit', label: 'Line of Fit', z: 82, needs: 'xy-cont', about: 'A fitted line (or polynomial curve) with its confidence band, for each group. Needs continuous X and Y.', props: [
      { key: 'fitType', label: 'Fit', type: 'select', choices: [['polynomial', 'Polynomial'], ['robust', 'Robust Cauchy']], dflt: 'polynomial', help: '**Polynomial** (the default): least squares, statsmodels OLS. **Robust Cauchy**: statsmodels\' RLM with Cauchy weights (c = 2.3849), which give outlying points little weight; its band uses the normal quantile, and it has no prediction band, R² or F test.' },
      { key: 'degree', label: 'Degree', type: 'select', choices: [[1, 'Linear'], [2, 'Quadratic'], [3, 'Cubic']], dflt: 1, help: 'The polynomial\'s degree: **Linear** (the default), **Quadratic** or **Cubic**. The Equation is written as JMP writes it, b0 + b1·x + b2·(x − mean)² + b3·(x − mean)³. A fit of degree d needs more than d + 1 rows and d + 1 distinct X values.' },
      { key: 'confFit', label: 'Confidence of Fit', type: 'check', dflt: true, help: 'The shaded band around the line, on by default: where the mean of Y lies at each X, at 1 − α (Set Alpha Level in the red triangle).' },
      { key: 'confPred', label: 'Confidence of Prediction', type: 'check', dflt: false, when: (e) => e.fitType !== 'robust', shows: 'with a Polynomial fit', help: 'Dashed lines of the prediction interval: where the Y of one new row would fall at each X, at 1 − α; wider than the band of the fit.' },
      { key: 'equation', label: 'Equation', type: 'check', dflt: false, help: 'Writes the fitted equation in the panel\'s top left corner, one for each group.' },
      { key: 'r2', label: 'R²', type: 'check', dflt: false, when: (e) => e.fitType !== 'robust', shows: 'with a Polynomial fit', help: 'Writes R², the share of the variance of Y that the fit explains, in the corner.' },
      { key: 'rmse', label: 'Root Mean Square Error', type: 'check', dflt: false, help: 'Writes the root mean square error, the residuals\' standard deviation (for Robust Cauchy, RLM\'s robust estimate of their scale), in the corner.' },
      { key: 'ftest', label: 'F Test', type: 'check', dflt: false, when: (e) => e.fitType !== 'robust', shows: 'with a Polynomial fit', help: 'Writes the F test of the fit against a flat line at the mean of Y (every term but the intercept zero), with its p-value, in the corner.' },
    ] },
    { type: 'ellipse', label: 'Ellipse', z: 70, needs: 'xy-cont', about: 'The density ellipse of the bivariate normal with the means, standard deviations and correlation of X and Y, for each group. Needs continuous X and Y.', props: [
      { key: 'coverage', label: 'Coverage', type: 'select', choices: [[0.99, '99%'], [0.95, '95%'], [0.9, '90%'], [0.5, '50%']], dflt: 0.95, help: 'The share of the fitted normal inside the ellipse: 99%, 95% (the default), 90% or 50% (its radius² is the χ²(2) quantile of it). About that share of the points falls inside when X and Y are close to normal.' },
      { key: 'shaded', label: 'Shaded', type: 'check', dflt: false, help: 'Fills the ellipse with a light shade of its colour.' },
      { key: 'correlation', label: 'Correlation', type: 'check', dflt: false, help: 'Writes the correlation r of X and Y (Pearson\'s, Freq counted) in the panel\'s lower right corner, one for each group.' },
      { key: 'meanPoint', label: 'Mean Point', type: 'check', dflt: false, help: 'Marks the means of X and Y with a cross.' },
    ] },
    { type: 'contour', label: 'Contour', z: 40, needs: 'contour', about: 'With continuous X and Y, the contours of a kernel density that hold given shares of the points (scipy\'s gaussian_kde); with one categorical axis, a violin of the other variable\'s density for each level.', props: [
      { key: 'levels', label: 'Number of Levels', type: 'number', dflt: 4, min: 1, max: 20, step: 1, help: 'How many contours, 1 to 20 (default 4), for continuous X and Y: they hold 100%, (L − 1)/L, … and 1/L of the points, so the default 4 draws the regions of the densest 25%, 50%, 75% and all of them. Violins do not use it.' },
      { key: 'fill', label: 'Fill', type: 'check', dflt: true, help: 'Shades the regions between the contours, darker where the points are densest; for violins, fills them. On by default.' },
      { key: 'line', label: 'Line', type: 'check', dflt: true, help: 'Draws the contour lines (for violins, their outlines). On by default.' },
      { key: 'bw', label: 'Bandwidth Scale', type: 'number', dflt: 1, min: 0.2, max: 5, step: 0.1, help: 'Multiplies the kernel\'s bandwidth, Scott\'s rule, by this factor, 0.2 to 5 (default 1): above 1 the contours are smoother, below 1 they show more detail (and more islands).' },
    ] },
    { type: 'line', label: 'Line', z: 75, needs: 'resp', about: 'A line through a statistic of the continuous variable at each level (or value) of the other axis, or through the rows in the table\'s order, for each group. Needs a continuous X or Y.', props: [
      { key: 'ordering', label: 'Ordering', type: 'select', choices: [['auto', 'Auto'], ['summarized', 'Summarized'], ['row', 'Row Order']], dflt: 'auto', help: '**Auto** (the default) and **Summarized**: a vertex for each level (or distinct value) of the other axis, at the Summary Statistic, joined in their order. **Row Order**: a vertex for every row, joined in the table\'s order, each linked to its row.' },
      { key: 'connection', label: 'Connection', type: 'select', choices: [['line', 'Line'], ['curve', 'Curve'], ['step', 'Step']], dflt: 'line', help: CONNECT_HELP },
      { key: 'summary', label: 'Summary Statistic', type: 'select', choices: STATS, dflt: 'mean', when: (e) => e.ordering !== 'row', shows: 'unless Ordering is Row Order', help: `The statistic at each vertex, Mean by default: ${STATS_HELP}.` },
      { key: 'interval', label: 'Error Interval', type: 'select', choices: INTERVALS, dflt: 'none', when: (e) => e.ordering !== 'row', shows: 'unless Ordering is Row Order', help: `An interval at each vertex. ${INTERVAL_HELP}` },
      { key: 'style', label: 'Interval Style', type: 'select', choices: [['bars', 'Error Bars'], ['band', 'Error Band']], dflt: 'bars', when: (e) => e.ordering !== 'row' && e.interval !== 'none', shows: 'with an Error Interval', help: '**Error Bars** (the default) at each vertex, or an **Error Band** shaded between the ends of the intervals.' },
    ] },
    { type: 'bar', label: 'Bar', z: 20, needs: 'factor', about: 'A bar for each level (or value) of the other axis: a statistic of the continuous variable, or the count of rows. Needs X or Y, but not two categorical columns (Mosaic and Heatmap draw those).', props: [
      { key: 'barStyle', label: 'Bar Style', type: 'select', choices: [['side', 'Side by side'], ['stacked', 'Stacked'], ['needle', 'Needle']], dflt: 'side', help: '**Side by side** (the default): with Overlay (or several columns merged on an axis) the groups\' bars stand next to one another within each level; **Stacked**: they stand on top of one another (negative values stack downwards); **Needle**: a thin line in place of each bar.' },
      { key: 'summary', label: 'Summary Statistic', type: 'select', choices: STATS, dflt: 'auto', help: `The height of each bar. **Auto** (the default): the Mean with a continuous variable, N without one. Or ${STATS_HELP}. Without a continuous variable only N and % of Total can be drawn.` },
      { key: 'interval', label: 'Error Interval', type: 'select', choices: INTERVALS, dflt: 'none', help: `Error bars on each bar. ${INTERVAL_HELP}` },
      { key: 'label', label: 'Label', type: 'select', choices: LABELS, dflt: 'none', help: '**Label by Value** writes each bar\'s height on it; **Label by Percent of Total Values** its rows\' share of the panel\'s total (of the continuous variable\'s sum, or of the count of rows); **None** (the default) writes nothing.' },
    ] },
    { type: 'area', label: 'Area', z: 10, needs: 'factor', about: 'A line through a statistic at each level (or value) of the other axis with the area under it filled, for each group. Needs X or Y, but not two categorical columns.', props: [
      { key: 'areaStyle', label: 'Area Style', type: 'select', choices: [['overlaid', 'Overlaid'], ['stacked', 'Stacked']], dflt: 'overlaid', help: '**Overlaid** (the default): each group\'s area filled down to zero, half transparent over the others; **Stacked**: the groups\' areas on top of one another, so the top edge is their total.' },
      { key: 'summary', label: 'Summary Statistic', type: 'select', choices: STATS, dflt: 'auto', help: `The height at each vertex. **Auto** (the default): the Mean with a continuous variable, N without one. Or ${STATS_HELP}.` },
      { key: 'connection', label: 'Connection', type: 'select', choices: [['line', 'Line'], ['curve', 'Curve'], ['step', 'Step']], dflt: 'line', help: CONNECT_HELP },
    ] },
    { type: 'box', label: 'Box Plot', z: 50, needs: 'resp', about: 'A box plot of the continuous variable for each level (or value) of the other axis and each group, with JMP\'s quantiles; a click on a box selects its rows. Needs a continuous X or Y.', props: [
      { key: 'outliers', label: 'Outliers', type: 'check', dflt: true, help: 'Draws the values beyond the whiskers as points, each linked to its row (Outlier box type). On by default.' },
      { key: 'boxType', label: 'Box Type', type: 'select', choices: [['outlier', 'Outlier'], ['quantile', 'Quantile']], dflt: 'outlier', help: 'The box runs from the first to the third quartile, with a line at the median. **Outlier** (the default): the whiskers reach the furthest values within 1.5 interquartile ranges of the box, and the values beyond are outliers. **Quantile**: the whiskers reach the minimum and the maximum, and no value is an outlier.' },
      { key: 'boxStyle', label: 'Box Style', type: 'select', choices: [['normal', 'Normal'], ['solid', 'Solid'], ['thin', 'Thin']], dflt: 'normal', help: '**Normal** (the default): a lightly filled box; **Solid**: a box filled with its colour; **Thin**: a narrow outline.' },
      { key: 'width', label: 'Width Proportion', type: 'number', dflt: 0.5, min: 0.05, max: 1, step: 0.05, help: 'The box\'s width as a share of its level\'s room, 0.05 to 1 (default 0.5).' },
      { key: 'diamond', label: 'Confidence Diamond', type: 'check', dflt: false, help: 'A diamond on each box: its middle at the mean, its top and bottom at the ends of the t confidence interval of the mean at 1 − α (Set Alpha Level in the red triangle).' },
    ] },
    // statsmodels' beanplot, which JMP does not have: a violin, a line per row, the mean and median.
    { type: 'bean', label: 'Bean', z: 45, needs: 'bean', about: 'statsmodels\' bean plot, not in JMP: for each level of a categorical axis (and each group), a violin of the density of the continuous variable, a short line for every row, the mean and the median. Needs a continuous X or Y, and at most a categorical column on the other axis.', props: [
      { key: 'beans', label: 'Beans', type: 'select', choices: [['lines', 'Lines'], ['jitter', 'Jittered Points'], ['none', 'None']], dflt: 'lines', help: 'The rows inside each violin: **Lines** (the default), a short line across the violin at each row\'s value (a bean), linked to its row; **Jittered Points**, a dot for each row spread across the violin\'s width at its value; **None**, no rows.' },
      { key: 'mean', label: 'Mean Line', type: 'check', dflt: true, help: 'The mean of each bean as a long line across it. On by default.' },
      { key: 'median', label: 'Median', type: 'check', dflt: true, help: 'The median of each bean as a cross. On by default.' },
      { key: 'overall', label: 'Overall Mean', type: 'check', dflt: true, help: 'A dotted line across the panel at the mean of all its rows, as Kampstra\'s bean plot draws it (statsmodels\' beanplot does not). On by default.' },
      { key: 'split', label: 'Split Two Groups', type: 'check', dflt: false, help: 'With an Overlay (or a categorical Color) of exactly two levels, and one column on each axis: the first level draws the left half of each bean and the second the right half (the lower and upper halves when the beans lie across), back to back.' },
      { key: 'cutoff', label: 'Cut at the Data', type: 'check', dflt: false, help: 'Ends each violin at the smallest and the largest value. Off (the default, as statsmodels) the density runs 1.5 standard deviations past them.' },
      { key: 'bw', label: 'Bandwidth Scale', type: 'number', dflt: 1, min: 0.2, max: 5, step: 0.1, help: 'Multiplies the bandwidth of the violins\' Gaussian kernel density (Scott\'s rule) by this factor, 0.2 to 5 (default 1): larger is smoother. Every violin is drawn to the same width, whatever the size of its group.' },
    ] },
    { type: 'histogram', label: 'Histogram', z: 25, needs: 'histogram', about: 'The distribution of one continuous variable in bins (or as a density curve); with a categorical column on the other axis, a histogram for each of its levels. Needs one continuous X or Y.', props: [
      { key: 'histStyle', label: 'Histogram Style', type: 'select', choices: [['bar', 'Bar'], ['kernel', 'Kernel Density']], dflt: 'bar', help: '**Bar** (the default): the rows counted in bins; **Kernel Density**: a Gaussian kernel density curve (scipy\'s gaussian_kde, Scott\'s bandwidth), scaled to the counts.' },
      { key: 'scale', label: 'Response Scale', type: 'select', choices: [['count', 'Count'], ['percent', 'Percent']], dflt: 'count', help: '**Count** (the default): rows in each bin (Freq counts a row that many times); **Percent**: the share of the histogram\'s rows, each group\'s and each level\'s histogram adding up to 100.' },
      { key: 'binWidth', label: 'Bin Width (empty: automatic)', type: 'number', dflt: null, min: 0, when: (e) => e.histStyle !== 'kernel', shows: 'with the Bar style', help: 'The bins\' width in the variable\'s units; they start at a whole multiple of it. Empty (the default): a round width chosen from the number of values. Every panel and group uses the same bins.' },
      { key: 'bw', label: 'Bandwidth Scale', type: 'number', dflt: 1, min: 0.2, max: 5, step: 0.1, when: (e) => e.histStyle === 'kernel', shows: 'with the Kernel Density style', help: 'Multiplies the density\'s bandwidth (Scott\'s rule) by this factor, 0.2 to 5 (default 1): larger is smoother.' },
      { key: 'counts', label: 'Counts', type: 'check', dflt: false, when: (e) => e.histStyle !== 'kernel', shows: 'with the Bar style', help: 'Writes each bin\'s count (or percent) above its bar.' },
    ] },
    { type: 'heatmap', label: 'Heatmap', z: 15, needs: 'xy', about: 'A cell for each pair of levels (or bins) of X and Y, coloured by its count of rows, or by the mean of a continuous Color column. Needs X and Y.', props: [
      { key: 'label', label: 'Label', type: 'select', choices: LABELS, dflt: 'none', help: '**Label by Value** writes each cell\'s count (or its mean of the Color column); **Label by Percent of Total Values** the cell\'s share of the panel\'s rows; **None** (the default) writes nothing.' },
      { key: 'bins', label: 'Bins on a Continuous Axis', type: 'number', dflt: 16, min: 2, max: 80, step: 1, help: 'About how many bins a continuous X or Y is cut into, 2 to 80 (default 16); the bins have round widths, so their number can differ a little. A categorical axis has a cell for each level.' },
    ] },
    { type: 'mosaic', label: 'Mosaic', z: 5, needs: 'cat-cat', exclusive: true, about: 'The contingency table of X and Y as areas: a column for each X level as wide as its share of the rows, split by the shares of the Y levels within it. Needs categorical X and Y, and is drawn alone.', props: [
      { key: 'cellLabel', label: 'Cell Labeling', type: 'select', choices: [['none', 'None'], ['count', 'Label by Count'], ['percent', 'Label by Percent']], dflt: 'none', help: '**Label by Count** writes the rows in each cell; **Label by Percent** the cell\'s share of its X level (its height); **None** (the default) writes nothing.' },
      { key: 'chisq', label: 'Chi-square Test', type: 'check', dflt: false, help: 'Writes Pearson\'s chi-square test of independence of X and Y above each panel (scipy\'s chi2_contingency, without a continuity correction): χ², its degrees of freedom and the p-value. A note says so when an expected count is below 5 and the p-value is only approximate.' },
    ] },
    { type: 'caption', label: 'Caption Box', z: 90, needs: 'resp', about: 'A box of summary statistics of the continuous variable, for each group. Needs a continuous X or Y.', props: [
      { key: 'stats', label: 'Summary Statistic', type: 'multi', choices: STATS.filter((s) => s[0] !== 'pct'), dflt: ['mean'], max: 5, help: 'Tick up to five statistics (the Mean by default): N, Mean, Median, Sum, Min, Max, Range, Std Dev, Std Err, Variance, First and Third Quartile.' },
      { key: 'location', label: 'Location', type: 'select', choices: [['graph', 'Graph'], ['factor', 'Graph per factor']], dflt: 'graph', help: '**Graph** (the default): a box in the top right corner of each panel (one for each group), over all its rows; **Graph per factor**: a box at each level of the other axis.' },
    ] },
    { type: 'pie', label: 'Pie', z: 5, needs: 'factor', exclusive: true, about: 'A slice for each level of the categorical axis: its count of rows, or the sum or mean of a continuous variable. Needs X or Y, but not two categorical columns, and is drawn alone.', props: [
      { key: 'pieStyle', label: 'Pie Style', type: 'select', choices: [['pie', 'Pie'], ['ring', 'Ring']], dflt: 'pie', help: '**Pie** (the default), or **Ring**, with a hole in the middle.' },
      { key: 'summary', label: 'Summary Statistic', type: 'select', choices: [['n', 'N'], ['sum', 'Sum'], ['mean', 'Mean']], dflt: 'auto', help: 'The size of each slice. **Auto** (the default): the Sum of the continuous variable, or N without one; or **N**, **Sum** or **Mean**. Without a continuous variable the slices are always N; a negative value makes an empty slice.' },
      { key: 'label', label: 'Label', type: 'select', choices: [['percent', 'Label by Percent of Total Values'], ['value', 'Label by Value'], ['level', 'Label by Level'], ['none', 'None']], dflt: 'percent', help: 'What each slice says: its **Percent** of the pie (the default), its **Value**, its **Level**, or nothing.' },
    ] },
  ];
  const ELEMENT = Object.fromEntries(ELEMENTS.map((e) => [e.type, e]));

  /* What the X and Y columns make of the axes: the response is the
     continuous one (Y when both are), the factor the other. */
  function axesRoles(xc, yc) {
    const xk = xc ? (isCat(xc) ? 'cat' : 'cont') : null;
    const yk = yc ? (isCat(yc) ? 'cat' : 'cont') : null;
    if (yk === 'cont') return { resp: yc, fac: xc, horiz: false, facCat: xk === 'cat', xk, yk };
    if (xk === 'cont') return { resp: xc, fac: yc, horiz: true, facCat: yk === 'cat', xk, yk };
    if (xk === 'cat' && !yk) return { resp: null, fac: xc, horiz: false, facCat: true, xk, yk };
    if (yk === 'cat' && !xk) return { resp: null, fac: yc, horiz: true, facCat: true, xk, yk };
    return { resp: null, fac: null, horiz: false, facCat: false, xk, yk, both: xk === 'cat' && yk === 'cat' };
  }

  /* Why an element cannot draw these columns, or null. */
  function elementRefuses(type, xc, yc) {
    const R = axesRoles(xc, yc);
    const L = ELEMENT[type].label;
    switch (ELEMENT[type].needs) {
      case 'any': return xc || yc ? null : `${L} needs X or Y`;
      case 'xy-cont': return R.xk === 'cont' && R.yk === 'cont' ? null : `${L} needs continuous X and Y`;
      case 'contour': return (R.xk === 'cont' && R.yk === 'cont') || (R.resp && R.facCat) ? null : `${L} needs continuous X and Y (a density), or one continuous and one categorical (a violin)`;
      case 'resp': return R.resp ? null : `${L} needs a continuous X or Y`;
      case 'bean': return R.resp && (!R.fac || R.facCat) ? null : `${L} needs a continuous X or Y, and at most a categorical column on the other axis`;
      case 'factor': return R.resp || R.fac ? (R.both ? `${L} takes one categorical and one continuous variable, or one categorical alone` : null) : `${L} needs X or Y`;
      case 'histogram': return (R.xk === 'cont') !== (R.yk === 'cont') && !(R.xk === 'cont' && R.yk === 'cont') && (R.fac == null || R.facCat) ? null : `${L} needs one continuous variable, and at most a categorical one on the other axis`;
      case 'xy': return xc && yc ? null : `${L} needs X and Y`;
      case 'cat-cat': return R.xk === 'cat' && R.yk === 'cat' ? null : `${L} needs categorical X and Y`;
      default: return null;
    }
  }

  /* JMP's choice of elements for the columns in the zones. */
  function autoElements(xc, yc) {
    const R = axesRoles(xc, yc);
    if (!xc && !yc) return [];
    if (R.xk === 'cont' && R.yk === 'cont') return ['points', 'smoother'];
    if (!R.resp && R.fac && !R.both) return ['bar'];
    return ['points'];
  }

  function elementDefaults(type) {
    const out = { type };
    for (const p of ELEMENT[type].props) out[p.key] = clone(p.dflt);
    return out;
  }

  /* ---- the element icons of the palette ------------------------------------------------ */
  function icon(type) {
    const s = (attrs, ...kids) => svg('svg', { viewBox: '0 0 24 18', width: 24, height: 18, 'aria-hidden': 'true', class: 'sm-gb-icon', ...attrs }, ...kids);
    const P = (d, extra = {}) => svg('path', { d, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', ...extra });
    const dot = (x, y, r = 1.6) => svg('circle', { cx: x, cy: y, r, fill: 'currentColor' });
    const rect = (x, y, w, h, extra = {}) => svg('rect', { x, y, width: w, height: h, fill: 'currentColor', ...extra });
    switch (type) {
      case 'points': return s({}, dot(5, 13), dot(9, 10), dot(12, 12), dot(15, 6), dot(19, 5), dot(17, 9));
      case 'smoother': return s({}, dot(4, 13, 1.1), dot(9, 9, 1.1), dot(14, 10, 1.1), dot(19, 5, 1.1), P('M2 14 C7 6, 12 13, 22 3'));
      case 'fit': return s({}, dot(5, 12, 1.1), dot(10, 11, 1.1), dot(15, 6, 1.1), dot(19, 6, 1.1), P('M2 15 L22 3'));
      case 'ellipse': return s({}, svg('ellipse', { cx: 12, cy: 9, rx: 9, ry: 4.5, transform: 'rotate(-28 12 9)', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5 }), dot(12, 9, 1.2));
      case 'contour': return s({}, P('M4 10 C4 3, 20 2, 20 8 C20 15, 4 16, 4 10 Z'), P('M8 9.5 C8 6, 16 5.5, 16 8.5 C16 12, 8 12.5, 8 9.5 Z'));
      case 'line': return s({}, P('M2 14 L7 8 L12 11 L17 4 L22 7'));
      case 'bar': return s({}, rect(3, 8, 4, 8), rect(10, 3, 4, 13), rect(17, 10, 4, 6));
      case 'area': return s({}, svg('path', { d: 'M2 16 L2 11 L8 6 L14 9 L22 3 L22 16 Z', fill: 'currentColor', opacity: 0.55 }), P('M2 11 L8 6 L14 9 L22 3'));
      case 'box': return s({}, P('M12 1 L12 5 M12 13 L12 17 M9 1 L15 1 M9 17 L15 17'), svg('rect', { x: 7, y: 5, width: 10, height: 8, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5 }), P('M7 9 L17 9'));
      case 'bean': return s({}, P('M12 1 C15 4, 16.5 7, 14.5 9 C17.5 11, 16 15, 12 17 C8 15, 6.5 11, 9.5 9 C7.5 7, 9 4, 12 1 Z', { 'stroke-width': 1.2 }), P('M10 5.5 L14 5.5 M9.5 8 L14.5 8 M8.5 11 L15.5 11 M9.5 13.5 L14.5 13.5', { 'stroke-width': 0.9 }), P('M7.5 9.5 L16.5 9.5', { 'stroke-width': 1.8 }));
      case 'histogram': return s({}, rect(2, 11, 4, 5), rect(6, 6, 4, 10), rect(10, 2, 4, 14), rect(14, 7, 4, 9), rect(18, 12, 4, 4));
      case 'heatmap': return s({}, rect(3, 2, 6, 5, { opacity: 0.35 }), rect(9, 2, 6, 5, { opacity: 0.8 }), rect(15, 2, 6, 5, { opacity: 0.5 }), rect(3, 7, 6, 5, { opacity: 0.9 }), rect(9, 7, 6, 5, { opacity: 0.25 }), rect(15, 7, 6, 5, { opacity: 0.65 }), rect(3, 12, 6, 5, { opacity: 0.5 }), rect(9, 12, 6, 5, { opacity: 0.7 }), rect(15, 12, 6, 5, { opacity: 0.3 }));
      case 'mosaic': return s({}, rect(2, 2, 8, 6, { opacity: 0.85 }), rect(2, 9, 8, 7, { opacity: 0.4 }), rect(11, 2, 11, 10, { opacity: 0.6 }), rect(11, 13, 11, 3, { opacity: 0.3 }));
      case 'caption': return s({}, svg('rect', { x: 3, y: 2, width: 18, height: 14, rx: 2, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.3 }), P('M6 7 L18 7 M6 11 L14 11'));
      case 'pie': return s({}, svg('circle', { cx: 12, cy: 9, r: 7, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5 }), svg('path', { d: 'M12 9 L12 2 A7 7 0 0 1 18.6 11.3 Z', fill: 'currentColor' }));
      default: return s({});
    }
  }

  /* ---- Graph Builder: the state ----------------------------------------------------------
     spec.options.gb holds everything a redo or a saved project needs. A
     zone entry is { id, name }: the id within the session, the name when a
     project is opened again (the ids are new then). */
  function defaultState() {
    return {
      v: 1, zones: Object.fromEntries(ZONES.map((z) => [z.key, []])), xMode: 'side', yMode: 'side',
      elements: [], auto: true, title: null, labels: {}, show: { title: true, legend: true, xTitle: true, yTitle: true },
      legendPos: 'right', done: false, size: null, alpha: 0.05,
    };
  }

  function resolveRef(t, ref) {
    if (!t || !ref) return null;
    const byId = t.columns.find((c) => c.id === ref.id) || null;
    if (byId && byId.name === ref.name) return byId;
    return t.columns.find((c) => c.name === ref.name) || byId;
  }

  function normalize(S0, t) {
    const d = defaultState();
    const S = { ...d, ...(S0 || {}) };
    S.zones = { ...d.zones, ...(S.zones || {}) };
    S.show = { ...d.show, ...(S.show || {}) };
    S.labels = S.labels || {};
    for (const z of ZONES) {
      const list = [];
      for (const ref of S.zones[z.key] || []) {
        const c = resolveRef(t, ref);
        if (!c || list.some((x) => x.id === c.id) || zoneRefuses(z, c)) continue;
        list.push({ id: c.id, name: c.name });
      }
      S.zones[z.key] = list.slice(0, z.max);
    }
    if (S.auto) {
      const xc = S.zones.x[0] ? t.col(S.zones.x[0].id) : null;
      const yc = S.zones.y[0] ? t.col(S.zones.y[0].id) : null;
      const old = new Map((S.elements || []).map((e) => [e.type, e]));
      S.elements = autoElements(xc, yc).map((type) => old.get(type) || elementDefaults(type));
    }
    S.elements = (S.elements || []).filter((e) => e && ELEMENT[e.type]).map((e) => ({ ...elementDefaults(e.type), ...e }));
    return S;
  }

  function zoneCols(S, t) {
    return Object.fromEntries(ZONES.map((z) => [z.key, (S.zones[z.key] || []).map((ref) => t.col(ref.id)).filter(Boolean)]));
  }

  function defaultTitle(cols) {
    const n = (list) => list.map((c) => c.name).join(' & ');
    if (cols.x.length && cols.y.length) return `${n(cols.y)} vs. ${n(cols.x)}`;
    return n(cols.x.length ? cols.x : cols.y);
  }

  /* The groups a column makes (Group X, Group Y, Wrap, Overlay): its levels,
     or for a continuous column with many values five bins of about equal
     counts. code[r] is the group of row r, -1 when missing. */
  function groupsOf(t, c, rows) {
    const code = new Int32Array(t.nrows).fill(-1);
    let distinct = new Set();
    if (!isCat(c)) for (const r of rows) { const v = c.values[r]; if (Number.isFinite(v)) { distinct.add(v); if (distinct.size > 10) break; } }
    if (isCat(c) || distinct.size <= 10) {
      const lv = levelsAmong(t, c, rows);
      const m = new Map(lv.map((v, i) => [v, i]));
      for (const r of rows) { const k = m.get(c.values[r]); if (k != null) code[r] = k; }
      return { col: c, labels: lv.map((v) => cellText(c, v)), code };
    }
    const vals = rows.map((r) => c.values[r]).filter(Number.isFinite).sort((a, b) => a - b);
    const edges = [vals[0]];
    for (const p of [0.2, 0.4, 0.6, 0.8]) { const v = vals[Math.floor(p * (vals.length - 1))]; if (v > edges[edges.length - 1]) edges.push(v); }
    if (vals[vals.length - 1] > edges[edges.length - 1]) edges.push(vals[vals.length - 1]);
    for (const r of rows) {
      const v = c.values[r];
      if (!Number.isFinite(v)) continue;
      let k = 0;
      while (k < edges.length - 2 && v > edges[k + 1]) k++;
      code[r] = k;
    }
    const labels = [];
    for (let k = 0; k < edges.length - 1; k++) labels.push(`${fmt(edges[k])}–${fmt(edges[k + 1])}`);
    return { col: c, labels, code, binned: true };
  }

  /* ---- Graph Builder: the figure ------------------------------------------------------------ */
  const ORDER_OF = (type) => ELEMENT[type].z;

  async function buildFigure(B) {
    const { ctx, S } = B;
    const t = ctx.table;
    const cols = zoneCols(S, t);
    const fig = { traces: [], links: [], annotations: [], shapes: [], notes: [], codes: [], axisKeys: {}, mask: false, empty: false };
    if (!cols.x.length && !cols.y.length) { fig.empty = true; return fig; }
    const E = new Env(B, cols, fig);
    await E.build();
    return fig;
  }

  class Env {
    constructor(B, cols, fig) {
      this.B = B;
      this.ctx = B.ctx;
      this.S = B.S;
      this.t = B.ctx.table;
      this.cols = cols;
      this.fig = fig;
      this.notes = fig.notes;
      this.freqCol = cols.freq[0] || null;
      this.freqName = this.freqCol ? this.freqCol.name : null;
      const f = this.freqCol;
      this.rows0 = f ? B.ctx.rows.filter((r) => Number.isFinite(f.values[r]) && f.values[r] > 0) : B.ctx.rows.slice();
      this.W = f ? (r) => f.values[r] : () => 1;
      this.levelCache = new Map();
      this.legendSeen = new Set();
      this.anyLegend = false;
    }

    note(s) { if (!this.notes.includes(s)) this.notes.push(s); }

    /* The levels of a categorical axis column, over all the rows. */
    axisLevels(c) {
      let L = this.levelCache.get(c.id);
      if (!L) {
        const lv = levelsAmong(this.t, c, this.rows0);
        L = { lv, pos: new Map(lv.map((v, i) => [v, i])), labels: lv.map((v) => cellText(c, v)) };
        this.levelCache.set(c.id, L);
      }
      return L;
    }

    levelPos(c, v) { const p = this.axisLevels(c).pos.get(v); return p == null ? null : p; }

    /* The coordinate of row r for column c on its axis: a level's position,
       a value, or 0 on an empty axis; null when missing. */
    at(c, r) {
      if (!c) return 0;
      const v = c.values[r];
      if (isCat(c)) return isMissing(v) ? null : this.levelPos(c, v);
      return Number.isFinite(v) ? v : null;
    }

    async call(fn, payload) {
      if (this.B.noPython) { const e = new Error('waiting for Python'); e.waiting = true; throw e; }
      const res = await this.ctx.call(fn, payload);
      if (res && res.code && !this.fig.codes.includes(res.code)) this.fig.codes.push(res.code);
      return res;
    }

    async build() {
      const { S, cols, t, fig } = this;
      // ---- the elements, in drawing order; Mosaic and Pie draw alone
      let els = S.elements.slice().sort((a, b) => ORDER_OF(a.type) - ORDER_OF(b.type));
      const excl = els.find((e) => ELEMENT[e.type].exclusive);
      if (excl && els.length > 1) { this.note(`${ELEMENT[excl.type].label} is drawn alone; the other elements are left out.`); els = [excl]; }
      this.exclusive = excl ? excl.type : null;
      // ---- groups: Overlay, else a categorical Color
      const colorCol = cols.color[0] || null;
      this.colorCol = colorCol;
      const gcol = cols.overlay[0] || (colorCol && isCat(colorCol) ? colorCol : null);
      this.G = gcol ? groupsOf(t, gcol, this.rows0) : null;
      if (this.G && this.G.labels.length > 60) { this.note(`${gcol.name} has ${this.G.labels.length} levels; the groups use the first 60.`); }
      if (this.G) { let miss = 0; for (const r of this.rows0) if (this.G.code[r] < 0) miss++; if (miss) this.note(`${miss} row${miss > 1 ? 's' : ''} with no ${gcol.name} ${miss > 1 ? 'are' : 'is'} left out of the groups.`); }
      this.fig.mask = !!colorCol;
      if (colorCol && !isCat(colorCol)) this.colorRange = extent(this.rows0.map((r) => colorCol.values[r]));
      if (colorCol && isCat(colorCol)) this.colorLv = this.axisLevels(colorCol);
      const sizeCol = cols.size[0] || null;
      this.sizeCol = sizeCol;
      if (sizeCol) this.sizeRange = extent(this.rows0.map((r) => sizeCol.values[r]));
      this.byNames = [cols.wrap[0], cols.groupX[0], cols.groupY[0], gcol].filter(Boolean).map((c) => c.name);
      // ---- panels
      this.makePanels();
      const first = this.panels[0];
      const s0 = first.series[0];
      // ---- which elements can draw these columns
      const ok = [];
      for (const e of els) {
        const why = elementRefuses(e.type, s0.xc, s0.yc);
        if (why) this.note(`${why}.`); else ok.push(e);
      }
      this.els = ok;
      this.gl = webgl() && ok.some((e) => e.type === 'points' && (!e.summary || e.summary === 'none')) && this.rows0.length * Math.max(1, ...this.panels.map((P) => P.series.length)) > GL_POINTS;
      this.decideAxes(ok);
      for (const e of ok) {
        try { await RENDER[e.type](this, e); } catch (err) {
          if (err.waiting) { this.note(`${ELEMENT[e.type].label} follows when the Python engine has loaded.`); continue; }
          console.error(err);
          this.note(`${ELEMENT[e.type].label}: ${err.message || err}`);
        }
      }
      this.layout();
    }

    /* ---- the panels: Group X by Group Y (or Wrap), times the X and Y
       columns that stand side by side. */
    makePanels() {
      const { S, cols, t } = this;
      const wrapC = cols.wrap[0] || null;
      const gxC = wrapC ? null : (cols.groupX[0] || null);
      const gyC = wrapC ? null : (cols.groupY[0] || null);
      if (wrapC && (cols.groupX.length || cols.groupY.length)) this.note('Wrap is used; Group X and Group Y wait until Wrap is empty.');
      const xs = cols.x, ys = cols.y;
      const xSide = S.xMode !== 'merge' && xs.length > 1, ySide = S.yMode !== 'merge' && ys.length > 1;
      const xSets = xs.length ? (xSide ? xs.map((c) => [c]) : [xs]) : [[]];
      const ySets = ys.length ? (ySide ? ys.map((c) => [c]) : [ys]) : [[]];
      const series = (xset, yset) => {
        const out = [];
        const xl = xset.length ? xset : [null], yl = yset.length ? yset : [null];
        // Merged columns share an axis: one kind (and for categorical columns, one column) per axis.
        const okOn = (list) => list.filter((c, i) => !c || i === 0 || (!isCat(c) && !isCat(list[0])));
        const xo = okOn(xl), yo = okOn(yl);
        if (xo.length < xl.length || yo.length < yl.length) this.note('Merged columns share an axis: only continuous columns merge; the others are left out.');
        for (const xc of xo) for (const yc of yo) out.push({ xc, yc });
        return out;
      };
      this.xSide = xSide; this.ySide = ySide;
      this.wrap = wrapC ? groupsOf(t, wrapC, this.rows0) : null;
      this.gx = gxC ? groupsOf(t, gxC, this.rows0) : null;
      this.gy = gyC ? groupsOf(t, gyC, this.rows0) : null;
      const panels = [];
      if (this.wrap) {
        const k = Math.max(1, this.wrap.labels.length);
        const nC = Math.ceil(Math.sqrt(k)), nR = Math.ceil(k / nC);
        const buckets = Array.from({ length: k }, () => []);
        for (const r of this.rows0) { const w = this.wrap.code[r]; if (w >= 0) buckets[w].push(r); }
        this.wrap.labels.forEach((lab, i) => panels.push({ r: Math.floor(i / nC), c: i % nC, rows: buckets[i], xset: xs, yset: ys, series: series(xs, ys), wrapLabel: lab }));
        this.nR = nR; this.nC = nC;
      } else {
        const GX = this.gx ? this.gx.labels : [null], GY = this.gy ? this.gy.labels : [null];
        const buckets = new Map();
        for (const r of this.rows0) {
          const a = this.gx ? this.gx.code[r] : 0, b = this.gy ? this.gy.code[r] : 0;
          if (a < 0 || b < 0) continue;
          const key = b * 100000 + a;
          let l = buckets.get(key);
          if (!l) { l = []; buckets.set(key, l); }
          l.push(r);
        }
        GY.forEach((gyl, b) => ySets.forEach((yset, yi) => GX.forEach((gxl, a) => xSets.forEach((xset, xi) => {
          panels.push({ r: b * ySets.length + yi, c: a * xSets.length + xi, rows: buckets.get(b * 100000 + a) || [], xset, yset, series: series(xset, yset), gxLabel: gxl, gyLabel: gyl, gxi: a, gyi: b });
        }))));
        this.nR = GY.length * ySets.length; this.nC = GX.length * xSets.length;
      }
      panels.forEach((P, i) => {
        P.idx = i;
        P.xa = i === 0 ? 'x' : `x${i + 1}`;
        P.ya = i === 0 ? 'y' : `y${i + 1}`;
        if (this.G) {
          P.byGroup = this.G.labels.map(() => []);
          for (const r of P.rows) { const g = this.G.code[r]; if (g >= 0) P.byGroup[g].push(r); }
        }
      });
      // below / left neighbours, for the ticks and titles on the outer panels
      const at = new Map(panels.map((P) => [`${P.r}|${P.c}`, P]));
      for (const P of panels) {
        P.bottom = !at.has(`${P.r + 1}|${P.c}`);
        P.left = P.c === 0;
      }
      this.panels = panels;
      this.nSeries = Math.max(1, ...panels.map((P) => P.series.length));
    }

    /* Each (panel, series, group) with its rows. */
    forCells(fn) {
      for (const P of this.panels) {
        P.series.forEach((s, si) => {
          if (!this.G) fn(P, s, si, -1, P.rows);
          else this.G.labels.slice(0, 60).forEach((_, gi) => fn(P, s, si, gi, P.byGroup[gi]));
        });
      }
    }

    colorFor(si, gi, dflt) {
      if (gi >= 0) return PALETTE[gi % PALETTE.length];
      if (this.nSeries > 1) return PALETTE[si % PALETTE.length];
      return dflt;
    }

    seriesName(s) {
      const P0 = this.panels[0];
      const multiX = P0.series.some((q) => q.xc !== P0.series[0].xc);
      const multiY = P0.series.some((q) => q.yc !== P0.series[0].yc);
      if (multiX && multiY) return `${s.yc ? s.yc.name : ''} vs. ${s.xc ? s.xc.name : ''}`;
      return (multiX ? s.xc : s.yc || s.xc)?.name || '';
    }

    /* The legend of a trace: once per group (or merged column). */
    legend(si, gi) {
      if (gi >= 0) {
        const key = `g${gi}`;
        const first = !this.legendSeen.has(key);
        this.legendSeen.add(key);
        this.anyLegend = true;
        return { name: esc(this.G.labels[gi]), legendgroup: key, showlegend: first };
      }
      if (this.nSeries > 1) {
        const P0 = this.panels[0];
        const s = P0.series[si] || P0.series[0];
        const key = `s${si}`;
        const first = !this.legendSeen.has(key);
        this.legendSeen.add(key);
        this.anyLegend = true;
        return { name: esc(this.seriesName(s)), legendgroup: key, showlegend: first };
      }
      return { showlegend: false };
    }

    /* A point's colour: the Color column (gradient or levels), else its
       group's or column's colour. */
    rowColor(r, si, gi) {
      const c = this.colorCol;
      if (c && !isCat(c)) {
        const v = c.values[r];
        if (!Number.isFinite(v) || !this.colorRange) return dark() ? '#777' : '#aaa';
        const [lo, hi] = this.colorRange;
        return SM.util.ramp(hi > lo ? (v - lo) / (hi - lo) : 0.5);
      }
      if (c && isCat(c)) {
        const k = this.colorLv.pos.get(c.values[r]);
        return k == null ? (dark() ? '#777' : '#aaa') : PALETTE[k % PALETTE.length];
      }
      return this.colorFor(si, gi, pointColor());
    }

    rowSize(r) {
      const c = this.sizeCol;
      if (!c || !this.sizeRange) return 6;
      const v = c.values[r];
      if (!Number.isFinite(v)) return 3;
      const [lo, hi] = this.sizeRange;
      return 4 + 18 * Math.sqrt(hi > lo ? (v - lo) / (hi - lo) : 0.5);
    }

    lineType() { return this.gl ? 'scattergl' : 'scatter'; }

    /* The width of one factor position: 1 for levels, the smallest gap for values. */
    band(fac) {
      if (!fac || isCat(fac)) return 1;
      let b = this.bandCache && this.bandCache.get(fac.id);
      if (b) return b;
      const u = [...new Set(this.rows0.map((r) => fac.values[r]).filter(Number.isFinite))].sort((a, z) => a - z);
      let g = Infinity;
      for (let i = 1; i < u.length; i++) g = Math.min(g, u[i] - u[i - 1]);
      b = Number.isFinite(g) && g > 0 ? g : (u.length ? Math.abs(u[0]) || 1 : 1);
      (this.bandCache || (this.bandCache = new Map())).set(fac.id, b);
      return b;
    }

    /* Side by side: how many slots a factor position holds, and which one. */
    slots() { return (this.G ? Math.min(60, this.G.labels.length) : 1) * (this.nSeries > 1 ? this.nSeries : 1); }
    slotOf(si, gi) { return (this.nSeries > 1 ? si : 0) * (this.G ? Math.min(60, this.G.labels.length) : 1) + (gi >= 0 ? gi : 0); }

    /* The factor positions of one (panel, series, group), with their rows. */
    items(R, rows) {
      const { fac, resp } = R;
      const buckets = new Map();
      for (const r of rows) {
        if (resp && !Number.isFinite(resp.values[r])) continue;
        let key;
        if (!fac) key = 0;
        else if (isCat(fac)) { key = this.levelPos(fac, fac.values[r]); if (key == null) continue; }
        else { key = fac.values[r]; if (!Number.isFinite(key)) continue; }
        let b = buckets.get(key);
        if (!b) { b = []; buckets.set(key, b); }
        b.push(r);
      }
      return [...buckets.keys()].sort((a, b) => a - b).map((k) => ({ pos: k, rows: buckets.get(k), label: fac ? (isCat(fac) ? this.axisLevels(fac).labels[k] : cellText(fac, k)) : '' }));
    }

    /* Statistics of the items of several blocks: N and Sum counted here, the
       rest from graph.summary (one call per response column). */
    async fillStats(blocks, stats, { boxes = false } = {}) {
      const want = new Set();
      for (const s of stats) {
        if (s === 'mean') want.add('mean');
        else if (s === 'median') want.add('median');
        else if (s === 'min' || s === 'max' || s === 'range') { want.add('min'); want.add('max'); }
        else if (['sd', 'se', 'var', 'q1', 'q3'].includes(s)) want.add(s);
        else if (s === 'ci') { want.add('lower'); want.add('upper'); want.add('mean'); }
        else if (s === 'iqr') { want.add('q1'); want.add('q3'); }
        else if (s === 'sdI') { want.add('sd'); want.add('mean'); }
        else if (s === 'seI') { want.add('se'); want.add('mean'); }
      }
      if (boxes) ['quantiles', 'lo_whisker', 'hi_whisker', 'mean', 'lower', 'upper'].forEach((k) => want.add(k));
      for (const b of blocks) for (const it of b.items) {
        let n = 0, s = 0;
        const resp = b.R.resp;
        for (const r of it.rows) { const w = this.W(r); n += w; if (resp) s += w * resp.values[r]; }
        it.n = n; it.sum = resp ? s : null;
      }
      if (!want.size) return;
      const byResp = new Map();
      for (const b of blocks) {
        if (!b.R.resp) continue;
        const k = b.R.resp.id;
        if (!byResp.has(k)) byResp.set(k, []);
        byResp.get(k).push(b);
      }
      for (const list of byResp.values()) {
        const rows = [], codes = [], items = [];
        for (const b of list) for (const it of b.items) { items.push(it); const c = items.length - 1; for (const r of it.rows) { rows.push(r); codes.push(c); } }
        if (!items.length) continue;
        const res = await this.call('graph.summary', { y: list[0].R.resp.name, rows, codes, k: items.length, freq: this.freqName, alpha: this.S.alpha || 0.05, boxes, want: [...want], by: this.byNames.concat(list[0].R.fac ? [list[0].R.fac.name] : []) });
        items.forEach((it, i) => {
          for (const key of want) {
            if (key === 'quantiles') { it.quantiles = {}; for (const [q, arr] of Object.entries(res.quantiles || {})) it.quantiles[q] = arr[i]; } else it[key] = res[key] ? res[key][i] : null;
          }
        });
      }
    }

    statValue(it, stat, total) {
      switch (stat) {
        case 'n': return it.n;
        case 'sum': return it.sum;
        case 'pct': return total ? 100 * (it.sum != null ? it.sum : it.n) / total : null;
        case 'range': return it.max != null && it.min != null ? it.max - it.min : null;
        default: return it[stat] ?? null;
      }
    }

    interval(it, kind) {
      switch (kind) {
        case 'ci': return [it.lower, it.upper];
        case 'se': return it.mean != null && it.se != null ? [it.mean - it.se, it.mean + it.se] : [null, null];
        case 'sd': return it.mean != null && it.sd != null ? [it.mean - it.sd, it.mean + it.sd] : [null, null];
        case 'range': return [it.min, it.max];
        case 'iqr': return [it.q1, it.q3];
        default: return [null, null];
      }
    }

    intervalNeeds(kind) { return kind === 'ci' ? ['ci'] : kind === 'se' ? ['seI'] : kind === 'sd' ? ['sdI'] : kind === 'range' ? ['min'] : kind === 'iqr' ? ['iqr'] : []; }

    /* ---- axes: what each axis shows ---- */
    decideAxes(els) {
      const s0 = this.panels[0].series[0];
      const R = axesRoles(s0.xc, s0.yc);
      const kind = (c) => (c ? (isCat(c) ? 'cat' : 'cont') : 'none');
      this.xKind = kind(s0.xc);
      this.yKind = kind(s0.yc);
      // counts on an axis that has no column
      const counts = els.some((e) => ['bar', 'area', 'line'].includes(e.type) && !R.resp && R.fac) || els.some((e) => e.type === 'histogram' && !R.fac);
      this.countAxis = null;
      if (counts) {
        // Bar, Area and Line count along the response axis; a histogram's
        // counts run across its bins.
        if (els.some((e) => e.type === 'histogram') && !R.fac) this.countAxis = R.horiz ? 'y' : 'x';
        else this.countAxis = R.horiz ? 'x' : 'y';
        if (this.countAxis === 'x' && this.xKind === 'none') this.xKind = 'count';
        else if (this.countAxis === 'y' && this.yKind === 'none') this.yKind = 'count';
        else this.countAxis = null;
      }
      this.R0 = R;
    }

    countTitle() {
      const e = this.els.find((x) => ['bar', 'area', 'line', 'histogram'].includes(x.type));
      if (!e) return 'Count';
      if (e.type === 'histogram') return e.scale === 'percent' ? 'Percent' : 'Count';
      const st = e.summary === 'auto' || !e.summary ? 'n' : e.summary;
      return st === 'pct' ? '% of Total' : 'N';
    }

    axisTitle(which, P) {
      const S = this.S;
      const set = which === 'x' ? P.xset : P.yset;
      const kind = which === 'x' ? this.xKind : this.yKind;
      let text, key;
      if (kind === 'count') { text = this.countTitle(); key = `${which}:count`; }
      else if (!set.length) return null;
      else { text = set.map((c) => c.name).join(' & '); key = `${which}:${set[0].id}`; }
      if (S.labels[key] != null) text = S.labels[key];
      return { text, key };
    }

    /* ---- the layout: domains, axes, group labels, legend, title ---- */
    layout() {
      const { S, fig, B } = this;
      const tc = SM.util.themeColors();
      const legendOn = S.show.legend && this.anyLegend;
      const w = B.width(), h = B.height(this.nR);
      const legendPos = S.legendPos === 'right' && w < 520 ? 'bottom' : S.legendPos;
      const title = S.show.title ? (S.title != null ? S.title : defaultTitle(this.cols)) : null;
      const top = (title ? 30 : 8) + (this.gx ? 38 : 0) + (this.wrap ? 40 : 0) + (this.extraTop || 0);
      const right = this.gy ? 44 : 14;
      const M = { l: 60, r: right, t: top, b: 50 + (legendOn && legendPos === 'bottom' ? 36 : 0) };
      const pw = Math.max(60, w - M.l - M.r - (legendOn && legendPos === 'right' ? 130 : 0)), ph = Math.max(60, h - M.t - M.b);
      const gapX = this.nC > 1 ? (this.xKind === 'cat' ? 16 : 34) : 0, gapY = this.nR > 1 ? (this.wrap ? 34 : 16) : 0;
      const cw = (pw - gapX * (this.nC - 1)) / this.nC, rh = (ph - gapY * (this.nR - 1)) / this.nR;
      const L = { margin: M, barmode: 'overlay', hovermode: 'closest', showlegend: legendOn, annotations: fig.annotations, shapes: fig.shapes };
      if (title) L.title = { text: esc(title), x: 0.5, xanchor: 'center', y: 1, yanchor: 'top', yref: 'container', pad: { t: 8 }, font: { size: 13 } };
      const colFirst = new Map(), rowFirst = new Map();
      // Panels side by side on one X column: one X title under them all.
      const sharedX = this.nC > 1 && !this.xSide && !this.exclusive;
      for (const P of this.panels) {
        const x0 = (P.c * (cw + gapX)) / pw, x1 = (P.c * (cw + gapX) + cw) / pw;
        const y1 = 1 - (P.r * (rh + gapY)) / ph, y0 = y1 - rh / ph;
        P.dx = [clamp(x0, 0, 1), clamp(x1, 0, 1)];
        P.dy = [clamp(y0, 0, 1), clamp(y1, 0, 1)];
        const kx = P.xa === 'x' ? 'xaxis' : `xaxis${P.xa.slice(1)}`, ky = P.ya === 'y' ? 'yaxis' : `yaxis${P.ya.slice(1)}`;
        const ax = this.axis('x', P), ay = this.axis('y', P);
        ax.domain = P.dx; ax.anchor = P.ya;
        ay.domain = P.dy; ay.anchor = P.xa;
        // shared axes: a column of panels shares X, a row shares Y (with Wrap, all share both)
        const cKey = this.wrap ? 'all' : P.c, rKey = this.wrap ? 'all' : P.r;
        if (!P.freeX) { if (colFirst.has(cKey)) ax.matches = colFirst.get(cKey); else colFirst.set(cKey, P.xa); }
        if (!P.freeY) { if (rowFirst.has(rKey)) ay.matches = rowFirst.get(rKey); else rowFirst.set(rKey, P.ya); }
        if (!P.bottom) { ax.showticklabels = false; ax.title = undefined; } else if (!sharedX) {
          const tx = this.axisTitle('x', P);
          if (tx && S.show.xTitle) { ax.title = { text: esc(tx.text), standoff: 6 }; fig.axisKeys[kx] = tx.key; }
        }
        if (!P.left) { ay.showticklabels = false; ay.title = undefined; } else {
          const ty = this.axisTitle('y', P);
          if (ty && S.show.yTitle) { ay.title = { text: esc(ty.text), standoff: 6 }; fig.axisKeys[ky] = ty.key; }
        }
        if (this.exclusive === 'pie') { ax.visible = false; ay.visible = false; }
        L[kx] = ax;
        L[ky] = ay;
        // panel labels
        if (P.wrapLabel != null) fig.annotations.push({ text: esc(P.wrapLabel), xref: 'paper', yref: 'paper', x: (P.dx[0] + P.dx[1]) / 2, y: P.dy[1], yanchor: 'bottom', xanchor: 'center', showarrow: false, font: { size: 11 }, bgcolor: rgba(tc.grid, 0.5) });
        if (P.gxLabel != null && P.r === 0 && (!this.xSide || P.c % Math.max(1, this.cols.x.length) === 0)) {
          const span = this.xSide ? this.cols.x.length : 1;
          const xEnd = ((P.c + span - 1) * (cw + gapX) + cw) / pw;
          fig.annotations.push({ text: esc(P.gxLabel), xref: 'paper', yref: 'paper', x: (P.dx[0] + clamp(xEnd, 0, 1)) / 2, y: 1, yanchor: 'bottom', yshift: 2, xanchor: 'center', showarrow: false, font: { size: 11 } });
        }
        if (P.gyLabel != null && P.c === this.nC - 1 && (!this.ySide || P.r % Math.max(1, this.cols.y.length) === 0)) {
          const span = this.ySide ? this.cols.y.length : 1;
          const yEnd = 1 - ((P.r + span - 1) * (rh + gapY) + rh) / ph;
          fig.annotations.push({ text: esc(P.gyLabel), xref: 'paper', yref: 'paper', x: 1, xanchor: 'left', xshift: 6, y: (P.dy[1] + clamp(yEnd, 0, 1)) / 2, yanchor: 'middle', textangle: 90, showarrow: false, font: { size: 11 } });
        }
      }
      if (sharedX && S.show.xTitle) {
        const tx = this.axisTitle('x', this.panels[0]);
        if (tx) fig.annotations.push({ text: esc(tx.text), xref: 'paper', yref: 'paper', x: 0.5, y: 0, yanchor: 'top', yshift: -24, showarrow: false, font: { size: 11 } });
      }
      // Plotly offers to edit an axis title in place; with several panels the
      // titles are edited from the red triangle instead.
      fig.editAxes = this.panels.length === 1 && Object.keys(fig.axisKeys).length === 2;
      if (this.gx) fig.annotations.push({ text: `<b>${esc(this.gx.col.name)}</b>`, xref: 'paper', yref: 'paper', x: 0.5, y: 1, yanchor: 'bottom', yshift: 20, showarrow: false, font: { size: 11 } });
      if (this.gy) fig.annotations.push({ text: `<b>${esc(this.gy.col.name)}</b>`, xref: 'paper', yref: 'paper', x: 1, xanchor: 'left', xshift: 24, y: 0.5, textangle: 90, showarrow: false, font: { size: 11 } });
      if (this.wrap) fig.annotations.push({ text: `<b>${esc(this.wrap.col.name)}</b>`, xref: 'paper', yref: 'paper', x: 0.5, y: 1, yanchor: 'bottom', yshift: 18, showarrow: false, font: { size: 11 } });
      for (const { tr, P } of this.pies || []) tr.domain = { x: P.dx, y: P.dy };
      if (legendOn) {
        const ltText = this.legendTitle != null ? this.legendTitle : this.G ? this.G.col.name : null;
        const lt = ltText ? { text: esc(ltText), side: 'top' } : undefined;
        L.legend = legendPos === 'bottom' ? { orientation: 'h', x: 0, xanchor: 'left', y: 0, yanchor: 'bottom', yref: 'container', title: lt }
          : legendPos === 'inside' ? { x: 0.99, xanchor: 'right', y: 0.99, yanchor: 'top', bgcolor: rgba(tc.surface, 0.8), bordercolor: tc.grid, borderwidth: 1, title: lt }
            : { x: 1.02 + (this.gy ? 0.06 : 0), xanchor: 'left', y: 1, yanchor: 'top', title: lt };
        L.legend.tracegroupgap = 2;
      }
      // a colour bar for a continuous Color column
      if (this.colorCol && !isCat(this.colorCol) && this.colorRange && this.els.some((e) => e.type === 'points')) {
        const [lo, hi] = this.colorRange;
        fig.traces.push({ type: 'scatter', x: [null], y: [null], mode: 'markers', xaxis: 'x', yaxis: 'y', hoverinfo: 'skip', showlegend: false,
          marker: { color: [lo, hi], cmin: lo, cmax: hi, colorscale: RAMP, showscale: true, colorbar: { title: { text: esc(this.colorCol.name), side: 'right' }, thickness: 12, len: legendOn ? 0.45 : 0.8, y: legendOn ? 0 : 0.5, yanchor: legendOn ? 'bottom' : 'middle', x: 1.02 + (this.gy ? 0.06 : 0), outlinewidth: 0 } } });
      }
      fig.layout = L;
      fig.width = w;
      fig.height = h;
      fig.title = title || 'Graph Builder';
    }

    axis(which, P) {
      const kind = which === 'x' ? this.xKind : this.yKind;
      const col = (which === 'x' ? P.xset : P.yset)[0] || null;
      const over = P.axes && P.axes[which];
      if (over) return { ...over };
      if (kind === 'cat') {
        const L = this.axisLevels(col);
        const k = L.lv.length;
        return { type: 'linear', tickmode: 'array', tickvals: L.lv.map((_, i) => i), ticktext: L.labels.map(esc), range: which === 'y' ? [k - 0.5, -0.5] : [-0.5, k - 0.5], showgrid: false, zeroline: false, automargin: true };
      }
      if (kind === 'none') return { range: [-0.5, 0.5], showticklabels: false, ticks: '', showgrid: false, zeroline: false, showline: false, fixedrange: true };
      if (kind === 'count') return { rangemode: 'tozero', zeroline: false, automargin: true };
      const log = !isDate(col) && !!(this.S.log && this.S.log[which]);
      return { type: isDate(col) ? 'date' : log ? 'log' : 'linear', zeroline: false, automargin: true };
    }
  }

  /* ---- the elements' traces ------------------------------------------------------------------ */
  const RENDER = {};

  function jitterOn(e, c) {
    const j = e.jitter || 'auto';
    if (j === 'none') return false;
    if (j === 'auto') return !c || isCat(c);
    return !c || isCat(c);
  }

  function jit(r, e, salt) {
    const lim = 0.8 * (e.jitterLimit ?? 1);
    if (e.jitter === 'normal') {
      const u = Math.max(1e-9, hash01(r, salt)), v = hash01(r, salt + 11);
      return clamp(Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v) * lim / 6, -0.48, 0.48);
    }
    return (hash01(r, salt) - 0.5) * lim;
  }

  /* Centered grid jitter: points at one position that fall in the same of
     40 bins of the other axis are set side by side. */
  function gridJitter(list, lim) {
    const vals = list.map((p) => p.v);
    const ex = extent(vals) || [0, 1];
    const nb = 40, groups = new Map();
    for (const p of list) {
      const b = ex[1] > ex[0] ? Math.min(nb - 1, Math.floor(((p.v - ex[0]) / (ex[1] - ex[0])) * nb)) : 0;
      const key = `${p.pos}|${b}`;
      let g = groups.get(key);
      if (!g) { g = []; groups.set(key, g); }
      g.push(p);
    }
    let most = 1;
    for (const g of groups.values()) most = Math.max(most, g.length);
    const d = Math.min(0.09, (0.8 * lim) / most);
    const off = new Map();
    for (const g of groups.values()) g.forEach((p, i) => off.set(p.r, Math.ceil(i / 2) * (i % 2 ? 1 : -1) * d));
    return off;
  }

  /* Packed jitter (JMP's Packed; a beeswarm): at each position, the points
     in order of their value, each at the offset nearest the middle where it
     does not overlap a point already placed. The geometry is in pixels, from
     the graph's size, the panels and the value range; a position whose points
     need more room than the jitter limit is squeezed into it. */
  function packedJitter(list, { valuePx, catPx, diam, lim }) {
    const off = new Map();
    const byPos = new Map();
    for (const p of list) { let g = byPos.get(p.pos); if (!g) { g = []; byPos.set(p.pos, g); } g.push(p); }
    const room = 0.5 * lim * catPx;        // half the width a position may take, in pixels
    for (const g of byPos.values()) {
      g.sort((a, b) => a.v - b.v || a.r - b.r);
      const placed = [];                   // { vp, o }, in order of vp
      let widest = 0;
      for (const p of g) {
        const vp = p.v * valuePx;
        const blocked = [];
        for (let i = placed.length - 1; i >= 0; i--) {
          const dy = vp - placed[i].vp;
          if (dy >= diam) break;
          const half = Math.sqrt(Math.max(0, diam * diam - dy * dy));
          blocked.push([placed[i].o - half, placed[i].o + half]);
        }
        const cands = [0];
        for (const [a, b] of blocked) cands.push(a, b);
        cands.sort((a, b) => Math.abs(a) - Math.abs(b) || a - b);
        const o = cands.find((c) => blocked.every(([a, b]) => c <= a + 1e-6 || c >= b - 1e-6)) ?? 0;
        let k = placed.length;
        while (k > 0 && placed[k - 1].vp > vp) k--;
        placed.splice(k, 0, { vp, o });
        widest = Math.max(widest, Math.abs(o));
        off.set(p.r, o);
      }
      const squeeze = widest > room ? room / widest : 1;
      for (const p of g) off.set(p.r, (off.get(p.r) * squeeze) / catPx);
    }
    return off;
  }

  // The pixels per unit of a panel's axes, for the packed jitter.
  function packGeometry(E, list, jx, col, diam, lim) {
    const W = Math.max(200, (E.B.width ? E.B.width() : 600) - 90) / Math.max(1, E.nC);
    const H = Math.max(150, (E.B.height ? E.B.height() : 400) - 70) / Math.max(1, E.nR);
    const vals = list.map((p) => p.v);
    const ex = extent(vals) || [0, 1];
    const span = (ex[1] - ex[0]) * 1.1 || 1;          // Plotly's autorange pads about 5% each side
    const k = col ? Math.max(1, E.axisLevels(col).lv.length) : 1;
    return { valuePx: (jx ? H : W) / span, catPx: (jx ? W : H) / k, diam, lim };
  }

  RENDER.points = async (E, e) => {
    if (e.summary && e.summary !== 'none') return summaryPoints(E, e);
    const t = E.t;
    // Packed jitter packs a panel's points over every group at once, so
    // that the groups' points do not fall on each other.
    const packs = new Map();
    const packedFor = (P, s, si) => {
      const key = `${P.idx}|${si}`;
      if (packs.has(key)) return packs.get(key);
      const { xc, yc } = s;
      const jx = jitterOn(e, xc) && E.xKind !== 'count', jy = jitterOn(e, yc) && E.yKind !== 'count';
      let m = null;
      if (jx !== jy) {
        const list = [];
        for (const r of P.rows) {
          const x = E.at(xc, r), y = E.at(yc, r);
          if (x == null || y == null) continue;
          list.push({ r, pos: jx ? x : y, v: jx ? y : x });
        }
        const diam = (E.rows0.length > 2000 ? 4 : 6) + 1;
        m = list.length <= 20000 ? packedJitter(list, packGeometry(E, list, jx, jx ? xc : yc, diam, e.jitterLimit ?? 1)) : null;
      }
      packs.set(key, m);
      return m;
    };
    E.forCells((P, s, si, gi, rows) => {
      const { xc, yc } = s;
      const jx = jitterOn(e, xc) && E.xKind !== 'count', jy = jitterOn(e, yc) && E.yKind !== 'count';
      let grid = null;
      if (e.jitter === 'packed' && (jx !== jy)) grid = packedFor(P, s, si);
      if (e.jitter === 'grid' && (jx !== jy)) {
        const list = [];
        for (const r of rows) {
          const x = E.at(xc, r), y = E.at(yc, r);
          if (x == null || y == null) continue;
          list.push({ r, pos: jx ? x : y, v: jx ? y : x });
        }
        grid = gridJitter(list, e.jitterLimit ?? 1);
      }
      const X = [], Y = [], R = [], C = [], Z = [], H = [];
      const hoverCols = [xc, yc, E.colorCol, E.sizeCol, E.G ? E.G.col : null].filter((c, i, a) => c && a.indexOf(c) === i);
      for (const r of rows) {
        let x = E.at(xc, r), y = E.at(yc, r);
        if (x == null || y == null) continue;
        if (grid && grid.has(r)) { if (jx) x += grid.get(r); else y += grid.get(r); } else {
          if (jx && !grid) x += jit(r, e, 1);
          if (jy && !grid) y += jit(r, e, 2);
        }
        X.push(x); Y.push(y); R.push(r);
        C.push(E.rowColor(r, si, gi));
        if (E.sizeCol) Z.push(E.rowSize(r));
        H.push(rowHover(t, r, hoverCols));
      }
      if (!R.length) return;
      const uni = C.every((c) => c === C[0]);
      const tr = {
        type: E.gl ? 'scattergl' : 'scatter', mode: 'markers', x: X, y: Y, rows: R, xaxis: P.xa, yaxis: P.ya,
        marker: { color: uni ? C[0] : C, size: E.sizeCol ? Z : (E.rows0.length > 2000 ? 4 : 6), opacity: E.sizeCol ? 0.7 : (E.rows0.length > 2000 ? 0.65 : 0.9), line: E.sizeCol ? { width: 0.6, color: rgba(SM.util.themeColors().text, 0.4) } : { width: 0 } },
        hovertext: H, hovertemplate: '%{hovertext}<extra></extra>', ...E.legend(si, gi),
      };
      if (E.fig.mask) tr.selected = { marker: { opacity: 1 } };
      E.fig.traces.push(tr);
    });
  };

  /* Points with a Summary Statistic: one point per factor position. */
  async function summaryPoints(E, e) {
    const blocks = [];
    E.forCells((P, s, si, gi, rows) => { const R = axesRoles(s.xc, s.yc); blocks.push({ P, s, si, gi, R, items: E.items(R, rows) }); });
    await summaryTraces(E, e, blocks, { stat: e.summary, mode: 'markers' });
  }

  /* Summary statistics as points or a line: Points' summaries, Line, and
     the vertices of Area. */
  async function summaryTraces(E, e, blocks, { stat, mode, shape = 'linear', fill = null, stack = false }) {
    const R0 = blocks[0] && blocks[0].R;
    if (!R0) return;
    if (!R0.resp && !['n', 'pct'].includes(stat)) { E.note(`${ELEMENT[e.type].label}: without a continuous variable the statistic is N.`); stat = 'n'; }
    let interval = e.interval && e.interval !== 'none' ? e.interval : null;
    if (interval && !R0.resp) interval = null;
    if (interval && ['ci', 'se', 'sd'].includes(interval) && stat !== 'mean') { E.note(`${ELEMENT[e.type].label}: the ${interval === 'ci' ? 'confidence interval' : interval === 'se' ? 'standard error' : 'standard deviation'} interval goes with the Mean.`); interval = null; }
    await E.fillStats(blocks, [stat, ...(interval ? E.intervalNeeds(interval) : [])]);
    const totals = new Map();
    for (const b of blocks) { const k = `${b.P.idx}|${b.si}`; totals.set(k, (totals.get(k) || 0) + b.items.reduce((a, it) => a + ((it.sum != null ? it.sum : it.n) || 0), 0)); }
    const slots = E.slots();
    for (const b of blocks) {
      const { P, si, gi, R } = b;
      if (!b.items.length) continue;
      const bw = E.band(R.fac);
      const off = mode === 'markers' && slots > 1 && R.facCat ? (-0.4 + (E.slotOf(si, gi) + 0.5) * (0.8 / slots)) * bw * 0.6 : 0;
      const pos = b.items.map((it) => it.pos + off);
      const val = b.items.map((it) => E.statValue(it, stat, totals.get(`${P.idx}|${si}`)));
      const color = E.colorFor(si, gi, mode === 'markers' ? pointColor() : inkColor());
      const lab = STAT_LABEL[stat] || stat;
      const name = R.resp ? `${lab}(${R.resp.name})` : lab;
      const hov = b.items.map((it, k) => `${esc(it.label)}${gi >= 0 ? `, ${esc(E.G.labels[gi])}` : ''}<br>${esc(name)}: ${fmt(val[k])}<br>N: ${fmt(it.n)}`);
      const tr = { type: E.lineType(), mode: mode === 'markers' ? 'markers' : 'lines+markers', xaxis: P.xa, yaxis: P.ya, marker: { color, size: mode === 'markers' ? 8 : 5 }, line: { color, width: 2, shape }, hovertext: hov, hovertemplate: '%{hovertext}<extra></extra>', ...E.legend(si, gi) };
      if (R.horiz) { tr.y = pos; tr.x = val; } else { tr.x = pos; tr.y = val; }
      if (fill) { tr.fill = R.horiz ? 'tozerox' : 'tozeroy'; tr.fillcolor = rgba(color, 0.32); tr.mode = 'lines'; }
      if (stack) { tr.stackgroup = `p${P.idx}s${si}`; tr.orientation = R.horiz ? 'h' : 'v'; tr.fillcolor = rgba(color, 0.55); tr.mode = 'lines'; delete tr.fill; }
      if (interval) {
        const iv = b.items.map((it) => E.interval(it, interval));
        const up = iv.map((q, k) => (q[1] != null && val[k] != null ? q[1] - val[k] : null)), dn = iv.map((q, k) => (q[0] != null && val[k] != null ? val[k] - q[0] : null));
        if (e.style === 'band' && mode !== 'markers') {
          const lo = iv.map((q) => q[0]), hi = iv.map((q) => q[1]);
          const band = { type: E.lineType(), mode: 'lines', fill: 'toself', fillcolor: rgba(color, 0.18), line: { width: 0 }, hoverinfo: 'skip', showlegend: false, xaxis: P.xa, yaxis: P.ya };
          if (R.horiz) { band.y = [...pos, ...pos.slice().reverse()]; band.x = [...hi, ...lo.slice().reverse()]; } else { band.x = [...pos, ...pos.slice().reverse()]; band.y = [...hi, ...lo.slice().reverse()]; }
          E.fig.traces.push(band);
        } else {
          const eb = { type: 'data', symmetric: false, array: up, arrayminus: dn, color, thickness: 1.3, width: 4 };
          if (R.horiz) tr.error_x = eb; else tr.error_y = eb;
        }
      }
      const ti = E.fig.traces.push(tr) - 1;
      const ov = overlayMarks(tr);
      if (E.gl) ov.type = 'scattergl';
      const oi = E.fig.traces.push(ov) - 1;
      E.fig.links.push({ trace: ti, overlay: oi, kind: 'mark', rows: b.items.map((it) => it.rows), x: tr.x, y: tr.y });
    }
  }

  RENDER.line = async (E, e) => {
    const shape = e.connection === 'curve' ? 'spline' : e.connection === 'step' ? 'hv' : 'linear';
    if (e.ordering === 'row') {
      E.forCells((P, s, si, gi, rows) => {
        const R = axesRoles(s.xc, s.yc);
        const X = [], Y = [], RR = [];
        for (const r of rows) { const x = E.at(s.xc, r), y = E.at(s.yc, r); if (x == null || y == null) continue; X.push(x); Y.push(y); RR.push(r); }
        if (!RR.length) return;
        const color = E.colorFor(si, gi, inkColor());
        const hov = RR.map((r) => rowHover(E.t, r, [s.xc, s.yc]));
        E.fig.traces.push({ type: E.lineType(), mode: 'lines+markers', x: X, y: Y, rows: RR, xaxis: P.xa, yaxis: P.ya, line: { color, width: 1.6, shape: R.horiz ? shape.replace('hv', 'vh') : shape }, marker: { color, size: 4 }, hovertext: hov, hovertemplate: '%{hovertext}<extra></extra>', ...E.legend(si, gi) });
      });
      return;
    }
    const blocks = [];
    E.forCells((P, s, si, gi, rows) => { const R = axesRoles(s.xc, s.yc); blocks.push({ P, s, si, gi, R, items: E.items(R, rows) }); });
    await summaryTraces(E, e, blocks, { stat: e.summary === 'auto' ? 'mean' : (e.summary || 'mean'), mode: 'lines', shape });
  };

  RENDER.area = async (E, e) => {
    const blocks = [];
    E.forCells((P, s, si, gi, rows) => { const R = axesRoles(s.xc, s.yc); blocks.push({ P, s, si, gi, R, items: E.items(R, rows) }); });
    const R0 = blocks[0] && blocks[0].R;
    const stat = e.summary === 'auto' || !e.summary ? (R0 && R0.resp ? 'mean' : 'n') : e.summary;
    const shape = e.connection === 'curve' ? 'spline' : e.connection === 'step' ? 'hv' : 'linear';
    await summaryTraces(E, { ...e, interval: 'none' }, blocks, { stat, mode: 'lines', shape, fill: e.areaStyle !== 'stacked', stack: e.areaStyle === 'stacked' });
  };

  RENDER.bar = async (E, e) => {
    const blocks = [];
    E.forCells((P, s, si, gi, rows) => { const R = axesRoles(s.xc, s.yc); blocks.push({ P, s, si, gi, R, items: E.items(R, rows) }); });
    const R0 = blocks[0] && blocks[0].R;
    if (!R0) return;
    let stat = e.summary === 'auto' || !e.summary ? (R0.resp ? 'mean' : 'n') : e.summary;
    if (!R0.resp && !['n', 'pct'].includes(stat)) { E.note('Bar: without a continuous variable the statistic is N.'); stat = 'n'; }
    let interval = e.interval && e.interval !== 'none' && R0.resp ? e.interval : null;
    if (interval && ['ci', 'se', 'sd'].includes(interval) && stat !== 'mean') { E.note('Bar: that error interval goes with the Mean.'); interval = null; }
    await E.fillStats(blocks, [stat, ...(interval ? E.intervalNeeds(interval) : [])]);
    const totals = new Map();
    for (const b of blocks) { const k = `${b.P.idx}|${b.si}`; totals.set(k, (totals.get(k) || 0) + b.items.reduce((a, it) => a + ((it.sum != null ? it.sum : it.n) || 0), 0)); }
    const slots = E.slots();
    const stacked = e.barStyle === 'stacked', needle = e.barStyle === 'needle';
    const cum = new Map();
    const lab = STAT_LABEL[stat] || stat;
    for (const b of blocks) {
      const { P, si, gi, R } = b;
      if (!b.items.length) continue;
      const bw = E.band(R.fac);
      const slot = E.slotOf(si, gi);
      const width = stacked ? 0.8 * bw : (needle ? 0.08 * bw : (0.8 * bw) / slots * 0.92);
      const off = stacked || slots === 1 ? 0 : (-0.4 + (slot + 0.5) * (0.8 / slots)) * bw;
      const pos = b.items.map((it) => it.pos + off);
      const val = b.items.map((it) => E.statValue(it, stat, totals.get(`${P.idx}|${si}`)) ?? 0);
      let base;
      if (stacked) {
        base = b.items.map((it, k) => {
          const key = `${P.idx}|${it.pos}|${val[k] < 0 ? '-' : '+'}`;
          const c0 = cum.get(key) || 0;
          cum.set(key, c0 + val[k]);
          return c0;
        });
      }
      const color = E.colorFor(si, gi, barColor());
      const name = R.resp ? `${lab}(${R.resp.name})` : lab;
      const hov = b.items.map((it, k) => `${esc(it.label)}${gi >= 0 ? `, ${esc(E.G.labels[gi])}` : ''}<br>${esc(name)}: ${fmt(val[k])}${stat !== 'n' ? `<br>N: ${fmt(it.n)}` : ''}`);
      const shade = gi >= 0 && E.nSeries > 1 && si > 0 ? rgba(color, Math.max(0.35, 1 - 0.3 * si)) : color;
      const tr = { type: 'bar', orientation: R.horiz ? 'h' : 'v', width: b.items.map(() => width), xaxis: P.xa, yaxis: P.ya, marker: { color: shade, line: { width: gi >= 0 && E.nSeries > 1 ? 1 : 0, color } }, hovertext: hov, hovertemplate: '%{hovertext}<extra></extra>', ...E.legend(si, gi) };
      if (base) tr.base = base;
      if (R.horiz) { tr.y = pos; tr.x = val; } else { tr.x = pos; tr.y = val; }
      if (e.label && e.label !== 'none') {
        const tot = totals.get(`${P.idx}|${si}`) || 1;
        tr.text = b.items.map((it, k) => (e.label === 'percent' ? `${(100 * ((it.sum != null ? it.sum : it.n) || 0) / tot).toFixed(1)}%` : fmt(val[k])));
        tr.textposition = stacked ? 'inside' : 'outside';
        tr.cliponaxis = false;
        tr.textfont = { size: 10 };
      }
      if (interval) {
        const iv = b.items.map((it) => E.interval(it, interval));
        const eb = { type: 'data', symmetric: false, array: iv.map((q, k) => (q[1] != null ? q[1] - val[k] : null)), arrayminus: iv.map((q, k) => (q[0] != null ? val[k] - q[0] : null)), color: SM.util.themeColors().text, thickness: 1.2, width: 4 };
        if (R.horiz) tr.error_x = eb; else tr.error_y = eb;
      }
      const ti = E.fig.traces.push(tr) - 1;
      const oi = E.fig.traces.push(overlayBar(tr)) - 1;
      E.fig.links.push({ trace: ti, overlay: oi, kind: 'bar', rows: b.items.map((it) => it.rows), len: val, horiz: R.horiz });
    }
  };

  RENDER.box = async (E, e) => {
    const blocks = [];
    E.forCells((P, s, si, gi, rows) => { const R = axesRoles(s.xc, s.yc); blocks.push({ P, s, si, gi, R, items: E.items(R, rows) }); });
    if (!blocks.length) return;
    await E.fillStats(blocks, ['median'], { boxes: true });
    const slots = E.slots();
    const tc = SM.util.themeColors();
    for (const b of blocks) {
      const { P, si, gi, R } = b;
      if (!b.items.length) continue;
      const resp = R.resp;
      const bw = E.band(R.fac);
      const slot = E.slotOf(si, gi);
      const off = slots === 1 ? 0 : (-0.4 + (slot + 0.5) * (0.8 / slots)) * bw;
      const width = clamp(e.width ?? 0.5, 0.05, 1) * 1.1 * (0.8 * bw / slots) * (e.boxStyle === 'thin' ? 0.4 : 1);
      const pos = b.items.map((it) => it.pos + off);
      const color = E.colorFor(si, gi, dark() ? '#9cb6d0' : '#4a6f94');
      const quant = e.boxType === 'quantile';
      const lf = b.items.map((it) => (quant ? it.quantiles.q0 : it.lo_whisker));
      const uf = b.items.map((it) => (quant ? it.quantiles.q100 : it.hi_whisker));
      const tr = {
        type: 'box', orientation: R.horiz ? 'h' : 'v', q1: b.items.map((it) => it.quantiles.q25), median: b.items.map((it) => it.quantiles.q50), q3: b.items.map((it) => it.quantiles.q75),
        lowerfence: lf, upperfence: uf, boxpoints: false, width, xaxis: P.xa, yaxis: P.ya,
        fillcolor: e.boxStyle === 'solid' ? rgba(color, 0.7) : e.boxStyle === 'thin' ? 'rgba(0,0,0,0)' : rgba(color, 0.18),
        line: { color: e.boxStyle === 'solid' ? tc.text : color, width: e.boxStyle === 'thin' ? 1 : 1.4 }, whiskerwidth: 0.5,
        hoverinfo: 'x+y', ...E.legend(si, gi),
      };
      if (R.horiz) tr.y = pos; else tr.x = pos;
      const ti = E.fig.traces.push(tr) - 1;
      const ov = { type: 'scatter', mode: 'markers', x: [], y: [], xaxis: P.xa, yaxis: P.ya, marker: { color: SM.report.SELECTED, size: 6 }, hoverinfo: 'skip', showlegend: false };
      const oi = E.fig.traces.push(ov) - 1;
      E.fig.links.push({ trace: ti, overlay: oi, kind: 'box', rows: b.items.map((it) => it.rows), pos, vals: b.items.map((it) => it.rows.map((r) => resp.values[r])), horiz: R.horiz, jitter: width * 0.6 });
      // outliers, linked point by point
      if (e.outliers !== false && !quant) {
        const X = [], Y = [], RR = [], H = [];
        b.items.forEach((it, k) => { for (const r of it.rows) { const v = resp.values[r]; if (v < lf[k] || v > uf[k]) { if (R.horiz) { X.push(v); Y.push(pos[k]); } else { X.push(pos[k]); Y.push(v); } RR.push(r); H.push(rowHover(E.t, r, [R.fac, resp])); } } });
        if (RR.length) E.fig.traces.push({ type: 'scatter', mode: 'markers', x: X, y: Y, rows: RR, xaxis: P.xa, yaxis: P.ya, marker: { color, size: 5 }, hovertext: H, hovertemplate: '%{hovertext}<extra></extra>', showlegend: false, legendgroup: gi >= 0 ? `g${gi}` : undefined });
      }
      if (e.diamond) {
        const dx = [], dy = [];
        b.items.forEach((it, k) => {
          if (it.lower == null || it.upper == null) return;
          const p = pos[k], hw = width / 2;
          const pts = [[p, it.lower], [p + hw, it.mean], [p, it.upper], [p - hw, it.mean], [p, it.lower]];
          for (const [a, v] of pts) { if (R.horiz) { dx.push(v); dy.push(a); } else { dx.push(a); dy.push(v); } }
          dx.push(null); dy.push(null);
        });
        E.fig.traces.push({ type: 'scatter', mode: 'lines', x: dx, y: dy, xaxis: P.xa, yaxis: P.ya, line: { color: '#c0392b', width: 1.3 }, hoverinfo: 'skip', showlegend: false });
      }
    }
  };

  RENDER.histogram = async (E, e) => {
    const s0 = E.panels[0].series[0];
    const R0 = axesRoles(s0.xc, s0.yc);
    const resp = R0.resp;
    const vals = E.rows0.map((r) => resp.values[r]).filter(Number.isFinite);
    if (!vals.length) return;
    let bins;
    if (e.binWidth > 0) {
      const ex = extent(vals);
      const size = e.binWidth, start = Math.floor(ex[0] / size) * size;
      let end = Math.ceil(ex[1] / size) * size;
      if (end <= ex[1]) end += size;
      bins = { start, end, size };
    } else bins = SM.report.niceBins(vals);
    const nb = Math.max(1, Math.round((bins.end - bins.start) / bins.size));
    const centers = Array.from({ length: nb }, (_, j) => bins.start + (j + 0.5) * bins.size);
    const band = !!R0.fac;
    const blocks = [];
    E.forCells((P, s, si, gi, rows) => {
      const R = axesRoles(s.xc, s.yc);
      const levels = band ? E.items(R, rows) : [{ pos: 0, rows: rows.filter((r) => Number.isFinite(R.resp.values[r])), label: '' }];
      for (const lv of levels) {
        const counts = new Array(nb).fill(0), members = Array.from({ length: nb }, () => []);
        let tot = 0;
        for (const r of lv.rows) {
          const v = R.resp.values[r];
          if (!Number.isFinite(v)) continue;
          const j = clamp(Math.floor((v - bins.start) / bins.size + 1e-9), 0, nb - 1);
          const w = E.W(r);
          counts[j] += w; members[j].push(r); tot += w;
        }
        blocks.push({ P, s, si, gi, R, lv, counts, members, tot });
      }
    });
    const pct = e.scale === 'percent';
    const scaleOf = (b) => (pct ? 100 / (b.tot || 1) : 1);
    let most = 0;
    for (const b of blocks) for (const c of b.counts) most = Math.max(most, c * scaleOf(b));
    const kernel = e.histStyle === 'kernel';
    let dens = null;
    blocks.forEach((b, i) => { b.i = i; });
    if (kernel) {
      const rows = [], codes = [];
      blocks.forEach((b, i) => { for (const r of b.lv.rows) { rows.push(r); codes.push(i); } });
      const res = await E.call('graph.kde1', { y: resp.name, rows, codes, k: blocks.length, bw: e.bw || 1, lo: bins.start, hi: bins.end, freq: E.freqName, by: E.byNames });
      dens = res.densities;
      most = 0;
      blocks.forEach((b, i) => { const d = dens[i]; if (d && d.d) for (const v of d.d) most = Math.max(most, v * b.tot * bins.size * scaleOf(b)); });
    }
    for (const b of blocks) {
      const { P, si, gi, R, lv } = b;
      if (!b.tot) continue;
      const color = E.colorFor(si, gi, barColor());
      const k = scaleOf(b);
      const len = b.counts.map((c) => c * k);
      if (kernel) {
        const d = dens[b.i];
        if (!d || !d.d) continue;
        const sc = band ? (0.8 / (most || 1)) : 1;
        const L = d.d.map((v) => v * b.tot * bins.size * k * sc);
        const tr = { type: E.lineType(), mode: 'lines', xaxis: P.xa, yaxis: P.ya, line: { color: E.colorFor(si, gi, inkColor()), width: 1.8 }, fill: band ? 'toself' : (R.horiz ? 'tozeroy' : 'tozerox'), fillcolor: rgba(E.colorFor(si, gi, inkColor()), 0.2), hoverinfo: 'skip', ...E.legend(si, gi) };
        const q = band ? (R.horiz ? lv.pos + 0.4 : lv.pos - 0.4) : 0;
        const sign = band && R.horiz ? -1 : 1;
        const along = d.y, across = L.map((v) => q + sign * v);
        if (!R.horiz) { tr.y = along; tr.x = band ? across : L; } else { tr.x = along; tr.y = band ? across : L; }
        if (band) { if (!R.horiz) { tr.y = [...along, along[along.length - 1], along[0]]; tr.x = [...across, q, q]; } else { tr.x = [...along, along[along.length - 1], along[0]]; tr.y = [...across, q, q]; } }
        E.fig.traces.push(tr);
        continue;
      }
      const tr = { type: 'bar', xaxis: P.xa, yaxis: P.ya, marker: { color: E.G || E.nSeries > 1 ? rgba(color, 0.6) : color, line: { color: SM.util.themeColors().surface, width: 0.6 } }, width: centers.map(() => bins.size), ...E.legend(si, gi) };
      const hov = centers.map((c, j) => `${esc(R.resp.name)}: ${fmt(c - bins.size / 2)} to ${fmt(c + bins.size / 2)}${lv.label ? `<br>${esc(lv.label)}` : ''}<br>${pct ? 'Percent' : 'Count'}: ${fmt(len[j])}`);
      tr.hovertext = hov;
      tr.hovertemplate = '%{hovertext}<extra></extra>';
      let shown = len;
      if (band) {
        const sc = 0.8 / (most || 1);
        shown = len.map((v) => v * sc);
        // bars grow from the edge of the level's band
        if (!R.horiz) { tr.orientation = 'h'; tr.y = centers; tr.x = shown; tr.base = centers.map(() => lv.pos - 0.4); } else { tr.orientation = 'v'; tr.x = centers; tr.y = shown.map((v) => -v); tr.base = centers.map(() => lv.pos + 0.4); shown = shown.map((v) => -v); }
      } else if (R.horiz) { tr.orientation = 'v'; tr.x = centers; tr.y = len; } else { tr.orientation = 'h'; tr.y = centers; tr.x = len; }
      if (e.counts) { tr.text = b.counts.map((c) => (c ? fmt(pct ? c * k : c) : '')); tr.textposition = 'outside'; tr.cliponaxis = false; tr.textfont = { size: 9 }; }
      const ti = E.fig.traces.push(tr) - 1;
      const oi = E.fig.traces.push(overlayBar(tr)) - 1;
      E.fig.links.push({ trace: ti, overlay: oi, kind: 'bar', rows: b.members, len: shown, horiz: tr.orientation === 'h' });
    }
  };

  /* Bins or levels of one heatmap axis. */
  function heatAxis(E, c, want) {
    if (!c) return { n: 1, centers: [0], of: () => 0 };
    if (isCat(c)) { const L = E.axisLevels(c); return { n: L.lv.length, centers: L.lv.map((_, i) => i), of: (r) => E.levelPos(c, c.values[r]), labels: L.labels }; }
    const ex = extent(E.rows0.map((r) => c.values[r]));
    if (!ex) return { n: 0, centers: [], of: () => null };
    const b = SM.report.niceBins([ex[0], ex[1]], want);
    const n = Math.max(1, Math.round((b.end - b.start) / b.size));
    return { n, centers: Array.from({ length: n }, (_, j) => b.start + (j + 0.5) * b.size), of: (r) => { const v = c.values[r]; return Number.isFinite(v) ? clamp(Math.floor((v - b.start) / b.size + 1e-9), 0, n - 1) : null; }, size: b.size };
  }

  RENDER.heatmap = async (E, e) => {
    const s0 = E.panels[0].series[0];
    const hx = heatAxis(E, s0.xc, e.bins || 16), hy = heatAxis(E, s0.yc, e.bins || 16);
    const cc = E.colorCol && !isCat(E.colorCol) ? E.colorCol : null;
    const cells = [];
    let zmin = Infinity, zmax = -Infinity, grand = 0;
    for (const P of E.panels) {
      const z = Array.from({ length: hy.n }, () => new Array(hx.n).fill(null));
      const rows = Array.from({ length: hy.n }, () => Array.from({ length: hx.n }, () => []));
      const n = Array.from({ length: hy.n }, () => new Array(hx.n).fill(0)), sw = Array.from({ length: hy.n }, () => new Array(hx.n).fill(0));
      for (const r of P.rows) {
        const ix = hx.of(r), iy = hy.of(r);
        if (ix == null || iy == null) continue;
        const w = E.W(r);
        if (cc) { const v = cc.values[r]; if (!Number.isFinite(v)) continue; sw[iy][ix] += w * v; }
        n[iy][ix] += w;
        rows[iy][ix].push(r);
      }
      let tot = 0;
      for (let i = 0; i < hy.n; i++) for (let j = 0; j < hx.n; j++) if (n[i][j]) { z[i][j] = cc ? sw[i][j] / n[i][j] : n[i][j]; tot += n[i][j]; zmin = Math.min(zmin, z[i][j]); zmax = Math.max(zmax, z[i][j]); }
      grand += tot;
      cells.push({ P, z, rows, n, tot });
    }
    const label = cc ? `Mean(${cc.name})` : 'Count';
    cells.forEach((cl, i) => {
      const { P } = cl;
      const tr = { type: 'heatmap', x: hx.centers, y: hy.centers, z: cl.z, xaxis: P.xa, yaxis: P.ya, colorscale: cc ? RAMP : seqScale(), zmin: Number.isFinite(zmin) ? zmin : 0, zmax: Number.isFinite(zmax) ? zmax : 1, showscale: i === 0, xgap: 1, ygap: 1,
        colorbar: { title: { text: esc(label), side: 'right' }, thickness: 12, len: 0.8, outlinewidth: 0, x: 1.02 + (E.gy ? 0.06 : 0) }, hovertemplate: `${esc(label)}: %{z}<extra></extra>` };
      if (e.label && e.label !== 'none') {
        tr.text = cl.z.map((row, iy) => row.map((v, ix) => (v == null ? '' : e.label === 'percent' ? `${(100 * cl.n[iy][ix] / (cl.tot || 1)).toFixed(1)}%` : fmt(cc ? +v.toPrecision(3) : v))));
        tr.texttemplate = '%{text}';
        tr.textfont = { size: 10 };
      }
      const ti = E.fig.traces.push(tr) - 1;
      const oi = E.fig.traces.push({ type: 'heatmap', x: hx.centers, y: hy.centers, z: cl.z.map((row) => row.map(() => null)), xaxis: P.xa, yaxis: P.ya, colorscale: [[0, rgba(SM.report.SELECTED, 0.3)], [1, rgba(SM.report.SELECTED, 0.9)]], zmin: 0, zmax: 1, showscale: false, hoverinfo: 'skip', xgap: 1, ygap: 1 }) - 1;
      E.fig.links.push({ trace: ti, overlay: oi, kind: 'cell', rows: cl.rows });
    });
    void grand;
  };

  RENDER.mosaic = async (E, e) => {
    const tables = [];
    for (const P of E.panels) {
      const s = P.series[0];
      const LX = E.axisLevels(s.xc), LY = E.axisLevels(s.yc);
      const cnt = LX.lv.map(() => LY.lv.map(() => 0)), mem = LX.lv.map(() => LY.lv.map(() => []));
      for (const r of P.rows) {
        const i = E.levelPos(s.xc, s.xc.values[r]), j = E.levelPos(s.yc, s.yc.values[r]);
        if (i == null || j == null) continue;
        cnt[i][j] += E.W(r); mem[i][j].push(r);
      }
      const colTot = cnt.map((row) => row.reduce((a, b) => a + b, 0));
      const N = colTot.reduce((a, b) => a + b, 0) || 1;
      const gap = 0.012;
      let x0 = 0;
      const xs = [], ws = [];
      colTot.forEach((c) => { const w = c / N; xs.push(x0 + w / 2); ws.push(Math.max(0, w - gap)); x0 += w; });
      LY.lv.forEach((_, j) => {
        const base = [], h = [], rows = [];
        cnt.forEach((row, i) => {
          const below = row.slice(0, j).reduce((a, b) => a + b, 0);
          base.push(colTot[i] ? below / colTot[i] : 0);
          h.push(colTot[i] ? row[j] / colTot[i] : 0);
          rows.push(mem[i][j]);
        });
        const color = PALETTE[j % PALETTE.length];
        const text = e.cellLabel === 'count' ? cnt.map((row) => (row[j] ? fmt(row[j]) : '')) : e.cellLabel === 'percent' ? h.map((v) => (v ? `${(100 * v).toFixed(1)}%` : '')) : undefined;
        const tr = { type: 'bar', x: xs, y: h, base, width: ws, xaxis: P.xa, yaxis: P.ya, marker: { color: rgba(color, 0.85), line: { color: SM.util.themeColors().surface, width: 1 } }, text, textposition: text ? 'inside' : undefined, insidetextanchor: 'middle', textfont: { size: 10 },
          hovertext: cnt.map((row, i) => `${esc(s.xc.name)}: ${esc(LX.labels[i])}<br>${esc(s.yc.name)}: ${esc(LY.labels[j])}<br>Count: ${fmt(row[j])} (${(100 * h[i]).toFixed(1)}%)`), hovertemplate: '%{hovertext}<extra></extra>',
          name: esc(LY.labels[j]), legendgroup: `m${j}`, showlegend: P.idx === 0 };
        E.anyLegend = true;
        const ti = E.fig.traces.push(tr) - 1;
        const oi = E.fig.traces.push(overlayBar(tr)) - 1;
        E.fig.links.push({ trace: ti, overlay: oi, kind: 'bar', rows, len: h, horiz: false });
      });
      P.axes = {
        x: { range: [0, 1], tickmode: 'array', tickvals: xs, ticktext: LX.labels.map(esc), showgrid: false, zeroline: false, automargin: true },
        y: { range: [0, 1], tickformat: '.0%', showgrid: false, zeroline: false, automargin: true },
      };
      P.freeX = true;
      tables.push({ P, cnt });
    }
    E.legendTitle = E.panels[0].series[0].yc.name;
    if (e.chisq) {
      const res = await E.call('graph.chisq', { tables: tables.map((x) => x.cnt), x: E.panels[0].series[0].xc.name, y: E.panels[0].series[0].yc.name });
      res.tests.forEach((r, i) => {
        const P = tables[i].P;
        const text = r.error ? esc(r.error) : `Pearson χ² ${fmt(r.chi2, { sig: 5 })}, df ${r.df}, p ${SM.util.fmtP(r.p)}`;
        E.fig.annotations.push({ text, xref: `${P.xa} domain`, yref: `${P.ya} domain`, x: 0.5, y: 1, yanchor: 'bottom', yshift: 2, xanchor: 'center', showarrow: false, font: { size: 10 } });
        E.extraTop = 16;
        if (!r.error && r.min_expected < 5) E.note(`Mosaic: the smallest expected count is ${fmt(r.min_expected, { sig: 3 })}; with counts below 5 the χ² p-value is approximate.`);
      });
    }
  };

  RENDER.caption = async (E, e) => {
    const perFactor = e.location === 'factor';
    const blocks = [];
    E.forCells((P, s, si, gi, rows) => {
      const R = axesRoles(s.xc, s.yc);
      const items = perFactor ? E.items(R, rows) : [{ pos: 0, rows: rows.filter((r) => Number.isFinite(R.resp.values[r])), label: '' }];
      blocks.push({ P, s, si, gi, R, items });
    });
    const stats = (e.stats && e.stats.length ? e.stats : ['mean']).slice(0, 5);
    await E.fillStats(blocks, stats);
    const tc = SM.util.themeColors();
    for (const b of blocks) {
      const { P, gi, R } = b;
      b.items.forEach((it) => {
        if (!it.rows.length) return;
        const lines = stats.map((st) => `${STAT_LABEL[st]}: ${fmt(E.statValue(it, st, null), { sig: 5 })}`);
        const color = gi >= 0 ? PALETTE[gi % PALETTE.length] : tc.text;
        const k = gi >= 0 ? gi : 0;
        if (perFactor && R.fac) {
          const a = { text: lines.join('<br>'), showarrow: false, font: { size: 10, color }, xref: R.horiz ? `${P.xa} domain` : P.xa, yref: R.horiz ? P.ya : `${P.ya} domain` };
          if (R.horiz) { a.x = 0.99; a.xanchor = 'right'; a.y = it.pos; a.yshift = -k * 12 * stats.length; } else { a.x = it.pos; a.y = 0.99; a.yanchor = 'top'; a.yshift = -k * 12 * stats.length; }
          E.fig.annotations.push(a);
        } else {
          E.fig.annotations.push({ text: lines.join('<br>'), showarrow: false, font: { size: 10, color }, xref: `${P.xa} domain`, yref: `${P.ya} domain`, x: 0.99, y: 0.99, xanchor: 'right', yanchor: 'top', yshift: -k * 13 * stats.length, align: 'right', bgcolor: rgba(tc.surface, 0.75) });
        }
      });
    }
  };

  RENDER.pie = async (E, e) => {
    const s0 = E.panels[0].series[0];
    const R0 = axesRoles(s0.xc, s0.yc);
    let stat = e.summary === 'auto' || !e.summary ? (R0.resp ? 'sum' : 'n') : e.summary;
    if (!R0.resp) stat = 'n';
    const blocks = [];
    for (const P of E.panels) { const R = axesRoles(P.series[0].xc, P.series[0].yc); blocks.push({ P, si: 0, gi: -1, R, items: E.items(R, P.rows) }); }
    await E.fillStats(blocks, [stat]);
    for (const b of blocks) {
      const { P, R } = b;
      if (!b.items.length) continue;
      const vals = b.items.map((it) => Math.max(0, E.statValue(it, stat, null) || 0));
      const tr = {
        type: 'pie', labels: b.items.map((it) => esc(it.label)), values: vals, sort: false, direction: 'clockwise', hole: e.pieStyle === 'ring' ? 0.45 : 0,
        marker: { colors: b.items.map((it) => PALETTE[it.pos % PALETTE.length]), line: { color: SM.util.themeColors().surface, width: 1 } },
        textinfo: e.label === 'none' ? 'none' : e.label === 'value' ? 'value' : e.label === 'level' ? 'label' : 'percent', textfont: { size: 10 },
        hovertemplate: `%{label}<br>${esc(R.resp && stat !== 'n' ? `${STAT_LABEL[stat]}(${R.resp.name})` : 'N')}: %{value}<br>%{percent}<extra></extra>`,
        domain: { x: [0, 1], y: [0, 1] }, showlegend: P.idx === 0, name: '',
      };
      E.anyLegend = true;
      const ti = E.fig.traces.push(tr) - 1;
      (E.pies || (E.pies = [])).push({ tr, P });
      E.fig.links.push({ trace: ti, kind: 'slice', rows: b.items.map((it) => it.rows) });
    }
    E.legendTitle = R0.fac ? R0.fac.name : '';
  };

  /* The model elements: one Python call per pair of X and Y columns, with
     a code for each (panel, column, group). */
  async function perPair(E, fn, extra) {
    const blocks = [];
    E.forCells((P, s, si, gi, rows) => { if (s.xc && s.yc && !isCat(s.xc) && !isCat(s.yc)) blocks.push({ P, s, si, gi, rows }); });
    const byPair = new Map();
    for (const b of blocks) { const k = `${b.s.xc.id}|${b.s.yc.id}`; if (!byPair.has(k)) byPair.set(k, []); byPair.get(k).push(b); }
    for (const list of byPair.values()) {
      const rows = [], codes = [];
      list.forEach((b, i) => { for (const r of b.rows) { rows.push(r); codes.push(i); } });
      const res = await E.call(fn, { x: list[0].s.xc.name, y: list[0].s.yc.name, rows, codes, k: list.length, freq: E.freqName, by: E.byNames, ...extra });
      list.forEach((b, i) => { b.res = res; b.i = i; });
    }
    return blocks;
  }

  function band(E, P, xs, lo, hi, color, alpha = 0.18) {
    const ok = xs.map((_, k) => lo[k] != null && hi[k] != null);
    const x = xs.filter((_, k) => ok[k]), l = lo.filter((_, k) => ok[k]), h = hi.filter((_, k) => ok[k]);
    return { type: E.lineType(), mode: 'lines', x: [...x, ...x.slice().reverse()], y: [...h, ...l.slice().reverse()], fill: 'toself', fillcolor: rgba(color, alpha), line: { width: 0 }, hoverinfo: 'skip', showlegend: false, xaxis: P.xa, yaxis: P.ya };
  }

  RENDER.smoother = async (E, e) => {
    const method = e.method === 'lowess' ? 'lowess' : 'spline';
    E.note(method === 'lowess'
      ? `Smoother: Local Kernel is statsmodels' lowess (span ${fmt(e.width ?? 0.667)}, ${e.robust ?? 3} robustifying iterations), not JMP's own kernel smoother.`
      : `Smoother: a cubic smoothing spline with λ = ${fmt(e.lambda ?? 0.05)} on standardized X, JMP's criterion (scipy's make_smoothing_spline).`);
    const blocks = await perPair(E, 'graph.smoother', method === 'lowess' ? { method, frac: e.width ?? 0.667, it: e.robust ?? 3 } : { method, lam: e.lambda ?? 0.05, conf: !!e.conf, alpha: E.S.alpha || 0.05 });
    for (const b of blocks) {
      const c = b.res.curves[b.i];
      if (!c || c.error) { if (c && c.error && b.rows.length) E.note(`Smoother${b.gi >= 0 ? ` (${E.G.labels[b.gi]})` : ''}: ${c.error}.`); continue; }
      const color = E.colorFor(b.si, b.gi, inkColor());
      if (c.lower) E.fig.traces.push(band(E, b.P, c.x, c.lower, c.upper, color));
      E.fig.traces.push({ type: E.lineType(), mode: 'lines', x: c.x, y: c.y, xaxis: b.P.xa, yaxis: b.P.ya, line: { color, width: 2.2 }, hovertemplate: `Smoother (${method === 'lowess' ? `local kernel, width ${fmt(e.width ?? 0.667)}` : `λ ${fmt(e.lambda ?? 0.05)}`})<br>%{x}, %{y}<extra></extra>`, ...E.legend(b.si, b.gi) });
    }
  };

  RENDER.fit = async (E, e) => {
    const robust = e.fitType === 'robust';
    const blocks = await perPair(E, 'graph.fit', { degree: Number(e.degree) || 1, robust, alpha: E.S.alpha || 0.05 });
    const byPanel = new Map();
    for (const b of blocks) {
      const f = b.res.fits[b.i];
      if (!f || f.error) { if (f && f.error && b.rows.length) E.note(`Line of Fit${b.gi >= 0 ? ` (${E.G.labels[b.gi]})` : ''}: ${f.error}.`); continue; }
      const color = E.colorFor(b.si, b.gi, dark() ? '#e8a07a' : '#b0413e');
      if (e.confFit !== false && f.fit_lower) E.fig.traces.push(band(E, b.P, f.x, f.fit_lower, f.fit_upper, color, 0.16));
      if (e.confPred && f.pred_lower) {
        for (const arr of [f.pred_lower, f.pred_upper]) E.fig.traces.push({ type: E.lineType(), mode: 'lines', x: f.x, y: arr, xaxis: b.P.xa, yaxis: b.P.ya, line: { color, width: 1, dash: 'dash' }, hoverinfo: 'skip', showlegend: false });
      }
      E.fig.traces.push({ type: E.lineType(), mode: 'lines', x: f.x, y: f.y, xaxis: b.P.xa, yaxis: b.P.ya, line: { color, width: 2 }, hovertemplate: `Line of Fit${robust ? ' (robust)' : ''}<br>%{x}, %{y}<extra></extra>`, ...E.legend(b.si, b.gi) });
      const lines = [];
      if (e.equation) lines.push(...equation(f, b.s.xc.name, b.s.yc.name));
      if (e.r2 && f.r2 != null) lines.push(`R² ${fmt(f.r2, { sig: 4 })}`);
      if (e.rmse && f.rmse != null) lines.push(`RMSE ${fmt(f.rmse, { sig: 4 })}`);
      if (e.ftest && f.f != null) lines.push(`F ${fmt(f.f, { sig: 4 })}, p ${SM.util.fmtP(f.p)}`);
      if (lines.length) {
        const k = byPanel.get(b.P.idx) || 0;
        byPanel.set(b.P.idx, k + lines.length);
        E.fig.annotations.push({ text: lines.map(esc).join('<br>'), xref: `${b.P.xa} domain`, yref: `${b.P.ya} domain`, x: 0.01, y: 0.99, xanchor: 'left', yanchor: 'top', yshift: -13 * k, align: 'left', showarrow: false, font: { size: 10, color: b.gi >= 0 || E.nSeries > 1 ? color : SM.util.themeColors().text }, bgcolor: rgba(SM.util.themeColors().surface, 0.7) });
      }
    }
  };

  /* JMP's form of the fitted polynomial, as lines of text (escaped by the caller). */
  function equation(f, x, y) {
    const c = f.coef;
    const term = (v, s) => `${v < 0 ? '− ' : '+ '}${fmt(Math.abs(v), { sig: 4 })}${s}`;
    const m = fmt(f.mean, { sig: 4 });
    const parts = [fmt(c[0], { sig: 4 })];
    if (c.length > 1) parts.push(term(c[1], `·${x}`));
    if (c.length > 2) parts.push(term(c[2], `·(${x} − ${m})²`));
    if (c.length > 3) parts.push(term(c[3], `·(${x} − ${m})³`));
    return [`${y} =`, parts.slice(0, 2).join(' '), ...(parts.length > 2 ? [parts.slice(2).join(' ')] : [])];
  }

  RENDER.ellipse = async (E, e) => {
    const blocks = await perPair(E, 'graph.ellipse', { coverage: Number(e.coverage) || 0.95 });
    const perPanel = new Map();
    for (const b of blocks) {
      const r = b.res.ellipses[b.i];
      if (!r || r.error) { if (r && r.error && b.rows.length > 2) E.note(`Ellipse${b.gi >= 0 ? ` (${E.G.labels[b.gi]})` : ''}: ${r.error}.`); continue; }
      const color = E.colorFor(b.si, b.gi, inkColor());
      const tr = { type: E.lineType(), mode: 'lines', x: r.x, y: r.y, xaxis: b.P.xa, yaxis: b.P.ya, line: { color, width: 1.6 }, hovertemplate: `${fmt(100 * (Number(e.coverage) || 0.95))}% density ellipse<br>r = ${fmt(r.r, { sig: 4 })}<extra></extra>`, ...E.legend(b.si, b.gi) };
      if (e.shaded) { tr.fill = 'toself'; tr.fillcolor = rgba(color, 0.14); }
      E.fig.traces.push(tr);
      if (e.meanPoint) E.fig.traces.push({ type: E.lineType(), mode: 'markers', x: [r.mean[0]], y: [r.mean[1]], xaxis: b.P.xa, yaxis: b.P.ya, marker: { symbol: 'cross', size: 10, color }, hovertemplate: `mean (${fmt(r.mean[0])}, ${fmt(r.mean[1])})<extra></extra>`, showlegend: false });
      if (e.correlation) {
        const k = perPanel.get(b.P.idx) || 0;
        perPanel.set(b.P.idx, k + 1);
        E.fig.annotations.push({ text: `r ${fmt(r.r, { sig: 4 })}`, xref: `${b.P.xa} domain`, yref: `${b.P.ya} domain`, x: 0.99, y: 0.01, xanchor: 'right', yanchor: 'bottom', yshift: 13 * k, showarrow: false, font: { size: 10, color: b.gi >= 0 || E.nSeries > 1 ? color : SM.util.themeColors().text } });
      }
    }
  };

  RENDER.contour = async (E, e) => {
    const s0 = E.panels[0].series[0];
    const R0 = axesRoles(s0.xc, s0.yc);
    const L = clamp(Math.round(e.levels || 4), 1, 20);
    if (R0.facCat && R0.resp) return violins(E, e);
    const blocks = await perPair(E, 'graph.density', { bw: e.bw || 1 });
    for (const b of blocks) {
      const d = b.res.densities[b.i];
      if (!d || d.error) { if (d && d.error && b.rows.length > 2) E.note(`Contour${b.gi >= 0 ? ` (${E.G.labels[b.gi]})` : ''}: ${d.error}.`); continue; }
      const color = E.colorFor(b.si, b.gi, inkColor());
      const fill = e.fill !== false, line = e.line !== false;
      // graph.density gives the share of the points inside the density
      // contour through each grid point; 1 minus that rises towards the
      // mode like a density, and its contours at 0, 1/L, ... hold 100%,
      // (L-1)/L, ... of the points. Below 0, outside them all, nothing is filled.
      const z = d.z.map((row) => row.map((m) => (m == null ? null : 1 - m)));
      const lo = -1 / L, cut = (0 - lo) / (1 - lo);
      const tr = {
        type: 'contour', x: d.x, y: d.y, z, xaxis: b.P.xa, yaxis: b.P.ya, autocontour: false, ncontours: L,
        contours: { start: 0, end: 1 - 1 / L + 1e-9, size: 1 / L, coloring: fill ? 'fill' : 'lines', showlines: line },
        zmin: lo, zmax: 1, showscale: false, hoverinfo: 'skip', ...E.legend(b.si, b.gi),
        line: { width: line ? 1 : 0, color: fill ? rgba(color, 0.9) : undefined, smoothing: 1 },
        colorscale: fill ? [[0, rgba(color, 0)], [cut - 1e-6, rgba(color, 0)], [cut, rgba(color, 0.1)], [1, rgba(color, 0.62)]] : [[0, color], [1, color]],
      };
      E.fig.traces.push(tr);
    }
  };

  /* Contour with one categorical axis: a violin of the other per level. */
  async function violins(E, e) {
    const blocks = [];
    E.forCells((P, s, si, gi, rows) => { const R = axesRoles(s.xc, s.yc); for (const it of E.items(R, rows)) blocks.push({ P, s, si, gi, R, it }); });
    if (!blocks.length) return;
    const resp = blocks[0].R.resp;
    const fac = blocks[0].R.fac;
    const rows = [], codes = [];
    blocks.forEach((b, i) => { for (const r of b.it.rows) { rows.push(r); codes.push(i); } });
    const res = await E.call('graph.kde1', { y: resp.name, rows, codes, k: blocks.length, bw: e.bw || 1, freq: E.freqName, by: E.byNames.concat(fac ? [fac.name] : []) });
    let most = 0;
    res.densities.forEach((d) => { if (d && d.d) for (const v of d.d) most = Math.max(most, v); });
    const slots = E.slots();
    blocks.forEach((b, i) => {
      const d = res.densities[i];
      if (!d || !d.d) return;
      const off = slots === 1 ? 0 : -0.4 + (E.slotOf(b.si, b.gi) + 0.5) * (0.8 / slots);
      const half = (0.4 / slots) / (most || 1);
      const p = b.it.pos + off;
      const across = [...d.d.map((v) => p + v * half), ...d.d.slice().reverse().map((v) => p - v * half)];
      const along = [...d.y, ...d.y.slice().reverse()];
      const color = E.colorFor(b.si, b.gi, inkColor());
      const tr = { type: E.lineType(), mode: 'lines', fill: 'toself', fillcolor: rgba(color, e.fill !== false ? 0.25 : 0), line: { color, width: e.line !== false ? 1.2 : 0 }, xaxis: b.P.xa, yaxis: b.P.ya, hovertemplate: `${esc(b.it.label)}: density of ${esc(resp.name)}<extra></extra>`, ...E.legend(b.si, b.gi) };
      if (b.R.horiz) { tr.x = along; tr.y = across; } else { tr.x = across; tr.y = along; }
      E.fig.traces.push(tr);
    });
  }

  /* Linear interpolation in an increasing xs. */
  function interp1(xs, ys, v) {
    const n = xs.length;
    if (!(v > xs[0])) return ys[0];
    if (v >= xs[n - 1]) return ys[n - 1];
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (xs[m] <= v) lo = m; else hi = m; }
    return ys[lo] + ((v - xs[lo]) / (xs[hi] - xs[lo] || 1)) * (ys[hi] - ys[lo]);
  }

  /* Bean: statsmodels' beanplot (Kampstra's bean plot). For each level, and
     each group, the violin of a Gaussian kernel density drawn to one width
     (graph.bean, from statsmodels' own violin), a line for each row (the
     beans: line markers, linked to their rows), the mean as a longer line
     and the median as a cross; the overall mean dotted across the panel.
     With Split Two Groups and an Overlay of two levels, the first level
     takes the left half of each bean and the second the right. The sizes
     follow statsmodels' plot_opts: the violin 0.8 of a level's room, a
     bean 0.5 and the mean line 0.5 of it. */
  RENDER.bean = async (E, e) => {
    const blocks = [];
    E.forCells((P, s, si, gi, rows) => { const R = axesRoles(s.xc, s.yc); for (const it of E.items(R, rows)) blocks.push({ P, s, si, gi, R, it }); });
    if (!blocks.length) return;
    const R0 = blocks[0].R;
    const resp = R0.resp, fac = R0.fac, horiz = R0.horiz;
    const rows = [], codes = [];
    blocks.forEach((b, i) => { for (const r of b.it.rows) { rows.push(r); codes.push(i); } });
    const res = await E.call('graph.bean', { y: resp.name, rows, codes, k: blocks.length, bw: e.bw || 1, cutoff: !!e.cutoff, freq: E.freqName, by: E.byNames.concat(fac ? [fac.name] : []) });
    const nG = E.G ? Math.min(60, E.G.labels.length) : 0;
    const split = !!e.split && nG === 2 && E.nSeries === 1;
    if (e.split && !split) E.note('Bean: Split Two Groups needs an Overlay (or a categorical Color) of two levels, and one column on each axis.');
    const slots = split ? 1 : E.slots();
    // A bean is a line marker, its length in pixels: the room a level has along its axis.
    const nPos = fac && isCat(fac) ? Math.max(1, E.axisLevels(fac).lv.length) : 1;
    const room = horiz ? (E.B.height(E.nR) - 90) / Math.max(1, E.nR) : (E.B.width() - 110 - (E.G ? 130 : 0)) / Math.max(1, E.nC);
    const pxUnit = Math.max(8, room / nPos);
    const tc = SM.util.themeColors();
    const medColor = dark() ? '#f08a80' : '#b0302a';
    const perPanel = new Map();     // panel -> the mean lines and the medians
    const totals = new Map();       // panel|series -> n and sum, for the overall mean
    const put = (tr, along, across) => { if (horiz) { tr.x = along; tr.y = across; } else { tr.x = across; tr.y = along; } };
    blocks.forEach((b, i) => {
      const d = res.beans[i];
      if (!d || !d.n) return;
      const { P, si, gi } = b;
      const side = split ? (gi === 0 ? -1 : 1) : 0;
      const off = split || slots === 1 ? 0 : -0.4 + (E.slotOf(si, gi) + 0.5) * (0.8 / slots);
      const pos = b.it.pos + off;
      const half = 0.4 / slots;
      const color = E.colorFor(si, gi, inkColor());
      const key = `${P.idx}|${si}`;
      const tt = totals.get(key) || { n: 0, s: 0, P, si };
      tt.n += d.n; tt.s += d.n * d.mean;
      totals.set(key, tt);
      const label = `${esc(b.it.label || resp.name)}${gi >= 0 ? `, ${esc(E.G.labels[gi])}` : ''}`;
      if (d.y && d.d) {
        let across, along;
        if (!side) { across = [...d.d.map((v) => pos + v * half), ...d.d.slice().reverse().map((v) => pos - v * half)]; along = [...d.y, ...d.y.slice().reverse()]; }
        else { across = [...d.d.map((v) => pos + side * v * half), pos, pos]; along = [...d.y, d.y[d.y.length - 1], d.y[0]]; }
        const tr = { type: 'scatter', mode: 'lines', fill: 'toself', fillcolor: rgba(color, 0.2), line: { color, width: 1.1 }, xaxis: P.xa, yaxis: P.ya,
          hovertemplate: `${label}<br>density of ${esc(resp.name)}, bandwidth ${fmt(d.bandwidth, { sig: 3 })}<extra></extra>`, ...E.legend(si, gi) };
        put(tr, along, across);
        E.fig.traces.push(tr);
      } else if (d.error && b.it.rows.length > 1) E.note(`Bean${b.it.label ? ` (${b.it.label})` : ''}: ${d.error}.`);
      if (e.beans !== 'none') {
        const jit = e.beans === 'jitter' && d.y && d.d;
        const center = side ? pos + side * 0.125 : pos;
        const A = [], C = [], RR = [], H = [];
        for (const r of b.it.rows) {
          const v = resp.values[r];
          if (!Number.isFinite(v)) continue;
          let q = center;
          if (jit) { const u = hash01(r, 23); q = pos + (side ? side * u : 2 * u - 1) * interp1(d.y, d.d, v) * half; }
          A.push(v); C.push(q); RR.push(r); H.push(rowHover(E.t, r, [fac, resp, E.G ? E.G.col : null]));
        }
        if (RR.length) {
          const len = (side ? 0.25 : 0.5 / slots) * pxUnit;
          const tr = { type: 'scatter', mode: 'markers', rows: RR, xaxis: P.xa, yaxis: P.ya, hovertext: H, hovertemplate: '%{hovertext}<extra></extra>', showlegend: false, legendgroup: gi >= 0 ? `g${gi}` : undefined,
            marker: jit ? { size: 4.5, color, opacity: 0.85, line: { width: 0 } } : { symbol: horiz ? 'line-ns-open' : 'line-ew-open', size: clamp(Math.round(len), 4, 90), color: rgba(color, 0.8), line: { width: 1.1 } } };
          put(tr, A, C);
          if (E.fig.mask) tr.selected = { marker: { opacity: 1 } };
          E.fig.traces.push(tr);
        }
      }
      let pp = perPanel.get(P.idx);
      if (!pp) { pp = { P, ma: [], mc: [], mh: [], da: [], dc: [], dh: [] }; perPanel.set(P.idx, pp); }
      if (e.mean !== false && Number.isFinite(d.mean)) {
        const w = side ? 0.25 : 0.25 / slots;
        const a = side ? pos : pos - w, z = side ? pos + side * 2 * w : pos + w;
        const h = `${label}<br>Mean(${esc(resp.name)}): ${fmt(d.mean, { sig: 6 })}<br>N: ${fmt(d.n)}`;
        pp.ma.push(d.mean, d.mean, null); pp.mc.push(a, z, null); pp.mh.push(h, h, '');
      }
      if (e.median !== false && Number.isFinite(d.median)) {
        pp.da.push(d.median); pp.dc.push(side ? pos + side * 0.08 : pos); pp.dh.push(`${label}<br>Median(${esc(resp.name)}): ${fmt(d.median, { sig: 6 })}`);
      }
    });
    for (const pp of perPanel.values()) {
      const { P } = pp;
      if (pp.ma.length) { const tr = { type: 'scatter', mode: 'lines', xaxis: P.xa, yaxis: P.ya, line: { color: tc.text, width: 2.6 }, hovertext: pp.mh, hovertemplate: '%{hovertext}<extra></extra>', showlegend: false }; put(tr, pp.ma, pp.mc); E.fig.traces.push(tr); }
      if (pp.da.length) { const tr = { type: 'scatter', mode: 'markers', xaxis: P.xa, yaxis: P.ya, marker: { symbol: 'cross-thin-open', size: 11, color: medColor, line: { width: 2, color: medColor } }, hovertext: pp.dh, hovertemplate: '%{hovertext}<extra></extra>', showlegend: false }; put(tr, pp.da, pp.dc); E.fig.traces.push(tr); }
    }
    if (e.overall !== false) {
      for (const tt of totals.values()) {
        if (!tt.n) continue;
        const m = tt.s / tt.n;
        const line = { color: E.nSeries > 1 ? E.colorFor(tt.si, -1, tc.muted) : tc.muted, width: 1.3, dash: 'dot' };
        E.fig.shapes.push(horiz
          ? { type: 'line', xref: tt.P.xa, yref: `${tt.P.ya} domain`, x0: m, x1: m, y0: 0, y1: 1, line, layer: 'below' }
          : { type: 'line', xref: `${tt.P.xa} domain`, yref: tt.P.ya, x0: 0, x1: 1, y0: m, y1: m, line, layer: 'below' });
      }
    }
    E.note(`Bean: statsmodels' beanplot. Each violin is a Gaussian kernel density (scipy's gaussian_kde, Scott's rule${(e.bw || 1) !== 1 ? ` times ${fmt(e.bw)}` : ''}) drawn to one width, from the smallest value to the largest${e.cutoff ? '' : ' and 1.5 standard deviations past them'}; a line for each row, the mean as the long line and the median as the cross${e.overall !== false ? '. The dotted line is the overall mean, as Kampstra\'s bean plot draws it (statsmodels\' beanplot does not)' : ''}.`);
  };

  /* ---- Graph Builder: the builder -----------------------------------------------------------
     The report's top outline holds the builder: the columns on the left
     with the element properties under them, the element palette above the
     graph, and the drop zones around it. A change updates spec.options.gb
     (without redoing the report) and redraws the graph alone; Redo and a
     saved project rebuild everything from the state. */
  const UI = new WeakMap();          // report -> what the view keeps between redos: filter, selection, undo
  const BUILDERS = new WeakMap();    // report -> its current builder
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function infoSlot(key) { return typeof KvotInfo !== 'undefined' ? KvotInfo.slot(key) : null; }

  class Builder {
    constructor(ctx) {
      this.ctx = ctx;
      this.t = ctx.table;
      this.report = ctx.report;
      this.runSeq = ctx.report.seq;
      let ui = UI.get(ctx.report);
      if (!ui) { ui = { filter: '', sel: null, undo: [] }; UI.set(ctx.report, ui); }
      this.ui = ui;
      this.S = normalize(clone(ctx.opt('gb', null)), this.t);
      this.seq = 0;
      this.busy = 0;
      this.plotBox = null;
      this.pendingBox = null;
      this.lastFig = null;
      this.shown = new Promise((res) => { this._shown = res; });   // the first figure is on show
      this.build();
      // A new column does not redo the report (the core leaves reports alone
      // then), but it belongs in the builder's list at once.
      const off = this.t.on('schema', (e) => {
        if (this.dead) { off(); return; }
        if (e && e.added) this.renderColumns();
      });
    }

    get dead() { return this.report.seq !== this.runSeq; }

    /* ---- the pieces ---- */
    build() {
      const root = el('div', { class: 'sm-gb' });
      this.root = root;
      root._gb = this.api();
      const btn = (text, fn, extra = {}) => { const b = el('button', { type: 'button', class: 'sm-btn small', text, ...extra }); b.addEventListener('click', fn); return b; };
      this.undoBtn = btn('Undo', () => this.undo(), { dataset: { gbkey: 'undo' } });
      this.doneBtn = btn('Done', () => this.update((S) => { S.done = !S.done; }), { dataset: { gbkey: 'done' }, 'aria-pressed': 'false' });
      const start = btn('Start Over', () => this.startOver(), { dataset: { gbkey: 'start' } });
      this.bar = el('div', { class: 'sm-gb-bar', dataset: { noexport: '' } }, this.undoBtn, start, this.doneBtn,
        el('span', { class: 'sm-gb-hint', text: 'Drag columns onto the zones, or select a column and click a zone. Click an element to show it; shift-click to add it.' }), infoSlot('p:graphbuilder'));
      // columns
      this.filter = el('input', { type: 'search', class: 'sm-gb-filter', placeholder: 'Filter', 'aria-label': 'Filter columns' });
      this.filter.value = this.ui.filter || '';
      this.filter.addEventListener('input', () => { this.ui.filter = this.filter.value; this.renderColumns(); });
      this.colCount = el('span', { class: 'sm-count' });
      this.colList = el('ul', { class: 'sm-gb-collist', role: 'listbox', 'aria-label': 'Columns: drag one onto a zone, or select one and press Enter for the zones' });
      this.wireColumns();
      const cols = el('div', { class: 'sm-gb-cols' }, el('h4', null, 'Select Columns', el('span', { class: 'sm-grow' }), this.colCount), this.filter, this.colList);
      this.propsBox = el('div', { class: 'sm-gb-props', 'aria-live': 'polite' });
      const left = el('aside', { class: 'sm-gb-left', 'aria-label': 'Columns and element properties', dataset: { noexport: '' } }, cols, this.propsBox);
      // palette
      this.palette = el('div', { class: 'sm-gb-palette', role: 'toolbar', 'aria-label': 'Elements: click to show one, shift-click to add or remove one', dataset: { noexport: '' } });
      this.wirePalette();
      // zones around the graph
      this.zoneEls = {};
      for (const z of ZONES) {
        const box = el('div', { class: `sm-gb-zone sm-gb-z-${z.key}${z.key === 'y' || z.key === 'groupY' ? ' is-vertical' : ''}`, role: 'button', tabindex: '0', dataset: { zone: z.key, gbkey: `zone:${z.key}`, noexport: '' } });
        this.wireZone(box, z);
        this.zoneEls[z.key] = box;
      }
      this.plotWrap = el('div', { class: 'sm-gb-plotwrap' });
      const Z = this.zoneEls;
      const side = el('div', { class: 'sm-gb-side' }, Z.wrap, Z.overlay, Z.color, Z.size, Z.freq);
      this.frame = el('div', { class: 'sm-gb-frame' }, Z.groupX, Z.y, this.plotWrap, Z.groupY, side, Z.x);
      this.status = el('div', { class: 'sm-gb-status' });
      this.showCP = btn('Show Control Panel', () => this.update((S) => { S.done = false; }), { class: 'sm-linkbtn sm-gb-showcp', dataset: { gbkey: 'showcp' } });
      const center = el('div', { class: 'sm-gb-center' }, this.palette, this.frame, this.status);
      root.append(this.showCP, this.bar, el('div', { class: 'sm-gb-work' }, left, center));
      this.renderColumns();
      this.renderChrome();
    }

    renderChrome() {
      const focusKey = this.root.contains(document.activeElement) ? document.activeElement.dataset.gbkey : null;
      this.root.classList.toggle('is-done', !!this.S.done);
      this.doneBtn.setAttribute('aria-pressed', String(!!this.S.done));
      this.undoBtn.disabled = !this.ui.undo.length;
      this.renderZones();
      this.renderPalette();
      this.renderProps();
      if (focusKey) { const f = this.root.querySelector(`[data-gbkey="${CSS.escape(focusKey)}"]`); if (f) f.focus({ preventScroll: true }); }
      // An open (i) of the builder follows its elements and their settings.
      if (typeof KvotInfo !== 'undefined' && KvotInfo.current && /^p:graphbuilder/.test(KvotInfo.current() || '')) KvotInfo.refresh();
    }

    renderColumns() {
      const f = (this.ui.filter || '').trim().toLowerCase();
      const list = this.colList;
      list.replaceChildren();
      const cols = this.t.columns.filter((c) => !f || c.name.toLowerCase().includes(f));
      this.colCount.textContent = String(this.t.columns.length);
      if (this.ui.sel && !this.t.col(this.ui.sel)) this.ui.sel = null;
      for (const c of cols) {
        const on = this.ui.sel === c.id;
        const li = el('li', { role: 'option', draggable: 'true', tabindex: on || (!this.ui.sel && c === cols[0]) ? '0' : '-1', 'aria-selected': String(on), dataset: { id: c.id, gbkey: `col:${c.id}` }, title: `${c.name}: ${TYPE_LABEL[c.modelingType]}, ${c.dataType}` },
          typeIcon(c.modelingType), el('span', { class: 'sm-colname', text: c.name }));
        if (on) li.classList.add('is-selected');
        list.append(li);
      }
      if (!cols.length) list.append(el('li', { class: 'sm-gb-none', text: 'No column matches.' }));
    }

    wireColumns() {
      const list = this.colList;
      const idOf = (ev) => { const li = ev.target.closest('li[data-id]'); return li ? li.dataset.id : null; };
      const select = (id) => {
        this.ui.sel = this.ui.sel === id ? null : id;
        for (const li of list.querySelectorAll('li[data-id]')) {
          const on = li.dataset.id === this.ui.sel;
          li.classList.toggle('is-selected', on);
          li.setAttribute('aria-selected', String(on));
        }
        this.root.classList.toggle('has-pick', !!this.ui.sel);
      };
      list.addEventListener('click', (ev) => { const id = idOf(ev); if (id) select(id); });
      list.addEventListener('dblclick', (ev) => { const id = idOf(ev); if (id) { this.ui.sel = null; this.autoAdd(this.t.col(id)); } });
      list.addEventListener('dragstart', (ev) => {
        const id = idOf(ev);
        if (!id) return;
        ev.dataTransfer.setData(MIME, JSON.stringify([id]));
        ev.dataTransfer.setData('text/plain', this.t.col(id).name);
        ev.dataTransfer.effectAllowed = 'copy';
        this.root.classList.add('is-dragging');
      });
      list.addEventListener('dragend', () => this.root.classList.remove('is-dragging'));
      list.addEventListener('contextmenu', (ev) => {
        const id = idOf(ev);
        if (!id) return;
        ev.preventDefault();
        SM.ui.menu(this.zoneMenuFor(this.t.col(id)), { x: ev.clientX, y: ev.clientY });
      });
      list.addEventListener('keydown', (ev) => {
        const items = [...list.querySelectorAll('li[data-id]')];
        if (!items.length) return;
        const cur = items.findIndex((li) => li === document.activeElement);
        if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
          ev.preventDefault();
          const k = clamp(cur + (ev.key === 'ArrowDown' ? 1 : -1), 0, items.length - 1);
          items.forEach((li, i) => li.setAttribute('tabindex', i === k ? '0' : '-1'));
          items[k].focus();
        } else if (ev.key === ' ') {
          ev.preventDefault();
          if (cur >= 0) select(items[cur].dataset.id);
        } else if (ev.key === 'Enter' || ev.key === 'ContextMenu' || (ev.key === 'F10' && ev.shiftKey)) {
          ev.preventDefault();
          if (cur < 0) return;
          const r = items[cur].getBoundingClientRect();
          SM.ui.menu(this.zoneMenuFor(this.t.col(items[cur].dataset.id)), { x: r.left + 20, y: r.bottom }, { returnFocus: items[cur] });
        } else if (ev.key === 'Escape' && this.ui.sel) { select(this.ui.sel); }
      });
    }

    /* The zones a column can go to, as a menu. */
    zoneMenuFor(c) {
      return [{ head: `Add ${c.name} to` }, ...ZONES.map((z) => {
        const why = zoneRefuses(z, c);
        return { label: z.label, disabled: !!why, title: why, action: () => this.addColumns(z.key, [c.id]) };
      })];
    }

    autoAdd(c) {
      const Z = this.S.zones;
      let key;
      if (!isCat(c)) key = !Z.y.length ? 'y' : !Z.x.length ? 'x' : 'y';
      else key = !Z.x.length ? 'x' : !Z.overlay.length ? 'overlay' : !Z.groupX.length ? 'groupX' : 'groupY';
      this.addColumns(key, [c.id]);
    }

    renderZones() {
      for (const z of ZONES) {
        const box = this.zoneEls[z.key];
        const list = this.S.zones[z.key];
        box.replaceChildren(el('span', { class: 'sm-gb-zlabel', text: z.label }));
        box.classList.toggle('is-empty', !list.length);
        for (const ref of list) {
          const c = this.t.col(ref.id);
          if (!c) continue;
          box.append(el('button', { type: 'button', class: 'sm-gb-chip', 'aria-haspopup': 'menu', 'aria-label': `${c.name} in ${z.label}: options (Delete removes it)`, dataset: { col: c.id, gbkey: `chip:${z.key}:${c.id}` } },
            typeIcon(c.modelingType), el('span', { class: 'sm-colname', text: c.name })));
        }
        if ((z.key === 'x' || z.key === 'y') && list.length > 1) box.append(el('span', { class: 'sm-gb-zmode', text: (z.key === 'x' ? this.S.xMode : this.S.yMode) === 'merge' ? 'merged' : 'side by side' }));
        const names = list.map((r) => r.name).join(', ');
        box.setAttribute('aria-label', `${z.label} zone${names ? `: ${names}` : ', empty'}. Drop a column here, or press Enter to add one; the context menu key for more.`);
      }
    }

    wireZone(box, z) {
      const hasCols = (ev) => ev.dataTransfer && [...ev.dataTransfer.types].includes(MIME);
      box.addEventListener('dragover', (ev) => {
        if (!hasCols(ev)) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'copy';
        box.classList.add('is-drop');
        const chip = ev.target.closest('.sm-gb-chip');
        box.querySelectorAll('.sm-gb-chip.is-drop').forEach((c) => { if (c !== chip) c.classList.remove('is-drop'); });
        if (chip) chip.classList.add('is-drop');
      });
      box.addEventListener('dragleave', (ev) => { if (!box.contains(ev.relatedTarget)) { box.classList.remove('is-drop'); box.querySelectorAll('.is-drop').forEach((c) => c.classList.remove('is-drop')); } });
      box.addEventListener('drop', (ev) => {
        box.classList.remove('is-drop');
        this.root.classList.remove('is-dragging');
        const raw = ev.dataTransfer.getData(MIME);
        if (!raw) return;
        ev.preventDefault();
        let ids = [];
        try { ids = JSON.parse(raw); } catch (e) { return; }
        const chip = ev.target.closest('.sm-gb-chip');
        this.addColumns(z.key, ids, { replaceId: chip ? chip.dataset.col : null });
      });
      const activate = (ev) => {
        const chip = ev.target.closest('.sm-gb-chip');
        if (this.ui.sel) {
          const id = this.ui.sel;
          this.ui.sel = null;
          this.root.classList.remove('has-pick');
          this.renderColumns();
          this.addColumns(z.key, [id], { replaceId: chip ? chip.dataset.col : null });
          return;
        }
        if (chip) SM.ui.menu(this.chipMenu(z, this.t.col(chip.dataset.col)), chip, { returnFocus: chip });
        else SM.ui.menu(this.addMenu(z), box, { returnFocus: box });
      };
      box.addEventListener('click', activate);
      box.addEventListener('keydown', (ev) => {
        const chip = ev.target.closest('.sm-gb-chip');
        if ((ev.key === 'Enter' || ev.key === ' ') && (ev.target === box || chip)) { ev.preventDefault(); activate(ev); }
        else if ((ev.key === 'Delete' || ev.key === 'Backspace') && chip) { ev.preventDefault(); this.removeColumn(z.key, chip.dataset.col); }
        else if (ev.key === 'ContextMenu' || (ev.key === 'F10' && ev.shiftKey)) { ev.preventDefault(); SM.ui.menu(this.zoneMenu(z), box, { returnFocus: box }); }
      });
      box.addEventListener('contextmenu', (ev) => {
        ev.preventDefault();
        const chip = ev.target.closest('.sm-gb-chip');
        SM.ui.menu(chip ? this.chipMenu(z, this.t.col(chip.dataset.col)) : this.zoneMenu(z), { x: ev.clientX, y: ev.clientY });
      });
    }

    addMenu(z) {
      const inZone = new Set(this.S.zones[z.key].map((r) => r.id));
      const items = this.t.columns.filter((c) => !inZone.has(c.id)).map((c) => {
        const why = zoneRefuses(z, c);
        return { label: c.name, mark: isCat(c) ? '▦' : '◢', disabled: !!why, title: why, action: () => this.addColumns(z.key, [c.id]) };
      });
      return [{ head: `Add to ${z.label}` }, ...(items.length ? items : [{ label: '(no more columns)', disabled: true }])];
    }

    zoneMenu(z) {
      const S = this.S;
      const list = S.zones[z.key];
      const items = [{ head: z.label }];
      if (z.key === 'x' || z.key === 'y') {
        const mk = z.key === 'x' ? 'xMode' : 'yMode';
        const first = list[0] ? this.t.col(list[0].id) : null;
        const on = !!(S.log && S.log[z.key]);
        items.push({ label: 'Merge Columns', checked: S[mk] === 'merge', disabled: list.length < 2, action: () => this.update((s) => { s[mk] = 'merge'; }) },
          { label: 'Side by Side', checked: S[mk] !== 'merge', disabled: list.length < 2, action: () => this.update((s) => { s[mk] = 'side'; }) },
          { label: 'Log Scale', checked: on, disabled: !first || isCat(first) || isDate(first), action: () => this.update((s) => { s.log = { ...(s.log || {}), [z.key]: !on }; }) }, { separator: true });
      }
      items.push({ label: 'Add Column', submenu: () => this.addMenu(z).slice(1) });
      items.push({ label: 'Swap with', disabled: !list.length, submenu: () => ZONES.filter((o) => o.key !== z.key).map((o) => ({ label: o.label, action: () => this.update((s) => { const a = s.zones[z.key]; s.zones[z.key] = s.zones[o.key]; s.zones[o.key] = a; }) })) });
      items.push({ label: 'Remove All', disabled: !list.length, action: () => this.update((s) => { s.zones[z.key] = []; }) });
      return items;
    }

    chipMenu(z, c) {
      if (!c) return [];
      const S = this.S;
      const items = [{ head: c.name }, { label: 'Remove', action: () => this.removeColumn(z.key, c.id) },
        { label: 'Move to', submenu: () => ZONES.filter((o) => o.key !== z.key).map((o) => { const why = zoneRefuses(o, c); return { label: o.label, disabled: !!why, title: why, action: () => this.update((s) => { s.zones[z.key] = s.zones[z.key].filter((r) => r.id !== c.id); const l = s.zones[o.key].filter((r) => r.id !== c.id); s.zones[o.key] = o.max === 1 ? [{ id: c.id, name: c.name }] : [...l, { id: c.id, name: c.name }]; }) }; }) },
        { label: 'Replace with', submenu: () => this.t.columns.filter((o) => o.id !== c.id).map((o) => { const why = zoneRefuses(z, o); return { label: o.name, disabled: !!why, title: why, action: () => this.addColumns(z.key, [o.id], { replaceId: c.id }) }; }) }];
      if ((z.key === 'x' || z.key === 'y') && S.zones[z.key].length > 1) {
        const mk = z.key === 'x' ? 'xMode' : 'yMode';
        items.push({ separator: true }, { label: 'Merge Columns', checked: S[mk] === 'merge', action: () => this.update((s) => { s[mk] = s[mk] === 'merge' ? 'side' : 'merge'; }) });
      }
      return items;
    }

    addColumns(key, ids, { replaceId = null } = {}) {
      const z = ZONE[key];
      const cols = ids.map((id) => this.t.col(id)).filter(Boolean);
      const bad = cols.map((c) => zoneRefuses(z, c)).filter(Boolean);
      const ok = cols.filter((c) => !zoneRefuses(z, c));
      if (bad.length) SM.ui.toast(bad[0]);
      if (!ok.length) return;
      const refs = ok.map((c) => ({ id: c.id, name: c.name }));
      this.update((S) => {
        let list = S.zones[key].filter((r) => !refs.some((x) => x.id === r.id) || r.id === replaceId);
        const at = replaceId ? list.findIndex((r) => r.id === replaceId) : -1;
        if (at >= 0) list.splice(at, 1, ...refs);
        else if (z.max === 1) list = refs.slice(0, 1);
        else list = list.concat(refs);
        if (list.length > z.max) { list = list.slice(list.length - z.max); SM.ui.toast(`${z.label} holds at most ${z.max} columns`); }
        S.zones[key] = list;
      });
    }

    removeColumn(key, id) { this.update((S) => { S.zones[key] = S.zones[key].filter((r) => r.id !== id); }); }

    renderPalette() {
      const cols = zoneCols(this.S, this.t);
      const xc = cols.x[0] || null, yc = cols.y[0] || null;
      this.palette.replaceChildren();
      for (const E of ELEMENTS) {
        const on = this.S.elements.some((e) => e.type === E.type);
        const why = xc || yc ? elementRefuses(E.type, xc, yc) : null;
        const b = el('button', { type: 'button', class: 'sm-gb-el', 'aria-pressed': String(on), 'aria-disabled': why ? 'true' : null, 'aria-label': `${E.label}${why ? ` (${why})` : ''}`, title: why || `${E.label}: click to show it alone, shift-click to add or remove it`, dataset: { el: E.type, gbkey: `el:${E.type}` } },
          icon(E.type), el('span', { class: 'sm-gb-elname', text: E.label }));
        this.palette.append(b);
      }
    }

    wirePalette() {
      const typeOf = (ev) => { const b = ev.target.closest('.sm-gb-el'); return b ? b.dataset.el : null; };
      this.palette.addEventListener('click', (ev) => {
        const type = typeOf(ev);
        if (!type) return;
        const b = ev.target.closest('.sm-gb-el');
        if (b.getAttribute('aria-disabled') === 'true' && !this.S.elements.some((e) => e.type === type)) { SM.ui.toast(`${b.title}.`); return; }
        if (ev.shiftKey || ev.metaKey || ev.ctrlKey) this.toggleElement(type); else this.onlyElement(type);
      });
      this.palette.addEventListener('contextmenu', (ev) => {
        const type = typeOf(ev);
        if (!type) return;
        ev.preventDefault();
        const on = this.S.elements.some((e) => e.type === type);
        SM.ui.menu([{ head: ELEMENT[type].label }, { label: 'Show Alone', action: () => this.onlyElement(type) }, { label: on ? 'Remove from the Graph' : 'Add to the Graph', action: () => this.toggleElement(type) }], { x: ev.clientX, y: ev.clientY });
      });
    }

    onlyElement(type) {
      this.update((S) => {
        const had = S.elements.find((e) => e.type === type);
        S.auto = false;
        S.elements = [had || elementDefaults(type)];
      });
    }

    toggleElement(type) {
      this.update((S) => {
        S.auto = false;
        if (S.elements.some((e) => e.type === type)) S.elements = S.elements.filter((e) => e.type !== type);
        else S.elements = [...S.elements, elementDefaults(type)];
      });
    }

    renderProps() {
      const box = this.propsBox;
      box.replaceChildren(el('h4', null, 'Properties', infoSlot('p:graphbuilder:props')));
      if (!this.S.elements.length) { box.append(el('p', { class: 'sm-ob-note', text: 'No element: choose one above the graph.' })); return; }
      this.S.elements.forEach((e, idx) => {
        const def = ELEMENT[e.type];
        const rm = el('button', { type: 'button', class: 'sm-gb-rm', 'aria-label': `Remove ${def.label}`, title: `Remove ${def.label}`, text: '×', dataset: { gbkey: `rm:${e.type}` } });
        rm.addEventListener('click', () => this.toggleElement(e.type));
        const fs = el('fieldset', { class: 'sm-gb-prop', dataset: { el: e.type } }, el('legend', null, icon(e.type), el('span', { text: def.label }), rm));
        for (const p of def.props) if (!p.when || p.when(e)) fs.append(this.control(e, idx, p));
        box.append(fs);
      });
    }

    setProp(idx, key, value, { later = false } = {}) {
      const go = () => this.update((S) => { if (S.elements[idx]) S.elements[idx][key] = value; });
      if (later) { clearTimeout(this._propTimer); this._propTimer = setTimeout(go, 160); } else go();
    }

    control(e, idx, p) {
      const id = SM.util.uid('gbp');
      const key = `prop:${e.type}:${p.key}`;
      const v = e[p.key];
      let input;
      if (p.type === 'select') {
        const choices = p.dflt === 'auto' ? [['auto', 'Auto'], ...p.choices] : p.choices;
        input = el('select', { id, dataset: { gbkey: key } }, ...choices.map(([cv, l]) => el('option', { value: String(cv), text: l })));
        input.value = String(v ?? p.dflt);
        input.addEventListener('change', () => { const raw = input.value; const num = choices.find(([cv]) => String(cv) === raw); this.setProp(idx, p.key, num && typeof num[0] === 'number' ? Number(raw) : raw); });
        return el('label', { class: 'sm-gb-field', for: id }, el('span', { text: p.label }), input);
      }
      if (p.type === 'check') {
        input = el('input', { type: 'checkbox', id, dataset: { gbkey: key } });
        input.checked = !!v;
        input.addEventListener('change', () => this.setProp(idx, p.key, input.checked));
        return el('label', { class: 'sm-gb-field is-check', for: id }, input, el('span', { text: p.label }));
      }
      if (p.type === 'log') {
        const lo = Math.log10(p.min), hi = Math.log10(p.max);
        input = el('input', { type: 'range', id, min: String(lo), max: String(hi), step: '0.05', dataset: { gbkey: key }, 'aria-valuetext': fmt(v) });
        input.value = String(Math.log10(v || p.dflt));
        const out = el('output', { for: id, class: 'sm-gb-out', text: fmt(v ?? p.dflt, { sig: 3 }) });
        const num = el('input', { type: 'text', inputmode: 'decimal', size: 7, class: 'sm-gb-num', 'aria-label': `${p.label} value`, dataset: { gbkey: `${key}:n` } });
        num.value = String(v ?? p.dflt);
        input.addEventListener('input', () => { const val = +(10 ** Number(input.value)).toPrecision(3); out.textContent = fmt(val); num.value = String(val); input.setAttribute('aria-valuetext', fmt(val)); this.setProp(idx, p.key, val, { later: true }); });
        num.addEventListener('change', () => { const val = SM.table.toNumber(num.value.replace(',', '.')); if (val > 0) this.setProp(idx, p.key, clamp(val, p.min, p.max)); });
        return el('div', { class: 'sm-gb-field is-log' }, el('label', { for: id, text: p.label }), el('div', { class: 'sm-gb-logrow' }, input, num));
      }
      if (p.type === 'multi') {
        const cur = new Set(Array.isArray(v) ? v : p.dflt);
        const group = el('div', { class: 'sm-gb-multi', role: 'group', 'aria-label': p.label });
        for (const [cv, l] of p.choices) {
          const cid = SM.util.uid('gbm');
          const cb = el('input', { type: 'checkbox', id: cid, dataset: { gbkey: `${key}:${cv}` } });
          cb.checked = cur.has(cv);
          cb.addEventListener('change', () => {
            const next = p.choices.map(([k]) => k).filter((k) => (k === cv ? cb.checked : cur.has(k)));
            if (next.length > (p.max || 5)) { cb.checked = false; SM.ui.toast(`At most ${p.max || 5} statistics`); return; }
            this.setProp(idx, p.key, next.length ? next : [cv]);
          });
          group.append(el('label', { class: 'sm-gb-field is-check', for: cid }, cb, el('span', { text: l })));
        }
        return el('div', { class: 'sm-gb-field is-multi' }, el('span', { text: p.label }), group);
      }
      input = el('input', { type: 'text', inputmode: 'decimal', id, size: 6, dataset: { gbkey: key } });
      input.value = v == null ? '' : String(v);
      input.placeholder = p.dflt == null ? 'auto' : '';
      input.addEventListener('change', () => {
        const txt = input.value.trim().replace(',', '.');
        if (txt === '') { this.setProp(idx, p.key, p.dflt); return; }
        const n = SM.table.toNumber(txt);
        if (!Number.isFinite(n)) { input.value = v == null ? '' : String(v); return; }
        this.setProp(idx, p.key, clamp(n, p.min ?? -Infinity, p.max ?? Infinity));
      });
      return el('label', { class: 'sm-gb-field', for: id }, el('span', { text: p.label }), input);
    }

    /* ---- changes ---- */
    /* The builder that is on show: after a Redo this one is gone, and a
       click on its last frame goes to the new one. */
    current() { const b = BUILDERS.get(this.report); return b && b !== this && !b.dead ? b : null; }

    update(fn, { undo = true } = {}) {
      if (this.dead) { const b = this.current(); if (b) b.update(fn, { undo }); return; }
      if (undo) { this.ui.undo.push(JSON.stringify(this.S)); if (this.ui.undo.length > 60) this.ui.undo.shift(); }
      fn(this.S);
      this.S = normalize(this.S, this.t);
      this.save();
      this.renderChrome();
      this.schedule();
    }

    save() { this.ctx.set('gb', clone(this.S), null, { rerun: false }); }

    undo() {
      if (this.dead) { const b = this.current(); if (b) b.undo(); return; }
      const prev = this.ui.undo.pop();
      if (!prev) return;
      this.S = normalize(JSON.parse(prev), this.t);
      this.save();
      this.renderChrome();
      this.schedule();
    }

    startOver() { this.update((S) => { const keep = { size: S.size, alpha: S.alpha, legendPos: S.legendPos }; Object.assign(S, defaultState(), keep); }); }

    schedule() {
      this.pendingRedraw = true;
      clearTimeout(this._timer);
      this._timer = setTimeout(() => { this.pendingRedraw = false; this.redraw(); }, 30);
    }

    async idle() {
      for (let i = 0; i < 800; i++) {
        if (!this.busy && !this.pendingRedraw && !this.pendingBox) return true;
        await sleep(25);
      }
      return false;
    }

    /* ---- the graph ---- */
    width() {
      const S = this.S;
      if (S.size && S.size.w) return clamp(S.size.w, 240, 2400);
      const host = this.report.content || this.report.body;
      const full = host && host.clientWidth ? host.clientWidth - 40 : 900;
      const narrow = full < 700;
      const chrome = S.done ? 0 : (narrow ? 0 : 210 + 34 + 34 + 150 + 30);
      return clamp(Math.round(full - chrome), 280, 900);
    }

    height(nR = 1) {
      const S = this.S;
      if (S.size && S.size.h) return clamp(S.size.h, 200, 2400);
      const w = this.width();
      return clamp(Math.round(w * 0.64) + (nR > 2 ? (nR - 2) * 80 : 0), 260, 980);
    }

    async redraw() {
      if (this.dead) return;
      const seq = ++this.seq;
      this.busy++;
      const ctx = this.ctx;
      try {
        ctx.warnings = [];
        this.status.dataset.state = 'running';
        // Before the engine has loaded, what needs no Python is drawn at once
        // (points, counts); the rest follows when it is ready.
        if (SM.engine.state !== 'ready' && SM.engine.state !== 'error') {
          this.noPython = true;
          let quick;
          try { quick = await buildFigure(this); } finally { this.noPython = false; }
          if (seq !== this.seq || this.dead) return;
          this.lastFig = quick;
          this.show(quick);
          if (!quick.notes.some((n) => /Python engine has loaded/.test(n))) return;
          await SM.engine.ready().catch(() => null);
          if (seq !== this.seq || this.dead) return;
          ctx.warnings = [];
        }
        const fig = await buildFigure(this);
        if (seq !== this.seq || this.dead) return;
        this.lastFig = fig;
        this.show(fig);
        this.report.pyCode = fig.codes.slice();
      } catch (e) {
        if (seq === this.seq && !this.dead) { console.error(e); this.status.replaceChildren(ctx.error(e)); }
      } finally {
        this.busy--;
        if (seq === this.seq) this.status.dataset.state = 'done';
      }
    }

    show(fig) {
      const ctx = this.ctx;
      if (this._shown) { this._shown(); this._shown = null; }
      if (fig.empty) {
        this.discard(this.pendingBox);
        this.pendingBox = null;
        this.discard(this.plotBox);
        this.plotBox = null;
        const w = this.width(), h = this.height();
        this.plotWrap.replaceChildren(el('div', { class: 'sm-gb-empty', style: { width: `${w}px`, height: `${Math.min(h, 360)}px` } },
          el('p', { text: 'Drop columns here' }), el('p', { class: 'sm-ob-note', text: 'Drag a column from the list (or from the Columns panel) onto X or Y; by touch, hold it a moment first. Or select a column, then click a zone (the keyboard: Enter).' })));
        this.status.replaceChildren();
        return;
      }
      const S = this.S;
      const box = ctx.plot(fig.traces, fig.layout, {
        width: fig.width, height: fig.height, title: fig.title,
        config: { edits: { titleText: !!S.show.title, axisTitleText: !!fig.editAxes } },
        onDraw: (gd) => this.onDraw(gd),
      });
      link(box, fig.links, { maskColors: fig.mask });
      if (this.pendingBox) this.discard(this.pendingBox);
      if (!this.plotBox || !this.plotBox.isConnected || !this.plotBox._plot || !this.plotBox._plot.drawn) {
        this.discard(this.plotBox);
        this.plotWrap.replaceChildren(box);
        this.plotBox = box;
        this.pendingBox = null;
      } else {
        box.classList.add('is-pending');
        this.plotWrap.append(box);
        this.pendingBox = box;
        setTimeout(() => this.promote(box), 1500);
      }
      // what the graph leaves out, statsmodels' messages, and the Python
      const parts = [];
      for (const n of fig.notes) parts.push(ctx.note(n));
      for (const w of ctx.warnings) parts.push(ctx.warn(w));
      ctx.warnings = [];
      if (fig.codes.length) parts.push(ctx.code(fig.codes.join('\n\n# ----\n')));
      this.status.replaceChildren(...parts);
    }

    promote(box) {
      if (this.pendingBox !== box) return;
      const old = this.plotBox;
      this.plotBox = box;
      this.pendingBox = null;
      box.classList.remove('is-pending');
      if (old && old !== box) this.discard(old);
    }

    discard(box) {
      if (!box) return;
      const p = box._plot;
      if (p) {
        p.purge();
        const i = this.report.plots.indexOf(p);
        if (i >= 0) this.report.plots.splice(i, 1);
      }
      box.remove();
    }

    onDraw(gd) {
      if (gd === this.pendingBox) this.promote(gd);
      gd.on('plotly_relayout', (ev) => {
        if (!ev || this.dead) return;
        let changed = false;
        for (const [k, v] of Object.entries(ev)) {
          if (k === 'title.text') { this.S.title = String(v); changed = true; }
          const m = /^([xy]axis\d*)\.title\.text$/.exec(k);
          const fig = this.lastFig;
          if (m && fig && fig.axisKeys[m[1]]) { this.S.labels[fig.axisKeys[m[1]]] = String(v); changed = true; }
        }
        if (changed) { this.ui.undo.push(JSON.stringify(this.S)); this.save(); }
      });
    }

    /* ---- the red triangle ---- */
    menu() {
      const S = this.S;
      const tog = (label, get, set) => ({ label, checked: !!get(S), action: () => this.update(set) });
      return [
        tog('Show Control Panel', (s) => !s.done, (s) => { s.done = !s.done; }),
        tog('Title', (s) => s.show.title, (s) => { s.show.title = !s.show.title; }),
        tog('Legend', (s) => s.show.legend, (s) => { s.show.legend = !s.show.legend; }),
        tog('X Axis Title', (s) => s.show.xTitle, (s) => { s.show.xTitle = !s.show.xTitle; }),
        tog('Y Axis Title', (s) => s.show.yTitle, (s) => { s.show.yTitle = !s.show.yTitle; }),
        { label: 'Legend Position', submenu: () => [['right', 'Right'], ['bottom', 'Bottom'], ['inside', 'Inside']].map(([v, l]) => ({ label: l, checked: S.legendPos === v, action: () => this.update((s) => { s.legendPos = v; }) })) },
        { label: 'Set Alpha Level', submenu: () => [0.1, 0.05, 0.01].map((a) => ({ label: String(a), checked: S.alpha === a, action: () => this.update((s) => { s.alpha = a; }) })).concat([{ label: 'Other…', action: async () => { const v = await SM.ui.form({ title: 'Set Alpha Level', fields: [{ key: 'a', label: 'α (0 to 0.5)', type: 'number', value: S.alpha, help: 'The α of every interval in the graph: the bands of Line of Fit (of the fit and of prediction), the smoother\'s Confidence of Fit, the Confidence Interval error bars and the Box Plot\'s Confidence Diamond are drawn at 1 − α, so 0.05 (the default) gives 95% and 0.01 gives 99%. A value outside 0 to 0.5 is ignored.' }] }); if (v && v.a > 0 && v.a < 0.5) this.update((s) => { s.alpha = v.a; }); } }]) },
        { separator: true },
        { label: 'Edit Title and Axis Titles…', action: () => this.editTitles() },
        { label: 'Graph Size…', action: () => this.sizeDialog() },
        { separator: true },
        { label: 'Undo', disabled: !this.ui.undo.length, action: () => this.undo() },
        { label: 'Start Over', action: () => this.startOver() },
      ];
    }

    async editTitles() {
      const S = this.S;
      const cols = zoneCols(S, this.t);
      const fields = [{ key: 'title', label: 'Title (empty: automatic)', value: S.title ?? '', full: true, help: 'The title over the graph. Empty gives the automatic one, the Y columns vs. the X columns; Title in the red triangle hides it.' }];
      const fx = cols.x[0], fy = cols.y[0];
      if (fx) fields.push({ key: 'x', label: `X axis title (${fx.name})`, value: S.labels[`x:${fx.id}`] ?? '', full: true, helpLabel: 'X axis title', help: 'The title under the X axis where the first X column is; empty: the column\'s name.' });
      if (fy) fields.push({ key: 'y', label: `Y axis title (${fy.name})`, value: S.labels[`y:${fy.id}`] ?? '', full: true, helpLabel: 'Y axis title', help: 'The title beside the Y axis where the first Y column is; empty: the column\'s name.' });
      const v = await SM.ui.form({ title: 'Edit Title and Axis Titles', fields });
      if (!v) return;
      this.update((s) => {
        s.title = v.title.trim() === '' ? null : v.title;
        if (fx) { if (v.x.trim() === '') delete s.labels[`x:${fx.id}`]; else s.labels[`x:${fx.id}`] = v.x; }
        if (fy) { if (v.y.trim() === '') delete s.labels[`y:${fy.id}`]; else s.labels[`y:${fy.id}`] = v.y; }
      });
    }

    async sizeDialog() {
      const w = this.width(), h = this.height(this.lastFig && this.lastFig.layout ? 1 : 1);
      const v = await SM.ui.form({ title: 'Graph Size', lead: 'In pixels; empty fits the graph to the window.', fields: [{ key: 'w', label: 'Width', type: 'number', value: this.S.size ? this.S.size.w : null, placeholder: String(w), help: 'The graph\'s width in pixels, 240 to 2400 (the grey number is the width now). Empty fits the graph to the window and follows it when it changes.' }, { key: 'h', label: 'Height', type: 'number', value: this.S.size ? this.S.size.h : null, placeholder: String(h), help: 'The height in pixels, 200 to 2400. Empty: about two thirds of the width, more for more than two rows of panels.' }] });
      if (!v) return;
      this.update((s) => { s.size = v.w || v.h ? { w: v.w > 0 ? v.w : null, h: v.h > 0 ? v.h : null } : null; });
    }

    /* For the tests and the console: a handle on the builder. */
    api() {
      const self = this;
      const id = (name) => { const c = self.t.col(name); if (!c) throw new Error(`no column ${name}`); return c.id; };
      return {
        state: () => clone(self.S),
        add(zone, names, opts) { self.addColumns(zone, (Array.isArray(names) ? names : [names]).map(id), opts); return self.idle(); },
        remove(zone, name) { self.removeColumn(zone, id(name)); return self.idle(); },
        elements(types) { self.update((S) => { S.auto = false; S.elements = types.map((t) => S.elements.find((e) => e.type === t) || elementDefaults(t)); }); return self.idle(); },
        prop(type, key, value) { self.update((S) => { const e = S.elements.find((x) => x.type === type); if (e) e[key] = value; }); return self.idle(); },
        update(fn) { self.update(fn); return self.idle(); },
        undo() { self.undo(); return self.idle(); },
        idle: () => self.idle(),
        plot: () => (self.plotBox ? self.plotBox._plot : null),
        figure: () => self.lastFig,
        notes: () => (self.lastFig ? self.lastFig.notes.slice() : []),
      };
    }
  }

  /* ---- Graph Builder: what its (i) says -------------------------------------------------------
     Both topics are functions: they explain the properties of the elements in
     the graph on show (the report of the active tab) as its Properties panel
     shows them, those shown now first and then those that come with another
     choice; with no builder on show, every element's. */
  function shownBuilder() {
    const tab = SM.app && SM.app.activeTab;
    const b = tab && tab.report ? BUILDERS.get(tab.report) : null;
    return b && !b.dead ? b : null;
  }

  function propChoices(e) {
    const def = ELEMENT[e.type];
    const on = def.props.filter((p) => !p.when || p.when(e));
    const off = def.props.filter((p) => !on.includes(p));
    return [...on.map((p) => [p.label, p.help]), ...off.map((p) => [p.label, `Shown ${p.shows}. ${p.help}`])];
  }

  function propSections(b, prefix) {
    const els = b ? b.S.elements.filter((e) => ELEMENT[e.type]) : ELEMENTS.map((d) => elementDefaults(d.type));
    return els.map((e) => ({ heading: `${prefix}${ELEMENT[e.type].label}`, text: ELEMENT[e.type].about, choices: propChoices(e) }));
  }

  const GB_ZONES = [
    ['X, Y', 'The axes, up to 4 columns on X and 6 on Y. With a continuous column on one axis and a categorical one on the other, the continuous one is the variable the elements summarize at each level. Several columns in a zone stand side by side, a panel each, or merge on one axis (right click the zone: Merge Columns); only continuous columns merge. The zone\'s menu also has Log Scale, for a continuous column that is not a date.'],
    ['Group X, Group Y', 'Small multiples: a column of panels (Group X) or a row of them (Group Y) for each level, sharing their axes. A continuous column with more than 10 distinct values is cut into five bins of about equal counts.'],
    ['Wrap', 'A panel for each level, wrapped into a grid of about as many columns as rows. While Wrap has a column, Group X and Group Y wait.'],
    ['Overlay', 'Groups within each panel, each with its colour and legend entry and its own smoother, fit, bars, boxes or beans (up to 60 groups; a continuous column with many values is cut into five bins). Rows with no value are left out of the groups.'],
    ['Color', 'Colours the points: a blue-to-red gradient over a continuous column, with a colour bar (a Heatmap then shows its mean in each cell); a colour for each level of a categorical one, which also groups the elements as Overlay does. It wins over the rows\' own colours.'],
    ['Size', 'A continuous column: the larger its value, the larger the point, from 4 pixels across at the column\'s smallest value to 22 at its largest (a missing value gives a small point).'],
    ['Freq', 'A numeric column of counts: a row counts that many times in every statistic, bin and fit; rows with a missing, zero or negative count are left out.'],
  ];
  const GB_BUILDER = [
    ['Select Columns', 'The table\'s columns; Filter narrows the list by name. Drag a column onto a zone (from here or from the page\'s Columns panel), or click it and then click a zone. Double-click puts it where it fits: a continuous column on Y (then X), a categorical one on X (then Overlay, Group X, Group Y). Right click it, or press Enter, for the list of zones.'],
    ['A zone and its columns', 'Click an empty zone to pick a column for it from a list. Click a column in a zone for Remove, Move to and Replace with; drop another column on it to replace it. Right click a zone (or use the context menu key) for Merge Columns or Side by Side, Log Scale, Add Column, Swap with and Remove All.'],
    ['Elements', 'The palette above the graph. Click an element to draw it alone; shift-click (or ctrl/⌘-click) to add it to the others or take it away; right click for the same as a menu. A dimmed element cannot draw the columns in the zones and says why. Until you pick one, the builder chooses as JMP does: Points and Smoother for two continuous columns, Bar for a categorical column alone, Points otherwise.'],
    ['Properties', 'Under the columns, a box for each element in the graph with its settings (explained below); × takes the element away. A change redraws the graph at once.'],
    ['Undo', 'Steps back through the changes to the zones, the elements and their properties, up to 60 of them.'],
    ['Start Over', 'Empties the zones and takes the elements away; the graph size, α and the legend position stay.'],
    ['Done', 'Hides the columns, the palette, the zones and the properties and leaves the graph; Show Control Panel above the graph (or in the red triangle) brings them back.'],
    ['Titles', 'With one panel, click the title or an axis title on the graph and type your own; Edit Title and Axis Titles… in the red triangle does it for any graph.'],
  ];
  const GB_TRIANGLE = [
    ['Show Control Panel', 'Shows or hides the columns, the palette, the zones and the properties, as Done does.'],
    ['Title, Legend, X Axis Title, Y Axis Title', 'Show or hide those parts of the graph.'],
    ['Legend Position', 'Right (the default; under the graph when it is narrow), Bottom, or Inside the plot\'s top right corner.'],
    ['Set Alpha Level', 'α for every interval in the graph: the bands of Line of Fit and of the smoother, the Confidence Interval error bars and the Confidence Diamond are at 1 − α (0.05, the default, gives 95%). Other… takes any value between 0 and 0.5.'],
    ['Edit Title and Axis Titles…', 'Your own title, and titles for the first X and Y columns; an empty one is automatic again.'],
    ['Graph Size…', 'A fixed width and height in pixels; empty fits the graph to the window.'],
    ['Undo, Start Over', 'As the buttons above the builder.'],
  ];
  const GB_LEAD = 'Drag columns onto the zones around the graph and choose elements from the palette; the graph redraws at once. Points, bars, boxes, bins, cells and slices are linked to their rows: click or drag to select, and the selection shows in every graph of the table.';

  function gbTopic() {
    const b = shownBuilder();
    const inGraph = new Set(b ? b.S.elements.map((e) => e.type) : []);
    const props = propSections(b, 'Properties: ');
    return {
      kicker: 'Graph', title: 'Graph Builder', lead: GB_LEAD,
      sections: [
        { heading: 'Zones', choices: GB_ZONES },
        { heading: 'The builder', choices: GB_BUILDER },
        { heading: 'Elements', text: b ? 'The elements in the graph are marked; their properties follow.' : 'What each element draws; the properties of every element follow.', choices: ELEMENTS.map((d) => [d.label, d.about, inGraph.has(d.type)]) },
        ...(props.length ? props : [{ heading: 'Properties', text: 'No element in the graph yet: click one in the palette above the graph, and its settings are explained here.' }]),
        { heading: 'The red triangle', choices: GB_TRIANGLE },
        { heading: 'Touch and keyboard', list: ['Select a column (tap it, or Space), then tap a zone: the column goes there. Tap a column in a zone for Remove, Move to and Replace with.', 'On a column in the list, Enter opens the list of zones.', 'On a zone, Enter adds a column, the context menu key (or Shift+F10) opens its menu, Delete removes the focused column.'] },
        { heading: 'Differences from JMP', list: [
          'Smoother: the same penalised least squares as JMP\'s cubic spline (λ on standardized X), from scipy; JMP\'s option to scale λ by the count is not applied, and its other methods (P-Spline, Savitzky-Golay, moving averages) are not here. Local Kernel is statsmodels\' lowess.',
          'The smoother\'s Confidence of Fit is a bootstrap band (100 resamples of the rows, fewer for many rows): the fit plus or minus z(1 − α/2) times their spread.',
          'Line of Fit\'s Robust Cauchy is statsmodels\' RLM with Cauchy weights, c = 2.3849; Time Series fits are not here.',
          'Ellipse: the contour of the fitted bivariate normal (radius² the χ²(2) quantile of the coverage).',
          'Contour: highest-density regions of a Gaussian kernel density with Scott\'s bandwidth; Bagplot and HDR types are not here.',
          'Bean is not in JMP. It follows statsmodels\' beanplot (Kampstra 2008): every violin is scaled to the same width, so their areas do not compare the groups\' sizes; the overall mean line is Kampstra\'s, not drawn by statsmodels.',
          'Excluded rows are left out of the graph; hidden rows are not drawn but count in the statistics. Map shapes, Page, Interval, Shape and the Local Data Filter\'s own column switcher are not in this builder.',
        ] },
      ],
      more: { label: 'Graph Builder', id: 'help-p-graphbuilder' },
    };
  }

  function gbPropsTopic() {
    const b = shownBuilder();
    const props = b ? propSections(b, '') : [];
    return {
      kicker: 'Graph Builder', title: 'Properties',
      lead: 'The settings of each element in the graph, under its name; a change redraws the graph at once, and × beside the name takes the element away. Some settings come with another choice (an Error Interval with a Summary Statistic, Lambda with the Spline method); they are listed after the others.',
      sections: props.length ? props : [{ text: 'No element in the graph yet: click one in the palette above the graph (shift-click adds another), and its settings show in the Properties panel and here.' }],
      more: { label: 'Graph Builder', id: 'help-p-graphbuilder' },
    };
  }

  SM.platforms.register({
    id: 'graphbuilder', label: 'Graph Builder', menu: 'Graph', order: 10, launch: null, info: 'p:graphbuilder',
    topics: { 'p:graphbuilder': gbTopic, 'p:graphbuilder:props': gbPropsTopic },
    about: 'Drag-and-drop graphs: columns onto the X, Y, Group X, Group Y, Wrap, Overlay, Color, Size and Freq zones, elements from a palette (Points, Smoother, Line of Fit, Ellipse, Contour, Line, Bar, Area, Box Plot, Bean, Histogram, Heatmap, Mosaic, Caption Box, Pie), each with its properties. Every mark is linked to its rows; Done leaves the graph alone.',
    uses: ['scipy.interpolate.make_smoothing_spline', 'statsmodels.nonparametric.smoothers_lowess.lowess', 'statsmodels.regression.linear_model.OLS', 'statsmodels.robust.robust_linear_model.RLM', 'scipy.stats.gaussian_kde', 'statsmodels.graphics.boxplots (beanplot\'s violins)', 'scipy.stats.chi2, chi2_contingency', 'numpy.quantile (weibull)'],
    title: () => 'Graph Builder',
    triangle(ctx) { const b = BUILDERS.get(ctx.report); return b && !b.dead ? b.menu() : []; },
    /* The builder of a report (its handle, as the tests use it). */
    builder: (report) => { const b = BUILDERS.get(report); return b ? b.root._gb : null; },
    async render(ctx) {
      if (!ctx.table) throw new Error('Graph Builder needs a table');
      // Graph Builder follows the table as it changes, as JMP's does.
      if (ctx.spec.autoRecalc === undefined) ctx.spec.autoRecalc = true;
      const b = new Builder(ctx);
      BUILDERS.set(ctx.report, b);
      ctx.container.append(b.root);
      // The report is done when the first figure is on show; before the engine
      // has loaded, that is the part that needs no Python.
      await Promise.race([b.redraw(), b.shown]);
      ctx.warnings = [];
    },
  });

  /* ==========================================================================
     THE OTHER GRAPHS
     ========================================================================== */

  function availWidth(ctx, dflt = 760) {
    const host = ctx.report.content || ctx.report.body;
    const w = host && host.clientWidth ? host.clientWidth - 70 : dflt;
    return clamp(w, 280, 1200);
  }

  /* The colours a column gives its rows: the palette by level, or the
     blue-grey-red gradient over its range. */
  function colorer(t, c, rows) {
    const grey = dark() ? '#777' : '#aaa';
    if (!c) return null;
    if (isCat(c)) {
      const lv = levelsAmong(t, c, rows);
      const m = new Map(lv.map((v, i) => [v, i]));
      return { cat: true, col: c, labels: lv.map((v) => cellText(c, v)), index: (r) => (m.has(c.values[r]) ? m.get(c.values[r]) : -1), color: (r) => { const k = m.get(c.values[r]); return k == null ? grey : PALETTE[k % PALETTE.length]; } };
    }
    const ex = extent(rows.map((r) => c.values[r]));
    return { cat: false, col: c, range: ex, index: () => 0, color: (r) => { const v = c.values[r]; if (!Number.isFinite(v) || !ex) return grey; return SM.util.ramp(ex[1] > ex[0] ? (v - ex[0]) / (ex[1] - ex[0]) : 0.5); } };
  }

  /* A legend for a colouring column, as traces: one per level, or a colour bar. */
  function legendTraces(C, { xaxis = 'x', yaxis = 'y', type = 'scatter' } = {}) {
    if (!C) return [];
    if (C.cat) return C.labels.map((lab, i) => ({ type, mode: 'markers', x: [null], y: [null], xaxis, yaxis, name: esc(lab), marker: { color: PALETTE[i % PALETTE.length], size: 8 }, showlegend: true, hoverinfo: 'skip', legendgroup: `g${i}` }));
    if (!C.range) return [];
    return [{ type: 'scatter', mode: 'markers', x: [null], y: [null], xaxis, yaxis, hoverinfo: 'skip', showlegend: false, marker: { color: C.range, cmin: C.range[0], cmax: C.range[1], colorscale: RAMP, showscale: true, colorbar: { title: { text: esc(C.col.name), side: 'right' }, thickness: 12, len: 0.7, outlinewidth: 0 } } }];
  }

  /* A small HTML legend of levels (for 3-D graphs, whose legends Plotly draws poorly). */
  function htmlLegend(C) {
    if (!C) return null;
    if (!C.cat) return el('p', { class: 'sm-ob-note', text: `Colours: ${C.col.name}, blue (low) to red (high)${C.range ? `, ${fmt(C.range[0])} to ${fmt(C.range[1])}` : ''}.` });
    return el('div', { class: 'sm-graph-pick', role: 'list', 'aria-label': `${C.col.name} colours` }, el('strong', { text: C.col.name }),
      ...C.labels.map((lab, i) => el('span', { role: 'listitem', class: 'sm-inline' }, el('span', { class: 'sm-swatch', style: { display: 'inline-block', width: '10px', height: '10px', borderRadius: '50%', background: PALETTE[i % PALETTE.length] } }), lab)));
  }

  function scene3d(names) {
    const tc = SM.util.themeColors();
    const ax = (n) => ({ title: { text: esc(n) }, gridcolor: tc.grid, zerolinecolor: tc.grid, linecolor: tc.muted, color: tc.text, showbackground: false, backgroundcolor: 'rgba(0,0,0,0)' });
    return { xaxis: ax(names[0]), yaxis: ax(names[1]), zaxis: ax(names[2]), bgcolor: 'rgba(0,0,0,0)', aspectmode: 'cube' };
  }

  const SYM3D = ['circle', 'square', 'diamond', 'cross', 'x', 'circle-open', 'square-open', 'diamond-open'];

  /* ---- Scatterplot Matrix ---------------------------------------------------------------- */
  SM.platforms.register({
    id: 'scattermatrix', label: 'Scatterplot Matrix', menu: 'Graph', order: 20, info: 'p:scattermatrix',
    topics: {
      'p:scattermatrix': {
        kicker: 'Graph', title: 'Scatterplot Matrix',
        lead: 'A scatterplot for every pair of columns, linked: drag a rectangle in one cell and the rows light up in all of them.',
        sections: [
          { heading: 'Roles', choices: [['Y, Columns', 'The columns; with no X, each pair once (lower or upper triangle) or twice (square).'], ['X', 'Optional: the matrix is then the Y columns by the X columns.'], ['Group', 'Colours the points, and gives each level its own ellipse and fit line.'], ['By', 'A matrix for each level.']] },
          { heading: 'The red triangle', choices: [
            ['Show Points', 'The points of every pair, linked to the rows: drag a rectangle in one cell and the rows light up in all of them. On by default.'],
            ['Fit Line', 'A least squares line (statsmodels OLS) in each cell, with its 95% confidence band; one for each level of Group.'],
            ['Density Ellipses', 'The ellipse of the bivariate normal with the pair\'s means and covariance that holds the Ellipses Coverage; one for each level of Group.'],
            ['Shaded Ellipses', 'Fills the density ellipses.'],
            ['Ellipses Coverage', 'The share of the fitted normal inside each ellipse: 99%, 95% (the default), 90% or 50%.'],
            ['Nonpar Density', 'Kernel density contours that hold 25, 50, 75 and 100% of the points (scipy\'s gaussian_kde, Scott\'s bandwidth), whatever their shape.'],
            ['Histograms', 'A histogram of each column on the diagonal, its bars linked to their rows.'],
            ['Matrix Format', 'Lower or upper triangle, or the square of every pair twice; not with X columns.'],
          ] },
        ],
        more: { label: 'Scatterplot Matrix', id: 'help-p-scattermatrix' },
      },
    },
    about: 'A scatterplot of every pair of columns in one linked grid, with density ellipses, fit lines, nonparametric density contours and histograms on the diagonal; lower, upper or square, or Y by X.',
    uses: ['statsmodels.regression.linear_model.OLS', 'scipy.stats.chi2 (density ellipses)', 'scipy.stats.gaussian_kde'],
    launch: {
      lead: 'Choose two or more continuous columns. Each pair gets a scatterplot; with X columns as well the matrix is Y by X.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 1, numeric: true, types: ['continuous'], hint: 'required: continuous', help: 'The continuous columns to plot against one another. Without X, every pair of them, in the shape Matrix Format says, with each column\'s name on the diagonal; a row with a missing value leaves only the pairs that need it.' },
        { key: 'x', label: 'X', numeric: true, types: ['continuous'], hint: 'optional: Y by X', help: 'Continuous columns for the matrix\'s columns: the matrix is then the Y columns (down the side) by the X columns (along the bottom), every cell a pair, and Matrix Format does not apply.' },
        { key: 'group', label: 'Group', max: 1, types: ['ordinal', 'nominal'], hint: 'optional categorical', help: 'Colours the points by level, with a legend; the fit lines, density ellipses and density contours are then drawn for each level.' },
        { key: 'by', label: 'By', hint: 'optional', help: 'A separate matrix for each level of the By columns (each combination of levels with several).' },
      ],
      options: [{ key: 'format', label: 'Matrix Format', type: 'select', value: 'lower', choices: [['lower', 'Lower Triangular'], ['upper', 'Upper Triangular'], ['square', 'Square']], help: '**Lower Triangular** (the default) and **Upper Triangular** show each pair once, below or above the diagonal of names; **Square** shows each pair twice, mirrored. Only without X columns; the red triangle changes it later.' }],
      validate: (s) => ((s.roles.y || []).length + (s.roles.x || []).length < 2 ? 'Choose at least two columns (Y, or Y and X)' : null),
    },
    title: () => 'Scatterplot Matrix',
    triangle(ctx) {
      const cov = ctx.opt('coverage', 0.95);
      const fmtM = ctx.opt('format', 'lower');
      return [
        ctx.check('Show Points', 'points', null, true),
        ctx.check('Fit Line', 'fit', null, false),
        ctx.check('Density Ellipses', 'ellipses', null, false),
        ctx.check('Shaded Ellipses', 'shaded', null, false),
        { label: 'Ellipses Coverage', submenu: () => [0.99, 0.95, 0.9, 0.5].map((c) => ({ label: `${c * 100}%`, checked: cov === c, action: () => ctx.set('coverage', c) })) },
        ctx.check('Nonpar Density', 'nonpar', null, false),
        ctx.check('Histograms', 'hist', null, false),
        { label: 'Matrix Format', disabled: ctx.roles('x').length > 0, submenu: () => [['lower', 'Lower Triangular'], ['upper', 'Upper Triangular'], ['square', 'Square']].map(([v, l]) => ({ label: l, checked: fmtM === v, action: () => ctx.set('format', v) })) },
      ];
    },
    async render(ctx) {
      const t = ctx.table;
      const ys = ctx.roles('y'), xs = ctx.roles('x');
      const rect = xs.length > 0;
      const R = ys, Cc = rect ? xs : ys;
      const k = R.length, m = Cc.length;
      const fmtM = rect ? 'square' : ctx.opt('format', 'lower');
      const G = colorer(t, ctx.role('group'), ctx.rows);
      const showPts = ctx.opt('points', true), fitOn = ctx.opt('fit', false), ellOn = ctx.opt('ellipses', false), npOn = ctx.opt('nonpar', false), histOn = ctx.opt('hist', false);
      const cells = [];
      for (let i = 0; i < k; i++) for (let j = 0; j < m; j++) {
        const diag = !rect && i === j;
        if (!rect && !diag && ((fmtM === 'lower' && j > i) || (fmtM === 'upper' && j < i))) continue;
        cells.push({ i, j, diag });
      }
      const cs = clamp(Math.floor((availWidth(ctx) - 110 - (G ? 110 : 0)) / m), 70, 170);
      const W = m * cs + 90 + (G ? 110 : 0), H = k * cs + 70;
      const layout = { margin: { l: 64, r: G ? 120 : 12, t: 10, b: 56 }, showlegend: !!G, barmode: 'overlay', annotations: [], legend: G ? { title: { text: esc(G.col.name) }, x: 1.02, y: 1 } : undefined };
      const traces = [], links = [];
      const gap = 0.012;
      const colAxis = new Map(), rowAxis = new Map();
      // Tick labels on the outer edges: left and bottom where a scatter cell
      // is there, else right and top (as JMP's square and upper matrices).
      const at = new Map(cells.map((c) => [`${c.i}|${c.j}`, c]));
      const plain = (i, j) => { const c = at.get(`${i}|${j}`); return c && !c.diag ? c : null; };
      const yTicks = new Map(), xTicks = new Map();
      for (let i = 0; i < k; i++) { const c = plain(i, 0) || plain(i, m - 1); if (c) yTicks.set(`${c.i}|${c.j}`, c.j === 0 ? 'left' : 'right'); }
      for (let j = 0; j < m; j++) { const c = plain(k - 1, j) || plain(0, j); if (c) xTicks.set(`${c.i}|${c.j}`, c.i === k - 1 ? 'bottom' : 'top'); }
      if (!rect && fmtM !== 'lower') { layout.margin.t = 56; layout.margin.r = (G ? 120 : 12) + 50; if (layout.legend) layout.legend.x = 1.14; }
      const gl = webgl() && ctx.rows.length * cells.length > GL_POINTS;
      const pairs = [];
      cells.forEach((c, idx) => {
        const xa = idx === 0 ? 'x' : `x${idx + 1}`, ya = idx === 0 ? 'y' : `y${idx + 1}`;
        c.xa = xa; c.ya = ya;
        const kx = idx === 0 ? 'xaxis' : `xaxis${idx + 1}`, ky = idx === 0 ? 'yaxis' : `yaxis${idx + 1}`;
        const ax = { domain: [c.j / m + gap, (c.j + 1) / m - gap], anchor: ya, zeroline: false, showticklabels: false, ticks: '' };
        const ay = { domain: [1 - (c.i + 1) / k + gap, 1 - c.i / k - gap], anchor: xa, zeroline: false, showticklabels: false, ticks: '' };
        if (colAxis.has(c.j)) ax.matches = colAxis.get(c.j); else colAxis.set(c.j, xa);
        if (!c.diag) { if (rowAxis.has(c.i)) ay.matches = rowAxis.get(c.i); else rowAxis.set(c.i, ya); }
        const xs0 = xTicks.get(`${c.i}|${c.j}`), ys0 = yTicks.get(`${c.i}|${c.j}`);
        if (xs0) { ax.showticklabels = true; ax.ticks = 'outside'; ax.side = xs0; ax.title = { text: esc(Cc[c.j].name), standoff: 4 }; }
        if (ys0) { ay.showticklabels = true; ay.ticks = 'outside'; ay.side = ys0; ay.title = { text: esc(R[c.i].name), standoff: 4 }; }
        ax.showline = true; ay.showline = true; ax.mirror = true; ay.mirror = true;
        layout[kx] = ax; layout[ky] = ay;
        const xc = Cc[c.j], yc = R[c.i];
        if (c.diag) {
          if (!histOn) { ay.showgrid = false; ax.showgrid = false; }
          // In paper coordinates: a cell without a trace has no subplot to refer to.
          layout.annotations.push({ text: `<b>${esc(yc.name)}</b>`, xref: 'paper', yref: 'paper', x: (ax.domain[0] + ax.domain[1]) / 2, y: histOn ? ay.domain[1] - 0.01 : (ay.domain[0] + ay.domain[1]) / 2, xanchor: 'center', yanchor: histOn ? 'top' : 'middle', showarrow: false, font: { size: 11 }, bgcolor: histOn ? rgba(SM.util.themeColors().surface, 0.8) : undefined });
          if (histOn) {
            const vals = [], rws = [];
            for (const r of ctx.rows) { const v = xc.values[r]; if (Number.isFinite(v)) { vals.push(v); rws.push(r); } }
            if (vals.length) {
              const b = SM.report.niceBins(vals);
              const nb = Math.max(1, Math.round((b.end - b.start) / b.size));
              const cnt = new Array(nb).fill(0), mem = Array.from({ length: nb }, () => []);
              vals.forEach((v, q) => { const jj = clamp(Math.floor((v - b.start) / b.size + 1e-9), 0, nb - 1); cnt[jj]++; mem[jj].push(rws[q]); });
              const tr = { type: 'bar', x: cnt.map((_, jj) => b.start + (jj + 0.5) * b.size), y: cnt, width: cnt.map(() => b.size), xaxis: xa, yaxis: ya, marker: { color: barColor(), line: { width: 0.4, color: SM.util.themeColors().surface } }, hovertemplate: `${esc(xc.name)}: %{x}<br>Count: %{y}<extra></extra>`, showlegend: false };
              const ti = traces.push(tr) - 1;
              const oi = traces.push(overlayBar(tr)) - 1;
              links.push({ trace: ti, overlay: oi, kind: 'bar', rows: mem, len: cnt, horiz: false });
              ay.rangemode = 'tozero';
            }
          }
          return;
        }
        const rows = ctx.rows.filter((r) => Number.isFinite(xc.values[r]) && Number.isFinite(yc.values[r]));
        pairs.push({ c, xc, yc, rows });
        if (showPts && rows.length) {
          traces.push({ type: gl ? 'scattergl' : 'scatter', mode: 'markers', x: rows.map((r) => xc.values[r]), y: rows.map((r) => yc.values[r]), rows, xaxis: xa, yaxis: ya,
            marker: { size: rows.length > 1500 ? 3 : 4.5, color: G ? rows.map((r) => G.color(r)) : pointColor(), opacity: 0.85 },
            hovertext: rows.map((r) => rowHover(t, r, [xc, yc, G ? G.col : null])), hovertemplate: '%{hovertext}<extra></extra>', showlegend: false });
        }
      });
      // the statistics of each pair, per group
      const codeOf = (r) => (G ? G.index(r) : 0);
      const kG = G ? G.labels.length : 1;
      const lineCol = (g) => (G ? PALETTE[g % PALETTE.length] : inkColor());
      const codes = [];
      for (const p of pairs) {
        const rows = p.rows.filter((r) => codeOf(r) >= 0);
        const payload = { x: p.xc.name, y: p.yc.name, rows, codes: rows.map(codeOf), k: kG, by: G ? [G.col.name] : [] };
        if (ellOn) {
          const res = await ctx.call('graph.ellipse', { ...payload, coverage: ctx.opt('coverage', 0.95) });
          if (!codes.includes(res.code)) codes.push(res.code);
          res.ellipses.forEach((e, g) => { if (!e.error) traces.push({ type: gl ? 'scattergl' : 'scatter', mode: 'lines', x: e.x, y: e.y, xaxis: p.c.xa, yaxis: p.c.ya, line: { color: lineCol(g), width: 1.3 }, fill: ctx.opt('shaded', false) ? 'toself' : 'none', fillcolor: rgba(lineCol(g), 0.12), hovertemplate: `r = ${fmt(e.r, { sig: 4 })}<extra></extra>`, showlegend: false }); });
        }
        if (fitOn) {
          const res = await ctx.call('graph.fit', { ...payload, degree: 1, n_grid: 40 });
          if (!codes.includes(res.code)) codes.push(res.code);
          res.fits.forEach((f, g) => {
            if (f.error) return;
            traces.push({ type: gl ? 'scattergl' : 'scatter', mode: 'lines', x: [...f.x, ...f.x.slice().reverse()], y: [...f.fit_upper, ...f.fit_lower.slice().reverse()], fill: 'toself', fillcolor: rgba(lineCol(g), 0.14), line: { width: 0 }, xaxis: p.c.xa, yaxis: p.c.ya, hoverinfo: 'skip', showlegend: false });
            traces.push({ type: gl ? 'scattergl' : 'scatter', mode: 'lines', x: f.x, y: f.y, xaxis: p.c.xa, yaxis: p.c.ya, line: { color: lineCol(g), width: 1.6 }, hovertemplate: `${esc(p.yc.name)} = ${fmt(f.coef[0], { sig: 4 })} + ${fmt(f.coef[1], { sig: 4 })}·${esc(p.xc.name)}<br>R² ${fmt(f.r2, { sig: 3 })}<extra></extra>`, showlegend: false });
          });
        }
        if (npOn) {
          const res = await ctx.call('graph.density', { ...payload, grid: 48 });
          if (!codes.includes(res.code)) codes.push(res.code);
          res.densities.forEach((d, g) => {
            if (d.error) return;
            traces.push({ type: 'contour', x: d.x, y: d.y, z: d.z.map((row) => row.map((v) => (v == null ? null : 1 - v))), xaxis: p.c.xa, yaxis: p.c.ya, autocontour: false, contours: { start: 0, end: 0.75 + 1e-9, size: 0.25, coloring: 'lines' }, colorscale: [[0, lineCol(g)], [1, lineCol(g)]], showscale: false, line: { width: 1 }, hoverinfo: 'skip', showlegend: false });
          });
        }
      }
      traces.push(...legendTraces(G, { type: gl ? 'scattergl' : 'scatter' }));
      const box = ctx.plot(traces, layout, { width: W, height: H, title: 'Scatterplot Matrix' });
      link(box, links);
      ctx.container.append(el('div', { class: 'sm-graph-wide' }, box));
      if (ctx.rows.length && cells.every((c) => c.diag)) ctx.container.append(ctx.note('Choose two or more columns for pairs.'));
      if (codes.length) ctx.container.append(ctx.code(codes.join('\n\n# ----\n')));
    },
  });

  /* ---- Scatterplot 3D ------------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'scatter3d', label: 'Scatterplot 3D', menu: 'Graph', order: 30, info: 'p:scatter3d',
    topics: {
      'p:scatter3d': {
        kicker: 'Graph', title: 'Scatterplot 3D',
        lead: 'Three columns as a cloud of points to turn with the mouse (drag to rotate; to zoom, pick Zoom in the toolbar above the graph and drag). The menus above the graph choose which of the Y columns are on the axes.',
        sections: [
          { heading: 'In the report', choices: [
            ['X Axis, Y Axis, Z Axis', 'The Y column on each axis. Choosing a column that is on another axis swaps the two, so the three axes always show three different columns.'],
            ['The graph', 'Drag to turn it and click a point to select its row. The toolbar above it zooms (pick Zoom, then drag up or down), pans, resets the view and saves a picture; the mouse wheel scrolls the page, not the graph.'],
            ['Drop Lines (red triangle)', 'A line from each point down to the lowest Z, which shows where the point lies over the X–Y plane (for up to 3000 rows).'],
          ] },
          { heading: 'Linking', text: 'A click on a point selects its row; selected rows are drawn larger in orange, and the rows\' colours, markers, labels and hidden states apply. Coloring colours the points by a column instead.' },
          { heading: 'WebGL', text: 'The graph is drawn with WebGL; a browser with WebGL turned off shows a notice instead.' },
        ],
        more: { label: 'Scatterplot 3D', id: 'help-p-scatter3d' },
      },
    },
    about: 'Three continuous columns as a rotating point cloud; menus choose the axes among the Y columns; linked point by point.',
    uses: ['plotly scatter3d (drawing only)'],
    launch: {
      lead: 'Choose three or more continuous columns; the first three go on the axes, and the menus in the report change them.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 3, numeric: true, types: ['continuous'], hint: 'required: three or more', help: 'Three or more continuous columns: the first three go on the X, Y and Z axes, and the menus above the graph put any of them on an axis. A row is drawn when it has all three values.' },
        { key: 'color', label: 'Coloring', max: 1, hint: 'optional', help: 'Colours the points: a colour for each level of a categorical column (listed under the graph), a blue-to-red gradient over a continuous one. It takes the place of the rows\' own colours.' },
        { key: 'by', label: 'By', hint: 'optional', help: 'A separate graph for each level of the By columns.' },
      ],
    },
    title: () => 'Scatterplot 3D',
    triangle(ctx) { return [ctx.check('Drop Lines', 'drop', null, false)]; },
    async render(ctx) {
      const t = ctx.table;
      const ys = ctx.roles('y');
      let ax = ctx.opt('axes', [0, 1, 2]).map((i) => clamp(i | 0, 0, ys.length - 1));
      if (new Set(ax).size < 3) ax = [0, 1, 2];
      const cols = ax.map((i) => ys[i]);
      const pick = el('div', { class: 'sm-graph-pick' });
      ['X', 'Y', 'Z'].forEach((name, a) => {
        const id = SM.util.uid('s3');
        const s = el('select', { id }, ...ys.map((c, i) => el('option', { value: String(i), text: c.name })));
        s.value = String(ax[a]);
        s.addEventListener('change', () => { const next = ax.slice(); const v = Number(s.value); const other = next.indexOf(v); if (other >= 0 && other !== a) next[other] = next[a]; next[a] = v; ctx.set('axes', next); });
        pick.append(el('label', { for: id }, `${name} Axis`, s));
      });
      pick.append(infoSlot('p:scatter3d'));
      const rows = ctx.rows.filter((r) => cols.every((c) => Number.isFinite(c.values[r])));
      const C = colorer(t, ctx.role('color'), rows);
      const base = rows.map((r) => (C ? C.color(r) : pointColor()));
      const X = rows.map((r) => cols[0].values[r]), Y = rows.map((r) => cols[1].values[r]), Z = rows.map((r) => cols[2].values[r]);
      const traces = [{ type: 'scatter3d', mode: 'markers', x: X, y: Y, z: Z, rows, marker: { size: 3.5, color: base, line: { width: 0 } },
        hovertext: rows.map((r) => rowHover(t, r, [...cols, C ? C.col : null])), hovertemplate: '%{hovertext}<extra></extra>', showlegend: false }];
      if (ctx.opt('drop', false) && rows.length <= 3000) {
        const zmin = Math.min(...Z);
        const dx = [], dy = [], dz = [];
        rows.forEach((_, k) => { dx.push(X[k], X[k], null); dy.push(Y[k], Y[k], null); dz.push(zmin, Z[k], null); });
        traces.push({ type: 'scatter3d', mode: 'lines', x: dx, y: dy, z: dz, line: { color: rgba(SM.util.themeColors().muted, 0.5), width: 1 }, hoverinfo: 'skip', showlegend: false });
      }
      const w = Math.min(760, availWidth(ctx)), h = Math.round(Math.min(620, w * 0.82));
      const box = ctx.plot(traces, { scene: scene3d(cols.map((c) => c.name)), margin: { l: 0, r: 0, t: 6, b: 0 }, xaxis: { visible: false }, yaxis: { visible: false } }, { width: w, height: h, title: 'Scatterplot 3D' });
      pointStates(box, [{ trace: 0, rows, coords: { x: X, y: Y, z: Z }, color: base, size: 3.5, symbols: SYM3D, fade: 0.2, mask: !!C }]);
      ctx.container.append(pick, box, htmlLegend(C), ctx.note(`${rows.length} rows with all three values. Drag to rotate; to zoom, pick Zoom in the toolbar above the graph and drag. A click selects a row.`));
    },
  });

  /* ---- Contour Plot and Surface Plot -------------------------------------------------------------- */
  const THEMES = { ramp: ['Blue to Gray to Red', RAMP], viridis: ['Viridis', 'Viridis'], blues: ['Blues', 'Blues'], spectral: ['Spectral', 'Portland'] };
  const interpMenu = (ctx, sc) => ({ label: 'Interpolation', submenu: () => [['linear', 'Linear'], ['cubic', 'Cubic'], ['nearest', 'Nearest']].map(([v, l]) => ({ label: l, checked: ctx.opt('method', 'linear', sc) === v, action: () => ctx.set('method', v, sc) })) });
  const themeMenu = (ctx, sc) => ({ label: 'Color Theme', submenu: () => Object.entries(THEMES).map(([k, [l]]) => ({ label: l, checked: ctx.opt('theme', 'ramp', sc) === k, action: () => ctx.set('theme', k, sc) })) });

  function contourLevels(zmin, zmax, spec) {
    if (spec && spec.size > 0) return { start: spec.min ?? zmin, end: spec.max ?? zmax, size: spec.size };
    const n = spec && spec.n > 0 ? spec.n : 10;
    if (!(zmax > zmin)) return { start: zmin, end: zmin + 1, size: 1 };
    const size = niceStep((zmax - zmin) / n);
    return { start: Math.ceil(zmin / size) * size, end: Math.floor(zmax / size) * size, size };
  }

  const XY_LAUNCH = (lead) => ({
    lead,
    roles: [
      { key: 'y', label: 'Y', min: 1, numeric: true, types: ['continuous'], hint: 'required: the values (one graph each)', help: 'The values to draw over the plane of the two X columns; each Y column gets a graph of its own.' },
      { key: 'x', label: 'X', min: 2, max: 2, numeric: true, types: ['continuous'], hint: 'required: two coordinates', help: 'Exactly two continuous columns, the coordinates of each row: the first across, the second up. Rows at the same pair of X values are averaged, and the values between the rows are interpolated on their Delaunay triangulation; outside the rows\' hull there are none.' },
      { key: 'by', label: 'By', hint: 'optional', help: 'A separate graph for each level of the By columns.' },
    ],
  });

  SM.platforms.register({
    id: 'contour', label: 'Contour Plot', menu: 'Graph', order: 40, info: 'p:contour',
    topics: {
      'p:contour': {
        kicker: 'Graph', title: 'Contour Plot',
        lead: 'The values of Y over the plane of two X columns, as contour lines or filled bands. The values between the points come from interpolation on their Delaunay triangulation (scipy.interpolate.griddata); outside the points\' hull there is none.',
        sections: [{ heading: 'The red triangle', choices: [
          ['Show Data Points', 'The rows as points over the contours, linked to the table. On by default.'],
          ['Fill Areas', 'Colours the bands between the contour lines instead of drawing the lines alone.'],
          ['Label Contours', 'Writes each contour\'s level on its line.'],
          ['Specify Contours…', 'How many contours, or the step between them with a first and last level; empty is automatic: about 10 at round levels.'],
          ['Interpolation', '**Linear** (the default): a plane over each triangle of the Delaunay triangulation of the rows; **Cubic**: a smooth surface through them (scipy\'s Clough–Tocher); **Nearest**: each grid point takes the value of the nearest row, and there are values beyond the hull too.'],
          ['Color Theme', 'The colour scale of the levels: Blue to Gray to Red (the default), Viridis, Blues or Spectral.'],
        ] }],
        more: { label: 'Contour Plot', id: 'help-p-contour' },
      },
    },
    about: 'Contours of a response over two coordinates, interpolated on the Delaunay triangulation of the points (linear, cubic or nearest), with the data points linked.',
    uses: ['scipy.interpolate.griddata'],
    launch: XY_LAUNCH('Choose the response Y and the two X coordinates. Each Y gets its contour plot.'),
    title: () => 'Contour Plot',
    async render(ctx) {
      const [xa, xb] = ctx.roles('x');
      for (const yc of ctx.roles('y')) {
        const sc = yc.id;
        const o = (k, d) => ctx.opt(k, d, sc);
        const ob = ctx.outline(`Contour Plot for ${yc.name}`, { key: `c:${yc.id}`, menu: () => [
          ctx.check('Show Data Points', 'points', sc, true), ctx.check('Fill Areas', 'fill', sc, false), ctx.check('Label Contours', 'labels', sc, false),
          { label: 'Specify Contours…', action: async () => { const cur = o('levels', {}); const v = await SM.ui.form({ title: `Specify Contours: ${yc.name}`, lead: 'Either the number of contours, or the step (with an optional first and last level). Empty: automatic.', fields: [{ key: 'n', label: 'Number of contours', type: 'number', value: cur.n ?? null, help: 'About how many contours: the step between them is the round number at or just above the range of Y divided by this (10 when empty). Not used when a Step is given.' }, { key: 'size', label: 'Step', type: 'number', value: cur.size ?? null, help: 'The distance between two contour levels, in the units of Y; it takes the place of the number of contours.' }, { key: 'min', label: 'First level', type: 'number', value: cur.min ?? null, help: 'With a Step: the lowest contour level (empty: the lowest interpolated value).' }, { key: 'max', label: 'Last level', type: 'number', value: cur.max ?? null, help: 'With a Step: the highest contour level (empty: the highest interpolated value).' }] }); if (v) ctx.set('levels', v, sc); } },
          interpMenu(ctx, sc), themeMenu(ctx, sc),
        ] });
        const res = await ctx.call('graph.interp', { x: xa.name, y: xb.name, z: yc.name, method: o('method', 'linear'), grid: 70 });
        if (res.error) { ob.add(ctx.warn(`${yc.name}: ${res.error}`)); continue; }
        const lv = contourLevels(res.zmin, res.zmax, o('levels', null));
        const fill = o('fill', false);
        const traces = [{ type: 'contour', x: res.x, y: res.y, z: res.z, autocontour: false, contours: { ...lv, coloring: fill ? 'fill' : 'lines', showlabels: o('labels', false), labelfont: { size: 10, color: SM.util.themeColors().text } }, colorscale: THEMES[o('theme', 'ramp')][1], line: { width: 1.4 }, connectgaps: false,
          colorbar: { title: { text: esc(yc.name), side: 'right' }, thickness: 12, outlinewidth: 0 }, hovertemplate: `${esc(xa.name)} %{x}<br>${esc(xb.name)} %{y}<br>${esc(yc.name)} %{z:.4g}<extra></extra>` }];
        if (o('points', true)) {
          const rows = ctx.rows.filter((r) => [xa, xb, yc].every((c) => Number.isFinite(c.values[r])));
          traces.push({ type: rows.length > GL_POINTS && webgl() ? 'scattergl' : 'scatter', mode: 'markers', x: rows.map((r) => xa.values[r]), y: rows.map((r) => xb.values[r]), rows, marker: { size: 5, color: dark() ? '#e8e0d8' : '#3d3229', opacity: 0.75 }, hovertext: rows.map((r) => rowHover(ctx.table, r, [xa, xb, yc])), hovertemplate: '%{hovertext}<extra></extra>', showlegend: false });
        }
        const w = Math.min(640, availWidth(ctx)), h = Math.round(w * 0.78);
        ob.add(ctx.plot(traces, { xaxis: { title: { text: esc(xa.name) }, zeroline: false }, yaxis: { title: { text: esc(xb.name) }, zeroline: false }, margin: { l: 60, r: 10, t: 10, b: 46 } }, { width: w, height: h, title: `Contour plot of ${yc.name}` }),
          ctx.note(`${res.n} points (${res.points} distinct positions), ${res.method} interpolation on a 70 × 70 grid; ${fill ? 'filled bands' : 'lines'} every ${fmt(lv.size)}.`), ctx.code(res.code));
      }
    },
  });

  SM.platforms.register({
    id: 'surface', label: 'Surface Plot', menu: 'Graph', order: 110, info: 'p:surface',
    topics: {
      'p:surface': {
        kicker: 'Graph', title: 'Surface Plot',
        lead: 'The values of Y over two X columns as a surface to turn with the mouse, interpolated between the points (scipy.interpolate.griddata), with the data points as a cloud; a click on a point selects its row.',
        sections: [{ heading: 'The red triangle', choices: [
          ['Show Data Points', 'The rows as points around the surface, linked to the table. On by default.'],
          ['Show Contours', 'Contour lines of the surface, drawn on it and projected below it.'],
          ['Interpolation', '**Linear** (the default): a plane over each triangle of the Delaunay triangulation of the rows; **Cubic**: a smooth surface through them (Clough–Tocher); **Nearest**: the value of the nearest row, beyond the hull too.'],
          ['Color Theme', 'The colour scale of the surface: Blue to Gray to Red (the default), Viridis, Blues or Spectral.'],
          ['Grid Size…', 'How many grid points the surface has along each X (default 40).'],
        ] }, { heading: 'The graph', text: 'Drag to turn it; to zoom, pick Zoom in the toolbar above the graph and drag. A click on a data point selects its row. The graph needs WebGL.' }],
        more: { label: 'Surface Plot', id: 'help-p-surface' },
      },
    },
    about: 'A response over two coordinates as a 3-D surface interpolated on the Delaunay triangulation of the points, with the linked data points.',
    uses: ['scipy.interpolate.griddata'],
    launch: XY_LAUNCH('Choose the response Y and the two X coordinates. Each Y gets its surface.'),
    title: () => 'Surface Plot',
    async render(ctx) {
      const [xa, xb] = ctx.roles('x');
      for (const yc of ctx.roles('y')) {
        const sc = yc.id;
        const o = (k, d) => ctx.opt(k, d, sc);
        const ob = ctx.outline(`Surface Plot for ${yc.name}`, { key: `s:${yc.id}`, menu: () => [
          ctx.check('Show Data Points', 'points', sc, true), ctx.check('Show Contours', 'contours', sc, false),
          interpMenu(ctx, sc), themeMenu(ctx, sc),
          { label: 'Grid Size…', action: async () => { const v = await SM.ui.form({ title: 'Grid Size', fields: [{ key: 'g', label: 'Points on each axis (10 to 120)', type: 'number', value: o('grid', 40), help: 'The surface is interpolated at this many points along each X, so on a grid of this many squared (default 40). A finer grid shows more detail and draws more slowly; values outside 10 to 120 are brought inside.' }] }); if (v && v.g) ctx.set('grid', clamp(Math.round(v.g), 10, 120), sc); } },
        ] });
        const res = await ctx.call('graph.interp', { x: xa.name, y: xb.name, z: yc.name, method: o('method', 'linear'), grid: o('grid', 40) });
        if (res.error) { ob.add(ctx.warn(`${yc.name}: ${res.error}`)); continue; }
        const traces = [{ type: 'surface', x: res.x, y: res.y, z: res.z, colorscale: THEMES[o('theme', 'ramp')][1], opacity: 0.92, colorbar: { title: { text: esc(yc.name), side: 'right' }, thickness: 12, len: 0.7, outlinewidth: 0 },
          contours: o('contours', false) ? { z: { show: true, usecolormap: true, project: { z: true } } } : {}, hovertemplate: `${esc(xa.name)} %{x}<br>${esc(xb.name)} %{y}<br>${esc(yc.name)} %{z:.4g}<extra></extra>` }];
        const specs = [];
        if (o('points', true)) {
          const rows = ctx.rows.filter((r) => [xa, xb, yc].every((c) => Number.isFinite(c.values[r])));
          const X = rows.map((r) => xa.values[r]), Y = rows.map((r) => xb.values[r]), Z = rows.map((r) => yc.values[r]);
          const base = dark() ? '#f0e6dc' : '#2b221b';
          traces.push({ type: 'scatter3d', mode: 'markers', x: X, y: Y, z: Z, rows, marker: { size: 3, color: base }, hovertext: rows.map((r) => rowHover(ctx.table, r, [xa, xb, yc])), hovertemplate: '%{hovertext}<extra></extra>', showlegend: false });
          specs.push({ trace: 1, rows, coords: { x: X, y: Y, z: Z }, color: base, size: 3, symbols: SYM3D, fade: 0.3 });
        }
        const w = Math.min(760, availWidth(ctx)), h = Math.round(Math.min(640, w * 0.82));
        const box = ctx.plot(traces, { scene: scene3d([xa.name, xb.name, yc.name]), margin: { l: 0, r: 0, t: 6, b: 0 }, xaxis: { visible: false }, yaxis: { visible: false } }, { width: w, height: h, title: `Surface of ${yc.name}` });
        if (specs.length) pointStates(box, specs);
        ob.add(box, ctx.note(`${res.n} points, ${res.method} interpolation on a ${o('grid', 40)} × ${o('grid', 40)} grid; outside the points' hull the surface is missing.`), ctx.code(res.code));
      }
    },
  });

  /* ---- Bubble Plot -------------------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'bubble', label: 'Bubble Plot', menu: 'Graph', order: 50, info: 'p:bubble',
    topics: {
      'p:bubble': {
        kicker: 'Graph', title: 'Bubble Plot',
        lead: 'A scatterplot whose points are bubbles: their area follows Sizes, their colour Coloring. With an ID, the rows of each ID become one bubble at their mean X and Y, sized by the sum of Sizes; with Time, a slider and Play step through the times.',
        sections: [
          { heading: 'In the report', choices: [
            ['Time slider, Play, Pause', 'With a Time column: the slider shows the bubbles at one time, Play steps through the times in their order and Pause stops it.'],
            ['A bubble', 'Click it to select all its rows, at every time; bubbles that hold a selected row get a heavy outline. Hover for its ID, time, mean X and Y, size and number of rows.'],
          ] },
          { heading: 'The red triangle', choices: [
            ['Label', 'Writes each bubble\'s ID (or the row\'s label) on it.'],
            ['All Times', 'With a Time column: every row at once, a bubble for each ID over all the times, without the animation.'],
            ['Bubble Size', 'Scales every bubble, × 0.5 to × 2; at × 1 the largest bubble is 46 pixels across.'],
          ] },
        ],
        more: { label: 'Bubble Plot', id: 'help-p-bubble' },
      },
    },
    about: 'Bubbles at the mean X and Y of each ID, sized by the sum of a column and coloured by another, animated over Time with a slider; linked to the rows of each bubble.',
    uses: ['plotly frames (animation)'],
    launch: {
      lead: 'Y and X place the bubbles. ID makes one bubble of the rows of each level; Time animates them.',
      roles: [
        { key: 'y', label: 'Y', min: 1, max: 1, numeric: true, types: ['continuous'], hint: 'required', help: 'The vertical position: each bubble sits at the mean Y of its rows (Freq-weighted).' },
        { key: 'x', label: 'X', min: 1, max: 1, numeric: true, types: ['continuous'], hint: 'required', help: 'The horizontal position: the mean X of the bubble\'s rows.' },
        { key: 'id', label: 'ID', max: 2, hint: 'optional: a bubble per level', help: 'One or two columns: the rows of each level (or each pair of levels) make one bubble, named after it. Without an ID every row is a bubble. Rows with a missing ID are left out.' },
        { key: 'time', label: 'Time', max: 1, hint: 'optional: animation', help: 'Animates the bubbles: a frame for each level of this column in its value order, with a slider and Play; each frame\'s bubbles are made of that time\'s rows. Rows with no time are left out.' },
        { key: 'size', label: 'Sizes', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric', help: 'The bubbles\' areas are proportional to the sum of this column over their rows; without it, to their count of rows (with Freq, the sum of the counts).' },
        { key: 'color', label: 'Coloring', max: 1, hint: 'optional', help: 'Colours the bubbles: a categorical column by the most common level among each bubble\'s rows (with a legend), a continuous one by their mean on a blue-to-red gradient.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric', help: 'A count for each row: it weights the mean X and Y (and the count that sizes a bubble without Sizes); rows with a missing, zero or negative count are left out.' },
        { key: 'by', label: 'By', hint: 'optional', help: 'A separate graph for each level of the By columns.' },
      ],
    },
    title: () => 'Bubble Plot',
    triangle(ctx) {
      return [
        ctx.check('Label', 'label', null, false),
        ctx.check('All Times', 'allTimes', null, false, { disabled: !ctx.role('time') }),
        { label: 'Bubble Size', submenu: () => [0.5, 0.75, 1, 1.5, 2].map((f) => ({ label: `× ${f}`, checked: ctx.opt('scale', 1) === f, action: () => ctx.set('scale', f) })) },
      ];
    },
    async render(ctx) {
      const t = ctx.table;
      const Y = ctx.role('y'), X = ctx.role('x'), IDs = ctx.roles('id'), T = ctx.role('time'), Z = ctx.role('size'), F = ctx.role('freq');
      const W = (r) => (F ? F.values[r] : 1);
      const rows = ctx.rows.filter((r) => Number.isFinite(X.values[r]) && Number.isFinite(Y.values[r]) && (!F || W(r) > 0) && !(T && isMissing(T.values[r])) && !IDs.some((c) => isMissing(c.values[r])));
      const C = colorer(t, ctx.role('color'), rows);
      // the bubbles: the ID levels (or the rows), and the times
      const times = T && !ctx.opt('allTimes', false) ? levelsAmong(t, T, rows) : [null];
      const tIndex = new Map(times.map((v, i) => [v, i]));
      let itemOf, labels;
      if (IDs.length) {
        const keys = new Map();
        labels = [];
        itemOf = (r) => {
          const k = IDs.map((c) => String(c.values[r])).join('\u0001');
          if (!keys.has(k)) { keys.set(k, labels.length); labels.push(IDs.map((c) => cellText(c, c.values[r])).join(', ')); }
          return keys.get(k);
        };
      } else {
        const pos = new Map(rows.map((r, i) => [r, i]));
        labels = rows.map((r) => { const lab = t.labelColumn(); return lab && !isMissing(lab.values[r]) ? cellText(lab, lab.values[r]) : `row ${r + 1}`; });
        itemOf = (r) => pos.get(r);
      }
      const cells = new Map();     // frame * big + item -> rows
      for (const r of rows) {
        const f = T && times[0] != null ? tIndex.get(T.values[r]) : 0;
        if (f == null) continue;
        const i = itemOf(r);
        const key = f * 1e7 + i;
        if (!cells.has(key)) cells.set(key, []);
        cells.get(key).push(r);
      }
      const nItems = labels.length;
      const itemRows = Array.from({ length: nItems }, () => []);
      for (const r of rows) itemRows[itemOf(r)].push(r);
      const frames = times.map((tv, f) => {
        const x = new Array(nItems).fill(null), y = new Array(nItems).fill(null), s = new Array(nItems).fill(0), col = new Array(nItems).fill(pointColor()), hov = new Array(nItems).fill('');
        for (let i = 0; i < nItems; i++) {
          const rs = cells.get(f * 1e7 + i);
          if (!rs) continue;
          let sw = 0, sx = 0, sy = 0, sz = 0;
          for (const r of rs) { const w = W(r); sw += w; sx += w * X.values[r]; sy += w * Y.values[r]; sz += Z ? (Number.isFinite(Z.values[r]) ? Z.values[r] : 0) : w; }
          x[i] = sx / sw; y[i] = sy / sw; s[i] = Math.max(0, sz);
          if (C && C.cat) {
            const counts = new Map();
            for (const r of rs) { const k = C.index(r); counts.set(k, (counts.get(k) || 0) + W(r)); }
            let best = -1, bn = -1;
            for (const [k2, n2] of counts) if (n2 > bn || (n2 === bn && k2 < best)) { best = k2; bn = n2; }
            col[i] = best >= 0 ? PALETTE[best % PALETTE.length] : pointColor();
          } else if (C) {
            let cs = 0, cw = 0;
            for (const r of rs) { const v = C.col.values[r]; if (Number.isFinite(v)) { cs += W(r) * v; cw += W(r); } }
            col[i] = cw && C.range ? SM.util.ramp(C.range[1] > C.range[0] ? (cs / cw - C.range[0]) / (C.range[1] - C.range[0]) : 0.5) : pointColor();
          }
          hov[i] = `${esc(labels[i])}${tv != null ? `<br>${esc(T.name)}: ${esc(cellText(T, tv))}` : ''}<br>${esc(X.name)}: ${fmt(x[i], { sig: 5 })}<br>${esc(Y.name)}: ${fmt(y[i], { sig: 5 })}<br>${Z ? `${esc(Z.name)} (sum)` : 'N'}: ${fmt(s[i], { sig: 5 })}<br>rows: ${rs.length}`;
        }
        return { name: String(f), label: tv == null ? '' : cellText(T, tv), x, y, s, col, hov };
      });
      let smax = 0;
      for (const fr of frames) for (const v of fr.s) smax = Math.max(smax, v);
      const maxPx = 46 * (ctx.opt('scale', 1) || 1);
      const sizeref = smax > 0 ? (2 * smax) / (maxPx * maxPx) : 1;
      const f0 = frames[0];
      const lab = ctx.opt('label', false);
      const tr = { type: 'scatter', mode: lab ? 'markers+text' : 'markers', x: f0.x, y: f0.y, text: lab ? labels.map(esc) : undefined, textposition: 'middle center', textfont: { size: 9 },
        marker: { size: f0.s, sizemode: 'area', sizeref, sizemin: 2, color: f0.col, opacity: 0.72, line: { width: labels.map(() => 0.6), color: labels.map(() => rgba(SM.util.themeColors().text, 0.5)) } },
        hovertext: f0.hov, hovertemplate: '%{hovertext}<extra></extra>', showlegend: false };
      const exX = extent(rows.map((r) => X.values[r])), exY = extent(rows.map((r) => Y.values[r]));
      const pad = (ex) => (ex ? [ex[0] - 0.08 * (ex[1] - ex[0] || 1), ex[1] + 0.08 * (ex[1] - ex[0] || 1)] : undefined);
      const layout = { xaxis: { title: { text: esc(X.name) }, range: pad(exX), zeroline: false }, yaxis: { title: { text: esc(Y.name) }, range: pad(exY), zeroline: false }, margin: { l: 60, r: 12, t: 10, b: frames.length > 1 ? 120 : 46 }, showlegend: !!(C && C.cat), legend: C && C.cat ? { title: { text: esc(C.col.name) } } : undefined };
      if (frames.length > 1) {
        layout.sliders = [{ active: 0, x: 0.2, len: 0.8, y: 0, yanchor: 'top', pad: { t: 50 }, currentvalue: { prefix: `${esc(T.name)}: `, font: { size: 12 } },
          steps: frames.map((fr) => ({ label: esc(fr.label), method: 'animate', args: [[fr.name], { mode: 'immediate', frame: { duration: 300, redraw: false }, transition: { duration: 250 } }] })) }];
        layout.updatemenus = [{ type: 'buttons', showactive: false, x: 0, xanchor: 'left', y: 0, yanchor: 'top', pad: { t: 64, r: 8 }, direction: 'left',
          buttons: [{ label: 'Play', method: 'animate', args: [null, { fromcurrent: true, frame: { duration: 600, redraw: false }, transition: { duration: 400 } }] }, { label: 'Pause', method: 'animate', args: [[null], { mode: 'immediate', frame: { duration: 0, redraw: false }, transition: { duration: 0 } }] }] }];
      }
      const traces = [tr, ...(C && C.cat ? legendTraces(C) : [])];
      const w = Math.min(760, availWidth(ctx)), h = Math.round(w * 0.66) + (frames.length > 1 ? 80 : 0);
      const box = ctx.plot(traces, layout, { width: w, height: h, title: 'Bubble Plot', onDraw: (gd) => {
        if (frames.length > 1) Plotly.addFrames(gd, frames.map((fr) => ({ name: fr.name, data: [{ x: fr.x, y: fr.y, 'marker.size': fr.s, 'marker.color': fr.col, hovertext: fr.hov }], traces: [0] })));
      } });
      // Linked by ID: a click selects the bubble's rows, and bubbles with a selected row are ringed.
      link(box, [], { after: (p, sel) => {
        const st = t.state;
        const on = itemRows.map((rs) => sel && rs.some((r) => st[r] & 1));
        try { Plotly.restyle(p.box, { 'marker.line.width': [on.map((v) => (v ? 3 : 0.6))], 'marker.line.color': [on.map((v) => (v ? SM.report.SELECTED : rgba(SM.util.themeColors().text, 0.5)))] }, [0]); } catch (e) { /* not drawn */ }
      } });
      const p = box._plot;
      const prev = p.opts.onDraw;
      p.opts.onDraw = (gd) => {
        if (prev) prev(gd);
        gd.on('plotly_click', (ev) => {
          const pt = ev && ev.points && ev.points[0];
          if (!pt || pt.curveNumber !== 0) return;
          const rs = itemRows[pt.pointNumber] || [];
          const e = ev.event || {};
          if (rs.length) t.select(rs, e.shiftKey ? 'add' : (e.metaKey || e.ctrlKey) ? 'toggle' : 'replace');
        });
        gd.on('plotly_selected', (ev) => {
          const pl = gd._plot;
          if (!ev || !ev.points || (pl && pl.quiet)) return;
          const rs = [];
          for (const pt of ev.points) if (pt.curveNumber === 0) rs.push(...(itemRows[pt.pointNumber] || []));
          const go = () => t.select(rs, (ev.event && ev.event.shiftKey) ? 'add' : 'replace');
          if (pl) pl.own(go); else go();
        });
      };
      box._bubble = { frames, labels, itemRows };
      ctx.container.append(box, ctx.note(`${nItems} bubble${nItems === 1 ? '' : 's'}${IDs.length ? ` (one per ${IDs.map((c) => c.name).join(' × ')})` : ' (one per row)'} at the mean ${X.name} and ${Y.name}${F ? ` weighted by ${F.name}` : ''}; area proportional to ${Z ? `the sum of ${Z.name}` : 'the count of rows'}${frames.length > 1 ? `; ${frames.length} times of ${T.name}` : ''}.`));
    },
  });

  /* ---- Parallel Plot ---------------------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'parallel', label: 'Parallel Plot', menu: 'Graph', order: 60, info: 'p:parallel',
    topics: {
      'p:parallel': {
        kicker: 'Graph', title: 'Parallel Plot',
        lead: 'Each row is a line across parallel axes, one per column. By default each axis runs from its column\'s minimum to its maximum; Scale Uniformly puts them on one scale, Standardize on z-scores.',
        sections: [
          { heading: 'Selecting', text: 'Click a line\'s vertex to select its row, or drag a rectangle over part of one axis to select the rows that pass through it (brushing). Selected rows are drawn over the others in orange.' },
          { heading: 'Grouping', text: 'X, Grouping colours the lines by level.' },
          { heading: 'The red triangle', choices: [
            ['Scale Uniformly', 'Every axis on one scale, the values themselves, instead of each running from its column\'s minimum (bottom) to its maximum (top).'],
            ['Standardize', 'Every axis in standard deviations from its mean: (value − mean)/std dev, so columns in different units compare.'],
            ['Center at Zero', 'With Scale Uniformly: each column\'s mean moved to 0, so the axes compare their spreads.'],
            ['Reverse Axes…', 'Turns the axes you tick upside down (↓ before the name), which helps when a column falls as the others rise.'],
          ] },
        ],
        more: { label: 'Parallel Plot', id: 'help-p-parallel' },
      },
    },
    about: 'Rows as lines across parallel axes (each column on its range, on one scale, or standardized), coloured by a grouping column; click or brush an axis range to select rows.',
    uses: ['plotly (drawing only)'],
    launch: {
      lead: 'Choose two or more continuous columns; each row becomes a line across their axes.',
      roles: [
        { key: 'y', label: 'Y, Response', min: 2, numeric: true, types: ['continuous'], hint: 'required: two or more', help: 'Two or more continuous columns, an axis each, from left to right in this order. A row with a missing value in any of them is left out.' },
        { key: 'x', label: 'X, Grouping', max: 1, types: ['ordinal', 'nominal'], hint: 'optional categorical', help: 'A categorical column that colours the lines by level, with a legend.' },
        { key: 'by', label: 'By', hint: 'optional', help: 'A separate graph for each level of the By columns.' },
      ],
    },
    title: () => 'Parallel Plot',
    triangle(ctx) {
      const sc = ctx.opt('scale', 'range');
      return [
        { label: 'Scale Uniformly', checked: sc === 'uniform', action: () => ctx.set('scale', sc === 'uniform' ? 'range' : 'uniform') },
        { label: 'Standardize', checked: sc === 'std', action: () => ctx.set('scale', sc === 'std' ? 'range' : 'std') },
        ctx.check('Center at Zero', 'center', null, false, { disabled: sc !== 'uniform' }),
        { label: 'Reverse Axes…', action: async () => {
          const cols = ctx.roles('y');
          const cur = new Set(ctx.opt('reverse', []));
          const v = await SM.ui.form({ title: 'Reverse Axes', lead: 'The axes to turn upside down.', fields: cols.map((c) => ({ key: c.id, label: c.name, type: 'check', value: cur.has(c.id), helpLabel: 'A column', help: 'Ticked: its axis is turned upside down, the largest value at the bottom (↓ before its name under the axis).' })) });
          if (v) ctx.set('reverse', cols.filter((c) => v[c.id]).map((c) => c.id));
        } },
      ];
    },
    async render(ctx) {
      const t = ctx.table;
      const cols = ctx.roles('y');
      const k = cols.length;
      const rows = ctx.rows.filter((r) => cols.every((c) => Number.isFinite(c.values[r])));
      const scale = ctx.opt('scale', 'range'), center = ctx.opt('center', false);
      const rev = new Set(ctx.opt('reverse', []));
      const stats = cols.map((c) => {
        const v = rows.map((r) => c.values[r]);
        const ex = extent(v) || [0, 1];
        const m = v.reduce((a, b) => a + b, 0) / (v.length || 1);
        const sd = Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / Math.max(1, v.length - 1)) || 1;
        return { lo: ex[0], hi: ex[1], m, sd };
      });
      const val = (j, r) => {
        const s = stats[j], v = cols[j].values[r];
        let u = scale === 'std' ? (v - s.m) / s.sd : scale === 'uniform' ? (center ? v - s.m : v) : (s.hi > s.lo ? (v - s.lo) / (s.hi - s.lo) : 0.5);
        if (rev.has(cols[j].id)) u = scale === 'range' ? 1 - u : -u;
        return u;
      };
      const G = colorer(t, ctx.role('x'), rows);
      const groups = G ? G.labels.map((_, g) => rows.filter((r) => G.index(r) === g)) : [rows];
      const gl = webgl() && rows.length * k > GL_POINTS;
      const traces = [], paths = new Map();
      groups.forEach((rs, g) => {
        const X = [], Yv = [], RR = [], H = [];
        for (const r of rs) {
          const ys = [];
          for (let j = 0; j < k; j++) { const u = val(j, r); X.push(j); Yv.push(u); RR.push(r); ys.push(u); H.push(rowHover(t, r, [cols[j]])); }
          X.push(null); Yv.push(null); RR.push(r); H.push('');
          paths.set(r, [cols.map((_, j) => j), ys]);
        }
        if (!RR.length) return;
        const color = G ? PALETTE[g % PALETTE.length] : (dark() ? '#8fb3d6' : '#4a6f94');
        traces.push({ type: gl ? 'scattergl' : 'scatter', mode: 'lines+markers', x: X, y: Yv, rows: RR, line: { color: rgba(color, rows.length > 500 ? 0.35 : 0.65), width: 1 }, marker: { size: 3, color },
          hovertext: H, hovertemplate: '%{hovertext}<extra></extra>', name: G ? esc(G.labels[g]) : '', showlegend: !!G, legendgroup: `g${g}` });
      });
      const ov = { type: gl ? 'scattergl' : 'scatter', mode: 'lines', x: [], y: [], line: { color: SM.report.SELECTED, width: 2.2 }, hoverinfo: 'skip', showlegend: false };
      const oi = traces.push(ov) - 1;
      const tc = SM.util.themeColors();
      const shapes = cols.map((_, j) => ({ type: 'line', xref: 'x', yref: 'paper', x0: j, x1: j, y0: 0, y1: 1, line: { color: tc.muted, width: 1 } }));
      const annotations = [];
      if (scale === 'range') cols.forEach((c, j) => {
        const s = stats[j], r0 = rev.has(c.id);
        annotations.push({ x: j, y: 1, xref: 'x', yref: 'paper', yanchor: 'bottom', text: fmt(r0 ? s.lo : s.hi, { sig: 4 }), showarrow: false, font: { size: 10, color: tc.muted } },
          { x: j, y: 0, xref: 'x', yref: 'paper', yanchor: 'top', yshift: -2, text: fmt(r0 ? s.hi : s.lo, { sig: 4 }), showarrow: false, font: { size: 10, color: tc.muted } });
      });
      cols.forEach((c, j) => annotations.push({ x: j, y: 0, xref: 'x', yref: 'paper', yanchor: 'top', yshift: scale === 'range' ? -18 : -4, text: `${rev.has(c.id) ? '↓ ' : ''}${esc(c.name)}`, showarrow: false, font: { size: 11 } }));
      const w = Math.min(Math.max(420, 150 * k), availWidth(ctx)), h = 380;
      const layout = { xaxis: { range: [-0.25, k - 0.75], showticklabels: false, showgrid: false, zeroline: false, showline: false, ticks: '' },
        yaxis: scale === 'range' ? { range: [-0.04, 1.04], showticklabels: false, showgrid: false, zeroline: false, showline: false, ticks: '' } : { title: { text: scale === 'std' ? 'Standardized value' : center ? 'Value − mean' : 'Value' }, zeroline: scale !== 'range' },
        shapes, annotations, margin: { l: scale === 'range' ? 20 : 60, r: G ? 120 : 20, t: 24, b: 46 }, showlegend: !!G, legend: G ? { title: { text: esc(G.col.name) } } : undefined };
      const box = ctx.plot(traces, layout, { width: w, height: h, title: 'Parallel Plot' });
      // The lines are the core's (a row per vertex); the overlay redraws the selected rows' lines.
      link(box, [{ trace: -1, overlay: oi, kind: 'path', rows: [], paths, list: rows }]);
      ctx.container.append(box, ctx.note(`${rows.length} rows with every value${rows.length < ctx.rows.length ? ` (${ctx.rows.length - rows.length} with a missing value left out)` : ''}. ${scale === 'range' ? 'Each axis runs from its column\'s minimum (bottom) to its maximum (top).' : scale === 'std' ? 'Values standardized: (value − mean)/std dev.' : 'All columns on one scale.'} Drag a rectangle over an axis to select the rows through it.`));
    },
  });

  /* ---- Cell Plot ------------------------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'cellplot', label: 'Cell Plot', menu: 'Graph', order: 70, info: 'p:cellplot',
    topics: {
      'p:cellplot': {
        kicker: 'Graph', title: 'Cell Plot',
        lead: 'The table as colours: a row of cells for each row, a column for each column. Continuous columns are standardized and coloured blue (low) to red (high); categorical ones take a colour per level.',
        sections: [
          { heading: 'The red triangle', choices: [
            ['Scale Uniformly', 'Colours every continuous column on one scale, from the smallest value of them all to the largest, instead of each column in its own standard deviations (−3 to 3).'],
            ['Center at Zero', 'Puts the middle of the colour scale at the value zero: for standardized columns 0 rather than the mean, with Scale Uniformly a scale from minus to plus the largest absolute value.'],
            ['Legend', 'The colour bar of the continuous columns. On by default.'],
          ] },
          { heading: 'Selecting', text: 'A click on a cell selects its row; the selected rows are marked in the strip on the left.' },
        ],
        more: { label: 'Cell Plot', id: 'help-p-cellplot' },
      },
    },
    about: 'The rows as rows of coloured cells, one column per column (continuous standardized, categorical by level), with the selected rows marked; a click selects a row.',
    uses: ['plotly heatmap (drawing only)'],
    launch: {
      lead: 'Choose the columns to draw; X labels the rows.',
      roles: [
        { key: 'y', label: 'Y', min: 1, hint: 'required', help: 'The columns to draw, a column of cells each, in this order: continuous ones standardized and coloured blue (low) to red (high), categorical ones a colour for each level; missing values are left blank.' },
        { key: 'x', label: 'X, Label', max: 1, hint: 'optional: row labels', help: 'A column whose values label the rows down the side (up to 80 rows are labelled); without it, the table\'s label column or the row number.' },
        { key: 'by', label: 'By', hint: 'optional', help: 'A separate graph for each level of the By columns.' },
      ],
    },
    title: () => 'Cell Plot',
    triangle(ctx) { return [ctx.check('Scale Uniformly', 'uniform', null, false), ctx.check('Center at Zero', 'center', null, false), ctx.check('Legend', 'legend', null, true)]; },
    async render(ctx) {
      const t = ctx.table;
      const cols = ctx.roles('y');
      const rows = ctx.rows;
      const n = rows.length;
      const uni = ctx.opt('uniform', false), center = ctx.opt('center', false);
      const cont = cols.filter((c) => !isCat(c));
      let glo = Infinity, ghi = -Infinity;
      for (const c of cont) for (const r of rows) { const v = c.values[r]; if (Number.isFinite(v)) { if (v < glo) glo = v; if (v > ghi) ghi = v; } }
      const yIdx = rows.map((_, i) => i);
      const traces = [], links = [];
      let scaleShown = false;
      cols.forEach((c, j) => {
        let z, cs, zmin, zmax, text;
        if (isCat(c)) {
          const L = levelsAmong(t, c, rows);
          const m = new Map(L.map((v, i) => [v, i]));
          z = rows.map((r) => [m.has(c.values[r]) ? m.get(c.values[r]) : null]);
          const nl = Math.max(1, L.length);
          cs = [];
          L.forEach((_, i) => { const col = PALETTE[i % PALETTE.length]; cs.push([i / nl, col], [(i + 1) / nl, col]); });
          if (!cs.length) cs = [[0, '#aaa'], [1, '#aaa']];
          zmin = -0.5; zmax = nl - 0.5;
        } else {
          const v = rows.map((r) => c.values[r]).filter(Number.isFinite);
          const m = v.reduce((a, b) => a + b, 0) / (v.length || 1);
          const sd = Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / Math.max(1, v.length - 1)) || 1;
          if (uni) {
            z = rows.map((r) => [Number.isFinite(c.values[r]) ? c.values[r] : null]);
            zmin = glo; zmax = ghi;
            if (center) { const a = Math.max(Math.abs(glo), Math.abs(ghi)); zmin = -a; zmax = a; }
          } else {
            z = rows.map((r) => [Number.isFinite(c.values[r]) ? (c.values[r] - (center ? 0 : m)) / sd : null]);
            zmin = -3; zmax = 3;
          }
          cs = RAMP;
        }
        text = rows.map((r) => [isMissing(c.values[r]) ? '.' : esc(cellText(c, c.values[r]))]);
        const showscale = !isCat(c) && !scaleShown && ctx.opt('legend', true);
        if (showscale) scaleShown = true;
        const tr = { type: 'heatmap', x: [j], y: yIdx, z, text, colorscale: cs, zmin, zmax, showscale, xgap: 1, ygap: n > 150 ? 0 : 1,
          colorbar: showscale ? { title: { text: uni ? 'Value' : 'Standardized', side: 'right' }, thickness: 12, len: 0.6, outlinewidth: 0 } : undefined,
          hovertemplate: `${esc(c.name)}: %{text}<br>row %{customdata}<extra></extra>`, customdata: rows.map((r) => [r + 1]) };
        const ti = traces.push(tr) - 1;
        links.push({ trace: ti, overlay: null, kind: 'cell', rows: rows.map((r) => [[r]]) });
      });
      // the strip of selected rows, left of the columns
      const oi = traces.push({ type: 'heatmap', x: [-1], y: yIdx, z: rows.map(() => [null]), colorscale: [[0, rgba(SM.report.SELECTED, 0.9)], [1, SM.report.SELECTED]], zmin: 0, zmax: 1, showscale: false, hoverinfo: 'skip', xgap: 1 }) - 1;
      if (links.length) links[0].overlay = oi;
      const lab = ctx.role('x') || t.labelColumn();
      const showLabels = n <= 80;
      const layout = {
        xaxis: { tickmode: 'array', tickvals: [-1, ...cols.map((_, j) => j)], ticktext: ['', ...cols.map((c) => esc(c.name))], range: [-1.5, cols.length - 0.5], side: 'top', showgrid: false, zeroline: false, showline: false, ticks: '' },
        yaxis: { range: [n - 0.5, -0.5], tickmode: showLabels ? 'array' : 'auto', tickvals: showLabels ? yIdx : undefined, ticktext: showLabels ? rows.map((r) => esc(lab && !isMissing(lab.values[r]) ? cellText(lab, lab.values[r]) : String(r + 1))) : undefined, showticklabels: showLabels, showgrid: false, zeroline: false, title: showLabels ? undefined : { text: `${n} rows` } },
        margin: { l: showLabels ? 70 : 40, r: 16, t: 36, b: 12 },
      };
      const w = Math.min(availWidth(ctx), 120 + 70 * cols.length + 90), h = clamp((n <= 80 ? 15 : 3) * n + 90, 240, 900);
      const box = ctx.plot(traces, layout, { width: w, height: h, title: 'Cell Plot' });
      link(box, links);
      ctx.container.append(box, ctx.note(`${n} rows in table order. ${uni ? 'Continuous columns on one scale.' : `Continuous columns standardized${center ? ' about zero' : ''}, colours from −3 to 3 standard deviations.`} Categorical columns take a colour per level; missing values are left blank.`));
    },
  });

  /* ---- Ternary Plot ---------------------------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'ternary', label: 'Ternary Plot', menu: 'Graph', order: 80, info: 'p:ternary',
    topics: {
      'p:ternary': {
        kicker: 'Graph', title: 'Ternary Plot',
        lead: 'Three components of a mixture, each row a point in the triangle: its three values divided by their sum. Rows with a negative value or a zero sum are left out.',
        sections: [{ heading: 'Linking', text: 'Click a point or drag a lasso to select rows; selected rows show in orange, and the rows\' colours, markers, labels and hidden states apply.' }],
        more: { label: 'Ternary Plot', id: 'help-p-ternary' },
      },
    },
    about: 'Three components as shares of their sum in a triangle, one point per row, linked to the table.',
    uses: ['plotly scatterternary (drawing only)'],
    launch: {
      lead: 'Choose the three components.',
      roles: [
        { key: 'y', label: 'Y, Plotting', min: 3, max: 3, numeric: true, types: ['continuous'], hint: 'required: three', help: 'Exactly three numeric columns, the components of a mixture, one for each corner: each row is placed by its three values divided by their sum. Rows with a missing or negative value, or a zero sum, are left out.' },
        { key: 'color', label: 'Coloring', max: 1, hint: 'optional', help: 'Colours the points: a colour for each level of a categorical column (listed under the graph), a blue-to-red gradient over a continuous one. It takes the place of the rows\' own colours.' },
        { key: 'by', label: 'By', hint: 'optional', help: 'A separate graph for each level of the By columns.' },
      ],
    },
    title: () => 'Ternary Plot',
    async render(ctx) {
      const t = ctx.table;
      const [A, Bc, Cc] = ctx.roles('y');
      const rows = ctx.rows.filter((r) => [A, Bc, Cc].every((c) => Number.isFinite(c.values[r]) && c.values[r] >= 0) && A.values[r] + Bc.values[r] + Cc.values[r] > 0);
      const s = rows.map((r) => A.values[r] + Bc.values[r] + Cc.values[r]);
      const a = rows.map((r, k) => A.values[r] / s[k]), b = rows.map((r, k) => Bc.values[r] / s[k]), c = rows.map((r, k) => Cc.values[r] / s[k]);
      const C = colorer(t, ctx.role('color'), rows);
      const base = rows.map((r) => (C ? C.color(r) : pointColor()));
      const tc = SM.util.themeColors();
      const axis = (col) => ({ title: { text: esc(col.name) }, gridcolor: tc.grid, linecolor: tc.muted, tickcolor: tc.muted, color: tc.text, min: 0 });
      const traces = [{ type: 'scatterternary', mode: 'markers', a, b, c, rows, marker: { size: 6, color: base, line: { width: 0 } }, hovertext: rows.map((r, k) => `${rowHover(t, r, [A, Bc, Cc])}<br>shares ${fmt(a[k], { digits: 3 })}, ${fmt(b[k], { digits: 3 })}, ${fmt(c[k], { digits: 3 })}`), hovertemplate: '%{hovertext}<extra></extra>', showlegend: false }];
      const w = Math.min(620, availWidth(ctx));
      const box = ctx.plot(traces, { ternary: { sum: 1, aaxis: axis(A), baxis: axis(Bc), caxis: axis(Cc), bgcolor: 'rgba(0,0,0,0)' }, dragmode: 'lasso', xaxis: { visible: false }, yaxis: { visible: false }, margin: { l: 50, r: 50, t: 36, b: 36 } }, { width: w, height: Math.round(w * 0.9), title: 'Ternary Plot' });
      pointStates(box, [{ trace: 0, rows, coords: { a, b, c }, color: base, size: 6, symbols: SM.report.SYMBOLS, fade: 0.25, mask: !!C }]);
      ctx.container.append(box, htmlLegend(C), ctx.note(`${rows.length} rows${rows.length < ctx.rows.length ? `; ${ctx.rows.length - rows.length} with a missing or negative value, or a zero sum, left out` : ''}. Each point is (${A.name}, ${Bc.name}, ${Cc.name}) divided by their sum.`));
    },
  });

  /* ---- Treemap ------------------------------------------------------------------------------------------------ */
  SM.platforms.register({
    id: 'treemap', label: 'Treemap', menu: 'Graph', order: 90, info: 'p:treemap',
    topics: {
      'p:treemap': {
        kicker: 'Graph', title: 'Treemap',
        lead: 'A rectangle for each level of the categories, its area the count of rows (or the sum of Sizes), nested for a second category. Coloring colours the tiles by the mean of a continuous column, or by the level of a categorical one.',
        sections: [{ heading: 'Linking', text: 'A click on a tile selects its rows; tiles that hold a selected row get an orange outline. Alt-click zooms into a tile, and with two categories the path bar above the tiles goes back up.' }],
        more: { label: 'Treemap', id: 'help-p-treemap' },
      },
    },
    about: 'Nested rectangles for the levels of one or two categories, sized by the count or the sum of a column and coloured by another; a click on a tile selects its rows.',
    uses: ['plotly treemap (drawing only)'],
    launch: {
      lead: 'Choose one or two categories; Sizes (optional) sets the areas.',
      roles: [
        { key: 'x', label: 'Categories', min: 1, max: 2, types: ['ordinal', 'nominal'], hint: 'required: one or two', help: 'One or two categorical columns: a tile for each level of the first, in value order, split into tiles for the levels of the second. Rows with a missing category are left out.' },
        { key: 'size', label: 'Sizes', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric', help: 'The tiles\' areas are the sums of this column over their rows; rows with a missing, zero or negative value are left out. Without it, the areas are the counts of rows.' },
        { key: 'color', label: 'Coloring', max: 1, hint: 'optional', help: 'A continuous column colours each tile by its mean, blue (low) to red (high). A categorical one gives each tile the colour of its first row\'s level, which suits a column that is the same throughout a tile (the first category, say). Without it, the tiles of each level of the first category share a colour, lighter for the tiles of the second.' },
        { key: 'by', label: 'By', hint: 'optional', help: 'A separate treemap for each level of the By columns.' },
      ],
    },
    title: () => 'Treemap',
    async render(ctx) {
      const t = ctx.table;
      const cats = ctx.roles('x'), Z = ctx.role('size');
      const rows = ctx.rows.filter((r) => cats.every((c) => !isMissing(c.values[r])) && (!Z || (Number.isFinite(Z.values[r]) && Z.values[r] > 0)));
      const C = colorer(t, ctx.role('color'), rows);
      const w = (r) => (Z ? Z.values[r] : 1);
      const tiles = new Map();          // id -> { label, parent, value, rows }
      for (const r of rows) {
        let parent = '';
        cats.forEach((c, d) => {
          const lab = cellText(c, c.values[r]);
          const id = d === 0 ? `L0:${String(c.values[r])}` : `${parent}/L${d}:${String(c.values[r])}`;
          let tl = tiles.get(id);
          if (!tl) { tl = { id, label: lab, parent, value: 0, rows: [], depth: d }; tiles.set(id, tl); }
          tl.value += w(r);
          tl.rows.push(r);
          parent = id;
        });
      }
      // in the table's level order
      const order = cats.map((c) => new Map(t.levels(c).map((v, i) => [String(v), i])));
      const list = [...tiles.values()].sort((a, b) => a.depth - b.depth || (order[a.depth].get(a.id.split(':').pop()) ?? 0) - (order[b.depth].get(b.id.split(':').pop()) ?? 0));
      const colorOfTile = (tl, k) => {
        if (C && !C.cat && C.range) {
          let s = 0, n = 0;
          for (const r of tl.rows) { const v = C.col.values[r]; if (Number.isFinite(v)) { s += v; n++; } }
          return n ? SM.util.ramp(C.range[1] > C.range[0] ? (s / n - C.range[0]) / (C.range[1] - C.range[0]) : 0.5) : '#999';
        }
        if (C && C.cat) return C.color(tl.rows[0]);
        const top = tl.depth === 0 ? tl : tiles.get(tl.id.split('/')[0]);
        const i = list.filter((x) => x.depth === 0).indexOf(top);
        return rgba(PALETTE[(i >= 0 ? i : k) % PALETTE.length], tl.depth === 0 ? 0.9 : 0.62);
      };
      const tc = SM.util.themeColors();
      const tr = {
        type: 'treemap', ids: list.map((x) => x.id), labels: list.map((x) => esc(x.label)), parents: list.map((x) => x.parent), values: list.map((x) => x.value), branchvalues: 'total',
        marker: { colors: list.map(colorOfTile), line: { width: list.map(() => 1), color: list.map(() => tc.surface) } }, textinfo: 'label+value+percent parent', textfont: { size: 11 },
        hovertemplate: `%{label}<br>${esc(Z ? `Sum(${Z.name})` : 'N')}: %{value}<br>%{percentParent:.1%} of %{parent}<extra></extra>`, sort: false, pathbar: { visible: cats.length > 1 },
      };
      const W = Math.min(820, availWidth(ctx));
      const box = ctx.plot([tr], { margin: { l: 4, r: 4, t: 26, b: 4 }, xaxis: { visible: false }, yaxis: { visible: false } }, { width: W, height: Math.round(W * 0.6), title: 'Treemap' });
      link(box, [], { after: (p, sel) => {
        const st = t.state;
        const on = list.map((x) => sel && x.rows.some((r) => st[r] & 1));
        try { Plotly.restyle(p.box, { 'marker.line.width': [on.map((v) => (v ? 3.5 : 1))], 'marker.line.color': [on.map((v) => (v ? SM.report.SELECTED : tc.surface))] }, [0]); } catch (e) { /* not drawn */ }
      } });
      const p = box._plot;
      const prev = p.opts.onDraw;
      p.opts.onDraw = (gd) => {
        if (prev) prev(gd);
        gd.on('plotly_treemapclick', (ev) => {
          const pt = ev && ev.points && ev.points[0];
          const tl = pt ? tiles.get(pt.id) : null;
          if (!tl) return true;
          const e = ev.event || {};
          t.select(tl.rows, e.shiftKey ? 'add' : (e.metaKey || e.ctrlKey) ? 'toggle' : 'replace');
          return !!e.altKey;    // Alt-click zooms into the tile, as Plotly does by default
        });
      };
      box._tiles = { list };
      ctx.container.append(box, ctx.note(`${list.filter((x) => x.depth === 0).length} tiles of ${cats[0].name}${cats[1] ? `, split by ${cats[1].name}` : ''}; areas are ${Z ? `sums of ${Z.name}` : 'counts of rows'}. A click selects a tile's rows (Alt-click zooms in).`));
    },
  });

  /* ==========================================================================
     FUNCTIONAL DATA PLOT
     statsmodels' functional graphics (fboxplot, hdrboxplot, rainbowplot),
     their numbers from graph.fbox and graph.hdr, drawn here. A curve is a
     row (Rows as Functions) or the rows of an ID (Stacked), and it is linked
     as a whole: a click on a curve selects its rows, curves that hold a
     selected row are drawn over the others in the selection colour, and a
     curve whose rows are all hidden is not drawn.
     ========================================================================== */
  const FD_DEPTH = [['MBD', 'Modified Band Depth (MBD)'], ['BD2', 'Band Depth (BD2)'], ['BD2x', 'Band Depth (BD2), Counted']];
  const FD_SHORT = { MBD: 'MBD', BD2: 'BD2', BD2x: 'BD2, counted' };
  const FD_RULES = [['statsmodels', 'statsmodels (fboxplot)'], ['sungenton', 'Sun and Genton (R\'s fda::fbplot)']];
  const FD_BW = [['normal_reference', 'Normal Reference'], ['cv_ml', 'Cross-Validation, Likelihood'], ['cv_ls', 'Cross-Validation, Least Squares']];
  // The outlying curves' colours: the palette without the selection's orange.
  const FD_COLORS = PALETTE.filter((c) => c.toLowerCase() !== SM.report.SELECTED.toLowerCase());
  const VIRIDIS = ['#440154', '#482878', '#3e4989', '#31688e', '#26828e', '#1f9e89', '#35b779', '#6ece58', '#b5de2b', '#fde725'];
  function viridis(u) {
    const v = clamp(u, 0, 1) * (VIRIDIS.length - 1);
    const i = Math.min(VIRIDIS.length - 2, Math.floor(v)), f = v - i;
    const a = rgbOf(VIRIDIS[i]), b = rgbOf(VIRIDIS[i + 1]);
    return `rgb(${Math.round(a[0] + f * (b[0] - a[0]))}, ${Math.round(a[1] + f * (b[1] - a[1]))}, ${Math.round(a[2] + f * (b[2] - a[2]))})`;
  }
  /* The colour of a depth rank, q from 0 (the deepest) to 1: dark to light
     on a light page, bright to dark on a dark one. */
  const depthColor = (q) => viridis(dark() ? 1 - 0.8 * q : 0.88 * q);
  const pct = (v) => `${fmt(100 * v, { digits: 1 })}%`;

  /* What graph.fbox and graph.hdr are asked: the curves, and the By
     columns for the Python shown under the results. */
  function fdPayload(ctx) {
    const by = ctx.names('by');
    if (ctx.opt('format', 'wide') === 'long') return { layout: 'long', y: ctx.name('yl'), id: ctx.name('id'), x: ctx.name('x'), by };
    return { layout: 'wide', y: ctx.names('y'), xmode: ctx.opt('fdX', 'names'), by };
  }

  /* The curves as the page draws them: labels, rows, and paths with
     vertices between the points (a line is straight between them anyway),
     so that hovering or clicking anywhere along a curve finds it. */
  function fdCurves(ctx, fb) {
    const t = ctx.table;
    const long = fb.layout === 'long';
    const idCol = ctx.role('id') || (long ? null : t.labelColumn());
    const labels = fb.rows.map((rs) => (idCol && !isMissing(idCol.values[rs[0]]) ? cellText(idCol, idCol.values[rs[0]]) : `row ${rs[0] + 1}`));
    const x = fb.x, p = x.length;
    const k = p >= 48 ? 1 : Math.ceil(48 / Math.max(1, p - 1));
    const along = (v) => { const out = []; for (let j = 0; j < p - 1; j++) for (let s = 0; s < k; s++) out.push(v[j] + ((v[j + 1] - v[j]) * s) / k); out.push(v[p - 1]); return out; };
    const xc = long ? ctx.role('x') : null;
    const idName = long ? ctx.name('id') : null;
    const xTitle = long ? (xc ? xc.name : `the order of each ${idName}'s rows`) : (fb.source === 'names' ? 'X (from the Y column names)' : 'Y column');
    const yTitle = long ? ctx.name('yl') : 'Y';
    const xText = (v) => (xc && isDate(xc) ? cellText(xc, v) : (!long && fb.source === 'order' ? fb.names[Math.round(v) - 1] : fmt(v, { sig: 6 })));
    return { n: fb.curves.length, p, x, dx: along(x), Y: fb.curves, paths: fb.curves.map(along), rows: fb.rows, labels, long, idCol, xc, idName, xTitle, yTitle, xText,
      idHead: idCol ? idCol.name : 'Row', source: fb.source, names: fb.names };
  }

  /* A trace of several curves with gaps between them; vtx: the curve of each vertex. */
  function curveTrace(F, list, style, hov) {
    const x = [], y = [], vtx = [], text = [];
    for (const c of list) {
      const ys = F.paths[c], h = hov(c);
      for (let j = 0; j < ys.length; j++) { x.push(F.dx[j]); y.push(ys[j]); vtx.push(c); text.push(h); }
      x.push(null); y.push(null); vtx.push(-1); text.push('');
    }
    return { tr: { type: 'scatter', mode: 'lines', x, y, hovertext: text, hovertemplate: `%{hovertext}<br>${esc(F.xTitle)}: %{x}<br>${esc(F.yTitle)}: %{y:.4g}<extra></extra>`, ...style }, vtx };
  }

  /* A band between two curves, filled. */
  function fdBand(x, lo, hi, color, name, extra = {}) {
    return { type: 'scatter', mode: 'lines', x: [...x, ...x.slice().reverse()], y: [...hi, ...lo.slice().reverse()], fill: 'toself', fillcolor: color, line: { width: 0 }, hoverinfo: 'skip', name, ...extra };
  }

  /* Curves linked by curve. specs: [{ trace, vtx, x, y }] for the traces of
     curves; overlay: the trace that shows the selected curves. */
  function linkCurves(box, F, specs, overlay) {
    const p = box._plot;
    if (!p) return box;
    const t = p.table;
    let hidSig = '';
    link(box, [], { after: (pl, sel) => {
      const st = t.state;
      const hidden = F.rows.map((rs) => rs.every((r) => st[r] & 4));
      const sig = hidden.map((h) => (h ? 1 : 0)).join('');
      if (sig !== hidSig) {
        const had = hidSig.includes('1');
        hidSig = sig;
        if (had || sig.includes('1')) {
          const nul = (s, arr) => arr.map((v, k) => (s.vtx[k] >= 0 && hidden[s.vtx[k]] ? null : v));
          try { Plotly.restyle(pl.box, { x: specs.map((s) => nul(s, s.x)), y: specs.map((s) => nul(s, s.y)) }, specs.map((s) => s.trace)); } catch (e) { console.warn('SM graph: restyle failed', e); }
        }
      }
      const ox = [], oy = [];
      if (sel) {
        F.rows.forEach((rs, c) => {
          if (hidden[c] || !rs.some((r) => st[r] & 1)) return;
          const ys = F.paths[c];
          for (let j = 0; j < ys.length; j++) { ox.push(F.dx[j]); oy.push(ys[j]); }
          ox.push(null); oy.push(null);
        });
      }
      try { Plotly.restyle(pl.box, { x: [ox], y: [oy] }, [overlay]); } catch (e) { console.warn('SM graph: restyle failed', e); }
    } });
    const prev = p.opts.onDraw;
    p.opts.onDraw = (gd) => {
      if (prev) prev(gd);
      gd.on('plotly_click', (ev) => {
        const pt = ev && ev.points && ev.points[0];
        if (!pt || !t) return;
        const s = specs.find((q) => q.trace === pt.curveNumber);
        const c = s ? s.vtx[pt.pointNumber] : -1;
        if (c == null || c < 0) return;
        const e = ev.event || {};
        t.select(F.rows[c], e.shiftKey ? 'add' : (e.metaKey || e.ctrlKey) ? 'toggle' : 'replace');
      });
    };
    box._curves = { F, specs, overlay };
    return box;
  }

  const fdOverlay = () => ({ type: 'scatter', mode: 'lines', x: [], y: [], line: { color: SM.report.SELECTED, width: 2.8 }, hoverinfo: 'skip', showlegend: false });

  /* The layout of a graph of curves; with a legend of `entries` items, on
     the right, or under the graph when it is narrow. */
  function fdLayout(F, w, { legend = true, entries = 0 } = {}) {
    const bottom = w < 620;
    const ax = { title: { text: esc(F.xTitle) }, zeroline: false };
    if (F.xc && isDate(F.xc)) ax.type = 'date';
    if (!F.long && F.source === 'order' && F.p <= 30) { ax.tickmode = 'array'; ax.tickvals = F.x; ax.ticktext = F.names.map(esc); }
    const under = legend && bottom ? 19 * (w < 460 ? entries : Math.ceil(entries / 2)) + 16 : 0;
    return {
      xaxis: ax, yaxis: { title: { text: esc(F.yTitle) }, zeroline: false }, hovermode: 'closest', hoverdistance: 30,
      margin: { l: 60, r: 12, t: 10, b: 48 + under }, showlegend: legend,
      legend: bottom ? { orientation: 'h', x: 0, xanchor: 'left', y: 0, yanchor: 'bottom', yref: 'container' } : { x: 1.02, xanchor: 'left', y: 1, yanchor: 'top' },
      _under: under,
    };
  }
  const fdSize = (ctx) => { const w = Math.min(820, availWidth(ctx)); return { w, h: Math.round(clamp(w * 0.56, 280, 470)), named: w < 620 ? 5 : 12 }; };
  /* A graph of curves: its layout's room for a legend under it is added to the height. */
  function fdPlot(ctx, traces, F, { w, h }, { legend = true, title } = {}) {
    const entries = traces.filter((t) => t.name && t.showlegend !== false).length;
    const L = fdLayout(F, w, { legend, entries });
    const under = L._under;
    delete L._under;
    return ctx.plot(traces, L, { width: w, height: h + under, title });
  }

  /* Where a curve passes the fences: runs of X above and below. */
  function fdWhere(F, fb, c) {
    const ys = F.Y[c], parts = [];
    const runs = (test, word) => {
      let a = -1;
      for (let j = 0; j <= F.p; j++) {
        const on = j < F.p && test(j);
        if (on && a < 0) a = j;
        if (!on && a >= 0) { parts.push(`${word} ${F.xText(F.x[a])}${j - 1 > a ? `–${F.xText(F.x[j - 1])}` : ''}`); a = -1; }
      }
    };
    runs((j) => ys[j] > fb.fence_hi[j], 'above');
    runs((j) => ys[j] < fb.fence_lo[j], 'below');
    return parts.join('; ');
  }

  const selectMode = (ev) => (ev && ev.shiftKey ? 'add' : ev && (ev.metaKey || ev.ctrlKey) ? 'toggle' : 'replace');

  function fdDataNote(ctx, F, fb) {
    const parts = [];
    if (F.long) parts.push(`${F.n} curves, one for each ${F.idName}, at ${F.p} points of ${F.xc ? F.xc.name : `the order of their rows`}`);
    else parts.push(`${F.n} curves, one for each row, at ${F.p} points; X is ${fb.source === 'names' ? 'the number in each Y column\'s name' : 'the column order'}`);
    if (fb.dropped) parts.push(`${fb.dropped} row${fb.dropped > 1 ? 's' : ''} with a missing value left out`);
    if (fb.interp) parts.push(`the curves are not measured at the same X, so each is interpolated linearly (numpy.interp) to ${fb.interp.points} equally spaced points from ${F.xText(fb.interp.lo)} to ${F.xText(fb.interp.hi)}, the range every curve covers${fb.interp.left_out ? `; ${fb.interp.left_out} curve${fb.interp.left_out > 1 ? 's' : ''} with fewer than two points left out` : ''}`);
    if (fb.averaged) parts.push('values at the same X within a curve are averaged');
    if (fb.ties && fb.method !== 'BD2x') parts.push(`${fb.ties} value${fb.ties > 1 ? 's are' : ' is'} tied with another at the same point: statsmodels ranks ties in the order numpy's sort leaves them, which moves those curves' depths a little`);
    return ctx.note(`${parts.join('; ')}.${fb.notes && fb.notes.length ? ` ${fb.notes.join(' ')}` : ''}`);
  }

  function fdBoxView(ctx, F, fb) {
    const t = ctx.table;
    const out = [], rest = [];
    fb.outlier.forEach((o, c) => (o ? out : rest).push(c));
    const outRows = out.flatMap((c) => F.rows[c]);
    const ob = ctx.outline('Functional Boxplot', { key: 'fd:box', info: 'p:functional:box', menu: () => [
      { label: 'Select Outliers', disabled: !out.length, action: () => t.select(outRows) },
      ctx.check('Show Curves', 'fdCurves', null, false),
      ctx.check('Show Fences', 'fdFences', null, false),
    ] });
    const ink = SM.util.themeColors().text;
    const size = fdSize(ctx);
    const traces = [], specs = [];
    const add = (ct) => { const i = traces.push(ct.tr) - 1; specs.push({ trace: i, vtx: ct.vtx, x: ct.tr.x, y: ct.tr.y }); };
    const hov = (c) => `${esc(F.labels[c])}${c === fb.median ? ' (the median)' : ''}<br>depth ${fmt(fb.depth[c], { sig: 4 })}, rank ${fb.rank[c]} of ${F.n}${fb.outlier[c] ? ', outlier' : ''}`;
    traces.push(fdBand(F.x, fb.env_lo, fb.env_hi, rgba(ink, 0.12), 'Non-outlying envelope'));
    traces.push(fdBand(F.x, fb.lower, fb.upper, rgba(ink, 0.3), '50% central region'));
    if (ctx.opt('fdCurves', false)) add(curveTrace(F, rest.filter((c) => c !== fb.median), { line: { color: rgba(ink, 0.3), width: 0.8 }, name: 'The other curves' }, hov));
    if (ctx.opt('fdFences', false)) traces.push({ type: 'scatter', mode: 'lines', x: [...F.x, null, ...F.x], y: [...fb.fence_lo, null, ...fb.fence_hi], line: { color: rgba(ink, 0.75), width: 1, dash: 'dash' }, hoverinfo: 'skip', name: 'Fences' });
    add(curveTrace(F, [fb.median], { line: { color: ink, width: 2.6 }, name: esc(`Median: ${F.labels[fb.median]}`) }, hov));
    const named = size.named;
    out.slice(0, named).forEach((c, i) => add(curveTrace(F, [c], { line: { color: FD_COLORS[i % FD_COLORS.length], width: 1.6 }, name: esc(F.labels[c]) }, hov)));
    if (out.length > named) add(curveTrace(F, out.slice(named), { line: { color: rgba(SM.util.themeColors().muted, 0.9), width: 1.1, dash: 'dot' }, name: `${out.length - named} more outliers` }, hov));
    const oi = traces.push(fdOverlay()) - 1;
    const box = fdPlot(ctx, traces, F, size, { title: 'Functional boxplot' });
    linkCurves(box, F, specs, oi);
    const how = fb.method === 'BD2x' ? 'the band depth counted from its definition' : `statsmodels' banddepth, ${FD_DEPTH.find(([v]) => v === fb.method)[1]}`;
    const rule = fb.rule === 'sungenton'
      ? `a curve is an outlier where, at any point, it passes the fences: the central region's envelope widened by ${fmt(fb.wfactor)} times its range on each side (Sun and Genton's rule, as R's fda::fbplot)`
      : `a curve is an outlier where, at any point, it leaves the central region stretched ${fmt(fb.wfactor)} times about the pointwise median of its curves (statsmodels' fboxplot)`;
    const notes = [ctx.note(`The curves ordered by ${how}; the median is the deepest curve, ${F.labels[fb.median]}. The 50% central region is the envelope of the ${fb.central} deepest; ${rule}: ${out.length ? `${out.length} outlying curve${out.length > 1 ? 's' : ''}` : 'none'}. The outer band is the envelope of the curves that are not outliers.`)];
    if (fb.rule !== 'sungenton' && out.length > 0.2 * F.n) notes.push(ctx.note(`fboxplot's fences are narrow: its factor stretches the central region to ${fmt(fb.wfactor)} times its width, where Sun and Genton's add ${fmt(fb.wfactor)} times the width on each side (fboxplot's factor f is their (f − 1)/2), so ${out.length} of the ${F.n} curves are outliers here. Outlier Rule ▸ Sun and Genton, or a larger Outlier Factor (statsmodels' own example takes 2.58), flags fewer.`));
    if (fb.method === 'BD2') notes.push(ctx.note('statsmodels\' BD2 is a formula in the ranks at each point: (curves below at its lowest rank) × (curves above at its highest), which counts pairs that do not make a band around the curve; it is at least the band depth, and can order the curves differently. Band Depth (BD2), Counted counts the bands.'));
    ob.add(box, ...notes);
    if (out.length) {
      const rows = out.map((c) => ({ id: F.labels[c], depth: fb.depth[c], rank: fb.rank[c], where: fdWhere(F, fb, c), _c: c }));
      ob.add(ctx.rt({ columns: [{ key: 'id', label: F.idHead, fmt: 'text' }, { key: 'depth', label: `Depth (${FD_SHORT[fb.method]})` }, { key: 'rank', label: 'Rank', fmt: 'int' }, { key: 'where', label: 'Outside the Fences at', fmt: 'text' }], rows },
        { caption: 'Outlying Curves', key: 'fd:outliers', name: 'Outlying Curves', onRow: (row, ev) => t.select(F.rows[row._c], selectMode(ev)) }));
    }
    ob.add(ctx.code(fb.code));
    return { box, out, outRows };
  }

  function fdHdrView(ctx, F, hd) {
    const t = ctx.table;
    const out = hd && !hd.error ? hd.outlier.map((o, c) => (o ? c : -1)).filter((c) => c >= 0) : [];
    const outRows = out.flatMap((c) => F.rows[c]);
    const ob = ctx.outline('HDR Boxplot', { key: 'fd:hdr', info: 'p:functional:hdr', menu: () => [
      { label: 'Select Outliers', disabled: !out.length, action: () => t.select(outRows) },
      ctx.check('Score Plot', 'fdScores', null, true),
      { label: 'Outlier Threshold…', action: async () => {
        const v = await SM.ui.form({ title: 'Outlier Threshold', lead: 'A curve is an outlier when its density is below the (1 − threshold) quantile of the densities at the curves; statsmodels\' default is 0.95.', fields: [{ key: 'q', label: 'Threshold (0.5 to 0.999)', type: 'number', value: ctx.opt('fdThreshold', 0.95), help: 'The HDR boxplot\'s outlier contour: about a share 1 − threshold of the curves always fall outside it, so 0.95 (statsmodels\' default) flags about 5% of them and 0.99 about 1%. A number between 0.5 and 1.' }], validate: (x) => (x.q > 0.5 && x.q < 1 ? null : 'The threshold must be between 0.5 and 1') });
        if (v) ctx.set('fdThreshold', v.q);
      } },
      { label: 'Bandwidth', submenu: () => FD_BW.map(([v, l]) => ({ label: l, checked: ctx.opt('fdBw', 'normal_reference') === v, action: () => ctx.set('fdBw', v) })) },
    ] });
    if (!hd || hd.error) { ob.add(ctx.warn((hd && hd.error) || 'The HDR boxplot could not be computed.')); return { out, outRows }; }
    const tc = SM.util.themeColors();
    const ink = inkColor();
    const size = fdSize(ctx);
    const traces = [], specs = [];
    const add = (ct) => { const i = traces.push(ct.tr) - 1; specs.push({ trace: i, vtx: ct.vtx, x: ct.tr.x, y: ct.tr.y }); };
    const hov = (c) => `${esc(F.labels[c])}<br>HDR density ${fmt(hd.density[c], { sig: 4 })}${hd.outlier[c] ? ', outlier' : ''}`;
    const rest = F.rows.map((_, c) => c).filter((c) => !hd.outlier[c]);
    add(curveTrace(F, rest, { line: { color: rgba(tc.text, 0.2), width: 0.8 }, name: 'Curves' }, hov));
    if (hd.hdr90 && hd.hdr90[0]) traces.push(fdBand(F.x, hd.hdr90[1], hd.hdr90[0], rgba(ink, 0.2), '90% HDR'));
    if (hd.hdr50 && hd.hdr50[0]) traces.push(fdBand(F.x, hd.hdr50[1], hd.hdr50[0], rgba(ink, 0.42), '50% HDR'));
    traces.push({ type: 'scatter', mode: 'lines', x: F.x, y: hd.modal, line: { color: ink, width: 2.6 }, name: 'Modal curve', hovertemplate: `the modal curve<br>${esc(F.xTitle)}: %{x}<br>${esc(F.yTitle)}: %{y:.4g}<extra></extra>` });
    const named = size.named;
    out.slice(0, named).forEach((c, i) => add(curveTrace(F, [c], { line: { color: FD_COLORS[i % FD_COLORS.length], width: 1.6 }, name: esc(F.labels[c]) }, hov)));
    if (out.length > named) add(curveTrace(F, out.slice(named), { line: { color: rgba(tc.muted, 0.9), width: 1.1, dash: 'dot' }, name: `${out.length - named} more outliers` }, hov));
    const oi = traces.push(fdOverlay()) - 1;
    const box = fdPlot(ctx, traces, F, size, { title: 'HDR boxplot' });
    linkCurves(box, F, specs, oi);
    ob.add(box);
    let scores = null;
    if (ctx.opt('fdScores', true)) {
      const S = hd.scores, g = hd.grid;
      const outColor = dark() ? '#f08a80' : '#b0302a';
      // A constraint contour shades where the constraint fails: '<' shades the region above the level.
      const region = (lev, fill, name, dash) => ({ type: 'contour', x: g.x, y: g.y, z: g.z, contours: { type: 'constraint', operation: '<', value: lev }, fillcolor: fill, line: { color: rgba(ink, 0.75), width: 1, dash: dash || 'solid', smoothing: 0.8 }, hoverinfo: 'skip', showscale: false, showlegend: true, name });
      const st = [
        region(hd.levels['90'], rgba(ink, 0.14), '90% region'), region(hd.levels['50'], rgba(ink, 0.3), '50% region'),
        region(hd.levels.threshold, 'rgba(0,0,0,0)', `${fmt(100 * hd.threshold, { sig: 3 })}% contour: outliers outside`, 'dash'),
      ];
      const pts = { type: 'scatter', mode: 'markers', x: S.map((s) => s[0]), y: S.map((s) => s[1]), rows: F.long ? F.rows : F.rows.map((rs) => rs[0]),
        marker: { size: 7, color: S.map((_, c) => (hd.outlier[c] ? outColor : pointColor())), line: { width: 0 } }, name: 'Curves', showlegend: false,
        hovertext: S.map((_, c) => hov(c)), hovertemplate: '%{hovertext}<br>PC1 %{x:.4g}, PC2 %{y:.4g}<extra></extra>' };
      st.push(pts, { type: 'scatter', mode: 'markers', x: [hd.mode[0]], y: [hd.mode[1]], marker: { symbol: 'x-thin-open', size: 13, color: tc.text, line: { width: 2, color: tc.text } }, name: 'Mode: the modal curve', hovertemplate: 'the density\'s highest point: the modal curve<extra></extra>' });
      const ann = out.slice(0, 20).map((c) => ({ x: S[c][0], y: S[c][1], text: esc(F.labels[c]), showarrow: false, xanchor: 'left', xshift: 6, font: { size: 10, color: outColor } }));
      const ex = hd.explained;
      const w2 = Math.min(600, availWidth(ctx));
      const L = { xaxis: { title: { text: `PC1 score${ex ? ` (${pct(ex[0])} of the variance)` : ''}` }, zeroline: false, range: [g.x[0], g.x[g.x.length - 1]] }, yaxis: { title: { text: `PC2 score${ex ? ` (${pct(ex[1])})` : ''}` }, zeroline: false, range: [g.y[0], g.y[g.y.length - 1]] },
        margin: { l: 60, r: 12, t: 10, b: 108 }, showlegend: true, annotations: ann, legend: { orientation: 'h', x: 0, xanchor: 'left', y: 0, yanchor: 'bottom', yref: 'container' } };
      scores = ctx.plot(st, L, { width: w2, height: Math.round(w2 * 0.72) + 80, title: 'HDR score plot' });
      ob.add(el('h4', { class: 'sm-fd-sub', text: 'Score Plot' }), scores);
    }
    const bw = hd.bw || [];
    const G = hd.grid_n;
    ob.add(ctx.note(`The ${F.n} curves as points in the plane of their first two principal components (statsmodels PCA, each point along the curves standardized${hd.explained ? `; they hold ${pct(hd.explained[0])} and ${pct(hd.explained[1])} of the variance` : ''})${hd.constant ? `; ${hd.constant} point${hd.constant > 1 ? 's' : ''} where every curve has the same value ${hd.constant > 1 ? 'are' : 'is'} left out of the PCA` : ''}. A Gaussian kernel density of the scores (statsmodels KDEMultivariate, ${FD_BW.find(([v]) => v === hd.bw_method)[1].toLowerCase()} bandwidths ${fmt(bw[0], { sig: 3 })} and ${fmt(bw[1], { sig: 3 })}) gives the regions: the 50% region is where the density is above its median at the curves, the 90% region where it is above its 10th percentile (numpy's midpoint rule, as hdrboxplot). The modal curve is the curve rebuilt from the density's highest point, and each band the pointwise range of the curves rebuilt from the scores in its region, within the range of the scores; the 90% band comes from the part of its region outside the 50% one, as in hdrboxplot. A curve is an outlier when its density is below the ${fmt(100 * (1 - hd.threshold), { sig: 3 })}th percentile: ${out.length} of the ${F.n}, as about ${pct(1 - hd.threshold)} of the curves always are.`),
      ctx.note(`statsmodels' hdrboxplot searches for the ends of each band with differential evolution (7 generations) or a brute-force grid, which can fall short of them; here they are exact on a ${G} × ${G} grid of the score plane, which gives the same bands or slightly wider ones. The curves are not smoothed first, and the PCA is not robust, unlike Hyndman and Shang's HDR boxplot in R's rainbow package.`));
    if (out.length) {
      const rows = out.map((c) => ({ id: F.labels[c], dens: hd.density[c], pc1: hd.scores[c][0], pc2: hd.scores[c][1], _c: c }));
      ob.add(ctx.rt({ columns: [{ key: 'id', label: F.idHead, fmt: 'text' }, { key: 'dens', label: 'HDR Density' }, { key: 'pc1', label: 'PC1' }, { key: 'pc2', label: 'PC2' }], rows },
        { caption: 'Outlying Curves', key: 'fd:hdroutliers', name: 'HDR Outlying Curves', onRow: (row, ev) => t.select(F.rows[row._c], selectMode(ev)) }));
    }
    ob.add(ctx.code(hd.code));
    return { box, scores, out, outRows };
  }

  function fdRainbowView(ctx, F, fb) {
    const ob = ctx.outline('Rainbow Plot', { key: 'fd:rainbow', info: 'p:functional:rainbow' });
    const n = F.n;
    const q = (c) => (fb.rank[c] - 1) / Math.max(1, n - 1);
    const hov = (c) => `${esc(F.labels[c])}${c === fb.median ? ' (the median)' : ''}<br>depth ${fmt(fb.depth[c], { sig: 4 })}, rank ${fb.rank[c]} of ${n}`;
    const traces = [], specs = [];
    const add = (ct) => { const i = traces.push(ct.tr) - 1; specs.push({ trace: i, vtx: ct.vtx, x: ct.tr.x, y: ct.tr.y }); };
    const order = fb.order.slice().reverse().filter((c) => c !== fb.median);   // the least deep first: the deepest on top
    if (n <= 150) for (const c of order) add(curveTrace(F, [c], { line: { color: depthColor(q(c)), width: 1.1 }, showlegend: false }, hov));
    else {
      const bins = 40;
      const groups = Array.from({ length: bins }, () => []);
      for (const c of order) groups[Math.min(bins - 1, Math.floor(q(c) * bins))].push(c);
      for (let b = bins - 1; b >= 0; b--) if (groups[b].length) add(curveTrace(F, groups[b], { line: { color: depthColor((b + 0.5) / bins), width: 1 }, showlegend: false }, hov));
    }
    add(curveTrace(F, [fb.median], { line: { color: depthColor(0), width: 3 }, showlegend: false }, hov));
    const cs = [0, 0.25, 0.5, 0.75, 1].map((u) => [u, depthColor(u)]);
    traces.push({ type: 'scatter', mode: 'markers', x: [null], y: [null], hoverinfo: 'skip', showlegend: false,
      marker: { color: [1, n], cmin: 1, cmax: n, colorscale: cs, showscale: true, colorbar: { title: { text: 'Depth rank', side: 'right' }, thickness: 12, len: 0.8, outlinewidth: 0, tickvals: [1, n], ticktext: ['1: deepest', String(n)] } } });
    const oi = traces.push(fdOverlay()) - 1;
    const box = fdPlot(ctx, traces, F, fdSize(ctx), { legend: false, title: 'Rainbow plot' });
    linkCurves(box, F, specs, oi);
    ob.add(box, ctx.note(`Every curve coloured by its depth rank (${FD_DEPTH.find(([v]) => v === fb.method)[1]}): the deepest ${dark() ? 'brightest' : 'darkest'}, the median (${F.labels[fb.median]}) drawn thickest and on top. statsmodels' rainbowplot colours the same order with a rainbow colour map, the median in black.`), ctx.code(fb.code));
    return { box };
  }

  function fdDepthTable(ctx, F, fb, hd) {
    const t = ctx.table;
    const ob = ctx.outline('Curve Depths', { key: 'fd:table' });
    const H = hd && !hd.error ? hd : null;
    const columns = [{ key: 'id', label: F.idHead, fmt: 'text' }, { key: 'depth', label: `Depth (${FD_SHORT[fb.method]})` }, { key: 'rank', label: 'Rank', fmt: 'int' }, { key: 'out', label: 'Outlier', fmt: 'text' }];
    if (H) columns.push({ key: 'hd', label: 'HDR Density' }, { key: 'hout', label: 'HDR Outlier', fmt: 'text' }, { key: 'pc1', label: 'PC1', hidden: true }, { key: 'pc2', label: 'PC2', hidden: true });
    const rows = F.rows.map((rs, c) => ({ id: F.labels[c], depth: fb.depth[c], rank: fb.rank[c], out: fb.outlier[c] ? 'Yes' : '', hd: H ? H.density[c] : null, hout: H ? (H.outlier[c] ? 'Yes' : '') : null, pc1: H ? H.scores[c][0] : null, pc2: H ? H.scores[c][1] : null, _c: c }));
    ob.add(ctx.rt({ columns, rows }, { key: 'fd:depths', name: 'Curve Depths', maxRows: 300, onRow: (row, ev) => t.select(F.rows[row._c], selectMode(ev)) }),
      ctx.note('Click a line to select the curve\'s rows; a heading sorts. Right click for the PC scores (with the HDR Boxplot), Copy Table or Make into Data Table.'));
  }

  /* Save Columns: a value for each curve, into every row of it. */
  function fdSave(ctx, name, value, spec = {}) {
    const S = ctx._fd;
    if (!S) return;
    const rows = [], values = [];
    S.F.rows.forEach((rs, c) => { const v = value(c); for (const r of rs) { rows.push(r); values.push(v); } });
    ctx.saveColumn(name, { rows, values }, { notes: `${spec.notes || name}, from ${ctx.report.title}`, ...spec });
  }

  SM.platforms.register({
    id: 'functional', label: 'Functional Data Plot', menu: 'Graph', order: 100, info: 'p:functional',
    topics: {
      'p:functional': {
        kicker: 'Graph', title: 'Functional Data Plot',
        lead: 'Curves as data: a boxplot of whole curves, ordered by how central each is among the others (its band depth); an HDR boxplot from the density of their principal component scores; and a rainbow plot coloured by depth. statsmodels\' functional graphics: JMP (standard) has no functional boxplots, and JMP Pro\'s Functional Data Explorer is a different analysis (it fits basis functions and functional principal components).',
        sections: [
          { heading: 'Data formats', choices: [['Rows as Functions', 'Each row is a curve, the Y columns its values at the points along it. X is the number in each column\'s name (0, 2.5, week 3), or the column order when a name holds none (X Values in the red triangle).'], ['Stacked', 'A row per point: the ID names the curve, X says where along it (or the order of its rows), Y is the value. Curves measured at different X are interpolated linearly to common points over the range they all cover.']] },
          { heading: 'The red triangle', choices: [
            ['Functional Boxplot, HDR Boxplot, Rainbow Plot, Curve Depths', 'The views, each turned on or off; the functional boxplot and the table of depths are on at the start.'],
            ['Depth', 'How central each curve is: the **Modified Band Depth** (statsmodels\' default, which ties less), statsmodels\' **Band Depth (BD2)**, or **BD2, Counted** from its definition (up to 400 curves). It orders the curves of the functional boxplot, the rainbow plot and the table.'],
            ['Outlier Rule', 'How the functional boxplot\'s fences are drawn: **statsmodels** (fboxplot, the default), the central region stretched by the factor about the pointwise median of its curves; **Sun and Genton** (R\'s fda::fbplot), the region\'s envelope widened by the factor times its range.'],
            ['Outlier Factor…', 'The fences\' factor, 1.5 by default; a larger one flags fewer curves.'],
            ['X Values', 'Rows as Functions: X from the numbers in the Y columns\' names (the default), or the column order 1, 2, ….'],
            ['Select Outliers', 'Selects the rows of the functional boxplot\'s outliers.'],
            ['Save Columns', 'Depth, Depth Rank and Outlier Flag, and with the HDR Boxplot its density, outlier flag and PC scores, as new columns: each curve\'s value in every row of it.'],
          ] },
          { heading: 'Linking', text: 'A curve stands for its row, or for its ID\'s rows: click it (or its line in a table) to select them, shift-click to add. Rows selected anywhere draw their curves in orange. A curve whose rows are all hidden is not drawn; excluded rows are left out.' },
          { heading: 'Band depth', text: 'For each curve, the share of the bands between two curves of the sample that hold it: at every point (BD2), or on average over the points (MBD, which ties less). The deepest curve is the median; the n/2 deepest make the 50% central region. statsmodels computes both from the ranks at each point (Sun, Genton and Nychka\'s fast formula); for BD2 the formula counts more bands than there are, so Band Depth (BD2), Counted counts them.' },
        ],
        more: { label: 'Functional Data Plot', id: 'help-p-functional' },
      },
      'p:functional:format': {
        kicker: 'Functional Data Plot', title: 'Data Format',
        lead: 'How the table holds the curves.',
        sections: [{ choices: [['Rows as Functions', 'a row per curve; the Y columns are the points along it, X from the numbers in their names (or their order); ID, Function names the curves'], ['Stacked', 'a row per point: ID, Function names the curve (required), X, Input places the point (optional: else the order of the ID\'s rows), Y, Output is the value']] }],
        more: { label: 'Functional Data Plot', id: 'help-p-functional' },
      },
      'p:functional:box': {
        kicker: 'Functional Data Plot', title: 'Functional Boxplot',
        lead: 'Sun and Genton\'s functional boxplot as statsmodels\' fboxplot draws it: the median curve (the deepest), the 50% central region (the envelope of the deepest half of the curves), the envelope of the curves that are not outliers, and the outliers, each in its colour and listed with where it passes the fences.',
        sections: [
          { heading: 'Outliers', choices: [['statsmodels (fboxplot)', 'a curve is an outlier where, at any point, it leaves the central region stretched by the factor about the pointwise median of its curves; with the default 1.5 these fences are close to the region, and many curves pass them'], ['Sun and Genton', 'the fences are the central region\'s envelope widened by the factor times its range on each side, as R\'s fda::fbplot draws them; fboxplot\'s factor f equals their (f − 1)/2']] },
          { heading: 'The red triangle', text: 'Select Outliers selects the outlying curves\' rows. Show Curves draws the other curves thin; Show Fences draws the fences.' },
        ],
        more: { label: 'Functional Data Plot', id: 'help-p-functional' },
      },
      'p:functional:hdr': {
        kicker: 'Functional Data Plot', title: 'HDR Boxplot',
        lead: 'Hyndman and Shang\'s highest-density-region boxplot as statsmodels\' hdrboxplot computes it: each curve becomes a point, its scores on the first two principal components; a kernel density of those points gives the 50% and 90% regions and the mode; the curves rebuilt from the scores in a region make its band, the mode gives the modal curve.',
        sections: [
          { heading: 'Outliers', text: 'A curve is an outlier when its density is below the (1 − threshold) quantile of the densities at the curves: with the threshold 0.95 about 5% of the curves always are. Shape outliers, curves of an unusual form within the others\' range, show here more than in the functional boxplot.' },
          { heading: 'Differences', list: ['The ends of the bands are found exactly on a grid of the score plane, where hdrboxplot searches for them with differential evolution (or a brute-force grid), which falls short of them a little.', 'statsmodels standardizes each point before the PCA; a point where all curves are equal is left out of it here (statsmodels\' PCA fails on it).', 'R\'s rainbow package uses a robust PCA and its own bandwidths, so its regions differ.'] },
          { heading: 'Score Plot', text: 'The curves\' scores with the 50% and 90% regions and the outlier contour. The points are linked to the rows, as the curves are.' },
          { heading: 'The red triangle', choices: [
            ['Select Outliers', 'Selects the rows of the HDR boxplot\'s outlying curves.'],
            ['Score Plot', 'Shows or hides the plot of the curves\' principal component scores. On by default.'],
            ['Outlier Threshold…', 'The coverage of the outlier contour, 0.95 by default: about a share 1 − threshold of the curves fall outside it and are outliers.'],
            ['Bandwidth', 'The bandwidths of the kernel density of the scores (statsmodels\' KDEMultivariate): **Normal Reference** (the default, a rule of thumb from the scores\' spread), or found by **Cross-Validation, Likelihood** or **Cross-Validation, Least Squares**, which follow the data more closely and take longer.'],
          ] },
        ],
        more: { label: 'Functional Data Plot', id: 'help-p-functional' },
      },
      'p:functional:rainbow': {
        kicker: 'Functional Data Plot', title: 'Rainbow Plot',
        lead: 'Every curve coloured by its depth rank, the deepest darkest (brightest on a dark page) and drawn on top, the median thickest: where the centre of the curves lies, and which curves are far from it. statsmodels\' rainbowplot draws the same order with a rainbow colour map.',
        more: { label: 'Functional Data Plot', id: 'help-p-functional' },
      },
    },
    about: 'Curves as data (a row per curve, or stacked with an ID): the functional boxplot by band depth (median curve, 50% central region, envelope and outliers), the HDR boxplot from a kernel density of the principal component scores (50% and 90% regions, the modal curve, outliers, the score plot), and the rainbow plot; curves linked to their rows, depths and flags saved to the table.',
    uses: ['statsmodels.graphics.functional.banddepth (fboxplot, rainbowplot)', 'statsmodels.multivariate.pca.PCA (hdrboxplot)', 'statsmodels.nonparametric.kernel_density.KDEMultivariate (hdrboxplot)', 'statsmodels.graphics.functional._inverse_transform', 'scipy.optimize.minimize (Nelder-Mead: the mode)', 'numpy.interp (Stacked data)'],
    launch: {
      lead: 'Curves: each row a curve whose values are the Y columns (Rows as Functions), or stacked, a row per point: an ID naming the curve, an X and a Y.',
      roles: [
        { key: 'y', label: 'Y, Output', numeric: true, types: ['continuous'], hint: 'a column for each point along the curves', help: 'Rows as Functions: two or more columns, one for each point along the curves; each row is a curve. X is the number in each column\'s name when every name holds one (0, 2.5, week 3), the columns then taken in the order of those numbers; otherwise the column order (X Values in the red triangle chooses). A row with a missing value is left out.' },
        { key: 'yl', label: 'Y, Output', max: 1, numeric: true, types: ['continuous'], hint: 'the values', help: 'Stacked: the one column of values, a row for each point of a curve.' },
        { key: 'id', label: 'ID, Function', max: 1, hint: 'names the curves', help: 'Names the curves. Stacked: required, a curve for the rows of each level. Rows as Functions: optional, the curve\'s name in the tables and legends (else the table\'s label column, or the row number).' },
        { key: 'x', label: 'X, Input', max: 1, numeric: true, hint: 'optional: where along the curve (else the row order)', help: 'Stacked only: where along its curve each row\'s value lies; without it, the order of the ID\'s rows. Values at the same X of a curve are averaged; curves measured at different X are interpolated linearly to common points over the range every curve covers.' },
        { key: 'by', label: 'By', hint: 'optional', help: 'A separate Functional Data Plot for each level of the By columns; the depths and outliers are found within each group.' },
      ],
      extra(api, spec) {
        const st = { format: spec && spec.options && spec.options.format === 'long' ? 'long' : 'wide' };
        const name = SM.util.uid('fdfmt');
        const radios = [['wide', 'Rows as Functions'], ['long', 'Stacked']].map(([v, label]) => {
          const r = el('input', { type: 'radio', name, value: v, dataset: { fdformat: v } });
          r.addEventListener('change', () => { if (r.checked) { st.format = v; apply(); } });
          return { v, r, lab: el('label', { class: 'sm-fd-radio' }, r, el('span', { text: label })) };
        });
        const box = el('div', { class: 'sm-fd-launch', role: 'radiogroup', 'aria-label': 'Data Format' },
          el('h4', null, 'Data Format', infoSlot('p:functional:format')), el('div', { class: 'sm-fd-radios' }, ...radios.map((x) => x.lab)));
        const apply = () => {
          const long = st.format === 'long';
          for (const x of radios) x.r.checked = x.v === st.format;
          api.showRole('y', !long); api.showRole('yl', long); api.showRole('x', long);
          api.setRequired('y', !long); api.setRequired('yl', long); api.setRequired('id', long);
          api.message('');
        };
        apply();
        return {
          el: box, position: 'top',
          read: () => ({ roles: st.format === 'long' ? { y: [] } : { yl: [], x: [] }, options: { format: st.format } }),
          recall(saved) { const f = saved && saved.options && saved.options.format; if (f === 'wide' || f === 'long') { st.format = f; apply(); } },
          help: [['Data Format', '**Rows as Functions** (the default): each row is a curve, its values in the Y, Output columns. **Stacked**: a row for each point, an ID, Function column naming the curve, an optional X, Input and one Y, Output column. The roles change to suit the format.']],
        };
      },
      validate(s) {
        if ((s.options && s.options.format) === 'long') {
          if (!(s.roles.yl || []).length) return 'Stacked: choose the Y, Output column (the values)';
          if (!(s.roles.id || []).length) return 'Stacked: choose the ID, Function column (a curve for each level)';
          return null;
        }
        return (s.roles.y || []).length < 2 ? 'Rows as Functions: choose two or more Y, Output columns, one for each point along the curves' : null;
      },
    },
    title: () => 'Functional Data Plot',
    /* What a report computed for a By group: { fb, hd, F } (graph.fbox, graph.hdr, the curves). */
    state: (report, i = 0) => ((report && report._fdGroups) || [])[i] || null,
    triangle(ctx) {
      const S = ctx._fd || null;
      const long = ctx.opt('format', 'wide') === 'long';
      const outRows = S ? S.F.rows.filter((_, c) => S.fb.outlier[c]).flat() : [];
      const H = S && S.hd && !S.hd.error ? S.hd : null;
      const dm = ctx.opt('fdDepth', 'MBD');
      return [
        ctx.check('Functional Boxplot', 'fdBox', null, true),
        ctx.check('HDR Boxplot', 'fdHdr', null, false),
        ctx.check('Rainbow Plot', 'fdRainbow', null, false),
        ctx.check('Curve Depths', 'fdTable', null, true),
        { separator: true },
        { label: 'Depth', submenu: () => FD_DEPTH.map(([v, l]) => ({ label: l, checked: dm === v, action: () => ctx.set('fdDepth', v) })) },
        { label: 'Outlier Rule', submenu: () => FD_RULES.map(([v, l]) => ({ label: l, checked: ctx.opt('fdRule', 'statsmodels') === v, action: () => ctx.set('fdRule', v) })) },
        { label: 'Outlier Factor…', action: async () => {
          const v = await SM.ui.form({ title: 'Outlier Factor', lead: 'The factor of the functional boxplot\'s fences: statsmodels\' wfactor (1.5 by default; its own example takes 2.58), or Sun and Genton\'s factor (1.5 in R\'s fda::fbplot).', fields: [{ key: 'f', label: 'Factor (0.5 to 10)', type: 'number', value: ctx.opt('fdFactor', 1.5), help: 'How far the fences lie from the 50% central region (default 1.5). With the statsmodels rule the region is stretched this many times about the pointwise median of its curves; with Sun and Genton\'s the fences are this many times the region\'s range beyond its edges. A curve that passes a fence anywhere is an outlier, so a larger factor flags fewer curves.' }], validate: (x) => (x.f >= 0.5 && x.f <= 10 ? null : 'The factor must be between 0.5 and 10') });
          if (v) ctx.set('fdFactor', v.f);
        } },
        long ? null : { label: 'X Values', submenu: () => [['names', 'From the Column Names'], ['order', 'Column Order (1, 2, …)']].map(([v, l]) => ({ label: l, checked: ctx.opt('fdX', 'names') === v, action: () => ctx.set('fdX', v) })) },
        { separator: true },
        { label: 'Select Outliers', disabled: !outRows.length, action: () => ctx.table.select(outRows) },
        { label: 'Save Columns', disabled: !S, submenu: () => [
          { label: 'Depth', action: () => fdSave(ctx, `Depth (${FD_SHORT[S.fb.method]})`, (c) => S.fb.depth[c], { notes: `band depth, ${FD_DEPTH.find(([v]) => v === S.fb.method)[1]}` }) },
          { label: 'Depth Rank', action: () => fdSave(ctx, 'Depth Rank', (c) => S.fb.rank[c], { notes: 'depth rank, 1 the deepest curve', modelingType: 'ordinal' }) },
          { label: 'Outlier Flag', action: () => fdSave(ctx, 'Functional Outlier', (c) => (S.fb.outlier[c] ? 1 : 0), { notes: 'functional boxplot outlier (1)', modelingType: 'nominal' }) },
          { label: 'HDR Density', disabled: !H, action: () => fdSave(ctx, 'HDR Density', (c) => H.density[c], { notes: 'the kernel density at the curve\'s PC scores' }) },
          { label: 'HDR Outlier Flag', disabled: !H, action: () => fdSave(ctx, 'HDR Outlier', (c) => (H.outlier[c] ? 1 : 0), { notes: 'HDR boxplot outlier (1)', modelingType: 'nominal' }) },
          { label: 'PC Scores', disabled: !H, action: () => { fdSave(ctx, 'HDR PC1', (c) => H.scores[c][0], { notes: 'first principal component score' }); fdSave(ctx, 'HDR PC2', (c) => H.scores[c][1], { notes: 'second principal component score' }); } },
        ] },
      ];
    },
    async render(ctx) {
      const base = fdPayload(ctx);
      const fb = await ctx.call('graph.fbox', { ...base, method: ctx.opt('fdDepth', 'MBD'), wfactor: ctx.opt('fdFactor', 1.5), rule: ctx.opt('fdRule', 'statsmodels') });
      if (fb.error) { ctx.container.append(ctx.warn(fb.error)); return; }
      const F = fdCurves(ctx, fb);
      const hd = ctx.opt('fdHdr', false) ? await ctx.call('graph.hdr', { ...base, threshold: ctx.opt('fdThreshold', 0.95), bw: ctx.opt('fdBw', 'normal_reference') }) : null;
      ctx._fd = { fb, hd, F };
      // For the tests and the console: what each By group computed (state() below).
      const rep = ctx.report;
      if (rep._fdSeq !== rep.seq) { rep._fdSeq = rep.seq; rep._fdGroups = []; }
      rep._fdGroups.push(ctx._fd);
      ctx.container.append(fdDataNote(ctx, F, fb));
      const views = {};
      if (ctx.opt('fdBox', true)) views.box = fdBoxView(ctx, F, fb);
      if (hd) views.hdr = fdHdrView(ctx, F, hd);
      if (ctx.opt('fdRainbow', false)) views.rainbow = fdRainbowView(ctx, F, fb);
      if (ctx.opt('fdTable', true)) fdDepthTable(ctx, F, fb, hd);
      ctx._fd.views = views;
      ctx.container.append(ctx.note('JMP (standard) has no functional boxplots; JMP Pro\'s Functional Data Explorer is a different analysis, fitting basis functions and functional principal components. These are statsmodels\' functional graphics, drawn in the page.'));
    },
  });

  /* A simulated table of curves for the Functional Data Plot. */
  SM.io.addExample('curves', {
    label: 'Temperature curves (60 days × 24 hours)',
    about: 'Simulated: a day\'s temperature hour by hour at two sites, a daily cycle with a random level, amplitude and peak hour, and correlated noise. Six days are unusual: three much warmer or colder than the others (magnitude outliers: days 07, 24, 42) and three of another shape (a cold front in the afternoon, the warmest hour at night, an overcast day: days 14, 31, 53). Rows as Functions: the columns 0 to 23 are the hours. For Graph > Functional Data Plot.',
    make() {
      const r = SM.util.rng('curves');
      const n = 60, H = 24;
      const kind = { 6: 'heat', 23: 'cold', 41: 'warm', 13: 'front', 30: 'night', 52: 'overcast' };
      const day = [], site = [], cols = Array.from({ length: H }, () => []);
      for (let i = 0; i < n; i++) {
        const inland = i % 2 === 1, k = kind[i];
        let level = r.normal(inland ? 14 : 13, 1.1);
        let amp = Math.max(1.5, r.normal(inland ? 5.4 : 4.2, 0.6));
        let peak = 15 + r.normal(0, 0.5);
        if (k === 'heat') level += 9; else if (k === 'cold') level -= 8; else if (k === 'warm') level += 6.5;
        if (k === 'night') peak = 3;
        if (k === 'overcast') amp = 0.5;
        let e = 0;
        for (let h = 0; h < H; h++) {
          e = 0.7 * e + r.normal(0, 0.22);
          let v = level + amp * Math.cos((2 * Math.PI * (h - peak)) / 24) + e;
          if (k === 'front') v -= 7 / (1 + Math.exp(-(h - 13) / 0.7));
          cols[h].push(+v.toFixed(2));
        }
        day.push(`Day ${String(i + 1).padStart(2, '0')}`);
        site.push(inland ? 'Inland' : 'Coast');
      }
      return new SM.Table({ name: 'Temperature curves', source: 'simulated', columns: [
        { name: 'day', dataType: 'character', values: day, role: 'label' },
        { name: 'site', dataType: 'character', values: site },
        ...cols.map((v, h) => ({ name: String(h), dataType: 'numeric', values: v, notes: `temperature (°C) at hour ${h}` })),
      ] });
    },
  });

  /* ---- Legacy: Chart and Overlay Plot -------------------------------------------------------------------------- */
  /* A figure from Graph Builder's engine with a fixed state: Chart draws its
     bars, lines, points and pies with the builder's elements. */
  async function staticFigure(ctx, S, { width = 560, height = 380 } = {}) {
    const B = { ctx, S: normalize(S, ctx.table), width: () => width, height: () => height };
    return buildFigure(B);
  }

  const CHART_STATS = [['n', 'N'], ['pct', '% of Total'], ['mean', 'Mean'], ['sum', 'Sum'], ['min', 'Min'], ['max', 'Max'], ['sd', 'Std Dev'], ['se', 'Std Err'], ['median', 'Median'], ['range', 'Range']];

  SM.platforms.register({
    id: 'chart', label: 'Chart', menu: 'Graph/Legacy', order: 10, info: 'p:chart',
    topics: {
      'p:chart': {
        kicker: 'Graph > Legacy', title: 'Chart',
        lead: 'A statistic of the Y columns (or the count of rows) for each level of the categories, as bars, lines, points, needles or a pie. A second category column splits each level into side-by-side bars.',
        sections: [{ heading: 'The red triangle', choices: [
          ['Chart Type', 'Bar, Line, Point, Needle or Pie chart.'],
          ['Statistic', 'N, % of Total, Mean, Sum, Min, Max, Std Dev, Std Err, Median or Range, computed as Graph Builder computes them.'],
          ['Error Interval', 'Range, Standard Error, Standard Deviation, the 95% Confidence Interval of the mean or the Interquartile Range, on each bar or point; the first three go with the Mean.'],
          ['Horizontal', 'The categories down the side.'],
          ['Overlay', 'All the Y columns in one chart; otherwise a chart each.'],
          ['Label by Value', 'Writes each bar\'s value on it.'],
        ] }],
        more: { label: 'Chart', id: 'help-p-chart' },
      },
    },
    about: 'Bar, line, point, needle and pie charts of a statistic of the Y columns by one or two category columns, vertical or horizontal, overlaid or one per column; linked bars.',
    uses: ['statsmodels / numpy summaries (graph.summary)'],
    launch: {
      lead: 'Choose the categories and, optionally, the columns to take a statistic of (with none, the count of rows).',
      roles: [
        { key: 'y', label: 'Y, Statistics', numeric: true, types: ['continuous'], hint: 'optional: continuous', help: 'The continuous columns whose Statistic is charted for each category. Without them the chart counts rows (N, or % of Total).' },
        { key: 'x', label: 'Categories, X, Levels', min: 1, max: 2, hint: 'required: one or two', help: 'One or two columns: a bar (point, slice) for each level of the first; a second one splits each level into side-by-side bars, one for each of its levels, with a legend.' },
        { key: 'by', label: 'By', hint: 'optional', help: 'A separate chart for each level of the By columns.' },
      ],
      options: [
        { key: 'stat', label: 'Statistic', type: 'select', value: 'mean', choices: CHART_STATS, help: 'What each bar shows: N, % of Total (the level\'s share of the column\'s sum, or of the rows), Mean (the default), Sum, Min, Max, Std Dev, Std Err, Median (JMP\'s quantile) or Range. Without Y columns only N and % of Total. A Pie Chart\'s slices are in proportion to the statistic (negative values count as 0); its % of Total is the share of the sum.' },
        { key: 'kind', label: 'Chart', type: 'select', value: 'bar', choices: [['bar', 'Bar Chart'], ['line', 'Line Chart'], ['point', 'Point Chart'], ['needle', 'Needle Chart'], ['pie', 'Pie Chart']], help: '**Bar Chart** (the default), **Line Chart** (the statistics joined in the levels\' order), **Point Chart**, **Needle Chart** (a thin line for each bar) or **Pie Chart** (a slice for each level). The red triangle changes it later.' },
        { key: 'horizontal', label: 'Horizontal', type: 'check', value: false, help: 'The categories down the side and the bars across.' },
        { key: 'overlay', label: 'Overlay', type: 'check', value: true, help: 'On (the default): every Y column in one chart, their bars side by side with a legend; off: a chart for each Y column.' },
      ],
    },
    title: (spec) => ({ bar: 'Bar Chart', line: 'Line Chart', point: 'Point Chart', needle: 'Needle Chart', pie: 'Pie Chart' }[spec.options && spec.options.kind] || 'Chart'),
    triangle(ctx) {
      const kind = ctx.opt('kind', 'bar');
      return [
        { label: 'Chart Type', submenu: () => [['bar', 'Bar Chart'], ['line', 'Line Chart'], ['point', 'Point Chart'], ['needle', 'Needle Chart'], ['pie', 'Pie Chart']].map(([v, l]) => ({ label: l, checked: kind === v, action: () => ctx.set('kind', v) })) },
        { label: 'Statistic', submenu: () => CHART_STATS.map(([v, l]) => ({ label: l, checked: ctx.opt('stat', 'mean') === v, action: () => ctx.set('stat', v) })) },
        { label: 'Error Interval', submenu: () => INTERVALS.map(([v, l]) => ({ label: l, checked: ctx.opt('interval', 'none') === v, action: () => ctx.set('interval', v) })) },
        ctx.check('Horizontal', 'horizontal', null, false),
        ctx.check('Overlay', 'overlay', null, true),
        ctx.check('Label by Value', 'label', null, false),
      ];
    },
    async render(ctx) {
      const ys = ctx.roles('y'), xs = ctx.roles('x');
      let stat = ctx.opt('stat', 'mean');
      if (!ys.length && !['n', 'pct'].includes(stat)) stat = 'n';
      const kind = ctx.opt('kind', 'bar');
      const horiz = ctx.opt('horizontal', false);
      const ref = (c) => ({ id: c.id, name: c.name });
      const sets = !ys.length ? [[]] : ctx.opt('overlay', true) ? [ys] : ys.map((c) => [c]);
      // a pie's slices in proportion to the statistic; % of Total is the share of the sum (of the rows without Y)
      const element = kind === 'pie' ? { type: 'pie', summary: stat === 'pct' ? (ys.length ? 'sum' : 'n') : stat }
        : kind === 'line' ? { type: 'line', ordering: 'summarized', summary: stat, interval: ctx.opt('interval', 'none') }
          : kind === 'point' ? { type: 'points', summary: stat, interval: ctx.opt('interval', 'none') }
            : { type: 'bar', barStyle: kind === 'needle' ? 'needle' : 'side', summary: stat, interval: ctx.opt('interval', 'none'), label: ctx.opt('label', false) ? 'value' : 'none' };
      const codes = [];
      for (const set of sets) {
        const fac = [ref(xs[0])], val = set.map(ref);
        const zones = horiz ? { y: fac, x: val } : { x: fac, y: val };
        if (xs[1]) zones.overlay = [ref(xs[1])];
        const S = { zones, elements: [element], auto: false, xMode: 'merge', yMode: 'merge', show: { title: false, legend: true, xTitle: true, yTitle: true } };
        const w = Math.min(760, availWidth(ctx));
        const fig = await staticFigure(ctx, S, { width: w, height: Math.round(Math.min(460, w * 0.62)) });
        codes.push(...fig.codes.filter((c) => !codes.includes(c)));
        const parent = sets.length > 1 ? ctx.outline(set[0].name, { key: `chart:${set[0].id}` }) : null;
        const host = parent ? parent.body : ctx.container;
        if (fig.empty) { host.append(ctx.note('Nothing to chart.')); continue; }
        const box = ctx.plot(fig.traces, fig.layout, { width: fig.width, height: fig.height, title: `${ELEMENT[element.type].label} chart` });
        link(box, fig.links);
        host.append(box, ...fig.notes.map((n) => ctx.note(n)));
      }
      const lab = CHART_STATS.find(([v]) => v === stat)[1];
      ctx.container.append(ctx.note(`${lab}${ys.length ? ` of ${ys.map((c) => c.name).join(', ')}` : ' of rows'} for each level of ${xs.map((c) => c.name).join(' and ')}. Click a ${kind === 'pie' ? 'slice' : kind === 'bar' || kind === 'needle' ? 'bar' : 'point'} to select its rows.`));
      if (codes.length) ctx.container.append(ctx.code(codes.join('\n\n# ----\n')));
    },
  });

  SM.platforms.register({
    id: 'overlay', label: 'Overlay Plot', menu: 'Graph/Legacy', order: 20, info: 'p:overlay',
    topics: {
      'p:overlay': {
        kicker: 'Graph > Legacy', title: 'Overlay Plot',
        lead: 'Several Y columns against one X (or against the row order) in one graph, each with its own markers and line, on the left or the right axis; or each on its own axis, stacked.',
        sections: [{ heading: 'The red triangle', choices: [
          ['Overlay Y\'s', 'On (the default): every Y column in one graph; off: each on its own axis, stacked, sharing X.'],
          ['Sort X', 'On (the default): the points are joined in the order of X; off: in the table\'s row order.'],
          ['Connect Thru Missing', 'A line goes on across a row whose Y is missing; off, it breaks there.'],
          ['Y Options', 'For each Y column: **Left Scale** or **Right Scale** (the axis on the right, with Overlay Y\'s), **Show Points**, **Connect Points** (the line), **Needle** (a line from 0 to each point) and **Step** (a step from each point to the next).'],
        ] }],
        more: { label: 'Overlay Plot', id: 'help-p-overlay' },
      },
    },
    about: 'Several Y columns against one X (or the row order), points and lines, on a left and a right axis or on separate axes; linked point by point.',
    uses: ['plotly (drawing only)'],
    launch: {
      lead: 'Choose the Y columns and, optionally, the X to plot them against.',
      roles: [
        { key: 'y', label: 'Y', min: 1, numeric: true, types: ['continuous'], hint: 'required: one or more', help: 'The continuous columns to plot, each with its own colour, markers and line.' },
        { key: 'x', label: 'X', max: 1, numeric: true, hint: 'optional: else the row order', help: 'A numeric column to plot them against; without it, the row number. Rows with a missing X are left out.' },
        { key: 'group', label: 'Grouping', max: 1, types: ['ordinal', 'nominal'], hint: 'optional', help: 'A categorical column: a line (and a colour) for each of its levels, for each Y column.' },
        { key: 'by', label: 'By', hint: 'optional', help: 'A separate graph for each level of the By columns.' },
      ],
    },
    title: () => 'Overlay Plot',
    triangle(ctx) {
      const ys = ctx.roles('y');
      return [
        ctx.check('Overlay Y\'s', 'overlayY', null, true),
        ctx.check('Sort X', 'sortX', null, true),
        ctx.check('Connect Thru Missing', 'thru', null, false),
        { label: 'Y Options', submenu: () => ys.map((c) => ({ label: c.name, submenu: () => [
          { label: 'Left Scale', checked: ctx.opt('right', false, c.id) !== true, action: () => ctx.set('right', false, c.id) },
          { label: 'Right Scale', checked: ctx.opt('right', false, c.id) === true, action: () => ctx.set('right', true, c.id) },
          ctx.check('Show Points', 'points', c.id, true), ctx.check('Connect Points', 'connect', c.id, true),
          ctx.check('Needle', 'needle', c.id, false), ctx.check('Step', 'step', c.id, false),
        ] })) },
      ];
    },
    async render(ctx) {
      const t = ctx.table;
      const ys = ctx.roles('y'), X = ctx.role('x');
      const G = colorer(t, ctx.role('group'), ctx.rows);
      const overlayY = ctx.opt('overlayY', true), sortX = ctx.opt('sortX', true), thru = ctx.opt('thru', false);
      const xOf = (r) => (X ? X.values[r] : r + 1);
      const traces = [];
      const n = ys.length;
      const layout = { margin: { l: 60, r: 60, t: 10, b: 46 }, showlegend: n > 1 || !!G, legend: { x: 1.08, y: 1 } };
      let anyRight = false;
      ys.forEach((c, i) => {
        const sc = c.id;
        const right = overlayY && ctx.opt('right', false, sc) === true;
        anyRight = anyRight || right;
        const xa = overlayY ? 'x' : (i === 0 ? 'x' : `x${i + 1}`);
        const ya = overlayY ? (right ? 'y2' : 'y') : (i === 0 ? 'y' : `y${i + 1}`);
        let rows = ctx.rows.filter((r) => Number.isFinite(xOf(r)) && (thru ? Number.isFinite(c.values[r]) : true));
        if (sortX) rows = rows.slice().sort((a, b) => xOf(a) - xOf(b) || a - b);
        const groups = G ? G.labels.map((_, g) => rows.filter((r) => G.index(r) === g)) : [rows];
        groups.forEach((rs, g) => {
          if (!rs.length) return;
          const color = G ? PALETTE[g % PALETTE.length] : PALETTE[i % PALETTE.length];
          const pts = ctx.opt('points', true, sc), con = ctx.opt('connect', true, sc);
          const yv = rs.map((r) => (Number.isFinite(c.values[r]) ? c.values[r] : null));
          traces.push({ type: 'scatter', mode: [pts ? 'markers' : '', con ? 'lines' : ''].filter(Boolean).join('+') || 'markers', x: rs.map(xOf), y: yv, rows: rs, xaxis: xa, yaxis: ya,
            line: { color, width: 1.5, shape: ctx.opt('step', false, sc) ? 'hv' : 'linear' }, marker: { color, size: 5 }, connectgaps: thru,
            name: esc(G ? `${c.name}, ${G.labels[g]}` : c.name), hovertext: rs.map((r) => rowHover(t, r, [X, c, G ? G.col : null])), hovertemplate: '%{hovertext}<extra></extra>' });
          if (ctx.opt('needle', false, sc)) {
            const nx = [], ny = [];
            rs.forEach((r, k) => { if (yv[k] != null) { nx.push(xOf(r), xOf(r), null); ny.push(0, yv[k], null); } });
            traces.push({ type: 'scatter', mode: 'lines', x: nx, y: ny, xaxis: xa, yaxis: ya, line: { color: rgba(color, 0.6), width: 1 }, hoverinfo: 'skip', showlegend: false });
          }
        });
        if (!overlayY) {
          const kx = i === 0 ? 'xaxis' : `xaxis${i + 1}`, ky = i === 0 ? 'yaxis' : `yaxis${i + 1}`;
          const top = 1 - i / n, bot = 1 - (i + 1) / n + (i < n - 1 ? 0.04 : 0);
          layout[kx] = { anchor: ya, matches: i === 0 ? undefined : 'x', showticklabels: i === n - 1, title: i === n - 1 ? { text: esc(X ? X.name : 'Row') } : undefined };
          layout[ky] = { domain: [bot, top], anchor: xa, title: { text: esc(c.name) } };
        }
      });
      if (overlayY) {
        const left = ys.filter((c) => ctx.opt('right', false, c.id) !== true), right = ys.filter((c) => ctx.opt('right', false, c.id) === true);
        layout.xaxis = { title: { text: esc(X ? X.name : 'Row') } };
        layout.yaxis = { title: { text: esc(left.map((c) => c.name).join(', ')) } };
        if (anyRight) layout.yaxis2 = { overlaying: 'y', side: 'right', title: { text: esc(right.map((c) => c.name).join(', ')) }, showgrid: false, zeroline: false };
      }
      const w = Math.min(760, availWidth(ctx)), h = overlayY ? Math.round(w * 0.6) : clamp(160 * n + 60, 260, 900);
      ctx.container.append(ctx.plot(traces, layout, { width: w, height: h, title: 'Overlay Plot' }),
        ctx.note(`${ys.map((c) => c.name).join(', ')} against ${X ? X.name : 'the row order'}${sortX ? ', connected in the order of X' : ', connected in row order'}.`));
    },
  });

  /* ---- END OF PART 4 ---- */
}(typeof self !== 'undefined' ? self : this));
