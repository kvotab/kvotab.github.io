#!/usr/bin/env node
/*
  The automatic algorithm and the methods it switches between, against
  DifferentialEquations.jl itself.

  ref/default.json is what OrdinaryDiffEq 7.8.1 did on the problems in
  problems-default.mjs (scripts/gen-ode-default-ref.jl wrote it, from the
  twins of those problems in Julia, with exact Jacobians on both sides). For
  every run this compares

    the answer      the final state's error against a reference at reltol
                    1e-12, in units of the run's own tolerance, with Julia's
                    error beside it; the port may not be much worse
    the switching   which method took every step, as runs of (method,
                    steps): held step for step where the two agree today
                    (`exact` in COMPARISONS), and otherwise reported
    the work        accepted and rejected steps, beside Julia's

  Exact agreement is not to be expected everywhere and is not asked for.
  Lorenz-like chaos aside, documented differences decide the FBDF runs:
  OrdinaryDiffEq's composite controller never rejects an FBDF step (its BDF
  controller reads an error estimate that is written elsewhere -- see
  ../../../js/ode/julia/solvers/default.js), so its FBDF rides through steps
  the port rejects; the port predicts FBDF's first step after a switch by an
  Euler step, which OrdinaryDiffEq does not; and a state at rest makes Julia's
  stiffness estimate NaN, which this package passes over. Every run held step
  for step has a Rosenbrock method on its stiff side, or none.

      node resources/tests/ode/julia/test-default.mjs [--verbose]
*/
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as J from '../../../js/ode/julia/index.js';
import { COMPARISONS } from './problems-default.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const VERBOSE = process.argv.includes('--verbose');
const REF = JSON.parse(readFileSync(join(HERE, 'ref', 'default.json'), 'utf8'));

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
  checks++;
  if (!ok || VERBOSE) console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `: ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

function compress(choice) {
  const out = [];
  for (const a of choice) {
    if (out.length && out[out.length - 1][0] === a) out[out.length - 1][1]++;
    else out.push([a, 1]);
  }
  return out;
}

/** The worst error of `got` against `ref`, in units of atol + rtol·|ref|. */
function tolUnits(got, ref, rtol, atol) {
  let worst = 0;
  for (let i = 0; i < ref.length; i++) {
    const d = Math.abs(got[i] - ref[i]) / (atol + rtol * Math.abs(ref[i]));
    if (!(d <= worst)) worst = d;
  }
  return worst;
}

const make = {
  Tsit5: () => J.Tsit5(),
  Vern7: () => J.Vern7(),
  Rosenbrock23: () => J.Rosenbrock23(),
  DefaultODEAlgorithm: () => J.DefaultODEAlgorithm(),
};

console.log('problem    method                 tol      steps (Julia)     rejected (Julia)   err/tol (Julia)   switching');
for (const c of COMPARISONS) {
  const rtol = c.reltol ?? 1e-3;
  const atol = c.abstol ?? 1e-6;
  const entry = REF.problems[c.p.name];
  const jl = entry.runs.find((r) => r.alg === c.alg && r.reltol === rtol && r.abstol === atol);
  if (!jl) { check(`${c.p.name} ${c.alg} ${rtol}: in the reference file`, false); continue; }
  const prob = new J.ODEProblem(c.p.f, c.p.u0, c.p.tspan, { jac: c.p.jac, jacPattern: c.p.jacPattern });
  const sol = J.solve(prob, make[c.alg](), { reltol: rtol, abstol: atol });
  const s = sol.stats;
  const label = `${c.p.name} ${c.alg} ${rtol}`;
  check(`${label}: succeeds`, sol.retcode === 'Success', sol.message);

  const errOurs = tolUnits(sol.final, entry.reference, rtol, atol);
  const errJulia = tolUnits(jl.final, entry.reference, rtol, atol);
  // As accurate as Julia, give or take what a different but equally valid
  // sequence of steps costs; and never far out in absolute terms.
  check(`${label}: as accurate as OrdinaryDiffEq`, errOurs <= Math.max(10 * errJulia, 20),
    `${errOurs.toFixed(2)} tolerance units against Julia's ${errJulia.toFixed(2)}`);

  const ours = sol.algChoice ? compress(sol.algChoice) : null;
  const same = ours && jl.runs ? JSON.stringify(ours) === JSON.stringify(jl.runs) : null;
  if (c.exact) {
    if (jl.runs) {
      check(`${label}: switches as OrdinaryDiffEq does, step for step`, same === true,
        `ours ${JSON.stringify(ours)}, Julia's ${JSON.stringify(jl.runs)}`);
    }
    check(`${label}: as many steps as OrdinaryDiffEq`, s.naccept === jl.naccept && s.nreject === jl.nreject,
      `${s.naccept}/${s.nreject} against ${jl.naccept}/${jl.nreject}`);
  } else if (!jl.runs) {
    // A single method: the same algorithm with the same controller takes the
    // same steps up to rounding, so the counts are held within a tenth.
    check(`${label}: about as many steps as OrdinaryDiffEq`,
      Math.abs(s.naccept - jl.naccept) <= 0.1 * jl.naccept + 2,
      `${s.naccept} against ${jl.naccept}`);
  }
  if (ours && jl.runs) {
    // Whatever else, the same methods: the size and tolerance choose them.
    const used = (r) => [...new Set(r.map(([a]) => a))].sort().join(',');
    check(`${label}: the same methods as OrdinaryDiffEq`, used(ours) === used(jl.runs),
      `${used(ours)} against ${used(jl.runs)}`);
    // And the first switch at the same step, where there is one.
    if (jl.runs.length > 1) {
      check(`${label}: the first switch where OrdinaryDiffEq makes it`,
        ours.length > 1 && ours[0][0] === jl.runs[0][0] && Math.abs(ours[0][1] - jl.runs[0][1]) <= 2,
        `after ${ours[0][1]} steps of ${ours[0][0]}, Julia after ${jl.runs[0][1]} of ${jl.runs[0][0]}`);
    }
  }
  const sw = ours ? (same ? 'identical' : `${ours.length} runs, Julia ${jl.runs.length}`) : '';
  console.log(`${c.p.name.padEnd(10)} ${c.alg.padEnd(22)} ${rtol.toExponential(0).padEnd(6)} `
    + `${String(s.naccept).padStart(6)} (${String(jl.naccept).padStart(5)})    `
    + `${String(s.nreject).padStart(6)} (${String(jl.nreject).padStart(5)})    `
    + `${errOurs.toFixed(2).padStart(7)} (${errJulia.toFixed(2).padStart(6)})    ${sw}`);
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) console.log('failed: ' + failures.join('; '));
process.exit(failures.length ? 1 : 0);
