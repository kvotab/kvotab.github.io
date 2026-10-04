/* ==========================================================================
   distributions.html: THE DISCRETE FAMILIES

   Counts and trials. A probability mass function is the family's logpdf at
   a whole number (and -Infinity elsewhere); cdf(x) is P(X <= floor x) and
   sf(x) is P(X > floor x), so both work at any real x. A quantile is the
   smallest k whose cdf reaches u.

   The binomial, Poisson and negative binomial probabilities use Loader's
   saddle-point form (special.js), which stays accurate for millions of
   trials; their cumulative probabilities are incomplete beta and gamma
   functions rather than sums.
   ========================================================================== */

import { lchoose, lbeta, logDbinomRaw, logDpoisRaw, gammaInc, betaInc, normQuantile } from './special.js';
import { brentMin, nelderMead } from './numeric.js';
import { field } from './kit.js';

const R = String.raw;
const isInt = Number.isInteger;

/**
 * The smallest k in [lo, hi] for which ok(k) holds, ok being false then
 * true as k grows; searched outwards from a guess by doubling steps, then
 * by bisection. hi if ok never holds.
 */
export function discreteSearch(ok, guess, lo, hi) {
  let k = Number.isFinite(guess) ? Math.round(guess) : lo;
  if (k < lo) k = lo;
  if (k > hi) k = hi;
  let a; // the largest known k with !ok, or lo - 1
  let b; // the smallest known k with ok
  if (ok(k)) {
    b = k;
    let step = 1;
    a = b - step;
    while (a >= lo && ok(a)) { b = a; step *= 2; a = b - step; }
    if (a < lo) a = lo - 1;
  } else {
    a = k;
    let step = 1;
    b = a + step;
    while (b <= hi && !ok(b)) { a = b; step *= 2; b = a + step; }
    if (b > hi) {
      if (!Number.isFinite(hi)) return Infinity;
      if (!ok(hi)) return hi;
      b = hi;
    }
  }
  while (b - a > 1) {
    const m = Math.floor((a + b) / 2);
    if (m === a || m === b) break;   // beyond 2^53 there may be no whole number between
    if (ok(m)) b = m; else a = m;
  }
  return b;
}

/* The largest count the page computes with: beyond 10^15 whole numbers are
   no longer all representable, and sums and searches over them stall. */
export const MAX_COUNT = 1e15;
const tooLarge = (what) => `${what} is too large: the page counts up to 10^15.`;

/* The quantile tolerance: a cdf that rounds to a hair below u still counts
   as reaching it, so the quantile of 11/16 in Binomial(4, 1/2) is 2. */
const reaches = (F, u) => F >= u - 1e-12 * Math.min(u, 1 - u);

/* A quantile guess from the normal with Cornish-Fisher's skewness term. */
function cfGuess(u, mean, sd, skew) {
  const z = normQuantile(u);
  return mean + sd * (z + skew * (z * z - 1) / 6);
}

/** Counts of each distinct value of a sorted integer sample: [values, counts]. */
export function tally(x) {
  const values = [];
  const counts = [];
  for (let i = 0; i < x.length; i++) {
    if (values.length && values[values.length - 1] === x[i]) counts[counts.length - 1]++;
    else { values.push(x[i]); counts.push(1); }
  }
  return [values, counts];
}

const countsApplicable = (s) => (s.allInteger && s.nonneg ? '' : 'needs whole numbers of zero or above');

/* The probabilities of a family whose CDF is a sum (hypergeometric,
   beta-binomial) summed once per parameter set from both ends of the
   support, so that P(X <= k) and P(X > k) are lookups: summed for every
   value, a cumulative curve or a quantile search cost a sum over up to half
   the support each time. Each side is summed from its own end, so a small
   tail is exact; the larger side is one minus the smaller. Tables of up to
   a million terms, two million in all, are kept for the latest parameter
   sets; beyond that every value is summed for itself. */
const SUM_TABLE_MAX = 1e6;
const SUM_TABLES_TOTAL = 2e6;
const sumTables = new Map();
let sumTablesSize = 0;
function sumTable(key, lo, hi, logpmf) {
  const m = hi - lo + 1;
  if (!(m <= SUM_TABLE_MAX)) return null;
  const old = sumTables.get(key);
  if (old) return old;
  const left = new Float64Array(m);
  const right = new Float64Array(m);
  for (let i = 0; i < m; i++) left[i] = Math.exp(logpmf(lo + i));
  let s = 0;
  for (let i = m - 1; i >= 0; i--) { right[i] = s; s += left[i]; }
  s = 0;
  for (let i = 0; i < m; i++) { s += left[i]; left[i] = s; }
  while (sumTables.size && sumTablesSize + m > SUM_TABLES_TOTAL) {
    const [k, t] = sumTables.entries().next().value;
    sumTables.delete(k);
    sumTablesSize -= t.left.length;
  }
  const t = { lo, left, right };
  sumTables.set(key, t);
  sumTablesSize += m;
  return t;
}
/* P(X <= k) and P(X > k) from a table, k inside the support. */
function tableCdf(t, k) {
  const L = t.left[k - t.lo];
  const R = t.right[k - t.lo];
  return Math.min(1, Math.max(0, L <= R ? L : 1 - R));
}
function tableSf(t, k) {
  const L = t.left[k - t.lo];
  const R = t.right[k - t.lo];
  return Math.min(1, Math.max(0, R <= L ? R : 1 - L));
}

/* ======================================================================
   Bernoulli
   ====================================================================== */

export const bernoulli = {
  id: 'bernoulli', label: 'Bernoulli', kind: 'discrete', group: 'Discrete',
  blurb: 'One trial that succeeds (1) with probability p or fails (0).',
  params: [field('p', 'Probability of success p', 'probc')],
  defaults: { p: 0.3 },
  support: () => [0, 1],
  logpdf: (k, p) => (k === 0 ? Math.log1p(-p.p) : k === 1 ? Math.log(p.p) : -Infinity),
  cdf: (x, p) => (x < 0 ? 0 : x < 1 ? 1 - p.p : 1),
  sf: (x, p) => (x < 0 ? 1 : x < 1 ? p.p : 0),
  quantile: (u, p) => (reaches(1 - p.p, u) ? 0 : 1),
  isf: (q, p) => (p.p <= q ? 0 : 1),
  mean: (p) => p.p,
  variance: (p) => p.p * (1 - p.p),
  skewness: (p) => (1 - 2 * p.p) / Math.sqrt(p.p * (1 - p.p)),
  kurtosis: (p) => (1 - 6 * p.p * (1 - p.p)) / (p.p * (1 - p.p)),
  entropy: (p) => (p.p > 0 ? -p.p * Math.log(p.p) : 0) + (p.p < 1 ? -(1 - p.p) * Math.log1p(-p.p) : 0),
  mode: (p) => (p.p > 0.5 ? 1 : 0),
  modeText: (p) => (p.p === 0.5 ? '0 and 1' : ''),
  parameterisations: [
    { id: 'p', label: 'Probability of success', fields: [field('p', 'Probability of success p', 'probc')], to: (v) => ({ p: v.p }), from: (p) => ({ p: p.p }) },
  ],
  fit: {
    k: 1, keys: ['p'],
    applicable: (s) => (s.binary ? '' : 'needs values that are all 0 or 1'),
    mle: (s) => ({ p: s.mean }),
    mom: (s) => ({ p: s.mean }),
  },
  tex: { pdf: R`P(X=1)=p,\ P(X=0)=1-p`, cdf: R`F(0)=1-p`, mean: R`p`, variance: R`p(1-p)` },
  scipy: 'bernoulli(p)',
};

/* ======================================================================
   Binomial
   ====================================================================== */

function binomCdf(k, n, p) {
  if (k < 0) return 0;
  if (k >= n) return 1;
  return betaInc(n - k, k + 1, 1 - p, p)[0];
}
function binomSf(k, n, p) {
  if (k < 0) return 1;
  if (k >= n) return 0;
  return betaInc(n - k, k + 1, 1 - p, p)[1];
}

/* The binomial log-likelihood of a tallied sample with n trials and p = mean/n. */
function binomProfile(values, counts, n, mean) {
  const p = mean / n;
  let ll = 0;
  for (let i = 0; i < values.length; i++) ll += counts[i] * logDbinomRaw(values[i], n, p, 1 - p);
  return ll;
}

export const binomial = {
  id: 'binomial', label: 'Binomial', kind: 'discrete', group: 'Discrete',
  blurb: 'The number of successes in n independent trials, each succeeding with probability p.',
  params: [field('n', 'Trials n', 'nonnegint'), field('p', 'Probability of success p', 'probc')],
  defaults: { n: 10, p: 0.3 },
  validate: (p) => (p.n > MAX_COUNT ? tooLarge('n') : ''),
  support: (p) => [0, p.n],
  logpdf: (k, p) => (isInt(k) && k >= 0 && k <= p.n ? logDbinomRaw(k, p.n, p.p, 1 - p.p) : -Infinity),
  cdf: (x, p) => binomCdf(Math.floor(x), p.n, p.p),
  sf: (x, p) => binomSf(Math.floor(x), p.n, p.p),
  quantile: (u, p) => {
    const m = p.n * p.p; const sd = Math.sqrt(m * (1 - p.p));
    return discreteSearch((k) => reaches(binomCdf(k, p.n, p.p), u), cfGuess(u, m, sd, sd > 0 ? (1 - 2 * p.p) / sd : 0), 0, p.n);
  },
  isf: (q, p) => {
    const m = p.n * p.p; const sd = Math.sqrt(m * (1 - p.p));
    return discreteSearch((k) => binomSf(k, p.n, p.p) <= q * (1 + 1e-12), cfGuess(1 - q, m, sd, 0), 0, p.n);
  },
  mean: (p) => p.n * p.p,
  variance: (p) => p.n * p.p * (1 - p.p),
  skewness: (p) => (1 - 2 * p.p) / Math.sqrt(p.n * p.p * (1 - p.p)),
  kurtosis: (p) => (1 - 6 * p.p * (1 - p.p)) / (p.n * p.p * (1 - p.p)),
  mode: (p) => Math.min(p.n, Math.floor((p.n + 1) * p.p)),
  modeText: (p) => { const t = (p.n + 1) * p.p; return p.p > 0 && p.p < 1 && isInt(t) && t >= 1 && t <= p.n ? `${t - 1} and ${t}` : ''; },
  parameterisations: [
    { id: 'n-p', label: 'Trials and probability', fields: [field('n', 'Trials n', 'nonnegint'), field('p', 'Probability of success p', 'probc')],
      to: (v) => ({ n: v.n, p: v.p }), from: (p) => ({ n: p.n, p: p.p }) },
    { id: 'n-mean', label: 'Trials and mean', fields: [field('n', 'Trials n', 'posint'), field('mean', 'Mean number of successes', 'nonneg')],
      to: (v) => { if (!(v.mean <= v.n)) throw new Error('The mean cannot exceed the number of trials.'); return { n: v.n, p: v.mean / v.n }; },
      from: (p) => ({ n: p.n, mean: p.n * p.p }) },
  ],
  fit: {
    k: 2, keys: ['p'],
    applicable: countsApplicable,
    /* n is given (opts.trials) or estimated: the profile likelihood over n
       is searched from the largest count up. A sample at least as spread
       as its mean has no binomial: the profile rises towards the Poisson. */
    mle: (s, opts = {}) => {
      if (Number.isInteger(opts.trials) && opts.trials > 0) {
        if (s.max > opts.trials) return { params: null, why: `a count is above the ${opts.trials} trials given` };
        return { params: { n: opts.trials, p: s.mean / opts.trials }, k: 1, note: `n = ${opts.trials} given` };
      }
      if (!(s.mean > 0)) return null;
      const [values, counts] = tally(s.x);
      const lo = s.max;
      const cap = Math.max(1000, 1000 * s.max);
      if (s.var >= s.mean) {
        return { params: { n: cap, p: s.mean / cap }, note: 'the sample is at least as spread as its mean; n is at its limit and this is close to a Poisson' };
      }
      const f = (n) => -binomProfile(values, counts, n, s.mean);
      let a = lo;
      let b = Math.min(cap, Math.max(lo + 2, Math.ceil(2 * s.mean * s.mean / Math.max(s.mean - s.var, 1e-9))));
      while (b < cap && f(b) < f(b - 1)) b = Math.min(cap, 2 * b);
      while (b - a > 2) {
        const m1 = Math.floor(a + (b - a) / 3);
        const m2 = Math.ceil(b - (b - a) / 3);
        if (f(m1) <= f(m2)) b = m2; else a = m1;
      }
      let best = a;
      for (let n = a; n <= b; n++) if (f(n) < f(best)) best = n;
      return { params: { n: best, p: s.mean / best }, note: 'n estimated' };
    },
    mom: (s, opts = {}) => {
      if (Number.isInteger(opts.trials) && opts.trials > 0) return { params: { n: opts.trials, p: s.mean / opts.trials }, k: 1, note: `n = ${opts.trials} given` };
      if (!(s.var < s.mean)) return { params: null, why: 'the variance is not below the mean, which a binomial needs' };
      const p0 = 1 - s.var / s.mean;
      const n = Math.max(Math.round(s.mean / p0), s.max);
      return { n, p: s.mean / n };
    },
  },
  tex: { pdf: R`P(X=k)=\binom nk p^k(1-p)^{n-k}`, cdf: R`F(k)=I_{1-p}(n-k,\,k+1)`, mean: R`np`, variance: R`np(1-p)` },
  scipy: 'binom(n, p)',
};

/* ======================================================================
   Poisson
   ====================================================================== */

export const poisson = {
  id: 'poisson', label: 'Poisson', kind: 'discrete', group: 'Discrete',
  blurb: 'The number of events in a fixed time or space when they happen independently at a constant rate: decays counted, failures, arrivals.',
  params: [field('lambda', 'Mean λ', 'pos')],
  defaults: { lambda: 4 },
  validate: (p) => (p.lambda > MAX_COUNT ? tooLarge('λ') : ''),
  support: () => [0, Infinity],
  logpdf: (k, p) => (isInt(k) && k >= 0 ? logDpoisRaw(k, p.lambda) : -Infinity),
  cdf: (x, p) => { const k = Math.floor(x); return k < 0 ? 0 : gammaInc(k + 1, p.lambda)[1]; },
  sf: (x, p) => { const k = Math.floor(x); return k < 0 ? 1 : gammaInc(k + 1, p.lambda)[0]; },
  quantile: (u, p) => discreteSearch((k) => reaches(gammaInc(k + 1, p.lambda)[1], u), cfGuess(u, p.lambda, Math.sqrt(p.lambda), 1 / Math.sqrt(p.lambda)), 0, Infinity),
  isf: (q, p) => discreteSearch((k) => gammaInc(k + 1, p.lambda)[0] <= q * (1 + 1e-12), cfGuess(1 - q, p.lambda, Math.sqrt(p.lambda), 1 / Math.sqrt(p.lambda)), 0, Infinity),
  mean: (p) => p.lambda,
  variance: (p) => p.lambda,
  skewness: (p) => 1 / Math.sqrt(p.lambda),
  kurtosis: (p) => 1 / p.lambda,
  mode: (p) => Math.floor(p.lambda),
  modeText: (p) => (isInt(p.lambda) && p.lambda >= 1 ? `${p.lambda - 1} and ${p.lambda}` : ''),
  parameterisations: [
    { id: 'rate', label: 'Mean λ', fields: [field('lambda', 'Mean λ', 'pos')], to: (v) => ({ lambda: v.lambda }), from: (p) => ({ lambda: p.lambda }) },
    { id: 'rate-exposure', label: 'Rate and exposure', fields: [field('rate', 'Rate (events per unit)', 'pos'), field('exposure', 'Exposure (units)', 'pos')],
      to: (v) => ({ lambda: v.rate * v.exposure }), from: (p, v) => { const t = v && v.exposure > 0 ? v.exposure : 1; return { rate: p.lambda / t, exposure: t }; } },
  ],
  fit: {
    k: 1, keys: ['lambda'],
    applicable: (s) => countsApplicable(s) || (s.mean > 0 ? '' : 'needs at least one count above zero'),
    mle: (s) => ({ lambda: s.mean }),
    mom: (s) => ({ lambda: s.mean }),
  },
  tex: { pdf: R`P(X=k)=\frac{\lambda^ke^{-\lambda}}{k!}`, cdf: R`F(k)=Q(k+1,\,\lambda)`, mean: R`\lambda`, variance: R`\lambda` },
  scipy: 'poisson(mu=λ)',
};

/* ======================================================================
   Negative binomial and geometric
   ====================================================================== */

function nbLogpmf(k, r, p) {
  if (!isInt(k) || k < 0) return -Infinity;
  if (k === 0) return r * Math.log(p);
  return Math.log(r / (r + k)) + logDbinomRaw(r, k + r, p, 1 - p);
}
const nbCdf = (k, r, p) => (k < 0 ? 0 : betaInc(r, k + 1, p, 1 - p)[0]);
const nbSf = (k, r, p) => (k < 0 ? 1 : betaInc(r, k + 1, p, 1 - p)[1]);

export const negbinomial = {
  id: 'negbinomial', label: 'Negative binomial', kind: 'discrete', group: 'Discrete',
  blurb: 'The failures before the r-th success; also counts more spread out than a Poisson (a Poisson whose mean is gamma-distributed).',
  params: [field('r', 'Successes r', 'pos'), field('p', 'Probability of success p', 'prob')],
  defaults: { r: 3, p: 0.4 },
  validate: (p) => (p.r > MAX_COUNT || p.r * (1 - p.p) / (p.p * p.p) > MAX_COUNT ? tooLarge('The spread of the counts') : ''),
  support: () => [0, Infinity],
  logpdf: (k, p) => nbLogpmf(k, p.r, p.p),
  cdf: (x, p) => nbCdf(Math.floor(x), p.r, p.p),
  sf: (x, p) => nbSf(Math.floor(x), p.r, p.p),
  quantile: (u, p) => {
    const m = p.r * (1 - p.p) / p.p; const sd = Math.sqrt(m / p.p);
    return discreteSearch((k) => reaches(nbCdf(k, p.r, p.p), u), cfGuess(u, m, sd, (2 - p.p) / Math.sqrt(p.r * (1 - p.p))), 0, Infinity);
  },
  isf: (q, p) => {
    const m = p.r * (1 - p.p) / p.p; const sd = Math.sqrt(m / p.p);
    return discreteSearch((k) => nbSf(k, p.r, p.p) <= q * (1 + 1e-12), cfGuess(1 - q, m, sd, 0), 0, Infinity);
  },
  mean: (p) => p.r * (1 - p.p) / p.p,
  variance: (p) => p.r * (1 - p.p) / (p.p * p.p),
  skewness: (p) => (2 - p.p) / Math.sqrt(p.r * (1 - p.p)),
  kurtosis: (p) => 6 / p.r + p.p * p.p / (p.r * (1 - p.p)),
  mode: (p) => (p.r > 1 ? Math.floor((p.r - 1) * (1 - p.p) / p.p) : 0),
  parameterisations: [
    { id: 'r-p', label: 'Successes r and probability p', fields: [field('r', 'Successes r', 'pos'), field('p', 'Probability of success p', 'prob')],
      to: (v) => ({ r: v.r, p: v.p }), from: (p) => ({ r: p.r, p: p.p }) },
    { id: 'mean-r', label: 'Mean and dispersion r', fields: [field('mean', 'Mean', 'pos'), field('r', 'Dispersion r', 'pos')],
      to: (v) => ({ r: v.r, p: v.r / (v.r + v.mean) }), from: (p) => ({ mean: p.r * (1 - p.p) / p.p, r: p.r }) },
    { id: 'mean-var', label: 'Mean and variance', fields: [field('mean', 'Mean', 'pos'), field('var', 'Variance (above the mean)', 'pos')],
      to: (v) => { if (!(v.var > v.mean)) throw new Error('The variance must be above the mean.'); return { r: v.mean * v.mean / (v.var - v.mean), p: v.mean / v.var }; },
      from: (p) => ({ mean: p.r * (1 - p.p) / p.p, var: p.r * (1 - p.p) / (p.p * p.p) }) },
  ],
  fit: {
    k: 2, keys: ['r', 'p'],
    applicable: (s) => countsApplicable(s) || (s.mean > 0 ? '' : 'needs at least one count above zero'),
    mle: (s) => {
      const [values, counts] = tally(s.x);
      const nll = (lr) => {
        const r = Math.exp(lr); const p = r / (r + s.mean);
        let ll = 0;
        for (let i = 0; i < values.length; i++) ll += counts[i] * nbLogpmf(values[i], r, p);
        return -ll;
      };
      const hi = Math.log(1e7);
      const got = brentMin(nll, Math.log(1e-4), hi, { tol: 1e-12 });
      const r = Math.exp(got.x);
      const atLimit = got.x > hi - 0.5;
      return { params: { r, p: r / (r + s.mean) }, atLimit, note: atLimit ? 'r at its limit: the counts are no more spread than a Poisson’s' : '' };
    },
    mom: (s) => (s.var > s.mean ? { r: s.mean * s.mean / (s.var - s.mean), p: s.mean / s.var } : { params: null, why: 'the variance is not above the mean, which a negative binomial needs' }),
  },
  tex: { pdf: R`P(X=k)=\binom{k+r-1}{k}p^r(1-p)^k`, cdf: R`F(k)=I_p(r,\,k+1)`, mean: R`\frac{r(1-p)}{p}`, variance: R`\frac{r(1-p)}{p^2}` },
  scipy: 'nbinom(n=r, p=p)',
};

export const geometric = {
  id: 'geometric', label: 'Geometric', kind: 'discrete', group: 'Discrete',
  blurb: 'The failures before the first success, each trial succeeding with probability p.',
  params: [field('p', 'Probability of success p', 'prob')],
  defaults: { p: 0.3 },
  validate: (p) => ((1 - p.p) / (p.p * p.p) > MAX_COUNT ? tooLarge('The spread of the counts') : ''),
  support: () => [0, Infinity],
  logpdf: (k, p) => (isInt(k) && k >= 0 ? Math.log(p.p) + k * Math.log1p(-p.p) : -Infinity),
  cdf: (x, p) => { const k = Math.floor(x); return k < 0 ? 0 : -Math.expm1((k + 1) * Math.log1p(-p.p)); },
  sf: (x, p) => { const k = Math.floor(x); return k < 0 ? 1 : Math.exp((k + 1) * Math.log1p(-p.p)); },
  quantile: (u, p) => discreteSearch((k) => reaches(-Math.expm1((k + 1) * Math.log1p(-p.p)), u), Math.log1p(-u) / Math.log1p(-p.p) - 1, 0, Infinity),
  isf: (q, p) => discreteSearch((k) => Math.exp((k + 1) * Math.log1p(-p.p)) <= q * (1 + 1e-12), Math.log(q) / Math.log1p(-p.p) - 1, 0, Infinity),
  mean: (p) => (1 - p.p) / p.p,
  variance: (p) => (1 - p.p) / (p.p * p.p),
  skewness: (p) => (2 - p.p) / Math.sqrt(1 - p.p),
  kurtosis: (p) => 6 + p.p * p.p / (1 - p.p),
  entropy: (p) => (-(1 - p.p) * Math.log1p(-p.p) - p.p * Math.log(p.p)) / p.p,
  mode: () => 0,
  parameterisations: [
    { id: 'p', label: 'Probability of success', fields: [field('p', 'Probability of success p', 'prob')], to: (v) => ({ p: v.p }), from: (p) => ({ p: p.p }) },
    { id: 'mean', label: 'Mean number of failures', fields: [field('mean', 'Mean', 'pos')], to: (v) => ({ p: 1 / (1 + v.mean) }), from: (p) => ({ mean: (1 - p.p) / p.p }) },
  ],
  fit: {
    k: 1, keys: ['p'],
    applicable: (s) => countsApplicable(s) || (s.mean > 0 ? '' : 'needs at least one count above zero'),
    mle: (s) => ({ p: 1 / (1 + s.mean) }),
    mom: (s) => ({ p: 1 / (1 + s.mean) }),
  },
  tex: { pdf: R`P(X=k)=p(1-p)^k`, cdf: R`F(k)=1-(1-p)^{k+1}`, mean: R`\frac{1-p}{p}`, variance: R`\frac{1-p}{p^2}` },
  scipy: 'geom(p, loc=−1)',
};

/* ======================================================================
   Hypergeometric
   ====================================================================== */

function hyperRange(p) { return [Math.max(0, p.n + p.K - p.N), Math.min(p.n, p.K)]; }

function hyperLogpmf(k, p) {
  const [lo, hi] = hyperRange(p);
  if (!isInt(k) || k < lo || k > hi) return -Infinity;
  const pr = p.n / p.N;
  const qr = 1 - pr;
  return logDbinomRaw(k, p.K, pr, qr) + logDbinomRaw(p.n - k, p.N - p.K, pr, qr) - logDbinomRaw(p.n, p.N, pr, qr);
}

/* P(X <= k) summed from whichever end of the support is nearer k. */
const hyperTable = (p, lo, hi) => sumTable(`hyper|${p.N}|${p.K}|${p.n}`, lo, hi, (j) => hyperLogpmf(j, p));
function hyperCdf(k, p) {
  const [lo, hi] = hyperRange(p);
  if (k < lo) return 0;
  if (k >= hi) return 1;
  const t = hyperTable(p, lo, hi);
  if (t) return tableCdf(t, k);
  const mean = p.n * p.K / p.N;
  if (k <= mean) {
    let s = 0;
    for (let j = lo; j <= k; j++) s += Math.exp(hyperLogpmf(j, p));
    return Math.min(1, s);
  }
  let s = 0;
  for (let j = k + 1; j <= hi; j++) s += Math.exp(hyperLogpmf(j, p));
  return Math.max(0, 1 - s);
}
function hyperSf(k, p) {
  const [lo, hi] = hyperRange(p);
  if (k < lo) return 1;
  if (k >= hi) return 0;
  const t = hyperTable(p, lo, hi);
  if (t) return tableSf(t, k);
  const mean = p.n * p.K / p.N;
  if (k >= mean) {
    let s = 0;
    for (let j = k + 1; j <= hi; j++) s += Math.exp(hyperLogpmf(j, p));
    return Math.min(1, s);
  }
  return Math.max(0, 1 - hyperCdf(k, p));
}

export const hypergeometric = {
  id: 'hypergeometric', label: 'Hypergeometric', kind: 'discrete', group: 'Discrete',
  blurb: 'Successes in n draws without replacement from N items of which K are successes: sampling for inspection.',
  params: [field('N', 'Population N', 'posint'), field('K', 'Successes in the population K', 'nonnegint'), field('n', 'Draws n', 'nonnegint')],
  defaults: { N: 50, K: 10, n: 12 },
  validate: (p) => {
    if (!(p.K <= p.N && p.n <= p.N)) return 'K and n cannot exceed N.';
    if (p.N > MAX_COUNT) return tooLarge('N');
    const [lo, hi] = hyperRange(p);
    return hi - lo > 1e7 ? 'The draws can take more than ten million values, too many to sum.' : '';
  },
  support: (p) => hyperRange(p),
  logpdf: (k, p) => hyperLogpmf(k, p),
  cdf: (x, p) => hyperCdf(Math.floor(x), p),
  sf: (x, p) => hyperSf(Math.floor(x), p),
  quantile: (u, p) => { const [lo, hi] = hyperRange(p); return discreteSearch((k) => reaches(hyperCdf(k, p), u), p.n * p.K / p.N, lo, hi); },
  isf: (q, p) => { const [lo, hi] = hyperRange(p); return discreteSearch((k) => hyperSf(k, p) <= q * (1 + 1e-12), p.n * p.K / p.N, lo, hi); },
  mean: (p) => p.n * p.K / p.N,
  variance: (p) => (p.N > 1 ? p.n * p.K * (p.N - p.K) * (p.N - p.n) / (p.N * p.N * (p.N - 1)) : 0),
  skewness: (p) => {
    const { N, K, n } = p;
    if (N <= 2) return undefined;
    return (N - 2 * K) * Math.sqrt(N - 1) * (N - 2 * n) / (Math.sqrt(n * K * (N - K) * (N - n)) * (N - 2));
  },
  mode: (p) => Math.floor((p.n + 1) * (p.K + 1) / (p.N + 2)),
  parameterisations: [
    { id: 'N-K-n', label: 'Population, successes and draws', fields: [field('N', 'Population N', 'posint'), field('K', 'Successes in the population K', 'nonnegint'), field('n', 'Draws n', 'nonnegint')],
      to: (v) => ({ N: v.N, K: v.K, n: v.n }), from: (p) => ({ N: p.N, K: p.K, n: p.n }) },
  ],
  fit: { applicable: () => 'is not fitted: its population and draws are known, not estimated' },
  tex: { pdf: R`P(X=k)=\frac{\binom Kk\binom{N-K}{n-k}}{\binom Nn}`, cdf: R`\text{a sum of the probabilities}`, mean: R`n\frac KN`, variance: R`n\frac KN\frac{N-K}{N}\frac{N-n}{N-1}` },
  scipy: 'hypergeom(M=N, n=K, N=n)',
};

/* ======================================================================
   Discrete uniform
   ====================================================================== */

export const discreteuniform = {
  id: 'discreteuniform', label: 'Discrete uniform', kind: 'discrete', group: 'Discrete',
  blurb: 'Every whole number from a to b equally likely: a fair die, a random index.',
  params: [field('a', 'Lowest a', 'int'), field('b', 'Highest b', 'int')],
  defaults: { a: 1, b: 6 },
  validate: (p) => (!(p.b >= p.a) ? 'The highest value cannot be below the lowest.' : Math.max(Math.abs(p.a), Math.abs(p.b)) > MAX_COUNT ? tooLarge('A value') : ''),
  support: (p) => [p.a, p.b],
  logpdf: (k, p) => (isInt(k) && k >= p.a && k <= p.b ? -Math.log(p.b - p.a + 1) : -Infinity),
  cdf: (x, p) => { const k = Math.floor(x); return k < p.a ? 0 : k >= p.b ? 1 : (k - p.a + 1) / (p.b - p.a + 1); },
  sf: (x, p) => { const k = Math.floor(x); return k < p.a ? 1 : k >= p.b ? 0 : (p.b - k) / (p.b - p.a + 1); },
  quantile: (u, p) => { const N = p.b - p.a + 1; return Math.min(p.b, Math.max(p.a, p.a + Math.ceil(u * N * (1 - 1e-12)) - 1)); },
  isf: (q, p) => { const N = p.b - p.a + 1; return Math.min(p.b, Math.max(p.a, p.b - Math.floor(q * N * (1 + 1e-12)))); },
  mean: (p) => (p.a + p.b) / 2,
  variance: (p) => { const N = p.b - p.a + 1; return (N * N - 1) / 12; },
  skewness: () => 0,
  kurtosis: (p) => { const N = p.b - p.a + 1; return N > 1 ? -6 * (N * N + 1) / (5 * (N * N - 1)) : NaN; },
  entropy: (p) => Math.log(p.b - p.a + 1),
  mode: (p) => p.a,
  modeText: (p) => (p.b > p.a ? 'every value from a to b' : ''),
  parameterisations: [
    { id: 'a-b', label: 'Lowest and highest', fields: [field('a', 'Lowest a', 'int'), field('b', 'Highest b', 'int')], to: (v) => ({ a: v.a, b: v.b }), from: (p) => ({ a: p.a, b: p.b }) },
  ],
  fit: {
    k: 2, regular: false,
    applicable: (s) => (s.allInteger ? '' : 'needs whole numbers'),
    mle: (s) => ({ params: { a: s.min, b: s.max }, edges: true }),
    mom: (s) => { const N = Math.max(1, Math.round(Math.sqrt(12 * s.var + 1))); const a = Math.round(s.mean - (N - 1) / 2); return { a, b: a + N - 1 }; },
  },
  tex: { pdf: R`P(X=k)=\frac{1}{b-a+1},\ k=a,\dots,b`, cdf: R`F(k)=\frac{k-a+1}{b-a+1}`, mean: R`\frac{a+b}{2}`, variance: R`\frac{(b-a+1)^2-1}{12}` },
  scipy: 'randint(a, b+1)',
};

/* ======================================================================
   Beta-binomial
   ====================================================================== */

function bbLogpmf(k, p) {
  if (!isInt(k) || k < 0 || k > p.n) return -Infinity;
  return lchoose(p.n, k) + lbeta(k + p.alpha, p.n - k + p.beta) - lbeta(p.alpha, p.beta);
}
const bbTable = (p) => sumTable(`bb|${p.n}|${p.alpha}|${p.beta}`, 0, p.n, (j) => bbLogpmf(j, p));
function bbCdf(k, p) {
  if (k < 0) return 0;
  if (k >= p.n) return 1;
  const t = bbTable(p);
  if (t) return tableCdf(t, k);
  let s = 0;
  if (k < p.n / 2) { for (let j = 0; j <= k; j++) s += Math.exp(bbLogpmf(j, p)); return Math.min(1, s); }
  for (let j = k + 1; j <= p.n; j++) s += Math.exp(bbLogpmf(j, p));
  return Math.max(0, 1 - s);
}
function bbSf(k, p) {
  if (k < 0) return 1;
  if (k >= p.n) return 0;
  const t = bbTable(p);
  if (t) return tableSf(t, k);
  let s = 0;
  if (k >= p.n / 2) { for (let j = k + 1; j <= p.n; j++) s += Math.exp(bbLogpmf(j, p)); return Math.min(1, s); }
  return Math.max(0, 1 - bbCdf(k, p));
}

export const betabinomial = {
  id: 'betabinomial', label: 'Beta-binomial', kind: 'discrete', group: 'Discrete',
  blurb: 'Successes in n trials whose probability of success itself varies as a beta: a binomial with more spread.',
  params: [field('n', 'Trials n', 'nonnegint'), field('alpha', 'Shape α', 'pos'), field('beta', 'Shape β', 'pos')],
  defaults: { n: 10, alpha: 2, beta: 3 },
  validate: (p) => (p.n > 1e7 ? 'n is too large: the beta-binomial is summed term by term, up to ten million trials.' : ''),
  support: (p) => [0, p.n],
  logpdf: (k, p) => bbLogpmf(k, p),
  cdf: (x, p) => bbCdf(Math.floor(x), p),
  sf: (x, p) => bbSf(Math.floor(x), p),
  quantile: (u, p) => discreteSearch((k) => reaches(bbCdf(k, p), u), p.n * p.alpha / (p.alpha + p.beta), 0, p.n),
  isf: (q, p) => discreteSearch((k) => bbSf(k, p) <= q * (1 + 1e-12), p.n * p.alpha / (p.alpha + p.beta), 0, p.n),
  mean: (p) => p.n * p.alpha / (p.alpha + p.beta),
  variance: (p) => { const s = p.alpha + p.beta; return p.n * p.alpha * p.beta * (s + p.n) / (s * s * (s + 1)); },
  skewness: (p) => {
    const { n, alpha: a, beta: b } = p;
    if (n === 0) return NaN;
    return (a + b + 2 * n) * (b - a) / (a + b + 2) * Math.sqrt((1 + a + b) / (n * a * b * (n + a + b)));
  },
  parameterisations: [
    { id: 'n-shapes', label: 'Trials and shapes α, β', fields: [field('n', 'Trials n', 'nonnegint'), field('alpha', 'Shape α', 'pos'), field('beta', 'Shape β', 'pos')],
      to: (v) => ({ n: v.n, alpha: v.alpha, beta: v.beta }), from: (p) => ({ n: p.n, alpha: p.alpha, beta: p.beta }) },
    { id: 'n-mean-rho', label: 'Trials, mean probability and correlation', fields: [field('n', 'Trials n', 'nonnegint'), field('pi', 'Mean probability π', 'prob'), field('rho', 'Intra-class correlation ρ', 'prob')],
      to: (v) => { const s = 1 / v.rho - 1; return { n: v.n, alpha: v.pi * s, beta: (1 - v.pi) * s }; },
      from: (p) => ({ n: p.n, pi: p.alpha / (p.alpha + p.beta), rho: 1 / (p.alpha + p.beta + 1) }) },
  ],
  fit: {
    k: 2, keys: ['alpha', 'beta'],
    applicable: (s, opts = {}) => countsApplicable(s) || (Number.isInteger(opts.trials) && opts.trials > 0 ? '' : 'needs the number of trials n, given in the fit settings'),
    mle: (s, opts = {}) => {
      const n = opts.trials;
      if (!(Number.isInteger(n) && n > 0)) return null;
      if (s.max > n) return { params: null, why: `a count is above the ${n} trials given` };
      const [values, counts] = tally(s.x);
      const nll = ([la, lb]) => {
        const p = { n, alpha: Math.exp(la), beta: Math.exp(lb) };
        let ll = 0;
        for (let i = 0; i < values.length; i++) ll += counts[i] * bbLogpmf(values[i], p);
        return -ll;
      };
      const m = Math.min(0.99, Math.max(0.01, s.mean / n));
      const got = nelderMead(nll, [Math.log(2 * m), Math.log(2 * (1 - m))], { steps: [0.5, 0.5] });
      return { params: { n, alpha: Math.exp(got.x[0]), beta: Math.exp(got.x[1]) }, note: `n = ${n} given` };
    },
    mom: (s, opts = {}) => {
      const n = opts.trials;
      if (!(Number.isInteger(n) && n > 0)) return null;
      const m1 = s.mean;
      const m2 = s.var + s.mean * s.mean;
      const den = n * (m2 / m1 - m1 - 1) + m1;
      const a = (n * m1 - m2) / den;
      const b = (n - m1) * (n - m2 / m1) / den;
      return a > 0 && b > 0 ? { params: { n, alpha: a, beta: b }, note: `n = ${n} given` } : { params: null, why: 'the sample is less spread than a binomial; no beta-binomial matches it' };
    },
  },
  tex: { pdf: R`P(X=k)=\binom nk\frac{B(k+\alpha,\,n-k+\beta)}{B(\alpha,\beta)}`, cdf: R`\text{a sum of the probabilities}`, mean: R`\frac{n\alpha}{\alpha+\beta}`, variance: R`\frac{n\alpha\beta(\alpha+\beta+n)}{(\alpha+\beta)^2(\alpha+\beta+1)}` },
  scipy: 'betabinom(n, a=α, b=β)',
};

export const DISCRETE = [bernoulli, binomial, poisson, negbinomial, geometric, hypergeometric, discreteuniform, betabinomial];
