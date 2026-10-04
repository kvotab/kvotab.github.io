/* ==========================================================================
   distributions.html: A DISTRIBUTION FROM KNOWN VALUES

   "Any two known values": the member of a family with, say, a mean of 5 and
   a 95th percentile of 20. As many values as the family has free
   parameters, each a property (mean, median, mode, SD, variance, CV, a
   percentile, geometric mean or SD); the parameters are found by
   Nelder-Mead on the squared relative misses from several starts, then
   polished by Newton's method until the values are met to about twelve
   figures. When no member of the family has the values (a lognormal whose
   mean is below its median), the nearest is reported, not used. With a
   shift the values are those of the shifted distribution, X + shift.
   ========================================================================== */

import { makeDistribution } from './dist.js';
import { fixedKeys } from './families.js';
import { propertyById } from './kit.js';
import { nelderMead, newtonSystem } from './numeric.js';

/**
 * A property of a distribution: closed forms first, the evaluated statistics
 * after. D is the distribution with the shift; params are the family's
 * own, before it.
 */
export function propertyValue(fam, D, params, row, shift = 0) {
  const has = (name) => typeof fam[name] === 'function';
  const closed = (name) => (has(name) ? fam[name](params) : undefined);
  const lazy = () => D.stats();
  const moved = (v) => (v === undefined ? undefined : v + shift);
  switch (row.prop) {
    case 'mean': { const v = moved(closed('mean')); return v !== undefined ? v : lazy().mean; }
    case 'median': { const v = moved(closed('median')); return v !== undefined ? v : D.quantile(0.5); }
    case 'mode': { const v = moved(closed('mode')); return v !== undefined ? v : lazy().mode; }
    case 'var': { const v = closed('variance'); return v !== undefined ? v : lazy().variance; }
    case 'sd': { const v = closed('variance'); return Math.sqrt(v !== undefined ? v : lazy().variance); }
    case 'cv': {
      const m = moved(closed('mean')); const v = closed('variance');
      const mm = m !== undefined ? m : lazy().mean;
      const vv = v !== undefined ? v : lazy().variance;
      return Math.sqrt(vv) / Math.abs(mm);
    }
    case 'q': return D.quantile(row.p / 100);
    /* the logarithms of shifted values have no closed form */
    case 'gm': { const lm = !shift && has('logMoments') ? fam.logMoments(params) : null; return lm ? Math.exp(lm[0]) : lazy().gm; }
    case 'gsd': { const lm = !shift && has('logMoments') ? fam.logMoments(params) : null; return lm ? Math.exp(Math.sqrt(lm[1])) : lazy().gsd; }
    default: return NaN;
  }
}

/** The label of a known-value row, as a message names it. */
export function rowLabel(row) {
  if (row.prop === 'q') return `the ${+row.p}th percentile`;
  const p = propertyById(row.prop);
  return p ? `the ${p.label.toLowerCase()}` : row.prop;
}

/**
 * The parameters of the member of fam whose properties are the rows'.
 *
 * @param {Object} fam
 * @param {Array<{prop: string, p?: number, value: number}>} rows
 * @param {Object} p0   the current parameters (a start, and the fixed ones)
 * @param {number} [shift]   added to every value: the rows describe X + shift
 * @returns {Object} canonical parameters (before the shift)
 */
export function solveKnown(fam, rows, p0, shift = 0) {
  if (!fam.free) throw new Error('This family cannot be given by known values.');
  const k = fam.free.keys.length;
  if (rows.length !== k) throw new Error(`Give ${k} value${k > 1 ? 's' : ''}.`);
  const seen = new Set();
  for (const row of rows) {
    if (!Number.isFinite(row.value)) throw new Error(`Give a value for ${rowLabel(row)}.`);
    if (row.prop === 'q' && !(row.p > 0 && row.p < 100)) throw new Error('A percentile must be between 0 and 100.');
    const prop = propertyById(row.prop);
    if (prop && prop.domain === 'pos' && !(row.value > 0)) throw new Error(`${rowLabel(row)[0].toUpperCase()}${rowLabel(row).slice(1)} must be above zero.`);
    if (prop && prop.domain === 'gt1' && !(row.value > 1)) throw new Error('The geometric SD must be above 1.');
    const key = row.prop === 'q' ? `q${row.p}` : row.prop;
    if (seen.has(key)) throw new Error(`${rowLabel(row)[0].toUpperCase()}${rowLabel(row).slice(1)} is given twice.`);
    seen.add(key);
  }
  /* The scale a miss is measured against: the value itself, or for a value
     at zero the spread the other values imply. */
  const spread = (() => {
    const loc = rows.filter((r) => ['mean', 'median', 'mode', 'q', 'gm'].includes(r.prop)).map((r) => r.value);
    const sd = rows.find((r) => r.prop === 'sd');
    const v = rows.find((r) => r.prop === 'var');
    if (sd) return sd.value;
    if (v) return Math.sqrt(v.value);
    if (loc.length > 1) return Math.max(...loc) - Math.min(...loc);
    return Math.max(1e-300, ...loc.map(Math.abs));
  })();
  const scales = rows.map((r) => Math.abs(r.value) > 0 ? Math.abs(r.value) : spread || 1);
  const fixed = {};
  for (const key of fixedKeys(fam)) fixed[key] = p0 && Number.isFinite(p0[key]) ? p0[key] : fam.defaults[key];
  const base = { ...fam.defaults, ...fixed };
  const residual = (z) => {
    let params;
    try { params = { ...base, ...fam.free.from(z, base), ...fixed }; } catch (e) { return null; }
    let D;
    try { D = makeDistribution({ family: fam.id, params, shift }); } catch (e) { return null; }
    const r = [];
    for (let i = 0; i < rows.length; i++) {
      const v = propertyValue(fam, D, params, rows[i], shift);
      if (!Number.isFinite(v)) return null;
      r.push((v - rows[i].value) / scales[i]);
    }
    return r;
  };
  const cost = (z) => { const r = residual(z); return r ? r.reduce((a, b) => a + b * b, 0) : Infinity; };
  const starts = [];
  const add = (p) => {
    try {
      const q = { ...base, ...p, ...fixed };
      if (fam.validate && fam.validate(q)) return;
      const z = fam.free.to(q);
      if (z.every(Number.isFinite)) starts.push(z);
    } catch (e) { /* not a start */ }
  };
  /* the starts are placed by the values before the shift */
  const LOCATIONS = ['mean', 'median', 'mode', 'q'];
  const unshifted = shift ? rows.map((r) => (LOCATIONS.includes(r.prop) ? { ...r, value: r.value - shift } : r)) : rows;
  if (p0) add(p0);
  add(fam.defaults);
  add(scaledDefaults(fam, unshifted));
  for (const p of rangeStarts(fam, unshifted)) add(p);
  let best = null;
  for (const z0 of starts) {
    if (!Number.isFinite(cost(z0))) continue;
    const got = nelderMead(cost, z0, { maxIter: 500 * k, ftol: 1e-20, xtol: 1e-12 });
    if (!best || got.f < best.f) best = got;
    if (best.f < 1e-20) break;
  }
  if (!best || !Number.isFinite(best.f)) throw new Error(`No ${fam.label.toLowerCase()} distribution has these values.`);
  const polished = newtonSystem((z) => residual(z) || new Array(k).fill(NaN), best.x, { tol: 1e-15 });
  const z = Number.isFinite(polished.norm) && polished.norm * polished.norm <= best.f ? polished.x : best.x;
  const r = residual(z);
  const params = { ...base, ...fam.free.from(z, base), ...fixed };
  const miss = r ? Math.max(...r.map(Math.abs)) : Infinity;
  if (!(miss < 1e-9)) {
    const err = new Error(`No ${fam.label.toLowerCase()} distribution has exactly these values.`);
    err.closest = params;
    throw err;
  }
  return params;
}

/* Starts for the families given by their ends and corners (a, c, b, d):
   the corners spread around the values given, at three widths, in the
   logarithms for a log shape. Started from defaults far from the values, a
   search over corners ends on a boundary. */
function rangeStarts(fam, rows) {
  const keys = fam.params.map((p) => p.key);
  if (!keys.includes('a') || !keys.includes('b')) return [];
  const logShape = fam.support(fam.defaults)[0] >= 0 && /^log/.test(fam.id);
  const where = rows.filter((r) => ['mean', 'median', 'mode', 'q', 'gm'].includes(r.prop)).map((r) => r.value);
  if (!where.length || (logShape && where.some((v) => !(v > 0)))) return [];
  const tx = logShape ? Math.log : (v) => v;
  const back = logShape ? Math.exp : (v) => v;
  const vals = where.map(tx).sort((p, q) => p - q);
  const lo = vals[0];
  const hi = vals[vals.length - 1];
  const sdRow = rows.find((r) => r.prop === 'sd');
  const spread = hi > lo ? hi - lo : (sdRow && !logShape ? 4 * sdRow.value : Math.max(Math.abs(lo), 1));
  const mode = rows.find((r) => r.prop === 'mode');
  const mid = mode ? tx(mode.value) : vals[Math.floor(vals.length / 2)];
  const out = [];
  for (const k of [0.25, 1, 3]) {
    const a = lo - k * spread;
    const b = hi + k * spread;
    const c = Math.min(b - 1e-9 * (b - a), Math.max(a + 1e-9 * (b - a), mid));
    const p = { a: back(a), b: back(b), c: back(c) };
    if (keys.includes('d')) Object.assign(p, { b: back(mid - spread / 4), c: back(mid + spread / 4), d: back(b) });
    out.push(p);
  }
  return out;
}

/* The defaults moved to where the values are: a start nearer than the
   defaults when the values are far from them. */
function scaledDefaults(fam, rows) {
  const loc = rows.find((r) => ['mean', 'median', 'mode', 'q', 'gm'].includes(r.prop));
  const out = { ...fam.defaults };
  if (!loc) return out;
  for (const def of fam.params) {
    if (def.domain === 'real' && /^(mu|x0)$/.test(def.key)) out[def.key] = loc.value;
    if (def.domain === 'pos' && /^(theta|lambda|sigma|beta|s|b|gamma|alpha|xm)$/.test(def.key) && loc.value > 0 && fam.support(fam.defaults)[0] >= 0) {
      out[def.key] = fam.defaults[def.key] * loc.value;
    }
  }
  return out;
}
