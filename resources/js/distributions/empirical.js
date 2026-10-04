/* ==========================================================================
   distributions.html: DISTRIBUTIONS FROM DATA AND FROM TABLES

   Four ways to make a distribution of a sample without choosing a family,
   and two to write one down by hand:

   - interpolated: the cumulative curve through (x(i), (i-1)/(n-1)), whose
     quantiles are the type-7 sample quantiles (R's and NumPy's default,
     and what Kompartment and Ecolego sample an empirical parameter by);
   - ecdf: probability 1/n at each value, the sample itself;
   - kde: a Gaussian kernel on every value, with Silverman's or Scott's
     bandwidth or one given; optionally in ln x, for skewed positive data;
   - histogram: probability spread evenly over each bin, with Sturges',
     Freedman-Diaconis', Scott's or the square-root rule, or a bin count;
   - a cumulative table (x, F): straight lines between the points;
   - a probability table (x, p): masses at the points.

   The first, the histogram and the cumulative table are one object
   (piecewiseLinear); the ecdf and the probability table another
   (pointMasses). Each returns the same functions a family has, with the
   parameters bound in.
   ========================================================================== */

import { normCdf, normSf, normPdf } from './special.js';
import { brentRoot, integrate } from './numeric.js';
import { sampleQuantile, fromRawMoments } from './kit.js';

/* ---- piecewise-linear cumulative curves -------------------------------------- */

/**
 * The distribution whose CDF is the straight lines through (xs[i], Fs[i]),
 * xs non-decreasing, Fs non-decreasing from 0 to 1. Where xs repeats, F
 * jumps: that is a mass at the point (an atom), which the density leaves
 * out and everything else includes.
 */
export function piecewiseLinear(xs, Fs) {
  const n = xs.length;
  const lo = xs[0];
  const hi = xs[n - 1];
  /* the last index i with xs[i] <= x */
  const locate = (x) => {
    let a = 0;
    let b = n - 1;
    if (x < xs[0]) return -1;
    if (x >= xs[b]) return b;
    while (b - a > 1) {
      const m = (a + b) >> 1;
      if (xs[m] <= x) a = m; else b = m;
    }
    return a;
  };
  const cdf = (x) => {
    if (x < lo) return 0;
    if (x >= hi) return 1;
    const i = locate(x);
    const w = xs[i + 1] - xs[i];
    return w > 0 ? Fs[i] + (Fs[i + 1] - Fs[i]) * (x - xs[i]) / w : Fs[i + 1];
  };
  /* P(X < x): below a jump at x rather than above it */
  const cdfLeft = (x) => {
    if (x <= lo) return 0;
    if (x > hi) return 1;
    let a = 0;
    let b = n - 1;
    while (b - a > 1) { const m = (a + b) >> 1; if (xs[m] >= x) b = m; else a = m; }
    const j = xs[a] >= x ? a : b;   // the first index at or beyond x
    if (j === 0) return 0;
    const w = xs[j] - xs[j - 1];
    return w > 0 ? Fs[j - 1] + (Fs[j] - Fs[j - 1]) * (x - xs[j - 1]) / w : Fs[j - 1];
  };
  const pdf = (x) => {
    if (x < lo || x > hi) return 0;
    let i = locate(x);
    if (i >= n - 1) i = n - 2;
    while (i > 0 && xs[i + 1] - xs[i] === 0) i--;
    const w = xs[i + 1] - xs[i];
    return w > 0 ? (Fs[i + 1] - Fs[i]) / w : 0;
  };
  /* the smallest x with F(x) >= u */
  const quantile = (u) => {
    if (u <= 0) return lo;
    if (u >= 1) return hi;
    let a = 0;
    let b = n - 1;
    while (b - a > 1) {
      const m = (a + b) >> 1;
      if (Fs[m] < u) a = m; else b = m;
    }
    const dF = Fs[b] - Fs[a];
    return dF > 0 ? xs[a] + (xs[b] - xs[a]) * (u - Fs[a]) / dF : xs[b];
  };
  /* E[X^k] over the pieces: uniform on each piece of positive width, a mass
     where the width is zero. Central moments about c to keep precision. */
  const centralMoment = (k, c) => {
    let s = 0;
    for (let i = 0; i < n - 1; i++) {
      const m = Fs[i + 1] - Fs[i];
      if (!(m > 0)) continue;
      const a = xs[i] - c;
      const b = xs[i + 1] - c;
      if (b > a) s += m * (Math.pow(b, k + 1) - Math.pow(a, k + 1)) / ((k + 1) * (b - a));
      else s += m * Math.pow(a, k);
    }
    return s;
  };
  const mean = centralMoment(1, 0);
  const m2 = centralMoment(2, mean);
  const m3 = centralMoment(3, mean);
  const m4 = centralMoment(4, mean);
  let entropy = 0;
  let hasAtom = false;
  let modeX = lo;
  let modeD = -1;
  for (let i = 0; i < n - 1; i++) {
    const m = Fs[i + 1] - Fs[i];
    const w = xs[i + 1] - xs[i];
    if (!(m > 0)) continue;
    if (!(w > 0)) { hasAtom = true; continue; }
    entropy -= m * Math.log(m / w);
    if (m / w > modeD) { modeD = m / w; modeX = (xs[i] + xs[i + 1]) / 2; }
  }
  return {
    kind: 'continuous', support: [lo, hi], cdf, cdfLeft, sf: (x) => 1 - cdf(x), pdf,
    logpdf: (x) => Math.log(pdf(x)), quantile, isf: (q) => quantile(1 - q),
    moments: { mean, variance: m2, skewness: m3 / Math.pow(m2, 1.5), kurtosis: m4 / (m2 * m2) - 3 },
    entropy: hasAtom ? NaN : entropy,
    mode: modeX,
    atoms: hasAtom,
  };
}

/** The interpolated empirical distribution of a sorted sample. */
export function interpolated(sorted) {
  const n = sorted.length;
  if (n < 2) throw new Error('Needs at least two values.');
  return piecewiseLinear(Array.from(sorted), Array.from(sorted, (_, i) => i / (n - 1)));
}

/* ---- histograms -------------------------------------------------------------- */

export const BIN_RULES = [
  ['sturges', 'Sturges: 1 + log₂ n bins'],
  ['fd', 'Freedman–Diaconis: width 2·IQR/n^⅓'],
  ['scott', 'Scott: width 3.49·SD/n^⅓'],
  ['sqrt', 'Square root: √n bins'],
];

/** The number of bins a rule gives for a sorted sample. */
export function binCount(sorted, rule) {
  const n = sorted.length;
  const range = sorted[n - 1] - sorted[0];
  if (!(range > 0)) return 1;
  if (Number.isFinite(rule) && rule >= 1) return Math.round(rule);
  if (rule === 'sqrt') return Math.max(1, Math.ceil(Math.sqrt(n)));
  if (rule === 'fd' || rule === 'scott') {
    let width;
    if (rule === 'fd') width = 2 * (sampleQuantile(sorted, 0.75) - sampleQuantile(sorted, 0.25)) / Math.cbrt(n);
    else {
      let m = 0;
      for (const v of sorted) m += v;
      m /= n;
      let s = 0;
      for (const v of sorted) s += (v - m) * (v - m);
      width = 3.49 * Math.sqrt(s / (n - 1)) / Math.cbrt(n);
    }
    if (width > 0) return Math.min(10000, Math.max(1, Math.ceil(range / width)));
  }
  return Math.max(1, Math.ceil(Math.log2(n) + 1));
}

/** The histogram distribution: bins of equal width from the smallest value to the largest. */
export function histogram(sorted, rule = 'sturges') {
  const n = sorted.length;
  const lo = sorted[0];
  const hi = sorted[n - 1];
  if (!(hi > lo)) throw new Error('A histogram needs values that differ.');
  const k = binCount(sorted, rule);
  const w = (hi - lo) / k;
  const counts = new Array(k).fill(0);
  for (const v of sorted) counts[Math.min(k - 1, Math.floor((v - lo) / w))]++;
  const xs = [lo];
  const Fs = [0];
  let c = 0;
  for (let i = 0; i < k; i++) {
    c += counts[i];
    xs.push(i === k - 1 ? hi : lo + (i + 1) * w);
    Fs.push(c / n);
  }
  const d = piecewiseLinear(xs, Fs);
  d.bins = { lo, width: w, counts };
  return d;
}

/* ---- kernel density ---------------------------------------------------------------- */

export const BANDWIDTH_RULES = [
  ['silverman', 'Silverman: 0.9·min(SD, IQR/1.34)·n^−⅕'],
  ['scott', 'Scott: 1.06·SD·n^−⅕'],
];

/** The bandwidth a rule gives for a sorted sample (of ln x when log is set). */
export function bandwidth(sorted, rule) {
  const n = sorted.length;
  let m = 0;
  for (const v of sorted) m += v;
  m /= n;
  let s2 = 0;
  for (const v of sorted) s2 += (v - m) * (v - m);
  const sd = Math.sqrt(s2 / (n - 1));
  const iqr = sampleQuantile(sorted, 0.75) - sampleQuantile(sorted, 0.25);
  if (rule === 'scott') return 1.06 * sd * Math.pow(n, -0.2);
  const spread = iqr > 0 ? Math.min(sd, iqr / 1.34) : sd;
  return 0.9 * spread * Math.pow(n, -0.2);
}

const KDE_BINS = 4096;

/**
 * A Gaussian kernel density estimate with bandwidth h, of x or (log) of
 * ln x. Above 2,000 values the kernels sit on 4,096 bins (linear binning),
 * which changes nothing visible while h spans several bins; the moments are
 * always the exact ones.
 */
export function kde(sorted, h, log = false) {
  if (!(h > 0)) throw new Error('The bandwidth must be above zero.');
  if (log && !(sorted[0] > 0)) throw new Error('A kernel density in ln x needs every value above zero.');
  const raw = log ? Float64Array.from(sorted, Math.log) : Float64Array.from(sorted);
  const n = raw.length;
  let centres = raw;
  let weights = null;
  if (n > 2000) {
    const lo = raw[0];
    const hi = raw[n - 1];
    const step = (hi - lo) / (KDE_BINS - 1);
    if (step > 0) {
      const w = new Float64Array(KDE_BINS);
      for (const v of raw) {
        const t = (v - lo) / step;
        const i = Math.min(KDE_BINS - 2, Math.floor(t));
        const f = t - i;
        w[i] += 1 - f;
        w[i + 1] += f;
      }
      const c = [];
      const ww = [];
      for (let i = 0; i < KDE_BINS; i++) if (w[i] > 0) { c.push(lo + i * step); ww.push(w[i] / n); }
      centres = Float64Array.from(c);
      weights = Float64Array.from(ww);
    }
  }
  const m = centres.length;
  const wt = (i) => (weights ? weights[i] : 1 / n);
  const cutoff = 9;
  /* the kernels within reach of y, found by binary search on the sorted centres */
  const span = (y) => {
    let a = 0; let b = m;
    const left = y - cutoff * h;
    while (a < b) { const mid = (a + b) >> 1; if (centres[mid] < left) a = mid + 1; else b = mid; }
    const start = a;
    a = start; b = m;
    const right = y + cutoff * h;
    while (a < b) { const mid = (a + b) >> 1; if (centres[mid] <= right) a = mid + 1; else b = mid; }
    return [start, a];
  };
  const densityY = (y) => {
    const [s, e] = span(y);
    let f = 0;
    for (let i = s; i < e; i++) f += wt(i) * normPdf((y - centres[i]) / h);
    return f / h;
  };
  const cdfY = (y) => {
    const [s, e] = span(y);
    let F = s ? (weights ? sumW(0, s) : s / n) : 0;
    for (let i = s; i < e; i++) F += wt(i) * normCdf((y - centres[i]) / h);
    return Math.min(1, F);
  };
  const sfY = (y) => {
    const [s, e] = span(y);
    let S = e < m ? (weights ? sumW(e, m) : (m - e) / n) : 0;
    for (let i = s; i < e; i++) S += wt(i) * normSf((y - centres[i]) / h);
    return Math.min(1, S);
  };
  let prefix = null;
  function sumW(a, b) {
    if (!prefix) {
      prefix = new Float64Array(m + 1);
      for (let i = 0; i < m; i++) prefix[i + 1] = prefix[i] + weights[i];
    }
    return prefix[b] - prefix[a];
  }
  const yLo = raw[0] - cutoff * h;
  const yHi = raw[n - 1] + cutoff * h;
  /* quantiles: a table of the CDF to start from, then Brent */
  const G = 1024;
  let table = null;
  const quantileY = (u, upper) => {
    if (!table) {
      table = { y: new Float64Array(G), F: new Float64Array(G) };
      for (let i = 0; i < G; i++) { const y = yLo + (yHi - yLo) * i / (G - 1); table.y[i] = y; table.F[i] = cdfY(y); }
    }
    const target = upper ? 1 - u : u;
    let a = 0; let b = G - 1;
    while (b - a > 1) { const mid = (a + b) >> 1; if (table.F[mid] < target) a = mid; else b = mid; }
    let ya = table.y[a]; let yb = table.y[b];
    if (upper) {
      const f = (y) => u - sfY(y);
      if (!(f(ya) <= 0)) ya = yLo - 30 * h;
      if (!(f(yb) >= 0)) yb = yHi + 30 * h;
      return brentRoot(f, ya, yb, { rtol: 1e-13 });
    }
    const f = (y) => cdfY(y) - u;
    if (!(f(ya) <= 0)) ya = yLo - 30 * h;
    if (!(f(yb) >= 0)) yb = yHi + 30 * h;
    return brentRoot(f, ya, yb, { rtol: 1e-13 });
  };
  /* moments: exact */
  let mean = 0;
  for (const v of raw) mean += v;
  mean /= n;
  let c2 = 0; let c3 = 0; let c4 = 0;
  for (const v of raw) { const d = v - mean; c2 += d * d; c3 += d * d * d; c4 += d * d * d * d; }
  c2 /= n; c3 /= n; c4 /= n;
  let moments;
  if (!log) {
    const v = c2 + h * h;
    moments = { mean, variance: v, skewness: c3 / Math.pow(v, 1.5), kurtosis: (c4 + 6 * c2 * h * h + 3 * h ** 4) / (v * v) - 3 };
  } else {
    /* E[X^k] = mean of exp(k y_i + k^2 h^2 / 2), scaled by the largest to stay finite */
    const ymax = raw[n - 1];
    const raw4 = [1, 2, 3, 4].map((k) => {
      let s = 0;
      for (const v of raw) s += Math.exp(k * (v - ymax));
      return Math.log(s / n) + k * ymax + k * k * h * h / 2;
    });
    const scale = Math.exp(raw4[0]);
    moments = fromRawMoments(1, Math.exp(raw4[1] - 2 * raw4[0]), Math.exp(raw4[2] - 3 * raw4[0]), Math.exp(raw4[3] - 4 * raw4[0]));
    moments.variance *= scale * scale;
    moments.mean = scale;
  }
  const d = log ? {
    kind: 'continuous',
    support: [0, Infinity],
    pdf: (x) => (x > 0 ? densityY(Math.log(x)) / x : 0),
    cdf: (x) => (x > 0 ? cdfY(Math.log(x)) : 0),
    sf: (x) => (x > 0 ? sfY(Math.log(x)) : 1),
    quantile: (u) => Math.exp(quantileY(u, false)),
    isf: (q) => Math.exp(quantileY(q, true)),
    logMoments: [mean, c2 + h * h],
  } : {
    kind: 'continuous',
    support: [-Infinity, Infinity],
    pdf: densityY,
    cdf: cdfY,
    sf: sfY,
    quantile: (u) => quantileY(u, false),
    isf: (q) => quantileY(q, true),
  };
  d.logpdf = (x) => Math.log(d.pdf(x));
  d.moments = moments;
  d.h = h;
  /* For draws: the inverse of a table of the CDF at 8,192 points across the
     kernels, linear between them, with a Gaussian tail beyond the first and
     last kernel. Its error is far below the bandwidth, and a draw costs a
     binary search instead of a root finding over every kernel. */
  let inv = null;
  d.fastAt = (u) => {
    if (!inv) {
      const G = 8192;
      inv = { y: new Float64Array(G), F: new Float64Array(G) };
      for (let i = 0; i < G; i++) { const y = yLo + (yHi - yLo) * i / (G - 1); inv.y[i] = y; inv.F[i] = cdfY(y); }
    }
    const { y, F } = inv;
    let v;
    if (u <= F[0] || u >= F[F.length - 1]) v = quantileY(u <= F[0] ? u : 1 - u, u > F[0]);
    else {
      let a = 0; let b = F.length - 1;
      while (b - a > 1) { const m = (a + b) >> 1; if (F[m] < u) a = m; else b = m; }
      const dF = F[b] - F[a];
      v = dF > 0 ? y[a] + (y[b] - y[a]) * (u - F[a]) / dF : y[b];
    }
    return log ? Math.exp(v) : v;
  };
  /* the entropy over the y-axis by Gauss-Kronrod (plus E[ln X] for the log form) */
  d.entropy = (() => {
    const g = (y) => { const f = densityY(y); return f > 0 ? -f * Math.log(f) : 0; };
    let H = 0;
    const pieces = 64;
    for (let i = 0; i < pieces; i++) H += integrate(g, yLo + (yHi - yLo) * i / pieces, yLo + (yHi - yLo) * (i + 1) / pieces, { rtol: 1e-9, maxIntervals: 40 });
    return log ? H + mean : H;
  })();
  d.mode = (() => {
    let best = yLo; let bestF = -1;
    const N = 800;
    for (let i = 0; i <= N; i++) {
      const y = yLo + (yHi - yLo) * i / N;
      const f = log ? densityY(y) * Math.exp(-y) : densityY(y);
      if (f > bestF) { bestF = f; best = y; }
    }
    return log ? Math.exp(best) : best;
  })();
  return d;
}

/* ---- point masses -------------------------------------------------------------------- */

/**
 * The distribution with probability ps[i] at xs[i] (xs sorted and distinct,
 * ps summing to 1).
 */
export function pointMasses(xs, ps) {
  const n = xs.length;
  const cum = new Float64Array(n);
  let c = 0;
  for (let i = 0; i < n; i++) { c += ps[i]; cum[i] = c; }
  for (let i = 0; i < n; i++) cum[i] /= c;
  const tailFrom = new Float64Array(n);   // P(X > xs[i])
  let t = 0;
  for (let i = n - 1; i >= 0; i--) { tailFrom[i] = t; t += ps[i] / c; }
  const locate = (x) => {
    let a = -1; let b = n;
    while (b - a > 1) { const m = (a + b) >> 1; if (xs[m] <= x) a = m; else b = m; }
    return a;
  };
  const at = new Map();
  for (let i = 0; i < n; i++) at.set(xs[i], ps[i] / c);
  let mean = 0;
  for (let i = 0; i < n; i++) mean += xs[i] * ps[i] / c;
  let m2 = 0; let m3 = 0; let m4 = 0; let H = 0;
  let mode = xs[0]; let modeP = -1;
  for (let i = 0; i < n; i++) {
    const p = ps[i] / c;
    const d = xs[i] - mean;
    m2 += p * d * d; m3 += p * d * d * d; m4 += p * d * d * d * d;
    if (p > 0) H -= p * Math.log(p);
    if (p > modeP) { modeP = p; mode = xs[i]; }
  }
  return {
    kind: 'discrete', points: true, support: [xs[0], xs[n - 1]],
    logpdf: (x) => { const p = at.get(x); return p > 0 ? Math.log(p) : -Infinity; },
    cdf: (x) => { const i = locate(x); return i < 0 ? 0 : cum[i]; },
    sf: (x) => { const i = locate(x); return i < 0 ? 1 : tailFrom[i]; },
    quantile: (u) => {
      let a = -1; let b = n - 1;
      while (b - a > 1) { const m = (a + b) >> 1; if (cum[m] >= u - 1e-12 * Math.min(u, 1 - u)) b = m; else a = m; }
      return xs[b];
    },
    isf: (q) => {
      let a = -1; let b = n - 1;
      while (b - a > 1) { const m = (a + b) >> 1; if (tailFrom[m] <= q * (1 + 1e-12)) b = m; else a = m; }
      return xs[b];
    },
    atoms: () => [Array.from(xs), Array.from(ps, (p) => p / c)],
    moments: { mean, variance: m2, skewness: m3 / Math.pow(m2, 1.5), kurtosis: m4 / (m2 * m2) - 3 },
    entropy: H,
    mode,
  };
}

/** The sample as a distribution: 1/n at each value, ties adding up. */
export function ecdf(sorted) {
  const xs = [];
  const ps = [];
  for (const v of sorted) {
    if (xs.length && xs[xs.length - 1] === v) ps[ps.length - 1] += 1;
    else { xs.push(v); ps.push(1); }
  }
  return pointMasses(xs, ps);
}

/* ---- methods, for the editor and the fits ------------------------------------------------ */

export const EMPIRICAL_METHODS = [
  ['interpolated', 'Interpolated (straight lines between the sorted values)'],
  ['kde', 'Kernel density (Gaussian kernels)'],
  ['histogram', 'Histogram'],
  ['ecdf', 'Empirical CDF (1/n at each value)'],
];

export const TABLE_MODES = [
  ['cdf', 'Cumulative table: x and F(x), straight lines between'],
  ['pmf', 'Probability table: x and P(X = x)'],
];

