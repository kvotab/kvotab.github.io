#!/usr/bin/env node
/*
  What came with the automatic algorithm (2026-10-03), checked on its own:

    1  an explicit method forms no Jacobian and no W, even under the switch
       while it is in charge -- on 300 000 states a dense W would be 720 GB
    2  Vern7's interpolation stages are worked out only for a step a saved
       row falls in, six evaluations of f each time
    3  a clamped solution is not the point an FSAL method evaluated its last
       stage at, and f is taken again there
    4  GMRES: against a dense LU, with and without the diagonal scaling, warm
       started, and failing as it should at its memory cap
    5  the Krylov FBDF against the factorising one, and a problem's own J·v
       used when it has one
    6  the switch's bookkeeping -- which method took each saved row, the
       steps each took, the log of switches -- and its options: the stiff
       side first, AutoAlgSwitch of two methods, a state at rest read as
       Julia reads it, the thresholds
    7  OrdinaryDiffEq's starting step, including its constant-derivative case
    8  handing off: a run told not to switch to a stiff method stops where it
       would have, with the state there, for the caller to go on from

      node resources/tests/ode/julia/test-switching.mjs
*/
import * as J from '../../../js/ode/julia/index.js';
import { kepler, heat, vdp1000 } from './problems-default.mjs';

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
  checks++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `: ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

// --- 1 ---------------------------------------------------------------------------------------
console.log('\n1. an explicit method forms no matrix');
{
  const n = 300000;
  const f = (t, u, du) => { for (let i = 0; i < n; i++) du[i] = -u[i] * (1 + (i % 7) / 7); };
  const u0 = new Float64Array(n).fill(1);
  for (const [name, make] of [['Tsit5', J.Tsit5], ['Vern7', J.Vern7], ['Default', J.DefaultODEAlgorithm]]) {
    let sol;
    try {
      sol = J.solve(new J.ODEProblem(f, u0, [0, 1]), make(), { saveEverystep: false });
    } catch (e) {
      check(`${name}: runs on 300 000 states`, false, e.message);
      continue;
    }
    check(`${name}: runs on 300 000 states without a Jacobian`,
      sol.retcode === 'Success' && sol.stats.njacs === 0 && sol.stats.nw === 0,
      `${sol.retcode}, ${sol.stats.naccept} steps, ${sol.stats.njacs} Jacobians`);
  }
}

// --- 2 ---------------------------------------------------------------------------------------
console.log('\n2. Vern7 works out its interpolation stages only when a row needs them');
{
  const P = () => new J.ODEProblem(kepler.f, kepler.u0, kepler.tspan);
  const plain = J.solve(P(), J.Vern7(), { reltol: 1e-8, abstol: 1e-10 });
  const grid = Array.from({ length: 41 }, (_, i) => i * 0.5);
  const rows = J.solve(P(), J.Vern7(), { reltol: 1e-8, abstol: 1e-10, saveat: grid });
  // Ten evaluations a step either way (the first is the integrator's f at
  // the step's start), plus six for each step a row of the grid falls inside.
  const stepsWithRows = new Set();
  const ts = plain.t;
  for (const g of grid) {
    if (g === 0 || g === 20) continue;
    let j = 1;
    while (j < ts.length && ts[j] < g) j++;
    if (ts[j] !== g) stepsWithRows.add(j);
  }
  const extra = rows.stats.nf - plain.stats.nf;
  check('the same steps with and without saved rows', rows.stats.naccept === plain.stats.naccept);
  check('six more evaluations for each step a saved row falls inside, and no others',
    extra === 6 * stepsWithRows.size, `${extra} more, for ${stepsWithRows.size} steps with rows`);
  let worst = 0;
  const ref = J.solve(P(), J.Vern7(), { reltol: 1e-13, abstol: 1e-15, saveat: grid, tstops: grid });
  grid.forEach((g, j) => {
    for (let i = 0; i < 4; i++) worst = Math.max(worst, Math.abs(rows.u[j][i] - ref.u[j][i]));
  });
  check('and the rows are as good as the steps', worst < 1e-6, `worst ${worst.toExponential(2)}`);
}

// --- 3 ---------------------------------------------------------------------------------------
console.log('\n3. f is taken again where clamping moved the solution');
for (const [name, make] of [['Tsit5', J.Tsit5], ['Rosenbrock23', J.Rosenbrock23]]) {
  // u' = −1 − u: falls through zero at ln 2 and is held there by the clamp.
  const calls = [];
  const f = (t, u, du) => { calls.push([t, u[0]]); du[0] = -1 - u[0]; };
  let clampedAt = null;
  const sol = J.solve(new J.ODEProblem(f, [1], [0, 2]), make(), {
    nonNegative: true, reltol: 1e-4, abstol: 1e-8,
    onAccepted: (t, u) => { if (clampedAt == null && u[0] === 0) clampedAt = t; },
  });
  // After the first accepted step that clamped, the next f evaluated at that
  // time must be at the clamped state, 0.
  const after = calls.find(([t]) => t === clampedAt);
  check(`${name}: f is evaluated at the clamped state`, sol.retcode === 'Success' && clampedAt != null
    && calls.some(([t, u]) => t === clampedAt && u === 0), after ? `at t = ${clampedAt}` : 'no clamp');
}

// --- 4 ---------------------------------------------------------------------------------------
console.log('\n4. GMRES');
{
  const n = 60;
  let seed = 7;
  const rand = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 - 0.5; };
  const A = new J.DenseMatrix(n);
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) A.set(i, j, rand() + (i === j ? 6 : 0));
  const b = Float64Array.from({ length: n }, rand);
  const lu = new J.DenseLU(n);
  lu.factor(A);
  const exact = Float64Array.from(b);
  lu.solve(exact);
  const op = (v, out) => A.apply(v, out);
  const g = new J.GMRES(n);
  const x = new Float64Array(n);
  const st = g.solve(op, b, x, { atol: 0, rtol: 1e-12, itmax: n });
  const err = (y) => Math.max(...Array.from(y, (v, i) => Math.abs(v - exact[i])));
  check('solves to its tolerance against a dense LU', st.solved && err(x) < 1e-9,
    `${st.niter} iterations, ${err(x).toExponential(2)} from the LU's answer`);
  const w = Float64Array.from({ length: n }, (_, i) => 10 ** ((i % 9) - 4));
  const x2 = new Float64Array(n);
  const st2 = g.solve(op, b, x2, { atol: 0, rtol: 1e-12, itmax: n, left: w, right: w });
  check('and the same with the diagonal scaling on both sides', st2.solved && err(x2) < 1e-9,
    `${st2.niter} iterations, ${err(x2).toExponential(2)}`);
  const x3 = new Float64Array(n);
  // A warm start keeps the cold start's threshold, rtol·‖b‖ as an absolute
  // one, as LinearSolve hands it over; Krylov.jl's rtol alone would be
  // measured against the (tiny) warm residual.
  const bnorm = Math.hypot(...b);
  const st3 = g.solve(op, b, x3, { atol: 1e-12 * bnorm, rtol: 0, itmax: n, x0: exact });
  check('started from the answer, it stops at once', st3.solved && st3.niter === 0 && err(x3) < 1e-12,
    `${st3.niter} iterations`);
  const tight = new J.GMRES(n, { memory: 5, maxBytes: 8 * n * 5 });
  const x4 = new Float64Array(n);
  const st4 = tight.solve(op, b, x4, { atol: 0, rtol: 1e-14, itmax: n });
  check('a basis at its memory cap fails rather than growing', !st4.solved && /cap/.test(st4.status), st4.status);
  const c = J.symGivens(3, 4, new Float64Array(3));
  check('a Givens rotation zeroes its second entry', Math.abs(c[1] * 3 - c[0] * 4) < 1e-15 && Math.abs(c[2] - 5) < 1e-15);
}

// --- 5 ---------------------------------------------------------------------------------------
console.log('\n5. the Krylov FBDF');
{
  const p = heat(200);
  const P = (extra = {}) => new J.ODEProblem(p.f, p.u0, p.tspan, { jac: p.jac, jacPattern: p.jacPattern, ...extra });
  const lu = J.solve(P(), J.FBDF(), { reltol: 1e-6, abstol: 1e-8 });
  const kr = J.solve(P(), J.FBDF({ linsolve: 'gmres' }), { reltol: 1e-6, abstol: 1e-8 });
  let worst = 0;
  for (let i = 0; i < p.n; i++) worst = Math.max(worst, Math.abs(lu.final[i] - kr.final[i]) / (1e-8 + 1e-6 * Math.abs(lu.final[i])));
  check('agrees with the factorising FBDF within the tolerance', kr.retcode === 'Success' && worst < 50,
    `${worst.toFixed(2)} tolerance units; ${kr.stats.naccept} steps against ${lu.stats.naccept}, `
    + `${kr.stats.krylovIters} GMRES iterations, no factorisation (${kr.stats.nw})`);
  check('forms no matrix', kr.stats.njacs === 0 && kr.stats.nw === 0);
  // J·v from the problem itself, exactly: no f spent on differencing it.
  const dx = 1 / (p.n + 1);
  let jvps = 0;
  const jvp = (t, u, v, out) => {
    jvps++;
    for (let i = 0; i < p.n; i++) {
      const l = i > 0 ? v[i - 1] : 0;
      const r = i < p.n - 1 ? v[i + 1] : 0;
      out[i] = (l - 2 * v[i] + r) / (dx * dx);
    }
  };
  const ex = J.solve(P({ jvp }), J.FBDF({ linsolve: 'gmres' }), { reltol: 1e-6, abstol: 1e-8 });
  check('uses the problem\'s own J·v when it has one', ex.retcode === 'Success' && jvps > 0
    && ex.stats.nf < kr.stats.nf / 3, `${jvps} products, ${ex.stats.nf} f against ${kr.stats.nf}`);
}

// --- 6 ---------------------------------------------------------------------------------------
console.log('\n6. the switch\'s bookkeeping and options');
{
  const P = (p) => new J.ODEProblem(p.f, p.u0, p.tspan, { jac: p.jac });
  const sol = J.solve(P(vdp1000), J.DefaultODEAlgorithm());
  const s = sol.stats;
  const by = Object.values(s.stepsBy).reduce((a, b) => a + b, 0);
  check('the steps each method took add up to the steps', by === s.naccept, JSON.stringify(s.stepsBy));
  check('a method choice for every saved row', sol.algChoice.length === sol.t.length
    && sol.algChoice.every((a) => a === 1 || a === 3), `${sol.algChoice.length} for ${sol.t.length}`);
  check('the switches logged', s.switches === s.switchLog.length && s.switches === 7
    && s.switchLog[0].from === 'Tsit5' && s.switchLog[0].to === 'Rosenbrock23',
  `${s.switches}: ${s.switchLog.map((e) => `${e.from}->${e.to}@${e.t.toPrecision(3)}`).slice(0, 3).join(' ')}`);

  const thin = J.solve(P(vdp1000), J.DefaultODEAlgorithm(), { maxPoints: 100 });
  check('thinning the rows keeps the choices with them', thin.algChoice.length === thin.t.length);

  const implicit = J.solve(P(vdp1000), J.DefaultImplicitODEAlgorithm());
  check('DefaultImplicitODEAlgorithm starts on the stiff side and stays there',
    implicit.retcode === 'Success' && implicit.algChoice[0] === 3 && implicit.stats.switches === 0,
    `first ${implicit.algChoice[0]}, ${implicit.stats.switches} switches`);

  const pair = J.solve(P(vdp1000), J.AutoAlgSwitch(J.Tsit5(), J.Rodas5P()));
  check('AutoAlgSwitch of two methods switches between them',
    pair.retcode === 'Success' && pair.stats.switches >= 2 && Object.keys(pair.stats.stepsBy).join() === 'Tsit5,Rodas5P',
    `${pair.stats.switches} switches, ${JSON.stringify(pair.stats.stepsBy)}`);

  // An oscillator far from stiff, with a state at rest beside it: passed
  // over here, and in Julia NaN, which reads as stiff.
  const idle = {
    f: (t, u, du) => { du[0] = u[1]; du[1] = -u[0]; du[2] = 0; },
    u0: [1, 0, 0], tspan: [0, 20],
  };
  const ours = J.solve(new J.ODEProblem(idle.f, idle.u0, idle.tspan), J.DefaultODEAlgorithm());
  const jl = J.solve(new J.ODEProblem(idle.f, idle.u0, idle.tspan), J.DefaultODEAlgorithm({ stillIsStiff: true }));
  check('a state at rest does not make a non-stiff problem stiff', ours.stats.switches === 0,
    `${ours.stats.switches} switches`);
  check('unless asked to read it as Julia does', jl.stats.switches > 0, `${jl.stats.switches} switches`);

  const eager = J.solve(P(vdp1000), J.DefaultODEAlgorithm({ maxstiffstep: 2, maxnonstiffstep: 1 }));
  const firstRun = (x) => { let k = 0; while (k < x.algChoice.length && x.algChoice[k] === x.algChoice[0]) k++; return k; };
  check('the thresholds are the switch\'s: three stiff verdicts switch, not eleven',
    firstRun(eager) < firstRun(sol), `${firstRun(eager)} rows before the first switch, against ${firstRun(sol)}`);

  // An event inside the run restarts the method in charge.
  let fired = 0;
  const events = {
    n: 1, direction: 1, fun: (t, u, out) => { out[0] = t - 1500; return out; },
    apply: () => { fired++; },
  };
  const ev = J.solve(new J.ODEProblem(vdp1000.f, vdp1000.u0, vdp1000.tspan, { jac: vdp1000.jac, events }),
    J.DefaultODEAlgorithm());
  check('an event inside a run is handled, and the run goes on to the end',
    ev.retcode === 'Success' && fired === 1 && Math.abs(ev.events[0].t - 1500) < 1e-9);
}

// --- 7 ---------------------------------------------------------------------------------------
console.log('\n7. OrdinaryDiffEq\'s starting step');
{
  const work = { u1: new Float64Array(1), f1: new Float64Array(1), w: new Float64Array(1) };
  // f does not change: the first probe is the answer, a hundred times over.
  const flat = (t, u, du) => { du[0] = 1; };
  const dt = J.initialStepSciML(flat, 0, Float64Array.from([1]), Float64Array.from([1]), 1, 5, 1e-3, 1e-6, 10, work);
  // d0 = 1/(1e-6 + 1e-3), d1 = the same: dt0 = (d0/d1)/100 = 0.01
  check('a constant derivative gives a hundred times the first probe', Math.abs(dt - 1) < 1e-15, `${dt}`);
  // dtmax bounds the first probe; the answer is a hundred times that, which
  // the integrator then holds to dtmax, as OrdinaryDiffEq's does.
  const dtCap = J.initialStepSciML(flat, 0, Float64Array.from([1]), Float64Array.from([1]), 1, 5, 1e-3, 1e-6, 0.005, work);
  check('dtmax bounds the first probe', Math.abs(dtCap - 0.5) < 1e-15, `${dtCap}`);
  check('Julia\'s eps', J.epsOf(1) === Number.EPSILON && J.epsOf(0) === Number.MIN_VALUE && J.epsOf(-2) === 2 * Number.EPSILON);
}

// --- 8 ---------------------------------------------------------------------------------------
console.log('\n8. handing off a stiff method');
{
  const P = (p) => new J.ODEProblem(p.f, p.u0, p.tspan, { jac: p.jac });
  // Rows every millisecond up to past the first switch, then every ten.
  const saveat = [...Array.from({ length: 30 }, (_, i) => i / 1000), ...Array.from({ length: 300 }, (_, i) => 10 * (i + 1))];
  const whole = J.solve(P(vdp1000), J.DefaultODEAlgorithm(), { saveat });
  const first = whole.stats.switchLog[0];
  const cut = J.solve(P(vdp1000), J.DefaultODEAlgorithm({ handOff: ['Rosenbrock23'] }), { saveat });
  check('it stops where the default would have switched, saying to what',
    cut.retcode === J.HandedOff && cut.handOff.t === first.t
    && cut.handOff.from === 'Tsit5' && cut.handOff.to === 'Rosenbrock23',
  `${cut.retcode} at ${cut.handOff?.t} (the switch at ${first.t})`);
  // The same run up to there, so the same rows and the same state.
  const k = whole.t.findIndex((t) => t > first.t);
  const sameRows = cut.t.length === k && cut.t.every((t, i) => t === whole.t[i]
    && cut.u[i].every((v, j) => v === whole.u[i][j]));
  check('with the rows of the run up to there, bit for bit', sameRows, `${cut.t.length} rows, ${k} before the switch`);
  // The default's own row at that time: the end of a step, read off the
  // interpolant at θ = (t - t₀)/h, which rounding leaves a hair below one.
  const at = J.solve(P(vdp1000), J.DefaultODEAlgorithm(), { saveat: [...saveat, first.t].sort((x, y) => x - y) });
  const row = at.u[at.t.indexOf(first.t)];
  check('and the state there, the one the default switched with',
    cut.handOff.u.every((v, j) => Math.abs(v - row[j]) <= 1e-12 * Math.max(1, Math.abs(v))),
    `${Array.from(cut.handOff.u).map((v) => v.toPrecision(6))} against ${Array.from(row).map((v) => v.toPrecision(6))}`);
  check('the explicit steps are still counted', cut.stats.stepsBy.Tsit5 > 0 && cut.stats.switches === 0,
    JSON.stringify(cut.stats.stepsBy));
  const start = J.solve(P(vdp1000), J.DefaultODEAlgorithm({ stiffalgfirst: true, handOff: ['Rosenbrock23'] }), { saveat });
  check('started on a method it hands off, it stops before a step',
    start.retcode === J.HandedOff && start.handOff.t === 0 && start.stats.nsteps === 0
    && start.handOff.u[0] === 2 && start.handOff.u[1] === 0, `${start.stats.nsteps} steps`);
  const other = J.solve(P(vdp1000), J.DefaultODEAlgorithm({ handOff: ['KrylovFBDF'] }), { saveat });
  check('a method it never chooses is no reason to stop',
    other.retcode === J.Success && other.t.length === whole.t.length
    && other.u.every((u, i) => u.every((v, j) => v === whole.u[i][j])));
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) console.log('failed: ' + failures.join('; '));
process.exit(failures.length ? 1 : 0);
