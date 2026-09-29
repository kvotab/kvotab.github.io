/* ==========================================================================
   SMUI.HTML: ANALYZE > SPECIALIZED MODELING > META-ANALYSIS

   Each row of the table is a study. Its effect comes from one of three
   layouts of columns, chosen in the launch dialog: an effect and its
   standard error (or variance); n, mean and standard deviation of two
   groups (Hedges' g or the mean difference); events and totals of two
   groups (log odds ratio, log risk ratio, risk difference).

   The report, as a published meta-analysis shows it: the forest plot
   (studies linked to their rows), the summary estimates (fixed effect,
   random effects by DerSimonian-Laird, Paule-Mandel and REML, Hartung-
   Knapp on request, the prediction interval), heterogeneity, subgroups,
   the funnel plot with Egger's and Begg's tests, leave-one-out, and from
   the red triangle a cumulative meta-analysis and a meta-regression with
   its bubble plots. The numbers are statsmodels' meta_analysis
   (resources/py/smui/meta.py); JMP has no platform for this, so the names
   follow the published forest plots and JMP's report style.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);

  /* ---- roles and layouts ------------------------------------------------------ */
  const NUM = { numeric: true, types: ['continuous'], max: 1 };
  const ES = 'Effect and standard error layout, required there', CONT = 'Two groups, continuous outcome layout, required there', BINL = 'Two groups, binary outcome layout, required there';
  const ROLES = [
    { key: 'effect', label: 'Effect', ...NUM, hint: 'required: one effect per study',
      help: `${ES}: each study's effect as it reports it, such as a mean difference, a standardized mean difference or a log odds, risk or hazard ratio (for a log ratio, tick the box of the layout to see ratios).` },
    { key: 'se', label: 'Std Error', ...NUM, hint: 'required: its standard error',
      help: `${ES}: the effect's standard error, or its variance when the layout's box says the column holds variances (the role is then called Variance). A study whose value is not above 0 is left out.` },
    { key: 'n1', label: 'N (Treatment)', ...NUM, hint: 'required', help: `${CONT}: the number of subjects in the treatment group; a study with fewer than 2 in a group is left out.` },
    { key: 'mean1', label: 'Mean (Treatment)', ...NUM, hint: 'required', help: `${CONT}: the treatment group's mean.` },
    { key: 'sd1', label: 'Std Dev (Treatment)', ...NUM, hint: 'required', help: `${CONT}: the treatment group's standard deviation, above 0.` },
    { key: 'n2', label: 'N (Control)', ...NUM, hint: 'required', help: `${CONT}: the number of subjects in the control group, at least 2.` },
    { key: 'mean2', label: 'Mean (Control)', ...NUM, hint: 'required', help: `${CONT}: the control group's mean; the effect is treatment minus control.` },
    { key: 'sd2', label: 'Std Dev (Control)', ...NUM, hint: 'required', help: `${CONT}: the control group's standard deviation, above 0.` },
    { key: 'events1', label: 'Events (Treatment)', ...NUM, hint: 'required', help: `${BINL}: the subjects with the event in the treatment group, from 0 to its N.` },
    { key: 'total1', label: 'N (Treatment)', ...NUM, hint: 'required: the group size', help: `${BINL}: the size of the treatment group, above 0.` },
    { key: 'events2', label: 'Events (Control)', ...NUM, hint: 'required', help: `${BINL}: the subjects with the event in the control group, from 0 to its N.` },
    { key: 'total2', label: 'N (Control)', ...NUM, hint: 'required: the group size', help: `${BINL}: the size of the control group, above 0; the ratios are treatment over control.` },
    { key: 'label', label: 'Study Label', max: 1, hint: 'optional: names in the plots',
      help: 'The name of each study in the forest plot, the other plots and the tables. Without it, the table\'s label column (Cols > Label), or the row number.' },
    { key: 'group', label: 'Group', max: 1, types: ['ordinal', 'nominal'], hint: 'optional: subgroups',
      help: 'Subgroups: the studies of each level are pooled on their own (the Subgroups outline, with a test of subgroup differences) and listed by level in the forest plot. Studies with a missing value are left out.' },
    { key: 'covariates', label: 'Covariates', hint: 'optional: for Meta-Regression',
      help: 'Study-level variables (moderators) for a Meta-Regression, which the report then opens with: continuous columns enter as they are, nominal and ordinal ones as dummies against their first level. The red triangle\'s Meta-Regression… changes them.' },
    { key: 'by', label: 'By', hint: 'optional',
      help: 'A separate meta-analysis for each level of the By column (each combination of levels, with several By columns). Rows with a missing By value are left out.' },
  ];
  const ROLE = Object.fromEntries(ROLES.map((r) => [r.key, r]));
  const LAYOUTS = [['es', 'Effect and standard error'], ['cont', 'Two groups, continuous outcome'], ['bin', 'Two groups, binary outcome']];
  const LAYOUT_ROLES = { es: ['effect', 'se'], cont: ['n1', 'mean1', 'sd1', 'n2', 'mean2', 'sd2'], bin: ['events1', 'total1', 'events2', 'total2'] };
  const INPUT_KEYS = [].concat(...Object.values(LAYOUT_ROLES));
  const METHODS = [['dl', 'DerSimonian–Laird'], ['pm', 'Paule–Mandel'], ['reml', 'REML']];
  const METHOD = Object.fromEntries(METHODS);
  const CONT_MEASURES = [['smd', 'Standardized mean difference (Hedges\' g)'], ['md', 'Mean difference']];
  const BIN_MEASURES = [['or', 'Odds ratio'], ['rr', 'Risk ratio'], ['rd', 'Risk difference']];
  const MEASURE_ITEMS = { smd: 'Hedges\' g (Standardized Mean Difference)', md: 'Mean Difference', or: 'Odds Ratio', rr: 'Risk Ratio', rd: 'Risk Difference' };
  const ZERO = [['0.5', 'Add 0.5 to every cell'], ['tac', 'Treatment-arm correction'], ['none', 'None: leave such studies out']];
  const SHORT = { 'Odds Ratio': 'OR', 'Risk Ratio': 'RR', Ratio: 'Ratio' };

  const layoutOf = (o) => (LAYOUT_ROLES[o && o.layout] ? o.layout : 'es');
  function measureKey(o) {
    const layout = layoutOf(o);
    if (layout === 'es') return o.logRatio ? 'es_log' : 'es';
    if (layout === 'cont') return o.measure === 'md' ? 'md' : 'smd';
    return ['or', 'rr', 'rd'].includes(o.measure) ? o.measure : 'or';
  }
  const PLURAL = { es: 'Effects', es_log: 'Ratios', smd: 'Standardized Mean Differences', md: 'Mean Differences', or: 'Odds Ratios', rr: 'Risk Ratios', rd: 'Risk Differences' };

  /* A table with events columns opens on the binary layout, one with means
     on the continuous one. */
  function guessLayout(t) {
    const names = t.columns.map((c) => c.name.toLowerCase());
    if (names.some((n) => /event|cases|deaths|respon/.test(n))) return 'bin';
    if (names.some((n) => /\bmean/.test(n)) && names.some((n) => /\bsd\b|std|deviation/.test(n))) return 'cont';
    return 'es';
  }

  /* ---- colours: the studies, and the two pooled models (validated for both
     themes against kvot.css's surfaces: blue and red pass the CVD checks) --- */
  function colors() {
    const c = SM.util.themeColors();
    return { ...c, study: c.dark ? '#4d8ad6' : '#2a6db3', re: c.dark ? '#d0584e' : '#b0413e', fe: c.text, ci: c.text };
  }

  const pct = (x) => (x == null || !Number.isFinite(x) ? null : 100 * x);
  const lvText = (alpha) => `${fmt(100 * (1 - alpha))}%`;

  /* ---- what the backend is asked ----------------------------------------------------- */
  function inputsOf(ctx) {
    const o = ctx.spec.options || {};
    const layout = layoutOf(o);
    const inp = { layout };
    for (const k of LAYOUT_ROLES[layout]) inp[k] = ctx.name(k);
    const lab = ctx.role('label') || (ctx.table && ctx.table.labelColumn());
    inp.label = lab ? lab.name : null;
    inp.group = ctx.name('group');
    if (layout === 'es') { inp.var = o.seKind === 'var'; inp.log = !!o.logRatio; }
    else if (layout === 'cont') inp.measure = o.measure === 'md' ? 'md' : 'smd';
    else { inp.measure = measureKey(o); inp.cc = o.cc == null ? 0.5 : (o.cc === 'none' || o.cc === 'tac' ? o.cc : Number(o.cc)); }
    return inp;
  }

  function covariatesOf(ctx) {
    const ids = ctx.opt('mreg', null);
    const cols = (ids == null ? ctx.roles('covariates') : ids.map((id) => ctx.col(id)).filter(Boolean));
    return cols;
  }

  const baseArgs = (ctx) => ({ inputs: inputsOf(ctx), method: ctx.opt('method', 'dl'), alpha: ctx.alpha, hksj: !!ctx.opt('hksj', false) });

  /* ---- numbers in the forest plot's text columns ------------------------------------ */
  function decimals(res) {
    if (res.measure.log) return 2;
    const w = res.studies.map((s) => s.upper - s.lower).filter((x) => x > 0).sort((a, b) => a - b);
    const med = w.length ? w[Math.floor(w.length / 2)] : 1;
    return Math.max(0, Math.min(4, 1 - Math.floor(Math.log10(med))));
  }
  const fd = (x, dec) => (x == null || !Number.isFinite(x) ? '.' : fmt(x, { digits: dec }));
  const pText = (p) => (p == null || !Number.isFinite(p) ? '.' : p < 0.0001 ? '< 0.0001' : `= ${p.toFixed(4)}`);
  /* A hex colour with an alpha, for the subtotal diamonds. */
  const withAlpha = (col, a) => (/^#[0-9a-f]{6}$/i.test(col) ? `${col}${Math.round(a * 255).toString(16).padStart(2, '0')}` : col);

  /* Tick values of a log axis between a and b (display values): 1-2-5, or
     denser when the range is narrow. */
  function logTicks(a, b) {
    // the densest of these sequences that gives at most 8 ticks
    const sets = [[1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9], [1, 1.5, 2, 3, 5, 7], [1, 2, 3, 5], [1, 2, 5], [1, 3], [1]];
    const at = (mant) => {
      const out = [];
      for (let e = Math.floor(Math.log10(a)) - 1; e <= Math.ceil(Math.log10(b)) + 1; e++) {
        for (const m of mant) { const v = +(m * 10 ** e).toPrecision(4); if (v >= a && v <= b) out.push(v); }
      }
      return out;
    };
    let out = [];
    for (const mant of sets) { out = at(mant); if (out.length <= 8) break; }
    while (out.length > 8) out = out.filter((v, i) => i % 2 === 0 || v === 1);   // many decades: every other power of ten
    return out.length >= 3 ? out : null;   // a very narrow range: Plotly's own ticks
  }

  /* A value axis for effects on the display scale: log for ratios. */
  function valueAxis(res, vals, { log, title, withNull = true, display = false }) {
    const tx = res.measure.log && !display ? Math.exp : (x) => x;
    const xs = vals.filter((v) => v != null && Number.isFinite(v)).map(tx);
    if (withNull) xs.push(res.measure.null);
    if (log) {
      const ls = xs.filter((v) => v > 0).map(Math.log10);
      let a = Math.min(...ls), b = Math.max(...ls);
      if (!(b > a)) { a -= 0.3; b += 0.3; }
      const pad = 0.06 * (b - a);
      const ticks = logTicks(10 ** (a - pad), 10 ** (b + pad));
      const ax = { type: 'log', range: [a - pad, b + pad], title: { text: title }, zeroline: false };
      if (ticks) { ax.tickvals = ticks; ax.ticktext = ticks.map((v) => fmt(v, { sig: 3 })); }
      return ax;
    }
    let a = Math.min(...xs), b = Math.max(...xs);
    if (!(b > a)) { a -= 0.5; b += 0.5; }
    const pad = 0.06 * (b - a);
    return { range: [a - pad, b + pad], title: { text: title }, zeroline: false };
  }

  /* The width a plot may take in the report: the report body less its
     padding, two outline indents and room for a vertical scroll bar that
     may appear once the report is drawn. */
  const availWidth = (ctx) => { const w = (ctx.report && ctx.report.body && ctx.report.body.clientWidth) || 0; return w > 240 ? w - 100 : 900; };

  /* ---- the graphs' code ---------------------------------------------------------------------
     Under each graph, Python that draws it with matplotlib from a CSV export of
     the table: meta.plot_code writes it, the studies and their pooling computed
     as the report's code computes them, from what the page chose (the forest
     plot's options, its columns and its axis range, the order of a sort by
     label; the other graphs' sizes, axis ranges and ticks, the funnel's
     lines). Each graph function fills `info` with those choices. A headless
     run (Bootstrap) draws no graphs and asks for none. */
  const withCode = (ctx, graph, code) => (code ? el('div', { class: 'sm-meta-plotcode' }, graph, ctx.code(code)) : graph);
  async function plotCode(ctx, kind, plot, extra = {}) {
    if (ctx.headless) return null;
    const r = await ctx.call('meta.plot_code', { ...baseArgs(ctx), ...extra, kind, plot });
    return r && !r.error ? r.plot_code : null;
  }
  const axisOf = (ax) => ({ range: ax.range, tickvals: ax.tickvals || null, ticktext: ax.ticktext || null });

  /* ======================================================================
     THE FOREST PLOT
     ====================================================================== */
  function forestItems(ctx, res, o) {
    const items = [];
    const m = res.measure;
    const showFE = o('fShowFE', true), showRE = o('fShowRE', true);
    const both = showFE && showRE;
    const reLabel = `Random effects (${METHOD[res.method]}${res.hksj ? ', HK' : ''})`;
    const sortBy = o('fSort', 'table');
    const order = (list) => {
      const s = list.slice();
      if (sortBy === 'effect') s.sort((a, b) => a.eff - b.eff);
      else if (sortBy === 'weight') s.sort((a, b) => b.w_re - a.w_re);
      else if (sortBy === 'precision') s.sort((a, b) => a.se - b.se);
      else if (sortBy === 'label') s.sort((a, b) => SM.table.collator.compare(a.label, b.label));
      return s;
    };
    const mhOn = !!(o('mhDiamond', false) && res.mh);
    const study = (s) => ({ kind: 'study', label: s.label, est: s.eff, lo: s.lower, hi: s.upper, wFE: mhOn && s.w_mh != null ? s.w_mh : s.w_fe, wRE: s.w_re, row: s.row, s });
    const het = (h, prefix) => {
      const parts = [];
      if (h.i2 != null) parts.push(`I² = ${fmt(100 * h.i2, { digits: 0 })}%`);
      if (h.tau2 != null) parts.push(`τ² = ${fmt(h.tau2, { sig: 3 })}`);
      if (h.q != null && h.df) parts.push(`Q = ${fmt(h.q, { digits: 2 })}, df = ${h.df}, p ${pText(h.p)}`);
      return parts.length ? `${prefix}${parts.join('; ')}` : null;
    };
    items.push({ kind: 'head' });
    if (res.subgroups && o('subgroups', true)) {
      for (const g of res.subgroups.groups) {
        items.push({ kind: 'group', label: g.level });
        const members = res.studies.filter((s) => s.group === g.level);
        for (const s of order(members)) items.push(study(s));
        const wf = members.reduce((a, s) => a + (mhOn && s.w_mh != null ? s.w_mh : s.w_fe), 0), wr = members.reduce((a, s) => a + s.w_re, 0);
        const gfe = mhOn && g.mh ? g.mh : g.fe;
        if (showFE && g.k > 1) items.push({ kind: 'diamond', which: 'fe', sub: true, label: mhOn && g.mh ? 'Subtotal, fixed effect (M–H)' : 'Subtotal, fixed effect', est: gfe.est, lo: gfe.lower, hi: gfe.upper, wFE: wf, wRE: both ? null : wr });
        if (showRE && g.k > 1) items.push({ kind: 'diamond', which: 're', sub: true, label: 'Subtotal, random effects', est: g.re.est, lo: g.re.lower, hi: g.re.upper, wFE: both ? null : wf, wRE: wr });
        if (o('fStats', true) && g.k > 1) {
          const t = het({ i2: g.i2, tau2: showRE ? g.tau2 : null, q: g.q, df: g.df, p: g.p }, 'Heterogeneity: ');
          if (t) items.push({ kind: 'text', label: t });
        }
        items.push({ kind: 'gap' });
      }
    } else {
      for (const s of order(res.studies)) items.push(study(s));
      items.push({ kind: 'gap' });
    }
    const ch = res.chosen;
    const feD = mhOn ? res.mh : ch.fe;
    if (showFE) items.push({ kind: 'diamond', which: 'fe', label: mhOn ? 'Fixed effect (Mantel–Haenszel)' : 'Fixed effect', est: feD.est, lo: feD.lower, hi: feD.upper, wFE: 1, wRE: both ? null : 1 });
    if (showRE) items.push({ kind: 'diamond', which: 're', label: reLabel, est: ch.re.est, lo: ch.re.lower, hi: ch.re.upper, wFE: both ? null : 1, wRE: 1 });
    if (showRE && o('fShowPI', true) && res.pi) items.push({ kind: 'pi', label: 'Prediction interval', est: res.pi.est, lo: res.pi.lower, hi: res.pi.upper });
    if (o('fStats', true)) {
      const h = res.het;
      const t = het({ i2: h.i2, tau2: showRE ? h.tau2 : null, q: h.q, df: h.df, p: h.p }, 'Heterogeneity: ');
      if (t && res.k > 1) items.push({ kind: 'text', label: t });
      const main = showRE ? ch.re : ch.fe;
      if (main && main.p != null) items.push({ kind: 'text', label: `Test for overall effect${showRE ? ' (random)' : ''}: ${main.df ? 't' : 'z'} = ${fmt(main.z, { digits: 2 })}, p ${pText(main.p)}` });
      if (res.subgroups && o('subgroups', true) && res.subgroups.tests.length) {
        const tt = res.subgroups.tests[showRE ? 1 : 0];
        items.push({ kind: 'text', label: `Test for subgroup differences (${showRE ? 'random' : 'fixed'}): Q = ${fmt(tt.q, { digits: 2 })}, df = ${tt.df}, p ${pText(tt.p)}` });
      }
    }
    return { items, showFE, showRE, both, mhOn };
  }

  function forestPlot(ctx, res, o, info = {}) {
    const c = colors();
    const m = res.measure;
    const tx = m.log ? Math.exp : (x) => x;
    const log = m.log && o('fLog', true);
    const { items, showFE, showRE, both, mhOn } = forestItems(ctx, res, o);
    const dec = decimals(res);
    // y positions: a gap is half a row
    let y = 0;
    const H_ROW = 20;
    for (const it of items) {
      if (it.kind === 'head') { it.y = -1.25; continue; }
      if (it.kind === 'gap') { y += 0.5; it.y = null; continue; }
      it.y = y;
      y += 1;
    }
    const last = y - 1;
    const rowsY = items.filter((it) => it.y != null && it.kind !== 'head');
    // column widths in px
    const labels = rowsY.map((it) => (it.kind === 'text' ? '' : String(it.label || '').slice(0, 36)));
    const labW = Math.max(96, Math.min(240, 14 + 6.7 * Math.max(5, ...labels.map((s) => s.length))));
    const ciText = (it) => `${fd(tx(it.est), dec)} [${fd(tx(it.lo), dec)}, ${fd(tx(it.hi), dec)}]`;
    const cis = rowsY.filter((it) => ['study', 'diamond', 'pi'].includes(it.kind)).map(ciText);
    const ciW = Math.max(110, 18 + 6.6 * Math.max(...cis.map((s) => s.length), 10));
    const weights = o('fWeights', true);
    const wCols = weights ? (both ? [['wFE', 'Weight<br>fixed'], ['wRE', 'Weight<br>random']] : [[showRE ? 'wRE' : 'wFE', 'Weight']]) : [];
    const wW = 62;
    const plotW = Math.max(220, Math.min(460, availWidth(ctx) - labW - ciW - wW * wCols.length - 30));
    const W = Math.round(labW + plotW + ciW + wW * wCols.length + 16);
    const Hpx = Math.round((last + 3.4) * H_ROW + 66);
    const inner = W - 16;
    let at = 0;
    const dom = (w) => { const d = [at / inner, Math.min(1, (at + w) / inner)]; at += w; return d; };
    const dLab = dom(labW), dPlot = dom(plotW), dCi = dom(ciW), dW = wCols.map(() => dom(wW));
    const hidden = { range: [0, 1], showgrid: false, zeroline: false, showline: false, showticklabels: false, ticks: '', fixedrange: true };
    const traces = [];
    const textTrace = (axis, x, list, pos, extra = {}) => ({ type: 'scatter', mode: 'text', xaxis: axis, yaxis: 'y', x: list.map(() => x), y: list.map((d) => d.y), text: list.map((d) => d.t), textposition: pos, cliponaxis: false, hoverinfo: 'skip', showlegend: false, textfont: { size: 11, color: c.text }, ...extra });
    // study labels, bold group headers, statistics lines in the muted ink
    const cutLabel = (l) => { const t = String(l || ''); return t.length > 36 ? `${t.slice(0, 35)}…` : t; };
    const labList = rowsY.filter((it) => it.kind !== 'text').map((it) => ({ y: it.y, t: it.kind === 'group' || it.kind === 'diamond' && !it.sub ? `<b>${T(cutLabel(it.label))}</b>` : T(cutLabel(it.label)) }));
    traces.push(textTrace('x2', 0.01, labList, 'middle right'));
    const statList = rowsY.filter((it) => it.kind === 'text').map((it) => ({ y: it.y, t: T(it.label) }));
    if (statList.length) traces.push(textTrace('x2', 0.01, statList, 'middle right', { textfont: { size: 10.5, color: c.muted } }));
    // the header
    const head = [{ axis: 'x2', x: 0.01, t: '<b>Study</b>', pos: 'middle right' }, { axis: 'x3', x: 0.99, t: `<b>${T(m.display)} [${lvText(res.alpha)} CI]</b>`, pos: 'middle left' }];
    wCols.forEach(([, lab], i) => head.push({ axis: `x${4 + i}`, x: 0.97, t: `<b>${lab}</b>`, pos: 'middle left' }));
    for (const h of head) traces.push(textTrace(h.axis, h.x, [{ y: -1.25, t: h.t }], h.pos));
    // effect [CI] and weights
    const valued = rowsY.filter((it) => ['study', 'diamond', 'pi'].includes(it.kind));
    traces.push(textTrace('x3', 0.99, valued.map((it) => ({ y: it.y, t: it.kind === 'diamond' && !it.sub ? `<b>${ciText(it)}</b>` : ciText(it) })), 'middle left'));
    wCols.forEach(([key], i) => {
      const list = valued.filter((it) => it[key] != null).map((it) => ({ y: it.y, t: `${fmt(100 * it[key], { digits: 1 })}%` }));
      traces.push(textTrace(`x${4 + i}`, 0.97, list, 'middle left'));
    });
    // The axis covers every estimate and the pooled intervals, and the study
    // intervals up to 60% of that span beyond; longer ones end in an arrow.
    const st = rowsY.filter((it) => it.kind === 'study');
    const f = log ? Math.log10 : (x) => x;
    const core = [m.null, ...st.map((it) => tx(it.est)), ...rowsY.filter((it) => it.kind === 'diamond' || it.kind === 'pi').flatMap((it) => [tx(it.lo), tx(it.hi)])].filter(Number.isFinite);
    const full = core.concat(st.flatMap((it) => [tx(it.lo), tx(it.hi)])).filter(Number.isFinite);
    const a = Math.min(...core.map(f)), b = Math.max(...core.map(f));
    const span = Math.max(b - a, log ? 0.3 : Math.abs(b) * 0.1 || 1);
    const ext = [Math.max(Math.min(...full.map(f)), a - 0.6 * span), Math.min(Math.max(...full.map(f)), b + 0.6 * span)];
    const xa = valueAxis(res, log ? ext.map((v) => 10 ** v) : ext, { log, title: `${m.display}${log ? ' (log scale)' : ''}`, display: true });
    const edge = log ? xa.range.map((v) => 10 ** v) : xa.range;
    const segX = [], segY = [], arrows = { l: [], r: [] };
    for (const it of st) {
      const lo = tx(it.lo), hi = tx(it.hi);
      segX.push(Math.max(lo, edge[0]), Math.min(hi, edge[1]), null);
      segY.push(it.y, it.y, null);
      if (lo < edge[0]) arrows.l.push(it.y);
      if (hi > edge[1]) arrows.r.push(it.y);
    }
    traces.push({ type: 'scatter', mode: 'lines', x: segX, y: segY, line: { color: c.ci, width: 1.2 }, hoverinfo: 'skip', showlegend: false, name: 'Confidence intervals' });
    for (const [side, ys] of Object.entries(arrows)) {
      if (!ys.length) continue;
      traces.push({ type: 'scatter', mode: 'markers', x: ys.map(() => edge[side === 'l' ? 0 : 1]), y: ys, marker: { symbol: side === 'l' ? 'triangle-left' : 'triangle-right', size: 8, color: c.ci }, cliponaxis: false, hoverinfo: 'skip', showlegend: false, name: 'Interval continues' });
    }
    // the null line and the pooled estimate's line, over the studies and the diamonds
    const y0 = -0.5, y1 = Math.max(...rowsY.filter((it) => ['study', 'diamond', 'pi'].includes(it.kind)).map((it) => it.y)) + 0.5;
    traces.push({ type: 'scatter', mode: 'lines', x: [m.null, m.null], y: [y0, y1], line: { color: c.muted, width: 1 }, hoverinfo: 'skip', showlegend: false, name: 'No effect' });
    const mainD = items.filter((it) => it.kind === 'diamond' && !it.sub);
    const main = mainD.find((it) => it.which === 're') || mainD[0];
    if (main && o('fPooledLine', true)) traces.push({ type: 'scatter', mode: 'lines', x: [tx(main.est), tx(main.est)], y: [y0, y1], line: { color: main.which === 're' ? c.re : c.fe, width: 1, dash: 'dot' }, hoverinfo: 'skip', showlegend: false, name: 'Pooled estimate' });
    // diamonds and the prediction interval
    for (const it of items.filter((d) => d.kind === 'diamond')) {
      const col = it.which === 're' ? c.re : c.fe;
      const h = it.sub ? 0.3 : 0.36;
      traces.push({ type: 'scatter', mode: 'lines', fill: 'toself', x: [tx(it.lo), tx(it.est), tx(it.hi), tx(it.est), tx(it.lo)], y: [it.y, it.y - h, it.y, it.y + h, it.y],
        line: { color: col, width: 1 }, fillcolor: it.sub ? withAlpha(col, 0.55) : col, hoveron: 'fills', hoverinfo: 'text',
        text: `${T(it.label)}: ${ciText(it)}`, showlegend: false, name: it.label });
    }
    for (const it of items.filter((d) => d.kind === 'pi')) {
      traces.push({ type: 'scatter', mode: 'lines', x: [tx(it.lo), tx(it.hi)], y: [it.y, it.y], line: { color: c.re, width: 3 }, hoverinfo: 'text', text: `${T(it.label)}: ${fd(tx(it.lo), dec)} to ${fd(tx(it.hi), dec)}`, showlegend: false, name: it.label });
      traces.push({ type: 'scatter', mode: 'lines', x: [tx(it.lo), tx(it.lo), null, tx(it.hi), tx(it.hi)], y: [it.y - 0.22, it.y + 0.22, null, it.y - 0.22, it.y + 0.22], line: { color: c.re, width: 1.5 }, hoverinfo: 'skip', showlegend: false });
    }
    // the studies' squares, last so they are on top: linked to their rows
    const wKey = showRE ? 'wRE' : 'wFE';
    const wmax = Math.max(...st.map((it) => it[wKey]), 1e-12);
    traces.push({
      type: 'scatter', mode: 'markers', x: st.map((it) => tx(it.est)), y: st.map((it) => it.y), rows: st.map((it) => it.row),
      marker: { symbol: 'square', color: c.study, size: st.map((it) => Math.max(5, 17 * Math.sqrt(it[wKey] / wmax))), line: { width: 0 } },
      hovertext: st.map((it) => `${T(it.label)}: ${ciText(it)}, weight ${fmt(100 * it[wKey], { digits: 1 })}%`), hovertemplate: '%{hovertext}<extra></extra>', name: 'Studies',
    });
    const layout = {
      margin: { l: 8, r: 8, t: 22, b: 44 },   // the top margin keeps Plotly's toolbar off the header
      xaxis: { ...xa, domain: dPlot, anchor: 'y', showgrid: false, ticks: 'outside' },
      xaxis2: { ...hidden, domain: dLab, anchor: 'y' },
      xaxis3: { ...hidden, domain: dCi, anchor: 'y' },
      yaxis: { range: [last + 0.9, -2.15], showgrid: false, zeroline: false, showline: false, showticklabels: false, ticks: '', fixedrange: true },
      shapes: [{ type: 'line', xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: -0.55, y1: -0.55, line: { color: c.grid, width: 1 } }],
      hovermode: 'closest',
    };
    dW.forEach((d, i) => { layout[`xaxis${4 + i}`] = { ...hidden, domain: d, anchor: 'y' }; });
    const plot = ctx.plot(traces, layout, { width: W, height: Hpx, title: `Forest plot of ${m.plural || m.display}`, fit: false });
    const sortBy = o('fSort', 'table');
    Object.assign(info, {
      showFE, showRE, showPI: o('fShowPI', true), weights, stats: o('fStats', true), pooledLine: o('fPooledLine', true), log, sort: sortBy,
      subgroups: !!(res.subgroups && o('subgroups', true)), mh: mhOn,
      labelOrder: sortBy === 'label' ? res.studies.slice().sort((a, b) => SM.table.collator.compare(a.label, b.label)).map((s) => s.row) : null,
      layout: { W, H: Hpx, lab: dLab, plot: dPlot, ci: dCi, w: dW, ...axisOf(xa) },
    });
    return el('div', { class: 'sm-meta-scroll' }, plot);
  }

  /* ======================================================================
     SMALL PLOTS: leave-one-out, cumulative, funnel, bubbles
     ====================================================================== */
  function miniForest(ctx, res, rows, labels, full, title, info = {}) {
    const c = colors();
    const m = res.measure;
    const tx = m.log ? Math.exp : (x) => x;
    const log = m.log && ctx.opt('fLog', true);
    const n = rows.length;
    const segX = [], segY = [];
    rows.forEach((r, i) => { segX.push(tx(r.lower), tx(r.upper), null); segY.push(i, i, null); });
    const traces = [
      { type: 'scatter', mode: 'lines', x: [m.null, m.null], y: [-0.5, n - 0.5], line: { color: c.muted, width: 1 }, hoverinfo: 'skip', name: 'No effect' },
      { type: 'scatter', mode: 'lines', x: [tx(full), tx(full)], y: [-0.5, n - 0.5], line: { color: c.re, width: 1, dash: 'dot' }, hoverinfo: 'skip', name: 'All studies' },
      { type: 'scatter', mode: 'lines', x: segX, y: segY, line: { color: c.ci, width: 1.2 }, hoverinfo: 'skip', name: 'Intervals' },
      { type: 'scatter', mode: 'markers', x: rows.map((r) => tx(r.est)), y: rows.map((_, i) => i), rows: rows.map((r) => r.row), marker: { symbol: 'diamond', size: 9, color: c.study },
        hovertext: labels.map((l, i) => `${T(l)}: ${fmt(tx(rows[i].est), { sig: 4 })} [${fmt(tx(rows[i].lower), { sig: 4 })}, ${fmt(tx(rows[i].upper), { sig: 4 })}]`), hovertemplate: '%{hovertext}<extra></extra>', name: 'Estimates' },
    ];
    const xa = valueAxis(res, rows.flatMap((r) => [r.lower, r.upper]).concat([full]), { log, title: `${m.display}${log ? ' (log scale)' : ''}` });
    const longest = Math.max(4, ...labels.map((l) => String(l).length));
    const width = Math.min(620, Math.max(380, 300 + 6.6 * longest)), height = Math.round(22 * n + 64);
    Object.assign(info, { log, width, height, ...axisOf(xa) });
    return ctx.plot(traces, {
      xaxis: { ...xa, showgrid: false },
      yaxis: { tickvals: rows.map((_, i) => i), ticktext: labels.map(T), range: [n - 0.4, -0.6], showgrid: false, zeroline: false, ticks: '', automargin: true },
      margin: { l: Math.min(220, 12 + 6.6 * longest), r: 14, t: 6, b: 42 },
    }, { width, height, title });
  }

  function funnelPlot(ctx, res, b, o, info = {}) {
    const c = colors();
    const m = res.measure;
    const tx = m.log ? Math.exp : (x) => x;
    const log = m.log && ctx.opt('fLog', true);
    const smax = Math.max(...b.se) * 1.08;
    const z = SM.util.qnorm(1 - ctx.alpha / 2);
    const traces = [];
    if (o('fnLimits', true)) {
      traces.push({ type: 'scatter', mode: 'lines', x: [tx(b.fe - z * smax), tx(b.fe), tx(b.fe + z * smax)], y: [smax, 0, smax], line: { color: c.muted, width: 1, dash: 'dash' }, hoverinfo: 'skip', name: `Pseudo ${lvText(ctx.alpha)} limits` });
    }
    traces.push({ type: 'scatter', mode: 'lines', x: [tx(b.fe), tx(b.fe)], y: [0, smax], line: { color: c.fe, width: 1 }, hoverinfo: 'skip', name: 'Fixed effect' });
    if (o('fnRE', false)) traces.push({ type: 'scatter', mode: 'lines', x: [tx(b.re), tx(b.re)], y: [0, smax], line: { color: c.re, width: 1, dash: 'dot' }, hoverinfo: 'skip', name: 'Random effects' });
    if (o('fnEggerLine', false) && b.egger) {
      const e = b.egger;
      traces.push({ type: 'scatter', mode: 'lines', x: [tx(e.slope), tx(e.slope + e.intercept * smax)], y: [0, smax], line: { color: c.re, width: 1.5 }, hoverinfo: 'skip', name: 'Egger\'s line' });
    }
    traces.push({ type: 'scatter', mode: 'markers', x: b.eff.map(tx), y: b.se, rows: b.rows, marker: { size: 8, color: c.study, line: { color: c.surface, width: 1 } },
      hovertext: b.labels.map((l, i) => `${T(l)}: ${fmt(tx(b.eff[i]), { sig: 4 })}, SE ${fmt(b.se[i], { sig: 4 })}`), hovertemplate: '%{hovertext}<extra></extra>', name: 'Studies' });
    const lim = o('fnLimits', true) ? [b.fe - z * smax, b.fe + z * smax] : [];
    const xa = valueAxis(res, b.eff.concat(lim), { log, title: `${m.display}${log ? ' (log scale)' : ''}`, withNull: false });
    const width = Math.min(520, Math.max(320, availWidth(ctx) - 20));
    Object.assign(info, { log, limits: o('fnLimits', true), re: o('fnRE', false), egger: !!(o('fnEggerLine', false) && b.egger), width, height: 340, ...axisOf(xa) });
    return ctx.plot(traces, { xaxis: { ...xa }, yaxis: { title: { text: 'Standard Error' }, range: [smax, 0], zeroline: false }, margin: { l: 58, r: 14, t: 8, b: 42 } },
      { width, height: 340, title: `Funnel plot of ${m.plural || m.display}` });
  }

  function bubblePlot(ctx, mr, cv, res, info = {}) {
    const c = colors();
    const m = mr.measure;
    const tx = m.log ? Math.exp : (x) => x;
    const log = m.log && ctx.opt('fLog', true);
    const wmax = Math.max(...mr.w);
    const traces = [
      { type: 'scatter', mode: 'lines', x: cv.grid, y: cv.upper.map(tx), line: { width: 0, color: c.re }, hoverinfo: 'skip', name: 'Upper' },
      { type: 'scatter', mode: 'lines', x: cv.grid, y: cv.lower.map(tx), line: { width: 0, color: c.re }, fill: 'tonexty', fillcolor: c.dark ? 'rgba(208,88,78,0.16)' : 'rgba(176,65,62,0.13)', hoverinfo: 'skip', name: `${lvText(ctx.alpha)} confidence band` },
      { type: 'scatter', mode: 'lines', x: cv.grid, y: cv.fit.map(tx), line: { color: c.re, width: 2 }, hoverinfo: 'skip', name: 'Fit' },
      { type: 'scatter', mode: 'lines', x: [Math.min(...cv.grid), Math.max(...cv.grid)], y: [m.null, m.null], line: { color: c.muted, width: 1 }, hoverinfo: 'skip', name: 'No effect' },
      { type: 'scatter', mode: 'markers', x: cv.x, y: mr.eff.map(tx), rows: mr.rows,
        marker: { size: mr.w.map((w) => Math.max(6, 34 * Math.sqrt(w / wmax))), color: c.dark ? 'rgba(77,138,214,0.55)' : 'rgba(42,109,179,0.5)', line: { color: c.study, width: 1 } },
        hovertext: mr.rows.map((r, i) => `${T(mr.labels ? mr.labels[i] : `row ${r + 1}`)}: ${fmt(tx(mr.eff[i]), { sig: 4 })}, weight ${fmt(100 * mr.w[i], { digits: 1 })}%`), hovertemplate: '%{hovertext}<extra></extra>', name: 'Studies' },
    ];
    const ya = valueAxis({ measure: m }, mr.eff.concat(cv.lower, cv.upper), { log, title: `${m.display}${log ? ' (log scale)' : ''}` });
    const width = Math.min(520, Math.max(320, availWidth(ctx) - 20));
    Object.assign(info, { covariate: cv.covariate, log, width, height: 330, ...axisOf(ya) });
    return ctx.plot(traces, { xaxis: { title: { text: T(cv.covariate) } }, yaxis: ya, margin: { l: 60, r: 14, t: 8, b: 42 } },
      { width, height: 330, title: `Bubble plot of ${m.display} by ${cv.covariate}` });
  }

  /* ======================================================================
     THE REPORT
     ====================================================================== */
  function estimateColumns(res, { t = false, scale = 'effect' } = {}) {
    const lv = lvText(res.alpha);
    const m = res.measure;
    const cols = [{ key: 'model', label: 'Model', fmt: 'text' }, { key: 'method', label: 'Method', fmt: 'text' }];
    if (scale === 'ratio') {
      cols.push({ key: 'ratio', label: m.display }, { key: 'ratio_lower', label: `Lower ${lv}` }, { key: 'ratio_upper', label: `Upper ${lv}` });
    } else {
      cols.push({ key: 'est', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'lower', label: `Lower ${lv}` }, { key: 'upper', label: `Upper ${lv}` });
    }
    if (scale !== 'log') {
      cols.push({ key: 'z', label: t ? 't Ratio' : 'z Ratio' });
      if (t) cols.push({ key: 'df', label: 'DF', fmt: 'int' });
      cols.push({ key: 'p', label: t ? 'Prob>|t|' : 'Prob>|z|', fmt: 'p' }, { key: 'tau2', label: 'τ²' });
    }
    return cols;
  }

  /* One table of estimates; for a ratio the ratio table, then the log scale. */
  function estimateTables(ctx, res, rows, { t = false, caption = null } = {}) {
    const m = res.measure;
    if (!m.log) return [ctx.rt({ caption, columns: estimateColumns(res, { t }), rows }, { sortable: false })];
    return [ctx.rt({ caption, columns: estimateColumns(res, { t, scale: 'ratio' }), rows }, { sortable: false }),
      ctx.rt({ caption: `${caption ? `${caption}: ` : ''}${m.effect}`, columns: estimateColumns(res, { t, scale: 'log' }), rows }, { sortable: false })];
  }

  function summaryOutline(ctx, res, parent) {
    const ob = ctx.outline('Summary Estimates', { parent, key: 'summary', info: 'p:meta:summary', menu: () => [
      { label: 'Random-Effects Method', submenu: () => methodItems(ctx) },
      ctx.check('Hartung–Knapp Intervals', 'hksj', null, false),
      res.mh ? ctx.check('Mantel–Haenszel Fixed Effect in the Forest Plot', 'mhDiamond', null, false) : null,
    ].filter(Boolean) });
    const lv = lvText(res.alpha);
    const rows = res.pooled.map((p) => ({ ...p, model: p.key === res.method ? `${p.model} ◆` : p.model, tau2: p.tau2 }));
    ob.add(...estimateTables(ctx, res, rows));
    if (res.hksj_rows && res.hksj_rows.length && ctx.opt('hksj', false)) {
      ob.add(...estimateTables(ctx, res, res.hksj_rows.map((p) => ({ ...p, model: p.key === res.method ? 'Random effects ◆' : 'Random effects' })), { t: true, caption: 'Hartung–Knapp–Sidik–Jonkman' }));
    }
    if (res.pi) {
      const m = res.measure;
      const cols = [{ key: 'what', label: 'Model', fmt: 'text' }];
      if (m.log) cols.push({ key: 'ratio_lower', label: `${m.display} Lower ${lv}` }, { key: 'ratio_upper', label: `${m.display} Upper ${lv}` });
      cols.push({ key: 'lower', label: `${m.log ? `${m.effect} ` : ''}Lower ${lv}` }, { key: 'upper', label: `${m.log ? `${m.effect} ` : ''}Upper ${lv}` }, { key: 'df', label: 'DF (t)', fmt: 'int' });
      ob.add(ctx.rt({ caption: 'Prediction Interval', columns: cols, rows: [{ ...res.pi, what: `Random effects (${METHOD[res.method]})` }] }, { sortable: false }));
    }
    const notes = [
      `◆ marks the random-effects method of the plots (${METHOD[res.method]}; change it in the red triangle > Random-Effects Method).`,
      `The fixed effect weights each study by 1/variance; the random effects by 1/(variance + τ²). DerSimonian–Laird (statsmodels' "chi2") and Paule–Mandel ("iterated") are statsmodels' combine_effects; REML is not in statsmodels: its τ² is the root of the restricted-likelihood score (scipy), the estimate statsmodels' WLS with those weights.`,
      `The intervals are normal (Wald) intervals and the tests z tests, as RevMan and metafor's rma give by default${res.hksj ? '; Hartung–Knapp uses the WLS scale and t with k − 1 degrees of freedom (metafor test = "knha")' : '; Hartung–Knapp (red triangle) widens them with t on k − 1 degrees of freedom'}. metafor's rma defaults to REML, RevMan 5 to DerSimonian–Laird${res.mh ? ' (and Mantel–Haenszel for odds ratios, from statsmodels\' StratifiedTable, with the Robins–Breslow–Greenland standard error)' : ''}.`,
      res.pi ? `The prediction interval, where the effect of a new study is expected, is μ̂ ± t(k − 2)·√(τ² + SE²) (Higgins, Thompson and Spiegelhalter 2009, as R's meta); metafor's predict uses the normal quantile instead.` : 'A prediction interval needs three studies or more.',
    ];
    if (res.raw_tau2_dl != null && res.raw_tau2_dl < 0) notes.push(`Q is below its degrees of freedom: statsmodels leaves the DerSimonian–Laird τ² at (Q − df)/C = ${fmt(res.raw_tau2_dl)}; the estimator is max(0, ·) = 0, so the random effects are the fixed effect.`);
    ob.add(...notes.map((t) => ctx.note(t)));
    if (res.measure.log) ob.add(ctx.note(`The pooling is done on the log scale (${res.measure.effect}, the second table); the ${res.measure.display.toLowerCase()}s and their intervals are its exponentials.`));
    ob.add(ctx.code(res.code));
    return ob;
  }

  function heterogeneityOutline(ctx, res, parent) {
    const ob = ctx.outline('Heterogeneity', { parent, key: 'het', info: 'p:meta:heterogeneity' });
    const h = res.het;
    const lv = lvText(res.alpha);
    if (res.k < 2) { ob.add(ctx.note('One study: no heterogeneity to measure.')); return ob; }
    ob.add(ctx.rt({ caption: 'Test of Homogeneity', columns: [{ key: 'what', label: 'Test', fmt: 'text' }, { key: 'q', label: 'Q' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'p', label: 'Prob > ChiSq', fmt: 'p' }],
      rows: [{ what: 'Cochran\'s Q', q: h.q, df: h.df, p: h.p }] }, { sortable: false }));
    const meth = METHOD[res.method];
    ob.add(ctx.rt({ caption: 'Heterogeneity Measures', columns: [{ key: 'stat', label: 'Statistic', fmt: 'text' }, { key: 'est', label: 'Estimate' }, { key: 'lo', label: `Lower ${lv}` }, { key: 'hi', label: `Upper ${lv}` }, { key: 'how', label: 'Interval', fmt: 'text' }],
      rows: [
        { stat: 'I² (%)', est: pct(h.i2), lo: pct(h.i2_lower), hi: pct(h.i2_upper), how: 'Higgins–Thompson' },
        { stat: 'H', est: h.h, lo: h.h_lower, hi: h.h_upper, how: 'Higgins–Thompson' },
        { stat: `τ² (${meth})`, est: h.tau2, lo: h.tau2_lower, hi: h.tau2_upper, how: 'Q-profile' },
        { stat: `τ (${meth})`, est: h.tau, lo: h.tau_lower, hi: h.tau_upper, how: 'Q-profile' },
      ] }, { sortable: false }));
    ob.add(ctx.kv([['Typical within-study variance s²', h.s2], ['H² = Q/df (statsmodels h2)', h.h2_raw]]));
    const notes = ['I² = (Q − df)/Q is the share of the variability between studies; H = √(Q/df). Their intervals are Higgins and Thompson\'s (2002), from the standard error of ln H, as R\'s meta reports them. The τ² interval is Viechtbauer\'s (2007) Q-profile (metafor\'s confint), the same whichever estimator gives τ².'];
    if (h.i2_raw < 0) notes.push(`Q is below its degrees of freedom: statsmodels' i2 is ${fmt(100 * h.i2_raw, { sig: 4 })}% and h2 ${fmt(h.h2_raw, { sig: 4 })}; I² is shown at 0 and H at 1, as usual.`);
    if (res.k < 3) notes.push('With two studies the intervals of I² and H are not defined.');
    ob.add(...notes.map((t) => ctx.note(t)));
    return ob;
  }

  function subgroupOutline(ctx, res, parent) {
    const sg = res.subgroups;
    const ob = ctx.outline('Subgroups', { parent, key: 'subgroups', info: 'p:meta:subgroups' });
    const m = res.measure;
    const lv = lvText(res.alpha);
    const s = m.log ? (SHORT[m.display] || m.display) : '';
    const tx = m.log ? Math.exp : (x) => x;
    const gname = ctx.name('group') || 'Group';
    ob.add(ctx.rt({
      columns: [{ key: 'level', label: gname, fmt: 'text' }, { key: 'k', label: 'k', fmt: 'int' }, { key: 'fe', label: m.log ? `${s} (fixed)` : 'Fixed' }, { key: 're', label: m.log ? `${s} (random)` : 'Random' },
        { key: 'lo', label: `Lower ${lv}` }, { key: 'hi', label: `Upper ${lv}` }, { key: 'p', label: 'Prob>|z|', fmt: 'p' }, { key: 'q', label: 'Q' }, { key: 'df', label: 'DF', fmt: 'int' },
        { key: 'qp', label: 'Prob > ChiSq', fmt: 'p' }, { key: 'i2', label: 'I² (%)' }, { key: 'tau2', label: 'τ²' },
        ...(m.key === 'or' ? [{ key: 'mh', label: 'OR (M–H)', hidden: !ctx.opt('mhDiamond', false) }] : [])],
      rows: sg.groups.map((g) => ({ level: g.level, k: g.k, fe: tx(g.fe.est), re: tx(g.re.est), lo: tx(g.re.lower), hi: tx(g.re.upper), p: g.re.p, q: g.q, df: g.df, qp: g.p, i2: pct(g.i2), tau2: g.tau2, mh: g.mh ? g.mh.ratio : null })),
    }, { sortable: false }));
    if (sg.tests.length) {
      ob.add(ctx.rt({ caption: 'Test of Subgroup Differences', columns: [{ key: 'model', label: 'Model', fmt: 'text' }, { key: 'q', label: 'Q Between' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'p', label: 'Prob > ChiSq', fmt: 'p' }, { key: 'i2', label: 'I² (%)' }],
        rows: sg.tests.map((t) => ({ ...t, i2: pct(t.i2) })) }, { sortable: false }));
      ob.add(ctx.note(`Each subgroup is pooled on its own (its own τ²). Q between is the Q of the subgroup estimates (statsmodels' combine_effects on them): for the fixed effect it equals Q total − Σ Q within; the random-effects test is RevMan's. A model with one τ² for all subgroups is the Meta-Regression on ${gname}.`));
    } else ob.add(ctx.note('One subgroup only: nothing to compare.'));
    return ob;
  }

  function studyTable(ctx, res, parent) {
    const ob = ctx.outline('Study Effects', { parent, key: 'studies', closed: true });
    const m = res.measure;
    const lv = lvText(res.alpha);
    const cols = [{ key: 'label', label: 'Study', fmt: 'text' }];
    if (res.subgroups) cols.push({ key: 'group', label: ctx.name('group') || 'Group', fmt: 'text' });
    cols.push({ key: 'eff', label: m.effect }, { key: 'se', label: 'Std Error' }, { key: 'lower', label: `Lower ${lv}` }, { key: 'upper', label: `Upper ${lv}` });
    if (m.log) cols.push({ key: 'ratio', label: m.display }, { key: 'ratio_lower', label: `${SHORT[m.display] || m.display} Lower ${lv}` }, { key: 'ratio_upper', label: `${SHORT[m.display] || m.display} Upper ${lv}` });
    cols.push({ key: 'wf', label: 'Weight % (fixed)', digits: 2 }, { key: 'wr', label: `Weight % (random, ${METHOD[res.method]})`, digits: 2 }, { key: 'p', label: 'Prob>|z|', fmt: 'p', hidden: true });
    ob.add(ctx.rt({ columns: cols, rows: res.studies.map((s) => ({ ...s, wf: pct(s.w_fe), wr: pct(s.w_re) })) }, { onRow: (row) => ctx.table.select([row.row]) }),
      ctx.note('Click a line to select the study\'s row. Study intervals are normal: effect ± z·SE.'));
    return ob;
  }

  async function funnelOutline(ctx, res, parent) {
    const o = (k, d) => ctx.opt(k, d);
    const ob = ctx.outline('Funnel Plot', { parent, key: 'funnel', info: 'p:meta:funnel', menu: () => [
      ctx.check('Pseudo Confidence Limits', 'fnLimits', null, true), ctx.check('Random-Effects Estimate', 'fnRE', null, false), ctx.check('Egger\'s Line', 'fnEggerLine', null, false),
      { separator: true }, ctx.check('Egger\'s Regression Test', 'egger', null, true), ctx.check('Begg\'s Rank Correlation', 'begg', null, true),
      { separator: true }, { label: 'Remove', action: () => ctx.set('funnel', false) },
    ] });
    const args = baseArgs(ctx);
    delete args.hksj;   // the funnel's tests do not depend on it
    const b = await ctx.call('meta.bias', args);
    if (b.error) { ob.add(ctx.warn(b.error)); return; }
    const fInfo = {};
    const fg = funnelPlot(ctx, res, b, o, fInfo);
    ob.add(withCode(ctx, fg, await plotCode(ctx, 'funnel', fInfo, { hksj: false })));
    ob.add(ctx.note(`Each study's ${res.measure.effect.toLowerCase()} against its standard error, the most precise at the top; the dashed lines are the pseudo ${lvText(ctx.alpha)} limits around the fixed effect, where the studies would fall without heterogeneity or small-study effects. Click or drag to select studies.`));
    const lv = lvText(ctx.alpha);
    if (b.same_se) { ob.add(ctx.note('Every study has the same standard error: there is no regression on the precision and no rank correlation with the variance.')); return; }
    if (!b.egger) { ob.add(ctx.note('The tests need three studies or more.')); return; }
    if (o('egger', true)) {
      const e = b.egger;
      const eg = ctx.outline('Egger\'s Regression Test', { parent: ob, key: 'egger' });
      eg.add(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'est', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }, { key: 'lo', label: `Lower ${lv}` }, { key: 'hi', label: `Upper ${lv}` }],
        rows: [{ term: 'Intercept (bias)', est: e.intercept, se: e.se, t: e.t, p: e.p, lo: e.lower, hi: e.upper }, { term: 'Slope (precision)', est: e.slope, se: e.slope_se, t: e.slope_t, p: e.slope_p, lo: e.slope_lower, hi: e.slope_upper }] }, { sortable: false }),
        ctx.kv([['DF', e.df, 'int'], ['Studies', b.k, 'int']]),
        ctx.note(`Ordinary least squares (statsmodels OLS) of the standardized effect, effect/SE, on the precision, 1/SE (Egger et al. 1997): an intercept away from zero is evidence of small-study effects (asymmetry). This is the classic test, metafor's regtest(model = "lm"); metafor's default regresses on the standard error in a random-effects meta-regression.`),
        ctx.code(b.code));
    }
    if (o('begg', true)) {
      const bg = ctx.outline('Begg\'s Rank Correlation', { parent: ob, key: 'begg' });
      bg.add(ctx.kv([['Kendall\'s τ', b.begg.tau], ['Prob>|τ|', b.begg.p, 'p'], ['Studies', b.begg.n, 'int']]),
        ctx.note('Kendall\'s τ-b between the standardized effects (y − ŷ)/√(v − 1/Σw) and the variances (Begg and Mazumdar 1994), by scipy\'s kendalltau: an exact p-value for fewer than 50 studies without ties, the normal approximation otherwise.'));
    }
    if (b.k < 10) ob.add(ctx.warn(`With ${b.k} studies the tests for small-study effects have little power; the Cochrane Handbook advises them from about ten studies.`));
    ob.add(ctx.note('Trim and fill is not offered here.'));
  }

  async function looOutline(ctx, res, parent) {
    const ob = ctx.outline('Leave-One-Out', { parent, key: 'loo', info: 'p:meta:loo', menu: () => [ctx.check('Show Plot', 'looPlot', null, true), { label: 'Remove', action: () => ctx.set('loo', false) }] });
    const r = await ctx.call('meta.leave_one_out', baseArgs(ctx));
    if (r.error) { ob.add(ctx.note(r.error)); return; }
    const m = r.measure;
    const lv = lvText(ctx.alpha);
    if (ctx.opt('looPlot', true)) {
      const info = {};
      const g = miniForest(ctx, res, r.rows, r.rows.map((x) => `without ${x.label}`), r.full.est, 'Leave-one-out estimates', info);
      ob.add(withCode(ctx, g, await plotCode(ctx, 'loo', info)));
    }
    const cols = [{ key: 'label', label: 'Study Left Out', fmt: 'text' }, { key: 'est', label: 'Estimate' }, { key: 'lower', label: `Lower ${lv}` }, { key: 'upper', label: `Upper ${lv}` }, { key: 'p', label: r.hksj ? 'Prob>|t|' : 'Prob>|z|', fmt: 'p' }, { key: 'tau2', label: 'τ²' }, { key: 'i2p', label: 'I² (%)' }, { key: 'q', label: 'Q', hidden: true }];
    if (m.log) cols.splice(4, 0, { key: 'ratio', label: m.display }, { key: 'ratio_lower', label: `${SHORT[m.display] || m.display} Lower ${lv}` }, { key: 'ratio_upper', label: `${SHORT[m.display] || m.display} Upper ${lv}` });
    ob.add(ctx.rt({ columns: cols, rows: r.rows.map((x) => ({ ...x, i2p: pct(x.i2) })) }, { onRow: (row) => ctx.table.select([row.row]) }),
      ctx.note(`The random-effects estimate (${METHOD[r.method]}${r.hksj ? ', Hartung–Knapp' : ''}) with each study left out; the dotted line is the estimate from all studies. A study whose omission moves the estimate far is influential. Click a point or a line to select the study left out.`),
      ctx.code(r.code));
  }

  async function cumulativeOutline(ctx, res, parent, cum) {
    const byCol = cum.by ? ctx.col(cum.by) : null;
    const ob = ctx.outline(`Cumulative Meta-Analysis${byCol ? ` by ${byCol.name}` : ''}`, { parent, key: 'cum', info: 'p:meta:cumulative', menu: () => [
      { label: 'Order By…', action: () => cumulativeDialog(ctx) },
      { label: 'Descending', checked: !!cum.desc, action: () => ctx.set('cum', { ...cum, desc: !cum.desc }) },
      ctx.check('Show Plot', 'cumPlot', null, true),
      { label: 'Remove', action: () => ctx.set('cum', null) },
    ] });
    if (cum.by && !byCol) { ob.add(ctx.warn('The ordering column is no longer in the table: choose another (Order By…).')); return; }
    const r = await ctx.call('meta.cumulative', { ...baseArgs(ctx), order_by: byCol ? byCol.name : null, descending: !!cum.desc });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const m = r.measure;
    const lv = lvText(ctx.alpha);
    if (ctx.opt('cumPlot', true)) {
      const info = {};
      const g = miniForest(ctx, res, r.rows, r.rows.map((x) => `+ ${x.label}${byCol ? ` (${x.value ?? '.'})` : ''}`), r.rows[r.rows.length - 1].est, 'Cumulative estimates', info);
      ob.add(withCode(ctx, g, await plotCode(ctx, 'cumulative', info, { order_by: byCol ? byCol.name : null, descending: !!cum.desc })));
    }
    const cols = [{ key: 'label', label: 'Study Added', fmt: 'text' }];
    if (byCol) cols.push({ key: 'value', label: byCol.name, fmt: 'text' });
    cols.push({ key: 'k', label: 'k', fmt: 'int' }, { key: 'est', label: 'Estimate' }, { key: 'lower', label: `Lower ${lv}` }, { key: 'upper', label: `Upper ${lv}` });
    if (m.log) cols.push({ key: 'ratio', label: m.display }, { key: 'ratio_lower', label: `${SHORT[m.display] || m.display} Lower ${lv}` }, { key: 'ratio_upper', label: `${SHORT[m.display] || m.display} Upper ${lv}` });
    cols.push({ key: 'p', label: r.hksj ? 'Prob>|t|' : 'Prob>|z|', fmt: 'p' }, { key: 'tau2', label: 'τ²' }, { key: 'i2p', label: 'I² (%)' });
    ob.add(ctx.rt({ columns: cols, rows: r.rows.map((x) => ({ ...x, i2p: pct(x.i2) })) }, { sortable: false, onRow: (row) => ctx.table.select([row.row]) }),
      ctx.note(`Each line pools the studies up to it, in the order of ${byCol ? byCol.name : 'the rows'}${cum.desc ? ' (descending)' : ''}, ties in row order${r.n_missing_order ? `, the ${r.n_missing_order} with ${byCol.name} missing last` : ''}: random effects, ${METHOD[r.method]}. Click a point or a line to select the study added.`),
      ctx.code(r.code));
  }

  async function regressionOutline(ctx, res, parent, covs) {
    const ob = ctx.outline(`Meta-Regression`, { parent, key: 'mreg', info: 'p:meta:regression', menu: () => [
      { label: 'Covariates…', action: () => regressionDialog(ctx) },
      { label: 'Remove', action: () => ctx.set('mreg', []) },
    ] });
    const r = await ctx.call('meta.regression', { ...baseArgs(ctx), covariates: covs.map((c) => c.name) });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const lv = lvText(ctx.alpha);
    const t = r.hksj;
    ob.add(ctx.kv([
      ['Studies', r.k, 'int'], ['Coefficients', r.p, 'int'], [`Residual τ² (${METHOD[r.method]})`, r.tau2], ['Residual I² (%)', pct(r.i2)],
      ['R² (τ² explained, %)', pct(r.r2)], ['τ² without covariates', r.tau2_0],
    ], { caption: 'Summary of Fit' }));
    ob.add(ctx.rt({ caption: 'Parameter Estimates', columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'est', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'z', label: t ? 't Ratio' : 'z Ratio' }, { key: 'p', label: t ? 'Prob>|t|' : 'Prob>|z|', fmt: 'p' }, { key: 'lower', label: `Lower ${lv}` }, { key: 'upper', label: `Upper ${lv}` }], rows: r.terms }, { sortable: false }));
    const tests = [{ what: 'Residual heterogeneity (Q_E)', stat: r.qe, df: r.qe_df, p: r.qe_p }];
    if (r.qm) tests.unshift({ what: r.qm.test === 'F' ? `Moderators (F, ${r.qm.df} and ${r.qm.df_den} DF)` : 'Moderators (Q_M, Wald χ²)', stat: r.qm.stat, df: r.qm.df, p: r.qm.p });
    ob.add(ctx.rt({ caption: 'Tests', columns: [{ key: 'what', label: 'Test', fmt: 'text' }, { key: 'stat', label: 'Statistic' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'p', label: 'p-Value', fmt: 'p' }], rows: tests }, { sortable: false }));
    const plots = [];
    for (const cv of r.curves) {
      const info = {};
      const g = bubblePlot(ctx, r, cv, res, info);
      plots.push(withCode(ctx, g, await plotCode(ctx, 'bubble', info, { covariates: covs.map((c) => c.name) })));
    }
    if (plots.length) ob.add(ctx.row(...plots));
    ob.add(ctx.note(`Weighted least squares (statsmodels WLS) of ${r.measure.effect.toLowerCase()} on the covariates, weights 1/(v + τ²) with τ² the residual between-study variance (${METHOD[r.method]}), ${t ? 'the scale estimated and t tests on k − p degrees of freedom (Knapp–Hartung)' : 'the scale fixed at 1 and z tests'}: the mixed-effects meta-regression of metafor's rma with mods. Nominal covariates are dummy coded against their first level. R² is the share of τ² the covariates explain.${r.n_dropped ? ` ${r.n_dropped} studies with a missing covariate are left out.` : ''} In the bubble plots each bubble's area is proportional to its weight; the other covariates sit at their means (or first levels).`),
      ctx.code(r.code));
  }

  /* ---- red triangles -------------------------------------------------------------- */
  function methodItems(ctx) {
    return METHODS.map(([k, label]) => ({ label, checked: ctx.opt('method', 'dl') === k, action: () => ctx.set('method', k) }));
  }

  function measureItems(ctx) {
    const o = ctx.spec.options || {};
    const layout = layoutOf(o);
    if (layout === 'es') return [{ label: 'Effects Are Log Ratios', checked: !!o.logRatio, action: () => ctx.set('logRatio', !o.logRatio) }, { label: 'Std Error Column Holds Variances', checked: o.seKind === 'var', action: () => ctx.set('seKind', o.seKind === 'var' ? 'se' : 'var') }];
    const list = layout === 'cont' ? CONT_MEASURES : BIN_MEASURES;
    const cur = measureKey(o);
    return list.map(([k]) => ({ label: MEASURE_ITEMS[k], checked: cur === k, action: () => ctx.set('measure', k) }));
  }

  function zeroItems(ctx) {
    const cur = String(ctx.opt('cc', 0.5));
    const items = { '0.5': 'Add 0.5 to Every Cell', tac: 'Treatment-Arm Correction', none: 'None (Leave Such Studies Out)' };
    return ZERO.map(([k]) => ({ label: items[k], checked: cur === k, action: () => ctx.set('cc', k === '0.5' ? 0.5 : k) }));
  }

  function forestMenu(ctx) {
    const o = ctx.spec.options || {};
    const sortItem = (k, label) => ({ label, checked: ctx.opt('fSort', 'table') === k, action: () => ctx.set('fSort', k) });
    return [
      ctx.check('Fixed Effect', 'fShowFE', null, true), ctx.check('Random Effects', 'fShowRE', null, true), ctx.check('Prediction Interval', 'fShowPI', null, true),
      ctx.check('Weights', 'fWeights', null, true), ctx.check('Statistics', 'fStats', null, true), ctx.check('Pooled Estimate Line', 'fPooledLine', null, true),
      measureIsLog(o) ? ctx.check('Log Scale', 'fLog', null, true) : null,
      measureKey(o) === 'or' ? ctx.check('Mantel–Haenszel Fixed Effect', 'mhDiamond', null, false) : null,
      { label: 'Sort Studies', submenu: () => [sortItem('table', 'Table Order'), sortItem('effect', 'By Effect'), sortItem('weight', 'By Weight'), sortItem('precision', 'By Precision'), sortItem('label', 'By Label')] },
    ].filter(Boolean);
  }

  function topMenu(ctx) {
    const o = ctx.spec.options || {};
    const layout = layoutOf(o);
    const cum = ctx.opt('cum', null);
    const covs = covariatesOf(ctx);
    return [
      { label: 'Random-Effects Method', submenu: () => methodItems(ctx) },
      ctx.check('Hartung–Knapp Intervals', 'hksj', null, false),
      { label: 'Effect Size', submenu: () => measureItems(ctx) },
      layout === 'bin' ? { label: 'Zero Cells', submenu: () => zeroItems(ctx) } : null,
      { separator: true },
      { label: 'Forest Plot Options', submenu: () => forestMenu(ctx) },
      ctx.check('Forest Plot', 'forest', null, true),
      ctx.check('Summary Estimates', 'summary', null, true),
      ctx.check('Heterogeneity', 'het', null, true),
      ctx.role('group') ? ctx.check('Subgroups', 'subgroups', null, true) : null,
      ctx.check('Study Effects', 'studies', null, true),
      ctx.check('Funnel Plot', 'funnel', null, true),
      ctx.check('Leave-One-Out', 'loo', null, true),
      { label: 'Cumulative Meta-Analysis…', checked: !!cum, action: () => cumulativeDialog(ctx) },
      { label: 'Meta-Regression…', checked: covs.length > 0, action: () => regressionDialog(ctx) },
      { separator: true },
      { label: 'Save Columns', submenu: () => saveItems(ctx) },
    ];
  }

  const measureIsLog = (o) => ['es_log', 'or', 'rr'].includes(measureKey(o || {}));

  async function cumulativeDialog(ctx) {
    const t = ctx.table;
    const used = new Set(INPUT_KEYS.flatMap((k) => ctx.spec.roles[k] || []));
    const cands = t.columns.filter((c) => !used.has(c.id));
    const cur = ctx.opt('cum', null);
    const guess = cands.find((c) => /year|date|publ/i.test(c.name));
    const v = await SM.ui.form({
      title: 'Cumulative Meta-Analysis', info: 'p:meta:cumulative',
      lead: 'The studies are added one at a time in the order of a column; each line pools the studies up to it.',
      fields: [
        { key: 'by', label: 'Order by', type: 'select', value: cur ? (cur.by || '') : (guess ? guess.id : ''), choices: [['', '(row order)'], ...cands.map((c) => [c.id, c.name])],
          help: 'The column whose order the studies come in: a year of publication, a sample size, a quality rating. (row order) takes the table\'s order. Ties keep the row order; studies missing the value come last.' },
        { key: 'desc', label: 'Descending', type: 'check', value: cur ? !!cur.desc : false,
          help: 'Adds the studies from the largest value down (the most recent first, for a year).' },
      ],
    });
    if (v) ctx.set('cum', { by: v.by || null, desc: !!v.desc });
  }

  async function regressionDialog(ctx) {
    const t = ctx.table;
    const used = new Set([...INPUT_KEYS, 'label'].flatMap((k) => ctx.spec.roles[k] || []));
    const cands = t.columns.filter((c) => !used.has(c.id) && (c.isNumeric || c.isCategorical)).slice(0, 40);
    if (!cands.length) { SM.ui.toast('The table has no other columns to use as covariates'); return; }
    const cur = new Set(covariatesOf(ctx).map((c) => c.id));
    const v = await SM.ui.form({
      title: 'Meta-Regression', info: 'p:meta:regression',
      lead: 'Choose the study-level covariates (moderators). Continuous columns enter as they are, nominal and ordinal ones as dummies against their first level.',
      fields: cands.map((c) => ({ key: c.id, label: `${c.name} (${SM.util.TYPE_LABEL[c.modelingType].toLowerCase()})`, type: 'check', value: cur.has(c.id), helpLabel: 'Each column',
        help: 'Ticked, the column is a covariate of the meta-regression: a continuous one enters as it is, a nominal or ordinal one as dummies against its first level. The list holds up to 40 columns that are not the layout\'s inputs or the Study Label; none ticked removes the Meta-Regression.' })),
    });
    if (v) ctx.set('mreg', cands.filter((c) => v[c.id]).map((c) => c.id));
  }

  function saveItems(ctx) {
    const o = ctx.spec.options || {};
    const raw = layoutOf(o) !== 'es';
    const save = async (what) => {
      let r;
      try { r = await ctx.call('meta.save', { inputs: inputsOf(ctx), method: ctx.opt('method', 'dl'), alpha: ctx.alpha }); } catch (e) { SM.ui.toast(e.message, { error: true }); return; }
      if (r.error) { SM.ui.toast(r.error, { error: true }); return; }
      const m = r.measure;
      const lv = lvText(ctx.alpha);
      const note = `saved from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`;
      if (what === 'effect') ctx.saveColumn(m.effect, { rows: r.rows, values: r.eff }, { notes: note });
      else if (what === 'se') ctx.saveColumn(`Std Error ${m.effect}`, { rows: r.rows, values: r.se }, { notes: note });
      else if (what === 'var') ctx.saveColumn(`Variance ${m.effect}`, { rows: r.rows, values: r.var }, { notes: note });
      else if (what === 'ci') { ctx.saveColumn(`Lower ${lv} ${m.effect}`, { rows: r.rows, values: r.lower }, { notes: note }); ctx.saveColumn(`Upper ${lv} ${m.effect}`, { rows: r.rows, values: r.upper }, { notes: note }); }
      else if (what === 'wfe') ctx.saveColumn('Weight % Fixed', { rows: r.rows, values: r.w_fe }, { notes: note });
      else if (what === 'wre') ctx.saveColumn(`Weight % Random (${METHOD[ctx.opt('method', 'dl')]})`, { rows: r.rows, values: r.w_re }, { notes: note });
    };
    return [
      raw ? { label: 'Effect Size', action: () => save('effect') } : null,
      raw ? { label: 'Std Error', action: () => save('se') } : null,
      raw ? { label: 'Variance', action: () => save('var') } : null,
      { label: 'Confidence Limits', action: () => save('ci') },
      { label: 'Weights, Fixed Effect', action: () => save('wfe') },
      { label: 'Weights, Random Effects', action: () => save('wre') },
    ].filter(Boolean);
  }

  /* ---- render ----------------------------------------------------------------------- */
  async function render(ctx) {
    const o = (k, d) => ctx.opt(k, d);
    const res = await ctx.call('meta.combine', baseArgs(ctx));
    if (res.error) { ctx.container.append(ctx.warn(`Meta-Analysis: ${res.error}`)); return; }
    const host = ctx.container;
    if (res.dropped.length) {
      const list = res.dropped.slice(0, 8).map((d) => `row ${d.row + 1} (${d.reason})`).join('; ');
      host.append(ctx.warn(`${res.dropped.length} row${res.dropped.length > 1 ? 's' : ''} left out: ${list}${res.dropped.length > 8 ? '; …' : ''}.`));
    }
    if (res.corrected.length) {
      const how = String(ctx.opt('cc', 0.5)) === 'tac' ? 'the treatment-arm continuity correction (statsmodels "tac")' : `${fmt(Number(ctx.opt('cc', 0.5)))} added to every cell`;
      const one = res.corrected.length === 1;
      host.append(ctx.note(`${one ? 'Row' : 'Rows'} ${res.corrected.map((r) => r + 1).join(', ')} ${one ? 'has' : 'have'} a zero cell: ${how}, in ${one ? 'that study' : 'those studies'} only${res.measure.key === 'rd' ? ' (for the risk difference only where the variance would be zero)' : ''}. statsmodels' effectsize_2proportions would add the correction to the counts of every study but to the totals of ${one ? 'this one' : 'these'} alone, so it is called for ${one ? 'that study' : 'these studies'} alone.`));
    }
    const k = res.k;
    host.append(ctx.kv([['Studies', k, 'int'], ['Effect', res.measure.effect, 'text'], ['Random-effects method', `${METHOD[res.method]}${res.hksj ? ', Hartung–Knapp' : ''}`, 'text']]));
    if (o('forest', true)) {
      const fo = ctx.outline('Forest Plot', { key: 'forest', info: 'p:meta:forest', menu: () => forestMenu(ctx) });
      const info = {};
      const box = forestPlot(ctx, res, o, info);
      const code = await plotCode(ctx, 'forest', info);
      if (code) box.append(ctx.code(code));   // right under the plot, inside its sideways scroller
      fo.add(box);
      const wWhat = o('fShowRE', true) ? `the random-effects model (${METHOD[res.method]})` : 'the fixed-effect model';
      fo.add(ctx.note(`Squares: the studies, their area proportional to their weight in ${wWhat}; lines: their ${lvText(res.alpha)} confidence intervals. Diamonds: the pooled estimates and their intervals${res.pi && o('fShowPI', true) && o('fShowRE', true) ? '; the red bar is the prediction interval' : ''}. The grey line is no effect (${fmt(res.measure.null)}). Click a square or drag over squares to select the studies' rows.`));
    }
    if (o('summary', true)) summaryOutline(ctx, res, null);
    if (o('het', true)) heterogeneityOutline(ctx, res, null);
    if (res.subgroups && o('subgroups', true)) subgroupOutline(ctx, res, null);
    if (o('studies', true)) studyTable(ctx, res, null);
    if (o('funnel', true)) await funnelOutline(ctx, res, null);
    if (o('loo', true)) await looOutline(ctx, res, null);
    const cum = o('cum', null);
    if (cum) await cumulativeOutline(ctx, res, null, cum);
    const covs = covariatesOf(ctx);
    if (covs.length) await regressionOutline(ctx, res, null, covs);
  }

  /* ---- the launch dialog's layout part ------------------------------------------------ */
  let launchRoot = null;
  function launchExtra(api, spec) {
    const t = api.table;
    const o0 = (spec && spec.options) || {};
    const st = {
      layout: LAYOUT_ROLES[o0.layout] ? o0.layout : guessLayout(t), seKind: o0.seKind === 'var' ? 'var' : 'se', logRatio: !!o0.logRatio,
      cmeasure: o0.measure === 'md' ? 'md' : 'smd', bmeasure: ['or', 'rr', 'rd'].includes(o0.measure) ? o0.measure : 'or', cc: o0.cc == null ? '0.5' : String(o0.cc),
    };
    const name = SM.util.uid('meta-layout');
    const radios = LAYOUTS.map(([k, label]) => {
      const r = el('input', { type: 'radio', name, value: k });
      r.checked = st.layout === k;
      r.addEventListener('change', () => { if (r.checked) { st.layout = k; apply(); } });
      return el('label', { class: 'sm-meta-radio' }, r, label);
    });
    const sel = (choices, value, label, onChange) => {
      const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: v, text: l })));
      s.value = value;
      s.addEventListener('change', () => onChange(s.value));
      return s;
    };
    const seKind = sel([['se', 'Standard errors'], ['var', 'Variances']], st.seKind, 'The Std Error column holds', (v) => { st.seKind = v; apply(); });
    const logBox = el('input', { type: 'checkbox' });
    logBox.checked = st.logRatio;
    logBox.addEventListener('change', () => { st.logRatio = logBox.checked; });
    const cMeas = sel(CONT_MEASURES, st.cmeasure, 'Effect size', (v) => { st.cmeasure = v; });
    const bMeas = sel(BIN_MEASURES, st.bmeasure, 'Effect size', (v) => { st.bmeasure = v; });
    const cc = sel(ZERO, st.cc, 'Zero cells', (v) => { st.cc = v; });
    const opt = (label, input) => el('label', { class: 'sm-meta-opt' }, el('span', { text: label }), input);
    const parts = {
      es: el('div', { class: 'sm-meta-opts' }, opt('The Std Error column holds', seKind), el('label', { class: 'sm-meta-opt' }, logBox, el('span', { text: 'Effects are log ratios (odds, risk or hazard ratios): show them as ratios' }))),
      cont: el('div', { class: 'sm-meta-opts' }, opt('Effect size', cMeas)),
      bin: el('div', { class: 'sm-meta-opts' }, opt('Effect size', bMeas), opt('Zero cells', cc)),
    };
    const box = el('div', { class: 'sm-meta-launch', role: 'group', 'aria-label': 'Input layout' },
      el('h4', null, 'Input Layout', typeof KvotInfo !== 'undefined' ? KvotInfo.slot('p:meta:layout') : null),
      el('div', { class: 'sm-meta-radios' }, ...radios), parts.es, parts.cont, parts.bin);
    launchRoot = box;
    const visible = () => [...LAYOUT_ROLES[st.layout], 'label', 'group', 'covariates', 'by'];
    const decorate = () => {
      const dlg = box.closest('.sm-dialog');
      if (!dlg) return;
      const rows = [...dlg.querySelectorAll('.sm-roles > .sm-role')];
      rows.forEach((row, i) => {
        const r = ROLES[i];
        if (!r) return;
        const req = LAYOUT_ROLES[st.layout].includes(r.key);
        const b = row.querySelector('.sm-btn');
        if (b) { b.classList.toggle('required', req); if (r.key === 'se') b.textContent = st.seKind === 'var' ? 'Variance' : 'Std Error'; }
        const ul = row.querySelector('.sm-role-list');
        if (ul && req) ul.dataset.hint = r.key === 'se' ? (st.seKind === 'var' ? 'required: its variance' : 'required: its standard error') : r.hint;
      });
    };
    const apply = () => {
      for (const r of ROLES) api.showRole(r.key, visible().includes(r.key));
      for (const [k, p] of Object.entries(parts)) p.hidden = k !== st.layout;
      decorate();
      api.message('');
    };
    // A column cast into a hidden role (a double click finds the first role
    // that takes it) moves to the first visible one with room. The move
    // waits for a microtask: Recall fills the roles before it gives this part
    // its layout back, and a relaunch fills them after this part is made.
    let snap = {};
    let busy = false;
    let pending = false;
    const fixHidden = () => {
      pending = false;
      const state = api.state;
      const vis = visible();
      let moved = false;
      for (const key of INPUT_KEYS) {
        if (vis.includes(key)) continue;
        const added = (state[key] || []).filter((id) => !(snap[key] || []).includes(id));
        if (!added.length) continue;
        state[key] = (state[key] || []).filter((id) => !added.includes(id));
        for (const id of added) {
          const c = t.col(id);
          const target = vis.find((k2) => { const r = ROLE[k2]; return c && !SM.launch.roleAccepts(r, c) && (state[k2] || []).length < (r.max ?? Infinity) && !(state[k2] || []).includes(id); });
          if (target) state[target] = [...(state[target] || []), id];
        }
        moved = true;
      }
      if (moved) { busy = true; try { api.render(); } finally { busy = false; } }
      snap = JSON.parse(JSON.stringify(state));
    };
    api.onRolesChange(() => { if (busy || pending) return; pending = true; Promise.resolve().then(fixHidden); });
    apply();
    // The layout comes first: above the roles, in the dialog's middle column.
    requestAnimationFrame(() => {
      const col = box.parentElement;
      if (col && col.firstChild !== box) { col.insertBefore(box, col.firstChild); box.classList.add('is-top'); }
      decorate();
    });
    // What the part's fields do: the Input Layout and the fields of the layout chosen now.
    const help = () => [
      ['Input Layout', 'How the table holds the studies, one per row: Effect and standard error (as studies publish them), Two groups, continuous outcome (n, mean and standard deviation of each group) or Two groups, binary outcome (events and totals). Only the roles of the chosen layout show: what is cast into another layout\'s roles stays while the dialog is open, and OK takes the chosen layout\'s alone.'],
      ...(st.layout === 'es' ? [
        ['The Std Error column holds', 'Standard errors (a study\'s variance is their square, the default) or variances (used as they are).'],
        ['Effects are log ratios', 'Tick when the effects are logs of odds, risk or hazard ratios: the pooling stays on the log scale, and the plots and tables also show the ratios, exp(effect), on a log axis.'],
      ] : st.layout === 'cont' ? [
        ['Effect size', 'Hedges\' g, the standardized mean difference: the difference of the means over the pooled standard deviation, bias corrected (statsmodels\' effectsize_smd, RevMan\'s formulas; the default), for outcomes measured on different scales. The mean difference, with variance s₁²/n₁ + s₂²/n₂, keeps the outcome\'s own units.'],
      ] : [
        ['Effect size', 'The log odds ratio (the default), the log risk ratio (both shown as ratios) or the risk difference, treatment against control (statsmodels\' effectsize_2proportions).'],
        ['Zero cells', 'A study with no events, or only events, in a group has no finite log ratio: add 0.5 to each of its cells (the default, as RevMan), the treatment-arm correction (amounts that depend on the group sizes, statsmodels\' "tac"), or leave such studies out. Studies with no events (or only events) in both groups are left out of the ratios; the risk difference needs a correction only where both groups are all or nothing.'],
      ]),
    ];
    return {
      el: box,
      help,
      helpHeading: 'Input Layout',
      read() {
        const roles = {};
        for (const k of INPUT_KEYS) if (!LAYOUT_ROLES[st.layout].includes(k)) roles[k] = [];
        const options = { layout: st.layout };
        if (st.layout === 'es') { options.seKind = st.seKind; options.logRatio = st.logRatio; }
        if (st.layout === 'cont') options.measure = st.cmeasure;
        if (st.layout === 'bin') { options.measure = st.bmeasure; options.cc = st.cc === '0.5' ? 0.5 : st.cc; }
        return { roles, options };
      },
      recall(saved) {
        const x = (saved && saved.options) || {};
        if (LAYOUT_ROLES[x.layout]) st.layout = x.layout;
        if (x.seKind) { st.seKind = x.seKind; seKind.value = x.seKind; }
        if ('logRatio' in x) { st.logRatio = !!x.logRatio; logBox.checked = st.logRatio; }
        if (x.layout === 'cont' && x.measure) { st.cmeasure = x.measure; cMeas.value = x.measure; }
        if (x.layout === 'bin' && x.measure) { st.bmeasure = x.measure; bMeas.value = x.measure; }
        if (x.cc != null) { st.cc = String(x.cc); cc.value = st.cc; }
        radios.forEach((l) => { const r = l.querySelector('input'); r.checked = r.value === st.layout; });
        apply();
      },
    };
  }

  function validate(spec) {
    const o = spec.options || {};
    const layout = layoutOf(o);
    const need = LAYOUT_ROLES[layout].filter((k) => !(spec.roles[k] || []).length);
    if (need.length) {
      const dlg = launchRoot && launchRoot.closest('.sm-dialog');
      if (dlg) {
        const rows = [...dlg.querySelectorAll('.sm-roles > .sm-role')];
        for (const k of need) { const row = rows[ROLES.findIndex((r) => r.key === k)]; if (row) row.classList.add('is-missing'); }
      }
      const lab = (k) => (k === 'se' && o.seKind === 'var' ? 'Variance' : ROLE[k].label);
      return `${LAYOUTS.find((l) => l[0] === layout)[1]}: cast a column into ${need.map(lab).join(', ')}`;
    }
    return null;
  }

  /* ---- topics ------------------------------------------------------------------------ */
  const MORE = { label: 'Meta-Analysis', id: 'help-p-meta' };
  const TOPICS = {
    'p:meta': {
      kicker: 'Specialized Modeling', title: 'Meta-Analysis',
      lead: 'Pools the results of several studies, one study per row: a forest plot, fixed-effect and random-effects estimates, heterogeneity, small-study effects, sensitivity, subgroups and meta-regression. JMP has no meta-analysis platform; the numbers are statsmodels\' meta_analysis, and the report follows the published forest plots.',
      sections: [
        { heading: 'Input layouts', choices: [
          ['Effect and standard error', 'One effect per study (a mean difference, a log odds ratio, a log hazard ratio) with its standard error or variance, as studies report them. Tick “log ratios” to see the ratios on a log axis.'],
          ['Two groups, continuous outcome', 'N, mean and standard deviation of each group: Hedges\' g (statsmodels effectsize_smd, RevMan\'s formulas) or the mean difference.'],
          ['Two groups, binary outcome', 'Events and totals of each group: log odds ratio, log risk ratio or risk difference (effectsize_2proportions), with a continuity correction for zero cells.'],
        ] },
        { heading: 'Roles', choices: [['Study Label', 'The names in the plots; without it the table\'s label column, or the row number.'], ['Group', 'Subgroups: pooled separately and compared.'], ['Covariates', 'Study-level variables for the Meta-Regression.'], ['By', 'A separate meta-analysis for each level.']] },
        { heading: 'Estimators', text: 'The fixed effect weights each study by the inverse of its variance (with Mantel–Haenszel for odds ratios). The random effects add the between-study variance τ²: DerSimonian–Laird (statsmodels\' "chi2", the default), Paule–Mandel ("iterated") or REML. Intervals are normal (Wald) unless Hartung–Knapp is on.' },
      ],
      more: MORE,
    },
    'p:meta:layout': {
      kicker: 'Meta-Analysis', title: 'Input Layout',
      lead: 'How the table holds the studies. Only the roles of the chosen layout are shown; Study Label, Group, Covariates and By go with every layout.',
      sections: [
        { heading: 'Zero cells', text: 'A study with no events (or only events) in a group has no finite log odds or risk ratio. By default 0.5 is added to every cell of such a study (RevMan); the treatment-arm correction adds amounts that depend on the group sizes (statsmodels "tac"); None leaves such studies out. Studies without events in either group carry no information on a ratio and are left out of odds and risk ratios.' },
        { heading: 'Hedges\' g', text: 'The difference of the means over the pooled standard deviation, times J = 1 − 3/(4N − 9); its variance N/(n₁n₂) + g²/(2(N − 3.94)), as RevMan computes them.' },
      ],
      more: MORE,
    },
    'p:meta:forest': {
      kicker: 'Meta-Analysis', title: 'Forest Plot',
      lead: 'One line per study: the square at its effect, its area proportional to its weight, and the line its confidence interval, with the effect, the interval and the weight written on the right. The diamonds are the pooled estimates, their width the interval; the red bar is the prediction interval.',
      sections: [
        { heading: 'Linking', text: 'Click a square, or drag over squares, to select the studies\' rows in the table; rows selected elsewhere highlight their squares.' },
        { heading: 'Options', text: 'The outline\'s red triangle shows or hides the fixed effect, the random effects, the prediction interval, the weights and the statistics, sorts the studies and turns the log axis of ratios off. With a Group role the studies are listed by subgroup, each with its subtotal.' },
        { heading: 'Wide plots', text: 'On a narrow screen the plot scrolls sideways inside the report.' },
      ],
      more: MORE,
    },
    'p:meta:summary': {
      kicker: 'Meta-Analysis', title: 'Summary Estimates',
      lead: 'Every pooled estimate: the fixed effect by inverse variance (and Mantel–Haenszel for odds ratios), and the random effects with τ² by DerSimonian–Laird, Paule–Mandel and REML, each with its standard error, interval and test. The prediction interval says where the effect of a new study is expected.',
      sections: [
        { heading: 'Compared with other software', text: 'metafor\'s rma defaults to REML, RevMan 5 to DerSimonian–Laird (Mantel–Haenszel for binary outcomes); both give normal intervals and z tests unless asked for Hartung–Knapp. The prediction interval uses t with k − 2 degrees of freedom (as R\'s meta); metafor\'s predict uses the normal quantile.' },
        { heading: 'Hartung–Knapp', text: 'From the red triangle: the variance of the random-effects estimate scaled by the weighted residual variance, with t on k − 1 degrees of freedom (statsmodels\' "wls" intervals). It keeps closer to the nominal coverage with few studies.' },
      ],
      more: MORE,
    },
    'p:meta:heterogeneity': {
      kicker: 'Meta-Analysis', title: 'Heterogeneity',
      lead: 'Cochran\'s Q tests whether the studies share one effect. I² is the share of the variability that is between studies, H = √(Q/df), and τ² the between-study variance of the random-effects model (τ its standard deviation, on the scale of the effect).',
      sections: [{ heading: 'Intervals', text: 'I² and H by Higgins and Thompson (2002), from the standard error of ln H, as R\'s meta; τ² and τ by Viechtbauer\'s (2007) Q-profile, as metafor\'s confint. When Q is below its degrees of freedom I² is 0 and H is 1.' }],
      more: MORE,
    },
    'p:meta:subgroups': {
      kicker: 'Meta-Analysis', title: 'Subgroups',
      lead: 'The studies of each level of the Group column pooled on their own, and a test of whether the subgroups differ: Q between, the heterogeneity of the subgroup estimates, for the fixed and the random effects.',
      more: MORE,
    },
    'p:meta:funnel': {
      kicker: 'Meta-Analysis', title: 'Funnel Plot',
      lead: 'Each study\'s effect against its standard error, the most precise at the top. Without small-study effects the studies scatter symmetrically inside the pseudo confidence limits around the fixed effect; a gap in one lower corner suggests that small studies with results in one direction are missing (publication bias is one reason of several).',
      sections: [
        { heading: 'The tests', choices: [['Egger\'s regression', 'Least squares of the standardized effect on the precision; the intercept measures the asymmetry.'], ['Begg\'s rank correlation', 'Kendall\'s τ between the standardized effects and their variances.']] },
        { heading: 'Caution', text: 'Both have little power with fewer than about ten studies. Trim and fill is not offered.' },
      ],
      more: MORE,
    },
    'p:meta:loo': {
      kicker: 'Meta-Analysis', title: 'Leave-One-Out',
      lead: 'The random-effects estimate with each study left out in turn. A study whose omission moves the estimate far, or changes the conclusion, is influential.',
      more: MORE,
    },
    'p:meta:cumulative': {
      kicker: 'Meta-Analysis', title: 'Cumulative Meta-Analysis',
      lead: 'The random-effects estimate as the studies come in, in the order of a column (the year of publication, say): each line pools the studies up to it, showing when the evidence settled.',
      more: MORE,
    },
    'p:meta:regression': {
      kicker: 'Meta-Analysis', title: 'Meta-Regression',
      lead: 'Weighted least squares of the effects on study-level covariates (statsmodels WLS), weights 1/(v + τ²) with τ² the residual between-study variance: a mixed-effects meta-regression, as metafor\'s rma with mods.',
      sections: [
        { heading: 'The report', text: 'The coefficients with z tests (t with Hartung–Knapp), Q_M for all covariates together, Q_E for the heterogeneity that is left, and R², the share of τ² the covariates explain.' },
        { heading: 'The bubble plot', text: 'Each study against a continuous covariate, the bubble\'s area proportional to its weight, with the fitted line and its confidence band. Click or drag to select studies.' },
      ],
      more: MORE,
    },
  };

  /* ---- the platform --------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'meta', label: 'Meta-Analysis', menu: 'Analyze/Specialized Modeling', order: 60, info: 'p:meta', topics: TOPICS,
    about: 'Pools studies, one per row, from an effect and its standard error, from the means and standard deviations of two groups (Hedges\' g, mean difference) or from events in two groups (odds ratio, risk ratio, risk difference): forest plot linked to the rows, fixed and random effects (DerSimonian–Laird, Paule–Mandel, REML; Hartung–Knapp; Mantel–Haenszel), prediction interval, heterogeneity (Q, I², H, τ² with intervals), subgroups, funnel plot with Egger\'s and Begg\'s tests, leave-one-out, cumulative meta-analysis and meta-regression with bubble plots.',
    uses: ['statsmodels.stats.meta_analysis (combine_effects, effectsize_smd, effectsize_2proportions)', 'statsmodels.stats.contingency_tables.StratifiedTable (Mantel–Haenszel)', 'statsmodels WLS, OLS (REML pooling, meta-regression, Egger\'s test)', 'scipy.stats (kendalltau, chi2, t), scipy.optimize.brentq (REML, Q-profile)'],
    launch: {
      lead: 'Each row is a study. Choose how the table holds the studies, then cast the columns of that layout.',
      roles: ROLES,
      extra: launchExtra,
      validate,
    },
    title: (spec) => `Meta-Analysis of ${PLURAL[measureKey(spec.options || {})]}`,
    triangle: topMenu,
    render,
  });

  /* ---- the example: simulated trials, never real ones ---------------------------------------- */
  SM.io.addExample('studies', {
    label: 'Trials (14 rows): events in two arms, year, dose, quality',
    about: 'Simulated randomized trials of a treatment against a control with a binary outcome: the events and group sizes of each arm, the year, the dose and a quality rating. The true odds ratio falls with the dose and is lower in low-quality trials, with heterogeneity between trials, and one small trial has no events in the treatment arm. For Meta-Analysis (Analyze > Specialized Modeling).',
    make() {
      const r = SM.util.rng('meta-trials');
      const k = 14;
      const c = { study: [], year: [], dose: [], quality: [], e1: [], n1: [], e2: [], n2: [] };
      const binom = (n, p) => { let x = 0; for (let i = 0; i < n; i++) if (r.u() < p) x++; return x; };
      const years = Array.from({ length: k }, (_, i) => 1989 + 2 * i + r.int(0, 1));
      for (let i = years.length - 1; i > 0; i--) { const j = Math.floor(r.u() * (i + 1)); [years[i], years[j]] = [years[j], years[i]]; }
      for (let i = 0; i < k; i++) {
        let size = Math.round(Math.exp(r.normal(4.7, 0.75)));
        size = Math.max(24, Math.min(620, size));
        let pc = 0.1 + 0.22 * r.u();
        if (i === 5) { size = 24; pc = 0.12; }   // a small trial: few events
        const n1 = size, n2 = Math.max(10, size + r.int(-Math.round(size / 10), Math.round(size / 10)));
        const dose = 10 * r.int(1, 8);
        const q = r.u() < (size < 110 ? 0.55 : 0.2) ? 'low' : (r.u() < 0.5 ? 'moderate' : 'high');
        const theta = -0.1 - 0.009 * (dose - 45) - (q === 'low' ? 0.3 : 0) + r.normal(0, 0.18);
        const lp = Math.log(pc / (1 - pc)) + theta;
        const pt = 1 / (1 + Math.exp(-lp));
        let e1 = binom(n1, pt);
        const e2 = binom(n2, pc);
        if (i === 5) e1 = 0;
        c.study.push(`Trial ${String.fromCharCode(65 + i)}`); c.year.push(years[i]); c.dose.push(dose); c.quality.push(q);
        c.e1.push(e1); c.n1.push(n1); c.e2.push(e2); c.n2.push(n2);
      }
      return new SM.Table({ name: 'Trials', source: 'simulated', columns: [
        { name: 'study', dataType: 'character', values: c.study, role: 'label' },
        { name: 'year', dataType: 'numeric', values: c.year },
        { name: 'events (treatment)', dataType: 'numeric', values: c.e1 },
        { name: 'n (treatment)', dataType: 'numeric', values: c.n1 },
        { name: 'events (control)', dataType: 'numeric', values: c.e2 },
        { name: 'n (control)', dataType: 'numeric', values: c.n2 },
        { name: 'dose (mg)', dataType: 'numeric', values: c.dose },
        { name: 'quality', dataType: 'character', modelingType: 'ordinal', valueOrder: ['low', 'moderate', 'high'], values: c.quality },
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
