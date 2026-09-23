#!/usr/bin/env node
/*
  The sparse LU that keeps its pivots (RefactorLU in facsimile-solver.js),
  checked against the dense LU with partial pivoting it stands in for.

    1. On every iteration matrix of a real run of the canister model (case
       13g, captured from a run with the dense LU), it factors without falling
       back, and its solutions are as accurate as the dense LU's: the
       normwise backward error of each is at round-off.
    2. A pivot that collapses is chosen again, not used; a singular matrix and
       one with a NaN in it are declined, so the dense LU gets them.
    3. auto picks it for the canister model, and for a matrix where it costs
       no more than the searching sparse LU; a full matrix, where no order
       saves anything, stays on the dense LU.
    4. Asked for on a model whose constraint does not determine its variable,
       the run fails with the same message as with the dense LU.

  The step sequences of the two differ, and are not compared: on this model a
  change at the level of round-off, from either factorisation, moves a run by
  hundreds of steps either way. Measured against a run at rtol 1e-9, the two
  give the same errors.

      node resources/tests/facsimile/test-lu.js

  Exit status is 0 when every check passes.
*/
'use strict';
const path = require('path');

const jsDir = path.join(__dirname, '..', '..', 'js');
const FacsimileModel = require(path.join(jsDir, 'facsimile-model.js'));
const FacsimileODE = require(path.join(jsDir, 'facsimile-solver.js'));
const { FACSIMILE_DEFAULT_MODEL, FACSIMILE_PRESETS } = require(path.join(jsDir, 'facsimile-default.js'));

let checks = 0;
const failures = [];
function check(label, got, want = true) {
  checks++;
  const ok = got === want;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${got} (expected ${want})`}`);
  if (!ok) failures.push(label);
}

// --- 1. the iteration matrices of a real run ---------------------------------
const preset = FACSIMILE_PRESETS.find((p) => p.id === '13g');
const model = FacsimileModel.compile(FACSIMILE_DEFAULT_MODEL, { settings: preset.settings });
const n = model.nspecies;
const pattern = model.pattern;
const captured = [];
const formAndFactor = FacsimileODE.DenseLU.prototype.formAndFactor;
FacsimileODE.DenseLU.prototype.formAndFactor = function (a, pat, values, w, mass) {
  captured.push({ a, values: Float64Array.from(values), w: w ? Float64Array.from(w) : null });
  return formAndFactor.call(this, a, pat, values, w, mass);
};
FacsimileODE.runModel(model, {
  solver: 'ndf', matrix: 'dense', tend: preset.settings.TEND * 365.25 * 86400, rtol: preset.solver.rtol,
  atol: 1e-30, nonNegative: true, norm: 'max', maxOrder: 5,
});
FacsimileODE.DenseLU.prototype.formAndFactor = formAndFactor;

function denseMatrix(a, values, w) {
  const A = Array.from({ length: n }, () => new Float64Array(n));
  for (let j = 0; j < n; j++) {
    for (let q = pattern.colPtr[j]; q < pattern.colPtr[j + 1]; q++) {
      const i = pattern.rowIdx[q];
      A[i][j] = -a * values[q] * (w ? w[j] / w[i] : 1);
    }
  }
  for (let i = 0; i < n; i++) A[i][i] += 1;
  return A;
}
// ||A x - b|| / (||A|| ||x|| + ||b||), infinity norms.
function backwardError(A, x, b) {
  let r = 0, an = 0, xn = 0, bn = 0;
  for (let i = 0; i < n; i++) {
    let t = -b[i], rs = 0;
    for (let j = 0; j < n; j++) { t += A[i][j] * x[j]; rs += Math.abs(A[i][j]); }
    r = Math.max(r, Math.abs(t)); an = Math.max(an, rs); xn = Math.max(xn, Math.abs(x[i])); bn = Math.max(bn, Math.abs(b[i]));
  }
  return r / (an * xn + bn);
}
{
  const lu = new FacsimileODE.RefactorLU(pattern);
  const dense = new FacsimileODE.DenseLU(n);
  // A right-hand side spanning the orders of magnitude a Newton residual does.
  const b = Float64Array.from({ length: n }, (_, i) => Math.sin(1 + i) * 10 ** (-(i % 5) * 3));
  let declined = 0, worstKept = 0, worstDense = 0;
  for (const m of captured) {
    if (!lu.factor(m.a, m.values, m.w, null)) { declined++; continue; }
    dense.formAndFactor(m.a, pattern, m.values, m.w, null);
    const A = denseMatrix(m.a, m.values, m.w);
    worstKept = Math.max(worstKept, backwardError(A, lu.solve(b), b));
    worstDense = Math.max(worstDense, backwardError(A, dense.solve(b), b));
  }
  console.log(`      ${captured.length} matrices; pivots chosen again ${lu.repivots} times; `
    + `${lu.ops} multiply-adds and ${lu.nnz} entries per factor, against ${Math.round(n * n * n / 3)} and ${n * n} dense; `
    + `worst backward error ${worstKept.toExponential(2)} kept, ${worstDense.toExponential(2)} dense`);
  check(`every one of the ${captured.length} iteration matrices of case 13g factors without the dense LU`, declined, 0);
  check('its solutions are at round-off: backward error below 1e-15', worstKept < 1e-15);
  check('and no worse than ten times the dense LU\'s', worstKept <= 10 * Math.max(worstDense, 1e-17));
  check('it needs a small fraction of the dense LU\'s work', lu.ops < 0.15 * n * n * n / 3);
  check('the pivots are kept far more often than chosen again', lu.repivots < 0.25 * captured.length);
}

// --- 2. a pivot that collapses, a singular matrix, a NaN ----------------------
{
  // A full 3 x 3 pattern; with a = -1 and a zero mass, Mass - a*J is J itself.
  const full = { n: 3, nnz: 9, colPtr: Int32Array.from([0, 3, 6, 9]), rowIdx: Int32Array.from([0, 1, 2, 0, 1, 2, 0, 1, 2]) };
  const zeroMass = new Float64Array(3);
  const lu = new FacsimileODE.RefactorLU(full);
  const solveWith = (cols) => (lu.factor(-1, Float64Array.from(cols), null, zeroMass) ? Array.from(lu.solve(Float64Array.from([1, 2, 3]))) : null);
  const residual = (cols, x) => Math.max(...[0, 1, 2].map((i) => Math.abs(cols[i] * x[0] + cols[3 + i] * x[1] + cols[6 + i] * x[2] - (i + 1))));
  const first = [4, 1, 0, 1, 5, 1, 0, 1, 6];
  const x1 = solveWith(first);
  // Whichever entry was chosen as the first pivot collapses to 1e-9; every
  // column has another entry of at least 1 below it, so the kept pivot fails.
  const collapsed = first.slice();
  collapsed[lu.pc[0] * 3 + lu.pr[0]] = 1e-9;
  const before = lu.repivots;
  const x2 = solveWith(collapsed);
  check('a first matrix is solved exactly', x1 !== null && residual(first, x1) < 1e-15);
  check('a kept first pivot that collapses to 1e-9 is chosen again', lu.repivots - before, 1);
  check('and the matrix is still solved to round-off', x2 !== null && residual(collapsed, x2) < 1e-15);
  check('a singular matrix is declined, for the dense LU to report', solveWith([0, 0, 0, 0, 0, 0, 0, 0, 0]), null);
  check('so is one with a NaN in it', solveWith([NaN, 1, 0, 1, 5, 1, 0, 1, 6]), null);
  check('and after a decline the next matrix is chosen afresh and solved', (() => { const x = solveWith(first); return x !== null && residual(first, x) < 1e-15; })());
}

// --- 3. which path auto takes -------------------------------------------------
{
  const it = FacsimileODE.makeIterationMatrix(pattern, captured[0].values, 'auto', null);
  check('auto: the canister model, whose sparse factor fills in, gets the LU that keeps its pivots', it.info.lu, 'refactor');
  const build = (m, entries) => {
    const I = [], J = [], V = [];
    for (const [i, j, v] of entries) { I.push(i); J.push(j); V.push(v); }
    const T = FacsimileODE.cscFromTriplets(m, m, Int32Array.from(I), Int32Array.from(J), Float64Array.from(V));
    return { pattern: { n: m, nnz: T.nnz, colPtr: T.colptr, rowIdx: T.rowind }, values: T.values };
  };
  // A tridiagonal matrix: the kept pivots cost no more than the searching LU.
  const tri = [];
  for (let k = 0; k < 50; k++) for (const d of [-1, 0, 1]) if (k + d >= 0 && k + d < 50) tri.push([k, k + d, d === 0 ? -2 : 1]);
  const T = build(50, tri);
  check('auto: a tridiagonal matrix gets it too, since it costs no more', FacsimileODE.makeIterationMatrix(T.pattern, T.values, 'auto', null).info.lu, 'refactor');
  // A full matrix: n^3/3 whatever the order, no saving on the dense LU.
  const full = [];
  for (let i = 0; i < 120; i++) for (let j = 0; j < 120; j++) full.push([i, j, i === j ? -200 : Math.sin(i * 7 + j)]);
  const F = build(120, full);
  check('auto: a full matrix, where nothing is saved, goes to the dense LU', FacsimileODE.makeIterationMatrix(F.pattern, F.values, 'auto', null).info.lu, 'dense');
}

// --- 4. the singular message comes through unchanged --------------------------
{
  // y0' = -y0 + y1, and an algebraic y1 whose constraint reads nothing:
  // its row of Mass - a*J is zero, so the matrix is singular in column 1.
  const two = { n: 2, nnz: 2, colPtr: Int32Array.from([0, 1, 2]), rowIdx: Int32Array.from([0, 0]) };
  const values = Float64Array.from([-1, 1]);
  const mass = Float64Array.from([1, 0]);
  const message = (mode) => {
    const it = FacsimileODE.makeIterationMatrix(two, values, mode, mass);
    try { it.form(0.5, values, null); } catch (e) { return e.message; }
    return '';
  };
  const dense = message('dense');
  check('a constraint that does not determine its variable fails the same way with either LU', message('refactor'), dense);
  check('and the message is the one about the constraint', dense.includes('does not determine it'));
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) {
  console.log('failed:\n  ' + failures.join('\n  '));
  process.exit(1);
}
