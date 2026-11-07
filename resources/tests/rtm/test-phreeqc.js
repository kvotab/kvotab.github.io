#!/usr/bin/env node
/* ==========================================================================
   RTM.HTML AND PHREEQC: THE HAND-OFF, AGAINST THINGS WITH KNOWN ANSWERS

       node resources/tests/rtm/test-phreeqc.js

   The reading of databases and reactions needs no PHREEQC. The rest runs
   the page's own PHREEQC, vendors/phreeqc (IPhreeqc compiled to
   WebAssembly), on the phreeqc.dat that comes with it.

   With RTM_PHREEQC_PYTHON naming a Python that has phreeqpython, the same
   inputs also go through that PHREEQC (phreeqc-bridge.py), and the two must
   agree: the WebAssembly build against a native one.

   What is checked with PHREEQC running:
     * a water written as a model, compiled by rtm.html, lands back on
       PHREEQC's molalities (its own speciation, from the conditional
       constants alone);
     * the database's log K, worked back from PHREEQC's activities, is the
       database's own;
     * a run of that model, read back through PHREEQC, starts at exactly the
       water's pH and calcite saturation, and with acid added follows PHREEQC
       adding the same acid by itself;
     * with salt added instead, the drift of the activity coefficients is
       reported, and is what moved the answer;
     * the built-in model: the species PHREEQC knows are counted, the
       hydrated electron and the radicals are not, and the missing
       counter-ion is noticed;
     * the jobs as the page sends them, through the handler its worker runs;
     * the database the page loads as a script is the file, character for
       character.

   Exit status is 0 when every check that ran passed.
   ========================================================================== */
'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const root = path.join(__dirname, '..', '..', '..');
const jsDir = path.join(root, 'resources', 'js');
global.FacsimileModel = require(path.join(jsDir, 'facsimile-model.js'));
global.FacsimileODE = require(path.join(jsDir, 'facsimile-solver.js'));
global.RtmModel = require(path.join(jsDir, 'rtm-model.js'));
global.FacsimileOdeJulia = require(path.join(jsDir, 'facsimile-ode-julia.js'));
const { handleRtmMessage } = require(path.join(jsDir, 'rtm-worker.js'));
const { RTM_DEFAULT_MODEL } = require(path.join(jsDir, 'rtm-default.js'));
const P = require(path.join(jsDir, 'rtm-phreeqc.js'));
const E = require(path.join(jsDir, 'rtm-phreeqc-engine.js'));
global.RtmPhreeqc = P;

let checks = 0;
const failures = [];
function check(label, ok, detail) {
  checks++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `: ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

/* ======================================================================
   1. Reading, without PHREEQC
   ====================================================================== */
console.log('\n--- reading ---');
{
  const t = (s) => P.parseSide(s).map((x) => `${x.c}*${x.n}`).join(' ');
  check('a plain side', t('2.0000 UO2+2 + 2.0000 H2O') === '2*UO2+2 2*H2O', t('2.0000 UO2+2 + 2.0000 H2O'));
  check('a sign glued to a coefficient', t('(UO2)2(OH)2+2 +2.0000 H+') === '1*(UO2)2(OH)2+2 2*H+',
    t('(UO2)2(OH)2+2 +2.0000 H+'));
  check('signed terms', t('+1.000H2O                  -1.000H+') === '1*H2O -1*H+', t('+1.000H2O  -1.000H+'));
  check('a coefficient glued to its species', t('CO3-2 + 2H+') === '1*CO3-2 2*H+', t('CO3-2 + 2H+'));

  const { left, right } = P.normalise(P.parseSide('+1.000H2O -1.000H+'), P.parseSide('OH-'));
  check('a minus moves the species across', JSON.stringify([left, right])
    === JSON.stringify([[{ c: 1, n: 'H2O' }], [{ c: 1, n: 'OH-' }, { c: 1, n: 'H+' }]]),
  JSON.stringify([left, right]));

  check('atoms: H in H2', P.countAtoms('H2', 'H') === 2);
  check('atoms: C in UO2(CO3)3-4', P.countAtoms('UO2(CO3)3-4', 'C') === 3);
  check('atoms: an element of several letters', P.countAtoms('Hdg', 'Hdg') === 1);

  const taken = new Map();
  check('a leading group renamed', P.rtmName('(UO2)2(OH)2+2', taken) === 'UO2_2(OH)2+2');
  check('a dimer renamed', P.rtmName('(CO2)2', taken) === 'CO2_2');
  check('a plain name kept', P.rtmName('UO2(CO3)3-4', taken) === 'UO2(CO3)3-4');
  check('every renamed name is one rtm.html takes',
    ['(UO2)2(OH)2+2', '(CO2)2', 'Fe(OH)3-', 'CaCO3:H2O'].every((n) => RtmModel.speciesNameOk
      ? RtmModel.speciesNameOk(P.rtmName(n)) : /^[A-Za-z](?:[A-Za-z0-9_]|\([A-Za-z0-9_]+\))*(?:[+-][0-9]*)?$/
        .test(P.rtmName(n))));

  // A database written two ways at once: phreeqc.dat's and the NAGRA-PSI one's.
  const db = P.readDatabase(`
SOLUTION_MASTER_SPECIES
H        H+     -1.0  H     1.008
H(0)     H2      0.0  H
H(1)     H+     -1.0  0
E        e-      0.0  0     0
O        H2O     0.0  O     16.0
O(0)     O2      0.0  O
O(-2)    H2O     0.0  0
C        CO3-2   2.0  HCO3  12.0111
C(+4)    CO3-2   2.0  HCO3
C(-4)    CH4     0.0  CH4
Fe       Fe+2    0.0  Fe    55.847
Fe(+2)   Fe+2    0.0  Fe
Fe(+3)   Fe+3   -2.0  Fe
SOLUTION_SPECIES
H+ = H+
CO3-2 = CO3-2
Fe+2 = Fe+2
H2O = H2O
e- = e-
+1.000H2O                  -1.000H+                   = OH-
    log_k  -14.0
CO3-2 + H+ = HCO3-
    log_k 10.3
    -dw 1.18e-9
CO3-2 + 10 H+ + 8 e- = CH4 + 3 H2O
Fe+2 = Fe+3 + e-
Fe+3 + H2O = FeOH+2 + H+
2 H+ + 2 e- = H2
Fe+3 + OH- = FeOH+2 ; log_k 11.8    # defined again: this one counts, as in PHREEQC
2 H2O = O2 + 4 H+ + 4 e-
2CO3-2 + 4 H+ = (CO2)2 + 2 H2O
`);
  const ex = (s) => JSON.stringify([...db.expand(s)].sort());
  check('HCO3- is one C(4)', ex('HCO3-') === JSON.stringify([['C(+4)', 1]]), ex('HCO3-'));
  check('H2 is two H(0)', ex('H2') === JSON.stringify([['H(0)', 2]]), ex('H2'));
  check('(CO2)2 is two C(4)', ex('(CO2)2') === JSON.stringify([['C(+4)', 2]]), ex('(CO2)2'));
  check('FeOH+2 is Fe(3), not Fe(2)', ex('FeOH+2') === JSON.stringify([['Fe(+3)', 1]]), ex('FeOH+2'));
  check('CH4 is C(-4)', ex('CH4') === JSON.stringify([['C(-4)', 1]]), ex('CH4'));
  check('OH- counts for nothing', ex('OH-') === '[]', ex('OH-'));
  check('a species defined again takes the later reaction',
    db.reaction.get('FeOH+2').left.map((x) => x.n).join(' ') === 'Fe+3 OH-',
    JSON.stringify(db.reaction.get('FeOH+2')));
  check('... and still counts as Fe(3)', ex('FeOH+2') === JSON.stringify([['Fe(+3)', 1]]), ex('FeOH+2'));
  check('redox is known by its electrons', db.isRedox('Fe+3') && db.isRedox('CH4') && !db.isRedox('FeOH+2'));
  check('-dw is read', db.dw.get('HCO3-') === 1.18e-9);

  const eqs = P.modelEquilibria('<EQUILIBRIUM>\n <=> OH- + H+, logK = -14\nCO3-2 + 2 H+ <=> CO2, logK = 16.7 # x\n');
  check('a model\'s equilibria are read', eqs.length === 2 && eqs[1].reac[1].c === 2 && eqs[0].reac.length === 0,
    JSON.stringify(eqs));
}

/* ======================================================================
   2. With PHREEQC running
   ====================================================================== */
/** phreeqpython's PHREEQC, one process per run, for the cross-check. */
function bridgeEngine(py, dbText) {
  return {
    run(text) {
      const r = spawnSync(py, ['-I', path.join(__dirname, 'phreeqc-bridge.py')],
        { input: JSON.stringify({ db: dbText, input: text }), maxBuffer: 1 << 30 });
      if (r.status) throw new Error(r.stderr.toString());
      const o = JSON.parse(r.stdout.toString());
      if (o.error) throw new Error(o.error);
      return o.rows;
    },
  };
}

function pageRun(text, tend) {
  const solver = { method: 'ndf', tend, rtol: 1e-6, atol: 1e-20, matrix: 'auto', norm: 'max',
    maxSteps: 500000, maxPoints: 4000, nonNegative: true };
  let reply = null;
  handleRtmMessage({ type: 'run', id: 1, text, solver }, (msg) => {
    if (msg.type === 'result') reply = msg;
    else if (msg.type === 'error') throw new Error(`${msg.stage}: ${msg.error}`);
  });
  return reply;
}

const vendors = path.join(root, 'vendors', 'phreeqc');
const dbText = fs.readFileSync(path.join(vendors, 'phreeqc.dat'), 'latin1');
const database = { name: 'phreeqc.dat', text: dbText };
// An illustrative granitic groundwater: round numbers, nobody's sample.
const groundwater = `SOLUTION 1
  temp 15
  pH 7.4
  pe -3
  units mmol/kgw
  Na 50; K 0.5; Ca 15; Mg 5
  Cl 85 charge
  S(6) 2; C(4) 2.5; Fe(2) 0.02; Si 0.2
END
`;
const carbonate = 'SOLUTION 1\n temp 25\n units mol/kgw\n pH 7 charge\n C(4) 2.2e-3\n Na 0.102\n Cl 0.1\nEND\n';

function withPhreeqc(engine) {
  // --- a water into a model ---------------------------------------------
  const res = P.waterToModel({ engine, database, water: { name: 'groundwater', text: groundwater }, relax: 1e3 });
  const m = RtmModel.compile(res.text);
  const back = new Map([...res.names].map(([k, v]) => [v, k]));
  let worst = 0;
  m.speciesNames.forEach((n, i) => { worst = Math.max(worst, Math.abs(m.initialState()[i] / res.molal.get(back.get(n)) - 1)); });
  check('the groundwater as a model: rtm.html\'s own speciation lands on PHREEQC\'s', worst < 1e-8,
    `${res.report.species} species, ${res.report.equilibria} equilibria, ${worst.toExponential(1)}`);
  check('no redox relation is written', res.report.redox.includes('H2') && !/ e- /.test(res.text));
  check('every relation is held during the run', (res.text.match(/kf = /g) || []).length === res.report.equilibria);

  const carb = P.waterToModel({ engine, database, water: { name: 'carbonate', text: carbonate } });
  const line = carb.text.split('\n').find((l) => l.startsWith('CO3-2 + H+ <=> HCO3-'));
  const logk = Number(/# log K (\S+)/.exec(line)[1]);
  const logkC = Number(/logK = (\S+?),?\s/.exec(line)[1]);
  check('the database\'s log K, worked back from PHREEQC\'s activities', Math.abs(logk - 10.3289) < 2e-4,
    `HCO3- at 25 C: ${logk} (phreeqc.dat 10.329); conditional ${logkC.toFixed(4)} at I = 0.10`);

  // --- a run back out: acid --------------------------------------------
  const water = { name: 'groundwater', text: groundwater };
  const acidText = res.text.replace('TEND = 1\n', 'TEND = 1e5\n')
    + '=> H+ + Cl-, k = 1.5e-8\n';
  const acid = P.viewRun({ engine, database, run: pageRun(acidText, 1e5), modelText: acidText, water,
    phases: ['Calcite'], unit: 's' });
  const at0 = acid.rows[0].pq;
  const last = acid.rows[acid.rows.length - 1];
  const alone = P.parseRows(engine.run(`${P.punchBlock()}${groundwater.replace('END', '')}`
    + `REACTION 1\n  HCl 1\n  ${(1.5e-8 * last.t).toPrecision(12)} moles\nEND\n`)).pop();
  const water0 = P.parseRows(engine.run(`${P.punchBlock()}${groundwater}`)).pop();
  check('at the start the run is the water: pH', Math.abs(at0.pH - water0.pH) < 1e-6,
    `${at0.pH.toFixed(6)} vs ${water0.pH.toFixed(6)}`);
  check('... and calcite saturation', Math.abs(at0.phases.get('Calcite') - water0.phases.get('Calcite')) < 1e-5,
    `${at0.phases.get('Calcite').toFixed(5)} vs ${water0.phases.get('Calcite').toFixed(5)}`);
  check('with acid added, PHREEQC alone agrees at the end: pH', Math.abs(last.pq.pH - alone.pH) < 2e-3,
    `${last.pq.pH.toFixed(4)} vs ${alone.pH.toFixed(4)}`);
  check('... and calcite saturation', Math.abs(last.pq.phases.get('Calcite') - alone.phases.get('Calcite')) < 2e-3,
    `${last.pq.phases.get('Calcite').toFixed(4)} vs ${alone.phases.get('Calcite').toFixed(4)}`);
  check('the activity coefficients hardly moved', Math.abs(acid.report.drift[0].by) < 0.01,
    `${acid.report.drift[0].by.toExponential(2)} in log K`);

  // --- the same water, its relations held exactly ---------------------------
  const ex = P.waterToModel({ engine, database, water, exact: true });
  const mx = RtmModel.compile(ex.text);
  const backX = new Map([...ex.names].map(([k, v]) => [v, k]));
  const cx = mx.toConcentrations(mx.initialState());
  let worstX = 0;
  mx.speciesNames.forEach((n, i) => { worstX = Math.max(worstX, Math.abs(cx[i] / ex.molal.get(backX.get(n)) - 1)); });
  check('held exactly: EQUILIBRATE = always and no kf, the start on PHREEQC\'s molalities',
    /^EQUILIBRATE = always$/m.test(ex.text) && !/kf = /.test(ex.text) && !!mx.heldEquilibria
      && mx.heldEquilibria.relations === ex.report.equilibria && worstX < 1e-8,
    `${mx.heldEquilibria ? mx.heldEquilibria.species : 0} species on ${ex.report.equilibria} relations, `
      + `${worstX.toExponential(1)}`);
  let both = '';
  try { P.waterToModel({ engine, database, water, exact: true, relax: 1e3 }); } catch (e) { both = e.message; }
  check('... and exactly and as fast pairs at once is refused', /either exactly or as fast pairs/.test(both), both);
  const exAcidText = ex.text.replace('TEND = 1\n', 'TEND = 1e5\n') + '=> H+ + Cl-, k = 1.5e-8\n';
  const exAcid = P.viewRun({ engine, database, run: pageRun(exAcidText, 1e5), modelText: exAcidText, water,
    phases: ['Calcite'], unit: 's' });
  const exLast = exAcid.rows[exAcid.rows.length - 1];
  const exAlone = P.parseRows(engine.run(`${P.punchBlock()}${groundwater.replace('END', '')}`
    + `REACTION 1\n  HCl 1\n  ${(1.5e-8 * exLast.t).toPrecision(12)} moles\nEND\n`)).pop();
  check('held exactly, the acid run lands where PHREEQC alone does, as close as the pairs or closer',
    Math.abs(exLast.pq.pH - exAlone.pH) < 2e-3
      && Math.abs(exLast.pq.pH - exAlone.pH) <= Math.abs(last.pq.pH - alone.pH) + 1e-4,
    `pH ${exLast.pq.pH.toFixed(5)} vs ${exAlone.pH.toFixed(5)}; the pairs ${last.pq.pH.toFixed(5)} vs ${alone.pH.toFixed(5)}`);
  check('with the water, its temperature', acid.report.temperature === 15 && acid.report.temperatureFrom === 'the water',
    `${acid.report.temperature} C, from ${acid.report.temperatureFrom}`);

  // --- no water: the temperature from the top of the model text --------------
  const bare = P.viewRun({ engine, database, run: pageRun(acidText, 1e5), modelText: acidText, phases: ['Calcite'],
    unit: 's' });
  check('without a water, the temperature the model was written at, from its text',
    bare.report.temperature === 15 && bare.report.temperatureFrom === 'the model text',
    `${bare.report.temperature} C, from ${bare.report.temperatureFrom}`);
  check('... so the start is the water\'s pH all the same', Math.abs(bare.rows[0].pq.pH - water0.pH) < 1e-6,
    bare.rows[0].pq.pH.toFixed(6));

  // --- a water PHREEQC refuses: said, and the run looked at without it --------
  const refused = P.viewRun({ engine, database, run: pageRun(acidText, 1e5), modelText: acidText,
    water: { name: 'bad', text: 'SOLUTION 1\n  pH seven\nEND\n' }, phases: ['Calcite'], unit: 's' });
  check('a water PHREEQC refuses is reported, and the look goes on', /Concentration data error/.test(
    refused.report.waterError || '') && refused.report.failed.length === 0 && refused.rows.length === 100,
  refused.report.waterError);

  // --- salt: the conditional constants go wrong, and it is said ------------
  const saltText = acidText.replace('=> H+ + Cl-, k = 1.5e-8', '=> Na+ + Cl-, k = 4e-6');
  const salt = P.viewRun({ engine, database, run: pageRun(saltText, 1e5), modelText: saltText, water,
    phases: ['Calcite'], unit: 's' });
  check('with 0.4 mol/kgw of salt the drift is reported', Math.abs(salt.report.drift[0].by) > 0.2,
    `${salt.report.drift[0].by.toFixed(3)} in log K (${salt.report.drift[0].rel}); ionic strength `
    + `${salt.report.ionicStrength.map((x) => x.toFixed(3)).join(' to ')}`);

  // --- the built-in model --------------------------------------------------
  const builtin = P.viewRun({ engine, database, run: pageRun(RTM_DEFAULT_MODEL), modelText: RTM_DEFAULT_MODEL,
    times: 10, unit: 's' });
  const counted = builtin.report.counted.map((c) => c.name).sort().join(' ');
  check('the built-in model: what PHREEQC knows is counted', counted === 'CO2 CO3-2 H+ H2 HCO3- O2 OH-', counted);
  check('the hydrated electron is not PHREEQC\'s e-', builtin.report.skipped.some((s) => s.name === 'e-'));
  check('radicals are listed as left out', builtin.report.unmapped.some((u) => u.name === 'OHra'));
  check('the missing counter-ion is noticed', !!builtin.report.notNeutral);
  check('every water was calculated', builtin.report.failed.length === 0 && builtin.rows.length === 200,
    `${builtin.rows.length} waters`);
  return { res, acidText, acid };
}

/* ======================================================================
   3. The jobs as the page sends them, and the database as the page loads it
   ====================================================================== */
async function asThePage(createPhreeqc, acidText) {
  const handle = E.handler(createPhreeqc, { builtin: dbText });
  const ask = (msg) => new Promise((resolve) => {
    const progress = [];
    handle(msg, (m) => { if (m.type === 'progress') progress.push(m); else resolve({ ...m, progress }); });
  });
  const a = await ask({ id: 1, type: 'toModel', database: null,
    water: { name: 'groundwater', text: groundwater }, options: { relax: 1e3 } });
  check('the page\'s water job: a model, checked by rtm.html\'s compiler', a.type === 'done' && a.check
    && a.check.worst < 1e-8 && a.check.converged, a.type === 'done' ? `${a.report.species} species, `
    + `${a.check.worst.toExponential(1)} from PHREEQC, PHREEQC ${a.version}` : a.error);
  const run = pageRun(acidText, 1e5);
  const v = await ask({ id: 2, type: 'view', database: null, water: { name: 'groundwater', text: groundwater },
    run, modelText: acidText, options: { times: 50, unit: 's' } });
  check('the page\'s view job: a table, with progress on the way', v.type === 'done'
    && v.table.pH.length === 50 && v.progress.length > 0 && v.csv.split('\n').length === 52,
  v.type === 'done' ? `${v.table.pH.length} rows, ${v.phases.length} phases, ${v.progress.length} progress messages`
    : v.error);
  const held = await ask({ id: 5, type: 'toModel', database: null,
    water: { name: 'groundwater', text: groundwater }, options: { exact: true } });
  check('... and held exactly, checked from the concentrations its state stands for', held.type === 'done'
    && held.check && held.check.worst < 1e-8 && held.check.converged && /^EQUILIBRATE = always$/m.test(held.text),
  held.type === 'done' ? `${held.check.worst.toExponential(1)} from PHREEQC` : held.error);
  const bad = await ask({ id: 3, type: 'toModel', database: null, water: { name: 'x', text: 'SOLUTION 1\n pH seven\nEND\n' } });
  check('a bad water is answered with PHREEQC\'s own message', bad.type === 'error' && /pH|ph/.test(bad.error),
    bad.error && bad.error.split('\n')[0]);
  const after = await ask({ id: 4, type: 'toModel', database: null, water: { name: 'c', text: carbonate } });
  check('and the next job is not hurt by it', after.type === 'done', after.error);

  const sandbox = {};
  new Function('self', fs.readFileSync(path.join(vendors, 'phreeqc-dat.js'), 'utf8'))(sandbox);
  check('the database as a script is the file, character for character', sandbox.PHREEQC_DAT === dbText,
    `${sandbox.PHREEQC_DAT.length} characters`);
  check('... and is plain ASCII', !/[^\x00-\x7f]/.test(fs.readFileSync(path.join(vendors, 'phreeqc-dat.js'), 'latin1')));
}

/* ======================================================================
   4. The WebAssembly build against a native PHREEQC (when there is one)
   ====================================================================== */
function againstNative(wasm, py, first) {
  const bridge = bridgeEngine(py, dbText);
  const water = { name: 'groundwater', text: groundwater };
  const b = P.waterToModel({ engine: bridge, database, water, relax: 1e3, date: 'd' });
  const a = P.waterToModel({ engine: wasm, database, water, relax: 1e3, date: 'd' });
  const nums = (s) => s.match(/-?\d+\.?\d*(?:e[-+]?\d+)?/gi).map(Number);
  const na = nums(a.text);
  const nb = nums(b.text);
  let worst = na.length === nb.length ? 0 : Infinity;
  na.forEach((x, i) => { worst = Math.max(worst, Math.abs(x - nb[i]) / Math.max(Math.abs(nb[i]), 1e-300)); });
  check('a water as a model: the WebAssembly PHREEQC and phreeqpython\'s agree', worst < 1e-9,
    `${na.length} numbers, largest relative difference ${worst.toExponential(1)}`);
  const run = pageRun(first.acidText, 1e5);
  const va = P.viewRun({ engine: wasm, database, run, modelText: first.acidText, water, times: 30, unit: 's' });
  const vb = P.viewRun({ engine: bridge, database, run, modelText: first.acidText, water, times: 30, unit: 's' });
  const A = va.csv().trim().split('\n').map((l) => l.split(','));
  const B = vb.csv().trim().split('\n').map((l) => l.split(','));
  let w2 = A[0].join() === B[0].join() && A.length === B.length ? 0 : Infinity;
  for (let i = 1; i < Math.min(A.length, B.length); i++) {
    for (let j = 0; j < A[i].length; j++) if (Number.isFinite(+B[i][j])) w2 = Math.max(w2, Math.abs(+A[i][j] - +B[i][j]));
  }
  check('a run through PHREEQC: the two agree on every number written', w2 < 1e-6, `largest difference ${w2.toExponential(1)}`);
}

(async () => {
  const createPhreeqc = require(path.join(vendors, 'phreeqc.js'));
  const wasm = await E.create(createPhreeqc);
  wasm.load(dbText);
  console.log(`\n--- with PHREEQC: ${wasm.version}, compiled to WebAssembly ---`);
  const first = withPhreeqc(wasm);
  console.log('\n--- as the page asks ---');
  await asThePage(createPhreeqc, first.acidText);
  const py = process.env.RTM_PHREEQC_PYTHON;
  if (py) {
    console.log(`\n--- against phreeqpython (${py}) ---`);
    againstNative(wasm, py, first);
  } else {
    console.log('\n--- against a native PHREEQC: skipped (RTM_PHREEQC_PYTHON not set) ---');
  }
  wasm.close();
  console.log(`\n${checks - failures.length} of ${checks} checks passed`);
  if (failures.length) {
    console.log(`FAILED: ${failures.join('; ')}`);
    process.exit(1);
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
