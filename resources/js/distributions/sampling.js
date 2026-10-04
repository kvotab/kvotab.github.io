/* ==========================================================================
   distributions.html: SAMPLES

   Draws of a distribution by inverse transform: a uniform number u in
   (0, 1) becomes the value at probability u (read from the complement 1 - u
   above one half, so that the upper tail keeps its digits). The schemes
   differ only in the uniforms:

     random        independent draws (xoshiro128**, rng.js)
     lhs           Latin hypercube: one draw from each of n equal strata of
                   probability, at a random place in it, in random order
                   (McKay, Beckman and Conover 1979)
     lhs-centred   the same at the middle of each stratum
     sobol         Sobol's sequence with Joe and Kuo's direction numbers
                   (2008; sobol.LICENSE), scrambled by a random lower
                   triangular matrix and a random digital shift (Matoušek
                   1998), which keeps it a net
     halton        Halton's sequence in the first sixteen primes, each digit
                   position scrambled by a random permutation of the digits

   Every distribution draws from a stream of its own, made from the seed and
   its letter (rng.js), so its sample does not depend on which others are
   drawn; with the same seed a simple random or Latin hypercube sample is the
   draws a Monte Carlo expression takes. In the two sequences the letter is
   also the dimension (A the first), so that samples taken together fill the
   unit cube of their probabilities evenly.
   ========================================================================== */

import { makeRng, streamSeed } from './rng.js';
import { makeDistribution } from './dist.js';
import { ksPValue } from './fit.js';
import { sampleQuantile } from './kit.js';

export const SCHEMES = [
  ['random', 'Simple random (Monte Carlo)'],
  ['lhs', 'Latin hypercube'],
  ['lhs-centred', 'Latin hypercube, centred'],
  ['sobol', 'Sobol sequence, scrambled'],
  ['halton', 'Halton sequence, scrambled'],
];

/** The schemes in a few words, for tables. */
export const SCHEME_SHORT = { random: 'simple random', lhs: 'Latin hypercube', 'lhs-centred': 'centred Latin hypercube', sobol: 'Sobol', halton: 'Halton' };

/** The percentiles a sample's summary reports. */
export const SAMPLE_PERCENTILES = [1, 5, 50, 95, 99];

/** At most this many draws of one distribution, and of all together. */
export const SAMPLE_MAX = 1000000;
export const SAMPLE_TOTAL_MAX = 4000000;

/* The dimensions the sequences have: one for each letter the page gives. */
export const SEQUENCE_DIMENSIONS = 16;

/* ---- Sobol ------------------------------------------------------------------------------------ */

/* Joe and Kuo's new-joe-kuo-6.21201, dimensions 2 to 16: the primitive
   polynomial (its coefficients as the bits of the number, leading and
   trailing ones included) and the initial direction numbers m. The first
   dimension is the van der Corput sequence, every m = 1. */
const SOBOL_DIRECTIONS = [
  null,
  [3, [1]],
  [7, [1, 3]],
  [11, [1, 3, 1]],
  [13, [1, 1, 1]],
  [19, [1, 1, 3, 3]],
  [25, [1, 3, 5, 13]],
  [37, [1, 1, 5, 5, 17]],
  [41, [1, 1, 5, 5, 5]],
  [47, [1, 1, 7, 11, 19]],
  [55, [1, 1, 5, 1, 1]],
  [59, [1, 1, 1, 3, 11]],
  [61, [1, 3, 5, 5, 31]],
  [67, [1, 3, 3, 9, 7, 49]],
  [91, [1, 1, 1, 15, 21, 21]],
  [97, [1, 3, 1, 13, 27, 49]],
];

/**
 * The 32 direction numbers of dimension d (from 0), as 32-bit words whose
 * top bit is the first binary digit: V_j = m_j 2^(31 - j), and from the
 * degree s on the recurrence V_j = V_(j-s) ^ (V_(j-s) >> s) ^ the a_k V_(j-k)
 * of the polynomial's middle coefficients (Bratley and Fox 1988).
 */
export function sobolDirections(d) {
  const v = new Uint32Array(32);
  if (d === 0) {
    for (let j = 0; j < 32; j++) v[j] = 2 ** (31 - j);
    return v;
  }
  const [poly, m] = SOBOL_DIRECTIONS[d];
  const s = m.length;
  for (let j = 0; j < s; j++) v[j] = m[j] * 2 ** (31 - j);
  for (let j = s; j < 32; j++) {
    let w = (v[j - s] ^ (v[j - s] >>> s)) >>> 0;
    for (let k = 1; k < s; k++) if ((poly >>> (s - k)) & 1) w = (w ^ v[j - k]) >>> 0;
    v[j] = w;
  }
  return v;
}

const bitParity = (x) => {
  x ^= x >>> 16;
  x ^= x >>> 8;
  x ^= x >>> 4;
  x ^= x >>> 2;
  x ^= x >>> 1;
  return x & 1;
};

/** A random 32-bit word from a stream of doubles. */
const word = (rng) => Math.floor(rng() * 4294967296) >>> 0;

/**
 * n points of dimension d of Sobol's sequence as 32-bit integers, in Gray
 * code order. With rng, scrambled: the direction numbers multiplied by a
 * random lower triangular binary matrix with a unit diagonal, and every
 * point shifted by a random word (XOR). Without, the plain sequence, which
 * starts at 0.
 */
export function sobolWords(n, d, rng) {
  let v = sobolDirections(d);
  let x = 0;
  if (rng) {
    /* row r of the matrix (digit r from the top) has its diagonal digit and
       random digits to the left of it, the ones above it */
    const rows = new Uint32Array(32);
    for (let r = 0; r < 32; r++) {
      const above = r === 0 ? 0 : (word(rng) & ~(0xffffffff >>> r)) >>> 0;
      rows[r] = (above | (0x80000000 >>> r)) >>> 0;
    }
    const scrambled = new Uint32Array(32);
    for (let j = 0; j < 32; j++) {
      let y = 0;
      for (let r = 0; r < 32; r++) if (bitParity(rows[r] & v[j])) y |= 0x80000000 >>> r;
      scrambled[j] = y >>> 0;
    }
    v = scrambled;
    x = word(rng);
  }
  const out = new Uint32Array(n);
  if (n) out[0] = x;
  for (let i = 0; i + 1 < n; i++) {
    /* the lowest zero bit of i */
    x = (x ^ v[31 - Math.clz32((i + 1) & ~i)]) >>> 0;
    out[i + 1] = x;
  }
  return out;
}

/* ---- Halton -------------------------------------------------------------------------------------- */

const PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53];

/**
 * n points of dimension d of Halton's sequence: the radical inverse of
 * 0, 1, 2, ... in the d-th prime, each digit position's digits permuted at
 * random (as many positions as a double holds; the positions past an
 * index's own digits hold the permuted zero, which places the point at
 * random inside its smallest cell). Without rng, the plain sequence.
 */
export function haltonPoints(n, d, rng) {
  const b = PRIMES[d];
  const positions = Math.ceil(54 / Math.log2(b)) - 1;
  const perms = [];
  for (let j = 0; j < positions; j++) {
    const p = Array.from({ length: b }, (_, i) => i);
    if (rng) for (let i = b - 1; i > 0; i--) { const k = Math.floor(rng() * (i + 1)); const t = p[i]; p[i] = p[k]; p[k] = t; }
    perms.push(p);
  }
  /* what the positions from k on add when every digit there is zero */
  const tail = new Float64Array(positions + 1);
  for (let k = positions - 1; k >= 0; k--) tail[k] = tail[k + 1] + perms[k][0] * b ** -(k + 1);
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let v = 0;
    let k = 0;
    let f = 1 / b;
    for (let m = i; m > 0 && k < positions; k++) {
      const digit = m % b;
      m = (m - digit) / b;
      v += perms[k][digit] * f;
      f /= b;
    }
    out[i] = v + tail[k];
  }
  return out;
}

/* ---- the uniforms ------------------------------------------------------------------------------ */

/* Strictly inside (0, 1): an end would be an infinite draw from an
   unbounded distribution. */
const LOW = 2 ** -53;

/**
 * n uniforms of one distribution and their complements, by a scheme.
 *
 * @param {string} scheme   one of SCHEMES
 * @param {number} n
 * @param {number} seed
 * @param {string} letter   the distribution's letter: its stream, and in a sequence its dimension
 * @returns {{u: Float64Array, uc: Float64Array}}
 */
export function uniforms(scheme, n, seed, letter) {
  const rng = makeRng(streamSeed(seed, letter));
  const u = new Float64Array(n);
  const uc = new Float64Array(n);
  if (scheme === 'random') {
    for (let i = 0; i < n; i++) { u[i] = rng(); uc[i] = 1 - u[i]; }
  } else if (scheme === 'lhs' || scheme === 'lhs-centred') {
    /* the order and the places as dist.js's sampler takes them from the stream */
    const order = Array.from({ length: n }, (_, i) => i);
    for (let i = n - 1; i > 0; i--) { const j = Math.floor(rng() * (i + 1)); const t = order[i]; order[i] = order[j]; order[j] = t; }
    for (let i = 0; i < n; i++) {
      const k = order[i];
      const r = scheme === 'lhs' ? rng() : 0.5;
      u[i] = (k + r) / n;
      uc[i] = (n - k - r) / n;
    }
  } else if (scheme === 'sobol' || scheme === 'halton') {
    const d = dimensionOf(letter);
    if (scheme === 'sobol') {
      const w = sobolWords(n, d, rng);
      /* the middle of the point's cell of width 2^-32 */
      for (let i = 0; i < n; i++) { u[i] = (w[i] + 0.5) / 4294967296; uc[i] = (4294967295.5 - w[i]) / 4294967296; }
    } else {
      const h = haltonPoints(n, d, rng);
      for (let i = 0; i < n; i++) {
        const v = Math.min(1 - LOW, Math.max(LOW, h[i]));
        u[i] = v;
        uc[i] = 1 - v;
      }
    }
  } else {
    throw new Error(`Unknown sampling scheme ${scheme}.`);
  }
  return { u, uc };
}

/** A letter's dimension in the sequences: A the first. */
export function dimensionOf(letter) {
  const d = String(letter).charCodeAt(0) - 65;
  if (!(d >= 0 && d < SEQUENCE_DIMENSIONS)) throw new Error(`The sequences have ${SEQUENCE_DIMENSIONS} dimensions, for the letters A to P.`);
  return d;
}

/**
 * n draws of D by a scheme, with the uniforms they came from.
 *
 * @param {Object} D        from makeDistribution
 * @returns {{values: Float64Array, u: Float64Array}}
 */
export function drawSample(D, scheme, n, seed, letter) {
  const { u, uc } = uniforms(scheme, n, seed, letter);
  /* a kernel density draws from its table of quantiles, as dist.js's sampler does */
  const at = D.fastAt ? (p, q) => D.fastAt(p <= 0.5 ? p : 1 - q) : D.at;
  const values = new Float64Array(n);
  for (let i = 0; i < n; i++) values[i] = at(u[i], uc[i]);
  return { values, u };
}

/**
 * A sample against its distribution: n, mean, SD (n - 1), the ends, the
 * percentiles of SAMPLE_PERCENTILES (type 7) and Kolmogorov-Smirnov's D with
 * its p-value. For a continuous distribution F(x) is the uniform a draw came
 * from, so D needs no CDF; for a discrete one the CDF is taken at each
 * distinct value, below and at it.
 */
export function summarise(D, values, u) {
  const n = values.length;
  const sorted = Float64Array.from(values).sort();
  let mean = 0;
  for (let i = 0; i < n; i++) mean += (sorted[i] - mean) / (i + 1);
  let ss = 0;
  for (let i = 0; i < n; i++) ss += (sorted[i] - mean) ** 2;
  let d = 0;
  if (D.kind === 'discrete') {
    for (let i = 0; i < n;) {
      let j = i;
      while (j < n && sorted[j] === sorted[i]) j++;
      const F = D.cdf(sorted[i]);
      const below = F - D.pdf(sorted[i]);
      d = Math.max(d, Math.abs(i / n - below), Math.abs(j / n - F));
      i = j;
    }
  } else {
    const us = Float64Array.from(u).sort();
    for (let i = 0; i < n; i++) d = Math.max(d, (i + 1) / n - us[i], us[i] - i / n);
  }
  return {
    n, mean, sd: n > 1 ? Math.sqrt(ss / (n - 1)) : NaN, min: sorted[0], max: sorted[n - 1],
    q: SAMPLE_PERCENTILES.map((p) => sampleQuantile(sorted, p / 100)),
    ks: d, ksP: ksPValue(d, n),
  };
}

/**
 * The job the worker runs: each item drawn and summarised.
 *
 * @param {{items: Array<{key, letter, spec}>, n, scheme, seed}} payload
 * @param {function(number, number, string)} [progress]
 * @returns {{columns: Array<{key, values?: Float64Array, summary?: Object, error?: string}>}}
 */
export function sampleJob(payload, progress) {
  const { items, n, scheme, seed } = payload;
  if (!(Number.isInteger(n) && n >= 1 && n <= SAMPLE_MAX)) throw new Error(`The number of draws must be a whole number from 1 to ${SAMPLE_MAX.toLocaleString('en')}.`);
  if (n * items.length > SAMPLE_TOTAL_MAX) throw new Error(`At most ${SAMPLE_TOTAL_MAX.toLocaleString('en')} draws in all.`);
  const columns = [];
  items.forEach((item, k) => {
    if (progress) progress(k, items.length, item.letter);
    try {
      const D = makeDistribution(item.spec);
      const { values, u } = drawSample(D, scheme, n, seed, item.letter);
      columns.push({ key: item.key, values, summary: summarise(D, values, u) });
    } catch (e) {
      columns.push({ key: item.key, error: e.message });
    }
  });
  return { columns };
}
