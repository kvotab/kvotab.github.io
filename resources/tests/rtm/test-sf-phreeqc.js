#!/usr/bin/env node
/* ==========================================================================
   RTM.HTML: THE SIMPLE FUNCTIONS ON PHREEQC

       node resources/tests/rtm/test-sf-phreeqc.js

   rtm-sf-phreeqc.js turns SimpleFunctions.html's own data (sf-data.js) into
   a PHREEQC database -- phreeqc.dat with the Simple Functions' species and
   solids put in -- and the Batch tab's input for Version A or B. Run here
   through the page's own PHREEQC (vendors/phreeqc), as the batch runs it:

     * the definitions: 158 species, 48 solids, a named expression each, the
       18 elements phreeqc.dat lacks, phreeqc.dat's other species of Sr and
       Pb left out, and methane and sulfide;
     * the database loads, and PHREEQC's log K of every species and solid is
       the converted constant; from PHREEQC's activities in three waters,
       every one of the Simple Functions' own constants comes back;
     * Version B's conditioned water: at its pH, goethite and magnetite at
       saturation, and its free HCO3- exactly the table's; Version A's water
       at its Eh;
     * both versions on the reference waters of TR-10-61 against sf-model.js
       (every term from the reactions, dimers counted twice): within 0.32 log
       units, element by element, but for the few the solid's own dissolution
       moves (radium sulphate in Gideå's water, silver chloride in the ocean)
       and the three most saline waters, left out;
     * the input with the constants drawn: all at nought is the input as
       they are; one solid's +1 raises its element tenfold;
     * a run whose pH is not where it was asked gives no totals;
     * the table's columns as the Simple Functions read them;
     * the Simple Functions' own ways, ticked: the pH read as [H+], held
       exactly for the kilogram of water the water starts with; the water
       kept as it is, each limit from the solid's saturation index at a
       trace of it, the same as PHREEQC's own phase constraint where the
       element stays a trace; with both, every element's median over the
       reference waters within 0.06 log units of sf-model.js's in both
       versions, and the constants drawn as before.

   Exit status is 0 when every check passed.
   ========================================================================== */
'use strict';

const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..', '..', '..');
const jsDir = path.join(root, 'resources', 'js');
const SF = require(path.join(jsDir, 'sf-model.js'));
const D = require(path.join(jsDir, 'sf-data.js'));
const M = require(path.join(jsDir, 'rtm-model.js'));
const P = require(path.join(jsDir, 'rtm-sf-phreeqc.js'));
const E = require(path.join(jsDir, 'rtm-phreeqc-engine.js'));
const createPhreeqc = require(path.join(root, 'vendors', 'phreeqc', 'phreeqc.js'));

let checks = 0;
const failures = [];
function check(what, ok, detail) {
  checks++;
  if (ok) console.log(`  ok    ${what}`);
  else { console.log(`  FAIL  ${what}${detail ? `: ${detail}` : ''}`); failures.push(what); }
}

const sandbox = {};
new Function('self', fs.readFileSync(path.join(root, 'vendors', 'phreeqc', 'phreeqc-dat.js'), 'utf8'))(sandbox);
const BASE = sandbox.PHREEQC_DAT;

(async () => {
  console.log('The definitions');
  const built = P.build(D.SRSITE, SF, BASE, M.ATOMIC_WEIGHTS);
  const nSp = D.SRSITE.elements.reduce((a, e) => a + e.species.length, 0);
  const nSo = D.SRSITE.elements.reduce((a, e) => a + e.solids.length, 0);
  check(`every species (${nSp}) and solid (${nSo}) of the 20 elements`, built.species.length === nSp && built.solids.length === nSo && nSp === 158 && nSo === 48);
  check('a named expression for each, dK_ and its name', built.named.length === 206 && built.named.includes('dK_UO2:2H2O(am)') && built.named.includes('dK_(UO2)2CO3(OH)3-'));
  const masters = (built.text.match(/^SOLUTION_MASTER_SPECIES\n([^]*?)\n\n/m) || ['', ''])[1].split('\n');
  check('the 18 elements phreeqc.dat lacks, and the markers of free HCO3- and of [H+]', masters.length === 20 && !masters.some((l) => /^(Sr|Pb)\s/.test(l))
    && masters.some((l) => /^Mark\s+Mark-/.test(l)) && masters.some((l) => /^Markh\s+Markh\+/.test(l)));
  check("phreeqc.dat's species of Pb the Simple Functions do not have, and CH4 and HS-, left out",
    ['Pb2OH+3', 'PbSO4', 'Pb(CO3)2-2', 'PbHCO3+', 'PbF+', 'CH4', 'HS-'].every((n) => built.suppressed.includes(n)) && !built.suppressed.some((n) => /^Sr/.test(n)));
  check('the solids named as the Simple Functions name them, no comma nor space',
    ['Zr(OH)4(am_aged)', 'TcO2:1.63H2O(s)', 'ThO2:2H2O(am_aged)', 'Coffinite'].every((n) => built.solids.some((s) => s.name === n))
    && built.solids.every((s) => !/[,\s]/.test(s.name)));
  check('Zr(OH)4(am,fresh) is defined but not among the solids tried, as in the Simple Functions',
    built.solids.some((s) => s.id === 'Zr(OH)4(am,fresh)') && !P.solidsSpec(built).includes('am_fresh'));
  const tcO4 = built.species.find((s) => s.id === 'TcO4-');
  check('TcO4-: O2(g) taken out, log K -29.385, three electrons', tcO4 && tcO4.eq === 'TcO(OH)2 + H2O = TcO4- + 4 H+ + 3 e-' && Math.abs(tcO4.logKPhreeqc + 29.385) < 1e-9);
  check("goethite and magnetite at the Simple Functions' constants",
    built.fe[0].eq === 'FeOOH + 3 H+ + e- = Fe+2 + 2 H2O' && Math.abs(built.fe[0].logKPhreeqc - 12.025) < 1e-9
    && built.fe[1].eq === 'Fe3O4 + 8 H+ + 2 e- = 3 Fe+2 + 4 H2O' && Math.abs(built.fe[1].logKPhreeqc - 36.06) < 1e-9);
  const db = P.database(BASE, built);
  check("put in before phreeqc.dat's END, its first", db.indexOf('Fix_HCO3-') < db.search(/^END\s*$/m));

  console.log('PHREEQC with the database');
  const engine = await E.create(createPhreeqc);
  let loaded = true;
  try { engine.load(db); } catch (e) { loaded = false; check('the database loads', false, e.message.slice(0, 300)); }
  if (!loaded) return finish();
  check('the database loads', true);
  const run = (input, n = 1) => {
    const got = engine.run(`DELETE\n -all\nEND\n${input}\nEND\n`, n);
    return Object.fromEntries(got[0].map((h, k) => [h, got[got.length - 1][k]]));
  };
  const all = [...built.species, ...built.solids];
  const lk = run(`SOLUTION 1\n pH 7\nUSER_PUNCH 1\n -headings ${all.map((_, i) => `k${i}`).join(' ')}\n`
    + `${built.species.map((s, i) => `${10 + i} PUNCH LK_SPECIES("${s.name}")`).join('\n')}\n`
    + `${built.solids.map((s, i) => `${1000 + i} PUNCH LK_PHASE("${s.name}")`).join('\n')}\nSELECTED_OUTPUT 1\n -reset false\n`);
  const worstLk = Math.max(...all.map((s, i) => Math.abs(lk[`k${i}`] - s.logKPhreeqc)));
  check("PHREEQC's log K of every species and solid is the converted constant", worstLk < 1e-12, `largest difference ${worstLk}`);
  // The Simple Functions' constants worked back from PHREEQC's activities, O2(g) through log K 83.1.
  const names = new Set();
  for (const s of built.species) { const rx = SF.parseReaction(s.rx); [...rx.left, ...rx.right].forEach((t) => names.add(P.phreeqcFormula(t.formula))); }
  for (const s of built.solids) { const rx = SF.parseReaction(s.rx); [...rx.left.slice(1), ...rx.right].forEach((t) => names.add(P.phreeqcFormula(t.formula))); }
  names.delete('O2(g)');
  const list = [...names];
  const back = (pH, pe) => {
    const A = run(`SOLUTION 1\n units mol/kgw\n pH ${pH}\n pe ${pe}\n Ca 0.02\n Na 0.09\n Cl 0.13\n S(6) 0.005\n C(4) 0.002\n Si 1e-4\n Fe 1e-5\n`
      + `${D.SRSITE.elements.map((e) => ` ${e.el} 1e-12`).join('\n')}\nUSER_PUNCH 1\n -headings ${[...list.map((n) => `la_${n}`), ...built.solids.map((s) => `si_${s.name}`), 'pe', 'pH'].join(' ')}\n`
      + `${list.map((n, i) => `${10 + i} PUNCH LA("${n}")`).join('\n')}\n${built.solids.map((s, i) => `${5000 + i} PUNCH SI("${s.name}")`).join('\n')}\n`
      + '9990 PUNCH -LA("e-"), -LA("H+")\nSELECTED_OUTPUT 1\n -reset false\n');
    const logO2 = 2 * A.la_H2O - P.LOGK_O2 + 4 * A.pH + 4 * A.pe;
    const la = (f) => (f === 'O2(g)' ? logO2 : A[`la_${f}`]);
    let worst = 0;
    for (const s of built.species) {
      const rx = SF.parseReaction(s.rx);
      const k = rx.right.reduce((v, t) => v + t.coef * la(P.phreeqcFormula(t.formula)), 0) - rx.left.reduce((v, t) => v + t.coef * la(P.phreeqcFormula(t.formula)), 0);
      worst = Math.max(worst, Math.abs(k - s.logK));
    }
    for (const s of built.solids) {
      const rx = SF.parseReaction(s.rx);
      const iap = rx.right.reduce((v, t) => v + t.coef * la(P.phreeqcFormula(t.formula)), 0) - rx.left.slice(1).reduce((v, t) => v + t.coef * la(P.phreeqcFormula(t.formula)), 0);
      worst = Math.max(worst, Math.abs(iap - A[`si_${s.name}`] - s.logK));
    }
    return worst;
  };
  for (const [pH, pe] of [[6.5, -2], [7.5, -3.5], [9.5, -6]]) {
    const w = back(pH, pe);
    check(`at pH ${pH} and pe ${pe}, every one of the Simple Functions' constants back from the activities`, w < 1e-12, `largest difference ${w}`);
  }
  const red = run('SOLUTION 1\n units mol/kgw\n pH 7.5\n pe -6\n Na 0.01\n Cl 0.01\n C(4) 0.002\n S(6) 0.001\nSELECTED_OUTPUT 1\n -reset false\n -molalities CH4 HS-\n');
  check('no methane and no sulfide, even at pe -6', red['m_CH4(mol/kgw)'] < 1e-90 && red['m_HS-(mol/kgw)'] < 1e-90);

  console.log("The reference waters' table");
  const rows = P.referenceRows(D.TR1061_WATERS);
  const columns = rows[0].map(String);
  const { cols, missingA, missingB } = P.columnsOf(SF, columns);
  check('12 waters, every column Version A and B need, Mg and K too', rows.length === 13 && !missingA.length && !missingB.length && cols.Mg && cols.K);
  const starred = P.columnsOf(SF, ['X(km)', 'pH', '[Ca]tot (m)', '[Cl]tot (m)', '[Na]tot (m)', '[SO4-2]tot (m)**', '[Si]tot (m)', 'IS (mol/kg)', '[HCO3-] (m)*']);
  check('columns with footnote stars read; Eh and iron missing for Version A only',
    starred.cols.SO4 === '[SO4-2]tot (m)**' && starred.cols.HCO3 === '[HCO3-] (m)*' && !starred.missingB.length && starred.missingA.join() === 'Eh,Fe');
  const fill = (t, row, solid, extra = {}) => t.replace(/\{([^{}\n]+)\}/g, (m, name) => (name === 'solid' ? solid
    : name in extra ? String(extra[name]) : columns.includes(name) ? String(row[columns.indexOf(name)] ?? '') : m));

  console.log('Version B: the conditioned water');
  const inputB = P.input(built, { version: 'B', drawn: false, cols });
  const forsmark = rows[1];
  const cond = inputB.slice(0, inputB.indexOf('SAVE solution 1')).replace(/^#.*\n/gm, '');
  const c = run(fill(`${cond}SELECTED_OUTPUT 1\n -reset false\nUSER_PUNCH 1\n -headings pH mHCO3 siGoe siMag kgw\n 10 PUNCH -LA("H+"), MOL("HCO3-"), SI("Goethite"), SI("Magnetite"), TOT("water")\n`, forsmark, ''));
  const hco3 = forsmark[columns.indexOf(cols.HCO3)];
  check("Forsmark's water at its pH, goethite and magnetite at saturation", Math.abs(c.pH - forsmark[1]) < 1e-9 && Math.abs(c.siGoe) < 1e-9 && Math.abs(c.siMag) < 1e-9);
  // The marker is so many moles: the free HCO3- is the table's for the kilogram of water the water started with.
  check("its free HCO3- the table's, for the kilogram of water it started with", Math.abs(c.mHCO3 * c.kgw / hco3 - 1) < 1e-9 && Math.abs(c.mHCO3 / hco3 - 1) < 1e-3,
    `${c.mHCO3} mol/kgw in ${c.kgw} kg for ${hco3}`);
  const inputA = P.input(built, { version: 'A', drawn: false, cols });
  const condA = inputA.slice(0, inputA.indexOf('SAVE solution 1')).replace(/^#.*\n/gm, '');
  const a = run(fill(`${condA}SELECTED_OUTPUT 1\n -reset false\nUSER_PUNCH 1\n -headings pe mHCO3\n 10 PUNCH -LA("e-"), MOL("HCO3-")\n`, forsmark, ''));
  const eh = forsmark[columns.indexOf(cols.Eh)];
  check("Version A: Forsmark's water at its Eh, pe = Eh / 59.16 (to the water's activity)", Math.abs(a.pe - eh / 59.16) < 1e-4, `pe ${a.pe} for Eh ${eh}`);

  console.log('Both versions against sf-model.js');
  const els = built.elements;
  const lowest = (input, row) => els.map((e) => {
    let best = null;
    for (const solid of e.solids) {
      try {
        const v = run(fill(input, row, solid))[`${e.el}(mol/kgw)`];
        if (typeof v === 'number' && (best === null || v < best)) best = v;
      } catch (er) { /* refused: the lowest is of the others */ }
    }
    return best;
  });
  const saline = /saline|salinity/i;
  for (const version of ['B', 'A']) {
    const plan = SF.compile(D.SRSITE, { version, reactionTerms: true, polyStoichiometry: true });
    const exceptions = new Set(['Gideå Ra', 'Ocean water Ag']);
    let n = 0, near = 0, worst = 0, at = '';
    const far = [];
    for (const [i, w] of D.TR1061_WATERS.entries()) {
      if (saline.test(w.id) || w.id.startsWith('Cement') || (version === 'A' && !Number.isFinite(w.Eh))) continue;
      const sf = SF.evaluateWater(plan, { ...w, Ca: w.Ca + (w.Mg || 0) });
      const got = lowest(version === 'A' ? inputA : inputB, rows[1 + i]);
      els.forEach((e, k) => {
        if (got[k] === null) return;
        const d = Math.log10(got[k]) - Math.log10(sf.elements[k].S);
        n++;
        const key = `${w.id.split(' ')[0]} ${e.el}`;
        if (exceptions.has(key) || exceptions.has(`${w.id} ${e.el}`)) return;
        if (Math.abs(d) <= 0.32) near++; else far.push(`${key} ${d.toFixed(2)}`);
        if (Math.abs(d) > worst) { worst = Math.abs(d); at = key; }
      });
    }
    check(`Version ${version}: ${n} results, every one within 0.32 log units of the Simple Functions' but the solid's own (largest ${worst.toFixed(2)}, ${at})`,
      n >= (version === 'A' ? 119 : 159) && !far.length, far.join(', '));
  }
  const gideB = lowest(inputB, rows[5])[els.findIndex((e) => e.el === 'Ra')];
  check("Gideå's radium: radium sulphate's own sulphate brings it a factor of ten below", gideB && Math.log10(gideB) < -4.8 && Math.log10(gideB) > -5.2, String(gideB));

  console.log('The constants drawn');
  const drawnB = P.input(built, { version: 'B', drawn: true, cols });
  const zero = Object.fromEntries(built.named.map((nm) => [nm, 0]));
  const uNom = run(fill(inputB, forsmark, 'UO2:2H2O(am)'))['U(mol/kgw)'];
  const uZero = run(fill(drawnB, forsmark, 'UO2:2H2O(am)', zero))['U(mol/kgw)'];
  const uUp = run(fill(drawnB, forsmark, 'UO2:2H2O(am)', { ...zero, 'dK_UO2:2H2O(am)': 1 }))['U(mol/kgw)'];
  check('every constant drawn at nought: the input as they are', Math.abs(uZero / uNom - 1) < 1e-9, `${uZero} for ${uNom}`);
  check("UO2:2H2O(am)'s constant +1: uranium tenfold", Math.abs(uUp / uZero - 10) < 1e-6, String(uUp / uZero));
  const spec = P.uncertainSpec(built).split(';').map((x) => x.trim());
  check('Uncertain: every constant normal about nought, its ± two standard deviations',
    spec.length === 206 && spec.includes('dK_UO2:2H2O(am) normal 0 0.545') && spec.includes('dK_SrOH+ normal 0 0.15'));

  console.log('A pH not held');
  const offTarget = fill(inputB, forsmark, 'UO2:2H2O(am)').replace(/IF ABS\(-LA\("H\+"\) - ([0-9.]+)\)/, (m, x) => `IF ABS(-LA("H+") - ${Number(x) + 0.01})`);
  const off = run(offTarget);
  check('gives no totals, so that it is never the lowest', typeof off['U(mol/kgw)'] !== 'number' && typeof off.pH === 'number');

  // A named expression an input sets stays so in PHREEQC for the inputs after it (the +1 above): the database afresh.
  engine.load(db);
  console.log("The Simple Functions' ways: the pH as a concentration");
  const pHmB = P.input(built, { version: 'B', cols, pHm: true });
  const condM = pHmB.slice(0, pHmB.indexOf('SAVE solution 1')).replace(/^#.*\n/gm, '');
  const m = run(fill(`${condM}SELECTED_OUTPUT 1\n -reset false\nUSER_PUNCH 1\n -headings mH aH kgw siGoe\n 10 PUNCH MOL("H+"), -LA("H+"), TOT("water"), SI("Goethite")\n`, forsmark, ''));
  const pH0 = forsmark[1];
  check("Forsmark's conditioned water: [H+] = 10^-pH for the kilogram of water it started with, goethite at saturation",
    Math.abs(m.mH * m.kgw / Math.pow(10, -pH0) - 1) < 1e-9 && Math.abs(-Math.log10(m.mH) - pH0) < 1e-3 && Math.abs(m.siGoe) < 1e-9,
    `[H+] ${m.mH} in ${m.kgw} kg`);
  check("PHREEQC's own pH, the activity's, a tenth of a unit above at its ionic strength", m.aH - pH0 > 0.08 && m.aH - pH0 < 0.13, String(m.aH - pH0));
  const pHmA = P.input(built, { version: 'A', cols, pHm: true });
  const mA = run(fill(`${pHmA.slice(0, pHmA.indexOf('SAVE solution 1')).replace(/^#.*\n/gm, '')}SELECTED_OUTPUT 1\n -reset false\nUSER_PUNCH 1\n -headings mH pe\n 10 PUNCH MOL("H+"), -LA("e-")\n`, forsmark, ''));
  check("Version A: [H+] = 10^-pH in the water as the table gives it, and its Eh", Math.abs(mA.mH / Math.pow(10, -pH0) - 1) < 1e-9 && Math.abs(mA.pe - eh / 59.16) < 1e-4);
  const niK = els.findIndex((e) => e.el === 'Ni');
  const niAct = lowest(inputB, forsmark)[niK], niConc = lowest(pHmB, forsmark)[niK];
  check("nickel, whose solid dissolves with [H+] squared, twice the pH's shift lower", Math.abs(Math.log10(niAct / niConc) - 2 * (m.aH - pH0)) < 0.02,
    `${Math.log10(niAct / niConc).toFixed(3)} for ${(m.aH - pH0).toFixed(3)}`);
  const offM = run(fill(pHmB, forsmark, 'UO2:2H2O(am)').replace(/IF ABS\(SI\("Fix_mH\+"\) - ([0-9.]+)\)/, (mm, x) => `IF ABS(SI("Fix_mH+") - ${Number(x) + 0.01})`));
  check('[H+] not where it was asked: no totals', typeof offM['U(mol/kgw)'] !== 'number' && typeof offM.pH === 'number');

  console.log("The Simple Functions' ways: the water kept as it is");
  const keptB = P.input(built, { version: 'B', cols, kept: true });
  check('no solid dissolves: a trace of the solid in the water conditioned, each solid\'s limit from its saturation index',
    !/\{solid\} 0 /.test(keptB) && keptB.includes('USE solution 1\nREACTION 1\n {solid} 1\n 1e-12 moles\nEQUILIBRIUM_PHASES 2\n Goethite 0 10\n Magnetite 0 10\n Fix_H+')
    && (keptB.match(/^END$/gm) || []).length === 2
    && keptB.includes(' IF s$ = "Nb2O5(s)" THEN v(4) = TOT("Nb") * 10^(-SI(s$) / 2)') && keptB.includes(' IF s$ = "Becquerelite" THEN'));
  // The exact limit in the same water: the conditioned water written out, the element set by the solid in PHREEQC's
  // initial solution, where the element stays a trace and changes nothing.
  const condK = keptB.slice(0, keptB.indexOf('SAVE solution 1')).replace(/^#.*\n/gm, '');
  const w0 = run(fill(`${condK}SELECTED_OUTPUT 1\n -reset false\nUSER_PUNCH 1\n -headings pHa pe Ca Mg Na K Cl S Si C Fe\n`
    + ' 10 PUNCH -LA("H+"), -LA("e-"), TOT("Ca"), TOT("Mg"), TOT("Na"), TOT("K"), TOT("Cl"), TOT("S(6)"), TOT("Si"), TOT("C(4)"), TOT("Fe")\n', forsmark, ''));
  const written = [` pH ${w0.pHa}`, ` pe ${w0.pe}`, ...['Ca', 'Mg', 'Na', 'K', 'Cl', 'Si', 'Fe'].map((k) => ` ${k} ${w0[k]}`), ` S(6) ${w0.S}`, ` C(4) ${w0.C}`];
  let worstK = 0, atK = '';
  // (Not coffinite: the table gives Forsmark's water silica of 1e-20, which no uranium saturates it with.)
  for (const [el, solid] of [['Zr', 'Zr(OH)4(am_aged)'], ['Tc', 'TcO2:1.63H2O(s)'], ['Th', 'ThO2:2H2O(am_aged)'], ['Pa', 'Pa2O5(s)'], ['U', 'UO2:2H2O(am)'],
    ['Np', 'NpO2:2H2O(am)'], ['Pd', 'Pd(OH)2(s)']]) {
    const exact = run(`SOLUTION 1\n units mol/kgw\n${written.join('\n')}\n ${el} 1e-9 ${solid} 0\nSELECTED_OUTPUT 1\n -reset false\nUSER_PUNCH 1\n -headings T\n 10 PUNCH TOT("${el}")\n`).T;
    const got = run(fill(keptB, forsmark, solid))[`${el}(mol/kgw)`];
    const d = Math.abs(Math.log10(got / exact));
    if (!(d <= worstK)) { worstK = d; atK = `${el} ${solid}`; }
  }
  check("Forsmark: the limit the same as PHREEQC's own phase constraint, where the element stays a trace (Zr, Tc, Th, Pa, U, Np, Pd)",
    worstK < 1e-5, `${worstK} at ${atK}`);
  const srK = els.findIndex((e) => e.el === 'Sr'), raK = els.findIndex((e) => e.el === 'Ra');
  const planB = SF.compile(D.SRSITE, { version: 'B', reactionTerms: true, polyStoichiometry: true });
  const gw = D.TR1061_WATERS[4];
  const sfGide = SF.evaluateWater(planB, { ...gw, Ca: gw.Ca + (gw.Mg || 0) }).elements;
  const gideKept = lowest(keptB, rows[5]);
  check("Gideå's radium, kept: the Simple Functions' own, no longer a factor of ten below", gw.id === 'Gideå'
    && Math.abs(Math.log10(gideKept[raK] / sfGide[raK].S)) < 0.1, `${gideKept[raK]} for ${sfGide[raK].S}`);
  const srDiss = lowest(inputB, forsmark)[srK], srKept = lowest(keptB, forsmark)[srK];
  check("Forsmark's strontium, kept: higher, its solid's own sulphate and carbonate no longer in the water", srKept > srDiss * 1.1, `${srKept} for ${srDiss}`);

  console.log('Both ways against sf-model.js');
  for (const version of ['B', 'A']) {
    const plan = SF.compile(D.SRSITE, { version, reactionTerms: true, polyStoichiometry: true });
    const both = P.input(built, { version, cols, pHm: true, kept: true });
    const diffs = els.map(() => []);
    for (const [i, w] of D.TR1061_WATERS.entries()) {
      if (saline.test(w.id) || w.id.startsWith('Cement') || (version === 'A' && !Number.isFinite(w.Eh))) continue;
      const sf = SF.evaluateWater(plan, { ...w, Ca: w.Ca + (w.Mg || 0) });
      lowest(both, rows[1 + i]).forEach((v, k) => { if (v > 0) diffs[k].push(Math.log10(v / sf.elements[k].S)); });
    }
    const med = (a) => { const b = a.slice().sort((x, y) => x - y); return b.length ? b[Math.floor(b.length / 2)] : NaN; };
    const meds = diffs.map(med);
    const worst = Math.max(...meds.map(Math.abs));
    const n = diffs.reduce((a, d) => a + d.length, 0);
    check(`Version ${version}, both ticked: ${n} results, every element's median within 0.06 log units of the Simple Functions' (largest ${worst.toFixed(3)}, ${els[meds.map(Math.abs).indexOf(worst)].el})`,
      worst <= 0.06 && n >= (version === 'A' ? 120 : 160));
  }

  console.log('The constants drawn, the water kept');
  const drawnK = P.input(built, { version: 'B', drawn: true, cols, kept: true });
  const kNom = run(fill(keptB, forsmark, 'UO2:2H2O(am)'))['U(mol/kgw)'];
  const kZero = run(fill(drawnK, forsmark, 'UO2:2H2O(am)', zero))['U(mol/kgw)'];
  const kUp = run(fill(drawnK, forsmark, 'UO2:2H2O(am)', { ...zero, 'dK_UO2:2H2O(am)': 1 }))['U(mol/kgw)'];
  check('every constant drawn at nought: the input as they are', Math.abs(kZero / kNom - 1) < 1e-9, `${kZero} for ${kNom}`);
  check("UO2:2H2O(am)'s constant +1: uranium tenfold, exactly", Math.abs(kUp / kZero - 10) < 1e-9, String(kUp / kZero));
  return finish();
})().catch((e) => { console.log(`  FAIL  ${e.stack}`); failures.push('crashed'); finish(); });

function finish() {
  console.log(`\n${checks - failures.length} of ${checks} checks passed`);
  process.exit(failures.length ? 1 : 0);
}
