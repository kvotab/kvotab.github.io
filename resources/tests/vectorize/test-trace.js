#!/usr/bin/env node
/* vectorize.html's engine, in Node: resources/js/vectorize-trace.js against
   images drawn in the test, with no page and no browser.

       node resources/tests/vectorize/test-trace.js

   Exit status 0 when every check passes. */
'use strict';

const path = require('path');
const V = require(path.join(__dirname, '../../js/vectorize-trace.js'));

let checks = 0;
const failures = [];
function check(label, ok, detail) {
  checks++;
  if (!ok) failures.push(label);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail === undefined ? '' : ': ' + detail}`);
}

/* An RGBA image whose grey is 1 - coverage, coverage from inkAt(x, y) on an
   ss × ss grid inside each pixel (ss = 1: hard pixel edges, no antialiasing). */
function image(w, h, inkAt, ss = 4, grey = 0) {
  const rgba = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let c = 0;
      for (let j = 0; j < ss; j++) for (let i = 0; i < ss; i++) {
        if (inkAt(x + (i + 0.5) / ss, y + (j + 0.5) / ss)) c++;
      }
      const v = Math.round(255 - (255 - grey) * c / (ss * ss));
      const o = 4 * (y * w + x);
      rgba[o] = rgba[o + 1] = rgba[o + 2] = v; rgba[o + 3] = 255;
    }
  }
  return { width: w, height: h, rgba };
}

const BASE = { detail: 2, smooth: 0.5, faint: 0, invert: false, threshold: 0.5, specks: 0, tolerance: 0.25, corners: 0 };

function trace(img, p) {
  const q = Object.assign({}, BASE, p);
  const F = V.buildField(img, q, 10e6);
  const loops = V.traceContours(F.P, F.GW, F.GH, q.threshold);
  return Object.assign(V.fitLoops(loops, q, F.sx, F.sy), { loops, F });
}

/* The path's subpaths, each a list of Béziers [x0,y0,x1,y1,x2,y2,x3,y3]. */
function parse(d) {
  const tok = d.match(/[MCZ]|-?\d*\.?\d+(?:e-?\d+)?/g) || [];
  const subs = [];
  let i = 0, cur = null, x = 0, y = 0;
  while (i < tok.length) {
    const t = tok[i++];
    if (t === 'M') { x = +tok[i++]; y = +tok[i++]; cur = []; subs.push(cur); }
    else if (t === 'C') {
      const c = [x, y, +tok[i++], +tok[i++], +tok[i++], +tok[i++], +tok[i++], +tok[i++]];
      cur.push(c); x = c[6]; y = c[7];
    }
  }
  return subs;
}

function at(c, t) {
  const v = 1 - t;
  return [v * v * v * c[0] + 3 * v * v * t * c[2] + 3 * v * t * t * c[4] + t * t * t * c[6],
          v * v * v * c[1] + 3 * v * v * t * c[3] + 3 * v * t * t * c[5] + t * t * t * c[7]];
}

function samples(subs, per = 24) {
  const out = [];
  for (const s of subs) for (const c of s) for (let k = 0; k < per; k++) out.push(at(c, k / per));
  return out;
}

/* Rasterise the path at pixel centres with the nonzero rule, as a browser
   fills it. */
function rasterise(d, w, h) {
  const edges = [];
  for (const s of parse(d)) for (const c of s) {
    let p = at(c, 0);
    for (let k = 1; k <= 16; k++) { const q = at(c, k / 16); edges.push([p[0], p[1], q[0], q[1]]); p = q; }
  }
  const ink = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const yc = y + 0.5, xs = [];
    for (const [x0, y0, x1, y1] of edges) {
      if ((y0 <= yc) === (y1 <= yc)) continue;
      xs.push([x0 + (yc - y0) * (x1 - x0) / (y1 - y0), y1 > y0 ? 1 : -1]);
    }
    xs.sort((a, b) => a[0] - b[0]);
    let wind = 0, k = 0;
    for (let x = 0; x < w; x++) {
      const xc = x + 0.5;
      while (k < xs.length && xs[k][0] < xc) wind += xs[k++][1];
      if (wind !== 0) ink[y * w + x] = 1;
    }
  }
  return ink;
}

/* A seeded random source, so the doodle is the same every run. */
function rng(seed) {
  return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

/* A doodle of wavy strokes and rings, lines about `lw` px wide, drawn on a
   2× grid and averaged down, the way a scanned or exported drawing is. */
function doodle(w, h, n, lw, seed) {
  const r = rng(seed), W = 2 * w, H = 2 * h;
  const hi = new Uint8Array(W * H);
  const stamp = (cx, cy, rad) => {
    for (let y = Math.max(0, Math.floor(cy - rad)); y <= Math.min(H - 1, Math.ceil(cy + rad)); y++)
      for (let x = Math.max(0, Math.floor(cx - rad)); x <= Math.min(W - 1, Math.ceil(cx + rad)); x++)
        if ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= rad * rad) hi[y * W + x] = 1;
  };
  for (let s = 0; s < n; s++) {
    const cx = r() * W, cy = r() * H, size = (0.03 + r() * 0.15) * W, rad = lw;
    if (r() < 0.4) {
      for (let a = 0; a < 2 * Math.PI; a += 0.5 / size) stamp(cx + size * Math.cos(a), cy + size * 0.7 * Math.sin(a), rad);
    } else {
      const ang = r() * Math.PI, f = 1 + r() * 3, amp = size * 0.2 * r();
      for (let t = -1; t <= 1; t += 0.5 / size) {
        const along = t * size, off = amp * Math.sin(f * t * Math.PI);
        stamp(cx + along * Math.cos(ang) - off * Math.sin(ang), cy + along * Math.sin(ang) + off * Math.cos(ang), rad);
      }
    }
  }
  const rgba = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = 2 * y * W + 2 * x;
    const c = hi[i] + hi[i + 1] + hi[i + W] + hi[i + W + 1];
    const o = 4 * (y * w + x);
    rgba[o] = rgba[o + 1] = rgba[o + 2] = 255 - Math.round(255 * c / 4); rgba[o + 3] = 255;
  }
  return { width: w, height: h, rgba };
}

// ── A ring: two outlines, wound opposite ways, on the right radii ─────────────
{
  const img = image(100, 100, (x, y) => { const d = Math.hypot(x - 50, y - 50); return d >= 30 && d <= 40; });
  const r = trace(img, {});
  check('ring: two outlines', r.shapes === 2, `${r.shapes}`);
  check('ring: outline and hole wind opposite ways',
    r.loops.length === 2 && Math.sign(r.loops[0].area) === -Math.sign(r.loops[1].area));
  const rad = samples(parse(r.d)).map(([x, y]) => Math.hypot(x - 50, y - 50));
  const off = Math.max(...rad.map(v => Math.min(Math.abs(v - 30), Math.abs(v - 40))));
  check('ring: curves within 0.3 px of the true circles', off < 0.3, `${off.toFixed(3)} px`);
  check('ring: a handful of curves, not hundreds', r.curves <= 24, `${r.curves}`);
}

// ── A hard-edged circle: smoothing takes the pixel steps out ──────────────────
{
  const img = image(48, 48, (x, y) => Math.hypot(x - 24, y - 24) <= 15, 1);
  const dev = (p) => {
    const r = trace(img, p);
    const rad = samples(parse(r.d)).map(([x, y]) => Math.hypot(x - 24, y - 24));
    const mean = rad.reduce((a, b) => a + b, 0) / rad.length;
    return { spread: Math.max(...rad) - Math.min(...rad), curves: r.curves, mean };
  };
  // A tight curve tolerance for both, so the spread is the outline's own and
  // not the fit's.
  const raw = dev({ smooth: 0, tolerance: 0.1 }), smooth = dev({ smooth: 1, tolerance: 0.1 });
  check('pixel circle: smoothed outline is round (radius spread under 0.3 px)', smooth.spread < 0.3,
    `${smooth.spread.toFixed(3)} px with smoothing, ${raw.spread.toFixed(3)} px without`);
  check('pixel circle: smoothing needs fewer curves', smooth.curves < raw.curves, `${smooth.curves} vs ${raw.curves}`);
  check('pixel circle: smoothing keeps the size (mean radius within 0.5 px of 15)', Math.abs(smooth.mean - 15) < 0.5,
    `${smooth.mean.toFixed(3)} px`);
}

// ── Faint lines: kept unbroken, at their own width, on grainy grey paper ─────
/* Grain of ±amp grey levels over the whole image, the same every run. */
function grain(img, amp, seed) {
  const r = rng(seed);
  for (let i = 0; i < img.rgba.length; i += 4) {
    const v = Math.max(0, Math.min(255, img.rgba[i] + Math.round((r() * 2 - 1) * amp)));
    img.rgba[i] = img.rgba[i + 1] = img.rgba[i + 2] = v;
  }
  return img;
}
{
  // A 1.2 px line at grey 200 -- a fifth of black -- with grain on it.
  const img = grain(image(80, 40, (x, y) => Math.abs((y - 20) - 0.3 * (x - 40)) < 0.6 && x > 10 && x < 70, 4, 200), 10, 3);
  const plain = trace(img, { faint: 0, specks: 4 }), lifted = trace(img, { faint: 70, smooth: 0.7, specks: 4 });
  check('faint line: gone without Faint lines', plain.shapes === 0, `${plain.shapes}`);
  check('faint line: one unbroken shape with Faint lines', lifted.shapes === 1, `${lifted.shapes}`);
}
{
  // A black and a light grey line, both 2 px wide: lifted, they trace alike.
  const img = image(100, 60, (x, y) => x > 10 && x < 90 && (Math.abs(y - 20) < 1 || Math.abs(y - 40) < 1), 4, 0);
  for (let y = 30; y < 60; y++) for (let x = 0; x < 100; x++) {
    const o = 4 * (y * 100 + x), v = 255 - Math.round((255 - img.rgba[o]) * 0.3);
    img.rgba[o] = img.rgba[o + 1] = img.rgba[o + 2] = v;
  }
  const r = trace(img, { faint: 70, smooth: 0.7 });
  const areas = r.loops.map(l => Math.abs(l.area)).sort((a, b) => a - b);
  check('faint line: as wide as a black one of the same width (area within 25 %)',
    areas.length === 2 && areas[1] / areas[0] < 1.25, areas.map(a => (a / 4).toFixed(0)).join(' vs ') + ' px²');
}
{
  // Grey, grainy paper (grey 225 ± 12) with one black disc on it.
  const img = grain(image(120, 90, (x, y) => Math.hypot(x - 60, y - 45) < 12, 4, 0), 12, 5);
  for (let i = 0; i < img.rgba.length; i += 4) {
    const v = Math.round(img.rgba[i] * 225 / 255);
    img.rgba[i] = img.rgba[i + 1] = img.rgba[i + 2] = v;
  }
  const r = trace(img, { faint: 70, smooth: 0.7, specks: 4 });
  check('grey paper: the paper stays paper, the disc is one shape', r.shapes === 1, `${r.shapes}`);
}

// ── Corners: kept when asked for, rounded when not ────────────────────────────
{
  const img = image(100, 100, (x, y) => x >= 30 && x <= 70 && y >= 30 && y <= 70, 4);
  const near = (r) => {
    const ends = parse(r.d).flatMap(s => s.map(c => [c[6], c[7]]));
    return [[30, 30], [70, 30], [70, 70], [30, 70]].map(([cx, cy]) =>
      Math.min(...ends.map(([x, y]) => Math.hypot(x - cx, y - cy))));
  };
  const sharp = near(trace(img, { corners: 70, smooth: 0.3 }));
  check('square: a node within 0.6 px of every corner with corners on', Math.max(...sharp) < 0.6,
    sharp.map(v => v.toFixed(2)).join(', '));
  const soft = trace(img, { corners: 0, smooth: 0.3 });
  check('square: still one closed shape with corners off', soft.shapes === 1, `${soft.shapes}`);
}

// ── Specks are dropped by area, light-on-dark by invert ───────────────────────
{
  const img = image(60, 60, (x, y) => Math.hypot(x - 15, y - 15) < 1.2 || Math.hypot(x - 40, y - 40) < 10);
  check('specks: the dot goes, the disc stays', trace(img, { specks: 20 }).shapes === 1);
  check('specks: both kept at 0', trace(img, { specks: 0 }).shapes === 2);
  const neg = image(60, 60, (x, y) => !(Math.hypot(x - 30, y - 30) < 12));
  check('invert: a white disc on black traces as one shape', trace(neg, { invert: true }).shapes === 1);
}

// ── Saddles: a checkerboard closes every outline ──────────────────────────────
{
  const img = image(64, 64, (x, y) => ((Math.floor(x / 8) + Math.floor(y / 8)) & 1) === 1, 1);
  let ok = true, r;
  try { r = trace(img, { smooth: 0, detail: 1 }); } catch (e) { ok = false; }
  check('checkerboard: every outline closes', ok && r.shapes > 0, ok ? `${r.shapes} shapes` : 'threw');
}

// ── The whole picture: the fill matches the drawing, and in good time ─────────
{
  const img = doodle(1080, 810, 160, 1.6, 7);
  const t0 = Date.now();
  // The line-art preset's settings (line weight 45 %).
  const r = trace(img, { detail: 3, smooth: 0.7, faint: 70, threshold: 0.55, specks: 4, tolerance: 0.5, corners: 15 });
  const ms = Date.now() - t0;
  const ink = rasterise(r.d, 1080, 810);
  // The drawing's own ink: pixels at least half covered.
  let both = 0, either = 0;
  for (let i = 0; i < ink.length; i++) {
    const src = (255 - img.rgba[4 * i]) / 255 > 0.5 ? 1 : 0;
    if (src && ink[i]) both++;
    if (src || ink[i]) either++;
  }
  const iou = both / either;
  check('doodle: filled area matches the drawing (overlap over 0.84)', iou > 0.84, iou.toFixed(3));
  check('doodle: 1080 × 810 at 3× detail in under 15 s', ms < 15000, `${(ms / 1000).toFixed(1)} s, ${r.shapes} shapes, ${r.curves} curves, ${(r.d.length / 1024).toFixed(0)} kB`);
}

console.log(`\n${checks - failures.length}/${checks} checks passed`);
if (failures.length) { console.log('Failed:\n  ' + failures.join('\n  ')); process.exit(1); }
