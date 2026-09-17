#!/usr/bin/env node
/*
  The observed order of convergence of every method in the package.

  This is the test that proves a tableau was transcribed correctly, and the
  only one that does. A Rosenbrock or Runge-Kutta method with one mistyped
  coefficient does not crash, does not report an error, and does not fail any
  reasonable accuracy check against a reference solution at loose tolerance.
  It just quietly loses its order. So: run it at a fixed step on a problem
  whose exact solution is known, halve the step, and watch the error. If the
  method is order p the error must fall by 2^p each time, and if it does for
  four halvings then every coefficient that carries order is right.

      node resources/tests/ode_julia/test-order.mjs

  Exit status is 0 when every method shows its advertised order.
*/
import { solve, ODEProblem } from '../../js/ode_julia/core/integrator.js';
import * as alg from '../../js/ode_julia/index.js';
import { manufactured } from './problems.mjs';

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
  checks++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `: ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

/**
 * Global error at the end of the span, at a fixed step.
 *
 * The Newton iteration is held to a far tighter tolerance than anything a real
 * run would use, because what is being measured is the truncation error of the
 * formula and nothing else. Left at its default, the Newton's own stopping
 * criterion puts a floor under the error -- for RadauIIA5, which works to
 * Hairer's deliberately loosened internal tolerance, that floor is around
 * 5e-13 and the measured order falls away beneath it, saying nothing about the
 * tableau.
 */
function errorAt(algorithm, dt, useJac) {
  const p = manufactured;
  const prob = new ODEProblem(p.f, p.u0, p.tspan,
    useJac ? { jac: p.jac, tgrad: p.tgrad } : {});
  const sol = solve(prob, algorithm, {
    adaptive: false, dt, saveEverystep: false, reltol: 1e-14, abstol: 1e-14,
    kappa: 1e-10, newtonMaxIters: 50, maxJacAge: 1,
  });
  if (sol.retcode !== 'Success') return { err: NaN, retcode: sol.retcode, message: sol.message };
  const exact = p.exact(p.tspan[1]);
  const got = sol.final;
  let e = 0;
  for (let i = 0; i < p.n; i++) e = Math.max(e, Math.abs(got[i] - exact[i]));
  return { err: e, retcode: sol.retcode };
}

/**
 * Four halvings, and the slope of log(error) against log(dt).
 *
 * The step range is chosen per method so that the coarse end is not so big
 * that the asymptotic rate has not set in, and the fine end not so small that
 * rounding dominates -- for a fifth-order method at dt = 1e-3 the error is
 * already near 1e-14 and the measurement becomes noise.
 */
function measureOrder(algorithm, name, expected, dt0, useJac) {
  const dts = [dt0, dt0 / 2, dt0 / 4, dt0 / 8, dt0 / 16];
  const errs = [];
  for (const dt of dts) {
    const r = errorAt(algorithm, dt, useJac);
    if (!Number.isFinite(r.err)) {
      check(`${name}: runs at dt = ${dt}`, false, r.message || r.retcode);
      return;
    }
    errs.push(r.err);
  }
  const rates = [];
  for (let i = 1; i < errs.length; i++) {
    rates.push(errs[i - 1] > 0 && errs[i] > 0 ? Math.log2(errs[i - 1] / errs[i]) : NaN);
  }
  const shown = errs.map((e) => e.toExponential(2)).join(' -> ');
  const rateStr = rates.map((r) => r.toFixed(2)).join(', ');
  console.log(`      ${name}${useJac ? ' (exact J and df/dt)' : ' (both differenced)'}: ${shown}`);
  console.log(`      rates: ${rateStr}`);
  // The last two halvings are the asymptotic ones; the first can still be
  // pre-asymptotic on a nonlinear problem.
  const best = Math.max(...rates.slice(-2).filter(Number.isFinite));
  check(`${name} converges at order ${expected}${useJac ? '' : ' with derivatives differenced'}`,
        best >= expected - 0.45, `best observed ${best.toFixed(2)}`);
}

const cases = [
  ['Rodas5P', alg.Rodas5P(), 5, 0.2],
  ['TRBDF2', alg.TRBDF2(), 2, 0.2],
  ['KenCarp4', alg.KenCarp4(), 4, 0.2],
  ['RadauIIA5', alg.RadauIIA5(), 5, 0.2],
];
for (const [name, a, order, dt0] of cases) {
  if (!a) continue;
  measureOrder(a, name, order, dt0, true);
  measureOrder(a, name, order, dt0, false);
}

/* --- the variable-order method, pinned to each order in turn ---------------
   A k-step BDF has nothing to be order k with until it has k past points, so
   started cold its first steps are order 1 and 2 and the measurement sees
   those and not the formula. Seeded with the exact solution at the k points
   before t₀, each order can be measured on its own. */
for (const [label, make] of [['FBDF', (k) => alg.FBDF({ maxOrder: k, minOrder: k })],
  ['QNDF', (k) => alg.QNDF({ maxOrder: k, minOrder: k })],
  ['QBDF', (k) => alg.QBDF({ maxOrder: k, minOrder: k })]]) {
console.log(`\n--- ${label}, one order at a time, history seeded from the exact solution ---`);
for (let k = 1; k <= 5; k++) {
  const p = manufactured;
  const dt0 = 0.2;
  const errs = [];
  const dts = [dt0, dt0 / 2, dt0 / 4, dt0 / 8, dt0 / 16];
  let failed = null;
  for (const dt of dts) {
    const hist = { t: [], u: [] };
    for (let j = 1; j <= k; j++) {
      hist.t.push(p.tspan[0] - j * dt);
      hist.u.push(p.exact(p.tspan[0] - j * dt));
    }
    const prob = new ODEProblem(p.f, p.u0, p.tspan, { jac: p.jac });
    const sol = solve(prob, make(k), {
      adaptive: false, dt, saveEverystep: false, reltol: 1e-14, abstol: 1e-14,
      history: hist, kappa: 1e-10, newtonMaxIters: 50, maxJacAge: 1,
    });
    if (sol.retcode !== 'Success') { failed = sol.message || sol.retcode; break; }
    const exact = p.exact(p.tspan[1]);
    let e = 0;
    for (let i = 0; i < p.n; i++) e = Math.max(e, Math.abs(sol.final[i] - exact[i]));
    errs.push(e);
  }
  if (failed) { check(`${label} at order ${k} runs`, false, failed); continue; }
  const rates = errs.slice(1).map((e, i) => Math.log2(errs[i] / e));
  console.log(`      order ${k}: ${errs.map((e) => e.toExponential(2)).join(' -> ')}`);
  console.log(`      rates: ${rates.map((r) => r.toFixed(2)).join(', ')}`);
  const best = Math.max(...rates.slice(-2).filter(Number.isFinite));
  check(`${label} at order ${k} converges at order ${k}`, best >= k - 0.4,
        `best observed ${best.toFixed(2)}`);
}
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) console.log('failed: ' + failures.join(', '));
process.exit(failures.length ? 1 : 0);
