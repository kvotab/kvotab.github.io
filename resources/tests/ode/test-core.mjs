#!/usr/bin/env node
/*
  The solver core shared by facsimile.html, rtm.html and Kompartment
  (resources/js/ode/core/ and solvers/), checked on its own.

      node resources/tests/ode/test-core.mjs

  1. The single-file build is the modules: the same run through each gives the
     same bits.
  2. facsimile-solver.js's `saveAt` comes out as it always did: times at or
     before the start are the starting state, a time past the end is dropped,
     a repeated time is repeated.
  3. The four iteration-matrix modes give the LU they name, and `auto` takes
     each page's measurements of when a dense LU is cheaper.
  4. Every shape of Jacobian is accepted, and a pattern without values is
     differenced through its colouring.
  5. Each way of failing has its code.
  6. An event that has been switched off is not reported.
  7. A floating absolute tolerance handed over as a Float64Array keeps its
     high-water mark in that array.

  The pages' own suites are what check the numbers against references:
  resources/tests/facsimile/, resources/tests/rtm/ and kompartment/test/.
  Exit status is 0 when every check passes.
*/
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as core from '../../js/ode/index.js';

const require = createRequire(import.meta.url);
const jsDir = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'js');
const bundle = require(join(jsDir, 'ode-core.js'));
const FacsimileODE = require(join(jsDir, 'facsimile-solver.js'));

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
  checks++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok || !detail ? '' : `: ${detail}`}`);
  if (!ok) failures.push(label);
}
function throws(fn) {
  try { fn(); } catch (e) { return e; }
  return null;
}

// Robertson's problem, with its analytic Jacobian as the values of a pattern.
const robertson = {
  f: (t, y, out) => {
    out[0] = -0.04 * y[0] + 1e4 * y[1] * y[2];
    out[1] = 0.04 * y[0] - 1e4 * y[1] * y[2] - 3e7 * y[1] * y[1];
    out[2] = 3e7 * y[1] * y[1];
    return out;
  },
  // Columns 0, 1, 2; every entry present.
  pattern: { n: 3, nnz: 9, colPtr: Int32Array.of(0, 3, 6, 9), rowIdx: Int32Array.of(0, 1, 2, 0, 1, 2, 0, 1, 2) },
  values: new Float64Array(9),
  evaluate(t, y) {
    const v = robertson.values;
    v[0] = -0.04; v[1] = 0.04; v[2] = 0;
    v[3] = 1e4 * y[2]; v[4] = -1e4 * y[2] - 6e7 * y[1]; v[5] = 6e7 * y[1];
    v[6] = 1e4 * y[1]; v[7] = -1e4 * y[1]; v[8] = 0;
    return v;
  },
};
const buf = new Float64Array(1);
const bits = new Uint32Array(buf.buffer);
function hash(rows) {
  let h = 2166136261;
  for (const row of rows) {
    for (const v of row) {
      buf[0] = v + 0;
      h = Math.imul(h ^ bits[0], 16777619) >>> 0;
      h = Math.imul(h ^ bits[1], 16777619) >>> 0;
    }
  }
  return h;
}

// --- 1. the build is the modules -----------------------------------------------
{
  const run = (api, opts) => api.ndf(robertson.f, [0, 0.4, 40, 4e5], Float64Array.of(1, 0, 0), {
    rtol: 1e-6, abstol: [1e-8, 1e-14, 1e-6],
    jacobian: { pattern: robertson.pattern, evaluate: (t, y) => robertson.evaluate(t, y) },
    ...opts,
  });
  for (const [label, opts] of [
    ['auto', {}], ['refactor', { matrix: 'refactor' }], ['sparse', { matrix: 'sparse' }],
    ['dense', { matrix: 'dense' }], ['scaled, two Newton iterations', { scaling: true, minNewton: 2, denseBelow: 0, denseFill: 0.35 }],
  ]) {
    const a = run(core, opts);
    const b = run(bundle, opts);
    check(`the bundle and the modules give the same bits: ${label}`,
      hash(a.y) === hash(b.y) && a.stats.nsteps === b.stats.nsteps, `${a.stats.nsteps} against ${b.stats.nsteps} steps`);
  }
  const res = run(core, {});
  // Hindmarsh's published values at t = 4e5.
  const want = [4.9394e-3, 1.9854e-8, 0.99506];
  const y = res.y[res.y.length - 1];
  check('Robertson at t = 4e5 is the published answer', want.every((w, i) => Math.abs(y[i] / w - 1) < 2e-3),
    Array.from(y).map((v) => v.toExponential(4)).join(' '));
  check('and the three still add up to one', Math.abs(y[0] + y[1] + y[2] - 1) < 1e-9);
}

// --- 2. facsimile-solver.js's saveAt ------------------------------------------
{
  const f = (t, y, out) => { out[0] = -y[0]; return out; };
  const jacobian = { pattern: { n: 1, nnz: 1, colPtr: Int32Array.of(0, 1), rowIdx: Int32Array.of(0) }, evaluate: () => Float64Array.of(-1) };
  const saveAt = [-1, 0, 0.5, 1, 2, 2, 3];
  const res = FacsimileODE.ndf(f, 0, 2, Float64Array.of(1), { rtol: 1e-8, atol: 1e-12, jacobian, saveAt });
  const T = Array.from(res.series.t);
  check('saveAt: the times asked for, those past the end left out', JSON.stringify(T) === JSON.stringify([-1, 0, 0.5, 1, 2, 2]), JSON.stringify(T));
  check('  a time at or before the start is the starting state', res.series.y[0][0] === 1 && res.series.y[1][0] === 1);
  check('  and a time inside the run is the solution there', Math.abs(res.series.y[2][0] - Math.exp(-0.5)) < 1e-7);
  check('  a repeated end time is repeated, and is the end state', res.series.y[4][0] === res.y[0] && res.series.y[5][0] === res.y[0]);
  check('  and the end is the end', res.t === 2 && Math.abs(res.y[0] - Math.exp(-2)) < 1e-7);
  const none = FacsimileODE.ndf(f, 0, 2, Float64Array.of(1), { rtol: 1e-8, atol: 1e-12, jacobian });
  check('no saveAt, no series', none.series === null && none.y[0] === res.y[0]);
}

// --- 3. the iteration matrix -------------------------------------------------------
{
  const tridiagonal = (m) => {
    const I = [], J = [], V = [];
    for (let k = 0; k < m; k++) for (const d of [-1, 0, 1]) if (k + d >= 0 && k + d < m) { I.push(k); J.push(k + d); V.push(d === 0 ? -2 : 1); }
    const T = core.cscFromTriplets(m, m, Int32Array.from(I), Int32Array.from(J), Float64Array.from(V));
    return { pattern: { n: m, nnz: T.nnz, colPtr: T.colptr, rowIdx: T.rowind }, values: T.values };
  };
  const big = tridiagonal(50);
  const lu = (mode, extra = {}) => core.iterationMatrix(big.pattern, big.values, { mode, ...extra }).info.lu;
  check('auto on a tridiagonal matrix: the LU that keeps its pivots', lu('auto') === 'refactor', lu('auto'));
  check('refactor, sparse and dense are what they say',
    lu('refactor') === 'refactor' && lu('sparse') === 'sparse' && lu('dense') === 'dense', `${lu('refactor')} ${lu('sparse')} ${lu('dense')}`);
  const small = tridiagonal(10);
  check('auto below 24 equations is dense, as Kompartment measured it',
    core.iterationMatrix(small.pattern, small.values).info.lu === 'dense');
  check('and sparse from the start with facsimile.html\'s measurements',
    core.makeIterationMatrix(small.pattern, small.values, 'auto', null).info.lu === 'refactor');
  // Every mode solves the same system.
  const b = Float64Array.from({ length: 50 }, (_, i) => Math.sin(i + 1));
  const x = {};
  for (const mode of ['refactor', 'sparse', 'dense']) {
    const m = core.iterationMatrix(big.pattern, big.values, { mode });
    m.form(0.3, big.values, null, null);
    x[mode] = m.solve(b, new Float64Array(50));
  }
  const worst = Math.max(...x.dense.map((v, i) => Math.max(Math.abs(v - x.sparse[i]), Math.abs(v - x.refactor[i]))));
  check('and the three LUs solve I - a*J alike', worst < 1e-13, worst);
  const K = core.sparseIterationMatrix(50, big.pattern, big.values);
  check('Kompartment\'s entry answers with the sparse matrix auto chose', K && K.lu === 'refactor');
  check('  and null where auto chose the dense one', core.sparseIterationMatrix(10, small.pattern, small.values) === null);
  // I - 1*diag(0.5, 1) is singular in its second column; with the second
  // state algebraic and its constraint reading only the first, so is the
  // matrix of the second pattern; and a NaN is a NaN.
  const diagonal = { n: 2, nnz: 2, colPtr: Int32Array.of(0, 1, 2), rowIdx: Int32Array.of(0, 1) };
  const holey = { n: 2, nnz: 2, colPtr: Int32Array.of(0, 1, 2), rowIdx: Int32Array.of(0, 0) };
  const said = (pattern, mode, values, mass) => {
    const m = core.iterationMatrix(pattern, values, { mode, mass, hints: { singular: 'Here is why.' } });
    const e = throws(() => m.form(1, values, null, null));
    return e ? e.message : '';
  };
  for (const mode of ['sparse', 'refactor', 'dense']) {
    const msg = said(diagonal, mode, Float64Array.of(0.5, 1), null);
    check(`a singular matrix says where, with the page's sentence: ${mode}`, /I - h\*J is singular at column 1\. Here is why\./.test(msg), msg);
  }
  check('an algebraic column says its constraint does not determine it',
    /does not determine it/.test(said(holey, 'dense', Float64Array.of(-1, 1), Float64Array.of(1, 0))));
  check('an entry that is not a number is refused, not solved with',
    /not a number/.test(said(holey, 'dense', Float64Array.of(NaN, 1), null)));
}

// --- 4. the shapes of Jacobian ---------------------------------------------------
{
  const f = (t, y, out) => { out[0] = -y[0] + y[1]; out[1] = -2 * y[1]; return out; };
  const exact = (t) => [Math.exp(-t) + (Math.exp(-t) - Math.exp(-2 * t)), Math.exp(-2 * t)];
  const pattern = { n: 2, nnz: 3, colPtr: Int32Array.of(0, 1, 3), rowIdx: Int32Array.of(0, 0, 1) };
  const shapes = {
    'none (differenced densely)': null,
    'an array of rows': [[-1, 1], [0, -2]],
    'a function': () => [Float64Array.of(-1, 1), Float64Array.of(0, -2)],
    'a pattern with values': { pattern, evaluate: () => Float64Array.of(-1, 1, -2) },
    'a pattern alone (differenced)': { pattern },
    'dense rows filled in place': { evaluateDense: (t, y, rows) => { rows[0][0] = -1; rows[0][1] = 1; rows[1][0] = 0; rows[1][1] = -2; return rows; } },
  };
  for (const [label, jacobian] of Object.entries(shapes)) {
    const res = core.ndf(f, [0, 1, 3], Float64Array.of(1, 1), { rtol: 1e-8, abstol: 1e-12, jacobian });
    const y = res.y[2];
    const e = exact(3);
    check(`Jacobian as ${label}`, Math.abs(y[0] - e[0]) < 1e-6 && Math.abs(y[1] - e[1]) < 1e-6,
      `${y[0]} ${y[1]} against ${e[0]} ${e[1]}`);
  }
  const bad = throws(() => core.ndf(f, [0, 1], Float64Array.of(1, 1), { jacobian: { values: 1 } }));
  check('and anything else is refused by name', bad && bad.code === 'jacobian');
}

// --- 5. the ways of failing ---------------------------------------------------------
{
  const decay = (t, y, out) => { out[0] = -y[0]; return out; };
  const code = (fn) => { const e = throws(fn); return e ? e.code : 'none'; };
  check('equal start and end: span', code(() => core.ndf(decay, [1, 1], Float64Array.of(1))) === 'span');
  check('a derivative that is not a number: nonfinite', code(() => core.ndf(() => [NaN], [0, 1], Float64Array.of(1))) === 'nonfinite');
  check('the step budget: steps', code(() => core.ndf(decay, [0, 1e6], Float64Array.of(1), { maxSteps: 5, hmax: 1 })) === 'steps');
  check('a Jacobian with a NaN: singular, saying not a number',
    (() => { const e = throws(() => core.ndf(decay, [0, 1], Float64Array.of(1), { jacobian: [[NaN]] })); return e && e.code === 'singular' && /not a number/.test(e.message); })());
  const stopped = throws(() => core.ndf(decay, [0, 10], Float64Array.of(1), { onStep: () => false }));
  check('onStep answering false: aborted', stopped && stopped.code === 'aborted');
  const e = throws(() => core.ndf(decay, [0, 1e6], Float64Array.of(1), { maxSteps: 30, hmax: 1 }));
  check('and a failure inside the run carries its last steps', e && Array.isArray(e.trace) && e.trace.length === 12 && e.lastY instanceof Float64Array);
  check('Kompartment\'s name for the error is the same class', core.NdfFailure === core.SolverError && e instanceof core.NdfFailure);
}

// --- 6. an event switched off --------------------------------------------------------
{
  const clock = (t, y, out) => { out[0] = 1; return out; };
  const events = (enabled) => ({
    n: 2, direction: Int8Array.of(1, 1), enabled,
    fun: (t, y, out) => { out[0] = y[0] - 2; out[1] = y[0] - 5; return out; },
  });
  const on = core.ndf(clock, [0, 10], Float64Array.of(0), { rtol: 1e-8, abstol: 1e-12, events: events(Uint8Array.of(1, 1)) });
  const off = core.ndf(clock, [0, 10], Float64Array.of(0), { rtol: 1e-8, abstol: 1e-12, events: events(Uint8Array.of(0, 1)) });
  check('the first event stops the run at its crossing', on.stopped && on.stopped.which[0] === 0 && Math.abs(on.stopped.t - 2) < 1e-9, on.stopped && on.stopped.t);
  check('switched off, the next one does', off.stopped && off.stopped.which[0] === 1 && Math.abs(off.stopped.t - 5) < 1e-9, off.stopped && off.stopped.t);
}

// --- 7. a floating tolerance kept by the caller ----------------------------------------
{
  const grow = (t, y, out) => { out[0] = y[0]; return out; };
  const abstol = Float64Array.of(1e-10);
  core.ndf(grow, [0, 5], Float64Array.of(1), { rtol: 1e-6, abstol, autoAbstol: true });
  check('autoAbstol raises a Float64Array abstol in place, to rtol·|y| at the end',
    Math.abs(abstol[0] / (1e-6 * Math.exp(5)) - 1) < 1e-4, abstol[0]);
  const plain = [1e-10];
  core.ndf(grow, [0, 5], Float64Array.of(1), { rtol: 1e-6, abstol: plain, autoAbstol: true });
  check('and never touches a plain array', plain[0] === 1e-10);
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) {
  console.log('failed:\n  ' + failures.join('\n  '));
  process.exit(1);
}
