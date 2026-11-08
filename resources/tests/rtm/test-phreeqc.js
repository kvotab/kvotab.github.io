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
    .replace(/^(\S+)(\s+)([0-9][0-9.eE+-]*)(.*)$/gm, (line, name, gap, value, rest) => {
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
  let pitzer = '';
  try {
    // Before the database: PHREEQC reads one to its first END, and so does the page.
    P.waterToModel({ engine, database: { name: 'pz', text: `PITZER\n-B0\n Na+ Cl- 0.0765\n${dbText}` }, water,
      activity: true });
  } catch (e) { pitzer = e.message; }
  check('... and a database with the Pitzer model is not followed, and says so', /Pitzer activity model/.test(pitzer),
    pitzer.slice(0, 90));
  const fol = P.waterToModel({ engine, database, water, activity: true, exact: true, redox: false });
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
    .replace(/^(\S+)(\s+)([0-9][0-9.eE+-]*)(.*)$/gm, (line, name, gap, value, rest) => {
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
  const text = res.text.replace(/^(\S+)(\s+)([0-9][0-9.eE+-]*)(.*)$/gm, (line, name, gap, value, rest) => {
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
    .replace(/^(\S+)(\s+)([0-9][0-9.eE+-]*)(.*)$/gm, (line, name, gap, value, rest) => {
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
    .replace(/^(\S+)(\s+)([0-9][0-9.eE+-]*)(.*)$/gm, (line, name, gap, value, rest) => {
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

function againstSit(engine) {
  const own = { name: 'phreeqc.dat with a SIT block', text: `${SIT_OWN}${dbText}` };
  // A saline water: the page's coefficients at PHREEQC's molalities, and its start on them.
  const saline = `${KNOBS}SOLUTION 1\n temp 25\n units mol/kgw\n pH 7.5\n Na 1.5\n K 0.1\n Ca 0.02\n Mg 0.01\n`
    + ' Cl 1.66 charge\n C(4) 0.003\n S(6) 0.005\nEND\n';
  engine.load(own.text);
  const res = P.waterToModel({ engine, database: own, water: { name: 'saline', text: saline }, activity: true, exact: true,
    redox: false });
  const m = RtmModel.compile(res.text);
  const ns = m.speciesNames.length;
  const C = new Float64Array(ns);
  for (const [p, n] of res.names) C[m.speciesNames.indexOf(n)] = res.molal.get(p);
  const lnG = new Float64Array(ns);
  const w = RtmModel.activityAt(m.act, C, 0, lnG, new Float64Array(ns));
  let worstG = 0;
  let at = '';
  for (const [p, n] of res.names) {
    const d = Math.abs(lnG[m.speciesNames.indexOf(n)] / Math.LN10 - res.water.species.get(p)[1]);
    if (d > worstG) { worstG = d; at = n; }
  }
  const dAw = Math.abs(w.lnAw / Math.LN10 - Math.log10(res.water.aw));
  check('SIT: the page\'s coefficients at PHREEQC\'s molalities are PHREEQC\'s, and so is the water\'s activity',
    worstG < 1e-12 && dAw < 1e-14, `log gamma within ${worstG.toExponential(1)} (${at}), log a(H2O) within `
      + `${dAw.toExponential(1)}, at I = ${res.water.mu.toFixed(3)}`);
  const y = m.toConcentrations(m.initialState());
  let worst = 0;
  for (const [p, n] of res.names) worst = Math.max(worst, Math.abs(y[m.speciesNames.indexOf(n)] / res.molal.get(p) - 1));
  const sitLines = res.text.split('\n<SIT>\n')[1].split('\n<REACTIONS>')[0].trim().split('\n');
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
    + 'under SIT stay on them', !!gap && view.report.activity.kind === 'sit' && Math.abs(gap.by) < 1e-6
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
    .replace(/^(\S+)(\s+)([0-9][0-9.eE+-]*)(.*)$/gm, (line, name, gap, value, rest) => {
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
    const sres = P.waterToModel({ engine, database: sd, water: { name: label, text: `${KNOBS}${wt}` }, activity: true,
      exact: true, redox: false });
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
    + 'in three waters', lines.every((l) => l.gw < 1e-12 && l.aw < 1e-14 && l.start < 1e-8),
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
