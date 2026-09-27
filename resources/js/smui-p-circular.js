/* ==========================================================================
   SMUI.HTML: ANALYZE > SPECIALIZED MODELING > CIRCULAR STATISTICS

   Angles, directions and times of day: one outline per Y column, with a
   circular dot plot linked to the rows and a rose diagram, the summary (mean
   direction, mean resultant length, circular variance and standard
   deviation, median direction), intervals for the mean direction, the
   Rayleigh and V tests, a fitted von Mises distribution; with an X column
   the circular-linear correlation (continuous X), the circular-circular
   correlation (an X of angles) or the comparison of groups (Watson-Williams,
   uniform scores). JMP has no such platform: the methods are Mardia and
   Jupp's (2000), Fisher's (1993) and Zar's (2010); the numbers are
   resources/py/smui/circular.py's.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt, PALETTE } = SM.util;
  const { isMissing } = SM.table;

  const UNITS = [['degrees', 'Degrees (0 to 360)'], ['radians', 'Radians (0 to 2π)'], ['clock', 'Clock (the period below: 24 hours, 7 days, 12 months)']];
  const ZERO = [['auto', 'Automatic (clockwise from the top; radians counterclockwise from the right)'], ['compass', 'Clockwise from the top (compass, clock)'], ['math', 'Counterclockwise from the right (mathematical)']];
  const RED = '#b0413e';
  const TAU = 2 * Math.PI;

  /* The units of the report: the full circle P in the columns' units. */
  function settings(ctx) {
    const units = ctx.opt('units', 'degrees');
    const per = Number(ctx.opt('period', 24));
    const P = units === 'degrees' ? 360 : units === 'radians' ? TAU : (per > 0 ? per : 24);
    const zero = ctx.opt('zero', 'auto');
    const compass = zero === 'compass' || (zero === 'auto' && units !== 'radians');
    return { units, P, compass, payload: { units, period: units === 'clock' ? P : null } };
  }

  const frac = (v, P) => { const f = (v % P) / P; return f < 0 ? f + 1 : f; };
  /* An angle, a fraction of the circle, as a point at radius r. */
  const xy = (f, r, compass) => (compass ? [r * Math.sin(TAU * f), r * Math.cos(TAU * f)] : [r * Math.cos(TAU * f), r * Math.sin(TAU * f)]);
  const unitText = (S, v) => (v == null ? '.' : S.units === 'degrees' ? `${fmt(v)}°` : S.units === 'radians' ? `${fmt(v)} rad` : fmt(v));

  /* The labels around the circle: [fraction, text]. */
  function ticks(S) {
    if (S.units === 'degrees') return [0, 45, 90, 135, 180, 225, 270, 315].map((d) => [d / 360, `${d}°`]);
    if (S.units === 'radians') return ['0', 'π/4', 'π/2', '3π/4', 'π', '5π/4', '3π/2', '7π/4'].map((t, i) => [i / 8, t]);
    const P = S.P;
    if (Number.isInteger(P) && P <= 12) return Array.from({ length: P }, (_, i) => [i / P, String(i)]);
    if (Number.isInteger(P) && P <= 48) {
      const step = [2, 3, 4, 6, 8, 12].find((s) => P % s === 0 && P / s <= 12) || Math.ceil(P / 8);
      const out = [];
      for (let v = 0; v < P; v += step) out.push([v / P, String(v)]);
      return out;
    }
    return Array.from({ length: 8 }, (_, i) => [i / 8, fmt((i * P) / 8)]);
  }

  /* The angles of a column in the report's rows, with Freq. */
  function anglesOf(ctx, col, S) {
    const f = ctx.role('freq');
    const rows = [], vals = [], wts = [];
    for (const r of ctx.rows) {
      const v = col.values[r];
      if (typeof v !== 'number' || !Number.isFinite(v)) continue;
      const w = f ? f.values[r] : 1;
      if (!(w > 0) || !Number.isFinite(w)) continue;
      rows.push(r); vals.push(v); wts.push(w);
    }
    return { rows, vals, wts };
  }

  function binsOf(ctx, S) {
    const b = Number(ctx.opt('bins', 0));
    if (b >= 4) return Math.round(b);
    return S.units === 'clock' && Number.isInteger(S.P) && S.P >= 4 && S.P <= 36 ? S.P : 24;
  }

  function polarAxes(S) {
    const c = SM.util.themeColors();
    const tk = ticks(S);
    return {
      bgcolor: 'rgba(0,0,0,0)',
      angularaxis: { direction: S.compass ? 'clockwise' : 'counterclockwise', rotation: S.compass ? 90 : 0, tickvals: tk.map((t) => 360 * t[0]), ticktext: tk.map((t) => t[1]), gridcolor: c.grid, linecolor: c.muted, tickcolor: c.muted, color: c.text },
      radialaxis: { gridcolor: c.grid, linecolor: c.grid, tickcolor: c.muted, color: c.muted, angle: S.compass ? 90 : 0, tickangle: S.compass ? 90 : 0, tickfont: { size: 9 } },
    };
  }

  /* ---- the rose diagram: a histogram on the circle (Plotly barpolar) -------- */
  function rose(ctx, col, S, A, sum, vm) {
    const nb = binsOf(ctx, S);
    const area = ctx.opt('roseArea', true, col.id);
    const counts = new Array(nb).fill(0);
    A.vals.forEach((v, k) => { counts[Math.min(nb - 1, Math.floor(frac(v, S.P) * nb))] += A.wts[k]; });
    const w = S.P / nb;
    const rOf = (c) => (area ? Math.sqrt(c) : c);
    const traces = [{
      type: 'barpolar', r: counts.map(rOf), theta: counts.map((_, j) => (360 * (j + 0.5)) / nb), width: counts.map(() => 360 / nb),
      marker: { color: SM.report.BAR, line: { color: SM.util.themeColors().surface, width: 0.8 } },
      hovertext: counts.map((c, j) => `${unitText(S, j * w)} to ${unitText(S, (j + 1) * w)}: ${fmt(c)}`), hovertemplate: '%{hovertext}<extra></extra>', name: 'Rose',
    }];
    const top = Math.max(...counts.map(rOf), 1e-9);
    if (vm && vm.curve) {
      // the fitted density as counts per bin, on the same radius scale
      const n = sum ? sum.n : A.vals.length;
      traces.push({ type: 'scatterpolar', mode: 'lines', r: vm.curve.density.map((d) => rOf(n * d * w)), theta: vm.curve.x.map((x) => (360 * x) / S.P), line: { color: '#3a7d44', width: 1.8 }, hoverinfo: 'skip', name: 'von Mises' });
    }
    if (sum && sum.mean != null) {
      const t = (360 * sum.mean) / S.P;
      traces.push({ type: 'scatterpolar', mode: 'lines+markers', r: [0, sum.rbar * top], theta: [t, t], line: { color: RED, width: 2.2 }, marker: { size: [0, 7], color: RED, symbol: 'circle' },
        hovertemplate: `mean direction ${unitText(S, sum.mean)}, R̄ ${fmt(sum.rbar)}<extra></extra>`, name: 'Mean' });
    }
    return ctx.plot(traces, {
      polar: { ...polarAxes(S), radialaxis: { ...polarAxes(S).radialaxis, range: [0, top * 1.04] } },
      xaxis: { visible: false }, yaxis: { visible: false }, dragmode: false, margin: { l: 34, r: 34, t: 22, b: 22 },
    }, { width: 330, height: 330, title: `${col.name} rose diagram`, select: false });
  }

  /* ---- the circular dot plot: each row a point outside the circle, stacked
     in bins, with the mean vector; linked to the rows ------------------------- */
  function dotPlot(ctx, col, S, A, sum, grp) {
    const c = SM.util.themeColors();
    const nd = 72;
    const n = A.vals.length;
    const stack = new Array(nd).fill(0);
    const idx = A.vals.map((v) => Math.min(nd - 1, Math.floor(frac(v, S.P) * nd)));
    for (const k of idx) stack[k]++;
    const most = Math.max(1, ...stack);
    const step = Math.min(0.065, 0.55 / most);
    const seen = new Array(nd).fill(0);
    const pos = A.vals.map((v, k) => { const s = seen[idx[k]]++; return xy(frac(v, S.P), 1.07 + s * step, S.compass); });
    const reach = 1.07 + (most - 1) * step + 0.08;
    const traces = [];
    const circle = Array.from({ length: 181 }, (_, i) => xy(i / 180, 1, S.compass));
    traces.push({ type: 'scatter', mode: 'lines', x: circle.map((p) => p[0]), y: circle.map((p) => p[1]), line: { color: c.muted, width: 1 }, hoverinfo: 'skip', showlegend: false });
    // the tick marks just inside the circle
    const tk = ticks(S);
    const tx = [], ty = [];
    for (const [f] of tk) { const a = xy(f, 0.94, S.compass), b = xy(f, 1, S.compass); tx.push(a[0], b[0], null); ty.push(a[1], b[1], null); }
    traces.push({ type: 'scatter', mode: 'lines', x: tx, y: ty, line: { color: c.muted, width: 1 }, hoverinfo: 'skip', showlegend: false });
    const type = n > 4000 ? 'scattergl' : 'scatter';
    const size = n > 3000 ? 3 : n > 600 ? 4 : 6;
    const hover = (k) => `row ${A.rows[k] + 1}: ${unitText(S, A.vals[k])}`;
    if (grp) {
      grp.levels.forEach((lv, g) => {
        const ks = A.rows.map((_, k) => k).filter((k) => grp.code[k] === g);
        traces.push({ type, mode: 'markers', x: ks.map((k) => pos[k][0]), y: ks.map((k) => pos[k][1]), rows: ks.map((k) => A.rows[k]), marker: { size, color: PALETTE[g % PALETTE.length] },
          hovertext: ks.map(hover), hovertemplate: '%{hovertext}<extra></extra>', name: SM.report.plotlyText(lv), showlegend: true });
      });
    } else {
      traces.push({ type, mode: 'markers', x: pos.map((p) => p[0]), y: pos.map((p) => p[1]), rows: A.rows, marker: { size }, hovertext: A.rows.map((_, k) => hover(k)), hovertemplate: '%{hovertext}<extra></extra>', name: SM.report.plotlyText(col.name), showlegend: false });
    }
    const annotations = tk.map(([f, t]) => { const p = xy(f, 0.8, S.compass); return { x: p[0], y: p[1], text: SM.report.plotlyText(t), showarrow: false, font: { size: 10, color: c.muted }, xref: 'x', yref: 'y' }; });
    const arrow = (m, R, color) => { const p = xy(frac(m, S.P), R, S.compass); return { x: p[0], y: p[1], ax: 0, ay: 0, xref: 'x', yref: 'y', axref: 'x', ayref: 'y', showarrow: true, arrowhead: 2, arrowsize: 1, arrowwidth: 2, arrowcolor: color, text: '' }; };
    if (grp) grp.means.forEach((g, i) => { if (g.mean != null) annotations.push(arrow(g.mean, g.rbar, PALETTE[i % PALETTE.length])); });
    else if (sum && sum.mean != null) annotations.push(arrow(sum.mean, sum.rbar, RED));
    // the von Mises interval of the mean direction, as an arc just inside the circle
    const ci = sum && sum.ci && sum.ci.rows[0];
    if (!grp && ci && ci.lower != null) {
      const f0 = frac(ci.lower, S.P);
      let f1 = frac(ci.upper, S.P);
      if (f1 < f0) f1 += 1;
      const arc = Array.from({ length: 41 }, (_, i) => xy(f0 + ((f1 - f0) * i) / 40, 0.97, S.compass));
      traces.push({ type: 'scatter', mode: 'lines', x: arc.map((p) => p[0]), y: arc.map((p) => p[1]), line: { color: RED, width: 3 }, hovertemplate: `${fmt(100 * (1 - (sum.alpha || 0.05)))}% interval of the mean direction (von Mises): ${unitText(S, ci.lower)} to ${unitText(S, ci.upper)}<extra></extra>`, showlegend: false });
    }
    const L = Math.max(1.25, reach);
    return ctx.plot(traces, {
      xaxis: { visible: false, range: [-L, L], fixedrange: true }, yaxis: { visible: false, range: [-L, L], scaleanchor: 'x', fixedrange: true },
      annotations, showlegend: !!grp, legend: { orientation: 'h', x: 0, y: -0.02, yanchor: 'top' }, margin: { l: 8, r: 8, t: 8, b: grp ? 34 : 8 },
    }, { width: 340, height: grp ? 364 : 340, title: `${col.name} circular dot plot` });
  }

  /* ---- one column ------------------------------------------------------------- */
  async function column(ctx, col, parent, S) {
    const sc = col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const outline = ctx.outline(col.name, { parent, key: `col:${col.id}`, menu: () => colMenu(ctx, col, S), info: 'p:circular' });
    const A = anglesOf(ctx, col, S);
    const freq = ctx.name('freq');
    const base = { column: col.name, ...S.payload, freq, alpha: ctx.alpha, where: ctx.where || [] };
    const vdir = o('vdir', null);
    const sum = await ctx.call('circular.summary', { ...base, v_dir: vdir });
    if (sum.error) { outline.add(ctx.warn(`${col.name}: ${sum.error}`)); return; }
    const vm = o('vm', false) ? await ctx.call('circular.vonmises', base) : null;
    const x = ctx.role('x');
    const xAngle = !!x && !x.isCategorical && ctx.opt('xAngle', false);
    let grp = null, gres = null;
    if (x && x.isCategorical && x.id !== col.id) {
      gres = await ctx.call('circular.groups', { ...base, column: undefined, y: col.name, x: x.name });
      if (!gres.error) {
        const lvKey = new Map(gres.levels.map((v, i) => [typeof v === 'number' ? v : String(v), i]));
        const code = A.rows.map((r) => { const v = x.values[r]; return isMissing(v) ? -1 : (lvKey.get(typeof v === 'number' ? v : String(v)) ?? -1); });
        grp = { levels: gres.levels.map((v) => SM.grid.cellText(x, v)), code, means: gres.groups };
      }
    }
    // ---- the graphs
    const graphs = [];
    if (o('dot', true)) graphs.push(dotPlot(ctx, col, S, A, sum, grp));
    if (o('rose', true)) graphs.push(rose(ctx, col, S, A, sum, vm && !vm.error ? vm : null));
    if (graphs.length) outline.add(ctx.row(...graphs));
    if (o('rose', true)) outline.add(ctx.note(`Rose diagram: ${binsOf(ctx, S)} bins; ${ctx.opt('roseArea', true, sc) ? 'the radius is the square root of the count, so that the area shows it (Fisher 1993)' : 'the radius is the count'}${vm && !vm.error ? '; the green curve is the fitted von Mises, as counts per bin' : ''}. The red line is the mean direction, its length R̄ times the longest bar.`));
    // ---- the summary
    if (o('summary', true)) {
      const ob = ctx.outline('Summary Statistics', { parent: outline, key: `summary:${sc}`, info: 'p:circular:summary' });
      ob.add(ctx.kv([
        ['N', sum.n], ['Mean Direction', sum.mean], ['Mean Resultant Length (R̄)', sum.rbar], ['Circular Variance (1 − R̄)', sum.circ_var],
        ['Circular Std Dev', sum.circ_sd], ['Angular Deviation', sum.ang_dev], ['Circular Dispersion', sum.dispersion], ['Median Direction', sum.median],
        ['Skewness', sum.skewness], ['Kurtosis', sum.kurtosis],
      ]), ctx.note(`In ${S.units === 'clock' ? `the units of a clock of period ${fmt(S.P)}` : S.units}. Circular Std Dev √(−2 ln R̄) and Angular Deviation √(2(1 − R̄)) are in these units too; R̄, the circular variance and dispersion have none.${sum.median_ties > 1 ? ` ${sum.median_ties} directions share the least mean distance: the median shown is the one nearest the mean direction.` : ''}`), ctx.code(sum.code));
    }
    if (o('ci', true)) {
      const ob = ctx.outline('Confidence Intervals for the Mean Direction', { parent: outline, key: `ci:${sc}`, info: 'p:circular:summary' });
      ob.add(ctx.rt(sum.ci, { sortable: false }), ctx.note('From the lower limit to the upper in the direction the angles grow; a lower limit above the upper crosses zero. Upton\'s (1986) interval assumes a von Mises distribution; Fisher\'s (1993) holds for any unimodal one when n is large (25 or more).'));
    }
    if (o('uniformity', true)) {
      const ob = ctx.outline('Tests of Uniformity', { parent: outline, key: `unif:${sc}`, info: 'p:circular:tests', menu: () => [{ label: 'V Test…', checked: vdir != null, action: () => vDialog(ctx, col, S) }] });
      const rows = [{ test: 'Rayleigh, Z = nR̄²', stat: sum.rayleigh.Z, u: null, p: sum.rayleigh.p }];
      if (sum.vtest) rows.push({ test: `V test, mean direction ${unitText(S, sum.vtest.dir)}`, stat: sum.vtest.V, u: sum.vtest.u, p: sum.vtest.p });
      ob.add(ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'stat', label: 'Statistic' }, { key: 'u', label: 'u = V√(2/n)', hidden: true }, { key: 'p', label: 'p-Value', fmt: 'p' }], rows }, { sortable: false }),
        ctx.note(`Rayleigh: against a uniform distribution, for one mode (Zar's approximation of the p-value). ${sum.vtest ? 'V: against uniform, for a mode at the given direction, V = nR̄ cos(mean − direction), u = V√(2/n) one-sided against the normal (Durand and Greenwood 1958). ' : 'V Test… (this outline\'s red triangle) tests for a mode at a direction you give. '}A small p-value is evidence that the directions are not uniform.${sum.vtest ? ' Right click for u.' : ''}`));
    }
    if (vm) vonMisesReport(ctx, col, outline, S, vm);
    // ---- with X
    if (x && x.id !== col.id) {
      if (x.isCategorical) groupsReport(ctx, col, x, outline, S, gres);
      else if (xAngle) await circCorrReport(ctx, col, x, outline, S, base);
      else await linearReport(ctx, col, x, outline, S, base);
    }
  }

  function vonMisesReport(ctx, col, parent, S, vm) {
    const ob = ctx.outline('Fitted von Mises Distribution', { parent, key: `vm:${col.id}`, info: 'p:circular:vonmises', menu: () => [{ label: 'Remove Fit', action: () => ctx.set('vm', false, col.id) }] });
    if (vm.error) { ob.add(ctx.warn(vm.error)); return; }
    ob.add(ctx.rt(vm.estimates, { sortable: false }), ctx.kv([['−2 log(Likelihood)', -2 * vm.loglik], ['κ, small-sample (Best and Fisher 1981)', vm.kappa_small], ['N', vm.n]]),
      ctx.note('f(θ) = exp(κ cos(θ − μ))/(2π I₀(κ)): μ̂ is the mean direction, κ̂ solves I₁(κ)/I₀(κ) = R̄ (maximum likelihood; scipy.stats.vonmises.fit gives the same). The standard errors are from the information; μ\'s interval is normal, κ\'s the likelihood-ratio interval. The fitted density is drawn on the rose diagram.'),
      ...(vm.notes || []).map((t) => ctx.note(t)), ctx.code(vm.code));
  }

  async function linearReport(ctx, col, x, parent, S, base) {
    const ob = ctx.outline('Circular-Linear Correlation', { parent, key: `cl:${col.id}`, info: 'p:circular:x' });
    const r = await ctx.call('circular.linear', { ...base, column: undefined, y: col.name, x: x.name });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const P = [];
    const f = ctx.role('freq');
    for (const row of ctx.rows) {
      const a = col.values[row], b = x.values[row];
      if (!Number.isFinite(a) || !Number.isFinite(b) || (f && !(f.values[row] > 0))) continue;
      P.push([row, b, ((a % S.P) + S.P) % S.P]);
    }
    const tk = ticks(S);
    ob.add(ctx.row(
      ctx.plot([{ type: P.length > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: P.map((p) => p[1]), y: P.map((p) => p[2]), rows: P.map((p) => p[0]), marker: { size: 6 } }],
        { xaxis: { title: { text: SM.report.plotlyText(x.name) } }, yaxis: { title: { text: SM.report.plotlyText(col.name) }, range: [0, S.P], tickvals: tk.map((t) => t[0] * S.P), ticktext: tk.map((t) => t[1]) }, margin: { l: 56, r: 10, t: 8, b: 42 } },
        { width: 380, height: 300, title: `${col.name} by ${x.name}` }),
      ctx.kv([['Correlation R', r.r], ['R²', r.r2], ['n R² (χ², 2 DF)', r.chisq], ['Prob > ChiSq', r.p, 'p'], ['N', r.n], [`r(${x.name}, cos)`, r.r_xc], [`r(${x.name}, sin)`, r.r_xs], ['r(cos, sin)', r.r_cs]])),
    ctx.note(`How well ${x.name} predicts the direction through cos θ and sin θ (Mardia 1976; Mardia and Jupp 2000): R² = (r²ₓc + r²ₓs − 2rₓc rₓs rcs)/(1 − r²cs), from 0 to 1; nR² is about χ² with 2 DF when they are independent. Set X Is an Angle (the report's red triangle) when ${x.name} is itself an angle.`), ctx.code(r.code));
  }

  async function circCorrReport(ctx, col, x, parent, S, base) {
    const ob = ctx.outline('Circular-Circular Correlation', { parent, key: `cc:${col.id}`, info: 'p:circular:x' });
    const r = await ctx.call('circular.circular', { ...base, column: undefined, y: col.name, x: x.name });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const P = [];
    const f = ctx.role('freq');
    for (const row of ctx.rows) {
      const a = col.values[row], b = x.values[row];
      if (!Number.isFinite(a) || !Number.isFinite(b) || (f && !(f.values[row] > 0))) continue;
      P.push([row, ((b % S.P) + S.P) % S.P, ((a % S.P) + S.P) % S.P]);
    }
    const tk = ticks(S);
    const axis = (name) => ({ title: { text: SM.report.plotlyText(name) }, range: [0, S.P], tickvals: tk.map((t) => t[0] * S.P), ticktext: tk.map((t) => t[1]) });
    ob.add(ctx.row(
      ctx.plot([{ type: P.length > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: P.map((p) => p[1]), y: P.map((p) => p[2]), rows: P.map((p) => p[0]), marker: { size: 6 } }],
        { xaxis: axis(x.name), yaxis: axis(col.name), margin: { l: 56, r: 10, t: 8, b: 42 } }, { width: 340, height: 320, title: `${col.name} by ${x.name}` }),
      ctx.kv([['Circular Correlation r', r.r], ['Z', r.z], ['Prob > |Z|', r.p, 'p'], ['N', r.n]])),
    ctx.note('Jammalamadaka and SenGupta\'s (2001) coefficient: Σ sin(α − ᾱ) sin(β − β̄)/√(Σ sin²(α − ᾱ) Σ sin²(β − β̄)), from −1 to 1, with its large-sample normal test. The plot is on a torus: its edges wrap around.'), ctx.code(r.code));
  }

  function groupsReport(ctx, col, x, parent, S, g) {
    const ob = ctx.outline(`Comparison of ${x.name} Groups`, { parent, key: `groups:${col.id}`, info: 'p:circular:x' });
    if (!g || g.error) { ob.add(ctx.warn(g ? g.error : 'no groups')); return; }
    ob.add(ctx.rt({ columns: [{ key: 'lv', label: x.name, fmt: 'text' }, { key: 'n', label: 'N', fmt: 'int' }, { key: 'mean', label: 'Mean Direction' }, { key: 'rbar', label: 'R̄' }, { key: 'circ_sd', label: 'Circular Std Dev' }],
      rows: g.groups.map((r) => ({ ...r, lv: SM.grid.cellText(x, r.level) })) }, { sortable: false }));
    const tests = [];
    if (g.ww) tests.push({ test: 'Watson-Williams (mean directions)', stat: g.ww.F, dfn: g.ww.df_num, dfd: g.ww.df_den, p: g.ww.p });
    tests.push({ test: 'Uniform scores (distributions)', stat: g.uscores.W, dfn: g.uscores.df, dfd: null, p: g.uscores.p });
    ob.add(ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'stat', label: 'F or χ²' }, { key: 'dfn', label: 'DFNum', fmt: 'int' }, { key: 'dfd', label: 'DFDen', fmt: 'int' }, { key: 'p', label: 'p-Value', fmt: 'p' }], rows: tests }, { sortable: false }),
      g.ww ? ctx.kv([['κ̂ within the groups', g.ww.kappa], ['Correction 1 + 3/(8κ̂)', g.ww.correction], ['R̄ within the groups', g.ww.rbar_within]]) : null,
      ctx.note('Watson-Williams: whether the groups share one mean direction, for von Mises groups of one concentration κ; F = (1 + 3/(8κ̂))·((ΣRⱼ − R)/(q − 1))/((n − ΣRⱼ)/(n − q)) (Mardia and Jupp 2000). The uniform-scores test (Mardia-Watson-Wheeler) replaces the angles by their ranks around the circle and asks whether the groups\' distributions are the same, without the von Mises assumption.'),
      ...(g.notes || []).map((t) => ctx.note(t)), ctx.code(g.code));
  }

  async function vDialog(ctx, col, S) {
    const cur = ctx.opt('vdir', null, col.id);
    const v = await SM.ui.form({
      title: `V Test: ${col.name}`, info: 'p:circular:tests',
      lead: `Test against uniformity for a mode at a direction you expect (Durand and Greenwood 1958), in the report's units (${S.units === 'clock' ? `a clock of period ${fmt(S.P)}` : S.units}).`,
      fields: [{ key: 'dir', label: 'Expected mean direction', type: 'number', value: cur ?? 0 }],
      validate: (x) => (x.dir != null && Number.isFinite(x.dir) ? null : 'Give a direction.'),
    });
    if (v) ctx.set('vdir', v.dir, col.id);
  }

  /* Save: the angles in radians or degrees, or their signed deviation from
     the mean direction (in the column's units, −P/2 to P/2). */
  async function save(ctx, col, S, kind) {
    const A = anglesOf(ctx, col, S);
    let values;
    if (kind === 'rad') values = A.vals.map((v) => TAU * frac(v, S.P));
    else if (kind === 'deg') values = A.vals.map((v) => 360 * frac(v, S.P));
    else {
      const sum = await ctx.call('circular.summary', { column: col.name, ...S.payload, freq: ctx.name('freq'), alpha: ctx.alpha, where: ctx.where || [] });
      if (sum.error || sum.mean == null) { SM.ui.toast(sum.error || 'the mean direction is not defined', { error: true }); return; }
      values = A.vals.map((v) => { let d = frac(v - sum.mean, S.P); if (d >= 0.5) d -= 1; return d * S.P; });
    }
    const name = { rad: `Radians[${col.name}]`, deg: `Degrees[${col.name}]`, dev: `Deviation[${col.name}]` }[kind];
    ctx.saveColumn(name, { rows: A.rows, values }, { notes: `${col.name} ${kind === 'dev' ? 'minus its mean direction' : kind === 'rad' ? 'in radians, 0 to 2π' : 'in degrees, 0 to 360'}, saved from ${ctx.report.title}` });
  }

  function colMenu(ctx, col, S) {
    const sc = col.id;
    return [
      ctx.check('Circular Dot Plot', 'dot', sc, true),
      ctx.check('Rose Diagram', 'rose', sc, true),
      ctx.check('Rose Area Proportional to Count', 'roseArea', sc, true),
      { separator: true },
      ctx.check('Summary Statistics', 'summary', sc, true),
      ctx.check('Confidence Intervals', 'ci', sc, true),
      ctx.check('Tests of Uniformity', 'uniformity', sc, true),
      { label: 'V Test…', checked: ctx.opt('vdir', null, sc) != null, action: () => vDialog(ctx, col, S) },
      ctx.check('Fit von Mises', 'vm', sc, false),
      { separator: true },
      { label: 'Save', submenu: () => [{ label: 'Radians', action: () => save(ctx, col, S, 'rad') }, { label: 'Degrees', action: () => save(ctx, col, S, 'deg') }, { label: 'Deviation from the Mean Direction', action: () => save(ctx, col, S, 'dev') }] },
    ];
  }

  /* ---- several angle columns: their circular correlations --------------------- */
  async function correlations(ctx, cols, S) {
    const ob = ctx.outline('Circular-Circular Correlations', { key: 'ycorr', info: 'p:circular:x', menu: () => [{ label: 'Remove', action: () => ctx.set('ycorr', false) }] });
    const rows = [];
    let code = null;
    for (let i = 0; i < cols.length; i++) {
      for (let j = i + 1; j < cols.length; j++) {
        const r = await ctx.call('circular.circular', { y: cols[i].name, x: cols[j].name, ...S.payload, freq: ctx.name('freq'), alpha: ctx.alpha, where: ctx.where || [] });
        if (r.error) rows.push({ a: cols[i].name, b: cols[j].name, n: null, r: null, z: null, p: null });
        else { rows.push({ a: cols[i].name, b: cols[j].name, n: r.n, r: r.r, z: r.z, p: r.p }); code = code || r.code; }
      }
    }
    ob.add(ctx.rt({ columns: [{ key: 'a', label: 'Angle', fmt: 'text' }, { key: 'b', label: 'by Angle', fmt: 'text' }, { key: 'n', label: 'N', fmt: 'int' }, { key: 'r', label: 'Circular Correlation' }, { key: 'z', label: 'Z' }, { key: 'p', label: 'Prob > |Z|', fmt: 'p' }], rows }),
      ctx.note('Each pair on its rows with both angles: Jammalamadaka and SenGupta\'s (2001) coefficient and its large-sample test. The code is the first pair\'s; the others are the same.'), ctx.code(code));
  }

  /* ---- the example: simulated wind, never a real record ---------------------- */
  /* A von Mises draw by Best and Fisher's (1979) algorithm, as Fisher (1993)
     gives it. */
  function vonMises(r, mu, kappa) {
    if (kappa < 1e-8) return TAU * r.u();
    const a = 1 + Math.sqrt(1 + 4 * kappa * kappa);
    const b = (a - Math.sqrt(2 * a)) / (2 * kappa);
    const rr = (1 + b * b) / (2 * b);
    for (;;) {
      const u1 = r.u(), u2 = r.u(), u3 = r.u();
      const z = Math.cos(Math.PI * u1);
      const f = (1 + rr * z) / (rr + z);
      const c = kappa * (rr - f);
      if (c * (2 - c) - u2 > 0 || Math.log(c / u2) + 1 - c >= 0) {
        const t = mu + (u3 > 0.5 ? 1 : -1) * Math.acos(f);
        return ((t % TAU) + TAU) % TAU;
      }
    }
  }

  SM.io.addExample('wind', {
    label: 'Wind (240 rows): direction, speed, season, hour of the peak gust',
    about: 'Simulated daily wind at a coastal site, 120 winter and 120 summer days, for Circular Statistics (Analyze > Specialized Modeling). The truth: the direction is von Mises, in winter around 220° with κ = 2.5 and in summer around 280° with κ = 1.5; the speed is 4 + 2.5·cos(direction − 250°) plus normal noise with SD 1 m/s (at least 0.2), so the wind is strongest from about 250°; the direction at a second station is the first plus a von Mises error around 15° with κ = 4; the hour of the day\'s peak gust is von Mises around 15:00 with κ = 1.2 on a 24-hour clock, the same in both seasons and unrelated to the direction.',
    make() {
      const r = SM.util.rng('smui-wind');
      const deg = (t) => (t * 180) / Math.PI;
      const rad = (d) => (d * Math.PI) / 180;
      const c = { day: [], season: [], dir: [], speed: [], dir2: [], hour: [] };
      for (let i = 0; i < 240; i++) {
        const winter = i < 120;
        const th = vonMises(r, rad(winter ? 220 : 280), winter ? 2.5 : 1.5);
        const sp = Math.max(0.2, 4 + 2.5 * Math.cos(th - rad(250)) + r.normal(0, 1));
        const th2 = (th + vonMises(r, rad(15), 4)) % TAU;
        const h = (vonMises(r, TAU * (15 / 24), 1.2) * 24) / TAU;
        c.day.push(i + 1); c.season.push(winter ? 'winter' : 'summer');
        c.dir.push(Math.round(deg(th) * 10) / 10 % 360); c.speed.push(Math.round(sp * 10) / 10);
        c.dir2.push(Math.round(deg(th2) * 10) / 10 % 360); c.hour.push(Math.round(h * 100) / 100 % 24);
      }
      return new SM.Table({ name: 'Wind', source: 'simulated', columns: [
        { name: 'day', dataType: 'numeric', values: c.day },
        { name: 'season', dataType: 'character', values: c.season, valueOrder: ['winter', 'summer'] },
        { name: 'direction (°)', dataType: 'numeric', values: c.dir },
        { name: 'speed (m/s)', dataType: 'numeric', values: c.speed },
        { name: 'direction B (°)', dataType: 'numeric', values: c.dir2 },
        { name: 'hour of peak gust', dataType: 'numeric', values: c.hour },
      ] });
    },
  });

  /* ---- the platform ------------------------------------------------------------ */
  const MORE = { label: 'Circular Statistics', id: 'help-p-circular' };
  const TOPICS = {
    'p:circular': {
      kicker: 'Specialized Modeling', title: 'Circular Statistics',
      lead: 'For angles and times on a clock, where 359° is next to 1° and 23:30 next to 00:30: wind and current directions, compass bearings, times of day, days of the week, months. The ordinary mean and standard deviation mislead there; these statistics treat each value as a point on a circle. Not in JMP.',
      sections: [
        { heading: 'Roles', choices: [['Y, Angle', 'One or more columns of angles, in the units of the launch dialog: degrees, radians, or a clock of a given period (24 for hours).'], ['X', 'Optional. Continuous: the circular-linear correlation, or with X Is an Angle the circular-circular correlation; nominal or ordinal: a comparison of the groups.'], ['Freq', 'A count per row.'], ['By', 'A separate analysis for each level.']] },
        { heading: 'The graphs', text: 'The circular dot plot stacks each row\'s point outside the unit circle, with the mean vector (its length R̄) and the von Mises interval of the mean direction as an arc; click or drag to select rows. The rose diagram is a histogram around the circle; with Rose Area Proportional to Count (the default, as Fisher 1993 advises) the radius is the square root of the count, so the area shows it.' },
        { heading: 'Orientation', text: 'Zero at the top and clockwise, as a compass and a clock, for degrees and clocks; counterclockwise from the right, as in mathematics, for radians. The report\'s red triangle changes it, and the units.' },
      ],
      more: MORE,
    },
    'p:circular:summary': {
      kicker: 'Circular Statistics', title: 'The summary',
      lead: 'Each angle θ as the point (cos θ, sin θ): their mean is the mean resultant vector, whose direction is the mean direction and whose length R̄ (0 to 1) is the concentration.',
      sections: [
        { choices: [['Mean Direction', 'atan2(mean sin θ, mean cos θ); undefined when R̄ = 0'], ['R̄', 'the mean resultant length: 1 when every angle is the same, near 0 for angles spread evenly or in opposite clusters'], ['Circular Variance', '1 − R̄ (Mardia and Jupp 2000; scipy.stats.circvar)'], ['Circular Std Dev', '√(−2 ln R̄), in the column\'s units (scipy.stats.circstd); about the standard deviation for concentrated data'], ['Angular Deviation', '√(2(1 − R̄)) (Zar 2010)'], ['Circular Dispersion', '(1 − ρ̂₂)/(2R̄²), ρ̂₂ the mean of cos 2(θ − mean) (Fisher 1993): it sets the interval of the mean direction'], ['Median Direction', 'the point with the least mean circular distance to the data, half of them on each side (Fisher 1993)'], ['Skewness, Kurtosis', 'Fisher\'s (1993) circular skewness and kurtosis, from the second trigonometric moment']] },
        { heading: 'Intervals for the mean direction', text: 'von Mises: Upton\'s (1986) approximation, as Zar (2010) gives it, from χ²₁; it needs R̄ above √(χ²₁/2n), else the data do not fix a direction. Any unimodal distribution: mean ± arcsin(z·σ̂), σ̂² = dispersion/n (Fisher 1993), for n of 25 or more.' },
      ],
      more: MORE,
    },
    'p:circular:tests': {
      kicker: 'Circular Statistics', title: 'Tests of uniformity',
      lead: 'Whether the directions have a preferred direction at all.',
      sections: [
        { choices: [['Rayleigh', 'Z = nR̄² against a uniform distribution, most powerful for one mode (von Mises); the p-value is Zar\'s (2010) approximation exp(√(1 + 4n + 4(n² − R²)) − (1 + 2n)), R = nR̄'], ['V test', 'the same for a mode at a direction given in advance (Durand and Greenwood 1958): V = nR̄ cos(mean − direction), u = V√(2/n) against the normal, one-sided']] },
        { heading: 'Two modes', text: 'Both tests look for one mode: angles clustered at opposite directions have a small R̄ and look uniform to them.' },
      ],
      more: MORE,
    },
    'p:circular:vonmises': {
      kicker: 'Circular Statistics', title: 'The von Mises distribution',
      lead: 'The circle\'s normal distribution: f(θ) = exp(κ cos(θ − μ))/(2π I₀(κ)), μ the mean direction, κ ≥ 0 the concentration (0 is uniform; κ above 2 is close to a normal with variance 1/κ).',
      sections: [
        { heading: 'The fit', text: 'Maximum likelihood (Mardia and Jupp 2000): μ̂ is the mean direction and κ̂ solves A₁(κ) = I₁(κ)/I₀(κ) = R̄, the same as scipy.stats.vonmises.fit. The standard errors are 1/√(nκA₁(κ)) for μ and 1/√(n(1 − A₁/κ − A₁²)) for κ; κ\'s interval is the likelihood-ratio one. For small samples κ̂ is too large; Best and Fisher\'s (1981) corrected value is shown beside it.' },
      ],
      more: MORE,
    },
    'p:circular:x': {
      kicker: 'Circular Statistics', title: 'An angle and an X',
      lead: 'With an X column the report relates the angle to it.',
      sections: [
        { choices: [['Circular-linear', 'a continuous X: R² from the correlations of X with cos θ and sin θ (Mardia 1976), nR² about χ² with 2 DF under independence'], ['Circular-circular', 'an X of angles (X Is an Angle) or several Y columns (Circular Correlations): Jammalamadaka and SenGupta\'s (2001) coefficient with its large-sample normal test'], ['Groups', 'a nominal or ordinal X: each group\'s mean direction and R̄; the Watson-Williams F test of one mean direction for von Mises groups of one κ (Mardia and Jupp 2000), which needs κ̂ of at least 1 or 2; and the uniform-scores test (Mardia-Watson-Wheeler) of the same distribution in every group, which does not']] },
      ],
      more: MORE,
    },
  };

  SM.platforms.register({
    id: 'circular', label: 'Circular Statistics', menu: 'Analyze/Specialized Modeling', order: 100, info: 'p:circular', topics: TOPICS,
    about: 'Angles, directions and times of day (not in JMP): a circular dot plot linked to the rows and a rose diagram; the mean direction, mean resultant length, circular variance and standard deviation, median direction; intervals for the mean direction (von Mises and large-sample); the Rayleigh and V tests; a fitted von Mises distribution; with an X column the circular-linear correlation, the circular-circular correlation or a comparison of groups (Watson-Williams, uniform scores). Degrees, radians or a clock of any period. After Mardia and Jupp (2000), Fisher (1993) and Zar (2010).',
    uses: ['scipy.stats (circmean, circvar, circstd, vonmises, chi2, f, norm, rankdata)', 'scipy.special.i0e, i1e (the von Mises κ)', 'scipy.optimize.brentq'],
    launch: {
      lead: 'Cast one or more columns of angles into Y and choose their units. An X column relates them to a covariate, another angle or groups.',
      roles: [
        { key: 'y', label: 'Y, Angle', min: 1, numeric: true, types: ['continuous'], hint: 'required: one or more', info: 'p:circular' },
        { key: 'x', label: 'X', max: 1, hint: 'optional', info: 'p:circular:x' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric' },
        { key: 'by', label: 'By', hint: 'optional' },
      ],
      options: [
        { key: 'units', label: 'Units', type: 'select', value: 'degrees', choices: UNITS },
        { key: 'period', label: 'Period of a clock', type: 'number', value: 24, hint: 'the full circle in the clock\'s units: 24 hours, 7 days, 12 months' },
        { key: 'zero', label: 'Zero and direction', type: 'select', value: 'auto', choices: ZERO },
        { key: 'xAngle', label: 'X is an angle too', type: 'check', value: false },
      ],
      validate(spec, table) {
        const o = spec.options || {};
        if (o.units === 'clock' && !(Number(o.period) > 0)) return 'The period of a clock must be positive.';
        const ys = (spec.roles.y || []);
        if ((spec.roles.x || []).some((id) => ys.includes(id))) return 'X must be another column than the angles.';
        return null;
      },
    },
    title: () => 'Circular Statistics',
    triangle(ctx) {
      const S = settings(ctx);
      const x = ctx.role('x');
      const ys = ctx.roles('y');
      const bins = binsOf(ctx, S);
      return [
        { label: 'Units', submenu: () => [...UNITS.slice(0, 2).map(([k, l]) => ({ label: l, checked: S.units === k, action: () => ctx.set('units', k) })),
          { label: 'Clock…', checked: S.units === 'clock', action: async () => { const v = await SM.ui.form({ title: 'Units: a clock', fields: [{ key: 'p', label: 'Period (the full circle: 24 hours, 7 days, 12 months)', type: 'number', value: S.units === 'clock' ? S.P : 24 }], validate: (f) => (f.p > 0 ? null : 'The period must be positive.') }); if (v) { ctx.set('period', v.p, null, { rerun: false }); ctx.set('units', 'clock'); } } }] },
        { label: 'Zero and Direction', submenu: () => ZERO.map(([k, l]) => ({ label: l, checked: ctx.opt('zero', 'auto') === k, action: () => ctx.set('zero', k) })) },
        { label: 'Rose Bins', submenu: () => [8, 12, 16, 18, 24, 36, 72].map((b) => ({ label: String(b), checked: bins === b, action: () => ctx.set('bins', b) })) },
        x && !x.isCategorical ? ctx.check('X Is an Angle', 'xAngle', null, false) : null,
        ys.length > 1 ? ctx.check('Circular Correlations', 'ycorr', null, false) : null,
        { label: 'Fit von Mises for All', action: () => { for (const c of ys) ctx.set('vm', true, c.id, { rerun: false }); ctx.report.run(); } },
      ].filter(Boolean);
    },
    async render(ctx) {
      const S = settings(ctx);
      const cols = ctx.roles('y');
      const wrap = el('div', { class: 'sm-circ-wrap' });
      ctx.container.append(wrap);
      for (const c of cols) {
        try { await column(ctx, c, wrap, S); } catch (e) { console.error(e); wrap.append(ctx.error(e)); }
      }
      if (cols.length > 1 && ctx.opt('ycorr', false)) await correlations(ctx, cols, S);
    },
  });
}(typeof self !== 'undefined' ? self : this));
