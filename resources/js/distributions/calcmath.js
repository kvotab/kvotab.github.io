/* ==========================================================================
   distributions.html: THE CALCULATIONS

   What the Calculate tab works out, as functions of evaluated
   distributions (dist.js), so that the tests can run them in Node:
   interval probabilities, central and shortest intervals, conditional
   expectations above and below a threshold, value at risk and the mean
   beyond it, and six comparisons of two distributions.

   Expectations of a continuous distribution are integrals over its
   quantile function on the part of (0, 1) they need, by tanh-sinh with the
   complement of u carried separately (numeric.js), so that the mean of a
   far tail keeps its precision; a discrete one's are sums over its
   probabilities.
   ========================================================================== */

import { integrate01Vec, integrate, brentMin } from './numeric.js';

/* ---- probabilities ---------------------------------------------------------------- */

/** P(X <= x), P(X > x), P(a < X <= b), the density (or probability) and hazard at x. */
export function probabilities(D, x, a, b) {
  const out = { cdf: NaN, sf: NaN, between: NaN, density: NaN, hazard: NaN };
  if (Number.isFinite(x)) {
    out.cdf = D.cdf(x);
    out.sf = D.sf(x);
    out.density = D.pdf(x);
    out.hazard = D.hazard(x);
  }
  if (Number.isFinite(a) && Number.isFinite(b)) {
    if (b < a) out.between = 0;
    else {
      /* from whichever side keeps the digits */
      const Fa = D.cdf(a);
      out.between = Fa > 0.5 ? D.sf(a) - D.sf(b) : D.cdf(b) - Fa;
      if (out.between < 0) out.between = 0;
    }
  }
  return out;
}

/* ---- intervals ------------------------------------------------------------------------ */

/** The central interval holding `cover` (0..1): equal probability left out on each side. */
export function centralInterval(D, cover) {
  const tail = (1 - cover) / 2;
  return [D.quantile(tail), D.isf(tail)];
}

/**
 * The shortest interval [Q(u), Q(u + cover)] holding `cover`: the u that
 * minimises the width, by Brent's method. For a unimodal density it is the
 * highest-density interval.
 */
export function shortestInterval(D, cover) {
  const rest = 1 - cover;
  if (!(rest > 0)) return [D.support[0], D.support[1]];
  /* a discrete one: the narrowest run of consecutive values holding the
     probability, by two pointers over its values */
  if (D.kind === 'discrete') {
    const at = D.atoms();
    if (at) {
      const [xs, ps] = at;
      let best = null;
      let mass = 0;
      let j = 0;
      for (let i = 0; i < xs.length; i++) {
        while (j < xs.length && mass < cover - 1e-12) { mass += ps[j]; j++; }
        if (mass < cover - 1e-12) break;
        if (!best || xs[j - 1] - xs[i] < best[1] - best[0]) best = [xs[i], xs[j - 1]];
        mass -= ps[i];
      }
      if (best) return best;
    }
  }
  const width = (u) => {
    const lo = D.quantile(u);
    const hi = D.at(u + cover, rest - u);
    const w = hi - lo;
    return Number.isFinite(w) ? w : Infinity;
  };
  const eps = Math.min(1e-9, rest / 4);
  /* a coarse scan first, since a discrete or multimodal width is not smooth */
  let best = eps;
  let bw = width(eps);
  const N = 200;
  for (let i = 0; i <= N; i++) {
    const u = eps + (rest - 2 * eps) * i / N;
    const w = width(u);
    if (w < bw) { bw = w; best = u; }
  }
  const step = (rest - 2 * eps) / N;
  const got = brentMin(width, Math.max(eps, best - step), Math.min(rest - eps, best + step), { tol: 1e-10 });
  const u = got.f <= bw ? got.x : best;
  return [D.quantile(u), D.at(u + cover, rest - u)];
}

/* ---- expectations over part of the distribution ------------------------------------------- */

/**
 * ∫ x dF over the probability interval (u0, u1) of a continuous
 * distribution, given u0 and u1 with their complements c0 = 1 - u0 and
 * c1 = 1 - u1 (exact, so that a tail u1 = 1, c1 = 0 is exact too).
 */
function partialMean(D, u0, c0, u1, c1) {
  const len = c0 - c1;
  if (!(len > 0)) return 0;
  const f = (t, tc) => {
    /* u = u0 + len t, with complement c1 + len tc */
    const u = u0 + len * t;
    const uc = c1 + len * tc;
    return [D.at(u, uc)];
  };
  return len * integrate01Vec(f, 1, { rtol: 1e-11 })[0];
}

/* Whether the mean of the right (or left) tail is finite. */
function tailMeanExists(D, side) {
  if (side === 'right') return Number.isFinite(D.support[1]) || D.tails.right > 1;
  return Number.isFinite(D.support[0]) || D.tails.left > 1;
}

/**
 * E[X | X > t], E[X | X <= t], E[(X - t)+], and at a level p the value at
 * risk Q(p) and the mean beyond it, E[X | X >= Q(p)].
 */
export function tailStats(D, t, level) {
  const out = { above: NaN, below: NaN, excess: NaN, pAbove: NaN, var: NaN, tvar: NaN };
  const rightOk = tailMeanExists(D, 'right');
  const leftOk = tailMeanExists(D, 'left');
  if (D.kind === 'discrete') {
    const at = D.atoms();
    if (at) {
      const [xs, ps] = at;
      let sa = 0; let pa = 0; let sb = 0; let pb = 0;
      for (let i = 0; i < xs.length; i++) {
        if (xs[i] > t) { sa += xs[i] * ps[i]; pa += ps[i]; } else { sb += xs[i] * ps[i]; pb += ps[i]; }
      }
      if (Number.isFinite(t)) {
        out.above = pa > 0 ? sa / pa : NaN;
        out.below = pb > 0 ? sb / pb : NaN;
        out.pAbove = pa;
        out.excess = pa > 0 ? sa - t * pa : 0;
      }
      if (level > 0 && level < 1) {
        out.var = D.quantile(level);
        let s = 0; let p = 0;
        for (let i = 0; i < xs.length; i++) if (xs[i] >= out.var) { s += xs[i] * ps[i]; p += ps[i]; }
        out.tvar = p > 0 ? s / p : NaN;
      }
    }
    return out;
  }
  if (Number.isFinite(t)) {
    const F = D.cdf(t);
    const S = D.sf(t);
    out.pAbove = S;
    if (S > 0) out.above = rightOk ? partialMean(D, F, S, 1, 0) / S : Infinity;
    if (F > 0) out.below = leftOk ? partialMean(D, 0, 1, F, S) / F : -Infinity;
    if (S > 0 && Number.isFinite(out.above)) out.excess = S * (out.above - t);
    else if (S === 0) out.excess = 0;
    else if (out.above === Infinity) out.excess = Infinity;
  }
  if (level > 0 && level < 1) {
    out.var = D.quantile(level);
    out.tvar = rightOk ? partialMean(D, level, 1 - level, 1, 0) / (1 - level) : Infinity;
  }
  return out;
}

/* ---- two distributions ---------------------------------------------------------------------- */

/* P(Y < x) and P(Y > x). */
const below = (Y, x) => (Y.kind === 'discrete' ? Y.cdf(x) - Y.pdf(x) : Y.cdf(x));

/* The x-range both live on, for integrals over x. */
function sharedRange(X, Y) {
  const lo = Math.min(X.quantile(1e-12), Y.quantile(1e-12));
  const hi = Math.max(X.isf(1e-12), Y.isf(1e-12));
  return [lo, hi];
}

/* ∫ g(x) dx over [lo, hi] in pieces, with the support ends of both (and any
   atoms given) as breaks. */
function integrateX(g, lo, hi, X, Y, extra = []) {
  const cuts = new Set([lo, hi]);
  for (const v of [...X.support, ...Y.support, ...extra]) if (v > lo && v < hi) cuts.add(v);
  const pts = [...cuts].sort((a, b) => a - b);
  let s = 0;
  for (let i = 0; i + 1 < pts.length; i++) {
    const a = pts[i]; const b = pts[i + 1];
    const pieces = pts.length > 50 ? 2 : 48;
    for (let k = 0; k < pieces; k++) s += integrate(g, a + (b - a) * k / pieces, a + (b - a) * (k + 1) / pieces, { rtol: 1e-9, maxIntervals: 30 });
  }
  return s;
}

/**
 * Six ways to compare X and Y (independent, for the first):
 * P(X > Y), P(X < Y), the overlap of the densities, the largest gap between
 * the CDFs (K–S), the Wasserstein-1 distance, the Hellinger distance and the
 * Kullback–Leibler divergence each way.
 */
export function compare(X, Y) {
  const out = { pGreater: NaN, pLess: NaN, pEqual: NaN, overlap: NaN, ks: NaN, wasserstein: NaN, hellinger: NaN, klXY: NaN, klYX: NaN };
  /* P(X > Y) = E[P(Y < X)]: a sum over the atoms of a discrete one, an
     integral over X's quantile function when both are continuous */
  if (X.kind === 'discrete') {
    const at = X.atoms();
    if (at) {
      let g = 0; let l = 0;
      for (let i = 0; i < at[0].length; i++) { g += at[1][i] * below(Y, at[0][i]); l += at[1][i] * Y.sf(at[0][i]); }
      out.pGreater = g;
      out.pLess = l;
    }
  } else if (Y.kind === 'discrete') {
    const at = Y.atoms();
    if (at) {
      let g = 0; let l = 0;
      for (let i = 0; i < at[0].length; i++) { g += at[1][i] * X.sf(at[0][i]); l += at[1][i] * X.cdf(at[0][i]); }
      out.pGreater = g;
      out.pLess = l;
    }
  } else {
    const r = integrate01Vec((u, uc) => { const x = X.at(u, uc); return [below(Y, x), Y.sf(x)]; }, 2, { rtol: 1e-10, scale: [1, 1] });
    out.pGreater = r[0];
    out.pLess = r[1];
  }
  /* ties have probability zero unless both are discrete */
  out.pEqual = X.kind === 'discrete' && Y.kind === 'discrete' ? Math.max(0, 1 - out.pGreater - out.pLess) : 0;

  /* the largest gap between the CDFs, at the quantiles of both and at the atoms */
  {
    let d = 0;
    const probe = (x) => {
      if (!Number.isFinite(x)) return;
      d = Math.max(d, Math.abs(X.cdf(x) - Y.cdf(x)));
      if (X.kind === 'discrete' || Y.kind === 'discrete') d = Math.max(d, Math.abs(below(X, x) - below(Y, x)));
    };
    const N = 1500;
    for (let i = 1; i < N; i++) {
      const u = i / N;
      probe(X.quantile(u));
      probe(Y.quantile(u));
    }
    for (const D of [X, Y]) {
      if (D.kind === 'discrete') {
        const at = D.atoms();
        if (at && at[0].length < 20000) for (const x of at[0]) probe(x);
      }
    }
    out.ks = d;
  }

  /* Wasserstein-1: the area between the CDFs (equally, between the quantile
     functions), exactly between the atoms when both are discrete */
  const meanOk = (D) => tailMeanExists(D, 'left') && tailMeanExists(D, 'right');
  if (!(meanOk(X) && meanOk(Y))) out.wasserstein = Infinity;
  else if (X.kind === 'discrete' && Y.kind === 'discrete') {
    const ax = X.atoms();
    const ay = Y.atoms();
    if (ax && ay) {
      const xs = [...new Set([...ax[0], ...ay[0]])].sort((a, b) => a - b);
      let w = 0;
      for (let i = 0; i + 1 < xs.length; i++) w += Math.abs(X.cdf(xs[i]) - Y.cdf(xs[i])) * (xs[i + 1] - xs[i]);
      out.wasserstein = w;
    }
  } else {
    const [lo, hi] = sharedRange(X, Y);
    const extra = [];
    for (const D of [X, Y]) {
      if (D.kind !== 'discrete') continue;
      const at = D.atoms();
      if (at && at[0].length <= 2000) extra.push(...at[0]);
    }
    out.wasserstein = integrateX((x) => Math.abs(X.cdf(x) - Y.cdf(x)), lo, hi, X, Y, extra);
  }

  if (X.kind === 'continuous' && Y.kind === 'continuous') {
    const [lo, hi] = sharedRange(X, Y);
    out.overlap = integrateX((x) => Math.min(X.pdf(x), Y.pdf(x)), lo, hi, X, Y);
    const bc = integrateX((x) => Math.sqrt(X.pdf(x) * Y.pdf(x)), lo, hi, X, Y);
    out.hellinger = Math.sqrt(Math.max(0, 1 - bc));
    out.klXY = kl(X, Y);
    out.klYX = kl(Y, X);
  } else if (X.kind === 'discrete' && Y.kind === 'discrete') {
    const ax = X.atoms();
    const ay = Y.atoms();
    if (ax && ay) {
      /* over the atoms of both, each probability evaluated directly: either
         list stops where its own tail is negligible, the other's need not */
      const xs = new Set([...ax[0], ...ay[0]]);
      let ov = 0; let bc = 0; let kxy = 0; let kyx = 0;
      for (const x of xs) {
        const p = X.pdf(x);
        const q = Y.pdf(x);
        ov += Math.min(p, q);
        bc += Math.sqrt(p * q);
        if (p > 0) kxy += q > 0 ? p * (X.logpdf(x) - Y.logpdf(x)) : Infinity;
        if (q > 0) kyx += p > 0 ? q * (Y.logpdf(x) - X.logpdf(x)) : Infinity;
      }
      out.overlap = ov;
      out.hellinger = Math.sqrt(Math.max(0, 1 - bc));
      out.klXY = Math.max(0, kxy);
      out.klYX = Math.max(0, kyx);
    }
  }
  return out;
}

/* KL(P || Q) = E_P[ln p(X) - ln q(X)], over P's quantile function; infinite
   where P has probability that Q has none. */
function kl(P, Q) {
  let infinite = false;
  const r = integrate01Vec((u, uc) => {
    const x = P.at(u, uc);
    const lp = P.logpdf(x);
    const lq = Q.logpdf(x);
    if (lq === -Infinity && lp > -Infinity) { infinite = true; return [0]; }
    const v = lp - lq;
    return [Number.isFinite(v) ? v : 0];
  }, 1, { rtol: 1e-9 });
  return infinite ? Infinity : Math.max(0, r[0]);
}
