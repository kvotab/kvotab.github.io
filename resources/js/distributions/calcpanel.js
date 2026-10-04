/* ==========================================================================
   distributions.html: THE CALCULATE TAB

   Five cards, each a small form and a table over the distributions (or a
   pair of them): probabilities at x and between a and b, percentiles and
   intervals, tail expectations, a comparison of two, and a Monte Carlo
   expression that becomes a distribution of its own. The numbers come from
   calcmath.js; this file reads the forms and writes the tables. Samples
   have a tab of their own (samplepanel.js).
   ========================================================================== */

import { probabilities, centralInterval, shortestInterval, tailStats, compare } from './calcmath.js';
import { fmt, parseNum, parseNumberList } from './format.js';
import { parseExpression } from './expr.js';
import { theme, slotStyle } from './chart.js';
import { SCHEMES } from './sampling.js';

export function setupCalc(app) {
  const $ = (id) => document.getElementById(id);
  const c = () => app.state.calc;

  function restore() {
    const s = c();
    $('dsCalcX').value = s.x; $('dsCalcA').value = s.a; $('dsCalcB').value = s.b; $('dsCalcShade').checked = !!s.shade;
    $('dsCalcPcts').value = s.pcts; $('dsCalcCover').value = s.cover;
    $('dsCalcT').value = s.t; $('dsCalcLevel').value = s.level;
    $('dsCalcMcExpr').value = s.mcExpr; $('dsCalcMcN').value = s.mcN; $('dsCalcMcSeed').value = s.mcSeed;
    const sel = $('dsCalcMcScheme');
    if (!sel.options.length) for (const [k, label] of SCHEMES) sel.append(new Option(label, k));
    sel.value = SCHEMES.some(([k]) => k === s.mcScheme) ? s.mcScheme : 'random';
  }
  function store() {
    const s = c();
    s.x = $('dsCalcX').value; s.a = $('dsCalcA').value; s.b = $('dsCalcB').value; s.shade = $('dsCalcShade').checked;
    s.pcts = $('dsCalcPcts').value; s.cover = $('dsCalcCover').value;
    s.t = $('dsCalcT').value; s.level = $('dsCalcLevel').value;
    s.cx = $('dsCalcCX').value || null; s.cy = $('dsCalcCY').value || null;
    s.mcExpr = $('dsCalcMcExpr').value; s.mcN = $('dsCalcMcN').value; s.mcSeed = $('dsCalcMcSeed').value; s.mcScheme = $('dsCalcMcScheme').value;
    app.saveSoon();
  }

  /* Sensible numbers to start from: the selected distribution's median and quartiles. */
  function seedInputs(its) {
    const s = c();
    const it = its.find((x) => x.key === app.state.active && x.D) || its.find((x) => x.D);
    if (!it) return;
    const D = it.D;
    const nice = (v) => String(+v.toPrecision(3));
    if (String(s.x).trim() === '') { s.x = nice(D.quantile(0.5)); $('dsCalcX').value = s.x; }
    if (String(s.a).trim() === '' && String(s.b).trim() === '') { s.a = nice(D.quantile(0.25)); s.b = nice(D.quantile(0.75)); $('dsCalcA').value = s.a; $('dsCalcB').value = s.b; }
    if (String(s.t).trim() === '') { s.t = nice(D.quantile(0.9)); $('dsCalcT').value = s.t; }
  }

  /* A table: a row per distribution, a column per quantity. */
  function table(id, cols, its, cells) {
    const t = $(id);
    t.replaceChildren();
    const head = t.createTHead().insertRow();
    for (const label of ['Distribution', ...cols]) {
      const th = document.createElement('th');
      th.textContent = label;
      head.append(th);
    }
    const body = t.createTBody();
    const th = theme();
    for (const it of its) {
      const tr = body.insertRow();
      const name = tr.insertCell();
      const { colour, dash } = slotStyle(it.slot, th);
      const key = document.createElement('span');
      key.className = 'ds-key' + (dash === 'dash' ? ' dashed' : '');
      key.style.setProperty('--ds-colour', colour);
      key.style.marginRight = '6px';
      name.append(key, document.createTextNode(it.name));
      if (!it.D) {
        const td = tr.insertCell();
        td.colSpan = cols.length;
        td.className = 'err';
        td.textContent = it.pending ? 'drawing…' : (it.error || 'not defined');
        continue;
      }
      let values;
      try { values = cells(it.D, it); } catch (e) { values = cols.map(() => '—'); }
      for (const v of values) tr.insertCell().textContent = v;
    }
  }

  const pct = (v) => (Number.isFinite(v) ? fmt(v, 5) : '—');

  function renderProb(its) {
    const x = parseNum($('dsCalcX').value);
    const a = parseNum($('dsCalcA').value);
    const b = parseNum($('dsCalcB').value);
    $('dsCalcX').setAttribute('aria-invalid', String($('dsCalcX').value.trim() !== '' && !Number.isFinite(x)));
    const cols = [`P(X ≤ ${fmt(x, 4)})`, `P(X > ${fmt(x, 4)})`, `P(${fmt(a, 4)} < X ≤ ${fmt(b, 4)})`, `f(${fmt(x, 4)})`, `h(${fmt(x, 4)})`];
    table('dsCalcProbTable', cols, its, (D) => {
      const r = probabilities(D, x, a, b);
      return [pct(r.cdf), pct(r.sf), pct(r.between), fmt(r.density, 5), fmt(r.hazard, 5)];
    });
  }

  function renderQuant(its) {
    const ps = parseNumberList($('dsCalcPcts').value).values.filter((p) => p > 0 && p < 100).slice(0, 12);
    const cover = parseNum($('dsCalcCover').value);
    const okCover = cover > 0 && cover < 100;
    $('dsCalcCover').setAttribute('aria-invalid', String(!okCover));
    const cols = [...ps.map((p) => `P${+p}`), ...(okCover ? [`central ${+cover} %`, `shortest ${+cover} %`] : [])];
    table('dsCalcQuantTable', cols, its, (D) => {
      const out = ps.map((p) => fmt(p <= 50 ? D.quantile(p / 100) : D.isf(1 - p / 100), 6));
      if (okCover) {
        const ci = centralInterval(D, cover / 100);
        const si = shortestInterval(D, cover / 100);
        out.push(`${fmt(ci[0], 5)} to ${fmt(ci[1], 5)}`, `${fmt(si[0], 5)} to ${fmt(si[1], 5)}`);
      }
      return out;
    });
  }

  function renderTail(its) {
    const t = parseNum($('dsCalcT').value);
    const level = parseNum($('dsCalcLevel').value);
    const okLevel = level > 0 && level < 100;
    $('dsCalcLevel').setAttribute('aria-invalid', String(!okLevel));
    const cols = [`P(X > ${fmt(t, 4)})`, `E[X | X > ${fmt(t, 4)}]`, `E[X | X ≤ ${fmt(t, 4)}]`, `E[(X − ${fmt(t, 4)})⁺]`, `value at ${+level} %`, `mean beyond it`];
    table('dsCalcTailTable', cols, its, (D) => {
      const r = tailStats(D, t, okLevel ? level / 100 : NaN);
      return [pct(r.pAbove), fmt(r.above, 6), fmt(r.below, 6), fmt(r.excess, 5), fmt(r.var, 6), fmt(r.tvar, 6)];
    });
  }

  function fillPairSelects(its) {
    const s = c();
    for (const [id, keep, fallback] of [['dsCalcCX', s.cx, 0], ['dsCalcCY', s.cy, 1]]) {
      const sel = $(id);
      const current = sel.value || keep;
      sel.replaceChildren();
      for (const it of its) {
        const o = document.createElement('option');
        o.value = it.key;
        o.textContent = it.name;
        sel.append(o);
      }
      const want = its.find((it) => it.key === current) ? current : (its[Math.min(fallback, its.length - 1)] || {}).key;
      if (want) sel.value = want;
    }
  }

  function renderCompare(its) {
    const t = $('dsCalcCompareTable');
    t.replaceChildren();
    const X = its.find((it) => it.key === $('dsCalcCX').value);
    const Y = its.find((it) => it.key === $('dsCalcCY').value);
    if (!X || !Y) return;
    const body = t.createTBody();
    const rowOf = (label, value) => { const tr = body.insertRow(); tr.insertCell().textContent = label; tr.insertCell().textContent = value; };
    if (!X.D || !Y.D) { rowOf('', `${!X.D ? X.letter : Y.letter} has an error.`); return; }
    if (X.key === Y.key) { rowOf('', 'Choose two different distributions.'); return; }
    let r;
    try { r = compare(X.D, Y.D); } catch (e) { rowOf('', 'The comparison failed.'); return; }
    rowOf(`P(${X.letter} > ${Y.letter}), independent`, fmt(r.pGreater, 5));
    rowOf(`P(${X.letter} < ${Y.letter})`, fmt(r.pLess, 5));
    if (X.D.kind === 'discrete' && Y.D.kind === 'discrete') rowOf(`P(${X.letter} = ${Y.letter})`, fmt(r.pEqual, 5));
    rowOf('Overlap of the densities', fmt(r.overlap, 5));
    rowOf('Largest gap between the CDFs (K–S)', fmt(r.ks, 5));
    rowOf('Wasserstein distance', fmt(r.wasserstein, 5));
    rowOf('Hellinger distance', fmt(r.hellinger, 5));
    rowOf(`Kullback–Leibler ${X.letter} ‖ ${Y.letter} (nats)`, fmt(r.klXY, 5));
    rowOf(`Kullback–Leibler ${Y.letter} ‖ ${X.letter} (nats)`, fmt(r.klYX, 5));
  }

  function render() {
    const its = app.items();
    seedInputs(its);
    fillPairSelects(its);
    renderProb(its);
    renderQuant(its);
    renderTail(its);
    renderCompare(its);
    const help = $('dsCalcMcExpr');
    if (!help.value && its.length >= 2) help.placeholder = `e.g. ${its[0].letter} * ${its[1].letter} + 2`;
  }

  /* ---- Monte Carlo ---- */
  function addMc() {
    const msg = $('dsCalcMcMsg');
    const expr = $('dsCalcMcExpr').value.trim();
    msg.hidden = true;
    try {
      const its = app.items();
      parseExpression(expr, (name) => its.some((it) => it.letter === name));
    } catch (e) {
      msg.textContent = e.message;
      msg.hidden = false;
      return;
    }
    const d = app.addFromPanel((x) => {
      x.kind = 'mc';
      x.mc = { expr, n: $('dsCalcMcN').value, seed: $('dsCalcMcSeed').value, scheme: $('dsCalcMcScheme').value, method: 'kde' };
      x.name = '';
    });
    if (d) app.status(`Added as ${app.fullName(d)}; it is drawn in the background.`);
    store();
  }

  let timer = null;
  registerActions({
    'ds:calc': () => {
      store();
      clearTimeout(timer);
      timer = setTimeout(render, 120);
    },
    'ds:mcAdd': () => addMc(),
  });
  for (const id of ['dsCalcMcExpr', 'dsCalcMcN', 'dsCalcMcSeed', 'dsCalcMcScheme']) {
    $(id).addEventListener('change', store);
  }
  restore();
  return { render };
}
