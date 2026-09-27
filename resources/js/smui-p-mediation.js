/* ==========================================================================
   SMUI.HTML: ANALYZE > SPECIALIZED MODELING > MEDIATION

   Causal mediation analysis: how much of a treatment's effect on an
   outcome passes through a mediator. statsmodels' Mediation
   (resources/py/smui/mediation.py) fits a mediator model and an outcome
   model (least squares, or logistic, probit or Poisson GLMs) and simulates
   the average causal mediation effect (ACME, the indirect effect) and the
   average direct effect (ADE) by the quasi-Bayesian draws of Imai, Keele
   and Tingley or by the bootstrap. The report: a path diagram with the
   models' coefficients on the arrows and the effects beside them, the
   Mediation Effects table with a forest-style plot, the simulated
   distributions, the two models' parameter estimates, and notes on what
   the effects mean and what they assume. JMP has no causal mediation
   analysis (its Structural Equation Models fit linear mediation); the
   report is laid out as JMP lays out its model reports.

   It brings its own example table, File > Examples > Coaching study: 600
   simulated people with a known indirect effect.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;

  const MORE = { label: 'Mediation', id: 'help-p-mediation' };
  const MODELS = [['ols', 'Least Squares'], ['logit', 'Logistic'], ['probit', 'Probit'], ['poisson', 'Poisson']];
  const MODEL_LABEL = { ols: 'Least Squares', logit: 'Logistic (logit)', probit: 'Probit', poisson: 'Poisson (log)' };
  const COEF_SCALE = { ols: '', logit: ' (log odds)', probit: ' (probit)', poisson: ' (log)' };
  const METHODS = [['parametric', 'Parametric (quasi-Bayesian)'], ['bootstrap', 'Nonparametric bootstrap']];
  const METHOD_LABEL = Object.fromEntries(METHODS);
  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));
  const esc = (s) => SM.report.plotlyText(s);
  const slot = (key) => (typeof KvotInfo !== 'undefined' ? KvotInfo.slot(key) : null);
  const sig = (x) => fmt(x, { sig: 4 });

  /* The indirect path (ACME) and the direct path (ADE): blue and rose,
     apart from each other, from the selection's orange and from the
     surfaces in both themes (checked with the dataviz skill's validator);
     the total takes the text colour and a diamond. */
  function colors() {
    const T = SM.util.themeColors();
    return T.dark ? { acme: '#4d8ad6', ade: '#d1528f', text: T.text, muted: T.muted, grid: T.grid, surface: T.surface, dark: true }
      : { acme: '#2e6fba', ade: '#b8406e', text: T.text, muted: T.muted, grid: T.grid, surface: T.surface, dark: false };
  }

  /* ---- the treatment's two values ------------------------------------------------------ */
  /* JMP's quantile (Weibull, p(n + 1)) of a sorted array. */
  function quantile(sorted, p) {
    const n = sorted.length;
    if (!n) return NaN;
    const h = p * (n + 1);
    if (h <= 1) return sorted[0];
    if (h >= n) return sorted[n - 1];
    const lo = Math.floor(h);
    return sorted[lo - 1] + (h - lo) * (sorted[lo] - sorted[lo - 1]);
  }

  /* The default contrast of a continuous treatment: its two values when it
     has two, else its quartiles. */
  function defaultContrast(c) {
    const v = c.values.filter((x) => typeof x === 'number' && Number.isFinite(x)).sort((a, b) => a - b);
    const u = [...new Set(v)];
    if (u.length === 2) return [u[0], u[1]];
    if (!v.length) return [0, 1];
    return [quantile(v, 0.25), quantile(v, 0.75)];
  }

  function levelOf(table, c, want, fallback) {
    const lv = table.levels(c);
    const hit = want == null ? undefined : lv.find((v) => String(v) === String(want));
    return hit !== undefined ? hit : fallback;
  }

  function payloadOf(ctx) {
    return {
      y: ctx.name('y'), treatment: ctx.name('treatment'), mediator: ctx.name('mediator'), covariates: ctx.names('covariates'),
      outcome_model: ctx.opt('outcomeModel', null), mediator_model: ctx.opt('mediatorModel', null), interaction: !!ctx.opt('interaction', false),
      control: ctx.opt('control', null), treated: ctx.opt('treated', null),
      n_rep: ctx.opt('nRep', 1000), method: ctx.opt('method', 'parametric'), seed: ctx.opt('seed', 1), alpha: ctx.alpha,
    };
  }

  const treatText = (ctx, res, v) => (res.t_kind === 'categorical' ? SM.grid.cellText(ctx.role('treatment'), v) : fmt(v));

  /* ---- the summary ----------------------------------------------------------------------- */
  function summary(ctx, res) {
    const secs = res.cached ? '' : `, ${fmt(res.seconds, { sig: 2 })} s`;
    const pairs = [
      ['Outcome', `${res.y}: ${MODEL_LABEL[res.outcome_model]}`, 'text'],
      ['Mediator', `${res.mediator}: ${MODEL_LABEL[res.mediator_model]}`, 'text'],
      ['Treatment', `${res.treatment}: ${treatText(ctx, res, res.treated)} (treated) against ${treatText(ctx, res, res.control)} (control)${res.t_kind === 'continuous' ? ', a continuous column' : ''}`, 'text'],
      ['Covariates', res.covariates.length ? `${res.covariates.join(', ')} (in both models)` : 'none', 'text'],
      res.interaction ? ['Interaction', `${res.treatment} × ${res.mediator} in the outcome model`, 'text'] : null,
      ['Rows', res.n_missing ? `${res.n} (${res.n_missing} with a missing value left out)` : String(res.n), 'text'],
      res.t_kind === 'categorical' ? ['Treated rows, control rows', `${res.n_treated}, ${res.n_control}`, 'text'] : null,
      ['Simulations', `${res.n_rep}, ${res.method === 'bootstrap' ? 'nonparametric bootstrap' : 'parametric (quasi-Bayesian)'}, seed ${res.seed}${secs}`, 'text'],
    ];
    ctx.container.append(el('div', { class: 'sm-med-summary' }, ctx.kv(pairs)));
  }

  /* ---- the path diagram: Plotly shapes and annotations --------------------------------- */
  function edge(from, to, w, h, pad = 0.12) {
    const dx = to.x - from.x, dy = to.y - from.y;
    const t = Math.min(dx ? (w / 2 + pad) / Math.abs(dx) : Infinity, dy ? (h / 2 + pad) / Math.abs(dy) : Infinity);
    return { x: from.x + t * dx, y: from.y + t * dy };
  }

  function effectOf(res, name) { return res.effects.rows.find((r) => r.effect === name); }
  const ci = (e) => `${sig(e.lower)} to ${sig(e.upper)}`;

  /* The three boxes in a triangle: the treatment and the outcome below, the
     mediator above; the coefficients on the arrows, the effects inside and
     under it. Narrower than 470 pixels (a phone), the boxes widen and the
     longer labels move under the triangle. */
  function pathDiagram(ctx, res) {
    const C = colors();
    const width = W(620);
    const compact = width < 470;
    const bw = compact ? 3.9 : 2.7, bh = compact ? 1.25 : 1.05;
    const T = { x: compact ? 2.15 : 1.55, y: 0.95 }, M = { x: 5, y: 4.25 }, Y = { x: compact ? 7.85 : 8.45, y: 0.95 };
    const f = compact ? { node: 10.5, sub: 9, lab: 9.5, eff: 10 } : { node: 11.5, sub: 10, lab: 11, eff: 11 };
    const box = (p, fill) => ({ type: 'rect', xref: 'x', yref: 'y', x0: p.x - bw / 2, x1: p.x + bw / 2, y0: p.y - bh / 2, y1: p.y + bh / 2, line: { color: C.text, width: 1.2 }, fillcolor: fill, layer: 'below' });
    const fill = C.dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.025)';
    const tLabel = res.t_kind === 'categorical' ? `${treatText(ctx, res, res.treated)} vs ${treatText(ctx, res, res.control)}` : `${fmt(res.treated)} vs ${fmt(res.control)}`;
    const node = (p, role, name, sub) => ({ x: p.x, y: p.y, xref: 'x', yref: 'y', showarrow: false, align: 'center', font: { size: f.node, color: C.text },
      text: `<b>${role}</b><br>${esc(name)}${sub ? `<br><span style="font-size:${f.sub}px">${esc(sub)}</span>` : ''}` });
    const arrow = (a, b, color) => {
      const st = edge(a, b, bw, bh), e = edge(b, a, bw, bh);
      return { x: e.x, y: e.y, ax: st.x, ay: st.y, xref: 'x', yref: 'y', axref: 'x', ayref: 'y', showarrow: true, arrowhead: 2, arrowsize: 1.1, arrowwidth: 2, arrowcolor: color, text: '' };
    };
    const P = res.paths;
    const mScale = COEF_SCALE[res.mediator_model], oScale = COEF_SCALE[res.outcome_model];
    const lab = (x, y, text, anchor = 'center', size = f.lab) => ({ x, y, xref: 'x', yref: 'y', showarrow: false, xanchor: anchor, align: anchor === 'center' ? 'center' : anchor, font: { size, color: C.text }, text });
    const acme = effectOf(res, 'ACME (average)'), ade = effectOf(res, 'ADE (average)'), tot = effectOf(res, 'Total Effect'), prop = effectOf(res, 'Prop. Mediated (average)');
    const lv = fmt(100 * (1 - ctx.alpha));
    const se = (e) => (compact ? '' : `<br>(SE ${sig(e.se)})`);
    const aText = `a = ${sig(P.a.estimate)}${mScale}${se(P.a)}`;
    const bText = P.i ? `b = ${sig(P.b.estimate)} at control,<br>${sig(P.b.estimate + P.i.estimate)} at treated${oScale}` : `b = ${sig(P.b.estimate)}${oScale}${se(P.b)}`;
    const cText = P.i ? `c′ = ${sig(P.c.estimate)} at ${esc(res.mediator)} = 0${compact ? ', ' : '<br>'}T×M ${sig(P.i.estimate)}${oScale}` : `c′ = ${sig(P.c.estimate)}${oScale} (SE ${sig(P.c.se)})`;
    const mediated = `${fmt(100 * prop.estimate, { sig: 3 })}% mediated`;
    const annotations = [
      arrow(T, M, C.acme), arrow(M, Y, C.acme), arrow(T, Y, C.ade),
      node(T, 'Treatment', res.treatment, tLabel), node(M, 'Mediator', res.mediator, MODEL_LABEL[res.mediator_model]), node(Y, 'Outcome', res.y, MODEL_LABEL[res.outcome_model]),
    ];
    let yr;
    if (compact) {
      annotations.push(
        lab(3.3, 2.65, aText, 'right'), lab(6.7, 2.65, bText, 'left'),
        lab(5, 2.3, `<b>ACME ${sig(acme.estimate)}</b><br>${ci(acme)}`, 'center', f.eff),
        lab(5, 0.0, cText), lab(5, -0.6, `<b>ADE ${sig(ade.estimate)}</b>  ${ci(ade)}`, 'center', f.eff),
        lab(5, -1.2, `Total ${sig(tot.estimate)}, ${mediated}`));
      yr = [-1.65, 5.6];
    } else {
      annotations.push(
        lab(2.9, 2.85, aText, 'right'), lab(7.1, 2.85, bText, 'left'),
        lab(5, P.i ? 1.45 : 1.28, cText, 'center', 10.5),
        lab(5, 2.45, `<b>ACME ${sig(acme.estimate)}</b><br>${lv}%: ${ci(acme)}`, 'center', f.eff),
        lab(5, 0.1, `<b>ADE ${sig(ade.estimate)}</b>  ${lv}%: ${ci(ade)}`, 'center', f.eff),
        lab(5, -0.42, `Total effect ${sig(tot.estimate)} (${ci(tot)}), ${mediated}`, 'center', 10.5));
      yr = [-0.75, 5.6];
    }
    if (res.covariates.length) {
      const adj = `Adjusted for ${res.covariates.join(', ')}`;
      annotations.push(lab(0.05, 5.4, esc(compact && adj.length > 44 ? `Adjusted for ${res.covariates.length} covariates` : adj), 'left', compact ? 9 : 10));
    }
    const hidden = { visible: false, fixedrange: true, showgrid: false, zeroline: false };
    const layout = {
      xaxis: { ...hidden, range: [-0.1, 10.1] }, yaxis: { ...hidden, range: yr },
      shapes: [box(T, fill), box(M, fill), box(Y, fill)], annotations, margin: { l: 6, r: 6, t: 6, b: 6 }, dragmode: false, hovermode: false,
    };
    // An invisible trace keeps the axes; the diagram is shapes and annotations.
    return ctx.plot([{ type: 'scatter', mode: 'markers', x: [0, 10], y: [0, 5], marker: { size: 1, opacity: 0 }, hoverinfo: 'skip', showlegend: false }], layout,
      { width, height: compact ? 380 : 330, title: 'mediation path diagram', select: false, config: { displayModeBar: false } });
  }

  function diagramOutline(ctx, res) {
    const ob = ctx.outline('Path Diagram', { key: 'diagram', info: 'p:mediation:diagram', menu: () => [{ label: 'Remove', action: () => ctx.set('diagram', false) }] });
    ob.add(pathDiagram(ctx, res));
    const P = res.paths;
    const notes = [`The arrows carry the models' coefficients: a, the treatment's effect on ${res.mediator} in the mediator model; b, the effect of ${res.mediator} on ${res.y} in the outcome model; c′, the treatment's own effect in the outcome model. Blue is the indirect path, through ${res.mediator}; rose the direct path.`];
    if (res.product) notes.push(`With two least squares models and no interaction the indirect effect is the product a × b = ${sig(res.product.ab)} and the direct effect c′ = ${sig(res.product.c)} (Baron and Kenny's product of coefficients); the simulation gives ACME ${sig(effectOf(res, 'ACME (average)').estimate)} and ADE ${sig(effectOf(res, 'ADE (average)').estimate)}, and it gives the intervals.`);
    else notes.push(`With ${P.i ? 'the interaction' : 'a nonlinear model'} the effects are not a product of coefficients: they are averages, over the rows, of the differences between predicted outcomes, which is what the simulation computes.`);
    ob.add(...notes.map((s) => ctx.note(s)));
  }

  /* ---- the effects ----------------------------------------------------------------------------- */
  function effectsTable(ctx, res) {
    const small = 2 / res.n_rep;
    const rows = res.effects.rows.map((r) => ({ ...r, p: r.p === 0 ? `<${fmt(small, { sig: 3 })}${small < ctx.alpha ? '*' : ''}` : r.p }));
    return ctx.rt({ columns: res.effects.columns, rows }, {
      sortable: false, key: 'effects', name: 'Mediation Effects',
      cellClass: (r, c) => {
        const k = [];
        if (c.key === 'effect' && (/average/.test(r.effect) || r.effect === 'Total Effect')) k.push('sm-med-avg');
        if (c.key === 'p' && typeof r.p === 'string') k.push('p-sig');
        return k.join(' ');
      },
    });
  }

  function forestPlot(ctx, res) {
    const C = colors();
    const lv = fmt(100 * (1 - ctx.alpha));
    const names = ['ACME (control)', 'ACME (treated)', 'ACME (average)', 'ADE (control)', 'ADE (treated)', 'ADE (average)', 'Total Effect'];
    const items = names.map((n) => effectOf(res, n));
    const groups = [
      { name: 'ACME (indirect)', pick: (e) => e.kind === 'acme', marker: { symbol: 'circle', size: 9, color: C.acme, line: { color: C.surface, width: 2 } }, color: C.acme },
      { name: 'ADE (direct)', pick: (e) => e.kind === 'ade', marker: { symbol: 'square', size: 9, color: C.ade, line: { color: C.surface, width: 2 } }, color: C.ade },
      { name: 'Total', pick: (e) => e.kind === 'total', marker: { symbol: 'diamond', size: 11, color: C.text, line: { color: C.surface, width: 2 } }, color: C.text },
    ];
    const traces = groups.map((g) => {
      const its = items.filter(g.pick);
      return {
        type: 'scatter', mode: 'markers', name: g.name, x: its.map((e) => e.estimate), y: its.map((e) => e.effect), marker: g.marker,
        error_x: { type: 'data', symmetric: false, array: its.map((e) => e.upper - e.estimate), arrayminus: its.map((e) => e.estimate - e.lower), color: g.color, thickness: 2, width: 5 },
        customdata: its.map((e) => [e.lower, e.upper]), hovertemplate: `%{y}: %{x:.5g}<br>${lv}% interval %{customdata[0]:.5g} to %{customdata[1]:.5g}<extra></extra>`,
      };
    });
    const lo = Math.min(...items.map((e) => e.lower)), hi = Math.max(...items.map((e) => e.upper));
    const shapes = lo <= 0 && hi >= 0 ? [{ type: 'line', xref: 'x', yref: 'paper', x0: 0, x1: 0, y0: 0, y1: 1, line: { color: C.muted, width: 1 } }] : [];
    return ctx.plot(traces, {
      showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, shapes, margin: { l: 10, r: 14, t: 30, b: 42 },
      xaxis: { title: { text: res.outcome_binary ? `Effect on P(${esc(res.y)})` : `Effect on ${esc(res.y)}` }, zeroline: false },
      yaxis: { type: 'category', categoryorder: 'array', categoryarray: names.slice().reverse(), automargin: true },
    }, { width: W(430), height: 290, title: 'mediation effects', select: false });
  }

  function effectsOutline(ctx, res) {
    const ob = ctx.outline('Mediation Effects', { key: 'effects', info: 'p:mediation:effects', menu: () => [ctx.check('Effects Plot', 'forest', null, true), ctx.check('Simulated Distributions', 'draws', null, false)] });
    const tbl = effectsTable(ctx, res);
    ob.add(ctx.opt('forest', true) ? ctx.row(el('div', { class: 'sm-med-table' }, tbl), forestPlot(ctx, res)) : tbl);
    const t1 = treatText(ctx, res, res.treated), t0 = treatText(ctx, res, res.control);
    const notes = [
      `ACME, the average causal mediation effect: how ${res.y} changes when ${res.mediator} moves from what it would be under ${t0} to what it would be under ${t1}, with the treatment itself held at ${t0} (the control version) or at ${t1} (the treated version). ADE, the average direct effect: how ${res.y} changes from ${t0} to ${t1} with ${res.mediator} held where it would be under ${t0} (control) or under ${t1} (treated). The total effect is the whole change, ACME + ADE; the proportion mediated ACME / total, which wanders when the total effect is near zero.`,
      `Each estimate is the mean of the ${res.n_rep} simulated values (the median for the proportion mediated), the interval their ${fmt(50 * ctx.alpha)}th and ${fmt(100 - 50 * ctx.alpha)}th percentiles, and the p-value twice the share of the simulated values on the other side of zero, so its smallest step is ${fmt(2 / res.n_rep, { sig: 3 })}: <${fmt(2 / res.n_rep, { sig: 3 })} means no simulated value crossed zero.`,
      `These are causal effects only under sequential ignorability: nothing left out of the covariates affects both the treatment and ${res.mediator} or ${res.y} (a randomized treatment ensures it), and, given the treatment and the covariates, nothing left out affects both ${res.mediator} and ${res.y}. Randomizing the treatment does not ensure the second part and the data cannot check it (see Assumptions and Method).`,
      ...(res.notes || []),
    ];
    ob.add(...notes.map((s) => ctx.note(s)), ctx.code(res.code));
    return ob;
  }

  /* ---- the simulated distributions ----------------------------------------------------------------------- */
  function drawsOutline(ctx, res) {
    const C = colors();
    const ob = ctx.outline('Simulated Distributions', { key: 'draws', info: 'p:mediation:draws', menu: () => [{ label: 'Remove', action: () => ctx.set('draws', false) }] });
    const D = res.draws;
    const avg = (a, b) => a.map((v, i) => (v + b[i]) / 2);
    const plots = [['ACME (average)', avg(D.acme_ctrl, D.acme_tx), C.acme], ['ADE (average)', avg(D.ade_ctrl, D.ade_tx), C.ade]].map(([name, vals, color]) => {
      const e = effectOf(res, name);
      const b = SM.report.niceBins(vals);
      const nb = Math.max(1, Math.round((b.end - b.start) / b.size));
      const counts = new Array(nb).fill(0);
      for (const v of vals) counts[Math.min(nb - 1, Math.max(0, Math.floor((v - b.start) / b.size + 1e-9)))]++;
      const x = counts.map((_, j) => b.start + (j + 0.5) * b.size);
      const vline = (v, dash, width = 1.5) => ({ type: 'line', xref: 'x', yref: 'paper', x0: v, x1: v, y0: 0, y1: 1, line: { color: C.text, width, dash } });
      const shapes = [vline(e.estimate, 'solid', 2), vline(e.lower, 'dot'), vline(e.upper, 'dot')];
      if (b.start < 0 && b.end > 0) shapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: 0, x1: 0, y0: 0, y1: 1, line: { color: C.muted, width: 1 } });
      return ctx.plot([{ type: 'bar', x, y: counts, width: b.size, marker: { color, opacity: 0.75, line: { color: C.surface, width: 1 } }, name, hovertemplate: `${name} %{x:.4g}: %{y} simulations<extra></extra>` }],
        { xaxis: { title: { text: name } }, yaxis: { title: { text: 'Simulations' }, rangemode: 'tozero' }, shapes, bargap: 0, margin: { l: 52, r: 10, t: 8, b: 42 } },
        { width: W(360), height: 240, title: `${name} simulated`, select: false });
    });
    ob.add(ctx.row(...plots), ctx.note(`The ${res.n_rep} simulated values of each average effect, ${res.method === 'bootstrap' ? 'one per bootstrap sample' : 'one per draw of the two models\' parameters'}. The solid line is the estimate (their mean), the dotted lines the ${fmt(100 * (1 - ctx.alpha))}% interval (their percentiles).`));
  }

  /* ---- the two models -------------------------------------------------------------------------------------- */
  function modelOutline(ctx, res, which) {
    const Mo = res.models[which];
    const title = which === 'mediator' ? 'Mediator Model' : 'Outcome Model';
    const ob = ctx.outline(title, { key: `model:${which}`, closed: true, info: 'p:mediation:models' });
    const covs = res.covariates.length ? ` + ${res.covariates.join(' + ')}` : '';
    const rhs = which === 'mediator' ? `${res.treatment}${covs}` : `${res.treatment} + ${res.mediator}${res.interaction ? ` + ${res.treatment}*${res.mediator}` : ''}${covs}`;
    ob.add(ctx.kv([['Model', `${Mo.label}: ${Mo.response} on ${rhs}`, 'text'], ...Mo.summary.map(([k, v, f]) => [k, v, f])]),
      ctx.rt(Mo.estimates, { caption: 'Parameter Estimates', sortable: false, key: `est:${which}` }));
    const notes = [];
    if (res.t_kind === 'categorical') notes.push(`${res.t_label} is 1 for ${res.treatment} = ${treatText(ctx, res, res.treated)} and 0 for ${treatText(ctx, res, res.control)} (indicator coding: statsmodels sets the treatment to 0 and 1). Nominal covariates are effect coded, as JMP codes them.`);
    else notes.push(`${res.t_label} is 0 at ${res.treatment} = ${fmt(res.control)} and 1 at ${fmt(res.treated)}: its coefficient is the effect of the whole contrast.`);
    if (Mo.kind !== 'ols') notes.push(`A generalized linear model (statsmodels GLM, ${Mo.kind === 'poisson' ? 'Poisson family' : 'binomial family'}), fitted by maximum likelihood; z tests.`);
    ob.add(...notes.map((s) => ctx.note(s)));
  }

  /* ---- assumptions and method ---------------------------------------------------------------------------------- */
  function aboutOutline(ctx) {
    const ob = ctx.outline('Assumptions and Method', { key: 'about', info: 'p:mediation:about', menu: () => [{ label: 'Remove', action: () => ctx.set('about', false) }] });
    const para = (head, text) => el('p', null, el('strong', { text: `${head}. ` }), text);
    ob.add(el('div', { class: 'sm-med-about' },
      para('What is estimated', 'The treatment\'s total effect on the outcome, split in two: the part that goes through the mediator (the indirect effect, ACME) and the rest (the direct effect, ADE). Each is defined by potential outcomes: the outcome a person would have with the treatment at one value and the mediator at the value it would take under the same or the other treatment. They come in two versions, with the treatment held at control or at treated; without an interaction of treatment and mediator in the outcome model (and with linear models) the two are the same.'),
      para('Sequential ignorability', 'First, given the covariates, the treatment is as good as randomly assigned: nothing unmeasured drives both it and the mediator or the outcome. A randomized experiment ensures this. Second, given the treatment and the covariates, the mediator is as good as randomly assigned: nothing unmeasured drives both the mediator and the outcome. Nothing ensures the second part, not even randomizing the treatment, and the data cannot test it; a covariate that affects both the mediator and the outcome must be in the models, and nothing the treatment affects may be among the covariates. The models must also be right.'),
      para('How statsmodels computes it', 'Mediation (Imai, Keele and Tingley 2010) fits the mediator model and the outcome model, and then, many times over: draws the models\' parameters from their estimated sampling distributions (parametric, the quasi-Bayesian method) or fits them to a bootstrap sample of the rows; draws each row\'s mediator under control and under treatment from the mediator model; predicts each row\'s outcome for the four combinations with the outcome model; and averages the differences over the rows. The estimates, intervals and p-values are the mean, the percentiles and the sign shares of the simulated values. A binary or count outcome\'s effects are on the scale of the prediction: probabilities or expected counts.'),
      para('Against R\'s mediation', 'statsmodels follows R\'s mediate() (Tingley et al. 2014): the same algorithms, the same definitions of the effects, the same percentile intervals and sign-share p-values, and the quasi-Bayesian estimates are the means of the simulations in both. With the bootstrap they differ: R resamples the rows once for both models, statsmodels draws a separate resample for each; R takes its point estimates from the original data (and the proportion mediated as their ratio), statsmodels takes the mean of the replicates (and their median); R offers BCa intervals, statsmodels percentile ones only. R also has medsens() for the sensitivity of the effects to a violation of sequential ignorability, and more model classes (ordered, quantile, survival, multilevel); statsmodels has neither. Both treat the treatment as 0 and 1 (R\'s control.value and treat.value set another contrast; here the treatment is recoded).'),
      para('Worked around here', 'statsmodels 0.14.6\'s Mediation passes scale= to the mediator model\'s get_distribution, which the discrete Logit, Probit and Poisson do not take: binary and count models are the GLM families (the same maximum likelihood fits). Its formula path rebuilds both designs for every simulation, which is slow in the browser; the page uses its array path and sets the interaction column itself, which gives the same numbers (the tests check it); the Python shown uses the formula path.'),
      para('JMP', 'JMP has no causal mediation analysis. Its Structural Equation Models platform fits linear mediation models (indirect effects as products of path coefficients, with delta-method or bootstrap standard errors), which for two least squares models without an interaction estimate the same thing as ACME and ADE.'),
    ));
  }

  /* ---- the launch dialog's own part: the contrast, the models, the simulations ------------------------------------ */
  function launchExtra(api, spec) {
    const t = api.table;
    const o0 = (spec && spec.options) || {};
    const st = { out: o0.outcomeModel || null, med: o0.mediatorModel || null, control: o0.control ?? null, treated: o0.treated ?? null, tKey: null };
    const col = (k) => { const id = (api.state[k] || [])[0]; return id ? t.col(id) : null; };
    const mkSel = (choices, value, label) => { const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: v, text: l }))); if (value != null) s.value = value; return s; };
    const numIn = (label, value, size = 7) => { const i = el('input', { type: 'text', inputmode: 'decimal', size, 'aria-label': label }); i.value = value == null ? '' : String(value); return i; };
    const lab = (text, ...inputs) => el('label', { class: 'sm-med-opt' }, el('span', { text }), ...inputs);
    const ctlSel = el('select', { 'aria-label': 'Control level' }), trtSel = el('select', { 'aria-label': 'Treated level' });
    const ctlIn = numIn('Control value', null), trtIn = numIn('Treated value', null);
    const lCtl = lab('Control', ctlSel, ctlIn), lTrt = lab('Treated', trtSel, trtIn);
    const outSel = mkSel(MODELS, st.out, 'Outcome model'), medSel = mkSel(MODELS, st.med, 'Mediator model');
    const inter = el('input', { type: 'checkbox', 'aria-label': 'Treatment by mediator interaction' });
    inter.checked = !!o0.interaction;
    const nRep = numIn('Simulations', o0.nRep ?? 1000, 6), seed = numIn('Seed', o0.seed ?? 1, 6);
    const method = mkSel(METHODS, o0.method || 'parametric', 'Method');
    outSel.addEventListener('change', () => { st.out = outSel.value; });
    medSel.addEventListener('change', () => { st.med = medSel.value; });
    ctlSel.addEventListener('change', () => { st.control = ctlSel.value; });
    trtSel.addEventListener('change', () => { st.treated = trtSel.value; });
    ctlIn.addEventListener('input', () => { st.control = ctlIn.value; });
    trtIn.addEventListener('input', () => { st.treated = trtIn.value; });
    const sync = () => {
      const c = col('treatment');
      const cat = !!(c && c.isCategorical);
      ctlSel.hidden = trtSel.hidden = !cat;
      ctlIn.hidden = trtIn.hidden = cat || !c;
      const key = c ? c.id : null;
      if (key !== st.tKey) {
        // another treatment column: its own defaults, unless recalled values fit it
        if (st.tKey != null) { st.control = null; st.treated = null; }
        st.tKey = key;
      }
      if (cat) {
        const lv = t.levels(c);
        const opts = () => lv.map((v) => el('option', { value: String(v), text: SM.grid.cellText(c, v) }));
        ctlSel.replaceChildren(...opts());
        trtSel.replaceChildren(...opts());
        const c0 = levelOf(t, c, st.control, lv[0]);
        const c1 = levelOf(t, c, st.treated, lv[lv.length - 1]);
        if (c0 !== undefined) ctlSel.value = String(c0);
        if (c1 !== undefined) trtSel.value = String(c1);
        if (lv.length !== 2) api.message(`${c.name} has ${lv.length} level${lv.length === 1 ? '' : 's'}: the treatment takes a column with two levels, or a continuous one.`);
      } else if (c) {
        const [d0, d1] = defaultContrast(c);
        const num = (v) => { const x = Number(String(v ?? '').replace(',', '.')); return String(v ?? '').trim() !== '' && Number.isFinite(x) ? x : null; };
        ctlIn.value = String(num(st.control) ?? +d0.toPrecision(6));
        trtIn.value = String(num(st.treated) ?? +d1.toPrecision(6));
      }
      const y = col('y'), m = col('mediator');
      if (!st.out) outSel.value = y && y.isCategorical ? 'logit' : 'ols';
      if (!st.med) medSel.value = m && m.isCategorical ? 'logit' : 'ols';
    };
    api.onRolesChange(sync);
    sync();
    const box = el('div', { class: 'sm-med-launch' },
      el('div', { class: 'sm-med-row' }, el('span', { class: 'sm-med-head' }, el('strong', { text: 'Treatment contrast' }), slot('p:mediation:contrast')), lCtl, lTrt),
      el('div', { class: 'sm-med-row' }, lab('Outcome model', outSel), lab('Mediator model', medSel), el('label', { class: 'sm-med-opt' }, inter, el('span', { text: 'Treatment × mediator interaction' }))),
      el('div', { class: 'sm-med-row' }, el('span', { class: 'sm-med-head' }, el('strong', { text: 'Simulations' }), slot('p:mediation:simulation')), lab('Number', nRep), lab('Method', method), lab('Seed', seed)));
    const number = (i) => { const s = String(i.value).trim().replace(',', '.'); return s === '' ? null : Number(s); };
    return {
      el: box,
      help: [
        ['Control', 'Where the effects start: a level of a two-level treatment (at first its first level), or a number for a continuous one (at first its first quartile, or the smaller of its two values). statsmodels codes it 0.'],
        ['Treated', 'Where the effects go: the other level (at first the last), or a number (the third quartile, or the larger value), coded 1. For a continuous treatment the effects are those of the whole step from Control to Treated.'],
        ['Outcome model', 'The model of Y on the treatment, the mediator and the covariates: Least Squares for a continuous Y (its default), Logistic or Probit for two levels or 0/1 (Logistic is the default for a categorical Y), Poisson for a count. A categorical Y takes Logistic or Probit only.'],
        ['Mediator model', 'The model of the mediator on the treatment and the covariates, chosen the same way: Least Squares for a continuous mediator, Logistic or Probit for a two-level one, Poisson for a count.'],
        ['Treatment × mediator interaction', 'Adds treatment × mediator to the outcome model, so that the mediator may act differently under control and under treatment; the control and treated versions of ACME and ADE then differ. Off by default: without it, and with least squares models, the two versions are the same.'],
        ['Number', 'How many simulations, 20 to 100 000 (1000 by default). More give steadier estimates and intervals and a finer p-value, whose smallest step is 2 / simulations; the time grows with them, and rows × simulations may be at most 10 million.'],
        ['Method', 'Parametric (quasi-Bayesian, the default, as in R\'s mediation): each simulation draws the two models\' parameters from their estimated sampling distributions. Nonparametric bootstrap: each refits both models to a resample of the rows; slower, and it does not lean on the normal approximation.'],
        ['Seed', 'The seed of the simulations, a whole number from 0: the same seed gives the same numbers, here and in the Python shown.'],
      ],
      read() {
        const c = col('treatment');
        let control = null, treated = null;
        if (c && c.isCategorical) {
          const lv = t.levels(c);
          control = lv.find((v) => String(v) === ctlSel.value) ?? null;
          treated = lv.find((v) => String(v) === trtSel.value) ?? null;
        } else if (c) { control = number(ctlIn); treated = number(trtIn); }
        const n = number(nRep), sd = number(seed);
        return { options: { control, treated, outcomeModel: outSel.value, mediatorModel: medSel.value, interaction: inter.checked, nRep: n == null ? 1000 : n, method: method.value, seed: sd == null ? 1 : sd } };
      },
      recall(saved) {
        const o = (saved && saved.options) || {};
        st.out = o.outcomeModel || null; st.med = o.mediatorModel || null;
        if (st.out) outSel.value = st.out;
        if (st.med) medSel.value = st.med;
        st.control = o.control ?? null; st.treated = o.treated ?? null; st.tKey = null;
        inter.checked = !!o.interaction;
        nRep.value = String(o.nRep ?? 1000); seed.value = String(o.seed ?? 1); method.value = o.method || 'parametric';
        sync();
      },
    };
  }

  function validate(spec, table) {
    const one = (k) => { const id = ((spec.roles || {})[k] || [])[0]; return id ? table.col(id) : null; };
    const y = one('y'), tr = one('treatment'), m = one('mediator');
    const cov = ((spec.roles || {}).covariates || []).map((id) => table.col(id)).filter(Boolean);
    if (new Set([y.id, tr.id, m.id]).size < 3) return 'The outcome, the treatment and the mediator must be three different columns.';
    for (const c of cov) if (c === y || c === tr || c === m) return `${c.name} is ${c === y ? 'the outcome' : c === tr ? 'the treatment' : 'the mediator'}: take it out of the covariates.`;
    const o = spec.options || {};
    if (tr.isCategorical) {
      const lv = table.levels(tr);
      if (lv.length !== 2) return `The treatment takes a column with two levels, or a continuous one; ${tr.name} has ${lv.length}.`;
      if (String(o.control) === String(o.treated)) return 'The control and the treated level must be different.';
    } else if (!Number.isFinite(o.control) || !Number.isFinite(o.treated) || o.control === o.treated) {
      return `Give ${tr.name} two different values to compare: the control value and the treated value.`;
    }
    for (const [c, k, what] of [[y, o.outcomeModel, 'outcome'], [m, o.mediatorModel, 'mediator']]) {
      if (c.isCategorical) {
        const lv = table.levels(c);
        if (lv.length !== 2) return `${c.name} (the ${what}) has ${lv.length} levels: a categorical ${what} takes two (a logistic or probit model).`;
        if (k === 'poisson') return `${c.name} (the ${what}) is categorical: a Poisson model takes counts.`;
      } else if (!c.isNumeric) return `${c.name} (the ${what}) must be numeric, or nominal with two levels.`;
    }
    if (!(o.nRep >= 20 && o.nRep <= 100000)) return 'Simulations: a number from 20 to 100000.';
    if (!Number.isInteger(o.seed) || o.seed < 0) return 'Seed: a whole number, zero or more.';
    return null;
  }

  /* ---- the red triangle --------------------------------------------------------------------------------------- */
  async function contrastDialog(ctx) {
    const c = ctx.role('treatment');
    if (!c) return;
    if (c.isCategorical) {
      const lv = ctx.table.levels(c);
      const choices = lv.map((v) => [String(v), SM.grid.cellText(c, v)]);
      const cur0 = levelOf(ctx.table, c, ctx.opt('control', null), lv[0]), cur1 = levelOf(ctx.table, c, ctx.opt('treated', null), lv[lv.length - 1]);
      const v = await SM.ui.form({ title: `Treatment Contrast: ${c.name}`, info: 'p:mediation:contrast', fields: [
        { key: 'c0', label: 'Control level', type: 'select', value: String(cur0), choices, help: 'The level the effects start from, coded 0 in both models.' },
        { key: 'c1', label: 'Treated level', type: 'select', value: String(cur1), choices, help: 'The level the effects go to, coded 1; another level than Control. Swapping the two turns every effect\'s sign, and the control and treated versions trade places.' }],
      validate: (x) => (x.c0 === x.c1 ? 'The two levels must be different.' : null) });
      if (!v) return;
      ctx.set('control', lv.find((x) => String(x) === v.c0), null, { rerun: false });
      ctx.set('treated', lv.find((x) => String(x) === v.c1));
    } else {
      const [d0, d1] = defaultContrast(c);
      const v = await SM.ui.form({ title: `Treatment Contrast: ${c.name}`, info: 'p:mediation:contrast', lead: `The effects compare ${c.name} at the treated value with ${c.name} at the control value.`, fields: [
        { key: 'c0', label: 'Control value', type: 'number', value: ctx.opt('control', d0), help: `The value of ${c.name} the effects start from, in its units: at first its first quartile, or the smaller of its two values.` },
        { key: 'c1', label: 'Treated value', type: 'number', value: ctx.opt('treated', d1), help: `The value they go to (at first the third quartile, or the larger value): the effects are those of moving ${c.name} from Control value to Treated value, with the treatment recoded to (T − control)/(treated − control), the same model.` }],
      validate: (x) => (x.c0 == null || x.c1 == null || x.c0 === x.c1 ? 'Give two different numbers.' : null) });
      if (!v) return;
      ctx.set('control', v.c0, null, { rerun: false });
      ctx.set('treated', v.c1);
    }
  }

  async function simulationDialog(ctx) {
    const v = await SM.ui.form({ title: 'Simulations', info: 'p:mediation:simulation', fields: [
      { key: 'n', label: 'Number of simulations', type: 'number', value: ctx.opt('nRep', 1000), help: '20 to 100 000, 1000 by default. More give steadier estimates and intervals and a finer p-value (its step is 2 / simulations); rows × simulations may be at most 10 million.' },
      { key: 'method', label: 'Method', type: 'select', value: ctx.opt('method', 'parametric'), choices: METHODS, help: 'Parametric (quasi-Bayesian) or the nonparametric bootstrap, as above; the bootstrap refits both models in every simulation, so it takes longer.' },
      { key: 'seed', label: 'Seed', type: 'number', value: ctx.opt('seed', 1), help: 'A whole number from 0: the same seed gives the same simulations, here and in the Python shown.' }],
    validate: (x) => (!(x.n >= 20 && x.n <= 100000) ? 'Simulations: a number from 20 to 100000.' : !Number.isInteger(x.seed) || x.seed < 0 ? 'Seed: a whole number, zero or more.' : null) });
    if (!v) return;
    ctx.set('nRep', Math.round(v.n), null, { rerun: false });
    ctx.set('method', v.method, null, { rerun: false });
    ctx.set('seed', v.seed);
  }

  function triangle(ctx) {
    const pick = (key, dflt) => (label, value) => ({ label, checked: ctx.opt(key, dflt) === value, action: () => ctx.set(key, value) });
    const res = ctx.med && ctx.med.res;
    return [
      ctx.check('Path Diagram', 'diagram', null, true),
      ctx.check('Effects Plot', 'forest', null, true),
      ctx.check('Simulated Distributions', 'draws', null, false),
      ctx.check('Mediator Model', 'mediatorOutline', null, true),
      ctx.check('Outcome Model', 'outcomeOutline', null, true),
      ctx.check('Assumptions and Method', 'about', null, true),
      { separator: true },
      { label: 'Outcome Model Type', submenu: () => MODELS.map(([k, l]) => pick('outcomeModel', res ? res.outcome_model : 'ols')(l, k)) },
      { label: 'Mediator Model Type', submenu: () => MODELS.map(([k, l]) => pick('mediatorModel', res ? res.mediator_model : 'ols')(l, k)) },
      ctx.check('Treatment × Mediator Interaction', 'interaction', null, false),
      { label: 'Treatment Contrast…', action: () => contrastDialog(ctx) },
      { label: 'Method', submenu: () => METHODS.map(([k, l]) => pick('method', 'parametric')(l, k)) },
      { label: 'Simulations…', action: () => simulationDialog(ctx) },
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
  }

  /* ---- the report ---------------------------------------------------------------------------------------------- */
  async function render(ctx) {
    ctx.med = null;
    const base = payloadOf(ctx);
    const note = el('p', { class: 'sm-ob-note sm-med-progress', text: `Mediation: ${base.n_rep} simulations…`, role: 'status' });
    ctx.container.append(note);
    const off = SM.engine.on('log', (m) => {
      const k = /^smui:progress mediation (\d+) (\d+)/.exec((m && m.text) || '');
      if (!k) return;
      const text = `Mediation${ctx.byLabel ? ` (${ctx.byLabel})` : ''}: ${k[1]} of ${k[2]} simulations…`;
      note.textContent = text;
      ctx.report.noteEl.textContent = text;
    });
    let res;
    try { res = await ctx.call('mediation.fit', base); } finally { off(); note.remove(); }
    if (res.error) { ctx.container.append(ctx.warn(res.error)); return; }
    ctx.med = { res };
    summary(ctx, res);
    if (ctx.opt('diagram', true)) diagramOutline(ctx, res);
    effectsOutline(ctx, res);
    if (ctx.opt('draws', false)) drawsOutline(ctx, res);
    if (ctx.opt('mediatorOutline', true)) modelOutline(ctx, res, 'mediator');
    if (ctx.opt('outcomeOutline', true)) modelOutline(ctx, res, 'outcome');
    if (ctx.opt('about', true)) aboutOutline(ctx);
  }

  /* ---- the example table: a simulated coaching study ------------------------------------------------------------ */
  /* 600 people, half given a coaching program at random. Coaching raises
     confidence by 4 points; each point of confidence raises the exam score by
     1.5, so the indirect effect is 6; coaching also raises the score by 2
     directly. Age, sex and a baseline score affect confidence and the score:
     with them in the models, sequential ignorability holds. Both potential
     values of confidence and the score are drawn for everyone, so the
     sample's true effects are known, for the pass mark (score 70 or more)
     too. resources/tests/smui/test_mediation.py makes the same table. */
  function simulateCoaching() {
    const r = SM.util.rng('mediation-coaching');
    const n = 600;
    const arms = Array.from({ length: n }, (_, i) => (i < n / 2 ? 0 : 1));
    for (let i = n - 1; i > 0; i--) { const j = Math.floor(r.u() * (i + 1)); [arms[i], arms[j]] = [arms[j], arms[i]]; }
    const c = { id: [], age: [], sex: [], baseline: [], program: [], confidence: [], score: [], passed: [] };
    const acme = [0, 0], ade = [0, 0], pacme = [0, 0], pade = [0, 0];
    for (let i = 0; i < n; i++) {
      const age = Math.max(20, Math.min(65, Math.round(r.normal(38, 9))));
      const sex = r.u() < 0.5 ? 'F' : 'M';
      const base = +r.normal(50, 10).toFixed(1);
      const t = arms[i];
      const em = r.normal(0, 3), ey = r.normal(0, 5);
      const mu = 20 + 0.3 * (base - 50) + 0.05 * (age - 38) + (sex === 'F' ? 1 : 0) + em;
      const m = [+mu.toFixed(1), +(mu + 4).toFixed(1)];
      const y = (tt, mm) => +(30 + 1.5 * mm + 2 * tt + 0.4 * (base - 50) - 0.1 * (age - 38) + ey).toFixed(1);
      for (const k of [0, 1]) {
        acme[k] += y(k, m[1]) - y(k, m[0]);
        ade[k] += y(1, m[k]) - y(0, m[k]);
        pacme[k] += (y(k, m[1]) >= 70) - (y(k, m[0]) >= 70);
        pade[k] += (y(1, m[k]) >= 70) - (y(0, m[k]) >= 70);
      }
      c.id.push(`P${String(i + 1).padStart(3, '0')}`); c.age.push(age); c.sex.push(sex); c.baseline.push(base);
      c.program.push(t ? 'coaching' : 'control'); c.confidence.push(m[t]); c.score.push(y(t, m[t])); c.passed.push(y(t, m[t]) >= 70 ? 'yes' : 'no');
    }
    return { c, truth: { acme: acme.map((a) => a / n), ade: ade.map((a) => a / n), acmePassed: pacme.map((a) => a / n), adePassed: pade.map((a) => a / n) } };
  }
  const SIM = simulateCoaching();
  const TRUTH = SIM.truth;
  const pp = (x) => fmt(x, { sig: 2 });
  SM.io.addExample('mediation', {
    label: 'Coaching study (600 people): program, confidence, exam score',
    about: `Simulated randomized study: 600 people, half given a coaching program. Coaching raises confidence by 4 points and each point of confidence raises the exam score by 1.5, so the true indirect effect (ACME) is ${fmt(Math.round(10 * TRUTH.acme[0]) / 10)}; coaching also raises the score by ${fmt(Math.round(10 * TRUTH.ade[0]) / 10)} directly (ADE), a total of 8, 75% of it mediated. Age, sex and the baseline score affect both confidence and the score: they are the covariates that make the indirect effect identifiable. Passed (a score of 70 or more) is a binary outcome; on its probability the true ACME is ${pp(TRUTH.acmePassed[0])} (control) and ${pp(TRUTH.acmePassed[1])} (treated), the ADE ${pp(TRUTH.adePassed[0])} and ${pp(TRUTH.adePassed[1])}. For Mediation.`,
    truth: TRUTH,
    make() {
      const { c } = simulateCoaching();
      return new SM.Table({ name: 'Coaching study', source: 'simulated', columns: [
        { name: 'id', dataType: 'character', values: c.id, role: 'label' },
        { name: 'age', dataType: 'numeric', values: c.age, notes: 'years' },
        { name: 'sex', dataType: 'character', values: c.sex, valueOrder: ['F', 'M'] },
        { name: 'baseline', dataType: 'numeric', values: c.baseline, notes: 'the score of a test before the program' },
        { name: 'program', dataType: 'character', values: c.program, valueOrder: ['control', 'coaching'], notes: 'assigned at random: coaching or control' },
        { name: 'confidence', dataType: 'numeric', values: c.confidence, notes: 'a confidence score after the program: the mediator' },
        { name: 'score', dataType: 'numeric', values: c.score, notes: 'the exam score: the outcome' },
        { name: 'passed', dataType: 'character', values: c.passed, valueOrder: ['no', 'yes'], notes: 'yes when the score is 70 or more' },
      ] });
    },
  });

  /* ---- Help -------------------------------------------------------------------------------------------------------- */
  const TOPICS = {
    'p:mediation': {
      kicker: 'Analyze > Specialized Modeling', title: 'Mediation',
      lead: 'How much of a treatment\'s effect on an outcome passes through a mediator: statsmodels\' causal mediation analysis (Imai, Keele and Tingley), with a mediator model and an outcome model and simulated effects.',
      sections: [
        { heading: 'Roles', choices: [['Y, Outcome', 'Continuous (least squares), binary (logistic or probit: effects on the probability) or a count (Poisson).'],
          ['Treatment', 'Two levels (choose the control and the treated level), or continuous (choose the two values to compare).'],
          ['Mediator', 'What the treatment may change and that may change the outcome: continuous, binary or a count.'],
          ['Covariates', 'Columns that affect the mediator and the outcome (or the treatment), measured before the treatment; they enter both models.'],
          ['By', 'A separate analysis for each level.']] },
        { heading: 'In the red triangle', text: 'Every setting of the launch dialog can be changed in the report: Outcome and Mediator Model Type, Treatment × Mediator Interaction, Treatment Contrast…, Method and Simulations… (the number and the seed); the effects are simulated again.' },
        { heading: 'Reading it', text: 'ACME is the indirect effect, ADE the direct one, and their sum the total. Look at the intervals, and think hard about sequential ignorability: nothing unmeasured may drive both the mediator and the outcome.' },
      ],
      more: MORE,
    },
    'p:mediation:effects': {
      kicker: 'Mediation', title: 'Mediation Effects',
      lead: 'statsmodels\' summary(): each effect\'s estimate, interval and p-value from the simulated values.',
      sections: [{ choices: [['ACME', 'the average causal mediation effect: the change in the outcome when the mediator moves as the treatment would move it, the treatment held fixed (at control or at treated)'],
        ['ADE', 'the average direct effect: the change from control to treated with the mediator held where it would be under control (or under treatment)'],
        ['Total Effect', 'the average of ACME and ADE over the two versions, added: the whole effect'], ['Prop. Mediated', 'ACME / total (the median over the simulations)'],
        ['Average', 'the mean of the control and treated versions'], ['P-value', 'twice the share of simulated values on the other side of zero; its step is 2 / simulations']] }],
      more: MORE,
    },
    'p:mediation:diagram': {
      kicker: 'Mediation', title: 'Path Diagram',
      lead: 'The treatment, the mediator and the outcome, with the models\' coefficients on the arrows (a, b, c′) and the simulated indirect (ACME) and direct (ADE) effects. For two least squares models without an interaction the indirect effect is a × b; otherwise it is an average of predicted differences.',
      more: MORE,
    },
    'p:mediation:draws': { kicker: 'Mediation', title: 'Simulated Distributions', lead: 'The simulated values of the average ACME and ADE: their mean is the estimate, their percentiles the interval. A lopsided histogram is why the interval is not symmetric.', more: MORE },
    'p:mediation:models': {
      kicker: 'Mediation', title: 'Mediator and Outcome Models',
      lead: 'The two models Mediation simulates from, fitted to the complete rows: the mediator on the treatment and the covariates; the outcome on the treatment, the mediator (and their interaction) and the covariates. The treatment is 0 for control and 1 for treated; nominal covariates are effect coded as in JMP.',
      more: MORE,
    },
    'p:mediation:contrast': { kicker: 'Mediation', title: 'Treatment Contrast', lead: 'The two values the effects compare. A two-level treatment: its control and treated levels. A continuous one: two values (at first its quartiles, or its two values when it has two); statsmodels contrasts 0 with 1, so the treatment is recoded to (T − control) / (treated − control), the same model.', more: MORE },
    'p:mediation:simulation': {
      kicker: 'Mediation', title: 'Simulations',
      lead: 'How many times the effects are simulated, and how.',
      sections: [{ choices: [['Parametric', 'the quasi-Bayesian method: the models\' parameters drawn from their approximate sampling distributions (the default, as in R\'s mediation)'],
        ['Bootstrap', 'the models refitted to resamples of the rows; slower (a fit per model per simulation)']] },
      { text: 'The number of simulations (1000 by default) sets how steady the estimates are and the p-value\'s step, 2 / simulations; the seed makes them repeatable, here and in the Python shown.' }],
      more: MORE,
    },
    'p:mediation:about': { kicker: 'Mediation', title: 'Assumptions and Method', lead: 'What the effects mean, what they assume (sequential ignorability), how statsmodels computes them and how that differs from R\'s mediation package.', more: MORE },
  };

  /* ---- the platform ------------------------------------------------------------------------------------------------ */
  SM.platforms.register({
    id: 'mediation', label: 'Mediation', menu: 'Analyze/Specialized Modeling', order: 80, info: 'p:mediation', topics: TOPICS,
    about: 'Causal mediation analysis (statsmodels\' Mediation, Imai, Keele and Tingley 2010): how much of a treatment\'s effect on an outcome passes through a mediator. A mediator model and an outcome model (least squares, or logistic, probit and Poisson GLMs, with covariates and an optional treatment × mediator interaction) are simulated by the quasi-Bayesian method or the bootstrap into the average causal mediation effects (ACME), the average direct effects (ADE), the total effect and the proportion mediated, for the control and the treated condition and on average, with intervals and p-values; a path diagram, a forest-style plot, the simulated distributions and both models\' parameter estimates. A two-level or a continuous treatment (two values contrasted). JMP has no causal mediation analysis.',
    uses: ['statsmodels.stats.mediation.Mediation, MediationResults.summary', 'statsmodels.regression.linear_model.OLS', 'statsmodels.genmod.generalized_linear_model.GLM (Binomial logit and probit, Poisson)', 'patsy'],
    launch: {
      lead: 'The effect of a treatment on an outcome, split into the part that goes through a mediator (indirect) and the rest (direct): a model of the mediator, a model of the outcome, and simulations.',
      roles: [
        { key: 'y', label: 'Y, Outcome', min: 1, max: 1, hint: 'required: continuous, binary or a count',
          help: 'The outcome: continuous (least squares), two levels or 0/1 (logistic or probit: the effects are on the probability of the second level, or of 1) or a count (Poisson: on the expected count), as Outcome model says. Rows with a missing value in any role are left out.' },
        { key: 'treatment', label: 'Treatment', min: 1, max: 1, hint: 'required: two levels, or continuous',
          help: 'What may cause the change: a column with two levels, whose Control and Treated levels are picked below, or a continuous one, with two values to compare (at first its quartiles, or its two values when it has only two).' },
        { key: 'mediator', label: 'Mediator', min: 1, max: 1, hint: 'required',
          help: 'The path the effect may take: something the treatment changes and that changes the outcome in turn, measured after the treatment and before the outcome. Continuous, two levels or a count, as Mediator model says.' },
        { key: 'covariates', label: 'Covariates', hint: 'optional: in both models',
          help: 'Optional. Columns measured before the treatment that affect the mediator and the outcome (or the treatment): they enter both models as main effects, a nominal one effect coded. Nothing the treatment itself changes may be among them.' },
        { key: 'by', label: 'By', hint: 'optional',
          help: 'A separate analysis of the rows of each level (each combination of levels, with several By columns). Rows with a missing By value are left out.' },
      ],
      extra: launchExtra,
      validate,
    },
    title(spec, table) {
      const name = (k) => { const id = ((spec.roles || {})[k] || [])[0]; const c = id && table ? table.col(id) : null; return c ? c.name : null; };
      return name('treatment') && name('y') && name('mediator') ? `Mediation of ${name('treatment')} on ${name('y')} through ${name('mediator')}` : 'Mediation';
    },
    triangle,
    render,
  });
}(typeof self !== 'undefined' ? self : this));
