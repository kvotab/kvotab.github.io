/* ==========================================================================
   SMUI.HTML: DOE > SAMPLE SIZE EXPLORERS > TEST CALCULATORS

   JMP's hypothesis test calculators (Help > Sample Index > Calculators),
   the A/B test of Shmueli et al. ch. 14: two groups compared from their
   summary statistics alone, with no table.

     Two Means        means, standard deviations and sizes: Welch's or the
                      pooled t test (scipy.stats.ttest_ind_from_stats),
                      one- or two-sided, against a hypothesized difference;
                      the interval of the difference and the effect size
     Two Proportions  counts and sizes: the difference, ratio or odds ratio
                      by statsmodels' test_proportions_2indep and
                      confint_proportions_2indep, any of their methods
     Multiple Tests   with two tests or more, their p-values adjusted
                      together (statsmodels multipletests)

   A report holds several tests (Add Two Means, Add Two Proportions); each
   has its fields, its results, a graph of its statistic under the null
   hypothesis with the p-value shaded, the Python of both, and Sample Size
   and Power… for a study of a difference like the one seen. A field
   changed is worked out at once, in place (the report is not drawn again,
   so the field keeps the focus). The numbers are
   resources/py/smui/calculators.py's.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const MORE = { label: 'Test Calculators', id: 'help-p-calculators' };
  const W = (w) => Math.max(240, Math.min(w, (root.innerWidth || 1200) - 110));

  const KIND = { means: 'Two Means', props: 'Two Proportions' };
  const TITLE = { means: 'Hypothesis Test for Two Means', props: 'Hypothesis Test for Two Proportions' };
  const ALTS = [['two-sided', 'Two-sided (≠)'], ['greater', 'Greater (>)'], ['less', 'Less (<)']];
  const COMPARES = [['diff', 'Difference'], ['ratio', 'Ratio'], ['odds-ratio', 'Odds Ratio']];
  // the methods with a test, as calculators.py's PROP_METHODS names them
  const METHODS = {
    diff: [['score', 'Score (pooled z at a difference of 0)'], ['mn', 'Miettinen-Nurminen (score, n/(n − 1))'], ['agresti-caffo', 'Agresti-Caffo (adjusted Wald)'], ['wald', 'Wald']],
    ratio: [['score', 'Koopman (score)'], ['mn', 'Miettinen-Nurminen (score, n/(n − 1))'], ['log', 'Katz (log)'], ['log-adjusted', 'Adjusted log (0.5 added)']],
    'odds-ratio': [['score', 'Score'], ['mn', 'Miettinen-Nurminen (score, n/(n − 1))'], ['logit', 'Woolf (logit)'], ['logit-adjusted', 'Gart (adjusted logit, 0.5 added)'], ['logit-smoothed', 'Independence-smoothed logit']],
  };
  const FRESH = {
    means: () => ({ g1: { name: 'Group 1', mean: 52.3, sd: 14.1, n: 480 }, g2: { name: 'Group 2', mean: 49.8, sd: 13.6, n: 495 }, null: '', alternative: 'two-sided', variance: 'unequal' }),
    props: () => ({ g1: { name: 'Group 1', count: 58, n: 1204 }, g2: { name: 'Group 2', count: 41, n: 1187 }, compare: 'diff', null: '', alternative: 'two-sided', method: 'score' }),
  };
  const DEFAULT = () => [{ key: 't1', kind: 'means', name: 'Test 1', ...FRESH.means() }, { key: 't2', kind: 'props', name: 'Test 2', ...FRESH.props() }];

  const clone = (x) => JSON.parse(JSON.stringify(x));
  function testsOf(ctx) {
    const v = ctx.opt('tests', null);
    return Array.isArray(v) ? clone(v).filter((t) => t && (t.kind === 'means' || t.kind === 'props')) : DEFAULT();
  }
  function nextKey(tests) {
    let n = 0;
    for (const t of tests) { const m = /^t(\d+)$/.exec(t.key || ''); if (m) n = Math.max(n, +m[1]); }
    return `t${n + 1}`;
  }
  const toNum = (s) => { const t = String(s ?? '').trim().replace(',', '.'); if (t === '') return ''; const v = Number(t); return Number.isFinite(v) ? v : t; };

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx) {
    const S = { tests: testsOf(ctx), views: new Map(), seq: 0, multi: null };
    ctx.calc = S;
    const addBtn = (kind) => {
      const b = el('button', { type: 'button', class: 'sm-btn small', text: `Add ${KIND[kind]}` });
      b.addEventListener('click', () => addTest(ctx, kind));
      return b;
    };
    const alpha = el('input', { type: 'text', inputmode: 'decimal', size: 5, class: 'sm-calc-input', 'aria-label': 'Alpha' });
    alpha.value = String(ctx.alpha);
    const setAlpha = () => {
      const v = toNum(alpha.value);
      if (typeof v === 'number' && v > 0 && v < 1) { if (v !== ctx.alpha) ctx.set('alpha', v); }
      else { SM.ui.toast('α is a probability between 0 and 1', { error: true }); alpha.value = String(ctx.alpha); }
    };
    alpha.addEventListener('change', setAlpha);
    alpha.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); setAlpha(); } });
    ctx.container.append(el('div', { class: 'sm-calc-bar', 'data-noexport': '' }, addBtn('means'), addBtn('props'),
      el('label', { class: 'sm-calc-alpha' }, el('span', { text: 'Alpha' }), alpha)));
    if (!S.tests.length) ctx.container.append(ctx.note('No tests: Add Two Means or Add Two Proportions.'));
    S.tests.forEach((t, i) => testOutline(ctx, S, t, i));
    if (S.tests.length > 1) S.multi = ctx.outline('Multiple Tests', { key: 'multiple', info: 'p:calc:multiple' });
    await update(ctx, S, false);
  }

  /* Work every test out again (after a field changed: in place). */
  async function update(ctx, S, store) {
    if (store) ctx.set('tests', clone(S.tests), null, { rerun: false });
    const my = ++S.seq;
    let r;
    try { r = await ctx.call('calculators.compute', { tests: S.tests, alpha: ctx.alpha }); } catch (e) {
      for (const v of S.views.values()) v.results.replaceChildren(ctx.error(e));
      return;
    }
    if (my !== S.seq) return;
    ctx.report.pyCode = [];
    for (const res of r.tests) {
      const v = S.views.get(res.key);
      if (v) fill(ctx, S, v, res);
    }
    if (S.multi) fillMultiple(ctx, S, r);
  }

  function purge(ctx, host) {
    for (const box of host.querySelectorAll('.sm-plot')) {
      const p = box._plot;
      if (!p) continue;
      p.purge();
      const k = ctx.report.plots.indexOf(p);
      if (k >= 0) ctx.report.plots.splice(k, 1);
    }
  }

  /* ---- a test: its outline, fields and results ----------------------------------------------- */
  function testOutline(ctx, S, t, i) {
    const ob = ctx.outline(`${t.name || `Test ${i + 1}`}: ${TITLE[t.kind]}`, { key: `test:${t.key}`, info: t.kind === 'means' ? 'p:calc:means' : 'p:calc:props', menu: () => testMenu(ctx, S, t) });
    const results = el('div', { class: 'sm-calc-results', 'aria-live': 'polite' });
    const form = t.kind === 'means' ? meansForm(ctx, S, t) : propsForm(ctx, S, t);
    ob.add(el('div', { class: 'sm-calc-top' }, form, results));
    S.views.set(t.key, { ob, results, test: t });
  }

  function testMenu(ctx, S, t) {
    const at = S.tests.findIndex((x) => x.key === t.key);
    const redo = (tests) => ctx.set('tests', tests);
    return [
      { label: 'Rename…', action: async () => { const v = await SM.ui.form({ title: 'Rename the Test', fields: [{ key: 'name', label: 'Name', type: 'text', value: t.name || '', help: 'The name of the test in its title, in Multiple Tests and in the code.' }] }); if (v && String(v.name || '').trim()) redo(S.tests.map((x) => (x.key === t.key ? { ...x, name: String(v.name).trim() } : x))); } },
      { label: 'Duplicate', action: () => { const c = { ...clone(t), key: nextKey(S.tests), name: `${t.name || 'Test'} copy` }; const all = S.tests.slice(); all.splice(at + 1, 0, c); redo(all); } },
      { label: 'Move Up', disabled: at <= 0, action: () => { const all = S.tests.slice(); [all[at - 1], all[at]] = [all[at], all[at - 1]]; redo(all); } },
      { label: 'Move Down', disabled: at < 0 || at >= S.tests.length - 1, action: () => { const all = S.tests.slice(); [all[at + 1], all[at]] = [all[at], all[at + 1]]; redo(all); } },
      { label: 'Reset the Inputs', action: () => redo(S.tests.map((x) => (x.key === t.key ? { key: x.key, kind: x.kind, name: x.name, ...FRESH[x.kind]() } : x))) },
      { label: 'Sample Size and Power…', action: () => toPower(ctx, S, t) },
      { separator: true },
      { label: 'Remove', action: () => redo(S.tests.filter((x) => x.key !== t.key)) },
    ];
  }

  function addTest(ctx, kind) {
    const tests = testsOf(ctx);
    tests.push({ key: nextKey(tests), kind, name: `Test ${tests.length + 1}`, ...FRESH[kind]() });
    ctx.set('tests', tests);
  }

  /* ---- the fields ---------------------------------------------------------------------------- */
  function field(value, aria, { size = 8, text = false, placeholder = '' } = {}) {
    const i = el('input', { type: 'text', inputmode: text ? 'text' : 'decimal', size, class: 'sm-calc-input', 'aria-label': aria, placeholder });
    i.value = value == null ? '' : String(value);
    return i;
  }
  function select(choices, value, aria) {
    const s = el('select', { class: 'sm-calc-select', 'aria-label': aria }, ...choices.map(([v, l]) => el('option', { value: v, text: l })));
    s.value = value;
    return s;
  }

  /* The fields of both groups side by side: a row per quantity, a column per group. */
  function groupsGrid(t, rows) {
    const g = el('div', { class: 'sm-calc-grid', role: 'group', 'aria-label': 'The two groups' },
      el('span'), el('span', { class: 'sm-calc-head', text: 'Group 1' }), el('span', { class: 'sm-calc-head', text: 'Group 2' }));
    const inputs = {};
    for (const [key, label, text] of rows) {
      const a = field(t.g1[key], `${label} 1`, { text, size: text ? 10 : 8 });
      const b = field(t.g2[key], `${label} 2`, { text, size: text ? 10 : 8 });
      inputs[key] = [a, b];
      g.append(el('span', { class: 'sm-calc-label', text: label }), a, b);
    }
    return { el: g, inputs };
  }

  function wire(ctx, S, t, inputs, read) {
    const go = () => { read(); update(ctx, S, true); };
    for (const i of inputs) {
      i.addEventListener('change', go);
      if (i.tagName === 'INPUT') i.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); go(); } });
    }
  }

  function meansForm(ctx, S, t) {
    const G = groupsGrid(t, [['name', 'Name', true], ['mean', 'Mean'], ['sd', 'Std Dev'], ['n', 'N']]);
    const nul = field(t.null, 'Hypothesized Difference', { placeholder: '0' });
    const alt = select(ALTS, t.alternative || 'two-sided', 'Alternative');
    const vr = select([['unequal', 'Unequal (Welch)'], ['equal', 'Equal (pooled)']], t.variance || 'unequal', 'Variances');
    const more = el('div', { class: 'sm-form sm-calc-form' },
      el('label', { text: 'Hypothesized Difference' }), nul, el('label', { text: 'Alternative' }), alt, el('label', { text: 'Variances' }), vr);
    const read = () => {
      for (const k of ['name', 'mean', 'sd', 'n']) {
        const [a, b] = G.inputs[k];
        t.g1[k] = k === 'name' ? a.value.trim() : toNum(a.value);
        t.g2[k] = k === 'name' ? b.value.trim() : toNum(b.value);
      }
      t.null = toNum(nul.value); t.alternative = alt.value; t.variance = vr.value;
    };
    wire(ctx, S, t, [...Object.values(G.inputs).flat(), nul, alt, vr], read);
    return el('div', { class: 'sm-calc-fields' }, G.el, more);
  }

  function propsForm(ctx, S, t) {
    const G = groupsGrid(t, [['name', 'Name', true], ['count', 'Count'], ['n', 'N']]);
    const cmp = select(COMPARES, t.compare || 'diff', 'Compare');
    const nul = field(t.null, 'Hypothesized Value', { placeholder: (t.compare || 'diff') === 'diff' ? '0' : '1' });
    const alt = select(ALTS, t.alternative || 'two-sided', 'Alternative');
    const met = select(METHODS[t.compare || 'diff'], t.method || 'score', 'Test Method');
    const more = el('div', { class: 'sm-form sm-calc-form' },
      el('label', { text: 'Compare' }), cmp, el('label', { text: 'Hypothesized Value' }), nul, el('label', { text: 'Alternative' }), alt, el('label', { text: 'Test Method' }), met);
    cmp.addEventListener('change', () => {   // the methods and the null value of the comparison chosen
      const keep = met.value;
      met.replaceChildren(...METHODS[cmp.value].map(([v, l]) => el('option', { value: v, text: l })));
      met.value = METHODS[cmp.value].some(([v]) => v === keep) ? keep : 'score';
      nul.placeholder = cmp.value === 'diff' ? '0' : '1';
      nul.value = '';
    });
    const read = () => {
      for (const k of ['name', 'count', 'n']) {
        const [a, b] = G.inputs[k];
        t.g1[k] = k === 'name' ? a.value.trim() : toNum(a.value);
        t.g2[k] = k === 'name' ? b.value.trim() : toNum(b.value);
      }
      t.compare = cmp.value; t.null = toNum(nul.value); t.alternative = alt.value; t.method = met.value;
    };
    wire(ctx, S, t, [...Object.values(G.inputs).flat(), cmp, nul, alt, met], read);
    return el('div', { class: 'sm-calc-fields' }, G.el, more);
  }

  /* ---- the results ----------------------------------------------------------------------------- */
  function fill(ctx, S, v, res) {
    purge(ctx, v.results);
    if (res.error) { v.results.replaceChildren(ctx.warn(res.error)); return; }
    const pct = `${fmt(100 * (1 - res.alpha))}%`;
    const [n1, n2] = res.groups;
    const parts = [];
    const alt = { 'two-sided': '≠', greater: '>', less: '<' }[res.alternative];
    if (res.kind === 'means') {
      parts.push(ctx.rt({ columns: [{ key: 'group', label: 'Group', fmt: 'text' }, { key: 'mean', label: 'Mean' }, { key: 'sd', label: 'Std Dev' }, { key: 'n', label: 'N' },
        { key: 'se', label: 'Std Err Mean' }, { key: 'lower', label: `Lower ${pct}` }, { key: 'upper', label: `Upper ${pct}` }], rows: res.summary }, { key: `sum:${res.key}`, sortable: false }));
      const pairs = [];
      if (res.null) pairs.push(['Hypothesized Difference', res.null]);
      pairs.push([`Difference (${n1} − ${n2})`, res.diff], ['Std Err Dif', res.se], ['Upper CL Dif', res.upper], ['Lower CL Dif', res.lower], ['Confidence', 1 - res.alpha],
        ['t Ratio', res.t], ['DF', res.df], ['Prob > |t|', res.p_two, 'p'], ['Prob > t', res.p_greater, 'p'], ['Prob < t', res.p_less, 'p']);
      parts.push(el('div', { class: 'sm-calc-test' }, el('h4', { text: res.equal ? 't Test, pooled (equal variances)' : 'Welch\'s t Test (unequal variances)' }), ctx.kv(pairs)));
      if (res.effect) {
        parts.push(ctx.rt({ columns: [{ key: 'effect', label: 'Effect Size', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'lower', label: `Lower ${pct}` }, { key: 'upper', label: `Upper ${pct}` }, { key: 'method', label: 'Interval', fmt: 'text' }],
          rows: res.effect }, { key: `es:${res.key}`, sortable: false }));
      }
      parts.push(ctx.note(`H₀: mean(${n1}) − mean(${n2}) = ${fmt(res.null)}; the alternative chosen, ${alt}: ${res.alternative === 'two-sided' ? 'Prob > |t|' : res.alternative === 'greater' ? 'Prob > t' : 'Prob < t'} = ${SM.util.fmtP(res.p, res.alpha)}. The interval of the difference is the two-sided ${pct} one; the effect size standardizes the difference seen by ${res.equal ? 'the pooled standard deviation (Cohen\'s d), Hedges\' g corrects its bias' : 'the root mean of the two variances (d*, Bonett\'s interval)'}.`));
    } else {
      parts.push(ctx.rt({ columns: [{ key: 'group', label: 'Group', fmt: 'text' }, { key: 'count', label: 'Count' }, { key: 'n', label: 'N' }, { key: 'prop', label: 'Proportion' },
        { key: 'lower', label: `Lower ${pct}` }, { key: 'upper', label: `Upper ${pct}` }], rows: res.summary }, { key: `sum:${res.key}`, sortable: false }));
      const what = { diff: `Difference (${n1} − ${n2})`, ratio: `Ratio (${n1} / ${n2})`, 'odds-ratio': `Odds Ratio (${n1} / ${n2})` }[res.compare];
      const m = res.methods.find((x) => x.key === res.method);
      const pairs = [[what, res.estimate], [`Lower ${pct}`, res.lower], [`Upper ${pct}`, res.upper], ['Method', m ? m.method : res.method, 'text'],
        ['z', res.z], ['Prob > |z|', res.p_two, 'p'], ['Prob > z', res.p_greater, 'p'], ['Prob < z', res.p_less, 'p']];
      const base = res.compare === 'diff' ? 0 : 1;
      if (res.null !== base) pairs.unshift(['Hypothesized Value', res.null]);
      parts.push(el('div', { class: 'sm-calc-test' }, el('h4', { text: `Test of the ${{ diff: 'difference', ratio: 'ratio', 'odds-ratio': 'odds ratio' }[res.compare]}` }), ctx.kv(pairs)));
      parts.push(ctx.note(`H₀: the ${{ diff: 'difference', ratio: 'ratio', 'odds-ratio': 'odds ratio' }[res.compare]} of the proportions of ${n1} and ${n2} is ${fmt(res.null)}; the alternative chosen, ${alt}: ${res.alternative === 'two-sided' ? 'Prob > |z|' : res.alternative === 'greater' ? 'Prob > z' : 'Prob < z'} = ${SM.util.fmtP(res.p, res.alpha)}. Each group's interval is Wilson's; the other methods are under Other Methods.${(res.notes || []).length ? ` ${res.notes.join(' ')}` : ''}`));
    }
    const plot = curvePlot(ctx, res);
    const powerBtn = el('button', { type: 'button', class: 'sm-btn small', text: 'Sample Size and Power…', 'data-noexport': '', title: 'Open Sample Size and Power with these groups: the sample size a study needs to find a difference like this one' });
    powerBtn.addEventListener('click', () => toPower(ctx, S, v.test));
    v.results.replaceChildren(...parts, ctx.code(res.code), el('div', { class: 'sm-calc-plot' }, plot), el('div', { class: 'sm-calc-links', 'data-noexport': '' }, powerBtn));
    if (res.kind === 'props') {
      const other = ctx.outline('Other Methods', { parent: v.ob, key: `other:${res.key}`, closed: true, info: 'p:calc:props' });
      other.el.dataset.calc = 'other';
      const old = v.ob.body.querySelectorAll(':scope > .sm-ob[data-calc="other"]');
      for (const o of old) if (o !== other.el) o.remove();
      other.add(el('div', { class: 'sm-calc-scroll' }, ctx.rt({ columns: [{ key: 'method', label: 'Method', fmt: 'text' }, { key: 'lower', label: `Lower ${pct}` }, { key: 'upper', label: `Upper ${pct}` }, { key: 'z', label: 'z' },
        { key: 'p_two', label: 'Prob > |z|', fmt: 'p' }, { key: 'p_greater', label: 'Prob > z', fmt: 'p' }, { key: 'p_less', label: 'Prob < z', fmt: 'p' }], rows: res.methods.map((x) => ({ ...x, method: x.note ? `${x.method} (${x.note})` : x.method })) }, { key: `methods:${res.key}`, sortable: false })),
      ctx.note('Every method of statsmodels\' confint_proportions_2indep for the interval and test_proportions_2indep for the test (Newcombe\'s is an interval only). The score methods invert the score test: without the n/(n − 1) factor it is, at a difference of 0, the pooled z test JMP\'s calculator reports; Miettinen and Nurminen add the factor.'));
    }
  }

  /* The statistic's distribution under the null hypothesis, the p-value shaded, the critical values dashed. */
  function curvePlot(ctx, res) {
    const c = res.curve;
    const th = SM.util.themeColors();
    const fill = th.dark ? 'rgba(240, 160, 80, 0.45)' : 'rgba(217, 130, 43, 0.45)';
    const traces = [{ type: 'scatter', mode: 'lines', x: c.x, y: c.y, line: { color: SM.report.BASE, width: 1.6 }, name: 'Density', hoverinfo: 'skip', showlegend: false }];
    for (const tl of c.tails) traces.push({ type: 'scatter', mode: 'lines', x: tl.x, y: tl.y, fill: 'tozeroy', fillcolor: fill, line: { width: 0, color: fill }, hoverinfo: 'skip', showlegend: false, name: 'p-value' });
    const crit = th.dark ? '#e87c73' : '#b0413e';
    const shapes = [...c.crit.map((x) => ({ type: 'line', x0: x, x1: x, yref: 'paper', y0: 0, y1: 1, line: { color: crit, width: 1, dash: 'dash' } })),
      { type: 'line', x0: c.stat, x1: c.stat, yref: 'paper', y0: 0, y1: 1, line: { color: th.muted, width: 1.4 } }];
    const title = `${res.name}: ${c.label}`;
    return SM.predict.withCode(ctx.plot(traces, { margin: { l: 50, r: 10, t: 28, b: 42 }, title: { text: T(title), font: { size: 12 } }, shapes,
      xaxis: { title: { text: c.label }, range: [-c.half, c.half] }, yaxis: { title: { text: 'Density' }, rangemode: 'tozero' } },
    { width: W(420), height: 280, title, select: false }), ctx.code(res.plot_code));
  }

  /* ---- Multiple Tests ------------------------------------------------------------------------- */
  function fillMultiple(ctx, S, r) {
    const ob = S.multi;
    ob.body.replaceChildren();
    const M = r.multiple;
    if (!M) { ob.add(ctx.note('Two tests or more, each with its p-value, are adjusted together here; fix the tests that give an error.')); return; }
    const cols = [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'p', label: 'p-Value', fmt: 'p' }, ...M.methods.map((m) => ({ key: m.key, label: m.label, fmt: 'p', hidden: !m.shown }))];
    ob.add(el('div', { class: 'sm-calc-scroll' }, ctx.rt({ columns: cols, rows: M.rows }, { key: 'multiple', sortable: false })),
      ctx.note(`Each test's p-value (of its chosen alternative) adjusted for the ${M.rows.length} tests: Holm's controls the chance of any false discovery among them (the familywise error rate), Benjamini and Hochberg's the expected share of false ones among the discoveries (the false discovery rate). A star marks a p-value below α = ${fmt(M.alpha)}. Right click the table, Columns, for Bonferroni, Šidák, Holm-Šidák, Hochberg, Hommel and Benjamini-Yekutieli.`),
      ctx.code(M.code));
  }

  /* ---- Sample Size and Power, with these groups ----------------------------------------------- */
  function toPower(ctx, S, t) {
    const P = SM.platforms.get('power');
    if (!P) { SM.ui.toast('Sample Size and Power is not on this page', { error: true }); return; }
    const sides = t.alternative === 'two-sided' ? 2 : 1;
    const num = (v) => (typeof v === 'number' ? v : toNum(v));
    let options;
    if (t.kind === 'means') {
      const [m1, s1, n1, m2, s2, n2] = [t.g1.mean, t.g1.sd, t.g1.n, t.g2.mean, t.g2.sd, t.g2.n].map(num);
      const d0 = typeof num(t.null) === 'number' ? num(t.null) : 0;
      if (![m1, s1, n1, m2, s2, n2].every((x) => typeof x === 'number') || n1 < 2 || n2 < 2) { SM.ui.toast('Fill in both groups first', { error: true }); return; }
      const sp = Math.sqrt(((n1 - 1) * s1 * s1 + (n2 - 1) * s2 * s2) / (n1 + n2 - 2));
      options = { situation: 'two_means', 'in:two_means': { alpha: ctx.alpha, sd: +sp.toPrecision(8), extra: 0, ratio: +(n2 / n1).toPrecision(8), diff: +(m1 - m2 - d0).toPrecision(8), n: null, power: 0.8, sides } };
    } else {
      const [x1, n1, x2, n2] = [t.g1.count, t.g1.n, t.g2.count, t.g2.n].map(num);
      if (![x1, n1, x2, n2].every((x) => typeof x === 'number') || !(n1 > 0 && n2 > 0)) { SM.ui.toast('Fill in both groups first', { error: true }); return; }
      const d0 = t.compare === 'diff' && typeof num(t.null) === 'number' ? num(t.null) : 0;
      options = { situation: 'two_props', 'in:two_props': { alpha: ctx.alpha, p2: +(x2 / n2).toPrecision(8), null_diff: d0, p1: +(x1 / n1).toPrecision(8), n: null, n2: null, power: 0.8, sides } };
    }
    SM.app.openReport(P, { roles: {}, options }, null);
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:calc': {
      kicker: 'DOE > Sample Size Explorers', title: 'Test Calculators',
      lead: 'Tests of two groups from their summary statistics alone, as JMP\'s hypothesis test calculators do (Help > Sample Index > Calculators): two means from their means, standard deviations and sizes, two proportions from their counts. An A/B test\'s results are often all there is: the average and spread of a measure in each version, or how many converted out of how many.',
      sections: [
        { heading: 'In the report', choices: [
          ['Add Two Means, Add Two Proportions', 'A new test at the end of the report, with example values to replace.'],
          ['Alpha', 'The significance level of every test and 1 − the confidence of every interval (0.05). Set α Level in the red triangle does the same.'],
          ['A test\'s red triangle', 'Rename…, Duplicate, Move Up and Down, Reset the Inputs, Sample Size and Power…, Remove.'],
          ['Multiple Tests', 'With two tests or more: their p-values adjusted together, so that testing several metrics does not find differences by chance.']] },
        { heading: 'Differences from JMP', text: 'JMP\'s calculators are separate scripts, one test each; here one report holds several tests and adjusts their p-values together. The proportions offer every method of statsmodels; the default is the score test without the n/(n − 1) factor, which at a difference of 0 is the pooled z test of JMP\'s calculator. The effect sizes are those of Bivariate Analysis\'s t test.' },
      ],
      more: MORE,
    },
    'p:calc:means': {
      kicker: 'Test Calculators', title: 'Hypothesis Test for Two Means',
      lead: 'The t test of the difference of two means from each group\'s mean, standard deviation and size (scipy.stats.ttest_ind_from_stats): t = (mean₁ − mean₂ − d₀) / SE, with the interval of the difference, as Bivariate Analysis\'s t test reports it from the rows.',
      sections: [
        { heading: 'The fields', choices: [
          ['Name', 'Each group\'s name, which the results use (B − A). Group 1 and Group 2 by default.'],
          ['Mean', 'The group\'s sample mean.'], ['Std Dev', 'The group\'s sample standard deviation (with n − 1 in its denominator), 0 or more.'],
          ['N', 'The group\'s number of observations, 2 or more.'],
          ['Hypothesized Difference', 'd₀, the difference mean₁ − mean₂ under the null hypothesis; empty is 0. A margin other than 0 tests superiority or non-inferiority.'],
          ['Alternative', 'Two-sided: the difference is not d₀; Greater: mean₁ − mean₂ > d₀; Less: < d₀. The report gives all three p-values; the chosen one is shaded in the graph and goes to Multiple Tests.'],
          ['Variances', 'Unequal (Welch, the default): each group its own variance, the degrees of freedom by Welch-Satterthwaite. Equal (pooled): one variance, n₁ + n₂ − 2 degrees of freedom; right only when the spreads are alike.']] },
        { heading: 'The results', choices: [
          ['Difference, Std Err Dif, Lower and Upper CL Dif', 'mean₁ − mean₂, its standard error and its two-sided interval at 1 − α.'],
          ['t Ratio, DF, Prob > |t|, Prob > t, Prob < t', 'The test of the difference against d₀: the two-sided and both one-sided p-values.'],
          ['Effect Size', 'Pooled: Cohen\'s d, the difference over the pooled standard deviation, with its exact interval from the noncentral t, and Hedges\' g (d times Hedges\' correction J). Welch: d*, the difference over √((s₁² + s₂²)/2), with Bonett\'s interval, and g*.'],
          ['The graph', 't\'s distribution when the null hypothesis holds: the p-value shaded, the critical values at α dashed, the observed t the solid line.'],
          ['Sample Size and Power…', 'Opens Sample Size and Power with the pooled standard deviation, the difference seen and the groups\' ratio: the total sample size a study needs to find such a difference with power 0.8.']] },
      ],
      more: MORE,
    },
    'p:calc:props': {
      kicker: 'Test Calculators', title: 'Hypothesis Test for Two Proportions',
      lead: 'Two proportions from the number of events (successes, conversions) out of each group\'s size, compared as a difference, a ratio (relative risk) or an odds ratio, with an interval and a test (statsmodels test_proportions_2indep and confint_proportions_2indep).',
      sections: [
        { heading: 'The fields', choices: [
          ['Name', 'Each group\'s name, which the results use. Group 1 and Group 2 by default.'],
          ['Count', 'The number of events in the group: 0 to N.'], ['N', 'The group\'s size, 1 or more.'],
          ['Compare', 'Difference p₁ − p₂ (the default), Ratio p₁/p₂ or Odds Ratio.'],
          ['Hypothesized Value', 'The difference (0 when empty), or the ratio or odds ratio (1 when empty), under the null hypothesis.'],
          ['Alternative', 'Two-sided, Greater (the difference or ratio above the hypothesized value) or Less. The report gives all three p-values; the chosen one is shaded and goes to Multiple Tests.'],
          ['Test Method', 'Score (the default): Farrington-Manning\'s score test, the pooled z test at a difference of 0, as JMP\'s calculator; Miettinen-Nurminen: the score test with the n/(n − 1) factor; Agresti-Caffo: the adjusted Wald test of Bivariate Analysis\'s Two Sample Test for Proportions; Wald; for a ratio Katz\'s log and the adjusted log, for an odds ratio Woolf\'s logit, Gart\'s adjusted logit and the independence-smoothed logit.']] },
        { heading: 'The results', choices: [
          ['Each group', 'Its proportion with Wilson\'s interval.'],
          ['The test', 'The estimate, the chosen method\'s interval and its z test: the two-sided and both one-sided p-values.'],
          ['Other Methods', 'Every method\'s interval and test, to see how much the choice matters (with small counts it can).'],
          ['The graph', 'z\'s distribution when the null hypothesis holds: the p-value shaded, the critical values dashed, the observed z the solid line.'],
          ['Sample Size and Power…', 'Opens Sample Size and Power with the two proportions seen: the sample size of each group a study needs to find such a difference with power 0.8.']] },
      ],
      more: MORE,
    },
    'p:calc:multiple': {
      kicker: 'Test Calculators', title: 'Multiple Tests',
      lead: 'Several tests at once (the metrics of one A/B test) find a difference by chance more often than α: each p-value is adjusted for the number of tests (statsmodels multipletests).',
      sections: [{ choices: [['Holm', 'Controls the familywise error rate, the chance of any false discovery, and is never worse than Bonferroni.'], ['Benjamini-Hochberg (FDR)', 'Controls the false discovery rate, the expected share of false discoveries among the discoveries: more of them than Holm finds.'], ['Right click, Columns', 'Bonferroni, Šidák, Holm-Šidák, Hochberg, Hommel and Benjamini-Yekutieli.']] }],
      more: MORE,
    },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'calculators', label: 'Test Calculators', menu: 'DOE/Sample Size Explorers', order: 20, info: 'p:calc', needsTable: false, topics: TOPICS,
    about: 'Hypothesis tests of two groups from summary statistics, as JMP\'s calculators: two means from their means, standard deviations and sizes (Welch\'s or the pooled t test, one- or two-sided, against a hypothesized difference; the interval of the difference and the effect size) and two proportions from counts (their difference, ratio or odds ratio by any of statsmodels\' methods, with intervals), several tests in one report with their p-values adjusted together, each test\'s graph of its statistic under the null hypothesis, and Sample Size and Power with the groups seen.',
    uses: ['scipy.stats.ttest_ind_from_stats, t, nct', 'statsmodels.stats.proportion: test_proportions_2indep, confint_proportions_2indep, proportion_confint', 'statsmodels.stats.multitest.multipletests'],
    title: () => 'Test Calculators',
    triangle: (ctx) => [
      { label: 'Add Two Means', action: () => addTest(ctx, 'means') },
      { label: 'Add Two Proportions', action: () => addTest(ctx, 'props') },
      { label: 'Reset All Tests', action: () => ctx.set('tests', DEFAULT()) },
    ],
    render,
  });

  SM.calculators = Object.freeze({ DEFAULT, FRESH, METHODS });
}(typeof self !== 'undefined' ? self : this));
