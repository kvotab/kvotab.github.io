#!/usr/bin/env node
/*
  What keeps a run from taking the machine with it.

  A run that needs hundreds of thousands of steps -- which this model does as
  soon as the step size is capped, and which the solvers that have since been
  taken off the page did unprompted -- used to store every one of them, so the
  memory climbed at about 3 MB a second until the tab died. There is a ceiling
  on the stored points now, and this checks that it holds, that the two ends of
  the run survive the thinning, and that a run which cannot finish says so
  instead of grinding.

      node resources/tests/facsimile/test-limits.js

  Exit status is 0 when every check passes.
*/
'use strict';
const path = require('path');

const jsDir = path.join(__dirname, '..', '..', 'js');
const FacsimileModel = require(path.join(jsDir, 'facsimile-model.js'));
const FacsimileODE = require(path.join(jsDir, 'facsimile-solver.js'));
const { FACSIMILE_DEFAULT_MODEL, FACSIMILE_PRESETS } = require(path.join(jsDir, 'facsimile-default.js'));

const YEAR = 365.25 * 86400;
let checks = 0;
const failures = [];

function check(label, got, want = true) {
  checks++;
  const ok = got === want;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${got} (expected ${want})`}`);
  if (!ok) failures.push(label);
}

const preset = FACSIMILE_PRESETS.find((p) => p.id === '13g');
const model = FacsimileModel.compile(FACSIMILE_DEFAULT_MODEL, { settings: preset.settings });
const tend = 500 * YEAR;

// --- the ceiling on the stored points ---------------------------------------
for (const cap of [1000, 4000]) {
  const res = FacsimileODE.runModel(model, {
    solver: 'ndf', tend, rtol: 1e-5, atol: 1e-30, nonNegative: true, maxPoints: cap,
  });
  const t = res.t;
  const last = t[t.length - 1];
  let increasing = true;
  for (let i = 1; i < t.length; i++) if (!(t[i] > t[i - 1])) increasing = false;
  console.log(`\ncap ${cap}: ${res.stats.nsteps} steps kept as ${t.length} points, one in ${res.stats.stride}`);
  check(`cap ${cap}: the store stays inside it`, t.length <= cap);
  check(`cap ${cap}: it is not thinned further than it needs`, t.length > cap / 2 - 2);
  check(`cap ${cap}: the run still starts at zero`, t[0] === 0);
  check(`cap ${cap}: and still ends where it was asked to`, Math.abs(last - tend) < 1e-6 * tend);
  check(`cap ${cap}: the clock still only goes forwards`, increasing);
  check(`cap ${cap}: every point still has a state`, res.y.length === t.length);
  check(`cap ${cap}: and the states are the right width`, res.y[t.length - 1].length === model.nspecies);
}

// --- an ordinary run is not thinned at all ----------------------------------
{
  const res = FacsimileODE.runModel(model, {
    solver: 'ndf', tend, rtol: 1e-5, atol: 1e-30, nonNegative: true,
  });
  console.log(`\nno cap given: ${res.stats.nsteps} steps, ${res.t.length} points`);
  check('a run inside the default ceiling keeps every step', res.stats.stride, 1);
  check('and reports how many points that is', res.stats.points, res.t.length);
}

// --- a run that cannot finish says so ---------------------------------------
{
  // A maximum step of a ten-thousandth of a year over five hundred of them is
  // five million steps, against the five thousand the same case takes when the
  // solver chooses for itself. It runs out of the budget long before the end.
  let failed = null;
  try {
    FacsimileODE.runModel(model, {
      solver: 'ndf', tend, rtol: 1e-5, atol: 1e-30, nonNegative: true,
      hmax: 1e-4 * YEAR, maxSteps: 4000,
    });
  } catch (e) {
    failed = e;
  }
  console.log(`\nwith a budget of 4000 steps: ${failed ? failed.message.slice(0, 80) : 'it finished'}`);
  check('a run out of its step budget stops', !!failed);
  check('and says that is what happened', failed ? failed.code : '', 'steps');
  check('and hands back what it had integrated', !!(failed && failed.partial && failed.partial.t.length > 1));
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) console.log('failed: ' + failures.join(', '));
process.exit(failures.length ? 1 : 0);
