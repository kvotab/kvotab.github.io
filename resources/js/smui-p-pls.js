/* ==========================================================================
   SMUI.HTML: ANALYZE > MULTIVARIATE METHODS > PARTIAL LEAST SQUARES

   JMP's Partial Least Squares on scikit-learn's PLSRegression, which is
   NIPALS (resources/py/smui/pls.py): continuous Y's on many, correlated
   continuous X's through a few factors.

     Model Launch                the method, the validation and the number
                                 of factors; Go adds a fit
     Model Comparison Summary    a line per fit
     NIPALS Fit with k Factors   per fit:
       ... Cross Validation      Root Mean PRESS per number of factors and
                                 van der Voet's T² test against the minimum
       X-Y Scores Plots          each factor's X score against its Y score
       Percent Variation Explained, Model Coefficients (centred and scaled,
       and original), Variable Importance Plot (VIP, the 0.8 line), and from
       the red triangle VIP vs Coefficients, Loading Plots, Distance Plots
       (DModX, DModY), T Square Plot, Percent Variation Plots, Profiler,
       Save Columns (Predicteds, X Scores, Y Scores), Remove Fit

   The fits are the report's option `fits` (the launch's settings make the
   first); every option that changes a fit's numbers is in its spec.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const MORE = { label: 'Partial Least Squares', id: 'help-p-pls' };
  const METHODS = [['kfold', 'KFold'], ['holdback', 'Holdback'], ['loo', 'Leave-One-Out'], ['none', 'None']];
  const SETS = ['Training', 'Validation', 'Test'];
  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));

  /* The sets' colours: the points' blue, and a green and a violet (not the selection's orange). */
  function setColors() {
    const c = SM.util.themeColors();
    return [SM.report.BASE, c.dark ? '#5fb36b' : '#3a7d44', c.dark ? '#b39ddb' : '#6c5b7b'];
  }
  function colors() {
    const c = SM.util.themeColors();
    return { ...c, line: c.dark ? '#ff7a6b' : '#c0392b', point: SM.report.BASE };
  }

  const wide = (tbl) => el('div', { class: 'sm-pls-scroll' }, tbl);
  const num = (v, d) => { const x = Number(v); return Number.isFinite(x) ? x : d; };
  const scatterType = (n) => (n > 4000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter');
  const markerSize = (n) => (n > 2000 ? 3.5 : n > 600 ? 4.5 : 6);
  const factorsWord = (k) => `${k} Factor${k === 1 ? '' : 's'}`;

  /* The fit the launch dialog asks for, and the fits of the report: the
     option `fits` (Go and Remove Fit change it), or that one fit. */
  function launchFit(ctx) {
    return { id: 'f1', method: ctx.opt('method', 'kfold'), folds: Math.round(num(ctx.opt('folds', 7), 7)), holdback: num(ctx.opt('holdback', 0.2), 0.2), factors: Math.round(num(ctx.opt('factors', 15), 15)) };
  }
  function fitList(ctx) {
    const f = ctx.opt('fits', null);
    return Array.isArray(f) ? f : [launchFit(ctx)];
  }

  /* What the backend needs to find a fit's model (the profiler's payload too). */
  function payloadOf(ctx, f) {
    return {
      y: ctx.names('y'), x: ctx.names('x'), validation: ctx.name('validation'), method: f.method, folds: f.folds, holdback: f.holdback, factors: f.factors,
      center: !!ctx.opt('center', true), scale: !!ctx.opt('scale', true), seed: SM.predict.seed(ctx),
    };
  }

  const vipThreshold = (ctx, f) => num(ctx.opt('vipThreshold', 0.8, f.id), 0.8);

  function validationText(r) {
    if (r.method === 'kfold') return `KFold, ${r.folds} folds`;
    if (r.method === 'holdback') return `Holdback ${fmt(r.holdback)}`;
    if (r.method === 'column') return 'Validation Column';
    return r.method === 'loo' ? 'Leave-One-Out' : 'None';
  }

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx) {
    const fits = fitList(ctx);
    const multiY = ctx.roles('y').length > 1;
    const scale = !!ctx.opt('scale', true), center = !!ctx.opt('center', true);
    ctx.container.append(ctx.note(`${ctx.roles('y').length} response${multiY ? 's' : ''} and ${ctx.roles('x').length} factors; ${center ? 'centred' : 'not centred'} and ${scale ? 'scaled' : 'not scaled'}. NIPALS (scikit-learn's PLSRegression).`));
    if (ctx.opt('launchPanel', true) && !ctx.headless) modelLaunch(ctx, fits);
    const results = [];
    for (const f of fits) {
      let r;
      const note = ctx.headless ? null : el('p', { class: 'sm-ob-note sm-pls-progress', role: 'status', text: `Fitting: ${validationText({ ...f, method: ctx.role('validation') ? 'column' : f.method })}…` });
      if (note) ctx.container.append(note);
      const off = note ? SM.engine.on('progress', (p) => { if (p && p.what === 'pls') note.textContent = `Leave-One-Out: ${fmt(p.done)} of ${fmt(p.total)} rows…`; }) : null;
      try { r = await ctx.call('pls.fit', { ...payloadOf(ctx, f), alpha: ctx.alpha }); } catch (e) { r = { error: e.message || String(e) }; } finally { if (off) off(); if (note) note.remove(); }
      results.push(r);
    }
    if (fits.length) comparison(ctx, fits, results);
    else ctx.container.append(ctx.note('No fits: choose the settings in Model Launch and press Go.'));
    for (let i = 0; i < fits.length; i++) await fitOutline(ctx, fits[i], results[i]);
  }

  /* ---- Model Launch: the settings of a new fit ------------------------------------------- */
  function modelLaunch(ctx, fits) {
    const ob = ctx.outline('Model Launch', { key: 'launch', info: 'p:pls:launch' });
    const hasCol = !!ctx.role('validation');
    const last = fits.length ? fits[fits.length - 1] : launchFit(ctx);
    const select = (items, value, aria, disabled) => { const s = el('select', { 'aria-label': aria, class: 'sm-pls-select' }, ...items.map(([v, l]) => el('option', { value: v, text: l }))); s.value = value; s.disabled = !!disabled; return s; };
    const input = (value, aria) => { const i = el('input', { type: 'text', inputmode: 'decimal', size: 5, 'aria-label': aria, class: 'sm-pls-input' }); i.value = String(value); return i; };
    const method = select([['nipals', 'NIPALS']], 'nipals', 'Method Specification', true);
    const vm = select(hasCol ? [['column', 'Validation Column']] : METHODS, hasCol ? 'column' : (last.method === 'column' ? 'kfold' : last.method), 'Validation Method', hasCol);
    const folds = input(last.folds ?? 7, 'Number of Folds');
    const hold = input(last.holdback ?? 0.2, 'Holdback Portion');
    const nf = input(last.factors ?? 15, 'Initial Number of Factors');
    const foldsBox = el('label', { class: 'sm-pls-field' }, el('span', { text: 'Number of Folds' }), folds);
    const holdBox = el('label', { class: 'sm-pls-field' }, el('span', { text: 'Holdback Portion' }), hold);
    const show = () => { foldsBox.hidden = vm.value !== 'kfold'; holdBox.hidden = vm.value !== 'holdback'; };
    vm.addEventListener('change', show);
    show();
    const go = el('button', { type: 'button', class: 'sm-btn small primary', text: 'Go' });
    const msg = el('span', { class: 'sm-pls-msg', role: 'status' });
    go.addEventListener('click', () => {
      const k = Math.round(num(folds.value.replace(',', '.'), NaN)), h = num(hold.value.replace(',', '.'), NaN), a = Math.round(num(nf.value.replace(',', '.'), NaN));
      if (vm.value === 'kfold' && !(k >= 2)) { msg.textContent = 'Number of Folds: 2 or more'; return; }
      if (vm.value === 'holdback' && !(h > 0 && h < 1)) { msg.textContent = 'Holdback Portion: between 0 and 1'; return; }
      if (!(a >= 1)) { msg.textContent = 'Initial Number of Factors: 1 or more'; return; }
      const ids = fits.map((x) => Number(String(x.id).replace(/^f/, '')) || 0);
      const next = { id: `f${Math.max(0, ...ids) + 1}`, method: vm.value, folds: vm.value === 'kfold' ? k : (last.folds ?? 7), holdback: vm.value === 'holdback' ? h : (last.holdback ?? 0.2), factors: a };
      ctx.set('fits', [...fits, next]);
    });
    ob.add(el('div', { class: 'sm-pls-launch', 'data-noexport': '' },
      el('label', { class: 'sm-pls-field' }, el('span', { text: 'Method Specification' }), method),
      el('label', { class: 'sm-pls-field' }, el('span', { text: 'Validation Method' }), vm), foldsBox, holdBox,
      el('label', { class: 'sm-pls-field' }, el('span', { text: 'Initial Number of Factors' }), nf), go, msg),
    ctx.note(`Go adds a fit with these settings${hasCol ? ' (the Validation column decides the rows: 0 or Training fit the model, 1 or Validation choose the number of factors, 2 or Test are kept out)' : ''}. scikit-learn's PLSRegression is NIPALS; JMP's SIMPLS is not in it.`));
  }

  /* ---- Model Comparison Summary ---------------------------------------------------------------- */
  function comparison(ctx, fits, results) {
    const ob = ctx.outline('Model Comparison Summary', { key: 'summary', info: 'p:pls:summary' });
    const thr = [...new Set(fits.map((f) => vipThreshold(ctx, f)))];
    const rows = [];
    fits.forEach((f, i) => {
      const r = results[i];
      if (!r || r.error) return;
      const last = r.percent[r.percent.length - 1] || {};
      rows.push({ method: 'NIPALS', validation: validationText(r), n: r.n_train, factors: r.factors, cumx: last.cumx, cumy: last.cumy, vip: r.vip.filter((v) => v > vipThreshold(ctx, f)).length });
    });
    ob.add(wide(ctx.rt({ columns: [
      { key: 'method', label: 'Method', fmt: 'text' }, { key: 'validation', label: 'Validation Method', fmt: 'text' }, { key: 'n', label: 'Number of rows', fmt: 'int' },
      { key: 'factors', label: 'Number of factors', fmt: 'int' }, { key: 'cumx', label: 'Percent Variation Explained for Cumulative X', digits: 4 },
      { key: 'cumy', label: 'Percent Variation Explained for Cumulative Y', digits: 4 }, { key: 'vip', label: thr.length === 1 ? `Number of VIP>${fmt(thr[0])}` : 'Number of VIP > Threshold', fmt: 'int' },
    ], rows }, { key: 'plssummary', sortable: false })));
  }

  /* ---- one fit ------------------------------------------------------------------------------------ */
  async function fitOutline(ctx, f, r) {
    const ok = r && !r.error;
    // Bootstrap reruns the report on resampled rows and finds a table by its
    // outlines' titles: a resample whose validation picks another number of
    // factors keeps the report's title (its numbers are the resample's own).
    const chosenKey = `plsChosen:${ctx.byLabel || ''}`;
    const chosen = ctx.opt(chosenKey, null) || {};
    if (ok && !ctx.headless && chosen[f.id] !== r.factors) ctx.set(chosenKey, { ...chosen, [f.id]: r.factors }, null, { rerun: false });
    const k = ok ? (ctx.resampled && chosen[f.id] != null ? chosen[f.id] : r.factors) : null;
    const ob = ctx.outline(ok ? `NIPALS Fit with ${factorsWord(k)}` : 'NIPALS Fit', { key: `fit:${f.id}`, info: 'p:pls:fit', menu: () => fitMenu(ctx, f, ok ? r : null) });
    if (!ok) { ob.add(ctx.warn(r ? r.error : 'The fit failed.')); return; }
    const o = (k, d) => ctx.opt(k, d, f.id);
    const sets = r.sets;
    const setText = r.method === 'column' || r.method === 'holdback' ? ` (Training ${sets.Training}, Validation ${sets.Validation}${sets.Test ? `, Test ${sets.Test}` : ''})` : '';
    ob.add(ctx.note([`${fmt(r.n)} rows${setText}; the model is fitted to the ${fmt(r.n_train)} training rows with ${factorsWord(r.factors)}${r.cv ? ', the number with the smallest Root Mean PRESS' : ` (the Initial Number of Factors${r.factors < r.factors_asked ? `, as many as the rows and X's allow` : ''})`}.`, ...r.notes].join(' ')));
    if (r.cv) cvOutline(ctx, ob, f, r);
    if (o('xyScores', true)) xyScores(ctx, ob, r);
    percentOutline(ctx, ob, f, r);
    coefOutlines(ctx, ob, r);
    if (o('vipPlot', true)) vipOutline(ctx, ob, f, r);
    if (o('vipCoef', false)) vipCoefOutline(ctx, ob, f, r);
    if (o('loadings', false)) loadingsOutline(ctx, ob, r);
    if (o('distance', false)) distanceOutline(ctx, ob, r);
    if (o('t2', false)) t2Outline(ctx, ob, r);
    if (o('profiler', false) && !ctx.headless) await SM.profiler.render(ctx, ob, { sources: [{ fn: 'pls.profile', payload: payloadOf(ctx, f) }], scope: f.id, option: 'profiler' });
    ob.add(ctx.code(r.code));
  }

  function cvOutline(ctx, parent, f, r) {
    const cv = r.cv;
    const ob = ctx.outline(cv.title, { parent, key: 'cv', info: 'p:pls:cv' });
    const col = colors();
    ob.add(ctx.row(wide(ctx.rt({ columns: [{ key: 'factors', label: 'Number of Factors', fmt: 'int' }, { key: 'rmpress', label: 'Root Mean PRESS', digits: 5 }, { key: 't2', label: 'van der Voet T²', digits: 4 }, { key: 'p', label: 'Prob > van der Voet T²', fmt: 'p' }], rows: cv.rows },
      { key: 'plscv', sortable: false, cellClass: (row) => (row.factors === cv.best ? 'sm-pls-min' : '') })),
    ctx.plot([
      { type: 'scatter', mode: 'lines+markers', x: cv.rows.map((q) => q.factors), y: cv.rows.map((q) => q.rmpress), line: { color: col.point, width: 1.6 }, marker: { size: 6, color: col.point }, hovertemplate: '%{x} factors: %{y:.5g}<extra></extra>', name: 'Root Mean PRESS' },
      { type: 'scatter', mode: 'markers', x: [cv.best], y: [cv.rows[cv.best].rmpress], marker: { size: 11, color: 'rgba(0,0,0,0)', line: { color: col.line, width: 2 } }, hoverinfo: 'skip', name: 'minimum' },
    ], { xaxis: { title: { text: 'Number of Factors' }, dtick: cv.rows.length > 12 ? 2 : 1 }, yaxis: { title: { text: 'Root Mean PRESS' } }, margin: { l: 58, r: 10, t: 8, b: 42 } }, { width: W(360), height: 260, title: 'Root Mean PRESS by number of factors', select: false })));
    const how = r.method === 'kfold' ? `each training row predicted by the model fitted to the other ${r.folds - 1} of ${r.folds} random folds (seed ${r.seed})`
      : r.method === 'loo' ? 'each training row predicted by the model fitted to the others'
        : 'the validation rows predicted by the model fitted to the training rows';
    const lines = [`The minimum Root Mean PRESS is ${fmt(cv.rows[cv.best].rmpress, { sig: 5 })} and the minimizing number of factors is ${cv.best}.`];
    if (cv.best === 0) lines.push('No number of factors predicts better than the mean of the training rows; the fit takes 1 factor.');
    if (cv.fewest != null && cv.fewest < Math.max(1, cv.best)) lines.push(`By van der Voet's rule (the fewest factors whose Prob > van der Voet T² exceeds 0.10, SAS's default), ${cv.fewest} would do.`);
    ob.add(ctx.note(lines.join(' ')), ctx.note(`PRESS: ${how}, over the ${fmt(cv.n_rows)} rows; Root Mean PRESS is the root of the mean squared predicted residual over the rows and responses, on the centred and scaled Y${r.scale ? '' : ' (not scaled: in the units of the Y\'s)'}. van der Voet's T² compares each number of factors with the minimum: C = d′S⁻¹d from the differences of the squared predicted residuals (d their sums per response, S their cross products), its p-value the share of ${fmt(cv.n_sim)} random swaps of the two models' residuals (seed) with a larger C, as SAS PROC PLS computes it. JMP's exact pooling over folds is not documented; here the residuals of every fold are pooled.`));
  }

  function xyScores(ctx, parent, r) {
    const ob = ctx.outline('X-Y Scores Plots', { parent, key: 'xy', info: 'p:pls:scores' });
    const sc = r.scores;
    const cols = setColors();
    const k = r.factors;
    const plots = [];
    for (let a = 0; a < k; a++) {
      const traces = [];
      let lo = Infinity, hi = -Infinity;
      for (let s = 0; s < 3; s++) {
        const idx = sc.set.map((v, i) => (v === s ? i : -1)).filter((i) => i >= 0);
        if (!idx.length) continue;
        const xs = idx.map((i) => sc.t[i][a]), ys = idx.map((i) => sc.u[i][a]);
        for (const v of xs) if (Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
        traces.push({ type: scatterType(idx.length), mode: 'markers', x: xs, y: ys, rows: idx.map((i) => sc.rows[i]), marker: { size: markerSize(sc.rows.length), color: cols[s], symbol: s === 0 ? 'circle' : s === 1 ? 'diamond' : 'square' }, name: SETS[s] });
      }
      // the inner relation: the least squares slope of u on t in the training rows
      const tr = sc.set.map((v, i) => (v === 0 ? i : -1)).filter((i) => i >= 0);
      const tt = tr.reduce((s0, i) => s0 + sc.t[i][a] ** 2, 0), tu = tr.reduce((s0, i) => s0 + sc.t[i][a] * sc.u[i][a], 0);
      const b = tt > 0 ? tu / tt : 0;
      if (Number.isFinite(lo)) traces.push({ type: 'scatter', mode: 'lines', x: [lo, hi], y: [b * lo, b * hi], line: { color: colors().muted, dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false });
      plots.push(ctx.plot(traces, { xaxis: { title: { text: `X Score ${a + 1}` }, zeroline: false }, yaxis: { title: { text: `Y Score ${a + 1}` }, zeroline: false }, margin: { l: 52, r: 8, t: 8, b: 42 }, showlegend: false },
        { width: W(k > 2 ? 250 : 300), height: 240, title: `X-Y scores of factor ${a + 1}` }));
    }
    const several = new Set(sc.set).size > 1;
    ob.add(ctx.row(...plots), ctx.note(`Each row's X score against its Y score on each factor; the dotted line is the inner relation u = b t fitted to the training rows (with one Y, b is 1).${several ? ' Circles: training rows; diamonds: validation; squares: test.' : ''} A curve suggests a nonlinear relation, a lone point an outlier. Drag over points to select rows.`));
  }

  function percentOutline(ctx, parent, f, r) {
    const ob = ctx.outline('Percent Variation Explained', { parent, key: 'percent', info: 'p:pls:percent' });
    ob.add(wide(ctx.rt({ columns: [{ key: 'factor', label: 'Number of Factors', fmt: 'int' }, { key: 'x', label: 'X Effect', digits: 4 }, { key: 'cumx', label: 'Cumulative X', digits: 4 }, { key: 'y', label: 'Y Effect', digits: 4 }, { key: 'cumy', label: 'Cumulative Y', digits: 4 }], rows: r.percent }, { key: 'plspercent', sortable: false })));
    if (ctx.opt('pctPlots', false, f.id)) {
      const col = colors();
      const xs = r.percent.map((q) => q.factor);
      const mk = (key, cum, title) => ctx.plot([
        { type: 'bar', x: xs, y: r.percent.map((q) => q[key]), marker: { color: SM.report.BAR }, name: title, hovertemplate: '%{x}: %{y:.4g}%<extra></extra>' },
        { type: 'scatter', mode: 'lines+markers', x: xs, y: r.percent.map((q) => q[cum]), line: { color: col.line, width: 1.6 }, marker: { size: 5, color: col.line }, name: 'Cumulative', hovertemplate: '%{x}: %{y:.4g}%<extra></extra>' },
      ], { xaxis: { title: { text: 'Number of Factors' }, dtick: 1 }, yaxis: { title: { text: `${title} (%)` }, range: [0, 102] }, margin: { l: 52, r: 8, t: 8, b: 42 } }, { width: W(300), height: 230, title, select: false });
      ob.add(ctx.row(mk('x', 'cumx', 'X Effect'), mk('y', 'cumy', 'Y Effect')));
    }
    ob.add(ctx.note('The percent of the centred and scaled X\'s and Y\'s sum of squares each factor explains in the training rows, and the cumulative percent.'));
  }

  function coefOutlines(ctx, parent, r) {
    const ys = r.y;
    const cols = [{ key: 'term', label: 'Term', fmt: 'text' }, ...ys.map((nm, k) => ({ key: `c${k}`, label: nm }))];
    const cs = r.x.map((nm, j) => ({ term: nm, ...Object.fromEntries(ys.map((_, k) => [`c${k}`, r.coef[j][k]])) }));
    const ob1 = ctx.outline('Model Coefficients for Centered and Scaled Data', { parent, key: 'coefcs', info: 'p:pls:coef' });
    ob1.add(wide(ctx.rt({ columns: cols, rows: cs }, { key: 'plscoefcs' })));
    if (!(r.center && r.scale)) ob1.add(ctx.note(`With ${r.center ? '' : 'Centering and '}${r.scale ? '' : 'Scaling'} off the data are ${r.center ? 'centred only' : r.scale ? 'scaled only' : 'as they are'}.`));
    const ob2 = ctx.outline('Model Coefficients for Original Data', { parent, key: 'coeforig', info: 'p:pls:coef' });
    const orig = [{ term: 'Intercept', ...Object.fromEntries(ys.map((_, k) => [`c${k}`, r.intercept[k]])) }, ...r.x.map((nm, j) => ({ term: nm, ...Object.fromEntries(ys.map((_, k) => [`c${k}`, r.coef_orig[j][k]])) }))];
    ob2.add(wide(ctx.rt({ columns: cols, rows: orig }, { key: 'plscoeforig', sortable: false })), ctx.note('The same model on the original scales: each coefficient times the Y\'s standard deviation over the X\'s, and the intercept from the means.'));
  }

  function vipOutline(ctx, parent, f, r) {
    const ob = ctx.outline('Variable Importance Plot', { parent, key: 'vip', info: 'p:pls:vip' });
    const thr = vipThreshold(ctx, f);
    const col = colors();
    const labels = r.x.map((nm) => T(nm));
    const plot = ctx.plot([
      { type: 'scatter', mode: 'lines+markers', x: labels, y: r.vip, line: { color: col.point, width: 1.4 }, marker: { size: 7, color: r.vip.map((v) => (v > thr ? col.point : col.muted)) }, hovertemplate: '%{x}: VIP %{y:.4f}<extra></extra>', name: 'VIP' },
    ], { xaxis: { type: 'category', tickangle: r.x.length > 8 ? -45 : 0, automargin: true }, yaxis: { title: { text: 'VIP' }, rangemode: 'tozero' }, margin: { l: 52, r: 10, t: 8, b: 50 },
      shapes: [{ type: 'line', xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: thr, y1: thr, line: { color: col.line, width: 1.3, dash: 'dash' } }] },
    { width: W(Math.max(320, Math.min(760, 70 + 34 * r.x.length))), height: 270, title: 'Variable importance', select: false });
    const tbl = wide(ctx.rt({ columns: [{ key: 'x', label: 'X', fmt: 'text' }, { key: 'vip', label: 'VIP', digits: 4 }], rows: r.x.map((nm, j) => ({ x: nm, vip: r.vip[j] })) }, { key: 'plsvip', cellClass: (row, c) => (c.key === 'vip' && row.vip <= thr ? 'sm-pls-low' : '') }));
    ob.add(ctx.row(plot, tbl), ctx.note(`VIP (Wold's variable importance for the projection) of each X over the ${factorsWord(r.factors).toLowerCase()}: √(p Σₐ SSYₐ w²ⱼₐ / Σₐ SSYₐ), SSYₐ the Y variation factor a explains and w its unit weights. The dashed line is the threshold ${fmt(thr)} (Set VIP Threshold): an X below it contributes little (Wold's rule of thumb, JMP's default 0.8).`));
  }

  function vipCoefOutline(ctx, parent, f, r) {
    const ob = ctx.outline('VIP vs Coefficients Plots', { parent, key: 'vipcoef', info: 'p:pls:vip' });
    const thr = vipThreshold(ctx, f);
    const col = colors();
    const plots = r.y.map((ynm, k) => {
      const cs = r.coef.map((row) => row[k]);
      let lo = Infinity, hi = -Infinity;
      for (const v of cs) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      const m = Math.max(Math.abs(lo), Math.abs(hi)) * 1.15 || 1;
      return ctx.plot([{ type: 'scatter', mode: 'markers+text', x: cs, y: r.vip, text: r.x.map((nm) => T(nm)), textposition: 'top center', textfont: { size: 9.5, color: col.text }, marker: { size: 7, color: col.point }, hovertemplate: '%{text}: coefficient %{x:.4g}, VIP %{y:.4f}<extra></extra>', name: T(ynm) }],
        { xaxis: { title: { text: `Coefficient for ${T(ynm)} (centred and scaled)` }, range: [-m, m], zeroline: true }, yaxis: { title: { text: 'VIP' }, rangemode: 'tozero' }, margin: { l: 52, r: 10, t: 8, b: 44 },
          shapes: [{ type: 'line', xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: thr, y1: thr, line: { color: col.line, width: 1.2, dash: 'dash' } }] },
        { width: W(360), height: 300, title: `VIP vs coefficients for ${ynm}`, select: false });
    });
    ob.add(ctx.row(...plots), ctx.note(`Each X's VIP against its centred and scaled coefficient, one plot per response: X's above the dashed line (${fmt(thr)}) and far from 0 matter; those below it with small coefficients are candidates to drop.`));
  }

  function loadingsOutline(ctx, parent, r) {
    const ob = ctx.outline('Loading Plots', { parent, key: 'loadings', info: 'p:pls:loadings' });
    const k = r.factors;
    const mk = (names, L, title) => ctx.plot(Array.from({ length: k }, (_, a) => ({
      type: 'scatter', mode: 'lines+markers', x: names.map((nm) => T(nm)), y: L.map((row) => row[a]), line: { color: SM.util.PALETTE[a % SM.util.PALETTE.length], width: 1.4 }, marker: { size: 5 }, name: `Factor ${a + 1}`, hovertemplate: `Factor ${a + 1}, %{x}: %{y:.4f}<extra></extra>`,
    })), { xaxis: { type: 'category', tickangle: names.length > 8 ? -45 : 0, automargin: true }, yaxis: { title: { text: title }, zeroline: true }, showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, margin: { l: 52, r: 10, t: 26, b: 50 } },
    { width: W(Math.max(320, Math.min(760, 80 + 34 * names.length))), height: 290, title, select: false });
    ob.add(ctx.row(mk(r.x, r.x_loadings, 'X Loadings'), mk(r.y, r.y_loadings, 'Y Loadings')),
      ctx.note('The X loadings p (the regression of each centred and scaled X on the factor\'s X scores) and the Y loadings q, factor by factor. The signs of a factor are arbitrary: scikit-learn turns each so that its largest weight is positive.'));
  }

  /* Points of rows by set (training, validation, test), in their own traces. */
  function bySet(r, xOf, yOf) {
    const cols = setColors();
    const d = r.dist;
    const out = [];
    for (let s = 0; s < 3; s++) {
      const idx = d.set.map((v, i) => (v === s ? i : -1)).filter((i) => i >= 0);
      if (!idx.length) continue;
      out.push({ type: scatterType(idx.length), mode: 'markers', x: idx.map((i) => xOf(i)), y: idx.map((i) => yOf(i)), rows: idx.map((i) => d.rows[i]), marker: { size: markerSize(d.rows.length), color: cols[s], symbol: s === 0 ? 'circle' : s === 1 ? 'diamond' : 'square' }, name: SETS[s] });
    }
    return out;
  }

  function distanceOutline(ctx, parent, r) {
    const ob = ctx.outline('Distance Plots', { parent, key: 'distance', info: 'p:pls:distance' });
    const d = r.dist;
    const several = new Set(d.set).size > 1;
    const lay = (xt, yt) => ({ xaxis: { title: { text: xt }, zeroline: false }, yaxis: { title: { text: yt }, rangemode: 'tozero' }, margin: { l: 52, r: 8, t: several ? 26 : 8, b: 42 }, showlegend: several, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' } });
    const plots = [];
    if (r.dmodx_ok) plots.push(ctx.plot(bySet(r, (i) => d.rows[i] + 1, (i) => d.dmodx[i]), lay('Row', 'DModX'), { width: W(320), height: 250, title: 'Distance to the X model by row' }));
    plots.push(ctx.plot(bySet(r, (i) => d.rows[i] + 1, (i) => d.dmody[i]), lay('Row', 'DModY'), { width: W(320), height: 250, title: 'Distance to the Y model by row' }));
    if (r.dmodx_ok) plots.push(ctx.plot(bySet(r, (i) => d.dmodx[i], (i) => d.dmody[i]), lay('DModX', 'DModY'), { width: W(320), height: 250, title: 'Distance to the Y model by distance to the X model' }));
    ob.add(ctx.row(...plots), ctx.note(`DModX: the root mean square of a row's centred and scaled X residuals after the ${factorsWord(r.factors).toLowerCase()}, over p − k degrees of freedom; DModY the same for the Y's (over the responses); both times √(n/(n − k − 1)) for the n training rows. A good model has both small; a row far out on either is an outlier of the X's or of the fit.${r.dmodx_ok ? '' : ' With as many factors as X\'s the X\'s are reproduced exactly: there is no DModX.'} Drag over points to select rows.`));
  }

  function t2Outline(ctx, parent, r) {
    const ob = ctx.outline('T Square Plot', { parent, key: 't2', info: 'p:pls:t2' });
    const d = r.dist;
    const col = colors();
    const several = new Set(d.set).size > 1;
    ob.add(ctx.row(ctx.plot(bySet(r, (i) => d.rows[i] + 1, (i) => d.t2[i]), {
      xaxis: { title: { text: 'Row' }, zeroline: false }, yaxis: { title: { text: 'T²' }, rangemode: 'tozero' }, margin: { l: 52, r: 8, t: several ? 26 : 8, b: 42 }, showlegend: several, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' },
      shapes: [{ type: 'line', xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: r.ucl, y1: r.ucl, line: { color: col.line, width: 1.3, dash: 'dash' }, label: { text: `UCL ${fmt(r.ucl, { sig: 4 })}`, font: { size: 10, color: col.line }, textposition: 'end' } }],
    }, { width: W(560), height: 270, title: 'T² by row' })),
    ctx.note(`Hotelling's T² of each row's X scores, Σₐ tₐ²/sₐ² with sₐ² the training variance of factor a: how far the row is from the centre of the model plane. The dashed limit is ((n − 1)²/n) times the ${fmt(100 * (1 - ctx.alpha))}% quantile of Beta(k/2, (n − k − 1)/2) (the training rows' own distribution; α from the report's Set α Level). Drag over points to select rows.`));
  }

  /* ======================================================================
     MENUS
     ====================================================================== */
  function fitMenu(ctx, f, r) {
    const c = (label, key, d) => ctx.check(label, key, f.id, d);
    const items = [
      c('Percent Variation Plots', 'pctPlots', false),
      c('Variable Importance Plot', 'vipPlot', true),
      c('VIP vs Coefficients Plots', 'vipCoef', false),
      { label: 'Set VIP Threshold…', action: () => vipDialog(ctx, f) },
      c('Loading Plots', 'loadings', false),
      c('X-Y Scores Plots', 'xyScores', true),
      c('Distance Plots', 'distance', false),
      c('T Square Plot', 't2', false),
      c('Profiler', 'profiler', false),
      { separator: true },
      { label: 'Save Columns', disabled: !r, submenu: () => [
        { label: 'Save Predicteds', action: () => save(ctx, f, 'pred') },
        { label: 'Save X Scores', action: () => save(ctx, f, 'xscores') },
        { label: 'Save Y Scores', action: () => save(ctx, f, 'yscores') },
      ] },
      { label: 'Remove Fit', action: () => ctx.set('fits', fitList(ctx).filter((x) => x.id !== f.id)) },
    ];
    return items;
  }

  async function vipDialog(ctx, f) {
    const v = await SM.ui.form({ title: 'Set VIP Threshold', info: 'p:pls:vip', fields: [{ key: 'thr', label: 'VIP threshold', type: 'number', value: vipThreshold(ctx, f) }], validate: (x) => (x.thr > 0 ? null : 'The threshold is a positive number') });
    if (v) ctx.set('vipThreshold', v.thr, f.id);
  }

  async function save(ctx, f, what) {
    try {
      const r = await ctx.call('pls.save', { ...payloadOf(ctx, f), what });
      const from = `from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''} (NIPALS fit ${f.id})`;
      r.names.forEach((nm, k) => ctx.saveColumn(nm, { rows: r.rows, values: r.values[k] }, { notes: `${what === 'pred' ? 'predicted' : what === 'xscores' ? 'X score' : 'Y score'}, ${from}` }));
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  function topMenu(ctx) {
    return [
      ctx.check('Model Launch', 'launchPanel', null, true),
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:pls': {
      kicker: 'Analyze > Multivariate Methods', title: 'Partial Least Squares',
      lead: 'Predicts one or more continuous Y\'s from many continuous X\'s, even more X\'s than rows or X\'s that are nearly collinear (spectra, process sensors), through a few factors: linear combinations of the X\'s chosen to explain the X\'s and to predict the Y\'s. Validation chooses how many factors. The numbers are scikit-learn\'s PLSRegression (NIPALS).',
      sections: [
        { heading: 'Roles', choices: [['Y', 'One or more continuous responses, fitted together.'], ['X', 'Continuous factors.'], ['Validation', 'Optional: 0 or Training, 1 or Validation, 2 or Test.'], ['By', 'A separate analysis for each level.']] },
        { heading: 'Centering and Scaling', text: 'On by default: each column less its mean, over its standard deviation (the training rows\'). Without Scaling a column with large values dominates the factors. scikit-learn always centres; with Centering off it is given the rows and their mirror image, whose means are 0, which gives the uncentred model.' },
        { heading: 'Method', text: 'NIPALS, scikit-learn\'s PLSRegression: the X scores deflate both the X\'s and the Y\'s, as JMP\'s NIPALS. JMP\'s SIMPLS (the same for one Y) is not in scikit-learn.' },
        { heading: 'Validation Method', choices: [['KFold', '7 folds by default, drawn at random from the seed (scikit-learn KFold with shuffle).'], ['Holdback', 'A share of the rows (0.2) drawn from the seed chooses the number of factors; the rest fit the model.'], ['Leave-One-Out', 'Each row predicted by the model without it.'], ['Validation column', 'Its 1 rows choose, its 0 rows fit, its 2 rows are kept out.'], ['None', 'The Initial Number of Factors, as many as the rows and X\'s allow.']] },
        { heading: 'Initial Number of Factors', text: 'The most factors tried (15 by default), at most the number of X\'s and the training rows less two.' },
      ],
      more: MORE,
    },
    'p:pls:launch': { kicker: 'Partial Least Squares', title: 'Model Launch', lead: 'The settings of a new fit: the method (NIPALS), the validation method with its folds or holdback portion, and the Initial Number of Factors. Go adds the fit below, and a line to the Model Comparison Summary; Remove Fit (a fit\'s red triangle) takes it away.', more: MORE },
    'p:pls:summary': { kicker: 'Partial Least Squares', title: 'Model Comparison Summary', lead: 'A line per fit: its method and validation, the training rows, the number of factors, the cumulative percent of the X and Y variation it explains, and how many X\'s have a VIP above the threshold.', more: MORE },
    'p:pls:fit': {
      kicker: 'Partial Least Squares', title: 'NIPALS Fit',
      lead: 'The model with the number of factors the validation chose (the smallest Root Mean PRESS), fitted to the training rows. Its red triangle adds the VIP vs Coefficients, Loading, Distance, T Square and Percent Variation plots, the Profiler, and Save Columns.',
      more: MORE,
    },
    'p:pls:cv': {
      kicker: 'Partial Least Squares', title: 'Cross Validation',
      lead: 'For 0 to the Initial Number of Factors: the Root Mean PRESS, the root mean squared predicted residual of the validation rows over the responses (centred and scaled Y), and van der Voet\'s T² test of each number against the one with the minimum.',
      sections: [
        { heading: 'van der Voet T²', text: 'With D the differences of the squared predicted residuals of the two models (row by response), d the sums of D\'s columns and S = D′D, C = d′S⁻¹d; its p-value is the share of random swaps of the two models\' residuals row by row (1000, from the seed) with a larger C (van der Voet 1994, as SAS PROC PLS computes it). A p-value above 0.10 says the model with fewer factors predicts about as well; SAS then takes the fewest such factors. The fit here takes the minimum, as JMP does.' },
        { heading: 'Pooling', text: 'For KFold and Leave-One-Out the residuals of all folds are pooled into one PRESS and one test. JMP documents averaging over validation sets for the T²; its exact computation is not documented.' },
      ],
      more: MORE,
    },
    'p:pls:percent': { kicker: 'Partial Least Squares', title: 'Percent Variation Explained', lead: 'For each factor, the percent of the centred and scaled X\'s sum of squares (X Effect) and of the Y\'s (Y Effect) it explains in the training rows, and the cumulative percents. Percent Variation Plots (red triangle) draws them.', more: MORE },
    'p:pls:coef': { kicker: 'Partial Least Squares', title: 'Model Coefficients', lead: 'The fitted model as coefficients of the X\'s: on the centred and scaled data, B = W(P′W)⁻¹Q′ from the weights W and the loadings P and Q, and on the original scales, with the intercepts. They equal scikit-learn\'s coef_.', more: MORE },
    'p:pls:vip': { kicker: 'Partial Least Squares', title: 'Variable Importance', lead: 'VIP of each X: √(p Σₐ SSYₐ w²ⱼₐ / Σₐ SSYₐ), the X\'s squared unit weights on the factors, each weighted by the Y variation the factor explains, times the number of X\'s p. The mean of VIP² is 1; below the threshold (0.8, Wold\'s rule, JMP\'s default) an X contributes little. VIP vs Coefficients plots each X\'s VIP against its centred and scaled coefficient.', more: MORE },
    'p:pls:scores': { kicker: 'Partial Least Squares', title: 'X-Y Scores Plots', lead: 'For each factor, each row\'s X score t (the row\'s centred and scaled X\'s times the factor\'s rotation) against its Y score u (its deflated Y\'s times the Y weights). The dotted line is the inner relation u = b t.', more: MORE },
    'p:pls:loadings': { kicker: 'Partial Least Squares', title: 'Loading Plots', lead: 'The X loadings (each X regressed on a factor\'s X scores) and the Y loadings of each factor, across the variables: which X\'s and Y\'s a factor carries.', more: MORE },
    'p:pls:distance': { kicker: 'Partial Least Squares', title: 'Distance Plots', lead: 'DModX and DModY: the distances of each row to the X and Y models, the root mean squares of its centred and scaled residuals after the factors (over p − k for the X\'s, over the responses for the Y\'s), times √(n/(n − k − 1)) for training rows. Validation and test rows are drawn in their own markers.', more: MORE },
    'p:pls:t2': { kicker: 'Partial Least Squares', title: 'T Square Plot', lead: 'Hotelling\'s T² of each row\'s X scores, with the limit ((n − 1)²/n) Beta(1 − α; k/2, (n − k − 1)/2) for the training rows. A row above it is far from the other rows in the plane of the factors.', more: MORE },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'pls', label: 'Partial Least Squares', menu: 'Analyze/Multivariate Methods', order: 32, info: 'p:pls', topics: TOPICS,
    about: 'Partial least squares regression of continuous Y\'s on many, correlated continuous X\'s, as JMP\'s Partial Least Squares: NIPALS (scikit-learn\'s PLSRegression) with Centering and Scaling, the number of factors chosen by KFold, Holdback, Leave-One-Out or a Validation column (Root Mean PRESS and van der Voet\'s T² test), or given; the Model Comparison Summary of the fits, Percent Variation Explained, the model coefficients (centred and scaled, and original), VIP with the 0.8 line and VIP vs Coefficients, X-Y scores, loadings, the distances DModX and DModY, T², the Prediction Profiler, and Save Predicteds, X Scores and Y Scores.',
    uses: ['sklearn.cross_decomposition.PLSRegression', 'sklearn.model_selection.KFold, LeaveOneOut', 'numpy.linalg.pinv', 'scipy.stats.beta'],
    launch: {
      lead: 'Choose the continuous responses and the continuous factors. The number of factors is chosen by validation (KFold by default) and can be refitted from Model Launch in the report.',
      roles: [
        { key: 'y', label: 'Y', min: 1, numeric: true, types: ['continuous'], hint: 'required: continuous responses' },
        { key: 'x', label: 'X', min: 1, numeric: true, types: ['continuous'], hint: 'required: continuous factors' },
        { key: 'validation', label: 'Validation', max: 1, hint: 'optional: 0/1/2 or Training/Validation/Test', info: 'p:predict:validation' },
        { key: 'by', label: 'By', hint: 'optional' },
      ],
      options: [
        { key: 'center', label: 'Centering', type: 'check', value: true },
        { key: 'scale', label: 'Scaling', type: 'check', value: true },
        { key: 'plsMethod', label: 'Method', type: 'select', value: 'nipals', choices: [['nipals', 'NIPALS']], hint: 'scikit-learn\'s PLSRegression is NIPALS; SIMPLS is not in it' },
        { key: 'method', label: 'Validation Method', type: 'select', value: 'kfold', choices: METHODS, hint: 'a Validation column, when cast, decides instead' },
        { key: 'folds', label: 'Number of Folds', type: 'number', value: 7 },
        { key: 'holdback', label: 'Holdback Portion', type: 'number', value: 0.2 },
        { key: 'factors', label: 'Initial Number of Factors', type: 'number', value: 15 },
        { key: 'seed', label: 'Random Seed', type: 'text', value: '', hint: 'empty: a seed drawn now and kept with the report' },
      ],
      validate: (spec) => {
        const o = spec.options || {};
        if (o.folds != null && !(Number.isInteger(o.folds) && o.folds >= 2)) return 'Number of Folds is a whole number, 2 or more';
        if (o.holdback != null && !(o.holdback > 0 && o.holdback < 1)) return 'Holdback Portion is between 0 and 1';
        if (o.factors != null && !(Number.isInteger(o.factors) && o.factors >= 1)) return 'Initial Number of Factors is a whole number, 1 or more';
        if (o.seed != null && String(o.seed).trim() !== '' && !Number.isInteger(Number(o.seed))) return 'The Random Seed is a whole number';
        const ys = (spec.roles && spec.roles.y) || [], xs = (spec.roles && spec.roles.x) || [];
        if (ys.some((id) => xs.includes(id))) return 'A column cannot be both a Y and an X';
        return null;
      },
    },
    title: () => 'Partial Least Squares',
    triangle: topMenu,
    render,
  });

  /* ---- the example: simulated spectra ---------------------------------------------------------- */
  SM.io.addExample('spectra', {
    label: 'Spectra (60 samples): absorbance at 30 wavelengths',
    about: 'Simulated: 60 samples, each a mixture of three components whose concentrations (%) vary at random: analyte A (1–10%), analyte B (0.5–5%) and water (5–25%), which is not a response. The absorbance at 30 wavelengths from 1100 to 2260 nm is the sum of each component\'s spectrum (Gaussian bands, A at 1450 and 1940 nm, B at 1700 and 2100 nm, water at 1450 and 1930 nm, overlapping A\'s) times its concentration, plus a baseline that shifts and tilts from sample to sample, plus noise (sd 0.002). The 30 absorbances are highly correlated and outnumber the latent structure: three factors carry A, B and the water, a fourth the baseline. For Partial Least Squares (Analyze > Multivariate Methods).',
    make() {
      const r = SM.util.rng('pls-spectra');
      const n = 60;
      const waves = Array.from({ length: 30 }, (_, j) => 1100 + 40 * j);
      const band = (w, c, s) => Math.exp(-0.5 * ((w - c) / s) ** 2);
      const spec = {
        A: (w) => 0.030 * band(w, 1450, 45) + 0.022 * band(w, 1940, 60),
        B: (w) => 0.045 * band(w, 1700, 55) + 0.030 * band(w, 2100, 70),
        water: (w) => 0.012 * band(w, 1450, 70) + 0.018 * band(w, 1930, 75),
      };
      const cA = [], cB = [], cW = [], X = waves.map(() => []);
      for (let i = 0; i < n; i++) {
        const a = 1 + 9 * r.u(), b = 0.5 + 4.5 * r.u(), wtr = 5 + 20 * r.u();
        const offset = 0.05 + 0.03 * r.normal(), tilt = 0.00002 * r.normal();
        cA.push(+a.toFixed(3)); cB.push(+b.toFixed(3)); cW.push(+wtr.toFixed(2));
        waves.forEach((w, j) => X[j].push(+(a * spec.A(w) + b * spec.B(w) + wtr * spec.water(w) + offset + tilt * (w - 1680) + 0.002 * r.normal()).toFixed(5)));
      }
      return new SM.Table({ name: 'Spectra', source: 'simulated', columns: [
        { name: 'sample', dataType: 'numeric', values: Array.from({ length: n }, (_, i) => i + 1) },
        { name: 'A (%)', dataType: 'numeric', values: cA },
        { name: 'B (%)', dataType: 'numeric', values: cB },
        { name: 'water (%)', dataType: 'numeric', values: cW },
        ...waves.map((w, j) => ({ name: `nm ${w}`, dataType: 'numeric', values: X[j] })),
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
