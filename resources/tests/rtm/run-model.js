#!/usr/bin/env node
/* ==========================================================================
   COMPILE AND RUN A MODEL TEXT, FOR A SCRIPT THAT IS NOT JAVASCRIPT

   Reads { text, tend, rtol, atol, solver, teval } as JSON on stdin and writes
   { species, t, y } back on stdout, y being one row per requested time.
   ========================================================================== */
'use strict';

const path = require('path');

const jsDir = path.join(__dirname, '..', '..', 'js');
require(path.join(jsDir, 'facsimile-model.js'));
const FacsimileODE = require(path.join(jsDir, 'facsimile-solver.js'));
const RtmModel = require(path.join(jsDir, 'rtm-model.js'));
const OdeJulia = require(path.join(jsDir, 'facsimile-ode-julia.js'));

let input = '';
process.stdin.on('data', (d) => { input += d; });
process.stdin.on('end', () => {
  const req = JSON.parse(input);
  let model;
  try {
    model = RtmModel.compile(req.text);
  } catch (e) {
    process.stdout.write(JSON.stringify({ error: `compile: ${e.message}` }));
    return;
  }
  try {
    const res = FacsimileODE.runModel(model, {
      solver: OdeJulia.is(req.solver) ? OdeJulia.solver(req.solver) : (req.solver || 'ndf'),
      tend: req.tend,
      rtol: req.rtol,
      atol: req.atol,
      nonNegative: req.nonNegative !== false,
      stagnationTol: 0.5,       // as rtm-worker.js sets it; see the note there
      maxSteps: req.maxSteps || 2000000,
      maxPoints: 1e9,          // every step: the caller interpolates itself
    });
    /*
      Linear interpolation between stored steps. The comparison is against
      another code's own output times, which are not ours, and a straight line
      across one accepted step is well inside the tolerance the step was
      chosen for -- the check itself only claims three or four digits.
    */
    const t = res.t;
    const rows = (req.teval || [t[t.length - 1]]).map((want) => {
      let hi = 1;
      while (hi < t.length - 1 && t[hi] < want) hi++;
      const lo = hi - 1;
      const span = t[hi] - t[lo];
      const f = span > 0 ? (want - t[lo]) / span : 0;
      return Array.from(res.y[lo], (v, i) => v + f * (res.y[hi][i] - v));
    });
    process.stdout.write(JSON.stringify({
      species: model.speciesNames,
      t: req.teval || [t[t.length - 1]],
      y: rows,
      stats: { nsteps: res.stats.nsteps, nfailed: res.stats.nfailed, npoints: t.length },
    }));
  } catch (e) {
    process.stdout.write(JSON.stringify({ error: `run: ${e.message}` }));
  }
});
