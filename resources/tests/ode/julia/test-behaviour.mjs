#!/usr/bin/env node
/*
  What the integrator does around a step, on problems small enough to know the
  answer to: where events are found, what the rows saved inside a step hold,
  the output hook, how a run that cannot go on ends, and the bookkeeping of
  QNDF and RadauIIA5 when a step is thrown away.

      node resources/tests/ode/julia/test-behaviour.mjs

  Every group here failed on the package as it was before 2026-09-25, each for
  the reason its heading gives:

    1  two or more event functions were never located, of two crossing in one
       step the lower-numbered one was reported, earlier or not, and there was
       no way to switch one off
    2  FBDF and QNDF rows between steps came from a Hermite with a zero slope
       at the far end
    3  rows inside a step an event cut short were read at the wrong place
    4  there was no hook for the saved rows
    5  QNDF rolled its differences forward before the error test, and from
       the unclamped state
    6  RadauIIA5 extrapolated its starting guess from a failed attempt and
       could fall to the floor for good; a step that failed there was retried
       until the step budget ran out; a non-finite candidate was left in place
    7  RadauIIA5 kept a complex factorisation from a Jacobian renewed for age
    8  a NaN error estimate was accepted, and the maximum norms skipped NaNs
    9  FBDF could not go on from a jump late in a run: its first step predicted
       no change, and its history's times were the clock's rounded readings
   10  FBDF moved a component at rest by rounding, 1e4 ulps at a time, and an
       event on it fired again and again
   11  an event was handed back from the middle of its bracket, which could
       be a hair short of the crossing, and a run restarted there found the
       same crossing again
   12  RadauIIA5 carried its polynomial below zero from a component clamped
       there, and with rates that read max(0, y) it ground at one short step

  Exit status is 0 when every check passes.
*/
import { solve, ODEProblem } from '../../../js/ode/julia/core/integrator.js';
import { NewtonSolver, COEFFICIENT_MULTISTEP } from '../../../js/ode/julia/core/newton.js';
import { wmaxNorm } from '../../../js/ode/julia/core/linalg.js';
import * as alg from '../../../js/ode/julia/index.js';

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
  checks++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `: ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

const METHODS = {
  FBDF: alg.FBDF, QNDF: alg.QNDF, QBDF: alg.QBDF, Rodas5P: alg.Rodas5P,
  RadauIIA5: alg.RadauIIA5, KenCarp4: alg.KenCarp4, TRBDF2: alg.TRBDF2,
};
const linspace = (a, b, m) => Array.from({ length: m }, (_, i) => a + (b - a) * (i / (m - 1)));

/** y' = -y, y(0) = 1, with a second component y2' = y - y2 / 10 riding along. */
const decay = (t, u, du) => { du[0] = -u[0]; du[1] = u[0] - 0.1 * u[1]; return du; };

/** Wraps an algorithm so a test can watch its cache. */
function watched(make, onBuild) {
  const base = make();
  return { ...base, build: (n, integ, opts) => { const c = base.build(n, integ, opts); onBuild(c, integ); return c; } };
}

/** A method that is no method: its step does what the test says. */
function fakeMethod(stepFn) {
  return {
    name: 'Fake', order: 1,
    build: () => ({ order: 1, errorOrder: 1, hasFsalLast: false, dtpropose: null, step: stepFn }),
    controller: {},
  };
}

// --- 1. events --------------------------------------------------------------------------

console.log('\n1. event functions, one direction each, the earliest crossing first');
for (const [name, make] of Object.entries(METHODS)) {
  // y reaches 0.25 at ln 4 (falling); t reaches 0.5 first (rising).
  const events = {
    n: 2, direction: [-1, 1], terminal: true,
    fun: (t, u, out) => { out[0] = u[0] - 0.25; out[1] = t - 0.5; return out; },
  };
  const sol = solve(new ODEProblem(decay, [1, 0], [0, 5], { events }), make(),
    { reltol: 1e-8, abstol: 1e-10, saveEverystep: false });
  const ev = sol.events[0];
  check(`${name}: with a direction per function, the earlier crossing stops the run`,
    !!ev && ev.which === 1 && Math.abs(ev.t - 0.5) < 1e-9, ev ? `which ${ev.which} at ${ev.t}` : 'no event');

  // The second function may only fall, and t rises: it must not count.
  const onlyFalling = { ...events, direction: [-1, -1] };
  const sol2 = solve(new ODEProblem(decay, [1, 0], [0, 5], { events: onlyFalling }), make(),
    { reltol: 1e-8, abstol: 1e-10, saveEverystep: false });
  const ev2 = sol2.events[0];
  // TRBDF2 is second order: its event time is held to less.
  const tol = name === 'TRBDF2' ? 1e-5 : 1e-6;
  check(`${name}: a crossing in the other direction is not one`,
    !!ev2 && ev2.which === 0 && Math.abs(ev2.t - Math.log(4)) < tol, ev2 ? `which ${ev2.which} at ${ev2.t}` : 'no event');
}
{
  // Two crossings inside one step: t = 0.3 numbered first, t = 0.2 second, one
  // direction for both. The first step is forced to cover both.
  const events = {
    n: 2, direction: 1, terminal: true,
    fun: (t, u, out) => { out[0] = t - 0.3; out[1] = t - 0.2; return out; },
  };
  const slow = (t, u, du) => { du[0] = -0.01 * u[0]; return du; };
  for (const [name, make] of Object.entries(METHODS)) {
    const sol = solve(new ODEProblem(slow, [1], [0, 5], { events }), make(),
      { reltol: 1e-2, abstol: 1e-6, dt: 0.5, saveEverystep: false });
    const ev = sol.events[0];
    check(`${name}: of two crossings in one step the earlier is reported, whatever their numbers`,
      !!ev && ev.which === 1 && Math.abs(ev.t - 0.2) < 1e-12, ev ? `which ${ev.which} at ${ev.t}` : 'no event');
  }
  // A function switched off is not looked at. It is the first-numbered and the
  // earlier to cross here, so neither the first-numbered nor the earliest rule
  // can pick the one left on by accident.
  const masked = {
    n: 2, direction: 1, terminal: true, enabled: Uint8Array.from([0, 1]),
    fun: (t, u, out) => { out[0] = t - 0.2; out[1] = t - 0.3; return out; },
  };
  for (const [name, make] of Object.entries(METHODS)) {
    const sol = solve(new ODEProblem(slow, [1], [0, 5], { events: masked }), make(),
      { reltol: 1e-2, abstol: 1e-6, dt: 0.5, saveEverystep: false });
    const ev = sol.events[0];
    check(`${name}: a function switched off does not fire, and the one left does`,
      !!ev && ev.which === 1 && Math.abs(ev.t - 0.3) < 1e-12, ev ? `which ${ev.which} at ${ev.t}` : 'no event');
  }
  // The same function twice: both reported, at one instant.
  const twins = {
    n: 2, direction: [1, 1], terminal: true,
    fun: (t, u, out) => { out[0] = t - 0.25; out[1] = t - 0.25; return out; },
  };
  const sol = solve(new ODEProblem(slow, [1], [0, 5], { events: twins }), alg.Rodas5P(),
    { reltol: 1e-2, abstol: 1e-6, dt: 0.5, saveEverystep: false });
  const ev = sol.events[0];
  check('two functions crossing at one instant are reported together',
    !!ev && Array.isArray(ev.all) && ev.all.join() === '0,1', ev ? `all ${ev.all}` : 'no event');
}

// --- 2. rows between steps ------------------------------------------------------------------

console.log('\n2. the rows between steps, from each method\'s own interpolant');
{
  const grid = linspace(0, 10, 201);
  for (const [name, make] of Object.entries(METHODS)) {
    const sol = solve(new ODEProblem(decay, [1, 0], [0, 10]), make(),
      { reltol: 1e-8, abstol: 1e-12, saveat: grid, saveEverystep: false });
    let worst = 0;
    grid.forEach((t, j) => { worst = Math.max(worst, Math.abs(sol.u[j][0] - Math.exp(-t))); });
    // TRBDF2 is second order; the rest are held near the tolerance.
    const bound = name === 'TRBDF2' ? 1e-5 : 1e-6;
    check(`${name}: every row within ${bound} of e^-t`, worst < bound, `worst ${worst.toExponential(2)}`);
  }
}

// --- 3. rows inside a step an event cut short -----------------------------------------------

console.log('\n3. rows inside the step an event cut short');
{
  const grid = linspace(0, 3, 301);
  const events = { n: 1, direction: -1, terminal: true, fun: (t, u, out) => { out[0] = u[0] - 0.25; return out; } };
  for (const [name, make] of Object.entries(METHODS)) {
    const sol = solve(new ODEProblem(decay, [1, 0], [0, 3], { events }), make(),
      { reltol: 1e-8, abstol: 1e-12, saveat: grid, saveEverystep: false });
    const ev = sol.events[0];
    let worst = 0;
    for (let j = 0; j < sol.t.length; j++) worst = Math.max(worst, Math.abs(sol.u[j][0] - Math.exp(-sol.t[j])));
    const bound = name === 'TRBDF2' ? 1e-5 : 1e-6;
    check(`${name}: rows up to the event within ${bound} of e^-t`,
      !!ev && worst < bound, `worst ${worst.toExponential(2)}, event at ${ev && ev.t}`);
  }
}

// --- 4. the output hook ---------------------------------------------------------------------

console.log('\n4. onOutput sees every saved row');
{
  const grid = linspace(0, 2, 21);
  const events = { n: 1, direction: -1, terminal: true, fun: (t, u, out) => { out[0] = u[0] - 0.25; return out; } };
  for (const withEvent of [false, true]) {
    const seen = [];
    const sol = solve(new ODEProblem(decay, [1, 0], [0, 2], withEvent ? { events } : {}), alg.FBDF(),
      { reltol: 1e-8, abstol: 1e-12, saveat: grid, saveEverystep: false,
        onOutput: (t, u) => seen.push([t, Float64Array.from(u)]) });
    // Every saved row but the first (the start) and an event's (not a saveat time).
    const rows = withEvent ? sol.t.length - 2 : sol.t.length - 1;
    const same = seen.length === rows
      && seen.every(([t, u], j) => t === sol.t[j + 1] && u[0] === sol.u[j + 1][0] && u[1] === sol.u[j + 1][1]);
    check(`onOutput is called once for each saved row, with its values${withEvent ? ', up to an event' : ''}`,
      same, `${seen.length} calls for ${rows} rows`);
  }
}

// --- 5. QNDF's differences ------------------------------------------------------------------

console.log('\n5. QNDF: the differences follow the steps that were kept');
{
  // Van der Pol at mu = 10 and a loose tolerance: plenty of rejected steps.
  const vdp = (t, u, du) => { du[0] = u[1]; du[1] = 10 * (1 - u[0] * u[0]) * u[1] - u[0]; return du; };
  // A step taken at a new size or order first rescales the differences onto
  // it, which is part of taking it; one at the size and order of the last
  // accepted step has nothing to rescale, and its rejection must leave them as
  // they were -- before, its solution was rolled into them all the same.
  let rejected = 0;
  let changed = 0;
  const make = () => watched(alg.QNDF, (c) => {
    let snapshot = null;
    const step = c.step.bind(c);
    const onReject = c.rejected.bind(c);
    c.step = (integ) => {
      const k = Math.min(c.order, c.maxOrder);
      const rescales = !c.started || c.dtprev === 0 || integ.dt !== c.dtprev || c.prevOrder !== k;
      snapshot = rescales ? null : c.D.map((d) => Float64Array.from(d));
      return step(integ);
    };
    c.rejected = (integ) => {
      if (snapshot) {
        rejected++;
        if (c.D.some((d, j) => d.some((v, i) => v !== snapshot[j][i]))) changed++;
      }
      return onReject(integ);
    };
  });
  solve(new ODEProblem(vdp, [2, 0], [0, 20]), make(), { reltol: 1e-3, abstol: 1e-6, saveEverystep: false });
  check('a step the error test rejects leaves the differences as they were',
    rejected > 0 && changed === 0, `${changed} of ${rejected} rejected steps changed them`);

  // A chain of twelve whose fast members undershoot zero and are clamped back.
  const k = Array.from({ length: 12 }, (_, i) => 10 ** (-i / 4));
  const chain = (t, u, du) => {
    du[0] = -k[0] * u[0];
    for (let i = 1; i < 12; i++) du[i] = k[i - 1] * u[i - 1] - k[i] * u[i];
    return du;
  };
  let worst = 0;
  let clamps = 0;
  const make2 = () => watched(alg.QNDF, (c, integ) => {
    let kept = Float64Array.from(integ.uprev);
    const accepted = c.accepted.bind(c);
    const clamp = integ.clamp.bind(integ);
    integ.clamp = (u) => { const hit = clamp(u); clamps += hit; return hit; };
    c.accepted = (ig, dtjust) => {
      accepted(ig, dtjust);
      // After a step is kept, ∇y at the new point is the kept state less the
      // last one -- to rounding -- however the step was clamped.
      for (let i = 0; i < ig.n; i++) worst = Math.max(worst, Math.abs(c.D[1][i] - (ig.u[i] - kept[i])));
      kept = Float64Array.from(ig.u);
    };
  });
  const u0 = new Array(12).fill(0); u0[0] = 1;
  solve(new ODEProblem(chain, u0, [0, 1000]), make2(),
    { reltol: 1e-3, abstol: 1e-6, saveEverystep: false, nonNegative: true });
  check('the first difference after a clamped step is the kept state less the last one',
    clamps > 0 && worst < 1e-14, `worst ${worst.toExponential(2)} over ${clamps} clamped values`);
}

// --- 6. failures that used to grind ---------------------------------------------------------

console.log('\n6. RadauIIA5 recovers from a failed attempt; a step that fails at the floor ends the run');
{
  // The Brusselator, A = 1 and B = 3: a Newton that diverges at t = 13.7.
  const brusselator = (t, u, du) => {
    const [x, y] = u;
    du[0] = 1 - 4 * x + x * x * y;
    du[1] = 3 * x - x * x * y;
    return du;
  };
  const sol = solve(new ODEProblem(brusselator, [1, 1], [0, 60]), alg.RadauIIA5(),
    { maxiters: 20000, saveEverystep: false });
  check('RadauIIA5 gets past a diverged Newton on the Brusselator and reaches the end',
    sol.retcode === 'Success', `${sol.retcode} at t = ${sol.stats.t} after ${sol.stats.nsteps} steps`);

  // No state has a derivative after t = 1: every step past it fails.
  const broken = (t, u, du) => { du[0] = t > 1 ? NaN : -u[0]; return du; };
  for (const [name, make] of Object.entries(METHODS)) {
    const s = solve(new ODEProblem(broken, [1], [0, 5]), make(), { maxiters: 20000, saveEverystep: false });
    check(`${name}: a step that cannot be taken even at the floor ends the run there`,
      s.retcode !== 'MaxIters' && s.retcode !== 'Success' && s.stats.nsteps < 2000 && s.stats.t > 0.99,
      `${s.retcode} after ${s.stats.nsteps} attempts at t = ${s.stats.t}`);
  }

  // A candidate that is not a number is not left for the next attempt to read.
  let attempt = 0;
  let sawNaN = false;
  const glitch = fakeMethod((integ) => {
    attempt++;
    if (attempt > 1 && integ.u.some((v) => !Number.isFinite(v))) sawNaN = true;
    for (let i = 0; i < integ.n; i++) integ.u[i] = attempt === 1 ? NaN : integ.uprev[i];
    integ.EEst = 0.5;
    return true;
  });
  solve(new ODEProblem(decay, [1, 0], [0, 1]), glitch, { dt: 0.1, saveEverystep: false });
  check('after a non-finite candidate the next attempt starts from the last accepted state', attempt > 1 && !sawNaN);
}

// --- 7. RadauIIA5's two factorisations ------------------------------------------------------

console.log('\n7. RadauIIA5 refactors its complex half with every new Jacobian');
{
  // Van der Pol at mu = 1: a limit cycle the controller follows at a steady
  // step, the Newton converging fast, and a Jacobian renewed for age every
  // second step -- often at a step size the last step had too.
  const f = (t, u, du) => { du[0] = u[1]; du[1] = (1 - u[0] * u[0]) * u[1] - u[0]; return du; };
  let stale = 0;
  let renewals = 0;
  const make = () => watched(alg.RadauIIA5, (c, integ) => {
    let complexFactors = 0;
    const factor = c.clu.factor.bind(c.clu);
    c.clu.factor = (re, im) => { complexFactors++; return factor(re, im); };
    const step = c.step.bind(c);
    c.step = (ig) => {
      const jacs = ig.jacCache.njac;
      const before = complexFactors;
      const ok = step(ig);
      if (ig.jacCache.njac !== jacs) {
        renewals++;
        if (complexFactors === before) stale++;
      }
      return ok;
    };
  });
  solve(new ODEProblem(f, [1, 1], [0, 50]), make(), { reltol: 1e-4, abstol: 1e-7, maxJacAge: 2, saveEverystep: false });
  check('every step that renews J factorises the complex half from it',
    renewals > 3 && stale === 0, `${stale} of ${renewals} renewals kept the old complex factor`);
}

// --- 8. NaN ------------------------------------------------------------------------------

console.log('\n8. a norm or an error estimate that is not a number');
{
  check('the maximum norm of a vector with a NaN in it is NaN', Number.isNaN(wmaxNorm([1, NaN, 0.5], [1, 1, 1])));

  // One Newton iteration from a derivative with a NaN in its first component.
  const newton = new NewtonSolver(2, { norm: 'max' });
  newton.method = COEFFICIENT_MULTISTEP;
  newton.gamma = 1;
  newton.c = 1;
  newton.tmp.set([1, 1]);
  newton.z.set([1, 1]);
  const identityW = { solve: (b) => b };
  const status = newton.solve((t, u, out) => { out[0] = NaN; out[1] = 0; return out; }, identityW,
    0, 1e-3, Float64Array.from([1, 1]), { reltol: 1e-6, abstol: 1e-9 }, true);
  check('a Newton correction with a NaN in it is not convergence in the maximum norm',
    status !== 'Convergence', `status ${status}`);

  // A method whose error estimate is NaN: no step of it may be accepted.
  const nanEst = fakeMethod((integ) => { integ.u.set(integ.uprev); integ.EEst = NaN; return true; });
  const s1 = solve(new ODEProblem(decay, [1, 0], [0, 1]), nanEst, { dt: 0.1, saveEverystep: false });
  check('a step whose error estimate is NaN is not accepted', s1.stats.naccept === 0 && s1.retcode !== 'Success',
    `${s1.stats.naccept} accepted, ${s1.retcode}`);

  // The same through the integrator's own maximum norm: the error of one
  // component cannot be measured.
  const nanComponent = fakeMethod((integ) => {
    integ.u.set(integ.uprev);
    integ.EEst = integ.errorNorm(Float64Array.from([1e-12, NaN]));
    return true;
  });
  const s2 = solve(new ODEProblem(decay, [1, 0], [0, 1]), nanComponent,
    { dt: 0.1, norm: 'max', saveEverystep: false });
  check('the integrator\'s maximum norm does not pass a step on the components it could measure',
    s2.stats.naccept === 0 && s2.retcode !== 'Success', `${s2.stats.naccept} accepted, ${s2.retcode}`);
}

// --- 9. FBDF from a jump late in a run -------------------------------------------------------

console.log('\n9. every method goes on from a jump late in a run');
{
  // A chain M -> B -> R -> W given M = 9e12 and B = 1e12 at T, which is what a
  // model whose packages all fail at once does. R starts from nothing and rises
  // at 1e10 a unit of time, and at T the clock is good to 9e-13. FBDF's first
  // step used to predict no change, so that its error estimate was h f, and
  // no step it could represent passed; with that mended, its history's times
  // were the clock's rounded readings, 3 % out on the shortest steps, and the
  // error estimate saw 1e10 times the rounding. Each alone still failed here.
  const T = 5000.123456789;
  const chain = (t, u, du) => {
    du[0] = -1e-4 * u[0];
    du[1] = 1e-4 * u[0] - 0.01 * u[1];
    du[2] = 0.01 * u[1] - 1e-3 * u[2];
    du[3] = 1e-3 * u[2];
    return du;
  };
  // R at the end from the closed form (Bateman): the M part and the B part.
  const k = [1e-4, 0.01, 1e-3];
  const tau = 20000 - T;
  const e = (r) => Math.exp(-r * tau);
  const rExact = 9e12 * k[0] * k[1] * (e(k[0]) / ((k[1] - k[0]) * (k[2] - k[0]))
    + e(k[1]) / ((k[0] - k[1]) * (k[2] - k[1])) + e(k[2]) / ((k[0] - k[2]) * (k[1] - k[2])))
    + 1e12 * k[1] * (e(k[1]) / (k[2] - k[1]) + e(k[2]) / (k[1] - k[2]));
  for (const [name, make] of Object.entries(METHODS)) {
    // As Kompartment runs it: a new run from the jump.
    const a = solve(new ODEProblem(chain, [9e12, 1e12, 0, 0], [T, 20000]), make(),
      { reltol: 1e-6, abstol: 1e-6, saveEverystep: false });
    const rA = a.u[a.u.length - 1][2];
    check(`${name}: a run that starts at the jump reaches the end, and R there to 1e-4`,
      a.retcode === 'Success' && Math.abs(rA / rExact - 1) < 1e-4,
      a.retcode === 'Success' ? `R off by ${(rA / rExact - 1).toExponential(1)}` : a.message);
    // As the integrator restarts itself: an event at T applies the jump.
    const events = {
      n: 1, direction: 1, fun: (t, u, out) => { out[0] = t - T; return out; },
      apply: (t, u) => { u[0] += 9e12; u[1] += 1e12; },
    };
    const b = solve(new ODEProblem(chain, [0, 0, 0, 0], [0, 20000], { events }), make(),
      { reltol: 1e-6, abstol: 1e-6, saveEverystep: false });
    const rB = b.u[b.u.length - 1][2];
    check(`${name}: a run with an event that applies the jump reaches the end, and R there to 1e-4`,
      b.retcode === 'Success' && Math.abs(rB / rExact - 1) < 1e-4,
      b.retcode === 'Success' ? `R off by ${(rB / rExact - 1).toExponential(1)}` : b.message);
  }
}

// --- 10. a component at rest --------------------------------------------------------------

console.log('\n10. a component at rest stays exactly where it is');
{
  // A feeds B fast, B -> C slowly, A + B -> D; TOT counts what has been fed,
  // and an event switches the feed off when TOT reaches 3.7. After it TOT is
  // at rest, and so is the event function, at its zero. FBDF summed its
  // Lagrange formulas as Σ wⱼ·uⱼ, with weights in the thousands once the step
  // had grown, and moved TOT by 9e-11: the event fired four times in this run
  // (fifty times on the canister model, and the page's cap then ended it).
  const f = (t, u, du) => {
    const r = u[5];                   // the feed, switched off by the event
    du[0] = r - 1e3 * u[0] - 10 * u[0] * u[1];
    du[1] = 1e3 * u[0] - 1e-2 * u[1] - 10 * u[0] * u[1];
    du[2] = 1e-2 * u[1] - 1e-4 * u[2];
    du[3] = 10 * u[0] * u[1];
    du[4] = r;                        // TOT
    du[5] = 0;
    return du;
  };
  for (const [name, make] of Object.entries(METHODS)) {
    const events = {
      n: 1, direction: 1, fun: (t, u, out) => { out[0] = u[4] - 3.7; return out; },
      apply: (t, u) => { u[5] = 0; },
    };
    let tot = null;
    let moved = 0;
    const sol = solve(new ODEProblem(f, [0, 0, 0, 0, 0, 1], [0, 1e5], { events }), make(), {
      reltol: 1e-6, abstol: 1e-12, saveEverystep: false,
      onAccepted: (t, u) => {
        if (u[5] !== 0) return;
        if (tot == null) tot = u[4];
        else moved = Math.max(moved, Math.abs(u[4] - tot));
      },
    });
    check(`${name}: the feed is switched off once, and TOT does not move after it`,
      sol.retcode === 'Success' && sol.events.length === 1 && tot != null && moved === 0,
      `${sol.events.length} events, TOT moved by ${moved.toExponential(1)}`);
  }
}

// --- 11. the far side of a crossing --------------------------------------------------------

console.log('\n11. an event is handed back where it has happened, and a restart does not find it again');
{
  // A = exp(-0.3 t) falls through exp(-0.3 c). The run stops there, and a new
  // one starts from the state handed back, as the pages' drivers do. That
  // state came from the middle of the search's bracket, and at these levels
  // it lay a hair short of the crossing for one method or another: the
  // restart found the same crossing 4e-16 to 5e-15 in, past the guard for a
  // root at the very start. Now it is the bracket's far end, as the NDF's.
  const f = (t, u, du) => { du[0] = -0.3 * u[0]; du[1] = 0.3 * u[0]; return du; };
  const jac = (t, y, J) => {
    if (J.values) { J.values[0] = -0.3; J.values[1] = 0.3; return; }
    J.data.fill(0); J.data[0] = -0.3; J.data[1] = 0.3;
  };
  const jacPattern = { colPtr: Int32Array.from([0, 2, 2]), rowIdx: Int32Array.from([0, 1]) };
  const opts = { reltol: 1e-8, abstol: 1e-12, norm: 'rms', smoothEst: true, saveEverystep: false };
  for (const [name, make] of Object.entries(METHODS)) {
    const again = [];
    const near = [];
    for (const c of [0.03402, 0.1, 0.15293, 0.16844, 0.18395, 0.26667]) {
      const level = Math.exp(-0.3 * c);
      const events = {
        n: 1, direction: -1, terminal: true, fun: (t, u, out) => { out[0] = u[0] - level; return out; },
      };
      const P = (u0, span) => new ODEProblem(f, u0, span, { events, jac, jacPattern });
      const first = solve(P([1, 0], [0, 10]), make({ smoothEst: true }), opts);
      const ev = first.events[0];
      if (!(first.final[0] - level <= 0)) near.push(c);
      const second = solve(P(first.final, [ev.t, 10]), make({ smoothEst: true }), opts);
      if (second.events.length) again.push(`${c} (+${(second.events[0].t - ev.t).toExponential(1)})`);
    }
    check(`${name}: every stop is past its crossing, and no restart finds it again`,
      !near.length && !again.length,
      `short of it at ${near.join(', ') || 'none'}; found again at ${again.join(', ') || 'none'}`);
  }
}

// --- 12. RadauIIA5 at a clamped component -----------------------------------------------------

console.log('\n12. RadauIIA5 goes on past a component held at zero, where the rates are flat below it');
{
  // The rates read each species as max(0, y), as facsimile's and rtm's models
  // do, and the Jacobian is the right-hand one; the integrator clamps every
  // accepted step at zero. A decays in a millisecond and sits at zero, and
  // the rest move on a scale of a hundred. Radau's starting guess carried the
  // last step's polynomial on below zero, where f is flat and J is not, and
  // its Newton crawled: every step past 5e-3 was taken for divergence, and
  // 20000 steps reached t = 58.
  const p = (y) => (y > 0 ? y : 0);
  const f = (t, u, du) => {
    const a = p(u[0]); const b = p(u[1]); const c = p(u[2]);
    du[0] = -1e3 * a - 10 * a * b;
    du[1] = 1e3 * a - 1e-2 * b - 10 * a * b;
    du[2] = 1e-2 * b - 1e-4 * c;
    du[3] = 10 * a * b;
    return du;
  };
  const jac = (t, u, J) => {
    const on = (y) => (y >= 0 ? 1 : 0);
    const a = p(u[0]); const b = p(u[1]);
    const da = on(u[0]); const db = on(u[1]); const dc = on(u[2]);
    const d = [
      [(-1e3 - 10 * b) * da, -10 * a * db, 0, 0],
      [(1e3 - 10 * b) * da, (-1e-2 - 10 * a) * db, 0, 0],
      [0, 1e-2 * db, -1e-4 * dc, 0],
      [10 * b * da, 10 * a * db, 0, 0],
    ];
    if (J.values) throw new Error('dense only');
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) J.data[c * 4 + r] = d[r][c];
  };
  const u0 = [0.0009661531756565588, 3.5041242189016497, 0.06597147775755544, 0.06446497116601559];
  const sol = solve(new ODEProblem(f, u0, [3.7, 1e5], { jac }), alg.RadauIIA5(), {
    reltol: 1e-6, abstol: 1e-12, norm: 'rms', matrix: 'dense', smoothEst: true, saveEverystep: false,
    nonNegative: [true, true, true, true], maxiters: 20000,
  });
  check('RadauIIA5 reaches the end in a few hundred steps',
    sol.retcode === 'Success' && sol.stats.naccept < 1000,
    `${sol.retcode}, ${sol.stats.naccept} steps, ${sol.stats.nreject} rejected${sol.message ? `: ${sol.message.slice(0, 80)}` : ''}`);
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) {
  console.log(`failed: ${failures.join('; ')}`);
  process.exit(1);
}
