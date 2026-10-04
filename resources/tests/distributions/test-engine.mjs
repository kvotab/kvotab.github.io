#!/usr/bin/env node
/* ==========================================================================
   distributions.html's engine in Node, against SciPy and against itself.

     node resources/tests/distributions/test-engine.mjs [--verbose]

   1. Every family and parameter set of scipy-ref.json (gen-scipy-ref.py):
      density or probability, CDF, survival function, quantiles in both
      tails, mean, variance, skewness, excess kurtosis, entropy, median.
   2. Maximum-likelihood fits to SciPy's samples: ours must reach at least
      SciPy's log-likelihood.
   3. Internal checks that need no reference: every parameterisation
      round-trips, "known values" solve to the values asked for, truncation
      (at values and at percentiles), the empirical distributions, the method
      of moments matches the sample's moments, sampling, the expression
      parser; and the Sample tab's schemes, the plain sequences against
      SciPy's points (qmc-ref.json, gen-qmc-ref.py).

   Exit status 0 when every check passes.
   ========================================================================== */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ENGINE = path.join(HERE, '..', '..', 'js', 'distributions');
const imp = (name) => import(path.join(ENGINE, name));
const { FAMILIES, familyById, parameterisationsOf, KNOWN } = await imp('families.js');
const { makeDistribution } = await imp('dist.js');

const VERBOSE = process.argv.includes('--verbose');
let checks = 0;
const failures = [];

function check(label, ok, detail = '') {
  checks++;
  if (!ok) {
    failures.push(`${label}${detail ? ': ' + detail : ''}`);
    console.log(`FAIL  ${label}${detail ? ': ' + detail : ''}`);
  } else if (VERBOSE) console.log(`ok    ${label}`);
}

const val = (v) => (v === 'nan' ? NaN : v === 'inf' ? Infinity : v === '-inf' ? -Infinity : v);

/* relative closeness, with an absolute floor for values near zero */
function close(got, want, rtol, atol = 0) {
  if (Number.isNaN(want)) return Number.isNaN(got);
  if (!Number.isFinite(want)) return got === want;
  if (!Number.isFinite(got)) return false;
  return Math.abs(got - want) <= Math.max(rtol * Math.abs(want), atol);
}

const show = (v) => (typeof v === 'number' ? v.toPrecision(12) : String(v));

/* ---- 1. against SciPy ------------------------------------------------------------------ */

const ref = JSON.parse(fs.readFileSync(path.join(HERE, 'scipy-ref.json'), 'utf8'));

/* Tolerances per quantity. SciPy's own entropy for some families is a
   numerical integral, and its skewness and kurtosis for some are formulas
   with cancellation, so those are looser. */
const TOL = { logpdf: 1e-10, cdf: 1e-10, sf: 1e-10, ppf: 1e-9, isf: 1e-9, mean: 1e-10, variance: 1e-9, skewness: 1e-7, kurtosis: 1e-6, entropy: 1e-7, median: 1e-9 };
/* No looser tolerances: where SciPy is imprecise, gen-scipy-ref.py takes
   the value from mpmath instead (a case's 'arbiter' says which). */
const LOOSE = {};

/* Deliberate differences from SciPy's conventions for moments that do not
   exist. The page says a moment is infinite when only one tail makes it
   diverge and the moments below it are finite, and undefined when both
   tails do or a lower moment is already infinite; SciPy says nan in some of
   the first cases and inf in one of the second. */
const CONVENTION = {
  'pareto|alpha=3|skewness': [Infinity, 'variance finite, third moment infinite on the right'],
  'pareto|alpha=3|kurtosis': [Infinity, 'variance finite, fourth moment infinite on the right'],
  'invgamma|alpha=3|skewness': [Infinity, 'variance finite, third moment infinite on the right'],
  'invgamma|alpha=3|kurtosis': [Infinity, 'variance finite, fourth moment infinite on the right'],
  'loglogistic|beta=4|kurtosis': [Infinity, 'variance finite, fourth moment infinite on the right'],
  'loglogistic|beta=1.5|variance': [Infinity, 'mean finite, second moment infinite on the right'],
  'gev|xi=0.6|variance': [Infinity, 'mean finite, second moment infinite on the right'],
  'gev|xi=0.3|kurtosis': [Infinity, 'variance finite, fourth moment infinite on the right'],
  'genpareto|xi=0.6|variance': [Infinity, 'mean finite, second moment infinite on the right'],
  'studentt|nu=0.7|mean': [NaN, 'both tails heavy: the mean is undefined, not infinite'],
  'invgamma|alpha=0.8|variance': [NaN, 'the mean is infinite, so the variance about it is undefined'],
};

for (const c of ref.cases) {
  const fam = familyById(c.family);
  const tag = `${c.family}(${Object.entries(c.params).map(([k, v]) => `${k}=${v}`).join(', ')})`;
  if (!fam) { check(`${tag} exists`, false); continue; }
  let D;
  try { D = makeDistribution({ family: c.family, params: c.params }); } catch (e) { check(`${tag} builds`, false, e.message); continue; }
  const loose = (what) => {
    for (const [key, [tol]] of Object.entries(LOOSE)) {
      const [f, p, w] = key.split('|');
      const [pk, pv] = p.split('=');
      if (f === c.family && String(c.params[pk]) === pv && w === what) return tol;
    }
    return null;
  };
  const tol = (what) => loose(what) ?? TOL[what];
  for (let i = 0; i < c.x.length; i++) {
    const x = c.x[i];
    const lp = val(c.logpdf[i]);
    const gotLp = D.logpdf(x);
    check(`${tag} logpdf(${x})`, lp === -Infinity ? gotLp === -Infinity : close(gotLp, lp, tol('logpdf'), 1e-12), `${show(gotLp)} vs ${show(lp)}`);
    const F = val(c.cdf[i]);
    check(`${tag} cdf(${x})`, close(D.cdf(x), F, tol('cdf'), 1e-300), `${show(D.cdf(x))} vs ${show(F)}`);
    const S = val(c.sf[i]);
    check(`${tag} sf(${x})`, close(D.sf(x), S, tol('sf'), 1e-300), `${show(D.sf(x))} vs ${show(S)}`);
  }
  for (let i = 0; i < c.u.length; i++) {
    const want = val(c.ppf[i]);
    const got = D.quantile(c.u[i]);
    check(`${tag} quantile(${c.u[i]})`, close(got, want, tol('ppf'), 1e-300), `${show(got)} vs ${show(want)}`);
  }
  for (let i = 0; i < c.q.length; i++) {
    const want = val(c.isf[i]);
    const got = D.isf(c.q[i]);
    check(`${tag} isf(${c.q[i]})`, close(got, want, tol('isf'), 1e-300), `${show(got)} vs ${show(want)}`);
  }
  const s = D.stats();
  for (const [name, w] of Object.entries(c.stats)) {
    let want = val(w);
    for (const [key, [ours]] of Object.entries(CONVENTION)) {
      const [f, p, what] = key.split('|');
      const [pk, pv] = p.split('=');
      if (f === c.family && String(c.params[pk]) === pv && what === name) want = ours;
    }
    const got = s[name];
    check(`${tag} ${name}`, close(got, want, tol(name), 1e-12), `${show(got)} vs ${show(want)}`);
  }
}

/* ---- summary ---------------------------------------------------------------------------- */

const extra = await import(path.join(HERE, 'engine-checks.mjs')).catch((e) => {
  if (e.code === 'ERR_MODULE_NOT_FOUND') return null;
  throw e;
});
if (extra) await extra.run({ check, close, imp, ref, VERBOSE });

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
process.exit(failures.length ? 1 : 0);
