#!/usr/bin/env node
/*
  The three factorisations everything else stands on.

  Checked by residual rather than against stored numbers: for a linear solve
  the residual ‖Ax − b‖ is the whole truth, and a factorisation that agrees
  with a stored answer to six digits on one matrix can still be wrong.

      node resources/tests/ode/julia/test-linalg.mjs
*/
import {
  DenseMatrix, CSC, cscFromTriplets, DenseLU, ComplexDenseLU, SparseLU,
  reverseCuthillMcKee, fillWeights, wrmsNorm, wmaxNorm,
} from '../../../js/ode/julia/core/linalg.js';

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
  checks++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `: ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

/** A deterministic pseudo-random source, so a failure can be reproduced. */
function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function denseResidual(A, x, b) {
  const n = A.n;
  let worst = 0;
  let scale = 0;
  for (let i = 0; i < n; i++) {
    let r = -b[i];
    for (let j = 0; j < n; j++) r += A.get(i, j) * x[j];
    worst = Math.max(worst, Math.abs(r));
    scale = Math.max(scale, Math.abs(b[i]));
  }
  return worst / (scale || 1);
}

/* --- dense LU --------------------------------------------------------------
   A well-conditioned random matrix, then one that needs pivoting badly: a
   zero leading pivot, which an unpivoted LU divides by. */
{
  const rand = rng(12345);
  for (const n of [1, 2, 5, 40]) {
    const A = DenseMatrix.zeros(n);
    for (let j = 0; j < n; j++) {
      for (let i = 0; i < n; i++) A.set(i, j, rand() - 0.5);
      A.set(j, j, A.get(j, j) + n);          // diagonally dominant
    }
    const b = Float64Array.from({ length: n }, () => rand() - 0.5);
    const lu = new DenseLU(n);
    check(`dense ${n}x${n} factorises`, lu.factor(A));
    const x = Float64Array.from(b);
    lu.solve(x);
    const r = denseResidual(A, x, b);
    check(`dense ${n}x${n} solves`, r < 1e-13, `residual ${r.toExponential(2)}`);
  }

  const A = DenseMatrix.zeros(3);
  // [[0,1,2],[1,0,1],[2,1,0]] -- the first pivot is zero.
  A.set(0, 1, 1); A.set(0, 2, 2);
  A.set(1, 0, 1); A.set(1, 2, 1);
  A.set(2, 0, 2); A.set(2, 1, 1);
  const b = Float64Array.from([3, 2, 3]);
  const lu = new DenseLU(3);
  lu.factor(A);
  const x = Float64Array.from(b);
  lu.solve(x);
  check('a zero leading pivot is pivoted around', denseResidual(A, x, b) < 1e-14);

  // A reversed-diagonal matrix: every step of the factorisation must pivot.
  for (const n of [6, 30]) {
    const rand2 = rng(5150 + n);
    const A2 = DenseMatrix.zeros(n);
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) A2.set(i, j, 0.01 * (rand2() - 0.5));
      A2.set(i, n - 1 - i, 1 + rand2());
    }
    const b2 = Float64Array.from({ length: n }, () => rand2() - 0.5);
    const lu2 = new DenseLU(n);
    lu2.factor(A2);
    const x2 = Float64Array.from(b2);
    lu2.solve(x2);
    const r2 = denseResidual(A2, x2, b2);
    check(`dense ${n}x${n} pivoting on every step`, r2 < 1e-12, `residual ${r2.toExponential(2)}`);
  }

  const S = DenseMatrix.zeros(3);
  S.set(0, 0, 1); S.set(1, 1, 1);            // column 2 is all zeros
  check('a singular matrix is reported, not divided by', new DenseLU(3).factor(S) === false);
}

/* --- complex dense LU ------------------------------------------------------
   The one RadauIIA5 needs. Checked against the equivalent real 2n x 2n system,
   which is a genuinely independent route to the same answer. */
{
  const rand = rng(999);
  const n = 12;
  const re = new Float64Array(n * n);
  const im = new Float64Array(n * n);
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      re[j * n + i] = rand() - 0.5;
      im[j * n + i] = rand() - 0.5;
    }
    re[j * n + j] += n;
    im[j * n + j] += n / 3;
  }
  const br = Float64Array.from({ length: n }, () => rand() - 0.5);
  const bi = Float64Array.from({ length: n }, () => rand() - 0.5);

  const clu = new ComplexDenseLU(n);
  check('complex factorises', clu.factor(re, im));
  const xr = Float64Array.from(br);
  const xi = Float64Array.from(bi);
  clu.solve(xr, xi);

  // (Re + i Im)(xr + i xi) = br + i bi, as a real system of twice the size.
  const R = DenseMatrix.zeros(2 * n);
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      R.set(i, j, re[j * n + i]);
      R.set(i, j + n, -im[j * n + i]);
      R.set(i + n, j, im[j * n + i]);
      R.set(i + n, j + n, re[j * n + i]);
    }
  }
  const rhs = new Float64Array(2 * n);
  rhs.set(br, 0); rhs.set(bi, n);
  const rlu = new DenseLU(2 * n);
  rlu.factor(R);
  const xreal = Float64Array.from(rhs);
  rlu.solve(xreal);
  let worst = 0;
  for (let i = 0; i < n; i++) {
    worst = Math.max(worst, Math.abs(xr[i] - xreal[i]), Math.abs(xi[i] - xreal[i + n]));
  }
  check('complex solve agrees with the real 2n system', worst < 1e-12,
        `worst ${worst.toExponential(2)}`);
}

/* --- sparse LU -------------------------------------------------------------
   A tridiagonal-plus-corners matrix: sparse enough that the factor should stay
   sparse, and awkward enough that the reach computation has to be right. */
function buildSparse(n, rand) {
  const rows = []; const cols = []; const vals = [];
  const push = (i, j, v) => { rows.push(i); cols.push(j); vals.push(v); };
  for (let i = 0; i < n; i++) {
    push(i, i, 4 + rand());
    if (i > 0) push(i, i - 1, -1 - rand() * 0.5);
    if (i < n - 1) push(i, i + 1, -1 - rand() * 0.5);
    if (i % 7 === 0 && i + 5 < n) push(i, i + 5, rand() * 0.3);
    if (i % 11 === 3 && i - 4 >= 0) push(i, i - 4, rand() * 0.3);
  }
  return cscFromTriplets(n, rows, cols, vals);
}

{
  const rand = rng(4242);
  for (const n of [1, 3, 30, 200]) {
    const A = buildSparse(n, rand);
    const b = Float64Array.from({ length: n }, () => rand() - 0.5);

    const slu = new SparseLU(n, A.colPtr, A.rowIdx);
    check(`sparse ${n} factorises`, slu.factor(A.colPtr, A.rowIdx, A.values));
    const x = Float64Array.from(b);
    slu.solve(x);
    const Ax = new Float64Array(n);
    A.apply(x, Ax);
    let worst = 0;
    let scale = 0;
    for (let i = 0; i < n; i++) {
      worst = Math.max(worst, Math.abs(Ax[i] - b[i]));
      scale = Math.max(scale, Math.abs(b[i]));
    }
    check(`sparse ${n} solves`, worst / (scale || 1) < 1e-12,
          `residual ${(worst / (scale || 1)).toExponential(2)}`);

    // and the same answer as the dense factorisation of the same matrix
    const D = A.toDense();
    const dlu = new DenseLU(n);
    dlu.factor(D);
    const xd = Float64Array.from(b);
    dlu.solve(xd);
    let diff = 0;
    for (let i = 0; i < n; i++) diff = Math.max(diff, Math.abs(x[i] - xd[i]));
    check(`sparse ${n} agrees with dense`, diff < 1e-11, `worst ${diff.toExponential(2)}`);
  }
}

/* --- pivoting, where it is actually needed ---------------------------------
   Every sparse matrix above is diagonally dominant, so no interchange ever
   happens and a solve that mishandles them still passes. These do not have
   that luxury: the diagonal is zero. */
{
  const rand = rng(31337);
  for (const n of [4, 25]) {
    const rows = []; const cols = []; const vals = [];
    for (let i = 0; i < n; i++) {
      rows.push(i); cols.push(i); vals.push(0);              // an empty diagonal
      rows.push(i); cols.push((i + 1) % n); vals.push(1 + rand());
      rows.push((i + 1) % n); cols.push(i); vals.push(1 + rand());
      if (n > 4) { rows.push(i); cols.push((i + 7) % n); vals.push(rand() * 0.4); }
    }
    const A = cscFromTriplets(n, rows, cols, vals);
    const b = Float64Array.from({ length: n }, () => rand() - 0.5);

    const slu = new SparseLU(n, A.colPtr, A.rowIdx);
    check(`sparse ${n} with a zero diagonal factorises`, slu.factor(A.colPtr, A.rowIdx, A.values));
    const x = Float64Array.from(b);
    slu.solve(x);
    const Ax = new Float64Array(n);
    A.apply(x, Ax);
    let worst = 0;
    for (let i = 0; i < n; i++) worst = Math.max(worst, Math.abs(Ax[i] - b[i]));
    check(`sparse ${n} with a zero diagonal solves`, worst < 1e-11,
          `residual ${worst.toExponential(2)}`);

    const dlu = new DenseLU(n);
    dlu.factor(A.toDense());
    const xd = Float64Array.from(b);
    dlu.solve(xd);
    let diff = 0;
    for (let i = 0; i < n; i++) diff = Math.max(diff, Math.abs(x[i] - xd[i]));
    check(`and dense agrees on the same pivoting`, diff < 1e-10, `worst ${diff.toExponential(2)}`);
  }
}

/* --- the orderings ------------------------------------------------------- */
{
  const rand = rng(777);
  const n = 200;
  const A = buildSparse(n, rand);
  const perm = reverseCuthillMcKee(n, A.colPtr, A.rowIdx);
  const seen = new Set(perm);
  check('RCM is a permutation', seen.size === n && Math.min(...perm) === 0 && Math.max(...perm) === n - 1);

  const b = Float64Array.from({ length: n }, () => rand() - 0.5);
  const plain = new SparseLU(n, A.colPtr, A.rowIdx);
  plain.factor(A.colPtr, A.rowIdx, A.values);
  const ordered = new SparseLU(n, A.colPtr, A.rowIdx, perm);
  check('a reordered factorisation still factorises', ordered.factor(A.colPtr, A.rowIdx, A.values));
  const x = Float64Array.from(b);
  ordered.solve(x);
  const Ax = new Float64Array(n);
  A.apply(x, Ax);
  let worst = 0;
  for (let i = 0; i < n; i++) worst = Math.max(worst, Math.abs(Ax[i] - b[i]));
  check('and solves the original system', worst < 1e-11, `residual ${worst.toExponential(2)}`);
  console.log(`      fill: ${plain.fill} unordered, ${ordered.fill} with RCM, ${n * n} dense`);
}

/* Several components, the vertices of least degree after a connected block.
   The ordering used to start each component at the least degree from its
   scan position and move on by one either way, so here it took the six
   isolated vertices one per step, walked past the chain, and returned zeros
   where the chain should have been: not a permutation, and the factorisation
   through it reported the matrix singular. */
{
  const m = 12;
  const rows = []; const cols = []; const vals = [];
  for (let i = 0; i < m; i++) {
    rows.push(i); cols.push(i); vals.push(3 + i);
    if (i < 5) {
      rows.push(i + 1); cols.push(i); vals.push(-1);
      rows.push(i); cols.push(i + 1); vals.push(-0.5);
    }
  }
  const B = cscFromTriplets(m, rows, cols, vals);
  const q = reverseCuthillMcKee(m, B.colPtr, B.rowIdx);
  check('RCM is a permutation with isolated vertices after a connected block',
        new Set(q).size === m && Math.min(...q) === 0 && Math.max(...q) === m - 1, Array.from(q).join(','));
  const lu = new SparseLU(m, B.colPtr, B.rowIdx, q);
  check('and the factorisation through it succeeds', lu.factor(B.colPtr, B.rowIdx, B.values));
  const b = Float64Array.from({ length: m }, (_, i) => 1 + (i % 4));
  const x = Float64Array.from(b);
  lu.solve(x);
  const Bx = new Float64Array(m);
  B.apply(x, Bx);
  let worst = 0;
  for (let i = 0; i < m; i++) worst = Math.max(worst, Math.abs(Bx[i] - b[i]));
  check('and solves the system', worst < 1e-12, `residual ${worst.toExponential(2)}`);
}

/* --- norms ---------------------------------------------------------------- */
{
  const w = new Float64Array(4);
  fillWeights(w, [1, 2, 3, 4], [0, 0, 0, 0], 0.1, 1e-3);
  check('weights are atol + rtol*max(|u|,|uprev|)', Math.abs(w[2] - (1e-3 + 0.3)) < 1e-15);
  const e = Float64Array.from([w[0], 0, 0, 0]);
  check('wrms of one unit error over four is 1/2', Math.abs(wrmsNorm(e, w) - 0.5) < 1e-15);
  check('wmax of the same is 1', Math.abs(wmaxNorm(e, w) - 1) < 1e-15);
  const wa = new Float64Array(2);
  fillWeights(wa, [1, 1], [1, 1], 0, [1, 2]);
  check('a per-component atol is honoured', wa[0] === 1 && wa[1] === 2);
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) console.log('failed: ' + failures.join(', '));
process.exit(failures.length ? 1 : 0);
