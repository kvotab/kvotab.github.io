/* ==========================================================================
   SMUI.HTML: THE PREDICTION PROFILER, FOR ANY PLATFORM

   A platform whose backend lets its models be profiled (profile.expose in
   resources/py/smui/profile.py registers '<area>.profile') gets JMP's
   Prediction Profiler with one call:

     await SM.profiler.render(ctx, parent, {
       sources: [{ fn: 'partition.profile', payload }],   // one or more models
       scope,              // the option scope (a response's column id), or null
       option: 'profiler', // the option that shows it (Remove clears it)
     });

   One small plot per response and factor: the prediction as the factor
   runs over its range, the other factors at their current values (drag
   the red dashed line, click in the plot, or type the value below it),
   dotted limits when the backend gives them. The current values are an
   option of the report, one set per By group.

   From its red triangle, as JMP's: Desirability Functions (a function per
   response, set with Set Desirabilities; the Desirability row is their
   weighted geometric mean over each factor), Maximize Desirability (the
   factors moved to the best setting: '<area>.maximize'), Remember Settings
   (a table of settings and predictions), Assess Variable Importance
   (Sobol main and total effects: '<area>.importance'), Marginal Model
   Plots (partial dependence with ICE lines: '<area>.marginal') and Save
   Shapley Values (permutation SHAP of every row: '<area>.shapley'). These
   work with one source (one model).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el, fmt } = SM.util;

  function pal() {
    const c = SM.util.themeColors();
    return { point: SM.report.BASE, fit: c.dark ? '#ff7a6b' : '#c0392b', muted: c.muted };
  }

  function extent(...arrs) {
    let lo = Infinity, hi = -Infinity;
    for (const a of arrs) if (a) for (const v of a) if (v != null && Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (!(lo <= hi)) return [0, 1];
    if (lo === hi) return [lo - 0.5, hi + 0.5];
    return [lo, hi];
  }

  const lineTrace = (x, y, color, dash = 'solid', width = 1.3) => ({ type: 'scatter', mode: 'lines', x, y, line: { color, dash, width }, hoverinfo: 'skip', showlegend: false });

  const GOALS = [['max', 'Maximize'], ['min', 'Minimize'], ['target', 'Match Target'], ['none', 'None']];
  const DEFAULT_D = { max: [0.0183, 0.5, 0.9817], min: [0.9817, 0.5, 0.0183], target: [0.0183, 1, 0.0183] };
  const defaultSpec = (goal, lo, hi) => {
    if (!(hi > lo)) hi = lo + 1;
    const d = DEFAULT_D[goal];
    return { goal, points: d ? [[lo, d[0]], [(lo + hi) / 2, d[1]], [hi, d[2]]] : [], importance: 1 };
  };

  async function render(ctx, parent, { sources, scope = null, title = 'Prediction Profiler', key = 'profiler', option = 'profiler', info = 'p:profiler', note = null, stateKey: givenKey = null }) {
    const P = pal();
    const stateKey = givenKey || `profilerAt:${option}:${ctx.byLabel || ''}`;
    const desKey = `profilerDes:${option}`;
    const memKey = `profilerMem:${option}:${ctx.byLabel || ''}`;
    const impKey = `profilerImp:${option}`;
    const margKey = `profilerMarg:${option}`;
    const iceKey = `profilerICE:${option}`;
    const single = sources.length === 1;
    const fnOf = (what) => sources[0].fn.replace(/\.profile$/, `.${what}`);
    const can = (what) => single && SM.engine.has(fnOf(what));
    let current = { ...(ctx.opt(stateKey, null, scope) || {}) };
    const des = single ? ctx.opt(desKey, null, scope) : null;
    const remembered = ctx.opt(memKey, null, scope) || [];
    const impMethod = can('importance') ? ctx.opt(impKey, null, scope) : null;
    const margOn = can('marginal') && !!ctx.opt(margKey, false, scope);
    let res = null;
    const ob = ctx.outline(title, { parent, key, info, menu: () => [
      { label: 'Desirability Functions', checked: !!des, disabled: !can('maximize'), action: () => ctx.set(desKey, des ? null : defaults(), scope) },
      { label: 'Maximize Desirability', disabled: !des || !can('maximize'), action: () => maximize() },
      { label: 'Set Desirabilities…', disabled: !des, action: () => setDesirabilities() },
      { label: 'Remember Settings', disabled: !res, action: () => remember() },
      { label: 'Assess Variable Importance', disabled: !can('importance'), submenu: () => [
        { label: 'Independent Uniform Inputs', checked: impMethod === 'uniform', action: () => ctx.set(impKey, impMethod === 'uniform' ? null : 'uniform', scope) },
        { label: 'Independent Resampled Inputs', checked: impMethod === 'resampled', action: () => ctx.set(impKey, impMethod === 'resampled' ? null : 'resampled', scope) },
      ] },
      { label: 'Marginal Model Plots', checked: margOn, disabled: !can('marginal'), action: () => ctx.set(margKey, !margOn, scope) },
      { label: 'ICE Lines', checked: !!ctx.opt(iceKey, false, scope), disabled: !margOn, action: () => ctx.set(iceKey, !ctx.opt(iceKey, false, scope), scope) },
      { label: 'Save Shapley Values…', disabled: !can('shapley') || !ctx.table, action: () => saveShapley(ctx, { fn: fnOf('shapley'), payload: sources[0].payload, key, scope }) },
      { separator: true },
      { label: 'Reset Factor Settings', action: () => ctx.set(stateKey, null, scope) },
      { label: 'Remove', action: () => ctx.set(option, false, scope) },
    ] });
    const load = async () => {
      const outs = await Promise.all(sources.map((s) => ctx.call(s.fn, { ...s.payload, current, alpha: ctx.alpha, ...(des ? { des } : {}) })));
      return { factors: outs[0].factors, responses: outs.flatMap((x) => x.responses), desirability: single ? outs[0].desirability || null : null };
    };
    // For tests and the console: what this profiler asks and where it keeps its state.
    ob.el._profiler = { sources, scope, stateKey, desKey, memKey, impKey };
    try { res = await load(); } catch (e) { ob.add(ctx.error(e)); return ob; }
    // Desirability Functions on: every response Maximize over its row's range (JMP's default).
    function defaults() {
      const out = {};
      res.responses.forEach((r, ri) => { const [lo, hi] = rowRange(r); out[r.name] = defaultSpec('max', lo, hi); });
      return out;
    }
    function rowRange(r) {
      if (r.bounded) return [0, 1];
      return extent(...r.traces.flatMap((t) => [t.pred, t.lower, t.upper]));
    }
    async function maximize() {
      try {
        const out = await ctx.call(fnOf('maximize'), { ...sources[0].payload, current, alpha: ctx.alpha, des, max_seed: 1 });
        current = { ...out.best.setting };
        ctx.set(stateKey, current, scope, { rerun: false });
        res = { factors: out.profile.factors, responses: out.profile.responses, desirability: out.profile.desirability || null };
        redraw();
        SM.ui.toast(`Maximized: desirability ${fmt(out.best.desirability, { sig: 5 })}`);
      } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
    }
    function remember() {
      const row = { setting: remembered.length + 1, ...Object.fromEntries(res.factors.map((f) => [`f:${f.name}`, f.current])), ...Object.fromEntries(res.responses.map((r) => [`r:${r.name}`, r.current.pred])) };
      if (res.desirability) row.D = res.desirability.current;
      ctx.set(memKey, [...remembered, row], scope);
    }
    async function setDesirabilities(only = null) {
      const cur = des || defaults();
      const fields = [];
      for (const r of res.responses) {
        if (only && r.name !== only) continue;
        const sp = cur[r.name] || defaultSpec('max', ...rowRange(r));
        const pts = sp.points.length === 3 ? sp.points : defaultSpec('max', ...rowRange(r)).points;
        const k = (x) => `${r.name}\u0001${x}`;
        fields.push({ key: k('goal'), label: `${r.name}: Goal`, type: 'select', value: sp.goal, choices: GOALS, helpLabel: 'Goal', help: 'Maximize: larger values are more desirable. Minimize: smaller values are. Match Target: values near the middle point are. None: the response is left out of the overall desirability. Changing the goal keeps the points: set their desirabilities to match.' });
        ['Low', 'Middle', 'High'].forEach((nm, i) => {
          fields.push({ key: k(`y${i}`), label: `${nm} value`, type: 'number', value: Number.isFinite(pts[i][0]) ? +Number(pts[i][0]).toPrecision(7) : pts[i][0], helpLabel: 'Low, Middle and High value', help: 'Three values of the response through which the desirability function runs, in any order; it is flat beyond the outer two. They start at the ends and the middle of the range the profiler\'s curves cover.' });
          fields.push({ key: k(`d${i}`), label: `${nm} desirability`, type: 'number', value: pts[i][1], helpLabel: 'Low, Middle and High desirability', help: 'How desirable each value is, from 0 (unacceptable: an overall desirability of 0) to 1 (ideal). JMP\'s defaults for Maximize are 0.0183, 0.5 and 0.9817, for Minimize the reverse, and for Match Target 0.0183, 1 and 0.0183.' });
        });
        fields.push({ key: k('importance'), label: 'Importance', type: 'number', value: sp.importance ?? 1, help: 'The weight of the response in the overall desirability, the weighted geometric mean (d₁^w₁ · d₂^w₂ · …)^(1/(w₁ + w₂ + …)): only the ratios of the importances matter, and 0 leaves the response out.' });
      }
      const v = await SM.ui.form({ title: 'Set Desirabilities', info: 'p:profiler:desirability', lead: 'For each response: its goal, three points of its desirability function (a value and its desirability between 0 and 1), and its importance in the overall desirability.', fields,
        validate: (x) => { for (const [kk, val] of Object.entries(x)) if (/\u0001d\d$/.test(kk) && val != null && (val < 0 || val > 1)) return 'A desirability is between 0 and 1'; return null; } });
      if (!v) return;
      const out = { ...cur };
      for (const r of res.responses) {
        if (only && r.name !== only) continue;
        const k = (x) => v[`${r.name}\u0001${x}`];
        const goal = k('goal');
        const pts = [0, 1, 2].map((i) => [k(`y${i}`), k(`d${i}`)]);
        if (goal !== 'none' && pts.some(([a, b]) => a == null || b == null)) { SM.ui.toast(`${r.name}: every point needs a value and a desirability`, { error: true }); return; }
        out[r.name] = { goal, points: goal === 'none' ? [] : pts, importance: k('importance') ?? 1 };
      }
      ctx.set(desKey, out, scope);
    }
    const F = res.factors;
    if (!F.length) { ob.add(ctx.note('The model has no factors to profile.')); return ob; }
    const nf = F.length;
    const desOn = !!(des && res.desirability);
    const avail = Math.max(320, Math.min(1180, (root.innerWidth || 1200) - 150 - (desOn ? 110 : 0)));
    const pw = Math.max(118, Math.min(215, Math.floor((avail - 130) / nf)));
    const ph = res.responses.length > 2 ? 140 : 175;
    const grid = el('div', { class: 'sm-prof', style: { gridTemplateColumns: `minmax(92px, max-content) repeat(${nf}, max-content)${desOn ? ' max-content' : ''}` } });
    const yr = res.responses.map((r) => {
      if (r.bounded) return [0, 1];
      const [lo, hi] = extent(...r.traces.flatMap((t) => [t.pred, t.lower, t.upper]));
      const pad = 0.06 * (hi - lo);
      return [lo - pad, hi + pad];
    });
    const labelOfLevel = (f, v) => { const i = f.levels.findIndex((x) => x === v || String(x) === String(v)); return i >= 0 ? f.labels[i] : String(v); };
    const traces = (ri, fi) => {
      const r = res.responses[ri], tr = r.traces[fi], f = res.factors[fi];
      const cat = f.type === 'categorical';
      const out = [];
      if (tr.lower && tr.upper) {
        for (const b of [tr.upper, tr.lower]) out.push({ type: 'scatter', mode: cat ? 'markers' : 'lines', x: tr.x, y: b, line: { color: P.fit, width: 1, dash: 'dot' }, marker: { symbol: 'line-ew-open', size: 11, color: P.fit, line: { width: 1.2, color: P.fit } }, hoverinfo: 'skip', showlegend: false });
      }
      out.push({ type: 'scatter', mode: cat ? 'lines+markers' : 'lines', x: tr.x, y: tr.pred, line: { color: P.point, width: 1.8 }, marker: { size: 6, color: P.point }, hovertemplate: `${SM.report.plotlyText(f.name)} %{x}<br>${SM.report.plotlyText(r.name)} %{y:.5g}<extra></extra>`, showlegend: false });
      out.push(lineTrace([tr.x[0], tr.x[tr.x.length - 1]], [r.current.pred, r.current.pred], P.fit, 'dash', 1));
      return out;
    };
    const layout = (ri, fi) => {
      const f = res.factors[fi];
      const cat = f.type === 'categorical';
      const cur = cat ? labelOfLevel(f, f.current) : f.current;
      return {
        margin: { l: fi === 0 ? 48 : 6, r: 6, t: 6, b: 24 }, hovermode: 'x', dragmode: false,
        xaxis: cat ? { type: 'category', tickfont: { size: 9 }, fixedrange: true, showgrid: false } : { range: [f.min, f.max], tickfont: { size: 9 }, fixedrange: true, showgrid: false, nticks: 4 },
        yaxis: { range: yr[ri], showticklabels: fi === 0, tickfont: { size: 9 }, fixedrange: true, nticks: 5 },
        shapes: [{ type: 'line', xref: 'x', yref: 'paper', x0: cur, x1: cur, y0: 0, y1: 1, line: { color: P.fit, width: 1.4, dash: 'dash' } }],
      };
    };
    const cells = res.responses.map(() => []);
    const vals = [];
    let busy = false, pending = false;
    const setFactor = async (fi, x) => {
      const f = res.factors[fi];
      let v;
      if (f.type === 'categorical') {
        let i = typeof x === 'number' ? Math.round(x) : f.labels.indexOf(String(x));
        i = Math.max(0, Math.min(f.levels.length - 1, i < 0 ? 0 : i));
        v = f.levels[i];
      } else {
        v = Number(x);
        if (!Number.isFinite(v)) return;
        v = Math.max(f.min, Math.min(f.max, v));
      }
      current = { ...current, [f.name]: v };
      if (busy) { pending = true; return; }
      busy = true;
      try {
        do {
          pending = false;
          ctx.set(stateKey, current, scope, { rerun: false });
          res = await load();
          redraw();
        } while (pending);
      } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); } finally { busy = false; }
    };
    const wire = (fi) => (gd) => {
      gd.on('plotly_relayout', (ev) => { const k = ev && Object.keys(ev).find((q) => /^shapes\[0\]\.x0$/.test(q)); if (k) setFactor(fi, ev[k]); });
      gd.on('plotly_click', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt) setFactor(fi, pt.x); });
    };
    const valueBox = (ri) => {
      const r = res.responses[ri];
      const c = r.current;
      const d = desOn && res.desirability && res.desirability.individual ? res.desirability.individual[r.name] : null;
      return [el('span', { class: 'sm-prof-name', text: r.name }), el('span', { class: 'sm-prof-val', text: fmt(c.pred, { sig: 6 }) }),
        c.lower != null ? el('span', { class: 'sm-prof-ci', text: `[${fmt(c.lower, { sig: 5 })}, ${fmt(c.upper, { sig: 5 })}]` }) : null,
        d != null ? el('span', { class: 'sm-prof-ci', text: `desirability ${fmt(d, { sig: 4 })}` }) : null];
    };
    // the desirability function of a response, drawn as JMP does: the response up, desirability across
    const desTraces = (ri) => {
      const r = res.responses[ri];
      const cv = res.desirability && res.desirability.curves[r.name];
      const sp = des && des[r.name];
      if (!cv || !sp) return [lineTrace([0, 1], [r.current.pred, r.current.pred], P.muted, 'dot', 1)];
      return [{ type: 'scatter', mode: 'lines', x: cv.d, y: cv.y, line: { color: P.point, width: 1.6 }, hovertemplate: `${SM.report.plotlyText(r.name)} %{y:.5g}<br>desirability %{x:.4f}<extra></extra>`, showlegend: false },
        { type: 'scatter', mode: 'markers', x: sp.points.map((q) => q[1]), y: sp.points.map((q) => q[0]), marker: { size: 7, color: P.fit }, hoverinfo: 'skip', showlegend: false },
        lineTrace([0, 1], [r.current.pred, r.current.pred], P.fit, 'dash', 1)];
    };
    const desLayout = (ri) => ({ margin: { l: 6, r: 8, t: 6, b: 24 }, hovermode: 'closest', dragmode: false, xaxis: { range: [-0.02, 1.02], tickvals: [0, 0.5, 1], tickfont: { size: 9 }, fixedrange: true, showgrid: false }, yaxis: { range: yr[ri], showticklabels: false, fixedrange: true, nticks: 5 } });
    const dRange = [0, 1.02];
    const Dtraces = (fi) => {
      const dr = res.desirability, f = res.factors[fi];
      const tr = dr.traces[fi];
      const cat = f.type === 'categorical';
      return [{ type: 'scatter', mode: cat ? 'lines+markers' : 'lines', x: tr.x, y: tr.D, line: { color: P.point, width: 1.8 }, marker: { size: 6, color: P.point }, hovertemplate: `${SM.report.plotlyText(f.name)} %{x}<br>desirability %{y:.4f}<extra></extra>`, showlegend: false },
        lineTrace([tr.x[0], tr.x[tr.x.length - 1]], [dr.current, dr.current], P.fit, 'dash', 1)];
    };
    const Dlayout = (fi) => { const L = layout(0, fi); return { ...L, yaxis: { ...L.yaxis, range: dRange, showticklabels: fi === 0 } }; };
    const desCells = [];
    res.responses.forEach((r, ri) => {
      const lab = el('div', { class: 'sm-prof-y' }, ...valueBox(ri).filter(Boolean));
      vals.push(lab);
      grid.append(lab);
      F.forEach((f, fi) => {
        const box = ctx.plot(traces(ri, fi), layout(ri, fi), { width: pw + (fi === 0 ? 42 : 0), height: ph, select: false, fit: false, title: `${r.name} profile over ${f.name}`, config: { edits: { shapePosition: true }, displayModeBar: false }, onDraw: wire(fi) });
        cells[ri].push(box);
        grid.append(box);
      });
      if (desOn) {
        const box = ctx.plot(desTraces(ri), desLayout(ri), { width: 96, height: ph, select: false, fit: false, title: `${r.name} desirability`, config: { displayModeBar: false }, onDraw: (gd) => gd.on('plotly_click', () => setDesirabilities(r.name)) });
        box.classList.add('sm-prof-des');
        box.title = 'Click to set this desirability';
        desCells.push(box);
        grid.append(box);
      }
    });
    let dLabel = null;
    const dCells = [];
    if (desOn) {
      dLabel = el('div', { class: 'sm-prof-y' }, el('span', { class: 'sm-prof-name', text: 'Desirability' }), el('span', { class: 'sm-prof-val', text: fmt(res.desirability.current, { sig: 5 }) }));
      grid.append(dLabel);
      F.forEach((f, fi) => {
        const box = ctx.plot(Dtraces(fi), Dlayout(fi), { width: pw + (fi === 0 ? 42 : 0), height: Math.round(ph * 0.8), select: false, fit: false, title: `Desirability over ${f.name}`, config: { edits: { shapePosition: true }, displayModeBar: false }, onDraw: wire(fi) });
        dCells.push(box);
        grid.append(box);
      });
      grid.append(el('div'));
    }
    grid.append(el('div', { class: 'sm-prof-y sm-prof-corner', text: 'Factors' }));
    const inputs = F.map((f, fi) => {
      let input;
      if (f.type === 'categorical') {
        input = el('select', { 'aria-label': `${f.name} current value` }, ...f.labels.map((l, i) => el('option', { value: String(i), text: l })));
        input.value = String(Math.max(0, f.levels.findIndex((x) => x === f.current)));
        input.addEventListener('change', () => setFactor(fi, Number(input.value)));
      } else {
        input = el('input', { type: 'text', inputmode: 'decimal', size: 8, 'aria-label': `${f.name} current value` });
        input.value = fmt(f.current, { sig: 6 }).replace('−', '-');
        const apply = () => setFactor(fi, SM.table.toNumber(input.value.replace(',', '.')));
        input.addEventListener('change', apply);
        input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); apply(); } });
      }
      const slider = f.type === 'continuous' ? el('input', { type: 'range', min: String(f.min), max: String(f.max), step: String((f.max - f.min) / 200 || 1), value: String(f.current), 'aria-label': `${f.name} slider` }) : null;
      if (slider) slider.addEventListener('change', () => setFactor(fi, Number(slider.value)));
      grid.append(el('div', { class: 'sm-prof-x', style: { width: `${pw + (fi === 0 ? 42 : 0)}px` } }, el('span', { class: 'sm-prof-fname', text: f.name }), input, slider));
      return { input, slider };
    });
    if (desOn) grid.append(el('div', { class: 'sm-prof-x sm-prof-corner', text: 'Desirability' }));
    const update = (box, tr, lay) => {
      const p = box._plot;
      if (p && p.drawn) Plotly.react(box, tr, SM.report.merge(box.layout, { shapes: lay.shapes || [], yaxis: { range: lay.yaxis.range } }));
      else if (p) { p.traces = tr; p.userLayout = lay; }
    };
    // A move can take a prediction beyond its row's range: widen it (never narrow, so the eye keeps its scale).
    const widen = () => res.responses.forEach((r, ri) => {
      if (r.bounded) return;
      const [lo, hi] = extent(...r.traces.flatMap((t) => [t.pred, t.lower, t.upper]));
      if (lo < yr[ri][0] || hi > yr[ri][1]) { const pad = 0.06 * (hi - lo); yr[ri] = [Math.min(yr[ri][0], lo - pad), Math.max(yr[ri][1], hi + pad)]; }
    });
    const redraw = () => {
      widen();
      res.responses.forEach((r, ri) => {
        vals[ri].replaceChildren(...valueBox(ri).filter(Boolean));
        res.factors.forEach((f, fi) => update(cells[ri][fi], traces(ri, fi), layout(ri, fi)));
        if (desOn && res.desirability) update(desCells[ri], desTraces(ri), desLayout(ri));
      });
      if (desOn && res.desirability) {
        dLabel.lastChild.textContent = fmt(res.desirability.current, { sig: 5 });
        res.factors.forEach((f, fi) => update(dCells[fi], Dtraces(fi), Dlayout(fi)));
      }
      res.factors.forEach((f, fi) => {
        const { input, slider } = inputs[fi];
        if (f.type === 'categorical') input.value = String(Math.max(0, f.levels.findIndex((x) => x === f.current || String(x) === String(f.current))));
        else { if (document.activeElement !== input) input.value = fmt(f.current, { sig: 6 }).replace('−', '-'); if (slider) slider.value = String(f.current); }
      });
    };
    ob.add(el('div', { class: 'sm-profwrap' }, grid), ctx.note(note || 'Drag the red dashed line of a factor, click in its plot, or type its value.'));
    if (desOn) ob.add(ctx.note('Desirability: each response\'s function at the right (click it to set it); the Desirability row is their geometric mean, weighted by importance. Maximize Desirability in the red triangle finds the best setting.'));
    if (remembered.length) {
      const cols = [{ key: 'setting', label: 'Setting', fmt: 'int' }, ...res.factors.map((f) => ({ key: `f:${f.name}`, label: f.name, fmt: f.type === 'categorical' ? 'text' : 'num' })),
        ...res.responses.map((r) => ({ key: `r:${r.name}`, label: r.name })), ...(remembered.some((m) => m.D != null) ? [{ key: 'D', label: 'Desirability' }] : [])];
      const rows = remembered.map((m) => ({ ...m, ...Object.fromEntries(res.factors.filter((f) => f.type === 'categorical').map((f) => { const i = f.levels.findIndex((x) => x === m[`f:${f.name}`] || String(x) === String(m[`f:${f.name}`])); return [`f:${f.name}`, i >= 0 ? f.labels[i] : String(m[`f:${f.name}`] ?? '')]; })) }));
      const mem = ctx.outline('Remembered Settings', { parent: ob, key: `${key}:remembered`, info: 'p:profiler', menu: () => [{ label: 'Clear', action: () => ctx.set(memKey, null, scope) }] });
      mem.add(ctx.rt({ columns: cols, rows }, { key: 'remembered', sortable: false, onRow: (row) => { const back = remembered.find((m) => m.setting === row.setting); if (back) ctx.set(stateKey, Object.fromEntries(res.factors.map((f) => [f.name, back[`f:${f.name}`]])), scope); } }),
        ctx.note('Click a row to set the factors to it again.'));
    }
    if (impMethod) await importanceReport(ctx, ob, { fn: fnOf('importance'), payload: sources[0].payload, method: impMethod, key, scope, impKey });
    if (margOn) await marginalReport(ctx, ob, { fn: fnOf('marginal'), payload: sources[0].payload, key, scope, margKey, ice: !!ctx.opt(iceKey, false, scope) });
    return ob;
  }

  /* Marginal Model Plots: each response's mean prediction over the background rows as one factor runs over its
     range, the others at the rows' own values (partial dependence), with ICE lines on request. Drawn from the
     prediction, as the profiler is (no code block of their own: they sit in the profiler's grid). */
  async function marginalReport(ctx, parent, { fn, payload, key, scope, margKey, ice }) {
    const ob = ctx.outline('Marginal Model Plots', { parent, key: `${key}:marginal`, info: 'p:profiler:marginal', menu: () => [{ label: 'Remove', action: () => ctx.set(margKey, false, scope) }] });
    let r;
    try { r = await ctx.call(fn, { ...payload, mm_n: 200, mm_ice: ice ? 30 : 0, mm_seed: 1, grid: 41 }); } catch (e) { ob.add(ctx.error(e)); return; }
    const P = pal();
    const nf = r.factors.length;
    const avail = Math.max(320, Math.min(1180, (root.innerWidth || 1200) - 150));
    const pw = Math.max(118, Math.min(215, Math.floor((avail - 130) / nf)));
    const ph = r.responses.length > 2 ? 140 : 170;
    const grid = el('div', { class: 'sm-prof sm-prof-marg', style: { gridTemplateColumns: `minmax(92px, max-content) repeat(${nf}, max-content)` } });
    const rows = [];
    r.responses.forEach((resp) => {
      grid.append(el('div', { class: 'sm-prof-y' }, el('span', { class: 'sm-prof-name', text: resp.name })));
      let lo = Infinity, hi = -Infinity;
      for (const t of resp.traces) for (const v of [...t.pd, ...t.ice.flat()]) if (Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      const yr = resp.bounded ? [0, 1] : (lo <= hi ? [lo - 0.06 * (hi - lo || 1), hi + 0.06 * (hi - lo || 1)] : [0, 1]);
      resp.traces.forEach((t, fi) => {
        const f = r.factors[fi];
        const cat = f.type === 'categorical';
        const traces = t.ice.map((line) => ({ type: 'scatter', mode: cat ? 'lines+markers' : 'lines', x: t.x, y: line, line: { color: P.muted, width: 0.7 }, marker: { size: 3, color: P.muted }, opacity: 0.45, hoverinfo: 'skip', showlegend: false }));
        traces.push({ type: 'scatter', mode: cat ? 'lines+markers' : 'lines', x: t.x, y: t.pd, line: { color: P.point, width: 2 }, marker: { size: 6, color: P.point }, hovertemplate: `${SM.report.plotlyText(f.name)} %{x}<br>mean ${SM.report.plotlyText(resp.name)} %{y:.5g}<extra></extra>`, showlegend: false });
        grid.append(ctx.plot(traces, { margin: { l: fi === 0 ? 48 : 6, r: 6, t: 6, b: 24 }, hovermode: 'closest', dragmode: false,
          xaxis: cat ? { type: 'category', tickfont: { size: 9 }, fixedrange: true, showgrid: false } : { range: [f.min, f.max], tickfont: { size: 9 }, fixedrange: true, showgrid: false, nticks: 4 },
          yaxis: { range: yr, showticklabels: fi === 0, tickfont: { size: 9 }, fixedrange: true, nticks: 5 } }, { width: pw + (fi === 0 ? 42 : 0), height: ph, select: false, fit: false, title: `${resp.name} marginal over ${f.name}`, config: { displayModeBar: false } }));
        t.x.forEach((x, i) => rows.push({ response: resp.name, factor: f.name, value: typeof x === 'number' ? x : String(x), mean: t.pd[i] }));
      });
    });
    grid.append(el('div', { class: 'sm-prof-y sm-prof-corner', text: 'Factors' }));
    r.factors.forEach((f, fi) => grid.append(el('div', { class: 'sm-prof-x', style: { width: `${pw + (fi === 0 ? 42 : 0)}px` } }, el('span', { class: 'sm-prof-fname', text: f.name }))));
    const tbl = ctx.rt({ columns: [{ key: 'response', label: 'Response', fmt: 'text' }, { key: 'factor', label: 'Factor', fmt: 'text' }, { key: 'value', label: 'Value', fmt: 'text' }, { key: 'mean', label: 'Mean Prediction' }], rows: rows.map((q) => ({ ...q, value: typeof q.value === 'number' ? fmt(q.value, { sig: 6 }) : q.value })) }, { key: `${key}:marginal`, sortable: false, maxRows: 60 });
    const tbox = ctx.outline('Marginal Model Values', { parent: ob, key: `${key}:marginalvals`, closed: true });
    tbox.add(tbl);
    ob.body.prepend(el('div', { class: 'sm-profwrap' }, grid));
    ob.body.insertBefore(ctx.note(`Each factor's marginal model: the mean prediction of ${r.n} rows the model learned from (drawn from the seed), the factor set to each value of its range or each level and the other factors at the rows' own values (partial dependence)${r.ice ? `; the thin lines are ${r.ice} of those rows each on its own (individual conditional expectation, ICE)` : ''}. Unlike the profiler, the other factors are not held at one setting: where the curves bend differently, the factors interact. JMP averages over its importance draws; here over the rows.`), tbox.el);
  }

  /* Save Shapley Values: permutation SHAP of the rows asked for, a column per factor and response. */
  async function saveShapley(ctx, { fn, payload, key, scope }) {
    const t = ctx.table;
    const sel = t.rowsWith ? t.rowsWith('selected') : [];
    const v = await SM.ui.form({ title: 'Save Shapley Values', info: 'p:profiler:shapley', fields: [
      { key: 'rows', label: 'Rows', type: 'select', value: sel.length ? 'selected' : 'report', choices: [['report', 'The report\'s rows'], ['all', 'Every row of the table'], ...(sel.length ? [['selected', `The ${sel.length} selected rows`]] : [])], help: 'The rows whose predictions are explained: the report\'s (those it used, the excluded ones left out), every row of the table (excluded rows too), or the selected ones.' },
      { key: 'n', label: 'Background rows', type: 'number', value: 50, help: 'How many of the rows the model learned from (drawn from the seed) stand for the factors\' usual values: a factor that is not yet set takes each of these rows\' values in turn, and the prediction is averaged over them. More rows, steadier values and a slower computation.' },
      { key: 'perm', label: 'Permutations', type: 'number', value: 10, help: 'How many random orders of the factors are averaged (each with its reverse), as JMP\'s Permutation SHAP (10 by default). With at least as many as there are orderings of the factors (6 for 3), every ordering is taken once, which gives the exact Shapley values of this background.' },
      { key: 'seed', label: 'Random Seed', type: 'number', value: 1, help: 'The seed of the background rows and the orders drawn: the same seed gives the same values again.' },
    ], validate: (x) => (!(Number.isInteger(x.n) && x.n >= 1) ? 'Background rows: a whole number, 1 or more' : !(Number.isInteger(x.perm) && x.perm >= 1) ? 'Permutations: a whole number, 1 or more' : null) });
    if (!v) return;
    const rows = v.rows === 'all' ? Array.from({ length: t.nrows }, (_, i) => i) : v.rows === 'selected' ? sel : ctx.rows.slice();
    try {
      const r = await ctx.call(fn, { ...payload, sh_rows: rows, sh_n: v.n, sh_perm: v.perm, sh_seed: v.seed == null ? 1 : v.seed });
      for (const resp of r.responses) {
        r.factors.forEach((f, j) => ctx.saveColumn(`Shapley[${f}] ${resp.name}`, { rows: r.rows, values: resp.values[j] }, { notes: `the Shapley value of ${f} in each row's ${resp.name}: its contribution against the mean prediction of ${r.n} background rows (${fmt(resp.base, { sig: 6 })}), by ${r.how} (seed ${v.seed}), from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}` }));
      }
      SM.ui.toast(`Saved the Shapley values of ${r.rows.length} rows: ${r.factors.length * r.responses.length} columns`);
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  /* Assess Variable Importance: Sobol's main and total effects per response. */
  async function importanceReport(ctx, parent, { fn, payload, method, key, scope, impKey }) {
    const ob = ctx.outline(`Variable Importance: ${method === 'resampled' ? 'Independent Resampled Inputs' : 'Independent Uniform Inputs'}`, { parent, key: `${key}:importance`, info: 'p:profiler:importance', menu: () => [{ label: 'Remove', action: () => ctx.set(impKey, null, scope) }] });
    let r;
    try { r = await ctx.call(fn, { ...payload, imp_method: method, imp_n: 1024, imp_seed: 1 }); } catch (e) { ob.add(ctx.error(e)); return; }
    const bar = SM.report.BAR;
    for (const resp of r.responses) {
      const rows = resp.rows.slice().sort((a, b) => b.total - a.total);
      const plot = ctx.plot([
        { type: 'bar', orientation: 'h', y: rows.map((x) => SM.report.plotlyText(x.column)), x: rows.map((x) => x.total), name: 'Total Effect', marker: { color: bar }, hovertemplate: '%{y}: total %{x:.4f}<extra></extra>' },
        { type: 'bar', orientation: 'h', y: rows.map((x) => SM.report.plotlyText(x.column)), x: rows.map((x) => x.main), name: 'Main Effect', marker: { color: SM.report.BASE }, hovertemplate: '%{y}: main %{x:.4f}<extra></extra>' },
      ], { barmode: 'group', showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, margin: { l: 110, r: 12, t: 30, b: 40 }, xaxis: { range: [0, 1.05], title: { text: 'Share of the variance' } }, yaxis: { autorange: 'reversed' } }, { width: 360, height: Math.max(160, 30 * rows.length + 90), title: `${resp.response} variable importance`, select: false });
      ctx.outline(resp.response, { parent: ob, key: `${key}:imp:${resp.response}` }).add(ctx.row(ctx.rt({ columns: [{ key: 'column', label: 'Column', fmt: 'text' }, { key: 'main', label: 'Main Effect' }, { key: 'total', label: 'Total Effect' }], rows }, { key: `imp-${resp.response}` }), plot));
    }
    ob.add(ctx.note(`Sobol indices from ${r.evaluations} predictions (${r.n} draws; scipy.stats.sobol_indices): the main effect is the share of the prediction's variance a factor explains alone, the total effect with its interactions. The factors are drawn independently: ${method === 'resampled' ? 'from the values in the data' : 'uniformly over their ranges, a categorical factor\'s levels equally likely'}.`));
  }

  SM.profiler = Object.freeze({ render });
  SM.info.add({
    'p:profiler': {
      kicker: 'Profilers', title: 'Prediction Profiler',
      lead: 'How the prediction changes with each factor, the other factors held at their current values. Drag a red dashed line, click in a plot, or type a value under it; the prediction at the current values is on the left. A categorical response has a row per level: the probability of that level.',
      sections: [{ choices: [['Desirability Functions', 'a desirability between 0 and 1 for each response and their combination, the Desirability row'], ['Maximize Desirability', 'moves the factors to the setting with the highest desirability'], ['Remember Settings', 'adds the current setting and its predictions to a table; click a row to go back to it'], ['Assess Variable Importance', 'how much of the prediction\'s variation each factor accounts for'], ['Marginal Model Plots', 'each factor\'s mean prediction over the rows the model learned from, the other factors at the rows\' own values (partial dependence); ICE Lines adds rows\' own curves'], ['Save Shapley Values…', 'each row\'s prediction taken apart into a contribution per factor (Permutation SHAP), saved as columns'], ['Reset Factor Settings', 'puts every factor back at its mean (a continuous one) or its first level']] }],
    },
    'p:profiler:desirability': {
      kicker: 'Profilers', title: 'Desirability',
      lead: 'Each response has a goal: Maximize, Minimize or Match Target, set by three points, a value and how desirable it is (0 to 1). The function runs smoothly through them (a monotone cubic) and is flat beyond. The overall desirability is the geometric mean of the responses\' desirabilities, each to the power of its importance: 0 if any is 0. JMP\'s defaults put 0.0183, 0.5 and 0.9817 at the low, middle and high values for Maximize.',
      sections: [{ heading: 'Maximize Desirability', text: 'A quasi-random search over the factors (every level combination of the categorical ones when there are few), the best settings refined by scipy.optimize (Powell\'s method, within the ranges), and the categorical factors\' levels tried again one at a time. A tree or a forest has flat steps: the best step is found, not a single best point.' }],
    },
    'p:profiler:marginal': {
      kicker: 'Profilers', title: 'Marginal Model Plots',
      lead: 'For each factor, each response\'s mean prediction over the rows the model learned from (200 of them at most, drawn from the seed), the factor set to each value of its range or each level and the other factors at each row\'s own values: partial dependence. ICE Lines (red triangle) adds 30 of those rows\' own curves (individual conditional expectation): curves that bend differently show the factor interacting with the others. JMP draws them from its variable importance draws; here from the rows. Like the profiler they are drawn from the model\'s prediction and have no code block; Marginal Model Values holds their numbers.',
    },
    'p:profiler:shapley': {
      kicker: 'Profilers', title: 'Shapley Values',
      lead: 'Each row\'s prediction taken apart into a contribution per factor (Permutation SHAP, as JMP Pro\'s Save Shapley Values): along random orders of the factors, each factor is set to the row\'s value in turn, the factors not yet set at the values of background rows the model learned from, and the factor gets the change of the mean prediction. A row\'s values add up to its prediction less the background\'s mean prediction. With as many permutations as there are orderings of the factors, the values are exact for the background. The columns are Shapley[factor] response, one per factor and response (each level\'s probability of a categorical one).',
    },
    'p:profiler:importance': {
      kicker: 'Profilers', title: 'Assess Variable Importance',
      lead: 'Sobol\'s sensitivity indices of the prediction (scipy.stats.sobol_indices): the main effect of a factor is the share of the prediction\'s variance it accounts for alone, the total effect the share it takes part in, with its interactions. Main effects that add to about 1 mean an additive model.',
      sections: [{ choices: [['Independent Uniform Inputs', 'each factor drawn uniformly over its range, a categorical factor\'s levels equally likely'], ['Independent Resampled Inputs', 'each factor drawn from its values in the data, one factor independently of the others']] }],
    },
  });
}(typeof self !== 'undefined' ? self : this));
