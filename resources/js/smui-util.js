/* ==========================================================================
   SMUI.HTML: SHARED PIECES

   The page is a statistics workbench in the manner of JMP: a data table,
   launch dialogs that cast columns into roles, and reports of outline
   boxes whose red-triangle menus add analyses. The statistics are
   statsmodels (with numpy, scipy and pandas) running in Pyodide in a Web
   Worker; the table, the graphs and the reports are this page's own.

   Everything hangs off one namespace, SM:

     SM.util      this file: events, formatting, DOM building, random numbers
     SM.Table     the data table (smui-table.js)
     SM.io        reading and writing files, the example tables (smui-io.js)
     SM.grid      the data grid (smui-grid.js)
     SM.panels    the Columns and Rows panels (smui-panels.js)
     SM.engine    the Pyodide worker (smui-engine.js, smui-worker.mjs)
     SM.report    report windows and their parts (smui-report.js)
     SM.launch    launch dialogs (smui-launch.js)
     SM.platforms the analysis platforms, one file each (smui-p-*.js)
     SM.app       the page: menus, tabs, state (smui-app.js)
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});

  /* ---- events ----------------------------------------------------------- */
  class Emitter {
    constructor() { this._h = Object.create(null); }
    on(type, fn) { (this._h[type] || (this._h[type] = [])).push(fn); return () => this.off(type, fn); }
    off(type, fn) { const a = this._h[type]; if (a) { const i = a.indexOf(fn); if (i >= 0) a.splice(i, 1); } }
    emit(type, detail) {
      for (const fn of (this._h[type] || []).slice()) {
        try { fn(detail); } catch (e) { console.error(`SM: a '${type}' handler failed`, e); }
      }
    }
  }

  /* ---- numbers as JMP shows them ------------------------------------------
     Estimates to about seven significant digits, integers as integers,
     very large or small magnitudes in exponent form, a missing value as a
     dot. p-values to four decimals, below 0.0001 as <.0001, and an
     asterisk when below the significance level. */
  function fmt(x, opts = {}) {
    if (x == null || x === '' || (typeof x === 'number' && Number.isNaN(x))) return '.';
    if (typeof x === 'string') return x === 'Infinity' ? '∞' : x === '-Infinity' ? '−∞' : x;
    if (typeof x !== 'number') return String(x);
    if (!Number.isFinite(x)) return x > 0 ? '∞' : '−∞';
    const digits = opts.digits;
    if (digits != null) return minus(x.toFixed(digits));
    if (Number.isInteger(x) && Math.abs(x) < 1e15) return minus(String(x));
    const a = Math.abs(x);
    const sig = opts.sig || 7;
    if (a !== 0 && (a >= 1e9 || a < 1e-4)) return minus(x.toExponential(Math.max(0, Math.min(sig, 5) - 1)).replace('e+', 'e'));
    let s = x.toPrecision(sig);
    if (s.includes('e')) return minus(Number(s).toString());
    if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '');
    return minus(s);
  }
  const minus = (s) => s.replace(/^-/, '−');

  function fmtP(p, alpha = 0.05) {
    if (p == null || (typeof p === 'number' && Number.isNaN(p))) return '.';
    if (typeof p !== 'number') return String(p);
    const star = p < alpha ? '*' : '';
    if (p < 0.0001) return `<.0001${star}`;
    return `${p.toFixed(4)}${star}`;
  }

  function fmtPct(x, digits = 1) {
    if (x == null || Number.isNaN(x)) return '.';
    return `${(100 * x).toFixed(digits)}%`;
  }

  /* ---- DOM, text nodes only ------------------------------------------------ */
  function el(tag, attrs, ...children) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === 'class') e.className = v;
        else if (k === 'text') e.textContent = v;
        else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
        else if (k === 'dataset') Object.assign(e.dataset, v);
        else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
        else if (v === true) e.setAttribute(k, '');
        else e.setAttribute(k, String(v));
      }
    }
    for (const c of children.flat(Infinity)) {
      if (c == null || c === false) continue;
      e.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return e;
  }

  function svg(tag, attrs, ...children) {
    const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v != null) e.setAttribute(k, String(v));
    for (const c of children.flat(Infinity)) if (c) e.append(c);
    return e;
  }

  /* The modeling-type icons: blue for continuous, green for ordinal, red
     for nominal -- the convention JMP users read at a glance. */
  function typeIcon(type, size = 12) {
    const s = svg('svg', { viewBox: '0 0 12 12', width: size, height: size, class: `sm-type sm-type-${type}`, 'aria-hidden': 'true' });
    if (type === 'continuous') {
      s.append(svg('path', { d: 'M1.5 10.5 L10.5 10.5 L10.5 1.5 Z', fill: 'currentColor' }));
    } else if (type === 'ordinal') {
      s.append(svg('rect', { x: 1, y: 7, width: 2.4, height: 3.5, fill: 'currentColor' }),
        svg('rect', { x: 4.8, y: 4.5, width: 2.4, height: 6, fill: 'currentColor' }),
        svg('rect', { x: 8.6, y: 1.5, width: 2.4, height: 9, fill: 'currentColor' }));
    } else {
      s.append(svg('rect', { x: 1, y: 4, width: 2.4, height: 6.5, fill: 'currentColor' }),
        svg('rect', { x: 4.8, y: 1.5, width: 2.4, height: 9, fill: 'currentColor' }),
        svg('rect', { x: 8.6, y: 6, width: 2.4, height: 4.5, fill: 'currentColor' }));
    }
    return s;
  }

  const TYPE_LABEL = { continuous: 'Continuous', ordinal: 'Ordinal', nominal: 'Nominal' };

  /* ---- random numbers for the example tables ------------------------------
     sfc32 seeded from a string: the same seed gives the same table in every
     browser. */
  function rng(seed = 'smui') {
    let h = 1779033703 ^ String(seed).length;
    for (let i = 0; i < String(seed).length; i++) { h = Math.imul(h ^ String(seed).charCodeAt(i), 3432918353); h = (h << 13) | (h >>> 19); }
    const next = () => { h = Math.imul(h ^ (h >>> 16), 2246822507); h = Math.imul(h ^ (h >>> 13), 3266489909); return (h ^= h >>> 16) >>> 0; };
    let a = next(), b = next(), c = next(), d = next();
    const u = () => {
      a >>>= 0; b >>>= 0; c >>>= 0; d >>>= 0;
      let t = (a + b) | 0; a = b ^ (b >>> 9); b = (c + (c << 3)) | 0; c = (c << 21) | (c >>> 11); d = (d + 1) | 0; t = (t + d) | 0; c = (c + t) | 0;
      return (t >>> 0) / 4294967296;
    };
    let spare = null;
    const normal = (mu = 0, sd = 1) => {
      if (spare != null) { const z = spare; spare = null; return mu + sd * z; }
      let x, y, r;
      do { x = 2 * u() - 1; y = 2 * u() - 1; r = x * x + y * y; } while (r >= 1 || r === 0);
      const f = Math.sqrt(-2 * Math.log(r) / r);
      spare = y * f;
      return mu + sd * x * f;
    };
    const pick = (arr) => arr[Math.floor(u() * arr.length)];
    const int = (lo, hi) => lo + Math.floor(u() * (hi - lo + 1));
    return { u, normal, pick, int };
  }

  /* ---- odds and ends -------------------------------------------------------- */
  let uidN = 0;
  const uid = (p = 'sm') => `${p}${++uidN}`;

  function debounce(fn, ms) {
    let t = null;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }

  function download(name, data, type = 'text/plain') {
    const blob = data instanceof Blob ? data : new Blob([data], { type });
    const a = el('a', { href: URL.createObjectURL(blob), download: name });
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  /* A Python string literal for generated code. */
  const pyStr = (s) => JSON.stringify(String(s));

  /* Column names in a patsy formula: Q("...") unless a plain identifier
     that is neither a Python keyword nor patsy's C, I or Q. */
  const PY_KEYWORDS = new Set(['False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except',
    'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield', 'C', 'I', 'Q']);
  const q = (name) => (/^[A-Za-z_][A-Za-z0-9_]*$/.test(name) && !PY_KEYWORDS.has(name) ? name : `Q(${pyStr(name)})`);

  function quantileSorted(sorted, p) {
    const n = sorted.length;
    if (!n) return NaN;
    const h = (n - 1) * p;
    const lo = Math.floor(h);
    return lo + 1 < n ? sorted[lo] + (h - lo) * (sorted[lo + 1] - sorted[lo]) : sorted[lo];
  }

  function themeColors() {
    const css = getComputedStyle(document.documentElement);
    const v = (name, fb) => (css.getPropertyValue(name).trim() || fb);
    return {
      text: v('--text-primary', '#352921'), muted: v('--text-muted', '#786b5d'), grid: v('--border-color', '#e0d7ce'),
      surface: v('--bg-surface', '#fcf7f2'), accent: v('--color-kvot-accent', '#bb6c5d'),
      bright: v('--color-kvot-bright', '#f3b87b'), link: v('--link-color', '#a8503f'),
      dark: document.documentElement.getAttribute('data-theme') === 'dark',
    };
  }

  /* A qualitative palette readable on both themes, for groups and levels. */
  const PALETTE = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd'];

  /* The standard normal quantile (Acklam's rational approximation, relative
     error below 1.2e-9) and distribution function (erfc by Numerical
     Recipes' Chebyshev fit, 1.2e-7). Enough for plotting positions and
     saved scores; the tests themselves are computed in Python. */
  function qnorm(p) {
    if (!(p > 0 && p < 1)) return p === 0 ? -Infinity : p === 1 ? Infinity : NaN;
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.3577518672690, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    const lo = 0.02425;
    let q, r;
    if (p < lo) { q = Math.sqrt(-2 * Math.log(p)); return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    if (p > 1 - lo) { q = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    q = p - 0.5; r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }

  function pnorm(x) {
    const z = Math.abs(x) / Math.SQRT2;
    const t = 1 / (1 + 0.5 * z);
    const erfc = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
    return x >= 0 ? 1 - erfc / 2 : erfc / 2;
  }

  /* Ranks with ties averaged, 1-based, of an array of numbers. */
  function ranks(x) {
    const idx = x.map((_, i) => i).sort((a, b) => x[a] - x[b]);
    const r = new Array(x.length);
    for (let i = 0; i < idx.length;) {
      let j = i;
      while (j + 1 < idx.length && x[idx[j + 1]] === x[idx[i]]) j++;
      const avg = (i + j) / 2 + 1;
      for (let k = i; k <= j; k++) r[idx[k]] = avg;
      i = j + 1;
    }
    return r;
  }

  /* A row's colour: 0-11 are the palette, 100-163 a blue-grey-red ramp
     (Color by Column on a continuous column). */
  function colorOf(idx) {
    if (idx == null || idx < 0) return null;
    if (idx >= 100) return ramp(Math.min(63, idx - 100) / 63);
    return PALETTE[idx % PALETTE.length];
  }

  function ramp(t) {
    const stops = [[47, 110, 199], [176, 176, 176], [192, 57, 43]];
    const k = t < 0.5 ? 0 : 1;
    const u = t < 0.5 ? t / 0.5 : (t - 0.5) / 0.5;
    const a = stops[k], b = stops[k + 1];
    const c = a.map((v, i) => Math.round(v + u * (b[i] - v)));
    return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
  }

  SM.util = Object.freeze({
    Emitter, fmt, fmtP, fmtPct, el, svg, typeIcon, TYPE_LABEL, rng, uid, debounce, download, pyStr, q, quantileSorted,
    themeColors, PALETTE, colorOf, ramp, qnorm, pnorm, ranks,
  });
}(typeof self !== 'undefined' ? self : this));
