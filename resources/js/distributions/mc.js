/* ==========================================================================
   distributions.html: MONTE CARLO OF AN EXPRESSION

   The draws behind a Monte Carlo distribution: each distribution the
   expression names is drawn n times by a sampling scheme (sampling.js:
   simple random, Latin hypercube, centred Latin hypercube, Sobol, Halton)
   from a stream of its own (the seed and the distribution's letter make the
   stream, so changing one distribution leaves the others' draws as they
   were; in the sequences the letter is the dimension, so the draws of the
   letters fill their joint probabilities evenly), the expression is
   evaluated draw by draw, and the results that are not finite numbers are
   counted and left out. Runs in the page's worker, or in the page when
   there is none.
   ========================================================================== */

import { makeDistribution } from './dist.js';
import { parseExpression, evaluateExpression } from './expr.js';
import { streamSeed } from './rng.js';
import { drawSample, SCHEMES } from './sampling.js';

export { streamSeed };

export const MC_MAX = 1000000;

/**
 * @param {Object<string, Object>} specs  the spec of each letter the expression may name
 * @param {string} expr
 * @param {number} n
 * @param {number} seed
 * @param {string|boolean} scheme   one of sampling.js's SCHEMES (true and false: Latin hypercube or simple random)
 * @returns {{values: Float64Array, dropped: number}}
 */
export function runMonteCarlo(specs, expr, n, seed, scheme) {
  const how = scheme === true ? 'lhs' : scheme === false || scheme == null ? 'random' : String(scheme);
  if (!SCHEMES.some(([k]) => k === how)) throw new Error(`Unknown sampling scheme ${how}.`);
  if (!(Number.isInteger(n) && n >= 2 && n <= MC_MAX)) throw new Error(`The number of draws must be a whole number from 2 to ${MC_MAX.toLocaleString('en')}.`);
  const { tree, variables } = parseExpression(expr, (name) => Object.prototype.hasOwnProperty.call(specs, name));
  if (!variables.length) throw new Error('The expression names no distribution.');
  const env = {};
  for (const letter of variables) {
    const D = makeDistribution(specs[letter]);
    env[letter] = drawSample(D, how, n, seed, letter).values;
  }
  const raw = evaluateExpression(tree, env, n);
  const all = typeof raw === 'number' ? new Float64Array(n).fill(raw) : raw;
  let kept = 0;
  for (let i = 0; i < n; i++) if (Number.isFinite(all[i])) all[kept++] = all[i];
  return { values: all.slice(0, kept), dropped: n - kept };
}
