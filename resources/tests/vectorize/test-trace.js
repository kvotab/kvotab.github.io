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

// ── Black lines only: a coloured cartoon ──────────────────────────────────────

/* A colour image from colourAt(x, y) -> [r, g, b] averaged on an ss × ss grid
   in each pixel, with the share of each pixel that is black ink (truth). */
function colourImage(w, h, colourAt, ss = 4) {
  const rgba = new Uint8ClampedArray(w * h * 4), truth = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let r = 0, g = 0, b = 0, k = 0;
    for (let j = 0; j < ss; j++) for (let i = 0; i < ss; i++) {
      const c = colourAt(x + (i + 0.5) / ss, y + (j + 0.5) / ss);
      r += c[0]; g += c[1]; b += c[2];
      if (c.black) k++;
    }
    const o = 4 * (y * w + x), n = ss * ss;
    rgba[o] = Math.round(r / n); rgba[o + 1] = Math.round(g / n); rgba[o + 2] = Math.round(b / n); rgba[o + 3] = 255;
    truth[y * w + x] = k / n;
  }
  return { width: w, height: h, rgba, truth };
}

/* The colour of a JPEG with 4:2:0 subsampling: brightness kept pixel by
   pixel, colour averaged over 2 × 2 blocks. */
function chromaBleed(img) {
  const { width: w, height: h, rgba } = img, out = new Uint8ClampedArray(rgba);
  const Y = (o) => 0.299 * rgba[o] + 0.587 * rgba[o + 1] + 0.114 * rgba[o + 2];
  for (let by = 0; by < h; by += 2) for (let bx = 0; bx < w; bx += 2) {
    let cb = 0, cr = 0, n = 0;
    for (let y = by; y < Math.min(h, by + 2); y++) for (let x = bx; x < Math.min(w, bx + 2); x++) {
      const o = 4 * (y * w + x), yy = Y(o);
      cb += 0.564 * (rgba[o + 2] - yy); cr += 0.713 * (rgba[o] - yy); n++;
    }
    cb /= n; cr /= n;
    for (let y = by; y < Math.min(h, by + 2); y++) for (let x = bx; x < Math.min(w, bx + 2); x++) {
      const o = 4 * (y * w + x), yy = Y(o);
      out[o] = yy + 1.402 * cr; out[o + 1] = yy - 0.344 * cb - 0.714 * cr; out[o + 2] = yy + 1.772 * cb;
    }
  }
  return Object.assign({}, img, { rgba: out });
}

const BLACK = Object.assign([0, 0, 0], { black: true });
/* A cartoon: flat fills of every kind with black outlines, a solid black
   disc, a thin black fold line across the red, and a thin dark blue line,
   not black, on the white. Regions name each fill's inside, away from any
   black, for the checks. */
const CARTOON_FILLS = {
  red: { c: [220, 30, 30], inside: (x, y) => x > 18 && x < 62 && y > 18 && y < 62 && Math.abs(x - 40 - 0.25 * (y - 40)) > 3 },
  navy: { c: [20, 30, 90], inside: (x, y) => Math.hypot(x - 105, y - 40) < 17 },
  brown: { c: [70, 40, 20], inside: (x, y) => ((x - 160) / 22) ** 2 + ((y - 40) / 14) ** 2 < 0.7 },
  grey: { c: [128, 128, 128], inside: (x, y) => x > 18 && x < 62 && y > 88 && y < 122 },
  darkgrey: { c: [80, 80, 80], inside: (x, y) => Math.hypot(x - 105, y - 105) < 14 },
};
function cartoonAt(x, y) {
  const ring = (d, r, lw) => d <= r && d >= r - lw;
  // Red square, outlined 3 px, with a fold line 1.2 px wide across it.
  if (x >= 12 && x <= 68 && y >= 12 && y <= 68) {
    if (x < 15 || x > 65 || y < 15 || y > 65) return BLACK;
    if (Math.abs(x - 40 - 0.25 * (y - 40)) < 0.6 && y > 22 && y < 58) return BLACK;
    return CARTOON_FILLS.red.c;
  }
  const dn = Math.hypot(x - 105, y - 40);
  if (ring(dn, 24, 2.5)) return BLACK;
  if (dn < 21.5) return CARTOON_FILLS.navy.c;
  const de = Math.hypot((x - 160) / 28, (y - 40) / 18);
  if (de <= 1 && de >= 1 - 2.5 / 18) return BLACK;
  if (de < 1) return CARTOON_FILLS.brown.c;
  if (x >= 12 && x <= 68 && y >= 82 && y <= 128) {
    if (x < 15 || x > 65 || y < 85 || y > 125) return BLACK;
    return CARTOON_FILLS.grey.c;
  }
  const dg = Math.hypot(x - 105, y - 105);
  if (ring(dg, 20, 2.5)) return BLACK;
  if (dg < 17.5) return CARTOON_FILLS.darkgrey.c;
  if (Math.hypot(x - 160, y - 105) < 8) return BLACK;                   // a solid black disc
  if (x > 140 && x < 185 && Math.abs(y - 125 - 0.1 * (x - 160)) < 1) return [20, 30, 110]; // dark blue line
  return [255, 255, 255];
}
{
  const LINEART = { detail: 2, smooth: 0.7, faint: 70, threshold: 0.55 };
  const score = (img, F) => {
    const { width: w, height: h } = img;
    let tp = 0, fp = 0, fn = 0;
    const inside = {};
    for (const k of Object.keys(CARTOON_FILLS)) inside[k] = [0, 0];
    let blue = 0;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const gx = Math.round((x + 0.5) * F.sx - 0.5) + 1, gy = Math.round((y + 0.5) * F.sy - 0.5) + 1;
      const ink = F.P[gy * F.GW + gx] > LINEART.threshold, tr = img.truth[y * w + x] > 0.5;
      if (ink && tr) tp++; else if (ink) fp++; else if (tr) fn++;
      for (const [k, f] of Object.entries(CARTOON_FILLS)) if (f.inside(x + 0.5, y + 0.5)) { inside[k][1]++; if (ink) inside[k][0]++; }
      if (ink && x > 142 && x < 183 && Math.abs(y + 0.5 - 125 - 0.1 * (x + 0.5 - 160)) < 1.5) blue++;
    }
    return { iou: tp / (tp + fp + fn), inside, blue };
  };
  for (const [label, img] of [['clean', colourImage(200, 140, cartoonAt)], ['JPEG colour', chromaBleed(colourImage(200, 140, cartoonAt))]]) {
    const dark = score(img, V.buildField(img, LINEART, 10e6));
    const black = score(img, V.buildField(img, Object.assign({ black: true }, LINEART), 10e6));
    if (label === 'clean') {
      check('cartoon: traced by darkness, the dark fills come out as solid ink', dark.inside.navy[0] / dark.inside.navy[1] > 0.9 &&
        dark.inside.brown[0] / dark.inside.brown[1] > 0.9, `navy ${dark.inside.navy[0]}/${dark.inside.navy[1]}, brown ${dark.inside.brown[0]}/${dark.inside.brown[1]}`);
    }
    const filled = Object.entries(black.inside).filter(([, v]) => v[0] > 0).map(([k, v]) => `${k} ${v[0]}/${v[1]}`);
    check(`cartoon, ${label}: black lines only leaves every fill as paper (red, navy, brown, grey, dark grey)`, !filled.length, filled.join(', ') || 'none inked');
    check(`cartoon, ${label}: black lines only traces the black lines (overlap over 0.8)`, black.iou > 0.8, black.iou.toFixed(3));
    check(`cartoon, ${label}: a dark blue line on white is not black`, black.blue === 0, `${black.blue} px inked`);
  }
  // The fold line, 1.2 px wide on red, comes out unbroken; the black disc keeps its size.
  const img = chromaBleed(colourImage(200, 140, cartoonAt));
  const q = Object.assign({ black: true }, LINEART);
  const F = V.buildField(img, q, 10e6);
  let gaps = 0;
  for (let y = 24; y <= 56; y += 0.5) {
    const x = 40 + 0.25 * (y - 40);
    if (!(F.P[Math.round(y * F.sy + 0.5) * F.GW + Math.round(x * F.sx + 0.5)] > q.threshold)) gaps++;
  }
  check('cartoon: a thin black fold line across a colour comes out unbroken', gaps === 0, `${gaps} gaps`);
  const loops = V.traceContours(F.P, F.GW, F.GH, q.threshold);
  const disc = loops.map(l => l.pts).filter(p => Math.abs(p[0] - (160 * F.sx + 0.5)) < 12 * F.sx && Math.abs(p[1] - (97 * F.sy + 0.5)) < 4 * F.sy);
  const area = loops.filter(l => Math.abs(l.pts[0] - (160 * F.sx + 0.5)) < 12 * F.sx && Math.abs(l.pts[1] - (97 * F.sy + 0.5)) < 4 * F.sy)
    .reduce((s, l) => s + Math.abs(l.area), 0) / (F.sx * F.sy);
  // Its edge is measured against the white just outside it, so it is cut
  // where it is half black; against the floor, it came out 6.5 % small.
  check('cartoon: a solid black disc keeps its area (within 5 %)', disc.length === 1 && Math.abs(area / (Math.PI * 64) - 1) < 0.05,
    `${area.toFixed(0)} px² against ${(Math.PI * 64).toFixed(0)}`);
  // Transparency is paper, in this mode too.
  const clear = image(40, 40, (x, y) => Math.hypot(x - 20, y - 20) < 8);
  for (let i = 0; i < clear.rgba.length; i += 4) if (clear.rgba[i] > 128) clear.rgba[i + 3] = 0;
  check('black lines only: a transparent background is paper', trace(clear, { black: true }).shapes === 1);
}

// ── Pieces: an outline and its holes are one piece ────────────────────────────
{
  // A ring, a disc in its hole, and a dot apart.
  const img = image(100, 100, (x, y) => {
    const d = Math.hypot(x - 45, y - 45);
    return (d >= 25 && d <= 33) || d <= 10 || Math.hypot(x - 88, y - 88) < 4;
  });
  const r = trace(img, {});
  const T = V.labelInk(r.F.P, r.F.GW, r.F.GH, BASE.threshold);
  const labs = r.loops.map(l => T.labels[l.ink]);
  check('pieces: three, for four outlines', T.count === 3 && r.loops.length === 4, `${T.count} pieces, ${r.loops.length} outlines`);
  const byArea = r.loops.map((l, i) => [Math.abs(l.area), labs[i], Math.sign(l.area)]).sort((a, b) => b[0] - a[0]);
  check('pieces: the ring\'s outline and its hole are one piece, the disc in the hole another',
    byArea[0][1] === byArea[1][1] && byArea[0][2] === -byArea[1][2] && byArea[2][1] !== byArea[0][1], JSON.stringify(labs));
  const seedInk = [1, 2, 3].every(k => r.F.P[T.seed[k]] > BASE.threshold && T.labels[T.seed[k]] === k);
  check('pieces: each seed is ink of its own piece', seedInk);
  // Saddles: the pieces join where the outlines do.
  const cb = image(64, 64, (x, y) => ((Math.floor(x / 8) + Math.floor(y / 8)) & 1) === 1, 1);
  const rc = trace(cb, { smooth: 0, detail: 1 });
  const Tc = V.labelInk(rc.F.P, rc.F.GW, rc.F.GH, BASE.threshold);
  const outer = new Map();
  for (const l of rc.loops) if (l.area < 0) outer.set(Tc.labels[l.ink], (outer.get(Tc.labels[l.ink]) || 0) + 1);
  check('pieces: on a checkerboard, every piece has one outer outline', outer.size === Tc.count && [...outer.values()].every(v => v === 1),
    `${Tc.count} pieces, ${outer.size} with an outer outline`);
  // Below half, every corner where four squares meet joins the black ones:
  // one piece, the white squares its holes.
  const loops4 = V.traceContours(rc.F.P, rc.F.GW, rc.F.GH, 0.4);
  const T4 = V.labelInk(rc.F.P, rc.F.GW, rc.F.GH, 0.4);
  const outer4 = loops4.filter(l => l.area < 0).length;
  check('pieces: joined at the corners, a checkerboard is one piece with one outer outline',
    T4.count === 1 && outer4 === 1 && loops4.every(l => T4.labels[l.ink] === 1), `${T4.count} pieces, ${outer4} outer outlines, ${loops4.length} in all`);
}

// ── The runner: removing pieces and erasing ───────────────────────────────────
{
  const posts = [];
  const run = V.makeRunner((m) => posts.push(m));
  // A ring with a disc in its hole, a bar, and a dot.
  const img = image(120, 100, (x, y) => {
    const d = Math.hypot(x - 40, y - 45);
    return (d >= 22 && d <= 30) || d <= 9 || (x >= 80 && x <= 112 && y >= 40 && y <= 50) || Math.hypot(x - 100, y - 85) < 3;
  });
  run({ type: 'source', width: img.width, height: img.height, buffer: img.rgba.slice().buffer });
  const params = (extra) => Object.assign({}, BASE, { specks: 0 }, extra);
  const go = (extra, id) => {
    posts.length = 0;
    run({ type: 'run', id, maxWork: 10e6, params: params(extra) });
    return { res: posts.find(m => m.type === 'result'), stages: posts.filter(m => m.type === 'progress').map(m => m.stage) };
  };
  const first = go({}, 1).res;
  check('runner: four pieces, each with its slice of the path, box and seed',
    first.n === 4 && first.cuts.length === 5 && first.cuts[4] === first.d.length && first.boxes.length === 16 && first.seeds.length === 8, `${first.n} pieces`);
  const pieceOf = (res, x, y) => {
    for (let k = 0; k < res.n; k++) {
      const b = res.boxes.subarray(4 * k, 4 * k + 4);
      if (x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3]) return k;
    }
    return -1;
  };
  // The ring's piece: the largest box.
  let ring = 0;
  for (let k = 1; k < first.n; k++) if (first.boxes[4 * k + 2] - first.boxes[4 * k] > first.boxes[4 * ring + 2] - first.boxes[4 * ring]) ring = k;
  const ringD = first.d.slice(first.cuts[ring], first.cuts[ring + 1]);
  check('runner: a piece\'s path is its outline and its hole', (ringD.match(/M/g) || []).length === 2, ringD.slice(0, 40) + '…');
  const seed = [first.seeds[2 * ring], first.seeds[2 * ring + 1]];
  const removed = go({ removed: [seed] }, 2);
  check('runner: removing by the seed takes the ring, hole and all, and leaves the disc in it', removed.res.n === 3 &&
    removed.res.removed === 1 && !removed.res.d.includes(ringD) && pieceOf(removed.res, 40, 45) >= 0, `${removed.res.n} pieces`);
  check('runner: removing a piece only puts the drawing together again', removed.stages.join() === 'Fitting curves', removed.stages.join(', '));
  const nearEdge = go({ removed: [[40 + 22.4, 45]] }, 3).res;
  check('runner: a point at the edge of the ink finds the piece too', nearEdge.n === 3 && nearEdge.removed === 1, `${nearEdge.n} pieces`);
  check('runner: a point on the paper removes nothing', go({ removed: [[60, 10]] }, 4).res.n === 4);
  const thinner = go({ removed: [seed], threshold: 0.8 }, 5).res;
  check('runner: the removed piece stays removed with thinner lines', thinner.n === 3 && thinner.removed === 1, `${thinner.n} pieces`);
  // Erase a band across the bar: it falls in two, cut where the stroke ran.
  const before = go({}, 6).res;
  const keep = before.d.slice(before.cuts[pieceOf(before, 40, 45)], before.cuts[pieceOf(before, 40, 45) + 1]);
  const cut = go({ erase: [{ r: 3, pts: [96, 30, 96, 60] }], eraseKey: 'a' }, 7);
  const bars = [];
  for (let k = 0; k < cut.res.n; k++) if (cut.res.boxes[4 * k + 1] >= 38 && cut.res.boxes[4 * k + 3] <= 52) bars.push(cut.res.boxes.slice(4 * k, 4 * k + 4));
  bars.sort((a, b) => a[0] - b[0]);
  check('runner: erasing across the bar cuts it in two', cut.res.n === 5 && bars.length === 2, `${cut.res.n} pieces`);
  check('runner: the cut follows the stroke (edges within 0.5 px of 93 and 99)', bars.length === 2 &&
    Math.abs(bars[0][2] - 93) < 0.5 && Math.abs(bars[1][0] - 99) < 0.5, bars.map(b => `${b[0].toFixed(2)}..${b[2].toFixed(2)}`).join(', '));
  check('runner: an outline the stroke did not touch keeps its curves exactly', cut.res.d.includes(keep));
  const back = go({}, 8).res;
  check('runner: no strokes, the bar whole again', back.n === 4 && back.d === before.d);
  const loose = go({ tolerance: 2 }, 9).res;
  check('runner: a looser curve fit refits every outline', loose.curves < back.curves && !loose.d.includes(keep), `${loose.curves} curves against ${back.curves}`);
}
{
  // A slanted stroke across a square's corner: the cut is as straight as
  // the stroke's edge, not stepped by the samples (a hard-edged eraser was
  // 0.5 px off, in 71 curves).
  const posts = [], run = V.makeRunner((m) => posts.push(m));
  const img = image(100, 100, (x, y) => x >= 20 && x <= 80 && y >= 20 && y <= 80);
  run({ type: 'source', width: 100, height: 100, buffer: img.rgba.slice().buffer });
  const R = 4, x0 = 0, y0 = 70, x1 = 100, y1 = 70 - 100 * Math.tan(25 * Math.PI / 180);
  run({ type: 'run', id: 1, maxWork: 10e6, params: Object.assign({}, BASE, { erase: [{ r: R, pts: [x0, y0, x1, y1] }], eraseKey: 's' }) });
  const res = posts.find(m => m.type === 'result');
  const nx = y0 - y1, ny = x1 - x0, nl = Math.hypot(nx, ny);
  let worst = 0, n = 0;
  for (const [px, py] of samples(parse(res.d), 32)) {
    if (px < 26 || px > 74 || py < 26 || py > 74) continue;
    const dist = Math.abs((px - x0) * nx + (py - y0) * ny) / nl;
    if (dist < R + 2) { n++; worst = Math.max(worst, Math.abs(dist - R)); }
  }
  check('erasing: a slanted cut follows the stroke\'s edge (within 0.3 px) in few curves', res.n === 2 && n > 50 && worst < 0.3 && res.curves < 40,
    `${res.n} pieces, ${worst.toFixed(3)} px off, ${res.curves} curves`);
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
