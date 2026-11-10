/*
  Sensitivity indices from a sample, for rtm.html's Uncertainty tab: each
  number drawn against one value of each run, with nothing run again.

    - the first-order Sobol' index, by EASI (Plischke's effective algorithm,
      with Tissot and Prieur's correction for the bias a random design
      leaves): the share of the value's variance the number explains alone;
    - Borgonovo's moment-independent delta, reduced for its bias as SALib
      and GlobalSensitivity.jl reduce it: how far knowing the number moves
      the value's whole distribution, its tails as much as its middle. It is
      read off the value's normal scores -- its ranks put through the
      inverse of the normal distribution -- which do not change it: delta is
      the same for any increasing transformation of the output (Borgonovo,
      Tarantola, Plischke and Morris 2014, J. R. Stat. Soc. B 76, 925). A
      value most runs share, a front that has come through, makes a kernel
      density estimate of the value itself a spike, and delta lands far
      outside [0, 1]; the scores' never is. Scores rather than the ranks
      themselves, whose edges at 0 and 1 a kernel blurs: on the Ishigami
      function the ranks take x1's delta from 0.215 to 0.178, the scores to
      0.220;
    - PAWN, the median over ten slices of the number of the
      Kolmogorov-Smirnov distance between the value's distribution in the
      slice and overall.

  The methods are Kompartment's ports -- kompartment/src/domain/gsa.js of
  GlobalSensitivity.jl, salib.js of SALib -- checked there against them.
  Each index has an interval at conf, SALib's: the estimate plus and minus
  the normal quantile times the standard deviation of the index over the
  same bootstrap resamples of the runs, the same resamples for every number
  and every index. The resamples come from the seed given, so that the same
  runs give the same intervals.
*/
import { easi, deltaMoment } from '../../../kompartment/src/domain/gsa.js';
import { pawn } from '../../../kompartment/src/domain/salib.js';
import { normalQuantile } from '../../../kompartment/src/domain/pdf.js';

/** A stream of uniforms on [0, 1) from a seed: mulberry32. */
export function seeded(seed) {
  let a = (Math.floor(Math.abs(Number(seed) || 1)) >>> 0) || 1;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** n indices into n runs, drawn with replacement, `boots` times. */
export function bootstrapResamples(n, boots, next) {
  return Array.from({ length: boots }, () => {
    const r = new Int32Array(n);
    for (let i = 0; i < n; i++) r[i] = Math.min(n - 1, Math.floor(next() * n));
    return r;
  });
}

/**
 * Each value's normal score: the standard normal's quantile at its rank over
 * all of them, (k + 1/2)/n. Ties -- runs that come to the same number -- are
 * put in an order of their own by the stream next, which no input has
 * anything to do with.
 */
export function normalScores(v, next) {
  const key = Float64Array.from(v, () => next());
  const idx = Array.from({ length: v.length }, (_, i) => i).sort((p, q) => v[p] - v[q] || key[p] - key[q]);
  const r = new Float64Array(v.length);
  idx.forEach((i, k) => { r[i] = normalQuantile((k + 0.5) / v.length); });
  return r;
}

const sdOf = (v) => {
  if (v.length < 2) return NaN;
  let m = 0;
  for (const x of v) m += x;
  m /= v.length;
  let s = 0;
  for (const x of v) s += (x - m) * (x - m);
  return Math.sqrt(s / (v.length - 1));
};

/**
 * The three indices of each number drawn, xs[j][run], against the value
 * y[run].
 * @param {ArrayLike<number>[]} xs  one column per number drawn
 * @param {ArrayLike<number>} y     the value of each run
 * @param {object} [o]
 * @param {number} [o.boots]        bootstrap resamples (100, as SALib's delta)
 * @param {number} [o.seed]         where the resamples come from
 * @param {number} [o.conf]         the intervals' level
 * @param {Int32Array[]} [o.resamples]  the resamples themselves, for a test
 * @param {boolean} [o.scores]      delta off the value's normal scores (true), or off the value itself, as a test compares
 * @param {(j: number, of: number) => Promise<void>} [o.pause]  after each number: the page lets the browser draw
 * @returns {Promise<{ n, boots, conf, inputs: object[] }>}
 */
export async function indicesOf(xs, y, { boots = 100, seed = 1, conf = 0.95, resamples = null, scores = true, pause = null } = {}) {
  const Y = Float64Array.from(y);
  const n = Y.length;
  const R = resamples || bootstrapResamples(n, boots, seeded(seed));
  // What delta reads: the normal scores, ties ordered by a stream of their own, or the value.
  const D = scores ? normalScores(Y, seeded(seed + 104729)) : Y;
  const B = R.length;
  const z = normalQuantile(0.5 + conf / 2);
  const Yb = R.map((r) => Float64Array.from(r, (i) => Y[i]));
  const inputs = [];
  for (let j = 0; j < xs.length; j++) {
    const X = Float64Array.from(xs[j]);
    const Xb = R.map((r) => Float64Array.from(r, (i) => X[i]));
    const s1 = easi(X, Y).s1c;
    const s1Half = z * sdOf(Xb.map((xr, b) => easi(xr, Yb[b]).s1c).filter(Number.isFinite));
    // delta's own bootstrap, on the same resamples: what it gives back is GlobalSensitivity.jl's interval, the spread over
    // root B; SALib's, the interval of delta itself, is root B times as wide.
    const d = deltaMoment(X, D, { resamples: R, conf });
    const dHalf = (d.adjusted - d.low) * Math.sqrt(B);
    const pw = pawn(X, Y).median;
    const pwHalf = z * sdOf(Xb.map((xr, b) => pawn(xr, Yb[b]).median).filter(Number.isFinite));
    inputs.push({
      s1, s1Low: s1 - s1Half, s1High: s1 + s1Half,
      delta: d.adjusted, deltaLow: d.adjusted - dHalf, deltaHigh: d.adjusted + dHalf, deltaRaw: d.delta,
      pawn: pw, pawnLow: pw - pwHalf, pawnHigh: pw + pwHalf,
    });
    if (pause) await pause(j, xs.length);
  }
  return { n, boots: B, conf, inputs };
}
