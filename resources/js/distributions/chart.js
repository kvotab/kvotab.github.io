/* ==========================================================================
   distributions.html: THE CHARTS

   Figures for Plotly from evaluated distributions: density (or
   probability), cumulative and exceedance probability, quantile function
   and hazard rate, for the Chart tab and for the Fit tab's diagnostics.

   A continuous curve is evaluated on a grid even across the axis and on a
   grid of quantiles, merged, so that the tails and the region where the
   probability is are both drawn finely, and a density that jumps at the end
   of its support is drawn with its edge. A discrete distribution is drawn
   as stems (its probabilities) or steps (its cumulative curves).

   Marks follow the page's chart rules: 2px lines, a 10 % wash under a
   density, hairline solid grid, the legend above the plot whenever there are
   two or more distributions, one tooltip listing every curve at the x under
   the pointer, value first. Names are escaped before they reach Plotly.
   ========================================================================== */

import { normQuantile, normCdf, LN10 } from './special.js';
import { escapeHtml, fmt, parseNum } from './format.js';
import { symbolOf } from './kit.js';
import { binCount } from './empirical.js';

export const FUNCTIONS = {
  pdf: { label: 'Density / probability', short: 'f(x)' },
  cdf: { label: 'Cumulative probability', short: 'F(x)' },
  sf: { label: 'Exceedance probability', short: '1 − F(x)' },
  quantile: { label: 'Quantile function', short: 'Q(p)' },
  hazard: { label: 'Hazard rate', short: 'h(x)' },
};

/* ---- theme ------------------------------------------------------------------------- */

/** The colours of the page's theme as it is drawn now. */
export function theme() {
  const root = document.querySelector('.ds') || document.documentElement;
  const cs = getComputedStyle(root);
  const doc = getComputedStyle(document.documentElement);
  const v = (name, fallback) => (cs.getPropertyValue(name) || doc.getPropertyValue(name) || fallback).trim() || fallback;
  return {
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--ds-c${i}`, '#2a78d6')),
    data: v('--ds-data', '#8a8178'),
    bg: v('--bg-primary', '#ffffff'),
    text: v('--text-primary', '#352921'),
    text2: v('--text-secondary', '#6b5d4f'),
    muted: v('--text-muted', '#786b5d'),
    grid: v('--border-color', '#e0d7ce'),
  };
}

/** The colour and dash of a distribution's slot (0..15). */
export function slotStyle(slot, th) {
  return { colour: th.series[slot % 8], dash: slot >= 8 ? 'dash' : 'solid' };
}

export function withAlpha(colour, alpha) {
  const hex = String(colour).replace('#', '');
  const n = parseInt(hex.length === 3 ? hex.replace(/./g, (c) => c + c) : hex, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

/* ---- the x-axis ------------------------------------------------------------------------ */

/**
 * The x-range covering every item's [Q(pmin), Q(pmax)] (and its data, when
 * shown), or the values given. For a log axis, positive.
 */
export function axisRange(items, s) {
  let lo = Infinity;
  let hi = -Infinity;
  const pmin = Math.min(Math.max(s.pmin / 100, 1e-12), 0.49);
  const pmax = Math.max(Math.min(s.pmax / 100, 1 - 1e-12), 0.51);
  for (const it of items) {
    const D = it.D;
    let a = D.quantile(pmin);
    let b = D.isf(1 - pmax);
    if (s.logx) {
      if (!(b > 0)) continue;
      if (!(a > 0)) a = Math.max(D.quantile(0.5) > 0 ? D.quantile(0.5) / 1e3 : b / 1e6, Number.MIN_VALUE);
    }
    if (D.kind === 'discrete') { a -= 0.5; b += 0.5; }
    if (Number.isFinite(a)) lo = Math.min(lo, a);
    if (Number.isFinite(b)) hi = Math.max(hi, b);
    if (s.showData && it.data && it.data.length) {
      const d0 = it.data[0];
      const d1 = it.data[it.data.length - 1];
      if (!s.logx || d0 > 0) lo = Math.min(lo, d0);
      hi = Math.max(hi, d1);
    }
  }
  if (!(hi > lo)) {
    if (Number.isFinite(lo)) { const w = Math.abs(lo) || 1; lo -= w / 2; hi = lo + w; } else { lo = 0; hi = 1; }
  }
  /* a support end just outside the range is brought in, so a uniform shows its edges */
  if (!s.logx) {
    const pad = (hi - lo) * 0.04;
    for (const it of items) {
      const [s0, s1] = it.D.support;
      if (Number.isFinite(s0) && s0 < lo && lo - s0 < 4 * pad) lo = s0;
      if (Number.isFinite(s1) && s1 > hi && s1 - hi < 4 * pad) hi = s1;
      if (Number.isFinite(s0) && Math.abs(s0 - lo) < 1e-9 * (hi - lo) + 1e-300) lo = s0 - pad / 2;
      if (Number.isFinite(s1) && Math.abs(s1 - hi) < 1e-9 * (hi - lo) + 1e-300) hi = s1 + pad / 2;
    }
  }
  if (Number.isFinite(s.xmin) && (!s.logx || s.xmin > 0)) lo = s.xmin;
  if (Number.isFinite(s.xmax)) hi = s.xmax;
  if (!(hi > lo)) hi = lo + (Math.abs(lo) || 1);
  if (s.logx && !(lo > 0)) lo = hi / 1e6;
  return [lo, hi];
}

/* ---- sampling a curve --------------------------------------------------------------------- */

function valueGrid(D, lo, hi, s) {
  const xs = [];
  const N = 360;
  for (let i = 0; i <= N; i++) {
    const t = i / N;
    xs.push(s.logx ? Math.exp(Math.log(lo) + t * (Math.log(hi) - Math.log(lo))) : lo + t * (hi - lo));
  }
  /* quantiles evenly spread in normal scores, for the tails */
  const pmin = Math.min(Math.max(s.pmin / 100, 1e-12), 0.49);
  const pmax = Math.max(Math.min(s.pmax / 100, 1 - 1e-12), 0.51);
  const z0 = normQuantile(pmin);
  const z1 = normQuantile(1 - (1 - pmax));
  const M = 160;
  for (let i = 0; i <= M; i++) {
    const z = z0 + (z1 - z0) * i / M;
    const u = normCdf(z);
    const x = D.at(u, normCdf(-z));
    if (x > lo && x < hi) xs.push(x);
  }
  /* the support ends, with a point just outside, so a jump is drawn as an edge */
  for (const e of D.support) {
    if (!Number.isFinite(e) || e < lo || e > hi) continue;
    const eps = Math.max(Math.abs(e), (hi - lo) * 1e-6) * 1e-9;
    xs.push(e, e - eps, e + eps);
  }
  const sorted = xs.filter((x) => x >= lo && x <= hi && (!s.logx || x > 0)).sort((a, b) => a - b);
  const out = [];
  for (const x of sorted) if (!out.length || x > out[out.length - 1]) out.push(x);
  return out;
}

function clean(v) { return Number.isFinite(v) ? v : null; }

/**
 * One distribution's curve of function fn over [lo, hi]: { x, y, stems }
 * where stems marks a discrete distribution drawn as stems.
 */
export function curve(D, fn, lo, hi, s) {
  if (fn === 'quantile') return quantileCurve(D, s);
  if (D.kind === 'discrete') return discreteCurve(D, fn, lo, hi);
  const xs = valueGrid(D, lo, hi, s);
  const y = xs.map((x) => {
    if (fn === 'pdf') { const f = D.pdf(x); return clean(s.logx ? f * x * LN10 : f); }
    if (fn === 'cdf') return clean(D.cdf(x));
    if (fn === 'sf') return clean(D.sf(x));
    return clean(D.hazard(x));
  });
  return { x: xs, y, stems: false };
}

function discreteCurve(D, fn, lo, hi) {
  const at = D.atoms();
  if (!at) return { x: [], y: [], stems: fn === 'pdf' || fn === 'hazard' };
  const xs = [];
  const ps = [];
  for (let i = 0; i < at[0].length; i++) if (at[0][i] >= lo && at[0][i] <= hi) { xs.push(at[0][i]); ps.push(at[1][i]); }
  if (fn === 'pdf') return { x: xs, y: ps, stems: true };
  /* P(X <= x) summed from the left and P(X > x) from the right, from one
     value of each: not one CDF per value, which for a family whose CDF is
     itself a sum is a sum over the support every time */
  const m = xs.length;
  const below = new Array(m);
  const above = new Array(m);
  if (m) {
    below[0] = D.cdf(xs[0]);
    for (let i = 1; i < m; i++) below[i] = below[i - 1] + ps[i];
    above[m - 1] = D.sf(xs[m - 1]);
    for (let i = m - 2; i >= 0; i--) above[i] = above[i + 1] + ps[i + 1];
  }
  if (fn === 'hazard') return { x: xs, y: xs.map((x, i) => clean(ps[i] / (ps[i] + above[i]))), stems: true };
  /* steps: right-continuous, drawn with shape 'hv' */
  const x = [lo, ...xs, hi];
  const y = fn === 'cdf' ? [D.cdf(lo), ...below.map((v) => Math.min(1, v)), D.cdf(hi)] : [D.sf(lo), ...above.map((v) => Math.min(1, v)), D.sf(hi)];
  return { x, y: y.map(clean), stems: false, step: true };
}

function quantileCurve(D, s) {
  const pmin = Math.min(Math.max(s.pmin / 100, 1e-12), 0.49);
  const pmax = Math.max(Math.min(s.pmax / 100, 1 - 1e-12), 0.51);
  const us = [];
  const N = 300;
  for (let i = 0; i <= N; i++) us.push(pmin + (pmax - pmin) * i / N);
  const z0 = normQuantile(pmin);
  const z1 = normQuantile(pmax);
  for (let i = 0; i <= 80; i++) us.push(normCdf(z0 + (z1 - z0) * i / 80));
  us.sort((a, b) => a - b);
  const u = us.filter((v, i) => i === 0 || v > us[i - 1]);
  return { x: u, y: u.map((p) => clean(D.at(p, 1 - p))), stems: false, step: D.kind === 'discrete' };
}

/* ---- data overlays ------------------------------------------------------------------------------ */

/* The data a distribution carries and the draws of the Sample tab look
   alike, the draws with dotted outlines. */
const overlayLine = (what) => (what === 'sample' ? 'dot' : 'solid');

/* How the histograms are binned: a rule, a number of bins or a width (in
   decades on a log axis), [key, label]. */
export const HIST_BINS = [
  ['fd', 'Freedman–Diaconis'],
  ['scott', 'Scott'],
  ['sturges', 'Sturges'],
  ['sqrt', 'square root'],
  ['rice', 'Rice'],
  ['count', 'number of bins'],
  ['width', 'bin width'],
];
const MAX_RULE_BINS = 500;
const MAX_BINS = 2000;

/**
 * The bins of a histogram over sorted values: the left edge, the width and
 * the number. A rule's bins span the values; a given width puts the edges
 * at its multiples, so that histograms side by side share them.
 *
 * @param {ArrayLike<number>} vals   sorted
 * @param {{rule: string, value: *}} [bins]
 */
export function histogramBins(vals, bins) {
  const n = vals.length;
  const a = vals[0];
  const b = vals[n - 1];
  const rule = (bins && bins.rule) || 'fd';
  const v = bins ? parseFloat(String(bins.value ?? '').replace(',', '.')) : NaN;
  if (rule === 'width' && v > 0) {
    const a0 = Math.floor(a / v) * v;
    const k = Math.min(MAX_BINS, Math.max(1, Math.ceil((b - a0) / v)));
    return { a: a0, width: Math.max(v, (b - a0) / k), k };
  }
  let k;
  if (rule === 'count' && v >= 1) k = Math.min(MAX_BINS, Math.round(v));
  else if (rule === 'rice') k = Math.min(MAX_RULE_BINS, Math.ceil(2 * Math.cbrt(n)));
  else k = Math.min(MAX_RULE_BINS, binCount(vals, ['scott', 'sturges', 'sqrt'].includes(rule) ? rule : 'fd'));
  k = Math.max(1, k);
  return { a, width: (b - a) / k, k };
}

/* The bins setting as a select and its field (the chart's and the Fit tab's). */
/** The select's choices and the stored setting, put into a select and its field. */
export function fillBins(sel, input, bins) {
  if (!sel.options.length) for (const [k, label] of HIST_BINS) sel.append(new Option(label, k));
  sel.value = bins.rule;
  input.value = bins.value;
  syncBinsField(sel, input, bins);
}

/** The field shows only for a number of bins or a width, and is marked when it is not one. */
export function syncBinsField(sel, input, bins) {
  const needs = bins.rule === 'count' || bins.rule === 'width';
  input.hidden = !needs;
  input.placeholder = bins.rule === 'count' ? 'bins' : 'width';
  input.setAttribute('aria-label', bins.rule === 'count' ? 'Number of bins' : 'Bin width (in decades on a logarithmic x-axis)');
  const v = parseNum(bins.value);
  const ok = !needs || String(bins.value).trim() === '' || (bins.rule === 'count' ? Number.isInteger(v) && v >= 1 && v <= 2000 : v > 0);
  input.setAttribute('aria-invalid', String(!ok));
}

/* A histogram of the data as a stepped area: density (per decade on a log axis). */
function histogramTrace(data, lo, hi, s, colour, key, what = 'data') {
  const vals = s.logx ? data.filter((v) => v > 0).map(Math.log10) : Array.from(data);
  const n = vals.length;
  if (n < 2) return null;
  if (!(vals[n - 1] > vals[0])) return null;
  const { a, width, k } = histogramBins(vals, s.bins);
  const counts = new Array(k).fill(0);
  for (const v of vals) counts[Math.min(k - 1, Math.floor((v - a) / width))]++;
  const xs = [];
  const ys = [];
  for (let i = 0; i < k; i++) {
    const e0 = a + i * width;
    const e1 = a + (i + 1) * width;
    const h = counts[i] / (data.length * width);   // density of log10 x, per decade, or of x
    const X0 = s.logx ? Math.pow(10, e0) : e0;
    const X1 = s.logx ? Math.pow(10, e1) : e1;
    if (i === 0) { xs.push(X0); ys.push(0); }
    xs.push(X0, X1);
    ys.push(h, h);
    if (i === k - 1) { xs.push(X1); ys.push(0); }
  }
  return {
    type: 'scatter', mode: 'lines', x: xs, y: ys, fill: 'tozeroy',
    fillcolor: withAlpha(colour, what === 'sample' ? 0.12 : 0.16), line: { color: withAlpha(colour, 0.6), width: 1, dash: overlayLine(what) },
    hoverinfo: 'skip', showlegend: false, legendgroup: key, name: what,
  };
}

/* The empirical CDF as steps; past 4,000 values at 2,000 evenly spaced
   ranks, which a screen cannot tell from every step. */
function ecdfTrace(data, lo, hi, fn, colour, key, what = 'data') {
  const n = data.length;
  const xs = [lo];
  const ys = [fn === 'cdf' ? 0 : 1];
  const step = (i) => {
    xs.push(data[i]);
    ys.push(fn === 'cdf' ? (i + 1) / n : 1 - (i + 1) / n);
  };
  if (n > 4000) {
    const m = 2000;
    let last = -1;
    for (let j = 0; j <= m; j++) {
      let i = Math.round((j * (n - 1)) / m);
      while (i + 1 < n && data[i + 1] === data[i]) i++;
      if (i > last) { step(i); last = i; }
    }
  } else {
    for (let i = 0; i < n; i++) {
      if (i + 1 < n && data[i + 1] === data[i]) continue;
      step(i);
    }
  }
  xs.push(hi);
  ys.push(ys[ys.length - 1]);
  return {
    type: 'scatter', mode: 'lines', x: xs, y: ys, line: { color: withAlpha(colour, 0.6), width: 1.5, shape: 'hv', dash: overlayLine(what) },
    hoverinfo: 'skip', showlegend: false, legendgroup: key, name: what,
  };
}

function frequencyTrace(data, colour, key, what = 'data') {
  const counts = new Map();
  for (const v of data) counts.set(v, (counts.get(v) || 0) + 1);
  const xs = [...counts.keys()].sort((a, b) => a - b);
  return {
    type: 'scatter', mode: 'markers', x: xs, y: xs.map((x) => counts.get(x) / data.length),
    marker: { symbol: what === 'sample' ? 'diamond-open' : 'circle-open', size: 9, color: colour, line: { width: 2 } },
    hoverinfo: 'skip', showlegend: false, legendgroup: key, name: what,
  };
}

/* Sorted values against their plotting positions, at most 400 of them. */
function quantileMarkers(data, colour, key, what) {
  const n = data.length;
  const step = Math.max(1, Math.floor(n / 400));
  const px = [];
  const py = [];
  for (let i = 0; i < n; i += step) { px.push((i + 0.5) / n); py.push(data[i]); }
  return { type: 'scatter', mode: 'markers', x: px, y: py, marker: { size: 4, color: withAlpha(colour, 0.5), symbol: what === 'sample' ? 'diamond' : 'circle' }, hoverinfo: 'skip', showlegend: false, legendgroup: key, name: what };
}

/* ---- one figure --------------------------------------------------------------------------------------- */

/**
 * The traces and layout of one chart.
 *
 * @param {Array<{key, name, slot, D, data, visible}>} items
 * @param {string} fn         one of FUNCTIONS
 * @param {Object} s          { logx, logy, showData, showSamples, pmin, pmax, xmin, xmax }
 * @param {Object} th         theme()
 * @param {Object} [opts]     { shade: {key, a, b}, height }
 */
export function figure(items, fn, s, th, opts = {}) {
  const shown = items.filter((it) => it.visible && it.D);
  const logx = s.logx && fn !== 'quantile';
  const sx = { ...s, logx };
  const [lo, hi] = shown.length ? axisRange(shown, sx) : [0, 1];
  const traces = [];
  const fills = [];
  const several = items.length > 1;
  /* Several discrete distributions on a short axis stand side by side at
     each value, a little apart, so that one does not hide another; the
     tooltip keeps the true value. */
  const stemmed = (fn === 'pdf' || fn === 'hazard') ? shown.filter((it) => it.D.kind === 'discrete') : [];
  const dodge = stemmed.length > 1 && hi - lo < 300 ? Math.min(0.12, 0.36 / stemmed.length) : 0;
  const offsetOf = (it) => (dodge ? (stemmed.indexOf(it) - (stemmed.length - 1) / 2) * dodge : 0);
  for (const it of items) {
    const { colour, dash } = slotStyle(it.slot, th);
    const name = escapeHtml(it.name);
    const key = it.key;
    if (!it.visible || !it.D) {
      traces.push({ type: 'scatter', mode: 'lines', x: [], y: [], name, legendgroup: key, visible: 'legendonly', showlegend: several, line: { color: colour, width: 2, dash } });
      continue;
    }
    const D = it.D;
    const c = curve(D, fn, lo, hi, sx);
    const hover = `<b>%{y:.4~g}</b>  ${name}<extra></extra>`;
    for (const [what, on, values] of [['data', s.showData, it.data], ['sample', s.showSamples, it.sample]]) {
      if (!on || !values || values.length < 2 || fn === 'hazard') continue;
      let t = null;
      if (fn === 'pdf') t = D.kind === 'discrete' ? frequencyTrace(values, colour, key, what) : histogramTrace(values, lo, hi, sx, colour, key, what);
      else if (fn === 'cdf' || fn === 'sf') t = ecdfTrace(values, lo, hi, fn, colour, key, what);
      else if (fn === 'quantile') t = quantileMarkers(values, colour, key, what);
      if (t) fills.push(t);
    }
    if (c.stems) {
      const off = offsetOf(it);
      const sx2 = [];
      const sy2 = [];
      for (let i = 0; i < c.x.length; i++) { sx2.push(c.x[i] + off, c.x[i] + off, null); sy2.push(0, c.y[i], null); }
      traces.push({ type: 'scatter', mode: 'lines', x: sx2, y: sy2, line: { color: colour, width: c.x.length > 300 ? 1 : 2, dash }, hoverinfo: 'skip', name, legendgroup: key, showlegend: several });
      traces.push({
        type: 'scatter', mode: 'markers', x: off ? c.x.map((v) => v + off) : c.x, y: c.y, customdata: c.x, name, legendgroup: key, showlegend: false,
        marker: c.x.length <= 80 ? { size: 9, color: colour, line: { color: th.bg, width: 2 } } : { size: 6, color: colour, opacity: 0 },
        hovertemplate: off ? `<b>%{y:.4~g}</b>  ${name} at %{customdata}<extra></extra>` : hover,
      });
      continue;
    }
    const line = { color: colour, width: 2, dash, shape: c.step ? 'hv' : 'linear' };
    const isDensity = fn === 'pdf';
    traces.push({
      type: 'scatter', mode: 'lines', x: c.x, y: c.y, name, legendgroup: key, showlegend: several, line,
      fill: isDensity && !s.logy ? 'tozeroy' : 'none', fillcolor: withAlpha(colour, 0.1), hovertemplate: hover, connectgaps: false,
    });
    if (isDensity && opts.shade && opts.shade.key === key) {
      const { a, b } = opts.shade;
      const xs = [];
      const ys = [];
      const at = (x) => { const f = D.pdf(x); return s.logx ? f * x * LN10 : f; };
      if (Number.isFinite(a) && Number.isFinite(b) && b > a) {
        xs.push(a); ys.push(at(a));
        for (let i = 0; i < c.x.length; i++) if (c.x[i] > a && c.x[i] < b) { xs.push(c.x[i]); ys.push(c.y[i]); }
        xs.push(b); ys.push(at(b));
        fills.push({ type: 'scatter', mode: 'lines', x: xs, y: ys.map(clean), fill: 'tozeroy', fillcolor: withAlpha(colour, 0.38), line: { width: 0, color: colour }, hoverinfo: 'skip', showlegend: false, legendgroup: key });
      }
    }
  }
  const anyContinuous = shown.some((it) => it.D.kind === 'continuous');
  const anyDiscrete = shown.some((it) => it.D.kind === 'discrete');
  const ytitle = {
    pdf: anyDiscrete && anyContinuous ? (logx ? 'Density per decade / probability' : 'Density / probability') : anyDiscrete ? 'Probability' : logx ? 'Density per decade, x·f(x)·ln 10' : 'Density',
    cdf: 'P(X ≤ x)', sf: 'P(X > x)', quantile: 'Value', hazard: 'Hazard rate',
  }[fn];
  const axis = {
    gridcolor: th.grid, linecolor: th.grid, zeroline: false, color: th.text2, tickfont: { size: 11, color: th.text2 },
    showspikes: false, automargin: true,
  };
  const xaxis = {
    ...axis,
    title: { text: fn === 'quantile' ? 'Cumulative probability p' : 'x', font: { size: 12, color: th.text2 }, standoff: 6 },
    type: logx ? 'log' : 'linear',
    range: fn === 'quantile' ? undefined : (logx ? [Math.log10(lo), Math.log10(hi)] : [lo, hi]),
    hoverformat: '.5~g',
    showspikes: true, spikemode: 'across', spikesnap: 'cursor', spikethickness: 1, spikecolor: th.muted, spikedash: 'solid',
  };
  const yaxis = {
    ...axis,
    title: { text: ytitle, font: { size: 12, color: th.text2 }, standoff: 6 },
    type: s.logy ? 'log' : 'linear',
    rangemode: s.logy ? undefined : (fn === 'quantile' ? 'normal' : 'tozero'),
    exponentformat: 'e',
  };
  if (fn === 'cdf' && !s.logy) yaxis.range = [0, 1.02];
  const layout = {
    paper_bgcolor: th.bg, plot_bgcolor: th.bg,
    font: { family: 'verdana, sans-serif', size: 11, color: th.text2 },
    margin: { l: 58, r: 14, t: several ? 34 : 12, b: 40 },
    showlegend: several,
    legend: { orientation: 'h', x: 0, xanchor: 'left', y: 1.01, yanchor: 'bottom', font: { size: 11, color: th.text }, bgcolor: 'rgba(0,0,0,0)', itemclick: 'toggle', itemdoubleclick: false },
    hovermode: 'x unified',
    hoverlabel: { bgcolor: th.bg, bordercolor: th.grid, font: { color: th.text, size: 12, family: 'verdana, sans-serif' } },
    xaxis, yaxis,
  };
  return { data: [...fills, ...traces], layout, range: [lo, hi] };
}

/** Plotly's options for every chart on the page. */
export const PLOT_CONFIG = {
  responsive: true,
  displaylogo: false,
  modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d', 'toggleSpikelines', 'hoverCompareCartesian', 'hoverClosestCartesian'],
  toImageButtonOptions: { format: 'png', filename: 'distributions', scale: 2 },
};

/* ---- the fit diagnostics ------------------------------------------------------------------------------- */

/**
 * The fits against the data: density over a histogram, CDF over the
 * empirical one, P-P or Q-Q.
 *
 * @param {Float64Array} data sorted
 * @param {Array<{key, name, colour, D}>} fits
 */
export function fitFigure(data, fits, kind, th, logx, bins) {
  const n = data.length;
  const traces = [];
  const name = (f) => escapeHtml(f.name);
  const s = { logx: logx && data[0] > 0, logy: false, showData: true, pmin: 0.1, pmax: 99.9, bins };
  let lo = data[0];
  let hi = data[n - 1];
  const pad = (hi - lo) * 0.05 || Math.abs(lo) * 0.1 || 1;
  if (!s.logx) { lo -= pad; hi += pad; } else { lo /= 1.2; hi *= 1.2; }
  const discrete = fits.length && fits.every((f) => f.D.kind === 'discrete');
  const several = fits.length > 1;
  let xtitle = 'x';
  let ytitle = '';
  if (kind === 'pdf') {
    if (discrete) traces.push(frequencyTrace(data, th.data, 'data'));
    else { const h = histogramTrace(data, lo, hi, s, th.data, 'data'); if (h) traces.push(h); }
    const dodge = discrete && fits.length > 1 && hi - lo < 300 ? Math.min(0.14, 0.42 / fits.length) : 0;
    fits.forEach((f, j) => {
      const c = curve(f.D, 'pdf', lo, hi, s);
      if (c.stems) {
        const off = dodge ? (j - (fits.length - 1) / 2) * dodge : 0;
        const sx2 = [];
        const sy2 = [];
        for (let i = 0; i < c.x.length; i++) { sx2.push(c.x[i] + off, c.x[i] + off, null); sy2.push(0, c.y[i], null); }
        traces.push({ type: 'scatter', mode: 'lines', x: sx2, y: sy2, name: name(f), legendgroup: f.key, line: { color: f.colour, width: 2 }, hoverinfo: 'skip' });
        traces.push({ type: 'scatter', mode: 'markers', x: c.x.map((v) => v + off), y: c.y, customdata: c.x, name: name(f), legendgroup: f.key, showlegend: false, marker: { size: 8, color: f.colour, line: { color: th.bg, width: 2 } }, hovertemplate: `<b>%{y:.4~g}</b>  ${name(f)} at %{customdata}<extra></extra>` });
      } else {
        traces.push({ type: 'scatter', mode: 'lines', x: c.x, y: c.y, name: name(f), line: { color: f.colour, width: 2 }, hovertemplate: `<b>%{y:.4~g}</b>  ${name(f)}<extra></extra>` });
      }
    });
    ytitle = discrete ? 'Probability (circles: the data)' : s.logx ? 'Density per decade (shaded: the data)' : 'Density (shaded: the data)';
  } else if (kind === 'cdf') {
    traces.push({ ...ecdfTrace(data, lo, hi, 'cdf', th.data, 'data'), name: 'data', line: { color: th.data, width: 2, shape: 'hv' } });
    for (const f of fits) {
      const c = curve(f.D, 'cdf', lo, hi, s);
      traces.push({ type: 'scatter', mode: 'lines', x: c.x, y: c.y, name: name(f), line: { color: f.colour, width: 2, shape: c.step ? 'hv' : 'linear' }, hovertemplate: `<b>%{y:.4~g}</b>  ${name(f)}<extra></extra>` });
    }
    ytitle = 'P(X ≤ x) (grey steps: the data)';
  } else if (kind === 'pp') {
    traces.push({ type: 'scatter', mode: 'lines', x: [0, 1], y: [0, 1], line: { color: th.muted, width: 1 }, hoverinfo: 'skip', showlegend: false });
    const step = Math.max(1, Math.floor(n / 1000));
    for (const f of fits) {
      const px = [];
      const py = [];
      for (let i = 0; i < n; i += step) { px.push((i + 0.5) / n); py.push(f.D.cdf(data[i])); }
      traces.push({ type: 'scatter', mode: n <= 60 ? 'lines+markers' : 'lines', x: px, y: py, name: name(f), line: { color: f.colour, width: 2 }, marker: { size: 8, color: f.colour, line: { color: th.bg, width: 2 } }, hovertemplate: `<b>%{y:.4~g}</b>  ${name(f)}<extra></extra>` });
    }
    xtitle = 'Empirical probability (i − ½)/n';
    ytitle = 'Fitted probability F(xᵢ)';
  } else {
    const step = Math.max(1, Math.floor(n / 1000));
    let qlo = Infinity;
    let qhi = -Infinity;
    for (const f of fits) {
      const px = [];
      const py = [];
      for (let i = 0; i < n; i += step) {
        const u = (i + 0.5) / n;
        const q = f.D.at(u, 1 - u);
        px.push(q);
        py.push(data[i]);
        if (Number.isFinite(q)) { qlo = Math.min(qlo, q); qhi = Math.max(qhi, q); }
      }
      traces.push({ type: 'scatter', mode: n <= 60 ? 'lines+markers' : 'lines', x: px, y: py, name: name(f), line: { color: f.colour, width: 2 }, marker: { size: 8, color: f.colour, line: { color: th.bg, width: 2 } }, hovertemplate: `<b>%{y:.4~g}</b>  ${name(f)}<extra></extra>` });
    }
    const a = Math.min(qlo, data[0]);
    const b = Math.max(qhi, data[n - 1]);
    traces.unshift({ type: 'scatter', mode: 'lines', x: [a, b], y: [a, b], line: { color: th.muted, width: 1 }, hoverinfo: 'skip', showlegend: false });
    xtitle = 'Fitted quantile Q((i − ½)/n)';
    ytitle = 'Data, sorted';
  }
  const axis = { gridcolor: th.grid, linecolor: th.grid, zeroline: false, color: th.text2, tickfont: { size: 11, color: th.text2 }, automargin: true };
  const logAxes = s.logx && (kind === 'pdf' || kind === 'cdf' || kind === 'qq');
  return {
    data: traces,
    layout: {
      paper_bgcolor: th.bg, plot_bgcolor: th.bg,
      font: { family: 'verdana, sans-serif', size: 11, color: th.text2 },
      margin: { l: 58, r: 14, t: several ? 34 : 12, b: 42 },
      showlegend: true,
      legend: { orientation: 'h', x: 0, xanchor: 'left', y: 1.01, yanchor: 'bottom', font: { size: 11, color: th.text }, bgcolor: 'rgba(0,0,0,0)' },
      hovermode: kind === 'pp' || kind === 'qq' ? 'closest' : 'x unified',
      hoverlabel: { bgcolor: th.bg, bordercolor: th.grid, font: { color: th.text, size: 12 } },
      xaxis: { ...axis, title: { text: xtitle, font: { size: 12, color: th.text2 } }, type: logAxes ? 'log' : 'linear', range: kind === 'pdf' || kind === 'cdf' ? (logAxes ? [Math.log10(lo), Math.log10(hi)] : [lo, hi]) : undefined, hoverformat: '.5~g' },
      yaxis: { ...axis, title: { text: ytitle, font: { size: 12, color: th.text2 } }, type: kind === 'qq' && logAxes ? 'log' : 'linear', rangemode: kind === 'pdf' ? 'tozero' : 'normal' },
    },
  };
}

/* ---- the curves as a table ----------------------------------------------------------------------------- */

/** The values a chart draws, as rows for a CSV file: distribution, x (or p), value. */
export function curveRows(items, fn, s) {
  const shown = items.filter((it) => it.visible && it.D);
  const logx = s.logx && fn !== 'quantile';
  const sx = { ...s, logx };
  const [lo, hi] = shown.length ? axisRange(shown, sx) : [0, 1];
  const rows = [['Distribution', fn === 'quantile' ? 'p' : 'x', FUNCTIONS[fn].short + (fn === 'pdf' && logx ? ' (per decade: x·f(x)·ln 10)' : '')]];
  for (const it of shown) {
    const c = curve(it.D, fn, lo, hi, sx);
    for (let i = 0; i < c.x.length; i++) if (c.x[i] !== null && c.y[i] !== null) rows.push([it.name, String(c.x[i]), String(c.y[i])]);
  }
  return rows;
}

/** A short description of a distribution's parameters (and shift), for the list and the tables. */
export function describeParams(D, sig = 4) {
  if (!D) return '';
  const parts = D.family ? D.family.params.map((p) => `${symbolOf(p)} = ${fmt(D.params[p.key], sig)}`) : [];
  if (D.shift) parts.push(`shifted by ${fmt(D.shift, sig)}`);
  return parts.join(', ');
}
