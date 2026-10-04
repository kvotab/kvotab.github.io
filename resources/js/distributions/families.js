/* ==========================================================================
   distributions.html: THE FAMILIES, LISTED

   A family (continuous.js, discrete.js) is a plain object. What it may
   define, with p its canonical parameters:

     id, label, kind ('continuous' | 'discrete'), group, blurb
     params        the canonical parameters: [{ key, label, domain }]
     defaults      canonical values a new distribution starts from
     validate(p)   '' or why the combination is impossible
     support(p)    [lowest, highest], either possibly infinite
     logpdf(x, p)  ln of the density (or of the probability, if discrete)
     cdf, sf       P(X <= x) and P(X > x); logcdf, logsf where precise
     quantile(u, p), isf(q, p)   the inverses of cdf and sf
     mean, variance, skewness, kurtosis (excess), entropy, mode, median
                   closed forms; undefined asks dist.js to integrate,
                   NaN means "does not exist", Infinity "is infinite"
     modeText(p)   words when the mode is not one value ("both ends")
     logMoments(p) [E ln X, Var ln X] for a positive family
     tails(p)      { left, right }: the orders below which moments exist
     parameterisations   [{ id, label, fields, to(values), from(p, values) }]
     free          { keys, to(p) -> z in R^k, from(z, p0) -> p } for solvers
     fit           { k, mle(sample, opts), mom(sample, opts), applicable(sample, opts),
                     regular (false: no standard errors), note }
     tex, scipy    for the Help
   ========================================================================== */

import { CONTINUOUS } from './continuous.js';
import { DISCRETE } from './discrete.js';
import { field } from './kit.js';

export const FAMILIES = [...CONTINUOUS, ...DISCRETE];

const BY_ID = Object.create(null);
for (const f of FAMILIES) BY_ID[f.id] = f;

/** A family by id, or null; an id from outside cannot reach Object's own keys. */
export function familyById(id) {
  return typeof id === 'string' && Object.prototype.hasOwnProperty.call(BY_ID, id) ? BY_ID[id] : null;
}

/** The groups of the family picker, in order. */
export const GROUPS = [
  ['General', 'General and symmetric'],
  ['Positive', 'Positive values'],
  ['Bounded', 'Bounded'],
  ['Log scale', 'Logarithmic shapes'],
  ['Extremes', 'Extremes'],
  ['Discrete', 'Counts (discrete)'],
];

/** The id of the "known values" parameterisation every solvable continuous family has. */
export const KNOWN = 'known';

/**
 * A family's parameterisations: its own, then "known values" for a
 * continuous family that can be solved for.
 */
export function parameterisationsOf(fam) {
  const list = (fam.parameterisations || []).slice();
  if (fam.kind === 'continuous' && fam.free) {
    const k = fam.free.keys.length;
    list.push({
      id: KNOWN,
      label: k === 1 ? 'One known value' : `Any ${['', 'one', 'two', 'three', 'four'][k] || k} known values`,
      known: k,
      fields: [],
    });
  }
  return list;
}

/** The parameters a family keeps fixed while solving or fitting (beta's ends, PERT's λ). */
export function fixedKeys(fam) {
  if (!fam.free) return [];
  return fam.params.map((p) => p.key).filter((key) => !fam.free.keys.includes(key));
}

/** The canonical parameter fields, as a parameterisation would list them. */
export function canonicalFields(fam) {
  return fam.params.map((p) => field(p.key, p.label, p.domain));
}
