/* ==========================================================================
   SMUI.HTML: DOE

   DOE > Classical        Screening Design, Full Factorial Design, Response
                          Surface Design: a dialog of responses and factors,
                          then a new design table (Pattern, the factors with
                          their modeling types, empty responses); a full
                          factorial also as a split plot (factors that are
                          hard to change set once per whole plot) or with its
                          replicates as blocks, its model kept for Fit Model
                          (the table's Model script and Fit Model's Recall),
                          and Simulate Responses: a formula column of random
                          draws from that model
   DOE > Special Purpose  Space Filling Design (scipy.stats.qmc)
   DOE > Design Diagnostics  Evaluate Design: power, variance, aliases,
                          correlations, efficiencies, prediction variance
   DOE > Sample Size Explorers  Sample Size and Power: a report without a
                          table; give two of the effect, the sample size and
                          the power, and the third is computed

   The designs and the numbers are resources/py/smui/doe.py's and
   power.py's. A continuous factor's coding (the values at −1 and +1) goes
   into its column notes, 'Coding [low, high]: 10, 20', which Evaluate
   Design reads back.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const toNum = (s) => { const t = String(s ?? '').trim().replace(',', '.').replace('−', '-'); if (t === '') return null; const x = Number(t); return Number.isFinite(x) ? x : NaN; };

  const ORDERS = [['randomize', 'Randomize'], ['sort_lr', 'Sort Left to Right'], ['sort_rl', 'Sort Right to Left'], ['keep', 'Keep the Same']];
  const GOALS = ['Maximize', 'Match Target', 'Minimize', 'None'];
  const last = {};   // the last dialog of each command, for this session

  function colors() {
    const t = SM.util.themeColors();
    const d = t.dark;
    return { text: t.text, muted: t.muted, grid: t.grid, point: d ? '#7fb2ff' : SM.report.BASE, curve: d ? '#7fb2ff' : '#2f6690', exact: d ? '#ffb454' : '#b35900', mark: d ? '#ff7a6b' : '#c0392b', level: d ? '#7bd88f' : '#2e7d32' };
  }

  const fitWidth = (ctx, w, min) => (SM.quality ? SM.quality.fitWidth(ctx, w, min) : w);
  // A graph with its matplotlib code under it (the backend's: plot_code), as one item of a row.
  const withCode = (ctx, graph, code) => (code ? el('div', { class: 'sm-doe-plotcode' }, graph, ctx.code(code)) : graph);

  async function engineCall(fn, payload) {
    if (SM.engine.state !== 'ready') SM.ui.toast('Waiting for the Python engine to load…');
    return SM.engine.call(fn, payload);
  }

  /* ---- the dialog's parts ---------------------------------------------------------- */
  function section(title, ...nodes) {
    return el('fieldset', { class: 'sm-doe-sec' }, el('legend', { text: title }), ...nodes);
  }

  function responseEditor(initial) {
    const list = el('div', { class: 'sm-doe-list' });
    const rows = [];
    const add = (r) => {
      const name = el('input', { type: 'text', value: r.name, size: 12, 'aria-label': 'Response name' });
      const goal = el('select', { 'aria-label': 'Goal' }, ...GOALS.map((g) => el('option', { value: g, text: g })));
      goal.value = r.goal || 'Maximize';
      const rm = el('button', { type: 'button', class: 'sm-btn small', text: '×', 'aria-label': 'Remove the response' });
      const row = { el: el('div', { class: 'sm-doe-row' }, name, goal, rm), read: () => ({ name: name.value.trim(), goal: goal.value }) };
      rm.addEventListener('click', () => { if (rows.length <= 1) return; rows.splice(rows.indexOf(row), 1); row.el.remove(); });
      rows.push(row);
      list.append(row.el);
    };
    (initial && initial.length ? initial : [{ name: 'Y', goal: 'Maximize' }]).forEach(add);
    const more = el('button', { type: 'button', class: 'sm-btn small', text: 'Add Response' });
    more.addEventListener('click', () => { const names = new Set(rows.map((r) => r.read().name)); let i = rows.length + 1; while (names.has(`Y${i}`)) i++; add({ name: `Y${i}`, goal: 'Maximize' }); });
    return { el: el('div', null, list, more), read: () => rows.map((r) => r.read()).filter((r) => r.name) };
  }

  function factorEditor({ kinds = ['continuous', 'categorical'], twoLevel = false, initial = null, count = 3, changes = false } = {}) {
    const tbody = el('tbody');
    const rows = [];
    const listeners = [];
    const changed = () => listeners.forEach((f) => f());
    const nextName = () => { const names = new Set(rows.map((r) => r.read().name)); let i = rows.length + 1; while (names.has(`X${i}`)) i++; return `X${i}`; };
    const add = (f) => {
      const name = el('input', { type: 'text', value: f.name, size: 10, 'aria-label': 'Factor name' });
      const role = el('select', { 'aria-label': 'Role' }, ...kinds.map((k) => el('option', { value: k, text: k === 'continuous' ? 'Continuous' : 'Categorical' })));
      role.value = kinds.includes(f.kind) ? f.kind : kinds[0];
      const lo = el('input', { type: 'text', inputmode: 'decimal', size: 6, value: String(f.low ?? -1), 'aria-label': 'Low value' });
      const hi = el('input', { type: 'text', inputmode: 'decimal', size: 6, value: String(f.high ?? 1), 'aria-label': 'High value' });
      const lv = el('input', { type: 'text', size: 18, value: (f.levels || (twoLevel ? ['L1', 'L2'] : ['L1', 'L2', 'L3'])).join(', '), 'aria-label': 'Levels, separated by commas' });
      const vals = el('div', { class: 'sm-doe-values' });
      const renderVals = () => vals.replaceChildren(...(role.value === 'continuous' ? [lo, el('span', { text: 'to' }), hi] : [lv]));
      renderVals();
      const rm = el('button', { type: 'button', class: 'sm-btn small', text: '×', 'aria-label': 'Remove the factor' });
      // Changes (a split plot): Easy, its level may change from run to run; Hard, set once for a whole plot of runs
      const ch = changes ? el('select', { 'aria-label': 'Changes' }, el('option', { value: 'easy', text: 'Easy' }), el('option', { value: 'hard', text: 'Hard' })) : null;
      if (ch) { ch.value = f.changes === 'hard' ? 'hard' : 'easy'; ch.addEventListener('change', changed); }
      const tr = el('tr', null, el('td', null, name), el('td', null, role), ch ? el('td', null, ch) : null, el('td', null, vals), el('td', null, rm));
      const row = { tr, read: () => ({ name: name.value.trim(), kind: role.value, low: toNum(lo.value), high: toNum(hi.value), levels: lv.value.split(',').map((s) => s.trim()).filter(Boolean), ...(ch ? { changes: ch.value } : {}) }) };
      role.addEventListener('change', () => { renderVals(); changed(); });
      for (const i of [name, lo, hi, lv]) i.addEventListener('change', changed);
      rm.addEventListener('click', () => { rows.splice(rows.indexOf(row), 1); tr.remove(); changed(); });
      rows.push(row);
      tbody.append(tr);
    };
    (initial && initial.length ? initial : Array.from({ length: count }, (_, i) => ({ name: `X${i + 1}`, kind: kinds[0], low: -1, high: 1 }))).forEach(add);
    const buttons = el('div', { class: 'sm-doe-row' });
    for (const k of kinds) {
      const b = el('button', { type: 'button', class: 'sm-btn small', text: `Add ${k === 'continuous' ? 'Continuous' : 'Categorical'}` });
      b.addEventListener('click', () => { add({ name: nextName(), kind: k, low: -1, high: 1 }); changed(); });
      buttons.append(b);
    }
    const nIn = el('input', { type: 'text', inputmode: 'numeric', size: 3, value: '1', 'aria-label': 'How many factors to add' });
    const nBtn = el('button', { type: 'button', class: 'sm-btn small', text: 'Add N' });
    nBtn.addEventListener('click', () => { const n = Math.max(1, Math.min(30, Math.round(toNum(nIn.value) || 1))); for (let i = 0; i < n; i++) add({ name: nextName(), kind: kinds[0], low: -1, high: 1 }); changed(); });
    buttons.append(nIn, nBtn);
    const table = el('table', { class: 'sm-doe-factors' }, el('thead', null, el('tr', null, el('th', { text: 'Name' }), el('th', { text: 'Role' }), changes ? el('th', { text: 'Changes' }) : null, el('th', { text: 'Values' }), el('th'))), tbody);
    const validate = () => {
      const fs = rows.map((r) => r.read());
      if (!fs.length) return 'Add at least one factor.';
      const seen = new Set();
      for (const f of fs) {
        if (!f.name) return 'Every factor needs a name.';
        if (seen.has(f.name)) return `Two factors are called ${f.name}.`;
        seen.add(f.name);
        if (f.kind === 'continuous') {
          if (f.low == null || f.high == null || Number.isNaN(f.low) || Number.isNaN(f.high)) return `${f.name}: give numbers for the low and high values.`;
          if (!(f.low < f.high)) return `${f.name}: the low value must be below the high.`;
        } else {
          if (f.levels.length < 2) return `${f.name}: give two or more levels, separated by commas.`;
          if (twoLevel && f.levels.length !== 2) return `${f.name}: a screening factor has two levels.`;
          if (new Set(f.levels).size !== f.levels.length) return `${f.name}: the levels must differ.`;
        }
      }
      return null;
    };
    return { el: el('div', { class: 'sm-doe-factorbox' }, el('div', { class: 'sm-doe-scroll' }, table), buttons), read: () => rows.map((r) => r.read()), count: () => rows.length, onChange: (f) => listeners.push(f), validate };
  }

  function outputOptions({ centers = true, replicates = true, defaults = {} } = {}) {
    const order = el('select', { 'aria-label': 'Run order' }, ...ORDERS.map(([v, l]) => el('option', { value: v, text: l })));
    order.value = defaults.order || 'randomize';
    const seed = el('input', { type: 'text', inputmode: 'numeric', size: 10, value: defaults.seed ?? '', placeholder: 'random', 'aria-label': 'Random seed' });
    const cp = el('input', { type: 'text', inputmode: 'numeric', size: 4, value: String(defaults.center_points ?? 0), 'aria-label': 'Number of center points' });
    const rep = el('input', { type: 'text', inputmode: 'numeric', size: 4, value: String(defaults.replicates ?? 0), 'aria-label': 'Number of replicates' });
    const grid = el('div', { class: 'sm-form' },
      el('label', { text: 'Run Order' }), order,
      centers ? el('label', { text: 'Number of Center Points' }) : null, centers ? cp : null,
      replicates ? el('label', { text: 'Number of Replicates' }) : null, replicates ? rep : null,
      el('label', { text: 'Random Seed' }), seed);
    const inputs = [order, seed, cp, rep];
    return {
      el: grid, inputs,
      read: () => ({ order: order.value, seed: seed.value.trim() === '' ? null : Math.round(toNum(seed.value)), center_points: centers ? Math.max(0, Math.round(toNum(cp.value) || 0)) : 0, replicates: replicates ? Math.max(0, Math.round(toNum(rep.value) || 0)) : 0 }),
      setCenters: (n) => { cp.value = String(n); },
    };
  }

  /* scripts: the table's scripts, as JMP's design tables have them ({ name, platform, kind, spec },
     smui-scripts.js: the Table panel runs them) */
  function makeTable(res, source, scripts = null) {
    const t = new SM.Table({
      name: SM.app.uniqueTableName(res.name), source, notes: res.notes, scripts: scripts || [],
      columns: res.columns.map((c) => ({ name: c.name, dataType: c.dataType, modelingType: c.modelingType, notes: c.notes || '', valueOrder: c.valueOrder || null,
        values: c.values.map((v) => (v == null ? (c.dataType === 'numeric' ? NaN : null) : v)) })),
    });
    SM.app.addTable(t);
    SM.ui.toast(`Made the design table ${t.name}: ${res.n_runs} runs`);
    return t;
  }

  function designDialog({ title, info, body, onMake, extraButtons = [] }) {
    const msg = el('div', { class: 'sm-launch-msg', role: 'status' });
    const dlg = SM.ui.dialog({
      title, info, className: 'sm-doe-dialog', body: el('div', null, body, msg),
      buttons: [...extraButtons.map((b) => ({ label: b.label, action: async () => { msg.textContent = ''; try { await b.action(msg); } catch (e) { msg.textContent = e.message || String(e); } return false; } })),
        { label: 'Cancel' },
        { label: 'Make Table', primary: true, action: async () => {
          msg.textContent = '';
          try { return await onMake(msg); } catch (e) { msg.textContent = (e && e.message) || String(e); return false; }
        } }],
    });
    return { dlg, msg };
  }

  /* ---- Full Factorial ------------------------------------------------------------------ */
  /* The design's model, { roles: { y: [names] }, options, effects } by column names, as Fit Model's
     Recall: Fit Model > Recall then opens with it (the table's Model script does the same from the
     Table panel). */
  function recallModel(spec) {
    if (spec && SM.launch && SM.launch.last) SM.launch.last.set('fitmodel', { roles: spec.roles, options: spec.options, extra: { effects: spec.effects } });
  }

  const levelCount = (f) => (f.kind === 'continuous' ? 2 : Math.max(1, (f.levels || []).length));
  const wholePlotsDefault = (H, reps) => H * Math.max(2, reps + 1);   // doe.py's whole_plots_default

  /* Simulate Responses: the coefficients of the design's model, the random columns' and the
     error's standard deviations, then a formula column of random draws from it. */
  async function simulateResponses(t, res, factors) {
    const sim = res.simulate;
    if (!sim) return null;
    const y = ((res.model && res.model.roles.y) || [])[0] || 'Y';
    const fields = [{ key: 'b0', label: 'Intercept', type: 'number', value: 0, help: 'The response where every continuous factor is at the middle of its range, averaged over the levels of the categorical ones.' }];
    sim.terms.forEach((term, i) => term.labels.forEach((lab, j) => fields.push({ key: `c${i}_${j}`, label: lab, type: 'number', value: term.defaults[j], helpLabel: 'A term (X1, X1*X2, X3[L1])',
      help: 'Its coefficient: a continuous factor coded −1 at its low value and +1 at its high, a categorical one effect coded (the level in brackets +1, the last level −1, the others 0), an interaction the product. 1 for a main effect and 0 for an interaction to begin with.' })));
    for (const r of sim.random) fields.push({ key: `s:${r}`, label: `${r} σ`, type: 'number', value: sim.sigmas[r], helpLabel: 'Whole Plots σ, Block σ', help: 'The standard deviation of the random effect of each whole plot or block: one normal draw shared by its runs.' });
    fields.push({ key: 's:Error', label: 'Error σ', type: 'number', value: sim.sigmas.Error, help: 'The standard deviation of the error: a normal draw of its own for each run.' });
    const v = await SM.ui.form({
      title: 'Simulate Responses', info: 'cmd:simulateresponses', okLabel: 'Make Column',
      lead: `A column ${y} Simulated: a formula of the design's model with these coefficients and random draws for the ${sim.random.length ? `${sim.random.join(' and ')} and the ` : ''}error. Fit Model's Recall has the model with it as Y.`,
      fields,
      validate: (x) => {
        for (const k of ['s:Error', ...sim.random.map((r) => `s:${r}`)]) if (x[k] != null && x[k] < 0) return 'A standard deviation is 0 or more.';
        return null;
      },
    });
    if (!v) return null;
    const payload = {
      factors, terms: sim.terms.map((term) => term.names), intercept: v.b0 ?? 0,
      coefficients: sim.terms.map((term, i) => term.labels.map((_, j) => v[`c${i}_${j}`] ?? 0)),
      sigmas: Object.fromEntries([...sim.random, 'Error'].map((r) => [r, v[`s:${r}`] ?? 0])),
    };
    const { expr } = await engineCall('doe.simulate_formula', payload);
    const c = t.addColumn({ name: t.uniqueName(`${y} Simulated`), dataType: 'numeric', values: [],
      notes: `Simulate Responses: the design's model with random draws (the formula). Cols > Formula edits the coefficients; the formula's seed keeps the draws.` });
    try { SM.formula.apply(t, c, expr); } catch (e) { t.removeColumn(c.id); throw e; }
    const spec = { ...res.model, roles: { ...res.model.roles, y: [c.name] } };
    t.setScripts([...(t.scripts || []).filter((x) => x.name !== 'Model (Simulated)'), { name: 'Model (Simulated)', platform: 'fitmodel', kind: 'launch', spec }]);
    recallModel(spec);
    SM.ui.toast(`Added ${c.name}: the design's model with random draws`);
    return c;
  }

  function fullFactorial() {
    const L = last.full || {};
    const S = L.split || {};
    const resp = responseEditor(L.responses);
    const fac = factorEditor({ initial: L.factors, count: 3, changes: true });
    const out = outputOptions({ defaults: L.output });
    const uid = (p) => SM.util.uid(p);
    const wp = el('input', { type: 'text', inputmode: 'numeric', size: 4, value: S.whole_plots ?? '', id: uid('wp'), 'aria-label': 'Number of whole plots' });
    const blocks = el('input', { type: 'checkbox', id: uid('bl') });
    blocks.checked = !!S.blocks;
    const simulate = el('input', { type: 'checkbox', id: uid('si') });
    simulate.checked = !!S.simulate;
    // in the Output Options' own grid, after its fields
    out.el.append(
      el('label', { for: wp.id, text: 'Number of Whole Plots' }), wp,
      el('label', { for: blocks.id, text: 'Replicates as Blocks' }), el('div', null, blocks),
      el('label', { for: simulate.id, text: 'Simulate Responses' }), el('div', null, simulate));
    const runs = el('p', { class: 'sm-ob-note' });
    const count = () => {
      const fs = fac.read();
      const o = out.read();
      const hard = fs.filter((f) => f.changes === 'hard'), easy = fs.filter((f) => f.changes !== 'hard');
      const split = hard.length > 0;
      const cont = fs.some((f) => f.kind === 'continuous');
      const combos = fs.reduce((p, f) => p * levelCount(f), fs.length ? 1 : 0);
      wp.disabled = !split;
      blocks.disabled = split || o.replicates < 1;
      if (split) {
        const H = hard.reduce((p, f) => p * levelCount(f), 1), E = easy.reduce((p, f) => p * levelCount(f), 1);
        const w = toNum(wp.value);
        const W = w == null || Number.isNaN(w) ? wholePlotsDefault(H, o.replicates) : Math.round(w);
        wp.placeholder = String(wholePlotsDefault(H, o.replicates));
        if (!easy.length) runs.textContent = 'Every factor is hard to change: make at least one easy to change.';
        else if (W < H || W % H) runs.textContent = `The number of whole plots must be a multiple of ${H}, the settings of the hard-to-change factors.`;
        else runs.textContent = `Number of runs: ${W * E} (a split plot: ${W} whole plots of ${E} runs, each of the ${H} settings of the hard-to-change factors in ${W / H}).`;
        return;
      }
      wp.placeholder = '';
      const cp = cont ? o.center_points : 0;
      if (blocks.checked && o.replicates >= 1) {
        const B = o.replicates + 1;
        runs.textContent = `Number of runs: ${B * (combos + cp)} (${B} blocks of the ${combos} combinations${cp ? ` and ${cp} center point${cp > 1 ? 's' : ''}` : ''}).`;
        return;
      }
      runs.textContent = `Number of runs: ${combos * (o.replicates + 1) + cp} (${combos} combinations${o.replicates ? ` × ${o.replicates + 1}` : ''}${cp ? ` + ${cp} center points` : ''}).`;
    };
    fac.onChange(count);
    out.inputs.forEach((i) => i.addEventListener('change', count));
    for (const i of [wp, blocks]) i.addEventListener('change', count);
    count();
    designDialog({
      title: 'Full Factorial Design', info: 'cmd:fullfactorial',
      body: el('div', null,
        el('p', { class: 'sm-dialog-lead', text: 'Every combination of the factors\' levels: continuous factors at their low and high values, categorical ones at each of their levels. A factor that is hard to change makes it a split plot.' }),
        section('Responses', resp.el), section('Factors', fac.el), section('Output Options', out.el, runs)),
      onMake: async (msg) => {
        const err = fac.validate();
        if (err) { msg.textContent = err; return false; }
        const fs = fac.read();
        const o = out.read();
        const split = fs.some((f) => f.changes === 'hard');
        const w = toNum(wp.value);
        if (split && w != null && (Number.isNaN(w) || w < 1 || w !== Math.round(w))) { msg.textContent = 'Number of Whole Plots: a whole number, or empty for the default.'; return false; }
        const payload = { factors: fs, responses: resp.read(), ...o, whole_plots: split && w != null ? w : null, blocks: !split && blocks.checked };
        last.full = { factors: fs, responses: payload.responses, output: o, split: { whole_plots: wp.value.trim(), blocks: blocks.checked, simulate: simulate.checked } };
        const res = await engineCall('doe.full_factorial', payload);
        const t = makeTable(res, 'DOE > Full Factorial Design', res.model ? [{ name: 'Model', platform: 'fitmodel', kind: 'launch', spec: res.model }] : null);
        recallModel(res.model);
        // after this dialog has closed
        if (simulate.checked) setTimeout(() => simulateResponses(t, res, fs).catch((e) => SM.ui.toast((e && e.message) || String(e))), 0);
        return true;
      },
    });
  }

  /* ---- Screening --------------------------------------------------------------------------- */
  function designList(kind) {
    const box = el('div', { class: 'sm-doe-designs', role: 'radiogroup', 'aria-label': 'Designs' });
    let chosen = null, designs = [];
    const set = (list, preferred) => {
      designs = list;
      box.replaceChildren();
      if (!list.length) { box.append(el('p', { class: 'sm-ob-note', text: 'No design for this number of factors.' })); chosen = null; return; }
      const keep = list.find((d) => d.key === chosen) || list.find((d) => d.key === preferred) || list[0];
      chosen = keep.key;
      const head = kind === 'screening' ? el('div', { class: 'sm-doe-dhead' }, el('span', { text: 'Runs' }), el('span', { text: 'Design' }), el('span', { text: 'Resolution' }))
        : el('div', { class: 'sm-doe-dhead' }, el('span', { text: 'Runs' }), el('span', { text: 'Design' }), el('span', { text: 'Axial α' }));
      box.append(head);
      const name = `d${SM.util.uid('')}`;
      for (const d of list) {
        const r = el('input', { type: 'radio', name, value: d.key });
        r.checked = d.key === chosen;
        r.addEventListener('change', () => { chosen = d.key; if (box.onpick) box.onpick(d); });
        const label = kind === 'screening' ? [String(d.runs), d.type, d.resolution] : [String(d.runs), d.label, d.alpha != null ? fmt(d.alpha, { sig: 5 }) : '—'];
        box.append(el('label', { class: 'sm-doe-design' }, r, ...label.map((t) => el('span', { text: t }))));
      }
      if (box.onpick) box.onpick(keep);
    };
    return { el: box, set, value: () => chosen, designs: () => designs, onpick: (f) => { box.onpick = f; } };
  }

  function screening() {
    const L = last.screening || {};
    const resp = responseEditor(L.responses);
    const fac = factorEditor({ twoLevel: true, initial: L.factors, count: 5 });
    const out = outputOptions({ defaults: L.output });
    const list = designList('screening');
    const detail = el('p', { class: 'sm-ob-note' });
    list.onpick((d) => { detail.textContent = d.type === 'Fractional Factorial' ? `Resolution ${d.resolution}${d.wlp ? `; words of length 3, 4, 5: ${d.wlp.slice(0, 3).join(', ')}` : ''}.` : d.type === 'Plackett-Burman' ? 'Plackett-Burman: main effects are partially aliased with two-factor interactions.' : 'Every effect can be estimated.'; });
    let pending = 0;
    const refresh = SM.util.debounce(async () => {
      const k = fac.count();
      const seq = ++pending;
      list.el.replaceChildren(el('p', { class: 'sm-ob-note', text: SM.engine.state === 'ready' ? 'Listing the designs…' : 'Waiting for the Python engine…' }));
      try {
        const r = await SM.engine.call('doe.screening_designs', { n_factors: k });
        if (seq !== pending) return;
        const good = r.designs.filter((d) => d.res >= 4);
        list.set(r.designs, (good[0] || r.designs[0] || {}).key);
      } catch (e) { list.el.replaceChildren(el('p', { class: 'sm-ob-warn', text: e.message })); }
    }, 120);
    fac.onChange(refresh);
    refresh();
    const payload = () => ({ factors: fac.read(), responses: resp.read(), design: list.value() || 'auto', ...out.read() });
    designDialog({
      title: 'Screening Design', info: 'cmd:screening',
      body: el('div', null,
        el('p', { class: 'sm-dialog-lead', text: 'Two-level designs that estimate the main effects in few runs: fractional factorials of resolution III and up, and Plackett-Burman designs. Choose a design from the list.' }),
        section('Responses', resp.el), section('Factors', fac.el), section('Choose a Design', list.el, detail), section('Output Options', out.el)),
      extraButtons: [{ label: 'Show Aliases', action: async () => {
        const err = fac.validate();
        if (err) throw new Error(err);
        const r = await engineCall('doe.screening', { ...payload(), order: 'keep' });
        const body = el('div', null,
          el('p', { class: 'sm-dialog-lead', text: `${r.design.type}, ${r.n_runs} runs, resolution ${r.design.resolution}.` }),
          r.generators.length ? el('p', { text: `Generators: ${r.generators.join('; ')}` }) : null,
          r.defining_relation.length ? el('p', { text: `Defining relation: ${r.defining_relation.map((w) => w.replace(/^I = /, '')).join(' = ').replace(/^/, 'I = ')}` }) : null,
          r.aliases.length ? SM.report.rt({ columns: [{ key: 'effect', label: 'Effect', fmt: 'text' }, { key: 'aliases', label: 'Aliases (up to three factors)', fmt: 'text' }], rows: r.aliases }, { sortable: false }) : el('p', { class: 'sm-ob-note', text: r.design.type === 'Plackett-Burman' ? 'Partial aliasing: see Evaluate Design\'s alias matrix.' : 'No aliases among the main effects and two-factor interactions.' }));
        SM.ui.dialog({ title: 'Aliasing of Effects', body, narrow: true, buttons: [{ label: 'Close', primary: true }] });
      } }],
      onMake: async (msg) => {
        const err = fac.validate();
        if (err) { msg.textContent = err; return false; }
        if (fac.count() < 2) { msg.textContent = 'A screening design needs two or more factors.'; return false; }
        const p = payload();
        last.screening = { factors: p.factors, responses: p.responses, output: out.read() };
        const res = await engineCall('doe.screening', p);
        makeTable(res, `DOE > Screening Design (${res.design.type}, resolution ${res.design.resolution})`);
        return true;
      },
    });
  }

  /* ---- Response surface ----------------------------------------------------------------------- */
  function responseSurface() {
    const L = last.rsm || {};
    const resp = responseEditor(L.responses);
    const fac = factorEditor({ kinds: ['continuous'], initial: L.factors, count: 3 });
    const out = outputOptions({ defaults: { center_points: 6, ...(L.output || {}) } });
    const list = designList('rsm');
    const alpha = el('input', { type: 'text', inputmode: 'decimal', size: 6, placeholder: 'from the design', 'aria-label': 'Axial value alpha' });
    const inscribe = el('input', { type: 'checkbox', 'aria-label': 'Inscribe the design in the factor limits' });
    const detail = el('p', { class: 'sm-ob-note' });
    list.onpick((d) => { out.setCenters(d.center); detail.textContent = d.key === 'bbd' ? `Box-Behnken: ${d.runs - d.center} runs on the edges of the cube and ${d.center} center points; no run has every factor at an extreme.` : `Central composite: the ${d.cube} cube, 2k axial points at α = ${fmt(d.alpha, { sig: 5 })} and center points.`; });
    let pending = 0;
    const refresh = SM.util.debounce(async () => {
      const seq = ++pending;
      list.el.replaceChildren(el('p', { class: 'sm-ob-note', text: SM.engine.state === 'ready' ? 'Listing the designs…' : 'Waiting for the Python engine…' }));
      try {
        const r = await SM.engine.call('doe.rsm_designs', { n_factors: fac.count() });
        if (seq !== pending) return;
        list.set(r.designs, 'ccd:rotatable');
      } catch (e) { list.el.replaceChildren(el('p', { class: 'sm-ob-warn', text: e.message })); }
    }, 120);
    fac.onChange(refresh);
    refresh();
    designDialog({
      title: 'Response Surface Design', info: 'cmd:rsm',
      body: el('div', null,
        el('p', { class: 'sm-dialog-lead', text: 'Designs for a quadratic model of continuous factors: central composite designs (a two-level cube, axial points and center points) and Box-Behnken designs.' }),
        section('Responses', resp.el), section('Factors', fac.el), section('Choose a Design', list.el, detail,
          el('div', { class: 'sm-form' }, el('label', { text: 'Axial value α (CCD; empty: the design\'s)' }), alpha, el('label', { text: 'Inscribe (axial points at the factor limits)' }), inscribe)),
        section('Output Options', out.el)),
      onMake: async (msg) => {
        const err = fac.validate();
        if (err) { msg.textContent = err; return false; }
        let design = list.value();
        if (!design) { msg.textContent = 'No response surface design for this number of factors (2 to 8; Box-Behnken 3 to 7).'; return false; }
        const a = toNum(alpha.value);
        if (a != null && design.startsWith('ccd')) { if (!(a > 0)) { msg.textContent = 'α must be a positive number.'; return false; } design = 'ccd:custom'; }
        const o = out.read();
        const p = { factors: fac.read(), responses: resp.read(), design, alpha: a, inscribe: inscribe.checked, ...o };
        last.rsm = { factors: p.factors, responses: p.responses, output: o };
        const res = await engineCall('doe.rsm', p);
        makeTable(res, 'DOE > Response Surface Design');
        return true;
      },
    });
  }

  /* ---- Space filling -------------------------------------------------------------------------- */
  function spaceFilling() {
    const L = last.space || {};
    const resp = responseEditor(L.responses);
    const fac = factorEditor({ kinds: ['continuous'], initial: L.factors, count: 3 });
    const method = el('select', { 'aria-label': 'Method' }, ...[['lhs', 'Latin Hypercube'], ['maximin', 'Sphere Packing (maximin)'], ['uniform', 'Uniform'], ['sobol', 'Sobol'], ['halton', 'Halton']].map(([v, l]) => el('option', { value: v, text: l })));
    method.value = L.method || 'lhs';
    const n = el('input', { type: 'text', inputmode: 'numeric', size: 5, value: String(L.n ?? 20), 'aria-label': 'Number of runs' });
    const seed = el('input', { type: 'text', inputmode: 'numeric', size: 10, value: L.seed ?? '', placeholder: 'random', 'aria-label': 'Random seed' });
    designDialog({
      title: 'Space Filling Design', info: 'cmd:spacefilling',
      body: el('div', null,
        el('p', { class: 'sm-dialog-lead', text: 'Points spread evenly over the ranges of continuous factors, for computer experiments and for exploring a response without a model in mind.' }),
        section('Responses', resp.el), section('Factors', fac.el),
        section('Space Filling Design Methods', el('div', { class: 'sm-form' }, el('label', { text: 'Method' }), method, el('label', { text: 'Number of Runs' }), n, el('label', { text: 'Random Seed' }), seed))),
      onMake: async (msg) => {
        const err = fac.validate();
        if (err) { msg.textContent = err; return false; }
        const runs = Math.round(toNum(n.value));
        if (!(runs >= 2 && runs <= 10000)) { msg.textContent = 'Ask for 2 to 10000 runs.'; return false; }
        const sd = seed.value.trim() === '' ? null : Math.round(toNum(seed.value));
        const p = { factors: fac.read(), responses: resp.read(), n_runs: runs, method: method.value, seed: sd };
        last.space = { factors: p.factors, responses: p.responses, method: p.method, n: runs, seed: seed.value };
        const res = await engineCall('doe.space_filling', p);
        makeTable(res, `DOE > Space Filling Design (${method.options[method.selectedIndex].text})`);
        return true;
      },
    });
  }

  const CMD_TOPIC = (title, lead, sections) => ({ kicker: 'DOE', title, lead, sections });
  /* The fields of the design dialogs, as their (i) explains them. */
  const RESPONSE_CHOICES = [
    ['Response name', 'The name of an empty response column of the design table, for the results of the runs.'],
    ['Goal', 'Maximize, Match Target, Minimize or None: written into the response column\'s notes; the design does not depend on it.'],
    ['×', 'Remove the response (one always stays).'],
    ['Add Response', 'Another response column, Y2, Y3, …'],
  ];
  const factorChoices = ({ categorical = true, twoLevel = false } = {}) => [
    ['Name', 'The factor\'s column name in the design table; the names must differ.'],
    ['Role', categorical ? `Continuous: set at a low and a high value (and the middle for center points). Categorical: ${twoLevel ? 'two named levels' : 'a list of named levels, each a setting of its own'}.` : 'Continuous only, in this design.'],
    ['Values', categorical ? `A continuous factor's low and high values in its own units, low below high: they are −1 and +1 of the coding the column's notes keep. A categorical factor's levels, separated by commas${twoLevel ? ': exactly two' : ''}.` : 'The low and high values in the factor\'s own units, low below high: they are −1 and +1 of the coding the column\'s notes keep.'],
    ['×', 'Remove the factor.'],
    [categorical ? 'Add Continuous, Add Categorical' : 'Add Continuous', 'Another factor, named X4, X5, … in turn.'],
    ['Add N', `Add as many ${categorical ? 'continuous ' : ''}factors as the box before it says (1 to 30).`],
  ];
  const outputChoices = ({ centers = null, replicates = null } = {}) => [
    ['Run Order', 'Randomize, the default (the Random Seed repeats an order); Sort Left to Right, the first factor changing slowest; Sort Right to Left, the last changing slowest; Keep the Same, the standard order.'],
    ...(centers ? [['Number of Center Points', centers]] : []),
    ...(replicates ? [['Number of Replicates', replicates]] : []),
    ['Random Seed', 'The seed of the random run order: the same seed gives the same order. Empty draws one, and the table\'s notes say which.'],
  ];
  const MAKE_TABLE = ['Make Table', 'Make the design table and add it to the open tables; the dialog keeps its settings for the next time in this session.'];
  SM.commands.register({
    menu: 'DOE/Classical', label: 'Screening Design…', order: 10, action: screening, uses: ['numpy (generators, defining relation)'],
    about: 'Two-level fractional factorial (by generators, with resolution and aliases) and Plackett-Burman designs for screening many factors.',
    topics: { 'cmd:screening': CMD_TOPIC('Screening Design', 'Two-level designs that estimate every main effect in few runs. Fractional factorials 2^(k−p) are built from generators; their resolution (III: main effects aliased with two-factor interactions, IV: main effects clear, V: two-factor interactions clear) comes from the defining relation. Plackett-Burman designs of 12, 20 and 24 runs alias every main effect partially with many interactions.', [
      { heading: 'Steps', list: ['Name the responses and the factors (continuous with a low and high value, or categorical with two levels).', 'Choose a design from the list: runs, type and resolution.', 'Show Aliases lists the defining relation and which effects are confounded.', 'Make Table makes the design table; its notes keep the generators and aliases.'] },
      { heading: 'Responses', choices: RESPONSE_CHOICES },
      { heading: 'Factors', choices: factorChoices({ twoLevel: true }) },
      { heading: 'Choose a Design', choices: [
        ['The list', 'The designs for this many factors, by their runs, type and resolution: the full factorial (up to 128 runs), the regular fractions, and Plackett-Burman designs of 12, 20 and 24 runs. It starts at the smallest of resolution IV or better, and follows the number of factors.'],
        ['Show Aliases', 'The generators, the defining relation and which main effects and two-factor interactions are confounded, for the design chosen.']] },
      { heading: 'Output Options', choices: outputChoices({
        centers: 'Runs with every continuous factor at the middle of its range (the categorical factors alternate their two levels): a check of curvature and an estimate of pure error. They need a continuous factor; 0 by default.',
        replicates: 'Copies of the whole design beyond the first (the center points are not copied); 0 by default.' }) },
      { heading: 'Buttons', choices: [MAKE_TABLE] },
    ]) },
  });
  SM.commands.register({
    menu: 'DOE/Classical', label: 'Full Factorial Design…', order: 20, action: fullFactorial, uses: ['itertools.product', 'numpy.random.default_rng (run order, the restricted randomization of a split plot)'],
    about: 'Every combination of the levels of continuous (two-level) and categorical factors, with replicates, center points and a randomized or sorted run order; a split plot when factors are hard to change, or the replicates as blocks; the design\'s model (with its random whole plots or blocks) kept for Fit Model, and simulated responses.',
    topics: {
      'cmd:fullfactorial': CMD_TOPIC('Full Factorial Design', 'Every combination of the factors\' levels: 2 for each continuous factor (low and high), and each level of a categorical factor. All main effects and interactions can be estimated.', [
        { heading: 'Responses', choices: RESPONSE_CHOICES },
        { heading: 'Factors', choices: [...factorChoices().slice(0, 2),
          ['Changes', 'Easy, the default: the factor\'s setting may change from one run to the next. Hard: it is set once for a group of runs, a whole plot, as an oven\'s temperature is for the batches baked in it; the design is then a split plot.'],
          ...factorChoices().slice(2)] },
        { heading: 'Output Options', choices: [...outputChoices({
          centers: 'Runs with every continuous factor at the middle of its range (the categorical factors cycle through their levels): a check of curvature and an estimate of pure error. They need a continuous factor; 0 by default. With blocks, each block has them; a split plot has none.',
          replicates: 'Copies of the whole design beyond the first (the center points are not copied): 1 doubles the runs. 0 by default. In a split plot, the default number of whole plots follows it.' }),
          ['Number of Whole Plots', 'A split plot\'s whole plots: a multiple of the number of settings of the hard-to-change factors, each setting then in as many whole plots. Empty: each setting twice (or once for each copy of the design, with more replicates), so that the whole plots\' variation can be told from the hard-to-change factors\' effects. Each whole plot holds every combination of the easy-to-change factors once.'],
          ['Replicates as Blocks', 'With one or more replicates and no hard-to-change factor: each copy of the design is a block (a day, a batch of material), randomized within itself; a Block column says which, and the model has Block as a random effect.'],
          ['Simulate Responses', 'After Make Table: the coefficients of the design\'s model and the standard deviations of its random effects and error, then a formula column of simulated responses (Y Simulated), to try the analysis before the runs are made.']] },
        { heading: 'Buttons', choices: [MAKE_TABLE] },
        { heading: 'Split plots', text: 'The whole plots are in a random order, and the runs in a random order within each: the randomization is restricted, and the runs of a whole plot share its random effect. The hard-to-change factors are then tested against the variation between whole plots (with few degrees of freedom: the number of whole plots less the settings), the others against the variation within them. Fit Model does this with Whole Plots as a random effect (REML), as the design\'s model has it.' },
        { heading: 'The table', text: 'A Pattern column (− low, + high, 0 center, a number the level of a categorical factor), the factors with their modeling types, a Whole Plots or Block column when there are any, and an empty column for each response. A continuous factor\'s notes give its coding, which Evaluate Design uses. The table\'s Model script is the design\'s model: the full factorial, or its main effects and two-factor interactions when the full factorial would leave the error no degree of freedom, with Whole Plots or Block as a random effect; Fit Model\'s Recall opens with it too.' },
        { heading: 'Differences from JMP', list: [
          'JMP makes split plots in Custom Design, where a factor\'s Changes may also be Very Hard (a split-split plot) and the design is chosen for its efficiency; here a split plot is the full factorial, with every combination of the easy-to-change factors in each whole plot.',
          'Replicates as Blocks is this page\'s; JMP blocks a design with a blocking factor of Custom Design, or in the screening designs.',
          'JMP\'s full factorial Model script is the full factorial even when it leaves no error degrees of freedom; here the highest interactions are left out then.',
          'JMP\'s Simulate Responses window stays open, with Apply for new coefficients; here the column\'s formula keeps them, and Cols > Formula changes them.'] },
      ]),
      'cmd:simulateresponses': CMD_TOPIC('Simulate Responses', 'A response column of random draws from the design\'s model, to try the analysis (and see what the design can find) before the runs are made.', [
        { heading: 'The formula', text: 'The intercept, plus each coefficient times its coded columns (a continuous factor (x − middle)/(half its range), −1 to +1; a categorical factor effect coded: its level in brackets 1, its last level −1, the others 0), plus for each whole plot or block one normal draw with its σ, shared by its runs (Col Mean(Random Normal(), :"Whole Plots") times the square root of the whole plot\'s number of runs is a standard normal draw of the whole plot), plus a normal error with the Error σ for each run.' },
        { heading: 'Afterwards', text: 'The column is a formula column: its seed keeps the same draws when the table is computed again, and Cols > Formula shows and changes the coefficients. The table gets a Model (Simulated) script, and Fit Model\'s Recall has the design\'s model with the simulated column as Y.' },
      ]),
    },
  });
  SM.commands.register({
    menu: 'DOE/Classical', label: 'Response Surface Design…', order: 30, action: responseSurface, uses: ['numpy (central composite, Box-Behnken)'],
    about: 'Central composite designs (rotatable, orthogonal, face-centred, spherical, or a given α) and Box-Behnken designs for 3 to 7 factors, for fitting a quadratic model.',
    topics: { 'cmd:rsm': CMD_TOPIC('Response Surface Design', 'Designs for a second-order (quadratic) model of continuous factors.', [
      { heading: 'Designs', choices: [['CCD, rotatable', 'α = F^¼ (F the cube runs): the prediction variance depends only on the distance from the center.'], ['CCD, orthogonal', 'α chosen so the squared terms are uncorrelated.'], ['CCD, face centred', 'α = 1: three levels per factor, inside the cube.'], ['CCD, spherical', 'α = √k: every non-center point on one sphere.'], ['Box-Behnken', 'Three levels, runs on the edges of the cube and none at its corners.']] },
      { heading: 'Axial values', text: 'With α > 1 the axial points lie beyond the low and high values; Inscribe shrinks the design so they fall on the limits.' },
      { heading: 'Responses', choices: RESPONSE_CHOICES },
      { heading: 'Factors', choices: factorChoices({ categorical: false }) },
      { heading: 'Choose a Design', choices: [
        ['The list', 'The designs for this many factors (central composite for 2 to 8, Box-Behnken for 3 to 7), by their runs and axial value α; choosing one puts its usual number of center points into Output Options. The orthogonal α depends on the number of center points, and the list shows it for the usual number.'],
        ['Axial value α (CCD; empty: the design\'s)', 'A distance of the axial points of your own, in coded units (1 is the low or high value), for a central composite design; empty keeps the chosen design\'s α. Box-Behnken designs have no axial points.'],
        ['Inscribe (axial points at the factor limits)', 'Shrink the whole design by 1/α, so that the axial points lie at the low and high values and the cube inside them: for factors that cannot go beyond their limits.']] },
      { heading: 'Output Options', choices: outputChoices({
        centers: 'Runs at the center of the design: they estimate pure error and steady the prediction variance near the center. Choosing a design puts its usual number here.',
        replicates: 'Copies of the design\'s runs beyond the first (the center points are not copied); 0 by default.' }) },
      { heading: 'Buttons', choices: [MAKE_TABLE] },
    ]) },
  });
  SM.commands.register({
    menu: 'DOE/Special Purpose', label: 'Space Filling Design…', order: 10, action: spaceFilling, uses: ['scipy.stats.qmc: LatinHypercube, Sobol, Halton, discrepancy, scale'],
    about: 'Latin hypercube, sphere packing, uniform, Sobol and Halton designs over the ranges of continuous factors (scipy.stats.qmc), seeded.',
    topics: { 'cmd:spacefilling': CMD_TOPIC('Space Filling Design', 'Points that fill the factor space evenly, for computer experiments and nonparametric models.', [
      { heading: 'Methods', choices: [['Latin Hypercube', 'Every factor\'s range cut into n equal strata with one point in each; optimised for the centred discrepancy (scipy random-cd).'], ['Sphere Packing', 'A Latin hypercube with the smallest distance between points made large (maximin).'], ['Uniform', 'Minimum centred discrepancy: close to a uniform distribution.'], ['Sobol, Halton', 'Scrambled low-discrepancy sequences; Sobol is balanced for a power of two runs.']] },
      { heading: 'Responses', choices: RESPONSE_CHOICES },
      { heading: 'Factors', choices: factorChoices({ categorical: false }) },
      { heading: 'Space Filling Design Methods', choices: [
        ['Method', 'How the points are placed: one of the methods above; Latin Hypercube by default.'],
        ['Number of Runs', 'How many points, 2 to 10000; 20 by default.'],
        ['Random Seed', 'The seed of the random placement: the same seed gives the same design; empty draws a new one each time, and the table\'s notes say which.']] },
      { heading: 'Buttons', choices: [MAKE_TABLE] },
    ]) },
  });

  /* ==================================================================================
     Evaluate Design
     ================================================================================== */
  const MODELS = [['main', 'Main Effects'], ['2fi', 'Main Effects and Two-Factor Interactions'], ['rsm', 'Response Surface (with squares)'], ['full', 'Full Factorial']];

  function codingOf(col) {
    const m = /Coding \[low, high\]:\s*([^,]+),\s*([^\s.][^\n]*)/.exec(col.notes || '');
    if (!m) return null;
    const lo = SM.table.toNumber(m[1]), hi = SM.table.toNumber(m[2].replace(/\.$/, ''));
    return Number.isFinite(lo) && Number.isFinite(hi) && lo < hi ? [lo, hi] : null;
  }

  /* A split plot's whole plots: the Whole Plots role, or (as JMP takes its Whole Plots factor) a column
     called Whole Plots cast among the factors. */
  const isWholePlots = (c) => /^whole\s*plots?$/i.test(String(c.name).trim());
  function wholePlotsOf(ctx) {
    const role = ctx.roles('wp')[0] || null;
    const xs = ctx.roles('x');
    const inX = role ? null : xs.find(isWholePlots) || null;
    return { col: role || inX, fromX: !!inX, factors: xs.filter((c) => c !== inX && c !== role) };
  }

  async function wpRatioSettings(ctx) {
    const v = await SM.ui.form({ title: 'Split Plot Variance Ratio', info: 'p:evaldesign', fields: [
      { key: 'ratio', label: 'Split Plot Variance Ratio', type: 'number', value: ctx.opt('wpRatio', 1),
        help: 'The whole plots\' variance over the error variance (the runs within a whole plot), 1 by default as JMP\'s: 0 or more. A larger ratio gives the whole-plot effects larger variances and less power; the effects within the whole plots do not change.' },
    ], validate: (x) => (!(x.ratio >= 0) ? 'the ratio is a number of 0 or more' : null) });
    if (v) ctx.set('wpRatio', v.ratio);
  }

  async function evalRender(ctx) {
    const WP = wholePlotsOf(ctx);
    const factors = WP.factors;
    const model = ctx.opt('model', 'main');
    const coding = {};
    for (const c of factors) if (!c.isCategorical) { const cd = codingOf(c); if (cd) coding[c.name] = cd; }
    const pw = ctx.opt('powerSettings', { alpha: 0.05, rmse: 1, coefficient: 1 }) || {};
    const ratio = Number(ctx.opt('wpRatio', 1));
    const res = await ctx.call('doe.evaluate', { factors: factors.map((c) => c.name), model, alpha: pw.alpha ?? 0.05, rmse: pw.rmse ?? 1, coefficient: pw.coefficient ?? 1, coding, where: ctx.where || [],
      ...(WP.col ? { whole_plots: WP.col.name, wp_ratio: Number.isFinite(ratio) && ratio >= 0 ? ratio : 1 } : {}) });
    const pc = res.plot_code || {};
    const c = colors();
    const fo = ctx.outline('Factors', { key: 'factors' });
    fo.add(ctx.rt({ columns: [{ key: 'name', label: 'Factor', fmt: 'text' }, { key: 'role', label: 'Role', fmt: 'text' }, { key: 'values', label: 'Values', fmt: 'text' }],
      rows: (res.factors || []).map((f) => ({ name: f.name, role: f.kind === 'continuous' ? 'Continuous' : 'Categorical', values: f.kind === 'continuous' ? `${fmt(f.low)} to ${fmt(f.high)}${coding[f.name] ? '' : ' (the data\'s range)'}` : f.levels.join(', ') })) }, { sortable: false, key: 'factors' }));
    const mo = ctx.outline('Model', { key: 'model', menu: () => MODELS.map(([k, l]) => ({ label: l, checked: model === k, action: () => ctx.set('model', k) })) });
    mo.add(el('p', { class: 'sm-doe-terms', text: (res.terms || []).join(', ') }));
    if (res.error) { ctx.container.append(ctx.warn(res.error)); return; }
    if (res.alias) { const ao = ctx.outline('Alias Terms', { key: 'aliasterms', closed: res.alias.cols.length > 12 }); ao.add(el('p', { class: 'sm-doe-terms', text: res.alias.cols.join(', ') })); }
    const de = ctx.outline('Design Evaluation', { key: 'evaluation' });
    // power
    const sp = res.split;
    const po = ctx.outline('Power Analysis', { parent: de, key: 'power', menu: () => [{ label: 'Power Settings…', action: () => powerSettings(ctx) }, ...(sp ? [{ label: 'Split Plot Variance Ratio…', action: () => wpRatioSettings(ctx) }] : [])] });
    po.add(ctx.kv([['Significance Level', pw.alpha ?? 0.05], ['Anticipated RMSE', pw.rmse ?? 1], ['Anticipated Coefficient', pw.coefficient ?? 1],
      ...(sp ? [['Whole Plots', sp.whole_plots, 'int'], ['Split Plot Variance Ratio', sp.ratio]] : [['Error Degrees of Freedom', res.df_error, 'int']])]));
    po.add(ctx.rt(res.power, { sortable: false, key: 'power' }));
    if (res.effect_power) po.add(ctx.rt(res.effect_power, { caption: 'Effect power (categorical factors)', sortable: false, key: 'effectpower' }));
    if (sp) {
      po.add(ctx.note(`A split plot: the whole plots (${sp.column}${WP.fromX ? ', cast among the factors' : ''}, ${sp.whole_plots} of them, ${sp.sizes.length === 1 ? `${sp.sizes[0]} runs each` : `${sp.sizes[0]} to ${sp.sizes[sp.sizes.length - 1]} runs`}) are a random effect whose variance is ${fmt(sp.ratio)} times the error's (the Split Plot Variance Ratio): V = σ²(I + η ZZ′). The variances, the power, the prediction variance and the efficiencies use the GLS information X′V⁻¹X, and each test the denominator degrees of freedom of Satterthwaite's approximation at that ratio: a term that is constant within the whole plots is tested on the variation between them, the others within them (a balanced split plot's two error degrees of freedom, exactly). Fit Model with ${sp.column} as a random effect is the analysis.`));
      if (!sp.estimable) po.add(ctx.warn('The whole plots\' variance cannot be estimated: there are no more whole plots than the model has terms constant within them (no whole-plot error), so those terms cannot be tested. Add whole plots, or take terms out of the model.'));
    } else {
      // a table with a Whole Plots column not used: the evaluation takes the runs as completely randomized
      const wpCol = ctx.table && ctx.table.columns.find(isWholePlots);
      if (wpCol) po.add(ctx.note(`The table has a ${wpCol.name} column, a split plot: cast it in the Whole Plots role (or among the factors, as JMP takes its Whole Plots factor) for an evaluation that allows for the whole plots. Without it the runs are taken as completely randomized, and the hard-to-change factors show more power than they have.`));
    }
    if (!sp) po.add(ctx.note(res.df_error > 0 ? `The power of a t test (an F test with one degree of freedom) that the coefficient is zero when it is the anticipated coefficient, in coded units (continuous factors from −1 to +1): noncentrality (coefficient/RMSE)² / [(XᵀX)⁻¹]ⱼⱼ, ${res.df_error} error degrees of freedom. Categorical effects: coefficients alternating ±the anticipated one.` : 'No error degrees of freedom: the design has as many runs as the model has parameters, so nothing can be tested.'));
    // prediction variance profile
    const pv = ctx.outline('Prediction Variance Profile', { parent: de, key: 'profile' });
    const ymax = Math.max(...res.profile.flatMap((p) => p.variance)) * 1.08;
    pv.add(ctx.row(...res.profile.map((p, i) => withCode(ctx, ctx.plot([
      p.kind === 'continuous'
        ? { type: 'scatter', mode: 'lines', x: p.x, y: p.variance, line: { color: c.curve, width: 2 }, hovertemplate: `${esc(p.factor)} %{x}: %{y:.4f}<extra></extra>` }
        : { type: 'scatter', mode: 'markers+lines', x: p.x.map(esc), y: p.variance, line: { color: c.curve, width: 1 }, marker: { size: 7, color: c.curve }, hovertemplate: `${esc(p.factor)} %{x}: %{y:.4f}<extra></extra>` },
    ], { xaxis: { title: { text: esc(p.factor) }, type: p.kind === 'continuous' ? 'linear' : 'category' }, yaxis: { title: { text: 'Variance' }, range: [0, ymax] }, margin: { l: 50, r: 8, t: 8, b: 40 } }, { width: 200, height: 200, title: `Prediction variance ${p.factor}`, select: false }), (pc.profile || [])[i]))),
    ctx.note(`The relative prediction variance x′(${sp ? 'X′V⁻¹X' : 'XᵀX'})⁻¹x (the variance of the predicted mean over σ²${sp ? ', the error variance: the whole plots\' variance is in V' : ''}) along each factor, the others at their center (categorical: the first level).`));
    // fraction of design space
    const fd = ctx.outline('Fraction of Design Space Plot', { parent: de, key: 'fds' });
    fd.add(withCode(ctx, ctx.plot([{ type: 'scatter', mode: 'lines', x: res.fds.fraction, y: res.fds.variance, line: { color: c.curve, width: 2 }, hovertemplate: 'fraction %{x:.2f}: %{y:.4f}<extra></extra>' }],
      { xaxis: { title: { text: 'Fraction of Space' }, range: [0, 1] }, yaxis: { title: { text: 'Prediction Variance' }, rangemode: 'tozero' }, margin: { l: 54, r: 10, t: 8, b: 42 } }, { width: fitWidth(ctx, 380, 240), height: 260, title: 'Fraction of design space', select: false }), pc.fds),
    ctx.note('The share of the design space (4096 Sobol points of the coded cube; categorical levels equally likely) where the relative prediction variance is at most the value on the curve.'));
    // estimation efficiency
    const ee = ctx.outline('Estimation Efficiency', { parent: de, key: 'efficiency' });
    const vif = new Map((res.vif.rows || []).map((r) => [r.term, r.vif]));
    ee.add(ctx.rt({ columns: [...res.variance.columns, { key: 'vif', label: 'VIF' }], rows: res.variance.rows.map((r) => ({ ...r, vif: vif.get(r.term) ?? null })) }, { sortable: false, key: 'efficiency' }),
      ctx.note(`Variance: [(${sp ? 'X′V⁻¹X' : 'XᵀX'})⁻¹]ⱼⱼ in units of σ²${sp ? ', the error variance' : ''}. Fractional increase in CI length: √(N·variance) − 1, against an orthogonal design of the same size${sp ? ' with the error variance alone (completely randomized)' : ''}. VIF from statsmodels variance_inflation_factor on the coded model matrix.`));
    // alias matrix
    if (res.alias) {
      const am = ctx.outline('Alias Matrix', { parent: de, key: 'aliasmatrix', closed: res.alias.cols.length > 15 });
      const cols = [{ key: 'term', label: 'Effect', fmt: 'text' }, ...res.alias.cols.map((n, j) => ({ key: `a${j}`, label: n, digits: 3 }))];
      am.add(ctx.rt({ columns: cols, rows: res.alias.rows.map((n, i) => ({ term: n, ...Object.fromEntries(res.alias.matrix[i].map((v, j) => [`a${j}`, v])) })) }, { sortable: false, key: 'aliasmatrix' }),
        ctx.note(sp ? 'How the alias terms (left out of the model) bias the GLS estimates: E[b] = β + A·β₂ with A = (X₁′V⁻¹X₁)⁻¹X₁′V⁻¹X₂.' : 'How the alias terms (left out of the model) bias the estimates: E[b] = β + A·β₂ with A = (X₁ᵀX₁)⁻¹X₁ᵀX₂.'));
    }
    // color map on correlations
    const cm = ctx.outline('Color Map On Correlations', { parent: de, key: 'colormap' });
    const names = res.correlation.names.map(esc);
    const Z = res.correlation.matrix.map((row) => row.map((v) => Math.abs(v)));
    const dark = SM.util.themeColors().dark;
    cm.add(withCode(ctx, ctx.plot([{ type: 'heatmap', x: names, y: names, z: Z, zmin: 0, zmax: 1, colorscale: dark ? [[0, '#1f2a36'], [0.5, '#6f86a3'], [1, '#ff6b5c']] : [[0, '#f4f7fb'], [0.5, '#8fa9c2'], [1, '#c0392b']], colorbar: { thickness: 10, title: { text: '|r|' } }, hovertemplate: '%{y} × %{x}: |r| = %{z:.3f}<extra></extra>' }],
      { xaxis: { type: 'category', tickangle: -45, showgrid: false }, yaxis: { type: 'category', autorange: 'reversed', showgrid: false }, margin: { l: 90, r: 10, t: 8, b: 90 }, shapes: res.correlation.n_model < names.length ? [{ type: 'line', xref: 'x', yref: 'paper', x0: res.correlation.n_model - 0.5, x1: res.correlation.n_model - 0.5, y0: 0, y1: 1, line: { color: c.text, width: 1, dash: 'dot' } }] : [] },
      { width: fitWidth(ctx, Math.max(320, Math.min(720, 140 + 26 * names.length))), height: Math.max(300, Math.min(720, 120 + 26 * names.length)), title: 'Color map on correlations', select: false }), pc.colormap),
    ctx.note('The absolute correlations of the model terms and, right of the dotted line, the alias terms, in coded units.'));
    // diagnostics
    const dd = ctx.outline('Design Diagnostics', { parent: de, key: 'diagnostics' });
    dd.add(ctx.kv(res.diagnostics), ctx.note((sp ? 'A split plot: the efficiencies use the GLS information X′V⁻¹X in place of XᵀX, so they are against an orthogonal design with the error variance alone; the whole plots\' variance lowers them. ' : '') + 'D efficiency = 100·|XᵀX/N|^(1/p); A efficiency = 100·p/trace(N(XᵀX)⁻¹); G efficiency = 100·√(p/N)/σ_max, the largest prediction standard deviation searched over the runs, the vertices of the design space and 4096 Sobol points (JMP searches its own candidate set, so G can differ a little). All in coded units: 100 for an orthogonal two-level design; a categorical factor with three or more levels is effect coded, its columns correlated, so even a full factorial with one is below 100.'), ctx.code(res.code));
  }

  async function powerSettings(ctx) {
    const cur = ctx.opt('powerSettings', { alpha: 0.05, rmse: 1, coefficient: 1 }) || {};
    const v = await SM.ui.form({ title: 'Power Analysis', fields: [
      { key: 'alpha', label: 'Significance level', type: 'number', value: cur.alpha ?? 0.05, help: 'The α of the test of each coefficient; 0.05 by default. Between 0 and 1.' },
      { key: 'rmse', label: 'Anticipated RMSE', type: 'number', value: cur.rmse ?? 1, help: 'The error standard deviation you expect in the response; the power rises as it falls. 1 by default; positive.' },
      { key: 'coefficient', label: 'Anticipated coefficient (for every term)', type: 'number', value: cur.coefficient ?? 1,
        help: 'The size of the coefficient to detect, the same for every term, in coded units: a continuous factor\'s coefficient is half the change in the response from its low to its high value. 1 by default.' },
    ], validate: (x) => (!(x.alpha > 0 && x.alpha < 1) ? 'α must lie between 0 and 1' : !(x.rmse > 0) ? 'the RMSE must be positive' : null) });
    if (v) ctx.set('powerSettings', v);
  }

  SM.platforms.register({
    id: 'evaldesign', label: 'Evaluate Design', menu: 'DOE/Design Diagnostics', order: 10, info: 'p:evaldesign',
    about: 'Diagnostics of a design table for a model (main effects, interactions, a response surface): the power of each term, the variance of the coefficients and VIF, the alias matrix and a colour map of correlations, D, G and A efficiencies, the prediction variance profile and the fraction of design space; a split plot\'s whole plots as a random effect (GLS information, Satterthwaite\'s degrees of freedom for each test).',
    uses: ['numpy.linalg', 'scipy.stats.ncf (power)', 'scipy.stats.qmc.Sobol (design space)', 'statsmodels.stats.outliers_influence.variance_inflation_factor'],
    topics: {
      'p:evaldesign': {
        kicker: 'DOE > Design Diagnostics', title: 'Evaluate Design',
        lead: 'How good a design is for a model, before any response is measured. The factors are coded: continuous from −1 at the low value to +1 at the high one (from the column notes a DOE table writes, else the data\'s range), categorical effect coded.',
        sections: [
          { heading: 'Roles', choices: [['X, Factor', 'The factor columns of the design.'], ['Y, Response', 'Optional: the responses, which the evaluation does not use.']] },
          { heading: 'The report', text: 'Power Analysis: the power to detect each coefficient of the anticipated size. Estimation Efficiency: the variance of each estimate and its VIF. Alias Matrix and the colour map: which effects are confounded with terms left out. Design Diagnostics: D, G and A efficiencies. The Model red triangle changes the model.' },
          { heading: 'Split plots', text: 'With a Whole Plots column (the Whole Plots role, or a column called Whole Plots among the factors, as JMP takes its Whole Plots factor) the whole plots are a random effect with a variance η times the error\'s, η the Split Plot Variance Ratio (1 by default, as JMP\'s; Advanced Options): V = σ²(I + η ZZ′). The relative variances, the power, the prediction variance profile, the fraction of design space, the alias matrix and the efficiencies use the GLS information X′V⁻¹X. Each test\'s denominator degrees of freedom (the DFDen column) are Satterthwaite\'s at the anticipated variances: a term constant within the whole plots is tested on the variation between them, with few degrees of freedom and less power, the others within them; for a balanced split plot these are the exact whole-plot and within-plot error degrees of freedom. The colour map and the VIF are properties of the model\'s columns and do not change.' },
          { heading: 'Differences from JMP', list: [
            'JMP\'s help does not say how its split-plot evaluation finds the power\'s degrees of freedom; here they are Satterthwaite\'s at the anticipated variances.',
            'The efficiencies of a split plot use the GLS information here, against an orthogonal, completely randomized design with the error variance alone.'] },
        ],
        more: { label: 'Evaluate Design', id: 'help-p-evaldesign' },
      },
    },
    launch: {
      lead: 'Choose the factor columns of a design table. The Model option sets the terms to evaluate.',
      roles: [
        { key: 'x', label: 'X, Factor', min: 1, hint: 'required',
          help: 'The factor columns of the design. A continuous one is coded −1 to +1 from the low and high values in its notes (the "Coding [low, high]" a DOE design table writes), else from the data\'s range; an ordinal or nominal one is effect coded. Rows with a missing factor are left out.' },
        { key: 'y', label: 'Y, Response', hint: 'optional',
          help: 'The responses, for the record only: the evaluation depends on the factor settings alone.' },
        { key: 'wp', label: 'Whole Plots', max: 1, hint: 'optional: a split plot\'s whole plots',
          help: 'A split plot\'s whole plots (the Whole Plots column a DOE design table has): the runs that share a setting of the hard-to-change factors. They are a random effect with a variance that is the Split Plot Variance Ratio times the error\'s (1 by default), and the evaluation allows for them: the GLS information, and each test on the whole plots or within them. A column called Whole Plots among the factors is taken as the whole plots too, as JMP takes its Whole Plots factor.' },
      ],
      options: [{ key: 'model', label: 'Model', type: 'select', value: 'main', choices: MODELS,
        help: 'The terms the design is judged for: Main Effects; with the Two-Factor Interactions; Response Surface, which adds the squares of the continuous factors; Full Factorial, every interaction. Terms left out (the next order of interactions) are the alias terms. The Model red triangle changes it later.' }],
    },
    title: () => 'Evaluate Design',
    triangle: (ctx) => [
      { label: 'Model', submenu: () => MODELS.map(([k, l]) => ({ label: l, checked: ctx.opt('model', 'main') === k, action: () => ctx.set('model', k) })) },
      { label: 'Power Settings…', action: () => powerSettings(ctx) },
      { label: 'Advanced Options', submenu: () => [{ label: 'Split Plot Variance Ratio…', disabled: !wholePlotsOf(ctx).col, action: () => wpRatioSettings(ctx) }] },
    ],
    render: evalRender,
  });

  /* ==================================================================================
     Sample Size and Power
     ================================================================================== */
  const SITUATIONS = [
    ['one_mean', 'One Sample Mean'], ['two_means', 'Two Sample Means'], ['k_means', 'k Sample Means'], ['one_prop', 'One Sample Proportion'],
    ['two_props', 'Two Sample Proportions'], ['one_var', 'One Sample Variance'], ['poisson', 'Counts per Unit'], ['sigma', 'Sigma Quality Level'],
  ];
  // The fields of each situation: [key, label, kind]; kind 'solve' is one of the three to give two of.
  const FIELDS = {
    one_mean: [['alpha', 'Alpha'], ['sd', 'Std Dev'], ['extra', 'Extra Parameters'], ['diff', 'Difference to Detect', 'solve'], ['n', 'Sample Size', 'solve'], ['power', 'Power', 'solve']],
    two_means: [['alpha', 'Alpha'], ['sd', 'Std Dev'], ['extra', 'Extra Parameters'], ['ratio', 'Group Size Ratio (n2/n1)'], ['diff', 'Difference to Detect', 'solve'], ['n', 'Sample Size (total)', 'solve'], ['power', 'Power', 'solve']],
    k_means: [['alpha', 'Alpha'], ['sd', 'Std Dev'], ['extra', 'Extra Parameters'], ['means', 'Means (separated by commas)', 'list'], ['n', 'Sample Size (total)', 'solve'], ['power', 'Power', 'solve']],
    one_prop: [['alpha', 'Alpha'], ['p0', 'Null Proportion'], ['p1', 'Proportion', 'solve'], ['n', 'Sample Size', 'solve'], ['power', 'Power', 'solve']],
    two_props: [['alpha', 'Alpha'], ['p2', 'Proportion 2'], ['null_diff', 'Null Difference in Proportion'], ['p1', 'Proportion 1', 'solve'], ['n', 'Sample Size 1', 'solve'], ['n2', 'Sample Size 2 (empty: as group 1)'], ['power', 'Power', 'solve']],
    one_var: [['alpha', 'Alpha'], ['var0', 'Baseline Variance'], ['dvar', 'Difference to Detect (variance)', 'solve'], ['n', 'Sample Size', 'solve'], ['power', 'Power', 'solve']],
    poisson: [['alpha', 'Alpha'], ['lam0', 'Baseline Count per Unit'], ['dlam', 'Difference to Detect', 'solve'], ['n', 'Sample Size (units)', 'solve'], ['power', 'Power', 'solve']],
    sigma: [['defects', 'Number of Defects', 'solve'], ['opportunities', 'Number of Opportunities', 'solve'], ['sigma_level', 'Sigma Quality Level', 'solve']],
  };
  const DEFAULTS = {
    one_mean: { alpha: 0.05, sd: 1, extra: 0, diff: 0.5, n: null, power: 0.8, sides: 2 },
    two_means: { alpha: 0.05, sd: 1, extra: 0, ratio: 1, diff: 0.5, n: null, power: 0.8, sides: 2 },
    k_means: { alpha: 0.05, sd: 1, extra: 0, means: '10, 10, 11, 12', n: null, power: 0.8 },
    one_prop: { alpha: 0.05, p0: 0.5, p1: 0.6, n: null, power: 0.8, sides: 2 },
    two_props: { alpha: 0.05, p2: 0.5, null_diff: 0, p1: 0.6, n: null, n2: null, power: 0.8, sides: 2 },
    one_var: { alpha: 0.05, var0: 1, dvar: 1, n: null, power: 0.8, sides: 1 },
    poisson: { alpha: 0.05, lam0: 2, dlam: 0.5, n: null, power: 0.8, sides: 1 },
    sigma: { defects: 3.4, opportunities: 1000000, sigma_level: null },
  };

  async function powerRender(ctx) {
    const sit = ctx.opt('situation', 'one_mean');
    const label = (SITUATIONS.find((s) => s[0] === sit) || SITUATIONS[0])[1];
    const picker = el('div', { class: 'sm-pw-sits', role: 'group', 'aria-label': 'Situation' });
    for (const [k, l] of SITUATIONS) {
      const b = el('button', { type: 'button', class: `sm-btn small${k === sit ? ' is-on' : ''}`, 'aria-pressed': String(k === sit), text: l });
      b.addEventListener('click', () => { if (k !== sit) ctx.set('situation', k); });
      picker.append(b);
    }
    ctx.container.append(picker);
    const ob = ctx.outline(label, { key: `pw:${sit}`, info: 'p:power', menu: () => [
      { label: 'Reset the Inputs', action: () => ctx.set(`in:${sit}`, { ...DEFAULTS[sit] }) },
      ctx.check('Power vs Sample Size', 'plotN', null, true),
      ctx.check('Power vs Difference', 'plotDiff', null, true),
    ] });
    const vals = { ...DEFAULTS[sit], ...(ctx.opt(`in:${sit}`, {}) || {}) };
    const inputs = {};
    const form = el('div', { class: 'sm-form sm-pw-form' });
    for (const [key, lab, kind] of FIELDS[sit]) {
      const i = el('input', { type: 'text', inputmode: kind === 'list' ? 'text' : 'decimal', size: kind === 'list' ? 24 : 10, 'aria-label': lab, dataset: { key } });
      i.value = vals[key] == null ? '' : String(vals[key]);
      inputs[key] = i;
      form.append(el('label', { text: lab + (kind === 'solve' ? ' ◦' : '') }), i);
    }
    let sides = null;
    if ('sides' in DEFAULTS[sit]) {
      sides = el('select', { 'aria-label': 'Sides' }, el('option', { value: '2', text: 'Two-sided' }), el('option', { value: '1', text: 'One-sided' }));
      sides.value = String(vals.sides ?? 2);
      form.append(el('label', { text: 'Test' }), sides);
    }
    const go = el('button', { type: 'button', class: 'sm-btn primary', text: 'Continue' });
    const help = el('p', { class: 'sm-ob-note', text: sit === 'sigma' ? 'Give two of the three; the third is computed.' : 'Give two of the fields marked ◦ and leave one empty: it is computed. With only the difference, or only the sample size, the power curve answers.' });
    const results = el('div', { class: 'sm-pw-results' });
    const plots = el('div', { class: 'sm-ob-row' });
    ob.add(el('div', { class: 'sm-pw-top' }, el('div', null, form, el('div', { class: 'sm-pw-go' }, go)), el('div', null, results)), help, plots);
    const read = () => {
      const v = {};
      for (const [key, , kind] of FIELDS[sit]) {
        const t = inputs[key].value.trim();
        v[key] = kind === 'list' ? t : (t === '' ? null : toNum(t));
      }
      if (sides) v.sides = Number(sides.value);
      return v;
    };
    let seq = 0;
    const update = async (store) => {
      const v = read();
      for (const [key, lab, kind] of FIELDS[sit]) if (kind !== 'list' && Number.isNaN(v[key])) { results.replaceChildren(ctx.warn(`${lab}: not a number`)); return; }
      if (store) ctx.set(`in:${sit}`, v, null, { rerun: false });
      const payload = { situation: sit, ...v };
      if (sit === 'k_means') payload.means = String(v.means || '').split(/[,;\s]+/).map(toNum).filter((x) => x != null && Number.isFinite(x));
      const my = ++seq;
      ctx.report.pyCode = [];
      let r;
      try { r = await ctx.call('power.compute', payload); } catch (e) { results.replaceChildren(ctx.error(e)); return; }
      if (my !== seq) return;
      for (const i of Object.values(inputs)) { i.placeholder = ''; i.classList.remove('is-solved'); }
      if (r.error) { results.replaceChildren(ctx.warn(r.error)); purge(plots); plots.replaceChildren(); return; }
      if (r.solved && inputs[r.solved] != null) {
        const x = r.values[r.solved];
        inputs[r.solved].placeholder = x == null ? 'no solution' : `= ${fmt(x, { sig: 6 })}`;
        if (inputs[r.solved].value.trim() === '' ) inputs[r.solved].classList.add('is-solved');
      }
      const pairs = [];
      for (const [key, lab, kind] of FIELDS[sit]) {
        if (kind === 'list') { pairs.push([lab, String(v.means || ''), 'text']); continue; }
        const x = key in r.values ? r.values[key] : v[key];
        if (x == null && kind !== 'solve') continue;
        pairs.push([`${lab}${r.solved === key ? ' (computed)' : ''}`, x]);
      }
      for (const row of r.rows || []) pairs.push(row);
      results.replaceChildren(ctx.kv(pairs), ...(r.notes || []).map((n) => ctx.note(n)), ctx.code(r.code));
      purge(plots);
      plots.replaceChildren(...curvePlots(ctx, r, sit));
    };
    const purge = (host) => {
      for (const box of host.querySelectorAll('.sm-plot')) {
        const p = box._plot;
        if (!p) continue;
        p.purge();
        const k = ctx.report.plots.indexOf(p);
        if (k >= 0) ctx.report.plots.splice(k, 1);
      }
    };
    for (const i of Object.values(inputs)) {
      i.addEventListener('change', () => update(true));
      i.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); update(true); } });
    }
    if (sides) sides.addEventListener('change', () => update(true));
    go.addEventListener('click', () => update(true));
    await update(false);
  }

  function curvePlots(ctx, r, sit) {
    const c = colors();
    const out = [];
    const cur = r.values;
    const mk = (curve, xTitle, atX, atY, key) => {
      const traces = [{ type: 'scatter', mode: 'lines', x: curve.x, y: curve.y, line: { color: c.curve, width: 2, shape: 'linear' }, name: curve.y_exact ? 'Normal approximation' : 'Power', hovertemplate: `${esc(xTitle)} %{x}: power %{y:.4f}<extra></extra>` }];
      if (curve.y_exact) traces.push({ type: 'scatter', mode: 'lines', x: curve.x, y: curve.y_exact, line: { color: c.exact, width: 1.3, shape: key === 'n' ? 'hv' : 'linear' }, name: 'Exact', hovertemplate: `${esc(xTitle)} %{x}: exact power %{y:.4f}<extra></extra>` });
      if (atX != null && atY != null && Number.isFinite(atX) && Number.isFinite(atY)) traces.push({ type: 'scatter', mode: 'markers', x: [atX], y: [atY], marker: { size: 9, color: c.mark, symbol: 'diamond' }, name: 'Here', hovertemplate: `${esc(xTitle)} %{x:.4g}: power %{y:.4f}<extra></extra>` });
      return ctx.plot(traces, {
        xaxis: { title: { text: esc(xTitle) } }, yaxis: { title: { text: 'Power' }, range: [0, 1.02] },
        shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: r.alpha, y1: r.alpha, line: { color: c.muted, width: 1, dash: 'dot' } }],
        showlegend: !!curve.y_exact, legend: { orientation: 'h', y: -0.28 }, margin: { l: 52, r: 12, t: 10, b: curve.y_exact ? 64 : 44 },
      }, { width: fitWidth(ctx, 380, 240), height: curve.y_exact ? 300 : 270, title: `Power vs ${xTitle}`, select: false });
    };
    const pc = r.plot_code || {};
    if (r.curves.n && ctx.opt('plotN', true)) out.push(withCode(ctx, mk(r.curves.n, r.curves.n.label, cur.n, cur.power, 'n'), pc.n));
    if (r.curves.diff && ctx.opt('plotDiff', true)) {
      const key = sit === 'one_prop' || sit === 'two_props' ? 'p1' : sit === 'one_var' ? 'dvar' : sit === 'poisson' ? 'dlam' : 'diff';
      out.push(withCode(ctx, mk(r.curves.diff, r.curves.diff.label, cur[key], cur.power, 'diff'), pc.diff));
    }
    return out;
  }

  SM.platforms.register({
    id: 'power', label: 'Sample Size and Power', menu: 'DOE/Sample Size Explorers', order: 10, info: 'p:power', needsTable: false,
    about: 'Sample size, power or the detectable difference for one and two sample means, k means (ANOVA), one and two proportions (normal approximation and exact binomial), one variance, a Poisson rate (counts per unit) and the sigma quality level, with power curves against the sample size and the difference.',
    uses: ['statsmodels.stats.power: TTestPower, TTestIndPower, FTestAnovaPower, NormalIndPower, ttest_power', 'statsmodels.stats.proportion: proportion_effectsize, power_proportions_2indep, binom_test_reject_interval', 'scipy.stats (chi2, poisson, norm)'],
    topics: {
      'p:power': {
        kicker: 'DOE > Sample Size Explorers', title: 'Sample Size and Power',
        lead: 'Pick a situation, fill in the fields and leave one of the fields marked ◦ empty: Continue (or Enter) computes it. With only the difference, or only the sample size, the graphs show the power curve.',
        sections: [
          { heading: 'Situations', choices: [['One and Two Sample Means', 't tests (statsmodels TTestPower, TTestIndPower); for two means the sample size is the total of both groups; Extra Parameters take error degrees of freedom.'], ['k Sample Means', 'One-way ANOVA from the means and σ (Cohen\'s f, FTestAnovaPower); the sample size is the total.'], ['Proportions', 'One sample: the normal approximation on Cohen\'s h and the exact binomial power. Two samples: the pooled z test (power_proportions_2indep); with a Null Difference other than 0, the normal approximation with unpooled variances (Chow, Shao and Wang).'], ['One Sample Variance', 'The χ² test of σ₀² against σ₀² + the difference; exact.'], ['Counts per Unit', 'A Poisson rate per unit against the baseline plus the difference; normal approximation and exact.'], ['Sigma Quality Level', 'Φ⁻¹(1 − defects/opportunities) + 1.5.']] },
          { heading: 'Whole numbers', text: 'A computed sample size is fractional; the report also gives the smallest whole one that reaches the power, and for proportions and counts the smallest with the exact power.' },
          { heading: 'In the report', choices: [
            ['The situation buttons', 'Above the report: each situation has its own fields, and the values entered in them are kept when you come back to it.'],
            ['Fields marked ◦', 'The effect, the sample size and the power: give two and leave one empty, and it is computed (shown in its field as = value). With all three given, the power is computed again from the other two.'],
            ['Test', 'Two-sided or one-sided, in the direction of the difference given (not for k means and the sigma level). Two-sided by default, but one-sided for One Sample Variance and Counts per Unit.'],
            ['Continue', 'Compute. Enter in a field, or leaving a field you changed, does the same.'],
            ['Reset the Inputs', 'In the red triangle: the situation\'s default values again.']] },
          { heading: 'Means', choices: [
            ['Alpha', 'The significance level of the test, in every situation but the sigma level; 0.05 by default.'],
            ['Std Dev', 'The standard deviation σ of the response, which the difference is measured against.'],
            ['Extra Parameters', 'Parameters of the model beyond the means (covariates, blocks): each takes one error degree of freedom. 0 by default.'],
            ['Group Size Ratio (n2/n1)', 'Two Sample Means: the second group\'s size over the first\'s; the total is split in this ratio. 1 is equal groups.'],
            ['Difference to Detect', 'One mean: μ − μ₀; two means: μ₁ − μ₂; in the units of the response. With a one-sided test its sign gives the direction.'],
            ['Means (separated by commas)', 'k Sample Means: the group means you expect, two or more; the effect is Cohen\'s f, their standard deviation over Std Dev.'],
            ['Sample Size, Sample Size (total)', 'One mean: n; two and k means: the total over the groups.'],
            ['Power', 'The probability of rejecting the null hypothesis when the effect is as given; 0.8 by default.']] },
          { heading: 'Proportions', choices: [
            ['Null Proportion', 'One Sample Proportion: p₀, the proportion under the null hypothesis.'],
            ['Proportion', 'One Sample Proportion: the true proportion to detect.'],
            ['Proportion 1, Proportion 2', 'Two Sample Proportions: the first group\'s proportion to detect, and the second group\'s.'],
            ['Null Difference in Proportion', 'Two Sample Proportions: p₁ − p₂ under the null hypothesis. 0 tests equal proportions (the pooled z test); another value a difference of that margin (non-inferiority or superiority), by the normal approximation with unpooled variances of Chow, Shao and Wang: the power Φ(|p₁ − p₂ − δ₀|/√(p₁(1 − p₁)/n₁ + p₂(1 − p₂)/n₂) − z), z the one- or two-sided critical value, and the sample size solved from it. The report\'s note says which.'],
            ['Sample Size 1', 'The size of the first group.'],
            ['Sample Size 2 (empty: as group 1)', 'The size of the second group: with Sample Size 1 given, their ratio. When Sample Size 1 is the field computed, the groups are taken as equal.']] },
          { heading: 'Variance, counts and sigma', choices: [
            ['Baseline Variance', 'One Sample Variance: σ₀², the variance under the null hypothesis.'],
            ['Difference to Detect (variance)', 'σ₁² − σ₀²; a negative difference tests for a smaller variance.'],
            ['Baseline Count per Unit', 'Counts per Unit: λ₀, the rate per unit under the null hypothesis.'],
            ['Difference to Detect', 'Counts per Unit: λ₁ − λ₀, the change in the count per unit.'],
            ['Sample Size (units)', 'Counts per Unit: the number of units observed.'],
            ['Number of Defects, Number of Opportunities, Sigma Quality Level', 'Sigma Quality Level: give two and the third is computed, with the level = Φ⁻¹(1 − defects/opportunities) + 1.5.']] },
        ],
        more: { label: 'Sample Size and Power', id: 'help-p-power' },
      },
    },
    title: () => 'Sample Size and Power',
    triangle: (ctx) => [{ label: 'Situation', submenu: () => SITUATIONS.map(([k, l]) => ({ label: l, checked: ctx.opt('situation', 'one_mean') === k, action: () => ctx.set('situation', k) })) }],
    render: powerRender,
  });
}(typeof self !== 'undefined' ? self : this));
