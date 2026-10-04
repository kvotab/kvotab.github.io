/* ==========================================================================
   distributions.html: ONE DISTRIBUTION, EVALUATED

   makeDistribution(spec) turns what the page stores about a distribution
   into an object with every function and statistic the page shows:

     spec = { family, params }                     a family with its canonical parameters
          | { family: 'empirical', method, data, bw, log, bins }
          | { family: 'table', mode: 'cdf' | 'pmf', rows: [[x, v], ...] }
     plus, for any of them, shift: s (X + s; a whole number for a
     distribution on whole numbers), and trunc: { lo, hi } (either null),
     values, or { by: 'p', lo, hi }, probabilities whose values are the
     bounds. The shift comes first, so the bounds are shifted values.

   What a family leaves out is worked out here: a quantile by root finding,
   moments, entropy and log-moments by tanh-sinh integration over the
   quantile function (or by summation over the probabilities of a discrete
   one), a mode by search. A truncated distribution always goes that way,
   with the moments that exist decided from the family's tails and the
   bounds.
   ========================================================================== */

import { familyById } from './families.js';
import { DOMAINS } from './kit.js';
import { rootIncreasing, brentRoot, integrate01Vec } from './numeric.js';
import { interpolated, histogram, kde, ecdf, pointMasses, piecewiseLinear, bandwidth } from './empirical.js';

/* ---- checking a spec ------------------------------------------------------------ */

/** '' or why the canonical parameters are not a distribution of the family. */
export function checkParams(fam, p) {
  for (const def of fam.params) {
    const v = p[def.key];
    if (!Number.isFinite(v)) return `${def.label} is missing.`;
    const why = (DOMAINS[def.domain] || DOMAINS.real).check(v);
    if (why) return `${def.label} ${why}.`;
  }
  return fam.validate ? fam.validate(p) : '';
}

/* ---- the base object ------------------------------------------------------------- */

function fromFamily(fam, p) {
  const why = checkParams(fam, p);
  if (why) throw new Error(why);
  const has = (name) => typeof fam[name] === 'function';
  const base = {
    kind: fam.kind,
    integer: fam.kind === 'discrete',
    family: fam,
    params: p,
    support: fam.support(p),
    logpdf: (x) => fam.logpdf(x, p),
    cdf: (x) => fam.cdf(x, p),
    sf: has('sf') ? (x) => fam.sf(x, p) : (x) => 1 - fam.cdf(x, p),
    tails: has('tails') ? fam.tails(p) : { left: Infinity, right: Infinity },
    closed: {},
  };
  if (has('logcdf')) base.logcdf = (x) => fam.logcdf(x, p);
  if (has('logsf')) base.logsf = (x) => fam.logsf(x, p);
  if (has('quantile')) base.quantile = (u) => fam.quantile(u, p);
  if (has('isf')) base.isf = (q) => fam.isf(q, p);
  for (const name of ['mean', 'variance', 'skewness', 'kurtosis', 'entropy', 'mode', 'median']) {
    if (has(name)) base.closed[name] = () => fam[name](p);
  }
  if (has('logMoments')) base.closed.logMoments = () => fam.logMoments(p);
  if (has('breaks')) base.breaks = fam.breaks(p);
  if (has('modeText')) base.modeText = fam.modeText(p) || '';
  return base;
}

function fromEmpirical(spec) {
  const data = Float64Array.from((spec.data || []).filter(Number.isFinite)).sort();
  if (data.length < 2) throw new Error('Needs at least two values.');
  if (!(data[data.length - 1] > data[0])) throw new Error('Every value is the same.');
  let e;
  if (spec.method === 'ecdf') e = ecdf(data);
  else if (spec.method === 'histogram') e = histogram(data, spec.bins ?? 'sturges');
  else if (spec.method === 'kde') {
    const logs = spec.log ? Float64Array.from(data, Math.log) : data;
    if (spec.log && !(data[0] > 0)) throw new Error('A kernel density in ln x needs every value above zero.');
    const h = Number.isFinite(spec.bw) && spec.bw > 0 ? spec.bw : bandwidth(logs, spec.bw === 'scott' ? 'scott' : 'silverman');
    e = kde(data, h, !!spec.log);
  } else e = interpolated(data);
  return wrapPrepared(e);
}

function fromTable(spec) {
  const rows = (spec.rows || []).filter((r) => Number.isFinite(r[0]) && Number.isFinite(r[1]));
  if (spec.mode === 'pmf') {
    if (!rows.length) throw new Error('The table has no rows.');
    const merged = new Map();
    for (const [x, p] of rows) {
      if (p < 0) throw new Error('A probability cannot be negative.');
      merged.set(x, (merged.get(x) || 0) + p);
    }
    const xs = [...merged.keys()].sort((a, b) => a - b);
    const ps = xs.map((x) => merged.get(x));
    const total = ps.reduce((a, b) => a + b, 0);
    if (!(total > 0)) throw new Error('The probabilities add up to zero.');
    const e = pointMasses(xs, ps);
    const out = wrapPrepared(e);
    out.note = Math.abs(total - 1) > 1e-9 ? `The probabilities add up to ${+total.toPrecision(6)}; they are scaled to 1.` : '';
    return out;
  }
  if (rows.length < 2) throw new Error('A cumulative table needs at least two rows.');
  const sorted = rows.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i][1] < sorted[i - 1][1]) throw new Error('F(x) must not decrease as x grows.');
  }
  if (Math.abs(sorted[0][1]) > 1e-12) throw new Error('The first F(x) must be 0.');
  if (Math.abs(sorted[sorted.length - 1][1] - 1) > 1e-12) throw new Error('The last F(x) must be 1.');
  return wrapPrepared(piecewiseLinear(sorted.map((r) => r[0]), sorted.map((r) => r[1])));
}

/* An empirical or table object, whose statistics are already worked out. */
function wrapPrepared(e) {
  const base = {
    kind: e.kind,
    integer: false,
    points: !!e.points,
    support: e.support,
    logpdf: e.logpdf || ((x) => Math.log(e.pdf(x))),
    cdf: e.cdf,
    sf: e.sf,
    quantile: e.quantile,
    isf: e.isf,
    tails: { left: Infinity, right: Infinity },
    closed: {
      mean: () => e.moments.mean,
      variance: () => e.moments.variance,
      skewness: () => e.moments.skewness,
      kurtosis: () => e.moments.kurtosis,
      entropy: () => e.entropy,
      mode: () => e.mode,
    },
    prepared: e,
  };
  if (e.logMoments) base.closed.logMoments = () => e.logMoments;
  if (e.cdfLeft) base.cdfLeft = e.cdfLeft;
  if (e.fastAt) base.fastAt = e.fastAt;
  if (e.atoms && typeof e.atoms === 'function') base.atomsExact = e.atoms;
  if (e.atoms === true) base.note = 'Tied values make steps (masses) in this distribution; the density leaves them out.';
  return base;
}

/* ---- shift ---------------------------------------------------------------------------- */

/**
 * X + s: every value moved by s. The spread, the shape and the entropy are
 * as they were; the location statistics move by s; the log-moments change
 * in no simple way and are worked out again, numerically.
 */
function shiftBy(base, s) {
  const Q = quantileOf(base);
  const I = isfOf(base);
  const c = base.closed || {};
  const closed = {};
  for (const name of ['mean', 'median', 'mode']) if (c[name]) closed[name] = () => c[name]() + s;
  for (const name of ['variance', 'skewness', 'kurtosis', 'entropy']) if (c[name]) closed[name] = c[name];
  const out = {
    ...base,
    support: [base.support[0] + s, base.support[1] + s],
    logpdf: (x) => base.logpdf(x - s),
    cdf: (x) => base.cdf(x - s),
    sf: (x) => base.sf(x - s),
    quantile: (u) => Q(u) + s,
    isf: (q) => I(q) + s,
    closed,
    shift: s,
  };
  delete out.logcdf;
  delete out.logsf;
  if (base.logcdf) out.logcdf = (x) => base.logcdf(x - s);
  if (base.logsf) out.logsf = (x) => base.logsf(x - s);
  if (base.cdfLeft) out.cdfLeft = (x) => base.cdfLeft(x - s);
  if (base.fastAt) out.fastAt = (u) => base.fastAt(u) + s;
  if (base.atomsExact) out.atomsExact = () => { const [xs, ps] = base.atomsExact(); return [xs.map((x) => x + s), ps]; };
  return out;
}

/* ---- truncation ---------------------------------------------------------------------- */

/**
 * X conditioned on lo <= X <= hi. Each of F and 1 - F is used where it is
 * small, so that a truncation deep in a tail keeps its precision: a lower
 * bound above the median works with the survival function throughout.
 */
function truncate(base, lo, hi) {
  const [s0, s1] = base.support;
  const discrete = base.kind === 'discrete';
  let L = Number.isFinite(lo) ? lo : -Infinity;
  let H = Number.isFinite(hi) ? hi : Infinity;
  if (discrete && base.integer) {
    if (Number.isFinite(L)) L = Math.ceil(L);
    if (Number.isFinite(H)) H = Math.floor(H);
  }
  if (!(H >= L)) throw new Error(discrete ? 'No value lies between the bounds.' : 'The upper bound of the truncation must be above the lower one.');
  /* P(X < L) and P(X >= L), P(X <= H) and P(X > H). A continuous
     distribution with a mass at L (tied data, a jump in a cumulative table)
     keeps that mass: its cdf from the left is used. */
  let FL; let SL;
  if (!Number.isFinite(L) || L <= s0) { FL = 0; SL = 1; } else if (discrete) {
    const below = base.integer ? L - 1 : prevAtom(base, L);
    FL = below === null ? 0 : base.cdf(below);
    SL = below === null ? 1 : base.sf(below);
  } else if (base.cdfLeft) { FL = base.cdfLeft(L); SL = 1 - FL; } else { FL = base.cdf(L); SL = base.sf(L); }
  let FU; let SU;
  if (!Number.isFinite(H) || H >= s1) { FU = 1; SU = 0; } else { FU = base.cdf(H); SU = base.sf(H); }
  let Z;
  if (FL <= 0.5 && SU <= 0.5) Z = 1 - FL - SU;
  else if (FL > 0.5) Z = SL - SU;
  else Z = FU - FL;
  if (!(Z > 1e-300)) throw new Error('The truncation leaves no probability: the bounds lie where the distribution has none.');
  const lnZ = Math.log(Z);
  const support = [Math.max(s0, L), Math.min(s1, H)];
  const inside = (x) => x >= support[0] && x <= support[1];
  const t = {
    ...base,
    fastAt: null,
    truncated: { lo: L, hi: H, mass: Z },
    support,
    logpdf: (x) => (inside(x) ? base.logpdf(x) - lnZ : -Infinity),
    cdf: (x) => {
      if (x < support[0]) return 0;
      if (x >= support[1]) return 1;
      return Math.min(1, Math.max(0, FL <= 0.5 ? (base.cdf(x) - FL) / Z : (SL - base.sf(x)) / Z));
    },
    sf: (x) => {
      if (x < support[0]) return 1;
      if (x >= support[1]) return 0;
      return Math.min(1, Math.max(0, SU <= 0.5 ? (base.sf(x) - SU) / Z : (FU - base.cdf(x)) / Z));
    },
    closed: {},
    tails: base.tails,
  };
  const Q = quantileOf(base);
  const I = isfOf(base);
  t.quantile = (u) => {
    const pLow = FL + u * Z;
    const x = pLow <= 0.5 ? Q(pLow) : I(SU + (1 - u) * Z);
    return Math.min(support[1], Math.max(support[0], x));
  };
  t.isf = (q) => {
    const pHigh = SU + q * Z;
    const x = pHigh <= 0.5 ? I(pHigh) : Q(FL + (1 - q) * Z);
    return Math.min(support[1], Math.max(support[0], x));
  };
  if (base.breaks) t.breaks = base.breaks.map((u) => (FL <= 0.5 ? (u - FL) / Z : (SL - (1 - u)) / Z)).filter((u) => u > 0 && u < 1);
  if (base.atomsExact) {
    t.atomsExact = () => {
      const [xs, ps] = base.atomsExact();
      const keep = xs.map((x, i) => [x, ps[i]]).filter(([x]) => inside(x));
      return [keep.map((r) => r[0]), keep.map((r) => r[1] / Z)];
    };
  }
  /* the mode is searched for again: a bimodal or U-shaped density, or a
     table, does not have its truncated mode at the bound nearest its own */
  return t;
}

/* The atom just below x of a finite discrete distribution, or null. */
function prevAtom(base, x) {
  if (!base.atomsExact) return x;
  const [xs] = base.atomsExact();
  let best = null;
  for (const v of xs) if (v < x) best = v;
  return best;
}

/* ---- inverses ------------------------------------------------------------------------------- */

function guessCentre(base) {
  const c = base.closed;
  const m = c.mean ? c.mean() : NaN;
  const v = c.variance ? c.variance() : NaN;
  const [lo, hi] = base.support;
  let x0 = Number.isFinite(m) ? m : (Number.isFinite(lo) && Number.isFinite(hi) ? (lo + hi) / 2 : Number.isFinite(lo) ? lo + 1 : Number.isFinite(hi) ? hi - 1 : 0);
  const sd = Number.isFinite(v) && v > 0 ? Math.sqrt(v) : (Number.isFinite(lo) && Number.isFinite(hi) ? (hi - lo) / 4 : Math.max(1, Math.abs(x0)));
  if (x0 <= lo) x0 = lo + Math.min(sd, 1e-3 * Math.max(1, Math.abs(lo)));
  if (x0 >= hi) x0 = hi - Math.min(sd, 1e-3 * Math.max(1, Math.abs(hi)));
  return [x0, sd];
}

/* The quantile function, by root finding on the CDF when there is no closed form. */
function quantileOf(base) {
  if (base.quantile) return base.quantile;
  const [x0, sd] = guessCentre(base);
  const [lo, hi] = base.support;
  return (u) => {
    if (u <= 0) return lo;
    if (u >= 1) return hi;
    return rootIncreasing((x) => base.cdf(x) - u, x0, lo, hi, sd);
  };
}

function isfOf(base) {
  if (base.isf) return base.isf;
  if (base.quantile && !base.sf) return (q) => base.quantile(1 - q);
  const [x0, sd] = guessCentre(base);
  const [lo, hi] = base.support;
  return (q) => {
    if (q <= 0) return hi;
    if (q >= 1) return lo;
    return rootIncreasing((x) => q - base.sf(x), x0, lo, hi, sd);
  };
}

/* ---- the distribution ----------------------------------------------------------------------- */

/**
 * @param {Object} spec
 * @returns {Object} the evaluated distribution (see the file header)
 */
export function makeDistribution(spec) {
  let base;
  if (spec.family === 'empirical') base = fromEmpirical(spec);
  else if (spec.family === 'table') base = fromTable(spec);
  else {
    const fam = familyById(spec.family);
    if (!fam) throw new Error('Unknown distribution family.');
    base = fromFamily(fam, spec.params || {});
  }
  const shift = Number(spec.shift);
  if (Number.isFinite(shift) && shift !== 0) {
    if (base.kind === 'discrete' && base.integer && !Number.isInteger(shift)) throw new Error('A distribution on whole numbers can only be shifted by a whole number.');
    base = shiftBy(base, shift);
  }
  const tr = spec.trunc || {};
  let lo = tr.lo;
  let hi = tr.hi;
  let atP = null;
  if (tr.by === 'p') {
    /* bounds given as probabilities: the values at them before truncation,
       each kept (for a discrete distribution, the smallest value whose
       cumulative probability reaches the bound's); 0 and 1 are no bound */
    const pl = Number.isFinite(lo) && lo > 0 ? lo : null;
    const ph = Number.isFinite(hi) && hi < 1 ? hi : null;
    if ((pl !== null && !(pl < 1)) || (ph !== null && !(ph > 0))) throw new Error('A percentile of the truncation must be between 0 and 100.');
    if (pl !== null && ph !== null && !(pl < ph)) throw new Error('The lower percentile of the truncation must be below the upper one.');
    const Q = quantileOf(base);
    const I = isfOf(base);
    const valueAt = (p) => (p <= 0.5 ? Q(p) : I(1 - p));
    lo = pl === null ? null : valueAt(pl);
    hi = ph === null ? null : valueAt(ph);
    atP = { lo: pl, hi: ph };
  }
  if (Number.isFinite(lo) || Number.isFinite(hi)) base = truncate(base, lo, hi);
  if (atP && base.truncated) base.truncated = { ...base.truncated, plo: atP.lo, phi: atP.hi };

  const quantile = quantileOf(base);
  const isf = isfOf(base);
  const D = {
    kind: base.kind,
    integer: !!base.integer,
    points: !!base.points,
    family: base.family || null,
    params: base.params || null,
    support: base.support,
    tails: base.tails || { left: Infinity, right: Infinity },
    shift: base.shift || 0,
    truncated: base.truncated || null,
    note: base.note || '',
    prepared: base.prepared || null,
    logpdf: base.logpdf,
    pdf: (x) => Math.exp(base.logpdf(x)),
    cdf: base.cdf,
    sf: base.sf,
    logcdf: base.logcdf && !base.truncated ? base.logcdf : (x) => Math.log(base.cdf(x)),
    logsf: base.logsf && !base.truncated ? base.logsf : (x) => Math.log(base.sf(x)),
    quantile: (u) => (u <= 0.5 ? quantile(u) : isf(1 - u)),
    isf: (q) => (q <= 0.5 ? isf(q) : quantile(1 - q)),
    /* the value at a probability given with its complement */
    at: (u, uc) => (u <= 0.5 ? quantile(u) : isf(uc)),
    fastAt: base.fastAt || null,
  };
  D.hazard = (x) => {
    if (D.kind === 'discrete') {
      const p = D.pdf(x);
      const s = D.sf(x) + p;
      return s > 0 ? p / s : NaN;
    }
    const s = D.sf(x);
    return s > 0 ? D.pdf(x) / s : NaN;
  };
  D.atoms = (eps = 1e-15) => atomsOf(D, base, eps);
  let cache = null;
  D.stats = () => (cache || (cache = statistics(D, base)));
  D.sample = (n, rng, lhs = false) => sampleOf(D, n, rng, lhs);
  return D;
}

/* ---- atoms of a discrete distribution ------------------------------------------------------- */

const MAX_ATOMS = 2e6;

function atomsOf(D, base, eps) {
  if (base.atomsExact) return base.atomsExact();
  if (D.kind !== 'discrete') return null;
  let a = Number.isFinite(D.support[0]) ? D.support[0] : D.quantile(eps / 2);
  let b = Number.isFinite(D.support[1]) ? D.support[1] : D.isf(eps / 2);
  if (!Number.isFinite(a)) a = D.quantile(eps / 2);
  if (!Number.isFinite(b)) b = D.isf(eps / 2);
  if (b - a > MAX_ATOMS) {
    a = D.quantile(eps / 2);
    b = D.isf(eps / 2);
    if (b - a > MAX_ATOMS) return null;
  }
  if (!Number.isSafeInteger(a) || !Number.isSafeInteger(b) || b - a > MAX_ATOMS) return null;
  const xs = [];
  const ps = [];
  for (let k = a; k <= b; k++) {
    const p = D.pdf(k);
    if (p > 0) { xs.push(k); ps.push(p); }
  }
  return [xs, ps];
}

/* ---- statistics ------------------------------------------------------------------------------- */

const exists = (support, tails, k) => (Number.isFinite(support[0]) || k < tails.left) && (Number.isFinite(support[1]) || k < tails.right);

/* What a moment that does not exist is: infinite on one heavy side, undefined on two. */
function missingMoment(support, tails, k, odd) {
  const leftHeavy = !(Number.isFinite(support[0]) || k < tails.left);
  const rightHeavy = !(Number.isFinite(support[1]) || k < tails.right);
  if (leftHeavy && rightHeavy) return NaN;
  if (!odd) return Infinity;
  return rightHeavy ? Infinity : -Infinity;
}

function closedValue(base, name) {
  if (base.truncated) return undefined;
  const f = base.closed[name];
  if (!f) return undefined;
  const v = f();
  return v === undefined ? undefined : v;
}

function statistics(D, base) {
  const s = {};
  const { support, tails } = { support: D.support, tails: base.tails || { left: Infinity, right: Infinity } };
  /* median, quartiles, the percentiles shown */
  s.median = closedValue(base, 'median');
  if (s.median === undefined) s.median = D.quantile(0.5);
  s.q1 = D.quantile(0.25);
  s.q3 = D.quantile(0.75);
  s.iqr = s.q3 - s.q1;

  /* moments: closed where the family has them, else numeric */
  const want = {
    mean: closedValue(base, 'mean'), variance: closedValue(base, 'variance'),
    skewness: closedValue(base, 'skewness'), kurtosis: closedValue(base, 'kurtosis'),
    entropy: closedValue(base, 'entropy'),
  };
  const lm = closedValue(base, 'logMoments');
  const positive = support[0] >= 0;
  const needNumeric = Object.values(want).some((v) => v === undefined) || (positive && lm === undefined);
  let num = null;
  if (needNumeric) num = D.kind === 'discrete' ? discreteNumeric(D, support, tails) : continuousNumeric(D, support, tails, s.median, base.breaks);
  const pick = (name) => (want[name] !== undefined ? want[name] : num ? num[name] : NaN);
  s.mean = pick('mean');
  s.variance = pick('variance');
  s.skewness = pick('skewness');
  s.kurtosis = pick('kurtosis');
  s.entropy = pick('entropy');
  /* a distribution on one point has no shape */
  if (s.variance === 0) { s.skewness = NaN; s.kurtosis = NaN; }
  s.sd = Number.isFinite(s.variance) ? Math.sqrt(s.variance) : s.variance;
  s.cv = Number.isFinite(s.sd) && Number.isFinite(s.mean) && s.mean !== 0 ? s.sd / Math.abs(s.mean) : (s.sd === Infinity && Number.isFinite(s.mean) ? Infinity : NaN);
  if (positive) {
    const [el, vl] = lm !== undefined ? lm : num ? [num.meanLog, num.varLog] : [NaN, NaN];
    s.gm = Number.isFinite(el) ? Math.exp(el) : (el === -Infinity ? 0 : NaN);
    s.gsd = Number.isFinite(vl) && vl >= 0 && Number.isFinite(el) ? Math.exp(Math.sqrt(vl)) : NaN;
  } else {
    s.gm = NaN;
    s.gsd = NaN;
  }
  /* mode */
  const m = closedValue(base, 'mode');
  s.mode = m !== undefined ? m : numericMode(D);
  s.modeText = base.truncated ? '' : (base.modeText || '');
  s.mad = medianAbsoluteDeviation(D, s.median);
  return s;
}

/* Moments, entropy and log-moments by one tanh-sinh pass over the quantile
   function, with the powers taken about the median to keep the central
   moments clear of cancellation. */
function continuousNumeric(D, support, tails, median, breaks) {
  const c = Number.isFinite(median) ? median : 0;
  const positive = support[0] >= 0;
  const orders = [1, 2, 3, 4].map((k) => exists(support, tails, k));
  const f = (u, uc) => {
    const x = D.at(u, uc);
    const d = x - c;
    const out = [d, d * d, d * d * d, d * d * d * d, -D.logpdf(x), NaN, NaN];
    for (let k = 0; k < 4; k++) if (!orders[k]) out[k] = 0;
    if (positive) { const l = Math.log(x); out[5] = l; out[6] = l * l; }
    return out;
  };
  const r = integrate01Vec(f, 7, { scale: [0, 0, 0, 0, 1, 1, 1], breaks });
  const out = {};
  if (orders[0]) out.mean = c + r[0]; else out.mean = missingMoment(support, tails, 1, true);
  if (orders[0] && orders[1]) {
    const mu = r[0];
    out.variance = r[1] - mu * mu;
    if (orders[2]) out.skewness = (r[2] - 3 * mu * r[1] + 2 * mu ** 3) / Math.pow(out.variance, 1.5);
    else out.skewness = missingMoment(support, tails, 3, true);
    if (orders[3]) out.kurtosis = (r[3] - 4 * mu * r[2] + 6 * mu * mu * r[1] - 3 * mu ** 4) / (out.variance * out.variance) - 3;
    else out.kurtosis = Infinity;
  } else {
    /* an infinite mean leaves the variance undefined; a finite one with an
       infinite second moment makes it infinite */
    out.variance = orders[0] ? Infinity : NaN;
    out.skewness = NaN;
    out.kurtosis = NaN;
  }
  out.entropy = r[4];
  if (positive) {
    out.meanLog = r[5];
    out.varLog = r[6] - r[5] * r[5];
  }
  return out;
}

function discreteNumeric(D) {
  const at = D.atoms();
  if (!at) return { mean: NaN, variance: NaN, skewness: NaN, kurtosis: NaN, entropy: NaN, meanLog: NaN, varLog: NaN };
  const [xs, ps] = at;
  let tot = 0;
  let mean = 0;
  for (let i = 0; i < xs.length; i++) { tot += ps[i]; mean += xs[i] * ps[i]; }
  mean /= tot;
  let m2 = 0; let m3 = 0; let m4 = 0; let H = 0; let el = 0; let el2 = 0; let zero = false;
  for (let i = 0; i < xs.length; i++) {
    const p = ps[i] / tot;
    const d = xs[i] - mean;
    m2 += p * d * d; m3 += p * d * d * d; m4 += p * d * d * d * d;
    if (p > 0) H -= p * Math.log(p);
    if (xs[i] > 0) { const l = Math.log(xs[i]); el += p * l; el2 += p * l * l; } else if (p > 0) zero = true;
  }
  return {
    mean, variance: m2, skewness: m3 / Math.pow(m2, 1.5), kurtosis: m4 / (m2 * m2) - 3, entropy: H,
    meanLog: zero ? -Infinity : el, varLog: zero ? NaN : el2 - el * el,
  };
}

/* The highest density, searched on a grid between the 0.1 and 99.9
   percentiles and refined; a discrete one's most probable atom. */
function numericMode(D) {
  if (D.kind === 'discrete') {
    const at = D.atoms();
    if (!at) return NaN;
    let best = at[0][0]; let bp = -1;
    for (let i = 0; i < at[0].length; i++) if (at[1][i] > bp) { bp = at[1][i]; best = at[0][i]; }
    return best;
  }
  const a = D.quantile(0.001);
  const b = D.quantile(0.999);
  const N = 400;
  let best = a; let bestF = -Infinity;
  for (let i = 0; i <= N; i++) {
    const x = a + (b - a) * i / N;
    const f = D.logpdf(x);
    if (f > bestF) { bestF = f; best = x; }
  }
  for (const end of D.support) {
    if (Number.isFinite(end) && D.logpdf(end) >= bestF) return end;
  }
  let lo = Math.max(a, best - (b - a) / N);
  let hi = Math.min(b, best + (b - a) / N);
  for (let i = 0; i < 80; i++) {
    const m1 = lo + (hi - lo) / 3;
    const m2 = hi - (hi - lo) / 3;
    if (D.logpdf(m1) < D.logpdf(m2)) lo = m1; else hi = m2;
  }
  return (lo + hi) / 2;
}

/* The median of |X - median|: for a continuous distribution the d with
   F(m + d) - F(m - d) = 1/2. */
function medianAbsoluteDeviation(D, m) {
  if (!Number.isFinite(m)) return NaN;
  if (D.kind === 'discrete') {
    const at = D.atoms();
    if (!at) return NaN;
    const pairs = at[0].map((x, i) => [Math.abs(x - m), at[1][i]]).sort((a, b) => a[0] - b[0]);
    let c = 0;
    for (const [d, p] of pairs) { c += p; if (c >= 0.5 - 1e-12) return d; }
    return pairs.length ? pairs[pairs.length - 1][0] : NaN;
  }
  const g = (d) => D.cdf(m + d) - D.cdf(m - d) - 0.5;
  let hi = Math.max(D.quantile(0.75) - m, m - D.quantile(0.25), 1e-300);
  for (let i = 0; i < 200 && g(hi) < 0; i++) hi *= 2;
  return brentRoot(g, 0, hi);
}

/* ---- sampling -------------------------------------------------------------------------------- */

/**
 * n draws by inverse transform from rng() (uniform on (0, 1)); with lhs,
 * one draw from each of n equal-probability strata, in random order.
 */
function sampleOf(D, n, rng, lhs) {
  const out = new Float64Array(n);
  /* a kernel density draws from its table of quantiles, which is exact to
     far below its bandwidth and needs no root finding per draw */
  const at = D.fastAt ? (u, uc) => D.fastAt(u <= 0.5 ? u : 1 - uc) : D.at;
  if (lhs) {
    const order = Array.from({ length: n }, (_, i) => i);
    for (let i = n - 1; i > 0; i--) { const j = Math.floor(rng() * (i + 1)); const t = order[i]; order[i] = order[j]; order[j] = t; }
    for (let i = 0; i < n; i++) {
      const k = order[i];
      const r = rng();
      out[i] = at((k + r) / n, (n - k - r) / n);
    }
    return out;
  }
  for (let i = 0; i < n; i++) {
    const u = rng();
    out[i] = at(u, 1 - u);
  }
  return out;
}
