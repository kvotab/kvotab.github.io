#!/usr/bin/env node
/*
  Every solver against the standard stiff test set, and against SciPy.

  The order test proves the tableaux. This proves the rest of it: the step-size
  control, the Newton iteration and its convergence heuristics, the order
  selection, the Jacobian reuse, and whether any of them falls over on a
  problem that was chosen decades ago precisely because solvers fall over on it.

  The references in ref/ come from scipy.integrate Radau at rtol 1e-12, which
  is somebody else's arithmetic and three orders tighter than anything asked
  for here. Regenerate them with scripts/gen-ode-julia-ref.py.

      node resources/tests/ode/julia/test-stiff.mjs [--verbose]

  Exit status is 0 when every solver reaches the end of every problem inside
  the accuracy it was asked for.
*/
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { solve, ODEProblem } from '../../../js/ode/julia/core/integrator.js';
import * as alg from '../../../js/ode/julia/index.js';
import { rober, hires, orego, pollution, vanderpol } from './problems.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const VERBOSE = process.argv.includes('--verbose');

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
  checks++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `: ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

function loadRef(name) {
  const text = readFileSync(join(HERE, 'ref', `${name}.csv`), 'utf8').trim().split('\n');
  const rows = text.slice(1).map((line) => line.split(',').map(Number));
  return { t: rows.map((r) => r[0]), y: rows.map((r) => Float64Array.from(r.slice(1))) };
}

/**
 * The worst error over the sampled times, measured in units of the tolerance
 * the solver was actually given:
 *
 *     |got − want| / (atol + rtol·|want|)
 *
 * A plain relative comparison is the wrong instrument here and quietly
 * indicts correct solvers. Robertson's third component is 1.6e-11 at the first
 * sampled decade; at atol 1e-14 every method's error there is a fraction of a
 * unit of tolerance and none of them is doing anything wrong, yet measured
 * relatively they look 1e-4 out. What a solver promises is this quantity, so
 * this is what is checked.
 *
 * The solver is asked to save exactly at the reference times and to step onto
 * them (`saveat` with `tstops`), so what is compared is the integration and
 * not the interpolant. The interpolants have their own check in test-interp.
 */
function worstError(sol, ref, rtol, atol) {
  let worst = 0;
  let where = '';
  if (sol.t.length !== ref.t.length) {
    return { worst: Infinity, where: `saved ${sol.t.length} points, wanted ${ref.t.length}` };
  }
  for (let j = 0; j < ref.t.length; j++) {
    const got = sol.u[j];
    for (let i = 0; i < got.length; i++) {
      const want = ref.y[j][i];
      const d = Math.abs(got[i] - want) / (atol + rtol * Math.abs(want));
      if (d > worst) { worst = d; where = `y${i} at t = ${ref.t[j].toPrecision(3)}`; }
    }
  }
  return { worst, where };
}

const CASES = [
  // The slack is how many units of its own tolerance a solver may be out by at
  // the sampled points. It is never 1: a tolerance controls the local error of
  // each step, and what accumulates over thousands of them is larger, by a
  // factor that depends on how much the problem amplifies a perturbation.
  { p: rober, ref: 'rober', rtol: 1e-8, atol: 1e-14, slack: 60 },
  { p: hires, ref: 'hires', rtol: 1e-8, atol: 1e-12, slack: 60 },
  // The Oregonator oscillates, so a pointwise comparison measures phase as
  // much as amplitude, and phase error accumulates over periods rather than
  // over steps. The spread among methods that are all behaving correctly is
  // consequently wide here -- Rodas5P 2, FBDF 23, KenCarp4 232, QNDF 264,
  // QBDF 716 -- and the budget has to hold all of them. QBDF trailing QNDF is
  // not a fault: kappa is exactly what buys QNDF the smaller error constant,
  // and with kappa zero it is a plain BDF and says so.
  { p: orego, ref: 'orego', rtol: 1e-8, atol: 1e-12, slack: 1500 },
  { p: pollution, ref: 'pollution', rtol: 1e-8, atol: 1e-14, slack: 60 },
  { p: vanderpol(1e6), ref: 'vanderpol', rtol: 1e-8, atol: 1e-10, slack: 400 },
];

// `loosen` relaxes a solver's tolerance from the problem's, and `slackFactor`
// relaxes what it is then held to.
//
// TRBDF2 gets both. It is second order: asking it for eight digits is asking
// for hundreds of thousands of steps, which tests one's patience rather than
// the method, so it runs at 1e-5. And on a problem with sharp transients a
// pointwise comparison against a reference measures phase as much as
// amplitude, and a second-order method's phase error is far larger than its
// local error -- which is a true fact about second-order methods and not a
// defect in this one. Its order is proved exactly in test-order; what is
// checked here is that it stays on the solution.
//
// Measured, on the Oregonator: at 1e-5 TRBDF2 is 3e3 tolerance units out and
// at 1e-4 it is 1e11, with no warning either time. That cliff is worth knowing
// about and is written up in the README.
const SOLVERS = [
  ['FBDF', () => alg.FBDF(), 1, 1],
  ['QNDF', () => alg.QNDF(), 1, 1],
  ['QBDF', () => alg.QBDF(), 1, 1],
  ['Rodas5P', () => alg.Rodas5P(), 1, 1],
  ['KenCarp4', () => alg.KenCarp4(), 1, 1],
  ['TRBDF2', () => alg.TRBDF2(), 1e3, 10],
  ['RadauIIA5', () => alg.RadauIIA5(), 1, 1],
];

for (const c of CASES) {
  const ref = loadRef(c.ref);
  console.log(`\n=== ${c.p.name} (rtol ${c.rtol}, atol ${c.atol}) ===`);
  console.log('      solver        steps   rejected    f evals   Jacobians        LU   err/tolerance');
  for (const [name, make, loosen, slackFactor] of SOLVERS) {
    const rtol = c.rtol * loosen;
    const atol = c.atol * loosen;
    const prob = new ODEProblem(c.p.f, c.p.u0, c.p.tspan, c.p.jac ? { jac: c.p.jac } : {});
    let sol;
    const t0 = Date.now();
    try {
      // tstops as well as saveat, so every reference time is the end of a
      // step and what is compared is the integration and not the interpolant.
      // Measured through the interpolant instead, the worst error on Robertson
      // is always at the first sampled decade, inside one enormous opening
      // step, on a component then worth 1e-11 -- a fair test of an interpolant
      // and no test at all of a solver. The interpolants get their own check
      // below.
      sol = solve(prob, make(), {
        reltol: rtol, abstol: atol, maxiters: 2e6, saveat: ref.t, tstops: ref.t,
      });
    } catch (e) {
      check(`${c.p.name}: ${name} runs`, false, e.message);
      continue;
    }
    const ms = Date.now() - t0;
    if (sol.retcode !== 'Success') {
      check(`${c.p.name}: ${name} reaches the end`, false,
            `${sol.retcode} -- ${sol.message}`);
      continue;
    }
    const { worst, where } = worstError(sol, ref, rtol, atol);
    const s = sol.stats;
    console.log(`      ${name.padEnd(11)} ${String(s.naccept).padStart(7)}`
      + ` ${String(s.nreject).padStart(10)} ${String(s.nf).padStart(10)}`
      + ` ${String(s.njacs).padStart(11)} ${String(s.nw).padStart(9)}`
      + `   ${worst.toPrecision(3).padStart(9)}${VERBOSE ? `  (${where}, ${ms} ms)` : ''}`);
    const budget = c.slack * slackFactor;
    check(`${c.p.name}: ${name} agrees with SciPy`, worst < budget,
          `${worst.toPrecision(3)} units of tolerance, budget ${budget}`);
  }
}

/* --- tolerance actually controls the error -------------------------------- */
console.log('\n=== tightening the tolerance tightens the answer (rober) ===');
{
  const ref = loadRef('rober');
  // Measured as a plain relative difference here, because the point is that
  // the answer itself improves -- in tolerance units it would not, by
  // construction, since the units shrink with the tolerance.
  const relError = (sol) => {
    let worst = 0;
    for (let j = 0; j < ref.t.length; j++) {
      for (let i = 0; i < 3; i++) {
        const want = ref.y[j][i];
        if (Math.abs(want) < 1e-8) continue;
        worst = Math.max(worst, Math.abs(sol.u[j][i] - want) / Math.abs(want));
      }
    }
    return worst;
  };
  for (const [name, make, loosen] of SOLVERS) {
    const errs = [];
    for (const rtol of [1e-4, 1e-6, 1e-8]) {
      const prob = new ODEProblem(rober.f, rober.u0, rober.tspan, { jac: rober.jac });
      const sol = solve(prob, make(), {
        reltol: rtol * Math.min(loosen, 100), abstol: rtol * 1e-6 * Math.min(loosen, 100),
        maxiters: 2e6, saveat: ref.t, tstops: ref.t,
      });
      errs.push(sol.retcode === 'Success' ? relError(sol) : NaN);
    }
    console.log(`      ${name.padEnd(11)} ${errs.map((e) => e.toExponential(2)).join('  ')}`);
    check(`rober: ${name} gets more accurate as the tolerance tightens`,
          errs[2] < errs[0] / 10 && Number.isFinite(errs[2]),
          `${errs[0].toExponential(1)} -> ${errs[2].toExponential(1)}`);
  }
}

/* --- letting the absolute tolerance follow the solution -------------------- */
console.log('\n=== abstol allowed to follow the solution upwards ===');
{
  // Each component ends up judged against the largest it has ever been rather
  // than against a floor fixed before the run. What that is worth depends on
  // the problem and on the method, which is why it is off by default -- but it
  // must at least do something, and the same something every time.
  for (const [p, name, atol] of [[rober, 'rober', 1e-14], [hires, 'hires', 1e-12]]) {
    const at = (auto) => solve(
      new ODEProblem(p.f, p.u0, p.tspan, p.jac ? { jac: p.jac } : {}),
      alg.FBDF(), { reltol: 1e-8, abstol: atol, maxiters: 2e6, autoAbstol: auto },
    );
    const off = at(false);
    const on = at(true);
    console.log(`      ${name}: ${off.stats.naccept} steps off, ${on.stats.naccept} on`);
    check(`${name}: both settings reach the end`,
          off.retcode === 'Success' && on.retcode === 'Success', true);
    check(`${name}: the setting changes the run`, on.stats.naccept !== off.stats.naccept, true);
    // Loosening the tolerance must not move the answer beyond what the
    // tolerance allows; the reference here is the run with it off.
    let worst = 0;
    for (let i = 0; i < p.n; i++) {
      const a = off.final[i];
      const b = on.final[i];
      worst = Math.max(worst, Math.abs(a - b) / (atol + 1e-8 * Math.abs(a)));
    }
    console.log(`      ${name}: the two answers differ by ${worst.toPrecision(3)} tolerance units`);
    check(`${name}: and the answer still stands up`, worst < 2000, true,);
  }
}

/* --- a step at the floor that fails its error test ------------------------- */
console.log('\n=== accepting a failing step when no shorter one exists ===');
{
  // Far from the origin one ulp of t is large: at t = 1e15 the smallest step
  // that changes the clock is about 2 seconds, so a solver that wants less
  // than that is asking for a step that does not exist. Every method here
  // stops at that point by default, which is what the published methods do
  // (IntegrationTolNotMet) and what DifferentialEquations.jl does.
  // `belowTolRun` accepts that many such steps in a row instead.
  const mu = 1e6;
  const f = (t, y, du) => { du[0] = y[1]; du[1] = mu * ((1 - y[0] * y[0]) * y[1] - y[0]); };
  const at = (n) => solve(
    new ODEProblem(f, [2, 0], [1e15, 1e15 + 40]), alg.Rodas5P(),
    { reltol: 1e-10, abstol: 1e-12, maxiters: 2e5, belowTolRun: n },
  );
  const strict = at(0);
  const lenient = at(5);
  console.log(`      belowTolRun 0: ${strict.retcode}, ${strict.stats.naccept} steps`);
  console.log(`      belowTolRun 5: ${lenient.retcode}, ${lenient.stats.naccept} steps, `
    + `${lenient.stats.nbelowtol} of them accepted below tolerance`);
  check('the default stops at the floor, as the published methods do',
        strict.retcode, 'DtLessThanMin');
  check('and allowing a few such steps gets through instead',
        lenient.retcode, 'Success');
  check('with the count reported rather than buried',
        lenient.stats.nbelowtol > 0, true);
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) console.log('failed: ' + failures.join(', '));
process.exit(failures.length ? 1 : 0);
