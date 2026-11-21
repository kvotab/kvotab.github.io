/*
  vectorize-trace.js -- the tracing engine of vectorize.html.

  It turns a raster image into filled outlines drawn with smooth curves, as
  SVG path data, in four steps:

    1. An ink field. How dark each pixel is (how light, for light lines on a
       dark ground), on an enlarged copy of the image, with faint lines
       darkened and the whole lightly blurred. The blur is what takes away the
       pixel steps and the compression noise that make a traced line jagged.
    2. Outlines. Marching squares follows the field's contour at the
       threshold, placing each crossing between two pixels by linear
       interpolation, so the outlines are not tied to the pixel grid.
    3. Corners. Where an outline turns more sharply than the corner setting
       allows, the point is kept as a corner; everywhere else the curve runs
       smoothly through it.
    4. Curves. Between corners, Schneider's least-squares fit (Graphics Gems,
       1990) lays as few cubic Béziers along the points as keep within the
       curve tolerance, each leaving in the direction the last one arrived.

  The outlines run with the ink on their left, so an outline and the holes
  inside it wind opposite ways and the default nonzero fill rule draws them
  right, even where fitting has nudged two outlines across each other.

  The file runs as a Web Worker (vectorize.js starts it). Loaded in Node, for
  resources/tests/vectorize, it exports its functions instead.
*/
'use strict';

(function () {

  // ── 1. The ink field ──────────────────────────────────────────────────────

  /* Darkness 0..1 of every pixel; a transparent pixel counts as background. */
  function inkOf(rgba, sw, sh, invert) {
    const n = sw * sh;
    const ink = new Float32Array(n);
    const bg = invert ? 0 : 1;
    for (let i = 0, j = 0; i < n; i++, j += 4) {
      const a = rgba[j + 3] / 255;
      const l = (0.2126 * rgba[j] + 0.7152 * rgba[j + 1] + 0.0722 * rgba[j + 2]) / 255;
      const v = l * a + bg * (1 - a);
      ink[i] = invert ? v : 1 - v;
    }
    return ink;
  }

  /* Bilinear resampling, sampling at pixel centres. */
  function resample(src, sw, sh, ww, wh) {
    const out = new Float32Array(ww * wh);
    const kx = sw / ww, ky = sh / wh;
    const x0 = new Int32Array(ww), x1 = new Int32Array(ww), fx = new Float32Array(ww);
    for (let x = 0; x < ww; x++) {
      let u = (x + 0.5) * kx - 0.5;
      if (u < 0) u = 0; else if (u > sw - 1) u = sw - 1;
      const i = Math.floor(u);
      x0[x] = i; x1[x] = Math.min(i + 1, sw - 1); fx[x] = u - i;
    }
    for (let y = 0; y < wh; y++) {
      let v = (y + 0.5) * ky - 0.5;
      if (v < 0) v = 0; else if (v > sh - 1) v = sh - 1;
      const j = Math.floor(v);
      const r0 = j * sw, r1 = Math.min(j + 1, sh - 1) * sw, fy = v - j, o = y * ww;
      for (let x = 0; x < ww; x++) {
        const a = src[r0 + x0[x]], b = src[r0 + x1[x]];
        const c = src[r1 + x0[x]], d = src[r1 + x1[x]];
        const f = fx[x];
        const top = a + (b - a) * f;
        out[o + x] = top + (c + (d - c) * f - top) * fy;
      }
    }
    return out;
  }

  /* A true Gaussian, separable, edges extended. For small radii. */
  function blurExact(a, w, h, sigma, tmp) {
    const r = Math.max(1, Math.ceil(sigma * 3));
    const k = new Float32Array(2 * r + 1);
    let sum = 0;
    for (let i = -r; i <= r; i++) { const v = Math.exp(-(i * i) / (2 * sigma * sigma)); k[i + r] = v; sum += v; }
    for (let i = 0; i < k.length; i++) k[i] /= sum;
    for (let y = 0; y < h; y++) {
      const o = y * w;
      for (let x = 0; x < w; x++) {
        let acc = 0;
        for (let i = -r; i <= r; i++) {
          let xx = x + i;
          if (xx < 0) xx = 0; else if (xx >= w) xx = w - 1;
          acc += a[o + xx] * k[i + r];
        }
        tmp[o + x] = acc;
      }
    }
    for (let y = 0; y < h; y++) {
      const o = y * w;
      for (let x = 0; x < w; x++) a[o + x] = 0;
      for (let i = -r; i <= r; i++) {
        let yy = y + i;
        if (yy < 0) yy = 0; else if (yy >= h) yy = h - 1;
        const q = yy * w, kk = k[i + r];
        for (let x = 0; x < w; x++) a[o + x] += tmp[q + x] * kk;
      }
    }
  }

  /* One running-sum box blur of radius r along rows (step 1) or columns
     (step w), edges extended. */
  function boxPass(src, dst, w, h, r, horizontal) {
    const len = horizontal ? w : h, lines = horizontal ? h : w;
    const step = horizontal ? 1 : w, lineStep = horizontal ? w : 1;
    const inv = 1 / (2 * r + 1);
    for (let l = 0; l < lines; l++) {
      const o = l * lineStep;
      let acc = 0;
      for (let i = -r; i <= r; i++) acc += src[o + Math.min(Math.max(i, 0), len - 1) * step];
      for (let i = 0; i < len; i++) {
        dst[o + i * step] = acc * inv;
        const add = Math.min(i + r + 1, len - 1), sub = Math.max(i - r, 0);
        acc += src[o + add * step] - src[o + sub * step];
      }
    }
  }

  /* Three box blurs come within a few per cent of a Gaussian, at a cost that
     does not grow with the radius. For large radii. */
  function blurBoxes(a, w, h, sigma, tmp) {
    const n = 3;
    const wIdeal = Math.sqrt(12 * sigma * sigma / n + 1);
    let wl = Math.floor(wIdeal); if (wl % 2 === 0) wl--;
    const wu = wl + 2;
    const m = Math.round((12 * sigma * sigma - n * wl * wl - 4 * n * wl - 3 * n) / (-4 * wl - 4));
    for (let i = 0; i < n; i++) {
      const r = ((i < m ? wl : wu) - 1) / 2;
      boxPass(a, tmp, w, h, r, true);
      boxPass(tmp, a, w, h, r, false);
    }
  }

  function blur(a, w, h, sigma) {
    if (sigma < 0.25) return;
    const tmp = new Float32Array(a.length);
    if (sigma <= 2) blurExact(a, w, h, sigma, tmp);
    else blurBoxes(a, w, h, sigma, tmp);
  }

  /* The largest value within r along rows or columns, edges clamped: a
     running maximum over a queue of falling values, so O(1) a sample. */
  function maxPass(src, dst, w, h, r, horizontal) {
    const len = horizontal ? w : h, lines = horizontal ? h : w;
    const step = horizontal ? 1 : w, lineStep = horizontal ? w : 1;
    const q = new Int32Array(len);
    for (let l = 0; l < lines; l++) {
      const o = l * lineStep;
      let head = 0, tail = 0, next = 0;
      for (let i = 0; i < len; i++) {
        const hi = Math.min(len - 1, i + r);
        for (; next <= hi; next++) {
          const v = src[o + next * step];
          while (tail > head && src[o + q[tail - 1] * step] <= v) tail--;
          q[tail++] = next;
        }
        while (q[head] < i - r) head++;
        dst[o + i * step] = src[o + q[head] * step];
      }
    }
  }

  /* The paper's own darkness: the median, since most of a drawing is paper,
     but never more than 0.3, so a dark image is not wiped out. */
  function paperLevel(ink) {
    const hist = new Uint32Array(256);
    for (let i = 0; i < ink.length; i++) hist[Math.min(255, (ink[i] * 256) | 0)]++;
    let seen = 0, b = 0;
    for (; b < 255; b++) { seen += hist[b]; if (seen * 2 >= ink.length) break; }
    return Math.min(0.3, (b + 0.5) / 256);
  }

  /*
    Faint lines, 0..100. Each line is brought up to full strength by its own
    darkest point nearby (a maximum over r, smoothed), so a light grey line
    and a black one are both cut at half their own strength: the faint one
    stays unbroken and no thinner than it looks. The floor stops the paper's
    grain from being brought up the same way; the stronger the setting, the
    fainter the lines it reaches.
  */
  function liftFaint(a, w, h, faint, r) {
    const f = Math.min(1, Math.max(0, faint / 100));
    const floor = 0.03 + 0.97 * (1 - f) * (1 - f);
    const M = new Float32Array(a.length), tmp = new Float32Array(a.length);
    maxPass(a, tmp, w, h, r, true);
    maxPass(tmp, M, w, h, r, false);
    boxPass(M, tmp, w, h, r, true);
    boxPass(tmp, M, w, h, r, false);
    for (let i = 0; i < a.length; i++) {
      const v = a[i] / (M[i] > floor ? M[i] : floor);
      a[i] = v > 1 ? 1 : v;
    }
  }

  /* Otsu's threshold over the field: the split that best separates ink from
     paper. */
  function otsu(a) {
    const hist = new Float64Array(256);
    for (let i = 0; i < a.length; i++) {
      let b = (a[i] * 256) | 0;
      if (b > 255) b = 255; else if (b < 0) b = 0;
      hist[b]++;
    }
    let total = 0, sum = 0;
    for (let i = 0; i < 256; i++) { total += hist[i]; sum += i * hist[i]; }
    let wB = 0, sumB = 0, best = -1, at = 127;
    for (let i = 0; i < 255; i++) {
      wB += hist[i];
      if (!wB) continue;
      const wF = total - wB;
      if (!wF) break;
      sumB += i * hist[i];
      const d = sumB / wB - (sum - sumB) / wF;
      const between = wB * wF * d * d;
      if (between > best) { best = between; at = i; }
    }
    return (at + 1) / 256;
  }

  /*
    The field, enlarged by p.detail (held under maxWork pixels in all), with a
    one-sample border of zero all round so every outline closes inside it.
    Sample (gx, gy) of the padded grid sits at source coordinate
    ((gx - 0.5) / sx, (gy - 0.5) / sy).

    With faint lines on, the paper's own tone is taken off first (a grey
    scan's paper is not ink), and the lines are lifted after the smoothing,
    so it is the smoothed line whose strength is measured.
  */
  function buildField(src, p, maxWork) {
    const sw = src.width, sh = src.height;
    let s = Math.max(0.05, +p.detail || 1);
    const cap = Math.sqrt((maxWork || 10e6) / (sw * sh));
    if (s > cap) s = cap;
    const ww = Math.max(1, Math.round(sw * s)), wh = Math.max(1, Math.round(sh * s));
    const smooth = +p.smooth || 0, faint = +p.faint || 0;
    const ink = inkOf(src.rgba, sw, sh, !!p.invert);
    if (faint > 0) {
      const paper = paperLevel(ink), k = 1 / (1 - paper);
      for (let i = 0; i < ink.length; i++) { const v = (ink[i] - paper) * k; ink[i] = v > 0 ? v : 0; }
    }
    const a = (ww === sw && wh === sh) ? ink : resample(ink, sw, sh, ww, wh);
    blur(a, ww, wh, smooth * s);
    if (faint > 0) liftFaint(a, ww, wh, faint, Math.max(2, Math.round((2 + 2 * smooth) * s)));
    const GW = ww + 2, GH = wh + 2;
    const P = new Float32Array(GW * GH);
    for (let y = 0; y < wh; y++) P.set(a.subarray(y * ww, (y + 1) * ww), (y + 1) * GW + 1);
    return { P, GW, GH, ww, wh, sx: ww / sw, sy: wh / sh, auto: otsu(a) };
  }

  // ── 2. Outlines: marching squares ─────────────────────────────────────────

  /*
    A cell's corners are numbered clockwise on screen, 0 top-left, 1
    top-right, 2 bottom-right, 3 bottom-left, and its edge k runs from corner
    k to corner k + 1. Walking clockwise round a cell, an edge where the walk
    passes from paper into ink is where an outline enters the cell, and the
    outline leaves by the next edge where the walk passes from ink back to
    paper -- which keeps the ink on the outline's left. In a saddle cell (ink
    at two opposite corners) the cell's centre decides whether the two inks
    join: if they do, the outline leaves by the edge before instead of after.
    Leaving a cell by edge k, the outline enters the next cell by edge k + 2.
  */
  function traceContours(P, GW, GH, t) {
    const ins = new Uint8Array(GW * GH);
    for (let i = 0; i < ins.length; i++) ins[i] = P[i] > t ? 1 : 0;
    const NHW = GW - 1;
    const visited = new Uint8Array(NHW * GH);
    const loops = [];
    let buf = new Float32Array(1 << 15);
    const maxSteps = 4 * GW * GH;

    for (let y = 1; y < GH - 1; y++) {
      for (let x = 0; x < GW - 1; x++) {
        const i = y * GW + x;
        const a = ins[i];
        if (a === ins[i + 1] || visited[y * NHW + x]) continue;
        // The horizontal edge (x, y) is crossed: enter by it from whichever
        // of its two cells sees it as paper-to-ink.
        let cx = x, cy = a ? y - 1 : y, k = a ? 2 : 0;
        const sx = cx, sy = cy, sk = k;
        let n = 0, steps = 0;
        do {
          const i0 = cy * GW + cx;
          const v0 = P[i0], v1 = P[i0 + 1], v2 = P[i0 + GW + 1], v3 = P[i0 + GW];
          let px, py;
          if (k === 0) { px = cx + (t - v0) / (v1 - v0); py = cy; visited[cy * NHW + cx] = 1; }
          else if (k === 1) { px = cx + 1; py = cy + (t - v1) / (v2 - v1); }
          else if (k === 2) { px = cx + 1 - (t - v2) / (v3 - v2); py = cy + 1; visited[(cy + 1) * NHW + cx] = 1; }
          else { px = cx; py = cy + 1 - (t - v3) / (v0 - v3); }
          if (n + 2 > buf.length) { const nb = new Float32Array(buf.length * 2); nb.set(buf); buf = nb; }
          buf[n++] = px; buf[n++] = py;

          const b0 = ins[i0], b1 = ins[i0 + 1], b2 = ins[i0 + GW + 1], b3 = ins[i0 + GW];
          let e;
          if (b0 === b2 && b1 === b3 && b0 !== b1) {
            e = ((v0 + v1 + v2 + v3) * 0.25 > t) ? (k + 3) & 3 : (k + 1) & 3;
          } else if (b0 && !b1) e = 0;
          else if (b1 && !b2) e = 1;
          else if (b2 && !b3) e = 2;
          else e = 3;
          if (e === 0) cy--; else if (e === 1) cx++; else if (e === 2) cy++; else cx--;
          k = (e + 2) & 3;
          if (++steps > maxSteps) throw new Error('An outline did not close.');
        } while (cx !== sx || cy !== sy || k !== sk);

        const pts = buf.slice(0, n);
        let area = 0;
        for (let j = 0, m = n - 2; j < n; m = j, j += 2) area += pts[m] * pts[j + 1] - pts[j] * pts[m + 1];
        loops.push({ pts, area: area / 2 });
      }
    }
    return loops;
  }

  // ── 3 and 4. Corners and curves ───────────────────────────────────────────

  function bez(c, u, out) {
    const v = 1 - u, b0 = v * v * v, b1 = 3 * v * v * u, b2 = 3 * v * u * u, b3 = u * u * u;
    out[0] = b0 * c[0] + b1 * c[2] + b2 * c[4] + b3 * c[6];
    out[1] = b0 * c[1] + b1 * c[3] + b2 * c[5] + b3 * c[7];
  }

  function chordParams(Q, first, last) {
    const n = last - first + 1;
    const u = new Float64Array(n);
    for (let i = 1; i < n; i++) {
      const a = 2 * (first + i), b = a - 2;
      u[i] = u[i - 1] + Math.hypot(Q[a] - Q[b], Q[a + 1] - Q[b + 1]);
    }
    const L = u[n - 1];
    if (L > 0) for (let i = 1; i < n; i++) u[i] /= L;
    else for (let i = 1; i < n; i++) u[i] = i / (n - 1);
    return u;
  }

  /* The least-squares cubic through Q[first..last] with the end tangents
     given: only the two handle lengths are free. */
  function generate(Q, first, last, u, t1x, t1y, t2x, t2y) {
    const p0x = Q[2 * first], p0y = Q[2 * first + 1], p3x = Q[2 * last], p3y = Q[2 * last + 1];
    let c00 = 0, c01 = 0, c11 = 0, x0 = 0, x1 = 0;
    for (let i = 0; i < u.length; i++) {
      const t = u[i], v = 1 - t;
      const b0 = v * v * v, b1 = 3 * v * v * t, b2 = 3 * v * t * t, b3 = t * t * t;
      const a1x = t1x * b1, a1y = t1y * b1, a2x = t2x * b2, a2y = t2y * b2;
      c00 += a1x * a1x + a1y * a1y;
      c01 += a1x * a2x + a1y * a2y;
      c11 += a2x * a2x + a2y * a2y;
      const j = 2 * (first + i);
      const tx = Q[j] - (p0x * (b0 + b1) + p3x * (b2 + b3));
      const ty = Q[j + 1] - (p0y * (b0 + b1) + p3y * (b2 + b3));
      x0 += a1x * tx + a1y * ty;
      x1 += a2x * tx + a2y * ty;
    }
    const det = c00 * c11 - c01 * c01;
    let al = det ? (x0 * c11 - x1 * c01) / det : 0;
    let ar = det ? (c00 * x1 - c01 * x0) / det : 0;
    const seg = Math.hypot(p3x - p0x, p3y - p0y);
    const eps = 1e-6 * seg;
    // Handles that point backwards or reach far past the chord give loops and
    // overshoot; Schneider's fallback of a third of the chord is safer.
    if (al < eps || ar < eps || al > 2 * seg || ar > 2 * seg) al = ar = seg / 3;
    return [p0x, p0y, p0x + t1x * al, p0y + t1y * al, p3x + t2x * ar, p3y + t2y * ar, p3x, p3y];
  }

  function maxError(Q, first, last, c, u) {
    let max = 0, at = (first + last) >> 1;
    const p = [0, 0];
    for (let i = 1; i < u.length - 1; i++) {
      bez(c, u[i], p);
      const j = 2 * (first + i);
      const dx = p[0] - Q[j], dy = p[1] - Q[j + 1];
      const d = dx * dx + dy * dy;
      if (d >= max) { max = d; at = first + i; }
    }
    return [max, at];
  }

  /* One Newton step on each parameter towards the closest point of the curve. */
  function reparam(Q, first, c, u) {
    const out = new Float64Array(u.length);
    const p = [0, 0];
    const d1 = [3 * (c[2] - c[0]), 3 * (c[3] - c[1]), 3 * (c[4] - c[2]), 3 * (c[5] - c[3]), 3 * (c[6] - c[4]), 3 * (c[7] - c[5])];
    const d2 = [2 * (d1[2] - d1[0]), 2 * (d1[3] - d1[1]), 2 * (d1[4] - d1[2]), 2 * (d1[5] - d1[3])];
    for (let i = 0; i < u.length; i++) {
      const t = u[i], v = 1 - t;
      bez(c, t, p);
      const qx = v * v * d1[0] + 2 * v * t * d1[2] + t * t * d1[4];
      const qy = v * v * d1[1] + 2 * v * t * d1[3] + t * t * d1[5];
      const rx = v * d2[0] + t * d2[2], ry = v * d2[1] + t * d2[3];
      const j = 2 * (first + i);
      const ex = p[0] - Q[j], ey = p[1] - Q[j + 1];
      const den = qx * qx + qy * qy + ex * rx + ey * ry;
      let nt = den ? t - (ex * qx + ey * qy) / den : t;
      if (!(nt >= 0)) nt = 0; else if (nt > 1) nt = 1;
      out[i] = nt;
    }
    return out;
  }

  function unit(x, y) {
    const l = Math.hypot(x, y);
    return l > 1e-12 ? [x / l, y / l] : [1, 0];
  }

  /*
    Schneider's fit of Q[first..last] within sqrt(err2), splitting at the
    worst point until each piece fits. A stack in place of recursion, so a
    long outline cannot run out of call stack; the left piece is always
    finished first, which keeps the curves in path order. Each curve is
    appended to out as its two handles and its end point.
  */
  function fitRange(Q, first, last, t1, t2, err2, m, out) {
    const stack = [[first, last, t1[0], t1[1], t2[0], t2[1]]];
    while (stack.length) {
      const [f, l, ax, ay, bx, by] = stack.pop();
      const n = l - f + 1;
      if (n === 2) {
        const d = Math.hypot(Q[2 * l] - Q[2 * f], Q[2 * l + 1] - Q[2 * f + 1]) / 3;
        out.push(Q[2 * f] + ax * d, Q[2 * f + 1] + ay * d, Q[2 * l] + bx * d, Q[2 * l + 1] + by * d, Q[2 * l], Q[2 * l + 1]);
        continue;
      }
      let u = chordParams(Q, f, l);
      let c = generate(Q, f, l, u, ax, ay, bx, by);
      let [e, split] = maxError(Q, f, l, c, u);
      if (e > err2 && e < 16 * err2) {
        for (let it = 0; it < 4; it++) {
          u = reparam(Q, f, c, u);
          c = generate(Q, f, l, u, ax, ay, bx, by);
          [e, split] = maxError(Q, f, l, c, u);
          if (e <= err2) break;
        }
      }
      if (e <= err2) { out.push(c[2], c[3], c[4], c[5], c[6], c[7]); continue; }
      if (split <= f) split = f + 1; else if (split >= l) split = l - 1;
      // The tangent at the split from points on either side, so both pieces
      // meet there smoothly.
      const q = Math.max(1, Math.min(m, split - f, l - split));
      const tc = unit(Q[2 * (split - q)] - Q[2 * (split + q)], Q[2 * (split - q) + 1] - Q[2 * (split + q) + 1]);
      stack.push([split, l, -tc[0], -tc[1], bx, by]);
      stack.push([f, split, ax, ay, tc[0], tc[1]]);
    }
  }

  /* Where the outline turns more sharply than maxTurn (radians), measured
     over m points either side, keeping only the sharpest point of each turn. */
  function findCorners(pts, n, m, maxTurn) {
    if (!(maxTurn < Math.PI) || n < 2 * m + 3) return [];
    const turn = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const a = (i - m + n) % n, b = (i + m) % n;
      const ax = pts[2 * i] - pts[2 * a], ay = pts[2 * i + 1] - pts[2 * a + 1];
      const bx = pts[2 * b] - pts[2 * i], by = pts[2 * b + 1] - pts[2 * i + 1];
      const la = Math.hypot(ax, ay), lb = Math.hypot(bx, by);
      if (!la || !lb) continue;
      let c = (ax * bx + ay * by) / (la * lb);
      if (c > 1) c = 1; else if (c < -1) c = -1;
      turn[i] = Math.acos(c);
    }
    const corners = [];
    for (let i = 0; i < n; i++) {
      const v = turn[i];
      if (v <= maxTurn) continue;
      // The sharpest within m either side; of equals, the first.
      let best = true;
      for (let j = 1; j <= m; j++) {
        if (turn[(i - j + n) % n] >= v || turn[(i + j) % n] > v) { best = false; break; }
      }
      if (best) corners.push(i);
    }
    return corners;
  }

  /*
    The path data for all loops whose area clears p.specks (in source px²),
    in source pixel coordinates. p.tolerance is the curve tolerance in source
    px; p.corners, 0..100, how readily a sharp turn is kept as a corner (0
    never).
  */
  function fitLoops(loops, p, sx, sy) {
    const s = (sx + sy) / 2;
    const minArea = (+p.specks || 0) * sx * sy;
    const tol = Math.max(0.02, +p.tolerance || 0.5) * s;
    const err2 = tol * tol;
    const cornerLevel = +p.corners || 0;
    const maxTurn = cornerLevel > 0 ? (180 - cornerLevel * 1.35) * Math.PI / 180 : Infinity;
    const m = Math.max(2, Math.round(2 * s));
    const parts = [];
    let shapes = 0, curves = 0;
    const X = (v) => Math.round(((v - 0.5) / sx) * 100) / 100;
    const Y = (v) => Math.round(((v - 0.5) / sy) * 100) / 100;

    for (const loop of loops) {
      if (Math.abs(loop.area) < minArea) continue;
      const raw = loop.pts;
      // Drop repeated points (where the contour passes a sample exactly).
      const pts = new Float64Array(raw.length);
      let n = 0;
      for (let j = 0; j < raw.length; j += 2) {
        if (n && Math.abs(raw[j] - pts[2 * n - 2]) < 1e-4 && Math.abs(raw[j + 1] - pts[2 * n - 1]) < 1e-4) continue;
        pts[2 * n] = raw[j]; pts[2 * n + 1] = raw[j + 1]; n++;
      }
      if (n > 1 && Math.abs(pts[0] - pts[2 * n - 2]) < 1e-4 && Math.abs(pts[1] - pts[2 * n - 1]) < 1e-4) n--;
      if (n < 3) continue;

      const corners = findCorners(pts, n, m, maxTurn);
      const start = corners.length ? corners[0] : 0;
      // The loop from its first corner (or its first point) round to the same
      // point again.
      const Q = new Float64Array(2 * (n + 1));
      for (let j = 0; j <= n; j++) {
        const k = (start + j) % n;
        Q[2 * j] = pts[2 * k]; Q[2 * j + 1] = pts[2 * k + 1];
      }
      const out = [];
      if (!corners.length) {
        const mm = Math.min(m, Math.floor(n / 3));
        const t = unit(Q[2 * mm] - Q[2 * (n - mm)], Q[2 * mm + 1] - Q[2 * (n - mm) + 1]);
        fitRange(Q, 0, n, t, [-t[0], -t[1]], err2, m, out);
      } else {
        const idx = corners.map(c => (c - start + n) % n).sort((a, b) => a - b);
        idx.push(n);
        for (let j = 0; j + 1 < idx.length; j++) {
          const f = idx[j], l = idx[j + 1];
          if (l - f < 2) {
            const d = Math.hypot(Q[2 * l] - Q[2 * f], Q[2 * l + 1] - Q[2 * f + 1]) / 3;
            const tt = unit(Q[2 * l] - Q[2 * f], Q[2 * l + 1] - Q[2 * f + 1]);
            out.push(Q[2 * f] + tt[0] * d, Q[2 * f + 1] + tt[1] * d, Q[2 * l] - tt[0] * d, Q[2 * l + 1] - tt[1] * d, Q[2 * l], Q[2 * l + 1]);
            continue;
          }
          const q = Math.max(1, Math.min(m, l - f - 1));
          const t1 = unit(Q[2 * (f + q)] - Q[2 * f], Q[2 * (f + q) + 1] - Q[2 * f + 1]);
          const t2 = unit(Q[2 * (l - q)] - Q[2 * l], Q[2 * (l - q) + 1] - Q[2 * l + 1]);
          fitRange(Q, f, l, t1, t2, err2, m, out);
        }
      }
      const d = ['M', X(Q[0]), Y(Q[1])];
      for (let j = 0; j < out.length; j += 6) {
        d.push('C', X(out[j]), Y(out[j + 1]), X(out[j + 2]), Y(out[j + 3]), X(out[j + 4]), Y(out[j + 5]));
      }
      d.push('Z');
      parts.push(d.join(' ').replace(/ ?([MCZ]) ?/g, '$1'));
      shapes++;
      curves += out.length / 6;
    }
    return { d: parts.join(''), shapes, curves };
  }

  /* The thresholded field as an RGBA image (ink black), at most ~4 Mpx. */
  function previewOf(F, t) {
    const f = Math.max(1, Math.ceil(Math.sqrt(F.ww * F.wh / 4e6)));
    const w = Math.ceil(F.ww / f), h = Math.ceil(F.wh / f);
    const px = new Uint8ClampedArray(w * h * 4);
    for (let y = 0; y < h; y++) {
      const gy = Math.min(F.wh - 1, y * f + (f >> 1)) + 1;
      for (let x = 0; x < w; x++) {
        const gx = Math.min(F.ww - 1, x * f + (f >> 1)) + 1;
        const v = F.P[gy * F.GW + gx] > t ? 0 : 255;
        const o = 4 * (y * w + x);
        px[o] = px[o + 1] = px[o + 2] = v; px[o + 3] = 255;
      }
    }
    return { width: w, height: h, data: px };
  }

  // ── The worker ────────────────────────────────────────────────────────────

  /*
    Each step's result is kept until something it depends on changes, so
    moving the curve settings refits without retracing, and moving the
    threshold retraces without rebuilding the field.
  */
  function makeRunner(post) {
    let src = null, F = null, fKey = '', loops = null, lKey = '';
    return function handle(msg) {
      if (msg.type === 'source') {
        src = { width: msg.width, height: msg.height, rgba: new Uint8ClampedArray(msg.buffer) };
        F = null; fKey = ''; loops = null; lKey = '';
        return;
      }
      if (msg.type !== 'run') return;
      if (!src) throw new Error('No image has been given yet.');
      const p = msg.params;
      const t0 = Date.now();
      const key = [p.detail, p.smooth, p.faint, p.invert ? 1 : 0, msg.maxWork].join('|');
      if (key !== fKey) {
        post({ type: 'progress', id: msg.id, stage: 'Preparing the image' });
        F = null; loops = null; lKey = '';
        F = buildField(src, p, msg.maxWork);
        fKey = key;
      }
      const t = Math.min(0.98, Math.max(0.02, +p.threshold));
      const k2 = key + '|' + t;
      if (k2 !== lKey) {
        post({ type: 'progress', id: msg.id, stage: 'Tracing outlines' });
        loops = traceContours(F.P, F.GW, F.GH, t);
        lKey = k2;
      }
      post({ type: 'progress', id: msg.id, stage: 'Fitting curves' });
      const r = fitLoops(loops, p, F.sx, F.sy);
      const preview = msg.wantPreview ? previewOf(F, t) : null;
      post({
        type: 'result', id: msg.id, d: r.d, shapes: r.shapes, curves: r.curves,
        auto: F.auto, scale: (F.sx + F.sy) / 2, workW: F.ww, workH: F.wh,
        ms: Date.now() - t0, preview,
      }, preview ? [preview.data.buffer] : []);
    };
  }

  const api = { inkOf, resample, blur, maxPass, paperLevel, liftFaint, otsu, buildField, traceContours, findCorners, fitLoops, previewOf, makeRunner };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else if (typeof self !== 'undefined' && typeof importScripts === 'function') {
    const handle = makeRunner((m, transfer) => self.postMessage(m, transfer || []));
    self.onmessage = (e) => {
      try { handle(e.data); }
      catch (err) {
        self.postMessage({ type: 'error', id: e.data && e.data.id, message: (err && err.message) || String(err) });
      }
    };
  }
})();
