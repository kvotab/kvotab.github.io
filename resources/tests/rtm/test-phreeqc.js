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
    .replace(/^(\S+)(\s+)([0-9][0-9.eE+-]*)(.*)$/gm, (line, name, gap, value, rest) => {
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
  const handOff = (db, water, label, redox = false) => {
    engine.load(db.text);
    const res = P.waterToModel({ engine, database: db, water: { name: label, text: water }, activity: true, exact: true,
      redox, floor: 1e-30 });
    const m = RtmModel.compile(res.text);
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
    ['APHI', '-Aphi\n  0.392 -11 0 0 0.0001\n', 50]].map(([label, opts, tc]) => ({ label, ...handOff(own(opts), saline(tc), label) }));
  check('  the page\'s coefficients and water at PHREEQC\'s molalities are PHREEQC\'s: every type of parameter, at 25 and '
    + '70 C, without the MacInnes scaling and E-theta, and with APHI', cases.every((c) => c.gam < 1e-11 && c.aw < 1e-12),
  cases.map((c) => `${c.label}: log gamma ${c.gam.toExponential(1)}, ln a(H2O) ${c.aw.toExponential(1)}`).join('; ')
    + `; I = ${cases[0].I.toFixed(2)}`);
  const pzBody = (t) => t.split('\n<PITZER>\n')[1].split('\n<REACTIONS>')[0].trim().split('\n');
  const species = (t) => t.split('<SPECIES>')[1].split('<EQUILIBRIUM>')[0];
  check('  the hand-off: ACTIVITY = pitzer, the database\'s parameters between the species written with their terms in '
    + 'the temperature, MACINNES no, ETHETA no and APHI where the database says so, no a or b, and the page starts on '
    + 'PHREEQC\'s water', cases.every((c) => /^ACTIVITY = pitzer$/m.test(c.res.text) && c.start < 1e-10
      && pzBody(c.res.text).filter((l) => !/^(MACINNES|ETHETA|APHI)\b/.test(l)).length === c.res.report.activity.pitzer
      && !/\ba=/.test(species(c.res.text)))
    && /^B0\s+Na\+\s+Cl-\s+0\.08\s+-700\s+-4\s+0\.009\s+-0\.000003$/m.test(cases[0].res.text)
    && /^MACINNES  no$/m.test(cases[2].res.text) && /^ETHETA  no$/m.test(cases[2].res.text)
    && /^APHI  0\.392  -11  0  0  0\.0001$/m.test(cases[3].res.text),
  cases.map((c) => `${c.label}: ${c.res.report.activity.pitzer} parameters, the start within ${c.start.toExponential(1)}`)
    .join('; '));

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
  const pzCases = [['seawater', seawater], ['a 60 C brine over gypsum', hotBrine], ['no chloride', noCl]]
    .map(([label, w]) => ({ label, ...handOff(pzdb, w.replace('EQUILIBRIUM_PHASES', 'EQUILIBRIUM_PHASES'), label) }));
  check('  pitzer.dat: seawater, a 60 C brine over gypsum and a water with no chloride, scaled by the Cl- it would have: '
    + 'the coefficients at PHREEQC\'s molalities, and the start of the model written from each, PHREEQC\'s',
  pzCases.every((c) => c.gam < 1e-11 && c.aw < 1e-12 && c.start < 1e-9),
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
  console.log('\n--- CD-MUSIC: the reading, the hand-off, acid against REACTION, the PHREEQC tab ---');
  againstCdMusic(wasm);
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
