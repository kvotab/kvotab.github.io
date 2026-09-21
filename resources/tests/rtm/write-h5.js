#!/usr/bin/env node
/* ==========================================================================
   WRITE A RUN AS AN HDF5 FILE, THE WAY THE PAGE DOES

   Runs a model through the page's own worker handler and hands the reply to
   rtm-hdf5.js, so that what lands on disk is byte for byte what rtm.html
   sends the HDF5 Browser. test-hdf5.py opens the result with h5py.

     node resources/tests/rtm/write-h5.js out.h5                 # the built-in model
     node resources/tests/rtm/write-h5.js out.h5 --example batch-first
     node resources/tests/rtm/write-h5.js out.h5 --text model.rtm --tend 100

   Prints one line of JSON about the run, for the caller to check against.
   ========================================================================== */
'use strict';

const fs = require('fs');
const path = require('path');

const jsDir = path.join(__dirname, '..', '..', 'js');
global.FacsimileModel = require(path.join(jsDir, 'facsimile-model.js'));
global.FacsimileODE = require(path.join(jsDir, 'facsimile-ode.js'));
global.RtmModel = require(path.join(jsDir, 'rtm-model.js'));
global.FacsimileOdeJulia = require(path.join(jsDir, 'facsimile-ode-julia.js'));
const { RTM_DEFAULT_MODEL } = require(path.join(jsDir, 'rtm-default.js'));
const { RTM_EXAMPLES } = require(path.join(jsDir, 'rtm-examples.js'));
const RtmHDF5 = require(path.join(jsDir, 'rtm-hdf5.js'));
const { handleRtmMessage } = require(path.join(jsDir, 'rtm-worker.js'));

const args = process.argv.slice(2);
const out = args.shift();
if (!out) { console.error('usage: write-h5.js <out.h5> [--example id] [--text file] [--tend t]'); process.exit(2); }
const opt = { cell: 0, layer: 0 };
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === '--example') opt.example = args[++i];
  else if (a === '--text') opt.textFile = args[++i];
  else if (a === '--tend') opt.tend = Number(args[++i]);
  else if (a === '--cell') opt.cell = Number(args[++i]);
  else if (a === '--layer') opt.layer = Number(args[++i]);
  else { console.error(`unknown argument ${a}`); process.exit(2); }
}

let text = RTM_DEFAULT_MODEL;
let title = 'Reactive transport';
if (opt.example) {
  const e = RTM_EXAMPLES.find((x) => x.id === opt.example);
  if (!e) { console.error(`no example "${opt.example}"`); process.exit(2); }
  text = e.text;
  title = e.label;
}
if (opt.textFile) text = fs.readFileSync(opt.textFile, 'utf8');

// The solver options the panel would send, and the same defaults it starts on.
const solver = {
  method: 'ndf', tend: opt.tend, rtol: 1e-6, atol: 1e-20, matrix: 'auto', norm: 'max',
  maxSteps: 500000, maxPoints: 4000, nonNegative: true,
};

let reply = null;
handleRtmMessage({ type: 'run', id: 1, text, solver }, (msg) => {
  if (msg.type === 'result') reply = msg;
  else if (msg.type === 'error') { console.error(`${msg.stage}: ${msg.error}`); process.exit(1); }
});
if (!reply) { console.error('the run produced nothing'); process.exit(1); }

const bytes = RtmHDF5.resultFile(reply, {
  solver, text, cell: opt.cell, layer: opt.layer, title,
});
fs.writeFileSync(out, bytes);
console.log(JSON.stringify({
  bytes: bytes.length,
  points: reply.n,
  species: reply.model.species.length,
  cells: reply.model.cells,
  fracture: reply.model.fracture,
  stride: reply.model.stride,
  transport: reply.model.transport,
  tend: reply.t[reply.n - 1],
  timeUnit: reply.model.timeUnit,
}));
