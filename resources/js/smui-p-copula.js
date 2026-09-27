/* ==========================================================================
   SMUI.HTML: ANALYZE > MULTIVARIATE METHODS > COPULAS

   The dependence of two or more continuous columns with each column's own
   distribution taken away: the columns' ranks over n + 1 (pseudo-
   observations) and the copula families of statsmodels.distributions.
   copula fitted to them. JMP has no copula platform; the report is laid out
   as JMP lays out its fits:

     Pseudo-Observations   the ranks/(n + 1) of a pair (linked to the rows)
                           with the fitted copula's density contours, and the
                           data themselves with the joint model's contours
                           when the margins are fitted; a scatterplot matrix
                           for more than two columns
     Dependence            Kendall's τ and Spearman's ρ with their tests, and
                           the τ, ρ and tail dependence each fit implies; the
                           tail concentration function on request
     Copula Comparison     each family's parameters with standard errors, log
                           likelihood, AIC and BIC, best first; a click shows
                           that copula; a parametric-bootstrap goodness of fit
                           on request
     Margins               a distribution for each column, best by AICc, or
                           the empirical one
     Joint Probabilities   P(X ≤ x, Y ≤ y), P(Y > y | X > x) and the rest at
                           a point, from the copula with the margins
     Simulate              draws from the joint model as a new table

   The numbers are resources/py/smui/copula.py's (statsmodels, scipy).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const MORE = { label: 'Copulas', id: 'help-p-copula' };

  const FAMILY_ITEMS = [['gaussian', 'Gaussian'], ['t', 'Student t'], ['clayton', 'Clayton'], ['frank', 'Frank'], ['gumbel', 'Gumbel'], ['indep', 'Independence']];
  const DEFAULT_FAMILIES = ['indep', 'gaussian', 't', 'clayton', 'frank', 'gumbel'];
  const MULTI = ['indep', 'gaussian', 't'];
  const METHODS = [['mpl', 'Maximum Pseudo-Likelihood'], ['itau', 'Inversion of Kendall\'s τ']];
  const METHOD = Object.fromEntries(METHODS);
  const ROTATIONS = [['auto', 'By the Sign of τ'], ['all', 'All Rotations'], ['none', 'None']];
  const SE_KINDS = [['hessian', 'Hessian of the Pseudo-Likelihood'], ['rank', 'Rank-Corrected (Genest, Ghoudi and Rivest)']];
  const MARGIN_ITEMS = [['auto', 'Best by AICc'], ['normal', 'Normal'], ['lognormal', 'Lognormal'], ['gamma', 'Gamma'], ['weibull', 'Weibull'], ['exponential', 'Exponential'],
    ['logistic', 'Logistic'], ['t', 'Student\'s t'], ['beta', 'Beta'], ['empirical', 'Empirical']];
  const MARGIN_LABEL = Object.fromEntries(MARGIN_ITEMS);
  const HDR_WIDTH = [2.2, 1.7, 1.25, 1];

  /* Overlay colours, checked against kvot.css's surfaces and against the
     page's point colour (SM.report.BASE) and selection colour: contour lines,
     and simulated points (which also get their own marker). */
  function colors() {
    const c = SM.util.themeColors();
    return { ...c, contour: c.dark ? '#9085e9' : '#b0413e', sim: c.dark ? '#199e70' : '#1baf7a', point: SM.report.BASE };
  }

  const nice = (x) => fmt(x, { sig: 4 });
  const pctText = (p) => `${Math.round(100 * p)}%`;
  const fitsOk = (res) => (res.fits || []).filter((f) => !f.error);
  const lvText = (alpha) => `${fmt(100 * (1 - alpha))}%`;

  /* The index of the pair (i, j), i < j, in the upper triangle row by row. */
  function pairIndex(i, j, k) {
    let q = 0;
    for (let a = 0; a < k; a++) for (let b = a + 1; b < k; b++) { if (a === i && b === j) return q; q++; }
    return -1;
  }

  /* A fit's parameters for the pair (i, j): its bivariate margin. */
  function pairParams(f, i, j, k) {
    if (!f) return [];
    if (!['gaussian', 't'].includes(f.family) || k === 2) return f.values;
    const q = pairIndex(i, j, k);
    return f.family === 't' ? [f.values[q], f.values[f.values.length - 1]] : [f.values[q]];
  }

  function paramText(f, k) {
    const v = f.values || [];
    if (f.family === 'indep') return '(none)';
    if (f.family === 'gaussian') return k === 2 ? `ρ = ${nice(v[0])}` : `${v.length} correlations`;
    if (f.family === 't') return k === 2 ? `ρ = ${nice(v[0])}, ν = ${nice(v[1])}` : `${v.length - 1} correlations, ν = ${nice(v[v.length - 1])}`;
    return `θ = ${nice(v[0])}`;
  }

  /* The pair shown in the single-pair graphs (with more than two columns). */
  function pairOf(ctx, k) {
    let p = ctx.opt('pair', null);
    if (!Array.isArray(p) || p.length !== 2 || p[0] === p[1] || p.some((x) => !(Number.isInteger(x) && x >= 0 && x < k))) p = [0, 1];
    return p[0] < p[1] ? p.slice() : [p[1], p[0]];
  }

  function shownFit(ctx, res) {
    const ok = fitsOk(res);
    const want = ctx.opt('shown', null);
    return ok.find((f) => f.family === want) || ok.find((f) => f.family === res.best) || ok[0] || null;
  }

  /* The fit payload: every option that changes the numbers. */
  const fitArgs = (ctx, names) => ({
    columns: names, families: ctx.opt('families', DEFAULT_FAMILIES), method: ctx.opt('method', 'mpl'),
    rotations: ctx.opt('rotations', 'auto'), se: ctx.opt('se', 'hessian'), alpha: ctx.alpha,
  });

  /* The margins' choice for every column: Best by AICc unless one is set. */
  function marginChoice(ctx, cols) {
    const out = {};
    for (const c of cols) { const v = ctx.opt('marginFamily', 'auto', c.id); if (v && v !== 'auto') out[c.name] = v; }
    return out;
  }
  const marginSpecs = (m) => m.columns.map((c) => ({ dist: c.chosen.dist, values: c.chosen.values }));

  /* Contour lines of a density grid, one trace per level. Highest-density
     levels (normal scores, the data scale): the 50% region thickest, 90% and
     95% dotted. Density levels (the unit square): above 1 solid, thicker as
     the density grows, below 1 dotted, each labelled with its density. */
  function contourTraces(d, color, axes = {}, { labels = true } = {}) {
    if (!d || !d.levels || !d.levels.length) return [];
    return d.levels.map((lv, q) => {
      const dens = lv.kind === 'density';
      const width = dens ? (lv.level > 1 ? 1 + 0.4 * Math.log2(lv.level) : 1) : (HDR_WIDTH[q] ?? 1);
      return {
        type: 'contour', x: d.x, y: d.y, z: d.z, autocontour: false,
        contours: { start: lv.level, end: lv.level * (1 + 1e-9) + 1e-300, size: Math.abs(lv.level) + 1, coloring: 'none', showlabels: dens && labels, labelfont: { size: 9.5, color }, labelformat: '.3~g' },
        line: { color, width, dash: dens ? (lv.level < 1 ? 'dot' : 'solid') : (q < 2 ? 'solid' : 'dot'), smoothing: 0.85 },
        showscale: false, hoverinfo: 'skip', showlegend: false, name: dens ? `density ${densText(lv.level)}` : `${pctText(lv.p)} region`, ...axes,
      };
    });
  }
  const densText = (c) => (c >= 1 ? String(c) : `1/${Math.round(1 / c)}`);
  /* What the contours of a density grid are, in words. */
  function contourNote(d, label) {
    if (!d || !d.levels || !d.levels.length) return '';
    if (d.levels[0].kind !== 'density') return hdrNote(label);
    const up = d.levels.filter((lv) => lv.level > 1).map((lv) => densText(lv.level)), down = d.levels.filter((lv) => lv.level < 1).map((lv) => densText(lv.level));
    return `The contours are the ${label}'s density${up.length ? ` at ${up.join(', ')} (solid: pairs of values that many times as likely as under independence)` : ''}${down.length ? `${up.length ? ' and' : ''} at ${down.join(', ')} (dotted: less likely)` : ''}.`;
  }

  const scatterType = (n) => (n > 4000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter');
  const markerSize = (n) => (n > 2000 ? 3 : n > 600 ? 4 : 5.5);
  const hdrNote = (label) => `The contours enclose 50% (thickest), 75%, 90% and 95% (dotted) of the ${label}'s probability: its highest-density regions.`;

  function colValues(col, rows) { return rows.map((r) => col.values[r]); }

  /* A report table in its own sideways scroller: on a phone a wide table
     scrolls by itself instead of widening the whole report. (Graphs go into
     ctx.row() for the same reason: a graph sizes itself to its parent's
     clientWidth, which in an outline body counts the body's indent.) */
  const wide = (tbl) => el('div', { class: 'sm-cop-scroll' }, tbl);

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx) {
    const cols = ctx.roles('y');
    const names = cols.map((c) => c.name);
    const o = (key, d) => ctx.opt(key, d);
    const res = await ctx.call('copula.fit', fitArgs(ctx, names));
    const box = ctx.container;
    if (res.error) { box.append(ctx.warn(res.error)); return; }
    const k = res.k;
    const S = { res, cols, names, k, pair: pairOf(ctx, k), fit: shownFit(ctx, res), margins: null, specs: null };
    const tieText = res.ties.map((t, c) => (t ? `${names[c]} has ${t} tied value${t === 1 ? '' : 's'}` : null)).filter(Boolean);
    box.append(ctx.note(`${fmt(res.n)} rows with a value in every column${res.n_missing ? ` (${res.n_missing} left out for a missing value)` : ''}; ${METHOD[res.method].toLowerCase()}${res.method === 'mpl' ? ' on the pseudo-observations' : ''}.${tieText.length ? ` ${tieText.join('; ')}: ties get their average rank.` : ''}${res.n < 30 ? ' With so few rows the families are hard to tell apart.' : ''}`));
    if (k > 2) box.append(ctx.note('With more than two columns the Gaussian and Student t copulas (a correlation matrix, and ν) and the independence copula are fitted; Clayton, Frank and Gumbel are fitted to two columns.'));
    const needMargins = o('margins', false) || o('calc', false) || !!o('simCompare', null);
    if (needMargins) {
      S.margins = await ctx.call('copula.margins', { columns: names, choice: marginChoice(ctx, cols), alpha: ctx.alpha });
      if (S.margins && !S.margins.error) S.specs = marginSpecs(S.margins);
    }
    if (o('pseudo', true)) await pseudoOutline(ctx, S);
    if (o('dependence', true)) await dependenceOutline(ctx, S);
    if (o('comparison', true)) comparisonOutline(ctx, S);
    if (o('gof', null)) await gofOutline(ctx, S);
    if (o('margins', false) && S.margins) marginsOutline(ctx, S);
    if (o('calc', false) && S.specs) await calcOutline(ctx, S);
    if (o('simCompare', null) && S.fit) await simOutline(ctx, S);
  }

  /* ======================================================================
     PSEUDO-OBSERVATIONS
     ====================================================================== */
  async function pseudoOutline(ctx, S) {
    const { res, names, k } = S;
    const o = (key, d) => ctx.opt(key, d);
    const scale = o('scale', 'uniform');
    const [i, j] = S.pair;
    const f = S.fit;
    const col = colors();
    const ob = ctx.outline('Pseudo-Observations', { key: 'pseudo', info: 'p:copula:pseudo', menu: () => pseudoMenu(ctx, S) });
    if (k > 2 && o('splom', true)) await splom(ctx, S, ob, scale);
    const u = res.u;
    const tx = (v) => (scale === 'normal' ? v.map((x) => SM.util.qnorm(x)) : v);
    const fp = f ? pairParams(f, i, j, k) : [];
    const dens = f && f.family !== 'indep' && o('contours', true) ? await ctx.call('copula.density', { family: f.family, params: fp, scale }) : null;
    const suffix = scale === 'normal' ? 'normal score' : 'rank/(n + 1)';
    const range = scale === 'normal' ? [-3.3, 3.3] : [0, 1];
    const n = res.n;
    const traces = [{ type: scatterType(n), mode: 'markers', x: tx(u[i]), y: tx(u[j]), rows: res.rows, marker: { size: markerSize(n) }, name: 'Pseudo-observations' }, ...contourTraces(dens, col.contour)];
    const ax = (name) => ({ title: { text: `${name}: ${suffix}` }, range, zeroline: false });
    const plots = [ctx.plot(traces, { xaxis: ax(names[i]), yaxis: ax(names[j]), margin: { l: 58, r: 10, t: 8, b: 46 } },
      { width: 380, height: 372, title: `Pseudo-observations of ${names[i]} and ${names[j]}` })];
    // the data themselves, with the joint model's contours
    if (S.specs && o('joint', true)) {
      const specs = [S.specs[i], S.specs[j]];
      const jd = f && o('contours', true) ? await ctx.call('copula.joint', { columns: names, family: f.family, params: fp, margins: specs, pair: [i, j] }) : null;
      const xs = colValues(S.cols[i], res.rows), ys = colValues(S.cols[j], res.rows);
      plots.push(ctx.plot([{ type: scatterType(n), mode: 'markers', x: xs, y: ys, rows: res.rows, marker: { size: markerSize(n) }, name: 'Data' }, ...contourTraces(jd, col.contour)],
        { xaxis: { title: { text: names[i] }, zeroline: false }, yaxis: { title: { text: names[j] }, zeroline: false }, margin: { l: 58, r: 10, t: 8, b: 46 } },
        { width: 380, height: 372, title: `${names[i]} and ${names[j]} with the joint model` }));
    }
    ob.add(ctx.row(...plots));
    const parts = [];
    if (!f) parts.push('No copula was fitted.');
    else if (f.family === 'indep') parts.push('The independence copula has the smallest AIC (or is chosen): its density is 1 everywhere, so it has no contours.');
    else if (dens) parts.push(`${contourNote(dens, `fitted ${f.label} copula`)}${k > 2 ? ` For this pair: the bivariate margin of the ${k}-column fit.` : ''}`);
    parts.push(scale === 'normal' ? 'Normal scores are Φ⁻¹ of the pseudo-observations: a Gaussian copula looks like elliptical contours on this scale, tail dependence like corners drawn out along the diagonal.'
      : 'Each point is a row: its rank in each column over n + 1. Drag over points to select rows.');
    if (S.specs && o('joint', true)) parts.push(`On the right the data with the joint distribution's regions holding 50, 75, 90 and 95% of it: the copula with the margins ${S.margins.columns.filter((_, c) => c === i || c === j).map((c) => `${c.column}: ${c.chosen.label}`).join(', ')} (Margins).`);
    ob.add(ctx.note(parts.join(' ')));
    if (!S.specs && f && f.family !== 'indep') ob.add(ctx.note('Margins (red triangle of Copulas) adds the data with the joint model\'s contours.'));
  }

  /* A lower-triangular scatterplot matrix of the pseudo-observations, each
     cell with the contours of that pair's margin of the fitted copula. */
  async function splom(ctx, S, ob, scale) {
    const { res, names, k } = S;
    const f = S.fit;
    const col = colors();
    const g = k - 1;
    const room = (ctx.report && ctx.report.body && ctx.report.body.clientWidth) || 800;
    const size = Math.max(70, Math.min(170, Math.floor((Math.min(room - 90, 860) - 70) / g)));
    const W = size * g + 70, H = size * g + 56;
    const gap = 0.015;
    const tx = (v) => (scale === 'normal' ? v.map((x) => SM.util.qnorm(x)) : v);
    const range = scale === 'normal' ? [-3.3, 3.3] : [0, 1];
    const traces = [];
    const layout = { margin: { l: 58, r: 8, t: 6, b: 50 }, dragmode: 'select' };
    let a = 0;
    for (let r = 1; r < k; r++) {
      for (let c = 0; c < r; c++) {
        a++;
        const xa = a === 1 ? 'x' : `x${a}`, ya = a === 1 ? 'y' : `y${a}`;
        const gi = r - 1, gj = c;
        const bottom = gi === g - 1, left = gj === 0;
        layout[`xaxis${a === 1 ? '' : a}`] = { domain: [gj / g + gap, (gj + 1) / g - gap], anchor: ya, range, showticklabels: bottom, showgrid: false, zeroline: false, ticks: bottom ? 'outside' : '', title: bottom ? { text: names[c], standoff: 4, font: { size: 10.5 } } : undefined, tickfont: { size: 9 }, nticks: 3, mirror: true };
        layout[`yaxis${a === 1 ? '' : a}`] = { domain: [1 - (gi + 1) / g + gap, 1 - gi / g - gap], anchor: xa, range, showticklabels: left, showgrid: false, zeroline: false, ticks: left ? 'outside' : '', title: left ? { text: names[r], standoff: 4, font: { size: 10.5 } } : undefined, tickfont: { size: 9 }, nticks: 3, mirror: true };
        traces.push({ type: scatterType(res.n * (k * (k - 1)) / 2), mode: 'markers', x: tx(res.u[c]), y: tx(res.u[r]), rows: res.rows, marker: { size: res.n > 500 ? 2.5 : 3.5 }, xaxis: xa, yaxis: ya, name: `${names[r]} by ${names[c]}` });
        if (f && f.family !== 'indep' && ctx.opt('contours', true)) {
          const d = await ctx.call('copula.density', { family: f.family, params: pairParams(f, c, r, k), scale, m: 40 });
          traces.push(...contourTraces(d, col.contour, { xaxis: xa, yaxis: ya }, { labels: false }).map((t) => ({ ...t, line: { ...t.line, width: Math.max(0.8, t.line.width * 0.7) } })));
        }
      }
    }
    const sub = ctx.outline('Scatterplot Matrix', { parent: ob, key: 'splom' });
    sub.add(ctx.row(ctx.plot(traces, layout, { width: W, height: H, title: 'Scatterplot matrix of the pseudo-observations' })),
      ctx.note(`Every pair of the ${k} columns${f && f.family !== 'indep' ? `, with the contours of the fitted ${f.label} copula's margin for the pair (the same levels as below, unlabelled)` : ''}. Pair (red triangle) picks the pair drawn below and used by the other outlines.`));
  }

  function pseudoMenu(ctx, S) {
    const o = (key, d) => ctx.opt(key, d);
    const ok = fitsOk(S.res);
    const items = [
      { label: 'Scale', submenu: () => [['uniform', 'Uniform (u, v)'], ['normal', 'Normal Scores']].map(([v, l]) => ({ label: l, checked: o('scale', 'uniform') === v, action: () => ctx.set('scale', v) })) },
      ctx.check('Density Contours', 'contours', null, true),
      { label: 'Contours Of', submenu: () => ok.map((f) => ({ label: f.label, checked: S.fit && S.fit.family === f.family, action: () => ctx.set('shown', f.family) })) },
      { label: 'Data with the Joint Model', checked: !!(o('joint', true) && S.specs), action: () => { if (S.specs && o('joint', true)) ctx.set('joint', false); else { ctx.set('joint', true, null, { rerun: false }); ctx.set('margins', true); } } },
    ];
    if (S.k > 2) {
      items.push(ctx.check('Scatterplot Matrix', 'splom', null, true));
      items.push({ label: 'Pair', submenu: () => pairItems(ctx, S) });
    }
    return items;
  }

  function pairItems(ctx, S) {
    const out = [];
    for (let a = 0; a < S.k; a++) for (let b = a + 1; b < S.k; b++) out.push({ label: `${S.names[a]} and ${S.names[b]}`, checked: S.pair[0] === a && S.pair[1] === b, action: () => ctx.set('pair', [a, b]) });
    return out;
  }

  /* ======================================================================
     DEPENDENCE
     ====================================================================== */
  async function dependenceOutline(ctx, S) {
    const { res, names, k } = S;
    const ob = ctx.outline('Dependence', { key: 'dependence', info: 'p:copula:dependence', menu: () => [
      ctx.check('Tail Concentration Function', 'tails', null, false),
      ...(k > 2 ? [{ label: 'Pair', submenu: () => pairItems(ctx, S) }] : []),
    ] });
    ob.add(wide(ctx.rt({
      caption: 'Rank Correlations',
      columns: [{ key: 'var', label: 'Variable', fmt: 'text' }, { key: 'by', label: 'by Variable', fmt: 'text' }, { key: 'tau', label: 'Kendall τb', digits: 4 }, { key: 'tau_se', label: 'Std Err τ', digits: 4, hidden: true },
        { key: 'tau_p', label: 'Prob>|τb|', fmt: 'p' }, { key: 'rho', label: 'Spearman ρ', digits: 4 }, { key: 'rho_p', label: 'Prob>|ρ|', fmt: 'p' }, { key: 'n', label: 'N', fmt: 'int' }],
      rows: res.dependence,
    }, { key: 'rank' })));
    const pairLabel = (m) => `${names[m.i]} and ${names[m.j]}`;
    const rows = [];
    for (const d of res.dependence) rows.push({ copula: 'Data', pair: `${d.by} and ${d.var}`, tau: d.tau, rho_s: d.rho, lambda_l: null, lambda_u: null, lambda_ul: null, lambda_lr: null, _data: true });
    for (const f of fitsOk(res)) for (const m of f.measures) rows.push({ copula: f.label, family: f.family, pair: pairLabel(m), ...m });
    const cols = [{ key: 'copula', label: 'Copula', fmt: 'text' }];
    if (k > 2) cols.push({ key: 'pair', label: 'Pair', fmt: 'text' });
    // with negative dependence the tails are in the other two corners: shown then
    const corners = res.dependence.some((d) => d.tau < 0);
    cols.push({ key: 'tau', label: 'Kendall τ', digits: 4 }, { key: 'rho_s', label: 'Spearman ρ', digits: 4 }, { key: 'lambda_l', label: 'Lower Tail λL', digits: 4 }, { key: 'lambda_u', label: 'Upper Tail λU', digits: 4 },
      { key: 'lambda_ul', label: 'λ Upper Left', digits: 4, hidden: !corners }, { key: 'lambda_lr', label: 'λ Lower Right', digits: 4, hidden: !corners });
    ob.add(wide(ctx.rt({ caption: 'Implied by the Fitted Copulas', columns: cols, rows }, { key: 'implied', cellClass: (r) => (r._data ? 'sm-cop-datarow' : S.fit && r.family === S.fit.family ? 'sm-cop-shown' : '') })),
      ctx.note(`The first line is the data's. Kendall\'s τ and Spearman\'s ρ are the rank correlations each fitted copula implies; the tail dependence λL = lim P(V ≤ q | U ≤ q) and λU = lim P(V > q | U > q) as q → 0 or 1 say how often both columns are extreme together (0: in the limit never more than by chance). The Gaussian and Frank copulas have none; Clayton has lower, Gumbel upper, the t copula both (and in the other two corners). Rotated copulas carry their tails into the corners: λ upper left is the limit of P(V > 1 − q | U ≤ q) as q → 0, λ lower right that of P(V ≤ q | U > 1 − q)${corners ? '' : ' (right click, Columns, shows them)'}.`),
      ctx.note('τb and ρ are scipy\'s kendalltau and spearmanr (p from the normal and t approximations). The t copula\'s tail dependence and Spearman\'s ρ are computed here (statsmodels 0.14.6 gets both wrong: see Help); ρ of Clayton and Gumbel, which have no closed form, is 12 ∫∫C − 3 by quadrature.'),
      ctx.code(res.code));
    if (ctx.opt('tails', false) && fitsOk(res).some((f) => f.family !== 'indep')) await tailsOutline(ctx, S, ob);
  }

  /* The tail concentration function, one small panel per fitted copula
     (each with the data's), so that each copula's tails meet the data's
     without a legend of many colours. */
  async function tailsOutline(ctx, S, parent) {
    const { res, names, k } = S;
    const [i, j] = S.pair;
    const fits = fitsOk(res).filter((f) => f.family !== 'indep');
    const r = await ctx.call('copula.tails', { columns: names, pair: [i, j], fits: fits.map((f) => ({ family: f.family, params: pairParams(f, i, j, k) })) });
    const col = colors();
    const ob = ctx.outline('Tail Concentration Function', { parent, key: 'tails', info: 'p:copula:tails', menu: () => [{ label: 'Remove', action: () => ctx.set('tails', false) }] });
    const per = Math.min(4, fits.length);
    const rowsN = Math.ceil(fits.length / per);
    const cellW = 190, cellH = 150;
    const W = Math.min(cellW * per + 70, 840), H = cellH * rowsN + 60;
    const traces = [], layout = { margin: { l: 50, r: 8, t: 22, b: 44 }, annotations: [], showlegend: false };
    const gx = 0.03, gy = 0.07;
    fits.forEach((f, q) => {
      const a = q + 1, xa = a === 1 ? 'x' : `x${a}`, ya = a === 1 ? 'y' : `y${a}`;
      const cr = Math.floor(q / per), cc = q % per;
      const bottom = cr === rowsN - 1 || q + per >= fits.length, left = cc === 0;
      layout[`xaxis${a === 1 ? '' : a}`] = { domain: [cc / per + gx, (cc + 1) / per - gx], anchor: ya, range: [0, 1], showticklabels: bottom, ticks: bottom ? 'outside' : '', title: bottom ? { text: 'q', standoff: 2, font: { size: 10 } } : undefined, tickfont: { size: 9 }, nticks: 3, zeroline: false, mirror: true, showgrid: false };
      layout[`yaxis${a === 1 ? '' : a}`] = { domain: [1 - (cr + 1) / rowsN + gy, 1 - cr / rowsN - gy], anchor: xa, range: [0, 1.02], showticklabels: left, ticks: left ? 'outside' : '', tickfont: { size: 9 }, nticks: 3, zeroline: false, mirror: true, showgrid: false };
      traces.push({ type: 'scatter', mode: 'markers', x: r.q, y: r.empirical, marker: { size: 3.5, color: col.point }, xaxis: xa, yaxis: ya, hovertemplate: 'q %{x}: data %{y:.3f}<extra></extra>', name: 'Data' });
      const m = r.fits.find((x) => x.family === f.family);
      if (m) traces.push({ type: 'scatter', mode: 'lines', x: r.q, y: m.values, line: { color: col.contour, width: 2 }, xaxis: xa, yaxis: ya, hovertemplate: `q %{x}: ${T(f.label)} %{y:.3f}<extra></extra>`, name: f.label });
      layout.annotations.push({ xref: `${xa} domain`, yref: `${ya} domain`, x: 0.5, y: 1.02, xanchor: 'center', yanchor: 'bottom', text: T(f.label), showarrow: false, font: { size: 10.5, color: col.text } });
    });
    layout.shapes = fits.map((_, q) => { const a = q + 1; return { type: 'line', xref: a === 1 ? 'x' : `x${a}`, yref: `${a === 1 ? 'y' : `y${a}`} domain`, x0: 0.5, x1: 0.5, y0: 0, y1: 1, line: { color: col.muted, width: 0.8, dash: 'dot' } }; });
    ob.add(ctx.row(ctx.plot(traces, layout, { width: W, height: H, title: `Tail concentration of ${names[i]} and ${names[j]}`, select: false })),
      ctx.note(`Dots: the data's share of the rows with both columns at or below their q quantile, over q (q ≤ ½), and with both above it, over 1 − q; lines: C(q, q)/q and (1 − 2q + C(q, q))/(1 − q) for each fitted copula C. At the left end the curve tends to the lower tail dependence λL, at the right end to λU. A copula whose line follows the dots at both ends describes the tails; the dots at the very ends rest on few rows.`),
      ctx.code(`# the data's tail concentration from the pseudo-observations u (see the Copula Comparison code)\nq = np.round(np.arange(0.02, 0.99, 0.01), 2)\nbelow = np.array([np.mean((u[:, 0] <= a) & (u[:, 1] <= a)) for a in q])\nabove = np.array([np.mean((u[:, 0] > a) & (u[:, 1] > a)) for a in q])\nprint(np.where(q <= 0.5, below / q, above / (1 - q)))`));
  }

  /* ======================================================================
     COPULA COMPARISON
     ====================================================================== */
  function comparisonOutline(ctx, S) {
    const { res, k } = S;
    const ok = fitsOk(res);
    const ob = ctx.outline('Copula Comparison', { key: 'comparison', info: 'p:copula:comparison', menu: () => comparisonMenu(ctx, S) });
    const rows = ok.map((f) => ({ family: f.family, copula: f.label, params: paramText(f, k), k: f.k, loglik: f.loglik, m2ll: -2 * f.loglik, aic: f.aic, delta: f.delta, weight: f.weight, bic: f.bic, aicc: f.aicc }));
    ob.add(wide(ctx.rt({
      caption: 'Fits, Best First by AIC',
      columns: [{ key: 'copula', label: 'Copula', fmt: 'text' }, { key: 'params', label: 'Parameters', fmt: 'text' }, { key: 'k', label: 'Number of Parameters', fmt: 'int', hidden: true },
        { key: 'loglik', label: 'LogLikelihood' }, { key: 'm2ll', label: '−2 LogLikelihood', hidden: true }, { key: 'aic', label: 'AIC' }, { key: 'delta', label: 'ΔAIC' }, { key: 'weight', label: 'AIC Weight', digits: 4 },
        { key: 'bic', label: 'BIC' }, { key: 'aicc', label: 'AICc', hidden: true }],
      rows,
    }, { key: 'comparison', onRow: (row) => ctx.set('shown', row.family), cellClass: (r) => (S.fit && r.family === S.fit.family ? 'sm-cop-shown' : '') })));
    const bad = (res.fits || []).filter((f) => f.error);
    if (bad.length) ob.add(ctx.note(`Not fitted: ${bad.map((f) => `${f.label} (${f.error})`).join('; ')}.`));
    if (!ok.length) ob.add(ctx.warn(k > 2 ? 'No copula to fit: with more than two columns only the Gaussian, Student t and independence copulas apply. Tick one of them in Fit (red triangle).' : 'No copula could be fitted (see above). Tick another in Fit (red triangle).'));
    // parameter estimates
    const kind = res.se_kind;
    const lv = lvText(ctx.alpha);
    const prow = [];
    for (const f of ok) for (const p of f.params) prow.push({ copula: f.label, family: f.family, ...p, estimate: p.estimate, se: p.se, lower: p.lower, upper: p.upper, bound: p.bound ? 'at its bound' : '' });
    const pcols = [{ key: 'copula', label: 'Copula', fmt: 'text' }, { key: 'name', label: 'Parameter', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' },
      { key: 'lower', label: `Lower ${lv}` }, { key: 'upper', label: `Upper ${lv}` }];
    if (kind !== 'delta') pcols.push({ key: kind === 'rank' ? 'se_hessian' : 'se_rank', label: kind === 'rank' ? 'Std Error (Hessian)' : 'Std Error (Rank-Corrected)', hidden: true });
    pcols.push({ key: 'bound', label: 'Note', fmt: 'text', hidden: !prow.some((r) => r.bound) });
    ob.add(wide(ctx.rt({ caption: 'Parameter Estimates', columns: pcols, rows: prow }, { key: 'params', sortable: false, cellClass: (r) => (S.fit && r.family === S.fit.family ? 'sm-cop-shown' : '') })));
    for (const f of ok) if (f.note) ob.add(ctx.note(`${f.label}: ${f.note}`));
    const how = res.method === 'itau'
      ? 'Each parameter from Kendall\'s τ (statsmodels\' theta_from_tau and corr_from_tau; for Frank with τ < 0 by the symmetry θ(−τ) = −θ(τ), as statsmodels\' own series fails there), its standard error by the delta method on the U-statistic variance of τ; ν of the t copula by maximum pseudo-likelihood with ρ held at its τ value. The log likelihoods are at those estimates, so AIC compares the families but is not maximised.'
      : `Maximum pseudo-likelihood (Genest, Ghoudi and Rivest 1995): the sum of the log densities of statsmodels\' copulas over the pseudo-observations, maximised with scipy.optimize; standard errors ${kind === 'rank' ? 'rank-corrected (Genest, Ghoudi and Rivest\'s variance, as R copula\'s fitCopula(method = "mpl") gives)' : 'from the numerical Hessian (statsmodels approx_hess)'}.`;
    const caveat = res.method === 'itau' ? 'The standard errors allow for the ranks (τ is a function of them), but not for ties.'
      : kind === 'rank' ? 'The rank correction allows for the margins being estimated by ranks; the Hessian alone does not (right click, Columns, shows it).'
        : 'These treat the pseudo-observations as if they were the true uniforms: they leave out that the margins are estimated (by the ranks), and are too small, in simulations here by 5–30%. Standard Errors ▸ Rank-Corrected (red triangle) allows for it.';
    ob.add(ctx.note(`${how} ${caveat} Intervals are Wald intervals on the scale where the parameter is unbounded (log θ, log(θ − 1), Fisher's z of ρ, log ν). AIC and BIC compare pseudo-likelihoods: the margins are the same for every family, so they cancel. Click a line to show that copula in the graphs.`),
      ctx.code(res.code));
  }

  function comparisonMenu(ctx, S) {
    const o = (key, d) => ctx.opt(key, d);
    const fam = o('families', DEFAULT_FAMILIES);
    const toggle = (key) => {
      const next = fam.includes(key) ? fam.filter((x) => x !== key) : [...fam, key];
      if (!next.length) { SM.ui.toast('Keep at least one copula'); return; }
      ctx.set('families', next);
    };
    return [
      { label: 'Fit', submenu: () => FAMILY_ITEMS.map(([key, l]) => ({ label: l, checked: fam.includes(key), disabled: S.k > 2 && !MULTI.includes(key), action: () => toggle(key) })) },
      { label: 'Rotations of Clayton and Gumbel', submenu: () => ROTATIONS.map(([v, l]) => ({ label: l, checked: o('rotations', 'auto') === v, action: () => ctx.set('rotations', v) })) },
      { label: 'Estimation Method', submenu: () => METHODS.map(([v, l]) => ({ label: l, checked: o('method', 'mpl') === v, action: () => ctx.set('method', v) })) },
      { label: 'Standard Errors', disabled: o('method', 'mpl') === 'itau', submenu: () => SE_KINDS.map(([v, l]) => ({ label: l, checked: o('se', 'hessian') === v, action: () => ctx.set('se', v) })) },
      { label: 'Show Copula', submenu: () => fitsOk(S.res).map((f) => ({ label: f.label, checked: S.fit && S.fit.family === f.family, action: () => ctx.set('shown', f.family) })) },
      { separator: true },
      { label: 'Goodness of Fit…', disabled: S.k !== 2, action: () => gofDialog(ctx) },
    ];
  }

  /* ======================================================================
     GOODNESS OF FIT
     ====================================================================== */
  async function gofDialog(ctx) {
    const cur = ctx.opt('gof', null) || {};
    const v = await SM.ui.form({
      title: 'Goodness of Fit', info: 'p:copula:gof',
      lead: 'The Cramér–von Mises distance of each fitted copula from the empirical copula, with a parametric bootstrap p-value: each bootstrap sample is drawn from the fitted copula and fitted again. It takes a while: seconds per hundred samples for most families, longer for the t copula.',
      fields: [{ key: 'B', label: 'Bootstrap samples', type: 'number', value: cur.B ?? 100 }, { key: 'seed', label: 'Random seed', type: 'number', value: cur.seed ?? 1 }],
      validate: (x) => (x.B >= 10 && x.B <= 5000 && Number.isInteger(x.B) ? (Number.isInteger(x.seed) && x.seed >= 0 ? null : 'The seed is a whole number, 0 or more') : 'Between 10 and 5000 bootstrap samples'),
    });
    if (v) ctx.set('gof', { B: v.B, seed: v.seed });
  }

  async function gofOutline(ctx, S) {
    if (S.k !== 2) return;
    const g = ctx.opt('gof', null);
    const ob = ctx.outline('Goodness of Fit', { key: 'gof', info: 'p:copula:gof', menu: () => [{ label: 'Change Bootstrap…', action: () => gofDialog(ctx) }, { label: 'Remove', action: () => ctx.set('gof', null) }] });
    const a = fitArgs(ctx, S.names);
    const r = await ctx.call('copula.gof', { columns: S.names, families: a.families, method: a.method, rotations: a.rotations, B: g.B, seed: g.seed });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const order = fitsOk(S.res).map((f) => f.family);
    const grows = r.rows.slice().sort((x, y) => order.indexOf(x.family) - order.indexOf(y.family));
    ob.add(wide(ctx.rt({ caption: 'Cramér–von Mises Test', columns: [{ key: 'label', label: 'Copula', fmt: 'text' }, { key: 'S', label: 'Sn' }, { key: 'S_mean', label: 'Mean Sn*', hidden: true }, { key: 'p', label: 'Prob>Sn', fmt: 'p' }, { key: 'B', label: 'Samples', fmt: 'int' }], rows: grows }, { key: 'gof', cellClass: (row) => (S.fit && row.family === S.fit.family ? 'sm-cop-shown' : '') })),
      ctx.note(`Sn = Σ (Cn(Ui) − C(Ui))², Cn the empirical copula of the pseudo-observations and C the fitted copula (Genest, Rémillard and Beaudoin 2009). Prob>Sn = (the number of bootstrap Sn* at least Sn + ½)/(B + 1), as R copula's gofCopula (simulation = "pb"), from ${r.B} samples${r.method === 'mpl' ? ', each fitted by maximum pseudo-likelihood' : ', each fitted from its Kendall\'s τ'} (seed ${r.seed}). A small p-value is evidence against the family; a large one is not evidence for it, only an absence of evidence against. The independence line tests independence.`),
      ctx.code(r.code));
  }

  /* ======================================================================
     MARGINS
     ====================================================================== */
  function marginsOutline(ctx, S) {
    const m = S.margins;
    const ob = ctx.outline('Margins', { key: 'margins', info: 'p:copula:margins', menu: () => [
      { label: 'All Margins', submenu: () => MARGIN_ITEMS.map(([v, l]) => ({ label: l, action: () => { for (const c of S.cols) ctx.set('marginFamily', v, c.id, { rerun: false }); ctx.report.run(); } })) },
      { label: 'Remove', action: () => ctx.set('margins', false) },
    ] });
    if (m.error) { ob.add(ctx.warn(m.error)); return; }
    const col = colors();
    const wrap = el('div', { class: 'sm-cop-margins' });
    ob.add(wrap);
    m.columns.forEach((c, q) => {
      const column = S.cols[q];
      const sub = ctx.outline(c.column, { parent: ob, key: `margin:${column.id}`, menu: () => MARGIN_ITEMS.map(([v, l]) => ({ label: l, checked: ctx.opt('marginFamily', 'auto', column.id) === v, action: () => ctx.set('marginFamily', v, column.id) })) });
      wrap.append(sub.el);
      const vals = colValues(column, S.res.rows);
      const bins = SM.report.niceBins(vals);
      const nb = Math.max(1, Math.round((bins.end - bins.start) / bins.size));
      const counts = new Array(nb).fill(0), members = Array.from({ length: nb }, () => []);
      vals.forEach((v, t) => { const h = Math.min(nb - 1, Math.max(0, Math.floor((v - bins.start) / bins.size + 1e-9))); counts[h]++; members[h].push(S.res.rows[t]); });
      const traces = [{ type: 'bar', x: counts.map((_, h) => bins.start + (h + 0.5) * bins.size), y: counts, width: bins.size, rows: members, marker: { color: SM.report.BAR, line: { color: col.surface, width: 0.8 } }, hovertemplate: '%{x}: %{y}<extra></extra>', name: c.column }];
      if (c.chosen.curve) traces.push({ type: 'scatter', mode: 'lines', x: c.chosen.curve.x, y: c.chosen.curve.pdf.map((d) => d * vals.length * bins.size), line: { color: col.contour, width: 2 }, hoverinfo: 'skip', name: c.chosen.label });
      const plot = ctx.plot(traces, { xaxis: { title: { text: c.column } }, yaxis: { title: { text: 'Count' }, rangemode: 'tozero' }, bargap: 0.02 }, { width: 330, height: 240, title: `${c.column} histogram with its margin` });
      const cands = c.candidates.map((f) => ({ ...f, params: f.params.map((p) => `${p.name.split(' ')[0]} ${nice(p.estimate)}`).join(', '), chosen: f.dist === c.chosen.dist ? '✓' : '' }));
      const tbl = wide(ctx.rt({ caption: 'Fitted Distributions, Best First by AICc', columns: [{ key: 'chosen', label: '', fmt: 'text' }, { key: 'label', label: 'Distribution', fmt: 'text' }, { key: 'params', label: 'Parameters', fmt: 'text' }, { key: 'k', label: 'Number of Parameters', fmt: 'int', hidden: true },
        { key: 'loglik', label: 'LogLikelihood', hidden: true }, { key: 'aicc', label: 'AICc' }, { key: 'delta', label: 'ΔAICc' }, { key: 'bic', label: 'BIC' }, { key: 'warning', label: 'Note', fmt: 'text', hidden: !cands.some((f) => f.warning) }], rows: cands },
      { key: 'margins', onRow: (row) => ctx.set('marginFamily', row.dist, column.id), cellClass: (r) => (r.chosen ? 'sm-cop-shown' : '') }));
      sub.add(ctx.row(plot, tbl), ctx.note(c.chosen.dist === 'empirical'
        ? 'The empirical margin: its distribution function steps through i/(n + 1) at the sorted values (interpolated between them), its quantiles are JMP\'s; the curve is a kernel density estimate, used only for the contours.'
        : `${c.chosen.label}${c.want === 'auto' ? ', the smallest AICc' : ''}: ${c.chosen.params.map((p) => `${p.name} = ${nice(p.estimate)}`).join(', ')} (maximum likelihood, as Distribution fits it). Click a line to use another; the red triangle also offers the empirical margin.`));
    });
    ob.add(ctx.note('The margins do not change the copula fits (those use only the ranks); they turn the copula into a joint distribution for the contours on the data scale, Joint Probabilities and Simulate.'), ctx.code(m.code));
  }

  /* ======================================================================
     JOINT PROBABILITIES
     ====================================================================== */
  async function calcOutline(ctx, S) {
    const { names, k } = S;
    const [i, j] = S.pair;
    const f = S.fit;
    const ob = ctx.outline('Joint Probabilities', { key: 'calc', info: 'p:copula:joint', menu: () => [...(k > 2 ? [{ label: 'Pair', submenu: () => pairItems(ctx, S) }] : []), { label: 'Remove', action: () => ctx.set('calc', false) }] });
    if (!f) { ob.add(ctx.warn('No copula was fitted.')); return; }
    const at = ctx.opt('calcAt', null) || {};
    const r = await ctx.call('copula.prob', { columns: names, family: f.family, params: pairParams(f, i, j, k), margins: [S.specs[i], S.specs[j]], pair: [i, j], x: at.x ?? null, y: at.y ?? null });
    const X = names[i], Y = names[j];
    const mk = (label, value) => {
      const inp = el('input', { type: 'text', inputmode: 'decimal', size: 9, 'aria-label': label, class: 'sm-cop-input' });
      inp.value = String(+value.toPrecision(7));
      return inp;
    };
    const ix = mk(`${X} value`, r.x), iy = mk(`${Y} value`, r.y);
    const go = () => {
      const num = (s) => { const t = s.value.trim().replace(',', '.').replace('−', '-'); return t === '' ? null : Number(t); };
      const x = num(ix), y = num(iy);
      if (!Number.isFinite(x) || !Number.isFinite(y)) { SM.ui.toast('Give a number for both columns', { error: true }); return; }
      ctx.set('calcAt', { x, y });
    };
    for (const inp of [ix, iy]) inp.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); go(); } });
    const btn = el('button', { type: 'button', class: 'sm-btn small', text: 'Compute' });
    btn.addEventListener('click', go);
    ob.add(el('div', { class: 'sm-cop-calc' }, el('label', null, el('span', { text: `${X} = x` }), ix), el('label', null, el('span', { text: `${Y} = y` }), iy), btn));
    const lines = [
      ['px', `P(${X} ≤ x)`], ['py', `P(${Y} ≤ y)`], ['le', `P(${X} ≤ x and ${Y} ≤ y)`], ['gt', `P(${X} > x and ${Y} > y)`],
      ['le_le', `P(${Y} ≤ y | ${X} ≤ x)`], ['gt_gt', `P(${Y} > y | ${X} > x)`],
    ].map(([key, label]) => ({ what: label, model: r.model[key], indep: r.indep[key], observed: r.observed[key] }));
    ob.add(wide(ctx.rt({ caption: `At x = ${nice(r.x)}, y = ${nice(r.y)}`, columns: [{ key: 'what', label: 'Probability', fmt: 'text' }, { key: 'model', label: `${f.label} Copula`, digits: 4 }, { key: 'indep', label: 'Independence', digits: 4 }, { key: 'observed', label: 'Observed Share', digits: 4 }], rows: lines }, { key: 'calc', sortable: false })),
      ctx.note(`From the fitted ${f.label} copula C with the margins F (${S.margins.columns.filter((_, c) => c === i || c === j).map((c) => `${c.column}: ${c.chosen.label}`).join(', ')}): u = F(x), v = F(y), P(both ≤) = C(u, v), P(both >) = 1 − u − v + C(u, v); the conditional probabilities divide by P(${X} ≤ x) or P(${X} > x). Independence uses the same margins with C(u, v) = uv. The observed shares count the ${fmt(r.n)} rows (${r.observed.n_le_x} with ${X} ≤ x, ${r.observed.n_gt_x} above).`));
  }

  /* ======================================================================
     SIMULATE
     ====================================================================== */
  async function simulateDialog(ctx) {
    const cols = ctx.roles('y');
    const names = cols.map((c) => c.name);
    const res = await ctx.call('copula.fit', fitArgs(ctx, names));
    if (res.error) { SM.ui.toast(res.error, { error: true }); return; }
    const f = shownFit(ctx, res);
    if (!f) { SM.ui.toast('No copula was fitted', { error: true }); return; }
    const cur = ctx.opt('simCompare', null) || {};
    const v = await SM.ui.form({
      title: 'Simulate', info: 'p:copula:simulate',
      lead: `Draws from the ${f.label} copula (${paramText(f, res.k)}) with the fitted margins, as a new table. The same seed gives the same table.`,
      fields: [
        { key: 'n', label: 'Number of rows', type: 'number', value: cur.n ?? res.n },
        { key: 'seed', label: 'Random seed', type: 'number', value: cur.seed ?? 1 },
        { key: 'scale', label: 'Values', type: 'select', value: cur.scale || 'data', choices: [['data', 'On the data scale: the copula with the fitted margins'], ['uniform', 'On the copula scale: uniform margins']] },
        { key: 'compare', label: 'Compare with the data in this report', type: 'check', value: true },
      ],
      validate: (x) => (!(Number.isInteger(x.n) && x.n >= 1 && x.n <= 1000000) ? 'The number of rows is a whole number from 1 to 1 000 000' : !(Number.isInteger(x.seed) && x.seed >= 0) ? 'The seed is a whole number, 0 or more' : null),
    });
    if (!v) return;
    let specs = null;
    if (v.scale === 'data') {
      const m = await ctx.call('copula.margins', { columns: names, choice: marginChoice(ctx, cols), alpha: ctx.alpha });
      if (m.error) { SM.ui.toast(m.error, { error: true }); return; }
      specs = marginSpecs(m);
    }
    const r = await ctx.call('copula.simulate', { columns: names, family: f.family, params: f.values, margins: specs, n: v.n, seed: v.seed, scale: v.scale });
    if (r.error) { SM.ui.toast(r.error, { error: true }); return; }
    const margText = specs ? specs.map((s, c) => `${names[c]} ${MARGIN_LABEL[s.dist] || s.dist}${s.values.length ? ` (${s.values.map((x) => nice(x)).join(', ')})` : ''}`).join('; ') : 'uniform margins';
    const t = new SM.Table({
      name: SM.app.uniqueTableName(`${ctx.table.name} simulated`), source: `simulated from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`,
      notes: `Simulated by Copulas: ${fmt(r.n)} draws from the ${f.label} copula (${paramText(f, res.k)}), fitted by ${METHOD[res.method].toLowerCase()} to ${fmt(res.n)} rows of ${ctx.table.name}${ctx.byLabel ? ` (${ctx.byLabel})` : ''}, with ${margText}; seed ${r.seed} (numpy default_rng).`,
      columns: names.map((nm, c) => ({ name: nm, dataType: 'numeric', values: r.values[c].map((x) => (x == null ? NaN : x)) })),
    });
    if (v.compare) ctx.set('simCompare', { n: v.n, seed: v.seed, scale: v.scale });
    SM.app.addTable(t);
    SM.ui.toast(`Made the table ${t.name}: ${fmt(r.n)} simulated rows`);
  }

  async function simOutline(ctx, S) {
    const sc = ctx.opt('simCompare', null);
    const { res, names, k } = S;
    const [i, j] = S.pair;
    const f = S.fit;
    const ob = ctx.outline('Simulated and Observed', { key: 'sim', info: 'p:copula:simulate', menu: () => [{ label: 'Simulate…', action: () => simulateDialog(ctx) }, { label: 'Remove', action: () => ctx.set('simCompare', null) }] });
    if (sc.scale === 'data' && !S.specs) { ob.add(ctx.warn('The margins could not be fitted.')); return; }
    const r = await ctx.call('copula.simulate', { columns: names, family: f.family, params: f.values, margins: sc.scale === 'data' ? S.specs : null, n: sc.n, seed: sc.seed, scale: sc.scale });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const col = colors();
    const uniform = sc.scale === 'uniform';
    const ox = uniform ? res.u[i] : colValues(S.cols[i], res.rows), oy = uniform ? res.u[j] : colValues(S.cols[j], res.rows);
    const nSim = r.values[i].length;
    const traces = [
      { type: scatterType(nSim), mode: 'markers', x: r.values[i], y: r.values[j], marker: { size: Math.max(3, markerSize(nSim) - 0.5), color: col.sim, symbol: 'x-thin', line: { width: 1.2, color: col.sim } }, hovertemplate: `simulated<br>${T(names[i])} %{x}<br>${T(names[j])} %{y}<extra></extra>`, name: 'Simulated' },
      { type: scatterType(res.n), mode: 'markers', x: ox, y: oy, rows: res.rows, marker: { size: markerSize(res.n) }, name: 'Observed' },
    ];
    const suffix = uniform ? ' (pseudo-observation)' : '';
    ob.add(ctx.row(ctx.plot(traces, { xaxis: { title: { text: `${names[i]}${suffix}` }, zeroline: false }, yaxis: { title: { text: `${names[j]}${suffix}` }, zeroline: false }, showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, margin: { l: 58, r: 10, t: 26, b: 46 } },
      { width: 420, height: 400, title: `Simulated and observed ${names[i]} and ${names[j]}` })),
    ctx.note(`${fmt(nSim)} draws (×) from the ${f.label} copula${uniform ? '' : ' with the fitted margins'}, seed ${sc.seed}, over the ${fmt(res.n)} observed rows (dots, linked to the table). Where the model is right the two clouds have the same shape${uniform ? '' : ', tails included'}.`), ctx.code(r.code));
  }

  /* ======================================================================
     THE TOP RED TRIANGLE
     ====================================================================== */
  function topMenu(ctx) {
    const cols = ctx.roles('y');
    return [
      ctx.check('Pseudo-Observations', 'pseudo', null, true),
      ctx.check('Dependence', 'dependence', null, true),
      ctx.check('Tail Concentration Function', 'tails', null, false),
      ctx.check('Copula Comparison', 'comparison', null, true),
      ctx.check('Margins', 'margins', null, false),
      ctx.check('Joint Probabilities', 'calc', null, false),
      { separator: true },
      { label: 'Fit', submenu: () => { const fam = ctx.opt('families', DEFAULT_FAMILIES); return FAMILY_ITEMS.map(([key, l]) => ({ label: l, checked: fam.includes(key), disabled: cols.length > 2 && !MULTI.includes(key), action: () => { const next = fam.includes(key) ? fam.filter((x) => x !== key) : [...fam, key]; if (next.length) ctx.set('families', next); else SM.ui.toast('Keep at least one copula'); } })); } },
      { label: 'Estimation Method', submenu: () => METHODS.map(([v, l]) => ({ label: l, checked: ctx.opt('method', 'mpl') === v, action: () => ctx.set('method', v) })) },
      { label: 'Goodness of Fit…', disabled: cols.length !== 2, action: () => gofDialog(ctx) },
      { label: 'Simulate…', action: () => simulateDialog(ctx) },
      { separator: true },
      { label: 'Save', submenu: () => [
        { label: 'Pseudo-Observations', action: () => saveScores(ctx, 'pseudo') },
        { label: 'Normal Scores', action: () => saveScores(ctx, 'normal') },
      ] },
    ];
  }

  async function saveScores(ctx, kind) {
    const names = ctx.names('y');
    const res = await ctx.call('copula.fit', fitArgs(ctx, names));
    if (res.error) { SM.ui.toast(res.error, { error: true }); return; }
    names.forEach((nm, c) => {
      const vals = kind === 'normal' ? res.u[c].map((x) => SM.util.qnorm(x)) : res.u[c];
      ctx.saveColumn(kind === 'normal' ? `Normal Score[${nm}]` : `Pseudo[${nm}]`, { rows: res.rows, values: vals },
        { notes: kind === 'normal' ? `Φ⁻¹ of the rank over n + 1 (ties averaged), from ${ctx.report.title}` : `rank over n + 1 (ties averaged), from ${ctx.report.title}` });
    });
  }

  /* ======================================================================
     THE LAUNCH DIALOG'S OWN PART: the copulas to fit and how
     ====================================================================== */
  function launchExtra(api, spec) {
    const o = (spec && spec.options) || {};
    const checks = FAMILY_ITEMS.map(([key, l]) => {
      const i = el('input', { type: 'checkbox', value: key });
      i.checked = (o.families || DEFAULT_FAMILIES).includes(key);
      return { key, i, lab: el('label', { class: 'sm-cop-check' }, i, el('span', { text: l })) };
    });
    const select = (items, value, aria) => {
      const s = el('select', { 'aria-label': aria }, ...items.map(([v, l]) => el('option', { value: v, text: l })));
      s.value = value;
      return s;
    };
    const rot = select(ROTATIONS, o.rotations || 'auto', 'Rotations of Clayton and Gumbel');
    const meth = select(METHODS, o.method || 'mpl', 'Estimation method');
    const marg = el('input', { type: 'checkbox' });
    marg.checked = !!o.margins;
    const hint = el('p', { class: 'sm-cop-hint' });
    const box = el('div', { class: 'sm-cop-launch' },
      el('h4', { text: 'Copulas to Fit' }),
      el('div', { class: 'sm-cop-checks' }, ...checks.map((c) => c.lab)),
      el('div', { class: 'sm-cop-opts' },
        el('label', { class: 'sm-cop-opt' }, el('span', { text: 'Rotations' }), rot),
        el('label', { class: 'sm-cop-opt' }, el('span', { text: 'Estimation' }), meth),
        el('label', { class: 'sm-cop-check' }, marg, el('span', { text: 'Fit Margins' }))),
      hint);
    const update = (state) => {
      const k = ((state && state.y) || []).length;
      for (const c of checks) c.lab.classList.toggle('is-off', k > 2 && !MULTI.includes(c.key));
      rot.disabled = k > 2;
      hint.textContent = k > 2 ? 'With more than two columns only the Gaussian, Student t and independence copulas are fitted.' : 'Rotations: Clayton and Gumbel turned by 180° for a positive τ (survival copulas) or by 90° and 270° for a negative one.';
    };
    api.onRolesChange(update);
    update(api.state);
    return {
      el: box,
      read: () => ({ options: { families: checks.filter((c) => c.i.checked).map((c) => c.key), rotations: rot.value, method: meth.value, margins: marg.checked } }),
      recall: (saved) => {
        const so = (saved && saved.options) || {};
        if (Array.isArray(so.families)) for (const c of checks) c.i.checked = so.families.includes(c.key);
        if (so.rotations) rot.value = so.rotations;
        if (so.method) meth.value = so.method;
        if (so.margins != null) marg.checked = !!so.margins;
      },
    };
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:copula': {
      kicker: 'Analyze > Multivariate Methods', title: 'Copulas',
      lead: 'How two or more continuous columns depend on each other once each column\'s own distribution is taken away. The columns\' ranks over n + 1 (pseudo-observations) are fitted by copula families of statsmodels.distributions.copula; with the margins fitted too, the copula gives the joint distribution, its probabilities and draws from it. JMP has no copula platform: the report follows JMP\'s fits in style, and the numbers are statsmodels\'.',
      sections: [
        { heading: 'Roles', choices: [['Y, Columns', 'Two continuous columns, or more for the Gaussian and Student t copulas.'], ['By', 'A separate analysis for each level.']] },
        { heading: 'The families', choices: [
          ['Gaussian', 'The normal distribution\'s dependence: symmetric, no tail dependence.'],
          ['Student t', 'Like the Gaussian, with tail dependence in all four corners that grows as ν falls.'],
          ['Clayton', 'Lower-tail dependence: small values come together.'],
          ['Frank', 'Symmetric, no tail dependence, positive or negative.'],
          ['Gumbel', 'Upper-tail dependence: large values come together.'],
          ['Rotations', 'Clayton and Gumbel turned by 180° (survival copulas: the tail moves to the other corner) or by 90° and 270° (negative dependence), as R\'s VineCopula defines them.'],
          ['Independence', 'C(u, v) = uv: the reference with no parameter.'],
        ] },
        { heading: 'Estimation', text: 'Maximum pseudo-likelihood (the default) maximises the copula\'s log density summed over the pseudo-observations; inversion of Kendall\'s τ sets each parameter so that the copula has the data\'s τ (what statsmodels itself offers, fit_corr_param). Both use only the ranks, so the margins cannot bias them.' },
      ],
      more: MORE,
    },
    'p:copula:pseudo': {
      kicker: 'Copulas', title: 'Pseudo-Observations',
      lead: 'Each row\'s rank in each column over n + 1: a sample from the copula when the columns are continuous. The contours are the fitted copula\'s highest-density regions holding 50, 75, 90 and 95% of its probability.',
      sections: [
        { heading: 'Scales', choices: [['Uniform', 'The ranks over n + 1, in the unit square.'], ['Normal Scores', 'Φ⁻¹ of them: the copula with standard normal margins, where the Gaussian copula\'s contours are ellipses and tail dependence pulls the corners out.']] },
        { heading: 'Data with the Joint Model', text: 'With the margins fitted, the data themselves with the contours of the joint density c(F₁(x), F₂(y)) f₁(x) f₂(y) (statsmodels CopulaDistribution).' },
        { heading: 'Linking', text: 'Click or drag over points to select their rows; rows selected elsewhere are highlighted here.' },
      ],
      more: MORE,
    },
    'p:copula:dependence': {
      kicker: 'Copulas', title: 'Dependence',
      lead: 'Rank correlations of the data, and the dependence each fitted copula implies: Kendall\'s τ, Spearman\'s ρ and the tail dependence coefficients.',
      sections: [
        { heading: 'Kendall and Spearman', text: 'τb (scipy kendalltau, with its standard error from the U-statistic variance: right click, Columns) and Spearman\'s ρ (spearmanr), with tests of no correlation.' },
        { heading: 'Tail dependence', text: 'λL is the limit of P(V ≤ q | U ≤ q) as q → 0, λU of P(V > q | U > q) as q → 1: the chance that one column is extreme given the other is. Gaussian and Frank: 0; Clayton: 2^(−1/θ) lower; Gumbel: 2 − 2^(1/θ) upper; t: 2 t_(ν+1)(−√((ν + 1)(1 − ρ)/(1 + ρ))) in both.' },
        { heading: 'statsmodels 0.14.6', text: 'Its t copula\'s dependence_tail divides by 1 where 1 + ρ is meant, and its spearmans_rho is the Gaussian copula\'s; both are computed correctly here (the t copula\'s ρ from its normal variance mixture form).' },
      ],
      more: MORE,
    },
    'p:copula:tails': {
      kicker: 'Copulas', title: 'Tail Concentration Function',
      lead: 'L(q) = C(q, q)/q for q ≤ ½ and R(q) = (1 − 2q + C(q, q))/(1 − q) above: the share of the rows below the q quantile in one column that are below it in the other too (and the same above). Its ends tend to the tail dependence coefficients. The data\'s curve (dots) against each fitted copula\'s (line), one panel per copula.',
      more: MORE,
    },
    'p:copula:comparison': {
      kicker: 'Copulas', title: 'Copula Comparison',
      lead: 'Each fitted copula: its parameters, log pseudo-likelihood, AIC (−2 log L + 2k), ΔAIC, the AIC weights and BIC, best first. A click on a line shows that copula in the graphs and uses it for the joint probabilities and simulations.',
      sections: [
        { heading: 'Standard errors', choices: [['Hessian', 'From the numerical Hessian of the log pseudo-likelihood (statsmodels approx_hess). They take the pseudo-observations as known and are too small: the ranks estimate the margins.'], ['Rank-Corrected', 'Genest, Ghoudi and Rivest\'s (1995) variance, which allows for the ranks (R copula\'s fitCopula(method = "mpl")). In simulations here it matches the spread of the estimates.'], ['Kendall\'s τ', 'With τ inversion: the delta method on τ\'s U-statistic variance.']] },
        { heading: 'Bounds', text: 'Clayton θ in [0.0001, 40], Gumbel θ in [1.000001, 50], Frank θ in [−100, 100], ρ in [−0.999, 0.999], ν in [1, 200]. A parameter at a bound has no standard error; Clayton or Gumbel at the lower bound is the independence copula.' },
      ],
      more: MORE,
    },
    'p:copula:gof': {
      kicker: 'Copulas', title: 'Goodness of Fit',
      lead: 'The Cramér–von Mises statistic Sn = Σ (Cn(Ui) − C(Ui))² between the empirical copula Cn and each fitted copula C, with a parametric bootstrap p-value (Genest, Rémillard and Beaudoin 2009; R copula\'s gofCopula with simulation = "pb"): B samples of n rows are drawn from the fitted copula, turned into pseudo-observations and fitted again, and p = (#{Sn* ≥ Sn} + ½)/(B + 1).',
      sections: [{ heading: 'Time', text: 'Every bootstrap sample is a new fit: a hundred samples take seconds for the one-parameter families and longer for the t copula, whose cdf is a numerical integral. For two columns.' }],
      more: MORE,
    },
    'p:copula:margins': {
      kicker: 'Copulas', title: 'Margins',
      lead: 'A distribution for each column on the rows the copula uses: normal, lognormal, gamma, Weibull, exponential, logistic, Student\'s t and beta (when they apply) fitted by maximum likelihood as Distribution fits them, the smallest AICc chosen; or pick one, or the empirical distribution (its cdf through i/(n + 1) at the sorted values).',
      more: MORE,
    },
    'p:copula:joint': {
      kicker: 'Copulas', title: 'Joint Probabilities',
      lead: 'The copula with the margins is a joint distribution. At a point (x, y): P(X ≤ x, Y ≤ y) = C(F₁(x), F₂(y)), the probability that both are above, and the conditional probabilities P(Y ≤ y | X ≤ x) and P(Y > y | X > x), beside the same under independence and the shares observed in the data.',
      more: MORE,
    },
    'p:copula:simulate': {
      kicker: 'Copulas', title: 'Simulate',
      lead: 'Draws from the fitted copula (statsmodels\' rvs; Frank\'s by conditional inversion), turned into values by the margins\' quantile functions (statsmodels CopulaDistribution.rvs), as a new table. A seed makes the draws repeatable: the Python code gives the same table. Compare with the data plots the draws over the observed rows.',
      more: MORE,
    },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'copula', label: 'Copulas', menu: 'Analyze/Multivariate Methods', order: 60, info: 'p:copula', topics: TOPICS,
    about: 'The dependence of two or more continuous columns apart from their own distributions: pseudo-observations (ranks over n + 1) linked to the rows with the fitted copula\'s density contours; Kendall\'s τ and Spearman\'s ρ and the τ, ρ and tail dependence each copula implies; Gaussian, Student t, Clayton, Frank and Gumbel copulas (with rotations) fitted by maximum pseudo-likelihood or from Kendall\'s τ, compared by AIC and BIC, with Hessian or rank-corrected standard errors and a parametric-bootstrap Cramér–von Mises test; fitted margins, the joint density on the data scale, joint and conditional probabilities, and simulation of new tables.',
    uses: ['statsmodels.distributions.copula (GaussianCopula, StudentTCopula, ClaytonCopula, FrankCopula, GumbelCopula, IndependenceCopula, CopulaDistribution)', 'statsmodels.tools.numdiff.approx_hess', 'statsmodels.stats.correlation_tools.corr_nearest', 'statsmodels.base.model.GenericLikelihoodModel (the margins, through Distribution)', 'scipy.stats (rankdata, kendalltau, spearmanr, multivariate_normal, multivariate_t), scipy.optimize, scipy.integrate'],
    launch: {
      lead: 'Choose two or more continuous columns. The copulas are fitted to their ranks; Clayton, Frank and Gumbel to two columns, the Gaussian and Student t copulas to any number.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 2, numeric: true, types: ['continuous'], hint: 'required: two or more continuous' },
        { key: 'by', label: 'By', hint: 'optional' },
      ],
      extra: launchExtra,
      validate: (spec) => ((spec.options && Array.isArray(spec.options.families) && !spec.options.families.length) ? 'Copulas to Fit: choose at least one' : null),
    },
    title: (spec, table) => {
      const names = ((spec.roles && spec.roles.y) || []).map((id) => (table && table.col(id) ? table.col(id).name : null)).filter(Boolean);
      return names.length === 2 ? `Copulas of ${names[0]} and ${names[1]}` : names.length > 2 ? `Copulas of ${names.length} Columns` : 'Copulas';
    },
    triangle: topMenu,
    render,
  });

  /* ---- the example: simulated, with its true copula in the notes ------------------------------ */
  SM.io.addExample('dependence', {
    label: 'Drought (500 rows): soil moisture and stream flow',
    about: 'Simulated: soil moisture (%) and stream flow (m³/s) on 500 days. Their ranks follow a Clayton copula with θ = 2 (Kendall\'s τ = 0.5; lower tail dependence λL = 2^(−1/2) ≈ 0.707, none in the upper tail): dry soil and low flow come together more often than wet soil and high flow. Soil moisture is Weibull with shape 2.2 and scale 30; stream flow lognormal with μ = 1.5 and σ = 0.6 on the log scale. Region (North, South) is assigned at random and changes nothing. For Copulas (Analyze > Multivariate Methods).',
    make() {
      const r = SM.util.rng('copula-dependence');
      const u01 = () => { let x = r.u(); while (x === 0) x = r.u(); return x; };
      // Marsaglia and Tsang's gamma sampler (shape below 1 by the U^(1/a) boost)
      const rgamma = (a) => {
        if (a < 1) return rgamma(a + 1) * u01() ** (1 / a);
        const d = a - 1 / 3, c = 1 / Math.sqrt(9 * d);
        for (;;) {
          let x, v;
          do { x = r.normal(); v = 1 + c * x; } while (v <= 0);
          v = v * v * v;
          const w = u01();
          if (w < 1 - 0.0331 * x ** 4 || Math.log(w) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v;
        }
      };
      const n = 500, theta = 2;
      const c = { day: [], region: [], moisture: [], flow: [] };
      for (let i = 0; i < n; i++) {
        // Clayton by its frailty: V ~ Gamma(1/θ), U = (1 + E/V)^(−1/θ) with E exponential
        const V = rgamma(1 / theta);
        const [u1, u2] = [0, 1].map(() => (1 - Math.log(u01()) / V) ** (-1 / theta));
        c.day.push(i + 1);
        c.region.push(r.u() < 0.5 ? 'North' : 'South');
        c.moisture.push(+(30 * (-Math.log1p(-u1)) ** (1 / 2.2)).toFixed(2));
        c.flow.push(+Math.exp(1.5 + 0.6 * SM.util.qnorm(u2)).toFixed(3));
      }
      return new SM.Table({ name: 'Drought', source: 'simulated', columns: [
        { name: 'day', dataType: 'numeric', values: c.day },
        { name: 'region', dataType: 'character', values: c.region },
        { name: 'soil moisture (%)', dataType: 'numeric', values: c.moisture },
        { name: 'stream flow (m³/s)', dataType: 'numeric', values: c.flow },
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
