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

/*
  A species line of a model text, as the checks edit them -- a name, the gap, its first number and the rest -- in
  <SPECIES> alone: <VOLUMES>, which the hand-off writes wherever it writes <CONDUCTANCE>, has lines of the same shape.
*/
const SPECIES_LINE = /(?<=^<SPECIES>[^\S\n]*\n(?:(?!<)[^\n]*\n)*)^(\S+)(\s+)([0-9][0-9.eE+-]*)(.*)$/gm;

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

  // SIT's coefficients, as PHREEQC reads them: by kind and pair, either way round, a later one replacing.
  const sdb = P.readDatabase(`SIT
-epsilon
  Na+   Cl-    0.03
  Cl-   Na+    0.04            # the same pair again: this one counts
  Ca+2  Cl-    0.14  -50  0  0.001
  CO2   CO2    0.05
-epsilon1
  Na+   Cl-    0.002
SOLUTION_SPECIES
H+ = H+
END
SIT
-epsilon
  K+  Cl-  0.0                 # after the database's END: not in the database
`, 'SIT\n-epsilon\n  H+ Cl- 0.12\n');
  const sitOf = (k) => sdb.sit.get(k);
  check('a database\'s SIT block: each pair by kind, either way round, the later one counting, a species with itself',
    sdb.model === 'SIT' && sdb.sit.size === 5 && sitOf('eps Cl- Na+').a[0] === 0.04 && sitOf('eps1 Cl- Na+').a[0] === 0.002
      && sitOf('eps CO2').a[0] === 0.05 && sitOf('eps Cl- H+').a[0] === 0.12 && !sdb.sit.has('eps Cl- K+'),
    [...sdb.sit.keys()].join(', '));
  const tk = 323.15;
  const want = 0.14 - 50 * (1 / tk - 1 / 298.15) + 0.001 * (tk - 298.15);
  check('  read to the database\'s first END, as PHREEQC reads one; its temperature terms as PHREEQC works them out',
    Math.abs(P.sitParam(sitOf('eps Ca+2 Cl-').a, tk) - want) < 1e-15 && P.sitParam(sitOf('eps Ca+2 Cl-').a, 298.155) === 0.14,
    `${P.sitParam(sitOf('eps Ca+2 Cl-').a, tk).toFixed(8)} at 50 C`);
}

/* ======================================================================
   Redox: the couples tied to the electron, against PHREEQC
   ====================================================================== */
function againstRedox(engine) {
  const back = (res) => new Map([...res.names].map(([k, v]) => [v, k]));
  const startOf = (res) => {
    const m = RtmModel.compile(res.text);
    const y = m.toConcentrations(m.initialState());
    const b = back(res);
    let worst = 0;
    let at = '';
    m.speciesNames.forEach((n, i) => {
      const want = b.has(n) ? res.molal.get(b.get(n)) : undefined;
      if (!(want > 0)) return;
      const d = Math.abs(y[i] / want - 1);
      if (d > worst) { worst = d; at = n; }
    });
    return { m, y, worst, at, pe: -Math.log10(y[m.speciesNames.indexOf('e-')]) };
  };
  // The groundwater, given as an analysis: PHREEQC's next step puts its
  // couples on one pe, and the text is that water, every couple tied.
  for (const activity of [true, false]) {
    engine.load(dbText);
    const res = P.waterToModel({ engine, database, water: { name: 'groundwater', text: groundwater }, activity, exact: true });
    const s = startOf(res);
    const e = res.report.electron;
    check(`a water given as an analysis, ${activity ? 'with its activity coefficients' : 'conditional'}: written as `
      + 'PHREEQC\'s next step, its couples tied to the electron, and the page starts on that water and its pe',
    /^e-\s+electron$/m.test(res.text) && /^Fe\+2 <=> Fe\+3 \+ e-,\s+logK = -1[0-9]\.[0-9]{10}/m.test(res.text)
      && e && e.settled && e.settled.from === -3 && Math.abs(e.settled.to - res.water.pe) < 1e-12
      && ['HS-', 'CH4', 'H2', 'Fe+3'].every((n) => e.tied.includes(n))
      && s.worst < 1e-8 && Math.abs(s.pe - res.water.pe) < 1e-9,
    `pe ${e ? `${e.settled.from} given, ${res.water.pe.toFixed(6)} at one pe` : '?'}; tied ${e ? e.tied.join(', ') : '-'}; `
      + `the start within ${s.worst.toExponential(1)} (${s.at}), pe within ${Math.abs(s.pe - res.water.pe).toExponential(1)}`);
  }
  // Given sulfide and sulfate, Fe(2) and Fe(3) out of equilibrium at pe 4:
  // the database's log K, not one read back off the water, and the start
  // where the couples settle, as PHREEQC's next step has it.
  const mixedUp = 'SOLUTION 1\n temp 25\n pH 7.0\n pe 4\n units mmol/kgw\n Na 10\n Ca 2\n Cl 14 charge\n'
    + ' S(6) 1\n S(-2) 0.01\n Fe(2) 0.01\n Fe(3) 0.001\n C(4) 2\nEND\n';
  engine.load(dbText);
  const mres = P.waterToModel({ engine, database, water: { name: 'mixed', text: mixedUp }, activity: true, exact: true });
  const ms = startOf(mres);
  check('  given valence states its pe does not hold, the water settles on one pe, as PHREEQC\'s next step has it',
    mres.report.electron.settled.from === 4 && mres.water.pe < -3 && ms.worst < 1e-8
    && /^SO4-2 \+ 9 H\+ \+ 8 e- <=> HS- \+ 4 H2O,\s+logK = 33\.6500000000/m.test(mres.text),
    `pe 4 given, ${mres.water.pe.toFixed(4)} settled; the start within ${ms.worst.toExponential(1)}`);
  // Not held exactly, no relation with electrons, as before.
  engine.load(dbText);
  const pairs = P.waterToModel({ engine, database, water: { name: 'groundwater', text: groundwater }, activity: true, relax: 1e3 });
  check('  held as fast pairs, the couples are not tied, and each valence state keeps its own total',
    !/electron/.test(pairs.text.split('<SETTINGS>')[1]) && !pairs.report.electron && pairs.report.redox.includes('H2'));

  // Oxygen fed into the groundwater at a steady rate, against PHREEQC
  // adding the same oxygen: the iron's equivalence point and past it.
  engine.load(dbText);
  const ores = P.waterToModel({ engine, database, water: { name: 'groundwater', text: groundwater }, activity: true,
    exact: true, floor: 0 });
  const k = 1e-8;
  const T = 1e4;
  const text = ores.text.replace('TEND = 1\n', `TEND = ${T}\n`)
    .replace('# Your kinetic reactions here, in the same species and units.', ` => O2, r = ${k}`);
  const m = RtmModel.compile(text);
  const steps = [0.5e-5, 2e-5, 6e-5, 1e-4];
  const t0 = Date.now();
  const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: T, rtol: 1e-8, atol: 1e-20, outputTimes: steps.map((x) => x / k) });
  const ms2 = Date.now() - t0;
  engine.load(dbText);
  const rows = P.parseRows(engine.run(`${P.punchBlock()}${groundwater}MIX 1\n 1 1.0\nSAVE solution 2\nEND\n`
    + steps.map((x, i) => `USE solution 2\nREACTION ${i + 1}\n O2 1\n ${x} moles\nEND\n`).join('')));
  const reacted = rows.filter((x) => x.state === 'react').slice(1);
  const ob = back(ores);
  let worstSp = 0;
  let worstPe = 0;
  let at = '';
  steps.forEach((x, i) => {
    const c = m.toConcentrations(r.grid.y[i]);
    const pq = reacted[i];
    m.speciesNames.forEach((n, j) => {
      const want = ob.has(n) ? pq.species.get(ob.get(n)) : null;
      if (!want || !(want[0] > 1e-12)) return;
      const d = Math.abs(c[j] / want[0] - 1);
      if (d > worstSp) { worstSp = d; at = `${n} at ${x} mol`; }
    });
    worstPe = Math.max(worstPe, Math.abs(-Math.log10(c[m.speciesNames.indexOf('e-')]) - pq.pe));
  });
  check('oxygen into the groundwater, against PHREEQC adding the same: through the iron\'s equivalence point and past it',
    worstSp < 1e-4 && worstPe < 1e-4 && reacted[reacted.length - 1].pe > 13,
    `every species above 1e-12 within ${worstSp.toExponential(1)} (${at}), the pe within ${worstPe.toExponential(1)}, `
      + `from ${reacted[0].pe.toFixed(3)} to ${reacted[reacted.length - 1].pe.toFixed(3)}; ${m.speciesNames.length} species, ${ms2} ms`);

  // The PHREEQC tab on that run: the electron is PHREEQC's pe, and the run's
  // valence states are the ones PHREEQC shares each element out to at it.
  const reply = pageRun(text, T);
  engine.load(dbText);
  const view = P.viewRun({ engine, database, run: reply, modelText: text, unit: 's', times: 12 });
  const x = view.report.redox;
  check('  the PHREEQC tab: each water at the run\'s pe, and PHREEQC shares the valence states out as the run has them',
    x && !x.error && x.elements.includes('Fe') && x.elements.includes('S') && Math.abs(x.gap) < 1e-6
    && view.report.skipped.some((sk) => sk.name === 'e-' && /the electron/.test(sk.why)),
    x ? `pe ${x.pe[0].toFixed(3)} to ${x.pe[1].toFixed(3)}; ${x.elements.join(', ')} within ${Math.abs(x.gap).toExponential(1)} (${x.worst})`
      : 'no redox');

  // A pyrite column: oxygenated water into an aquifer with pyrite, calcite
  // and goethite, against PHREEQC's TRANSPORT. Each cell's pyrite goes, the
  // pe jumps by sixteen, and goethite takes the iron.
  const N = 20;
  const L = 0.1;
  const dx = L / N;
  const dt = 2000;
  const S = 30;
  const alpha = L / 40;
  const v = dx / dt;
  const water = (n) => `SOLUTION ${n}\n temp 25\n units mmol/kgw\n pH 7.5\n Na 2\n Ca 1\n Cl 2 charge\n C(4) 3\n S(6) 0.5\n Fe 0.001\n`;
  const phases = (n) => `EQUILIBRIUM_PHASES ${n}\n Pyrite 0 5e-5\n Calcite 0 0.01\n Goethite 0 0\n`;
  const inflow = 'SOLUTION 0\n temp 25\n units mmol/kgw\n pH 7.5\n Na 2\n Ca 1\n Cl 2 charge\n C(4) 3\n S(6) 0.5\n'
    + ' O(0) 0.25\n Fe 1e-9\nEND\n';
  engine.load(dbText);
  let started = Date.now();
  const prow = engine.run(`${water(`1-${N}`)}END\n${phases(`1-${N}`)}END\nRUN_CELLS\n -cells 1-${N}\nEND\n${inflow}`
    + 'SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings cell time pH pe S6 Fe py\n -start\n'
    + '10 PUNCH CELL_NO, TOTAL_TIME, -LA("H+"), -LA("e-"), TOT("S(6)"), TOT("Fe"), EQUI("Pyrite")\n -end\n'
    + `TRANSPORT\n -cells ${N}\n -shifts ${S}\n -time_step ${dt}\n -lengths ${dx}\n -dispersivities ${alpha}\n`
    + ` -diffusion_coefficient 0\n -flow_direction forward\n -boundary_conditions flux flux\n -punch_cells 1-${N}\n`
    + ` -punch_frequency 1\n -print_frequency ${10 * S}\nEND\n`);
  const pqMs = Date.now() - started;
  const head = prow[0].map((h) => String(h).trim());
  const pq = new Map();
  for (const row of prow.slice(1)) {
    const t = Number(row[head.indexOf('time')]);
    if (!(t > 0)) continue;
    const o = {};
    for (const key of ['pH', 'pe', 'S6', 'Fe', 'py']) o[key] = Number(row[head.indexOf(key)]);
    pq.set(`${Number(row[head.indexOf('cell')])}/${Math.round(t / dt)}`, o);
  }
  engine.load(dbText);
  const cres = P.waterToModel({ engine, database, water: { name: 'column', text: `${water(1)}${phases(1)}END\n` },
    activity: true, exact: true, phases: true, floor: 0 });
  engine.load(dbText);
  const inRow = P.parseRows(engine.run(`${P.punchBlock()}${inflow}MIX 1\n 0 1.0\nEND\n`)).pop();
  const cb = back(cres);
  const ctext = cres.text
    .replace('MODE = batch', `MODE = transport\nCELLS = ${N}\nLENGTH = ${L}\nDIFFUSION = 1\nADVECTION = 1\n`
      + `ADVECTION_SCHEME = limited\nVELOCITY = ${v}\nPECLET = ${L / alpha}\nLEFT = robin\nRIGHT = free`)
    .replace('TEND = 1\n', `TEND = ${(S + 0.5) * dt}\n`)
    .replace(SPECIES_LINE, (line, name, gap, value, rest) => {
      if (/mineral/.test(rest) || !cb.has(name)) return line;
      const sp = inRow.species.get(cb.get(name));
      return `${line}  left=${sp ? sp[0] : 0}`;
    });
  const cm = RtmModel.compile(ctext);
  started = Date.now();
  const cr = FacsimileODE.runModel(cm, { solver: 'ndf', tend: (S + 0.5) * dt, rtol: 1e-6, atol: 1e-20, nonNegative: true,
    stagnationTol: 0.5, belowTolRun: 5, outputTimes: Array.from({ length: S }, (_, kk) => (kk + 1.5) * dt) });
  const rtmMs = Date.now() - started;
  const ns = cm.speciesNames.length;
  const db = P.readDatabase(dbText);
  const sum = (label) => {
    const out = [];
    cm.speciesNames.forEach((n, i) => {
      if (!cb.has(n)) return;
      for (const [kk, cc] of db.expand(cb.get(n))) if (P.normLabel(kk) === label) out.push([i, cc]);
    });
    return out;
  };
  const s6 = sum('S(6)');
  const fe = [...sum('Fe(2)'), ...sum('Fe(3)')];
  const iH = cm.speciesNames.indexOf('H+');
  const iE = cm.speciesNames.indexOf('e-');
  const iPy = cm.speciesNames.indexOf('Pyrite');
  const lnG = new Float64Array(ns);
  const dG = new Float64Array(ns);
  const worst = { pH: 0, pe: 0, S6: 0, Fe: 0 };
  for (let kk = 1; kk <= S; kk++) {
    const c = cm.toConcentrations(cr.grid.y[kk - 1]);
    const b = (N - 1) * ns;
    RtmModel.activityAt(cm.act, c, b, lnG, dG);
    const o = { pH: -(Math.log(c[b + iH]) + lnG[iH]) / Math.LN10, pe: -Math.log10(c[b + iE]),
      S6: s6.reduce((a, [i, cc]) => a + cc * c[b + i], 0), Fe: fe.reduce((a, [i, cc]) => a + cc * c[b + i], 0) };
    const d = pq.get(`${N}/${kk}`);
    for (const key of Object.keys(worst)) worst[key] = Math.max(worst[key], Math.abs(o[key] - d[key]));
  }
  const end = cm.toConcentrations(cr.grid.y[S - 1]);
  let gone = 0;
  let pqGone = 0;
  let left = 0;
  let pqLeft = 0;
  for (let cell = 0; cell < N; cell++) {
    if (!(end[cell * ns + iPy] > 0)) gone++;
    left += end[cell * ns + iPy];
    const d = pq.get(`${cell + 1}/${S}`);
    if (!(d.py > 0)) pqGone++;
    pqLeft += d.py;
  }
  check('a pyrite column, oxygenated water in, against PHREEQC\'s TRANSPORT: the effluent, and the pyrite gone and left',
    worst.pH < 0.005 && worst.pe < 0.005 && worst.S6 < 3e-6 && worst.Fe < 2e-9 && Math.abs(gone - pqGone) <= 1
    && Math.abs(left / pqLeft - 1) < 0.05 && cr.events.length === gone,
    `effluent pH within ${worst.pH.toFixed(4)}, pe ${worst.pe.toFixed(4)}, sulfate ${(worst.S6 * 1e3).toFixed(5)} mM, `
      + `iron ${(worst.Fe * 1e3).toExponential(2)} mM; pyrite gone from ${gone} cells (PHREEQC ${pqGone}), `
      + `${((left / pqLeft - 1) * 100).toFixed(1)} % left; ${N} cells, ${S} shifts: PHREEQC ${pqMs} ms, the page ${rtmMs} ms`);
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
  // Written as the database's analytic expression, moved to the conditional log K at this water.
  const logkC = RtmModel.compile(carb.text).equilibria.find((eq) => eq.text.startsWith('CO3-2 + H+ <=> HCO3-')).lnK / Math.LN10;
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
  const ex = P.waterToModel({ engine, database, water, exact: true, redox: false });
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
  const own = P.waterToModel({ engine, database, water, exact: true, dw: true, redox: false });
  const one = P.waterToModel({ engine, database, water, exact: true, D: 2e-9, redox: false });
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
  // A line as PHREEQC's read_equilibrium_phases takes it: the SI, a word beginning with a letter an alternative
  // formula or phase, the amount, d... or p..., and -force_equality on the line after, true unless it begins with f.
  const plain = (name, si) => ({ name, si, alt: null, only: null, forced: false, extra: '' });
  const assemblage = P.readAssemblage('EQUILIBRIUM_PHASES 1\n Calcite 0 0.002\n CO2(g) -2.0 10\n Fix_H+ -8 NaOH 0.01\n'
    + ' Gypsum 0 0.01 dissolve_only\n Anhydrite 0 Calcite 0.1 p\n -force_equality true\n Quartz\n -force_equality false\nEND\n');
  check('a phase\'s reaction is read: Calcite is CaCO3 = CO3-2 + Ca+2; the input\'s EQUILIBRIUM_PHASES with their SI, '
    + 'an alternative formula or phase, d... and p..., and -force_equality',
  JSON.stringify(P.readDatabase(dbText).phaseReaction.get('Calcite')) === JSON.stringify({ left: [{ c: 1, n: 'CaCO3' }],
    right: [{ c: 1, n: 'CO3-2' }, { c: 1, n: 'Ca+2' }] })
    && JSON.stringify(assemblage) === JSON.stringify([plain('Calcite', 0), plain('CO2(g)', -2),
      { ...plain('Fix_H+', -8), alt: 'NaOH' }, { ...plain('Gypsum', 0), only: 'dissolve' },
      { ...plain('Anhydrite', 0), alt: 'Calcite', only: 'precipitate', forced: true }, plain('Quartz', 0)]),
  JSON.stringify(assemblage));
  const phasesIn = 'EQUILIBRIUM_PHASES 1\n Calcite 0 0.002\n CO2(g) -2.0 10\n Pyrite 0 0\n';
  const phaseWater = { name: 'groundwater', text: groundwater.replace('END', phasesIn) };
  let notHeld = '';
  try { P.waterToModel({ engine, database, water: phaseWater, phases: true }); } catch (e) { notHeld = e.message; }
  check('... phases are kept at saturation only with the relations held exactly', /needs the relations held exactly/.test(notHeld),
    notHeld);
  const ph = P.waterToModel({ engine, database, water: phaseWater, activity: true, exact: true, phases: true, redox: false });
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
  let llnl = '';
  try {
    // Before the database: PHREEQC reads one to its first END, and so does the page.
    P.waterToModel({ engine, database: { name: 'llnl', text: `LLNL_AQUEOUS_MODEL_PARAMETERS\n-temperatures\n 0 25\n${dbText}` },
      water, activity: true });
  } catch (e) { llnl = e.message; }
  check('... and a database with LLNL\'s activity model and none of its tables is not followed, and says so',
    /LLNL's activity model without its tables/.test(llnl), llnl.slice(0, 90));
  const fol = P.waterToModel({ engine, database, water, activity: true, exact: true, redox: false });
  const mf = RtmModel.compile(fol.text);
  const backF = new Map([...fol.names].map(([k, v]) => [v, k]));
  const cf = mf.toConcentrations(mf.initialState());
  let worstF = 0;
  mf.speciesNames.forEach((n, i) => { worstF = Math.max(worstF, Math.abs(cf[i] / fol.molal.get(backF.get(n)) - 1)); });
  check('following the ionic strength: ACTIVITY at the water\'s temperature, the water in the relations, '
    + 'the database\'s log K; the start on PHREEQC\'s molalities from the page\'s own activity coefficients',
  /^ACTIVITY = debye-huckel$/m.test(fol.text) && /^TEMPERATURE = 15$/m.test(fol.text)
    // The water's dissociation as the database's analytic expression, -14.343286 at 15 C.
    && /^H2O <=> OH- \+ H\+, +analytic = /m.test(fol.text)
    && Math.abs(mf.equilibria.find((eq) => eq.text.startsWith('H2O <=> OH- + H+')).lnK / Math.LN10 + 14.343286) < 1e-6
    && /^Ca\+2 .* a=5 {2}b=0\.165$/m.test(fol.text)
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
  const fixedRes = P.waterToModel({ engine, database, water, exact: true, redox: false });
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
    .replace(SPECIES_LINE, (line, name, gap, value, rest) => {
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
    .replace(SPECIES_LINE, (line, name, gap, value, rest) => {
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

function againstSurface(engine) {
  // PHREEQC's Example 8 water, zinc on hydrous ferric oxide, without electrostatics.
  const ex8 = (sfOpts) => 'SOLUTION 1\n units mmol/kgw\n pH 8.0\n Zn 0.0001\n Na 100 charge\n N(5) 100\n'
    + `SURFACE 1\n Hfo_sOH 5e-6 600 0.09\n Hfo_wOH 2e-4\n -equilibrate 1\n${sfOpts}END\n`;
  for (const activity of [true, false]) {
    engine.load(dbText);
    const res = P.waterToModel({ engine, database, water: { name: 'Example 8', text: ex8(' -no_edl\n') }, activity,
      exact: true });
    const m = RtmModel.compile(res.text);
    const y = m.toConcentrations(m.initialState());
    const back = new Map([...res.names].map(([k, n]) => [n, k]));
    let worst = 0;
    m.speciesNames.forEach((n, i) => {
      const ref = back.has(n) ? res.molal.get(back.get(n)) : res.amounts.get(n);
      if (ref !== undefined) worst = Math.max(worst, Math.abs(y[i] - ref) / Math.max(ref, 1e-15));
    });
    const sf = res.report.surface;
    const lines = /^Hfo_wOH\s+\S+\s+surface$/m.test(res.text) && /^Hfo_sOZn\+\s+\S+\s+surface$/m.test(res.text)
      && (activity ? /^Hfo_wOH \+ Zn\+2 <=> Hfo_wOZn\+ \+ H\+,\s+logK = -1\.9900000000/m.test(res.text)
        : /^Hfo_wOH \+ Zn\+2 <=> Hfo_wOZn\+ \+ H\+,\s+logK = -2\.3\d+\s+# log K -1\.9900/m.test(res.text));
    check(`a surface in the water (-no_edl), ${activity ? 'with its activity coefficients' : 'conditional'}: the sites `
      + 'and the species on them written, and the page starts from what PHREEQC put there',
    lines && worst < 1e-8 && sf && sf.species.length === 8 && sf.sites.join() === 'Hfo_sOH,Hfo_wOH'
      && !res.report.surfaceSkipped.length,
    `${sf ? sf.species.length : 0} species on ${sf ? sf.sites.join(', ') : 'nothing'}; within ${worst.toExponential(1)}`);
  }
  engine.load(dbText);
  const apart = P.waterToModel({ engine, database, water: { name: 'Example 8', text: ex8(' -no_edl\n') }, activity: true,
    exact: false });
  check('  not held exactly, the surface is said and not carried',
    !/ surface$/m.test(apart.text) && /held exactly/.test(apart.report.surfaceSkipped.map((x) => x.why).join()));

  // Zinc into a column of ferrihydrite against PHREEQC's TRANSPORT. The
  // background NaCl, so that no redox couple moves the pH.
  const N = 40;
  const L = 0.08;
  const dx = L / N;
  const dt = 720;
  const S = 3 * N;
  const alpha = 0.002;
  const v = dx / dt;
  const bg = (n) => `SOLUTION ${n}\n units mmol/kgw\n temp 25\n pH 6.5\n Na 10 charge\n Cl 10\n Zn 1e-9\n`;
  const sfBlock = (n) => `SURFACE ${n}\n -equilibrate 1\n -no_edl\n Hfo_sOH 5e-6\n Hfo_wOH 2e-4\n`;
  const loaded = `${bg(1)}${sfBlock(1)}END\n`;
  const inflow = 'SOLUTION 0\n units mmol/kgw\n temp 25\n pH 6.5\n Na 10 charge\n Cl 10\n Zn 0.1\nEND\n';
  engine.load(dbText);
  const started = Date.now();
  const rows = engine.run(`${bg(`1-${N}`)}END\n${sfBlock(`1-${N}`)}END\n${inflow}`
    + 'SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings cell time Zn pH\n -start\n'
    + '10 PUNCH CELL_NO, TOTAL_TIME, TOT("Zn"), -LA("H+")\n -end\n'
    + `TRANSPORT\n -cells ${N}\n -shifts ${S}\n -time_step ${dt}\n -lengths ${dx}\n -dispersivities ${alpha}\n`
    + ` -diffusion_coefficient 0\n -flow_direction forward\n -boundary_conditions flux flux\n -punch_cells ${N}\n`
    + ` -punch_frequency 1\n -print_frequency ${10 * S}\nEND\n`);
  const pqMs = Date.now() - started;
  const head = rows[0].map((h) => String(h).trim());
  const pq = new Map();
  for (const r of rows.slice(1)) {
    const t = Number(r[head.indexOf('time')]);
    if (t > 0) pq.set(Math.round(t / dt), { Zn: Number(r[head.indexOf('Zn')]), pH: Number(r[head.indexOf('pH')]) });
  }
  engine.load(dbText);
  const res = P.waterToModel({ engine, database, water: { name: 'column', text: loaded }, activity: true, exact: true });
  const inRow = P.parseRows(engine.run(`${P.punchBlock()}${inflow}`)).pop();
  const back = new Map([...res.names].map(([k, n]) => [n, k]));
  const text = res.text
    .replace('MODE = batch', `MODE = transport\nCELLS = ${N}\nLENGTH = ${L}\nDIFFUSION = 1\nADVECTION = 1\n`
      + `ADVECTION_SCHEME = limited\nVELOCITY = ${v}\nPECLET = ${L / alpha}\nLEFT = robin\nRIGHT = free`)
    .replace('TEND = 1\n', `TEND = ${(S + 0.5) * dt}\n`)
    .replace(SPECIES_LINE, (line, name, gap, value, rest) => {
      if (/mineral|exchange|surface/.test(rest) || !back.has(name)) return line;
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
  const zn = [];
  m.speciesNames.forEach((n, i) => {
    if (!back.has(n)) return;
    const ex = db.expand(back.get(n));
    if (ex.has('Zn')) zn.push([i, ex.get('Zn')]);
  });
  const iH = m.speciesNames.indexOf('H+');
  const lnG = new Float64Array(ns);
  const dG = new Float64Array(ns);
  let wZn = 0;
  let wpH = 0;
  let end = null;
  for (let k = 1; k <= S; k++) {
    const c = m.toConcentrations(r.grid.y[k - 1]);
    const cell = c.subarray((N - 1) * ns, N * ns);
    let tot = 0;
    for (const [i, kk] of zn) tot += kk * cell[i];
    RtmModel.activityAt(m.act, cell, 0, lnG, dG, N - 1);
    const pH = -Math.log10(cell[iH]) - lnG[iH] / Math.LN10;
    wZn = Math.max(wZn, Math.abs(tot - pq.get(k).Zn));
    wpH = Math.max(wpH, Math.abs(pH - pq.get(k).pH));
    if (k === S) end = { Zn: Math.abs(tot - pq.get(k).Zn), pH: Math.abs(pH - pq.get(k).pH), at: pH };
  }
  check('zinc into a column of ferrihydrite (-no_edl) against PHREEQC\'s TRANSPORT: the effluent, the pH falling ahead '
    + 'of the zinc', wZn < 6e-7 && wpH < 0.02 && end.Zn < 2e-8 && end.pH < 5e-4,
  `within ${(wZn * 1e6).toFixed(3)} umol/kgw of zinc (of 100) and ${wpH.toFixed(4)} in pH; after three pore volumes `
    + `${(end.Zn * 1e6).toFixed(4)} and ${end.pH.toFixed(5)}, at pH ${end.at.toFixed(3)}; ${N} cells: PHREEQC ${pqMs} ms, `
    + `the page ${rtmMs} ms`);

  // The PHREEQC tab: the run's surface against PHREEQC's loaded from each water.
  const reply = pageRun(text.replace(/^CELLS = \d+$/m, 'CELLS = 10').replace(`LENGTH = ${L}`, `LENGTH = ${L / 4}`)
    .replace(/^TEND = .*$/m, `TEND = ${30 * dt}`), 30 * dt);
  engine.load(dbText);
  const view = P.viewRun({ engine, database, run: reply, modelText: text, water: { name: 'column', text: loaded },
    unit: 's', times: 15 });
  const x = view.report.surface;
  check('  the PHREEQC tab loads PHREEQC\'s surface from each water of a run: the fractions the run holds',
    x && !x.error && Math.abs(x.gap) < 1e-6 && view.report.unmapped.length === 0 && !view.report.unchecked.length
    && view.report.skipped.some((sk) => sk.name === 'Hfo_wOZn+' && /on a surface/.test(sk.why)),
    x ? `within ${Math.abs(x.gap).toExponential(1)} (${x.worst}) over ${view.report.waters} waters` : 'no surface');
}

function againstDoubleLayer(engine) {
  const F = 96493.5;
  const Rg = 8.31470;
  // Example 8 as PHREEQC has it, with its double layer: the hand-off, both ways.
  const ex8 = 'SOLUTION 1\n units mmol/kgw\n pH 8.0\n Zn 0.0001\n Na 100 charge\n N(5) 100\n'
    + 'SURFACE 1\n Hfo_sOH 5e-6 600 0.09\n Hfo_wOH 2e-4\n -equilibrate 1\nEND\n';
  engine.load(dbText);
  const probe = engine.run('SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings psi\n -start\n'
    + `10 PUNCH EDL("psi", "Hfo")\n -end\n${ex8}`);
  const psiPq = Number(probe[probe.length - 1][0]);
  for (const activity of [true, false]) {
    engine.load(dbText);
    const res = P.waterToModel({ engine, database, water: { name: 'Example 8', text: ex8 }, activity, exact: true });
    const m = RtmModel.compile(res.text);
    const y = m.toConcentrations(m.initialState());
    const back = new Map([...res.names].map(([k, n]) => [n, k]));
    let worst = 0;
    m.speciesNames.forEach((n, i) => {
      const ref = back.has(n) ? res.molal.get(back.get(n)) : res.amounts.get(n);
      if (ref !== undefined) worst = Math.max(worst, Math.abs(y[i] - ref) / Math.max(ref, 1e-15));
    });
    const psi = -Math.log(y[m.speciesNames.indexOf('Hfo_psi')]) * Rg * 298.15 / F;
    const pots = res.report.surface && res.report.surface.potentials;
    check(`a surface with its double layer, ${activity ? 'with its activity coefficients' : 'conditional'}: its potential `
      + 'written with the area and grams, and the page starts from PHREEQC\'s water, surface and potential',
    /^Hfo_psi\s+\S+\s+potential\s+area=600\s+grams=0\.09$/m.test(res.text) && worst < 1e-8
      && Math.abs(psi - psiPq) < 1e-9 && pots && pots.length === 1 && Math.abs(pots[0].psi - psiPq) < 1e-15
      && (activity || /^TEMPERATURE = 25$/m.test(res.text)),
    `within ${worst.toExponential(1)}; psi ${(psi * 1e3).toFixed(6)} mV, PHREEQC's ${(psiPq * 1e3).toFixed(6)}`);
  }

  // Sites loaded from PHREEQC's first water, then the whole speciated: the
  // page's two steps against PHREEQC's -equilibrate and its reaction step.
  // NaCl, so that no redox couple moves the pH in PHREEQC's reaction step.
  const sol = 'SOLUTION 1\n units mmol/kgw\n pH 8.0\n Zn 0.0001\n Na 100 charge\n Cl 100\n';
  const water = `${sol}SURFACE 1\n Hfo_sOH 5e-6 600 0.09\n Hfo_wOH 2e-4\n -equilibrate 1\nEND\n`;
  engine.load(dbText);
  const res = P.waterToModel({ engine, database, water: { name: 'Example 8', text: water }, activity: true, exact: true });
  const init = P.parseRows(engine.run(`${P.punchBlock()}${sol}END\n`)).pop();
  const back = new Map([...res.names].map(([k, n]) => [n, k]));
  const text = res.text.replace(SPECIES_LINE, (line, name, gap, value, rest) => {
    if (/potential/.test(rest)) return `${name}${gap}${rest.trim()}`;
    if (/surface/.test(rest)) {
      return `${name}${gap}surface${{ Hfo_sOH: ' sites=5e-6', Hfo_wOH: ' sites=2e-4' }[name] || ''}`;
    }
    if (!back.has(name)) return line;
    const sp = init.species.get(back.get(name));
    return `${name}${gap}${sp ? sp[0] : 0}${rest}`;
  });
  const m = RtmModel.compile(text);
  const y = m.toConcentrations(m.initialState());
  let worst = 0;
  m.speciesNames.forEach((n, i) => {
    const ref = back.has(n) ? res.molal.get(back.get(n)) : res.amounts.get(n);
    if (ref !== undefined) worst = Math.max(worst, Math.abs(y[i] - ref) / Math.max(ref, 1e-15));
  });
  check('  sites loaded from the first water, its potential with them, then the whole speciated: PHREEQC\'s '
    + '-equilibrate and its reaction step', worst < 1e-8 && /Hfo_wOH +surface sites=2e-4/.test(text),
  `within ${worst.toExponential(1)}`);

  // Zinc into a column of ferrihydrite with its double layer, against PHREEQC's TRANSPORT.
  const N = 40;
  const L = 0.08;
  const dx = L / N;
  const dt = 720;
  const S = 3 * N;
  const alpha = 0.002;
  const v = dx / dt;
  const bg = (n) => `SOLUTION ${n}\n units mmol/kgw\n temp 25\n pH 6.5\n Na 10 charge\n Cl 10\n Zn 1e-9\n`;
  const sfBlock = (n) => `SURFACE ${n}\n -equilibrate 1\n Hfo_sOH 5e-6 600 0.09\n Hfo_wOH 2e-4\n`;
  const loaded = `${bg(1)}${sfBlock(1)}END\n`;
  const inflow = 'SOLUTION 0\n units mmol/kgw\n temp 25\n pH 6.5\n Na 10 charge\n Cl 10\n Zn 0.1\nEND\n';
  engine.load(dbText);
  const started = Date.now();
  const rows = engine.run(`${bg(`1-${N}`)}END\n${sfBlock(`1-${N}`)}END\n${inflow}`
    + 'SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings cell time Zn pH\n -start\n'
    + '10 PUNCH CELL_NO, TOTAL_TIME, TOT("Zn"), -LA("H+")\n -end\n'
    + `TRANSPORT\n -cells ${N}\n -shifts ${S}\n -time_step ${dt}\n -lengths ${dx}\n -dispersivities ${alpha}\n`
    + ` -diffusion_coefficient 0\n -flow_direction forward\n -boundary_conditions flux flux\n -punch_cells ${N}\n`
    + ` -punch_frequency 1\n -print_frequency ${10 * S}\nEND\n`);
  const pqMs = Date.now() - started;
  const head = rows[0].map((h) => String(h).trim());
  const pq = new Map();
  for (const r of rows.slice(1)) {
    const t = Number(r[head.indexOf('time')]);
    if (t > 0) pq.set(Math.round(t / dt), { Zn: Number(r[head.indexOf('Zn')]), pH: Number(r[head.indexOf('pH')]) });
  }
  engine.load(dbText);
  const cres = P.waterToModel({ engine, database, water: { name: 'column', text: loaded }, activity: true, exact: true });
  const inRow = P.parseRows(engine.run(`${P.punchBlock()}${inflow}`)).pop();
  const cback = new Map([...cres.names].map(([k, n]) => [n, k]));
  const ctext = cres.text
    .replace('MODE = batch', `MODE = transport\nCELLS = ${N}\nLENGTH = ${L}\nDIFFUSION = 1\nADVECTION = 1\n`
      + `ADVECTION_SCHEME = limited\nVELOCITY = ${v}\nPECLET = ${L / alpha}\nLEFT = robin\nRIGHT = free`)
    .replace('TEND = 1\n', `TEND = ${(S + 0.5) * dt}\n`)
    .replace(SPECIES_LINE, (line, name, gap, value, rest) => {
      if (/mineral|exchange|surface|potential/.test(rest) || !cback.has(name)) return line;
      const sp = inRow.species.get(cback.get(name));
      return `${line}  left=${sp ? sp[0] : 0}`;
    });
  const cm = RtmModel.compile(ctext);
  const t0 = Date.now();
  const r = FacsimileODE.runModel(cm, { solver: 'ndf', tend: (S + 0.5) * dt, rtol: 1e-7, atol: 1e-20, nonNegative: true,
    outputTimes: Array.from({ length: S }, (_, k) => (k + 1.5) * dt) });
  const rtmMs = Date.now() - t0;
  const ns = cm.speciesNames.length;
  const db = P.readDatabase(dbText);
  const zn = [];
  cm.speciesNames.forEach((n, i) => {
    if (!cback.has(n)) return;
    const ex = db.expand(cback.get(n));
    if (ex.has('Zn')) zn.push([i, ex.get('Zn')]);
  });
  const iH = cm.speciesNames.indexOf('H+');
  const lnG = new Float64Array(ns);
  const dG = new Float64Array(ns);
  let wZn = 0;
  let wpH = 0;
  let end = null;
  for (let k = 1; k <= S; k++) {
    const c = cm.toConcentrations(r.grid.y[k - 1]);
    const cell = c.subarray((N - 1) * ns, N * ns);
    let tot = 0;
    for (const [i, kk] of zn) tot += kk * cell[i];
    RtmModel.activityAt(cm.act, cell, 0, lnG, dG, N - 1);
    const pH = -Math.log10(cell[iH]) - lnG[iH] / Math.LN10;
    wZn = Math.max(wZn, Math.abs(tot - pq.get(k).Zn));
    wpH = Math.max(wpH, Math.abs(pH - pq.get(k).pH));
    if (k === S) end = { Zn: Math.abs(tot - pq.get(k).Zn), pH: Math.abs(pH - pq.get(k).pH), at: pH };
  }
  check('zinc into a column of ferrihydrite with its double layer against PHREEQC\'s TRANSPORT: the effluent',
    wZn < 6e-7 && wpH < 0.02 && end.Zn < 3e-8 && end.pH < 5e-4,
    `within ${(wZn * 1e6).toFixed(3)} umol/kgw of zinc (of 100) and ${wpH.toFixed(4)} in pH; after three pore volumes `
      + `${(end.Zn * 1e6).toFixed(4)} and ${end.pH.toFixed(5)}, at pH ${end.at.toFixed(3)}; ${N} cells: PHREEQC ${pqMs} ms, `
      + `the page ${rtmMs} ms`);

  // The PHREEQC tab: the run's surface and potential against PHREEQC's loaded from each water.
  const reply = pageRun(ctext.replace(/^CELLS = \d+$/m, 'CELLS = 10').replace(`LENGTH = ${L}`, `LENGTH = ${L / 4}`)
    .replace(/^TEND = .*$/m, `TEND = ${30 * dt}`), 30 * dt);
  engine.load(dbText);
  const view = P.viewRun({ engine, database, run: reply, modelText: ctext, water: { name: 'column', text: loaded },
    unit: 's', times: 15 });
  const x = view.report.surface;
  check('  the PHREEQC tab loads PHREEQC\'s surface with its double layer from each water: the fractions and the '
    + 'potential the run holds',
  x && !x.error && Math.abs(x.gap) < 1e-6 && x.psiGap && Math.abs(x.psiGap.by) < 1e-9
    && view.report.skipped.some((sk) => sk.name === 'Hfo_psi' && /potential/.test(sk.why)) && !view.report.unmapped.length,
  x ? `within ${Math.abs(x.gap).toExponential(1)} (${x.worst}), the potential within `
    + `${x.psiGap ? Math.abs(x.psiGap.by).toExponential(1) : '?'} V, over ${view.report.waters} waters` : 'no surface');
}

/* ======================================================================
   SIT: PHREEQC's specific ion interaction theory

   A database with a SIT block gives PHREEQC SIT's activity coefficients,
   and the page follows them: ACTIVITY = sit, the database's coefficients
   between the species written in <SIT>. The checks always run on
   phreeqc.dat with a SIT block of our own -- made-up coefficients, put
   before the database because PHREEQC reads a database to its first END --
   and, where this machine has it, on PHREEQC's own sit.dat (ThermoChimie;
   never shipped, read where the PHREEQC build left it or RTM_SIT_DAT says).
   KNOBS asks PHREEQC for its gammas to 1e-14 (1e-12 in TRANSPORT, which
   does not settle every shift closer): by default its SIT stops at 1e-7.
   ====================================================================== */
const SIT_OWN = `SIT
# Made-up coefficients for these tests, nobody's data.
-epsilon
  Na+     Cl-     0.05
  K+      Cl-     0.02
  Ca+2    Cl-     0.1
  Mg+2    Cl-     0.2
  H+      Cl-     0.1
  Na+     OH-     0.05
  Na+     HCO3-   0.0
  Na+     CO3-2  -0.05
  Na+     SO4-2  -0.1
  Na+     NO3-   -0.05
  K+      NO3-   -0.1
  Ca+2    NO3-    0.05
  CaHCO3+ Cl-     0.1
  Fe+2    Cl-     0.15
  Fe+3    Cl-     0.3
  Na+     HS-     0.05
  CO2     Na+     0.02
  CO2     Cl-     0.02
-epsilon1
  Na+     Cl-     0.001
`;
const KNOBS = 'KNOBS\n -convergence_tolerance 1e-14\n';
// TRANSPORT does not settle every shift at 1e-14.
const KNOBS_COLUMN = 'KNOBS\n -convergence_tolerance 1e-12\n';

/** Brine into a column of fresh water at calcite saturation, against PHREEQC's TRANSPORT. */
function sitColumn(engine, db, N, pv) {
  const L = 0.1;
  const dx = L / N;
  const dt = 1000;
  const S = pv * N;
  const alpha = L / 40;
  const v = dx / dt;
  const water = (n) => `SOLUTION ${n}\n temp 25\n units mol/kgw\n pH 7.5\n Na 0.01\n Ca 0.001\n Cl 0.01 charge\n C(4) 0.003\n`;
  const brine = 'SOLUTION 0\n temp 25\n units mol/kgw\n pH 7.5\n Na 2\n Ca 0.001\n Cl 2 charge\n C(4) 0.003\nEND\n';
  engine.load(db.text);
  let started = Date.now();
  const rows = engine.run(`${KNOBS_COLUMN}${water(`1-${N}`)}END\nEQUILIBRIUM_PHASES 1-${N}\n Calcite 0 0.01\nEND\n`
    + `RUN_CELLS\n -cells 1-${N}\nEND\n${brine}`
    + 'SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings cell time pH Ca Na\n -start\n'
    + '10 PUNCH CELL_NO, TOTAL_TIME, -LA("H+"), TOT("Ca"), TOT("Na")\n -end\n'
    + `TRANSPORT\n -cells ${N}\n -shifts ${S}\n -time_step ${dt}\n -lengths ${dx}\n -dispersivities ${alpha}\n`
    + ` -diffusion_coefficient 0\n -flow_direction forward\n -boundary_conditions flux flux\n -punch_cells ${N}\n`
    + ` -punch_frequency 1\n -print_frequency ${10 * S}\nEND\n`);
  const pqMs = Date.now() - started;
  const head = rows[0].map((h) => String(h).trim());
  const pq = new Map();
  for (const r of rows.slice(1)) {
    const t = Number(r[head.indexOf('time')]);
    if (t > 0) pq.set(Math.round(t / dt), { pH: Number(r[head.indexOf('pH')]), Ca: Number(r[head.indexOf('Ca')]), Na: Number(r[head.indexOf('Na')]) });
  }
  engine.load(db.text);
  const res = P.waterToModel({ engine, database: db, water: { name: 'column', text: `${KNOBS_COLUMN}${water(1)}EQUILIBRIUM_PHASES 1\n Calcite 0 0.01\nEND\n` },
    activity: true, exact: true, phases: true, redox: false });
  const inflow = P.parseRows(engine.run(`${KNOBS_COLUMN}${P.punchBlock()}${brine}`)).pop();
  const back = new Map([...res.names].map(([k, n]) => [n, k]));
  const text = res.text
    .replace('MODE = batch', `MODE = transport\nCELLS = ${N}\nLENGTH = ${L}\nDIFFUSION = 1\nADVECTION = 1\n`
      + `ADVECTION_SCHEME = limited\nVELOCITY = ${v}\nPECLET = ${L / alpha}\nLEFT = robin\nRIGHT = free`)
    .replace('TEND = 1\n', `TEND = ${(S + 0.5) * dt}\n`)
    .replace(SPECIES_LINE, (line, name, gap, value, rest) => {
      if (/mineral/.test(rest) || !back.has(name)) return line;
      const sp = inflow.species.get(back.get(name));
      return `${line}  left=${sp ? sp[0] : 0}`;
    });
  const m = RtmModel.compile(text);
  started = Date.now();
  const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: (S + 0.5) * dt, rtol: 1e-7, atol: 1e-20, nonNegative: true,
    outputTimes: Array.from({ length: S }, (_, k) => (k + 1.5) * dt) });
  const rtmMs = Date.now() - started;
  const ns = m.speciesNames.length;
  const rdb = P.readDatabase(db.text);
  const of = { Ca: [], Na: [] };
  m.speciesNames.forEach((n, i) => {
    if (!back.has(n)) return;
    const ex = rdb.expand(back.get(n));
    for (const el of ['Ca', 'Na']) if (ex.has(el)) of[el].push([i, ex.get(el)]);
  });
  const iH = m.speciesNames.indexOf('H+');
  const lnG = new Float64Array(ns);
  const dG = new Float64Array(ns);
  const out = { pH: 0, Ca: 0, Na: 0, endPH: 0, endCa: 0, pqMs, rtmMs, I: 0 };
  for (let k = 1; k <= S; k++) {
    const c = m.toConcentrations(r.grid.y[k - 1]);
    const b = (N - 1) * ns;
    const w = RtmModel.activityAt(m.act, c, b, lnG, dG);
    const o = { pH: -(Math.log(c[b + iH]) + lnG[iH]) / Math.LN10 };
    for (const el of ['Ca', 'Na']) o[el] = of[el].reduce((a, [i, kk]) => a + kk * c[b + i], 0);
    const d = pq.get(k);
    out.pH = Math.max(out.pH, Math.abs(o.pH - d.pH));
    out.Ca = Math.max(out.Ca, Math.abs(o.Ca - d.Ca));
    out.Na = Math.max(out.Na, Math.abs(o.Na - d.Na));
    out.I = Math.max(out.I, w.I);
    if (k === S) { out.endPH = Math.abs(o.pH - d.pH); out.endCa = Math.abs(o.Ca / d.Ca - 1); out.plateau = o.pH; }
  }
  return out;
}

/*
  PHREEQC's SIT takes its Debye-Hueckel A at the a(H2O) a calculation starts
  from (sit.cpp's PTEMP_SIT, once a calculation): 1 for an initial solution,
  the water's own when a reaction step starts from it. The page's A is at the
  water's own a(H2O), so a water to hold the page against goes through two
  steps of nothing, MIX, the second starting from the a(H2O) the first gave.
*/
const SIT_STEP = 'MIX 1\n 1 1.0\nSAVE solution 1\nEND\n';
const SIT_STEPS = SIT_STEP.repeat(2);

/** The page's log10 gamma of each species PHREEQC has, at PHREEQC's molalities, and the water's. */
function sitAtPhreeqc(res) {
  const m = RtmModel.compile(res.text);
  const ns = m.speciesNames.length;
  const C = new Float64Array(ns);
  for (const [p, n] of res.names) C[m.speciesNames.indexOf(n)] = res.molal.get(p);
  const lnG = new Float64Array(ns);
  const w = RtmModel.activityAt(m.act, C, 0, lnG, new Float64Array(ns));
  const lg = new Map([...res.names].map(([p, n]) => [p, { n, page: lnG[m.speciesNames.indexOf(n)] / Math.LN10,
    pq: res.water.species.get(p)[1], z: m.act.z[m.speciesNames.indexOf(n)] }]));
  return { m, w, lg, law: w.lnAw / Math.LN10 };
}

function againstSit(engine) {
  const own = { name: 'phreeqc.dat with a SIT block', text: `${SIT_OWN}${dbText}` };
  // A saline water: the page's coefficients at PHREEQC's molalities, and its start on them.
  const salineSolution = 'SOLUTION 1\n temp 25\n units mol/kgw\n pH 7.5\n Na 1.5\n K 0.1\n Ca 0.02\n Mg 0.01\n'
    + ' Cl 1.66 charge\n C(4) 0.003\n S(6) 0.005\nEND\n';
  const saline = `${KNOBS}${salineSolution}${SIT_STEPS}`;
  engine.load(own.text);
  const res = P.waterToModel({ engine, database: own, water: { name: 'saline', text: saline }, activity: true, exact: true,
    redox: false });
  const at0 = sitAtPhreeqc(res);
  const m = at0.m;
  let worstG = 0;
  let at = '';
  for (const g of at0.lg.values()) if (Math.abs(g.page - g.pq) > worstG) { worstG = Math.abs(g.page - g.pq); at = g.n; }
  const dAw = Math.abs(at0.law - Math.log10(res.water.aw));
  check('SIT: the page\'s coefficients at PHREEQC\'s molalities are PHREEQC\'s, and so is the water\'s activity, '
    + 'PHREEQC\'s A at the water\'s own a(H2O) as the page\'s is', worstG < 1e-12 && dAw < 1e-14 && res.water.state === 'react',
  `log gamma within ${worstG.toExponential(1)} (${at}), log a(H2O) within ${dAw.toExponential(1)}, at I = `
      + `${res.water.mu.toFixed(3)}`);
  // PHREEQC's initial solution has its A at a(H2O) = 1: the coefficients apart by z^2 times A's part alone.
  engine.load(own.text);
  const ires = P.waterToModel({ engine, database: own, water: { name: 'saline', text: `${KNOBS}${salineSolution}` },
    activity: true, exact: true, redox: false });
  const ia = sitAtPhreeqc(ires);
  const sq = Math.sqrt(ia.w.I);
  const Aown = RtmModel.debyeHuckelAB(25, 1, Math.exp(ia.w.lnAw)).A;
  const A1 = RtmModel.debyeHuckelAB(25).A;
  let iApart = 0;
  let iOff = 0;
  let iAt = '';
  for (const g of ia.lg.values()) {
    const d = g.page - g.pq;
    if (Math.abs(d) > Math.abs(iApart)) { iApart = d; iAt = g.n; }
    iOff = Math.max(iOff, Math.abs(d - (g.z * g.z * -sq * (Aown - A1)) / (1 + 1.5 * sq)));
  }
  check('  against PHREEQC\'s initial solution, its A at a(H2O) = 1: apart by z^2 times A\'s part alone',
    iOff < 1e-12 && Math.abs(iApart) > 1e-9 && ires.water.state === 'i_soln',
    `${iApart.toExponential(2)} in log gamma (${iAt}), A ${Aown.toPrecision(10)} for ${A1.toPrecision(10)}; the rest `
      + `within ${iOff.toExponential(1)}`);
  /*
    At 150 C, the water on its vapour pressure, A goes a part in 1e3 as far
    as ln a(H2O): the same, and the Jacobian. PHREEQC keeps the highest
    pressure a water reaches (calc_rho_0) and takes A at the pressure its
    step starts from, the step before's; the hand-off writes the one the
    last step ended at, 7e-8 atm higher here, and A is that far apart too.
  */
  const hotSolution = salineSolution.replace('temp 25', 'temp 150');
  const hotWater = (steps) => {
    engine.load(own.text);
    return P.waterToModel({ engine, database: own, water: { name: 'saline at 150 C', text: `${KNOBS}${hotSolution}${steps}` },
      activity: true, exact: true, redox: false });
  };
  const hres = hotWater(SIT_STEPS);
  const ha = sitAtPhreeqc(hres);
  const pressureOf = (r) => Number(/^PRESSURE = (\S+)$/m.exec(r.text)[1]);
  const pEnd = pressureOf(hres);
  const pStart = pressureOf(hotWater(SIT_STEP));
  const hA = (atm) => RtmModel.debyeHuckelAB(150, atm, Math.exp(ha.w.lnAw)).A;
  const hsq = Math.sqrt(ha.w.I);
  const hD = -hsq / (1 + 1.5 * hsq);
  let hG = 0;
  let hRest = 0;
  for (const g of ha.lg.values()) {
    hG = Math.max(hG, Math.abs(g.page - g.pq));
    hRest = Math.max(hRest, Math.abs(g.page - g.pq - g.z * g.z * hD * (hA(pEnd) - hA(pStart))));
  }
  const hAw = Math.abs(ha.law - Math.log10(hres.water.aw));
  const hy = ha.m.toConcentrations(ha.m.initialState());
  let hStart = 0;
  for (const [p, n] of hres.names) hStart = Math.max(hStart, Math.abs(hy[ha.m.speciesNames.indexOf(n)] / hres.molal.get(p) - 1));
  // The Jacobian on the vapour pressure (A through the dielectric constant) and above it (through the density): at
  // PHREEQC's own pressure, a hair above the vapour pressure, a difference would straddle the corner between them.
  const hJ = ['1', '10'].map((atm) => {
    const hm = RtmModel.compile(hres.text.replace(/^PRESSURE = .*$/m, `PRESSURE = ${atm}`));
    return RtmModel.verifyJacobian(hm, 0, hm.initialState());
  });
  engine.load(own.text);
  const hi = sitAtPhreeqc(P.waterToModel({ engine, database: own, water: { name: 'saline at 150 C', text: `${KNOBS}${hotSolution}` },
    activity: true, exact: true, redox: false }));
  let hiApart = 0;
  for (const g of hi.lg.values()) if (Math.abs(g.page - g.pq) > Math.abs(hiApart)) hiApart = g.page - g.pq;
  check('  at 150 C, on the vapour pressure: the coefficients, the water\'s activity and the start PHREEQC\'s after two '
    + 'steps of nothing, A at the pressure the step started at, and the Jacobian through A\'s a(H2O), on the vapour '
    + 'pressure and above it', hRest < 1e-13
    && hAw < 1e-13 && hStart < 1e-8 && pEnd > pStart && hJ.every((v) => v.discrepancies.length === 0)
    && Math.abs(hiApart) > 1e-6,
  `log gamma within ${hG.toExponential(1)}, ${hRest.toExponential(1)} once A is taken at ${pStart} atm for ${pEnd}; `
      + `log a(H2O) ${hAw.toExponential(1)}, the start ${hStart.toExponential(1)}; ${hJ[0].checked} and ${hJ[1].checked} `
      + 'Jacobian entries at 1 and 10 atm; '
      + `PHREEQC's initial solution ${hiApart.toExponential(2)} off`);
  const y = m.toConcentrations(m.initialState());
  let worst = 0;
  for (const [p, n] of res.names) worst = Math.max(worst, Math.abs(y[m.speciesNames.indexOf(n)] / res.molal.get(p) - 1));
  const sitLines = res.text.split('\n<SIT>\n')[1].split(/\n<[A-Z_]+>/)[0].trim().split('\n');
  check('  the hand-off: ACTIVITY = sit and the database\'s coefficients between the species written, no a or b, and '
    + 'the page starts on PHREEQC\'s water', /^ACTIVITY = sit$/m.test(res.text) && sitLines.length === res.report.activity.sitPairs
    && res.report.activity.kind === 'sit' && !/^\S+\s+\S+\s+.*\ba=/m.test(res.text.split('<SPECIES>')[1].split('<EQUILIBRIUM>')[0])
    && worst < 1e-8, `${sitLines.length} pairs written; the start within ${worst.toExponential(1)}`);

  // The PHREEQC tab: salt goes in; PHREEQC's coefficients move, and the model's own stay on them.
  const saltText = `${res.text.replace('TEND = 1\n', 'TEND = 1e5\n')}=> Na+ + Cl-, k = 1e-5\n`;
  const view = P.viewRun({ engine, database: own, run: pageRun(saltText, 1e5), modelText: saltText,
    water: { name: 'saline', text: saline }, unit: 's', times: 12 });
  const gap = view.report.activity && view.report.activity.gap[0];
  check('  the PHREEQC tab, a run that adds 1 mol/kgw of salt: PHREEQC\'s coefficients move, and the model\'s own '
    + 'under SIT stay on them (PHREEQC\'s waters there initial solutions, their A at a(H2O) = 1)', !!gap
    && view.report.activity.kind === 'sit' && Math.abs(gap.by) < 1e-6
    && Math.abs(view.report.drift[0].by) > 0.05, gap ? `PHREEQC's moved ${view.report.drift[0].by.toFixed(3)} in log K, `
      + `the model's ${Math.abs(gap.by).toExponential(1)} from them (${gap.rel})` : 'no comparison');

  // An exchanger: each species on it takes its ion's coefficient, as PHREEQC's does.
  const exWater = `${KNOBS}SOLUTION 1\n units mol/kgw\n temp 25\n pH 7 charge\n Na 0.5\n K 0.1\n N(5) 0.6\n Ca 0.001\n`
    + ' Cl 0.002\nEXCHANGE 1\n -equilibrate 1\n X 0.0011\nEND\n';
  engine.load(own.text);
  const xres = P.waterToModel({ engine, database: own, water: { name: 'exchanger', text: exWater }, activity: true,
    exact: true, redox: false });
  const xm = RtmModel.compile(xres.text);
  const xy = xm.toConcentrations(xm.initialState());
  let xw = 0;
  for (const [n, v] of xres.amounts) xw = Math.max(xw, Math.abs(xy[xm.speciesNames.indexOf(n)] / v - 1));
  for (const [p, n] of xres.names) xw = Math.max(xw, Math.abs(xy[xm.speciesNames.indexOf(n)] / xres.molal.get(p) - 1));
  check('  an exchanger in a saline water: its species written without a or b, taking their ions\' SIT coefficients, '
    + 'and the page starts on PHREEQC\'s exchanger', /^CaX2\s+\S+\s+exchange$/m.test(xres.text)
    && xres.report.exchange.species.every((e) => !e.folded) && xw < 1e-7, `within ${xw.toExponential(1)}`);

  // Brine into fresh water over calcite.
  const col = sitColumn(engine, own, 40, 3);
  check('  brine (2 mol/kgw NaCl) into fresh water over calcite, against PHREEQC\'s TRANSPORT: the effluent all the way, '
    + 'and where it settles', col.pH < 0.03 && col.Ca < 1e-5 && col.Na < 0.02 && col.endPH < 1e-4 && col.endCa < 1e-4
    && col.I > 1.9, `pH within ${col.pH.toFixed(4)}, Ca ${(col.Ca * 1e3).toFixed(5)} mM, Na ${(col.Na * 1e3).toFixed(2)} mM `
      + `(of 2000) in the front; at the end pH ${col.plateau.toFixed(4)} within ${col.endPH.toExponential(1)}, Ca within `
      + `${col.endCa.toExponential(1)}; 40 cells, 3 pore volumes: PHREEQC ${col.pqMs} ms, the page ${col.rtmMs} ms`);

  // Redox under SIT: the pyrite column in a saline water, each cell speciated in its components and V's sums.
  const N = 20;
  const L = 0.1;
  const dx = L / N;
  const dt = 2000;
  const S = 30;
  const alpha = L / 40;
  const v = dx / dt;
  const pw = (n) => `SOLUTION ${n}\n temp 25\n units mmol/kgw\n pH 7.5\n Na 500\n Ca 1\n Cl 500 charge\n C(4) 3\n S(6) 0.5\n Fe 0.001\n`;
  const phases = (n) => `EQUILIBRIUM_PHASES ${n}\n Pyrite 0 5e-5\n Calcite 0 0.01\n Goethite 0 0\n`;
  const inflow = 'SOLUTION 0\n temp 25\n units mmol/kgw\n pH 7.5\n Na 500\n Ca 1\n Cl 500 charge\n C(4) 3\n S(6) 0.5\n'
    + ' O(0) 0.25\n Fe 1e-9\nEND\n';
  engine.load(own.text);
  let started = Date.now();
  const prow = engine.run(`${pw(`1-${N}`)}END\n${phases(`1-${N}`)}END\nRUN_CELLS\n -cells 1-${N}\nEND\n${inflow}`
    + 'SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings cell time pH pe S6 py\n -start\n'
    + '10 PUNCH CELL_NO, TOTAL_TIME, -LA("H+"), -LA("e-"), TOT("S(6)"), EQUI("Pyrite")\n -end\n'
    + `TRANSPORT\n -cells ${N}\n -shifts ${S}\n -time_step ${dt}\n -lengths ${dx}\n -dispersivities ${alpha}\n`
    + ` -diffusion_coefficient 0\n -flow_direction forward\n -boundary_conditions flux flux\n -punch_cells 1-${N}\n`
    + ` -punch_frequency 1\n -print_frequency ${10 * S}\nEND\n`);
  const pqMs = Date.now() - started;
  const head = prow[0].map((h) => String(h).trim());
  const pq = new Map();
  for (const row of prow.slice(1)) {
    const t = Number(row[head.indexOf('time')]);
    if (!(t > 0)) continue;
    const o = {};
    for (const key of ['pH', 'pe', 'S6', 'py']) o[key] = Number(row[head.indexOf(key)]);
    pq.set(`${Number(row[head.indexOf('cell')])}/${Math.round(t / dt)}`, o);
  }
  engine.load(own.text);
  const cres = P.waterToModel({ engine, database: own, water: { name: 'column', text: `${pw(1)}${phases(1)}END\n` },
    activity: true, exact: true, phases: true, floor: 0 });
  engine.load(own.text);
  const inRow = P.parseRows(engine.run(`${P.punchBlock()}${inflow}MIX 1\n 0 1.0\nEND\n`)).pop();
  const cb = new Map([...cres.names].map(([k, n]) => [n, k]));
  const ctext = cres.text
    .replace('MODE = batch', `MODE = transport\nCELLS = ${N}\nLENGTH = ${L}\nDIFFUSION = 1\nADVECTION = 1\n`
      + `ADVECTION_SCHEME = limited\nVELOCITY = ${v}\nPECLET = ${L / alpha}\nLEFT = robin\nRIGHT = free`)
    .replace('TEND = 1\n', `TEND = ${(S + 0.5) * dt}\n`)
    .replace(SPECIES_LINE, (line, name, gap, value, rest) => {
      if (/mineral/.test(rest) || !cb.has(name)) return line;
      const sp = inRow.species.get(cb.get(name));
      return `${line}  left=${sp ? sp[0] : 0}`;
    });
  const cm = RtmModel.compile(ctext);
  started = Date.now();
  const cr = FacsimileODE.runModel(cm, { solver: 'ndf', tend: (S + 0.5) * dt, rtol: 1e-6, atol: 1e-20, nonNegative: true,
    stagnationTol: 0.5, belowTolRun: 5, outputTimes: Array.from({ length: S }, (_, kk) => (kk + 1.5) * dt) });
  const rtmMs = Date.now() - started;
  const cns = cm.speciesNames.length;
  const rdb = P.readDatabase(own.text);
  const s6 = [];
  cm.speciesNames.forEach((n, i) => {
    if (!cb.has(n)) return;
    for (const [kk, cc] of rdb.expand(cb.get(n))) if (P.normLabel(kk) === 'S(6)') s6.push([i, cc]);
  });
  const iH = cm.speciesNames.indexOf('H+');
  const iE = cm.speciesNames.indexOf('e-');
  const iPy = cm.speciesNames.indexOf('Pyrite');
  const clnG = new Float64Array(cns);
  const cdG = new Float64Array(cns);
  const worstR = { pH: 0, pe: 0, S6: 0 };
  for (let kk = 1; kk <= S; kk++) {
    const c = cm.toConcentrations(cr.grid.y[kk - 1]);
    const b = (N - 1) * cns;
    RtmModel.activityAt(cm.act, c, b, clnG, cdG);
    const o = { pH: -(Math.log(c[b + iH]) + clnG[iH]) / Math.LN10, pe: -Math.log10(c[b + iE]),
      S6: s6.reduce((a, [i, cc]) => a + cc * c[b + i], 0) };
    const d = pq.get(`${N}/${kk}`);
    for (const key of Object.keys(worstR)) worstR[key] = Math.max(worstR[key], Math.abs(o[key] - d[key]));
  }
  const end = cm.toConcentrations(cr.grid.y[S - 1]);
  let gone = 0;
  let pqGone = 0;
  for (let cell = 0; cell < N; cell++) {
    if (!(end[cell * cns + iPy] > 0)) gone++;
    if (!(pq.get(`${cell + 1}/${S}`).py > 0)) pqGone++;
  }
  check('  the pyrite column in 0.5 mol/kgw NaCl under SIT, against PHREEQC\'s TRANSPORT: each cell speciated in its '
    + 'components and V\'s sums', worstR.pH < 0.005 && worstR.pe < 0.005 && worstR.S6 < 3e-6 && Math.abs(gone - pqGone) <= 1,
  `effluent pH within ${worstR.pH.toFixed(4)}, pe ${worstR.pe.toFixed(4)}, sulfate ${(worstR.S6 * 1e3).toFixed(5)} mM; `
    + `pyrite gone from ${gone} cells (PHREEQC ${pqGone}); PHREEQC ${pqMs} ms, the page ${rtmMs} ms`);

  // PHREEQC's own sit.dat, where this machine has it.
  const sitDat = process.env.RTM_SIT_DAT || path.join(require('os').homedir(), '.cache', 'kvotab-phreeqc', 'obj',
    'database', 'sit.dat');
  if (!fs.existsSync(sitDat)) {
    console.log(`skip  PHREEQC's sit.dat: not at ${sitDat} (set RTM_SIT_DAT)`);
    return;
  }
  const sd = { name: 'sit.dat', text: fs.readFileSync(sitDat, 'latin1') };
  const waters = [
    ['1 mol/kgw NaCl with Ca, Mg, sulfate and carbonate, 15 C', 'SOLUTION 1\n units mol/kgw\n temp 15\n pH 7.5\n Na 1.0\n'
      + ' Cl 1.0 charge\n Ca 0.01\n Mg 0.005\n S(6) 0.01\n C(4) 0.002\nEND\n'],
    ['uranium(6) carbonate in 3 mol/kgw NaCl, 25 C', 'SOLUTION 1\n units mol/kgw\n temp 25\n pH 8\n Na 3.0\n Cl 3.0 charge\n'
      + ' C(4) 0.01\n U(6) 1e-6\nEND\n'],
    ['0.5 mol/kgw NaCl at 60 C', 'SOLUTION 1\n units mol/kgw\n temp 60\n pH 7\n Na 0.5\n Cl 0.5 charge\n Ca 0.002\n C(4) 0.001\nEND\n'],
  ];
  const lines = waters.map(([label, wt]) => {
    engine.load(sd.text);
    const sres = P.waterToModel({ engine, database: sd, water: { name: label, text: `${KNOBS}${wt}${SIT_STEPS}` },
      activity: true, exact: true, redox: false });
    const sm = RtmModel.compile(sres.text);
    const n = sm.speciesNames.length;
    const sc = new Float64Array(n);
    for (const [p, nm] of sres.names) sc[sm.speciesNames.indexOf(nm)] = sres.molal.get(p);
    const g = new Float64Array(n);
    const sw = RtmModel.activityAt(sm.act, sc, 0, g, new Float64Array(n));
    let gw = 0;
    for (const [p, nm] of sres.names) gw = Math.max(gw, Math.abs(g[sm.speciesNames.indexOf(nm)] / Math.LN10 - sres.water.species.get(p)[1]));
    const sy = sm.toConcentrations(sm.initialState());
    let sw2 = 0;
    for (const [p, nm] of sres.names) sw2 = Math.max(sw2, Math.abs(sy[sm.speciesNames.indexOf(nm)] / sres.molal.get(p) - 1));
    return { label, gw, aw: Math.abs(sw.lnAw / Math.LN10 - Math.log10(sres.water.aw)), start: sw2, pairs: sres.report.activity.sitPairs };
  });
  check('PHREEQC\'s sit.dat: the coefficients and the water\'s activity at PHREEQC\'s molalities, and the hand-off\'s start, '
    + 'in three waters, each after two steps of nothing', lines.every((l) => l.gw < 1e-12 && l.aw < 1e-14 && l.start < 1e-8),
  lines.map((l) => `${l.label}: ${l.pairs} pairs, log gamma within ${l.gw.toExponential(1)}, the start within `
    + `${l.start.toExponential(1)}`).join('; '));
  const scol = sitColumn(engine, sd, 40, 3);
  check('  brine into fresh water over calcite on sit.dat, against PHREEQC\'s TRANSPORT',
    scol.pH < 0.03 && scol.Ca < 1e-5 && scol.Na < 0.02 && scol.endPH < 1e-4 && scol.endCa < 1e-4,
    `pH within ${scol.pH.toFixed(4)}, Ca ${(scol.Ca * 1e3).toFixed(5)} mM, Na ${(scol.Na * 1e3).toFixed(2)} mM in the front; `
      + `at the end pH ${scol.plateau.toFixed(4)} within ${scol.endPH.toExponential(1)}; PHREEQC ${scol.pqMs} ms, the page `
      + `${scol.rtmMs} ms`);
}

/* ======================================================================
   A gas phase: PHREEQC's GAS_PHASE

   A water with a gas phase written as a model, at a fixed pressure and in a
   fixed volume, with ideal gases (phreeqc.dat with the gases' critical
   constants and the species' molar volumes taken out, so that PHREEQC
   holds them ideal and moves no log K with pressure) and with real ones
   (phreeqc.dat as it is: Peng and Robinson's equation). Its fugacity
   coefficients against PHREEQC's own, CO2 added against PHREEQC's REACTION,
   a bubble forming, and the PHREEQC tab.
   ====================================================================== */
function againstGas(engine) {
  const ideal = { name: 'phreeqc.dat, ideal', text: dbText.split('\n').filter((l) => !/^\s*-(T_c|P_c|Omega|Vm)\b/i.test(l)).join('\n') };
  const knobs = 'KNOBS\n -convergence_tolerance 1e-12\n';
  // Reading, without PHREEQC.
  const gp = P.readGasPhases('GAS_PHASE 2\n -fixed_volume\n -volume 0.5\n CO2(g) 0.1\n N2(g)\nEND\nGAS_PHASE 3\n -pressure 2\n H2(g) 0\n');
  const g2 = gp.get('2');
  const g3 = gp.get('3');
  const db = P.readDatabase(`${dbText}`, 'GAS_BINARY_PARAMETERS\nCO2(g) N2(g) 0.05\n');
  check('a GAS_PHASE is read as PHREEQC reads one; a gas\'s critical constants and the pairs\' binary parameters, '
    + 'PHREEQC\'s own for water vapour where none is given',
  g2.fixed === 'volume' && g2.volume === 0.5 && g2.comps.length === 2 && g2.comps[0].p === 0.1 && g3.fixed === 'pressure'
    && g3.pressure === 2 && db.critical.get('CO2(g)').tc === 304.2 && db.critical.get('N2(g)').omega === 0.039
    && db.gasK('N2(g)', 'CO2(g)') === 0.05 && Math.abs(db.gasK('H2O(g)', 'CO2(g)') - 0.19) < 1e-15
    && Math.abs(db.gasK('CH4(g)', 'H2O(g)') - 0.49) < 1e-15 && db.gasK('H2(g)', 'CH4(g)') === 0,
  `CO2(g) Tc ${db.critical.get('CO2(g)').tc} K; k(H2O, CO2) ${db.gasK('H2O(g)', 'CO2(g)').toFixed(2)}`);

  const water = (fixed, opt, solutes) => `${knobs}SOLUTION 1\n units mmol/kgw\n temp 25\n pH 7 charge\n Na 10\n Cl 10\n`
    + ` ${solutes}\nGAS_PHASE 1\n -fixed_${fixed}\n ${opt}\n CO2(g) 0\n N2(g) 0\nEND\n`;
  const handOff = (dbx, w) => {
    engine.load(dbx.text);
    const res = P.waterToModel({ engine, database: dbx, water: { name: 'gassy', text: w }, activity: true, exact: true, redox: false });
    const m = RtmModel.compile(res.text);
    const y = m.toConcentrations(m.initialState());
    let worst = 0;
    for (const [pq, nm] of res.names) worst = Math.max(worst, Math.abs(y[m.speciesNames.indexOf(nm)] / res.molal.get(pq) - 1));
    for (const [nm, v] of res.amounts) worst = Math.max(worst, Math.abs(y[m.speciesNames.indexOf(nm)] / v - 1));
    return { res, m, worst };
  };
  // CO2 added: PHREEQC's REACTION, and the page's model of the water with CO2 coming in at the same rate.
  const added = (dbx, w, res, steps) => {
    engine.load(dbx.text);
    const rows = engine.run(`${w.replace('END\n', '')}REACTION 1\n CO2 1\n ${steps.map((s) => s * 1e-3).join(' ')} moles\n`
      + 'INCREMENTAL_REACTIONS false\nSELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings step pH co2g\n -start\n'
      + '10 PUNCH STEP_NO, -LA("H+"), GAS("CO2(g)")\n -end\nEND\n');
    const head = rows[0].map((h) => String(h).trim());
    const pq = rows.slice(1).filter((r) => Number(r[head.indexOf('step')]) > 0)
      .map((r) => ({ pH: Number(r[head.indexOf('pH')]), co2g: Number(r[head.indexOf('co2g')]) }));
    const k = 1e-6;
    const tEnd = steps[steps.length - 1] * 1e-3 / k;
    const text = `${res.text.replace('TEND = 1\n', `TEND = ${tEnd}\n`)}=> CO2, k = ${k}\n`;
    const m = RtmModel.compile(text);
    const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: tEnd, rtol: 1e-10, atol: 1e-22, nonNegative: true,
      outputTimes: steps.map((s) => s * 1e-3 / k) });
    const ns = m.speciesNames.length;
    const lnG = new Float64Array(ns);
    let pH = 0;
    let gas = 0;
    steps.forEach((s, i) => {
      const c = m.toConcentrations(r.grid.y[i]);
      RtmModel.activityAt(m.act, c, 0, lnG, new Float64Array(ns));
      const iH = m.speciesNames.indexOf('H+');
      pH = Math.max(pH, Math.abs(-(Math.log(c[iH]) + lnG[iH]) / Math.LN10 - pq[i].pH));
      if (pq[i].co2g > 0) gas = Math.max(gas, Math.abs(c[m.speciesNames.indexOf('CO2(g)')] / pq[i].co2g - 1));
    });
    return { pH, gas, run: r, text, m };
  };

  // At a fixed pressure: ideal at 1.1 atm, real at 10.
  const fpI = handOff(ideal, water('pressure', '-pressure 1.1', 'C(4) 40\n N(0) 1.2'));
  const fpIa = added(ideal, water('pressure', '-pressure 1.1', 'C(4) 40\n N(0) 1.2'), fpI.res, [2, 6, 10, 20]);
  check('a bubble of ideal gases at 1.1 atm: the start PHREEQC\'s, and CO2 added as PHREEQC\'s REACTION adds it',
    fpI.worst < 1e-8 && fpIa.pH < 1e-8 && fpIa.gas < 1e-6 && /^GAS_PRESSURE = 1.1$/m.test(fpI.res.text),
    `the start within ${fpI.worst.toExponential(1)}; then pH within ${fpIa.pH.toExponential(1)}, the bubble's CO2 within `
      + `${fpIa.gas.toExponential(1)}`);
  const fpR = handOff(database, water('pressure', '-pressure 10', 'C(4) 600\n N(0) 40'));
  const fpRa = added(database, water('pressure', '-pressure 10', 'C(4) 600\n N(0) 40'), fpR.res, [20, 60, 100]);
  // PHREEQC's phi at its own composition, against the page's equation there.
  engine.load(dbText);
  const pr = engine.run(`${water('pressure', '-pressure 10', 'C(4) 600\n N(0) 40').replace('END\n', '')}SELECTED_OUTPUT 99\n`
    + ' -reset false\nUSER_PUNCH 99\n -headings vm phiC phiN nC nN\n -start\n'
    + '10 PUNCH GAS_VM, PR_PHI("CO2(g)"), PR_PHI("N2(g)"), GAS("CO2(g)"), GAS("N2(g)")\n -end\nEND\n');
  const ph = pr[0].map((h) => String(h).trim());
  const prow = pr[pr.length - 1];
  const pv = (k) => Number(prow[ph.indexOf(k)]);
  const gas = fpR.m.act.gas;
  const nT = pv('nC') + pv('nN');
  const qC = gas.qOf[fpR.m.speciesNames.indexOf('CO2(g)')];
  const xs = new Float64Array(2);
  xs[qC] = pv('nC') / nT;
  xs[1 - qC] = pv('nN') / nT;
  const st = RtmModel.prState(gas.pr, xs, 10, 0);
  const dPhi = Math.max(Math.abs(gas.pr.lnPhi[qC] - Math.log(pv('phiC'))), Math.abs(gas.pr.lnPhi[1 - qC] - Math.log(pv('phiN'))));
  check('  real gases at 10 atm (Peng and Robinson): the page\'s phi and molar volume at PHREEQC\'s composition are '
    + 'PHREEQC\'s, the start PHREEQC\'s, and CO2 added as PHREEQC adds it',
  dPhi < 1e-12 && Math.abs(st.Vm / pv('vm') - 1) < 1e-12 && fpR.worst < 1e-8 && fpRa.pH < 1e-6 && fpRa.gas < 1e-5
    && /^CO2\(g\)\s+\S+\s+gas\s+Tc=304.2\s+Pc=72.86\s+omega=0.225$/m.test(fpR.res.text),
  `phi(CO2) ${pv('phiC').toFixed(10)}, within ${dPhi.toExponential(1)} in ln; the start within ${fpR.worst.toExponential(1)}; `
    + `then pH within ${fpRa.pH.toExponential(1)}, the bubble's CO2 within ${fpRa.gas.toExponential(1)} (PHREEQC's water `
    + 'losing what CO2 hydrates)');

  // In a fixed volume: the water at the gas phase's pressure, which then moves.
  const fvI = handOff(ideal, water('volume', '-volume 0.5', 'C(4) 40\n N(0) 1.2'));
  const fvIa = added(ideal, water('volume', '-volume 0.5', 'C(4) 40\n N(0) 1.2'), fvI.res, [4, 10, 20]);
  const fvR = handOff(database, water('volume', '-volume 0.2', 'C(4) 600\n N(0) 40'));
  const fvRa = added(database, water('volume', '-volume 0.2', 'C(4) 600\n N(0) 40'), fvR.res, [20, 60, 100]);
  check('a fixed volume, ideal and real: the start PHREEQC\'s, the water at the gas phase\'s pressure; with CO2 '
    + 'added, PHREEQC moves A and B with the pressure, and with the molar volumes its log K, which the run holds',
  fvI.worst < 1e-8 && fvR.worst < 1e-8 && fvIa.pH < 1e-4 && fvRa.pH < 1e-3 && /^PRESSURE = 17.23854/m.test(fvR.res.text),
  `the start within ${fvI.worst.toExponential(1)} and ${fvR.worst.toExponential(1)}; with CO2 added pH within `
    + `${fvIa.pH.toExponential(1)} (ideal, 0.76 to 1.13 atm) and ${fvRa.pH.toExponential(1)} (real, 17 to 20 atm)`);

  // A bubble forming: the water held at 1 atm and below it to start with, CO2 added a millimole at a time.
  const under = water('pressure', '-pressure 1', 'C(4) 20\n N(0) 0.4');
  const bf = handOff(ideal, under);
  const steps = Array.from({ length: 25 }, (_, i) => i + 1);
  engine.load(ideal.text);
  const rows = engine.run(`${under.replace('END\n', '')}REACTION 1\n CO2 1\n ${steps.map((s) => s * 1e-3).join(' ')} moles\n`
    + 'INCREMENTAL_REACTIONS false\nSELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings step g\n -start\n'
    + '10 PUNCH STEP_NO, GAS("CO2(g)") + GAS("N2(g)")\n -end\nEND\n');
  const head = rows[0].map((h) => String(h).trim());
  // PHREEQC keeps 1e-25 mol of a gas phase that is not there: a bubble is more than that.
  const first = rows.slice(1).find((r) => Number(r[head.indexOf('step')]) > 0 && Number(r[head.indexOf('g')]) > 1e-20);
  const firstStep = first ? Number(first[head.indexOf('step')]) : -1;
  const ba = added(ideal, under, bf.res, steps);
  const formed = ba.run.events.find((e) => /a bubble forms/.test(e.expr));
  const formedAt = formed ? formed.t * 1e-6 * 1e3 : -1;
  check('  a bubble forming as CO2 comes in: the page\'s event between PHREEQC\'s last step with no gas phase and its '
    + 'first with one, and the waters the same either side (to 1e-7 in pH: PHREEQC\'s water loses what CO2 hydrates, '
    + 'the page\'s kilogram does not)', bf.res.report.gas && bf.res.report.gas.species
    .every((g) => g.amount === 0) && formedAt > firstStep - 1 && formedAt < firstStep && ba.pH < 1e-7,
  `PHREEQC first has a bubble at +${firstStep} mmol, the page forms one at +${formedAt.toFixed(4)}; pH within ${ba.pH.toExponential(1)}`);

  // The PHREEQC tab on a run with a bubble: the run's partial pressures, the pressures the waters hold the gases at.
  const reply = pageRun(fpIa.text, 2e4);
  engine.load(ideal.text);
  const view = P.viewRun({ engine, database: ideal, run: reply, modelText: fpIa.text,
    water: { name: 'gassy', text: water('pressure', '-pressure 1.1', 'C(4) 40\n N(0) 1.2') }, unit: 's', times: 12 });
  const vg = view.report.gas;
  check('  the PHREEQC tab: each gas\'s partial pressure in the run is the pressure PHREEQC finds the water holds it at',
    !!vg && vg.compared > 0 && Math.abs(vg.gap) < 1e-6 && view.report.skipped.some((s) => s.name === 'CO2(g)' && /a gas/.test(s.why)),
    vg ? `within ${Math.abs(vg.gap).toExponential(1)} in log over ${vg.compared} pressures` : 'no comparison');
}

/* ======================================================================
   The temperature: each reaction's log K as PHREEQC has it at any, a
   heated batch, and a column with a temperature profile

   Every reaction of phreeqc.dat -- species, phases, exchange and surface
   species -- its log K from the database's terms (log_k, delta_h with its
   unit, -analytic, named expressions) as the page reads them, against
   PHREEQC's LK_SPECIES and LK_PHASE at six temperatures. Calcite and gypsum
   heated from 25 to 90 C along a table read at the clock, against PHREEQC's
   REACTION_TEMPERATURE: the water and the minerals at every step, and
   gypsum going over to anhydrite at the temperature PHREEQC's saturation
   index of anhydrite crosses zero, found by bisection. A column whose cells
   are held at 10 to 70 C, acid water in over calcite, against TRANSPORT with
   its cells' temperatures held (-thermal_diffusion 1e30 0): the effluent
   through the run, and the end, where each cell is the inflow at calcite
   saturation at its own temperature in both.
   ====================================================================== */
function againstTemperature(engine) {
  engine.load(dbText);
  const db = P.readDatabase(dbText);
  // Every reaction, at six temperatures; the BASIC program a hundred and fifty reads at a time.
  const items = [...db.lk.keys()].map((key) => {
    const cut = key.indexOf(' ');
    const kind = key.slice(0, cut);
    return { kind, name: key.slice(cut + 1), fn: kind === 'p' ? 'LK_PHASE' : 'LK_SPECIES' };
  });
  let lkWorst = 0;
  let lkAt = '';
  let compared = 0;
  for (const T of [0.01, 10, 25, 50, 75, 90]) {
    for (let c = 0; c < items.length; c += 150) {
      const part = items.slice(c, c + 150);
      const rows = P.parseRows(engine.run(`${P.punchBlock(part.map((it) => `STR_E$(${it.fn}("${it.name}"), 23, 15)`))}`
        + `SOLUTION 1\n temp ${T}\n pH 7\n Na 1\n Cl 1\nEND\n`));
      const r = rows[rows.length - 1];
      part.forEach((it, i) => {
        const d = Math.abs(P.kCalc(db.logKTerms(it.kind, it.name), T + 273.15) - Number(r.x[i]));
        compared++;
        if (!(d <= lkWorst)) { lkWorst = d; lkAt = `${it.name} at ${T} C`; }
      });
    }
  }
  const named = P.readDatabase('NAMED_EXPRESSIONS\nLog_K_A\n -log_k 2\n -delta_h -10 kcal\nLog_K_B\n -analytic 1 0 -300\n'
    + ' -add_logk Log_K_A 0.5\nSOLUTION_SPECIES\nA+ = A+\n log_k 0\nA+ + B- = AB\n -l 1.5\n -d 4184 joules\n'
    + ' -add_logk Log_K_B 2\n -add_constant 0.25\n');
  const tAB = named.logKTerms('s', 'AB');
  const wantAB = [1.5 + 0.25, 4.184, 2, 0, -600, 0, 0, 0];
  check('each reaction\'s log K at a temperature from the database\'s terms: every one of phreeqc.dat against PHREEQC\'s '
    + 'LK_SPECIES and LK_PHASE at 0 to 90 C; units, abbreviations and named expressions as PHREEQC reads them',
  compared > 2000 && lkWorst < 1e-12 && tAB.every((v, k) => Math.abs(v - wantAB[k]) < 1e-12),
  `${compared} log K, worst ${lkWorst.toExponential(1)} (${lkAt}); AB ${JSON.stringify(tAB)}`);

  // --- calcite and gypsum heated from 25 to 90 C ---------------------------
  const sol = 'SOLUTION 1\n temp 25\n units mmol/kgw\n pH 7 charge\n Na 1\n Cl 1\nEQUILIBRIUM_PHASES 1\n Calcite 0 0.01\n'
    + ' Gypsum 0 0.02\n Anhydrite 0 0\n';
  const res = P.waterToModel({ engine, database, water: { name: 'heated', text: `${sol}END\n` }, phases: true, exact: true,
    activity: true, redox: false });
  const text = res.text.replace(/^TEMPERATURE = 25$/m, 'TEMPERATURE = heat(t)')
    .replace('<SPECIES>', '<TABLE heat>\n0 25\n1 90\n\n<SPECIES>').replace(/^EQUILIBRATE = .*$/m, 'EQUILIBRATE = always');
  const m = RtmModel.compile(text);
  const steps = 14;
  const want = Array.from({ length: steps }, (_, k) => k / (steps - 1));
  const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: 1, rtol: 1e-10, atol: 1e-20, outputTimes: want });
  const pqRows = P.parseRows(engine.run(`${P.punchBlock(['STR_E$(EQUI("Calcite"), 23, 15)', 'STR_E$(EQUI("Gypsum"), 23, 15)',
    'STR_E$(EQUI("Anhydrite"), 23, 15)', 'STR_E$(TOT("Ca"), 23, 15)', 'STR_E$(TOT("water"), 23, 15)'])}${sol}`
    + `REACTION_TEMPERATURE 1\n 25 90 in ${steps} steps\nEND\n`)).filter((w) => w.state === 'react');
  const idx = (n) => m.speciesNames.indexOf(n);
  const caSp = [...res.names].filter(([sp]) => db.expand(sp).has('Ca')).map(([sp, n]) => [idx(n), db.expand(sp).get('Ca')]);
  const iH = idx(res.names.get('H+'));
  let wH = 0;
  let wCa = 0;
  let wMin = 0;
  let after = { H: 0, Ca: 0, min: 0 };
  for (let k = 0; k < steps; k++) {
    const w = pqRows[k];
    const c = m.toConcentrations(r.grid.y[k], r.grid.t[k]);
    const kgw = Number(w.x[4]);
    const dH = Math.abs(Math.log10(c[iH] / w.mH));
    const dCa = Math.abs(caSp.reduce((s, [i, n]) => s + n * c[i], 0) / Number(w.x[3]) - 1);
    const dMin = Math.max(...['Calcite', 'Gypsum', 'Anhydrite'].map((n, j) => Math.abs(c[idx(n)] - Number(w.x[j]) / kgw)));
    // Past the change PHREEQC's kilogram of water has grown by gypsum's water of hydration; the page holds 1 kg.
    if (Number(w.x[2]) > 0) after = { H: Math.max(after.H, dH), Ca: Math.max(after.Ca, dCa), min: Math.max(after.min, dMin) };
    else { wH = Math.max(wH, dH); wCa = Math.max(wCa, dCa); wMin = Math.max(wMin, dMin); }
  }
  const siAnh = (T) => {
    const rows = P.parseRows(engine.run(`${P.punchBlock(['STR_E$(SI("Anhydrite"), 23, 15)'])}`
      + `${sol.replace(' Anhydrite 0 0\n', '')}REACTION_TEMPERATURE 1\n ${T}\nEND\n`)).filter((w) => w.state === 'react');
    return Number(rows[rows.length - 1].x[0]);
  };
  let lo = 50;
  let hi = 60;
  for (let i = 0; i < 40; i++) { const mid = (lo + hi) / 2; if (siAnh(mid) < 0) lo = mid; else hi = mid; }
  const ev = r.events.find((e) => /Anhydrite precipitates/.test(e.expr));
  const tEv = ev ? 25 + 65 * ev.t : NaN;
  check('calcite and gypsum heated from 25 to 90 C, TEMPERATURE a table read at the clock, against PHREEQC\'s '
    + 'REACTION_TEMPERATURE: the water and the minerals at every step, and gypsum going over to anhydrite at PHREEQC\'s '
    + 'temperature', pqRows.length === steps && wH < 1e-7 && wCa < 5e-7 && wMin < 1e-6 && after.H < 1e-6 && after.Ca < 1e-5
    && after.min < 1e-5 && r.events.length === 1 && /and Gypsum has dissolved away/.test(ev.expr)
    && Math.abs(tEv - (lo + hi) / 2) < 1e-6,
  `gypsum: log m(H+) ${wH.toExponential(1)}, Ca ${wCa.toExponential(1)}, minerals ${wMin.toExponential(1)} mol/kgw; `
    + `anhydrite, PHREEQC's water ${((Number(pqRows[steps - 1].x[4]) / Number(pqRows[0].x[4]) - 1) * 1e6).toFixed(0)} ppm `
    + `heavier: ${after.H.toExponential(1)}, ${after.Ca.toExponential(1)}, ${after.min.toExponential(1)}; at `
    + `${tEv.toFixed(7)} C for PHREEQC's ${((lo + hi) / 2).toFixed(7)}`);

  // --- a column held at 10 to 70 C ------------------------------------------
  const N = 20;
  const L = 0.1;
  const dx = L / N;
  const dt = 1000;
  const S = 4 * N;
  const alpha = L / 40;
  const Tof = (i) => 10 + (60 * i) / (N - 1);
  const water = (n, T) => `SOLUTION ${n}\n temp ${T}\n units mmol/kgw\n pH 7 charge\n Na 2\n Ca 1\n Cl 2\n C(4) 3\n`;
  const acid = 'SOLUTION 0\n temp 25\n units mmol/kgw\n pH 6 charge\n Na 2\n Ca 2\n Cl 4\n C(4) 3\nEND\n';
  let sols = '';
  for (let i = 0; i < N; i++) sols += water(i + 1, Tof(i));
  // A clean PHREEQC: TRANSPORT would apply the REACTION_TEMPERATURE 1 above to cell 1.
  engine.load(dbText);
  const rows = engine.run(`${sols}END\nEQUILIBRIUM_PHASES 1-${N}\n Calcite 0 0.1\nEND\nRUN_CELLS\n -cells 1-${N}\nEND\n${acid}`
    + 'SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings cell time pH Ca tc\n -start\n'
    + '10 PUNCH CELL_NO, TOTAL_TIME, STR_E$(-LA("H+"), 23, 15), STR_E$(TOT("Ca"), 23, 15), TC\n -end\n'
    + `TRANSPORT\n -cells ${N}\n -shifts ${S}\n -time_step ${dt}\n -lengths ${dx}\n -dispersivities ${alpha}\n`
    + ` -diffusion_coefficient 0\n -flow_direction forward\n -boundary_conditions flux flux\n -punch_cells 1-${N}\n`
    + ` -punch_frequency 1\n -print_frequency ${10 * S}\n -thermal_diffusion 1e30 0\nEND\n`);
  const head = rows[0].map((h) => String(h).trim());
  const pq = new Map();
  let held = 0;
  for (const row of rows.slice(1)) {
    const t = Number(row[head.indexOf('time')]);
    if (!(t > 0)) continue;
    const cell = Number(row[head.indexOf('cell')]);
    held = Math.max(held, Math.abs(Number(row[head.indexOf('tc')]) - Tof(cell - 1)));
    pq.set(`${cell}/${Math.round(t / dt)}`, { pH: Number(row[head.indexOf('pH')]), Ca: Number(row[head.indexOf('Ca')]) });
  }
  const col = P.waterToModel({ engine, database, water: { name: 'column', text: `${water(1, Tof(0))}EQUILIBRIUM_PHASES 1\n Calcite 0 0.1\nEND\n` },
    activity: true, exact: true, phases: true, redox: false });
  const inflow = P.parseRows(engine.run(`${P.punchBlock()}${acid}`)).pop();
  const back = new Map([...col.names].map(([k, n]) => [n, k]));
  const ctext = col.text
    .replace('MODE = batch', `MODE = transport\nCELLS = ${N}\nLENGTH = ${L}\nDIFFUSION = 1\nADVECTION = 1\n`
      + `ADVECTION_SCHEME = limited\nVELOCITY = ${dx / dt}\nPECLET = ${L / alpha}\nLEFT = robin\nRIGHT = free`)
    .replace(/^TEMPERATURE = .*$/m, 'TEMPERATURE = Tc')
    .replace('<SPECIES>', `<PARAMETERS>\nTc all 10 + 60*i/${N - 1}\n\n<SPECIES>`)
    .replace('TEND = 1\n', `TEND = ${(S + 0.5) * dt}\n`)
    .replace(SPECIES_LINE, (line, name, gap, value, rest) => {
      if (/mineral/.test(rest) || !back.has(name)) return line;
      const sp = inflow.species.get(back.get(name));
      return `${line}  left=${sp ? sp[0] : 0}`;
    });
  const cm = RtmModel.compile(ctext);
  const times = Array.from({ length: S }, (_, k) => (k + 1.5) * dt);
  const cr = FacsimileODE.runModel(cm, { solver: 'ndf', tend: (S + 0.5) * dt, rtol: 1e-8, atol: 1e-20, nonNegative: true,
    outputTimes: times });
  const ns = cm.speciesNames.length;
  const caOf = [];
  cm.speciesNames.forEach((n, i) => { if (back.has(n) && db.expand(back.get(n)).has('Ca')) caOf.push([i, db.expand(back.get(n)).get('Ca')]); });
  const ciH = cm.speciesNames.indexOf('H+');
  const lnG = new Float64Array(ns);
  const dG = new Float64Array(ns);
  const at = (c, cell) => {
    let Ca = 0;
    for (const [i, k] of caOf) Ca += k * c[cell * ns + i];
    RtmModel.activityAt(cm.act, c, cell * ns, lnG, dG, cell);
    return { Ca, pH: -(Math.log(c[cell * ns + ciH]) + lnG[ciH]) / Math.LN10 };
  };
  let effpH = 0;
  let effCa = 0;
  for (let k = 1; k <= S; k++) {
    const o = at(cm.toConcentrations(cr.grid.y[k - 1], times[k - 1]), N - 1);
    const d = pq.get(`${N}/${k}`);
    effpH = Math.max(effpH, Math.abs(o.pH - d.pH));
    effCa = Math.max(effCa, Math.abs(o.Ca - d.Ca));
  }
  const end = cm.toConcentrations(cr.grid.y[S - 1], times[S - 1]);
  let endpH = 0;
  let endCa = 0;
  for (let cell = 0; cell < N; cell++) {
    const o = at(end, cell);
    const d = pq.get(`${cell + 1}/${S}`);
    endpH = Math.max(endpH, Math.abs(o.pH - d.pH));
    endCa = Math.max(endCa, Math.abs(o.Ca / d.Ca - 1));
  }
  const tc = cm.temperatures(0);
  check('a column held at 10 to 70 C, TEMPERATURE a parameter, acid water in over calcite, against TRANSPORT with its '
    + 'cells\' temperatures held: the effluent through the run, and each cell at the end the inflow at calcite saturation at '
    + 'its own temperature', held === 0 && Math.abs(tc[0] - 10) < 1e-12 && Math.abs(tc[N - 1] - 70) < 1e-12
    && effpH < 0.01 && effCa < 3e-5 && endpH < 2e-5 && endCa < 3e-5,
  `effluent pH within ${effpH.toFixed(4)}, Ca within ${(effCa * 1e3).toFixed(4)} mM; at the end pH within `
    + `${endpH.toExponential(1)} and Ca ${endCa.toExponential(1)} in every cell, PHREEQC's water heavier by what `
    + 'calcite and CO2 take of it');
}

/* ======================================================================
   Solid solutions: PHREEQC's SOLID_SOLUTIONS

   Aragonite and strontianite, phreeqc.dat's, in a water that holds them
   at saturation: the solid solution ideal, and binary in each of the ten
   forms PHREEQC takes Guggenheim's parameters in, from its tenth example's
   a0 = 3.43 and a1 = -1.82 or near them, inside the miscibility gap and
   either side of it; given at another temperature, by -tempc (PHREEQC adds
   298.15) and -tempk, and in a water at 50 C. Each written as a model, the
   start against PHREEQC's. Strontianite added as PHREEQC's REACTION adds
   it, the solid's composition through the gap, where it comes to it and
   leaves it found by bisection on PHREEQC's; and the PHREEQC tab.
   ====================================================================== */
function againstSolidSolutions(engine) {
  // Reading, without PHREEQC.
  const read = P.readSolidSolutions('SOLID_SOLUTIONS 1\nCa(x)Sr(1-x)CO3\n -comp1 Aragonite 0\n -comp2 Strontianite 0.1\n'
    + ' -Gugg_nondim 3.43 -1.82\n -tempc 25\nIdeal\n -comp Calcite 0\n -comp Otavite 0\n -comp Rhodochrosite 0\nEND\n');
  const s1 = read.get('1');
  check('a SOLID_SOLUTIONS is read as PHREEQC reads one: -comp1 and -comp2 first, the options by its prefix rule, '
    + '-tempc as degrees above 25 C, as PHREEQC adds 298.15 to them',
  !!s1 && s1.length === 2 && s1[0].name === 'Ca(x)Sr(1-x)CO3' && s1[0].comps.map((c) => c.name).join() === 'Aragonite,Strontianite'
    && s1[0].comps[1].moles === 0.1 && s1[0].input === 'a0a1' && s1[0].p[0] === 3.43 && s1[0].p[1] === -1.82
    && Math.abs(s1[0].tk - 323.15) < 1e-12 && s1[1].comps.length === 3 && !s1[1].input,
  s1 ? `${s1.map((ss) => `${ss.name}: ${ss.comps.map((c) => c.name).join(', ')}`).join('; ')}; tk ${s1[0].tk}` : 'nothing read');

  const water = (temp, sr, ss, ca = 3, c = 7) => `SOLUTION 1\n units mmol/kgw\n temp ${temp}\n pH 7.2 charge\n Ca ${ca}\n C ${c}\n Sr ${sr}\n`
    + ` Na 1\n Cl 1\nSOLID_SOLUTIONS 1\nCa(x)Sr(1-x)CO3\n -comp1 Aragonite 0\n -comp2 Strontianite 0\n${ss}END\n`;
  const handOff = (w) => {
    engine.load(dbText);
    const res = P.waterToModel({ engine, database, water: { name: 'carbonates', text: w }, activity: true, exact: true, redox: false });
    const m = RtmModel.compile(res.text);
    const y = m.toConcentrations(m.initialState());
    let worst = 0;
    for (const [pq, nm] of res.names) {
      const want = res.molal.get(pq);
      if (want > 0) worst = Math.max(worst, Math.abs(y[m.speciesNames.indexOf(nm)] / want - 1));
    }
    for (const [nm, v] of res.amounts) if (v > 0) worst = Math.max(worst, Math.abs(y[m.speciesNames.indexOf(nm)] / v - 1));
    const am = y[m.speciesNames.indexOf('Aragonite')];
    const st = y[m.speciesNames.indexOf('Strontianite')];
    return { res, m, worst, xSr: st / (am + st) };
  };
  const forms = [
    ['ideal', ''],
    ['-Gugg_nondimensional', ' -Gugg_nondimensional 3.43 -1.82\n'],
    ['-Gugg_kJ', ' -Gugg_kJ 8.5 -4.5\n'],
    ['-activity_coefficients', ' -activity_coefficients 134.6 5.4 0.02 0.98\n'],
    ['-distribution_coefficients', ' -distribution_coefficients 0.2397 57.96 0.1 0.9\n'],
    ['-miscibility_gap', ' -miscibility_gap 0.0048 0.858\n'],
    ['-spinodal_gap', ' -spinodal_gap 0.0654 0.62\n'],
    ['-critical_point', ' -critical_point 0.3 702\n'],
    ['-alyotropic_point', ' -alyotropic_point 0.199 -8.212\n'],
    ['-Thompson', ' -Thompson 5 12\n'],
    ['-Margules', ' -Margules 2.0 0.5\n'],
  ];
  const starts = forms.map(([label, ss]) => ({ label, ...handOff(water(25, 0.5, ss)) }))
    .concat([['below the gap', 0.02, 3, 7], ['above it', 10, 1, 13]].map(([label, sr, ca, c]) => ({ label,
      ...handOff(water(25, sr, ' -Gugg_nondimensional 3.43 -1.82\n', ca, c)) })));
  const prm = (h) => (h.res.report.solids[0].binary ? `a0 ${h.res.report.solids[0].binary.a0.toFixed(4)}` : 'ideal');
  check('the solid solution written as a model starts on PHREEQC\'s water and solid, ideal and in each of the ten '
    + 'forms PHREEQC takes Guggenheim\'s parameters in', starts.every((h) => h.worst < 1e-9 && h.res.report.solids.length === 1),
  starts.map((h) => `${h.label} ${h.worst.toExponential(1)} (${prm(h)}, x_Sr ${h.xSr.toFixed(4)})`).join('; '));
  const gapAt = RtmModel.binaryAt(starts[1].m.equilibria.find((eq) => eq.grp).grp, 298.15).gap;
  const sides = starts.slice(-2).map((h) => h.xSr);
  check('  the binary one below its miscibility gap, inside it and above it, as PHREEQC has it',
    sides[0] < gapAt.xb1 && starts[1].xSr > gapAt.xb1 && starts[1].xSr < gapAt.xb2 && sides[1] > gapAt.xb2
    && /^Ca\(x\)Sr\(1-x\)CO3\s+Aragonite\s+Strontianite\s+a0=3.43\s+a1=-1.82$/m.test(starts[1].res.text),
  `x_Sr ${sides[0].toFixed(6)}, ${starts[1].xSr.toFixed(6)} and ${sides[1].toFixed(6)}, the gap ${gapAt.xb1.toFixed(6)} to `
    + `${gapAt.xb2.toFixed(6)}`);

  // At another temperature: -tempc (PHREEQC's 298.15 more), -tempk, and the water at 50 C.
  const temps = [['-tempc 25', water(25, 0.5, ' -Gugg_nondimensional 3.43 -1.82\n -tempc 25\n'), /tc=50\b/],
    ['-tempk 310', water(25, 0.5, ' -Gugg_nondimensional 3.43 -1.82\n -tempk 310\n'), /tc=36.85\b/],
    ['the water at 50 C', water(50, 0.5, ' -Gugg_nondimensional 3.43 -1.82\n'), /TEMPERATURE = 50/]]
    .map(([label, w, re]) => ({ label, re, ...handOff(w) }));
  check('  given at another temperature, by -tempc and -tempk, and in a water at 50 C: a0 and a1 there as PHREEQC has '
    + 'them, and the start PHREEQC\'s', temps.every((h) => h.worst < 1e-9 && h.re.test(h.res.text)),
  temps.map((h) => `${h.label} ${h.worst.toExponential(1)} (${prm(h)})`).join('; '));

  /*
    Strontianite added: PHREEQC's REACTION, 0.2 mmol at a time, and the
    page's model of the water with SrCO3 coming in at the same rate. The
    solid's composition through the gap: where it comes to it and leaves
    it, PHREEQC's found by bisection on the amount added.
  */
  const sol = 'SOLUTION 1\n units mmol/kgw\n pH 7.2 charge\n Ca 3\n C 7\n Sr 0.001\n Na 1\n Cl 1\n';
  const ssBlock = (p) => `SOLID_SOLUTIONS 1\nCa(x)Sr(1-x)CO3\n -comp1 Aragonite 0\n -comp2 Strontianite 0\n${p}`;
  const extras = ['STR_E$(S_S("Aragonite"), 23, 15)', 'STR_E$(S_S("Strontianite"), 23, 15)', 'STR_E$(-LA("H+"), 23, 15)',
    'STR_E$(TOT("Sr"), 23, 15)'];
  const pqAt = (p, amounts) => {
    engine.load(dbText);
    return P.parseRows(engine.run(`${P.punchBlock(extras)}${sol}${ssBlock(p)}REACTION 1\n SrCO3 1.0\n `
      + `${amounts.map((a) => String(a)).join(' ')} moles\nINCREMENTAL_REACTIONS false\nEND\n`)).filter((w) => w.state === 'react')
      .map((w) => { const a = Number(w.x[0]); const b = Number(w.x[1]); return { x: a + b > 0 ? b / (a + b) : 0, pH: Number(w.x[2]), sr: Number(w.x[3]) }; });
  };
  const dn = 2e-4;
  const steps = Array.from({ length: 30 }, (_, k) => (k + 1) * dn);
  const rate = 1e-6;
  const added = ['', ' -Gugg_nondimensional 3.43 -1.82\n'].map((p) => {
    const pq = pqAt(p, steps);
    const res = handOff(`${sol}${ssBlock(p)}END\n`).res;
    const text = res.text.replace('TEND = 1\n', `TEND = ${steps[29] / rate}\n`) + `=> Sr+2 + CO3-2, k = ${rate}\n`;
    const m = RtmModel.compile(text);
    const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: steps[29] / rate, rtol: 1e-10, atol: 1e-20,
      outputTimes: steps.map((a) => a / rate) });
    const ns = m.speciesNames.length;
    const am = m.speciesNames.indexOf('Aragonite');
    const st = m.speciesNames.indexOf('Strontianite');
    const iH = m.speciesNames.indexOf('H+');
    const lnG = new Float64Array(ns);
    let x = 0;
    let pH = 0;
    steps.forEach((a, k) => {
      const c = m.toConcentrations(r.grid.y[k], a / rate);
      RtmModel.activityAt(m.act, c, 0, lnG, new Float64Array(ns), 0);
      x = Math.max(x, Math.abs(c[st] / (c[am] + c[st]) - pq[k].x));
      pH = Math.max(pH, Math.abs(-(Math.log(c[iH]) + lnG[iH]) / Math.LN10 - pq[k].pH));
    });
    return { p, x, pH, r, m, text, events: r.events.map((e) => ({ at: e.t * rate, expr: e.expr })) };
  });
  // PHREEQC's amount added where its solid's composition crosses an edge of the gap, by bisection.
  const cross = (edge, lo0, hi0) => {
    let lo = lo0;
    let hi = hi0;
    for (let i = 0; i < 40; i++) {
      const mid = (lo + hi) / 2;
      if (pqAt(' -Gugg_nondimensional 3.43 -1.82\n', [mid])[0].x < edge) lo = mid; else hi = mid;
    }
    return (lo + hi) / 2;
  };
  const bin = added[1];
  const into = bin.events.find((e) => /comes to its miscibility gap/.test(e.expr));
  const out = bin.events.find((e) => /leaves its miscibility gap/.test(e.expr));
  const pqIn = into ? cross(gapAt.xb1, into.at * 0.9, into.at * 1.1) : NaN;
  const pqOut = out ? cross(gapAt.xb2, out.at * 0.9, out.at * 1.1) : NaN;
  check('strontianite added as PHREEQC\'s REACTION adds it: the solid\'s composition and the pH PHREEQC\'s, ideal and '
    + 'binary, and the binary one coming to its miscibility gap and leaving it where PHREEQC\'s does',
  added.every((a) => a.x < 5e-6 && a.pH < 5e-6) && added[0].events.length === 0 && bin.events.length === 2
    && Math.abs(into.at / pqIn - 1) < 5e-5 && Math.abs(out.at / pqOut - 1) < 5e-5,
  `x_Sr within ${added.map((a) => a.x.toExponential(1)).join(' and ')}, pH within ${added.map((a) => a.pH.toExponential(1))
    .join(' and ')} (PHREEQC's water growing by what bicarbonate gives up as it goes to CO2); into the gap at `
    + `${into ? (into.at * 1e3).toFixed(8) : '-'} mmol for PHREEQC's ${(pqIn * 1e3).toFixed(8)}, out at `
    + `${out ? (out.at * 1e3).toFixed(8) : '-'} for ${(pqOut * 1e3).toFixed(8)}`);

  // The PHREEQC tab on the binary run: each member's activity in the run, PHREEQC's 10^SI of the pure member.
  const reply = pageRun(bin.text, steps[29] / rate);
  engine.load(dbText);
  const view = P.viewRun({ engine, database, run: reply, modelText: bin.text,
    water: { name: 'carbonates', text: `${sol}END\n` }, unit: 's', times: 12 });
  const vs = view.report.solids && view.report.solids[0];
  check('  the PHREEQC tab: each member\'s activity in the run, x lambda or the gap\'s edge\'s, is the one PHREEQC finds the '
    + 'water holds the pure member at, and the members are not looked at as pure minerals',
  !!vs && vs.compared > 0 && Math.abs(vs.gap) < 1e-6 && vs.binary
    && !(view.report.minerals || []).some((mn) => /Aragonite|Strontianite/.test(mn.name)),
  vs ? `within ${Math.abs(vs.gap).toExponential(1)} in log over ${vs.compared} activities (${vs.worst})` : 'no comparison');
}

/* ======================================================================
   Pitzer: PHREEQC's PITZER

   Always on phreeqc.dat with a PITZER block of the tests' own in front of
   it, round numbers, every type of parameter and terms in the temperature;
   and on PHREEQC's own pitzer.dat where it is on this machine
   (~/.cache/kvotab-phreeqc/obj/database/pitzer.dat from the PHREEQC build,
   or RTM_PITZER_DAT), skipped otherwise: no Pitzer database comes with the
   page. The page's coefficients and water at PHREEQC's molalities, the
   hand-off and its start, the electron PHREEQC's Pitzer model holds, the
   PHREEQC tab; and on pitzer.dat seawater, a hot brine over gypsum, NaCl
   added to a water over anhydrite until halite forms, against REACTION,
   and brine through a column, against TRANSPORT.
   ====================================================================== */
const PITZER_OWN = (opts = '') => `PITZER
-B0
  Na+    Cl-     0.08  -700  -4  0.009  -3e-6
  K+     Cl-     0.05  0  0  5e-4
  Ca+2   Cl-     0.3   0  0  -3e-4  1.4e-7
  Mg+2   Cl-     0.35  0  0  -2e-4  2e-6
  Na+    SO4-2   0.02  0  0  2e-3
  Ca+2   SO4-2   0.2
  Na+    HCO3-   0.03
-B1
  Na+    Cl-     0.27  0  0  6e-5  1e-6
  K+     Cl-     0.21  0  0  1e-3
  Ca+2   Cl-     1.6   0  0  7.6e-3  -8e-7
  Mg+2   Cl-     1.7   0  0  3.7e-3
  Na+    SO4-2   1.1   0  0  5.6e-3
  Ca+2   SO4-2   3.2   0  0  5e-2
-B2
  Ca+2   SO4-2   -54   0  0  -0.5
-C0
  Na+    Cl-     0.001   30  0.09  -5e-5
  K+     Cl-     -0.0008  0  0  -5e-5
  Ca+2   Cl-     -0.0003
  Mg+2   Cl-     0.005  0  0  -1.6e-4
  Na+    SO4-2   0.005  0  0  -1.2e-4
-THETA
  K+     Na+     -0.01
  Ca+2   Na+     0.07
  Mg+2   Na+     0.07
  Cl-    SO4-2   0.03
-LAMDA
  CO2    Na+     0.1
  CO2    Cl-     -0.005
  CO2    CO2     0.02
  CaSO4  Na+     0.05
-ZETA
  CO2    Na+     Cl-     -0.003
-PSI
  K+     Na+     Cl-     -0.002
  Ca+2   Na+     Cl-     -0.007
  Mg+2   Na+     Cl-     -0.012
  Cl-    SO4-2   Na+     0.0014
-MU
  CO2    CO2     Na+     -0.001
  CO2    CO2     CO2     0.0005
-ETA
  CO2    Ca+2    Na+     0.002
-ALPHAS
  Ca+2   SO4-2   1.4  12
${opts}`;

function againstPitzer(engine) {
  // Reading, without PHREEQC: the options by PHREEQC's prefix rule, a parameter given again replaces it.
  const rd = P.readDatabase('PITZER\n -mac false\n -use_e false\n -redox\n -B0\n  Na+ Cl- 0.1 1\n -b0\n  Cl- Na+ 0.2\n'
    + ' -lambda\n  CO2 Na+ 0.1\n -Aphi\n  0.39 -10\nEND\n');
  const b0 = rd.pitzer.get('B0 Cl- Na+');
  check('Pitzer: a PITZER block is read as PHREEQC reads one: its options by the prefix rule, true unless they say f..., '
    + 'and a parameter given again, either way round, replacing the first',
  rd.model === 'Pitzer' && rd.pitzer.size === 2 && !!b0 && b0.a.length === 1 && b0.a[0] === 0.2 && b0.sp[0] === 'Cl-'
    && rd.pitzer.has('LAMBDA CO2 Na+') && !rd.pitzerOpts.macinnes && !rd.pitzerOpts.etheta && rd.pitzerOpts.redox
    && rd.aphi.join() === '0.39,-10', `${[...rd.pitzer.keys()].join(', ')}; ${JSON.stringify(rd.pitzerOpts)}`);

  // The page's coefficients at PHREEQC's molalities, and its start on them, on phreeqc.dat with the block.
  const saline = (tc) => `${KNOBS}SOLUTION 1\n temp ${tc}\n units mol/kgw\n pH 7\n Na 3\n K 0.2\n Ca 0.1\n Mg 0.2\n`
    + ' Cl 3.7 charge\n S(6) 0.05\n C(4) 0.02\nEND\n';
  const handOff = (db, water, label, redox = false, edit = (t) => t) => {
    engine.load(db.text);
    const res = P.waterToModel({ engine, database: db, water: { name: label, text: water }, activity: true, exact: true,
      redox, floor: 1e-30 });
    const m = RtmModel.compile(edit(res.text));
    const ns = m.speciesNames.length;
    const C = new Float64Array(ns);
    for (const [p, n] of res.names) C[m.speciesNames.indexOf(n)] = res.molal.get(p);
    const lnG = new Float64Array(ns);
    const w = RtmModel.activityAt(m.act, C, 0, lnG, new Float64Array(ns));
    let gam = 0;
    for (const [p, n] of res.names) {
      if (!(res.molal.get(p) > 0)) continue;
      gam = Math.max(gam, Math.abs(lnG[m.speciesNames.indexOf(n)] / Math.LN10 - res.water.species.get(p)[1]));
    }
    const y = m.toConcentrations(m.initialState());
    let start = 0;
    for (const [p, n] of res.names) {
      if (res.molal.get(p) > 1e-25) start = Math.max(start, Math.abs(y[m.speciesNames.indexOf(n)] / res.molal.get(p) - 1));
    }
    for (const [n, v] of res.amounts) if (v > 0) start = Math.max(start, Math.abs(y[m.speciesNames.indexOf(n)] / v - 1));
    return { res, m, gam, aw: Math.abs(w.lnAw - Math.log(res.water.aw)), start, I: res.water.mu };
  };
  const own = (opts) => ({ name: 'phreeqc.dat with a PITZER block', text: `${PITZER_OWN(opts)}${dbText}` });
  const cases = [['25 C', '', 25], ['70 C', '', 70], ['no MacInnes, no E-theta', '-MacInnes false\n-use_etheta false\n', 40],
    ['APHI', '-Aphi\n  0.392 -11 0 0 0.0001\n', 50], ['150 C', '', 150]]
    .map(([label, opts, tc]) => ({ label, ...handOff(own(opts), saline(tc), label) }));
  check('  the page\'s coefficients and water at PHREEQC\'s molalities are PHREEQC\'s: every type of parameter, at 25, 70 '
    + 'and 150 C (on the vapour pressure times a(H2O), A_phi the water\'s own), without the MacInnes scaling and E-theta, '
    + 'and with APHI', cases.every((c) => c.gam < 1e-13 && c.aw < 1e-13),
  cases.map((c) => `${c.label}: log gamma ${c.gam.toExponential(1)}, ln a(H2O) ${c.aw.toExponential(1)}`).join('; ')
    + `; I = ${cases[0].I.toFixed(2)}`);
  // <PITZER>'s lines, to the next section (<VOLUMES> where the water is above one atmosphere, or <REACTIONS>).
  const pzBody = (t) => t.split('\n<PITZER>\n')[1].split('\n<')[0].trim().split('\n');
  const species = (t) => t.split('<SPECIES>')[1].split('<EQUILIBRIUM>')[0];
  check('  the hand-off: ACTIVITY = pitzer, the database\'s parameters between the species written with their terms in '
    + 'the temperature, MACINNES no, ETHETA no and APHI where the database says so, no a or b, and the page starts on '
    + 'PHREEQC\'s water', cases.every((c) => /^ACTIVITY = pitzer$/m.test(c.res.text) && c.start < 1e-12
      && pzBody(c.res.text).filter((l) => !/^(MACINNES|ETHETA|APHI)\b/.test(l)).length === c.res.report.activity.pitzer
      && !/\ba=/.test(species(c.res.text)))
    && /^B0\s+Na\+\s+Cl-\s+0\.08\s+-700\s+-4\s+0\.009\s+-0\.000003$/m.test(cases[0].res.text)
    && /^MACINNES  no$/m.test(cases[2].res.text) && /^ETHETA  no$/m.test(cases[2].res.text)
    && /^APHI  0\.392  -11  0  0  0\.0001$/m.test(cases[3].res.text),
  cases.map((c) => `${c.label}: ${c.res.report.activity.pitzer} parameters, the start within ${c.start.toExponential(1)}`)
    .join('; '));

  /*
    At 150 C with the PRESSURE the hand-off writes taken out: the page puts
    the water on the vapour pressure times its own a(H2O), as PHREEQC does
    an initial solution's, A_phi there, and F of charges 1 and 2 at that
    pressure, APHI or not (with the pressure left at one atmosphere, F1 and
    F2 would be 2.5e-3 off in log gamma).
  */
  const noP = (t) => t.replace(/^PRESSURE = .*\n/m, '');
  const hot = [['150 C', '', 150], ['150 C with APHI', '-Aphi\n  0.392 -11 0 0.0005\n', 150]]
    .map(([label, opts, tc]) => ({ label, ...handOff(own(opts), saline(tc), label, false, noP) }));
  check('  at 150 C with the PRESSURE PHREEQC\'s water is at left out of the model: the page puts the water on the vapour '
    + 'pressure times its own a(H2O), A_phi and F of charges 1 and 2 there, with APHI too, and its coefficients and water '
    + 'are PHREEQC\'s', hot.every((c) => c.gam < 1e-12 && c.aw < 1e-13 && c.start < 1e-11
      && /^PRESSURE = /m.test(c.res.text) && !/^PRESSURE = /m.test(noP(c.res.text))),
  hot.map((c) => `${c.label}: log gamma ${c.gam.toExponential(1)}, ln a(H2O) ${c.aw.toExponential(1)}, the start `
    + `${c.start.toExponential(1)}; PHREEQC at ${/^PRESSURE = (\S+)/m.exec(c.res.text)[1].slice(0, 7)} atm`).join('; '));

  // The electron: PHREEQC's Pitzer model holds the pe where the water has it unless its PITZER says -redox.
  const gw = 'SOLUTION 1\n temp 15\n pH 7.4\n pe -3\n units mmol/kgw\n Na 50; K 0.5; Ca 15; Mg 5\n Cl 85 charge\n'
    + ' S(6) 2; C(4) 2.5; Fe(2) 0.02; Si 0.2\nEND\n';
  const held = handOff(own(''), gw, 'groundwater', true);
  const free = handOff(own('-redox true\n'), gw, 'groundwater', true);
  const peOf = (db) => {
    engine.load(db.text);
    const rows = engine.run(`${gw.replace('END\n', '')}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings pe\n -start\n`
      + '10 PUNCH -LA("e-")\n -end\nREACTION 1\n O2 1\n 0.003 moles\nEND\n');
    return Number(rows[rows.length - 1][0]);
  };
  const peHeld = peOf(own(''));
  const peFree = peOf(own('-redox true\n'));
  check('  the electron: PHREEQC\'s Pitzer model holds the pe where the water has it, O2 added or not, unless -redox, and '
    + 'the hand-off fixes the electron there; with -redox it is free, as with the other models',
  Math.abs(peHeld + 3) < 1e-9 && peFree > 10 && /^e-\s+electron\s+pe=-3\s+fixed$/m.test(held.res.text)
    && /^e-\s+electron$/m.test(free.res.text) && held.start < 1e-10 && free.start < 1e-10,
  `PHREEQC's pe with 3 mmol O2 added: ${peHeld.toFixed(4)} held, ${peFree.toFixed(3)} with -redox; the starts within `
    + `${held.start.toExponential(1)} and ${free.start.toExponential(1)}`);

  // The PHREEQC tab: salt goes in; PHREEQC's coefficients move, and the model's own stay on them.
  const salty = cases[0].res.text;
  const saltText = `${salty.replace('TEND = 1\n', 'TEND = 1e5\n')}=> Na+ + Cl-, k = 1e-5\n`;
  engine.load(own('').text);
  const view = P.viewRun({ engine, database: own(''), run: pageRun(saltText, 1e5), modelText: saltText,
    water: { name: 'saline', text: saline(25) }, unit: 's', times: 12 });
  const gap = view.report.activity && view.report.activity.gap[0];
  check('  the PHREEQC tab, a run that adds 1 mol/kgw of salt to a 3 mol/kgw brine: PHREEQC\'s coefficients move, and the '
    + 'model\'s own under Pitzer stay on them', !!gap && view.report.activity.kind === 'pitzer' && Math.abs(gap.by) < 1e-6
    && Math.abs(view.report.drift[0].by) > 0.05, gap ? `PHREEQC's moved ${view.report.drift[0].by.toFixed(3)} in log K, `
      + `the model's ${Math.abs(gap.by).toExponential(1)} from them (${gap.rel})` : 'no comparison');

  // PHREEQC's own pitzer.dat, where it is on this machine.
  const pzPath = process.env.RTM_PITZER_DAT
    || path.join(require('os').homedir(), '.cache', 'kvotab-phreeqc', 'obj', 'database', 'pitzer.dat');
  if (!fs.existsSync(pzPath)) {
    console.log(`skip  pitzer.dat: not at ${pzPath} (set RTM_PITZER_DAT)`);
    return;
  }
  const pzdb = { name: 'pitzer.dat', text: fs.readFileSync(pzPath, 'latin1') };
  const seawater = `${KNOBS}SOLUTION 1\n temp 25\n units mol/kgw\n pH 8.2\n Na 0.4861\n K 0.0106\n Mg 0.0548\n Ca 0.0107\n`
    + ' Cl 0.5658 charge\n S(6) 0.0293\n C(4) 0.0021\n Br 0.00087\n B 0.00042\nEND\n';
  const hotBrine = `${KNOBS}SOLUTION 1\n temp 60\n units mol/kgw\n pH 7\n Na 4\n Ca 0.05\n Cl 4.1 charge\n S(6) 0.02\n`
    + ' C(4) 0.001\nEQUILIBRIUM_PHASES 1\n Gypsum 0 0.1\n Anhydrite 0 0\nEND\n';
  const noCl = `${KNOBS}SOLUTION 1\n temp 25\n units mol/kgw\n pH 7\n Na 1\n S(6) 0.5 charge\n C(4) 0.001\nEND\n`;
  const pzCases = [['seawater', seawater], ['a 60 C brine over gypsum', hotBrine], ['no chloride', noCl],
    ['a 150 C brine', saline(150)]].map(([label, w]) => ({ label, ...handOff(pzdb, w, label) }));
  check('  pitzer.dat: seawater, a 60 C brine over gypsum, a water with no chloride, scaled by the Cl- it would have, and '
    + 'a brine at 150 C, on the vapour pressure: the coefficients at PHREEQC\'s molalities, and the start of the model '
    + 'written from each, PHREEQC\'s', pzCases.every((c) => c.gam < 1e-13 && c.aw < 1e-13 && c.start < 1e-12),
  pzCases.map((c) => `${c.label}: log gamma ${c.gam.toExponential(1)}, the start ${c.start.toExponential(1)} `
    + `(${c.res.report.activity.pitzer} parameters)`).join('; '));

  // NaCl added to a water over anhydrite until halite forms: REACTION, and the page's model of the water.
  const anh = 'SOLUTION 1\n temp 25\n units mol/kgw\n pH 7 charge\n Ca 0.01\n S(6) 0.01\n Na 1e-6\n Cl 1e-6\n'
    + 'EQUILIBRIUM_PHASES 1\n Anhydrite 0 0.2\n Halite 0 0\n';
  const extras = ['STR_E$(TOT("Ca"), 23, 16)', 'STR_E$(EQUI("Anhydrite"), 23, 16)', 'STR_E$(EQUI("Halite"), 23, 16)'];
  const pqAt = (amounts) => {
    engine.load(pzdb.text);
    return P.parseRows(engine.run(`${P.punchBlock(extras)}${anh}REACTION 1\n NaCl 1\n ${amounts.join(' ')} moles\n`
      + 'INCREMENTAL_REACTIONS false\nEND\n')).filter((w) => w.state === 'react')
      .map((w) => ({ ca: Number(w.x[0]), anh: Number(w.x[1]), hal: Number(w.x[2]) }));
  };
  const steps = Array.from({ length: 14 }, (_, k) => 0.5 * (k + 1));
  const pq = pqAt(steps);
  engine.load(pzdb.text);
  const ares = P.waterToModel({ engine, database: pzdb, water: { name: 'anhydrite', text: `${anh}END\n` }, activity: true,
    exact: true, phases: true });
  const rate = 1e-4;
  const atext = `${ares.text.replace('TEND = 1\n', `TEND = ${steps[13] / rate}\n`)}=> Na+ + Cl-, k = ${rate}\n`;
  const am = RtmModel.compile(atext);
  const ar = FacsimileODE.runModel(am, { solver: 'ndf', tend: steps[13] / rate, rtol: 1e-10, atol: 1e-20,
    outputTimes: steps.map((a) => a / rate) });
  const caOf = am.speciesNames.map((n, i) => (/^Ca/.test(n) && n !== 'Anhydrite' ? i : -1)).filter((i) => i >= 0);
  let wCa = 0;
  let wMin = 0;
  steps.forEach((a, k) => {
    const c = am.toConcentrations(ar.grid.y[k], a / rate);
    wCa = Math.max(wCa, Math.abs(caOf.reduce((acc, i) => acc + c[i], 0) / pq[k].ca - 1));
    wMin = Math.max(wMin, Math.abs(c[am.speciesNames.indexOf('Anhydrite')] - pq[k].anh),
      Math.abs(c[am.speciesNames.indexOf('Halite')] - pq[k].hal));
  });
  const ev = ar.events.find((e) => /Halite precipitates/.test(e.expr));
  let lo = ev ? ev.t * rate * 0.95 : 0;
  let hi = ev ? ev.t * rate * 1.05 : 0;
  for (let i = 0; ev && i < 40; i++) {
    const mid = (lo + hi) / 2;
    if (pqAt([mid])[0].hal > 1e-20) hi = mid; else lo = mid;
  }
  const pqHal = (lo + hi) / 2;
  check('  pitzer.dat: NaCl added to a water over anhydrite to 7 mol/kgw, against REACTION: calcium and the minerals '
    + 'PHREEQC\'s, and halite forming where PHREEQC\'s does (bisection on the amount added)',
  wCa < 1e-6 && wMin < 1e-7 && !!ev && Math.abs((ev.t * rate) / pqHal - 1) < 1e-7,
  `Ca within ${wCa.toExponential(1)}, the minerals ${wMin.toExponential(1)} mol; halite at ${ev ? (ev.t * rate).toFixed(8) : '-'} `
    + `mol for PHREEQC's ${pqHal.toFixed(8)}`);

  // Brine into fresh water over calcite, against TRANSPORT.
  const col = sitColumn(engine, pzdb, 40, 3);
  check('  pitzer.dat: brine (2 mol/kgw NaCl) into fresh water over calcite, against PHREEQC\'s TRANSPORT: the effluent '
    + 'all the way, and where it settles', col.pH < 0.03 && col.Ca < 1e-5 && col.Na < 0.02 && col.endPH < 1e-4
    && col.endCa < 1e-4 && col.I > 1.9, `pH within ${col.pH.toFixed(4)}, Ca ${(col.Ca * 1e3).toFixed(5)} mM, Na `
      + `${(col.Na * 1e3).toFixed(2)} mM (of 2000) in the front; at the end pH ${col.plateau.toFixed(4)} within `
      + `${col.endPH.toExponential(1)}; 40 cells, 3 pore volumes: PHREEQC ${col.pqMs} ms, the page ${col.rtmMs} ms`);
}

/* ======================================================================
   A and B at the water's activity

   PHREEQC works the density of water out at the vapour pressure times the
   water's activity (calc_rho_0), and with phreeqc.dat's molar volumes
   k_temp does so again at every iteration, so a salty or hot water's
   Debye-Hueckel A and B are its own; above 100 C the water's pressure, and
   the dielectric constant with it, is that vapour pressure too. Its DH_A and
   DH_B against the page's at the same a(H2O), and the page's coefficients at
   PHREEQC's molalities, from 25 to 150 C.
   ====================================================================== */
function againstWaterActivity(engine) {
  const salty = (nacl, tc) => `${KNOBS}SOLUTION 1\n temp ${tc}\n units mol/kgw\n pH 7\n Na ${nacl}\n Cl ${nacl} charge\n`
    + ' Ca 0.01\n S(6) 0.01\n C(4) 0.002\nEND\n';
  engine.load(dbText);
  const rows = engine.run(`${salty(3, 90).replace('END\n', '')}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n`
    + ' -headings a b aw\n -start\n10 PUNCH STR_E$(DH_A, 23, 16), STR_E$(DH_B, 23, 16), STR_E$(ACT("H2O"), 23, 16)\n -end\nEND\n');
  const [pa, pb, paw] = rows[rows.length - 1].map(Number);
  const ab = RtmModel.debyeHuckelAB(90, 1, paw);
  const ab1 = RtmModel.debyeHuckelAB(90);
  check('Debye-Hueckel A and B at the water\'s activity: PHREEQC\'s DH_A and DH_B in a 3 mol/kgw NaCl water at 90 C are '
    + 'the page\'s at its a(H2O), where they are not those of pure water',
  Math.abs(ab.A / pa - 1) < 1e-13 && Math.abs(ab.B / pb - 1) < 1e-13 && Math.abs(ab1.A / pa - 1) > 1e-7,
  `A ${pa.toFixed(12)} within ${Math.abs(ab.A / pa - 1).toExponential(1)}, ${Math.abs(ab1.A / pa - 1).toExponential(1)} `
    + `from pure water's; a(H2O) ${paw.toFixed(5)}`);
  const cases = [[0.01, 25], [1, 25], [1, 60], [1, 90], [3, 90], [0.5, 150]].map(([nacl, tc]) => {
    engine.load(dbText);
    const res = P.waterToModel({ engine, database, water: { name: 'salty', text: salty(nacl, tc) }, activity: true,
      exact: true, redox: false, floor: 1e-30 });
    const m = RtmModel.compile(res.text);
    const ns = m.speciesNames.length;
    const C = new Float64Array(ns);
    for (const [p, n] of res.names) C[m.speciesNames.indexOf(n)] = res.molal.get(p);
    const lnG = new Float64Array(ns);
    RtmModel.activityAt(m.act, C, 0, lnG, new Float64Array(ns));
    let gam = 0;
    for (const [p, n] of res.names) {
      if (res.molal.get(p) > 0) gam = Math.max(gam, Math.abs(lnG[m.speciesNames.indexOf(n)] / Math.LN10 - res.water.species.get(p)[1]));
    }
    const y = m.toConcentrations(m.initialState());
    let start = 0;
    for (const [p, n] of res.names) {
      if (res.molal.get(p) > 1e-25) start = Math.max(start, Math.abs(y[m.speciesNames.indexOf(n)] / res.molal.get(p) - 1));
    }
    return { nacl, tc, gam, start };
  });
  check('  the page\'s Debye-Hueckel coefficients at PHREEQC\'s molalities, 0.01 to 3 mol/kgw of NaCl at 25 to 150 C, '
    + 'and the start of the model written from each, PHREEQC\'s', cases.every((c) => c.gam < 1e-14 && c.start < 1e-9),
  cases.map((c) => `${c.nacl} at ${c.tc} C: ${c.gam.toExponential(1)}, the start ${c.start.toExponential(1)}`).join('; '));
}

/* ======================================================================
   LLNL's activity model: PHREEQC's LLNL_AQUEOUS_MODEL_PARAMETERS

   Always on a small database of the tests' own, round numbers and LLNL's
   tables with five temperatures, an ion and a neutral species with
   -llnl_gamma, CO2, O2 and H2 with -co2_llnl_gamma and a neutral species
   with neither; and on PHREEQC's own llnl.dat where it is on this machine
   (~/.cache/kvotab-phreeqc/obj/database/llnl.dat or RTM_LLNL_DAT), skipped
   otherwise. The reading, the page's coefficients and water at PHREEQC's
   molalities between the tables' temperatures, the hand-off and its start,
   and the PHREEQC tab.
   ====================================================================== */
const OWN_LLNL = `SOLUTION_MASTER_SPECIES
H        H+       -1   H       1.008
H(1)     H+       -1   0.0
H(0)     H2        0   H
E        e-        0   0.0     0.0
O        H2O       0   O       16.0
O(-2)    H2O       0   0.0
O(0)     O2        0   O
Na       Na+       0   Na      22.99
Cl       Cl-       0   Cl      35.45
Ca       Ca+2      0   Ca      40.08
C        HCO3-     1   HCO3    12.01
C(4)     HCO3-     1   HCO3    12.01
Alkalinity HCO3-   1   HCO3    61.02
SOLUTION_SPECIES
H+ = H+
  -llnl_gamma 9
  log_k 0
e- = e-
  log_k 0
H2O = H2O
  -llnl_gamma 3
  log_k 0
Na+ = Na+
  -llnl_gamma 4
  log_k 0
Cl- = Cl-
  -llnl_gamma 3
  log_k 0
Ca+2 = Ca+2
  -llnl_gamma 6
  log_k 0
HCO3- = HCO3-
  -llnl_gamma 4
  log_k 0
H2O = OH- + H+
  -llnl_gamma 3.5
  log_k -14
  -delta_h 56 kJ
HCO3- + H+ = CO2 + H2O
  -co2_llnl_gamma
  log_k 6.3
  -delta_h -9 kJ
HCO3- = CO3-2 + H+
  -llnl_gamma 4.5
  log_k -10.3
  -delta_h 15 kJ
Na+ + Cl- = NaCl
  -llnl_gamma 3
  log_k -0.5
Ca+2 + HCO3- = CaHCO3+
  -llnl_gamma 4
  log_k 1.1
Ca+2 + Cl- = CaCl+
  -llnl_gamma 4
  log_k -0.3
Na+ + HCO3- = NaHCO3
  log_k -0.2
2 H2O = O2 + 4 H+ + 4 e-
  -co2_llnl_gamma
  log_k -86
2 H+ + 2 e- = H2
  -co2_llnl_gamma
  log_k -3.1
LLNL_AQUEOUS_MODEL_PARAMETERS
-temp
  0.01 25 60 100 150
-dh_a
  0.49 0.51 0.55 0.60 0.69
-dh_b
  0.325 0.329 0.335 0.342 0.353
-b_dot
  0.037 0.041 0.044 0.046 0.047
-c_co2
  -1.03 0.00128 256 0.44 -0.0016
`;

function againstLlnl(engine) {
  const rd = P.readDatabase(OWN_LLNL);
  const re = P.readDatabase('SOLUTION_SPECIES\nNa+ = Na+\n  -llnl_gamma 4\n  -gamma 4.1 0.08\nK+ = K+\n  -gamma 3 0\n'
    + '  -llnl_g 3.5\n');
  check('LLNL: LLNL_AQUEOUS_MODEL_PARAMETERS is read as PHREEQC reads it, its options by the prefix rule and their numbers '
    + 'on the lines after them; -llnl_gamma and -co2_llnl_gamma, the last of them and -gamma the species\' rule',
  rd.model === 'LLNL' && rd.llnl.temps.join() === '0.01,25,60,100,150' && rd.llnl.bdot.length === 5
    && rd.llnl.co2.length === 5 && rd.llnlGamma.get('Na+') === 4 && rd.co2Gamma.has('CO2') && rd.co2Gamma.has('H2')
    && !rd.llnlGamma.has('NaHCO3') && re.gamma.has('Na+') && !re.llnlGamma.has('Na+') && re.llnlGamma.get('K+') === 3.5
    && !re.gamma.has('K+'), `tables at ${rd.llnl.temps.join(', ')} C; ${rd.llnlGamma.size} species with -llnl_gamma, `
      + `${rd.co2Gamma.size} with -co2_llnl_gamma`);

  const own = { name: 'own-llnl.dat', text: OWN_LLNL };
  const water = (tc, more = '') => `${KNOBS}SOLUTION 1\n temp ${tc}\n units mol/kgw\n pH 7.5\n Na 2\n Cl 2 charge\n`
    + ` Ca 0.05\n C(4) 0.01\n${more}END\n`;
  const handOff = (db, w) => {
    engine.load(db.text);
    const res = P.waterToModel({ engine, database: db, water: { name: 'llnl', text: w }, activity: true, exact: true,
      redox: false, floor: 1e-30 });
    const m = RtmModel.compile(res.text);
    const ns = m.speciesNames.length;
    const C = new Float64Array(ns);
    for (const [p, n] of res.names) C[m.speciesNames.indexOf(n)] = res.molal.get(p);
    const lnG = new Float64Array(ns);
    const wa = RtmModel.activityAt(m.act, C, 0, lnG, new Float64Array(ns));
    let gam = 0;
    for (const [p, n] of res.names) {
      if (res.molal.get(p) > 0) gam = Math.max(gam, Math.abs(lnG[m.speciesNames.indexOf(n)] / Math.LN10 - res.water.species.get(p)[1]));
    }
    const y = m.toConcentrations(m.initialState());
    let start = 0;
    for (const [p, n] of res.names) {
      if (res.molal.get(p) > 1e-25) start = Math.max(start, Math.abs(y[m.speciesNames.indexOf(n)] / res.molal.get(p) - 1));
    }
    return { res, gam, aw: Math.abs(wa.lnAw - Math.log(res.water.aw)), start };
  };
  const cases = [40, 120].map((tc) => ({ tc, ...handOff(own, water(tc)) }));
  const t40 = cases[0].res.text;
  check('  the page\'s coefficients and water at PHREEQC\'s molalities in 2 mol/kgw of NaCl at 40 and 120 C, each between '
    + 'two of the tables\' temperatures, are PHREEQC\'s; the hand-off writes ACTIVITY = llnl, -llnl_gamma as a=, '
    + 'drummond and the tables, and the page starts on PHREEQC\'s water', cases.every((c) => c.gam < 1e-14 && c.aw < 1e-14
      && c.start < 1e-12) && /^ACTIVITY = llnl$/m.test(t40) && /^Na\+\s+\S+\s+a=4$/m.test(t40)
    && /^CO2\s+\S+\s+drummond$/m.test(t40) && /^NaHCO3\s+\S+$/m.test(t40)
    && /^TEMPERATURES\s+0\.01\s+25\s+60\s+100\s+150$/m.test(t40) && /^CO2\s+-1\.03\s+0\.00128\s+256\s+0\.44\s+-0\.0016$/m.test(t40),
  cases.map((c) => `${c.tc} C: log gamma ${c.gam.toExponential(1)}, the start ${c.start.toExponential(1)}`).join('; '));

  // An ion the database gives no -llnl_gamma: PHREEQC has no coefficient for it under this model, nor the page.
  let bare = '';
  try {
    handOff({ name: 'own-llnl.dat', text: OWN_LLNL.replace('Ca+2 + Cl- = CaCl+\n  -llnl_gamma 4\n', 'Ca+2 + Cl- = CaCl+\n') },
      water(40));
  } catch (e) { bare = e.message; }
  check('  a water with an ion the database gives no -llnl_gamma is not followed, and says why',
    /gives CaCl\+ no -llnl_gamma/.test(bare), bare.slice(0, 120));

  // The PHREEQC tab: salt goes in; PHREEQC's coefficients move, and the model's own stay on them.
  const saltText = `${t40.replace('TEND = 1\n', 'TEND = 1e5\n')}=> Na+ + Cl-, k = 1e-5\n`;
  engine.load(OWN_LLNL);
  const view = P.viewRun({ engine, database: own, run: pageRun(saltText, 1e5), modelText: saltText,
    water: { name: 'llnl', text: water(40) }, unit: 's', times: 12 });
  const gap = view.report.activity && view.report.activity.gap[0];
  check('  the PHREEQC tab, a run that adds 1 mol/kgw of salt: PHREEQC\'s coefficients move, and the model\'s own under '
    + 'LLNL\'s model stay on them', !!gap && view.report.activity.kind === 'llnl' && Math.abs(gap.by) < 1e-6
    && Math.abs(view.report.drift[0].by) > 0.01, gap ? `PHREEQC's moved ${view.report.drift[0].by.toFixed(3)} in log K, `
      + `the model's ${Math.abs(gap.by).toExponential(1)} from them (${gap.rel})` : 'no comparison');

  // PHREEQC's own llnl.dat, where it is on this machine.
  const llPath = process.env.RTM_LLNL_DAT
    || path.join(require('os').homedir(), '.cache', 'kvotab-phreeqc', 'obj', 'database', 'llnl.dat');
  if (!fs.existsSync(llPath)) {
    console.log(`skip  llnl.dat: not at ${llPath} (set RTM_LLNL_DAT)`);
    return;
  }
  const lldb = { name: 'llnl.dat', text: fs.readFileSync(llPath, 'latin1') };
  const salty = (tc) => `${KNOBS}SOLUTION 1\n temp ${tc}\n units mol/kgw\n pH 7\n Na 1\n Cl 1 charge\n Ca 0.01\n`
    + ' S(6) 0.01\n C(4) 0.002\n K 0.01\nEND\n';
  const llCases = [25, 90, 200].map((tc) => ({ tc, ...handOff(lldb, salty(tc)) }));
  check('  llnl.dat: a 1 mol/kgw NaCl water at 25, 90 and 200 C, the coefficients at PHREEQC\'s molalities and the start of '
    + 'the model written from it PHREEQC\'s', llCases.every((c) => c.gam < 1e-14 && c.aw < 1e-14 && c.start < 1e-12),
  llCases.map((c) => `${c.tc} C: log gamma ${c.gam.toExponential(1)}, the start ${c.start.toExponential(1)}`).join('; '));
}

/* ======================================================================
   MOLAR VOLUMES, log K at the pressure: PHREEQC's -Vm read, each species'
   volume against PHREEQC's VM(), waters at 100 to 500 atm and at 150 C on
   the vapour pressure handed off, the relations at PHREEQC's water after
   salt went in, anhydrite and salt against REACTION, and the PHREEQC tab
   ====================================================================== */
function againstVolumes(engine) {
  engine.load(dbText);
  const db = { name: 'phreeqc.dat', text: dbText };
  const rd = P.readDatabase(dbText);
  const re = P.readDatabase('SOLUTION_SPECIES\nNa+ = Na+\n  -Vm 1 2 3\nNa+ = Na+\nK+ = K+\n  -Millero 3 0.1 0 1 0 0 9\n'
    + 'PHASES\nFoo\n  Foo = Na+\n  -Vm 0.0369 dm3/mol\nBar\n  Bar = K+\n  -Vm 20 # cm3/mol\n');
  check('volumes: -Vm and -Millero read as PHREEQC reads them, a species\' ten numbers and six, a phase\'s with its unit; '
    + 'a reaction read again starts without', rd.vm.get('Na+').join() === '2.28,-4.38,-4.1,-0.586,0.09,4,0.3,52,-0.00333,0.566'
    && rd.phaseVm.get('Calcite') === 36.9 && !re.vm.has('Na+') && re.millero.get('K+').length === 6
    && Math.abs(re.phaseVm.get('Foo') - 36.9) < 1e-12 && re.phaseVm.get('Bar') === 20,
  `phreeqc.dat: ${rd.vm.size} species with -Vm, ${rd.phaseVm.size} phases`);

  const water = (tc, atm) => `${KNOBS}SOLUTION 1\n temp ${tc}\n pressure ${atm}\n units mol/kgw\n pH 7.5\n Na 1\n Cl 1 charge\n`
    + ' Ca 0.02\n Mg 0.01\n C(4) 0.01\n S(6) 0.01\nEQUILIBRIUM_PHASES 1\n Calcite 0 0.1\nSAVE solution 1\nEND\n';
  const handOff = (w) => P.waterToModel({ engine, database: db, water: { name: 'pressure', text: w }, activity: true,
    exact: true, redox: false, floor: 1e-30, phases: true });
  const at = (res, m) => {
    const C = new Float64Array(m.speciesNames.length);
    for (const [p, n] of res.names) C[m.speciesNames.indexOf(n)] = res.molal.get(p);
    return C;
  };
  const cases = [[25, 300], [60, 100], [150, 1], [150, 50]].map(([tc, atm]) => {
    const res = handOff(water(tc, atm));
    const m = RtmModel.compile(res.text);
    const mv = RtmModel.molarVolumes(m.act, at(res, m), 0, 0);
    let dv = 0;
    let n = 0;
    for (const [p, nm] of res.names) {
      if (!res.volumes.has(p)) continue;
      const k = m.speciesNames.indexOf(nm);
      if (!mv.V[k]) continue;
      dv = Math.max(dv, Math.abs(mv.V[k] - res.volumes.get(p)));
      n++;
    }
    dv = Math.max(dv, Math.abs(mv.Vw - res.volumes.get('H2O')));
    const y = m.toConcentrations(m.initialState());
    let start = 0;
    for (const [p, nm] of res.names) {
      if (res.molal.get(p) > 1e-25) start = Math.max(start, Math.abs(y[m.speciesNames.indexOf(nm)] / res.molal.get(p) - 1));
    }
    const pLine = /^PRESSURE = (\S+)$/m.exec(res.text);
    return { tc, atm, res, m, dv, n, start, P: res.report.pressure.atm, pLine: pLine ? Number(pLine[1]) : null,
      vols: res.report.pressure.volumes };
  });
  check('  each species\' molar volume and the water\'s at PHREEQC\'s water, the page\'s against PHREEQC\'s VM(), at 25 C and 300 atm, 60 C and '
    + '100 atm, 150 C on the vapour pressure times a(H2O) and at 50 atm; the hand-off writes PRESSURE, PHREEQC\'s, and '
    + '<VOLUMES>, the database\'s -Vm, and the model starts on PHREEQC\'s water', cases.every((c) => c.dv < 1e-12 && c.n > 10
    && c.start < 1e-12 && c.vols > 10 && c.pLine === c.P),
  cases.map((c) => `${c.tc} C ${c.P.toFixed(4)} atm: ${c.n} volumes within ${c.dv.toExponential(1)} cm3/mol, `
    + `${c.vols} written, the start ${c.start.toExponential(1)}`).join('; '));

  // The log K written are at one atmosphere: the same from the water before and after 2 mol/kgw of salt went in.
  const lkOf = (text) => {
    const out = new Map();
    for (const l of text.split('<EQUILIBRIUM>')[1].split(/\n\n/)[0].split('\n')) {
      const mm = /^(.*?<=>.*?),\s*(?:logK = ([^,\s]+)|analytic = ([^,#]+))/.exec(l);
      if (mm) out.set(mm[1].trim(), mm[2] !== undefined ? Number(mm[2]) : Number(mm[3].trim().split(/\s+/)[0]));
    }
    return out;
  };
  const salted = (tc, atm) => `${water(tc, atm)}USE solution 1\nREACTION 1\n NaCl 1\n 2 moles\nSAVE solution 2\nEND\n`;
  const ends = [[25, 500], [150, 1], [150, 200]].map(([tc, atm]) => {
    const a = handOff(water(tc, atm));
    const b = handOff(salted(tc, atm));
    const la = lkOf(a.text);
    const lb = lkOf(b.text);
    let lk = 0;
    for (const [k, v] of la) if (lb.has(k)) lk = Math.max(lk, Math.abs(v - lb.get(k)));
    // Every relation of the model written at the start, at PHREEQC's water after the salt.
    const m = RtmModel.compile(a.text);
    const C = new Float64Array(m.speciesNames.length);
    for (const [p, n] of a.names) { const sp = b.water.species.get(p); C[m.speciesNames.indexOf(n)] = sp ? sp[0] : 0; }
    const lnG = new Float64Array(C.length);
    const w = RtmModel.activityAt(m.act, C, 0, lnG, new Float64Array(C.length), 0);
    let worst = 0;
    let without = 0;
    for (const eq of m.equilibria) {
      if (eq.mineral >= 0 || eq.net.some(([s]) => !(C[s] > 1e-25))) continue;
      let r = RtmModel.lnKAtP(eq, 0, w) - (eq.water || 0) * w.lnAw;
      for (const [s, nu] of eq.net) r -= nu * (Math.log(C[s]) + lnG[s]);
      worst = Math.max(worst, Math.abs(r));
      without = Math.max(without, Math.abs(r - RtmModel.lnKAtP(eq, 0, w) + RtmModel.lnKAtP(eq, 0, null)));
    }
    return { tc, P: a.report.pressure.atm, I0: a.water.mu, I1: b.water.mu, lk, worst: worst / Math.LN10, without: without / Math.LN10 };
  });
  check('  the log K written are at one atmosphere, the same from PHREEQC\'s water before and after 2 mol/kgw of NaCl went in; '
    + 'every relation of the model written before holds at PHREEQC\'s water after, its log K at the pressure going with I',
  ends.every((e) => e.lk < 1e-12 && e.worst < 1e-12 && e.without > 1e-3),
  ends.map((e) => `${e.tc} C ${e.P.toFixed(3)} atm, I ${e.I0.toFixed(2)} to ${e.I1.toFixed(2)}: log K ${e.lk.toExponential(1)}, `
    + `the relations ${e.worst.toExponential(1)} (${e.without.toFixed(3)} without the volumes)`).join('; '));

  // Anhydrite and salt at 500 atm against REACTION, and at one atmosphere for how far the pressure takes it.
  const anh = (atm) => `${KNOBS}SOLUTION 1\n temp 25\n pressure ${atm}\n units mol/kgw\n pH 7\n Na 0.5\n Cl 0.5 charge\n Ca 0.01\n`
    + ' S(6) 0.01\nEQUILIBRIUM_PHASES 1\n Anhydrite 0 1\nSAVE solution 1\nSAVE equilibrium_phases 1\nEND\n';
  const anhRun = (atm) => {
    const res = handOff(anh(atm));
    const text = `${res.text.replace(/TEND = [^\n]*\n/, 'TEND = 1e5\n').replace(/EQUILIBRATE = [^\n]*\n/, 'EQUILIBRATE = always\n')}`
      + '\n<REACTIONS>\n=> Na+ + Cl-, k = 3e-5\n';
    const m = RtmModel.compile(text.replace(/\n<REACTIONS>\n([^<]*)\n<REACTIONS>\n/, '\n<REACTIONS>\n$1'));
    const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: 1e5, rtol: 1e-10, atol: 1e-20 });
    const y = m.toConcentrations(r.y[r.y.length - 1]);
    const pq = P.parseRows(engine.run(`${P.punchBlock(['EQUI("Anhydrite")', 'TOT("Ca")'])}${anh(atm)}USE solution 1\n`
      + 'USE equilibrium_phases 1\nREACTION 1\n NaCl 1\n 3 moles\nEND\n')).pop();
    const amount = y[m.speciesNames.indexOf('Anhydrite')];
    let ca = 0;
    m.speciesNames.forEach((n, k) => { if (/^Ca/.test(n) && n !== 'Anhydrite') ca += y[k]; });
    return { amount, pqAmount: Number(pq.x[0]), ca, pqCa: Number(pq.x[1]), I: pq.mu };
  };
  const a500 = anhRun(500);
  const a1 = anhRun(1);
  check('  3 mol/kgw of NaCl added to a water over anhydrite at 500 atm, against REACTION: calcium and the anhydrite left as '
    + 'PHREEQC has them, the pressure taking them well away from the same at one atmosphere',
  Math.abs(a500.ca / a500.pqCa - 1) < 1e-7 && Math.abs(a500.amount - a500.pqAmount) < 1e-8
    && Math.abs(a500.pqCa / a1.pqCa - 1) > 0.05,
  `calcium ${a500.ca.toExponential(6)}, within ${Math.abs(a500.ca / a500.pqCa - 1).toExponential(1)} of PHREEQC's `
    + `(${a1.pqCa.toExponential(4)} at 1 atm), anhydrite left within ${Math.abs(a500.amount - a500.pqAmount).toExponential(1)} mol, `
    + `I ${a500.I.toFixed(2)}`);

  // The PHREEQC tab at 500 atm: PHREEQC's coefficients and log K move, and the model's own stay on them.
  const res = handOff(water(25, 500));
  const saltText = `${res.text.replace('TEND = 1\n', 'TEND = 1e5\n')}`.replace(/(<REACTIONS>\n)?$/, '')
    + (/<REACTIONS>/.test(res.text) ? '=> Na+ + Cl-, k = 1e-5\n' : '\n<REACTIONS>\n=> Na+ + Cl-, k = 1e-5\n');
  const view = P.viewRun({ engine, database: db, run: pageRun(saltText, 1e5), modelText: saltText,
    water: { name: 'pressure', text: water(25, 500) }, unit: 's', times: 12 });
  const gap = view.report.activity && view.report.activity.gap[0];
  check('  the PHREEQC tab at 500 atm, a run that adds 1 mol/kgw of salt: PHREEQC\'s waters at the model\'s pressure, its '
    + 'coefficients and log K move, and the model\'s own stay on them', !!gap && Math.abs(gap.by) < 1e-6
    && Math.abs(view.report.drift[0].by) > 0.01, gap ? `PHREEQC's moved ${view.report.drift[0].by.toFixed(3)} in log K, `
      + `the model's ${Math.abs(gap.by).toExponential(1)} from them (${gap.rel})` : 'no comparison');

  // PHREEQC's own pitzer.dat, where it is on this machine: its molar volumes under Pitzer's model at 500 atm.
  const pzPath = process.env.RTM_PITZER_DAT
    || path.join(require('os').homedir(), '.cache', 'kvotab-phreeqc', 'obj', 'database', 'pitzer.dat');
  if (!fs.existsSync(pzPath)) {
    console.log(`skip  pitzer.dat at pressure: not at ${pzPath} (set RTM_PITZER_DAT)`);
    return;
  }
  const pzdb = { name: 'pitzer.dat', text: fs.readFileSync(pzPath, 'latin1') };
  engine.load(pzdb.text);
  const brine = `${KNOBS}SOLUTION 1\n temp 90\n pressure 500\n units mol/kgw\n pH 7\n Na 3\n Cl 3 charge\n Ca 0.05\n`
    + ' S(6) 0.03\n C(4) 0.002\n Mg 0.05\nEQUILIBRIUM_PHASES 1\n Anhydrite 0 0.1\nSAVE solution 1\nEND\n';
  const ho = (w) => P.waterToModel({ engine, database: pzdb, water: { name: 'brine', text: w }, activity: true, exact: true,
    redox: false, floor: 1e-30, phases: true });
  const pa = ho(brine);
  const pb = ho(`${brine}USE solution 1\nREACTION 1\n NaCl 1\n 1.5 moles\nEND\n`);
  const pm = RtmModel.compile(pa.text);
  const py = pm.toConcentrations(pm.initialState());
  let pStart = 0;
  for (const [p, n] of pa.names) if (pa.molal.get(p) > 1e-25) pStart = Math.max(pStart, Math.abs(py[pm.speciesNames.indexOf(n)] / pa.molal.get(p) - 1));
  const pC = new Float64Array(py.length);
  for (const [p, n] of pa.names) { const sp = pb.water.species.get(p); pC[pm.speciesNames.indexOf(n)] = sp ? sp[0] : 0; }
  const pG = new Float64Array(py.length);
  const pw = RtmModel.activityAt(pm.act, pC, 0, pG, new Float64Array(py.length), 0);
  let pWorst = 0;
  for (const eq of pm.equilibria) {
    if (eq.mineral >= 0 || eq.net.some(([s]) => !(pC[s] > 1e-25))) continue;
    let r = RtmModel.lnKAtP(eq, 0, pw) - (eq.water || 0) * pw.lnAw;
    for (const [s, nu] of eq.net) r -= nu * (Math.log(pC[s]) + pG[s]);
    pWorst = Math.max(pWorst, Math.abs(r) / Math.LN10);
  }
  check('  pitzer.dat: a brine at 90 C and 500 atm handed off under Pitzer with the database\'s volumes starts on PHREEQC\'s '
    + 'water, and its relations hold at PHREEQC\'s after 1.5 mol/kgw of NaCl went in', pStart < 1e-10 && pWorst < 1e-10
    && pa.report.pressure.volumes > 5, `the start ${pStart.toExponential(1)}, the relations ${pWorst.toExponential(1)} in log K `
      + `(I ${pa.water.mu.toFixed(2)} to ${pb.water.mu.toFixed(2)}), ${pa.report.pressure.volumes} volumes`);
  engine.load(dbText);
}

/* ======================================================================
   SITES THAT GO WITH A PHASE: PHREEQC's SURFACE with equilibrium_phase,
   handed off as sites= per=, salt added against REACTION
   ====================================================================== */
function againstSurfaceMineral(engine) {
  engine.load(dbText);
  const db = { name: 'phreeqc.dat', text: dbText };
  // Hfo's sites on anhydrite, which dissolves into salt without making water (a ferrihydrite would: 3 H2O a mole).
  const water = (more = '') => `${KNOBS}SOLUTION 1\n pH 7\n units mol/kgw\n Na 0.1\n Cl 0.1 charge\n Ca 0.01\n S(6) 0.01\n`
    + ' Zn 1e-6\nEQUILIBRIUM_PHASES 1\n Anhydrite 0 0.1\nSURFACE 1\n -equilibrate 1\n'
    + ` Hfo_wOH Anhydrite equilibrium_phase 0.02\n Hfo_sOH Anhydrite equilibrium_phase 0.0005\n -no_edl\n${more}`
    + 'SAVE solution 1\nSAVE equilibrium_phases 1\nSAVE surface 1\nEND\n';
  const res = P.waterToModel({ engine, database: db, water: { name: 'on anhydrite', text: water() }, activity: true,
    exact: true, redox: false, floor: 1e-30, phases: true });
  const m = RtmModel.compile(res.text);
  const y = m.toConcentrations(m.initialState());
  let start = 0;
  for (const [n, a] of res.amounts) {
    const k = m.speciesNames.indexOf(n);
    if (a > 1e-25 && k >= 0) start = Math.max(start, Math.abs(y[k] / a - 1));
  }
  for (const [p, n] of res.names) {
    const k = m.speciesNames.indexOf(n);
    if (res.molal.get(p) > 1e-25 && k >= 0) start = Math.max(start, Math.abs(y[k] / res.molal.get(p) - 1));
  }
  check('sites that go with a phase: PHREEQC\'s Hfo_wOH and Hfo_sOH on anhydrite (equilibrium_phase 0.02 and 0.0005) are '
    + 'written so many per mole of the mineral, sites= per=, and the model starts on PHREEQC\'s water and surface',
  start < 1e-12 && /^Hfo_wOH\s+\S+\s+surface\s+sites=0\.02\s+per=Anhydrite$/m.test(res.text)
    && /^Hfo_sOH\s+\S+\s+surface\s+sites=0\.0005\s+per=Anhydrite$/m.test(res.text), `the start ${start.toExponential(1)}`);

  // 0.3 mol/kgw of NaCl: anhydrite dissolves, the sites go with it, and what was on them comes off.
  const text = `${res.text.replace(/TEND = [^\n]*\n/, 'TEND = 1e5\n').replace(/EQUILIBRATE = [^\n]*\n/, 'EQUILIBRATE = always\n')}`
    + '\n<REACTIONS>\n=> Na+ + Cl-, k = 3e-6\n';
  const m2 = RtmModel.compile(text);
  const r = FacsimileODE.runModel(m2, { solver: 'ndf', tend: 1e5, rtol: 1e-10, atol: 1e-20 });
  const ye = m2.toConcentrations(r.y[r.y.length - 1]);
  const at = (n) => ye[m2.speciesNames.indexOf(n)];
  const lnG = new Float64Array(ye.length);
  RtmModel.activityAt(m2.act, ye, 0, lnG, new Float64Array(ye.length));
  const kH = m2.speciesNames.indexOf('H+');
  const pH = -(Math.log(ye[kH]) + lnG[kH]) / Math.LN10;
  const sites = m2.speciesNames.filter((n) => /^Hfo_w/.test(n)).reduce((acc, n) => acc + at(n), 0);
  const pq = P.parseRows(engine.run(`${P.punchBlock(['EQUI("Anhydrite")', 'TOT("water")'])}${water()}USE solution 1\n`
    + 'USE equilibrium_phases 1\nUSE surface 1\nREACTION 1\n NaCl 1\n 0.3 moles\nEND\n')).pop();
  let pqSites = 0;
  for (const [n, e] of pq.surface) if (/^Hfo_w/.test(n)) pqSites += e.m;
  const pqZn = (pq.surface.get('Hfo_wOZn+') || { m: 0 }).m + (pq.surface.get('Hfo_sOZn+') || { m: 0 }).m;
  const zn = (at('Hfo_wOZn+') || 0) + (at('Hfo_sOZn+') || 0);
  const M = at('Anhydrite');
  const pqM = Number(pq.x[0]);
  check('  0.3 mol/kgw of NaCl into it against REACTION: the anhydrite left, the zinc on the surface and the pH as PHREEQC '
    + 'has them, the sites 0.02 per mole of anhydrite as PHREEQC keeps them', Math.abs(M / pqM - 1) < 1e-6
    && Math.abs(zn / pqZn - 1) < 1e-5 && Math.abs(pH - pq.pH) < 1e-6 && Math.abs(sites / (0.02 * M) - 1) < 1e-12
    && Math.abs(pqSites / (0.02 * pqM) - 1) < 1e-6,
  `anhydrite ${M.toFixed(8)} for PHREEQC's ${pqM.toFixed(8)}, zinc on it within ${Math.abs(zn / pqZn - 1).toExponential(1)}, `
    + `pH ${Math.abs(pH - pq.pH).toExponential(1)}; PHREEQC's water ${Number(pq.x[1]).toFixed(9)} kg`);

  // With PHREEQC's double layer, its area 600 m2 to each mole of anhydrite: written area= per=, and salt as before.
  const ddlWater = () => water().replace(' -no_edl\n', '').replace('equilibrium_phase 0.02\n', 'equilibrium_phase 0.02 600\n');
  const rd = P.waterToModel({ engine, database: db, water: { name: 'with its double layer', text: ddlWater() },
    activity: true, exact: true, redox: false, floor: 1e-30, phases: true });
  const md = RtmModel.compile(`${rd.text.replace(/TEND = [^\n]*\n/, 'TEND = 1e5\n').replace(/EQUILIBRATE = [^\n]*\n/,
    'EQUILIBRATE = always\n')}\n<REACTIONS>\n=> Na+ + Cl-, k = 3e-6\n`);
  const yd0 = md.toConcentrations(md.initialState());
  let dStart = 0;
  for (const [n, a] of rd.amounts) {
    const k = md.speciesNames.indexOf(n);
    if (a > 1e-25 && k >= 0) dStart = Math.max(dStart, Math.abs(yd0[k] / a - 1));
  }
  const rr = FacsimileODE.runModel(md, { solver: 'ndf', tend: 1e5, rtol: 1e-10, atol: 1e-20 });
  const yd = md.toConcentrations(rr.y[rr.y.length - 1]);
  const atd = (n) => yd[md.speciesNames.indexOf(n)];
  const lnGd = new Float64Array(yd.length);
  RtmModel.activityAt(md.act, yd, 0, lnGd, new Float64Array(yd.length));
  const kHd = md.speciesNames.indexOf('H+');
  const pHd = -(Math.log(yd[kHd]) + lnGd[kHd]) / Math.LN10;
  const pqd = P.parseRows(engine.run(`${P.punchBlock(['EQUI("Anhydrite")', 'EDL("psi", "Hfo")'])}${ddlWater()}USE solution 1\n`
    + 'USE equilibrium_phases 1\nUSE surface 1\nREACTION 1\n NaCl 1\n 0.3 moles\nEND\n')).pop();
  const znd = (atd('Hfo_wOZn+') || 0) + (atd('Hfo_sOZn+') || 0);
  const pqZnd = (pqd.surface.get('Hfo_wOZn+') || { m: 0 }).m + (pqd.surface.get('Hfo_sOZn+') || { m: 0 }).m;
  const psi = -Math.log(atd('Hfo_psi')) * GAS_R_T(25);
  check('  with PHREEQC\'s double layer, its area 600 m2 to each mole of anhydrite: written area= per=, the start PHREEQC\'s, '
    + 'and 0.3 mol/kgw of NaCl against REACTION: the anhydrite, the zinc on the surface, the pH and the potential',
  /^Hfo_psi\s+\S+\s+potential\s+area=600\s+per=Anhydrite$/m.test(rd.text) && dStart < 1e-12
    && Math.abs(atd('Anhydrite') / Number(pqd.x[0]) - 1) < 1e-6 && Math.abs(znd / pqZnd - 1) < 1e-5
    && Math.abs(pHd - pqd.pH) < 1e-6 && Math.abs(psi - Number(pqd.x[1])) < 1e-6,
  `the start ${dStart.toExponential(1)}; anhydrite within ${Math.abs(atd('Anhydrite') / Number(pqd.x[0]) - 1).toExponential(1)}, `
    + `zinc on it ${Math.abs(znd / pqZnd - 1).toExponential(1)}, pH ${Math.abs(pHd - pqd.pH).toExponential(1)}, the potential `
    + `${(psi * 1e3).toFixed(4)} mV for PHREEQC's ${(Number(pqd.x[1]) * 1e3).toFixed(4)}`);
}

/* ======================================================================
   AN EXCHANGER'S SITES THAT GO WITH A PHASE OR A KINETIC REACTANT:
   PHREEQC's `CaX2 Anhydrite equilibrium_phase 0.05` and `NaX NaOHs
   kinetic_reactant 0.1`, handed off as sites= per= on the species, salt
   added against REACTION and the host dissolving against KINETICS
   ====================================================================== */
function againstExchangeMineral(engine) {
  const db = { name: 'phreeqc.dat', text: dbText };
  /*
    CaX2 on anhydrite, 0.05 of it to each mole -- 0.1 sites -- in a sodium
    chloride water: 0.3 mol/kgw more of the salt dissolves 86 % of the
    anhydrite, the sites go with it, and calcium and sodium share what is
    left as Gaines-Thomas has it at the capacity there. And the same with
    the capacity held where it started, as a check that the check can tell.
  */
  const water = () => `${KNOBS}SOLUTION 1\n pH 7\n units mol/kgw\n Na 0.1\n Cl 0.1 charge\n Ca 0.01\n S(6) 0.01\n`
    + 'EQUILIBRIUM_PHASES 1\n Anhydrite 0 0.05\nEXCHANGE 1\n CaX2 Anhydrite equilibrium_phase 0.05\n -equilibrate 1\n'
    + 'SAVE solution 1\nSAVE equilibrium_phases 1\nSAVE exchange 1\nEND\n';
  engine.load(dbText);
  const res = P.waterToModel({ engine, database: db, water: { name: 'on anhydrite', text: water() }, activity: true,
    exact: true, redox: false, floor: 1e-30, phases: true });
  const m = RtmModel.compile(res.text);
  const y0 = m.toConcentrations(m.initialState());
  let start = 0;
  for (const [n, a] of res.amounts) {
    const k = m.speciesNames.indexOf(n);
    if (a > 1e-25 && k >= 0) start = Math.max(start, Math.abs(y0[k] / a - 1));
  }
  engine.load(dbText);
  const pq = P.parseRows(engine.run(`${P.punchBlock(['EQUI("Anhydrite")', 'MOL("CaX2")', 'MOL("NaX")', 'TOT("water")'])}`
    + `${water()}USE solution 1\nUSE equilibrium_phases 1\nUSE exchange 1\nREACTION 1\n NaCl 1\n 0.3 moles\nEND\n`)).pop();
  const salted = (text) => {
    const m2 = RtmModel.compile(`${text.replace(/TEND = [^\n]*\n/, 'TEND = 1e5\n')}\n<REACTIONS>\n=> Na+ + Cl-, k = 3e-6\n`);
    const r = FacsimileODE.runModel(m2, { solver: 'ndf', tend: 1e5, rtol: 1e-10, atol: 1e-20 });
    const ye = m2.toConcentrations(r.y[r.y.length - 1]);
    const at = (n) => ye[m2.speciesNames.indexOf(n)];
    const lnG = new Float64Array(ye.length);
    RtmModel.activityAt(m2.act, ye, 0, lnG, new Float64Array(ye.length));
    const kH = m2.speciesNames.indexOf('H+');
    return { M: Math.abs(at('Anhydrite') / Number(pq.x[0]) - 1), CaX: Math.abs(at('CaX2') / Number(pq.x[1]) - 1),
      NaX: Math.abs(at('NaX') / Number(pq.x[2]) - 1), pH: Math.abs(-(Math.log(ye[kH]) + lnG[kH]) / Math.LN10 - pq.pH),
      used: 1 - at('Anhydrite') / y0[m.speciesNames.indexOf('Anhydrite')] };
  };
  const a = salted(res.text);
  const h = salted(res.text.replace(/  sites=\S+  per=Anhydrite/, ''));
  const per = res.report.exchange && res.report.exchange.per;
  const f = (v) => v.toExponential(1);
  check('an exchanger whose sites go with a phase: PHREEQC\'s CaX2 on anhydrite (equilibrium_phase 0.05) is written '
    + 'sites=0.1 per=Anhydrite on CaX2, the start PHREEQC\'s; 0.3 mol/kgw of NaCl into it against REACTION: the anhydrite '
    + 'left, CaX2, NaX and the pH as PHREEQC has them -- with the capacity held where it started, CaX2 and NaX are not',
  start < 1e-12 && /^CaX2\s+\S+\s+exchange.*\ssites=0\.1\s+per=Anhydrite$/m.test(res.text) && !!per && per.length === 1
    && per[0].mineral === 'Anhydrite' && a.M < 1e-7 && a.CaX < 1e-7 && a.NaX < 1e-7 && a.pH < 1e-8 && a.used > 0.8
    && h.CaX > 0.1 && h.NaX > 0.1,
  `the start ${f(start)}; ${(a.used * 100).toFixed(0)} % of the anhydrite dissolved: it within ${f(a.M)}, CaX2 ${f(a.CaX)}, `
    + `NaX ${f(a.NaX)}, pH ${f(a.pH)} (PHREEQC's water ${Number(pq.x[3]).toFixed(10)} kg); the capacity held: CaX2 `
    + `${f(h.CaX)}, NaX ${f(h.NaX)}`);

  /*
    NaX on a host of the tests' own, NaOH, dissolving at a first-order rate
    into a CO2 water with calcium and sodium, 0.1 of it to each mole: the
    sites go with it, calcium has most of them, and PHREEQC's KINETICS
    takes 0.1 NaX from each mole it adds. Amounts compared, PHREEQC's
    molality times its kilograms.
  */
  const sw = 'SOLUTION 1\n temp 25\n units mmol/kgw\n pH 5\n Na 1\n Ca 0.5\n Cl 2 charge\n C(4) 2\n';
  const rt = 'PHASES\nNaOHs\n NaOH = Na+ + OH-\n log_k 20\nRATES\nNaOHs\n-start\n10 rate = PARM(1) * M\n20 SAVE rate * TIME\n-end\n';
  const kn = 'KINETICS 1\nNaOHs\n -m 0.001\n -parms 1e-5\n -tol 1e-12\n -steps 2e5 in 10\n -runge_kutta 6\n';
  const xb = 'EXCHANGE 1\n NaX NaOHs kinetic_reactant 0.1\n -equilibrate 1\n';
  const KIN = 'KNOBS\n -convergence_tolerance 1e-12\n';
  engine.load(dbText);
  const kres = P.waterToModel({ engine, database: db, water: { name: 'host', text: `${KIN}${rt}${sw}${kn}${xb}END\n` },
    activity: true, exact: true });
  engine.load(dbText);
  const rows = engine.run(`${KIN}${rt}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings t M Ca Na CaX NaX pH w\n`
    + ` -start\n10 PUNCH TOTAL_TIME, KIN("NaOHs"), MOL("Ca+2"), MOL("Na+"), MOL("CaX2"), MOL("NaX"), -LA("H+"), TOT("water")\n`
    + ` -end\n${sw}${kn}${xb}END\n`);
  const pk = rows.slice(1).map((r) => r.map(Number)).filter((r) => r[0] > 0);
  const hosted = (text) => {
    const mdl = RtmModel.compile(text);
    const times = pk.map((r) => r[0]);
    const run = FacsimileODE.runModel(mdl, { solver: 'ndf', tend: times[times.length - 1], rtol: 1e-10, atol: 1e-22,
      breaks: times });
    const ns = mdl.speciesNames.length;
    const at = (n) => mdl.speciesNames.indexOf(n);
    const d = { M: 0, Ca: 0, Na: 0, CaX: 0, NaX: 0, pH: 0 };
    for (const row of pk) {
      const k = run.t.findIndex((t) => Math.abs(t - row[0]) <= 1e-9 * row[0]);
      const y = mdl.toConcentrations(run.y[k], run.t[k]);
      const lnG = new Float64Array(ns);
      RtmModel.activityAt(mdl.act, y, 0, lnG, new Float64Array(ns), 0);
      const w = row[7];
      d.M = Math.max(d.M, Math.abs(y[at('NaOHs')] / row[1] - 1));
      d.Ca = Math.max(d.Ca, Math.abs(y[at('Ca+2')] / (row[2] * w) - 1));
      d.Na = Math.max(d.Na, Math.abs(y[at('Na+')] / (row[3] * w) - 1));
      d.CaX = Math.max(d.CaX, Math.abs(y[at('CaX2')] / (row[4] * w) - 1));
      d.NaX = Math.max(d.NaX, Math.abs(y[at('NaX')] / (row[5] * w) - 1));
      d.pH = Math.max(d.pH, Math.abs(-(Math.log(y[at('H+')]) + lnG[at('H+')]) / Math.LN10 - row[6]));
    }
    return d;
  };
  const k = hosted(kres.text);
  const kh = hosted(kres.text.replace(/  sites=\S+  per=NaOHs/, ''));
  const kper = kres.report.exchange && kres.report.exchange.per;
  const used = 1 - pk[pk.length - 1][1] / 1e-3;
  check('  and with a kinetic reactant: PHREEQC\'s NaX on a host dissolving at a rate (kinetic_reactant 0.1), written '
    + 'sites=0.1 per=NaOHs on NaX; against KINETICS at its steps: the host, Ca+2 and Na+ in the water, CaX2 and NaX on the '
    + 'sites as they go, and the pH -- with the capacity held, the species on it are not',
  /^NaX\s+\S+\s+exchange.*\ssites=0\.1\s+per=NaOHs$/m.test(kres.text) && !!kper && kper.length === 1
    && kper[0].kind === 'kinetic_reactant' && k.M < 1e-7 && k.Ca < 1e-7 && k.Na < 1e-7 && k.CaX < 1e-7 && k.NaX < 1e-6
    && k.pH < 1e-7 && used > 0.8 && kh.CaX > 1 && kh.NaX > 1,
  `${(used * 100).toFixed(0)} % of the host dissolved: it within ${f(k.M)}, Ca+2 ${f(k.Ca)}, Na+ ${f(k.Na)}, CaX2 ${f(k.CaX)}, `
    + `NaX ${f(k.NaX)} in moles, pH ${f(k.pH)}; the capacity held: CaX2 ${f(kh.CaX)}, NaX ${f(kh.NaX)}`);
}

/* ======================================================================
   A COLUMN FROM PHREEQC's TRANSPORT: the input's TRANSPORT read and its
   column written -- cells, time step, dispersivity, ends -- every cell
   starting from cell 1 as PHREEQC equilibrates it before the first shift;
   Example 11's column as a user writes it, acid through calcite and calcite at
   a rate, each against PHREEQC's own TRANSPORT; the options; what is
   refused
   ====================================================================== */
/*
  An input of the tests' own in Example 11's manner: its chemistry -- a
  column of sodium and potassium nitrate, its exchanger loaded from it, then
  calcium chloride -- and its steps, as a PHREEQC user writes them: the
  column kept aside by COPY, an ADVECTION run, the cells put back, output
  and a graph, then the TRANSPORT. Calcium and chloride are only in
  SOLUTION 0, sodium, potassium and nitrate only in the column.
*/
const EXAMPLE_11 = `TITLE A column of nitrates flushed with calcium chloride.
SOLUTION 0  the water flowing in
  units  mmol/kgw
  temp   25
  pH     7  charge
  pe     12.5  O2(g)  -0.68
  Ca     0.6
  Cl     1.2
SOLUTION 1-40  the column's water
  units  mmol/kgw
  temp   25
  pH     7  charge
  pe     12.5  O2(g)  -0.68
  Na     1.0
  K      0.2
  N(5)   1.2
END
EXCHANGE 1-40
  -equilibrate 1
  X  0.0011
COPY cell 1 101
END
ADVECTION
  -cells 40
  -shifts 100
  -punch_cells 40
  -punch_frequency 1
PRINT; -reset false; -status false
SELECTED_OUTPUT
  -file  column-advection.sel
  -reset false
  -step
  -totals Na Cl K Ca
USER_PUNCH
  -heading volumes
  10 PUNCH (STEP_NO + 0.5) / 40
USER_GRAPH 1 the column by advection alone
  -headings Cl Na K Ca
  -plot_concentration_vs time
  -start
  10 PLOT_XY (STEP_NO + 0.5) / 40, TOT("Cl") * 1000, symbol = None
  -end
COPY cell 101 1-40
END
USER_GRAPH 1
  -detach
END
TRANSPORT
  -cells 40
  -lengths 0.002
  -shifts 100
  -time_step 720.0
  -flow_direction forward
  -boundary_conditions flux flux
  -diffusion_coefficient 0.0
  -dispersivities 0.002
  -correct_disp true
  -punch_cells 40
  -punch_frequency 1
SELECTED_OUTPUT
  -file  column-transport.sel
  -reset false
  -step
  -totals Na Cl K Ca
USER_GRAPH 2 the column with dispersion
  -headings Cl Na K Ca
  -plot_concentration_vs time
  10 PLOT_XY (STEP_NO + 0.5) / 40, TOT("Cl") * 1000, symbol = Plus
END
`;
function againstTransportHandOff(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const handOff = (name, text) => {
    engine.load(dbText);
    return P.waterToModel({ engine, database, water: { name, text }, activity: true, exact: true, phases: true,
      redox: false });
  };
  /*
    PHREEQC's TRANSPORT of the input against the page's run of the column
    written from it: the last cell's totals of `els` (and pH, and `amount`,
    a mineral or a reactant, in every cell at the last shift), PHREEQC's
    after shift k against the page's half a time step later; with `stag`,
    the stagnant cell behind the last one too (the input punching it),
    the page's rock layer behind its last cell.
  */
  const compare = (text, res, els, amount, stag) => {
    const t = P.readTransport(text);
    const N = t.cells;
    const S = t.shifts;
    const dt = t.dt;
    const at = text.search(/^TRANSPORT\b/m);
    engine.load(dbText);
    const rows = engine.run(`${text.slice(0, at)}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings cell time pH `
      + `${els.join(' ')}${amount ? ' am' : ''}\n -start\n10 PUNCH CELL_NO, TOTAL_TIME, -LA("H+"), ${els.map((el) => `TOT("${el}")`)
        .join(', ')}${amount ? `, ${amount}` : ''}\n -end\n${text.slice(at)}`);
    const head = rows[0].map((h) => String(h).trim());
    const pq = new Map();
    for (const r of rows.slice(1)) {
      const time = Number(r[head.indexOf('time')]);
      if (time > 0) pq.set(`${Number(r[head.indexOf('cell')])}/${Math.round(time / dt)}`, r.map(Number));
    }
    const m = RtmModel.compile(res.text);
    const run = FacsimileODE.runModel(m, { solver: 'ndf', tend: (S + 0.5) * dt, rtol: 1e-7, atol: 1e-20, nonNegative: true,
      outputTimes: Array.from({ length: S }, (_, k) => (k + 1.5) * dt) });
    const ns = m.speciesNames.length;
    const db = P.readDatabase(dbText);
    const back = new Map([...res.names].map(([k, n]) => [n, k]));
    const of = Object.fromEntries(els.map((el) => [el, []]));
    // A valence state as PHREEQC's TOT has it, N(5), is N(+5) where the database's formulas are expanded.
    m.speciesNames.forEach((n, i) => {
      if (!back.has(n)) return;
      const ex = db.expand(back.get(n));
      for (const el of els) {
        const key = el.replace(/\((\d)/, '(+$1');
        if (ex.has(key)) of[el].push([i, ex.get(key)]);
      }
    });
    const iH = m.speciesNames.indexOf('H+');
    const lnG = new Float64Array(ns);
    const stride = m.stride || 1;
    const worst = Object.fromEntries(['pH', ...els].map((k) => [k, 0]));
    const behind = Object.fromEntries(els.map((k) => [k, 0]));
    for (let k = 1; k <= S; k++) {
      const c = m.toConcentrations(run.grid.y[k - 1]);
      const b = (N - 1) * stride * ns;
      const d = pq.get(`${N}/${k}`);
      for (const el of els) {
        let tot = 0;
        for (const [i, kk] of of[el]) tot += kk * c[b + i];
        worst[el] = Math.max(worst[el], Math.abs(tot - d[head.indexOf(el)]));
      }
      RtmModel.activityAt(m.act, c, b, lnG, new Float64Array(ns));
      worst.pH = Math.max(worst.pH, Math.abs(-(Math.log(c[b + iH]) + lnG[iH]) / Math.LN10 - d[head.indexOf('pH')]));
      if (stag) {
        const bs = ((N - 1) * stride + 1) * ns;
        const ds = pq.get(`${2 * N + 1}/${k}`);
        for (const el of els) {
          let tot = 0;
          for (const [i, kk] of of[el]) tot += kk * c[bs + i];
          behind[el] = Math.max(behind[el], Math.abs(tot - ds[head.indexOf(el)]));
        }
      }
    }
    const out = { worst, N, S, behind };
    if (amount) {
      const name = /"([^"]+)"/.exec(amount)[1];
      const iM = m.speciesNames.indexOf(res.report.minerals.concat(res.report.kinetics ? res.report.kinetics.reactants.map((x) => ({ phase: x.name, as: x.as })) : [])
        .find((x) => x.phase === name).as);
      const end = m.toConcentrations(run.grid.y[S - 1]);
      let page = 0;
      let theirs = 0;
      out.gone = 0;
      out.pqGone = 0;
      // Every cell the input punches.
      for (let cell = 0; cell < N; cell++) {
        const row = pq.get(`${cell + 1}/${S}`);
        if (!row) continue;
        page += end[cell * stride * ns + iM];
        const v = row[head.indexOf('am')];
        theirs += v;
        if (!(end[cell * stride * ns + iM] > 0)) out.gone++;
        if (!(v > 0)) out.pqGone++;
      }
      out.page = page;
      out.theirs = theirs;
      // With stagnant cells, the amount in the one behind the last cell at every shift.
      if (stag) {
        out.behindAmount = 0;
        for (let k = 1; k <= S; k++) {
          const c = m.toConcentrations(run.grid.y[k - 1]);
          const v = pq.get(`${2 * N + 1}/${k}`)[head.indexOf('am')];
          out.behindAmount = Math.max(out.behindAmount, Math.abs(c[((N - 1) * stride + 1) * ns + iM] - v));
        }
      }
    }
    return out;
  };

  // Example 11's column, written as a user writes it: its TRANSPORT made a column, every cell as COPY puts it back.
  const r11 = handOff('Example 11', EXAMPLE_11);
  const c11 = compare(EXAMPLE_11, r11, ['Na', 'K', 'Ca', 'Cl']);
  const w = c11.worst;
  const t11 = r11.report.transport;
  check('a column from PHREEQC\'s TRANSPORT: Example 11\'s column as a user writes it -- ADVECTION first, the cells put back, then '
    + 'TRANSPORT -- its column written (40 cells, PECLET with -correct_disp, SOLUTION 0 flowing in), every cell starting as '
    + 'cell 1 after the COPY, calcium and chloride, which only SOLUTION 0 has, there to come; the effluent against PHREEQC\'s '
    + 'TRANSPORT', !!t11 && t11.cells === 40 && t11.left === 'robin' && t11.right === 'free' && Math.abs(t11.correction - 1.05) < 1e-12
    && /^PECLET = 38\.0952380952381$/m.test(r11.text) && /^CaX2\s+\S+\s+exchange/m.test(r11.text)
    && /^Cl-\s+\S+.*\sleft=0\.0011999/m.test(r11.text) && w.Na < 3e-5 && w.K < 5e-5 && w.Ca < 3e-5 && w.Cl < 1e-5,
  `within ${['Na', 'K', 'Ca', 'Cl'].map((el) => `${el} ${(w[el] * 1e3).toFixed(4)}`).join(', ')} mM; ${t11 ? `velocity `
    + `${t11.velocity.toExponential(4)} m/s, the end ${t11.tend} s` : 'no column'}`);

  // Acid through calcite in every cell (EQUILIBRIUM_PHASES), and calcite at a rate (KINETICS), each from its TRANSPORT.
  const N = 40;
  const water = (n) => `SOLUTION ${n}\n temp 25\n units mmol/kgw\n pH 7.5\n Na 2\n Ca 1\n Cl 2 charge\n C(4) 3\n`;
  const acid = 'SOLUTION 0\n temp 25\n units mmol/kgw\n pH 3 charge\n Na 2\n Ca 1\n Cl 7\n C(4) 3\n';
  const calcite = `${water(`1-${N}`)}${acid}END\nEQUILIBRIUM_PHASES 1-${N}\n Calcite 0 0.01\nEND\nTRANSPORT\n -cells ${N}\n`
    + ` -shifts ${2 * N}\n -time_step 1000\n -lengths ${N}*0.0025\n -dispersivities 0.0025\n -diffusion_coefficient 0\n`
    + ` -punch_cells 1-${N}\nEND\n`;
  const ca = compare(calcite, handOff('calcite', calcite), ['Ca'], 'EQUI("Calcite")');
  const K = 20;
  const kin = `${water(`1-${K}`)}END\nKINETICS 1-${K}\nCalcite\n -m 1e-3\n -parms 5000 0.6\n -tol 1e-10\nEND\n`
    + 'SOLUTION 0\n temp 25\n units mmol/kgw\n pH 4.5\n Na 1\n Cl 1 charge\n C(4) 10\nEND\n'
    + `TRANSPORT\n -cells ${K}\n -shifts ${2 * K}\n -time_step ${72000 / K}\n -lengths ${0.1 / K}\n -dispersivities `
    + `${0.05 / K}\n -diffusion_coefficient 0\n -punch_cells 1-${K}\nEND\n`;
  const rk = handOff('calcite at a rate', kin);
  const ck = compare(kin, rk, ['Ca'], 'KIN("Calcite")');
  const dis = (c, m0) => (c.N * m0 - c.page) / (c.N * m0 - c.theirs) - 1;
  check('  acid through calcite in every cell, EQUILIBRIUM_PHASES, and calcite dissolving at a rate, KINETICS, each '
    + 'from its TRANSPORT: the effluent, and the calcite left, against PHREEQC\'s', ca.worst.pH < 0.02 && ca.worst.Ca < 5e-5
    && Math.abs(ca.gone - ca.pqGone) <= 1 && ck.worst.pH < 0.2 && ck.worst.Ca < 2e-5 && Math.abs(dis(ck, 1e-3)) < 0.01,
  `calcite in every cell: pH within ${ca.worst.pH.toFixed(4)}, Ca ${(ca.worst.Ca * 1e3).toFixed(4)} mM, gone from `
    + `${ca.gone} cells, PHREEQC ${ca.pqGone}; at a rate on ${K} cells: pH within ${ck.worst.pH.toFixed(3)}, Ca `
    + `${(ck.worst.Ca * 1e3).toFixed(4)} mM, the calcite dissolved ${(dis(ck, 1e-3) * 100).toFixed(2)} % apart`);

  /*
    Cells that start apart: two waters, each with its exchanger loaded from
    it, flushed with calcium chloride; and calcite in the first half of the
    column only, acid flowing in. Each zone as PHREEQC equilibrates its first
    cell, cell 1's in <SPECIES>, the other's in <INITIAL>.
  */
  const twoWaters = 'SOLUTION 0\n units mmol/kgw\n pH 7 charge\n Ca 0.6\n Cl 1.2\nSOLUTION 1-20\n units mmol/kgw\n pH 7 charge\n'
    + ' Na 1.0\n K 0.2\n N(5) 1.2\nSOLUTION 21-40\n units mmol/kgw\n pH 7 charge\n Na 0.3\n K 0.6\n N(5) 0.9\nEND\n'
    + 'EXCHANGE 1-20\n -equilibrate 1\n X 0.0011\nEXCHANGE 21-40\n -equilibrate 21\n X 0.0008\nEND\n'
    + 'TRANSPORT\n -cells 40\n -lengths 0.002\n -shifts 120\n -time_step 720\n -dispersivities 0.002\n'
    + ' -diffusion_coefficient 0\n -punch_cells 40\nEND\n';
  const rz = handOff('two waters', twoWaters);
  const cz = compare(twoWaters, rz, ['Na', 'K', 'Ca', 'Cl']);
  const halfCalcite = `${water(`1-${N}`)}${acid}END\nEQUILIBRIUM_PHASES 1-20\n Calcite 0 0.01\nEND\nTRANSPORT\n -cells ${N}\n`
    + ` -shifts ${2 * N}\n -time_step 1000\n -lengths ${N}*0.0025\n -dispersivities 0.0025\n -diffusion_coefficient 0\n`
    + ` -punch_cells 1-${N}\nEND\n`;
  const rh = handOff('calcite in half', halfCalcite);
  const ch = compare(halfCalcite, rh, ['Ca'], 'EQUI("Calcite")');
  const zonesOf = (res) => res.report.transport.zones.map((z) => z.cells.join('-')).join(', ');
  check('  cells that start apart, each zone as PHREEQC equilibrates its first cell, the first in <SPECIES> and the rest '
    + 'in <INITIAL>: two waters with their exchangers flushed with calcium chloride, and calcite in half the column with '
    + 'acid flowing in; the effluent, and the calcite left, against PHREEQC\'s TRANSPORT', zonesOf(rz) === '1-20, 21-40'
    && /^KX\s+20-39\s+0\.00072742/m.test(rz.text) && cz.worst.Na < 3e-5 && cz.worst.K < 5e-5 && cz.worst.Ca < 3e-5
    && cz.worst.Cl < 1e-5 && zonesOf(rh) === '1-20, 21-40' && /^Calcite\s+20-39\s+0$/m.test(rh.text) && ch.worst.pH < 0.03
    && ch.worst.Ca < 1e-4 && Math.abs(ch.gone - ch.pqGone) <= 1,
  `two waters (zones ${zonesOf(rz)}): within ${['Na', 'K', 'Ca', 'Cl'].map((el) => `${el} ${(cz.worst[el] * 1e3).toFixed(4)}`)
    .join(', ')} mM; calcite in half (zones ${zonesOf(rh)}): pH within ${ch.worst.pH.toFixed(4)}, Ca `
    + `${(ch.worst.Ca * 1e3).toFixed(4)} mM, the calcite gone from ${ch.gone} cells, PHREEQC ${ch.pqGone}`);

  /*
    Nitrate that only the inflow brings, into a water at pe 4 with nothing
    to oxidise: cell 1's trace of it goes to N2 in PHREEQC's speciation,
    leaving no NO3- to write. It is written at the trace it came in as, with
    the database's log K (waterToModel's elsewhere): the valence states apart
    and the couples tied. A first version wrote no NO3- at all, the K+ of the
    inflow coming in without it.
  */
  const nitrateIn = 'SOLUTION 0\n units mmol/kgw\n pH 7 charge\n K 1\n N(5) 1\nSOLUTION 1-20\n units mmol/kgw\n pH 7 charge\n'
    + ' Na 1\n Cl 1\nEND\nTRANSPORT\n -cells 20\n -shifts 40\n -time_step 720\n -lengths 0.01\n -dispersivities 0.002\n'
    + ' -diffusion_coefficient 0\n -punch_cells 20\nEND\n';
  const nIn = [false, true].map((redox) => {
    engine.load(dbText);
    const res = P.waterToModel({ engine, database, water: { name: 'nitrate in', text: nitrateIn }, activity: true, exact: true,
      phases: true, redox });
    return { redox, res, cmp: compare(nitrateIn, res, ['K', 'N(5)', 'Na']) };
  });
  check('  what only another water brings and cell 1\'s trace of it has none of -- nitrate coming into a water at pe 4, N2 '
    + 'there in PHREEQC\'s speciation -- written at that trace, and the effluent against TRANSPORT, the valence states apart '
    + 'and the couples tied', nIn.every((x) => /^NO3-\s+9\.99\d*e-16\s.*left=0\.00099999/m.test(x.res.text)
    && x.res.report.transport.elsewhere.includes('NO3-') && /^# Cell 1's water has none of NO3-/m.test(x.res.text)
    && x.cmp.worst.K < 8e-5 && x.cmp.worst['N(5)'] < 8e-5 && x.cmp.worst.Na < 8e-5),
  nIn.map((x) => `${x.redox ? 'tied' : 'apart'}: within K ${(x.cmp.worst.K * 1e3).toFixed(4)}, N(5) ${(x.cmp.worst['N(5)'] * 1e3).toFixed(4)}, `
    + `Na ${(x.cmp.worst.Na * 1e3).toFixed(4)} mM; written at the trace: ${x.res.report.transport.elsewhere.join(', ')}`).join('; '));

  /*
    Stagnant cells, -stagnant 1 alpha theta_m theta_im: the page's rock
    matrix of one layer. First the exchange alone, which comes out exact:
    closed cells of one water, which diffusion moves nothing in, another
    water stagnant behind them -- PHREEQC's mixing is the first order
    exchange solved over each step, the page's the same equations
    integrated -- every cell and stagnant cell at every shift.
  */
  const stagAlone = 'SOLUTION 1-3\n units mmol/kgw\n pH 7 charge\n Na 1\n Cl 1\nSOLUTION 5-7\n units mmol/kgw\n pH 7 charge\n'
    + ' K 1\n Br 1\nEND\nTRANSPORT\n -cells 3\n -shifts 10\n -time_step 3000\n -flow_direction diffusion_only\n'
    + ' -boundary_conditions closed closed\n -diffusion_coefficient 1e-9\n -lengths 0.1\n -stagnant 1 5e-6 0.25 0.15\n'
    + ' -punch_cells 1-3 5-7\nEND\n';
  const ra = handOff('stagnant alone', stagAlone);
  engine.load(dbText);
  const aRows = engine.run('SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings c t Na K Cl Br\n -start\n'
    + '10 PUNCH CELL_NO, TOTAL_TIME, TOT("Na"), TOT("K"), TOT("Cl"), TOT("Br")\n -end\n'
    + `${stagAlone}`).slice(1).map((r) => r.map(Number)).filter((r) => r[1] > 0);
  const ma = RtmModel.compile(ra.text);
  const aTimes = [...new Set(aRows.map((r) => r[1]))].sort((a, b) => a - b);
  const runA = FacsimileODE.runModel(ma, { solver: 'ndf', tend: aTimes[aTimes.length - 1], rtol: 1e-10, atol: 1e-20,
    outputTimes: aTimes });
  const nsA = ma.speciesNames.length;
  const inA = (n) => ma.speciesNames.indexOf(n);
  let aWorst = 0;
  let aWhere = '';
  aTimes.forEach((tt, i) => {
    const c = ma.toConcentrations(runA.grid.y[i], tt);
    for (const row of aRows.filter((q) => q[1] === tt)) {
      const cell = row[0] <= 3 ? (row[0] - 1) * ma.stride : (row[0] - 5) * ma.stride + 1;
      const tot = [c[cell * nsA + inA('Na+')], c[cell * nsA + inA('K+')],
        c[cell * nsA + inA('Cl-')] + (inA('HCl') >= 0 ? c[cell * nsA + inA('HCl')] : 0),
        c[cell * nsA + inA('Br-')] + (inA('HBr') >= 0 ? c[cell * nsA + inA('HBr')] : 0)];
      tot.forEach((v, j) => {
        const d = Math.abs(v - row[2 + j]) / 1e-3;
        if (d > aWorst) { aWorst = d; aWhere = `${['Na', 'K', 'Cl', 'Br'][j]}, cell ${row[0]}`; }
      });
    }
  });
  const aSt = ra.report.transport.stagnant;
  check('  stagnant cells (-stagnant 1 alpha theta_m theta_im) as a rock matrix of one layer: the stagnant porosity, 1 m '
    + 'deep, the wetted surface 1/theta_m and every species\' Dm alpha/2, the stagnant water in <INITIAL> aimed at the '
    + 'matrix; the exchange alone exact against TRANSPORT at every shift, in every cell and stagnant cell',
  !!aSt && aSt.zones.length === 1 && !aSt.zones[0].same && /^MATRIX_CELLS = 1$/m.test(ra.text)
    && /^MATRIX_POROSITY = 0\.15$/m.test(ra.text) && /^WETTED_SURFACE = 4$/m.test(ra.text)
    && /^Na\+\s.*\sDm=0\.0000025(\s|$)/m.test(ra.text) && /^K\+\s+0-2\s+0\.001\S*\s+matrix$/m.test(ra.text)
    && aWorst < 1e-7 && aRows.length === 60,
  `${aRows.length} values, the worst ${aWorst.toExponential(1)} of 1 mmol/kgw (${aWhere}); zones ${JSON.stringify(aSt && aSt.zones)}`);

  /*
    A column flowing through cells with an exchanger, stagnant water with
    an exchanger behind them, flushed with salt and nitrate (our own input,
    a column written the way PHREEQC's Example 13's first one is): the
    effluent and the stagnant cell behind the last against TRANSPORT,
    nearer as the cells are refined -- PHREEQC shifts, mixes and exchanges
    in turn, the page all at once.
  */
  const stagFlow = (N) => 'SOLUTION 0\n units mmol/kgw\n pH 7 charge\n Na 1\n Cl 1\n N(5) 1\n'
    + `SOLUTION 1-${2 * N + 1}\n units mmol/kgw\n pH 7 charge\n K 1\n N(5) 1\nEXCHANGE 1-${2 * N + 1}\n -equilibrate 1\n`
    + ' X 0.001\nEXCHANGE_SPECIES\n K+ + X- = KX\n log_k 0\n -gamma 3.5 0.015\nEND\n'
    + `TRANSPORT\n -cells ${N}\n -shifts ${2 * N}\n -time_step ${54000 / N}\n -lengths ${1.5 / N}\n -dispersivities 0.01\n`
    + ` -diffusion_coefficient 0\n -stagnant 1 5e-6 0.25 0.15\n -punch_cells ${N} ${2 * N + 1}\nEND\n`;
  const flows = [20, 40].map((N) => {
    const res = handOff('stagnant flowing', stagFlow(N));
    return { N, res, cmp: compare(stagFlow(N), res, ['Na', 'K', 'Cl'], null, true) };
  });
  const [f20, f40] = flows.map((x) => x.cmp);
  const fmtW = (o) => Object.entries(o).filter(([k]) => k !== 'pH').map(([k, v]) => `${k} ${(v * 1e3).toFixed(4)}`).join(', ');
  check('  a column with stagnant cells, an exchanger in both, flushed with salt: the effluent and the stagnant cell behind '
    + 'the last against TRANSPORT, nearer as the cells are refined',
  flows.every((x) => x.res.report.transport.stagnant.zones.every((z) => z.same))
    && f40.worst.Na < 0.06e-3 && f40.worst.Cl < 0.015e-3 && f40.behind.Na < 0.05e-3 && f40.behind.Cl < 0.03e-3
    && ['Na', 'K', 'Cl'].every((el) => f40.worst[el] < f20.worst[el] && f40.behind[el] < f20.behind[el]),
  flows.map((x) => `${x.N} cells: the effluent within ${fmtW(x.cmp.worst)} mM, the stagnant cell ${fmtW(x.cmp.behind)} mM`).join('; '));

  // Calcite in the stagnant cells only, cell 1 with none: its amount in <INITIAL> aimed at the matrix, acid flowing in.
  const stagCalcite = (N) => `${KNOBS_COLUMN}SOLUTION 0\n units mmol/kgw\n pH 3 charge\n Cl 1\n Na 0.1\n`
    + `SOLUTION 1-${2 * N + 1}\n units mmol/kgw\n pH 7 charge\n Na 1\n Cl 1\n C(4) 1\nEQUILIBRIUM_PHASES ${N + 2}-${2 * N + 1}\n`
    + ` Calcite 0 0.002\nEND\nTRANSPORT\n -cells ${N}\n -shifts ${3 * N}\n -time_step ${36000 / N}\n -lengths ${1 / N}\n`
    + ` -dispersivities 0.01\n -diffusion_coefficient 0\n -stagnant 1 2e-5 0.3 0.2\n -punch_cells ${N} ${2 * N + 1}\nEND\n`;
  const behindCc = [20, 40].map((N) => {
    const res = handOff('calcite behind', stagCalcite(N));
    return { N, res, cmp: compare(stagCalcite(N), res, ['Ca'], 'EQUI("Calcite")', true) };
  });
  const [b20, b40] = behindCc.map((x) => x.cmp);
  check('  calcite in the stagnant cells only, cell 1 with none, acid flowing in: written in <INITIAL> aimed at the matrix, '
    + 'and the effluent and the calcite behind the last cell against TRANSPORT, nearer as the cells are refined',
  behindCc.every((x) => /^Calcite\s+0\s+mineral$/m.test(x.res.text) && /^Calcite\s+0-\d+\s+0\.00[0-9]+\S*\s+matrix$/m.test(x.res.text))
    && b40.worst.Ca < 0.04e-3 && b40.behindAmount < 0.06e-3 && b40.worst.pH < 0.25
    && b40.worst.Ca < b20.worst.Ca && b40.behindAmount < b20.behindAmount,
  behindCc.map((x) => `${x.N} cells: pH within ${x.cmp.worst.pH.toFixed(3)}, Ca ${(x.cmp.worst.Ca * 1e3).toFixed(4)} mM, the `
    + `calcite behind the last cell ${(x.cmp.behindAmount * 1e3).toFixed(4)} mmol`).join('; '));

  // The options, as the column comes out of them.
  const small = (o) => 'SOLUTION 0\n units mmol/kgw\n pH 7 charge\n Na 1\n Cl 1\nSOLUTION 1-5\n units mmol/kgw\n pH 7 charge\n'
    + ` K 1\n Br 1\nSOLUTION 6\n units mmol/kgw\n pH 7 charge\n Ca 0.5\n Cl 1\nEND\nTRANSPORT\n -cells 5\n -shifts 4\n ${o}\nEND\n`;
  const settings = (o) => {
    const res = handOff('options', small(o));
    RtmModel.compile(res.text);
    return res.text.split('\n').filter((l) => /^(CELLS|LENGTH|GRID|FACES|DIFFUSION|ADVECTION =|VELOCITY|PECLET|LEFT|RIGHT|TEND) /.test(l))
      .join('; ');
  };
  const options = [
    ['a day a shift, lengths as 5*0.1', '-time_step 1 day\n -lengths 5*0.1\n -dispersivities 0.01',
      'CELLS = 5; LENGTH = 0.5; DIFFUSION = 1; ADVECTION = 1; VELOCITY = 0.00000115740740740741; PECLET = 50; LEFT = robin; '
      + 'RIGHT = free; TEND = 345600'],
    ['flowing back, SOLUTION 6 coming in at the right', '-time_step 3600\n -flow_direction back\n -dispersivities 0.05',
      'CELLS = 5; LENGTH = 5; DIFFUSION = 1; ADVECTION = 1; VELOCITY = -0.000277777777777778; PECLET = 100; LEFT = free; '
      + 'RIGHT = robin; TEND = 14400'],
    ['both ends constant', '-time_step 3600\n -boundary_conditions constant constant\n -dispersivities 0.02\n'
      + ' -diffusion_coefficient 1e-9', 'CELLS = 5; LENGTH = 5; DIFFUSION = 1; ADVECTION = 1; VELOCITY = 0.000277777777777778; '
      + 'PECLET = 250; LEFT = dirichlet; RIGHT = dirichlet; TEND = 14400'],
    ['diffusion only, cells of their own lengths', '-time_step 3600\n -flow_direction diffusion_only\n -boundary_conditions '
      + 'closed constant\n -lengths 0.1 0.1 0.2 0.2 0.4', 'CELLS = 5; GRID = faces; FACES = 0, 0.1, 0.2, 0.4, 0.6, 1; '
      + 'DIFFUSION = 1; LEFT = neumann; RIGHT = dirichlet; TEND = 14400'],
    ['-correct_disp, flux at both ends', '-time_step 3600\n -dispersivities 0.01\n -correct_disp true',
      'CELLS = 5; LENGTH = 5; DIFFUSION = 1; ADVECTION = 1; VELOCITY = 0.000277777777777778; PECLET = 357.142857142857; '
      + 'LEFT = robin; RIGHT = free; TEND = 14400'],
    ['-multi_D with the water moving', '-time_step 3600\n -dispersivities 0.01\n -multi_d true 1e-9 0.3 0 1',
      'CELLS = 5; LENGTH = 5; DIFFUSION = nernst-planck; ADVECTION = 1; VELOCITY = 0.000277777777777778; PECLET = 500; '
      + 'LEFT = robin; RIGHT = free; TEND = 14400'],
  ];
  const wrongOpts = options.filter(([, o, want]) => settings(o) !== want);
  const back = handOff('back', small('-time_step 3600\n -shifts 4 -1'));
  const refusals = [
    ['stagnant cells with no water', small('-time_step 3600\n -stagnant 1 6.8e-6 0.3 0.1'),
      /stagnant cell 7, behind cell 1, has no SOLUTION/],
    ['stagnant cells in two layers', small('-time_step 3600\n -stagnant 2'), /stagnant cells in 2 layers \(-stagnant 2\)/],
    ['stagnant cells with no exchange factor', small('-time_step 3600\n -stagnant 1'), /-stagnant 1 with no exchange factor/],
    ['stagnant cells behind some cells only', small('-time_step 3600\n -stagnant 1 6.8e-6 0.3 0.1')
      .replace('END\nTRANSPORT', 'SOLUTION 7-9\n units mmol/kgw\n K 1\n Br 1\nEND\nTRANSPORT'),
    /stagnant cell 10, behind cell 4, has no SOLUTION/],
    ['stagnant cells at a temperature of their own', small('-time_step 3600\n -stagnant 1 6.8e-6 0.3 0.1')
      .replace('END\nTRANSPORT', 'SOLUTION 7-11\n temp 30\n units mmol/kgw\n K 1\n Br 1\nEND\nTRANSPORT'),
    /stagnant cell 7 starts at 30 C and cell 1 at 25 C/],
    ['an exchanger in the cells and not the stagnant cells', small('-time_step 3600\n -stagnant 1 6.8e-6 0.3 0.1')
      .replace('END\nTRANSPORT', 'SOLUTION 7-11\n units mmol/kgw\n K 1\n Br 1\nEXCHANGE 1-5\n -equilibrate 1\n X 0.001\n'
        + 'END\nTRANSPORT'), /an exchanger is in its cells and not in its stagnant cells/],
    ['a REACTION in a stagnant cell', small('-time_step 3600\n -stagnant 1 6.8e-6 0.3 0.1')
      .replace('END\nTRANSPORT', 'SOLUTION 7-11\n units mmol/kgw\n K 1\n Br 1\nREACTION 8\n NaCl 1\n 1e-5 moles\nEND\n'
        + 'TRANSPORT'), /a REACTION numbered as a cell \(8\)/],
    ['stagnant cells with -multi_D', small('-time_step 3600\n -multi_d true\n -stagnant 1 6.8e-6 0.3 0.1')
      .replace('END\nTRANSPORT', 'SOLUTION 7-11\n units mmol/kgw\n K 1\n Br 1\nEND\nTRANSPORT'),
    /stagnant cells \(-stagnant\) with -multi_D, which PHREEQC exchanges species by species at a rate that falls as its mixing steps grow/],
    ['cells of their own lengths under -multi_D', small('-time_step 3600\n -flow_direction diffusion_only\n -lengths 0.1 0.2\n'
      + ' -multi_d true'), /under -multi_D PHREEQC gives each cell its water whatever its length/],
    ['porosities of their own', small('-time_step 3600\n -multi_d true\n -porosities 0.3 0.2'), /cells have porosities of their own/],
    ['a porosity below -multi_D\'s limit', small('-time_step 3600\n -multi_d true 1e-9 0.3 0.4'),
      /its porosity, 0\.3, is below -multi_D's limit, 0\.4, where PHREEQC lets nothing diffuse/],
    ['coefficients corrected for the ionic strength', small('-time_step 3600\n -multi_d true 1e-9 0.3 0 1 true'),
      /corrected for the ionic strength as specific conductance has them/],
    ['a -multi_D neither true nor false', small('-time_step 3600\n -multi_d 1e-9'), /a -multi_D that says neither true nor false/],
    ['interlayer diffusion', small('-time_step 3600\n -multi_d true\n -interlayer_d true'), /interlayer diffusion \(-interlayer_D\)/],
    ['no time step', small('-dispersivities 0.01'), /it gives no -time_step/],
    ['a closed end the water comes in through', small('-time_step 3600\n -boundary_conditions closed flux'), /comes in through an end that is closed/],
    ['cells of their own lengths with the water moving', small('-time_step 3600\n -lengths 0.1 0.2'), /the page's column has one velocity/],
    ['dispersivities of their own', small('-time_step 3600\n -dispersivities 0.1 0.2'), /dispersivities of their own/],
    ['cells at temperatures of their own', 'SOLUTION 0\n units mmol/kgw\n Na 1\n Cl 1\nSOLUTION 1-2\n units mmol/kgw\n K 1\n'
      + ' Br 1\nSOLUTION 3-5\n temp 30\n units mmol/kgw\n K 1\n Br 1\nEND\nTRANSPORT\n -cells 5\n -shifts 4\n -time_step 3600\nEND\n',
    /cell 3 starts at 30 C and cell 1 at 25 C/],
    ['an exchanger in some cells only', 'SOLUTION 0\n units mmol/kgw\n Na 1\n Cl 1\nSOLUTION 1-5\n units mmol/kgw\n K 1\n'
      + ' Br 1\nEND\nEXCHANGE 1-2\n -equilibrate 1\n X 0.001\nEND\nTRANSPORT\n -cells 5\n -shifts 4\n -time_step 3600\nEND\n',
    /an exchanger is in some of its cells and not in others/],
    ['water coming in warmer', 'SOLUTION 0\n temp 40\n units mmol/kgw\n Na 1\n Cl 1\nSOLUTION 1-5\n units mmol/kgw\n K 1\n'
      + ' Br 1\nEND\nTRANSPORT\n -cells 5\n -shifts 4\n -time_step 3600\nEND\n', /carries the heat as well/],
    ['a REACTION in the cells', 'SOLUTION 0\n units mmol/kgw\n Na 1\n Cl 1\nSOLUTION 1-5\n units mmol/kgw\n K 1\n Br 1\n'
      + 'REACTION 1-5\n NaCl 1\n 1e-5 moles\nEND\nTRANSPORT\n -cells 5\n -shifts 4\n -time_step 3600\nEND\n',
    /a REACTION numbered as a cell \(1-5\)/],
  ];
  const refused = (text) => { try { handOff('refused', text); return '(carried)'; } catch (e) { return e.message; } };
  const wrongRef = refusals.filter(([, text, re]) => !re.test(refused(text)));
  check('  the options as the column comes out of them -- a time unit, lengths written n*x, the water flowing back, ends held '
    + 'constant, diffusion alone between cells of their own lengths, -correct_disp, -multi_D with the water moving, the old '
    + 'direction after -shifts -- and, '
    + `refused with their reasons: ${refusals.map((x) => x[0]).join('; ')}`, !wrongOpts.length && !wrongRef.length
    && /^VELOCITY = -0\.000277777777777778$/m.test(back.text) && /^RIGHT = robin$/m.test(back.text),
  `${wrongOpts.map(([what, o]) => `${what}: "${settings(o)}"`).join(' | ')}${wrongRef.map(([what, text]) => ` ${what}: `
    + `"${refused(text).slice(0, 160)}"`).join(' |')}`);
}

/* ======================================================================
   WHAT A RUN CAN BE READ AS, against PHREEQC: the quantities of a water
   handed off -- pH, I, a(H2O), the totals, SI(Calcite), what is on an
   exchanger and on a surface, a gas's partial pressure -- worked out by the
   model's own activity model, against PHREEQC's numbers for the same water
   ====================================================================== */
function againstQuantities(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const cases = [
    { name: 'a water with calcite and an exchanger',
      water: 'SOLUTION 1\n units mmol/kgw\n pH 7.5\n Na 5\n Ca 2\n Mg 1\n Cl 6 charge\n C(4) 4\n S(6) 1\nEQUILIBRIUM_PHASES 1\n'
        + ' Calcite 0 0.01\nEXCHANGE 1\n -equilibrate 1\n X 0.02\nEND\n',
      keys: ['pH', 'I', 'a(H2O)', 'tot(Ca)', 'tot(C)', 'tot(Na)', 'tot(S)', 'tot(Mg)', 'tot(Cl)', 'SI(Calcite)', 'share(CaX2)',
        'share(NaX)', 'share(MgX2)'],
      punch: '-LA("H+"), MU, ACT("H2O"), TOT("Ca"), TOT("C(4)"), TOT("Na"), TOT("S(6)"), TOT("Mg"), TOT("Cl"), SI("Calcite"), '
        + '2*MOL("CaX2")/TOT("X"), MOL("NaX")/TOT("X"), 2*MOL("MgX2")/TOT("X")', tol: 1e-8 },
    { name: 'a water with a surface', water: 'SOLUTION 1\n units mmol/kgw\n pH 6.5\n Na 2\n Cl 2 charge\n Zn 0.01\nSURFACE 1\n'
      + ' -equilibrate 1\n Hfo_wOH 2e-4 600 0.09\nEND\n',
    keys: ['pH', 'share(Hfo_wOH)', 'share(Hfo_wOH2+)', 'share(Hfo_wO-)', 'share(Hfo_wOZn+)'],
    punch: '-LA("H+"), MOL("Hfo_wOH")/2e-4, MOL("Hfo_wOH2+")/2e-4, MOL("Hfo_wO-")/2e-4, MOL("Hfo_wOZn+")/2e-4', tol: 1e-9 },
    { name: 'a gas phase of a fixed volume', water: 'SOLUTION 1\n units mmol/kgw\n pH 7\n Na 5\n Cl 2 charge\n C(4) 3\nGAS_PHASE 1\n'
      + ' -fixed_volume\n -volume 1\n CO2(g) 0.01\nEND\n', keys: ['pH', 'p(CO2(g))'], punch: '-LA("H+"), 10^SI("CO2(g)")', tol: 1e-7 },
  ];
  const results = cases.map((cs) => {
    engine.load(dbText);
    const res = P.waterToModel({ engine, database, water: { name: cs.name, text: cs.water }, activity: true, exact: true,
      phases: true, redox: false });
    const m = RtmModel.compile(res.text);
    const c = m.toConcentrations ? m.toConcentrations(m.initialState()) : m.initialState();
    const which = Int32Array.from(cs.keys.map((k) => m.quantities.findIndex((q) => q.key === k)));
    if ([...which].some((x) => x < 0)) return { cs, worst: Infinity, missing: cs.keys.filter((k, i) => which[i] < 0) };
    const out = new Float64Array(which.length);
    m.quantitiesAt(c, 0, 0, which, out);
    engine.load(dbText);
    const rows = engine.run(`${cs.water.replace('END\n', '')}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n 10 PUNCH ${cs.punch}\nEND\n`);
    const pq = rows[rows.length - 1].map(Number);
    let worst = 0;
    let where = '';
    cs.keys.forEach((k, i) => {
      const d = Math.abs(out[i] - pq[i]) / Math.max(Math.abs(pq[i]), k === 'pH' || /^SI/.test(k) ? 1 : 1e-300);
      if (d > worst) { worst = d; where = k; }
    });
    return { cs, worst, where };
  });
  check('quantities of a water handed off, worked out by the model, against PHREEQC\'s for it: pH, I, a(H2O), the totals, '
    + 'SI(Calcite), an exchanger\'s and a surface\'s shares, a gas\'s partial pressure',
  results.every((x) => x.worst <= x.cs.tol),
  results.map((x) => (x.missing ? `${x.cs.name}: no ${x.missing.join(', ')}` : `${x.cs.name}: within ${x.worst.toExponential(1)} (${x.where})`))
    .join('; '));
}

/* ======================================================================
   DIAGRAMS, against PHREEQC: a water handed off, held by the Diagrams tab
   at a pH, a pe or a total -- one point of the grid it works out -- against
   PHREEQC's SOLUTION of the same totals at that pH, pe or total, which
   speciates there without a charge balance as the tab does.
   ====================================================================== */
function againstDiagrams(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const handOff = (name, text, redox) => {
    engine.load(dbText);
    return P.waterToModel({ engine, database, water: { name, text }, activity: true, exact: true, redox: !!redox });
  };
  // Each species the model has, its molality as PHREEQC has it for a SOLUTION.
  const pqMolalities = (solution, names) => {
    engine.load(dbText);
    const rows = engine.run(`${solution}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n`
      + `${names.map((nm, i) => ` ${10 + i * 10} PUNCH MOL("${nm}")`).join('\n')}\nEND\n`);
    return rows[rows.length - 1].map(Number);
  };
  const diagram = (text, axes) => {
    let reply = null;
    handleRtmMessage({ type: 'diagram', id: 1, text, at: 'start', cell: 0, axes }, (m) => { if (m.type !== 'progress') reply = m; });
    if (reply.type === 'error') throw new Error(reply.error);
    return reply;
  };
  // The worst of each species against PHREEQC, relative to the larger of it and 1e-12 of the water's total of its kind.
  const compare = (reply, p, pq, names) => {
    let worst = 0;
    let where = '';
    names.forEach((nm, i) => {
      const k = reply.species.indexOf(nm);
      const ours = reply.states[p * reply.ns + k];
      const d = Math.abs(ours - pq[i]) / Math.max(Math.abs(pq[i]), 1e-15);
      if (pq[i] > 1e-15 && d > worst) { worst = d; where = nm; }
    });
    return [worst, where];
  };
  const solutes = (text) => {
    const m = RtmModel.compile(text);
    return m.speciesNames.filter((nm, k) => m.act.solute[k] && nm !== 'H2O' && nm !== 'e-');
  };
  const results = [];
  // pH: a carbonate water with no charge balance, at pH 4 to 10.
  const carb = 'SOLUTION 1\n units mmol/kgw\n pH 7.5\n Na 5\n Ca 2\n Mg 1\n Cl 7\n C(4) 4\n S(6) 1\nEND\n';
  const carbModel = handOff('carbonate', carb).text;
  const carbNames = solutes(carbModel);
  const phs = [4, 6, 8, 10];
  const r1 = diagram(carbModel, [{ kind: 'pH', from: 4, to: 10, n: 4 }]);
  phs.forEach((ph, p) => {
    const pq = pqMolalities(carb.replace(' pH 7.5', ` pH ${ph}`).replace('END\n', ''), carbNames);
    results.push(['pH', ph, ...compare(r1, p, pq, carbNames)]);
  });
  // pe: iron in both valence states at one pe, from 2 to 11, at pH 6 and 7 -- the pH held as PHREEQC's SOLUTION holds it:
  // left to itself, an unbuffered water's pH goes where reducing the iron's hydroxides takes it.
  const fe = 'SOLUTION 1\n units mmol/kgw\n pH 6\n pe 8\n Na 2\n Cl 2\n Fe 0.01\nEND\n';
  const feModel = handOff('iron', fe, true).text;
  const feNames = solutes(feModel).filter((nm) => /Fe/.test(nm));
  const r2 = diagram(feModel, [{ kind: 'pe', from: 2, to: 11, n: 4 }, { kind: 'pH', from: 6, to: 7, n: 2 }]);
  [6, 7].forEach((ph, j) => [2, 5, 8, 11].forEach((pe, i) => {
    const pq = pqMolalities(fe.replace(' pe 8', ` pe ${pe}`).replace(' pH 6', ` pH ${ph}`).replace('END\n', ''), feNames);
    results.push([`pH ${ph}, pe`, pe, ...compare(r2, j * 4 + i, pq, feNames)]);
  }));
  // A grid: pH 6 and 8 against total carbon 1e-4 and 1e-2 mol/kgw.
  const r3 = diagram(carbModel, [{ kind: 'pH', from: 6, to: 8, n: 2 }, { kind: 'tot', species: 'C', from: -4, to: -2, n: 2 }]);
  [[6, -4], [8, -4], [6, -2], [8, -2]].forEach(([ph, lt], p) => {
    const sol = carb.replace(' pH 7.5', ` pH ${ph}`).replace(' C(4) 4', ` C(4) ${1000 * 10 ** lt}`).replace('END\n', '');
    results.push([`pH ${ph}, log total C`, lt, ...compare(r3, p, pqMolalities(sol, carbNames), carbNames)]);
  });
  const worst = Math.max(...results.map((x) => x[2]));
  check('a diagram\'s points against PHREEQC\'s SOLUTION at the same pH, pe or total, every species of the water: '
    + 'a carbonate water at pH 4 to 10, iron in both valence states at pe 2 to 11 and pH 6 and 7, and pH against total carbon',
  worst < 1e-7 && r1.failed === 0 && r2.failed === 0 && r3.failed === 0,
  `the worst ${worst.toExponential(1)}: ${results.map(([what, v, w, nm]) => `${what} ${v} ${w.toExponential(1)}${nm ? ` (${nm})` : ''}`).join(', ')}`);
}

/* ======================================================================
   THE BOUNDARIES OF A MAP, against PHREEQC: a handed-off iron water's
   Pourbaix map, its boundaries found between the points of a coarse grid.
   At each point of each boundary PHREEQC's SOLUTION at that pH and pe gives
   the species either side the same amount of iron, more than any other
   species has; where three fields meet, the three of them. The map stays
   where water does, pe + pH from 0 to 20.5: far above the oxygen line
   PHREEQC's dissolved O2 runs to molalities it cannot converge on.
   ====================================================================== */
function againstBoundaries(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const fe = 'SOLUTION 1\n units mmol/kgw\n pH 6\n pe 8\n Na 2\n Cl 2\n Fe 0.01\nEND\n';
  /*
    The map of the water fe over the axes, its boundaries against PHREEQC's
    SOLUTION at their points: a point's pe on the second axis, pe(y).
  */
  const against = (fe, axes, pe) => {
    engine.load(dbText);
    const text = P.waterToModel({ engine, database, water: { name: 'iron', text: fe }, activity: true, exact: true, redox: true }).text;
    const m = RtmModel.compile(text);
    const terms = m.composition.elements.find((e) => e.el === 'Fe').terms.filter((tm) => tm[2] === 'water');
    const names = terms.map(([k]) => m.speciesNames[k]);
    let grid = null;
    handleRtmMessage({ type: 'diagram', id: 1, text, at: 'start', cell: 0, axes }, (r) => { if (r.type !== 'progress') grid = r; });
    let b = null;
    handleRtmMessage({ type: 'diagramBounds', id: 2, text, at: 'start', cell: 0, axes, grid: grid.states,
      criterion: { kind: 'predominance', terms: terms.map(([k, n]) => [k, n]) } }, (r) => { if (r.type !== 'progress') b = r; });
    if (b.type === 'error') throw new Error(b.error);
    // PHREEQC's amount of iron in each species at a pH and a pe.
    const amounts = (ph, peHere) => {
      engine.load(dbText);
      const rows = engine.run(`${fe.replace(' pH 6', ` pH ${ph.toPrecision(17)}`).replace(' pe 8', ` pe ${peHere.toPrecision(17)}`).replace('END\n', '')}`
        + `SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n${names.map((nm, i) => ` ${10 + 10 * i} PUNCH MOL("${nm}")`).join('\n')}\nEND\n`);
      return rows[rows.length - 1].map((v, i) => Number(v) * terms[i][1]);
    };
    // How far from equal the fields' own species are, and how far any other species is above them.
    const o = { b, text, worst: 0, over: -Infinity, where: '', points: 0 };
    const at = (x, y, labels) => {
      const a = amounts(x, pe(y));
      const mine = labels.map((q) => a[q]);
      const d = Math.log(Math.max(...mine) / Math.min(...mine));
      if (d > o.worst) { o.worst = d; o.where = `${labels.map((q) => names[q]).join('/')} at pH ${x.toFixed(4)}, ${axes[1].kind} ${y.toFixed(4)}`; }
      const others = a.filter((_, q) => !labels.includes(q));
      o.over = Math.max(o.over, Math.log(Math.max(...others) / Math.min(...mine)));
      o.points++;
    };
    for (const ln of b.lines) ln.x.forEach((x, q) => at(x, ln.y[q], [ln.a, ln.b]));
    for (const jn of b.junctions) at(jn.x, jn.y, jn.labels);
    o.ok = (tol) => b.unsolved === 0 && b.junctions.length >= 2 && b.junctions.every((jn) => jn.solved) && o.worst < tol && o.over < tol;
    o.said = `${b.lines.length} boundaries, ${b.junctions.length} meeting points, ${o.points} points against PHREEQC: the worst `
      + `${o.worst.toExponential(1)} (${o.where}), any other species at most 1 ${o.over < 0 ? '-' : '+'} ${Math.abs(o.over).toExponential(1)} times them`;
    return o;
  };
  const pe25 = against(fe, [{ kind: 'pH', from: 2, to: 8, n: 13 }, { kind: 'pe', from: -2, to: 12.5, n: 11 }], (y) => y);
  check('the boundaries of a Pourbaix map of a handed-off iron water, found between the points of a 13 x 11 grid: at each of '
    + 'their points PHREEQC\'s SOLUTION at that pH and pe gives the species either side the same amount of iron, to 1e-9, and '
    + 'no other species more (at a line\'s end where three meet, the third as much); where three fields meet, the three of them',
  pe25.ok(1e-9), pe25.said);
  /*
    The same water at 60 C over pH and Eh, in volts: each point's pe its Eh
    over the volts of a pe at 60 C, 0.066100 V, PHREEQC's SOLUTION given that
    pe and the temperature. The map stays below the oxygen line at 60 C,
    pe + pH 18.9.
  */
  const per60 = RtmModel.ehPerPe(333.15);
  const eh60 = against(fe.replace(' units', ' temp 60\n units'),
    [{ kind: 'pH', from: 2, to: 8, n: 13 }, { kind: 'Eh', from: -0.12, to: 0.72, n: 11 }], (y) => y / per60);
  check('  the same water at 60 C over pH and Eh: at each point of each boundary, its pe the Eh over the volts of a pe at 60 C, '
    + 'PHREEQC\'s SOLUTION at that pH, pe and temperature gives the species either side the same amount of iron, to 1e-9, and no '
    + 'other species more; where three fields meet, the three of them',
  /TEMPERATURE = 60\b/.test(eh60.text) && eh60.ok(1e-9), eh60.said);
}

/* ======================================================================
   Eh, against what PHREEQC prints. PHREEQC gives an Eh only where it prints
   a water's redox couples, each couple's pe and Eh to four decimals; the
   page's volts of a pe (RtmModel.ehPerPe) give each printed Eh back from
   the pe printed beside it, at 5, 25, 60 and 90 C. And a handed-off water's
   Eh, the page's quantity: its iron given to PHREEQC again as Fe(2) and
   Fe(3) apart, as much of each as the water has at its pe, makes a couple
   at that pe, and PHREEQC prints the couple's Eh.
   ====================================================================== */
function againstEh(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const couples = (printed) => {
    const out = [];
    const block = (printed.split('Redox couples')[1] || '').split('Distribution of species')[0];
    for (const line of block.split('\n')) {
      const m = /^\s+(\S+\/\S+)\s+(-?\d+\.\d{4})\s+(-?\d+\.\d{4})\s*$/.exec(line);
      if (m) out.push({ name: m[1], pe: Number(m[2]), eh: Number(m[3]) });
    }
    return out;
  };
  const waters = [' pH 6.5\n pe 4\n Na 2\n Cl 2 charge\n Fe(2) 0.1\n Fe(3) 1e-3\n N(5) 0.5\n N(-3) 0.01\n',
    ' pH 2.5\n pe 4\n Na 2\n Cl 2 charge\n Fe(2) 0.1\n Fe(3) 0.3\n N(5) 1e-3\n N(-3) 1\n'];
  const temps = [5, 25, 60, 90];
  const seen = [];
  for (const tc of temps) {
    for (const w of waters) {
      engine.load(dbText);
      for (const c of couples(engine.printed(`SOLUTION 1\n temp ${tc}\n units mmol/kgw\n${w}END\n`))) seen.push({ tc, ...c });
    }
  }
  // Each printed Eh from the pe printed beside it: each to four decimals, half a unit in the last either way.
  const off = (perPe) => Math.max(...seen.map((c) => Math.abs(perPe(c.tc + 273.15) * c.pe - c.eh)));
  const page = off(RtmModel.ehPerPe);
  const codata = off((tk) => (Math.LN10 * 0.008314462618 * tk) / 96.48533212);
  check(`Eh from pe as PHREEQC prints its redox couples: ${seen.length} couples at 5, 25, 60 and 90 C, pe from `
    + `${Math.min(...seen.map((c) => c.pe)).toFixed(1)} to ${Math.max(...seen.map((c) => c.pe)).toFixed(1)}, each printed Eh `
    + 'given back from the pe printed beside it to the four decimals both are printed to',
  seen.length >= 12 && temps.every((tc) => seen.some((c) => c.tc === tc)) && page <= 5.4e-5,
  `within ${page.toExponential(2)} V; with CODATA's R and F, ${codata.toExponential(2)}`);
  // A handed-off water's Eh.
  const quantity = temps.map((tc) => {
    const water = `SOLUTION 1\n temp ${tc}\n units mmol/kgw\n pH 6.5\n pe 3.5\n Na 2\n Cl 2\n Fe 0.1\nEND\n`;
    engine.load(dbText);
    const res = P.waterToModel({ engine, database, water: { name: 'iron', text: water }, activity: true, exact: true, redox: true });
    const m = RtmModel.compile(res.text);
    const c = m.toConcentrations(m.initialState());
    const out = new Float64Array(2);
    m.quantitiesAt(c, 0, 0, Int32Array.from(['pe', 'Eh'].map((k) => m.quantities.findIndex((q) => q.key === k))), out);
    engine.load(dbText);
    const rows = engine.run(`${water.replace('END\n', '')}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n`
      + ' 10 PUNCH TOT("Fe(2)")*1000, TOT("Fe(3)")*1000\nEND\n');
    const [fe2, fe3] = rows[rows.length - 1].map(Number);
    engine.load(dbText);
    const fec = couples(engine.printed(water.replace(' Fe 0.1\n', ` Fe(2) ${fe2.toPrecision(17)}\n Fe(3) ${fe3.toPrecision(17)}\n`)))
      .find((x) => x.name === 'Fe(2)/Fe(3)');
    return { tc, pe: out[0], eh: out[1], couple: fec, warm: new RegExp(`TEMPERATURE = ${tc}\\b`).test(res.text) || tc === 25 };
  });
  check('  a handed-off iron water at pe 3.5, at 5, 25, 60 and 90 C: the page\'s Eh is the one PHREEQC prints for the iron '
    + 'couple given as much Fe(2) and Fe(3) as the water has at its pe, to the four decimals it prints',
  quantity.every((q) => q.couple && Math.abs(q.pe - 3.5) < 1e-9 && Math.abs(q.couple.pe - 3.5) <= 5e-5
    && Math.abs(q.eh - q.couple.eh) <= 5.1e-5 && q.warm),
  quantity.map((q) => `${q.tc} C: ${q.eh.toFixed(6)} V for ${q.couple ? `${q.couple.eh.toFixed(4)} (its pe ${q.couple.pe.toFixed(4)})` : 'no couple'}`)
    .join('; '));
}

/* ======================================================================
   A SILICATE STABILITY MAP, against PHREEQC: a handed-off water, with
   phreeqc.dat's K-feldspar, kaolinite, gibbsite and K-mica added as
   <PHASES> at PHREEQC's log Ks at 25 C, mapped over log a(H4SiO4) and
   log a(K+)/a(H+), each phase per mole of aluminium. At each point of each
   boundary, and where three fields meet, the page's water there -- its
   totals and its pH -- given to PHREEQC's SOLUTION has the phases either
   side the same saturation index over their aluminium, and no phase a
   larger one.
   ====================================================================== */
function againstStability(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const water = 'SOLUTION 1\n units mmol/kgw\n pH 7\n Na 1\n Cl 1.1\n K 0.1\n Al 1e-6\n Si 0.1\nEND\n';
  const phases = [['K-feldspar', 'K_feldspar', '+ 8 H2O <=> K+ + Al(OH)4- + 3 H4SiO4', 1],
    ['Kaolinite', 'Kaolinite', '+ 6 H+ <=> H2O + 2 H4SiO4 + 2 Al+3', 2], ['Gibbsite', 'Gibbsite', '+ 3 H+ <=> Al+3 + 3 H2O', 1],
    ['K-mica', 'K_mica', '+ 10 H+ <=> K+ + 3 Al+3 + 3 H4SiO4', 3]];
  engine.load(dbText);
  const lk = engine.run(`${water.replace('END\n', '')}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n`
    + `${phases.map(([pq], i) => ` ${10 + 10 * i} PUNCH LK_PHASE("${pq}")`).join('\n')}\nEND\n`);
  const logKs = lk[lk.length - 1].map(Number);
  engine.load(dbText);
  const res = P.waterToModel({ engine, database, water: { name: 'silicate', text: water }, activity: true, exact: true });
  const text = `${res.text}\n<PHASES>\n${phases.map(([, nm, rx], i) => `${nm} ${rx},  logK = ${logKs[i]}`).join('\n')}\n`;
  const m = RtmModel.compile(text);
  const keys = phases.map(([, nm]) => `SI(${nm})`);
  const axes = [{ kind: 'la', species: 'H4SiO4', from: -5, to: -2, n: 13 }, { kind: 'ratio', species: 'K+', from: 0, to: 6, n: 13 }];
  const reply = (msg) => { let r = null; handleRtmMessage(msg, (x) => { if (x.type !== 'progress') r = x; }); if (r.type === 'error') throw new Error(r.error); return r; };
  const grid = reply({ type: 'diagram', id: 1, text, at: 'start', cell: 0, axes });
  const b = reply({ type: 'diagramBounds', id: 2, text, at: 'start', cell: 0, axes, grid: grid.states,
    criterion: { kind: 'phase', keys, per: phases.map((p) => p[3]) } });
  const ns = m.speciesNames.length;
  const totalsOf = (y) => Object.fromEntries(['K', 'Al', 'Si', 'Na', 'Cl'].map((el) => [el, m.composition.elements.find((e) => e.el === el)
    .terms.filter((tm) => tm[2] === 'water').reduce((acc, [k, n]) => acc + n * y[k], 0)]));
  // PHREEQC's saturation index of each phase over its aluminium, in the page's water at (x, y).
  const perAl = (x, y) => {
    const w = reply({ type: 'diagram', id: 3, text, at: 'start', cell: 0,
      axes: [{ kind: 'la', species: 'H4SiO4', from: x, to: x + 0.01, n: 2 }, { kind: 'ratio', species: 'K+', from: y, to: y + 0.01, n: 2 }] });
    const t = totalsOf(w.states.subarray(0, ns));
    const pH = w.quant[w.keys.indexOf('pH')];
    engine.load(dbText);
    const rows = engine.run(`SOLUTION 1\n units mol/kgw\n pH ${pH.toPrecision(17)}\n${Object.entries(t).map(([el, v]) => ` ${el} ${v.toPrecision(17)}`).join('\n')}\n`
      + `SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n${phases.map(([pq, , , n], i) => ` ${10 + 10 * i} PUNCH SI("${pq}")/${n}`).join('\n')}\nEND\n`);
    return rows[rows.length - 1].map(Number);
  };
  let worst = 0;
  let over = -Infinity;
  let where = '';
  let points = 0;
  const at = (x, y, labels) => {
    const v = perAl(x, y);
    const mine = labels.map((q) => v[q]);
    const d = Math.max(...mine) - Math.min(...mine);
    if (d > worst) { worst = d; where = `${labels.map((q) => phases[q][0]).join('/')} at ${x.toFixed(4)}, ${y.toFixed(4)}`; }
    over = Math.max(over, Math.max(...v.filter((_, q) => !labels.includes(q))) - Math.max(...mine));
    points++;
  };
  for (const ln of b.lines) ln.x.forEach((x, q) => at(x, ln.y[q], [ln.a, ln.b]));
  for (const jn of b.junctions) at(jn.x, jn.y, jn.labels);
  const pairs = [...new Set(b.lines.map((ln) => [phases[ln.a][0], phases[ln.b][0]].sort().join('|')))].sort().join(' ');
  check('a silicate stability map of a handed-off water, phreeqc.dat\'s K-feldspar, kaolinite, gibbsite and K-mica per mole of '
    + 'aluminium over log a(H4SiO4) and log a(K+)/a(H+): at each point of each boundary, and where three fields meet, PHREEQC\'s '
    + 'SOLUTION of the page\'s water there gives the phases either side the same saturation index over their aluminium, to 1e-9, '
    + 'and no phase a larger one',
  !grid.failed && b.unsolved === 0 && b.junctions.length === 1 && b.junctions.every((jn) => jn.solved) && worst < 1e-9 && over < 1e-9
    && pairs === 'Gibbsite|K-mica Gibbsite|Kaolinite K-feldspar|K-mica K-mica|Kaolinite',
  `${b.lines.length} boundaries (${pairs}), ${b.junctions.length} point where three meet, ${points} points against PHREEQC: `
    + `the worst ${worst.toExponential(1)} (${where}), any other phase at most ${over.toExponential(1)} above them`);
}

/* ======================================================================
   A REDOX LADDER, against PHREEQC: a handed-off water with nitrogen, iron,
   sulfur and carbon, the database's couples placed where each turns over
   -- at pH 7 along pe at 25 C, and at pH 5 along Eh at 40 C. Handed off
   with the floor at nought, every species the database has of the water's
   elements written, at none where the water has none of it: sulfide and
   methane in a water at pe 10, made from its sulfate and its carbonate --
   at pe 4 it would have no nitrate to make the rest of the nitrogen's
   from, PHREEQC counting none below 1e-30. Each species' valence state is told from
   its name and its relations as PHREEQC has it in its database; and at
   each rung PHREEQC's SOLUTION of the model's own totals, at that pH and
   pe, gives the couple's two valence states the same amount of the
   element. The range stays where water does, between H2 and O2 at 1 atm:
   PHREEQC's dissolved O2 and H2 run away outside it.
   ====================================================================== */
function againstLadder(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const water = (tc) => `SOLUTION 1\n temp ${tc}\n units mmol/kgw\n pH 7\n pe 10\n Na 2\n Cl 2\n N 0.2\n S 1\n C 2\n Fe 0.01\nEND\n`;
  const reply = (msg) => { let r = null; handleRtmMessage(msg, (x) => { if (x.type !== 'progress') r = x; }); if (r.type === 'error') throw new Error(r.error); return r; };
  const ladder = (tc, pHAt, axes, peOf) => {
    engine.load(dbText);
    const text = P.waterToModel({ engine, database, water: { name: 'redox', text: water(tc) }, activity: true, exact: true, redox: true,
      floor: 0 }).text;
    const m = RtmModel.compile(text);
    const C = m.composition;
    // The model's own totals, mol/kgw, as PHREEQC is given them at each rung.
    const y0 = m.toConcentrations(m.initialState());
    const totals = ['Na', 'Cl', 'N', 'S', 'C', 'Fe'].map((el) => ` ${el} ${C.elements.find((e) => e.el === el).terms
      .filter((tm) => tm[2] === 'water').reduce((acc, [k, n]) => acc + n * y0[k], 0).toPrecision(17)}`).join('\n');
    // Every species of the four elements in a valence state, and the one PHREEQC's database has it in.
    const told = ['N', 'Fe', 'S', 'C'].map((el) => C.elements.find((e) => e.el === el).terms.filter((tm) => tm[2] === 'water'));
    const grid = reply({ type: 'diagram', id: 1, text, at: 'start', cell: 0, axes, pHAt });
    const items = C.couples.map((cp) => {
      const terms = C.elements.find((e) => e.el === cp.el).terms.filter((tm) => tm[2] === 'water');
      return { cp, hi: terms.filter((tm) => tm[3] === cp.hi).map(([k, n]) => [k, n]), lo: terms.filter((tm) => tm[3] === cp.lo).map(([k, n]) => [k, n]) };
    });
    const L = reply({ type: 'diagramLadder', id: 2, text, at: 'start', cell: 0, axes, pHAt, grid: grid.states,
      couples: items.map((it) => ({ hi: it.hi, lo: it.lo })) });
    // PHREEQC's amount of the element in each of the couple's states, at the rung.
    let worst = 0;
    let where = '';
    const rungs = [];
    items.forEach((it, q) => {
      for (const v of L.rungs[q].roots) {
        const name = (s) => `${it.cp.el}(${s})`;
        engine.load(dbText);
        const rows = engine.run(`SOLUTION 1\n temp ${tc}\n units mol/kgw\n pH ${pHAt}\n pe ${peOf(v).toPrecision(17)}\n${totals}\n`
          + `SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n 10 PUNCH TOT("${name(it.cp.hi)}"), TOT("${name(it.cp.lo)}")\nEND\n`);
        const [a, b] = rows[rows.length - 1].map(Number);
        const d = Math.abs(Math.log(a / b));
        if (!(d <= worst)) { worst = d; where = `${it.cp.ox.join('+')}/${it.cp.red.join('+')} at ${v.toFixed(4)}`; }
        rungs.push(`${it.cp.ox.join('+')}/${it.cp.red.join('+')} ${v.toFixed(3)}`);
      }
    });
    return { m, told, items, L, grid, worst, where, rungs };
  };
  const at25 = ladder(25, 7, [{ kind: 'pe', from: -7, to: 13.5, n: 206 }], (v) => v);
  const stateOf = (o, nm) => {
    const k = o.m.speciesNames.indexOf(nm);
    for (const terms of o.told) for (const tm of terms) if (tm[0] === k) return tm[3];
    return undefined;
  };
  const want = { 'NO3-': 5, 'NO2-': 3, N2: 0, 'NH4+': -3, NH3: -3, 'NH4SO4-': -3, 'Fe+2': 2, 'Fe+3': 3, 'Fe(OH)2+': 3, 'Fe(OH)3-': 2,
    'FeHSO4+2': 3, 'FeHSO4+': 2, FeSO4: 2, 'Fe2(OH)2+4': 3, 'SO4-2': 6, 'HS-': -2, H2S: -2, 'CO3-2': 4, 'HCO3-': 4, CO2: 4, CH4: -4,
    'FeHCO3+': 2 };
  const off = Object.entries(want).filter(([nm, s]) => at25.m.speciesNames.includes(nm) && stateOf(at25, nm) !== s);
  const untold = at25.told.flat().filter((tm) => tm[3] === null).map(([k]) => at25.m.speciesNames[k]);
  const seen = Object.keys(want).filter((nm) => at25.m.speciesNames.includes(nm)).length;
  check('a handed-off water\'s valence states, from each species\' name and its relations: every species of N, Fe, S and C in '
    + 'the water in one, the one phreeqc.dat has it in -- FeHSO4+2 Fe(3) and S(6), FeHSO4+ Fe(2), NH4SO4- N(-3) and S(6), '
    + 'Fe2(OH)2+4 Fe(3), CH4 C(-4)',
  !off.length && !untold.length && seen >= 20, `${seen} species checked${off.length ? `; off: ${off.map(([nm]) => `${nm} ${stateOf(at25, nm)}`).join(', ')}` : ''}`
    + `${untold.length ? `; untold: ${untold.join(', ')}` : ''}`);
  const names = at25.items.map((it) => `${it.cp.ox.join('+')}/${it.cp.red.join('+')}`).sort().join(' ');
  check('  its couples, phreeqc.dat\'s half-reactions with the electron in them between two valence states: nitrate to nitrite, '
    + 'nitrogen and ammonium, sulfate to sulfide, carbonate to methane, ferric to ferrous',
  names === 'CO3-2/CH4 Fe+3/Fe+2 NO3-/N2 NO3-/NH4+ NO3-/NO2- SO4-2/HS-', names);
  check('  a redox ladder at pH 7 along pe: each couple turns over once inside the water\'s own range, and at each rung PHREEQC\'s '
    + 'SOLUTION of the water at pH 7 and that pe gives the two states the same amount of the element, to 1e-8',
  !at25.grid.failed && at25.L.unsolved === 0 && at25.items.length === 6 && at25.L.rungs.every((r) => r.roots.length === 1)
    && at25.worst < 1e-8,
  `${at25.rungs.join(', ')}; the worst ${at25.worst.toExponential(1)} (${at25.where})`);
  const per40 = RtmModel.ehPerPe(313.15);
  const eh40 = ladder(40, 5, [{ kind: 'Eh', from: -5 * per40, to: 15.5 * per40, n: 206 }], (v) => v / per40);
  check('  the same water at 40 C, at pH 5 along Eh: each rung\'s pe its Eh over the volts of a pe at 40 C, PHREEQC\'s SOLUTION '
    + 'at that pH, pe and temperature gives the two states the same amount of the element, to 1e-8',
  !eh40.grid.failed && eh40.L.unsolved === 0 && eh40.items.length === 6 && eh40.L.rungs.every((r) => r.roots.length === 1)
    && eh40.worst < 1e-8
    && Math.abs(eh40.L.ehPe / per40 - 1) < 1e-15,
  `${eh40.rungs.join(', ')}; the worst ${eh40.worst.toExponential(1)} (${eh40.where})`);
}

/* ======================================================================
   THE COUPLES ACROSS A MAP, against PHREEQC: the ladder's handed-off water
   over pH 4 to 10 and pe -4 to 10.7, where water itself holds, and over Eh
   across and pH up, the other way round. Each couple's line found as a
   map's boundaries are; at each of its points PHREEQC's SOLUTION of the
   model's totals at that pH and pe gives the two valence states the same
   amount of the element.
   ====================================================================== */
function againstCouples(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const water = 'SOLUTION 1\n temp 25\n units mmol/kgw\n pH 7\n pe 10\n Na 2\n Cl 2\n N 0.2\n S 1\n C 2\n Fe 0.01\nEND\n';
  engine.load(dbText);
  const text = P.waterToModel({ engine, database, water: { name: 'redox', text: water }, activity: true, exact: true, redox: true,
    floor: 0 }).text;
  const m = RtmModel.compile(text);
  const C = m.composition;
  const y0 = m.toConcentrations(m.initialState());
  const totals = ['Na', 'Cl', 'N', 'S', 'C', 'Fe'].map((el) => ` ${el} ${C.elements.find((e) => e.el === el).terms
    .filter((tm) => tm[2] === 'water').reduce((acc, [k, n]) => acc + n * y0[k], 0).toPrecision(17)}`).join('\n');
  const reply = (msg) => { let r = null; handleRtmMessage(msg, (x) => { if (x.type !== 'progress') r = x; }); if (r.type === 'error') throw new Error(r.error); return r; };
  const items = C.couples.map((cp) => {
    const terms = C.elements.find((e) => e.el === cp.el).terms.filter((tm) => tm[2] === 'water');
    return { cp, hi: terms.filter((tm) => tm[3] === cp.hi).map(([k, n]) => [k, n]), lo: terms.filter((tm) => tm[3] === cp.lo).map(([k, n]) => [k, n]) };
  });
  const per = RtmModel.ehPerPe(298.15);
  const map = (axes, at) => {
    const grid = reply({ type: 'diagram', id: 1, text, at: 'start', cell: 0, axes });
    const R = reply({ type: 'diagramCouples', id: 2, text, at: 'start', cell: 0, axes, grid: grid.states,
      couples: items.map((it) => ({ hi: it.hi, lo: it.lo })) });
    let worst = 0;
    let where = '';
    let points = 0;
    items.forEach((it, q) => {
      const name = (s) => `${it.cp.el}(${s})`;
      for (const ln of R.couples[q].lines) {
        ln.x.forEach((x, i) => {
          const [ph, pe] = at(x, ln.y[i]);
          engine.load(dbText);
          const rows = engine.run(`SOLUTION 1\n temp 25\n units mol/kgw\n pH ${ph.toPrecision(17)}\n pe ${pe.toPrecision(17)}\n${totals}\n`
            + `SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n 10 PUNCH TOT("${name(it.cp.hi)}"), TOT("${name(it.cp.lo)}")\nEND\n`);
          const [a, b] = rows[rows.length - 1].map(Number);
          const d = Math.abs(Math.log(a / b));
          points++;
          if (!(d <= worst)) { worst = d; where = `${it.cp.ox.join('+')}/${it.cp.red.join('+')} at pH ${ph.toFixed(4)}, pe ${pe.toFixed(4)}`; }
        });
      }
    });
    const crossing = R.couples.filter((c) => c.lines.length).length;
    return { grid, R, worst, where, points, crossing, unsolved: R.couples.reduce((n, c) => n + c.unsolved, 0) };
  };
  const pePH = map([{ kind: 'pH', from: 4, to: 10, n: 13 }, { kind: 'pe', from: -4, to: 10.7, n: 11 }], (x, y) => [x, y]);
  const ehPH = map([{ kind: 'Eh', from: -4 * per, to: 10.7 * per, n: 11 }, { kind: 'pH', from: 4, to: 10, n: 13 }],
    (x, y) => [y, x / per]);
  // Over Eh the lines are found to 1e-10 V, 1.7e-9 in pe: a couple of ten electrons, NO3-/N2, is then within 4e-8.
  check('the couples across a map of pH and pe, where water itself holds: the ladder\'s handed-off water, each of its six couples '
    + 'a line across it, and at each of its points PHREEQC\'s SOLUTION of the model\'s totals at that pH and pe gives the two '
    + 'states the same amount of the element, to 1e-8; over Eh across and pH up, the other way round, the same to 1e-7, the '
    + 'lines found to 1e-10 V',
  !pePH.grid.failed && pePH.unsolved === 0 && pePH.crossing === 6 && pePH.worst < 1e-8 && pePH.points >= 60
    && !ehPH.grid.failed && ehPH.unsolved === 0 && ehPH.crossing === 6 && ehPH.worst < 1e-7 && ehPH.points >= 60,
  `pH-pe: ${pePH.points} points of ${pePH.crossing} lines, the worst ${pePH.worst.toExponential(1)} (${pePH.where}); Eh-pH: `
    + `${ehPH.points} points, the worst ${ehPH.worst.toExponential(1)} (${ehPH.where})`);
}

/* ======================================================================
   REDOX ZONES, against PHREEQC: a water with oxygen, nitrate, sulfate and
   carbonate, with pyrolusite, ferrihydrite and FeS(ppt) as its
   EQUILIBRIUM_PHASES, handed off with every species phreeqc.dat has of its
   elements; organic carbon added at a steady rate as CO3-2 + 6 H+ + 4 e-,
   against PHREEQC's REACTION adding CH2O in steps. At each step every
   valence state's total -- the model's tot(N(5)), tot(Fe(2)) and the rest
   -- is PHREEQC's TOT("N(5)"), each mineral its EQUI, and the pH and the
   pe PHREEQC's: the oxygen and the nitrate used up, the pyrolusite and the
   ferrihydrite, the sulfate reduced with FeS forming, and methane, the
   mineral events between. PHREEQC's REACTION makes water as the carbon is
   oxidised, which the page's kilogram does not count: a few parts in 1e5.
   ====================================================================== */
function againstRedoxZones(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const water = 'SOLUTION 1\n temp 25\n units mmol/kgw\n pH 6.6\n Na 1.5\n K 0.05\n Ca 0.6\n Mg 0.2\n Cl 0.6\n O(0) 0.5\n N(5) 0.15\n'
    + ' S(6) 0.3\n C(4) 2.8\nEQUILIBRIUM_PHASES 1\n Pyrolusite 0 1e-4\n Fe(OH)3(a) 0 2e-4\n FeS(ppt) 0 0\n';
  const N = 32;
  const total = 1.6e-3;
  const rate = 1e-9;
  engine.load(dbText);
  const res = P.waterToModel({ engine, database, water: { name: 'zones', text: `${water}END\n` }, activity: true, exact: true, redox: true,
    phases: true, floor: 0 });
  const text = `${RtmModel.withValue(res.text, { kind: 'setting', name: 'TEND' }, total / rate)}\n<REACTIONS>\n=> CO3-2 + 6 H+ + 4 e-, k = ${rate}\n`;
  const m = RtmModel.compile(text);
  const keys = m.quantities.filter((q) => /^tot\(.+\(.+\)\)$/.test(q.key)).map((q) => q.key);
  const states = keys.map((k) => k.slice(4, -1));
  const phases = ['Pyrolusite', 'Fe(OH)3(a)', 'FeS(ppt)'];
  engine.load(dbText);
  const pq = engine.run(`${water}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n 10 PUNCH ${states.map((s) => `TOT("${s}")`).join(', ')}\n`
    + ` 20 PUNCH ${phases.map((p) => `EQUI("${p}")`).join(', ')}, -LA("H+"), -LA("e-")\n`
    + `REACTION 1\n CH2O 1\n ${total} moles in ${N} steps\nINCREMENTAL_REACTIONS true\nEND\n`).map((r) => r.map(Number)).slice(-N);
  const times = Array.from({ length: N }, (_, i) => ((i + 1) * total) / N / rate);
  const run = FacsimileODE.runModel(m, { solver: 'ndf', tend: times[N - 1], rtol: 1e-10, atol: 1e-22, breaks: times });
  const qi = Int32Array.from([...keys, 'pH', 'pe'].map((k) => m.quantities.findIndex((q) => q.key === k)));
  const out = new Float64Array(qi.length);
  const elTot = (y, el) => m.composition.elements.find((e) => e.el === el).terms.reduce((a, [k, n]) => a + n * y[k], 0);
  const d = { tot: 0, where: '', mineral: 0, pH: 0, pe: 0 };
  for (let i = 0; i < N; i++) {
    const k = run.t.findIndex((t) => Math.abs(t - times[i]) <= 1e-9 * times[i]);
    const y = Float64Array.from(m.toConcentrations(run.y[k], run.t[k]));
    m.quantitiesAt(y, run.t[k], 0, qi, out);
    states.forEach((s, j) => {
      const off = Math.abs(out[j] - pq[i][j]) / elTot(y, s.split('(')[0]);
      if (off > d.tot) { d.tot = off; d.where = `${s} at step ${i + 1}`; }
    });
    phases.forEach((p, j) => { d.mineral = Math.max(d.mineral, Math.abs(y[m.speciesNames.indexOf(p)] - pq[i][states.length + j])); });
    d.pH = Math.max(d.pH, Math.abs(out[keys.length] - pq[i][states.length + 3]));
    d.pe = Math.max(d.pe, Math.abs(out[keys.length + 1] - pq[i][states.length + 4]));
  }
  const at = (step, s) => pq[step - 1][states.indexOf(s)];
  const minAt = (step, p) => pq[step - 1][states.length + phases.indexOf(p)];
  // The zones as PHREEQC has them: the nitrate gone by the tenth step, the pyrolusite and the ferrihydrite then, FeS
  // forming as the sulfate is reduced, and methane at the end.
  const zones = at(10, 'N(5)') < 1e-12 && at(10, 'Mn(2)') > 0.99e-4 && minAt(11, 'Fe(OH)3(a)') === 0 && at(11, 'Fe(2)') > 1.99e-4
    && minAt(24, 'FeS(ppt)') > 1.9e-4 && at(32, 'S(-2)') > 9e-5 && at(32, 'C(-4)') > 1e-4;
  check('redox zones: a handed-off water with pyrolusite, ferrihydrite and FeS(ppt), organic carbon added at a steady rate as '
    + 'CO3-2 + 6 H+ + 4 e-, against PHREEQC\'s REACTION adding CH2O in 32 steps: at each, every valence state\'s total within '
    + '3e-5 of its element\'s, the minerals within 1e-8 mol/kgw, the pH within 2e-6 and the pe within 1e-3 -- the oxygen and the '
    + 'nitrate used up, the pyrolusite and the ferrihydrite, the sulfate reduced with FeS forming, then methane',
  keys.length === 12 && run.events && run.events.length === 3 && zones && d.tot < 3e-5 && d.mineral < 1e-8 && d.pH < 2e-6 && d.pe < 1e-3,
  `${keys.length} valence totals, ${run.events ? run.events.length : 0} events; the worst ${d.tot.toExponential(1)} of the element `
    + `(${d.where}), minerals ${d.mineral.toExponential(1)}, pH ${d.pH.toExponential(1)}, pe ${d.pe.toExponential(1)}`);
}

/* ======================================================================
   INVERSE MODELS, through PHREEQC: its INVERSE_MODELING between waters of a
   run (viewRun's `only` and `inverse`), read back from what it prints.
   ====================================================================== */
function againstInverse(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const solver = { method: 'ndf', rtol: 1e-10, atol: 1e-20, nonNegative: true, stagnationTol: 0.5 };
  const runOf = (text) => {
    let res = null;
    handleRtmMessage({ type: 'run', id: 1, text, solver }, (m) => { if (m.type === 'result' || m.type === 'error') res = m; });
    if (res.type === 'error') throw new Error(res.error);
    return { t: res.t, states: res.states, n: res.n, width: res.width, model: res.model };
  };
  // A handed-off water whose calcium and carbonate come in at 1e-8 mol/kgw a second for a day: 8.64e-4 mol of calcite.
  const water = 'SOLUTION 1\n units mmol/kgw\n pH 7 charge\n Na 1\n Cl 1\n Ca 0.5\n C(4) 2\n S(6) 0.2\nEND\n';
  engine.load(dbText);
  const handed = P.waterToModel({ engine, database, water: { name: 'w', text: water }, activity: true, exact: true, redox: false });
  let text = RtmModel.withValue(handed.text, { kind: 'setting', name: 'TEND' }, 86400);
  text = /^<REACTIONS>\s*$/m.test(text) ? text.replace(/^<REACTIONS>\s*$/m, '<REACTIONS>\n=> Ca+2 + CO3-2, r = 1e-8')
    : `${text}\n<REACTIONS>\n=> Ca+2 + CO3-2, r = 1e-8\n`;
  const run = runOf(text);
  engine.load(dbText);
  const v = P.viewRun({ engine, database, run, modelText: text,
    only: [{ cell: 0, k: 0, label: 'as it starts' }, { cell: 0, k: run.n - 1, label: 'as the run ends' }],
    inverse: { phases: ['Calcite', 'CO2(g)', 'Gypsum'], uncertainty: 0.05, range: true, minimal: true } }).inverse;
  const m0 = v.models[0];
  const cal = m0 && m0.phases.find((ph) => ph.name === 'Calcite');
  check('an inverse model between a run\'s start and its end: the calcite its reaction dissolved, 1e-8 mol/kgw a second '
    + 'for a day, to the four figures PHREEQC prints (8.640e-4), alone in the one minimal model, with its range at 5 %; '
    + 'the solutions as the run had them, the elements of the waters balanced',
  v.models.length === 1 && v.found === 1 && m0.minimal && m0.phases.length === 1 && !!cal && cal.value === 8.64e-4
    && cal.min < cal.value && cal.max > cal.value && m0.fractions.every((f) => f.value === 1)
    && m0.solutions.map((s) => s.description).join('|') === 'as it starts|as the run ends'
    && v.balances.join(' ') === 'C Ca Cl Na S' && Math.abs(v.waters[1].pH - 6.9517) < 1e-3,
  cal ? `Calcite ${cal.value} (${cal.min} to ${cal.max}), ${v.found} model${v.found === 1 ? '' : 's'}, `
    + `${v.calls} calls of cl1; balanced ${v.balances.join(', ')}` : JSON.stringify(v.models).slice(0, 200));

  // PHREEQC's own waters: the second the first with calcite and gypsum dissolved by REACTION, read back from what it prints.
  engine.load(dbText);
  const printed = engine.printed('SOLUTION 1\n units mmol/kgw\n pH 7.2 charge\n Na 1\n Cl 1\n C(4) 1\n Ca 0.2\n S(6) 0.1\n'
    + 'REACTION 1\n Calcite 1\n Gypsum 0.5\n 1e-3 moles\nSAVE solution 2\nEND\nINVERSE_MODELING 1\n -solutions 1 2\n'
    + ' -uncertainty 0.05\n -range true\n -minimal true\n -phases\n  Calcite\n  Gypsum\n  CO2(g)\n  Halite\n'
    + ' -balances\n  Na\n  Cl\nEND\n');
  const r2 = P.readInverse(printed, ['Calcite', 'Gypsum', 'CO2(g)', 'Halite']);
  const two = r2.models[0];
  const val = (nm) => (two.phases.find((ph) => ph.name === nm) || {}).value;
  check('  PHREEQC\'s own waters, the second the first with 1 mmol of calcite and 0.5 of gypsum dissolved: read back from '
    + 'what it prints, those two and no more, their ranges, the summary\'s counts',
  r2.models.length === 1 && r2.found === 1 && r2.minimalFound === 1 && two.minimal && two.phases.length === 2
    && val('Calcite') === 1e-3 && val('Gypsum') === 5e-4 && two.phases.every((ph) => ph.min < ph.value && ph.max > ph.value)
    && two.solutions.length === 2 && two.solutions[1].balances.some((b) => b.name === 'Ca' && b.input === 1.7e-3)
    && Number.isFinite(two.residuals) && r2.calls > 0,
  `${two ? two.phases.map((ph) => `${ph.name} ${ph.value} (${ph.min} to ${ph.max})`).join(', ') : 'none'}; `
    + `${r2.found} found, ${r2.minimalFound} minimal, ${r2.infeasible} infeasible sets, ${r2.calls} calls of cl1`);

  // What flows in, given whole: a column flushed many times over is that water at its far end, and needs no phase.
  const column = `${handed.text.replace(/^MODE = batch$/m, 'MODE = transport\nCELLS = 2\nLENGTH = 0.1\nVELOCITY = 1e-4\n'
    + 'ADVECTION = 1\nLEFT = robin\nRIGHT = free').replace(/^TEND = .*$/m, 'TEND = 1e5')}`;
  const flushed = runOf(column);
  engine.load(dbText);
  const vin = P.viewRun({ engine, database, run: flushed, modelText: column,
    only: [{ state: Array.from(flushed.model.inflow), label: 'the water flowing in' }, { cell: 1, k: flushed.n - 1, label: 'cell 1 at the end' }],
    inverse: { phases: ['Calcite'], uncertainty: 1e-6, range: false, minimal: true } }).inverse;
  const mi = vin.models[0];
  check('  what flows in, given whole: a column flushed a hundred times over is that water at its far end -- a minimal model '
    + 'of no phase at 1e-6, every total adjusted by less than 1e-12',
  vin.models.length === 1 && mi.minimal && mi.phases.length === 0 && mi.solutions[0].description === 'the water flowing in'
    && mi.solutions.every((s) => s.balances.every((b) => Math.abs(b.delta) < 1e-12)),
  mi ? `${mi.phases.length} phases; deltas up to ${Math.max(...mi.solutions.flatMap((s) => s.balances.map((b) => Math.abs(b.delta))))
    .toExponential(1)}` : 'no model');

  // The example of it: water with CO2 through calcite and gypsum, written from PHREEQC and flushed for ten pore volumes.
  const { RTM_EXAMPLES } = require(path.join(jsDir, 'rtm-examples.js'));
  const exText = RTM_EXAMPLES.find((x) => x.id === 'inversecolumn').text;
  const exRun = runOf(exText);
  const exModel = RtmModel.compile(exText);
  const ns = exModel.speciesNames.length;
  const last = exModel.cells - 1;
  const outlet = exRun.states.slice((exRun.n - 1) * exRun.width + last * ns, (exRun.n - 1) * exRun.width + (last + 1) * ns);
  const totalOf = (state, el) => exModel.composition.elements.find((e) => e.el === el).terms.filter((tm) => tm[2] === 'water')
    .reduce((sum, [k, n]) => sum + n * state[k], 0);
  const dC = totalOf(outlet, 'C') - totalOf(exRun.model.inflow, 'C');
  const dS = totalOf(outlet, 'S') - totalOf(exRun.model.inflow, 'S');
  engine.load(dbText);
  const exInv = P.viewRun({ engine, database, run: exRun, modelText: exText,
    only: [{ state: Array.from(exRun.model.inflow), label: 'the water flowing in' }, { cell: last, k: exRun.n - 1, label: 'the outlet' }],
    inverse: { phases: ['Calcite', 'Gypsum'], uncertainty: 0.05, range: true, minimal: true } }).inverse;
  const exM = exInv.models[0];
  const exVal = (nm) => (exM && exM.phases.find((ph) => ph.name === nm) || {}).value;
  check('  the example of it, water with CO2 through calcite and gypsum: PHREEQC\'s model the calcite and the gypsum the '
    + 'column dissolved, the outlet\'s carbon and sulfur over the inflow\'s, to the four figures it prints; no water taken '
    + 'from the minerals, the fractions one', exInv.models.length === 1 && Math.abs(exVal('Calcite') / dC - 1) < 5e-4
    && Math.abs(exVal('Gypsum') / dS - 1) < 5e-4 && exM.fractions.every((f) => f.value === 1) && exM.residuals < 1e-5,
  `Calcite ${exVal('Calcite')} for ${dC.toPrecision(6)}, Gypsum ${exVal('Gypsum')} for ${dS.toPrecision(6)}, residuals ${exM && exM.residuals}`);

  const refused = [];
  for (const [what, inverse, re] of [
    ['a phase the database does not have', { phases: ['Calcitee'] }, /The database has no phase Calcitee\./],
    ['an uncertainty of 1 or more', { phases: ['Calcite'], uncertainty: 1 }, /The uncertainty is a fraction of each total/],
    ['a phase going a third way', { phases: ['Calcite sideways'] }, /may be followed by dissolve or precipitate/],
  ]) {
    let msg = '';
    try {
      engine.load(dbText);
      P.viewRun({ engine, database, run, modelText: text, only: [{ cell: 0, k: 0 }, { cell: 0, k: run.n - 1 }], inverse });
    } catch (e) { msg = e.message; }
    if (!re.test(msg)) refused.push(`${what}: "${msg}"`);
  }
  check('  and refused, each with its reason: a phase the database does not have, an uncertainty of 1 or more, a phase '
    + 'going a third way', !refused.length, refused.join(' | '));
}

/* ======================================================================
   FITTING, against PHREEQC: zinc on a ferrihydrite's weak sites, titrated
   with acid -- PHREEQC's REACTION, the HCl added at each time measured --
   and the dissolved zinc it gives taken as what was measured; the handed-off
   model, its weak sites' log K for zinc moved off by a unit, fitted back to
   it by the Fit tab's computation. It finds the database's log K.
   ====================================================================== */
function againstFit(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const water = 'SOLUTION 1\n units mmol/kgw\n pH 8\n Na 10\n Cl 10 charge\n Zn 0.01\nSURFACE 1\n -equilibrate 1\n -no_edl\n'
    + ' Hfo_wOH 2e-4 600 0.09\nEND\n';
  engine.load(dbText);
  const res = P.waterToModel({ engine, database, water: { name: 'zinc on ferrihydrite', text: water }, activity: true, exact: true,
    redox: false });
  // The acid at 1e-8 mol/kgw a second for a day, 0.864 mmol in all, as the page adds it and as PHREEQC's REACTION does.
  const rate = 1e-8;
  const tend = 86400;
  let text = RtmModel.withValue(res.text, { kind: 'setting', name: 'TEND' }, tend);
  text = /^<REACTIONS>\s*$/m.test(text) ? text.replace(/^<REACTIONS>\s*$/m, `<REACTIONS>\n=> H+ + Cl-, r = ${rate}`)
    : `${text}\n<REACTIONS>\n=> H+ + Cl-, r = ${rate}\n`;
  const times = [8640, 17280, 25920, 34560, 43200, 51840, 60480, 69120, 77760, 86400];
  const measured = times.map((t) => {
    engine.load(dbText);
    const rows = engine.run(`${water.replace('END\n', '')}REACTION 1\n HCl 1\n ${(rate * t).toPrecision(12)} moles\n`
      + 'SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n 10 PUNCH TOT("Zn"), -LA("H+")\nEND\n');
    return rows[rows.length - 1].map(Number);
  });
  const lk = RtmModel.tunables(text).find((x) => x.kind === 'logK' && x.name.includes('Hfo_wOZn+'));
  const withData = `${text}\n<DATA>\ntime  tot(Zn)  cell = 0\n${times.map((t, i) => `${t} ${measured[i][0]}`).join('\n')}\n`;
  let reply = null;
  handleRtmMessage({ type: 'fit', id: 1, text: withData, solver: { method: 'ndf', rtol: 1e-10, atol: 1e-20, nonNegative: true,
    stagnationTol: 0.5 }, params: [{ kind: 'logK', name: lk.name, start: lk.value + 1 }] },
  (m) => { if (m.type !== 'progress') reply = m; });
  const got = reply.type === 'fit' ? reply.params[0] : null;
  check('a fit against PHREEQC: zinc on ferrihydrite\'s weak sites titrated with acid, PHREEQC\'s dissolved zinc as what was '
    + 'measured, the weak sites\' log K for zinc moved off by a unit and fitted back -- the database\'s, within its standard '
    + 'error and to 1e-6', !!got && Math.abs(got.value - lk.value) < 1e-6 && got.se !== null && Math.abs(got.value - lk.value) < 3 * got.se + 1e-9,
  got ? `${lk.name}: log K ${got.value.toFixed(9)} for ${lk.value} in ${reply.runs} runs, standard error ${got.se.toExponential(1)}, `
    + `pH ${measured[0][1].toFixed(2)} to ${measured[measured.length - 1][1].toFixed(2)}, the misfit's sd ${reply.sd.toExponential(1)}`
    : reply.error);
}

/* ======================================================================
   CONDUCTANCE, against PHREEQC: the specific conductance, the density and
   the viscosity of a handed-off water, worked out by the model from
   <CONDUCTANCE> and <VOLUMES> as PHREEQC works them out (calc_SC,
   calc_dens, viscosity), against PHREEQC's SC, RHO and VISCOS: dilute
   salt, a carbonate water, a brackish water at 50 C, and sulfate without
   chloride, whose viscosity takes the sulfate's volume against Cl-'s
   (calc_vm_Cl); and a water titrated with acid, the run's end against
   PHREEQC's REACTION.
   ====================================================================== */
function againstConductance(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const keys = ['SC', 'rho', 'viscos'];
  const at = (text, c) => {
    const m = RtmModel.compile(text);
    const which = Int32Array.from(keys.map((k) => m.quantities.findIndex((q) => q.key === k)));
    if ([...which].some((x) => x < 0)) return null;
    const out = new Float64Array(keys.length);
    m.quantitiesAt(c || (m.toConcentrations ? m.toConcentrations(m.initialState()) : m.initialState()), 0, 0, which, out);
    return { m, out };
  };
  const pqOf = (text, db = dbText) => {
    engine.load(db);
    const rows = engine.run(`${text.replace(/END\n$/, '')}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n`
      + ' 10 PUNCH SC, RHO, VISCOS, TOT("water")\nEND\n');
    return rows[rows.length - 1].map(Number);
  };
  const waters = [
    ['NaCl 10 mM', 'SOLUTION 1\n units mmol/kgw\n pH 7\n Na 10\n Cl 10 charge\nEND\n'],
    ['a carbonate water', 'SOLUTION 1\n units mmol/kgw\n pH 7.5\n Na 5\n Ca 2\n Mg 1\n Cl 6 charge\n C(4) 4\n S(6) 1\nEND\n'],
    ['brackish at 50 C', 'SOLUTION 1\n temp 50\n units mmol/kgw\n pH 7.8\n Na 200\n K 5\n Ca 10\n Mg 25\n Cl 250 charge\n S(6) 15\n'
      + ' C(4) 2\nEND\n'],
    ['sulfate without chloride', 'SOLUTION 1\n units mmol/kgw\n pH 7\n Na 20 charge\n Mg 3\n S(6) 12\nEND\n'],
  ];
  const results = waters.map(([label, text]) => {
    engine.load(dbText);
    const res = P.waterToModel({ engine, database, water: { name: label, text }, activity: true, exact: true, redox: false });
    const got = at(res.text);
    if (!got) return { label, worst: Infinity, why: 'no SC' };
    const pq = pqOf(text);
    const rel = keys.map((k, i) => Math.abs(got.out[i] / pq[i] - 1));
    return { label, worst: Math.max(...rel), sc: got.out[0], cond: /^<CONDUCTANCE>$/m.test(res.text),
      clVm: /^Cl-\s+vm /m.test(res.text) };
  });
  // The same under SIT and under Pitzer, the coefficients this file gives them, PHREEQC's convergence tightened.
  const mixed = `${KNOBS}SOLUTION 1\n units mmol/kgw\n pH 7.5\n Na 50\n K 5\n Ca 10\n Mg 5\n Cl 80 charge\n S(6) 5\n C(4) 2\nEND\n`;
  const others = [['sit', `${SIT_OWN}${dbText}`], ['pitzer', `${PITZER_OWN()}${dbText}`]].map(([label, db]) => {
    engine.load(db);
    const res = P.waterToModel({ engine, database: { name: label, text: db }, water: { name: label, text: mixed }, activity: true,
      exact: true, redox: false });
    const got = at(res.text);
    if (!got) return { label, worst: Infinity };
    const pq = pqOf(mixed, db);
    return { label, worst: Math.max(...keys.map((k, i) => Math.abs(got.out[i] / pq[i] - 1))),
      kind: new RegExp(`^ACTIVITY = ${label}$`, 'm').test(res.text) };
  });
  // Acid into the dilute salt at 1e-8 mol/kgw a second for a day, its pH from 7 to 3.1: the run's end against PHREEQC's
  // REACTION of the same. (Acid into a carbonate water makes water, CO2 from HCO3-, which PHREEQC's kilogram of water takes
  // and the page's does not, 1.5e-5 kg of it in a day; into salt, 2e-9 kg, from OH-.)
  const salt = waters[0][1];
  engine.load(dbText);
  const r2 = P.waterToModel({ engine, database, water: { name: 'titrated', text: salt }, activity: true, exact: true, redox: false });
  const titr = `${RtmModel.withValue(r2.text, { kind: 'setting', name: 'TEND' }, 86400).replace(/^<REACTIONS>\s*$/m,
    '<REACTIONS>\n=> H+ + Cl-, r = 1e-8')}`;
  const mt = RtmModel.compile(titr);
  const run = FacsimileODE.runModel(mt, { solver: 'ndf', tend: 86400, rtol: 1e-10, atol: 1e-20, nonNegative: true, maxPoints: 4,
    stagnationTol: 0.5 });
  const cEnd = mt.toConcentrations(run.y[run.y.length - 1], 86400);
  const endOut = at(titr, cEnd);
  const pqEnd = pqOf(`${KNOBS}${salt.replace('END\n', '')}REACTION 1\n HCl 1\n ${(1e-8 * 86400).toPrecision(12)} moles\nEND\n`);
  const runWorst = Math.max(...keys.map((k, i) => Math.abs(endOut.out[i] / pqEnd[i] - 1)));
  check('the specific conductance, the density and the viscosity of a handed-off water, worked out by the model as PHREEQC '
    + 'works them out, against its SC, RHO and VISCOS: dilute salt, a carbonate water, brackish water at 50 C, sulfate '
    + 'without chloride (Cl-\'s volume from its -Vm); a mixed water under SIT and under Pitzer; and acid into the salt at '
    + 'the run\'s end against REACTION',
  results.every((x) => x.worst < 1e-12 && x.cond) && results[3].clVm && others.every((x) => x.worst < 1e-9 && x.kind)
    && runWorst < 1e-8 && endOut.out[0] > 1.25 * results[0].sc,
  `${results.map((x) => `${x.label} ${x.worst.toExponential(1)} (SC ${x.sc ? x.sc.toPrecision(6) : '-'} uS/cm)`).join(', ')}; `
    + `${others.map((x) => `${x.label} ${x.worst.toExponential(1)}`).join(', ')}; acid ${runWorst.toExponential(1)} `
    + `(SC ${endOut.out[0].toPrecision(6)} for ${pqEnd[0].toPrecision(6)}, PHREEQC's water ${(pqEnd[3] - 1).toExponential(1)} kg more)`);
}

/* ======================================================================
   MULTICOMPONENT DIFFUSION (-multi_D): each species at its Dw times the
   porosity to the n, the ions coupled so that no current flows, each down
   its activity. Against PHREEQC's TRANSPORT as its explicit steps are made
   smaller -- its runs at 10 and 40 mixing steps to a shift, extrapolated,
   their error being first order in the step -- with closed ends, the ends
   held at pure water and at dilute salt, and the exponent 2; its implicit
   scheme, which takes each species down its concentration; each Dw at 40 C
   as DIFF_C has it; a flowing column with an exchanger; a tracer level
   across a salinity gradient, where PHREEQC drops the factor the page holds
   at its bound; and a hundred days with pure water held at both ends, which
   PHREEQC's rule as it is written stalls an implicit solver on.
   ====================================================================== */
function againstMultiD(engine) {
  // PHREEQC keeps a TRANSPORT's options for the next one in the same instance: each input here says -implicit and -stagnant.
  const database = { name: 'phreeqc.dat', text: dbText };
  const handOff = (name, text) => {
    engine.load(dbText);
    return P.waterToModel({ engine, database, water: { name, text }, activity: true, exact: true, redox: false });
  };
  const db = P.readDatabase(dbText);
  // HCl against NaCl in ten cells of 2 mm, five hours of diffusion.
  const acid = (o = {}) => `SOLUTION 0\n units mmol/kgw\n pH 7 charge${o.end || ''}\nSOLUTION 11\n units mmol/kgw\n`
    + ` pH 7 charge${o.end || ''}\nSOLUTION 1-5\n units mmol/kgw\n pH 2 charge\n Cl 10\nSOLUTION 6-10\n units mmol/kgw\n`
    + ` pH 7 charge\n Na 10\n Cl 10\nEND\nTRANSPORT\n -cells 10\n -shifts 5\n -time_step 3600 ${o.sub || 1}\n -lengths 0.002\n`
    + ` -boundary_conditions ${o.bc || 'closed closed'}\n -flow_direction diffusion_only\n -multi_D true 1e-9 0.3 0 ${o.n || 1}\n`
    + ` -implicit ${o.implicit ? 'true' : 'false'}\n -stagnant 0\n -punch_cells 1-10\n -punch_frequency 1\nEND\n`;
  const els = ['Na', 'Cl', 'Br'];
  // PHREEQC's cells 1 to n at its last shift: [pH, Na, Cl, Br] a cell.
  const pqLast = (text, n) => {
    const at = text.search(/^TRANSPORT\b/m);
    engine.load(dbText);
    const rows = engine.run(`${text.slice(0, at)}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings cell time pH Na Cl Br\n`
      + ` -start\n10 PUNCH CELL_NO, TOTAL_TIME, -LA("H+"), TOT("Na"), TOT("Cl"), TOT("Br")\n -end\n${text.slice(at)}`).slice(1);
    const t = Math.max(...rows.map((r) => Number(r[1])));
    const out = [];
    for (const r of rows) if (Number(r[1]) === t && r[0] >= 1 && r[0] <= n) out[r[0] - 1] = r.slice(2, 6).map(Number);
    return out;
  };
  // Each species' count of an element, as PHREEQC's TOT has it.
  const counts = (m, res, el) => {
    const back = new Map([...res.names].map(([k, nm]) => [nm, k]));
    return m.speciesNames.map((nm) => {
      if (!back.has(nm)) return 0;
      const ex = db.expand(back.get(nm));
      return ex.has(el) ? ex.get(el) : 0;
    });
  };
  // The page's at tend, the same; and its solver's counts.
  const pageAt = (res, tend, n) => {
    const m = RtmModel.compile(res.text);
    const run = FacsimileODE.runModel(m, { solver: 'ndf', tend, rtol: 1e-8, atol: 1e-20, nonNegative: true, outputTimes: [tend] });
    const c = m.toConcentrations(run.grid.y[0]);
    const ns = m.speciesNames.length;
    const iH = m.speciesNames.indexOf('H+');
    const of = els.map((el) => counts(m, res, el));
    const lnG = new Float64Array(ns);
    const out = [];
    for (let i = 0; i < n; i++) {
      const b = i * (m.stride || 1) * ns;
      RtmModel.activityAt(m.act, c, b, lnG, new Float64Array(ns));
      out.push([-(Math.log(c[b + iH]) + lnG[iH]) / Math.LN10,
        ...of.map((x) => x.reduce((acc, k, s) => acc + (k ? k * c[b + s] : 0), 0))]);
    }
    return { out, stats: run.stats };
  };
  // Worst page against PHREEQC; with two PHREEQC runs, against (4 x40 - x10)/3.
  const against = (page, pq40, pq10) => {
    const w = [0, 0, 0, 0];
    page.forEach((row, i) => row.forEach((v, j) => {
      const ref = pq10 ? (4 * pq40[i][j] - pq10[i][j]) / 3 : pq40[i][j];
      w[j] = Math.max(w[j], Math.abs(v - ref));
    }));
    return { pH: w[0], Na: w[1], Cl: w[2], Br: w[3] };
  };
  const say = (w, keys = ['Na', 'Cl']) => `${keys.map((k) => `${k} ${w[k].toExponential(1)}`).join(', ')} mol/kgw, pH `
    + `${w.pH.toExponential(1)}`;

  // What is written.
  const closed = handOff('acid against salt', acid());
  const lineOf = (text, name) => (new RegExp(`^${name.replace(/[+]/g, '\\+')}\\s.*$`, 'm').exec(text) || [''])[0];
  const md = closed.report.transport && closed.report.transport.multiD;
  check('-multi_D: DIFFUSION = nernst-planck and DIFFUSION_GRADIENT = activity, each species its Dw times the porosity '
    + 'to the n -- H+ 9.31e-9, HCl without -dw -multi_D\'s 1e-9 -- and reported', /^DIFFUSION = nernst-planck$/m.test(closed.text)
    && /^DIFFUSION_GRADIENT = activity$/m.test(closed.text) && /\bD=2\.793e-9\b/.test(lineOf(closed.text, 'H+'))
    && /\bD=3e-10\b/.test(lineOf(closed.text, 'HCl')) && !!md && md.porosity === 0.3 && md.n === 1
    && md.gradient === 'activity' && md.withoutDw.includes('HCl'),
  `${lineOf(closed.text, 'H+')} | ${lineOf(closed.text, 'HCl')} | ${JSON.stringify(md)}`);

  // At 40 C, as DIFF_C has each Dw there.
  const warm = handOff('acid against salt at 40 C', acid().replace(/ units mmol\/kgw\n/g, ' units mmol/kgw\n temp 40\n'));
  engine.load(dbText);
  const dc = engine.run('SOLUTION 1\n temp 40\n units mmol/kgw\n pH 7 charge\n Na 10\n Cl 10\nSELECTED_OUTPUT 99\n -reset false\n'
    + 'USER_PUNCH 99\n -headings Na Cl H v0\n 10 PUNCH DIFF_C("Na+"), DIFF_C("Cl-"), DIFF_C("H+"), VISCOS_0\nEND\n')[1].map(Number);
  const dOf = (text, name) => Number((/\bD=(\S+)/.exec(lineOf(text, name)) || [])[1]);
  const wantD = { 'Na+': 0.3 * dc[0], 'Cl-': 0.3 * dc[1], 'H+': 0.3 * dc[2], HCl: (0.3 * 1e-9 * 0.8900239182946) / dc[3] };
  const offD = Object.entries(wantD).map(([n, v]) => Math.abs(dOf(warm.text, n) / v - 1));
  check('  at 40 C each D is DIFF_C there times the porosity -- the viscosity of water and the species\' own dw_t -- and '
    + 'for one without -dw -multi_D\'s, the viscosity alone', Math.max(...offD) < 1e-9
    && dOf(warm.text, 'Na+') / dOf(closed.text, 'Na+') > 1.2,
  Object.keys(wantD).map((n, i) => `${n} ${dOf(warm.text, n).toExponential(6)} (${offD[i].toExponential(1)})`).join(', '));

  // Against TRANSPORT made ever finer in time.
  const pqClosed = [pqLast(acid({ sub: 40 }), 10), pqLast(acid({ sub: 10 }), 10)];
  const cases = [
    { name: 'closed', o: {}, res: closed, pq: pqClosed, tol: [2e-8, 3e-6] },
    { name: 'pure water held at both ends', o: { bc: 'constant constant' }, tol: [6e-7, 1.2e-4] },
    { name: 'dilute salt held there', o: { bc: 'constant constant', end: '\n Na 1\n Cl 1' }, tol: [1.2e-6, 1.5e-4] },
    { name: 'the exponent 2', o: { n: 2 }, tol: [5e-8, 3e-5] },
  ].map((cs) => {
    const res = cs.res || handOff(cs.name, acid(cs.o));
    const pq = cs.pq || [pqLast(acid({ ...cs.o, sub: 40 }), 10), pqLast(acid({ ...cs.o, sub: 10 }), 10)];
    const w = against(pageAt(res, 18000, 10).out, ...pq);
    return { ...cs, res, w, ok: w.Na <= cs.tol[0] && w.Cl <= cs.tol[0] && w.pH <= cs.tol[1] };
  });
  check('  HCl against NaCl in ten cells for five hours, against TRANSPORT as its steps are made smaller (10 and 40 to a shift, '
    + 'extrapolated): closed, pure water held at both ends, dilute salt there (where PHREEQC drops its factor), the exponent 2',
  cases.every((x) => x.ok), cases.map((x) => `${x.name}: ${say(x.w)}`).join('; '));

  // PHREEQC's implicit scheme: each species down its concentration.
  const imp = handOff('implicit', acid({ implicit: true }));
  const pqImp = pqLast(acid({ implicit: true, sub: 160 }), 10);
  const wImp = against(pageAt(imp, 18000, 10).out, pqImp);
  const wOwn = against(pqImp, ...pqClosed);
  check('  -implicit: written without DIFFUSION_GRADIENT, each species down its concentration as PHREEQC\'s implicit scheme '
    + 'takes it, against its runs at 160 steps to a shift -- which go their own way from its explicit ones',
  !/DIFFUSION_GRADIENT/.test(imp.text) && imp.report.transport.multiD.implicit === true && wImp.Na < 3e-6 && wImp.Cl < 1.5e-6
    && wImp.pH < 1e-3 && wOwn.Na > 2 * wImp.Na && wOwn.pH > 2 * wImp.pH,
  `${say(wImp)}; PHREEQC's implicit from its explicit: ${say(wOwn)}`);

  // A hundred days with pure water held at both ends.
  const long = RtmModel.compile(cases[1].res.text.replace(/^TEND = .*$/m, 'TEND = 8640000'));
  const t0 = Date.now();
  const runLong = FacsimileODE.runModel(long, { solver: 'ndf', tend: 8640000, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  check('  a hundred days with pure water held at both ends goes through: the factor held at its bounds, where PHREEQC\'s, '
    + 'dropped to 1 beyond them, stalls an implicit solver at 54 hours', runLong.stats.nsteps < 20000,
  `${runLong.stats.nsteps} steps, ${Date.now() - t0} ms`);

  // A column with an exchanger, flushed: the effluent, PHREEQC's after shift k against the page's half a step later.
  const flow = (N) => `SOLUTION 0\n units mmol/kgw\n pH 7 charge\n Ca 0.6\n Cl 1.2\nSOLUTION 1-${N}\n units mmol/kgw\n`
    + ` pH 7 charge\n Na 1.0\n K 0.2\n N(5) 1.2\nEXCHANGE 1-${N}\n -equilibrate 1\n X 0.0011\nEND\nTRANSPORT\n -cells ${N}\n`
    + ` -lengths ${0.08 / N}\n -shifts ${2.5 * N}\n -time_step ${(720 * 40) / N}\n -flow_direction forward\n`
    + ` -boundary_conditions flux flux\n -dispersivities 0.002\n -correct_disp true\n -multi_D true 1e-9 0.3 0 1\n`
    + ` -implicit false\n -stagnant 0\n -punch_cells ${N}\n -punch_frequency 1\nEND\n`;
  const effluent = (text, res, elsF) => {
    const t = P.readTransport(text);
    const at = text.search(/^TRANSPORT\b/m);
    engine.load(dbText);
    const rows = engine.run(`${text.slice(0, at)}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings cell time `
      + `${elsF.join(' ')}\n -start\n10 PUNCH CELL_NO, TOTAL_TIME, ${elsF.map((el) => `TOT("${el}")`).join(', ')}\n -end\n`
      + `${text.slice(at)}`).slice(1);
    const pq = new Map();
    for (const r of rows) if (Number(r[1]) > 0 && Number(r[0]) === t.cells) pq.set(Math.round(Number(r[1]) / t.dt), r.slice(2).map(Number));
    const m = RtmModel.compile(res.text);
    const run = FacsimileODE.runModel(m, { solver: 'ndf', tend: (t.shifts + 0.5) * t.dt, rtol: 1e-7, atol: 1e-20, nonNegative: true,
      outputTimes: Array.from({ length: t.shifts }, (_, k) => (k + 1.5) * t.dt) });
    const ns = m.speciesNames.length;
    const of = elsF.map((el) => counts(m, res, el));
    const worst = elsF.map(() => 0);
    for (let k = 1; k <= t.shifts; k++) {
      const c = m.toConcentrations(run.grid.y[k - 1]);
      const b = (t.cells - 1) * (m.stride || 1) * ns;
      of.forEach((x, j) => {
        const tot = x.reduce((acc, n, s) => acc + (n ? n * c[b + s] : 0), 0);
        worst[j] = Math.max(worst[j], Math.abs(tot - pq.get(k)[j]));
      });
    }
    return Object.fromEntries(elsF.map((el, j) => [el, worst[j]]));
  };
  const fl = [20, 40].map((N) => ({ N, w: effluent(flow(N), handOff('flowing', flow(N)), ['Na', 'K', 'Ca', 'Cl']) }));
  const [f20, f40] = fl.map((x) => x.w);
  check('  a column with an exchanger flushed with calcium chloride, -multi_D beside the dispersivity: the effluent against '
    + 'TRANSPORT, nearer on 40 cells than on 20', f40.Na < 0.025e-3 && f40.K < 0.035e-3 && f40.Ca < 0.02e-3 && f40.Cl < 0.006e-3
    && ['Na', 'K', 'Ca', 'Cl'].every((el) => f40[el] < f20[el]),
  fl.map((x) => `${x.N} cells: ${Object.entries(x.w).map(([k, v]) => `${k} ${(v * 1e3).toFixed(4)}`).join(', ')} mmol/kgw`)
    .join('; '));

  // A tracer level across sea-strength salt held at one end and fresh water at the other.
  const salt = 'SOLUTION 0\n units mmol/kgw\n pH 7 charge\n Na 500\n Cl 500\n Br 1\nSOLUTION 1-11\n units mmol/kgw\n pH 7 charge\n'
    + ' Na 1\n Cl 1\n Br 1\nEND\nTRANSPORT\n -cells 10\n -shifts 48\n -time_step 36000\n -lengths 0.002\n'
    + ' -boundary_conditions constant constant\n -flow_direction diffusion_only\n -multi_D true 1e-9 0.3 0 1\n'
    + ' -implicit false\n -stagnant 0\n -punch_cells 1-10\n -punch_frequency 48\nEND\n';
  const wS = against(pageAt(handOff('a tracer across salt', salt), 48 * 36000, 10).out, pqLast(salt, 10));
  check('  a tracer level across sea-strength salt held at one end and fresh water at the other: PHREEQC drops its factor on '
    + 'the tracer toward the fresh end, the page holds it at 0.2 -- the bromide within 8.5 %, the pH within 0.009',
  wS.Br < 1.4e-4 && wS.pH < 0.009 && wS.Na < 7e-5, say(wS, ['Na', 'Br']));
}

/* ======================================================================
   EQUILIBRIUM_PHASES AS PHREEQC READS A LINE: an alternative reaction --
   a formula, Fix_H+ -8 NaOH, or a phase, Calcite 0 Anhydrite -- carried as
   a mineral held where the phase's SI is (SI() on its relation), and
   dissolve_only, precipitate_only and -force_equality as the mineral's
   bounds; each against REACTION's steps
   ====================================================================== */
function againstPhaseExtras(engine) {
  const database = { name: 'phreeqc.dat', text: dbText };
  const KN = 'KNOBS\n -convergence_tolerance 1e-12\n';
  const FIX = 'PHASES\nFix_H+\n H+ = H+\n log_k 0\n';
  const saved = 'SAVE solution 1\nSAVE equilibrium_phases 1\nEND\n';
  const cases = [
    { name: 'a pH-stat, NaOH held where SI(Fix_H+) is -8, acid coming in',
      water: `${KN}${FIX}SOLUTION 1\n units mmol/kgw\n pH 6\n Na 1\n Cl 1 charge\n C(4) 2\nEQUILIBRIUM_PHASES 1\n Fix_H+ -8 NaOH 0.01\n${saved}`,
      react: ['HCl', '=> H+ + Cl-'], moles: 1e-3, phase: 'Fix_H+', line: /^NaOH_Fix_H\s+\S+\s+mineral$/m, amount: 1e-6, pH: 1e-6 },
    { name: 'calcite dissolve_only in a water supersaturated with it, acid coming in',
      water: `${KN}SOLUTION 1\n units mmol/kgw\n pH 8.5\n Na 1\n Ca 4\n Cl 9 charge\n C(4) 3\nEQUILIBRIUM_PHASES 1\n Calcite 0 0.002 dissolve_only\n${saved}`,
      react: ['HCl', '=> H+ + Cl-'], moles: 6e-3, phase: 'Calcite', line: /^Calcite\s+\S+\s+mineral\s+dissolve_only$/m, amount: 5e-5, pH: 2e-5 },
    { name: 'gypsum precipitate_only in a water undersaturated in it, calcium coming in',
      water: `${KN}SOLUTION 1\n units mmol/kgw\n pH 7\n Na 20\n Ca 1\n Cl 2 charge\n S(6) 10\nEQUILIBRIUM_PHASES 1\n Gypsum 0 0.01 precipitate_only\n${saved}`,
      react: ['CaCl2', '=> Ca+2 + 2 Cl-'], moles: 0.1, phase: 'Gypsum', line: /^Gypsum\s+\S+\s+mineral\s+precipitate_only$/m, amount: 1e-4, pH: 1e-5 },
    { name: 'a pH-stat with -force_equality, HCl held where SI(Fix_H+) is -9, salt coming in',
      water: `${KN}${FIX}SOLUTION 1\n units mmol/kgw\n pH 8\n Na 3\n Cl 1 charge\n C(4) 2\nEQUILIBRIUM_PHASES 1\n Fix_H+ -9 HCl 0\n -force_equality true\n${saved}`,
      react: ['NaCl', '=> Na+ + Cl-'], moles: 1e-3, phase: 'Fix_H+', line: /^HCl_Fix_H\s+\S+\s+mineral\s+force_equality$/m, amount: 1e-6, pH: 1e-6 },
    { name: 'anhydrite held where calcite is saturated (an alternative phase), acid coming in',
      water: `${KN}SOLUTION 1\n units mmol/kgw\n pH 7.5\n Na 5\n Ca 3\n Cl 4 charge\n C(4) 3\n S(6) 3\nEQUILIBRIUM_PHASES 1\n Calcite 0 Anhydrite 0.01\n${saved}`,
      react: ['HCl', '=> H+ + Cl-'], moles: 2e-3, phase: 'Calcite', line: /^Anhydrite_Calcite\s+\S+\s+mineral$/m, amount: 1e-4, pH: 1e-5 },
  ];
  const out = cases.map((c) => {
    engine.load(dbText);
    const res = P.waterToModel({ engine, database, water: { name: c.name, text: c.water }, activity: true, exact: true,
      phases: true, redox: false, floor: 1e-12 });
    engine.load(dbText);
    const pq = P.parseRows(engine.run(`${P.punchBlock([`EQUI("${c.phase}")`])}${c.water}USE solution 1\nUSE equilibrium_phases 1\n`
      + `REACTION 1\n ${c.react[0]} 1\n ${c.moles} moles in 5 steps\nEND\n`)).slice(-5);
    const T = 1e4;
    const m = RtmModel.compile(`${res.text.replace(/TEND = [^\n]*\n/, `TEND = ${T}\n`)}\n<REACTIONS>\n${c.react[1]}, `
      + `r = ${c.moles / T}\n`);
    const times = [1, 2, 3, 4, 5].map((k) => (k * T) / 5);
    const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: T, rtol: 1e-10, atol: 1e-20, outputTimes: times });
    const mn = res.report.minerals[0].as;
    const at = (n) => m.speciesNames.indexOf(n);
    const ns = m.speciesNames.length;
    let amount = 0;
    let pH = 0;
    // Against the most there was of it, at the start or at a step.
    let total = Math.abs(res.report.minerals[0].amount);
    for (let k = 0; k < 5; k++) {
      const C = m.toConcentrations(r.grid.y[k], times[k]);
      const lnG = new Float64Array(ns);
      RtmModel.activityAt(m.act, C, 0, lnG, new Float64Array(ns));
      const theirs = Number(pq[k].x[0]);
      total = Math.max(total, Math.abs(theirs));
      amount = Math.max(amount, Math.abs(C[at(mn)] - theirs));
      pH = Math.max(pH, Math.abs(-(Math.log(C[at('H+')]) + lnG[at('H+')]) / Math.LN10 - pq[k].pH));
    }
    return { c, amount: amount / Math.max(total, 1e-30), pH, line: c.line.test(res.text), skipped: res.report.phasesSkipped.length,
      events: r.events.length };
  });
  check('EQUILIBRIUM_PHASES as PHREEQC reads a line, against REACTION\'s steps: a pH-stat (an alternative formula), '
    + 'dissolve_only, precipitate_only, -force_equality and an alternative phase, each written as the page has them and '
    + 'its mineral and pH as PHREEQC has them', out.every((x) => x.line && !x.skipped && x.amount < x.c.amount
    && x.pH < x.c.pH),
  out.map((x) => `${x.c.name}: ${x.line ? '' : 'not written so, '}the mineral within ${x.amount.toExponential(1)} of the `
    + `most there was of it, pH ${x.pH.toExponential(1)}${x.events ? `, ${x.events} event${x.events > 1 ? 's' : ''}` : ''}`).join('; '));
}

/** RT/F at tc, in volts, with PHREEQC's constants: a potential from its activity exp(-F psi/RT). */
function GAS_R_T(tc) { return (8.31470 * (tc + 273.15)) / 96493.5; }

/* ======================================================================
   CD-MUSIC: PHREEQC's SURFACE with -cd_music, read, handed off, acid added
   against REACTION, and looked at through the PHREEQC tab
   ====================================================================== */
// A goethite-like surface of the tests' own, made-up constants: protons on plane 0, sodium on plane 1, a chloride
// pair across both, zinc split between them by PHREEQC's five numbers (f 0.3 of a charge of 2 on plane 0).
const OWN_CD = 'SURFACE_MASTER_SPECIES\n  Goe_uni  Goe_uniOH-0.5\n  Goe_tri  Goe_triO-0.5\nSURFACE_SPECIES\n'
  + '  Goe_uniOH-0.5 = Goe_uniOH-0.5\n    log_k 0\n'
  + '  Goe_uniOH-0.5 + H+ = Goe_uniOH2+0.5\n    log_k 9.2\n    -cd_music 1 0 0 0 0\n'
  + '  Goe_uniOH-0.5 + Na+ = Goe_uniOHNa+0.5\n    log_k -0.6\n    -cd_music 0 1 0 0 0\n'
  + '  Goe_uniOH-0.5 + H+ + Cl- = Goe_uniOH2Cl-0.5\n    log_k 8.4\n    -cd_music 1 -1 0 0 0\n'
  + '  Goe_uniOH-0.5 + Zn+2 = Goe_uniOHZn+1.5\n    log_k 3\n    -cd_music 0 0 0 0.3 2\n'
  + '  Goe_triO-0.5 = Goe_triO-0.5\n    log_k 0\n'
  + '  Goe_triO-0.5 + H+ = Goe_triOH+0.5\n    log_k 9.2\n    -cd_music 1 0 0 0 0\n'
  + '  Goe_triO-0.5 + Na+ = Goe_triONa+0.5\n    log_k -0.6\n    -cd_music 0 1 0 0 0\n';

function againstCdMusic(engine) {
  const cdText = OWN_CD + dbText;
  const db = { name: 'cd-test.dat', text: cdText };
  engine.load(cdText);
  const rd = P.readDatabase(cdText);
  const zn = rd.sfCd.get('Goe_uniOHZn+1.5');
  check('CD-MUSIC: -cd_music read as PHREEQC reads it, the planes\' charges from its five numbers, dz0 + f z, dz1 + (1 - f) z '
    + 'and dz2', !!zn && Math.abs(zn[0] - 0.6) < 1e-15 && Math.abs(zn[1] - 1.4) < 1e-15 && zn[2] === 0
    && rd.sfCd.get('Goe_uniOH2Cl-0.5').join() === '1,-1,0', zn ? zn.join(', ') : 'none');

  const water = (cl) => `${KNOBS}SOLUTION 1\n pH 7\n units mol/kgw\n Na 0.01\n Cl ${cl}\n Zn 1e-6\nSURFACE 1\n -cd_music\n`
    + ' Goe_uniOH 3.45e-3 98 1\n -capacitances 0.9 0.74\n Goe_triO 2.7e-3\n -equilibrate 1\nSAVE solution 1\nSAVE surface 1\nEND\n';
  const handOff = (w) => P.waterToModel({ engine, database: db, water: { name: 'cd', text: w }, activity: true, exact: true,
    redox: false, floor: 1e-30 });
  const startOf = (res) => {
    const m = RtmModel.compile(res.text);
    const y = m.toConcentrations(m.initialState());
    let worst = 0;
    for (const [n, a] of res.amounts) {
      const k = m.speciesNames.indexOf(n);
      if (a > 1e-25 && k >= 0) worst = Math.max(worst, Math.abs(y[k] / a - 1));
    }
    for (const [p, n] of res.names) {
      const k = m.speciesNames.indexOf(n);
      if (res.molal.get(p) > 1e-25 && k >= 0) worst = Math.max(worst, Math.abs(y[k] / res.molal.get(p) - 1));
    }
    return { m, worst };
  };
  const bal = handOff(water('0.01 charge'));
  const imb = handOff(water('0.0098'));
  const sb = startOf(bal);
  const si = startOf(imb);
  const pots = bal.report.surface.potentials;
  check('  the hand-off writes the surface by CD-MUSIC -- its three potentials at PHREEQC\'s EDL psi, psi1 and psi2, the '
    + 'first with the area and capacitances, each species\' planes as dz0 to dz2 and a half charge as z= -- and the model '
    + 'starts on PHREEQC\'s water and surface, in charge balance and with a charge of its own',
  sb.worst < 1e-11 && si.worst < 1e-11 && pots.length === 3 && pots.every((pp) => pp.cd)
    && /^Goe_psi\s+\S+\s+potential\s+area=98\s+grams=1\s+c0=0\.9\s+c1=0\.74$/m.test(bal.text)
    && /^Goe_psid\s+\S+\s+potential$/m.test(bal.text) && /^Goe_uniOHZn_1_5\s+\S+\s+surface\s+z=1\.5\s+dz0=0\.6\s+dz1=1\.4$/m.test(bal.text),
  `the start ${sb.worst.toExponential(1)} and ${si.worst.toExponential(1)}; psi ${pots.map((pp) => (pp.psi * 1e3).toFixed(3)).join(', ')} mV`);

  // 1 mmol of HCl against REACTION: the pH and the three potentials; and through the PHREEQC tab.
  const rtext = `${bal.text.replace(/TEND = [^\n]*\n/, 'TEND = 1e4\n').replace(/EQUILIBRATE = [^\n]*\n/, 'EQUILIBRATE = always\n')}`
    + '\n<REACTIONS>\n=> H+ + Cl-, k = 1e-7\n';
  const m2 = RtmModel.compile(rtext);
  const r = FacsimileODE.runModel(m2, { solver: 'ndf', tend: 1e4, rtol: 1e-10, atol: 1e-20 });
  const ye = m2.toConcentrations(r.y[r.y.length - 1]);
  const at = (n) => ye[m2.speciesNames.indexOf(n)];
  const lnG = new Float64Array(ye.length);
  RtmModel.activityAt(m2.act, ye, 0, lnG, new Float64Array(ye.length));
  const kH = m2.speciesNames.indexOf('H+');
  const pH = -(Math.log(ye[kH]) + lnG[kH]) / Math.LN10;
  const psi = ['Goe_psi', 'Goe_psib', 'Goe_psid'].map((n) => -Math.log(at(n)) * GAS_R_T(25));
  const pq = P.parseRows(engine.run(`${P.punchBlock(['EDL("psi", "Goe")', 'EDL("psi1", "Goe")', 'EDL("psi2", "Goe")'])}`
    + `${water('0.01 charge')}USE solution 1\nUSE surface 1\nREACTION 1\n HCl 1\n 0.001 moles\nEND\n`)).pop();
  const dpsi = Math.max(...psi.map((v, i) => Math.abs(v - Number(pq.x[i]))));
  const view = P.viewRun({ engine, database: db, run: pageRun(rtext, 1e4), modelText: rtext,
    water: { name: 'cd', text: water('0.01 charge') }, unit: 's', times: 8 });
  const sfr = view.report.surface;
  check('  1 mmol of HCl added against REACTION: the pH and the three potentials as PHREEQC has them; looked at through '
    + 'the PHREEQC tab, the surface PHREEQC loads from each water and its potentials the run\'s',
  Math.abs(pH - pq.pH) < 1e-8 && dpsi < 1e-9 && !!sfr && !sfr.error && Math.abs(sfr.gap) < 1e-9 && sfr.potentials.length === 3
    && Math.abs(sfr.psiGap.by) < 1e-9,
  `pH ${pH.toFixed(8)} for ${pq.pH.toFixed(8)}, the potentials within ${dpsi.toExponential(1)} V; the tab: the surface `
    + `${sfr ? Number(sfr.gap).toExponential(1) : '-'}, the potentials ${sfr && sfr.psiGap ? Math.abs(sfr.psiGap.by).toExponential(1) : '-'} V`);
  engine.load(dbText);
}

/* ======================================================================
   KINETICS: PHREEQC's kinetic reactants and their RATES programs

   Each of phreeqc.dat's seven RATES programs as the rate law the hand-off
   writes, against the program run by PHREEQC's own BASIC at the same water
   (M, M0 and PARM put in as numbers, TIME 1, SAVE as PUNCH), at an oxic
   water at 25 C and an anoxic one at 40 C, which take the programs'
   branches both ways. Reading KINETICS and RATES; what a program does that
   a rate law cannot be, refused with its reason. Then waters handed off
   with their KINETICS and run, against PHREEQC's KINETICS at its steps:
   calcite into a water with CO2 and no calcium, K-feldspar into a water
   with CO2, organic carbon (CH2O, Monod) through the water's O2 and into
   its nitrate, pyrite with O2; the last two moving electrons.
   ====================================================================== */
function againstKineticsHandOff(engine) {
  engine.load(dbText);
  const rates = P.readRates(dbText);
  // 1. Each program against PHREEQC's BASIC at a water.
  const PARMS = { quartz: [0.146, 1.5], 'k-feldspar': [6.41, 0.1], albite: [6.04, 0.1], calcite: [5, 0.6],
    pyrite: [-5, 0.1, 0.5, -0.11], organic_c: [], pyrolusite: [] };
  const waters = {
    'oxic, 25 C': 'SOLUTION 1\n temp 25\n units mmol/kgw\n pH 7.5\n pe 12\n Na 6; K 0.1; Ca 1; Mg 0.5; Al 1e-3; Si 0.2; Fe 0.01\n'
      + ' Mn 0.01\n Cl 1 charge\n S(6) 1\n N(5) 0.5\n C 2\n',
    'anoxic, 40 C': 'SOLUTION 1\n temp 40\n units mmol/kgw\n pH 6.8\n pe -2\n Na 6; K 0.1; Ca 1; Mg 0.5; Al 1e-3; Si 0.2\n'
      + ' Fe(2) 0.05; Mn 0.01\n Cl 1 charge\n S(6) 1\n N(5) 0.5\n C 4\n',
  };
  const fns = { exp: Math.exp, ln: Math.log, log10: Math.log10, sqrt: Math.sqrt, abs: Math.abs, sign: Math.sign,
    step: (x) => (x > 0 ? 1 : 0), ramp: (x) => (x > 0 ? x : 0) };
  const punchOne = (water, lines, head) => engine.run(`${water}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n`
    + ` -headings ${head}\n -start\n${lines}\n -end\nEND\n`).pop().map(Number);
  let worst = 0;
  let where = '';
  let compared = 0;
  const m = 5e-4;
  const m0 = 1e-3;
  for (const [wname, water] of Object.entries(waters)) {
    for (const r of rates.values()) {
      const parms = PARMS[r.name.toLowerCase()];
      const prog = r.lines.map((l) => l.replace(/\bPARM\s*\(\s*([0-9]+)\s*\)/gi, (_, i) => `(${parms[Number(i) - 1]})`)
        .replace(/\bM0\b/gi, `(${m0})`).replace(/\bM\b/gi, `(${m})`).replace(/\bTIME\b/gi, '1')
        .replace(/\bSAVE\b/gi, 'PUNCH')).join('\n');
      const pq = punchOne(water, prog, 'rate')[0];
      // The law, what it reads taken from PHREEQC at the same water: a molality as 10^LM, which keeps the smallest.
      const reads = [];
      const read = (what, kind) => { reads.push(what); return `${kind}__${reads.length - 1}`; };
      const ctx = { m: 'MM', m0, parms, W: 1, solnVol: punchOne(water, '10 PUNCH SOLN_VOL', 'v')[0],
        phase: (p, kind) => read(`${kind}("${p}")`, kind), act: (s) => read(`ACT("${s}")`, 'V'),
        mol: (s) => read(`10^LM("${s}")`, 'V'), tot: (l) => read(`TOT("${l}")`, 'V'), kin: () => null, equi: () => null };
      const law = P.rateLaw(r, ctx);
      const vals = punchOne(water, `${reads.map((x, i) => `${10 + i} PUNCH ${x}`).join('\n')}\n900 PUNCH TK, TC, MU`,
        `${reads.map((_, i) => `v${i}`).join(' ')} tk tc mu`);
      const scope = { MM: m, TK: vals[reads.length], TC: vals[reads.length + 1], I: vals[reads.length + 2], ...fns };
      reads.forEach((x, i) => { scope[`${x.slice(0, 2) === 'SI' ? 'SI' : x.slice(0, 2) === 'SR' ? 'SR' : 'V'}__${i}`] = vals[i]; });
      // eslint-disable-next-line no-new-func
      const ev = (text) => Function(...Object.keys(scope), `return (${text.replace(/\^/g, '**')});`)(...Object.values(scope));
      for (const [k, v] of law.names) scope[k] = ev(v);
      const page = ev(law.r);
      const rel = pq === 0 && page === 0 ? 0 : Math.abs(page - pq) / Math.abs(pq);
      compared++;
      if (rel > worst) { worst = rel; where = `${r.name}, ${wname}`; }
    }
  }
  check('Kinetics: phreeqc.dat\'s seven RATES as rate laws, each against its program run by PHREEQC\'s BASIC at an oxic '
    + 'water at 25 C and an anoxic one at 40 C: IF and GOTO taken both ways, DATA and READ, SI, SR, ACT, LM, TOT of a '
    + 'valence state, SOLN_VOL', compared === 14 && worst < 1e-12,
  `${compared} rates within ${worst.toExponential(1)} (${where})`);

  // 2. Reading: KINETICS's defaults and steps, RATES given again.
  const kb = P.readKinetics('KINETICS 2\nA\n -m 0.5\nB\n -m0 2\n -formula CaCO3 1 MgCO3 0.5\n -parms 1 two 3\nC\n'
    + ' -steps 1 day in 4\nKINETICS 3\nD\n -steps 10 4*5\n').get(2);
  const k3 = P.readKinetics('KINETICS 3\nD\n -steps 10 4*5\n').get(3);
  const rr = P.readRates('RATES\nX\n -start\n10 SAVE 1\n -end\n', 'RATES\nx\n -start\n10 SAVE 2\n20 END\n -end\n');
  check('  KINETICS read as PHREEQC reads it: -m and -m0 each the other\'s where not given, the formula the name unless '
    + 'given, -parms numbers and words, -steps 1 day in 4 four of 21600 s, 10 4*5 five steps; a RATES given again replaces',
  kb.comps.length === 3 && kb.comps[0].m0 === 0.5 && kb.comps[1].m === 2 && kb.comps[2].m === 1 && kb.comps[2].m0 === 1
    && kb.comps[1].formula.join('|') === 'CaCO3,1|MgCO3,0.5' && kb.comps[0].formula.join() === 'A,1'
    && kb.comps[1].parms.join() === '1,two,3' && kb.steps.join() === '21600,21600,21600,21600'
    && k3.steps.join() === '10,5,5,5,5' && rr.size === 1 && rr.get('x').lines.join('|') === '10 SAVE 2|20 END',
  `${JSON.stringify(kb.comps.map((c) => [c.m, c.m0, c.formula, c.parms]))}; steps ${kb.steps}; ${k3.steps}`);
  const refuse = (lines) => {
    try { P.rateLaw({ name: 'x', lines }, { m: '[x]', m0: 1, parms: [], W: 1, phase: () => null, act: () => null,
      mol: () => null, tot: () => null, kin: () => null, equi: () => null, solnVol: null }); } catch (e) { return e.message; }
    return '(no refusal)';
  };
  const refusals = [
    ['a loop', ['10 x = 1', '20 IF M > 0 THEN GOTO 10', '30 SAVE x*TIME'], /goes back, a loop/],
    ['moles not a rate times TIME', ['10 SAVE M*(1 - EXP(-TIME))'], /not moles in a step|other than as moles in a step/],
    ['a way that saves nothing', ['10 IF M > 0 THEN GOTO 30', '20 END', '30 SAVE M*TIME'], /saves nothing/],
    ['PUT', ['10 PUT(1, 1)', '20 SAVE M*TIME'], /cannot read|cannot be made of/],
    ['a PARM not given', ['10 SAVE PARM(2)*TIME'], /PARM\(2\), which -parms does not give/],
  ];
  const badR = refusals.filter(([, lines, re]) => !re.test(refuse(lines)));
  check(`  a program a rate law cannot be is refused, with its reason: ${refusals.map((x) => x[0]).join('; ')}`, !badR.length,
    badR.map(([what, lines]) => `${what}: ${refuse(lines)}`).join(' | '));

  // 3. Waters handed off with their KINETICS, run against PHREEQC's KINETICS at its steps.
  const KIN = 'KNOBS\n -convergence_tolerance 1e-12\n';
  const runs = [
    { label: 'calcite', water: 'SOLUTION 1\n temp 25\n units mmol/kgw\n pH 5.5\n Na 1\n Cl 1\n C(4) 10\n',
      kin: 'KINETICS 1\nCalcite\n -m 1e-3\n -parms 50 0.6\n -tol 1e-14\n -steps 36000 in 12\n -runge_kutta 6\n',
      reactant: 'Calcite', redox: false, tol: { M: 1e-7, pH: 1e-8, pe: Infinity } },
    { label: 'K-feldspar', water: 'SOLUTION 1\n temp 25\n units mmol/kgw\n pH 6\n Na 1\n Cl 1 charge\n C(4) 5\n Al 1e-4\n'
      + ' Si 0.1\n Ca 0.2\n Mg 0.1\n K 0.05\n', kin: 'KINETICS 1\nK-feldspar\n -m 2.18\n -parms 6.41 0.1\n -tol 1e-12\n'
      + ' -steps 3e7 in 12\n -runge_kutta 6\n', reactant: 'K-feldspar', redox: false, tol: { M: 1e-10, pH: 1e-7, pe: Infinity } },
    { label: 'organic carbon', water: 'SOLUTION 1\n temp 25\n units mmol/kgw\n pH 7\n Na 2 charge\n Cl 1\n N(5) 0.5\n'
      + ' S(6) 0.25\n C(4) 1\n O(0) 0.5\n', kin: 'KINETICS 1\nOrganic_C\n -formula CH2O\n -m 5e-3\n -tol 1e-12\n'
      + ' -steps 3e8 in 15\n -runge_kutta 6\n', reactant: 'Organic_C', redox: true, tol: { M: 1e-6, pH: 1e-6, pe: 1e-3 } },
    { label: 'pyrite', water: 'SOLUTION 1\n temp 25\n units mmol/kgw\n pH 7\n Na 2 charge\n Cl 1\n C(4) 2\n O(0) 0.6\n',
      kin: 'KINETICS 1\nPyrite\n -m 1e-3\n -parms -1 0.1 0.5 -0.11\n -tol 1e-12\n -steps 3e7 in 12\n -runge_kutta 6\n',
      reactant: 'Pyrite', redox: true, tol: { M: 1e-9, pH: 1e-8, pe: 1e-7 } },
  ].map((c) => {
    engine.load(dbText);
    const res = P.waterToModel({ engine, database: { name: 'phreeqc.dat', text: dbText },
      water: { name: c.label, text: `${KIN}${c.water}${c.kin}END\n` }, activity: true, exact: true, redox: c.redox, floor: 0 });
    const kin = res.report.kinetics;
    const rows = engine.run(`${KIN}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings t M pH pe\n -start\n`
      + `10 PUNCH TOTAL_TIME, KIN("${c.reactant}"), -LA("H+"), -LA("e-")\n -end\n${c.water}${c.kin}END\n`);
    const pq = rows.slice(1).map((r) => r.map(Number)).filter((r) => r[0] > 0);
    const mdl = RtmModel.compile(res.text);
    const times = pq.map((r) => r[0]);
    const t0 = Date.now();
    const run = FacsimileODE.runModel(mdl, { solver: 'ndf', tend: times[times.length - 1], rtol: 1e-10, atol: 1e-22, breaks: times });
    const ms = Date.now() - t0;
    const at = (n) => mdl.speciesNames.indexOf(n);
    const ns = mdl.speciesNames.length;
    const d = { M: 0, pH: 0, pe: 0 };
    for (const row of pq) {
      const k = run.t.findIndex((t) => Math.abs(t - row[0]) <= 1e-9 * row[0]);
      const y = mdl.toConcentrations(run.y[k], run.t[k]);
      const lnG = new Float64Array(ns);
      RtmModel.activityAt(mdl.act, y, 0, lnG, new Float64Array(ns), 0);
      d.M = Math.max(d.M, Math.abs(y[at(kin.reactants[0].as)] - row[1]) / row[1]);
      d.pH = Math.max(d.pH, Math.abs(-(Math.log(y[at('H+')]) + lnG[at('H+')]) / Math.LN10 - row[2]));
      if (c.redox) d.pe = Math.max(d.pe, Math.abs(-Math.log10(y[at('e-')]) - row[3]));
    }
    const first = pq[0];
    const last = pq[pq.length - 1];
    return { ...c, res, kin, d, ms, steps: pq.length, used: (first[1] - last[1]) / first[1] };
  });
  check('  waters handed off with their KINETICS and run, against PHREEQC\'s KINETICS at its steps: calcite into a water '
    + 'with CO2 and no calcium (its species from a trace of the reactant), K-feldspar, organic carbon through O2 into '
    + 'nitrate, pyrite with O2, the last two moving electrons, each reactant left and the pH and pe as PHREEQC has them',
  runs.every((x) => x.kin && x.d.M < x.tol.M && x.d.pH < x.tol.pH && (!x.redox || x.d.pe < x.tol.pe))
    && runs[0].kin.trace === 1e-20 && runs.every((x) => !x.res.report.kineticsSkipped.length),
  runs.map((x) => `${x.label}: ${x.kin ? `${x.d.M.toExponential(1)} in what is left, pH ${x.d.pH.toExponential(1)}`
    + `${x.redox ? `, pe ${x.d.pe.toExponential(1)}` : ''} over ${x.steps} steps (${x.ms} ms)` : 'not carried'}`).join('; '));
  const calcite = runs[0].res.text;
  check('  the model written: the reactant a mineral at -m, its dissolution a reaction with PHREEQC\'s program above it, '
    + 'the phase its rate reads in <PHASES>, TEND PHREEQC\'s steps together',
  /^Calcite\s+0\.001\s+mineral$/m.test(calcite) && /^#\s+20 IF \(M <= 0 and si_cc < 0\) THEN GOTO 200$/m.test(calcite)
    && /^Calcite => CO3-2 \+ Ca\+2, r = /m.test(calcite) && /^<PHASES>\nCalcite <=> CO3-2 \+ Ca\+2, /m.test(calcite)
    && /^TEND = 36000$/m.test(calcite), calcite.split('\n').filter((l) => /=>/.test(l)).join(' | ').slice(0, 200));

  /*
    4. A column: a CO2-charged water through 0.1 m of calcite dissolving at
    phreeqc.dat's rate, two pore volumes, against PHREEQC's TRANSPORT with
    KINETICS in every cell. The model is the hand-off's of the column's
    water with its KINETICS, made a column as in 4 above. The two schemes
    differ -- PHREEQC shifts a cell's water whole and then reacts it for the
    step, where the page's cells are mixed as the water goes -- and meet as
    the cells are refined, the velocity and the time kept.
  */
  const column = (N) => {
    const L = 0.1;
    const dx = L / N;
    const dt = (3600 * 20) / N;
    const S = 2 * N;
    const alpha = dx / 2;
    const cw = (n) => `SOLUTION ${n}\n temp 25\n units mmol/kgw\n pH 7.5\n Na 2\n Ca 1\n Cl 2 charge\n C(4) 3\n`;
    const ck = (n) => `KINETICS ${n}\nCalcite\n -m 1e-3\n -parms 5000 0.6\n -tol 1e-10\n`;
    const co2 = 'SOLUTION 0\n temp 25\n units mmol/kgw\n pH 4.5\n Na 1\n Cl 1 charge\n C(4) 10\nEND\n';
    engine.load(dbText);
    const t1 = Date.now();
    const rows = engine.run(`${cw(`1-${N}`)}END\n${ck(`1-${N}`)}END\n${co2}`
      + 'SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings cell time pH Ca cal\n -start\n'
      + '10 PUNCH CELL_NO, TOTAL_TIME, -LA("H+"), TOT("Ca"), KIN("Calcite")\n -end\n'
      + `TRANSPORT\n -cells ${N}\n -shifts ${S}\n -time_step ${dt}\n -lengths ${dx}\n -dispersivities ${alpha}\n`
      + ` -diffusion_coefficient 0\n -flow_direction forward\n -boundary_conditions flux flux\n -punch_cells 1-${N}\n`
      + ` -punch_frequency 1\n -print_frequency ${10 * S}\nEND\n`);
    const pqMs = Date.now() - t1;
    const head = rows[0].map((h) => String(h).trim());
    const pq = new Map();
    for (const r of rows.slice(1)) {
      const t = Number(r[head.indexOf('time')]);
      if (!(t > 0)) continue;
      pq.set(`${Number(r[head.indexOf('cell')])}/${Math.round(t / dt)}`, { pH: Number(r[head.indexOf('pH')]),
        Ca: Number(r[head.indexOf('Ca')]), cal: Number(r[head.indexOf('cal')]) });
    }
    engine.load(dbText);
    const res = P.waterToModel({ engine, database: { name: 'phreeqc.dat', text: dbText },
      water: { name: 'column', text: `${cw(1)}${ck(1)} -steps ${S * dt}\nEND\n` }, activity: true, exact: true });
    const inflow = P.parseRows(engine.run(`${P.punchBlock()}${co2}`)).pop();
    const back = new Map([...res.names].map(([k, n]) => [n, k]));
    const text = res.text
      .replace('MODE = batch', `MODE = transport\nCELLS = ${N}\nLENGTH = ${L}\nDIFFUSION = 1\nADVECTION = 1\n`
        + `ADVECTION_SCHEME = limited\nVELOCITY = ${dx / dt}\nPECLET = ${L / alpha}\nLEFT = robin\nRIGHT = free`)
      .replace(/^TEND = .*$/m, `TEND = ${(S + 0.5) * dt}`)
      .replace(SPECIES_LINE, (line, name, gap, value, rest) => {
        if (/mineral/.test(rest) || !back.has(name)) return line;
        const sp = inflow.species.get(back.get(name));
        return `${line}  left=${sp ? sp[0] : 0}`;
      });
    const mdl = RtmModel.compile(text);
    const t0 = Date.now();
    const r = FacsimileODE.runModel(mdl, { solver: 'ndf', tend: (S + 0.5) * dt, rtol: 1e-7, atol: 1e-20, nonNegative: true,
      outputTimes: Array.from({ length: S }, (_, k) => (k + 1.5) * dt) });
    const ms = Date.now() - t0;
    const ns = mdl.speciesNames.length;
    const dbr = P.readDatabase(dbText);
    const caOf = [];
    mdl.speciesNames.forEach((n, i) => {
      if (back.has(n) && dbr.expand(back.get(n)).has('Ca')) caOf.push([i, dbr.expand(back.get(n)).get('Ca')]);
    });
    const iH = mdl.speciesNames.indexOf('H+');
    const iCal = mdl.speciesNames.indexOf('Calcite');
    const lnG = new Float64Array(ns);
    let pH = 0;
    let Ca = 0;
    for (let k = 1; k <= S; k++) {
      const c = mdl.toConcentrations(r.grid.y[k - 1]);
      const b = (N - 1) * ns;
      let ca = 0;
      for (const [i, n] of caOf) ca += n * c[b + i];
      RtmModel.activityAt(mdl.act, c, b, lnG, new Float64Array(ns));
      const d = pq.get(`${N}/${k}`);
      pH = Math.max(pH, Math.abs(-(Math.log(c[b + iH]) + lnG[iH]) / Math.LN10 - d.pH));
      Ca = Math.max(Ca, Math.abs(ca - d.Ca));
    }
    const end = mdl.toConcentrations(r.grid.y[S - 1]);
    let dis = 0;
    let pqDis = 0;
    for (let cell = 0; cell < N; cell++) {
      dis += 1e-3 - end[cell * ns + iCal];
      pqDis += 1e-3 - pq.get(`${cell + 1}/${S}`).cal;
    }
    return { N, pH, Ca, dis: dis / pqDis - 1, ms, pqMs };
  };
  /*
    5. A surface whose sites go with a kinetic reactant, PHREEQC's SURFACE
    `Hfo_wOH NaOHs kinetic_reactant 0.2`: a host of the test's own, NaOH,
    dissolving at a first-order rate into a CO2 water with zinc, its sites
    going with it, the zinc on them taken up as the pH rises and coming off
    as they go; without
    electrostatics, and with a double layer of 53300 m2 to each mole. The
    host gives OH-, not water, so PHREEQC's kilogram moves little -- by the
    water its OH- makes with the carbonic acid, 3e-6 -- and amounts are
    compared, PHREEQC's molality times its kilograms. And an exchanger whose
    capacity goes with the reactant: carried at what PHREEQC loads at the
    start, and said to be.
  */
  const hostRun = (edl) => {
    const sw = 'SOLUTION 1\n temp 25\n units mmol/kgw\n pH 5\n Na 1\n Cl 1 charge\n C(4) 2\n Zn 0.01\n';
    const rt = 'PHASES\nNaOHs\n NaOH = Na+ + OH-\n log_k 20\nRATES\nNaOHs\n-start\n10 rate = PARM(1) * M\n20 SAVE rate * TIME\n-end\n';
    const kn = 'KINETICS 1\nNaOHs\n -m 0.001\n -parms 1e-5\n -tol 1e-12\n -steps 2e5 in 10\n -runge_kutta 6\n';
    const sf = `SURFACE 1\n${edl ? '' : ' -no_edl\n'} Hfo_wOH NaOHs kinetic_reactant 0.2${edl ? ' 53300' : ''}\n -equilibrate 1\n`;
    engine.load(dbText);
    const res = P.waterToModel({ engine, database: { name: 'phreeqc.dat', text: dbText },
      water: { name: 'host', text: `${KIN}${rt}${sw}${kn}${sf}END\n` }, activity: true, exact: true });
    engine.load(dbText);
    const rows = engine.run(`${KIN}${rt}SELECTED_OUTPUT 99\n -reset false\nUSER_PUNCH 99\n -headings t M Zn ZnS pH w\n -start\n`
      + `10 PUNCH TOTAL_TIME, KIN("NaOHs"), MOL("Zn+2"), MOL("Hfo_wOZn+"), -LA("H+"), TOT("water")\n -end\n${sw}${kn}${sf}END\n`);
    const pq = rows.slice(1).map((r) => r.map(Number)).filter((r) => r[0] > 0);
    const mdl = RtmModel.compile(res.text);
    const times = pq.map((r) => r[0]);
    const run = FacsimileODE.runModel(mdl, { solver: 'ndf', tend: times[times.length - 1], rtol: 1e-10, atol: 1e-22, breaks: times });
    const at = (n) => mdl.speciesNames.indexOf(n);
    const ns = mdl.speciesNames.length;
    const zn = new Map(res.names).get('Zn+2');
    const d = { M: 0, Zn: 0, on: 0, pH: 0 };
    let first = null;
    let lastOn = 0;
    for (const row of pq) {
      const k = run.t.findIndex((t) => Math.abs(t - row[0]) <= 1e-9 * row[0]);
      const y = mdl.toConcentrations(run.y[k], run.t[k]);
      const lnG = new Float64Array(ns);
      RtmModel.activityAt(mdl.act, y, 0, lnG, new Float64Array(ns), 0);
      d.M = Math.max(d.M, Math.abs(y[at('NaOHs')] / row[1] - 1));
      d.Zn = Math.max(d.Zn, Math.abs(y[at(zn)] / (row[2] * row[5]) - 1));
      d.on = Math.max(d.on, Math.abs(y[at('Hfo_wOZn+')] / (row[3] * row[5]) - 1));
      d.pH = Math.max(d.pH, Math.abs(-(Math.log(y[at('H+')]) + lnG[at('H+')]) / Math.LN10 - row[4]));
      if (!first) first = row;
      lastOn = row[3];
    }
    const per = /^Hfo_wOH\s+\S+\s+surface\s+sites=0\.2\s+per=NaOHs$/m.test(res.text)
      && (!edl || /^Hfo_psi\s+\S+\s+potential\s+area=53300\s+per=NaOHs$/m.test(res.text));
    return { edl, d, per, used: 1 - pq[pq.length - 1][1] / 1e-3, rise: lastOn / first[3], skipped: res.report.surfaceSkipped };
  };
  const hosts = [hostRun(false), hostRun(true)];
  engine.load(dbText);
  const linked = P.waterToModel({ engine, database: { name: 'phreeqc.dat', text: dbText }, water: { name: 'x', text: `${KIN}`
    + 'PHASES\nNaOHs\n NaOH = Na+ + OH-\n log_k 20\nRATES\nNaOHs\n-start\n10 rate = PARM(1) * M\n20 SAVE rate * TIME\n-end\n'
    + 'SOLUTION 1\n temp 25\n units mmol/kgw\n pH 5\n Na 1\n Ca 0.5\n Cl 2 charge\n C(4) 2\nKINETICS 1\nNaOHs\n -m 0.001\n'
    + ' -parms 1e-5\n -steps 2e5\nEXCHANGE 1\n X NaOHs kinetic_reactant 0.1\n -equilibrate 1\nEND\n' }, activity: true, exact: true });
  const lx = linked.report.exchange && linked.report.exchange.linked;
  check('  a surface whose sites go with a kinetic reactant: a host dissolving at a rate, 86 % of it, the sites going with '
    + 'it (sites= per=, and with a double layer its area per= too), the zinc on them taken up as the pH rises and coming '
    + 'off as they go, '
    + 'against PHREEQC\'s KINETICS with SURFACE kinetic_reactant; an exchanger whose capacity goes with the reactant '
    + 'carried at its start and said to be', hosts.every((x) => x.per && !x.skipped.length && x.d.M < 1e-8 && x.d.Zn < 1e-6
    && x.d.on < 1e-5 && x.d.pH < 1e-7 && x.used > 0.8) && !!lx && lx.length === 1 && lx[0].phase === 'NaOHs'
    && lx[0].kind === 'kinetic_reactant' && /the bare exchanger, X,/.test(lx[0].why),
  hosts.map((x) => `${x.edl ? 'with a double layer' : 'no electrostatics'}: ${(x.used * 100).toFixed(0)} % used, the host `
    + `within ${x.d.M.toExponential(1)}, Zn+2 ${x.d.Zn.toExponential(1)} and on the sites ${x.d.on.toExponential(1)} in moles, `
    + `pH ${x.d.pH.toExponential(1)}`).join('; ') + `; the exchanger ${lx ? JSON.stringify(lx) : 'not reported'}`);

  const cols = [column(20), column(40)];
  check('  a column, CO2 water through calcite dissolving at phreeqc.dat\'s rate, against PHREEQC\'s TRANSPORT with '
    + 'KINETICS in each cell: the effluent and the calcite dissolved, meeting as the cells are refined',
  cols[1].pH < 0.1 && cols[1].Ca < 1e-5 && Math.abs(cols[1].dis) < 0.005 && cols[1].pH < 0.6 * cols[0].pH
    && cols[1].Ca < 0.6 * cols[0].Ca,
  cols.map((x) => `${x.N} cells: pH within ${x.pH.toFixed(3)}, Ca ${(x.Ca * 1e3).toFixed(4)} mM, the calcite dissolved `
    + `${(x.dis * 100).toFixed(2)} %, PHREEQC ${x.pqMs} ms, the page ${x.ms} ms`).join('; '));
  engine.load(dbText);
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
  console.log('\n--- redox: the hand-off, oxygen in, a pyrite column, and the PHREEQC tab ---');
  againstRedox(wasm);
  console.log('\n--- a surface: the hand-off, zinc through a column, and the PHREEQC tab ---');
  againstSurface(wasm);
  console.log('\n--- the double layer: the hand-off, a surface loaded, zinc through a column, and the PHREEQC tab ---');
  againstDoubleLayer(wasm);
  console.log('\n--- SIT: the coefficients, the hand-off, the PHREEQC tab, an exchanger, brine, a pyrite column, sit.dat ---');
  againstSit(wasm);
  console.log('\n--- a gas phase: ideal and real, a fixed pressure and a fixed volume, a bubble forming, the PHREEQC tab ---');
  againstGas(wasm);
  console.log('\n--- the temperature: log K at any, a heated batch, a column held at 10 to 70 C ---');
  againstTemperature(wasm);
  console.log('\n--- solid solutions: the ten forms, another temperature, strontianite added through the gap, the PHREEQC tab ---');
  againstSolidSolutions(wasm);
  console.log('\n--- Pitzer: the coefficients, the hand-off, the electron, the PHREEQC tab, pitzer.dat ---');
  againstPitzer(wasm);
  console.log('\n--- Debye-Hueckel A and B at the water\'s activity ---');
  againstWaterActivity(wasm);
  console.log('\n--- LLNL: the reading, the coefficients, the hand-off, the PHREEQC tab, llnl.dat ---');
  againstLlnl(wasm);
  console.log('\n--- molar volumes: log K at the pressure, VM(), the hand-off at 100 to 500 atm, REACTION, the PHREEQC tab ---');
  againstVolumes(wasm);
  console.log('\n--- sites that go with a phase: the hand-off, salt against REACTION ---');
  againstSurfaceMineral(wasm);
  console.log('\n--- an exchanger\'s sites that go with a phase or a kinetic reactant: salt against REACTION, a host against KINETICS ---');
  againstExchangeMineral(wasm);
  console.log('\n--- a column from PHREEQC\'s TRANSPORT: Example 11, calcite, calcite at a rate, the options, the refusals ---');
  againstTransportHandOff(wasm);
  console.log('\n--- multicomponent diffusion: -multi_D against TRANSPORT made finer in time, -implicit, a flowing column, a tracer across salt ---');
  againstMultiD(wasm);
  console.log('\n--- what a run can be read as: a water\'s quantities against PHREEQC ---');
  againstQuantities(wasm);
  console.log('\n--- diagrams: a water held at a pH, a pe or a total, against PHREEQC\'s SOLUTION there ---');
  againstDiagrams(wasm);
  console.log('\n--- the boundaries of a map: a Pourbaix map\'s, over pe and over Eh, against PHREEQC\'s SOLUTION at their points ---');
  againstBoundaries(wasm);
  console.log('\n--- Eh: from pe as PHREEQC prints its redox couples\' Eh, and a handed-off water\'s ---');
  againstEh(wasm);
  console.log('\n--- a silicate stability map: each phase per mole of aluminium, against PHREEQC\'s SOLUTION at its boundaries ---');
  againstStability(wasm);
  console.log('\n--- a redox ladder: valence states, the couples, and where each turns over against PHREEQC\'s SOLUTION there ---');
  againstLadder(wasm);
  console.log('\n--- the couples across a map of pH and pe or Eh, against PHREEQC\'s SOLUTION along each line ---');
  againstCouples(wasm);
  console.log('\n--- redox zones: organic carbon at a steady rate against PHREEQC\'s REACTION, each valence state\'s total ---');
  againstRedoxZones(wasm);
  console.log('\n--- inverse models: PHREEQC\'s INVERSE_MODELING between waters of a run, read back from what it prints ---');
  againstInverse(wasm);
  console.log('\n--- fitting: a log K fitted back to what PHREEQC gives ---');
  againstFit(wasm);
  console.log('\n--- the conductance, the density and the viscosity against PHREEQC ---');
  againstConductance(wasm);
  console.log('\n--- EQUILIBRIUM_PHASES as PHREEQC reads a line: alternative reactions, dissolve_only, precipitate_only, -force_equality ---');
  againstPhaseExtras(wasm);
  console.log('\n--- CD-MUSIC: the reading, the hand-off, acid against REACTION, the PHREEQC tab ---');
  againstCdMusic(wasm);
  console.log('\n--- KINETICS: RATES as rate laws against PHREEQC\'s BASIC, the hand-off, runs against KINETICS ---');
  againstKineticsHandOff(wasm);
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
