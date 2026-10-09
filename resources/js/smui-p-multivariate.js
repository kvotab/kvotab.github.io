/* ==========================================================================
   SMUI.HTML: ANALYZE > MULTIVARIATE METHODS, CLUSTERING, SCREENING

   Multivariate Methods: Multivariate (correlations and their relatives, the
   scatterplot matrix, outlier distances, item reliability), Principal
   Components, Discriminant, Multiple Correspondence Analysis, Factor
   Analysis, Multidimensional Scaling. Clustering: Hierarchical Cluster,
   K Means Cluster. Screening: Test Many Responses, Explore Outliers. The
   numbers are resources/py/smui/multivariate.py's (statsmodels, scipy,
   numpy); this file draws them the way JMP does. Graphs whose points are
   rows carry `rows`, so they link to the table.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt, PALETTE } = SM.util;

  /* ---- shared pieces ------------------------------------------------------ */
  const dark = () => SM.util.themeColors().dark;
  const pal = (k) => PALETTE[((k % PALETTE.length) + PALETTE.length) % PALETTE.length];
  const RED = '#c0392b';
  /* Text from the table inside a Plotly hover template: only %{ is special there. */
  const tpl = (text) => String(text).replace(/%\{/g, '%\u200b{');
  const chi2Inv2 = (level) => -2 * Math.log(1 - level);           // chi-square quantile, 2 df
  const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
  /* WebGL scatter for many points, where the browser has WebGL: without it
     Plotly draws a notice instead of the graph. */
  let glOK = null;
  function scatterType(nPoints, limit) {
    if (nPoints <= limit) return 'scatter';
    if (glOK === null) {
      try { const cv = document.createElement('canvas'); glOK = !!(cv.getContext('webgl2') || cv.getContext('webgl')); } catch (e) { glOK = false; }
    }
    return glOK ? 'scattergl' : 'scatter';
  }

  /* A plot width that fits the work area (phone width), at least 280. */
  function fitW(w) {
    const v = typeof document !== 'undefined' ? document.querySelector('.sm-group.is-focused > .sm-views') || document.querySelector('.sm-views') : null;
    const avail = v && v.clientWidth ? v.clientWidth - 64 : w;
    return Math.round(Math.max(Math.min(w, 280), Math.min(w, avail)));
  }
  const dropped = (n) => (n > 0 ? `${plural(n, 'row')} with a missing value left out` : '');

  /* Blue (-1) to a neutral middle to red (+1), as JMP's colour maps. */
  function diverging(v) {
    if (v == null || !Number.isFinite(v)) return null;
    const d = dark();
    const neg = d ? [91, 156, 240] : [47, 110, 199];
    const mid = d ? [58, 52, 49] : [246, 243, 240];
    const pos = d ? [232, 96, 79] : [192, 57, 43];
    const t = Math.max(-1, Math.min(1, v));
    const to = t < 0 ? neg : pos;
    const u = Math.abs(t);
    const c = mid.map((x, i) => Math.round(x + u * (to[i] - x)));
    return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
  }
  const divergingScale = () => (dark() ? [[0, '#5b9cf0'], [0.5, '#3a3431'], [1, '#e8604f']] : [[0, '#2f6ec7'], [0.5, '#f6f3f0'], [1, '#c0392b']]);
  function ink(rgb) {
    const m = /rgb\((\d+), (\d+), (\d+)\)/.exec(rgb || '');
    if (!m) return null;
    const l = (0.299 * m[1] + 0.587 * m[2] + 0.114 * m[3]) / 255;
    return l > 0.55 ? '#1d1712' : '#f7f1ea';
  }

  /* Run fn(tr, row, k) on the rows of a report table now and after every
     redraw (a sort): colour maps and bars in cells. */
  function decorate(tbl, fn) {
    const body = tbl.tBodies[0];
    const apply = () => {
      const rows = tbl._rt.rows;
      [...body.rows].forEach((tr, k) => { if (k < rows.length && tr.cells.length > 1) fn(tr, rows[k], k); });
    };
    apply();
    if (typeof MutationObserver !== 'undefined') new MutationObserver(apply).observe(body, { childList: true });
    return tbl;
  }

  /* A bar in a cell: from the middle for [-1, 1], from the left for [0, max]. */
  function cellBar(td, v, lo, hi, color) {
    td.querySelector('.mv-barbox')?.remove();
    if (v == null || !Number.isFinite(v)) return;
    const box = el('span', { class: `mv-barbox${lo < 0 ? ' is-centered' : ''}`, 'aria-hidden': 'true' });
    const frac = Math.max(0, Math.min(1, lo < 0 ? Math.abs(v) / Math.max(Math.abs(lo), hi) : (v - lo) / (hi - lo || 1)));
    const bar = el('span', { class: 'mv-bar' });
    if (lo < 0) {
      bar.style.width = `${50 * frac}%`;
      bar.style.left = v >= 0 ? '50%' : `${50 - 50 * frac}%`;
    } else { bar.style.width = `${100 * frac}%`; bar.style.left = '0'; }
    if (color) bar.style.background = color;
    box.append(bar);
    td.append(box);
  }

  /* A matrix as a report table, row names in the first column. */
  function matrixTable(ctx, names, M, { fmtKey = 'num', colors = null, caption = null, blankDiag = false, digits = null, rowNames = null } = {}) {
    const columns = [{ key: '_v', label: '', fmt: 'text' }, ...names.map((n, j) => ({ key: `c${j}`, label: n, fmt: fmtKey, digits: digits ?? undefined }))];
    const rows = (rowNames || names).map((n, i) => {
      const r = { _v: n };
      names.forEach((_, j) => { r[`c${j}`] = blankDiag && i === j ? null : M[i][j]; });
      return r;
    });
    const tbl = ctx.rt({ columns, rows, caption }, { sortable: false });
    if (colors) {
      decorate(tbl, (tr, r, i) => {
        [...tr.cells].forEach((td, j) => {
          if (j === 0) return;
          const v = M[i][j - 1];
          const c = blankDiag && i === j - 1 ? null : colors(v, i, j - 1);
          td.classList.toggle('mv-cm', !!c);
          td.style.backgroundColor = c || '';
          td.style.color = c ? ink(c) : '';
        });
      });
    }
    return tbl;
  }

  function rowLabels(ctx, rows) {
    const lab = ctx.role('label') || (ctx.table ? ctx.table.labelColumn() : null);
    return rows.map((r) => (lab && !SM.table.isMissing(lab.values[r]) ? `${SM.grid.cellText(lab, lab.values[r])} (row ${r + 1})` : `row ${r + 1}`));
  }

  /* Points of a bivariate normal ellipse: means, standard deviations, the
     correlation and the coverage, or a 2 x 2 covariance matrix. */
  function ellipse(mx, my, sx, sy, r, level) {
    const c = Math.sqrt(chi2Inv2(level));
    const xs = [], ys = [];
    const rr = Math.max(-0.999999, Math.min(0.999999, r || 0));
    for (let k = 0; k <= 72; k++) {
      const t = (2 * Math.PI * k) / 72;
      const u = Math.cos(t), v = Math.sin(t);
      xs.push(mx + c * sx * u);
      ys.push(my + c * sy * (rr * u + Math.sqrt(1 - rr * rr) * v));
    }
    return { x: xs, y: ys };
  }
  function ellipseCov(mx, my, cov, level) {
    const sx = Math.sqrt(Math.max(cov[0][0], 0)), sy = Math.sqrt(Math.max(cov[1][1], 0));
    return ellipse(mx, my, sx, sy, sx > 0 && sy > 0 ? cov[0][1] / (sx * sy) : 0, level);
  }

  function pairStats(xs, ys) {
    const n = xs.length;
    let mx = 0, my = 0;
    for (let k = 0; k < n; k++) { mx += xs[k]; my += ys[k]; }
    mx /= n; my /= n;
    let sxx = 0, syy = 0, sxy = 0;
    for (let k = 0; k < n; k++) { const a = xs[k] - mx, b = ys[k] - my; sxx += a * a; syy += b * b; sxy += a * b; }
    const sx = Math.sqrt(sxx / (n - 1)), sy = Math.sqrt(syy / (n - 1));
    return { n, mx, my, sx, sy, r: sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : NaN };
  }

  /* The values of a numeric column for rows, and which rows have one. */
  function colValues(col, rows) {
    const v = [], rs = [];
    for (const r of rows) { const x = col.values[r]; if (typeof x === 'number' && Number.isFinite(x)) { v.push(x); rs.push(r); } }
    return { v, rows: rs };
  }

  function range(vals, pad = 0.06) {
    let lo = Infinity, hi = -Infinity;
    for (const x of vals) if (x != null && Number.isFinite(x)) { if (x < lo) lo = x; if (x > hi) hi = x; }
    if (!(lo <= hi)) return [0, 1];
    const d = hi - lo || Math.abs(hi) || 1;
    return [lo - pad * d, hi + pad * d];
  }

  /* A plot of one value per row against the row number (outlier distances),
     linked to the table, with an optional limit line. */
  function rowPlot(ctx, { rows, y, limit = null, limitLabel = 'UCL', ytitle, title, width = 560, height = 250, name = 'distance' }) {
    const x = rows.map((r) => r + 1);
    const text = rowLabels(ctx, rows);
    const traces = [{ type: 'scatter', mode: 'markers', x, y, rows, name, hovertext: text, hovertemplate: '%{hovertext}<br>%{y:.4g}<extra></extra>', marker: { size: 5 } }];
    const shapes = [], annotations = [];
    if (limit != null && Number.isFinite(limit)) {
      shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: limit, y1: limit, line: { color: RED, width: 1.2, dash: 'dash' } });
      annotations.push({ xref: 'paper', x: 1, y: limit, text: `${limitLabel} ${fmt(limit, { sig: 5 })}`, showarrow: false, xanchor: 'right', yanchor: 'bottom', font: { size: 10, color: RED } });
    }
    return ctx.plot(traces, { xaxis: { title: { text: 'Row Number' } }, yaxis: { title: { text: ytitle }, rangemode: 'tozero' }, shapes, annotations }, { width, height, title });
  }

  /* A few controls in a report (selects, numbers, buttons): DOM only. */
  function control(label, input) { return el('label', { class: 'mv-control' }, el('span', { text: label }), input); }
  function selectEl(value, choices, onChange, aria) {
    const s = el('select', { 'aria-label': aria || null }, ...choices.map(([v, l]) => el('option', { value: String(v), text: l, selected: String(v) === String(value) ? true : null })));
    s.addEventListener('change', () => onChange(s.value));
    return s;
  }
  function numberEl(value, onChange, { size = 5, aria = null } = {}) {
    const i = el('input', { type: 'text', inputmode: 'decimal', size, 'aria-label': aria });
    i.value = value == null ? '' : String(value);
    const go = () => { const t = i.value.trim().replace(',', '.'); const x = t === '' ? null : Number(t); if (x === null || Number.isFinite(x)) onChange(x); };
    i.addEventListener('change', go);
    i.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); go(); } });
    return i;
  }
  function button(label, onClick, cls = '') {
    const b = el('button', { type: 'button', class: `sm-btn small ${cls}`.trim(), text: label });
    b.addEventListener('click', onClick);
    return b;
  }
  const controls = (...nodes) => el('div', { class: 'mv-controls' }, ...nodes);

  const idsOf = (ctx, key) => ((ctx.spec.roles && ctx.spec.roles[key]) || []).slice();

  /* ---- saved columns ----------------------------------------------------------
     A backend save call (pca.save, kmeans.save, discriminant.save, ...) returns
     { columns: [{ name, formula | rows + values, modelingType, valueOrder, notes }] }:
     a formula is a live formula column (ctx.saveFormula), computed for every
     row whose columns are present, excluded rows too; values go to the rows
     named. A formula may refer to a column saved before it in the same batch
     as {{col:j}}: the page writes that column's name as the table has it (a
     name already taken gets a number). Returns the columns made. */
  const colRef = (c) => `:"${String(c.name).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
  function saveBatch(ctx, res) {
    if (!res || res.error) { SM.ui.toast((res && res.error) || 'Nothing to save', { error: true }); return []; }
    const made = [];
    for (const c of res.columns || []) {
      const spec = { notes: c.notes };
      if (c.modelingType) spec.modelingType = c.modelingType;
      if (c.valueOrder) spec.valueOrder = c.valueOrder.slice();
      let col = null;
      try {
        if (c.formula != null) col = ctx.saveFormula(c.name, c.formula.replace(/\{\{col:(\d+)\}\}/g, (_, j) => (made[+j] ? colRef(made[+j]) : '.')), spec);
        else col = ctx.saveColumn(c.name, { rows: c.rows, values: c.values }, spec);
      } catch (e) { SM.ui.toast(`${c.name}: ${e.message || e}`, { error: true }); break; }
      if (!col) break;   // a headless report saves nothing
      made.push(col);
    }
    return made;
  }
  SM.multivariate = Object.freeze({ saveBatch });   // Normal Mixtures' Save Mixture Formulas uses it

  // a save call's failure (a thrown error, or an error in its result) as a toast
  async function saveFrom(ctx, fn, payload) {
    try { return saveBatch(ctx, await mcall(ctx, fn, payload)); } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); return []; }
  }

  /* ---- the graphs as matplotlib code ------------------------------------------
     Under each graph, Python that draws it with matplotlib from a CSV export of
     the table (the notebook runs it): the report's rows, the numbers computed as
     the report computes them, the light theme's colours, the graph's size at 100
     pixels an inch. The backend writes the code of the graphs whose numbers it
     makes (the calls send the By group, `where`, for the code's rows); the
     scatterplot matrix's is written here, as the page chose its bins. */
  const J = JSON.stringify;
  const pyNum = (v) => (Number.isFinite(v) ? String(v) : Number.isNaN(v) ? 'float("nan")' : v > 0 ? 'float("inf")' : '-float("inf")');
  const pyLit = (v) => (typeof v === 'number' ? pyNum(v) : J(String(v)));
  const inches = (px) => String(Math.round(px) / 100);
  const PAPER = { base: '#2f6690', bar: '#8fa9c2', text: '#352921', muted: '#786b5d' };
  const mcall = (ctx, fn, payload) => ctx.call(fn, { ...payload, where: ctx.where || [] });
  // A graph with its code block under it, as one item of a row.
  const withCode = (graph, code) => (code ? el('div', { class: 'mv-plotcode' }, graph, code) : graph);
  // A choice of the report written into the backend's code, on the line the backend marks for it
  // (so that the choice needs no new call: Color Clusters, Biplot Rays).
  const withChoice = (code, line, value) => (code ? code.replace(line, value) : code);
  // The column that names the rows (the Label role, else the table's label column).
  // The lines the backend marks for those choices (multivariate.py's HC_COLOR and KM_RAYS).
  const HC_COLOR = 'color_clusters = False   # Color Clusters';
  const KM_RAYS = 'show_rays = True   # Biplot Rays';
  const labelName = (ctx) => { const c = ctx.role('label') || (ctx.table ? ctx.table.labelColumn() : null); return c ? c.name : null; };

  // The By group's rows (as the backend's code has them), and those of it the report leaves out.
  function keepLines(ctx) {
    const t = ctx.table, where = ctx.where || [];
    const L = where.map((w) => `df = df[df[${J(w.column)}] == ${pyLit(w.value)}]   # only the rows where ${SM.util.oneLine(`${w.column} is ${t.col(w.column) ? SM.grid.cellText(t.col(w.column), w.value) : w.value}`)}`);
    const cols = where.map((w) => t.col(w.column));
    const keep = new Set(ctx.rows), drop = [];
    for (let r = 0; r < t.nrows; r++) if (!keep.has(r) && where.every((w, k) => cols[k] && cols[k].values[r] === w.value)) drop.push(r);
    if (drop.length) L.push(`df = df.drop(index=[${drop.join(', ')}])   # the rows the report leaves out`);
    return L;
  }

  function levelOptions(ctx) {
    return [0.01, 0.05, 0.1, 0.5].map((a) => ({ label: String(a), checked: Math.abs(ctx.alpha - a) < 1e-12, action: () => ctx.set('alpha', a) }))
      .concat([{ label: 'Other…', action: async () => { const v = await SM.ui.form({ title: 'Set α Level', fields: [{ key: 'a', label: 'α (for the confidence intervals and tests)', type: 'number', value: ctx.alpha,
        help: 'The significance level: the confidence intervals are 100(1 − α)%, and the tests, the outlier limits and the false discovery rate use it. Between 0 and 1; 0.05 by default.' }] }); if (v && v.a > 0 && v.a < 1) ctx.set('alpha', v.a); } }]);
  }

  /* The launch roles several platforms share, and what they are for. */
  const BY_HELP = 'A separate report for each level of the By column (with several columns, each combination of their levels). Rows with a missing By value are left out.';
  const LABEL_HELP = 'A column whose values name the rows in the hover text of the graphs; without it the table\'s label column, else the row number.';

  /* ======================================================================
     MULTIVARIATE
     ====================================================================== */
  const NONPAR = [['spearman', "Spearman's ρ", 'Spearman ρ', 'Prob>|ρ|'], ['kendall', "Kendall's τ", 'Kendall τb', 'Prob>|τb|'], ['hoeffding', "Hoeffding's D", "Hoeffding's D", 'Prob>D']];

  async function mvRender(ctx) {
    const cols = ctx.roles('y');
    const names = cols.map((c) => c.name);
    const o = (k, d) => ctx.opt(k, d);
    const payload = { columns: names, weight: ctx.name('weight'), freq: ctx.name('freq'), method: o('method', 'rowwise'), alpha: ctx.alpha };
    const res = await mcall(ctx, 'multivariate.fit', payload);
    const box = ctx.container;
    if (res.error) { box.append(ctx.warn(res.error)); return; }
    const lv = fmt(100 * (1 - ctx.alpha));
    box.append(ctx.note(`Variance estimation: ${res.method}. ${res.method === 'Row-wise' ? `${fmt(res.n)} observations${res.n_missing_rows ? `; ${dropped(res.n_missing_rows)}` : ''}.` : 'Each pair on the rows where both are present.'}`));
    const cmap = o('cmCells', false) ? (v) => diverging(v) : null;
    if (o('corr', true)) {
      const ob = ctx.outline('Correlations', { key: 'corr', menu: () => [ctx.check('Color Cells', 'cmCells', null, false)] });
      ob.add(matrixTable(ctx, names, res.corr, { colors: cmap, digits: 4 }), ctx.code(res.code));
      if (res.singular) ob.add(ctx.warn(res.singular));
    }
    if (o('corrProb', false)) {
      const ob = ctx.outline('Correlation Probability', { key: 'corrp' });
      ob.add(matrixTable(ctx, names, res.p, { fmtKey: 'p', blankDiag: true }), ctx.note(res.method === 'Pairwise' ? 'Each p-value from a t test with the pair\'s count − 2 degrees of freedom.' : `t tests of zero correlation with n − 2 = ${fmt(res.n - 2)} degrees of freedom.`));
    }
    if (o('ci', false)) {
      const ob = ctx.outline('CI of Correlation', { key: 'ci' });
      const rows = [];
      for (let i = 0; i < names.length; i++) for (let j = i + 1; j < names.length; j++) rows.push({ v: names[j], by: names[i], r: res.corr[i][j], lo: res.lower[i][j], hi: res.upper[i][j] });
      ob.add(ctx.rt({ columns: [{ key: 'v', label: 'Variable', fmt: 'text' }, { key: 'by', label: 'by Variable', fmt: 'text' }, { key: 'r', label: 'Correlation', digits: 4 }, { key: 'lo', label: `Lower ${lv}%`, digits: 4 }, { key: 'hi', label: `Upper ${lv}%`, digits: 4 }], rows }),
        ctx.note('Fisher\'s z transformation: tanh(atanh(r) ± z(1 − α/2)/√(n − 3)).'));
    }
    if (o('inverse', false)) {
      const ob = ctx.outline('Inverse Corr', { key: 'inv' });
      if (res.inv) ob.add(matrixTable(ctx, names, res.inv, { digits: 4 }), ctx.note('The diagonal is 1/(1 − R²) of each column regressed on the others: its variance inflation factor.'));
      else ob.add(ctx.warn(res.singular));
    }
    if (o('partial', false)) {
      const ob = ctx.outline('Partial Corr', { key: 'partial', menu: () => [ctx.check('Partial Correlation Probability', 'partialP', null, false)] });
      if (res.partial) {
        ob.add(matrixTable(ctx, names, res.partial, { colors: cmap, digits: 4 }), ctx.note('The correlation of two columns adjusted for all the others: the negative of the inverse correlation matrix scaled to a unit diagonal.'));
        if (o('partialP', false)) ob.add(matrixTable(ctx, names, res.partial_p, { fmtKey: 'p', blankDiag: true, caption: 'Partial Correlation Probability' }), ctx.note(`t tests with n − p = ${fmt(res.partial_df)} degrees of freedom.`));
      } else ob.add(ctx.warn(res.singular));
    }
    if (o('cov', false)) ctx.outline('Covariance Matrix', { key: 'cov' }).add(matrixTable(ctx, names, res.cov));
    if (o('pairwise', false)) pairwiseOutline(ctx, res, lv);
    if (o('simpleUni', false) || o('simpleMulti', false)) {
      const ob = ctx.outline('Simple Statistics', { key: 'simple' });
      const cols6 = [{ key: 'column', label: 'Column', fmt: 'text' }, { key: 'n', label: 'N', fmt: 'int' }, { key: 'mean', label: 'Mean' }, { key: 'sd', label: 'Std Dev' }, { key: 'sum', label: 'Sum' }, { key: 'min', label: 'Minimum' }, { key: 'max', label: 'Maximum' }];
      if (o('simpleUni', false)) ob.add(ctx.rt({ columns: cols6, rows: res.uni, caption: 'Univariate Simple Statistics' }, { sortable: false }));
      if (o('simpleMulti', false)) ob.add(ctx.rt({ columns: cols6, rows: res.multi, caption: 'Multivariate Simple Statistics' }, { sortable: false }), ctx.note('On the rows with no missing value in any of the columns.'));
    }
    for (const [key, label, vlab, plab] of NONPAR) {
      if (!o(`np:${key}`, false)) continue;
      const r = await mcall(ctx, 'multivariate.nonparametric', { columns: names, measure: key, weight: ctx.name('weight'), freq: ctx.name('freq') });
      const ob = ctx.outline(`Nonparametric: ${label}`, { key: `np:${key}`, info: key === 'hoeffding' ? 'mv:hoeffding' : null, menu: () => [{ label: 'Remove', action: () => ctx.set(`np:${key}`, false) }] });
      const tbl = ctx.rt({ columns: [{ key: 'var', label: 'Variable', fmt: 'text' }, { key: 'by', label: 'by Variable', fmt: 'text' }, { key: 'value', label: vlab, digits: 4 }, { key: 'p', label: plab, fmt: 'p' }, { key: 'count', label: 'Count', fmt: 'int', hidden: true }, { key: 'bar', label: key === 'hoeffding' ? '0 .2 .4 .6 .8' : '−.8 −.4 0 .4 .8', fmt: 'text' }], rows: r.pairs.map((x) => ({ ...x, bar: '' })) });
      decorate(tbl, (tr, row) => { const td = tr.cells[tr.cells.length - 1]; td.classList.add('mv-barcell'); cellBar(td, row.value, key === 'hoeffding' ? 0 : -1, 1, row.value < 0 ? '#2f6ec7' : RED); });
      ob.add(tbl, ctx.note({ spearman: 'The correlation of the ranks (ties averaged); p from the t approximation with n − 2 df (scipy.stats.spearmanr).', kendall: 'τb from concordant and discordant pairs with the correction for ties; p from the normal approximation (scipy.stats.kendalltau).', hoeffding: 'D ranges from −0.5 to 1; large values mean dependence of any kind. Computed as SAS and JMP define it (30 × Hoeffding\'s U statistic); p from the Blum-Kiefer-Rosenblatt limit law of (n − 1)π⁴D/60 + π⁴/72.' }[key]), ctx.code(r.code));
    }
    if (o('dcor', false)) await distanceOutline(ctx, names);
    if (o('splom', true)) splomOutline(ctx, cols);
    if (o('cmCorr', false) || o('cmP', false) || o('cmCluster', false)) await colorMaps(ctx, names, res);
    if (o('mahal', false) || o('jack', false) || o('t2', false)) await outlierOutlines(ctx, names);
    if (o('alpha:raw', false) || o('alpha:std', false)) await reliabilityOutline(ctx, names);
    if (o('icc', false)) await iccOutline(ctx, names);
    if (o('kendallw', false)) await kendallOutline(ctx, names);
  }

  /* ---- distance correlation (statsmodels dist_dependence_measures; not in
     JMP): 0 only for independence, whatever the form of the dependence ---- */
  async function distanceOutline(ctx, names) {
    const o = (k, d) => ctx.opt(k, d);
    const ob = ctx.outline('Distance Correlations', { key: 'dcor', info: 'mv:dcor', menu: () => [
      ctx.check('Color Cells', 'dcorCells', null, true), ctx.check('Asymptotic Test Only', 'dcorAsym', null, false),
      { separator: true }, { label: 'Remove', action: () => ctx.set('dcor', false) }] });
    const r = await mcall(ctx, 'multivariate.distance', { columns: names, weight: ctx.name('weight'), freq: ctx.name('freq'), method: o('dcorAsym', false) ? 'asym' : 'auto' });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    // 0 (neutral) to 1 (red): dCor is never negative
    ob.add(matrixTable(ctx, names, r.matrix, { colors: o('dcorCells', true) ? (v) => diverging(v) : null, digits: 4, caption: 'Distance correlation' }));
    const tbl = ctx.rt({
      columns: [{ key: 'var', label: 'Variable', fmt: 'text' }, { key: 'by', label: 'by Variable', fmt: 'text' }, { key: 'dcor', label: 'dCor', digits: 4 }, { key: 'r', label: 'Correlation', digits: 4 },
        { key: 'dcov', label: 'dCov' }, { key: 'stat', label: 'n·dCov²' }, { key: 'p', label: 'Prob>n·dCov²', fmt: 'p' }, { key: 'method', label: 'p-Value from', fmt: 'text' },
        { key: 'z', label: '√(n·dCov²/S)', hidden: true }, { key: 'dvar_x', label: 'dVar by Variable', hidden: true }, { key: 'dvar_y', label: 'dVar Variable', hidden: true },
        { key: 'count', label: 'Count', fmt: 'int', hidden: true }, { key: 'bar', label: '0 .2 .4 .6 .8', fmt: 'text' }],
      rows: r.pairs.map((x) => ({ ...x, bar: '' })),
    });
    decorate(tbl, (tr, row) => { const td = tr.cells[tr.cells.length - 1]; td.classList.add('mv-barcell'); cellBar(td, row.dcor, 0, 1, RED); });
    ob.add(tbl,
      ctx.note('Distance correlation is 0 only when the two columns are independent, so it finds dependence of any form: a U or a circle, which the correlation and the rank correlations can miss (the (i) shows an example). dCov² is the mean product of the doubly centred distance matrices, dCor its correlation form (V-statistics, Székely, Rizzo and Bakirov 2007; statsmodels distance_statistics). The test of independence (distance_covariance_test) takes its p-value from permutations of the rows when a pair has at most 500 rows (the number B = 200 + 5000/n, a fixed seed), otherwise from the asymptotic bound; when no permutation reaches the observed n·dCov², statsmodels gives the asymptotic p-value instead, a conservative bound that can be larger than the permutation p-value (then below 1/B). Each pair on its own complete rows. Not in JMP, whose closest is Hoeffding\'s D (Nonparametric Correlations), a rank measure that also detects non-monotone dependence.'),
      ...(r.notes || []).map((t) => ctx.note(t)), ctx.code(r.code));
  }

  function pairwiseOutline(ctx, res, lv) {
    const ob = ctx.outline('Pairwise Correlations', { key: 'pairwise' });
    const tbl = ctx.rt({
      columns: [{ key: 'var', label: 'Variable', fmt: 'text' }, { key: 'by', label: 'by Variable', fmt: 'text' }, { key: 'r', label: 'Correlation', digits: 4 }, { key: 'count', label: 'Count', fmt: 'int' },
        { key: 'lower', label: `Lower ${lv}% CI`, digits: 4 }, { key: 'upper', label: `Upper ${lv}% CI`, digits: 4 }, { key: 'p', label: 'Signif Prob', fmt: 'p' }, { key: 'bar', label: '−.8 −.4 0 .4 .8', fmt: 'text' }],
      rows: res.pairs.map((x) => ({ ...x, bar: '' })),
    });
    decorate(tbl, (tr, row) => { const td = tr.cells[tr.cells.length - 1]; td.classList.add('mv-barcell'); cellBar(td, row.r, -1, 1, row.r < 0 ? '#2f6ec7' : RED); });
    ob.add(tbl, ctx.note('Each pair on the rows where both columns are present, whatever the estimation method. Click a heading to sort.'));
  }

  /* ---- the scatterplot matrix ------------------------------------------------ */
  function splomOutline(ctx, cols) {
    const o = (k, d) => ctx.opt(k, d);
    const ob = ctx.outline('Scatterplot Matrix', {
      key: 'splom',
      menu: () => [
        ctx.check('Show Points', 'spPoints', null, true), ctx.check('Density Ellipses', 'spEllipses', null, true), ctx.check('Shaded Ellipses', 'spShaded', null, false),
        ctx.check('Show Correlations', 'spCorr', null, false), ctx.check('Show Histograms', 'spHist', null, false), ctx.check('Fit Line', 'spFit', null, false),
        { label: 'Ellipse Coverage', submenu: () => [0.5, 0.9, 0.95, 0.99].map((a) => ({ label: String(a), checked: o('spLevel', 0.95) === a, action: () => ctx.set('spLevel', a) })) },
        { label: 'Matrix Format', submenu: () => [['square', 'Square'], ['lower', 'Lower Triangular'], ['upper', 'Upper Triangular']].map(([v, l]) => ({ label: l, checked: o('matrixFormat', 'square') === v, action: () => ctx.set('matrixFormat', v) })) },
      ],
    });
    if (cols.length > 16) { ob.add(ctx.note(`${cols.length} columns: the scatterplot matrix is drawn for up to 16.`)); return; }
    ob.add(scatterMatrix(ctx, cols, ctx.rows, {
      format: o('matrixFormat', 'square'), points: o('spPoints', true), ellipses: o('spEllipses', true), shaded: o('spShaded', false),
      corr: o('spCorr', false), hist: o('spHist', false), fit: o('spFit', false), level: o('spLevel', 0.95),
    }, [`X = df[${J(cols.map((c) => c.name))}]   # each pair on the rows where both columns have a value`]));
    ob.add(ctx.note(`Drag over points to select rows; the ellipses cover ${fmt(100 * o('spLevel', 0.95))}% of a bivariate normal with each pair's means, standard deviations and correlation.`));
  }

  /* The size of a scatterplot matrix of p columns in the room there is: the
     grid's g x g cells, the graph's width and height (the backend's code of
     a matrix it draws takes them: Discriminant's). */
  function splomSize(p, format) {
    const g = format === 'square' ? p : p - 1;
    const size = Math.max(44, Math.min(150, Math.floor((fitW(770) - 70) / Math.max(1, g))));
    return { g, size, width: size * g + 70, height: size * g + 56 };
  }

  /* The scatterplot matrix with its code under it: frame, the lines that
     give X, the graph's rows (all the report's, or those a fit took).
     opt.groups ({ of: row → group, open: rows drawn open, names, means,
     covs }) colours the points by group and draws each group's ellipse from
     its mean and covariance instead of the pair's; opt.code replaces the
     code the page writes (a fit's own). */
  function scatterMatrix(ctx, cols, rows, opt, frame) {
    const p = cols.length;
    const bins = [];
    const cells = [];
    if (opt.format === 'lower') { for (let i = 1; i < p; i++) for (let j = 0; j < i; j++) cells.push([i, j, i - 1, j]); }
    else if (opt.format === 'upper') { for (let i = 0; i < p - 1; i++) for (let j = i + 1; j < p; j++) cells.push([i, j, i, j - 1]); }
    else { for (let i = 0; i < p; i++) for (let j = 0; j < p; j++) cells.push([i, j, i, j]); }
    const { g, width: W, height: H } = splomSize(p, opt.format);
    const G = opt.groups || null;
    const gap = 0.012;
    const vals = cols.map((c) => rows.map((r) => { const v = c.values[r]; return typeof v === 'number' && Number.isFinite(v) ? v : null; }));
    const ranges = vals.map((v) => range(v));
    const total = rows.length * cells.length;
    const type = scatterType(total, 40000);
    const traces = [];
    const layout = { margin: { l: 58, r: 8, t: 6, b: 50 }, annotations: [], shapes: [], dragmode: 'select' };
    const tc = SM.util.themeColors();
    cells.forEach(([i, j, gi, gj], k) => {
      const a = k + 1;
      const xa = a === 1 ? 'x' : `x${a}`, ya = a === 1 ? 'y' : `y${a}`;
      const bottom = gi === g - 1, left = gj === 0;
      layout[`xaxis${a === 1 ? '' : a}`] = { domain: [gj / g + gap, (gj + 1) / g - gap], anchor: ya, range: ranges[j], showticklabels: bottom, showgrid: false, zeroline: false, ticks: bottom ? 'outside' : '', title: bottom ? { text: cols[j].name, standoff: 4, font: { size: 10.5 } } : undefined, tickfont: { size: 9 }, nticks: 4, mirror: true };
      layout[`yaxis${a === 1 ? '' : a}`] = { domain: [1 - (gi + 1) / g + gap, 1 - gi / g - gap], anchor: xa, range: ranges[i], showticklabels: left, showgrid: false, zeroline: false, ticks: left ? 'outside' : '', title: left ? { text: cols[i].name, standoff: 4, font: { size: 10.5 } } : undefined, tickfont: { size: 9 }, nticks: 4, mirror: true };
      if (i === j) {
        layout.annotations.push({ xref: `${xa} domain`, yref: `${ya} domain`, x: 0.5, y: opt.hist ? 0.92 : 0.5, text: cols[i].name, showarrow: false, font: { size: 11, color: tc.text } });
        traces.push({ type: 'scatter', mode: 'markers', x: [null], y: [null], xaxis: xa, yaxis: ya, hoverinfo: 'skip', showlegend: false });   // so the label cell is drawn
        if (opt.hist) {
          const { v, rows: rs } = colValues(cols[i], rows);
          const b = SM.report.niceBins(v);
          const nb = Math.max(1, Math.round((b.end - b.start) / b.size));
          bins[i] = { start: b.start, size: b.size, nb };
          const counts = new Array(nb).fill(0), members = Array.from({ length: nb }, () => []);
          v.forEach((x, q) => { const h = Math.min(nb - 1, Math.max(0, Math.floor((x - b.start) / b.size + 1e-9))); counts[h]++; members[h].push(rs[q]); });
          const mx = Math.max(...counts, 1);
          const [lo, hi] = ranges[i];
          const scale = (hi - lo) * 0.78 / mx;
          traces.push({ type: 'bar', x: counts.map((_, h) => b.start + (h + 0.5) * b.size), y: counts.map((c) => c * scale), base: lo, width: b.size * 0.96, rows: members, rowsScale: scale, customdata: counts, hovertemplate: '%{customdata} rows<extra></extra>', marker: { color: SM.report.BAR }, xaxis: xa, yaxis: ya, name: `${cols[i].name} histogram` });
        }
        return;
      }
      const xs = [], ys = [], rs = [];
      rows.forEach((r, q) => { const x = vals[j][q], y = vals[i][q]; if (x != null && y != null) { xs.push(x); ys.push(y); rs.push(r); } });
      const gmark = G ? { color: rs.map((r) => pal(G.of.get(r))), ...(G.open ? { symbol: rs.map((r) => (G.open.has(r) ? 'circle-open' : 'circle')) } : {}) } : {};
      if (opt.points) traces.push({ type, mode: 'markers', x: xs, y: ys, rows: rs, marker: { size: rows.length > 500 ? 3 : 4, ...gmark }, xaxis: xa, yaxis: ya, name: `${cols[i].name} by ${cols[j].name}`, hovertext: G ? rowLabels(ctx, rs).map((t, q) => `${t}: ${G.names[G.of.get(rs[q])]}`) : rowLabels(ctx, rs), hovertemplate: `%{hovertext}<br>${tpl(cols[j].name)}: %{x}<br>${tpl(cols[i].name)}: %{y}<extra></extra>` });
      if (G && opt.ellipses) {
        G.means.forEach((m, t) => {
          const C = G.covs[t];
          if (!C) return;
          const e = ellipseCov(m[j], m[i], [[C[j][j], C[j][i]], [C[i][j], C[i][i]]], opt.level);
          traces.push({ type: 'scatter', mode: 'lines', x: e.x, y: e.y, xaxis: xa, yaxis: ya, line: { color: pal(t), width: 1.2 }, fill: opt.shaded ? 'toself' : 'none', fillcolor: `${pal(t)}22`, hoverinfo: 'skip', name: `${G.names[t]} ellipse`, showlegend: false });
        });
      }
      if (xs.length > 2 && !G) {
        const s = pairStats(xs, ys);
        if (opt.ellipses && Number.isFinite(s.r)) {
          const e = ellipse(s.mx, s.my, s.sx, s.sy, s.r, opt.level);
          traces.push({ type: 'scatter', mode: 'lines', x: e.x, y: e.y, xaxis: xa, yaxis: ya, line: { color: RED, width: 1 }, fill: opt.shaded ? 'toself' : 'none', fillcolor: 'rgba(192,57,43,0.13)', hoverinfo: 'skip', name: 'ellipse' });
        }
        if (opt.fit && s.sx > 0) {
          const b1 = s.r * s.sy / s.sx, b0 = s.my - b1 * s.mx;
          const [lo, hi] = ranges[j];
          traces.push({ type: 'scatter', mode: 'lines', x: [lo, hi], y: [b0 + b1 * lo, b0 + b1 * hi], xaxis: xa, yaxis: ya, line: { color: tc.muted, width: 1 }, hoverinfo: 'skip', name: 'fit' });
        }
        if (opt.corr && Number.isFinite(s.r)) layout.annotations.push({ xref: `${xa} domain`, yref: `${ya} domain`, x: 0.03, y: 0.97, xanchor: 'left', yanchor: 'top', text: s.r.toFixed(4).replace('-', '−'), showarrow: false, font: { size: 9.5, color: tc.text } });
      }
    });
    if (G) {   // a legend of the groups (points drawn nowhere)
      G.names.forEach((nm, t) => traces.push({ type: 'scatter', mode: 'markers', x: [null], y: [null], xaxis: 'x', yaxis: 'y', marker: { size: 8, color: pal(t) }, name: SM.report.plotlyText(nm), showlegend: true, hoverinfo: 'skip' }));
      Object.assign(layout, { showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' } });
      layout.margin = { ...layout.margin, t: 30 };
    }
    return [ctx.plot(traces, layout, { width: W, height: H, title: 'Scatterplot Matrix', ...(G ? { rowColors: false } : {}) }), ctx.code(opt.code !== undefined ? opt.code : splomCode(ctx, cols, opt, bins, W, H, frame, rows.length))];
  }

  // The page's density ellipse, as Python (the backend's code has the same function).
  const ELLIPSE_PY = [
    'def ellipse(mx, my, sx, sy, r, level):',
    '    """The page\'s density ellipse: the contour of a bivariate normal with these means, standard deviations',
    '    and correlation that holds `level` of it, at 73 points."""',
    '    c = np.sqrt(-2 * np.log(1 - level))   # the square root of the chi-square quantile with 2 DF',
    '    t = 2 * np.pi * np.arange(73) / 72',
    '    r = min(max(r, -0.999999), 0.999999)',
    '    return mx + c * sx * np.cos(t), my + c * sy * (r * np.cos(t) + np.sqrt(1 - r * r) * np.sin(t))'];

  /* The scatterplot matrix as matplotlib code: each pair on its rows with its
     density ellipse, fit line and correlation, the columns' histograms on the
     diagonal in the page's bins, the axes over the ranges the page takes. */
  function splomCode(ctx, cols, opt, bins, W, H, frame, nrows) {
    const names = cols.map((c) => c.name);
    const p = cols.length, g = opt.format === 'square' ? p : p - 1;
    const lw = (px) => String(+(px * 0.72).toPrecision(3)), area = (px) => String(+((px * 0.72) ** 2).toPrecision(3));
    const hist = opt.hist && opt.format === 'square' && bins.filter(Boolean).length === p;
    const cells = {
      square: 'cells = [(i, j, i, j) for i in range(p) for j in range(p)]   # (the y column, the x column, the grid\'s row and column): Square',
      lower: 'cells = [(i, j, i - 1, j) for i in range(1, p) for j in range(i)]   # (the y column, the x column, the grid\'s row and column): Lower Triangular',
      upper: 'cells = [(i, j, i, j - 1) for i in range(p - 1) for j in range(i + 1, p)]   # (the y column, the x column, the grid\'s row and column): Upper Triangular',
    };
    const L = [SM.report.codeHead(ctx.table.name, ['import matplotlib.pyplot as plt']), ...keepLines(ctx), ...frame, `cols = ${J(names)}`];
    if (opt.ellipses) L.push(`level = ${pyNum(opt.level)}   # Ellipse Coverage`);
    if (hist) L.push(`bins = {${names.map((n, i) => `${J(n)}: (${pyNum(bins[i].start)}, ${pyNum(bins[i].size)}, ${bins[i].nb})`).join(', ')}}   # the page's histogram bins: start, width, number`);
    if (opt.ellipses) L.push('', ...ELLIPSE_PY);
    L.push('',
      'def axis_range(v):   # an axis over the values and 6% more on each side, as the page\'s',
      '    lo, hi = v.min(), v.max()',
      '    d = hi - lo or abs(hi) or 1',
      '    return lo - 0.06 * d, hi + 0.06 * d',
      '',
      '',
      'ranges = [axis_range(X[c].dropna()) if X[c].notna().any() else (0, 1) for c in cols]',
      `p, g = len(cols), ${g}`,
      cells[opt.format] || cells.square,
      `fig, axes = plt.subplots(g, g, figsize=(${inches(W)}, ${inches(H)}), squeeze=False, layout="constrained")`,
      'for ax in axes.flat:',
      '    ax.set_visible(False)   # (the cells the format leaves empty stay so)',
      'for i, j, gi, gj in cells:',
      '    ax = axes[gi, gj]',
      '    ax.set_visible(True)',
      '    ax.set_xlim(*ranges[j])',
      '    ax.set_ylim(*ranges[i])',
      '    ax.locator_params(nbins=4)',
      '    ax.tick_params(axis="x", labelbottom=gi == g - 1, length=3 if gi == g - 1 else 0, labelsize=6.5)',
      '    ax.tick_params(axis="y", labelleft=gj == 0, length=3 if gj == 0 else 0, labelsize=6.5)',
      '    if gi == g - 1:',
      '        ax.set_xlabel(cols[j], fontsize=7.6)',
      '    if gj == 0:',
      '        ax.set_ylabel(cols[i], fontsize=7.6)',
      `    if i == j:   # the diagonal: the column's name${hist ? ' and its histogram' : ''}`,
      `        ax.text(0.5, ${opt.hist ? 0.92 : 0.5}, cols[i], transform=ax.transAxes, ha="center", va="center", fontsize=7.9)`);
    if (hist) {
      L.push('        v = X[cols[i]].dropna().to_numpy()',
        '        start, size, nb = bins[cols[i]]',
        '        counts = np.bincount(np.clip(np.floor((v - start) / size + 1e-9), 0, nb - 1).astype(int), minlength=nb)   # each value\'s bin, as the page counts',
        '        lo, hi = ranges[i]',
        `        ax.bar(start + (np.arange(nb) + 0.5) * size, counts * (hi - lo) * 0.78 / max(counts.max(), 1), width=size * 0.96, bottom=lo, color="${PAPER.bar}")   # the tallest bar 78% of the cell`);
    }
    L.push('        continue',
      '    d = X[[cols[j], cols[i]]].dropna()   # the rows with both values',
      '    x, y = d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy()');
    if (opt.points) L.push(`    ax.scatter(x, y, s=${area(nrows > 500 ? 3 : 4)}, color="${PAPER.base}")`);
    if (opt.ellipses || opt.fit || opt.corr) {
      L.push('    if len(x) <= 2:',
        '        continue',
        '    mx, my = x.mean(), y.mean()',
        '    sxx, syy, sxy = ((x - mx) ** 2).sum(), ((y - my) ** 2).sum(), ((x - mx) * (y - my)).sum()',
        '    sx, sy = np.sqrt(sxx / (len(x) - 1)), np.sqrt(syy / (len(x) - 1))',
        '    r = sxy / np.sqrt(sxx * syy) if sxx > 0 and syy > 0 else np.nan   # the pair\'s correlation');
      if (opt.ellipses) {
        L.push('    if np.isfinite(r):   # the density ellipse', '        ex, ey = ellipse(mx, my, sx, sy, r, level)');
        if (opt.shaded) L.push(`        ax.fill(ex, ey, color="${RED}", alpha=0.13, linewidth=0)   # Shaded Ellipses`);
        L.push(`        ax.plot(ex, ey, color="${RED}", linewidth=${lw(1)})`);
      }
      if (opt.fit) {
        L.push('    if sx > 0:   # Fit Line: the least squares line of the pair',
          '        b1 = r * sy / sx',
          '        b0 = my - b1 * mx',
          '        lo, hi = ranges[j]',
          `        ax.plot([lo, hi], [b0 + b1 * lo, b0 + b1 * hi], color="${PAPER.muted}", linewidth=${lw(1)})`);
      }
      if (opt.corr) {
        L.push('    if np.isfinite(r):   # Show Correlations',
          '        ax.text(0.03, 0.97, f"{r:.4f}".replace("-", "−"), transform=ax.transAxes, ha="left", va="top", fontsize=6.8)');
      }
    }
    L.push('fig.suptitle("Scatterplot Matrix", fontsize=10)', 'plt.show()');
    return L.join('\n');
  }

  /* ---- colour maps --------------------------------------------------------------- */
  async function colorMaps(ctx, names, res) {
    const o = (k, d) => ctx.opt(k, d);
    const p = names.length;
    const sz = Math.max(260, Math.min(620, 60 + 46 * p));
    const heat = (z, zmin, zmax, text, scale, title, order) => {
      const nm = order.map((k) => names[k]);
      const zz = order.map((i) => order.map((j) => z[i][j]));
      const tt = order.map((i) => order.map((j) => text(z[i][j], i, j)));
      return ctx.plot([{ type: 'heatmap', z: zz, x: nm, y: nm, zmin, zmax, colorscale: scale, text: tt, texttemplate: p <= 12 ? '%{text}' : '', hovertemplate: '%{y} by %{x}: %{text}<extra></extra>', xgap: 1, ygap: 1, colorbar: { thickness: 10, len: 0.8 } }],
        { xaxis: { type: 'category', tickangle: -40, showgrid: false, showline: false, ticks: '' }, yaxis: { type: 'category', autorange: 'reversed', showgrid: false, showline: false, ticks: '' }, margin: { l: 40, r: 10, t: 8, b: 30 } }, { width: fitW(sz + 60), height: sz, title, select: false });
    };
    const ident = names.map((_, i) => i);
    const r4 = (v) => (v == null ? '' : v.toFixed(2).replace('-', '−'));
    if (o('cmCorr', false)) ctx.outline('Color Map On Correlations', { key: 'cmcorr' }).add(heat(res.corr, -1, 1, r4, divergingScale(), 'Color Map On Correlations', ident), ctx.code(res.cm_corr_code), ctx.note('Red for +1, blue for −1.'));
    if (o('cmP', false)) {
      const P = res.p.map((row, i) => row.map((v, j) => (i === j ? null : v)));
      const scale = dark() ? [[0, '#e8604f'], [0.5, '#3a3431'], [1, '#5b9cf0']] : [[0, '#c0392b'], [0.5, '#f6f3f0'], [1, '#2f6ec7']];
      ctx.outline('Color Map On p-values', { key: 'cmp' }).add(heat(P, 0, 1, (v, i, j) => (i === j ? '' : SM.util.fmtP(v, ctx.alpha)), scale, 'Color Map On p-values', ident), ctx.code(res.cm_p_code), ctx.note('Red for p = 0, blue for p = 1.'));
    }
    if (o('cmCluster', false)) {
      const r = await ctx.call('multivariate.cluster_order', { corr: res.corr });
      ctx.outline('Cluster the Correlations', { key: 'cmcluster' }).add(heat(res.corr, -1, 1, r4, divergingScale(), 'Cluster the Correlations', r.order), ctx.code(res.cm_cluster_code), ctx.note('The columns reordered so that similar ones are together: average linkage of 1 − r (scipy).'));
    }
  }

  /* ---- outlier analysis --------------------------------------------------------------- */
  async function outlierOutlines(ctx, names) {
    const o = (k, d) => ctx.opt(k, d);
    const r = await mcall(ctx, 'multivariate.outliers', { columns: names, alpha: ctx.alpha });
    if (r.error) { ctx.outline('Outlier Analysis', { key: 'outliers' }).add(ctx.warn(r.error)); return; }
    const kinds = [['mahal', 'Mahalanobis Distances', 'Mahalanobis Distance', 'mahal', 'ucl_mahal', 'Mahal. Distances'], ['jack', 'Jackknife Distances', 'Jackknife Distance', 'jack', 'ucl_jack', 'Jackknife Distances'], ['t2', 'T²', 'T²', 't2', 'ucl_t2', 'T Square']];
    for (const [key, title, ytitle, field, ucl, saveName] of kinds) {
      if (!o(key, false)) continue;
      const above = r.rows.filter((_, k) => r[field][k] > r[ucl]);
      const ob = ctx.outline(title, { key: `out:${key}`, info: 'mv:outliers', menu: () => [
        { label: 'Save', action: () => ctx.saveColumn(saveName, { rows: r.rows, values: r[field] }, { notes: `${title} from Multivariate; UCL ${fmt(r[ucl])} at α = ${ctx.alpha}` }) },
        { label: 'Select Rows above the UCL', action: () => ctx.table.select(above) },
        { label: 'Remove', action: () => ctx.set(key, false) },
      ] });
      ob.add(rowPlot(ctx, { rows: r.rows, y: r[field], limit: r[ucl], ytitle, title }), ctx.code(r[`${key}_code`]),
        ctx.note(`${above.length} row${above.length === 1 ? '' : 's'} above the upper control limit at α = ${ctx.alpha} (n = ${r.n}, p = ${r.p}).${key === 'jack' ? ' Each distance leaves its own row out of the mean and covariance.' : ''}`), ctx.code(r.code));
    }
  }

  async function reliabilityOutline(ctx, names) {
    const r = await mcall(ctx, 'multivariate.reliability', { columns: names, weight: ctx.name('weight'), freq: ctx.name('freq') });
    const both = [['alpha:raw', "Cronbach's α", 'alpha'], ['alpha:std', 'Standardized α', 'std_alpha']];
    for (const [key, title, field] of both) {
      if (!ctx.opt(key, false)) continue;
      const ob = ctx.outline(title, { key, menu: () => [{ label: 'Remove', action: () => ctx.set(key, false) }] });
      if (r.error) { ob.add(ctx.warn(r.error)); continue; }
      ob.add(ctx.kv([['Entire Set', r[field]]]),
        ctx.rt({ columns: [{ key: 'column', label: 'Excluded Col', fmt: 'text' }, { key: field, label: 'α', digits: 4 }, { key: 'item_total', label: 'Item-Total Corr', digits: 4, hidden: true }], rows: r.items }, { sortable: false }),
        ctx.note(field === 'alpha' ? 'α = k c̄/(v̄ + (k − 1) c̄), c̄ the mean covariance between items and v̄ the mean variance; beside each column, α with that column left out. Right click for the item-total correlations.' : 'α of the standardized items: k r̄/(1 + (k − 1) r̄), r̄ the mean correlation.'), ctx.code(r.code));
    }
  }

  /* ---- intraclass correlations and Kendall's W (Item Reliability; not in JMP): the columns are
     the raters, the rows the targets they rate, only the rows every rater rated ---- */
  async function iccOutline(ctx, names) {
    const r = await mcall(ctx, 'multivariate.icc', { columns: names, weight: ctx.name('weight'), freq: ctx.name('freq'), alpha: ctx.alpha });
    const ob = ctx.outline('Intraclass Correlations', { key: 'icc', info: 'mv:icc', menu: () => [{ label: 'Remove', action: () => ctx.set('icc', false) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const lv = fmt(100 * (1 - ctx.alpha));
    ob.add(ctx.kv([['Targets (rows)', r.n], ['Raters (columns)', r.k, 'int']]),
      ctx.rt({ columns: [{ key: 'source', label: 'Source', fmt: 'text' }, { key: 'df', label: 'DF' }, { key: 'ss', label: 'Sum of Squares' }, { key: 'ms', label: 'Mean Square' }, { key: 'f', label: 'F Ratio' }, { key: 'p', label: 'Prob > F', fmt: 'p' }], rows: r.anova, caption: 'Analysis of Variance' }, { sortable: false, key: 'icc:anova' }),
      ctx.rt({ columns: [{ key: 'form', label: 'Form', fmt: 'text' }, { key: 'sf', label: 'Shrout–Fleiss', fmt: 'text' }, { key: 'model', label: 'Model', fmt: 'text' }, { key: 'icc', label: 'ICC', digits: 4 }, { key: 'f', label: 'F Ratio' },
        { key: 'df1', label: 'NumDF' }, { key: 'df2', label: 'DenDF' }, { key: 'p', label: 'Prob > F', fmt: 'p' }, { key: 'lower', label: `Lower ${lv}%`, digits: 4 }, { key: 'upper', label: `Upper ${lv}%`, digits: 4 }], rows: r.icc, caption: 'Intraclass Correlations' }, { sortable: false, key: 'icc:forms' }),
      ctx.note(`The columns are the raters and the rows the targets, only the rows rated by every rater (${r.n_rows} of them). A one-way model takes each target's raters as a sample of raters; the two-way models have the same ${r.k} raters for every target: absolute agreement counts their differences in level, consistency does not. The k forms are the reliability of the mean of the ${r.k} raters. Each F tests ICC = 0; the intervals are exact but for absolute agreement (McGraw and Wong's approximation).`),
      ...(r.notes || []).map((t) => ctx.note(t)), ctx.code(r.code));
  }

  async function kendallOutline(ctx, names) {
    const r = await mcall(ctx, 'multivariate.kendall_w', { columns: names, weight: ctx.name('weight'), freq: ctx.name('freq') });
    const ob = ctx.outline("Kendall's W", { key: 'kendallw', info: 'mv:kendallw', menu: () => [{ label: 'Remove', action: () => ctx.set('kendallw', false) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    ob.add(ctx.kv([["Kendall's W", r.w], ['ChiSquare', r.chi2], ['DF', r.df, 'int'], ['Prob > ChiSq', r.p, 'p'], ['Objects (rows)', r.n, 'int'], ['Raters (columns)', r.m, 'int'], ['Mean Spearman ρ', r.mean_spearman]]),
      ctx.note(`The concordance of the ${r.m} raters (the columns): each ranks the ${r.n} objects (the rows rated by all of them; ties share the mean rank), and W = 12S/(m²(n³ − n) − mT) from the spread S of the objects' rank sums, T the correction for ties. W is 1 when every rater ranks the objects alike and 0 when their rankings share nothing. ChiSquare = m(n − 1)W on n − 1 DF is Friedman's test with the raters as blocks.`),
      ...(r.notes || []).map((t) => ctx.note(t)), ctx.code(r.code));
  }

  function openPCA(ctx) {
    const P = SM.platforms.get('pca');
    if (!P) { SM.ui.toast('Principal Components is not loaded'); return; }
    SM.app.openReport(P, { roles: { y: idsOf(ctx, 'y'), weight: idsOf(ctx, 'weight'), freq: idsOf(ctx, 'freq'), by: idsOf(ctx, 'by') }, options: { on: 'correlations' } }, ctx.table);
  }

  SM.platforms.register({
    id: 'multivariate', label: 'Multivariate', menu: 'Analyze/Multivariate Methods', order: 10, info: 'p:multivariate',
    about: 'Correlations of several columns (row-wise or pairwise), their tests and confidence intervals, inverse and partial correlations, covariances, Spearman, Kendall and Hoeffding, the scatterplot matrix with density ellipses, Mahalanobis, jackknife and T² distances, and Cronbach\'s α. Beyond JMP: distance correlations with the distance covariance test of independence, which detect dependence that is not monotone; intraclass correlations (the six forms of Shrout and Fleiss, in McGraw and Wong\'s names, with F tests and intervals) and Kendall\'s W with its chi-square (Friedman) test, in Item Reliability.',
    uses: ['numpy (correlations, covariances, inverse)', 'scipy.stats: pearsonr, spearmanr, kendalltau, t, beta', "Hoeffding's D and the Blum-Kiefer-Rosenblatt law (numpy, scipy.integrate)", 'statsmodels.stats.weightstats.DescrStatsW (weights)',
      'statsmodels.stats.dist_dependence_measures: distance_statistics, distance_covariance_test', 'scipy.stats: f, chi2, rankdata (intraclass correlations, Kendall\'s W)'],
    topics: {
      'p:multivariate': {
        kicker: 'Analyze > Multivariate Methods', title: 'Multivariate',
        lead: 'How several continuous columns vary together: the correlation matrix, a scatterplot matrix with density ellipses, and from the red triangle the tests, intervals, partial and nonparametric correlations, outlier distances and item reliability.',
        sections: [
          { heading: 'Roles', choices: [['Y, Columns', 'Two or more numeric columns (continuous or ordinal).'], ['Weight, Freq', 'Case weights and frequencies (DescrStatsW); a frequency counts as that many observations.'], ['By', 'One report per level.']] },
          { heading: 'Estimation Method', choices: [['Row-wise', 'Rows with a missing value in any column are left out of everything but the Univariate Simple Statistics and the Pairwise Correlations.'], ['Pairwise', 'Each correlation on the rows where its two columns are present; the matrix need not be positive definite.']] },
          { heading: 'Differences from JMP', text: 'JMP\'s REML, ML and Robust estimation are not offered; its Default (REML when there are missing values) is Row-wise here. Hoeffding\'s D is computed as JMP documents it, with p-values from the Blum-Kiefer-Rosenblatt limit (as SAS does). Distance Correlations are statsmodels\', not JMP\'s.' },
        ],
        more: { label: 'Multivariate', id: 'help-p-multivariate' },
      },
      'mv:hoeffding': { kicker: 'Multivariate', title: "Hoeffding's D", lead: 'A rank measure of dependence of any form, not only monotone: D = 30[(n−2)(n−3)D₁ + D₂ − 2(n−2)D₃]/[n(n−1)(n−2)(n−3)(n−4)] from the ranks R, S and the bivariate ranks Q. It is 1 for a perfectly monotone relation and near 0 for independence (it can be negative). The p-value refers (n − 1)π⁴D/60 + π⁴/72 to the Blum-Kiefer-Rosenblatt distribution, computed here by Imhof\'s inversion.', more: { label: 'Multivariate', id: 'help-p-multivariate' } },
      'mv:dcor': {
        kicker: 'Multivariate', title: 'Distance correlation',
        lead: 'A measure of dependence of any form: 0 only when two columns are independent, 1 for a straight line. It correlates the distances between rows, not the values: dCov² is the mean product of the two doubly centred distance matrices, and dCor = dCov/√(dVar_X·dVar_Y) (Székely, Rizzo and Bakirov 2007).',
        facts: [['y = x², 41 points from −1 to 1', 'correlation 0, Spearman ρ 0.02, dCor 0.49, p 0.04 (permutations)'], ['a circle, 40 points', 'correlation 0, Spearman ρ 0.00, dCor 0.20, p 0.55'], ['y = x', 'every measure 1']],
        sections: [
          { heading: 'The example', text: 'For the parabola the correlation and the rank correlations are 0, for there is no monotone trend; the distance correlation sees the dependence. Some shapes, such as the circle, give it only a weak signal: no single measure finds every dependence.' },
          { heading: 'The test', text: 'n·dCov² is large when the columns depend on each other. Its p-value comes from permuting the rows when a pair has at most 500 rows (B = 200 + 5000/n permutations, a fixed seed here, so the numbers repeat), otherwise from the asymptotic bound 2(1 − Φ(√(n·dCov²/S))), S the product of the mean distances. When no permutation reaches the observed value statsmodels gives that asymptotic p-value instead, and says so; that bound is conservative and can be larger than the permutation p-value, which is then below 1/B.' },
          { heading: 'Size', text: 'The distance matrices are n × n: a pair with more than 2000 rows uses a seeded random subsample of 2000.' },
          { heading: 'Not in JMP', text: 'JMP\'s closest is Hoeffding\'s D (Nonparametric Correlations), a rank measure that also detects non-monotone dependence.' },
        ],
        more: { label: 'Multivariate', id: 'help-p-multivariate' },
      },
      'mv:icc': {
        kicker: 'Multivariate', title: 'Intraclass correlations',
        lead: 'How much of the variation in the ratings is between the targets: the columns are the raters (or items), the rows the targets they rate, only the rows every rater rated. From the two-way analysis of variance without replication (Between Targets MSR, Between Raters MSC, Residual MSE; Within Targets MSW for the one-way model), the six forms of Shrout and Fleiss (1979), named as McGraw and Wong (1996) name them. Not in JMP.',
        sections: [
          { choices: [['ICC(1,1)', 'one-way random: each target has its own sample of raters; (MSR − MSW)/(MSR + (k − 1)MSW)'], ['ICC(A,1)', 'two-way, absolute agreement (Shrout and Fleiss\'s ICC(2,1)): the raters\' differences in level count as error; (MSR − MSE)/(MSR + (k − 1)MSE + k(MSC − MSE)/n)'], ['ICC(C,1)', 'two-way, consistency (their ICC(3,1)): only the rank and spacing of the targets matter; (MSR − MSE)/(MSR + (k − 1)MSE)'], ['ICC(1,k), ICC(A,k), ICC(C,k)', 'the reliability of the mean of the k raters: (MSR − MSW)/MSR, (MSR − MSE)/(MSR + (MSC − MSE)/n), (MSR − MSE)/MSR']] },
          { heading: 'Tests and intervals', text: 'F tests ICC = 0: MSR/MSW for the one-way forms, MSR/MSE for the two-way ones. The intervals invert the F distribution of those ratios (exact); for absolute agreement they are McGraw and Wong\'s approximation with Satterthwaite\'s degrees of freedom (their Table 7). Weight and Freq count a row that many times.' },
          { heading: 'Which one', text: 'Random raters from a larger pool whose levels matter: ICC(A,1). The same fixed raters, levels aside: ICC(C,1). A single score from one rater, or the mean of all k: the 1 or k forms. Shrout and Fleiss\'s example (6 targets, 4 judges) gives .17, .29, .71, .44, .62, .91.' },
        ],
        more: { label: 'Multivariate', id: 'help-p-multivariate' },
      },
      'mv:kendallw': {
        kicker: 'Multivariate', title: "Kendall's W",
        lead: 'The coefficient of concordance of m raters (the columns) ranking n objects (the rows every rater rated): W = 12S/(m²(n³ − n) − mT), S the sum of the squared deviations of the objects\' rank sums from their mean, T = Σ(t³ − t) over the groups of t tied objects of each rater (Kendall and Babington Smith 1939). W is 0 for no agreement, 1 for rankings that are all the same. Not in JMP.',
        sections: [
          { heading: 'The test', text: 'm(n − 1)W against χ² on n − 1 DF, which is Friedman\'s (1937) test with the raters as the blocks (scipy\'s friedmanchisquare gives the same number, ties corrected). Mean Spearman ρ is the average rank correlation of the pairs of raters; without ties it is (mW − 1)/(m − 1).' },
          { heading: 'Weights', text: 'As for the nonparametric correlations, Weight and Freq only leave out the rows without a positive value.' },
        ],
        more: { label: 'Multivariate', id: 'help-p-multivariate' },
      },
      'mv:outliers': { kicker: 'Multivariate', title: 'Outlier distances', lead: 'Mahalanobis distance: √((y − ȳ)′S⁻¹(y − ȳ)) with the sample mean and covariance of the rows with no missing value. The jackknife distance leaves the row itself out of the mean and covariance. T² is the squared Mahalanobis distance. The UCL of T² is (n − 1)²/n times the 1 − α quantile of Beta(p/2, (n − p − 1)/2) (Mason and Young 2002); the others are its transformations.', more: { label: 'Multivariate', id: 'help-p-multivariate' } },
    },
    launch: {
      lead: 'Choose two or more numeric columns. The report starts with their correlations and a scatterplot matrix; the red triangle adds the rest.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 2, numeric: true, types: ['continuous', 'ordinal'], hint: 'required: two or more numeric',
          help: 'The columns whose correlations, covariances and scatterplot matrix are shown, and which the outlier distances and item reliability are computed over.' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'Case weights: the means, covariances and correlations are weighted (statsmodels DescrStatsW); the tests count rows, or Freq, in their degrees of freedom. Rows with a missing, zero or negative weight are left out.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'A count per row: the row stands for that many observations, in the estimates and in the tests\' degrees of freedom.' },
        { key: 'by', label: 'By', hint: 'optional', help: BY_HELP },
      ],
      options: [
        { key: 'method', label: 'Estimation Method', type: 'select', value: 'rowwise', choices: [['rowwise', 'Row-wise'], ['pairwise', 'Pairwise']],
          help: 'Row-wise, the default: only the rows with every column present, so every statistic uses the same rows. Pairwise: each correlation and covariance on the rows where its two columns are present, which uses more of the data when values are missing, but the matrix need not be positive definite. JMP\'s REML, ML and Robust are not offered.' },
        { key: 'matrixFormat', label: 'Matrix Format', type: 'select', value: 'square', choices: [['square', 'Square'], ['lower', 'Lower Triangular'], ['upper', 'Upper Triangular']],
          help: 'The layout of the scatterplot matrix: Square shows every pair twice, with the columns\' names on the diagonal; Lower and Upper Triangular show each pair once.' },
      ],
    },
    title: () => 'Multivariate',
    triangle(ctx) {
      const o = (k, d) => ctx.opt(k, d);
      return [
        ctx.check('Correlations Multivariate', 'corr', null, true),
        ctx.check('Correlation Probability', 'corrProb', null, false),
        ctx.check('CI of Correlation', 'ci', null, false),
        ctx.check('Inverse Correlations', 'inverse', null, false),
        ctx.check('Partial Correlations', 'partial', null, false),
        ctx.check('Covariance Matrix', 'cov', null, false),
        ctx.check('Pairwise Correlations', 'pairwise', null, false),
        { label: 'Simple Statistics', submenu: () => [ctx.check('Univariate Simple Statistics', 'simpleUni', null, false), ctx.check('Multivariate Simple Statistics', 'simpleMulti', null, false)] },
        { label: 'Nonparametric Correlations', submenu: () => NONPAR.map(([k, l]) => ctx.check(l, `np:${k}`, null, false)) },
        ctx.check('Distance Correlations', 'dcor', null, false),
        { label: 'Set α Level', submenu: () => levelOptions(ctx) },
        { label: 'Estimation Method', submenu: () => [['rowwise', 'Row-wise'], ['pairwise', 'Pairwise']].map(([v, l]) => ({ label: l, checked: o('method', 'rowwise') === v, action: () => ctx.set('method', v) })) },
        { separator: true },
        ctx.check('Scatterplot Matrix', 'splom', null, true),
        { label: 'Color Maps', submenu: () => [ctx.check('Color Map On Correlations', 'cmCorr', null, false), ctx.check('Color Map On p-values', 'cmP', null, false), ctx.check('Cluster the Correlations', 'cmCluster', null, false), ctx.check('Color Cells of the Correlations', 'cmCells', null, false)] },
        { label: 'Outlier Analysis', submenu: () => [ctx.check('Mahalanobis Distances', 'mahal', null, false), ctx.check('Jackknife Distances', 'jack', null, false), ctx.check('T²', 't2', null, false)] },
        { label: 'Item Reliability', submenu: () => [ctx.check("Cronbach's α", 'alpha:raw', null, false), ctx.check('Standardized α', 'alpha:std', null, false),
          { separator: true }, ctx.check('Intraclass Correlations', 'icc', null, false), ctx.check("Kendall's W", 'kendallw', null, false)] },
        { label: 'Principal Components', action: () => openPCA(ctx) },
        { separator: true },
        { label: 'Save', submenu: () => [['mahal', 'Mahalanobis Distances', 'Mahal. Distances'], ['jack', 'Jackknife Distances', 'Jackknife Distances'], ['t2', 'T²', 'T Square']].map(([f, l, name]) => ({ label: l, action: async () => {
          const r = await mcall(ctx, 'multivariate.outliers', { columns: ctx.names('y'), alpha: ctx.alpha });
          if (r.error) { SM.ui.toast(r.error, { error: true }); return; }
          ctx.saveColumn(name, { rows: r.rows, values: r[f] }, { notes: `${l} from Multivariate` });
        } })) },
      ];
    },
    render: mvRender,
  });

  /* ======================================================================
     PRINCIPAL COMPONENTS
     ====================================================================== */
  const ON = { correlations: 'Correlations', covariances: 'Covariances', unscaled: 'Unscaled' };
  const ROTATIONS = [['varimax', 'Varimax'], ['quartimax', 'Quartimax'], ['equamax', 'Equamax'], ['biquartimax', 'Biquartimax'], ['parsimax', 'Parsimax'], ['factorparsimax', 'Factorparsimax'], ['orthomax', 'Orthomax (γ)'],
    ['promax', 'Promax (oblique)'], ['quartimin', 'Quartimin (oblique)'], ['biquartimin', 'Biquartimin (oblique)'], ['covarimin', 'Covarimin (oblique)'], ['oblimin', 'Oblimin (γ, oblique)'], ['obvarimax', 'Obvarimax (oblique)'], ['obequamax', 'Obequamax (oblique)'], ['obparsimax', 'Obparsimax (oblique)']];
  const ROTATION_HELP = 'An orthogonal rotation (Varimax, the common choice, and the others of the orthomax family) keeps the rotated factors uncorrelated; an oblique one (Promax, Quartimin, Oblimin …) lets them correlate, which often gives simpler loadings. Each looks for loadings near 0 or ±1, so that each column belongs to few factors.';
  const GAMMA_HELP = 'The weight γ of the Orthomax and Oblimin families: Orthomax with γ = 1 is varimax and 0 quartimax; Oblimin with γ = 0 is quartimin, 0.5 biquartimin, 1 covarimin. Empty: 1 for Orthomax, 0 for Oblimin. The other rotations do not use it.';
  const KAISER_HELP = 'Rotate with each column\'s loadings scaled to unit length, and scale them back after (SAS\'s default), so that columns with small communalities count as much as the others in the rotation.';

  async function pcaRender(ctx) {
    const names = ctx.names('y');
    const o = (k, d) => ctx.opt(k, d);
    const on = o('on', 'correlations');
    const rot = o('rotation', null);
    const res = await mcall(ctx, 'pca.fit', { columns: names, weight: ctx.name('weight'), freq: ctx.name('freq'), on, rotation: rot ? rot.method : null, n_rotate: rot ? rot.k : null, gamma: rot ? rot.gamma : null, kaiser: rot ? rot.kaiser !== false : true,
      plot: { x: o('pcx', 0), y: o('pcy', 1), ellipse: !!o('ellipse', false) } });
    const box = ctx.container;
    if (res.error) { box.append(ctx.warn(res.error)); return; }
    const k = res.eigenvalues.length;
    const comp = (j) => `Prin${j + 1}`;
    const cx = Math.min(o('pcx', 0), k - 1), cy = Math.min(Math.max(o('pcy', 1), 0), k - 1);
    box.append(ctx.note(`${fmt(res.n)} observations${res.n_rows < ctx.rows.length ? `; ${dropped(ctx.rows.length - res.n_rows)}` : ''}. ${{ correlations: 'The eigenvalues of the correlation matrix sum to the number of columns.', covariances: 'Eigenvalues of the covariance matrix.', unscaled: "Eigenvalues of the uncentred cross products X′X/n." }[on]}`));
    if (o('summary', true)) {
      const ob = ctx.outline('Summary Plots', { key: 'summary', info: 'pca:summary' });
      const choose = controls(control('Select component, x', selectEl(cx, res.eigenvalues.map((_, j) => [j, comp(j)]), (v) => ctx.set('pcx', +v), 'x component')),
        control('y', selectEl(cy, res.eigenvalues.map((_, j) => [j, comp(j)]), (v) => ctx.set('pcy', +v), 'y component')));
      ob.add(ctx.row(withCode(eigenBars(ctx, res, 250, 240), ctx.code(res.eigen_code)), withCode(scorePlot(ctx, res, cx, cy, 300, 280, o('ellipse', false)), ctx.code(res.score_summary_code)),
        withCode(loadingPlot(ctx, res.loadings, names, cx, cy, 300, 280, on !== 'unscaled', comp), ctx.code(res.loading_summary_code))), choose);
    }
    if (o('eigen', true)) {
      const ob = ctx.outline('Eigenvalues', { key: 'eigen', menu: () => [ctx.check('Bartlett Test', 'bartlett', null, false)] });
      const bt = o('bartlett', false);
      const cols = [{ key: 'num', label: 'Number', fmt: 'int' }, { key: 'eig', label: 'Eigenvalue', digits: 4 }, { key: 'pct', label: 'Percent', digits: 3 }, { key: 'bar', label: '20 40 60 80', fmt: 'text' }, { key: 'cum', label: 'Cum Percent', digits: 3 }];
      if (bt) cols.push({ key: 'chi2', label: 'ChiSquare', digits: 3 }, { key: 'df', label: 'DF' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' });
      const rows = res.eigenvalues.map((e, j) => ({ num: j + 1, eig: e, pct: res.percent[j], cum: res.cum[j], bar: '', ...(res.bartlett[j] ? { chi2: res.bartlett[j].chi2, df: res.bartlett[j].df, p: res.bartlett[j].p } : {}) }));
      const tbl = ctx.rt({ columns: cols, rows }, { sortable: false });
      decorate(tbl, (tr, row) => { const td = tr.cells[3]; td.classList.add('mv-barcell'); cellBar(td, row.pct, 0, 100, SM.report.BAR); });
      ob.add(tbl);
      if (bt) ob.add(ctx.note('Bartlett\'s test that the eigenvalues from this one on are equal (Jackson 2003): χ² = (n − 1)[q ln(mean) − Σ ln λ] over the q last eigenvalues, (q − 1)(q + 2)/2 df. It assumes multivariate normal data; on correlations it is approximate.'));
      ob.add(ctx.code(res.code));
    }
    if (o('eigvec', false)) ctx.outline('Eigenvectors', { key: 'eigvec' }).add(matrixTable(ctx, res.eigenvalues.map((_, j) => comp(j)), res.eigenvectors, { rowNames: names, digits: 5 }), ctx.note('Unit length; the sign of each is arbitrary (here the largest entry is positive).'));
    if (o('loadmat', false)) ctx.outline('Loading Matrix', { key: 'loadmat' }).add(matrixTable(ctx, res.eigenvalues.map((_, j) => comp(j)), res.loadings, { rowNames: names, digits: 5, colors: (v) => diverging(v) }), ctx.note(on === 'unscaled' ? 'Eigenvectors × √eigenvalue over the root mean square of each column.' : 'The correlations of the columns with the components (eigenvector × √eigenvalue, over the column\'s standard deviation on covariances).'));
    if (o('fmtload', false)) formattedLoadings(ctx, res, names, comp);
    if (o('corrmat', false) && res.corr) ctx.outline('Correlations', { key: 'corrmat' }).add(matrixTable(ctx, names, res.corr, { digits: 4 }));
    if (o('covmat', false)) ctx.outline(on === 'unscaled' ? "Cross Products X′X/n" : on === 'correlations' ? 'Correlation Matrix (analysed)' : 'Covariance Matrix', { key: 'covmat' }).add(matrixTable(ctx, names, res.matrix));
    if (o('scree', false)) ctx.outline('Scree Plot', { key: 'scree' }).add(screePlot(ctx, res.eigenvalues, 'Eigenvalue', on === 'correlations'), ctx.code(res.scree_code));
    if (o('score', false)) ctx.outline('Score Plot', { key: 'score' }).add(scorePlot(ctx, res, cx, cy, 440, 380, o('ellipse', false)), ctx.code(res.score_code));
    if (o('loadplot', false)) ctx.outline('Loading Plot', { key: 'loadplot' }).add(loadingPlot(ctx, res.loadings, names, cx, cy, 420, 380, on !== 'unscaled', comp), ctx.code(res.loading_code));
    if (o('biplot', false)) ctx.outline('Biplot', { key: 'biplot' }).add(biplot(ctx, res, names, cx, cy), ctx.code(res.biplot_code), ctx.note('The scores as points and the loadings as rays, the rays scaled to the spread of the scores.'));
    if (res.rotation) rotatedOutline(ctx, res, names);
  }

  function eigenBars(ctx, res, w, h) {
    return ctx.plot([{ type: 'bar', x: res.eigenvalues.map((_, j) => j + 1), y: res.eigenvalues, marker: { color: SM.report.BAR }, customdata: res.percent, hovertemplate: 'Prin%{x}: %{y:.4f} (%{customdata:.1f}%)<extra></extra>' }],
      { xaxis: { title: { text: 'Number' }, dtick: 1 }, yaxis: { title: { text: 'Eigenvalue' }, rangemode: 'tozero' }, shapes: ctx.opt('on', 'correlations') === 'correlations' ? [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 1, y1: 1, line: { color: RED, width: 1, dash: 'dot' } }] : [] },
      { width: fitW(w), height: h, title: 'Eigenvalues', select: false });
  }

  function screePlot(ctx, ev, ytitle, refOne) {
    return ctx.plot([{ type: 'scatter', mode: 'lines+markers', x: ev.map((_, j) => j + 1), y: ev, line: { color: SM.report.BASE, width: 1.5 }, marker: { size: 7 }, hovertemplate: '%{x}: %{y:.4f}<extra></extra>' }],
      { xaxis: { title: { text: 'Number of Components' }, dtick: 1 }, yaxis: { title: { text: ytitle }, rangemode: 'tozero' }, shapes: refOne ? [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 1, y1: 1, line: { color: RED, width: 1, dash: 'dot' } }] : [] },
      { width: fitW(380), height: 260, title: 'Scree Plot', select: false });
  }

  function scorePlot(ctx, res, a, b, w, h, withEllipse) {
    const x = res.scores.map((s) => s[a]), y = res.scores.map((s) => s[b]);
    const traces = [{ type: scatterType(res.rows.length, 8000), mode: 'markers', x, y, rows: res.rows, name: 'scores', hovertext: rowLabels(ctx, res.rows), hovertemplate: `%{hovertext}<br>Prin${a + 1}: %{x:.4f}<br>Prin${b + 1}: %{y:.4f}<extra></extra>` }];
    if (withEllipse && res.rows.length > 2) {
      const st = pairStats(x, y);
      const e = ellipse(st.mx, st.my, st.sx, st.sy, a === b ? 0 : st.r, 0.95);
      traces.push({ type: 'scatter', mode: 'lines', x: e.x, y: e.y, line: { color: RED, width: 1 }, hoverinfo: 'skip' });
    }
    return ctx.plot(traces, { xaxis: { title: { text: `Prin${a + 1}` }, zeroline: true }, yaxis: { title: { text: `Prin${b + 1}` }, zeroline: true } }, { width: fitW(w), height: h, title: 'Score Plot' });
  }

  function loadingPlot(ctx, L, names, a, b, w, h, unit, comp) {
    const tc = SM.util.themeColors();
    const traces = [];
    const xs = [], ys = [];
    names.forEach((_, i) => { xs.push(0, L[i][a], null); ys.push(0, L[i][b], null); });
    traces.push({ type: 'scatter', mode: 'lines', x: xs, y: ys, line: { color: tc.muted, width: 1 }, hoverinfo: 'skip' });
    traces.push({ type: 'scatter', mode: names.length <= 30 ? 'markers+text' : 'markers', x: names.map((_, i) => L[i][a]), y: names.map((_, i) => L[i][b]), text: names, textposition: 'top center', textfont: { size: 10, color: tc.text }, marker: { size: 7, color: RED, symbol: 'diamond' }, hovertemplate: '%{text}: (%{x:.4f}, %{y:.4f})<extra></extra>' });
    const layout = { xaxis: { title: { text: comp(a) }, zeroline: true }, yaxis: { title: { text: comp(b) }, zeroline: true, scaleanchor: 'x' }, shapes: [] };
    if (unit) {
      layout.shapes.push({ type: 'circle', xref: 'x', yref: 'y', x0: -1, x1: 1, y0: -1, y1: 1, line: { color: tc.grid, width: 1 } });
      layout.xaxis.range = [-1.15, 1.15];
      layout.yaxis.range = [-1.15, 1.15];
    }
    return ctx.plot(traces, layout, { width: fitW(w), height: h, title: 'Loading Plot', select: false });
  }

  function biplot(ctx, res, names, a, b) {
    const tc = SM.util.themeColors();
    const x = res.scores.map((s) => s[a]), y = res.scores.map((s) => s[b]);
    let smax = 0, lmax = 0;
    for (let k = 0; k < x.length; k++) smax = Math.max(smax, Math.abs(x[k]), Math.abs(y[k]));
    for (const l of res.loadings) lmax = Math.max(lmax, Math.abs(l[a]), Math.abs(l[b]));
    const s = lmax > 0 ? (0.85 * smax) / lmax : 1;
    const rx = [], ry = [];
    names.forEach((_, i) => { rx.push(0, s * res.loadings[i][a], null); ry.push(0, s * res.loadings[i][b], null); });
    return ctx.plot([
      { type: 'scatter', mode: 'markers', x, y, rows: res.rows, hovertext: rowLabels(ctx, res.rows), hovertemplate: '%{hovertext}<extra></extra>', marker: { size: 5 } },
      { type: 'scatter', mode: 'lines', x: rx, y: ry, line: { color: RED, width: 1.2 }, hoverinfo: 'skip' },
      { type: 'scatter', mode: 'text', x: names.map((_, i) => s * res.loadings[i][a]), y: names.map((_, i) => s * res.loadings[i][b]), text: names, textposition: 'top center', textfont: { size: 10.5, color: tc.text }, hoverinfo: 'skip' },
    ], { xaxis: { title: { text: `Prin${a + 1}` }, zeroline: true }, yaxis: { title: { text: `Prin${b + 1}` }, zeroline: true } }, { width: fitW(460), height: 400, title: 'Biplot' });
  }

  function formattedLoadings(ctx, res, names, comp) {
    const thr = ctx.opt('suppress', 0);
    const ob = ctx.outline('Formatted Loading Matrix', { key: 'fmtload', info: 'pca:fmtload' });
    const order = names.map((_, i) => i).sort((i, j) => res.loadings[j][0] - res.loadings[i][0]);
    const kk = res.eigenvalues.length;
    const tbl = matrixTable(ctx, res.eigenvalues.map((_, j) => comp(j)), order.map((i) => res.loadings[i]), { rowNames: order.map((i) => names[i]), digits: 4 });
    const blank = ctx.opt('blank', false);
    decorate(tbl, (tr, row, i) => { [...tr.cells].forEach((td, j) => { if (j === 0) return; const v = res.loadings[order[i]][j - 1]; const small = thr > 0 && Math.abs(v) < thr; td.classList.toggle('mv-dim', small && !blank); td.classList.toggle('mv-blank', small && blank); }); });
    ob.add(suppressControls(ctx, thr, blank, null), tbl,
      ctx.note(`Sorted by the loadings on Prin1, largest first${thr > 0 ? `; values below ${fmt(thr)} in absolute value ${blank ? 'left blank' : 'dimmed'}` : ''}. ${kk} components.`));
  }

  function rotatedOutline(ctx, res, names) {
    const R = res.rotation;
    const fac = Array.from({ length: R.k }, (_, j) => `Factor ${j + 1}`);
    const ob = ctx.outline(`Rotated Components: ${R.label}`, { key: 'rotated', menu: () => [
      { label: 'Save Rotated Components', action: () => saveRotated(ctx) },
      { label: 'Remove', action: () => ctx.set('rotation', null) },
    ] });
    const order = names.map((_, i) => i);
    const top = order.map((i) => { let b = 0; R.loadings[i].forEach((v, j) => { if (Math.abs(v) > Math.abs(R.loadings[i][b])) b = j; }); return b; });
    order.sort((i, j) => top[i] - top[j] || Math.abs(R.loadings[j][top[j]]) - Math.abs(R.loadings[i][top[i]]));
    ob.add(matrixTable(ctx, fac, order.map((i) => R.loadings[i]), { rowNames: order.map((i) => names[i]), digits: 4, colors: (v) => diverging(v), caption: 'Rotated Factor Loading' }));
    ob.add(ctx.rt({ columns: [{ key: 'f', label: '', fmt: 'text' }, { key: 'v', label: 'Variance', digits: 4 }, { key: 'pct', label: 'Percent', digits: 3 }], rows: fac.map((f, j) => ({ f, v: R.variance[j], pct: (100 * R.variance[j]) / res.eigenvalues.reduce((a, b) => a + b, 0) })), caption: R.kind === 'oblique' ? 'Variance Explained by Each Factor (ignoring the others)' : 'Variance Explained by Each Factor' }, { sortable: false }));
    ob.add(matrixTable(ctx, fac, R.T, { rowNames: fac, digits: 5, caption: 'Rotation Matrix' }));
    if (R.kind === 'oblique') ob.add(matrixTable(ctx, fac, R.phi, { rowNames: fac, digits: 4, caption: 'Factor Correlations' }));
    if (R.k >= 2) ob.add(loadingPlot(ctx, R.loadings, names, 0, 1, 380, 340, true, (j) => fac[j]), ctx.code(res.rotated_code));
    ob.add(ctx.note(`The first ${R.k} components' loadings rotated by statsmodels' factor_rotation${R.kaiser ? ', with Kaiser\'s normalization (as SAS)' : ''}. ${R.kind === 'oblique' ? 'Oblique: the rotated components are correlated.' : 'Orthogonal: the rotated components stay uncorrelated.'}`));
  }

  /* Save Rotated Components: formula columns, as Save Principal Components. */
  function saveRotated(ctx) {
    const rot = ctx.opt('rotation', null);
    if (!rot) { SM.ui.toast('Choose a rotation first: Factor Rotation…'); return null; }
    return saveFrom(ctx, 'pca.save', { columns: ctx.names('y'), weight: ctx.name('weight'), freq: ctx.name('freq'), on: ctx.opt('on', 'correlations'), what: 'rotated',
      rotation: rot.method, n_rotate: rot.k, gamma: rot.gamma, kaiser: rot.kaiser !== false });
  }

  /* Save Principal Components: the first n scores as formula columns (Prin1 =
     Σ eigenvector × the column centred, and on correlations scaled, by the
     fitted mean and standard deviation), so every row whose columns are
     present gets its score, excluded rows too, and the scores follow edits. */
  async function pcaSave(ctx) {
    const res = await mcall(ctx, 'pca.fit', { columns: ctx.names('y'), weight: ctx.name('weight'), freq: ctx.name('freq'), on: ctx.opt('on', 'correlations') });
    if (res.error) { SM.ui.toast(res.error, { error: true }); return; }
    const k = res.eigenvalues.length;
    const dflt = Math.max(1, res.eigenvalues.filter((e) => e >= 1).length);
    const v = await SM.ui.form({ title: 'Save Principal Components', fields: [{ key: 'n', label: `Number of components (1 to ${k})`, type: 'number', value: Math.min(k, dflt),
      help: 'How many component columns (Prin1, Prin2, …) to add to the table; the default is the number of eigenvalues of at least 1. Each is a formula column: the eigenvector times the row centred by the fitted means (on correlations also divided by the fitted standard deviations), so its variance over the report\'s rows is the eigenvalue, and every row whose columns are present gets a score, excluded rows too.' }] });
    if (!v || !(v.n >= 1)) return;
    await saveFrom(ctx, 'pca.save', { columns: ctx.names('y'), weight: ctx.name('weight'), freq: ctx.name('freq'), on: ctx.opt('on', 'correlations'), n: Math.min(k, Math.round(v.n)) });
  }

  async function rotationDialog(ctx) {
    const cur = ctx.opt('rotation', null) || {};
    const v = await SM.ui.form({
      title: 'Factor Rotation', lead: 'Rotate the loadings of the first components, as JMP\'s Factor Analysis option of Principal Components does.',
      fields: [
        { key: 'k', label: 'Number of components to rotate', type: 'number', value: cur.k ?? 2,
          help: 'The first components whose loadings are rotated together; two or more.' },
        { key: 'method', label: 'Rotation', type: 'select', value: cur.method || 'varimax', choices: ROTATIONS, help: ROTATION_HELP },
        { key: 'gamma', label: 'γ (Orthomax and Oblimin only)', type: 'number', value: cur.gamma ?? null, help: GAMMA_HELP },
        { key: 'kaiser', label: 'Kaiser normalization', type: 'check', value: cur.kaiser !== false, help: KAISER_HELP },
      ],
    });
    if (v) ctx.set('rotation', { k: Math.max(2, Math.round(v.k || 2)), method: v.method, gamma: v.gamma, kaiser: !!v.kaiser });
  }

  SM.platforms.register({
    id: 'pca', label: 'Principal Components', menu: 'Analyze/Multivariate Methods', order: 20, info: 'p:pca',
    about: 'Principal components on correlations, covariances or the unscaled data: eigenvalues with Bartlett\'s test of equal eigenvalues, eigenvectors, loadings, score, loading and scree plots, a biplot, rotated components, and the component scores saved as formula columns (every row, excluded ones too).',
    uses: ['statsmodels.multivariate.pca.PCA', 'statsmodels.multivariate.factor_rotation.rotate_factors', 'scipy.stats.chi2'],
    topics: {
      'p:pca': {
        kicker: 'Analyze > Multivariate Methods', title: 'Principal Components',
        lead: 'Linear combinations of the columns that are uncorrelated and take up as much of the variation as possible, the first the most.',
        sections: [
          { heading: 'On what', choices: [['Correlations', 'Each column standardized: the eigenvalues sum to the number of columns; loadings are correlations.'], ['Covariances', 'Centred columns: columns with larger variances weigh more.'], ['Unscaled', 'The raw cross products X′X/n, neither centred nor scaled.']] },
          { heading: 'Scores', text: 'Prin1, Prin2, … are the centred (and on correlations standardized, with the n − 1 standard deviation) rows times the eigenvectors, so their variances are the eigenvalues. The sign of an eigenvector is arbitrary; here its largest entry is positive. Save Principal Components and Save Rotated Components make them formula columns of the fitted means, standard deviations and eigenvectors (as JMP\'s): every row whose columns are present gets its score, excluded rows too, and an edited value is scored again.' },
          { heading: 'Differences from JMP', text: 'The advanced (sparse, robust) methods, supplementary variables and the outlier analysis of JMP\'s platform are not here. The rotation is statsmodels\' factor_rotation with Kaiser\'s normalization; promax is Hendrickson and White\'s with power 3, as SAS computes it.' },
        ],
        more: { label: 'Principal Components', id: 'help-p-pca' },
      },
      'pca:summary': {
        kicker: 'Principal Components', title: 'Summary Plots',
        lead: 'The eigenvalues as bars, the rows as points on two components (the score plot) and the columns as rays on the same two (the loading plot, inside the unit circle on correlations and covariances).',
        sections: [{ heading: 'In the report', choices: [
          ['Select component, x', 'The component on the horizontal axis of the score and loading plots; the Score Plot, Loading Plot and Biplot outlines follow it too.'],
          ['y', 'The component on the vertical axis.']] }],
        more: { label: 'Principal Components', id: 'help-p-pca' },
      },
      'pca:fmtload': {
        kicker: 'Principal Components', title: 'Formatted Loading Matrix',
        lead: 'The loadings with the columns sorted by their loading on Prin1, largest first, and the small ones dimmed or left blank, so that the pattern stands out.',
        sections: [{ heading: 'In the report', choices: [
          ['Suppress absolute loading values less than', 'Loadings smaller than this in absolute value are dimmed (or blanked); empty or 0 shows them all. The value takes effect when you leave the field or press Enter.'],
          ['Blank them (else dimmed)', 'Leave the suppressed loadings empty instead of dimming them.']] }],
        more: { label: 'Principal Components', id: 'help-p-pca' },
      },
    },
    launch: {
      lead: 'Choose the columns. The report shows the eigenvalues, a score plot and a loading plot of the first two components.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 2, numeric: true, types: ['continuous', 'ordinal'], hint: 'required: two or more numeric',
          help: 'The columns whose principal components are found. Rows with a missing value in any of them are left out.' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'Case weights of the means and of the matrix analysed. Rows with a missing, zero or negative weight are left out.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'A count per row: the row stands for that many observations, in the matrix and in Bartlett\'s test.' },
        { key: 'by', label: 'By', hint: 'optional', help: BY_HELP },
      ],
      options: [{ key: 'on', label: 'Principal components on', type: 'select', value: 'correlations', choices: [['correlations', 'Correlations'], ['covariances', 'Covariances'], ['unscaled', 'Unscaled']],
        help: 'Correlations, the default: each column standardized first, so every column counts alike and the loadings are correlations. Covariances: the columns only centred, so those with larger variances weigh more; for columns in the same units. Unscaled: the raw cross products X′X/n, neither centred nor scaled. The red triangle changes it later.' }],
    },
    title: (spec) => `Principal Components: on ${ON[(spec.options && spec.options.on) || 'correlations'] || 'Correlations'}`,
    triangle(ctx) {
      const on = ctx.opt('on', 'correlations');
      return [
        { label: 'Principal Components', submenu: () => Object.entries(ON).map(([v, l]) => ({ label: `on ${l}`, checked: on === v, action: () => { ctx.set('on', v, null, { rerun: false }); ctx.report.app.retitle(ctx.report); ctx.report.run(); } })) },
        ctx.check('Correlations', 'corrmat', null, false), ctx.check('Covariance Matrix', 'covmat', null, false),
        ctx.check('Eigenvalues', 'eigen', null, true), ctx.check('Eigenvectors', 'eigvec', null, false), ctx.check('Bartlett Test', 'bartlett', null, false),
        ctx.check('Loading Matrix', 'loadmat', null, false), ctx.check('Formatted Loading Matrix', 'fmtload', null, false),
        { separator: true },
        ctx.check('Summary Plots', 'summary', null, true), ctx.check('Biplot', 'biplot', null, false), ctx.check('Scree Plot', 'scree', null, false),
        ctx.check('Score Plot', 'score', null, false), ctx.check('Loading Plot', 'loadplot', null, false), ctx.check('Score Ellipses', 'ellipse', null, false),
        { separator: true },
        { label: 'Factor Rotation…', action: () => rotationDialog(ctx) },
        { label: 'Save Columns', submenu: () => [{ label: 'Save Principal Components…', action: () => pcaSave(ctx) }, { label: 'Save Rotated Components', disabled: !ctx.opt('rotation', null), action: () => saveRotated(ctx) }] },
      ];
    },
    render: pcaRender,
  });

  /* ======================================================================
     FACTOR ANALYSIS
     ====================================================================== */
  const FA_METHOD = { ml: 'Maximum Likelihood', pa: 'Principal Axis' };
  const FA_PRIOR = { smc: 'Common Factor Analysis (diagonals = SMC)', pc: 'Principal Components (diagonals = 1)' };

  function eigenTable(ctx, ev) {
    const tbl = ctx.rt({
      columns: [{ key: 'num', label: 'Number', fmt: 'int' }, { key: 'eig', label: 'Eigenvalue', digits: 4 }, { key: 'pct', label: 'Percent', digits: 3 }, { key: 'bar', label: '20 40 60 80', fmt: 'text' }, { key: 'cum', label: 'Cum Percent', digits: 3 }],
      rows: ev.values.map((e, j) => ({ num: j + 1, eig: e, pct: ev.percent[j], cum: ev.cum[j], bar: '' })),
    }, { sortable: false });
    decorate(tbl, (tr, row) => { const td = tr.cells[3]; td.classList.add('mv-barcell'); cellBar(td, Math.max(0, row.pct), 0, 100, SM.report.BAR); });
    return tbl;
  }

  async function faRender(ctx) {
    const names = ctx.names('y');
    const o = (k, d) => ctx.opt(k, d);
    const base = { columns: names, weight: ctx.name('weight'), freq: ctx.name('freq') };
    const pre = await mcall(ctx, 'factor.eigen', base);
    if (pre.error) { ctx.container.append(ctx.warn(pre.error)); return; }
    ctx.container.append(ctx.note(`${fmt(pre.n)} observations of ${names.length} columns, on the correlation matrix${pre.n_rows < ctx.rows.length ? `; ${dropped(ctx.rows.length - pre.n_rows)}` : ''}.`));
    if (o('eigen', true)) ctx.outline('Eigenvalues', { key: 'eigen' }).add(eigenTable(ctx, pre.eigen), ctx.note(`${pre.n_default} eigenvalue${pre.n_default > 1 ? 's' : ''} of at least 1: the default number of factors.`), ctx.code(pre.code));
    if (o('scree', true)) ctx.outline('Scree Plot', { key: 'scree' }).add(screePlot(ctx, pre.eigen.values, 'Eigenvalue', true), ctx.code(pre.scree_code));
    if (o('sphericity', false)) {
      const ob = ctx.outline("Bartlett's Test of Sphericity", { key: 'sphericity' });
      if (pre.sphericity) ob.add(ctx.rt({ columns: [{ key: 'chi2', label: 'ChiSquare', digits: 4 }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: [pre.sphericity] }, { sortable: false }), ctx.note('H0: the correlation matrix is the identity. χ² = −(n − 1 − (2p + 5)/6) ln|R|, p(p − 1)/2 df.'));
      else ob.add(ctx.warn('The correlation matrix is singular.'));
    }
    if (o('kmo', false)) {
      const ob = ctx.outline('Kaiser-Meyer-Olkin Test', { key: 'kmo' });
      if (pre.kmo) {
        ob.add(ctx.kv([['Overall MSA', pre.kmo.overall]]), ctx.rt({ columns: [{ key: 'c', label: 'Column', fmt: 'text' }, { key: 'm', label: 'MSA', digits: 4 }], rows: names.map((c, j) => ({ c, m: pre.kmo.items[j] })) }, { sortable: false }),
          ctx.note('Measure of sampling adequacy: Σr²/(Σr² + Σa²) over pairs, a the partial (anti-image) correlations. Below 0.5 unacceptable, 0.5 miserable, 0.6 mediocre, 0.7 middling, 0.8 meritorious, 0.9 marvelous.'));
      } else ob.add(ctx.warn('Not available: the correlation matrix is singular.'));
    }
    faLaunch(ctx, pre);
    const fits = o('fits', []);
    for (let i = 0; i < fits.length; i++) await faFit(ctx, base, fits[i], i);
  }

  function faLaunch(ctx, pre) {
    const d = { method: 'ml', prior: 'smc', k: pre.n_default, rotation: 'varimax', gamma: null, kaiser: true, ...(ctx.opt('draft', null) || {}) };
    const keep = (patch) => { Object.assign(d, patch); ctx.set('draft', { ...d }, null, { rerun: false }); };
    const kbox = el('input', { type: 'checkbox', 'aria-label': 'Kaiser normalization' });
    kbox.checked = d.kaiser !== false;
    kbox.addEventListener('change', () => keep({ kaiser: kbox.checked }));
    const ob = ctx.outline('Model Launch', { key: 'launch', info: 'fa:launch' });
    ob.add(controls(
      control('Factoring method', selectEl(d.method, Object.entries(FA_METHOD), (v) => keep({ method: v }), 'Factoring method')),
      control('Prior communality', selectEl(d.prior, Object.entries(FA_PRIOR), (v) => keep({ prior: v }), 'Prior communality')),
      control('Number of factors', numberEl(d.k, (v) => keep({ k: v ? Math.round(v) : null }), { size: 3, aria: 'Number of factors' })),
      control('Rotation method', selectEl(d.rotation, [['none', 'None'], ...ROTATIONS], (v) => keep({ rotation: v }), 'Rotation method')),
      control('γ', numberEl(d.gamma, (v) => keep({ gamma: v }), { size: 4, aria: 'gamma' })),
      control('Kaiser normalization', kbox),
      button('Go', () => { const fits = ctx.opt('fits', []); const id = fits.reduce((m, f, k) => Math.max(m, f.id ?? k), -1) + 1; ctx.set('fits', [...fits, { ...d, id }]); }, 'primary'),
    ));
  }

  function sortedLoadings(ctx, L, order, names, fac, thr, caption, blank = false) {
    const tbl = matrixTable(ctx, fac, order.map((i) => L[i]), { rowNames: order.map((i) => names[i]), digits: 4, caption });
    decorate(tbl, (tr, row, i) => { [...tr.cells].forEach((td, j) => { if (j === 0) return; const v = L[order[i]][j - 1]; const small = thr > 0 && Math.abs(v) < thr; td.classList.toggle('mv-dim', small && !blank); td.classList.toggle('mv-blank', small && blank); td.classList.toggle('mv-hit', Math.abs(v) >= Math.max(thr, 0.5)); }); });
    return tbl;
  }

  /* The suppress-small-loadings controls: the threshold and blank or dim. */
  function suppressControls(ctx, thr, blank, scope) {
    const b = el('input', { type: 'checkbox', 'aria-label': 'Blank the suppressed loadings' });
    b.checked = !!blank;
    b.addEventListener('change', () => ctx.set('blank', b.checked, scope));
    return controls(control('Suppress absolute loading values less than', numberEl(thr || '', (v) => ctx.set('suppress', v || 0, scope), { aria: 'Suppress absolute loading values less than' })), control('Blank them (else dimmed)', b));
  }

  // the fit's settings for the backend (factor.fit, factor.save)
  function faPayload(ctx, fit) {
    return { columns: ctx.names('y'), weight: ctx.name('weight'), freq: ctx.name('freq'), n_factors: fit.k, method: fit.method, prior: fit.prior,
      rotation: fit.rotation === 'none' ? null : fit.rotation, gamma: fit.gamma, kaiser: fit.kaiser !== false };
  }

  async function faFit(ctx, base, fit, i) {
    const sc = `fa${fit.id ?? i}`;   // a fit keeps its options when an earlier one is removed
    const r = await mcall(ctx, 'factor.fit', { ...faPayload(ctx, fit), plot: { x: ctx.opt('fx', 0, sc), y: ctx.opt('fy', 1, sc) } });
    const o = (k, d) => ctx.opt(k, d, sc);
    const names = base.columns;
    const title = r.error && !r.k ? 'Factor Analysis' : `Factor Analysis on Correlations with ${r.k} Factor${r.k > 1 ? 's' : ''}: ${FA_METHOD[r.method]}, ${r.rotation_label || 'no'} Rotation`;
    const ob = ctx.outline(title, { key: `fa:${fit.id ?? i}`, info: 'fa:fit', menu: () => faMenu(ctx, r, i, sc, fit) });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    if (r.identify) ob.add(ctx.warn(r.identify));
    const fac = Array.from({ length: r.k }, (_, j) => `Factor ${j + 1}`);
    const thr = o('suppress', 0);
    if (o('prior', false) && r.prior === 'smc') ob.add(ctx.rt({ columns: [{ key: 'c', label: 'Column', fmt: 'text' }, { key: 'v', label: 'Prior Communality (SMC)', digits: 4 }], rows: names.map((c, j) => ({ c, v: r.prior_communality[j] })) }, { sortable: false }));
    if (o('reduced', false) && r.reduced_eigen) ob.add(eigenTable(ctx, r.reduced_eigen), ctx.note('Eigenvalues of the reduced correlation matrix (SMC on the diagonal): the common variance. The cumulative percent can pass 100 because the matrix need not be positive definite.'));
    if (o('unrot', false)) ob.add(sortedLoadings(ctx, r.unrotated, r.order_unrotated, names, fac, thr, 'Unrotated Factor Loading', o('blank', false)));
    if (o('rotmat', false) && r.k > 1) ob.add(matrixTable(ctx, fac, r.rotation_matrix, { rowNames: fac, digits: 5, caption: 'Rotation Matrix' }));
    if (r.oblique) {
      if (o('interfactor', true)) ob.add(matrixTable(ctx, fac, r.phi, { rowNames: fac, digits: 4, caption: 'Interfactor Correlations' }));
      if (o('structure', false)) ob.add(matrixTable(ctx, fac, r.structure, { rowNames: names, digits: 4, caption: 'Factor Structure' }));
    }
    const side = [];
    if (o('comm', true)) side.push(ctx.rt({ columns: [{ key: 'c', label: 'Column', fmt: 'text' }, { key: 'v', label: 'Communality', digits: 4 }, { key: 'u', label: 'Uniqueness', digits: 4, hidden: true }], rows: names.map((c, j) => ({ c, v: r.communality[j], u: r.uniqueness[j] })), caption: 'Final Communality Estimates' }, { sortable: false }));
    if (o('variance', true)) side.push(ctx.rt({ columns: [{ key: 'factor', label: '', fmt: 'text' }, { key: 'variance', label: 'Variance', digits: 4 }, { key: 'percent', label: 'Percent', digits: 3 }, { key: 'cum', label: 'Cum Percent', digits: 3 }], rows: r.variance, caption: r.oblique ? 'Variance Explained by Each Factor Ignoring Other Factors' : 'Variance Explained by Each Factor' }, { sortable: false }));
    if (side.length) ob.add(ctx.row(...side));
    if (r.method === 'ml' && r.ml_test && o('sig', true)) {
      const rows = [];
      if (r.sphericity) rows.push({ test: 'H0: No common factors', chi2: r.sphericity.chi2, df: r.sphericity.df, p: r.sphericity.p });
      rows.push({ test: `H0: ${r.k} factor${r.k > 1 ? 's are' : ' is'} sufficient`, chi2: r.ml_test.chi2, df: r.ml_test.df, p: r.ml_test.p });
      ob.add(ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'chi2', label: 'ChiSquare', digits: 4 }, { key: 'df', label: 'DF' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows, caption: 'Significance Test' }, { sortable: false }),
        ctx.kv([['Criterion (ML discrepancy)', r.ml_test.criterion]]), ctx.note("Bartlett's corrected χ² = (n − 1 − (2p + 5)/6 − 2k/3) × the discrepancy ln|Σ̂| − ln|R| + tr(RΣ̂⁻¹) − p, ((p − k)² − (p + k))/2 df."));
    }
    if (r.method === 'ml' && r.fit && o('fitm', false)) ob.add(ctx.kv([['ChiSquare without Bartlett\'s Correction', r.fit.chi2_uncorrected], ['AIC', r.fit.aic], ['BIC', r.fit.bic], ["Tucker and Lewis's Reliability Coefficient", r.fit.tli], ['RMSEA', r.fit.rmsea]], { caption: 'Measures of Fit' }));
    if (o('scorecoef', false)) ob.add(matrixTable(ctx, fac, r.score_coef, { rowNames: names, digits: 5, caption: 'Standard Score Coefficients' }), ctx.note('Thurstone\'s regression scores: the standardized columns times these coefficients (statsmodels factor_score_params, method regression).'));
    if (o('rotload', true)) {
      const blank = o('blank', false);
      ob.add(suppressControls(ctx, thr, blank, sc),
        sortedLoadings(ctx, r.rotated, r.order, names, fac, thr, r.k > 1 && r.rotation !== 'none' ? 'Rotated Factor Loading' : 'Factor Loading', blank),
        ctx.note(`Columns grouped by the factor they load most on${thr > 0 ? `; loadings below ${fmt(thr)} in absolute value ${blank ? 'left blank' : 'dimmed'}` : ''}; |loading| ≥ 0.5 in colour.${r.kaiser && r.k > 1 && r.rotation !== 'none' ? ' Rotated with Kaiser\'s normalization.' : ''}`));
    }
    if (o('loadplot', true) && r.k >= 2) {
      const a = Math.min(o('fx', 0), r.k - 1), b = Math.min(o('fy', 1), r.k - 1);
      ob.add(loadingPlot(ctx, r.rotated, names, a, b, 380, 340, true, (j) => fac[j]), ctx.code(r.loading_code),
        r.k > 2 ? controls(control('x', selectEl(a, fac.map((f, j) => [j, f]), (v) => ctx.set('fx', +v, sc))), control('y', selectEl(b, fac.map((f, j) => [j, f]), (v) => ctx.set('fy', +v, sc)))) : null);
    }
    if (o('scoreplot', false)) {
      const a = Math.min(o('fx', 0), r.k - 1), b = r.k > 1 ? Math.min(o('fy', 1), r.k - 1) : 0;
      ob.add(ctx.plot([{ type: 'scatter', mode: 'markers', x: r.scores.map((s) => s[a]), y: r.scores.map((s) => (r.k > 1 ? s[b] : 0)), rows: r.rows, hovertext: rowLabels(ctx, r.rows), hovertemplate: '%{hovertext}<br>(%{x:.3f}, %{y:.3f})<extra></extra>' }],
        { xaxis: { title: { text: fac[a] }, zeroline: true }, yaxis: { title: { text: r.k > 1 ? fac[b] : '' }, zeroline: true } }, { width: fitW(420), height: 360, title: 'Score Plot' }), ctx.code(r.score_code));
    }
    ob.add(ctx.code(r.code));
  }

  function faMenu(ctx, r, i, sc, fit) {
    const c = (label, key, d) => ctx.check(label, key, sc, d);
    return [
      c('Prior Communality', 'prior', false), c('Eigenvalues (reduced matrix)', 'reduced', false), c('Unrotated Factor Loading', 'unrot', false), c('Rotation Matrix', 'rotmat', false),
      r.oblique ? c('Interfactor Correlations', 'interfactor', true) : null, r.oblique ? c('Factor Structure', 'structure', false) : null,
      c('Final Communality Estimates', 'comm', true), c('Standard Score Coefficients', 'scorecoef', false), c('Variance Explained by Each Factor', 'variance', true),
      r.method === 'ml' ? c('Significance Test', 'sig', true) : null, r.method === 'ml' ? c('Measures of Fit', 'fitm', false) : null,
      c('Rotated Factor Loading', 'rotload', true), c('Factor Loading Plot', 'loadplot', true), c('Score Plot', 'scoreplot', false),
      { separator: true },
      { label: 'Save Rotated Components', disabled: !!r.error, action: () => saveFrom(ctx, 'factor.save', faPayload(ctx, fit)) },
      { label: 'Remove Fit', action: () => ctx.set('fits', ctx.opt('fits', []).filter((_, k) => k !== i)) },
    ].filter(Boolean);
  }

  SM.platforms.register({
    id: 'factor', label: 'Factor Analysis', menu: 'Analyze/Multivariate Methods', order: 40, info: 'p:factor',
    about: 'Common factor analysis on the correlation matrix: maximum likelihood or principal axis extraction (statsmodels Factor), SMC or unit prior communalities, the number of factors from the eigenvalues, orthogonal and oblique rotations, the significance tests of the maximum likelihood fit, loading and score plots, and the factor scores saved as formula columns.',
    uses: ['statsmodels.multivariate.factor.Factor', 'statsmodels.multivariate.factor_rotation.rotate_factors', 'scipy.stats.chi2'],
    topics: {
      'p:factor': {
        kicker: 'Analyze > Multivariate Methods', title: 'Factor Analysis',
        lead: 'Models the correlations of the columns by a few unobserved factors. The report starts with the eigenvalues and a scree plot; choose the model in Model Launch and press Go. Each Go adds a fit.',
        sections: [
          { heading: 'Model Launch', choices: [['Maximum Likelihood', 'Tests the number of factors; needs a positive definite correlation matrix.'], ['Principal Axis', 'Eigenvectors of the reduced correlation matrix, communalities iterated (statsmodels\' default of 50 iterations).'], ['Prior communality', 'SMC (common factor analysis) or 1 (principal components).'], ['Rotation', 'Orthogonal (varimax …) or oblique (promax, quartimin …); Kaiser\'s normalization as SAS.']] },
          { heading: 'Scores', text: 'Save Rotated Components makes Thurstone\'s regression scores (statsmodels factor_score_params, method regression) of the standardized columns formula columns: the score coefficients times each column less its mean over its standard deviation (of the report\'s rows), so every row whose columns are present is scored, excluded rows too.' },
          { heading: 'Differences from JMP', text: 'Only the correlation matrix and row-wise deletion are offered. Equamax is orthomax with γ = k/2 and factor parsimax γ = p, as SAS defines them (statsmodels\' own equamax uses γ = 1/p). Promax is Hendrickson and White\'s with power 3 (statsmodels\' promax differs). Signs and order of factors are arbitrary: each factor is made to have a positive loading sum.' },
        ],
        more: { label: 'Factor Analysis', id: 'help-p-factor' },
      },
      'fa:launch': {
        kicker: 'Factor Analysis', title: 'Model Launch', lead: 'Set the factoring method, the prior communalities, the number of factors (default: the eigenvalues of at least one) and the rotation, then press Go. γ is the weight of the Orthomax and Oblimin families. Each Go adds a fit report below; Remove Fit in its red triangle takes it away.',
        sections: [{ heading: 'The controls', choices: [
          ['Factoring method', 'Maximum Likelihood, the default: the factors that make the correlations most likely, with tests of whether they are enough; it needs a positive definite correlation matrix. Principal Axis: the eigenvectors of the correlation matrix with communalities on its diagonal, iterated (statsmodels, 50 iterations).'],
          ['Prior communality', 'The diagonal Principal Axis starts from: Common Factor Analysis puts each column\'s squared multiple correlation (SMC) there, Principal Components 1. Maximum likelihood estimates the communalities itself and does not use it.'],
          ['Number of factors', 'How many factors to extract; empty takes the number of eigenvalues of at least 1. Maximum likelihood takes at most one fewer than the columns, and warns when the model is not identified.'],
          ['Rotation method', `None, or a rotation of the loadings. ${ROTATION_HELP}`],
          ['γ', GAMMA_HELP],
          ['Kaiser normalization', KAISER_HELP],
          ['Go', 'Fit the model with these settings and add its report below; each Go adds another, and the settings stay for the next one.']] }],
        more: { label: 'Factor Analysis', id: 'help-p-factor' },
      },
      'fa:fit': {
        kicker: 'Factor Analysis', title: 'A factor fit', lead: 'Communalities (the share of each column\'s variance the factors take up), the variance each factor explains, the loadings sorted so that columns of the same factor are together, and for maximum likelihood the tests of no common factors (Bartlett\'s sphericity) and of enough factors. The red triangle shows the rest and saves the factor scores.',
        sections: [{ heading: 'In the report', choices: [
          ['Suppress absolute loading values less than', 'Loadings smaller than this in absolute value are dimmed (or blanked) in the loading tables, so that the pattern stands out; empty or 0 shows them all. Loadings of 0.5 or more are in colour.'],
          ['Blank them (else dimmed)', 'Leave the suppressed loadings empty instead of dimming them.'],
          ['x, y', 'With three or more factors: the factors on the axes of the loading plot and of the score plot.']] }],
        more: { label: 'Factor Analysis', id: 'help-p-factor' },
      },
    },
    launch: {
      lead: 'Choose the numeric columns (three or more for maximum likelihood). Then choose the model in the report\'s Model Launch and press Go.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 2, numeric: true, types: ['continuous', 'ordinal'], hint: 'required: numeric',
          help: 'The columns to factor, through their correlation matrix; maximum likelihood needs three or more. Rows with a missing value in any of them are left out.' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'Case weights of the correlation matrix. Rows with a missing, zero or negative weight are left out.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'A count per row: the row stands for that many observations, in the correlations and in the tests\' degrees of freedom.' },
        { key: 'by', label: 'By', hint: 'optional', help: BY_HELP },
      ],
    },
    title: () => 'Factor Analysis',
    triangle(ctx) {
      return [ctx.check('Eigenvalues', 'eigen', null, true), ctx.check('Scree Plot', 'scree', null, true), ctx.check("Bartlett's Test of Sphericity", 'sphericity', null, false), ctx.check('Kaiser-Meyer-Olkin Test', 'kmo', null, false)];
    },
    render: faRender,
  });

  /* ======================================================================
     DISCRIMINANT
     ====================================================================== */
  const DISC = { linear: 'Linear, Common Covariance', quadratic: 'Quadratic, Different Covariances', regularized: 'Regularized, Compromise Method' };
  const SETS = ['Training', 'Validation', 'Test'];   // a Validation column's sets, 0, 1 and 2
  const PRIORS = { equal: 'Equal Probabilities', proportional: 'Proportional to Occurrence', other: 'Other' };

  // the fit's settings for the backend (discriminant.fit, discriminant.save)
  function discPayload(ctx, ycols) {
    const o = (k, d) => ctx.opt(k, d);
    return { y: ycols, x: ctx.name('x'), weight: ctx.name('weight'), freq: ctx.name('freq'), method: o('method', 'linear'), lam: o('lam', 0.5), gam: o('gam', 0), priors: o('priors', 'equal'), prior_values: o('priorValues', null), validation: ctx.name('validation') };
  }

  function discCall(ctx, ycols) {
    const o = (k, d) => ctx.opt(k, d);
    return mcall(ctx, 'discriminant.fit', { ...discPayload(ctx, ycols), alpha: ctx.alpha, curves: !!(o('roc', false) || o('lift', false)), decision: !!o('threshold', false),
      plot: { points: !!o('cpPoints', true), cl: !!o('cpCL', true), c50: !!o('cp50', false), rays: !!o('cpRays', true), splom: o('splom', false) ? discSplomSize(ctx, ycols) : null } });
  }

  function discColumns(ctx) {
    const all = ctx.names('y');
    const model = ctx.opt('model', null);
    return model && model.length ? all.filter((c) => model.includes(c)) : all;
  }

  async function discRender(ctx) {
    const o = (k, d) => ctx.opt(k, d);
    const all = ctx.names('y');
    const ycols = discColumns(ctx);
    const xcol = ctx.role('x');
    if (o('stepwise', false)) await stepwisePanel(ctx, all, xcol.name);
    const res = await discCall(ctx, ycols);
    const box = ctx.container;
    if (res.error) { box.append(ctx.warn(res.error)); return; }
    const labels = res.levels.map((v) => SM.grid.cellText(xcol, v));
    if (!ctx.headless) ctx.report._discLevels = labels.length;   // the red triangle's Decision Threshold (two groups)
    const method = o('method', 'linear');
    const vname = ctx.name('validation');
    box.append(ctx.kv([['Discriminant Method', DISC[method] + (method === 'regularized' ? ` (λ = ${fmt(res.lam)}, γ = ${fmt(res.gam)})` : ''), 'text'], ['Classification', xcol.name, 'text'], ['Priors', PRIORS[o('priors', 'equal')], 'text'], ycols.length < all.length ? ['Columns', ycols.join(', '), 'text'] : null,
      vname ? ['Validation', `${vname}: the model is fitted to the ${fmt(res.n_rows)} training rows and scores every row`, 'text'] : null]));
    for (const n of res.notes || []) box.append(ctx.note(n));
    if (ctx.name('weight') || ctx.name('freq')) box.append(ctx.note('With Weight or Freq the means, covariances and probabilities are weighted; the multivariate tests of Canonical Details count rows, not the sum of the weights, in their degrees of freedom.'));
    if (o('canplot', true)) canonicalPlot(ctx, res, labels, ycols);
    if (o('scores', true)) discScores(ctx, res, labels);
    scoreSummaries(ctx, res, labels);
    if (res.fit && o('roc', false)) SM.predict.rocCurves(ctx, null, res.fit, 'disc:');
    if (res.fit && o('lift', false)) SM.predict.liftCurves(ctx, null, res.fit, 'disc:');
    if (res.threshold && o('threshold', false)) discThreshold(ctx, res);
    if (o('splom', false)) discSplom(ctx, res, labels, ycols);
    if (o('dist', false)) ctx.outline('Squared Distances to Each Group', { key: 'dist' }).add(ctx.rt({ columns: [{ key: 'row', label: 'Row', fmt: 'int' }, ...labels.map((l, t) => ({ key: `d${t}`, label: `SqDist[${l}]`, digits: 4 }))], rows: res.rows.map((r, k) => Object.assign({ row: r + 1 }, ...labels.map((_, t) => ({ [`d${t}`]: res.sqdist[k][t] })))) }, { maxRows: 500 }), ctx.note('d² − 2 log(prior), plus log|S| of the group for the quadratic and regularized methods; the smallest wins.'));
    if (o('probs', false)) ctx.outline('Probabilities to Each Group', { key: 'probs' }).add(ctx.rt({ columns: [{ key: 'row', label: 'Row', fmt: 'int' }, ...labels.map((l, t) => ({ key: `p${t}`, label: `Prob[${l}]`, digits: 4 }))], rows: res.rows.map((r, k) => Object.assign({ row: r + 1 }, ...labels.map((_, t) => ({ [`p${t}`]: res.prob[k][t] })))) }, { maxRows: 500 }));
    if (o('candetails', false)) canonicalDetails(ctx, res, labels, ycols);
    if (o('canstruct', false) && res.canonical) {
      const C = res.canonical;
      const cn = Array.from({ length: C.m }, (_, j) => `Canon${j + 1}`);
      const ob = ctx.outline('Canonical Structure', { key: 'canstruct' });
      ob.add(matrixTable(ctx, cn, C.total_struct, { rowNames: ycols, digits: 4, caption: 'Total Canonical Structure' }), matrixTable(ctx, cn, C.between_struct, { rowNames: ycols, digits: 4, caption: 'Between Canonical Structure' }),
        matrixTable(ctx, cn, C.within_struct, { rowNames: ycols, digits: 4, caption: 'Pooled Within Canonical Structure' }), matrixTable(ctx, cn, C.means, { rowNames: labels, digits: 4, caption: 'Class Means on Canonical Variables' }));
    }
    if (o('groupmeans', false)) ctx.outline('Group Means', { key: 'groupmeans' }).add(matrixTable(ctx, ycols, [...res.means, res.grand_mean], { rowNames: [...labels, 'All'], digits: 5 }), ctx.rt({ columns: [{ key: 'l', label: xcol.name, fmt: 'text' }, { key: 'n', label: 'Count' }], rows: labels.map((l, t) => ({ l, n: res.counts[t] })) }, { sortable: false }));
    if (o('withincov', false)) {
      const ob = ctx.outline('Covariance Matrices', { key: 'withincov' });
      ob.add(matrixTable(ctx, ycols, res.pooled_cov, { caption: 'Pooled Within Covariance Matrix' }), matrixTable(ctx, ycols, res.pooled_corr, { digits: 4, caption: 'Pooled Within Correlation Matrix' }));
      if (method !== 'linear') labels.forEach((l, t) => ob.add(matrixTable(ctx, ycols, res.group_cov[t], { caption: `Covariance of ${l} (log|S| = ${fmt(res.logdet[t])})` })));
    }
    box.append(ctx.code(res.code));
  }

  function canonicalPlot(ctx, res, labels, ycols) {
    const o = (k, d) => ctx.opt(k, d);
    const ob = ctx.outline('Canonical Plot', { key: 'canplot' });
    const C = res.canonical;
    if (!C || !C.m) { ob.add(ctx.note('No canonical variables: the groups do not differ, or the covariance is singular.')); return; }
    const tc = SM.util.themeColors();
    const two = C.m >= 2;
    const T = labels.length;
    const jitter = (k) => { const h = Math.sin(k * 12.9898 + 78.233) * 43758.5453; return (h - Math.floor(h) - 0.5) * 0.5; };
    const xs = C.scores.map((s) => s[0]);
    const ys = two ? C.scores.map((s) => s[1]) : res.actual.map((a, k) => a + jitter(k));
    const traces = [];
    const setName = (k) => (res.sets ? ` (${SETS[res.sets[k]]})` : '');
    if (o('cpPoints', true)) traces.push({ type: 'scatter', mode: 'markers', x: xs, y: ys, rows: res.rows, showlegend: false, marker: { size: 6, color: res.actual.map((a) => pal(a)), ...(res.sets ? { symbol: res.sets.map((q) => (q ? 'circle-open' : 'circle')), line: { width: 1.4, color: res.actual.map((a) => pal(a)) } } : {}) }, hovertext: res.rows.map((r, k) => `${rowLabels(ctx, [r])[0]}${setName(k)}<br>${labels[res.actual[k]]} → ${labels[res.pred[k]]}`), hovertemplate: '%{hovertext}<extra></extra>', name: 'rows' });
    labels.forEach((l, t) => {
      const mx = C.means[t][0], my = two ? C.means[t][1] : t;
      traces.push({ type: 'scatter', mode: 'markers', x: [mx], y: [my], marker: { symbol: 'cross-thin-open', size: 16, line: { width: 2.2, color: pal(t) }, color: pal(t) }, name: l, showlegend: true, hovertemplate: `${tpl(l)} mean<extra></extra>` });
      if (o('cpCL', true)) {
        const rad = Math.sqrt(chi2Inv2(0.95) / res.counts[t]);
        if (two) { const e = ellipse(mx, my, rad / Math.sqrt(chi2Inv2(0.95)), rad / Math.sqrt(chi2Inv2(0.95)), 0, 0.95); traces.push({ type: 'scatter', mode: 'lines', x: e.x, y: e.y, line: { color: pal(t), width: 1.4 }, hoverinfo: 'skip', showlegend: false }); }
        else { const h = 1.96 / Math.sqrt(res.counts[t]); traces.push({ type: 'scatter', mode: 'lines', x: [mx - h, mx + h], y: [my, my], line: { color: pal(t), width: 3 }, hoverinfo: 'skip', showlegend: false }); }
      }
      if (o('cp50', false)) {
        if (two) { const e = ellipse(mx, my, 1, 1, 0, 0.5); traces.push({ type: 'scatter', mode: 'lines', x: e.x, y: e.y, line: { color: pal(t), width: 1, dash: 'dot' }, hoverinfo: 'skip', showlegend: false }); }
        else { const h = 0.6745; traces.push({ type: 'scatter', mode: 'lines', x: [mx - h, mx + h], y: [my + 0.3, my + 0.3], line: { color: pal(t), width: 1, dash: 'dot' }, hoverinfo: 'skip', showlegend: false }); }
      }
    });
    const annotations = [];
    if (o('cpRays', true)) {
      const s = 1.5;
      const ox = 0, oy = two ? 0 : T - 0.5;
      ycols.forEach((c, j) => {
        const dx = s * C.std[j][0], dy = two ? s * C.std[j][1] : 0.25 * (j + 1) / ycols.length;
        traces.push({ type: 'scatter', mode: 'lines', x: [ox, ox + dx], y: [oy, oy + dy], line: { color: tc.muted, width: 1.2 }, hoverinfo: 'skip', showlegend: false });
        annotations.push({ x: ox + dx, y: oy + dy, ax: ox, ay: oy, xref: 'x', yref: 'y', axref: 'x', ayref: 'y', showarrow: true, arrowhead: 2, arrowsize: 1, arrowwidth: 1.2, arrowcolor: tc.muted, text: '' });
        annotations.push({ x: ox + dx, y: oy + dy, text: c, showarrow: false, xanchor: dx >= 0 ? 'left' : 'right', font: { size: 10.5, color: tc.text } });
      });
    }
    ob.add(ctx.plot(traces, {
      showlegend: true, legend: { orientation: 'h', y: -0.2 }, annotations,
      xaxis: { title: { text: 'Canonical1' }, zeroline: true },
      yaxis: two ? { title: { text: 'Canonical2' }, zeroline: true, scaleanchor: 'x' } : { title: { text: '' }, tickvals: labels.map((_, t) => t), ticktext: labels, range: [-0.8, T + 0.2] },
    }, { width: fitW(540), height: two ? 460 : 320, title: 'Canonical Plot' }), ctx.code(res.canonical_code),
    ctx.note(`${two ? 'The first two canonical variables' : 'The canonical variable (two groups)'}: the directions that separate the groups best, scaled to unit pooled within-group variance. + marks each group mean${o('cpCL', true) ? ', with its 95% confidence region' : ''}${o('cp50', false) ? '; dotted: where half of a group\'s rows fall' : ''}${o('cpRays', true) ? '; the rays are the standardized scoring coefficients × 1.5' : ''}.${res.sets ? ' Open circles: the validation (and test) rows, scored by the training rows\' fit.' : ''}`));
  }

  function discScores(ctx, res, labels) {
    const o = (k, d) => ctx.opt(k, d);
    const interesting = o('interesting', false);
    const rowsAll = res.rows.map((r, k) => {
      const pp = res.prob[k][res.pred[k]];
      const others = res.prob[k].map((p, t) => [p, t]).filter(([p, t]) => t !== res.pred[k] && p > 0.1).map(([p, t]) => `${labels[t]} ${p.toFixed(2)}`).join(', ');
      return { k, row: r + 1, set: res.sets ? SETS[res.sets[k]] : null, actual: labels[res.actual[k]], sq: res.sqdist[k][res.actual[k]], pa: res.prob_actual[k], nl: res.neg_log_prob[k], bar: '', mis: res.misclassified[k] ? '*' : '', pred: labels[res.pred[k]], pp, others };
    });
    const rows = interesting ? rowsAll.filter((x) => x.mis || (x.pp > 0.05 && x.pp < 0.95)) : rowsAll;
    const ob = ctx.outline('Discriminant Scores', { key: 'scores', menu: () => [ctx.check('Show Interesting Rows Only', 'interesting', null, false), { label: 'Select Misclassified Rows', action: () => ctx.table.select(res.rows.filter((_, k) => res.misclassified[k])) }] });
    const mx = Math.max(1, ...res.neg_log_prob.filter(Number.isFinite));
    const sc = res.sets ? 1 : 0;   // the Set column shifts the bar's cell
    const tbl = ctx.rt({
      columns: [{ key: 'row', label: 'Row', fmt: 'int' }, ...(res.sets ? [{ key: 'set', label: 'Set', fmt: 'text' }] : []), { key: 'actual', label: 'Actual', fmt: 'text' }, { key: 'sq', label: 'SqDist(Actual)', digits: 4 }, { key: 'pa', label: 'Prob(Actual)', digits: 4 },
        { key: 'nl', label: '−Log(Prob)', digits: 4 }, { key: 'bar', label: '', fmt: 'text' }, { key: 'mis', label: '', fmt: 'text' }, { key: 'pred', label: 'Predicted', fmt: 'text' }, { key: 'pp', label: 'Prob(Pred)', digits: 4 }, { key: 'others', label: 'Others', fmt: 'text' }],
      rows,
    }, { maxRows: 400, onRow: (r, ev) => ctx.table.select([res.rows[r.k]], ev.shiftKey ? 'add' : 'replace') });
    decorate(tbl, (tr, row) => { const td = tr.cells[5 + sc]; td.classList.add('mv-barcell'); cellBar(td, row.nl, 0, mx, row.mis ? RED : SM.report.BAR); tr.cells[6 + sc].classList.toggle('mv-hit', !!row.mis); tr.classList.toggle('mv-validation', !!row.set && row.set !== 'Training'); });
    const open = res.sets ? res.sets.map((q) => q > 0) : null;
    const plot = ctx.plot([{ type: 'scatter', mode: 'markers', x: res.rows.map((r) => r + 1), y: res.neg_log_prob, rows: res.rows, marker: { size: 6, color: res.misclassified.map((m) => (m ? RED : SM.report.BASE)), symbol: res.misclassified.map((m, k) => (m ? (open && open[k] ? 'x-open' : 'x') : (open && open[k] ? 'circle-open' : 'circle'))) }, hovertext: res.rows.map((r, k) => `${rowLabels(ctx, [r])[0]}${res.sets ? ` (${SETS[res.sets[k]]})` : ''}: ${labels[res.actual[k]]} → ${labels[res.pred[k]]}`), hovertemplate: '%{hovertext}<br>−log(prob) %{y:.3f}<extra></extra>' }],
      { xaxis: { title: { text: 'Row Number' } }, yaxis: { title: { text: '−Log(Prob(Actual))' }, rangemode: 'tozero' } }, { width: fitW(520), height: 230, title: 'Discriminant scores by row' });
    ob.add(tbl, plot, ctx.code(res.scores_code), ctx.note(`${interesting ? 'Misclassified rows and rows whose predicted probability is between 0.05 and 0.95. ' : ''}* marks a misclassified row; a click on a line selects the row. The bar is −log of the probability of the actual group: long bars are rows the model predicts badly.${res.sets ? ' Set: the row\'s set in the Validation column; the validation and test rows (in italics, open marks in the graph) are scored by the fit to the training rows.' : ''}`));
  }

  function scoreSummaries(ctx, res, labels) {
    const ob = ctx.outline('Score Summaries', { key: 'summary', menu: () => [ctx.check('Show Classification Counts', 'counts', null, true)] });
    const sums = res.summaries || [{ set: 'Training', ...res.summary }];
    ob.add(ctx.rt({ columns: [{ key: 'src', label: 'Source', fmt: 'text' }, { key: 'nm', label: 'Number Misclassified' }, { key: 'pm', label: 'Percent Misclassified', digits: 4 }, { key: 'er2', label: 'Entropy RSquare', digits: 4 }, { key: 'm2', label: '−2LogLikelihood', digits: 5 }, { key: 'n', label: 'N', hidden: true }],
      rows: sums.map((S) => ({ src: S.set, nm: S.n_mis, pm: S.pct_mis, er2: S.entropy_r2, m2: S.m2ll, n: S.n })) }, { sortable: false }));
    if (ctx.opt('counts', true)) {
      const cm = (M, fmtKey, caption, digits) => {
        const tbl = matrixTable(ctx, labels, M, { fmtKey, caption, digits, rowNames: labels });
        tbl.querySelector('thead th').textContent = 'Actual \\ Predicted';
        decorate(tbl, (tr, row, i) => { [...tr.cells].forEach((td, j) => { if (j > 0) td.classList.toggle('mv-hit', j - 1 !== i && M[i][j - 1] > 0); }); });
        return tbl;
      };
      const confs = res.confusions || [{ set: 'Training', matrix: res.confusion }];
      for (const c of confs) {
        const rates = c.matrix.map((row) => { const s = row.reduce((a, b) => a + b, 0); return row.map((v) => (s ? v / s : null)); });
        const pre = res.confusions ? `${c.set}: ` : '';
        ob.add(ctx.row(cm(c.matrix, 'num', `${pre}Confusion Matrix (counts)`, 0), cm(rates, 'num', `${pre}Confusion Rates`, 4)));
      }
    }
    ob.add(ctx.note(`Entropy RSquare: 1 − log likelihood of the model / log likelihood of the group shares alone (the training rows' shares); 1 is perfect classification.${res.summaries ? ' The validation and test rows are scored by the model the training rows fit: their misclassification is the honest measure.' : ''}`));
  }

  /* The Decision Threshold (two groups): SM.predict's report of the second
     group's probability; Save Threshold Formula reads the Prob[] columns
     (saved as values of every row first when they are not in the table). */
  function discThreshold(ctx, res) {
    SM.predict.threshold(ctx, null, res.threshold, { scope: null, prefix: 'disc:', yCol: ctx.role('x'), probName: (label) => `Prob[${label}]`,
      save: { fn: 'discriminant.probs', payload: { ...discPayload(ctx, discColumns(ctx)), where: ctx.where || [] } } });
  }

  /* The Scatterplot Matrix (JMP's option): the covariates two by two below the
     diagonal, the rows in their groups' colours, each group's normal ellipse
     (its mean and the covariance the method uses: the pooled within
     covariance for the linear method) covering 90% of the group. */
  const discSplomSize = (ctx, ycols) => ({ ...splomSize(ycols.length, 'lower'), level: ctx.opt('spLevel', 0.9), shaded: !!ctx.opt('spShaded', false) });
  function discSplom(ctx, res, labels, ycols) {
    const ob = ctx.outline('Scatterplot Matrix', { key: 'dsplom', info: 'disc:splom', menu: () => [
      { label: 'Ellipse Coverage', submenu: () => [0.5, 0.9, 0.95, 0.99].map((a) => ({ label: String(a), checked: ctx.opt('spLevel', 0.9) === a, action: () => ctx.set('spLevel', a) })) },
      ctx.check('Shaded Ellipses', 'spShaded', null, false),
      { label: 'Remove', action: () => ctx.set('splom', false) }] });
    if (ycols.length < 2) { ob.add(ctx.note('The scatterplot matrix needs two or more covariates.')); return; }
    if (ycols.length > 16) { ob.add(ctx.note(`${ycols.length} covariates: the scatterplot matrix is drawn for up to 16.`)); return; }
    const cols = ycols.map((n) => ctx.table.col(n));
    const of = new Map(res.rows.map((r, k) => [r, res.actual[k]]));
    const open = res.sets ? new Set(res.rows.filter((_, k) => res.sets[k] > 0)) : null;
    const level = ctx.opt('spLevel', 0.9);
    ob.add(scatterMatrix(ctx, cols, res.rows, { format: 'lower', points: true, ellipses: true, shaded: ctx.opt('spShaded', false), corr: false, hist: false, fit: false, level,
      groups: { of, open, names: labels, means: res.means, covs: res.model_cov }, code: res.splom_code }, []));
    ob.add(ctx.note(`Each group's normal ellipse holds ${fmt(100 * level)}% of it: the group's mean and the covariance the ${ctx.opt('method', 'linear') === 'linear' ? 'linear method pools over the groups' : 'method gives the group'}${res.sets ? ', from the training rows; open circles are the validation and test rows' : ''}. Drag over points to select rows.`));
  }

  function canonicalDetails(ctx, res, labels, ycols) {
    const C = res.canonical;
    const ob = ctx.outline('Canonical Details', { key: 'candetails' });
    if (!C) { ob.add(ctx.warn('Not available.')); return; }
    ob.add(ctx.rt({
      columns: [{ key: 'eig', label: 'Eigenvalue', digits: 5 }, { key: 'pct', label: 'Percent', digits: 4 }, { key: 'cum', label: 'Cum Percent', digits: 4 }, { key: 'cc', label: 'Canonical Corr', digits: 5 }, { key: 'lr', label: 'Likelihood Ratio', digits: 5 },
        { key: 'F', label: 'Approx. F', digits: 4 }, { key: 'nd', label: 'NumDF' }, { key: 'dd', label: 'DenDF' }, { key: 'p', label: 'Prob>F', fmt: 'p' }],
      rows: C.eigen.map((e, j) => ({ eig: e, pct: C.percent[j], cum: C.cum[j], cc: C.cancorr[j], lr: C.lr[j], F: C.lr_tests[j].F, nd: C.lr_tests[j].numdf, dd: C.lr_tests[j].dendf, p: C.lr_tests[j].p })),
    }, { sortable: false }));
    ob.add(ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'value', label: 'Value', digits: 6 }, { key: 'F', label: 'Approx. F', digits: 4 }, { key: 'numdf', label: 'NumDF' }, { key: 'dendf', label: 'DenDF' }, { key: 'p', label: 'Prob>F', fmt: 'p' }], rows: res.tests }, { sortable: false }),
      ctx.note("Eigenvalues of E⁻¹H (H the between-groups, E the pooled within-groups cross products). The likelihood ratio of a row tests that its canonical correlation and all smaller ones are zero (Rao's F). The four tests are statsmodels MANOVA's; Roy's F is an upper bound."));
    const cn = Array.from({ length: C.m }, (_, j) => `Canon${j + 1}`);
    ob.add(matrixTable(ctx, ycols, res.pooled_cov, { caption: 'Within Matrix (pooled within covariance)' }), matrixTable(ctx, cn, C.raw, { rowNames: ycols, digits: 5, caption: 'Scoring Coefficients' }), matrixTable(ctx, cn, C.std, { rowNames: ycols, digits: 5, caption: 'Standardized Scoring Coefficients' }),
      ctx.note('The scoring coefficients make canonical variables with unit pooled within-group variance (their scores are centred at the grand mean); the standardized coefficients are for the columns scaled by their pooled within-group standard deviations.'));
  }

  async function stepwisePanel(ctx, all, x) {
    const entered = ctx.opt('entered', []);
    const r = await ctx.call('discriminant.stepwise', { y: all, x, entered, weight: ctx.name('weight'), freq: ctx.name('freq'), validation: ctx.name('validation') });
    if (r.error) { ctx.outline('Column Selection', { key: 'stepwise', info: 'disc:stepwise' }).add(ctx.warn(r.error)); return; }
    const ob = ctx.outline('Column Selection', { key: 'stepwise', info: 'disc:stepwise' });
    const setE = (list) => ctx.set('entered', list);
    const outs = r.columns.filter((c) => !c.entered && c.p != null).sort((a, b) => a.p - b.p);
    const ins = r.columns.filter((c) => c.entered && c.p != null).sort((a, b) => b.p - a.p);
    ob.add(ctx.kv([['Columns In', r.n_in, 'int'], ['Columns Out', r.n_out, 'int'], ['Smallest P to Enter', r.smallest_p_enter, 'p'], ['Largest P to Remove', r.largest_p_remove, 'p']]),
      controls(button('Step Forward', () => { if (outs.length) setE([...entered, outs[0].column]); }), button('Step Backward', () => { if (ins.length) setE(entered.filter((c) => c !== ins[0].column)); }),
        button('Enter All', () => setE(all.slice())), button('Remove All', () => setE([])), button('Apply This Model', () => ctx.set('model', entered.length ? entered.slice() : null), 'primary')),
      ctx.rt({ columns: [{ key: 'e', label: 'Entered', fmt: 'text' }, { key: 'column', label: 'Column', fmt: 'text' }, { key: 'F', label: 'F Ratio', digits: 5 }, { key: 'p', label: 'Prob > F', fmt: 'p' }], rows: r.columns.map((c) => ({ ...c, e: c.entered ? '✓' : '' })) },
        { sortable: false, onRow: (row) => setE(row.entered ? entered.filter((c) => c !== row.column) : [...entered, row.column]) }),
      ctx.note('F and Prob > F: the analysis-of-covariance test of the categories with the column as the response and the entered columns as covariates (statsmodels OLS). Click a line to enter or remove a column; Apply This Model refits with the entered columns.'));
  }

  /* Save Formulas (JMP's): SqDist[group], Prob[group] and Pred <X> as formula
     columns, from the report's fit (its training rows, with a Validation
     column), so every row whose covariates are present is scored. */
  function discSave(ctx, what = 'formulas') {
    const xcol = ctx.role('x');
    return saveFrom(ctx, 'discriminant.save', { ...discPayload(ctx, discColumns(ctx)), what }).then((made) => {
      const pred = made.find((c) => c.name.startsWith(`Pred ${xcol.name}`));
      if (pred && xcol.valueOrder && !pred.valueOrder) { pred.valueOrder = xcol.valueOrder.slice(); ctx.table._changed('schema', { info: pred.id }); }
      return made;
    });
  }

  SM.platforms.register({
    id: 'discriminant', label: 'Discriminant', menu: 'Analyze/Multivariate Methods', order: 30, info: 'p:discriminant',
    about: 'Classifies rows into the groups of a categorical column from continuous covariates: linear (pooled covariance), quadratic and regularized discriminant analysis, posterior probabilities and squared distances, the canonical plot with biplot rays and confidence regions of the means, the classification summary with a Validation column\'s sets (JMP Pro), ROC and lift curves, the Decision Threshold of two groups, a scatterplot matrix with the groups\' ellipses, the multivariate tests, stepwise selection, and Save Formulas: squared distances, probabilities and the predicted group as live formula columns.',
    uses: ['numpy, scipy.linalg.eigh (canonical analysis)', 'statsmodels.multivariate.manova.MANOVA', 'statsmodels.api.OLS (stepwise F tests)'],
    topics: {
      'p:discriminant': {
        kicker: 'Analyze > Multivariate Methods', title: 'Discriminant',
        lead: 'Predicts the group (X, Categories) of each row from continuous covariates (Y, Covariates), assuming normal covariates within each group. Each row goes to the group with the largest posterior probability.',
        sections: [
          { heading: 'Methods', choices: [['Linear', 'One covariance matrix for all groups (pooled): the boundaries are linear.'], ['Quadratic', 'Each group its own covariance matrix; needs enough rows per group.'], ['Regularized', 'Σ = (1 − γ)(λS_p + (1 − λ)S_t) + γ diag(…): λ = 1 is linear, λ = 0 quadratic; γ shrinks toward the diagonal.']] },
          { heading: 'Canonical plot', text: 'The canonical variables are the linear combinations that separate the groups best, scaled to unit variance within groups. Circles are 95% confidence regions of the group means; rays are the standardized scoring coefficients.' },
          { heading: 'Priors', text: 'Equal Probabilities is the default, as JMP\'s help has it; Proportional to Occurrence takes the training rows\' shares, Other the priors given.' },
          { heading: 'Validation', text: 'With a Validation column (JMP Pro) the discriminant is fitted to the training rows and every row is scored: the Score Summaries and the confusion counts of each set, the Set of each row in Discriminant Scores, open marks for the validation and test rows in the graphs. The validation rows\' misclassification is the honest measure of the rule.' },
          { heading: 'Score Options', choices: [['ROC Curve, Lift Curve', 'Each group against the others by its probability, per set (the Predictive Modeling platforms\' curves; rows counted by Weight × Freq).'], ['Decision Threshold', 'With two groups: the rule "the second group when its probability is at least the threshold", its counts and measures at any threshold, and Save Threshold Formula.'], ['Save Formulas', 'SqDist[group], Prob[group] and Pred <X> as formula columns (JMP\'s): every row whose covariates are present is scored, excluded rows too, and a changed value is scored again.']] },
          { heading: 'Scatterplot Matrix', text: 'The covariates two by two with each group\'s 90% normal ellipse from the covariance the method uses (pooled for the linear method, the group\'s own for the quadratic one).' },
          { heading: 'Differences from JMP', text: 'The Wide Linear method, shrinkage of covariances, the Precision Recall Curve, Consider New Levels and the profiler are not here. The four multivariate tests are statsmodels MANOVA\'s. JMP\'s Scatterplot Matrix opens its own platform; here it is part of the report. A validation row of a group the training rows lack is left out (the rule has no mean for it).' },
        ],
        more: { label: 'Discriminant', id: 'help-p-discriminant' },
      },
      'disc:splom': {
        kicker: 'Discriminant', title: 'Scatterplot Matrix',
        lead: 'The covariates two by two, below the diagonal as JMP draws it: every row in its group\'s colour, and for each group the normal ellipse that holds 90% of it (Ellipse Coverage, red triangle), from the group\'s mean and the covariance the method uses: the pooled within covariance for Linear, each group\'s own for Quadratic, the compromise for Regularized. Ellipses of one size and shape are what the linear method assumes; very different ones favour the quadratic method.',
        sections: [{ heading: 'In the report', choices: [['The points', 'Drag over them to select rows; open circles are the validation and test rows.']] }],
        more: { label: 'Discriminant', id: 'help-p-discriminant' },
      },
      'disc:stepwise': {
        kicker: 'Discriminant', title: 'Stepwise variable selection', lead: 'Step Forward enters the column with the smallest Prob > F, Step Backward removes the entered one with the largest. The F tests the categories in an analysis of covariance of the column on the entered ones. Apply This Model fits the discriminant with the entered columns.',
        sections: [{ heading: 'In the report', choices: [
          ['Step Forward', 'Enter the column not yet entered with the smallest Prob > F.'],
          ['Step Backward', 'Remove the entered column with the largest Prob > F.'],
          ['Enter All', 'Enter every column.'],
          ['Remove All', 'Remove every column.'],
          ['Apply This Model', 'Fit the discriminant below with the entered columns only (with none entered, with all of them).'],
          ['A line of the table', 'Click it to enter or remove that column.']] }],
        more: { label: 'Discriminant', id: 'help-p-discriminant' },
      },
    },
    launch: {
      lead: 'Choose the continuous covariates and the column of categories to predict.',
      roles: [
        { key: 'y', label: 'Y, Covariates', min: 1, numeric: true, types: ['continuous'], hint: 'required: continuous',
          help: 'The columns the groups are predicted from, assumed multivariate normal within each group. Rows with a missing value in any of them are left out.' },
        { key: 'x', label: 'X, Categories', min: 1, max: 1, types: ['nominal', 'ordinal'], hint: 'required: nominal or ordinal',
          help: 'The column of the groups to predict: each row is classified into the level with the largest posterior probability.' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'Weights the means, the covariances and the posterior probabilities; the multivariate tests count rows, not the sum of the weights, in their degrees of freedom.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'A count per row: the row stands for that many observations in the means and covariances.' },
        { ...SM.predict.roles({ weight: false, freq: false, by: false })[0], hint: 'optional: 0/1/2 or Training/Validation/Test',
          help: 'JMP Pro\'s Validation role: the rows with 0 or Training fit the discriminant (the means, covariances, canonical analysis and tests); the rows with 1 or Validation, and 2 or Test, are only scored by it, and the Score Summaries, confusion counts and curves are given for each set. Rows with no value are left out; a column of more values (k folds) is refused.' },
        { key: 'by', label: 'By', hint: 'optional', help: BY_HELP },
      ],
      options: [
        { key: 'method', label: 'Discriminant Method', type: 'select', value: 'linear', choices: [['linear', 'Linear, Common Covariance'], ['quadratic', 'Quadratic, Different Covariances'], ['regularized', 'Regularized, Compromise Method']],
          help: 'Linear, the default: one covariance matrix pooled over the groups, and straight boundaries between them. Quadratic: each group its own covariance, curved boundaries; it needs more rows per group. Regularized: a compromise of the two, with λ = 0.5 and γ = 0 until set in the red triangle.' },
        { key: 'stepwise', label: 'Stepwise Variable Selection', type: 'check', value: false,
          help: 'Start the report with the Column Selection panel, where the covariates are entered or removed one step at a time by their F tests; Apply This Model then fits the discriminant with the entered ones.' },
      ],
    },
    title: () => 'Discriminant Analysis',
    triangle(ctx) {
      const o = (k, d) => ctx.opt(k, d);
      const withRes = (fn) => async () => { const res = await discCall(ctx, discColumns(ctx)); if (res.error) { SM.ui.toast(res.error, { error: true }); return; } fn(res, res.levels.map((v) => SM.grid.cellText(ctx.role('x'), v))); };
      return [
        ctx.check('Stepwise Variable Selection', 'stepwise', null, false),
        { label: 'Discriminant Method', submenu: () => [
          { label: 'Linear, Common Covariance', checked: o('method', 'linear') === 'linear', action: () => ctx.set('method', 'linear') },
          { label: 'Quadratic, Different Covariances', checked: o('method', 'linear') === 'quadratic', action: () => ctx.set('method', 'quadratic') },
          { label: 'Regularized, Compromise Method…', checked: o('method', 'linear') === 'regularized', action: async () => { const v = await SM.ui.form({ title: 'Regularization Parameters', fields: [{ key: 'lam', label: 'λ, shrinkage to the common covariance (0 to 1)', type: 'number', value: o('lam', 0.5), help: 'Each group\'s covariance becomes λ·(the pooled covariance) + (1 − λ)·(its own): 1 is the linear method, 0 the quadratic. 0.5 by default.' },
            { key: 'gam', label: 'γ, shrinkage to the diagonal (0 to 1)', type: 'number', value: o('gam', 0), help: 'Then (1 − γ) of that plus γ of its diagonal, which shrinks the covariances toward zero and steadies the fit with many covariates or few rows. 0 by default.' }], validate: (x) => (x.lam >= 0 && x.lam <= 1 && x.gam >= 0 && x.gam <= 1 ? null : 'λ and γ are between 0 and 1') }); if (v) { ctx.set('lam', v.lam, null, { rerun: false }); ctx.set('gam', v.gam, null, { rerun: false }); ctx.set('method', 'regularized'); } } },
        ] },
        ctx.check('Discriminant Scores', 'scores', null, true),
        { label: 'Score Options', submenu: () => [
          ctx.check('Show Interesting Rows Only', 'interesting', null, false), ctx.check('Show Classification Counts', 'counts', null, true),
          ctx.check('Show Distances to Each Group', 'dist', null, false), ctx.check('Show Probabilities to Each Group', 'probs', null, false),
          ctx.check('ROC Curve', 'roc', null, false), ctx.check('Lift Curve', 'lift', null, false),
          ctx.report._discLevels === 2 ? SM.predict.thresholdItem(ctx, null) : null,
          { label: 'Select Misclassified Rows', action: withRes((res) => ctx.table.select(res.rows.filter((_, k) => res.misclassified[k]))) },
          { label: 'Select Uncertain Rows…', action: async () => { const v = await SM.ui.form({ title: 'Select Uncertain Rows', lead: 'Rows whose probability for some group is inside the range.', fields: [{ key: 'lo', label: 'From', type: 'number', value: 0.1, help: 'The lower end of the range: a row is selected when its posterior probability of some group lies strictly between From and To, a row the model is unsure of. 0.1 by default.' },
            { key: 'hi', label: 'To', type: 'number', value: 0.9, help: 'The upper end of the range; 0.9 by default.' }] }); if (!v) return; await withRes((res) => ctx.table.select(res.rows.filter((_, k) => res.prob[k].some((p) => p > v.lo && p < v.hi))))(); } },
          { label: 'Save Formulas', action: () => discSave(ctx) },
        ].filter(Boolean) },
        ctx.check('Canonical Plot', 'canplot', null, true),
        { label: 'Canonical Options', submenu: () => [
          ctx.check('Show Points', 'cpPoints', null, true), ctx.check('Show Means CL Ellipses', 'cpCL', null, true), ctx.check('Show Normal 50% Contours', 'cp50', null, false), ctx.check('Show Biplot Rays', 'cpRays', null, true),
          { label: 'Color Points', action: withRes((res) => { res.levels.forEach((_, t) => ctx.table.setColor(res.rows.filter((__, k) => res.actual[k] === t), t % 12)); }) },
          ctx.check('Show Canonical Details', 'candetails', null, false), ctx.check('Show Canonical Structure', 'canstruct', null, false),
          { label: 'Save Canonical Scores', action: () => discSave(ctx, 'canonical') },
        ] },
        { label: 'Specify Priors', submenu: () => [
          { label: 'Equal Probabilities', checked: o('priors', 'equal') === 'equal', action: () => ctx.set('priors', 'equal') },
          { label: 'Proportional to Occurrence', checked: o('priors', 'equal') === 'proportional', action: () => ctx.set('priors', 'proportional') },
          { label: 'Other…', checked: o('priors', 'equal') === 'other', action: async () => {
            const xcol = ctx.role('x');
            const lv = ctx.table.levels(xcol);
            const cur = o('priorValues', {}) || {};
            const v = await SM.ui.form({ title: 'Specify Priors', lead: 'The prior probability of each group; they are scaled to sum to one.', fields: lv.slice(0, 40).map((l, i) => ({ key: `p${i}`, label: SM.grid.cellText(xcol, l), type: 'number', value: cur[String(l)] ?? +(1 / lv.length).toFixed(4),
              helpLabel: 'Each group', help: 'The prior probability of the group. The priors are scaled to sum to one, so only their proportions count; a larger prior moves the classification toward the group. An empty field counts as 0.' })) });
            if (!v) return;
            const pv = {};
            lv.slice(0, 40).forEach((l, i) => { pv[String(l)] = v[`p${i}`] ?? 0; });
            ctx.set('priorValues', pv, null, { rerun: false });
            ctx.set('priors', 'other');
          } },
        ] },
        ctx.check('Show Within Covariances', 'withincov', null, false), ctx.check('Show Group Means', 'groupmeans', null, false),
      ];
    },
    render: discRender,
  });

  /* ======================================================================
     HIERARCHICAL CLUSTER
     ====================================================================== */
  const HMETHODS = [['average', 'Average'], ['centroid', 'Centroid'], ['ward', 'Ward'], ['single', 'Single'], ['complete', 'Complete']];
  const STDBY = [['columns', 'Columns'], ['none', 'Unstandardized'], ['rows', 'Rows']];
  // the Distance option (beyond JMP) of Single, Complete and Average linkage
  const HDISTANCES = [['sqeuclidean', 'Squared Euclidean (JMP)'], ['euclidean', 'Euclidean'], ['cityblock', 'City Block'], ['chebyshev', 'Chebyshev'], ['correlation', 'Correlation (1 − r)'],
    ['mahalanobis', 'Mahalanobis'], ['jaccard', 'Jaccard'], ['gower', 'Gower']];
  const DIST_WORDS = { sqeuclidean: 'squared Euclidean', euclidean: 'Euclidean', cityblock: 'city block', chebyshev: 'Chebyshev', correlation: 'correlation (1 − r)', mahalanobis: 'Mahalanobis', jaccard: 'Jaccard', gower: 'Gower' };
  const DIST_HELP = 'Beyond JMP, whose distances are the squared Euclidean ones: the dissimilarity Single, Complete and Average linkage join by. Euclidean, City Block (the sum of the absolute differences), Chebyshev (the largest one), Correlation (1 − the correlation of two rows across the columns, for shapes of profiles) and Mahalanobis (with the rows\' covariance, so correlated columns count once) take the columns as Standardize By leaves them; Jaccard takes each value as present (not 0) or absent, for 0/1 data; Gower averages |difference|/range over the numeric columns and 0 or 1 (the same level or not) over nominal ones, so it also takes nominal columns. Ward and Centroid need the squared Euclidean distances.';

  /* The union of the first joins: for each node (0..n-1 observations,
     n+s the s-th join) its root after n - k joins. */
  function clustersAt(merges, n, k, order) {
    const root = new Int32Array(2 * n - 1);
    for (let i = 0; i < root.length; i++) root[i] = i;
    const find = (i) => { while (root[i] !== i) { root[i] = root[root[i]]; i = root[i]; } return i; };
    for (let s = 0; s < n - k; s++) { const [a, b] = merges[s]; root[find(a)] = n + s; root[find(b)] = n + s; }
    const lab = new Int32Array(n);
    const map = new Map();
    for (const leaf of order) { const r = find(leaf); if (!map.has(r)) map.set(r, map.size); lab[leaf] = map.get(r); }
    return { lab, nodeCluster: (node) => map.get(find(node)) };
  }

  function leavesUnder(merges, n, node) {
    const out = [], stack = [node];
    while (stack.length) { const v = stack.pop(); if (v < n) out.push(v); else { const [a, b] = merges[v - n]; stack.push(a, b); } }
    return out;
  }

  /* The default number of clusters: where the joining distance jumps most
     (the largest ratio of one join to the one before), from 2 to 10. */
  function defaultClusters(heights, n) {
    let best = Math.min(3, n), ratio = -Infinity;
    for (let k = 2; k <= Math.min(10, n - 1); k++) {
      const up = heights[n - k], down = heights[n - k - 1];
      const r = down > 0 ? up / down : (up > 0 ? Infinity : 0);
      if (r > ratio) { ratio = r; best = k; }
    }
    return best;
  }

  function leafNames(ctx, rows) {
    const lc = ctx.role('label') || (ctx.table ? ctx.table.labelColumn() : null);
    return rows.map((r) => (lc && lc.values[r] != null && lc.values[r] !== '' && !(typeof lc.values[r] === 'number' && Number.isNaN(lc.values[r])) ? SM.grid.cellText(lc, lc.values[r]) : String(r + 1)));
  }

  // the clustering's settings for the backend (hcluster.fit, hcluster.save)
  function hcPayload(ctx) {
    const o = (k, d) => ctx.opt(k, d);
    return { columns: ctx.names('y'), method: o('method', 'ward'), standardize: o('standardize', 'columns'), robust: !!o('robust', false), impute: !!o('impute', false),
      matrix: o('format', 'attributes') === 'matrix', distance: o('distance', 'sqeuclidean'), n_clusters: o('ncluster', null) };
  }

  async function hcRender(ctx) {
    const cols = ctx.roles('y');
    const names = cols.map((c) => c.name);
    const o = (k, d) => ctx.opt(k, d);
    const method = o('method', 'ward'), standardize = o('standardize', 'columns');
    const base = hcPayload(ctx);
    const res = await mcall(ctx, 'hcluster.fit', { ...base, two_way: o('twoWay', false), label: labelName(ctx), silhouette: !!o('silhouette', false) });
    const box = ctx.container;
    if (res.error) { box.append(ctx.warn(res.error)); return; }
    if (!ctx.headless) ctx.report.hcCoords = !!res.coords;   // Save Formula for Closest Cluster needs the rows' values
    const n = res.n;
    const { merges, heights, order } = res;
    const k = Math.max(1, Math.min(n, Math.round(o('ncluster', null) ?? defaultClusters(heights, n))));
    if (!ctx.headless) ctx.report.hcShownClusters = k;      // what Number of Clusters… starts from
    const { lab, nodeCluster } = clustersAt(merges, n, k, order);
    const members = Array.from({ length: k }, () => []);
    for (let i = 0; i < n; i++) members[lab[i]].push(res.rows[i]);
    // Color Clusters and Mark Clusters follow the clusters when they change,
    // as in JMP; a redraw with the same clusters leaves the row states alone.
    const stamp = `${k}|${method}|${standardize}|${names.join('\u0001')}|${JSON.stringify(base)}`;
    const done = ctx.report._mvStamps || (ctx.report._mvStamps = {});
    for (const [opt, fn] of [['colorClusters', (rs, c) => ctx.table.setColor(rs, c % 12)], ['markClusters', (rs, c) => ctx.table.setMarker(rs, c % 12)]]) {
      const key = `${opt}\u0001${ctx.path}`;
      if (!o(opt, false)) { delete done[key]; continue; }
      if (done[key] !== stamp) { members.forEach(fn); done[key] = stamp; }
    }
    const names0 = leafNames(ctx, res.rows);
    const how = res.matrix ? 'the distances of the matrix in the columns'
      : res.distance === 'gower' ? 'Gower\'s distance (numeric columns over their ranges, levels the same or not)'
        : res.distance === 'jaccard' ? 'the Jaccard distance (each value present, not 0, or absent)'
          : `${{ columns: `columns standardized${o('robust', false) ? ' robustly (Huber)' : ''}`, none: 'unstandardized', rows: 'rows standardized' }[standardize]}${res.distance === 'sqeuclidean' ? '' : `, ${DIST_WORDS[res.distance]} distances`}`;
    box.append(ctx.note(`Method = ${HMETHODS.find((m) => m[0] === method)[1]}; ${how}; ${plural(n, 'row')}${!o('impute', false) && !res.matrix && n < ctx.rows.length ? ` (${dropped(ctx.rows.length - n)})` : ''}. ${k} cluster${k > 1 ? 's' : ''}.`));
    for (const t of res.notes || []) box.append(ctx.note(t));
    if (o('dendro', true)) dendrogramOutline(ctx, res, k, lab, nodeCluster, names0, members);
    if (o('history', true)) {
      const rep = new Int32Array(2 * n - 1);
      for (let i = 0; i < n; i++) rep[i] = i;
      const hist = [];
      for (let s = 0; s < n - 1; s++) {
        const [a, b] = merges[s];
        const [lead, join] = rep[a] <= rep[b] ? [rep[a], rep[b]] : [rep[b], rep[a]];
        rep[n + s] = lead;
        hist.push({ k: n - 1 - s, d: heights[s], leader: names0[lead], joiner: names0[join] });
      }
      hist.reverse();
      ctx.outline('Clustering History', { key: 'history', closed: n > 60 }).add(ctx.rt({ columns: [{ key: 'k', label: 'Number of Clusters', fmt: 'int' }, { key: 'd', label: 'Distance', digits: 6 }, { key: 'leader', label: 'Leader', fmt: 'text' }, { key: 'joiner', label: 'Joiner', fmt: 'text' }], rows: hist }, { maxRows: 400 }),
        ctx.note('The joins from the last (one cluster) back to the first. The leader and the joiner are the first row of each of the two clusters joined.'));
    }
    if (o('criterion', false) && !res.coords) ctx.outline('Cluster Criterion', { key: 'criterion', info: 'mv:ccc' }).add(ctx.note(`The cubic clustering criterion needs the rows' values in numeric columns: ${res.matrix ? 'a distance matrix has none' : 'a nominal column has no mean'}.`));
    else if (o('criterion', false)) {
      const crit = res.criterion.filter((c) => c.k >= 1);
      const ob = ctx.outline('Cluster Criterion', { key: 'criterion', info: 'mv:ccc' });
      ob.add(ctx.rt({ columns: [{ key: 'k', label: 'Number of Clusters', fmt: 'int' }, { key: 'ccc', label: 'CCC', digits: 4 }, { key: 'r2', label: 'RSquare', digits: 4 }, { key: 'er2', label: 'Approx Expected RSquare', digits: 4 }], rows: crit }, { maxRows: 200 }),
        ctx.plot([{ type: 'scatter', mode: 'lines+markers', x: crit.map((c) => c.k), y: crit.map((c) => c.ccc), line: { color: SM.report.BASE }, hovertemplate: '%{x} clusters: CCC %{y:.3f}<extra></extra>' }], { xaxis: { title: { text: 'Number of Clusters' } }, yaxis: { title: { text: 'CCC' } } }, { width: fitW(420), height: 240, title: 'Cubic clustering criterion', select: false }),
        ctx.code(res.ccc_code));
    }
    // the numeric columns' values of the rows clustered (imputed ones with Missing value imputation)
    const numCols = res.matrix ? [] : cols.filter((c) => (res.numeric || []).includes(c.name));
    const vals = hcValues(ctx, res, numCols);
    if (o('summary', false)) {
      if (numCols.length) clusterSummary(ctx, numCols, members, 'Cluster Summary', vals);
      else ctx.outline('Cluster Summary', { key: 'summary:Cluster Summary' }).add(ctx.note('No numeric columns to summarize: a distance matrix has none.'));
    }
    if (o('pcp', false)) {
      const ob = ctx.outline('Parallel Coordinate Plots', { key: 'pcp', info: 'hc:pcp' });
      if (!numCols.length) ob.add(ctx.note('A parallel coordinate plot needs numeric columns: a distance matrix has none.'));
      else {
        const labels = res.rows.map((_, i) => lab[i]);
        const means = members.map((rs) => numCols.map((c) => { const v = rs.map((r) => vals(c, r)).filter(Number.isFinite); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; }));
        ob.add(parallelPlot(ctx, { rows: res.rows, labels, k, cols: numCols, means, mu: res.mean, sd: res.sd, value: vals }), ctx.code(res.parallel_code),
          ctx.note(`Each row a thin line and each cluster's mean a thick one, over the ${numCols.length} numeric column${numCols.length > 1 ? 's' : ''}, each standardized by its mean and standard deviation over the rows clustered (0 is the mean).`));
      }
    }
    if (o('silhouette', false)) silhouetteOutline(ctx, res, k, lab, members);
    if (o('twoWay', false) && !res.coords) ctx.outline('Two Way Clustering', { key: 'twoway' }).add(ctx.note(`Two way clustering needs the rows' values in numeric columns: ${res.matrix ? 'a distance matrix has none' : 'a nominal column has none'}.`));
    if (o('twoWay', false) && res.col_order && res.data) {
      const ob = ctx.outline('Two Way Clustering', { key: 'twoway' });
      const colo = res.col_order;
      const z = order.map((i) => colo.map((j) => res.data[i][j]));
      const tall = n <= 150;
      const plain = standardize === 'none' || res.distance === 'gower' || res.distance === 'jaccard';
      ob.add(ctx.plot([{ type: 'heatmap', z, x: colo.map((j) => names[j]), y: order.map((i) => i), colorscale: plain ? 'Viridis' : divergingScale(), zmid: plain ? undefined : 0, hovertemplate: '%{x}: %{z:.3f}<extra></extra>', colorbar: { thickness: 10 } }],
        { yaxis: { autorange: 'reversed', tickvals: tall ? order.map((i) => i) : [], ticktext: tall ? order.map((i) => names0[i]) : [], type: 'category', showgrid: false }, xaxis: { type: 'category', showgrid: false, tickangle: -35 }, margin: { l: 70, r: 10, t: 8, b: 70 } },
        { width: fitW(Math.min(760, 120 + 40 * names.length)), height: tall ? Math.max(260, 13 * n + 90) : 600, title: 'Two way clustering', select: false }), ctx.code(res.twoway_code),
      ctx.note(`Rows in the order of the dendrogram, columns in the order of their own clustering (${method === 'centroid' ? 'Ward' : HMETHODS.find((m) => m[0] === method)[1]} on the columns); the colours are the ${res.distance === 'gower' ? 'values over their columns\' ranges' : res.distance === 'jaccard' ? 'values present (1) or not (0)' : standardize === 'none' ? 'values' : 'standardized values'}.`));
    }
    box.append(ctx.code(res.code));
  }

  function dendrogramOutline(ctx, res, k, lab, nodeCluster, names0, members) {
    const o = (kk, d) => ctx.opt(kk, d);
    const n = res.n;
    const { merges, heights, order } = res;
    const pos = new Float64Array(2 * n - 1), hh = new Float64Array(2 * n - 1);
    order.forEach((leaf, q) => { pos[leaf] = q; });
    for (let s = 0; s < n - 1; s++) { const [a, b] = merges[s]; pos[n + s] = (pos[a] + pos[b]) / 2; hh[n + s] = heights[s]; }
    const colored = o('colorClusters', false);
    const tc = SM.util.themeColors();
    const groups = new Map();
    const push = (key, color, s) => {
      if (!groups.has(key)) groups.set(key, { color, x: [], y: [], c: [] });
      const g = groups.get(key);
      const [a, b] = merges[s];
      g.x.push(hh[a], heights[s], heights[s], hh[b], null);
      g.y.push(pos[a], pos[a], pos[b], pos[b], null);
      g.c.push(s, s, s, s, null);
    };
    for (let s = 0; s < n - 1; s++) {
      if (s < n - k) { const c = nodeCluster(n + s); push(colored ? `c${c}` : 'in', colored ? pal(c) : tc.text, s); }
      else push('above', tc.muted, s);
    }
    const traces = [...groups.values()].map((g) => ({ type: 'scatter', mode: 'lines', x: g.x, y: g.y, customdata: g.c, line: { color: g.color, width: 1.3 }, hovertemplate: 'join at %{x:.4g}<extra>click: select</extra>' }));
    const leafRows = order.map((leaf) => res.rows[leaf]);
    traces.push({ type: 'scatter', mode: 'markers', x: order.map(() => 0), y: order.map((leaf) => pos[leaf]), rows: leafRows, marker: { size: n > 400 ? 3 : 5, color: colored ? order.map((leaf) => pal(lab[leaf])) : SM.report.BASE }, hovertext: order.map((leaf) => names0[leaf]), hovertemplate: '%{hovertext}<extra></extra>' });
    const cut = k >= n ? 0 : k <= 1 ? heights[n - 2] * 1.04 : (heights[n - k - 1] + heights[n - k]) / 2;
    const showLabels = n <= 150;
    const H = showLabels ? Math.max(240, 13 * n + 60) : 620;
    const dendro = ctx.plot(traces, {
      xaxis: { title: { text: 'Distance' }, rangemode: 'tozero', zeroline: false },
      yaxis: { range: [n - 0.5, -0.5], autorange: false, showgrid: false, zeroline: false, tickvals: showLabels ? order.map((leaf) => pos[leaf]) : [], ticktext: showLabels ? order.map((leaf) => names0[leaf]) : [], tickfont: { size: 9.5 }, ticks: '' },
      shapes: [{ type: 'line', x0: cut, x1: cut, yref: 'paper', y0: 0, y1: 1, line: { color: RED, width: 1.2, dash: 'dash' } }],
      annotations: [{ x: cut, yref: 'paper', y: 1, text: `${k} cluster${k > 1 ? 's' : ''}`, showarrow: false, xanchor: 'left', yanchor: 'bottom', font: { size: 10, color: RED } }],
      margin: { l: showLabels ? 90 : 20, r: 16, t: 18, b: 40 },
    }, {
      width: fitW(600), height: H, title: 'Dendrogram',
      onDraw: (gd) => gd.on('plotly_click', (ev) => {
        const pt = ev && ev.points && ev.points[0];
        if (!pt || !Number.isInteger(pt.customdata)) return;
        const rows = leavesUnder(merges, n, n + pt.customdata).map((leaf) => res.rows[leaf]);
        ctx.table.select(rows, ev.event && ev.event.shiftKey ? 'add' : 'replace');
      }),
    });
    const kmax = Math.min(n, 60);
    const val = el('span', { class: 'mv-value', text: String(k) });
    const slider = el('input', { type: 'range', min: '1', max: String(kmax), step: '1', value: String(Math.min(k, kmax)), 'aria-label': 'Number of clusters' });
    slider.addEventListener('input', () => { val.textContent = slider.value; });
    slider.addEventListener('change', () => ctx.set('ncluster', +slider.value));
    const ob = ctx.outline('Dendrogram', { key: 'dendro', info: 'hc:dendro' });
    // the dendrogram's code with Color Clusters written in (the backend writes the number of clusters)
    const dendroCode = withChoice(res.dendro_code, HC_COLOR, colored ? 'color_clusters = True   # Color Clusters' : HC_COLOR);
    ob.add(controls(control('Number of clusters', slider), val, button('−', () => ctx.set('ncluster', Math.max(1, k - 1))), button('+', () => ctx.set('ncluster', Math.min(n, k + 1)))), dendro, ctx.code(dendroCode));
    ob.add(el('div', { class: 'mv-legend' }, ...members.map((rs, c) => {
      const b = el('button', { type: 'button', title: `Select the rows of cluster ${c + 1}` }, el('span', { class: 'mv-swatch', style: { background: colored ? pal(c) : tc.muted } }), `${c + 1}: ${rs.length}`);
      b.addEventListener('click', (ev) => ctx.table.select(rs, ev.shiftKey ? 'add' : 'replace'));
      return b;
    })));
    if (o('distGraph', true)) {
      const m = Math.min(n - 1, Math.max(30, Math.min(n - 1, 60)));
      const ks = [], ds = [];
      for (let s = n - 2; s >= n - 1 - m && s >= 0; s--) { ks.push(n - 1 - s); ds.push(heights[s]); }
      ob.add(ctx.plot([{ type: 'scatter', mode: 'lines+markers', x: ks, y: ds, line: { color: SM.report.BASE, width: 1.3 }, marker: { size: 5 }, hovertemplate: '%{x} clusters: joined at %{y:.4g}<extra>click: choose</extra>' }],
        { xaxis: { title: { text: 'Number of Clusters' }, autorange: 'reversed' }, yaxis: { title: { text: 'Distance' }, rangemode: 'tozero' }, shapes: [{ type: 'line', x0: k, x1: k, yref: 'paper', y0: 0, y1: 1, line: { color: RED, width: 1, dash: 'dash' } }] },
        { width: fitW(600), height: 200, title: 'Distance Graph', select: false, onDraw: (gd) => gd.on('plotly_click', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt && Number.isFinite(pt.x)) ctx.set('ncluster', pt.x); }) }),
        ctx.code(res.distgraph_code));
    }
    ob.add(ctx.note('Drag the slider, click a point of the distance graph or use Number of Clusters… to choose the clusters; click a join to select its rows, or a cluster in the legend.'));
  }

  /* Means and standard deviations of each cluster, in the columns' units.
     value(c, r): a row's value (the imputed one with Missing value imputation). */
  function clusterSummary(ctx, cols, members, title, value = null) {
    const ob = ctx.outline(title, { key: `summary:${title}` });
    const means = [], sds = [];
    members.forEach((rs) => {
      const m = [], s = [];
      cols.forEach((c) => { const v = value ? rs.map((r) => value(c, r)).filter(Number.isFinite) : colValues(c, rs).v; const mu = v.reduce((a, b) => a + b, 0) / v.length; m.push(v.length ? mu : null); s.push(v.length > 1 ? Math.sqrt(v.reduce((a, b) => a + (b - mu) ** 2, 0) / v.length) : null); });
      means.push(m); sds.push(s);
    });
    const colsT = (cap) => [{ key: 'c', label: 'Cluster', fmt: 'int' }, { key: 'n', label: 'Count', fmt: 'int' }, ...cols.map((c, j) => ({ key: `v${j}`, label: c.name }))];
    const rowsT = (M) => members.map((rs, c) => Object.assign({ c: c + 1, n: rs.length }, ...cols.map((_, j) => ({ [`v${j}`]: M[c][j] }))));
    ob.add(ctx.rt({ columns: colsT(), rows: rowsT(means), caption: 'Cluster Means' }, { sortable: false }), ctx.rt({ columns: colsT(), rows: rowsT(sds), caption: 'Cluster Standard Deviations' }, { sortable: false }), ctx.note('Standard deviations with the n divisor, as JMP\'s cluster summaries.'));
    return { means, sds };
  }

  /* A row's value of a numeric column as the clustering has it: the imputed
     one with Missing value imputation (res.values), else the table's. */
  function hcValues(ctx, res, numCols) {
    if (!res.values) return (c, r) => { const v = c.values[r]; return typeof v === 'number' ? v : NaN; };
    const at = new Map(res.rows.map((r, i) => [r, i]));
    const j = new Map((res.numeric || []).map((nm, q) => [nm, q]));
    return (c, r) => { const i = at.get(r); const q = j.get(c.name); return i == null || q == null ? NaN : res.values[i][q]; };
  }

  /* Silhouettes (beyond JMP): how well each row sits in its cluster, (b − a)/max(a, b)
     with a its mean dissimilarity to its own cluster and b to the nearest other one;
     the rows' bars by cluster, each cluster's mean, and the mean by the number of clusters. */
  function silhouetteOutline(ctx, res, k, lab, members) {
    const S = res.silhouette;
    const ob = ctx.outline('Silhouettes', { key: 'silhouette', info: 'hc:silhouette', menu: () => [{ label: 'Remove', action: () => ctx.set('silhouette', false) }] });
    if (!S) return;
    if (S.error) { ob.add(ctx.note(S.error)); return; }
    const n = res.n;
    const tc = SM.util.themeColors();
    const colored = ctx.opt('colorClusters', false);
    if (k >= 2) {
      const idx = res.rows.map((_, i) => i).sort((a, b) => lab[a] - lab[b] || S.values[b] - S.values[a]);
      const ys = idx.map((_, q) => q);
      const bars = ctx.plot([{ type: 'bar', orientation: 'h', x: idx.map((i) => S.values[i]), y: ys, rows: idx.map((i) => [res.rows[i]]), width: 1, marker: { color: idx.map((i) => pal(lab[i])) }, hovertext: rowLabels(ctx, idx.map((i) => res.rows[i])).map((t, q) => `${t}: cluster ${lab[idx[q]] + 1}`), hovertemplate: '%{hovertext}<br>silhouette %{x:.4f}<extra></extra>' }],
        { xaxis: { title: { text: 'Silhouette' }, range: [Math.min(-0.1, ...S.values) - 0.02, 1] }, yaxis: { autorange: 'reversed', showticklabels: false, showgrid: false, zeroline: false },
          shapes: [{ type: 'line', x0: S.mean, x1: S.mean, yref: 'paper', y0: 0, y1: 1, line: { color: RED, width: 1.2, dash: 'dash' } }], bargap: 0, margin: { l: 20, r: 12, t: 8, b: 40 } },
        { width: fitW(560), height: Math.max(240, Math.min(620, 3 * n + 80)), title: `Silhouettes, ${k} clusters`, rowColors: false });
      ob.add(ctx.row(withCode(bars, ctx.code(res.silhouette_code)),
        ctx.rt({ columns: [{ key: 'c', label: 'Cluster', fmt: 'int' }, { key: 'n', label: 'Count', fmt: 'int' }, { key: 'm', label: 'Mean Silhouette', digits: 4 }], rows: [...S.clusters.map((c) => ({ c: c.cluster, n: c.count, m: c.mean })), { c: null, n, m: S.mean }], caption: `${k} clusters` },
          { sortable: false, onRow: (r, ev) => { if (r.c) ctx.table.select(members[r.c - 1], ev.shiftKey ? 'add' : 'replace'); } })));
    } else ob.add(ctx.note('One cluster has no silhouettes: choose two or more.'));
    if (S.path.length) {
      const ks = S.path.map((q) => q.k), ms = S.path.map((q) => q.mean);
      ob.add(withCode(ctx.plot([{ type: 'scatter', mode: 'lines+markers', x: ks, y: ms, line: { color: SM.report.BASE, width: 1.6 }, marker: { size: 6 }, hovertemplate: '%{x} clusters: mean silhouette %{y:.4f}<extra>click: choose</extra>' }],
        { xaxis: { title: { text: 'Number of Clusters' }, dtick: ks.length > 15 ? 2 : 1 }, yaxis: { title: { text: 'Mean Silhouette' } }, shapes: [{ type: 'line', x0: k, x1: k, yref: 'paper', y0: 0, y1: 1, line: { color: RED, width: 1, dash: 'dash' } }] },
        { width: fitW(420), height: 240, title: 'Mean silhouette by number of clusters', select: false, onDraw: (gd) => gd.on('plotly_click', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt && Number.isFinite(pt.x)) ctx.set('ncluster', pt.x); }) }),
      ctx.code(res.silhouette_k_code)));
    }
    ob.add(ctx.note(`Silhouettes on ${S.on}: 1 when a row is much nearer its own cluster than any other, 0 on the border, negative when it is nearer another cluster; a row alone in its cluster has 0 (as scikit-learn). The mean silhouette by number of clusters peaks at ${S.best ?? '—'} (among 2 to ${S.path.length ? S.path[S.path.length - 1].k : 2}): a candidate for the number of clusters. Click a point to choose it, a line of the table to select a cluster's rows.${colored ? '' : ' The colours are the clusters\', as Color Clusters gives them.'}`));
  }

  async function hcSave(ctx, what) {
    const res = await mcall(ctx, 'hcluster.fit', { ...hcPayload(ctx), two_way: ctx.opt('twoWay', false), label: labelName(ctx), silhouette: !!ctx.opt('silhouette', false) });
    if (res.error) { SM.ui.toast(res.error, { error: true }); return; }
    if (what === 'formula') { await saveFrom(ctx, 'hcluster.save', { ...hcPayload(ctx), n_clusters: ctx.opt('ncluster', null) ?? ctx.report.hcShownClusters ?? null }); return; }
    const k = Math.max(1, Math.min(res.n, Math.round(ctx.opt('ncluster', null) ?? defaultClusters(res.heights, res.n))));
    if (what === 'order') { const q = new Array(res.n); res.order.forEach((leaf, i) => { q[leaf] = i + 1; }); ctx.saveColumn('Display Order', { rows: res.rows, values: q }); return; }
    const { lab } = clustersAt(res.merges, res.n, k, res.order);
    ctx.saveColumn('Cluster', { rows: res.rows, values: Array.from(lab, (c) => c + 1) }, { modelingType: 'nominal', notes: `hierarchical clustering, ${res.method}, ${k} clusters` });
  }

  SM.platforms.register({
    id: 'hcluster', label: 'Hierarchical Cluster', menu: 'Analyze/Clustering', order: 10, info: 'p:hcluster',
    about: 'Agglomerative clustering of the rows (Average, Centroid, Ward, Single, Complete linkage) with JMP\'s squared-Euclidean distances, or of a distance matrix: robust standardization (Huber) and missing-value imputation (EM), the dendrogram with a chosen number of clusters, the distance graph, the clustering history, the cubic clustering criterion, cluster summaries, parallel coordinate plots, two-way clustering, cluster colours, markers, saved clusters and a formula for the closest cluster. Beyond JMP: other distances for Single, Complete and Average (Euclidean, city block, Chebyshev, correlation, Mahalanobis, Jaccard, and Gower, which takes nominal columns too) and silhouettes.',
    uses: ['scipy.cluster.hierarchy.linkage, leaves_list', 'scipy.spatial.distance.pdist, squareform', "the cubic clustering criterion (Sarle 1983), numpy", 'statsmodels.robust.scale.Huber (Standardize Robustly)',
      "Explore Missing Values' EM for a multivariate normal (Missing value imputation)", "Gower's (1971) distance and Rousseeuw's (1987) silhouettes, numpy"],
    topics: {
      'p:hcluster': {
        kicker: 'Analyze > Clustering', title: 'Hierarchical Cluster',
        lead: 'Starts with each row as a cluster and joins the two closest clusters until one is left. The dendrogram shows the joins; choose the number of clusters where the joining distance jumps.',
        sections: [
          { heading: 'Methods (distances as JMP defines them)', choices: [['Average', 'The mean squared Euclidean distance between the rows of the two clusters.'], ['Centroid', 'The squared distance between the cluster means.'], ['Ward', 'The increase in the within-cluster sum of squares: |x̄_K − x̄_L|²/(1/N_K + 1/N_L).'], ['Single', 'The smallest squared distance between rows of the two.'], ['Complete', 'The largest.']] },
          { heading: 'Standardize By', text: 'Columns (the default) scales every column to mean 0 and standard deviation 1 first, so that no column dominates by its units; Standardize Robustly takes Huber\'s M-estimates of each column\'s mean and standard deviation instead (as JMP), so that outliers pull them less.' },
          { heading: 'Missing values', text: 'Rows with a missing value are left out, unless Missing value imputation is on: then each missing value is its conditional mean under a multivariate normal of the numeric columns fitted by EM (Explore Missing Values\' Multivariate Normal Imputation), and only rows with no value are left out.' },
          { heading: 'Data Format', choices: [['Attribute List', 'A row per object, its values in the columns (the usual).'], ['Distance Matrix', 'The columns hold the distances between the rows\' objects, a column for each row (JMP\'s Data is distance matrix); one side of the diagonal is enough. Single, Complete and Average join by the distances as they are; Ward and Centroid take them as Euclidean distances.']] },
          { heading: 'Distance (beyond JMP)', text: DIST_HELP },
          { heading: 'Silhouettes (beyond JMP)', text: 'How well each row sits in its cluster (Rousseeuw 1987), on the clustering\'s own dissimilarities (the Euclidean ones where it joins on squared Euclidean distances): the rows\' silhouettes, each cluster\'s mean, and the mean silhouette by the number of clusters, whose peak suggests a number of clusters.' },
          { heading: 'Saved columns', choices: [['Save Clusters', 'The cluster of each row clustered.'], ['Save Formula for Closest Cluster', 'A formula column (JMP\'s): the cluster whose centroid is nearest by the squared Euclidean distance, in the space the clustering sees (the columns standardized as it standardized them). Every row whose columns are present gets one, excluded rows and new rows too; a row of the tree need not get its own cluster, for the tree is not cut by the nearest centroid.'], ['Save Display Order', 'Each row\'s place in the dendrogram.']] },
          { heading: 'Differences from JMP', text: 'The Fast and Hybrid Ward methods, stacked and summarized data and the constellation plot are not here. JMP\'s multivariate normal imputation estimates the covariances pairwise; here they are the EM estimate, as Explore Missing Values has them. The default number of clusters is where the joining distance jumps most (2 to 10). With a distance matrix or a nominal column (Gower) the cubic clustering criterion, two-way clustering and the closest-cluster formula are not available: they need the rows\' values.' },
        ],
        more: { label: 'Hierarchical Cluster', id: 'help-p-hcluster' },
      },
      'hc:dendro': {
        kicker: 'Hierarchical Cluster', title: 'Dendrogram', lead: 'Read from left to right: each vertical line joins two clusters at the distance where they were joined. The dashed line cuts the tree into the chosen number of clusters; the distance graph below shows the distance of each join against the number of clusters left.',
        sections: [{ heading: 'In the report', choices: [
          ['Number of clusters', 'Drag the slider (1 to 60) to cut the tree into that many clusters; the report follows when you let go. The colours, the cluster summary and Save Clusters use this number.'],
          ['− and +', 'One cluster fewer, or one more.'],
          ['The cluster buttons', 'Under the dendrogram, one per cluster with its number of rows: a click selects its rows (with shift, adds them to the selection).'],
          ['A join', 'Click a line of the dendrogram to select the rows under that join.'],
          ['Distance Graph', 'Click a point to choose that number of clusters.']] }],
        more: { label: 'Hierarchical Cluster', id: 'help-p-hcluster' },
      },
      'hc:pcp': {
        kicker: 'Hierarchical Cluster', title: 'Parallel Coordinate Plots',
        lead: 'The clusters\' profiles: a line for each row across the numeric columns, in its cluster\'s colour, and a thick line for each cluster\'s mean; every column standardized by its mean and standard deviation over the rows clustered, so 0 is the mean and ±1 a standard deviation. Clusters that differ in a column are apart there. As K Means\' Parallel Coord Plots (JMP draws a plot per cluster; here they share one).',
        more: { label: 'Hierarchical Cluster', id: 'help-p-hcluster' },
      },
      'hc:silhouette': {
        kicker: 'Hierarchical Cluster', title: 'Silhouettes',
        lead: 'Beyond JMP. A row\'s silhouette is (b − a)/max(a, b), a its mean dissimilarity to the other rows of its cluster and b the smallest mean dissimilarity to the rows of another cluster (Rousseeuw 1987): near 1 it sits well inside its cluster, near 0 between two, negative nearer another cluster. A row alone in its cluster has 0 (as scikit-learn\'s silhouette_samples). Up to 2000 rows.',
        sections: [{ heading: 'In the report', choices: [
          ['The bars', 'Each row\'s silhouette, by cluster, each cluster\'s largest first; the dashed line is the mean. Click or drag over bars to select their rows.'],
          ['The table', 'Each cluster\'s count and mean silhouette, and all the rows\'; click a line to select that cluster\'s rows.'],
          ['Mean silhouette by number of clusters', 'The tree cut into 2 to 30 clusters; the peak is a candidate number of clusters. Click a point to choose it.']] }],
        more: { label: 'Hierarchical Cluster', id: 'help-p-hcluster' },
      },
      'mv:ccc': { kicker: 'Clustering', title: 'Cubic clustering criterion', lead: 'Sarle\'s (1983) CCC compares the R² of the clusters with the R² expected if the data were uniform in a box (hyper-rectangle) of the same shape (the eigenvalues of the covariance matrix). Large positive values suggest clusters; peaks mark candidate numbers of clusters. It assumes roughly spherical clusters. Computed as SAS PROC CLUSTER does (checked against its Fisher iris example).', more: { label: 'K Means Cluster', id: 'help-p-kmeans' } },
    },
    launch: {
      lead: 'Choose the columns to cluster the rows by (or those of a distance matrix). Label names the rows in the dendrogram.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 1, types: ['continuous', 'ordinal', 'nominal'], hint: 'required: numeric (nominal with the Gower distance)',
          help: 'The columns the distances between the rows are computed from, or with Data Format Distance Matrix the columns of the matrix, one per row. Numeric columns; nominal ones with the Gower distance. Rows with a missing value in any of them are left out, unless Missing value imputation is on; at most 4000 rows (for more, K Means Cluster).' },
        { key: 'label', label: 'Label', max: 1, hint: 'optional',
          help: 'A column whose values name the rows in the dendrogram, the clustering history and the hover text; without it the table\'s label column, else the row number.' },
        { key: 'by', label: 'By', hint: 'optional', help: BY_HELP },
      ],
      options: [
        { key: 'method', label: 'Method', type: 'select', value: 'ward', choices: HMETHODS,
          help: 'How far apart two clusters are, with JMP\'s squared Euclidean distances. Ward, the default, joins the pair that raises the within-cluster sum of squares least: compact clusters of similar size. Average: the mean distance between their rows. Centroid: between their means. Single: their closest rows (it makes long chains). Complete: their farthest rows.' },
        { key: 'standardize', label: 'Standardize By', type: 'select', value: 'columns', choices: STDBY,
          help: 'Columns, the default: each column scaled to mean 0 and standard deviation 1 first, so that no column dominates by its units. Unstandardized: the values as they are. Rows: each row centred and scaled across its own columns, to cluster by the shape of the profile rather than its level.' },
        { key: 'robust', label: 'Standardize Robustly', type: 'check', value: false,
          help: 'With Standardize By Columns: each column centred and scaled by Huber\'s M-estimates of its mean and standard deviation (statsmodels\' Huber) instead of the plain ones, so that outliers pull the standardization less, as JMP\'s option does.' },
        { key: 'impute', label: 'Missing value imputation', type: 'check', value: false,
          help: 'Keep the rows with missing values: each missing value becomes its conditional mean given the row\'s other values, under a multivariate normal of the numeric columns fitted by EM (Explore Missing Values\' Multivariate Normal Imputation). Off: rows with a missing value are left out. Needs two or more numeric columns.' },
        { key: 'format', label: 'Data Format', type: 'select', value: 'attributes', choices: [['attributes', 'Attribute List'], ['matrix', 'Distance Matrix']],
          help: 'Attribute List, the default: a row per object, its values in the columns. Distance Matrix (JMP\'s Data is distance matrix): the columns hold the distances between the rows\' objects, a column for each row in the table\'s order, one side of the diagonal enough; Standardize By and Distance are then not used.' },
        { key: 'distance', label: 'Distance (Single, Complete, Average)', type: 'select', value: 'sqeuclidean', choices: HDISTANCES, help: DIST_HELP },
        { key: 'twoWay', label: 'Two Way Clustering', type: 'check', value: false,
          help: 'Also cluster the columns, and show the values as a heat map with the rows in the order of the dendrogram and the columns in the order of their own clustering.' },
      ],
      validate: (spec) => {
        const o = spec.options || {};
        if (o.distance && o.distance !== 'sqeuclidean' && (o.method === 'ward' || o.method === 'centroid' || !o.method) && o.format !== 'matrix') return `${(o.method || 'ward') === 'ward' ? 'Ward' : 'Centroid'} joins on squared Euclidean distances: choose Single, Complete or Average for another distance`;
        return null;
      },
    },
    title: () => 'Hierarchical Clustering',
    triangle(ctx) {
      return [
        ctx.check('Color Clusters', 'colorClusters', null, false), ctx.check('Mark Clusters', 'markClusters', null, false),
        { label: 'Number of Clusters…', action: async () => { const v = await SM.ui.form({ title: 'Number of Clusters', fields: [{ key: 'k', label: 'Number of clusters', type: 'number', value: ctx.opt('ncluster', null) ?? ctx.report.hcShownClusters ?? 3,
          help: 'Where the tree is cut: the number of clusters the rows fall into, marked by the dashed line and used by the colours, the cluster summary and Save Clusters. Until set, it is where the joining distance jumps most (2 to 10).' }] }); if (v && v.k >= 1) ctx.set('ncluster', Math.round(v.k)); } },
        ctx.check('Cluster Criterion', 'criterion', null, false),
        ctx.check('Show Dendrogram', 'dendro', null, true), ctx.check('Distance Graph', 'distGraph', null, true), ctx.check('Clustering History', 'history', null, true), ctx.check('Cluster Summary', 'summary', null, false),
        ctx.check('Parallel Coord Plots', 'pcp', null, false), ctx.check('Silhouettes', 'silhouette', null, false),
        ctx.check('Two Way Clustering', 'twoWay', null, false),
        { label: 'Method', submenu: () => HMETHODS.map(([v, l]) => ({ label: l, checked: ctx.opt('method', 'ward') === v, action: () => {
          if ((v === 'ward' || v === 'centroid') && ctx.opt('distance', 'sqeuclidean') !== 'sqeuclidean') ctx.set('distance', 'sqeuclidean', null, { rerun: false });
          ctx.set('method', v);
        } })) },
        { label: 'Standardize By', submenu: () => [...STDBY.map(([v, l]) => ({ label: l, checked: ctx.opt('standardize', 'columns') === v, action: () => ctx.set('standardize', v) })), { separator: true }, ctx.check('Standardize Robustly', 'robust', null, false)] },
        { label: 'Distance', submenu: () => HDISTANCES.map(([v, l]) => ({ label: l, checked: ctx.opt('distance', 'sqeuclidean') === v, disabled: v !== 'sqeuclidean' && ['ward', 'centroid'].includes(ctx.opt('method', 'ward')) && ctx.opt('format', 'attributes') !== 'matrix', action: () => ctx.set('distance', v) })) },
        ctx.check('Missing value imputation', 'impute', null, false),
        { separator: true },
        { label: 'Save Clusters', action: () => hcSave(ctx, 'clusters') },
        { label: 'Save Formula for Closest Cluster', disabled: ctx.report.hcCoords === false, action: () => hcSave(ctx, 'formula') },
        { label: 'Save Display Order', action: () => hcSave(ctx, 'order') },
      ];
    },
    render: hcRender,
  });

  /* ======================================================================
     K MEANS CLUSTER
     ====================================================================== */
  // the fits' settings for the backend (kmeans.fit, kmeans.save)
  function kmPayload(ctx) {
    const o = (k, d) => ctx.opt(k, d);
    const kmin = Math.max(1, Math.round(o('k', 3)));
    const kmax = o('kRange', null);
    const single = !!o('single', false);
    return { columns: ctx.names('y'), weight: ctx.name('weight'), freq: ctx.name('freq'), k_min: kmin, k_max: kmax && kmax > kmin ? Math.round(kmax) : kmin, standardize: o('scaled', true), seed: o('seed', 20260926), restarts: o('restarts', 10),
      ...(single ? { single: true, steps: o('steps', {}) || {} } : {}) };
  }
  const kmCall = (ctx) => mcall(ctx, 'kmeans.fit', kmPayload(ctx));

  async function kmRender(ctx) {
    const cols = ctx.roles('y');
    const o = (k, d) => ctx.opt(k, d);
    const res = await kmCall(ctx);
    const box = ctx.container;
    kmControls(ctx);
    if (res.error) { box.append(ctx.warn(res.error)); return; }
    box.append(ctx.note(`${fmt(res.n)} observations${res.n_rows < ctx.rows.length ? `; ${dropped(ctx.rows.length - res.n_rows)}` : ''}; ${res.standardize ? 'each column scaled to standard deviation 1' : 'the columns in their own units'}. ${res.single ? `Single Step: one k-means++ start for each number of clusters, from the seed ${res.seed}; Step moves it on one iteration, Go to the end.` : `k-means++ starts from the seed ${res.seed}, the best of ${res.restarts} by the within sum of squares.`}`));
    if (res.fits.length > 1 || o('comparison', true)) {
      const ob = ctx.outline('Cluster Comparison', { key: 'comparison', info: 'mv:ccc', menu: () => [ctx.check('Criteria by Number of Clusters', 'critPlot', null, true)] });
      ob.add(ctx.rt({
        columns: [{ key: 'method', label: 'Method', fmt: 'text' }, { key: 'k', label: 'NCluster', fmt: 'int' }, { key: 'ccc', label: 'CCC', digits: 4 }, { key: 'best', label: 'Best', fmt: 'text' }, { key: 'pseudo_f', label: 'Pseudo F', digits: 5 }, { key: 'r2', label: 'RSquare', digits: 4 }, { key: 'er2', label: 'Approx Expected RSquare', digits: 4, hidden: true }, { key: 'wss', label: 'Within SS', digits: 6 }],
        rows: res.fits.map((f) => ({ method: 'K Means Clustering', k: f.k, ccc: f.ccc, best: f.k === res.best ? 'Optimal CCC' : '', pseudo_f: f.pseudo_f, r2: f.r2, er2: f.er2, wss: f.wss })),
      }, { onRow: (r) => ctx.set('open', r.k) }), ctx.note('CCC: Sarle\'s cubic clustering criterion, largest best; Pseudo F: Calinski and Harabasz\'s ratio of between to within mean squares; RSquare: the share of the variance between clusters. Click a line to open its report.'));
      const done = res.fits.filter((f) => f.labels);
      if (done.length >= 2 && o('critPlot', true)) ob.add(withCode(kmCriteriaPlot(ctx, res, done), ctx.code(res.comparison_code)),
        ctx.note('The four criteria against the number of clusters: the within sum of squares always falls as k grows, so look for the elbow where it stops falling fast (the book\'s hand-drawn plot); CCC and pseudo F peak at good numbers of clusters. The dashed line is the Optimal CCC; click a point to open its fit.'));
    }
    const openK = o('open', res.best ?? res.fits[0].k);
    for (const f of res.fits) kmFit(ctx, res, f, cols, f.k === openK || res.fits.length === 1);
    box.append(ctx.code(res.code));
  }

  /* Cluster Comparison's graph: CCC, pseudo F, RSquare and the within sum of
     squares by the number of clusters, four panels on one axis of k. */
  function kmCriteriaPlot(ctx, res, fits) {
    const ks = fits.map((f) => f.k);
    const keys = [['ccc', 'CCC'], ['pseudo_f', 'Pseudo F'], ['r2', 'RSquare'], ['wss', 'Within SS']];
    const traces = [], layout = { showlegend: false, margin: { l: 56, r: 12, t: 26, b: 42 }, annotations: [], shapes: [] };
    const tc = SM.util.themeColors();
    keys.forEach(([key, label], q) => {
      const a = q + 1, row = Math.floor(q / 2), col = q % 2;
      const xa = a === 1 ? 'x' : `x${a}`, ya = a === 1 ? 'y' : `y${a}`;
      layout[`xaxis${a === 1 ? '' : a}`] = { domain: [col * 0.54, col * 0.54 + 0.46], anchor: ya, dtick: ks.length > 12 ? 2 : 1, title: row === 1 ? { text: 'NCluster', standoff: 4 } : undefined, showticklabels: row === 1, zeroline: false };
      layout[`yaxis${a === 1 ? '' : a}`] = { domain: [row === 0 ? 0.56 : 0, row === 0 ? 1 : 0.44], anchor: xa, zeroline: false, tickfont: { size: 9 } };
      traces.push({ type: 'scatter', mode: 'lines+markers', x: ks, y: fits.map((f) => f[key]), xaxis: xa, yaxis: ya, customdata: ks, line: { color: SM.report.BASE, width: 1.6 }, marker: { size: 6 }, name: label, hovertemplate: `%{x} clusters: ${label} %{y:.5g}<extra>click: open</extra>` });
      layout.annotations.push({ xref: `${xa} domain`, yref: `${ya} domain`, x: 0.5, y: 1.02, yanchor: 'bottom', text: label, showarrow: false, font: { size: 11, color: tc.text } });
      if (res.best != null) layout.shapes.push({ type: 'line', xref: xa, yref: `${ya} domain`, x0: res.best, x1: res.best, y0: 0, y1: 1, line: { color: RED, width: 1, dash: 'dash' } });
    });
    return ctx.plot(traces, layout, { width: fitW(560), height: 420, title: 'Cluster criteria by number of clusters', select: false,
      onDraw: (gd) => gd.on('plotly_click', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt && Number.isFinite(pt.x)) ctx.set('open', pt.x); }) });
  }

  function kmControls(ctx) {
    const o = (k, d) => ctx.opt(k, d);
    const d = { k: o('k', 3), kRange: o('kRange', null), scaled: o('scaled', true), restarts: o('restarts', 10), seed: o('seed', 20260926) };
    const sc = el('input', { type: 'checkbox', 'aria-label': 'Columns scaled individually' });
    sc.checked = !!d.scaled;
    const ss = el('input', { type: 'checkbox', 'aria-label': 'Single Step' });
    ss.checked = !!o('single', false);
    const ob = ctx.outline('Iterative Clustering', { key: 'control', info: 'km:control' });
    ob.add(controls(
      control('Number of Clusters', numberEl(d.k, (v) => { d.k = v; }, { size: 3, aria: 'Number of clusters' })),
      control('Range of Clusters (Optional)', numberEl(d.kRange, (v) => { d.kRange = v; }, { size: 3, aria: 'Range of clusters' })),
      control('Columns Scaled Individually', sc),
      control('Restarts', numberEl(d.restarts, (v) => { d.restarts = v; }, { size: 3, aria: 'Restarts' })),
      control('Seed', numberEl(d.seed, (v) => { d.seed = v; }, { size: 9, aria: 'Seed' })),
      control('Single Step', ss),
      button('Go', () => {
        const k = Math.max(1, Math.round(d.k || 3));
        ctx.set('single', ss.checked, null, { rerun: false });
        ctx.set('steps', {}, null, { rerun: false });   // Single Step starts again from the starting centres
        ctx.set('scaled', sc.checked, null, { rerun: false });
        ctx.set('kRange', d.kRange && d.kRange > k ? Math.min(Math.round(d.kRange), k + 30) : null, null, { rerun: false });
        ctx.set('restarts', Math.max(1, Math.min(100, Math.round(d.restarts || 10))), null, { rerun: false });
        ctx.set('seed', Math.round(d.seed ?? 20260926), null, { rerun: false });
        ctx.set('open', null, null, { rerun: false });
        ctx.set('k', k);
      }, 'primary'),
    ));
  }

  /* Single Step's buttons in a fit's report: Step moves it on one iteration, Go to the end. */
  function kmStepControls(ctx, f) {
    const steps = { ...(ctx.opt('steps', {}) || {}) };
    const set = (v) => { ctx.set('steps', { ...steps, [f.k]: v }); };
    const step = button('Step', () => set((steps[f.k] ?? 0) + 1));
    step.disabled = f.converged === true || steps[f.k] === null;
    const go = button('Go', () => set(null), 'primary');
    go.disabled = f.converged === true;
    return controls(step, go, el('span', { class: 'sm-ob-note', text: f.labels ? `Step ${f.step}${f.converged ? ': the centres no longer move' : ''}` : 'Step 0: the starting centres; no rows assigned yet' }));
  }

  function kmFit(ctx, res, f, cols, open) {
    const sc = `k${f.k}`;
    const o = (k, d) => ctx.opt(k, d, sc);
    if (!f.labels) {   // Single Step, before the first step: the starting centres only (JMP: no cluster assignments)
      const ob = ctx.outline(`K Means NCluster=${f.k}`, { key: `km:${f.k}`, closed: !open, info: 'km:fit' });
      const colsT = [{ key: 'c', label: 'Cluster', fmt: 'int' }, ...cols.map((c, j) => ({ key: `v${j}`, label: c.name }))];
      ob.add(kmStepControls(ctx, f), ctx.rt({ columns: colsT, rows: f.seeds.map((m, c) => Object.assign({ c: c + 1 }, ...cols.map((_, j) => ({ [`v${j}`]: m[j] })))), caption: 'Starting Centres' }, { sortable: false }),
        ctx.note('k-means++ from the report\'s seed: the first centre a random row, each next one a row drawn with a probability in proportion to its squared distance from the centres chosen. Step assigns every row to its nearest centre and moves each centre to the mean of its rows; Go repeats that until the centres stop moving.'));
      return;
    }
    const members = Array.from({ length: f.k }, () => []);
    f.labels.forEach((c, i) => members[c].push(res.rows[i]));
    const ob = ctx.outline(`K Means NCluster=${f.k}`, { key: `km:${f.k}`, closed: !open, info: 'km:fit', menu: () => [
      ctx.check('Biplot', 'biplot', sc, true), ctx.check('Biplot Rays', 'rays', sc, true), ctx.check('Parallel Coord Plots', 'pcp', sc, false), ctx.check('Scatterplot Matrix', 'splom', sc, false),
      { separator: true },
      { label: 'Save Colors to Table', action: () => members.forEach((rs, c) => ctx.table.setColor(rs, c % 12)) },
      { label: 'Mark Clusters', action: () => members.forEach((rs, c) => ctx.table.setMarker(rs, c % 12)) },
      { label: 'Save Clusters', action: () => saveFrom(ctx, 'kmeans.save', { ...kmPayload(ctx), k: f.k, what: 'clusters' }) },
      { label: 'Save Cluster Distance', action: async () => { try { const r = await mcall(ctx, 'kmeans.save', { ...kmPayload(ctx), k: f.k, what: 'clusters' }); saveBatch(ctx, r.error ? r : { columns: r.columns.filter((c) => c.name === 'Distance') }); } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); } } },
      { label: 'Save Cluster Formula', action: () => saveFrom(ctx, 'kmeans.save', { ...kmPayload(ctx), k: f.k, what: 'formula' }) },
      { label: 'Save Distance Formulas', action: () => saveFrom(ctx, 'kmeans.save', { ...kmPayload(ctx), k: f.k, what: 'distances' }) },
    ] });
    if (res.single) ob.add(kmStepControls(ctx, f));
    ob.add(ctx.rt({ columns: [{ key: 'c', label: 'Cluster', fmt: 'int' }, { key: 'n', label: 'Count' }], rows: f.counts.map((n, c) => ({ c: c + 1, n })), caption: 'Cluster Summary' }, { sortable: false, onRow: (r, ev) => ctx.table.select(members[r.c - 1], ev.shiftKey ? 'add' : 'replace') }),
      ctx.kv([['Step', f.iterations, 'int'], ['Criterion', f.criterion]]));
    const colsT = [{ key: 'c', label: 'Cluster', fmt: 'int' }, ...cols.map((c, j) => ({ key: `v${j}`, label: c.name }))];
    const rowsT = (M) => M.map((m, c) => Object.assign({ c: c + 1 }, ...cols.map((_, j) => ({ [`v${j}`]: m[j] }))));
    ob.add(ctx.rt({ columns: colsT, rows: rowsT(f.means), caption: 'Cluster Means' }, { sortable: false }), ctx.rt({ columns: colsT, rows: rowsT(f.sds), caption: 'Cluster Standard Deviations' }, { sortable: false }));
    ob.add(el('div', { class: 'mv-legend' }, ...members.map((rs, c) => {
      const b = el('button', { type: 'button', title: `Select the rows of cluster ${c + 1}` }, el('span', { class: 'mv-swatch', style: { background: pal(c) } }), `Cluster ${c + 1}: ${rs.length}`);
      b.addEventListener('click', (ev) => ctx.table.select(rs, ev.shiftKey ? 'add' : 'replace'));
      return b;
    })));
    if (o('biplot', true)) ob.add(kmBiplot(ctx, res, f, cols, o('rays', true)), ctx.code(o('rays', true) ? f.biplot_code : withChoice(f.biplot_code, KM_RAYS, 'show_rays = False   # Biplot Rays')));
    if (o('pcp', false)) ob.add(kmParallel(ctx, res, f, cols), ctx.code(f.parallel_code));
    if (o('splom', false)) ob.add(kmSplom(ctx, res, f, cols));
  }

  function kmBiplot(ctx, res, f, cols, rays) {
    const P = res.pca;
    if (!P.scores.length || P.scores[0].length < 2) return ctx.note('The biplot needs two or more columns.');
    const tc = SM.util.themeColors();
    const x = P.scores.map((s) => s[0]), y = P.scores.map((s) => s[1]);
    const traces = [{ type: 'scatter', mode: 'markers', x, y, rows: res.rows, marker: { size: 5, color: f.labels.map((c) => pal(c)) }, hovertext: res.rows.map((r, i) => `${rowLabels(ctx, [r])[0]}: cluster ${f.labels[i] + 1}`), hovertemplate: '%{hovertext}<extra></extra>', showlegend: false }];
    for (let c = 0; c < f.k; c++) {
      const idx = f.labels.map((l, i) => (l === c ? i : -1)).filter((i) => i >= 0);
      if (!idx.length) continue;
      const mx = idx.reduce((a, i) => a + x[i], 0) / idx.length, my = idx.reduce((a, i) => a + y[i], 0) / idx.length;
      if (idx.length > 2) {
        let sxx = 0, syy = 0, sxy = 0;
        for (const i of idx) { sxx += (x[i] - mx) ** 2; syy += (y[i] - my) ** 2; sxy += (x[i] - mx) * (y[i] - my); }
        const e = ellipseCov(mx, my, [[sxx / (idx.length - 1), sxy / (idx.length - 1)], [sxy / (idx.length - 1), syy / (idx.length - 1)]], 0.9);
        traces.push({ type: 'scatter', mode: 'lines', x: e.x, y: e.y, line: { color: pal(c), width: 1 }, fill: 'toself', fillcolor: `${pal(c)}22`, hoverinfo: 'skip', showlegend: false });
      }
      traces.push({ type: 'scatter', mode: 'markers+text', x: [mx], y: [my], text: [String(c + 1)], textposition: 'middle center', textfont: { size: 10, color: tc.text }, marker: { size: 10 + 22 * Math.sqrt(f.counts[c] / res.n), color: 'rgba(0,0,0,0)', line: { color: pal(c), width: 2 } }, name: `Cluster ${c + 1}`, hovertemplate: `cluster ${c + 1}: ${f.counts[c]} rows<extra></extra>`, showlegend: true });
    }
    if (rays) {
      let smax = 0;
      for (let i = 0; i < x.length; i++) smax = Math.max(smax, Math.abs(x[i]), Math.abs(y[i]));
      const V = P.vectors;
      let lmax = 0;
      cols.forEach((_, j) => { lmax = Math.max(lmax, Math.abs(V[j][0]), Math.abs(V[j][1])); });
      const s = lmax > 0 ? (0.8 * smax) / lmax : 1;
      const rx = [], ry = [];
      cols.forEach((_, j) => { rx.push(0, s * V[j][0], null); ry.push(0, s * V[j][1], null); });
      traces.push({ type: 'scatter', mode: 'lines', x: rx, y: ry, line: { color: tc.muted, width: 1 }, hoverinfo: 'skip', showlegend: false });
      traces.push({ type: 'scatter', mode: 'text', x: cols.map((_, j) => s * V[j][0]), y: cols.map((_, j) => s * V[j][1]), text: cols.map((c) => c.name), textfont: { size: 10, color: tc.text }, hoverinfo: 'skip', showlegend: false });
    }
    const tot = P.eigenvalues.reduce((a, b) => a + Math.max(b, 0), 0);
    return ctx.plot(traces, { showlegend: true, legend: { orientation: 'v', x: 1.02, y: 1 }, xaxis: { title: { text: `Prin1 (${(100 * P.eigenvalues[0] / tot).toFixed(1)}%)` }, zeroline: true }, yaxis: { title: { text: `Prin2 (${(100 * P.eigenvalues[1] / tot).toFixed(1)}%)` }, zeroline: true }, margin: { r: 110 } },
      { width: fitW(560), height: 420, title: `Biplot, ${f.k} clusters` });
  }

  /* Parallel coordinates of clusters (K Means' and Hierarchical Cluster's
     Parallel Coord Plots): each row a thin line in its cluster's colour and
     each cluster's mean a thick one, every column standardized by mu and sd.
     rows, labels (each row's cluster, 0-based), k, cols, means (k x columns,
     the columns' units), value(c, r) a row's value (the table's by default). */
  function parallelPlot(ctx, { rows, labels, k, cols, means, mu, sd, value = null }) {
    const tc = SM.util.themeColors();
    const names = cols.map((c) => c.name);
    const traces = [];
    const val = value || ((c, r) => c.values[r]);
    const zrow = (vals) => vals.map((v, j) => (v == null ? null : (v - mu[j]) / sd[j]));
    if (rows.length * cols.length <= 30000) {
      for (let c = 0; c < k; c++) {
        const xs = [], ys = [];
        rows.forEach((r, i) => { if (labels[i] !== c) return; cols.forEach((col, j) => { xs.push(names[j]); ys.push((val(col, r) - mu[j]) / sd[j]); }); xs.push(null); ys.push(null); });
        traces.push({ type: 'scatter', mode: 'lines', x: xs, y: ys, line: { color: pal(c), width: 0.6 }, opacity: 0.25, hoverinfo: 'skip', showlegend: false });
      }
    }
    means.forEach((m, c) => traces.push({ type: 'scatter', mode: 'lines+markers', x: names, y: zrow(m), line: { color: pal(c), width: 3 }, marker: { size: 7 }, name: `Cluster ${c + 1}`, hovertemplate: `cluster ${c + 1}, %{x}: %{y:.3f} sd<extra></extra>` }));
    return ctx.plot(traces, { showlegend: true, xaxis: { type: 'category', showgrid: true }, yaxis: { title: { text: 'Standardized value' }, zeroline: true, zerolinecolor: tc.muted } }, { width: fitW(Math.min(760, 180 + 90 * names.length)), height: 320, title: `Parallel coordinates, ${k} clusters`, select: false });
  }
  const kmParallel = (ctx, res, f, cols) => parallelPlot(ctx, { rows: res.rows, labels: f.labels, k: f.k, cols, means: f.means, mu: res.mean, sd: res.sd });

  function kmSplom(ctx, res, f, cols) {
    const box = el('div');
    const names = cols.map((c) => c.name), w = ctx.name('weight'), fq = ctx.name('freq');
    const frame = w || fq
      ? [`X = df[${J(names)}]`, `w = ${[w, fq].filter(Boolean).map((c) => `df[${J(c)}]`).join(' * ')}`, 'X = X[X.notna().all(axis=1) & w.gt(0)]   # the rows the clusters were fitted to: every column and a positive weight']
      : [`X = df[${J(names)}].dropna()   # the rows the clusters were fitted to: every column`];
    box.append(...scatterMatrix(ctx, cols, res.rows, { format: 'lower', points: true, ellipses: false, corr: false, hist: false, fit: false, level: 0.9 }, frame).filter(Boolean));
    box.append(ctx.note('Colour the rows by cluster (Save Colors to Table) to see the clusters here.'));
    return box;
  }

  SM.platforms.register({
    id: 'kmeans', label: 'K Means Cluster', menu: 'Analyze/Clustering', order: 20, info: 'p:kmeans',
    about: 'k-means clustering of the rows for one number of clusters or a range, from seeded k-means++ starts with several restarts, compared by the cubic clustering criterion, pseudo F, R² and the within sum of squares (with their graph by k), JMP\'s Single Step; cluster means and standard deviations, a biplot in principal components, parallel coordinates, saved clusters and distances for every row, the cluster and distance formulas, cluster colours.',
    uses: ["numpy (Lloyd's algorithm, k-means++ seeding)", 'scipy.cluster.vq.kmeans2 (in the code shown, and the tests)', "the cubic clustering criterion (Sarle 1983)"],
    topics: {
      'p:kmeans': {
        kicker: 'Analyze > Clustering', title: 'K Means Cluster',
        lead: 'Splits the rows into k clusters around k centres: each row goes to the nearest centre, each centre moves to the mean of its rows, until nothing changes.',
        sections: [
          { heading: 'Starts', text: 'k-means++ chooses the first centres far apart, from a fixed seed so that a report is reproducible; the best of several restarts (by the within-cluster sum of squares) is kept. The clusters are numbered by size.' },
          { heading: 'Choosing k', text: 'With a Range of Clusters, every k from Number of Clusters to the range is fitted and compared: the largest cubic clustering criterion is marked Optimal CCC. Pseudo F and R² are shown beside it, and a graph of the four criteria (CCC, pseudo F, R², within sum of squares) by k shows the elbow of the within sum of squares.' },
          { heading: 'Differences from JMP', text: 'JMP seeds its clusters from the order of the rows; here k-means++ with restarts is used, so the clusters can differ. The CCC is computed as SAS PROC CLUSTER does (from the eigenvalues of the covariance matrix); JMP may use FASTCLUS\'s variant. Self organizing maps and within-cluster scaling are not here.' },
        ],
        more: { label: 'K Means Cluster', id: 'help-p-kmeans' },
      },
      'km:control': {
        kicker: 'K Means Cluster', title: 'Iterative Clustering', lead: 'Number of Clusters and an optional Range of Clusters (up to 30 more) choose what is fitted; Columns Scaled Individually scales each column to standard deviation 1 first. Restarts and Seed set the k-means++ starts. Press Go.',
        sections: [{ heading: 'The controls', choices: [
          ['Number of Clusters', 'k, the number of clusters; with a range, the smallest k fitted. 3 by default.'],
          ['Range of Clusters (Optional)', 'A larger k: every k from Number of Clusters up to it (at most 30 more) is fitted and compared in Cluster Comparison, the one with the largest CCC marked. Empty fits one k.'],
          ['Columns Scaled Individually', 'Scale each column to standard deviation 1 first (on by default), so that columns in large units do not dominate the distances.'],
          ['Restarts', 'How many k-means++ starts; the fit with the smallest within-cluster sum of squares is kept. 10 by default, 1 to 100.'],
          ['Seed', 'The seed of the random starts: the same seed gives the same clusters.'],
          ['Single Step', 'JMP\'s Single Step: Go then shows each number of clusters at its starting centres (one k-means++ start, the Restarts not used), with Step and Go buttons in its report: Step assigns every row to its nearest centre and moves each centre to the mean of its rows, once; Go goes on until the centres stop moving (the fit with one restart). The clusters keep the numbers of their starting centres.'],
          ['Go', 'Fit with these settings; what is typed in the fields is used only when Go is pressed.']] }],
        more: { label: 'K Means Cluster', id: 'help-p-kmeans' },
      },
      'km:fit': {
        kicker: 'K Means Cluster', title: 'A k-means fit',
        lead: 'The clusters of one k: their sizes, means and standard deviations in the columns\' units, and a biplot on the first two principal components with a 90% ellipse around each cluster.',
        sections: [{ heading: 'In the report', choices: [
          ['The cluster buttons', 'One per cluster with its number of rows: a click selects its rows (with shift, adds them to the selection).'],
          ['A line of Cluster Summary', 'Click it to select the rows of that cluster.'],
          ['Step', 'With Single Step: one more iteration, every row to its nearest centre and each centre to the mean of its rows.'],
          ['Go', 'With Single Step: the iterations until the centres stop moving.']] },
          { heading: 'Saved columns', choices: [['Save Clusters', 'Cluster and Distance (the squared Euclidean distance to the cluster\'s centre, where the clustering is: the columns scaled, as JMP\'s Distance) for every row whose columns are present, excluded rows too: each in the cluster of its nearest centre.'], ['Save Cluster Formula', 'The same cluster as a live formula column (JMP\'s Cluster Formula): the nearest centre by the squared Euclidean distance.'], ['Save Distance Formulas', 'The k squared distances to the centres, as formula columns.']] }],
        more: { label: 'K Means Cluster', id: 'help-p-kmeans' },
      },
    },
    launch: {
      lead: 'Choose the numeric columns to cluster the rows by.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 1, numeric: true, types: ['continuous', 'ordinal'], hint: 'required: numeric',
          help: 'The columns the distances between the rows are measured in. Rows with a missing value in any of them are left out.' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'Weights each row\'s pull on its cluster\'s mean and its share of the within-cluster sum of squares. Rows with a missing, zero or negative weight are left out.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'A count per row: the row counts as that many identical rows.' },
        { key: 'by', label: 'By', hint: 'optional', help: BY_HELP },
      ],
      options: [
        { key: 'k', label: 'Number of Clusters', type: 'number', value: 3,
          help: 'k, the number of clusters to fit; with a Range of Clusters, the smallest k. The report\'s Iterative Clustering panel changes it later.' },
        { key: 'kRange', label: 'Range of Clusters (optional)', type: 'number', value: null,
          help: 'A larger k: every k from Number of Clusters up to this one is fitted and compared by the cubic clustering criterion in Cluster Comparison. Empty fits one k.' },
        { key: 'scaled', label: 'Columns Scaled Individually', type: 'check', value: true,
          help: 'Scale each column to standard deviation 1 before clustering (on by default), so that columns in large units do not dominate the distances. Off: the columns in their own units.' },
      ],
    },
    title: () => 'K Means Cluster',
    triangle(ctx) {
      return [ctx.check('Cluster Comparison', 'comparison', null, true)];
    },
    render: kmRender,
  });

  /* ======================================================================
     TEST MANY RESPONSES
     ====================================================================== */
  function openFitYbyX(ctx, r) {
    const P = SM.platforms.get('fitybyx');
    const y = ctx.table.col(r.y), x = ctx.table.col(r.x);
    if (!P) { SM.ui.toast('Bivariate Analysis is not loaded on this page'); return; }
    if (!y || !x) return;
    SM.app.openReport(P, { roles: { y: [y.id], x: [x.id] }, options: {} }, ctx.table);
  }

  async function rsRender(ctx) {
    const o = (k, d) => ctx.opt(k, d);
    const res = await mcall(ctx, 'respscreen.fit', { y: ctx.names('y'), x: ctx.names('x'), weight: ctx.name('weight'), freq: ctx.name('freq'), alpha: ctx.alpha, max_logworth: o('maxLogworth', 1000) });
    const box = ctx.container;
    const all = res.results;
    const tested = all.filter((r) => r.p != null);
    if (!tested.length) { box.append(ctx.warn('No pair could be tested: every pair has too few rows or a constant column.')); return; }
    const a = ctx.alpha;
    box.append(el('div', { class: 'mv-summary' },
      el('span', null, el('strong', { text: String(res.n_tests) }), ' tests'),
      el('span', null, el('strong', { text: String(res.n_sig_raw) }), ` with p < ${a}`),
      el('span', null, el('strong', { text: String(res.n_sig) }), ` with FDR p < ${a}`),
      all.length > tested.length ? el('span', { text: `${all.length - tested.length} pairs not tested (too few rows or a constant column)` }) : null));
    const click = (gd) => gd.on('plotly_click', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt && Number.isInteger(pt.customdata)) openFitYbyX(ctx, all[pt.customdata]); });
    const idx = tested.map((r) => all.indexOf(r));
    const hover = idx.map((i) => `${all[i].y} by ${all[i].x}<br>p ${SM.util.fmtP(all[i].p, a)}, FDR p ${SM.util.fmtP(all[i].fdr_p, a)}`);
    if (o('fdrPlot', true)) {
      const byRank = idx.slice().sort((i, j) => all[i].rank_fraction - all[j].rank_fraction);
      const floor = (p) => Math.max(p, 1e-300);
      const rf = byRank.map((i) => all[i].rank_fraction);
      ctx.outline('FDR PValue Plot', { key: 'fdrplot', info: 'rs:fdr' }).add(ctx.plot([
        { type: 'scatter', mode: 'markers', x: rf, y: byRank.map((i) => floor(all[i].p)), customdata: byRank, marker: { color: RED, size: 6 }, name: 'PValue', hovertext: byRank.map((i) => hover[idx.indexOf(i)]), hovertemplate: '%{hovertext}<extra>PValue</extra>' },
        { type: 'scatter', mode: 'markers', x: rf, y: byRank.map((i) => floor(all[i].fdr_p)), customdata: byRank, marker: { color: '#2f6ec7', size: 6, symbol: 'diamond' }, name: 'FDR PValue', hovertext: byRank.map((i) => hover[idx.indexOf(i)]), hovertemplate: '%{hovertext}<extra>FDR PValue</extra>' },
        { type: 'scatter', mode: 'lines', x: [0, 1], y: [a, a], line: { color: '#2f6ec7', width: 1.2 }, hoverinfo: 'skip', name: `α = ${a}` },
        { type: 'scatter', mode: 'lines', x: Array.from({ length: 51 }, (_, q) => Math.max(1e-3, q / 50)), y: Array.from({ length: 51 }, (_, q) => a * Math.max(1e-3, q / 50)), line: { color: RED, width: 1.2, dash: 'dot' }, hoverinfo: 'skip', name: 'FDR threshold for p' },
      ], { showlegend: true, legend: { orientation: 'h', y: -0.25 }, xaxis: { title: { text: 'Rank Fraction' }, range: [0, 1.02] }, yaxis: { title: { text: 'PValue' }, type: 'log', exponentformat: 'power' } }, { width: fitW(520), height: 340, title: 'FDR PValue Plot', select: false, onDraw: click }), ctx.code(res.fdr_code),
      ctx.note('The p-values (red) and the FDR-adjusted p-values (blue) in order of significance. A test is significant at the false discovery rate α where its FDR p-value is below the blue line, or equally where its p-value is below the dotted red line. Click a point for its Bivariate Analysis.'));
    }
    if (o('lwEffect', true)) {
      ctx.outline('FDR LogWorth by Effect Size', { key: 'lweffect' }).add(ctx.plot([{
        type: 'scatter', mode: 'markers', x: idx.map((i) => all[i].effect), y: idx.map((i) => all[i].fdr_logworth), customdata: idx, hovertext: hover, hovertemplate: '%{hovertext}<br>effect size %{x:.4g}<extra></extra>',
        marker: { size: 7, color: idx.map((i) => (all[i].fdr_p < a ? RED : SM.util.themeColors().muted)) },
      }], { xaxis: { title: { text: 'Effect Size' }, rangemode: 'tozero' }, yaxis: { title: { text: 'FDR LogWorth' }, rangemode: 'tozero' }, shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 2, y1: 2, line: { color: RED, width: 1, dash: 'dot' } }] },
      { width: fitW(500), height: 320, title: 'FDR LogWorth by Effect Size', select: false, onDraw: click }), ctx.code(res.effect_code),
      ctx.note('FDR LogWorth −log10(FDR p) against the effect size: √(model mean square)/robust σ for a continuous Y (σ from the IQR/1.349 unless the IQR is too small), √(χ²/DF) for a categorical one. The dotted line is FDR p = 0.01. Click a point for its Bivariate Analysis.'));
    }
    if (o('lwR2', false)) {
      const cy = idx.filter((i) => all[i].r2 != null);
      ctx.outline('FDR LogWorth by RSquare', { key: 'lwr2' }).add(ctx.plot([{ type: 'scatter', mode: 'markers', x: cy.map((i) => all[i].r2), y: cy.map((i) => all[i].fdr_logworth), customdata: cy, hovertext: cy.map((i) => hover[idx.indexOf(i)]), hovertemplate: '%{hovertext}<br>RSquare %{x:.4f}<extra></extra>', marker: { size: 7, color: SM.report.BASE } }],
        { xaxis: { title: { text: 'RSquare' }, range: [0, 1] }, yaxis: { title: { text: 'FDR LogWorth' }, rangemode: 'tozero' } }, { width: fitW(480), height: 300, title: 'FDR LogWorth by RSquare', select: false, onDraw: click }), ctx.code(res.r2_code));
    }
    const rows = all.slice().sort((p, q) => (q.fdr_logworth ?? -1) - (p.fdr_logworth ?? -1));
    ctx.outline('PValues', { key: 'pvalues' }).add(ctx.rt({
      columns: [{ key: 'y', label: 'Y', fmt: 'text' }, { key: 'x', label: 'X', fmt: 'text' }, { key: 'count', label: 'Count' }, { key: 'p', label: 'PValue', fmt: 'p' }, { key: 'logworth', label: 'LogWorth', digits: 4 }, { key: 'fdr_p', label: 'FDR PValue', fmt: 'p' },
        { key: 'fdr_logworth', label: 'FDR LogWorth', digits: 4 }, { key: 'effect', label: 'Effect Size', digits: 4 }, { key: 'rank_fraction', label: 'Rank Fraction', digits: 4 }, { key: 'r2', label: 'RSquare', digits: 4 }, { key: 'test', label: 'Test', fmt: 'text' }, { key: 'stat', label: 'Statistic', digits: 5, hidden: true }, { key: 'df', label: 'DF', hidden: true }],
      rows,
    }, { name: 'Test Many Responses PValues', maxRows: 1000, onRow: (r) => openFitYbyX(ctx, r) }), ctx.note('Sorted by FDR LogWorth. Continuous Y: the F test of Bivariate Analysis (Oneway ANOVA or the regression); categorical Y: the likelihood-ratio χ² of the contingency table or of the logistic fit. FDR p-values by Benjamini and Hochberg (statsmodels multipletests). Click a line to open its Bivariate Analysis; right click to make a data table.'),
    ctx.code(res.code));
    screenedModel(ctx, all, res.code);
  }

  /* The bivariate screening of a model's candidates (Hosmer and Lemeshow's
     purposeful selection starts so): for each Y, the X's whose p-value (or
     FDR p-value) is below the cut, 0.25 by default, and Fit Model with them. */
  function screenedOf(all, ys, cut, by) {
    const key = by === 'fdr' ? 'fdr_p' : 'p';
    return ys.map((y) => ({ y, xs: all.filter((r) => r.y === y && r[key] != null && r[key] < cut).sort((a, b) => a[key] - b[key]).map((r) => r.x) }));
  }

  function openScreenedModel(ctx, picks) {
    const P = SM.platforms.get('fitmodel');
    if (!P) { SM.ui.toast('Fit Model is not loaded on this page', { error: true }); return 0; }
    const ids = (k) => ((ctx.spec.roles && ctx.spec.roles[k]) || []).slice();
    let opened = 0;
    for (const { y, xs } of picks) {
      const yc = ctx.table.col(y);
      const xc = xs.map((x) => ctx.table.col(x)).filter(Boolean);
      if (!yc || !xc.length) continue;
      const personality = !yc.isCategorical ? 'standard' : yc.modelingType === 'ordinal' ? 'ordinal' : 'nominal';
      SM.app.openReport(P, { roles: { y: [yc.id], weight: ids('weight'), freq: ids('freq'), by: ids('by') }, effects: xc.map((c) => ({ cols: [c.id], names: [c.name], nest: [], nestNames: [], random: false })), options: { personality } }, ctx.table);
      opened++;
    }
    return opened;
  }

  // the screened X's in the code: the screening's own code (res.code makes the table res), then the cut
  // (joined as SM.predict joins a graph's code to its head: Save Python Script keeps the screening's code once)
  const screenedCode = (code, cut, by) => (code ? [`${code}\n\n# ----`,
    `cut = ${pyNum(cut)}   # the p-value cut`,
    `screened = res[res[${J(by === 'fdr' ? 'FDR_PValue' : 'PValue')}] < cut].sort_values(${J(by === 'fdr' ? 'FDR_PValue' : 'PValue')}).groupby("Y", sort=False)["X"].apply(list)   # each Y's X's below it`,
    'print(screened)   # Fit Model takes them as main effects'].join('\n') : null);

  function screenedModel(ctx, all, code) {
    const cut = ctx.opt('fmCut', 0.25), by = ctx.opt('fmBy', 'p');
    const ys = [...new Set(all.map((r) => r.y))];
    const picks = screenedOf(all, ys, cut, by);
    const ob = ctx.outline('Fit Model with the Screened X\'s', { key: 'screened', info: 'rs:model', closed: !ctx.opt('fmOpen', false) });
    const go = button('Fit Model', () => {
      const cur = screenedOf(all, ys, ctx.opt('fmCut', 0.25), ctx.opt('fmBy', 'p'));
      const none = cur.filter((q) => !q.xs.length).map((q) => q.y);
      const n = openScreenedModel(ctx, cur);
      if (!n) SM.ui.toast(`No X has a ${ctx.opt('fmBy', 'p') === 'fdr' ? 'FDR p-value' : 'p-value'} below ${ctx.opt('fmCut', 0.25)}: nothing to fit`, { error: true });
      else if (none.length) SM.ui.toast(`Opened Fit Model for ${n} response${n > 1 ? 's' : ''}; ${none.join(', ')} ${none.length > 1 ? 'have' : 'has'} no X below the cut`);
    }, 'primary');
    ob.add(controls(control('p-value below', numberEl(cut, (v) => { if (v > 0 && v <= 1) ctx.set('fmCut', v); else SM.ui.toast('The cut is a p-value, above 0 and at most 1', { error: true }); }, { size: 5, aria: 'p-value cut' })),
      control('by', selectEl(by, [['p', 'PValue'], ['fdr', 'FDR PValue']], (v) => ctx.set('fmBy', v), 'which p-value')), go),
      ctx.rt({ columns: [{ key: 'y', label: 'Y', fmt: 'text' }, { key: 'n', label: 'X\'s', fmt: 'int' }, { key: 'xs', label: `X's with ${by === 'fdr' ? 'FDR p' : 'p'} < ${cut}`, fmt: 'text' }],
        rows: picks.map((q) => ({ y: q.y, n: q.xs.length, xs: q.xs.join(', ') || '(none)' })) }, { sortable: false, key: 'screened' }), ctx.code(screenedCode(code, cut, by)),
      ctx.note(`Fit Model opens a model for each Y with its X's below the cut as main effects (least squares for a continuous Y, logistic for a categorical one), with the report's Weight, Freq and By: the purposeful selection of Hosmer and Lemeshow starts with the X's whose p-value alone is below 0.25, a loose cut that keeps variables whose effect only shows beside the others. Not in JMP.`));
  }

  SM.platforms.register({
    id: 'respscreen', label: 'Test Many Responses', menu: 'Analyze/Screening', order: 10, info: 'p:respscreen',
    about: 'Tests every Y against every X as Bivariate Analysis would (ANOVA or regression F for a continuous Y, the likelihood-ratio χ² of a contingency table or a logistic fit for a categorical one), with false discovery rate p-values, LogWorths, effect sizes and R²; the FDR PValue plot, FDR LogWorth by effect size, and a table whose lines open Bivariate Analysis; beyond JMP, Fit Model with each Y\'s X\'s below a p-value cut (bivariate screening).',
    uses: ['scipy.stats: f_oneway, linregress, chi2_contingency', 'statsmodels: Logit, MNLogit, GLM (frequency weights), WLS', 'statsmodels.stats.multitest.multipletests (fdr_bh)'],
    topics: {
      'p:respscreen': {
        kicker: 'Analyze > Screening', title: 'Test Many Responses',
        lead: 'Many tests at once: each Y against each X. With many tests some small p-values appear by chance, so the p-values are also adjusted to control the false discovery rate (the expected share of false positives among the tests called significant).',
        sections: [
          { heading: 'The tests', choices: [['Continuous Y, categorical X', 'Oneway analysis of variance F.'], ['Continuous Y, continuous X', 'Simple linear regression F.'], ['Categorical Y, categorical X', 'Likelihood-ratio χ² of the contingency table.'], ['Categorical Y, continuous X', 'Likelihood-ratio χ² of the (multinomial) logistic regression.']] },
          { heading: 'LogWorth', text: '−log10(p): 2 is p = 0.01, 3 is p = 0.001. FDR LogWorth is the same for the FDR p-value (Benjamini-Hochberg).' },
          { heading: 'Differences from JMP', text: 'The robust, Cauchy, Poisson and negative binomial fits, the Grouping and Subgroup roles, the practical-significance and equivalence tests and the means-differences reports are not here. Weight and Freq act as frequency weights.' },
        ],
        more: { label: 'Test Many Responses', id: 'help-p-respscreen' },
      },
      'rs:model': {
        kicker: 'Test Many Responses', title: 'Fit Model with the Screened X\'s',
        lead: 'The bivariate screening of a model\'s candidates: for each Y, the X\'s whose p-value against it is below the cut, and a Fit Model report with them as main effects (Standard Least Squares for a continuous Y, Nominal or Ordinal Logistic for a categorical one), the report\'s Weight, Freq and By kept. A loose cut such as 0.25 (Hosmer and Lemeshow) keeps variables that matter only together with others; the model then shows which to keep. Not in JMP.',
        sections: [{ heading: 'In the report', choices: [
          ['p-value below', 'The cut, above 0 and at most 1: an X whose p-value is below it goes into the model. 0.25 by default.'],
          ['by', 'PValue, the default: each test\'s own p-value; FDR PValue: the false-discovery-rate p-value, a stricter cut when there are many tests.'],
          ['Fit Model', 'Opens a Fit Model report for each Y with an X below the cut.']] }],
        more: { label: 'Test Many Responses', id: 'help-p-respscreen' },
      },
      'rs:fdr': { kicker: 'Test Many Responses', title: 'FDR PValue Plot', lead: 'The tests sorted by significance (rank fraction 1/m … 1). Red: the p-values; blue: the FDR p-values. Blue points under the solid line are significant at the false discovery rate α; equivalently red points under the dotted line α × rank fraction.', more: { label: 'Test Many Responses', id: 'help-p-respscreen' } },
    },
    launch: {
      lead: 'Choose many responses and factors: every pair is tested. A line of the report opens that pair in Bivariate Analysis.',
      roles: [
        { key: 'y', label: 'Y, Response', min: 1, hint: 'required: one or more',
          help: 'The responses, of any modeling type: each is tested against each X, a continuous Y by an F test, an ordinal or nominal one by a likelihood-ratio χ².' },
        { key: 'x', label: 'X', min: 1, hint: 'required: one or more',
          help: 'The factors, of any modeling type: a continuous X by a regression (or a logistic fit, for a categorical Y), an ordinal or nominal one by a one-way ANOVA (or a contingency table). Each pair uses the rows where both are present.' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'Weight and Freq together (their product) act as frequency weights in every test. Rows with a missing, zero or negative value are left out.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'A count per row: the row stands for that many observations in every test.' },
        { key: 'by', label: 'By', hint: 'optional', help: BY_HELP },
      ],
    },
    title: () => 'Test Many Responses',
    triangle(ctx) {
      return [
        ctx.check('FDR PValue Plot', 'fdrPlot', null, true), ctx.check('FDR LogWorth by Effect Size', 'lwEffect', null, true), ctx.check('FDR LogWorth by RSquare', 'lwR2', null, false),
        { label: 'Set α Level', submenu: () => levelOptions(ctx) },
        { label: 'Fit Model with the Screened X\'s', action: () => { ctx.set('fmOpen', true); } },
        { label: 'Max Logworth…', action: async () => { const v = await SM.ui.form({ title: 'Max Logworth', fields: [{ key: 'm', label: 'Largest LogWorth reported (larger ones are shown as this)', type: 'number', value: ctx.opt('maxLogworth', 1000),
          help: 'A cap on the LogWorths, −log₁₀ p, and the FDR LogWorths: larger ones are shown as this value, so that a few p-values near zero do not squeeze the rest of the plots. 1000 by default.' }] }); if (v && v.m > 0) ctx.set('maxLogworth', v.m); } },
      ];
    },
    render: rsRender,
  });

  /* ======================================================================
     EXPLORE OUTLIERS
     ====================================================================== */
  const EO = [
    ['qro', 'Quantile Range Outliers', 'Univariate', 'Values far beyond the tail quantiles; finds error and missing-value codes such as 9999.'],
    ['rfo', 'Robust Fit Outliers', 'Univariate', 'Values more than K robust spreads from a robust centre (Huber, Cauchy or quartiles).'],
    ['mro', 'Multivariate Robust Outliers', 'Multivariate', 'Rows far from the others in all the columns together: robust Mahalanobis distances (MCD).'],
    ['knn', 'Multivariate k-Nearest Neighbor Outliers', 'Multivariate', 'Rows far from their nearest neighbours.'],
  ];
  // the buttons under a method's report, as its (i) explains them
  const EO_ACTIONS = [
    ['Select Rows', 'Select the rows the method finds: those with an outlier in a column chosen in the table (every column listed when no line is chosen), or above the limit.'],
    ['Exclude Rows', 'Exclude those rows from every analysis; Rescan then screens the rows that are left.'],
    ['Color Rows', 'Colour those rows red, in the table and every graph.'],
    ['Rescan', 'Run the report again, after rows were excluded or values changed.'],
  ];
  // the two that change values, for the univariate methods (JMP's)
  const EO_VALUE_ACTIONS = [
    ['Add to Missing Value Codes', 'Add the outlier values of the chosen columns (every column listed when no line is chosen) to their Missing Value Codes column property: those values, 9999 say, are missing in every analysis from now on, and stay in the table as they were. One Edit > Undo takes it back. Not with By groups (the codes are the whole column\'s), as in JMP.'],
    ['Change to Missing', 'Overwrite the outlier cells of the chosen columns (every column listed when no line is chosen) with missing values: for values known to be wrong. A formula column\'s cells are left alone. One Edit > Undo takes it back.'],
  ];
  const EO_LINES = ['A line of Outliers by Column', 'Click it to choose that column (ctrl or ⌘ adds or takes away one, shift a sweep): its outlier rows are selected, and the buttons act on the chosen columns only. With no line chosen they act on every column listed.'];

  /* The lines chosen in a method's Outliers by Column table (JMP's buttons act
     on the table's selected rows): kept with the report for the session. */
  function eoChosen(ctx, key) {
    const all = ctx.report._eoChosen || (ctx.report._eoChosen = {});
    const k = `${key}\u0001${ctx.path || ''}`;
    return all[k] || (all[k] = { sel: new Set(), mark: {} });
  }

  /* The columns the value buttons act on: the chosen lines, else every column listed. */
  function eoColumnsOf(ch, cols) {
    const chosen = cols.filter((c) => ch.sel.has(c.column));
    return chosen.length ? chosen : cols;
  }

  function addToMissingCodes(ctx, cols) {
    const t = ctx.table;
    if (ctx.where && ctx.where.length) { SM.ui.toast('Add to Missing Value Codes is not available with By groups: the codes are the whole column\'s (as in JMP)', { error: true }); return; }
    if (typeof t.setMissingCodes !== 'function') { SM.ui.toast('This page has no Missing Value Codes yet', { error: true }); return; }
    const todo = cols.map((c) => ({ col: t.col(c.column), vals: (c.values || []).map((x) => x.value) })).filter((x) => x.col && x.vals.length);
    if (!todo.length) { SM.ui.toast('No outlier values to add'); return; }
    if (SM.app && SM.app.record) SM.app.record(t, 'Add to Missing Value Codes');
    let n = 0;
    for (const { col, vals } of todo) {
      const had = col.missingCodes || [];
      const add = vals.filter((v) => !had.includes(v));
      n += add.length;
      t.setMissingCodes(col.id, had.concat(add));
    }
    SM.ui.toast(`Added ${plural(n, 'value')} to the missing value codes of ${todo.map((x) => x.col.name).join(', ')}; Rescan to screen again`);
  }

  function changeToMissing(ctx, cells) {
    const t = ctx.table;
    const done = [], skipped = new Set();
    for (const { column, row } of cells) {
      const c = t.col(column);
      if (!c) continue;
      if (c.formula) { skipped.add(c.name); continue; }
      done.push([row, c]);
    }
    if (!done.length) { SM.ui.toast(skipped.size ? `${[...skipped].join(', ')}: a formula column's cells are left alone` : 'No outlier cells to change'); return; }
    if (SM.app && SM.app.record) SM.app.record(t, 'Change to Missing');
    for (const [row, c] of done) t.setCell(row, c.id, c.isNumeric ? NaN : null, { silent: true });
    t._changed('data', { cells: done.map(([row, c]) => [row, c.id]) });
    SM.ui.toast(`Changed ${plural(done.length, 'cell')} to missing${skipped.size ? ` (${[...skipped].join(', ')}: formula columns, left alone)` : ''}; Rescan to screen again`);
  }

  /* The buttons under a univariate method's report. of() gives the columns
     acted on (the chosen lines, else all listed), each with its outlier rows,
     values and cells. */
  function eoActions(ctx, rowsOf, what, values = null) {
    const extra = values ? [
      (() => { const b = button('Add to Missing Value Codes', () => addToMissingCodes(ctx, values.columns())); if (ctx.where && ctx.where.length) { b.disabled = true; b.title = 'Not with By groups: the codes are the whole column\'s (as in JMP)'; } return b; })(),
      button('Change to Missing', () => changeToMissing(ctx, values.cells())),
    ] : [];
    return controls(
      button('Select Rows', () => ctx.table.select(rowsOf())),
      button('Exclude Rows', () => { const rs = rowsOf(); if (rs.length) ctx.table.setState(rs, 'excluded', true); SM.ui.toast(`${rs.length} row${rs.length === 1 ? '' : 's'} excluded; Redo to rescan`); }),
      button('Color Rows', () => ctx.table.setColor(rowsOf(), 3)),
      ...extra,
      button('Rescan', () => ctx.report.run()),
      el('span', { class: 'sm-ob-note', text: what }),
    );
  }

  /* Outliers by Column with chosen lines: a click chooses (listClick), the
     chosen lines are marked and their outlier rows selected in the table. */
  function eoColumnTable(ctx, key, spec, cols) {
    const ch = eoChosen(ctx, key);
    const ids = cols.map((c) => c.column);
    for (const id of [...ch.sel]) if (!ids.includes(id)) ch.sel.delete(id);
    let tbl = null;
    const mark = () => { if (!tbl) return; [...tbl.tBodies[0].rows].forEach((tr, k) => { const r = tbl._rt.rows[k]; tr.classList.toggle('is-chosen', !!r && ch.sel.has(r.column)); }); };
    tbl = ctx.rt(spec, { onRow: (row, ev) => {
      SM.util.listClick(ev, row.column, ids, ch.sel, ch.mark);
      mark();
      ctx.table.select([...new Set(cols.filter((c) => ch.sel.has(c.column)).flatMap((c) => c.rows || []))].sort((a, b) => a - b));
    } });
    if (typeof MutationObserver !== 'undefined') new MutationObserver(mark).observe(tbl.tBodies[0], { childList: true });
    mark();
    return tbl;
  }

  async function eoRender(ctx) {
    const names = ctx.names('y');
    const o = (k, d) => ctx.opt(k, d);
    const box = ctx.container;
    const pick = el('div', { class: 'mv-methods', role: 'group', 'aria-label': 'Outlier methods' });
    let group = null;
    for (const [key, label, g, about] of EO) {
      // the first heading carries the (i) that explains the buttons
      if (g !== group) { pick.append(el('h5', null, g, group === null && typeof KvotInfo !== 'undefined' ? KvotInfo.slot('p:outliers') : null)); group = g; }
      const b = el('button', { type: 'button', class: `mv-method${o(key, false) ? ' is-on' : ''}`, 'aria-pressed': String(!!o(key, false)) }, el('strong', { text: label }), el('span', { text: about }));
      b.addEventListener('click', () => ctx.set(key, !o(key, false)));
      pick.append(b);
    }
    box.append(pick);
    if (!EO.some(([k]) => o(k, false))) box.append(ctx.note('Choose a method above (or from the red triangle).'));
    if (o('qro', false)) await qroOutline(ctx, names);
    if (o('rfo', false)) await rfoOutline(ctx, names);
    if (o('mro', false)) await mroOutline(ctx, names);
    if (o('knn', false)) await knnOutline(ctx, names);
  }

  const valuesText = (vals) => vals.slice(0, 12).map((x) => `${fmt(x.value)}${x.count > 1 ? ` (${x.count})` : ''}`).join(', ') + (vals.length > 12 ? ` … ${vals.length - 12} more` : '');

  async function qroOutline(ctx, names) {
    const o = (k, d) => ctx.opt(k, d);
    const tail = o('tail', 0.1), q = o('q', 3), ints = o('integers', false), only = o('onlyOutliers', false);
    const r = await mcall(ctx, 'outliers.quantile', { columns: names, tail, q, integers: ints });
    const ob = ctx.outline('Quantile Range Outliers', { key: 'qro', info: 'eo:qro', menu: () => [{ label: 'Close', action: () => ctx.set('qro', false) }] });
    const ib = el('input', { type: 'checkbox', 'aria-label': 'Restrict search to integers' });
    ib.checked = !!ints;
    ib.addEventListener('change', () => ctx.set('integers', ib.checked));
    const onlyBox = el('input', { type: 'checkbox', 'aria-label': 'Show only columns with outliers' });
    onlyBox.checked = !!only;
    onlyBox.addEventListener('change', () => ctx.set('onlyOutliers', onlyBox.checked));
    ob.add(controls(control('Tail Quantile', numberEl(tail, (v) => { if (v > 0 && v < 0.5) ctx.set('tail', v); }, { size: 5, aria: 'Tail quantile' })), control('Q', numberEl(q, (v) => { if (v > 0) ctx.set('q', v); }, { size: 4, aria: 'Q' })),
      control('Restrict search to integers', ib), control('Show only columns with outliers', onlyBox)));
    const cols = r.columns.filter((c) => c.low_q != null && (!only || c.count > 0));
    const lq = `${fmt(100 * tail)}%`, hq = `${fmt(100 * (1 - tail))}%`;
    const ch = eoChosen(ctx, 'qro');
    const acted = () => eoColumnsOf(ch, cols);
    const allRows = () => [...new Set(acted().flatMap((c) => c.rows || []))].sort((a, b) => a - b);
    const values = { columns: () => acted().filter((c) => c.count > 0), cells: () => { const names = new Set(acted().map((c) => c.column)); return r.cells.filter((c) => names.has(c.column)); } };
    ob.add(eoActions(ctx, allRows, 'act on the outliers of the columns chosen in the table, or of every column listed', values),
      eoColumnTable(ctx, 'qro', { columns: [{ key: 'column', label: 'Column', fmt: 'text' }, { key: 'low_q', label: `${lq} Quantile` }, { key: 'high_q', label: `${hq} Quantile` }, { key: 'low_t', label: 'Low Threshold' }, { key: 'high_t', label: 'High Threshold' }, { key: 'count', label: 'Count', fmt: 'int' }, { key: 'vals', label: 'Outliers', fmt: 'text' }], rows: cols.map((c) => ({ ...c, vals: valuesText(c.values) })), caption: 'Outliers by Column' }, cols),
      ctx.note(`A value is an outlier when it is more than Q × (the ${hq} − the ${lq} quantile) below the ${lq} or above the ${hq} quantile (quantiles as Distribution computes them).`));
    const byCell = ctx.outline('Outliers by Cell', { key: 'qro:cell', parent: ob, closed: true });
    byCell.add(ctx.rt({ columns: [{ key: 'column', label: 'Column', fmt: 'text' }, { key: 'row', label: 'Row', fmt: 'int' }, { key: 'distance', label: 'Outlier Distance', digits: 4 }, { key: 'value', label: 'Value' }], rows: r.cells.map((c) => ({ ...c, row: c.row + 1, _r: c.row })) }, { maxRows: 500, onRow: (row, ev) => ctx.table.select([row._r], ev.shiftKey ? 'add' : 'replace') }), ctx.note('Outlier distance: (value − median)/interquantile range.'));
    const counts = new Map();
    for (const c of r.cells) counts.set(c.row, (counts.get(c.row) || 0) + 1);
    ctx.outline('Outliers by Row', { key: 'qro:row', parent: ob, closed: true }).add(ctx.rt({ columns: [{ key: 'row', label: 'Row', fmt: 'int' }, { key: 'n', label: 'Number of Outliers', fmt: 'int' }], rows: [...counts.entries()].sort((a, b) => a[0] - b[0]).map(([row, n]) => ({ row: row + 1, n, _r: row })) }, { maxRows: 500, onRow: (row, ev) => ctx.table.select([row._r], ev.shiftKey ? 'add' : 'replace') }));
    if (r.nines.length) {
      ctx.outline('Nines', { key: 'qro:nines', parent: ob }).add(ctx.rt({ columns: [{ key: 'column', label: 'Column', fmt: 'text' }, { key: 'value', label: 'Highest Nines' }, { key: 'count', label: 'Count', fmt: 'int' }, { key: 'high_q', label: `${hq} Quantile` }], rows: r.nines }, { onRow: (row, ev) => ctx.table.select(row.rows, ev.shiftKey ? 'add' : 'replace') }),
        ctx.note('Values made of nines above the upper quantile are often codes for missing values; many of them suggest a code, one or two may be outliers. Click a line to select those rows (then Rows > Exclude, or change the cells).'));
    }
    ob.add(ctx.code(r.code));
  }

  async function rfoOutline(ctx, names) {
    const o = (k, d) => ctx.opt(k, d);
    const method = o('rfMethod', 'huber'), K = o('kSigma', 4);
    const r = await mcall(ctx, 'outliers.robust', { columns: names, method, k: K });
    const ob = ctx.outline('Robust Fit Outliers', { key: 'rfo', info: 'eo:rfo', menu: () => [{ label: 'Close', action: () => ctx.set('rfo', false) }] });
    ob.add(controls(control('Method', selectEl(method, [['huber', 'Huber'], ['cauchy', 'Cauchy'], ['quartile', 'Quartile']], (v) => ctx.set('rfMethod', v), 'Robust method')), control('K Sigma', numberEl(K, (v) => { if (v > 0) ctx.set('kSigma', v); }, { size: 4, aria: 'K sigma' }))));
    const cols = r.columns.filter((c) => c.center != null);
    const ch = eoChosen(ctx, 'rfo');
    const acted = () => eoColumnsOf(ch, cols);
    const allRows = () => [...new Set(acted().flatMap((c) => c.rows || []))].sort((a, b) => a - b);
    const values = { columns: () => acted().filter((c) => c.count > 0), cells: () => { const names = new Set(acted().map((c) => c.column)); return r.cells.filter((c) => names.has(c.column)); } };
    ob.add(eoActions(ctx, allRows, 'act on the outliers of the columns chosen in the table, or of every column listed', values),
      eoColumnTable(ctx, 'rfo', { columns: [{ key: 'column', label: 'Column', fmt: 'text' }, { key: 'center', label: `${{ huber: 'Huber', cauchy: 'Cauchy', quartile: 'Quartile' }[method]} Center` }, { key: 'spread', label: 'Spread' }, { key: 'low_t', label: 'Low Threshold' }, { key: 'high_t', label: 'High Threshold' }, { key: 'count', label: 'Count', fmt: 'int' }, { key: 'vals', label: 'Outliers', fmt: 'text' }], rows: cols.map((c) => ({ ...c, vals: valuesText(c.values) })), caption: 'Outliers by Column' }, cols),
      ctx.note({ huber: "Huber's M-estimates of location and scale (statsmodels.robust.scale.Huber).", cauchy: 'The location and scale of a Cauchy distribution fitted by maximum likelihood (scipy.stats.cauchy.fit).', quartile: 'The median and the interquartile range over 1.34898.' }[method] + ` Outliers lie more than ${fmt(K)} spreads from the centre.`));
    ctx.outline('Outliers by Cell', { key: 'rfo:cell', parent: ob, closed: true }).add(ctx.rt({ columns: [{ key: 'column', label: 'Column', fmt: 'text' }, { key: 'row', label: 'Row', fmt: 'int' }, { key: 'distance', label: 'Outlier Distance', digits: 4 }, { key: 'value', label: 'Value' }], rows: r.cells.map((c) => ({ ...c, row: c.row + 1, _r: c.row })) }, { maxRows: 500, onRow: (row, ev) => ctx.table.select([row._r], ev.shiftKey ? 'add' : 'replace') }), ctx.note('Outlier distance: (value − centre)/spread.'));
    ob.add(ctx.code(r.code));
  }

  async function mroOutline(ctx, names) {
    const r = await mcall(ctx, 'outliers.multivariate', { columns: names, alpha: ctx.alpha });
    const ob = ctx.outline('Multivariate Robust Outliers', { key: 'mro', info: 'eo:mro', menu: () => [
      { label: 'Save Robust Distances', action: () => { if (!r.error) ctx.saveColumn('Robust Distance', { rows: r.rows, values: r.robust }, { notes: `robust Mahalanobis distance (reweighted MCD); limit ${fmt(r.limit)}` }); } },
      { label: 'Close', action: () => ctx.set('mro', false) },
    ] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const out = r.rows.filter((_, k) => r.robust[k] > r.limit);
    ob.add(eoActions(ctx, () => out, `${out.length} row${out.length === 1 ? '' : 's'} above the limit`),
      ctx.row(withCode(rowPlot(ctx, { rows: r.rows, y: r.robust, limit: r.limit, limitLabel: `√χ²(${fmt(1 - ctx.alpha)}, ${r.p})`, ytitle: 'Robust Distance', title: 'Robust distances by row', width: 520 }), ctx.code(r.robust_code)),
        withCode(ctx.plot([{ type: 'scatter', mode: 'markers', x: r.classical, y: r.robust, rows: r.rows, hovertext: rowLabels(ctx, r.rows), hovertemplate: '%{hovertext}<br>classical %{x:.3f}, robust %{y:.3f}<extra></extra>', marker: { size: 5 } }],
          { xaxis: { title: { text: 'Mahalanobis Distance' }, rangemode: 'tozero' }, yaxis: { title: { text: 'Robust Distance' }, rangemode: 'tozero' }, shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: r.limit, y1: r.limit, line: { color: RED, width: 1, dash: 'dash' } }, { type: 'line', yref: 'paper', x0: r.limit, x1: r.limit, y0: 0, y1: 1, line: { color: RED, width: 1, dash: 'dash' } }] },
          { width: 360, height: 250, title: 'Distance-distance plot' }), ctx.code(r.dd_code))),
      ctx.note(`Robust distances from the reweighted minimum covariance determinant estimate (FAST-MCD, the ${r.h} rows of ${r.n} with the smallest covariance determinant, then reweighted), against the classical Mahalanobis distances. Outliers mask one another in the classical distances; the robust ones show them. The limit is the square root of the ${fmt(1 - ctx.alpha)} χ² quantile with ${r.p} df.`), ctx.code(r.code));
  }

  async function knnOutline(ctx, names) {
    const K = ctx.opt('knnK', 8);
    const r = await mcall(ctx, 'outliers.knn', { columns: names, k: K });
    const ob = ctx.outline('Multivariate k-Nearest Neighbor Outliers', { key: 'knn', info: 'eo:knn', menu: () => [{ label: 'Close', action: () => ctx.set('knn', false) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    ob.add(controls(control('K', numberEl(K, (v) => { if (v >= 1) ctx.set('knnK', Math.round(v)); }, { size: 3, aria: 'K' }))));
    const plots = r.ks.map((k, i) => withCode(rowPlot(ctx, { rows: r.rows, y: r.dist[String(k)], ytitle: `Distance to neighbor ${k}`, title: `k = ${k}`, width: 380, height: 220 }), ctx.code(r.plots && r.plots[i] ? r.plots[i].plot_code : null)));
    ob.add(ctx.row(...plots), ctx.note('The Euclidean distance from each row to its kth nearest neighbour (scipy cKDTree), for k = 1, 2, 3, 5, 8, … up to K, on columns centred at the median and scaled by max(Q3 − median, median − Q1)/z(0.75). An isolated row stands out for small k; a small group of outliers only once k passes its size. Drag over points to select them.'), ctx.code(r.code));
  }

  SM.platforms.register({
    id: 'outliers', label: 'Explore Outliers', menu: 'Analyze/Screening', order: 30, info: 'p:outliers',
    about: 'Finds outliers four ways: quantile range (values far past the tail quantiles, and codes such as 9999), robust fit (Huber, Cauchy or quartile centre and spread), multivariate robust distances (the minimum covariance determinant) and distances to the k nearest neighbours; select, exclude or colour the rows, add the values found to the columns\' Missing Value Codes or change them to missing.',
    uses: ['numpy.quantile', 'statsmodels.robust.scale.Huber', 'scipy.stats.cauchy.fit', 'FAST-MCD (numpy)', 'scipy.spatial.cKDTree'],
    topics: {
      'p:outliers': {
        kicker: 'Analyze > Screening', title: 'Explore Outliers',
        lead: 'Screens continuous columns for unusual values before an analysis. Press a method; its report lists the outliers, and the buttons select, exclude or colour those rows.',
        sections: [
          { heading: 'Methods', choices: EO.map(([, label, , about]) => [label, about]) },
          { heading: 'The method buttons', text: 'Press a method at the top of the report to add its report below, and press it again to take it away; the red triangle has the same four.' },
          { heading: 'Changing the table', text: 'The univariate methods have JMP\'s Add to Missing Value Codes (the outlier values become missing value codes of their columns: missing in every analysis, still stored) and Change to Missing (the cells overwritten). Both act on the columns chosen in Outliers by Column, or on every column listed, and Edit > Undo takes either back; Rescan screens again.' },
          { heading: 'Differences from JMP', text: 'JMP\'s Robust PCA Outliers and Color Cells are not here; Multivariate Robust Outliers uses the reweighted MCD (FAST-MCD), JMP\'s older platform its robust covariance estimate. Add to Missing Value Codes and Change to Missing act on whole columns (their lines chosen in Outliers by Column), not on single cells chosen in Outliers by Cell.' },
        ],
        more: { label: 'Explore Outliers', id: 'help-p-outliers' },
      },
      'eo:qro': {
        kicker: 'Explore Outliers', title: 'Quantile Range Outliers', lead: 'With Tail Quantile t and multiplier Q, the thresholds are q(t) − Q·(q(1 − t) − q(t)) and q(1 − t) + Q·(q(1 − t) − q(t)). The defaults t = 0.1, Q = 3 flag only extreme values. Restrict search to integers keeps whole numbers only (error codes). Nines lists all-nines values above the upper quantile.',
        sections: [{ heading: 'In the report', choices: [
          ['Tail Quantile', 't, above 0 and below 0.5: the quantiles q(t) and q(1 − t) the thresholds are measured from. 0.1 by default.'],
          ['Q', 'How many interquantile ranges, q(1 − t) − q(t), beyond those quantiles a value must lie to be an outlier; 3 by default. A smaller Q flags more values.'],
          ['Restrict search to integers', 'Flag only the whole numbers among the outliers, as error and missing-value codes such as 999 usually are.'],
          ['Show only columns with outliers', 'Leave the columns without an outlier out of the table.'],
          ...EO_ACTIONS, ...EO_VALUE_ACTIONS, EO_LINES,
          ['A line of Outliers by Cell or by Row', 'Click it to select the rows of that cell or row (with shift, add them).']] }],
        more: { label: 'Explore Outliers', id: 'help-p-outliers' },
      },
      'eo:rfo': {
        kicker: 'Explore Outliers', title: 'Robust Fit Outliers', lead: 'A robust centre c and spread s per column; outliers lie outside c ± K·s (K = 4 by default). Huber\'s estimates resist a few outliers; Cauchy ones resist more but can follow the denser part of clustered data; Quartile uses the median and IQR/1.34898.',
        sections: [{ heading: 'In the report', choices: [
          ['Method', 'The robust centre and spread of each column: Huber, the default, M-estimates of location and scale (statsmodels); Cauchy, the location and scale of a Cauchy distribution fitted by maximum likelihood (scipy); Quartile, the median and the interquartile range over 1.34898.'],
          ['K Sigma', 'Values more than K spreads from the centre are outliers; 4 by default.'],
          ...EO_ACTIONS, ...EO_VALUE_ACTIONS, EO_LINES,
          ['A line of Outliers by Cell', 'Click it to select the row of that cell (with shift, add it).']] }],
        more: { label: 'Explore Outliers', id: 'help-p-outliers' },
      },
      'eo:mro': {
        kicker: 'Explore Outliers', title: 'Multivariate Robust Outliers', lead: 'The minimum covariance determinant estimate takes the half of the rows whose covariance has the smallest determinant, so outliers cannot pull it; the distances from it are robust. Rows above the limit are outliers in the columns jointly, even when no single value is extreme.',
        sections: [{ heading: 'In the report', choices: [...EO_ACTIONS, ['The plots', 'Drag over points to select their rows.']] }],
        more: { label: 'Explore Outliers', id: 'help-p-outliers' },
      },
      'eo:knn': {
        kicker: 'Explore Outliers', title: 'k nearest neighbour outliers', lead: 'Each row\'s distance to its 1st, 2nd, 3rd, 5th, 8th … nearest neighbour. Large distances mark isolated rows; a cluster of k or fewer outliers shows at the k after its size.',
        sections: [{ heading: 'In the report', choices: [
          ['K', 'The largest neighbour to plot: a graph for k = 1, 2, 3, 5, 8, 13, … up to K; 8 by default, at most one less than the rows.'],
          ['The plots', 'Drag over points to select their rows.']] }],
        more: { label: 'Explore Outliers', id: 'help-p-outliers' },
      },
    },
    launch: {
      lead: 'Choose the continuous columns to screen, then pick the methods in the report.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 1, numeric: true, types: ['continuous'], hint: 'required: continuous',
          help: 'The columns to screen: the univariate methods take each column alone, the multivariate ones all of them together (on the rows with no missing value).' },
        { key: 'label', label: 'Label', max: 1, hint: 'optional', help: LABEL_HELP },
        { key: 'by', label: 'By', hint: 'optional', help: BY_HELP },
      ],
    },
    title: () => 'Explore Outliers',
    triangle(ctx) {
      return EO.map(([key, label]) => ctx.check(label, key, null, false));
    },
    render: eoRender,
  });

  /* ======================================================================
     MULTIPLE CORRESPONDENCE ANALYSIS
     ====================================================================== */
  function dimPickers(ctx, K, a, b, keys = ['dx', 'dy']) {
    if (K <= 2) return null;
    const ch = Array.from({ length: K }, (_, j) => [j, `c${j + 1}`]);
    return controls(control('x', selectEl(a, ch, (v) => ctx.set(keys[0], +v), 'x dimension')), control('y', selectEl(b, ch, (v) => ctx.set(keys[1], +v), 'y dimension')));
  }

  async function mcaRender(ctx) {
    const cols = ctx.roles('y');
    const o = (k, d) => ctx.opt(k, d);
    const res = await mcall(ctx, 'mca.fit', { columns: cols.map((c) => c.name), freq: ctx.name('freq'), plot: { x: o('dx', 0), y: o('dy', 1) } });
    const box = ctx.container;
    if (res.error) { box.append(ctx.warn(res.error)); return; }
    const K = res.K;
    const a = Math.min(o('dx', 0), K - 1), b = Math.min(o('dy', 1), K - 1);
    const colOf = new Map(cols.map((c) => [c.name, c]));
    const lab = (lv) => SM.grid.cellText(colOf.get(lv.column), lv.level);
    const dimLabel = (j) => `c${j + 1} (${res.percent[j].toFixed(1)}%)`;
    box.append(ctx.note(`${fmt(res.n)} observations of ${res.Q} columns with ${res.J} levels in all; ${K} dimension${K > 1 ? 's' : ''}; total inertia (J − Q)/Q = ${fmt(res.total_inertia, { sig: 5 })}.`));
    const tc = SM.util.themeColors();
    if (o('plot', true)) {
      const ob = ctx.outline('Correspondence Analysis', { key: 'plot', info: 'p:mca' });
      const traces = cols.map((c, i) => {
        const L = res.levels.filter((lv) => lv.column === c.name);
        return { type: 'scatter', mode: L.length <= 40 ? 'markers+text' : 'markers', x: L.map((lv) => lv.coords[a]), y: L.map((lv) => (K > 1 ? lv.coords[b] : 0)), text: L.map(lab), textposition: 'top center', textfont: { size: 10, color: tc.text }, marker: { size: 8, color: pal(i), symbol: ['circle', 'square', 'diamond', 'triangle-up', 'cross', 'x'][i % 6] }, name: c.name, hovertemplate: `${tpl(c.name)}: %{text}<br>(%{x:.3f}, %{y:.3f})<extra></extra>` };
      });
      ob.add(ctx.plot(traces, { showlegend: true, legend: { orientation: 'h', y: -0.22 }, xaxis: { title: { text: dimLabel(a) }, zeroline: true }, yaxis: { title: { text: K > 1 ? dimLabel(b) : '' }, zeroline: true } }, { width: fitW(560), height: 440, title: 'Correspondence Analysis', select: false }), ctx.code(res.plot_code),
        dimPickers(ctx, K, a, b), ctx.note('The levels in principal coordinates: levels near each other are chosen by the same rows; a level far from the origin is rare or distinctive.'));
    }
    if (o('rowplot', false)) {
      ctx.outline('Row Plot', { key: 'rowplot' }).add(ctx.plot([{ type: 'scatter', mode: 'markers', x: res.row_coords.map((r) => r[Math.min(a, r.length - 1)]), y: res.row_coords.map((r) => (r.length > 1 ? r[Math.min(b, r.length - 1)] : 0)), rows: res.rows, hovertext: rowLabels(ctx, res.rows), hovertemplate: '%{hovertext}<extra></extra>', marker: { size: 5 } }],
        { xaxis: { title: { text: dimLabel(Math.min(a, 3)) }, zeroline: true }, yaxis: { title: { text: K > 1 ? dimLabel(Math.min(b, 3)) : '' }, zeroline: true } }, { width: fitW(480), height: 380, title: 'MCA row plot' }), ctx.code(res.rows_code),
      ctx.note('Each row in principal coordinates (rows with the same levels coincide). Drag over points to select rows.'));
    }
    if (o('details', true)) {
      const ob = ctx.outline('Details', { key: 'details' });
      const tbl = ctx.rt({ columns: [{ key: 'j', label: 'Dimension', fmt: 'int' }, { key: 'sv', label: 'Singular Value', digits: 5 }, { key: 'in', label: 'Inertia', digits: 5 }, { key: 'pct', label: 'Portion', digits: 4 }, { key: 'bar', label: '20 40 60 80', fmt: 'text' }, { key: 'cum', label: 'Cumulative Portion', digits: 4 }],
        rows: res.singular.map((s, j) => ({ j: j + 1, sv: s, in: res.inertia[j], pct: res.percent[j] / 100, cum: res.cum[j] / 100, bar: '' })) }, { sortable: false });
      decorate(tbl, (tr, row) => { const td = tr.cells[4]; td.classList.add('mv-barcell'); cellBar(td, 100 * row.pct, 0, 100, SM.report.BAR); });
      ob.add(tbl, ctx.note('The inertias are the singular values of the Burt table\'s analysis (the principal inertias of the indicator matrix); the singular values are their square roots, as JMP reports them.'), ctx.code(res.code));
    }
    if (o('adjusted', false)) {
      const A = res.adjusted;
      let cb = 0, cg = 0;
      const rows = res.inertia.map((_, j) => { cb += A.benzecri_pct[j]; cg += A.greenacre_pct[j]; return { j: j + 1, adj: A.greenacre[j], bp: A.benzecri_pct[j], bc: cb, gp: A.greenacre_pct[j], gc: cg }; }).filter((r) => r.adj > 0);
      ctx.outline('Adjusted Inertia', { key: 'adjusted' }).add(ctx.rt({ columns: [{ key: 'j', label: 'Dimension', fmt: 'int' }, { key: 'adj', label: 'Adjusted Inertia', digits: 5 }, { key: 'bp', label: 'Benzécri Percent', digits: 4 }, { key: 'bc', label: 'Cumulative', digits: 4 }, { key: 'gp', label: 'Greenacre Percent', digits: 4 }, { key: 'gc', label: 'Cumulative', digits: 4 }], rows }, { sortable: false }),
        ctx.note(`(Q/(Q − 1))² (λ − 1/Q)² for the inertias λ above 1/Q = ${fmt(1 / res.Q, { sig: 4 })}. Benzécri's percentages are of their sum; Greenacre's of Q/(Q − 1)(Σλ² − (J − Q)/Q²) = ${fmt(A.greenacre_total, { sig: 5 })}.`));
    }
    const nd = Math.min(K, 3);
    if (o('coords', false)) ctx.outline('Coordinates', { key: 'coords' }).add(ctx.rt({ columns: [{ key: 'v', label: 'Column', fmt: 'text' }, { key: 'l', label: 'Level', fmt: 'text' }, ...Array.from({ length: nd }, (_, j) => ({ key: `c${j}`, label: `c${j + 1}`, digits: 5 })), { key: 'mass', label: 'Mass', digits: 4 }], rows: res.levels.map((lv) => Object.assign({ v: lv.column, l: lab(lv), mass: lv.mass }, ...Array.from({ length: nd }, (_, j) => ({ [`c${j}`]: lv.coords[j] })))) }));
    if (o('summary', false)) ctx.outline('Summary Statistics', { key: 'summary' }).add(ctx.rt({ columns: [{ key: 'v', label: 'Column', fmt: 'text' }, { key: 'l', label: 'Level', fmt: 'text' }, { key: 'mass', label: 'Mass', digits: 4 }, { key: 'q', label: 'Quality (2 dimensions)', digits: 4 }, { key: 'in', label: 'Relative Inertia', digits: 4 }, ...Array.from({ length: Math.min(K, 2) }, (_, j) => ({ key: `k${j}`, label: `Contribution c${j + 1}`, digits: 4 }))], rows: res.levels.map((lv) => Object.assign({ v: lv.column, l: lab(lv), mass: lv.mass, q: lv.quality, in: lv.inertia }, ...Array.from({ length: Math.min(K, 2) }, (_, j) => ({ [`k${j}`]: lv.contrib[j] })))) }),
      ctx.note('Mass: the level\'s share of the indicator matrix; quality: the share of its squared distance from the origin shown by the first two dimensions; contribution: its share of a dimension\'s inertia.'));
    if (o('cross', false)) {
      const names = res.levels.map((lv) => `${lv.column}: ${lab(lv)}`);
      ctx.outline('Cross Table (Burt)', { key: 'cross' }).add(matrixTable(ctx, names, res.burt, { digits: 0 }), ctx.note('Counts of the pairs of levels over all pairs of columns; the diagonal blocks hold each column\'s level counts.'));
    }
  }

  SM.platforms.register({
    id: 'mca', label: 'Multiple Correspondence Analysis', menu: 'Analyze/Multivariate Methods', order: 35, info: 'p:mca',
    about: 'Multiple correspondence analysis of two or more categorical columns: the singular value decomposition of the indicator matrix, inertias with Benzécri\'s and Greenacre\'s adjustments, the levels (and optionally the rows) in principal coordinates, masses, qualities and contributions, the Burt table.',
    uses: ['numpy.linalg.svd'],
    topics: {
      'p:mca': {
        kicker: 'Analyze > Multivariate Methods', title: 'Multiple Correspondence Analysis',
        lead: 'Maps the levels of several categorical columns so that levels chosen by the same rows lie close together: correspondence analysis of the indicator (dummy) matrix, equivalently of the Burt table of all two-way tables.',
        sections: [
          { heading: 'Reading it', text: 'Each dimension takes a share (Portion) of the total inertia (J − Q)/Q. The raw portions understate the fit of multiple correspondence analysis; Show Adjusted Inertia gives Benzécri\'s and Greenacre\'s corrections.' },
          { heading: 'In the report', choices: [['x, y', 'With three or more dimensions, under the plot: the dimensions on the axes of the plot of the levels and of the row plot.']] },
          { heading: 'Differences from JMP', text: 'Supplementary variables and IDs, the X, Factor role (simple correspondence analysis) and Cochran\'s Q are not here. The signs of the dimensions are arbitrary.' },
        ],
        more: { label: 'Multiple Correspondence Analysis', id: 'help-p-mca' },
      },
    },
    launch: {
      lead: 'Choose two or more nominal or ordinal columns.',
      roles: [
        { key: 'y', label: 'Y, Response', min: 2, types: ['nominal', 'ordinal'], hint: 'required: two or more categorical',
          help: 'The columns whose levels are mapped together; levels chosen by the same rows lie close. Rows with a missing value in any of them are left out.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'A count per row: the row stands for that many identical rows (a table of counts). Rows with a missing, zero or negative count are left out.' },
        { key: 'by', label: 'By', hint: 'optional', help: BY_HELP },
      ],
    },
    title: () => 'Multiple Correspondence Analysis',
    triangle(ctx) {
      return [
        ctx.check('Show Plot', 'plot', null, true), ctx.check('Show Row Plot', 'rowplot', null, false), ctx.check('Show Detail', 'details', null, true), ctx.check('Show Adjusted Inertia', 'adjusted', null, false),
        ctx.check('Show Coordinates', 'coords', null, false), ctx.check('Show Summary Statistics', 'summary', null, false), ctx.check('Cross Table', 'cross', null, false),
        { separator: true },
        { label: 'Save Row Coordinates', action: async () => { const r = await mcall(ctx, 'mca.fit', { columns: ctx.names('y'), freq: ctx.name('freq') }); if (r.error) { SM.ui.toast(r.error, { error: true }); return; } for (let j = 0; j < Math.min(2, r.K); j++) ctx.saveColumn(`MCA c${j + 1}`, { rows: r.rows, values: r.row_coords.map((x) => x[j]) }, { notes: `row coordinate ${j + 1} of the multiple correspondence analysis` }); } },
      ];
    },
    render: mcaRender,
  });

  /* ======================================================================
     MULTIDIMENSIONAL SCALING
     ====================================================================== */
  async function mdsRender(ctx) {
    const o = (k, d) => ctx.opt(k, d);
    const names = ctx.names('y');
    const matrix = o('format', 'attributes') === 'matrix';
    const res = await mcall(ctx, 'mds.fit', { columns: names, standardize: o('standardize', true), matrix, label: labelName(ctx) });
    const box = ctx.container;
    if (res.error) { box.append(ctx.warn(res.error)); return; }
    box.append(ctx.note(`${res.n} objects; classical (Torgerson) scaling of ${matrix ? 'the distance matrix in the columns' : `the Euclidean distances between the rows over ${names.length} column${names.length > 1 ? 's' : ''}${o('standardize', true) ? ', standardized' : ''}`}.`));
    const lab = leafNames(ctx, res.rows);
    const tc = SM.util.themeColors();
    const X = res.coords;
    const two = res.k >= 2;
    ctx.outline('Multidimensional Scaling Plot', { key: 'plot', info: 'p:mds' }).add(ctx.plot([{ type: 'scatter', mode: res.n <= 60 ? 'markers+text' : 'markers', x: X.map((r) => r[0]), y: X.map((r) => (two ? r[1] : 0)), rows: res.rows, text: res.n <= 60 ? lab : undefined, textposition: 'top center', textfont: { size: 9.5, color: tc.text }, hovertext: lab, hovertemplate: '%{hovertext}<br>(%{x:.3f}, %{y:.3f})<extra></extra>', marker: { size: 6 } }],
      { xaxis: { title: { text: 'Dimension 1' }, zeroline: true }, yaxis: { title: { text: two ? 'Dimension 2' : '' }, zeroline: true, scaleanchor: 'x' } }, { width: fitW(520), height: 440, title: 'Multidimensional Scaling Plot' }), ctx.code(res.plot_code),
    ctx.note('Objects close together in the map are close in the data. Drag over points to select rows.'));
    if (o('shepard', true)) {
      const S = res.shepard;
      const mx = Math.max(...S.d, ...S.dhat);
      ctx.outline('Shepard Diagram', { key: 'shepard' }).add(ctx.plot([
        { type: scatterType(S.d.length, 3000), mode: 'markers', x: S.d, y: S.dhat, marker: { size: 3, color: SM.report.BASE, opacity: 0.6 }, hoverinfo: 'skip' },
        { type: 'scatter', mode: 'lines', x: [0, mx], y: [0, mx], line: { color: RED, width: 1 }, hoverinfo: 'skip' },
      ], { xaxis: { title: { text: 'Distance' }, rangemode: 'tozero' }, yaxis: { title: { text: 'Map Distance' }, rangemode: 'tozero' } }, { width: fitW(380), height: 320, title: 'Shepard Diagram', select: false }), ctx.code(res.shepard_code),
      ctx.note(`The distances in the data against those in the two-dimensional map${res.n_pairs > S.d.length ? ` (a sample of ${S.d.length} of the ${res.n_pairs} pairs)` : ''}; on the line the map is exact.`));
    }
    if (o('fit', true)) ctx.outline('Fit Details', { key: 'fit' }).add(ctx.kv([['Stress (Kruskal, 2 dimensions)', res.stress], ['RSquare of the distances', res.r2], ['Objects', res.n, 'int'], ['Negative eigenvalues (share)', res.negative]]),
      ctx.note('Stress = √(Σ(d − d̂)²/Σd²) over the pairs; below 0.05 excellent, 0.1 good, 0.2 poor (Kruskal). Negative eigenvalues mean the distances are not Euclidean.'), ctx.code(res.code));
    if (o('eigen', false)) ctx.outline('Eigenvalues', { key: 'eigen' }).add(eigenTable(ctx, { values: res.eigenvalues, percent: res.percent, cum: res.percent.map((_, j) => res.percent.slice(0, j + 1).reduce((s, v) => s + v, 0)) }));
  }

  SM.platforms.register({
    id: 'mds', label: 'Multidimensional Scaling', menu: 'Analyze/Multivariate Methods', order: 50, info: 'p:mds',
    about: 'Classical (Torgerson) multidimensional scaling: a map of the objects from the Euclidean distances between the rows, or from a distance matrix in the columns; the Shepard diagram, Kruskal\'s stress, the eigenvalues, saved coordinates.',
    uses: ['numpy.linalg.eigh', 'scipy.spatial.distance.pdist'],
    topics: {
      'p:mds': {
        kicker: 'Analyze > Multivariate Methods', title: 'Multidimensional Scaling',
        lead: 'Places the objects in a plane so that their distances there are as close as possible to their distances in the data: the eigenvectors of the doubly centred squared distances (classical scaling).',
        sections: [
          { heading: 'Data Format', choices: [['Attribute List', 'Rows are the objects, the columns their attributes: Euclidean distances, of the standardized columns by default.'], ['Distance Matrix', 'The columns hold the distances between the rows\' objects (as many columns as rows); the matrix is made symmetric.']] },
          { heading: 'Differences from JMP', text: 'JMP fits metric and nonmetric scaling by minimizing stress iteratively, with transformations and Waern links; here the scaling is classical, which is exact for Euclidean distances and a good start otherwise. On standardized attributes it equals principal components.' },
        ],
        more: { label: 'Multidimensional Scaling', id: 'help-p-mds' },
      },
    },
    launch: {
      lead: 'Choose the attribute columns of the objects (the rows), or the columns of a distance matrix.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 1, numeric: true, types: ['continuous', 'ordinal'], hint: 'required: numeric',
          help: 'The attributes of the objects, one row per object; or, with Data Format Distance Matrix, the columns of a square matrix of distances, as many columns as rows. Attributes: rows with a missing value are left out.' },
        { key: 'label', label: 'Label', max: 1, hint: 'optional',
          help: 'A column whose values name the objects on the map (up to 60 objects) and in its hover text; without it the table\'s label column, else the row number.' },
        { key: 'by', label: 'By', hint: 'optional', help: BY_HELP },
      ],
      options: [
        { key: 'format', label: 'Data Format', type: 'select', value: 'attributes', choices: [['attributes', 'Attribute List'], ['matrix', 'Distance Matrix']],
          help: 'Attribute List, the default: the rows are the objects and the columns their attributes, and the distances are Euclidean. Distance Matrix: the columns hold the distances between the rows\' objects; the matrix is made symmetric, a missing entry taken from the other side of the diagonal.' },
        { key: 'standardize', label: 'Standardize the columns', type: 'check', value: true,
          help: 'Attribute List only: scale each column to mean 0 and standard deviation 1 before the distances (on by default), so that no attribute dominates by its units. A distance matrix is used as it is.' },
      ],
    },
    title: () => 'Multidimensional Scaling',
    triangle(ctx) {
      return [
        ctx.check('Shepard Diagram', 'shepard', null, true), ctx.check('Fit Details', 'fit', null, true), ctx.check('Eigenvalues', 'eigen', null, false),
        { separator: true },
        { label: 'Save Coordinates', action: async () => { const r = await mcall(ctx, 'mds.fit', { columns: ctx.names('y'), standardize: ctx.opt('standardize', true), matrix: ctx.opt('format', 'attributes') === 'matrix', label: labelName(ctx) }); if (r.error) { SM.ui.toast(r.error, { error: true }); return; } for (let j = 0; j < Math.min(2, r.k); j++) ctx.saveColumn(`MDS Dimension ${j + 1}`, { rows: r.rows, values: r.coords.map((x) => x[j]) }, { notes: `classical multidimensional scaling, dimension ${j + 1}` }); } },
      ];
    },
    render: mdsRender,
  });

}(typeof self !== 'undefined' ? self : this));
