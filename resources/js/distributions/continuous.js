/* ==========================================================================
   distributions.html: THE CONTINUOUS FAMILIES

   Each family is an object; families.js lists what one may define. A
   function a family leaves out, or one that returns undefined, is worked
   out numerically by dist.js (quantiles by root finding, moments and
   entropy by integrating over the quantile function), so a closed form here
   is a shortcut and a precision gain, never a requirement. NaN means the
   quantity does not exist (the Cauchy's mean); Infinity that it is
   infinite.

   The SciPy line of each family is the same distribution in
   scipy.stats, for anyone checking a number in Python; the tests compare
   with it.
   ========================================================================== */

import {
  EULER, LN2, LN10, LN_SQRT_2PI, LN_2PI,
  normPdf, normLogPdf, normCdf, normSf, normLogCdf, normLogSf, normQuantile, normIsf,
  erf, erfc, lgamma, digamma, trigamma, lbeta, gammaFn,
  logDpoisRaw, gammaInc, gammaIncInv, betaInc, betaIncInv, log1mexp, log1pexp,
} from './special.js';
import { brentRoot, nelderMead, newtonSystem } from './numeric.js';
import { field, locationScale, logOf, centralZ, logistic, logit, describeSample } from './kit.js';
import { triangleMle, triangleMom, logTriangleMom, logUniformMom, solveShape } from './shapes.js';

const R = String.raw;
const SKEW_GUMBEL = 1.1395470994046486;
const Z95 = 1.6448536269514722;
const SQRT2 = Math.SQRT2;

const sq = (v) => v * v;
/* A value that must be finite and positive, or an error for the user. */
function need(cond, message) { if (!cond) throw new Error(message); }

/* ======================================================================
   Normal
   ====================================================================== */

const stdNormal = {
  logpdf: (z) => normLogPdf(z),
  cdf: (z) => normCdf(z),
  sf: (z) => normSf(z),
  logcdf: (z) => normLogCdf(z),
  logsf: (z) => normLogSf(z),
  quantile: (u) => normQuantile(u),
  isf: (q) => normIsf(q),
  mean: () => 0,
  variance: () => 1,
  skewness: () => 0,
  kurtosis: () => 0,
  entropy: () => 0.5 + LN_SQRT_2PI,
  mode: () => 0,
  median: () => 0,
};

export const normal = locationScale({
  id: 'normal', label: 'Normal', kind: 'continuous', group: 'General',
  blurb: 'The bell curve, symmetric about its mean: the sum of many small independent effects.',
  params: [field('mu', 'Mean μ', 'real'), field('sigma', 'Standard deviation σ', 'pos')],
  defaults: { mu: 0, sigma: 1 },
  parameterisations: [
    { id: 'mu-sigma', label: 'Mean μ and SD σ', fields: [field('mu', 'Mean μ', 'real'), field('sigma', 'SD σ', 'pos')],
      to: (v) => ({ mu: v.mu, sigma: v.sigma }), from: (p) => ({ mu: p.mu, sigma: p.sigma }) },
    { id: 'mean-var', label: 'Mean and variance', fields: [field('mean', 'Mean', 'real'), field('var', 'Variance σ²', 'pos')],
      to: (v) => ({ mu: v.mean, sigma: Math.sqrt(v.var) }), from: (p) => ({ mean: p.mu, var: p.sigma * p.sigma }) },
    { id: 'mean-cv', label: 'Mean and CV', fields: [field('mean', 'Mean', 'real'), field('cv', 'Coefficient of variation', 'pos')],
      to: (v) => { need(v.mean !== 0, 'A mean of 0 has no coefficient of variation.'); return { mu: v.mean, sigma: Math.abs(v.mean) * v.cv }; },
      from: (p) => ({ mean: p.mu, cv: p.mu !== 0 ? p.sigma / Math.abs(p.mu) : NaN }) },
    { id: 'interval', label: 'Central interval', fields: [field('lower', 'Lower end', 'real'), field('upper', 'Upper end', 'real'), field('coverage', 'Coverage (%)', 'pct')],
      to: (v) => { need(v.upper > v.lower, 'The upper end must be above the lower end.'); const z = centralZ(v.coverage); return { mu: (v.lower + v.upper) / 2, sigma: (v.upper - v.lower) / (2 * z) }; },
      from: (p, v) => { const c = v && v.coverage > 0 && v.coverage < 100 ? v.coverage : 95; const z = centralZ(c); return { lower: p.mu - z * p.sigma, upper: p.mu + z * p.sigma, coverage: c }; } },
  ],
  free: { keys: ['mu', 'sigma'], to: (p) => [p.mu, Math.log(p.sigma)], from: (z) => ({ mu: z[0], sigma: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    mle: (s) => ({ mu: s.mean, sigma: s.sd }),
    mom: (s) => ({ mu: s.mean, sigma: s.sd }),
  },
  tex: {
    pdf: R`f(x)=\frac{1}{\sigma\sqrt{2\pi}}\exp\!\left(-\frac{(x-\mu)^2}{2\sigma^2}\right)`,
    cdf: R`F(x)=\Phi\!\left(\frac{x-\mu}{\sigma}\right)=\tfrac12\operatorname{erfc}\!\left(-\frac{x-\mu}{\sigma\sqrt2}\right)`,
    mean: R`\mu`, variance: R`\sigma^2`,
  },
  scipy: 'norm(loc=μ, scale=σ)',
}, stdNormal, { loc: 'mu', scale: 'sigma' });

/* ======================================================================
   Lognormal
   ====================================================================== */

export const lognormal = logOf(normal, {
  id: 'lognormal', label: 'Lognormal', kind: 'continuous', group: 'Positive',
  blurb: 'A quantity whose logarithm is normal: a product of many independent factors, skewed to the right.',
  params: [field('mu', 'μ (mean of ln X)', 'real'), field('sigma', 'σ (SD of ln X)', 'pos')],
  defaults: { mu: 0, sigma: 1 },
  mean: (p) => Math.exp(p.mu + p.sigma * p.sigma / 2),
  variance: (p) => Math.expm1(p.sigma * p.sigma) * Math.exp(2 * p.mu + p.sigma * p.sigma),
  skewness: (p) => { const e = Math.exp(p.sigma * p.sigma); return (e + 2) * Math.sqrt(Math.expm1(p.sigma * p.sigma)); },
  kurtosis: (p) => { const s2 = p.sigma * p.sigma; return Math.exp(4 * s2) + 2 * Math.exp(3 * s2) + 3 * Math.exp(2 * s2) - 6; },
  mode: (p) => Math.exp(p.mu - p.sigma * p.sigma),
  parameterisations: [
    { id: 'mu-sigma', label: 'μ and σ of ln X', fields: [field('mu', 'μ (mean of ln X)', 'real'), field('sigma', 'σ (SD of ln X)', 'pos')],
      to: (v) => ({ mu: v.mu, sigma: v.sigma }), from: (p) => ({ mu: p.mu, sigma: p.sigma }) },
    { id: 'log10', label: 'Mean and SD of log₁₀ X', fields: [field('m10', 'Mean of log₁₀ X', 'real'), field('s10', 'SD of log₁₀ X', 'pos')],
      to: (v) => ({ mu: v.m10 * LN10, sigma: v.s10 * LN10 }), from: (p) => ({ m10: p.mu / LN10, s10: p.sigma / LN10 }) },
    { id: 'gm-gsd', label: 'Geometric mean and GSD', fields: [field('gm', 'Geometric mean (median)', 'pos'), field('gsd', 'Geometric SD', 'gt1')],
      to: (v) => ({ mu: Math.log(v.gm), sigma: Math.log(v.gsd) }), from: (p) => ({ gm: Math.exp(p.mu), gsd: Math.exp(p.sigma) }) },
    { id: 'mean-sd', label: 'Mean and SD', fields: [field('mean', 'Mean', 'pos'), field('sd', 'Standard deviation', 'pos')],
      to: (v) => { const s2 = Math.log1p(sq(v.sd / v.mean)); return { mu: Math.log(v.mean) - s2 / 2, sigma: Math.sqrt(s2) }; },
      from: (p) => ({ mean: Math.exp(p.mu + p.sigma * p.sigma / 2), sd: Math.exp(p.mu + p.sigma * p.sigma / 2) * Math.sqrt(Math.expm1(p.sigma * p.sigma)) }) },
    { id: 'mean-cv', label: 'Mean and CV', fields: [field('mean', 'Mean', 'pos'), field('cv', 'Coefficient of variation', 'pos')],
      to: (v) => { const s2 = Math.log1p(v.cv * v.cv); return { mu: Math.log(v.mean) - s2 / 2, sigma: Math.sqrt(s2) }; },
      from: (p) => ({ mean: Math.exp(p.mu + p.sigma * p.sigma / 2), cv: Math.sqrt(Math.expm1(p.sigma * p.sigma)) }) },
    { id: 'median-ef', label: 'Median and error factor', fields: [field('median', 'Median', 'pos'), field('ef', 'Error factor (P95 / P50)', 'gt1')],
      to: (v) => ({ mu: Math.log(v.median), sigma: Math.log(v.ef) / Z95 }), from: (p) => ({ median: Math.exp(p.mu), ef: Math.exp(Z95 * p.sigma) }) },
    { id: 'interval', label: 'Central interval', fields: [field('lower', 'Lower end', 'pos'), field('upper', 'Upper end', 'pos'), field('coverage', 'Coverage (%)', 'pct')],
      to: (v) => { need(v.upper > v.lower, 'The upper end must be above the lower end.'); const z = centralZ(v.coverage); return { mu: (Math.log(v.lower) + Math.log(v.upper)) / 2, sigma: (Math.log(v.upper) - Math.log(v.lower)) / (2 * z) }; },
      from: (p, v) => { const c = v && v.coverage > 0 && v.coverage < 100 ? v.coverage : 95; const z = centralZ(c); return { lower: Math.exp(p.mu - z * p.sigma), upper: Math.exp(p.mu + z * p.sigma), coverage: c }; } },
  ],
  free: { keys: ['mu', 'sigma'], to: (p) => [p.mu, Math.log(p.sigma)], from: (z) => ({ mu: z[0], sigma: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    applicable: (s) => (s.positive ? '' : 'needs every value above zero'),
    mle: (s) => ({ mu: s.meanLog, sigma: s.sdLog }),
    mom: (s) => { const s2 = Math.log1p(s.var / (s.mean * s.mean)); return { mu: Math.log(s.mean) - s2 / 2, sigma: Math.sqrt(s2) }; },
  },
  tex: {
    pdf: R`f(x)=\frac{1}{x\sigma\sqrt{2\pi}}\exp\!\left(-\frac{(\ln x-\mu)^2}{2\sigma^2}\right),\ x>0`,
    cdf: R`F(x)=\Phi\!\left(\frac{\ln x-\mu}{\sigma}\right)`,
    mean: R`e^{\mu+\sigma^2/2}`, variance: R`\left(e^{\sigma^2}-1\right)e^{2\mu+\sigma^2}`,
  },
  scipy: 'lognorm(s=σ, scale=exp(μ))',
}, (p) => p, (q) => ({ mu: q.mu, sigma: q.sigma }));

/* ======================================================================
   Uniform and log-uniform
   ====================================================================== */

export const uniform = {
  id: 'uniform', label: 'Uniform', kind: 'continuous', group: 'Bounded',
  blurb: 'Every value between the two ends is as likely as any other.',
  params: [field('a', 'Minimum a', 'real'), field('b', 'Maximum b', 'real')],
  defaults: { a: 0, b: 1 },
  validate: (p) => (p.b > p.a ? '' : 'The maximum must be above the minimum.'),
  support: (p) => [p.a, p.b],
  logpdf: (x, p) => (x >= p.a && x <= p.b ? -Math.log(p.b - p.a) : -Infinity),
  cdf: (x, p) => (x <= p.a ? 0 : x >= p.b ? 1 : (x - p.a) / (p.b - p.a)),
  sf: (x, p) => (x <= p.a ? 1 : x >= p.b ? 0 : (p.b - x) / (p.b - p.a)),
  quantile: (u, p) => p.a + u * (p.b - p.a),
  isf: (q, p) => p.b - q * (p.b - p.a),
  mean: (p) => (p.a + p.b) / 2,
  variance: (p) => sq(p.b - p.a) / 12,
  skewness: () => 0,
  kurtosis: () => -1.2,
  entropy: (p) => Math.log(p.b - p.a),
  mode: (p) => (p.a + p.b) / 2,
  modeText: () => 'any value from a to b',
  median: (p) => (p.a + p.b) / 2,
  parameterisations: [
    { id: 'a-b', label: 'Minimum and maximum', fields: [field('a', 'Minimum a', 'real'), field('b', 'Maximum b', 'real')],
      to: (v) => ({ a: v.a, b: v.b }), from: (p) => ({ a: p.a, b: p.b }) },
    { id: 'mean-half', label: 'Mean and half-width', fields: [field('mean', 'Mean', 'real'), field('half', 'Half-width', 'pos')],
      to: (v) => ({ a: v.mean - v.half, b: v.mean + v.half }), from: (p) => ({ mean: (p.a + p.b) / 2, half: (p.b - p.a) / 2 }) },
    { id: 'mean-sd', label: 'Mean and SD', fields: [field('mean', 'Mean', 'real'), field('sd', 'Standard deviation', 'pos')],
      to: (v) => ({ a: v.mean - Math.sqrt(3) * v.sd, b: v.mean + Math.sqrt(3) * v.sd }), from: (p) => ({ mean: (p.a + p.b) / 2, sd: (p.b - p.a) / Math.sqrt(12) }) },
  ],
  free: { keys: ['a', 'b'], to: (p) => [p.a, Math.log(p.b - p.a)], from: (z) => ({ a: z[0], b: z[0] + Math.exp(z[1]) }) },
  fit: {
    k: 2, regular: false,
    mle: (s) => ({ params: { a: s.min, b: s.max }, edges: true }),
    mom: (s) => ({ a: s.mean - Math.sqrt(3) * s.sd, b: s.mean + Math.sqrt(3) * s.sd }),
  },
  tex: {
    pdf: R`f(x)=\frac{1}{b-a},\ a\le x\le b`, cdf: R`F(x)=\frac{x-a}{b-a}`,
    mean: R`\frac{a+b}{2}`, variance: R`\frac{(b-a)^2}{12}`,
  },
  scipy: 'uniform(loc=a, scale=b−a)',
};

export const loguniform = logOf(uniform, {
  id: 'loguniform', label: 'Log-uniform', kind: 'continuous', group: 'Log scale',
  blurb: 'Uniform in the logarithm: every decade between the ends is as likely as any other. For a quantity known only to within orders of magnitude.',
  params: [field('a', 'Minimum a', 'pos'), field('b', 'Maximum b', 'pos')],
  defaults: { a: 1, b: 100 },
  validate: (p) => (p.a > 0 && p.b > p.a ? '' : 'Need 0 < minimum < maximum.'),
  /* ln(x/a) and ln(b/x) as log1p of differences, for precision at the ends */
  cdf: (x, p) => (x <= p.a ? 0 : x >= p.b ? 1 : Math.log1p((x - p.a) / p.a) / Math.log1p((p.b - p.a) / p.a)),
  sf: (x, p) => (x <= p.a ? 1 : x >= p.b ? 0 : Math.log1p((p.b - x) / x) / Math.log1p((p.b - p.a) / p.a)),
  quantile: (u, p) => p.a + p.a * Math.expm1(u * Math.log1p((p.b - p.a) / p.a)),
  isf: (q, p) => p.b + p.b * Math.expm1(-q * Math.log1p((p.b - p.a) / p.a)),
  mean: (p) => (p.b - p.a) / Math.log1p((p.b - p.a) / p.a),
  mode: (p) => p.a,
  parameterisations: [
    { id: 'a-b', label: 'Minimum and maximum', fields: [field('a', 'Minimum a', 'pos'), field('b', 'Maximum b', 'pos')],
      to: (v) => ({ a: v.a, b: v.b }), from: (p) => ({ a: p.a, b: p.b }) },
    { id: 'log10', label: 'log₁₀ of minimum and maximum', fields: [field('la', 'log₁₀ minimum', 'real'), field('lb', 'log₁₀ maximum', 'real')],
      to: (v) => ({ a: Math.pow(10, v.la), b: Math.pow(10, v.lb) }), from: (p) => ({ la: Math.log10(p.a), lb: Math.log10(p.b) }) },
  ],
  free: { keys: ['a', 'b'], to: (p) => [Math.log(p.a), Math.log(Math.log(p.b) - Math.log(p.a))], from: (z) => ({ a: Math.exp(z[0]), b: Math.exp(z[0] + Math.exp(z[1])) }) },
  fit: {
    k: 2, regular: false,
    applicable: (s) => (s.positive ? '' : 'needs every value above zero'),
    mle: (s) => (s.positive ? { params: { a: s.min, b: s.max }, edges: true } : null),
    mom: (s) => { const got = logUniformMom(s); return got ? { a: got.min, b: got.max } : null; },
  },
  tex: {
    pdf: R`f(x)=\frac{1}{x\,(\ln b-\ln a)},\ a\le x\le b`, cdf: R`F(x)=\frac{\ln x-\ln a}{\ln b-\ln a}`,
    mean: R`\frac{b-a}{\ln b-\ln a}`, variance: R`\frac{b^2-a^2}{2(\ln b-\ln a)}-\left(\frac{b-a}{\ln b-\ln a}\right)^2`,
  },
  scipy: 'loguniform(a, b)',
}, (p) => ({ a: Math.log(p.a), b: Math.log(p.b) }));

/* ======================================================================
   Triangular, double-triangular and their log forms
   ====================================================================== */

function triangleValidate(p) {
  if (!(p.b > p.a)) return 'The maximum must be above the minimum.';
  if (!(p.c >= p.a && p.c <= p.b)) return 'The mode must lie between the minimum and the maximum.';
  return '';
}

const triFields = () => [field('a', 'Minimum a', 'real'), field('c', 'Mode c', 'real'), field('b', 'Maximum b', 'real')];
const triFree = {
  keys: ['a', 'c', 'b'],
  to: (p) => { const r = Math.min(1 - 1e-12, Math.max(1e-12, (p.c - p.a) / (p.b - p.a))); return [p.a, Math.log(p.b - p.a), logit(r)]; },
  from: (z) => { const w = Math.exp(z[1]); return { a: z[0], c: z[0] + w * logistic(z[2]), b: z[0] + w }; },
};

export const triangular = {
  id: 'triangular', label: 'Triangular', kind: 'continuous', group: 'Bounded',
  blurb: 'A straight rise to the most likely value and a straight fall from it: "about this, no less than that, no more than the other".',
  params: triFields(),
  defaults: { a: 0, c: 1, b: 3 },
  validate: triangleValidate,
  support: (p) => [p.a, p.b],
  logpdf: (x, p) => {
    if (x < p.a || x > p.b) return -Infinity;
    if (x < p.c) return Math.log(2 * (x - p.a) / ((p.b - p.a) * (p.c - p.a)));
    if (x === p.c) return Math.log(2 / (p.b - p.a));
    return Math.log(2 * (p.b - x) / ((p.b - p.a) * (p.b - p.c)));
  },
  /* Past the mode the CDF is written from the mode's own probability
     upwards rather than as 1 minus the far side, which keeps its precision
     when the mode is at the minimum (and the sf likewise when it is at the
     maximum). */
  cdf: (x, p) => {
    if (x <= p.a) return 0;
    if (x >= p.b) return 1;
    if (x <= p.c) return sq(x - p.a) / ((p.b - p.a) * (p.c - p.a));
    const s = sq(p.b - x) / ((p.b - p.a) * (p.b - p.c));
    return s < 0.5 ? 1 - s : (p.c - p.a) / (p.b - p.a) + (x - p.c) * (2 * (p.b - p.c) - (x - p.c)) / ((p.b - p.a) * (p.b - p.c));
  },
  sf: (x, p) => {
    if (x <= p.a) return 1;
    if (x >= p.b) return 0;
    if (x > p.c) return sq(p.b - x) / ((p.b - p.a) * (p.b - p.c));
    const f = sq(x - p.a) / ((p.b - p.a) * (p.c - p.a));
    return f < 0.5 ? 1 - f : (p.b - p.c) / (p.b - p.a) + (p.c - x) * (2 * (p.c - p.a) - (p.c - x)) / ((p.b - p.a) * (p.c - p.a));
  },
  quantile: (u, p) => {
    const fc = (p.c - p.a) / (p.b - p.a);
    if (u <= fc) return p.a + Math.sqrt(u * (p.b - p.a) * (p.c - p.a));
    const r = Math.sqrt((1 - u) * (p.b - p.a) * (p.b - p.c));
    return p.a + (p.b - p.a) * ((p.c - p.a) + u * (p.b - p.c)) / ((p.b - p.a) + r);
  },
  isf: (q, p) => {
    const gc = (p.b - p.c) / (p.b - p.a);
    if (q <= gc) return p.b - Math.sqrt(q * (p.b - p.a) * (p.b - p.c));
    const r = Math.sqrt((1 - q) * (p.b - p.a) * (p.c - p.a));
    return p.b - (p.b - p.a) * ((p.b - p.c) + q * (p.c - p.a)) / ((p.b - p.a) + r);
  },
  mean: (p) => (p.a + p.b + p.c) / 3,
  variance: (p) => (p.a * p.a + p.b * p.b + p.c * p.c - p.a * p.b - p.a * p.c - p.b * p.c) / 18,
  skewness: (p) => {
    const { a, b, c } = p;
    const q = a * a + b * b + c * c - a * b - a * c - b * c;
    return SQRT2 * (a + b - 2 * c) * (2 * a - b - c) * (a - 2 * b + c) / (5 * Math.pow(q, 1.5));
  },
  kurtosis: () => -0.6,
  entropy: (p) => 0.5 + Math.log((p.b - p.a) / 2),
  breaks: (p) => [(p.c - p.a) / (p.b - p.a)],
  mode: (p) => p.c,
  median: (p) => (p.c >= (p.a + p.b) / 2 ? p.a + Math.sqrt((p.b - p.a) * (p.c - p.a) / 2) : p.b - Math.sqrt((p.b - p.a) * (p.b - p.c) / 2)),
  parameterisations: [
    { id: 'a-c-b', label: 'Minimum, mode and maximum', fields: triFields(),
      to: (v) => ({ a: v.a, c: v.c, b: v.b }), from: (p) => ({ a: p.a, c: p.c, b: p.b }) },
  ],
  free: triFree,
  fit: {
    k: 3, regular: false,
    mle: (s) => { const g = triangleMle(s.x, false); return { a: g.min, c: g.mode, b: g.max }; },
    mom: (s) => {
      const g = triangleMom(s, false);
      return { params: { a: g.min, c: g.mode, b: g.max }, note: g.clamped ? 'the sample is more skewed than a triangle can be; this is the most skewed one' : '' };
    },
  },
  tex: {
    pdf: R`f(x)=\begin{cases}\frac{2(x-a)}{(b-a)(c-a)} & a\le x<c\\[2pt] \frac{2(b-x)}{(b-a)(b-c)} & c\le x\le b\end{cases}`,
    cdf: R`F(x)=\begin{cases}\frac{(x-a)^2}{(b-a)(c-a)} & x\le c\\[2pt] 1-\frac{(b-x)^2}{(b-a)(b-c)} & x>c\end{cases}`,
    mean: R`\frac{a+b+c}{3}`, variance: R`\frac{a^2+b^2+c^2-ab-ac-bc}{18}`,
  },
  scipy: 'triang(c=(c−a)/(b−a), loc=a, scale=b−a)',
};

export const logtriangular = logOf(triangular, {
  id: 'logtriangular', label: 'Log-triangular', kind: 'continuous', group: 'Log scale',
  blurb: 'A triangle in the logarithm: the shape a quantity known to within a factor gets, such as a sorption coefficient.',
  params: [field('a', 'Minimum a', 'pos'), field('c', 'Mode c (of the log)', 'pos'), field('b', 'Maximum b', 'pos')],
  defaults: { a: 0.1, c: 1, b: 100 },
  validate: (p) => (p.a > 0 ? triangleValidate(p) : 'The minimum must be above zero.'),
  /* Of X itself: e^(a'+1) while the rise in ln x reaches that far, else c. */
  mode: (p) => Math.exp(Math.min(Math.log(p.a) + 1, Math.log(p.c))),
  parameterisations: [
    { id: 'a-c-b', label: 'Minimum, mode (of ln X) and maximum', fields: [field('a', 'Minimum a', 'pos'), field('c', 'Mode c (of ln X)', 'pos'), field('b', 'Maximum b', 'pos')],
      to: (v) => ({ a: v.a, c: v.c, b: v.b }), from: (p) => ({ a: p.a, c: p.c, b: p.b }) },
  ],
  free: {
    keys: ['a', 'c', 'b'],
    to: (p) => triFree.to({ a: Math.log(p.a), c: Math.log(p.c), b: Math.log(p.b) }),
    from: (z) => { const q = triFree.from(z); return { a: Math.exp(q.a), c: Math.exp(q.c), b: Math.exp(q.b) }; },
  },
  fit: {
    k: 3, regular: false,
    applicable: (s) => (s.positive ? '' : 'needs every value above zero'),
    mle: (s) => {
      const g = triangleMle(Float64Array.from(s.x, Math.log), false);
      const mode = g.at < 0 ? Math.exp(g.min) : g.at >= s.n ? Math.exp(g.max) : s.x[g.at];
      return { a: Math.exp(g.min), c: mode, b: Math.exp(g.max) };
    },
    mom: (s) => {
      const g = logTriangleMom(s, false);
      if (!g) return null;
      return { params: { a: g.min, c: g.mode, b: g.max }, note: g.clamped ? 'no log-triangle has both the sample’s spread and its skewness; this is the nearest' : '' };
    },
  },
  tex: {
    pdf: R`f(x)=\frac{g(\ln x)}{x},\ g=\text{triangular on }[\ln a,\ln b]\text{ with mode }\ln c`,
    cdf: R`F(x)=G(\ln x)`,
    mean: R`\text{by numerical integration}`, variance: R`\text{by numerical integration}`,
  },
  scipy: 'no direct equivalent; ln X is triang(c=(ln c−ln a)/(ln b−ln a), loc=ln a, scale=ln b−ln a)',
}, (p) => ({ a: Math.log(p.a), c: Math.log(p.c), b: Math.log(p.b) }));

/* The double triangle as an even mixture of the right triangles (a, c, c)
   and (c, c, b): each has variance w^2/18, third central moment -+w^3/135 and
   fourth 2.4 times its variance squared, about its own mean. */
function dtriMoments(p) {
  const comps = [
    { m: (p.a + 2 * p.c) / 3, v: sq(p.c - p.a) / 18, m3: -Math.pow(p.c - p.a, 3) / 135 },
    { m: (2 * p.c + p.b) / 3, v: sq(p.b - p.c) / 18, m3: Math.pow(p.b - p.c, 3) / 135 },
  ];
  const mean = 0.5 * (comps[0].m + comps[1].m);
  let c2 = 0; let c3 = 0; let c4 = 0;
  for (const { m, v, m3 } of comps) {
    const d = m - mean;
    const m4 = 2.4 * v * v;
    c2 += 0.5 * (v + d * d);
    c3 += 0.5 * (m3 + 3 * v * d + d * d * d);
    c4 += 0.5 * (m4 + 4 * m3 * d + 6 * v * d * d + d ** 4);
  }
  return { mean, variance: c2, skewness: c3 / Math.pow(c2, 1.5), kurtosis: c4 / (c2 * c2) - 3 };
}

export const dtriangular = {
  id: 'dtriangular', label: 'Double-triangular', kind: 'continuous', group: 'Bounded',
  blurb: 'Two triangles that meet at the most likely value with half the probability on each side, so that value is the median as well as the peak.',
  params: triFields(),
  defaults: { a: 0, c: 1, b: 3 },
  validate: (p) => { const e = triangleValidate(p); if (e) return e; return p.c > p.a && p.c < p.b ? '' : 'The mode must lie strictly between the minimum and the maximum.'; },
  support: (p) => [p.a, p.b],
  logpdf: (x, p) => {
    if (x < p.a || x > p.b) return -Infinity;
    if (x <= p.c) return Math.log((x - p.a) / sq(p.c - p.a));
    return Math.log((p.b - x) / sq(p.b - p.c));
  },
  cdf: (x, p) => (x <= p.a ? 0 : x >= p.b ? 1 : x <= p.c ? sq(x - p.a) / (2 * sq(p.c - p.a)) : 1 - sq(p.b - x) / (2 * sq(p.b - p.c))),
  sf: (x, p) => (x <= p.a ? 1 : x >= p.b ? 0 : x <= p.c ? 1 - sq(x - p.a) / (2 * sq(p.c - p.a)) : sq(p.b - x) / (2 * sq(p.b - p.c))),
  quantile: (u, p) => (u <= 0.5 ? p.a + (p.c - p.a) * Math.sqrt(2 * u) : p.b - (p.b - p.c) * Math.sqrt(2 * (1 - u))),
  isf: (q, p) => (q <= 0.5 ? p.b - (p.b - p.c) * Math.sqrt(2 * q) : p.a + (p.c - p.a) * Math.sqrt(2 * (1 - q))),
  /* Half a triangle (a, c, c) and half a triangle (c, c, b). */
  mean: (p) => dtriMoments(p).mean,
  variance: (p) => dtriMoments(p).variance,
  skewness: (p) => dtriMoments(p).skewness,
  kurtosis: (p) => dtriMoments(p).kurtosis,
  entropy: (p) => 0.5 + (Math.log(p.c - p.a) + Math.log(p.b - p.c)) / 2,
  mode: (p) => p.c,
  median: (p) => p.c,
  breaks: () => [0.5],
  parameterisations: [
    { id: 'a-c-b', label: 'Minimum, mode and maximum', fields: triFields(),
      to: (v) => ({ a: v.a, c: v.c, b: v.b }), from: (p) => ({ a: p.a, c: p.c, b: p.b }) },
  ],
  free: triFree,
  fit: {
    k: 3, regular: false,
    mle: (s) => { const g = triangleMle(s.x, true); return { a: g.min, c: g.mode, b: g.max }; },
    mom: (s) => {
      const g = triangleMom(s, true);
      return { params: { a: g.min, c: g.mode, b: g.max }, note: g.clamped ? 'the sample is more skewed than this shape can be; this is the most skewed one' : '' };
    },
  },
  tex: {
    pdf: R`f(x)=\begin{cases}\frac{x-a}{(c-a)^2} & a\le x\le c\\[2pt] \frac{b-x}{(b-c)^2} & c<x\le b\end{cases}`,
    cdf: R`F(x)=\begin{cases}\frac{(x-a)^2}{2(c-a)^2} & x\le c\\[2pt] 1-\frac{(b-x)^2}{2(b-c)^2} & x>c\end{cases}`,
    mean: R`\frac{a+4c+b}{6}`, variance: R`\text{by numerical integration}`,
  },
  scipy: 'no equivalent (skbrnt’s dtriang)',
};

export const logdtriangular = logOf(dtriangular, {
  id: 'logdtriangular', label: 'Log-double-triangular', kind: 'continuous', group: 'Log scale',
  blurb: 'Two triangles in the logarithm that meet at the most likely value with half the probability on each side.',
  params: [field('a', 'Minimum a', 'pos'), field('c', 'Mode c (of ln X)', 'pos'), field('b', 'Maximum b', 'pos')],
  defaults: { a: 0.1, c: 1, b: 100 },
  validate: (p) => (p.a > 0 ? dtriangular.validate(p) : 'The minimum must be above zero.'),
  /* The rise peaks at e^(a'+1) or at c; just right of c the fall starts at
     1/((b'-c') c). The larger of the two. */
  mode: (p) => {
    const la = Math.log(p.a); const lc = Math.log(p.c); const lb = Math.log(p.b);
    const x1 = Math.exp(Math.min(la + 1, lc));
    const f1 = (Math.log(x1) - la) / (sq(lc - la) * x1);
    const f2 = 1 / ((lb - lc) * p.c);
    return f2 > f1 ? p.c : x1;
  },
  parameterisations: [
    { id: 'a-c-b', label: 'Minimum, mode (of ln X) and maximum', fields: [field('a', 'Minimum a', 'pos'), field('c', 'Mode c (of ln X)', 'pos'), field('b', 'Maximum b', 'pos')],
      to: (v) => ({ a: v.a, c: v.c, b: v.b }), from: (p) => ({ a: p.a, c: p.c, b: p.b }) },
  ],
  free: logtriangular.free,
  fit: {
    k: 3, regular: false,
    applicable: (s) => (s.positive ? '' : 'needs every value above zero'),
    mle: (s) => {
      const g = triangleMle(Float64Array.from(s.x, Math.log), true);
      let mode = g.at < 0 ? Math.exp(g.min) : g.at >= s.n ? Math.exp(g.max) : s.x[g.at];
      if (g.below && g.at >= 0 && g.at < s.n) mode = mode - Math.abs(mode) * Number.EPSILON;
      return { a: Math.exp(g.min), c: mode, b: Math.exp(g.max) };
    },
    mom: (s) => {
      const g = logTriangleMom(s, true);
      if (!g) return null;
      return { params: { a: g.min, c: g.mode, b: g.max }, note: g.clamped ? 'no shape of this kind has both the sample’s spread and its skewness; this is the nearest' : '' };
    },
  },
  tex: {
    pdf: R`f(x)=\frac{g(\ln x)}{x},\ g=\text{double-triangular on }[\ln a,\ln b]\text{ with mode }\ln c`,
    cdf: R`F(x)=G(\ln x)`,
    mean: R`\text{by numerical integration}`, variance: R`\text{by numerical integration}`,
  },
  scipy: 'no equivalent (skbrnt’s logdt)',
}, (p) => ({ a: Math.log(p.a), c: Math.log(p.c), b: Math.log(p.b) }));

/* ======================================================================
   Beta and PERT (a beta on [lo, hi])
   ====================================================================== */

function betaParts(al, be, lo, hi) {
  const w = hi - lo;
  const lb = lbeta(al, be);
  return {
    logpdf: (x) => {
      if (x < lo || x > hi) return -Infinity;
      const y = (x - lo) / w;
      const yc = (hi - x) / w;
      if (y === 0) return al < 1 ? Infinity : al === 1 ? Math.log(be) - Math.log(w) : -Infinity;
      if (yc === 0) return be < 1 ? Infinity : be === 1 ? Math.log(al) - Math.log(w) : -Infinity;
      const ly = y < 0.5 ? Math.log(y) : Math.log1p(-yc);
      const lyc = yc < 0.5 ? Math.log(yc) : Math.log1p(-y);
      return (al - 1) * ly + (be - 1) * lyc - lb - Math.log(w);
    },
    cdf: (x) => (x <= lo ? 0 : x >= hi ? 1 : betaInc(al, be, (x - lo) / w, (hi - x) / w)[0]),
    sf: (x) => (x <= lo ? 1 : x >= hi ? 0 : betaInc(al, be, (x - lo) / w, (hi - x) / w)[1]),
    quantile: (u) => { const [y, yc] = betaIncInv(al, be, u, 1 - u); return y <= 0.5 ? lo + w * y : hi - w * yc; },
    isf: (q) => { const [y, yc] = betaIncInv(al, be, 1 - q, q); return y <= 0.5 ? lo + w * y : hi - w * yc; },
    mean: () => lo + w * al / (al + be),
    variance: () => w * w * al * be / (sq(al + be) * (al + be + 1)),
    skewness: () => 2 * (be - al) * Math.sqrt(al + be + 1) / ((al + be + 2) * Math.sqrt(al * be)),
    kurtosis: () => 6 * (sq(al - be) * (al + be + 1) - al * be * (al + be + 2)) / (al * be * (al + be + 2) * (al + be + 3)),
    entropy: () => lb - (al - 1) * digamma(al) - (be - 1) * digamma(be) + (al + be - 2) * digamma(al + be) + Math.log(w),
    mode: () => {
      if (al > 1 && be > 1) return lo + w * (al - 1) / (al + be - 2);
      if (al <= 1 && be > 1) return lo;
      if (be <= 1 && al > 1) return hi;
      if (al === 1 && be === 1) return lo + w / 2;
      return al < be ? lo : hi;   // both below 1: the higher end
    },
  };
}

const betaBounds = () => [field('lo', 'Lower end', 'real'), field('hi', 'Upper end', 'real')];

export const beta = {
  id: 'beta', label: 'Beta', kind: 'continuous', group: 'Bounded',
  blurb: 'Any hump or U between two ends, from two shape parameters: proportions, fractions and probabilities, on 0 to 1 unless other ends are given.',
  params: [field('alpha', 'Shape α', 'pos'), field('beta', 'Shape β', 'pos'), field('lo', 'Lower end', 'real'), field('hi', 'Upper end', 'real')],
  defaults: { alpha: 2, beta: 5, lo: 0, hi: 1 },
  validate: (p) => (p.hi > p.lo ? '' : 'The upper end must be above the lower end.'),
  support: (p) => [p.lo, p.hi],
  logpdf: (x, p) => betaParts(p.alpha, p.beta, p.lo, p.hi).logpdf(x),
  cdf: (x, p) => betaParts(p.alpha, p.beta, p.lo, p.hi).cdf(x),
  sf: (x, p) => betaParts(p.alpha, p.beta, p.lo, p.hi).sf(x),
  quantile: (u, p) => betaParts(p.alpha, p.beta, p.lo, p.hi).quantile(u),
  isf: (q, p) => betaParts(p.alpha, p.beta, p.lo, p.hi).isf(q),
  mean: (p) => betaParts(p.alpha, p.beta, p.lo, p.hi).mean(),
  variance: (p) => betaParts(p.alpha, p.beta, p.lo, p.hi).variance(),
  skewness: (p) => betaParts(p.alpha, p.beta, p.lo, p.hi).skewness(),
  kurtosis: (p) => betaParts(p.alpha, p.beta, p.lo, p.hi).kurtosis(),
  entropy: (p) => betaParts(p.alpha, p.beta, p.lo, p.hi).entropy(),
  mode: (p) => betaParts(p.alpha, p.beta, p.lo, p.hi).mode(),
  modeText: (p) => (p.alpha === 1 && p.beta === 1 ? 'any value between the ends' : p.alpha < 1 && p.beta < 1 ? 'both ends' : ''),
  parameterisations: [
    { id: 'shapes', label: 'Shapes α and β', fields: [field('alpha', 'Shape α', 'pos'), field('beta', 'Shape β', 'pos'), ...betaBounds()],
      to: (v) => ({ alpha: v.alpha, beta: v.beta, lo: v.lo, hi: v.hi }), from: (p) => ({ alpha: p.alpha, beta: p.beta, lo: p.lo, hi: p.hi }) },
    { id: 'mean-sd', label: 'Mean and SD', fields: [field('mean', 'Mean', 'real'), field('sd', 'Standard deviation', 'pos'), ...betaBounds()],
      to: (v) => {
        need(v.hi > v.lo, 'The upper end must be above the lower end.');
        const m = (v.mean - v.lo) / (v.hi - v.lo);
        const s = v.sd / (v.hi - v.lo);
        need(m > 0 && m < 1, 'The mean must lie between the ends.');
        const k = m * (1 - m) / (s * s) - 1;
        need(k > 0, `The SD must be below ${(Math.sqrt(m * (1 - m)) * (v.hi - v.lo)).toPrecision(4)} for this mean.`);
        return { alpha: m * k, beta: (1 - m) * k, lo: v.lo, hi: v.hi };
      },
      from: (p) => { const w = p.hi - p.lo; const k = p.alpha + p.beta; return { mean: p.lo + w * p.alpha / k, sd: w * Math.sqrt(p.alpha * p.beta / (k * k * (k + 1))), lo: p.lo, hi: p.hi }; } },
    { id: 'mean-kappa', label: 'Mean and concentration', fields: [field('mean', 'Mean', 'real'), field('kappa', 'Concentration α + β', 'pos'), ...betaBounds()],
      to: (v) => { need(v.hi > v.lo, 'The upper end must be above the lower end.'); const m = (v.mean - v.lo) / (v.hi - v.lo); need(m > 0 && m < 1, 'The mean must lie between the ends.'); return { alpha: m * v.kappa, beta: (1 - m) * v.kappa, lo: v.lo, hi: v.hi }; },
      from: (p) => ({ mean: p.lo + (p.hi - p.lo) * p.alpha / (p.alpha + p.beta), kappa: p.alpha + p.beta, lo: p.lo, hi: p.hi }) },
    { id: 'mode-kappa', label: 'Mode and concentration', fields: [field('mode', 'Mode', 'real'), field('kappa', 'Concentration α + β (> 2)', 'real'), ...betaBounds()],
      covers: (p) => p.alpha > 1 && p.beta > 1, coversText: 'a hump with its mode inside, where α and β are both above 1',
      to: (v) => {
        need(v.hi > v.lo, 'The upper end must be above the lower end.');
        need(v.kappa > 2, 'The concentration must be above 2 for a mode inside.');
        const m = (v.mode - v.lo) / (v.hi - v.lo);
        need(m >= 0 && m <= 1, 'The mode must lie between the ends.');
        return { alpha: 1 + m * (v.kappa - 2), beta: 1 + (1 - m) * (v.kappa - 2), lo: v.lo, hi: v.hi };
      },
      from: (p) => { const k = p.alpha + p.beta; return { mode: p.lo + (p.hi - p.lo) * (p.alpha - 1) / (k - 2), kappa: k, lo: p.lo, hi: p.hi }; } },
  ],
  free: { keys: ['alpha', 'beta'], to: (p) => [Math.log(p.alpha), Math.log(p.beta)], from: (z, p0) => ({ alpha: Math.exp(z[0]), beta: Math.exp(z[1]), lo: p0 ? p0.lo : 0, hi: p0 ? p0.hi : 1 }) },
  fit: {
    k: 2,
    applicable: (s) => (s.inUnit ? '' : 'needs every value between 0 and 1 (the ends are fixed at 0 and 1)'),
    mle: (s) => {
      let lx = 0;
      let l1x = 0;
      for (let i = 0; i < s.n; i++) { lx += Math.log(s.x[i]); l1x += Math.log1p(-s.x[i]); }
      lx /= s.n;
      l1x /= s.n;
      const m = s.mean;
      const k0 = Math.max(m * (1 - m) / s.var - 1, 0.1);
      /* the two score equations, in the logarithms of the shapes */
      const F = ([la, lb]) => {
        const a = Math.exp(la); const b = Math.exp(lb); const d = digamma(a + b);
        return [digamma(a) - d - lx, digamma(b) - d - l1x];
      };
      const got = newtonSystem(F, [Math.log(m * k0), Math.log((1 - m) * k0)], { tol: 1e-14 });
      if (!(got.norm < 1e-8)) {
        const nll = ([la, lb]) => { const a = Math.exp(la); const b = Math.exp(lb); return -(s.n * ((a - 1) * lx + (b - 1) * l1x - lbeta(a, b))); };
        const nm = nelderMead(nll, [Math.log(m * k0), Math.log((1 - m) * k0)]);
        return { alpha: Math.exp(nm.x[0]), beta: Math.exp(nm.x[1]), lo: 0, hi: 1 };
      }
      return { alpha: Math.exp(got.x[0]), beta: Math.exp(got.x[1]), lo: 0, hi: 1 };
    },
    mom: (s) => { const k = s.mean * (1 - s.mean) / s.var - 1; return k > 0 ? { alpha: s.mean * k, beta: (1 - s.mean) * k, lo: 0, hi: 1 } : null; },
  },
  tex: {
    pdf: R`f(x)=\frac{y^{\alpha-1}(1-y)^{\beta-1}}{(h-l)\,B(\alpha,\beta)},\ y=\frac{x-l}{h-l}`,
    cdf: R`F(x)=I_y(\alpha,\beta)`,
    mean: R`l+(h-l)\frac{\alpha}{\alpha+\beta}`, variance: R`(h-l)^2\frac{\alpha\beta}{(\alpha+\beta)^2(\alpha+\beta+1)}`,
  },
  scipy: 'beta(α, β, loc=l, scale=h−l)',
};

const pertShapes = (p) => ({ al: 1 + p.lambda * (p.c - p.a) / (p.b - p.a), be: 1 + p.lambda * (p.b - p.c) / (p.b - p.a) });
const pertParts = (p) => { const { al, be } = pertShapes(p); return betaParts(al, be, p.a, p.b); };

/* The PERT whose mean, SD and skewness are the sample's. Its shapes add up
   to lambda + 2 whatever the mode, so the skewness is a function of the
   mode's place r = (c - a)/(b - a) alone: r from the skewness, the width
   from the SD, the position from the mean, as for the triangle. */
function pertMom(s, lambda) {
  const at = (r) => {
    const al = 1 + lambda * r;
    const be = 1 + lambda * (1 - r);
    const k = al + be;
    return { mean: al / k, sd: Math.sqrt(al * be / (k * k * (k + 1))), skew: 2 * (be - al) * Math.sqrt(k + 1) / ((k + 2) * Math.sqrt(al * be)) };
  };
  const { r, clamped } = solveShape((q) => at(q).skew, s.skew, 0, 1);
  const m = at(r);
  const w = s.sd / m.sd;
  const a = s.mean - w * m.mean;
  return { params: { a, c: a + r * w, b: a + w, lambda }, note: clamped ? 'the sample is more skewed than a PERT can be; this is the most skewed one' : '' };
}

export const pert = {
  id: 'pert', label: 'PERT', kind: 'continuous', group: 'Bounded',
  blurb: 'A smooth beta-shaped hump between a minimum and a maximum, peaking at the most likely value: the triangle with its corners rounded, from project risk analysis.',
  params: [field('a', 'Minimum a', 'real'), field('c', 'Mode c', 'real'), field('b', 'Maximum b', 'real'), field('lambda', 'Shape λ', 'pos')],
  defaults: { a: 0, c: 1, b: 3, lambda: 4 },
  validate: (p) => triangleValidate(p) || (p.lambda > 0 ? '' : 'λ must be above 0.'),
  support: (p) => [p.a, p.b],
  logpdf: (x, p) => pertParts(p).logpdf(x),
  cdf: (x, p) => pertParts(p).cdf(x),
  sf: (x, p) => pertParts(p).sf(x),
  quantile: (u, p) => pertParts(p).quantile(u),
  isf: (q, p) => pertParts(p).isf(q),
  mean: (p) => (p.a + p.lambda * p.c + p.b) / (p.lambda + 2),
  variance: (p) => pertParts(p).variance(),
  skewness: (p) => pertParts(p).skewness(),
  kurtosis: (p) => pertParts(p).kurtosis(),
  entropy: (p) => pertParts(p).entropy(),
  mode: (p) => p.c,
  parameterisations: [
    { id: 'a-c-b', label: 'Minimum, mode, maximum (and λ)', fields: [...triFields(), field('lambda', 'Shape λ (4 is the classic PERT)', 'pos')],
      to: (v) => ({ a: v.a, c: v.c, b: v.b, lambda: v.lambda }), from: (p) => ({ a: p.a, c: p.c, b: p.b, lambda: p.lambda }) },
  ],
  free: { keys: ['a', 'c', 'b'], to: triFree.to, from: (z, p0) => ({ ...triFree.from(z), lambda: p0 ? p0.lambda : 4 }) },
  fit: {
    k: 3, regular: false,
    note: 'λ = 4',
    mle: (s) => {
      const span = s.max - s.min;
      const nll = (z) => {
        const p = { ...triFree.from(z), lambda: 4 };
        if (!(p.a < s.min && p.b > s.max)) return Infinity;
        const { al, be } = pertShapes(p);
        const w = p.b - p.a;
        let ll = 0;
        for (let i = 0; i < s.n; i++) ll += (al - 1) * Math.log(s.x[i] - p.a) + (be - 1) * Math.log(p.b - s.x[i]);
        return -(ll - s.n * (lbeta(al, be) + (al + be - 1) * Math.log(w)));
      };
      const c0 = Math.min(s.max, Math.max(s.min, (6 * s.mean - s.min - s.max) / 4));
      let best = null;
      for (const pad of [0.05, 0.3]) {
        const a = s.min - pad * span;
        const b = s.max + pad * span;
        const got = nelderMead(nll, triFree.to({ a, c: c0, b }));
        if (!best || got.f < best.f) best = got;
      }
      return Number.isFinite(best.f) ? { ...triFree.from(best.x), lambda: 4 } : null;
    },
    mom: (s) => pertMom(s, 4),
  },
  tex: {
    pdf: R`X=a+(b-a)\,Y,\ Y\sim\mathrm{Beta}\!\left(1+\lambda\tfrac{c-a}{b-a},\ 1+\lambda\tfrac{b-c}{b-a}\right)`,
    cdf: R`F(x)=I_{(x-a)/(b-a)}(\alpha,\beta)`,
    mean: R`\frac{a+\lambda c+b}{\lambda+2}`, variance: R`\frac{(\mu-a)(b-\mu)}{\lambda+3}`,
  },
  scipy: 'beta(1+λ(c−a)/(b−a), 1+λ(b−c)/(b−a), loc=a, scale=b−a)',
};

/* ======================================================================
   Gamma, exponential, chi-square
   ====================================================================== */

function gammaLogpdf(x, k, theta) {
  if (x < 0) return -Infinity;
  if (x === 0) return k < 1 ? Infinity : k === 1 ? -Math.log(theta) : -Infinity;
  return Math.log(k / x) + logDpoisRaw(k, x / theta);
}

/* Shape k of the gamma whose ln(mean) - mean(ln x) is s (Minka's start, then Newton). */
function gammaShapeFor(s) {
  if (!(s > 0)) return NaN;
  let k = (3 - s + Math.sqrt(sq(s - 3) + 24 * s)) / (12 * s);
  for (let i = 0; i < 100; i++) {
    const g = Math.log(k) - digamma(k) - s;
    const dg = 1 / k - trigamma(k);
    const kn = k - g / dg;
    if (!(kn > 0)) { k /= 2; continue; }
    if (Math.abs(kn - k) <= 1e-15 * k) { k = kn; break; }
    k = kn;
  }
  return k;
}

export const gamma = {
  id: 'gamma', label: 'Gamma', kind: 'continuous', group: 'Positive',
  blurb: 'Waiting times and amounts that add up: the sum of k exponential waits, and a flexible right-skewed shape for anything positive.',
  params: [field('k', 'Shape k', 'pos'), field('theta', 'Scale θ', 'pos')],
  defaults: { k: 2, theta: 1 },
  support: () => [0, Infinity],
  logpdf: (x, p) => gammaLogpdf(x, p.k, p.theta),
  cdf: (x, p) => (x <= 0 ? 0 : gammaInc(p.k, x / p.theta)[0]),
  sf: (x, p) => (x <= 0 ? 1 : gammaInc(p.k, x / p.theta)[1]),
  quantile: (u, p) => p.theta * gammaIncInv(p.k, u, 1 - u),
  isf: (q, p) => p.theta * gammaIncInv(p.k, 1 - q, q),
  mean: (p) => p.k * p.theta,
  variance: (p) => p.k * p.theta * p.theta,
  skewness: (p) => 2 / Math.sqrt(p.k),
  kurtosis: (p) => 6 / p.k,
  entropy: (p) => p.k + Math.log(p.theta) + lgamma(p.k) + (1 - p.k) * digamma(p.k),
  mode: (p) => (p.k >= 1 ? (p.k - 1) * p.theta : 0),
  logMoments: (p) => [digamma(p.k) + Math.log(p.theta), trigamma(p.k)],
  parameterisations: [
    { id: 'shape-scale', label: 'Shape k and scale θ', fields: [field('k', 'Shape k', 'pos'), field('theta', 'Scale θ', 'pos')],
      to: (v) => ({ k: v.k, theta: v.theta }), from: (p) => ({ k: p.k, theta: p.theta }) },
    { id: 'shape-rate', label: 'Shape k and rate β', fields: [field('k', 'Shape k', 'pos'), field('rate', 'Rate β = 1/θ', 'pos')],
      to: (v) => ({ k: v.k, theta: 1 / v.rate }), from: (p) => ({ k: p.k, rate: 1 / p.theta }) },
    { id: 'mean-sd', label: 'Mean and SD', fields: [field('mean', 'Mean', 'pos'), field('sd', 'Standard deviation', 'pos')],
      to: (v) => ({ k: sq(v.mean / v.sd), theta: v.sd * v.sd / v.mean }), from: (p) => ({ mean: p.k * p.theta, sd: Math.sqrt(p.k) * p.theta }) },
    { id: 'mean-cv', label: 'Mean and CV', fields: [field('mean', 'Mean', 'pos'), field('cv', 'Coefficient of variation', 'pos')],
      to: (v) => ({ k: 1 / (v.cv * v.cv), theta: v.mean * v.cv * v.cv }), from: (p) => ({ mean: p.k * p.theta, cv: 1 / Math.sqrt(p.k) }) },
    { id: 'mean-shape', label: 'Mean and shape k', fields: [field('mean', 'Mean', 'pos'), field('k', 'Shape k', 'pos')],
      to: (v) => ({ k: v.k, theta: v.mean / v.k }), from: (p) => ({ mean: p.k * p.theta, k: p.k }) },
  ],
  free: { keys: ['k', 'theta'], to: (p) => [Math.log(p.k), Math.log(p.theta)], from: (z) => ({ k: Math.exp(z[0]), theta: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    applicable: (s) => (s.positive ? '' : 'needs every value above zero'),
    mle: (s) => { const k = gammaShapeFor(Math.log(s.mean) - s.meanLog); return k > 0 ? { k, theta: s.mean / k } : null; },
    mom: (s) => ({ k: s.mean * s.mean / s.var, theta: s.var / s.mean }),
  },
  tex: {
    pdf: R`f(x)=\frac{x^{k-1}e^{-x/\theta}}{\Gamma(k)\,\theta^k},\ x>0`, cdf: R`F(x)=P(k,\,x/\theta)\ \text{(regularized incomplete gamma)}`,
    mean: R`k\theta`, variance: R`k\theta^2`,
  },
  scipy: 'gamma(a=k, scale=θ)',
};

export const exponential = {
  id: 'exponential', label: 'Exponential', kind: 'continuous', group: 'Positive',
  blurb: 'The waiting time to an event that happens at a constant rate, such as a radioactive decay: memoryless.',
  params: [field('lambda', 'Rate λ', 'pos')],
  defaults: { lambda: 1 },
  support: () => [0, Infinity],
  logpdf: (x, p) => (x >= 0 ? Math.log(p.lambda) - p.lambda * x : -Infinity),
  cdf: (x, p) => (x <= 0 ? 0 : -Math.expm1(-p.lambda * x)),
  sf: (x, p) => (x <= 0 ? 1 : Math.exp(-p.lambda * x)),
  logsf: (x, p) => (x <= 0 ? 0 : -p.lambda * x),
  quantile: (u, p) => -Math.log1p(-u) / p.lambda,
  isf: (q, p) => -Math.log(q) / p.lambda,
  mean: (p) => 1 / p.lambda,
  variance: (p) => 1 / (p.lambda * p.lambda),
  skewness: () => 2,
  kurtosis: () => 6,
  entropy: (p) => 1 - Math.log(p.lambda),
  mode: () => 0,
  median: (p) => LN2 / p.lambda,
  logMoments: (p) => [-EULER - Math.log(p.lambda), Math.PI * Math.PI / 6],
  parameterisations: [
    { id: 'rate', label: 'Rate λ', fields: [field('lambda', 'Rate λ', 'pos')], to: (v) => ({ lambda: v.lambda }), from: (p) => ({ lambda: p.lambda }) },
    { id: 'mean', label: 'Mean (scale)', fields: [field('mean', 'Mean 1/λ', 'pos')], to: (v) => ({ lambda: 1 / v.mean }), from: (p) => ({ mean: 1 / p.lambda }) },
    { id: 'half-life', label: 'Half-life (median)', fields: [field('half', 'Half-life ln 2/λ', 'pos')], to: (v) => ({ lambda: LN2 / v.half }), from: (p) => ({ half: LN2 / p.lambda }) },
  ],
  free: { keys: ['lambda'], to: (p) => [Math.log(p.lambda)], from: (z) => ({ lambda: Math.exp(z[0]) }) },
  fit: {
    k: 1,
    applicable: (s) => (s.nonneg && s.mean > 0 ? '' : 'needs values of zero or above'),
    mle: (s) => ({ lambda: 1 / s.mean }),
    mom: (s) => ({ lambda: 1 / s.mean }),
  },
  tex: { pdf: R`f(x)=\lambda e^{-\lambda x},\ x\ge0`, cdf: R`F(x)=1-e^{-\lambda x}`, mean: R`1/\lambda`, variance: R`1/\lambda^2` },
  scipy: 'expon(scale=1/λ)',
};

export const chisquare = {
  id: 'chisquare', label: 'Chi-square', kind: 'continuous', group: 'Positive',
  blurb: 'The sum of k squared standard normals: the distribution of a sample variance and of many test statistics.',
  params: [field('k', 'Degrees of freedom k', 'pos')],
  defaults: { k: 3 },
  support: () => [0, Infinity],
  logpdf: (x, p) => gammaLogpdf(x, p.k / 2, 2),
  cdf: (x, p) => (x <= 0 ? 0 : gammaInc(p.k / 2, x / 2)[0]),
  sf: (x, p) => (x <= 0 ? 1 : gammaInc(p.k / 2, x / 2)[1]),
  quantile: (u, p) => 2 * gammaIncInv(p.k / 2, u, 1 - u),
  isf: (q, p) => 2 * gammaIncInv(p.k / 2, 1 - q, q),
  mean: (p) => p.k,
  variance: (p) => 2 * p.k,
  skewness: (p) => Math.sqrt(8 / p.k),
  kurtosis: (p) => 12 / p.k,
  entropy: (p) => p.k / 2 + LN2 + lgamma(p.k / 2) + (1 - p.k / 2) * digamma(p.k / 2),
  mode: (p) => Math.max(p.k - 2, 0),
  logMoments: (p) => [digamma(p.k / 2) + LN2, trigamma(p.k / 2)],
  parameterisations: [
    { id: 'df', label: 'Degrees of freedom', fields: [field('k', 'Degrees of freedom k', 'pos')], to: (v) => ({ k: v.k }), from: (p) => ({ k: p.k }) },
  ],
  free: { keys: ['k'], to: (p) => [Math.log(p.k)], from: (z) => ({ k: Math.exp(z[0]) }) },
  fit: {
    k: 1,
    applicable: (s) => (s.positive ? '' : 'needs every value above zero'),
    mle: (s) => {
      const target = s.meanLog - LN2;
      const f = (lk) => digamma(Math.exp(lk) / 2) - target;
      const lk = brentRoot(f, Math.log(1e-6), Math.log(1e8));
      return Number.isFinite(lk) ? { k: Math.exp(lk) } : null;
    },
    mom: (s) => ({ k: s.mean }),
  },
  tex: { pdf: R`f(x)=\frac{x^{k/2-1}e^{-x/2}}{2^{k/2}\Gamma(k/2)}`, cdf: R`F(x)=P(k/2,\,x/2)`, mean: R`k`, variance: R`2k` },
  scipy: 'chi2(df=k)',
};

/* ======================================================================
   Weibull
   ====================================================================== */

export const weibull = {
  id: 'weibull', label: 'Weibull', kind: 'continuous', group: 'Positive',
  blurb: 'Times to failure whose rate rises (k > 1) or falls (k < 1) with age; with k = 1 it is the exponential.',
  params: [field('k', 'Shape k', 'pos'), field('lambda', 'Scale λ', 'pos')],
  defaults: { k: 1.5, lambda: 1 },
  support: () => [0, Infinity],
  logpdf: (x, p) => {
    if (x < 0) return -Infinity;
    if (x === 0) return p.k < 1 ? Infinity : p.k === 1 ? -Math.log(p.lambda) : -Infinity;
    const lz = Math.log(x / p.lambda);
    return Math.log(p.k / p.lambda) + (p.k - 1) * lz - Math.exp(p.k * lz);
  },
  cdf: (x, p) => (x <= 0 ? 0 : -Math.expm1(-Math.pow(x / p.lambda, p.k))),
  sf: (x, p) => (x <= 0 ? 1 : Math.exp(-Math.pow(x / p.lambda, p.k))),
  logsf: (x, p) => (x <= 0 ? 0 : -Math.pow(x / p.lambda, p.k)),
  quantile: (u, p) => p.lambda * Math.pow(-Math.log1p(-u), 1 / p.k),
  isf: (q, p) => p.lambda * Math.pow(-Math.log(q), 1 / p.k),
  mean: (p) => p.lambda * gammaFn(1 + 1 / p.k),
  variance: (p) => sq(p.lambda * gammaFn(1 + 1 / p.k)) * Math.expm1(lgamma(1 + 2 / p.k) - 2 * lgamma(1 + 1 / p.k)),
  skewness: (p) => {
    if (p.k > 30) return undefined;
    const g1 = gammaFn(1 + 1 / p.k); const g2 = gammaFn(1 + 2 / p.k); const g3 = gammaFn(1 + 3 / p.k);
    return (g3 - 3 * g1 * g2 + 2 * g1 * g1 * g1) / Math.pow(g2 - g1 * g1, 1.5);
  },
  kurtosis: (p) => {
    if (p.k > 30) return undefined;
    const g1 = gammaFn(1 + 1 / p.k); const g2 = gammaFn(1 + 2 / p.k); const g3 = gammaFn(1 + 3 / p.k); const g4 = gammaFn(1 + 4 / p.k);
    return (g4 - 4 * g1 * g3 + 6 * g1 * g1 * g2 - 3 * g1 ** 4) / sq(g2 - g1 * g1) - 3;
  },
  entropy: (p) => EULER * (1 - 1 / p.k) + Math.log(p.lambda / p.k) + 1,
  mode: (p) => (p.k > 1 ? p.lambda * Math.pow((p.k - 1) / p.k, 1 / p.k) : 0),
  median: (p) => p.lambda * Math.pow(LN2, 1 / p.k),
  logMoments: (p) => [Math.log(p.lambda) - EULER / p.k, Math.PI * Math.PI / (6 * p.k * p.k)],
  parameterisations: [
    { id: 'shape-scale', label: 'Shape k and scale λ', fields: [field('k', 'Shape k', 'pos'), field('lambda', 'Scale λ', 'pos')],
      to: (v) => ({ k: v.k, lambda: v.lambda }), from: (p) => ({ k: p.k, lambda: p.lambda }) },
    { id: 'shape-mean', label: 'Shape k and mean', fields: [field('k', 'Shape k', 'pos'), field('mean', 'Mean', 'pos')],
      to: (v) => ({ k: v.k, lambda: v.mean / gammaFn(1 + 1 / v.k) }), from: (p) => ({ k: p.k, mean: p.lambda * gammaFn(1 + 1 / p.k) }) },
  ],
  free: { keys: ['k', 'lambda'], to: (p) => [Math.log(p.k), Math.log(p.lambda)], from: (z) => ({ k: Math.exp(z[0]), lambda: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    applicable: (s) => (s.positive ? '' : 'needs every value above zero'),
    mle: (s) => {
      /* the profile equation in k, on values scaled by the largest so that
         x^k cannot overflow */
      const y = Float64Array.from(s.x, (v) => v / s.max);
      const ly = Float64Array.from(y, Math.log);
      let mly = 0;
      for (let i = 0; i < s.n; i++) mly += ly[i];
      mly /= s.n;
      const g = (lk) => {
        const k = Math.exp(lk);
        let a = 0; let b = 0;
        for (let i = 0; i < s.n; i++) { const t = Math.exp(k * ly[i]); a += t * ly[i]; b += t; }
        return a / b - 1 / k - mly;
      };
      const lk = brentRoot(g, Math.log(1e-3), Math.log(1e4));
      if (!Number.isFinite(lk)) return null;
      const k = Math.exp(lk);
      let b = 0;
      for (let i = 0; i < s.n; i++) b += Math.exp(k * ly[i]);
      return { k, lambda: s.max * Math.pow(b / s.n, 1 / k) };
    },
    mom: (s) => {
      const cv2 = s.var / (s.mean * s.mean);
      const f = (lk) => { const k = Math.exp(lk); return Math.expm1(lgamma(1 + 2 / k) - 2 * lgamma(1 + 1 / k)) - cv2; };
      const lk = brentRoot(f, Math.log(0.02), Math.log(1e4));
      if (!Number.isFinite(lk)) return null;
      const k = Math.exp(lk);
      return { k, lambda: s.mean / gammaFn(1 + 1 / k) };
    },
  },
  tex: {
    pdf: R`f(x)=\frac{k}{\lambda}\left(\frac{x}{\lambda}\right)^{k-1}e^{-(x/\lambda)^k},\ x\ge0`, cdf: R`F(x)=1-e^{-(x/\lambda)^k}`,
    mean: R`\lambda\,\Gamma(1+1/k)`, variance: R`\lambda^2\left[\Gamma(1+2/k)-\Gamma(1+1/k)^2\right]`,
  },
  scipy: 'weibull_min(c=k, scale=λ)',
};

/* ======================================================================
   Location-scale families: logistic, Laplace, Cauchy, Gumbel (max, min)
   ====================================================================== */

export const logisticFam = locationScale({
  id: 'logistic', label: 'Logistic', kind: 'continuous', group: 'General',
  blurb: 'Like the normal but with heavier tails; its CDF is the logistic growth curve.',
  params: [field('mu', 'Location μ', 'real'), field('s', 'Scale s', 'pos')],
  defaults: { mu: 0, s: 1 },
  parameterisations: [
    { id: 'loc-scale', label: 'Location μ and scale s', fields: [field('mu', 'Location μ', 'real'), field('s', 'Scale s', 'pos')],
      to: (v) => ({ mu: v.mu, s: v.s }), from: (p) => ({ mu: p.mu, s: p.s }) },
    { id: 'mean-sd', label: 'Mean and SD', fields: [field('mean', 'Mean', 'real'), field('sd', 'Standard deviation', 'pos')],
      to: (v) => ({ mu: v.mean, s: v.sd * Math.sqrt(3) / Math.PI }), from: (p) => ({ mean: p.mu, sd: p.s * Math.PI / Math.sqrt(3) }) },
  ],
  free: { keys: ['mu', 's'], to: (p) => [p.mu, Math.log(p.s)], from: (z) => ({ mu: z[0], s: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    mle: (s) => {
      const nll = ([m, ls]) => {
        const sc = Math.exp(ls);
        let ll = 0;
        for (let i = 0; i < s.n; i++) { const z = Math.abs(s.x[i] - m) / sc; ll += -z - 2 * Math.log1p(Math.exp(-z)); }
        return -(ll - s.n * ls);
      };
      const med = s.x[Math.floor(s.n / 2)];
      const got = nelderMead(nll, [med, Math.log(s.sd * Math.sqrt(3) / Math.PI || 1)]);
      return { mu: got.x[0], s: Math.exp(got.x[1]) };
    },
    mom: (s) => ({ mu: s.mean, s: s.sd * Math.sqrt(3) / Math.PI }),
  },
  tex: {
    pdf: R`f(x)=\frac{e^{-z}}{s\,(1+e^{-z})^2},\ z=\frac{x-\mu}{s}`, cdf: R`F(x)=\frac{1}{1+e^{-z}}`,
    mean: R`\mu`, variance: R`\frac{s^2\pi^2}{3}`,
  },
  scipy: 'logistic(loc=μ, scale=s)',
}, {
  logpdf: (z) => { const a = Math.abs(z); return -a - 2 * Math.log1p(Math.exp(-a)); },
  cdf: (z) => logistic(z),
  sf: (z) => logistic(-z),
  logcdf: (z) => -log1pexp(-z),
  logsf: (z) => -log1pexp(z),
  quantile: (u) => Math.log(u) - Math.log1p(-u),
  isf: (q) => Math.log1p(-q) - Math.log(q),
  mean: () => 0, variance: () => Math.PI * Math.PI / 3, skewness: () => 0, kurtosis: () => 1.2,
  entropy: () => 2, mode: () => 0, median: () => 0,
}, { loc: 'mu', scale: 's' });

/* tan(b)/b - 1, by its series for small b where the difference would cancel. */
function tanOverMinusOne(b) {
  if (b < 0.05) { const b2 = b * b; return b2 * (1 / 3 + b2 * (2 / 15 + b2 * (17 / 315 + b2 * 62 / 2835))); }
  return Math.tan(b) / b - 1;
}

export const loglogistic = logOf(logisticFam, {
  id: 'loglogistic', label: 'Log-logistic', kind: 'continuous', group: 'Positive',
  blurb: 'A logistic in the logarithm (Fisk): like the lognormal, with a heavier, power-law upper tail.',
  params: [field('alpha', 'Scale α (the median)', 'pos'), field('beta', 'Shape β', 'pos')],
  defaults: { alpha: 1, beta: 4 },
  mean: (p) => { if (p.beta <= 1) return Infinity; const b = Math.PI / p.beta; return p.alpha * b / Math.sin(b); },
  /* the mean squared times CV² = tan(b)/b - 1, b = π/β: no cancellation */
  variance: (p) => {
    if (p.beta <= 2) return p.beta > 1 ? Infinity : NaN;
    const b = Math.PI / p.beta;
    const m = p.alpha * b / Math.sin(b);
    return m * m * tanOverMinusOne(b);
  },
  skewness: (p) => (p.beta <= 3 ? (p.beta > 2 ? Infinity : NaN) : undefined),
  kurtosis: (p) => (p.beta <= 4 ? (p.beta > 2 ? Infinity : NaN) : undefined),
  mode: (p) => (p.beta > 1 ? p.alpha * Math.pow((p.beta - 1) / (p.beta + 1), 1 / p.beta) : 0),
  tails: (p) => ({ left: Infinity, right: p.beta }),
  parameterisations: [
    { id: 'scale-shape', label: 'Scale α and shape β', fields: [field('alpha', 'Scale α (the median)', 'pos'), field('beta', 'Shape β', 'pos')],
      to: (v) => ({ alpha: v.alpha, beta: v.beta }), from: (p) => ({ alpha: p.alpha, beta: p.beta }) },
  ],
  free: { keys: ['alpha', 'beta'], to: (p) => [Math.log(p.alpha), Math.log(p.beta)], from: (z) => ({ alpha: Math.exp(z[0]), beta: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    applicable: (s) => (s.positive ? '' : 'needs every value above zero'),
    /* CV² + 1 = tan(b)/b with b = π/β < π/2, then the scale from the mean */
    mom: (s) => {
      const cv2 = s.var / (s.mean * s.mean);
      const b = brentRoot((t) => tanOverMinusOne(t) - cv2, 1e-9, Math.PI / 2 - 1e-12);
      if (!Number.isFinite(b)) return null;
      return { alpha: s.mean * Math.sin(b) / b, beta: Math.PI / b };
    },
  },
  tex: {
    pdf: R`f(x)=\frac{(\beta/\alpha)(x/\alpha)^{\beta-1}}{\left(1+(x/\alpha)^\beta\right)^2},\ x>0`, cdf: R`F(x)=\frac{1}{1+(x/\alpha)^{-\beta}}`,
    mean: R`\frac{\alpha\pi/\beta}{\sin(\pi/\beta)},\ \beta>1`, variance: R`\alpha^2\left(\frac{2b}{\sin 2b}-\frac{b^2}{\sin^2 b}\right),\ b=\pi/\beta,\ \beta>2`,
  },
  scipy: 'fisk(c=β, scale=α)',
}, (p) => ({ mu: Math.log(p.alpha), s: 1 / p.beta }), (q) => ({ alpha: Math.exp(q.mu), beta: 1 / q.s }));

export const laplace = locationScale({
  id: 'laplace', label: 'Laplace', kind: 'continuous', group: 'General',
  blurb: 'The double exponential: a sharp peak and exponential tails on both sides; differences of exponential waits.',
  params: [field('mu', 'Location μ', 'real'), field('b', 'Scale b', 'pos')],
  defaults: { mu: 0, b: 1 },
  parameterisations: [
    { id: 'loc-scale', label: 'Location μ and scale b', fields: [field('mu', 'Location μ', 'real'), field('b', 'Scale b', 'pos')],
      to: (v) => ({ mu: v.mu, b: v.b }), from: (p) => ({ mu: p.mu, b: p.b }) },
    { id: 'mean-sd', label: 'Mean and SD', fields: [field('mean', 'Mean', 'real'), field('sd', 'Standard deviation', 'pos')],
      to: (v) => ({ mu: v.mean, b: v.sd / SQRT2 }), from: (p) => ({ mean: p.mu, sd: p.b * SQRT2 }) },
  ],
  free: { keys: ['mu', 'b'], to: (p) => [p.mu, Math.log(p.b)], from: (z) => ({ mu: z[0], b: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    mle: (s) => {
      const m = s.n % 2 ? s.x[(s.n - 1) / 2] : 0.5 * (s.x[s.n / 2 - 1] + s.x[s.n / 2]);
      let b = 0;
      for (let i = 0; i < s.n; i++) b += Math.abs(s.x[i] - m);
      return b > 0 ? { mu: m, b: b / s.n } : null;
    },
    mom: (s) => ({ mu: s.mean, b: s.sd / SQRT2 }),
  },
  tex: { pdf: R`f(x)=\frac{1}{2b}e^{-|x-\mu|/b}`, cdf: R`F(x)=\begin{cases}\tfrac12e^{(x-\mu)/b} & x<\mu\\ 1-\tfrac12e^{-(x-\mu)/b} & x\ge\mu\end{cases}`, mean: R`\mu`, variance: R`2b^2` },
  scipy: 'laplace(loc=μ, scale=b)',
}, {
  logpdf: (z) => -LN2 - Math.abs(z),
  cdf: (z) => (z < 0 ? 0.5 * Math.exp(z) : 1 - 0.5 * Math.exp(-z)),
  sf: (z) => (z > 0 ? 0.5 * Math.exp(-z) : 1 - 0.5 * Math.exp(z)),
  logcdf: (z) => (z < 0 ? z - LN2 : Math.log1p(-0.5 * Math.exp(-z))),
  logsf: (z) => (z > 0 ? -z - LN2 : Math.log1p(-0.5 * Math.exp(z))),
  quantile: (u) => (u < 0.5 ? Math.log(2 * u) : -Math.log(2 * (1 - u))),
  isf: (q) => (q < 0.5 ? -Math.log(2 * q) : Math.log(2 * (1 - q))),
  mean: () => 0, variance: () => 2, skewness: () => 0, kurtosis: () => 3,
  entropy: () => 1 + LN2, mode: () => 0, median: () => 0,
}, { loc: 'mu', scale: 'b' });

export const cauchy = locationScale({
  id: 'cauchy', label: 'Cauchy', kind: 'continuous', group: 'General',
  blurb: 'A bell with tails so heavy that it has no mean or variance: the ratio of two normals.',
  params: [field('x0', 'Location x₀ (median)', 'real'), field('gamma', 'Scale γ (half the IQR)', 'pos')],
  defaults: { x0: 0, gamma: 1 },
  parameterisations: [
    { id: 'loc-scale', label: 'Location x₀ and scale γ', fields: [field('x0', 'Location x₀ (median)', 'real'), field('gamma', 'Scale γ', 'pos')],
      to: (v) => ({ x0: v.x0, gamma: v.gamma }), from: (p) => ({ x0: p.x0, gamma: p.gamma }) },
    { id: 'median-q3', label: 'Median and upper quartile', fields: [field('x0', 'Median', 'real'), field('q3', 'Upper quartile (P75)', 'real')],
      to: (v) => { need(v.q3 > v.x0, 'The upper quartile must be above the median.'); return { x0: v.x0, gamma: v.q3 - v.x0 }; }, from: (p) => ({ x0: p.x0, q3: p.x0 + p.gamma }) },
  ],
  free: { keys: ['x0', 'gamma'], to: (p) => [p.x0, Math.log(p.gamma)], from: (z) => ({ x0: z[0], gamma: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    mle: (s) => {
      const q = (p) => { const h = (s.n - 1) * p; const lo = Math.floor(h); return s.x[lo] + (h - lo) * (s.x[Math.min(lo + 1, s.n - 1)] - s.x[lo]); };
      const nll = ([m, lg]) => { const g = Math.exp(lg); let ll = 0; for (let i = 0; i < s.n; i++) ll += Math.log1p(sq((s.x[i] - m) / g)); return ll + s.n * lg; };
      const iqr = q(0.75) - q(0.25);
      const got = nelderMead(nll, [q(0.5), Math.log(iqr > 0 ? iqr / 2 : s.sd || 1)]);
      return { x0: got.x[0], gamma: Math.exp(got.x[1]) };
    },
    mom: () => ({ params: null, why: 'has no mean or variance to match' }),
  },
  tex: { pdf: R`f(x)=\frac{1}{\pi\gamma\left[1+\left(\frac{x-x_0}{\gamma}\right)^2\right]}`, cdf: R`F(x)=\tfrac12+\tfrac1\pi\arctan\frac{x-x_0}{\gamma}`, mean: R`\text{undefined}`, variance: R`\text{undefined}` },
  scipy: 'cauchy(loc=x₀, scale=γ)',
}, {
  logpdf: (z) => -Math.log(Math.PI) - Math.log1p(z * z),
  cdf: (z) => (z < 0 ? Math.atan2(1, -z) / Math.PI : 1 - Math.atan2(1, z) / Math.PI),
  sf: (z) => (z > 0 ? Math.atan2(1, z) / Math.PI : 1 - Math.atan2(1, -z) / Math.PI),
  quantile: (u) => (u === 0.5 ? 0 : u < 0.5 ? -1 / Math.tan(Math.PI * u) : 1 / Math.tan(Math.PI * (1 - u))),
  isf: (q) => (q === 0.5 ? 0 : q < 0.5 ? 1 / Math.tan(Math.PI * q) : -1 / Math.tan(Math.PI * (1 - q))),
  mean: () => NaN, variance: () => NaN, skewness: () => NaN, kurtosis: () => NaN,
  entropy: () => Math.log(4 * Math.PI), mode: () => 0, median: () => 0,
  tails: () => ({ left: 1, right: 1 }),
}, { loc: 'x0', scale: 'gamma' });

/* Gumbel for maxima, by profile likelihood: beta solves
   beta = mean(x) - sum x w / sum w with w = e^(-x/beta). */
function gumbelMle(x, n) {
  let mean = 0;
  for (let i = 0; i < n; i++) mean += x[i];
  mean /= n;
  let v = 0;
  for (let i = 0; i < n; i++) v += sq(x[i] - mean);
  const sd = Math.sqrt(v / n);
  if (!(sd > 0)) return null;
  let xmin = Infinity;
  for (let i = 0; i < n; i++) if (x[i] < xmin) xmin = x[i];
  const g = (lb) => {
    const b = Math.exp(lb);
    let sw = 0; let swx = 0;
    for (let i = 0; i < n; i++) { const w = Math.exp(-(x[i] - xmin) / b); sw += w; swx += w * x[i]; }
    return b - mean + swx / sw;
  };
  const b0 = sd * Math.sqrt(6) / Math.PI;
  const lb = brentRoot(g, Math.log(b0 / 100), Math.log(b0 * 100));
  if (!Number.isFinite(lb)) return null;
  const b = Math.exp(lb);
  let sw = 0;
  for (let i = 0; i < n; i++) sw += Math.exp(-(x[i] - xmin) / b);
  return { mu: xmin - b * Math.log(sw / n), beta: b };
}

const gumbelParams = () => [field('mu', 'Location μ (mode)', 'real'), field('beta', 'Scale β', 'pos')];

export const gumbel = locationScale({
  id: 'gumbel', label: 'Gumbel (maxima)', kind: 'continuous', group: 'Extremes',
  blurb: 'The largest of many values: annual maximum floods, winds and loads (extreme value type I).',
  params: gumbelParams(),
  defaults: { mu: 0, beta: 1 },
  parameterisations: [
    { id: 'loc-scale', label: 'Location μ and scale β', fields: gumbelParams(), to: (v) => ({ mu: v.mu, beta: v.beta }), from: (p) => ({ mu: p.mu, beta: p.beta }) },
    { id: 'mean-sd', label: 'Mean and SD', fields: [field('mean', 'Mean', 'real'), field('sd', 'Standard deviation', 'pos')],
      to: (v) => { const b = v.sd * Math.sqrt(6) / Math.PI; return { mu: v.mean - EULER * b, beta: b }; }, from: (p) => ({ mean: p.mu + EULER * p.beta, sd: p.beta * Math.PI / Math.sqrt(6) }) },
  ],
  free: { keys: ['mu', 'beta'], to: (p) => [p.mu, Math.log(p.beta)], from: (z) => ({ mu: z[0], beta: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    mle: (s) => gumbelMle(s.x, s.n),
    mom: (s) => { const b = s.sd * Math.sqrt(6) / Math.PI; return { mu: s.mean - EULER * b, beta: b }; },
  },
  tex: { pdf: R`f(x)=\frac1\beta e^{-(z+e^{-z})},\ z=\frac{x-\mu}{\beta}`, cdf: R`F(x)=e^{-e^{-z}}`, mean: R`\mu+\gamma\beta`, variance: R`\frac{\pi^2\beta^2}{6}` },
  scipy: 'gumbel_r(loc=μ, scale=β)',
}, {
  logpdf: (z) => -z - Math.exp(-z),
  cdf: (z) => Math.exp(-Math.exp(-z)),
  sf: (z) => -Math.expm1(-Math.exp(-z)),
  logcdf: (z) => -Math.exp(-z),
  quantile: (u) => -Math.log(-Math.log(u)),
  isf: (q) => -Math.log(-Math.log1p(-q)),
  mean: () => EULER, variance: () => Math.PI * Math.PI / 6, skewness: () => SKEW_GUMBEL, kurtosis: () => 2.4,
  entropy: () => EULER + 1, mode: () => 0, median: () => -Math.log(LN2),
}, { loc: 'mu', scale: 'beta' });

export const gumbelmin = locationScale({
  id: 'gumbelmin', label: 'Gumbel (minima)', kind: 'continuous', group: 'Extremes',
  blurb: 'The smallest of many values: the weakest link, the lowest flow.',
  params: gumbelParams(),
  defaults: { mu: 0, beta: 1 },
  parameterisations: [
    { id: 'loc-scale', label: 'Location μ and scale β', fields: gumbelParams(), to: (v) => ({ mu: v.mu, beta: v.beta }), from: (p) => ({ mu: p.mu, beta: p.beta }) },
    { id: 'mean-sd', label: 'Mean and SD', fields: [field('mean', 'Mean', 'real'), field('sd', 'Standard deviation', 'pos')],
      to: (v) => { const b = v.sd * Math.sqrt(6) / Math.PI; return { mu: v.mean + EULER * b, beta: b }; }, from: (p) => ({ mean: p.mu - EULER * p.beta, sd: p.beta * Math.PI / Math.sqrt(6) }) },
  ],
  free: { keys: ['mu', 'beta'], to: (p) => [p.mu, Math.log(p.beta)], from: (z) => ({ mu: z[0], beta: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    mle: (s) => { const g = gumbelMle(Float64Array.from(s.x, (v) => -v), s.n); return g ? { mu: -g.mu, beta: g.beta } : null; },
    mom: (s) => { const b = s.sd * Math.sqrt(6) / Math.PI; return { mu: s.mean + EULER * b, beta: b }; },
  },
  tex: { pdf: R`f(x)=\frac1\beta e^{z-e^{z}},\ z=\frac{x-\mu}{\beta}`, cdf: R`F(x)=1-e^{-e^{z}}`, mean: R`\mu-\gamma\beta`, variance: R`\frac{\pi^2\beta^2}{6}` },
  scipy: 'gumbel_l(loc=μ, scale=β)',
}, {
  logpdf: (z) => z - Math.exp(z),
  cdf: (z) => -Math.expm1(-Math.exp(z)),
  sf: (z) => Math.exp(-Math.exp(z)),
  logsf: (z) => -Math.exp(z),
  quantile: (u) => Math.log(-Math.log1p(-u)),
  isf: (q) => Math.log(-Math.log(q)),
  mean: () => -EULER, variance: () => Math.PI * Math.PI / 6, skewness: () => -SKEW_GUMBEL, kurtosis: () => 2.4,
  entropy: () => EULER + 1, mode: () => 0, median: () => Math.log(LN2),
}, { loc: 'mu', scale: 'beta' });

/* ======================================================================
   Generalized extreme value and generalized Pareto
   ====================================================================== */

/* The GEV's skewness and kurtosis from Gamma(1 - k xi). Both are ratios of
   differences that vanish like xi^3 and xi^4, so within 0.01 of zero, where
   the rounding would show, they are interpolated (a quartic) through
   +-0.01, +-0.02 and the Gumbel's own value at zero. */
function gevSkew(xi) {
  const g1 = gammaFn(1 - xi); const g2 = gammaFn(1 - 2 * xi); const g3 = gammaFn(1 - 3 * xi);
  return Math.sign(xi) * (g3 - 3 * g1 * g2 + 2 * g1 ** 3) / Math.pow(g2 - g1 * g1, 1.5);
}
function gevKurt(xi) {
  const g1 = gammaFn(1 - xi); const g2 = gammaFn(1 - 2 * xi); const g3 = gammaFn(1 - 3 * xi); const g4 = gammaFn(1 - 4 * xi);
  return (g4 - 4 * g1 * g3 + 6 * g2 * g1 * g1 - 3 * g1 ** 4) / sq(g2 - g1 * g1) - 3;
}
function nearZero(f, xi, atZero) {
  const h = 0.01;
  if (Math.abs(xi) >= h) return f(xi);
  const xs = [-2 * h, -h, 0, h, 2 * h];
  const ys = [f(-2 * h), f(-h), atZero, f(h), f(2 * h)];
  let s = 0;
  for (let i = 0; i < 5; i++) {
    let l = 1;
    for (let j = 0; j < 5; j++) if (j !== i) l *= (xi - xs[j]) / (xs[i] - xs[j]);
    s += ys[i] * l;
  }
  return s;
}

/* ln t(z) for the GEV: -log1p(xi z)/xi, -z in the limit xi -> 0. */
const gevLnT = (z, xi) => (Math.abs(xi) < 1e-12 ? -z : -Math.log1p(xi * z) / xi);
const xiFactor = (xi, t) => (Math.abs(xi) < 1e-12 ? t : Math.expm1(xi * t) / xi);   // (e^(xi t) - 1)/xi

export const gev = locationScale({
  id: 'gev', label: 'Generalized extreme value', kind: 'continuous', group: 'Extremes',
  blurb: 'The three kinds of block maximum in one: Gumbel (ξ = 0), Fréchet with a heavy upper tail (ξ > 0) and reversed Weibull with an upper bound (ξ < 0).',
  params: [field('mu', 'Location μ', 'real'), field('sigma', 'Scale σ', 'pos'), field('xi', 'Shape ξ', 'real')],
  defaults: { mu: 0, sigma: 1, xi: 0.1 },
  parameterisations: [
    { id: 'loc-scale-shape', label: 'Location, scale and shape', fields: [field('mu', 'Location μ', 'real'), field('sigma', 'Scale σ', 'pos'), field('xi', 'Shape ξ', 'real')],
      to: (v) => ({ mu: v.mu, sigma: v.sigma, xi: v.xi }), from: (p) => ({ mu: p.mu, sigma: p.sigma, xi: p.xi }) },
  ],
  free: { keys: ['mu', 'sigma', 'xi'], to: (p) => [p.mu, Math.log(p.sigma), p.xi], from: (z) => ({ mu: z[0], sigma: Math.exp(z[1]), xi: z[2] }) },
  fit: {
    k: 3,
    mle: (s) => {
      const nll = ([m, ls, xi]) => {
        if (xi <= -1 || xi > 5) return Infinity;
        const sg = Math.exp(ls);
        let ll = 0;
        for (let i = 0; i < s.n; i++) {
          const z = (s.x[i] - m) / sg;
          if (1 + xi * z <= 0) return Infinity;
          const lt = gevLnT(z, xi);
          ll += (xi + 1) * lt - Math.exp(lt);
        }
        return -(ll - s.n * ls);
      };
      const starts = [];
      const g = gumbelMle(s.x, s.n);
      if (g) starts.push([g.mu, Math.log(g.beta), 0.05], [g.mu, Math.log(g.beta), -0.05]);
      const mm = gev.fit.mom(s);
      if (mm && mm.params) starts.push([mm.params.mu, Math.log(mm.params.sigma), mm.params.xi]);
      let best = null;
      for (const z0 of starts) {
        if (!Number.isFinite(nll(z0))) continue;
        const got = nelderMead(nll, z0, { steps: [0.1 * s.sd, 0.1, 0.05] });
        if (!best || got.f < best.f) best = got;
      }
      return best && Number.isFinite(best.f) ? { mu: best.x[0], sigma: Math.exp(best.x[1]), xi: best.x[2] } : null;
    },
    mom: (s) => {
      const skewAt = (xi) => gev.skewness({ mu: 0, sigma: 1, xi });
      const target = s.skew;
      const f = (xi) => { const v = skewAt(xi); return Number.isFinite(v) ? v - target : (xi > 0 ? 1e9 : -1e9); };
      let xi;
      if (f(-2) > 0) xi = -2;
      else if (f(0.3333) < 0) xi = 0.3333;
      else xi = brentRoot(f, -2, 0.3333);
      if (!Number.isFinite(xi)) return null;
      const v1 = gev.variance({ mu: 0, sigma: 1, xi });
      const m1 = gev.mean({ mu: 0, sigma: 1, xi });
      const sigma = s.sd / Math.sqrt(v1);
      const clamped = xi === -2 || xi === 0.3333;
      return { params: { mu: s.mean - sigma * m1, sigma, xi }, note: clamped ? 'the sample’s skewness is beyond what this family reaches; this is the nearest' : '' };
    },
  },
  tex: {
    pdf: R`f(x)=\frac1\sigma\,t^{\xi+1}e^{-t},\ t=\left(1+\xi\frac{x-\mu}{\sigma}\right)^{-1/\xi}`,
    cdf: R`F(x)=e^{-t}`,
    mean: R`\mu+\sigma\frac{\Gamma(1-\xi)-1}{\xi},\ \xi<1`, variance: R`\sigma^2\frac{\Gamma(1-2\xi)-\Gamma(1-\xi)^2}{\xi^2},\ \xi<\tfrac12`,
  },
  scipy: 'genextreme(c=−ξ, loc=μ, scale=σ) — note SciPy’s opposite sign of the shape',
}, {
  support: (xi) => (xi > 0 ? [-1 / xi, Infinity] : xi < 0 ? [-Infinity, -1 / xi] : [-Infinity, Infinity]),
  logpdf: (z, xi) => {
    if (Math.abs(xi) >= 1e-12 && 1 + xi * z <= 0) return -Infinity;
    const lt = gevLnT(z, xi);
    return (xi + 1) * lt - Math.exp(lt);
  },
  cdf: (z, xi) => {
    if (Math.abs(xi) >= 1e-12 && 1 + xi * z <= 0) return xi > 0 ? 0 : 1;
    return Math.exp(-Math.exp(gevLnT(z, xi)));
  },
  sf: (z, xi) => {
    if (Math.abs(xi) >= 1e-12 && 1 + xi * z <= 0) return xi > 0 ? 1 : 0;
    return -Math.expm1(-Math.exp(gevLnT(z, xi)));
  },
  /* z = ((-ln u)^(-xi) - 1)/xi */
  quantile: (u, xi) => xiFactor(xi, -Math.log(-Math.log(u))),
  isf: (q, xi) => xiFactor(xi, -Math.log(-Math.log1p(-q))),
  mean: (xi) => (xi >= 1 ? Infinity : Math.abs(xi) < 1e-12 ? EULER : Math.expm1(lgamma(1 - xi)) / xi),
  variance: (xi) => {
    if (xi >= 0.5) return xi < 1 ? Infinity : NaN;
    if (Math.abs(xi) < 1e-8) return Math.PI * Math.PI / 6;
    return sq(gammaFn(1 - xi)) * Math.expm1(lgamma(1 - 2 * xi) - 2 * lgamma(1 - xi)) / (xi * xi);
  },
  skewness: (xi) => (xi >= 0.5 ? NaN : xi >= 1 / 3 ? Infinity : nearZero(gevSkew, xi, SKEW_GUMBEL)),
  kurtosis: (xi) => (xi >= 0.5 ? NaN : xi >= 0.25 ? Infinity : nearZero(gevKurt, xi, 2.4)),
  entropy: (xi) => EULER * (1 + xi) + 1,
  mode: (xi) => (xi <= -1 ? -1 / xi : xiFactor(xi, -Math.log1p(xi))),
  median: (xi) => xiFactor(xi, -Math.log(LN2)),
  tails: (xi) => ({ left: Infinity, right: xi > 0 ? 1 / xi : Infinity }),
}, { loc: 'mu', scale: 'sigma' }, (p) => p.xi);

export const genpareto = locationScale({
  id: 'genpareto', label: 'Generalized Pareto', kind: 'continuous', group: 'Extremes',
  blurb: 'Exceedances over a high threshold (peaks over threshold): exponential for ξ = 0, a heavy tail for ξ > 0, an upper bound for ξ < 0.',
  params: [field('mu', 'Threshold μ', 'real'), field('sigma', 'Scale σ', 'pos'), field('xi', 'Shape ξ', 'real')],
  defaults: { mu: 0, sigma: 1, xi: 0.2 },
  parameterisations: [
    { id: 'loc-scale-shape', label: 'Threshold, scale and shape', fields: [field('mu', 'Threshold μ', 'real'), field('sigma', 'Scale σ', 'pos'), field('xi', 'Shape ξ', 'real')],
      to: (v) => ({ mu: v.mu, sigma: v.sigma, xi: v.xi }), from: (p) => ({ mu: p.mu, sigma: p.sigma, xi: p.xi }) },
  ],
  free: { keys: ['sigma', 'xi'], to: (p) => [Math.log(p.sigma), p.xi], from: (z, p0) => ({ mu: p0 ? p0.mu : 0, sigma: Math.exp(z[0]), xi: z[1] }) },
  fit: {
    k: 2,
    note: 'threshold μ = 0',
    applicable: (s) => (s.nonneg ? '' : 'needs values of zero or above (the threshold is fixed at 0)'),
    mle: (s) => {
      const nll = ([ls, xi]) => {
        if (xi <= -1 || xi > 5) return Infinity;
        const sg = Math.exp(ls);
        let ll = 0;
        for (let i = 0; i < s.n; i++) {
          const z = s.x[i] / sg;
          if (Math.abs(xi) < 1e-12) ll -= z;
          else { if (1 + xi * z <= 0) return Infinity; ll -= (1 / xi + 1) * Math.log1p(xi * z); }
        }
        return -(ll - s.n * ls);
      };
      const mm = genpareto.fit.mom(s);
      const starts = [[Math.log(s.mean), 0.01], [Math.log(s.mean), -0.1]];
      if (mm) starts.push([Math.log(mm.sigma), mm.xi]);
      let best = null;
      for (const z0 of starts) {
        if (!Number.isFinite(nll(z0))) continue;
        const got = nelderMead(nll, z0, { steps: [0.1, 0.05] });
        if (!best || got.f < best.f) best = got;
      }
      return best && Number.isFinite(best.f) ? { mu: 0, sigma: Math.exp(best.x[0]), xi: best.x[1] } : null;
    },
    mom: (s) => { const xi = (1 - s.mean * s.mean / s.var) / 2; return { mu: 0, sigma: s.mean * (1 - xi), xi }; },
  },
  tex: {
    pdf: R`f(x)=\frac1\sigma\left(1+\xi z\right)^{-1/\xi-1},\ z=\frac{x-\mu}{\sigma}\ge0`, cdf: R`F(x)=1-\left(1+\xi z\right)^{-1/\xi}`,
    mean: R`\mu+\frac{\sigma}{1-\xi},\ \xi<1`, variance: R`\frac{\sigma^2}{(1-\xi)^2(1-2\xi)},\ \xi<\tfrac12`,
  },
  scipy: 'genpareto(c=ξ, loc=μ, scale=σ)',
}, {
  support: (xi) => [0, xi < 0 ? -1 / xi : Infinity],
  logpdf: (z, xi) => {
    if (z < 0) return -Infinity;
    if (Math.abs(xi) < 1e-12) return -z;
    if (1 + xi * z <= 0) return -Infinity;
    return -(1 / xi + 1) * Math.log1p(xi * z);
  },
  sf: (z, xi) => {
    if (z <= 0) return 1;
    if (Math.abs(xi) < 1e-12) return Math.exp(-z);
    if (1 + xi * z <= 0) return 0;
    return Math.exp(-Math.log1p(xi * z) / xi);
  },
  cdf: (z, xi) => {
    if (z <= 0) return 0;
    if (Math.abs(xi) < 1e-12) return -Math.expm1(-z);
    if (1 + xi * z <= 0) return 1;
    return -Math.expm1(-Math.log1p(xi * z) / xi);
  },
  quantile: (u, xi) => xiFactor(xi, -Math.log1p(-u)),
  isf: (q, xi) => xiFactor(xi, -Math.log(q)),
  mean: (xi) => (xi >= 1 ? Infinity : 1 / (1 - xi)),
  variance: (xi) => (xi >= 0.5 ? (xi < 1 ? Infinity : NaN) : 1 / (sq(1 - xi) * (1 - 2 * xi))),
  skewness: (xi) => (xi >= 0.5 ? NaN : xi >= 1 / 3 ? Infinity : 2 * (1 + xi) * Math.sqrt(1 - 2 * xi) / (1 - 3 * xi)),
  kurtosis: (xi) => (xi >= 0.5 ? NaN : xi >= 0.25 ? Infinity : 3 * (1 - 2 * xi) * (2 * xi * xi + xi + 3) / ((1 - 3 * xi) * (1 - 4 * xi)) - 3),
  entropy: (xi) => xi + 1,
  mode: (xi) => (xi < -1 ? -1 / xi : 0),
  median: (xi) => xiFactor(xi, LN2),
  tails: (xi) => ({ left: Infinity, right: xi > 0 ? 1 / xi : Infinity }),
}, { loc: 'mu', scale: 'sigma' }, (p) => p.xi);

/* ======================================================================
   Student's t
   ====================================================================== */

const NU_MAX = 1e3;

/* Above nu = 1e4 the t is its Cornish-Fisher expansion in 1/nu about the
   normal (Fisher 1925; terms to 1/nu^4, the first left out below 1e-17 of
   the quantile there): its incomplete beta has one parameter so large that
   the continued fraction would need millions of terms. */
const NU_ASYMP = 1e4;
function tOfZ(x, nu) {
  const x2 = x * x;
  const g1 = (x2 + 1) * x / 4;
  const g2 = ((5 * x2 + 16) * x2 + 3) * x / 96;
  const g3 = (((3 * x2 + 19) * x2 + 17) * x2 - 15) * x / 384;
  const g4 = ((((79 * x2 + 776) * x2 + 1482) * x2 - 1920) * x2 - 945) * x / 92160;
  const r = 1 / nu;
  return x + r * (g1 + r * (g2 + r * (g3 + r * g4)));
}
function zOfT(t, nu) {
  let x = t;
  for (let i = 0; i < 8; i++) {
    const h = 1e-6 * Math.max(1, Math.abs(x));
    const d = (tOfZ(x + h, nu) - tOfZ(x - h, nu)) / (2 * h);
    const dx = (tOfZ(x, nu) - t) / d;
    x -= dx;
    if (!(Math.abs(dx) > 1e-16 * Math.max(1, Math.abs(x)))) break;
  }
  return x;
}

export const studentt = locationScale({
  id: 'studentt', label: 'Student’s t', kind: 'continuous', group: 'General',
  blurb: 'A normal with heavier tails, the fewer the degrees of freedom the heavier; the normal as ν grows.',
  params: [field('nu', 'Degrees of freedom ν', 'pos'), field('mu', 'Location μ', 'real'), field('sigma', 'Scale σ', 'pos')],
  defaults: { nu: 5, mu: 0, sigma: 1 },
  parameterisations: [
    { id: 'df-loc-scale', label: 'ν, location and scale', fields: [field('nu', 'Degrees of freedom ν', 'pos'), field('mu', 'Location μ', 'real'), field('sigma', 'Scale σ', 'pos')],
      to: (v) => ({ nu: v.nu, mu: v.mu, sigma: v.sigma }), from: (p) => ({ nu: p.nu, mu: p.mu, sigma: p.sigma }) },
    { id: 'df-mean-sd', label: 'ν, mean and SD (ν > 2)', fields: [field('nu', 'Degrees of freedom ν', 'pos'), field('mean', 'Mean', 'real'), field('sd', 'Standard deviation', 'pos')],
      to: (v) => { need(v.nu > 2, 'The SD exists only for ν above 2.'); return { nu: v.nu, mu: v.mean, sigma: v.sd * Math.sqrt((v.nu - 2) / v.nu) }; },
      from: (p) => ({ nu: p.nu, mean: p.mu, sd: p.nu > 2 ? p.sigma * Math.sqrt(p.nu / (p.nu - 2)) : NaN }) },
  ],
  free: { keys: ['nu', 'mu', 'sigma'], to: (p) => [Math.log(p.nu), p.mu, Math.log(p.sigma)], from: (z) => ({ nu: Math.exp(z[0]), mu: z[1], sigma: Math.exp(z[2]) }) },
  fit: {
    k: 3,
    mle: (s) => {
      const nll = ([lnu, m, ls]) => {
        const nu = Math.exp(lnu);
        if (nu > NU_MAX || nu < 0.05) return Infinity;
        const sg = Math.exp(ls);
        let ll = 0;
        for (let i = 0; i < s.n; i++) ll += Math.log1p(sq((s.x[i] - m) / sg) / nu);
        return -(s.n * (-lbeta(nu / 2, 0.5) - 0.5 * Math.log(nu) - ls) - (nu + 1) / 2 * ll);
      };
      const med = s.x[Math.floor(s.n / 2)];
      let best = null;
      for (const nu0 of [3, 30]) {
        const z0 = [Math.log(nu0), med, Math.log(s.sd * Math.sqrt(nu0 > 2 ? (nu0 - 2) / nu0 : 0.5) || 1)];
        const got = nelderMead(nll, z0, { steps: [0.5, 0.1 * s.sd, 0.1] });
        if (!best || got.f < best.f) best = got;
      }
      const nu = Math.exp(best.x[0]);
      const atLimit = nu > 0.99 * NU_MAX;
      return { params: { nu, mu: best.x[1], sigma: Math.exp(best.x[2]) }, atLimit, note: atLimit ? `ν at its limit of ${NU_MAX}: the sample’s tails are no heavier than a normal’s` : '' };
    },
    mom: (s) => {
      const nu = s.kurt > 6 / (NU_MAX - 4) ? 4 + 6 / s.kurt : NU_MAX;
      return { params: { nu, mu: s.mean, sigma: s.sd * Math.sqrt((nu - 2) / nu) }, note: nu === NU_MAX ? 'the sample’s kurtosis is not above a normal’s; ν set to its limit' : '' };
    },
  },
  tex: {
    pdf: R`f(x)=\frac{\Gamma\!\left(\frac{\nu+1}{2}\right)}{\sigma\sqrt{\nu\pi}\,\Gamma\!\left(\frac\nu2\right)}\left(1+\frac{z^2}{\nu}\right)^{-\frac{\nu+1}{2}},\ z=\frac{x-\mu}{\sigma}`,
    cdf: R`F(x)=1-\tfrac12 I_{\nu/(\nu+z^2)}\!\left(\tfrac\nu2,\tfrac12\right),\ z\ge0`,
    mean: R`\mu,\ \nu>1`, variance: R`\sigma^2\frac{\nu}{\nu-2},\ \nu>2`,
  },
  scipy: 't(df=ν, loc=μ, scale=σ)',
}, {
  logpdf: (z, nu) => (nu > 1e15 ? normLogPdf(z) : -lbeta(nu / 2, 0.5) - 0.5 * Math.log(nu) - (nu + 1) / 2 * Math.log1p(z * z / nu)),
  cdf: (z, nu) => {
    if (nu > NU_ASYMP) return normCdf(zOfT(z, nu));
    const t2 = z * z;
    const tail = 0.5 * betaInc(nu / 2, 0.5, nu / (nu + t2), t2 / (nu + t2))[0];
    return z < 0 ? tail : 1 - tail;
  },
  sf: (z, nu) => {
    if (nu > NU_ASYMP) return normSf(zOfT(z, nu));
    const t2 = z * z;
    const tail = 0.5 * betaInc(nu / 2, 0.5, nu / (nu + t2), t2 / (nu + t2))[0];
    return z > 0 ? tail : 1 - tail;
  },
  quantile: (u, nu) => {
    if (nu > NU_ASYMP) return tOfZ(normQuantile(u), nu);
    if (u === 0.5) return 0;
    const lower = u < 0.5;
    const p = 2 * (lower ? u : 1 - u);
    const [x, y] = betaIncInv(nu / 2, 0.5, p, 1 - p);
    const t = Math.sqrt(nu * y / x);
    return lower ? -t : t;
  },
  isf: (q, nu) => {
    if (nu > NU_ASYMP) return tOfZ(normIsf(q), nu);
    if (q === 0.5) return 0;
    const upper = q < 0.5;
    const p = 2 * (upper ? q : 1 - q);
    const [x, y] = betaIncInv(nu / 2, 0.5, p, 1 - p);
    const t = Math.sqrt(nu * y / x);
    return upper ? t : -t;
  },
  mean: (nu) => (nu > 1 ? 0 : NaN),
  variance: (nu) => (nu > 2 ? nu / (nu - 2) : nu > 1 ? Infinity : NaN),
  skewness: (nu) => (nu > 3 ? 0 : NaN),
  kurtosis: (nu) => (nu > 4 ? 6 / (nu - 4) : nu > 2 ? Infinity : NaN),
  entropy: (nu) => (nu + 1) / 2 * (digamma((nu + 1) / 2) - digamma(nu / 2)) + 0.5 * Math.log(nu) + lbeta(nu / 2, 0.5),
  mode: () => 0,
  median: () => 0,
  tails: (nu) => ({ left: nu, right: nu }),
}, { loc: 'mu', scale: 'sigma' }, (p) => p.nu);

/* ======================================================================
   F
   ====================================================================== */

export const fdist = {
  id: 'f', label: 'F', kind: 'continuous', group: 'Positive',
  blurb: 'The ratio of two independent chi-squares, each over its degrees of freedom: the distribution of a variance ratio.',
  params: [field('d1', 'Numerator d₁', 'pos'), field('d2', 'Denominator d₂', 'pos')],
  defaults: { d1: 5, d2: 10 },
  support: () => [0, Infinity],
  logpdf: (x, p) => {
    const { d1, d2 } = p;
    if (x < 0) return -Infinity;
    if (x === 0) return d1 < 2 ? Infinity : d1 === 2 ? 0 : -Infinity;
    return (d1 / 2) * Math.log(d1 / d2) + (d1 / 2 - 1) * Math.log(x) - ((d1 + d2) / 2) * Math.log1p(d1 * x / d2) - lbeta(d1 / 2, d2 / 2);
  },
  cdf: (x, p) => (x <= 0 ? 0 : betaInc(p.d1 / 2, p.d2 / 2, p.d1 * x / (p.d1 * x + p.d2), p.d2 / (p.d1 * x + p.d2))[0]),
  sf: (x, p) => (x <= 0 ? 1 : betaInc(p.d1 / 2, p.d2 / 2, p.d1 * x / (p.d1 * x + p.d2), p.d2 / (p.d1 * x + p.d2))[1]),
  quantile: (u, p) => { const [b, bc] = betaIncInv(p.d1 / 2, p.d2 / 2, u, 1 - u); return p.d2 * b / (p.d1 * bc); },
  isf: (q, p) => { const [b, bc] = betaIncInv(p.d1 / 2, p.d2 / 2, 1 - q, q); return p.d2 * b / (p.d1 * bc); },
  mean: (p) => (p.d2 > 2 ? p.d2 / (p.d2 - 2) : Infinity),
  variance: (p) => (p.d2 > 4 ? 2 * p.d2 * p.d2 * (p.d1 + p.d2 - 2) / (p.d1 * sq(p.d2 - 2) * (p.d2 - 4)) : p.d2 > 2 ? Infinity : NaN),
  skewness: (p) => (p.d2 > 6 ? (2 * p.d1 + p.d2 - 2) * Math.sqrt(8 * (p.d2 - 4)) / ((p.d2 - 6) * Math.sqrt(p.d1 * (p.d1 + p.d2 - 2))) : p.d2 > 4 ? Infinity : NaN),
  kurtosis: (p) => {
    const { d1, d2 } = p;
    if (!(d2 > 8)) return d2 > 4 ? Infinity : NaN;
    return 12 * (d1 * (5 * d2 - 22) * (d1 + d2 - 2) + (d2 - 4) * sq(d2 - 2)) / (d1 * (d2 - 6) * (d2 - 8) * (d1 + d2 - 2));
  },
  entropy: (p) => {
    const { d1, d2 } = p;
    return Math.log(d2 / d1) + lbeta(d1 / 2, d2 / 2) + (1 - d1 / 2) * digamma(d1 / 2) - (1 + d2 / 2) * digamma(d2 / 2) + ((d1 + d2) / 2) * digamma((d1 + d2) / 2);
  },
  mode: (p) => (p.d1 > 2 ? (p.d1 - 2) / p.d1 * p.d2 / (p.d2 + 2) : 0),
  tails: (p) => ({ left: Infinity, right: p.d2 / 2 }),
  parameterisations: [
    { id: 'df', label: 'Degrees of freedom', fields: [field('d1', 'Numerator d₁', 'pos'), field('d2', 'Denominator d₂', 'pos')],
      to: (v) => ({ d1: v.d1, d2: v.d2 }), from: (p) => ({ d1: p.d1, d2: p.d2 }) },
  ],
  free: { keys: ['d1', 'd2'], to: (p) => [Math.log(p.d1), Math.log(p.d2)], from: (z) => ({ d1: Math.exp(z[0]), d2: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    applicable: (s) => (s.positive ? '' : 'needs every value above zero'),
    mle: (s) => {
      const lx = Float64Array.from(s.x, Math.log);
      let sumLx = 0;
      for (let i = 0; i < s.n; i++) sumLx += lx[i];
      const nll = ([l1, l2]) => {
        const d1 = Math.exp(l1); const d2 = Math.exp(l2);
        if (d1 > 1e6 || d2 > 1e6) return Infinity;
        const r = d1 / d2;
        let t = 0;
        for (let i = 0; i < s.n; i++) t += Math.log1p(r * s.x[i]);
        return -(s.n * ((d1 / 2) * Math.log(r) - lbeta(d1 / 2, d2 / 2)) + (d1 / 2 - 1) * sumLx - ((d1 + d2) / 2) * t);
      };
      const mm = fdist.fit.mom(s);
      const z0 = mm ? [Math.log(mm.d1), Math.log(mm.d2)] : [Math.log(5), Math.log(10)];
      const got = nelderMead(nll, z0, { steps: [0.5, 0.5] });
      if (!Number.isFinite(got.f)) return null;
      const d1 = Math.exp(got.x[0]);
      const d2 = Math.exp(got.x[1]);
      const capped = d1 > 0.5e6 || d2 > 0.5e6;
      return { params: { d1, d2 }, atLimit: capped, note: capped ? 'a degree of freedom ran to its limit of a million: the sample is not shaped like an F' : '' };
    },
    mom: (s) => {
      if (!(s.mean > 1)) return null;
      const d2 = 2 * s.mean / (s.mean - 1);
      if (!(d2 > 4)) return null;
      const den = s.var * sq(d2 - 2) * (d2 - 4) - 2 * d2 * d2;
      if (!(den > 0)) return null;
      return { d1: 2 * d2 * d2 * (d2 - 2) / den, d2 };
    },
  },
  tex: {
    pdf: R`f(x)=\frac{\left(\frac{d_1}{d_2}\right)^{d_1/2}x^{d_1/2-1}}{B\!\left(\frac{d_1}2,\frac{d_2}2\right)\left(1+\frac{d_1x}{d_2}\right)^{(d_1+d_2)/2}}`,
    cdf: R`F(x)=I_{d_1x/(d_1x+d_2)}\!\left(\tfrac{d_1}2,\tfrac{d_2}2\right)`, mean: R`\frac{d_2}{d_2-2},\ d_2>2`,
    variance: R`\frac{2d_2^2(d_1+d_2-2)}{d_1(d_2-2)^2(d_2-4)},\ d_2>4`,
  },
  scipy: 'f(dfn=d₁, dfd=d₂)',
};

/* ======================================================================
   Pareto, Rayleigh, half-normal
   ====================================================================== */

export const pareto = {
  id: 'pareto', label: 'Pareto', kind: 'continuous', group: 'Positive',
  blurb: 'A power-law tail above a minimum: incomes, city sizes, the few large among the many small.',
  params: [field('xm', 'Minimum xₘ', 'pos'), field('alpha', 'Shape α', 'pos')],
  defaults: { xm: 1, alpha: 3 },
  support: (p) => [p.xm, Infinity],
  logpdf: (x, p) => (x >= p.xm ? Math.log(p.alpha) + p.alpha * Math.log(p.xm) - (p.alpha + 1) * Math.log(x) : -Infinity),
  /* ln(x/xm) as log1p of the difference, which is exact near xm where the
     ratio would be rounded first */
  cdf: (x, p) => (x <= p.xm ? 0 : -Math.expm1(-p.alpha * Math.log1p((x - p.xm) / p.xm))),
  sf: (x, p) => (x <= p.xm ? 1 : Math.exp(-p.alpha * Math.log1p((x - p.xm) / p.xm))),
  logsf: (x, p) => (x <= p.xm ? 0 : -p.alpha * Math.log1p((x - p.xm) / p.xm)),
  quantile: (u, p) => p.xm * Math.exp(-Math.log1p(-u) / p.alpha),
  isf: (q, p) => p.xm * Math.exp(-Math.log(q) / p.alpha),
  mean: (p) => (p.alpha > 1 ? p.alpha * p.xm / (p.alpha - 1) : Infinity),
  variance: (p) => (p.alpha > 2 ? p.xm * p.xm * p.alpha / (sq(p.alpha - 1) * (p.alpha - 2)) : p.alpha > 1 ? Infinity : NaN),
  skewness: (p) => (p.alpha > 3 ? 2 * (1 + p.alpha) / (p.alpha - 3) * Math.sqrt((p.alpha - 2) / p.alpha) : p.alpha > 2 ? Infinity : NaN),
  kurtosis: (p) => { const a = p.alpha; return a > 4 ? 6 * (a ** 3 + a * a - 6 * a - 2) / (a * (a - 3) * (a - 4)) : a > 2 ? Infinity : NaN; },
  entropy: (p) => Math.log(p.xm / p.alpha) + 1 / p.alpha + 1,
  mode: (p) => p.xm,
  median: (p) => p.xm * Math.pow(2, 1 / p.alpha),
  logMoments: (p) => [Math.log(p.xm) + 1 / p.alpha, 1 / (p.alpha * p.alpha)],
  tails: (p) => ({ left: Infinity, right: p.alpha }),
  parameterisations: [
    { id: 'scale-shape', label: 'Minimum xₘ and shape α', fields: [field('xm', 'Minimum xₘ', 'pos'), field('alpha', 'Shape α', 'pos')],
      to: (v) => ({ xm: v.xm, alpha: v.alpha }), from: (p) => ({ xm: p.xm, alpha: p.alpha }) },
  ],
  free: { keys: ['xm', 'alpha'], to: (p) => [Math.log(p.xm), Math.log(p.alpha)], from: (z) => ({ xm: Math.exp(z[0]), alpha: Math.exp(z[1]) }) },
  fit: {
    k: 2, regular: false,
    applicable: (s) => (s.positive ? '' : 'needs every value above zero'),
    mle: (s) => {
      let t = 0;
      for (let i = 0; i < s.n; i++) t += Math.log(s.x[i] / s.min);
      return t > 0 ? { params: { xm: s.min, alpha: s.n / t }, edges: true } : null;
    },
    mom: (s) => { const a = 1 + Math.sqrt(1 + s.mean * s.mean / s.var); return { xm: s.mean * (a - 1) / a, alpha: a }; },
  },
  tex: {
    pdf: R`f(x)=\frac{\alpha x_m^\alpha}{x^{\alpha+1}},\ x\ge x_m`, cdf: R`F(x)=1-\left(\frac{x_m}{x}\right)^\alpha`,
    mean: R`\frac{\alpha x_m}{\alpha-1},\ \alpha>1`, variance: R`\frac{x_m^2\alpha}{(\alpha-1)^2(\alpha-2)},\ \alpha>2`,
  },
  scipy: 'pareto(b=α, scale=xₘ)',
};

export const rayleigh = {
  id: 'rayleigh', label: 'Rayleigh', kind: 'continuous', group: 'Positive',
  blurb: 'The length of a vector whose two components are independent normals: wind speeds, wave heights.',
  params: [field('sigma', 'Scale σ', 'pos')],
  defaults: { sigma: 1 },
  support: () => [0, Infinity],
  logpdf: (x, p) => (x > 0 ? Math.log(x) - 2 * Math.log(p.sigma) - x * x / (2 * p.sigma * p.sigma) : -Infinity),
  cdf: (x, p) => (x <= 0 ? 0 : -Math.expm1(-x * x / (2 * p.sigma * p.sigma))),
  sf: (x, p) => (x <= 0 ? 1 : Math.exp(-x * x / (2 * p.sigma * p.sigma))),
  logsf: (x, p) => (x <= 0 ? 0 : -x * x / (2 * p.sigma * p.sigma)),
  quantile: (u, p) => p.sigma * Math.sqrt(-2 * Math.log1p(-u)),
  isf: (q, p) => p.sigma * Math.sqrt(-2 * Math.log(q)),
  mean: (p) => p.sigma * Math.sqrt(Math.PI / 2),
  variance: (p) => (4 - Math.PI) / 2 * p.sigma * p.sigma,
  skewness: () => 2 * Math.sqrt(Math.PI) * (Math.PI - 3) / Math.pow(4 - Math.PI, 1.5),
  kurtosis: () => -(6 * Math.PI * Math.PI - 24 * Math.PI + 16) / sq(4 - Math.PI),
  entropy: (p) => 1 + Math.log(p.sigma / SQRT2) + EULER / 2,
  mode: (p) => p.sigma,
  median: (p) => p.sigma * Math.sqrt(2 * LN2),
  logMoments: (p) => [Math.log(p.sigma) + (LN2 - EULER) / 2, Math.PI * Math.PI / 24],
  parameterisations: [
    { id: 'scale', label: 'Scale σ', fields: [field('sigma', 'Scale σ (the mode)', 'pos')], to: (v) => ({ sigma: v.sigma }), from: (p) => ({ sigma: p.sigma }) },
    { id: 'mean', label: 'Mean', fields: [field('mean', 'Mean', 'pos')], to: (v) => ({ sigma: v.mean * Math.sqrt(2 / Math.PI) }), from: (p) => ({ mean: p.sigma * Math.sqrt(Math.PI / 2) }) },
  ],
  free: { keys: ['sigma'], to: (p) => [Math.log(p.sigma)], from: (z) => ({ sigma: Math.exp(z[0]) }) },
  fit: {
    k: 1,
    applicable: (s) => (s.nonneg && s.max > 0 ? '' : 'needs values of zero or above'),
    mle: (s) => { let t = 0; for (let i = 0; i < s.n; i++) t += s.x[i] * s.x[i]; return { sigma: Math.sqrt(t / (2 * s.n)) }; },
    mom: (s) => ({ sigma: s.mean * Math.sqrt(2 / Math.PI) }),
  },
  tex: { pdf: R`f(x)=\frac{x}{\sigma^2}e^{-x^2/(2\sigma^2)},\ x\ge0`, cdf: R`F(x)=1-e^{-x^2/(2\sigma^2)}`, mean: R`\sigma\sqrt{\pi/2}`, variance: R`\frac{4-\pi}{2}\sigma^2` },
  scipy: 'rayleigh(scale=σ)',
};

/* erf^-1(u) for small u, by Newton on Cody's erf, which keeps relative precision there. */
function erfinvSmall(u) {
  let x = u * Math.sqrt(Math.PI) / 2;
  for (let i = 0; i < 4; i++) x -= (erf(x) - u) / (2 / Math.sqrt(Math.PI) * Math.exp(-x * x));
  return x;
}

export const halfnormal = {
  id: 'halfnormal', label: 'Half-normal', kind: 'continuous', group: 'Positive',
  blurb: 'The absolute value of a normal centred on zero: a size of deviation regardless of its sign.',
  params: [field('sigma', 'Scale σ', 'pos')],
  defaults: { sigma: 1 },
  support: () => [0, Infinity],
  logpdf: (x, p) => (x >= 0 ? 0.5 * Math.log(2 / Math.PI) - Math.log(p.sigma) - x * x / (2 * p.sigma * p.sigma) : -Infinity),
  cdf: (x, p) => (x <= 0 ? 0 : erf(x / (p.sigma * SQRT2))),
  sf: (x, p) => (x <= 0 ? 1 : erfc(x / (p.sigma * SQRT2))),
  quantile: (u, p) => (u < 0.1 ? p.sigma * SQRT2 * erfinvSmall(u) : p.sigma * normIsf((1 - u) / 2)),
  isf: (q, p) => p.sigma * normIsf(q / 2),
  mean: (p) => p.sigma * Math.sqrt(2 / Math.PI),
  variance: (p) => p.sigma * p.sigma * (1 - 2 / Math.PI),
  skewness: () => SQRT2 * (4 - Math.PI) / Math.pow(Math.PI - 2, 1.5),
  kurtosis: () => 8 * (Math.PI - 3) / sq(Math.PI - 2),
  entropy: (p) => 0.5 * Math.log(Math.PI * Math.E * p.sigma * p.sigma / 2),
  mode: () => 0,
  median: (p) => p.sigma * normIsf(0.25),
  logMoments: (p) => [Math.log(p.sigma) - (EULER + LN2) / 2, Math.PI * Math.PI / 8],
  parameterisations: [
    { id: 'scale', label: 'Scale σ', fields: [field('sigma', 'Scale σ', 'pos')], to: (v) => ({ sigma: v.sigma }), from: (p) => ({ sigma: p.sigma }) },
    { id: 'mean', label: 'Mean', fields: [field('mean', 'Mean', 'pos')], to: (v) => ({ sigma: v.mean * Math.sqrt(Math.PI / 2) }), from: (p) => ({ mean: p.sigma * Math.sqrt(2 / Math.PI) }) },
  ],
  free: { keys: ['sigma'], to: (p) => [Math.log(p.sigma)], from: (z) => ({ sigma: Math.exp(z[0]) }) },
  fit: {
    k: 1,
    applicable: (s) => (s.nonneg && s.max > 0 ? '' : 'needs values of zero or above'),
    mle: (s) => { let t = 0; for (let i = 0; i < s.n; i++) t += s.x[i] * s.x[i]; return { sigma: Math.sqrt(t / s.n) }; },
    mom: (s) => ({ sigma: s.mean * Math.sqrt(Math.PI / 2) }),
  },
  tex: { pdf: R`f(x)=\frac{\sqrt2}{\sigma\sqrt\pi}e^{-x^2/(2\sigma^2)},\ x\ge0`, cdf: R`F(x)=\operatorname{erf}\frac{x}{\sigma\sqrt2}`, mean: R`\sigma\sqrt{2/\pi}`, variance: R`\sigma^2(1-2/\pi)` },
  scipy: 'halfnorm(scale=σ)',
};

/* ======================================================================
   Inverse Gaussian and inverse gamma
   ====================================================================== */

export const invgauss = {
  id: 'invgauss', label: 'Inverse Gaussian', kind: 'continuous', group: 'Positive',
  blurb: 'The first time a drifting Brownian motion reaches a level (Wald): travel times of a tracer by advection and dispersion.',
  params: [field('mu', 'Mean μ', 'pos'), field('lambda', 'Shape λ', 'pos')],
  defaults: { mu: 1, lambda: 3 },
  support: () => [0, Infinity],
  logpdf: (x, p) => (x > 0 ? 0.5 * (Math.log(p.lambda) - LN_2PI - 3 * Math.log(x)) - p.lambda * sq(x - p.mu) / (2 * p.mu * p.mu * x) : -Infinity),
  cdf: (x, p) => {
    if (x <= 0) return 0;
    const r = Math.sqrt(p.lambda / x);
    return normCdf(r * (x / p.mu - 1)) + Math.exp(2 * p.lambda / p.mu + normLogCdf(-r * (x / p.mu + 1)));
  },
  sf: (x, p) => {
    if (x <= 0) return 1;
    const r = Math.sqrt(p.lambda / x);
    const la = normLogSf(r * (x / p.mu - 1));
    const lb = 2 * p.lambda / p.mu + normLogCdf(-r * (x / p.mu + 1));
    return lb < la ? Math.exp(la + log1mexp(lb - la)) : 0;
  },
  mean: (p) => p.mu,
  variance: (p) => p.mu ** 3 / p.lambda,
  skewness: (p) => 3 * Math.sqrt(p.mu / p.lambda),
  kurtosis: (p) => 15 * p.mu / p.lambda,
  mode: (p) => p.mu * (Math.sqrt(1 + 9 * p.mu * p.mu / (4 * p.lambda * p.lambda)) - 3 * p.mu / (2 * p.lambda)),
  parameterisations: [
    { id: 'mean-shape', label: 'Mean μ and shape λ', fields: [field('mu', 'Mean μ', 'pos'), field('lambda', 'Shape λ', 'pos')],
      to: (v) => ({ mu: v.mu, lambda: v.lambda }), from: (p) => ({ mu: p.mu, lambda: p.lambda }) },
    { id: 'mean-sd', label: 'Mean and SD', fields: [field('mean', 'Mean', 'pos'), field('sd', 'Standard deviation', 'pos')],
      to: (v) => ({ mu: v.mean, lambda: v.mean ** 3 / (v.sd * v.sd) }), from: (p) => ({ mean: p.mu, sd: Math.sqrt(p.mu ** 3 / p.lambda) }) },
  ],
  free: { keys: ['mu', 'lambda'], to: (p) => [Math.log(p.mu), Math.log(p.lambda)], from: (z) => ({ mu: Math.exp(z[0]), lambda: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    applicable: (s) => (s.positive ? '' : 'needs every value above zero'),
    mle: (s) => { let t = 0; for (let i = 0; i < s.n; i++) t += 1 / s.x[i] - 1 / s.mean; return t > 0 ? { mu: s.mean, lambda: s.n / t } : null; },
    mom: (s) => ({ mu: s.mean, lambda: s.mean ** 3 / s.var }),
  },
  tex: {
    pdf: R`f(x)=\sqrt{\frac{\lambda}{2\pi x^3}}\exp\!\left(-\frac{\lambda(x-\mu)^2}{2\mu^2x}\right)`,
    cdf: R`F(x)=\Phi\!\left(\sqrt{\tfrac\lambda x}\left(\tfrac x\mu-1\right)\right)+e^{2\lambda/\mu}\Phi\!\left(-\sqrt{\tfrac\lambda x}\left(\tfrac x\mu+1\right)\right)`,
    mean: R`\mu`, variance: R`\mu^3/\lambda`,
  },
  scipy: 'invgauss(mu=μ/λ, scale=λ)',
};

export const invgamma = {
  id: 'invgamma', label: 'Inverse gamma', kind: 'continuous', group: 'Positive',
  blurb: 'The reciprocal of a gamma: a prior for a variance, and a heavy-tailed shape for positive quantities.',
  params: [field('alpha', 'Shape α', 'pos'), field('beta', 'Scale β', 'pos')],
  defaults: { alpha: 3, beta: 2 },
  support: () => [0, Infinity],
  logpdf: (x, p) => (x > 0 ? Math.log(p.alpha / x) + logDpoisRaw(p.alpha, p.beta / x) : -Infinity),
  cdf: (x, p) => (x <= 0 ? 0 : gammaInc(p.alpha, p.beta / x)[1]),
  sf: (x, p) => (x <= 0 ? 1 : gammaInc(p.alpha, p.beta / x)[0]),
  quantile: (u, p) => p.beta / gammaIncInv(p.alpha, 1 - u, u),
  isf: (q, p) => p.beta / gammaIncInv(p.alpha, q, 1 - q),
  mean: (p) => (p.alpha > 1 ? p.beta / (p.alpha - 1) : Infinity),
  variance: (p) => (p.alpha > 2 ? p.beta * p.beta / (sq(p.alpha - 1) * (p.alpha - 2)) : p.alpha > 1 ? Infinity : NaN),
  skewness: (p) => (p.alpha > 3 ? 4 * Math.sqrt(p.alpha - 2) / (p.alpha - 3) : p.alpha > 2 ? Infinity : NaN),
  kurtosis: (p) => (p.alpha > 4 ? (30 * p.alpha - 66) / ((p.alpha - 3) * (p.alpha - 4)) : p.alpha > 2 ? Infinity : NaN),
  entropy: (p) => p.alpha + Math.log(p.beta) + lgamma(p.alpha) - (1 + p.alpha) * digamma(p.alpha),
  mode: (p) => p.beta / (p.alpha + 1),
  logMoments: (p) => [Math.log(p.beta) - digamma(p.alpha), trigamma(p.alpha)],
  tails: (p) => ({ left: Infinity, right: p.alpha }),
  parameterisations: [
    { id: 'shape-scale', label: 'Shape α and scale β', fields: [field('alpha', 'Shape α', 'pos'), field('beta', 'Scale β', 'pos')],
      to: (v) => ({ alpha: v.alpha, beta: v.beta }), from: (p) => ({ alpha: p.alpha, beta: p.beta }) },
    { id: 'mean-sd', label: 'Mean and SD', fields: [field('mean', 'Mean', 'pos'), field('sd', 'Standard deviation', 'pos')],
      to: (v) => { const a = 2 + sq(v.mean / v.sd); return { alpha: a, beta: v.mean * (a - 1) }; },
      from: (p) => ({ mean: p.alpha > 1 ? p.beta / (p.alpha - 1) : NaN, sd: p.alpha > 2 ? p.beta / ((p.alpha - 1) * Math.sqrt(p.alpha - 2)) : NaN }) },
  ],
  free: { keys: ['alpha', 'beta'], to: (p) => [Math.log(p.alpha), Math.log(p.beta)], from: (z) => ({ alpha: Math.exp(z[0]), beta: Math.exp(z[1]) }) },
  fit: {
    k: 2,
    applicable: (s) => (s.positive ? '' : 'needs every value above zero'),
    mle: (s) => {
      const inv = describeSample(Array.from(s.x, (v) => 1 / v));
      const k = gammaShapeFor(Math.log(inv.mean) - inv.meanLog);
      return k > 0 ? { alpha: k, beta: k / inv.mean } : null;
    },
    mom: (s) => { const a = 2 + s.mean * s.mean / s.var; return { alpha: a, beta: s.mean * (a - 1) }; },
  },
  tex: {
    pdf: R`f(x)=\frac{\beta^\alpha}{\Gamma(\alpha)}x^{-\alpha-1}e^{-\beta/x},\ x>0`, cdf: R`F(x)=Q(\alpha,\,\beta/x)`,
    mean: R`\frac{\beta}{\alpha-1},\ \alpha>1`, variance: R`\frac{\beta^2}{(\alpha-1)^2(\alpha-2)},\ \alpha>2`,
  },
  scipy: 'invgamma(a=α, scale=β)',
};

/* ======================================================================
   Trapezoidal
   ====================================================================== */

function trapH(p) { return 2 / (p.d + p.c - p.a - p.b); }

export const trapezoidal = {
  id: 'trapezoidal', label: 'Trapezoidal', kind: 'continuous', group: 'Bounded',
  blurb: 'A rise, a flat top of equally likely values, and a fall: a triangle whose peak is a range.',
  params: [field('a', 'Minimum a', 'real'), field('b', 'Start of the top b', 'real'), field('c', 'End of the top c', 'real'), field('d', 'Maximum d', 'real')],
  defaults: { a: 0, b: 1, c: 2, d: 4 },
  validate: (p) => (p.a <= p.b && p.b <= p.c && p.c <= p.d && p.a < p.d ? '' : 'Need a ≤ b ≤ c ≤ d with a < d.'),
  support: (p) => [p.a, p.d],
  logpdf: (x, p) => {
    const h = trapH(p);
    if (x < p.a || x > p.d) return -Infinity;
    if (x < p.b) return Math.log(h * (x - p.a) / (p.b - p.a));
    if (x <= p.c) return Math.log(h);
    return Math.log(h * (p.d - x) / (p.d - p.c));
  },
  cdf: (x, p) => {
    const h = trapH(p);
    if (x <= p.a) return 0;
    if (x >= p.d) return 1;
    if (x < p.b) return h * sq(x - p.a) / (2 * (p.b - p.a));
    if (x <= p.c) return h * ((p.b - p.a) / 2 + (x - p.b));
    return 1 - h * sq(p.d - x) / (2 * (p.d - p.c));
  },
  sf: (x, p) => {
    const h = trapH(p);
    if (x <= p.a) return 1;
    if (x >= p.d) return 0;
    if (x > p.c) return h * sq(p.d - x) / (2 * (p.d - p.c));
    if (x >= p.b) return h * ((p.d - p.c) / 2 + (p.c - x));
    return 1 - h * sq(x - p.a) / (2 * (p.b - p.a));
  },
  quantile: (u, p) => {
    const h = trapH(p);
    const fb = h * (p.b - p.a) / 2;
    const fc = 1 - h * (p.d - p.c) / 2;
    if (u <= fb) return p.a + Math.sqrt(2 * u * (p.b - p.a) / h);
    if (u <= fc) return p.b + (u - fb) / h;
    return p.d - Math.sqrt(2 * (1 - u) * (p.d - p.c) / h);
  },
  isf: (q, p) => {
    const h = trapH(p);
    const gc = h * (p.d - p.c) / 2;
    const gb = 1 - h * (p.b - p.a) / 2;
    if (q <= gc) return p.d - Math.sqrt(2 * q * (p.d - p.c) / h);
    if (q <= gb) return p.c - (q - gc) / h;
    return p.a + Math.sqrt(2 * (1 - q) * (p.b - p.a) / h);
  },
  mode: (p) => (p.b + p.c) / 2,
  modeText: (p) => (p.c > p.b ? 'any value from b to c' : ''),
  breaks: (p) => { const h = trapH(p); return [h * (p.b - p.a) / 2, 1 - h * (p.d - p.c) / 2]; },
  parameterisations: [
    { id: 'abcd', label: 'The four corners', fields: [field('a', 'Minimum a', 'real'), field('b', 'Start of the top b', 'real'), field('c', 'End of the top c', 'real'), field('d', 'Maximum d', 'real')],
      to: (v) => ({ a: v.a, b: v.b, c: v.c, d: v.d }), from: (p) => ({ a: p.a, b: p.b, c: p.c, d: p.d }) },
  ],
  free: {
    keys: ['a', 'b', 'c', 'd'],
    to: (p) => {
      const w = p.d - p.a;
      const s1 = Math.min(1 - 1e-9, Math.max(1e-9, (p.b - p.a) / w));
      const s2 = Math.min(1 - 1e-9, Math.max(1e-9, (p.c - p.b) / (p.d - p.b || 1e-300)));
      return [p.a, Math.log(w), logit(s1), logit(s2)];
    },
    from: (z) => { const w = Math.exp(z[1]); const b = z[0] + w * logistic(z[2]); const d = z[0] + w; return { a: z[0], b, c: b + (d - b) * logistic(z[3]), d }; },
  },
  fit: {
    k: 4, regular: false,
    mle: (s) => {
      const span = s.max - s.min;
      const nll = (z) => {
        const p = trapezoidal.free.from(z);
        if (!(p.a < s.min && p.d > s.max)) return Infinity;
        let ll = 0;
        for (let i = 0; i < s.n; i++) ll += trapezoidal.logpdf(s.x[i], p);
        return -ll;
      };
      const q = (u) => s.x[Math.min(s.n - 1, Math.floor(u * s.n))];
      let best = null;
      for (const pad of [0.02, 0.2]) {
        const p0 = { a: s.min - pad * span, b: q(0.25), c: q(0.75), d: s.max + pad * span };
        const got = nelderMead(nll, trapezoidal.free.to(p0));
        if (!best || got.f < best.f) best = got;
      }
      return Number.isFinite(best.f) ? trapezoidal.free.from(best.x) : null;
    },
    mom: () => ({ params: null, why: 'four parameters need four moments; not offered' }),
  },
  tex: {
    pdf: R`f(x)=h\cdot\begin{cases}\frac{x-a}{b-a} & a\le x<b\\ 1 & b\le x\le c\\ \frac{d-x}{d-c} & c<x\le d\end{cases},\ h=\frac{2}{d+c-a-b}`,
    cdf: R`\text{piecewise quadratic, linear, quadratic}`,
    mean: R`\text{by numerical integration}`, variance: R`\text{by numerical integration}`,
  },
  scipy: 'trapezoid(c=(b−a)/(d−a), d=(c−a)/(d−a), loc=a, scale=d−a)',
};

export const CONTINUOUS = [
  normal, lognormal, uniform, loguniform, triangular, logtriangular, dtriangular, logdtriangular,
  pert, beta, trapezoidal, gamma, exponential, weibull, chisquare, fdist, pareto, rayleigh, halfnormal,
  invgauss, invgamma, loglogistic, logisticFam, laplace, cauchy, studentt, gumbel, gumbelmin, gev, genpareto,
];
