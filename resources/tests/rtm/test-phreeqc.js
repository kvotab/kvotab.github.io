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
  const own = P.waterToModel({ engine, database, water, exact: true, dw: true });
  const one = P.waterToModel({ engine, database, water, exact: true, D: 2e-9 });
  check('each species its own D from the database: the ions coupled, DIFFUSION = nernst-planck; one D for all: not',
    /^DIFFUSION = nernst-planck$/m.test(own.text) && /^Na\+ .*D=1\.33e-9$/m.test(own.text)
      && !/nernst-planck/.test(one.text) && RtmModel.compile(own.text).settings.DIFFUSION === 2);
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

  // --- phases carried as minerals, held at saturation ----------------------------
  check('a phase\'s reaction is read: Calcite is CaCO3 = CO3-2 + Ca+2; the input\'s EQUILIBRIUM_PHASES with their SI',
    JSON.stringify(P.readDatabase(dbText).phaseReaction.get('Calcite')) === JSON.stringify({ left: [{ c: 1, n: 'CaCO3' }],
      right: [{ c: 1, n: 'CO3-2' }, { c: 1, n: 'Ca+2' }] })
      && JSON.stringify(P.readAssemblage('EQUILIBRIUM_PHASES 1\n Calcite 0 0.002\n CO2(g) -2.0 10\nEND\n'))
        === JSON.stringify([{ name: 'Calcite', si: 0, extra: '' }, { name: 'CO2(g)', si: -2, extra: '' }]));
  const phasesIn = 'EQUILIBRIUM_PHASES 1\n Calcite 0 0.002\n CO2(g) -2.0 10\n Pyrite 0 0\n';
  const phaseWater = { name: 'groundwater', text: groundwater.replace('END', phasesIn) };
  let notHeld = '';
  try { P.waterToModel({ engine, database, water: phaseWater, phases: true }); } catch (e) { notHeld = e.message; }
  check('... phases are kept at saturation only with the relations held exactly', /needs the relations held exactly/.test(notHeld),
    notHeld);
  const ph = P.waterToModel({ engine, database, water: phaseWater, activity: true, exact: true, phases: true });
  const mph = RtmModel.compile(ph.text);
  const backP = new Map([...ph.names].map(([k, v]) => [v, k]));
  const cph = mph.toConcentrations(mph.initialState());
  let worstP = 0;
  let whereP = '';
  mph.speciesNames.forEach((n, i) => {
    const ref = backP.has(n) ? ph.molal.get(backP.get(n)) : ph.amounts.get(n);
    const d = Math.abs(cph[i] - ref) / Math.max(Math.abs(ref), 1e-15);
    if (d > worstP) { worstP = d; whereP = n; }
  });
  check('calcite and a CO2 pressure as minerals, pyrite not (it dissolves with electrons): the start, the amounts '
    + 'too, on what PHREEQC left', worstP < 1e-8 && ph.report.minerals.length === 2
    && ph.report.phasesSkipped.length === 1 && ph.report.phasesSkipped[0].name === 'Pyrite'
    && /^Calcite +[0-9.e-]+ +mineral$/m.test(ph.text) && /^CO2\(g\) <=> CO2,/m.test(ph.text),
  `${worstP.toExponential(1)} (${whereP}); ${ph.report.minerals.map((mn) => `${mn.as} ${mn.amount.toExponential(3)}`).join(', ')}`);
  // Acid in: the calcite dissolves and the gas holds the CO2, as PHREEQC with the same phases has them.
  const coupled = (res) => {
    // Every species of an element the model keeps in more than one valence
    // state: PHREEQC alone moves electrons between them, the model never does.
    const db = P.readDatabase(dbText);
    const labelsOf = new Map([...res.names.keys()].map((sp) => [sp, (() => {
      try { return [...db.expand(sp).keys()]; } catch (e) { return []; }
    })()]));
    const states = new Map();
    for (const labels of labelsOf.values()) {
      for (const lb of labels) {
        const el = P.elementOf(lb);
        if (!states.has(el)) states.set(el, new Set());
        states.get(el).add(lb);
      }
    }
    const many = new Set([...states].filter(([, set]) => set.size > 1).map(([el]) => el));
    // ...and the redox species the report names, H2 among them: H(1) is in no
    // species' count, so H looks to have one valence state when it has two.
    return new Set([...labelsOf].filter(([sp, labels]) => res.report.redox.includes(sp)
      || labels.some((lb) => many.has(P.elementOf(lb)))).map(([sp]) => sp));
  };
  const acidPh = `${ph.text.replace('TEND = 1\n', 'TEND = 1e5\n')}=> H+ + Cl-, k = 1e-8\n`;
  const runPh = pageRun(acidPh, 1e5);
  const kEnd = runPh.n - 1;
  const tPh = runPh.t[kEnd];
  const alonePh = P.parseRows(engine.run(`${P.punchBlock(['EQUI("Calcite")', 'TOT("water")'])}`
    + `${groundwater.replace('END', 'EQUILIBRIUM_PHASES 1\n Calcite 0 0.002\n CO2(g) -2.0 10\n')}`
    + `REACTION 1\n  HCl 1\n  ${(1e-8 * tPh).toPrecision(12)} moles\nEND\n`)).pop();
  const skipPh = coupled(ph);
  let worstA = 0;
  let whereA = '';
  runPh.model.species.forEach((n, i) => {
    const v = runPh.states[kEnd * runPh.width + i];
    const ref = n === 'Calcite' ? alonePh.x[0] / alonePh.x[1] : backP.has(n) && !skipPh.has(backP.get(n))
      ? alonePh.species.get(backP.get(n))[0] : null;
    if (ref === null || ref === undefined) return;
    const d = Math.abs(v / ref - 1);
    if (d > worstA) { worstA = d; whereA = n; }
  });
  // PHREEQC settles a phase only to its own tolerance: it leaves CO2(g) about
  // 3e-5 off its SI, which the model then holds, and the rest follows from that.
  check('... and with acid in, ends where PHREEQC with the same phases ends: the calcite left, every species',
    worstA < 1e-4, `${worstA.toExponential(1)} (${whereA}); calcite ${(alonePh.x[0] / alonePh.x[1]).toExponential(4)} left`);
  const viewPh = P.viewRun({ engine, database, run: runPh, modelText: acidPh, water: phaseWater, unit: 's' });
  const calc = (viewPh.report.minerals || []).find((mn) => mn.name === 'Calcite');
  const gas = (viewPh.report.minerals || []).find((mn) => mn.name === 'CO2(g)');
  check('... and the PHREEQC tab finds the water at saturation with calcite, and at the CO2 pressure, wherever there is any',
    !!calc && !!calc.present && Math.abs(calc.present[0]) < 1e-6 && Math.abs(calc.present[1]) < 1e-6
      && !!gas && !!gas.present && Math.abs(gas.present[0] + 2) < 1e-4 && gas.present[1] - gas.present[0] < 1e-8
      && viewPh.phases.includes('Calcite'),
    calc ? `Calcite SI ${calc.present && calc.present.map((v) => v.toExponential(1)).join(' to ')}, CO2(g) `
      + `${gas && gas.present && gas.present.map((v) => v.toFixed(6)).join(' to ')}` : 'no minerals reported');

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

  // --- activity coefficients that follow the ionic strength -----------------
  const dbRead = P.readDatabase(dbText);
  check('the database\'s -gamma is read: Ca+2 a = 5, b = 0.165; Na+ 4.08 and 0.082',
    dbRead.gamma.get('Ca+2').a === 5 && dbRead.gamma.get('Ca+2').b === 0.165 && dbRead.gamma.get('Na+').a === 4.08
      && dbRead.gamma.get('Na+').b === 0.082 && dbRead.model === null);
  let pitzer = '';
  try {
    P.waterToModel({ engine, database: { name: 'pz', text: `${dbText}\nPITZER\n-B0\n Na+ Cl- 0.0765\n` }, water,
      activity: true });
  } catch (e) { pitzer = e.message; }
  check('... and a database with the Pitzer model is not followed, and says so', /Pitzer activity model/.test(pitzer),
    pitzer.slice(0, 90));
  const fol = P.waterToModel({ engine, database, water, activity: true, exact: true });
  const mf = RtmModel.compile(fol.text);
  const backF = new Map([...fol.names].map(([k, v]) => [v, k]));
  const cf = mf.toConcentrations(mf.initialState());
  let worstF = 0;
  mf.speciesNames.forEach((n, i) => { worstF = Math.max(worstF, Math.abs(cf[i] / fol.molal.get(backF.get(n)) - 1)); });
  check('following the ionic strength: ACTIVITY at the water\'s temperature, the water in the relations, '
    + 'the database\'s log K; the start on PHREEQC\'s molalities from the page\'s own activity coefficients',
  /^ACTIVITY = debye-huckel$/m.test(fol.text) && /^TEMPERATURE = 15$/m.test(fol.text)
    && /^H2O <=> OH- \+ H\+, +logK = -14\.34328/m.test(fol.text) && /^Ca\+2 .* a=5 {2}b=0\.165$/m.test(fol.text)
    && worstF < 1e-8 && mf.activity.kind === 'debye-huckel',
  `${worstF.toExponential(1)} from PHREEQC; A ${mf.activity.A.toFixed(6)} at ${mf.activity.temperature} C`);
  // Salt again, each kind of model against PHREEQC adding the same salt by itself.
  const saltRun = (res) => {
    const text = `${res.text.replace('TEND = 1\n', 'TEND = 1e5\n')}=> Na+ + Cl-, k = 4e-6\n`;
    return { text, run: pageRun(text, 1e5) };
  };
  const againstAlone = (res, sr) => {
    const k = sr.run.n - 1;
    const tEnd = sr.run.t[k];
    const alone = P.parseRows(engine.run(`${P.punchBlock()}${groundwater.replace('END', '')}`
      + `REACTION 1\n  NaCl 1\n  ${(4e-6 * tEnd).toPrecision(12)} moles\nEND\n`)).pop();
    const back = new Map([...res.names].map(([a, b]) => [b, a]));
    let worstA = 0;
    let where = '';
    sr.run.model.species.forEach((n, i) => {
      const p = back.get(n);
      if (res.report.redox.includes(p)) return;   // PHREEQC alone moves the valence states; the model never does
      const d = Math.abs(sr.run.states[k * sr.run.width + i] / alone.species.get(p)[0] - 1);
      if (d > worstA) { worstA = d; where = n; }
    });
    return { worst: worstA, where };
  };
  const fixedRes = P.waterToModel({ engine, database, water, exact: true });
  const fixedSalt = againstAlone(fixedRes, saltRun(fixedRes));
  const folSaltRun = saltRun(fol);
  const folSalt = againstAlone(fol, folSaltRun);
  check('0.4 mol/kgw of salt: following, every species ends on what PHREEQC alone finds; fixed, far from it',
    folSalt.worst < 1e-5 && fixedSalt.worst > 0.1,
    `following ${folSalt.worst.toExponential(1)} (${folSalt.where}), fixed ${fixedSalt.worst.toFixed(2)} (${fixedSalt.where})`);
  const folView = P.viewRun({ engine, database, run: folSaltRun.run, modelText: folSaltRun.text, water,
    phases: ['Calcite'], unit: 's' });
  const gap = folView.report.activity && folView.report.activity.gap[0];
  check('... and the PHREEQC tab: its activity coefficients moved, and the model\'s own stayed on them',
    !!gap && Math.abs(gap.by) < 1e-6 && Math.abs(folView.report.drift[0].by) > 0.2 && folView.report.unchecked.length === 0,
    gap ? `PHREEQC's moved ${folView.report.drift[0].by.toFixed(3)}, the model's ${gap.by.toExponential(1)} from them `
      + `(${gap.rel})` : 'no comparison');

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
  const followed = await ask({ id: 6, type: 'toModel', database: null,
    water: { name: 'groundwater', text: groundwater }, options: { activity: true, exact: true } });
  check('... and following the ionic strength, checked by the page\'s own activity coefficients',
    followed.type === 'done' && followed.check && followed.check.worst < 1e-8 && followed.check.converged
      && /^ACTIVITY = debye-huckel$/m.test(followed.text),
    followed.type === 'done' ? `${followed.check.worst.toExponential(1)} from PHREEQC` : followed.error);
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

/* ======================================================================
   4. A reactive column against PHREEQC's own TRANSPORT

   Acid enters a column of groundwater at saturation with calcite and
   dissolves it, a front moving down the column. PHREEQC runs its TRANSPORT
   (shifts, mixing for the dispersivity, every cell equilibrated with its
   calcite each shift); the page runs the model it writes from the same water
   -- activities following the ionic strength, the relations held, calcite a
   mineral kept at saturation -- as a column, with limited advection, the
   inflow the speciated acid water. PHREEQC's cell at a shift is read as the
   water at its downstream face half a shift later, which is what its scheme
   makes it. The two are different numerical schemes and meet only as the
   cells are refined, so the checks are the effluent over the whole run, the
   calcite left and where the front has reached.
   ====================================================================== */
function againstTransport(engine) {
  const N = 40;
  const L = 0.1;
  const dx = L / N;
  const dt = 1000;
  const S = 2 * N;
  const alpha = L / 40;
  const v = dx / dt;
  const water = (n) => `SOLUTION ${n}\n temp 25\n units mmol/kgw\n pH 7.5\n Na 2\n Ca 1\n Cl 2 charge\n C(4) 3\n`;
  const acid = 'SOLUTION 0\n temp 25\n units mmol/kgw\n pH 3 charge\n Na 2\n Ca 1\n Cl 7\n C(4) 3\nEND\n';
  // A clean PHREEQC: what earlier inputs defined is still there otherwise, and
  // TRANSPORT applies every reactant numbered as a cell -- a REACTION 1 left
  // from a test above put acid into cell 1 at every shift.
  engine.load(dbText);
  const started = Date.now();
  const rows = engine.run(`${water(`1-${N}`)}END\nEQUILIBRIUM_PHASES 1-${N}\n Calcite 0 0.01\nEND\n`
    + `RUN_CELLS\n -cells 1-${N}\nEND\n${acid}`
    + 'SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings cell time pH Ca cal\n -start\n'
    + '10 PUNCH CELL_NO, TOTAL_TIME, -LA("H+"), TOT("Ca"), EQUI("Calcite")\n -end\n'
    + `TRANSPORT\n -cells ${N}\n -shifts ${S}\n -time_step ${dt}\n -lengths ${dx}\n -dispersivities ${alpha}\n`
    + ` -diffusion_coefficient 0\n -flow_direction forward\n -boundary_conditions flux flux\n -punch_cells 1-${N}\n`
    + ` -punch_frequency 1\n -print_frequency ${10 * S}\nEND\n`);
  const pqMs = Date.now() - started;
  const head = rows[0].map((h) => String(h).trim());
  const pq = new Map();
  for (const r of rows.slice(1)) {
    const t = Number(r[head.indexOf('time')]);
    if (!(t > 0)) continue;
    pq.set(`${Number(r[head.indexOf('cell')])}/${Math.round(t / dt)}`, {
      pH: Number(r[head.indexOf('pH')]), Ca: Number(r[head.indexOf('Ca')]), cal: Number(r[head.indexOf('cal')]) });
  }
  // The page: the water as the hand-off writes it, made a column.
  const res = P.waterToModel({ engine, database, water: { name: 'column', text: `${water(1)}EQUILIBRIUM_PHASES 1\n Calcite 0 0.01\nEND\n` },
    activity: true, exact: true, phases: true });
  const inflow = P.parseRows(engine.run(`${P.punchBlock()}${acid}`)).pop();
  const back = new Map([...res.names].map(([k, n]) => [n, k]));
  const text = res.text
    .replace('MODE = batch', `MODE = transport\nCELLS = ${N}\nLENGTH = ${L}\nDIFFUSION = 1\nADVECTION = 1\n`
      + `ADVECTION_SCHEME = limited\nVELOCITY = ${v}\nPECLET = ${L / alpha}\nLEFT = robin\nRIGHT = free`)
    .replace('TEND = 1\n', `TEND = ${(S + 0.5) * dt}\n`)
    .replace(/^(\S+)(\s+)([0-9][0-9.eE+-]*)(.*)$/gm, (line, name, gap, value, rest) => {
      if (/mineral/.test(rest) || !back.has(name)) return line;
      const sp = inflow.species.get(back.get(name));
      return `${line}  left=${sp ? sp[0] : 0}`;
    });
  const m = RtmModel.compile(text);
  const times = Array.from({ length: S }, (_, k) => (k + 1.5) * dt);
  const t0 = Date.now();
  const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: (S + 0.5) * dt, rtol: 1e-7, atol: 1e-20, nonNegative: true,
    outputTimes: times });
  const rtmMs = Date.now() - t0;
  const ns = m.speciesNames.length;
  const db = P.readDatabase(dbText);
  const caOf = [];
  m.speciesNames.forEach((n, i) => {
    if (!back.has(n)) return;
    const ex = db.expand(back.get(n));
    if (ex.has('Ca')) caOf.push([i, ex.get('Ca')]);
  });
  const iH = m.speciesNames.indexOf('H+');
  const iCal = m.speciesNames.indexOf('Calcite');
  const lnG = new Float64Array(ns);
  const dG = new Float64Array(ns);
  const at = (c, cell) => {
    let Ca = 0;
    for (const [i, k] of caOf) Ca += k * c[cell * ns + i];
    RtmModel.activityAt(m.act, c, cell * ns, lnG, dG);
    return { Ca, pH: -(Math.log(c[cell * ns + iH]) + lnG[iH]) / Math.LN10 };
  };
  // The effluent: PHREEQC's last cell at shift s, the outlet half a shift later.
  let effpH = 0;
  let effCa = 0;
  for (let k = 1; k <= S; k++) {
    const o = at(m.toConcentrations(r.grid.y[k - 1]), N - 1);
    const d = pq.get(`${N}/${k}`);
    effpH = Math.max(effpH, Math.abs(o.pH - d.pH));
    effCa = Math.max(effCa, Math.abs(o.Ca - d.Ca));
  }
  check('a reactive column, acid dissolving calcite, against PHREEQC\'s TRANSPORT: the effluent all the way through',
    effpH < 0.02 && effCa < 5e-5, `pH within ${effpH.toFixed(4)}, Ca within ${(effCa * 1e3).toFixed(4)} mM `
      + `(of 1 to 5); ${N} cells, ${S} shifts: PHREEQC ${pqMs} ms, the page ${rtmMs} ms`);
  // The calcite left: PHREEQC after S shifts, the page at S dt, as much acid in.
  const before = m.toConcentrations(r.grid.y[S - 2]);
  const after = m.toConcentrations(r.grid.y[S - 1]);
  let left = 0;
  let pqLeft = 0;
  let gone = 0;
  let pqGone = 0;
  for (let cell = 0; cell < N; cell++) {
    left += (before[cell * ns + iCal] + after[cell * ns + iCal]) / 2;
    if (!(after[cell * ns + iCal] > 0)) gone++;
    const d = pq.get(`${cell + 1}/${S}`);
    pqLeft += d.cal;
    if (!(d.cal > 0)) pqGone++;
  }
  check('... the calcite left in the column within 1 %, and the front within a cell of PHREEQC\'s',
    Math.abs(left / pqLeft - 1) < 0.01 && Math.abs(gone - pqGone) <= 1 && r.events.length === gone,
    `${((left / pqLeft - 1) * 100).toFixed(2)} %; calcite gone from ${gone} cells here, ${pqGone} in PHREEQC, `
      + `${r.events.length} events`);
}

/* ======================================================================
   5. A mineral dissolving at a rate, against PHREEQC's KINETICS

   Calcite dissolving into an undersaturated water at k (1 - SR), in PHREEQC
   as KINETICS with a RATES block, here as the hand-off's model of the water
   with calcite a mineral, its saturation from <PHASES> (log K PHREEQC gives
   for this temperature) and the rate law reading SR(Calcite). Not where it
   ends -- test-model.js has that -- but the way there.
   ====================================================================== */
function againstKinetics(engine) {
  engine.load(dbText);
  const water = 'SOLUTION 1\n temp 25\n units mmol/kgw\n pH 6.5\n Na 4\n Ca 0.2\n Cl 0.4 charge\n C(4) 4\n';
  const k = 1e-7;
  const steps = [100, 200, 700, 2000, 7000];
  const times = [];
  steps.forEach((dt) => times.push((times.length ? times[times.length - 1] : 0) + dt));
  const rows = engine.run(`${water}KINETICS 1\nCalcite\n -formula CaCO3 1\n -m 0.01\n -m0 0.01\n -parms ${k}\n`
    + ` -tol 1e-10\n -steps ${steps.join(' ')}\nINCREMENTAL_REACTIONS true\nRATES\nCalcite\n-start\n`
    + '10 rate = PARM(1) * (1 - SR("Calcite"))\n20 SAVE rate * TIME\n-end\nSELECTED_OUTPUT 99\n -reset false\n'
    + 'USER_PUNCH 99\n -headings t Ca pH\n -start\n10 PUNCH TOTAL_TIME, TOT("Ca"), -LA("H+")\n -end\nEND\n');
  const head = rows[0].map((h) => String(h).trim());
  const pq = new Map(rows.slice(1).map((r) => [Math.round(Number(r[head.indexOf('t')])),
    { Ca: Number(r[head.indexOf('Ca')]), pH: Number(r[head.indexOf('pH')]) }]));
  engine.load(dbText);
  const res = P.waterToModel({ engine, database, water: { name: 'w', text: `${water}END\n` }, activity: true, exact: true });
  const lk = P.parseRows(engine.run(`${P.punchBlock(['LK_PHASE("Calcite")'])}${water}END\n`)).pop().x[0];
  const text = `${res.text.replace('TEND = 1\n', `TEND = ${times[times.length - 1]}\n`)
    .replace('\n<EQUILIBRIUM>', 'Calcite     0.01   mineral\n\n<EQUILIBRIUM>')
    .replace('\n<REACTIONS>', `\n<PHASES>\nCalcite <=> CO3-2 + Ca+2, logK = ${lk}\n\n<REACTIONS>`)
  }Calcite => CO3-2 + Ca+2, r = k*(1 - SR(Calcite)), k = ${k}\n`;
  const m = RtmModel.compile(text);
  const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: times[times.length - 1], rtol: 1e-9, atol: 1e-22,
    nonNegative: true, outputTimes: times });
  const back = new Map([...res.names].map(([a, b]) => [b, a]));
  const db = P.readDatabase(dbText);
  const caOf = [];
  m.speciesNames.forEach((n, i) => {
    if (!back.has(n)) return;
    const ex = db.expand(back.get(n));
    if (ex.has('Ca')) caOf.push([i, ex.get('Ca')]);
  });
  const ns = m.speciesNames.length;
  const iH = m.speciesNames.indexOf('H+');
  const lnG = new Float64Array(ns);
  let worstCa = 0;
  let worstPH = 0;
  times.forEach((t, k2) => {
    const c = m.toConcentrations(r.grid.y[k2]);
    let Ca = 0;
    for (const [i, kk] of caOf) Ca += kk * c[i];
    RtmModel.activityAt(m.act, c, 0, lnG, new Float64Array(ns));
    const d = pq.get(t);
    worstCa = Math.max(worstCa, Math.abs(Ca / d.Ca - 1));
    worstPH = Math.max(worstPH, Math.abs(-(Math.log(c[iH]) + lnG[iH]) / Math.LN10 - d.pH));
  });
  check('calcite dissolving at k (1 - SR) against PHREEQC\'s KINETICS and RATES: the way to saturation',
    worstCa < 1e-4 && worstPH < 1e-5, `calcium within ${worstCa.toExponential(1)}, pH within ${worstPH.toExponential(1)} `
      + `over ${times.join(', ')} s (calcium ${(pq.get(times[0]).Ca * 1e3).toFixed(3)} to `
      + `${(pq.get(times[times.length - 1]).Ca * 1e3).toFixed(3)} mM)`);
}

/* ======================================================================
   6. An exchanger: the hand-off, PHREEQC's TRANSPORT, and the PHREEQC tab

   PHREEQC's Example 11: a column whose exchanger (X, 1.1 mmol/kgw) was
   loaded from a Na-K-NO3 water, flushed with CaCl2. The hand-off writes the
   exchanger and the species PHREEQC put on it; the page runs it as a column
   with limited advection, the inflow the speciated CaCl2 water, and its
   effluent is read against PHREEQC's last cell half a shift later, as in 4.
   Ca and Cl are in the column's water at a part in a million, so that the
   hand-off has their species to write.
   ====================================================================== */
function againstExchange(engine) {
  const exWater = (n) => `SOLUTION ${n}\n units mmol/kgw\n temp 25\n pH 7 charge\n Na 1.0\n K 0.2\n N(5) 1.2\n`
    + ' Ca 1e-6\n Cl 2e-6\n';
  const loaded = `${exWater(1)}EXCHANGE 1\n -equilibrate 1\n X 0.0011\nEND\n`;
  // The hand-off, both ways: the page's start is PHREEQC's exchanger.
  for (const activity of [true, false]) {
    engine.load(dbText);
    const res = P.waterToModel({ engine, database, water: { name: 'column', text: loaded }, activity, exact: true });
    const m = RtmModel.compile(res.text);
    const y = m.toConcentrations(m.initialState());
    let worst = 0;
    for (const [n, v] of res.amounts) worst = Math.max(worst, Math.abs(y[m.speciesNames.indexOf(n)] / v - 1));
    const lines = /^X-\s+exchanger$/m.test(res.text) && /^NaX\s+\S+\s+exchange(\s+a=4\.08\s+b=0\.082)?$/m.test(res.text)
      && /^K\+ \+ X- <=> KX,\s+logK = 0\.7000000000/m.test(res.text);
    check(`an exchanger in the water, ${activity ? 'with its activity coefficients' : 'conditional'}: written as an `
      + 'exchanger and the species on it, and the page starts from what PHREEQC put on it',
    lines && worst < 1e-12 && res.report.exchange && res.report.exchange.species.length === 3
      && (activity ? /exchange\s+a=4\.08\s+b=0\.082/.test(res.text) : !/exchange\s+a=/.test(res.text)),
    `${res.report.exchange ? res.report.exchange.species.map((e) => `${e.as} ${e.amount.toExponential(4)}`).join(', ') : 'none'}; `
      + `within ${worst.toExponential(1)}`);
  }
  engine.load(dbText);
  const apart = P.waterToModel({ engine, database, water: { name: 'column', text: loaded }, activity: true, exact: false });
  check('  not held exactly, the exchanger is said and not carried',
    !/exchanger/.test(apart.text.split('<SETTINGS>')[1]) && apart.report.exchangeSkipped.length === 1);

  // The column against PHREEQC's TRANSPORT.
  const N = 40;
  const L = 0.08;
  const dx = L / N;
  const dt = 720;
  const S = 3 * N;
  const alpha = 0.002;
  const v = dx / dt;
  const inflow = 'SOLUTION 0\n units mmol/kgw\n temp 25\n pH 7 charge\n Ca 0.6\n Cl 1.2\n Na 1e-6\n K 1e-6\n N(5) 1e-6\nEND\n';
  engine.load(dbText);
  const started = Date.now();
  const rows = engine.run(`${exWater(`1-${N}`)}END\nEXCHANGE 1-${N}\n -equilibrate 1\n X 0.0011\nEND\n${inflow}`
    + 'SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings cell time Na K Ca Cl\n -start\n'
    + '10 PUNCH CELL_NO, TOTAL_TIME, TOT("Na"), TOT("K"), TOT("Ca"), TOT("Cl")\n -end\n'
    + `TRANSPORT\n -cells ${N}\n -shifts ${S}\n -time_step ${dt}\n -lengths ${dx}\n -dispersivities ${alpha}\n`
    + ` -diffusion_coefficient 0\n -flow_direction forward\n -boundary_conditions flux flux\n -punch_cells ${N}\n`
    + ` -punch_frequency 1\n -print_frequency ${10 * S}\nEND\n`);
  const pqMs = Date.now() - started;
  const head = rows[0].map((h) => String(h).trim());
  const els = ['Na', 'K', 'Ca', 'Cl'];
  const pq = new Map();
  for (const r of rows.slice(1)) {
    const t = Number(r[head.indexOf('time')]);
    if (t > 0) pq.set(Math.round(t / dt), Object.fromEntries(els.map((k) => [k, Number(r[head.indexOf(k)])])));
  }
  engine.load(dbText);
  const res = P.waterToModel({ engine, database, water: { name: 'column', text: loaded }, activity: true, exact: true });
  const inRow = P.parseRows(engine.run(`${P.punchBlock()}${inflow}`)).pop();
  const back = new Map([...res.names].map(([k, n]) => [n, k]));
  const text = res.text
    .replace('MODE = batch', `MODE = transport\nCELLS = ${N}\nLENGTH = ${L}\nDIFFUSION = 1\nADVECTION = 1\n`
      + `ADVECTION_SCHEME = limited\nVELOCITY = ${v}\nPECLET = ${L / alpha}\nLEFT = robin\nRIGHT = free`)
    .replace('TEND = 1\n', `TEND = ${(S + 0.5) * dt}\n`)
    .replace(/^(\S+)(\s+)([0-9][0-9.eE+-]*)(.*)$/gm, (line, name, gap, value, rest) => {
      if (/mineral|exchange/.test(rest) || !back.has(name)) return line;
      const sp = inRow.species.get(back.get(name));
      return `${line}  left=${sp ? sp[0] : 0}`;
    });
  const m = RtmModel.compile(text);
  const t0 = Date.now();
  const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: (S + 0.5) * dt, rtol: 1e-7, atol: 1e-20, nonNegative: true,
    outputTimes: Array.from({ length: S }, (_, k) => (k + 1.5) * dt) });
  const rtmMs = Date.now() - t0;
  const ns = m.speciesNames.length;
  const db = P.readDatabase(dbText);
  const of = Object.fromEntries(els.map((k) => [k, []]));
  m.speciesNames.forEach((n, i) => {
    if (!back.has(n)) return;
    const ex = db.expand(back.get(n));
    for (const el of els) if (ex.has(el)) of[el].push([i, ex.get(el)]);
  });
  const worst = Object.fromEntries(els.map((k) => [k, 0]));
  let peakK = 0;
  for (let k = 1; k <= S; k++) {
    const c = m.toConcentrations(r.grid.y[k - 1]);
    for (const el of els) {
      let tot = 0;
      for (const [i, kk] of of[el]) tot += kk * c[(N - 1) * ns + i];
      worst[el] = Math.max(worst[el], Math.abs(tot - pq.get(k)[el]));
      if (el === 'K') peakK = Math.max(peakK, tot);
    }
  }
  check('Example 11, CaCl2 through a column whose exchanger holds Na and K, against PHREEQC\'s TRANSPORT: the effluent',
    worst.Na < 3e-5 && worst.K < 5e-5 && worst.Ca < 3e-5 && worst.Cl < 1e-5,
    `within ${els.map((el) => `${el} ${(worst[el] * 1e3).toFixed(4)}`).join(', ')} mM (K peaking at `
      + `${(peakK * 1e3).toFixed(3)} mM); ${N} cells, ${S} shifts: PHREEQC ${pqMs} ms, the page ${rtmMs} ms`);

  // The PHREEQC tab: the run's exchanger against PHREEQC's loaded from each water.
  const reply = pageRun(text.replace(/^CELLS = \d+$/m, 'CELLS = 10').replace(`LENGTH = ${L}`, `LENGTH = ${L / 4}`)
    .replace(/^TEND = .*$/m, `TEND = ${30 * dt}`), 30 * dt);
  engine.load(dbText);
  const view = P.viewRun({ engine, database, run: reply, modelText: text, water: { name: 'column', text: loaded },
    unit: 's', times: 15 });
  const x = view.report.exchange;
  check('  the PHREEQC tab loads PHREEQC\'s exchanger from each water of a run: the fractions the run holds',
    x && !x.error && Math.abs(x.gap) < 1e-6 && view.report.unmapped.length === 0
    && view.report.skipped.some((sk) => sk.name === 'X-'),
    x ? `within ${Math.abs(x.gap).toExponential(1)} (${x.worst}) over ${view.report.waters} waters` : 'no exchanger');
}

(async () => {
  const createPhreeqc = require(path.join(vendors, 'phreeqc.js'));
  const wasm = await E.create(createPhreeqc);
  wasm.load(dbText);
  console.log(`\n--- with PHREEQC: ${wasm.version}, compiled to WebAssembly ---`);
  const first = withPhreeqc(wasm);
  console.log('\n--- as the page asks ---');
  await asThePage(createPhreeqc, first.acidText);
  console.log('\n--- a reactive column against PHREEQC\'s TRANSPORT ---');
  againstTransport(wasm);
  console.log('\n--- a mineral dissolving at a rate against PHREEQC\'s KINETICS ---');
  againstKinetics(wasm);
  console.log('\n--- an exchanger: the hand-off, PHREEQC\'s TRANSPORT and the PHREEQC tab ---');
  againstExchange(wasm);
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
