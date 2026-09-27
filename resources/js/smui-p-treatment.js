/* ==========================================================================
   SMUI.HTML: ANALYZE > SPECIALIZED MODELING > TREATMENT EFFECTS

   The effect of a two-level treatment on an outcome, from observational
   data where the treated and the controls differ: statsmodels'
   TreatmentEffect (resources/py/smui/treatment.py) with five estimators,
   IPW, AIPW, AIPW (WLS), RA and IPW-RA, for the average effect, the
   potential-outcome means and, where statsmodels has it, the effect on the
   treated; the propensity score model (logit or probit) and the overlap of
   its scores, with trimming; the covariate balance before and after
   weighting, with a Love plot; the weights; the outcome models; and notes
   on what the estimates assume. JMP has no such platform: the report is
   laid out as JMP lays out its model reports.

   It brings its own example table, File > Examples > Job training: a
   simulated observational study with a known effect.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;

  const EST = [['ipw', 'IPW'], ['aipw', 'AIPW'], ['aipw_wls', 'AIPW (WLS)'], ['ra', 'RA'], ['ipw_ra', 'IPW-RA']];
  const EST_KEYS = EST.map((e) => e[0]);
  const ATT_OK = ['ipw', 'ra', 'ipw_ra'];
  const MORE = { label: 'Treatment Effects', id: 'help-p-treatment' };
  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));
  const esc = (s) => SM.report.plotlyText(s);
  const slot = (key) => (typeof KvotInfo !== 'undefined' ? KvotInfo.slot(key) : null);

  /* The two groups' colours: blue for the controls, rose for the treated,
     apart from each other and from the selection's orange in both themes
     (checked with the dataviz skill's validator). */
  const groupColors = () => (SM.util.themeColors().dark ? { treated: '#d1528f', control: '#4d8ad6' } : { treated: '#b8406e', control: '#2e6fba' });

  /* ---- the treated level ------------------------------------------------------ */
  function treatedLevel(ctx) {
    const c = ctx.role('treatment');
    if (!c) return null;
    const lv = ctx.table.levels(c);
    const want = ctx.opt('treated', null);
    const hit = want == null ? undefined : lv.find((v) => String(v) === String(want));
    return hit !== undefined ? hit : (lv.length ? lv[lv.length - 1] : null);
  }

  function payloadOf(ctx) {
    const t = ctx.role('treatment');
    return {
      y: ctx.name('y'), treatment: t ? t.name : null, treated: treatedLevel(ctx),
      outcome: ctx.names('outcome'), covariates: ctx.names('covariates'),
      link: ctx.opt('link', 'logit'), trim: ctx.opt('trim', null) || null, alpha: ctx.alpha,
    };
  }

  const pct = (x) => fmt(x, { sig: 3 });

  /* ---- histograms of two groups, mirrored or overlaid, bins linked to rows -------- */
  function niceStep(max, n = 4) {
    const raw = Math.max(max, 1) / n;
    const p = 10 ** Math.floor(Math.log10(raw));
    return [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw && (s >= 1 || max < 4)) || Math.max(1, Math.ceil(raw));
  }

  function groupHistogram(ctx, { values, t, rows, bins, mirror, lab, xTitle, title, shapes = [], width = 470, height = 280 }) {
    const C = groupColors();
    const surf = SM.util.themeColors().surface;
    const nb = Math.max(1, Math.round((bins.end - bins.start) / bins.size));
    const g = {};
    for (const key of ['treated', 'control']) g[key] = { counts: new Array(nb).fill(0), members: Array.from({ length: nb }, () => []) };
    for (let k = 0; k < values.length; k++) {
      const v = values[k];
      if (!Number.isFinite(v)) continue;
      const j = Math.min(nb - 1, Math.max(0, Math.floor((v - bins.start) / bins.size + 1e-9)));
      const G = t[k] === 1 ? g.treated : g.control;
      G.counts[j]++;
      G.members[j].push(rows[k]);
    }
    const centers = Array.from({ length: nb }, (_, j) => bins.start + (j + 0.5) * bins.size);
    const range = (j) => `${fmt(bins.start + j * bins.size, { sig: 4 })} to ${fmt(bins.start + (j + 1) * bins.size, { sig: 4 })}`;
    const trace = (key, sign) => ({
      type: 'bar', x: centers, y: g[key].counts.map((c) => sign * c), width: bins.size, rows: g[key].members, rowsScale: sign,
      marker: { color: C[key], opacity: mirror ? 1 : 0.62, line: { color: surf, width: 0.8 } },
      name: esc(lab[key]), hovertext: g[key].counts.map((c, j) => `${esc(lab[key])}: ${c} row${c === 1 ? '' : 's'}, ${range(j)}`), hovertemplate: '%{hovertext}<extra></extra>',
    });
    const traces = [trace('treated', 1), trace('control', mirror ? -1 : 1)];
    const maxC = Math.max(1, ...g.treated.counts, ...g.control.counts);
    let yaxis = { title: { text: 'Count' }, rangemode: 'tozero' };
    if (mirror) {
      const step = niceStep(maxC);
      const vals = [0];
      for (let v = step; v <= maxC * 1.04 + 1e-9; v += step) vals.push(v, -v);
      vals.sort((a, b) => a - b);
      yaxis = { title: { text: 'Count' }, tickvals: vals, ticktext: vals.map((v) => fmt(Math.abs(v))), range: [-1.1 * maxC, 1.1 * maxC], zeroline: true };
    }
    const layout = {
      barmode: 'overlay', bargap: 0, showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' },
      xaxis: { title: { text: xTitle }, range: [bins.start, bins.end] }, yaxis, shapes, margin: { l: 56, r: 12, t: 30, b: 42 },
    };
    return ctx.plot(traces, layout, { width: W(width), height, title });
  }

  /* ---- the summary and the estimates -------------------------------------------------- */
  function summary(ctx, res, lab) {
    const pairs = [
      ['Outcome', res.y, 'text'],
      ['Treated', `${lab.treated}: ${res.n_treated} rows`, 'text'],
      ['Control', `${lab.control}: ${res.n_control} rows`, 'text'],
      ['Treatment model', `${res.propensity.link === 'probit' ? 'Probit' : 'Logit'} on ${res.covariates.join(', ')}`, 'text'],
      ['Outcome model', res.outcome.length ? `Least squares in each group on ${res.outcome.join(', ')}` : 'The group means (no outcome covariates)', 'text'],
      res.n_missing ? ['Rows left out (missing values)', res.n_missing, 'int'] : null,
      res.trim && res.trim.n_dropped ? ['Rows trimmed', `${res.trim.n_dropped}: a propensity score outside [${fmt(res.trim.eps)}, ${fmt(1 - res.trim.eps)}]`, 'text'] : null,
    ];
    ctx.container.append(el('div', { class: 'sm-te-summary' }, ctx.kv(pairs)));
  }

  function effectRows(list, part = 'ate') {
    return list.map((e) => (e.error ? { label: e.label, estimate: null, se: null, z: null, p: null, lower: null, upper: null } : { label: e.label, ...e[part] }));
  }

  function estimatesTable(ctx, rows, caption, key) {
    const lv = fmt(100 * (1 - ctx.alpha));
    return ctx.rt({
      columns: [{ key: 'label', label: 'Estimator', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'z', label: 'z Ratio' },
        { key: 'p', label: 'Prob>|z|', fmt: 'p' }, { key: 'lower', label: `Lower ${lv}%` }, { key: 'upper', label: `Upper ${lv}%` }],
      rows,
    }, { caption, sortable: false, key });
  }

  function estimatesMenu(ctx) {
    const on = ctx.opt('estimators', EST_KEYS);
    return [
      { label: 'Estimators', submenu: () => EST.map(([k, label]) => ({
        label, checked: on.includes(k),
        action: () => { const next = on.includes(k) ? on.filter((x) => x !== k) : EST_KEYS.filter((x) => on.includes(x) || x === k); if (!next.length) { SM.ui.toast('Keep one estimator at least'); return; } ctx.set('estimators', next); },
      })) },
      ctx.check('Effect on the Treated (ATT)', 'att', null, true),
      ctx.check('Potential Outcome Means', 'pom', null, true),
      ctx.check('Estimate Comparison Plot', 'forest', null, true),
    ];
  }

  function forestPlot(ctx, res, ate, att) {
    const T = SM.util.themeColors();
    const items = [{ label: 'Difference in Means', kind: 'naive', ...res.naive }];
    for (const e of ate.estimates) if (!e.error) items.push({ label: e.label, kind: 'ate', ...e.ate });
    if (att) for (const e of att.estimates) if (!e.error) items.push({ label: `${e.label} (ATT)`, kind: 'att', ...e.ate });
    const cats = items.map((it) => it.label);
    const style = {
      naive: { name: 'Unadjusted', marker: { symbol: 'square-open', size: 9, color: T.muted, line: { width: 1.8 } }, color: T.muted },
      ate: { name: 'ATE', marker: { symbol: 'circle', size: 9, color: T.text }, color: T.text },
      att: { name: 'ATT', marker: { symbol: 'diamond', size: 10, color: T.accent }, color: T.accent },
    };
    const traces = [];
    for (const kind of ['naive', 'ate', 'att']) {
      const its = items.filter((it) => it.kind === kind);
      if (!its.length) continue;
      const s = style[kind];
      traces.push({
        type: 'scatter', mode: 'markers', x: its.map((it) => it.estimate), y: its.map((it) => it.label), name: s.name, marker: s.marker,
        error_x: { type: 'data', symmetric: false, array: its.map((it) => it.upper - it.estimate), arrayminus: its.map((it) => it.estimate - it.lower), color: s.color, thickness: 1.5, width: 5 },
        customdata: its.map((it) => [it.lower, it.upper]),
        hovertemplate: `%{y}: %{x:.5g}<br>${fmt(100 * (1 - ctx.alpha))}% interval %{customdata[0]:.5g} to %{customdata[1]:.5g}<extra></extra>`,
      });
    }
    const lo = Math.min(...items.map((it) => it.lower)), hi = Math.max(...items.map((it) => it.upper));
    const shapes = lo < 0 && hi > 0 ? [{ type: 'line', xref: 'x', yref: 'paper', x0: 0, x1: 0, y0: 0, y1: 1, line: { color: T.muted, width: 1, dash: 'dot' } }] : [];
    return ctx.plot(traces, {
      showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, shapes, margin: { l: 10, r: 14, t: 30, b: 42 },
      xaxis: { title: { text: `Effect on ${esc(res.y)}` }, zeroline: false }, yaxis: { type: 'category', categoryorder: 'array', categoryarray: cats.slice().reverse(), automargin: true },
    }, { width: W(470), height: Math.max(190, 72 + 26 * items.length), title: 'estimate comparison', select: false });
  }

  function estimatesOutline(ctx, res, ate, att, lab) {
    const ob = ctx.outline('Treatment Effect Estimates', { key: 'estimates', info: 'p:treatment:estimates', menu: () => estimatesMenu(ctx) });
    const n = res.naive;
    ob.add(estimatesTable(ctx, [{ label: 'Difference in Means (unadjusted)', ...n }, ...effectRows(ate.estimates)], `Average Treatment Effect (ATE): ${lab.treated} vs ${lab.control}`, 'ate'));
    for (const e of ate.estimates) if (e.error) ob.add(ctx.warn(`${e.label}: ${e.error}`));
    if (att) {
      ob.add(estimatesTable(ctx, effectRows(att.estimates), `Average Treatment Effect on the Treated (ATT): ${lab.treated} vs ${lab.control}`, 'att'));
      for (const e of att.estimates) if (e.error) ob.add(ctx.warn(`${e.label} (ATT): ${e.error}`));
      const noAtt = ate.estimates.filter((e) => !ATT_OK.includes(e.key)).map((e) => e.label);
      if (noAtt.length) ob.add(ctx.note(`statsmodels has no effect on the treated for ${noAtt.join(' and ')}.`));
    }
    if (ctx.opt('pom', true)) {
      const lv = fmt(100 * (1 - ctx.alpha));
      const rows = [{ label: 'Observed (unadjusted)', m0: n.mean_control, m1: n.mean_treated }];
      for (const e of ate.estimates) {
        if (!e.error) rows.push({ label: e.label, m0: e.pom0.estimate, se0: e.pom0.se, lo0: e.pom0.lower, hi0: e.pom0.upper, m1: e.pom1.estimate, se1: e.pom1.se, lo1: e.pom1.lower, hi1: e.pom1.upper });
      }
      ob.add(ctx.rt({
        columns: [{ key: 'label', label: 'Estimator', fmt: 'text' },
          { key: 'm0', label: `POM(${lab.control})` }, { key: 'se0', label: 'Std Error' }, { key: 'lo0', label: `Lower ${lv}%`, hidden: true }, { key: 'hi0', label: `Upper ${lv}%`, hidden: true },
          { key: 'm1', label: `POM(${lab.treated})` }, { key: 'se1', label: 'Std Error' }, { key: 'lo1', label: `Lower ${lv}%`, hidden: true }, { key: 'hi1', label: `Upper ${lv}%`, hidden: true }],
        rows,
      }, { caption: `Potential Outcome Means: the mean ${res.y} if every row had the level`, sortable: false, key: 'pom' }));
    }
    if (ctx.opt('forest', true)) ob.add(forestPlot(ctx, res, ate, att));
    const notes = [`The effect of ${lab.treated} against ${lab.control} on ${res.y}, averaged over all ${res.n} rows (ATE)${att ? ' and over the treated (ATT)' : ''}. The adjusted estimates are causal effects only when no confounder is missing from the covariates and the groups overlap (see Assumptions and Estimators).`];
    if (res.binary_y) notes.push(`${res.y} is 0/1: the effects are differences in the proportion with ${res.y} = 1, from linear outcome models.`);
    notes.push('Standard errors: statsmodels\' GMM of the propensity model, the outcome models and the effect together (robust, HC0), with z tests and normal intervals. The unadjusted difference has the unequal-variance standard error.');
    ob.add(...notes.map((s) => ctx.note(s)));
    if (ate.n_clip) ob.add(ctx.warn(`${ate.n_clip} row${ate.n_clip === 1 ? ' has a propensity score' : 's have propensity scores'} outside [0.01, 0.99]: inside its GMM statsmodels clips them there for IPW and AIPW (and to [0.001, 0.999] for AIPW (WLS) and IPW-RA), so those estimates differ a little from the formulas. Trimming at 0.01 or more avoids it.`));
    const moved = [...ate.estimates, ...(att ? att.estimates : [])].filter((e) => !e.error && e.gmm_gap > 1e-6);
    if (moved.length && !ate.n_clip) ob.add(ctx.note(`The GMM solution of ${moved.map((e) => e.label).join(', ')} differs from the closed form by up to ${fmt(Math.max(...moved.map((e) => e.gmm_gap)), { sig: 2 })} (relative).`));
    ob.add(ctx.code(ate.code));
    if (att) ob.add(ctx.code(att.code));
  }

  /* ---- the propensity score model and the overlap --------------------------------------- */
  function separationNote(ctx, res, lab) {
    const s = res.propensity.separation;
    const ov = res.overlap;
    if (s.state === 'none') {
      return ctx.note(`No separation: the propensity scores run from ${pct(Math.min(ov.treated.min, ov.control.min))} to ${pct(Math.max(ov.treated.max, ov.control.max))}; the fit converged${res.propensity.fit.iterations != null ? ` in ${res.propensity.fit.iterations} iterations` : ''}.`);
    }
    const parts = [];
    if (s.state === 'complete') parts.push('Complete separation: the covariates predict the treatment exactly, so there is no overlap, and these data cannot tell what the treatment does.');
    else parts.push('Quasi-complete separation: some rows have no counterparts in the other group, so the data cannot tell what the treatment does to them, and their weights are extreme.');
    if (s.n_certain) parts.push(`${s.n_certain} row${s.n_certain === 1 ? ' is' : 's are'} predicted with certainty (a propensity score within 1e−8 of 0 or 1).`);
    for (const x of s.levels) parts.push(`All ${x.n} rows with ${x.column} = ${x.level} are ${x.all === 'treated' ? lab.treated : lab.control}.`);
    if (!s.converged) parts.push('The fit did not converge: the estimates grow without bound.');
    parts.push('Take those rows out (exclude them, or trim), merge the level with another, or leave the covariate out of the treatment model.');
    return ctx.warn(parts.join(' '));
  }

  function propensityOutline(ctx, res, lab) {
    const P = res.propensity;
    const ob = ctx.outline('Propensity Score Model', { key: 'propensity', info: 'p:treatment:propensity', menu: () => [
      { label: 'Logit', checked: ctx.opt('link', 'logit') === 'logit', action: () => ctx.set('link', 'logit') },
      { label: 'Probit', checked: ctx.opt('link', 'logit') === 'probit', action: () => ctx.set('link', 'probit') },
      { separator: true },
      { label: 'Save Propensity Score', action: () => saveScores(ctx, 'ps') },
    ] });
    const f = P.fit;
    const whole = ctx.rt(P.whole, { caption: 'Whole Model Test', sortable: false, key: 'pswhole' });
    const stats = ctx.kv([['RSquare (U)', f.rsquare_u], ['AICc', f.aicc], ['BIC', f.bic], ['Area under ROC (c)', f.auc], ['Observations', f.n, 'int']]);
    ob.add(ctx.row(whole, stats));
    ob.add(ctx.rt(P.estimates, { caption: 'Parameter Estimates', sortable: false, key: 'psest' }));
    ob.add(separationNote(ctx, res, lab));
    ob.add(ctx.code(res.code));
  }

  function overlapMenu(ctx, res) {
    const trim = ctx.opt('trim', null);
    return [
      { label: 'Mirrored', checked: ctx.opt('mirror', true), action: () => ctx.set('mirror', true) },
      { label: 'Overlaid', checked: !ctx.opt('mirror', true), action: () => ctx.set('mirror', false) },
      ctx.check('Show Common Support', 'support', null, true),
      { label: 'Set Bin Width…', action: async () => { const v = await SM.ui.form({ title: 'Set Bin Width', fields: [{ key: 'w', label: 'Bin width of the propensity scores', type: 'number', value: ctx.opt('psBin', 0.05) }], validate: (x) => (x.w > 0.004 && x.w <= 0.5 ? null : 'a width between 0.005 and 0.5') }); if (v) ctx.set('psBin', v.w); } },
      { separator: true },
      { label: 'Trim Propensity Scores…', action: () => trimDialog(ctx) },
      trim ? { label: 'Remove Trimming', action: () => ctx.set('trim', null) } : null,
      trim && res.trim && res.trim.n_dropped ? { label: `Select Trimmed Rows (${res.trim.n_dropped})`, action: () => ctx.table.select(res.trim.rows) } : null,
      { label: `Select Rows Outside Common Support (${res.overlap.n_outside})`, disabled: !res.overlap.n_outside, action: () => ctx.table.select(res.overlap.rows_outside) },
    ];
  }

  async function trimDialog(ctx) {
    const v = await SM.ui.form({
      title: 'Trim Propensity Scores', info: 'p:treatment:overlap',
      lead: 'Leave out the rows whose propensity score (from the model on every row) is below ε or above 1 − ε, and fit everything again on the rest. The effect is then for the population where the groups overlap. 0 turns trimming off.',
      fields: [{ key: 'eps', label: 'ε', type: 'number', value: ctx.opt('trim', null) ?? 0.05 }],
      validate: (x) => (x.eps == null || (x.eps >= 0 && x.eps < 0.5) ? null : 'ε between 0 and 0.5'),
    });
    if (v) ctx.set('trim', v.eps > 0 ? v.eps : null);
  }

  function overlapOutline(ctx, res, lab) {
    const ob = ctx.outline('Overlap', { key: 'overlap', info: 'p:treatment:overlap', menu: () => overlapMenu(ctx, res) });
    const sc = res.scores;
    const ov = res.overlap;
    const size = ctx.opt('psBin', 0.05);
    const T = SM.util.themeColors();
    const shapes = [];
    if (ctx.opt('support', true) && ov.support) {
      const grey = T.dark ? 'rgba(200,190,180,0.10)' : 'rgba(90,80,70,0.09)';
      const [lo, hi] = ov.support;
      if (lo > 0) shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: 0, x1: lo, y0: 0, y1: 1, fillcolor: grey, line: { width: 0 }, layer: 'below' });
      if (hi < 1) shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: hi, x1: 1, y0: 0, y1: 1, fillcolor: grey, line: { width: 0 }, layer: 'below' });
    }
    if (res.trim) for (const x of [res.trim.eps, 1 - res.trim.eps]) shapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: x, x1: x, y0: 0, y1: 1, line: { color: T.accent, width: 1.3, dash: 'dash' } });
    const graph = groupHistogram(ctx, { values: sc.ps, t: sc.t, rows: sc.rows, bins: { start: 0, end: 1, size }, mirror: ctx.opt('mirror', true), lab, xTitle: `Propensity Score, P(${esc(lab.treated)})`, title: 'propensity score overlap', shapes });
    const kvs = [
      [`Treated (${res.n_treated})`, `${pct(ov.treated.min)} to ${pct(ov.treated.max)}, mean ${pct(ov.treated.mean)}`, 'text'],
      [`Control (${res.n_control})`, `${pct(ov.control.min)} to ${pct(ov.control.max)}, mean ${pct(ov.control.mean)}`, 'text'],
      ['Common support', ov.support ? `${pct(ov.support[0])} to ${pct(ov.support[1])}` : 'none', 'text'],
      ['Rows outside it', `${ov.n_outside} (${ov.n_outside_treated} treated, ${ov.n_outside_control} control)`, 'text'],
    ];
    if (res.trim) kvs.push(['Trimmed', `${res.trim.n_dropped} of ${res.trim.n_before} (${res.trim.n_dropped_treated} treated, ${res.trim.n_dropped_control} control) outside [${fmt(res.trim.eps)}, ${fmt(1 - res.trim.eps)}]`, 'text']);
    ob.add(ctx.row(graph, el('div', { class: 'sm-te-side' }, ctx.kv(kvs, { caption: 'Propensity Scores' }))));
    ob.add(ctx.note(`The treated above the axis, the controls ${ctx.opt('mirror', true) ? 'below' : 'overlaid'}. Where one group has scores the other lacks (shaded: outside the common support), its rows have no comparable counterparts, and the estimates there rest on the models' extrapolation. Click a bar to select its rows.`));
    if (res.trim) ob.add(ctx.note(`Trimming: the ${res.trim.n_dropped} rows with a score outside [${fmt(res.trim.eps)}, ${fmt(1 - res.trim.eps)}] in the model on all ${res.trim.n_before} rows are left out, and everything in the report is fitted again on the ${res.n} left (the scores here are that model's). The effects are then for the population with overlap, not for the whole sample.`));
  }

  /* ---- covariate balance ------------------------------------------------------------------------ */
  function lovePlot(ctx, balance, suffix, thr) {
    const T = SM.util.themeColors();
    const C = groupColors();
    let list = balance.filter((b) => b.smd != null || b[`smd${suffix}`] != null);
    if (ctx.opt('loveSort', true)) list = list.slice().sort((a, b) => Math.abs(b.smd ?? 0) - Math.abs(a.smd ?? 0));
    const terms = list.map((b) => esc(b.term));
    const lines = { type: 'scatter', mode: 'lines', x: [], y: [], line: { color: T.grid, width: 1.4 }, hoverinfo: 'skip', showlegend: false };
    const abs = (v) => (v == null ? null : Math.abs(v));
    list.forEach((b, i) => { lines.x.push(abs(b.smd), abs(b[`smd${suffix}`]), null); lines.y.push(terms[i], terms[i], null); });
    const what = suffix === '_att' ? 'ATT weights' : 'IPW weights';
    const traces = [lines,
      { type: 'scatter', mode: 'markers', x: list.map((b) => abs(b.smd)), y: terms, name: 'Unweighted', marker: { symbol: 'circle-open', size: 9, color: T.muted, line: { width: 1.8 } }, hovertemplate: '%{y}: |SMD| %{x:.3f}, unweighted<extra></extra>' },
      { type: 'scatter', mode: 'markers', x: list.map((b) => abs(b[`smd${suffix}`])), y: terms, name: `Weighted (${what})`, marker: { symbol: 'circle', size: 9, color: C.control }, hovertemplate: `%{y}: |SMD| %{x:.3f}, ${what}<extra></extra>` }];
    const maxX = Math.max(thr * 1.4, ...list.map((b) => Math.abs(b.smd ?? 0)), ...list.map((b) => Math.abs(b[`smd${suffix}`] ?? 0)));
    return ctx.plot(traces, {
      showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, margin: { l: 10, r: 14, t: 30, b: 42 },
      xaxis: { title: { text: '|Standardized Mean Difference|' }, range: [0, maxX * 1.06], zeroline: false },
      yaxis: { type: 'category', categoryorder: 'array', categoryarray: terms.slice().reverse(), automargin: true },
      shapes: [{ type: 'line', xref: 'x', yref: 'paper', x0: thr, x1: thr, y0: 0, y1: 1, line: { color: T.accent, width: 1.3, dash: 'dash' } }],
    }, { width: W(420), height: Math.max(200, 76 + 24 * list.length), title: 'Love plot', select: false });
  }

  function balanceOutline(ctx, res) {
    const bw = ctx.opt('balW', 'ate');
    const suffix = bw === 'att' ? '_att' : '_w';
    const thr = ctx.opt('smdThreshold', 0.1);
    const ob = ctx.outline('Covariate Balance', { key: 'balance', info: 'p:treatment:balance', menu: () => [
      ctx.check('Love Plot', 'love', null, true),
      ctx.check('Sort by Unweighted |SMD|', 'loveSort', null, true),
      { label: 'Weights', submenu: () => [
        { label: 'IPW (for the ATE)', checked: bw === 'ate', action: () => ctx.set('balW', 'ate') },
        { label: 'ATT (odds for the controls)', checked: bw === 'att', action: () => ctx.set('balW', 'att') },
      ] },
      { label: 'Set Threshold…', action: async () => { const v = await SM.ui.form({ title: 'Balance Threshold', fields: [{ key: 't', label: 'Largest |SMD| taken as balanced', type: 'number', value: thr }], validate: (x) => (x.t > 0 ? null : 'a number above 0') }); if (v) ctx.set('smdThreshold', v.t); } },
    ] });
    const rows = res.balance.map((b) => ({ term: b.term, mean_t: b.mean_t, mean_c: b.mean_c, smd: b.smd, vr: b.vr, mean_tx: b[`mean_t${suffix}`], mean_cx: b[`mean_c${suffix}`], smd_x: b[`smd${suffix}`], vr_x: b[`vr${suffix}`] }));
    const wl = bw === 'att' ? 'ATT Weighted' : 'Weighted';
    const table = ctx.rt({
      columns: [{ key: 'term', label: 'Covariate', fmt: 'text' },
        { key: 'mean_t', label: 'Mean Treated', hidden: true }, { key: 'mean_c', label: 'Mean Control', hidden: true },
        { key: 'smd', label: 'Std Mean Diff', digits: 3 }, { key: 'vr', label: 'Variance Ratio', digits: 3 },
        { key: 'mean_tx', label: `Mean Treated (${wl})`, hidden: true }, { key: 'mean_cx', label: `Mean Control (${wl})`, hidden: true },
        { key: 'smd_x', label: `Std Mean Diff (${wl})`, digits: 3 }, { key: 'vr_x', label: `Variance Ratio (${wl})`, digits: 3 }],
      rows,
    }, { caption: 'Balance', key: 'balance' });
    ob.add(ctx.opt('love', true) ? ctx.row(table, lovePlot(ctx, res.balance, suffix, thr)) : table);
    const over = (k) => res.balance.filter((b) => b[k] != null && Math.abs(b[k]) > thr).length;
    const n = res.balance.length;
    ob.add(ctx.note(`Treated minus control, in standard deviations: the standardized mean difference (SMD) is the difference in means over √((treated variance + control variance)/2), after weighting with weighted means and variances; for a level of a categorical covariate, of its 0/1 indicator, whose variance is p(1 − p). The variance ratio, treated variance over control variance, is for continuous covariates. ${over('smd')} of ${n} have |SMD| above ${fmt(thr)} before weighting, ${over(`smd${suffix}`)} after. Right click the table to show the means.`));
  }

  /* ---- the weights ------------------------------------------------------------------------------- */
  function weightsOutline(ctx, res, lab) {
    const wt = ctx.opt('wType', 'ate');
    const sc = res.scores;
    // JSON has no infinity: a weight of a row predicted with certainty comes as the text 'Infinity'
    const w = (wt === 'att' ? sc.w_att : sc.w_ate).map((v) => (typeof v === 'number' ? v : v === 'Infinity' ? Infinity : NaN));
    const WS = res.weights[wt === 'att' ? 'att' : 'ate'];
    const ob = ctx.outline('Weights', { key: 'weights', info: 'p:treatment:weights', menu: () => [
      { label: 'IPW (for the ATE)', checked: wt === 'ate', action: () => ctx.set('wType', 'ate') },
      { label: 'ATT (odds for the controls)', checked: wt === 'att', action: () => ctx.set('wType', 'att') },
      { separator: true },
      { label: 'Show Largest…', action: async () => { const v = await SM.ui.form({ title: 'Largest Weights', fields: [{ key: 'n', label: 'How many to list', type: 'number', value: ctx.opt('nLargest', 10) }] }); if (v && v.n > 0) ctx.set('nLargest', Math.min(200, Math.round(v.n))); } },
      { label: 'Save IPW Weight', action: () => saveScores(ctx, 'w_ate') },
      { label: 'Save ATT Weight', action: () => saveScores(ctx, 'w_att') },
    ] });
    const bins = SM.report.niceBins(w.filter(Number.isFinite));
    const graph = groupHistogram(ctx, { values: w, t: sc.t, rows: sc.rows, bins, mirror: ctx.opt('mirror', true), lab, xTitle: wt === 'att' ? 'ATT Weight' : 'IPW Weight', title: 'weights histogram' });
    const summ = ctx.rt({
      columns: [{ key: 'group', label: 'Group', fmt: 'text' }, { key: 'n', label: 'N', fmt: 'int' }, { key: 'sum', label: 'Sum' }, { key: 'mean', label: 'Mean' },
        { key: 'max', label: 'Maximum' }, { key: 'ess', label: 'Effective N', digits: 1 }],
      rows: [{ group: lab.treated, ...WS.treated }, { group: lab.control, ...WS.control }],
    }, { caption: wt === 'att' ? 'ATT Weights' : 'IPW Weights', sortable: false, key: 'wsum' });
    const N = ctx.opt('nLargest', 10);
    const yc = ctx.role('y');
    const order = w.map((_, k) => k).filter((k) => !Number.isNaN(w[k])).sort((a, b) => (w[b] === w[a] ? 0 : w[b] > w[a] ? 1 : -1)).slice(0, N);
    const largest = ctx.rt({
      columns: [{ key: 'row', label: 'Row', fmt: 'int' }, { key: 'group', label: 'Group', fmt: 'text' }, { key: 'ps', label: 'Propensity', sig: 4 }, { key: 'w', label: 'Weight', sig: 5 }, { key: 'y', label: res.y }],
      rows: order.map((k) => ({ row: sc.rows[k] + 1, group: sc.t[k] === 1 ? lab.treated : lab.control, ps: sc.ps[k], w: w[k], y: yc ? yc.values[sc.rows[k]] : null })),
    }, { caption: `The ${Math.min(N, order.length)} Largest Weights`, sortable: false, key: 'largest', onRow: (r, ev) => ctx.table.select([r.row - 1], ev && ev.shiftKey ? 'add' : (ev && (ev.metaKey || ev.ctrlKey)) ? 'toggle' : 'replace') });
    ob.add(ctx.row(graph, el('div', { class: 'sm-te-side' }, summ, largest)));
    const what = wt === 'att' ? 'For the effect on the treated a treated row weighs 1 and a control p/(1 − p), so that the controls stand for the treated.' : 'A treated row weighs 1/p and a control 1/(1 − p), p its propensity score, so that each group stands for the whole sample.';
    ob.add(ctx.note(`${what} The effective N, (Σw)²/Σw², is what the weighted group is worth in unweighted rows. ${WS.n_over_10 ? `${WS.n_over_10} row${WS.n_over_10 === 1 ? ' weighs' : 's weigh'} more than 10: rows like them are rare in their group, and IPW leans on them.` : 'No row weighs more than 10.'} Click a line of the list, or a bar, to select the rows.`));
  }

  function saveScores(ctx, key) {
    const te = ctx.te;
    if (!te) return;
    const sc = te.res.scores;
    const src = ctx.report.title + (ctx.byLabel ? ` ${ctx.byLabel}` : '');
    const spec = {
      ps: ['Propensity Score', `P(${te.lab.treated}) given ${te.res.covariates.join(', ')}: the ${te.res.propensity.link} propensity score, from ${src}`],
      w_ate: ['IPW Weight', `1/p for the treated, 1/(1 − p) for the controls (p the propensity score), from ${src}`],
      w_att: ['ATT Weight', `1 for the treated, p/(1 − p) for the controls, from ${src}`],
    }[key];
    ctx.saveColumn(spec[0], { rows: sc.rows, values: sc[key] }, { notes: spec[1] });
  }

  /* ---- the outcome models ---------------------------------------------------------------------------- */
  async function outcomeOutline(ctx, base, res, lab) {
    const om = await ctx.call('treatment.outcome_models', base);
    const ob = ctx.outline('Outcome Models', { key: 'outcome', info: 'p:treatment:outcome', menu: () => [{ label: 'Remove', action: () => ctx.set('outcomeModels', false) }] });
    if (om.error) { ob.add(ctx.warn(om.error)); return; }
    const boxes = [];
    for (const g of om.groups) {
      const sub = ctx.outline(`${g.group === 'treated' ? 'Treated' : 'Control'}: ${res.treatment} = ${g.level}`, { parent: ob, key: `outcome:${g.group}` });
      sub.add(ctx.kv([['RSquare', g.rsquare], ['Root Mean Square Error', g.rmse], [`Mean of ${res.y}`, g.mean_y], ['Observations', g.n, 'int']]),
        ctx.rt(g.estimates, { caption: 'Parameter Estimates', sortable: false, key: `outest:${g.group}` }));
      if (g.singular) sub.add(ctx.warn('The design is singular in this group: a covariate is constant here, and its estimate is not determined.'));
      boxes.push(sub.el);
    }
    ob.add(ctx.row(...boxes), ctx.note(`Least squares of ${res.y} on the outcome covariates in each group, as TreatmentEffect fits them (robust HC0 standard errors). RA averages the two models' predictions over all rows; AIPW corrects them with the weighted residuals.`), ctx.code(om.code));
  }

  /* ---- assumptions and estimators ---------------------------------------------------------------------- */
  function aboutOutline(ctx) {
    const ob = ctx.outline('Assumptions and Estimators', { key: 'about', info: 'p:treatment:assumptions', menu: () => [{ label: 'Remove', action: () => ctx.set('about', false) }] });
    const para = (head, text) => el('p', null, el('strong', { text: `${head}. ` }), text);
    ob.add(el('div', { class: 'sm-te-about' },
      para('What is estimated', 'The average treatment effect (ATE) is the difference the treatment would make to the outcome, averaged over everyone: the mean outcome if everyone were treated minus the mean if no one were (the potential-outcome means). The effect on the treated (ATT) averages over those who were treated.'),
      para('No unmeasured confounding', 'The covariates must hold everything that affects both who gets the treatment and the outcome. Then, among rows with the same covariates, who was treated is as good as chance, and the groups can be compared. No statistic can check this: it rests on knowing how the treatment came about. A confounder left out biases every estimator here.'),
      para('Overlap', 'Every kind of row must have had a real chance of either treatment: propensity scores away from 0 and 1. Where one group has no counterparts in the other, the estimate rests on extrapolation, and the weights grow large. The Overlap plot and the Weights show it; trimming keeps the rows where the groups overlap, and then the effect is for them.'),
      para('Also assumed', 'One row\'s treatment does not change another\'s outcome, and the treatment is one well-defined thing.'),
      para('How the estimators differ', 'IPW weights each row by the inverse of the probability of the treatment it got, so that each group looks like the whole sample; it needs the propensity model to be right, and large weights make it noisy. RA fits the outcome in each group and averages the predictions over everyone; it needs the outcome models to be right. AIPW adds to RA the residuals weighted by IPW: it is doubly robust, right when either the propensity model or the outcome models are right. IPW-RA fits the outcome models by least squares weighted with the IPW weights, and AIPW (WLS) is AIPW with such weighted models; both are doubly robust too. When the estimators agree, the result does not hang on one model; when they differ, look at the overlap and the balance.'),
      para('What statsmodels computes', 'TreatmentEffect, after Stata\'s teffects: the standard errors are from a GMM that stacks the propensity model\'s score, the outcome models\' normal equations and the effect\'s own equation, so they include the uncertainty of the estimated propensity scores (robust, HC0, no small-sample correction; z tests, normal intervals). Its limits: the outcome model is linear (for a 0/1 outcome a linear probability model); no case weights or clusters; the effect on the treated for IPW, RA and IPW-RA only; inside the GMM the propensity scores are clipped to [0.01, 0.99] (IPW, AIPW) or [0.001, 0.999] (AIPW (WLS), IPW-RA).'),
      para('Worked around here', 'statsmodels 0.14 takes the last six parameters as the propensity model\'s in the AIPW (WLS) and IPW-RA moment conditions, right only for a model with six; and its GMM differentiates with a fixed step of 1e−4, too coarse for a covariate in large units (the standard errors of IPW, AIPW (WLS) and IPW-RA come out wrong: several times too large with earnings in dollars). The page gives the moments the right slice and fits TreatmentEffect on the designs standardized (the same models and the same effects); the Python shows both.'),
      para('JMP', 'JMP has no platform for these estimators; JMP Pro\'s uplift models are a different thing (they predict who responds to a treatment).'),
    ));
  }

  /* ---- the launch dialog: the treated level --------------------------------------------------------------- */
  function launchExtra(api, spec) {
    const t = api.table;
    const sel = el('select', { 'aria-label': 'Treated level' });
    let want = spec && spec.options ? spec.options.treated : undefined;
    const col = () => { const id = (api.state.treatment || [])[0]; return id ? t.col(id) : null; };
    const fill = () => {
      const c = col();
      const lv = c ? t.levels(c) : [];
      const was = sel.value !== '' ? sel.value : (want != null ? String(want) : null);
      sel.replaceChildren(...(lv.length ? lv.map((v) => el('option', { value: String(v), text: SM.grid.cellText(c, v) })) : [el('option', { value: '', text: '(cast the Treatment first)' })]));
      sel.disabled = !lv.length;
      const pick = lv.find((v) => String(v) === was);
      const use = pick !== undefined ? pick : lv[lv.length - 1];
      if (use !== undefined) sel.value = String(use);
      if (c && lv.length !== 2) api.message(`${c.name} has ${lv.length} level${lv.length === 1 ? '' : 's'}; the Treatment takes a column with two.`);
    };
    sel.addEventListener('change', () => { want = sel.value; });
    api.onRolesChange(fill);
    fill();
    const box = el('div', { class: 'sm-te-launch' }, el('label', null, el('span', { text: 'Treated Level' }), sel), slot('p:treatment'));
    return {
      el: box,
      read() {
        const c = col();
        if (!c || sel.value === '') return { options: { treated: null } };
        const v = t.levels(c).find((x) => String(x) === sel.value);
        return { options: { treated: v === undefined ? null : v } };
      },
      recall(saved) { want = saved && saved.options ? saved.options.treated : undefined; sel.value = ''; fill(); },
    };
  }

  function validate(spec, table) {
    const cols = (k) => (spec.roles[k] || []).map((id) => table.col(id)).filter(Boolean);
    const [y] = cols('y');
    const [tr] = cols('treatment');
    const cov = [...cols('outcome'), ...cols('covariates')];
    if (y === tr) return 'The outcome and the treatment must be two columns.';
    const lv = table.levels(tr);
    if (lv.length !== 2) return `Treatment takes a column with two levels; ${tr.name} has ${lv.length}.`;
    if (!cov.length) return 'Give covariates: Outcome Covariates, Treatment Covariates, or both (the treatment model takes the outcome covariates when it has none of its own).';
    if (cov.includes(y)) return `${y.name} is the outcome: take it out of the covariates.`;
    if (cov.includes(tr)) return `${tr.name} is the treatment: take it out of the covariates.`;
    return null;
  }

  /* ---- the example table: a simulated job-training programme ------------------------------------------------ */
  /* Who takes part depends on age, education, prior earnings and region (a
     logit); earnings a year later depend on them too (with a square in age
     and a floor at zero), and the programme adds 2000 + 250 (12 − education)
     to a person's earnings: more for the less educated, who also take part
     more often, so the effect on the treated is larger than the average
     effect. Both potential outcomes are drawn for everyone, so the true
     effects in these 1000 people are known exactly. */
  function simulateProgram() {
    const r = SM.util.rng('program-6');
    const n = 1000;
    const REG = ['North', 'South', 'East', 'West'];
    const take = { North: 0, South: 0.45, East: -0.35, West: 0.15 };
    const pay = { North: 0, South: -1800, East: 900, West: 1400 };
    const c = { id: [], age: [], education: [], prior: [], region: [], program: [], earnings: [], employed: [] };
    let tau = 0, tauT = 0, emp = 0, empT = 0, nT = 0;
    for (let i = 0; i < n; i++) {
      const age = Math.max(18, Math.min(60, Math.round(r.normal(34, 9))));
      const educ = Math.max(8, Math.min(18, Math.round(r.normal(12, 2.2))));
      const region = REG[Math.floor(r.u() * 4)];
      const out = r.u() < 0.25 - 0.02 * (educ - 12);
      const prior = out ? 0 : Math.round(Math.exp(r.normal(9.75 + 0.06 * (educ - 12) + 0.008 * (age - 34), 0.45)) / 10) * 10;
      const lin = -0.6 - 0.045 * (age - 34) - 0.28 * (educ - 12) - 0.03 * (prior / 1000 - 14) + take[region];
      const T = r.u() < 1 / (1 + Math.exp(-lin)) ? 1 : 0;
      const base = 7000 + 0.55 * prior + 650 * (educ - 12) + 110 * (age - 34) - 6 * (age - 34) ** 2 + pay[region];
      const e = r.normal(0, 3800);
      const y0 = Math.round(Math.max(0, base + e)), y1 = Math.round(Math.max(0, base + 2000 + 250 * (12 - educ) + e));
      const lp = 0.3 + 0.18 * (educ - 12) + 0.00004 * (prior - 14000) - 0.02 * (age - 34);
      const u = r.u();
      const e0 = u < 1 / (1 + Math.exp(-lp)) ? 1 : 0, e1 = u < 1 / (1 + Math.exp(-(lp + 0.55))) ? 1 : 0;
      tau += y1 - y0; emp += e1 - e0;
      if (T) { tauT += y1 - y0; empT += e1 - e0; nT++; }
      c.id.push(`P${String(i + 1).padStart(4, '0')}`); c.age.push(age); c.education.push(educ); c.prior.push(prior); c.region.push(region);
      c.program.push(T); c.earnings.push(T ? y1 : y0); c.employed.push(T ? e1 : e0);
    }
    return { c, truth: { ate: tau / n, att: tauT / nT, ateEmp: emp / n, attEmp: empT / nT, nT } };
  }

  const SIM = simulateProgram();
  const TRUTH = SIM.truth;
  SM.io.addExample('program', {
    label: 'Job training (1000 people): program, earnings',
    about: `Simulated observational study: people chose to join a job-training program, more often the young, the less educated, those who earned little the year before, and in some regions more than others. Earnings and employment a year later. The true effect of the program on earnings is ${fmt(Math.round(TRUTH.ate))} on average (ATE; 2000 + 250 × (12 − education) a person, before the floor at zero) and ${fmt(Math.round(TRUTH.att))} for the ${TRUTH.nT} who joined (ATT); on employment ${fmt(TRUTH.ateEmp, { sig: 3 })} (ATT ${fmt(TRUTH.attEmp, { sig: 3 })}). The plain difference in means is far off. For Treatment Effects.`,
    truth: TRUTH,
    make() {
      const { c } = simulateProgram();
      return new SM.Table({ name: 'Job training', source: 'simulated', columns: [
        { name: 'id', dataType: 'character', values: c.id, role: 'label' },
        { name: 'age', dataType: 'numeric', values: c.age, notes: 'years, at the start of the program' },
        { name: 'education', dataType: 'numeric', values: c.education, notes: 'years of schooling' },
        { name: 'prior earnings', dataType: 'numeric', values: c.prior, notes: 'earnings in the year before the program (0: out of work)' },
        { name: 'region', dataType: 'character', values: c.region, valueOrder: ['North', 'South', 'East', 'West'] },
        { name: 'program', dataType: 'numeric', modelingType: 'nominal', values: c.program, notes: '1: joined the job-training program, 0: did not' },
        { name: 'earnings', dataType: 'numeric', values: c.earnings, notes: 'earnings in the year after the program' },
        { name: 'employed', dataType: 'numeric', modelingType: 'nominal', values: c.employed, notes: '1: employed a year after the program' },
      ] });
    },
  });

  /* ---- Help ------------------------------------------------------------------------------------------------------ */
  const TOPICS = {
    'p:treatment': {
      kicker: 'Analyze > Specialized Modeling', title: 'Treatment Effects',
      lead: 'The effect of a two-level treatment (a program, an exposure, a policy) on an outcome, from observational data where the treated and the controls differ: statsmodels\' TreatmentEffect with five estimators, the propensity score model, the overlap of its scores, and the balance of the covariates.',
      sections: [
        { heading: 'Roles', choices: [['Y, Outcome', 'A continuous outcome, or a 0/1 one (the effects are then differences in proportions).'], ['Treatment', 'A column with two levels. Choose the treated level under the roles; the other is the control.'],
          ['Outcome Covariates', 'The columns of the outcome models: least squares in each group (RA, AIPW, IPW-RA).'], ['Treatment Covariates', 'The columns of the propensity score model (logit or probit). Empty: the outcome covariates.'], ['By', 'A separate analysis for each level.']] },
        { heading: 'The red triangle', text: 'Choose the estimators, the effect on the treated and the potential-outcome means; the treatment model (logit or probit) and the treated level; trim the propensity scores; show or hide the parts of the report; save the propensity scores and the weights as columns.' },
        { heading: 'Reading it', text: 'Look at the overlap and the balance first: if the groups do not overlap, or the weighting leaves covariates out of balance, no estimator can be trusted. Then compare the estimators; the unadjusted difference in means shows how much the adjustment matters.' },
      ],
      more: MORE,
    },
    'p:treatment:estimates': {
      kicker: 'Treatment Effects', title: 'Treatment Effect Estimates',
      lead: 'The average treatment effect (ATE) by each estimator with its standard error, z test and confidence interval, and the unadjusted difference in means for contrast.',
      sections: [
        { choices: [['IPW', 'inverse probability weighting: the weighted means of the two groups, weights 1/p and 1/(1 − p)'], ['AIPW', 'the outcome models\' predictions corrected by the IPW-weighted residuals (doubly robust)'],
          ['AIPW (WLS)', 'AIPW with outcome models fitted by weighted least squares'], ['RA', 'regression adjustment: the two outcome models\' predictions averaged over all rows'],
          ['IPW-RA', 'regression adjustment with IPW-weighted outcome models (doubly robust)'], ['ATT', 'the effect on the treated: averaged over the treated rows (IPW, RA and IPW-RA)'],
          ['Potential Outcome Means', 'the mean outcome if every row had been treated, and if none had']] },
        { heading: 'Standard errors', text: 'statsmodels\' GMM of the propensity model, the outcome models and the effect together: robust (HC0), and they include the estimation of the propensity scores.' },
        { heading: 'Estimate Comparison', text: 'The estimates with their intervals. When they agree, the result does not hang on one model.' },
      ],
      more: MORE,
    },
    'p:treatment:propensity': {
      kicker: 'Treatment Effects', title: 'Propensity Score Model',
      lead: 'A logit (or probit) of the treatment on the treatment covariates: each row\'s probability of the treatment given its covariates, its propensity score. The tables are JMP\'s Nominal Logistic: effect coding, Wald ChiSquare, the Whole Model Test against the model without covariates.',
      sections: [
        { heading: 'Separation', text: 'When covariates predict the treatment with certainty (a level with only treated rows, say), the likelihood has no maximum: the estimates grow without bound and the scores reach 0 or 1. Those rows have no counterparts in the other group, and the data cannot say what the treatment does to them.' },
        { choices: [['RSquare (U)', 'the share of the uncertainty the covariates explain (McFadden)'], ['Area under ROC (c)', 'how well the scores tell the groups apart: 0.5 not at all, near 1 means little overlap']] },
      ],
      more: MORE,
    },
    'p:treatment:overlap': {
      kicker: 'Treatment Effects', title: 'Overlap',
      lead: 'The propensity scores of the treated (above) and of the controls (below, or overlaid). Where one group has scores the other lacks, its rows have no comparable counterparts.',
      sections: [{ choices: [['Common support', 'from the larger of the two groups\' smallest scores to the smaller of their largest; outside it shaded'],
        ['Trim Propensity Scores', 'leaves out the rows with a score outside [ε, 1 − ε] (0.05 and 0.1 are usual) in the model on all rows, and fits everything again on the rest: the effect is then for the population with overlap'],
        ['Linking', 'click a bar to select its rows; Select Rows Outside Common Support selects those']] }],
      more: MORE,
    },
    'p:treatment:balance': {
      kicker: 'Treatment Effects', title: 'Covariate Balance',
      lead: 'How different the groups are in each covariate, before and after weighting: the standardized mean difference, (treated mean − control mean)/√((treated variance + control variance)/2), and the variance ratio, treated variance over control variance.',
      sections: [
        { text: 'After weighting the means and variances are weighted (Austin and Stuart\'s definitions). An |SMD| below 0.1 is the usual mark of balance, and a variance ratio between 0.5 and 2. For a level of a categorical covariate the SMD is of its 0/1 indicator, whose variance is p(1 − p).' },
        { heading: 'Love plot', text: 'The |SMD| of each covariate unweighted (open) and weighted (filled), with a line at the threshold (Set Threshold changes it).' },
      ],
      more: MORE,
    },
    'p:treatment:weights': {
      kicker: 'Treatment Effects', title: 'Weights',
      lead: 'The IPW weights: 1/p for a treated row and 1/(1 − p) for a control, so that each group stands for the whole sample; for the effect on the treated 1 and p/(1 − p).',
      sections: [{ choices: [['Effective N', '(Σw)²/Σw²: how many unweighted rows the weighted group is worth'], ['Largest weights', 'the rows that count most; click one to select it in the table'], ['Save', 'the weights as a column, for weighted analyses elsewhere']] }],
      more: MORE,
    },
    'p:treatment:outcome': {
      kicker: 'Treatment Effects', title: 'Outcome Models',
      lead: 'The least squares fit of the outcome on the outcome covariates in each group, as TreatmentEffect makes them (robust HC0 standard errors). RA averages their predictions over all rows; AIPW adds the IPW-weighted residuals.',
      more: MORE,
    },
    'p:treatment:assumptions': {
      kicker: 'Treatment Effects', title: 'Assumptions and Estimators',
      lead: 'What the estimates need to be causal effects (no unmeasured confounding, overlap), how the estimators differ, and what statsmodels computes and does not.',
      more: MORE,
    },
  };

  /* ---- the platform -------------------------------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'treatment', label: 'Treatment Effects', menu: 'Analyze/Specialized Modeling', order: 70, info: 'p:treatment', topics: TOPICS,
    about: 'The effect of a two-level treatment on an outcome from observational data (statsmodels\' TreatmentEffect): the average treatment effect and the potential-outcome means by inverse probability weighting (IPW), augmented IPW (doubly robust; also with weighted outcome models), regression adjustment and IPW regression adjustment, and the effect on the treated, with GMM standard errors that include the estimation of the propensity scores; the propensity score model (logit or probit) with a check for separation, the overlap of the scores with trimming, the covariate balance before and after weighting with a Love plot, the weights, and the outcome models. JMP has no such platform.',
    uses: ['statsmodels.treatment.treatment_effects.TreatmentEffect: ipw, aipw, aipw_wls, ra, ipw_ra', 'statsmodels.discrete.discrete_model.Logit, Probit', 'statsmodels.regression.linear_model.OLS (HC0)', 'statsmodels.sandbox.regression.gmm.GMM', 'statsmodels.stats.weightstats.CompareMeans', 'patsy'],
    launch: {
      lead: 'The effect of a two-level treatment on an outcome, from observational data: a propensity score model for the treatment, an outcome model in each group, and five estimators that combine them.',
      roles: [
        { key: 'y', label: 'Y, Outcome', min: 1, max: 1, numeric: true, hint: 'required: continuous or 0/1' },
        { key: 'treatment', label: 'Treatment', min: 1, max: 1, hint: 'required: two levels' },
        { key: 'outcome', label: 'Outcome Covariates', hint: 'the outcome models' },
        { key: 'covariates', label: 'Treatment Covariates', hint: 'the propensity model; empty: as the outcome' },
        { key: 'by', label: 'By', hint: 'optional' },
      ],
      options: [{ key: 'link', label: 'Treatment Model', type: 'select', value: 'logit', choices: [['logit', 'Logit'], ['probit', 'Probit']] }],
      extra: launchExtra,
      validate,
    },
    title(spec, table) {
      const name = (k) => { const id = ((spec.roles || {})[k] || [])[0]; const c = id && table ? table.col(id) : null; return c ? c.name : null; };
      return name('treatment') && name('y') ? `Treatment Effects of ${name('treatment')} on ${name('y')}` : 'Treatment Effects';
    },
    triangle(ctx) {
      const tcol = ctx.role('treatment');
      const lv = tcol ? ctx.table.levels(tcol) : [];
      const cur = treatedLevel(ctx);
      return [
        ...estimatesMenu(ctx),
        { separator: true },
        { label: 'Treatment Model', submenu: () => [['logit', 'Logit'], ['probit', 'Probit']].map(([k, l]) => ({ label: l, checked: ctx.opt('link', 'logit') === k, action: () => ctx.set('link', k) })) },
        { label: 'Treated Level', disabled: lv.length !== 2, submenu: () => lv.map((v) => ({ label: SM.grid.cellText(tcol, v), checked: String(v) === String(cur), action: () => ctx.set('treated', v) })) },
        { label: 'Trim Propensity Scores…', action: () => trimDialog(ctx) },
        { separator: true },
        ctx.check('Propensity Score Model', 'psModel', null, true),
        ctx.check('Overlap', 'overlap', null, true),
        ctx.check('Covariate Balance', 'balance', null, true),
        ctx.check('Weights', 'weights', null, true),
        ctx.check('Outcome Models', 'outcomeModels', null, false),
        ctx.check('Assumptions and Estimators', 'about', null, true),
        { separator: true },
        { label: 'Save Columns', disabled: !ctx.te, submenu: () => [
          { label: 'Propensity Score', action: () => saveScores(ctx, 'ps') },
          { label: 'IPW Weight', action: () => saveScores(ctx, 'w_ate') },
          { label: 'ATT Weight', action: () => saveScores(ctx, 'w_att') },
        ] },
        { label: 'Model Dialog', action: () => ctx.report.relaunch() },
      ];
    },
    async render(ctx) {
      ctx.te = null;
      const base = payloadOf(ctx);
      const res = await ctx.call('treatment.fit', base);
      if (res.error) { ctx.container.append(ctx.warn(res.error)); return; }
      const lab = { treated: `${res.treatment} = ${res.treated_text}`, control: `${res.treatment} = ${res.control_text}` };
      ctx.te = { res, lab };
      const estimators = ctx.opt('estimators', EST_KEYS).filter((k) => EST_KEYS.includes(k));
      const attKeys = estimators.filter((k) => ATT_OK.includes(k));
      const wantAtt = ctx.opt('att', true) && attKeys.length > 0;
      const [ate, att] = await Promise.all([
        ctx.call('treatment.estimates', { ...base, estimators }),
        wantAtt ? ctx.call('treatment.estimates', { ...base, estimators: attKeys, effect_group: 1 }) : Promise.resolve(null),
      ]);
      summary(ctx, res, lab);
      if (ate.error) ctx.container.append(ctx.warn(ate.error));
      else estimatesOutline(ctx, res, ate, att && !att.error ? att : null, lab);
      if (ctx.opt('psModel', true)) propensityOutline(ctx, res, lab);
      if (ctx.opt('overlap', true)) overlapOutline(ctx, res, lab);
      if (ctx.opt('balance', true)) balanceOutline(ctx, res);
      if (ctx.opt('weights', true)) weightsOutline(ctx, res, lab);
      if (ctx.opt('outcomeModels', false)) await outcomeOutline(ctx, base, res, lab);
      if (ctx.opt('about', true)) aboutOutline(ctx);
    },
  });
}(typeof self !== 'undefined' ? self : this));
