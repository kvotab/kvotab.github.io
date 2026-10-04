/* ==========================================================================
   distributions.html: FITTING THE TRIANGLES AND THE LOG SHAPES

   The four triangles (triangular, double-triangular and their logarithmic
   forms) have no closed-form maximum likelihood, and their moments are not
   the ones a solver for a smooth family would expect, so they get the
   method Kompartment uses for the same shapes (kompartment/src/domain/
   fit.js, written for this site): a profile over the order statistics for
   the mode inside a search over the two ends, and the moments of a
   standardised peak for the method of moments.

   The maximum-likelihood mode is always one of the values (Oliver 1972:
   between two neighbours the log-likelihood is convex in the mode, so it
   peaks at an end). The double triangle's density jumps at its mode, so for
   it the mode a hair below a value is a candidate too.
   ========================================================================== */

import { nelderMead } from './numeric.js';

/* ---- maximum likelihood --------------------------------------------------- */

/**
 * The log-likelihood of the triangle on [a, b] whose mode is the best of
 * the candidates, over z sorted in (a, b).
 *
 * The double triangle's density at its mode is 1/(c - a) from the left and
 * 1/(b - c) from the right, whatever else is there. A side whose only values
 * sit at the mode lets its end close in on the mode and the likelihood grow
 * without bound (a spike on an end value, or on tied values), so such a
 * candidate is left out: each side needs a value away from the mode, or no
 * value at all. The mode at z[r] has z[0..r] on its left, the mode a hair
 * below z[r] has z[r..] on its right.
 */
function triangleProfile(z, a, b, double) {
  const n = z.length;
  const w = b - a;
  let right = 0;
  for (let i = 0; i < n; i++) right += Math.log1p(-(z[i] - a) / w);
  const base = double ? -n * Math.log(w) : n * Math.LN2 - n * Math.log(w);
  const p = double ? 2 : 1;
  let best = { ll: -Infinity, at: -1, below: false };
  if (!double) best = { ll: base + right, at: -1, below: false };
  let left = 0;
  for (let r = 0; r < n; r++) {
    const u = (z[r] - a) / w;
    const lu = Math.log(u);
    const lv = Math.log1p(-u);
    const smaller = z[0] < z[r];
    const larger = z[n - 1] > z[r];
    if (double && larger && (r === 0 || smaller)) {
      const ll = base + left - p * r * lu + right - p * (n - r) * lv;
      if (ll > best.ll) best = { ll, at: r, below: true };
    }
    left += lu;
    right -= lv;
    if (double && !(smaller && (r === n - 1 || larger))) continue;
    const ll = base + left - p * (r + 1) * lu + right - p * (n - r - 1) * lv;
    if (ll > best.ll) best = { ll, at: r, below: false };
  }
  if (!double && base + left > best.ll) best = { ll: base + left, at: n, below: false };
  return best;
}

/** A hair under v. */
const under = (v) => (v === 0 ? -Number.MIN_VALUE : v - Math.abs(v) * Number.EPSILON);

/**
 * The triangle of largest likelihood through sorted y: its ends and its
 * mode. Standardised to [0, 1] first, and the ends searched as their
 * distance past the extremes on a log scale, from a trillionth of the range
 * to a few hundred ranges.
 */
export function triangleMle(y, double) {
  const n = y.length;
  const lo = y[0];
  const span = y[n - 1] - lo;
  const z = Float64Array.from(y, (v) => (v - lo) / span);
  const clamp = (v) => Math.min(6, Math.max(-28, v));
  const cost = ([al, be]) => -triangleProfile(z, -Math.exp(clamp(al)), 1 + Math.exp(clamp(be)), double).ll;
  let best = null;
  for (const s of [-4, -1.5]) {
    const got = nelderMead(cost, [s, s], { steps: [0.7, 0.7], restarts: 0, maxIter: 160, ftol: 1e-10, xtol: 1e-8 });
    if (!best || got.f < best.f) best = got;
  }
  const a = -Math.exp(clamp(best.x[0]));
  const b = 1 + Math.exp(clamp(best.x[1]));
  const { at, below } = triangleProfile(z, a, b, double);
  const min = lo + a * span;
  const max = lo + b * span;
  let mode;
  if (at < 0) mode = min;
  else if (at >= n) mode = max;
  else mode = below ? under(y[at]) : y[at];
  return { min, max, mode, at, below };
}

/* ---- moments of the standardised peak ---------------------------------------- */

/* A peak at r on [0, 1]. The triangle holds r of its probability left of the
   peak, the double triangle half. Either side is a right triangle. */
const leftWeight = (r, double) => (double ? 0.5 : r);

/** E[Z^k] for k = 1..3. */
function shapeRaw(r, double) {
  const wl = leftWeight(r, double);
  const q = 1 - r;
  const out = [1];
  for (let k = 1; k <= 3; k++) {
    let right = 0;
    for (let j = 0, c = 1; j <= k; j++) {
      right += c * Math.pow(-q, j) * (2 / (j + 2));
      c = (c * (k - j)) / (j + 1);
    }
    out.push(wl * Math.pow(r, k) * (2 / (k + 2)) + (1 - wl) * right);
  }
  return out;
}

/** Mean, SD and skewness of the standardised peak. */
export function shapeMoments(r, double) {
  const [, m1, m2, m3] = shapeRaw(r, double);
  const v = m2 - m1 * m1;
  return { mean: m1, sd: Math.sqrt(v), skew: (m3 - 3 * m1 * m2 + 2 * m1 ** 3) / Math.pow(v, 1.5) };
}

/**
 * The r at which measure(r) equals target: a scan for a change of sign and
 * bisection inside it. Out of reach, the nearest, flagged clamped.
 */
export function solveShape(measure, target, lo, hi) {
  const steps = 64;
  let prevR = lo;
  let prev = measure(lo) - target;
  let best = { r: lo, gap: Math.abs(prev) };
  if (prev === 0) return { r: lo, clamped: false };
  for (let s = 1; s <= steps; s++) {
    const r = lo + ((hi - lo) * s) / steps;
    const now = measure(r) - target;
    if (!Number.isFinite(now)) { prevR = r; prev = now; continue; }
    if (Math.abs(now) < best.gap) best = { r, gap: Math.abs(now) };
    if (now === 0) return { r, clamped: false };
    if (Number.isFinite(prev) && (prev < 0) !== (now < 0)) {
      let a = prevR;
      let b = r;
      let fa = prev;
      for (let it = 0; it < 60; it++) {
        const m = (a + b) / 2;
        const fm = measure(m) - target;
        if ((fm < 0) === (fa < 0)) { a = m; fa = fm; } else b = m;
      }
      return { r: (a + b) / 2, clamped: false };
    }
    prevR = r;
    prev = now;
  }
  return { r: best.r, clamped: true };
}

/* ---- moments of the log shapes ---------------------------------------------------- */

/* X = exp(Y), Y = ln(min) + L Z: E[X^k] is e^(kL) times E[e^(-kL(1-Z))], a
   number in (0, 1] that neither overflows nor underflows for a spread of
   hundreds of decades. */

/** E[e^(-sV)] for V with density 2v on [0, 1]. */
function rampMgf(s) {
  if (Math.abs(s) < 0.5) {
    let sum = 0;
    let term = 1;
    for (let n = 0; n < 24; n++) {
      sum += term / (n + 2);
      term *= -s / (n + 1);
    }
    return 2 * sum;
  }
  return (2 * (1 - Math.exp(-s) * (1 + s))) / (s * s);
}

/** e^(-t) E[e^(sV)], finite however large s is (s <= t). */
function rampMgfUp(s, t) {
  if (s < 0.5) return Math.exp(-t) * rampMgf(-s);
  return (2 * (Math.exp(s - t) * (s - 1) + Math.exp(-t))) / (s * s);
}

/** E[e^(-t(1-Z))] for the peak shape. */
export function peakScaled(t, r, double) {
  const wl = leftWeight(r, double);
  return wl * rampMgfUp(t * r, t) + (1 - wl) * rampMgf(t * (1 - r));
}

/** E[e^(-t(1-U))] for U uniform. */
export function flatScaled(t) {
  return t < 1e-12 ? 1 : -Math.expm1(-t) / t;
}

/** The squared CV and the skewness of X = e^(L Z). */
export function logShapeMoments(scaled, L) {
  const m1 = scaled(L);
  const m2 = scaled(2 * L);
  const m3 = scaled(3 * L);
  const v = m2 / (m1 * m1) - 1;
  const c = m2 - m1 * m1;
  return { cv2: v, skew: (m3 - 3 * m1 * m2 + 2 * m1 ** 3) / Math.pow(c, 1.5), m1 };
}

/** The spread L at which the squared CV is cv2, or null out of reach. */
export function spreadFor(scaled, cv2) {
  let a = Math.log(1e-5);
  let b = Math.log(1400);
  if (!(logShapeMoments(scaled, Math.exp(b)).cv2 >= cv2)) return null;
  if (logShapeMoments(scaled, Math.exp(a)).cv2 >= cv2) return Math.exp(a);
  for (let it = 0; it < 80; it++) {
    const m = (a + b) / 2;
    if (logShapeMoments(scaled, Math.exp(m)).cv2 < cv2) a = m; else b = m;
  }
  return Math.exp((a + b) / 2);
}

/* ---- the method of moments for the four triangles ---------------------------------- */

/**
 * A triangle (or double triangle) whose mean, SD and skewness are the
 * sample's: the peak from the skewness, the width from the SD, the position
 * from the mean.
 */
export function triangleMom(s, double) {
  const [rlo, rhi] = double ? [1e-4, 1 - 1e-4] : [0, 1];
  const { r, clamped } = solveShape((q) => shapeMoments(q, double).skew, s.skew, rlo, rhi);
  const m = shapeMoments(r, double);
  const w = s.sd / m.sd;
  const min = s.mean - w * m.mean;
  return { min, max: min + w, mode: min + r * w, clamped };
}

/**
 * The log triangle whose mean, SD and skewness (of X, not of ln X) are the
 * sample's: for each peak the spread that gives the CV, then the peak whose
 * skewness is the sample's, and the position from the mean.
 */
export function logTriangleMom(s, double) {
  const cv2 = s.var / (s.mean * s.mean);
  const [rlo, rhi] = double ? [1e-3, 1 - 1e-3] : [0, 1];
  const spreadAt = (r) => spreadFor((t) => peakScaled(t, r, double), cv2);
  const skewAt = (r) => {
    const L = spreadAt(r);
    return L == null ? NaN : logShapeMoments((t) => peakScaled(t, r, double), L).skew;
  };
  const { r, clamped } = solveShape(skewAt, s.skew, rlo, rhi);
  const L = spreadAt(r);
  if (L == null) return null;
  const la = Math.log(s.mean) - L - Math.log(peakScaled(L, r, double));
  return { min: Math.exp(la), max: Math.exp(la + L), mode: Math.exp(la + r * L), clamped };
}

/** The log-uniform whose mean and SD are the sample's. */
export function logUniformMom(s) {
  const L = spreadFor(flatScaled, s.var / (s.mean * s.mean));
  if (L == null) return null;
  const la = Math.log(s.mean) - L - Math.log(flatScaled(L));
  return { min: Math.exp(la), max: Math.exp(la + L) };
}
