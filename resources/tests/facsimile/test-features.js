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

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) console.log('failed: ' + failures.join(', '));
process.exit(failures.length ? 1 : 0);
