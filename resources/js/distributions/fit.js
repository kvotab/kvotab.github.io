/* ==========================================================================
   distributions.html: FITTING FAMILIES TO A SAMPLE, AND RANKING THE FITS

   Each family that can be fitted is, by maximum likelihood and/or by the
   method of moments, and every fit is scored on the same sample:

   - the log-likelihood, and from it AIC, AICc and BIC, which reward fit and
     charge for parameters (the k of a fit is the parameters it estimated);
   - Kolmogorov-Smirnov's D (the largest gap between the empirical and the
     fitted CDF), Anderson-Darling's A² (squared gaps weighted towards the
     tails) and Cramér-von Mises' W² (squared gaps, unweighted), for a
     continuous family;
   - for a discrete family, D and Pearson's chi-square over cells with an
     expected count of at least five.

   The p-values of D and A² are those for a distribution fixed before the
   sample was seen. For one fitted to the sample they are too large
   (Lilliefors), so they rank, they do not accept. The chi-square's degrees
   of freedom are reduced by the fitted parameters, which is the right
   correction for it.

   A fit whose support ends at the sample's extremes (the uniforms and the
   Pareto by maximum likelihood) puts those values at probability 0 or 1, where
   A² is infinite; the tests are then taken on the values strictly inside,
   as Kompartment does.

   The method of moments matches the mean and variance of the values (and
   the skewness for three parameters), not of their logarithms.
   ========================================================================== */

import { FAMILIES, familyById } from './families.js';
import { describeSample } from './kit.js';
import { makeDistribution } from './dist.js';
import { gammaInc } from './special.js';
import { hessian, invertMatrix, nelderMead, newtonSystem } from './numeric.js';
import { tally } from './discrete.js';

export const FIT_MIN_SAMPLE = 5;

export const CRITERIA = [
  ['aic', 'AIC', 'low'],
  ['aicc', 'AICc', 'low'],
  ['bic', 'BIC', 'low'],
  ['ks', 'K–S D', 'low'],
  ['ad', 'A²', 'low'],
  ['cvm', 'W²', 'low'],
  ['chi2p', 'χ² p', 'high'],
  ['logL', 'Log-likelihood', 'high'],
];

/* ---- which families --------------------------------------------------------------- */

/** '' or why a family cannot be fitted to this sample. */
export function whyNot(fam, s, opts = {}) {
  if (!fam.fit) return 'is not fitted';
  if (s.n < FIT_MIN_SAMPLE) return `needs at least ${FIT_MIN_SAMPLE} values`;
  if (!s.distinct) return 'needs values that differ';
  const reason = fam.fit.applicable ? fam.fit.applicable(s, opts) : '';
  return reason || '';
}

/** The families of a kind ('continuous' or 'discrete') that can be fitted at all. */
export function fittable(kind) {
  return FAMILIES.filter((f) => f.kind === kind && f.fit && !(f.fit.applicable && /is not fitted/.test(f.fit.applicable({}) || '')));
}

/* ---- one fit --------------------------------------------------------------------------- */

function normalise(out) {
  if (out == null) return { why: 'could not be fitted to this sample' };
  if (typeof out !== 'object') return { why: 'could not be fitted to this sample' };
  if ('params' in out || 'why' in out) {
    if (!out.params) return { why: out.why || 'could not be fitted to this sample' };
    return out;
  }
  return { params: out };
}

/* The method of moments for a family that has no formula for it: the
   parameters whose mean and variance (and skewness, for three) are the
   sample's, by Nelder-Mead on the family's free parameters. */
/* A family's first k moments: its closed forms where it has them (they are
   what makes a search over parameters affordable), its numerical
   statistics where it does not. */
function momentsOf(fam, p, k) {
  const names = ['mean', 'variance', 'skewness'].slice(0, k);
  const out = names.map((n) => (typeof fam[n] === 'function' ? fam[n](p) : undefined));
  if (out.some((v) => v === undefined)) {
    let D;
    try { D = makeDistribution({ family: fam.id, params: p }); } catch (e) { return null; }
    const st = D.stats();
    names.forEach((n, i) => { if (out[i] === undefined) out[i] = st[n]; });
  }
  return out;
}

function genericMom(fam, s) {
  if (!fam.free) return null;
  const k = fam.free.keys.length;
  if (k > 3) return { params: null, why: 'needs more moments than mean, variance and skewness' };
  const targets = [s.mean, s.var, s.skew].slice(0, k);
  const scales = [Math.max(s.sd, 1e-300), Math.max(s.var, 1e-300), 1];
  const p0 = { ...fam.defaults };
  const residual = (z) => {
    let p;
    try { p = fam.free.from(z, p0); } catch (e) { return null; }
    if (fam.validate && fam.validate(p)) return null;
    const got = momentsOf(fam, p, k);
    if (!got) return null;
    const r = [];
    for (let i = 0; i < k; i++) {
      if (!Number.isFinite(got[i])) return null;
      r.push((got[i] - targets[i]) / scales[i]);
    }
    return r;
  };
  /* the mean and variance count a hundred times the skewness, so that a
     sample more skewed than the family can be still gets the member with
     its mean and variance, the nearest in skewness */
  const weights = [100, 100, 1];
  const cost = (z) => { const r = residual(z); return r ? r.reduce((a, b, i) => a + weights[i] * b * b, 0) : Infinity; };
  let best = null;
  for (const start of [fam.free.to(p0), fam.free.to({ ...p0, ...guessFromSample(fam, s) })]) {
    if (!start.every(Number.isFinite)) continue;
    const got = nelderMead(cost, start, { maxIter: 600 * k });
    if (!best || got.f < best.f) best = got;
  }
  if (!best || !Number.isFinite(best.f)) return null;
  const polished = newtonSystem((z) => residual(z) || new Array(k).fill(NaN), best.x);
  const z = Number.isFinite(polished.norm) && cost(polished.x) < best.f ? polished.x : best.x;
  const r = residual(z);
  if (!r) return { params: null, why: 'no member of the family has the sample’s moments' };
  const gap = Math.max(...r.map(Math.abs));
  if (gap < 1e-6) return fam.free.from(z, p0);
  if (k === 3 && Math.abs(r[0]) < 1e-6 && Math.abs(r[1]) < 1e-6) {
    return { params: fam.free.from(z, p0), note: `the sample’s skewness (${+s.skew.toPrecision(3)}) is beyond this family’s reach; this member has its mean and variance and the nearest skewness` };
  }
  return { params: null, why: 'no member of the family has the sample’s moments' };
}

/* A rough start for a search: a member whose scale is the sample's. */
function guessFromSample(fam, s) {
  const out = {};
  for (const def of fam.params) {
    if (/^(mu|x0|a|lo)$/.test(def.key) && def.domain === 'real') out[def.key] = s.mean;
    if (/^(sigma|s|b|beta|gamma|theta|lambda|alpha|xm)$/.test(def.key) && def.domain === 'pos' && fam.defaults[def.key] === 1) out[def.key] = s.sd || 1;
  }
  return out;
}

/* Maximum likelihood for a family without a method of its own: Nelder-Mead
   on the free parameters from the moment fit or the defaults. */
function genericMle(fam, s) {
  if (!fam.free) return null;
  const p0 = { ...fam.defaults };
  const nll = (z) => {
    let p;
    try { p = fam.free.from(z, p0); } catch (e) { return Infinity; }
    let ll = 0;
    for (let i = 0; i < s.n; i++) ll += fam.logpdf(s.x[i], p);
    return Number.isNaN(ll) ? Infinity : -ll;
  };
  const starts = [];
  const mom = normalise(fam.fit && fam.fit.mom ? fam.fit.mom(s) : genericMom(fam, s));
  if (mom.params) starts.push(fam.free.to({ ...p0, ...mom.params }));
  starts.push(fam.free.to(p0));
  let best = null;
  for (const z0 of starts) {
    if (!z0.every(Number.isFinite) || !Number.isFinite(nll(z0))) continue;
    const got = nelderMead(nll, z0);
    if (!best || got.f < best.f) best = got;
  }
  return best && Number.isFinite(best.f) ? fam.free.from(best.x, p0) : null;
}

/**
 * One family fitted to a described sample by one method, and scored.
 *
 * @param {Object} fam
 * @param {Object} s       describeSample(values)
 * @param {'mle'|'mom'} method
 * @param {Object} opts    { trials } for the binomial and beta-binomial
 */
export function fitFamily(fam, s, method, opts = {}) {
  const base = { family: fam.id, label: fam.label, kind: fam.kind, method };
  const reason = whyNot(fam, s, opts);
  if (reason) return { ...base, why: reason };
  let out;
  try {
    if (method === 'mom') out = normalise(fam.fit.mom ? fam.fit.mom(s, opts) : genericMom(fam, s));
    else out = normalise(fam.fit.mle ? fam.fit.mle(s, opts) : genericMle(fam, s));
  } catch (e) {
    return { ...base, why: 'the fit failed: ' + e.message };
  }
  if (out.why) return { ...base, why: out.why };
  const params = { ...fam.defaults, ...out.params };
  let D;
  try { D = makeDistribution({ family: fam.id, params }); } catch (e) { return { ...base, why: 'the fit gave no valid distribution (' + e.message + ')' }; }
  const k = out.k ?? fam.fit.k ?? (fam.free ? fam.free.keys.length : fam.params.length);
  const note = [fam.fit.note, out.note].filter(Boolean).join('; ');
  const score = scoreFit(D, s, k, { edges: !!out.edges });
  const result = { ...base, params, k, note, edges: !!out.edges, ...score };
  /* no standard errors at a bound: a parameter that ran to its limit (a t's
     ν, a negative binomial's r, an F's degrees of freedom) has none */
  if (method === 'mle' && fam.fit.regular !== false && !out.atLimit && Number.isFinite(score.logL)) {
    result.se = standardErrors(fam, s, params, out);
  }
  return result;
}

/* ---- scores ------------------------------------------------------------------------------ */

/** Kolmogorov's limiting distribution with Stephens' correction for n. */
export function ksPValue(d, n) {
  const sq = Math.sqrt(n);
  const lambda = (sq + 0.12 + 0.11 / sq) * d;
  if (lambda < 0.2) return 1;
  const a2 = -2 * lambda * lambda;
  let fac = 2;
  let sum = 0;
  let before = 0;
  for (let j = 1; j <= 100; j++) {
    const term = fac * Math.exp(a2 * j * j);
    sum += term;
    if (Math.abs(term) <= 0.001 * before || Math.abs(term) <= 1e-8 * sum) return Math.min(1, Math.max(0, sum));
    fac = -fac;
    before = Math.abs(term);
  }
  return 1;
}

/** The limiting distribution of A² (Marsaglia and Marsaglia 2004, ADinf). */
export function adPValue(a2) {
  if (!(a2 > 0)) return 1;
  if (!Number.isFinite(a2)) return 0;
  const z = a2;
  const below = z < 2
    ? (Math.exp(-1.2337141 / z) / Math.sqrt(z)) * (2.00012 + (0.247105 - (0.0649821 - (0.0347962 - (0.011672 - 0.00168691 * z) * z) * z) * z) * z)
    : Math.exp(-Math.exp(1.0776 - (2.30695 - (0.43424 - (0.082433 - (0.008056 - 0.0003146 * z) * z) * z) * z) * z));
  return Math.min(1, Math.max(0, 1 - below));
}

/**
 * How well distribution D describes the sample s, with k fitted parameters.
 */
export function scoreFit(D, s, k, { edges = false } = {}) {
  const n = s.n;
  let logL = 0;
  let outside = 0;
  for (let i = 0; i < n; i++) {
    const lp = D.logpdf(s.x[i]);
    if (!(lp > -Infinity)) outside++;
    logL += lp;
  }
  if (Number.isNaN(logL)) logL = -Infinity;
  const out = {
    logL, outside,
    aic: 2 * k - 2 * logL,
    aicc: n - k - 1 > 0 ? 2 * k - 2 * logL + 2 * k * (k + 1) / (n - k - 1) : Infinity,
    bic: k * Math.log(n) - 2 * logL,
  };
  if (D.kind === 'discrete') return { ...out, ...discreteTests(D, s, k) };
  /* the tests, on the values strictly inside the support when the fit's ends are the sample's */
  const F = [];
  const lF = [];
  const lS = [];
  for (let i = 0; i < n; i++) {
    const x = s.x[i];
    const f = D.cdf(x);
    if (edges && (f <= 0 || f >= 1)) continue;
    F.push(f);
    lF.push(D.logcdf(x));
    lS.push(D.logsf(x));
  }
  const m = F.length;
  let d = 0;
  let a2 = 0;
  let w2 = m ? 1 / (12 * m) : NaN;
  for (let i = 0; i < m; i++) {
    d = Math.max(d, (i + 1) / m - F[i], F[i] - i / m);
    a2 += (2 * i + 1) * (lF[i] + lS[m - 1 - i]);
    w2 += (F[i] - (2 * i + 1) / (2 * m)) ** 2;
  }
  a2 = m ? -m - a2 / m : NaN;
  if (Number.isNaN(a2) || a2 === -Infinity) a2 = Infinity;
  return { ...out, tested: m, ks: d, ksP: m ? ksPValue(d, m) : NaN, ad: a2, adP: adPValue(a2), cvm: w2, chi2: NaN, chi2df: NaN, chi2p: NaN };
}

/* D against a step CDF, and Pearson's chi-square over cells of expected count >= 5. */
function discreteTests(D, s, k) {
  const n = s.n;
  const [values, counts] = tally(s.x);
  let d = 0;
  let cum = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    const F = D.cdf(v);
    const below = F - D.pdf(v);   // P(X < v)
    d = Math.max(d, Math.abs(cum / n - below));
    cum += counts[i];
    d = Math.max(d, Math.abs(cum / n - F));
  }
  /* Cells cut at the fitted distribution's own quantiles, each value whole,
     merged until every expected count is at least five: as many cells as
     the data allow, however wide the support. */
  let chi2 = NaN;
  let df = NaN;
  let p = NaN;
  if (D.integer) {
    const K = Math.max(2, Math.min(60, Math.floor(n / 5)));
    const cuts = [];
    for (let j = 1; j < K; j++) {
      const c = D.quantile(j / K);
      if (Number.isFinite(c) && (!cuts.length || c > cuts[cuts.length - 1])) cuts.push(c);
    }
    /* cells (-inf, c1], (c1, c2], ..., (c_last, inf) */
    const edges = [...cuts, Infinity];
    const cells = [];
    let prevF = 0;
    let j = 0;
    let O = 0;
    let E = 0;
    for (let i = 0; i < edges.length; i++) {
      const F = edges[i] === Infinity ? 1 : D.cdf(edges[i]);
      E += n * (F - prevF);
      prevF = F;
      while (j < values.length && values[j] <= edges[i]) { O += counts[j]; j++; }
      if (E >= 5 || i === edges.length - 1) { cells.push([O, E]); O = 0; E = 0; }
    }
    while (cells.length > 1 && cells[cells.length - 1][1] < 5) {
      const last = cells.pop();
      cells[cells.length - 1][0] += last[0];
      cells[cells.length - 1][1] += last[1];
    }
    chi2 = 0;
    for (const [o, e] of cells) chi2 += e > 0 ? (o - e) ** 2 / e : (o > 0 ? Infinity : 0);
    df = cells.length - 1 - k;
    /* too few cells for the parameters fitted: no test */
    if (df > 0) p = gammaInc(df / 2, chi2 / 2)[1];
    else { chi2 = NaN; df = NaN; }
  }
  return { tested: n, ks: d, ksP: NaN, ad: NaN, adP: NaN, cvm: NaN, chi2, chi2df: df, chi2p: p };
}

/* Standard errors from the observed information, -d² logL / dθ², over the
   parameters the fit estimated. */
function standardErrors(fam, s, params, out) {
  const keys = fam.fit.keys || (fam.free ? fam.free.keys : []);
  const kFit = out.k ?? fam.fit.k ?? keys.length;
  if (!keys.length || kFit !== keys.length) return null;
  const theta = keys.map((key) => params[key]);
  const nll = (t) => {
    const p = { ...params };
    keys.forEach((key, i) => { p[key] = t[i]; });
    let ll = 0;
    for (let i = 0; i < s.n; i++) ll += fam.logpdf(s.x[i], p);
    return Number.isFinite(ll) ? -ll : NaN;
  };
  /* Each step sized to the parameter's own uncertainty, not to its size: a
     location of a million with a scale of one moves the likelihood over a
     range of about one, which a step of 1e-4 times a million would jump
     straight over. A curvature measured with the current step gives the
     uncertainty, the next step is a twentieth of it; each round moves the
     step by at most a factor of a thousand (a first step far too large
     measures a curvature far too large), never below what the parameter's
     rounding allows, never above a quarter of its value. */
  const f0 = nll(theta);
  if (!Number.isFinite(f0)) return null;
  const steps = theta.map((v) => 1e-4 * Math.max(Math.abs(v), 1e-2));
  for (let round = 0; round < 5; round++) {
    for (let i = 0; i < theta.length; i++) {
      const h = steps[i];
      const up = theta.slice(); up[i] += h;
      const dn = theta.slice(); dn[i] -= h;
      const c = (nll(up) - 2 * f0 + nll(dn)) / (h * h);
      if (!(c > 0 && Number.isFinite(c))) continue;
      let next = Math.min(Math.max(0.05 / Math.sqrt(c), h / 1000), h * 1000);
      next = Math.max(next, 1e-9 * Math.abs(theta[i]));
      if (theta[i] !== 0) next = Math.min(next, 0.25 * Math.abs(theta[i]));
      steps[i] = next;
    }
  }
  const H = hessian(nll, theta, steps);
  if (H.some((row) => row.some((v) => !Number.isFinite(v)))) return null;
  const C = invertMatrix(H);
  if (!C) return null;
  const se = {};
  for (let i = 0; i < keys.length; i++) {
    if (!(C[i][i] > 0)) return null;
    se[keys[i]] = Math.sqrt(C[i][i]);
  }
  return se;
}

/* ---- all of them --------------------------------------------------------------------------- */

/**
 * Every requested family fitted by every requested method.
 *
 * @param {number[]} values
 * @param {Object} opts { kind: 'continuous'|'discrete', methods: ['mle', 'mom'], families: ids|null, trials }
 * @param {function(number, number, string)} [progress]
 * @returns {{sample: Object, results: Object[]}}
 */
export function fitAll(values, opts = {}, progress = null) {
  const s = describeSample(values);
  const kind = opts.kind || (s.allInteger && s.nonneg ? 'discrete' : 'continuous');
  const methods = opts.methods && opts.methods.length ? opts.methods : ['mle'];
  const fams = (opts.families ? opts.families.map(familyById).filter(Boolean) : FAMILIES).filter((f) => f.kind === kind && f.fit);
  const results = [];
  const total = fams.length * methods.length;
  let done = 0;
  for (const fam of fams) {
    for (const method of methods) {
      if (progress) progress(done, total, fam.label);
      results.push(fitFamily(fam, s, method, opts));
      done++;
    }
  }
  if (progress) progress(total, total, '');
  return { sample: s, kind, results };
}

/**
 * The fits in order of a criterion, best first, with rank, the difference
 * from the best and, for an information criterion, the Akaike weight within
 * each method. Fits that failed come last, in their own order.
 */
export function rankFits(results, criterion = 'aic') {
  const def = CRITERIA.find((c) => c[0] === criterion) || CRITERIA[0];
  const sign = def[2] === 'high' ? -1 : 1;
  const value = (r) => {
    const v = r[def[0]];
    return Number.isFinite(v) ? sign * v : (Number.isNaN(v) ? Infinity : (sign * v === -Infinity ? -Infinity : Infinity));
  };
  const ok = results.filter((r) => !r.why);
  const bad = results.filter((r) => r.why);
  ok.sort((a, b) => {
    const d = value(a) - value(b);
    return Number.isNaN(d) ? 0 : d;
  });
  const best = ok.length ? value(ok[0]) : NaN;
  const info = ['aic', 'aicc', 'bic'].includes(def[0]);
  const weights = {};
  if (info) {
    for (const method of ['mle', 'mom']) {
      const group = ok.filter((r) => r.method === method && Number.isFinite(r[def[0]]));
      if (!group.length) continue;
      const lo = Math.min(...group.map((r) => r[def[0]]));
      const tot = group.reduce((a, r) => a + Math.exp(-(r[def[0]] - lo) / 2), 0);
      for (const r of group) weights[r.family + '|' + r.method] = Math.exp(-(r[def[0]] - lo) / 2) / tot;
    }
  }
  return [
    ...ok.map((r, i) => ({
      ...r, rank: i + 1,
      delta: Number.isFinite(value(r)) && Number.isFinite(best) ? sign * (value(r) - best) : NaN,
      weight: info ? (weights[r.family + '|' + r.method] ?? 0) : NaN,
    })),
    ...bad.map((r) => ({ ...r, rank: NaN, delta: NaN, weight: NaN })),
  ];
}
