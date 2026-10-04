/* ==========================================================================
   resources/js/erf.js against mpmath

       node resources/tests/logn/test-erf.mjs

   erf.js is a classic script (logn.html and rb.html load it), so it is run
   here in a strict function scope: a variable it forgets to declare throws.
   The values are mpmath's at 40 digits (400 for erfcinv(1e-300)), rounded
   to doubles:

       mp.mp.dps = 40
       erf(x), erfc(x), exp(x*x) * erfc(x), erfinv(w), erfinv(1 - z)

   They include each place the file was once wrong: erfc beyond 4 (1/sqrt(pi)
   taken for sqrt(pi)), erfc and erfcx beyond the single-precision limits
   (NaN from |x| = 9.194), and erfcinv where a rational approximation's
   argument is zero (z = 0.25 and 1.75 gave 0/0).
   ========================================================================== */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const file = fileURLToPath(new URL('../../js/erf.js', import.meta.url));
const lib = new Function(`'use strict';\n${readFileSync(file, 'utf8')}\n;return { erf, erfc, erfcx, erfcinv, erfinv, erfinv_refine };`)();

const REF = [
  ['erf', 1e-20, 1.1283791670955125e-20],
  ['erf', 0.25, 0.27632639016823696],
  ['erf', 0.46875, 0.49261347321793797],
  ['erf', 0.5, 0.5204998778130465],
  ['erf', 1, 0.8427007929497149],
  ['erf', 2, 0.9953222650189527],
  ['erf', 3.9, 0.9999999652077514],
  ['erf', 4, 0.9999999845827421],
  ['erf', 4.05, 0.9999999898117551],
  ['erf', 4.5, 0.9999999998033839],
  ['erf', 6, 1.0],
  ['erf', -4.5, -0.9999999998033839],
  ['erf', 10, 1.0],
  ['erf', -30, -1.0],
  ['erfc', 0.46875, 0.507386526782062],
  ['erfc', 1, 0.15729920705028513],
  ['erfc', 3.5, 7.430983723414128e-07],
  ['erfc', 4, 1.541725790028002e-08],
  ['erfc', 4.5, 1.9661604415428876e-10],
  ['erfc', 6, 2.1519736712498913e-17],
  ['erfc', 9.2, 1.0627315595404888e-38],
  ['erfc', 10, 2.088487583762545e-45],
  ['erfc', 20, 5.395865611607901e-176],
  ['erfc', 26.5, 2.2109076642637343e-307],
  ['erfc', -4.5, 1.999999999803384],
  ['erfc', -10, 2.0],
  ['erfc', -30, 2.0],
  ['erfcx', -26, 7.657724931490568e+293],
  ['erfcx', -4.5, 1245928884.2744062],
  ['erfcx', 0.25, 0.7703465477309968],
  ['erfcx', 1, 0.427583576155807],
  ['erfcx', 3.5, 0.1552936556088943],
  ['erfcx', 4.5, 0.12248480427384142],
  ['erfcx', 10, 0.05614099274382259],
  ['erfcx', 1000, 0.0005641893014533876],
  ['erfcx', 1e8, 5.641895835477562e-09],
  ['erfcinv', 0.25, 0.8134198475976185],
  ['erfcinv', 1.75, -0.8134198475976185],
  ['erfcinv', 0.5, 0.4769362762044699],
  ['erfcinv', 1e-300, 26.209469960516124],
  ['erfcinv', 1e-10, 4.572824967389486],
  ['erfcinv', 1.5, -0.4769362762044699],
  ['erfinv', 0.5, 0.4769362762044699],
  ['erfinv', 0.85, 1.0179024648320276],
  ['erfinv', -0.9, -1.1630871536766743],
  ['erfinv', 0.999999, 3.458910737275499],
];

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
  checks++;
  if (!ok) failures.push(`${label}${detail ? `: ${detail}` : ''}`);
}

for (const [name, x, want] of REF) {
  const got = lib[name](x);
  const rel = Math.abs(got - want) / Math.abs(want);
  check(`${name}(${x})`, rel <= 4e-15, `${got} vs ${want} (relative ${rel.toExponential(1)})`);
}
/* where a double has no room: the limits, not NaN */
const exact = [
  ['erfc(26.6) underflows to 0', lib.erfc(26.6), 0],
  ['erfc(Infinity)', lib.erfc(Infinity), 0],
  ['erfc(-Infinity)', lib.erfc(-Infinity), 2],
  ['erfcx(-27) overflows to Infinity', lib.erfcx(-27), Infinity],
  ['erfcx(1e308) underflows to 0', lib.erfcx(1e308), 0],
  ['erfcinv(0)', lib.erfcinv(0), Infinity],
  ['erfcinv(2)', lib.erfcinv(2), -Infinity],
  ['erfcinv(1)', lib.erfcinv(1), 0],
  ['erf(Infinity)', lib.erf(Infinity), 1],
];
for (const [label, got, want] of exact) check(label, got === want, `${got}`);
check('NaN in, NaN out', [lib.erf, lib.erfc, lib.erfcx, lib.erfcinv, lib.erfinv].every((f) => Number.isNaN(f(NaN))));
/* erf and erfc agree where both have their digits */
for (const x of [0.1, 0.46875, 0.6, 2, 3.9, 4, 4.1]) {
  check(`erf(${x}) + erfc(${x}) = 1`, Math.abs(lib.erf(x) + lib.erfc(x) - 1) <= 2.3e-16);
}
let refined;
try { refined = lib.erfinv_refine(0.5, 2); } catch (e) { refined = e.message; }
check('erfinv_refine runs in strict mode', Math.abs(refined - 0.4769362762044699) <= 2e-16, String(refined));

for (const f of failures) console.log(`FAIL  ${f}`);
console.log(`${checks - failures.length} of ${checks} checks passed`);
process.exit(failures.length ? 1 : 0);
