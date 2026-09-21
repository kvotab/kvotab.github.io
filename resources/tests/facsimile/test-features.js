#!/usr/bin/env node
/*
  The five things the model language gained to close the gap with FACSIMILE's
  own, checked against what FACSIMILE says they mean.

    1. A reaction may name its net rate, which then reads out beside the
       outputs (Technical Reference 1.6, the FXn parameters of the original
       canister model).
    2. deriv(X) reads a species' time derivative in <OUTPUTS>, which is what
       the original's five dummy variables were carrying.
    3. An event may be crossed downwards or either way, and may stop the run
       rather than only change a setting (Technical Reference 4.1).
    4. <TIMES> gives the times a run is to be reported at, interpolated
       between the solver's own steps, as WHEN/WHENEVER lists did.
    5. sin, cos, tan, artan, tanh, amod, sign and stepf (User Guide 9.3).

      node resources/tests/facsimile/test-features.js

  Exit status is 0 when every check passes. Nothing here needs the network.
*/
'use strict';
const path = require('path');

const jsDir = path.join(__dirname, '..', '..', 'js');
const FacsimileModel = require(path.join(jsDir, 'facsimile-model.js'));
const FacsimileODE = require(path.join(jsDir, 'facsimile-ode.js'));
const { FACSIMILE_DEFAULT_MODEL, FACSIMILE_PRESETS } = require(path.join(jsDir, 'facsimile-default.js'));

let checks = 0;
const failures = [];
function check(label, got, want = true) {
  checks++;
  const ok = got === want;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${got} (expected ${want})`}`);
  if (!ok) failures.push(label);
}
function near(label, got, want, tol) {
  const rel = want === 0 ? Math.abs(got) : Math.abs(got - want) / Math.abs(want);
  checks++;
  const ok = rel <= tol;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${got} against ${want}, relative ${rel.toExponential(2)} > ${tol}`}`);
  if (!ok) failures.push(label);
}
function throws(label, fn, fragment) {
  checks++;
  let message = '';
  try { fn(); } catch (e) { message = e.message; }
  const ok = message.includes(fragment);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: got "${message || 'no error'}", wanted "${fragment}"`}`);
  if (!ok) failures.push(label);
}
const at = (model, obs, name) => obs[model.observeNames.indexOf(name)];

/* ======================================================================
   1 and 2. Named reaction rates, and deriv()
   ====================================================================== */
console.log('\n--- named rates and deriv() ---');
{
  // A + B -> C at kf, C -> A + B at kb, and a constant source of A.
  const model = FacsimileModel.compile(`
<SETTINGS>
KF = 3.0
KB = 0.5
SRC = 0.25
<SPECIES>
A B C
<INITIAL>
A = 2
B = 1.5
C = 0.75
<EQUATIONS>
Z = 0
<REACTIONS>
RMAIN%KF%KB : A + B = C
= A, rf = SRC, rate = RSRC
<OUTPUTS>
DA = deriv(A)
DC = deriv(C)
SUM = RMAIN + RSRC
`);
  check('the rates are observables, in the order the reactions were written',
    model.rateNames.join(','), 'RMAIN,RSRC');
  const y = model.initialState(0);
  const obs = model.observe(0, y);
  const f = new Float64Array(model.nspecies);
  model.rhs(0, y, f);
  const [A, B, C] = [y[0], y[1], y[2]];
  near('a named reversible rate is kf[A][B] - kb[C]', at(model, obs, 'RMAIN'), 3 * A * B - 0.5 * C, 1e-12);
  near('a named absolute rate is the expression itself', at(model, obs, 'RSRC'), 0.25, 1e-12);
  near('deriv(A) is the derivative the solver integrates', at(model, obs, 'DA'), f[0], 1e-12);
  near('deriv(C) too', at(model, obs, 'DC'), f[2], 1e-12);
  near('and deriv(A) is the sum of the fluxes that reach A',
    at(model, obs, 'DA'), 0.25 - (3 * A * B - 0.5 * C), 1e-12);
  near('a rate may be used in an output', at(model, obs, 'SUM'),
    at(model, obs, 'RMAIN') + at(model, obs, 'RSRC'), 1e-12);

  // The rates and the derivatives must still be right away from t = 0, and
  // the analytic Jacobian must not have been disturbed by emitting them.
  const res = FacsimileODE.runModel(model, { solver: 'ndf', tend: 5, rtol: 1e-10, atol: 1e-16 });
  const k = res.t.length - 1;
  const o2 = model.observe(res.t[k], res.y[k]);
  model.rhs(res.t[k], res.y[k], f);
  near('deriv() at the end of a run', at(model, o2, 'DA'), f[0], 1e-12);
  check('the Jacobian still matches finite differences',
    model.verifyJacobian(2.5, res.y[k]).discrepancies.length, 0);
}
{
  // Two reactions may not share a name, and a name may not be taken twice.
  throws('two reactions with one name are refused',
    () => FacsimileModel.compile(`
<SPECIES>
A B
<EQUATIONS>
Z = 0
<REACTIONS>
R%1.0 : A = B
R%2.0 : B = A
`), 'Two reactions are both called "R"');
  throws('a rate may not take a name already in use',
    () => FacsimileModel.compile(`
<CONSTANTS>
R = 1
<SPECIES>
A B
<EQUATIONS>
Z = 0
<REACTIONS>
R%1.0 : A = B
`), 'already the name of something else');
  throws('deriv() is refused outside <OUTPUTS>',
    () => FacsimileModel.compile(`
<SPECIES>
A B
<EQUATIONS>
Z = deriv(A)
<REACTIONS>
%1.0 : A = B
`), 'deriv');
}

/* ======================================================================
   3. Event direction and the stop action
   ====================================================================== */
console.log('\n--- event direction and stopping ---');
{
  // A decays at 0.5/s from 1, so it falls through 0.5 at ln 2 / 0.5.
  const half = Math.log(2) / 0.5;
  const build = (clause) => FacsimileModel.compile(`
<SETTINGS>
K = 0.5
ON = 1
<SPECIES>
A B
<INITIAL>
A = 1
<EQUATIONS>
Z = 0
<REACTIONS>
A = B, kf = K*ON
<EVENTS>
${clause}
<OUTPUTS>
AA = A
`);
  const run = (m) => FacsimileODE.runModel(m, { solver: 'ndf', tend: 10, rtol: 1e-10, atol: 1e-16 });

  let res = run(build('A - 0.5, down, stop'));
  near('a downward event fires where the crossing is', res.events[0].t, half, 1e-7);
  near('and the run ends there', res.t[res.t.length - 1], half, 1e-7);
  check('the log says the event stopped it', res.events[0].stop);
  check('and so do the statistics', !!res.stats.stoppedBy);

  res = run(build('A - 0.5, stop'));
  check('an event with no direction is upward only, so a fall does not fire it', res.events.length, 0);
  near('and the run goes to the end', res.t[res.t.length - 1], 10, 1e-12);

  res = run(build('A - 0.5, both, stop'));
  near('"both" fires on the fall', res.events[0].t, half, 1e-7);

  res = run(build('A - 0.5, down, ON = 0'));
  check('an event may still only assign, and the run carries on', res.events.length, 1);
  check('the assignment is reported', res.events[0].changed.join(''), 'ON = 0');
  near('and the decay stops where it fired', res.y[res.y.length - 1][0], 0.5, 1e-6);
  check('a pure assignment does not stop the run', res.stats.stoppedBy, null);

  throws('an event that does nothing is refused',
    () => build('A - 0.5, down'), 'must do something');
  throws('two directions are refused', () => build('A - 0.5, up, down, stop'), 'only give one direction');
}

/* ======================================================================
   4. The output grid
   ====================================================================== */
console.log('\n--- output times ---');
{
  const model = FacsimileModel.compile(`
<SETTINGS>
K = 0.5
<SPECIES>
A B
<INITIAL>
A = 1
<EQUATIONS>
Z = 0
<REACTIONS>
A = B, kf = K
<TIMES>
0 .. 10 lin 11
<OUTPUTS>
AA = A
`);
  check('the times are on the model, in seconds', Array.from(model.outputTimes).join(','),
    '0,1,2,3,4,5,6,7,8,9,10');
  const res = FacsimileODE.runModel(model, { solver: 'ndf', tend: 10, rtol: 1e-10, atol: 1e-16 });
  check('every asked-for time is reported', res.grid.t.length, 11);
  let worst = 0;
  for (let i = 0; i < res.grid.t.length; i++) {
    const exact = Math.exp(-0.5 * res.grid.t[i]);
    worst = Math.max(worst, Math.abs(res.grid.y[i][0] - exact) / exact);
  }
  console.log(`      worst relative error on the grid: ${worst.toExponential(2)}`);
  // The interpolant is the cubic through both ends and both derivatives, so
  // it is far better than the linear interpolation the comparison in run.js
  // falls back on -- but it is still an interpolant, not the solver's own.
  check('the interpolated values are accurate to 1e-7', worst < 1e-7);

  // Every solver on the menu is served by the same code, so one other is
  // enough to show that it does not depend on the built-in one.
  const bdf = FacsimileODE.runModel(model, { solver: 'bdf', tend: 10, rtol: 1e-10, atol: 1e-16 });
  check('a second solver gets the same grid', bdf.grid.t.length, 11);
  near('and agrees on it', bdf.grid.y[5][0], res.grid.y[5][0], 1e-7);

  // Times past the end of the run are simply not reached.
  const short = FacsimileODE.runModel(model, { solver: 'ndf', tend: 4.5, rtol: 1e-8, atol: 1e-16 });
  check('a grid time after the end of the run is left out', short.grid.t.length, 5);

  const hours = FacsimileModel.compile(`
<SPECIES>
A B
<INITIAL>
A = 1
<EQUATIONS>
Z = 0
<REACTIONS>
A = B, kf = 1.0
<TIMES h>
1 2
0.5 + 0.5 * 2
1 .. 100 log 3
`);
  check('the unit in the header is applied, and the times are sorted and unique',
    Array.from(hours.outputTimes, (v) => v / 3600).join(','), '0.5,1,1.5,2,10,100');
  throws('a malformed <TIMES> line says so', () => FacsimileModel.compile(`
<SPECIES>
A
<EQUATIONS>
Z = 0
<REACTIONS>
%1.0 : A =
<TIMES>
1 .. 10 log
`), '<TIMES> line');
  throws('an unknown time unit says so', () => FacsimileModel.compile(`
<SPECIES>
A
<EQUATIONS>
Z = 0
<REACTIONS>
%1.0 : A =
<TIMES furlongs>
1
`), 'the unit must be one of');
}

/* ======================================================================
   5. The functions FACSIMILE has and this did not
   ====================================================================== */
console.log('\n--- new functions ---');
{
  const x = 0.7;
  const model = FacsimileModel.compile(`
<CONSTANTS>
X = ${x}
<SPECIES>
A B
<INITIAL>
A = 0.7
<EQUATIONS>
Z = 0
<REACTIONS>
A = B, kf = 1.0
<OUTPUTS>
FSIN = sin(X)
FCOS = cos(X)
FTAN = tan(X)
FATAN = atan(X)
FARTAN = artan(X)
FTANH = tanh(X)
FSIGN = sign(0 - X)
FSTEPF = stepf(0)
FSTEP = step(0)
FAMOD = amod(9.9, 8.0)
`);
  const obs = model.observe(0, model.initialState(0));
  near('sin', at(model, obs, 'FSIN'), Math.sin(x), 1e-15);
  near('cos', at(model, obs, 'FCOS'), Math.cos(x), 1e-15);
  near('tan', at(model, obs, 'FTAN'), Math.tan(x), 1e-15);
  near('atan', at(model, obs, 'FATAN'), Math.atan(x), 1e-15);
  near('artan is FACSIMILE’s spelling of the same thing',
    at(model, obs, 'FARTAN'), Math.atan(x), 1e-15);
  near('tanh', at(model, obs, 'FTANH'), Math.tanh(x), 1e-15);
  check('sign', at(model, obs, 'FSIGN'), -1);
  // The one place the two differ: FACSIMILE's STEPF is 1 at zero, and the
  // step() this page already had is 0 there.
  check('stepf(0) is 1, as FACSIMILE has it', at(model, obs, 'FSTEPF'), 1);
  check('step(0) is still 0', at(model, obs, 'FSTEP'), 0);
  near('amod(9.9, 8) is 1.9', at(model, obs, 'FAMOD'), 1.9, 1e-12);

  // Used in a rate law, each has to carry its own derivative into the
  // Jacobian; finite differences are the judge.
  const rates = FacsimileModel.compile(`
<CONSTANTS>
W = 1.3
<SPECIES>
A B C
<INITIAL>
A = 0.8
B = 0.3
C = 0.2
<EQUATIONS>
Z = 0
<REACTIONS>
A = B, kf = 1 + sin(A) + cos(B) + tanh(A*B)
B = C, kf = 2 + atan(A + B) + tan(0.3*C)
C = A, kf = 0.5 + amod(A + 3*B, W) + abs(sin(C))
`);
  const y = rates.initialState(0);
  const v0 = rates.verifyJacobian(0, y);
  const v1 = rates.verifyJacobian(1.5, Float64Array.from([0.41, 0.52, 0.63]));
  console.log(`      Jacobian entries checked: ${v0.checked} at t = 0, ${v1.checked} at t = 1.5`);
  check('the new functions differentiate correctly at t = 0', v0.discrepancies.length, 0);
  check('and away from it', v1.discrepancies.length, 0);
  check('nothing appears outside the pattern', !v0.outsidePattern && !v1.outsidePattern);
}

/* ======================================================================
   The canister model: the features in the model the page ships
   ====================================================================== */
console.log('\n--- the built-in canister model ---');
{
  const preset = FACSIMILE_PRESETS.find((p) => p.id === '13g');
  const model = FacsimileModel.compile(FACSIMILE_DEFAULT_MODEL, { settings: preset.settings });
  check('the corrosion and water-release rates are named',
    model.rateNames.join(','), 'RH2OIN,ROXID,ROXIDW,RANOX');
  check('it asks for output times', model.outputTimes.length > 0);

  const res = FacsimileODE.runModel(model, {
    solver: 'ndf', tend: 2 * 365.25 * 86400, rtol: 1e-6, atol: 1e-30, nonNegative: true,
  });
  check('the grid is filled as the run goes', res.grid.t.length > 100);
  check('and never runs past the end of the run',
    res.grid.t[res.grid.t.length - 1] <= res.t[res.t.length - 1] + 1e-6);

  // The two corrosion outputs are now multiples of the reactions' own rates
  // rather than a second copy of the rate laws. They must still be what the
  // Python port and the FACSIMILE model reported.
  const obs = model.observe(res.t[res.t.length - 1], res.y[res.y.length - 1]);
  near('dDUMO2 is three times the oxic corrosion rate',
    at(model, obs, 'dDUMO2'), 3 * at(model, obs, 'ROXID'), 1e-14);
  near('dDUMH2 is four times the anoxic one',
    at(model, obs, 'dDUMH2'), 4 * at(model, obs, 'RANOX'), 1e-14);
  const c1 = at(model, obs, 'c1'), c2 = at(model, obs, 'c2');
  const f1 = at(model, obs, 'f1'), f2 = at(model, obs, 'f2');
  near('and both still equal the rate laws they replaced',
    at(model, obs, 'dDUMO2'), c1 * 3 / 4 * f1 * f2, 1e-12);
  near('(the anoxic one too)', at(model, obs, 'dDUMH2'), c2 * 4 / 3 * (1 - f1) * f2, 1e-12);

  // GHNO3 is the original's apparent G-value, which needed five dummy
  // species there and one line of deriv() here.
  const f = new Float64Array(model.nspecies);
  model.rhs(res.t[res.t.length - 1], res.y[res.y.length - 1], f);
  const idx = (nm) => model.species.indexOf(nm);
  const want = (f[idx('HNO3')] + f[idx('HNO2')] + f[idx('NO2')] + f[idx('NO3')] + f[idx('NO')])
    / at(model, obs, 'DOSER');
  near('GHNO3 is the five derivatives over the dose rate', at(model, obs, 'GHNO3'), want, 1e-12);

  // A sanity check on the sign as well as the arithmetic: early in the run the
  // radiolysis is fixing nitrogen and the apparent G-value is positive; by two
  // years the oxygen is gone, the nitric acid is being destroyed again, and it
  // has turned round. That is the quantity the original reported.
  const early = model.observe(res.t[20], res.y[20]);
  console.log(`      GHNO3 at t = ${(res.t[20] / 3600).toExponential(2)} h: ${
    at(model, early, 'GHNO3').toExponential(3)} per 100 eV;`
    + ` at two years: ${at(model, obs, 'GHNO3').toExponential(3)}`);
  check('GHNO3 is positive while nitrogen is being fixed', at(model, early, 'GHNO3') > 0);
}

/* ======================================================================
   6. Algebraic variables: the model is a differential-algebraic system
   ====================================================================== */
console.log('\n--- algebraic variables ---');
{
  // The circle of the FACSIMILE User Guide 18.1.2: y1' = y2, y1^2 + y2^2 = 1,
  // started at its own documented y2 = -0.9 where the constraint wants
  // -sqrt(3)/2. Exact: y1 = sin(pi/6 - t), y2 = -cos(pi/6 - t).
  const circle = FacsimileModel.compile(`
<SPECIES>
Y1
<ALGEBRAIC>
Y2 : Y1*Y1 + Y2*Y2 - 1
<INITIAL>
Y1 = 0.5
Y2 = -0.9
<EQUATIONS>
Z = 0
<REACTIONS>
= Y1, rf = Y2
`, { clampNegative: false });
  check('the algebraic variable is a state variable', circle.species.join(','), 'Y1,Y2');
  check('and the mass matrix says which is which', Array.from(circle.mass).join(','), '1,0');
  check('it is not reported as an unreacting species', circle.warnings.length, 0);

  const c = Math.PI / 6;
  const res = FacsimileODE.runModel(circle, { solver: 'ndf', tend: 1.5, rtol: 1e-10, atol: 1e-12 });
  const start = res.stats.consistentStart;
  check('the start is put on its constraint before the run', start.solved);
  near('and the constraint is then satisfied', start.residual, 0, 1e-12);
  near('having moved the variable from -0.9 to -sqrt(3)/2',
    res.y[0][1], -Math.sqrt(3) / 2, 1e-12);

  let worst = 0, worstG = 0;
  for (let k = 0; k < res.t.length; k++) {
    const t = res.t[k];
    worst = Math.max(worst, Math.abs(res.y[k][0] - Math.sin(c - t)), Math.abs(res.y[k][1] + Math.cos(c - t)));
    worstG = Math.max(worstG, Math.abs(res.y[k][0] ** 2 + res.y[k][1] ** 2 - 1));
  }
  console.log(`      ${res.stats.nsteps} steps; worst error ${worst.toExponential(2)}, `
    + `worst constraint residual ${worstG.toExponential(2)}`);
  check('the solution follows the exact one', worst < 1e-8);
  check('and stays on the constraint throughout', worstG < 1e-9);

  // Robertson's problem in its usual index-1 form. The values at the end are
  // the ones every DAE code is checked against.
  const rob = FacsimileModel.compile(`
<SPECIES>
Y1 Y2
<ALGEBRAIC>
Y3 : Y1 + Y2 + Y3 - 1
<INITIAL>
Y1 = 1
<EQUATIONS>
Z = 0
<REACTIONS>
Y1 = Y2, kf = 0.04
Y2 + Y3 = Y1 + Y3, kf = 1.0E4
Y2 = , rf = 3.0E7*Y2*Y2
<TIMES>
40 4000000000 40000000000
`, { clampNegative: false });
  check('a reaction may use an algebraic variable as a catalyst', rob.nalgebraic, 1);
  const rr = FacsimileODE.runModel(rob, { solver: 'ndf', tend: 4e10, rtol: 1e-8, atol: 1e-12 });
  const at40 = rr.grid.y[0], atEnd = rr.grid.y[rr.grid.y.length - 1];
  console.log(`      Robertson in ${rr.stats.nsteps} steps; at t = 40 y = `
    + Array.from(at40, (v) => v.toExponential(6)).join(', '));
  near('Robertson y1 at t = 40', at40[0], 0.71582706, 1e-6);
  near('Robertson y2 at t = 40', at40[1], 9.1855491e-6, 1e-5);
  near('Robertson y3 at t = 40', at40[2], 0.28416375, 1e-6);
  near('Robertson y1 at t = 4e10', atEnd[0], 5.2083e-8, 1e-3);
  // y3 is 1 - y1 - y2 exactly, so it is 1 less about 5.2e-8 rather than 1.
  near('Robertson y3 at t = 4e10', atEnd[2], 1 - atEnd[0] - atEnd[1], 1e-15);
  near('and that is 1 to seven figures', atEnd[2], 0.99999995, 1e-7);
  let gg = 0;
  for (const y of rr.grid.y) gg = Math.max(gg, Math.abs(y[0] + y[1] + y[2] - 1));
  // The output grid interpolates between accepted steps, and a point between
  // two states that each satisfy the constraint does not satisfy it; every
  // grid point is put back on it, so this is exact rather than merely small.
  check('the reported grid satisfies the constraint exactly', gg, 0);

  throws('a ported solver is refused rather than given a mass matrix it ignores',
    () => FacsimileODE.runModel(rob, { solver: () => {}, tend: 1 }), 'differential-algebraic');
  throws('a reaction may not change an algebraic variable',
    () => FacsimileModel.compile(`
<SPECIES>
A
<ALGEBRAIC>
C : C - 2*A
<EQUATIONS>
Z = 0
<REACTIONS>
A = C, kf = 1.0
`), 'has no rate of change');
  throws('and it may not also be declared a species',
    () => FacsimileModel.compile(`
<SPECIES>
A C
<ALGEBRAIC>
C : C - 2*A
<EQUATIONS>
Z = 0
<REACTIONS>
A = , kf = 1.0
`), 'cannot be both');
  throws('a constraint that does not determine its variable says so',
    () => FacsimileODE.runModel(FacsimileModel.compile(`
<SPECIES>
A
<ALGEBRAIC>
C : A - 1
<INITIAL>
A = 2
<EQUATIONS>
Z = 0
<REACTIONS>
A = , kf = 1.0
`), { solver: 'ndf', tend: 1, rtol: 1e-6, atol: 1e-9 }), 'could not be put on their constraints');

  // A model with nothing algebraic must be handed a mass matrix of ones and
  // integrated by the same arithmetic as before.
  const plain = FacsimileModel.compile(`
<SPECIES>
A B
<INITIAL>
A = 1
<EQUATIONS>
Z = 0
<REACTIONS>
A = B, kf = 0.5
`);
  check('a model with no constraints has an identity mass matrix',
    Array.from(plain.mass).every((v) => v === 1) && plain.nalgebraic === 0);
}

/* ======================================================================
   7. WHEN and WHENEVER: value lists, and firing once
   ====================================================================== */
console.log('\n--- event value lists, and once ---');
{
  const build = (clause) => FacsimileModel.compile(`
<SETTINGS>
N = 0
<SPECIES>
A B
<INITIAL>
A = 1
<EQUATIONS>
S = sin(t)
Z = 0
<REACTIONS>
A = B, kf = 0.0
<EVENTS>
${clause}
<OUTPUTS>
AA = A
`);
  const run = (m, o) => FacsimileODE.runModel(m, { solver: 'ndf', tend: 20, rtol: 1e-10, atol: 1e-14, ...o });

  const list = build('t = 1 2 3 4 5, N = N + 1');
  check('a value list becomes one event per value', list.nevents, 5);
  check('and each says which value it is',
    list.events.map((e) => e.shown).join(','), 't = 1,t = 2,t = 3,t = 4,t = 5');
  let r = run(list);
  check('all five fire', r.events.length, 5);
  near('at the values themselves', r.events[3].t, 4, 1e-9);

  check('the increment form of <TIMES> works here too',
    build('t = 0 + 2 * 4, N = N + 1').nevents, 5);

  // sin(t) crosses 0.5 upward at 0.5236 and every 2*pi after it.
  r = run(build('S - 0.5, N = N + 1'));
  check('an event fires at every crossing by default, as WHENEVER does', r.events.length, 4);
  r = run(build('S - 0.5, once, N = N + 1'));
  check('and once makes it fire one time only, as WHEN does', r.events.length, 1);
  near('at the first crossing', r.events[0].t, Math.asin(0.5), 1e-8);
  check('the log says it was a one-shot', r.events[0].once, true);

  r = run(build('S = 0.5 0.9, both, once, N = N + 1'));
  check('in a value list, once applies to each value separately', r.events.length, 2);

  // A crossing pair inside one step is invisible to a sign test. This is not
  // a defect of the search but of how often it is asked, and capping the
  // step is the remedy -- worth a check because it is silent when it bites.
  const fast = build('S = 0.9, both, N = N + 1');
  const loose = run(fast);
  const capped = run(fast, { hmax: 0.5 });
  console.log(`      crossings of sin(t) = 0.9 found: ${loose.events.length} uncapped, `
    + `${capped.events.length} with hmax 0.5`);
  check('capping the step finds every crossing of a fast trigger', capped.events.length, 7);
  near('and puts the second one where it belongs', capped.events[1].t, Math.PI - Math.asin(0.9), 1e-6);
}

/* ======================================================================
   8. The worked example that ships with the page
   ====================================================================== */
console.log('\n--- the Langmuir example ---');
{
  const fs = require('fs');
  const file = path.join(__dirname, '..', '..', 'data', 'facsimile-langmuir.fac');
  const model = FacsimileModel.compile(fs.readFileSync(file, 'utf8'));
  check('it has one algebraic variable', model.nalgebraic, 1);
  check('and four events, three of them a value list', model.nevents, 4);
  const res = FacsimileODE.runModel(model, { solver: 'ndf', tend: 20, rtol: 1e-9, atol: 1e-12 });

  const K = 3, QMAX = 2, KLOSS = 0.25;
  const start = res.stats.consistentStart;
  check('the guessed coverage is moved onto the isotherm', start.solved && start.moved > 0.5);
  near('to the value the isotherm gives', res.y[0][1], QMAX * K * 1 / (1 + K * 1), 1e-12);

  // C = exp(-k t) exactly, and Q follows from it, at every reported time.
  let worstC = 0, worstQ = 0;
  for (let i = 0; i < res.grid.t.length; i++) {
    const t = res.grid.t[i], C = res.grid.y[i][0], Q = res.grid.y[i][1];
    const exactC = Math.exp(-KLOSS * t);
    worstC = Math.max(worstC, Math.abs(C - exactC) / exactC);
    worstQ = Math.max(worstQ, Math.abs(Q - QMAX * K * C / (1 + K * C)));
  }
  console.log(`      ${res.stats.nsteps} steps; worst error in C ${worstC.toExponential(2)}, `
    + `worst departure from the isotherm ${worstQ.toExponential(2)}`);
  // Loose against rtol because the run is restarted at each of the four
  // events, and each restart drops the order back to one.
  check('the gas follows exp(-kt)', worstC < 1e-7);
  check('and the coverage is on its isotherm at every reported time', worstQ, 0);

  const ln = (x) => Math.log(x) / KLOSS;
  check('all four events fire', res.events.length, 4);
  near('at C = 0.5', res.events[0].t, ln(2), 1e-7);
  near('at C = 0.25', res.events[1].t, ln(4), 1e-7);
  near('at C = 0.1', res.events[2].t, ln(10), 1e-7);
  near('and the run stops at C = 0.05', res.events[3].t, ln(20), 1e-7);
  check('which is what ended it', !!res.stats.stoppedBy);
  near('and where the last point is', res.t[res.t.length - 1], ln(20), 1e-7);
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) console.log('failed: ' + failures.join(', '));
process.exit(failures.length ? 1 : 0);
