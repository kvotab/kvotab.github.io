/* ==========================================================================
   distributions.html: WHAT EVERY FAMILY IS BUILT FROM

   A family is a plain object (see families.js for the full list of what it
   may define). This file has the pieces several of them share: the input
   fields and their domains, the properties a distribution can be fixed by
   when no named parameterisation fits ("known values"), the sample summary
   the fits read, and two builders -- one for a family that is another
   moved and stretched (location and scale), one for a family that is the
   exponential of another (the log shapes).
   ========================================================================== */

import { normQuantile } from './special.js';

/* ---- fields --------------------------------------------------------------- */

/**
 * What a field accepts. `check` returns '' or why the value is refused.
 */
export const DOMAINS = {
  real: { check: (v) => '', note: 'any number' },
  pos: { check: (v) => (v > 0 ? '' : 'must be greater than 0'), note: '> 0' },
  nonneg: { check: (v) => (v >= 0 ? '' : 'cannot be negative'), note: '≥ 0' },
  prob: { check: (v) => (v > 0 && v < 1 ? '' : 'must be between 0 and 1'), note: 'between 0 and 1' },
  probc: { check: (v) => (v >= 0 && v <= 1 ? '' : 'must be from 0 to 1'), note: '0 to 1' },
  pct: { check: (v) => (v > 0 && v < 100 ? '' : 'must be between 0 and 100'), note: 'between 0 and 100 %' },
  ge1: { check: (v) => (v >= 1 ? '' : 'must be at least 1'), note: '≥ 1' },
  gt1: { check: (v) => (v > 1 ? '' : 'must be greater than 1'), note: '> 1' },
  int: { check: (v) => (Number.isInteger(v) ? '' : 'must be a whole number'), note: 'a whole number' },
  posint: { check: (v) => (Number.isInteger(v) && v >= 1 ? '' : 'must be a whole number, 1 or more'), note: 'a whole number ≥ 1' },
  nonnegint: { check: (v) => (Number.isInteger(v) && v >= 0 ? '' : 'must be a whole number, 0 or more'), note: 'a whole number ≥ 0' },
};

/** A field: key in the values object, label shown, domain, and an optional hint. */
export const field = (key, label, domain = 'real', hint = '') => ({ key, label, domain, hint });

/** The symbol of a parameter, the one-letter word of its label ('Mean μ' -> μ, 'Minimum xₘ' -> xₘ), or its key. */
export function symbolOf(param) {
  const m = String(param.label).match(/(?:^|\s)([A-Za-z\u0391-\u03c9][\u2080-\u2089\u2098]?)(?=$|[\s)])/u);
  return m ? m[1] : param.key;
}

/* ---- the "known values" parameterisation ----------------------------------- */

/**
 * The properties a distribution can be fixed by. `needsP` ones take a
 * probability as well (in per cent). `positive` ones exist only for a
 * distribution on positive values.
 */
export const PROPERTIES = [
  { id: 'mean', label: 'Mean' },
  { id: 'median', label: 'Median' },
  { id: 'mode', label: 'Mode' },
  { id: 'sd', label: 'Standard deviation', domain: 'pos' },
  { id: 'var', label: 'Variance', domain: 'pos' },
  { id: 'cv', label: 'Coefficient of variation', domain: 'pos' },
  { id: 'q', label: 'Percentile', needsP: true },
  { id: 'gm', label: 'Geometric mean', domain: 'pos', positive: true },
  { id: 'gsd', label: 'Geometric SD', domain: 'gt1', positive: true },
];

export function propertyById(id) {
  return PROPERTIES.find((p) => p.id === id) || null;
}

/* ---- the sample a fit reads ------------------------------------------------- */

/**
 * Everything the fits read from a sample, worked out once.
 *
 * Moments are the population ones (divided by n), which is what the method
 * of moments matches; sd1 is the n - 1 one, for display.
 */
export function describeSample(values) {
  const x = Float64Array.from(values).sort();
  const n = x.length;
  let mean = 0;
  for (let i = 0; i < n; i++) mean += x[i];
  mean /= n;
  let m2 = 0;
  let m3 = 0;
  let m4 = 0;
  let allInteger = true;
  for (let i = 0; i < n; i++) {
    const d = x[i] - mean;
    const d2 = d * d;
    m2 += d2;
    m3 += d2 * d;
    m4 += d2 * d2;
    if (allInteger && !Number.isInteger(x[i])) allInteger = false;
  }
  m2 /= n;
  m3 /= n;
  m4 /= n;
  const min = x[0];
  const max = x[n - 1];
  const positive = min > 0;
  let meanLog = NaN;
  let varLog = NaN;
  if (positive) {
    let s = 0;
    for (let i = 0; i < n; i++) s += Math.log(x[i]);
    meanLog = s / n;
    let v = 0;
    for (let i = 0; i < n; i++) { const d = Math.log(x[i]) - meanLog; v += d * d; }
    varLog = v / n;
  }
  return {
    x, n, mean, var: m2, sd: Math.sqrt(m2), sd1: n > 1 ? Math.sqrt(m2 * n / (n - 1)) : NaN,
    skew: m2 > 0 ? m3 / Math.pow(m2, 1.5) : 0,
    kurt: m2 > 0 ? m4 / (m2 * m2) - 3 : 0,
    min, max, positive, nonneg: min >= 0, allInteger,
    inUnit: min > 0 && max < 1, binary: allInteger && min >= 0 && max <= 1,
    meanLog, varLog, sdLog: Math.sqrt(varLog),
    distinct: n > 0 && max > min,
  };
}

/** The type-7 sample quantile (linear between order statistics), as R and NumPy default to. */
export function sampleQuantile(sorted, p) {
  const n = sorted.length;
  if (!n) return NaN;
  const h = (n - 1) * p;
  const lo = Math.floor(h);
  const hi = Math.min(lo + 1, n - 1);
  return sorted[lo] + (h - lo) * (sorted[hi] - sorted[lo]);
}

/* ---- builders ------------------------------------------------------------------ */

/**
 * A location-scale family from a standard one. `std` holds the standard
 * shape's functions in z = (x - loc) / scale, each taking the shape
 * parameters `s` as a second argument; `shape(p)` picks them from the
 * family's parameters. Only what `std` has is defined, so the generic
 * fallbacks in dist.js fill in the rest.
 */
export function locationScale(def, std, keys = { loc: 'mu', scale: 'sigma' }, shape = () => null) {
  const L = keys.loc;
  const S = keys.scale;
  const fam = { ...def };
  const z = (x, p) => (x - p[L]) / p[S];
  if (std.logpdf) fam.logpdf = (x, p) => std.logpdf(z(x, p), shape(p)) - Math.log(p[S]);
  if (std.cdf) fam.cdf = (x, p) => std.cdf(z(x, p), shape(p));
  if (std.sf) fam.sf = (x, p) => std.sf(z(x, p), shape(p));
  if (std.logcdf) fam.logcdf = (x, p) => std.logcdf(z(x, p), shape(p));
  if (std.logsf) fam.logsf = (x, p) => std.logsf(z(x, p), shape(p));
  if (std.quantile) fam.quantile = (u, p) => p[L] + p[S] * std.quantile(u, shape(p));
  if (std.isf) fam.isf = (q, p) => p[L] + p[S] * std.isf(q, shape(p));
  if (std.support) {
    fam.support = (p) => std.support(shape(p)).map((v) => (Number.isFinite(v) ? p[L] + p[S] * v : v));
  } else if (!fam.support) {
    fam.support = () => [-Infinity, Infinity];
  }
  if (std.mean) fam.mean = (p) => p[L] + p[S] * std.mean(shape(p));
  if (std.variance) fam.variance = (p) => p[S] * p[S] * std.variance(shape(p));
  if (std.skewness) fam.skewness = (p) => std.skewness(shape(p));
  if (std.kurtosis) fam.kurtosis = (p) => std.kurtosis(shape(p));
  if (std.entropy) fam.entropy = (p) => std.entropy(shape(p)) + Math.log(p[S]);
  if (std.mode) fam.mode = (p) => p[L] + p[S] * std.mode(shape(p));
  if (std.median) fam.median = (p) => p[L] + p[S] * std.median(shape(p));
  if (std.tails) fam.tails = (p) => std.tails(shape(p));
  return fam;
}

/**
 * The family of X = exp(Y) for Y of family `base`. `toBase(p)` gives Y's
 * parameters from X's. Whatever the log family defines itself wins.
 *
 * Maximum likelihood on X is maximum likelihood on ln X, since the
 * Jacobian -sum ln x does not depend on the parameters; the fit is the
 * base's on the logarithms, mapped back by `fromBase`.
 */
export function logOf(base, def, toBase, fromBase) {
  const fam = {
    support: (p) => base.support(toBase(p)).map((v) => Math.exp(v)),
    logpdf: (x, p) => (x > 0 ? base.logpdf(Math.log(x), toBase(p)) - Math.log(x) : -Infinity),
    cdf: (x, p) => (x > 0 ? base.cdf(Math.log(x), toBase(p)) : 0),
    sf: (x, p) => (x > 0 ? (base.sf ? base.sf(Math.log(x), toBase(p)) : 1 - base.cdf(Math.log(x), toBase(p))) : 1),
    quantile: (u, p) => Math.exp(base.quantile(u, toBase(p))),
    median: (p) => Math.exp(base.median ? base.median(toBase(p)) : base.quantile(0.5, toBase(p))),
    ...def,
  };
  /* E[ln X] and Var[ln X] are Y's mean and variance, where Y has them in closed form. */
  if (base.mean && base.variance && !def.logMoments) fam.logMoments = (p) => [base.mean(toBase(p)), base.variance(toBase(p))];
  if (base.isf && !def.isf) fam.isf = (q, p) => Math.exp(base.isf(q, toBase(p)));
  if (base.breaks && !def.breaks) fam.breaks = (p) => base.breaks(toBase(p));
  if (base.logcdf && !def.logcdf) fam.logcdf = (x, p) => (x > 0 ? base.logcdf(Math.log(x), toBase(p)) : -Infinity);
  if (base.logsf && !def.logsf) fam.logsf = (x, p) => (x > 0 ? base.logsf(Math.log(x), toBase(p)) : 0);
  if (base.entropy && base.mean && !def.entropy) fam.entropy = (p) => base.entropy(toBase(p)) + base.mean(toBase(p));
  if (base.fit && base.fit.mle && fromBase && !(def.fit && def.fit.mle)) {
    fam.fit = { ...(def.fit || {}) };
    fam.fit.mle = (s, opts) => {
      if (!s.positive) return null;
      const logs = describeSample(Array.from(s.x, Math.log));
      const got = base.fit.mle(logs, opts);
      return got ? fromBase(got) : null;
    };
  }
  return fam;
}

/* ---- small helpers ----------------------------------------------------------------- */

/** z of the central interval holding `coverage` per cent. */
export function centralZ(coverage) {
  return normQuantile(0.5 + coverage / 200);
}

export const logistic = (t) => (t >= 0 ? 1 / (1 + Math.exp(-t)) : Math.exp(t) / (1 + Math.exp(t)));
export const logit = (u) => Math.log(u) - Math.log1p(-u);

/** Raw moments 1..4 to mean, variance, skewness and excess kurtosis. */
export function fromRawMoments(m1, m2, m3, m4) {
  const v = m2 - m1 * m1;
  const c3 = m3 - 3 * m1 * m2 + 2 * m1 * m1 * m1;
  const c4 = m4 - 4 * m1 * m3 + 6 * m1 * m1 * m2 - 3 * m1 * m1 * m1 * m1;
  return { mean: m1, variance: v, skewness: c3 / Math.pow(v, 1.5), kurtosis: c4 / (v * v) - 3 };
}
